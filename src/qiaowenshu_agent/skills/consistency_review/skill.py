"""Rule-first cross-document fact extraction and conflict detection."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Mapping

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import (
    Skill,
    SkillManifest,
    SkillRequest,
    SkillResult,
)


MANIFEST = SkillManifest(
    name="consistency-review",
    version="0.1.0",
    description="Extract canonical facts and detect cross-document conflicts.",
    input_schema={
        "type": "object",
        "required": ["documents"],
        "properties": {
            "project_id": {"type": "string"},
            "documents": {"type": "array"},
            "facts": {"type": "object"},
            "canonical_facts": {"type": "object"},
        },
    },
    output_schema={
        "type": "object",
        "required": ["canonical_facts", "conflicts", "summary"],
    },
    capabilities=("tender.consistency", "tender.canonical_facts"),
    required_permissions=("document.read",),
)


_FIELD_RULES: tuple[tuple[str, str, str], ...] = (
    (
        "project_name",
        "项目名称",
        r"(?:项目名称|采购项目名称|项目名)\s*[:：]?\s*([^\n\r，,；;。]{2,120})",
    ),
    (
        "project_number",
        "项目编号",
        r"(?:项目编号|招标编号|采购编号)\s*[:：]?\s*([^\n\r\s，,；;。]{3,100})",
    ),
    (
        "bidder_name",
        "投标人名称",
        r"(?:投标人名称|供应商名称|投标人)\s*[:：]?\s*([^\n\r，,；;。]{2,120})",
    ),
    (
        "project_manager",
        "项目经理",
        r"(?:项目经理|项目负责人|项目管理负责人)\s*[:：]?\s*([\u4e00-\u9fff]{2,8})",
    ),
    (
        "project_duration",
        "项目工期",
        r"(?:项目工期|工期|建设周期|交付期|服务期限)\s*[:：]?[^\d]{0,20}([0-9]+(?:\.[0-9]+)?\s*(?:日历天|天|个月|月|年))",
    ),
    (
        "delivery_date",
        "交付日期",
        r"(?:交付日期|交货日期|完成日期|交付时间)\s*[:：]?[^\d]{0,20}((?:20\d{2})[-/.年]\s*[0-9]{1,2}[-/.月]\s*[0-9]{1,2}日?)",
    ),
    (
        "warranty_period",
        "质保期",
        r"(?:质保期|保修期|免费维护期)\s*[:：]?[^\d]{0,20}([0-9]+(?:\.[0-9]+)?\s*(?:年|个月|月|天))",
    ),
    (
        "bid_price",
        "投标总价",
        r"(?:投标总价|投标报价|含税总价|总报价)\s*[:：]?[^0-9]{0,20}(?:人民币|¥|￥)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
    ),
    (
        "tax_rate",
        "税率",
        r"税率\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?\s*%)",
    ),
)


class ConsistencyReviewSkill(Skill):
    manifest = MANIFEST

    async def execute(
        self,
        request: SkillRequest,
        _context: SkillContext,
    ) -> SkillResult:
        try:
            data = _review(request.input)
        except (TypeError, ValueError) as exc:
            return SkillResult.failure(
                message=str(exc),
                error_code="INVALID_CONSISTENCY_REVIEW_INPUT",
            )
        warnings = [
            f"发现 {data['summary']['conflict_count']} 个跨文档冲突"
            if data["summary"]["conflict_count"]
            else ""
        ]
        warnings = [item for item in warnings if item]
        return SkillResult.success(
            data,
            message=(
                "consistency review completed with conflicts"
                if warnings
                else "consistency review completed"
            ),
            warnings=warnings,
        )


def _review(data: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise TypeError("consistency review input must be an object")
    documents = _documents(data.get("documents"))
    if not documents:
        raise ValueError("documents is required and cannot be empty")
    occurrences: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for document in documents:
        for field, _label, pattern in _FIELD_RULES:
            for match in re.finditer(pattern, document["text"], flags=re.I):
                value = _normalize_value(field, match.group(1))
                if value:
                    occurrences[field].append(
                        {
                            "field": field,
                            "value": value,
                            "document_id": document["document_id"],
                            "file_name": document.get("file_name", ""),
                            "page": document.get("page"),
                            "quote": _quote(
                                document["text"], match.start(), match.end()
                            ),
                            "source_references": list(
                                document.get("source_references") or []
                            ),
                        }
                    )
    _add_explicit_facts(occurrences, data.get("canonical_facts") or data.get("facts"))

    canonical: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []
    for field, label, _pattern in _FIELD_RULES:
        values = occurrences.get(field, [])
        if not values:
            continue
        distinct: list[str] = []
        for item in values:
            if item["value"] not in distinct:
                distinct.append(item["value"])
        canonical[field] = {
            "label": label,
            "value": distinct[0],
            "occurrences": values,
        }
        if len(distinct) > 1:
            conflicts.append(
                {
                    "conflict_id": f"CONSISTENCY-{len(conflicts) + 1:03d}",
                    "field": field,
                    "label": label,
                    "baseline_value": distinct[0],
                    "conflicting_values": distinct[1:],
                    "occurrences": values,
                    "severity": "high"
                    if field
                    in {
                        "project_name",
                        "project_number",
                        "bid_price",
                        "project_duration",
                    }
                    else "medium",
                }
            )
    high_risk = sum(1 for item in conflicts if item["severity"] == "high")
    return {
        "project_id": str(data.get("project_id") or "").strip(),
        "canonical_facts": canonical,
        "conflicts": conflicts,
        "summary": {
            "documents_checked": len(documents),
            "fields_found": len(canonical),
            "conflict_count": len(conflicts),
            "high_risk_count": high_risk,
            "consistent": not conflicts,
        },
    }


def _documents(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("documents must be a list")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ValueError("documents items must be objects")
        document_id = str(
            item.get("document_id") or item.get("file_id") or f"document-{index + 1}"
        ).strip()
        pages = item.get("pages")
        if isinstance(pages, (list, tuple)) and pages:
            for page_index, page in enumerate(pages, start=1):
                if isinstance(page, Mapping):
                    text = str(page.get("text") or page.get("content") or "")
                    page_number = page.get("page_number", page_index)
                else:
                    text = str(page)
                    page_number = page_index
                result.append(
                    {
                        "document_id": document_id,
                        "file_name": str(
                            item.get("file_name") or item.get("name") or ""
                        ),
                        "page": page_number,
                        "text": text,
                        "source_references": list(item.get("source_references") or []),
                    }
                )
            continue
        text = str(item.get("text") or item.get("content") or "")
        if text:
            result.append(
                {
                    "document_id": document_id,
                    "file_name": str(item.get("file_name") or item.get("name") or ""),
                    "page": item.get("page"),
                    "text": text,
                    "source_references": list(item.get("source_references") or []),
                }
            )
    return result


def _add_explicit_facts(
    occurrences: dict[str, list[dict[str, Any]]],
    facts: Any,
) -> None:
    if not facts:
        return
    if not isinstance(facts, Mapping):
        raise ValueError("canonical_facts must be an object")
    for field, raw in facts.items():
        if isinstance(raw, Mapping):
            value = raw.get("value")
            source = raw
        elif isinstance(raw, (list, tuple)):
            for item in raw:
                _add_explicit_fact(occurrences, str(field), item)
            continue
        else:
            value = raw
            source = {}
        _add_explicit_fact(occurrences, str(field), {"value": value, **source})


def _add_explicit_fact(
    occurrences: dict[str, list[dict[str, Any]]],
    field: str,
    raw: Any,
) -> None:
    if isinstance(raw, Mapping):
        value = raw.get("value")
        document_id = raw.get("document_id") or raw.get("file_id") or "explicit"
        page = raw.get("page")
        quote = raw.get("quote") or str(value or "")
    else:
        value = raw
        document_id = "explicit"
        page = None
        quote = str(value or "")
    normalized = _normalize_value(field, value)
    if normalized:
        occurrences[field].append(
            {
                "field": field,
                "value": normalized,
                "document_id": str(document_id),
                "file_name": "",
                "page": page,
                "quote": str(quote),
            }
        )


def _normalize_value(field: str, value: Any) -> str:
    text = str(value).strip() if value is not None else ""
    text = re.sub(r"\s+", "", text)
    if field == "bid_price":
        text = text.replace(",", "").replace("¥", "").replace("￥", "")
    if field == "tax_rate":
        text = text.replace("％", "%")
    if field in {"delivery_date"}:
        text = text.replace("年", "-").replace("月", "-").replace("日", "")
        text = text.replace("/", "-").replace(".", "-")
    return text.lower()


def _quote(text: str, start: int, end: int) -> str:
    left = max(0, text.rfind("\n", 0, start) + 1)
    right = text.find("\n", end)
    return text[left : right if right >= 0 else len(text)].strip()[:240]
