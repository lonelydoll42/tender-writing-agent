"""HTTP adapter for the deployment-specific knowledge-base service.

The deployment document lists RAGFlow-compatible knowledge-base endpoints but
does not include a stable request/response example.  This adapter keeps the
endpoint, request style, authentication, and knowledge-base identity
configurable, while presenting one evidence-only backend contract to the
Skill.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

import httpx

from qiaowenshu_agent.core.context import SkillContext


RequestStyle = Literal[
    "ragflow_retrieval",
    "search_docs",
    "rag_chat",
    "business_rag_chat",
]


class RagFlowConfigurationError(ValueError):
    """Raised when the HTTP backend configuration cannot be used."""

    error_code = "RETRIEVAL_BACKEND_CONFIGURATION_INVALID"
    retryable = False


class RagFlowHTTPError(RuntimeError):
    """A sanitized remote HTTP/application error.

    The response body is deliberately not included in the exception message;
    remote bodies may contain sensitive prompts, document text, or credentials.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str = "RETRIEVAL_REMOTE_FAILED",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.retryable = retryable


@dataclass(frozen=True)
class RagFlowConfig:
    """Runtime configuration for one RAGFlow/knowledge-base deployment."""

    base_url: str
    endpoint: str = "/knowledge_base/search_docs"
    request_style: RequestStyle = "search_docs"
    api_key: str | None = field(default=None, repr=False)
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"
    knowledge_base_name: str | None = None
    knowledge_base_id: str | int | None = None
    dataset_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    model: str | None = None
    scheme_id: str | None = None
    user_id: str | None = None
    rerank_id: str | None = None
    timeout_seconds: float = 60.0
    tenant_header: str = "X-Tenant-Id"
    enterprise_header: str = "X-Enterprise-Id"
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    extra_payload: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise RagFlowConfigurationError("knowledge base base_url is required")
        if not self.endpoint.strip():
            raise RagFlowConfigurationError("knowledge base endpoint is required")
        if self.request_style not in {
            "ragflow_retrieval",
            "search_docs",
            "rag_chat",
            "business_rag_chat",
        }:
            raise RagFlowConfigurationError(
                f"unsupported knowledge base request_style: {self.request_style}"
            )
        if self.timeout_seconds <= 0:
            raise RagFlowConfigurationError(
                "knowledge base timeout_seconds must be positive"
            )

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "RagFlowConfig | None":
        """Load configuration without ever requiring credentials at import time."""

        env = environ if environ is not None else os.environ
        base_url = _first_env(
            env,
            "QIAOWENSHU_KB_BASE_URL",
            "RAGFLOW_BASE_URL",
        )
        if not base_url:
            return None

        endpoint = _first_env(
            env,
            "QIAOWENSHU_KB_ENDPOINT",
            "RAGFLOW_RETRIEVAL_ENDPOINT",
        ) or "/api/v1/retrieval"
        configured_style = _first_env(
            env,
            "QIAOWENSHU_KB_REQUEST_STYLE",
            "RAGFLOW_REQUEST_STYLE",
        )
        request_style = configured_style or _style_from_endpoint(endpoint)
        if request_style not in {
            "ragflow_retrieval",
            "search_docs",
            "rag_chat",
            "business_rag_chat",
        }:
            raise RagFlowConfigurationError(
                "QIAOWENSHU_KB_REQUEST_STYLE must be search_docs, rag_chat, "
                "ragflow_retrieval, or business_rag_chat"
            )

        return cls(
            base_url=base_url,
            endpoint=endpoint,
            request_style=request_style,  # type: ignore[arg-type]
            api_key=_first_env(
                env,
                "QIAOWENSHU_KB_API_KEY",
                "RAGFLOW_API_KEY",
            ),
            auth_header=_first_env(
                env,
                "QIAOWENSHU_KB_AUTH_HEADER",
                "RAGFLOW_AUTH_HEADER",
            )
            or "Authorization",
            auth_scheme=_first_env(
                env,
                "QIAOWENSHU_KB_AUTH_SCHEME",
                "RAGFLOW_AUTH_SCHEME",
            )
            or "Bearer",
            knowledge_base_name=_first_env(
                env,
                "QIAOWENSHU_KB_NAME",
                "RAGFLOW_KNOWLEDGE_BASE_NAME",
            ),
            knowledge_base_id=_parse_identifier(
                _first_env(
                    env,
                    "QIAOWENSHU_KB_ID",
                    "RAGFLOW_KNOWLEDGE_BASE_ID",
                )
            ),
            dataset_ids=_parse_csv_tuple(
                _first_env(
                    env,
                    "QIAOWENSHU_KB_DATASET_IDS",
                    "RAGFLOW_DATASET_IDS",
                )
            ),
            document_ids=_parse_csv_tuple(
                _first_env(
                    env,
                    "QIAOWENSHU_KB_DOCUMENT_IDS",
                    "RAGFLOW_DOCUMENT_IDS",
                )
            ),
            model=_first_env(env, "QIAOWENSHU_KB_MODEL", "RAGFLOW_MODEL"),
            scheme_id=_first_env(
                env,
                "QIAOWENSHU_KB_SCHEME_ID",
                "RAGFLOW_SCHEME_ID",
            ),
            user_id=_first_env(
                env,
                "QIAOWENSHU_KB_USER_ID",
                "RAGFLOW_USER_ID",
            ),
            rerank_id=_first_env(
                env,
                "QIAOWENSHU_KB_RERANK_ID",
                "RAGFLOW_RERANK_ID",
            ),
            timeout_seconds=_parse_float(
                _first_env(
                    env,
                    "QIAOWENSHU_KB_TIMEOUT_SECONDS",
                    "RAGFLOW_TIMEOUT_SECONDS",
                ),
                default=60.0,
            ),
            tenant_header=_first_env(
                env,
                "QIAOWENSHU_KB_TENANT_HEADER",
            )
            or "X-Tenant-Id",
            enterprise_header=_first_env(
                env,
                "QIAOWENSHU_KB_ENTERPRISE_HEADER",
            )
            or "X-Enterprise-Id",
        )


class RagFlowRetrievalBackend:
    """Call a configured knowledge-base endpoint and project evidence rows.

    ``ragflow_retrieval`` matches the official ``/api/v1/retrieval`` contract.
    ``search_docs`` matches the reference service contract. ``rag_chat``
    matches the legacy ``/chat/kb_chat`` shape, and ``business_rag_chat``
    matches the business wrapper shape documented in the reference scripts.
    Chat modes are compatibility modes only; the returned answer is never used
    as evidence.
    """

    def __init__(
        self,
        config: RagFlowConfig,
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
        client: httpx.AsyncClient | None = None,
    ) -> "RagFlowRetrievalBackend | None":
        config = RagFlowConfig.from_env(environ)
        return cls(config, client=client) if config is not None else None

    async def run(
        self,
        payload: Mapping[str, Any],
        context: SkillContext,
    ) -> dict[str, Any]:
        body = self.build_request_payload(payload)
        headers = self.build_headers(context)
        url = self._request_url()

        try:
            if self._client is not None:
                response = await self._client.post(
                    url,
                    json=body,
                    headers=headers,
                    timeout=self.config.timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(
                    timeout=self.config.timeout_seconds
                ) as client:
                    response = await client.post(url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise RagFlowHTTPError(
                "knowledge base request timed out",
                error_code="RETRIEVAL_REMOTE_TIMEOUT",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise RagFlowHTTPError(
                "knowledge base request failed",
                error_code="RETRIEVAL_REMOTE_UNAVAILABLE",
                retryable=True,
            ) from exc

        if not 200 <= response.status_code < 300:
            raise RagFlowHTTPError(
                f"knowledge base returned HTTP {response.status_code}",
                status_code=response.status_code,
                error_code=_http_error_code(response.status_code),
                retryable=(
                    response.status_code in {408, 425, 429}
                    or response.status_code >= 500
                ),
            )

        try:
            raw = response.json()
        except ValueError as exc:
            raise RagFlowHTTPError(
                "knowledge base returned a non-JSON response",
                status_code=response.status_code,
                error_code="RETRIEVAL_INVALID_RESPONSE",
                retryable=False,
            ) from exc

        _raise_for_application_error(raw)
        return normalize_retrieval_response(
            raw,
            request_payload=payload,
            endpoint=self.config.endpoint,
        )

    def build_headers(self, context: SkillContext) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **dict(self.config.headers),
        }
        if self.config.api_key:
            value = self.config.api_key
            if self.config.auth_scheme:
                value = f"{self.config.auth_scheme} {value}"
            headers[self.config.auth_header] = value
        if context.request.tenant_id and self.config.tenant_header:
            headers[self.config.tenant_header] = context.request.tenant_id
        enterprise_id = context.request.metadata.get("enterprise_id")
        if enterprise_id and self.config.enterprise_header:
            headers[self.config.enterprise_header] = str(enterprise_id)
        return headers

    def build_request_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query") or "")
        top_k = int(payload.get("top_k") or 10)
        threshold = float(payload.get("threshold") or 0.0)
        kb_name = str(
            payload.get("knowledge_base_name")
            or self.config.knowledge_base_name
            or payload.get("namespace")
            or "default"
        )
        kb_id = payload.get("knowledge_base_id") or self.config.knowledge_base_id

        if self.config.request_style == "ragflow_retrieval":
            body = self._build_ragflow_retrieval_payload(
                payload,
                query=query,
                top_k=top_k,
            )
        elif self.config.request_style == "search_docs":
            body: dict[str, Any] = {
                "query": query,
                "knowledge_base_name": kb_name,
                "top_k": top_k,
                "score_threshold": threshold,
                "file_name": str(payload.get("file_name") or ""),
                "metadata": dict(payload.get("metadata") or {}),
                "retrieval_policy": str(
                    payload.get("retrieval_policy") or "standard"
                ),
            }
            if kb_id is not None:
                body["knowledge_base_id"] = kb_id
        elif self.config.request_style == "rag_chat":
            body = {
                "query": query,
                "mode": "local_kb",
                "kb_name": kb_name,
                "top_k": top_k,
                "score_threshold": threshold,
                "history": list(payload.get("history") or []),
                "stream": False,
                "return_direct": bool(payload.get("return_direct", False)),
            }
            model = str(payload.get("model") or self.config.model or "").strip()
            if model:
                body["model"] = model
        else:
            body = {
                "knowledge_base_id": kb_id if kb_id is not None else kb_name,
                "content": query,
            }
            user_id = str(
                payload.get("user_id") or self.config.user_id or ""
            ).strip()
            scheme_id = str(
                payload.get("scheme_id") or self.config.scheme_id or ""
            ).strip()
            if user_id:
                body["user_id"] = user_id
            if scheme_id:
                body["scheme_id"] = scheme_id
            model = str(payload.get("model") or self.config.model or "").strip()
            if model:
                body["model"] = model

        body.update(dict(self.config.extra_payload))
        return body

    def _build_ragflow_retrieval_payload(
        self,
        payload: Mapping[str, Any],
        *,
        query: str,
        top_k: int,
    ) -> dict[str, Any]:
        dataset_ids = _string_list(
            payload.get("dataset_ids") or self.config.dataset_ids
        )
        document_ids = _string_list(
            payload.get("document_ids") or self.config.document_ids
        )
        if not dataset_ids and not document_ids:
            configured_id = payload.get("knowledge_base_id")
            if configured_id is None:
                configured_id = self.config.knowledge_base_id
            if configured_id is not None:
                dataset_ids = [str(configured_id)]
        if not dataset_ids and not document_ids:
            raise RagFlowConfigurationError(
                "official RAGFlow retrieval requires dataset_ids or document_ids"
            )

        similarity_threshold = payload.get("similarity_threshold")
        if similarity_threshold is None:
            similarity_threshold = 0.2
        body: dict[str, Any] = {
            "question": query,
            "dataset_ids": dataset_ids,
            "document_ids": document_ids,
            "page": max(int(payload.get("page") or 1), 1),
            "page_size": max(int(payload.get("page_size") or top_k), 1),
            "similarity_threshold": float(similarity_threshold),
            "vector_similarity_weight": float(
                payload.get("vector_similarity_weight") or 0.3
            ),
            "top_k": max(int(payload.get("internal_recall_k") or 1024), 1),
            "keyword": bool(
                payload.get("keyword")
                if payload.get("keyword") is not None
                else "keyword" in (payload.get("channels") or [])
            ),
            "highlight": bool(payload.get("highlight", False)),
            "cross_languages": list(payload.get("cross_languages") or []),
            "metadata_condition": dict(
                payload.get("metadata_condition") or {}
            ),
            "use_kg": bool(payload.get("use_kg", False)),
            "toc_enhance": bool(payload.get("toc_enhance", False)),
        }
        rerank_id = str(
            payload.get("rerank_id") or self.config.rerank_id or ""
        ).strip()
        if rerank_id:
            body["rerank_id"] = rerank_id
        return body

    def _request_url(self) -> str:
        if self.config.endpoint.startswith(("http://", "https://")):
            return self.config.endpoint
        return f"{self.config.base_url.rstrip('/')}/{self.config.endpoint.lstrip('/')}"


def normalize_retrieval_response(
    raw: Any,
    *,
    request_payload: Mapping[str, Any],
    endpoint: str,
) -> dict[str, Any]:
    """Normalize common RAGFlow and legacy service response shapes."""

    candidates = _find_chunk_list(raw)
    top_k = int(request_payload.get("top_k") or 10)
    excluded = {
        str(item) for item in request_payload.get("exclude_document_ids") or []
    }
    rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            continue
        metadata = candidate.get("metadata")
        metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
        document_id = _first_value(
            candidate,
            metadata,
            ("document_id", "doc_id", "file_id", "documentId", "id"),
        )
        chunk_id = _first_value(
            candidate,
            metadata,
            ("chunk_id", "section_id", "segment_id", "chunkId", "id"),
        )
        source = _first_value(
            candidate,
            metadata,
            (
                "source",
                "file_name",
                "filename",
                "document_name",
                "document_keyword",
                "title",
            ),
        )
        content = _first_value(
            candidate,
            metadata,
            ("page_content", "content", "text", "chunk_content", "segment"),
        )
        section_path = _first_value(
            candidate,
            metadata,
            ("section_path", "heading_path", "path", "section", "heading"),
        )
        score = _first_value(
            candidate,
            metadata,
            ("score", "similarity", "relevance_score", "rerank_score"),
        )
        normalized_document_id = str(document_id) if document_id is not None else ""
        if normalized_document_id in excluded:
            continue
        row = dict(candidate)
        row.update(
            {
                "document_id": normalized_document_id,
                "chunk_id": (
                    str(chunk_id)
                    if chunk_id is not None
                    else f"chunk_{index + 1}"
                ),
                "source": str(source) if source is not None else "",
                "content": str(content) if content is not None else "",
                "section_path": section_path if section_path is not None else "",
                "score": _number_or_none(score),
                "metadata": metadata,
            }
        )
        rows.append(row)

    rows = rows[:top_k]
    references = [
        {
            "chunk_id": row["chunk_id"],
            "document_id": row["document_id"],
            "section_path": row["section_path"],
            "source": row["source"],
            "score": row["score"],
        }
        for row in rows
    ]
    evidence_parts = []
    for row in rows:
        content = row["content"].strip()
        if not content:
            continue
        label = row["source"] or _format_section_path(row["section_path"])
        evidence_parts.append(f"[{label}]\n{content}" if label else content)

    return {
        "namespace": request_payload.get("namespace", "default"),
        "query": request_payload.get("query", ""),
        "evidence_text": "\n\n".join(evidence_parts),
        "referenced_chunks": references,
        "results": rows,
        "raw_result_count": len(candidates),
        "returned_count": len(rows),
        "retrieval_policy": {
            key: request_payload.get(key)
            for key in (
                "exclude_document_ids",
                "exclude_sections",
                "data_type",
                "signal_paths",
                "filter_mode",
                "channels",
                "channel_weights",
                "internal_recall_k",
                "rerank",
                "threshold",
                "retrieval_policy",
            )
        },
        "router_used": "ragflow_http",
        "endpoint": endpoint,
        "stop_reason": "evidence_only" if rows else "no_evidence",
    }


def _find_chunk_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, Mapping):
        return []
    for key in (
        "docs",
        "sources",
        "references",
        "chunks",
        "records",
        "retrieval",
        "results",
    ):
        candidate = value.get(key)
        if isinstance(candidate, list):
            return candidate
    for key in ("data", "result", "response"):
        candidate = value.get(key)
        found = _find_chunk_list(candidate)
        if found:
            return found
    return []


def _first_value(
    row: Mapping[str, Any],
    metadata: Mapping[str, Any],
    keys: tuple[str, ...],
) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
        value = metadata.get(key)
        if value not in (None, ""):
            return value
    return None


def _format_section_path(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return " / ".join(str(item) for item in value if str(item).strip())
    return str(value or "")


def _number_or_none(value: Any) -> float | int | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _first_env(env: Mapping[str, str], *names: str) -> str | None:
    for name in names:
        value = env.get(name)
        if value is not None and value.strip():
            return value.strip()
    return None


def _parse_float(value: str | None, *, default: float) -> float:
    if not value:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise RagFlowConfigurationError(
            "knowledge base timeout must be a number"
        ) from exc


def _parse_identifier(value: str | None) -> str | int | None:
    if not value:
        return None
    return int(value) if value.isdigit() else value


def _parse_csv_tuple(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item) for item in value if str(item).strip()]


def _style_from_endpoint(endpoint: str) -> RequestStyle:
    lowered = endpoint.lower()
    if "/api/v1/retrieval" in lowered or lowered.endswith("/retrieval"):
        return "ragflow_retrieval"
    if "rag_chat" in lowered:
        return "business_rag_chat"
    if "/chat/" in lowered:
        return "rag_chat"
    return "search_docs"


def _http_error_code(status_code: int) -> str:
    if status_code in {401, 403}:
        return "RETRIEVAL_AUTH_FAILED"
    if status_code == 404:
        return "RETRIEVAL_ENDPOINT_NOT_FOUND"
    if status_code == 429:
        return "RETRIEVAL_RATE_LIMITED"
    if status_code >= 500:
        return "RETRIEVAL_REMOTE_SERVER_ERROR"
    return "RETRIEVAL_REMOTE_FAILED"


def _raise_for_application_error(raw: Any) -> None:
    if not isinstance(raw, Mapping):
        return
    if raw.get("success") is False:
        raise RagFlowHTTPError(
            "knowledge base rejected the retrieval request",
            error_code="RETRIEVAL_REMOTE_REJECTED",
            retryable=False,
        )
    code = raw.get("code")
    try:
        numeric_code = int(code)
    except (TypeError, ValueError):
        numeric_code = 0
    if numeric_code == 102 or numeric_code >= 400:
        error_code = (
            "RETRIEVAL_DATASET_SCOPE_REQUIRED"
            if numeric_code == 102
            else _http_error_code(numeric_code)
        )
        raise RagFlowHTTPError(
            "knowledge base rejected the retrieval request",
            status_code=numeric_code,
            error_code=error_code,
            retryable=numeric_code in {408, 425, 429} or numeric_code >= 500,
        )
