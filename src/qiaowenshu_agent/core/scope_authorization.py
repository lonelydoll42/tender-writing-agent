"""Runtime-owned, persisted bindings between reviews and writing inputs."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping


SCOPE_BINDINGS_STATE_KEY = "__runtime_review_scope_bindings_v1"
SCOPE_BINDINGS_VERSION = 1

_REQUIREMENT_ID_KEYS = ("requirement_id", "id")
_SCORING_ID_KEYS = ("item_id", "scoring_item_id", "score_id", "id")
_SECTION_ID_KEYS = ("section_id", "id")
_MATERIAL_ID_KEYS = ("material_id", "id")
_RUNTIME_SCORING_ID_PREFIX = "__runtime_scoring__:"


def prepare_compliance_review_input(value: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt resolved pipeline outputs to the deterministic review contract."""

    payload = copy.deepcopy(dict(value))
    requirements = payload.get("requirements")
    scoring_items = payload.get("scoring_items")
    if isinstance(requirements, (list, tuple)) and isinstance(
        scoring_items, (list, tuple)
    ):
        combined = list(requirements)
        colliding_ids = set(_catalog_id_collisions(payload))
        known_ids = {
            _record_identifier(row, _REQUIREMENT_ID_KEYS)
            for row in combined
            if isinstance(row, Mapping)
        }
        for item in scoring_items:
            if not isinstance(item, Mapping):
                continue
            item_id = _record_identifier(item, _SCORING_ID_KEYS)
            if not item_id:
                continue
            if item_id in colliding_ids:
                review_id = f"{_RUNTIME_SCORING_ID_PREFIX}{item_id}"
                suffix = 2
                while review_id in known_ids:
                    review_id = (
                        f"{_RUNTIME_SCORING_ID_PREFIX}{item_id}:{suffix}"
                    )
                    suffix += 1
            else:
                if item_id in known_ids:
                    continue
                review_id = item_id
            combined.append(
                {
                    "requirement_id": review_id,
                    "source_scoring_item_id": item_id,
                    "item_type": "scoring",
                    "category": "scoring",
                    "title": item.get("title") or item.get("name") or item_id,
                    "description": (
                        item.get("criteria")
                        or item.get("description")
                        or item.get("title")
                        or item_id
                    ),
                    "mandatory": False,
                    "max_score": item.get("max_score", item.get("score")),
                    "source_references": item.get("source_references") or [],
                }
            )
            known_ids.add(review_id)
        payload["requirements"] = combined

    ledger = payload.get("ledger")
    if isinstance(ledger, Mapping):
        nested_ledger = ledger.get("ledger")
        entries = ledger.get("entries")
        if (
            isinstance(nested_ledger, Mapping)
            and isinstance(entries, (list, tuple))
        ):
            payload["ledger"] = copy.deepcopy(dict(nested_ledger))
            payload.setdefault("ledger_entries", copy.deepcopy(list(entries)))
    return payload


def evaluate_compliance_input(value: Mapping[str, Any]) -> dict[str, Any] | None:
    """Re-run the local deterministic review so a claimed pass is not authority."""

    try:
        from qiaowenshu_agent.skills.compliance_review.skill import _review

        return _review(prepare_compliance_review_input(value))
    except (TypeError, ValueError, KeyError):
        return None


def create_review_binding(
    *,
    run_id: str,
    step_index: int,
    review_input: Mapping[str, Any],
    request_input: Mapping[str, Any],
    expected_review: Mapping[str, Any] | None,
    review_result_passed: bool,
    file_registry: Any,
    artifact_dependencies: list[dict[str, Any]],
    scope_snapshot: tuple[dict[str, Any], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    scope, reasons = scope_snapshot or build_writing_scope(
        review_input,
        request_input=request_input,
        file_registry=file_registry,
        artifact_dependencies=artifact_dependencies,
    )
    if expected_review is None:
        reasons.append(
            _reason(
                "review_validation_unavailable",
                "Runtime could not independently validate the resolved review input.",
            )
        )
    elif expected_review.get("business_status") != "passed":
        reasons.append(
            _reason(
                "review_validation_failed",
                "The deterministic review of the resolved input did not pass.",
                expected_business_status=expected_review.get("business_status"),
            )
        )
    if not review_result_passed:
        reasons.append(
            _reason(
                "review_not_passed",
                "The executed compliance-review result is not a successful pass.",
            )
        )
    reasons = _unique_reasons(reasons)
    status = "bound" if not reasons else "not_bound"
    binding: dict[str, Any] = {
        "version": SCOPE_BINDINGS_VERSION,
        "binding_id": f"{run_id}:review:{step_index}",
        "review_step_index": step_index,
        "status": status,
        "project_id": scope.get("project_id"),
        "scope_fingerprint": _fingerprint(scope),
        "requirements_fingerprint": scope.get("requirements_fingerprint"),
        "scoring_fingerprint": scope.get("scoring_fingerprint"),
        "section_ids": list(scope.get("section_ids") or []),
        "source_file_versions": list(scope.get("source_file_versions") or []),
        "artifact_dependency_ids": list(
            scope.get("artifact_dependency_ids") or []
        ),
        "review_input_fingerprint": _fingerprint(review_input),
        "scope": scope,
        "reasons": reasons,
    }
    binding["integrity_digest"] = _fingerprint(binding)
    return binding


def build_writing_scope(
    value: Mapping[str, Any],
    *,
    request_input: Mapping[str, Any],
    file_registry: Any,
    artifact_dependencies: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Resolve the effective writer payload and fingerprint its actual scope."""

    reasons: list[dict[str, Any]] = []
    project_id, project_reasons = _effective_project_id(value, request_input)
    reasons.extend(project_reasons)
    if not project_id:
        reasons.append(
            _reason(
                "project_id_missing",
                "A writing authorization requires a confirmed project ID.",
            )
        )

    if "requirements" not in value or value.get("requirements") is None:
        reasons.append(
            _reason(
                "requirements_not_supplied",
                "The review must receive the complete structured requirements catalog.",
            )
        )
    if "scoring_items" not in value or value.get("scoring_items") is None:
        reasons.append(
            _reason(
                "scoring_items_not_supplied",
                "The review must receive the scoring catalog, even when empty.",
            )
        )

    writer_payload = copy.deepcopy(dict(value))
    if not str(writer_payload.get("project_id") or "").strip():
        profile = writer_payload.get("tender_profile")
        profile_project = (
            str(profile.get("project_id") or "").strip()
            if isinstance(profile, Mapping)
            else ""
        )
        if not profile_project and project_id:
            writer_payload["project_id"] = project_id
        elif profile_project:
            writer_payload["project_id"] = profile_project

    parsed: dict[str, Any] = {}
    selected_sections: list[dict[str, Any]] = []
    try:
        from qiaowenshu_agent.skills.document_writing.skill import (
            _parse_input,
            _select_sections,
        )

        parsed = _parse_input(writer_payload)
        selected_sections = _select_sections(parsed)
    except (TypeError, ValueError, KeyError) as exc:
        reasons.append(
            _reason(
                "writing_scope_unresolvable",
                "The resolved input cannot be normalized with the writer's rules.",
                detail=str(exc),
            )
        )

    requirements, requirement_reasons = _indexed_records(
        value.get("requirements"),
        _REQUIREMENT_ID_KEYS,
        label="requirement",
        field_present="requirements" in value,
    )
    scoring_items, scoring_reasons = _indexed_records(
        value.get("scoring_items"),
        _SCORING_ID_KEYS,
        label="scoring_item",
        field_present="scoring_items" in value,
    )
    sections, section_reasons = _indexed_records(
        selected_sections,
        _SECTION_ID_KEYS,
        label="section",
        field_present=True,
    )
    reasons.extend(requirement_reasons)
    reasons.extend(scoring_reasons)
    reasons.extend(section_reasons)
    colliding_ids = _catalog_id_collisions(value)
    if colliding_ids:
        reasons.append(
            _reason(
                "requirement_scoring_id_collision",
                (
                    "A shared ID makes the requirement and scoring targets "
                    "ambiguous for review authorization."
                ),
                identifiers=colliding_ids,
            )
        )
    if not requirements and not scoring_items:
        reasons.append(
            _reason(
                "writing_requirements_empty",
                "A writing binding needs a reviewed requirement or scoring item.",
            )
        )
    if not sections:
        reasons.append(
            _reason(
                "writing_sections_empty",
                "The writer's actual section selector produced no chapters.",
            )
        )

    source_versions, source_reasons = _source_file_versions(
        value,
        request_input=request_input,
        file_registry=file_registry,
    )
    reasons.extend(source_reasons)
    dependencies, dependency_reasons = _dependency_index(artifact_dependencies)
    reasons.extend(dependency_reasons)

    context_exact: dict[str, str] = {}
    for key in (
        "tender_profile",
        "bidder_profile",
        "as_of",
        "bid_deadline",
        "style",
    ):
        normalized = (
            value.get(key)
            if key == "bid_deadline"
            else parsed.get(key)
            if parsed
            else value.get(key)
        )
        context_exact[key] = _fingerprint(normalized)

    context_subset: dict[str, dict[str, str]] = {}
    for key, id_keys in (
        ("materials", _MATERIAL_ID_KEYS),
        ("evidence_matches", ("match_id", "requirement_id", "id")),
        ("confirmed_facts", ("fact_id", "id")),
        ("approved_commitments", ("commitment_id", "id")),
    ):
        normalized = (
            parsed.get(key, value.get(key, []))
            if parsed
            else value.get(key, [])
        )
        context_subset[key] = _fingerprinted_collection(normalized, id_keys)

    tender_text = (
        parsed.get("tender_text", "") if parsed else value.get("tender_text", "")
    )
    context_exact["tender_text"] = _fingerprint(
        _normalize_text(tender_text)
    )
    scope = {
        "project_id": project_id,
        "requirements": requirements,
        "requirements_fingerprint": _fingerprint(requirements),
        "scoring_items": scoring_items,
        "scoring_fingerprint": _fingerprint(scoring_items),
        "sections": sections,
        "section_ids": list(sections),
        "context_exact": context_exact,
        "context_subset": context_subset,
        "source_file_versions": sorted(source_versions),
        "artifact_dependencies": dependencies,
        "artifact_dependency_ids": sorted(dependencies),
    }
    return scope, _unique_reasons(reasons)


def authorize_writer_scope(
    *,
    bindings: list[dict[str, Any]],
    steps: list[Any],
    writer_input: Mapping[str, Any],
    request_input: Mapping[str, Any],
    file_registry: Any,
    artifact_dependencies: list[dict[str, Any]],
) -> dict[str, Any]:
    """Authorize against one persisted review binding, never a union of reviews."""

    valid_bindings, integrity_reasons = validate_review_bindings(bindings, steps)
    if not valid_bindings:
        reasons = integrity_reasons or [
            _reason(
                "review_binding_missing",
                "No runtime-generated review binding is available for writing.",
            )
        ]
        return {
            "status": "blocked",
            "match_kind": None,
            "reasons": _unique_reasons(reasons),
            "candidates": [],
        }

    writer_scope, writer_reasons = build_writing_scope(
        writer_input,
        request_input=request_input,
        file_registry=file_registry,
        artifact_dependencies=artifact_dependencies,
    )
    candidate_results: list[dict[str, Any]] = []
    for binding in valid_bindings:
        if binding.get("status") != "bound":
            candidate_results.append(
                {
                    "binding_id": binding.get("binding_id"),
                    "status": "not_bound",
                    "reasons": binding.get("reasons") or [],
                }
            )
            continue
        reasons, match_kind = _compare_scopes(binding.get("scope"), writer_scope)
        reasons = _unique_reasons(writer_reasons + reasons)
        candidate_results.append(
            {
                "binding_id": binding.get("binding_id"),
                "status": "matched" if not reasons else "mismatch",
                "match_kind": match_kind if not reasons else None,
                "reasons": reasons,
            }
        )

    matched = next(
        (item for item in candidate_results if item["status"] == "matched"),
        None,
    )
    if matched is not None:
        binding = next(
            item
            for item in valid_bindings
            if item.get("binding_id") == matched["binding_id"]
        )
        return {
            "status": "authorized",
            "match_kind": matched["match_kind"],
            "binding_id": binding["binding_id"],
            "project_id": binding.get("project_id"),
            "scope_fingerprint": binding.get("scope_fingerprint"),
            "requirements_fingerprint": binding.get("requirements_fingerprint"),
            "scoring_fingerprint": binding.get("scoring_fingerprint"),
            "sections": list(writer_scope.get("section_ids") or []),
            "reasons": [
                _reason(
                    "authorized_exact_scope"
                    if matched["match_kind"] == "exact"
                    else "authorized_safe_subset",
                    "The resolved writer scope is within one passed review binding.",
                )
            ],
            "candidates": candidate_results,
        }

    all_reasons = [
        {
            "binding_id": item.get("binding_id"),
            **reason,
        }
        for item in candidate_results
        for reason in item.get("reasons", [])
    ]
    return {
        "status": "blocked",
        "match_kind": None,
        "project_id": writer_scope.get("project_id"),
        "scope_fingerprint": _fingerprint(writer_scope),
        "reasons": _unique_reasons(all_reasons or writer_reasons),
        "candidates": candidate_results,
    }


def validate_review_bindings(
    bindings: list[dict[str, Any]],
    steps: list[Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    valid: list[dict[str, Any]] = []
    reasons: list[dict[str, Any]] = []
    for binding in bindings:
        if not isinstance(binding, Mapping):
            reasons.append(
                _reason(
                    "review_binding_corrupt",
                    "A persisted runtime review binding is malformed.",
                )
            )
            continue
        body = dict(binding)
        integrity_digest = body.pop("integrity_digest", None)
        if (
            body.get("version") != SCOPE_BINDINGS_VERSION
            or not isinstance(integrity_digest, str)
            or _fingerprint(body) != integrity_digest
        ):
            reasons.append(
                _reason(
                    "review_binding_corrupt",
                    "A persisted runtime review binding failed its integrity check.",
                    binding_id=binding.get("binding_id"),
                )
            )
            continue
        index = binding.get("review_step_index")
        if not isinstance(index, int) or index < 0 or index >= len(steps):
            reasons.append(
                _reason(
                    "review_binding_step_missing",
                    "The review step linked to a persisted binding is unavailable.",
                    binding_id=binding.get("binding_id"),
                )
            )
            continue
        step = steps[index]
        if getattr(step, "skill_name", None) != "compliance-review":
            reasons.append(
                _reason(
                    "review_binding_step_mismatch",
                    "The persisted binding is not linked to a compliance-review step.",
                    binding_id=binding.get("binding_id"),
                )
            )
            continue
        result = getattr(step, "result", None)
        data = getattr(result, "data", None)
        public_binding = (
            data.get("runtime_scope_binding")
            if isinstance(data, Mapping)
            else None
        )
        if (
            not isinstance(public_binding, Mapping)
            or public_binding.get("binding_id") != binding.get("binding_id")
            or public_binding.get("integrity_digest") != integrity_digest
        ):
            reasons.append(
                _reason(
                    "review_binding_step_mismatch",
                    "The persisted binding does not match its recorded review result.",
                    binding_id=binding.get("binding_id"),
                )
            )
            continue
        scope = binding.get("scope")
        scope_requirements = (
            scope.get("requirements") if isinstance(scope, Mapping) else None
        )
        scope_scoring_items = (
            scope.get("scoring_items") if isinstance(scope, Mapping) else None
        )
        if isinstance(scope_requirements, Mapping) and isinstance(
            scope_scoring_items, Mapping
        ):
            colliding_ids = sorted(
                str(identifier)
                for identifier in set(scope_requirements)
                & set(scope_scoring_items)
            )
            if colliding_ids:
                reasons.append(
                    _reason(
                        "requirement_scoring_id_collision",
                        (
                            "A persisted review binding contains an ID shared "
                            "by requirement and scoring targets."
                        ),
                        binding_id=binding.get("binding_id"),
                        identifiers=colliding_ids,
                    )
                )
                continue
        valid.append(dict(binding))
    return valid, _unique_reasons(reasons)


def public_binding(binding: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": binding.get("status", "not_bound"),
        "binding_id": binding.get("binding_id"),
        "integrity_digest": binding.get("integrity_digest"),
        "review_step_index": binding.get("review_step_index"),
        "project_id": binding.get("project_id"),
        "scope_fingerprint": binding.get("scope_fingerprint"),
        "requirements_fingerprint": binding.get("requirements_fingerprint"),
        "scoring_fingerprint": binding.get("scoring_fingerprint"),
        "section_ids": list(binding.get("section_ids") or []),
        "source_file_versions": list(binding.get("source_file_versions") or []),
        "artifact_dependency_ids": list(
            binding.get("artifact_dependency_ids") or []
        ),
        "reasons": copy.deepcopy(list(binding.get("reasons") or [])),
    }


def binding_container(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Mapping) or value.get("version") != SCOPE_BINDINGS_VERSION:
        return []
    bindings = value.get("bindings")
    if not isinstance(bindings, list):
        return []
    return [dict(item) for item in bindings if isinstance(item, Mapping)]


def append_binding(container: Any, binding: dict[str, Any]) -> dict[str, Any]:
    bindings = binding_container(container)
    bindings.append(binding)
    return {"version": SCOPE_BINDINGS_VERSION, "bindings": bindings}


def collect_artifact_dependencies(
    artifact_ids: list[str],
    store: Any,
) -> list[dict[str, Any]]:
    getter = getattr(store, "get_artifact", None)
    if not callable(getter):
        return []
    found: dict[str, dict[str, Any]] = {}
    visiting: set[str] = set()

    def visit(artifact_id: str) -> None:
        if artifact_id in found or artifact_id in visiting:
            return
        visiting.add(artifact_id)
        try:
            artifact = getter(artifact_id)
        except Exception:
            artifact = None
        if artifact is None:
            visiting.remove(artifact_id)
            return
        dependency_ids = [
            str(item) for item in getattr(artifact, "dependencies", []) if str(item)
        ]
        record = {
            "artifact_id": str(getattr(artifact, "artifact_id", artifact_id)),
            "artifact_type": str(getattr(artifact, "artifact_type", "")),
            "project_id": str(getattr(artifact, "project_id", "")),
            "schema_version": str(getattr(artifact, "schema_version", "")),
            "content_hash": str(getattr(artifact, "content_hash", "")),
            "source_file_versions": sorted(
                str(item)
                for item in getattr(artifact, "source_file_versions", [])
            ),
            "dependencies": sorted(dependency_ids),
        }
        found[record["artifact_id"]] = {
            "artifact_id": record["artifact_id"],
            "fingerprint": _fingerprint(record),
        }
        for dependency_id in dependency_ids:
            visit(dependency_id)
        visiting.remove(artifact_id)

    for artifact_id in artifact_ids:
        if artifact_id:
            visit(str(artifact_id))
    return [found[key] for key in sorted(found)]


def _compare_scopes(
    reviewed: Any,
    requested: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(reviewed, Mapping):
        return [
            _reason(
                "review_binding_corrupt",
                "The persisted review scope is missing or malformed.",
            )
        ], "none"

    reasons: list[dict[str, Any]] = []
    if reviewed.get("project_id") != requested.get("project_id"):
        reasons.append(
            _reason(
                "project_mismatch",
                "The writer project does not match the reviewed project.",
                reviewed_project_id=reviewed.get("project_id"),
                writer_project_id=requested.get("project_id"),
            )
        )

    for field, label, missing_code, changed_code in (
        (
            "requirements",
            "requirement",
            "requirement_not_reviewed",
            "requirement_content_changed",
        ),
        (
            "scoring_items",
            "scoring item",
            "scoring_item_not_reviewed",
            "scoring_item_content_changed",
        ),
        (
            "sections",
            "section",
            "section_not_reviewed",
            "section_content_changed",
        ),
    ):
        _append_indexed_subset_reasons(
            reasons,
            reviewed.get(field),
            requested.get(field),
            label=label,
            missing_code=missing_code,
            changed_code=changed_code,
        )

    reviewed_context = reviewed.get("context_exact")
    writer_context = requested.get("context_exact")
    if not isinstance(reviewed_context, Mapping) or not isinstance(
        writer_context, Mapping
    ):
        reasons.append(
            _reason(
                "scope_context_unverifiable",
                "The factual writing context could not be fingerprinted.",
            )
        )
    else:
        for field, reviewed_digest in reviewed_context.items():
            if field not in writer_context:
                continue
            if writer_context.get(field) != reviewed_digest:
                code = (
                    "bidder_profile_changed"
                    if field == "bidder_profile"
                    else "scope_context_changed"
                )
                reasons.append(
                    _reason(
                        code,
                        f"The writer's {field} differs from the reviewed context.",
                        field=field,
                    )
                )

    reviewed_subset = reviewed.get("context_subset")
    writer_subset = requested.get("context_subset")
    if not isinstance(reviewed_subset, Mapping) or not isinstance(
        writer_subset, Mapping
    ):
        reasons.append(
            _reason(
                "scope_context_unverifiable",
                "The factual writing collections could not be fingerprinted.",
            )
        )
    else:
        codes = {
            "materials": "material_not_reviewed",
            "evidence_matches": "evidence_match_not_reviewed",
            "confirmed_facts": "confirmed_fact_not_reviewed",
            "approved_commitments": "approved_commitment_not_reviewed",
        }
        for field, values in writer_subset.items():
            _append_fingerprint_subset_reasons(
                reasons,
                reviewed_subset.get(field),
                values,
                label=field,
                missing_code=codes.get(field, "scope_context_changed"),
            )

    _append_string_subset_reasons(
        reasons,
        reviewed.get("source_file_versions"),
        requested.get("source_file_versions"),
        code="source_file_not_reviewed",
        label="source file version",
    )
    _append_fingerprint_subset_reasons(
        reasons,
        reviewed.get("artifact_dependencies"),
        requested.get("artifact_dependencies"),
        label="artifact dependency",
        missing_code="artifact_dependency_not_reviewed",
    )

    if reasons:
        return _unique_reasons(reasons), "none"
    exact = _fingerprint(reviewed) == _fingerprint(requested)
    return [], "exact" if exact else "safe_subset"


def _append_indexed_subset_reasons(
    reasons: list[dict[str, Any]],
    reviewed: Any,
    requested: Any,
    *,
    label: str,
    missing_code: str,
    changed_code: str,
) -> None:
    if not isinstance(reviewed, Mapping) or not isinstance(requested, Mapping):
        reasons.append(
            _reason(
                "scope_collection_unverifiable",
                f"The reviewed or requested {label} collection is unavailable.",
                collection=label,
            )
        )
        return
    for identifier, requested_item in requested.items():
        if identifier not in reviewed:
            reasons.append(
                _reason(
                    missing_code,
                    f"The writer includes an unreviewed {label}.",
                    identifier=identifier,
                )
            )
        elif reviewed.get(identifier) != requested_item:
            reasons.append(
                _reason(
                    changed_code,
                    f"The writer changed the reviewed {label}.",
                    identifier=identifier,
                )
            )


def _append_fingerprint_subset_reasons(
    reasons: list[dict[str, Any]],
    reviewed: Any,
    requested: Any,
    *,
    label: str,
    missing_code: str,
) -> None:
    if not isinstance(reviewed, Mapping) or not isinstance(requested, Mapping):
        reasons.append(
            _reason(
                "scope_collection_unverifiable",
                f"The reviewed or requested {label} collection is unavailable.",
                collection=label,
            )
        )
        return
    for identifier, fingerprint in requested.items():
        if reviewed.get(identifier) != fingerprint:
            reasons.append(
                _reason(
                    missing_code,
                    f"The writer includes an unreviewed or changed {label}.",
                    identifier=identifier,
                )
            )


def _append_string_subset_reasons(
    reasons: list[dict[str, Any]],
    reviewed: Any,
    requested: Any,
    *,
    code: str,
    label: str,
) -> None:
    if not isinstance(reviewed, (list, tuple)) or not isinstance(
        requested, (list, tuple)
    ):
        reasons.append(
            _reason(
                "scope_collection_unverifiable",
                f"The reviewed or requested {label} set is unavailable.",
            )
        )
        return
    reviewed_set = {str(item) for item in reviewed}
    for item in requested:
        if str(item) not in reviewed_set:
            reasons.append(
                _reason(
                    code,
                    f"The writer references a {label} outside the reviewed scope.",
                    source=str(item),
                )
            )


def _indexed_records(
    value: Any,
    id_keys: tuple[str, ...],
    *,
    label: str,
    field_present: bool,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    reasons: list[dict[str, Any]] = []
    if not field_present:
        return {}, [
            _reason(
                f"{label}s_not_supplied",
                f"The {label} collection was not supplied.",
            )
        ]
    if not isinstance(value, (list, tuple)):
        return {}, [
            _reason(
                f"{label}s_invalid",
                f"The {label} collection must be a list.",
            )
        ]
    indexed: dict[str, str] = {}
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            reasons.append(
                _reason(
                    f"{label}_invalid",
                    f"A {label} record is not an object.",
                    index=index,
                )
            )
            continue
        identifier = _record_identifier(item, id_keys)
        declared_ids = {
            str(item.get(key)).strip()
            for key in id_keys
            if item.get(key) not in (None, "")
        }
        if len(declared_ids) > 1:
            reasons.append(
                _reason(
                    f"{label}_id_ambiguous",
                    f"A {label} record has conflicting identifier fields.",
                    identifiers=sorted(declared_ids),
                )
            )
            continue
        if not identifier:
            reasons.append(
                _reason(
                    f"{label}_id_missing",
                    f"A {label} record has no stable identifier.",
                    index=index,
                )
            )
            continue
        normalized = {
            str(key): child
            for key, child in item.items()
            if str(key) not in id_keys
        }
        normalized["scope_id"] = identifier
        fingerprint = _fingerprint(normalized)
        if identifier in indexed:
            reasons.append(
                _reason(
                    f"{label}_id_duplicate",
                    f"The {label} collection contains a duplicate identifier.",
                    identifier=identifier,
                )
            )
            continue
        indexed[identifier] = fingerprint
    return indexed, reasons


def _fingerprinted_collection(value: Any, id_keys: tuple[str, ...]) -> dict[str, str]:
    if not isinstance(value, (list, tuple)):
        return {}
    indexed: dict[str, str] = {}
    for item in value:
        if isinstance(item, Mapping):
            identifier = _record_identifier(item, id_keys)
            if identifier:
                normalized = {
                    str(key): child
                    for key, child in item.items()
                    if str(key) not in id_keys
                }
                normalized["scope_id"] = identifier
                fingerprint = _fingerprint(normalized)
            else:
                fingerprint = _fingerprint(item)
                identifier = f"anonymous:{fingerprint}"
        else:
            fingerprint = _fingerprint(item)
            identifier = f"anonymous:{fingerprint}"
        if identifier in indexed and indexed[identifier] != fingerprint:
            identifier = f"{identifier}:{fingerprint}"
        indexed[identifier] = fingerprint
    return indexed


def _source_file_versions(
    value: Mapping[str, Any],
    *,
    request_input: Mapping[str, Any],
    file_registry: Any,
) -> tuple[set[str], list[dict[str, Any]]]:
    versions: set[str] = set()
    file_ids: set[str] = set()
    document_ids: set[str] = set()
    explicit_versions: set[str] = set()

    def visit(item: Any, key: str = "") -> None:
        if isinstance(item, Mapping):
            for raw_key, child in item.items():
                child_key = str(raw_key)
                if child_key == "file_id" and isinstance(child, str):
                    if child.strip():
                        file_ids.add(child.strip())
                elif child_key in {"file_ids", "bidder_file_ids"}:
                    if isinstance(child, (list, tuple)):
                        file_ids.update(
                            str(entry).strip()
                            for entry in child
                            if str(entry).strip()
                        )
                    elif isinstance(child, str) and child.strip():
                        file_ids.add(child.strip())
                if child_key in {"source_version", "source_file_version"}:
                    if isinstance(child, str) and child.strip():
                        explicit_versions.add(child.strip())
                if child_key in {"document_id", "source_id"}:
                    if isinstance(child, str) and child.strip():
                        document_ids.add(child.strip())
                visit(child, child_key)
            document_id = str(
                item.get("document_id")
                or item.get("source_id")
                or ""
            ).strip()
            file_version = str(item.get("file_version") or "").strip()
            if document_id and file_version:
                explicit_versions.add(
                    f"source-ref:{document_id}:{file_version}"
                )
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child, key)

    visit({str(key): child for key, child in value.items() if str(key) != "plan"})
    request_file_keys = {
        "file_id",
        "file_ids",
        "bidder_file_ids",
        "source_file_ids",
        "bidder_source_file_ids",
    }
    request_sources = {
        str(key): child
        for key, child in request_input.items()
        if str(key) in request_file_keys
    }
    visit(request_sources)
    reasons: list[dict[str, Any]] = []
    getter = getattr(file_registry, "get", None)
    token_getter = getattr(file_registry, "file_version_token", None)
    for file_id in sorted(file_ids):
        if callable(token_getter):
            try:
                token = str(token_getter(file_id) or "")
            except Exception:
                token = ""
            if token:
                versions.add(token)
                continue
        if not any(
            version == file_id or version.startswith(f"{file_id}:v")
            for version in explicit_versions
        ):
            reasons.append(
                _reason(
                    "source_file_version_unavailable",
                    "A referenced source file has no verifiable version.",
                    file_id=file_id,
                )
            )
        else:
            versions.update(
                version
                for version in explicit_versions
                if version == file_id or version.startswith(f"{file_id}:v")
            )
    for document_id in sorted(document_ids - file_ids):
        registered = None
        if callable(getter):
            try:
                registered = getter(document_id)
            except Exception:
                registered = None
        if registered is not None and callable(token_getter):
            try:
                token = str(token_getter(document_id) or "")
            except Exception:
                token = ""
            if token:
                versions.add(token)
                continue
        matching_versions = {
            version
            for version in explicit_versions
            if version.startswith(f"{document_id}:v")
            or version.startswith(f"source-ref:{document_id}:")
        }
        if matching_versions:
            versions.update(matching_versions)
        elif registered is None:
            reasons.append(
                _reason(
                    "source_file_version_unavailable",
                    "A referenced source document has no verifiable version.",
                    document_id=document_id,
                )
            )
    for version in explicit_versions:
        if ":v" in version:
            versions.add(version)
        elif version not in file_ids:
            reasons.append(
                _reason(
                    "source_file_version_unavailable",
                    "A source version reference is not version-qualified.",
                    source_version=version,
                )
            )
    if file_ids and not callable(getter) and not explicit_versions:
        reasons.append(
            _reason(
                "file_registry_unavailable",
                "Referenced files need a registry token or an explicit version.",
            )
        )
    return versions, reasons


def _dependency_index(
    dependencies: list[dict[str, Any]],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    indexed: dict[str, str] = {}
    reasons: list[dict[str, Any]] = []
    for dependency in dependencies:
        if not isinstance(dependency, Mapping):
            reasons.append(
                _reason(
                    "artifact_dependency_unverifiable",
                    "An upstream artifact dependency is malformed.",
                )
            )
            continue
        artifact_id = str(dependency.get("artifact_id") or "").strip()
        fingerprint = str(dependency.get("fingerprint") or "").strip()
        if not artifact_id or not fingerprint:
            reasons.append(
                _reason(
                    "artifact_dependency_unverifiable",
                    "An upstream dependency has no stable ID or content fingerprint.",
                    artifact_id=artifact_id or None,
                )
            )
            continue
        indexed[artifact_id] = fingerprint
    return indexed, reasons


def _effective_project_id(
    value: Mapping[str, Any],
    request_input: Mapping[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    explicit = str(value.get("project_id") or "").strip()
    profile = value.get("tender_profile")
    profile_project = (
        str(profile.get("project_id") or "").strip()
        if isinstance(profile, Mapping)
        else ""
    )
    request_project = str(request_input.get("project_id") or "").strip()
    chosen = request_project or explicit or profile_project
    reasons: list[dict[str, Any]] = []
    for source, candidate in (
        ("step_input", explicit),
        ("tender_profile", profile_project),
        ("request", request_project),
    ):
        if candidate and chosen and candidate != chosen:
            reasons.append(
                _reason(
                    "project_mismatch",
                    "An explicit project scope conflicts with the run project.",
                    source=source,
                    expected_project_id=chosen,
                    actual_project_id=candidate,
                )
            )
    return chosen, reasons


def _record_identifier(item: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _catalog_id_collisions(value: Mapping[str, Any]) -> list[str]:
    requirements = value.get("requirements")
    scoring_items = value.get("scoring_items")
    if not isinstance(requirements, (list, tuple)) or not isinstance(
        scoring_items, (list, tuple)
    ):
        return []
    requirement_ids = {
        _record_identifier(item, _REQUIREMENT_ID_KEYS)
        for item in requirements
        if isinstance(item, Mapping)
    }
    scoring_ids = {
        _record_identifier(item, _SCORING_ID_KEYS)
        for item in scoring_items
        if isinstance(item, Mapping)
    }
    return sorted((requirement_ids & scoring_ids) - {""})


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return value
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(child) for child in value]
    if isinstance(value, set):
        normalized = [_canonical(child) for child in value]
        return sorted(normalized, key=_canonical_json)
    if isinstance(value, Decimal):
        return {"$decimal": str(value.normalize())}
    if isinstance(value, (datetime, date)):
        return {"$date": value.isoformat()}
    if isinstance(value, Enum):
        return _canonical(value.value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite number in scope")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported scope value: {type(value).__name__}")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _fingerprint(value: Any) -> str:
    try:
        serialized = _canonical_json(value)
    except (TypeError, ValueError):
        serialized = json.dumps(
            {"unverifiable_type": type(value).__name__},
            sort_keys=True,
            separators=(",", ":"),
        )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _reason(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **details}


def _unique_reasons(reasons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for reason in reasons:
        fingerprint = _fingerprint(reason)
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(reason)
    return unique
