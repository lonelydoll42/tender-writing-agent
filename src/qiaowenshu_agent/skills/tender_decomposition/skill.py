"""Tender requirement and scoring-item decomposition Skill."""

from __future__ import annotations

import inspect
from typing import Any, Mapping, Protocol

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import (
    Skill,
    SkillManifest,
    SkillRequest,
    SkillResult,
)
from qiaowenshu_agent.core.files import FileRegistryError, ProjectFileRegistry
from qiaowenshu_agent.domain.models import ScoringItem, TenderRequirement
from qiaowenshu_agent.skills.tender_common import (
    checklist_by_category,
    parse_requirements,
    parse_scoring_items,
)
from qiaowenshu_agent.skills.local_backends import (
    FileRegistryNotConfigured,
    _document_structure_conflict_warnings,
    _document_structure_content_signature,
    document_relations_for_structures,
)


class TenderDecompositionBackend(Protocol):
    def run(
        self,
        payload: Mapping[str, Any],
        context: SkillContext,
    ) -> Mapping[str, Any] | Any: ...


MANIFEST = SkillManifest(
    name="tender-decomposition",
    version="0.1.0",
    description="Convert tender content into atomic requirements and checklists.",
    input_schema={
        "type": "object",
        "required": ["project_id"],
        "properties": {
            "project_id": {"type": "string"},
            "profile": {"type": "object"},
            "sections": {"type": "array"},
            "document_structures": {"type": "array"},
            "requirements": {"type": "array"},
            "scoring_items": {"type": "array"},
        },
    },
    output_schema={
        "type": "object",
        "required": [
            "project_id",
            "requirements",
            "scoring_items",
            "checklists",
            "document_relations",
            "relation_analysis",
        ],
    },
    capabilities=("tender.requirements", "tender.checklists", "tender.scoring"),
    required_permissions=("document.read",),
)


class TenderDecompositionSkill(Skill):
    manifest = MANIFEST

    def __init__(
        self,
        *,
        backend: TenderDecompositionBackend | None = None,
    ) -> None:
        self.backend = backend

    async def execute(
        self,
        request: SkillRequest,
        context: SkillContext,
    ) -> SkillResult:
        try:
            payload = _parse_input(request.input)
        except (TypeError, ValueError) as exc:
            return SkillResult.failure(
                message=str(exc),
                error_code="INVALID_TENDER_DECOMPOSITION_INPUT",
            )
        if self.backend is None and not payload["requirements"]:
            return SkillResult.blocked(
                message="tender decomposition backend is not configured",
                error_code="TENDER_DECOMPOSITION_BACKEND_NOT_CONFIGURED",
            )
        try:
            raw = payload
            if self.backend is not None:
                raw = self.backend.run(payload, context)
                if inspect.isawaitable(raw):
                    raw = await raw
            file_registry = context.get_service("file_registry")
            registry_validation_performed = isinstance(
                file_registry, ProjectFileRegistry
            )
            registry_verified_structures = _registry_verified_document_structures(
                file_registry,
                project_id=payload["project_id"],
                document_structures=[
                    *payload["document_structures"],
                    *_backend_document_structures(raw),
                ],
            )
            data = _normalize_output(
                raw,
                project_id=payload["project_id"],
                document_structures=payload["document_structures"],
                registry_verified_structures=registry_verified_structures,
                registry_validation_performed=registry_validation_performed,
            )
        except FileRegistryNotConfigured as exc:
            return SkillResult.blocked(
                message=str(exc),
                error_code="TENDER_DECOMPOSITION_FILE_REGISTRY_NOT_CONFIGURED",
            )
        except ValueError as exc:
            return SkillResult.failure(
                message=str(exc),
                error_code="INVALID_TENDER_DECOMPOSITION_OUTPUT",
            )
        except Exception as exc:
            return SkillResult.failure(
                message=f"tender decomposition backend failed: {exc}",
                error_code="TENDER_DECOMPOSITION_BACKEND_FAILED",
                retryable=True,
            )
        return SkillResult.success(data, message="tender decomposition completed")


def _parse_input(data: Mapping[str, Any]) -> dict[str, Any]:
    project_id = str(data.get("project_id") or "").strip()
    if not project_id:
        raise ValueError("project_id is required")
    profile = data.get("profile") or {}
    sections = data.get("sections") or []
    if not isinstance(profile, Mapping):
        raise ValueError("profile must be an object")
    if not isinstance(sections, list):
        raise ValueError("sections must be a list")
    raw_structures = data.get("document_structures")
    if raw_structures is None:
        document_structures = [
            section["document_structure"]
            for section in sections
            if isinstance(section, Mapping)
            and isinstance(section.get("document_structure"), Mapping)
        ]
    elif isinstance(raw_structures, list):
        document_structures = list(raw_structures)
    else:
        raise ValueError("document_structures must be a list")
    return {
        "project_id": project_id,
        "profile": dict(profile),
        "sections": list(sections),
        "document_structures": document_structures,
        "requirements": list(data.get("requirements") or []),
        "scoring_items": list(data.get("scoring_items") or []),
    }


def _normalize_output(
    raw: Any,
    *,
    project_id: str,
    document_structures: list[Any] | None = None,
    registry_verified_structures: list[Any] | None = None,
    registry_validation_performed: bool = False,
) -> dict[str, Any]:
    if hasattr(raw, "to_dict"):
        raw = raw.to_dict()
    if isinstance(raw, list):
        raw = {"requirements": raw}
    if not isinstance(raw, Mapping):
        raise ValueError("tender decomposition backend must return an object or list")
    body = {str(key): value for key, value in raw.items()}
    requirements = parse_requirements(body.get("requirements"))
    scoring_items = parse_scoring_items(body.get("scoring_items"))
    if not scoring_items:
        scoring_items = _scoring_items_from_requirements(requirements)
    checklists = checklist_by_category(requirements)
    mandatory_count = sum(1 for item in requirements if item.mandatory)
    additional_document_structures = (
        body.get("document_structures")
        if isinstance(body.get("document_structures"), list)
        else []
    )
    raw_relation_source_structures = [
        *(document_structures or []),
        *additional_document_structures,
    ]
    merged_document_structures = _merge_document_structures(
        document_structures or [],
        additional_document_structures,
    )
    relation_output = document_relations_for_structures(
        raw_relation_source_structures,
        input_anchor_structures=(
            []
            if registry_validation_performed
            else document_structures or []
        ),
        registry_verified_structures=registry_verified_structures or [],
    )
    warnings = [
        str(item) for item in (body.get("warnings") or [])
    ]
    warnings.extend(
        warning
        for warning in _document_structure_conflict_warnings(relation_output)
        if warning not in warnings
    )
    result = {
        "project_id": project_id,
        "requirements": [item.to_dict() for item in requirements],
        "scoring_items": [item.to_dict() for item in scoring_items],
        "document_structures": merged_document_structures,
        **relation_output,
        "checklists": checklists,
        "summary": {
            "requirement_count": len(requirements),
            "mandatory_count": mandatory_count,
            "scoring_item_count": len(scoring_items),
            "categories": {key: len(value) for key, value in checklists.items()},
        },
        "warnings": warnings,
    }
    if "block_projection_audit" in body:
        result["block_projection_audit"] = body["block_projection_audit"]
    if "needs_human_review" in body:
        result["needs_human_review"] = bool(body["needs_human_review"])
    if "business_status" in body:
        result["business_status"] = str(body["business_status"])
    if "extraction_complete" in body:
        result["extraction_complete"] = bool(body["extraction_complete"])
    return result


def _backend_document_structures(raw: Any) -> list[Any]:
    if hasattr(raw, "to_dict"):
        raw = raw.to_dict()
    if not isinstance(raw, Mapping):
        return []
    structures = raw.get("document_structures")
    return structures if isinstance(structures, list) else []


def _registry_verified_document_structures(
    registry: Any,
    *,
    project_id: str,
    document_structures: list[Any],
) -> list[dict[str, Any]]:
    if not isinstance(registry, ProjectFileRegistry):
        return []
    verified: list[dict[str, Any]] = []
    required_by_file_id: dict[str, Any | None] = {}
    project_file_records: dict[str, tuple[set[str], set[str]] | None] = {}
    parsed_by_file_id: dict[str, Mapping[str, Any] | None] = {}
    for candidate in document_structures:
        if not isinstance(candidate, Mapping):
            continue
        document_id = str(candidate.get("document_id") or "").strip()
        source_version = str(candidate.get("source_version") or "").strip()
        if not document_id or not source_version:
            continue
        if document_id not in required_by_file_id:
            try:
                required = registry.require(document_id)
            except (FileRegistryError, KeyError, ValueError):
                required = None
            required_by_file_id[document_id] = required
        registered_file = required_by_file_id[document_id]
        if registered_file is None:
            continue
        registered_file_id = str(
            getattr(registered_file, "file_id", "") or ""
        )
        registered_project_id = str(
            getattr(registered_file, "project_id", "") or ""
        )
        registered_version = getattr(registered_file, "version", None)
        registered_checksum = str(
            getattr(registered_file, "checksum", "") or ""
        ).strip()
        if (
            registered_file_id != document_id
            or registered_project_id != project_id
        ):
            continue
        if (
            registered_version in (None, "")
            or source_version != f"{document_id}:v{registered_version}"
            or not registered_checksum
            or str(candidate.get("source_checksum") or "").strip()
            != registered_checksum
        ):
            continue
        if project_id not in project_file_records:
            try:
                project_files = registry.list(project_id)
            except (FileRegistryError, KeyError, ValueError):
                project_file_records[project_id] = None
            else:
                project_file_records[project_id] = (
                    {
                        str(getattr(file, "file_id", "") or "")
                        for file in project_files
                    },
                    {
                        str(getattr(file, "supersedes", "") or "")
                        for file in project_files
                        if getattr(file, "supersedes", None)
                    },
                )
        current_project_files = project_file_records[project_id]
        if (
            current_project_files is None
            or registered_file_id not in current_project_files[0]
            or document_id in current_project_files[1]
        ):
            continue
        if document_id not in parsed_by_file_id:
            try:
                parsed = registry.parse(document_id)
            except (FileRegistryError, KeyError, ValueError):
                parsed = None
            parsed_by_file_id[document_id] = (
                parsed if isinstance(parsed, Mapping) else None
            )
        artifact = parsed_by_file_id[document_id]
        if artifact is None:
            continue
        if (
            str(artifact.get("project_id") or "") != project_id
            or str(artifact.get("file_id") or "") != document_id
            or artifact.get("version") != registered_version
            or str(artifact.get("checksum") or "").strip()
            != registered_checksum
        ):
            continue
        registry_structure = artifact.get("document_structure")
        if not isinstance(registry_structure, Mapping):
            continue
        registry_checksum = str(
            registry_structure.get("source_checksum") or ""
        ).strip()
        if not registry_checksum or str(candidate.get("source_checksum") or "") != (
            registry_checksum
        ):
            continue
        if (
            str(registry_structure.get("document_id") or "") != document_id
            or str(registry_structure.get("source_version") or "") != source_version
            or _document_structure_content_signature(candidate)
            != _document_structure_content_signature(registry_structure)
        ):
            continue
        trusted_structure = dict(registry_structure)
        if trusted_structure not in verified:
            verified.append(trusted_structure)
    return verified


def _merge_document_structures(
    preferred: list[Any],
    additional: list[Any],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    for item in [*preferred, *additional]:
        if not isinstance(item, Mapping):
            continue
        structure = dict(item)
        document_id = str(structure.get("document_id") or "").strip()
        source_version = str(structure.get("source_version") or "").strip()
        identity = (document_id, source_version)
        if all(identity) and identity in identities:
            continue
        if structure not in result:
            result.append(structure)
            if all(identity):
                identities.add(identity)
    return result


def _scoring_items_from_requirements(
    requirements: list[TenderRequirement],
) -> list[ScoringItem]:
    return [
        ScoringItem(
            item_id=item.requirement_id,
            title=item.title,
            max_score=item.max_score,
            criteria=item.description,
            evidence_required=list(item.evidence_required),
            linked_requirement_ids=[item.requirement_id],
            source_references=list(item.source_references),
        )
        for item in requirements
        if item.category == "scoring" and item.max_score is not None
    ]
