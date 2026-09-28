from __future__ import annotations

from typing import Any, Mapping

import pytest

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.core.registry import SkillRegistry
from qiaowenshu_agent.core.runtime import AgentRuntime
from qiaowenshu_agent.skills import build_default_registry
from qiaowenshu_agent.skills.document_profile.skill import DocumentProfileSkill
from qiaowenshu_agent.skills.knowledge_retrieval.skill import (
    InMemoryRetrievalBackend,
    KnowledgeRetrievalSkill,
)


class FakeProfileBackend:
    def run(
        self,
        payload: Mapping[str, Any],
        _context: SkillContext,
    ) -> dict[str, Any]:
        return {
            "job_id": payload["job_id"],
            "profile": {"routing_category": "generic"},
            "anatomy": None,
        }


@pytest.mark.asyncio
async def test_document_profile_skill_uses_injected_backend() -> None:
    registry = SkillRegistry()
    registry.register(DocumentProfileSkill(backend=FakeProfileBackend()))
    runtime = AgentRuntime(registry)

    result = await runtime.run(
        SkillRequest.create(
            {
                "file_id": "file_1",
                "job_id": "job_1",
                "mode": "coarse",
            },
            skill_name="document-profile",
        )
    )

    assert result.status == "success"
    assert result.output["profile"]["routing_category"] == "generic"


@pytest.mark.asyncio
async def test_retrieval_skill_preserves_scoped_evidence_contract() -> None:
    backend = InMemoryRetrievalBackend(
        [
            {
                "document_id": "doc_1",
                "chunk_id": "chunk_1",
                "path": "采购要求/付款条件",
                "content": "采购人应在验收合格后付款。",
            },
            {
                "document_id": "doc_2",
                "chunk_id": "chunk_2",
                "path": "技术要求",
                "content": "系统需要支持数据备份。",
            },
        ]
    )
    registry = SkillRegistry()
    registry.register(KnowledgeRetrievalSkill(backend=backend))
    runtime = AgentRuntime(registry)

    result = await runtime.run(
        SkillRequest.create(
            {
                "query": "采购付款",
                "namespace": "tenant-a",
                "top_k": 1,
                "exclude_document_ids": ["doc-ignored"],
                "channels": ["path", "content"],
            },
            skill_name="knowledge-retrieval",
        )
    )

    assert result.status == "success"
    assert result.output["namespace"] == "tenant-a"
    assert result.output["referenced_chunks"][0]["chunk_id"] == "chunk_1"
    assert "付款" in result.output["evidence_text"]


@pytest.mark.asyncio
async def test_default_registry_reports_unconfigured_external_services() -> None:
    runtime = AgentRuntime(build_default_registry())

    profile = await runtime.run(
        SkillRequest.create(
            {"file_id": "file_1", "job_id": "job_1"},
            skill_name="document-profile",
        )
    )
    preprocess = await runtime.run(
        SkillRequest.create(
            {"file_id": "file_1", "business_scene": "tender_parse"},
            skill_name="document-preprocess",
        )
    )

    assert profile.status == "partial"
    assert preprocess.status == "blocked"
    assert preprocess.steps[0].result.error_code == "PREPROCESS_BACKEND_NOT_CONFIGURED"
