from __future__ import annotations

import pytest

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import (
    SkillManifest,
    SkillRequest,
    SkillResult,
)
from qiaowenshu_agent.core.registry import SkillRegistry
from qiaowenshu_agent.core.runtime import AgentRuntime, DeterministicPlanner


class EchoSkill:
    manifest = SkillManifest(
        name="echo",
        version="1.0.0",
        description="echo input",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )

    async def execute(
        self,
        request: SkillRequest,
        _context: SkillContext,
    ) -> SkillResult:
        return SkillResult.success({"echo": request.input})


@pytest.mark.asyncio
async def test_runtime_executes_explicit_skill_and_records_events() -> None:
    registry = SkillRegistry()
    registry.register(EchoSkill())
    runtime = AgentRuntime(registry)
    request = SkillRequest.create({"value": 7}, skill_name="echo")

    result = await runtime.run(request)

    assert result.status == "success"
    assert result.output == {"echo": {"value": 7}}
    assert [event["event_type"] for event in result.events] == [
        "run_started",
        "plan_created",
        "skill_started",
        "skill_finished",
        "run_finished",
    ]
    assert any(entry["event_type"] == "skill_finished" for entry in result.trace)


@pytest.mark.asyncio
async def test_runtime_returns_blocked_when_no_skill_matches() -> None:
    registry = SkillRegistry()
    runtime = AgentRuntime(registry, planner=None)

    result = await runtime.run(SkillRequest.create({"task": "unknown"}))

    assert result.status == "blocked"
    assert result.message == "no skill matched the request"


@pytest.mark.asyncio
async def test_runtime_returns_reason_when_skill_is_missing() -> None:
    registry = SkillRegistry()
    runtime = AgentRuntime(registry)

    result = await runtime.run(
        SkillRequest.create({}, skill_name="missing-skill")
    )

    assert result.status == "error"
    assert result.steps[0].result.error_code == "SKILL_NOT_FOUND"


@pytest.mark.asyncio
async def test_runtime_can_execute_an_explicit_multi_skill_plan() -> None:
    registry = SkillRegistry()
    registry.register(EchoSkill())
    runtime = AgentRuntime(registry)

    result = await runtime.run(
        SkillRequest.create(
            {
                "plan": [
                    {"skill_name": "echo", "input": {"stage": "one"}},
                    {
                        "skill_name": "echo",
                        "input": {
                            "stage": "two",
                            "previous_stage": {
                                "$ref": "$state/echo/echo/stage"
                            },
                        },
                    },
                ]
            }
        )
    )

    assert result.status == "success"
    assert len(result.steps) == 2
    assert result.steps[1].result.data == {
        "echo": {"stage": "two", "previous_stage": "one"}
    }


@pytest.mark.asyncio
async def test_runtime_rejects_unavailable_step_input_reference() -> None:
    registry = SkillRegistry()
    registry.register(EchoSkill())
    runtime = AgentRuntime(registry)

    result = await runtime.run(
        SkillRequest.create(
            {
                "plan": [
                    {
                        "skill_name": "echo",
                        "input": {"value": {"$ref": "$state/missing/value"}},
                    }
                ]
            }
        )
    )

    assert result.status == "error"
    assert result.steps[0].result.error_code == "INVALID_STEP_INPUT_REFERENCE"


@pytest.mark.parametrize(
    ("task", "expected_skill"),
    [
        ("判断投标可行性", "bid-feasibility"),
        ("拆解评分标准并制定得分策略", "scoring-strategy"),
        ("匹配企业证明材料", "evidence-matching"),
    ],
)
def test_deterministic_planner_routes_tender_workflow_tasks(
    task: str,
    expected_skill: str,
) -> None:
    planner = DeterministicPlanner()

    plan = planner.plan(SkillRequest.create({"task": task}), SkillRegistry())

    assert [step.skill_name for step in plan] == [expected_skill]
