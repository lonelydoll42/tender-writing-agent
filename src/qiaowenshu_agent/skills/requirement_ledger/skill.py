"""Build one traceable requirement/evidence/response ledger."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any, Mapping

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import (
    Skill,
    SkillManifest,
    SkillRequest,
    SkillResult,
)
from qiaowenshu_agent.domain.models import ScoringItem, TenderRequirement


MANIFEST = SkillManifest(
    name="requirement-ledger",
    version="0.1.0",
    description=(
        "Join tender requirements, evidence, feasibility and response coverage "
        "by stable IDs."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "requirements": {"type": "array"},
            "scoring_items": {"type": "array"},
            "evidence_matches": {"type": "array"},
            "feasibility_checks": {"type": "array"},
            "response_map": {"type": "object"},
        },
    },
    output_schema={
        "type": "object",
        "required": ["ledger", "entries", "summary"],
    },
    capabilities=("tender.requirement_ledger", "tender.coverage_trace"),
    required_permissions=("document.read",),
)


class RequirementLedgerSkill(Skill):
    manifest = MANIFEST

    async def execute(
        self,
        request: SkillRequest,
        _context: SkillContext,
    ) -> SkillResult:
        try:
            data = _build_ledger(request.input)
        except (TypeError, ValueError) as exc:
            return SkillResult.failure(
                message=str(exc),
                error_code="INVALID_REQUIREMENT_LEDGER_INPUT",
            )
        return SkillResult.success(data, message="requirement ledger built")


def _build_ledger(data: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise TypeError("requirement ledger input must be an object")
    raw_requirements = data.get("requirements") or []
    raw_scores = data.get("scoring_items") or []
    if not isinstance(raw_requirements, (list, tuple)):
        raise ValueError("requirements must be a list")
    if not isinstance(raw_scores, (list, tuple)):
        raise ValueError("scoring_items must be a list")
    requirements = [
        item
        if isinstance(item, TenderRequirement)
        else TenderRequirement.from_mapping(item)
        for item in raw_requirements
    ]
    scoring_items = [
        item if isinstance(item, ScoringItem) else ScoringItem.from_mapping(item)
        for item in raw_scores
    ]
    if not requirements and not scoring_items:
        raise ValueError("requirements or scoring_items is required")
    matches = _index(data.get("evidence_matches") or [], "requirement_id")
    checks = _index(data.get("feasibility_checks") or [], "requirement_id")
    response_map = data.get("response_map") or {}
    if not isinstance(response_map, Mapping):
        raise ValueError("response_map must be an object")

    entries: list[dict[str, Any]] = []
    for item in requirements:
        raw_match = matches.get(item.requirement_id)
        raw_check = checks.get(item.requirement_id)
        entries.append(
            _entry_for_requirement(
                item,
                raw_match,
                raw_check,
                response_map.get(item.requirement_id),
            )
        )
    for item in scoring_items:
        raw_match = matches.get(item.item_id)
        entries.append(
            _entry_for_scoring(
                item,
                raw_match,
                response_map.get(item.item_id),
            )
        )

    statuses = Counter(str(item["status"]) for item in entries)
    total_score = sum(
        Decimal(str(item["max_score"]))
        for item in entries
        if item["max_score"] is not None
    )
    covered_score = sum(
        Decimal(str(item["max_score"])) * Decimal(str(_coverage(item["status"])))
        for item in entries
        if item["max_score"] is not None
    )
    mandatory_gaps = [
        item["requirement_id"]
        for item in entries
        if item["mandatory"] and item["status"] not in {"matched", "pass"}
    ]
    evidence_gaps = [
        _gap_from_entry(item)
        for item in entries
        if item["status"] not in {"matched", "pass", "not_applicable"}
    ]
    gap_type_counts = Counter(
        str(item["gap_type"])
        for item in evidence_gaps
        if item.get("gap_type")
    )
    project_id = str(data.get("project_id") or "").strip()
    summary = {
        "entry_count": len(entries),
        "status_counts": dict(statuses),
        "mandatory_gap_count": len(mandatory_gaps),
        "mandatory_gap_ids": mandatory_gaps,
        "total_score": float(total_score),
        "theoretical_covered_score": float(covered_score),
        "theoretical_score_coverage": (
            round(float(covered_score / total_score), 4) if total_score else None
        ),
        "evidence_gap_count": len(evidence_gaps),
        "gap_type_counts": dict(gap_type_counts),
    }
    warnings = (
        [f"存在 {len(mandatory_gaps)} 个未闭合硬性要求"] if mandatory_gaps else []
    )
    return {
        "project_id": project_id,
        "ledger": {
            "ledger_id": f"ledger_{project_id or 'project'}",
            "project_id": project_id,
            "version": 1,
        },
        "entries": entries,
        "evidence_gaps": evidence_gaps,
        "summary": summary,
        "warnings": warnings,
    }


def _entry_for_requirement(
    item: TenderRequirement,
    match: Mapping[str, Any] | None,
    check: Mapping[str, Any] | None,
    response_location: Any,
) -> dict[str, Any]:
    status = _status(match, check, has_evidence=bool(item.evidence_required))
    gap_type = _gap_type(
        category=item.category,
        mandatory=item.mandatory,
        status=status,
    )
    return {
        "requirement_id": item.requirement_id,
        "item_type": "requirement",
        "category": item.category,
        "title": item.title,
        "description": item.description,
        "mandatory": item.mandatory,
        "max_score": item.max_score,
        "evidence_material_ids": _material_ids(match),
        "evidence_source_references": (
            list(match.get("source_references") or []) if match else []
        ),
        "response_location": response_location,
        "status": status,
        "gap_type": gap_type,
        "gap_reason": _gap_reason(status, match, check),
        "feasibility_status": check.get("status") if check else None,
        "source_references": [
            reference.to_dict() for reference in item.source_references
        ],
    }


def _entry_for_scoring(
    item: ScoringItem,
    match: Mapping[str, Any] | None,
    response_location: Any,
) -> dict[str, Any]:
    status = _status(match, None, has_evidence=bool(item.evidence_required))
    return {
        "requirement_id": item.item_id,
        "item_type": "scoring",
        "category": "scoring",
        "title": item.title,
        "description": item.criteria,
        "mandatory": False,
        "max_score": item.max_score,
        "evidence_material_ids": _material_ids(match),
        "evidence_source_references": (
            list(match.get("source_references") or []) if match else []
        ),
        "response_location": response_location,
        "status": status,
        "gap_type": _gap_type(category="scoring", mandatory=False, status=status),
        "gap_reason": _gap_reason(status, match, None),
        "feasibility_status": None,
        "source_references": [
            reference.to_dict() for reference in item.source_references
        ],
    }


def _status(
    match: Mapping[str, Any] | None,
    check: Mapping[str, Any] | None,
    *,
    has_evidence: bool,
) -> str:
    check_status = str(check.get("status") or "").lower() if check else ""
    if check_status == "fail":
        return "invalid"
    if check_status == "unknown":
        return "unknown"
    match_status = str(match.get("status") or "").lower() if match else ""
    if match_status in {
        "matched",
        "partial",
        "missing",
        "invalid",
        "conflict",
        "human_review",
    }:
        return match_status
    return "unreviewed" if has_evidence else "matched"


def _material_ids(match: Mapping[str, Any] | None) -> list[str]:
    if not match:
        return []
    values = match.get("material_ids") or match.get("evidence_material_ids")
    if values is None and match.get("material_id"):
        values = [match["material_id"]]
    if not isinstance(values, (list, tuple, set)):
        return []
    return [str(value) for value in values if str(value).strip()]


def _index(value: Any, key: str) -> dict[str, Mapping[str, Any]]:
    if value is None:
        return {}
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{key} collection must be a list")
    result: dict[str, Mapping[str, Any]] = {}
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(f"{key} collection items must be objects")
        identifier = str(item.get(key) or "").strip()
        if identifier:
            result[identifier] = item
    return result


def _coverage(status: str) -> float:
    return {
        "matched": 1.0,
        "pass": 1.0,
        "partial": 0.5,
        "unknown": 0.0,
        "missing": 0.0,
        "invalid": 0.0,
        "conflict": 0.0,
        "human_review": 0.0,
        "unreviewed": 0.0,
    }.get(status, 0.0)


def _gap_type(*, category: str, mandatory: bool, status: str) -> str | None:
    if status in {"matched", "pass", "not_applicable"}:
        return None
    if status == "conflict":
        return "human_review"
    if status == "human_review":
        return "human_review"
    normalized = str(category or "").strip().lower()
    if normalized == "scoring":
        return "score_gap"
    if normalized in {"technical", "compliance"}:
        return "technical_confirmation"
    if normalized in {"format", "commercial"}:
        return "submission_gap"
    if mandatory or normalized in {"qualification", "disqualification"}:
        return "qualification_gap"
    return "human_review"


def _gap_reason(
    status: str,
    match: Mapping[str, Any] | None,
    check: Mapping[str, Any] | None,
) -> str:
    if check and check.get("reason"):
        return str(check["reason"])
    if match and match.get("reason"):
        return str(match["reason"])
    return {
        "partial": "证据仅部分覆盖",
        "missing": "缺少证明材料",
        "invalid": "证明材料无效或不符合要求",
        "conflict": "证据之间存在冲突，需要人工复核",
        "human_review": "OCR或其他来源置信度不足，需要人工复核",
        "unknown": "现有材料不足以确认要求",
        "unreviewed": "尚未完成证据核验",
    }.get(status, "证据尚未闭合")


def _gap_from_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "gap_id": str(entry.get("requirement_id") or "").strip(),
        "title": str(entry.get("title") or entry.get("requirement_id") or "").strip(),
        "gap_type": entry.get("gap_type") or "human_review",
        "status": str(entry.get("status") or "unknown"),
        "reason": str(entry.get("gap_reason") or "证据尚未闭合"),
        "evidence_material_ids": list(entry.get("evidence_material_ids") or []),
        "source_references": list(entry.get("source_references") or []),
    }
