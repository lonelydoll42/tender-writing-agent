from __future__ import annotations

from typing import Any, Mapping

import pytest

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.core.runtime import AgentRuntime
from qiaowenshu_agent.core.registry import SkillRegistry
from qiaowenshu_agent.skills.scoring_strategy import ScoringStrategySkill


@pytest.mark.asyncio
async def test_scoring_strategy_calculates_score_and_evidence_coverage() -> None:
    registry = SkillRegistry()
    registry.register(ScoringStrategySkill())
    runtime = AgentRuntime(registry)

    result = await runtime.run(
        SkillRequest.create(
            {
                "project_id": "project-1",
                "scoring_items": [
                    {
                        "item_id": "technical",
                        "title": "技术方案",
                        "max_score": 30,
                        "criteria": "方案完整、合理、可行，提供项目实施方案。",
                        "score_type": "subjective",
                        "source_references": [
                            {
                                "document_id": "tender.pdf",
                                "page": 12,
                                "section": "评分办法",
                            }
                        ],
                        "evidence_required": ["项目实施方案"],
                    },
                    {
                        "item_id": "qualification",
                        "title": "企业资质",
                        "max_score": 10,
                        "criteria": "具备相关资质证书，提供资质证书。",
                        "score_type": "objective",
                        "evidence_required": ["资质证书"],
                    },
                    {
                        "item_id": "service",
                        "title": "售后服务",
                        "max_score": 5,
                        "criteria": "服务承诺和响应机制。",
                        "score_type": "subjective",
                    },
                ],
                "evidence_materials": [
                    {
                        "material_id": "material-1",
                        "material_type": "方案文件",
                        "title": "项目实施方案",
                        "content": "项目实施方案和进度计划",
                        "source_references": [
                            {"document_id": "bid-materials.docx", "page": 3}
                        ],
                    }
                ],
            },
            skill_name="scoring-strategy",
        )
    )

    assert result.status == "success"
    output = result.output
    assert output["summary"]["total_score"] == 45.0
    assert output["summary"]["covered_score"] == 0.0
    assert output["summary"]["objective_proven_score"] == 0.0
    assert output["summary"]["objective_unproven_score"] == 10.0
    assert output["summary"]["price_available"] is False
    assert output["summary"]["subjective_available"] is False
    assert output["summary"]["score_coverage_rate"] == pytest.approx(0 / 45)
    assert output["summary"]["evidence_coverage_rate"] == pytest.approx(0.5)
    assert output["summary"]["evidence_gap_count"] == 1
    assert output["evidence_gaps"][0]["item_id"] == "qualification"

    technical = output["scoring_items"][0]
    assert technical["source_references"][0]["page"] == 12
    assert technical["evidence_status"] == "complete"
    assert technical["priority"] == "P1"
    assert output["priorities"][0]["item_id"] == "technical"


@pytest.mark.asyncio
async def test_scoring_strategy_parses_pipe_table_and_criteria_evidence() -> None:
    registry = SkillRegistry()
    registry.register(ScoringStrategySkill())
    runtime = AgentRuntime(registry)

    result = await runtime.run(
        SkillRequest.create(
            {
                "project_id": "project-2",
                "scoring_table": {
                    "columns": ["评分项", "分值", "评分标准"],
                    "values": [
                        [
                            "项目案例",
                            "20",
                            "每提供一个类似项目合同得5分，提供合同和验收报告。",
                        ],
                        ["报价", "30分", "按价格计算"],
                    ],
                },
                "evidence_materials": [
                    {
                        "id": "contract-1",
                        "type": "合同",
                        "name": "类似项目合同",
                    },
                    {
                        "id": "acceptance-1",
                        "type": "验收报告",
                        "name": "项目验收报告",
                    },
                ],
            },
            skill_name="scoring-strategy",
        )
    )

    assert result.status == "success"
    output = result.output
    assert output["summary"]["total_score"] == 50.0
    cases = output["scoring_items"][0]
    assert cases["title"] == "项目案例"
    assert cases["evidence_required"] == ["合同", "验收报告"]
    assert cases["evidence_status"] == "complete"
    assert output["scoring_items"][1]["score_type"] == "price"
    assert output["scoring_items"][1]["subjective_space"] == "low"


class Backend:
    async def run(
        self,
        payload: Mapping[str, Any],
        _context: SkillContext,
    ) -> dict[str, Any]:
        assert payload["project_id"] == "project-3"
        return {
            "scoring_items": [
                {
                    "id": "quality",
                    "name": "服务质量",
                    "points": 25,
                    "得分条件": "方案合理性由评委综合评价。",
                    "主观评分空间": "高",
                    "source": {"document_id": "tender.docx", "page": 8},
                }
            ],
            # This is intentionally ignored as an awarded/final score.
            "awarded_score": 99,
        }


@pytest.mark.asyncio
async def test_scoring_strategy_backend_is_extractor_and_ignores_awarded_score(
) -> None:
    registry = SkillRegistry()
    registry.register(ScoringStrategySkill(backend=Backend()))
    runtime = AgentRuntime(registry)

    result = await runtime.run(
        SkillRequest.create(
            {"project_id": "project-3"},
            skill_name="scoring-strategy",
        )
    )

    assert result.status == "success"
    output = result.output
    assert output["summary"]["total_score"] == 25.0
    assert "awarded_score" not in output
    assert "actual_score" not in output
    item = output["scoring_items"][0]
    assert item["max_score"] == 25.0
    assert item["subjective_space"] == "high"
    assert item["source_references"][0]["page"] == 8


@pytest.mark.asyncio
async def test_scoring_strategy_blocks_without_criteria() -> None:
    registry = SkillRegistry()
    registry.register(ScoringStrategySkill())
    result = await AgentRuntime(registry).run(
        SkillRequest.create(
            {"project_id": "project-4"},
            skill_name="scoring-strategy",
        )
    )

    assert result.status == "blocked"
    assert (
        result.steps[0].result.error_code
        == "SCORING_STRATEGY_INPUT_NOT_CONFIGURED"
    )
