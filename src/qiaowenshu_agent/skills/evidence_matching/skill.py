"""Deterministic matching of tender evidence requirements to bidder materials."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import (
    Skill,
    SkillManifest,
    SkillRequest,
    SkillResult,
)
from qiaowenshu_agent.domain.models import (
    EvidenceMaterial,
    EvidenceMatch,
    OCR_REVIEW_THRESHOLD,
    ScoringItem,
    SourceReference,
    TenderRequirement,
)
from qiaowenshu_agent.skills.rule_engine import evaluate_rule_ast


_EVIDENCE_TYPE_ALIASES: dict[str, tuple[str, ...]] = {
    "business_license": ("营业执照", "business license", "统一社会信用代码"),
    "qualification": ("资质证书", "资质证明", "企业资质", "许可证"),
    "certification": (
        "iso",
        "认证证书",
        "体系认证",
        "质量管理体系",
        "环境管理体系",
        "职业健康安全",
    ),
    "project_case": (
        "项目案例",
        "项目业绩",
        "类似业绩",
        "同类业绩",
        "项目经验",
        "类似项目",
        "业绩证明",
    ),
    "contract": ("合同", "项目合同", "合同关键页"),
    "acceptance": ("验收报告", "验收证明", "验收证书"),
    "award": ("获奖证书", "奖项", "荣誉证书"),
    "patent": ("专利", "专利证书"),
    "software_copyright": ("软件著作权", "软著", "计算机软件著作权"),
    "personnel_certificate": (
        "人员证书",
        "人员资格证",
        "职称证",
        "职业资格",
        "执业资格",
    ),
    "resume": ("人员简历", "项目经理简历", "简历", "履历"),
    "education": ("学历证书", "学位证", "学历证明"),
    "social_security": ("社保证明", "社保缴纳证明", "社保证明材料", "社保"),
    "financial_report": ("财务报告", "审计报告", "财务报表"),
    "tax": ("纳税证明", "完税证明", "纳税信用"),
    "credit": ("信用证明", "信用报告", "信用中国"),
    "authorization": ("授权委托书", "法定代表人授权", "授权书"),
    "bid_bond": ("投标保证金", "保证金缴纳证明", "银行保函", "保函"),
    "bank_reference": ("银行资信", "资信证明"),
    "commitment": ("承诺函", "承诺书", "服务承诺"),
    "technical_solution": ("技术方案", "实施方案", "技术响应"),
    "quotation": ("报价文件", "报价表", "开标一览表"),
}

_DOMAIN_TERMS = tuple(
    sorted(
        {
            term
            for aliases in _EVIDENCE_TYPE_ALIASES.values()
            for term in aliases
        }
        | {
            "近三年",
            "三年内",
            "项目负责人",
            "技术负责人",
            "智慧交通",
            "信息化",
            "软件开发",
            "系统集成",
            "运维服务",
            "服务能力",
            "注册资本",
            "成立年限",
            "本科",
            "硕士",
            "博士",
            "履约能力",
        },
        key=len,
        reverse=True,
    )
)

_STOP_TERMS = {
    "投标人",
    "供应商",
    "采购人",
    "应当",
    "须提供",
    "应提供",
    "提供",
    "证明材料",
    "证明",
    "材料",
    "相关",
    "符合",
    "满足",
    "具有",
    "要求",
    "企业",
    "公司",
}

_RULE_KEYWORDS = (
    "keyword",
    "keywords",
    "tag",
    "tags",
    "semantic_tag",
    "semantic_tags",
    "semantic_label",
    "semantic_labels",
    "labels",
    "terms",
)
_RULE_EVIDENCE_TYPES = (
    "evidence_type",
    "evidence_types",
    "material_type",
    "material_types",
    "required_evidence_type",
    "required_evidence_types",
)
_INVALID_STATUS_VALUES = {
    "invalid",
    "expired",
    "revoked",
    "void",
    "cancelled",
    "canceled",
    "rejected",
    "unverified",
    "pending",
    "失效",
    "过期",
    "撤销",
    "作废",
    "未核验",
}
_FALSE_VALUES = {"false", "0", "no", "否", "无", "失效", "过期"}
_TRUE_VALUES = {"true", "1", "yes", "是", "有效"}
_PARTIAL_THRESHOLD = 0.30
_STRONG_THRESHOLD = 0.65


@dataclass(frozen=True)
class _Target:
    identifier: str
    title: str
    description: str
    kind: str
    category: str
    mandatory: bool
    evidence_required: tuple[str, ...]
    check_rule: dict[str, Any]
    max_score: float | None
    source_references: tuple[SourceReference, ...]


@dataclass(frozen=True)
class _Candidate:
    material: EvidenceMaterial
    type_score: float
    keyword_score: float
    tag_score: float
    relevance: float
    matched_terms: tuple[str, ...]
    validity: str
    validity_reason: str


MANIFEST = SkillManifest(
    name="evidence-matching",
    version="0.1.0",
    description=(
        "Match tender requirements and scoring items to bidder evidence "
        "materials with auditable rules."
    ),
    input_schema={
        "type": "object",
        "required": ["materials"],
        "properties": {
            "project_id": {"type": "string"},
            "requirements": {"type": "array"},
            "scoring_items": {"type": "array"},
            "materials": {"type": "array"},
            "evidence_materials": {"type": "array"},
            "bidder_profile": {"type": "object"},
            "as_of": {"type": ["string", "null"]},
            "options": {"type": "object"},
        },
    },
    output_schema={
        "type": "object",
        "required": ["matches", "summary", "warnings"],
    },
    capabilities=("tender.evidence.match", "tender.evidence.coverage"),
    required_permissions=("document.read",),
)


class EvidenceMatchingSkill(Skill):
    """Match evidence without depending on an LLM or external service."""

    manifest = MANIFEST

    async def execute(
        self,
        request: SkillRequest,
        _context: SkillContext,
    ) -> SkillResult:
        try:
            payload = _parse_input(request.input)
            data = _match_payload(payload)
        except (TypeError, ValueError) as exc:
            return SkillResult.failure(
                message=str(exc),
                error_code="INVALID_EVIDENCE_MATCHING_INPUT",
            )
        return SkillResult.success(data, message="evidence matching completed")


def _parse_input(data: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise ValueError("evidence matching input must be an object")

    raw_requirements = _first_present(data, "requirements", "tender_requirements")
    raw_scoring_items = _first_present(data, "scoring_items", "scores")
    requirements = [
        _coerce_requirement(item)
        for item in _as_sequence(raw_requirements, "requirements")
    ]
    scoring_items = [
        _coerce_scoring_item(item)
        for item in _as_sequence(raw_scoring_items, "scoring_items")
    ]

    if data.get("requirement") is not None:
        requirements.extend(
            _coerce_requirement(item)
            for item in _as_sequence(data["requirement"], "requirement")
        )
    if data.get("scoring_item") is not None:
        scoring_items.extend(
            _coerce_scoring_item(item)
            for item in _as_sequence(data["scoring_item"], "scoring_item")
        )

    raw_items = data.get("items")
    if raw_items is not None:
        for item in _as_sequence(raw_items, "items"):
            if isinstance(item, ScoringItem):
                scoring_items.append(item)
                continue
            if isinstance(item, TenderRequirement):
                requirements.append(item)
                continue
            if not isinstance(item, Mapping):
                raise ValueError("items items must be requirement or scoring objects")
            kind = str(item.get("kind") or item.get("item_type") or "").lower()
            if kind in {"scoring", "score", "scoring_item"}:
                scoring_items.append(_coerce_scoring_item(item))
            else:
                requirements.append(_coerce_requirement(item))

    if not requirements and not scoring_items:
        raise ValueError("requirements or scoring_items is required")

    raw_materials = _first_present(data, "materials", "evidence_materials", "evidence")
    if raw_materials is None:
        bidder = data.get("bidder_profile") or data.get("bidder")
        if isinstance(bidder, Mapping):
            raw_materials = bidder.get("materials")
        elif hasattr(bidder, "materials"):
            raw_materials = getattr(bidder, "materials")
    materials = [
        _coerce_material(item)
        for item in _as_sequence(raw_materials, "materials")
    ]

    options = data.get("options") or {}
    if not isinstance(options, Mapping):
        raise ValueError("options must be an object")
    as_of_value = _first_present(data, "as_of")
    if as_of_value is None:
        as_of_value = options.get("as_of")
    as_of = _parse_date(as_of_value) if as_of_value is not None else date.today()

    target_ids = [item.requirement_id for item in requirements]
    target_ids.extend(item.item_id for item in scoring_items)
    duplicates = sorted(
        identifier
        for identifier, count in Counter(target_ids).items()
        if count > 1
    )
    if duplicates:
        raise ValueError(f"duplicate requirement or scoring item IDs: {duplicates}")

    return {
        "project_id": str(data.get("project_id") or "").strip(),
        "requirements": requirements,
        "scoring_items": scoring_items,
        "materials": materials,
        "as_of": as_of,
        "options": dict(options),
    }


def _match_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    targets = [
        _target_from_requirement(item) for item in payload["requirements"]
    ]
    targets.extend(
        _target_from_scoring_item(item) for item in payload["scoring_items"]
    )
    materials = list(payload["materials"])
    matches: list[EvidenceMatch] = []
    for target in targets:
        matches.append(
            _match_target(
                target,
                materials,
                as_of=payload["as_of"],
            )
        )

    counts = Counter(match.status for match in matches)
    total_score = sum(
        target.max_score or 0.0
        for target in targets
        if target.max_score is not None
    )
    covered_score = sum(
        (target.max_score or 0.0) * _coverage_factor(match.status)
        for target, match in zip(targets, matches)
        if target.max_score is not None
    )
    necessary_targets = [target for target in targets if _is_necessary(target)]
    necessary_unresolved = sum(
        1
        for target, match in zip(targets, matches)
        if _is_necessary(target) and match.status != "matched"
    )
    target_count = len(matches)
    effective_coverage = (
        sum(_coverage_factor(match.status) for match in matches) / target_count
        if target_count
        else 0.0
    )
    summary = {
        "target_count": target_count,
        "requirement_count": len(payload["requirements"]),
        "scoring_item_count": len(payload["scoring_items"]),
        "material_count": len(materials),
        "matched_count": counts.get("matched", 0),
        "partial_count": counts.get("partial", 0),
        "missing_count": counts.get("missing", 0),
        "invalid_count": counts.get("invalid", 0),
        "conflict_count": counts.get("conflict", 0),
        "human_review_count": counts.get("human_review", 0),
        "necessary_target_count": len(necessary_targets),
        "necessary_unresolved_count": necessary_unresolved,
        "coverage": round(effective_coverage, 4),
        "scored_coverage": (
            round(covered_score / total_score, 4) if total_score else None
        ),
    }
    return {
        "project_id": payload["project_id"],
        "matches": [match.to_dict() for match in matches],
        "summary": summary,
        "warnings": [],
    }


def _match_target(
    target: _Target,
    materials: list[EvidenceMaterial],
    *,
    as_of: date,
) -> EvidenceMatch:
    rule_ast = target.check_rule.get("rule_ast") or target.check_rule.get("ast")
    if isinstance(rule_ast, Mapping):
        evaluation = evaluate_rule_ast(rule_ast, materials, as_of=as_of)
        material = next(
            (
                item
                for item in materials
                if item.material_id in evaluation.material_ids
            ),
            None,
        )
        confidence = {
            "matched": 0.95,
            "partial": 0.55,
            "invalid": 0.85,
            "conflict": 0.85,
            "human_review": 0.5,
            "missing": 0.0,
        }.get(evaluation.status, 0.0)
        return _build_match(
            target,
            material=material,
            status=evaluation.status,
            confidence=confidence,
            reason=evaluation.reason,
            extra_references=list(evaluation.source_references),
        )
    target_terms = _target_terms(target)
    target_types = _target_type_hints(target)
    target_tags = _target_tags(target)
    if not target_terms and not target_types and not target_tags:
        return _build_match(
            target,
            material=None,
            status="missing",
            confidence=0.0,
            reason=(
                f"{_necessity_label(target)}未能提取可匹配的证据类型或关键词，"
                "无法确认材料覆盖情况。"
            ),
        )

    candidates = [
        _evaluate_candidate(
            target,
            material,
            as_of=as_of,
            target_terms=target_terms,
            target_types=target_types,
            target_tags=target_tags,
        )
        for material in materials
    ]
    contradictory_attributes = _contradictory_attribute_candidates(target, candidates)
    if contradictory_attributes:
        selected = _best_candidate(contradictory_attributes)
        assert selected is not None
        attribute = str(target.check_rule.get("attribute") or "attribute")
        return _build_match(
            target,
            material=selected.material,
            status="conflict",
            confidence=_confidence(selected, "conflict"),
            reason=(
                f"同一要求的属性 {attribute} 在多份有效材料中出现互相矛盾的值，"
                "不能合并认定为已覆盖。"
            ),
        )
    units = _required_evidence_units(target)
    if units:
        valid_coverage: dict[str, list[_Candidate]] = {}
        invalid_coverage: dict[str, list[_Candidate]] = {}
        for unit in units:
            valid_coverage[unit] = [
                candidate
                for candidate in candidates
                if candidate.validity == "valid"
                and _unit_matches(unit, candidate.material)
            ]
            invalid_coverage[unit] = [
                candidate
                for candidate in candidates
                if candidate.validity == "invalid"
                and _unit_matches(unit, candidate.material)
            ]

        covered_units = [unit for unit in units if valid_coverage[unit]]
        invalid_units = [unit for unit in units if invalid_coverage[unit]]
        ambiguous_units = [
            unit
            for unit in units
            if valid_coverage[unit] and invalid_coverage[unit]
        ]
        if ambiguous_units:
            relevant = [
                candidate
                for unit in ambiguous_units
                for candidate in [
                    *valid_coverage[unit],
                    *invalid_coverage[unit],
                ]
            ]
            selected = _best_candidate(relevant)
            assert selected is not None
            return _build_match(
                target,
                material=selected.material,
                status="conflict",
                confidence=_confidence(selected, "conflict"),
                reason=(
                    "同一证据要求同时存在有效和无效材料，不能合并认定为已覆盖："
                    f"{_join_terms(ambiguous_units)}。"
                ),
            )
        if len(covered_units) == len(units):
            relevant = [
                candidate
                for values in valid_coverage.values()
                for candidate in values
            ]
            selected = _best_candidate(relevant)
            assert selected is not None
            return _build_match(
                target,
                material=selected.material,
                status="matched",
                confidence=_confidence(selected, "matched"),
                reason=(
                    f"{_necessity_label(target)}证据要求已全部覆盖（"
                    f"{len(units)}/{len(units)}），材料通过有效性检查。"
                ),
            )
        if covered_units:
            relevant = [
                candidate
                for values in valid_coverage.values()
                for candidate in values
            ]
            selected = _best_candidate(relevant)
            assert selected is not None
            missing_units = [unit for unit in units if unit not in covered_units]
            return _build_match(
                target,
                material=selected.material,
                status="partial",
                confidence=_confidence(selected, "partial"),
                reason=(
                    f"材料仅覆盖 {len(covered_units)}/{len(units)} 项证据要求，"
                    f"仍缺少：{_join_terms(missing_units)}。"
                ),
            )
        if invalid_units:
            selected = _best_candidate(
                [candidate for unit in units for candidate in invalid_coverage[unit]]
            )
            assert selected is not None
            return _build_match(
                target,
                material=selected.material,
                status="invalid",
                confidence=_confidence(selected, "invalid"),
                reason=f"相关材料无法作为有效证据：{selected.validity_reason}",
            )
        return _build_match(
            target,
            material=None,
            status="missing",
            confidence=0.0,
            reason=(
                f"未找到与{_necessity_label(target)}证据要求匹配的材料："
                f"{_join_terms(units)}。"
            ),
        )

    best = _best_candidate(candidates)
    if best is None or best.relevance < _PARTIAL_THRESHOLD:
        return _build_match(
            target,
            material=None,
            status="missing",
            confidence=0.0,
            reason=f"未找到与{_necessity_label(target)}匹配的可用证明材料。",
        )
    relevant_candidates = [
        candidate
        for candidate in candidates
        if candidate.relevance >= _PARTIAL_THRESHOLD
    ]
    valid_candidates = [
        candidate
        for candidate in relevant_candidates
        if candidate.validity == "valid"
    ]
    invalid_candidates = [
        candidate
        for candidate in relevant_candidates
        if candidate.validity == "invalid"
    ]
    if valid_candidates and invalid_candidates:
        selected = _best_candidate([*valid_candidates, *invalid_candidates])
        assert selected is not None
        return _build_match(
            target,
            material=selected.material,
            status="conflict",
            confidence=_confidence(selected, "conflict"),
            reason="同一要求同时存在有效和无效材料，不能合并认定为已覆盖。",
        )
    if best.validity == "invalid":
        return _build_match(
            target,
            material=best.material,
            status="invalid",
            confidence=_confidence(best, "invalid"),
            reason=f"相关材料无法作为有效证据：{best.validity_reason}",
        )
    status = "matched" if best.relevance >= _STRONG_THRESHOLD else "partial"
    return _build_match(
        target,
        material=best.material,
        status=status,
        confidence=_confidence(best, status),
        reason=(
            f"材料已覆盖{_necessity_label(target)}的"
            f"{len(best.matched_terms)}/{len(target_terms) or 1}个关键词或标签。"
            if status == "partial"
            else f"材料的证据类型、关键词或语义标签与{_necessity_label(target)}匹配。"
        ),
    )


def _build_match(
    target: _Target,
    *,
    material: EvidenceMaterial | None,
    status: str,
    confidence: float,
    reason: str,
    extra_references: list[SourceReference] | None = None,
) -> EvidenceMatch:
    references = _merge_references(
        list(target.source_references),
        list(material.source_references) if material is not None else [],
        list(extra_references or []),
    )
    effective_status = status
    effective_confidence = confidence
    low_confidences = [
        reference.confidence
        for reference in references
        if reference.confidence is not None
        and reference.confidence < OCR_REVIEW_THRESHOLD
    ]
    if status == "matched" and low_confidences:
        source_confidence = min(low_confidences)
        effective_status = "human_review"
        effective_confidence = min(confidence, source_confidence)
        reason = (
            f"{reason} OCR来源置信度为 {source_confidence:.2f}，低于"
            f"人工复核阈值 {OCR_REVIEW_THRESHOLD:.2f}，不能直接认定为已覆盖。"
        )
    return EvidenceMatch(
        requirement_id=target.identifier,
        material_id=material.material_id if material is not None else None,
        status=effective_status,  # type: ignore[arg-type]
        confidence=round(max(0.0, min(effective_confidence, 1.0)), 4),
        reason=reason,
        source_references=references,
    )


def _evaluate_candidate(
    target: _Target,
    material: EvidenceMaterial,
    *,
    as_of: date,
    target_terms: list[str],
    target_types: set[str],
    target_tags: list[str],
) -> _Candidate:
    material_text = _material_text(material)
    material_types = _classify_types(material_text)
    if target_types:
        type_score = len(target_types & material_types) / len(target_types)
        if any(
            _phrase_matches(unit, material_text)
            for unit in _required_evidence_units(target)
        ):
            type_score = max(type_score, 0.9)
    else:
        type_score = 0.5

    matched_terms = tuple(
        term for term in target_terms if _phrase_matches(term, material_text)
    )
    keyword_score = (
        len(matched_terms) / len(target_terms) if target_terms else 0.5
    )
    material_tags = _material_tags(material)
    if target_tags:
        matched_tags = [
            tag
            for tag in target_tags
            if _phrase_matches(tag, material_text)
            or _semantic_type_overlap(tag, material_tags)
        ]
        tag_score = len(matched_tags) / len(target_tags)
    else:
        tag_score = 0.5
    relevance = 0.45 * type_score + 0.35 * keyword_score + 0.20 * tag_score
    validity, validity_reason = _material_validity(material, target, as_of)
    return _Candidate(
        material=material,
        type_score=type_score,
        keyword_score=keyword_score,
        tag_score=tag_score,
        relevance=round(relevance, 6),
        matched_terms=matched_terms,
        validity=validity,
        validity_reason=validity_reason,
    )


def _target_from_requirement(item: TenderRequirement) -> _Target:
    return _Target(
        identifier=item.requirement_id,
        title=item.title,
        description=item.description,
        kind="requirement",
        category=item.category,
        mandatory=item.mandatory,
        evidence_required=tuple(item.evidence_required),
        check_rule=dict(item.check_rule),
        max_score=item.max_score,
        source_references=tuple(item.source_references),
    )


def _target_from_scoring_item(item: ScoringItem) -> _Target:
    return _Target(
        identifier=item.item_id,
        title=item.title,
        description=item.criteria or item.title,
        kind="scoring_item",
        category="scoring",
        mandatory=item.max_score > 0,
        evidence_required=tuple(item.evidence_required),
        check_rule={},
        max_score=item.max_score,
        source_references=tuple(item.source_references),
    )


def _target_terms(target: _Target) -> list[str]:
    values = list(_required_evidence_units(target))
    values.extend(_rule_values(target.check_rule, _RULE_KEYWORDS))
    values.extend(_extract_domain_terms(target.title))
    values.extend(_extract_domain_terms(target.description))
    return _dedupe_terms(values)


def _target_tags(target: _Target) -> list[str]:
    return _dedupe_terms(_rule_values(target.check_rule, _RULE_KEYWORDS))


def _target_type_hints(target: _Target) -> set[str]:
    evidence_values = _required_evidence_units(target)
    sources = evidence_values or [target.title, target.description]
    result: set[str] = set()
    for value in sources:
        result.update(_classify_types(value))
    return result


def _required_evidence_units(target: _Target) -> list[str]:
    values = list(target.evidence_required)
    values.extend(_rule_values(target.check_rule, _RULE_EVIDENCE_TYPES))
    if values:
        return _dedupe_terms(values)
    type_hints = _target_type_hints_without_units(target)
    return [
        _EVIDENCE_TYPE_ALIASES[type_name][0]
        for type_name in sorted(type_hints)
    ]


def _target_type_hints_without_units(target: _Target) -> set[str]:
    result: set[str] = set()
    for value in (target.title, target.description):
        result.update(_classify_types(value))
    return result


def _unit_matches(unit: str, material: EvidenceMaterial) -> bool:
    if _is_specific_evidence_unit(unit):
        return _specific_unit_matches(unit, material)
    material_text = _material_text(material)
    if _phrase_matches(unit, material_text):
        return True
    unit_types = _classify_types(unit)
    if (
        unit_types
        and unit_types & _classify_types(material_text)
    ):
        return True
    return any(
        _phrase_matches(unit, tag) or _semantic_type_overlap(unit, [tag])
        for tag in _material_tags(material)
    )


def _is_specific_evidence_unit(value: str) -> bool:
    normalized = _compact(value)
    return "iso" in normalized or bool(re.search(r"\d", normalized))


def _specific_unit_matches(unit: str, material: EvidenceMaterial) -> bool:
    normalized_unit = _compact(unit)
    values = [
        material.material_type,
        material.title,
        material.content,
        *_string_values(material.metadata),
    ]
    return any(
        normalized_unit and normalized_unit in _compact(value)
        for value in values
    )


def _contradictory_attribute_candidates(
    target: _Target,
    candidates: list[_Candidate],
) -> list[_Candidate]:
    attribute = str(target.check_rule.get("attribute") or "").strip()
    if not attribute:
        return []
    units = _required_evidence_units(target)
    relevant = [
        candidate
        for candidate in candidates
        if candidate.validity == "valid"
        and candidate.relevance >= _PARTIAL_THRESHOLD
        and (
            not units
            or any(_unit_matches(unit, candidate.material) for unit in units)
        )
    ]
    values: list[tuple[_Candidate, Any]] = []
    for candidate in relevant:
        found, value = _material_attribute(candidate.material, attribute)
        if found:
            values.append((candidate, value))
    if len(values) < 2:
        return []
    normalized = {_comparison_key(value) for _, value in values}
    return [candidate for candidate, _ in values] if len(normalized) > 1 else []


def _material_attribute(
    material: EvidenceMaterial,
    attribute: str,
) -> tuple[bool, Any]:
    current: Any = material.metadata
    for segment in attribute.split("."):
        if not isinstance(current, Mapping) or segment not in current:
            return False, None
        current = current[segment]
    return True, current


def _comparison_key(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return "[" + ",".join(sorted(_comparison_key(item) for item in value)) + "]"
    return re.sub(r"[\s_\-:/\\.，。、“”‘’()（）【】\[\]{}]+", "", str(value).casefold())


def _material_text(material: EvidenceMaterial) -> str:
    metadata_text = " ".join(
        text
        for value in material.metadata.values()
        for text in _string_values(value)
    )
    return " ".join(
        item
        for item in (
            material.material_type,
            material.title,
            material.content,
            metadata_text,
        )
        if item
    )


def _material_tags(material: EvidenceMaterial) -> list[str]:
    values: list[str] = []
    for key, value in material.metadata.items():
        key_text = str(key).lower()
        if key_text in _RULE_KEYWORDS or "tag" in key_text:
            values.extend(_string_values(value))
    values.append(material.material_type)
    return _dedupe_terms(values)


def _material_validity(
    material: EvidenceMaterial,
    target: _Target,
    as_of: date,
) -> tuple[str, str]:
    metadata = material.metadata
    for key in ("valid", "is_valid", "active", "enabled"):
        if key in metadata and _is_false(metadata[key]):
            return "invalid", f"材料元数据 {key} 明确标记为无效"
    for key in ("verified", "is_verified"):
        if key in metadata and _is_false(metadata[key]):
            return "invalid", "材料尚未通过核验"

    status = str(
        metadata.get("status") or metadata.get("state") or ""
    ).strip().lower()
    if status in _INVALID_STATUS_VALUES:
        return "invalid", f"材料状态为 {status}"

    expiry_value = material.valid_until
    if expiry_value in (None, ""):
        for key in (
            "valid_until",
            "expires_at",
            "expiration_date",
            "expiry_date",
            "valid_to",
        ):
            if metadata.get(key) not in (None, ""):
                expiry_value = metadata[key]
                break
    require_expiry = any(
        _is_true(target.check_rule.get(key))
        for key in (
            "validity_required",
            "require_valid_until",
            "requires_validity",
        )
    )
    if expiry_value in (None, ""):
        if require_expiry:
            return "invalid", "材料缺少招标要求的有效期信息"
        return "valid", "材料未提供有效期，但当前规则未强制要求有效期"

    expiry = _parse_date_or_none(expiry_value)
    if expiry is None:
        return "invalid", "材料有效期格式无法解析"
    if expiry < as_of:
        return "invalid", f"材料已于 {expiry.isoformat()} 过期"

    valid_from_value = metadata.get("valid_from") or metadata.get("effective_date")
    if valid_from_value not in (None, ""):
        valid_from = _parse_date_or_none(valid_from_value)
        if valid_from is None:
            return "invalid", "材料生效日期格式无法解析"
        if valid_from > as_of:
            return "invalid", f"材料将于 {valid_from.isoformat()} 才生效"

    min_valid_days = target.check_rule.get(
        "min_valid_days", target.check_rule.get("minimum_valid_days")
    )
    if min_valid_days not in (None, ""):
        try:
            required_days = int(min_valid_days)
        except (TypeError, ValueError):
            return "invalid", "有效期规则 min_valid_days 不是整数"
        if (expiry - as_of).days < required_days:
            return "invalid", f"材料剩余有效期少于 {required_days} 天"
    return "valid", f"材料有效至 {expiry.isoformat()}"


def _best_candidate(candidates: list[_Candidate]) -> _Candidate | None:
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda candidate: (
            -candidate.relevance,
            0 if candidate.validity == "valid" else 1,
            candidate.material.material_id,
        ),
    )[0]


def _confidence(candidate: _Candidate, status: str) -> float:
    if status == "matched":
        return max(candidate.relevance, 0.75)
    if status == "partial":
        return max(candidate.relevance * 0.85, 0.3)
    if status == "invalid":
        return candidate.relevance
    if status == "conflict":
        return candidate.relevance
    return 0.0


def _coverage_factor(status: str) -> float:
    return {"matched": 1.0, "partial": 0.5}.get(status, 0.0)


def _is_necessary(target: _Target) -> bool:
    return (
        target.mandatory
        or bool(target.evidence_required)
        or (target.max_score or 0) > 0
    )


def _necessity_label(target: _Target) -> str:
    if target.mandatory:
        return "必需项"
    if target.kind == "scoring_item":
        return "评分项"
    return "要求项"


def _semantic_type_overlap(value: str, other_values: list[str]) -> bool:
    value_types = _classify_types(value)
    other_types = {
        type_name
        for other in other_values
        for type_name in _classify_types(other)
    }
    return bool(value_types.intersection(other_types))


def _classify_types(value: Any) -> set[str]:
    normalized = _compact(value)
    if not normalized:
        return set()
    result: set[str] = set()
    for type_name, aliases in _EVIDENCE_TYPE_ALIASES.items():
        if normalized == type_name or type_name in normalized:
            result.add(type_name)
            continue
        if any(_compact(alias) in normalized for alias in aliases):
            result.add(type_name)
    return result


def _extract_domain_terms(value: Any) -> list[str]:
    normalized = _compact(value)
    if not normalized:
        return []
    terms = [term for term in _DOMAIN_TERMS if _compact(term) in normalized]
    terms.extend(re.findall(r"[a-z0-9][a-z0-9._-]*", normalized))
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
        if run not in _STOP_TERMS and len(run) <= 12:
            terms.append(run)
    return _dedupe_terms(terms)


def _phrase_matches(term: Any, text: Any) -> bool:
    term_text = _compact(term)
    text_text = _compact(text)
    if not term_text or not text_text:
        return False
    if term_text in text_text or text_text in term_text:
        return True
    # ISO/IEC certificate numbers are distinct requirements.  Do not let the
    # shared generic token "iso" make ISO9001 match ISO27001.
    if _is_specific_evidence_unit(term_text) and _is_specific_evidence_unit(text_text):
        return False
    term_tokens = set(_extract_domain_terms(term_text))
    text_tokens = set(_extract_domain_terms(text_text))
    if term_tokens and term_tokens.intersection(text_tokens):
        return True
    if re.search(r"[\u4e00-\u9fff]", term_text):
        term_bigrams = {
            term_text[index : index + 2]
            for index in range(len(term_text) - 1)
        }
        text_bigrams = {
            text_text[index : index + 2]
            for index in range(len(text_text) - 1)
        }
        if term_bigrams and len(term_bigrams & text_bigrams) / len(term_bigrams) >= 0.6:
            return True
    return False


def _dedupe_terms(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _compact(value)
        if not normalized or normalized in _STOP_TERMS or normalized in seen:
            continue
        seen.add(normalized)
        result.append(str(value).strip())
    return result


def _join_terms(values: list[str]) -> str:
    return "、".join(value for value in values if value) or "必要证据"


def _merge_references(*groups: list[SourceReference]) -> list[SourceReference]:
    result: list[SourceReference] = []
    seen: set[tuple[Any, ...]] = set()
    for group in groups:
        for reference in group:
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


def _coerce_requirement(value: Any) -> TenderRequirement:
    if isinstance(value, TenderRequirement):
        return value
    if isinstance(value, Mapping):
        return TenderRequirement.from_mapping(value)
    raise ValueError("requirements items must be TenderRequirement objects or objects")


def _coerce_scoring_item(value: Any) -> ScoringItem:
    if isinstance(value, ScoringItem):
        return value
    if isinstance(value, Mapping):
        return ScoringItem.from_mapping(value)
    raise ValueError("scoring_items items must be ScoringItem objects or objects")


def _coerce_material(value: Any) -> EvidenceMaterial:
    if isinstance(value, EvidenceMaterial):
        return value
    if isinstance(value, Mapping):
        return EvidenceMaterial.from_mapping(value)
    raise ValueError("materials items must be EvidenceMaterial objects or objects")


def _as_sequence(value: Any, field_name: str) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, (Mapping, TenderRequirement, ScoringItem, EvidenceMaterial)):
        return [value]
    raise ValueError(f"{field_name} must be a list or a single object")


def _first_present(data: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _rule_values(rule: Mapping[str, Any], keys: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for key in keys:
        if key in rule:
            values.extend(_string_values(rule[key]))
    return values


def _string_values(value: Any) -> list[str]:
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, str):
        return [
            item.strip()
            for item in re.split(r"[,，;；、\n]+", value)
            if item.strip()
        ]
    if isinstance(value, Mapping):
        result: list[str] = []
        for item in value.values():
            result.extend(_string_values(item))
        return result
    if isinstance(value, (list, tuple, set)):
        result: list[str] = []
        for item in value:
            result.extend(_string_values(item))
        return result
    return [str(value).strip()] if str(value).strip() else []


def _parse_date(value: Any) -> date:
    parsed = _parse_date_or_none(value)
    if parsed is None:
        raise ValueError(f"invalid date value: {value}")
    return parsed


def _parse_date_or_none(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
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
    if re.fullmatch(r"\d{8}", text):
        try:
            return datetime.strptime(text, "%Y%m%d").date()
        except ValueError:
            return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        pass
    for format_name in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, format_name).date()
        except ValueError:
            continue
    return None


def _compact(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value).casefold())


def _is_false(value: Any) -> bool:
    if isinstance(value, bool):
        return not value
    return str(value).strip().lower() in _FALSE_VALUES


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUE_VALUES
