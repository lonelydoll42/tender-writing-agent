"""Optional FastAPI adapter for the Agent Runtime."""

from __future__ import annotations

import os
from typing import Any

import base64
import binascii
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import File, FastAPI, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.core.files import FileRegistryError, ProjectFileRegistry
from qiaowenshu_agent.core.runtime import AgentRuntime
from qiaowenshu_agent.core.store import HumanReviewTask, InMemoryStore, SQLiteStore
from qiaowenshu_agent.skills import build_default_registry


class AgentRunRequest(BaseModel):
    skill_name: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    user_id: str | None = None
    tenant_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectAnalyzeRequest(BaseModel):
    file_ids: list[str] = Field(min_length=1)
    bidder_file_ids: list[str] = Field(default_factory=list)
    bidder_id: str = "bidder"
    bidder_name: str = ""
    bidder_profile: dict[str, Any] | None = None
    materials: list[dict[str, Any]] = Field(default_factory=list)
    as_of: str | None = None


class HumanReviewCreateRequest(BaseModel):
    question: str
    severity: str = "warning"
    review_type: str = "manual_check"
    requirement_id: str | None = None
    source_run_id: str | None = None
    affected_artifact_ids: list[str] = Field(default_factory=list)
    review_id: str | None = None


class HumanReviewResolveRequest(BaseModel):
    resolution: dict[str, Any] = Field(default_factory=dict)
    resume_run: bool = False


def create_app(
    agent_runtime: AgentRuntime | None = None,
    *,
    storage_path: str | Path | None = None,
    ocr_backend: Any | None = None,
) -> FastAPI:
    """Create an API adapter for a host-provided runtime."""

    if agent_runtime is None:
        configured_path = storage_path or os.getenv("QIAOWENSHU_DB_PATH")
        store = (
            SQLiteStore(configured_path)
            if configured_path
            else InMemoryStore()
        )
        file_registry = ProjectFileRegistry(store, ocr_backend=ocr_backend)
        local_runtime = AgentRuntime(
            build_default_registry(file_registry=file_registry),
            services={"file_registry": file_registry, "store": store},
        )
    else:
        local_runtime = agent_runtime
        file_registry = local_runtime.services.get("file_registry")
        if not isinstance(file_registry, ProjectFileRegistry):
            file_registry = None
        elif ocr_backend is not None:
            file_registry.ocr_backend = ocr_backend
        store = local_runtime.store
    local_registry = local_runtime.registry
    local_app = FastAPI(title="Qiaowenshu Agent", version="0.1.0")
    local_app.state.file_registry = file_registry
    local_app.state.store = store

    @local_app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @local_app.get("/v1/skills")
    async def list_skills(
        include_extended: bool = Query(default=False),
    ) -> dict[str, Any]:
        skills = local_registry.manifest_dicts()
        if not include_extended:
            legacy_names = {
                "bid-feasibility",
                "document-preprocess",
                "document-profile",
                "document-writing",
                "evidence-matching",
                "knowledge-retrieval",
                "scoring-strategy",
                "tender-decomposition",
                "tender-intake",
            }
            skills = [item for item in skills if item["name"] in legacy_names]
        return {"skills": skills}

    @local_app.post("/v1/agent/runs")
    async def run_agent(payload: AgentRunRequest) -> dict[str, Any]:
        request = SkillRequest.create(
            payload.input,
            skill_name=payload.skill_name,
            user_id=payload.user_id,
            tenant_id=payload.tenant_id,
            metadata=payload.metadata,
        )
        result = await local_runtime.run(request)
        return result.to_dict()

    @local_app.get("/v1/agent/runs/{run_id}")
    async def get_agent_run(run_id: str) -> dict[str, Any]:
        record = local_runtime.store.get_run(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="run not found")
        return {"run": record.to_dict()}

    @local_app.post("/v1/agent/runs/{run_id}/resume")
    async def resume_agent_run(run_id: str) -> dict[str, Any]:
        try:
            result = await local_runtime.resume(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return result.to_dict()

    @local_app.post("/v1/projects/{project_id}/files")
    async def register_project_file(
        project_id: str,
        request: Request,
        file: UploadFile | None = File(default=None),
        file_name: Optional[str] = Query(default=None),
        file_role: str = Query(default="other"),
        material_type: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        if file_registry is None:
            raise HTTPException(
                status_code=503,
                detail="file registry service is not configured",
            )
        if file is not None:
            content = await file.read()
            body_file_name = file.filename
        else:
            content, body_file_name = await _read_upload_body(request)
        resolved_name = (
            file_name or request.headers.get("X-File-Name") or body_file_name
        )
        if not resolved_name:
            raise HTTPException(
                status_code=400,
                detail="file_name query parameter or X-File-Name header is required",
            )
        try:
            registration = file_registry.register(
                project_id=project_id,
                file_name=resolved_name,
                content=content,
                file_role=file_role,
                material_type=material_type,
            )
        except FileRegistryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "file": registration.file.to_dict(),
            "deduplicated": registration.deduplicated,
        }

    @local_app.get("/v1/projects/{project_id}/files")
    async def list_project_files(
        project_id: str,
        file_role: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        if file_registry is None:
            raise HTTPException(
                status_code=503,
                detail="file registry service is not configured",
            )
        return {
            "project_id": project_id,
            "files": [
                item.to_dict()
                for item in file_registry.list(project_id, file_role=file_role)
            ],
        }

    @local_app.get("/v1/projects/{project_id}")
    async def get_project(project_id: str) -> dict[str, Any]:
        project = local_runtime.store.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        return {"project": project.to_dict()}

    @local_app.get("/v1/projects/{project_id}/artifacts")
    async def list_project_artifacts(
        project_id: str,
        status: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        return {
            "project_id": project_id,
            "artifacts": [
                item.to_dict()
                for item in local_runtime.store.list_artifacts(
                    project_id, status=status
                )
            ],
        }

    @local_app.get("/v1/artifacts/{artifact_id}")
    async def get_artifact(artifact_id: str) -> dict[str, Any]:
        artifact = local_runtime.store.get_artifact(artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        return {"artifact": artifact.to_dict()}

    @local_app.post("/v1/projects/{project_id}/reviews")
    async def create_review(
        project_id: str,
        payload: HumanReviewCreateRequest,
    ) -> dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()
        task = HumanReviewTask(
            review_id=payload.review_id or f"review_{uuid4().hex[:16]}",
            project_id=project_id,
            severity=payload.severity,
            review_type=payload.review_type,
            requirement_id=payload.requirement_id,
            question=payload.question,
            source_run_id=payload.source_run_id,
            affected_artifact_ids=list(payload.affected_artifact_ids),
            created_at=timestamp,
            updated_at=timestamp,
        )
        local_runtime.store.ensure_project(project_id)
        local_runtime.store.save_review(task)
        return {"review": task.to_dict()}

    @local_app.get("/v1/projects/{project_id}/reviews")
    async def list_reviews(
        project_id: str,
        status: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        return {
            "project_id": project_id,
            "reviews": [
                item.to_dict()
                for item in local_runtime.store.list_reviews(
                    project_id, status=status
                )
            ],
        }

    @local_app.get("/v1/reviews/{review_id}")
    async def get_review(review_id: str) -> dict[str, Any]:
        task = local_runtime.store.get_review(review_id)
        if task is None:
            raise HTTPException(status_code=404, detail="review task not found")
        return {"review": task.to_dict()}

    @local_app.post("/v1/reviews/{review_id}/resolve")
    async def resolve_review(
        review_id: str,
        payload: HumanReviewResolveRequest,
    ) -> dict[str, Any]:
        task = local_runtime.store.get_review(review_id)
        if task is None:
            raise HTTPException(status_code=404, detail="review task not found")
        resolved = HumanReviewTask(
            review_id=task.review_id,
            project_id=task.project_id,
            severity=task.severity,
            review_type=task.review_type,
            requirement_id=task.requirement_id,
            question=task.question,
            status="resolved",
            source_run_id=task.source_run_id,
            affected_artifact_ids=list(task.affected_artifact_ids),
            resolution=dict(payload.resolution),
            created_at=task.created_at,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        local_runtime.store.save_review(resolved)
        response: dict[str, Any] = {"review": resolved.to_dict()}
        if payload.resume_run and task.source_run_id:
            try:
                response["run"] = (
                    await local_runtime.resume(task.source_run_id)
                ).to_dict()
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
        return response

    @local_app.get("/v1/files/{file_id}")
    async def get_project_file(file_id: str) -> dict[str, Any]:
        if file_registry is None:
            raise HTTPException(
                status_code=503,
                detail="file registry service is not configured",
            )
        record = file_registry.get(file_id)
        if record is None:
            raise HTTPException(status_code=404, detail="file not found")
        artifact = (
            file_registry.artifact(record.parse_artifact_id)
            if record.parse_artifact_id
            else None
        )
        return {"file": record.to_dict(), "artifact": artifact}

    @local_app.post("/v1/projects/{project_id}/files/{file_id}/parse")
    async def parse_project_file(project_id: str, file_id: str) -> dict[str, Any]:
        if file_registry is None:
            raise HTTPException(
                status_code=503,
                detail="file registry service is not configured",
            )
        record = file_registry.get(file_id)
        if record is None or record.project_id != project_id:
            raise HTTPException(status_code=404, detail="file not found")
        try:
            artifact = file_registry.parse(file_id, force=True)
        except FileRegistryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"file": file_registry.require(file_id).to_dict(), "artifact": artifact}

    @local_app.post("/v1/projects/{project_id}/analyze")
    async def analyze_project(
        project_id: str,
        payload: ProjectAnalyzeRequest,
    ) -> dict[str, Any]:
        if file_registry is None:
            raise HTTPException(
                status_code=503,
                detail="file registry service is not configured",
            )
        for file_id in payload.file_ids + payload.bidder_file_ids:
            record = file_registry.get(file_id)
            if record is None or record.project_id != project_id:
                raise HTTPException(
                    status_code=404, detail=f"file not found: {file_id}"
                )
        input_data = payload.model_dump()
        input_data["project_id"] = project_id
        input_data["plan"] = _project_analysis_plan(payload)
        result = await local_runtime.run(SkillRequest.create(input_data))
        return result.to_dict()

    return local_app


async def _read_upload_body(request: Request) -> tuple[bytes, str | None]:
    """Accept raw bytes and a small JSON/base64 convenience envelope."""

    body = await request.body()
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" not in content_type:
        return body, None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="invalid JSON upload body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400, detail="JSON upload body must be an object"
        )
    encoded = payload.get("content_base64")
    if encoded is not None:
        try:
            return base64.b64decode(str(encoded), validate=True), payload.get(
                "file_name"
            )
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail="content_base64 is invalid"
            ) from exc
    text = payload.get("content")
    if isinstance(text, str):
        return text.encode("utf-8"), payload.get("file_name")
    raise HTTPException(
        status_code=400, detail="JSON upload needs content or content_base64"
    )


def _project_analysis_plan(payload: ProjectAnalyzeRequest) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = [
        {
            "skill_name": "document-preprocess",
            "input": {
                "file_id": {"$ref": "$request/file_ids/0"},
                "business_scene": "tender_parse",
                "file_role": "tender",
            },
        },
        {
            "skill_name": "tender-intake",
            "input": {
                "project_id": {"$ref": "$request/project_id"},
                "file_ids": {"$ref": "$request/file_ids"},
            },
        },
        {
            "skill_name": "consistency-review",
            "input": {
                "project_id": {"$ref": "$request/project_id"},
                "documents": {"$ref": "$state/tender-intake/pages"},
            },
        },
        {
            "skill_name": "tender-decomposition",
            "input": {
                "project_id": {"$ref": "$request/project_id"},
                "profile": {"$ref": "$state/tender-intake/profile"},
                "sections": {"$ref": "$state/tender-intake/sections"},
            },
        },
    ]
    if payload.bidder_file_ids:
        plan.append(
            {
                "skill_name": "bidder-material-intake",
                "input": {
                    "project_id": {"$ref": "$request/project_id"},
                    "bidder_id": payload.bidder_id,
                    "bidder_name": payload.bidder_name,
                    "file_ids": {"$ref": "$request/bidder_file_ids"},
                    "as_of": payload.as_of,
                },
            }
        )
        bidder_ref: dict[str, Any] = {
            "$ref": "$state/bidder-material-intake/bidder_profile"
        }
        material_ref: dict[str, Any] = {
            "$ref": "$state/bidder-material-intake/materials"
        }
    else:
        bidder_ref = (
            {"$ref": "$request/bidder_profile"}
            if payload.bidder_profile is not None
            else {"bidder_id": payload.bidder_id}
        )
        material_ref = {"$ref": "$request/materials"}
    plan.extend(
        [
            {
                "skill_name": "evidence-matching",
                "input": {
                    "project_id": {"$ref": "$request/project_id"},
                    "requirements": {
                        "$ref": "$state/tender-decomposition/requirements"
                    },
                    "scoring_items": {
                        "$ref": "$state/tender-decomposition/scoring_items"
                    },
                    "materials": material_ref,
                    "as_of": payload.as_of,
                },
            },
            {
                "skill_name": "bid-feasibility",
                "input": {
                    "project_id": {"$ref": "$request/project_id"},
                    "requirements": {
                        "$ref": "$state/tender-decomposition/requirements"
                    },
                    "bidder_profile": bidder_ref,
                    "as_of": payload.as_of,
                },
            },
            {
                "skill_name": "requirement-ledger",
                "input": {
                    "project_id": {"$ref": "$request/project_id"},
                    "requirements": {
                        "$ref": "$state/tender-decomposition/requirements"
                    },
                    "scoring_items": {
                        "$ref": "$state/tender-decomposition/scoring_items"
                    },
                    "evidence_matches": {"$ref": "$state/evidence-matching/matches"},
                    "feasibility_checks": {"$ref": "$state/bid-feasibility/checks"},
                },
            },
            {
                "skill_name": "compliance-review",
                "input": {
                    "project_id": {"$ref": "$request/project_id"},
                    "ledger": {"$ref": "$state/requirement-ledger"},
                    "consistency_result": {"$ref": "$state/consistency-review"},
                },
            },
            {
                "skill_name": "scoring-strategy",
                "input": {
                    "project_id": {"$ref": "$request/project_id"},
                    "requirements": {
                        "$ref": "$state/tender-decomposition/requirements"
                    },
                    "scoring_items": {
                        "$ref": "$state/tender-decomposition/scoring_items"
                    },
                    "evidence_materials": material_ref,
                    "evidence_matches": {
                        "$ref": "$state/evidence-matching/matches"
                    },
                    "as_of": payload.as_of,
                },
            },
            {
                "skill_name": "analysis-report",
                "input": {
                    "project_id": {"$ref": "$request/project_id"},
                    "project": {"$ref": "$state/tender-intake/profile"},
                    "feasibility": {"$ref": "$state/bid-feasibility"},
                    "scoring": {"$ref": "$state/scoring-strategy"},
                    "ledger": {"$ref": "$state/requirement-ledger"},
                    "compliance": {"$ref": "$state/compliance-review"},
                },
            },
        ]
    )
    return plan


app = create_app(
    storage_path=os.getenv(
        "QIAOWENSHU_DB_PATH", ".qiaowenshu/qiaowenshu.sqlite3"
    )
)
