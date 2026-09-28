"""Skill facade for the standalone document preprocessing service."""

from __future__ import annotations

import inspect
from typing import Any, Mapping, Protocol

import httpx

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import (
    Skill,
    SkillManifest,
    SkillRequest,
    SkillResult,
)
from qiaowenshu_agent.skills.document_preprocess.models import DocumentPreprocessInput


class DocumentPreprocessBackend(Protocol):
    def run(
        self,
        payload: Mapping[str, Any],
        context: SkillContext,
    ) -> Mapping[str, Any] | Any: ...


MANIFEST = SkillManifest(
    name="document-preprocess",
    version="0.1.0",
    description="Normalize files and create parse-ready document artifacts.",
    input_schema={
        "type": "object",
        "required": ["file_id", "business_scene"],
        "properties": {
            "file_id": {"type": "string"},
            "business_scene": {"type": "string"},
            "file_role": {"type": ["string", "null"]},
            "options": {"type": "object"},
            "force": {"type": "boolean"},
        },
    },
    output_schema={
        "type": "object",
        "required": ["preprocess_id", "status"],
    },
    capabilities=(
        "document.normalize",
        "document.ocr",
        "document.artifact",
        "bid.rejection.preprocess",
    ),
    required_permissions=("document.read", "document.write"),
)


class DocumentPreprocessSkill(Skill):
    manifest = MANIFEST

    def __init__(self, *, backend: DocumentPreprocessBackend | None = None) -> None:
        self.backend = backend

    async def execute(
        self,
        request: SkillRequest,
        context: SkillContext,
    ) -> SkillResult:
        try:
            preprocess_input = DocumentPreprocessInput.from_mapping(request.input)
        except (TypeError, ValueError) as exc:
            return SkillResult.failure(
                message=str(exc),
                error_code="INVALID_PREPROCESS_INPUT",
            )
        if self.backend is None:
            return SkillResult.blocked(
                message="document preprocessing backend is not configured",
                error_code="PREPROCESS_BACKEND_NOT_CONFIGURED",
            )
        try:
            raw = self.backend.run(preprocess_input.to_payload(), context)
            if inspect.isawaitable(raw):
                raw = await raw
            if isinstance(raw, Mapping) and raw.get("status") == "blocked":
                return SkillResult.blocked(
                    message=str(
                        raw.get("message") or "document preprocessing is blocked"
                    ),
                    error_code=str(raw.get("error_code") or "PREPROCESS_BLOCKED"),
                )
            if hasattr(raw, "to_dict"):
                raw = raw.to_dict()
            if not isinstance(raw, Mapping):
                raw = {"value": raw}
            return SkillResult.success(
                dict(raw),
                message="document preprocessing completed",
            )
        except Exception as exc:
            return SkillResult.failure(
                message=f"document preprocessing backend failed: {exc}",
                error_code="PREPROCESS_BACKEND_FAILED",
                retryable=True,
            )


class HttpPreprocessBackend:
    """HTTP adapter for document-preprocess-service.

    The backend intentionally knows only the service contract. Tenant and user
    headers are supplied by the host application instead of being hard-coded.
    """

    def __init__(
        self,
        base_url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = dict(headers or {})
        self.timeout = timeout
        self._client = client

    async def run(
        self,
        payload: Mapping[str, Any],
        context: SkillContext,
    ) -> dict[str, Any]:
        headers = self._build_headers(context)
        if self._client is not None:
            response = await self._client.post(
                f"{self.base_url}/api/documents/preprocess",
                headers=headers,
                json=dict(payload),
                timeout=self.timeout,
            )
        else:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/documents/preprocess",
                    headers=headers,
                    json=dict(payload),
                )
        response.raise_for_status()
        body = response.json()
        if isinstance(body, Mapping) and isinstance(body.get("data"), Mapping):
            return dict(body["data"])
        if not isinstance(body, Mapping):
            raise ValueError("preprocess service returned a non-object response")
        return dict(body)

    def _build_headers(self, context: SkillContext) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **self.headers,
        }
        if context.request.tenant_id:
            _set_header(headers, "X-Tenant-Id", context.request.tenant_id)
        if context.request.user_id:
            _set_header(headers, "X-User-Id", context.request.user_id)
        _set_header(headers, "X-Request-Id", context.request.request_id)
        return headers


def _set_header(headers: dict[str, str], name: str, value: str) -> None:
    for key in list(headers):
        if key.lower() == name.lower():
            del headers[key]
    headers[name] = value
