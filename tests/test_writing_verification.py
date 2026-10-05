from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

import pytest

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.skills.document_writing import DocumentWritingSkill
from qiaowenshu_agent.skills.document_writing.verification import (
    resolve_as_of,
    scan_high_risk_claims,
)


class FakeWritingLLM:
    def __init__(self, response: Mapping[str, Any]) -> None:
        self.response = dict(response)
        self.calls: list[Sequence[Mapping[str, str]]] = []

    async def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        purpose: str,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        self.calls.append(messages)
        return self.response, SimpleNamespace(usage={"total_tokens": 20})


def _response(content: str, **fields: Any) -> dict[str, Any]:
    return {
        "section_id": "experience",
        "title": "企业能力",
        "content_markdown": content,
        "evidence_used": [],
        "unknowns": [],
        "risk_flags": [],
        "requirement_coverage": [],
        "scoring_coverage": [],
        **fields,
    }


def _material(
    material_id: str,
    title: str,
    content: str,
    *,
    material_type: str = "text",
    valid_until: str | None = "2027-12-31",
    status: str = "valid",
    confidence: float | None = 0.95,
) -> dict[str, Any]:
    reference: dict[str, Any] = {"document_id": f"{material_id}.pdf", "page": 1}
    if confidence is not None:
        reference["confidence"] = confidence
    return {
        "material_id": material_id,
        "material_type": material_type,
        "title": title,
        "content": content,
        "valid_until": valid_until,
        "metadata": {"status": status},
        "source_references": [reference],
    }


def _request_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "project_id": "project-verify",
        "sections": [
            {
                "section_id": "experience",
                "title": "企业能力",
                "requirement_ids": ["req-iso"],
                "scoring_item_ids": ["score-case"],
                "source_references": [{"document_id": "section-source.pdf", "page": 1}],
            }
        ],
        "requirements": [
            {
                "requirement_id": "req-iso",
                "category": "qualification",
                "title": "ISO/IEC 27001",
                "description": "投标人应提供有效ISO/IEC 27001认证。",
                "source_references": [{"document_id": "tender.pdf", "page": 3}],
            },
            {
                "requirement_id": "req-outside-context",
                "category": "other",
                "title": "未传入本章节的要求",
                "description": "不应出现在本章节模型上下文。",
                "source_references": [{"document_id": "outside.pdf", "page": 99}],
            },
        ],
        "scoring_items": [
            {
                "item_id": "score-case",
                "title": "类似项目案例",
                "criteria": "企业类似项目经验",
                "max_score": 10,
                "source_references": [{"document_id": "score.pdf", "page": 4}],
            },
            {
                "item_id": "score-outside-context",
                "title": "未传入本章节的评分项",
                "max_score": 5,
            },
        ],
        "materials": [],
        "evidence_matches": [],
    }
    data.update(overrides)
    return data


async def _execute(
    response: Mapping[str, Any],
    **overrides: Any,
) -> Any:
    llm = FakeWritingLLM(response)
    return await DocumentWritingSkill(llm=llm).execute(
        SkillRequest.create(_request_data(**overrides)),
        SkillContext(run_id="verify-test", request=SkillRequest.create()),
    )


@pytest.mark.asyncio
async def test_chinese_adjacent_iso_and_negative_material_do_not_verify_claim() -> None:
    scanned = scan_high_risk_claims("我公司已取得ISO27001认证。")
    assert [claim["category"] for claim in scanned] == ["certification"]

    result = await _execute(
        _response(
            "我公司已取得ISO27001认证。",
            evidence_used=["negative-iso"],
        ),
        materials=[
            _material(
                "negative-iso",
                "ISO27001认证情况",
                "本公司未取得ISO27001认证。",
                material_type="certification",
            )
        ],
    )

    assert result.status == "partial"
    assert result.data["business_status"] == "needs_review"
    assert result.data["needs_human_review"] is True
    assert (
        result.data["chapters"][0]["claim_evidence_mapping"][0]["status"]
        == "unsupported"
    )
    assert result.data["chapters"][0]["claim_evidence_mapping"][0]["rejected_evidence"]
    assert result.data["chapters"][0]["evidence_used"] == []
    assert result.data["chapters"][0]["source_references"] == []


@pytest.mark.asyncio
async def test_original_ground_truth_oracle_blocks_pmp_hallucination() -> None:
    oracle_path = (
        Path(__file__).parent
        / "标书Agent全流程模拟测试包_v1"
        / "13_ground_truth_预期规则与结果.json"
    )
    oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
    assert any(
        "不得虚构PMP证书" in item for item in oracle["anti_hallucination_checks"]
    )

    result = await _execute(
        _response("我公司已取得PMP认证。", unknowns=[]),
    )

    assert result.status == "partial"
    assert result.data["business_status"] == "needs_review"
    assert result.data["needs_human_review"] is True
    assert result.data["submission_allowed"] is False
    claim = result.data["claim_evidence_mapping"][0]
    assert claim["category"] == "personnel_qualification"
    assert claim["status"] == "unsupported"
    assert result.data["unsupported_claims"] == [claim]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "category"),
    [
        ("我公司已取得信息系统项目管理师证书。", "personnel_qualification"),
        ("我公司已取得北辰市三级信息安全资质。", "qualification_assertion"),
    ],
)
async def test_chinese_personnel_and_unknown_qualifications_require_review(
    content: str,
    category: str,
) -> None:
    claims = scan_high_risk_claims(content)
    assert [claim["category"] for claim in claims] == [category]

    result = await _execute(_response(content, unknowns=[]))

    assert result.status == "partial"
    assert result.data["business_status"] == "needs_review"
    assert result.data["claim_evidence_mapping"][0]["status"] == "unsupported"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        "项目经理王某持有PMP认证。",
        "项目经理王某持有信息系统项目管理师证书。",
    ],
)
async def test_named_personnel_qualification_is_supported_by_matching_valid_material(
    content: str,
) -> None:
    result = await _execute(
        _response(content, evidence_used=["manager-qualification"]),
        materials=[
            _material(
                "manager-qualification",
                "项目经理王某人员资质证书",
                content,
                material_type="personnel_certificate",
            )
        ],
    )

    assert result.status == "success", result.data
    assert result.data["business_status"] == "passed"
    claim = next(
        item
        for item in result.data["claim_evidence_mapping"]
        if item["category"] == "personnel_qualification"
    )
    assert claim["status"] == "supported"
    assert claim["evidence"][0]["source_id"] == "manager-qualification"


@pytest.mark.asyncio
async def test_historical_contract_amount_does_not_support_bid_quote() -> None:
    result = await _execute(
        _response(
            "本次投标报价135万元。",
            evidence_used=["past-contract"],
        ),
        materials=[
            _material(
                "past-contract",
                "历史项目合同",
                "历史合同金额135万元。",
                material_type="contract",
            )
        ],
    )

    assert result.status == "partial"
    assert result.data["business_status"] == "needs_review"
    claim = result.data["claim_evidence_mapping"][0]
    assert claim["category"] == "amount"
    assert claim["status"] == "unsupported"
    assert "角色" in claim["reason"] or claim["rejected_evidence"]
    assert result.data["chapters"][0]["source_references"] == []


@pytest.mark.asyncio
async def test_certificate_issue_date_does_not_support_delivery_date() -> None:
    result = await _execute(
        _response("项目交付日期为2026-10-01。", evidence_used=["certificate"]),
        materials=[
            _material(
                "certificate",
                "ISO27001认证证书",
                "ISO27001证书签发日期为2026-10-01。",
                material_type="certification",
            )
        ],
    )

    assert result.status == "partial"
    claim = next(
        item
        for item in result.data["claim_evidence_mapping"]
        if item["category"] == "date"
    )
    assert claim["status"] == "unsupported"
    assert claim["rejected_evidence"]


@pytest.mark.asyncio
async def test_service_durations_must_remain_bound_to_the_same_service() -> None:
    result = await _execute(
        _response(
            "我方承诺提供30天培训并在10天内完成交付。",
            evidence_used=["commitment"],
        ),
        materials=[
            _material(
                "commitment",
                "经批准的服务承诺函",
                "承诺提供10天培训并在30天内完成交付。",
                material_type="service_commitment",
            )
        ],
    )

    assert result.status == "partial"
    claim = next(
        item
        for item in result.data["claim_evidence_mapping"]
        if item["category"] == "service_commitment"
    )
    assert claim["status"] == "unsupported"
    assert claim["rejected_evidence"]


@pytest.mark.asyncio
async def test_real_valid_materials_support_matching_claims() -> None:
    result = await _execute(
        _response(
            "我方已取得ISO27001认证。累计完成30个项目案例。承诺提供7×24小时运维支持。",
            evidence_used=["iso", "cases", "service"],
        ),
        materials=[
            _material(
                "iso",
                "ISO27001认证证书",
                "ISO27001认证有效。",
                material_type="certification",
            ),
            _material(
                "cases",
                "企业案例清单",
                "企业累计完成30个项目案例。",
                material_type="project_cases",
            ),
            _material(
                "service",
                "已批准服务承诺函",
                "承诺提供7×24小时运维支持。",
                material_type="service_commitment",
            ),
        ],
    )

    assert result.status == "success", result.data
    assert result.data["business_status"] == "passed"
    assert result.data["submission_allowed"] is False
    assert {claim["category"] for claim in result.data["claim_evidence_mapping"]} == {
        "certification",
        "case_quantity",
        "service_commitment",
    }
    assert all(
        claim["status"] == "supported"
        for claim in result.data["claim_evidence_mapping"]
    )
    assert result.data["chapters"][0]["evidence_used"] == ["cases", "iso", "service"]
    assert "草案" in result.data["markdown"]
    assert "submission_allowed=false" in result.data["markdown"]


@pytest.mark.asyncio
async def test_unreviewed_bidder_profile_and_unapproved_fact_are_not_evidence() -> None:
    result = await _execute(
        _response("我方已取得ISO27001认证。"),
        bidder_profile={
            "bidder_id": "bidder-1",
            "attributes": {"certification": "ISO27001"},
            "confirmed_facts": [
                {"fact_id": "self-report", "text": "已取得ISO27001认证"}
            ],
        },
        confirmed_facts=[{"fact_id": "no-status", "text": "我方已取得ISO27001认证"}],
    )

    assert result.status == "partial"
    assert result.data["business_status"] == "needs_review"
    assert result.data["claim_evidence_mapping"][0]["status"] == "unsupported"


@pytest.mark.asyncio
async def test_tender_requirement_does_not_verify_bidder_qualification() -> None:
    result = await _execute(
        _response("我方具备有效ISO27001认证。"),
        materials=[],
    )

    assert result.status == "partial"
    assert result.data["claim_evidence_mapping"][0]["status"] == "unsupported"
    assert result.data["claim_evidence_mapping"][0]["evidence"] == []


@pytest.mark.asyncio
async def test_tender_requirement_statement_can_be_verified_only_as_tender_fact() -> (
    None
):
    result = await _execute(
        _response("招标文件要求投标人提供有效ISO/IEC 27001认证。"),
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert claim["status"] == "supported"
    assert claim["scope"] == "tender_requirement_only"
    assert claim["supports_enterprise_fact"] is False


@pytest.mark.asyncio
async def test_ids_are_context_scoped_and_empty_coverage_adds_no_refs() -> None:
    invalid = await _execute(
        _response(
            "本章为一般性方案说明。",
            section_id="other-section",
            evidence_used=["ghost"],
            requirement_coverage=["req-outside-context"],
            scoring_coverage=["score-outside-context"],
        ),
        materials=[_material("real", "材料", "已确认。")],
    )
    assert invalid.status == "partial"
    assert invalid.data["business_status"] == "failed"
    assert invalid.data["chapters"][0]["source_references"] == []
    assert {item["code"] for item in invalid.data["verification_findings"]} >= {
        "invalid_section_id",
        "unknown_evidence_used_id",
        "unknown_requirement_coverage_id",
        "unknown_scoring_coverage_id",
    }

    empty_coverage = await _execute(_response("本章为一般性方案说明。"))
    assert empty_coverage.data["chapters"][0]["source_references"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "valid_until", "confidence"),
    [
        ("unknown", "2027-12-31", 0.95),
        ("valid", "2025-12-31", 0.95),
        ("valid", "2027-12-31", 0.4),
    ],
)
async def test_unknown_expired_or_low_confidence_material_never_verifies(
    status: str,
    valid_until: str,
    confidence: float,
) -> None:
    result = await _execute(
        _response("我方已取得ISO27001认证。", evidence_used=["iso"]),
        materials=[
            _material(
                "iso",
                "ISO27001认证证书",
                "ISO27001认证有效。",
                material_type="certification",
                valid_until=valid_until,
                status=status,
                confidence=confidence,
            )
        ],
        as_of="2026-10-05",
    )

    assert result.status == "partial"
    assert result.data["claim_evidence_mapping"][0]["status"] == "unsupported"
    assert result.data["chapters"][0]["evidence_used"] == []


@pytest.mark.asyncio
async def test_tender_deadline_is_validity_date_and_is_reported() -> None:
    result = await _execute(
        _response("我方已取得ISO27001认证。", evidence_used=["iso"]),
        tender_profile={"key_dates": {"bid_deadline": "2026-10-10 09:30"}},
        materials=[
            _material(
                "iso",
                "ISO27001认证证书",
                "ISO27001认证有效。",
                material_type="certification",
                valid_until="2026-10-08",
            )
        ],
    )

    assert result.status == "partial"
    assert result.data["verification_as_of"] == {
        "date": "2026-10-10",
        "basis": "tender_bid_deadline",
    }
    assert result.data["claim_evidence_mapping"][0]["status"] == "unsupported"


def test_explicit_as_of_is_validated_and_overrides_tender_deadline() -> None:
    deadline = {"key_dates": {"bid_deadline": "2026-10-10"}}
    chosen, basis = resolve_as_of("2026-10-05", deadline)
    assert chosen == date(2026, 10, 5)
    assert basis == "request_as_of"
    with pytest.raises(ValueError, match="as_of"):
        resolve_as_of("2026-02-30", deadline)


def test_case_quantity_requires_explicit_count_unit_and_context() -> None:
    contract_claims = scan_high_risk_claims("历史项目合同金额135万元。")
    certificate_claims = scan_high_risk_claims("项目经理证书编号123456。")
    valid_claims = scan_high_risk_claims("累计完成30个项目案例。")

    assert [item["category"] for item in contract_claims] == ["amount"]
    assert "case_quantity" not in {item["category"] for item in certificate_claims}
    assert [item["category"] for item in valid_claims] == ["case_quantity"]
