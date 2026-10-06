"""Deterministic, conservative checks for generated tender chapter claims."""

from __future__ import annotations

import re
import unicodedata
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
    r"(?<![A-Za-z0-9-])ISO\s*(?P<iec>[/／]\s*IEC)?\s*[- ]?"
    r"(?P<number>\d{4,5})(?:\s*[:：]\s*(?P<edition>\d{4}))?"
    r"(?![A-Za-z0-9-])",
    re.IGNORECASE,
)
_ISO_IEC_ALIAS_NUMBERS = {"27001"}
_OTHER_CERT_RE = re.compile(
    r"(?<![A-Za-z0-9-])(?P<family>CMMI|ITSS)"
    r"(?:\s*(?:[-–—]\s*)?(?:(?:LEVEL|级别|等级)\s*)?"
    r"(?P<level>[1-5]))?(?![A-Za-z0-9-])",
    re.IGNORECASE,
)
_PMP_RE = re.compile(r"(?<![A-Za-z0-9])PMP(?![A-Za-z0-9])", re.IGNORECASE)
_PERSONNEL_QUALIFICATION_RE = re.compile(r"信息系统项目管理师|信息系统项目管理工程师")
_QUALIFICATION_WORD_RE = re.compile(r"认证|资质|资格|证书|证照|职称")
_QUALIFICATION_PHRASE_RE = re.compile(
    r"(?:取得|获得|通过|持有|具备|拥有)\s*"
    r"([\u4e00-\u9fffA-Za-z0-9/·（）()_-]{2,32}?"
    r"(?:认证|资质|资格|证书|证照|职称))"
)
_COUNT_RE = re.compile(
    r"(?P<number>\d[\d,]*|[零〇一二两三四五六七八九十百千万]+|"
    r"数十|数百|数千|几十|几百|几千|十余|百余|千余)"
    r"\s*(?:个|项|套|次|例|份)\s*"
    r"[\u4e00-\u9fffA-Za-z]{0,16}?"
    r"(?:类似|成功|相关|大型|重点|政务|政府)?"
    r"(?:项目案例|项目经验|案例|项目|合同|客户)"
    r"|(?:案例|项目经验|项目|合同)"
    r"(?:数量|数目|总数|共计)\s*[:：为]?\s*"
    r"(?P<number_after>\d[\d,]*|[零〇一二两三四五六七八九十百千万]+|"
    r"数十|数百|数千|几十|几百|几千|十余|百余|千余)"
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
_UNCLASSIFIED_COMPANY_RISK_RE = re.compile(
    r"(?:我方|我司|我公司|本公司|本企业|本单位|投标人|供应商)"
    r".{0,36}(?:累计|已经|已|曾|承接|实施|交付|完成|中标|取得|获得|具备|"
    r"拥有|持有|服务|提供|承诺|保证|确保)"
    r".{0,48}(?:资质|证书|认证|项目|合同|案例|经验|客户|人员|团队|金额|"
    r"业绩|能力|服务|交付|承诺)",
    re.IGNORECASE,
)
_HOLDER_LABEL_RE = re.compile(
    r"(?:证书持有人|持证主体|认证主体|获证组织|获证单位|认证单位|持证人)"
    r"\s*(?:为|是|[:：])\s*"
    r"(?P<holder>[^，,；;。()\r\n]{2,80})"
)
_EXPLICIT_REGISTRATION_ID_RE = re.compile(
    r"(?:统一社会信用代码|社会信用代码|信用代码|注册号)"
    r"\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9-]{7,31})",
    re.IGNORECASE,
)
_CERTIFICATE_NUMBER_LABEL_RE = re.compile(
    r"(?:证书编号|证书号|证号|编号|certificate\s*(?:no\.?|number))"
    r"\s*[:：]?\s*[A-Za-z0-9][A-Za-z0-9./_-]*",
    re.IGNORECASE,
)
_BIDDER_NAME_FIELDS = (
    "bidder_name",
    "name",
    "company_name",
    "enterprise_name",
    "organization_name",
    "legal_name",
)
_REGISTRATION_ID_FIELDS = (
    "unified_social_credit_code",
    "social_credit_code",
    "credit_code",
    "registration_id",
    "registration_number",
    "registered_id",
    "uscc",
)
_FLAT_METADATA_HOLDER_ID_FIELDS = (
    "unified_social_credit_code",
    "social_credit_code",
    "credit_code",
)
_ISSUER_FIELDS = (
    "issuer",
    "issuer_name",
    "issuing_authority",
    "certificate_issuer",
    "accreditation_body",
    "发证机构",
    "认证机构",
    "签发机构",
)
_ISSUER_REGISTRATION_ID_FIELDS = (
    "issuer_registration_id",
    "issuer_credit_code",
    "issuer_unified_social_credit_code",
    "issuing_authority_registration_id",
    "issuing_authority_credit_code",
)
_ISSUER_CONTEXT_RE = re.compile(r"发证机构|认证机构|颁证机构|签发机构|认证服务机构")
_HOLDER_NAME_FIELDS = (
    "holder",
    "holder_name",
    "certificate_holder",
    "certificate_holder_name",
    "certification_holder",
    "subject_name",
    "certification_subject",
)
_BUSINESS_OWNER_FIELDS = (
    "owner_name",
    "business_owner",
    "evidence_owner",
    "subject_owner",
)
_BUSINESS_ENTITY_NAME_PATTERN = (
    r"[\u4e00-\u9fffA-Za-z0-9·（）()]{1,48}?"
    r"(?:有限责任公司|股份有限公司|集团有限公司|有限公司|集团|公司|企业)"
)
_BUSINESS_OWNER_LABEL_RE = re.compile(
    r"(?:业绩主体|材料主体|企业主体|公司主体|主体)"
    r"\s*(?:为|是|[:：])\s*"
    rf"(?P<holder>{_BUSINESS_ENTITY_NAME_PATTERN})"
)
_BUSINESS_ENTITY_PREFIX_RE = re.compile(
    rf"^\s*(?P<owner>{_BUSINESS_ENTITY_NAME_PATTERN})"
    r"(?=\s*(?:累计|历史|历年|合同金额|合同|业绩|项目|政务|承接|完成|"
    r"案例|台账|清单|经验))"
)
_CERTIFICATION_STANDARD_FIELDS = (
    "certificate_type",
    "certification_type",
    "certification_standard",
    "certificate_standard",
    "standard",
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
    coverage = _claim_scan_coverage(content, claims)
    claim_mapping: list[dict[str, Any]] = []
    supported_material_ids: set[str] = set()
    mapped_reported_ids: set[str] = set()

    if coverage["status"] == "not_scanned":
        findings.append(
            _finding(
                expected_section_id,
                "claim_scan_not_run",
                "warning",
                "章节正文为空，无法执行高风险声明扫描。",
            )
        )
    for claim in claims:
        if claim["category"] != "unclassified_high_risk_assertion":
            continue
        claim_mapping.append(
            {
                **claim,
                "status": "needs_review",
                "scope": "enterprise_fact",
                "supports_enterprise_fact": False,
                "evidence": [],
                "rejected_evidence": [],
                "reason": (
                    "检测到企业高风险陈述，但当前模式无法完整分类"
                    "或提取其事实值。"
                ),
            }
        )
        findings.append(
            _finding(
                expected_section_id,
                "unclassified_high_risk_claim",
                "warning",
                "存在未能完整解析的企业高风险陈述，需人工核验。",
                claim_id=claim["claim_id"],
            )
        )

    bidder_identity = _bidder_identity(payload)
    for claim in claims:
        if claim["category"] == "unclassified_high_risk_assertion":
            continue
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
            else:
                claim_mapping.append(
                    {
                        **claim,
                        "status": "needs_review",
                        "scope": "tender_requirement_only",
                        "supports_enterprise_fact": False,
                        "evidence": [],
                        "rejected_evidence": [],
                        "reason": "未在招标上下文中找到足以核对该要求的来源。",
                    }
                )
                findings.append(
                    _finding(
                        expected_section_id,
                        "unverified_tender_requirement_statement",
                        "warning",
                        "正文复述的招标要求未能与招标上下文核对。",
                        claim_id=claim["claim_id"],
                    )
                )
            continue

        matched_sources: list[dict[str, Any]] = []
        rejected_sources: list[dict[str, Any]] = []
        certification_audits: list[dict[str, Any]] = []
        subject_audits: list[dict[str, Any]] = []
        for source in sources:
            certification_audit = None
            subject_audit = None
            if claim["category"] == "certification":
                certification_audit = _certification_source_check(
                    source,
                    claim,
                    bidder_identity,
                )
                if not certification_audit["relevant"]:
                    continue
                certification_audits.append(certification_audit)
                source_supports = certification_audit["supported"]
                conflict_reason = certification_audit["reason"]
            elif claim["category"] == "qualification_assertion":
                source_has_claim = _source_supports_claim(source, claim)
                if source_has_claim:
                    subject_audit = {
                        "subject_check": _enterprise_subject_check(
                            source,
                            bidder_identity,
                        )
                    }
                    subject_audits.append(subject_audit)
                    source_supports = (
                        subject_audit["subject_check"]["status"] == "matched"
                    )
                    conflict_reason = (
                        ""
                        if source_supports
                        else subject_audit["subject_check"]["reason"]
                    )
                else:
                    source_supports = False
                    conflict_reason = _source_conflict_reason(source, claim)
            elif _requires_business_subject_check(claim):
                source_has_claim = _source_supports_claim(source, claim)
                if source_has_claim:
                    subject_audit = {
                        "subject_check": _business_subject_check(
                            source,
                            bidder_identity,
                        )
                    }
                    subject_audits.append(subject_audit)
                    source_supports = (
                        subject_audit["subject_check"]["status"] == "matched"
                    )
                    conflict_reason = (
                        ""
                        if source_supports
                        else subject_audit["subject_check"]["reason"]
                    )
                else:
                    source_supports = False
                    conflict_reason = _source_conflict_reason(source, claim)
            else:
                source_supports = _source_supports_claim(source, claim)
                conflict_reason = _source_conflict_reason(source, claim)

            if not source_supports:
                if conflict_reason:
                    rejected = {
                        "source_id": source["source_id"],
                        "source_type": source["source_type"],
                        "title": source.get("title", ""),
                        "reason": conflict_reason,
                    }
                    if certification_audit:
                        rejected.update(
                            {
                                "standard_check": certification_audit[
                                    "standard_check"
                                ],
                                "subject_check": certification_audit["subject_check"],
                            }
                        )
                    if subject_audit:
                        rejected["subject_check"] = subject_audit["subject_check"]
                    rejected_sources.append(rejected)
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
            if certification_audit:
                evidence.update(
                    {
                        "standard_check": certification_audit["standard_check"],
                        "subject_check": certification_audit["subject_check"],
                    }
                )
            if subject_audit:
                evidence["subject_check"] = subject_audit["subject_check"]
            if usable:
                matched_sources.append(evidence)
                if source["source_type"] == "material":
                    supported_material_ids.add(source["source_id"])
                    if source["source_id"] in reported_evidence:
                        mapped_reported_ids.add(source["source_id"])
            else:
                rejected_sources.append({**evidence, "reason": reason})

        if matched_sources:
            audit_fields = (
                _claim_certification_audit(
                    claim,
                    certification_audits,
                    bidder_identity,
                )
                if claim["category"] == "certification"
                else (
                    {
                        "subject_check": _claim_generic_subject_audit(
                            subject_audits,
                            bidder_identity,
                        )
                    }
                    if claim["category"] == "qualification_assertion"
                    else (
                        {
                            "subject_check": _claim_business_subject_audit(
                                subject_audits,
                                bidder_identity,
                            )
                        }
                        if _requires_business_subject_check(claim)
                        else {}
                    )
                )
            )
            claim_mapping.append(
                {
                    **claim,
                    **audit_fields,
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
        elif claim["category"] == "certification":
            reason = _certification_failure_reason(certification_audits)
        elif tender_statement and _matching_tender_sources(claim, section_context):
            reason = (
                "招标要求只能证明采购方提出了要求，不能证明企业已具备"
                "资质、履历或已批准承诺。"
            )
        business_subject_check = (
            _claim_business_subject_audit(subject_audits, bidder_identity)
            if _requires_business_subject_check(claim) and subject_audits
            else {}
        )
        if business_subject_check:
            if business_subject_check["status"] in {"missing", "unknown"}:
                status = "needs_review"
                reason = business_subject_check["reason"]
            elif business_subject_check["status"] == "conflict":
                reason = business_subject_check["reason"]
        audit_fields = (
            _claim_certification_audit(
                claim,
                certification_audits,
                bidder_identity,
            )
            if claim["category"] == "certification"
            else (
                {
                    "subject_check": _claim_generic_subject_audit(
                        subject_audits,
                        bidder_identity,
                    )
                }
                if claim["category"] == "qualification_assertion"
                else (
                    {"subject_check": business_subject_check}
                    if business_subject_check
                    else {}
                )
            )
        )
        claim_mapping.append(
            {
                **claim,
                **audit_fields,
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
        "claim_verification": _claim_verification_result(
            content,
            claim_mapping,
            coverage,
        ),
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
            standard = _standard_identity(
                "ISO",
                match.group("number"),
                match.group("edition"),
                iec=bool(match.group("iec")),
            )
            candidates.append(
                (
                    "certification",
                    {
                        "standard": standard["canonical_id"],
                        "asserted_standard": standard,
                        "polarity": _claim_polarity(sentence),
                    },
                )
            )
        for match in _OTHER_CERT_RE.finditer(sentence):
            standard = _standard_identity(
                match.group("family").upper(),
                match.group("level"),
            )
            candidates.append(
                (
                    "certification",
                    {
                        "standard": standard["canonical_id"],
                        "asserted_standard": standard,
                        "polarity": _claim_polarity(sentence),
                    },
                )
            )

        if _PMP_RE.search(sentence):
            candidates.append(
                (
                    "personnel_qualification",
                    {
                        "qualification": "PMP",
                        "person": _PERSON_NAME_RE.findall(sentence),
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
            if re.search(
                r"(?<![A-Za-z0-9-])(?:ISO|CMMI|ITSS)(?![A-Za-z0-9])",
                sentence,
                re.IGNORECASE,
            ):
                candidates.append(
                    (
                        "unclassified_high_risk_assertion",
                        {
                            "scan_status": "partial",
                            "polarity": _claim_polarity(sentence),
                        },
                    )
                )
            else:
                phrase = _QUALIFICATION_PHRASE_RE.search(sentence)
                candidates.append(
                    (
                        "qualification_assertion",
                        {
                            "credential": (
                                phrase.group(1)
                                if phrase
                                else _normalize_compact(sentence)
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
                role = _date_role(sentence)
                candidates.append(
                    (
                        "date",
                        {
                            "date": (
                                f"{int(match.group(1)):04d}-{month:02d}"
                                if day is None
                                else f"{int(match.group(1)):04d}-{month:02d}-{day:02d}"
                            ),
                            "role": role,
                            "role_ambiguous": role is None,
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

        categories = {category for category, _ in candidates}
        if _has_unclassified_company_risk(sentence, categories):
            candidates.append(
                (
                    "unclassified_high_risk_assertion",
                    {
                        "scan_status": "partial",
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


def _has_unclassified_company_risk(
    sentence: str,
    recognized_categories: set[str],
) -> bool:
    if not _UNCLASSIFIED_COMPANY_RISK_RE.search(sentence):
        return False
    if not _is_company_assertion(sentence):
        return False
    if re.search(
        r"(?<![A-Za-z0-9-])(?:ISO|CMMI|ITSS)(?![A-Za-z0-9])",
        sentence,
        re.IGNORECASE,
    ) and "certification" not in recognized_categories:
        return True
    if (
        re.search(r"资质|资格|证书|证照|认证", sentence)
        and not recognized_categories.intersection(
            {"certification", "personnel_qualification", "qualification_assertion"}
        )
    ):
        return True
    if re.search(r"项目|合同|案例|业绩|客户|经验", sentence):
        has_quantity_marker = bool(
            re.search(
                r"(?:\d|[零〇一二两三四五六七八九十百千万]|数十|数百|数千|"
                r"几十|几百|几千|多个|若干|多项|众多)",
                sentence,
            )
        )
        if has_quantity_marker and "case_quantity" not in recognized_categories:
            return True
        if not recognized_categories:
            return True
    return not recognized_categories


def _claim_scan_coverage(
    content: str,
    claims: list[dict[str, Any]],
) -> dict[str, Any]:
    sentence_count = len(_sentences(content))
    recognized = [
        claim
        for claim in claims
        if claim["category"] != "unclassified_high_risk_assertion"
    ]
    unclassified = [
        claim
        for claim in claims
        if claim["category"] == "unclassified_high_risk_assertion"
    ]
    recognized_patterns = {claim["category"] for claim in recognized}
    if unclassified:
        recognized_patterns.add("unclassified_high_risk_assertion")
    status = (
        "not_scanned"
        if not str(content or "").strip()
        else "partial"
        if unclassified
        else "complete"
    )
    return {
        "status": status,
        "scanned_sentence_count": sentence_count,
        "recognized_claim_count": len(recognized),
        "unclassified_high_risk_claim_count": len(unclassified),
        "unclassified_high_risk_snippets": list(
            dict.fromkeys(claim["claim_text"] for claim in unclassified)
        ),
        "recognized_patterns": sorted(recognized_patterns),
        "scanner": "selected_high_risk_patterns_v2",
    }


def _claim_verification_result(
    content: str,
    claims: list[dict[str, Any]],
    coverage: Mapping[str, Any],
) -> dict[str, Any]:
    detected_count = len(claims)
    supported_count = sum(claim.get("status") == "supported" for claim in claims)
    unsupported_count = detected_count - supported_count
    if coverage.get("status") == "not_scanned":
        status = "not_checked"
    elif coverage.get("status") != "complete" or unsupported_count:
        status = "needs_review"
    elif detected_count == 0:
        status = "no_claims_detected"
    else:
        status = "verified"
    return {
        "status": status,
        "detected_claim_count": detected_count,
        "supported_claim_count": supported_count,
        "unsupported_claim_count": unsupported_count,
        "coverage": dict(coverage),
        "interpretation": (
            "模式扫描未发现声明不等于对正文事实作出验证；扫描范围是已实现的有限高风险模式。"
            if detected_count == 0
            else "本结果仅反映已识别的声明及未分类高风险片段。"
        ),
    }


def _claim_certification_audit(
    claim: Mapping[str, Any],
    audits: list[dict[str, Any]],
    bidder_identity: Mapping[str, Any],
) -> dict[str, Any]:
    expected = claim.get("markers", {}).get("asserted_standard", {})
    if not isinstance(expected, Mapping):
        expected = {}
    standard_audits = [
        audit.get("standard_check")
        for audit in audits
        if isinstance(audit.get("standard_check"), Mapping)
    ]
    subject_audits = [
        audit.get("subject_check")
        for audit in audits
        if isinstance(audit.get("subject_check"), Mapping)
    ]
    standard_check = _select_audit(standard_audits)
    subject_check = _select_audit(subject_audits)
    if not standard_check:
        standard_check = {
            "status": "unknown",
            "expected": _standard_display(expected),
            "structured": [],
            "body": [],
            "observed": [],
            "reason": "未找到可核对的认证标准证据。",
        }
    if not subject_check:
        subject_check = _enterprise_subject_check(
            {"row": {}},
            bidder_identity,
        )
    return {
        "asserted_standard": dict(expected),
        "standard_check": standard_check,
        "subject_check": subject_check,
    }


def _claim_generic_subject_audit(
    audits: list[dict[str, Any]],
    bidder_identity: Mapping[str, Any],
) -> dict[str, Any]:
    subject_audits = [
        audit["subject_check"]
        for audit in audits
        if isinstance(audit.get("subject_check"), Mapping)
    ]
    chosen = _select_audit(subject_audits)
    if chosen:
        return chosen
    return _enterprise_subject_check({"row": {}}, bidder_identity)


def _claim_business_subject_audit(
    audits: list[dict[str, Any]],
    bidder_identity: Mapping[str, Any],
) -> dict[str, Any]:
    subject_audits = [
        audit["subject_check"]
        for audit in audits
        if isinstance(audit.get("subject_check"), Mapping)
    ]
    chosen = _select_audit(subject_audits)
    if chosen:
        return chosen
    return _business_subject_check({"row": {}}, bidder_identity)


def _select_audit(audits: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not audits:
        return {}
    for status in ("matched", "conflict", "mismatch", "missing", "unknown"):
        for audit in audits:
            if audit.get("status") == status:
                return dict(audit)
    return dict(audits[0])


def _certification_failure_reason(audits: list[dict[str, Any]]) -> str:
    for audit in audits:
        reason = str(audit.get("reason") or "")
        if reason:
            return reason
    return "未找到能够核对完整认证标准和企业持证主体的来源。"


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


def _standard_identity(
    family: str,
    value: Any = None,
    edition: Any = None,
    *,
    iec: bool = False,
) -> dict[str, Any]:
    normalized_family = str(family or "").strip().upper()
    if normalized_family == "ISO":
        number = re.sub(r"\D", "", str(value or ""))
        if not number:
            return {}
        normalized_edition = re.sub(r"\D", "", str(edition or "")) or None
        iso_iec = iec or number in _ISO_IEC_ALIAS_NUMBERS
        display_family = "ISO/IEC" if iso_iec else "ISO"
        canonical_family = "iso/iec" if iso_iec else "iso"
        identifier = f"{display_family} {number}"
        if normalized_edition:
            identifier = f"{identifier}:{normalized_edition}"
        return {
            "type": display_family,
            "id": identifier,
            "canonical_id": f"{canonical_family}:{number}",
            "edition": normalized_edition,
        }
    if normalized_family in {"CMMI", "ITSS"}:
        level = re.sub(r"\D", "", str(value or "")) or None
        identifier = normalized_family + (f" Level {level}" if level else "")
        return {
            "type": normalized_family,
            "id": identifier,
            "canonical_id": normalized_family.casefold()
            + (f":{level}" if level else ""),
            "level": level,
        }
    return {}


def _standard_from_text(text: str) -> list[dict[str, Any]]:
    scrubbed = _CERTIFICATE_NUMBER_LABEL_RE.sub(" ", str(text or ""))
    standards: list[dict[str, Any]] = []
    for match in _ISO_RE.finditer(scrubbed):
        standards.append(
            _standard_identity(
                "ISO",
                match.group("number"),
                match.group("edition"),
                iec=bool(match.group("iec")),
            )
        )
    for match in _OTHER_CERT_RE.finditer(scrubbed):
        standards.append(
            _standard_identity(
                match.group("family"),
                match.group("level"),
            )
        )
    return _unique_standards(standards)


def _typed_standard_values(
    row: Mapping[str, Any],
) -> tuple[bool, list[dict[str, Any]]]:
    metadata = row.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    found_field = False
    standards: list[dict[str, Any]] = []
    for container in (row, metadata):
        for key in _CERTIFICATION_STANDARD_FIELDS:
            value = container.get(key)
            if value in (None, ""):
                continue
            found_field = True
            if isinstance(value, Mapping):
                value = (
                    value.get("value")
                    or value.get("text")
                    or value.get("standard")
                    or value.get("certificate_type")
                    or ""
                )
            if isinstance(value, (list, tuple, set)):
                values = list(value)
            else:
                values = [value]
            for item in values:
                if isinstance(item, (str, int, float)):
                    standards.extend(_standard_from_text(str(item)))
    return found_field, _unique_standards(standards)


def _certificate_body_texts(source: Mapping[str, Any]) -> list[str]:
    row = source.get("row")
    if not isinstance(row, Mapping):
        return [str(source.get("text") or "")]
    parts = [
        row.get("material_type"),
        row.get("type"),
        row.get("title"),
        row.get("name"),
        row.get("content"),
        row.get("text"),
    ]
    metadata = row.get("metadata")
    if isinstance(metadata, Mapping):
        parts.extend(
            metadata.get(key)
            for key in (
                "description",
                "extracted_text",
                "ocr_text",
                "certificate_content",
            )
        )
    return [str(part) for part in parts if part not in (None, "")]


def _certification_source_check(
    source: Mapping[str, Any],
    claim: Mapping[str, Any],
    bidder_identity: Mapping[str, Any],
) -> dict[str, Any]:
    row = source.get("row")
    row = row if isinstance(row, Mapping) else {}
    structured_present, structured_standards = _typed_standard_values(row)
    body_texts = _certificate_body_texts(source)
    body_standards = _drop_unspecific_standard_variants(
        _unique_standards(
            standard
            for text in body_texts
            for standard in _standard_from_text(text)
        )
    )
    source_labels = " ".join(
        [
            str(source.get("title") or ""),
            str(row.get("material_type") or ""),
            str(row.get("type") or ""),
        ]
    )
    metadata = row.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    relevant = bool(
        structured_present
        or body_standards
        or re.search(
            r"认证|资质|证书|certificate|ISO|CMMI|ITSS",
            source_labels,
            re.IGNORECASE,
        )
        or metadata.get("certificate_no")
    )
    if not relevant:
        return {"relevant": False}

    expected = claim.get("markers", {}).get("asserted_standard", {})
    if not isinstance(expected, Mapping):
        expected = {}
    standard_status = "unknown"
    standard_reason = "来源未提供可识别的完整认证标准标识。"
    observed = structured_standards or body_standards
    if structured_present and not structured_standards:
        standard_status = "unknown"
        standard_reason = "结构化认证标准字段存在，但未能解析完整标准标识。"
    elif len(structured_standards) > 1 or (
        not structured_standards and len(body_standards) > 1
    ):
        standard_status = "conflict"
        standard_reason = "来源包含多个可能的认证标准，无法唯一确定证书标准。"
    elif structured_standards and body_standards and not _same_standard_sets(
        structured_standards,
        body_standards,
    ):
        standard_status = "conflict"
        standard_reason = "metadata.certificate_type 与证书正文/标题标准相互矛盾。"
    else:
        candidate_standards = _drop_unspecific_standard_variants(
            _unique_standards([*body_standards, *structured_standards])
        )
        if candidate_standards and expected:
            if any(
                _claim_standard_matches(expected, candidate)
                for candidate in candidate_standards
            ) and len(candidate_standards) == 1:
                standard_status = "matched"
                standard_reason = "完整标准类型与标识一致。"
            else:
                standard_status = "mismatch"
                standard_reason = "来源认证标准与正文声明的完整标准标识不一致。"

    subject_check = _enterprise_subject_check(source, bidder_identity)
    polarity_matches = (
        _claim_polarity(_claim_source_text(source))
        == claim.get("markers", {}).get("polarity")
    )
    reason = ""
    if standard_status != "matched":
        reason = standard_reason
    elif subject_check["status"] != "matched":
        reason = str(subject_check["reason"])
    elif not polarity_matches:
        reason = "来源对认证状态的肯定/否定记载与正文相反。"
    return {
        "relevant": True,
        "standard_check": {
            "status": standard_status,
            "expected": _standard_display(expected),
            "structured": [_standard_display(item) for item in structured_standards],
            "body": [_standard_display(item) for item in body_standards],
            "observed": [_standard_display(item) for item in observed],
            "reason": standard_reason,
        },
        "subject_check": subject_check,
        "polarity_matches": polarity_matches,
        "supported": (
            standard_status == "matched"
            and subject_check["status"] == "matched"
            and polarity_matches
        ),
        "reason": reason,
        "source_id": source.get("source_id"),
        "source_type": source.get("source_type"),
        "title": source.get("title", ""),
    }


def _enterprise_subject_check(
    source: Mapping[str, Any],
    bidder_identity: Mapping[str, Any],
) -> dict[str, Any]:
    row = source.get("row")
    row = row if isinstance(row, Mapping) else {}
    metadata = row.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    metadata_holder = _structured_holder_identity(row, metadata)
    body_holders, unassigned_body_ids, excluded_body_ids = _body_holder_identities(
        _certificate_body_texts(source)
    )
    body_holder = _merge_identities(body_holders)
    holder = _merge_identities([metadata_holder, body_holder])
    unassigned_registration_ids = {
        "metadata": list(metadata_holder.get("_unassigned_registration_ids", [])),
        "body": unassigned_body_ids,
    }
    has_unassigned_registration_ids = any(unassigned_registration_ids.values())
    excluded_other_party_ids = sorted(
        set(metadata_holder.get("_excluded_other_party_registration_ids", []))
        | set(excluded_body_ids)
    )
    bidder = _public_identity(bidder_identity)
    metadata_public = _public_identity(metadata_holder)

    if (
        bidder_identity.get("conflict")
        or metadata_holder.get("conflict")
        or body_holder.get("conflict")
        or holder.get("conflict")
        or _identities_conflict(metadata_holder, body_holder)
    ):
        status = "conflict"
        reason = "投标主体或证据中的持证主体字段相互矛盾。"
        matching_basis = None
    elif not bidder.get("names") and not bidder.get("registration_ids"):
        status = "missing"
        reason = "缺少 bidder_profile.bidder_name 或可比较的注册标识。"
        matching_basis = None
    elif not holder.get("names") and not holder.get("registration_ids"):
        status = "missing"
        reason = "证据未提供可核对的企业持证主体。"
        matching_basis = None
    elif has_unassigned_registration_ids:
        status = "unknown"
        reason = "存在无法明确归属到持证主体的登记标识，不能仅凭名称判定一致。"
        matching_basis = None
    else:
        name_match = bool(
            set(bidder_identity.get("_normalized_names", []))
            & set(holder.get("_normalized_names", []))
        )
        id_match = bool(
            set(bidder_identity.get("_normalized_registration_ids", []))
            & set(holder.get("_normalized_registration_ids", []))
        )
        if _identities_conflict(bidder_identity, holder):
            status = "conflict"
            reason = "投标主体与证据持证主体名称或注册标识不一致。"
            matching_basis = None
        elif name_match or id_match:
            status = "matched"
            reason = "投标主体与持证主体通过精确名称或注册标识匹配。"
            matching_basis = (
                "registration_id" if id_match else "exact_legal_name"
            )
        else:
            status = "unknown"
            reason = "投标主体与持证主体没有可精确比较的共同身份字段。"
            matching_basis = None

    return {
        "status": status,
        "bidder": bidder,
        "holder": _public_identity(holder),
        "metadata_holder": metadata_public,
        "body_holders": [_public_identity(item) for item in body_holders],
        "unassigned_registration_ids": unassigned_registration_ids,
        "excluded_other_party_registration_ids": excluded_other_party_ids,
        "matching_basis": matching_basis,
        "reason": reason,
    }


def _business_subject_check(
    source: Mapping[str, Any],
    bidder_identity: Mapping[str, Any],
) -> dict[str, Any]:
    row_layers = _business_source_row_layers(source)
    metadata_owner, unassigned_metadata_ids, excluded_metadata_ids = (
        _business_metadata_owner_identity(row_layers)
    )
    title_texts = [str(source.get("title") or "")]
    body_texts: list[str] = []
    for row in row_layers:
        for key in ("title", "name"):
            value = row.get(key)
            if value not in (None, ""):
                title_texts.append(str(value))
        for key in ("content", "text", "claim", "fact", "value"):
            value = row.get(key)
            if value not in (None, ""):
                body_texts.append(str(value))

    title_owners = _business_text_owner_identities(title_texts)
    body_label_owners, unassigned_body_ids, excluded_body_ids = (
        _body_holder_identities(
            body_texts,
            holder_label_re=_BUSINESS_OWNER_LABEL_RE,
        )
    )
    body_prefix_owners = _business_text_owner_identities(
        body_texts,
        include_labels=False,
    )
    body_owners = [*body_label_owners, *body_prefix_owners]
    title_owner = _merge_identities(title_owners)
    body_owner = _merge_identities(body_owners)
    document_owner = _merge_identities([title_owner, body_owner])
    evidence_owner = _merge_identities([metadata_owner, document_owner])
    bidder = _public_identity(bidder_identity)
    unassigned_registration_ids = {
        "metadata": unassigned_metadata_ids,
        "body": unassigned_body_ids,
    }
    excluded_other_party_ids = sorted(
        set(excluded_metadata_ids) | set(excluded_body_ids)
    )

    source_identity_conflict = bool(
        metadata_owner.get("conflict")
        or title_owner.get("conflict")
        or body_owner.get("conflict")
        or evidence_owner.get("conflict")
        or _identities_conflict(metadata_owner, document_owner)
        or _identities_conflict(title_owner, body_owner)
    )
    if source_identity_conflict or bidder_identity.get("conflict"):
        status = "conflict"
        reason = "数值证据的metadata、标题或正文主体相互矛盾。"
        matching_basis = None
    elif not bidder.get("names") and not bidder.get("registration_ids"):
        status = "missing"
        reason = "缺少可核对的投标主体身份。"
        matching_basis = None
    elif any(unassigned_registration_ids.values()):
        status = "unknown"
        reason = "存在无法明确归属到企业主体的登记标识，不能仅凭名称判定一致。"
        matching_basis = None
    elif not evidence_owner.get("names") and not evidence_owner.get(
        "registration_ids"
    ):
        status = "missing"
        reason = "数值证据没有明确的企业归属主体。"
        matching_basis = None
    elif _identities_conflict(bidder_identity, evidence_owner):
        status = "conflict"
        reason = "数值证据归属主体与投标主体不一致。"
        matching_basis = None
    else:
        name_match = bool(
            set(bidder_identity.get("_normalized_names", []))
            & set(evidence_owner.get("_normalized_names", []))
        )
        id_match = bool(
            set(bidder_identity.get("_normalized_registration_ids", []))
            & set(evidence_owner.get("_normalized_registration_ids", []))
        )
        if name_match or id_match:
            status = "matched"
            reason = "数值证据归属主体与投标主体通过精确名称或注册标识匹配。"
            matching_basis = "registration_id" if id_match else "exact_legal_name"
        else:
            status = "unknown"
            reason = "数值证据归属主体与投标主体没有可精确比较的共同身份字段。"
            matching_basis = None

    return {
        "status": status,
        "bidder": bidder,
        "metadata_owner": _public_identity(metadata_owner),
        "title_owners": [_public_identity(item) for item in title_owners],
        "body_owners": [_public_identity(item) for item in body_owners],
        "evidence_owner": _public_identity(evidence_owner),
        "unassigned_registration_ids": unassigned_registration_ids,
        "excluded_other_party_registration_ids": excluded_other_party_ids,
        "matching_basis": matching_basis,
        "reason": reason,
    }


def _business_source_row_layers(source: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    layers: list[Mapping[str, Any]] = []
    row = source.get("row")
    while isinstance(row, Mapping):
        if any(row is existing for existing in layers):
            break
        layers.append(row)
        row = row.get("row")
    return layers


def _business_metadata_owner_identity(
    row_layers: list[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[str], list[str]]:
    identities: list[dict[str, Any]] = []
    unassigned_registration_ids: list[str] = []
    excluded_registration_ids: list[str] = []
    owner_name_targets = {
        "owner_name": "holder_name",
        "business_owner": "certificate_holder_name",
        "evidence_owner": "certification_holder",
        "subject_owner": "subject_name",
    }
    owner_id_targets = {
        "owner_registration_id": "holder_registration_id",
        "owner_credit_code": "holder_credit_code",
        "owner_unified_social_credit_code": "holder_unified_social_credit_code",
    }
    for row in row_layers:
        metadata = row.get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        projected_row: dict[str, Any] = {}
        identity_metadata_fields = (
            *_ISSUER_FIELDS,
            *_ISSUER_REGISTRATION_ID_FIELDS,
            *_FLAT_METADATA_HOLDER_ID_FIELDS,
        )
        projected_metadata = {
            key: metadata[key]
            for key in identity_metadata_fields
            if key in metadata
        }

        for key, target in owner_name_targets.items():
            if row.get(key) not in (None, ""):
                projected_row[target] = row[key]
            if metadata.get(key) not in (None, ""):
                projected_metadata[target] = metadata[key]
        for key, target in owner_id_targets.items():
            if row.get(key) not in (None, ""):
                projected_row[target] = row[key]
            if metadata.get(key) not in (None, ""):
                projected_metadata[target] = metadata[key]

        explicit_row_owner = any(
            _identity_from_mapping(value).get("names")
            if isinstance(value, Mapping)
            else _normalize_entity_name(value)
            for key in owner_name_targets
            if (value := row.get(key)) not in (None, "")
        )
        row_flat_ids = [
            row.get(key)
            for key in _FLAT_METADATA_HOLDER_ID_FIELDS
            if row.get(key) not in (None, "")
        ]
        holder = _structured_holder_identity(projected_row, projected_metadata)
        if row_flat_ids and explicit_row_owner and not _has_issuer_identity(metadata):
            holder = _merge_identities(
                [holder, _make_identity([], row_flat_ids)]
            )
        elif row_flat_ids:
            unassigned_registration_ids.extend(row_flat_ids)

        identities.append(holder)
        unassigned_registration_ids.extend(
            holder.get("_unassigned_registration_ids", [])
        )
        excluded_registration_ids.extend(
            holder.get("_excluded_other_party_registration_ids", [])
        )

    return (
        _merge_identities(identities),
        _normalized_registration_ids(unassigned_registration_ids),
        _normalized_registration_ids(excluded_registration_ids),
    )


def _business_text_owner_identities(
    texts: list[str],
    *,
    include_labels: bool = True,
) -> list[dict[str, Any]]:
    identities: list[dict[str, Any]] = []
    for text in dict.fromkeys(value.strip() for value in texts if value.strip()):
        if include_labels:
            for match in _BUSINESS_OWNER_LABEL_RE.finditer(text):
                identities.append(_make_identity([match.group("holder")], []))
        prefix_match = _BUSINESS_ENTITY_PREFIX_RE.match(text)
        if prefix_match:
            identities.append(_make_identity([prefix_match.group("owner")], []))

    unique: dict[tuple[tuple[str, ...], tuple[str, ...]], dict[str, Any]] = {}
    for identity in identities:
        key = (
            tuple(identity.get("_normalized_names", [])),
            tuple(identity.get("_normalized_registration_ids", [])),
        )
        if key != ((), ()):
            unique.setdefault(key, identity)
    return list(unique.values())


def _bidder_identity(payload: Mapping[str, Any]) -> dict[str, Any]:
    profile = payload.get("bidder_profile")
    profile = profile if isinstance(profile, Mapping) else {}
    attributes = profile.get("attributes")
    attributes = attributes if isinstance(attributes, Mapping) else {}
    names = [
        profile.get(key)
        for key in _BIDDER_NAME_FIELDS
        if profile.get(key) not in (None, "")
    ]
    registration_ids = [
        container.get(key)
        for container in (profile, attributes)
        for key in _REGISTRATION_ID_FIELDS
        if container.get(key) not in (None, "")
    ]
    return _make_identity(names, registration_ids)


def _structured_holder_identity(
    row: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    identities: list[dict[str, Any]] = []
    explicit_holder_name = False
    for container in (row, metadata):
        for key in _HOLDER_NAME_FIELDS:
            value = container.get(key)
            if value in (None, ""):
                continue
            if isinstance(value, Mapping):
                identity = _identity_from_mapping(value)
                explicit_holder_name = explicit_holder_name or bool(
                    identity.get("names")
                )
                identities.append(identity)
            elif isinstance(value, (str, int)):
                identity = _make_identity([str(value)], [])
                explicit_holder_name = explicit_holder_name or bool(
                    identity.get("names")
                )
                identities.append(identity)

    holder_registration_ids = [
        container.get(key)
        for container in (row, metadata)
        for key in (
            "holder_registration_id",
            "holder_credit_code",
            "holder_unified_social_credit_code",
        )
        if container.get(key) not in (None, "")
    ]
    flat_registration_ids = [
        metadata.get(key)
        for key in _FLAT_METADATA_HOLDER_ID_FIELDS
        if metadata.get(key) not in (None, "")
    ]
    issuer_ambiguity = _has_issuer_identity(metadata)
    unassigned_registration_ids: list[Any] = []
    if flat_registration_ids and explicit_holder_name and not issuer_ambiguity:
        holder_registration_ids.extend(flat_registration_ids)
    else:
        unassigned_registration_ids.extend(flat_registration_ids)

    if holder_registration_ids:
        identities.append(_make_identity([], holder_registration_ids))
    result = _merge_identities(identities)
    result["_unassigned_registration_ids"] = _normalized_registration_ids(
        unassigned_registration_ids
    )
    result["_excluded_other_party_registration_ids"] = _normalized_registration_ids(
        [
            metadata.get(key)
            for key in _ISSUER_REGISTRATION_ID_FIELDS
            if metadata.get(key) not in (None, "")
        ]
    )
    return result


def _identity_from_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    names = [
        value.get(key)
        for key in (
            "name",
            "holder_name",
            "bidder_name",
            "company_name",
            "enterprise_name",
            "organization_name",
            "legal_name",
        )
        if value.get(key) not in (None, "")
    ]
    registration_ids = [
        value.get(key)
        for key in _REGISTRATION_ID_FIELDS
        if value.get(key) not in (None, "")
    ]
    return _make_identity(names, registration_ids)


def _body_holder_identities(
    texts: list[str],
    *,
    holder_label_re: re.Pattern[str] = _HOLDER_LABEL_RE,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    identities: list[dict[str, Any]] = []
    unassigned_registration_ids: list[str] = []
    excluded_other_party_ids: list[str] = []
    for text in texts:
        holders = list(holder_label_re.finditer(text))
        holder_registration_ids: list[list[str]] = [[] for _ in holders]
        issuer_labels = list(_ISSUER_CONTEXT_RE.finditer(text))
        for registration_match in _EXPLICIT_REGISTRATION_ID_RE.finditer(text):
            registration_id = registration_match.group(1)
            preceding_holders = [
                (index, holder)
                for index, holder in enumerate(holders)
                if holder.end() <= registration_match.start()
            ]
            previous_holder_end = (
                preceding_holders[-1][1].end() if preceding_holders else -1
            )
            issuer_after_holder = any(
                previous_holder_end <= label.start() < registration_match.start()
                for label in issuer_labels
            )
            if issuer_after_holder:
                excluded_other_party_ids.append(
                    _normalize_registration_id(registration_id)
                )
                continue

            if preceding_holders:
                holder_index, holder = preceding_holders[-1]
                between = text[holder.end() : registration_match.start()]
                if (
                    len(between) <= 16
                    and re.fullmatch(r"[\s。.!！?？；;，,:：、]*", between)
                ):
                    holder_registration_ids[holder_index].append(registration_id)
                    continue

            unassigned_registration_ids.append(
                _normalize_registration_id(registration_id)
            )

        identities.extend(
            _make_identity([match.group("holder").strip()], registration_ids)
            for match, registration_ids in zip(holders, holder_registration_ids)
        )

    return (
        identities,
        sorted(set(unassigned_registration_ids)),
        sorted(set(excluded_other_party_ids)),
    )


def _has_issuer_identity(metadata: Mapping[str, Any]) -> bool:
    return any(metadata.get(key) not in (None, "") for key in _ISSUER_FIELDS)


def _normalized_registration_ids(values: list[Any]) -> list[str]:
    return sorted(
        {
            normalized
            for value in values
            if (normalized := _normalize_registration_id(value))
        }
    )


def _make_identity(names: Any, registration_ids: Any) -> dict[str, Any]:
    unique_names: dict[str, str] = {}
    for value in names if isinstance(names, (list, tuple, set)) else [names]:
        if isinstance(value, Mapping):
            value = value.get("name") or value.get("value") or ""
        normalized = _normalize_entity_name(value)
        if normalized:
            unique_names.setdefault(normalized, str(value).strip())
    unique_ids = {
        _normalize_registration_id(value)
        for value in (
            registration_ids
            if isinstance(registration_ids, (list, tuple, set))
            else [registration_ids]
        )
        if _normalize_registration_id(value)
    }
    return {
        "names": sorted(unique_names.values()),
        "registration_ids": sorted(unique_ids),
        "_normalized_names": sorted(unique_names),
        "_normalized_registration_ids": sorted(unique_ids),
        "conflict": len(unique_names) > 1 or len(unique_ids) > 1,
    }


def _merge_identities(identities: list[Mapping[str, Any]]) -> dict[str, Any]:
    names = [name for identity in identities for name in identity.get("names", [])]
    registration_ids = [
        identifier
        for identity in identities
        for identifier in identity.get("registration_ids", [])
    ]
    merged = _make_identity(names, registration_ids)
    merged["conflict"] = merged["conflict"] or any(
        bool(identity.get("conflict")) for identity in identities
    )
    return merged


def _public_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "names": list(identity.get("names", [])),
        "registration_ids": list(identity.get("registration_ids", [])),
    }


def _identities_conflict(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> bool:
    left_names = set(left.get("_normalized_names", []))
    right_names = set(right.get("_normalized_names", []))
    left_ids = set(left.get("_normalized_registration_ids", []))
    right_ids = set(right.get("_normalized_registration_ids", []))
    return bool(
        (left_names and right_names and not left_names.intersection(right_names))
        or (left_ids and right_ids and not left_ids.intersection(right_ids))
    )


def _normalize_entity_name(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"\s+", "", text)
    if normalized in {"本公司", "本企业", "本单位", "我方", "我司", "投标人"}:
        return ""
    return normalized


def _normalize_registration_id(value: Any) -> str:
    return re.sub(
        r"[^A-Za-z0-9]+",
        "",
        unicodedata.normalize("NFKC", str(value or "")),
    ).upper()


def _unique_standards(values: Any) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str | None], dict[str, Any]] = {}
    for value in values:
        if not isinstance(value, Mapping) or not value.get("canonical_id"):
            continue
        key = (str(value["canonical_id"]), value.get("edition"))
        unique.setdefault(key, dict(value))
    return [
        unique[key]
        for key in sorted(unique, key=lambda item: (item[0], item[1] or ""))
    ]


def _drop_unspecific_standard_variants(
    standards: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    families_with_levels = {
        str(standard.get("type", "")).upper()
        for standard in standards
        if standard.get("level")
    }
    standards_with_editions = {
        str(standard.get("canonical_id", ""))
        for standard in standards
        if standard.get("edition")
    }
    return [
        standard
        for standard in standards
        if not (
            standard.get("type") in {"CMMI", "ITSS"}
            and not standard.get("level")
            and str(standard.get("type", "")).upper() in families_with_levels
        )
        and not (
            str(standard.get("type", "")).startswith("ISO")
            and not standard.get("edition")
            and str(standard.get("canonical_id", "")) in standards_with_editions
        )
    ]


def _standard_display(value: Mapping[str, Any]) -> str:
    return str(value.get("id") or value.get("canonical_id") or "")


def _standards_equivalent(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return bool(
        left.get("canonical_id") == right.get("canonical_id")
        and not (
            left.get("edition")
            and right.get("edition")
            and left.get("edition") != right.get("edition")
        )
    )


def _claim_standard_matches(
    asserted: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> bool:
    return bool(
        _standards_equivalent(asserted, evidence)
        and (
            not asserted.get("edition")
            or asserted.get("edition") == evidence.get("edition")
        )
    )


def _same_standard_sets(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
) -> bool:
    def family_key(standard: Mapping[str, Any]) -> str:
        family = str(standard.get("type", "")).upper()
        if family in {"CMMI", "ITSS"}:
            return family
        return str(standard.get("canonical_id", ""))

    left_groups: dict[str, list[Mapping[str, Any]]] = {}
    right_groups: dict[str, list[Mapping[str, Any]]] = {}
    for standard in left:
        left_groups.setdefault(family_key(standard), []).append(standard)
    for standard in right:
        right_groups.setdefault(family_key(standard), []).append(standard)
    if left_groups.keys() != right_groups.keys():
        return False

    for family, left_items in left_groups.items():
        right_items = right_groups[family]
        qualifier = "level" if family in {"CMMI", "ITSS"} else "edition"
        left_values = {
            str(item[qualifier]) for item in left_items if item.get(qualifier)
        }
        right_values = {
            str(item[qualifier]) for item in right_items if item.get(qualifier)
        }
        if len(left_values) > 1 or len(right_values) > 1:
            return False
        if left_values and right_values and left_values != right_values:
            return False
    return True


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
        audit = _certification_source_check(
            source,
            claim,
            _make_identity([], []),
        )
        return bool(
            audit.get("relevant")
            and audit.get("standard_check", {}).get("status") == "matched"
            and audit.get("polarity_matches")
        )
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


def _requires_business_subject_check(claim: Mapping[str, Any]) -> bool:
    category = claim.get("category")
    if category == "case_quantity":
        return True
    if category != "amount":
        return False
    role = claim.get("markers", {}).get("role")
    return bool(claim.get("company_assertion")) or role in {
        "contract_amount",
        "project_amount",
        "award_amount",
        "registered_capital",
        "revenue",
    }


def _source_conflict_reason(
    source: Mapping[str, Any],
    claim: Mapping[str, Any],
) -> str:
    text = str(source.get("text") or "")
    category = claim["category"]
    markers = claim["markers"]
    if category == "certification":
        audit = _certification_source_check(
            source,
            claim,
            _make_identity([], []),
        )
        if not audit.get("relevant"):
            return ""
        if audit.get("standard_check", {}).get("status") != "matched":
            return str(audit.get("reason") or "来源标准与声明不匹配。")
        if not audit.get("polarity_matches"):
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
        fact_row = row.get("row")
        if not isinstance(fact_row, Mapping):
            fact_row = row
        return _explicit_fact_usable(fact_row, str(source.get("source_type")))
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
        asserted = markers.get("asserted_standard", {})
        standards = _standard_from_text(text)
        return (
            isinstance(asserted, Mapping)
            and len(standards) == 1
            and _claim_standard_matches(asserted, standards[0])
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
