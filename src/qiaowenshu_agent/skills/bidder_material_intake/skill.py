"""Build a structured bidder profile from uploaded enterprise materials."""

from __future__ import annotations

import inspect
from typing import Any, Mapping, Protocol

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import (
    Skill,
    SkillManifest,
    SkillRequest,
    SkillResult,
)
from qiaowenshu_agent.domain.models import BidderProfile
from qiaowenshu_agent.skills.local_backends import FileRegistryNotConfigured


class BidderMaterialIntakeBackend(Protocol):
    def run(
        self,
        payload: Mapping[str, Any],
        context: SkillContext,
    ) -> Mapping[str, Any] | Any: ...


MANIFEST = SkillManifest(
    name="bidder-material-intake",
    version="0.1.0",
    description="Classify bidder files and build structured evidence materials.",
    input_schema={
        "type": "object",
        "required": ["bidder_id"],
        "properties": {
            "project_id": {"type": "string"},
            "bidder_id": {"type": "string"},
            "bidder_name": {"type": "string"},
            "file_ids": {"type": "array"},
            "materials": {"type": "array"},
            "as_of": {"type": ["string", "null"]},
        },
    },
    output_schema={
        "type": "object",
        "required": ["bidder_profile", "materials", "summary"],
    },
    capabilities=("bidder.material_intake", "bidder.profile_building"),
    required_permissions=("document.read", "bidder.read"),
)


class BidderMaterialIntakeSkill(Skill):
    manifest = MANIFEST

    def __init__(self, *, backend: BidderMaterialIntakeBackend | None = None) -> None:
        self.backend = backend

    async def execute(
        self,
        request: SkillRequest,
        context: SkillContext,
    ) -> SkillResult:
        try:
            payload = _parse_input(request.input)
        except (TypeError, ValueError) as exc:
            return SkillResult.failure(
                message=str(exc),
                error_code="INVALID_BIDDER_MATERIAL_INTAKE_INPUT",
            )
        if self.backend is None and not payload["materials"]:
            return SkillResult.blocked(
                message="bidder material intake backend is not configured",
                error_code="BIDDER_MATERIAL_INTAKE_BACKEND_NOT_CONFIGURED",
            )
        try:
            raw = payload
            if self.backend is not None:
                raw = self.backend.run(payload, context)
                if inspect.isawaitable(raw):
                    raw = await raw
            data = _normalize_output(raw, payload)
        except FileRegistryNotConfigured as exc:
            return SkillResult.blocked(
                message=str(exc),
                error_code="BIDDER_MATERIAL_FILE_REGISTRY_NOT_CONFIGURED",
            )
        except ValueError as exc:
            return SkillResult.failure(
                message=str(exc),
                error_code="INVALID_BIDDER_MATERIAL_INTAKE_OUTPUT",
            )
        except Exception as exc:
            return SkillResult.failure(
                message=f"bidder material intake backend failed: {exc}",
                error_code="BIDDER_MATERIAL_INTAKE_BACKEND_FAILED",
                retryable=True,
            )
        return SkillResult.success(data, message="bidder material intake completed")


def _parse_input(data: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise TypeError("bidder material intake input must be an object")
    bidder_id = str(data.get("bidder_id") or data.get("id") or "").strip()
    if not bidder_id:
        raise ValueError("bidder_id is required")
    file_ids = data.get("file_ids") or []
    if not isinstance(file_ids, (list, tuple)):
        raise ValueError("file_ids must be a list")
    materials = data.get("materials") or []
    if not isinstance(materials, (list, tuple)):
        raise ValueError("materials must be a list")
    return {
        "project_id": str(data.get("project_id") or "").strip(),
        "bidder_id": bidder_id,
        "bidder_name": str(data.get("bidder_name") or data.get("name") or "").strip(),
        "file_ids": [str(item).strip() for item in file_ids if str(item).strip()],
        "materials": list(materials),
        "as_of": data.get("as_of"),
    }


def _normalize_output(raw: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    if hasattr(raw, "to_dict"):
        raw = raw.to_dict()
    if not isinstance(raw, Mapping):
        raise ValueError("bidder material intake backend must return an object")
    body = dict(raw)
    profile_raw = body.get("bidder_profile") or body.get("profile")
    if profile_raw is None:
        profile_raw = {
            "bidder_id": payload["bidder_id"],
            "bidder_name": payload["bidder_name"],
            "materials": body.get("materials") or payload["materials"],
        }
    if not isinstance(profile_raw, Mapping):
        raise ValueError("bidder_profile must be an object")
    profile_data = dict(profile_raw)
    profile_data.setdefault("bidder_id", payload["bidder_id"])
    profile_data.setdefault("bidder_name", payload["bidder_name"])
    profile = BidderProfile.from_mapping(profile_data)
    materials = [item.to_dict() for item in profile.materials]
    return {
        "project_id": payload["project_id"],
        "bidder_profile": profile.to_dict(),
        "materials": materials,
        "summary": {
            "material_count": len(materials),
            "validity_unknown_count": sum(
                1
                for item in materials
                if str(item.get("metadata", {}).get("verification_status") or "")
                in {"unknown", "pending"}
            ),
            "source_file_count": len(payload["file_ids"]),
        },
        "warnings": [str(item) for item in (body.get("warnings") or [])],
    }
