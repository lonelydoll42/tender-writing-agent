"""Reviewer replay of public source-role and group-header regressions."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PUBLIC = ROOT / "benchmarks/document_relations/boundary-evidence-regression/20261013"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def git(*args):
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def source_identity():
    files = {}
    aggregate = hashlib.sha256()
    for path in sorted((ROOT / "src").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        digest = sha(path)
        files[relative] = digest
        aggregate.update(relative.encode() + b"\t" + bytes.fromhex(digest) + b"\n")
    return {
        "source_commit": None,
        "checkout_base_commit": git("rev-parse", "HEAD"),
        "source_identity_basis": "exact source_files hashes, not checkout HEAD",
        "source_tree_sha256": aggregate.hexdigest(),
        "source_files": files,
    }


def freeze(path):
    tracked = git("ls-files", "-z").split("\0")
    files = {}
    for relative in tracked:
        target = ROOT / relative
        if not relative or not target.is_file():
            continue
        files[relative] = {
            "working_sha256": sha(target),
            "git_blob": git("rev-parse", f"HEAD:{relative}"),
        }
    save(
        path,
        {
            "schema": "source-role-baseline-freeze-v1",
            "frozen_at": datetime.now().astimezone().isoformat(),
            "source_commit": git("rev-parse", "HEAD"),
            "tracked_files": files,
            "contract_sha256": sha(Path(__file__).with_name("contract.md")),
            "isolation_sha256": sha(
                Path(__file__).with_name("isolation-status.json")
            ),
            "classification": "public regression only; unseen evaluation not_run",
        },
    )


async def capture(helpers, path):
    payload = json.loads(path.read_bytes())
    legacy = helpers.old.load_evaluator("1.0.3")
    cases = []
    for entry in payload["cases"]:
        raw = path.parent / entry["input"]
        if sha(raw) != entry["raw_input_sha256"]:
            raise ValueError(f"{entry['case_id']}: public raw input changed")
        runtime = await legacy._run_input(raw, entry["case_id"])
        cases.append({"case_id": entry["case_id"], "runtime": runtime})
    return {
        "schema": "boundary-evidence-product-capture-v1",
        "captured_at": datetime.now().astimezone().isoformat(),
        **source_identity(),
        "cases_sha256": sha(path),
        "classification": "actual Registry/Runtime public output; not synthetic",
        "cases": cases,
    }


def expected_role(variant):
    if variant in {"forged_raw_valid_flag", "wrong_source_version"}:
        return "raw_source"
    if variant.startswith("boundary_"):
        return "termination"
    if variant in {
        "parent_not_confirmed",
        "parent_scope_not_confirmed",
        "parent_link_missing",
        "structural_parent_only",
        "parent_link_wrong_group",
        "parent_link_wrong_source",
        "additional_conflicting_parent",
    }:
        return "inheritance"
    if variant == "operator_from_adjacent_group":
        return "operator"
    if variant == "forged_confirmed_from_review_source":
        return "operator_or_inheritance"
    return "scope"


def check_reasons(helpers, grader, payload, captured):
    legacy = helpers.old.load_evaluator("1.0.3")
    runs = {row["case_id"]: row["runtime"] for row in captured["cases"]}
    checks = []
    not_applicable = []
    for entry in payload["cases"]:
        runtime = runs[entry["case_id"]]
        if runtime["execution_state"] != "executed":
            continue
        graph, context = runtime["graph"], runtime["source_context"]
        if entry["expected_product_review"]:
            variants = [
                ("forged_confirmed_from_review_source", helpers.forge(entry, context))
            ]
        else:
            try:
                helpers.bind(entry, graph)
            except ValueError:
                not_applicable.append(
                    {
                        "case_id": entry["case_id"],
                        "reason": "actual product has no complete tree",
                    }
                )
                continue
            variants = []
            for variant in payload["negative_mutations"]:
                role = expected_role(variant)
                if (
                    role == "inheritance"
                    and not entry["evidence_contract"]["groups"]["S1"]["inheritance"]
                ):
                    continue
                variants.append(
                    (variant, helpers.mutate(entry, graph, context, variant))
                )
        for variant, changed in variants:
            before = helpers.digest(changed)
            source = legacy._validate_graph_source_references(changed, context)
            scored = grader.score_case(
                entry["case"],
                changed,
                context,
                evidence_contract=entry["evidence_contract"],
            )
            audit = scored["evidence_audit"]
            role = expected_role(variant)
            roles = (
                ("operator", "inheritance")
                if role == "operator_or_inheritance"
                else (role,)
            )
            rejected = [
                {
                    "group_id": group_id,
                    "role": key,
                    "reason": result["reason"],
                }
                for group_id, group in audit["groups"].items()
                for key in roles
                if isinstance((result := group.get(key)), dict)
                and result.get("passed") is False
                and result.get("reason")
            ]
            raw_ok = source["invalid_references"] == 0
            if role == "raw_source":
                role_ok = not raw_ok
            else:
                role_ok = raw_ok and bool(rejected)
            checks.append(
                {
                    "case_id": entry["case_id"],
                    "variant": variant,
                    "expected_rejection_role": role,
                    "raw_invalid_references": source["invalid_references"],
                    "raw_failures": source["failures"],
                    "semantic_rejections": rejected,
                    "contract_errors": audit["contract_errors"],
                    "actual_rejected": scored["status"] != "passed",
                    "passed": (
                        scored["status"] != "passed"
                        and role_ok
                        and helpers.digest(changed) == before
                    ),
                }
            )
    return {
        "schema": "source-role-negative-reasons-v1",
        "classification": "mutated graphs, not product/business decisions",
        "summary": {
            "passed": sum(row["passed"] for row in checks),
            "total": len(checks),
            "semantic_checks": sum(
                row["expected_rejection_role"] != "raw_source" for row in checks
            ),
            "semantic_checks_with_invalid_source": sum(
                row["expected_rejection_role"] != "raw_source"
                and row["raw_invalid_references"] > 0
                for row in checks
            ),
        },
        "not_applicable": not_applicable,
        "checks": checks,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--freeze-tests", type=Path)
    parser.add_argument("--test-file", type=Path, action="append", default=[])
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--label", default="public")
    args = parser.parse_args()
    if args.freeze:
        freeze(args.freeze)
        return
    if args.freeze_tests:
        if not args.test_file:
            parser.error("--test-file is required with --freeze-tests")
        save(
            args.freeze_tests,
            {
                "schema": "source-role-test-first-freeze-v1",
                "frozen_at": datetime.now().astimezone().isoformat(),
                "files": {
                    path.as_posix(): sha(path) for path in args.test_file
                },
            },
        )
        return
    if not args.output_directory:
        parser.error("--output-directory is required when not freezing")
    output = args.output_directory
    output.mkdir(parents=True, exist_ok=False)
    helpers = load("public_boundary_helpers", PUBLIC / "check-boundary.py")
    grader = load(
        "public_boundary_grader",
        ROOT / "scripts/run_document_relations_boundary_rescore.py",
    )
    summaries = {}
    for name, path in (
        ("development", PUBLIC / "development/cases.json"),
        ("public-h01-h06", PUBLIC / "reserved-exposed/cases.json"),
    ):
        payload = json.loads(path.read_bytes())
        captured = asyncio.run(capture(helpers, path))
        save(output / f"{name}-capture.json", captured)
        result = helpers.check(payload, captured, path)
        save(output / f"{name}-check.json", result)
        reasons = check_reasons(helpers, grader, payload, captured)
        save(output / f"{name}-negative-reasons.json", reasons)
        summaries[name] = {
            "product_and_graph_checks": result["summary"],
            "negative_reasons": reasons["summary"],
        }
    report = {
        "schema": "source-role-public-replay-v1",
        "label": args.label,
        "generated_at": datetime.now().astimezone().isoformat(),
        **source_identity(),
        "grader_version": grader.EVALUATOR_VERSION,
        "grader_sha256": sha(
            ROOT / "scripts/run_document_relations_boundary_rescore.py"
        ),
        "unseen_evaluation": "not_run",
        "business_materials": "not_run",
        "summary": summaries,
    }
    save(output / "summary.json", report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
