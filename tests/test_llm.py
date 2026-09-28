from __future__ import annotations

import json

import httpx
import pytest

from qiaowenshu_agent.llm import OpenAICompatibleQwenClient, QwenConfig


def test_qwen_config_routes_models_by_skill_purpose() -> None:
    config = QwenConfig.from_env(
        {
            "QIAOWENSHU_LLM_API_BASE_URL": "https://llm.test/api/v1",
            "QIAOWENSHU_LLM_API_KEY": "secret",
            "QIAOWENSHU_LLM_MODEL_DOCUMENT_WRITING": "qwen-plus",
            "QIAOWENSHU_LLM_MODEL_ROUTES": '{"custom_purpose": "qwen-turbo"}',
        }
    )

    assert config is not None
    assert config.model_for("document-writing") == "qwen-plus"
    assert config.model_for("scoring_strategy") == "qwen3.8-max"
    assert config.model_for("custom-purpose") == "qwen-turbo"
    assert config.public_dict()["api_key_configured"] is True
    assert "secret" not in str(config.public_dict())


@pytest.mark.asyncio
async def test_qwen_client_calls_chat_completions_with_selected_model() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "qwen-max",
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    config = QwenConfig(
        base_url="https://llm.test/api/v1",
        api_key="secret",
        model_routes={"document_writing": "qwen-max"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenAICompatibleQwenClient(config, client=client)
        data, completion = await adapter.complete_json(
            [{"role": "user", "content": "write"}],
            purpose="document-writing",
        )

    assert data == {"ok": True}
    assert completion.usage == {"prompt_tokens": 10, "completion_tokens": 5}
    assert seen["url"] == "https://llm.test/api/v1/chat/completions"
    assert seen["authorization"] == "Bearer secret"
    assert seen["body"]["model"] == "qwen-max"  # type: ignore[index]
    assert seen["body"]["response_format"] == {"type": "json_object"}  # type: ignore[index]
