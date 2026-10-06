"""Conservative condition trees for a small local requirement subset."""

from __future__ import annotations

import re
from typing import Any


def build_local_requirement_rule(text: str) -> dict[str, Any]:
    """Return a traceable manual-review rule, or ``{}`` when unsupported."""

    if not isinstance(text, str) or not text.strip():
        return {}
    source = re.sub(r"\s+", " ", text).strip()
    compact = _compact(source)
    logic: dict[str, Any] | None = None

    if _has_all(compact, "营业执照", "法人登记"):
        logic = _join(
            source,
            [
                _evidence(
                    "business_license",
                    ["营业执照"],
                    validity=_validity(source, "营业执照"),
                ),
                _evidence(
                    "legal_entity_registration",
                    ["法人登记"],
                    validity=_validity(source, "法人登记"),
                ),
            ],
            operator=_between_operator(source, "营业执照", "法人登记"),
        )
    elif _has_any(compact, "营业执照", "法人登记"):
        logic = (
            _evidence(
                "business_license",
                ["营业执照"],
                validity=_validity(source, "营业执照"),
            )
            if _has(compact, "营业执照")
            else _evidence(
                "legal_entity_registration",
                ["法人登记"],
                validity=_validity(source, "法人登记"),
            )
        )
    elif _has_any(compact, "审计报告", "银行资信", "资信证明"):
        conditions: list[dict[str, Any]] = []
        if _has(compact, "审计报告"):
            audit = _evidence("audit_report_key_pages", ["审计报告", "关键页"])
            year = re.search(r"((?:19|20)\d{2})\s*年", source)
            if year:
                audit["year"] = int(year.group(1))
            conditions.append(audit)
        if _has_any(compact, "银行资信", "资信证明"):
            conditions.append(
                _evidence("bank_credit_reference", ["银行资信", "资信证明"])
            )
        logic = _join(
            source,
            conditions,
            operator=_between_operator(source, "审计报告", "银行资信")
            if _has(compact, "审计报告") and _has_any(compact, "银行资信", "资信证明")
            else "all",
        )
    elif _has_all(compact, "信息系统项目管理师", "社会保险") or _has_all(
        compact, "信息系统项目管理师", "社保"
    ):
        conditions = [
            _evidence("personnel_certificate", ["信息系统项目管理师"]),
            _evidence("social_security_record", ["社会保险", "社保"]),
        ]
        if _has(compact, "投标人"):
            conditions.append(
                _evidence(
                    "bidder_employer_relationship",
                    ["投标人", "缴纳", "社会保险", "社保"],
                )
            )
        month_range = _month_range(source)
        if month_range:
            conditions.append(
                {
                    "op": "date_range",
                    "field": "social_security_month",
                    "start": month_range[0],
                    "end": month_range[1],
                    "continuous": _has(compact, "连续"),
                    "source_terms": ["连续", "社会保险", "社保"],
                }
            )
        else:
            conditions.append(
                {
                    "op": "manual_review",
                    "reason": "社保起止月份无法从原文可靠提取",
                    "source_text": source,
                }
            )
        sameperson = {
            "op": "sameperson",
            "subject": "拟任项目经理/项目经理",
            "person_field": "person_id",
            "conditions": [
                {
                    "op": "all",
                    "conditions": conditions,
                    "source_text": source,
                }
            ],
            "source_terms": ["拟任项目经理", "项目经理", "同人"],
            "source_text": source,
        }
        logic = {
            "op": "all",
            "conditions": [sameperson],
            "source_text": source,
        }
    elif _has_any(compact, "oauth2", "oidc") and _has_any(
        compact, "身份平台", "身份系统", "统一身份"
    ):
        conditions = [
            _evidence("identity_integration", ["OAuth2.0", "OIDC", "对接"]),
            _evidence("existing_identity_system", ["现有身份平台", "现有身份系统"]),
        ]
        replacement_markers = (
            "不得更换",
            "不能更换",
            "不可更换",
            "不得要求更换",
            "不能要求更换",
            "不得替换",
            "不能替换",
        )
        if _has_any(compact, *replacement_markers):
            replacement_terms = [
                term
                for term in replacement_markers
                if _has(compact, term)
            ]
            conditions.append(
                {
                    "op": "not",
                    "condition": {
                        "op": "comparison",
                        "field": "identity_system_changed",
                        "operator": "eq",
                        "value": True,
                        "source_terms": replacement_terms or ["更换", "替换"],
                    },
                }
            )
        protocol_conditions = []
        if _has(compact, "oauth2"):
            protocol_conditions.append(_evidence("oauth2", ["OAuth2.0"]))
        if _has(compact, "oidc"):
            protocol_conditions.append(_evidence("oidc", ["OIDC"]))
        protocol = (
            protocol_conditions[0]
            if len(protocol_conditions) == 1
            else _join(source, protocol_conditions, operator="any")
        )
        conditions[0] = protocol
        logic = _join(source, conditions, operator="all")
    elif _has(compact, "tls") and _has_any(compact, "敏感字段", "国密"):
        conditions = []
        tls = re.search(
            r"TLS\s*([0-9]+(?:\.[0-9]+)?)\s*(?:及以上|\+|以上)", source, re.I
        )
        if tls:
            conditions.append(
                {
                    "op": "comparison",
                    "field": "tls_version",
                    "operator": "gte",
                    "value": tls.group(1),
                    "source_terms": ["TLS", tls.group(1)],
                }
            )
        else:
            conditions.append(
                {
                    "op": "manual_review",
                    "reason": "TLS 阈值无法从原文可靠提取",
                    "source_text": source,
                }
            )
        if _has(compact, "敏感字段"):
            conditions.append(_evidence("sensitive_database_fields", ["敏感字段"]))
        crypto = []
        if _has(compact, "国密"):
            crypto.append(_evidence("national_cryptography", ["国密"]))
        if _has(compact, "等效强度"):
            crypto.append(_evidence("equivalent_strength_encryption", ["等效强度"]))
        if len(crypto) == 1:
            conditions.append(crypto[0])
        elif len(crypto) > 1:
            conditions.append(
                _join(
                    source,
                    crypto,
                    operator=_between_operator(source, "国密", "等效强度")
                    if _has_any(compact, "国密", "等效强度")
                    else "all",
                )
            )
        logic = _join(source, conditions, operator="all")
    elif _has(compact, "国产linux") and _has(compact, "postgresql"):
        conditions = [
            _evidence("domestic_linux", ["国产Linux"]),
            _evidence("postgresql_compatibility", ["PostgreSQL", "兼容"]),
        ]
        if _has_any(compact, "不绑定单一公有云", "不得绑定单一公有云"):
            conditions.append(
                {
                    "op": "not",
                    "condition": {
                        "op": "comparison",
                        "field": "single_public_cloud_binding",
                        "operator": "eq",
                        "value": True,
                        "source_terms": ["不绑定单一公有云", "不得绑定单一公有云"],
                    },
                }
            )
        logic = _join(source, conditions, operator="all")

    return _rule(source, logic) if logic else {}


def _rule(source: str, logic: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_ast": {
            "op": "manual_review",
            "reason": "阶段B仅保留条件结构，自动核验不支持",
            "source_text": source,
            "condition_logic": logic,
            "coverage_status": "partial",
        },
        "condition_logic": logic,
        "coverage_status": "partial",
        "source_text": source,
        "evaluation_capability": {"automatic": "unsupported", "human_review": True},
    }


def _join(
    source: str,
    conditions: list[dict[str, Any]],
    *,
    operator: str,
) -> dict[str, Any]:
    if not conditions:
        return {
            "op": "manual_review",
            "reason": "条件未能可靠解析",
            "source_text": source,
        }
    return {"op": operator, "conditions": conditions, "source_text": source}


def _evidence(
    material_type: str,
    source_terms: list[str],
    *,
    validity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "op": "evidence",
        "material_type": material_type,
        "source_terms": source_terms,
    }
    if validity is not None:
        node["validity"] = validity
    return node


def _validity(source: str, term: str) -> dict[str, Any] | None:
    if "有效" not in source:
        return None
    return {"required": True, "source_terms": ["有效", term]}


def _between_operator(source: str, left: str, right: str) -> str:
    start = source.find(left)
    end = source.find(right, start + len(left))
    if start < 0 or end < 0:
        start = source.find(right)
        end = source.find(left, start + len(right))
        if start < 0 or end < 0:
            return "all"
    fragment = source[start + len(left) : end]
    if "或" in fragment or "或者" in fragment:
        return "any"
    return "all"


def _month_range(source: str) -> tuple[str, str] | None:
    match = re.search(
        r"((?:19|20)\d{2})\s*年\s*(\d{1,2})\s*月"
        r"\s*(?:至|到|-|—|~|～)\s*"
        r"((?:19|20)\d{2})?\s*年?\s*(\d{1,2})\s*月",
        source,
    )
    if not match:
        return None
    start_year, start_month = int(match.group(1)), int(match.group(2))
    end_year = int(match.group(3) or start_year)
    end_month = int(match.group(4))
    if not 1 <= start_month <= 12 or not 1 <= end_month <= 12:
        return None
    return f"{start_year:04d}-{start_month:02d}", f"{end_year:04d}-{end_month:02d}"


def _compact(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.casefold())


def _has(value: str, term: str) -> bool:
    return _compact(term) in value


def _has_any(value: str, *terms: str) -> bool:
    return any(_has(value, term) for term in terms)


def _has_all(value: str, *terms: str) -> bool:
    return all(_has(value, term) for term in terms)
