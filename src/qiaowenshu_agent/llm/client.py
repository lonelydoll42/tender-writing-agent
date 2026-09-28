"""Small async client for OpenAI-compatible Qwen chat completions."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import httpx

from qiaowenshu_agent.llm.config import QwenConfig


class LLMError(RuntimeError):
    """Base error with a stable error code for Skill results."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable


class LLMRemoteError(LLMError):
    """Sanitized transport or remote API error."""


class LLMResponseError(LLMError):
    """The provider returned a response that did not match the contract."""


@dataclass(frozen=True)
class LLMCompletion:
    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str | None = None


class OpenAICompatibleQwenClient:
    """Call Qwen through the standard ``/chat/completions`` contract."""

    def __init__(
        self,
        config: QwenConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self._client = client

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        dotenv_path: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> "OpenAICompatibleQwenClient | None":
        config = QwenConfig.from_env(environ, dotenv_path=dotenv_path)
        return cls(config, client=client) if config is not None else None

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        purpose: str = "default",
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: Mapping[str, Any] | None = None,
    ) -> LLMCompletion:
        selected_model = self.config.model_for(purpose, model)
        if not selected_model or selected_model == "rule":
            raise LLMError(
                "no generative model is configured for this purpose",
                error_code="LLM_MODEL_NOT_CONFIGURED",
            )
        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": [dict(message) for message in messages],
            "temperature": (
                self.config.temperature if temperature is None else temperature
            ),
            "max_tokens": max_tokens or self.config.max_tokens,
            "stream": False,
        }
        if response_format is not None:
            payload["response_format"] = dict(response_format)

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        last_error: LLMRemoteError | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = await self._post(payload, headers)
            except LLMRemoteError as exc:
                last_error = exc
                if not exc.retryable or attempt >= self.config.max_retries:
                    raise
                await asyncio.sleep(min(2**attempt, 4))
                continue
            return _parse_completion(response, fallback_model=selected_model)
        if last_error is not None:
            raise last_error
        raise LLMRemoteError(
            "LLM request failed",
            error_code="LLM_REMOTE_FAILED",
            retryable=True,
        )

    async def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        purpose: str = "default",
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[dict[str, Any], LLMCompletion]:
        completion = await self.complete(
            messages,
            purpose=purpose,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        parsed = parse_json_object(completion.content)
        if not isinstance(parsed, dict):
            raise LLMResponseError(
                "LLM JSON response must be an object",
                error_code="LLM_INVALID_JSON_RESPONSE",
            )
        return parsed, completion

    async def _post(
        self,
        payload: Mapping[str, Any],
        headers: Mapping[str, str],
    ) -> httpx.Response:
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        try:
            if self._client is not None:
                response = await self._client.post(
                    url,
                    json=dict(payload),
                    headers=dict(headers),
                    timeout=self.config.timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(
                    timeout=self.config.timeout_seconds
                ) as client:
                    response = await client.post(
                        url,
                        json=dict(payload),
                        headers=dict(headers),
                    )
        except httpx.TimeoutException as exc:
            raise LLMRemoteError(
                "LLM request timed out",
                error_code="LLM_REMOTE_TIMEOUT",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMRemoteError(
                "LLM request failed",
                error_code="LLM_REMOTE_UNAVAILABLE",
                retryable=True,
            ) from exc

        if not 200 <= response.status_code < 300:
            raise LLMRemoteError(
                f"LLM returned HTTP {response.status_code}",
                error_code=_http_error_code(response.status_code),
                retryable=(
                    response.status_code in {408, 425, 429}
                    or response.status_code >= 500
                ),
            )
        return response


def parse_json_object(content: str) -> dict[str, Any]:
    """Parse direct or fenced JSON without trusting surrounding prose."""

    text = str(content or "").strip()
    candidates = [text]
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip().startswith("```"):
            candidates.append("\n".join(lines[1:-1]).strip())
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise LLMResponseError(
        "LLM response is not valid JSON",
        error_code="LLM_INVALID_JSON_RESPONSE",
    )


def _parse_completion(
    response: httpx.Response,
    *,
    fallback_model: str,
) -> LLMCompletion:
    try:
        raw = response.json()
    except ValueError as exc:
        raise LLMResponseError(
            "LLM returned a non-JSON response",
            error_code="LLM_INVALID_RESPONSE",
        ) from exc
    if not isinstance(raw, Mapping):
        raise LLMResponseError(
            "LLM response must be an object",
            error_code="LLM_INVALID_RESPONSE",
        )
    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMResponseError(
            "LLM response has no choices",
            error_code="LLM_INVALID_RESPONSE",
        )
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise LLMResponseError(
            "LLM choice must be an object",
            error_code="LLM_INVALID_RESPONSE",
        )
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise LLMResponseError(
            "LLM choice has no message",
            error_code="LLM_INVALID_RESPONSE",
        )
    content = _message_content(message.get("content"))
    if not content:
        raise LLMResponseError(
            "LLM message content is empty",
            error_code="LLM_EMPTY_RESPONSE",
        )
    return LLMCompletion(
        content=content,
        model=str(raw.get("model") or fallback_model),
        usage=_normalize_usage(raw.get("usage")),
        finish_reason=(
            str(choice.get("finish_reason"))
            if choice.get("finish_reason") is not None
            else None
        ),
    )


def _message_content(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, Mapping) and item.get("type") == "text":
                text = str(item.get("text") or "").strip()
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()
    return ""


def _normalize_usage(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    usage: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        raw = value.get(key)
        if raw is None:
            continue
        try:
            usage[key] = max(int(raw), 0)
        except (TypeError, ValueError):
            continue
    return usage


def _http_error_code(status_code: int) -> str:
    if status_code == 401 or status_code == 403:
        return "LLM_AUTH_FAILED"
    if status_code == 429:
        return "LLM_RATE_LIMITED"
    if status_code >= 500:
        return "LLM_REMOTE_SERVER_ERROR"
    return "LLM_REMOTE_REJECTED"
