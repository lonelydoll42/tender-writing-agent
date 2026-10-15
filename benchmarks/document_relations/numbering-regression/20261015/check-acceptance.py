"""Check actual numbered-material semantics independently of the frozen grader."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import re
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
early = argparse.ArgumentParser(add_help=False)
early.add_argument("--product-root", type=Path, default=ROOT)
PRODUCT_ROOT = early.parse_known_args()[0].product_root.resolve(strict=True)
sys.path.insert(0, str(PRODUCT_ROOT))
sys.path.insert(0, str(PRODUCT_ROOT / "src"))

from qiaowenshu_agent.core.contracts import SkillRequest  # noqa: E402
from qiaowenshu_agent.core.files import ProjectFileRegistry  # noqa: E402
from qiaowenshu_agent.core.runtime import AgentRuntime  # noqa: E402
from qiaowenshu_agent.skills import build_default_registry  # noqa: E402
from scripts import run_document_relations_eval as legacy  # noqa: E402
from scripts import run_document_relations_rescore as scorer  # noqa: E402
from scripts.run_document_relations_negation_eval import _step  # noqa: E402

REGRESSION = ROOT / "benchmarks/document_relations/numbering-regression/20261015"


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def cites(value, *texts, field="source_references"):
    quotes = [r.get("quote", "") for r in value.get(field, []) if isinstance(r, dict)]
    return all(any(text in quote for quote in quotes) for text in texts)


def pair_errors(case, graph):
    errors = []
    labels = case["labels"]
    texts = [f"编号{label}项" for label in labels]
    nodes = graph.get("condition_nodes", [])
    atoms = [node for node in nodes if node.get("op") == "ATOM"]
    roles = []
    for text in texts:
        found = [node for node in atoms if node.get("text") == text]
        if len(found) != 1:
            errors.append(f"one exact source material ATOM required: {text}")
            continue
        atom = found[0]
        roles.append(atom)
        if atom.get("status") != "confirmed":
            errors.append(f"explicit material is not confirmed: {text}")
        if not any(ref.get("quote") == text for ref in atom["source_references"]):
            errors.append(f"material leaf lacks exact original occurrence: {text}")
    if len(atoms) != 2 or len(roles) != 2:
        errors.append("exactly two explicit material leaves required")
        return errors
    member_ids = [node["node_id"] for node in roles]
    groups = [node for node in nodes if node.get("op") != "ATOM"]
    if len(groups) != 1:
        return errors + ["one direct AND required"]
    group = groups[0]
    if (
        group.get("op") != "AND"
        or group.get("status") != "confirmed"
        or group.get("children") != member_ids
    ):
        errors.append("direct AND/status/members differ from explicit pair")
    if graph.get("roots") != [group["node_id"]]:
        errors.append("material pair does not have one logical root")
    range_text = f"编号{labels[0]}至{labels[1]}"
    count = re.search(r"共(?:两|二|2)项材料", case["input_text"]).group()
    enumeration = f"{texts[0]}和{texts[1]}"
    basis = (range_text, enumeration, count)
    if (
        group.get("operator_relation", {}).get("status") != "confirmed"
        or not cites(group.get("operator_relation", {}), "均须提交")
        or not cites(group, "均须提交", field="operator_source_references")
    ):
        errors.append("operator duty is not proved")
    scope = group.get("scope_relation", {})
    if (
        scope.get("status") != "confirmed"
        or scope.get("target_node_ids") != member_ids
        or not cites(scope, *basis, field="scope_source_references")
        or not cites(scope, *texts, field="member_source_references")
        or not cites(
            scope, case["input_text"].strip(), field="boundary_source_references"
        )
    ):
        errors.append("node scope/member/terminal evidence duty failed")
    block_scopes = [
        scope
        for block in graph.get("block_relations", [])
        for scope in block.get("scope_relations", [])
    ]
    if len(block_scopes) != 1:
        errors.append("one block scope required")
    else:
        block_scope = block_scopes[0]
        if (
            block_scope.get("operator") != "AND"
            or block_scope.get("status") != "confirmed"
            or block_scope.get("target_node_ids") != member_ids
            or block_scope.get("operator_relation", {}).get("status") != "confirmed"
            or not cites(block_scope.get("operator_relation", {}), "均须提交")
            or not cites(block_scope, "均须提交", field="operator_source_references")
            or not cites(block_scope, *basis, field="scope_source_references")
            or not cites(
                block_scope,
                case["input_text"].strip(),
                field="boundary_source_references",
            )
        ):
            errors.append("block and node scopes disagree or lack role evidence")
    for atom in roles:
        parents = [
            parent
            for parent in atom.get("parent_relations", [])
            if parent.get("layer") == "semantic_parent"
        ]
        if (
            len(parents) != 1
            or parents[0].get("status") != "confirmed"
            or parents[0].get("target_node_ids") != [group["node_id"]]
            or not cites(parents[0], *basis)
        ):
            errors.append("material semantic parent has wrong target or source")
    if graph.get("references"):
        errors.append("material labels must not create discourse references")
    return errors


def check_graph(case, graph, context):
    source = legacy._validate_graph_source_references(graph, context)
    errors = []
    if (
        graph.get("document_id") != context["document_id"]
        or graph.get("source_version") != context["source_version"]
    ):
        errors.append("graph source identity/version differs from Registry")
    if source["invalid_references"]:
        errors.append("invalid raw source references")
    nodes = graph.get("condition_nodes", [])
    ids = [node.get("node_id") for node in nodes]
    if len(ids) != len(set(ids)) or not all(ids):
        errors.append("condition node IDs must be unique and nonempty")
    expectation = case["expectation"]
    if expectation == "confirmed_pair":
        errors.extend(pair_errors(case, graph))
    elif expectation == "review_numbering":
        if any(
            node.get("status") == "confirmed"
            and (node.get("op") != "ATOM" or re.search(r"编号\d", node.get("text", "")))
            for node in nodes
        ):
            errors.append("unsupported numbered expression is confirmed")
        reviews = [
            node
            for node in nodes
            if node.get("status") in {"candidate", "unresolved"}
            and "编号" in node.get("text", "")
            and node.get("reason")
            and cites(node, case["input_text"].splitlines()[0])
        ]
        if not reviews:
            errors.append("numbering needs explicit review state and original text")
        if any(
            scope.get("status") == "confirmed"
            for block in graph.get("block_relations", [])
            for scope in block.get("scope_relations", [])
        ):
            errors.append("unsupported numbering has a confirmed scope")
    elif expectation == "preserve_explicit_group":
        atoms = [node for node in nodes if node.get("op") == "ATOM"]
        groups = [node for node in nodes if node.get("op") != "ATOM"]
        if (
            [node.get("text") for node in atoms] != case["preserved_atoms"]
            or any(node.get("status") != "confirmed" for node in atoms)
            or len(groups) != 1
            or groups[0].get("op") != "AND"
            or groups[0].get("status") != "confirmed"
            or groups[0].get("children") != [node["node_id"] for node in atoms]
        ):
            errors.append("ordinary explicit material list was changed or blocked")
    elif expectation == "preserve":
        atoms = [node for node in nodes if node.get("op") == "ATOM"]
        if sorted(n.get("text", "") for n in atoms) != sorted(case["preserved_atoms"]):
            errors.append("amount/material control atoms changed or expanded")
        for text in case.get("confirmed_atoms", []):
            if not any(
                node.get("text") == text and node.get("status") == "confirmed"
                for node in atoms
            ):
                errors.append(f"valid control was incorrectly blocked: {text}")
        if any(node.get("op") != "ATOM" for node in nodes):
            errors.append("control created a logical material group")
    else:
        raise ValueError("unknown expectation")
    if not graph.get("needs_human_review") or graph.get("coverage_status") != "partial":
        errors.append("global partial/manual-review boundary changed")
    return {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "source_checked": source["checked_references"],
        "source_invalid": source["invalid_references"],
    }


async def capture(case):
    registry = ProjectFileRegistry()
    project = f"numbering-public-{case['case_id']}"
    raw = case["input_text"].encode("utf-8")
    registered = registry.register(
        project_id=project,
        file_name=f"{case['case_id']}.txt",
        file_role="tender",
        content=raw,
    )
    file_id = registered.file.file_id
    context = {
        "document_id": file_id,
        "source_version": registry.file_version_token(file_id),
        "pages": case["input_text"].split("\f"),
    }
    runtime = AgentRuntime(
        build_default_registry(file_registry=registry),
        services={"file_registry": registry},
    )
    result = await runtime.run(
        SkillRequest.create(
            {
                "project_id": project,
                "file_ids": [file_id],
                "bidder_file_ids": [],
                "bidder_id": "",
                "bidder_name": "",
                "task": "分析招标文件",
            }
        )
    )
    intake, _ = _step(result, "tender-intake")
    decomposition, data = _step(result, "tender-decomposition")
    if not data or len(data.get("document_relations", [])) != 1:
        raise ValueError("Registry/Runtime did not return one actual graph")
    graph = data["document_relations"][0]
    checked = check_graph(case, graph, context)
    if intake not in {"success", "partial"} or decomposition not in {
        "success",
        "partial",
    }:
        checked["errors"].append("intake/decomposition execution failed")
        checked["status"] = "failed"
    return {
        "case_id": case["case_id"],
        "expectation": case["expectation"],
        "execution_state": "executed",
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        **checked,
        "actual_graph": graph,
        "source_context": context,
        "runtime": {
            "run_status": str(result.status),
            "intake_status": intake,
            "decomposition_status": decomposition,
        },
    }


def mutations(case, captured):
    original = captured["actual_graph"]
    group = next(n for n in original["condition_nodes"] if n["op"] == "AND")
    atom = next(n for n in original["condition_nodes"] if n["op"] == "ATOM")
    second = next(
        n
        for n in original["condition_nodes"]
        if n["op"] == "ATOM" and n["node_id"] != atom["node_id"]
    )
    kinds = (
        "OR_instead_of_AND",
        "missing_child",
        "duplicate_child",
        "normalized_decimal_label",
        "invented_middle_label",
        "wrong_leaf_evidence",
        "parent_self",
        "parent_other_leaf",
        "parent_missing_target",
        "parent_missing_evidence",
        "scope_missing_member",
        "scope_duplicate_member",
        "scope_extra_member",
        "scope_candidate",
        "operator_missing_evidence",
        "operator_candidate",
        "scope_borrowed_operator_evidence",
        "boundary_punctuation_only",
        "block_scope_mismatch",
        "block_operator_missing_evidence",
        "duplicate_node_id",
        "invalid_version",
        "invalid_offset",
    )
    output = []
    for kind in kinds:
        graph = deepcopy(original)
        changed_group = next(
            n for n in graph["condition_nodes"] if n["node_id"] == group["node_id"]
        )
        changed_atom = next(
            n for n in graph["condition_nodes"] if n["node_id"] == atom["node_id"]
        )
        scope = changed_group["scope_relation"]
        if kind == "OR_instead_of_AND":
            changed_group["op"] = "OR"
        elif kind == "missing_child":
            changed_group["children"].pop()
        elif kind == "duplicate_child":
            changed_group["children"].append(changed_group["children"][0])
        elif kind == "normalized_decimal_label":
            second_changed = next(
                n for n in graph["condition_nodes"] if n["node_id"] == second["node_id"]
            )
            second_changed["text"] = "编号1.1项"
        elif kind == "invented_middle_label":
            changed_atom["text"] = "编号1.95项"
        elif kind == "wrong_leaf_evidence":
            changed_atom["source_references"] = deepcopy(second["source_references"])
        elif kind.startswith("parent_"):
            parent = next(
                p
                for p in changed_atom["parent_relations"]
                if p.get("layer") == "semantic_parent"
            )
            if kind == "parent_self":
                parent["target_node_ids"] = [changed_atom["node_id"]]
            elif kind == "parent_other_leaf":
                parent["target_node_ids"] = [second["node_id"]]
            elif kind == "parent_missing_target":
                parent["target_node_ids"] = []
            else:
                parent["source_references"] = []
        elif kind == "scope_missing_member":
            scope["target_node_ids"].pop()
        elif kind == "scope_duplicate_member":
            scope["target_node_ids"].append(scope["target_node_ids"][0])
        elif kind == "scope_extra_member":
            scope["target_node_ids"].append(changed_group["node_id"])
        elif kind == "scope_candidate":
            scope["status"] = "candidate"
        elif kind == "operator_missing_evidence":
            changed_group["operator_relation"]["source_references"] = []
            changed_group["operator_source_references"] = []
        elif kind == "operator_candidate":
            changed_group["operator_relation"]["status"] = "candidate"
        elif kind == "scope_borrowed_operator_evidence":
            reference = deepcopy(
                next(
                    ref
                    for ref in scope["boundary_source_references"]
                    if ref["quote"] == case["input_text"]
                )
            )
            reference["char_start"] += reference["quote"].index("均须提交")
            reference["char_end"] = reference["char_start"] + len("均须提交")
            reference["quote"] = "均须提交"
            reference["locator"] = (
                f"p{reference['page']}:c"
                f"{reference['char_start']}-{reference['char_end']}"
            )
            scope["scope_source_references"] = [reference]
        elif kind == "boundary_punctuation_only":
            reference = deepcopy(
                next(
                    ref
                    for ref in scope["boundary_source_references"]
                    if ref["quote"] == case["input_text"]
                )
            )
            reference["char_start"] = reference["char_end"] - 1
            reference["quote"] = "。"
            reference["locator"] = (
                f"p{reference['page']}:c"
                f"{reference['char_start']}-{reference['char_end']}"
            )
            scope["boundary_source_references"] = [reference]
        elif kind == "block_scope_mismatch":
            graph["block_relations"][0]["scope_relations"][0]["target_node_ids"] = []
        elif kind == "block_operator_missing_evidence":
            block_scope = graph["block_relations"][0]["scope_relations"][0]
            block_scope["operator_relation"]["source_references"] = []
        elif kind == "duplicate_node_id":
            graph["condition_nodes"].append(deepcopy(changed_atom))
        elif kind in {"invalid_version", "invalid_offset"}:
            for value in objects(graph):
                if {"quote", "char_start", "char_end"} <= value.keys():
                    if kind == "invalid_version":
                        value["source_version"] = "wrong-version"
                    else:
                        value["char_end"] += 1
        checked = check_graph(case, graph, captured["source_context"])
        output.append(
            {
                "mutation": kind,
                "kind": "source" if kind.startswith("invalid_") else "semantic",
                "rejected": checked["status"] == "failed",
                **checked,
            }
        )
    return output


async def run(files):
    cases = []
    for path in files:
        payload = json.loads(path.read_bytes())
        if payload.get("schema") != "finite-material-numbering-cases-v1":
            raise ValueError("invalid fixture schema")
        cases.extend(payload["cases"])
    if len({case["case_id"] for case in cases}) != len(cases):
        raise ValueError("duplicate fixture IDs")
    results = []
    for case in cases:
        try:
            results.append(await capture(case))
        except Exception as exc:
            results.append(
                {
                    "case_id": case["case_id"],
                    "expectation": case["expectation"],
                    "execution_state": "failed",
                    "status": "failed",
                    "errors": [f"{type(exc).__name__}: {exc}"],
                }
            )
    positive = next(r for r in results if r["case_id"] == "P01-original-case12")
    changed = (
        mutations(
            next(c for c in cases if c["case_id"] == positive["case_id"]), positive
        )
        if positive["status"] == "passed"
        else []
    )
    return {
        "schema": "numbering-public-acceptance-v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "classification": "actual public Registry/Runtime output; not unseen",
        "product_root": str(PRODUCT_ROOT),
        "source_tree_sha256": legacy._source_tree_sha256(PRODUCT_ROOT),
        "acceptance_tool_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "input_fixtures": [
            {"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in files
        ],
        "cases": results,
        "graph_mutations": changed,
        "mutation_execution": "executed" if changed else "not_run_positive_unavailable",
        "summary": {
            "total": len(results),
            "passed": sum(r["status"] == "passed" for r in results),
            "executed": sum(r["execution_state"] == "executed" for r in results),
            "source_checked": sum(r.get("source_checked", 0) for r in results),
            "source_invalid": sum(r.get("source_invalid", 0) for r in results),
            **{
                f"{kind}_mutations_{suffix}": sum(
                    m["kind"] == kind
                    and (m["rejected"] if suffix == "rejected" else True)
                    for m in changed
                )
                for kind in ("semantic", "source")
                for suffix in ("rejected", "total")
            },
        },
        "unseen_evaluation": "not_run",
        "production_accepted": False,
    }


def mapping(path):
    report = json.loads(path.read_bytes())
    captured = next(c for c in report["cases"] if c["case_id"] == "case-12")
    oracle = json.loads(
        (
            PRODUCT_ROOT
            / "benchmarks/document_relations/reserved/v2/machine-oracle.json"
        ).read_bytes()
    )
    case = next(c for c in oracle["cases"] if c["case_id"] == "case-12")
    views = {}
    for version in ("1.0.3", "1.0.4"):
        evaluator = scorer.load_evaluator(version)
        normalized = evaluator._validate_graph_source_references(
            captured["actual_graph"], captured["source_context"]
        )["normalized_graph"]
        _, matched, candidates = evaluator._match_atoms(case, normalized)
        views[version] = {
            "mapping": matched,
            "candidates": candidates,
            "score": scorer.score_case(
                case,
                captured["actual_graph"],
                captured["source_context"],
                version=version,
            ),
        }
    return {
        "schema": "numbering-frozen-mapping-v1",
        "capture_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "source_tree_sha256": report["source_tree_sha256"],
        "case_id": "case-12",
        "views": views,
    }


def audit_export(export, tree):
    helper = (
        ROOT / "benchmarks/document_relations"
        "/copy-alternative-regression/20261014/verify-snapshot.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_numbering_baseline_verifier", helper
    )
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    expected = verifier.tree_blobs(tree)
    for path, blob in expected.items():
        if verifier.raw_blob(export / path) != blob:
            raise ValueError(f"raw Git export mismatch: {path}")
    return {
        "schema": "numbering-baseline-export-v1",
        "base_commit": tree,
        "git_files": len(expected),
        "all_export_blobs_match": True,
        "source_tree_sha256": legacy._source_tree_sha256(export),
        "files": [
            {"path": path, "git_blob": blob, "sha256": verifier.sha(export / path)}
            for path, blob in sorted(expected.items())
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product-root", type=Path, default=PRODUCT_ROOT)
    parser.add_argument("--case-file", type=Path, action="append")
    parser.add_argument("--mapping-report", type=Path)
    parser.add_argument("--audit-export", type=Path)
    parser.add_argument("--archive-tree")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must be new")
    if args.mapping_report:
        report = mapping(args.mapping_report)
    elif args.audit_export:
        if not args.archive_tree:
            parser.error("--audit-export requires --archive-tree")
        report = audit_export(args.audit_export.resolve(strict=True), args.archive_tree)
    else:
        report = asyncio.run(run(args.case_file or [REGRESSION / "cases.json"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    if "summary" not in report:
        print(json.dumps({k: report[k] for k in report if k not in {"files", "views"}}))
        return 0
    print(json.dumps(report["summary"]))
    return (
        0
        if (
            report["summary"]["passed"] == report["summary"]["total"]
            and all(m["rejected"] for m in report["graph_mutations"])
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
