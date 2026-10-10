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
from qiaowenshu_agent.domain.document_structure import build_document_structure
from qiaowenshu_agent.domain.document_relations import build_document_relations
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
        document_structures: list[dict[str, Any]] = []
        warnings: list[str] = []
        combined_text: list[str] = []
        for artifact in artifacts:
            text = str(artifact.get("text") or "")
            combined_text.append(text)
            warnings.extend(str(item) for item in artifact.get("warnings") or [])
            document_structure = artifact.get("document_structure")
            if isinstance(document_structure, Mapping):
                document_structure = dict(document_structure)
                document_structures.append(document_structure)
            else:
                document_structure = None
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
                    **(
                        {"document_structure": document_structure}
                        if document_structure is not None
                        else {}
                    ),
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
            "document_structures": document_structures,
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
        sections = payload.get("sections") or []
        document_structures, structure_source = _document_structures_for_decomposition(
            payload, sections
        )
        input_anchor_structures = _input_document_structures(payload, sections)
        relation_output = document_relations_for_structures(
            document_structures,
            input_anchor_structures=input_anchor_structures,
        )
        relation_conflict_warnings = _document_structure_conflict_warnings(
            relation_output
        )
        explicit_requirements = list(payload.get("requirements") or [])
        explicit_scores = list(payload.get("scoring_items") or [])
        if explicit_requirements or explicit_scores:
            return {
                "requirements": explicit_requirements,
                "scoring_items": explicit_scores,
                "warnings": relation_conflict_warnings,
                "document_structures": document_structures,
                **relation_output,
                "block_projection_audit": _not_run_projection_audit(
                    document_structures,
                    structure_source=structure_source,
                ),
            }

        text = _sections_text(sections)
        requirements: list[dict[str, Any]] = []
        scoring_items: list[dict[str, Any]] = []
        seen: dict[tuple[str, tuple[tuple[str, str], ...]], int] = {}
        warnings: list[str] = []
        candidate_records = _candidate_records(sections)
        candidate_projection, candidate_entries = _build_candidate_projection_audit(
            candidate_records,
            document_structures,
            structure_source=structure_source,
        )
        candidate_results: dict[str, list[dict[str, Any]]] = {
            item["candidate_id"]: [] for item in candidate_entries
        }
        records = group_requirement_records(
            sections,
            candidate_records,
        )
        for line, source_references, group_rule in records:
            candidate_ids = _candidate_ids_for_record(
                line,
                source_references,
                candidate_entries,
            )
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
                    _set_candidate_outcome(
                        candidate_results,
                        candidate_ids,
                        "merged_into_existing_scoring_item",
                        existing["item_id"],
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
                _set_candidate_outcome(
                    candidate_results,
                    candidate_ids,
                    "scoring_item_created",
                    item_id,
                )
                continue
            if _looks_like_score(line):
                warnings.append(
                    f"评分上限无法从原文可靠提取，未生成评分项：{line}"
                )
                _set_candidate_outcome(
                    candidate_results,
                    candidate_ids,
                    "score_candidate_without_reliable_ceiling",
                )
                continue
            category = _category_from_line(line)
            if group_rule is None and not _is_requirement_line(line, category):
                _set_candidate_outcome(
                    candidate_results,
                    candidate_ids,
                    "not_requirement_under_local_rules",
                )
                continue
            if duplicate_key in seen:
                existing = requirements[seen[duplicate_key]]
                existing["source_references"] = _merge_source_references(
                    existing["source_references"], source_references
                )
                _set_candidate_outcome(
                    candidate_results,
                    candidate_ids,
                    "merged_into_existing_requirement",
                    existing["requirement_id"],
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
            _set_candidate_outcome(
                candidate_results,
                candidate_ids,
                "requirement_created",
                requirement_id,
            )
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
            "warnings": _unique([*warnings, *relation_conflict_warnings]),
            "extraction_complete": False,
            "needs_human_review": True,
            "business_status": "needs_review",
            "document_structures": document_structures,
            **relation_output,
            "block_projection_audit": {
                "candidate_projection": candidate_projection,
                "final_requirement_extraction": {
                    "status": "partial_first_pass",
                    "complete": False,
                    "candidate_results": [
                        {
                            "candidate_id": item["candidate_id"],
                            "outcomes": (
                                candidate_results[item["candidate_id"]]
                                or [
                                    {
                                        "outcome": "not_reconciled_after_grouping",
                                        "generated_ids": [],
                                    }
                                ]
                            ),
                        }
                        for item in candidate_entries
                    ],
                    "requirement_ids": [
                        item["requirement_id"] for item in requirements
                    ],
                    "scoring_item_ids": [item["item_id"] for item in scoring_items],
                },
            },
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


def _document_structures_for_decomposition(
    payload: Mapping[str, Any],
    sections: list[Any],
) -> tuple[list[dict[str, Any]], str]:
    provided = payload.get("document_structures")
    top_level = (
        [dict(item) for item in provided if isinstance(item, Mapping)]
        if isinstance(provided, list)
        else []
    )
    section_structures = [
        dict(section["document_structure"])
        for section in sections
        if isinstance(section, Mapping)
        and isinstance(section.get("document_structure"), Mapping)
    ]
    structures: list[dict[str, Any]] = []
    for structure in [*top_level, *section_structures]:
        if structure not in structures:
            structures.append(structure)

    fallback_count = 0
    for index, section in enumerate(sections, start=1):
        identity = _section_source_identity(section)
        embedded = (
            section.get("document_structure")
            if isinstance(section, Mapping)
            and isinstance(section.get("document_structure"), Mapping)
            else None
        )
        if (
            embedded is not None
            and not identity["conflict"]
            and identity["document_id"]
            and identity["source_version"]
        ):
            continue

        candidates = [
            structure
            for structure in structures
            if identity["document_id"]
            and str(structure.get("document_id") or "")
            == identity["document_id"]
            and str(structure.get("source_version") or "")
            == identity["source_version"]
        ]
        if (
            not identity["conflict"]
            and identity["document_id"]
            and identity["source_version"]
            and len(candidates) == 1
        ):
            continue

        fallback = _legacy_section_structure(
            section,
            index=index,
            identity=identity,
        )
        structures.append(fallback)
        fallback_count += 1

    if fallback_count and (top_level or section_structures):
        source = "mixed"
    elif fallback_count:
        source = "legacy_text_fallback"
    elif section_structures and not top_level:
        source = "provided_in_sections"
    elif top_level:
        source = "provided_top_level"
    else:
        source = "legacy_text_fallback"
    return structures, source


def _input_document_structures(
    payload: Mapping[str, Any],
    sections: list[Any],
) -> list[dict[str, Any]]:
    provided = payload.get("document_structures")
    structures = [
        dict(item)
        for item in provided
        if isinstance(item, Mapping)
    ] if isinstance(provided, list) else []
    structures.extend(
        dict(section["document_structure"])
        for section in sections
        if isinstance(section, Mapping)
        and isinstance(section.get("document_structure"), Mapping)
    )
    return structures


def document_relations_for_structures(
    document_structures: list[Any],
    *,
    input_anchor_structures: list[Any] | None = None,
    registry_verified_structures: list[Any] | None = None,
) -> dict[str, Any]:
    graphs: list[dict[str, Any]] = []
    warnings: list[str] = []
    diagnostics: list[str] = []
    unprocessed_structures: list[dict[str, str]] = []
    input_anchor_signatures = _document_structure_anchor_signatures(
        document_structures
        if input_anchor_structures is None
        else input_anchor_structures
    )
    registry_anchor_signatures = _document_structure_anchor_signatures(
        registry_verified_structures or []
    )
    structures_by_identity: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for structure in document_structures:
        if not isinstance(structure, Mapping):
            unprocessed_structures.append(
                {"document_id": "", "source_version": "", "reason": "not_mapping"}
            )
            continue
        document_id = str(structure.get("document_id") or "").strip()
        source_version = str(structure.get("source_version") or "").strip()
        identity = (document_id, source_version)
        if not all(identity):
            unprocessed_structures.append(
                {
                    "document_id": document_id,
                    "source_version": source_version,
                    "reason": "missing_document_identity",
                }
            )
            continue
        structures_by_identity.setdefault(identity, []).append(structure)

    for (document_id, source_version), versions in structures_by_identity.items():
        signatures = {
            _document_structure_content_signature(item) for item in versions
        }
        if len(signatures) > 1:
            unprocessed_structures.append(
                {
                    "document_id": document_id,
                    "source_version": source_version,
                    "reason": "conflicting_content",
                }
            )
            warnings.append(
                "conflicting document content for "
                f"{document_id} {source_version}; relations were not built"
            )
            continue
        else:
            structure = versions[0]

        if structure.get("schema_version") != "document-structure-v1":
            reason = "unsupported_schema"
            warning = (
                f"relations not run for {document_id} {source_version}: "
                "unsupported document structure schema"
            )
            unprocessed_structures.append(
                {
                    "document_id": document_id,
                    "source_version": source_version,
                    "reason": reason,
                }
            )
            warnings.append(warning)
            continue

        blocks = structure.get("blocks")
        if not isinstance(blocks, list):
            reason = "invalid_blocks"
            warning = (
                f"relations not run for {document_id} {source_version}: "
                "document blocks are missing or invalid"
            )
            unprocessed_structures.append(
                {
                    "document_id": document_id,
                    "source_version": source_version,
                    "reason": reason,
                }
            )
            warnings.append(warning)
            continue
        if not blocks:
            reason = "empty_blocks"
            warning = (
                f"relations not run for {document_id} {source_version}: "
                "document structure has no blocks"
            )
            unprocessed_structures.append(
                {
                    "document_id": document_id,
                    "source_version": source_version,
                    "reason": reason,
                }
            )
            warnings.append(warning)
            continue

        try:
            graph = dict(
                build_document_relations(_relation_source_structure(structure))
            )
        except Exception as exc:
            unprocessed_structures.append(
                {
                    "document_id": document_id,
                    "source_version": source_version,
                    "reason": "builder_failed",
                }
            )
            warnings.append(
                f"relations not run for {document_id} {source_version}: "
                f"relation builder failed ({type(exc).__name__})"
            )
            continue
        graph["document_id"] = document_id
        graph["source_version"] = source_version
        structure_signature = _document_structure_content_signature(structure)
        if structure_signature in registry_anchor_signatures.get(
            (document_id, source_version), set()
        ):
            source_identity_status = "registry_verified"
        elif structure_signature in input_anchor_signatures.get(
            (document_id, source_version), set()
        ):
            source_identity_status = "caller_asserted"
        else:
            source_identity_status = "unverified"
        graph["source_identity_status"] = source_identity_status

        coordinates_unverified = _has_unverified_source_coordinates(structure)
        if source_identity_status == "unverified" or coordinates_unverified:
            graph = _candidate_only_relations(graph)
            graph_warnings = [str(item) for item in graph.get("warnings") or []]
            if coordinates_unverified:
                warning = (
                    "section-relative source coordinates are unverified; "
                    "relation confirmations require human review"
                    if _has_section_relative_source_coordinates(structure)
                    else "source coordinates are unknown or unverified; "
                    "relation confirmations require human review"
                )
                if warning not in graph_warnings:
                    graph_warnings.append(warning)
            if source_identity_status == "unverified":
                warning = (
                    "source identity is not anchored to input or Registry "
                    "content; relation confirmations require human review"
                )
                if warning not in graph_warnings:
                    graph_warnings.append(warning)
            graph["warnings"] = graph_warnings
            graph["needs_human_review"] = True
        graph["source_reference_status"] = (
            "unverified"
            if coordinates_unverified
            else _graph_source_reference_status(graph)
        )
        graphs.append(graph)
        warnings.extend(str(item) for item in graph.get("warnings") or [])

    if not document_structures:
        diagnostics.append(
            "no document structures were supplied; relation analysis was not run"
        )

    executed = bool(graphs)
    source_statuses = [
        str(graph.get("source_reference_status") or "unresolved")
        for graph in graphs
    ]
    unresolved_document_count = sum(
        status != "verified" for status in source_statuses
    )
    not_run_reasons = {item["reason"] for item in unprocessed_structures}
    if not executed and not document_structures:
        not_run_reason = "no_document_structures"
    elif not executed and len(not_run_reasons) == 1:
        not_run_reason = next(iter(not_run_reasons))
    elif not executed:
        not_run_reason = "no_eligible_structures"
    else:
        not_run_reason = None
    identity_statuses = [
        str(graph.get("source_identity_status") or "unverified")
        for graph in graphs
    ]
    if not executed:
        source_identity_status = (
            "unverified" if unprocessed_structures else "not_run"
        )
    elif "unverified" in identity_statuses or unprocessed_structures:
        source_identity_status = "unverified"
    elif "caller_asserted" in identity_statuses:
        source_identity_status = "caller_asserted"
    else:
        source_identity_status = "registry_verified"
    return {
        "document_relations": graphs,
        "relation_analysis": {
            "status": "executed" if executed else "not_run",
            "coverage_status": "partial" if executed else "not_run",
            "document_count": len(graphs),
            "needs_human_review": not_run_reason != "no_document_structures",
            "unresolved_document_count": unresolved_document_count,
            "source_identity_status": source_identity_status,
            "source_reference_status": (
                "not_run"
                if not executed
                else "unresolved"
                if all(status != "verified" for status in source_statuses)
                else "partial"
                if unresolved_document_count
                else "verified"
            ),
            "not_run_reason": not_run_reason,
            "unprocessed_structures": unprocessed_structures,
            "warnings": list(dict.fromkeys(warnings)),
            "diagnostics": list(dict.fromkeys(diagnostics)),
        },
    }


def _document_structure_anchor_signatures(
    structures: list[Any],
) -> dict[tuple[str, str], set[tuple[Any, ...]]]:
    signatures: dict[tuple[str, str], set[tuple[Any, ...]]] = {}
    for structure in structures:
        if not isinstance(structure, Mapping):
            continue
        identity = (
            str(structure.get("document_id") or "").strip(),
            str(structure.get("source_version") or "").strip(),
        )
        if not all(identity):
            continue
        signatures.setdefault(identity, set()).add(
            _document_structure_content_signature(structure)
        )
    return signatures


def _document_structure_content_signature(
    structure: Mapping[str, Any],
) -> tuple[Any, ...]:
    return (_freeze_structure_content(_relation_source_structure(structure)),)


def _document_structure_conflict_warnings(
    relation_output: Mapping[str, Any],
) -> list[str]:
    analysis = relation_output.get("relation_analysis")
    if not isinstance(analysis, Mapping):
        return []
    return [
        str(warning)
        for warning in analysis.get("warnings") or []
        if str(warning).startswith("conflicting document content")
    ]


def _freeze_structure_content(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(
            sorted(
                (
                    str(key),
                    _freeze_structure_content(item),
                )
                for key, item in value.items()
            )
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_structure_content(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(_freeze_structure_content(item) for item in value))
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value


def _graph_source_reference_status(graph: Mapping[str, Any]) -> str:
    nodes = graph.get("condition_nodes")
    if isinstance(nodes, Mapping):
        nodes = list(nodes.values())
    if isinstance(nodes, list) and nodes:
        verified_nodes = [
            _has_verified_source_references(node)
            for node in nodes
            if isinstance(node, Mapping)
        ]
        if verified_nodes and all(verified_nodes):
            return "verified"
        if any(verified_nodes):
            return "partial"
        return "unresolved"
    return "verified" if _has_verified_source_references(graph) else "unresolved"


def _has_verified_source_references(value: Any) -> bool:
    if isinstance(value, Mapping):
        references = value.get("source_references")
        if isinstance(references, list) and any(
            isinstance(reference, Mapping)
            and isinstance(reference.get("document_id"), str)
            and bool(reference.get("document_id"))
            and isinstance(reference.get("source_version"), str)
            and bool(reference.get("source_version"))
            and isinstance(reference.get("page"), int)
            and not isinstance(reference.get("page"), bool)
            and isinstance(reference.get("char_start"), int)
            and not isinstance(reference.get("char_start"), bool)
            and isinstance(reference.get("char_end"), int)
            and not isinstance(reference.get("char_end"), bool)
            and isinstance(reference.get("quote"), str)
            for reference in references
        ):
            return True
        return any(
            _has_verified_source_references(item) for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_has_verified_source_references(item) for item in value)
    return False


def _relation_source_structure(structure: Mapping[str, Any]) -> dict[str, Any]:
    source = dict(structure)
    for key in (
        "block_relations",
        "condition_nodes",
        "document_relations",
        "references",
        "relation_analysis",
        "roots",
    ):
        source.pop(key, None)
    blocks: list[Any] = []
    for block in structure.get("blocks", []):
        if not isinstance(block, Mapping):
            blocks.append(block)
            continue
        source_block = dict(block)
        for key in (
            "condition_node_ids",
            "condition_nodes",
            "parent_relation",
            "reference_relations",
            "scope_relations",
        ):
            source_block.pop(key, None)
        blocks.append(source_block)
    source["blocks"] = blocks
    return source


def _has_unverified_source_coordinates(structure: Mapping[str, Any]) -> bool:
    metadata = structure.get("metadata")
    coordinate_values = [
        structure.get("source_coordinate_status"),
        structure.get("source_coordinate_scope"),
    ]
    if isinstance(metadata, Mapping):
        coordinate_values.extend(
            [
                metadata.get("source_coordinate_status"),
                metadata.get("source_coordinate_scope"),
            ]
        )
    pages = structure.get("pages")
    for page in pages if isinstance(pages, list) else []:
        if isinstance(page, Mapping):
            coordinate_values.extend(
                [
                    page.get("source_coordinate_status"),
                    page.get("source_coordinate_scope"),
                    page.get("page_number_scope"),
                ]
            )
            page_metadata = page.get("metadata")
            if isinstance(page_metadata, Mapping):
                coordinate_values.extend(
                    [
                        page_metadata.get("source_coordinate_status"),
                        page_metadata.get("source_coordinate_scope"),
                    ]
                )
    blocks = structure.get("blocks")
    for block in blocks if isinstance(blocks, list) else []:
        if isinstance(block, Mapping):
            coordinate_values.extend(
                [
                    block.get("source_coordinate_status"),
                    block.get("source_coordinate_scope"),
                    block.get("source_span_coordinate_status"),
                    block.get("source_span_scope"),
                ]
            )
            block_metadata = block.get("metadata")
            if isinstance(block_metadata, Mapping):
                coordinate_values.extend(
                    [
                        block_metadata.get("source_coordinate_status"),
                        block_metadata.get("source_coordinate_scope"),
                    ]
                )
    return any(_coordinate_value_is_unverified(value) for value in coordinate_values)


def _coordinate_value_is_unverified(value: Any) -> bool:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return bool(
        normalized
        and any(
            marker in normalized
            for marker in (
                "unknown",
                "unverified",
                "unmarked",
                "unresolved",
                "not_set",
                "not_available",
                "partial",
                "relative",
            )
        )
    )


def _has_section_relative_source_coordinates(
    structure: Mapping[str, Any],
) -> bool:
    values = [
        structure.get("source_coordinate_status"),
        structure.get("source_coordinate_scope"),
    ]
    metadata = structure.get("metadata")
    if isinstance(metadata, Mapping):
        values.extend(
            [
                metadata.get("source_coordinate_status"),
                metadata.get("source_coordinate_scope"),
            ]
        )
    pages = structure.get("pages")
    for page in pages if isinstance(pages, list) else []:
        if isinstance(page, Mapping):
            values.extend(
                [
                    page.get("source_coordinate_status"),
                    page.get("source_coordinate_scope"),
                    page.get("page_number_scope"),
                ]
            )
            page_metadata = page.get("metadata")
            if isinstance(page_metadata, Mapping):
                values.extend(
                    [
                        page_metadata.get("source_coordinate_status"),
                        page_metadata.get("source_coordinate_scope"),
                    ]
                )
    blocks = structure.get("blocks")
    for block in blocks if isinstance(blocks, list) else []:
        if isinstance(block, Mapping):
            values.extend(
                [
                    block.get("source_coordinate_status"),
                    block.get("source_coordinate_scope"),
                    block.get("source_span_coordinate_status"),
                    block.get("source_span_scope"),
                ]
            )
            block_metadata = block.get("metadata")
            if isinstance(block_metadata, Mapping):
                values.extend(
                    [
                        block_metadata.get("source_coordinate_status"),
                        block_metadata.get("source_coordinate_scope"),
                    ]
                )
    return any("section_relative" in str(value or "") for value in values)


def _candidate_only_relations(value: Any) -> Any:
    if isinstance(value, Mapping):
        result = {
            str(key): _candidate_only_relations(item)
            for key, item in value.items()
        }
        if result.get("status") == "confirmed":
            result["status"] = "candidate"
        return result
    if isinstance(value, list):
        return [_candidate_only_relations(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_candidate_only_relations(item) for item in value)
    return value


def _section_source_identity(section: Any) -> dict[str, Any]:
    if not isinstance(section, Mapping):
        return {
            "document_id": "",
            "source_version": "",
            "conflict": False,
            "reason": "section has no explicit source identity",
        }
    document_ids = {
        str(section.get(key) or "").strip()
        for key in ("file_id", "document_id")
        if str(section.get(key) or "").strip()
    }
    source_versions = {
        str(section.get(key) or "").strip()
        for key in ("source_version", "source_file_version")
        if str(section.get(key) or "").strip()
    }
    reference_document_ids: set[str] = set()
    reference_versions: set[str] = set()
    raw_references = section.get("source_references") or []
    if isinstance(raw_references, (list, tuple)):
        for reference in raw_references:
            if not isinstance(reference, Mapping):
                continue
            document_id = str(reference.get("document_id") or "").strip()
            source_version = str(
                reference.get("source_version")
                or reference.get("source_file_version")
                or ""
            ).strip()
            if document_id:
                reference_document_ids.add(document_id)
            if source_version:
                reference_versions.add(source_version)

    attached = section.get("document_structure")
    if isinstance(attached, Mapping):
        document_id = str(attached.get("document_id") or "").strip()
        source_version = str(attached.get("source_version") or "").strip()
        if document_id:
            document_ids.add(document_id)
        if source_version:
            source_versions.add(source_version)

    reason = ""
    if len(reference_document_ids) > 1 or len(reference_versions) > 1:
        reason = "section references contain multiple document/version keys"
    elif reference_document_ids and document_ids - reference_document_ids:
        reason = "section identity conflicts with source references"
    elif reference_versions and source_versions - reference_versions:
        reason = "section version conflicts with source references"
    elif len(document_ids) > 1:
        reason = "section contains conflicting document identifiers"
    elif len(source_versions) > 1:
        reason = "section contains conflicting source versions"
    return {
        "document_id": next(iter(document_ids), "")
        or next(iter(reference_document_ids), ""),
        "source_version": next(iter(source_versions), "")
        or next(iter(reference_versions), ""),
        "conflict": bool(reason),
        "reason": reason or "source identity is incomplete",
    }


def _legacy_section_structure(
    section: Any,
    *,
    index: int,
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(section, Mapping):
        content = str(section.get("content") or section.get("text") or "")
        raw_references = section.get("source_references") or []
        section_id = str(section.get("section_id") or "")
        title = str(section.get("title") or "")
        checksum = section.get("checksum", section.get("source_checksum"))
    else:
        content = str(section)
        raw_references = []
        section_id = ""
        title = ""
        checksum = None
    references = (
        [dict(item) for item in raw_references if isinstance(item, Mapping)]
        if isinstance(raw_references, (list, tuple))
        else []
    )
    identified = bool(
        not identity.get("conflict")
        and identity.get("document_id")
        and identity.get("source_version")
    )
    document_id = (
        str(identity["document_id"])
        if identified
        else f"unverified-section-{index}-{section_id or title or 'legacy'}"
    )
    source_version = (
        str(identity["source_version"]) if identified else "unverified"
    )
    pages = [
        {
            "page_number": page_number,
            "text": page_text,
        }
        for page_number, page_text in enumerate(content.split("\f") or [""], start=1)
    ]
    structure = build_document_structure(
        pages,
        document_id=document_id,
        source_version=source_version,
        source_checksum=(str(checksum) if checksum not in (None, "") else None),
    )
    metadata = dict(structure.get("metadata") or {})
    metadata["integration_source"] = "legacy_section_text_fallback"
    metadata["source_representation"] = "legacy_section_text_fragment"
    metadata["source_identity_status"] = "identified" if identified else "unverified"
    metadata["source_coordinate_status"] = "section_relative_unverified"
    metadata["source_coordinate_scope"] = "section_relative"
    metadata["source_references_status"] = "diagnostic_only"
    metadata["source_references_diagnostic_only"] = references
    metadata["fallback_section_index"] = index
    if not identified:
        metadata["source_identity_reason"] = (
            str(identity.get("reason") or "section source identity is missing")
        )
    structure["metadata"] = metadata
    structure["source_coordinate_status"] = "section_relative_unverified"
    structure["source_coordinate_scope"] = "section_relative"
    for page in structure.get("pages", []):
        if isinstance(page, dict):
            page["source_coordinate_status"] = "section_relative_unverified"
            page["page_number_scope"] = "section_relative"

    block_id_map: dict[str, str] = {}
    for block in structure.get("blocks", []):
        if not isinstance(block, dict):
            continue
        old_block_id = str(block.get("block_id") or "")
        if old_block_id:
            block_id_map[old_block_id] = f"{old_block_id}:section-{index}"
    for block in structure.get("blocks", []):
        if not isinstance(block, dict):
            continue
        if str(block.get("block_id") or "") in block_id_map:
            block["block_id"] = block_id_map[str(block["block_id"])]
        for key in ("parent_block_id", "section_block_id"):
            parent_id = str(block.get(key) or "")
            if parent_id in block_id_map:
                block[key] = block_id_map[parent_id]
        block["source_coordinate_status"] = "section_relative_unverified"
        block["source_coordinate_scope"] = "section_relative"
        block["source_span_coordinate_status"] = "section_relative_unverified"
        block["source_span_scope"] = "section_relative"
        block["source_references"] = []
    return structure


def _not_run_projection_audit(
    document_structures: list[Mapping[str, Any]],
    *,
    structure_source: str,
) -> dict[str, Any]:
    blocks = [
        {
            "document_id": str(structure.get("document_id") or ""),
            "source_version": str(structure.get("source_version") or ""),
            "block_id": str(block.get("block_id") or ""),
            "source_coordinate_status": str(
                block.get("source_coordinate_status")
                or structure.get("source_coordinate_status")
                or "source_coordinates_unmarked"
            ),
            "candidate_ids": [],
            "participated": False,
            "filter_reason": "candidate_projection_not_run_for_explicit_input",
        }
        for structure in document_structures
        for block in structure.get("blocks", [])
        if isinstance(block, Mapping)
    ]
    return {
        "candidate_projection": {
            "status": "not_run_explicit_input",
            "structure_source": structure_source,
            "blocks": blocks,
            "candidates": [],
        },
        "final_requirement_extraction": {
            "status": "bypassed_explicit_input",
            "complete": False,
            "candidate_results": [],
        },
    }


def _build_candidate_projection_audit(
    records: list[tuple[str, list[dict[str, Any]]]],
    document_structures: list[Mapping[str, Any]],
    *,
    structure_source: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    for index, (text, references) in enumerate(records, start=1):
        candidate_id = f"C-{index:04d}"
        source_blocks, mapping_status, mapping_reason = _candidate_source_blocks(
            text,
            references,
            document_structures,
        )
        candidates.append(
            {
                "candidate_id": candidate_id,
                "candidate_text": text,
                "source_block_ids": [item["block_id"] for item in source_blocks],
                "source_blocks": source_blocks,
                "source_mapping_status": mapping_status,
                "source_mapping_reason": mapping_reason,
                "source_references": [dict(item) for item in references],
            }
        )

    candidate_ids_by_block: dict[tuple[str, str, str], list[str]] = {}
    for candidate in candidates:
        for source_block in candidate["source_blocks"]:
            key = (
                source_block["document_id"],
                source_block["source_version"],
                source_block["block_id"],
            )
            candidate_ids_by_block.setdefault(key, []).append(candidate["candidate_id"])

    block_audit: list[dict[str, Any]] = []
    for structure in document_structures:
        document_id = str(structure.get("document_id") or "")
        source_version = str(structure.get("source_version") or "")
        for block in structure.get("blocks", []):
            if not isinstance(block, Mapping):
                continue
            block_id = str(block.get("block_id") or "")
            candidate_ids = candidate_ids_by_block.get(
                (document_id, source_version, block_id),
                [],
            )
            if candidate_ids:
                filter_reason = None
            else:
                filter_reason = _candidate_filter_reason(block)
                if (
                    filter_reason == "not_selected_or_source_unmapped"
                    and _source_coordinates_unverified(structure, block)
                ):
                    filter_reason = "source_coordinates_unverified"
            block_audit.append(
                {
                    "document_id": document_id,
                    "source_version": source_version,
                    "block_id": block_id,
                    "source_coordinate_status": str(
                        block.get("source_coordinate_status")
                        or structure.get("source_coordinate_status")
                        or "source_coordinates_unmarked"
                    ),
                    "participated": bool(candidate_ids),
                    "projection_status": (
                        "candidate"
                        if candidate_ids
                        else "filtered"
                        if filter_reason != "not_selected_or_source_unmapped"
                        else "not_selected_or_source_unmapped"
                    ),
                    "filter_reason": filter_reason,
                    "candidate_ids": list(candidate_ids),
                }
            )

    return (
        {
            "status": "executed_legacy_candidate_rules",
            "structure_source": structure_source,
            "blocks": block_audit,
            "candidates": [
                {
                    "candidate_id": item["candidate_id"],
                    "candidate_text": item["candidate_text"],
                    "source_block_ids": item["source_block_ids"],
                    "source_blocks": item["source_blocks"],
                    "source_mapping_status": item["source_mapping_status"],
                    "source_mapping_reason": item["source_mapping_reason"],
                }
                for item in candidates
            ],
        },
        candidates,
    )


def _candidate_source_blocks(
    candidate_text: str,
    references: list[dict[str, Any]],
    document_structures: list[Mapping[str, Any]],
) -> tuple[list[dict[str, str]], str, str | None]:
    line_references: dict[
        tuple[str, str, int, int],
        list[Mapping[str, Any]],
    ] = {}
    has_line_locator = False
    incomplete_line_locator = False
    conflicting_line_locator = False
    has_unlocated_reference = False
    for reference in references:
        if not isinstance(reference, Mapping):
            incomplete_line_locator = True
            continue
        locator_parts = _source_reference_locator_parts(reference)
        explicit_pages: list[int] = []
        explicit_lines: list[int] = []
        for field in ("page", "page_number"):
            value = reference.get(field)
            if value in (None, ""):
                continue
            parsed = _optional_coordinate_int(value)
            if parsed is None:
                incomplete_line_locator = True
            else:
                explicit_pages.append(parsed)
        explicit_line_value = reference.get("line_number")
        if explicit_line_value not in (None, ""):
            parsed_line = _optional_coordinate_int(explicit_line_value)
            if parsed_line is None:
                incomplete_line_locator = True
            else:
                explicit_lines.append(parsed_line)

        locator_page = locator_parts["page_number"]
        locator_line = locator_parts["line_number"]
        if locator_line is None and not explicit_lines:
            has_unlocated_reference = True
            continue
        has_line_locator = True
        page_claims = [*explicit_pages]
        if locator_page is not None:
            page_claims.append(locator_page)
        line_claims = [*explicit_lines]
        if locator_line is not None:
            line_claims.append(locator_line)
        if len(set(page_claims)) > 1 or len(set(line_claims)) > 1:
            conflicting_line_locator = True
        if incomplete_line_locator:
            continue

        page_number = (
            explicit_pages[0] if explicit_pages else locator_page
        )
        line_number = explicit_lines[0] if explicit_lines else locator_line
        document_id = str(reference.get("document_id") or "").strip()
        source_versions = {
            str(reference.get(field) or "").strip()
            for field in ("source_version", "source_file_version")
            if str(reference.get(field) or "").strip()
        }
        if len(source_versions) > 1:
            conflicting_line_locator = True
        source_version = next(iter(source_versions), "")
        if (
            not document_id
            or not source_version
            or page_number is None
            or line_number is None
            or page_number < 1
            or line_number < 1
        ):
            incomplete_line_locator = True
            continue
        key = (document_id, source_version, page_number, line_number)
        line_references.setdefault(key, []).append(reference)

    if has_line_locator:
        if conflicting_line_locator:
            return (
                [],
                "ambiguous",
                "line locator conflicts with explicit page, line, or version metadata",
            )
        if has_unlocated_reference:
            return (
                [],
                "ambiguous",
                "candidate mixes exact and unlocated source references",
            )
        if incomplete_line_locator or not line_references:
            return (
                [],
                "ambiguous",
                "line locator lacks a complete document/version/page key",
            )
        result: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for document_id, source_version, page_number, line_number in sorted(
            line_references
        ):
            matching_blocks = [
                (structure, block)
                for structure in document_structures
                if str(structure.get("document_id") or "") == document_id
                and str(structure.get("source_version") or "") == source_version
                for block in structure.get("blocks", [])
                if isinstance(block, Mapping)
                and _positive_int(block.get("page_number")) == page_number
                and _positive_int(block.get("line_number")) == line_number
            ]
            verified_blocks = [
                (structure, block)
                for structure, block in matching_blocks
                if not _source_coordinates_unverified(structure, block)
            ]
            if len(verified_blocks) > 1:
                return [], "ambiguous", "line locator matches multiple source blocks"
            if not verified_blocks:
                if matching_blocks:
                    return (
                        [],
                        "unmapped",
                        "matching block has section-relative unverified coordinates",
                )
                return [], "unmapped", "line locator did not match a source block"
            structure, block = verified_blocks[0]
            source_references = line_references[
                (document_id, source_version, page_number, line_number)
            ]
            if _duplicate_locator_claims_conflict(source_references):
                return (
                    [],
                    "ambiguous",
                    "duplicate locator has conflicting quote or span claims",
                )
            for reference in source_references:
                reason = _reference_matches_block(
                    reference,
                    structure,
                    block,
                    quote_mode="exact",
                )
                if reason:
                    status = "ambiguous" if len(source_references) > 1 else "unmapped"
                    return [], status, reason
            key = (
                document_id,
                source_version,
                str(block.get("block_id") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(
                {
                    "document_id": document_id,
                    "source_version": source_version,
                    "block_id": key[2],
                    "mapping_method": "exact_locator",
                }
            )
        return result, "mapped_exact_locator", None

    if not references:
        return [], "unmapped", "candidate has no source references"
    source_keys: set[tuple[str, str]] = set()
    for reference in references:
        if not isinstance(reference, Mapping):
            continue
        document_id = str(reference.get("document_id") or "").strip()
        source_version = str(
            reference.get("source_version")
            or reference.get("source_file_version")
            or ""
        ).strip()
        if not document_id or not source_version:
            return (
                [],
                "ambiguous",
                "text fallback requires explicit document and version",
            )
        source_keys.add((document_id, source_version))
    if len(source_keys) != 1:
        return (
            [],
            "ambiguous",
            "text fallback references multiple document/version keys",
        )

    document_id, source_version = next(iter(source_keys))
    candidate_normalized = _normalize(_clean_candidate_line(candidate_text))
    matching_blocks: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for structure in document_structures:
        if (
            str(structure.get("document_id") or "") != document_id
            or str(structure.get("source_version") or "") != source_version
        ):
            continue
        for block in structure.get("blocks", []):
            if not isinstance(block, Mapping):
                continue
            raw_text = str(block.get("raw_text") or "")
            block_normalized = _normalize(_clean_candidate_line(raw_text))
            if (
                block_normalized
                and len(block_normalized) >= 6
                and candidate_normalized
                and (
                    block_normalized == candidate_normalized
                    or block_normalized in candidate_normalized
                    or candidate_normalized in block_normalized
                )
            ):
                matching_blocks.append((structure, block))
    verified_blocks = [
        (structure, block)
        for structure, block in matching_blocks
        if not _source_coordinates_unverified(structure, block)
    ]
    supported_blocks: dict[
        tuple[str, str, str],
        tuple[Mapping[str, Any], Mapping[str, Any]],
    ] = {}
    support_reasons: list[str] = []
    for structure, block in verified_blocks:
        reasons = [
            _reference_matches_block(
                reference,
                structure,
                block,
                quote_mode="substring",
            )
            for reference in references
            if isinstance(reference, Mapping)
        ]
        if reasons and all(reason is None for reason in reasons):
            key = (
                str(structure.get("document_id") or ""),
                str(structure.get("source_version") or ""),
                str(block.get("block_id") or ""),
            )
            if key[2]:
                supported_blocks[key] = (structure, block)
        else:
            support_reasons.extend(reason for reason in reasons if reason)
    if len(supported_blocks) > 1:
        return [], "ambiguous", "text fallback matches multiple source blocks"
    if not supported_blocks:
        if matching_blocks:
            if not verified_blocks:
                return [], "unmapped", (
                    "matching block has section-relative unverified coordinates"
                )
            if support_reasons:
                return [], "unmapped", support_reasons[0]
            return [], "unmapped", "text fallback requires a non-empty source quote"
        return [], "unmapped", "text fallback did not match a source block"
    (document_id, source_version, block_id), _ = next(
        iter(supported_blocks.items())
    )
    return (
        [
            {
                "document_id": document_id,
                "source_version": source_version,
                "block_id": block_id,
                "mapping_method": "unique_text_match",
            }
        ],
        "mapped_unique_text",
        None,
    )


def _source_reference_locator_parts(
    reference: Mapping[str, Any],
) -> dict[str, int | tuple[int, int] | None]:
    locator = str(reference.get("locator") or "")
    page_match = re.search(r"(?:^|:)p(\d+)(?=:|$)", locator)
    line_match = re.search(r"(?:^|:)p(\d+)(?::[^:]*)*:l(\d+)$", locator)
    span_match = re.search(r"(?:^|:)p\d+:c(\d+)-(\d+)(?::l\d+)?$", locator)
    return {
        "page_number": _optional_coordinate_int(page_match.group(1))
        if page_match
        else None,
        "line_number": _optional_coordinate_int(line_match.group(2))
        if line_match
        else None,
        "char_span": (
            (
                _optional_coordinate_int(span_match.group(1)),
                _optional_coordinate_int(span_match.group(2)),
            )
            if span_match
            else None
        ),
    }


def _optional_coordinate_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if isinstance(value, float) and value != number:
        return None
    return number


def _duplicate_locator_claims_conflict(
    references: list[Mapping[str, Any]],
) -> bool:
    quotes = {
        str(reference.get("quote") or reference.get("content") or "").strip()
        for reference in references
        if str(reference.get("quote") or reference.get("content") or "").strip()
    }
    if len(quotes) > 1:
        return True

    pages: set[int] = set()
    spans: set[tuple[int, int]] = set()
    for reference in references:
        for field in ("page", "page_number"):
            value = reference.get(field)
            if value not in (None, ""):
                parsed = _optional_coordinate_int(value)
                if parsed is not None:
                    pages.add(parsed)
        locator_parts = _source_reference_locator_parts(reference)
        locator_page = locator_parts["page_number"]
        if isinstance(locator_page, int):
            pages.add(locator_page)
        for start_field, end_field in (("char_start", "char_end"),):
            start = reference.get(start_field)
            end = reference.get(end_field)
            if start not in (None, "") and end not in (None, ""):
                parsed_start = _optional_coordinate_int(start)
                parsed_end = _optional_coordinate_int(end)
                if parsed_start is not None and parsed_end is not None:
                    spans.add((parsed_start, parsed_end))
        source_span = reference.get("source_span")
        if isinstance(source_span, Mapping):
            start = _optional_coordinate_int(source_span.get("start"))
            end = _optional_coordinate_int(source_span.get("end"))
            if start is not None and end is not None:
                spans.add((start, end))
        locator_span = locator_parts["char_span"]
        if (
            isinstance(locator_span, tuple)
            and all(isinstance(value, int) for value in locator_span)
        ):
            spans.add(locator_span)
    return len(pages) > 1 or len(spans) > 1


def _reference_matches_block(
    reference: Mapping[str, Any],
    structure: Mapping[str, Any],
    block: Mapping[str, Any],
    *,
    quote_mode: str,
) -> str | None:
    raw_text = block.get("raw_text")
    span = block.get("source_span")
    if not isinstance(raw_text, str) or not isinstance(span, Mapping):
        return "source block raw text/span is unavailable"
    span_page = _optional_coordinate_int(span.get("page_number"))
    span_start = _optional_coordinate_int(span.get("start"))
    span_end = _optional_coordinate_int(span.get("end"))
    block_page = _optional_coordinate_int(block.get("page_number"))
    if (
        span_page is None
        or span_start is None
        or span_end is None
        or span_start < 0
        or span_end < span_start
        or block_page != span_page
    ):
        return "source block has an invalid raw span"
    pages = structure.get("pages")
    matching_pages = [
        page
        for page in pages
        if isinstance(page, Mapping)
        and _optional_coordinate_int(page.get("page_number")) == span_page
    ] if isinstance(pages, list) else []
    if len(matching_pages) != 1:
        return "source block page text is unavailable or ambiguous"
    page_raw_text = matching_pages[0].get("raw_text")
    if not isinstance(page_raw_text, str):
        return "source block page text is unavailable or ambiguous"
    if page_raw_text[span_start:span_end] != raw_text:
        return "source block span does not select its raw text"

    quote = str(reference.get("quote") or reference.get("content") or "")
    quote = quote.strip()
    if not quote:
        return "source reference has no quote"
    if quote_mode == "exact" and quote != raw_text.strip():
        return "source reference quote conflicts with source raw line"
    if quote_mode == "substring" and quote not in raw_text:
        return "text fallback quote is not supported by source raw text"

    for field in ("page", "page_number"):
        value = reference.get(field)
        if value in (None, ""):
            continue
        claimed_page = _optional_coordinate_int(value)
        if claimed_page is None:
            return "source reference has an invalid page"
        if claimed_page != span_page:
            return "source reference page conflicts with source block span"
    locator_parts = _source_reference_locator_parts(reference)
    locator_page = locator_parts["page_number"]
    if locator_page is not None and locator_page != span_page:
        return "source locator page conflicts with source block span"

    span_claims: list[tuple[int, int]] = []
    char_start = reference.get("char_start")
    char_end = reference.get("char_end")
    if char_start not in (None, "") or char_end not in (None, ""):
        parsed_start = _optional_coordinate_int(char_start)
        parsed_end = _optional_coordinate_int(char_end)
        if parsed_start is None or parsed_end is None:
            return "source reference has an incomplete character span"
        span_claims.append((parsed_start, parsed_end))
    reference_span = reference.get("source_span")
    if reference_span not in (None, ""):
        if not isinstance(reference_span, Mapping):
            return "source reference has an invalid source span"
        nested_start = reference_span.get("start")
        nested_end = reference_span.get("end")
        if nested_start not in (None, "") or nested_end not in (None, ""):
            parsed_start = _optional_coordinate_int(nested_start)
            parsed_end = _optional_coordinate_int(nested_end)
            if parsed_start is None or parsed_end is None:
                return "source reference has an incomplete character span"
            span_claims.append((parsed_start, parsed_end))
        nested_page = reference_span.get("page_number")
        if nested_page not in (None, ""):
            parsed_page = _optional_coordinate_int(nested_page)
            if parsed_page is None or parsed_page != span_page:
                return "source reference page conflicts with source block span"
    locator_span = locator_parts["char_span"]
    if isinstance(locator_span, tuple):
        if not all(isinstance(value, int) for value in locator_span):
            return "source locator has an invalid character span"
        span_claims.append(locator_span)
    if any(claim != (span_start, span_end) for claim in span_claims):
        return "source reference character span conflicts with source block span"
    return None


def _source_coordinates_unverified(
    structure: Mapping[str, Any],
    block: Mapping[str, Any],
) -> bool:
    metadata = structure.get("metadata")
    statuses = {
        str(block.get("source_coordinate_status") or ""),
        str(structure.get("source_coordinate_status") or ""),
        str(metadata.get("source_coordinate_status") or "")
        if isinstance(metadata, Mapping)
        else "",
    }
    scopes = {
        str(block.get("source_coordinate_scope") or ""),
        str(structure.get("source_coordinate_scope") or ""),
    }
    return (
        "section_relative_unverified" in statuses
        or "section_relative" in scopes
    )


def _positive_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _candidate_filter_reason(block: Mapping[str, Any]) -> str:
    text = str(block.get("raw_text") or block.get("normalized_text") or "")
    candidate = _clean_candidate_line(text)
    if _is_heading_line(re.sub(r"\s+", " ", text).strip()):
        return "heading"
    if _is_noise(candidate):
        return "noise"
    if _is_layout_noise(candidate):
        return "layout_noise"
    if len(candidate) < 6:
        return "short"
    if len(candidate) > 500:
        return "too_long"
    return "not_selected_or_source_unmapped"


def _candidate_ids_for_record(
    text: str,
    references: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> list[str]:
    reference_keys = {
        _candidate_reference_key(reference)
        for reference in references
        if isinstance(reference, Mapping)
    }
    matches = [
        candidate["candidate_id"]
        for candidate in candidates
        if reference_keys
        & {
            _candidate_reference_key(reference)
            for reference in candidate["source_references"]
            if isinstance(reference, Mapping)
        }
    ]
    if matches:
        return matches
    normalized = _normalize(text)
    text_matches = [
        candidate["candidate_id"]
        for candidate in candidates
        if (candidate_normalized := _normalize(candidate["candidate_text"]))
        and candidate_normalized == normalized
    ]
    return text_matches if len(text_matches) == 1 else []


def _candidate_reference_key(reference: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(reference.get("document_id") or ""),
        str(
            reference.get("source_version")
            or reference.get("source_file_version")
            or ""
        ),
        reference.get("page"),
        str(reference.get("locator") or ""),
        str(reference.get("quote") or ""),
    )


def _set_candidate_outcome(
    candidate_results: dict[str, list[dict[str, Any]]],
    candidate_ids: list[str],
    outcome: str,
    generated_id: str | None = None,
) -> None:
    for candidate_id in candidate_ids:
        result = {
            "outcome": outcome,
            "generated_ids": [generated_id] if generated_id else [],
        }
        results = candidate_results.setdefault(candidate_id, [])
        if result not in results:
            results.append(result)


def _candidate_lines(text: str) -> list[str]:
    return [line for line, _references in _candidate_records([{"content": text}])]


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
                page_number = _reference_page_number(reference)
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
    seen: set[tuple[Any, ...]] = set()
    for reference in [*first, *second]:
        source_span = reference.get("source_span")
        key = (
            str(reference.get("document_id") or ""),
            reference.get("page"),
            str(reference.get("locator") or ""),
            str(
                reference.get("source_version")
                or reference.get("source_file_version")
                or ""
            ),
            str(reference.get("quote") or reference.get("content") or ""),
            reference.get("char_start"),
            reference.get("char_end"),
            repr(source_span),
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
        locator = str(item.get("locator") or "")
        locator_parts = _source_reference_locator_parts(item)
        explicit_line = _optional_coordinate_int(item.get("line_number"))
        precise_reference = (
            locator_parts["line_number"] is not None
            or explicit_line is not None
            or locator_parts["char_span"] is not None
            or item.get("char_start") not in (None, "")
            or item.get("char_end") not in (None, "")
            or isinstance(item.get("source_span"), Mapping)
        )
        precise_line = locator_parts["line_number"] or explicit_line
        if precise_line is not None and precise_line != line_number:
            continue
        if precise_reference:
            if not locator:
                item["locator"] = f"p{page_number}:l{line_number}"
        else:
            if fragment:
                item["quote"] = raw_line.strip()
            item["locator"] = f"{locator}:l{line_number}" if locator else (
                f"p{page_number}:l{line_number}"
            )
        result.append(item)
    return result


def _reference_page_number(reference: Mapping[str, Any]) -> int:
    for key in ("page", "page_number"):
        value = reference.get(key)
        if value not in (None, ""):
            page_number = _optional_coordinate_int(value)
            return page_number if page_number is not None else 1
    locator_page = _source_reference_locator_parts(reference)["page_number"]
    return locator_page if locator_page is not None else 1


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
