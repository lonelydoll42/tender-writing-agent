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
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            {
                **_material(
                    "negative-iso",
                    "ISO27001认证情况",
                    "本公司未取得ISO27001认证。",
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder": "甲公司",
                    "certificate_type": "ISO27001",
                },
            }
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
async def test_company_case_quantity_from_another_owner_is_not_supported() -> None:
    result = await _execute(
        _response(
            "我司累计承接三十项大型政务项目。",
            evidence_used=["MAT-CASE-BETA"],
            unknowns=[],
            risk_flags=[],
        ),
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            {
                **_material(
                    "MAT-CASE-BETA",
                    "乙公司政务项目业绩汇总",
                    "主体：乙公司。经合同台账核对，累计承接三十项大型政务项目。",
                    material_type="project_cases",
                ),
                "metadata": {"status": "valid", "owner_name": "乙公司"},
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert claim["subject_check"]["status"] == "conflict"
    assert claim["subject_check"]["metadata_owner"]["names"] == ["乙公司"]


@pytest.mark.asyncio
async def test_body_attributed_other_owner_cannot_support_case_quantity() -> None:
    result = await _execute(
        _response(
            "我司累计承接三十项大型政务项目。",
            evidence_used=["idsource"],
            unknowns=[],
            risk_flags=[],
        ),
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            _material(
                "idsource",
                "乙公司业绩",
                "乙公司累计承接三十项大型政务项目。",
                material_type="project_cases",
            )
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert claim["subject_check"]["status"] == "conflict"
    assert claim["subject_check"]["body_owners"][0]["names"] == ["乙公司"]


@pytest.mark.asyncio
async def test_company_contract_amount_from_another_owner_is_not_supported() -> None:
    result = await _execute(
        _response(
            "我司合同金额为135万元。",
            evidence_used=["MAT-CONTRACT-BETA"],
            unknowns=[],
            risk_flags=[],
        ),
        sections=[{"section_id": "experience", "title": "项目经验"}],
        requirements=[],
        scoring_items=[],
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            {
                **_material(
                    "MAT-CONTRACT-BETA",
                    "乙公司合同台账",
                    "主体：乙公司。合同金额为135万元。",
                    material_type="contract",
                ),
                "metadata": {"status": "valid", "owner_name": "乙公司"},
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert claim["subject_check"]["status"] == "conflict"
    assert claim["subject_check"]["metadata_owner"]["names"] == ["乙公司"]


@pytest.mark.asyncio
async def test_body_attributed_other_owner_cannot_support_contract_amount() -> None:
    result = await _execute(
        _response(
            "我司历史项目合同金额135万元。",
            evidence_used=["MAT-CONTRACT-BETA"],
            unknowns=[],
            risk_flags=[],
        ),
        sections=[{"section_id": "experience", "title": "项目经验"}],
        requirements=[],
        scoring_items=[],
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            _material(
                "MAT-CONTRACT-BETA",
                "乙公司台账",
                "乙公司历史项目合同金额135万元。",
                material_type="text",
            )
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert claim["subject_check"]["status"] == "conflict"
    assert claim["subject_check"]["body_owners"][0]["names"] == ["乙公司"]


@pytest.mark.asyncio
async def test_body_attributed_same_owner_supports_contract_amount() -> None:
    result = await _execute(
        _response(
            "我司历史项目合同金额135万元。",
            evidence_used=["MAT-CONTRACT-ALPHA"],
            unknowns=[],
            risk_flags=[],
        ),
        sections=[{"section_id": "experience", "title": "项目经验"}],
        requirements=[],
        scoring_items=[],
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            _material(
                "MAT-CONTRACT-ALPHA",
                "甲公司台账",
                "甲公司历史项目合同金额135万元。",
                material_type="text",
            )
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "success", result.data
    assert claim["status"] == "supported"
    assert claim["subject_check"]["status"] == "matched"
    assert claim["subject_check"]["body_owners"][0]["names"] == ["甲公司"]


@pytest.mark.asyncio
async def test_numeric_source_metadata_and_body_owner_conflict_is_not_support() -> None:
    result = await _execute(
        _response(
            "我司合同金额为135万元。",
            evidence_used=["MAT-CONTRACT-CONFLICT"],
            unknowns=[],
            risk_flags=[],
        ),
        sections=[{"section_id": "experience", "title": "项目经验"}],
        requirements=[],
        scoring_items=[],
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            {
                **_material(
                    "MAT-CONTRACT-CONFLICT",
                    "甲公司台账",
                    "乙公司历史项目合同金额135万元。",
                    material_type="text",
                ),
                "metadata": {"status": "valid", "owner_name": "甲公司"},
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert claim["subject_check"]["status"] == "conflict"
    assert claim["subject_check"]["metadata_owner"]["names"] == ["甲公司"]
    assert claim["subject_check"]["body_owners"][0]["names"] == ["乙公司"]


@pytest.mark.asyncio
@pytest.mark.parametrize("id_location", ["metadata", "body"])
async def test_numeric_owner_registration_id_conflict_is_not_hidden_by_name(
    id_location: str,
) -> None:
    bidder_id = "91310000MA1A111111"
    evidence_id = "91320000MA1A222222"
    if id_location == "metadata":
        material = {
            **_material(
                "MAT-CONTRACT-ID-CONFLICT",
                "甲公司台账",
                "甲公司历史项目合同金额135万元。",
                material_type="text",
            ),
            "metadata": {
                "status": "valid",
                "owner_name": "甲公司",
                "unified_social_credit_code": evidence_id,
            },
        }
    else:
        material = {
            **_material(
                "MAT-CONTRACT-ID-CONFLICT",
                "甲公司台账",
                (
                    "主体：甲公司。统一社会信用代码："
                    f"{evidence_id}。历史项目合同金额135万元。"
                ),
                material_type="text",
            ),
            "metadata": {"status": "valid", "owner_name": "甲公司"},
        }
    result = await _execute(
        _response(
            "我司历史项目合同金额135万元。",
            evidence_used=["MAT-CONTRACT-ID-CONFLICT"],
            unknowns=[],
            risk_flags=[],
        ),
        sections=[{"section_id": "experience", "title": "项目经验"}],
        requirements=[],
        scoring_items=[],
        bidder_profile={
            "bidder_name": "甲公司",
            "unified_social_credit_code": bidder_id,
        },
        materials=[material],
    )

    claim = result.data["claim_evidence_mapping"][0]
    subject = claim["subject_check"]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert subject["status"] == "conflict"
    if id_location == "metadata":
        assert subject["metadata_owner"]["registration_ids"] == [evidence_id]
    else:
        assert subject["body_owners"][0]["registration_ids"] == [evidence_id]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claim_text", "material_id", "material_title", "material_content", "location"),
    [
        (
            "我司累计承接三十项大型政务项目。",
            "MAT-CASE-ID-MATCH",
            "甲公司业绩",
            "甲公司累计承接三十项大型政务项目。",
            "metadata",
        ),
        (
            "我司历史项目合同金额135万元。",
            "MAT-AMOUNT-ID-MATCH",
            "甲公司台账",
            "甲公司历史项目合同金额135万元。",
            "metadata",
        ),
        (
            "我司历史项目合同金额135万元。",
            "MAT-AMOUNT-BODY-ID-MATCH",
            "甲公司台账",
            (
                "主体：甲公司。统一社会信用代码："
                "91310000MA1A111111。历史项目合同金额135万元。"
            ),
            "body",
        ),
    ],
)
async def test_numeric_owner_matching_registration_id_supports_claim(
    claim_text: str,
    material_id: str,
    material_title: str,
    material_content: str,
    location: str,
) -> None:
    bidder_id = "91310000MA1A111111"
    metadata: dict[str, Any] = {"status": "valid", "owner_name": "甲公司"}
    if location == "metadata":
        metadata["unified_social_credit_code"] = bidder_id
    result = await _execute(
        _response(
            claim_text,
            evidence_used=[material_id],
            unknowns=[],
            risk_flags=[],
        ),
        sections=[{"section_id": "experience", "title": "项目经验"}],
        requirements=[],
        scoring_items=[],
        bidder_profile={
            "bidder_name": "甲公司",
            "unified_social_credit_code": bidder_id,
        },
        materials=[
            {
                **_material(
                    material_id,
                    material_title,
                    material_content,
                    material_type=(
                        "project_cases"
                        if material_id.startswith("MAT-CASE")
                        else "text"
                    ),
                ),
                "metadata": metadata,
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "success", result.data
    assert claim["status"] == "supported"
    assert claim["subject_check"]["status"] == "matched"
    assert claim["subject_check"]["matching_basis"] == "registration_id"
    identity = (
        claim["subject_check"]["metadata_owner"]
        if location == "metadata"
        else claim["subject_check"]["body_owners"][0]
    )
    assert identity["registration_ids"] == [bidder_id]


@pytest.mark.asyncio
async def test_unattributed_numeric_source_registration_id_requires_review() -> None:
    bidder_id = "91310000MA1A111111"
    other_id = "91320000MA1A222222"
    result = await _execute(
        _response(
            "我司历史项目合同金额135万元。",
            evidence_used=["MAT-CONTRACT-ID-UNKNOWN"],
            unknowns=[],
            risk_flags=[],
        ),
        sections=[{"section_id": "experience", "title": "项目经验"}],
        requirements=[],
        scoring_items=[],
        bidder_profile={
            "bidder_name": "甲公司",
            "unified_social_credit_code": bidder_id,
        },
        materials=[
            {
                **_material(
                    "MAT-CONTRACT-ID-UNKNOWN",
                    "甲公司台账",
                    "甲公司历史项目合同金额135万元。",
                    material_type="text",
                ),
                "metadata": {
                    "status": "valid",
                    "unified_social_credit_code": other_id,
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    subject = claim["subject_check"]
    assert result.status == "partial"
    assert claim["status"] == "needs_review"
    assert subject["status"] == "unknown"
    assert subject["unassigned_registration_ids"]["metadata"] == [other_id]


@pytest.mark.asyncio
async def test_numeric_source_issuer_registration_id_is_not_borrowed_by_owner() -> None:
    bidder_id = "91310000MA1A111111"
    issuer_id = "91320000MA1A222222"
    result = await _execute(
        _response(
            "我司历史项目合同金额135万元。",
            evidence_used=["MAT-CONTRACT-ISSUER"],
            unknowns=[],
            risk_flags=[],
        ),
        sections=[{"section_id": "experience", "title": "项目经验"}],
        requirements=[],
        scoring_items=[],
        bidder_profile={
            "bidder_name": "甲公司",
            "unified_social_credit_code": bidder_id,
        },
        materials=[
            {
                **_material(
                    "MAT-CONTRACT-ISSUER",
                    "甲公司台账",
                    "甲公司历史项目合同金额135万元。",
                    material_type="text",
                ),
                "metadata": {
                    "status": "valid",
                    "owner_name": "甲公司",
                    "issuer_name": "认证机构",
                    "issuer_registration_id": issuer_id,
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    subject = claim["subject_check"]
    assert result.status == "success", result.data
    assert claim["status"] == "supported"
    assert subject["metadata_owner"]["registration_ids"] == []
    assert subject["excluded_other_party_registration_ids"] == [issuer_id]


@pytest.mark.asyncio
async def test_company_numeric_claim_with_unknown_evidence_owner_needs_review() -> None:
    result = await _execute(
        _response(
            "我司合同金额为135万元。",
            evidence_used=["MAT-CONTRACT-UNKNOWN"],
            unknowns=[],
            risk_flags=[],
        ),
        sections=[{"section_id": "experience", "title": "项目经验"}],
        requirements=[],
        scoring_items=[],
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            _material(
                "MAT-CONTRACT-UNKNOWN",
                "合同台账",
                "合同金额为135万元。",
                material_type="contract",
            )
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "needs_review"
    assert claim["subject_check"]["status"] == "missing"


@pytest.mark.asyncio
async def test_confirmed_case_fact_with_different_owner_cannot_support_claim() -> None:
    result = await _execute(
        _response("我司累计承接三十项大型政务项目。", unknowns=[], risk_flags=[]),
        bidder_profile={"bidder_name": "甲公司"},
        confirmed_facts=[
            {
                "fact_id": "confirmed-beta-cases",
                "text": "累计承接三十项大型政务项目。",
                "confirmed": True,
                "row": {"owner_name": "乙公司"},
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert claim["subject_check"]["status"] == "conflict"
    assert claim["subject_check"]["metadata_owner"]["names"] == ["乙公司"]


@pytest.mark.asyncio
async def test_confirmed_case_fact_with_explicit_bidder_owner_supports_claim() -> None:
    result = await _execute(
        _response("我司累计承接三十项大型政务项目。", unknowns=[], risk_flags=[]),
        bidder_profile={"bidder_name": "甲公司"},
        confirmed_facts=[
            {
                "fact_id": "confirmed-alpha-cases",
                "text": "累计承接三十项大型政务项目。",
                "confirmed": True,
                "row": {"owner_name": "甲公司"},
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "success", result.data
    assert claim["status"] == "supported"
    assert claim["subject_check"]["status"] == "matched"


@pytest.mark.asyncio
async def test_confirmed_numeric_fact_without_owner_needs_review() -> None:
    result = await _execute(
        _response("我司累计承接三十项大型政务项目。", unknowns=[], risk_flags=[]),
        bidder_profile={"bidder_name": "甲公司"},
        confirmed_facts=[
            {
                "fact_id": "confirmed-unowned-cases",
                "text": "累计承接三十项大型政务项目。",
                "confirmed": True,
                "row": {},
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "needs_review"
    assert claim["subject_check"]["status"] == "missing"


@pytest.mark.asyncio
async def test_same_owner_contract_amount_material_supports_company_claim() -> None:
    result = await _execute(
        _response(
            "我司合同金额为135万元。",
            evidence_used=["MAT-CONTRACT-ALPHA"],
            unknowns=[],
            risk_flags=[],
        ),
        sections=[{"section_id": "experience", "title": "项目经验"}],
        requirements=[],
        scoring_items=[],
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            {
                **_material(
                    "MAT-CONTRACT-ALPHA",
                    "甲公司合同台账",
                    "主体：甲公司。合同金额为135万元。",
                    material_type="contract",
                ),
                "metadata": {"status": "valid", "owner_name": "甲公司"},
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "success", result.data
    assert claim["status"] == "supported"
    assert claim["subject_check"]["status"] == "matched"


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
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            {
                **_material(
                    "iso",
                    "ISO27001认证证书",
                    "ISO27001认证有效。",
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder": "甲公司",
                    "certificate_type": "ISO27001",
                    "certificate_no": "CN-27001-2026",
                },
            },
            {
                **_material(
                    "cases",
                    "企业案例清单",
                    "企业累计完成30个项目案例。",
                    material_type="project_cases",
                ),
                "metadata": {"status": "valid", "owner_name": "甲公司"},
            },
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
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            {
                **_material(
                    "iso",
                    "ISO27001认证证书",
                    "ISO27001认证有效。",
                    material_type="certification",
                    valid_until=valid_until,
                    status=status,
                    confidence=confidence,
                ),
                "metadata": {
                    "status": status,
                    "holder": "甲公司",
                    "certificate_type": "ISO27001",
                },
            }
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
        bidder_profile={"bidder_name": "甲公司"},
        tender_profile={"key_dates": {"bid_deadline": "2026-10-10 09:30"}},
        materials=[
            {
                **_material(
                    "iso",
                    "ISO27001认证证书",
                    "ISO27001认证有效。",
                    material_type="certification",
                    valid_until="2026-10-08",
                ),
                "metadata": {
                    "status": "valid",
                    "holder": "甲公司",
                    "certificate_type": "ISO27001",
                },
            }
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


@pytest.mark.asyncio
async def test_certificate_number_digits_do_not_match_another_iso_standard() -> None:
    result = await _execute(
        _response("我司已取得ISO27001认证。", evidence_used=["iso"]),
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            {
                **_material(
                    "iso",
                    "ISO9001认证证书",
                    "ISO9001认证有效。证书编号：CN27001-2026。",
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder": "甲公司",
                    "certificate_type": "ISO9001",
                    "certificate_no": "CN27001-2026",
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert claim["standard_check"]["status"] == "mismatch"
    assert claim["standard_check"]["observed"] == ["ISO 9001"]


@pytest.mark.asyncio
async def test_matching_certificate_standard_and_bidder_holder_is_supported() -> None:
    result = await _execute(
        _response("我司已取得ISO/IEC 27001认证。", evidence_used=["iso"]),
        bidder_profile={
            "bidder_name": "甲公司",
            "attributes": {"unified_social_credit_code": "91310000A"},
        },
        materials=[
            {
                **_material(
                    "iso",
                    "ISO27001认证证书",
                    "认证标准：ISO27001，状态：有效。",
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder": {
                        "name": "甲公司",
                        "unified_social_credit_code": "91310000A",
                    },
                    "certificate_type": "ISO/IEC 27001",
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "success", result.data
    assert claim["status"] == "supported"
    assert claim["asserted_standard"]["id"] == "ISO/IEC 27001"
    assert claim["standard_check"]["status"] == "matched"
    assert claim["subject_check"]["status"] == "matched"


@pytest.mark.asyncio
async def test_other_company_holder_does_not_support_bidder_claim() -> None:
    result = await _execute(
        _response("我司已取得ISO27001认证。", evidence_used=["iso"]),
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            {
                **_material(
                    "iso",
                    "ISO27001认证证书",
                    "认证标准：ISO27001，状态：有效。",
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder": "乙公司",
                    "certificate_type": "ISO27001",
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert claim["subject_check"]["status"] == "conflict"
    assert claim["evidence"] == []


@pytest.mark.asyncio
async def test_certificate_without_holder_or_bidder_identity_requires_review() -> None:
    result = await _execute(
        _response("我司已取得ISO27001认证。", evidence_used=["iso"]),
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            {
                **_material(
                    "iso",
                    "ISO27001认证证书",
                    "认证标准：ISO27001，状态：有效。",
                    material_type="certification",
                ),
                "metadata": {"status": "valid", "certificate_type": "ISO27001"},
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert claim["subject_check"]["status"] == "missing"


@pytest.mark.asyncio
async def test_holder_without_bidder_name_cannot_be_assumed_bidder() -> None:
    result = await _execute(
        _response("我司已取得ISO27001认证。", evidence_used=["iso"]),
        materials=[
            {
                **_material(
                    "iso",
                    "ISO27001认证证书",
                    "ISO27001认证有效。",
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder_name": "甲公司",
                    "certificate_type": "ISO27001",
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert claim["subject_check"]["status"] == "missing"


@pytest.mark.asyncio
async def test_personnel_certificate_holder_is_not_treated_as_bidder_identity() -> None:
    result = await _execute(
        _response("我司已取得ISO27001认证。", evidence_used=["iso"]),
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            {
                **_material(
                    "iso",
                    "ISO27001认证证书",
                    "ISO27001认证有效。",
                    material_type="personnel_certificate",
                ),
                "metadata": {
                    "status": "valid",
                    "holder": "张三",
                    "certificate_type": "ISO27001",
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert claim["subject_check"]["status"] == "conflict"


@pytest.mark.asyncio
async def test_structured_and_body_holder_conflict_requires_review() -> None:
    result = await _execute(
        _response("我司已取得ISO27001认证。", evidence_used=["iso"]),
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            {
                **_material(
                    "iso",
                    "ISO27001认证证书",
                    "ISO27001认证有效。持证主体：乙公司。",
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder": "甲公司",
                    "certificate_type": "ISO27001",
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert claim["subject_check"]["status"] == "conflict"
    assert claim["subject_check"]["metadata_holder"]["names"] == ["甲公司"]
    assert claim["subject_check"]["body_holders"][0]["names"] == ["乙公司"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("certificate_type", "content_standard"),
    [
        ("ISO27001", "ISO9001"),
        ("ISO9001", "ISO27001"),
    ],
)
async def test_structured_standard_conflicting_with_certificate_body_is_not_used(
    certificate_type: str,
    content_standard: str,
) -> None:
    result = await _execute(
        _response("我司已取得ISO27001认证。", evidence_used=["iso"]),
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            {
                **_material(
                    "iso",
                    "认证证书",
                    f"{content_standard}认证有效。",
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder": "甲公司",
                    "certificate_type": certificate_type,
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert claim["standard_check"]["status"] == "conflict"
    expected_structured = {
        "ISO27001": "ISO/IEC 27001",
        "ISO9001": "ISO 9001",
    }[certificate_type]
    expected_body = {
        "ISO27001": "ISO/IEC 27001",
        "ISO9001": "ISO 9001",
    }[content_standard]
    assert claim["standard_check"]["structured"] == [expected_structured]
    assert claim["standard_check"]["body"] == [expected_body]


@pytest.mark.asyncio
async def test_confirmed_fact_without_holder_cannot_bypass_subject_check() -> None:
    result = await _execute(
        _response("我司已取得ISO27001认证。"),
        bidder_profile={"bidder_name": "甲公司"},
        confirmed_facts=[
            {
                "fact_id": "confirmed-iso",
                "text": "认证标准：ISO27001，认证有效。",
                "confirmed": True,
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert claim["subject_check"]["status"] == "missing"


@pytest.mark.asyncio
async def test_tender_text_does_not_support_bidder_qualification_assertion() -> None:
    result = await _execute(
        _response("我司已取得ISO27001认证。"),
        tender_text="招标文件要求投标人提供ISO27001认证。",
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert claim["evidence"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claim_text", "material_text"),
    [
        ("我司通过CMMI 5级认证。", "认证标准：CMMI Level 5，状态：有效。"),
        ("我司取得ITSS 3级认证。", "认证标准：ITSS-3，状态：有效。"),
    ],
)
async def test_cmmi_and_itss_standards_require_exact_typed_identity(
    claim_text: str,
    material_text: str,
) -> None:
    result = await _execute(
        _response(claim_text, evidence_used=["cert"]),
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            {
                **_material(
                    "cert",
                    "认证证书",
                    material_text,
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder": "甲公司",
                    "certificate_type": material_text.split("：", 1)[1].split(
                        "，", 1
                    )[0],
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "success", result.data
    assert claim["standard_check"]["status"] == "matched"
    assert claim["subject_check"]["status"] == "matched"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "certificate_type"),
    [
        ("我司已取得CMMI3认证。", "CMMI 3"),
        ("我司已取得CMMI-3认证。", "CMMI-3"),
        ("我司已取得CMMI Level 3认证。", "CMMI Level 3"),
        ("我司已取得CMMI 3级认证。", "CMMI 3级"),
        ("我司已取得ITSS2认证。", "ITSS 2"),
        ("我司已取得ITSS-2级认证。", "ITSS-2"),
    ],
)
async def test_cmmi_itss_spelling_variants_still_require_subject_match(
    content: str,
    certificate_type: str,
) -> None:
    scanned = scan_high_risk_claims(content)
    assert [claim["category"] for claim in scanned] == ["certification"]

    result = await _execute(
        _response(content, evidence_used=["cert"]),
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            {
                **_material(
                    "cert",
                    "认证证书",
                    f"{certificate_type}认证有效。",
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "certificate_type": certificate_type,
                    "holder": "甲公司",
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert claim["category"] == "certification"
    assert claim["status"] == "supported"
    assert claim["subject_check"]["status"] == "matched"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "certificate_type"),
    [
        ("我司已取得CMMI3认证。", "CMMI 3"),
        ("我司已取得CMMI-3认证。", "CMMI-3"),
        ("我司已取得CMMI Level 3认证。", "CMMI Level 3"),
        ("我司已取得CMMI 3级认证。", "CMMI 3级"),
        ("我司已取得ITSS2认证。", "ITSS 2"),
    ],
)
async def test_cmmi_itss_spelling_variants_cannot_bypass_missing_subject(
    content: str,
    certificate_type: str,
) -> None:
    scanned = scan_high_risk_claims(content)
    assert [claim["category"] for claim in scanned] == ["certification"]

    result = await _execute(
        _response(content, evidence_used=["cert"]),
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            {
                **_material(
                    "cert",
                    "认证证书",
                    f"{certificate_type}认证有效。",
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "certificate_type": certificate_type,
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert claim["category"] == "certification"
    assert claim["status"] == "unsupported"
    assert claim["subject_check"]["status"] == "missing"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claim_text", "certificate_type", "certificate_no"),
    [
        ("我司通过CMMI 5级认证。", "CMMI 50", "CN-CMMI5-2026"),
        ("我司取得ITSS 3级认证。", "ITSS 30", "CN-ITSS3-2026"),
    ],
)
async def test_cmmi_and_itss_levels_do_not_match_numeric_substrings(
    claim_text: str,
    certificate_type: str,
    certificate_no: str,
) -> None:
    result = await _execute(
        _response(claim_text, evidence_used=["cert"]),
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            {
                **_material(
                    "cert",
                    "认证证书",
                    f"{certificate_type}认证有效。",
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder": "甲公司",
                    "certificate_type": certificate_type,
                    "certificate_no": certificate_no,
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert claim["standard_check"]["status"] in {"mismatch", "unknown"}


@pytest.mark.asyncio
async def test_certificate_number_cannot_supply_cmmi_level() -> None:
    result = await _execute(
        _response("我司通过CMMI 3级认证。", evidence_used=["cert"]),
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            {
                **_material(
                    "cert",
                    "CMMI认证证书",
                    "CMMI 5级认证有效。",
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder": "甲公司",
                    "certificate_type": "CMMI 5",
                    "certificate_no": "CN-CMMI-3-2026",
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert claim["standard_check"]["status"] in {"mismatch", "conflict"}
    assert claim["standard_check"]["structured"] == ["CMMI Level 5"]
    assert claim["standard_check"]["body"] == ["CMMI Level 5"]


@pytest.mark.asyncio
async def test_cmmi_number_collision_is_blocked_and_consistent_level_passes() -> None:
    negative = await _execute(
        _response("我司通过CMMI 3级认证。", evidence_used=["cmmi"]),
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            {
                **_material(
                    "cmmi",
                    "CMMI认证证书",
                    "认证标准：CMMI 5级。持证主体：甲公司。",
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder_name": "甲公司",
                    "certificate_type": "CMMI 5",
                    "certificate_no": "CN-CMMI-3-2026",
                },
            }
        ],
    )
    positive = await _execute(
        _response("我司通过CMMI 3级认证。", evidence_used=["cmmi"]),
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            {
                **_material(
                    "cmmi",
                    "CMMI认证证书",
                    "认证标准：CMMI 3级。持证主体：甲公司。",
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder_name": "甲公司",
                    "certificate_type": "CMMI 3",
                    "certificate_no": "CN-CMMI-3-2026",
                },
            }
        ],
    )

    rejected_claim = negative.data["claim_evidence_mapping"][0]
    supported_claim = positive.data["claim_evidence_mapping"][0]
    assert negative.status == "partial"
    assert rejected_claim["status"] == "unsupported"
    assert rejected_claim["standard_check"]["status"] == "mismatch"
    assert rejected_claim["standard_check"]["structured"] == ["CMMI Level 5"]
    assert rejected_claim["standard_check"]["body"] == ["CMMI Level 5"]
    assert positive.status == "success", positive.data
    assert supported_claim["status"] == "supported"
    assert supported_claim["standard_check"]["status"] == "matched"
    assert supported_claim["subject_check"]["status"] == "matched"


@pytest.mark.asyncio
async def test_same_bidder_name_with_different_registration_id_is_conflict() -> None:
    result = await _execute(
        _response("我司已取得ISO27001认证。", evidence_used=["iso"]),
        bidder_profile={
            "bidder_name": "甲公司",
            "attributes": {"unified_social_credit_code": "91310000AAAAAAAAAA"},
        },
        materials=[
            {
                **_material(
                    "iso",
                    "ISO27001认证证书",
                    "ISO27001认证有效。",
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder": {
                        "name": "甲公司",
                        "unified_social_credit_code": "91310000BBBBBBBBBB",
                    },
                    "certificate_type": "ISO27001",
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert claim["subject_check"]["status"] == "conflict"
    assert claim["subject_check"]["bidder"]["registration_ids"] == [
        "91310000AAAAAAAAAA"
    ]
    assert claim["subject_check"]["metadata_holder"]["registration_ids"] == [
        "91310000BBBBBBBBBB"
    ]


@pytest.mark.asyncio
async def test_flat_metadata_and_adjacent_body_ids_conflict() -> None:
    bidder_id = "91310000MA1A111111"
    holder_id = "91320000MA1A222222"
    result = await _execute(
        _response("我司已取得ISO/IEC27001认证。", evidence_used=["iso"]),
        bidder_profile={
            "bidder_name": "甲公司",
            "attributes": {"unified_social_credit_code": bidder_id},
        },
        materials=[
            {
                **_material(
                    "iso",
                    "ISO27001认证证书",
                    (
                        "持证主体：甲公司。"
                        f"统一社会信用代码：{holder_id}。"
                        "认证标准：ISO/IEC27001"
                    ),
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder_name": "甲公司",
                    "unified_social_credit_code": holder_id,
                    "certificate_type": "ISO/IEC27001",
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    subject = claim["subject_check"]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert subject["status"] == "conflict"
    assert subject["bidder"]["registration_ids"] == [bidder_id]
    assert subject["metadata_holder"]["registration_ids"] == [holder_id]
    assert subject["body_holders"][0]["registration_ids"] == [holder_id]


@pytest.mark.asyncio
async def test_flat_metadata_holder_registration_id_supports_same_bidder() -> None:
    registration_id = "91310000MA1A111111"
    result = await _execute(
        _response("我司已取得ISO/IEC27001认证。", evidence_used=["iso"]),
        bidder_profile={
            "bidder_name": "甲公司",
            "attributes": {"unified_social_credit_code": registration_id},
        },
        materials=[
            {
                **_material(
                    "iso",
                    "ISO27001认证证书",
                    "ISO/IEC27001认证有效。",
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder_name": "甲公司",
                    "unified_social_credit_code": registration_id,
                    "certificate_type": "ISO/IEC27001",
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "success", result.data
    assert claim["status"] == "supported"
    assert claim["subject_check"]["status"] == "matched"
    assert claim["subject_check"]["matching_basis"] == "registration_id"


@pytest.mark.asyncio
async def test_unattributed_flat_registration_id_prevents_name_only_match() -> None:
    result = await _execute(
        _response("我司已取得ISO27001认证。", evidence_used=["iso"]),
        bidder_profile={
            "bidder_name": "甲公司",
            "attributes": {"unified_social_credit_code": "91310000MA1A111111"},
        },
        materials=[
            {
                **_material(
                    "iso",
                    "ISO27001认证证书",
                    "ISO27001认证有效。",
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder_name": "甲公司",
                    "issuer_name": "认证机构",
                    "unified_social_credit_code": "91320000MA1A222222",
                    "certificate_type": "ISO27001",
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    subject = claim["subject_check"]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert subject["status"] == "unknown"
    assert subject["metadata_holder"]["names"] == ["甲公司"]
    assert subject["unassigned_registration_ids"]["metadata"] == [
        "91320000MA1A222222"
    ]


@pytest.mark.asyncio
async def test_body_issuer_id_is_not_borrowed_by_holder() -> None:
    issuer_id = "91320000MA1A222222"
    result = await _execute(
        _response("我司已取得ISO27001认证。", evidence_used=["iso"]),
        bidder_profile={
            "bidder_name": "甲公司",
            "attributes": {"unified_social_credit_code": "91310000MA1A111111"},
        },
        materials=[
            {
                **_material(
                    "iso",
                    "ISO27001认证证书",
                    (
                        "ISO27001认证有效。持证主体：甲公司。"
                        f"发证机构统一社会信用代码：{issuer_id}。"
                    ),
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder_name": "甲公司",
                    "certificate_type": "ISO27001",
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    subject = claim["subject_check"]
    assert result.status == "success", result.data
    assert claim["status"] == "supported"
    assert subject["status"] == "matched"
    assert issuer_id not in subject["holder"]["registration_ids"]
    assert issuer_id not in subject["body_holders"][0]["registration_ids"]
    assert subject["excluded_other_party_registration_ids"] == [issuer_id]


@pytest.mark.asyncio
async def test_unassociated_body_registration_id_prevents_name_only_match() -> None:
    result = await _execute(
        _response("我司已取得ISO27001认证。", evidence_used=["iso"]),
        bidder_profile={
            "bidder_name": "甲公司",
            "attributes": {"unified_social_credit_code": "91310000MA1A111111"},
        },
        materials=[
            {
                **_material(
                    "iso",
                    "ISO27001认证证书",
                    (
                        "ISO27001认证有效。持证主体：甲公司。"
                        "关联统一社会信用代码：91320000MA1A222222。"
                    ),
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder_name": "甲公司",
                    "certificate_type": "ISO27001",
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert claim["subject_check"]["status"] == "unknown"
    assert claim["subject_check"]["unassigned_registration_ids"]["body"] == [
        "91320000MA1A222222"
    ]


@pytest.mark.asyncio
async def test_explicit_registration_id_can_match_without_holder_name() -> None:
    result = await _execute(
        _response("我司已取得ISO27001认证。", evidence_used=["iso"]),
        bidder_profile={
            "bidder_name": "甲公司",
            "attributes": {"unified_social_credit_code": "91310000AAAAAAAAAA"},
        },
        materials=[
            {
                **_material(
                    "iso",
                    "ISO27001认证证书",
                    "ISO27001认证有效。",
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder_registration_id": "91310000AAAAAAAAAA",
                    "certificate_type": "ISO27001",
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "success", result.data
    assert claim["status"] == "supported"
    assert claim["subject_check"]["status"] == "matched"
    assert claim["subject_check"]["matching_basis"] == "registration_id"


@pytest.mark.asyncio
async def test_company_name_punctuation_difference_is_not_an_alias_match() -> None:
    result = await _execute(
        _response("我司已取得ISO27001认证。", evidence_used=["iso"]),
        bidder_profile={"bidder_name": "甲（集团）有限公司"},
        materials=[
            {
                **_material(
                    "iso",
                    "ISO27001认证证书",
                    "ISO27001认证有效。",
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder": "甲集团有限公司",
                    "certificate_type": "ISO27001",
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert claim["subject_check"]["status"] == "conflict"


@pytest.mark.asyncio
async def test_explicit_standard_edition_requires_matching_evidence_edition() -> None:
    result = await _execute(
        _response("我司已取得ISO/IEC 27001:2022认证。", evidence_used=["iso"]),
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            {
                **_material(
                    "iso",
                    "ISO27001认证证书",
                    "ISO/IEC 27001认证有效。",
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder": "甲公司",
                    "certificate_type": "ISO27001",
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "partial"
    assert claim["status"] == "unsupported"
    assert claim["standard_check"]["status"] == "mismatch"


@pytest.mark.asyncio
async def test_iso_editionless_title_does_not_conflict_with_2022_evidence() -> None:
    result = await _execute(
        _response("我司已取得ISO/IEC 27001:2022认证。", evidence_used=["iso"]),
        bidder_profile={"bidder_name": "甲公司"},
        materials=[
            {
                **_material(
                    "iso",
                    "ISO/IEC 27001",
                    "认证标准：ISO/IEC 27001:2022。认证有效。",
                    material_type="certification",
                ),
                "metadata": {
                    "status": "valid",
                    "holder_name": "甲公司",
                    "certificate_type": "ISO/IEC 27001:2022",
                },
            }
        ],
    )

    claim = result.data["claim_evidence_mapping"][0]
    assert result.status == "success", result.data
    assert claim["status"] == "supported"
    assert claim["standard_check"]["status"] == "matched"
    assert claim["standard_check"]["structured"] == ["ISO/IEC 27001:2022"]
    assert claim["standard_check"]["body"] == ["ISO/IEC 27001:2022"]


@pytest.mark.asyncio
async def test_chinese_project_quantity_with_descriptors_is_reviewed() -> None:
    content = "我司累计承接三十项大型政务项目。"
    scanned = scan_high_risk_claims(content)
    assert [claim["category"] for claim in scanned] == ["case_quantity"]
    assert scanned[0]["markers"]["count"] == "30"

    result = await _execute(_response(content, unknowns=[]))
    assert result.status == "partial"
    claim = result.data["claim_evidence_mapping"][0]
    assert result.data["business_status"] == "needs_review"
    assert claim["status"] == "unsupported"
    assert claim["supports_enterprise_fact"] is False
    assert "subject_check" not in claim
    assert result.data["claim_verification"]["coverage"]["status"] == "complete"
    assert result.data["claim_verification"]["coverage"][
        "unclassified_high_risk_claim_count"
    ] == 0


@pytest.mark.asyncio
async def test_unclassified_company_claim_makes_scan_coverage_partial() -> None:
    result = await _execute(
        _response("我司持续服务多个大型政务客户，行业领先。", unknowns=[])
    )

    assert result.status == "partial"
    assert result.data["business_status"] == "needs_review"
    assert result.data["claim_verification"]["coverage"]["status"] == "partial"
    assert result.data["claim_verification"]["coverage"][
        "unclassified_high_risk_claim_count"
    ] == 1
    assert "我司持续服务多个大型政务客户，行业领先。" in result.data[
        "claim_verification"
    ]["coverage"]["unclassified_high_risk_snippets"]
    assert "unclassified_high_risk_assertion" in result.data[
        "claim_verification"
    ]["coverage"]["recognized_patterns"]
    assert any(
        claim["category"] == "unclassified_high_risk_assertion"
        and claim["status"] == "needs_review"
        for claim in result.data["claim_evidence_mapping"]
    )


@pytest.mark.asyncio
async def test_benign_chapter_reports_no_claims_not_a_fact_verification_pass() -> None:
    result = await _execute(_response("本章按项目阶段说明实施安排与质量控制。"))

    assert result.status == "success", result.data
    assert result.data["claim_verification"]["status"] == "no_claims_detected"
    assert result.data["claim_verification"]["coverage"]["status"] == "complete"
    assert result.data["submission_allowed"] is False
    assert "submission_allowed=false" in result.data["notices"][0]
    assert all("本输出仅为草案" not in warning for warning in result.warnings)


def test_empty_content_reports_claim_scan_not_checked() -> None:
    from qiaowenshu_agent.skills.document_writing.verification import verify_chapter

    result = verify_chapter(
        {},
        content="",
        payload={"bidder_profile": {}},
        section={"section_id": "experience"},
        section_context={"requirements": [], "scoring_items": [], "materials": []},
        as_of="2026-10-05",
    )

    assert result["claim_verification"]["status"] == "not_checked"
    assert result["claim_verification"]["coverage"]["status"] == "not_scanned"
