"""Persistence ports and local SQLite implementation.

The runtime only needs a small persistence boundary.  Keeping this module
independent from Skills makes the in-memory implementation useful in tests
and leaves room for a database/object-storage adapter later.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def _load_json(value: str | bytes | None, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Project:
    project_id: str
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Artifact:
    """A versioned output with explicit source and dependency metadata."""

    artifact_id: str
    artifact_type: str
    project_id: str
    schema_version: str = "1.0"
    source_file_versions: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    created_by_run: str | None = None
    created_at: str = ""
    content_hash: str = ""
    status: str = "valid"
    stale_reason: str | None = None
    content: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = dict(self.content)
        result.update(
            {
                "artifact_id": self.artifact_id,
                "artifact_type": self.artifact_type,
                "project_id": self.project_id,
                "schema_version": self.schema_version,
                "source_file_versions": list(self.source_file_versions),
                "dependencies": list(self.dependencies),
                "created_by_run": self.created_by_run,
                "created_at": self.created_at,
                "content_hash": self.content_hash,
                "status": self.status,
                "stale_reason": self.stale_reason,
            }
        )
        return result


@dataclass(frozen=True)
class AgentRun:
    """Serializable execution checkpoint used for restart and resume."""

    run_id: str
    project_id: str = ""
    request: dict[str, Any] = field(default_factory=dict)
    plan: list[dict[str, Any]] = field(default_factory=list)
    status: str = "running"
    steps: list[dict[str, Any]] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    trace: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)
    artifact_ids: list[str] = field(default_factory=list)
    next_step_index: int = 0
    elapsed_ms: int = 0
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HumanReviewTask:
    review_id: str
    project_id: str
    severity: str = "warning"
    review_type: str = "manual_check"
    requirement_id: str | None = None
    question: str = ""
    status: str = "open"
    source_run_id: str | None = None
    affected_artifact_ids: list[str] = field(default_factory=list)
    resolution: dict[str, Any] | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Store(Protocol):
    """Minimal persistence contract used by the local runtime."""

    def ensure_project(
        self, project_id: str, metadata: Mapping[str, Any] | None = None
    ) -> Project: ...

    def get_project(self, project_id: str) -> Project | None: ...

    def save_file(self, record: Any, content: bytes) -> None: ...

    def get_file(self, file_id: str) -> Any | None: ...

    def file_content(self, file_id: str) -> bytes: ...

    def list_files(
        self, project_id: str, file_role: str | None = None
    ) -> list[Any]: ...

    def save_artifact(self, artifact: Artifact) -> None: ...

    def get_artifact(self, artifact_id: str) -> Artifact | None: ...

    def list_artifacts(
        self, project_id: str, status: str | None = None
    ) -> list[Artifact]: ...

    def invalidate_from_files(self, file_ids: list[str]) -> list[str]: ...

    def save_run(self, run: AgentRun) -> None: ...

    def get_run(self, run_id: str) -> AgentRun | None: ...

    def list_runs(self, project_id: str) -> list[AgentRun]: ...

    def save_review(self, task: HumanReviewTask) -> None: ...

    def get_review(self, review_id: str) -> HumanReviewTask | None: ...

    def list_reviews(
        self, project_id: str, status: str | None = None
    ) -> list[HumanReviewTask]: ...


class InMemoryStore:
    """Thread-safe store used by unit tests and explicitly ephemeral apps."""

    def __init__(self) -> None:
        self._projects: dict[str, Project] = {}
        self._files: dict[str, tuple[Any, bytes]] = {}
        self._artifacts: dict[str, Artifact] = {}
        self._runs: dict[str, AgentRun] = {}
        self._reviews: dict[str, HumanReviewTask] = {}
        self._lock = threading.RLock()

    def ensure_project(
        self, project_id: str, metadata: Mapping[str, Any] | None = None
    ) -> Project:
        with self._lock:
            existing = self._projects.get(project_id)
            if existing is not None:
                if metadata:
                    existing = replace(
                        existing,
                        updated_at=_now(),
                        metadata={**existing.metadata, **dict(metadata)},
                    )
                    self._projects[project_id] = existing
                return existing
            timestamp = _now()
            project = Project(
                project_id=project_id,
                created_at=timestamp,
                updated_at=timestamp,
                metadata=dict(metadata or {}),
            )
            self._projects[project_id] = project
            return project

    def get_project(self, project_id: str) -> Project | None:
        with self._lock:
            return self._projects.get(project_id)

    def save_file(self, record: Any, content: bytes) -> None:
        with self._lock:
            self._files[record.file_id] = (record, bytes(content))

    def get_file(self, file_id: str) -> Any | None:
        with self._lock:
            entry = self._files.get(file_id)
            return entry[0] if entry else None

    def file_content(self, file_id: str) -> bytes:
        with self._lock:
            entry = self._files.get(file_id)
            if entry is None:
                raise KeyError(file_id)
            return bytes(entry[1])

    def list_files(self, project_id: str, file_role: str | None = None) -> list[Any]:
        with self._lock:
            records = [
                record
                for record, _content in self._files.values()
                if record.project_id == project_id
                and (not file_role or record.file_role == file_role)
            ]
        return sorted(records, key=lambda item: (item.file_name, item.version))

    def save_artifact(self, artifact: Artifact) -> None:
        with self._lock:
            self._artifacts[artifact.artifact_id] = artifact

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        with self._lock:
            return self._artifacts.get(artifact_id)

    def list_artifacts(
        self, project_id: str, status: str | None = None
    ) -> list[Artifact]:
        with self._lock:
            artifacts = [
                artifact
                for artifact in self._artifacts.values()
                if artifact.project_id == project_id
                and (not status or artifact.status == status)
            ]
        return sorted(artifacts, key=lambda item: item.created_at)

    def invalidate_from_files(self, file_ids: list[str]) -> list[str]:
        with self._lock:
            stale_ids: set[str] = set()
            changed = set(file_ids)
            for artifact in self._artifacts.values():
                if any(
                    _source_matches(source, changed)
                    for source in artifact.source_file_versions
                ):
                    stale_ids.add(artifact.artifact_id)
            self._propagate_stale(stale_ids)
            return sorted(stale_ids)

    def _propagate_stale(self, stale_ids: set[str]) -> None:
        changed = True
        while changed:
            changed = False
            for artifact in self._artifacts.values():
                if artifact.artifact_id in stale_ids:
                    continue
                if any(dependency in stale_ids for dependency in artifact.dependencies):
                    stale_ids.add(artifact.artifact_id)
                    changed = True
        for artifact_id in stale_ids:
            artifact = self._artifacts[artifact_id]
            if artifact.status != "stale":
                self._artifacts[artifact_id] = replace(
                    artifact,
                    status="stale",
                    stale_reason="source file version changed",
                )

    def save_run(self, run: AgentRun) -> None:
        with self._lock:
            self._runs[run.run_id] = run

    def get_run(self, run_id: str) -> AgentRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def list_runs(self, project_id: str) -> list[AgentRun]:
        with self._lock:
            runs = [run for run in self._runs.values() if run.project_id == project_id]
        return sorted(runs, key=lambda item: item.created_at)

    def save_review(self, task: HumanReviewTask) -> None:
        with self._lock:
            self._reviews[task.review_id] = task

    def get_review(self, review_id: str) -> HumanReviewTask | None:
        with self._lock:
            return self._reviews.get(review_id)

    def list_reviews(
        self, project_id: str, status: str | None = None
    ) -> list[HumanReviewTask]:
        with self._lock:
            tasks = [
                task
                for task in self._reviews.values()
                if task.project_id == project_id
                and (not status or task.status == status)
            ]
        return sorted(tasks, key=lambda item: item.created_at)


class SQLiteStore:
    """Small SQLite-backed store suitable for the local service."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            self.path,
            check_same_thread=False,
            isolation_level=None,
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._initialize()

    def _initialize(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_files (
                    file_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    file_role TEXT NOT NULL,
                    material_type TEXT,
                    version INTEGER NOT NULL,
                    checksum TEXT NOT NULL,
                    uploaded_at TEXT NOT NULL,
                    parse_status TEXT NOT NULL,
                    page_count INTEGER,
                    parse_artifact_id TEXT,
                    supersedes TEXT,
                    parse_error TEXT,
                    metadata_json TEXT NOT NULL,
                    content BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_files_project
                    ON project_files(project_id, file_name, version);
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    artifact_type TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    source_file_versions_json TEXT NOT NULL,
                    dependencies_json TEXT NOT NULL,
                    created_by_run TEXT,
                    created_at TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stale_reason TEXT,
                    content_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_artifacts_project
                    ON artifacts(project_id, status, created_at);
                CREATE TABLE IF NOT EXISTS agent_runs (
                    run_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_runs_project
                    ON agent_runs(project_id, created_at);
                CREATE TABLE IF NOT EXISTS human_review_tasks (
                    review_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reviews_project
                    ON human_review_tasks(project_id, status, created_at);
                """
            )

    def ensure_project(
        self, project_id: str, metadata: Mapping[str, Any] | None = None
    ) -> Project:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if row is None:
                timestamp = _now()
                self._connection.execute(
                    "INSERT INTO projects VALUES (?, ?, ?, ?)",
                    (project_id, timestamp, timestamp, _json(dict(metadata or {}))),
                )
                return Project(
                    project_id=project_id,
                    created_at=timestamp,
                    updated_at=timestamp,
                    metadata=dict(metadata or {}),
                )
            existing_metadata = _load_json(row["metadata_json"], {})
            merged = {**existing_metadata, **dict(metadata or {})}
            timestamp = _now() if metadata else row["updated_at"]
            if metadata:
                self._connection.execute(
                    "UPDATE projects SET updated_at = ?, metadata_json = ? "
                    "WHERE project_id = ?",
                    (timestamp, _json(merged), project_id),
                )
            return Project(
                project_id=row["project_id"],
                created_at=row["created_at"],
                updated_at=timestamp,
                metadata=merged,
            )

    def get_project(self, project_id: str) -> Project | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
        if row is None:
            return None
        return Project(
            project_id=row["project_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=_load_json(row["metadata_json"], {}),
        )

    def save_file(self, record: Any, content: bytes) -> None:
        with self._lock:
            self._connection.execute(
                """INSERT OR REPLACE INTO project_files
                (file_id, project_id, file_name, file_role, material_type, version,
                 checksum, uploaded_at, parse_status, page_count, parse_artifact_id,
                 supersedes, parse_error, metadata_json, content)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.file_id,
                    record.project_id,
                    record.file_name,
                    record.file_role,
                    record.material_type,
                    record.version,
                    record.checksum,
                    record.uploaded_at,
                    record.parse_status,
                    record.page_count,
                    record.parse_artifact_id,
                    record.supersedes,
                    record.parse_error,
                    _json(record.metadata or {}),
                    sqlite3.Binary(content),
                ),
            )

    def get_file(self, file_id: str) -> Any | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM project_files WHERE file_id = ?", (file_id,)
            ).fetchone()
        return _file_from_row(row) if row is not None else None

    def file_content(self, file_id: str) -> bytes:
        with self._lock:
            row = self._connection.execute(
                "SELECT content FROM project_files WHERE file_id = ?", (file_id,)
            ).fetchone()
        if row is None:
            raise KeyError(file_id)
        return bytes(row["content"])

    def list_files(self, project_id: str, file_role: str | None = None) -> list[Any]:
        query = "SELECT * FROM project_files WHERE project_id = ?"
        params: list[Any] = [project_id]
        if file_role:
            query += " AND file_role = ?"
            params.append(file_role)
        query += " ORDER BY file_name, version"
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [_file_from_row(row) for row in rows]

    def save_artifact(self, artifact: Artifact) -> None:
        with self._lock:
            self._connection.execute(
                """INSERT OR REPLACE INTO artifacts
                (artifact_id, artifact_type, project_id, schema_version,
                 source_file_versions_json, dependencies_json, created_by_run,
                 created_at, content_hash, status, stale_reason, content_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    artifact.artifact_id,
                    artifact.artifact_type,
                    artifact.project_id,
                    artifact.schema_version,
                    _json(artifact.source_file_versions),
                    _json(artifact.dependencies),
                    artifact.created_by_run,
                    artifact.created_at,
                    artifact.content_hash,
                    artifact.status,
                    artifact.stale_reason,
                    _json(artifact.content),
                ),
            )

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
        return _artifact_from_row(row) if row is not None else None

    def list_artifacts(
        self, project_id: str, status: str | None = None
    ) -> list[Artifact]:
        query = "SELECT * FROM artifacts WHERE project_id = ?"
        params: list[Any] = [project_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at"
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [_artifact_from_row(row) for row in rows]

    def invalidate_from_files(self, file_ids: list[str]) -> list[str]:
        with self._lock:
            rows = self._connection.execute("SELECT * FROM artifacts").fetchall()
            artifacts = [_artifact_from_row(row) for row in rows]
            stale_ids: set[str] = {
                artifact.artifact_id
                for artifact in artifacts
                if any(
                    _source_matches(source, set(file_ids))
                    for source in artifact.source_file_versions
                )
            }
            changed = True
            while changed:
                changed = False
                for artifact in artifacts:
                    if artifact.artifact_id in stale_ids:
                        continue
                    if any(
                        dependency in stale_ids
                        for dependency in artifact.dependencies
                    ):
                        stale_ids.add(artifact.artifact_id)
                        changed = True
            for artifact in artifacts:
                if artifact.artifact_id in stale_ids and artifact.status != "stale":
                    self._connection.execute(
                        "UPDATE artifacts SET status = ?, stale_reason = ? "
                        "WHERE artifact_id = ?",
                        (
                            "stale",
                            "source file version changed",
                            artifact.artifact_id,
                        ),
                    )
            return sorted(stale_ids)

    def save_run(self, run: AgentRun) -> None:
        payload = run.to_dict()
        with self._lock:
            self._connection.execute(
                """INSERT OR REPLACE INTO agent_runs
                (run_id, project_id, status, created_at, updated_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    run.run_id,
                    run.project_id,
                    run.status,
                    run.created_at,
                    run.updated_at,
                    _json(payload),
                ),
            )

    def get_run(self, run_id: str) -> AgentRun | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload_json FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return _run_from_payload(_load_json(row["payload_json"], {})) if row else None

    def list_runs(self, project_id: str) -> list[AgentRun]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload_json FROM agent_runs WHERE project_id = ? "
                "ORDER BY created_at",
                (project_id,),
            ).fetchall()
        return [_run_from_payload(_load_json(row["payload_json"], {})) for row in rows]

    def save_review(self, task: HumanReviewTask) -> None:
        with self._lock:
            self._connection.execute(
                """INSERT OR REPLACE INTO human_review_tasks
                (review_id, project_id, status, created_at, updated_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    task.review_id,
                    task.project_id,
                    task.status,
                    task.created_at,
                    task.updated_at,
                    _json(task.to_dict()),
                ),
            )

    def get_review(self, review_id: str) -> HumanReviewTask | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload_json FROM human_review_tasks WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        return (
            _review_from_payload(_load_json(row["payload_json"], {}))
            if row
            else None
        )

    def list_reviews(
        self, project_id: str, status: str | None = None
    ) -> list[HumanReviewTask]:
        query = "SELECT payload_json FROM human_review_tasks WHERE project_id = ?"
        params: list[Any] = [project_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at"
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [
            _review_from_payload(_load_json(row["payload_json"], {}))
            for row in rows
        ]

    def close(self) -> None:
        with self._lock:
            self._connection.close()


def _source_matches(source: str, file_ids: set[str]) -> bool:
    return any(
        source == file_id or source.startswith(f"{file_id}:v")
        for file_id in file_ids
    )


def _file_from_row(row: sqlite3.Row) -> Any:
    from qiaowenshu_agent.core.files import ProjectFile

    return ProjectFile(
        file_id=row["file_id"],
        project_id=row["project_id"],
        file_name=row["file_name"],
        file_role=row["file_role"],
        material_type=row["material_type"],
        version=row["version"],
        checksum=row["checksum"],
        uploaded_at=row["uploaded_at"],
        parse_status=row["parse_status"],
        page_count=row["page_count"],
        parse_artifact_id=row["parse_artifact_id"],
        supersedes=row["supersedes"],
        parse_error=row["parse_error"],
        metadata=_load_json(row["metadata_json"], {}),
    )


def _artifact_from_row(row: sqlite3.Row) -> Artifact:
    return Artifact(
        artifact_id=row["artifact_id"],
        artifact_type=row["artifact_type"],
        project_id=row["project_id"],
        schema_version=row["schema_version"],
        source_file_versions=_load_json(row["source_file_versions_json"], []),
        dependencies=_load_json(row["dependencies_json"], []),
        created_by_run=row["created_by_run"],
        created_at=row["created_at"],
        content_hash=row["content_hash"],
        status=row["status"],
        stale_reason=row["stale_reason"],
        content=_load_json(row["content_json"], {}),
    )


def _run_from_payload(payload: Mapping[str, Any]) -> AgentRun:
    fields = {
        key: payload.get(key, default)
        for key, default in (
            ("run_id", ""),
            ("project_id", ""),
            ("request", {}),
            ("plan", []),
            ("status", "running"),
            ("steps", []),
            ("state", {}),
            ("output", {}),
            ("message", ""),
            ("trace", []),
            ("events", []),
            ("budget", {}),
            ("artifact_ids", []),
            ("next_step_index", 0),
            ("elapsed_ms", 0),
            ("created_at", ""),
            ("updated_at", ""),
        )
    }
    return AgentRun(**fields)


def _review_from_payload(payload: Mapping[str, Any]) -> HumanReviewTask:
    return HumanReviewTask(
        review_id=str(payload.get("review_id") or ""),
        project_id=str(payload.get("project_id") or ""),
        severity=str(payload.get("severity") or "warning"),
        review_type=str(payload.get("review_type") or "manual_check"),
        requirement_id=(
            str(payload["requirement_id"])
            if payload.get("requirement_id") not in (None, "")
            else None
        ),
        question=str(payload.get("question") or ""),
        status=str(payload.get("status") or "open"),
        source_run_id=(
            str(payload["source_run_id"])
            if payload.get("source_run_id") not in (None, "")
            else None
        ),
        affected_artifact_ids=list(payload.get("affected_artifact_ids") or []),
        resolution=(
            dict(payload["resolution"])
            if isinstance(payload.get("resolution"), Mapping)
            else None
        ),
        created_at=str(payload.get("created_at") or ""),
        updated_at=str(payload.get("updated_at") or ""),
    )
