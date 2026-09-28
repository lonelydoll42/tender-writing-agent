"""Scoring criteria decomposition and deterministic bid priority Skill."""

from __future__ import annotations

import inspect
import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Protocol

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import (
    Skill,
    SkillManifest,
    SkillRequest,
    SkillResult,
)
from qiaowenshu_agent.domain.models import (
    EvidenceMaterial,
    ScoringItem,
    SourceReference,
)
from qiaowenshu_agent.skills.tender_common import parse_requirements


class ScoringStrategyBackend(Protocol):
    """Optional extractor for document or model-backed scoring tables."""

    def run(
        self,
        payload: Mapping[str, Any],
        context: SkillContext,
    ) -> Mapping[str, Any] | Any:
        ...


MANIFEST = SkillManifest(
    name="scoring-strategy",
    version="0.1.0",
    description=(
        "Decompose scoring criteria and calculate evidence coverage and bid "
        "priorities."
    ),
    input_schema={
        "type": "object",
        "required": ["project_id"],
        "properties": {
            "project_id": {"type": "string"},
            "scoring_items": {"type": "array"},
            "scoring_table": {"type": ["array", "object"]},
            "scoring_criteria": {"type": ["array", "object"]},
            "scoring_text": {"type": "string"},
            "requirements": {"type": "array"},
            "evidence_materials": {"type": "array"},
            "evidence_matches": {"type": "array"},
        },
    },
    output_schema={
        "type": "object",
        "required": [
            "project_id",
            "scoring_items",
            "summary",
            "priorities",
            "evidence_gaps",
        ],
    },
    capabilities=(
        "tender.scoring_strategy",
        "tender.evidence_coverage",
        "tender.priority",
    ),
    required_permissions=("document.read",),
)


class ScoringStrategySkill(Skill):
    """Normalize scoring rows and calculate strategy data without model scores."""

    manifest = MANIFEST

    def __init__(self, *, backend: ScoringStrategyBackend | None = None) -> None:
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
                error_code="INVALID_SCORING_STRATEGY_INPUT",
            )

        if self.backend is None and not (
            payload["scoring_items"]
            or payload["requirements"]
            or payload["scoring_text"]
        ):
            return SkillResult.blocked(
                message="scoring strategy input has no scoring criteria",
                error_code="SCORING_STRATEGY_INPUT_NOT_CONFIGURED",
            )

        try:
            raw: Any = payload
            if self.backend is not None:
                raw = self.backend.run(payload, context)
                if inspect.isawaitable(raw):
                    raw = await raw
            data = _normalize_output(raw, payload=payload)
        except ValueError as exc:
            return SkillResult.failure(
                message=str(exc),
                error_code="INVALID_SCORING_STRATEGY_OUTPUT",
            )
        except Exception as exc:
            return SkillResult.failure(
                message=f"scoring strategy backend failed: {exc}",
                error_code="SCORING_STRATEGY_BACKEND_FAILED",
                retryable=True,
            )

        warnings = list(data.get("warnings", []))
        if not data["scoring_items"]:
            warnings.append("no scoring items were extracted")
            data["warnings"] = warnings
            return SkillResult.partial(
                data,
                message="scoring strategy completed with no scoring items",
                warnings=warnings,
            )
        return SkillResult.success(
            data,
            message="scoring strategy completed",
            warnings=warnings,
        )


def _parse_input(data: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise TypeError("scoring strategy input must be an object")
    project_id = str(data.get("project_id") or "").strip()
    if not project_id:
        raise ValueError("project_id is required")

    raw_scoring_items = _first_non_empty(
        data,
        (
            "scoring_items",
            "scoring_table",
            "scoring_criteria",
            "score_items",
            "score_rules",
            "items",
        ),
    )
    raw_requirements = data.get("requirements")
    raw_materials = _first_non_empty(
        data, ("evidence_materials", "materials", "proof_materials")
    )
    raw_matches = _first_non_empty(
        data, ("evidence_matches", "scoring_evidence_matches")
    )
    scoring_text = data.get("scoring_text") or data.get("criteria_text") or ""
    if not isinstance(scoring_text, str):
        raise ValueError("scoring_text must be a string")

    return {
        "project_id": project_id,
        "scoring_items": _coerce_rows(raw_scoring_items, "scoring_items"),
        "requirements": _coerce_rows(raw_requirements, "requirements"),
        "evidence_materials": _coerce_rows(raw_materials, "evidence_materials"),
        "evidence_matches": _coerce_rows(raw_matches, "evidence_matches"),
        "scoring_text": scoring_text.strip(),
        "as_of": data.get("as_of") or data.get("evaluation_date"),
        "price_score": data.get("price_score"),
        "price_available": data.get("price_available"),
        "subjective_score": data.get("subjective_score"),
        "subjective_scores": data.get("subjective_scores"),
        "subjective_available": data.get("subjective_available"),
        "declared_total_score": _number_or_none(
            data.get("declared_total_score", data.get("total_score"))
        ),
    }


def _normalize_output(raw: Any, *, payload: Mapping[str, Any]) -> dict[str, Any]:
    if hasattr(raw, "to_dict"):
        raw = raw.to_dict()
    if isinstance(raw, str):
        body: dict[str, Any] = {"scoring_text": raw}
    elif isinstance(raw, (list, tuple)):
        body = {"scoring_items": list(raw)}
    elif isinstance(raw, Mapping):
        body = {str(key): value for key, value in raw.items()}
    else:
        raise ValueError(
            "scoring strategy backend must return an object, list, or text"
        )

    raw_items = _first_non_empty(
        body,
        (
            "scoring_items",
            "scoring_table",
            "scoring_criteria",
            "score_items",
            "score_rules",
            "items",
        ),
    )
    if raw_items is None:
        raw_items = payload.get("scoring_items")
    rows = _coerce_rows(raw_items, "scoring_items")
    text = body.get("scoring_text") or body.get("criteria_text")
    if not text:
        text = payload.get("scoring_text", "")
    if not rows and isinstance(text, str):
        rows = _parse_scoring_text(text)

    if not rows:
        raw_requirements = body.get("requirements") or payload.get("requirements")
        requirements = parse_requirements(raw_requirements)
        rows = [
            {
                "item_id": item.requirement_id,
                "title": item.title,
                "max_score": item.max_score,
                "criteria": item.description,
                "evidence_required": list(item.evidence_required),
                "linked_requirement_ids": [item.requirement_id],
                "source_references": [ref.to_dict() for ref in item.source_references],
            }
            for item in requirements
            if item.category == "scoring" and item.max_score is not None
        ]

    items = _normalize_scoring_items(rows)
    _ensure_unique_item_ids(items)

    materials_raw = _first_non_empty(
        body, ("evidence_materials", "materials", "proof_materials")
    )
    if materials_raw is None:
        materials_raw = payload.get("evidence_materials")
    materials = _normalize_materials(materials_raw)

    matches_raw = _first_non_empty(
        body, ("evidence_matches", "scoring_evidence_matches")
    )
    if matches_raw is None:
        matches_raw = payload.get("evidence_matches")
    explicit_matches = _normalize_explicit_matches(matches_raw)
    items, evidence_matches, evidence_gaps = _attach_evidence(
        items,
        materials=materials,
        explicit_matches=explicit_matches,
        as_of=_parse_date_or_none(payload.get("as_of")) or date.today(),
    )
    items, priorities = _assign_priorities(items)

    total_score = _round(sum(float(item["max_score"]) for item in items))
    objective_items = [
        item for item in items if item["score_type"] == "objective"
    ]
    price_items = [item for item in items if item["score_type"] == "price"]
    subjective_items = [
        item for item in items if item["score_type"] == "subjective"
    ]
    objective_max_score = _round(
        sum(float(item["max_score"]) for item in objective_items)
    )
    objective_proven_score = _round(
        sum(
            float(item["max_score"])
            for item in objective_items
            if item["evidence_complete"]
        )
    )
    objective_unproven_score = _round(objective_max_score - objective_proven_score)
    # Keep the legacy name, but make it obey the strict objective-only rule.
    covered_score = objective_proven_score
    price_max_score = _round(sum(float(item["max_score"]) for item in price_items))
    subjective_max_score = _round(
        sum(float(item["max_score"]) for item in subjective_items)
    )
    unclassified_score = _round(
        total_score - objective_max_score - price_max_score - subjective_max_score
    )
    source_summary = body.get("summary")
    source_summary = source_summary if isinstance(source_summary, Mapping) else {}
    price_score = _number_or_none(
        source_summary.get(
            "price_score",
            body.get("price_score", payload.get("price_score")),
        )
    )
    subjective_score = source_summary.get(
        "subjective_score",
        body.get("subjective_score", payload.get("subjective_score")),
    )
    subjective_scores = source_summary.get(
        "subjective_scores",
        body.get("subjective_scores", payload.get("subjective_scores")),
    )
    price_available = _explicit_bool(
        source_summary.get(
            "price_available",
            body.get("price_available", payload.get("price_available")),
        )
    )
    if price_available is None:
        price_available = price_score is not None
    subjective_available = _explicit_bool(
        source_summary.get(
            "subjective_available",
            body.get("subjective_available", payload.get("subjective_available")),
        )
    )
    if subjective_available is None:
        subjective_available = (
            subjective_score is not None or subjective_scores is not None
        )
    required_evidence_count = sum(
        len(item["evidence_required"]) for item in items
    )
    matched_evidence_count = sum(
        1 for match in evidence_matches if match["status"] == "matched"
    )
    covered_item_count = sum(
        1 for item in objective_items if item["evidence_complete"]
    )
    item_count = len(items)
    score_coverage_rate = (
        _round(covered_score / total_score) if total_score else 0.0
    )
    objective_coverage_rate = (
        _round(objective_proven_score / objective_max_score)
        if objective_max_score
        else 0.0
    )
    evidence_coverage_rate = (
        _round(matched_evidence_count / required_evidence_count)
        if required_evidence_count
        else 1.0
    )
    item_coverage_rate = _round(covered_item_count / item_count) if item_count else 0.0

    warnings = _string_list(body.get("warnings"))
    declared_total = _number_or_none(
        body.get("declared_total_score", body.get("total_score"))
    )
    if declared_total is None:
        declared_total = payload.get("declared_total_score")
    if declared_total is not None and abs(declared_total - total_score) > 0.000001:
        warnings.append(
            "declared total score does not match the sum of normalized scoring items"
        )

    summary = {
        "item_count": item_count,
        "total_score": total_score,
        "total_max_score": total_score,
        "declared_total_score": declared_total,
        # Compatibility fields now use the strict objective-only meaning.
        "covered_score": covered_score,
        "covered_score_ceiling": covered_score,
        "objective_proven_score": objective_proven_score,
        "objective_unproven_score": objective_unproven_score,
        "objective_max_score": objective_max_score,
        "uncovered_score": _round(total_score - covered_score),
        "evidence_gap_score": objective_unproven_score,
        "score_coverage_rate": score_coverage_rate,
        "coverage_rate": score_coverage_rate,
        "objective_score_coverage_rate": objective_coverage_rate,
        "item_coverage_rate": item_coverage_rate,
        "evidence_coverage_rate": evidence_coverage_rate,
        "required_evidence_count": required_evidence_count,
        "matched_evidence_count": matched_evidence_count,
        "evidence_gap_count": sum(
            1 for match in evidence_matches if match["status"] != "matched"
        ),
        "gap_item_count": sum(1 for item in items if not item["evidence_complete"]),
        "evidence_material_count": len(materials),
        "price_available": price_available,
        "price_score": price_score,
        "price_max_score": price_max_score,
        "subjective_available": subjective_available,
        "subjective_max_score": subjective_max_score,
        "unclassified_score": unclassified_score,
    }
    return {
        "project_id": str(payload["project_id"]),
        "scoring_items": items,
        "summary": summary,
        "priorities": priorities,
        "evidence_matches": evidence_matches,
        "evidence_gaps": evidence_gaps,
        "warnings": _deduplicate(warnings),
    }


def _normalize_scoring_items(rows: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(rows):
        if isinstance(raw, ScoringItem):
            item_data = raw.to_dict()
            source_data: Mapping[str, Any] = item_data
        elif isinstance(raw, str):
            item_data = _parse_scoring_line(raw, index)
            if item_data is None:
                raise ValueError(f"invalid scoring text line at index {index}")
            source_data = item_data
        elif isinstance(raw, Mapping):
            item_data = {str(key): value for key, value in raw.items()}
            source_data = item_data
        else:
            raise ValueError(
                "scoring_items items must be objects or scoring text lines"
            )

        canonical = _canonical_scoring_mapping(item_data, index=index)
        try:
            item = ScoringItem.from_mapping(canonical)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid scoring item at index {index}: {exc}") from exc

        output = item.to_dict()
        output["score_type"] = _classify_score_type(source_data, item)
        space, space_weight = _classify_subjective_space(
            source_data,
            score_type=output["score_type"],
            text=f"{item.title} {item.criteria}",
        )
        output["subjective_space"] = space
        output["subjective_space_weight"] = space_weight
        output["evidence_required"] = _evidence_requirements(canonical)
        result.append(output)
    return result


def _canonical_scoring_mapping(
    raw: Mapping[str, Any],
    *,
    index: int,
) -> dict[str, Any]:
    data = {str(key): value for key, value in raw.items()}
    aliases = {
        "item_id": ("item_id", "id", "code", "编号", "评分项编号"),
        "title": ("title", "name", "item", "评分项", "评审因素", "评分因素"),
        "max_score": (
            "max_score",
            "score",
            "points",
            "分值",
            "满分",
            "最高分",
            "score_value",
        ),
        "criteria": (
            "criteria",
            "description",
            "condition",
            "得分条件",
            "评分标准",
            "评分办法",
            "标准",
        ),
    }
    for canonical, names in aliases.items():
        if _is_empty(data.get(canonical)):
            value = _first_value(data, names)
            if value is not None:
                data[canonical] = value

    if isinstance(data.get("max_score"), str):
        parsed_score = _number_from_cell(data["max_score"])
        if parsed_score is not None:
            data["max_score"] = parsed_score

    if _is_empty(data.get("item_id")):
        data["item_id"] = f"score-{index + 1}"
    if _is_empty(data.get("title")):
        data["title"] = str(data.get("item_id"))

    evidence = _first_value(
        data,
        (
            "evidence_required",
            "required_evidence",
            "required_materials",
            "proof",
            "proof_required",
            "证明材料",
            "证明材料要求",
        ),
    )
    evidence_requirements = _evidence_requirements_from_value(evidence)
    if not evidence_requirements:
        criteria = str(data.get("criteria") or "")
        evidence_requirements = _extract_evidence_from_text(criteria)
    data["evidence_required"] = evidence_requirements

    if not data.get("source_references"):
        source_value = _first_value(data, ("sources", "source", "来源"))
        references = _source_references(source_value, data)
        if references:
            data["source_references"] = references
    else:
        data["source_references"] = _source_references(
            data["source_references"], data
        )
    return data


def _evidence_requirements(data: Mapping[str, Any]) -> list[str]:
    return _evidence_requirements_from_value(data.get("evidence_required"))


def _evidence_requirements_from_value(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    result: list[str] = []
    for item in values:
        if isinstance(item, Mapping):
            item = (
                item.get("name")
                or item.get("title")
                or item.get("type")
                or item.get("requirement")
                or item.get("description")
            )
        text = str(item or "").strip()
        if not text:
            continue
        for part in re.split(r"[,，;；\n、和及]", text):
            part = re.sub(r"^(?:一个|一份|一项|相关|若干)", "", part)
            part = part.strip(" \t:：-—")
            if part and part not in result:
                result.append(part)
    return result


def _source_references(value: Any, row: Mapping[str, Any]) -> list[dict[str, Any]]:
    if value is None or value == "":
        value = []
    if isinstance(value, (str, int, float)):
        value = [{"document_id": str(value)}]
    elif isinstance(value, SourceReference):
        value = [value.to_dict()]
    elif isinstance(value, Mapping):
        value = [value]
    elif not isinstance(value, (list, tuple, set)):
        raise ValueError("source_references must be a list or object")

    fallback_document_id = _first_value(
        row,
        ("document_id", "file_id", "source_id", "document", "file_path"),
    )
    if fallback_document_id is None:
        fallback_document_id = "inline-scoring-input"
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, SourceReference):
            reference = item.to_dict()
        elif isinstance(item, str):
            reference = {"document_id": item}
        elif isinstance(item, Mapping):
            reference = {str(key): raw for key, raw in item.items()}
        else:
            raise ValueError("source reference must be an object or string")
        reference.setdefault("document_id", str(fallback_document_id))
        if "page" not in reference and "page_number" in reference:
            reference["page"] = reference["page_number"]
        if "section" not in reference and "section_path" in reference:
            reference["section"] = reference["section_path"]
        if "quote" not in reference and "content" in reference:
            reference["quote"] = reference["content"]
        try:
            normalized = SourceReference.from_mapping(reference).to_dict()
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid scoring source reference: {exc}") from exc
        if normalized not in result:
            result.append(normalized)
    return result


def _normalize_materials(value: Any) -> list[EvidenceMaterial]:
    rows = _coerce_rows(value, "evidence_materials")
    result: list[EvidenceMaterial] = []
    for index, raw in enumerate(rows):
        if isinstance(raw, EvidenceMaterial):
            result.append(raw)
            continue
        if isinstance(raw, str):
            raw = {
                "material_id": f"material-{index + 1}",
                "material_type": "text",
                "title": raw,
                "content": raw,
            }
        elif isinstance(raw, Mapping):
            raw = {str(key): item for key, item in raw.items()}
        else:
            raise ValueError("evidence_materials items must be objects or strings")
        data = dict(raw)
        data.setdefault("material_id", data.get("id") or f"material-{index + 1}")
        data.setdefault(
            "material_type",
            data.get("type")
            or data.get("evidence_type")
            or data.get("title")
            or "unknown",
        )
        data.setdefault("title", data.get("name") or data.get("material_type"))
        data.setdefault("content", data.get("text") or "")
        if not data.get("source_references"):
            source = _first_value(data, ("sources", "source", "来源"))
            references = _source_references(source, data)
            if references:
                data["source_references"] = references
        else:
            data["source_references"] = _source_references(
                data["source_references"], data
            )
        try:
            result.append(EvidenceMaterial.from_mapping(data))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"invalid evidence material at index {index}: {exc}"
            ) from exc
    return result


def _normalize_explicit_matches(value: Any) -> list[dict[str, Any]]:
    rows = _coerce_rows(value, "evidence_matches")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise ValueError("evidence_matches items must be objects")
        data = {str(key): item for key, item in raw.items()}
        item_id = str(
            data.get("item_id")
            or data.get("scoring_item_id")
            or data.get("requirement_id")
            or ""
        ).strip()
        if not item_id:
            raise ValueError(f"evidence match at index {index} needs item_id")
        evidence_requirement = str(
            data.get("evidence_requirement")
            or data.get("evidence_type")
            or data.get("material_type")
            or data.get("evidence")
            or ""
        ).strip()
        status = _normalize_match_status(data.get("status"))
        confidence = _number_or_none(data.get("confidence"))
        if confidence is None:
            confidence = 1.0 if status == "matched" else 0.0
        confidence = max(0.0, min(1.0, confidence))
        source_value = data.get("source_references") or data.get("sources")
        references = _source_references(source_value, data) if source_value else []
        result.append(
            {
                "item_id": item_id,
                "requirement_id": str(data.get("requirement_id") or "").strip(),
                "evidence_requirement": evidence_requirement,
                "material_id": (
                    str(data["material_id"]).strip()
                    if data.get("material_id") not in (None, "")
                    else None
                ),
                "status": status,
                "confidence": _round(confidence),
                "reason": str(data.get("reason") or "upstream evidence match").strip(),
                "source_references": references,
            }
        )
    return result


def _attach_evidence(
    items: list[dict[str, Any]],
    *,
    materials: list[EvidenceMaterial],
    explicit_matches: list[dict[str, Any]],
    as_of: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    all_matches: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for item in items:
        required = list(item["evidence_required"])
        item_matches: list[dict[str, Any]] = []
        missing: list[str] = []
        partial: list[str] = []
        if not required:
            item_status = "not_required"
        else:
            for requirement in required:
                match = _explicit_match_for(
                    explicit_matches,
                    item=item,
                    requirement=requirement,
                )
                if match is None:
                    match = _match_material(requirement, materials, as_of=as_of)
                if match is None:
                    match = _missing_match(item, requirement)
                match = dict(match)
                match["item_id"] = item["item_id"]
                match["evidence_requirement"] = requirement
                item_matches.append(match)
                if match["status"] != "matched":
                    if match["status"] == "partial":
                        partial.append(requirement)
                    else:
                        missing.append(requirement)
                all_matches.append(match)
            item_status = (
                "conflict"
                if any(match["status"] == "conflict" for match in item_matches)
                else "complete"
                if all(match["status"] == "matched" for match in item_matches)
                else "partial"
                if any(
                    match["status"] in {"matched", "partial"}
                    for match in item_matches
                )
                else "missing"
            )

        item["evidence_status"] = item_status
        item["evidence_complete"] = item_status in {"complete", "not_required"}
        item["evidence_matches"] = item_matches
        item["evidence_coverage_rate"] = (
            _round(
                sum(1 for match in item_matches if match["status"] == "matched")
                / len(required)
            )
            if required
            else 1.0
        )
        item["evidence_gaps"] = missing + partial
        if missing or partial or item_status == "conflict":
            gaps.append(
                {
                    "item_id": item["item_id"],
                    "title": item["title"],
                    "max_score": item["max_score"],
                    "missing_evidence": missing,
                    "partial_evidence": partial,
                    "evidence_gaps": missing + partial,
                    "status": item_status,
                    "gap_type": "score_gap",
                    "source_references": item["source_references"],
                }
            )
    return items, all_matches, gaps


def _explicit_match_for(
    matches: list[dict[str, Any]],
    *,
    item: Mapping[str, Any],
    requirement: str,
) -> dict[str, Any] | None:
    linked_ids = set(item.get("linked_requirement_ids") or [])
    candidates = [
        match
        for match in matches
        if match["item_id"] == item["item_id"]
        or match.get("requirement_id") in linked_ids
        or match["item_id"] in linked_ids
    ]
    if not candidates:
        return None
    exact = [
        match
        for match in candidates
        if not match["evidence_requirement"]
        or _same_text(match["evidence_requirement"], requirement)
    ]
    if not exact:
        return None
    if any(match["status"] == "conflict" for match in exact):
        selected = next(match for match in exact if match["status"] == "conflict")
        return dict(selected)
    if {match["status"] for match in exact} >= {"matched", "invalid"}:
        selected = max(
            exact,
            key=lambda match: (match["confidence"], match.get("material_id") or ""),
        )
        return {
            **dict(selected),
            "status": "conflict",
            "reason": "同一评分证据同时存在有效和无效材料，不能合并认定为已满足",
        }
    status_order = {
        "matched": 3,
        "partial": 2,
        "missing": 1,
        "conflict": 0,
        "invalid": 0,
    }
    selected = max(
        exact,
        key=lambda match: (
            status_order[match["status"]],
            match["confidence"],
            match.get("material_id") or "",
        ),
    )
    return dict(selected)


def _match_material(
    requirement: str,
    materials: list[EvidenceMaterial],
    *,
    as_of: date,
) -> dict[str, Any] | None:
    if not materials:
        return None
    candidates: list[tuple[int, float, EvidenceMaterial, str, bool, str]] = []
    required = _compact_text(requirement)
    aliases = _evidence_aliases(requirement)
    for material in materials:
        text = _compact_text(_material_text(material))
        material_type = _compact_text(material.material_type)
        matched = False
        relevance = 0.0
        reason = ""
        if required and required in text:
            matched, relevance, reason = True, 1.0, "evidence phrase found in material"
        elif any(alias in text or alias in material_type for alias in aliases):
            matched, relevance, reason = (
                True,
                0.85,
                "evidence type matched by deterministic alias",
            )
        else:
            overlap = _text_overlap(requirement, _material_text(material))
            if overlap >= 0.5:
                matched, relevance, reason = (
                    True,
                    overlap,
                    "material has partial evidence text overlap",
                )
        if matched:
            valid, validity_reason = _scoring_material_validity(material, as_of)
            candidates.append(
                (3 if relevance >= 1 else 2 if relevance >= 0.85 else 1,
                 relevance,
                 material,
                 reason,
                 valid,
                 validity_reason)
            )
    if not candidates:
        return None
    valid_candidates = [candidate for candidate in candidates if candidate[4]]
    invalid_candidates = [candidate for candidate in candidates if not candidate[4]]
    if valid_candidates and invalid_candidates:
        selected = max(
            [*valid_candidates, *invalid_candidates],
            key=lambda value: (value[0], value[1], value[2].material_id),
        )
        return {
            "material_id": selected[2].material_id,
            "status": "conflict",
            "confidence": _round(selected[1]),
            "reason": "同一评分证据同时存在有效和无效材料，不能合并认定为已满足",
            "source_references": [
                reference.to_dict()
                for candidate in [*valid_candidates, *invalid_candidates]
                for reference in candidate[2].source_references
            ],
        }
    selected_pool = valid_candidates or invalid_candidates
    _, confidence, material, reason, valid, validity_reason = max(
        selected_pool,
        key=lambda value: (value[0], value[1], value[2].material_id),
    )
    return {
        "material_id": material.material_id,
        "status": (
            "matched"
            if valid and confidence >= 0.85
            else "partial"
            if valid
            else "invalid"
        ),
        "confidence": _round(confidence),
        "reason": reason if valid else validity_reason,
        "source_references": [ref.to_dict() for ref in material.source_references],
    }


def _missing_match(item: Mapping[str, Any], requirement: str) -> dict[str, Any]:
    return {
        "material_id": None,
        "status": "missing",
        "confidence": 0.0,
        "reason": "no matching evidence material was supplied",
        "source_references": list(item.get("source_references") or []),
    }


def _assign_priorities(
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    total_score = sum(float(item["max_score"]) for item in items)
    for item in items:
        score_share = float(item["max_score"]) / total_score if total_score else 0.0
        priority_score = score_share * (
            1.0 + 0.35 * float(item["subjective_space_weight"])
        )
        item["score_share"] = _round(score_share)
        item["priority_score"] = _round(priority_score)

    ordered = sorted(
        items,
        key=lambda item: (
            -float(item["priority_score"]),
            -float(item["max_score"]),
            str(item["item_id"]),
        ),
    )
    highest = float(ordered[0]["priority_score"]) if ordered else 0.0
    priorities: list[dict[str, Any]] = []
    for rank, item in enumerate(ordered, start=1):
        item_score = float(item["priority_score"])
        if highest == 0.0 or item_score >= highest * 0.75:
            priority = "P1"
        elif item_score >= highest * 0.40:
            priority = "P2"
        else:
            priority = "P3"
        item["priority"] = priority
        item["priority_rank"] = rank
        item["strategy"] = _strategy_for(item)
        priorities.append(
            {
                "item_id": item["item_id"],
                "title": item["title"],
                "max_score": item["max_score"],
                "priority": priority,
                "priority_rank": rank,
                "priority_score": item["priority_score"],
                "subjective_space": item["subjective_space"],
                "evidence_status": item["evidence_status"],
                "evidence_gaps": list(item["evidence_gaps"]),
                "source_references": list(item["source_references"]),
            }
        )
    return items, priorities


def _strategy_for(item: Mapping[str, Any]) -> str:
    space = item["subjective_space"]
    if space == "high":
        strategy = "优先围绕评分条件组织可核验的主观方案和证明材料"
    elif space == "medium":
        strategy = "优先细化评分条件对应的方案，并同步核对证明材料"
    elif space == "low":
        strategy = "优先逐项核对客观条件、参数和证明材料"
    else:
        strategy = "先确认评分条件的评价方式，再准备对应方案和证明材料"
    if item["evidence_gaps"]:
        strategy += "；当前存在证据缺口"
    return strategy


def _classify_score_type(raw: Mapping[str, Any], item: ScoringItem) -> str:
    value = _first_value(
        raw,
        ("score_type", "scoring_type", "evaluation_type", "评分类型"),
    )
    if value is not None:
        normalized = _normalize_score_type(value)
        if normalized != "unknown":
            return normalized
    text = f"{item.title} {item.criteria}"
    if any(word in text for word in ("报价", "价格", "低价")):
        return "price"
    if any(
        word in text
        for word in (
            "专家评审",
            "方案完整",
            "合理性",
            "可行性",
            "先进性",
            "创新性",
            "服务方案",
            "技术方案",
            "实施方案",
        )
    ):
        return "subjective"
    if any(word in text for word in ("满足", "具备", "提供", "数量", "证书")):
        return "objective"
    return "unknown"


def _classify_subjective_space(
    raw: Mapping[str, Any],
    *,
    score_type: str,
    text: str,
) -> tuple[str, float]:
    explicit = _first_value(
        raw,
        (
            "subjective_space",
            "subjective_score_space",
            "subjectivity",
            "主观评分空间",
        ),
    )
    if explicit is not None:
        level = _subjective_level(explicit)
        return level, _subjective_weight(level)
    if score_type == "subjective":
        return "high", 1.0
    if score_type in {"objective", "price"}:
        return "low", 0.0
    if any(word in text for word in ("评审", "评价", "方案")):
        return "medium", 0.5
    return "unknown", 0.25


def _subjective_level(value: Any) -> str:
    if isinstance(value, bool):
        return "high" if value else "low"
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 1:
            numeric /= 100.0
        if numeric >= 0.66:
            return "high"
        if numeric >= 0.33:
            return "medium"
        return "low"
    text = str(value).strip().lower()
    if any(word in text for word in ("high", "高", "大", "主观")):
        return "high"
    if any(word in text for word in ("medium", "中")):
        return "medium"
    if any(word in text for word in ("low", "低", "小", "客观", "无")):
        return "low"
    return "unknown"


def _subjective_weight(level: str) -> float:
    return {"high": 1.0, "medium": 0.5, "low": 0.0, "unknown": 0.25}[level]


def _normalize_score_type(value: Any) -> str:
    text = str(value).strip().lower()
    if any(word in text for word in ("subjective", "主观", "方案评审")):
        return "subjective"
    if any(word in text for word in ("objective", "客观", "符合性")):
        return "objective"
    if any(word in text for word in ("price", "报价", "价格")):
        return "price"
    return "unknown"


def _parse_scoring_text(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = _parse_scoring_line(line, len(rows))
        if parsed is not None:
            rows.append(parsed)
    return rows


def _parse_scoring_line(line: str, index: int) -> dict[str, Any] | None:
    cells = [part.strip() for part in re.split(r"\s*\|\s*|\t", line.strip(" |"))]
    score: float | None = None
    title = ""
    criteria = ""
    item_id = ""
    if len(cells) >= 2:
        for cell_index, cell in enumerate(cells):
            candidate = _number_from_cell(cell)
            if candidate is not None:
                score = candidate
                if cell_index > 0 and not title:
                    title = cells[0]
                elif cell_index + 1 < len(cells):
                    title = cells[cell_index + 1]
                other_cells = [
                    value
                    for position, value in enumerate(cells)
                    if position
                    not in {cell_index, cells.index(title) if title in cells else -1}
                ]
                criteria = "；".join(value for value in other_cells if value)
                break
    if score is None:
        match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:分|points?)", line, re.I)
        if match is None:
            match = re.search(r"[（(]\s*(\d+(?:\.\d+)?)\s*分?\s*[）)]", line)
        if match is None:
            return None
        score = float(match.group(1))
        prefix = line[: match.start()]
        suffix = line[match.end() :]
        prefix = re.sub(r"^\s*(?:\d+[、.)．]\s*)", "", prefix).strip(" ：:.-")
        suffix = suffix.strip(" ：:")
        if prefix and suffix:
            title, criteria = prefix, suffix
        elif prefix:
            title = prefix
        else:
            parts = re.split(r"[：:]", suffix, maxsplit=1)
            title = parts[0].strip() if parts else suffix
            criteria = parts[1].strip() if len(parts) > 1 else ""
    if not title or score is None:
        return None
    leading_id = re.match(r"^\s*([A-Za-z0-9_-]+)[、.)．]\s*", line)
    if leading_id:
        item_id = leading_id.group(1)
    if not item_id:
        item_id = f"score-{index + 1}"
    return {
        "item_id": item_id,
        "title": title,
        "max_score": score,
        "criteria": criteria,
        "evidence_required": _extract_evidence_from_text(criteria),
    }


def _extract_evidence_from_text(text: str) -> list[str]:
    result: list[str] = []
    patterns = (
        r"(?:需提供|须提供|应提供|提供|附|提交)[：:]?\s*([^。；;，,]+)",
        r"(?:证明材料|证明文件)[：:]?\s*([^。；;，,]+)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            value = match.group(1).strip(" ：:()（）")
            if re.search(r"得\s*\d+(?:\.\d+)?\s*分", value):
                continue
            if value and value not in result:
                result.append(value)
    return result


def _number_from_cell(value: str) -> float | None:
    text = value.strip().replace(",", "")
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*分", text)
    return float(match.group(1)) if match else None


def _material_text(material: EvidenceMaterial) -> str:
    metadata = " ".join(str(value) for value in material.metadata.values())
    return " ".join(
        value
        for value in (
            material.material_type,
            material.title,
            material.content,
            metadata,
        )
        if value
    )


def _evidence_aliases(value: str) -> list[str]:
    text = _compact_text(value)
    aliases = {
        "营业执照": ("营业执照", "执照"),
        "资质证书": ("资质证书", "资质"),
        "类似项目案例": ("类似项目案例", "项目案例", "案例", "合同"),
        "验收报告": ("验收报告", "验收证明", "验收"),
        "人员证书": ("人员证书", "资格证书", "职称证书"),
        "社保证明": ("社保证明", "社保"),
    }
    for key, values in aliases.items():
        if key in text:
            return [_compact_text(item) for item in values]
    return []


def _text_overlap(left: str, right: str) -> float:
    left_tokens = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", left.lower()))
    right_tokens = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", right.lower()))
    if not left_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)


def _compact_text(value: Any) -> str:
    return re.sub(r"[\s\W_]+", "", str(value or "").lower())


def _same_text(left: Any, right: Any) -> bool:
    return _compact_text(left) == _compact_text(right)


def _normalize_match_status(value: Any) -> str:
    text = str(value or "missing").strip().lower()
    aliases = {
        "matched": "matched",
        "match": "matched",
        "已匹配": "matched",
        "partial": "partial",
        "部分": "partial",
        "部分匹配": "partial",
        "missing": "missing",
        "缺失": "missing",
        "invalid": "invalid",
        "无效": "invalid",
        "conflict": "conflict",
        "冲突": "conflict",
    }
    return aliases.get(text, "invalid")


def _scoring_material_validity(
    material: EvidenceMaterial,
    as_of: date,
) -> tuple[bool, str]:
    metadata = material.metadata
    for key in ("valid", "is_valid", "active", "enabled"):
        if key in metadata and str(metadata[key]).strip().lower() in {
            "false",
            "0",
            "no",
            "invalid",
            "无效",
            "过期",
        }:
            return False, f"材料元数据 {key} 明确标记为无效"
    status = str(metadata.get("status") or metadata.get("state") or "").strip().lower()
    if status in {"invalid", "expired", "rejected", "无效", "过期", "不通过"}:
        return False, f"材料状态为 {status}"
    expiry_value = material.valid_until
    if expiry_value in (None, ""):
        for key in ("valid_until", "expires_at", "expiration_date", "expiry_date"):
            if metadata.get(key) not in (None, ""):
                expiry_value = metadata[key]
                break
    if expiry_value in (None, ""):
        return True, "材料未提供有效期"
    expiry = _parse_date_or_none(expiry_value)
    if expiry is None:
        return False, "材料有效期格式无法解析"
    if expiry < as_of:
        return False, f"材料已于 {expiry.isoformat()} 过期"
    return True, f"材料有效至 {expiry.isoformat()}"


def _coerce_rows(value: Any, field_name: str) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, Mapping):
        for key in ("rows", "items", "records", "data"):
            if key in value:
                nested = value[key]
                if not isinstance(nested, (list, tuple)):
                    raise ValueError(f"{field_name}.{key} must be a list")
                return list(nested)
        if "columns" in value and "values" in value:
            columns = value["columns"]
            values = value["values"]
            if not isinstance(columns, (list, tuple)) or not isinstance(
                values, (list, tuple)
            ):
                raise ValueError(f"{field_name} columns and values must be lists")
            return [
                {
                    str(column): row[position] if position < len(row) else None
                    for position, column in enumerate(columns)
                }
                for row in values
                if isinstance(row, (list, tuple))
            ]
        return [dict(value)]
    if isinstance(value, str):
        return [value]
    raise ValueError(f"{field_name} must be a list, object, or text")


def _first_non_empty(data: Mapping[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = data.get(name)
        if value not in (None, "", [], ()):
            return value
    return None


def _first_value(data: Mapping[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in data and data[name] not in (None, ""):
            return data[name]
    return None


def _is_empty(value: Any) -> bool:
    return value in (None, "", [])


def _number_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid numeric value: {value}") from exc


def _explicit_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "是", "可计算", "可确定"}:
        return True
    if text in {"false", "0", "no", "n", "否", "不可计算", "不可确定"}:
        return False
    return None


def _parse_date_or_none(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value in (None, ""):
        return None
    text = str(value).strip()
    chinese = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日?", text)
    if chinese:
        try:
            return date(
                int(chinese.group(1)),
                int(chinese.group(2)),
                int(chinese.group(3)),
            )
        except ValueError:
            return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        pass
    for format_name in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, format_name).date()
        except ValueError:
            continue
    return None


def _round(value: float) -> float:
    return round(float(value), 6)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return [str(item).strip() for item in values if str(item).strip()]


def _deduplicate(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _ensure_unique_item_ids(items: list[Mapping[str, Any]]) -> None:
    seen: set[str] = set()
    for item in items:
        item_id = str(item["item_id"])
        if item_id in seen:
            raise ValueError(f"duplicate scoring item_id: {item_id}")
        seen.add(item_id)

