"""Typed request model for retrieval policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class KnowledgeRetrievalInput:
    query: str
    namespace: str = "default"
    knowledge_base_name: str | None = None
    knowledge_base_id: str | int | None = None
    dataset_ids: list[str] = field(default_factory=list)
    document_ids: list[str] = field(default_factory=list)
    top_k: int = 10
    exclude_document_ids: list[str] = field(default_factory=list)
    exclude_sections: list[dict[str, str]] = field(default_factory=list)
    data_type: int = 1
    signal_paths: list[str] = field(default_factory=list)
    filter_mode: str = "delete"
    channels: list[str] = field(default_factory=list)
    channel_weights: dict[str, float] = field(default_factory=dict)
    internal_recall_k: int | None = None
    rerank: bool = False
    threshold: float = 0.0
    retrieval_policy: str = "standard"
    file_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    model: str | None = None
    scheme_id: str | None = None
    user_id: str | None = None
    similarity_threshold: float | None = None
    vector_similarity_weight: float = 0.3
    rerank_id: str | None = None
    keyword: bool | None = None
    highlight: bool = False
    cross_languages: list[str] = field(default_factory=list)
    metadata_condition: dict[str, Any] = field(default_factory=dict)
    page: int = 1
    page_size: int | None = None
    use_kg: bool = False
    toc_enhance: bool = False

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "KnowledgeRetrievalInput":
        query = str(data.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        top_k = int(data.get("top_k", 10))
        if not 1 <= top_k <= 100:
            raise ValueError("top_k must be between 1 and 100")
        filter_mode = str(data.get("filter_mode") or "delete")
        if filter_mode not in {"delete", "keep"}:
            raise ValueError("filter_mode must be delete or keep")
        return cls(
            query=query,
            namespace=str(data.get("namespace") or "default"),
            knowledge_base_name=(
                str(data["knowledge_base_name"]).strip()
                if data.get("knowledge_base_name")
                else None
            ),
            knowledge_base_id=data.get("knowledge_base_id"),
            dataset_ids=[
                str(item) for item in data.get("dataset_ids") or []
            ],
            document_ids=[
                str(item) for item in data.get("document_ids") or []
            ],
            top_k=top_k,
            exclude_document_ids=[
                str(item) for item in data.get("exclude_document_ids") or []
            ],
            exclude_sections=[
                dict(item) for item in data.get("exclude_sections") or []
            ],
            data_type=int(data.get("data_type", 1)),
            signal_paths=[str(item) for item in data.get("signal_paths") or []],
            filter_mode=filter_mode,
            channels=[str(item) for item in data.get("channels") or []],
            channel_weights={
                str(key): float(value)
                for key, value in dict(data.get("channel_weights") or {}).items()
            },
            internal_recall_k=(
                int(data["internal_recall_k"])
                if data.get("internal_recall_k") is not None
                else None
            ),
            rerank=bool(data.get("rerank", False)),
            threshold=float(
                data.get("threshold", data.get("score_threshold", 0.0))
            ),
            retrieval_policy=str(data.get("retrieval_policy") or "standard"),
            file_name=str(data.get("file_name") or ""),
            metadata=dict(data.get("metadata") or {}),
            model=(str(data["model"]).strip() if data.get("model") else None),
            scheme_id=(
                str(data["scheme_id"]).strip()
                if data.get("scheme_id")
                else None
            ),
            user_id=(
                str(data["user_id"]).strip() if data.get("user_id") else None
            ),
            similarity_threshold=(
                float(data["similarity_threshold"])
                if data.get("similarity_threshold") is not None
                else None
            ),
            vector_similarity_weight=float(
                data.get("vector_similarity_weight", 0.3)
            ),
            rerank_id=(
                str(data["rerank_id"]).strip()
                if data.get("rerank_id")
                else None
            ),
            keyword=(
                bool(data["keyword"])
                if data.get("keyword") is not None
                else None
            ),
            highlight=bool(data.get("highlight", False)),
            cross_languages=[
                str(item) for item in data.get("cross_languages") or []
            ],
            metadata_condition=dict(data.get("metadata_condition") or {}),
            page=max(int(data.get("page", 1)), 1),
            page_size=(
                max(int(data["page_size"]), 1)
                if data.get("page_size") is not None
                else None
            ),
            use_kg=bool(data.get("use_kg", False)),
            toc_enhance=bool(data.get("toc_enhance", False)),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "namespace": self.namespace,
            "knowledge_base_name": self.knowledge_base_name,
            "knowledge_base_id": self.knowledge_base_id,
            "dataset_ids": list(self.dataset_ids),
            "document_ids": list(self.document_ids),
            "top_k": self.top_k,
            "exclude_document_ids": list(self.exclude_document_ids),
            "exclude_sections": list(self.exclude_sections),
            "data_type": self.data_type,
            "signal_paths": list(self.signal_paths),
            "filter_mode": self.filter_mode,
            "channels": list(self.channels),
            "channel_weights": dict(self.channel_weights),
            "internal_recall_k": self.internal_recall_k,
            "rerank": self.rerank,
            "threshold": self.threshold,
            "retrieval_policy": self.retrieval_policy,
            "file_name": self.file_name,
            "metadata": dict(self.metadata),
            "model": self.model,
            "scheme_id": self.scheme_id,
            "user_id": self.user_id,
            "similarity_threshold": self.similarity_threshold,
            "vector_similarity_weight": self.vector_similarity_weight,
            "rerank_id": self.rerank_id,
            "keyword": self.keyword,
            "highlight": self.highlight,
            "cross_languages": list(self.cross_languages),
            "metadata_condition": dict(self.metadata_condition),
            "page": self.page,
            "page_size": self.page_size,
            "use_kg": self.use_kg,
            "toc_enhance": self.toc_enhance,
        }
