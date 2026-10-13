"""Reviewer regression for logical inheritance versus other parent kinds."""

from __future__ import annotations

import argparse
import hashlib
import json
import runpy
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
EXPECTED = {
    "semantic_parent": True,
    "logical_parent": True,
    "condition_parent": True,
    "attribute_parent": False,
    "contextual_parent": False,
    "structural_list": False,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("refusing to overwrite logical-parent check")
    test_path = ROOT / "tests/evals/test_document_relations_boundary_rescore.py"
    ns = runpy.run_path(str(test_path))
    checks = []
    for layer, expected in EXPECTED.items():
        case, graph, context, contract = ns["_fixture"](mode="inherited")
        node = next(
            row for row in graph["condition_nodes"] if row["node_id"] == "node-S1"
        )
        node["parent_relations"][0]["layer"] = layer
        before = json.dumps(graph, sort_keys=True, ensure_ascii=False)
        result = ns["_score"](case, graph, context, contract)
        actual = result["status"] == "passed"
        checks.append(
            {
                "layer": layer,
                "expected_accept": expected,
                "actual_accept": actual,
                "input_preserved": before
                == json.dumps(graph, sort_keys=True, ensure_ascii=False),
                "passed": actual == expected,
                "errors": result["errors"],
                "evidence_audit": result["evidence_audit"],
            }
        )
    report = {
        "schema": "boundary-evidence-logical-parent-review-v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "classification": "public synthetic reviewer counterexamples",
        "grader_sha256": hashlib.sha256(
            (ROOT / "scripts/run_document_relations_boundary_rescore.py").read_bytes()
        ).hexdigest(),
        "fixture_tests_sha256": hashlib.sha256(test_path.read_bytes()).hexdigest(),
        "passed": sum(row["passed"] for row in checks),
        "total": len(checks),
        "false_accept": sum(
            not row["expected_accept"] and row["actual_accept"] for row in checks
        ),
        "false_block": sum(
            row["expected_accept"] and not row["actual_accept"] for row in checks
        ),
        "checks": checks,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    if report["passed"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
