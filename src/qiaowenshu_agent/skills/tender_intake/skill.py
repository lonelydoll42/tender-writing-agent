"""Tender document intake and structured profile Skill."""

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
from qiaowenshu_agent.domain.models import TenderProfile
from qiaowenshu_agent.skills.local_backends import FileRegistryNotConfigured


class TenderIntakeBackend(Protocol):
    def run(
        self,
        payload: Mapping[str, Any],
        context: SkillContext,
    ) -> Mapping[str, Any] | Any: ...


MANIFEST = SkillManifest(
    name="tender-intake",
    version="0.1.0",
    description="Build a page-aware structured profile from tender documents.",
    input_schema={
        "type": "object",
        "required": ["project_id", "file_ids"],
        "properties": {
            "project_id": {"type": "string"},
            "file_ids": {"type": "array", "items": {"type": "string"}},
            "business_scene": {"type": "string"},
            "options": {"type": "object"},
        },
    },
    output_schema={
        "type": "object",
        "required": ["project_id", "profile", "sections", "pages"],
    },
    capabilities=("tender.profile", "tender.sections", "tender.evidence"),
    required_permissions=("document.read",),
)


class TenderIntakeSkill(Skill):
    manifest = MANIFEST

    def __init__(self, *, backend: TenderIntakeBackend | None = None) -> None:
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
                error_code="INVALID_TENDER_INTAKE_INPUT",
            )
        if self.backend is None:
            return SkillResult.blocked(
                message="tender intake backend is not configured",
                error_code="TENDER_INTAKE_BACKEND_NOT_CONFIGURED",
            )
        try:
            raw = self.backend.run(payload, context)
            if inspect.isawaitable(raw):
                raw = await raw
            data = _normalize_output(raw, project_id=payload["project_id"])
        except FileRegistryNotConfigured as exc:
            return SkillResult.blocked(
                message=str(exc),
                error_code="TENDER_INTAKE_FILE_REGISTRY_NOT_CONFIGURED",
            )
        except ValueError as exc:
            return SkillResult.failure(
                message=str(exc),
                error_code="INVALID_TENDER_INTAKE_OUTPUT",
            )
        except Exception as exc:
            return SkillResult.failure(
                message=f"tender intake backend failed: {exc}",
                error_code="TENDER_INTAKE_BACKEND_FAILED",
                retryable=True,
            )
        return SkillResult.success(data, message="tender intake completed")


def _parse_input(data: Mapping[str, Any]) -> dict[str, Any]:
    project_id = str(data.get("project_id") or "").strip()
    if not project_id:
        raise ValueError("project_id is required")
    raw_file_ids = data.get("file_ids")
    if raw_file_ids is None and data.get("file_id"):
        raw_file_ids = [data["file_id"]]
    if not isinstance(raw_file_ids, (list, tuple)):
        raise ValueError("file_ids must be a non-empty list")
    file_ids = [str(item).strip() for item in raw_file_ids if str(item).strip()]
    if not file_ids:
        raise ValueError("file_ids must be a non-empty list")
    options = data.get("options") or {}
    if not isinstance(options, Mapping):
        raise ValueError("options must be an object")
    return {
        "project_id": project_id,
        "file_ids": file_ids,
        "business_scene": str(data.get("business_scene") or "tender_parse"),
        "options": dict(options),
    }


def _normalize_output(raw: Any, *, project_id: str) -> dict[str, Any]:
    if hasattr(raw, "to_dict"):
        raw = raw.to_dict()
    if not isinstance(raw, Mapping):
        raise ValueError("tender intake backend must return an object")
    body = {str(key): value for key, value in raw.items()}
    profile_raw = body.get("profile") or body.get("tender_profile") or body
    if not isinstance(profile_raw, Mapping):
        raise ValueError("tender intake profile must be an object")
    profile_data = dict(profile_raw)
    profile_data.setdefault("project_id", project_id)
    profile = TenderProfile.from_mapping(profile_data)
    sections = body.get("sections") or []
    pages = body.get("pages") or []
    artifacts = body.get("artifacts") or []
    for name, value in (
        ("sections", sections),
        ("pages", pages),
        ("artifacts", artifacts),
    ):
        if not isinstance(value, list):
            raise ValueError(f"{name} must be a list")
    raw_structures = body.get("document_structures")
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
    for section in sections:
        if not isinstance(section, Mapping):
            continue
        structure = section.get("document_structure")
        if isinstance(structure, Mapping) and structure not in document_structures:
            document_structures.append(structure)

    normalized_sections: list[Any] = []
    structure_warnings: list[str] = []
    for section in sections:
        if not isinstance(section, Mapping):
            normalized_sections.append(section)
            continue
        normalized_section = dict(section)
        attached_structure = normalized_section.get("document_structure")
        document_id, source_version, identity_error = _section_structure_identity(
            normalized_section,
            attached_structure if isinstance(attached_structure, Mapping) else None,
        )
        matches = [
            structure
            for structure in document_structures
            if isinstance(structure, Mapping)
            and document_id
            and str(structure.get("document_id") or "") == document_id
            and (
                not source_version
                or str(structure.get("source_version") or "") == source_version
            )
        ]
        if not identity_error and len(matches) == 1:
            normalized_section["document_structure"] = matches[0]
        else:
            normalized_section.pop("document_structure", None)
            if document_structures or isinstance(attached_structure, Mapping):
                reason = (
                    identity_error
                    or "source identity is missing or matches multiple structures"
                )
                structure_warnings.append(
                    "document_structure was preserved at top level but not "
                    f"attached to section "
                    f"{normalized_section.get('section_id') or ''}: "
                    f"{reason}"
                )
        normalized_sections.append(normalized_section)

    warnings = [str(item) for item in (body.get("warnings") or [])]
    warnings.extend(profile.warnings)
    warnings.extend(structure_warnings)
    return {
        "project_id": project_id,
        "profile": profile.to_dict(),
        "sections": normalized_sections,
        "pages": list(pages),
        "document_structures": document_structures,
        "artifacts": list(artifacts),
        "warnings": warnings,
    }


def _section_structure_identity(
    section: Mapping[str, Any],
    attached_structure: Mapping[str, Any] | None,
) -> tuple[str, str, str | None]:
    document_ids = {
        str(section.get(key) or "").strip()
        for key in ("file_id", "document_id")
        if str(section.get(key) or "").strip()
    }
    source_versions = {
        str(section.get(key) or "").strip()
        for key in ("source_version", "source_file_version")
        if str(section.get(key) or "").strip()
    }
    reference_document_ids: set[str] = set()
    reference_versions: set[str] = set()
    references = section.get("source_references") or []
    if isinstance(references, (list, tuple)):
        for reference in references:
            if not isinstance(reference, Mapping):
                continue
            document_id = str(reference.get("document_id") or "").strip()
            source_version = str(
                reference.get("source_version")
                or reference.get("source_file_version")
                or ""
            ).strip()
            if document_id:
                reference_document_ids.add(document_id)
            if source_version:
                reference_versions.add(source_version)

    if attached_structure is not None:
        attached_document_id = str(attached_structure.get("document_id") or "").strip()
        attached_source_version = str(
            attached_structure.get("source_version") or ""
        ).strip()
        if attached_document_id:
            document_ids.add(attached_document_id)
        if attached_source_version:
            source_versions.add(attached_source_version)

    if len(reference_document_ids) > 1 or len(reference_versions) > 1:
        return "", "", "section references contain conflicting document versions"
    if reference_document_ids and document_ids - reference_document_ids:
        return "", "", "section identity conflicts with source references"
    if reference_versions and source_versions - reference_versions:
        return "", "", "section version conflicts with source references"
    if len(document_ids) > 1:
        return "", "", "section contains conflicting document identifiers"
    if len(source_versions) > 1:
        return "", "", "section contains conflicting source versions"

    document_id = next(iter(document_ids), "")
    source_version = next(iter(source_versions), "")
    if not document_id and len(reference_document_ids) == 1:
        document_id = next(iter(reference_document_ids))
    if not source_version and len(reference_versions) == 1:
        source_version = next(iter(reference_versions))
    return document_id, source_version, None
