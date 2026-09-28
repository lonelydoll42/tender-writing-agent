"""Small deterministic backends for the local, file-backed demo runtime.

They are deliberately conservative.  A deployment can inject OCR/LLM/parser
backends later, while local runs still preserve the same artifact contracts.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.files import (
    FileRegistryError,
    ProjectFileRegistry,
)
from qiaowenshu_agent.domain.models import SourceReference


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

        text = _sections_text(payload.get("sections") or [])
        requirements: list[dict[str, Any]] = []
        scoring_items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for line in _candidate_lines(text):
            normalized = _normalize(line)
            if normalized in seen:
                continue
            seen.add(normalized)
            source_references = _line_references(line, payload.get("sections") or [])
            score = _score_from_line(line)
            if score is not None and _looks_like_score(line):
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
                continue
            category = _category_from_line(line)
            if not _is_requirement_line(line, category):
                continue
            requirement_id = f"R-{len(requirements) + 1:03d}"
            requirements.append(
                {
                    "requirement_id": requirement_id,
                    "category": category,
                    "title": _title_from_line(line),
                    "description": line,
                    "mandatory": category
                    in {"disqualification", "qualification", "compliance"}
                    or _contains_any(line, "必须", "应当", "须", "不得"),
                    "evidence_required": _evidence_hints(line),
                    "source_references": source_references,
                }
            )
        warnings = []
        if not text.strip():
            warnings.append(
                "parsed tender artifacts contain no text; OCR or a parser "
                "backend is required"
            )
        elif not requirements and not scoring_items:
            warnings.append(
                "local parser found no atomic requirements; review the parsed artifact"
            )
        return {
            "requirements": requirements,
            "scoring_items": scoring_items,
            "warnings": warnings,
        }


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
    value = f"{file_name}\n{text}".lower()
    rules = (
        (("营业执照", "法人登记", "统一社会信用代码"), "business_license"),
        (("iso27001", "iso/iec 27001", "信息安全管理体系"), "certification"),
        (("iso9001", "质量管理体系"), "certification"),
        (("验收报告", "验收证明"), "acceptance"),
        (("合同", "合同额", "合同金额"), "contract"),
        (("项目经理", "项目负责人", "项目管理师"), "personnel_certificate"),
        (("社保", "社会保险"), "social_security"),
        (("保证金", "银行回单", "保函"), "bid_bond"),
        (("审计报告", "财务报告", "资产负债表"), "financial_report"),
        (("授权委托", "授权书"), "authorization"),
    )
    for terms, material_type in rules:
        if any(term in value for term in terms):
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
    certificate_type = _first_match(text, r"(ISO\s*/?IEC\s*[0-9]+(?:\s*:\s*[0-9]{4})?)")
    if certificate_type:
        metadata["certificate_type"] = re.sub(r"\s+", "", certificate_type).upper()
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
    amount = _first_number(
        text,
        r"(?:合同金额|合同额|项目金额|保证金金额|缴纳金额|金额)\s*[:：]?[^0-9]{0,10}([0-9][0-9,]*(?:\.[0-9]+)?)",
    )
    if amount is not None:
        metadata["amount"] = amount
    if _contains_any(text, "已过期", "过期", "失效", "无效"):
        metadata["verification_status"] = "invalid"
        metadata["status"] = "expired" if _contains_any(text, "过期") else "invalid"
    elif _contains_any(text, "有效", "合格", "足额"):
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
        metadata["bid_bond_amount"] = amount
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
        result["bid_bond_amount"] = max(bond_amounts)
    return result


def _first_number(text: str, pattern: str) -> float | None:
    value = _first_match(text, pattern)
    if not value:
        return None
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


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
    result: list[str] = []
    for raw in re.split(r"[\n\r]+", text):
        line = re.sub(r"^[\s\-•●▪一二三四五六七八九十、.()（）]+", "", raw).strip()
        line = re.sub(r"\s+", " ", line)
        if 6 <= len(line) <= 500 and not _is_noise(line):
            result.append(line)
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
    if _contains_any(line, "废标", "无效投标", "否决", "不得", "一票否决"):
        return "disqualification"
    if _contains_any(line, "资格", "营业执照", "资质", "保证金", "社保", "证书"):
        return "qualification"
    if _contains_any(line, "评分", "得分", "分值"):
        return "scoring"
    if _contains_any(line, "报价", "税率", "付款", "商务"):
        return "commercial"
    if _contains_any(line, "格式", "签字", "盖章", "文件份数"):
        return "format"
    return (
        "technical"
        if _contains_any(line, "系统", "支持", "参数", "功能", "性能")
        else "other"
    )


def _is_requirement_line(line: str, category: str) -> bool:
    return category != "other" or _contains_any(
        line,
        "应提供",
        "须提供",
        "必须",
        "应当",
        "要求",
        "不少于",
        "不低于",
        "不得少于",
        "符合",
    )


def _looks_like_score(line: str) -> bool:
    return _contains_any(line, "评分", "得分", "分值") or bool(
        re.search(r"(?:^|\s)[0-9]+(?:\.[0-9]+)?\s*分", line)
    )


def _score_from_line(line: str) -> float | None:
    matches = re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*分", line)
    if not matches:
        return None
    try:
        return float(matches[0])
    except ValueError:
        return None


def _evidence_hints(line: str) -> list[str]:
    hints: list[str] = []
    mapping = {
        "营业执照": "business_license",
        "法人登记": "business_license",
        "资质": "qualification",
        "认证": "certification",
        "ISO": "certification",
        "合同": "contract",
        "验收": "acceptance",
        "社保": "social_security",
        "审计": "financial_report",
        "财务": "financial_report",
        "授权": "authorization",
        "保证金": "bid_bond",
        "证书": "personnel_certificate",
    }
    for term, material_type in mapping.items():
        if term.lower() in line.lower() and material_type not in hints:
            hints.append(material_type)
    return hints


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
