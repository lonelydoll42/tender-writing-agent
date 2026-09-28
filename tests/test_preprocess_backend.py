from __future__ import annotations

import json

import httpx
import pytest

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.skills.document_preprocess.skill import HttpPreprocessBackend


@pytest.mark.asyncio
async def test_preprocess_backend_adds_context_headers_and_unwraps_response() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "code": 200,
                "message": "OK",
                "data": {
                    "task_id": "task_1",
                    "preprocess_id": "prep_1",
                    "status": "QUEUED",
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    request = SkillRequest.create(
        {"file_id": "file_1", "business_scene": "tender_parse"},
        tenant_id="10001",
        user_id="42",
    )
    context = SkillContext(run_id="run_test", request=request)
    backend = HttpPreprocessBackend(
        "http://preprocess.test",
        headers={"X-Gateway-Secret": "configured-by-host"},
        client=client,
    )
    try:
        result = await backend.run(request.input, context)
    finally:
        await client.aclose()

    assert seen["url"] == "http://preprocess.test/api/documents/preprocess"
    headers = seen["headers"]
    assert isinstance(headers, dict)
    assert headers["x-tenant-id"] == "10001"
    assert headers["x-user-id"] == "42"
    assert headers["x-request-id"] == request.request_id
    assert headers["x-gateway-secret"] == "configured-by-host"
    assert seen["body"] == request.input
    assert result == {
        "task_id": "task_1",
        "preprocess_id": "prep_1",
        "status": "QUEUED",
    }


@pytest.mark.asyncio
async def test_preprocess_backend_context_identity_overrides_static_header() -> None:
    seen_headers: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json={"status": "QUEUED"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend = HttpPreprocessBackend(
        "http://preprocess.test",
        headers={"x-tenant-id": "host-tenant"},
        client=client,
    )
    context = SkillContext(
        run_id="run_test",
        request=SkillRequest.create({}, tenant_id="request-tenant"),
    )
    try:
        await backend.run({}, context)
    finally:
        await client.aclose()

    assert seen_headers["x-tenant-id"] == "request-tenant"


@pytest.mark.asyncio
async def test_preprocess_backend_preserves_bid_rejection_scene_contract() -> None:
    seen_body: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_body.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "code": 200,
                "message": "OK",
                "data": {
                    "preprocess_id": "prep-bid-1",
                    "parse_ready_file_id": "file-parse-ready-1",
                    "status": "QUEUED",
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    request = SkillRequest.create(
        {
            "file_id": "bid-file-1",
            "business_scene": "bid_rejection_check",
            "file_role": "bid_file",
        },
        tenant_id="10001",
    )
    context = SkillContext(run_id="run_bid_rejection", request=request)
    backend = HttpPreprocessBackend("http://preprocess.test", client=client)
    try:
        result = await backend.run(request.input, context)
    finally:
        await client.aclose()

    assert seen_body == request.input
    assert result["parse_ready_file_id"] == "file-parse-ready-1"
