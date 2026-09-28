"""Deterministic quotation and price-rule validation."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import (
    Skill,
    SkillManifest,
    SkillRequest,
    SkillResult,
)


MANIFEST = SkillManifest(
    name="quotation-check",
    version="0.1.0",
    description="Validate quotation arithmetic and price rules deterministically.",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "total_price": {"type": ["number", "string", "null"]},
            "line_items": {"type": "array"},
            "quoted_totals": {"type": "array"},
            "price_ceiling": {"type": ["number", "string", "null"]},
            "uppercase_amount": {"type": ["string", "null"]},
            "price_score": {"type": "object"},
        },
    },
    output_schema={
        "type": "object",
        "required": ["checks", "summary"],
    },
    capabilities=("tender.quotation_validation", "tender.price_formula"),
    required_permissions=("document.read",),
)


class QuotationCheckSkill(Skill):
    manifest = MANIFEST

    async def execute(
        self,
        request: SkillRequest,
        _context: SkillContext,
    ) -> SkillResult:
        try:
            data = _check(request.input)
        except (TypeError, ValueError) as exc:
            return SkillResult.failure(
                message=str(exc),
                error_code="INVALID_QUOTATION_CHECK_INPUT",
            )
        failed = data["summary"]["failed_count"]
        unknown = data["summary"]["unknown_count"]
        warnings = []
        if failed:
            warnings.append(f"发现 {failed} 个报价校验失败")
        if unknown:
            warnings.append(f"有 {unknown} 个报价规则缺少输入，需人工核验")
        if failed:
            return SkillResult.partial(
                data,
                message="quotation check found failures",
                warnings=warnings,
            )
        if unknown:
            return SkillResult.partial(
                data,
                message="quotation check is incomplete",
                warnings=warnings,
            )
        return SkillResult.success(data, message="quotation check passed")


def _check(data: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise TypeError("quotation check input must be an object")
    checks: list[dict[str, Any]] = []
    total = _decimal(data.get("total_price"))
    line_items = data.get("line_items")
    if line_items is not None:
        if not isinstance(line_items, (list, tuple)):
            raise ValueError("line_items must be a list")
        line_total = Decimal("0")
        line_values_known = True
        for index, raw in enumerate(line_items, start=1):
            if not isinstance(raw, Mapping):
                raise ValueError("line_items items must be objects")
            quantity = _decimal(raw.get("quantity"))
            unit_price = _decimal(raw.get("unit_price"))
            subtotal = _decimal(raw.get("subtotal"))
            if subtotal is None and quantity is not None and unit_price is not None:
                subtotal = _money(quantity * unit_price)
            if subtotal is None:
                line_values_known = False
                continue
            line_total += subtotal
            if quantity is not None and unit_price is not None:
                expected = _money(quantity * unit_price)
                checks.append(
                    _check_row(
                        f"LINE-{index:03d}",
                        "quantity_times_unit_price",
                        expected,
                        subtotal,
                        "分项数量乘单价应等于分项小计",
                    )
                )
        if total is not None and line_values_known:
            checks.append(
                _check_row(
                    "QUOTE-001",
                    "line_items_sum",
                    _money(line_total),
                    total,
                    "分项报价合计应等于投标总价",
                )
            )
        elif total is not None:
            checks.append(
                _unknown_row("QUOTE-001", "line_items_sum", "存在缺少金额的分项报价")
            )

    quoted_totals = data.get("quoted_totals")
    if quoted_totals is not None:
        if not isinstance(quoted_totals, (list, tuple)):
            raise ValueError("quoted_totals must be a list")
        values: list[tuple[str, Decimal]] = []
        for item in quoted_totals:
            if not isinstance(item, Mapping):
                raise ValueError("quoted_totals items must be objects")
            value = _decimal(item.get("value", item.get("total_price")))
            if value is not None:
                values.append(
                    (
                        str(item.get("document_id") or item.get("name") or "document"),
                        value,
                    )
                )
        if total is not None:
            for document_id, value in values:
                checks.append(
                    _check_row(
                        f"QUOTE-{len(checks) + 1:03d}",
                        "document_total_matches",
                        total,
                        value,
                        f"{document_id}应与投标总价一致",
                    )
                )
        elif values:
            baseline = values[0][1]
            for document_id, value in values[1:]:
                checks.append(
                    _check_row(
                        f"QUOTE-{len(checks) + 1:03d}",
                        "document_totals_match",
                        baseline,
                        value,
                        f"{document_id}应与报价基准一致",
                    )
                )

    ceiling = _decimal(data.get("price_ceiling", data.get("max_price")))
    if ceiling is not None and total is not None:
        checks.append(
            _check_row(
                "QUOTE-CEILING",
                "price_ceiling",
                f"<= {ceiling}",
                total,
                "投标总价不得超过最高限价",
                passed=total <= ceiling,
            )
        )
    elif ceiling is not None:
        checks.append(_unknown_row("QUOTE-CEILING", "price_ceiling", "缺少投标总价"))

    uppercase = data.get("uppercase_amount", data.get("amount_uppercase"))
    if uppercase not in (None, "") and total is not None:
        parsed_upper = parse_chinese_amount(str(uppercase))
        checks.append(
            _check_row(
                "QUOTE-UPPER",
                "uppercase_amount_matches",
                total,
                parsed_upper,
                "大写金额应与小写金额一致",
                passed=parsed_upper is not None and parsed_upper == total,
            )
            if parsed_upper is not None
            else _unknown_row(
                "QUOTE-UPPER", "uppercase_amount_matches", "无法解析大写金额"
            )
        )
    elif uppercase not in (None, ""):
        checks.append(
            _unknown_row("QUOTE-UPPER", "uppercase_amount_matches", "缺少小写总价")
        )

    price_score = data.get("price_score")
    if price_score is not None:
        checks.append(_price_score_row(price_score, total))

    counts = {"passed": 0, "failed": 0, "unknown": 0}
    for check in checks:
        counts[check["status"]] = counts.get(check["status"], 0) + 1
    return {
        "project_id": str(data.get("project_id") or "").strip(),
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_count": counts["passed"],
            "failed_count": counts["failed"],
            "unknown_count": counts["unknown"],
            "passed": counts["failed"] == 0 and counts["unknown"] == 0,
        },
    }


def _check_row(
    check_id: str,
    check_type: str,
    expected: Any,
    actual: Any,
    reason: str,
    *,
    passed: bool | None = None,
) -> dict[str, Any]:
    if passed is None:
        passed = _equal_amount(expected, actual)
    return {
        "check_id": check_id,
        "check_type": check_type,
        "status": "passed" if passed else "failed",
        "expected": _serialize(expected),
        "actual": _serialize(actual),
        "reason": reason,
        "severity": "blocker" if not passed else "none",
    }


def _unknown_row(check_id: str, check_type: str, reason: str) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "check_type": check_type,
        "status": "unknown",
        "expected": None,
        "actual": None,
        "reason": reason,
        "severity": "high_risk",
    }


def _price_score_row(raw: Any, total: Decimal | None) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return _unknown_row("PRICE-SCORE", "price_score", "price_score必须是对象")
    lowest = _decimal(raw.get("lowest_price"))
    quote = total or _decimal(raw.get("quote_price"))
    max_score = _decimal(raw.get("max_score"))
    if lowest is None or quote is None or max_score is None or quote <= 0:
        return _unknown_row("PRICE-SCORE", "price_score", "缺少最低价、报价或最高分")
    formula = str(raw.get("formula") or "lowest_price / quote_price")
    score = _money(max_score * lowest / quote)
    return {
        "check_id": "PRICE-SCORE",
        "check_type": "price_score",
        "status": "passed",
        "expected": formula,
        "actual": float(score),
        "reason": "按最低价/投标报价计算价格分，结果仅为理论价格分",
        "severity": "none",
    }


def _decimal(value: Any) -> Decimal | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return Decimal(
            str(value).replace(",", "").replace("¥", "").replace("￥", "").strip()
        )
    except (InvalidOperation, ValueError):
        return None


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _equal_amount(first: Any, second: Any) -> bool:
    left = _decimal(first)
    right = _decimal(second)
    if left is not None and right is not None:
        return _money(left) == _money(right)
    return str(first) == str(second)


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def parse_chinese_amount(value: str) -> Decimal | None:
    """Parse common RMB uppercase strings such as ``人民币壹佰元整``."""

    text = re.sub(r"\s+", "", value).replace("人民币", "")
    if not text:
        return None
    digits = {
        "零": 0,
        "〇": 0,
        "壹": 1,
        "一": 1,
        "贰": 2,
        "貳": 2,
        "二": 2,
        "叁": 3,
        "三": 3,
        "肆": 4,
        "四": 4,
        "伍": 5,
        "五": 5,
        "陆": 6,
        "陸": 6,
        "六": 6,
        "柒": 7,
        "七": 7,
        "捌": 8,
        "八": 8,
        "玖": 9,
        "九": 9,
    }
    small_units = {"拾": 10, "十": 10, "佰": 100, "百": 100, "仟": 1000, "千": 1000}
    large_units = {"万": 10_000, "萬": 10_000, "亿": 100_000_000, "億": 100_000_000}
    integer_text = re.split(r"元|圆|圓", text, maxsplit=1)[0]
    integer_text = integer_text.replace("整", "")
    if not integer_text:
        return None
    total = 0
    section = 0
    number = 0
    for char in integer_text:
        if char in digits:
            number = digits[char]
        elif char in small_units:
            unit = small_units[char]
            section += (number or 1) * unit
            number = 0
        elif char in large_units:
            section += number
            total += section * large_units[char]
            section = 0
            number = 0
        else:
            return None
    return Decimal(total + section + number)
