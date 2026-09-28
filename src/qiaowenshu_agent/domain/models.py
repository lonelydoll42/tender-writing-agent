"""Stable, persistence-independent models for the tender workflow."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping


RequirementCategory = Literal[
    "disqualification",
    "qualification",
    "compliance",
    "technical",
    "commercial",
    "scoring",
    "format",
    "evidence",
    "other",
]
RequirementStatus = Literal["pass", "fail", "unknown", "not_applicable"]
EvidenceMatchStatus = Literal[
    "matched",
    "partial",
    "missing",
    "invalid",
    "conflict",
    "human_review",
]

OCR_REVIEW_THRESHOLD = 0.66

_CATEGORY_ALIASES = {
    "废标": "disqualification",
    "一票否决": "disqualification",
    "资格": "qualification",
    "符合性": "compliance",
    "技术": "technical",
    "商务": "commercial",
    "评分": "scoring",
    "格式": "format",
    "证明": "evidence",
}


def _text(value: Any, default: str = "") -> str:
    return str(value).strip() if value is not None else default


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid integer value: {value}") from exc


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid numeric value: {value}") from exc


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if not isinstance(value, (list, tuple, set)):
        raise ValueError("expected a string or list of strings")
    return [_text(item) for item in value if _text(item)]


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return {str(key): item for key, item in value.items()}


def _reference_list(value: Any) -> list["SourceReference"]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise ValueError("source_references must be a list")
    return [SourceReference.from_mapping(item) for item in value]


def _category(value: Any) -> RequirementCategory:
    normalized = _text(value, "other").lower()
    normalized = _CATEGORY_ALIASES.get(normalized, normalized)
    if normalized not in {
        "disqualification",
        "qualification",
        "compliance",
        "technical",
        "commercial",
        "scoring",
        "format",
        "evidence",
        "other",
    }:
        return "other"
    return normalized  # type: ignore[return-value]


@dataclass(frozen=True)
class SourceReference:
    document_id: str
    page: int | None = None
    section: str = ""
    quote: str = ""
    locator: str = ""
    bbox: list[float] | None = None
    confidence: float | None = None
    extraction_method: str = ""
    source_version: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "SourceReference":
        document_id = _text(
            data.get("document_id")
            or data.get("file_id")
            or data.get("source_id")
        )
        if not document_id:
            raise ValueError("source reference document_id is required")
        raw_bbox = data.get("bbox", data.get("bounding_box"))
        bbox: list[float] | None = None
        if raw_bbox not in (None, ""):
            if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) != 4:
                raise ValueError("source reference bbox must contain four numbers")
            try:
                bbox = [float(value) for value in raw_bbox]
            except (TypeError, ValueError) as exc:
                raise ValueError("source reference bbox must contain numbers") from exc
        confidence = _optional_float(
            data.get("confidence", data.get("ocr_confidence"))
        )
        if confidence is not None:
            if confidence > 1 and confidence <= 100:
                confidence /= 100
            if not 0 <= confidence <= 1:
                raise ValueError("source reference confidence must be between 0 and 1")
        return cls(
            document_id=document_id,
            page=_optional_int(data.get("page", data.get("page_number"))),
            section=_text(data.get("section") or data.get("section_path")),
            quote=_text(data.get("quote") or data.get("content")),
            locator=_text(data.get("locator") or data.get("chunk_id")),
            bbox=bbox,
            confidence=confidence,
            extraction_method=_text(
                data.get("extraction_method") or data.get("method")
            ),
            source_version=_text(
                data.get("source_version") or data.get("file_version")
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TenderProfile:
    project_id: str
    project_name: str = ""
    tender_number: str = ""
    procurement_scope: str = ""
    key_dates: dict[str, str] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    source_references: list[SourceReference] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "TenderProfile":
        project_id = _text(data.get("project_id"))
        if not project_id:
            raise ValueError("project_id is required")
        raw_dates = _mapping(data.get("key_dates"), "key_dates")
        return cls(
            project_id=project_id,
            project_name=_text(data.get("project_name")),
            tender_number=_text(data.get("tender_number")),
            procurement_scope=_text(data.get("procurement_scope")),
            key_dates={str(key): _text(value) for key, value in raw_dates.items()},
            attributes=_mapping(data.get("attributes"), "attributes"),
            source_references=_reference_list(data.get("source_references")),
            warnings=_string_list(data.get("warnings")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TenderRequirement:
    requirement_id: str
    category: RequirementCategory
    title: str
    description: str
    mandatory: bool = False
    evidence_required: list[str] = field(default_factory=list)
    check_rule: dict[str, Any] = field(default_factory=dict)
    max_score: float | None = None
    response_guidance: str = ""
    source_references: list[SourceReference] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "TenderRequirement":
        requirement_id = _text(data.get("requirement_id") or data.get("id"))
        title = _text(data.get("title") or data.get("name"))
        description = _text(data.get("description") or data.get("requirement"))
        if not requirement_id:
            raise ValueError("requirement_id is required")
        if not title and not description:
            raise ValueError(f"requirement {requirement_id} needs title or description")
        if not title:
            title = description[:80]
        if not description:
            description = title
        raw_rule = data.get("check_rule") or data.get("rule")
        return cls(
            requirement_id=requirement_id,
            category=_category(data.get("category")),
            title=title,
            description=description,
            mandatory=bool(data.get("mandatory", data.get("required", False))),
            evidence_required=_string_list(
                data.get("evidence_required")
                or data.get("required_evidence")
                or data.get("required_materials")
            ),
            check_rule=_mapping(raw_rule, "check_rule"),
            max_score=_optional_float(
                data.get("max_score", data.get("score"))
            ),
            response_guidance=_text(data.get("response_guidance")),
            source_references=_reference_list(data.get("source_references")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScoringItem:
    item_id: str
    title: str
    max_score: float
    criteria: str = ""
    evidence_required: list[str] = field(default_factory=list)
    linked_requirement_ids: list[str] = field(default_factory=list)
    strategy: str = ""
    priority: str = "normal"
    source_references: list[SourceReference] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ScoringItem":
        item_id = _text(data.get("item_id") or data.get("id"))
        title = _text(data.get("title") or data.get("name"))
        if not item_id or not title:
            raise ValueError("scoring item requires item_id and title")
        max_score = _optional_float(data.get("max_score", data.get("score")))
        if max_score is None or max_score < 0:
            raise ValueError(f"scoring item {item_id} needs a non-negative max_score")
        return cls(
            item_id=item_id,
            title=title,
            max_score=max_score,
            criteria=_text(data.get("criteria") or data.get("description")),
            evidence_required=_string_list(
                data.get("evidence_required") or data.get("required_evidence")
            ),
            linked_requirement_ids=_string_list(
                data.get("linked_requirement_ids")
                or data.get("requirement_ids")
            ),
            strategy=_text(data.get("strategy")),
            priority=_text(data.get("priority"), "normal"),
            source_references=_reference_list(data.get("source_references")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceMaterial:
    material_id: str
    material_type: str
    title: str = ""
    content: str = ""
    valid_until: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    source_references: list[SourceReference] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "EvidenceMaterial":
        material_id = _text(data.get("material_id") or data.get("id"))
        material_type = _text(data.get("material_type") or data.get("type"))
        if not material_id or not material_type:
            raise ValueError("evidence material requires material_id and material_type")
        return cls(
            material_id=material_id,
            material_type=material_type,
            title=_text(data.get("title") or data.get("name")),
            content=_text(data.get("content") or data.get("text")),
            valid_until=(
                _text(data.get("valid_until"))
                if data.get("valid_until") not in (None, "")
                else None
            ),
            metadata=_mapping(data.get("metadata"), "metadata"),
            source_references=_reference_list(data.get("source_references")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BidderProfile:
    bidder_id: str
    bidder_name: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    materials: list[EvidenceMaterial] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "BidderProfile":
        bidder_id = _text(data.get("bidder_id") or data.get("id"))
        if not bidder_id:
            raise ValueError("bidder_id is required")
        attributes = _mapping(data.get("attributes"), "attributes")
        for key, value in data.items():
            if key not in {"bidder_id", "id", "bidder_name", "attributes", "materials"}:
                attributes.setdefault(str(key), value)
        raw_materials = data.get("materials") or []
        if not isinstance(raw_materials, (list, tuple)):
            raise ValueError("materials must be a list")
        return cls(
            bidder_id=bidder_id,
            bidder_name=_text(data.get("bidder_name") or data.get("name")),
            attributes=attributes,
            materials=[EvidenceMaterial.from_mapping(item) for item in raw_materials],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FeasibilityCheck:
    requirement_id: str
    status: RequirementStatus
    reason: str
    mandatory: bool
    source_references: list[SourceReference] = field(default_factory=list)
    title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FeasibilityDecision:
    project_id: str
    decision: Literal["bid", "no_bid", "human_review"]
    checks: list[FeasibilityCheck] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceMatch:
    requirement_id: str
    material_id: str | None
    status: EvidenceMatchStatus
    confidence: float
    reason: str
    source_references: list[SourceReference] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
