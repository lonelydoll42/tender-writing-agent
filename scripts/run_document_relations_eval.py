"""Score the frozen synthetic document-relations bundle through the real runtime."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qiaowenshu_agent.core.contracts import SkillRequest  # noqa: E402
from qiaowenshu_agent.core.files import ProjectFileRegistry  # noqa: E402
from qiaowenshu_agent.core.runtime import AgentRuntime  # noqa: E402
from qiaowenshu_agent.skills import build_default_registry  # noqa: E402


EXPECTED_CASE_IDS = tuple(f"case-{index:02d}" for index in range(1, 15))
EXPECTED_V2_FINGERPRINT = (
    "eb7322ccbdafba33db9ab17a6bc35c793fdce2ff9cb0bad82a38d5920e0d6864"
)
EXPECTED_V2_MANIFEST_SHA256 = (
    "14072deebb73f993759272f19ca687649903c201b49f0d5ff78ede926a8dfcb2"
)
EXPECTED_V1_FINGERPRINT = (
    "a60343e423e1ba28c4cf7d43c8a5e771f978640234c8206ba54b9899b3ce518f"
)
EXPECTED_V1_MANIFEST_SHA256 = (
    "294e0c028279a308cdf8571ef6f090501a31bfb0ab7d8f329199d926723a81e0"
)
EXPECTED_BASE_COMMIT = "bbb8309a342574c4cc138584170791e05f2d205e"
EXPECTED_REFERENCE_COUNT = 196
EXPECTED_PAYLOAD_COUNT = 29
BOUNDARY = "\f"
STATUS_VALUES = {"confirmed", "candidate", "unresolved"}
EVALUATOR_VERSION = "1.0.3"
REPORT_SCHEMA = "document-relations-acceptance-eval-v1"
PUBLICATION_RECORD = (
    ROOT / "benchmarks" / "document_relations" / "publication-record.json"
)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _source_tree_sha256(root: Path = ROOT) -> str:
    """Use the established binarydigest source-tree algorithm."""
    digest = hashlib.sha256()
    for path in sorted(
        (root / "src").rglob("*.py"),
        key=lambda item: item.relative_to(root).as_posix(),
    ):
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
            "git_worktree_status": None,
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
    worktree = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    source = subprocess.run(
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
            bool(worktree.stdout.strip()) if worktree.returncode == 0 else None
        ),
        "git_worktree_status": (
            worktree.stdout.splitlines() if worktree.returncode == 0 else None
        ),
        "git_src_worktree_dirty": (
            bool(source.stdout.strip()) if source.returncode == 0 else None
        ),
        "git_src_worktree_status": (
            source.stdout.splitlines() if source.returncode == 0 else None
        ),
    }


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _published_report(report_id: str) -> dict[str, Any]:
    record = _load_json(PUBLICATION_RECORD)
    reports = record.get("reports")
    if not isinstance(reports, list):
        raise ValueError("publication record has no report inventory")
    for report in reports:
        if isinstance(report, Mapping) and report.get("id") == report_id:
            return dict(report)
    raise ValueError(f"publication record has no report entry: {report_id}")


def _published_bundle(version: str) -> dict[str, Any]:
    record = _load_json(PUBLICATION_RECORD)
    bundles = record.get("bundles")
    if not isinstance(bundles, list):
        raise ValueError("publication record has no bundle inventory")
    for bundle in bundles:
        if isinstance(bundle, Mapping) and bundle.get("version") == version:
            return dict(bundle)
    raise ValueError(f"publication record has no bundle entry: {version}")


def _safe_bundle_path(bundle: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or not relative or ".." in candidate.parts:
        raise ValueError(f"unsafe frozen artifact path: {relative!r}")
    resolved = (bundle / candidate).resolve()
    try:
        resolved.relative_to(bundle.resolve())
    except ValueError as exc:
        raise ValueError(f"frozen artifact escapes bundle: {relative}") from exc
    return resolved


def _walk_source_references(value: Any):
    if isinstance(value, Mapping):
        if isinstance(value.get("quote"), str) and _locator(value) is not None:
            yield value
        for child in value.values():
            yield from _walk_source_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_source_references(child)


def _locator(value: Mapping[str, Any]) -> tuple[int, int] | None:
    page = value.get("page", value.get("page_number"))
    line = value.get("line", value.get("line_number"))
    if page is None or line is None:
        locator = value.get("locator")
        match = re.search(r"(?i)p(\d+)[^0-9]+l(\d+)", str(locator or ""))
        if match:
            page, line = match.groups()
    try:
        page_number = int(page)
        line_number = int(line)
    except (TypeError, ValueError):
        return None
    if page_number < 1 or line_number < 1:
        return None
    return page_number, line_number


def _deduplicated_references(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()
    for reference in _walk_source_references(value):
        location = _locator(reference)
        quote = reference.get("quote")
        if location is None or not isinstance(quote, str) or not quote:
            continue
        key = (location[0], location[1], quote)
        if key not in seen:
            seen.add(key)
            result.append({"page": location[0], "line": location[1], "quote": quote})
    return result


def _reference_inventory(
    value: Any,
) -> tuple[list[Mapping[str, Any]], list[dict[str, Any]]]:
    occurrences = [
        reference
        for reference in _walk_source_references(value)
        if isinstance(reference, Mapping)
    ]
    return occurrences, _deduplicated_references(value)


def _validate_source_coordinates(
    bundle: Path, oracle: Mapping[str, Any], manifest: Mapping[str, Any]
) -> dict[str, Any]:
    cases = oracle.get("cases")
    if not isinstance(cases, list):
        raise ValueError("machine oracle must contain a cases list")
    matched = 0
    unique_matched = 0
    per_case: dict[str, int] = {}
    unique_per_case: dict[str, int] = {}
    for case in cases:
        case_id = str(case.get("case_id") or "")
        input_name = case.get("input")
        if not isinstance(input_name, str):
            raise ValueError(f"missing input path for {case_id}")
        input_path = _safe_bundle_path(bundle, input_name)
        raw = input_path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw:
            raise ValueError(f"{case_id} is not clean UTF-8/LF input")
        text = raw.decode("utf-8")
        pages = text.split(BOUNDARY)
        raw_references, unique_case_refs = _reference_inventory(case)
        for reference in raw_references:
            location = _locator(reference)
            assert location is not None
            page, line = location
            quote = str(reference.get("quote") or "")
            if page > len(pages):
                raise ValueError(f"oracle page is outside input for {case_id}")
            physical_lines = pages[page - 1].split("\n")
            if line > len(physical_lines) or quote not in physical_lines[line - 1]:
                raise ValueError(
                    f"source coordinate does not match raw input: "
                    f"{case_id} p{page}l{line}"
                )
            matched += 1
        unique_matched += len(unique_case_refs)
        per_case[case_id] = len(raw_references)
        unique_per_case[case_id] = len(unique_case_refs)

    expected = int(
        manifest.get("source_reference_validation", {}).get("references", -1)
    )
    if (
        matched != EXPECTED_REFERENCE_COUNT
        or matched != expected
        or manifest.get("source_reference_validation", {}).get("status") != "pass"
    ):
        raise ValueError(f"source coordinate coverage mismatch: {matched}/{expected}")
    return {
        "status": "passed",
        "references_checked": matched,
        "denominator": expected,
        "unique_references_checked": unique_matched,
        "unique_denominator": unique_matched,
        "per_case": per_case,
        "unique_per_case": unique_per_case,
        "coordinate_rule": (
            "UTF-8 bytes split on literal U+000C; 1-based LF physical lines; "
            "quoted substring must occur on that exact line; duplicate citation "
            "occurrences count toward the frozen total"
        ),
    }


def verify_bundle(bundle_path: Path) -> dict[str, Any]:
    bundle = bundle_path.resolve(strict=True)
    manifest_path = _safe_bundle_path(bundle, "freeze.json")
    manifest_raw = manifest_path.read_bytes()
    manifest_sha256 = _sha256(manifest_raw)
    if manifest_sha256 != EXPECTED_V2_MANIFEST_SHA256:
        raise ValueError("v2 freeze.json SHA-256 does not match the approved freeze")
    manifest = json.loads(manifest_raw.decode("utf-8"))
    if not isinstance(manifest, Mapping) or manifest.get("manifest_version") != "2.0":
        raise ValueError("unsupported relation bundle manifest")
    if manifest.get("base_commit") != EXPECTED_BASE_COMMIT:
        raise ValueError("relation bundle base commit mismatch")
    if manifest.get("state") != "frozen_not_executed":
        raise ValueError("relation bundle was not frozen as unexecuted")
    if manifest.get("fingerprint", {}).get("sha256") != EXPECTED_V2_FINGERPRINT:
        raise ValueError("approved v2 bundle fingerprint is missing")
    lineage = manifest.get("lineage", {})
    if (
        lineage.get("v1_fingerprint") != EXPECTED_V1_FINGERPRINT
        or lineage.get("v1_freeze_json_sha256") != EXPECTED_V1_MANIFEST_SHA256
    ):
        raise ValueError("v1 lineage does not match the approved history")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != EXPECTED_PAYLOAD_COUNT:
        raise ValueError("v2 manifest must contain exactly 29 payload artifacts")
    checked: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for item in artifacts:
        if not isinstance(item, Mapping):
            raise ValueError("invalid artifact record")
        relative = str(item.get("path") or "")
        if relative in seen_paths:
            raise ValueError(f"duplicate frozen artifact path: {relative}")
        seen_paths.add(relative)
        path = _safe_bundle_path(bundle, relative)
        content = path.read_bytes()
        actual_hash = _sha256(content)
        if actual_hash != item.get("sha256") or len(content) != item.get("bytes"):
            raise ValueError(f"frozen artifact hash/size mismatch: {relative}")
        checked.append({"path": relative, "bytes": len(content), "sha256": actual_hash})

    on_disk = {
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and path.resolve() != manifest_path
    }
    if on_disk != seen_paths:
        raise ValueError("bundle contains missing or unmanifested payload files")
    canonical = "".join(
        f"{item['path']}\t{item['sha256'].lower()}\n"
        for item in sorted(checked, key=lambda entry: entry["path"])
    ).encode("utf-8")
    fingerprint = _sha256(canonical)
    if fingerprint != EXPECTED_V2_FINGERPRINT:
        raise ValueError("v2 payload fingerprint mismatch")

    expected_files = (
        {f"{case_id}.txt" for case_id in EXPECTED_CASE_IDS}
        | {f"{case_id}.oracle.md" for case_id in EXPECTED_CASE_IDS}
        | {"machine-oracle.json"}
    )
    if seen_paths != expected_files:
        raise ValueError("v2 payload set is not the approved 14/14/1 inventory")
    oracle = _load_json(_safe_bundle_path(bundle, "machine-oracle.json"))
    cases = oracle.get("cases")
    if (
        not isinstance(cases, list)
        or [case.get("case_id") for case in cases] != list(EXPECTED_CASE_IDS)
        or oracle.get("execution_state") != "not_run"
    ):
        raise ValueError("machine oracle case order or frozen execution state mismatch")
    for case in cases:
        if (
            case.get("input") != f"{case['case_id']}.txt"
            or case.get("markdown_oracle") != f"{case['case_id']}.oracle.md"
        ):
            raise ValueError(f"oracle/input mapping mismatch: {case.get('case_id')}")
        expected = case.get("expect_confirmed")
        if not isinstance(expected, Mapping):
            raise ValueError(f"missing semantic oracle for {case.get('case_id')}")
        if not isinstance(case.get("forbidden"), list) or not isinstance(
            case.get("needs_review"), list
        ):
            raise ValueError(f"incomplete relation oracle for {case.get('case_id')}")

    coordinates = _validate_source_coordinates(bundle, oracle, manifest)
    return {
        "manifest": manifest,
        "oracle": oracle,
        "bundle": bundle,
        "manifest_sha256": manifest_sha256,
        "bundle_fingerprint": fingerprint,
        "checked_files": checked,
        "source_coordinates": coordinates,
    }


def _status(value: Any) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "confirmed": "confirmed",
        "candidate": "candidate",
        "unresolved": "unresolved",
        "needs_review": "candidate",
        "ambiguous": "candidate",
    }
    return aliases.get(text, text)


def _relation_execution_state(
    decomposition_step: Mapping[str, Any] | None,
) -> tuple[str, str, Mapping[str, Any] | None]:
    if decomposition_step is None:
        return "not_run", "tender-decomposition step absent", None
    step_status = str(decomposition_step.get("status") or "").lower()
    data = decomposition_step.get("data")
    if step_status not in {"success", "partial"}:
        if step_status in {"", "not_run", "skipped"}:
            return "not_run", "tender-decomposition step did not execute", None
        return "failed", f"tender-decomposition status={step_status}", None
    if not isinstance(data, Mapping):
        return "failed", "tender-decomposition returned no object data", None
    analysis = data.get("relation_analysis")
    if not isinstance(analysis, Mapping):
        return "failed", "relation_analysis is missing", None
    declared = str(analysis.get("status") or "").lower()
    executed = analysis.get("executed")
    not_run = analysis.get("not_run")
    unprocessed = analysis.get("unprocessed_structures")
    if isinstance(unprocessed, Mapping):
        unprocessed_reasons = [str(unprocessed.get("reason") or "").lower()]
    elif isinstance(unprocessed, list):
        unprocessed_reasons = [
            str(item.get("reason") or "").lower()
            for item in unprocessed
            if isinstance(item, Mapping)
        ]
    else:
        unprocessed_reasons = []
    if "builder_failed" in unprocessed_reasons:
        return "failed", "relation builder failed for unprocessed structures", data
    if declared == "not_run" or not_run is True or executed is False:
        return "not_run", "relation_analysis explicitly reports not_run", data
    if declared not in {"executed", "success", "partial"} and executed is not True:
        return (
            "failed",
            f"unrecognized relation_analysis state={declared or 'missing'}",
            data,
        )
    graphs = data.get("document_relations")
    if not isinstance(graphs, list) or len(graphs) != 1:
        return "failed", "expected one document_relations graph for one input", data
    graph = graphs[0]
    if not isinstance(graph, Mapping):
        return "failed", "document_relations entry is not an object", data
    schema = graph.get("schema", graph.get("schema_version"))
    if schema != "document-relations-v1":
        return "failed", f"unsupported graph schema={schema!r}", data
    if not isinstance(graph.get("condition_nodes"), list):
        return "failed", "condition_nodes is missing or invalid", data
    if not isinstance(graph.get("block_relations"), list):
        return "failed", "block_relations is missing or invalid", data
    return "executed", "", graph


def _field_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        converted = converter()
        return converted if isinstance(converted, Mapping) else None
    return None


def _runtime_steps(run_result: Any) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for step in getattr(run_result, "steps", []) or []:
        result = getattr(step, "result", None)
        data = _field_mapping(getattr(result, "data", None))
        steps.append(
            {
                "skill_name": str(getattr(step, "skill_name", "")),
                "status": str(getattr(result, "status", "not_run")),
                "data": dict(data) if data is not None else None,
            }
        )
    return steps


def _find_step(steps: list[dict[str, Any]], skill_name: str) -> dict[str, Any] | None:
    matches = [step for step in steps if step["skill_name"] == skill_name]
    return matches[-1] if matches else None


async def _run_input(path: Path, case_id: str) -> dict[str, Any]:
    content = path.read_bytes()
    project_id = f"document-relations-{case_id}"
    registry = ProjectFileRegistry()
    registration = registry.register(
        project_id=project_id,
        file_name=path.name,
        file_role="tender",
        content=content,
    )
    file_id = registration.file.file_id
    registered_checksum = registry.require(file_id).checksum
    if registered_checksum != _sha256(content):
        raise RuntimeError("Registry checksum differs from frozen TXT bytes")
    source_version = registry.file_version_token(file_id)
    source_context = {
        "document_id": file_id,
        "source_version": source_version,
        "pages": content.decode("utf-8").split(BOUNDARY),
        "raw_input_sha256": _sha256(content),
    }
    runtime = AgentRuntime(
        build_default_registry(file_registry=registry),
        services={"file_registry": registry},
    )
    result = await runtime.run(
        SkillRequest.create(
            {
                "project_id": project_id,
                "file_ids": [file_id],
                "bidder_file_ids": [],
                "bidder_id": "synthetic-relations-no-business-materials",
                "bidder_name": "合成关系评测（无企业材料）",
                "task": "分析招标文件",
            }
        )
    )
    steps = _runtime_steps(result)
    decomposition = _find_step(steps, "tender-decomposition")
    state, reason, graph_or_data = _relation_execution_state(decomposition)
    if state != "executed":
        return {
            "execution_state": state,
            "reason": reason,
            "registered_input_sha256": registered_checksum,
            "intake_status": (_find_step(steps, "tender-intake") or {}).get(
                "status", "not_run"
            ),
            "decomposition_status": (decomposition or {}).get("status", "not_run"),
            "graph": None,
        }
    graph = graph_or_data
    assert isinstance(graph, Mapping)
    graph_doc = graph.get("document_id", graph.get("docid"))
    if graph_doc is None or str(graph_doc) != str(file_id):
        return {
            "execution_state": "failed",
            "reason": "graph document identity does not match registered input",
            "registered_input_sha256": registered_checksum,
            "intake_status": (_find_step(steps, "tender-intake") or {}).get(
                "status", "not_run"
            ),
            "decomposition_status": (decomposition or {}).get("status", "not_run"),
            "graph": None,
        }
    graph_version = graph.get("source_version", graph.get("version"))
    if graph_version is None or str(graph_version) != str(source_version):
        return {
            "execution_state": "failed",
            "reason": "graph source version does not match registered input",
            "registered_input_sha256": registered_checksum,
            "intake_status": (_find_step(steps, "tender-intake") or {}).get(
                "status", "not_run"
            ),
            "decomposition_status": (decomposition or {}).get("status", "not_run"),
            "graph": None,
        }
    return {
        "execution_state": "executed",
        "reason": "",
        "registered_input_sha256": registered_checksum,
        "intake_status": (_find_step(steps, "tender-intake") or {}).get(
            "status", "not_run"
        ),
        "decomposition_status": (decomposition or {}).get("status", "not_run"),
        "graph": dict(graph),
        "source_context": source_context,
    }


def _canonical_text(value: Any) -> str:
    text = str(value or "").casefold()
    return "".join(
        char
        for char in text
        if not char.isspace() and not unicodedata.category(char).startswith(("P", "S"))
    )


def _text_similarity(left: Any, right: Any) -> float:
    a = _canonical_text(left)
    b = _canonical_text(right)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    if len(a) < 2 or len(b) < 2:
        return 1.0 if a == b else 0.0
    agrams = {a[index : index + 2] for index in range(len(a) - 1)}
    bgrams = {b[index : index + 2] for index in range(len(b) - 1)}
    return len(agrams & bgrams) / max(1, len(agrams | bgrams))


def _actual_references(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        references = value.get("source_references")
        if isinstance(references, Mapping):
            references = [references]
        if isinstance(references, list):
            return [
                dict(reference)
                for reference in references
                if isinstance(reference, Mapping)
            ]
    return []


def _flatten_reference_payload(value: Any):
    if isinstance(value, Mapping):
        reference_keys = {
            "document_id",
            "docid",
            "source_version",
            "version",
            "page",
            "page_number",
            "locator",
            "line",
            "line_number",
            "quote",
            "char_start",
            "char_end",
            "source_span",
        }
        if reference_keys & set(value):
            yield value
            return
        for child in value.values():
            yield from _flatten_reference_payload(child)
    elif isinstance(value, list):
        for child in value:
            yield from _flatten_reference_payload(child)
    else:
        yield value


def _walk_actual_source_references(value: Any):
    reference_fields = {"source_references", "boundary_source_references"}
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in reference_fields:
                yield from _flatten_reference_payload(child)
            else:
                yield from _walk_actual_source_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_actual_source_references(child)


def _strict_integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _reference_matches(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    actual_location = _locator(actual)
    expected_location = _locator(expected)
    if actual_location != expected_location or actual_location is None:
        return False
    actual_quote = str(actual.get("quote") or "")
    expected_quote = str(expected.get("quote") or "")
    return bool(
        actual_quote
        and expected_quote
        and (actual_quote in expected_quote or expected_quote in actual_quote)
    )


def _references_cover(
    actual_values: Any, expected_values: Any, *, require_all: bool = True
) -> tuple[bool, list[str]]:
    actual_refs = _deduplicated_references(actual_values)
    expected_refs = _deduplicated_references(expected_values)
    missing: list[str] = []
    for expected in expected_refs:
        if not any(_reference_matches(actual, expected) for actual in actual_refs):
            missing.append(f"p{expected['page']}l{expected['line']}")
    if not expected_refs:
        return False, ["no frozen source references"]
    covered = not missing if require_all else len(missing) < len(expected_refs)
    return covered, missing


def _page_line_offsets(page_text: str, line_number: int) -> tuple[int, int] | None:
    start = 0
    for current_line, line in enumerate(page_text.split("\n"), start=1):
        end = start + len(line)
        if current_line == line_number:
            return start, end
        start = end + 1
    return None


def _validate_graph_source_references(
    graph: Mapping[str, Any], source_context: Mapping[str, Any]
) -> dict[str, Any]:
    pages = source_context.get("pages")
    if not isinstance(pages, list):
        pages = []
    expected_document_id = str(source_context.get("document_id") or "")
    expected_version = str(source_context.get("source_version") or "")
    references = list(_walk_actual_source_references(graph))
    normalized_graph = deepcopy(graph)
    normalized_references = list(_walk_actual_source_references(normalized_graph))
    failures: list[dict[str, Any]] = []
    offset_checked = 0
    invalid_indices: set[int] = set()
    resolved_locations: dict[int, tuple[int, int]] = {}
    derived_line_count = 0
    supplied_line_count = 0

    def fail(index: int, reason: str, page: int | None = None, line: int | None = None):
        failure: dict[str, Any] = {"reference_index": index, "reason": reason}
        if page is not None:
            failure["locator"] = f"p{page}l{line}" if line is not None else f"p{page}"
        failures.append(failure)
        invalid_indices.add(index)

    for index, reference in enumerate(references):
        if not isinstance(reference, Mapping):
            fail(index, "not an object")
            continue

        for aliases, expected, reason in (
            (
                ("document_id", "docid"),
                expected_document_id,
                "document identity mismatch",
            ),
            (
                ("source_version", "version"),
                expected_version,
                "source version mismatch",
            ),
        ):
            values = [reference[key] for key in aliases if key in reference]
            if not values or any(str(value or "") != expected for value in values):
                fail(index, reason)

        locator = str(reference.get("locator") or "")
        char_locator = re.search(
            r"(?:^|:)p(\d+):c(\d+)-(\d+)$", locator, flags=re.IGNORECASE
        )
        line_locator = re.search(r"p(\d+):l(\d+)$", locator, flags=re.IGNORECASE)
        if locator and not char_locator and not line_locator:
            fail(index, "source locator format is unsupported")

        page_values = [
            _strict_integer(reference[key])
            for key in ("page", "page_number")
            if key in reference
        ]
        page = page_values[0] if page_values else None
        if (
            not page_values
            and char_locator
            and "page" not in reference
            and "page_number" not in reference
        ):
            page = int(char_locator.group(1))
        if page is None or page < 1 or any(value != page for value in page_values):
            fail(index, "page must be a positive integer", page)

        quote = reference.get("quote")
        if not isinstance(quote, str) or not quote:
            fail(index, "missing exact source quote", page)
            continue

        offset_pairs: list[tuple[Any, Any]] = []
        if "char_start" in reference or "char_end" in reference:
            offset_pairs.append(
                (reference.get("char_start"), reference.get("char_end"))
            )
        elif "start" in reference or "end" in reference:
            offset_pairs.append((reference.get("start"), reference.get("end")))
        span = reference.get("source_span")
        if isinstance(span, Mapping) and ("start" in span or "end" in span):
            offset_pairs.append((span.get("start"), span.get("end")))
        if not offset_pairs:
            fail(index, "raw character offsets are missing", page)
            continue
        valid_offsets: list[tuple[int, int]] = []
        for start_value, end_value in offset_pairs:
            offset_checked += 1
            start = _strict_integer(start_value)
            end = _strict_integer(end_value)
            if start is None or end is None or start < 0 or end <= start:
                fail(
                    index,
                    "raw character offsets are incomplete or invalid",
                    page,
                )
                continue
            valid_offsets.append((start, end))
        if not valid_offsets:
            continue
        start, end = valid_offsets[0]
        if any(pair != (start, end) for pair in valid_offsets[1:]):
            fail(index, "source character offset fields disagree", page)
        if char_locator and (
            int(char_locator.group(1)) != page
            or (int(char_locator.group(2)), int(char_locator.group(3))) != (start, end)
        ):
            fail(index, "locator does not match page and raw character offsets", page)
        if page is None or page < 1:
            continue
        if page > len(pages):
            fail(index, "page is outside registered raw input", page)
            continue

        page_text = str(pages[page - 1])
        if start >= len(page_text) or end > len(page_text):
            fail(index, "raw character offsets are outside the registered page", page)
            continue
        derived_line = page_text.count("\n", 0, start) + 1
        bounds = _page_line_offsets(page_text, derived_line)
        if bounds is None:
            fail(index, "line derived from raw character offsets is invalid", page)
            continue
        line_start, line_end = bounds
        if start < line_start or end > line_end or page_text[start:end] != quote:
            fail(
                index,
                "raw character offsets do not select the exact quote on one line",
                page,
                derived_line,
            )
            continue
        resolved_locations[index] = (page, derived_line)

        for line_key in ("line", "line_number"):
            if line_key not in reference:
                continue
            supplied_line = _strict_integer(reference[line_key])
            if supplied_line is None or supplied_line < 1:
                fail(index, f"{line_key} must be a positive integer", page)
            elif supplied_line != derived_line:
                fail(
                    index,
                    f"{line_key} disagrees with the char_start-derived line",
                    page,
                    derived_line,
                )
            else:
                supplied_line_count += 1
        line_values = [
            reference[key] for key in ("line", "line_number") if key in reference
        ]
        if line_values and any(value != line_values[0] for value in line_values[1:]):
            fail(index, "line and line_number fields disagree", page, derived_line)
        if line_locator:
            locator_page = int(line_locator.group(1))
            locator_line = int(line_locator.group(2))
            if locator_page != page or locator_line != derived_line:
                fail(
                    index,
                    "line locator does not match raw character offsets",
                    page,
                    derived_line,
                )

        if not line_values:
            derived_line_count += 1
            if index < len(normalized_references):
                normalized_references[index]["line_number"] = derived_line

    for index, reference in enumerate(normalized_references):
        if isinstance(reference, dict):
            reference["_raw_coordinate_valid"] = index not in invalid_indices

    unique_keys = set()
    for index, reference in enumerate(references):
        if isinstance(reference, Mapping):
            coordinate = resolved_locations.get(index) or _locator(reference)
            unique_keys.add(
                (
                    str(reference.get("document_id", reference.get("docid", ""))),
                    str(reference.get("source_version", reference.get("version", ""))),
                    coordinate,
                    str(reference.get("quote") or ""),
                )
            )
        else:
            unique_keys.add((str(reference),))
    return {
        "checked_references": len(references),
        "unique_references": len(unique_keys),
        "raw_offsets_checked": offset_checked,
        "invalid_references": len(invalid_indices),
        "line_numbers_derived": derived_line_count,
        "line_numbers_supplied": supplied_line_count,
        "failures": failures,
        "normalized_graph": normalized_graph,
    }


def _node_refs(node: Mapping[str, Any]) -> list[dict[str, Any]]:
    return _actual_references(node)


def _oracle_source(value: Any) -> list[dict[str, Any]]:
    return _deduplicated_references(value)


def _unique_group_failures(
    errors: list[Mapping[str, Any]],
    metric: str,
    eligible_group_ids: set[str],
) -> set[str]:
    return {
        str(error.get("expected_group_id"))
        for error in errors
        if error.get("metric") == metric
        and str(error.get("expected_group_id")) in eligible_group_ids
    }


def _assert_ratio_metric_bounds(metrics: Mapping[str, Mapping[str, Any]]) -> None:
    for name, metric in metrics.items():
        numerator = int(metric.get("numerator", 0))
        denominator = int(metric.get("denominator", 0))
        if numerator < 0 or denominator < 0 or numerator > denominator:
            raise ValueError(
                f"ratio metric {name} is outside its denominator: "
                f"{numerator}/{denominator}"
            )


def _candidate_source_literal_match(
    expected: Mapping[str, Any],
    node: Mapping[str, Any],
    source_refs: list[dict[str, Any]],
) -> bool:
    if _status(expected.get("certainty")) != "candidate":
        return False
    actual_text = str(node.get("text") or "")
    if not actual_text:
        return False
    for expected_ref in source_refs:
        expected_location = _locator(expected_ref)
        expected_quote = str(expected_ref.get("quote") or "")
        if (
            expected_location is None
            or not expected_quote
            or expected_quote not in actual_text
        ):
            continue
        for actual_ref in _node_refs(node):
            if actual_ref.get("_raw_coordinate_valid") is not True:
                continue
            if _locator(actual_ref) != expected_location:
                continue
            if expected_quote in str(actual_ref.get("quote") or ""):
                return True
    return False


def _atom_candidates(
    expected: Mapping[str, Any], actual_nodes: list[Mapping[str, Any]]
) -> list[tuple[int, str]]:
    source_refs = _oracle_source(expected.get("source"))
    candidates: list[tuple[int, str]] = []
    expected_text = expected.get("text", "")
    for node in actual_nodes:
        node_id = node.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            continue
        matched_locations = 0
        exact_quote = 0
        for expected_ref in source_refs:
            for actual_ref in _node_refs(node):
                if _locator(actual_ref) != _locator(expected_ref):
                    continue
                actual_quote = str(actual_ref.get("quote") or "")
                expected_quote = str(expected_ref.get("quote") or "")
                if (
                    actual_quote
                    and expected_quote
                    and (
                        actual_quote in expected_quote or expected_quote in actual_quote
                    )
                ):
                    matched_locations += 1
                    exact_quote += int(actual_quote == expected_quote)
                    break
        similarity = _text_similarity(expected_text, node.get("text"))
        source_literal_match = _candidate_source_literal_match(
            expected, node, source_refs
        )
        if source_literal_match or (matched_locations and similarity >= 0.35):
            candidates.append(
                (
                    matched_locations * 1000
                    + exact_quote * 100
                    + int(similarity * 100),
                    node_id,
                )
            )
    return sorted(candidates, reverse=True)


def _match_atoms(
    case: Mapping[str, Any], graph: Mapping[str, Any]
) -> tuple[dict[str, Mapping[str, Any]], dict[str, str], list[dict[str, Any]]]:
    nodes = graph.get("condition_nodes")
    actual_atoms = [
        node
        for node in (nodes if isinstance(nodes, list) else [])
        if isinstance(node, Mapping) and str(node.get("op", "")).upper() == "ATOM"
    ]
    expected_conditions = [
        condition
        for condition in case.get("conditions", [])
        if isinstance(condition, Mapping)
    ]
    expected_by_id = {
        str(condition.get("id")): condition
        for condition in expected_conditions
        if condition.get("id") is not None
    }
    candidates = {
        atom_id: _atom_candidates(condition, actual_atoms)
        for atom_id, condition in expected_by_id.items()
    }
    chosen: dict[str, str] = {}
    used_actual: set[str] = set()
    ordered = sorted(
        expected_by_id,
        key=lambda atom_id: (len(candidates[atom_id]), atom_id),
    )
    for atom_id in ordered:
        for _, node_id in candidates[atom_id]:
            if node_id not in used_actual:
                chosen[atom_id] = node_id
                used_actual.add(node_id)
                break
    return (
        expected_by_id,
        {key: str(value) for key, value in chosen.items()},
        [
            {
                "expected_id": atom_id,
                "candidate_node_ids": [node_id for _, node_id in candidates[atom_id]],
            }
            for atom_id in expected_by_id
        ],
    )


def _group_members(group: Mapping[str, Any]) -> list[str]:
    members = group.get("members", [])
    if isinstance(members, str):
        return [members]
    if isinstance(members, list):
        return [str(member) for member in members]
    return []


def _node_map(graph: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    nodes = graph.get("condition_nodes")
    if not isinstance(nodes, list):
        return {}
    result: dict[str, Mapping[str, Any]] = {}
    for node in nodes:
        if isinstance(node, Mapping) and isinstance(node.get("node_id"), str):
            result[str(node["node_id"])] = node
    return result


def _children(node: Mapping[str, Any]) -> list[str]:
    values = node.get("children")
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if isinstance(value, str)]


def _descendant_atoms(
    node_id: str,
    nodes: Mapping[str, Mapping[str, Any]],
    atom_to_oracle: Mapping[str, str],
) -> set[str]:
    @lru_cache(maxsize=None)
    def visit(current: str, path: tuple[str, ...]) -> frozenset[str]:
        if current in path or current not in nodes:
            return frozenset()
        node = nodes[current]
        if str(node.get("op", "")).upper() == "ATOM":
            matched = atom_to_oracle.get(current)
            return frozenset({matched}) if matched else frozenset()
        found: set[str] = set()
        for child in _children(node):
            found.update(visit(child, (*path, current)))
        return frozenset(found)

    return set(visit(node_id, ()))


def _expected_group_members(groups: list[Mapping[str, Any]], group_id: str) -> set[str]:
    by_id = {str(group.get("id")): group for group in groups if group.get("id")}

    def visit(identifier: str, seen: frozenset[str]) -> set[str]:
        if identifier in seen:
            return set()
        if identifier not in by_id:
            return {identifier}
        result: set[str] = set()
        for member in _group_members(by_id[identifier]):
            result.update(visit(member, seen | {identifier}))
        return result

    return visit(group_id, frozenset())


def _scope_components(graph: Mapping[str, Any]) -> list[set[str]]:
    nodes = _node_map(graph)
    adjacency: dict[str, set[str]] = defaultdict(set)

    def connect(source: str, targets: Any) -> None:
        if isinstance(targets, str):
            targets = [targets]
        if not isinstance(targets, list):
            return
        for target in targets:
            target_id = str(target)
            if target_id in nodes and target_id != source:
                adjacency[source].add(target_id)
                adjacency[target_id].add(source)

    for node_id, node in nodes.items():
        relation = node.get("scope_relation")
        if (
            isinstance(relation, Mapping)
            and _status(relation.get("status")) == "confirmed"
        ):
            connect(node_id, relation.get("target_node_ids"))

    block_to_nodes: dict[str, set[str]] = defaultdict(set)
    for node_id, node in nodes.items():
        for block_id in node.get("source_block_ids") or []:
            block_to_nodes[str(block_id)].add(node_id)
    block_relations = graph.get("block_relations")
    if isinstance(block_relations, list):
        for block in block_relations:
            if not isinstance(block, Mapping):
                continue
            source_block = str(block.get("block_id") or "")
            relations = block.get("scope_relations")
            if not isinstance(relations, list):
                continue
            for relation in relations:
                if (
                    not isinstance(relation, Mapping)
                    or _status(relation.get("status")) != "confirmed"
                ):
                    continue
                targets = relation.get("target_block_ids") or []
                if isinstance(targets, str):
                    targets = [targets]
                source_nodes = block_to_nodes.get(source_block, set())
                target_nodes = {
                    node_id
                    for target in targets
                    for node_id in block_to_nodes.get(str(target), set())
                }
                for source in source_nodes:
                    connect(source, list(target_nodes))

    components: list[set[str]] = []
    visited: set[str] = set()
    for start in adjacency:
        if start in visited:
            continue
        stack = [start]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.add(current)
            stack.extend(adjacency.get(current, set()) - visited)
        atoms = {
            nodes[node_id].get("node_id")
            for node_id in component
            if str(nodes[node_id].get("op", "")).upper() == "ATOM"
        }
        if atoms:
            components.append({str(atom) for atom in atoms})
    return components


def _operator_source_refs(node: Mapping[str, Any]) -> list[dict[str, Any]]:
    operator = node.get("operator_relation")
    return _actual_references(operator) if isinstance(operator, Mapping) else []


def _group_source_refs(node: Mapping[str, Any]) -> list[dict[str, Any]]:
    combined = _operator_source_refs(node)
    scope = node.get("scope_relation")
    if isinstance(scope, Mapping):
        combined.extend(_actual_references(scope))
        combined.extend(
            _deduplicated_references(scope.get("boundary_source_references"))
        )
    return combined


def _operator_cues(operator: str, quote: str) -> set[str]:
    cues = {
        "AND": (
            "均须同时",
            "必须同时",
            "须同时",
            "同时提交",
            "同时满足",
            "均须",
            "均应",
            "均需",
            "全部提交",
            "全部满足",
            "并须",
            "并且",
            "以及",
            "及",
            "且",
        ),
        "OR": (
            "任选一项",
            "任选其一",
            "任一项",
            "任一条件",
            "任选",
            "择一",
            "只需择一",
            "二选一",
            "之一",
            "或",
        ),
    }
    return {cue for cue in cues.get(operator, ()) if cue in quote}


def _operator_evidence(
    group: Mapping[str, Any], node: Mapping[str, Any]
) -> tuple[bool, str]:
    operator = str(group.get("operator") or "").upper()
    relation = node.get("operator_relation")
    if (
        not isinstance(relation, Mapping)
        or _status(relation.get("status")) != "confirmed"
    ):
        return False, "operator_relation is not confirmed"

    basis = _oracle_source(group.get("boundary_basis"))
    cue_basis = [
        (reference, _operator_cues(operator, str(reference.get("quote") or "")))
        for reference in basis
    ]
    cue_basis = [(reference, cues) for reference, cues in cue_basis if cues]
    if not cue_basis:
        return False, "frozen boundary_basis has no recognized explicit operator cue"

    actual_refs = _actual_references(relation)
    if not actual_refs:
        return False, "operator_relation has no source references"
    for actual in actual_refs:
        actual_cues = _operator_cues(operator, str(actual.get("quote") or ""))
        if not any(
            _reference_matches(actual, expected) and bool(actual_cues & expected_cues)
            for expected, expected_cues in cue_basis
        ):
            return False, "operator source does not cite its matching explicit cue"
    for expected, expected_cues in cue_basis:
        if not any(
            _reference_matches(actual, expected)
            and bool(
                _operator_cues(operator, str(actual.get("quote") or "")) & expected_cues
            )
            for actual in actual_refs
        ):
            return False, "operator_relation does not cover every explicit cue source"
    return True, ""


def _scope_evidence(
    group: Mapping[str, Any],
    source_references: Any,
    boundary_references: Any,
    member_nodes: list[Mapping[str, Any]],
) -> tuple[bool, str, bool, str]:
    basis = _oracle_source(group.get("boundary_basis"))
    if not basis:
        return (
            False,
            "frozen group has no boundary_basis",
            False,
            ("frozen group has no boundary_basis"),
        )

    members_without_sources = [
        str(node.get("node_id") or "<unknown>")
        for node in member_nodes
        if not _node_refs(node)
    ]
    actual_scope_refs = _deduplicated_references(source_references)
    member_refs = [reference for node in member_nodes for reference in _node_refs(node)]
    scope_basis = [*basis, *member_refs]
    scope_supported = (
        bool(actual_scope_refs)
        and any(
            _reference_matches(actual, expected)
            for actual in actual_scope_refs
            for expected in scope_basis
        )
        and not members_without_sources
    )
    if members_without_sources:
        scope_reason = "scope members lack source references: " + ", ".join(
            members_without_sources
        )
    elif not scope_supported:
        scope_reason = (
            "scope source does not match a frozen boundary or a cited member source"
        )
    else:
        scope_reason = ""

    boundary_refs = _deduplicated_references(boundary_references)
    boundary_covered, missing = _references_cover(boundary_refs, basis)
    if not boundary_covered:
        boundary_reason = (
            "termination boundary does not cover frozen boundary_basis: "
            + ", ".join(missing)
        )
    else:
        boundary_reason = ""
    return scope_supported, scope_reason, boundary_covered, boundary_reason


def _match_groups(
    case: Mapping[str, Any],
    graph: Mapping[str, Any],
    atom_map: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, set[str]], list[dict[str, Any]]]:
    expected_groups = [
        group for group in case.get("groups", []) if isinstance(group, Mapping)
    ]
    expected_group_ids = {
        str(group.get("id")) for group in expected_groups if group.get("id") is not None
    }
    nodes = _node_map(graph)
    actual_group_nodes = {
        node_id: node
        for node_id, node in nodes.items()
        if str(node.get("op", "")).upper() in {"AND", "OR"}
    }
    components = _scope_components(graph)
    group_map: dict[str, str] = {}
    member_map: dict[str, set[str]] = {}
    errors: list[dict[str, Any]] = []
    pending = {
        str(group.get("id")): group
        for group in expected_groups
        if group.get("id") is not None
    }

    def resolve_member(member: str) -> str | None:
        if member in expected_group_ids:
            return group_map.get(member)
        return atom_map.get(member)

    progress = True
    while pending and progress:
        progress = False
        for group_id, group in list(pending.items()):
            members = _group_members(group)
            resolved = [resolve_member(member) for member in members]
            if any(value is None for value in resolved):
                continue
            expected_children = {str(value) for value in resolved}
            operator = str(group.get("operator") or "").upper()
            status = _status(group.get("status"))
            selected: str | None = None
            if operator in {"AND", "OR"}:
                for node_id, node in actual_group_nodes.items():
                    if (
                        str(node.get("op", "")).upper() == operator
                        and set(_children(node)) == expected_children
                        and _status(node.get("status")) == status == "confirmed"
                    ):
                        selected = node_id
                        break
                if selected is not None:
                    selected_node = actual_group_nodes[selected]
                    operator_ok, operator_reason = _operator_evidence(
                        group, selected_node
                    )
                    if not operator_ok:
                        errors.append(
                            {
                                "metric": "operator_evidence",
                                "expected_group_id": group_id,
                                "reason": operator_reason,
                            }
                        )
                        selected = None
                    if selected is None:
                        continue
                    scope_relation = selected_node.get("scope_relation")
                    raw_targets = (
                        scope_relation.get("target_node_ids")
                        if isinstance(scope_relation, Mapping)
                        else []
                    ) or []
                    if isinstance(raw_targets, str):
                        raw_targets = [raw_targets]
                    actual_targets = {
                        str(value) for value in raw_targets if isinstance(value, str)
                    }
                    expected_leaves = {
                        atom_map[atom]
                        for atom in _expected_group_members(expected_groups, group_id)
                        if atom in atom_map
                    }
                    if frozenset(actual_targets) not in {
                        frozenset(expected_children),
                        frozenset(expected_leaves),
                    }:
                        errors.append(
                            {
                                "metric": "scope_evidence",
                                "expected_group_id": group_id,
                                "reason": (
                                    "scope target_node_ids do not match expected "
                                    "members"
                                ),
                            }
                        )
                        selected = None
                    if selected is None:
                        continue
                    scope_ok, scope_reason, boundary_ok, boundary_reason = (
                        _scope_evidence(
                            group,
                            scope_relation.get("source_references"),
                            scope_relation.get("boundary_source_references"),
                            [
                                nodes[child]
                                for child in expected_children
                                if child in nodes
                            ],
                        )
                    )
                    if not scope_ok:
                        errors.append(
                            {
                                "metric": "scope_evidence",
                                "expected_group_id": group_id,
                                "reason": scope_reason,
                            }
                        )
                    if not boundary_ok:
                        errors.append(
                            {
                                "metric": "boundary_evidence",
                                "expected_group_id": group_id,
                                "reason": boundary_reason,
                            }
                        )
                    if not scope_ok or not boundary_ok:
                        selected = None
            elif operator == "REQUIRED" and len(resolved) == 1:
                candidate = str(resolved[0])
                for node_id, group_node in actual_group_nodes.items():
                    if (
                        str(group_node.get("op", "")).upper() != "AND"
                        or set(_children(group_node)) != {candidate}
                        or _status(group_node.get("status")) != "confirmed"
                    ):
                        continue
                    operator_relation = group_node.get("operator_relation")
                    scope_relation = group_node.get("scope_relation")
                    if (
                        not isinstance(operator_relation, Mapping)
                        or _status(operator_relation.get("status")) != "confirmed"
                    ):
                        continue
                    if (
                        not isinstance(scope_relation, Mapping)
                        or _status(scope_relation.get("status")) != "confirmed"
                    ):
                        continue
                    targets = scope_relation.get("target_node_ids") or []
                    if isinstance(targets, str):
                        targets = [targets]
                    if {str(value) for value in targets} != {candidate}:
                        continue
                    operator_source_ok, operator_missing = _references_cover(
                        _operator_source_refs(group_node),
                        group.get("boundary_basis"),
                    )
                    scope_ok, scope_reason, boundary_ok, boundary_reason = (
                        _scope_evidence(
                            group,
                            scope_relation.get("source_references"),
                            scope_relation.get("boundary_source_references"),
                            [nodes[candidate]] if candidate in nodes else [],
                        )
                    )
                    if not operator_source_ok:
                        errors.append(
                            {
                                "metric": "scope_evidence",
                                "expected_group_id": group_id,
                                "missing_locators": operator_missing,
                                "reason": (
                                    "unary REQUIRED boundary lacks operator source"
                                ),
                            }
                        )
                    if not scope_ok:
                        errors.append(
                            {
                                "metric": "scope_evidence",
                                "expected_group_id": group_id,
                                "reason": scope_reason,
                            }
                        )
                    if not boundary_ok:
                        errors.append(
                            {
                                "metric": "boundary_evidence",
                                "expected_group_id": group_id,
                                "reason": boundary_reason,
                            }
                        )
                    if not operator_source_ok or not scope_ok or not boundary_ok:
                        continue
                    selected = node_id
                    break
                if selected is None:
                    node = nodes.get(candidate)
                    if node and _status(node.get("status")) == "confirmed":
                        selected = candidate
            elif status == "confirmed":
                expected_atoms = _expected_group_members(expected_groups, group_id)
                expected_actual_atoms = {
                    atom_map[atom] for atom in expected_atoms if atom in atom_map
                }
                for component in components:
                    if component == expected_actual_atoms:
                        scope_nodes = [
                            nodes[node_id] for node_id in component if node_id in nodes
                        ]
                        scope_refs = [
                            reference
                            for node in scope_nodes
                            for reference in _actual_references(
                                node.get("scope_relation")
                            )
                        ]
                        boundary_refs = [
                            reference
                            for node in scope_nodes
                            if isinstance(node.get("scope_relation"), Mapping)
                            for reference in _deduplicated_references(
                                node["scope_relation"].get("boundary_source_references")
                            )
                        ]
                        scope_ok, scope_reason, boundary_ok, boundary_reason = (
                            _scope_evidence(
                                group,
                                scope_refs,
                                boundary_refs,
                                scope_nodes,
                            )
                        )
                        if not scope_ok:
                            errors.append(
                                {
                                    "metric": "scope_evidence",
                                    "expected_group_id": group_id,
                                    "reason": scope_reason,
                                }
                            )
                        if not boundary_ok:
                            errors.append(
                                {
                                    "metric": "boundary_evidence",
                                    "expected_group_id": group_id,
                                    "reason": boundary_reason,
                                }
                            )
                        if scope_ok and boundary_ok:
                            selected = "scope:" + ",".join(sorted(component))
                        break
            if selected is not None:
                group_map[group_id] = selected
                if selected.startswith("scope:"):
                    member_map[group_id] = {
                        atom
                        for atom in _expected_group_members(expected_groups, group_id)
                    }
                else:
                    member_map[group_id] = _descendant_atoms(
                        selected, nodes, {value: key for key, value in atom_map.items()}
                    )
                    if not member_map[group_id] and operator == "REQUIRED":
                        atom_id = next(
                            (
                                member
                                for member in members
                                if atom_map.get(member) == selected
                            ),
                            None,
                        )
                        if atom_id:
                            member_map[group_id] = {atom_id}
                del pending[group_id]
                progress = True
            elif all(value is not None for value in resolved) and operator in {
                "AND",
                "OR",
            }:
                errors.append(
                    {
                        "metric": "group_structure",
                        "expected_group_id": group_id,
                        "expected_operator": operator,
                        "expected_direct_members": members,
                        "reason": "confirmed operator node missing exact children",
                    }
                )
                del pending[group_id]
                progress = True

    for group_id, group in pending.items():
        if _status(group.get("status")) == "confirmed":
            errors.append(
                {
                    "metric": "group_structure",
                    "expected_group_id": group_id,
                    "expected_operator": group.get("operator"),
                    "expected_direct_members": _group_members(group),
                    "reason": "expected nested member could not be resolved",
                }
            )
    return group_map, member_map, errors


def _parent_relation_kind(relation: Mapping[str, Any]) -> str:
    layer = str(relation.get("layer") or "").strip().lower()
    if layer in {"structural_list", "list_membership", "visible_list_membership"}:
        return "structural_list"
    claim = str(relation.get("claim") or "")
    if "可见条目" in claim and "枚举" in claim:
        return "structural_list"
    return "semantic"


_STRUCTURAL_LIST_LAYERS = {
    "structural_list",
    "list_membership",
    "visible_list_membership",
}
_SEMANTIC_PARENT_LAYERS = {
    "semantic_parent",
    "logical_parent",
    "condition_parent",
    "attribute_parent",
    "contextual_parent",
}
_LIST_CUE = re.compile(
    r"如下|下列|以下(?:任一|各|[一二三四五六七八九十\d]+)?"
    r"(?:类|项|种|份|个|材料|条件|要求|内容)|清单|列表|列举|列示"
)


def _relation_layer(relation: Mapping[str, Any]) -> str:
    layer = relation.get("layer", relation.get("relation_layer"))
    return str(layer or "").strip().lower()


def _relation_has_basis(relation: Mapping[str, Any]) -> bool:
    def has_content(value: Any) -> bool:
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, Mapping):
            return any(has_content(item) for item in value.values())
        if isinstance(value, (list, tuple, set)):
            return any(has_content(item) for item in value)
        return False

    for key in ("basis", "relation_basis", "basis_text"):
        if has_content(relation.get(key)):
            return True
    return False


def _is_typed_relation(
    relation: Mapping[str, Any], accepted_layers: set[str]
) -> bool:
    return _relation_layer(relation) in accepted_layers and _relation_has_basis(
        relation
    )


def _is_explicit_list_cue(value: Any) -> bool:
    return bool(_LIST_CUE.search(str(value or "")))


def _relation_targets(relation: Mapping[str, Any]) -> dict[str, set[str]]:
    targets: dict[str, set[str]] = {}
    for field in ("target_node_ids", "target_block_ids"):
        values = relation.get(field) or []
        if isinstance(values, str):
            values = [values]
        targets[field] = (
            {str(value) for value in values if value is not None}
            if isinstance(values, list)
            else set()
        )
    return targets


def _records_from_node_parent(node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    values = node.get("parent_relations")
    if isinstance(values, Mapping):
        return [values]
    if isinstance(values, list):
        return [value for value in values if isinstance(value, Mapping)]
    return []


def _structural_list_parent_match(
    relation: Mapping[str, Any],
    child_ids: list[str],
    atom_map: Mapping[str, str],
    group_map: Mapping[str, str],
    nodes: Mapping[str, Mapping[str, Any]],
    graph: Mapping[str, Any],
) -> tuple[bool, list[str]]:
    expected_refs = _oracle_source(relation.get("source"))
    cue_refs = [
        reference
        for reference in expected_refs
        if _is_explicit_list_cue(reference.get("quote"))
    ]
    if not cue_refs:
        return False, ["frozen structural parent source has no explicit list cue"]

    child_node_ids = {
        atom_map.get(child_id) or group_map.get(child_id) or child_id
        for child_id in child_ids
    }
    if not child_node_ids or any(node_id not in nodes for node_id in child_node_ids):
        return False, ["structural-list child condition node is missing"]
    if not expected_refs:
        return False, ["structural-list parent has no explicit source cue"]

    block_records: dict[str, Mapping[str, Any]] = {}
    for block in graph.get("block_relations", []):
        if not isinstance(block, Mapping) or not block.get("block_id"):
            continue
        block_records[str(block["block_id"])] = block

    per_child_records: dict[str, list[Mapping[str, Any]]] = {}
    last_missing: list[str] = []

    for child_node_id in child_node_ids:
        child = nodes[child_node_id]
        records = _records_from_node_parent(child)
        for block_id in child.get("source_block_ids") or []:
            child_block = block_records.get(str(block_id))
            block_parent = (
                child_block.get("parent_relation")
                if isinstance(child_block, Mapping)
                else None
            )
            if isinstance(block_parent, Mapping):
                records.append(block_parent)
        per_child_records[child_node_id] = [
            record
            for record in records
            if _status(record.get("status")) == "confirmed"
            and _is_typed_relation(record, _STRUCTURAL_LIST_LAYERS)
            and any(_relation_targets(record).values())
        ]

    if all(per_child_records.values()):
        target_sets: list[set[tuple[str, str]]] = []
        for records in per_child_records.values():
            target_sets.append(
                {
                    (field, target)
                    for record in records
                    for field, targets in _relation_targets(record).items()
                    for target in targets
                }
            )
        shared_targets = set.intersection(*target_sets) if target_sets else set()
        for target_kind, target_id in shared_targets:
            if target_kind == "target_node_ids":
                target_node = nodes.get(target_id)
                target_block = None
                target_refs = _node_refs(target_node) if target_node else []
            else:
                target_block = block_records.get(target_id)
                target_node = None
                target_relation = (
                    target_block.get("parent_relation")
                    if isinstance(target_block, Mapping)
                    else None
                )
                target_refs = _actual_references(target_relation)
            if target_node is None and target_block is None:
                last_missing = ["structural parent target does not exist"]
                continue
            cue_covered, _ = _references_cover(target_refs, cue_refs)
            target_has_cue = cue_covered and any(
                _is_explicit_list_cue(reference.get("quote"))
                and any(
                    _reference_matches(reference, cue_reference)
                    for cue_reference in cue_refs
                )
                for reference in target_refs
            )
            if not target_has_cue:
                last_missing = [
                    "structural parent target has no source-backed explicit list cue"
                ]
                continue
            refs = [
                reference
                for records in per_child_records.values()
                for record in records
                if target_id
                in _relation_targets(record).get(target_kind, set())
                for reference in _actual_references(record)
            ]
            every_child_cites_cue = all(
                any(
                    target_id
                    in _relation_targets(record).get(target_kind, set())
                    and any(
                        _reference_matches(actual_ref, cue_ref)
                        for actual_ref in _actual_references(record)
                        for cue_ref in cue_refs
                    )
                    for record in records
                )
                for records in per_child_records.values()
            )
            if not every_child_cites_cue:
                last_missing = [
                    "structural child links do not independently cite the list cue"
                ]
                continue
            covered, missing = _references_cover(refs, expected_refs)
            if covered:
                return True, []
            if missing:
                last_missing = missing

    return False, last_missing or [
        "no confirmed structural parent links all visible list members"
    ]


def _explicit_semantic_parent_match(
    relation: Mapping[str, Any],
    child_ids: list[str],
    atom_map: Mapping[str, str],
    nodes: Mapping[str, Mapping[str, Any]],
    graph: Mapping[str, Any],
) -> tuple[bool, list[str]]:
    parent_labels = re.findall(
        r"(?<![A-Za-z0-9])A\d+(?![A-Za-z0-9])",
        str(relation.get("parent") or ""),
        flags=re.IGNORECASE,
    )
    if len(parent_labels) != 1:
        return False, ["oracle parent does not identify one condition node"]
    parent_node_id = atom_map.get(parent_labels[0].upper())
    parent_node = nodes.get(parent_node_id or "")
    if parent_node is None:
        return False, ["explicit semantic parent condition node is missing"]
    parent_block_ids = {
        str(value) for value in parent_node.get("source_block_ids") or []
    }
    existing_block_ids = {
        str(block["block_id"])
        for block in graph.get("block_relations", [])
        if isinstance(block, Mapping) and block.get("block_id") is not None
    }
    parent_block_ids &= existing_block_ids
    expected_refs = _oracle_source(relation.get("source"))
    if not expected_refs:
        return False, ["semantic parent has no frozen source references"]

    missing: list[str] = []
    for child_id in child_ids:
        child_node = nodes.get(atom_map.get(child_id, ""))
        if child_node is None:
            return False, [f"semantic child condition node is missing: {child_id}"]
        for record in _records_from_node_parent(child_node):
            if _status(record.get("status")) != "confirmed" or not _is_typed_relation(
                record, _SEMANTIC_PARENT_LAYERS
            ):
                continue
            targets = _relation_targets(record)
            target_match = (
                parent_node_id in targets["target_node_ids"]
                or bool(parent_block_ids & targets["target_block_ids"])
            )
            if not target_match:
                continue
            covered, unmatched = _references_cover(
                _actual_references(record), expected_refs
            )
            if covered:
                break
            missing = unmatched
        else:
            return False, missing or [
                f"no confirmed directed parent relation for {child_id}"
            ]
    return True, []


def _semantic_parent_match(
    relation: Mapping[str, Any],
    case: Mapping[str, Any],
    group_map: Mapping[str, str],
    group_members: Mapping[str, set[str]],
    nodes: Mapping[str, Mapping[str, Any]],
    atom_map: Mapping[str, str],
    graph: Mapping[str, Any],
) -> tuple[bool, list[str]]:
    child_ids = relation.get("children")
    if not isinstance(child_ids, list) or not child_ids:
        return False, ["no semantic children in oracle"]
    child_ids = [str(child_id) for child_id in child_ids]
    if _parent_relation_kind(relation) == "structural_list":
        return _structural_list_parent_match(
            relation, child_ids, atom_map, group_map, nodes, graph
        )

    explicit_match, explicit_missing = _explicit_semantic_parent_match(
        relation, child_ids, atom_map, nodes, graph
    )
    if explicit_match:
        return True, []
    resolved = {group_map.get(str(child)) or str(child) for child in child_ids}
    expected_refs = _oracle_source(relation.get("source"))
    groups = {
        str(group.get("id")): group
        for group in case.get("groups", [])
        if isinstance(group, Mapping) and group.get("id") is not None
    }
    for group_id, group in groups.items():
        if set(_group_members(group)) != {str(child) for child in child_ids}:
            continue
        actual_id = group_map.get(group_id)
        if not actual_id:
            continue
        if actual_id.startswith("scope:"):
            actual_node_ids = set(actual_id.removeprefix("scope:").split(","))
            actual_refs: list[dict[str, Any]] = []
            for node_id in actual_node_ids:
                scope_relation = nodes.get(node_id, {}).get("scope_relation")
                if (
                    isinstance(scope_relation, Mapping)
                    and _status(scope_relation.get("status")) == "confirmed"
                ):
                    actual_refs.extend(_actual_references(scope_relation))
                    actual_refs.extend(
                        _deduplicated_references(
                            scope_relation.get("boundary_source_references")
                        )
                    )
            covered, missing = _references_cover(actual_refs, expected_refs)
            expected_members = _expected_group_members(
                [
                    entry
                    for entry in case.get("groups", [])
                    if isinstance(entry, Mapping)
                ],
                group_id,
            )
            if group_members.get(group_id) == expected_members and covered:
                return True, []
            return False, missing or ["confirmed semantic scope parent is missing"]
        node = nodes.get(actual_id)
        if node is None:
            continue
        actual_refs = _group_source_refs(node)
        covered, missing = _references_cover(actual_refs, expected_refs)
        if _status(node.get("status")) == "confirmed" and covered:
            return True, []
        return False, missing or ["semantic group parent is not confirmed"]
    semantic_candidates = []
    for node_id, node in nodes.items():
        if str(node.get("op", "")).upper() not in {"AND", "OR"}:
            continue
        direct = set(_children(node))
        if direct == resolved and _status(node.get("status")) == "confirmed":
            semantic_candidates.append(node)
    for node in semantic_candidates:
        covered, missing = _references_cover(_group_source_refs(node), expected_refs)
        if covered:
            return True, []
        return False, missing
    return False, explicit_missing or ["no confirmed semantic group parent matched"]


def _relation_records(
    graph: Mapping[str, Any], relation_type: str
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    nodes = graph.get("condition_nodes")
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, Mapping):
                continue
            if relation_type == "scope":
                relation = node.get("scope_relation")
                if isinstance(relation, Mapping):
                    records.append(dict(relation))
            elif relation_type == "parent":
                values = node.get("parent_relations")
                if isinstance(values, Mapping):
                    values = [values]
                if isinstance(values, list):
                    records.extend(
                        dict(item) for item in values if isinstance(item, Mapping)
                    )
    blocks = graph.get("block_relations")
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, Mapping):
                continue
            if relation_type == "parent":
                relation = block.get("parent_relation")
                if isinstance(relation, Mapping):
                    records.append({**dict(relation), "_physical_parent": True})
            else:
                values = block.get(f"{relation_type}_relations")
                if isinstance(values, Mapping):
                    values = [values]
                if isinstance(values, list):
                    records.extend(
                        dict(item) for item in values if isinstance(item, Mapping)
                    )
    if relation_type == "reference":
        values = graph.get("references")
        if isinstance(values, list):
            records.extend(dict(item) for item in values if isinstance(item, Mapping))
    return records


def _review_groups(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for item in case.get("needs_review", []):
        if not isinstance(item, Mapping):
            continue
        key = (str(item.get("type") or ""), str(item.get("condition_id") or ""))
        group = grouped.setdefault(
            key,
            {
                "type": key[0],
                "condition_id": key[1] or None,
                "allowed_statuses": set(),
                "sources": [],
            },
        )
        status = _status(item.get("status"))
        if status in STATUS_VALUES:
            group["allowed_statuses"].add(status)
        group["sources"].extend(_oracle_source(item.get("source")))
    for group in grouped.values():
        unique = {
            (ref["page"], ref["line"], ref["quote"]): ref for ref in group["sources"]
        }
        group["sources"] = list(unique.values())
        group["allowed_statuses"] = sorted(group["allowed_statuses"])
    return list(grouped.values())


def _operator_relation_records(graph: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    def relation_values(value: Any) -> list[Mapping[str, Any]]:
        if isinstance(value, Mapping):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
        return []

    def add(
        relation: Any, *wrappers: Mapping[str, Any]
    ) -> None:
        if not isinstance(relation, Mapping):
            return
        relation_status = _status(relation.get("status"))
        if not relation_status:
            return
        for wrapper in wrappers:
            wrapper_status = wrapper.get("operator_status")
            if (
                wrapper_status is not None
                and str(wrapper_status).strip()
                and _status(wrapper_status) != relation_status
            ):
                return
        records.append(dict(relation))

    nodes = graph.get("condition_nodes")
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, Mapping):
                continue
            add(node.get("operator_relation"), node)
            scope = node.get("scope_relation")
            if isinstance(scope, Mapping):
                add(scope.get("operator_relation"), node, scope)

    blocks = graph.get("block_relations")
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, Mapping):
                continue
            for relation in relation_values(block.get("operator_relations")):
                add(relation, block)
            for scope in relation_values(block.get("scope_relations")):
                add(scope.get("operator_relation"), block, scope)

    return records


def _review_item_covered(
    item: Mapping[str, Any],
    graph: Mapping[str, Any],
    atom_nodes: Mapping[str, Mapping[str, Any]],
) -> tuple[bool, str]:
    relation_type = str(item.get("type") or "")
    expected_statuses = set(item.get("allowed_statuses") or [])
    expected_sources = item.get("sources") or []
    if relation_type == "condition":
        condition_id = item.get("condition_id")
        node = atom_nodes.get(str(condition_id))
        if node is None:
            return False, "candidate atom missing"
        actual_refs = _node_refs(node)
        covered, _ = _references_cover(actual_refs, expected_sources)
        if _status(node.get("status")) in expected_statuses and covered:
            return True, ""
        return False, "candidate atom status/source mismatch"
    if relation_type not in {"parent", "scope", "reference", "operator"}:
        return False, "unsupported review relation type"
    if relation_type == "operator":
        records = _operator_relation_records(graph)
    else:
        records = _relation_records(graph, relation_type)
    for record in records:
        status = _status(record.get("status"))
        if status not in expected_statuses:
            continue
        actual_refs = _actual_references(record)
        if relation_type != "operator" and isinstance(
            record.get("boundary_source_references"), list
        ):
            actual_refs.extend(
                _deduplicated_references(record["boundary_source_references"])
            )
        covered, _ = _references_cover(actual_refs, expected_sources)
        if covered:
            return True, ""
    return False, "review relation status/source mismatch"


def _classify_forbidden_scope(claim: str) -> str:
    text = re.sub(r"\s+", "", claim)
    if re.search(
        r"(?:不得|不能|不可|不应|禁止|不可以).{0,35}(?:并成|合并|并入|归入)",
        text,
    ):
        return "prohibit_merge"
    if re.search(
        r"(?:不得|不能|不可|不应|禁止|不可以).{0,24}"
        r"(?:排除|遗漏|漏掉|省略|不纳入|不包括|不包含)",
        text,
    ):
        return "require_members"
    if re.search(r"(?:不得|不能|不可|不应|禁止|不可以).{0,24}忽略", text):
        return "require_members"
    if re.search(r"(?:不得|不能|不可|不应|禁止|不可以).{0,32}确认", text):
        return "prohibit_confirmation"
    return "unclassified"


def _classify_forbidden_condition(claim: str) -> str:
    text = re.sub(r"\s+", "", claim)
    if (
        re.search(r"(?:编号|序号).{0,16}(?:小数|金额条件|材料条件)", text)
        or re.search(r"(?:金额|万元|元).{0,16}(?:编号|材料条件)", text)
    ) and re.search(r"(?:生成额外|误当|识别成|解释为|误识别)", text):
        return "prohibit_numeric_material_atom"
    return "unclassified"


def _looks_like_numeric_material_atom(node: Mapping[str, Any]) -> bool:
    text = str(node.get("text") or "")
    quotes = " ".join(
        str(reference.get("quote") or "") for reference in _node_refs(node)
    )
    combined = text + " " + quotes
    has_decimal = re.search(r"(?<!\d)\d+\.\d+(?!\d)", combined) is not None
    has_context = (
        re.search(
            r"(?:万(?:元)?|人民币|金额|预算|材料|证明|证书|资质|编号|序号|提交|提供)",
            combined,
        )
        is not None
    )
    return has_decimal and has_context


def _actual_confirmed_group_members(
    graph: Mapping[str, Any], atom_map: Mapping[str, str]
) -> list[tuple[str, str, set[str]]]:
    nodes = _node_map(graph)
    reverse_atoms = {actual: expected for expected, actual in atom_map.items()}
    result: list[tuple[str, str, set[str]]] = []
    for node_id, node in nodes.items():
        operator = str(node.get("op", "")).upper()
        if operator not in {"AND", "OR"} or _status(node.get("status")) != "confirmed":
            continue
        members = _descendant_atoms(node_id, nodes, reverse_atoms)
        result.append((node_id, operator, members))
    for index, component in enumerate(_scope_components(graph)):
        members = {reverse_atoms[node] for node in component if node in reverse_atoms}
        if members:
            result.append((f"scope-component-{index}", "SCOPE", members))
    return result


def _locator_mentions(text: Any) -> tuple[int, int] | None:
    match = re.search(r"(?i)p(\d+)\s*[-:]\s*l(\d+)", str(text or ""))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _source_locations(value: Any) -> set[tuple[int, int]]:
    return {
        location
        for reference in _oracle_source(value)
        if (location := _locator(reference)) is not None
    }


def _forbidden_flattened_scope(
    members: set[str],
    graph: Mapping[str, Any],
    atom_map: Mapping[str, str],
    group_map: Mapping[str, str],
) -> bool:
    nodes = _node_map(graph)
    expected_atom_by_node = {
        actual_id: expected_id for expected_id, actual_id in atom_map.items()
    }
    expected_group_by_node = {
        actual_id: expected_id
        for expected_id, actual_id in group_map.items()
        if not actual_id.startswith("scope:")
    }
    expected_nodes = set(expected_group_by_node)
    for node_id, node in nodes.items():
        if (
            node_id in expected_nodes
            or str(node.get("op", "")).upper() not in {"AND", "OR"}
            or _status(node.get("status")) != "confirmed"
        ):
            continue
        direct_members = {
            expected_member
            for child in _children(node)
            if (
                expected_member := expected_group_by_node.get(child)
                or expected_atom_by_node.get(child)
            )
        }
        if members <= direct_members:
            return True
    return False


def _forbidden_violation(
    item: Mapping[str, Any],
    case: Mapping[str, Any],
    graph: Mapping[str, Any],
    atom_map: Mapping[str, str],
    group_members: Mapping[str, set[str]],
    group_map: Mapping[str, str],
) -> tuple[bool, str]:
    kind = str(item.get("type") or "")
    members = {
        str(member)
        for member in (
            item.get("members")
            if isinstance(item.get("members"), list)
            else [item.get("members")]
        )
        if member is not None
    }
    actual_groups = _actual_confirmed_group_members(graph, atom_map)
    if kind == "operator":
        operator = str(item.get("operator") or "").upper()
        violated = any(
            actual_operator == operator and members <= actual_members
            for _, actual_operator, actual_members in actual_groups
        )
        return violated, "forbidden operator was confirmed" if violated else ""
    if kind == "scope":
        direction = _classify_forbidden_scope(str(item.get("claim") or ""))
        if direction == "require_members":
            eligible = [
                group_id
                for group_id, group in (
                    (str(group.get("id")), group)
                    for group in case.get("groups", [])
                    if isinstance(group, Mapping) and group.get("id") is not None
                )
                if members
                <= _expected_group_members(
                    [
                        entry
                        for entry in case.get("groups", [])
                        if isinstance(entry, Mapping)
                    ],
                    group_id,
                )
            ]
            satisfied = any(group_id in group_members for group_id in eligible)
            return not satisfied, (
                "explicitly required scope members were omitted"
                if not satisfied
                else ""
            )
        if direction == "prohibit_merge":
            violated = _forbidden_flattened_scope(members, graph, atom_map, group_map)
            return (
                violated,
                "forbidden scope members were flattened into direct children"
                if violated
                else "",
            )
        if direction == "prohibit_confirmation":
            violated = any(
                members <= actual_members for _, _, actual_members in actual_groups
            )
            return violated, "incomplete scope was confirmed" if violated else ""
        return True, "forbidden scope claim direction is not classified"
    if kind in {"reference", "reference_or_continuation"}:
        locations = _source_locations(item.get("source"))
        if kind == "reference_or_continuation":
            claim = str(item.get("claim") or "")
            mentioned = set(
                re.findall(r"(?<![A-Za-z0-9])[AS]\d+(?![A-Za-z0-9])", claim)
            )
            mentioned_atoms = {token for token in mentioned if token.startswith("A")}
            mentioned_groups = {token for token in mentioned if token.startswith("S")}
            scope_violation = any(
                bool(mentioned_atoms & actual_members)
                and (
                    any(
                        group_id in mentioned_groups
                        and mentioned_atoms & group_members.get(group_id, set())
                        for group_id in group_members
                    )
                    or any(
                        mentioned_groups
                        and target_group_id in mentioned_groups
                        and _expected_group_members(
                            [
                                group
                                for group in case.get("groups", [])
                                if isinstance(group, Mapping)
                            ],
                            target_group_id,
                        )
                        <= actual_members
                        for target_group_id in mentioned_groups
                    )
                )
                for _, _, actual_members in actual_groups
            )
        else:
            scope_violation = False
        relation_violation = False
        for record in _relation_records(graph, "reference"):
            if _status(record.get("status")) != "confirmed":
                continue
            actual_locations = {
                location
                for reference in _actual_references(record)
                if (location := _locator(reference)) is not None
            }
            if not locations or locations & actual_locations:
                relation_violation = True
                break
        violated = relation_violation or scope_violation
        return (
            violated,
            "forbidden reference/continuation was confirmed" if violated else "",
        )
    if kind == "condition":
        direction = _classify_forbidden_condition(str(item.get("claim") or ""))
        if direction != "prohibit_numeric_material_atom":
            return True, "forbidden condition claim direction is not classified"
        source_locations = _source_locations(item.get("source"))
        nodes = _node_map(graph)
        legal_alignment_ids = set(atom_map.values())
        for expected in case.get("conditions", []):
            if not isinstance(expected, Mapping):
                continue
            legal_alignment_ids.update(
                node_id
                for _, node_id in _atom_candidates(
                    expected,
                    [
                        node
                        for node in nodes.values()
                        if str(node.get("op", "")).upper() == "ATOM"
                    ],
                )
            )
        for node_id, node in nodes.items():
            if str(node.get("op", "")).upper() != "ATOM":
                continue
            node_locations = {
                location
                for reference in _node_refs(node)
                if (location := _locator(reference)) is not None
            }
            if (
                node_id not in legal_alignment_ids
                and source_locations & node_locations
                and _status(node.get("status")) == "confirmed"
                and _looks_like_numeric_material_atom(node)
            ):
                return True, "forbidden candidate condition was confirmed"
        return False, ""
    return True, "unsupported forbidden claim type"


def _expected_relation_group(
    relation: Mapping[str, Any], case: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    children = relation.get("children")
    if not isinstance(children, list):
        return None
    for group in case.get("groups", []):
        if isinstance(group, Mapping) and set(_group_members(group)) == {
            str(child) for child in children
        }:
            return group
    return None


def _target_locations(
    relation: Mapping[str, Any],
    nodes: Mapping[str, Mapping[str, Any]],
) -> set[tuple[int, int]]:
    targets: set[str] = set()
    for field in ("target_node_ids", "target_block_ids"):
        values = relation.get(field) or []
        if isinstance(values, str):
            values = [values]
        if isinstance(values, list):
            targets.update(str(value) for value in values)
    locations: set[tuple[int, int]] = set()
    for node_id, node in nodes.items():
        source_blocks = {str(value) for value in node.get("source_block_ids") or []}
        if node_id in targets or source_blocks & targets:
            for reference in _node_refs(node):
                location = _locator(reference)
                if location:
                    locations.add(location)
    for target in targets:
        for reference in nodes.get(target, {}).get("source_references", []) or []:
            if isinstance(reference, Mapping) and (location := _locator(reference)):
                locations.add(location)
    return locations


def _check_confirmed_reference(
    relation: Mapping[str, Any], graph: Mapping[str, Any]
) -> tuple[bool, list[str]]:
    from_location = _locator_mentions(relation.get("from"))
    to_location = _locator_mentions(relation.get("to"))
    expected_refs = _oracle_source(relation.get("source"))
    nodes = _node_map(graph)
    for record in _relation_records(graph, "reference"):
        if _status(record.get("status")) != "confirmed":
            continue
        actual_refs = _actual_references(record)
        covered, missing = _references_cover(actual_refs, expected_refs)
        if not covered:
            continue
        source_locations = {
            location
            for reference in actual_refs
            if (location := _locator(reference)) is not None
        }
        if from_location and from_location not in source_locations:
            continue
        target_locations = _target_locations(record, nodes)
        if to_location and to_location not in target_locations:
            continue
        if not record.get("target_block_ids") and not record.get("target_node_ids"):
            continue
        return True, []
    return False, ["confirmed reference status/source/target mismatch"]


def _score_case(
    case: Mapping[str, Any],
    graph: Mapping[str, Any],
    source_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    source_validation = (
        _validate_graph_source_references(graph, source_context)
        if source_context is not None
        else {
            "checked_references": 0,
            "unique_references": 0,
            "raw_offsets_checked": 0,
            "invalid_references": 0,
            "failures": [],
        }
    )
    graph = source_validation.get("normalized_graph", graph)
    for failure in source_validation["failures"]:
        errors.append(
            {
                "metric": "source_invalid",
                "reference_index": failure.get("reference_index"),
                "locator": failure.get("locator"),
                "reason": failure["reason"],
            }
        )
    expected_by_id, atom_map, candidate_edges = _match_atoms(case, graph)
    nodes = _node_map(graph)
    atom_nodes = {
        atom_id: nodes[node_id]
        for atom_id, node_id in atom_map.items()
        if node_id in nodes
    }
    confirmed_ids = {
        str(value) for value in case.get("expect_confirmed", {}).get("conditions", [])
    }
    all_expected_refs = 0
    missing_source_refs = 0
    for atom_id in confirmed_ids:
        expected = expected_by_id.get(atom_id)
        node = atom_nodes.get(atom_id)
        if expected is None:
            errors.append(
                {
                    "metric": "condition_omission",
                    "expected_id": atom_id,
                    "reason": "oracle atom missing",
                }
            )
            continue
        expected_refs = _oracle_source(expected.get("source"))
        all_expected_refs += len(expected_refs)
        if node is None:
            errors.append(
                {
                    "metric": "condition_omission",
                    "expected_id": atom_id,
                    "reason": "no unique source-anchored ATOM matched",
                }
            )
            missing_source_refs += len(expected_refs)
            continue
        if _status(node.get("status")) != "confirmed":
            errors.append(
                {
                    "metric": "condition_status",
                    "expected_id": atom_id,
                    "actual_status": node.get("status"),
                    "reason": "explicitly confirmed atom was not confirmed",
                }
            )
        covered, missing = _references_cover(_node_refs(node), expected_refs)
        if not covered:
            missing_source_refs += len(missing)
            errors.append(
                {
                    "metric": "source_coverage",
                    "expected_id": atom_id,
                    "missing_locators": missing,
                }
            )

    edges_by_atom = {
        item["expected_id"]: set(item["candidate_node_ids"]) for item in candidate_edges
    }
    confirmed_pairs = [
        (left, right)
        for index, left in enumerate(sorted(confirmed_ids))
        for right in sorted(confirmed_ids)[index + 1 :]
    ]
    wrong_merge_pairs = 0
    for left, right in confirmed_pairs:
        shared = edges_by_atom.get(left, set()) & edges_by_atom.get(right, set())
        if any(
            node_id in nodes and _status(nodes[node_id].get("status")) == "confirmed"
            for node_id in shared
        ):
            wrong_merge_pairs += 1
            errors.append(
                {
                    "metric": "wrong_merge_pairs",
                    "expected_ids": [left, right],
                    "reason": "one confirmed ATOM aligns to multiple frozen atoms",
                }
            )
    wrong_split_atoms = 0
    for atom_id in confirmed_ids:
        split_nodes = {
            node_id
            for node_id in edges_by_atom.get(atom_id, set())
            if node_id in nodes and _status(nodes[node_id].get("status")) == "confirmed"
        }
        if len(split_nodes) > 1:
            wrong_split_atoms += 1
            errors.append(
                {
                    "metric": "wrong_split_atom_units",
                    "expected_id": atom_id,
                    "actual_node_ids": sorted(split_nodes),
                }
            )

    group_map, group_members, group_errors = _match_groups(case, graph, atom_map)
    errors.extend(group_errors)
    confirmed_groups = [
        group
        for group in case.get("groups", [])
        if isinstance(group, Mapping) and _status(group.get("status")) == "confirmed"
    ]
    expected_scope_atoms = set(confirmed_ids)
    scope_decisions = 0
    scope_mismatches = 0
    for group in confirmed_groups:
        group_id = str(group.get("id"))
        expected_members = _expected_group_members(
            [item for item in case.get("groups", []) if isinstance(item, Mapping)],
            group_id,
        )
        actual_members = group_members.get(group_id, set())
        for atom_id in expected_scope_atoms:
            scope_decisions += 1
            expected_member = atom_id in expected_members
            actual_member = atom_id in actual_members
            if expected_member != actual_member:
                scope_mismatches += 1
                errors.append(
                    {
                        "metric": "scope_membership_decisions",
                        "group_id": group_id,
                        "condition_id": atom_id,
                        "expected_member": expected_member,
                        "actual_member": actual_member,
                    }
                )

    parent_relations = [
        relation
        for relation in case.get("expect_confirmed", {}).get("relations", [])
        if isinstance(relation, Mapping) and relation.get("type") == "parent"
    ]
    parent_failures = 0
    for relation in parent_relations:
        matched, missing = _semantic_parent_match(
            relation, case, group_map, group_members, nodes, atom_map, graph
        )
        if not matched:
            parent_failures += 1
            errors.append(
                {
                    "metric": "parent_relations",
                    "expected_children": relation.get("children"),
                    "expected_parent_kind": _parent_relation_kind(relation),
                    "missing_locators": missing,
                    "reason": "confirmed semantic parent/scope relation missing",
                }
            )
    reference_relations = [
        relation
        for relation in case.get("expect_confirmed", {}).get("relations", [])
        if isinstance(relation, Mapping) and relation.get("type") == "reference"
    ]
    reference_failures = 0
    for relation in reference_relations:
        matched, missing = _check_confirmed_reference(relation, graph)
        if not matched:
            reference_failures += 1
            errors.append(
                {
                    "metric": "reference_relations",
                    "missing_locators": missing,
                }
            )
    for relation in case.get("expect_confirmed", {}).get("relations", []):
        if isinstance(relation, Mapping) and relation.get("type") == "operator":
            expected_operator = str(relation.get("operator") or "").upper()
            if not any(
                str(node.get("op", "")).upper() == expected_operator
                and _status(node.get("status")) == "confirmed"
                for node in nodes.values()
            ):
                errors.append(
                    {
                        "metric": "operator_relations",
                        "expected_operator": expected_operator,
                        "reason": "confirmed operator relation missing",
                    }
                )

    forbidden_failures = 0
    for item in case.get("forbidden", []):
        if not isinstance(item, Mapping):
            forbidden_failures += 1
            errors.append(
                {"metric": "forbidden_claims", "reason": "invalid oracle record"}
            )
            continue
        violation, reason = _forbidden_violation(
            item, case, graph, atom_map, group_members, group_map
        )
        if violation:
            forbidden_failures += 1
            errors.append(
                {
                    "metric": "forbidden_claims",
                    "claim_type": item.get("type"),
                    "direction": (
                        _classify_forbidden_scope(str(item.get("claim") or ""))
                        if item.get("type") == "scope"
                        else None
                    ),
                    "reason": reason,
                }
            )

    review_items = _review_groups(case)
    review_failures = 0
    for item in review_items:
        covered, reason = _review_item_covered(item, graph, atom_nodes)
        if not covered:
            review_failures += 1
            errors.append(
                {
                    "metric": "review_handling",
                    "claim_type": item["type"],
                    "condition_id": item.get("condition_id"),
                    "expected_statuses": item["allowed_statuses"],
                    "missing_locators": [
                        f"p{ref['page']}l{ref['line']}" for ref in item["sources"]
                    ],
                    "reason": reason,
                }
            )
    review_groups = [
        group
        for group in case.get("groups", [])
        if isinstance(group, Mapping) and _status(group.get("status")) != "confirmed"
    ]
    review_group_failures = 0
    for group in review_groups:
        target_atoms = _expected_group_members(
            [item for item in case.get("groups", []) if isinstance(item, Mapping)],
            str(group.get("id")),
        )
        confirmed_match = any(
            operator in {"AND", "OR"} and target_atoms <= actual_members
            for _, operator, actual_members in _actual_confirmed_group_members(
                graph, atom_map
            )
        )
        if confirmed_match:
            review_group_failures += 1
            errors.append(
                {
                    "metric": "review_handling",
                    "group_id": group.get("id"),
                    "reason": "group requiring review was asserted as confirmed",
                }
            )

    denominators = case.get("denominators", {})
    confirmed_atom_count = len(confirmed_ids)
    wrong_merge_denominator = confirmed_atom_count * (confirmed_atom_count - 1) // 2
    expected_scope_count = len(confirmed_groups)
    expected_scope_decisions = confirmed_atom_count * expected_scope_count
    explicit_operator_groups = {
        str(group.get("id"))
        for group in confirmed_groups
        if str(group.get("operator") or "").upper() in {"AND", "OR"}
    }
    scope_evidence_groups = {str(group.get("id")) for group in confirmed_groups}
    operator_structure_failures = _unique_group_failures(
        errors, "group_structure", explicit_operator_groups
    )
    operator_evidence_failures = _unique_group_failures(
        errors, "operator_evidence", explicit_operator_groups
    )
    scope_evidence_failures = _unique_group_failures(
        errors, "scope_evidence", scope_evidence_groups
    )
    boundary_evidence_failures = _unique_group_failures(
        errors, "boundary_evidence", scope_evidence_groups
    )
    denominator_checks = {
        "condition_omission": confirmed_atom_count,
        "wrong_merge_pairs": wrong_merge_denominator,
        "wrong_split_atom_units": confirmed_atom_count,
        "scope_membership_decisions": expected_scope_decisions,
    }
    for name, expected_value in denominator_checks.items():
        if denominators.get(name) != expected_value:
            errors.append(
                {
                    "metric": "oracle_denominator",
                    "name": name,
                    "expected": expected_value,
                    "frozen": denominators.get(name),
                    "reason": "frozen denominator formula mismatch",
                }
            )
    if denominators.get("scope_membership_decisions") != scope_decisions:
        errors.append(
            {
                "metric": "oracle_denominator",
                "name": "scope_membership_decisions",
                "expected": denominators.get("scope_membership_decisions"),
                "measured": scope_decisions,
                "reason": "scope decision count differs from frozen denominator",
            }
        )

    metrics = {
        "condition_omission": {
            "numerator": sum(
                error["metric"] == "condition_omission" for error in errors
            ),
            "denominator": confirmed_atom_count,
        },
        "wrong_merge_pairs": {
            "numerator": wrong_merge_pairs,
            "denominator": wrong_merge_denominator,
        },
        "wrong_split_atom_units": {
            "numerator": wrong_split_atoms,
            "denominator": confirmed_atom_count,
        },
        "scope_membership_decisions": {
            "numerator": scope_mismatches,
            "denominator": expected_scope_decisions,
        },
        "operator_group_structure": {
            "numerator": len(operator_structure_failures),
            "denominator": len(explicit_operator_groups),
        },
        "operator_evidence": {
            "numerator": len(operator_evidence_failures),
            "denominator": len(explicit_operator_groups),
        },
        "scope_evidence": {
            "numerator": len(scope_evidence_failures),
            "denominator": len(scope_evidence_groups),
        },
        "boundary_evidence": {
            "numerator": len(boundary_evidence_failures),
            "denominator": len(scope_evidence_groups),
        },
        "parent_relations": {
            "numerator": parent_failures,
            "denominator": len(parent_relations),
        },
        "reference_relations": {
            "numerator": reference_failures,
            "denominator": len(reference_relations),
        },
        "forbidden_claims": {
            "numerator": forbidden_failures,
            "denominator": len(case.get("forbidden", [])),
        },
        "review_handling": {
            "numerator": review_failures + review_group_failures,
            "denominator": len(review_items) + len(review_groups),
            "raw_needs_review_items": len(case.get("needs_review", [])),
        },
        "source_coverage": {
            "numerator": missing_source_refs,
            "denominator": all_expected_refs,
        },
        "source_invalid": {
            "numerator": source_validation["invalid_references"],
            "denominator": source_validation["checked_references"],
        },
    }
    _assert_ratio_metric_bounds(metrics)
    return {
        "case_id": case.get("case_id"),
        "status": "failed" if errors else "passed",
        "expected_confirmed_atom_ids": sorted(confirmed_ids),
        "matched_atom_ids": sorted(atom_map),
        "confirmed_group_ids": [str(group.get("id")) for group in confirmed_groups],
        "matched_group_ids": sorted(group_map),
        "group_status_review_count": len(review_groups),
        "actual_source_validation": {
            "checked_references": source_validation["checked_references"],
            "unique_references": source_validation["unique_references"],
            "raw_offsets_checked": source_validation["raw_offsets_checked"],
            "invalid_references": source_validation["invalid_references"],
            "line_numbers_derived": source_validation.get("line_numbers_derived", 0),
            "line_numbers_supplied": source_validation.get("line_numbers_supplied", 0),
        },
        "event_counts": {
            "error_events": len(errors),
            "group_structure_error_events": sum(
                error.get("metric") == "group_structure" for error in errors
            ),
        },
        "metrics": metrics,
        "errors": errors,
    }


def _not_run_case(
    case_id: str, reason: str, runtime: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "status": "not_run",
        "execution_state": "not_run",
        "reason": reason,
        "runtime": dict(runtime),
        "metrics": {},
        "errors": [],
    }


def _runtime_replay_material(runtime: Mapping[str, Any]) -> dict[str, Any]:
    graph = runtime.get("graph")
    source_context = runtime.get("source_context")
    if not isinstance(graph, Mapping) or not isinstance(source_context, Mapping):
        return {}
    saved_context = deepcopy(dict(source_context))
    saved_context["registered_input_sha256"] = runtime.get("registered_input_sha256")
    saved_context["page_separator"] = BOUNDARY
    return {
        "actual_graph": deepcopy(dict(graph)),
        "source_context": saved_context,
    }


async def run_evaluation(
    bundle_path: Path, *, main_reviewer_authorized: bool = False
) -> dict[str, Any]:
    if not main_reviewer_authorized:
        raise PermissionError(
            "first product scoring requires explicit main-reviewer authorization"
        )
    freeze = verify_bundle(bundle_path)
    oracle_cases = freeze["oracle"]["cases"]
    case_results: list[dict[str, Any]] = []
    for case in oracle_cases:
        case_id = str(case["case_id"])
        input_path = _safe_bundle_path(freeze["bundle"], str(case["input"]))
        try:
            runtime = await _run_input(input_path, case_id)
        except Exception as exc:  # runtime failures are measured failures, not not_run
            case_results.append(
                {
                    "case_id": case_id,
                    "status": "failed",
                    "execution_state": "failed",
                    "reason": f"runtime exception: {type(exc).__name__}",
                    "runtime": {"exception_message": str(exc)},
                    "metrics": {},
                    "errors": [
                        {
                            "metric": "runtime_execution",
                            "reason": f"{type(exc).__name__}: {exc}",
                        }
                    ],
                }
            )
            continue
        if runtime["execution_state"] == "not_run":
            case_results.append(_not_run_case(case_id, str(runtime["reason"]), runtime))
            continue
        if runtime["execution_state"] == "failed":
            case_results.append(
                {
                    "case_id": case_id,
                    "status": "failed",
                    "execution_state": "failed",
                    "reason": runtime["reason"],
                    "runtime": {
                        key: value for key, value in runtime.items() if key != "graph"
                    },
                    "metrics": {},
                    "errors": [
                        {
                            "metric": "runtime_execution",
                            "reason": runtime["reason"],
                        }
                    ],
                }
            )
            continue
        scored = _score_case(case, runtime["graph"], runtime.get("source_context"))
        scored["execution_state"] = "executed"
        scored["runtime"] = {
            "registered_input_sha256": runtime["registered_input_sha256"],
            "intake_status": runtime["intake_status"],
            "decomposition_status": runtime["decomposition_status"],
        }
        scored.update(_runtime_replay_material(runtime))
        case_results.append(scored)

    aggregate: dict[str, dict[str, Any]] = {}
    metric_names = {
        name
        for case in case_results
        for name in case.get("metrics", {})
        if isinstance(case.get("metrics", {}).get(name), Mapping)
    }
    for name in sorted(metric_names):
        numerator = sum(
            int(case["metrics"][name].get("numerator", 0))
            for case in case_results
            if case.get("execution_state") == "executed"
            and isinstance(case.get("metrics", {}).get(name), Mapping)
        )
        denominator = sum(
            int(case["metrics"][name].get("denominator", 0))
            for case in case_results
            if case.get("execution_state") == "executed"
            and isinstance(case.get("metrics", {}).get(name), Mapping)
        )
        aggregate[name] = {
            "numerator": numerator,
            "denominator": denominator,
            "status": "measured" if denominator else "not_applicable",
        }
    _assert_ratio_metric_bounds(aggregate)
    failed = sum(case["status"] == "failed" for case in case_results)
    not_run = sum(case["status"] == "not_run" for case in case_results)
    passed = sum(case["status"] == "passed" for case in case_results)
    event_counts = {
        "error_events": sum(len(case.get("errors", [])) for case in case_results),
        "group_structure_error_events": sum(
            int(case.get("event_counts", {}).get("group_structure_error_events", 0))
            for case in case_results
        ),
    }
    manifest = freeze["manifest"]
    v1_bundle = _published_bundle("v1")
    v2_bundle = _published_bundle("v2")
    initial_invalid_report = _published_report("initial-invalid-evaluator-score")
    initial_invalid_proof = _published_report(
        "initial-invalid-evaluator-source-proof"
    )
    first_valid_report = _published_report("first-valid-score")
    first_valid_proof = _published_report("first-valid-source-proof")
    publication = _load_json(PUBLICATION_RECORD)
    input_history = [
        {
            "version": "v1",
            "classification": "rejected-annotated-container",
            "origin_directory": v1_bundle["source_directory"],
            "directory": v1_bundle["published_directory"],
            "bundle_fingerprint": manifest["lineage"]["v1_fingerprint"],
            "freeze_json_sha256": manifest["lineage"]["v1_freeze_json_sha256"],
            "scoring_status": "rejected_before_scoring",
            "reason": "annotation/container lines made source coordinates non-physical",
        },
        {
            "version": "v2",
            "classification": "normative-clean-input",
            "origin_directory": v2_bundle["source_directory"],
            "directory": v2_bundle["published_directory"],
            "bundle_fingerprint": freeze["bundle_fingerprint"],
            "freeze_json_sha256": freeze["manifest_sha256"],
            "scoring_status": ("scored" if passed + failed > 0 else "not_run"),
            "source_semantics_changed": False,
        },
    ]
    evaluator_path = Path(__file__).resolve()
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now().astimezone().isoformat(),
        "classification": "shared-filesystem synthetic evaluation; not certified blind",
        "base_commit": EXPECTED_BASE_COMMIT,
        **_git_metadata(ROOT),
        "source_tree_sha256": _source_tree_sha256(ROOT),
        "source_tree_sha256_algorithm": (
            "SHA-256 over sorted src/**/*.py POSIX relative paths, TAB, raw file "
            "SHA-256 bytes, and LF; binarydigest-compatible"
        ),
        "evaluator": {
            "version": EVALUATOR_VERSION,
            "path": evaluator_path.relative_to(ROOT).as_posix(),
            "sha256": _sha256(evaluator_path.read_bytes()),
        },
        "freeze": {
            "v2_manifest_sha256": freeze["manifest_sha256"],
            "v2_bundle_fingerprint": freeze["bundle_fingerprint"],
            "payload_files": len(freeze["checked_files"]),
            "source_coordinates": freeze["source_coordinates"],
        },
        "input_history": {
            "source_semantics_unchanged": True,
            "versions": input_history,
            "metadata_erratum": (
                "freeze.json developer_status_at_freeze says A/B remained paused per "
                "user. Correction: A/B had not been created or started at freeze; "
                "the user had not explicitly paused them. A/B fork_context=false "
                "agents started at approximately 2026-10-09 14:44 Asia/Shanghai, "
                "after the 14:42:19.892 freeze, without permission to read the "
                "private corpus. The frozen manifest bytes are unchanged."
            ),
            "public_release": {
                "published_at": publication.get("published_at"),
                "classification": publication.get("classification"),
                "policy_boundary": publication.get("policy_boundary"),
                "developer_access": publication.get("developer_access"),
            },
        },
        "evaluator_contract_erratum": {
            "prior_report": initial_invalid_report["published_path"],
            "prior_report_sha256": initial_invalid_report["sha256"],
            "prior_report_classification": (
                "invalid_evaluator_output_not_product_result"
            ),
            "prior_source_proof": initial_invalid_proof["published_path"],
            "prior_source_proof_sha256": initial_invalid_proof["sha256"],
            "first_valid_report": first_valid_report["published_path"],
            "first_valid_report_sha256": first_valid_report["sha256"],
            "first_valid_report_classification": first_valid_report[
                "classification"
            ],
            "first_valid_source_proof": first_valid_proof["published_path"],
            "first_valid_source_proof_sha256": first_valid_proof["sha256"],
            "first_valid_interpretation": (
                "preserved initial product score; source validation remains strict"
            ),
            "same_source_rerun": {
                "archive_base_staged_tree": (
                    "803ccb0ef95d343bd9eba7a7cf866e99a2e95357"
                ),
                "source_tree_sha256": (
                    "93ad62e4729baedb9f149a781afa8b712987e9424818a4a5c82052af25d2b417"
                ),
                "interpretation": (
                    "grader correction and rescore, not a development regression"
                ),
            },
            "issues_corrected": [
                "derive physical line from validated raw page character offsets "
                "when product references omit line fields",
                "count operator group structure failures by unique expected "
                "AND/OR group unit",
                "check forbidden flattened scope claims against direct children, "
                "not ancestor leaf closures",
                "preserve raw actual graph and registered source context for replay",
                "distinguish confirmed structural-list membership from semantic "
                "scope/parent, requiring explicit relation layer, basis, existing "
                "target, and target-owned list-cue evidence",
                "require typed directed semantic-parent evidence and matching "
                "source references; a promoted physical parent is insufficient",
                "map candidate atoms through exact source literals only when "
                "their raw source references passed coordinate validation",
            ],
        },
        "typed_parent_adapter_erratum": {
            "classification": "grader_contract_compatibility_only",
            "frozen_oracle_changed": False,
            "first_valid_report_changed": False,
            "first_valid_product_graph_replayed_here": False,
            "case_04_05": (
                "confirmed visible-list membership is a structural relation; it "
                "does not require or imply a confirmed logical scope or AND group"
            ),
            "case_09_13": (
                "attribute and contextual scopes are represented as non-operator "
                "scope relations; no synthetic AND is required"
            ),
            "public_regression": True,
        },
        "candidate_source_literal_adapter_erratum": {
            "classification": "grader_contract_compatibility_only",
            "frozen_oracle_changed": False,
            "historical_reports_changed": False,
            "first_valid_report_changed": False,
            "applies_only_when_expected_certainty_is": "candidate",
            "required_evidence": (
                "actual text contains the exact frozen source quote and an actual "
                "reference at the same page/line contains that quote and passed "
                "raw-coordinate validation"
            ),
            "actual_status_checked_separately": True,
            "one_to_one_atom_mapping_preserved": True,
            "public_regression": True,
        },
        "summary": {
            "case_count": len(case_results),
            "passed": passed,
            "failed": failed,
            "not_run": not_run,
            "metrics": aggregate,
            "event_counts": event_counts,
        },
        "business_materials": {
            "status": "not_run",
            "denominator": 14,
            "business_pass_rate": "not_calculated",
            "registered": False,
        },
        "claims": {
            "blind_holdout": False,
            "certified_blind": False,
            "synthetic_txt_only": True,
            "real_business_pdf": False,
            "first_score_requires_main_reviewer_authorization": True,
            "main_reviewer_authorized": main_reviewer_authorized,
            "report_write_policy": "create_only",
            "acceptance_only_score_is_developer_exposure": False,
            "developer_exposure_requires_release_or_access": True,
            "exposure_time_recorded_on_release_or_access": True,
            "public_regression_after_developer_exposure": True,
            "cases_are_public_regression": True,
            "source_line_resolution": (
                "validated raw page character offsets; missing line is added only "
                "to an independent scoring shadow graph"
            ),
            "actual_graph_preserves_product_reference_shape": True,
        },
        "historical_acceptance_boundary": {
            "existing_public_original_file_integrity_evaluation": "0/8",
            "enterprise_materials": "not_run/8",
            "generic_and_production_acceptance": "not_passed",
        },
        "cases": case_results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle",
        type=Path,
        required=True,
        help="path to the externally frozen v2 bundle",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="new report path; existing files are never overwritten",
    )
    parser.add_argument(
        "--main-reviewer-authorized",
        action="store_true",
        help="attest explicit main-reviewer authorization for first scoring",
    )
    args = parser.parse_args(argv)
    if not args.main_reviewer_authorized:
        parser.error(
            "first product scoring requires explicit main-reviewer authorization"
        )
    output = args.output.resolve()
    if output.exists():
        parser.error(f"refusing to overwrite existing report: {output}")
    report = asyncio.run(
        run_evaluation(
            args.bundle,
            main_reviewer_authorized=args.main_reviewer_authorized,
        )
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(rendered)
    if report["summary"]["failed"]:
        return 1
    if report["summary"]["not_run"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
