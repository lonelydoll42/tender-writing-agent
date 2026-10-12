"""Offline-rescore preserved document-relations product graphs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
LEGACY_EVALUATOR_PATH = ROOT / "scripts" / "run_document_relations_eval.py"
LEGACY_EVALUATOR_SHA256 = (
    "26330942263746e6794deb7def70e17f4848bb64f2fe7ebb4011f5784ca57483"
)
LEGACY_SOURCE_TREE_ALGORITHM = (
    "SHA-256 over sorted src/**/*.py POSIX relative paths, TAB, raw file "
    "SHA-256 bytes, and LF; binarydigest-compatible"
)
EVALUATOR_VERSION = "1.0.4"
OFFLINE_REPORT_SCHEMA = "document-relations-offline-rescore-v1"
SUPPORTED_VERSIONS = ("1.0.3", "1.0.4")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_sha256(value: Any) -> str:
    try:
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("report graph/context is not canonical JSON data") from exc
    return _sha256(canonical)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _load_json_bytes(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _isolated_legacy_module() -> ModuleType:
    try:
        legacy_bytes = LEGACY_EVALUATOR_PATH.read_bytes()
    except OSError as exc:
        raise ValueError("the frozen 1.0.3 evaluator is unavailable") from exc
    if _sha256(legacy_bytes) != LEGACY_EVALUATOR_SHA256:
        raise ValueError("the frozen 1.0.3 evaluator SHA-256 does not match")

    name = f"_document_relations_eval_103_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, LEGACY_EVALUATOR_PATH)
    if spec is None or spec.loader is None:
        raise ValueError("unable to load an isolated 1.0.3 evaluator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    if module.EVALUATOR_VERSION != "1.0.3":
        sys.modules.pop(name, None)
        raise ValueError("the loaded legacy evaluator does not identify as 1.0.3")
    return module


def load_evaluator(version: str) -> ModuleType:
    """Load a private evaluator instance without mutating the legacy module."""
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(f"unsupported evaluator version: {version!r}")
    module = _isolated_legacy_module()
    if version == "1.0.3":
        return module

    original_atom_candidates = module._atom_candidates
    module._rescore_literal_mapping_enabled = True

    def atom_candidates(
        expected: Mapping[str, Any], actual_nodes: list[Mapping[str, Any]]
    ) -> list[tuple[int, str]]:
        candidates = original_atom_candidates(expected, actual_nodes)
        if (
            not module._rescore_literal_mapping_enabled
            or module._status(expected.get("certainty")) != "confirmed"
        ):
            return candidates

        candidate_ids = {node_id for _, node_id in candidates}
        expected_refs = module._oracle_source(expected.get("source"))
        expected_text = str(expected.get("text") or "")
        added: list[tuple[int, str]] = []
        for node in actual_nodes:
            node_id = node.get("node_id")
            if not isinstance(node_id, str) or not node_id or node_id in candidate_ids:
                continue
            actual_text = str(node.get("text") or "").strip()
            matched_locations = 0
            for expected_ref in expected_refs:
                expected_location = module._locator(expected_ref)
                expected_quote = expected_ref.get("quote")
                if (
                    expected_location is None
                    or not isinstance(expected_quote, str)
                    or not expected_quote
                    or actual_text != expected_quote.strip()
                ):
                    continue
                if any(
                    actual_ref.get("_raw_coordinate_valid") is True
                    and module._locator(actual_ref) == expected_location
                    and actual_ref.get("quote") == expected_quote
                    for actual_ref in module._node_refs(node)
                ):
                    matched_locations += 1
            if matched_locations:
                similarity = module._text_similarity(expected_text, node.get("text"))
                added.append(
                    (
                        matched_locations * 1100 + int(similarity * 100),
                        node_id,
                    )
                )
        return sorted([*candidates, *added], reverse=True)

    module._atom_candidates = atom_candidates
    module.EVALUATOR_VERSION = EVALUATOR_VERSION
    return module


def _fallback_context_matches(
    graph: Mapping[str, Any], source_context: Mapping[str, Any] | None
) -> bool:
    if source_context is None or not isinstance(source_context.get("pages"), list):
        return False
    document_id = source_context.get("document_id")
    source_version = source_context.get("source_version")
    return bool(
        isinstance(document_id, str)
        and document_id
        and isinstance(source_version, str)
        and source_version
        and graph.get("document_id", document_id) == document_id
        and graph.get("source_version", source_version) == source_version
    )


def score_case(
    case: Mapping[str, Any],
    graph: Mapping[str, Any],
    source_context: Mapping[str, Any] | None,
    *,
    version: str = EVALUATOR_VERSION,
) -> dict[str, Any]:
    """Score one preserved graph using a fresh legacy source-validation shadow."""
    if not isinstance(case, Mapping) or not isinstance(graph, Mapping):
        raise ValueError("case and graph must be objects")
    if source_context is not None and not isinstance(source_context, Mapping):
        raise ValueError("source_context must be an object or None")

    evaluator = load_evaluator(version)
    if version == EVALUATOR_VERSION:
        evaluator._rescore_literal_mapping_enabled = _fallback_context_matches(
            graph, source_context
        )
    result = evaluator._score_case(
        deepcopy(case),
        deepcopy(graph),
        deepcopy(source_context) if source_context is not None else None,
    )
    result["evaluator_version"] = version
    return result


def _validate_product_report(
    report_path: Path,
    expected_report_sha256: str,
    legacy: ModuleType,
) -> tuple[dict[str, Any], bytes, str]:
    if not _is_sha256(expected_report_sha256.lower()):
        raise ValueError("expected_report_sha256 must be a 64-character SHA-256")
    try:
        raw = report_path.read_bytes()
    except OSError as exc:
        raise ValueError("unable to read the product report") from exc
    report_sha256 = _sha256(raw)
    if report_sha256 != expected_report_sha256.lower():
        raise ValueError("product report SHA-256 does not match the expected value")
    report = _load_json_bytes(raw, label="product report")
    if report.get("schema") != legacy.REPORT_SCHEMA:
        raise ValueError("unsupported product report schema")
    if report.get("base_commit") != legacy.EXPECTED_BASE_COMMIT:
        raise ValueError("product report base commit does not match the frozen bundle")

    source_tree_sha256 = report.get("source_tree_sha256")
    if not _is_sha256(source_tree_sha256):
        raise ValueError("product report source_tree_sha256 is missing or invalid")
    if report.get("source_tree_sha256_algorithm") != LEGACY_SOURCE_TREE_ALGORITHM:
        raise ValueError("product report source-tree hash algorithm is unsupported")

    evaluator = _require_mapping(report.get("evaluator"), "product report evaluator")
    if (
        evaluator.get("version") != "1.0.3"
        or evaluator.get("path") != "scripts/run_document_relations_eval.py"
        or evaluator.get("sha256") != LEGACY_EVALUATOR_SHA256
    ):
        raise ValueError("product report does not identify the frozen 1.0.3 evaluator")

    freeze = _require_mapping(report.get("freeze"), "product report freeze")
    if (
        freeze.get("v2_manifest_sha256") != legacy.EXPECTED_V2_MANIFEST_SHA256
        or freeze.get("v2_bundle_fingerprint") != legacy.EXPECTED_V2_FINGERPRINT
        or freeze.get("payload_files") != legacy.EXPECTED_PAYLOAD_COUNT
    ):
        raise ValueError("product report frozen manifest/fingerprint does not match")

    cases = report.get("cases")
    if not isinstance(cases, list) or len(cases) != len(legacy.EXPECTED_CASE_IDS):
        raise ValueError("product report must contain exactly 14 cases")
    by_id: dict[str, Mapping[str, Any]] = {}
    for case in cases:
        if not isinstance(case, Mapping):
            raise ValueError("product report case rows must be objects")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or case_id in by_id:
            raise ValueError("product report case IDs must be unique strings")
        by_id[case_id] = case
    if set(by_id) != set(legacy.EXPECTED_CASE_IDS):
        raise ValueError("product report case IDs do not match the frozen 14 cases")
    return report, raw, report_sha256


def _bundle_case_inputs(
    freeze: Mapping[str, Any],
) -> dict[str, tuple[dict[str, Any], str, list[str]]]:
    result: dict[str, tuple[dict[str, Any], str, list[str]]] = {}
    for oracle_case in freeze["oracle"]["cases"]:
        case_id = str(oracle_case["case_id"])
        input_path = freeze["bundle"] / str(oracle_case["input"])
        try:
            raw = input_path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"unable to read frozen input for {case_id}") from exc
        if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw:
            raise ValueError(f"frozen input is not clean UTF-8/LF for {case_id}")
        result[case_id] = (oracle_case, _sha256(raw), text.split("\f"))
    return result


def _validate_case_replay_material(
    case_id: str,
    case: Mapping[str, Any],
    expected_input_sha256: str,
    expected_pages: list[str],
) -> tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None, Mapping[str, Any]]:
    execution_state = case.get("execution_state")
    status = case.get("status")
    if execution_state not in {"executed", "failed", "not_run"}:
        raise ValueError(f"unsupported execution_state for {case_id}")
    expected_statuses = {
        "executed": {"passed", "failed"},
        "failed": {"failed"},
        "not_run": {"not_run"},
    }
    if status not in expected_statuses[execution_state]:
        raise ValueError(f"status/execution_state mismatch for {case_id}")

    runtime = _require_mapping(case.get("runtime"), f"{case_id} runtime")
    runtime_input_sha256 = runtime.get("registered_input_sha256")
    if (
        runtime_input_sha256 is not None
        and runtime_input_sha256 != expected_input_sha256
    ):
        raise ValueError(f"runtime input checksum mismatch for {case_id}")
    if execution_state == "executed" and runtime_input_sha256 != expected_input_sha256:
        raise ValueError(f"executed runtime input checksum is missing for {case_id}")

    graph_value = case.get("actual_graph")
    context_value = case.get("source_context")
    graph = (
        _require_mapping(graph_value, f"{case_id} actual_graph")
        if graph_value is not None
        else None
    )
    source_context = (
        _require_mapping(context_value, f"{case_id} source_context")
        if context_value is not None
        else None
    )
    if execution_state == "executed" and (graph is None or source_context is None):
        raise ValueError(f"executed case is missing graph or source_context: {case_id}")

    if source_context is not None:
        if source_context.get("pages") != expected_pages:
            raise ValueError(
                f"source_context pages do not match frozen input: {case_id}"
            )
        if source_context.get("page_separator") != "\f":
            raise ValueError(f"source_context page separator mismatch for {case_id}")
        if (
            source_context.get("raw_input_sha256") != expected_input_sha256
            or source_context.get("registered_input_sha256") != expected_input_sha256
        ):
            raise ValueError(f"source_context input checksum mismatch for {case_id}")
    if graph is not None and source_context is not None:
        if (
            not isinstance(graph.get("document_id"), str)
            or not graph.get("document_id")
            or graph.get("document_id") != source_context.get("document_id")
            or not isinstance(graph.get("source_version"), str)
            or not graph.get("source_version")
            or graph.get("source_version") != source_context.get("source_version")
        ):
            raise ValueError(f"graph/source_context identity mismatch for {case_id}")
    if execution_state == "executed":
        schema = graph.get("schema", graph.get("schema_version")) if graph else None
        if schema != "document-relations-v1":
            raise ValueError(f"unsupported actual graph schema for {case_id}")
        nodes = graph.get("condition_nodes")
        if not isinstance(nodes, list):
            raise ValueError(
                f"actual graph condition_nodes must be a list for {case_id}"
            )
        node_ids: set[str] = set()
        for node in nodes:
            if not isinstance(node, Mapping):
                raise ValueError(f"actual graph node must be an object for {case_id}")
            node_id = node.get("node_id")
            if not isinstance(node_id, str) or not node_id.strip():
                raise ValueError(
                    f"actual graph node_id must be non-empty for {case_id}"
                )
            if node_id in node_ids:
                raise ValueError(f"duplicate actual graph node_id for {case_id}")
            node_ids.add(node_id)

    if execution_state != "executed" and not isinstance(case.get("reason"), str):
        raise ValueError(f"non-executed case reason is missing for {case_id}")
    return execution_state, graph, source_context, runtime


def _aggregate_results(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    metric_names = {
        name
        for case in case_results
        for name, metric in case.get("metrics", {}).items()
        if isinstance(metric, Mapping)
    }
    aggregate: dict[str, dict[str, Any]] = {}
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

    legacy = load_evaluator("1.0.3")
    legacy._assert_ratio_metric_bounds(aggregate)
    passed = sum(case["status"] == "passed" for case in case_results)
    failed = sum(case["status"] == "failed" for case in case_results)
    not_run = sum(case["status"] == "not_run" for case in case_results)
    event_counts = {
        "error_events": sum(len(case.get("errors", [])) for case in case_results),
        "group_structure_error_events": sum(
            int(case.get("event_counts", {}).get("group_structure_error_events", 0))
            for case in case_results
        ),
    }
    return {
        "case_count": len(case_results),
        "passed": passed,
        "failed": failed,
        "not_run": not_run,
        "metrics": aggregate,
        "event_counts": event_counts,
    }


def rescore_report(
    bundle: Path,
    product_report: Path,
    *,
    version: str,
    expected_report_sha256: str,
    main_reviewer_authorized: bool,
) -> dict[str, Any]:
    if not main_reviewer_authorized:
        raise PermissionError("offline product-report rescore requires authorization")
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(f"unsupported evaluator version: {version!r}")

    legacy = load_evaluator("1.0.3")
    report, _, report_sha256 = _validate_product_report(
        Path(product_report), expected_report_sha256, legacy
    )
    try:
        freeze = legacy.verify_bundle(Path(bundle))
    except OSError as exc:
        raise ValueError("the frozen document-relations bundle is unavailable") from exc
    original_freeze = report["freeze"]
    if (
        original_freeze["v2_manifest_sha256"] != freeze["manifest_sha256"]
        or original_freeze["v2_bundle_fingerprint"] != freeze["bundle_fingerprint"]
    ):
        raise ValueError("product report freeze does not match the verified bundle")

    product_cases = {
        str(case["case_id"]): case for case in report["cases"]
    }
    bundle_inputs = _bundle_case_inputs(freeze)
    evaluator = load_evaluator(version)
    current_evaluator_sha256 = _sha256(Path(__file__).read_bytes())
    old_source_tree_sha256 = report["source_tree_sha256"]
    case_results: list[dict[str, Any]] = []

    for case_id in legacy.EXPECTED_CASE_IDS:
        oracle_case, input_sha256, pages = bundle_inputs[case_id]
        product_case = product_cases[case_id]
        execution_state, graph, source_context, runtime = (
            _validate_case_replay_material(
                case_id, product_case, input_sha256, pages
            )
        )
        graph_sha256 = _canonical_sha256(graph) if graph is not None else None
        context_sha256 = (
            _canonical_sha256(source_context) if source_context is not None else None
        )

        if execution_state == "executed":
            assert graph is not None and source_context is not None
            scored = evaluator._score_case(
                deepcopy(oracle_case),
                deepcopy(dict(graph)),
                deepcopy(dict(source_context)),
            )
            scored["execution_state"] = "executed"
            scored["runtime"] = deepcopy(dict(runtime))
            scored["actual_graph"] = deepcopy(dict(graph))
            scored["source_context"] = deepcopy(dict(source_context))
            scored["bundle_input_sha256"] = input_sha256
            scored["actual_graph_canonical_json_sha256"] = graph_sha256
            scored["source_context_canonical_json_sha256"] = context_sha256
            scored["product_report_status"] = product_case["status"]
            if "reason" in product_case:
                scored["reason"] = deepcopy(product_case["reason"])
            scored["evaluator_version"] = version
            case_results.append(scored)
            continue

        preserved: dict[str, Any] = {
            "case_id": case_id,
            "status": product_case["status"],
            "execution_state": execution_state,
            "runtime": deepcopy(dict(runtime)),
            "metrics": {},
            "errors": deepcopy(product_case.get("errors", [])),
            "product_report_status": product_case["status"],
            "bundle_input_sha256": input_sha256,
            "actual_graph_canonical_json_sha256": graph_sha256,
            "source_context_canonical_json_sha256": context_sha256,
        }
        if "reason" in product_case:
            preserved["reason"] = deepcopy(product_case["reason"])
        if "event_counts" in product_case:
            preserved["event_counts"] = deepcopy(product_case["event_counts"])
        if graph is not None:
            preserved["actual_graph"] = deepcopy(dict(graph))
        if source_context is not None:
            preserved["source_context"] = deepcopy(dict(source_context))
        case_results.append(preserved)

    legacy._assert_ratio_metric_bounds(
        {
            name: metric
            for case in case_results
            for name, metric in case.get("metrics", {}).items()
            if isinstance(metric, Mapping)
        }
    )
    return {
        "schema": OFFLINE_REPORT_SCHEMA,
        "generated_at": datetime.now().astimezone().isoformat(),
        "classification": "offline grader rescore of preserved product output",
        "interpretation": (
            "This is a grader-only offline rescore, not a product or source "
            "improvement. Original graph, source context, execution state, and "
            "runtime are preserved."
        ),
        "base_commit": legacy.EXPECTED_BASE_COMMIT,
        "source_tree_sha256": old_source_tree_sha256,
        "source_tree_sha256_algorithm": LEGACY_SOURCE_TREE_ALGORITHM,
        "evaluator": {
            "version": version,
            "path": Path(__file__).resolve().relative_to(ROOT).as_posix(),
            "sha256": current_evaluator_sha256,
            "legacy_evaluator_sha256": LEGACY_EVALUATOR_SHA256,
        },
        "product_report": {
            "sha256": report_sha256,
            "schema": report["schema"],
            "evaluator_sha256": LEGACY_EVALUATOR_SHA256,
            "source_tree_sha256": old_source_tree_sha256,
        },
        "freeze": {
            "v2_manifest_sha256": freeze["manifest_sha256"],
            "v2_bundle_fingerprint": freeze["bundle_fingerprint"],
            "payload_files": len(freeze["checked_files"]),
        },
        "claims": {
            "offline_rescore": True,
            "product_runtime_invoked": False,
            "product_source_changed": False,
            "main_reviewer_authorized": main_reviewer_authorized,
            "create_only_report": True,
        },
        "summary": _aggregate_results(case_results),
        "cases": case_results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--product-report", type=Path, required=True)
    parser.add_argument("--expected-report-sha256", required=True)
    parser.add_argument(
        "--version", choices=SUPPORTED_VERSIONS, default=EVALUATOR_VERSION
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--main-reviewer-authorized",
        action="store_true",
        help="attest explicit authorization for this offline rescore",
    )
    args = parser.parse_args(argv)
    if not args.main_reviewer_authorized:
        parser.error("offline product-report rescore requires authorization")
    output = args.output.resolve()
    if output.exists():
        parser.error(f"refusing to overwrite existing report: {output}")

    report = rescore_report(
        args.bundle,
        args.product_report,
        version=args.version,
        expected_report_sha256=args.expected_report_sha256,
        main_reviewer_authorized=args.main_reviewer_authorized,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
    except FileExistsError:
        parser.error(f"refusing to overwrite existing report: {output}")
    if report["summary"]["failed"]:
        return 1
    if report["summary"]["not_run"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
