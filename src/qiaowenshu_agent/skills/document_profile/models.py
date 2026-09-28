"""Typed input and output models for document profiling."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class DocumentProfileInput:
    file_path: str | None
    file_id: str | None
    job_id: str
    mode: str = "coarse"
    output_dir: str | None = None
    settings: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "DocumentProfileInput":
        file_path = str(data.get("file_path") or "").strip() or None
        file_id = str(data.get("file_id") or "").strip() or None
        if file_path is None and file_id is None:
            raise ValueError("file_path or file_id is required")
        job_id = str(data.get("job_id") or file_id or "").strip()
        if not job_id:
            raise ValueError("job_id is required")
        mode = str(data.get("mode") or "coarse").strip()
        if mode not in {"coarse", "structural", "lightweight"}:
            raise ValueError("mode must be coarse, structural, or lightweight")
        return cls(
            file_path=file_path,
            file_id=file_id,
            job_id=job_id,
            mode=mode,
            output_dir=str(data.get("output_dir") or "").strip() or None,
            settings=dict(data.get("settings") or {}),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "file_id": self.file_id,
            "job_id": self.job_id,
            "mode": self.mode,
            "output_dir": self.output_dir,
            "settings": dict(self.settings),
        }


@dataclass(frozen=True)
class DocumentProfileOutput:
    file_id: str | None
    job_id: str
    mode: str
    profile: dict[str, Any]
    anatomy: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "job_id": self.job_id,
            "mode": self.mode,
            "profile": dict(self.profile),
            "anatomy": self.anatomy,
            "artifacts": list(self.artifacts),
            "warnings": list(self.warnings),
        }
