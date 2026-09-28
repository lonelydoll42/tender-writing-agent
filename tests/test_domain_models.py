from __future__ import annotations

import pytest

from qiaowenshu_agent.domain.models import (
    BidderProfile,
    EvidenceMaterial,
    ScoringItem,
    TenderRequirement,
)


def test_tender_requirement_normalizes_aliases_and_source_reference() -> None:
    requirement = TenderRequirement.from_mapping(
        {
            "id": "req-1",
            "category": "一票否决",
            "name": "营业执照",
            "requirement": "提供有效营业执照",
            "required": True,
            "required_materials": "营业执照, 统一社会信用代码证",
            "source_references": {
                "document_id": "tender.pdf",
                "page_number": "4",
                "section_path": "资格审查",
                "content": "投标人须提供营业执照。",
            },
        }
    )

    assert requirement.category == "disqualification"
    assert requirement.mandatory is True
    assert requirement.evidence_required == [
        "营业执照",
        "统一社会信用代码证",
    ]
    assert requirement.source_references[0].page == 4
    assert requirement.source_references[0].section == "资格审查"


def test_scoring_item_rejects_missing_or_negative_score() -> None:
    with pytest.raises(ValueError, match="non-negative max_score"):
        ScoringItem.from_mapping(
            {"id": "score-1", "title": "技术方案", "score": -1}
        )

    with pytest.raises(ValueError, match="needs a non-negative max_score"):
        ScoringItem.from_mapping({"id": "score-2", "title": "服务"})


def test_bidder_profile_promotes_extra_fields_and_materials() -> None:
    bidder = BidderProfile.from_mapping(
        {
            "id": "bidder-1",
            "name": "示例公司",
            "registered_capital": 1000,
            "materials": [
                {
                    "id": "mat-1",
                    "type": "营业执照",
                    "name": "营业执照扫描件",
                    "text": "统一社会信用代码 911...",
                    "valid_until": "2030-01-01",
                }
            ],
        }
    )

    assert bidder.bidder_name == "示例公司"
    assert bidder.attributes["registered_capital"] == 1000
    assert isinstance(bidder.materials[0], EvidenceMaterial)
    assert bidder.materials[0].material_type == "营业执照"
