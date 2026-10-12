"""Main-reviewer offline boundary checks; never invokes the product runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path


def run(root: Path) -> dict:
    sys.path.insert(0, str(root))
    from scripts import run_document_relations_rescore as evaluator

    product_path = root / (
        "benchmarks/document_relations/reports/"
        "inheritance-followup-20261012/relations-score.json"
    )
    product_bytes = product_path.read_bytes()
    product = json.loads(product_bytes)
    oracle = json.loads(
        (
            root / "benchmarks/document_relations/reserved/v2/machine-oracle.json"
        ).read_bytes()
    )
    case = next(item for item in oracle["cases"] if item["case_id"] == "case-11")
    saved = next(item for item in product["cases"] if item["case_id"] == "case-11")
    baseline_graph = saved["actual_graph"]
    baseline_context = saved["source_context"]
    results = []

    def check(name, mutate, should_pass=False, expected_metric=None):
        graph, context = deepcopy(baseline_graph), deepcopy(baseline_context)
        mutate(graph, context)
        before = json.dumps([graph, context], ensure_ascii=False, sort_keys=True)
        score = evaluator.score_case(case, graph, context, version="1.0.4")
        passed = (score["status"] == "passed") == should_pass
        if expected_metric is not None:
            passed = passed and score["metrics"][expected_metric]["numerator"] > 0
        after = json.dumps([graph, context], ensure_ascii=False, sort_keys=True)
        passed = passed and before == after
        results.append(
            {
                "name": name,
                "expected_score": "passed" if should_pass else "failed",
                "actual_score": score["status"],
                "check_passed": passed,
                "input_unchanged": before == after,
                "expected_metric": expected_metric,
                "score": score,
                "actual_graph": graph,
                "source_context": context,
            }
        )

    def atom(graph):
        return next(node for node in graph["condition_nodes"] if node["op"] == "ATOM")

    check("original-literal-mapping", lambda g, c: None, should_pass=True)
    check(
        "supplied-line-instead-of-derived",
        lambda g, c: atom(g)["source_references"][0].update(line_number=2),
        should_pass=True,
    )
    for name, text in (
        ("wrong-form-number", "近两年1.10号表"),
        ("decimal-punctuation-lost", "近两年19号表"),
        ("wrong-year", "近三年1.9号表"),
        ("quoted-text-plus-negation", "无需提交近两年1.9号表"),
        ("quoted-text-plus-quantity", "近两年1.9号表三份"),
        ("only-a-substring", "近两年1.9号"),
        ("quote-with-wrong-suffix", "近两年1.9号表复印件免提交"),
    ):
        check(
            name,
            lambda g, c, text=text: atom(g).update(text=text),
            expected_metric="condition_omission",
        )
    check(
        "candidate-does-not-become-confirmed",
        lambda g, c: atom(g).update(status="candidate"),
    )
    for name, changes in (
        ("wrong-document", {"document_id": "other-document"}),
        ("wrong-version", {"source_version": "other-version"}),
        (
            "wrong-offset-with-asserted-valid",
            {"char_start": 28, "_raw_coordinate_valid": True},
        ),
        ("wrong-line", {"line_number": 3}),
        ("wrong-quote", {"quote": "近两年1.10号表"}),
    ):
        check(
            name,
            lambda g, c, changes=changes: atom(g)["source_references"][0].update(
                changes
            ),
            expected_metric="source_invalid",
        )

    def duplicate_atom(graph, context):
        node = deepcopy(atom(graph))
        node["node_id"] = "extra-duplicate-atom"
        graph["condition_nodes"].append(node)

    check(
        "duplicate-literal-atoms",
        duplicate_atom,
        expected_metric="wrong_split_atom_units",
    )

    def wrong_group_operator(graph, context):
        node = next(
            node
            for node in graph["condition_nodes"]
            if node["op"] == "OR" and len(node["children"]) == 2
        )
        node["op"] = "AND"

    check(
        "correct-atoms-wrong-operator",
        wrong_group_operator,
        expected_metric="operator_group_structure",
    )

    def flatten(graph, context):
        root = next(node for node in graph["condition_nodes"] if node["op"] == "AND")
        root["children"] = [
            node["node_id"] for node in graph["condition_nodes"] if node["op"] == "ATOM"
        ]

    check(
        "correct-atoms-flattened-tree",
        flatten,
        expected_metric="operator_group_structure",
    )
    return {
        "schema": "document-relations-remap-boundary-v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "classification": "public_original_case_mutations_not_blind",
        "product_report_sha256": hashlib.sha256(product_bytes).hexdigest(),
        "evaluator_version": evaluator.EVALUATOR_VERSION,
        "checker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "summary": {
            "check_count": len(results),
            "passed": sum(item["check_passed"] for item in results),
            "failed": sum(not item["check_passed"] for item in results),
            "not_run": 0,
        },
        "claims": {
            "runtime_executed": False,
            "product_improvement": False,
            "business_materials": "not_run",
        },
        "checks": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("refusing to overwrite a boundary report")
    report = run(args.root.resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["summary"]))
    return 1 if report["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
