from __future__ import annotations

import pytest

from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.core.runtime import AgentRuntime
from qiaowenshu_agent.skills import build_default_registry


@pytest.mark.asyncio
async def test_tender_workflow_passes_structured_state_between_skills() -> None:
    runtime = AgentRuntime(build_default_registry())
    result = await runtime.run(
        SkillRequest.create(
            {
                "project_id": "project-1",
                "requirements": [
                    {
                        "requirement_id": "license-1",
                        "category": "qualification",
                        "title": "营业执照",
                        "description": "提供有效营业执照",
                        "mandatory": True,
                        "evidence_required": ["business_license"],
                    }
                ],
                "scoring_items": [
                    {
                        "item_id": "technical-1",
                        "title": "技术方案",
                        "max_score": 20,
                        "criteria": "方案完整，提供技术方案",
                        "evidence_required": ["技术方案"],
                    }
                ],
                "bidder_profile": {
                    "bidder_id": "bidder-1",
                    "materials": [
                        {
                            "material_id": "license-material",
                            "material_type": "business_license",
                            "title": "营业执照",
                        }
                    ],
                },
                "plan": [
                    {
                        "skill_name": "tender-decomposition",
                        "input": {
                            "project_id": {"$ref": "$request/project_id"},
                            "requirements": {"$ref": "$request/requirements"},
                            "scoring_items": {"$ref": "$request/scoring_items"},
                        },
                    },
                    {
                        "skill_name": "bid-feasibility",
                        "input": {
                            "project_id": {"$ref": "$request/project_id"},
                            "requirements": {
                                "$ref": "$state/tender-decomposition/requirements"
                            },
                            "bidder_profile": {
                                "$ref": "$request/bidder_profile"
                            },
                        },
                    },
                    {
                        "skill_name": "evidence-matching",
                        "input": {
                            "requirements": {
                                "$ref": "$state/tender-decomposition/requirements"
                            },
                            "scoring_items": {
                                "$ref": "$state/tender-decomposition/scoring_items"
                            },
                            "materials": {
                                "$ref": "$request/bidder_profile/materials"
                            },
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
        "evidence-matching",
    ]
    assert result.steps[1].result.data["decision"] == "bid"
    assert result.output["summary"]["matched_count"] == 1
