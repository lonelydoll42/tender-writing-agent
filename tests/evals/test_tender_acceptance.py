from __future__ import annotations

import pytest

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.core.registry import SkillRegistry
from qiaowenshu_agent.core.runtime import AgentRuntime, DeterministicPlanner
from qiaowenshu_agent.skills import build_default_registry
from qiaowenshu_agent.skills.bid_feasibility.skill import BidFeasibilitySkill
from qiaowenshu_agent.skills.evidence_matching import EvidenceMatchingSkill
from qiaowenshu_agent.skills.scoring_strategy import ScoringStrategySkill
from qiaowenshu_agent.skills.tender_decomposition.skill import (
    TenderDecompositionSkill,
)

from tests.evals.cases import (
    COMPLETE_BIDDER,
    REQUIREMENTS,
    SCORING_TABLE,
)


def _context() -> SkillContext:
    return SkillContext(
        run_id="run-eval",
        request=SkillRequest.create(),
    )


@pytest.mark.parametrize(
    ("prompt", "expected_skill"),
    [
        ("帮我分析这份招标文件", "tender-intake"),
        ("帮我拆一下这个项目的评分标准", "scoring-strategy"),
        ("根据这份招标文件生成投标方案", "tender-intake"),
        ("检查一下这份标书有没有废标风险", "bid-feasibility"),
        ("只拆解招标文件的资格条件", "tender-decomposition"),
    ],
)
def test_trigger_prompts_route_to_the_smallest_workflow_skill(
    prompt: str,
    expected_skill: str,
) -> None:
    planner = DeterministicPlanner(default_skill=None)

    plan = planner.plan(SkillRequest.create({"task": prompt}), SkillRegistry())

    assert [step.skill_name for step in plan] == [expected_skill]


@pytest.mark.parametrize(
    "prompt",
    [
        "什么叫投标保证金？",
        "给我解释一下政府采购是什么意思。",
        "一般标书多少页？",
    ],
)
def test_general_questions_do_not_trigger_tender_workflow(
    prompt: str,
) -> None:
    planner = DeterministicPlanner(default_skill=None)

    plan = planner.plan(SkillRequest.create({"task": prompt}), SkillRegistry())

    assert plan == []


@pytest.mark.asyncio
async def test_requirement_and_disqualification_recall_is_complete() -> None:
    runtime = AgentRuntime(SkillRegistry())
    skill = TenderDecompositionSkill()
    request = SkillRequest.create(
        {
            "project_id": "benchmark-project",
            "requirements": REQUIREMENTS,
        },
        skill_name="tender-decomposition",
    )

    result = await skill.execute(request, _context())

    assert result.status == "success"
    actual = {item["requirement_id"] for item in result.data["requirements"]}
    expected = {item["requirement_id"] for item in REQUIREMENTS}
    assert actual == expected
    assert result.data["summary"]["categories"]["disqualification"] == 1
    assert result.data["summary"]["categories"]["qualification"] == 4
    assert runtime.registry.names() == []


@pytest.mark.asyncio
async def test_feasibility_passes_complete_bidder_without_free_text_claims() -> None:
    skill = BidFeasibilitySkill()
    result = await skill.execute(
        SkillRequest.create(
            {
                "project_id": "benchmark-project",
                "requirements": REQUIREMENTS,
                "bidder_profile": COMPLETE_BIDDER,
            },
            skill_name="bid-feasibility",
        ),
        _context(),
    )

    assert result.status == "success"
    assert result.data["decision"] == "bid"
    assert result.data["summary"]["mandatory_unknown_count"] == 0
    assert all(check["status"] == "pass" for check in result.data["checks"])


@pytest.mark.asyncio
async def test_missing_required_certificate_requires_review_and_never_passes() -> None:
    bidder = dict(COMPLETE_BIDDER)
    bidder["materials"] = [
        material
        for material in COMPLETE_BIDDER["materials"]
        if material["material_id"] != "mat-iso"
    ]
    result = await BidFeasibilitySkill().execute(
        SkillRequest.create(
            {
                "project_id": "benchmark-project",
                "requirements": REQUIREMENTS,
                "bidder_profile": bidder,
            }
        ),
        _context(),
    )

    assert result.status == "success"
    assert result.data["decision"] == "human_review"
    iso_check = next(
        check
        for check in result.data["checks"]
        if check["requirement_id"] == "qual-iso"
    )
    assert iso_check["status"] == "unknown"
    assert "ISO27001" in result.data["warnings"][0]


@pytest.mark.asyncio
async def test_scoring_item_decomposition_covers_writeable_evidence_units() -> None:
    result = await ScoringStrategySkill().execute(
        SkillRequest.create(
            {
                "project_id": "benchmark-project",
                "scoring_table": SCORING_TABLE,
            },
            skill_name="scoring-strategy",
        ),
        _context(),
    )

    assert result.status == "success"
    implementation = result.data["scoring_items"][0]
    assert implementation["max_score"] == 10.0
    assert all(
        term in implementation["criteria"]
        for term in ("项目组织", "进度计划", "风险管理", "质量管理")
    )
    assert implementation["evidence_required"] == [
        "项目团队",
        "甘特图",
        "风险表",
        "质量方案",
    ]
    assert result.data["summary"]["total_score"] == 50.0


@pytest.mark.asyncio
async def test_evidence_matching_reports_missing_materials_explicitly() -> None:
    result = await EvidenceMatchingSkill().execute(
        SkillRequest.create(
            {
                "requirements": [REQUIREMENTS[2]],
                "materials": COMPLETE_BIDDER["materials"][:1],
            },
            skill_name="evidence-matching",
        ),
        _context(),
    )

    assert result.status == "success"
    match = result.data["matches"][0]
    assert match["status"] == "missing"
    assert match["material_id"] is None
    assert match["confidence"] == 0.0


@pytest.mark.asyncio
async def test_partial_e2e_workflow_has_no_unsupported_writing_steps() -> None:
    result = await AgentRuntime(build_default_registry()).run(
        SkillRequest.create(
            {
                "project_id": "benchmark-project",
                "requirements": REQUIREMENTS[:2],
                "bidder_profile": COMPLETE_BIDDER,
                "plan": [
                    {
                        "skill_name": "tender-decomposition",
                        "input": {
                            "project_id": "benchmark-project",
                            "requirements": REQUIREMENTS[:2],
                        },
                    },
                    {
                        "skill_name": "bid-feasibility",
                        "input": {
                            "project_id": "benchmark-project",
                            "requirements": {
                                "$ref": "$state/tender-decomposition/requirements"
                            },
                            "bidder_profile": {"$ref": "$request/bidder_profile"},
                        },
                    },
                ],
            }
        )
    )

    assert result.status == "success"
    assert [step.skill_name for step in result.steps] == [
        "tender-decomposition",
        "bid-feasibility",
    ]
    assert all(
        step.skill_name
        not in {
            "document-writing",
            "technical-response",
            "commercial-response",
            "quotation-check",
            "compliance-review",
            "submission-package",
        }
        for step in result.steps
    )
