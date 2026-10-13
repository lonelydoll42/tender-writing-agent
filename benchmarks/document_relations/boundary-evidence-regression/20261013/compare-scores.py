"""Reviewer comparison of old/new grading of the same preserved product output."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path


EXPECTED_INPUT = "1745cb650edca81e163fc773c71cd9db96e33b3e2df10dc3b8c208af050eb7b7"


def canonical(value) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def compare(product_path: Path, old_path: Path, new_path: Path) -> dict:
    raw_product = product_path.read_bytes()
    if hashlib.sha256(raw_product).hexdigest() != EXPECTED_INPUT:
        raise ValueError("comparison input is not the frozen original output")
    product, old, new = [
        json.loads(path.read_bytes()) for path in (product_path, old_path, new_path)
    ]
    source_sha = product["source_tree_sha256"]
    if (
        old["source_tree_sha256"] != source_sha
        or new["source_tree_sha256"] != source_sha
    ):
        raise ValueError("rescores identify a different product source tree")
    by_version = [
        {row["case_id"]: row for row in report["cases"]}
        for report in (product, old, new)
    ]
    if any(set(rows) != set(by_version[0]) for rows in by_version):
        raise ValueError("case identity set changed")
    comparisons = []
    for case_id, original in by_version[0].items():
        before, after = by_version[1][case_id], by_version[2][case_id]
        equality = {
            field: original[field] == before[field] == after[field]
            for field in (
                "actual_graph",
                "source_context",
                "runtime",
                "execution_state",
            )
        }
        if not all(equality.values()):
            raise ValueError(f"product replay material changed: {case_id}")
        for report in (before, after):
            for field, fingerprint in (
                ("actual_graph", "actual_graph_canonical_json_sha256"),
                ("source_context", "source_context_canonical_json_sha256"),
            ):
                if report[fingerprint] != canonical(original[field]):
                    raise ValueError(f"report fingerprint mismatch: {case_id}/{field}")
        metric_delta = {
            name: {
                "old": before["metrics"].get(name),
                "new": after["metrics"].get(name),
            }
            for name in sorted(set(before["metrics"]) | set(after["metrics"]))
            if before["metrics"].get(name) != after["metrics"].get(name)
        }
        comparisons.append(
            {
                "case_id": case_id,
                "product_material_preserved": equality,
                "original_product_graph_sha256": canonical(original["actual_graph"]),
                "source_context_sha256": canonical(original["source_context"]),
                "status": {"old": before["status"], "new": after["status"]},
                "atoms": {
                    "old": before["matched_atom_ids"],
                    "new": after["matched_atom_ids"],
                },
                "groups": {
                    "old": before["matched_group_ids"],
                    "new": after["matched_group_ids"],
                },
                "metric_delta": metric_delta,
                "old_errors": before.get("errors", []),
                "new_errors": after.get("errors", []),
                "evidence_audit": after.get("evidence_audit"),
            }
        )
    return {
        "schema": "boundary-evidence-same-output-comparison-v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "classification": "grader comparison, not product parsing improvement",
        "product_report_sha256": EXPECTED_INPUT,
        "product_source_tree_sha256": source_sha,
        "old_report_sha256": hashlib.sha256(old_path.read_bytes()).hexdigest(),
        "new_report_sha256": hashlib.sha256(new_path.read_bytes()).hexdigest(),
        "old_evaluator": old["evaluator"],
        "new_evaluator": new["evaluator"],
        "old_summary": old["summary"],
        "new_summary": new["summary"],
        "all_14_original_materials_preserved": len(comparisons) == 14,
        "changed_cases": [
            row["case_id"]
            for row in comparisons
            if row["metric_delta"] or row["status"]["old"] != row["status"]["new"]
        ],
        "cases": comparisons,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("product", "old", "new", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("refusing to overwrite comparison")
    result = compare(args.product, args.old, args.new)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


if __name__ == "__main__":
    main()
