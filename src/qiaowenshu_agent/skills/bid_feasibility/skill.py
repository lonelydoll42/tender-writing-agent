"""Deterministic bid feasibility Skill.

The Skill deliberately keeps the final decision in ordinary Python rules. An
upstream parser or retrieval service may provide structured requirements and
evidence, but neither an LLM response nor a free-form explanation can turn
missing evidence into a passing check.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Mapping, Sequence

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import (
    Skill,
    SkillManifest,
    SkillRequest,
    SkillResult,
)
from qiaowenshu_agent.domain.models import (
    BidderProfile,
    EvidenceMaterial,
    FeasibilityCheck,
    FeasibilityDecision,
    OCR_REVIEW_THRESHOLD,
    SourceReference,
    TenderRequirement,
)
from qiaowenshu_agent.skills.rule_engine import evaluate_rule_ast
from qiaowenshu_agent.skills.tender_common import parse_requirements


MANIFEST = SkillManifest(
    name="bid-feasibility",
    version="0.1.0",
    description="Determine bid feasibility from requirements and bidder evidence.",
    input_schema={
        "type": "object",
        "required": ["project_id"],
        "properties": {
            "project_id": {"type": "string"},
            "requirements": {"type": "array"},
            "tender_profile": {"type": "object"},
            "bidder_profile": {"type": "object"},
            "bidder": {"type": "object"},
            "materials": {"type": "array"},
            "options": {"type": "object"},
        },
    },
    output_schema={
        "type": "object",
        "required": [
            "project_id",
            "decision",
            "checks",
            "blockers",
            "warnings",
            "summary",
        ],
    },
    capabilities=("tender.feasibility", "tender.eligibility", "tender.evidence"),
    required_permissions=("document.read", "bidder.read"),
)


@dataclass(frozen=True)
class _ParsedInput:
    project_id: str
    requirements: list[TenderRequirement]
    bidder: BidderProfile
    options: dict[str, Any]
    warnings: list[str]


class BidFeasibilitySkill(Skill):
    """Evaluate tender requirements using deterministic evidence rules."""

    manifest = MANIFEST

    async def execute(
        self,
        request: SkillRequest,
        context: SkillContext,
    ) -> SkillResult:
        try:
            payload = _parse_input(request.input, context.state)
        except (TypeError, ValueError) as exc:
            return SkillResult.failure(
                message=str(exc),
                error_code="INVALID_BID_FEASIBILITY_INPUT",
            )

        if not payload.requirements:
            return SkillResult.blocked(
                message="bid feasibility requires at least one tender requirement",
                error_code="BID_FEASIBILITY_REQUIREMENTS_NOT_CONFIGURED",
            )

        decision = evaluate_feasibility(
            payload.project_id,
            payload.requirements,
            payload.bidder,
            options=payload.options,
            initial_warnings=payload.warnings,
        )
        data = decision.to_dict()
        data["summary"] = _summary(decision)
        return SkillResult.success(
            data,
            message=f"bid feasibility completed: {decision.decision}",
        )


def evaluate_feasibility(
    project_id: str,
    requirements: Sequence[TenderRequirement | Mapping[str, Any]],
    bidder: BidderProfile | Mapping[str, Any],
    *,
    options: Mapping[str, Any] | None = None,
    initial_warnings: Sequence[str] | None = None,
) -> FeasibilityDecision:
    """Return a typed, deterministic feasibility decision.

    This public helper is useful for focused tests and for hosts that already
    have domain objects. Mapping inputs are normalized through the same domain
    models used by the Skill facade.
    """

    normalized_requirements = [
        item
        if isinstance(item, TenderRequirement)
        else TenderRequirement.from_mapping(item)
        for item in requirements
    ]
    normalized_bidder = (
        bidder
        if isinstance(bidder, BidderProfile)
        else BidderProfile.from_mapping(bidder)
    )
    settings = dict(options or {})
    checks: list[FeasibilityCheck] = []
    hard_failures: list[str] = []
    hard_unknowns: list[str] = []
    warnings = [str(item) for item in (initial_warnings or []) if str(item).strip()]

    for requirement in normalized_requirements:
        check, effective_mandatory = _evaluate_requirement(
            requirement,
            normalized_bidder,
            options=settings,
        )
        checks.append(check)
        label = f"{requirement.requirement_id}: {requirement.title}"
        if check.status == "fail" and effective_mandatory:
            hard_failures.append(f"{label}；{check.reason}")
        elif check.status == "unknown" and effective_mandatory:
            hard_unknowns.append(f"{label}；{check.reason}")
        elif check.status == "unknown":
            warnings.append(f"待补证据：{label}；{check.reason}")

    if hard_failures:
        decision_name = "no_bid"
    elif hard_unknowns:
        decision_name = "human_review"
        warnings.extend(f"需人工确认：{item}" for item in hard_unknowns)
    else:
        decision_name = "bid"

    return FeasibilityDecision(
        project_id=str(project_id).strip(),
        decision=decision_name,
        checks=checks,
        blockers=hard_failures,
        warnings=_unique_strings(warnings),
    )


def _parse_input(
    data: Mapping[str, Any],
    state: Mapping[str, Any] | None = None,
) -> _ParsedInput:
    if not isinstance(data, Mapping):
        raise TypeError("bid feasibility input must be an object")
    state = state or {}

    project_id = _text(data.get("project_id"))
    if not project_id:
        raw_tender_profile = data.get("tender_profile")
        tender_profile = (
            _object_mapping(raw_tender_profile, "tender_profile")
            if raw_tender_profile is not None
            else {}
        )
        project_id = _text(tender_profile.get("project_id"))
    if not project_id:
        raise ValueError("project_id is required")

    decomposition = _state_mapping(
        data.get("decomposition"),
        state,
        "tender-decomposition",
        "tender_decomposition",
    )
    raw_requirements = _present_value(data, "requirements")
    if raw_requirements is _MISSING or raw_requirements is None:
        raw_requirements = decomposition.get("requirements")
    requirements = parse_requirements(raw_requirements)

    raw_bidder = _present_value(data, "bidder_profile")
    if raw_bidder is _MISSING or raw_bidder is None:
        raw_bidder = _present_value(data, "bidder")
    if raw_bidder is _MISSING or raw_bidder is None:
        raw_bidder = _state_value(
            state,
            "bidder-profile",
            "bidder_profile",
            "bidder",
            "evidence-collection",
            "evidence_collection",
        )

    warnings: list[str] = []
    if raw_bidder is _MISSING or raw_bidder is None:
        bidder_data: dict[str, Any] = {"bidder_id": "unknown"}
        warnings.append(
            "bidder profile is not supplied; missing evidence remains unknown"
        )
    else:
        bidder_data = _object_mapping(raw_bidder, "bidder_profile")

    top_materials = _present_value(data, "materials")
    if top_materials is not _MISSING and top_materials is not None:
        if not isinstance(top_materials, (list, tuple)):
            raise ValueError("materials must be a list")
        current_materials = bidder_data.get("materials") or []
        if not isinstance(current_materials, (list, tuple)):
            raise ValueError("bidder_profile.materials must be a list")
        bidder_data["materials"] = [*current_materials, *top_materials]

    bidder = BidderProfile.from_mapping(bidder_data)
    raw_options = data.get("options") or {}
    if not isinstance(raw_options, Mapping):
        raise ValueError("options must be an object")
    options = dict(raw_options)
    if options.get("as_of") in (None, ""):
        top_level_as_of = data.get("as_of") or data.get("evaluation_date")
        if top_level_as_of not in (None, ""):
            options["as_of"] = top_level_as_of
    return _ParsedInput(
        project_id=project_id,
        requirements=requirements,
        bidder=bidder,
        options=options,
        warnings=warnings,
    )


_MISSING = object()


def _present_value(data: Mapping[str, Any], key: str) -> Any:
    return data[key] if key in data else _MISSING


def _state_value(state: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in state and state[name] is not None:
            value = state[name]
            if hasattr(value, "data") and isinstance(value.data, Mapping):
                return value.data
            return value
    return _MISSING


def _state_mapping(
    value: Any,
    state: Mapping[str, Any],
    *names: str,
) -> dict[str, Any]:
    candidate = value
    if candidate is None or candidate is _MISSING:
        candidate = _state_value(state, *names)
    if candidate is _MISSING or candidate is None:
        return {}
    mapping = _object_mapping(candidate, "decomposition")
    return mapping


def _object_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    elif hasattr(value, "data") and isinstance(value.data, Mapping):
        value = value.data
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return {str(key): item for key, item in value.items()}


def _evaluate_requirement(
    requirement: TenderRequirement,
    bidder: BidderProfile,
    *,
    options: Mapping[str, Any],
) -> tuple[FeasibilityCheck, bool]:
    rule = dict(requirement.check_rule)
    references = list(requirement.source_references)
    effective_mandatory = _is_hard_requirement(requirement)

    rule_ast = rule.get("rule_ast") or rule.get("ast")
    if isinstance(rule_ast, Mapping):
        as_of = _parse_date(
            options.get("as_of") or options.get("evaluation_date")
        ) or date.today()
        evaluation = evaluate_rule_ast(
            rule_ast,
            bidder.materials,
            as_of=as_of,
        )
        status = {
            "matched": "pass",
            "invalid": "fail",
            "partial": "unknown",
            "missing": "unknown",
            "conflict": "unknown",
            "human_review": "unknown",
        }.get(evaluation.status, "unknown")
        return (
            _check(
                requirement,
                status,
                evaluation.reason,
                effective_mandatory,
                _merge_references(
                    references,
                    list(evaluation.source_references),
                ),
            ),
            effective_mandatory,
        )

    if _is_not_applicable(rule):
        return (
            FeasibilityCheck(
                requirement_id=requirement.requirement_id,
                status="not_applicable",
                reason="规则明确标记为不适用",
                mandatory=effective_mandatory,
                source_references=references,
                title=requirement.title,
            ),
            effective_mandatory,
        )

    kind = _requirement_kind(requirement)
    explicit_attribute = _rule_attribute(rule, kind)
    if explicit_attribute:
        found, actual = _lookup_path(bidder.attributes, explicit_attribute)
        if found:
            status, reason = _compare_attribute(actual, rule)
            return (
                _check(
                    requirement,
                    status,
                    reason,
                    effective_mandatory,
                    references,
                ),
                effective_mandatory,
            )
        if _has_comparison(rule):
            metadata_result = _evaluate_material_attribute(
                bidder.materials,
                explicit_attribute,
                rule,
                kind,
                options,
            )
            if metadata_result is not None:
                status, reason, material_refs = metadata_result
                return (
                    _check(
                        requirement,
                        status,
                        reason,
                        effective_mandatory,
                        _merge_references(references, material_refs),
                    ),
                    effective_mandatory,
                )
            return (
                _check(
                    requirement,
                    "unknown",
                    f"投标人属性 {explicit_attribute} 缺失，无法核验要求",
                    effective_mandatory,
                    references,
                ),
                effective_mandatory,
            )

    for attribute in _attribute_candidates(requirement, kind, rule):
        found, actual = _lookup_path(bidder.attributes, attribute)
        if found:
            status, reason = _compare_attribute(actual, rule)
            return (
                _check(
                    requirement,
                    status,
                    f"依据投标人属性 {attribute}：{reason}",
                    effective_mandatory,
                    references,
                ),
                effective_mandatory,
            )

    evidence_result = _evaluate_material_evidence(
        requirement,
        bidder.materials,
        kind,
        options,
    )
    if evidence_result is not None:
        status, reason, material_refs = evidence_result
        return (
            _check(
                requirement,
                status,
                reason,
                effective_mandatory,
                _merge_references(references, material_refs),
            ),
            effective_mandatory,
        )

    return (
        _check(
            requirement,
            "unknown",
            "未找到可核验的投标人属性或证明材料",
            effective_mandatory,
            references,
        ),
        effective_mandatory,
    )


def _check(
    requirement: TenderRequirement,
    status: str,
    reason: str,
    mandatory: bool,
    references: Sequence[SourceReference],
) -> FeasibilityCheck:
    low_confidences = [
        reference.confidence
        for reference in references
        if reference.confidence is not None
        and reference.confidence < OCR_REVIEW_THRESHOLD
    ]
    if status == "pass" and low_confidences:
        source_confidence = min(low_confidences)
        status = "unknown"
        reason = (
            f"{reason} OCR来源置信度为 {source_confidence:.2f}，低于"
            f"人工复核阈值 {OCR_REVIEW_THRESHOLD:.2f}，需人工核验。"
        )
    return FeasibilityCheck(
        requirement_id=requirement.requirement_id,
        status=status,  # type: ignore[arg-type]
        reason=reason,
        mandatory=mandatory,
        source_references=list(references),
        title=requirement.title,
    )


def _is_hard_requirement(requirement: TenderRequirement) -> bool:
    rule = requirement.check_rule
    if "hard" in rule:
        return _truthy(rule["hard"])
    if requirement.mandatory:
        return True
    if requirement.category in {"disqualification", "qualification"}:
        return True
    return _requirement_kind(requirement) == "bid_bond"


def _is_not_applicable(rule: Mapping[str, Any]) -> bool:
    return rule.get("not_applicable") is True or rule.get("applicable") is False


def _requirement_kind(requirement: TenderRequirement) -> str:
    rule = requirement.check_rule
    raw_kind = (
        rule.get("type")
        or rule.get("check_type")
        or rule.get("kind")
        or rule.get("rule_type")
    )
    kind = _canonical_kind(raw_kind)
    if kind:
        return kind

    text = _normalize_text(f"{requirement.title} {requirement.description}")
    if _contains_any(
        text,
        "投标保证金",
        "履约保证金",
        "保证金",
        "保函",
        "bid bond",
        "bid guarantee",
    ):
        return "bid_bond"
    if _contains_any(
        text,
        "人员证书",
        "人员资格",
        "项目经理",
        "技术负责人",
        "certificate",
        "personnel",
        "staff",
    ):
        return "personnel_certificate"
    if _contains_any(
        text,
        "类似项目",
        "类似案例",
        "同类项目",
        "同类案例",
        "案例",
        "业绩",
        "similar case",
        "experience",
    ):
        return "similar_case"
    if _contains_any(
        text,
        "技术参数",
        "技术要求",
        "参数",
        "性能指标",
        "technical",
        "parameter",
        "specification",
    ):
        return "technical_parameter"
    if requirement.category in {"disqualification", "qualification"}:
        return "qualification"
    return "generic"


def _canonical_kind(value: Any) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None
    aliases = {
        "qualification": "qualification",
        "hardqualification": "qualification",
        "eligibility": "qualification",
        "资格": "qualification",
        "硬性资格": "qualification",
        "disqualification": "qualification",
        "similarcase": "similar_case",
        "similarproject": "similar_case",
        "case": "similar_case",
        "experience": "similar_case",
        "类似案例": "similar_case",
        "类似项目": "similar_case",
        "personnelcertificate": "personnel_certificate",
        "staffcertificate": "personnel_certificate",
        "personnel": "personnel_certificate",
        "certificate": "personnel_certificate",
        "人员证书": "personnel_certificate",
        "technicalparameter": "technical_parameter",
        "technical": "technical_parameter",
        "parameter": "technical_parameter",
        "技术参数": "technical_parameter",
        "bidbond": "bid_bond",
        "bidguarantee": "bid_bond",
        "guarantee": "bid_bond",
        "投标保证金": "bid_bond",
        "保证金": "bid_bond",
    }
    return aliases.get(normalized)


def _rule_attribute(rule: Mapping[str, Any], kind: str) -> str:
    for key in ("attribute", "bidder_attribute", "attribute_path", "field", "path"):
        value = _text(rule.get(key))
        if value:
            return value
    if kind == "technical_parameter":
        parameter = _text(rule.get("parameter") or rule.get("parameter_name"))
        if parameter:
            return f"technical_parameters.{parameter}"
    return ""


def _attribute_candidates(
    requirement: TenderRequirement,
    kind: str,
    rule: Mapping[str, Any],
) -> list[str]:
    candidates: list[str] = []
    aliases = {
        "qualification": [
            "qualification_status",
            "eligible",
            "eligibility",
            "qualifications",
            "qualification",
            "business_license",
            "license",
            "certifications",
            "registered_capital",
            "established_years",
        ],
        "similar_case": [
            "similar_case_count",
            "similar_cases",
            "case_count",
            "project_case_count",
            "project_cases",
            "experience",
        ],
        "personnel_certificate": [
            "personnel_certificates",
            "staff_certificates",
            "certificates",
            "personnel",
            "team_certificates",
        ],
        "technical_parameter": [
            "technical_compliance",
            "technical_parameters",
            "parameters",
            "technical_response",
            "capabilities",
        ],
        "bid_bond": [
            "bid_bond_provided",
            "bid_guarantee_provided",
            "bid_bond",
            "bid_guarantee",
            "guarantee",
            "bid_bond_amount",
            "guarantee_amount",
        ],
        "generic": [],
    }
    candidates.extend(aliases.get(kind, []))

    text = _normalize_text(f"{requirement.title} {requirement.description}")
    keyword_aliases = {
        "注册资本": "registered_capital",
        "成立年限": "established_years",
        "从业年限": "established_years",
        "案例数量": "similar_case_count",
        "项目案例": "similar_cases",
        "人员证书": "personnel_certificates",
        "技术参数": "technical_parameters",
        "投标保证金": "bid_bond_amount",
        "保证金": "bid_bond_amount",
    }
    for keyword, attribute in keyword_aliases.items():
        if keyword in text:
            candidates.insert(0, attribute)

    explicit = _rule_attribute(rule, kind)
    if explicit:
        candidates.insert(0, explicit)
    return _unique_strings(candidates)


def _compare_attribute(value: Any, rule: Mapping[str, Any]) -> tuple[str, str]:
    if _is_empty_value(value):
        return "unknown", "属性已提供但没有可核验的值"

    if _has_comparison(rule):
        if "expected" in rule or "equals" in rule or "equal" in rule:
            expected = rule.get("expected", rule.get("equals", rule.get("equal")))
            matched = _values_equal(value, expected)
            return (
                ("pass", f"属性值满足预期 {expected!r}")
                if matched
                else ("fail", f"属性值 {value!r} 不满足预期 {expected!r}")
            )
        minimum = _first_rule_value(rule, "minimum", "min", "at_least")
        if minimum is not _MISSING:
            actual_number = _number_or_length(value)
            expected_number = _decimal(minimum)
            if actual_number is None or expected_number is None:
                return "fail", "属性值或最小值无法解析为可比较的数字"
            return (
                ("pass", f"属性值 {actual_number} 不低于最低要求 {expected_number}")
                if actual_number >= expected_number
                else ("fail", f"属性值 {actual_number} 低于最低要求 {expected_number}")
            )
        maximum = _first_rule_value(rule, "maximum", "max", "at_most")
        if maximum is not _MISSING:
            actual_number = _number_or_length(value)
            expected_number = _decimal(maximum)
            if actual_number is None or expected_number is None:
                return "fail", "属性值或最大值无法解析为可比较的数字"
            return (
                ("pass", f"属性值 {actual_number} 不超过最高要求 {expected_number}")
                if actual_number <= expected_number
                else ("fail", f"属性值 {actual_number} 超过最高要求 {expected_number}")
            )
        contains = _first_rule_value(rule, "contains", "includes")
        if contains is not _MISSING:
            expected_values = (
                list(contains)
                if isinstance(contains, (list, tuple, set))
                else [contains]
            )
            matched = all(_contains_value(value, item) for item in expected_values)
            return (
                ("pass", f"属性值包含要求项 {expected_values!r}")
                if matched
                else ("fail", f"属性值缺少要求项 {expected_values!r}")
            )
        one_of = _first_rule_value(rule, "one_of", "in", "allowed_values")
        if one_of is not _MISSING:
            allowed = one_of if isinstance(one_of, (list, tuple, set)) else [one_of]
            matched = any(_values_equal(value, item) for item in allowed)
            return (
                ("pass", f"属性值属于允许范围 {list(allowed)!r}")
                if matched
                else ("fail", f"属性值 {value!r} 不在允许范围 {list(allowed)!r} 内")
            )

    if _truthy(value):
        return "pass", "属性明确表明要求已满足"
    return "fail", "属性明确表明要求未满足"


def _evaluate_material_evidence(
    requirement: TenderRequirement,
    materials: Sequence[EvidenceMaterial],
    kind: str,
    options: Mapping[str, Any],
) -> tuple[str, str, list[SourceReference]] | None:
    required_types = _required_material_types(requirement, kind)
    if not required_types:
        return None

    explicit_material_types = bool(
        requirement.evidence_required
        or _required_material_types_from_rule(requirement.check_rule, kind)
    )
    evidence_mode = _normalize_text(
        requirement.check_rule.get("evidence_mode")
        or requirement.check_rule.get("material_mode")
        or ("all" if explicit_material_types else "any")
    )
    require_all = evidence_mode not in {"any", "任一", "one"}
    results: list[tuple[str, str, list[SourceReference]]] = []
    for required_type in required_types:
        matches = [
            material
            for material in materials
            if _material_matches(material, required_type, kind)
        ]
        if not matches:
            results.append(("unknown", f"缺少证明材料：{required_type}", []))
            continue
        valid_matches = [
            material
            for material in matches
            if _material_is_valid(material, options)
        ]
        invalid_matches = [
            material for material in matches if material not in valid_matches
        ]
        references = _material_references(matches)
        if valid_matches and invalid_matches:
            results.append(
                (
                    "unknown",
                    (
                        f"证明材料 {required_type} 同时存在有效和无效版本，"
                        "无法确认采用哪一版本"
                    ),
                    references,
                )
            )
        elif not valid_matches:
            results.append(
                (
                    "fail",
                    f"证明材料 {required_type} 均无效或已过期",
                    references,
                )
            )
        else:
            results.append(
                (
                    "pass",
                    f"已找到有效证明材料：{required_type}",
                    _material_references(valid_matches),
                )
            )

    if require_all:
        if any(status == "fail" for status, _, _ in results):
            return _combine_material_results(results, preferred="fail")
        if any(status == "unknown" for status, _, _ in results):
            return _combine_material_results(results, preferred="unknown")
        return _combine_material_results(results, preferred="pass")
    if any(status == "pass" for status, _, _ in results):
        return _combine_material_results(results, preferred="pass")
    if any(status == "unknown" for status, _, _ in results):
        return _combine_material_results(results, preferred="unknown")
    return _combine_material_results(results, preferred="fail")


def _evaluate_material_attribute(
    materials: Sequence[EvidenceMaterial],
    attribute: str,
    rule: Mapping[str, Any],
    kind: str,
    options: Mapping[str, Any],
) -> tuple[str, str, list[SourceReference]] | None:
    required_types = _required_material_types_from_rule(rule, kind)
    matches = [
        material
        for material in materials
        if _material_matches_any(material, required_types, kind)
    ]
    if not matches:
        return None
    valid_matches = [
        material for material in matches if _material_is_valid(material, options)
    ]
    invalid_matches = [
        material for material in matches if material not in valid_matches
    ]
    references = _material_references(matches)
    if valid_matches and invalid_matches:
        return (
            "unknown",
            (
                f"证明材料同时存在有效和无效版本，无法确认属性 {attribute}"
            ),
            references,
        )
    if not valid_matches:
        return (
            "fail",
            f"证明材料均无效，无法核验属性 {attribute}",
            _material_references(matches),
        )
    evaluated: list[tuple[str, str, EvidenceMaterial]] = []
    for material in valid_matches:
        value = _lookup_material_attribute(material, attribute)
        if value is not _MISSING:
            status, reason = _compare_attribute(value, rule)
            evaluated.append((status, reason, material))
    if not evaluated:
        return None
    statuses = {status for status, _, _ in evaluated}
    if "pass" in statuses and "fail" in statuses:
        return (
            "unknown",
            f"不同有效材料对属性 {attribute} 的核验结果冲突，无法确认",
            _material_references([item[2] for item in evaluated]),
        )
    if "unknown" in statuses:
        return (
            "unknown",
            f"属性 {attribute} 存在无法核验的材料结果",
            _material_references([item[2] for item in evaluated]),
        )
    status, reason, material = evaluated[0]
    return (
        status,
        f"依据材料属性 {attribute}：{reason}",
        _material_references([item[2] for item in evaluated]),
    )


def _required_material_types(
    requirement: TenderRequirement,
    kind: str,
) -> list[str]:
    rule_types = _required_material_types_from_rule(requirement.check_rule, kind)
    if rule_types:
        return rule_types
    return list(requirement.evidence_required) or _DEFAULT_MATERIAL_TYPES.get(kind, [])


def _required_material_types_from_rule(
    rule: Mapping[str, Any],
    kind: str,
) -> list[str]:
    raw = (
        rule.get("evidence_types")
        or rule.get("material_types")
        or rule.get("required_material_types")
    )
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if not isinstance(raw, (list, tuple, set)):
        raise ValueError("check_rule.evidence_types must be a list or string")
    return [_text(item) for item in raw if _text(item)]


_DEFAULT_MATERIAL_TYPES: dict[str, list[str]] = {
    "qualification": ["qualification", "business_license", "资质证书", "营业执照"],
    "similar_case": ["similar_case", "project_case", "similar_project", "案例"],
        "personnel_certificate": [
            "personnel_certificate",
            "staff_certificate",
            "certificate",
        ],
    "technical_parameter": [
        "technical_response",
        "technical_certificate",
        "技术参数响应",
    ],
    "bid_bond": ["bid_bond", "bid_guarantee", "bank_guarantee", "投标保证金"],
    "generic": [],
}


_MATERIAL_ALIASES: dict[str, set[str]] = {
    "qualification": {
        "qualification",
        "qualificationcertificate",
        "qualificationcertification",
        "businesslicense",
        "license",
        "资质",
        "资质证书",
        "营业执照",
        "认证",
        "certification",
    },
    "similar_case": {
        "similarcase",
        "projectcase",
        "similarproject",
        "case",
        "projectexperience",
        "案例",
        "项目案例",
        "类似项目",
        "业绩",
    },
    "personnel_certificate": {
        "personnelcertificate",
        "staffcertificate",
        "certificate",
        "qualificationcertificateforstaff",
        "resume",
        "人员证书",
        "人员资格证书",
        "证书",
        "简历",
    },
    "technical_parameter": {
        "technicalresponse",
        "technicalcertificate",
        "technicalparameter",
        "technicalspecification",
        "技术参数响应",
        "技术参数",
        "技术方案",
    },
    "bid_bond": {
        "bidbond",
        "bidguarantee",
        "bankguarantee",
        "guarantee",
        "投标保证金",
        "投标保函",
        "保函",
    },
}


def _material_matches(
    material: EvidenceMaterial,
    required_type: str,
    kind: str,
) -> bool:
    required = _normalize_text(required_type)
    if not required:
        return False
    candidates = {
        _normalize_text(material.material_type),
        _normalize_text(material.title),
    }
    for value in material.metadata.values():
        if isinstance(value, (str, int, float, bool)):
            candidates.add(_normalize_text(value))
    aliases = _MATERIAL_ALIASES.get(kind, set())
    required_kind = _canonical_kind(required_type)
    required_aliases = _MATERIAL_ALIASES.get(required_kind or "", set())
    accepted = required_aliases or {required}
    required_is_kind_alias = (
        required_kind == kind
        or required in aliases
        or required in required_aliases
    )
    for candidate in candidates:
        if not candidate:
            continue
        if candidate in accepted:
            return True
        if any(
            _safe_type_contains(candidate, accepted_item)
            for accepted_item in accepted
        ):
            return True
        if required_is_kind_alias and candidate in aliases:
            return True
    return False


def _safe_type_contains(candidate: str, accepted: str) -> bool:
    if len(candidate) < 2 or len(accepted) < 2:
        return False
    if re.fullmatch(r"[0-9.]+", candidate):
        return False
    return candidate in accepted or accepted in candidate


def _material_matches_any(
    material: EvidenceMaterial,
    required_types: Sequence[str],
    kind: str,
) -> bool:
    return any(_material_matches(material, item, kind) for item in required_types)


def _material_is_valid(material: EvidenceMaterial, options: Mapping[str, Any]) -> bool:
    metadata = material.metadata
    status = _normalize_text(metadata.get("status"))
    if status in {"invalid", "expired", "rejected", "无效", "过期", "不通过"}:
        return False
    if metadata.get("valid") is False or metadata.get("is_valid") is False:
        return False
    as_of = options.get("as_of") or options.get("evaluation_date")
    if as_of and material.valid_until:
        expiry = _parse_date(material.valid_until)
        evaluation = _parse_date(as_of)
        if expiry is not None and evaluation is not None and expiry < evaluation:
            return False
    return True


def _lookup_material_attribute(
    material: EvidenceMaterial,
    attribute: str,
) -> Any:
    path = attribute.split(".")
    found, value = _lookup_path(material.metadata, path[0])
    if found and len(path) == 1:
        return value
    if found and len(path) > 1:
        return _lookup_path_value(value, path[1:])
    if path[-1] == "amount":
        return material.metadata.get("amount", _MISSING)
    return _MISSING


def _lookup_path(
    mapping: Mapping[str, Any],
    path: str | Sequence[str],
) -> tuple[bool, Any]:
    segments = path.split(".") if isinstance(path, str) else list(path)
    current: Any = mapping
    for segment in segments:
        if isinstance(current, Mapping) and segment in current:
            current = current[segment]
        else:
            return False, None
    return True, current


def _lookup_path_value(value: Any, segments: Sequence[str]) -> Any:
    current = value
    for segment in segments:
        if isinstance(current, Mapping) and segment in current:
            current = current[segment]
        else:
            return _MISSING
    return current


def _has_comparison(rule: Mapping[str, Any]) -> bool:
    return any(
        key in rule
        for key in (
            "expected",
            "equals",
            "equal",
            "minimum",
            "min",
            "at_least",
            "maximum",
            "max",
            "at_most",
            "contains",
            "includes",
            "one_of",
            "in",
            "allowed_values",
        )
    )


def _first_rule_value(rule: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in rule:
            return rule[key]
    return _MISSING


def _values_equal(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool):
        return _truthy(actual) is expected
    actual_number = _decimal(actual)
    expected_number = _decimal(expected)
    if actual_number is not None and expected_number is not None:
        return actual_number == expected_number
    if isinstance(actual, (list, tuple, set)):
        return any(_values_equal(item, expected) for item in actual)
    return _normalize_text(actual) == _normalize_text(expected)


def _contains_value(actual: Any, expected: Any) -> bool:
    if isinstance(actual, Mapping):
        return any(_values_equal(key, expected) for key in actual) or any(
            _values_equal(value, expected) for value in actual.values()
        )
    if isinstance(actual, (list, tuple, set)):
        return any(_values_equal(item, expected) for item in actual)
    return _normalize_text(expected) in _normalize_text(actual)


def _number_or_length(value: Any) -> Decimal | None:
    if isinstance(value, (list, tuple, set, Mapping)):
        return Decimal(len(value))
    return _decimal(value)


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float, Decimal)):
        return value != 0
    if isinstance(value, str):
        normalized = _normalize_text(value)
        if normalized in {
            "false",
            "no",
            "否",
            "不",
            "不满足",
            "未满足",
            "未提供",
            "无",
            "invalid",
            "不通过",
        }:
            return False
        return bool(normalized)
    return bool(value)


def _is_empty_value(value: Any) -> bool:
    return value is None or value == "" or (
        isinstance(value, (list, tuple, set, Mapping)) and not value
    )


def _material_references(
    materials: Sequence[EvidenceMaterial],
) -> list[SourceReference]:
    references: list[SourceReference] = []
    for material in materials:
        references = _merge_references(references, material.source_references)
    return references


def _combine_material_results(
    results: Sequence[tuple[str, str, list[SourceReference]]],
    *,
    preferred: str,
) -> tuple[str, str, list[SourceReference]]:
    reasons = [reason for status, reason, _ in results if status == preferred]
    references: list[SourceReference] = []
    for _, _, item_references in results:
        references = _merge_references(references, item_references)
    return preferred, "；".join(reasons), references


def _merge_references(
    first: Sequence[SourceReference],
    second: Sequence[SourceReference],
) -> list[SourceReference]:
    result: list[SourceReference] = []
    seen: set[tuple[str, int | None, str, str, str]] = set()
    for reference in [*first, *second]:
        key = (
            reference.document_id,
            reference.page,
            reference.section,
            reference.quote,
            reference.locator,
        )
        if key not in seen:
            seen.add(key)
            result.append(reference)
    return result


def _summary(decision: FeasibilityDecision) -> dict[str, Any]:
    counts = {status: 0 for status in ("pass", "fail", "unknown", "not_applicable")}
    for check in decision.checks:
        counts[check.status] = counts.get(check.status, 0) + 1
    return {
        "check_count": len(decision.checks),
        "status_counts": counts,
        "mandatory_fail_count": sum(
            1
            for check in decision.checks
            if check.mandatory and check.status == "fail"
        ),
        "mandatory_unknown_count": sum(
            1
            for check in decision.checks
            if check.mandatory and check.status == "unknown"
        ),
    }


def _unique_strings(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _text(value: Any, default: str = "") -> str:
    return str(value).strip() if value is not None else default


def _normalize_text(value: Any) -> str:
    text = _text(value).lower()
    return re.sub(r"[\s_\-:/\\.，。、“”‘’()（）【】\[\]{}]+", "", text)


def _contains_any(text: str, *keywords: str) -> bool:
    return any(_normalize_text(keyword) in text for keyword in keywords)


def _parse_date(value: Any) -> date | None:
    text = _text(value)
    if not text:
        return None
    text = text.replace("年", "-").replace("月", "-").replace("日", "")
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None
