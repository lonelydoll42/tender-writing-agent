"""Tender document intake and structured profile Skill."""

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
from qiaowenshu_agent.domain.models import TenderProfile
from qiaowenshu_agent.skills.local_backends import FileRegistryNotConfigured


class TenderIntakeBackend(Protocol):
    def run(
        self,
        payload: Mapping[str, Any],
        context: SkillContext,
    ) -> Mapping[str, Any] | Any: ...


MANIFEST = SkillManifest(
    name="tender-intake",
    version="0.1.0",
    description="Build a page-aware structured profile from tender documents.",
    input_schema={
        "type": "object",
        "required": ["project_id", "file_ids"],
        "properties": {
            "project_id": {"type": "string"},
            "file_ids": {"type": "array", "items": {"type": "string"}},
            "business_scene": {"type": "string"},
            "options": {"type": "object"},
        },
    },
    output_schema={
        "type": "object",
        "required": ["project_id", "profile", "sections", "pages"],
    },
    capabilities=("tender.profile", "tender.sections", "tender.evidence"),
    required_permissions=("document.read",),
)


class TenderIntakeSkill(Skill):
    manifest = MANIFEST

    def __init__(self, *, backend: TenderIntakeBackend | None = None) -> None:
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
                error_code="INVALID_TENDER_INTAKE_INPUT",
            )
        if self.backend is None:
            return SkillResult.blocked(
                message="tender intake backend is not configured",
                error_code="TENDER_INTAKE_BACKEND_NOT_CONFIGURED",
            )
        try:
            raw = self.backend.run(payload, context)
            if inspect.isawaitable(raw):
                raw = await raw
            data = _normalize_output(raw, project_id=payload["project_id"])
        except FileRegistryNotConfigured as exc:
            return SkillResult.blocked(
                message=str(exc),
                error_code="TENDER_INTAKE_FILE_REGISTRY_NOT_CONFIGURED",
            )
        except ValueError as exc:
            return SkillResult.failure(
                message=str(exc),
                error_code="INVALID_TENDER_INTAKE_OUTPUT",
            )
        except Exception as exc:
            return SkillResult.failure(
                message=f"tender intake backend failed: {exc}",
                error_code="TENDER_INTAKE_BACKEND_FAILED",
                retryable=True,
            )
        return SkillResult.success(data, message="tender intake completed")


def _parse_input(data: Mapping[str, Any]) -> dict[str, Any]:
    project_id = str(data.get("project_id") or "").strip()
    if not project_id:
        raise ValueError("project_id is required")
    raw_file_ids = data.get("file_ids")
    if raw_file_ids is None and data.get("file_id"):
        raw_file_ids = [data["file_id"]]
    if not isinstance(raw_file_ids, (list, tuple)):
        raise ValueError("file_ids must be a non-empty list")
    file_ids = [str(item).strip() for item in raw_file_ids if str(item).strip()]
    if not file_ids:
        raise ValueError("file_ids must be a non-empty list")
    options = data.get("options") or {}
    if not isinstance(options, Mapping):
        raise ValueError("options must be an object")
    return {
        "project_id": project_id,
        "file_ids": file_ids,
        "business_scene": str(data.get("business_scene") or "tender_parse"),
        "options": dict(options),
    }


def _normalize_output(raw: Any, *, project_id: str) -> dict[str, Any]:
    if hasattr(raw, "to_dict"):
        raw = raw.to_dict()
    if not isinstance(raw, Mapping):
        raise ValueError("tender intake backend must return an object")
    body = {str(key): value for key, value in raw.items()}
    profile_raw = body.get("profile") or body.get("tender_profile") or body
    if not isinstance(profile_raw, Mapping):
        raise ValueError("tender intake profile must be an object")
    profile_data = dict(profile_raw)
    profile_data.setdefault("project_id", project_id)
    profile = TenderProfile.from_mapping(profile_data)
    sections = body.get("sections") or []
    pages = body.get("pages") or []
    artifacts = body.get("artifacts") or []
    for name, value in (
        ("sections", sections),
        ("pages", pages),
        ("artifacts", artifacts),
    ):
        if not isinstance(value, list):
            raise ValueError(f"{name} must be a list")
    warnings = [str(item) for item in (body.get("warnings") or [])]
    warnings.extend(profile.warnings)
    return {
        "project_id": project_id,
        "profile": profile.to_dict(),
        "sections": list(sections),
        "pages": list(pages),
        "artifacts": list(artifacts),
        "warnings": warnings,
    }
