"""Independent reviewer capture/mutation checks for the frozen evidence contract."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from scripts import run_document_relations_rescore as old  # noqa: E402


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def product_ref(context, source):
    return {
        **deepcopy(source),
        "document_id": context["document_id"],
        "source_version": context["source_version"],
    }


def whole_line(context, source):
    page = context["pages"][source["page"] - 1]
    start = page.rfind("\n", 0, source["char_start"]) + 1
    end = page.find("\n", source["char_end"])
    if end < 0:
        end = len(page)
    return product_ref(
        context,
        {
            "page": source["page"],
            "line": source["line"],
            "quote": page[start:end],
            "char_start": start,
            "char_end": end,
        },
    )


def forge(entry, context):
    """Deliberately asserted trees used only as grader negative counterexamples."""
    contracts = entry["evidence_contract"]["groups"]
    nodes = []
    for atom in entry["case"]["conditions"]:
        nodes.append(
            {
                "node_id": atom["id"],
                "op": "ATOM",
                "status": "confirmed",
                "children": [],
                "text": atom["text"],
                "source_references": [product_ref(context, r) for r in atom["source"]],
            }
        )
    for group_id, contract in contracts.items():
        scope_sources = [product_ref(context, r) for r in contract["scope_sources"]]
        member_sources = [
            product_ref(context, r)
            for rows in contract["member_sources"].values()
            for r in rows
        ]
        boundary = [product_ref(context, r) for r in contract["termination_sources"]]
        operators = [product_ref(context, r) for r in contract["operator_sources"]]
        parent = []
        if contract["inheritance"]:
            parent.append(
                {
                    "status": "confirmed",
                    "layer": "semantic_parent",
                    "basis": "explicit per-group contract",
                    "target_node_ids": ["S0"],
                    "source_references": [
                        product_ref(context, r)
                        for r in contract["inheritance"]["parent_link_sources"]
                    ],
                }
            )
        nodes.append(
            {
                "node_id": group_id,
                "op": contract["operator"],
                "status": "confirmed",
                "text": f"synthetic-{group_id}",
                "children": contract["members"],
                "source_references": [
                    *operators,
                    *scope_sources,
                    *member_sources,
                    *boundary,
                ],
                "operator_relation": {
                    "status": "confirmed",
                    "source_references": operators,
                },
                "scope_relation": {
                    "status": "confirmed",
                    "target_node_ids": contract["members"],
                    "scope_source_references": scope_sources,
                    "member_source_references": member_sources,
                    "source_references": [*scope_sources, *member_sources],
                    "boundary_source_references": boundary,
                },
                "parent_relations": parent,
            }
        )
    root = next(node for node in nodes if node["node_id"] == "S0")
    for contract in contracts.values():
        if contract["inheritance"]:
            root["source_references"].extend(
                product_ref(context, source)
                for source in contract["inheritance"]["applicability_sources"]
            )
    return {
        "schema": "document-relations-v1",
        "document_id": context["document_id"],
        "source_version": context["source_version"],
        "condition_nodes": nodes,
        "block_relations": [],
        "references": [],
        "roots": ["S0"],
    }


def bind(entry, graph):
    rows = graph["condition_nodes"]
    result = {}
    for atom in entry["case"]["conditions"]:
        candidates = [
            row["node_id"]
            for row in rows
            if row["op"] == "ATOM" and row["text"].strip() == atom["text"]
        ]
        if len(candidates) != 1:
            raise ValueError(f"independent exact atom binding failed: {atom['id']}")
        result[atom["id"]] = candidates[0]
    pending = list(entry["case"]["groups"])
    while pending:
        progress = False
        for group in pending[:]:
            if not all(member in result for member in group["members"]):
                continue
            targets = {result[member] for member in group["members"]}
            candidates = [
                row["node_id"]
                for row in rows
                if row["op"] == group["operator"]
                and set(row["children"]) == targets
                and len(row["children"]) == len(targets)
            ]
            if len(candidates) != 1:
                raise ValueError(
                    f"independent direct group binding failed: {group['id']}"
                )
            result[group["id"]] = candidates[0]
            pending.remove(group)
            progress = True
        if not progress:
            raise ValueError("unresolved independent group binding")
    return result


def mutate(entry, raw_graph, context, variant):
    graph = deepcopy(raw_graph)
    ids = bind(entry, graph)
    nodes = {row["node_id"]: row for row in graph["condition_nodes"]}
    first, second, root = [nodes[ids[group]] for group in ("S1", "S2", "S0")]
    scope, operator = first["scope_relation"], first["operator_relation"]
    contracts = entry["evidence_contract"]["groups"]
    parent = first.get("parent_relations", [])
    if variant == "unchanged":
        pass
    elif variant in {"boundary_whole_own_line", "boundary_only_final_punctuation"}:
        terminal = contracts["S1"]["termination_sources"][0]
        scope["boundary_source_references"] = [
            whole_line(context, terminal)
            if variant == "boundary_whole_own_line"
            else product_ref(context, terminal)
        ]
    elif variant == "parent_reference_superset_inside_scope":
        if parent:
            parent[0]["source_references"] = [
                whole_line(context, contracts["S0"]["operator_sources"][0]),
                whole_line(context, contracts["S1"]["scope_sources"][0]),
            ]
    elif variant == "operator_from_adjacent_group":
        operator["source_references"] = [
            product_ref(context, contracts["S2"]["scope_sources"][0])
        ]
    elif variant == "scope_from_adjacent_group":
        for key in (
            "scope_source_references",
            "member_source_references",
            "source_references",
        ):
            scope[key] = deepcopy(second["scope_relation"][key])
    elif variant == "missing_one_member_source":
        target = contracts["S1"]["member_sources"][contracts["S1"]["members"][-1]][0]
        for key in (
            "scope_source_references",
            "member_source_references",
            "source_references",
        ):
            scope[key] = [
                r
                for r in scope[key]
                if not (
                    r["page"] == target["page"]
                    and r["char_start"] <= target["char_start"]
                    and r["char_end"] >= target["char_end"]
                )
            ]
    elif variant == "scope_not_confirmed":
        scope["status"] = "candidate"
    elif variant == "leaf_targets_for_root":
        root["scope_relation"]["target_node_ids"] = [
            ids[atom["id"]] for atom in entry["case"]["conditions"]
        ]
    elif variant in {"boundary_from_adjacent_group", "boundary_wrong_occurrence"}:
        scope["boundary_source_references"] = [
            product_ref(context, contracts["S2"]["termination_sources"][0])
        ]
    elif variant == "boundary_operator_only":
        scope["boundary_source_references"] = deepcopy(operator["source_references"])
    elif variant == "boundary_semicolon_only":
        region = contracts["S1"]["region"]
        start = context["pages"][0].index(
            "；", region["char_start"], region["char_end"]
        )
        scope["boundary_source_references"] = [
            product_ref(
                context,
                {
                    "page": 1,
                    "line": contracts["S1"]["scope_sources"][0]["line"],
                    "quote": "；",
                    "char_start": start,
                    "char_end": start + 1,
                },
            )
        ]
    elif variant == "boundary_missing":
        scope["boundary_source_references"] = []
    elif variant == "boundary_cross_paragraph":
        scope["boundary_source_references"].append(
            whole_line(context, contracts["S2"]["scope_sources"][0])
        )
    elif variant == "parent_not_confirmed":
        root["status"] = "candidate"
    elif variant == "parent_scope_not_confirmed":
        root["scope_relation"]["status"] = "candidate"
    elif variant == "parent_link_missing":
        first["parent_relations"] = []
    elif variant == "structural_parent_only":
        for relation in parent:
            relation["layer"] = "structural_list"
    elif variant == "parent_link_wrong_group":
        for relation in parent:
            relation["target_node_ids"] = [second["node_id"]]
    elif variant == "parent_link_wrong_source":
        for relation in parent:
            relation["source_references"] = [
                product_ref(context, contracts["S2"]["scope_sources"][0])
            ]
    elif variant == "additional_conflicting_parent":
        parent.append(
            {
                "status": "confirmed",
                "layer": "semantic_parent",
                "basis": "conflicting parent",
                "target_node_ids": [second["node_id"]],
                "source_references": deepcopy(second["source_references"]),
            }
        )
    elif variant == "forged_raw_valid_flag":
        reference = operator["source_references"][0]
        reference["char_start"] += 1
        reference["char_end"] += 1
        reference["_raw_coordinate_valid"] = True
    elif variant == "wrong_source_version":
        operator["source_references"][0]["source_version"] += ":stale"
    else:
        raise ValueError(variant)
    return graph


async def capture(payload, cases_path):
    legacy = old.load_evaluator("1.0.3")
    result = []
    for entry in payload["cases"]:
        path = cases_path.parent / entry["input"]
        assert (
            hashlib.sha256(path.read_bytes()).hexdigest() == entry["raw_input_sha256"]
        )
        runtime = await legacy._run_input(path, entry["case_id"])
        result.append({"case_id": entry["case_id"], "runtime": runtime})
    return {
        "schema": "boundary-evidence-product-capture-v1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "source_commit": "b166d3d78905445f754991a0e82b6b5a94f88501",
        "source_tree_sha256": (
            "da6ccd4982e25f3e245070c179f37be03bb47dff2f0d680a54d355cfbc1cd1b0"
        ),
        "cases_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "cases": result,
    }


def check(payload, captures, cases_path):
    if captures["cases_sha256"] != hashlib.sha256(cases_path.read_bytes()).hexdigest():
        raise ValueError("frozen capture/annotation identity mismatch")
    spec = importlib.util.spec_from_file_location(
        "boundary_new", ROOT / "scripts/run_document_relations_boundary_rescore.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    runs = {row["case_id"]: row["runtime"] for row in captures["cases"]}
    outcomes, execution, not_applicable = [], [], []
    parent_variants = {
        "parent_not_confirmed",
        "parent_scope_not_confirmed",
        "parent_link_missing",
        "structural_parent_only",
        "parent_link_wrong_group",
        "parent_link_wrong_source",
        "additional_conflicting_parent",
    }
    for entry in payload["cases"]:
        runtime = runs[entry["case_id"]]
        execution.append(
            {"case_id": entry["case_id"], "execution_state": runtime["execution_state"]}
        )
        if runtime["execution_state"] != "executed":
            continue
        graph, context = runtime["graph"], runtime["source_context"]
        if entry["expected_product_review"]:
            groups = [
                node for node in graph["condition_nodes"] if node["op"] in {"AND", "OR"}
            ]
            # Conflict/unknown inheritance cannot leave a complete outer AND confirmed.
            root_cue = entry["evidence_contract"]["groups"]["S0"]["operator_sources"][0]
            confirmed_outer = [
                node
                for node in groups
                if node["op"] == "AND"
                and node["status"] == "confirmed"
                and len(node["children"]) == 2
                and any(
                    reference["char_start"] <= root_cue["char_start"]
                    and reference["char_end"] >= root_cue["char_end"]
                    for reference in node["operator_relation"]["source_references"]
                )
            ]
            outcomes.append(
                {
                    "case_id": entry["case_id"],
                    "variant": "actual_product_review",
                    "category": "product_review",
                    "passed": not confirmed_outer,
                    "confirmed_outer_ids": [
                        node["node_id"] for node in confirmed_outer
                    ],
                }
            )
            variants = [
                ("forged_confirmed_from_review_source", forge(entry, context), False)
            ]
            synthetic_valid = False
        else:
            scored = module.score_case(
                entry["case"],
                graph,
                context,
                evidence_contract=entry["evidence_contract"],
            )
            outcomes.append(
                {
                    "case_id": entry["case_id"],
                    "variant": "actual_product_positive",
                    "category": "product_positive",
                    "passed": scored["status"] == "passed",
                    "errors": scored.get("errors", []),
                }
            )
            synthetic_valid = False
            try:
                bind(entry, graph)
            except ValueError:
                graph = forge(entry, context)
                synthetic_valid = True
            variants = [
                (name, mutate(entry, graph, context, name), True)
                for name in payload["positive_mutations"]
            ]
            for name in payload["negative_mutations"]:
                if (
                    name in parent_variants
                    and not entry["evidence_contract"]["groups"]["S1"]["inheritance"]
                ):
                    not_applicable.append(
                        {
                            "case_id": entry["case_id"],
                            "variant": name,
                            "reason": "no inherited operator in this local positive",
                        }
                    )
                    continue
                variants.append((name, mutate(entry, graph, context, name), False))
        for name, changed, expected in variants:
            before = digest(changed)
            scored = module.score_case(
                entry["case"],
                changed,
                context,
                evidence_contract=entry["evidence_contract"],
            )
            actual = scored["status"] == "passed"
            outcomes.append(
                {
                    "case_id": entry["case_id"],
                    "variant": name,
                    "category": (
                        "valid_synthetic"
                        if expected and synthetic_valid
                        else "valid"
                        if expected
                        else "invalid_confirmed"
                    ),
                    "passed": actual == expected and digest(changed) == before,
                    "expected_accept": expected,
                    "actual_accept": actual,
                    "raw_input_preserved": digest(changed) == before,
                    "errors": scored.get("errors", []),
                    "evidence_audit": scored.get("evidence_audit"),
                }
            )
    counts = {}
    for category in (
        "valid",
        "valid_synthetic",
        "invalid_confirmed",
        "product_review",
        "product_positive",
    ):
        selected = [row for row in outcomes if row["category"] == category]
        counts[category] = {
            "passed": sum(row["passed"] for row in selected),
            "total": len(selected),
        }
    return {
        "schema": "boundary-evidence-independent-check-v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "cases_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "capture_canonical_sha256": digest(captures),
        "grader_sha256": hashlib.sha256(
            (ROOT / "scripts/run_document_relations_boundary_rescore.py").read_bytes()
        ).hexdigest(),
        "business_materials": "not_run",
        "policy_only_isolation": payload["policy_only_isolation"],
        "summary": {
            **counts,
            "false_block": sum(
                row["category"] in {"valid", "valid_synthetic"} and not row["passed"]
                for row in outcomes
            ),
            "false_accept": sum(
                row["category"] == "invalid_confirmed" and row["actual_accept"]
                for row in outcomes
            ),
            "executed_files": sum(
                row["execution_state"] == "executed" for row in execution
            ),
            "execution_failed_files": sum(
                row["execution_state"] == "failed" for row in execution
            ),
            "not_run_files": sum(
                row["execution_state"] == "not_run" for row in execution
            ),
            "checks_failed": sum(not row["passed"] for row in outcomes),
            "contract_checks_failed": sum(
                not row["passed"]
                for row in outcomes
                if row["category"] in {"valid", "valid_synthetic", "invalid_confirmed"}
            ),
        },
        "execution": execution,
        "not_applicable": not_applicable,
        "checks": outcomes,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--captures", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("refusing to overwrite reviewer report")
    payload = json.loads(args.cases.read_bytes())
    if args.capture:
        result = asyncio.run(capture(payload, args.cases))
    else:
        result = check(payload, json.loads(args.captures.read_bytes()), args.cases)
    save(args.output, result)
    if not args.capture and result["summary"]["checks_failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
