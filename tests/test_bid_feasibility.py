from __future__ import annotations

import json
from pathlib import Path

import pytest

from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.registry import SkillRegistry
from qiaowenshu_agent.core.runtime import AgentRuntime
from qiaowenshu_agent.domain.models import SourceReference
from qiaowenshu_agent.skills.bid_feasibility.skill import (
    BidFeasibilitySkill,
    evaluate_feasibility,
)


def _reference(document_id: str, page: int, quote: str) -> dict[str, object]:
    return {
        "document_id": document_id,
        "page": page,
        "section": "资格审查",
        "quote": quote,
    }


def _requirements() -> list[dict[str, object]]:
    return [
        {
            "requirement_id": "qual-1",
            "category": "qualification",
            "title": "营业执照有效",
            "description": "投标人应具有有效营业执照",
            "mandatory": True,
            "evidence_required": ["business_license"],
            "source_references": [_reference("tender.pdf", 8, "应具有有效营业执照")],
        },
        {
            "requirement_id": "case-1",
            "category": "qualification",
            "title": "类似项目案例不少于2个",
            "description": "提供类似项目业绩",
            "mandatory": True,
            "check_rule": {
                "type": "similar_case",
                "attribute": "similar_case_count",
                "minimum": 2,
            },
            "source_references": [_reference("tender.pdf", 10, "类似业绩不少于2个")],
        },
        {
            "requirement_id": "staff-1",
            "category": "qualification",
            "title": "项目经理证书",
            "description": "项目经理应具备项目管理证书",
            "mandatory": True,
            "evidence_required": ["personnel_certificate"],
            "source_references": [_reference("tender.pdf", 11, "项目经理证书")],
        },
        {
            "requirement_id": "tech-1",
            "category": "technical",
            "title": "数据备份技术参数",
            "description": "系统应支持数据备份",
            "mandatory": True,
            "check_rule": {
                "type": "technical_parameter",
                "attribute": "technical_parameters.data_backup",
                "expected": True,
            },
            "source_references": [_reference("tender.pdf", 18, "支持数据备份")],
        },
        {
            "requirement_id": "bond-1",
            "category": "commercial",
            "title": "投标保证金",
            "description": "应提交投标保证金100000元",
            "mandatory": True,
            "check_rule": {
                "type": "bid_bond",
                "attribute": "bid_bond_amount",
                "minimum": 100000,
            },
            "source_references": [_reference("tender.pdf", 22, "投标保证金100000元")],
        },
    ]


def _bidder() -> dict[str, object]:
    return {
        "bidder_id": "bidder-1",
        "bidder_name": "示例公司",
        "attributes": {
            "similar_case_count": 2,
            "technical_parameters": {"data_backup": True},
            "bid_bond_amount": 100000,
        },
        "materials": [
            {
                "material_id": "license-1",
                "material_type": "business_license",
                "title": "营业执照",
                "source_references": [_reference("bidder.pdf", 3, "营业执照")],
            },
            {
                "material_id": "staff-1",
                "material_type": "personnel_certificate",
                "title": "项目经理证书",
                "source_references": [_reference("bidder.pdf", 12, "项目经理证书")],
            },
        ],
    }


@pytest.mark.asyncio
async def test_feasibility_returns_typed_auditable_bid_decision() -> None:
    registry = SkillRegistry()
    registry.register(BidFeasibilitySkill())
    result = await AgentRuntime(registry).run(
        SkillRequest.create(
            {
                "project_id": "project-1",
                "requirements": _requirements(),
                "bidder_profile": _bidder(),
            },
            skill_name="bid-feasibility",
        )
    )

    assert result.status == "success"
    assert result.output["decision"] == "bid"
    assert all("requirement_id" in check for check in result.output["checks"])
    license_check = next(
        check
        for check in result.output["checks"]
        if check["requirement_id"] == "qual-1"
    )
    assert license_check["status"] == "pass"
    assert license_check["source_references"][0]["page"] == 8
    assert result.output["summary"]["status_counts"]["pass"] == 5


@pytest.mark.asyncio
async def test_missing_hard_evidence_requires_human_review() -> None:
    skill = BidFeasibilitySkill()
    context = SkillContext(
        run_id="run-test",
        request=SkillRequest.create(),
    )
    result = await skill.execute(
        SkillRequest.create(
            {
                "project_id": "project-1",
                "requirements": [
                    {
                        "requirement_id": "staff-1",
                        "category": "qualification",
                        "title": "项目经理证书",
                        "mandatory": True,
                        "evidence_required": ["personnel_certificate"],
                        "source_references": [
                            _reference("tender.pdf", 11, "项目经理证书")
                        ],
                    }
                ],
                "bidder_profile": {"bidder_id": "bidder-1", "materials": []},
            }
        ),
        context,
    )

    assert result.status == "success"
    assert result.data["decision"] == "human_review"
    check = result.data["checks"][0]
    assert check["status"] == "unknown"
    assert "source_references" in check
    assert result.data["warnings"]


def test_explicit_failed_hard_rule_produces_no_bid() -> None:
    decision = evaluate_feasibility(
        "project-1",
        [
            {
                "requirement_id": "capital-1",
                "category": "qualification",
                "title": "注册资本",
                "mandatory": True,
                "check_rule": {
                    "attribute": "registered_capital",
                    "minimum": 1000,
                },
                "source_references": [
                    _reference("tender.pdf", 9, "注册资本不低于1000万元")
                ],
            }
        ],
        {
            "bidder_id": "bidder-1",
            "attributes": {"registered_capital": 500},
        },
    )

    assert decision.decision == "no_bid"
    assert decision.checks[0].status == "fail"
    assert decision.blockers


@pytest.mark.asyncio
async def test_project_id_can_be_read_from_tender_profile() -> None:
    result = await BidFeasibilitySkill().execute(
        SkillRequest.create(
            {
                "tender_profile": {"project_id": "project-from-profile"},
                "requirements": [
                    {
                        "requirement_id": "req-1",
                        "category": "technical",
                        "title": "技术响应",
                        "mandatory": False,
                    }
                ],
                "bidder_profile": {"bidder_id": "bidder-1"},
            }
        ),
        SkillContext(
            run_id="run-profile-project",
            request=SkillRequest.create(),
        ),
    )

    assert result.status == "success"
    assert result.data["project_id"] == "project-from-profile"


def test_invalid_or_expired_material_does_not_pass() -> None:
    decision = evaluate_feasibility(
        "project-1",
        [
            {
                "requirement_id": "bond-1",
                "category": "commercial",
                "title": "投标保证金",
                "mandatory": True,
                "evidence_required": ["bid_bond"],
                "source_references": [_reference("tender.pdf", 22, "提交投标保证金")],
            }
        ],
        {
            "bidder_id": "bidder-1",
            "materials": [
                {
                    "material_id": "bond-1",
                    "material_type": "bid_bond",
                    "valid_until": "2025-01-01",
                    "source_references": [_reference("bidder.pdf", 30, "投标保函")],
                }
            ],
        },
        options={"as_of": "2026-01-01"},
    )

    assert decision.decision == "no_bid"
    assert decision.checks[0].status == "fail"
    assert decision.checks[0].source_references[-1].page == 30


@pytest.mark.asyncio
async def test_requirements_and_bidder_can_be_read_from_runtime_state() -> None:
    context = SkillContext(
        run_id="run-state",
        request=SkillRequest.create(),
        state={
            "tender-decomposition": {
                "requirements": [
                    {
                        "requirement_id": "license-1",
                        "category": "qualification",
                        "title": "营业执照",
                        "mandatory": True,
                        "evidence_required": ["business_license"],
                    }
                ]
            },
            "bidder-profile": {
                "bidder_id": "bidder-1",
                "materials": [
                    {
                        "material_id": "license-1",
                        "material_type": "business_license",
                    }
                ],
            },
        },
    )
    result = await BidFeasibilitySkill().execute(
        SkillRequest.create({"project_id": "project-1"}),
        context,
    )

    assert result.status == "success"
    assert result.data["decision"] == "bid"


def test_manifest_is_machine_readable_and_domain_reference_imports_are_stable() -> None:
    manifest_path = (
        Path(__file__).parents[1]
        / "src"
        / "qiaowenshu_agent"
        / "skills"
        / "bid_feasibility"
        / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["name"] == "bid-feasibility"
    assert manifest["entrypoint"].endswith(":BidFeasibilitySkill")
    assert SourceReference.from_mapping(_reference("tender.pdf", 1, "要求")).page == 1
