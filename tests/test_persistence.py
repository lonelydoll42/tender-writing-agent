from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qiaowenshu_agent.api import create_app
from qiaowenshu_agent.core.contracts import (
    SkillManifest,
    SkillRequest,
    SkillResult,
)
from qiaowenshu_agent.core.files import ProjectFileRegistry
from qiaowenshu_agent.core.registry import SkillRegistry
from qiaowenshu_agent.core.runtime import AgentRuntime
from qiaowenshu_agent.core.store import SQLiteStore


def test_sqlite_store_survives_restart_and_propagates_stale(tmp_path: Path) -> None:
    database = tmp_path / "qiaowenshu.sqlite3"
    first_store = SQLiteStore(database)
    first_registry = ProjectFileRegistry(first_store)

    first = first_registry.register(
        project_id="project-1",
        file_name="tender.txt",
        file_role="tender",
        content=b"version one",
    )
    parsed = first_registry.parse(first.file.file_id)
    profile = first_registry.save_artifact(
        {"project_name": "demo"},
        project_id="project-1",
        artifact_type="tender_profile",
        source_file_versions=[first_registry.file_version_token(first.file.file_id)],
    )
    ledger = first_registry.save_artifact(
        {"entry_count": 1},
        project_id="project-1",
        artifact_type="requirement_ledger",
        dependencies=[profile["artifact_id"]],
    )

    second = first_registry.register(
        project_id="project-1",
        file_name="tender.txt",
        file_role="tender",
        content=b"version two",
    )

    assert second.file.version == 2
    assert first_registry.artifact(parsed["artifact_id"])["status"] == "stale"
    assert first_registry.artifact(profile["artifact_id"])["status"] == "stale"
    assert first_registry.artifact(ledger["artifact_id"])["status"] == "stale"

    first_store.close()
    second_store = SQLiteStore(database)
    second_registry = ProjectFileRegistry(second_store)

    assert second_registry.project("project-1")["project_id"] == "project-1"
    assert second_registry.require(first.file.file_id).version == 1
    assert second_registry.require(second.file.file_id).version == 2
    assert second_registry.content(first.file.file_id) == b"version one"
    assert second_registry.artifact(profile["artifact_id"])["status"] == "stale"
    second_store.close()


class RetryableSkill:
    manifest = SkillManifest(
        name="retryable",
        version="1.0.0",
        description="fail once for recovery testing",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )

    async def execute(
        self,
        _request: SkillRequest,
        _context,
    ) -> SkillResult:
        return SkillResult.failure(
            message="temporary failure",
            error_code="TEMPORARY_FAILURE",
            retryable=True,
        )


class RecoveredSkill:
    manifest = SkillManifest(
        name="retryable",
        version="1.0.0",
        description="recovered implementation",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )

    async def execute(
        self,
        _request: SkillRequest,
        _context,
    ) -> SkillResult:
        return SkillResult.success({"ready": True})


class RecoveryEchoSkill:
    manifest = SkillManifest(
        name="recovery-echo",
        version="1.0.0",
        description="echo resumed state",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )

    async def execute(
        self,
        request: SkillRequest,
        _context,
    ) -> SkillResult:
        return SkillResult.success({"previous": request.input["previous"]})


@pytest.mark.asyncio
async def test_runtime_resumes_from_persisted_checkpoint(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "runs.sqlite3")
    first_registry = SkillRegistry()
    first_registry.register(RetryableSkill())
    first_registry.register(RecoveryEchoSkill())
    first_runtime = AgentRuntime(first_registry, services={"store": store})
    request = SkillRequest.create(
        {
            "project_id": "project-1",
            "plan": [
                {"skill_name": "retryable", "input": {}},
                {
                    "skill_name": "recovery-echo",
                    "input": {
                        "previous": {"$ref": "$state/retryable/ready"}
                    },
                },
            ],
        }
    )

    first_result = await first_runtime.run(request)

    assert first_result.status == "retryable_error"
    assert store.get_run(first_result.run_id).next_step_index == 0

    restarted_registry = SkillRegistry()
    restarted_registry.register(RecoveredSkill())
    restarted_registry.register(RecoveryEchoSkill())
    restarted_runtime = AgentRuntime(restarted_registry, services={"store": store})
    resumed = await restarted_runtime.resume(first_result.run_id)

    assert resumed.status == "success"
    assert [step.skill_name for step in resumed.steps] == [
        "retryable",
        "recovery-echo",
    ]
    assert resumed.output == {"previous": True}
    assert store.get_run(first_result.run_id).next_step_index == 2
    store.close()


def test_persistent_api_exposes_project_runs_artifacts_and_reviews(
    tmp_path: Path,
) -> None:
    database = tmp_path / "api.sqlite3"
    first_app = create_app(storage_path=database)
    first_client = TestClient(first_app)
    uploaded = first_client.post(
        "/v1/projects/project-1/files?file_name=tender.txt&file_role=tender",
        content=b"project content",
    )
    assert uploaded.status_code == 200
    file_id = uploaded.json()["file"]["file_id"]
    parsed = first_client.post(
        f"/v1/projects/project-1/files/{file_id}/parse"
    )
    assert parsed.status_code == 200
    first_app.state.store.close()

    second_app = create_app(storage_path=database)
    second_client = TestClient(second_app)
    assert second_client.get("/v1/projects/project-1").status_code == 200
    files = second_client.get("/v1/projects/project-1/files")
    assert files.json()["files"][0]["file_id"] == file_id
    artifacts = second_client.get("/v1/projects/project-1/artifacts")
    assert artifacts.json()["artifacts"][0]["status"] == "valid"

    created = second_client.post(
        "/v1/projects/project-1/reviews",
        json={
            "question": "请确认补遗是否已核对",
            "severity": "blocker",
            "review_type": "amendment_check",
            "affected_artifact_ids": [
                artifacts.json()["artifacts"][0]["artifact_id"]
            ],
        },
    )
    assert created.status_code == 200
    review_id = created.json()["review"]["review_id"]
    resolved = second_client.post(
        f"/v1/reviews/{review_id}/resolve",
        json={"resolution": {"confirmed": True}},
    )
    assert resolved.status_code == 200
    assert resolved.json()["review"]["status"] == "resolved"
    listed = second_client.get("/v1/projects/project-1/reviews?status=resolved")
    assert listed.json()["reviews"][0]["review_id"] == review_id
    second_app.state.store.close()
