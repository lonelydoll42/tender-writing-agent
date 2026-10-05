"""Tender requirement and scoring-item decomposition Skill."""

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
from qiaowenshu_agent.domain.models import ScoringItem, TenderRequirement
from qiaowenshu_agent.skills.tender_common import (
    checklist_by_category,
    parse_requirements,
    parse_scoring_items,
)
from qiaowenshu_agent.skills.local_backends import FileRegistryNotConfigured


class TenderDecompositionBackend(Protocol):
    def run(
        self,
        payload: Mapping[str, Any],
        context: SkillContext,
    ) -> Mapping[str, Any] | Any: ...


MANIFEST = SkillManifest(
    name="tender-decomposition",
    version="0.1.0",
    description="Convert tender content into atomic requirements and checklists.",
    input_schema={
        "type": "object",
        "required": ["project_id"],
        "properties": {
            "project_id": {"type": "string"},
            "profile": {"type": "object"},
            "sections": {"type": "array"},
            "requirements": {"type": "array"},
            "scoring_items": {"type": "array"},
        },
    },
    output_schema={
        "type": "object",
        "required": ["project_id", "requirements", "scoring_items", "checklists"],
    },
    capabilities=("tender.requirements", "tender.checklists", "tender.scoring"),
    required_permissions=("document.read",),
)


class TenderDecompositionSkill(Skill):
    manifest = MANIFEST

    def __init__(
        self,
        *,
        backend: TenderDecompositionBackend | None = None,
    ) -> None:
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
                error_code="INVALID_TENDER_DECOMPOSITION_INPUT",
            )
        if self.backend is None and not payload["requirements"]:
            return SkillResult.blocked(
                message="tender decomposition backend is not configured",
                error_code="TENDER_DECOMPOSITION_BACKEND_NOT_CONFIGURED",
            )
        try:
            raw = payload
            if self.backend is not None:
                raw = self.backend.run(payload, context)
                if inspect.isawaitable(raw):
                    raw = await raw
            data = _normalize_output(raw, project_id=payload["project_id"])
        except FileRegistryNotConfigured as exc:
            return SkillResult.blocked(
                message=str(exc),
                error_code="TENDER_DECOMPOSITION_FILE_REGISTRY_NOT_CONFIGURED",
            )
        except ValueError as exc:
            return SkillResult.failure(
                message=str(exc),
                error_code="INVALID_TENDER_DECOMPOSITION_OUTPUT",
            )
        except Exception as exc:
            return SkillResult.failure(
                message=f"tender decomposition backend failed: {exc}",
                error_code="TENDER_DECOMPOSITION_BACKEND_FAILED",
                retryable=True,
            )
        return SkillResult.success(data, message="tender decomposition completed")


def _parse_input(data: Mapping[str, Any]) -> dict[str, Any]:
    project_id = str(data.get("project_id") or "").strip()
    if not project_id:
        raise ValueError("project_id is required")
    profile = data.get("profile") or {}
    sections = data.get("sections") or []
    if not isinstance(profile, Mapping):
        raise ValueError("profile must be an object")
    if not isinstance(sections, list):
        raise ValueError("sections must be a list")
    return {
        "project_id": project_id,
        "profile": dict(profile),
        "sections": list(sections),
        "requirements": list(data.get("requirements") or []),
        "scoring_items": list(data.get("scoring_items") or []),
    }


def _normalize_output(raw: Any, *, project_id: str) -> dict[str, Any]:
    if hasattr(raw, "to_dict"):
        raw = raw.to_dict()
    if isinstance(raw, list):
        raw = {"requirements": raw}
    if not isinstance(raw, Mapping):
        raise ValueError("tender decomposition backend must return an object or list")
    body = {str(key): value for key, value in raw.items()}
    requirements = parse_requirements(body.get("requirements"))
    scoring_items = parse_scoring_items(body.get("scoring_items"))
    if not scoring_items:
        scoring_items = _scoring_items_from_requirements(requirements)
    checklists = checklist_by_category(requirements)
    mandatory_count = sum(1 for item in requirements if item.mandatory)
    result = {
        "project_id": project_id,
        "requirements": [item.to_dict() for item in requirements],
        "scoring_items": [item.to_dict() for item in scoring_items],
        "checklists": checklists,
        "summary": {
            "requirement_count": len(requirements),
            "mandatory_count": mandatory_count,
            "scoring_item_count": len(scoring_items),
            "categories": {key: len(value) for key, value in checklists.items()},
        },
        "warnings": [str(item) for item in (body.get("warnings") or [])],
    }
    if "needs_human_review" in body:
        result["needs_human_review"] = bool(body["needs_human_review"])
    if "business_status" in body:
        result["business_status"] = str(body["business_status"])
    if "extraction_complete" in body:
        result["extraction_complete"] = bool(body["extraction_complete"])
    return result


def _scoring_items_from_requirements(
    requirements: list[TenderRequirement],
) -> list[ScoringItem]:
    return [
        ScoringItem(
            item_id=item.requirement_id,
            title=item.title,
            max_score=item.max_score,
            criteria=item.description,
            evidence_required=list(item.evidence_required),
            linked_requirement_ids=[item.requirement_id],
            source_references=list(item.source_references),
        )
        for item in requirements
        if item.category == "scoring" and item.max_score is not None
    ]
