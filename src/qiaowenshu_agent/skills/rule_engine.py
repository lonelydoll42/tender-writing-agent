"""Small, auditable rule engine for evidence-backed tender conditions.

The semantic matcher is useful for finding candidate materials, but it is not
enough to prove compound requirements.  This module deliberately keeps the
rule language narrow and deterministic so the same result can be consumed by
evidence matching and bid feasibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Mapping, Sequence

from qiaowenshu_agent.domain.models import EvidenceMaterial, SourceReference


RuleStatus = str

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

_TYPE_ALIASES: dict[str, tuple[str, ...]] = {
    "business_license": ("营业执照", "business license"),
    "certification": ("认证证书", "体系认证", "certification"),
    "project_case": ("项目案例", "项目业绩", "类似项目", "案例"),
    "contract": ("合同", "项目合同", "contract"),
    "acceptance": ("验收报告", "验收证明", "验收证书", "acceptance"),
    "bid_bond": ("投标保证金", "保证金", "bid bond"),
}

_STATUS_PRIORITY = {
    "conflict": 5,
    "human_review": 4,
    "invalid": 3,
    "partial": 2,
    "missing": 1,
    "matched": 0,
}


@dataclass(frozen=True)
class RuleEvaluation:
    """Result of evaluating one rule AST against material evidence."""

    status: RuleStatus
    reason: str
    material_ids: tuple[str, ...] = ()
    source_references: tuple[SourceReference, ...] = ()
    details: Mapping[str, Any] | None = None


def evaluate_rule_ast(
    ast: Mapping[str, Any],
    materials: Sequence[EvidenceMaterial],
    *,
    as_of: date,
) -> RuleEvaluation:
    """Evaluate a supported evidence rule AST.

    Supported operators are ``all``, ``any``, ``not``, ``exists``, ``count``
    and ``bundle_count``.  ``count`` counts individual materials or distinct
    ``group_by`` values.  ``bundle_count`` counts groups that contain every
    requested evidence type, which is useful for contract plus acceptance
    evidence belonging to the same project case.
    """

    if not isinstance(ast, Mapping):
        raise ValueError("rule_ast must be an object")
    normalized_materials = list(materials)
    return _evaluate(ast, normalized_materials, as_of=as_of)


def _evaluate(
    ast: Mapping[str, Any],
    materials: list[EvidenceMaterial],
    *,
    as_of: date,
) -> RuleEvaluation:
    operator = str(
        ast.get("op") or ast.get("operator") or ast.get("type") or ""
    ).strip().lower()
    if operator in {"all", "and", "all_of"}:
        evaluations = _child_evaluations(ast, materials, as_of=as_of)
        if not evaluations:
            raise ValueError("all rule requires conditions")
        return _combine(evaluations, mode="all")
    if operator in {"any", "or", "any_of"}:
        evaluations = _child_evaluations(ast, materials, as_of=as_of)
        if not evaluations:
            raise ValueError("any rule requires conditions")
        return _combine(evaluations, mode="any")
    if operator == "not":
        child = ast.get("condition") or ast.get("child")
        if not isinstance(child, Mapping):
            raise ValueError("not rule requires one condition")
        evaluation = _evaluate(child, materials, as_of=as_of)
        if evaluation.status == "matched":
            return _with_status(evaluation, "invalid", "否定条件被满足")
        if evaluation.status in {"conflict", "human_review"}:
            return evaluation
        return _with_status(evaluation, "matched", "否定条件未被证据满足")
    if operator == "exists":
        return _evaluate_count(ast, materials, as_of=as_of, default_minimum=1)
    if operator == "count":
        return _evaluate_count(ast, materials, as_of=as_of, default_minimum=1)
    if operator in {"bundle_count", "bundle"}:
        return _evaluate_bundle_count(ast, materials, as_of=as_of)
    raise ValueError(f"unsupported rule_ast operator: {operator or '<empty>'}")


def _child_evaluations(
    ast: Mapping[str, Any],
    materials: list[EvidenceMaterial],
    *,
    as_of: date,
) -> list[RuleEvaluation]:
    raw_conditions = ast.get("conditions") or ast.get("children")
    if not isinstance(raw_conditions, (list, tuple)):
        raise ValueError("rule conditions must be a list")
    result: list[RuleEvaluation] = []
    for condition in raw_conditions:
        if not isinstance(condition, Mapping):
            raise ValueError("rule conditions must contain objects")
        result.append(_evaluate(condition, materials, as_of=as_of))
    return result


def _combine(evaluations: Sequence[RuleEvaluation], *, mode: str) -> RuleEvaluation:
    material_ids = _unique_strings(
        item for evaluation in evaluations for item in evaluation.material_ids
    )
    references = _merge_references(
        reference
        for evaluation in evaluations
        for reference in evaluation.source_references
    )
    if mode == "any" and any(item.status == "matched" for item in evaluations):
        return RuleEvaluation(
            "matched",
            "至少一个组合条件被证据满足",
            tuple(material_ids),
            tuple(references),
            {"children": [item.details for item in evaluations]},
        )
    if mode == "all" and all(item.status == "matched" for item in evaluations):
        return RuleEvaluation(
            "matched",
            "全部组合条件均被证据满足",
            tuple(material_ids),
            tuple(references),
            {"children": [item.details for item in evaluations]},
        )

    selected = sorted(
        evaluations,
        key=lambda item: _STATUS_PRIORITY.get(item.status, 0),
        reverse=True,
    )
    chosen = selected[0]
    if mode == "any":
        if all(item.status in {"invalid", "missing"} for item in evaluations):
            status = (
                "invalid"
                if any(item.status == "invalid" for item in evaluations)
                else "missing"
            )
        else:
            status = chosen.status
    else:
        status = chosen.status
    return RuleEvaluation(
        status,
        f"组合条件未完全满足：{chosen.reason}",
        tuple(material_ids),
        tuple(references),
        {"children": [item.details for item in evaluations]},
    )


def _evaluate_count(
    ast: Mapping[str, Any],
    materials: list[EvidenceMaterial],
    *,
    as_of: date,
    default_minimum: int,
) -> RuleEvaluation:
    selection = _select_materials(ast, materials, as_of=as_of)
    raw = selection["raw"]
    valid = selection["valid"]
    invalid = selection["invalid"]
    qualified = selection["qualified"]
    references = _merge_references(
        material.source_references
        for material in raw
    )
    material_ids = _unique_strings(material.material_id for material in raw)
    if valid and invalid:
        return RuleEvaluation(
            "conflict",
            "同一证据类型同时存在有效和无效材料，且规则未声明版本优先级",
            tuple(material_ids),
            tuple(references),
            {"candidate_count": len(raw), "qualified_count": len(qualified)},
        )
    if not raw:
        return RuleEvaluation(
            "missing",
            "未找到规则要求的证据材料",
            (),
            (),
            {"candidate_count": 0, "qualified_count": 0},
        )

    count = _distinct_count(qualified, ast.get("group_by"))
    minimum = _integer(ast.get("minimum", ast.get("min", default_minimum)))
    maximum_value = ast.get("maximum", ast.get("max"))
    maximum = _integer(maximum_value) if maximum_value is not None else None
    within_maximum = maximum is None or count <= maximum
    if count >= minimum and within_maximum:
        status = "matched"
        reason = f"规则要求至少 {minimum} 个，当前有 {count} 个符合条件"
    elif count > 0:
        status = "partial"
        reason = f"规则要求至少 {minimum} 个，当前仅有 {count} 个符合条件"
    else:
        status = "invalid" if invalid or valid else "missing"
        reason = "存在证据材料，但没有材料满足组合条件"
    if maximum is not None and count > maximum:
        status = "invalid"
        reason = f"规则要求最多 {maximum} 个，当前有 {count} 个符合条件"
    return RuleEvaluation(
        status,
        reason,
        tuple(material_ids),
        tuple(references),
        {
            "candidate_count": len(raw),
            "qualified_count": count,
            "minimum": minimum,
            "maximum": maximum,
        },
    )


def _evaluate_bundle_count(
    ast: Mapping[str, Any],
    materials: list[EvidenceMaterial],
    *,
    as_of: date,
) -> RuleEvaluation:
    required_types = _string_list(
        ast.get("evidence_types")
        or ast.get("material_types")
        or ast.get("required_evidence_types")
    )
    if not required_types:
        raise ValueError("bundle_count requires evidence_types")
    group_by = str(ast.get("group_by") or "case_id")
    raw = [
        material
        for material in materials
        if any(
            _material_matches_type(material, required)
            for required in required_types
        )
    ]
    if not raw:
        return RuleEvaluation(
            "missing",
            "未找到组成证据包的材料",
            (),
            (),
            {"bundle_count": 0, "required_types": required_types},
        )
    groups: dict[str, list[EvidenceMaterial]] = {}
    for material in raw:
        key = _group_value(material, group_by)
        groups.setdefault(key, []).append(material)

    qualified_groups: list[list[EvidenceMaterial]] = []
    conflict_groups: list[list[EvidenceMaterial]] = []
    partial_groups: list[list[EvidenceMaterial]] = []
    for group in groups.values():
        valid = [material for material in group if _material_is_valid(material, as_of)]
        invalid = [material for material in group if material not in valid]
        if valid and invalid:
            conflict_groups.append(group)
            continue
        if not valid:
            partial_groups.append(group)
            continue
        has_all_types = all(
            any(_material_matches_type(material, required) for material in valid)
            for required in required_types
        )
        where = ast.get("where")
        where_matches = (
            not where
            or any(_where_matches(material, where, as_of=as_of) for material in valid)
        )
        if has_all_types and where_matches:
            qualified_groups.append(valid)
        else:
            partial_groups.append(valid)

    references = _merge_references(
        material.source_references
        for material in raw
    )
    material_ids = _unique_strings(material.material_id for material in raw)
    if conflict_groups:
        return RuleEvaluation(
            "conflict",
            "同一案例的证据包同时存在有效和无效版本，无法确定采用哪一版本",
            tuple(material_ids),
            tuple(references),
            {
                "bundle_count": len(qualified_groups),
                "conflict_group_count": len(conflict_groups),
            },
        )
    minimum = _integer(ast.get("minimum", ast.get("min", 1)))
    maximum_value = ast.get("maximum", ast.get("max"))
    maximum = _integer(maximum_value) if maximum_value is not None else None
    count = len(qualified_groups)
    if count >= minimum and (maximum is None or count <= maximum):
        status = "matched"
        reason = f"规则要求至少 {minimum} 个完整证据包，当前有 {count} 个"
    elif count > 0:
        status = "partial"
        reason = f"规则要求至少 {minimum} 个完整证据包，当前有 {count} 个"
    elif partial_groups:
        status = "partial"
        reason = "存在相关案例材料，但合同、验收或其他组合条件未闭合"
    else:
        status = "invalid"
        reason = "存在相关材料，但没有完整证据包满足组合条件"
    if maximum is not None and count > maximum:
        status = "invalid"
        reason = f"规则要求最多 {maximum} 个完整证据包，当前有 {count} 个"
    return RuleEvaluation(
        status,
        reason,
        tuple(material_ids),
        tuple(references),
        {
            "bundle_count": count,
            "partial_group_count": len(partial_groups),
            "minimum": minimum,
            "maximum": maximum,
            "required_types": required_types,
        },
    )


def _select_materials(
    ast: Mapping[str, Any],
    materials: list[EvidenceMaterial],
    *,
    as_of: date,
) -> dict[str, list[EvidenceMaterial]]:
    required_types = _string_list(
        ast.get("evidence_types")
        or ast.get("material_types")
        or ast.get("evidence_type")
    )
    if not required_types:
        raise ValueError("count or exists rule requires evidence_types")
    raw = [
        material
        for material in materials
        if any(
            _material_matches_type(material, required)
            for required in required_types
        )
    ]
    valid = [material for material in raw if _material_is_valid(material, as_of)]
    invalid = [material for material in raw if material not in valid]
    where = ast.get("where")
    qualified = [
        material
        for material in valid
        if not where or _where_matches(material, where, as_of=as_of)
    ]
    return {"raw": raw, "valid": valid, "invalid": invalid, "qualified": qualified}


def _where_matches(
    material: EvidenceMaterial,
    where: Any,
    *,
    as_of: date,
) -> bool:
    if not isinstance(where, Mapping):
        raise ValueError("rule where must be an object")
    for raw_key, expected in where.items():
        key = str(raw_key)
        actual = _material_value(material, key)
        if actual is _MISSING or not _condition_matches(actual, expected, as_of=as_of):
            return False
    return True


def _condition_matches(actual: Any, expected: Any, *, as_of: date) -> bool:
    if not isinstance(expected, Mapping):
        return _equal(actual, expected)
    if "equals" in expected or "expected" in expected:
        value = expected.get("equals", expected.get("expected"))
        if not _equal(actual, value):
            return False
    if "one_of" in expected or "in" in expected:
        values = expected.get("one_of", expected.get("in"))
        if not isinstance(values, (list, tuple, set)):
            values = [values]
        if not any(_equal(actual, item) for item in values):
            return False
    if "minimum" in expected or "min" in expected:
        minimum = _decimal(expected.get("minimum", expected.get("min")))
        actual_number = _decimal(actual)
        if minimum is None or actual_number is None or actual_number < minimum:
            return False
    if "maximum" in expected or "max" in expected:
        maximum = _decimal(expected.get("maximum", expected.get("max")))
        actual_number = _decimal(actual)
        if maximum is None or actual_number is None or actual_number > maximum:
            return False
    if "within_years" in expected or "max_age_years" in expected:
        years = _decimal(expected.get("within_years", expected.get("max_age_years")))
        if years is None or not _within_days(actual, as_of, int(years * 365)):
            return False
    if "within_days" in expected or "max_age_days" in expected:
        days = _integer(expected.get("within_days", expected.get("max_age_days")))
        if not _within_days(actual, as_of, days):
            return False
    if "before" in expected and not _date_compare(actual, expected["before"], "before"):
        return False
    if "after" in expected and not _date_compare(actual, expected["after"], "after"):
        return False
    return True


def _within_days(value: Any, as_of: date, days: int) -> bool:
    parsed = _parse_date(value)
    return parsed is not None and as_of - timedelta(days=days) <= parsed <= as_of


def _date_compare(value: Any, boundary: Any, operator: str) -> bool:
    actual = _parse_date(value)
    expected = _parse_date(boundary)
    if actual is None or expected is None:
        return False
    return actual < expected if operator == "before" else actual > expected


def _material_is_valid(material: EvidenceMaterial, as_of: date) -> bool:
    metadata = material.metadata
    for key in ("valid", "is_valid", "active", "enabled"):
        if key in metadata and _is_false(metadata[key]):
            return False
    status = _compact(metadata.get("status") or metadata.get("state"))
    if status in {_compact(item) for item in _INVALID_STATUS_VALUES}:
        return False
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
    if expiry_value not in (None, ""):
        expiry = _parse_date(expiry_value)
        if expiry is None or expiry < as_of:
            return False
    valid_from = metadata.get("valid_from") or metadata.get("effective_date")
    if valid_from not in (None, ""):
        parsed = _parse_date(valid_from)
        if parsed is None or parsed > as_of:
            return False
    return True


def _material_matches_type(material: EvidenceMaterial, required: Any) -> bool:
    target = _compact(required)
    if not target:
        return False
    values = [material.material_type, material.title, material.content]
    values.extend(_scalar_values(material.metadata))
    text = _compact(" ".join(str(value) for value in values))
    if "iso" in target or any(character.isdigit() for character in target):
        return target in text
    aliases = _TYPE_ALIASES.get(target, ())
    if target in text:
        return True
    return any(_compact(alias) in text for alias in aliases)


def _material_value(material: EvidenceMaterial, key: str) -> Any:
    if key in {"material_id", "id"}:
        return material.material_id
    if key in {"material_type", "type"}:
        return material.material_type
    if key == "valid_until":
        return material.valid_until
    current: Any = material.metadata
    if key.startswith("metadata."):
        key = key.removeprefix("metadata.")
    if key.startswith("material."):
        key = key.removeprefix("material.")
    for segment in key.split("."):
        if not isinstance(current, Mapping) or segment not in current:
            return _MISSING
        current = current[segment]
    return current


def _group_value(material: EvidenceMaterial, group_by: str) -> str:
    value = _material_value(material, group_by)
    if value is _MISSING or value in (None, ""):
        return material.material_id
    return str(value)


def _distinct_count(materials: Sequence[EvidenceMaterial], group_by: Any) -> int:
    if not group_by:
        return len(materials)
    return len({_group_value(material, str(group_by)) for material in materials})


def _is_false(value: Any) -> bool:
    if isinstance(value, bool):
        return not value
    return _compact(value) in {"false", "0", "no", "否", "无", "失效", "过期"}


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    chinese = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日?", text)
    if chinese:
        text = f"{chinese.group(1)}-{chinese.group(2)}-{chinese.group(3)}"
    if re.fullmatch(r"\d{8}", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("，", ""))
    except (InvalidOperation, ValueError):
        return None


def _integer(value: Any) -> int:
    number = _decimal(value)
    if number is None or number != number.to_integral_value():
        raise ValueError(f"rule count must be an integer: {value}")
    return int(number)


def _equal(left: Any, right: Any) -> bool:
    left_number = _decimal(left)
    right_number = _decimal(right)
    if left_number is not None and right_number is not None:
        return left_number == right_number
    return _compact(left) == _compact(right)


def _scalar_values(value: Any) -> list[Any]:
    if isinstance(value, Mapping):
        result: list[Any] = []
        for nested in value.values():
            result.extend(_scalar_values(nested))
        return result
    if isinstance(value, (list, tuple, set)):
        result = []
        for nested in value:
            result.extend(_scalar_values(nested))
        return result
    return [value]


def _with_status(
    evaluation: RuleEvaluation,
    status: str,
    reason: str,
) -> RuleEvaluation:
    return RuleEvaluation(
        status,
        reason,
        evaluation.material_ids,
        evaluation.source_references,
        evaluation.details,
    )


def _unique_strings(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [
            item.strip()
            for item in re.split(r"[,，;；、\n]+", value)
            if item.strip()
        ]
    if not isinstance(value, (list, tuple, set)):
        raise ValueError("evidence_types must be a string or list")
    return [str(item).strip() for item in value if str(item).strip()]


def _merge_references(values: Any) -> list[SourceReference]:
    result: list[SourceReference] = []
    seen: set[tuple[Any, ...]] = set()
    for reference in values:
        if not isinstance(reference, SourceReference):
            continue
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


def _compact(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value).casefold())


_MISSING = object()
