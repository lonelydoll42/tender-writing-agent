"""Skill facade for the reference document-profile Agent.

The reference implementation remains an injected backend. This keeps the new
Agent Runtime independent from worker imports while preserving the existing
ProfileAgent/Coordinator behavior when the adapter is connected.
"""

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
from qiaowenshu_agent.skills.document_profile.models import (
    DocumentProfileInput,
    DocumentProfileOutput,
)


class DocumentProfileBackend(Protocol):
    def run(
        self,
        payload: Mapping[str, Any],
        context: SkillContext,
    ) -> Mapping[str, Any] | Any:
        ...


MANIFEST = SkillManifest(
    name="document-profile",
    version="0.1.0",
    description="Analyze document structure and produce routing or anatomy metadata.",
    input_schema={
        "type": "object",
        "required": ["job_id"],
        "properties": {
            "file_path": {"type": ["string", "null"]},
            "file_id": {"type": ["string", "null"]},
            "job_id": {"type": "string"},
            "mode": {
                "type": "string",
                "enum": ["coarse", "structural", "lightweight"],
            },
        },
    },
    output_schema={
        "type": "object",
        "required": ["job_id", "mode", "profile"],
    },
    capabilities=("document.profile", "document.anatomy"),
    required_permissions=("document.read",),
)


class DocumentProfileSkill(Skill):
    manifest = MANIFEST

    def __init__(self, *, backend: DocumentProfileBackend | None = None) -> None:
        self.backend = backend

    async def execute(
        self,
        request: SkillRequest,
        context: SkillContext,
    ) -> SkillResult:
        try:
            profile_input = DocumentProfileInput.from_mapping(request.input)
        except ValueError as exc:
            return SkillResult.failure(
                message=str(exc),
                error_code="INVALID_DOCUMENT_PROFILE_INPUT",
            )

        if self.backend is None:
            output = DocumentProfileOutput(
                file_id=profile_input.file_id,
                job_id=profile_input.job_id,
                mode=profile_input.mode,
                profile={
                    "category": "unknown document",
                    "routing_category": "generic",
                    "configured": False,
                },
                warnings=["document profile backend is not configured"],
            )
            return SkillResult.partial(
                output.to_dict(),
                message="profile skill is available but has no backend",
                warnings=output.warnings,
            )

        try:
            raw = self.backend.run(profile_input.to_payload(), context)
            if inspect.isawaitable(raw):
                raw = await raw
            data = _normalize_backend_output(raw, profile_input)
        except Exception as exc:
            return SkillResult.failure(
                message=f"document profile backend failed: {exc}",
                error_code="DOCUMENT_PROFILE_BACKEND_FAILED",
                retryable=True,
            )
        return SkillResult.success(data, message="document profile completed")


def _normalize_backend_output(
    raw: Any,
    profile_input: DocumentProfileInput,
) -> dict[str, Any]:
    if hasattr(raw, "to_dict"):
        raw = raw.to_dict()
    elif hasattr(raw, "__dict__") and not isinstance(raw, Mapping):
        raw = dict(raw.__dict__)
    if not isinstance(raw, Mapping):
        raw = {"value": raw}
    output = dict(raw)
    output.setdefault("file_id", profile_input.file_id)
    output.setdefault("job_id", profile_input.job_id)
    output.setdefault("mode", profile_input.mode)
    output.setdefault("profile", {})
    return output
