from __future__ import annotations

from datetime import date

import pytest

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.domain.models import (
    EvidenceMaterial,
    SourceReference,
    TenderRequirement,
)
from qiaowenshu_agent.skills.evidence_matching import EvidenceMatchingSkill


def make_context(request: SkillRequest) -> SkillContext:
    return SkillContext(run_id="run_evidence_test", request=request)


@pytest.mark.asyncio
async def test_matching_accepts_domain_objects_and_preserves_references() -> None:
    requirement = TenderRequirement(
        requirement_id="req-license",
        category="qualification",
        title="营业执照",
        description="提供有效营业执照。",
        mandatory=True,
        evidence_required=["营业执照"],
        source_references=[
            SourceReference(document_id="tender.pdf", page=3, section="资格条件")
        ],
    )
    material = EvidenceMaterial(
        material_id="mat-license",
        material_type="营业执照",
        title="企业营业执照",
        valid_until="2030-12-31",
        source_references=[
            SourceReference(document_id="license.pdf", page=1, section="证照")
        ],
    )
    request = SkillRequest.create(
        {
            "requirements": [requirement],
            "materials": [material],
            "as_of": "2026-01-01",
        },
        skill_name="evidence-matching",
    )

    result = await EvidenceMatchingSkill().execute(request, make_context(request))

    assert result.status == "success"
    match = result.data["matches"][0]
    assert match["requirement_id"] == "req-license"
    assert match["material_id"] == "mat-license"
    assert match["status"] == "matched"
    assert match["confidence"] >= 0.8
    assert [item["document_id"] for item in match["source_references"]] == [
        "tender.pdf",
        "license.pdf",
    ]


@pytest.mark.asyncio
async def test_dictionary_input_matches_scoring_item_by_type_and_tags() -> None:
    request = SkillRequest.create(
        {
            "scoring_items": [
                {
                    "id": "score-case",
                    "name": "类似项目案例",
                    "score": 10,
                    "required_evidence": ["类似项目案例"],
                }
            ],
            "evidence_materials": [
                {
                    "id": "mat-case",
                    "type": "项目业绩",
                    "title": "智慧交通项目验收材料",
                    "text": "包含近三年类似项目合同及验收情况",
                    "metadata": {"semantic_tags": ["智慧交通", "类似业绩"]},
                }
            ],
            "as_of": "2026-01-01",
        },
        skill_name="evidence-matching",
    )

    result = await EvidenceMatchingSkill().execute(request, make_context(request))

    assert result.status == "success"
    assert result.data["matches"][0]["status"] == "matched"
    assert result.data["summary"]["scored_coverage"] == 1.0


@pytest.mark.asyncio
async def test_multiple_evidence_units_are_partial_until_all_are_present() -> None:
    request = SkillRequest.create(
        {
            "requirements": [
                {
                    "id": "req-company",
                    "category": "qualification",
                    "title": "企业证照与认证",
                    "required": True,
                    "required_evidence": ["营业执照", "ISO认证"],
                }
            ],
            "materials": [{"id": "mat-license", "type": "营业执照"}],
        },
        skill_name="evidence-matching",
    )

    result = await EvidenceMatchingSkill().execute(request, make_context(request))

    match = result.data["matches"][0]
    assert match["status"] == "partial"
    assert match["material_id"] == "mat-license"


@pytest.mark.asyncio
async def test_missing_material_is_not_reported_as_a_match() -> None:
    request = SkillRequest.create(
        {
            "requirements": [
                {
                    "id": "req-contract",
                    "category": "qualification",
                    "title": "类似项目合同",
                    "required": True,
                    "required_evidence": ["项目合同"],
                    "source_references": [{"document_id": "tender.pdf", "page": 20}],
                }
            ],
            "materials": [],
        },
        skill_name="evidence-matching",
    )

    result = await EvidenceMatchingSkill().execute(request, make_context(request))

    match = result.data["matches"][0]
    assert match["status"] == "missing"
    assert match["material_id"] is None
    assert match["source_references"][0]["document_id"] == "tender.pdf"


@pytest.mark.asyncio
async def test_expired_material_is_invalid_even_when_type_matches() -> None:
    request = SkillRequest.create(
        {
            "requirements": [
                {
                    "id": "req-cert",
                    "category": "qualification",
                    "title": "资质证书",
                    "required": True,
                    "required_evidence": ["资质证书"],
                }
            ],
            "materials": [
                {
                    "id": "mat-expired",
                    "type": "资质证书",
                    "valid_until": "2025年12月31日",
                }
            ],
            "as_of": date(2026, 1, 1),
        },
        skill_name="evidence-matching",
    )

    result = await EvidenceMatchingSkill().execute(request, make_context(request))

    match = result.data["matches"][0]
    assert match["status"] == "invalid"
    assert match["material_id"] == "mat-expired"
    assert "过期" in match["reason"]
