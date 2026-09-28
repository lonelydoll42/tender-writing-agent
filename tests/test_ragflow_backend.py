from __future__ import annotations

import json

import httpx
import pytest

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.core.registry import SkillRegistry
from qiaowenshu_agent.core.runtime import AgentRuntime
from qiaowenshu_agent.skills.knowledge_retrieval.ragflow_backend import (
    RagFlowConfig,
    RagFlowRetrievalBackend,
)
from qiaowenshu_agent.skills.knowledge_retrieval.skill import KnowledgeRetrievalSkill


def make_context() -> SkillContext:
    return SkillContext(
        run_id="run_test",
        request=SkillRequest.create(
            {},
            tenant_id="tenant-a",
            metadata={"enterprise_id": "enterprise-a"},
        ),
    )


@pytest.mark.asyncio
async def test_ragflow_backend_posts_search_payload_and_normalizes_nested_docs(
) -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "code": 200,
                "data": {
                    "docs": [
                        {
                            "page_content": "付款条件应在验收合格后执行。",
                            "score": 0.91,
                            "metadata": {
                                "id": "chunk-1",
                                "document_id": "doc-1",
                                "filename": "采购文件.docx",
                                "section_path": ["商务要求", "付款条件"],
                            },
                        }
                    ]
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend = RagFlowRetrievalBackend(
        RagFlowConfig(
            base_url="http://ragflow.test",
            knowledge_base_name="tender-kb",
            api_key="test-token",
        ),
        client=client,
    )
    try:
        result = await backend.run(
            {
                "query": "采购付款",
                "namespace": "tenant-a",
                "top_k": 3,
                "threshold": 0.2,
                "retrieval_policy": "standard",
            },
            make_context(),
        )
    finally:
        await client.aclose()

    assert seen["url"] == "http://ragflow.test/knowledge_base/search_docs"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["query"] == "采购付款"
    assert body["knowledge_base_name"] == "tender-kb"
    assert body["top_k"] == 3
    assert body["score_threshold"] == 0.2

    headers = seen["headers"]
    assert isinstance(headers, dict)
    assert headers["authorization"] == "Bearer test-token"
    assert headers["x-tenant-id"] == "tenant-a"
    assert headers["x-enterprise-id"] == "enterprise-a"

    assert result["returned_count"] == 1
    assert result["referenced_chunks"] == [
        {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "section_path": ["商务要求", "付款条件"],
            "source": "采购文件.docx",
            "score": 0.91,
        }
    ]
    assert "付款条件应在验收合格后执行" in result["evidence_text"]


@pytest.mark.asyncio
async def test_business_rag_chat_style_uses_configured_knowledge_base_id() -> None:
    seen_body: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_body.update(json.loads(request.content))
        return httpx.Response(200, json={"sources": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend = RagFlowRetrievalBackend(
        RagFlowConfig(
            base_url="http://ragflow.test",
            endpoint="/knowledge_base/rag_chat",
            request_style="business_rag_chat",
            knowledge_base_id=42,
            scheme_id="scheme-1",
            user_id="user-1",
            model="deepseek-test",
        ),
        client=client,
    )
    try:
        await backend.run(
            {"query": "采购范围", "namespace": "ignored", "top_k": 5},
            make_context(),
        )
    finally:
        await client.aclose()

    assert seen_body == {
        "knowledge_base_id": 42,
        "content": "采购范围",
        "user_id": "user-1",
        "scheme_id": "scheme-1",
        "model": "deepseek-test",
    }


@pytest.mark.asyncio
async def test_official_ragflow_retrieval_posts_dataset_scope_and_chunks() -> None:
    seen_body: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_body.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "chunks": [
                        {
                            "id": "chunk-1",
                            "document_id": "doc-1",
                            "document_keyword": "投标文件.pdf",
                            "content": "投标人应提供完整的技术方案。",
                            "similarity": 0.88,
                        }
                    ],
                    "total": 1,
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend = RagFlowRetrievalBackend(
        RagFlowConfig(
            base_url="http://ragflow.test",
            endpoint="/api/v1/retrieval",
            request_style="ragflow_retrieval",
            dataset_ids=("dataset-1",),
            api_key="test-token",
        ),
        client=client,
    )
    try:
        result = await backend.run(
            {"query": "技术方案", "namespace": "tender", "top_k": 2},
            make_context(),
        )
    finally:
        await client.aclose()

    assert seen_body == {
        "question": "技术方案",
        "dataset_ids": ["dataset-1"],
        "document_ids": [],
        "page": 1,
        "page_size": 2,
        "similarity_threshold": 0.2,
        "vector_similarity_weight": 0.3,
        "top_k": 1024,
        "keyword": False,
        "highlight": False,
        "cross_languages": [],
        "metadata_condition": {},
        "use_kg": False,
        "toc_enhance": False,
    }
    assert result["referenced_chunks"][0] == {
        "chunk_id": "chunk-1",
        "document_id": "doc-1",
        "section_path": "",
        "source": "投标文件.pdf",
        "score": 0.88,
    }
    assert "技术方案" in result["evidence_text"]


@pytest.mark.asyncio
async def test_skill_maps_remote_auth_error_without_exposing_response_body() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"detail": "token=should-not-appear", "password": "secret"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend = RagFlowRetrievalBackend(
        RagFlowConfig(base_url="http://ragflow.test"),
        client=client,
    )
    registry = SkillRegistry()
    registry.register(KnowledgeRetrievalSkill(backend=backend))
    runtime = AgentRuntime(registry)
    try:
        result = await runtime.run(
            SkillRequest.create(
                {"query": "采购付款"},
                skill_name="knowledge-retrieval",
            )
        )
    finally:
        await client.aclose()

    assert result.status == "error"
    assert result.steps[0].result.error_code == "RETRIEVAL_AUTH_FAILED"
    assert "should-not-appear" not in result.steps[0].result.message
    assert "secret" not in result.steps[0].result.message


def test_ragflow_config_from_env_infers_business_style_for_rag_chat() -> None:
    config = RagFlowConfig.from_env(
        {
            "QIAOWENSHU_KB_BASE_URL": "http://ragflow.test",
            "QIAOWENSHU_KB_ENDPOINT": "/knowledge_base/rag_chat",
            "QIAOWENSHU_KB_ID": "42",
            "QIAOWENSHU_KB_API_KEY": "token",
        }
    )

    assert config is not None
    assert config.request_style == "business_rag_chat"
    assert config.knowledge_base_id == 42


def test_ragflow_config_from_env_infers_official_style_and_dataset_ids() -> None:
    config = RagFlowConfig.from_env(
        {
            "QIAOWENSHU_KB_BASE_URL": "http://ragflow.test",
            "QIAOWENSHU_KB_ENDPOINT": "/api/v1/retrieval",
            "QIAOWENSHU_KB_DATASET_IDS": "dataset-1, dataset-2",
        }
    )

    assert config is not None
    assert config.request_style == "ragflow_retrieval"
    assert config.dataset_ids == ("dataset-1", "dataset-2")


def test_ragflow_config_from_env_defaults_to_official_endpoint() -> None:
    config = RagFlowConfig.from_env(
        {"QIAOWENSHU_KB_BASE_URL": "http://ragflow.test"}
    )

    assert config is not None
    assert config.endpoint == "/api/v1/retrieval"
    assert config.request_style == "ragflow_retrieval"
