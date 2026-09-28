"""Stable machine-readable output for tender analysis.

The protocol deliberately keeps bid eligibility, document preparation status,
evidence gaps, and score coverage as separate concepts.  The human report is
rendered from this normalized object and is never used as the source of truth.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from typing import Any


ANALYSIS_PROTOCOL_VERSION = "2.0"
BID_DECISIONS = {"bid", "no_bid", "human_review"}
WRITING_STATUSES = {
    "not_started",
    "drafting",
    "ready_for_review",
    "ready_for_submission",
    "submitted",
}
GAP_TYPES = {
    "qualification_gap",
    "score_gap",
    "technical_confirmation",
    "submission_gap",
    "human_review",
}


def derive_writing_status(data: Mapping[str, Any]) -> str:
    """Derive document preparation status without changing bid eligibility."""

    explicit = data.get("writing_status") or data.get("document_status")
    if explicit:
        status = str(explicit).strip()
        if status not in WRITING_STATUSES:
            raise ValueError(f"unsupported writing status: {status}")
        return status
    if data.get("submitted") is True:
        return "submitted"

    draft = data.get("draft")
    if isinstance(draft, Mapping):
        if draft.get("ready_for_submission") or draft.get("submission_ready"):
            return "ready_for_submission"
        if draft.get("reviewed") or draft.get("ready_for_review"):
            return "ready_for_review"
        return "drafting"
    if draft or data.get("response_map") or data.get("sections"):
        return "drafting"
    return "not_started"


def classify_gap_type(gap: Mapping[str, Any]) -> str:
    """Classify a gap using explicit metadata first, then stable categories."""

    explicit = str(
        gap.get("gap_type") or gap.get("gap_category") or gap.get("type") or ""
    ).strip()
    if explicit in GAP_TYPES:
        return explicit

    if gap.get("conflict") or gap.get("ambiguous") or gap.get("verification_pending"):
        return "human_review"

    category = str(gap.get("category") or gap.get("item_type") or "").strip().lower()
    if category in {"disqualification", "qualification", "资格", "废标"}:
        return "qualification_gap"
    if category in {"scoring", "score", "评分"}:
        return "score_gap"
    if category in {"technical", "compliance", "技术", "符合性"}:
        return "technical_confirmation"
    if category in {"format", "commercial", "submission", "形式", "商务"}:
        return "submission_gap"
    if str(gap.get("status") or "").lower() in {
        "unknown",
        "unreviewed",
        "conflict",
    }:
        return "human_review"
    return "human_review"


def normalize_gap(gap: Mapping[str, Any], *, fallback_id: str) -> dict[str, Any]:
    gap_id = str(
        gap.get("gap_id")
        or gap.get("id")
        or gap.get("requirement_id")
        or gap.get("item_id")
        or fallback_id
    ).strip()
    title = str(gap.get("title") or gap.get("requirement") or gap_id).strip()
    reason = str(gap.get("reason") or gap.get("message") or "证据尚未闭合").strip()
    evidence = gap.get("evidence") or gap.get("evidence_material_ids") or []
    if isinstance(evidence, str):
        evidence = [evidence]
    if not isinstance(evidence, (list, tuple, set)):
        evidence = []
    references = gap.get("source_references") or gap.get("evidence_source_references")
    if isinstance(references, Mapping):
        references = [references]
    if not isinstance(references, (list, tuple)):
        references = []
    return {
        "gap_id": gap_id,
        "gap_type": classify_gap_type(gap),
        "title": title,
        "status": str(gap.get("status") or "unknown").strip(),
        "reason": reason,
        "evidence": _unique_strings(evidence),
        "source_references": [item for item in references if isinstance(item, Mapping)],
    }


def build_machine_json(
    data: Mapping[str, Any],
    *,
    project: Mapping[str, Any] | None = None,
    feasibility: Mapping[str, Any] | None = None,
    scoring: Mapping[str, Any] | None = None,
    evidence_gaps: Sequence[Mapping[str, Any]] | None = None,
    fatal_risks: Sequence[Mapping[str, Any] | str] | None = None,
) -> dict[str, Any]:
    """Build and validate the protocol object from upstream Skill outputs."""

    root = _mapping(data)
    feasibility_data = _mapping(
        feasibility if feasibility is not None else root.get("feasibility")
    )
    scoring_data = _mapping(scoring if scoring is not None else root.get("scoring"))
    decision = str(
        feasibility_data.get("decision")
        or root.get("bid_decision")
        or root.get("decision")
        or "human_review"
    ).strip()
    if decision not in BID_DECISIONS:
        raise ValueError(f"unsupported bid decision: {decision}")

    raw_project = (
        project
        if project is not None
        else root.get("project")
        or root.get("tender_profile")
        or root.get("profile")
        or {}
    )
    project_data = _mapping(raw_project)
    project_data.setdefault("project_id", str(root.get("project_id") or "").strip())

    hard_requirements = _hard_requirements(feasibility_data)
    score = _score_object(scoring_data)

    raw_gaps: list[Mapping[str, Any]] = []
    raw_gaps.extend(
        _mappings(
            evidence_gaps
            if evidence_gaps is not None
            else root.get("evidence_gaps")
        )
    )
    raw_gaps.extend(_mappings(_mapping(root.get("ledger")).get("evidence_gaps")))
    raw_gaps.extend(
        {**item, "category": "scoring"}
        for item in _mappings(scoring_data.get("evidence_gaps"))
    )
    for check in _mappings(feasibility_data.get("checks")):
        if str(check.get("status") or "") in {"unknown", "fail"}:
            raw_gaps.append(
                {
                    "requirement_id": check.get("requirement_id"),
                    "title": check.get("title") or check.get("requirement_id"),
                    "status": check.get("status"),
                    "reason": check.get("reason"),
                    "category": "qualification" if check.get("mandatory") else "other",
                    "source_references": check.get("source_references") or [],
                }
            )
    gaps = _dedupe_gaps(raw_gaps)

    risks: list[dict[str, Any]] = []
    raw_risks = fatal_risks if fatal_risks is not None else root.get("fatal_risks")
    for index, item in enumerate(raw_risks or [], start=1):
        if isinstance(item, Mapping):
            risks.append(dict(item))
        else:
            risks.append(
                {
                    "risk_id": f"RISK-{index:03d}",
                    "severity": "high",
                    "message": str(item),
                }
            )
    for blocker in _values(feasibility_data.get("blockers")):
        risks.append(
            {
                "risk_id": f"FEASIBILITY-{len(risks) + 1:03d}",
                "severity": "high",
                "message": str(blocker),
                "type": "qualification",
            }
        )
    compliance = _mapping(root.get("compliance"))
    for finding in _mappings(compliance.get("findings")):
        if str(finding.get("severity") or "") in {"blocker", "high_risk"}:
            risks.append(dict(finding))

    result = {
        "protocol_version": ANALYSIS_PROTOCOL_VERSION,
        "bid_decision": decision,
        "writing_status": derive_writing_status(root),
        "project": project_data,
        "hard_requirements": hard_requirements,
        "score": score,
        "evidence_gaps": gaps,
        "fatal_risks": _dedupe_risks(risks),
    }
    validate_machine_json(result)
    return result


def render_human_report(machine_json: Mapping[str, Any]) -> str:
    """Render a short report from protocol data without inventing facts."""

    score = _mapping(machine_json.get("score"))
    lines = [
        "# 投标分析摘要",
        f"- 投标决策：{machine_json.get('bid_decision')}",
        f"- 投标文件状态：{machine_json.get('writing_status')}",
        f"- 评分规则总分：{score.get('rule_total', 0)}分",
        f"- 当前可证明客观分：{score.get('objective_proven', 0)}分",
        f"- 尚未证明客观分：{score.get('objective_unproven', 0)}分",
        f"- 价格分当前可计算：{'是' if score.get('price_available') else '否'}",
        (
            "- 主观技术分当前可确定："
            f"{'是' if score.get('subjective_available') else '否'}"
        ),
    ]
    gaps = machine_json.get("evidence_gaps") or []
    if gaps:
        lines.append("- 主要证据缺口：")
        lines.extend(
            f"  - {item.get('gap_type')}：{item.get('title')}；{item.get('reason')}"
            for item in gaps
            if isinstance(item, Mapping)
        )
    risks = machine_json.get("fatal_risks") or []
    if risks:
        lines.append("- 主要风险：")
        lines.extend(
            f"  - {item.get('message') or item.get('reason') or item}"
            for item in risks
            if isinstance(item, Mapping)
        )
    return "\n".join(lines)


def validate_machine_json(data: Mapping[str, Any]) -> None:
    required = {
        "protocol_version",
        "bid_decision",
        "writing_status",
        "project",
        "hard_requirements",
        "score",
        "evidence_gaps",
        "fatal_risks",
    }
    missing = sorted(required - set(data))
    if missing:
        raise ValueError(f"analysis JSON is missing fields: {missing}")
    if data["protocol_version"] != ANALYSIS_PROTOCOL_VERSION:
        raise ValueError("unsupported analysis protocol version")
    if data["bid_decision"] not in BID_DECISIONS:
        raise ValueError("invalid bid_decision")
    if data["writing_status"] not in WRITING_STATUSES:
        raise ValueError("invalid writing_status")
    if not isinstance(data["project"], Mapping):
        raise ValueError("project must be an object")
    if not isinstance(data["hard_requirements"], list):
        raise ValueError("hard_requirements must be a list")
    score = data["score"]
    if not isinstance(score, Mapping):
        raise ValueError("score must be an object")
    for key in (
        "rule_total",
        "objective_proven",
        "objective_unproven",
        "price_available",
        "price_score",
        "price_max_score",
        "subjective_available",
        "subjective_max_score",
    ):
        if key not in score:
            raise ValueError(f"score is missing {key}")
    if not isinstance(data["evidence_gaps"], list):
        raise ValueError("evidence_gaps must be a list")
    if not isinstance(data["fatal_risks"], list):
        raise ValueError("fatal_risks must be a list")


def _hard_requirements(feasibility: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    status_map = {
        "pass": "satisfied",
        "fail": "failed",
        "unknown": "unknown",
        "not_applicable": "not_applicable",
    }
    for check in _mappings(feasibility.get("checks")):
        references = _reference_mappings(check.get("source_references"))
        evidence = check.get("evidence_material_ids") or check.get("evidence") or []
        if isinstance(evidence, str):
            evidence = [evidence]
        if not isinstance(evidence, (list, tuple, set)):
            evidence = []
        if not evidence:
            evidence = [
                str(ref.get("document_id"))
                for ref in references
                if ref.get("document_id")
            ]
        result.append(
            {
                "id": str(check.get("requirement_id") or "").strip(),
                "requirement": str(
                    check.get("title")
                    or check.get("requirement")
                    or check.get("requirement_id")
                    or ""
                ).strip(),
                "status": status_map.get(
                    str(check.get("status") or "unknown"), "unknown"
                ),
                "mandatory": bool(check.get("mandatory")),
                "evidence": _unique_strings(evidence),
                "reason": str(check.get("reason") or "").strip(),
                "source_references": references,
            }
        )
    return result


def _score_object(scoring: Mapping[str, Any]) -> dict[str, Any]:
    summary = _mapping(scoring.get("summary"))
    items = _mappings(scoring.get("scoring_items"))
    item_total = sum(_number(item.get("max_score")) for item in items)
    item_objective_max = sum(
        _number(item.get("max_score"))
        for item in items
        if str(item.get("score_type") or "").strip().lower() == "objective"
    )
    item_price_max = sum(
        _number(item.get("max_score"))
        for item in items
        if str(item.get("score_type") or "").strip().lower() == "price"
    )
    item_subjective_max = sum(
        _number(item.get("max_score"))
        for item in items
        if str(item.get("score_type") or "").strip().lower() == "subjective"
    )
    total = _number(summary.get("total_score", summary.get("rule_total", item_total)))
    objective_proven_value = summary.get("objective_proven_score")
    if objective_proven_value is None:
        objective_proven_value = summary.get("objective_proven")
    if objective_proven_value is None and items:
        objective_proven_value = sum(
            _number(item.get("max_score"))
            for item in items
            if str(item.get("score_type") or "").strip().lower() == "objective"
            and bool(item.get("evidence_complete"))
        )
    if objective_proven_value is None:
        objective_proven_value = summary.get("covered_score", 0)
    objective_max = _number(summary.get("objective_max_score", item_objective_max))
    objective_proven = _number(objective_proven_value)
    objective_unproven_value = summary.get("objective_unproven_score")
    if objective_unproven_value is None:
        objective_unproven_value = summary.get("objective_unproven")
    if objective_unproven_value is None:
        objective_unproven_value = max(0.0, objective_max - objective_proven)
    if objective_max == 0.0 and (
        objective_proven > 0.0 or _number(objective_unproven_value) > 0.0
    ):
        objective_max = _number(objective_proven + _number(objective_unproven_value))
    price_max = _number(summary.get("price_max_score", item_price_max))
    subjective_max = _number(
        summary.get("subjective_max_score", item_subjective_max)
    )
    price_score = _number_or_none(summary.get("price_score"))
    subjective_score = summary.get("subjective_score")
    price_available = bool(
        summary.get("price_available", price_score is not None)
    )
    subjective_available = bool(
        summary.get(
            "subjective_available",
            subjective_score is not None
            or summary.get("subjective_scores") is not None,
        )
    )
    unclassified = max(0.0, total - objective_max - price_max - subjective_max)
    return {
        "rule_total": total,
        "objective_proven": _number(objective_proven),
        "objective_unproven": _number(objective_unproven_value),
        "objective_max_score": objective_max,
        "unclassified_score": _number(unclassified),
        "price_available": price_available,
        "price_score": price_score,
        "price_max_score": price_max,
        "subjective_available": subjective_available,
        "subjective_max_score": subjective_max,
    }


def _dedupe_gaps(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, value in enumerate(values, start=1):
        normalized = normalize_gap(value, fallback_id=f"GAP-{index:03d}")
        key = (normalized["gap_id"], normalized["gap_type"])
        if key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def _dedupe_risks(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, value in enumerate(values, start=1):
        item = dict(value)
        key = str(
            item.get("risk_id")
            or item.get("finding_id")
            or item.get("message")
            or item.get("reason")
            or index
        )
        if key not in seen:
            seen.add(key)
            item.setdefault("risk_id", key)
            result.append(item)
    return result


def _mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "data") and isinstance(value.data, Mapping):
        value = value.data
    elif hasattr(value, "to_dict"):
        value = value.to_dict()
    elif is_dataclass(value):
        value = asdict(value)
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _mappings(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    return [
        _mapping(item)
        for item in value
        if isinstance(item, Mapping) or hasattr(item, "to_dict")
    ]


def _reference_mappings(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    return [_mapping(item) for item in value if isinstance(item, Mapping)]


def _values(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _number_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _unique_strings(values: Sequence[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
