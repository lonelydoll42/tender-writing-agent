"""Typed input model for the document preprocessing service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class DocumentPreprocessInput:
    file_id: str
    business_scene: str
    file_role: str | None = None
    options: dict[str, Any] = field(default_factory=dict)
    force: bool = False

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "DocumentPreprocessInput":
        file_id = str(data.get("file_id") or "").strip()
        business_scene = str(data.get("business_scene") or "").strip()
        if not file_id:
            raise ValueError("file_id is required")
        if not business_scene:
            raise ValueError("business_scene is required")
        return cls(
            file_id=file_id,
            business_scene=business_scene,
            file_role=str(data.get("file_role") or "").strip() or None,
            options=dict(data.get("options") or {}),
            force=bool(data.get("force", False)),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "business_scene": self.business_scene,
            "file_role": self.file_role,
            "options": dict(self.options),
            "force": self.force,
        }
