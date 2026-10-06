"""Small deterministic backends for the local, file-backed demo runtime.

They are deliberately conservative.  A deployment can inject OCR/LLM/parser
backends later, while local runs still preserve the same artifact contracts.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.files import (
    FileRegistryError,
    ProjectFileRegistry,
)
from qiaowenshu_agent.domain.models import SourceReference
from qiaowenshu_agent.skills.local_requirement_logic import (
    build_local_requirement_rule,
)
from qiaowenshu_agent.skills.local_requirement_groups import (
    group_requirement_records,
)


class FileRegistryNotConfigured(RuntimeError):
    """Raised when a local backend has no registry service to read from."""


def resolve_file_registry(
    context: SkillContext,
    configured: ProjectFileRegistry | None = None,
) -> ProjectFileRegistry:
    registry = configured or context.get_service("file_registry")
    if not isinstance(registry, ProjectFileRegistry):
        raise FileRegistryNotConfigured("file registry service is not configured")
    return registry


class RegistryDocumentPreprocessBackend:
    """Create a parse-ready artifact from a registered file."""

    def __init__(self, file_registry: ProjectFileRegistry | None = None) -> None:
        self.file_registry = file_registry

    def run(
        self,
        payload: Mapping[str, Any],
        context: SkillContext,
    ) -> dict[str, Any]:
        registry = resolve_file_registry(context, self.file_registry)
        file_id = str(payload.get("file_id") or "").strip()
        try:
            artifact = registry.parse(
                file_id,
                force=bool(payload.get("force", False)),
            )
        except FileRegistryError as exc:
            return {
                "status": "blocked",
                "error_code": "PREPROCESS_BACKEND_NOT_CONFIGURED",
                "message": str(exc),
            }
        return {
            "preprocess_id": f"prep_{artifact['artifact_id']}",
            "task_id": f"task_{artifact['artifact_id']}",
            "status": "SUCCESS",
            "parse_ready_file_id": file_id,
            "parse_artifact_id": artifact["artifact_id"],
            "artifact": artifact,
            "warnings": list(artifact.get("warnings") or []),
        }


class RegistryTenderIntakeBackend:
    """Build a page-aware tender profile from registered file artifacts."""

    def __init__(self, file_registry: ProjectFileRegistry | None = None) -> None:
        self.file_registry = file_registry

    def run(
        self,
        payload: Mapping[str, Any],
        context: SkillContext,
    ) -> dict[str, Any]:
        registry = resolve_file_registry(context, self.file_registry)
        file_ids = [str(item).strip() for item in payload["file_ids"]]
        artifacts = [registry.parse(file_id) for file_id in file_ids]
        pages: list[dict[str, Any]] = []
        sections: list[dict[str, Any]] = []
        warnings: list[str] = []
        combined_text: list[str] = []
        for artifact in artifacts:
            text = str(artifact.get("text") or "")
            combined_text.append(text)
            warnings.extend(str(item) for item in artifact.get("warnings") or [])
            artifact_pages = _artifact_pages(artifact)
            artifact_references: list[dict[str, Any]] = []
            for page in artifact_pages:
                page_number = int(page.get("page_number") or 1)
                page_text = str(page.get("text") or "")
                references = _page_references(artifact, page)
                artifact_references.extend(references)
                pages.append(
                    {
                        "page_id": f"{artifact['file_id']}-p{page_number}",
                        "file_id": artifact["file_id"],
                        "page_number": page_number,
                        "text": page_text,
                        "page_type": page.get("page_type") or "native_text",
                        "extraction_method": page.get("extraction_method")
                        or "native_text",
                        "confidence": page.get("confidence"),
                        "regions": list(page.get("regions") or []),
                        "warnings": list(page.get("warnings") or []),
                        "source_references": references,
                    }
                )
                warnings.extend(
                    f"{artifact['file_name']}第{page_number}页：{item}"
                    for item in page.get("warnings") or []
                )
            sections.append(
                {
                    "section_id": f"section-{artifact['file_id']}",
                    "title": artifact["file_name"],
                    "kind": _section_kind(artifact["file_name"]),
                    "content": text,
                    "text": text,
                    "source_references": artifact_references,
                }
            )

        text = "\n".join(combined_text)
        project_id = str(payload["project_id"])
        profile = _build_profile(project_id, text, artifacts)
        return {
            "project_id": project_id,
            "profile": profile,
            "sections": sections,
            "pages": pages,
            "artifacts": artifacts,
            "warnings": _unique(warnings),
        }


class RegistryTenderDecompositionBackend:
    """Extract a conservative first-pass requirement set from parsed text."""

    def run(
        self,
        payload: Mapping[str, Any],
        _context: SkillContext,
    ) -> dict[str, Any]:
        explicit_requirements = list(payload.get("requirements") or [])
        explicit_scores = list(payload.get("scoring_items") or [])
        if explicit_requirements or explicit_scores:
            return {
                "requirements": explicit_requirements,
                "scoring_items": explicit_scores,
                "warnings": [],
            }

        sections = payload.get("sections") or []
        text = _sections_text(sections)
        requirements: list[dict[str, Any]] = []
        scoring_items: list[dict[str, Any]] = []
        seen: dict[tuple[str, tuple[tuple[str, str], ...]], int] = {}
        warnings: list[str] = []
        records = group_requirement_records(
            sections,
            _candidate_records(sections),
        )
        for line, source_references, group_rule in records:
            normalized = _normalize(line)
            source_key = tuple(
                sorted(
                    {
                        (
                            str(reference.get("document_id") or ""),
                            str(
                                reference.get("source_version")
                                or reference.get("source_file_version")
                                or ""
                            ),
                        )
                        for reference in source_references
                    }
                )
            )
            duplicate_key = (normalized, source_key)
            score = _score_from_line(line)
            if score is not None and _looks_like_score(line):
                if duplicate_key in seen:
                    existing = scoring_items[seen[duplicate_key]]
                    existing["source_references"] = _merge_source_references(
                        existing["source_references"], source_references
                    )
                    continue
                item_id = f"S-{len(scoring_items) + 1:03d}"
                scoring_items.append(
                    {
                        "item_id": item_id,
                        "title": _title_from_line(line),
                        "max_score": score,
                        "criteria": line,
                        "evidence_required": _evidence_hints(line),
                        "source_references": source_references,
                    }
                )
                seen[duplicate_key] = len(scoring_items) - 1
                continue
            if _looks_like_score(line):
                warnings.append(
                    f"评分上限无法从原文可靠提取，未生成评分项：{line}"
                )
                continue
            category = _category_from_line(line)
            if group_rule is None and not _is_requirement_line(line, category):
                continue
            if duplicate_key in seen:
                existing = requirements[seen[duplicate_key]]
                existing["source_references"] = _merge_source_references(
                    existing["source_references"], source_references
                )
                continue
            requirement_id = f"R-{len(requirements) + 1:03d}"
            requirement = {
                "requirement_id": requirement_id,
                "category": category,
                "title": _title_from_line(line),
                "description": line,
                "mandatory": group_rule is not None
                or category
                in {"disqualification", "qualification", "compliance"}
                or _is_mandatory_clause(line),
                "evidence_required": _evidence_hints(line),
                "source_references": source_references,
            }
            check_rule = group_rule or _check_rule_from_line(line)
            if check_rule:
                requirement["check_rule"] = check_rule
            requirements.append(requirement)
            seen[duplicate_key] = len(requirements) - 1
        clarification_titles = _clarification_titles(sections)
        if clarification_titles:
            warnings.append(
                "检测到更正、澄清或补遗材料；局部解析器不会自动判定"
                "新旧条款的覆盖关系，需人工复核："
                + "、".join(clarification_titles)
            )
        if not text.strip():
            warnings.append(
                "parsed tender artifacts contain no text; OCR or a parser "
                "backend is required"
            )
        elif not requirements and not scoring_items:
            warnings.append(
                "local parser found no atomic requirements; review the parsed artifact"
            )
        result = {
            "requirements": requirements,
            "scoring_items": scoring_items,
            "warnings": warnings,
            "extraction_complete": False,
            "needs_human_review": True,
            "business_status": "needs_review",
        }
        return result


class RegistryBidderMaterialBackend:
    """Classify and extract auditable fields from registered bidder files."""

    def __init__(self, file_registry: ProjectFileRegistry | None = None) -> None:
        self.file_registry = file_registry

    def run(
        self,
        payload: Mapping[str, Any],
        context: SkillContext,
    ) -> dict[str, Any]:
        registry = resolve_file_registry(context, self.file_registry)
        materials: list[dict[str, Any]] = []
        warnings: list[str] = []
        for file_id in payload.get("file_ids") or []:
            record = registry.require(str(file_id))
            artifact = registry.parse(record.file_id)
            text = str(artifact.get("text") or "")
            material_type = record.material_type or _material_type(
                record.file_name,
                text,
            )
            metadata = _material_metadata(material_type, record.file_name, text)
            extraction_warning = metadata.pop("_extraction_warning", "")
            if extraction_warning:
                warnings.append(f"{record.file_name}：{extraction_warning}")
            if _needs_validity_review(text):
                warnings.append(
                    f"{record.file_name}中的材料有效性表述不明确，需人工核验"
                )
            if not text.strip():
                warnings.append(f"{record.file_name}没有可提取文本，需人工核验")
                metadata.setdefault("verification_status", "unknown")
            artifact_pages = _artifact_pages(artifact)
            references = [
                reference
                for page in artifact_pages
                for reference in _page_references(artifact, page)
            ]
            materials.append(
                {
                    "material_id": record.file_id,
                    "material_type": material_type,
                    "title": record.file_name,
                    "content": text,
                    "valid_until": metadata.get("valid_until"),
                    "metadata": metadata,
                    "source_references": references,
                }
            )
        explicit = payload.get("materials") or []
        if explicit:
            materials.extend(
                dict(item) if isinstance(item, Mapping) else item for item in explicit
            )
        bidder_name = str(payload.get("bidder_name") or "").strip()
        if not bidder_name:
            bidder_name = _first_match(
                "\n".join(
                    str(item.get("content") or "")
                    for item in materials
                    if isinstance(item, Mapping)
                ),
                r"(?:企业名称|公司名称|投标人名称|单位名称)\s*[:：]?\s*([^\n\r，,；;。]{2,100})",
            )
        attributes = _bidder_attributes(materials)
        return {
            "bidder_profile": {
                "bidder_id": str(payload["bidder_id"]),
                "bidder_name": bidder_name,
                "attributes": attributes,
                "materials": materials,
            },
            "warnings": _unique(warnings),
        }


def _build_profile(
    project_id: str,
    text: str,
    artifacts: list[Mapping[str, Any]],
) -> dict[str, Any]:
    project_name = _first_match(
        text,
        r"(?:项目名称|项目名|采购项目名称)\s*[:：]?\s*([^\n\r]{2,120})",
    )
    tender_number = _first_match(
        text,
        r"(?:项目编号|招标编号|采购编号)\s*[:：]?\s*([^\n\r\s]{3,80})",
    )
    dates: dict[str, str] = {}
    for key, pattern in {
        "bid_deadline": (
            r"(?:投标截止|递交截止|开标时间)[^\d]{0,20}"
            r"([0-9]{4}[-年/.][0-9]{1,2}[-月/.][0-9]{1,2}"
            r"(?:日)?(?:\s*[0-9]{1,2}:[0-9]{2})?)"
        ),
        "delivery_deadline": (
            r"(?:交付期|工期|服务期限)[^\d]{0,20}"
            r"([0-9]{1,4}\s*(?:日历天|天|个月|月))"
        ),
    }.items():
        value = _first_match(text, pattern)
        if value:
            dates[key] = value
    references = [
        reference
        for artifact in artifacts
        for reference in _artifact_references(artifact)
    ]
    return {
        "project_id": project_id,
        "project_name": project_name,
        "tender_number": tender_number,
        "procurement_scope": _first_match(
            text,
            r"(?:采购内容|项目概况|建设内容|服务内容)\s*[:：]?\s*([^\n\r]{2,240})",
        ),
        "key_dates": dates,
        "attributes": {
            "source_file_ids": [str(artifact["file_id"]) for artifact in artifacts],
            "source_versions": {
                str(artifact["file_id"]): artifact.get("version")
                for artifact in artifacts
            },
        },
        "source_references": references,
    }


def _artifact_pages(artifact: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw_pages = artifact.get("pages")
    if isinstance(raw_pages, (list, tuple)) and raw_pages:
        return [item for item in raw_pages if isinstance(item, Mapping)] or [
            {"page_number": 1, "text": artifact.get("text") or ""}
        ]
    text = str(artifact.get("text") or "")
    page_texts = text.split("\f") if text else [""]
    return [
        {"page_number": page_number, "text": page_text}
        for page_number, page_text in enumerate(page_texts, start=1)
    ]


def _page_references(
    artifact: Mapping[str, Any], page: Mapping[str, Any]
) -> list[dict[str, Any]]:
    raw_references = page.get("source_references")
    if isinstance(raw_references, (list, tuple)):
        references = [
            dict(item) for item in raw_references if isinstance(item, Mapping)
        ]
        if references:
            return references
    page_number = int(page.get("page_number") or 1)
    source_version = str(
        artifact.get("source_file_versions")
        or f"{artifact['file_id']}:v{artifact.get('version') or 1}"
    )
    if isinstance(artifact.get("source_file_versions"), list):
        source_version = str(
            (artifact.get("source_file_versions") or [""])[0]
        )
    return [
        SourceReference(
            document_id=str(artifact["file_id"]),
            page=page_number,
            quote=str(page.get("text") or "")[:240],
            locator=f"{artifact['artifact_id']}:p{page_number}",
            source_version=source_version,
        ).to_dict()
    ]


def _artifact_references(artifact: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        reference
        for page in _artifact_pages(artifact)
        for reference in _page_references(artifact, page)
    ]


def _material_type(file_name: str, text: str) -> str:
    file_name = Path(file_name).name.lower()
    filename_rules = (
        (("投标保证金", "保证金回单", "银行回单", "保函"), "bid_bond"),
        (("营业执照", "法人登记", "统一社会信用代码"), "business_license"),
        (("iso27001", "iso/iec 27001", "信息安全管理体系"), "certification"),
        (("iso9001", "质量管理体系"), "certification"),
        (("项目经理", "项目负责人", "项目管理师"), "personnel_certificate"),
        (("社保", "社会保险"), "social_security"),
        (("审计报告", "财务报告", "资产负债表"), "financial_report"),
        (("授权委托", "授权书"), "authorization"),
        (("验收报告", "验收证明"), "acceptance"),
        (("合同", "合同额", "合同金额"), "contract"),
    )
    for terms, material_type in filename_rules:
        if any(term in file_name for term in terms):
            return material_type

    body_field_rules = (
        (
            r"(?m)^[ \t]*(?:投标保证金(?:金额)?|保证金金额|缴纳金额|"
            r"交易金额|交易状态|付款人|收款人|付款账号|收款账号|回单编号)"
            r"[ \t]*(?:[:：]\s*\S|\s+\S)",
            "bid_bond",
        ),
        (
            r"(?m)^[ \t]*(?:合同金额|合同额|合同编号|项目名称|甲方|乙方|签订日期)"
            r"[ \t]*(?:[:：]\s*\S|\s+\S)",
            "contract",
        ),
    )
    for pattern, material_type in body_field_rules:
        if re.search(pattern, text):
            return material_type

    content_rules = (
        (("营业执照", "法人登记", "统一社会信用代码"), "business_license"),
        (("iso27001", "iso/iec 27001", "信息安全管理体系"), "certification"),
        (("iso9001", "质量管理体系"), "certification"),
        (("项目经理", "项目负责人", "项目管理师"), "personnel_certificate"),
        (("社保", "社会保险"), "social_security"),
        (("审计报告", "财务报告", "资产负债表"), "financial_report"),
        (("授权委托", "授权书"), "authorization"),
        (("验收报告", "验收证明"), "acceptance"),
    )
    lowered_text = text.lower()
    for terms, material_type in content_rules:
        if any(term in lowered_text for term in terms):
            return material_type
    return "other"


def _material_metadata(material_type: str, file_name: str, text: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "verification_status": "unknown",
        "material_type_source": "file_name_and_text_rule",
    }
    holder = _first_match(
        text,
        r"(?:持证人|证书持有人|企业名称|公司名称|投标人名称|乙方|被授权人)\s*[:：]?\s*([^\n\r，,；;。]{2,100})",
    )
    if holder:
        metadata["holder"] = holder
    certificate_type = _first_match(
        text,
        r"(?<![A-Za-z0-9])(ISO\s*(?:/\s*IEC\s*)?"
        r"[0-9]{4,6}(?:\s*[:：]\s*[0-9]{4})?)",
    )
    if certificate_type:
        identifiers = _iso_standard_identifiers(certificate_type)
        metadata["certificate_type"] = (
            identifiers[0]
            if identifiers
            else re.sub(r"\s+", "", certificate_type).upper()
        )
    certificate_no = _first_match(
        text,
        r"(?:证书编号|证书号|编号)\s*[:：]?\s*([A-Za-z0-9\-/]{4,80})",
    )
    if certificate_no:
        metadata["certificate_no"] = certificate_no
    valid_from = _first_match(
        text,
        r"(?:有效期自|生效日期|签发日期)\s*[:：]?\s*([0-9]{4}[-/.年][0-9]{1,2}[-/.月][0-9]{1,2}日?)",
    )
    valid_until = _first_match(
        text,
        r"(?:有效期至|有效截止日期|截止日期)\s*[:：]?\s*([0-9]{4}[-/.年][0-9]{1,2}[-/.月][0-9]{1,2}日?)",
    )
    if valid_from:
        metadata["valid_from"] = _normalize_date(valid_from)
    if valid_until:
        metadata["valid_until"] = _normalize_date(valid_until)
    amount, amount_warning = _extract_labeled_amount(text)
    if amount is not None:
        metadata["amount"] = amount["amount"]
        metadata["amount_currency"] = "CNY"
        metadata["amount_unit"] = "元"
        metadata["amount_original"] = amount["original"]
        metadata["amount_original_unit"] = amount["unit"]
    elif amount_warning:
        metadata["_extraction_warning"] = amount_warning
    status = _explicit_material_status(text)
    if status == "invalid":
        metadata["verification_status"] = "invalid"
        metadata["status"] = "expired" if _contains_any(text, "过期") else "invalid"
    elif status == "verified":
        metadata["verification_status"] = "verified"
        metadata["status"] = "valid"
    if material_type == "contract":
        metadata["project_name"] = _first_match(
            text, r"(?:项目名称|项目名)\s*[:：]?\s*([^\n\r，,；;。]{2,120})"
        )
        metadata["party_a"] = _first_match(
            text, r"(?:甲方|采购人)\s*[:：]?\s*([^\n\r，,；;。]{2,100})"
        )
        metadata["party_b"] = _first_match(
            text, r"(?:乙方|供应商)\s*[:：]?\s*([^\n\r，,；;。]{2,100})"
        )
    if material_type == "bid_bond" and amount is not None:
        metadata["bid_bond_amount"] = amount["amount"]
    return {key: value for key, value in metadata.items() if value not in (None, "")}


def _bidder_attributes(materials: list[dict[str, Any]]) -> dict[str, Any]:
    contracts = [item for item in materials if item.get("material_type") == "contract"]
    bond_amounts = [
        item.get("metadata", {}).get("bid_bond_amount")
        for item in materials
        if item.get("metadata", {}).get("bid_bond_amount") is not None
    ]
    certifications = [
        item.get("metadata", {}).get("certificate_type")
        for item in materials
        if item.get("metadata", {}).get("certificate_type")
    ]
    result: dict[str, Any] = {
        "similar_case_count": len(contracts),
        "certification_types": certifications,
    }
    if bond_amounts:
        parsed_amounts = [
            amount
            for value in bond_amounts
            if (amount := _decimal_or_none(value)) is not None
        ]
        if parsed_amounts:
            result["bid_bond_amount"] = _decimal_text(max(parsed_amounts))
    return result


def _extract_labeled_amount(
    text: str,
) -> tuple[dict[str, str] | None, str]:
    labels = r"(?:合同金额|合同额|项目金额|保证金金额|缴纳金额|交易金额|金额)"
    label_pattern = re.compile(
        rf"(?m)^[ \t]*(?P<label>{labels})[ \t]*(?P<separator>[:：])?"
        r"[ \t]*(?P<value>[^\r\n\f]*)"
    )
    unknown_pattern = (
        r"未提供|未填写|未明确|未披露|暂无|未知|不详|待补|暂缺|"
        r"无(?:此项|具体)?金额|未约定"
    )
    value_prefix = re.compile(
        r"^(?:人民币|RMB|CNY|[¥￥]|[0-9]|[-−﹣－]\s*[0-9]|"
        r"未提供|未填写|未明确|未披露|暂无|未知|不详|待补|暂缺|"
        r"无(?:此项|具体)?金额|未约定)",
        flags=re.IGNORECASE,
    )
    parsed: list[tuple[Decimal, Decimal, str]] = []
    for label_match in label_pattern.finditer(text):
        field = label_match.group("value").strip()
        if not label_match.group("separator") and not value_prefix.match(field):
            continue
        if re.search(unknown_pattern, field):
            return None, "金额字段标记为未提供或未知，需人工核验"
        if re.search(r"[-−﹣－]\s*[0-9]", field):
            return None, "金额字段出现负数，需人工核验"
        amount_match = re.search(
            r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(万元|万|元)(?![年月日])",
            field,
        )
        if amount_match is None:
            return None, "金额字段含数字或单位不完整，需人工核验"
        try:
            original = Decimal(amount_match.group(1).replace(",", ""))
        except (InvalidOperation, ValueError):
            return None, "金额字段无法精确解析，需人工核验"
        unit = amount_match.group(2)
        multiplier = Decimal("10000") if unit in {"万元", "万"} else Decimal("1")
        parsed.append((original * multiplier, original, unit))
    if not parsed:
        return None, ""
    if len({item[0] for item in parsed}) > 1:
        return None, "存在多个不同金额字段，无法可靠确认目标金额，需人工核验"
    amount, original, unit = parsed[0]
    return {
        "amount": _decimal_text(amount),
        "original": _decimal_text(original),
        "unit": unit,
    }, ""


def _explicit_material_status(text: str) -> str:
    if re.search(
        r"(?:本)?(?:回单金额|保证金金额|投标保证金金额)\s*低于\s*"
        r"(?:招标文件|采购文件)\s*要求|"
        r"(?:金额不足|未足额|不足额|低于要求|不符合要求|不满足要求|"
        r"不合格|未通过|无效|作废|撤销|已过期|过期|失效|"
        r"未通过核验)"
        r".{0,16}(?:有效|合格|足额)?",
        text,
    ):
        return "invalid"
    positive_patterns = (
        r"(?:证书|认证|营业执照|登记证明|投标保证金|保证金)"
        r"(?:状态|结果|核验结果)?\s*[:：]?\s*(?:当前)?"
        r"(?:有效|合格|足额)(?!期|性)",
        r"(?:已)?(?:核验|审核|审查)\s*(?:结果)?\s*[:：]?\s*通过",
        r"(?:保证金|缴纳金额|到账).{0,16}(?:足额|全额)(?:到账)?",
    )
    return (
        "verified"
        if any(re.search(pattern, text) for pattern in positive_patterns)
        else "unknown"
    )


def _needs_validity_review(text: str) -> bool:
    return bool(
        re.search(
        r"(?:有效性|是否有效|有效状态|有效期不明|期限不明|状态不明|"
            r"待核验|待审核|不足以证明|无法确认|不能确认|未能确认|尚未核验)",
            text,
        )
    )


def _decimal_or_none(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _normalize_date(value: str) -> str:
    return re.sub(r"[年/.]", "-", value.replace("月", "-").replace("日", ""))


def _sections_text(sections: list[Any]) -> str:
    values: list[str] = []
    for item in sections:
        if isinstance(item, Mapping):
            values.append(str(item.get("content") or item.get("text") or ""))
        else:
            values.append(str(item))
    return "\n".join(values)


def _candidate_lines(text: str) -> list[str]:
    return [
        line
        for line, _references in _candidate_records([{"content": text}])
    ]


def _candidate_records(
    sections: list[Any],
) -> list[tuple[str, list[dict[str, Any]]]]:
    records: list[tuple[str, list[dict[str, Any]]]] = []
    for section in sections:
        section_records: list[tuple[str, list[dict[str, Any]]]] = []
        if isinstance(section, Mapping):
            content = str(section.get("content") or section.get("text") or "")
            raw_references = section.get("source_references") or []
        else:
            content = str(section)
            raw_references = []

        references_by_page: dict[int, list[dict[str, Any]]] = {}
        if isinstance(raw_references, (list, tuple)):
            for reference in raw_references:
                if not isinstance(reference, Mapping):
                    continue
                try:
                    page_number = int(reference.get("page") or 1)
                except (TypeError, ValueError):
                    page_number = 1
                references_by_page.setdefault(page_number, []).append(
                    dict(reference)
                )

        for page_number, page_text in enumerate(content.split("\f"), start=1):
            page_references = references_by_page.get(page_number, [])
            for line_number, raw_line in enumerate(page_text.splitlines(), start=1):
                if _is_heading_line(re.sub(r"\s+", " ", raw_line).strip()):
                    continue
                line = _clean_candidate_line(raw_line)
                if not line or _is_noise(line) or _is_layout_noise(line):
                    continue
                line_references = _line_source_references(
                    page_references,
                    raw_line,
                    page_number,
                    line_number,
                )
                if section_records and _should_join_lines(section_records[-1][0], line):
                    previous, previous_references = section_records[-1]
                    section_records[-1] = (
                        f"{previous} {line}",
                        _merge_source_references(
                            previous_references, line_references
                        ),
                    )
                else:
                    section_records.append((line, line_references))
        records.extend(section_records)

    return [
        (line, references)
        for line, references in records
        if 6 <= len(line) <= 500 and not _is_noise(line)
    ]


def _clarification_titles(sections: list[Any]) -> list[str]:
    titles: list[str] = []
    for section in sections:
        if not isinstance(section, Mapping):
            continue
        title = str(section.get("title") or "")
        kind = str(section.get("kind") or "").lower()
        if kind in {"clarification", "correction", "addendum"} or _contains_any(
            title, "更正", "澄清", "补遗"
        ):
            titles.append(title or "更正/澄清/补遗材料")
    return _unique(titles)


def _clean_candidate_line(raw_line: str) -> str:
    line = re.sub(
        r"^[\s\-•●▪★一二三四五六七八九十、.()（）]+",
        "",
        raw_line,
    ).strip()
    return re.sub(r"\s+", " ", line)


def _should_join_lines(previous: str, current: str) -> bool:
    if not previous or not current or re.search(r"[。；;!?！？]$", previous):
        return False
    if previous.endswith(
        (
            "的",
            "及",
            "与",
            "和",
            "应",
            "须",
            "得",
            "为",
            "最高",
            "满分",
            "累计",
            "不超过",
        )
    ):
        return True
    if re.search(r"(?:得|计)\s*\d+(?:\.\d+)?$", previous) and current.startswith("分"):
        return True
    if current.startswith(
        (
            "对接",
            "及以上",
            "天",
            "万元",
            "兼容",
            "社会保险",
            "月份",
            "月社会保险",
            "证明",
            "材料",
        )
    ):
        return True
    if re.search(
        r"(?:OAuth2\.?0|OIDC|TLS1\.?2|PostgreSQL|Linux|"
        r"\d{4}\s*年\s*\d+\s*月\s*至)$",
        previous,
        flags=re.IGNORECASE,
    ):
        return True
    if re.match(r"^(?:最高|满分|累计|不超过|上限|无上限|不封顶)", current):
        return _looks_like_score(previous) or _contains_any(
            previous, "合同", "每项", "每个", "得", "计", "评分", "得分"
        )
    if re.match(r"^\d+(?:\.\d+)?\s*分", current):
        return previous.endswith(("最高", "满分", "累计", "不超过", "上限")) or (
            _looks_like_score(previous)
            and _contains_any(previous, "每项", "每个", "合同", "累计")
        )
    return current.startswith(("能力", "证明", "证书", "材料")) and previous.endswith(
        ("的", "应", "须", "具有", "具备")
    )


def _merge_source_references(
    first: list[dict[str, Any]],
    second: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, int | None, str, str]] = set()
    for reference in [*first, *second]:
        key = (
            str(reference.get("document_id") or ""),
            reference.get("page"),
            str(reference.get("locator") or ""),
            str(
                reference.get("source_version")
                or reference.get("source_file_version")
                or ""
            ),
        )
        if key not in seen:
            seen.add(key)
            result.append(reference)
    return result


def _line_source_references(
    page_references: list[dict[str, Any]],
    raw_line: str,
    page_number: int,
    line_number: int,
) -> list[dict[str, Any]]:
    fragment = re.sub(r"\s+", " ", raw_line).strip()
    result: list[dict[str, Any]] = []
    for reference in page_references:
        item = dict(reference)
        if fragment:
            item["quote"] = raw_line.strip()
        locator = str(item.get("locator") or "")
        item["locator"] = f"{locator}:l{line_number}" if locator else (
            f"p{page_number}:l{line_number}"
        )
        result.append(item)
    return result


def _line_references(line: str, sections: list[Any]) -> list[dict[str, Any]]:
    for item in sections:
        if not isinstance(item, Mapping):
            continue
        content = str(item.get("content") or item.get("text") or "")
        if line in content:
            refs = item.get("source_references") or []
            return list(refs) if isinstance(refs, list) else []
    return []


def _category_from_line(line: str) -> str:
    if _contains_any(line, "废标", "无效投标", "否决", "一票否决"):
        return "disqualification"
    if _is_eligibility_statement(line) or _contains_any(
        line,
        "资格条件",
        "资格要求",
        "资质证书",
        "营业执照",
        "法人登记证明",
        "审计报告",
        "银行资信",
    ):
        return "qualification"
    if _contains_any(line, "评分", "得分", "分值"):
        return "scoring"
    if _contains_any(line, "报价", "税率", "付款", "商务"):
        return "commercial"
    if _contains_any(line, "格式", "签字", "盖章", "文件份数"):
        return "format"
    if _contains_any(line, "系统", "支持", "参数", "功能", "性能", "日志"):
        return "technical"
    if _is_mandatory_clause(line):
        return "compliance"
    return "other"


def _is_requirement_line(line: str, category: str) -> bool:
    if _is_heading_line(line) or _is_non_requirement_context(line):
        return False
    return _is_eligibility_statement(line) or _is_mandatory_clause(line) or (
        category in {"qualification", "disqualification"}
        and (
            _contains_any(line, "需", "应", "须", "必须", "不得", "要求")
            or _has_qualification_evidence_context(line)
        )
    )


def _has_qualification_evidence_context(line: str) -> bool:
    evidence_terms = (
        "营业执照",
        "法人登记证明",
        "审计报告关键页",
        "银行资信证明",
        "资信证明",
    )
    if not _contains_any(line, *evidence_terms):
        return False
    submission_action = _contains_any(
        line,
        "提供",
        "提交",
        "出具",
        "递交",
        "附上",
        "附：",
        "作为证明",
    )
    qualification_context = _contains_any(
        line,
        "资格审查",
        "资格要求",
        "资格条件",
        "资格证明",
        "审查材料",
    )
    license_context = _contains_any(
        line,
        "营业执照",
        "法人登记证明",
    ) and _contains_any(line, "有效", "依法登记", "投标人", "供应商")
    return submission_action and (
        qualification_context
        or license_context
        or _contains_any(line, "审计报告关键页", "银行资信证明", "资信证明")
        or _contains_any(line, "投标人", "供应商", "申请人", "响应人")
    )


def _is_non_requirement_context(line: str) -> bool:
    has_hard_action = _has_hard_requirement_action(line)
    if "不作为资格审查条件" in line:
        return not has_hard_action
    if _contains_any(line, "可选材料", "背景资料"):
        return not has_hard_action
    return "企业介绍" in line and not has_hard_action


def _has_hard_requirement_action(line: str) -> bool:
    return bool(
        re.search(
            r"(?:必须|须|应当|不得|严禁|禁止)"
            r".{0,24}(?:提供|提交|出具|递交|附上|附：|具有|具备|满足|符合)"
            r"|应(?=提供|提交|出具|递交|附上|附：|具有|具备|满足|符合)",
            line,
        )
    )


def _is_eligibility_statement(line: str) -> bool:
    eligibility_terms = (
        "独立承担民事责任",
        "独立法人资格",
        "依法设立",
        "商业信誉",
        "财务会计制度",
        "履行合同所必需",
        "依法缴纳税收",
        "社会保障资金",
        "重大违法记录",
        "资质证书",
    )
    if not _contains_any(line, *eligibility_terms):
        return False

    clause = re.sub(
        r"^\s*(?:\d+(?:\.\d+)*[、.)）]?|[一二三四五六七八九十]+[、.）)])\s*",
        "",
        line,
    )
    subject = r"(?:投标人|供应商|申请人|响应人|投标单位|投标申请人)"
    prefix = (
        r"(?:(?:(?:本项目|采购文件|招标文件|本次招标)?"
        r"(?:资格要求|资格条件)\s*[:：]?\s*)|"
        r"(?:(?:本项目|采购文件|招标文件|本次招标)?要求\s*))?"
    )
    obligation = (
        r"(?:应当|应|须|必须|需|具有|具备|符合|满足|"
        r"应具备|应符合|应满足|须具备|须符合|需具备)"
    )
    return re.match(prefix + subject + r"\s*" + obligation, clause) is not None


def _is_mandatory_clause(line: str) -> bool:
    return bool(
        re.search(
            r"(?:应当|应(?=提供|提交|具有|具备|满足|符合|遵守|配置|支持|采用|"
            r"达到|按|在|于|履行|保证|响应)"
            r"|须(?=提供|提交|具有|具备|持有|满足|符合|遵守|采用|按|在|于|履行|保证|"
            r"完成|达到|响应)"
            r"|必须"
            r"|不得|严禁|禁止|不应|不得少于|不少于|不低于|不超过|"
            r"不高于|至少|至多)",
            line,
        )
    )


def _is_heading_line(line: str) -> bool:
    return bool(
        re.match(
            r"^[一二三四五六七八九十百]+、",
            line,
        )
        and not re.search(r"[。；;！？!?]$", line)
        and not _is_mandatory_clause(line)
        and not _is_eligibility_statement(line)
        and not _has_qualification_evidence_context(line)
    )


def _is_layout_noise(line: str) -> bool:
    compact = re.sub(r"\s+", "", line)
    watermark_chars = set("料资试测拟模★")
    if compact and set(compact) <= watermark_chars:
        return True
    return compact.rstrip("★") in {
        "统一身份与权限",
        "日志审计",
        "数据安全",
        "部署兼容",
    }


def _looks_like_score(line: str) -> bool:
    return _contains_any(line, "评分", "得分", "分值") or bool(
        re.search(
            r"(?:得|计取?|累计|最高|满分|不超过)\s*"
            r"[0-9]+(?:\.[0-9]+)?\s*分",
            line,
        )
        or re.search(
            r"[0-9]+(?:\.[0-9]+)?\s*(?:-|~|～|至|到)\s*"
            r"[0-9]+(?:\.[0-9]+)?\s*分",
            line,
        )
    )


def _score_from_line(line: str) -> float | None:
    if _contains_any(line, "无上限", "不设上限", "不封顶", "不限分", "不限上限"):
        return None

    score = r"([0-9]+(?:\.[0-9]+)?)\s*分"
    ceiling_pattern = (
        r"(?:最高(?:可得|得分|得)?|满分(?:为)?|不得超过|不超过|"
        r"累计(?:不超过|最高|上限|最多|至多)?|"
        r"(?:合计|总计)(?:不超过|最高|累计|为)?|"
        r"总分(?:为|不超过)?|上限(?:为|不超过)?|封顶(?:为)?)\s*"
        + score
    )
    ceilings = re.findall(ceiling_pattern, line)
    if ceilings:
        normalized_ceilings = {Decimal(value) for value in ceilings}
        if len(normalized_ceilings) != 1:
            return None
        return float(next(iter(normalized_ceilings)))

    if re.search(
        r"每(?:个|项|份|家|人|次|种).{0,40}"
        r"(?:得|计取?|加)\s*[0-9]+(?:\.[0-9]+)?\s*分",
        line,
    ):
        return None
    ranges = re.findall(
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:-|~|～|至|到)\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*分",
        line,
    )
    if ranges:
        return float(max(Decimal(upper) for _, upper in ranges))
    matches = re.findall(score, line)
    if len(matches) == 1:
        return float(Decimal(matches[0]))
    if matches and len(set(matches)) == 1:
        return float(Decimal(matches[0]))
    return None


def _evidence_hints(line: str) -> list[str]:
    hints: list[str] = []
    standards = _iso_standard_identifiers(line)
    hints.extend(standards)
    mapping = {
        "营业执照": "business_license",
        "法人登记": "business_license",
        "独立承担民事责任": "business_license",
        "依法设立": "business_license",
        "资质": "qualification",
        "认证": "certification",
        "ISO": "certification",
        "合同": "contract",
        "验收": "acceptance",
        "社保": "social_security",
        "审计": "financial_report",
        "财务": "financial_report",
        "商业信誉": "credit",
        "依法缴纳税收": "tax",
        "社会保障资金": "social_security",
        "履行合同所必需": "qualification",
        "专业技术能力": "qualification",
        "重大违法记录": "credit",
        "授权": "authorization",
        "保证金": "bid_bond",
        "证书": "personnel_certificate",
    }
    for term, material_type in mapping.items():
        if standards and material_type == "certification":
            continue
        if term.lower() in line.lower() and material_type not in hints:
            hints.append(material_type)
    return hints


def _iso_standard_identifiers(line: str) -> list[str]:
    identifiers = []
    for match in re.finditer(
        r"(?<![A-Za-z0-9])ISO\s*(?:/\s*IEC\s*)?"
        r"(\d{4,6})(?:\s*[:：]\s*(\d{4}))?",
        line,
        flags=re.IGNORECASE,
    ):
        identifier = f"ISO{match.group(1)}"
        if match.group(2):
            identifier += f":{match.group(2)}"
        if identifier not in identifiers:
            identifiers.append(identifier)
    return identifiers


def _check_rule_from_line(line: str) -> dict[str, Any]:
    local_rule = build_local_requirement_rule(line)
    if local_rule:
        return local_rule
    standards = _iso_standard_identifiers(line)
    if len(standards) != 1:
        return {}
    ast: dict[str, Any] = {
        "op": "exists",
        "evidence_types": standards,
    }
    if _contains_any(line, "有效", "在有效期内"):
        ast["where"] = {"verification_status": "verified"}
    return {"rule_ast": ast}


def _title_from_line(line: str) -> str:
    title = re.split(r"[：:，,。；;]", line, maxsplit=1)[0].strip()
    return title[:80] or line[:80]


def _section_kind(file_name: str) -> str:
    name = Path(file_name).stem.lower()
    if any(term in name for term in ("更正", "补遗", "澄清")):
        return "clarification"
    return "tender"


def _first_match(text: str, pattern: str) -> str:
    match = re.search(pattern, text, flags=re.I)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _contains_any(value: str, *terms: str) -> bool:
    return any(term.lower() in value.lower() for term in terms)


def _is_noise(value: str) -> bool:
    return value in {"目录", "招标文件", "采购文件"} or set(value) <= {"-", "_", "."}


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
