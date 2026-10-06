from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

from qiaowenshu_agent.api import create_app
from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillManifest, SkillRequest, SkillResult
from qiaowenshu_agent.core.files import ProjectFileRegistry
from qiaowenshu_agent.core.registry import SkillRegistry
from qiaowenshu_agent.core.runtime import AgentRuntime
from qiaowenshu_agent.core.store import AgentRun, InMemoryStore, SQLiteStore
from qiaowenshu_agent.skills.compliance_review.skill import ComplianceReviewSkill


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
            capabilities=(
                ("tender.analysis_report",) if name == "analysis-report" else ()
            ),
        )
        self.calls = 0
        self.response = response

    async def execute(
        self,
        request: SkillRequest,
        _context: SkillContext,
    ) -> SkillResult:
        self.calls += 1
        if self.response is not None:
            return self.response(request)
        return SkillResult.success({"received": request.input})


def _runtime(
    skills: list[Any],
    *,
    services: dict[str, Any] | None = None,
) -> AgentRuntime:
    registry = SkillRegistry()
    for skill in skills:
        registry.register(skill)
    return AgentRuntime(registry, services=services)


def _missing_mandatory_requirement() -> dict[str, Any]:
    return {
        "ledger": {
            "entries": [
                {
                    "requirement_id": "R-HARD",
                    "mandatory": True,
                    "status": "missing",
                }
            ]
        }
    }


def _review_required_requirement() -> dict[str, Any]:
    return {
        "ledger": {
            "entries": [
                {
                    "requirement_id": "R-REVIEW",
                    "mandatory": True,
                    "status": "human_review",
                }
            ]
        }
    }


def _checked_passing_ledger() -> dict[str, Any]:
    return {
        "ledger": {
            "entries": [
                {
                    "requirement_id": "R-PASS",
                    "mandatory": True,
                    "status": "matched",
                }
            ]
        }
    }


@pytest.mark.asyncio
async def test_missing_hard_requirement_blocks_writing_but_keeps_report_diagnostics(
) -> None:
    report = CountingSkill("analysis-report")
    writer = CountingSkill("document-writing")
    runtime = _runtime([ComplianceReviewSkill(), report, writer])
    result = await runtime.run(
        SkillRequest.create(
            {
                "project_id": "project-1",
                "plan": [
                    {
                        "skill_name": "compliance-review",
                        "input": _missing_mandatory_requirement(),
                    },
                    {"skill_name": "analysis-report", "input": {}},
                    {"skill_name": "document-writing", "input": {}},
                ],
            }
        )
    )

    assert result.status == "blocked"
    assert result.execution_status == "blocked"
    assert result.business_status == "failed"
    assert result.submission_allowed is False
    assert result.steps[0].result.status == "partial"
    assert result.steps[0].result.data["business_status"] == "failed"
    assert result.steps[0].result.data["checked"] is True
    assert result.steps[0].result.data["submission_allowed"] is False
    assert report.calls == 1
    assert writer.calls == 0
    assert result.steps[-1].result.error_code == "COMPLIANCE_GATE_BLOCKED"
    assert "business_status is failed" in result.steps[-1].result.message


@pytest.mark.asyncio
async def test_review_required_blocks_writing_and_allows_report() -> None:
    report = CountingSkill("analysis-report")
    writer = CountingSkill("document-writing")
    runtime = _runtime([ComplianceReviewSkill(), report, writer])
    result = await runtime.run(
        SkillRequest.create(
            {
                "plan": [
                    {
                        "skill_name": "compliance-review",
                        "input": _review_required_requirement(),
                    },
                    {"skill_name": "analysis-report", "input": {}},
                    {"skill_name": "document-writing", "input": {}},
                ]
            }
        )
    )

    assert result.business_status == "needs_review"
    assert result.steps[0].result.data["checked"] is True
    assert result.steps[0].result.data["scoped_gate_passed"] is False
    assert report.calls == 1
    assert writer.calls == 0


@pytest.mark.asyncio
async def test_scoped_pass_allows_draft_but_never_authorizes_submission() -> None:
    writer = CountingSkill("document-writing")
    runtime = _runtime([ComplianceReviewSkill(), writer])
    scoped_requirement = {
        "requirement_id": "R-PASS",
        "category": "technical",
        "title": "技术要求",
        "description": "交付方案需符合项目要求",
        "mandatory": True,
    }
    scoped_review = {
        "project_id": "project-1",
        "requirements": [scoped_requirement],
        "scoring_items": [],
        "ledger": {
            "entries": [
                {
                    "requirement_id": "R-PASS",
                    "mandatory": True,
                    "status": "matched",
                }
            ]
        },
        "sections": [
            {
                "section_id": "technical",
                "title": "技术方案",
                "kind": "technical",
                "requirement_ids": ["R-PASS"],
            }
        ],
        "writing_scope": ["technical"],
    }
    scoped_writer_input = {
        "project_id": "project-1",
        "requirements": [scoped_requirement],
        "scoring_items": [],
        "sections": scoped_review["sections"],
        "writing_scope": ["technical"],
    }
    result = await runtime.run(
        SkillRequest.create(
            {
                "plan": [
                    {
                        "skill_name": "compliance-review",
                        "input": scoped_review,
                    },
                    {
                        "skill_name": "document-writing",
                        "input": scoped_writer_input,
                    },
                ]
            }
        )
    )

    payload = result.to_dict()
    compliance = result.steps[0].result.data
    assert writer.calls == 1
    assert compliance["business_status"] == "passed"
    assert compliance["checked"] is True
    assert compliance["summary"]["passed"] is True
    assert compliance["scoped_gate_passed"] is True
    assert compliance["submission_allowed"] is False
    assert payload["execution_status"] == "completed"
    assert payload["business_status"] == "passed"
    assert payload["scoped_gate_passed"] is True
    assert payload["submission_allowed"] is False


@pytest.mark.asyncio
async def test_empty_review_scope_is_not_checked_and_blocks_writing() -> None:
    report = CountingSkill("analysis-report")
    writer = CountingSkill("document-writing")
    runtime = _runtime([ComplianceReviewSkill(), report, writer])
    result = await runtime.run(
        SkillRequest.create(
            {
                "plan": [
                    {"skill_name": "compliance-review", "input": {}},
                    {"skill_name": "analysis-report", "input": {}},
                    {"skill_name": "document-writing", "input": {}},
                ]
            }
        )
    )

    assert result.business_status == "not_checked"
    assert result.steps[0].result.data["business_status"] == "not_checked"
    assert result.steps[0].result.data["checked"] is False
    assert report.calls == 1
    assert writer.calls == 0


@pytest.mark.asyncio
async def test_partial_and_nested_pdf_warnings_survive_later_success() -> None:
    def parsed_pdf(_request: SkillRequest) -> SkillResult:
        return SkillResult.success(
            {"pages": [{"warnings": ["PDF OCR confidence is insufficient"]}]}
        )

    def decomposition(_request: SkillRequest) -> SkillResult:
        return SkillResult.success({"warnings": ["requirement needs verification"]})

    def partial_result(_request: SkillRequest) -> SkillResult:
        return SkillResult.partial(
            {"status": "uncertain"},
            warnings=["one requirement remains unresolved"],
        )

    preprocess = CountingSkill("document-preprocess", parsed_pdf)
    decompose = CountingSkill("tender-decomposition", decomposition)
    partial = CountingSkill("evidence-matching", partial_result)
    report = CountingSkill("analysis-report")
    runtime = _runtime(
        [
            preprocess,
            decompose,
            partial,
            ComplianceReviewSkill(),
            report,
        ]
    )
    result = await runtime.run(
        SkillRequest.create(
            {
                "plan": [
                    {"skill_name": "document-preprocess", "input": {}},
                    {"skill_name": "tender-decomposition", "input": {}},
                    {"skill_name": "evidence-matching", "input": {}},
                    {
                        "skill_name": "compliance-review",
                        "input": _checked_passing_ledger(),
                    },
                    {"skill_name": "analysis-report", "input": {}},
                ]
            }
        )
    )

    payload = result.to_dict()
    assert result.status == "partial"
    assert payload["execution_status"] == "completed"
    assert report.calls == 1
    assert result.steps[-1].result.status == "success"
    assert payload["business_status"] == "needs_review"
    assert payload["scoped_gate_passed"] is False
    assert payload["submission_allowed"] is False
    assert "PDF OCR confidence is insufficient" in payload["warnings"]
    assert "requirement needs verification" in payload["warnings"]
    assert "one requirement remains unresolved" in payload["warnings"]
    run_finished = [
        event for event in result.events if event["event_type"] == "run_finished"
    ][-1]
    assert run_finished["payload"]["status"] == result.status


@pytest.mark.asyncio
async def test_nested_non_string_business_status_fails_closed_without_type_error(
) -> None:
    malformed = CountingSkill(
        "malformed-analysis",
        lambda _request: SkillResult.success(
            {"diagnostics": [{"business_status": []}]}
        ),
    )
    runtime = _runtime([malformed])

    result = await runtime.run(
        SkillRequest.create(
            {
                "plan": [{"skill_name": "malformed-analysis", "input": {}}],
            }
        )
    )

    payload = result.to_dict()
    assert payload["business_status"] == "not_checked"
    assert payload["scoped_gate_passed"] is False
    assert payload["submission_allowed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("store_kind", ["memory", "sqlite"])
async def test_file_replacement_during_last_skill_blocks_completed_run(
    store_kind: str,
    tmp_path: Path,
) -> None:
    store = (
        InMemoryStore()
        if store_kind == "memory"
        else SQLiteStore(tmp_path / "racing-upload.sqlite3")
    )
    files = ProjectFileRegistry(store)
    original = files.register(
        project_id="race",
        file_name="tender.pdf",
        file_role="tender",
        content=b"old tender",
    )

    def replace_file_during_analysis(_request: SkillRequest) -> SkillResult:
        files.register(
            project_id="race",
            file_name="tender.pdf",
            file_role="tender",
            content=b"new tender uploaded during execution",
        )
        return SkillResult.success({"report": "based on old tender"})

    analysis = CountingSkill("final-analysis", replace_file_during_analysis)
    runtime = _runtime(
        [ComplianceReviewSkill(), analysis],
        services={"store": store, "file_registry": files},
    )
    result = await runtime.run(
        SkillRequest.create(
            {
                "project_id": "race",
                "file_ids": [original.file.file_id],
                "plan": [
                    {
                        "skill_name": "compliance-review",
                        "input": _checked_passing_ledger(),
                    },
                    {"skill_name": "final-analysis", "input": {}},
                ],
            }
        ),
        run_id="racing-upload-run",
    )

    artifacts = files.artifacts("race")
    assert result.status == "blocked"
    assert result.execution_status == "blocked"
    assert result.output["error_code"] == "STALE_RUN_DEPENDENCIES"
    assert result.business_status == "not_checked"
    assert result.scoped_gate_passed is False
    assert result.submission_allowed is False
    assert analysis.calls == 1
    assert len(artifacts) == 2
    assert {item["status"] for item in artifacts} == {"stale"}
    terminal_event = result.events[-1]
    assert terminal_event["event_type"] == "run_failed"
    assert terminal_event["payload"]["status"] == "blocked"
    assert terminal_event["payload"]["error_code"] == "STALE_RUN_DEPENDENCIES"

    if isinstance(store, SQLiteStore):
        store.close()
        restarted_store = SQLiteStore(tmp_path / "racing-upload.sqlite3")
        restarted_files = ProjectFileRegistry(restarted_store)
        restarted_runtime = _runtime(
            [],
            services={
                "store": restarted_store,
                "file_registry": restarted_files,
            },
        )
        snapshot = restarted_runtime.inspect_run("racing-upload-run")
        assert snapshot is not None
        assert snapshot["status"] == "blocked"
        assert snapshot["business_status"] == "not_checked"
        assert snapshot["scoped_gate_passed"] is False
        assert snapshot["dependency_status"] == "stale"
        restarted_store.close()


@pytest.mark.asyncio
async def test_structured_versioned_references_are_validated_but_external_refs_are_not(
) -> None:
    store = InMemoryStore()
    files = ProjectFileRegistry(store)
    original = files.register(
        project_id="project-1",
        file_name="source.pdf",
        file_role="tender",
        content=b"registered source",
    )
    files.register(
        project_id="project-1",
        file_name="source.pdf",
        file_role="tender",
        content=b"replacement source",
    )
    probe = CountingSkill("probe")
    runtime = _runtime([probe], services={"file_registry": files})
    stale_reference = await runtime.run(
        SkillRequest.create(
            {
                "project_id": "project-1",
                "materials": [
                    {
                        "source_references": [
                            {
                                "document_id": original.file.file_id,
                                "source_version": f"{original.file.file_id}:v1",
                            }
                        ]
                    }
                ],
                "plan": [{"skill_name": "probe"}],
            }
        )
    )
    external_reference = await runtime.run(
        SkillRequest.create(
            {
                "project_id": "project-1",
                "requirements": [
                    {
                        "source_references": [
                            {
                                "document_id": "tender.pdf",
                                "source_version": "tender.pdf",
                            }
                        ]
                    }
                ],
                "plan": [{"skill_name": "probe"}],
            }
        )
    )

    assert stale_reference.status == "blocked"
    assert stale_reference.output["error_code"] == "STALE_RUN_DEPENDENCIES"
    assert probe.calls == 1
    assert external_reference.status == "success"


@pytest.mark.asyncio
async def test_custom_plan_without_compliance_cannot_call_writer() -> None:
    writer = CountingSkill("document-writing")
    report = CountingSkill("analysis-report")
    runtime = _runtime([writer, report])
    result = await runtime.run(
        SkillRequest.create(
            {
                "plan": [
                    {"skill_name": "analysis-report", "input": {}},
                    {"skill_name": "document-writing", "input": {}},
                ]
            }
        )
    )

    assert report.calls == 1
    assert writer.calls == 0
    assert result.steps[-1].result.error_code == "COMPLIANCE_GATE_BLOCKED"
    assert result.steps[-1].result.data["business_status"] == "not_checked"


@pytest.mark.asyncio
async def test_explicit_missing_file_blocks_before_any_skill() -> None:
    store = InMemoryStore()
    files = ProjectFileRegistry(store)
    probe = CountingSkill("probe")
    runtime = _runtime([probe], services={"file_registry": files})
    result = await runtime.run(
        SkillRequest.create(
            {
                "project_id": "project-1",
                "file_ids": ["file-does-not-exist"],
                "plan": [{"skill_name": "probe"}],
            }
        )
    )

    assert result.status == "blocked"
    assert result.output["error_code"] == "STALE_RUN_DEPENDENCIES"
    assert result.output["dependency_issues"][0]["type"] == "file_missing"
    assert probe.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("store_kind", ["memory", "sqlite"])
async def test_completed_resume_rejects_superseded_file_and_preserves_record(
    store_kind: str,
    tmp_path: Path,
) -> None:
    store = (
        InMemoryStore()
        if store_kind == "memory"
        else SQLiteStore(tmp_path / "resume.sqlite3")
    )
    files = ProjectFileRegistry(store)
    original = files.register(
        project_id="project-1",
        file_name="tender.txt",
        file_role="tender",
        content=b"version one",
    )
    probe = CountingSkill("probe")
    runtime = _runtime([probe], services={"file_registry": files})
    request = SkillRequest.create(
        {
            "project_id": "project-1",
            "file_ids": [original.file.file_id],
            "plan": [{"skill_name": "probe"}],
        }
    )
    first = await runtime.run(request, run_id="completed-file-run")
    original_record = store.get_run(first.run_id)

    files.register(
        project_id="project-1",
        file_name="tender.txt",
        file_role="tender",
        content=b"version two",
    )
    resumed = await runtime.resume(first.run_id)
    new_run = await runtime.run(request, run_id="new-run-with-old-file")

    assert first.status == "success"
    assert original_record.status == "success"
    assert resumed.status == "blocked"
    assert resumed.output["error_code"] == "STALE_RUN_DEPENDENCIES"
    assert new_run.status == "blocked"
    assert new_run.output["error_code"] == "STALE_RUN_DEPENDENCIES"
    assert probe.calls == 1
    assert store.get_run(first.run_id).status == "success"
    assert (
        files.artifact(first_record_artifact_id(original_record))["status"]
        == "stale"
    )
    if isinstance(store, SQLiteStore):
        store.close()


def first_record_artifact_id(record: AgentRun) -> str:
    return next(item for item in record.artifact_ids if item)


@pytest.mark.asyncio
@pytest.mark.parametrize("dependency_kind", ["missing", "superseded_source"])
async def test_resume_checks_recursive_artifact_dependencies(
    dependency_kind: str,
) -> None:
    store = InMemoryStore()
    files = ProjectFileRegistry(store)
    source = files.register(
        project_id="project-1",
        file_name="source.txt",
        file_role="tender",
        content=b"version one",
    )
    if dependency_kind == "superseded_source":
        files.register(
            project_id="project-1",
            file_name="source.txt",
            file_role="tender",
            content=b"version two",
        )
        leaf = files.save_artifact(
            {"level": "leaf"},
            project_id="project-1",
            artifact_type="leaf",
            source_file_versions=[f"{source.file.file_id}:v1"],
        )
    else:
        leaf = files.save_artifact(
            {"level": "leaf"},
            project_id="project-1",
            artifact_type="leaf",
        )
    middle = files.save_artifact(
        {"level": "middle"},
        project_id="project-1",
        artifact_type="middle",
        dependencies=[leaf["artifact_id"]],
    )
    root = files.save_artifact(
        {"level": "root"},
        project_id="project-1",
        artifact_type="root",
        dependencies=[middle["artifact_id"]],
    )
    if dependency_kind == "missing":
        leaf_record = store.get_artifact(leaf["artifact_id"])
        store.save_artifact(
            replace(leaf_record, dependencies=["missing-deep-dependency"])
        )
    store.save_run(
        AgentRun(
            run_id="recursive-run",
            project_id="project-1",
            request={
                "request_id": "request-1",
                "input": {"project_id": "project-1"},
            },
            status="success",
            artifact_ids=[root["artifact_id"]],
            next_step_index=1,
        )
    )
    runtime = _runtime([], services={"store": store, "file_registry": files})

    resumed = await runtime.resume("recursive-run")

    assert resumed.status == "blocked"
    assert resumed.output["error_code"] == "STALE_RUN_DEPENDENCIES"
    issue_types = {item["type"] for item in resumed.output["dependency_issues"]}
    assert (
        "artifact_missing" in issue_types
        if dependency_kind == "missing"
        else "file_superseded" in issue_types
    )


@pytest.mark.asyncio
async def test_whole_state_reference_records_artifact_dependency() -> None:
    store = InMemoryStore()
    files = ProjectFileRegistry(store)
    source = files.register(
        project_id="project-1",
        file_name="source.txt",
        file_role="tender",
        content=b"source text",
    )
    producer = CountingSkill("producer")
    consumer = CountingSkill("consumer")
    runtime = _runtime(
        [producer, consumer],
        services={"file_registry": files},
    )
    result = await runtime.run(
        SkillRequest.create(
            {
                "project_id": "project-1",
                "file_ids": [source.file.file_id],
                "plan": [
                    {
                        "skill_name": "producer",
                        "input": {"file_ids": {"$ref": "$request/file_ids"}},
                    },
                    {
                        "skill_name": "consumer",
                        "input": {"snapshot": {"$ref": "$state"}},
                    },
                ],
            }
        ),
        run_id="full-state-dependency",
    )

    artifacts = files.artifacts("project-1")
    consumer_artifact = next(
        item
        for item in artifacts
        if item["artifact_type"] == "skill_output:consumer"
    )
    assert result.status == "success"
    assert consumer_artifact["dependencies"] == [
        next(
            item["artifact_id"]
            for item in artifacts
            if item["artifact_type"] == "skill_output:producer"
        )
    ]


def test_run_get_snapshot_matches_runtime_after_restart_and_shows_stale(
    tmp_path: Path,
) -> None:
    database = tmp_path / "run-inspection.sqlite3"
    first_store = SQLiteStore(database)
    first_files = ProjectFileRegistry(first_store)
    source = first_files.register(
        project_id="project-api",
        file_name="tender.txt",
        file_role="tender",
        content=b"original tender",
    )
    first_probe = CountingSkill("probe")
    first_runtime = _runtime(
        [first_probe],
        services={"store": first_store, "file_registry": first_files},
    )
    first_app = create_app(agent_runtime=first_runtime)
    with TestClient(first_app) as client:
        posted = client.post(
            "/v1/agent/runs",
            json={
                "input": {
                    "project_id": "project-api",
                    "file_ids": [source.file.file_id],
                    "plan": [{"skill_name": "probe"}],
                }
            },
        )
        assert posted.status_code == 200
        post_run = posted.json()
        run_id = post_run["run_id"]
        before_restart = client.get(f"/v1/agent/runs/{run_id}").json()["run"]
    first_store.close()

    second_store = SQLiteStore(database)
    second_files = ProjectFileRegistry(second_store)
    second_runtime = _runtime(
        [CountingSkill("probe")],
        services={"store": second_store, "file_registry": second_files},
    )
    second_app = create_app(agent_runtime=second_runtime)
    with TestClient(second_app) as client:
        after_restart = client.get(f"/v1/agent/runs/{run_id}").json()["run"]
        assert after_restart["status"] == post_run["status"]
        assert after_restart["execution_status"] == post_run["execution_status"]
        assert after_restart["business_status"] == post_run["business_status"]
        assert after_restart["needs_human_review"] == post_run["needs_human_review"]
        assert after_restart["submission_allowed"] is False
        assert after_restart["request"] == before_restart["request"]
        assert after_restart["state"] == before_restart["state"]
        assert after_restart["plan"] == before_restart["plan"]
        assert after_restart["budget"] == before_restart["budget"]

        second_files.register(
            project_id="project-api",
            file_name="tender.txt",
            file_role="tender",
            content=b"updated tender",
        )
        stale_snapshot = client.get(f"/v1/agent/runs/{run_id}").json()["run"]

    persisted = second_store.get_run(run_id)
    second_store.close()

    assert first_probe.calls == 1
    assert stale_snapshot["status"] == "blocked"
    assert stale_snapshot["execution_status"] == "blocked"
    assert stale_snapshot["business_status"] == "not_checked"
    assert stale_snapshot["submission_allowed"] is False
    assert stale_snapshot["dependency_status"] == "stale"
    assert stale_snapshot["persisted_status"] == "success"
    assert stale_snapshot["request"] == before_restart["request"]
    assert stale_snapshot["state"] == before_restart["state"]
    assert stale_snapshot["plan"] == before_restart["plan"]
    assert stale_snapshot["budget"] == before_restart["budget"]
    assert stale_snapshot["dependency_issues"]
    assert persisted.status == "success"


def test_run_get_snapshot_keeps_running_distinct_from_blocked() -> None:
    store = InMemoryStore()
    store.save_run(
        AgentRun(
            run_id="active-run",
            request={"request_id": "request-active", "input": {}},
            status="running",
        )
    )
    runtime = _runtime([], services={"store": store})
    app = create_app(agent_runtime=runtime)

    with TestClient(app) as client:
        snapshot = client.get("/v1/agent/runs/active-run").json()["run"]

    assert snapshot["status"] == "running"
    assert snapshot["execution_status"] == "running"
    assert snapshot["business_status"] == "not_checked"
    assert snapshot["needs_human_review"] is True
    assert snapshot["submission_allowed"] is False
    assert snapshot["persisted_status"] == "running"
    assert store.get_run("active-run").status == "running"
