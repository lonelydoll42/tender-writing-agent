"""Skill facade for the reference agentic retrieval workflow."""

from __future__ import annotations

import inspect
import re
from typing import Any, Mapping, Protocol

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import (
    Skill,
    SkillManifest,
    SkillRequest,
    SkillResult,
)
from qiaowenshu_agent.skills.knowledge_retrieval.models import KnowledgeRetrievalInput
from qiaowenshu_agent.skills.knowledge_retrieval.ragflow_backend import (
    RagFlowConfigurationError,
    RagFlowHTTPError,
)


class KnowledgeRetrievalBackend(Protocol):
    def run(
        self,
        payload: Mapping[str, Any],
        context: SkillContext,
    ) -> Mapping[str, Any] | Any:
        ...


MANIFEST = SkillManifest(
    name="knowledge-retrieval",
    version="0.1.0",
    description="Retrieve scoped evidence through the knowledge base workflow.",
    input_schema={
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string"},
            "namespace": {"type": "string"},
            "knowledge_base_name": {"type": "string"},
            "knowledge_base_id": {"type": ["string", "integer"]},
            "dataset_ids": {"type": "array", "items": {"type": "string"}},
            "document_ids": {"type": "array", "items": {"type": "string"}},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 100},
            "threshold": {"type": "number"},
            "similarity_threshold": {"type": "number"},
            "vector_similarity_weight": {"type": "number"},
            "rerank_id": {"type": "string"},
            "retrieval_policy": {"type": "string"},
            "file_name": {"type": "string"},
            "channels": {"type": "array", "items": {"type": "string"}},
        },
    },
    output_schema={
        "type": "object",
        "required": ["evidence_text", "referenced_chunks"],
    },
    capabilities=("retrieval.evidence", "retrieval.trace"),
    required_permissions=("knowledge.read",),
)


class KnowledgeRetrievalSkill(Skill):
    manifest = MANIFEST

    def __init__(self, *, backend: KnowledgeRetrievalBackend | None = None) -> None:
        self.backend = backend

    async def execute(
        self,
        request: SkillRequest,
        context: SkillContext,
    ) -> SkillResult:
        try:
            retrieval_input = KnowledgeRetrievalInput.from_mapping(request.input)
        except (TypeError, ValueError) as exc:
            return SkillResult.failure(
                message=str(exc),
                error_code="INVALID_RETRIEVAL_INPUT",
            )
        if self.backend is None:
            return SkillResult.blocked(
                message="knowledge retrieval backend is not configured",
                error_code="RETRIEVAL_BACKEND_NOT_CONFIGURED",
            )
        try:
            raw = self.backend.run(retrieval_input.to_payload(), context)
            if inspect.isawaitable(raw):
                raw = await raw
            if hasattr(raw, "to_api_response"):
                raw = raw.to_api_response()
            elif hasattr(raw, "to_dict"):
                raw = raw.to_dict()
            if not isinstance(raw, Mapping):
                raw = {"value": raw}
            data = dict(raw)
            data.setdefault("evidence_text", "")
            data.setdefault("referenced_chunks", [])
            return SkillResult.success(data, message="knowledge retrieval completed")
        except RagFlowConfigurationError as exc:
            return SkillResult.blocked(
                message=str(exc),
                error_code=exc.error_code,
            )
        except RagFlowHTTPError as exc:
            return SkillResult.failure(
                message=str(exc),
                error_code=exc.error_code,
                retryable=exc.retryable,
            )
        except Exception as exc:
            return SkillResult.failure(
                message=f"knowledge retrieval backend failed: {exc}",
                error_code="RETRIEVAL_BACKEND_FAILED",
                retryable=True,
            )


class InMemoryRetrievalBackend:
    """Small deterministic backend for local development and contract tests."""

    def __init__(self, documents: list[Mapping[str, Any]] | None = None) -> None:
        self.documents = [dict(document) for document in documents or []]

    def run(
        self,
        payload: Mapping[str, Any],
        _context: SkillContext,
    ) -> dict[str, Any]:
        query = str(payload["query"])
        raw_terms = re.findall(r"[A-Za-z0-9_]+|.", query.lower(), flags=re.DOTALL)
        terms = [
            term
            for term in raw_terms
            if term.strip() and (term.isalnum() or term == "_")
        ]
        excluded = {str(item) for item in payload.get("exclude_document_ids") or []}
        scored: list[tuple[float, dict[str, Any]]] = []
        for document in self.documents:
            document_id = str(document.get("document_id") or document.get("id") or "")
            if document_id in excluded:
                continue
            content = str(document.get("content") or "")
            path = str(document.get("path") or document.get("section_path") or "")
            haystack = f"{path}\n{content}".lower()
            score = sum(haystack.count(term) for term in terms)
            if score <= 0:
                continue
            row = dict(document)
            row.setdefault("document_id", document_id)
            row.setdefault("chunk_id", row.get("id") or f"chunk_{len(scored) + 1}")
            row["score"] = float(score)
            scored.append((float(score), row))
        scored.sort(key=lambda item: (-item[0], str(item[1].get("chunk_id"))))
        rows = [row for _, row in scored[: int(payload.get("top_k") or 10)]]
        evidence = "\n\n".join(
            f"[{row.get('path', '')}]\n{row.get('content', '')}" for row in rows
        )
        references = [
            {
                "chunk_id": row.get("chunk_id"),
                "document_id": row.get("document_id"),
                "section_path": row.get("path") or row.get("section_path", ""),
                "score": row.get("score", 0.0),
            }
            for row in rows
        ]
        return {
            "namespace": payload.get("namespace", "default"),
            "query": query,
            "evidence_text": evidence,
            "referenced_chunks": references,
            "results": rows,
            "router_used": "in_memory",
            "stop_reason": "evidence_only",
        }
