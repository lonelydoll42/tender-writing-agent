"""Independently check actual finite financial contexts and evidence duties."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

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

REGRESSION = (
    ROOT / "benchmarks/document_relations/financial-context-regression/20261015"
)


def objects(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from objects(item)


def cites(record: dict, *clauses: str, field: str = "source_references") -> bool:
    quotes = [
        str(ref.get("quote", ""))
        for ref in record.get(field, [])
        if isinstance(ref, dict)
    ]
    return all(any(clause in quote for quote in quotes) for clause in clauses)


def check_graph(case: dict, graph: dict, context: dict) -> dict:
    errors = []
    source = legacy._validate_graph_source_references(graph, context)
    if (
        graph.get("document_id") != context["document_id"]
        or graph.get("source_version") != context["source_version"]
    ):
        errors.append("graph identity/version differs from Registry")
    if source["invalid_references"]:
        errors.append("invalid raw source references")
    nodes = graph.get("condition_nodes", [])
    threshold_blocks = {
        block["block_id"]
        for block in graph.get("block_relations", [])
        if cites(block.get("parent_relation", {}), case["threshold_text"])
    }
    scopes = [
        scope
        for block in graph.get("block_relations", [])
        if block.get("block_id") in threshold_blocks
        for scope in block.get("scope_relations", [])
        if scope.get("relation_type") == "financial_context_scope"
    ]
    refs = [
        ref
        for ref in graph.get("references", [])
        if ref.get("reference_text") == "营业收入"
        and ref.get("source_block_id") in threshold_blocks
    ]
    predicates = [
        node
        for node in nodes
        if set(node.get("source_block_ids", [])) & threshold_blocks
        and node.get("op") == "ATOM"
    ]
    parents = [
        parent
        for node in predicates
        for parent in node.get("parent_relations", [])
        if parent.get("layer") in {"contextual_parent", "attribute_parent"}
    ]
    if case["expectation"] == "confirmed_context":
        roles = {}
        for role, text in (
            ("anchor", case["anchor_text"]),
            ("field", case["field_text"]),
            ("predicate", case["threshold_text"]),
        ):
            matches = [
                node
                for node in nodes
                if node.get("op") == "ATOM" and node.get("text") == text
            ]
            if len(matches) != 1:
                errors.append(f"exact original {role} ATOM is missing or duplicated")
            else:
                roles[role] = matches[0]
        if len(roles) == 3:
            anchor, field, predicate = (
                roles["anchor"],
                roles["field"],
                roles["predicate"],
            )
            member_ids = {anchor["node_id"], field["node_id"], predicate["node_id"]}
            if len(member_ids) != 3 or len(
                {node.get("node_id") for node in nodes}
            ) != len(nodes):
                errors.append("condition node identities are not unique")
            blocks = set(anchor["source_block_ids"]) | set(
                predicate["source_block_ids"]
            )
            if len([n for n in nodes if n.get("op") == "ATOM"]) != 3 or any(
                n.get("status") != "confirmed" for n in roles.values()
            ):
                errors.append("three exact confirmed original atoms are not retained")
            logical = [n for n in nodes if n.get("op") in {"AND", "OR"}]
            if (
                len(logical) != 1
                or logical[0].get("op") != "AND"
                or set(logical[0].get("children", []))
                != {anchor["node_id"], field["node_id"]}
            ):
                errors.append("original AND(A1,A2) changed or threshold flattened")
            first = next(
                line for line in case["input_text"].splitlines() if line.strip()
            )
            clauses = (first, case["threshold_text"])
            if len(scopes) != 1:
                errors.append("one exact block financial context scope is required")
            else:
                scope = scopes[0]
                if (
                    not scope.get("relation_id")
                    or scope.get("status") != "confirmed"
                    or scope.get("scope_status", "confirmed") != "confirmed"
                    or scope.get("operator") in {"AND", "OR", "REQUIRED", None, ""}
                    or set(scope.get("target_node_ids", [])) != member_ids
                    or len(scope.get("target_node_ids", [])) != 3
                    or set(scope.get("member_node_ids", [])) != member_ids
                    or len(scope.get("member_node_ids", [])) != 3
                    or set(scope.get("target_block_ids", [])) != blocks
                    or len(scope.get("target_block_ids", [])) != 2
                    or len(blocks) != 2
                ):
                    errors.append(
                        "financial scope status, direct members or blocks differ"
                    )
                for name in (
                    "source_references",
                    "scope_source_references",
                    "boundary_source_references",
                ):
                    if not cites(scope, *clauses, field=name):
                        errors.append(
                            f"financial scope {name} lacks bilateral evidence"
                        )
                if predicate.get("scope_relation") != scope:
                    errors.append("node/block financial scope representations differ")
            if len(parents) != 1 or not any(
                parent.get("status") == "confirmed"
                and parent.get("layer") == "contextual_parent"
                and parent.get("basis")
                and parent.get("target_node_ids") == [field["node_id"]]
                and set(parent.get("target_block_ids", []))
                == set(field["source_block_ids"])
                and cites(parent, *clauses)
                for parent in parents
            ):
                errors.append(
                    "directed predicate-to-field parent/evidence is incorrect"
                )
            if len(refs) != 1 or not any(
                ref.get("status") == "confirmed"
                and ref.get("target_node_ids") == [field["node_id"]]
                and set(ref.get("target_block_ids", []))
                == set(field["source_block_ids"])
                and cites(ref, *clauses)
                for ref in refs
            ):
                errors.append("unique field reference/bilateral evidence is incorrect")
    else:
        if not scopes or any(
            scope.get("status") not in {"candidate", "unresolved"}
            or not scope.get("reason")
            for scope in scopes
        ):
            errors.append("explicit candidate/unresolved financial scope is missing")
        for node in predicates:
            scope = node.get("scope_relation", {})
            if (
                scope.get("relation_type") == "financial_context_scope"
                and scope.get("status") == "confirmed"
            ):
                errors.append("review predicate has a confirmed financial scope")
        if any(parent.get("status") == "confirmed" for parent in parents):
            errors.append("review predicate has a confirmed field parent")
        if any(ref.get("status") == "confirmed" for ref in refs):
            errors.append("review revenue reference is incorrectly confirmed")
        if not any(cites(scope, case["threshold_text"]) for scope in scopes):
            errors.append("review scope lost original threshold")
    if not graph.get("needs_human_review") or graph.get("coverage_status") != "partial":
        errors.append("global partial/manual-review boundary changed")
    return {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "source_checked": source["checked_references"],
        "source_invalid": source["invalid_references"],
    }


async def capture(case: dict) -> dict:
    registry = ProjectFileRegistry()
    project = f"financial-public-{case['case_id']}"
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
        raise ValueError("actual Runtime decomposition did not return one graph")
    graph = data["document_relations"][0]
    checked = check_graph(case, graph, context)
    if intake not in {"success", "partial"} or decomposition not in {
        "success",
        "partial",
    }:
        checked["errors"].append("intake/decomposition did not execute successfully")
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


def mutations(case: dict, captured: dict) -> list[dict]:
    graph = captured["actual_graph"]
    role = {
        name: next(n for n in graph["condition_nodes"] if n.get("text") == text)
        for name, text in (
            ("anchor", case["anchor_text"]),
            ("field", case["field_text"]),
            ("predicate", case["threshold_text"]),
        )
    }
    first = case["input_text"].splitlines()[0]
    kinds = (
        "parent_wrong_target",
        "parent_self_target",
        "parent_extra_target",
        "parent_missing_anchor_evidence",
        "reference_wrong_target",
        "reference_missing_anchor_evidence",
        "reference_candidate",
        "scope_missing_predicate",
        "scope_extra_member",
        "scope_duplicate_member",
        "scope_duplicate_blocks",
        "duplicate_node_id",
        "scope_flat_AND",
        "scope_missing_membership_evidence",
        "scope_missing_boundary_evidence",
        "scope_missing_source_evidence",
        "scope_candidate",
        "node_scope_mismatch",
        "missing_parent",
        "logical_flattening",
        "boundary_wrong_valid_clause",
        "reference_wrong_blocks",
        "parent_wrong_blocks",
        "invalid_version",
        "invalid_offset",
    )
    output = []
    for kind in kinds:
        changed = deepcopy(graph)
        for record in list(objects(changed)):
            scope = record.get("relation_type") == "financial_context_scope"
            parent = record.get("layer") == "contextual_parent"
            ref = (
                record.get("reference_kind") == "anaphora"
                and record.get("reference_text") == "营业收入"
            )
            if kind == "parent_wrong_target" and parent:
                record["target_node_ids"] = [role["anchor"]["node_id"]]
            if kind == "parent_self_target" and parent:
                record["target_node_ids"] = [role["predicate"]["node_id"]]
            if kind == "parent_extra_target" and parent:
                record["target_node_ids"].append(role["anchor"]["node_id"])
            if kind == "reference_wrong_target" and ref:
                record["target_node_ids"] = [role["anchor"]["node_id"]]
            if kind.endswith("missing_anchor_evidence") and (
                (kind.startswith("parent") and parent)
                or (kind.startswith("reference") and ref)
            ):
                record["source_references"] = [
                    item
                    for item in record["source_references"]
                    if first not in str(item.get("quote", ""))
                ]
            if kind == "reference_candidate" and ref:
                record["status"] = "candidate"
            if kind == "scope_missing_predicate" and scope:
                record["target_node_ids"] = [
                    role["anchor"]["node_id"],
                    role["field"]["node_id"],
                ]
                record["member_node_ids"] = list(record["target_node_ids"])
            if kind == "scope_extra_member" and scope:
                record["target_node_ids"] = [
                    *record["target_node_ids"],
                    "unrelated-condition",
                ]
            if kind == "scope_duplicate_member" and scope:
                record["target_node_ids"] = [
                    *record["target_node_ids"],
                    role["field"]["node_id"],
                ]
                record["member_node_ids"] = list(record["target_node_ids"])
            if kind == "scope_duplicate_blocks" and scope:
                record["target_block_ids"] = [
                    *record["target_block_ids"],
                    role["field"]["source_block_ids"][0],
                ]
            if (
                kind == "duplicate_node_id"
                and record.get("node_id") == (role["field"]["node_id"])
            ):
                record["node_id"] = role["anchor"]["node_id"]
            if kind == "scope_flat_AND" and scope:
                record["operator"] = "AND"
            for mutation, field in (
                ("scope_missing_membership_evidence", "scope_source_references"),
                ("scope_missing_boundary_evidence", "boundary_source_references"),
                ("scope_missing_source_evidence", "source_references"),
            ):
                if kind == mutation and scope:
                    record[field] = []
            if kind == "scope_candidate" and scope:
                record["status"] = "candidate"
            if (
                kind == "node_scope_mismatch"
                and record.get("node_id") == (role["predicate"]["node_id"])
            ):
                record["scope_relation"] = {
                    **record.get("scope_relation", {}),
                    "relation_id": "different-scope",
                }
            if kind == "missing_parent" and "parent_relations" in record:
                record["parent_relations"] = [
                    item
                    for item in record["parent_relations"]
                    if item.get("layer") != "contextual_parent"
                ]
            if kind == "logical_flattening" and record.get("op") == "AND":
                record["children"].append(role["predicate"]["node_id"])
            if kind == "boundary_wrong_valid_clause" and scope:
                record["boundary_source_references"] = [
                    item
                    for item in record["boundary_source_references"]
                    if first in str(item.get("quote", ""))
                ]
            if (kind == "reference_wrong_blocks" and ref) or (
                kind == "parent_wrong_blocks" and parent
            ):
                record["target_block_ids"] = role["predicate"]["source_block_ids"]
            if kind == "invalid_version" and "quote" in record:
                record["source_version"] = "wrong-version"
            if kind == "invalid_offset" and "char_start" in record:
                record["char_start"] += 1
        checked = check_graph(case, changed, captured["source_context"])
        output.append(
            {
                "mutation": kind,
                "kind": "source" if kind.startswith("invalid_") else "semantic",
                "rejected": checked["status"] == "failed",
                **checked,
            }
        )
    return output


def mapping_report(path: Path) -> dict:
    preserved = json.loads(path.read_bytes())
    captured = next(c for c in preserved["cases"] if c["case_id"] == "case-13")
    oracle = json.loads(
        (
            PRODUCT_ROOT
            / "benchmarks/document_relations/reserved/v2/machine-oracle.json"
        ).read_bytes()
    )
    case = next(c for c in oracle["cases"] if c["case_id"] == "case-13")
    result = {}
    for version in ("1.0.3", "1.0.4"):
        evaluator = scorer.load_evaluator(version)
        normalized = evaluator._validate_graph_source_references(
            captured["actual_graph"], captured["source_context"]
        )["normalized_graph"]
        _, mapping, candidates = evaluator._match_atoms(case, normalized)
        nodes = {n["node_id"]: n for n in normalized["condition_nodes"]}
        result[version] = {
            "mapping": {
                key: {"node_id": value, "text": nodes[value]["text"]}
                for key, value in mapping.items()
            },
            "candidates": candidates,
            "score": scorer.score_case(
                case,
                captured["actual_graph"],
                captured["source_context"],
                version=version,
            ),
        }
    return {
        "schema": "financial-context-frozen-mapping-v1",
        "capture_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "source_tree_sha256": preserved["source_tree_sha256"],
        "case_id": "case-13",
        "frozen_scorers_unchanged": True,
        "views": result,
    }


async def run(files: list[Path]) -> dict:
    cases = []
    for path in files:
        payload = json.loads(path.read_bytes())
        if payload.get("schema") != "finite-financial-context-cases-v1":
            raise ValueError("invalid financial context fixture schema")
        cases.extend(payload["cases"])
    if len({c["case_id"] for c in cases}) != len(cases):
        raise ValueError("duplicate fixture case IDs")
    results = []
    for case in cases:
        if case["expectation"] not in {"confirmed_context", "review_context"}:
            raise ValueError("unknown fixture expectation")
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
    positive = next((r for r in results if r["case_id"] == "F01-original-case13"), None)
    positive_case = next(
        (c for c in cases if c["case_id"] == "F01-original-case13"), None
    )
    changed = (
        mutations(positive_case, positive)
        if (positive and positive["status"] == "passed")
        else []
    )
    return {
        "schema": "financial-context-public-acceptance-v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "classification": "actual public Registry/Runtime checks; not unseen",
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product-root", type=Path, default=PRODUCT_ROOT)
    parser.add_argument("--case-file", type=Path, action="append")
    parser.add_argument("--mapping-report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must use a new path")
    report = (
        mapping_report(args.mapping_report)
        if args.mapping_report
        else asyncio.run(run(args.case_file or [REGRESSION / "cases.json"]))
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    if "summary" not in report:
        print(
            json.dumps({"case_id": report["case_id"], "views": list(report["views"])})
        )
        return 0
    print(json.dumps(report["summary"]))
    good = report["summary"]["total"] == report["summary"]["passed"] and all(
        m["rejected"] for m in report["graph_mutations"]
    )
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
