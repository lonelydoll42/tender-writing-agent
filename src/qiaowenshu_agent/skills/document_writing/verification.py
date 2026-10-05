"""Deterministic, conservative checks for generated tender chapter claims."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


OCR_REVIEW_THRESHOLD = 0.66
_VALID_STATUSES = {
    "approved",
    "confirmed",
    "matched",
    "pass",
    "valid",
    "verified",
    "有效",
    "已确认",
    "已验证",
    "通过",
}
_INVALID_STATUSES = {
    "expired",
    "invalid",
    "rejected",
    "revoked",
    "unknown",
    "过期",
    "无效",
    "未知",
    "未核验",
    "未验证",
}
_ISO_RE = re.compile(
    r"(?<![A-Za-z0-9])ISO\s*(?:[/／]\s*IEC)?\s*[- ]?"
    r"(\d{4,5})(?:\s*:\s*\d{4})?(?!\d)",
    re.IGNORECASE,
)
_OTHER_CERT_RE = re.compile(
    r"(?<![A-Za-z0-9])(CMMI|ITSS|PMP)\s*[- ]?([1-5])?(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_PERSONNEL_QUALIFICATION_RE = re.compile(r"信息系统项目管理师|信息系统项目管理工程师")
_QUALIFICATION_WORD_RE = re.compile(r"认证|资质|资格|证书|证照|职称")
_QUALIFICATION_PHRASE_RE = re.compile(
    r"(?:取得|获得|通过|持有|具备|拥有)\s*"
    r"([\u4e00-\u9fffA-Za-z0-9/·（）()_-]{2,32}?"
    r"(?:认证|资质|资格|证书|证照|职称))"
)
_COUNT_RE = re.compile(
    r"(?P<number>\d[\d,]*|[零〇一二两三四五六七八九十百千万]+)"
    r"\s*(?:个|项|套|次|例|份)\s*(?:类似|成功|相关)?"
    r"(?:项目案例|项目经验|案例|项目|合同)"
    r"|(?:案例|项目经验|项目|合同)"
    r"(?:数量|数目|总数|共计)\s*[:：为]?\s*"
    r"(?P<number_after>\d[\d,]*|[零〇一二两三四五六七八九十百千万]+)"
    r"\s*(?:个|项|套|次|例|份)"
)
_AMOUNT_RE = re.compile(
    r"(?:人民币\s*)?[¥￥]?\s*(\d[\d,]*(?:\.\d+)?)\s*"
    r"(亿元|万元|万人民币|万|元|人民币)"
)
_DATE_RE = re.compile(
    r"(?<!\d)(20\d{2})\s*[-/.年]\s*(\d{1,2})"
    r"(?:\s*[-/.月]\s*(\d{1,2})\s*日?)?"
)
_PERSON_ROLE_RE = re.compile(
    r"项目经理|项目负责人|技术负责人|项目团队|高级工程师|工程师|"
    r"证书编号|证书号|证号|身份证号|持证"
)
_PERSON_NAME_RE = re.compile(
    r"(?:项目经理|项目负责人|技术负责人|姓名)\s*[:：为]?\s*"
    r"([\u4e00-\u9fff]{2,4}?)"
    r"(?=(?:持有|具有|已|具备|拥有|获得(?:了)?|取得|通过|负责|担任|"
    r"获评|任职|的|[，,。！？!?；;：:]|$))"
)
_CERT_NUMBER_RE = re.compile(
    r"(?:证书编号|证书号|证号)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9./_-]{2,})"
)
_PERSON_COUNT_RE = re.compile(
    r"(?:配备|安排|拥有|具有|共)?\s*(\d+)\s*(?:名|人)\s*"
    r"(?:项目经理|项目负责人|技术负责人|工程师)"
)
_CLAIM_NEGATION_RE = re.compile(
    r"未\s*(?:取得|通过|获得|拥有|具备|持有|完成|交付|认证)|"
    r"不具备|未认证|未获批|未批准|未承诺|不提供|不承诺|"
    r"无(?:有效)?(?:资质|认证|证书|案例|项目经验)"
)
_COMMITMENT_ACTION_RE = re.compile(
    r"承诺|保证|确保|我方将|我司将|本公司将|本企业将|"
    r"提供|安排|配备|交付|完成|在.{0,8}(?:内|前)"
)
_SERVICE_TERM_RE = re.compile(
    r"服务|支持|响应|质保|售后|运维|培训|驻场|到场|上线|交付|巡检|维护|升级|保障"
)
_SERVICE_ROLE_RE = re.compile(
    r"运维支持服务|售后服务|技术支持|运维支持|运维服务|"
    r"项目培训|培训|交付|响应|质保|售后|运维|支持|服务|"
    r"驻场|到场|上线|巡检|维护|升级|保障"
)
_DURATION_RE = re.compile(
    r"7\s*[×xX*]\s*24(?:\s*小时)?|"
    r"\d+(?:\.\d+)?\s*(?:分钟|小时|工作日|天|日|周|个月|月|年)"
)
_TENDER_REQUEST_RE = re.compile(
    r"(?:招标文件|招标要求|采购需求|采购人要求|评分标准|项目要求)"
    r".{0,30}(?:要求|规定|应|须|必须|需|提供|达到|满足)|"
    r"(?:要求|规定|应|须|必须|需)\s*(?:我方|投标人|供应商)?\s*"
    r"(?:提供|具备|满足|配备|达到|承诺)"
)
_COMPANY_ASSERTION_RE = re.compile(
    r"我方|我司|我公司|本公司|本企业|本单位|投标人已|已通过|已取得|"
    r"具备|拥有|持有|获得|完成了|实施了|交付了|中标"
)
_MATERIAL_REFERENCE_FIELDS = ("source_references", "references", "sources")


def verify_chapter(
    raw: Mapping[str, Any],
    *,
    content: str,
    payload: Mapping[str, Any],
    section: Mapping[str, Any],
    section_context: Mapping[str, Any],
    as_of: date | str | None = None,
) -> dict[str, Any]:
    """Validate model IDs and scan high-risk claims against supplied sources.

    The scanner is intentionally narrow. It detects selected high-risk patterns
    but is not a general natural-language fact verifier.
    """

    check_date = _parse_date(as_of) if as_of is not None else date.today()
    if check_date is None:
        raise ValueError("verification as_of must be a valid calendar date")
    expected_section_id = _identifier(section.get("section_id"))
    findings: list[dict[str, Any]] = []

    reported_section_id = _identifier(raw.get("section_id"))
    if not reported_section_id:
        findings.append(
            _finding(
                expected_section_id,
                "missing_section_id",
                "error",
                "模型未返回 section_id，章节归属不能由模型输出确认。",
            )
        )
    elif reported_section_id != expected_section_id:
        findings.append(
            _finding(
                expected_section_id,
                "invalid_section_id",
                "error",
                f"模型返回章节 ID {reported_section_id!r} 与实际生成章节不一致。",
                reference_id=reported_section_id,
            )
        )

    requirement_ids = _context_ids(
        section_context.get("requirements"),
        ("requirement_id", "id"),
    )
    scoring_ids = _context_ids(
        section_context.get("scoring_items"),
        ("item_id", "id"),
    )
    material_rows = _mapping_rows(section_context.get("materials"))
    material_ids = _context_ids(material_rows, ("material_id", "id"))

    reported_evidence, evidence_errors = _validate_reported_ids(
        raw.get("evidence_used"),
        material_ids,
        expected_section_id,
        "evidence_used",
    )
    reported_requirements, requirement_errors = _validate_reported_ids(
        raw.get("requirement_coverage"),
        requirement_ids,
        expected_section_id,
        "requirement_coverage",
    )
    reported_scoring, scoring_errors = _validate_reported_ids(
        raw.get("scoring_coverage"),
        scoring_ids,
        expected_section_id,
        "scoring_coverage",
    )
    findings.extend(evidence_errors + requirement_errors + scoring_errors)

    materials_by_id: dict[str, list[dict[str, Any]]] = {}
    for row in material_rows:
        identifier = _identifier(row.get("material_id") or row.get("id"))
        if identifier:
            materials_by_id.setdefault(identifier, []).append(row)
    for identifier, rows in materials_by_id.items():
        if len(rows) > 1:
            findings.append(
                _finding(
                    expected_section_id,
                    "ambiguous_material_id",
                    "error",
                    f"上下文中的材料 ID {identifier!r} 重复，无法唯一定位来源。",
                    reference_id=identifier,
                )
            )

    match_rows = _mapping_rows(section_context.get("evidence_matches"))
    match_status = _match_status_by_material(match_rows)
    for identifier in reported_evidence:
        rows = materials_by_id.get(identifier, [])
        if len(rows) != 1:
            continue
        usable, reason = _source_usable(
            rows[0],
            check_date,
            match_status.get(identifier, []),
        )
        if not usable:
            findings.append(
                _finding(
                    expected_section_id,
                    "evidence_source_not_verified",
                    "warning",
                    f"模型引用的材料 {identifier!r} 未达到可验证状态：{reason}",
                    reference_id=identifier,
                )
            )

    sources = _business_sources(payload, section_context)
    claims = scan_high_risk_claims(content, section_id=expected_section_id)
    claim_mapping: list[dict[str, Any]] = []
    supported_material_ids: set[str] = set()
    mapped_reported_ids: set[str] = set()

    for claim in claims:
        tender_statement = _is_tender_request(claim["claim_text"])
        if tender_statement and not _is_company_assertion(claim["claim_text"]):
            tender_evidence = _matching_tender_sources(
                claim,
                section_context,
            )
            if tender_evidence:
                claim_mapping.append(
                    {
                        **claim,
                        "status": "supported",
                        "scope": "tender_requirement_only",
                        "supports_enterprise_fact": False,
                        "evidence": tender_evidence,
                        "rejected_evidence": [],
                        "reason": (
                            "招标侧要求可由招标上下文支持；"
                            "该来源不证明企业已具备相应资质或经历。"
                        ),
                    }
                )
                continue

        matched_sources: list[dict[str, Any]] = []
        rejected_sources: list[dict[str, Any]] = []
        for source in sources:
            if not _source_supports_claim(source, claim):
                conflict_reason = _source_conflict_reason(source, claim)
                if conflict_reason:
                    rejected_sources.append(
                        {
                            "source_id": source["source_id"],
                            "source_type": source["source_type"],
                            "title": source.get("title", ""),
                            "reason": conflict_reason,
                        }
                    )
                continue
            usable, reason = _business_source_usable(
                source,
                check_date,
                match_status,
            )
            evidence = {
                "source_id": source["source_id"],
                "source_type": source["source_type"],
                "title": source.get("title", ""),
            }
            if usable:
                matched_sources.append(evidence)
                if source["source_type"] == "material":
                    supported_material_ids.add(source["source_id"])
                    if source["source_id"] in reported_evidence:
                        mapped_reported_ids.add(source["source_id"])
            else:
                rejected_sources.append({**evidence, "reason": reason})

        if matched_sources:
            claim_mapping.append(
                {
                    **claim,
                    "status": "supported",
                    "scope": "enterprise_fact",
                    "supports_enterprise_fact": True,
                    "evidence": matched_sources,
                    "rejected_evidence": rejected_sources,
                    "reason": "声明中的可识别关键值与有效企业材料或已提供事实相符。",
                }
            )
            continue

        status = "unsupported"
        reason = "未找到能够支持该正文高风险事实的企业材料或已确认事实。"
        if rejected_sources:
            reason = (
                "存在内容相关来源，但其状态、有效期、置信度或匹配状态"
                "不允许作为验证依据。"
            )
            findings.append(
                _finding(
                    expected_section_id,
                    "claim_source_not_usable",
                    "warning",
                    f"正文声明“{claim['claim_text']}”仅匹配到不可作为验证依据的来源。",
                    claim_id=claim["claim_id"],
                )
            )
        elif tender_statement and _matching_tender_sources(claim, section_context):
            reason = (
                "招标要求只能证明采购方提出了要求，不能证明企业已具备"
                "资质、履历或已批准承诺。"
            )
        claim_mapping.append(
            {
                **claim,
                "status": status,
                "scope": "enterprise_fact",
                "supports_enterprise_fact": False,
                "evidence": [],
                "rejected_evidence": rejected_sources,
                "reason": reason,
            }
        )
        findings.append(
            _finding(
                expected_section_id,
                "unsupported_high_risk_claim",
                "warning",
                f"正文高风险事实需要人工核实：{reason}",
                claim_id=claim["claim_id"],
            )
        )

    if claims:
        for identifier in reported_evidence:
            if identifier not in mapped_reported_ids:
                findings.append(
                    _finding(
                        expected_section_id,
                        "evidence_reference_not_mapped",
                        "warning",
                        (
                            f"材料 {identifier!r} 虽存在于章节上下文，但未被独立核验为"
                            "正文高风险声明的支持来源。"
                        ),
                        reference_id=identifier,
                    )
                )

    unsupported_claims = [
        claim for claim in claim_mapping if claim["status"] != "supported"
    ]
    return {
        "section_id": expected_section_id,
        "model_reported_section_id": reported_section_id or None,
        "reported_evidence_used": reported_evidence,
        "evidence_used": sorted(supported_material_ids),
        "requirement_coverage": reported_requirements,
        "scoring_coverage": reported_scoring,
        "claims_scanned": len(claim_mapping),
        "claim_evidence_mapping": claim_mapping,
        "unsupported_claims": unsupported_claims,
        "verification_findings": findings,
        "integrity_failed": any(finding["severity"] == "error" for finding in findings),
        "verified_material_ids": sorted(supported_material_ids),
    }


def scan_high_risk_claims(
    content: str,
    *,
    section_id: str = "",
) -> list[dict[str, Any]]:
    """Extract selected high-risk claim candidates from chapter prose."""

    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for sentence in _sentences(content):
        candidates: list[tuple[str, dict[str, Any]]] = []

        for match in _ISO_RE.finditer(sentence):
            candidates.append(
                (
                    "certification",
                    {
                        "standard": match.group(1),
                        "polarity": _claim_polarity(sentence),
                    },
                )
            )
        for match in _OTHER_CERT_RE.finditer(sentence):
            standard = match.group(1).upper() + (match.group(2) or "")
            if standard == "PMP":
                candidates.append(
                    (
                        "personnel_qualification",
                        {
                            "qualification": standard,
                            "person": _PERSON_NAME_RE.findall(sentence),
                            "polarity": _claim_polarity(sentence),
                        },
                    )
                )
            else:
                candidates.append(
                    (
                        "certification",
                        {
                            "standard": standard,
                            "polarity": _claim_polarity(sentence),
                        },
                    )
                )

        for match in _PERSONNEL_QUALIFICATION_RE.finditer(sentence):
            candidates.append(
                (
                    "personnel_qualification",
                    {
                        "qualification": match.group(0),
                        "person": _PERSON_NAME_RE.findall(sentence),
                        "polarity": _claim_polarity(sentence),
                    },
                )
            )

        has_credential_claim = any(
            category in {"certification", "personnel_qualification"}
            for category, _ in candidates
        )
        if (
            not has_credential_claim
            and _QUALIFICATION_WORD_RE.search(sentence)
            and _is_company_assertion(sentence)
        ):
            phrase = _QUALIFICATION_PHRASE_RE.search(sentence)
            candidates.append(
                (
                    "qualification_assertion",
                    {
                        "credential": (
                            phrase.group(1) if phrase else _normalize_compact(sentence)
                        ),
                        "polarity": _claim_polarity(sentence),
                    },
                )
            )
        for match in _COUNT_RE.finditer(sentence):
            number = match.group("number") or match.group("number_after")
            if number:
                candidates.append(
                    (
                        "case_quantity",
                        {
                            "count": _normalize_count(number),
                            "polarity": _claim_polarity(sentence),
                        },
                    )
                )
        for match in _AMOUNT_RE.finditer(sentence):
            amount = _amount_yuan(match.group(1), match.group(2))
            if amount is not None:
                role = _amount_role(sentence)
                candidates.append(
                    (
                        "amount",
                        {
                            "amount_yuan": str(amount),
                            "role": role,
                            "role_ambiguous": role is None,
                        },
                    )
                )
        for match in _DATE_RE.finditer(sentence):
            day = int(match.group(3)) if match.group(3) else None
            month = int(match.group(2))
            if month <= 12 and (day is None or day <= 31):
                candidates.append(
                    (
                        "date",
                        {
                            "date": (
                                f"{int(match.group(1)):04d}-{month:02d}"
                                if day is None
                                else f"{int(match.group(1)):04d}-{month:02d}-{day:02d}"
                            ),
                            "role": _date_role(sentence),
                            "role_ambiguous": _date_role(sentence) is None,
                            "polarity": _claim_polarity(sentence),
                        },
                    )
                )

        role_terms = sorted(set(_PERSON_ROLE_RE.findall(sentence)))
        if role_terms:
            details = _PERSON_NAME_RE.findall(sentence)
            details.extend(_CERT_NUMBER_RE.findall(sentence))
            details.extend(_PERSON_COUNT_RE.findall(sentence))
            candidates.append(
                (
                    "personnel",
                    {
                        "role_terms": role_terms,
                        "details": sorted(set(details)),
                        "polarity": _claim_polarity(sentence),
                    },
                )
            )

        service_terms = sorted(set(_SERVICE_TERM_RE.findall(sentence)))
        if service_terms and _COMMITMENT_ACTION_RE.search(sentence):
            commitment_pairs, relationship_ambiguous = _commitment_pairs(sentence)
            candidates.append(
                (
                    "service_commitment",
                    {
                        "service_terms": service_terms,
                        "service_roles": sorted(
                            {role for _, role, _ in commitment_pairs}
                        ),
                        "commitment_pairs": [list(item) for item in commitment_pairs],
                        "relationship_ambiguous": relationship_ambiguous,
                        "polarity": _claim_polarity(sentence),
                    },
                )
            )

        for category, markers in candidates:
            key = (category, sentence, repr(sorted(markers.items())))
            if key in seen:
                continue
            seen.add(key)
            result.append(
                {
                    "claim_id": f"{section_id}:claim-{len(result) + 1:03d}",
                    "section_id": section_id,
                    "category": category,
                    "claim_text": sentence,
                    "markers": markers,
                    "tender_request_statement": _is_tender_request(sentence),
                    "company_assertion": _is_company_assertion(sentence),
                }
            )
    return result


def resolve_as_of(
    explicit: Any,
    tender_profile: Mapping[str, Any],
    *,
    bid_deadline: Any = None,
) -> tuple[date, str]:
    """Choose and validate the date used for material-validity checks."""

    if explicit not in (None, ""):
        parsed = _parse_date(explicit)
        if parsed is None:
            raise ValueError("as_of must be a valid date such as YYYY-MM-DD")
        return parsed, "request_as_of"

    candidates: list[Any] = [bid_deadline, tender_profile.get("bid_deadline")]
    key_dates = tender_profile.get("key_dates")
    if isinstance(key_dates, Mapping):
        for key, value in key_dates.items():
            normalized_key = str(key).casefold().replace(" ", "_")
            if normalized_key in {
                "bid_deadline",
                "tender_deadline",
                "submission_deadline",
                "投标截止时间",
                "投标截止日期",
                "递交截止时间",
                "递交截止日期",
            }:
                candidates.append(value)
    for candidate in candidates:
        if candidate in (None, ""):
            continue
        parsed = _parse_date(candidate)
        if parsed is None:
            raise ValueError("tender bid deadline must be a valid calendar date")
        return parsed, "tender_bid_deadline"
    return date.today(), "system_date"


def _validate_reported_ids(
    value: Any,
    allowed: set[str],
    section_id: str,
    field_name: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    if value is None:
        return [], findings
    if isinstance(value, str):
        candidates = [item.strip() for item in value.replace("，", ",").split(",")]
    elif isinstance(value, (list, tuple, set)):
        candidates = []
        for item in value:
            if isinstance(item, (str, int)):
                text = str(item).strip()
                if text:
                    candidates.append(text)
            elif item not in (None, ""):
                findings.append(
                    _finding(
                        section_id,
                        f"malformed_{field_name}_id",
                        "error",
                        f"{field_name} 含有非 ID 值，已忽略该项。",
                        reference_id=str(item),
                    )
                )
    else:
        findings.append(
            _finding(
                section_id,
                f"malformed_{field_name}",
                "error",
                f"{field_name} 必须为 ID 字符串或列表，已忽略该字段。",
            )
        )
        return [], findings

    valid: list[str] = []
    seen: set[str] = set()
    for identifier in candidates:
        if not identifier:
            continue
        if identifier not in allowed:
            findings.append(
                _finding(
                    section_id,
                    f"unknown_{field_name}_id",
                    "error",
                    f"{field_name} 引用了不在本章节实际上下文中的 ID {identifier!r}。",
                    reference_id=identifier,
                )
            )
            continue
        if identifier not in seen:
            seen.add(identifier)
            valid.append(identifier)
    return valid, findings


def _business_sources(
    payload: Mapping[str, Any],
    section_context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for index, row in enumerate(_mapping_rows(section_context.get("materials"))):
        identifier = _identifier(row.get("material_id") or row.get("id"))
        if not identifier:
            continue
        sources.append(
            {
                "source_id": identifier,
                "source_type": "material",
                "title": str(row.get("title") or row.get("material_type") or ""),
                "text": _material_text(row),
                "row": row,
                "index": index,
            }
        )

    bidder = payload.get("bidder_profile")
    bidder = bidder if isinstance(bidder, Mapping) else {}
    confirmed = list(_fact_rows(payload.get("confirmed_facts"), "confirmed_fact"))
    confirmed.extend(
        _fact_rows(
            bidder.get("confirmed_facts"),
            "confirmed_fact",
        )
    )
    confirmed.extend(
        _fact_rows(payload.get("approved_commitments"), "approved_commitment")
    )
    confirmed.extend(
        _fact_rows(
            bidder.get("approved_commitments"),
            "approved_commitment",
        )
    )
    for index, fact in enumerate(confirmed):
        sources.append(
            {
                "source_id": fact["source_id"] or f"confirmed-fact-{index + 1}",
                "source_type": fact["source_type"],
                "title": fact.get("title", ""),
                "text": fact["text"],
                "row": fact,
                "index": index,
            }
        )

    return sources


def _fact_rows(
    value: Any,
    default_type: str,
) -> list[dict[str, Any]]:
    if value is None:
        return []
    rows: list[tuple[str, Any]]
    if isinstance(value, Mapping):
        rows = [(str(key), item) for key, item in value.items()]
    elif isinstance(value, (list, tuple)):
        rows = [(str(index + 1), item) for index, item in enumerate(value)]
    else:
        rows = [("1", value)]
    result: list[dict[str, Any]] = []
    for key, item in rows:
        if isinstance(item, Mapping):
            text = str(
                item.get("text")
                or item.get("claim")
                or item.get("fact")
                or item.get("value")
                or ""
            ).strip()
            if not text:
                continue
            if not _explicitly_confirmed(item, default_type):
                result.append(
                    {
                        "source_id": _identifier(item.get("fact_id") or item.get("id"))
                        or key,
                        "source_type": "unconfirmed_fact",
                        "title": str(item.get("title") or ""),
                        "text": text,
                        "row": dict(item),
                    }
                )
                continue
            result.append(
                {
                    "source_id": _identifier(item.get("fact_id") or item.get("id"))
                    or key,
                    "source_type": default_type,
                    "title": str(item.get("title") or ""),
                    "text": _fact_text(item, text),
                    "row": dict(item),
                }
            )
        elif isinstance(item, (str, int, float)):
            text = str(item).strip()
            if text:
                result.append(
                    {
                        "source_id": key,
                        "source_type": "unconfirmed_fact",
                        "title": "",
                        "text": text,
                        "row": {},
                    }
                )
    return result


def _attribute_fact(key: str, value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        text_value = value.get("value", value.get("text"))
        if text_value in (None, ""):
            return None
        row = dict(value)
        normalized_value = str(text_value)
    elif isinstance(value, (str, int, float, bool)):
        row = {"provided": True}
        normalized_value = str(value)
    else:
        return None
    labels = _attribute_labels(key)
    return {
        "source_id": f"bidder-profile:{key}",
        "source_type": "bidder_profile_field",
        "title": key,
        "text": f"{key} {' '.join(labels)} {normalized_value}",
        "row": row,
    }


def _source_supports_claim(source: Mapping[str, Any], claim: Mapping[str, Any]) -> bool:
    text = str(source.get("text") or "")
    normalized = _normalize_compact(text)
    category = claim["category"]
    markers = claim["markers"]
    source_type = str(source.get("source_type") or "")

    if category == "certification":
        standard = str(markers.get("standard") or "").casefold()
        if not standard or standard not in normalized:
            return False
        source_polarity = _claim_polarity(text)
        return source_polarity == markers.get("polarity")
    if category == "personnel_qualification":
        return _qualification_evidence_matches(
            text,
            str(markers.get("qualification") or ""),
            [str(item) for item in markers.get("person", [])],
            str(markers.get("polarity") or ""),
        )
    if category == "qualification_assertion":
        return _credential_evidence_matches(
            text,
            str(markers.get("credential") or ""),
            str(markers.get("polarity") or ""),
        )
    if category == "case_quantity":
        number = str(markers.get("count") or "")
        return bool(
            number
            and number in _all_count_values(text)
            and re.search(r"案例|项目|合同|case|project", text, re.IGNORECASE)
            and _claim_polarity(text) == markers.get("polarity")
        )
    if category == "amount":
        wanted = Decimal(str(markers["amount_yuan"]))
        amounts = _all_amount_values(text)
        wanted_role = markers.get("role")
        source_role = _amount_role(text)
        return (
            wanted in amounts
            and bool(wanted_role)
            and not markers.get("role_ambiguous")
            and wanted_role == source_role
        )
    if category == "date":
        wanted = str(markers.get("date") or "")
        wanted_role = markers.get("role")
        return bool(
            wanted
            and wanted in _all_dates(text)
            and wanted_role
            and not markers.get("role_ambiguous")
            and wanted_role == _date_role(text)
            and _claim_polarity(text) == markers.get("polarity")
        )
    if category == "personnel":
        role_terms = [str(item) for item in markers.get("role_terms", [])]
        details = [str(item) for item in markers.get("details", [])]
        if not all(_normalize_compact(term) in normalized for term in role_terms):
            return False
        if not all(_normalize_compact(detail) in normalized for detail in details):
            return False
        return bool(role_terms) and (_claim_polarity(text) == markers.get("polarity"))
    if category == "service_commitment":
        row = source.get("row")
        row = row if isinstance(row, Mapping) else {}
        source_kind = (
            f"{source.get('title', '')} {row.get('material_type', '')} "
            f"{row.get('category', '')} {source_type}"
        )
        approved_commitment = source_type == "approved_commitment" or (
            source_type == "confirmed_fact"
            and str(row.get("category") or row.get("type") or "").casefold()
            in {"commitment", "service_commitment", "承诺", "服务承诺"}
        )
        commitment_material = bool(
            source_type == "material"
            and re.search(
                r"承诺|服務承諾|服务承诺|commitment", source_kind, re.IGNORECASE
            )
        )
        if not (approved_commitment or commitment_material):
            return False
        wanted_pairs = {tuple(item) for item in markers.get("commitment_pairs", [])}
        source_pairs, source_ambiguous = _commitment_pairs(_claim_source_text(source))
        wanted_roles = set(str(item) for item in markers.get("service_roles", []))
        return (
            bool(wanted_roles)
            and not markers.get("relationship_ambiguous")
            and not source_ambiguous
            and wanted_roles == {role for _, role, _ in source_pairs}
            and wanted_pairs == set(source_pairs)
            and _claim_polarity(text) == markers.get("polarity")
        )
    return False


def _source_conflict_reason(
    source: Mapping[str, Any],
    claim: Mapping[str, Any],
) -> str:
    text = str(source.get("text") or "")
    normalized = _normalize_compact(text)
    category = claim["category"]
    markers = claim["markers"]
    if category == "certification":
        standard = str(markers.get("standard") or "").casefold()
        if standard in normalized and _claim_polarity(text) != markers.get("polarity"):
            return "来源对该资质记载的肯定/否定状态与正文相反"
    elif category == "personnel_qualification":
        qualification = str(markers.get("qualification") or "")
        people = [str(item) for item in markers.get("person", [])]
        if _qualification_evidence_matches(
            text,
            qualification,
            people,
            "negative" if markers.get("polarity") == "positive" else "positive",
        ):
            return "来源对该人员资质记载的肯定/否定状态与正文相反"
    elif category == "qualification_assertion":
        credential = str(markers.get("credential") or "")
        opposite_polarity = (
            "negative" if markers.get("polarity") == "positive" else "positive"
        )
        if _credential_evidence_matches(text, credential, opposite_polarity):
            return "来源对该资质记载的肯定/否定状态与正文相反"
    elif category == "amount":
        amount = Decimal(str(markers["amount_yuan"]))
        if amount in _all_amount_values(text):
            source_role = _amount_role(text)
            claim_role = markers.get("role")
            if not claim_role or source_role != claim_role:
                return "金额数值相同，但来源事实角色与正文不一致或无法唯一确定"
    elif category == "date":
        value = str(markers.get("date") or "")
        if value in _all_dates(text):
            source_role = _date_role(text)
            claim_role = markers.get("role")
            if not claim_role or source_role != claim_role:
                return "日期数值相同，但来源日期角色与正文不一致或无法唯一确定"
    elif category == "service_commitment":
        source_pairs, _ = _commitment_pairs(_claim_source_text(source))
        wanted_pairs = {tuple(item) for item in markers.get("commitment_pairs", [])}
        if source_pairs and wanted_pairs and source_pairs != wanted_pairs:
            return "承诺来源中的期限与服务类型配对和正文不一致"
    elif category in {"case_quantity", "personnel"}:
        if _claim_polarity(text) != markers.get("polarity"):
            return "来源对该企业事实记载的肯定/否定状态与正文相反"
    return ""


def _qualification_evidence_matches(
    text: str,
    qualification: str,
    people: list[str],
    polarity: str,
) -> bool:
    target = _normalize_compact(qualification)
    normalized_people = [_normalize_compact(person) for person in people]
    if (
        not target
        or not normalized_people
        or any(not person for person in normalized_people)
    ):
        return False
    return any(
        target in _normalize_compact(sentence)
        and all(person in _normalize_compact(sentence) for person in normalized_people)
        and _claim_polarity(sentence) == polarity
        for sentence in _sentences(text)
    )


def _credential_evidence_matches(
    text: str,
    credential: str,
    polarity: str,
) -> bool:
    target = _normalize_compact(credential)
    if not target:
        return False
    return any(
        target in _normalize_compact(sentence) and _claim_polarity(sentence) == polarity
        for sentence in _sentences(text)
    )


def _claim_source_text(source: Mapping[str, Any]) -> str:
    if source.get("source_type") == "material":
        row = source.get("row")
        if isinstance(row, Mapping):
            return str(row.get("content") or row.get("text") or "")
    return str(source.get("text") or "")


def _amount_role(text: str) -> str | None:
    roles = {
        "bid_quote": r"(?:本次|本项目|投标|本次投标).{0,8}(?:报价|投标总价)|投标报价",
        "quote": r"报价|投标总价",
        "contract_amount": r"合同(?:金额|额)",
        "project_amount": r"项目(?:金额|总额)",
        "award_amount": r"中标金额",
        "registered_capital": r"注册资本",
        "revenue": r"营业收入|年营收|营业额",
        "budget": r"采购预算|项目预算|预算|最高限价",
        "bid_bond": r"投标保证金|保证金",
    }
    found = [
        role
        for role, pattern in roles.items()
        if re.search(pattern, text, re.IGNORECASE)
    ]
    if "bid_quote" in found:
        found = [role for role in found if role != "quote"]
    return found[0] if len(found) == 1 else None


def _date_role(text: str) -> str | None:
    patterns = {
        "certificate_issue": r"证书.{0,8}(?:签发|发证)|(?:签发|发证)日期",
        "certificate_validity": r"(?:证书|认证).{0,10}(?:有效期|有效截止)|有效期至",
        "bid_deadline": r"投标.{0,8}(?:截止|递交)|递交截止|开标时间|提交截止",
        "delivery_date": r"交付|上线|交付期限|交付日期|完成交付",
        "contract_date": r"合同.{0,8}(?:签订|签署|日期)",
        "project_start": r"项目.{0,8}(?:启动|开始|开工)",
        "project_acceptance": r"项目.{0,8}(?:验收|竣工)",
        "social_security_period": r"社保|社会保险|缴纳期间",
    }
    found = [
        role
        for role, pattern in patterns.items()
        if re.search(pattern, text, re.IGNORECASE)
    ]
    if "certificate_validity" in found and "certificate_issue" in found:
        return None
    return found[0] if len(found) == 1 else None


def _commitment_pairs(text: str) -> tuple[set[tuple[str, str, str]], bool]:
    clauses = re.split(r"[，,；;。、]|并且|并|以及|同时|和", str(text or ""))
    pairs: set[tuple[str, str, str]] = set()
    ambiguous = False
    for clause in clauses:
        durations = [_normalize_compact(item) for item in _DURATION_RE.findall(clause)]
        roles = _SERVICE_ROLE_RE.findall(clause)
        polarity = _claim_polarity(clause)
        if not durations and not roles:
            continue
        if not durations and len(roles) == 1:
            pairs.add(("", roles[0], polarity))
        elif len(durations) == 1 and len(roles) == 1:
            pairs.add((durations[0], roles[0], polarity))
        else:
            ambiguous = True
    return pairs, ambiguous


def _claim_polarity(text: str) -> str:
    return "negative" if _CLAIM_NEGATION_RE.search(str(text or "")) else "positive"


def _business_source_usable(
    source: Mapping[str, Any],
    as_of: date,
    match_status: Mapping[str, list[dict[str, Any]]],
) -> tuple[bool, str]:
    row = source.get("row")
    if not isinstance(row, Mapping):
        row = {}
    if source.get("source_type") == "unconfirmed_fact":
        return False, "该字段没有显式确认状态"
    if source.get("source_type") == "bidder_profile_field":
        confidence = _read_confidence(row.get("confidence"))
        if confidence is not None and confidence < OCR_REVIEW_THRESHOLD:
            return False, f"字段置信度 {confidence:.2f} 低于复核阈值"
        status_values = _status_values(row)
        if any(status in _INVALID_STATUSES for status in status_values):
            return False, "企业字段状态为无效或未知"
        return True, "用户提供的企业字段"
    if source.get("source_type") in {
        "confirmed_fact",
        "approved_commitment",
        "unconfirmed_fact",
    }:
        return _explicit_fact_usable(row, str(source.get("source_type")))
    identifier = str(source.get("source_id") or "")
    return _material_usable(row, as_of, match_status.get(identifier, []))


def _source_usable(
    row: Mapping[str, Any],
    as_of: date,
    matches: list[dict[str, Any]],
) -> tuple[bool, str]:
    return _material_usable(row, as_of, matches)


def _material_usable(
    row: Mapping[str, Any],
    as_of: date,
    matches: list[dict[str, Any]],
) -> tuple[bool, str]:
    metadata = row.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    statuses = _status_values(row, metadata)
    if any(status in _INVALID_STATUSES for status in statuses):
        status = next(status for status in statuses if status in _INVALID_STATUSES)
        return False, f"材料状态为 {status}"
    if not statuses or any(status not in _VALID_STATUSES for status in statuses):
        return False, "材料没有明确的有效/已验证状态"

    valid_until = row.get("valid_until")
    if valid_until in (None, ""):
        valid_until = next(
            (
                metadata.get(key)
                for key in (
                    "valid_until",
                    "expires_at",
                    "expiration_date",
                    "expiry_date",
                )
                if metadata.get(key) not in (None, "")
            ),
            None,
        )
    if valid_until not in (None, ""):
        expiry = _parse_date(valid_until)
        if expiry is None:
            return False, "材料有效期无法解析"
        if expiry < as_of:
            return False, f"材料已于 {expiry.isoformat()} 过期"

    for reference in _source_references(row):
        confidence = _read_confidence(
            reference.get("confidence", reference.get("ocr_confidence"))
        )
        if confidence is not None and confidence < OCR_REVIEW_THRESHOLD:
            return False, f"来源置信度 {confidence:.2f} 低于复核阈值"

    for match in matches:
        status = _normalized_status(match.get("status"))
        if status in _INVALID_STATUSES or status not in _VALID_STATUSES:
            return False, f"证据匹配状态为 {status or 'unknown'}"
        confidence = _read_confidence(match.get("confidence"))
        if confidence is not None and confidence < OCR_REVIEW_THRESHOLD:
            return False, f"证据匹配置信度 {confidence:.2f} 低于复核阈值"
        for reference in _source_references(match):
            reference_confidence = _read_confidence(
                reference.get("confidence", reference.get("ocr_confidence"))
            )
            if (
                reference_confidence is not None
                and reference_confidence < OCR_REVIEW_THRESHOLD
            ):
                return False, f"匹配来源置信度 {reference_confidence:.2f} 低于复核阈值"
    return True, "材料状态有效"


def _explicit_fact_usable(
    row: Mapping[str, Any],
    source_type: str,
) -> tuple[bool, str]:
    confidence = _read_confidence(row.get("confidence"))
    if confidence is not None and confidence < OCR_REVIEW_THRESHOLD:
        return False, f"事实置信度 {confidence:.2f} 低于复核阈值"
    statuses = _status_values(row)
    if any(status in _INVALID_STATUSES for status in statuses):
        status = next(status for status in statuses if status in _INVALID_STATUSES)
        return False, f"事实状态为 {status}"
    if statuses and any(status not in _VALID_STATUSES for status in statuses):
        return False, "事实状态未确认"
    if source_type == "approved_commitment":
        if not _explicitly_confirmed(row, source_type):
            return False, "承诺没有显式的已批准状态"
    elif source_type == "confirmed_fact":
        if not _explicitly_confirmed(row, source_type):
            return False, "事实没有显式的已确认状态"
    else:
        return False, "事实没有显式的已确认状态"
    return True, "已确认事实"


def _match_status_by_material(
    matches: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for match in matches:
        identifiers: list[str] = []
        one = match.get("material_id")
        if one not in (None, ""):
            identifiers.append(str(one))
        many = match.get("material_ids") or match.get("evidence_material_ids") or []
        if isinstance(many, (list, tuple, set)):
            identifiers.extend(str(item) for item in many if item not in (None, ""))
        for identifier in identifiers:
            result.setdefault(identifier, []).append(match)
    return result


def _matching_tender_sources(
    claim: Mapping[str, Any],
    section_context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    source_text = "\n".join(
        [
            str(section_context.get("source_excerpt") or ""),
            str(section_context.get("source_section") or ""),
            _flatten_text(section_context.get("tender_profile")),
        ]
    )
    for row in _mapping_rows(section_context.get("requirements")):
        text = _flatten_text(row)
        if text and _tender_text_supports(text, claim):
            matched.append(
                {
                    "source_id": _identifier(
                        row.get("requirement_id") or row.get("id")
                    ),
                    "source_type": "tender_requirement",
                    "title": str(row.get("title") or ""),
                }
            )
    for row in _mapping_rows(section_context.get("scoring_items")):
        text = _flatten_text(row)
        if text and _tender_text_supports(text, claim):
            matched.append(
                {
                    "source_id": _identifier(row.get("item_id") or row.get("id")),
                    "source_type": "tender_scoring_item",
                    "title": str(row.get("title") or ""),
                }
            )
    if source_text and _tender_text_supports(source_text, claim):
        matched.append(
            {
                "source_id": "provided-tender-text",
                "source_type": "tender_source_text",
                "title": "招标原文或项目字段",
            }
        )
    return matched


def _tender_text_supports(text: str, claim: Mapping[str, Any]) -> bool:
    category = claim["category"]
    markers = claim["markers"]
    compact = _normalize_compact(text)
    if category == "certification":
        return (
            str(markers.get("standard") or "").casefold() in compact
            and _claim_polarity(text) == markers.get("polarity")
            and bool(
                re.search(
                    r"应|须|要求|提供|认证|证书|资质|ISO|CMMI|ITSS|PMP",
                    text,
                    re.IGNORECASE,
                )
            )
        )
    if category == "personnel_qualification":
        qualification = _normalize_compact(str(markers.get("qualification") or ""))
        return (
            bool(qualification)
            and qualification in compact
            and _claim_polarity(text) == markers.get("polarity")
            and bool(
                re.search(
                    r"应|须|要求|提供|配备|项目经理|项目负责人|资质|资格|证书",
                    text,
                )
            )
        )
    if category == "qualification_assertion":
        credential = _normalize_compact(str(markers.get("credential") or ""))
        return (
            bool(credential)
            and credential in compact
            and _claim_polarity(text) == markers.get("polarity")
            and bool(re.search(r"应|须|要求|提供|资质|资格|证书|认证", text))
        )
    if category == "case_quantity":
        return str(markers.get("count") or "") in _all_count_values(text) and bool(
            re.search(r"案例|项目|合同|应|须|评分|要求", text)
        )
    if category == "amount":
        role = markers.get("role")
        return (
            Decimal(str(markers["amount_yuan"])) in _all_amount_values(text)
            and bool(role)
            and not markers.get("role_ambiguous")
            and role == _amount_role(text)
        )
    if category == "date":
        role = markers.get("role")
        return (
            str(markers.get("date") or "") in _all_dates(text)
            and bool(role)
            and not markers.get("role_ambiguous")
            and role == _date_role(text)
            and _claim_polarity(text) == markers.get("polarity")
        )
    if category == "personnel":
        return all(
            _normalize_compact(term) in compact
            for term in markers.get("role_terms", [])
        ) and all(
            _normalize_compact(detail) in compact
            for detail in markers.get("details", [])
        )
    if category == "service_commitment":
        pairs, ambiguous = _commitment_pairs(text)
        return (
            not ambiguous
            and set(tuple(item) for item in markers.get("commitment_pairs", []))
            == pairs
            and bool(re.search(r"要求|应|须|必须|需|评分|采购", text))
        )
    return False


def _is_tender_request(text: str) -> bool:
    return bool(_TENDER_REQUEST_RE.search(text))


def _is_company_assertion(text: str) -> bool:
    if _is_tender_request(text):
        return bool(
            re.search(
                r"(?:我方|我司|本公司|本企业|本单位)\s*(?:已|具备|拥有|持有|通过|取得|获得|承诺|保证|确保|将)",
                text,
            )
        )
    return bool(_COMPANY_ASSERTION_RE.search(text))


def _status_values(*rows: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for row in rows:
        for key in (
            "verification_status",
            "status",
            "state",
            "validity_status",
        ):
            if row.get(key) not in (None, ""):
                values.append(_normalized_status(row[key]))
    return values


def _normalized_status(value: Any) -> str:
    return str(value or "").strip().casefold().replace(" ", "_")


def _source_references(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    for key in _MATERIAL_REFERENCE_FIELDS:
        value = row.get(key)
        if isinstance(value, Mapping):
            return [dict(value)]
        if isinstance(value, (list, tuple)):
            return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _read_confidence(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    if 1 < confidence <= 100:
        confidence /= 100
    return max(0.0, min(confidence, 1.0))


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    iso = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None
    chinese = re.match(r"^(\d{4})年(\d{1,2})月(\d{1,2})日?", text)
    if chinese:
        try:
            return date(
                int(chinese.group(1)), int(chinese.group(2)), int(chinese.group(3))
            )
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _sentences(text: str) -> list[str]:
    result: list[str] = []
    for line in str(text or "").splitlines():
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)
        for part in re.split(r"(?<=[。！？!?；;])\s*", line):
            part = part.strip(" \t|`*-")
            if part:
                result.append(part)
    return result


def _material_text(row: Mapping[str, Any]) -> str:
    metadata = row.get("metadata")
    parts = [
        row.get("material_type"),
        row.get("type"),
        row.get("title"),
        row.get("name"),
        row.get("content"),
        row.get("text"),
        row.get("valid_until"),
        _flatten_text(metadata),
    ]
    return " ".join(str(part) for part in parts if part not in (None, ""))


def _fact_text(row: Mapping[str, Any], default: str) -> str:
    return (
        " ".join(
            str(row.get(key))
            for key in ("category", "type", "title", "text", "claim", "fact", "value")
            if row.get(key) not in (None, "")
        )
        or default
    )


def _explicitly_confirmed(row: Mapping[str, Any], source_type: str) -> bool:
    if source_type == "approved_commitment":
        if row.get("approved") is True:
            return True
        approved_states = {"approved", "已批准"}
        return any(
            _normalized_status(row.get(key)) in approved_states
            for key in ("status", "verification_status")
            if row.get(key) not in (None, "")
        )
    if row.get("confirmed") is True:
        return True
    confirmed_states = {
        "approved",
        "confirmed",
        "valid",
        "verified",
        "有效",
        "已确认",
        "已验证",
        "通过",
    }
    return any(
        _normalized_status(row.get(key)) in confirmed_states
        for key in ("status", "verification_status")
        if row.get(key) not in (None, "")
    )


def _flatten_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join(
            f"{key} {_flatten_text(item)}"
            for key, item in value.items()
            if item not in (None, "")
        )
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_text(item) for item in value if item not in (None, ""))
    return str(value or "")


def _attribute_labels(key: str) -> list[str]:
    normalized = key.casefold().replace("-", "_")
    labels: list[str] = []
    if any(item in normalized for item in ("case", "project", "案例", "项目")):
        labels.extend(["案例", "项目"])
    if any(
        item in normalized for item in ("amount", "revenue", "price", "金额", "合同额")
    ):
        labels.extend(["金额", "合同额"])
    if any(item in normalized for item in ("cert", "iso", "资质", "认证")):
        labels.extend(["资质", "认证", "证书"])
    if any(item in normalized for item in ("person", "manager", "人员", "证书")):
        labels.extend(["人员", "项目经理", "证书"])
    if any(
        item in normalized for item in ("service", "commit", "服务", "承诺", "交付")
    ):
        labels.extend(["服务", "承诺", "交付"])
    if any(
        item in normalized for item in ("date", "deadline", "日期", "期限", "有效期")
    ):
        labels.extend(["日期", "有效期"])
    return labels


def _all_count_values(text: str) -> set[str]:
    result: set[str] = set()
    for match in _COUNT_RE.finditer(str(text or "")):
        number = match.group("number") or match.group("number_after")
        normalized = _normalize_count(number or "")
        if normalized:
            result.add(normalized)
    return result


def _normalize_count(value: str) -> str:
    compact = str(value or "").replace(",", "").strip()
    if compact.isdigit():
        return str(int(compact))
    parsed = _chinese_integer(compact)
    return str(parsed) if parsed is not None else compact


def _chinese_integer(value: str) -> int | None:
    digits = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if not value or any(
        char not in digits and char not in "十百千万" for char in value
    ):
        return None
    total = 0
    section = 0
    current = 0
    units = {"十": 10, "百": 100, "千": 1000}
    for char in value:
        if char in digits:
            current = digits[char]
        elif char in units:
            section += (current or 1) * units[char]
            current = 0
        elif char == "万":
            total = (total + section + current) * 10000
            section = 0
            current = 0
    return total + section + current


def _amount_yuan(number: str, unit: str) -> Decimal | None:
    try:
        value = Decimal(number.replace(",", ""))
    except InvalidOperation:
        return None
    multiplier = {
        "亿元": Decimal(100_000_000),
        "万元": Decimal(10_000),
        "万人民币": Decimal(10_000),
        "万": Decimal(10_000),
        "元": Decimal(1),
        "人民币": Decimal(1),
    }[unit]
    return value * multiplier


def _all_amount_values(text: str) -> set[Decimal]:
    result: set[Decimal] = set()
    for match in _AMOUNT_RE.finditer(str(text or "")):
        amount = _amount_yuan(match.group(1), match.group(2))
        if amount is not None:
            result.add(amount)
    return result


def _all_dates(text: str) -> set[str]:
    result: set[str] = set()
    for match in _DATE_RE.finditer(str(text or "")):
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3)) if match.group(3) else None
        if month > 12 or (day is not None and day > 31):
            continue
        result.add(
            f"{year:04d}-{month:02d}"
            if day is None
            else f"{year:04d}-{month:02d}-{day:02d}"
        )
    return result


def _normalize_compact(value: str) -> str:
    return re.sub(r"[\W_]+", "", str(value or ""), flags=re.UNICODE).casefold()


def _identifier(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _context_ids(rows: Any, keys: tuple[str, ...]) -> set[str]:
    result: set[str] = set()
    for row in _mapping_rows(rows):
        for key in keys:
            identifier = _identifier(row.get(key))
            if identifier:
                result.add(identifier)
                break
    return result


def _mapping_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _finding(
    section_id: str,
    code: str,
    severity: str,
    message: str,
    *,
    reference_id: str | None = None,
    claim_id: str | None = None,
) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "section_id": section_id,
        "code": code,
        "severity": severity,
        "message": message,
    }
    if reference_id:
        finding["reference_id"] = reference_id
    if claim_id:
        finding["claim_id"] = claim_id
    return finding
