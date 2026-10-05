from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import shutil
from typing import Any

import pytest

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.core.files import ProjectFileRegistry
from qiaowenshu_agent.skills.local_backends import (
    RegistryBidderMaterialBackend,
    RegistryTenderDecompositionBackend,
    _material_metadata,
)
from qiaowenshu_agent.skills.tender_decomposition import TenderDecompositionSkill


FIXTURE_ROOT = Path(__file__).parent / "标书Agent全流程模拟测试包_v1"
PDF_TEXT_AVAILABLE = bool(
    shutil.which("pdftotext") or shutil.which("pdftotext.exe")
)


def _context(
    *, registry: ProjectFileRegistry | None = None
) -> SkillContext:
    request = SkillRequest.create()
    services = {"file_registry": registry} if registry is not None else {}
    return SkillContext(
        run_id="local-parser-reliability",
        request=request,
        services=services,
    )


def _decompose(text: str) -> dict[str, Any]:
    return RegistryTenderDecompositionBackend().run(
        {"sections": [{"title": "tender.txt", "content": text}]},
        _context(),
    )


def test_original_two_line_regression_finds_qualification_and_score_ceiling() -> None:
    result = _decompose(
        "投标人应具有独立承担民事责任的能力\n"
        "每个合同得2分，最高10分"
    )

    assert len(result["requirements"]) == 1
    requirement = result["requirements"][0]
    assert requirement["category"] == "qualification"
    assert requirement["mandatory"] is True
    assert requirement["evidence_required"] == ["business_license"]
    assert len(result["scoring_items"]) == 1
    assert result["scoring_items"][0]["max_score"] == 10
    assert result["warnings"] == []
    assert result["extraction_complete"] is False
    assert result["needs_human_review"] is True
    assert result["business_status"] == "needs_review"


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("评分标准：每个合同得2分，最高10分", 10),
        ("技术方案可得0.5分，满分为2.5分", 2.5),
        ("同类项目每项0.5分，累计不超过3.5分", 3.5),
        ("综合评价按1.5-4.5分区间计分", 4.5),
    ],
)
def test_explicit_score_ceiling_is_selected(line: str, expected: float) -> None:
    result = _decompose(line)

    assert len(result["scoring_items"]) == 1
    assert result["scoring_items"][0]["max_score"] == expected


@pytest.mark.parametrize(
    "line",
    [
        "每个合同得2分，无上限",
        "每个项目得2分",
    ],
)
def test_unknown_score_ceiling_is_not_promoted_to_max_score(line: str) -> None:
    result = _decompose(line)

    assert result["scoring_items"] == []
    assert any(line in warning for warning in result["warnings"])
    assert result["needs_human_review"] is True
    assert result["business_status"] == "needs_review"


@pytest.mark.parametrize(
    "line",
    [
        "资质满分6分；业绩最高10分",
        "该项最高10分且不超过8分",
    ],
)
def test_conflicting_score_ceilings_are_not_resolved_by_taking_the_maximum(
    line: str,
) -> None:
    result = _decompose(line)

    assert result["scoring_items"] == []
    assert any(line in warning for warning in result["warnings"])
    assert result["needs_human_review"] is True
    assert result["business_status"] == "needs_review"


def test_score_continuation_across_pages_keeps_each_page_reference() -> None:
    sections = [
        {
            "title": "scoring.txt",
            "content": "类似项目业绩：每个合同得\f2分，最高\f10分",
            "source_references": [
                {
                    "document_id": "scoring.txt",
                    "page": page,
                    "locator": f"source:p{page}",
                    "quote": quote,
                }
                for page, quote in (
                    (1, "类似项目业绩：每个合同得"),
                    (2, "2分，最高"),
                    (3, "10分"),
                )
            ],
        }
    ]
    result = RegistryTenderDecompositionBackend().run(
        {"sections": sections},
        _context(),
    )

    assert len(result["scoring_items"]) == 1
    score = result["scoring_items"][0]
    assert score["max_score"] == 10
    assert {item["page"] for item in score["source_references"]} == {1, 2, 3}


def test_ordinary_company_description_is_not_promoted_to_qualification() -> None:
    result = _decompose(
        "企业介绍：本公司具有多年行业服务经验和丰富项目经验。\n"
        "采购人具有独立法人资格。\n"
        "系统展示供应商依法设立的信息。"
    )

    assert result["requirements"] == []
    assert result["scoring_items"] == []


@pytest.mark.parametrize(
    ("line", "evidence"),
    [
        ("投标人应具有独立承担民事责任的能力", "business_license"),
        ("供应商须依法设立并具有履行合同所必需的设备和专业技术能力", "qualification"),
        ("投标人应具有良好的商业信誉和健全的财务会计制度", "credit"),
    ],
)
def test_common_eligibility_phrases_are_mandatory_requirements(
    line: str, evidence: str
) -> None:
    result = _decompose(line)

    assert len(result["requirements"]) == 1
    requirement = result["requirements"][0]
    assert requirement["category"] == "qualification"
    assert requirement["mandatory"] is True
    assert evidence in requirement["evidence_required"]


@pytest.mark.parametrize(
    "standard",
    ["ISO27001", "ISO/IEC27001", "ISO/IEC 27001"],
)
def test_iso_standard_number_is_a_specific_evidence_unit_and_rule(
    standard: str,
) -> None:
    result = _decompose(f"投标人须提供有效{standard}认证")

    requirement = result["requirements"][0]
    assert requirement["evidence_required"] == ["ISO27001"]
    assert requirement["check_rule"] == {
        "rule_ast": {
            "op": "exists",
            "evidence_types": ["ISO27001"],
            "where": {"verification_status": "verified"},
        }
    }


def test_clarification_section_is_preserved_and_requires_review() -> None:
    result = RegistryTenderDecompositionBackend().run(
        {
            "sections": [
                {
                    "title": "tender.txt",
                    "kind": "tender",
                    "content": "日志保存不少于90天",
                },
                {
                    "title": "更正公告.txt",
                    "kind": "clarification",
                    "content": "日志保存调整为不少于180天",
                },
            ]
        },
        _context(),
    )

    assert any("更正公告.txt" in warning for warning in result["warnings"])
    assert result["needs_human_review"] is True
    assert result["business_status"] == "needs_review"
    descriptions = [item["description"] for item in result["requirements"]]
    assert any("90天" in item for item in descriptions)
    assert any("180天" in item for item in descriptions)


@pytest.mark.asyncio
async def test_structured_decomposition_keeps_legacy_status_shape() -> None:
    request = SkillRequest.create(
        {
            "project_id": "structured",
            "requirements": [
                {
                    "requirement_id": "R-1",
                    "category": "qualification",
                    "title": "营业执照",
                    "description": "提供营业执照",
                    "mandatory": True,
                }
            ],
        }
    )
    result = await TenderDecompositionSkill(
        backend=RegistryTenderDecompositionBackend()
    ).execute(request, _context())

    assert result.status == "success"
    assert result.data["warnings"] == []
    assert "needs_human_review" not in result.data
    assert "business_status" not in result.data
    assert "extraction_complete" not in result.data


@pytest.mark.parametrize(
    ("file_name", "text", "expected_yuan", "expected_original_unit"),
    [
        ("contract.txt", "合同金额：135万元", "1350000", "万元"),
        ("contract.txt", "合同金额：90万", "900000", "万"),
        ("bond.txt", "保证金金额：40,000元", "40000", "元"),
        ("bond.txt", "缴纳金额：30000元", "30000", "元"),
        ("contract.txt", "项目金额：1.25万元", "12500", "万元"),
    ],
)
def test_material_amount_is_normalized_to_exact_yuan_strings(
    file_name: str,
    text: str,
    expected_yuan: str,
    expected_original_unit: str,
) -> None:
    registry = ProjectFileRegistry()
    registration = registry.register(
        project_id="amount-project",
        file_name=file_name,
        file_role="bidder_material",
        content=text.encode("utf-8"),
    )
    result = RegistryBidderMaterialBackend().run(
        {"bidder_id": "bidder", "file_ids": [registration.file.file_id]},
        _context(registry=registry),
    )
    metadata = result["bidder_profile"]["materials"][0]["metadata"]

    assert Decimal(metadata["amount"]) == Decimal(expected_yuan)
    assert metadata["amount_original_unit"] == expected_original_unit
    assert metadata["amount_unit"] == "元"


def test_unparseable_amount_warns_and_does_not_invent_a_value() -> None:
    registry = ProjectFileRegistry()
    registration = registry.register(
        project_id="amount-review",
        file_name="合同金额.txt",
        file_role="bidder_material",
        content="合同金额：人民币叁拾万元".encode("utf-8"),
    )
    result = RegistryBidderMaterialBackend().run(
        {"bidder_id": "bidder", "file_ids": [registration.file.file_id]},
        _context(registry=registry),
    )
    metadata = result["bidder_profile"]["materials"][0]["metadata"]

    assert "amount" not in metadata
    assert metadata["verification_status"] == "unknown"
    assert result["warnings"]
    assert any("需人工核验" in item for item in result["warnings"])


@pytest.mark.parametrize(
    "text",
    [
        "合同金额：未提供。\n保证金金额：40000元",
        "合同金额：-40000元",
    ],
)
def test_unknown_or_negative_amount_does_not_leak_or_parse(
    text: str,
) -> None:
    registry = ProjectFileRegistry()
    registration = registry.register(
        project_id="amount-field-boundary",
        file_name="合同材料.txt",
        file_role="bidder_material",
        content=text.encode("utf-8"),
    )
    result = RegistryBidderMaterialBackend().run(
        {"bidder_id": "bidder", "file_ids": [registration.file.file_id]},
        _context(registry=registry),
    )
    metadata = result["bidder_profile"]["materials"][0]["metadata"]

    assert "amount" not in metadata
    assert metadata["verification_status"] == "unknown"
    assert result["warnings"]
    assert any("需人工核验" in item for item in result["warnings"])


@pytest.mark.skipif(
    not PDF_TEXT_AVAILABLE,
    reason="Poppler pdftotext is required for raw PDF regression",
)
@pytest.mark.parametrize(
    ("prefix", "expected_type", "expected_amount", "expected_status"),
    [
        ("06_类似项目合同_A", "contract", "1350000", "unknown"),
        ("07_类似项目合同_B", "contract", "900000", "unknown"),
        ("10A_投标保证金", "bid_bond", "40000", "unknown"),
        ("10B_投标保证金", "bid_bond", "30000", "invalid"),
    ],
)
def test_original_pdf_mixed_footer_amount_and_type_fields(
    prefix: str,
    expected_type: str,
    expected_amount: str,
    expected_status: str,
) -> None:
    source = next(FIXTURE_ROOT.glob(f"{prefix}*.pdf"))
    registry = ProjectFileRegistry()
    registration = registry.register_path(
        project_id=f"raw-pdf-{prefix}",
        path=source,
        file_role="bidder_material",
    )
    result = RegistryBidderMaterialBackend().run(
        {"bidder_id": "bidder", "file_ids": [registration.file.file_id]},
        _context(registry=registry),
    )
    material = result["bidder_profile"]["materials"][0]
    metadata = material["metadata"]

    assert material["material_type"] == expected_type
    assert metadata["amount"] == expected_amount
    assert metadata["amount_unit"] == "元"
    assert metadata["amount_original_unit"] == "元"
    assert metadata["verification_status"] == expected_status
    if expected_type == "bid_bond":
        assert metadata["bid_bond_amount"] == expected_amount


def test_insufficient_bond_context_does_not_replace_transaction_amount() -> None:
    registry = ProjectFileRegistry()
    registration = registry.register(
        project_id="bond-insufficient-context",
        file_name="保证金回单.txt",
        file_role="bidder_material",
        content=(
            "交易金额：人民币 30,000.00 元\n"
            "注意：本回单金额低于招标文件要求的 40,000 元。\n"
            "仅用于标书 Agent 流程测试，不代表真实主体或真实证照"
        ).encode("utf-8"),
    )
    result = RegistryBidderMaterialBackend().run(
        {"bidder_id": "bidder", "file_ids": [registration.file.file_id]},
        _context(registry=registry),
    )
    material = result["bidder_profile"]["materials"][0]
    metadata = material["metadata"]

    assert material["material_type"] == "bid_bond"
    assert metadata["amount"] == "30000"
    assert metadata["bid_bond_amount"] == "30000"
    assert metadata["verification_status"] == "invalid"


def test_ambiguous_validity_language_does_not_verify_material() -> None:
    registry = ProjectFileRegistry()
    registration = registry.register(
        project_id="validity-review",
        file_name="认证材料.txt",
        file_role="bidder_material",
        content="材料有效性仍需审核".encode("utf-8"),
    )
    result = RegistryBidderMaterialBackend().run(
        {"bidder_id": "bidder", "file_ids": [registration.file.file_id]},
        _context(registry=registry),
    )
    metadata = result["bidder_profile"]["materials"][0]["metadata"]

    assert metadata["verification_status"] == "unknown"
    assert metadata.get("status") != "valid"
    assert any("需人工核验" in item for item in result["warnings"])


@pytest.mark.parametrize(
    "text",
    [
        "有效ISO27001认证状态：有效",
        "ISO27001认证状态：有效",
        "ISO/IEC27001认证状态：有效",
        "ISO/IEC 27001认证状态：有效",
        "ISO9001认证状态：有效",
    ],
)
def test_iso_certificate_metadata_accepts_and_normalizes_standard_forms(
    text: str,
) -> None:
    metadata = _material_metadata(
        "certification",
        "certificate.txt",
        text,
    )

    assert metadata["verification_status"] == "verified"
    assert metadata["certificate_type"] == (
        "ISO9001" if "9001" in text else "ISO27001"
    )


def test_invalid_or_insufficient_status_never_becomes_verified() -> None:
    metadata = _material_metadata(
        "bid_bond",
        "bond.txt",
        "投标保证金金额不足，未达到要求",
    )

    assert metadata["verification_status"] == "invalid"
    assert metadata["status"] == "invalid"
