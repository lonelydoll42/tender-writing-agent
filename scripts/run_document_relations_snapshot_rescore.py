"""Offline three-view scoring for a preserved document-relations capture.

The expected source hash is compared with capture metadata only. Git provenance
must be proved separately; this adapter never invokes product Runtime/model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_document_relations_boundary_rescore as boundary  # noqa: E402
from scripts import run_document_relations_current_rescore as current  # noqa: E402
from scripts import run_document_relations_rescore as rescorer  # noqa: E402


FREEZE_DIR = ROOT / "benchmarks/document_relations/attribute-regression/20261014"
CONTRACT_PATH = FREEZE_DIR / "contract.md"
CASES_PATH = FREEZE_DIR / "cases.json"
SCOPE_PATH = FREEZE_DIR / "scope-freeze.json"
ATTRIBUTE_BASE_COMMIT = "91fb1b9751d010af9c0f804dc6afbfee1de36dd2"
ATTRIBUTE_BASELINE_SOURCE_SHA256 = (
    "51b1b18212c84ce50e8606106b96e4b5d5b548fb68bab491669cf08cf4e1ea34"
)
ATTRIBUTE_HASHES = {
    "contract": "8204635e3ece53755fe488c05900c161d92c9dd6d0d1c3d53fff2d80612ac2f1",
    "cases": "64c876600b0c7ba0ae504831f1a401d89c34bc0405c50ea6d6d5e080e7396605",
    "scope": "2969bc885fbb15638c37f286d3d0b85f23d57918a6bf432ad70bc9958f4d1a2a",
}
PINS = {
    "manifest": "14072deebb73f993759272f19ca687649903c201b49f0d5ff78ede926a8dfcb2",
    "fingerprint": "eb7322ccbdafba33db9ab17a6bc35c793fdce2ff9cb0bad82a38d5920e0d6864",
    "oracle": "9ed9b9ce5a38322f0bf43f9c21606fa5028b3c31b79b248bb0a9090821beac50",
    "1.0.3": "26330942263746e6794deb7def70e17f4848bb64f2fe7ebb4011f5784ca57483",
    "1.0.4": "05380973db4fd848a4c01e043847f4b648e738f8efa9b0c0affe6bf10cb41abf",
    "1.0.5": "23e7b6363ea3ab2e765e836f7bfeba4cf7966dc7045bcbd24c148f14e2d19ed3",
    "rules_json": "e3b2bffa3040507819296c91a5922fd7bd78f4d2d451d06e8dbc37fb596c9a49",
    "rules_markdown": (
        "7f3516a1a2342a0de7180e2eb0b176d468b9ed1ab4e18d3b27447a60db170544"
    ),
    "overlay": "526a08805b88192d2351a0c0b45f9cd6060745ba1a931919e069e9d104c86d02",
}
CASE_IDS = tuple(f"case-{number:02d}" for number in range(1, 15))
OVERLAY_IDS = ("case-03", "case-11")
VIEWS = ("1.0.3", "1.0.4", "1.0.5")
MATERIAL_FIELDS = (
    "runtime",
    "actual_graph",
    "source_context",
)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _verify_attribute_freeze() -> dict[str, str]:
    scope = current._read_pinned_json(
        SCOPE_PATH, ATTRIBUTE_HASHES["scope"], label="attribute scope freeze"
    )
    try:
        hashes = {
            "contract": _sha256(CONTRACT_PATH.read_bytes()),
            "cases": _sha256(CASES_PATH.read_bytes()),
        }
    except OSError as exc:
        raise ValueError("attribute contract/cases freeze is unavailable") from exc
    allowed = scope.get("allowed_existing_changes")
    if (
        hashes["contract"] != ATTRIBUTE_HASHES["contract"]
    ):
        raise ValueError("attribute contract SHA-256 does not match the freeze")
    if hashes["cases"] != ATTRIBUTE_HASHES["cases"]:
        raise ValueError("attribute cases SHA-256 does not match the freeze")
    if (
        scope.get("schema") != "finite-copy-attribute-scope-freeze-v1"
        or scope.get("base_commit") != ATTRIBUTE_BASE_COMMIT
        or scope.get("contract_sha256") != hashes["contract"]
        or scope.get("cases_sha256") != hashes["cases"]
        or scope.get("baseline_source_tree_sha256")
        != ATTRIBUTE_BASELINE_SOURCE_SHA256
        or not isinstance(allowed, list)
        or "src/qiaowenshu_agent/domain/document_relations.py" not in allowed
    ):
        raise ValueError("attribute contract/cases/scope freeze identity is invalid")
    return {**hashes, "scope": ATTRIBUTE_HASHES["scope"]}


def _verify_frozen_inputs() -> tuple[dict[str, str], dict[str, Any]]:
    actual = current._verify_existing_scorer_hashes()
    expected = {
        "1.0.3": PINS["1.0.3"],
        "1.0.4": PINS["1.0.4"],
        "1.0.5": PINS["1.0.5"],
        "rules_v1_json": PINS["rules_json"],
        "rules_v1_markdown": PINS["rules_markdown"],
        "historical_overlay": PINS["overlay"],
    }
    if actual != expected:
        raise ValueError("frozen grader/rule hashes differ from the 91fb1b9 pins")
    boundary._load_frozen_rules()
    return actual, current._verify_historical_af7_reference()


def _verify_bundle(
    bundle: Path,
) -> tuple[Path, Any, str, dict[str, tuple[dict[str, Any], str, list[str]]]]:
    try:
        path = Path(bundle).resolve(strict=True)
        freeze = rescorer.load_evaluator("1.0.3").verify_bundle(path)
    except OSError as exc:
        raise ValueError("the frozen v2 relation bundle is unavailable") from exc
    if (
        freeze.get("manifest_sha256") != PINS["manifest"]
        or freeze.get("bundle_fingerprint") != PINS["fingerprint"]
        or len(freeze.get("checked_files", [])) != 29
    ):
        raise ValueError("verified bundle differs from the frozen v2 manifest")
    oracle_sha = boundary._verified_machine_oracle_sha256(freeze)
    if oracle_sha != PINS["oracle"]:
        raise ValueError("verified v2 machine oracle SHA-256 does not match")
    inputs = rescorer._bundle_case_inputs(freeze)
    if tuple(inputs) != CASE_IDS:
        raise ValueError("verified v2 input case IDs/order do not match")
    return path, freeze, oracle_sha, inputs


def _validated_capture(
    bundle: Path,
    product_report: Path,
    expected_report_sha256: str,
    expected_source_tree_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    validated = rescorer.rescore_report(
        bundle,
        product_report,
        version="1.0.4",
        expected_report_sha256=expected_report_sha256,
        main_reviewer_authorized=True,
    )
    if validated["source_tree_sha256"] != expected_source_tree_sha256:
        raise ValueError(
            "expected_source_tree_sha256 does not match product report metadata"
        )
    try:
        raw = product_report.read_bytes()
    except OSError as exc:
        raise ValueError("unable to reread the validated product report") from exc
    if _sha256(raw) != validated["product_report"]["sha256"]:
        raise ValueError("product report changed after legacy validation")
    report = rescorer._load_json_bytes(raw, label="product report")
    if report.get("source_tree_sha256") != expected_source_tree_sha256:
        raise ValueError("product source-tree metadata changed after validation")
    return validated, report


def _errors_equal_ignoring_order(left: Any, right: Any) -> bool:
    if not isinstance(left, list) or not isinstance(right, list):
        return False

    def encode(item: Any) -> str:
        return json.dumps(
            item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    try:
        return sorted(map(encode, left)) == sorted(map(encode, right))
    except (TypeError, ValueError):
        return False


def rescore_report(
    bundle: Path,
    product_report: Path,
    *,
    expected_report_sha256: str,
    expected_source_tree_sha256: str,
    main_reviewer_authorized: bool,
) -> dict[str, Any]:
    if not main_reviewer_authorized:
        raise PermissionError("snapshot offline scoring requires authorization")
    if not isinstance(expected_report_sha256, str) or not rescorer._is_sha256(
        expected_report_sha256.lower()
    ):
        raise ValueError("expected_report_sha256 must be a 64-character SHA-256")
    if not rescorer._is_sha256(expected_source_tree_sha256):
        raise ValueError(
            "expected_source_tree_sha256 must be a lowercase 64-character SHA-256"
        )

    attribute_hashes = _verify_attribute_freeze()
    scorer_hashes, historical = _verify_frozen_inputs()
    bundle_path, freeze, oracle_sha, bundle_inputs = _verify_bundle(bundle)
    product_report = Path(product_report)
    validated, report = _validated_capture(
        bundle_path,
        product_report,
        expected_report_sha256,
        expected_source_tree_sha256,
    )
    if (
        validated["freeze"]["v2_manifest_sha256"] != freeze["manifest_sha256"]
        or validated["freeze"]["v2_bundle_fingerprint"]
        != freeze["bundle_fingerprint"]
    ):
        raise ValueError("product report freeze does not match the pinned v2 bundle")

    raw_cases = {row["case_id"]: row for row in report["cases"]}
    checked_cases = {row["case_id"]: row for row in validated["cases"]}
    if (
        len(raw_cases) != len(CASE_IDS)
        or set(raw_cases) != set(CASE_IDS)
        or tuple(checked_cases) != CASE_IDS
    ):
        raise ValueError("validated capture case inventory/order changed")

    source_contexts: dict[str, Mapping[str, Any]] = {}
    for case_id in CASE_IDS:
        raw_case, checked = raw_cases[case_id], checked_cases[case_id]
        if (
            raw_case.get("execution_state") != checked["execution_state"]
            or raw_case.get("status") != checked["product_report_status"]
            or any(raw_case.get(key) != checked.get(key) for key in MATERIAL_FIELDS)
            or raw_case.get("reason") != checked.get("reason")
        ):
            raise ValueError(f"{case_id} replay material changed after validation")
        if checked["execution_state"] == "executed":
            graph, context = checked["actual_graph"], checked["source_context"]
            document_id = (
                context.get("document_id") if isinstance(context, Mapping) else None
            )
            if (
                not isinstance(graph, Mapping)
                or not isinstance(context, Mapping)
                or not isinstance(document_id, str)
                or not document_id
                or context.get("source_version") != f"{document_id}:v1"
                or graph.get("source_version") != f"{document_id}:v1"
            ):
                raise ValueError(
                    f"{case_id} captured Registry source_version does not match "
                    "the registered v1 input"
                )
            source_contexts[case_id] = context

    rules = boundary._load_frozen_rules()
    overlay, overlay_sha = boundary._load_overlay(
        current.HISTORICAL_OVERLAY_PATH,
        expected_overlay_sha256=PINS["overlay"],
        expected_report_sha256=boundary.FROZEN_PRODUCT_REPORT_SHA256,
        oracle_sha256=oracle_sha,
        report_sha256=boundary.FROZEN_PRODUCT_REPORT_SHA256,
        rules=rules,
    )
    overlay_rows = current._validate_overlay_inventory(overlay, bundle_inputs)
    executable_ids = tuple(
        case_id for case_id in OVERLAY_IDS if case_id in source_contexts
    )
    executable_overlay = {
        **overlay,
        "cases": [overlay_rows[case_id] for case_id in executable_ids],
    }
    overlay_cases = boundary._validate_overlay_cases(
        executable_overlay,
        freeze,
        bundle_inputs,
        source_contexts,
        boundary.load_evaluator("1.0.4"),
    )
    if tuple(sorted(overlay_cases)) != executable_ids:
        raise ValueError("validated executable historical overlay inventory changed")
    overlay_validation = {
        case_id: (
            {"status": "validated_against_captured_registry_context",
             "execution_state": "executed"}
            if case_id in overlay_cases
            else {
                "status": "not_validated_non_executed",
                "execution_state": checked_cases[case_id]["execution_state"],
                "detail": (
                    "Sidecar hash, case identity, raw-input binding, and contract "
                    "schema were checked. Oracle/context applicability and scoring "
                    "were skipped because the case was not executed."
                ),
            }
        )
        for case_id in OVERLAY_IDS
    }

    case_results: list[dict[str, Any]] = []
    by_view: dict[str, list[dict[str, Any]]] = {version: [] for version in VIEWS}
    for case_id in CASE_IDS:
        raw_case, checked = raw_cases[case_id], checked_cases[case_id]
        state = checked["execution_state"]
        graph, context, runtime = (
            checked.get("actual_graph"),
            checked.get("source_context"),
            checked["runtime"],
        )
        input_sha = bundle_inputs[case_id][1]
        fingerprints: dict[str, str | None] = {
            "bundle_input_sha256": input_sha,
            "actual_graph_canonical_json_sha256": (
                rescorer._canonical_sha256(graph) if graph is not None else None
            ),
            "source_context_canonical_json_sha256": (
                rescorer._canonical_sha256(context) if context is not None else None
            ),
            "runtime_canonical_json_sha256": rescorer._canonical_sha256(runtime),
        }

        if state == "executed":
            oracle_case = bundle_inputs[case_id][0]
            score_103 = rescorer.score_case(
                oracle_case, graph, context, version="1.0.3"
            )
            score_104 = rescorer.score_case(
                oracle_case, graph, context, version="1.0.4"
            )
            if any(
                score_104.get(key) != checked.get(key)
                for key in ("status", "metrics", "errors")
            ):
                raise ValueError(
                    f"{case_id} public 1.0.4 score differs from validation"
                )
            scores = {
                "1.0.3": current._score_record(
                    score_103,
                    scorer_version="1.0.3",
                    scoring_method="frozen 1.0.3 score_case on captured graph",
                    fingerprints=fingerprints,
                ),
                "1.0.4": current._score_record(
                    score_104,
                    scorer_version="1.0.4",
                    scoring_method="frozen 1.0.4 score_case on captured graph",
                    fingerprints=fingerprints,
                ),
            }
            if case_id in overlay_cases:
                oracle_case, evidence_contract = overlay_cases[case_id]
                score_105 = boundary.score_case(
                    oracle_case,
                    graph,
                    context,
                    evidence_contract=evidence_contract,
                )
                scores["1.0.5"] = current._score_record(
                    score_105,
                    scorer_version="1.0.5",
                    scoring_method="frozen 1.0.5 score_case with validated sidecar",
                    fingerprints=fingerprints,
                )
                scores["1.0.5"]["evidence_contract_validation"] = (
                    overlay_validation[case_id]
                )
            else:
                score_105 = score_104
                scores["1.0.5"] = current._score_record(
                    score_104,
                    scorer_version="1.0.4",
                    scoring_method=(
                        "frozen 1.0.4 score_case; case is outside the "
                        "historical overlay"
                    ),
                    fingerprints=fingerprints,
                )
            selected = {"1.0.3": score_103, "1.0.4": score_104, "1.0.5": score_105}
            for version, score in selected.items():
                by_view[version].append(
                    {
                        "case_id": case_id,
                        "status": score["status"],
                        "execution_state": state,
                        "metrics": deepcopy(score.get("metrics", {})),
                        "errors": deepcopy(score.get("errors", [])),
                        "event_counts": deepcopy(score.get("event_counts", {})),
                    }
                )
        else:
            scores = {}
            for version in VIEWS:
                overlay_case = version == "1.0.5" and case_id in OVERLAY_IDS
                scorer_version = (
                    "1.0.4" if version == "1.0.5" and not overlay_case else version
                )
                scores[version] = current._not_scored_record(
                    raw_case,
                    scorer_version=scorer_version,
                    execution_state=state,
                    scoring_method=(
                        "not scored; captured case was not executed"
                        if overlay_case
                        else "not scored because no executable graph was captured"
                    ),
                    fingerprints=fingerprints,
                    evidence_contract_validation=(
                        overlay_validation[case_id] if overlay_case else None
                    ),
                )
                by_view[version].append(
                    {
                        "case_id": case_id,
                        "status": raw_case["status"],
                        "execution_state": state,
                        "metrics": {},
                        "errors": deepcopy(raw_case.get("errors", [])),
                        "event_counts": deepcopy(raw_case.get("event_counts", {})),
                    }
                )
        if any(row["replay_fingerprints"] != fingerprints for row in scores.values()):
            raise ValueError(f"{case_id} replay fingerprints differ across views")

        result: dict[str, Any] = {
            "case_id": case_id,
            "execution_state": state,
            "product_capture_status": raw_case["status"],
            "product_capture_errors": deepcopy(raw_case.get("errors", [])),
            "input_sha256": input_sha,
            "runtime": deepcopy(runtime),
            "replay_fingerprints": fingerprints,
            "replay_fingerprints_consistent_across_views": True,
            "scores": scores,
        }
        if "reason" in raw_case:
            result["reason"] = deepcopy(raw_case["reason"])
        if graph is not None:
            result["actual_graph"] = deepcopy(graph)
        if context is not None:
            result["source_context"] = deepcopy(context)
        if state == "executed":
            capture_score = current._captured_score(raw_case)
            errors_match = capture_score["errors"] == scores["1.0.3"]["errors"]
            result["product_capture_1_0_3_score"] = capture_score
            result["capture_1_0_3_parity"] = {
                "status_match": capture_score["status"] == scores["1.0.3"]["status"],
                "metrics_match": capture_score["metrics"] == scores["1.0.3"]["metrics"],
                "errors_match": errors_match,
                "errors_order_only_difference": (
                    not errors_match
                    and _errors_equal_ignoring_order(
                        capture_score["errors"], scores["1.0.3"]["errors"]
                    )
                ),
            }
        case_results.append(result)

    methods = {
        "1.0.3": "frozen 1.0.3 score_case",
        "1.0.4": "frozen 1.0.4 score_case",
        "1.0.5": "frozen 1.0.5 on case-03/case-11; 1.0.4 fallback elsewhere",
    }
    scoring_views = {
        version: {
            **rescorer._aggregate_results(by_view[version]),
            "method": methods[version],
            "overlay_case_ids": list(OVERLAY_IDS) if version == "1.0.5" else [],
        }
        for version in VIEWS
    }
    capture_summary = rescorer._aggregate_results(
        [
            {key: row.get(key, {}) for key in (
                "case_id", "status", "execution_state", "metrics", "errors",
                "event_counts",
            )}
            for row in report["cases"]
        ]
    )
    helper_path = Path(__file__).resolve()
    source_sha = report["source_tree_sha256"]
    return {
        "schema": "document-relations-source-snapshot-rescore-v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "classification": (
            "offline scoring of preserved product capture through frozen 1.0.5 API"
        ),
        "interpretation": (
            "All views score one preserved capture offline. The expected source "
            "hash is matched to capture metadata only; independent Git proof is "
            "required from the main reviewer."
        ),
        "source_capture": {
            "path": product_report.resolve().as_posix(),
            "sha256": validated["product_report"]["sha256"],
            "classification": report.get("classification"),
            "capture_base_commit_metadata": report["base_commit"],
            "capture_repository_context": report.get("repository_context"),
            "git_revision_at_capture": report.get("git_revision_at_run"),
            "evaluator_version": report["evaluator"]["version"],
            "evaluator_sha256": report["evaluator"]["sha256"],
            "source_tree_sha256": source_sha,
            "execution_summary": capture_summary,
        },
        "product_source": {
            "source_tree_sha256": source_sha,
            "source_tree_sha256_algorithm": report["source_tree_sha256_algorithm"],
            "expected_source_tree_sha256": expected_source_tree_sha256,
            "capture_base_commit_metadata": report["base_commit"],
            "product_commit_attested": False,
            "git_proof_status": "not_performed_main_reviewer_proof_required",
        },
        "source_identity": {
            "expected_source_tree_sha256": expected_source_tree_sha256,
            "captured_source_tree_sha256": source_sha,
            "metadata_match": True,
            "verification_method": "capture metadata equality only",
            "git_proof_performed": False,
            "git_proof_status": "not_performed_main_reviewer_proof_required",
        },
        "helper": {
            "path": helper_path.relative_to(ROOT).as_posix(),
            "sha256": _sha256(helper_path.read_bytes()),
        },
        "frozen_inputs": {
            "attribute_base_commit": ATTRIBUTE_BASE_COMMIT,
            "attribute_contract_sha256": attribute_hashes["contract"],
            "attribute_cases_sha256": attribute_hashes["cases"],
            "attribute_scope_freeze_sha256": attribute_hashes["scope"],
            "v2_manifest_sha256": freeze["manifest_sha256"],
            "v2_bundle_fingerprint": freeze["bundle_fingerprint"],
            "machine_oracle_sha256": oracle_sha,
            "payload_files": len(freeze["checked_files"]),
            "case_input_sha256": {key: bundle_inputs[key][1] for key in CASE_IDS},
            "overlay_sha256": overlay_sha,
            "overlay_case_ids": list(OVERLAY_IDS),
            "rules_json_sha256": scorer_hashes["rules_v1_json"],
            "rules_markdown_sha256": scorer_hashes["rules_v1_markdown"],
        },
        "frozen_scorers": {version: PINS[version] for version in VIEWS},
        "scoring_views": scoring_views,
        "historical_overlay_validation": overlay_validation,
        "historical_af7_reference": historical,
        "claims": {
            "main_reviewer_authorized": main_reviewer_authorized,
            "offline_scoring": True,
            "product_runtime_invoked_during_rescore": False,
            "model_invoked_during_rescore": False,
            "product_capture_reexecuted": False,
            "source_git_identity_verified": False,
            "actual_graphs_synthesized": False,
            "create_only_output": True,
        },
        "cases": case_results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--product-report", type=Path, required=True)
    parser.add_argument("--expected-report-sha256", required=True)
    parser.add_argument("--expected-source-tree-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--main-reviewer-authorized", action="store_true")
    args = parser.parse_args(argv)
    if not args.main_reviewer_authorized:
        parser.error("snapshot offline scoring requires authorization")
    output = args.output.resolve()
    if output.exists():
        parser.error(f"refusing to overwrite existing report: {output}")
    try:
        report = rescore_report(
            args.bundle,
            args.product_report,
            expected_report_sha256=args.expected_report_sha256,
            expected_source_tree_sha256=args.expected_source_tree_sha256,
            main_reviewer_authorized=True,
        )
    except (OSError, PermissionError, ValueError) as exc:
        parser.error(str(exc))
    output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    try:
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
    except FileExistsError:
        parser.error(f"refusing to overwrite existing report: {output}")
    if any(view["failed"] for view in report["scoring_views"].values()):
        return 1
    if any(view["not_run"] for view in report["scoring_views"].values()):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
