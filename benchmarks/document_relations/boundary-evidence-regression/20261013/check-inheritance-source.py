"""Reject accurate inherited OR citations when the raw local/scope proof conflicts."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("refusing to overwrite source-inheritance check")
    helpers = load_module("reviewer_helpers", HERE / "check-boundary.py")
    evaluator = load_module(
        "boundary_source_guard",
        ROOT / "scripts/run_document_relations_boundary_rescore.py",
    )
    cases = json.loads(args.cases.read_bytes())
    captures = json.loads(args.captures.read_bytes())
    if captures["cases_sha256"] != hashlib.sha256(args.cases.read_bytes()).hexdigest():
        raise ValueError("capture/annotation identity mismatch")
    runs = {entry["case_id"]: entry["runtime"] for entry in captures["cases"]}
    outcomes = []
    for entry in cases["cases"]:
        if not entry["expected_product_review"]:
            continue
        runtime = runs[entry["case_id"]]
        if runtime["execution_state"] != "executed":
            raise ValueError("source guard requires an actually captured raw input")
        context = runtime["source_context"]
        page = context["pages"][0]
        header = page.split("\n", 1)[0]
        selection = header.split("但", 1)[1].rstrip("：:")
        start = page.index(selection)
        inherited_operator = {
            "page": 1,
            "line": 1,
            "quote": selection,
            "char_start": start,
            "char_end": start + len(selection),
        }
        heading = {
            "page": 1,
            "line": 1,
            "quote": header,
            "char_start": 0,
            "char_end": len(header),
        }
        for spoof_flags in (False, True):
            counterexample = deepcopy(entry)
            groups = counterexample["evidence_contract"]["groups"]
            labels = [groups[key]["scope_sources"][0] for key in ("S1", "S2")]
            groups["S1"]["operator_sources"] = [inherited_operator]
            groups["S1"]["inheritance"] = {
                "parent_group_id": "S0",
                "applicability_sources": [heading],
                "parent_link_sources": [
                    groups["S0"]["operator_sources"][0],
                    labels[0],
                ],
                "declared_count": 2,
                "group_labels": labels,
                "contiguous": entry["negative_reason"] != "intervening_paragraph",
            }
            if spoof_flags:
                groups["S1"]["local_instruction"]["state"] = "absent"
                groups["S1"]["inheritance"]["contiguous"] = True
            graph = helpers.forge(counterexample, context)
            frozen_graph = helpers.digest(graph)
            result = evaluator.score_case(
                counterexample["case"],
                graph,
                context,
                evidence_contract=counterexample["evidence_contract"],
            )
            outcomes.append(
                {
                    "case_id": entry["case_id"],
                    "spoof_flags": spoof_flags,
                    "negative_reason": entry["negative_reason"],
                    "operator_reference_is_accurate_ancestor_or": inherited_operator,
                    "expected_accept": False,
                    "actual_accept": result["status"] == "passed",
                    "input_preserved": helpers.digest(graph) == frozen_graph,
                    "passed": (
                        result["status"] != "passed"
                        and helpers.digest(graph) == frozen_graph
                    ),
                    "errors": result.get("errors", []),
                    "evidence_audit": result.get("evidence_audit"),
                }
            )
    report = {
        "schema": "boundary-evidence-independent-source-guard-v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "classification": "deliberately incorrect confirmed graphs, not product output",
        "cases_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        "capture_sha256": hashlib.sha256(args.captures.read_bytes()).hexdigest(),
        "grader_sha256": hashlib.sha256(
            (ROOT / "scripts/run_document_relations_boundary_rescore.py").read_bytes()
        ).hexdigest(),
        "passed": sum(row["passed"] for row in outcomes),
        "total": len(outcomes),
        "false_accept": sum(row["actual_accept"] for row in outcomes),
        "checks": outcomes,
    }
    helpers.save(args.output, report)
    if report["passed"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
