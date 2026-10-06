from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import pytest

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillManifest, SkillRequest, SkillResult
from qiaowenshu_agent.core.registry import SkillRegistry
from qiaowenshu_agent.core.runtime import AgentRuntime
from qiaowenshu_agent.core.scope_authorization import (
    SCOPE_BINDINGS_STATE_KEY,
    _fingerprint,
    build_writing_scope,
    public_binding,
)
from qiaowenshu_agent.core.store import InMemoryStore, SQLiteStore
from qiaowenshu_agent.api import ProjectAnalyzeRequest, _project_analysis_plan
from qiaowenshu_agent.skills.compliance_review.skill import ComplianceReviewSkill


REQUIREMENT_A = {
    "requirement_id": "R-A",
    "category": "technical",
    "title": "接口要求",
    "description": "接口响应时间不高于两秒",
    "mandatory": True,
    "check_rule": {"operator": "lte", "value": 2, "unit": "second"},
    "source_references": [
        {"document_id": "tender-v1", "file_version": "v1", "page": 2}
    ],
}
SCORE_A = {
    "item_id": "S-A",
    "title": "方案评分",
    "criteria": "方案完整且可执行",
    "max_score": 5,
    "source_references": [
        {"document_id": "tender-v1", "file_version": "v1", "page": 5}
    ],
}
SECTIONS = [
    {
        "section_id": "technical",
        "title": "技术方案",
        "kind": "technical",
        "requirement_ids": ["R-A"],
        "source_references": [
            {"document_id": "tender-v1", "file_version": "v1", "page": 2}
        ],
    },
    {
        "section_id": "commercial",
        "title": "商务响应",
        "kind": "commercial",
        "source_references": [{"document_id": "tender-v1", "page": 7}],
    },
]


class CountingSkill:
    def __init__(
        self,
        name: str,
        response: Callable[[SkillRequest], SkillResult] | None = None,
    ) -> None:
        self.manifest = SkillManifest(
            name=name,
            version="1.0.0",
            description="test skill",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            capabilities=("tender.technical_writing",)
            if name == "document-writing"
            else (),
        )
        self.calls = 0
        self.response = response
        self.inputs: list[dict[str, Any]] = []

    async def execute(
        self,
        request: SkillRequest,
        _context: SkillContext,
    ) -> SkillResult:
        self.calls += 1
        self.inputs.append(copy.deepcopy(request.input))
        if self.response is not None:
            return self.response(request)
        return SkillResult.success({"received": request.input})


def _review_input(
    project_id: str = "project-A",
    *,
    requirements: list[dict[str, Any]] | None = None,
    scoring_items: list[dict[str, Any]] | None = None,
    sections: list[dict[str, Any]] | None = None,
    materials: list[dict[str, Any]] | None = None,
    bidder_profile: dict[str, Any] | None = None,
    confirmed_facts: list[dict[str, Any]] | None = None,
    approved_commitments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    requirements = copy.deepcopy(
        [REQUIREMENT_A] if requirements is None else requirements
    )
    scoring_items = copy.deepcopy([SCORE_A] if scoring_items is None else scoring_items)
    entries = [
        {
            "requirement_id": item["requirement_id"],
            "mandatory": item.get("mandatory", False),
            "status": "matched",
        }
        for item in requirements
    ]
    entries.extend(
        {
            "requirement_id": item.get("item_id") or item.get("id"),
            "mandatory": False,
            "status": "matched",
        }
        for item in scoring_items
    )
    return {
        "project_id": project_id,
        "tender_profile": {"project_id": project_id, "title": "Tender A"},
        "requirements": requirements,
        "scoring_items": scoring_items,
        "ledger": {"entries": entries},
        "sections": copy.deepcopy(SECTIONS if sections is None else sections),
        "materials": copy.deepcopy(materials or []),
        "evidence_matches": [],
        "bidder_profile": copy.deepcopy(
            bidder_profile or {"bidder_id": "bidder-A", "name": "甲公司"}
        ),
        "confirmed_facts": copy.deepcopy(confirmed_facts or []),
        "approved_commitments": copy.deepcopy(approved_commitments or []),
        "writing_scope": ["technical"],
    }


def _writer_input(review: dict[str, Any], **changes: Any) -> dict[str, Any]:
    payload = {
        key: copy.deepcopy(review[key])
        for key in (
            "project_id",
            "tender_profile",
            "requirements",
            "scoring_items",
            "sections",
            "materials",
            "evidence_matches",
            "bidder_profile",
            "confirmed_facts",
            "approved_commitments",
            "writing_scope",
        )
        if key in review
    }
    payload.update(copy.deepcopy(changes))
    return payload


def _typed_collision_input() -> dict[str, Any]:
    return {
        "project_id": "project-typed-collision",
        "tender_profile": {
            "project_id": "project-typed-collision",
            "title": "Typed ID collision",
        },
        "requirements": [
            {
                "requirement_id": "SAME",
                "category": "technical",
                "mandatory": True,
                "description": "原要求",
            }
        ],
        "scoring_items": [
            {
                "item_id": "SAME",
                "title": "另一个评分项",
                "criteria": "未经ledger核对的评分要求",
                "max_score": 100,
            }
        ],
        "ledger": {
            "entries": [
                {
                    "requirement_id": "SAME",
                    "item_type": "requirement",
                    "mandatory": True,
                    "status": "matched",
                }
            ]
        },
        "sections": [
            {
                "section_id": "solution",
                "title": "技术方案",
                "requirement_ids": ["SAME"],
                "scoring_item_ids": ["SAME"],
            }
        ],
        "materials": [],
        "evidence_matches": [],
        "bidder_profile": {"bidder_id": "bidder-A", "name": "甲公司"},
        "confirmed_facts": [],
        "approved_commitments": [],
        "writing_scope": ["solution"],
    }


def _runtime(
    skills: list[Any],
    *,
    store: InMemoryStore | SQLiteStore | None = None,
) -> AgentRuntime:
    registry = SkillRegistry()
    for skill in skills:
        registry.register(skill)
    return AgentRuntime(registry, services={"store": store} if store else None)


def _plan(
    review: dict[str, Any],
    writer: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        {"skill_name": "compliance-review", "input": review},
        {"skill_name": "document-writing", "input": writer},
    ]


def test_default_project_analysis_plan_supplies_review_scope_inputs() -> None:
    plan = _project_analysis_plan(
        ProjectAnalyzeRequest(
            file_ids=["tender-file"],
            bidder_file_ids=["bidder-file"],
            as_of="2026-10-05",
        )
    )
    review_input = next(
        step["input"] for step in plan if step["skill_name"] == "compliance-review"
    )

    assert review_input["requirements"] == {
        "$ref": "$state/tender-decomposition/requirements"
    }
    assert review_input["scoring_items"] == {
        "$ref": "$state/tender-decomposition/scoring_items"
    }
    assert review_input["sections"] == {"$ref": "$state/tender-intake/sections"}
    assert review_input["materials"] == {
        "$ref": "$state/bidder-material-intake/materials"
    }
    assert review_input["bidder_profile"] == {
        "$ref": "$state/bidder-material-intake/bidder_profile"
    }
    assert review_input["as_of"] == {"$ref": "$request/as_of"}
    assert review_input["evidence_matches"] == {
        "$ref": "$state/evidence-matching/matches"
    }


@pytest.mark.asyncio
async def test_project_a_review_cannot_authorize_project_b_writer() -> None:
    review = _review_input()
    writer = CountingSkill("document-writing")
    runtime = _runtime([ComplianceReviewSkill(), writer])

    result = await runtime.run(
        SkillRequest.create(
            {
                "plan": _plan(
                    review,
                    _writer_input(review, project_id="project-B"),
                )
            }
        )
    )

    assert writer.calls == 0
    assert result.steps[0].result.data["business_status"] == "passed"
    assert result.steps[0].result.data["runtime_scope_binding"]["status"] == "bound"
    assert result.steps[-1].result.error_code == "SCOPE_BINDING_BLOCKED"
    assert result.steps[-1].result.data["scope_binding_decision"]["status"] == "blocked"
    assert any(
        item["code"] == "project_mismatch"
        for item in result.steps[-1].result.data["scope_binding_decision"]["reasons"]
    )
    assert result.business_status == "passed"
    assert result.scoped_gate_passed is False
    assert result.submission_allowed is False


@pytest.mark.asyncio
async def test_exact_scope_reaches_writer_once() -> None:
    review = _review_input()
    requirement_ids = {
        item["requirement_id"] for item in review["requirements"]
    }
    scoring_ids = {item["item_id"] for item in review["scoring_items"]}
    assert requirement_ids.isdisjoint(scoring_ids)
    writer = CountingSkill("document-writing")
    runtime = _runtime([ComplianceReviewSkill(), writer])

    result = await runtime.run(
        SkillRequest.create(
            {
                "project_id": "project-A",
                "plan": _plan(review, _writer_input(review)),
            }
        )
    )

    assert writer.calls == 1
    assert result.business_status == "passed"
    assert result.scoped_gate_passed is True
    assert result.submission_allowed is False
    authorization = result.output["runtime_scope_authorization"]
    assert authorization["project_id"] == "project-A"
    assert authorization["status"] == "authorized"


@pytest.mark.asyncio
async def test_typed_id_collision_is_not_reviewed_or_authorized() -> None:
    review = _typed_collision_input()
    writer = CountingSkill("document-writing")
    runtime = _runtime([ComplianceReviewSkill(), writer])

    result = await runtime.run(
        SkillRequest.create(
            {"plan": _plan(review, _writer_input(review))}
        )
    )

    review_result = result.steps[0].result
    binding = review_result.data["runtime_scope_binding"]
    assert writer.calls == 0
    assert review_result.data["business_status"] == "needs_review"
    assert review_result.data["check_coverage"]["requirement_count"] == 2
    assert binding["status"] == "not_bound"
    assert any(
        item["code"] == "requirement_scoring_id_collision"
        for item in binding["reasons"]
    )
    decision = result.steps[-1].result.data["scope_binding_decision"]
    assert any(
        item["code"] == "requirement_scoring_id_collision"
        for item in decision["reasons"]
    )


@pytest.mark.asyncio
async def test_request_project_inheritance_and_resolved_refs() -> None:
    review = _review_input()
    writer_scope = _writer_input(review)
    for scope in (review, writer_scope):
        scope.pop("project_id")
        scope["tender_profile"].pop("project_id")
    writer = CountingSkill("document-writing")
    runtime = _runtime([ComplianceReviewSkill(), writer])

    result = await runtime.run(
        SkillRequest.create(
            {
                "project_id": "project-A",
                "review_scope": review,
                "writer_scope": writer_scope,
                "plan": [
                    {
                        "skill_name": "compliance-review",
                        "input": {"$ref": "$request/review_scope"},
                    },
                    {
                        "skill_name": "document-writing",
                        "input": {"$ref": "$request/writer_scope"},
                    },
                ],
            }
        )
    )

    assert writer.calls == 1
    assert writer.inputs[0]["project_id"] == "project-A"
    assert result.output["runtime_scope_authorization"]["match_kind"] == "exact"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "reason_code"),
    [
        (
            {
                "requirements": [
                    {
                        **REQUIREMENT_A,
                        "check_rule": {"operator": "eq", "value": 3},
                    }
                ]
            },
            "requirement_content_changed",
        ),
        (
            {
                "requirements": [
                    REQUIREMENT_A,
                    {
                        **REQUIREMENT_A,
                        "requirement_id": "R-B",
                        "title": "新增要求",
                    },
                ]
            },
            "requirement_not_reviewed",
        ),
        (
            {
                "materials": [
                    {
                        "material_id": "M-A",
                        "title": "证书",
                        "source_references": [
                            {
                                "document_id": "tender-v1",
                                "source_file_version": "tender-v1:v2",
                            }
                        ],
                    }
                ]
            },
            "source_file_not_reviewed",
        ),
        (
            {
                "bidder_profile": {
                    "bidder_id": "bidder-B",
                    "name": "乙公司",
                }
            },
            "bidder_profile_changed",
        ),
        (
            {
                "confirmed_facts": [
                    {"fact_id": "F-A", "claim": "新增事实"}
                ]
            },
            "confirmed_fact_not_reviewed",
        ),
        (
            {
                "approved_commitments": [
                    {"commitment_id": "C-A", "text": "新增承诺"}
                ]
            },
            "approved_commitment_not_reviewed",
        ),
        (
            {"bid_deadline": "2027-01-01"},
            "scope_context_changed",
        ),
    ],
)
async def test_writer_scope_expansion_or_mutation_is_rejected_before_call(
    change: dict[str, Any],
    reason_code: str,
) -> None:
    review = _review_input()
    review["as_of"] = "2026-10-05"
    writer = CountingSkill("document-writing")
    runtime = _runtime([ComplianceReviewSkill(), writer])

    result = await runtime.run(
        SkillRequest.create(
            {"plan": _plan(review, _writer_input(review, **change))}
        )
    )

    assert writer.calls == 0
    decision = result.steps[-1].result.data["scope_binding_decision"]
    assert result.steps[-1].result.error_code == "SCOPE_BINDING_BLOCKED"
    assert any(item["code"] == reason_code for item in decision["reasons"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("selector", "expected_sections", "match_kind"),
    [
        (None, ["tech-plan", "commercial-response"], "exact"),
        ([], ["tech-plan", "commercial-response"], "exact"),
        (["tech-plan"], ["tech-plan"], "safe_subset"),
        (["technical"], ["tech-plan"], "safe_subset"),
    ],
)
async def test_omitted_empty_id_and_kind_scope_authorize_actual_sections(
    selector: list[str] | None,
    expected_sections: list[str],
    match_kind: str,
) -> None:
    review = _review_input()
    review["sections"][0]["section_id"] = "tech-plan"
    review["sections"][1]["section_id"] = "commercial-response"
    review.pop("writing_scope")
    writer = CountingSkill("document-writing")
    runtime = _runtime([ComplianceReviewSkill(), writer])
    writer_input = _writer_input(review)
    if selector is not None:
        writer_input["writing_scope"] = selector

    result = await runtime.run(
        SkillRequest.create({"plan": _plan(review, writer_input)})
    )

    assert writer.calls == 1
    binding = result.output["runtime_scope_authorization"]
    assert binding["status"] == "authorized"
    assert binding["match_kind"] == match_kind
    assert binding["sections"] == expected_sections


@pytest.mark.asyncio
async def test_same_unknown_scope_in_review_and_writer_blocks_before_call() -> None:
    review = _review_input()
    review["writing_scope"] = ["does-not-match"]
    writer_input = _writer_input(review)
    assert writer_input["writing_scope"] == review["writing_scope"]
    writer = CountingSkill("document-writing")
    runtime = _runtime([ComplianceReviewSkill(), writer])

    result = await runtime.run(
        SkillRequest.create({"plan": _plan(review, writer_input)})
    )

    assert writer.calls == 0
    assert result.business_status == "passed"
    review_binding = result.steps[0].result.data["runtime_scope_binding"]
    assert review_binding["status"] == "not_bound"
    assert any(
        item["code"] == "writing_scope_unresolvable"
        for item in review_binding["reasons"]
    )
    assert result.steps[-1].result.error_code == "SCOPE_BINDING_BLOCKED"
    assert any(
        item["code"] == "writing_scope_unresolvable"
        for item in result.steps[-1].result.data["scope_binding_decision"][
            "reasons"
        ]
    )


@pytest.mark.asyncio
async def test_scope_fallback_and_section_limit_cannot_expand_review() -> None:
    review = _review_input()
    review["max_sections"] = 1
    writer = CountingSkill("document-writing")
    runtime = _runtime([ComplianceReviewSkill(), writer])
    writer_input = _writer_input(
        review,
        writing_scope=["does-not-match"],
        max_sections=12,
    )

    result = await runtime.run(
        SkillRequest.create({"plan": _plan(review, writer_input)})
    )

    assert writer.calls == 0
    decision = result.steps[-1].result.data["scope_binding_decision"]
    assert any(
        item["code"] == "writing_scope_unresolvable"
        for item in decision["reasons"]
    )


@pytest.mark.asyncio
async def test_derived_default_outline_is_bound_by_actual_selected_chapters() -> None:
    review = _review_input(sections=[])
    review.pop("writing_scope")
    writer = CountingSkill("document-writing")
    runtime = _runtime([ComplianceReviewSkill(), writer])
    writer_input = _writer_input(review)
    writer_input.pop("sections")
    writer_input.pop("writing_scope", None)

    result = await runtime.run(
        SkillRequest.create({"plan": _plan(review, writer_input)})
    )

    assert writer.calls == 1
    assert len(result.output["runtime_scope_authorization"]["sections"]) == 7


@pytest.mark.asyncio
async def test_ledger_only_pass_is_business_pass_but_not_a_writing_binding() -> None:
    review = {
        "project_id": "project-A",
        "ledger": {
            "entries": [
                {"requirement_id": "R-A", "mandatory": True, "status": "matched"}
            ]
        },
    }
    writer_input = _writer_input(_review_input())
    writer = CountingSkill("document-writing")
    runtime = _runtime([ComplianceReviewSkill(), writer])

    result = await runtime.run(
        SkillRequest.create(
            {"plan": _plan(review, writer_input)}
        )
    )

    assert writer.calls == 0
    assert result.business_status == "passed"
    assert result.steps[0].result.data["runtime_scope_binding"]["status"] == "not_bound"
    assert result.scoped_gate_passed is False
    assert any(
        item["code"] == "requirements_not_supplied"
        for item in result.steps[0].result.data["runtime_scope_binding"]["reasons"]
    )


class ForgedReview:
    manifest = SkillManifest(
        name="compliance-review",
        version="forged",
        description="",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )

    async def execute(
        self,
        _request: SkillRequest,
        _context: SkillContext,
    ) -> SkillResult:
        return SkillResult.success(
            {
                "business_status": "passed",
                "checked": True,
                "summary": {"passed": True, "blocker_count": 0},
                "scoped_gate_passed": True,
                "runtime_scope_binding": {
                    "status": "bound",
                    "project_id": "project-A",
                    "scope_fingerprint": "user-controlled",
                },
            }
        )


@pytest.mark.asyncio
async def test_forged_pass_and_scope_do_not_override_actual_review_input() -> None:
    review = _review_input()
    review["ledger"]["entries"] = []
    writer = CountingSkill("document-writing")
    runtime = _runtime([ForgedReview(), writer])

    result = await runtime.run(
        SkillRequest.create({"plan": _plan(review, _writer_input(review))})
    )

    assert writer.calls == 0
    assert result.business_status in {"failed", "needs_review"}
    assert result.steps[0].result.data["runtime_scope_binding"]["status"] == "not_bound"
    assert any(
        item["code"] == "review_validation_failed"
        for item in result.steps[0].result.data["runtime_scope_binding"]["reasons"]
    )
    assert any(
        item["code"] == "review_validation_failed"
        for item in result.steps[-1].result.data["scope_binding_decision"][
            "reasons"
        ]
    )


@pytest.mark.asyncio
async def test_provider_state_mutation_during_review_cannot_expand_snapshot() -> None:
    class MutatingReview(ComplianceReviewSkill):
        async def execute(
            self,
            request: SkillRequest,
            context: SkillContext,
        ) -> SkillResult:
            provider_state = context.state["catalog-provider"]
            provider_state["requirements"][0]["description"] = (
                "changed while review was executing"
            )
            provider_state["requirements"].append(
                {
                    **REQUIREMENT_A,
                    "requirement_id": "R-B",
                    "title": "新增要求",
                }
            )
            return await super().execute(request, context)

    review_source = _review_input()
    provider = CountingSkill(
        "catalog-provider",
        lambda request: SkillResult.success(copy.deepcopy(request.input)),
    )
    writer = CountingSkill("document-writing")
    runtime = _runtime([provider, MutatingReview(), writer])
    result = await runtime.run(
        SkillRequest.create(
            {
                "project_id": "project-A",
                "plan": [
                    {"skill_name": "catalog-provider", "input": review_source},
                    {
                        "skill_name": "compliance-review",
                        "input": {"$ref": "$state/catalog-provider"},
                    },
                    {
                        "skill_name": "document-writing",
                        "input": {"$ref": "$state/catalog-provider"},
                    },
                ],
            }
        )
    )

    assert writer.calls == 0
    decision = result.steps[-1].result.data["scope_binding_decision"]
    assert any(
        item["code"] in {"requirement_content_changed", "requirement_not_reviewed"}
        for item in decision["reasons"]
    )
    record = runtime.store.get_run(result.run_id)
    assert record is not None
    binding = record.state["__runtime_review_scope_bindings_v1"]["bindings"][0]
    expected_scope, expected_reasons = build_writing_scope(
        review_source,
        request_input={"project_id": "project-A"},
        file_registry=None,
        artifact_dependencies=[],
    )
    assert expected_reasons == []
    assert binding["scope"] == expected_scope


@pytest.mark.asyncio
async def test_multiple_reviews_do_not_authorize_a_combined_writer() -> None:
    review_a = _review_input()
    requirement_b = {
        **REQUIREMENT_A,
        "requirement_id": "R-B",
        "title": "另一要求",
    }
    score_b = {**SCORE_A, "item_id": "S-B"}
    review_b = _review_input(
        requirements=[requirement_b],
        scoring_items=[score_b],
    )
    combined = _writer_input(
        review_a,
        requirements=[REQUIREMENT_A, requirement_b],
        scoring_items=[SCORE_A, score_b],
    )
    writer = CountingSkill("document-writing")
    runtime = _runtime([ComplianceReviewSkill(), writer])

    result = await runtime.run(
        SkillRequest.create(
            {
                "plan": [
                    {"skill_name": "compliance-review", "input": review_a},
                    {"skill_name": "compliance-review", "input": review_b},
                    {"skill_name": "document-writing", "input": combined},
                ]
            }
        )
    )

    assert writer.calls == 0
    decision = result.steps[-1].result.data["scope_binding_decision"]
    assert decision["status"] == "blocked"
    assert result.scoped_gate_passed is False


@pytest.mark.asyncio
async def test_sqlite_legacy_checkpoint_without_binding_cannot_resume_writer(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy-scope.sqlite3"
    store = SQLiteStore(database)
    review = _review_input()
    runtime = _runtime([ComplianceReviewSkill()], store=store)
    await runtime.run(
        SkillRequest.create(
            {
                "project_id": "project-A",
                "plan": [
                    {"skill_name": "compliance-review", "input": review}
                ],
            }
        ),
        run_id="legacy-scope-run",
    )
    record = store.get_run("legacy-scope-run")
    assert record is not None
    legacy_state = copy.deepcopy(record.state)
    legacy_state.pop("__runtime_review_scope_bindings_v1", None)
    legacy_steps = copy.deepcopy(record.steps)
    legacy_steps[0]["result"]["data"].pop("runtime_scope_binding", None)
    store.save_run(
        replace(
            record,
            plan=_plan(review, _writer_input(review)),
            status="running",
            state=legacy_state,
            steps=legacy_steps,
            next_step_index=1,
        )
    )
    store.close()

    restarted_store = SQLiteStore(database)
    writer = CountingSkill("document-writing")
    restarted = _runtime(
        [ComplianceReviewSkill(), writer],
        store=restarted_store,
    )
    resumed = await restarted.resume("legacy-scope-run")

    assert writer.calls == 0
    assert resumed.steps[-1].result.error_code == "SCOPE_BINDING_BLOCKED"
    assert any(
        item["code"] == "review_binding_missing"
        for item in resumed.steps[-1].result.data["scope_binding_decision"]["reasons"]
    )
    restarted_store.close()


@pytest.mark.asyncio
async def test_sqlite_legacy_collision_binding_cannot_authorize_score_subset(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy-collision-scope.sqlite3"
    store = SQLiteStore(database)
    seed_review = _review_input()
    runtime = _runtime([ComplianceReviewSkill()], store=store)
    await runtime.run(
        SkillRequest.create(
            {
                "project_id": "project-A",
                "plan": [
                    {"skill_name": "compliance-review", "input": seed_review}
                ],
            }
        ),
        run_id="legacy-collision-scope-run",
    )
    record = store.get_run("legacy-collision-scope-run")
    assert record is not None

    collision_review = _typed_collision_input()
    collision_scope, _ = build_writing_scope(
        collision_review,
        request_input={"project_id": "project-typed-collision"},
        file_registry=None,
        artifact_dependencies=[],
    )
    state = copy.deepcopy(record.state)
    bindings = state[SCOPE_BINDINGS_STATE_KEY]["bindings"]
    binding = bindings[0]
    binding.update(
        {
            "status": "bound",
            "project_id": collision_scope["project_id"],
            "scope": collision_scope,
            "scope_fingerprint": _fingerprint(collision_scope),
            "requirements_fingerprint": collision_scope[
                "requirements_fingerprint"
            ],
            "scoring_fingerprint": collision_scope["scoring_fingerprint"],
            "section_ids": collision_scope["section_ids"],
            "source_file_versions": collision_scope["source_file_versions"],
            "artifact_dependency_ids": collision_scope[
                "artifact_dependency_ids"
            ],
            "review_input_fingerprint": _fingerprint(collision_review),
            "reasons": [],
        }
    )
    binding.pop("integrity_digest", None)
    binding["integrity_digest"] = _fingerprint(binding)

    writer_input = _writer_input(collision_review)
    writer_input["requirements"] = []
    writer_input["sections"] = [
        {
            **collision_review["sections"][0],
            "requirement_ids": [],
            "scoring_item_ids": ["SAME"],
        }
    ]
    steps = copy.deepcopy(record.steps)
    review_data = steps[0]["result"]["data"]
    review_data.update(
        {
            "business_status": "passed",
            "checked": True,
            "needs_human_review": False,
            "scoped_gate_passed": True,
            "summary": {"passed": True, "blocker_count": 0},
            "runtime_scope_binding": public_binding(binding),
        }
    )
    state["compliance-review"] = copy.deepcopy(review_data)
    store.save_run(
        replace(
            record,
            plan=_plan(collision_review, writer_input),
            status="running",
            state=state,
            steps=steps,
            next_step_index=1,
        )
    )
    store.close()

    restarted_store = SQLiteStore(database)
    writer = CountingSkill("document-writing")
    restarted = _runtime(
        [ComplianceReviewSkill(), writer],
        store=restarted_store,
    )
    resumed = await restarted.resume("legacy-collision-scope-run")

    assert writer.calls == 0
    assert resumed.steps[-1].result.error_code == "SCOPE_BINDING_BLOCKED"
    decision_reasons = resumed.steps[-1].result.data[
        "scope_binding_decision"
    ]["reasons"]
    assert any(
        item["code"] == "requirement_scoring_id_collision"
        for item in decision_reasons
    )
    restarted_store.close()


@pytest.mark.asyncio
async def test_sqlite_legacy_invalid_scope_binding_cannot_resume_all_chapters(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy-invalid-selector.sqlite3"
    store = SQLiteStore(database)
    legacy_review = _review_input()
    legacy_review.pop("writing_scope")
    runtime = _runtime([ComplianceReviewSkill()], store=store)
    await runtime.run(
        SkillRequest.create(
            {
                "project_id": "project-A",
                "plan": [
                    {"skill_name": "compliance-review", "input": legacy_review}
                ],
            }
        ),
        run_id="legacy-invalid-selector-run",
    )
    record = store.get_run("legacy-invalid-selector-run")
    assert record is not None

    invalid_review = _review_input()
    invalid_review["writing_scope"] = ["does-not-match"]
    all_chapters_scope, scope_reasons = build_writing_scope(
        legacy_review,
        request_input={"project_id": "project-A"},
        file_registry=None,
        artifact_dependencies=[],
    )
    assert scope_reasons == []
    assert set(all_chapters_scope["section_ids"]) == {
        "technical",
        "commercial",
    }

    state = copy.deepcopy(record.state)
    binding = state[SCOPE_BINDINGS_STATE_KEY]["bindings"][0]
    binding.update(
        {
            "status": "bound",
            "project_id": all_chapters_scope["project_id"],
            "scope": all_chapters_scope,
            "scope_fingerprint": _fingerprint(all_chapters_scope),
            "requirements_fingerprint": all_chapters_scope[
                "requirements_fingerprint"
            ],
            "scoring_fingerprint": all_chapters_scope["scoring_fingerprint"],
            "section_ids": all_chapters_scope["section_ids"],
            "source_file_versions": all_chapters_scope["source_file_versions"],
            "artifact_dependency_ids": all_chapters_scope[
                "artifact_dependency_ids"
            ],
            "review_input_fingerprint": _fingerprint(invalid_review),
            "reasons": [],
        }
    )
    binding.pop("integrity_digest", None)
    binding["integrity_digest"] = _fingerprint(binding)

    steps = copy.deepcopy(record.steps)
    review_data = steps[0]["result"]["data"]
    review_data["runtime_scope_binding"] = public_binding(binding)
    state["compliance-review"] = copy.deepcopy(review_data)
    store.save_run(
        replace(
            record,
            plan=_plan(invalid_review, _writer_input(invalid_review)),
            status="running",
            state=state,
            steps=steps,
            next_step_index=1,
        )
    )
    store.close()

    restarted_store = SQLiteStore(database)
    writer = CountingSkill("document-writing")
    restarted = _runtime(
        [ComplianceReviewSkill(), writer],
        store=restarted_store,
    )
    resumed = await restarted.resume("legacy-invalid-selector-run")

    assert writer.calls == 0
    assert resumed.steps[-1].result.error_code == "SCOPE_BINDING_BLOCKED"
    assert any(
        item["code"] == "writing_scope_unresolvable"
        for item in resumed.steps[-1].result.data["scope_binding_decision"][
            "reasons"
        ]
    )
    restarted_store.close()


@pytest.mark.asyncio
async def test_sqlite_same_scope_writer_failure_can_resume_and_retry(
    tmp_path: Path,
) -> None:
    database = tmp_path / "scope-resume.sqlite3"
    store = SQLiteStore(database)
    review = _review_input()

    def fail_once(_request: SkillRequest) -> SkillResult:
        if writer.calls == 1:
            return SkillResult.failure(
                message="temporary writer failure",
                error_code="TEMPORARY_WRITER_FAILURE",
                retryable=True,
            )
        return SkillResult.success({"draft": "same authorized scope"})

    writer = CountingSkill("document-writing", fail_once)
    runtime = _runtime([ComplianceReviewSkill(), writer], store=store)
    request = SkillRequest.create(
        {
            "project_id": "project-A",
            "plan": _plan(review, _writer_input(review)),
        }
    )
    first = await runtime.run(request, run_id="scope-retry-run")

    assert writer.calls == 1
    assert first.status == "retryable_error"
    store.close()

    restarted_store = SQLiteStore(database)
    restarted_writer = CountingSkill(
        "document-writing",
        lambda _request: SkillResult.success({"draft": "same authorized scope"}),
    )
    restarted = _runtime(
        [ComplianceReviewSkill(), restarted_writer],
        store=restarted_store,
    )
    resumed = await restarted.resume("scope-retry-run")

    assert restarted_writer.calls == 1
    assert resumed.status == "success"
    assert resumed.output["runtime_scope_authorization"]["status"] == "authorized"
    assert resumed.output["runtime_scope_authorization"]["project_id"] == "project-A"
    restarted_store.close()
