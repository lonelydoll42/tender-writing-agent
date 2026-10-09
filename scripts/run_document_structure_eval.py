"""Run the public document-structure regression corpus through the real runtime."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qiaowenshu_agent.core.contracts import SkillRequest  # noqa: E402
from qiaowenshu_agent.core.files import ProjectFileRegistry  # noqa: E402
from qiaowenshu_agent.core.runtime import AgentRuntime  # noqa: E402
from qiaowenshu_agent.skills import build_default_registry  # noqa: E402


BUNDLE = ROOT / "benchmarks" / "document_structure"
FIXTURE_PATH = BUNDLE / "fixtures" / "cases.json"
V1_ORACLE_PATH = BUNDLE / "oracle" / "structure-oracle.json"
V1_FREEZE_PATH = BUNDLE / "freeze-manifest.json"
V2_ORACLE_PATH = BUNDLE / "oracle" / "structure-oracle-v2.json"
V2_FREEZE_PATH = BUNDLE / "freeze-manifest-v2.json"
ORACLE_PATH = BUNDLE / "oracle" / "structure-oracle-v3.json"
FREEZE_PATH = BUNDLE / "freeze-manifest-v3.json"
UPSTREAM_BUNDLE = ROOT / "benchmarks" / "raw_requirement_holdout"
UPSTREAM_FREEZE_PATH = UPSTREAM_BUNDLE / "freeze-manifest.json"
CASE_IDS = ("H01", "H05", "H08")
BOUNDARY = "\f"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _source_tree_sha256(root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    source_files = sorted(
        (root / "src").rglob("*.py"),
        key=lambda item: item.relative_to(root).as_posix(),
    )
    for path in source_files:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8") + b"\t")
        digest.update(bytes.fromhex(_sha256(path.read_bytes())) + b"\n")
    return digest.hexdigest()


def _git_metadata(root: Path = ROOT) -> dict[str, Any]:
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root.resolve():
        return {
            "repository_context": "archive/no_local_git_root",
            "git_revision_at_run": None,
            "git_worktree_dirty": None,
            "git_src_worktree_dirty": None,
            "git_src_worktree_status": None,
        }
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    all_status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    source_status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", "src"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "repository_context": "git_worktree",
        "git_revision_at_run": (
            revision.stdout.strip() if revision.returncode == 0 else None
        ),
        "git_worktree_dirty": (
            bool(all_status.stdout.strip()) if all_status.returncode == 0 else None
        ),
        "git_src_worktree_dirty": (
            bool(source_status.stdout.strip())
            if source_status.returncode == 0
            else None
        ),
        "git_src_worktree_status": (
            source_status.stdout.splitlines()
            if source_status.returncode == 0
            else None
        ),
    }


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def verify_freeze() -> dict[str, Any]:
    manifest = _load_json(FREEZE_PATH)
    fixture_index = _load_json(FIXTURE_PATH)
    oracle = _load_json(ORACLE_PATH)
    upstream = _load_json(UPSTREAM_FREEZE_PATH)

    indexed_cases = fixture_index.get("cases")
    oracle_cases = oracle.get("cases")
    if not isinstance(indexed_cases, list) or not isinstance(oracle_cases, list):
        raise ValueError("fixture index and oracle must contain case lists")
    if [case.get("case_id") for case in indexed_cases] != list(CASE_IDS):
        raise ValueError("public fixture cases must be exactly H01, H05, H08")
    if [case.get("case_id") for case in oracle_cases] != list(CASE_IDS):
        raise ValueError("structure oracle cases must be exactly H01, H05, H08")

    upstream_files = {
        item["path"]: item
        for item in upstream.get("inputs", {}).get("documents", [])
        if isinstance(item, Mapping)
    }
    fixture_sources = {
        item["source_path"]: item for item in indexed_cases if isinstance(item, Mapping)
    }
    if len(fixture_sources) != len(CASE_IDS):
        raise ValueError("fixture source paths must be unique")
    fixtures_by_id = {
        item["case_id"]: item for item in indexed_cases if isinstance(item, Mapping)
    }

    expected_source_entries = {
        item["path"]: item for item in manifest.get("source_files", [])
    }
    if set(expected_source_entries) != set(fixture_sources):
        raise ValueError("freeze manifest sources do not match the fixture index")
    for source_path, fixture in fixture_sources.items():
        relative_to_upstream = Path(source_path).relative_to(
            Path("benchmarks") / "raw_requirement_holdout"
        ).as_posix()
        upstream_entry = upstream_files.get(relative_to_upstream)
        frozen_entry = expected_source_entries[source_path]
        if (
            upstream_entry is None
            or fixture.get("source_sha256") != upstream_entry.get("sha256")
            or frozen_entry.get("sha256") != upstream_entry.get("sha256")
            or frozen_entry.get("bytes") != upstream_entry.get("bytes")
        ):
            raise ValueError(
                f"source does not match the upstream raw freeze: {source_path}"
            )

    assets = list(manifest.get("assets") or [])
    upstream_manifest = manifest.get("upstream_manifest")
    if not isinstance(upstream_manifest, Mapping):
        raise ValueError("upstream manifest reference is missing")
    entries = [*assets, upstream_manifest, *manifest.get("source_files", [])]
    checked: list[dict[str, Any]] = []
    for item in entries:
        relative = str(item.get("path") or "")
        path = (ROOT / relative).resolve()
        try:
            path.relative_to(ROOT.resolve())
        except ValueError as exc:
            raise ValueError(
                f"freeze path escapes repository root: {relative}"
            ) from exc
        if not path.is_file():
            raise ValueError(f"frozen file is missing: {relative}")
        content = path.read_bytes()
        actual_hash = _sha256(content)
        actual_bytes = len(content)
        if actual_hash != item.get("sha256") or actual_bytes != item.get("bytes"):
            raise ValueError(f"frozen file hash/size mismatch: {relative}")
        checked.append(
            {"path": relative, "bytes": actual_bytes, "sha256": actual_hash}
        )

    canonical = "".join(
        f"{item['path']}\t{item['sha256']}\n"
        for item in sorted(checked, key=lambda value: value["path"])
    ).encode("utf-8")
    fingerprint = _sha256(canonical)
    if fingerprint != manifest.get("bundle_fingerprint"):
        raise ValueError("public document-structure bundle fingerprint mismatch")

    for case in oracle_cases:
        fixture_case = fixtures_by_id.get(case.get("case_id"))
        if fixture_case is None:
            raise ValueError(
                f"oracle case has no fixture index entry: {case.get('case_id')}"
            )
        if case.get("case_id") != fixture_case.get("case_id"):
            raise ValueError("oracle case/source mapping mismatch")
        if len(case.get("pages") or []) != fixture_case.get("expected_pages"):
            raise ValueError(f"oracle page count mismatch for {case['case_id']}")

    return {
        "valid": True,
        "bundle_fingerprint": fingerprint,
        "source_files": len(manifest.get("source_files", [])),
        "oracle_files": 1,
        "fixture_index_files": 1,
        "upstream_manifest_files": 1,
        "files": checked,
    }


def _physical_lines(page_text: str) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    position = 0
    line_number = 1
    while position < len(page_text):
        raw_end = position
        while raw_end < len(page_text) and page_text[raw_end] not in "\r\n":
            raw_end += 1
        if raw_end == len(page_text):
            line_ending = ""
            next_position = raw_end
        elif page_text.startswith("\r\n", raw_end):
            line_ending = "\r\n"
            next_position = raw_end + 2
        else:
            line_ending = page_text[raw_end]
            next_position = raw_end + 1
        lines.append(
            {
                "line_number": line_number,
                "start": position,
                "end": raw_end,
                "raw_text": page_text[position:raw_end],
                "line_ending": line_ending,
            }
        )
        line_number += 1
        position = next_position
    return lines


def _expanded_oracle(
    oracle_case: Mapping[str, Any], raw_pages: list[str]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    oracle_pages = oracle_case.get("pages")
    if not isinstance(oracle_pages, list) or len(oracle_pages) != len(raw_pages):
        raise ValueError(
            f"oracle/source page count mismatch: {oracle_case.get('case_id')}"
        )
    for page_text, oracle_page in zip(raw_pages, oracle_pages, strict=True):
        page_number = int(oracle_page["page_number"])
        physical_lines = _physical_lines(page_text)
        expected_lines = oracle_page.get("blocks")
        if not isinstance(expected_lines, list) or len(expected_lines) != len(
            physical_lines
        ):
            raise ValueError(
                f"oracle physical-line coverage mismatch for "
                f"{oracle_case.get('case_id')} page {page_number}"
            )
        for physical, expectation in zip(physical_lines, expected_lines, strict=True):
            if int(expectation.get("line", -1)) != physical["line_number"]:
                raise ValueError("oracle line numbers must cover every physical line")
            result.append(
                {
                    **dict(expectation),
                    "page_number": page_number,
                    "locator": f"p{page_number}l{physical['line_number']}",
                    "source_span": {
                        "page_number": page_number,
                        "start": physical["start"],
                        "end": physical["end"],
                    },
                    "raw_text": physical["raw_text"],
                    "line_ending": physical["line_ending"],
                }
            )
    return result


def _field_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        converted = converter()
        return converted if isinstance(converted, Mapping) else None
    return None


def _output_item_ids(
    data: Mapping[str, Any],
    collection_name: str,
    id_fields: tuple[str, ...],
) -> list[str] | None:
    items = data.get(collection_name)
    if not isinstance(items, list):
        return None
    identifiers: list[str] = []
    for item in items:
        item_mapping = _field_mapping(item)
        if item_mapping is None:
            return None
        identifier = next(
            (
                item_mapping.get(field)
                for field in id_fields
                if item_mapping.get(field) is not None
            ),
            None,
        )
        if not isinstance(identifier, str) or not identifier:
            return None
        identifiers.append(identifier)
    return identifiers


def _decomposition_output_ids(
    data: Mapping[str, Any],
) -> dict[str, list[str]] | None:
    requirement_ids = _output_item_ids(
        data,
        "requirements",
        ("requirement_id", "id"),
    )
    scoring_item_ids = _output_item_ids(
        data,
        "scoring_items",
        ("scoring_item_id", "item_id", "id"),
    )
    if requirement_ids is None or scoring_item_ids is None:
        return None
    return {
        "requirement_ids": requirement_ids,
        "scoring_item_ids": scoring_item_ids,
    }


def _document_structures(data: Any) -> list[dict[str, Any]]:
    mapping = _field_mapping(data)
    if mapping is None:
        return []
    result: list[dict[str, Any]] = []
    for key in ("document_structures", "document_structure"):
        value = mapping.get(key)
        if isinstance(value, Mapping):
            result.append(dict(value))
        elif isinstance(value, list):
            result.extend(dict(item) for item in value if isinstance(item, Mapping))
    for section in mapping.get("sections") or []:
        section_mapping = _field_mapping(section)
        if section_mapping is None:
            continue
        value = section_mapping.get("document_structure")
        if isinstance(value, Mapping):
            result.append(dict(value))
        elif isinstance(value, list):
            result.extend(dict(item) for item in value if isinstance(item, Mapping))
    return result


def _step_values(run_result: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for step in getattr(run_result, "steps", []) or []:
        result = getattr(step, "result", None)
        data = getattr(result, "data", None)
        data_mapping = _field_mapping(data)
        output.append(
            {
                "skill_name": str(getattr(step, "skill_name", "")),
                "status": str(getattr(result, "status", "not_run")),
                "data": dict(data_mapping) if data_mapping is not None else None,
            }
        )
    return output


def _find_step(
    steps: list[dict[str, Any]], skill_name: str
) -> dict[str, Any] | None:
    matches = [step for step in steps if step["skill_name"] == skill_name]
    return matches[-1] if matches else None


def _structure_pages(structure: Mapping[str, Any]) -> list[dict[str, Any]]:
    pages = structure.get("pages")
    if not isinstance(pages, list):
        return []
    return [dict(page) for page in pages if isinstance(page, Mapping)]


def _structure_page_text(page: Mapping[str, Any]) -> str | None:
    for key in ("raw_text", "text"):
        value = page.get(key)
        if isinstance(value, str):
            return value
    return None


def _source_span(block: Mapping[str, Any]) -> tuple[int, int, int] | None:
    span = block.get("source_span")
    if not isinstance(span, Mapping):
        return None
    try:
        page_number = int(span.get("page_number") or block.get("page_number"))
        start = int(span["start"])
        end = int(span["end"])
    except (KeyError, TypeError, ValueError):
        return None
    return page_number, start, end


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _collapse_whitespace_preserving_edges(value: str) -> str:
    return re.sub(r"\s+", " ", value)


def _path_tokens(label_path: Any) -> list[str] | None:
    if not isinstance(label_path, list):
        return None
    tokens: list[str] = []
    for label in label_path:
        if not isinstance(label, str):
            return None
        segment = label.strip()
        if (
            len(segment) >= 3
            and segment.startswith("（")
            and segment.endswith("）")
        ) or (
            len(segment) >= 3
            and segment.startswith("(")
            and segment.endswith(")")
        ):
            tokens.append(segment[1:-1])
        elif "." in segment:
            tokens.append(segment.rstrip(".").rsplit(".", 1)[-1])
        else:
            tokens.append(segment.rstrip("."))
    return tokens


def _normalization_map_errors(
    block: Mapping[str, Any],
    *,
    page_text: str,
    expected_page: int,
) -> list[str]:
    errors: list[str] = []
    normalized = block.get("normalized_text")
    raw_text = block.get("raw_text")
    span = _source_span(block)
    if not isinstance(normalized, str) or not isinstance(raw_text, str) or span is None:
        return ["missing normalized_text, raw_text, or source_span"]
    page_number, block_start, block_end = span
    if page_number != expected_page or block_end - block_start != len(raw_text):
        return ["normalization coordinates do not match source_span"]
    if (
        block_start < 0
        or block_end > len(page_text)
        or page_text[block_start:block_end] != raw_text
    ):
        return ["source_span does not resolve to the exact raw_text"]
    segments = block.get("normalization_map")
    if not isinstance(segments, list):
        return ["normalization_map is not a list"]
    if normalized and not segments:
        return ["normalization_map is empty for non-empty normalized_text"]
    allowed_normalizations = {
        raw_text,
        _collapse_whitespace_preserving_edges(raw_text),
        _collapse_whitespace(raw_text),
    }
    if normalized not in allowed_normalizations:
        errors.append("normalized_text changes non-whitespace source characters")

    normalized_cursor = 0
    previous_raw_end = block_start
    covered_source = [False] * len(raw_text)
    for segment in segments:
        if not isinstance(segment, Mapping):
            errors.append("normalization_map segment is not an object")
            continue
        try:
            norm_start = int(segment["normalized_start"])
            norm_end = int(segment["normalized_end"])
            raw_start = int(segment["raw_start"])
            raw_end = int(segment["raw_end"])
        except (KeyError, TypeError, ValueError):
            errors.append("normalization_map segment has invalid coordinates")
            continue
        if (
            norm_start != normalized_cursor
            or norm_end <= norm_start
            or norm_end > len(normalized)
            or raw_start < block_start
            or raw_end <= raw_start
            or raw_end > block_end
            or raw_start < previous_raw_end
        ):
            errors.append("normalization_map has a gap, overlap, or out-of-range span")
            continue
        normalized_slice = normalized[norm_start:norm_end]
        raw_slice = page_text[raw_start:raw_end]
        local_start = raw_start - block_start
        local_end = raw_end - block_start
        identity_mapping = (
            normalized_slice == raw_slice
            and len(normalized_slice) == len(raw_slice)
        )
        whitespace_run_mapping = (
            normalized_slice == " "
            and bool(raw_slice)
            and all(character.isspace() for character in raw_slice)
            and (local_start == 0 or not raw_text[local_start - 1].isspace())
            and (
                local_end == len(raw_text)
                or not raw_text[local_end].isspace()
            )
        )
        if not identity_mapping and not whitespace_run_mapping:
            errors.append("normalized text is not traceable to its source interval")
        for index in range(local_start, local_end):
            covered_source[index] = True
        normalized_cursor = norm_end
        previous_raw_end = raw_end

    if normalized_cursor != len(normalized):
        errors.append("normalization_map does not cover every normalized character")
    for index, character in enumerate(raw_text):
        if not character.isspace() and not covered_source[index]:
            errors.append("a non-whitespace source character is unmapped")
            break
    return errors


def _source_reference_errors(
    block: Mapping[str, Any],
    *,
    page_text: str,
    page_number: int,
    document_id: str,
    source_version: str,
) -> list[str]:
    raw_text = block.get("raw_text")
    if not isinstance(raw_text, str) or not raw_text:
        return []
    span = _source_span(block)
    references = block.get("source_references")
    if span is None or not isinstance(references, list) or not references:
        return ["non-empty physical block has no source reference"]
    _, start, end = span
    errors: list[str] = []
    for reference in references:
        if not isinstance(reference, Mapping):
            errors.append("source reference is not an object")
            continue
        try:
            ref_page = int(reference.get("page") or reference.get("page_number"))
            char_start = int(reference["char_start"])
            char_end = int(reference["char_end"])
        except (KeyError, TypeError, ValueError):
            errors.append("source reference has no page/character span")
            continue
        quote = str(reference.get("quote") or "")
        if (
            reference.get("document_id") != document_id
            or reference.get("source_version") != source_version
            or ref_page != page_number
            or char_start != start
            or char_end != end
            or char_start < 0
            or char_end > len(page_text)
            or not quote
            or page_text[char_start:char_end] != quote
            or quote != raw_text
        ):
            errors.append("source reference does not resolve to this exact page span")
    return errors


def _reference_key(reference: Any) -> tuple[Any, ...] | None:
    if not isinstance(reference, Mapping):
        return None
    try:
        page_number = int(reference.get("page") or reference["page_number"])
        char_start = int(reference["char_start"])
        char_end = int(reference["char_end"])
    except (KeyError, TypeError, ValueError):
        return None
    document_id = reference.get("document_id")
    source_version = reference.get("source_version")
    quote = reference.get("quote")
    if (
        not isinstance(document_id, str)
        or not isinstance(source_version, str)
        or not isinstance(quote, str)
        or char_start < 0
        or char_end <= char_start
        or not quote
    ):
        return None
    return document_id, source_version, page_number, char_start, char_end, quote


def _evaluate_continuation_candidates(
    *,
    expected_candidates: list[Mapping[str, Any]],
    structure: Mapping[str, Any],
    matched_by_locator: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    actual_candidates = structure.get("continuation_candidates")
    if not isinstance(actual_candidates, list):
        actual_candidates = []
    failures: list[dict[str, Any]] = []
    consumed: set[int] = set()

    for expected in expected_candidates:
        locator = str(expected.get("locator") or "unknown-locator")
        review = expected.get("review")
        preceding_locator = (
            str(review.get("candidate_parent") or "")
            if isinstance(review, Mapping)
            else ""
        )
        preceding = matched_by_locator.get(preceding_locator)
        current = matched_by_locator.get(locator)
        expected_ids = [
            str(block.get("block_id") or "")
            for block in (preceding, current)
            if isinstance(block, Mapping)
        ]
        matches = [
            (index, candidate)
            for index, candidate in enumerate(actual_candidates)
            if isinstance(candidate, Mapping)
            and candidate.get("source_block_ids") == expected_ids
        ]
        failure_reasons: list[str] = []
        if len(expected_ids) != 2 or not all(expected_ids):
            failure_reasons.append("expected preceding/current blocks are unavailable")
        if len(matches) != 1:
            failure_reasons.append(
                "global candidate does not match exact ordered block IDs"
            )
        else:
            index, candidate = matches[0]
            consumed.add(index)
            if candidate.get("status") != "needs_review":
                failure_reasons.append("global candidate status is not needs_review")
            if isinstance(current, Mapping):
                for field in ("parent_block_id", "section_block_id"):
                    if current.get(field) is not None:
                        failure_reasons.append(
                            f"uncertain continuation block asserts {field}"
                        )

            expected_references: list[tuple[Any, ...]] = []
            references_complete = True
            for block in (preceding, current):
                block_references = (
                    block.get("source_references")
                    if isinstance(block, Mapping)
                    else None
                )
                if not isinstance(block_references, list) or not block_references:
                    references_complete = False
                    continue
                for reference in block_references:
                    key = _reference_key(reference)
                    if key is None:
                        references_complete = False
                    else:
                        expected_references.append(key)

            candidate_references = candidate.get("source_references")
            actual_reference_keys = (
                [_reference_key(reference) for reference in candidate_references]
                if isinstance(candidate_references, list)
                else []
            )
            if (
                not references_complete
                or not actual_reference_keys
                or any(key is None for key in actual_reference_keys)
                or actual_reference_keys != expected_references
            ):
                failure_reasons.append(
                    "global candidate source references do not resolve to both blocks"
                )

        if failure_reasons:
            failures.append(
                {
                    "locator": locator,
                    "expected_source_block_ids": expected_ids,
                    "failure_reasons": failure_reasons,
                }
            )

    unexpected = [
        {
            "candidate_id": (
                candidate.get("candidate_id")
                if isinstance(candidate, Mapping)
                else None
            ),
            "source_block_ids": (
                candidate.get("source_block_ids")
                if isinstance(candidate, Mapping)
                else None
            ),
        }
        for index, candidate in enumerate(actual_candidates)
        if index not in consumed
    ]
    return {
        "status": "measured" if expected_candidates else "not_run",
        "denominator": len(expected_candidates),
        "failure_count": len(failures) + len(unexpected),
        "failures": failures,
        "unexpected_candidate_count": len(unexpected),
        "unexpected_candidates": unexpected,
    }


def _evaluate_table_grouping(
    *,
    expected: list[Mapping[str, Any]],
    matched_by_locator: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    rows = [item for item in expected if item.get("kind") == "table_row"]
    if not rows:
        return {
            "status": "not_run",
            "denominator": 0,
            "mismatch_count": 0,
            "unsupported_count": 0,
            "failure_count": 0,
            "mismatches": [],
            "unsupported": [],
        }

    row_indexes: dict[str, int] = {}
    mismatches: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    for item in rows:
        locator = str(item.get("locator") or "unknown-locator")
        anchor_locator = item.get("table_group")
        if not isinstance(anchor_locator, str) or not anchor_locator:
            unsupported.append(
                {"locator": locator, "reason": "oracle has no table_group anchor"}
            )
            continue
        expected_index = row_indexes.get(anchor_locator, 1)
        row_indexes[anchor_locator] = expected_index + 1
        actual = matched_by_locator.get(locator)
        anchor = matched_by_locator.get(anchor_locator)
        if not isinstance(actual, Mapping) or not isinstance(anchor, Mapping):
            unsupported.append(
                {
                    "locator": locator,
                    "reason": "table row or anchor block is unavailable",
                    "anchor_locator": anchor_locator,
                }
            )
            continue

        expected_group_id = anchor.get("block_id")
        actual_group_id = actual.get("table_group_id")
        actual_index = actual.get("table_row_index")
        if not isinstance(expected_group_id, str) or not expected_group_id:
            unsupported.append(
                {
                    "locator": locator,
                    "reason": "table anchor has no physical block_id",
                    "anchor_locator": anchor_locator,
                }
            )
            continue
        if (
            not isinstance(actual_group_id, str)
            or isinstance(actual_index, bool)
            or not isinstance(actual_index, int)
        ):
            unsupported.append(
                {
                    "locator": locator,
                    "reason": "table_group_id or one-based table_row_index is missing",
                    "actual_table_group_id": actual_group_id,
                    "actual_table_row_index": actual_index,
                }
            )
            continue
        if (
            actual_group_id != expected_group_id
            or actual_index != expected_index
        ):
            mismatches.append(
                {
                    "locator": locator,
                    "expected_table_group_id": expected_group_id,
                    "actual_table_group_id": actual_group_id,
                    "expected_table_row_index": expected_index,
                    "actual_table_row_index": actual_index,
                }
            )

    return {
        "status": "unsupported" if unsupported else "measured",
        "denominator": len(rows),
        "mismatch_count": len(mismatches),
        "unsupported_count": len(unsupported),
        "failure_count": len(mismatches) + len(unsupported),
        "mismatches": mismatches,
        "unsupported": unsupported,
    }


def _table_cell_ranges(raw_text: str) -> list[tuple[int, int, str]] | None:
    pipes = [
        index
        for index, character in enumerate(raw_text)
        if character == "|"
        and (
            len(raw_text[:index]) - len(raw_text[:index].rstrip("\\"))
        )
        % 2
        == 0
    ]
    if not pipes:
        return None

    cells: list[tuple[int, int, str]] = []
    starts_after_outer_pipe = not raw_text[: pipes[0]].strip()
    ends_at_outer_pipe = not raw_text[pipes[-1] + 1 :].strip()
    cursor = pipes[0] + 1 if starts_after_outer_pipe else 0
    for pipe_index in pipes[1:]:
        cells.append((cursor, pipe_index, raw_text[cursor:pipe_index]))
        cursor = pipe_index + 1
    if not ends_at_outer_pipe:
        cells.append((cursor, len(raw_text), raw_text[cursor:]))
    return cells


def _evaluate_table_cell_spans(
    *,
    expected: list[Mapping[str, Any]],
    matched_by_locator: Mapping[str, Mapping[str, Any]],
    raw_pages: list[str],
) -> dict[str, Any]:
    rows = [item for item in expected if item.get("kind") == "table_row"]
    expected_cell_count = 0
    failures: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    for item in rows:
        locator = str(item.get("locator") or "unknown-locator")
        expected_cells = _table_cell_ranges(str(item.get("raw_text") or ""))
        if expected_cells is None:
            unsupported.append(
                {
                    "locator": locator,
                    "reason": "table row has no parseable cell separators",
                }
            )
            continue
        expected_cell_count += len(expected_cells)
        block = matched_by_locator.get(locator)
        span = _source_span(block) if isinstance(block, Mapping) else None
        actual_cells = block.get("cell_spans") if isinstance(block, Mapping) else None
        if span is None or not isinstance(actual_cells, list):
            unsupported.append(
                {
                    "locator": locator,
                    "expected_cell_count": len(expected_cells),
                    "reason": "table row source_span or cell_spans is missing",
                }
            )
            continue

        page_number, row_start, row_end = span
        if not 1 <= page_number <= len(raw_pages):
            unsupported.append(
                {
                    "locator": locator,
                    "expected_cell_count": len(expected_cells),
                    "reason": "table row page is unavailable",
                }
            )
            continue
        page_text = raw_pages[page_number - 1]
        for index, (local_start, local_end, expected_text) in enumerate(
            expected_cells,
            start=1,
        ):
            if index > len(actual_cells):
                unsupported.append(
                    {
                        "locator": locator,
                        "cell_index": index,
                        "reason": "expected cell span is missing",
                    }
                )
                continue
            cell = actual_cells[index - 1]
            if not isinstance(cell, Mapping):
                unsupported.append(
                    {
                        "locator": locator,
                        "cell_index": index,
                        "reason": "cell span is not an object",
                    }
                )
                continue
            try:
                cell_start = int(cell["start"])
                cell_end = int(cell["end"])
            except (KeyError, TypeError, ValueError):
                unsupported.append(
                    {
                        "locator": locator,
                        "cell_index": index,
                        "reason": "cell span has invalid coordinates",
                    }
                )
                continue
            expected_start = row_start + local_start
            expected_end = row_start + local_end
            source_text = (
                page_text[cell_start:cell_end]
                if row_start <= cell_start <= cell_end <= row_end
                else None
            )
            if (
                not row_start <= cell_start <= cell_end <= row_end
                or cell_start != expected_start
                or cell_end != expected_end
                or cell.get("raw_text") != expected_text
                or source_text != expected_text
            ):
                failures.append(
                    {
                        "locator": locator,
                        "cell_index": index,
                        "expected_span": {
                            "start": expected_start,
                            "end": expected_end,
                            "raw_text": expected_text,
                        },
                        "actual_span": {
                            "start": cell_start,
                            "end": cell_end,
                            "raw_text": cell.get("raw_text"),
                            "resolved_source_text": source_text,
                        },
                    }
                )
        for index in range(len(expected_cells) + 1, len(actual_cells) + 1):
            failures.append(
                {
                    "locator": locator,
                    "cell_index": index,
                    "reason": "unexpected extra cell span",
                }
            )

    unsupported_count = sum(
        int(item.get("expected_cell_count", 1)) for item in unsupported
    )
    return {
        "status": "unsupported" if unsupported else "measured",
        "row_denominator": len(rows),
        "denominator": expected_cell_count,
        "failure_count": len(failures) + unsupported_count,
        "mismatch_count": len(failures),
        "unsupported_count": unsupported_count,
        "failures": failures,
        "unsupported": unsupported,
    }


def _evaluate_ambiguous_candidate_field(
    *,
    field_name: str,
    expected: list[Mapping[str, Any]],
    actual_by_locator: Mapping[str, list[Mapping[str, Any]]],
    global_candidates: Any = None,
    reference_errors_by_locator: Mapping[str, list[str]] | None = None,
) -> dict[str, Any]:
    expected_items = [
        item for item in expected if isinstance(item.get(field_name), Mapping)
    ]
    expected_by_locator = {
        str(item.get("locator") or ""): item for item in expected_items
    }
    global_candidate_list = (
        global_candidates if isinstance(global_candidates, list) else []
    )
    failures: list[dict[str, Any]] = []
    consumed_global_candidates: set[int] = set()
    for locator, item in expected_by_locator.items():
        matches = actual_by_locator.get(locator, [])
        if len(matches) != 1:
            failures.append(
                {
                    "locator": locator,
                    "reason": "candidate source block is missing or duplicated",
                }
            )
            continue
        block = matches[0]
        if global_candidates is None:
            candidate = block.get(field_name)
        else:
            block_id = block.get("block_id")
            matching_candidates = [
                (index, candidate)
                for index, candidate in enumerate(global_candidate_list)
                if isinstance(candidate, Mapping)
                and candidate.get("block_id") == block_id
            ]
            if len(matching_candidates) != 1:
                failures.append(
                    {
                        "locator": locator,
                        "reason": (
                            "global candidate does not uniquely identify the "
                            "expected source block"
                        ),
                    }
                )
                continue
            candidate_index, candidate = matching_candidates[0]
            consumed_global_candidates.add(candidate_index)

        reasons: list[str] = []
        if (
            field_name == "heading_candidate"
            and global_candidates is None
        ):
            if block.get(field_name) is not True:
                reasons.append("local heading_candidate is not true")
            if (
                block.get("kind_ambiguity")
                != "decimal_heading_or_numbered_clause"
            ):
                reasons.append("local heading ambiguity marker is missing or invalid")
            block_references = block.get("source_references")
            if (
                not isinstance(block_references, list)
                or not block_references
                or any(
                    not isinstance(reference, Mapping)
                    or _reference_key(reference) is None
                    for reference in block_references
                )
            ):
                reasons.append("source block has no valid source references")
            if (reference_errors_by_locator or {}).get(locator):
                reasons.append("source block references do not resolve exactly")
            if reasons:
                failures.append(
                    {"locator": locator, "failure_reasons": reasons}
                )
            continue

        if not isinstance(candidate, Mapping):
            reasons.append("candidate object is missing")
        else:
            if candidate.get("status") != "ambiguous":
                reasons.append("candidate status is not ambiguous")
            if (
                global_candidates is not None
                and candidate.get("candidate_kind")
                not in {
                    "title",
                    "document_title",
                }
            ):
                reasons.append("global candidate kind does not match its oracle field")
            block_id = block.get("block_id")
            candidate_block_ids = candidate.get("source_block_ids")
            candidate_block_id = candidate.get("source_block_id")
            if candidate_block_ids is not None and candidate_block_ids != [block_id]:
                reasons.append("candidate source_block_ids do not identify this block")
            if candidate_block_id is not None and candidate_block_id != block_id:
                reasons.append("candidate source_block_id does not identify this block")

            block_references = block.get("source_references")
            candidate_references = candidate.get("source_references")
            expected_reference_keys = (
                [_reference_key(reference) for reference in block_references]
                if isinstance(block_references, list)
                else []
            )
            actual_reference_keys = (
                [_reference_key(reference) for reference in candidate_references]
                if isinstance(candidate_references, list)
                else []
            )
            if (
                not expected_reference_keys
                or any(key is None for key in expected_reference_keys)
                or not actual_reference_keys
                or any(key is None for key in actual_reference_keys)
                or actual_reference_keys != expected_reference_keys
            ):
                reasons.append(
                    "candidate source references do not match the exact source block"
                )
        if reasons:
            failures.append(
                {"locator": locator, "failure_reasons": reasons}
            )

    if global_candidates is None:
        unexpected = [
            locator
            for locator, blocks in actual_by_locator.items()
            if locator not in expected_by_locator
            and any(
                block.get(field_name) is not None
                or (
                    field_name == "heading_candidate"
                    and block.get("kind_ambiguity") is not None
                )
                for block in blocks
            )
        ]
    else:
        unexpected = [
            index
            for index in range(len(global_candidate_list))
            if index not in consumed_global_candidates
        ]
        if not isinstance(global_candidates, list) and expected_items:
            unexpected.append("candidate list is not a list")
    return {
        "status": "measured" if expected_items else "not_run",
        "denominator": len(expected_items),
        "failure_count": len(failures) + len(unexpected),
        "failures": failures,
        "unexpected_candidates": unexpected,
    }


def _projection_stage_result(
    *,
    stage: Any,
    stage_name: str,
    expected_block_ids: list[str],
    ignored_synthetic_block_ids: set[str],
    allowed_dispositions: set[str],
) -> dict[str, Any]:
    records = stage.get("blocks") if isinstance(stage, Mapping) else None
    unsupported: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    stage_status = stage.get("status") if isinstance(stage, Mapping) else None
    normalized_stage_status = str(stage_status or "").lower()
    successful_stage_status = (
        normalized_stage_status
        in {"success", "succeeded", "passed", "complete", "completed"}
        or (
            normalized_stage_status.startswith("executed_")
            and not any(
                token in normalized_stage_status
                for token in ("fail", "error", "partial", "not_run")
            )
        )
    )
    stage_status_failure_count = int(
        stage_status is not None and not successful_stage_status
    )
    stage_errors = (
        [
            {
                "reason": "projection stage did not report a successful status",
                "stage_status": stage_status,
            }
        ]
        if stage_status_failure_count
        else []
    )
    if not isinstance(records, list):
        records = []

    expected_counts = {
        block_id: expected_block_ids.count(block_id) for block_id in expected_block_ids
    }
    actual_by_id: dict[str, list[Mapping[str, Any]]] = {}
    unexpected_records: list[Any] = []
    ignored_synthetic_count = 0
    for record in records:
        if not isinstance(record, Mapping):
            unexpected_records.append(record)
            continue
        block_id = record.get("block_id")
        if not isinstance(block_id, str) or not block_id:
            unexpected_records.append(record)
            continue
        if block_id in ignored_synthetic_block_ids:
            ignored_synthetic_count += 1
            continue
        if block_id not in expected_counts:
            unexpected_records.append({"block_id": block_id})
            continue
        actual_by_id.setdefault(block_id, []).append(record)

    missing_ids = [
        block_id for block_id in expected_counts if block_id not in actual_by_id
    ]
    duplicate_ids = [
        block_id
        for block_id, block_records in actual_by_id.items()
        if len(block_records) != 1
    ]
    duplicate_source_ids = [
        block_id for block_id, count in expected_counts.items() if count != 1
    ]
    if missing_ids:
        unsupported.append(
            {"reason": "original blocks have no disposition", "block_ids": missing_ids}
        )
    if duplicate_ids:
        mismatches.append(
            {
                "reason": "original blocks have more than one disposition",
                "block_ids": duplicate_ids,
            }
        )
    if duplicate_source_ids:
        unsupported.append(
            {
                "reason": "source structure has missing or duplicate block IDs",
                "block_ids": duplicate_source_ids,
            }
        )
    if unexpected_records:
        mismatches.append(
            {
                "reason": "audit contains records outside the original block set",
                "records": unexpected_records,
            }
        )

    for block_id, block_records in actual_by_id.items():
        if len(block_records) != 1:
            continue
        record = block_records[0]
        disposition = record.get("disposition") or record.get("projection_status")
        if not isinstance(disposition, str) or disposition not in allowed_dispositions:
            unsupported.append(
                {
                    "reason": "unknown or missing disposition",
                    "block_id": block_id,
                    "disposition": disposition,
                }
            )
            continue
        if disposition == "filtered":
            reason = record.get("filter_reason") or record.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                unsupported.append(
                    {
                        "reason": "filtered disposition has no filter reason",
                        "block_id": block_id,
                    }
                )

    if not expected_block_ids:
        unsupported.append({"reason": "original block ID set is unavailable"})
    mismatch_count = sum(
        len(item.get("block_ids") or item.get("records") or [item])
        for item in mismatches
    )
    unsupported_count = sum(
        len(item.get("block_ids") or [item]) for item in unsupported
    )
    return {
        "stage": stage_name,
        "stage_status": stage_status,
        "stage_status_failure_count": stage_status_failure_count,
        "status": (
            "unsupported"
            if unsupported or stage_errors
            else "measured"
        ),
        "denominator": len(expected_block_ids),
        "record_count": len(records),
        "ignored_synthetic_block_record_count": ignored_synthetic_count,
        "missing_count": len(missing_ids),
        "duplicate_count": len(duplicate_ids),
        "mismatch_count": mismatch_count,
        "unsupported_count": unsupported_count,
        "failure_count": (
            mismatch_count + unsupported_count + stage_status_failure_count
        ),
        "mismatches": mismatches,
        "unsupported": unsupported,
        "stage_errors": stage_errors,
    }


def _candidate_projection_mapping_result(
    *,
    stage: Any,
    expected_block_ids: list[str],
    ignored_synthetic_block_ids: set[str],
) -> dict[str, Any]:
    result = _projection_stage_result(
        stage=stage,
        stage_name="candidate_projection",
        expected_block_ids=expected_block_ids,
        ignored_synthetic_block_ids=ignored_synthetic_block_ids,
        allowed_dispositions={"candidate", "filtered"},
    )
    stage_mapping = stage if isinstance(stage, Mapping) else {}
    records = stage_mapping.get("blocks")
    candidates = stage_mapping.get("candidates")
    records = records if isinstance(records, list) else []
    candidates = candidates if isinstance(candidates, list) else []
    expected_ids = set(expected_block_ids)
    records_by_id: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        block_id = record.get("block_id")
        if (
            isinstance(block_id, str)
            and block_id in expected_ids
            and block_id not in ignored_synthetic_block_ids
        ):
            records_by_id.setdefault(block_id, []).append(record)

    candidate_blocks: dict[str, list[str]] = {}
    filtered_count = 0
    mapping_mismatches: list[dict[str, Any]] = []
    mapping_unsupported: list[dict[str, Any]] = []
    for block_id, block_records in records_by_id.items():
        if len(block_records) != 1:
            continue
        record = block_records[0]
        disposition = record.get("projection_status")
        candidate_ids = record.get("candidate_ids")
        if (
            not isinstance(candidate_ids, list)
            or any(not isinstance(value, str) or not value for value in candidate_ids)
        ):
            mapping_unsupported.append(
                {
                    "reason": "candidate_ids must be a list of non-empty IDs",
                    "block_id": block_id,
                }
            )
            continue
        if len(set(candidate_ids)) != len(candidate_ids):
            mapping_mismatches.append(
                {"reason": "block repeats a candidate ID", "block_id": block_id}
            )
        if record.get("participated") is not (disposition == "candidate"):
            mapping_mismatches.append(
                {
                    "reason": "participated flag disagrees with projection status",
                    "block_id": block_id,
                    "projection_status": disposition,
                    "participated": record.get("participated"),
                }
            )
        if disposition == "filtered":
            filtered_count += 1
            if candidate_ids:
                mapping_mismatches.append(
                    {
                        "reason": "filtered block maps to candidates",
                        "block_id": block_id,
                        "candidate_ids": candidate_ids,
                    }
                )
            continue
        if disposition != "candidate":
            continue
        if not candidate_ids:
            mapping_unsupported.append(
                {
                    "reason": "candidate projection has no candidate IDs",
                    "block_id": block_id,
                }
            )
            continue
        for candidate_id in candidate_ids:
            candidate_blocks.setdefault(candidate_id, []).append(block_id)

    candidate_records: dict[str, Mapping[str, Any]] = {}
    duplicate_candidate_ids: list[str] = []
    unexpected_candidates: list[Any] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            unexpected_candidates.append(candidate)
            continue
        candidate_id = candidate.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            unexpected_candidates.append(candidate)
        elif candidate_id in candidate_records:
            duplicate_candidate_ids.append(candidate_id)
        else:
            candidate_records[candidate_id] = candidate

    missing_candidate_ids = sorted(set(candidate_blocks) - set(candidate_records))
    extra_candidate_ids = sorted(set(candidate_records) - set(candidate_blocks))
    if missing_candidate_ids:
        mapping_unsupported.append(
            {
                "reason": "projected candidate ID has no candidate record",
                "candidate_ids": missing_candidate_ids,
            }
        )
    if duplicate_candidate_ids:
        mapping_mismatches.append(
            {
                "reason": "candidate IDs are duplicated",
                "candidate_ids": duplicate_candidate_ids,
            }
        )
    if extra_candidate_ids or unexpected_candidates:
        mapping_mismatches.append(
            {
                "reason": "candidate records do not map to projected source blocks",
                "candidate_ids": extra_candidate_ids,
                "records": unexpected_candidates,
            }
        )

    for candidate_id in set(candidate_blocks) & set(candidate_records):
        expected_source_ids = candidate_blocks[candidate_id]
        candidate = candidate_records[candidate_id]
        source_ids = candidate.get("source_block_ids")
        if (
            not isinstance(source_ids, list)
            or any(not isinstance(value, str) or not value for value in source_ids)
            or len(set(source_ids)) != len(source_ids)
            or set(source_ids) != set(expected_source_ids)
        ):
            mapping_mismatches.append(
                {
                    "reason": "candidate source_block_ids disagree with block mapping",
                    "candidate_id": candidate_id,
                    "expected_source_block_ids": sorted(expected_source_ids),
                    "actual_source_block_ids": source_ids,
                }
            )
        source_blocks = candidate.get("source_blocks")
        if source_blocks is not None:
            source_block_ids = (
                [
                    item.get("block_id")
                    for item in source_blocks
                    if isinstance(item, Mapping)
                ]
                if isinstance(source_blocks, list)
                else []
            )
            if (
                not isinstance(source_blocks, list)
                or len(source_block_ids) != len(source_blocks)
                or len(set(source_block_ids)) != len(source_block_ids)
                or set(source_block_ids) != set(expected_source_ids)
            ):
                mapping_mismatches.append(
                    {
                        "reason": "candidate source_blocks disagree with block mapping",
                        "candidate_id": candidate_id,
                        "expected_source_block_ids": sorted(expected_source_ids),
                        "actual_source_block_ids": source_block_ids,
                    }
                )

    mapping_mismatch_count = sum(
        len(item.get("candidate_ids") or item.get("block_ids") or [item])
        for item in mapping_mismatches
    )
    mapping_unsupported_count = sum(
        len(item.get("candidate_ids") or item.get("block_ids") or [item])
        for item in mapping_unsupported
    )
    result["mismatch_count"] += mapping_mismatch_count
    result["unsupported_count"] += mapping_unsupported_count
    result["failure_count"] += mapping_mismatch_count + mapping_unsupported_count
    result["status"] = (
        "unsupported"
        if result["failure_count"]
        else "measured"
    )
    result["candidate_count"] = len(candidate_records)
    result["filtered_block_count"] = filtered_count
    result["candidate_ids"] = sorted(candidate_blocks)
    result["mismatches"].extend(mapping_mismatches)
    result["unsupported"].extend(mapping_unsupported)
    return result


def _candidate_outcomes_result(
    *,
    stage: Any,
    candidate_ids: list[str],
    actual_output_ids: Mapping[str, Any] | None,
) -> dict[str, Any]:
    stage_mapping = stage if isinstance(stage, Mapping) else {}
    stage_status = stage_mapping.get("status")
    stage_status_failure_count = int(stage_status != "partial_first_pass")
    complete = stage_mapping.get("complete")
    unsupported: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    if complete is not False:
        mismatches.append(
            {
                "reason": "partial_first_pass must report complete=false",
                "complete": complete,
            }
        )

    results = stage_mapping.get("candidate_results")
    if not isinstance(results, list):
        unsupported.append({"reason": "final candidate_results are missing"})
        results = []
    results_by_id: dict[str, list[Mapping[str, Any]]] = {}
    unexpected_results: list[Any] = []
    for candidate_result in results:
        if not isinstance(candidate_result, Mapping):
            unexpected_results.append(candidate_result)
            continue
        candidate_id = candidate_result.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            unexpected_results.append(candidate_result)
        elif candidate_id not in candidate_ids:
            unexpected_results.append({"candidate_id": candidate_id})
        else:
            results_by_id.setdefault(candidate_id, []).append(candidate_result)

    missing_ids = [
        candidate_id
        for candidate_id in candidate_ids
        if candidate_id not in results_by_id
    ]
    duplicate_ids = [
        candidate_id
        for candidate_id, candidate_results in results_by_id.items()
        if len(candidate_results) != 1
    ]
    if missing_ids:
        unsupported.append(
            {
                "reason": "candidate has no final outcome record",
                "candidate_ids": missing_ids,
            }
        )
    if duplicate_ids:
        mismatches.append(
            {
                "reason": "candidate has multiple final outcome records",
                "candidate_ids": duplicate_ids,
            }
        )
    if unexpected_results:
        mismatches.append(
            {
                "reason": "final outcomes reference unknown candidates",
                "records": unexpected_results,
            }
        )

    generated_ids: list[str] = []
    generated_ids_by_category = {
        "requirement_ids": [],
        "scoring_item_ids": [],
    }
    outcome_categories = {
        "requirement_created": "requirement_ids",
        "merged_into_existing_requirement": "requirement_ids",
        "scoring_item_created": "scoring_item_ids",
        "merged_into_existing_scoring_item": "scoring_item_ids",
    }
    no_id_outcomes = {
        "not_requirement_under_local_rules",
        "score_candidate_without_reliable_ceiling",
        "not_reconciled_after_grouping",
    }
    outcome_count = 0
    for candidate_id, candidate_results in results_by_id.items():
        if len(candidate_results) != 1:
            continue
        outcomes = candidate_results[0].get("outcomes")
        if not isinstance(outcomes, list) or not outcomes:
            unsupported.append(
                {
                    "reason": "candidate has no outcome records",
                    "candidate_id": candidate_id,
                }
            )
            continue
        for outcome in outcomes:
            outcome_count += 1
            if not isinstance(outcome, Mapping):
                unsupported.append(
                    {
                        "reason": "candidate outcome is not an object",
                        "candidate_id": candidate_id,
                    }
                )
                continue
            outcome_name = outcome.get("outcome")
            if not isinstance(outcome_name, str) or not outcome_name.strip():
                unsupported.append(
                    {
                        "reason": "candidate outcome label is missing",
                        "candidate_id": candidate_id,
                    }
                )
                outcome_name = ""
            ids = outcome.get("generated_ids")
            if not isinstance(ids, list) or any(
                not isinstance(value, str) or not value for value in ids
            ):
                unsupported.append(
                    {
                        "reason": "outcome generated_ids must be a list of IDs",
                        "candidate_id": candidate_id,
                    }
                )
                continue
            if len(set(ids)) != len(ids):
                mismatches.append(
                    {
                        "reason": "generated_ids repeats an ID within one outcome",
                        "candidate_id": candidate_id,
                        "outcome": outcome_name,
                        "generated_ids": ids,
                    }
                )
            category = outcome_categories.get(outcome_name)
            if category is not None:
                if not ids:
                    mismatches.append(
                        {
                            "reason": "created or merged outcome has no generated ID",
                            "candidate_id": candidate_id,
                            "outcome": outcome_name,
                        }
                    )
                generated_ids_by_category[category].extend(ids)
            elif outcome_name in no_id_outcomes:
                if ids:
                    mismatches.append(
                        {
                            "reason": "no-ID outcome contains generated IDs",
                            "candidate_id": candidate_id,
                            "outcome": outcome_name,
                            "generated_ids": ids,
                        }
                    )
            else:
                unsupported.append(
                    {
                        "reason": "unknown candidate outcome label",
                        "candidate_id": candidate_id,
                        "outcome": outcome_name,
                    }
                )
            generated_ids.extend(ids)

    categories = ("requirement_ids", "scoring_item_ids")
    declared_ids: dict[str, list[str]] = {}
    for category in categories:
        values = stage_mapping.get(category)
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value for value in values
        ):
            unsupported.append(
                {"reason": f"final extraction {category} is missing or invalid"}
            )
            continue
        declared_ids[category] = values
        if len(set(values)) != len(values):
            mismatches.append(
                {
                    "reason": f"final extraction {category} contains duplicate IDs",
                    "ids": values,
                }
            )

    if len(declared_ids) == len(categories):
        declared_all = [
            identifier
            for category in categories
            for identifier in declared_ids[category]
        ]
        if len(set(declared_all)) != len(declared_all):
            mismatches.append(
                {
                    "reason": "generated ID is declared in multiple categories",
                    "ids": declared_all,
                }
            )
        if set(generated_ids) != set(declared_all):
            mismatches.append(
                {
                    "reason": "candidate outcomes and final declared IDs disagree",
                    "generated_ids": generated_ids,
                    "declared_ids": declared_all,
                }
            )
        for category, category_ids in generated_ids_by_category.items():
            if not set(category_ids).issubset(set(declared_ids[category])):
                mismatches.append(
                    {
                        "reason": "outcome IDs do not exist in their declared category",
                        "category": category,
                        "outcome_ids": category_ids,
                        "declared_ids": declared_ids[category],
                    }
                )
        if actual_output_ids is None:
            unsupported.append({"reason": "decomposition output IDs are unavailable"})
        else:
            for category in categories:
                output_ids = actual_output_ids.get(category)
                if not isinstance(output_ids, list):
                    unsupported.append(
                        {
                            "reason": f"decomposition output {category} are unavailable"
                        }
                    )
                    continue
                if len(set(output_ids)) != len(output_ids) or set(
                    output_ids
                ) != set(declared_ids[category]):
                    mismatches.append(
                        {
                            "reason": "audit IDs disagree with decomposition output",
                            "category": category,
                            "audit_ids": declared_ids[category],
                            "output_ids": output_ids,
                        }
                    )

    unsupported_count = len(unsupported)
    mismatch_count = len(mismatches)
    return {
        "stage": "final_requirement_extraction",
        "stage_status": stage_status,
        "complete_claim": complete,
        "stage_status_failure_count": stage_status_failure_count,
        "status": (
            "unsupported"
            if unsupported or stage_status_failure_count
            else "measured"
        ),
        "denominator": len(candidate_ids),
        "record_count": len(results),
        "outcome_count": outcome_count,
        "generated_id_count": len(generated_ids),
        "missing_candidate_result_count": len(missing_ids),
        "duplicate_candidate_result_count": len(duplicate_ids),
        "mismatch_count": mismatch_count,
        "unsupported_count": unsupported_count,
        "failure_count": (
            mismatch_count + unsupported_count + stage_status_failure_count
        ),
        "mismatches": mismatches,
        "unsupported": unsupported,
    }


def _evaluate_block_projection_audit(
    *,
    audit: Any,
    source_structure: Mapping[str, Any] | None,
    actual_output_ids: Mapping[str, Any] | None,
) -> dict[str, Any]:
    source_blocks = (
        source_structure.get("blocks")
        if isinstance(source_structure, Mapping)
        else None
    )
    expected_block_ids = [
        str(block.get("block_id"))
        for block in source_blocks or []
        if isinstance(block, Mapping)
        and block.get("kind") != "page_boundary"
        and isinstance(block.get("block_id"), str)
        and block.get("block_id")
    ]
    synthetic_boundary_ids = {
        str(block.get("block_id"))
        for block in source_blocks or []
        if isinstance(block, Mapping)
        and block.get("kind") == "page_boundary"
        and isinstance(block.get("block_id"), str)
        and block.get("block_id")
    }
    audit_mapping = audit if isinstance(audit, Mapping) else {}
    candidate_result = _candidate_projection_mapping_result(
        stage=audit_mapping.get("candidate_projection"),
        expected_block_ids=expected_block_ids,
        ignored_synthetic_block_ids=synthetic_boundary_ids,
    )
    final_stage = audit_mapping.get("final_requirement_extraction")
    if final_stage is None:
        final_stage = audit_mapping.get("final_extraction")
    final_result = _candidate_outcomes_result(
        stage=final_stage,
        candidate_ids=candidate_result.get("candidate_ids", []),
        actual_output_ids=actual_output_ids,
    )
    return {
        "original_physical_block_count": len(expected_block_ids),
        "candidate_projection": candidate_result,
        "final_extraction": final_result,
        "failure_count": candidate_result["failure_count"]
        + final_result["failure_count"],
    }


def _evaluate_relationship_integrity(
    blocks: list[Mapping[str, Any]],
) -> dict[str, Any]:
    id_counts: dict[str, int] = {}
    for block in blocks:
        block_id = block.get("block_id")
        if isinstance(block_id, str) and block_id:
            id_counts[block_id] = id_counts.get(block_id, 0) + 1
    unique_ids = {block_id for block_id, count in id_counts.items() if count == 1}

    dangling_parent: list[dict[str, Any]] = []
    dangling_section: list[dict[str, Any]] = []
    self_parent: list[dict[str, Any]] = []
    parent_by_id: dict[str, str] = {}
    for block in blocks:
        block_id = block.get("block_id")
        if not isinstance(block_id, str) or id_counts.get(block_id) != 1:
            continue
        for field, failures in (
            ("parent_block_id", dangling_parent),
            ("section_block_id", dangling_section),
        ):
            reference = block.get(field)
            if reference is None or reference == "":
                continue
            if not isinstance(reference, str) or reference not in unique_ids:
                failures.append(
                    {
                        "block_id": block_id,
                        "reference": reference,
                        "field": field,
                    }
                )
            elif field == "parent_block_id":
                if reference == block_id:
                    self_parent.append({"block_id": block_id})
                else:
                    parent_by_id[block_id] = reference

    states: dict[str, int] = {}
    stack: list[str] = []
    cycles: list[list[str]] = []

    def visit(block_id: str) -> None:
        state = states.get(block_id, 0)
        if state == 2:
            return
        if state == 1:
            cycle_start = stack.index(block_id)
            cycle = stack[cycle_start:]
            if len(cycle) > 1:
                cycles.append([*cycle, block_id])
            return
        states[block_id] = 1
        stack.append(block_id)
        parent_id = parent_by_id.get(block_id)
        if parent_id is not None:
            visit(parent_id)
        stack.pop()
        states[block_id] = 2

    for block_id in parent_by_id:
        visit(block_id)

    failure_count = (
        len(dangling_parent)
        + len(dangling_section)
        + len(self_parent)
        + len(cycles)
    )
    return {
        "status": "passed" if not failure_count else "failed",
        "dangling_parent_count": len(dangling_parent),
        "dangling_parent": dangling_parent,
        "dangling_section_count": len(dangling_section),
        "dangling_section": dangling_section,
        "self_parent_count": len(self_parent),
        "self_parent": self_parent,
        "parent_cycle_count": len(cycles),
        "parent_cycles": cycles,
        "failure_count": failure_count,
    }


def _evaluate_structure(
    *,
    case_id: str,
    structure: Mapping[str, Any],
    oracle_case: Mapping[str, Any],
    raw_pages: list[str],
    document_id: str,
    source_version: str,
) -> dict[str, Any]:
    expected = _expanded_oracle(oracle_case, raw_pages)
    raw_blocks = structure.get("blocks")
    if not isinstance(raw_blocks, list):
        return {
            "status": "not_run",
            "not_run_reason": "document structure has no blocks list",
            "expected_block_count": len(expected),
            "actual_block_count": 0,
        }
    blocks = [dict(block) for block in raw_blocks if isinstance(block, Mapping)]
    boundary_blocks = [
        block for block in blocks if block.get("kind") == "page_boundary"
    ]
    physical_blocks = [block for block in blocks if block not in boundary_blocks]
    relationship_integrity = _evaluate_relationship_integrity(physical_blocks)
    expected_spans = {
        item["locator"]: (
            int(item["page_number"]),
            int(item["source_span"]["start"]),
            int(item["source_span"]["end"]),
        )
        for item in expected
    }
    actual_by_locator: dict[str, list[dict[str, Any]]] = {}
    for block in physical_blocks:
        try:
            page_number = int(block.get("page_number"))
            line_number = int(block.get("line_number"))
        except (TypeError, ValueError):
            continue
        actual_by_locator.setdefault(
            f"p{page_number}l{line_number}", []
        ).append(block)

    missing: list[str] = []
    unexpected: list[str] = []
    wrong_kind: list[dict[str, Any]] = []
    wrong_parent: list[dict[str, Any]] = []
    wrong_section: list[dict[str, Any]] = []
    wrong_numbering: list[dict[str, Any]] = []
    review_failures: list[str] = []
    merge_blocks: list[str] = []
    normalization_failures: list[dict[str, Any]] = []
    source_reference_failures: list[dict[str, Any]] = []
    reference_errors_by_locator: dict[str, list[str]] = {}
    known_locators = {item["locator"] for item in expected}
    review_candidates = [
        item
        for item in expected
        if isinstance(item.get("review"), Mapping)
        and item["review"].get("status") == "needs_review"
    ]
    matched_by_locator: dict[str, dict[str, Any]] = {}
    for locator, matches in actual_by_locator.items():
        if locator not in known_locators:
            unexpected.extend([locator] * len(matches))
        elif len(matches) > 1:
            unexpected.extend([locator] * (len(matches) - 1))
        else:
            matched_by_locator[locator] = matches[0]

    for block in physical_blocks:
        raw_text = block.get("raw_text")
        span = _source_span(block)
        covered_lines = []
        if span is not None:
            span_page, span_start, span_end = span
            covered_lines = [
                locator
                for locator, (
                    expected_page,
                    expected_start,
                    expected_end,
                ) in expected_spans.items()
                if expected_page == span_page
                and (
                    (span_start < expected_end and span_end > expected_start)
                    or span_start == span_end == expected_start
                )
            ]
        if (
            isinstance(raw_text, str)
            and ("\r" in raw_text or "\n" in raw_text)
        ) or len(covered_lines) > 1:
            merge_blocks.append(str(block.get("block_id") or "missing-block-id"))

    for item in expected:
        locator = item["locator"]
        matches = actual_by_locator.get(locator, [])
        if not matches:
            missing.append(locator)
            continue
        if len(matches) > 1:
            unexpected.extend([locator] * (len(matches) - 1))
        block = matches[0]
        if block.get("kind") != item.get("kind"):
            wrong_kind.append(
                {
                    "locator": locator,
                    "expected": item.get("kind"),
                    "actual": block.get("kind"),
                }
            )
        actual_parent = block.get("parent_block_id")
        if "parent" in item:
            expected_parent_locator = item["parent"]
            expected_parent = (
                matched_by_locator.get(expected_parent_locator, {}).get("block_id")
                if expected_parent_locator
                else None
            )
            if actual_parent != expected_parent:
                wrong_parent.append(
                    {
                        "locator": locator,
                        "expected_parent_block_id": expected_parent,
                        "actual_parent_block_id": actual_parent,
                    }
                )
        if "section" in item:
            expected_section_locator = item["section"]
            expected_section = (
                matched_by_locator.get(expected_section_locator, {}).get("block_id")
                if expected_section_locator
                else None
            )
            actual_section = block.get("section_block_id")
            if actual_section != expected_section:
                wrong_section.append(
                    {
                        "locator": locator,
                        "expected_section_block_id": expected_section,
                        "actual_section_block_id": actual_section,
                    }
                )

        expected_numbering = item.get("numbering")
        actual_numbering = block.get("numbering")
        if expected_numbering is None:
            if actual_numbering is not None:
                wrong_numbering.append(
                    {"locator": locator, "expected": None, "actual": actual_numbering}
                )
        elif not isinstance(actual_numbering, Mapping):
            wrong_numbering.append(
                {"locator": locator, "expected": expected_numbering, "actual": None}
            )
        else:
            mismatches = {
                name: {
                    "expected": expected_numbering.get(name),
                    "actual": actual_numbering.get(name),
                }
                for name in ("label", "level")
                if name in expected_numbering
                if actual_numbering.get(name) != expected_numbering.get(name)
            }
            if "path" in expected_numbering:
                expected_path_tokens = _path_tokens(expected_numbering["path"])
                if actual_numbering.get("path") != expected_path_tokens:
                    mismatches["path"] = {
                        "expected_tokens": expected_path_tokens,
                        "oracle_label_path": expected_numbering["path"],
                        "actual": actual_numbering.get("path"),
                    }
            if (
                not str(block.get("raw_text") or "").startswith(
                    str(expected_numbering.get("label") or "")
                )
                or mismatches
            ):
                wrong_numbering.append(
                    {"locator": locator, "mismatches": mismatches}
                )

        page_number = int(item["page_number"])
        page_text = raw_pages[page_number - 1]
        normalization_errors = _normalization_map_errors(
            block,
            page_text=page_text,
            expected_page=page_number,
        )
        if normalization_errors:
            normalization_failures.append(
                {"locator": locator, "errors": normalization_errors}
            )
        reference_errors = _source_reference_errors(
            block,
            page_text=page_text,
            page_number=page_number,
            document_id=document_id,
            source_version=source_version,
        )
        if reference_errors:
            source_reference_failures.append(
                {"locator": locator, "errors": reference_errors}
            )
            reference_errors_by_locator[locator] = reference_errors

    continuation_result = _evaluate_continuation_candidates(
        expected_candidates=review_candidates,
        structure=structure,
        matched_by_locator=matched_by_locator,
    )
    review_failures.extend(
        failure["locator"] for failure in continuation_result["failures"]
    )
    review_failures.extend(
        f"unexpected:{candidate.get('candidate_id') or 'unknown'}"
        for candidate in continuation_result["unexpected_candidates"]
    )
    table_grouping = _evaluate_table_grouping(
        expected=expected,
        matched_by_locator=matched_by_locator,
    )
    table_cell_spans = _evaluate_table_cell_spans(
        expected=expected,
        matched_by_locator=matched_by_locator,
        raw_pages=raw_pages,
    )
    title_candidates = _evaluate_ambiguous_candidate_field(
        field_name="title_candidate",
        expected=expected,
        actual_by_locator=actual_by_locator,
        global_candidates=structure.get("title_candidates"),
        reference_errors_by_locator=reference_errors_by_locator,
    )
    heading_candidates = _evaluate_ambiguous_candidate_field(
        field_name="heading_candidate",
        expected=expected,
        actual_by_locator=actual_by_locator,
        reference_errors_by_locator=reference_errors_by_locator,
    )
    candidate_failure_count = (
        title_candidates["failure_count"] + heading_candidates["failure_count"]
    )

    reconstructed_pages: list[dict[str, Any]] = []
    source_gap_pages: list[int] = []
    actual_page_map = {
        int(page.get("page_number") or index): page
        for index, page in enumerate(_structure_pages(structure), start=1)
    }
    for page_number, source_page in enumerate(raw_pages, start=1):
        page_blocks = [
            block
            for block in physical_blocks
            if block.get("page_number") == page_number
        ]
        page_blocks.sort(
            key=lambda block: (
                _source_span(block)[1]
                if _source_span(block) is not None
                else len(source_page) + 1
            )
        )
        cursor = 0
        page_errors: list[str] = []
        reconstructed = []
        for block in page_blocks:
            raw_text = block.get("raw_text")
            line_ending = block.get("line_ending")
            span = _source_span(block)
            if not isinstance(raw_text, str) or not isinstance(line_ending, str):
                page_errors.append("raw_text or line_ending missing")
                continue
            if span is None:
                page_errors.append("page block source_span missing")
                continue
            span_page, start, end = span
            if span_page != page_number or start != cursor or end < start:
                page_errors.append("source span has a page mismatch, gap, or overlap")
                continue
            if end > len(source_page) or source_page[start:end] != raw_text:
                page_errors.append("raw_text does not match its source span")
                continue
            if source_page[end : end + len(line_ending)] != line_ending:
                page_errors.append("line_ending does not match the page source")
                continue
            reconstructed.extend((raw_text, line_ending))
            cursor = end + len(line_ending)
        if cursor != len(source_page):
            page_errors.append("source page has uncovered characters")
        joined = "".join(reconstructed)
        if joined != source_page:
            page_errors.append("physical blocks do not reconstruct the source page")
        actual_page = actual_page_map.get(page_number)
        actual_page_text = (
            _structure_page_text(actual_page) if actual_page is not None else None
        )
        if actual_page_text != source_page:
            page_errors.append("document structure page text differs from raw input")
        if page_errors:
            source_gap_pages.append(page_number)
        reconstructed_pages.append(
            {
                "page_number": page_number,
                "source_characters": len(source_page),
                "reconstructed_characters": len(joined),
                "exact": not page_errors,
                "errors": page_errors,
            }
        )

    expected_boundaries = max(0, len(raw_pages) - 1)
    page_boundary_errors: list[str] = []
    if len(_structure_pages(structure)) != len(raw_pages):
        page_boundary_errors.append("document structure page count mismatch")
    if len(boundary_blocks) != expected_boundaries:
        page_boundary_errors.append("page_boundary block count mismatch")
    for block in boundary_blocks:
        if block.get("source_span") is not None:
            page_boundary_errors.append(
                "synthetic page_boundary must not cite a page-body span"
            )
        if block.get("source_references"):
            page_boundary_errors.append(
                "synthetic page_boundary must not cite page-body source"
            )

    missing_block_ids = [
        str(block.get("line_number") or "unknown-line")
        for block in physical_blocks
        if not block.get("block_id")
    ]
    block_ids = [
        str(block.get("block_id") or "")
        for block in physical_blocks
        if block.get("block_id")
    ]
    duplicate_ids = sorted(
        {block_id for block_id in block_ids if block_ids.count(block_id) > 1}
    )
    filtered_marked = [
        block
        for block in blocks
        if block.get("filtered") is True
        or block.get("filter_status") == "filtered"
        or block.get("downstream_disposition") == "filtered"
    ]
    filtered_ids = {
        str(block.get("block_id") or "")
        for block in filtered_marked
        if block.get("block_id")
    }
    preserved_filtered = sum(
        1
        for block in physical_blocks
        if str(block.get("block_id") or "") in filtered_ids
        and isinstance(block.get("raw_text"), str)
        and _source_span(block) is not None
    )

    return {
        "status": "executed",
        "case_id": case_id,
        "expected_block_count": len(expected),
        "actual_block_count": len(physical_blocks),
        "missing_blocks": {"count": len(missing), "locators": missing},
        "unexpected_blocks": {"count": len(unexpected), "locators": unexpected},
        "wrong_kind": {"count": len(wrong_kind), "items": wrong_kind},
        "wrong_parent_or_merge": {
            "count": len(wrong_parent) + len(merge_blocks),
            "wrong_parent_count": len(wrong_parent),
            "merge_count": len(merge_blocks),
            "wrong_parent": wrong_parent,
            "merge_block_ids": merge_blocks,
        },
        "wrong_section": {"count": len(wrong_section), "items": wrong_section},
        "wrong_numbering": {"count": len(wrong_numbering), "items": wrong_numbering},
        "invalid_relationship_references": relationship_integrity,
        "source_gaps": {
            "count": len(source_gap_pages),
            "page_numbers": source_gap_pages,
            "pages": reconstructed_pages,
        },
        "normalization_map": {
            "failure_count": len(normalization_failures),
            "failures": normalization_failures,
        },
        "source_references": {
            "failure_count": len(source_reference_failures),
            "failures": source_reference_failures,
        },
        "uncertain_relations": {
            "needs_review_denominator": len(review_candidates),
            "needs_review_failure_count": continuation_result["failure_count"],
            "needs_review_failures": review_failures,
            "candidate_validation": continuation_result,
        },
        "table_grouping": table_grouping,
        "table_cell_spans": table_cell_spans,
        "ambiguous_candidates": {
            "title_candidate": title_candidates,
            "heading_candidate": heading_candidates,
            "failure_count": candidate_failure_count,
        },
        "page_boundaries": {
            "expected_count": expected_boundaries,
            "explicit_block_count": len(boundary_blocks),
            "preserved_by_page_array": len(_structure_pages(structure))
            == len(raw_pages),
            "errors": page_boundary_errors,
        },
        "block_ids": {
            "unique_nonempty_count": len(set(block_ids)),
            "missing_block_ids": {
                "count": len(missing_block_ids),
                "line_numbers": missing_block_ids,
            },
            "duplicate_ids": duplicate_ids,
        },
        "filtered_content": {
            "status": "all_physical_source_blocks_checked",
            "preservation_denominator": len(expected),
            "preserved_physical_blocks": len(expected) - len(missing),
            "missing_physical_blocks": len(missing),
            "explicitly_marked_filtered_blocks": len(filtered_marked),
            "explicitly_marked_filtered_blocks_preserved": preserved_filtered,
            "filter_annotations_status": (
                "reported" if filtered_marked else "not_reported_by_structure"
            ),
        },
        "all_structure_checks_passed": not any(
            (
                missing,
                unexpected,
                wrong_kind,
                wrong_parent,
                wrong_section,
                wrong_numbering,
                relationship_integrity["failure_count"],
                continuation_result["failure_count"],
                table_grouping["failure_count"],
                table_cell_spans["failure_count"],
                candidate_failure_count,
                source_gap_pages,
                normalization_failures,
                source_reference_failures,
                review_failures,
                page_boundary_errors,
                missing_block_ids,
                duplicate_ids,
            )
        )
        and not merge_blocks,
    }


def _safe_output(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _safe_output(value.to_dict())
    if isinstance(value, Mapping):
        return {str(key): _safe_output(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_output(child) for child in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat") and callable(value.isoformat):
        return value.isoformat()
    return str(value)


async def _run_case(
    fixture_case: Mapping[str, Any],
    oracle_case: Mapping[str, Any],
) -> dict[str, Any]:
    source_path = (ROOT / str(fixture_case["source_path"])).resolve()
    source_path.relative_to(ROOT.resolve())
    source_bytes = source_path.read_bytes()
    source_text = source_bytes.decode("utf-8")
    raw_pages = source_text.split(BOUNDARY)
    project_id = f"document-structure-{fixture_case['case_id']}"
    file_id = f"document-structure-{fixture_case['case_id'].lower()}"
    registry = ProjectFileRegistry()
    registration = registry.register(
        project_id=project_id,
        file_name=source_path.name,
        file_role="tender",
        content=source_bytes,
        file_id=file_id,
    )
    source_version = registry.file_version_token(file_id)
    runtime = AgentRuntime(
        build_default_registry(file_registry=registry),
        services={"file_registry": registry},
    )
    request = SkillRequest.create(
        {
            "project_id": project_id,
            "file_ids": [file_id],
            "bidder_file_ids": [],
            "bidder_id": "document-structure-no-business-materials",
            "bidder_name": "synthetic text structure evaluation",
            "task": "分析招标文件",
        }
    )
    run_result = await runtime.run(request)
    steps = _step_values(run_result)
    intake_step = _find_step(steps, "tender-intake")
    decomposition_step = _find_step(steps, "tender-decomposition")
    intake_data = intake_step.get("data") if intake_step else None
    decomposition_data = decomposition_step.get("data") if decomposition_step else None
    intake_structures = _document_structures(intake_data)
    decomposition_structures = _document_structures(decomposition_data)
    parse_artifact = registry.parse(file_id)
    artifact_content = parse_artifact.get("content")
    parse_structures = _document_structures(parse_artifact)
    if not parse_structures:
        direct = parse_artifact.get("document_structure")
        if isinstance(direct, Mapping):
            parse_structures = [dict(direct)]

    intake_status = (
        str(intake_step.get("status") or "not_run").lower()
        if intake_step
        else "not_run"
    )
    decomposition_status = (
        str(decomposition_step.get("status") or "not_run").lower()
        if decomposition_step
        else "not_run"
    )
    complete_chain = (
        intake_status == "success"
        and decomposition_status == "success"
        and bool(parse_structures)
        and bool(intake_structures)
        and bool(decomposition_structures)
    )
    if not complete_chain:
        chain_status = (
            "failed"
            if any(
                status not in {"success", "not_run"}
                for status in (intake_status, decomposition_status)
            )
            else "not_run"
        )
        structure_result = {
            "status": chain_status,
            "case_id": fixture_case["case_id"],
            "not_run_reason": (
                "full Registry parse, TenderIntakeSkill, and "
                "TenderDecompositionSkill structure chain was not completed"
            ),
            "intake_status": intake_status,
            "decomposition_status": decomposition_status,
            "registry_parse_structure_count": len(parse_structures),
            "intake_structure_count": len(intake_structures),
            "decomposition_structure_count": len(decomposition_structures),
            "expected_block_count": sum(
                len(page.get("blocks") or [])
                for page in oracle_case.get("pages") or []
            ),
        }
    else:
        selected = decomposition_structures[0]
        structure_result = _evaluate_structure(
            case_id=str(fixture_case["case_id"]),
            structure=selected,
            oracle_case=oracle_case,
            raw_pages=raw_pages,
            document_id=file_id,
            source_version=source_version,
        )
        decomposition_mapping = _field_mapping(decomposition_data) or {}
        projection_audit = _evaluate_block_projection_audit(
            audit=decomposition_mapping.get("block_projection_audit"),
            source_structure=parse_structures[0],
            actual_output_ids=_decomposition_output_ids(decomposition_mapping),
        )
        structure_result["block_projection_audit"] = projection_audit
        if projection_audit["failure_count"]:
            structure_result["all_structure_checks_passed"] = False
        structure_result["selected_stage"] = "tender-decomposition"

    registry_pages = parse_artifact.get("pages")
    if not isinstance(registry_pages, list):
        registry_pages = (
            artifact_content.get("pages")
            if isinstance(artifact_content, Mapping)
            else []
        )
    registry_pages = list(registry_pages or [])
    registry_page_texts = [
        str(page.get("text") or page.get("raw_text") or "")
        for page in registry_pages
        if isinstance(page, Mapping)
    ]
    registry_page_mismatches = [
        page_number
        for page_number in range(1, max(len(raw_pages), len(registry_page_texts)) + 1)
        if page_number > len(raw_pages)
        or page_number > len(registry_page_texts)
        or raw_pages[page_number - 1] != registry_page_texts[page_number - 1]
    ]
    return {
        "case_id": fixture_case["case_id"],
        "evaluation_status": structure_result["status"],
        "source": {
            "path": fixture_case["source_path"],
            "sha256": _sha256(source_bytes),
            "expected_sha256": fixture_case["source_sha256"],
            "registered_checksum": registration.file.checksum,
            "registered_checksum_matches_raw": registration.file.checksum
            == _sha256(source_bytes),
            "source_version_label_in_raw": _inline_source_version(source_text),
            "registry_source_version": source_version,
            "raw_page_count": len(raw_pages),
        },
        "runtime": {
            "execution_status": getattr(run_result, "execution_status", "unknown"),
            "intake_step_status": intake_status,
            "decomposition_step_status": decomposition_status,
            "document_structures_exposed_by_intake": len(intake_structures),
            "document_structures_exposed_by_decomposition": len(
                decomposition_structures
            ),
            "document_structures_exposed_by_registry_parse": len(parse_structures),
            "full_chain_structure_exposure": complete_chain,
            "document_structures": {
                "registry_parse": _safe_output(parse_structures),
                "tender_intake": _safe_output(intake_structures),
                "tender_decomposition": _safe_output(decomposition_structures),
            },
            "complete_runtime_output": _safe_output(run_result),
            "registry_parse_artifact": _safe_output(parse_artifact),
        },
        "registry_pages": {
            "expected_page_count": len(raw_pages),
            "actual_page_count": len(registry_page_texts),
            "page_texts_match_raw_exactly": registry_page_texts == raw_pages,
            "mismatched_page_numbers": registry_page_mismatches,
        },
        "structure": structure_result,
        "business_layer": "not_run",
    }


def _inline_source_version(raw_text: str) -> str | None:
    match = re.search(r"(?m)^source_version:\s*(\S+)\s*$", raw_text)
    return match.group(1) if match else None


def _aggregate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    executed = [
        case for case in cases if case.get("structure", {}).get("status") == "executed"
    ]
    failed_cases = [
        case for case in cases if case.get("structure", {}).get("status") == "failed"
    ]
    not_run_cases = [
        case for case in cases if case.get("structure", {}).get("status") == "not_run"
    ]
    not_run = len(not_run_cases)
    registry_cases = [case for case in cases if "registry_pages" in case]

    def metric(
        name: str,
        denominator: int,
        count: int,
        details: list[Any],
    ) -> dict[str, Any]:
        return {
            "status": "measured" if denominator else "not_run",
            "denominator": denominator,
            "count": count if denominator else None,
            "details": details,
        }

    expected_blocks = sum(
        case["structure"]["expected_block_count"] for case in executed
    )
    missing_count = sum(
        case["structure"]["missing_blocks"]["count"] for case in executed
    )
    wrong_kind_count = sum(
        case["structure"]["wrong_kind"]["count"] for case in executed
    )
    wrong_parent_count = sum(
        case["structure"]["wrong_parent_or_merge"]["count"] for case in executed
    )
    wrong_parent_details = [
        {
            "case_id": case["case_id"],
            **case["structure"]["wrong_parent_or_merge"],
        }
        for case in executed
    ]
    relationship_failure_count = sum(
        case["structure"]["invalid_relationship_references"]["failure_count"]
        for case in executed
    )
    wrong_section_count = sum(
        case["structure"]["wrong_section"]["count"] for case in executed
    )
    wrong_numbering_count = sum(
        case["structure"]["wrong_numbering"]["count"] for case in executed
    )
    review_denominator = sum(
        case["structure"]["uncertain_relations"]["needs_review_denominator"]
        for case in executed
    )
    review_failure_count = sum(
        case["structure"]["uncertain_relations"]["needs_review_failure_count"]
        for case in executed
    )
    source_pages = sum(
        case["source"]["raw_page_count"] for case in executed
    )
    source_gap_count = sum(
        case["structure"]["source_gaps"]["count"] for case in executed
    )
    normalization_failures = sum(
        case["structure"]["normalization_map"]["failure_count"]
        for case in executed
    )
    table_grouping_denominator = sum(
        case["structure"]["table_grouping"]["denominator"] for case in executed
    )
    table_grouping_mismatches = sum(
        case["structure"]["table_grouping"]["mismatch_count"] for case in executed
    )
    table_grouping_unsupported = sum(
        case["structure"]["table_grouping"]["unsupported_count"]
        for case in executed
    )
    table_cell_denominator = sum(
        case["structure"]["table_cell_spans"]["denominator"]
        for case in executed
    )
    table_cell_failures = sum(
        case["structure"]["table_cell_spans"]["failure_count"]
        for case in executed
    )
    table_cell_unsupported = sum(
        case["structure"]["table_cell_spans"]["unsupported_count"]
        for case in executed
    )
    source_reference_failures = sum(
        case["structure"]["source_references"]["failure_count"]
        for case in executed
    )
    missing_block_ids = sum(
        case["structure"]["block_ids"]["missing_block_ids"]["count"]
        for case in executed
    )
    registry_page_denominator = sum(
        case["registry_pages"]["expected_page_count"] for case in registry_cases
    )
    registry_page_mismatches = sum(
        len(case["registry_pages"]["mismatched_page_numbers"])
        for case in registry_cases
    )

    def projection_metric(stage_name: str) -> dict[str, Any]:
        stage_results = [
            case["structure"]["block_projection_audit"][stage_name]
            for case in executed
            if isinstance(case["structure"].get("block_projection_audit"), Mapping)
        ]
        denominator = sum(item["denominator"] for item in stage_results)
        failure_count = sum(item["failure_count"] for item in stage_results)
        unsupported_count = sum(item["unsupported_count"] for item in stage_results)
        return {
            "status": "measured" if denominator else "not_run",
            "denominator": denominator,
            "failure_count": failure_count if denominator else None,
            "unsupported_count": unsupported_count if denominator else None,
            "details": [
                {
                    "case_id": case["case_id"],
                    **case["structure"]["block_projection_audit"][stage_name],
                }
                for case in executed
                if isinstance(case["structure"].get("block_projection_audit"), Mapping)
            ],
        }

    return {
        "case_count": len(cases),
        "executed": len(executed),
        "failed": len(failed_cases),
        "not_run": not_run,
        "missing_blocks": metric(
            "missing_blocks",
            expected_blocks,
            missing_count,
            [
                {
                    "case_id": case["case_id"],
                    **case["structure"]["missing_blocks"],
                }
                for case in executed
            ],
        ),
        "wrong_kind": metric(
            "wrong_kind",
            expected_blocks,
            wrong_kind_count,
            [
                {"case_id": case["case_id"], **case["structure"]["wrong_kind"]}
                for case in executed
            ],
        ),
        "wrong_parent_or_merge": metric(
            "wrong_parent_or_merge",
            expected_blocks,
            wrong_parent_count,
            wrong_parent_details,
        ),
        "invalid_relationship_references": metric(
            "invalid_relationship_references",
            expected_blocks,
            relationship_failure_count,
            [
                {
                    "case_id": case["case_id"],
                    **case["structure"]["invalid_relationship_references"],
                }
                for case in executed
            ],
        ),
        "wrong_section": metric(
            "wrong_section",
            expected_blocks,
            wrong_section_count,
            [
                {
                    "case_id": case["case_id"],
                    **case["structure"]["wrong_section"],
                }
                for case in executed
            ],
        ),
        "wrong_numbering": metric(
            "wrong_numbering",
            expected_blocks,
            wrong_numbering_count,
            [
                {
                    "case_id": case["case_id"],
                    **case["structure"]["wrong_numbering"],
                }
                for case in executed
            ],
        ),
        "uncertain_relation_needs_review": metric(
            "uncertain_relation_needs_review",
            review_denominator,
            review_failure_count,
            [
                {
                    "case_id": case["case_id"],
                    **case["structure"]["uncertain_relations"],
                }
                for case in executed
                if case["structure"]["uncertain_relations"][
                    "needs_review_denominator"
                ]
            ],
        ),
        "table_grouping": {
            "status": "measured" if table_grouping_denominator else "not_run",
            "denominator": table_grouping_denominator,
            "mismatch_count": (
                table_grouping_mismatches if table_grouping_denominator else None
            ),
            "unsupported_count": (
                table_grouping_unsupported if table_grouping_denominator else None
            ),
            "failure_count": (
                table_grouping_mismatches + table_grouping_unsupported
                if table_grouping_denominator
                else None
            ),
            "details": [
                {"case_id": case["case_id"], **case["structure"]["table_grouping"]}
                for case in executed
            ],
        },
        "table_cell_spans": {
            "status": "measured" if table_cell_denominator else "not_run",
            "denominator": table_cell_denominator,
            "failure_count": table_cell_failures if table_cell_denominator else None,
            "unsupported_count": (
                table_cell_unsupported if table_cell_denominator else None
            ),
            "details": [
                {
                    "case_id": case["case_id"],
                    **case["structure"]["table_cell_spans"],
                }
                for case in executed
            ],
        },
        "block_projection_audit": {
            "candidate_projection": projection_metric("candidate_projection"),
            "final_extraction": projection_metric("final_extraction"),
        },
        "source_gaps": metric(
            "source_gaps",
            source_pages,
            source_gap_count,
            [
                {
                    "case_id": case["case_id"],
                    **case["structure"]["source_gaps"],
                }
                for case in executed
            ],
        ),
        "normalization_map_failures": metric(
            "normalization_map_failures",
            expected_blocks,
            normalization_failures,
            [
                {
                    "case_id": case["case_id"],
                    **case["structure"]["normalization_map"],
                }
                for case in executed
            ],
        ),
        "source_reference_failures": metric(
            "source_reference_failures",
            expected_blocks,
            source_reference_failures,
            [
                {
                    "case_id": case["case_id"],
                    **case["structure"]["source_references"],
                }
                for case in executed
            ],
        ),
        "missing_block_ids": metric(
            "missing_block_ids",
            expected_blocks,
            missing_block_ids,
            [
                {
                    "case_id": case["case_id"],
                    **case["structure"]["block_ids"]["missing_block_ids"],
                }
                for case in executed
            ],
        ),
        "registry_parse_page_text_mismatches": metric(
            "registry_parse_page_text_mismatches",
            registry_page_denominator,
            registry_page_mismatches,
            [
                {
                    "case_id": case["case_id"],
                    **case["registry_pages"],
                }
                for case in registry_cases
            ],
        ),
        "not_run_cases": {
            "status": "measured",
            "denominator": len(cases),
            "count": not_run,
            "case_ids": [case["case_id"] for case in not_run_cases],
        },
        "failed_cases": {
            "status": "measured",
            "denominator": len(cases),
            "count": len(failed_cases),
            "case_ids": [case["case_id"] for case in failed_cases],
        },
        "filtered_content_preservation": {
            "status": "measured" if executed else "not_run",
            "denominator": expected_blocks if executed else 0,
            "preserved_physical_blocks": (
                expected_blocks - missing_count if executed else None
            ),
            "missing_physical_blocks": missing_count if executed else None,
            "explicit_filter_annotation_status": (
                "reported"
                if any(
                    case["structure"]["filtered_content"]["filter_annotations_status"]
                    == "reported"
                    for case in executed
                )
                else "not_reported_by_structure"
                if executed
                else "not_run"
            ),
        },
    }


async def run_evaluation() -> dict[str, Any]:
    freeze = verify_freeze()
    fixture_index = _load_json(FIXTURE_PATH)
    oracle = _load_json(ORACLE_PATH)
    oracle_by_id = {case["case_id"]: case for case in oracle["cases"]}
    cases: list[dict[str, Any]] = []
    for fixture_case in fixture_index["cases"]:
        try:
            cases.append(
                await _run_case(
                    fixture_case,
                    oracle_by_id[fixture_case["case_id"]],
                )
            )
        except Exception as exc:
            cases.append(
                {
                    "case_id": fixture_case["case_id"],
                    "evaluation_status": "not_run",
                    "source": {
                        "path": fixture_case["source_path"],
                        "expected_sha256": fixture_case["source_sha256"],
                    },
                    "runtime": {
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                    "structure": {
                        "status": "not_run",
                        "case_id": fixture_case["case_id"],
                        "not_run_reason": "registry/runtime evaluation raised an error",
                    },
                    "business_layer": "not_run",
                }
            )

    summary = _aggregate(cases)
    measured_cases = [
        case for case in cases if case.get("structure", {}).get("status") == "executed"
    ]
    all_structure_checks_passed = bool(measured_cases) and len(measured_cases) == len(
        cases
    ) and all(
        case["structure"].get("all_structure_checks_passed") is True
        for case in measured_cases
    )
    git_metadata = _git_metadata()
    report_kind = (
        "archive_snapshot"
        if git_metadata["repository_context"] == "archive/no_local_git_root"
        else "initial_debug_worktree"
    )
    return {
        "schema": "document-structure-eval-v1",
        "report_kind": report_kind,
        "report_kind_basis": (
            "derived from repository_context; archive_snapshot alone does not "
            "establish canonical archive status"
        ),
        "classification": "public_regression_not_blind",
        "generated_at": datetime.now(
            timezone(timedelta(hours=8), name="Asia/Shanghai")
        ).isoformat(),
        "evaluation_baseline_revision": "8ddc8f0eb46c079927893114ac9f4082973f8fa6",
        **git_metadata,
        "source_tree_sha256": _source_tree_sha256(),
        "source_tree_sha256_scope": (
            "SHA-256 over src/**/*.py sorted by repository-relative path; each "
            "path is followed by TAB and the raw-byte file SHA-256 digest"
        ),
        "freeze": freeze,
        "input_policy": {
            "source_files_are_existing_public_raw_fixtures": True,
            "raw_source_files_modified": False,
            "oracle_registered_as_runtime_input": False,
            "private_frozen_set_loaded": False,
            "reserved_copy_manifest_loaded": False,
            "reserved_copy_hash_verification_is_not_fixture_execution": True,
            "synthetic_private_samples_are_real_pdfs": False,
            "private_freeze_certified_blind": False,
        },
        "claims": {
            "model": "unused",
            "real_ocr": "unused",
            "business_layer": "not_run",
            "condition_tree_completeness": "not_run",
            "production_acceptance": "not_passed",
            "canonical_archive_report": "required_from_primary_reviewer",
            "archive_canonicality": (
                "unverified_until_primary_staged_tree_and_git_blob_check"
                if report_kind == "archive_snapshot"
                else "not_applicable_to_worktree_debug_report"
            ),
        },
        "schema_questions": {
            "numbering_path": (
                "Public oracle stores ancestor literal-label segments; runner "
                "converts each segment to its terminal token for comparison."
            ),
            "numbering_style": (
                "Retained in the full output but not pass/fail scored because "
                "the accepted style enum has not been agreed."
            ),
            "section_block_id": (
                "Evaluated independently from parent and numbering wherever the "
                "oracle specifies a structural section container."
            ),
        },
        "summary": {
            **summary,
            "structural_regression_status": (
                "passed_on_selected_public_cases"
                if all_structure_checks_passed
                else "not_passed"
                if measured_cases or summary["failed"]
                else "not_run"
            ),
            "condition_tree_completeness": {
                "status": "not_run",
                "denominator": len(cases),
                "passed": None,
            },
            "business_layer": {"status": "not_run", "denominator": len(cases)},
            "production_acceptance": "not_passed",
        },
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="write JSON to a new path only; existing files are never overwritten",
    )
    args = parser.parse_args(argv)
    output: Path | None = None
    if args.output is not None:
        output = args.output.resolve()
        if output.exists():
            parser.error(f"refusing to overwrite existing report: {output}")

    report = asyncio.run(run_evaluation())
    rendered = json.dumps(_safe_output(report), ensure_ascii=False, indent=2) + "\n"
    if output is None:
        sys.stdout.write(rendered)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with output.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(rendered)
        except FileExistsError:
            parser.error(f"refusing to overwrite existing report: {output}")
    summary = report.get("summary")
    return int(
        not (
            isinstance(summary, Mapping)
            and summary.get("structural_regression_status")
            == "passed_on_selected_public_cases"
            and summary.get("not_run") == 0
            and summary.get("failed") == 0
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
