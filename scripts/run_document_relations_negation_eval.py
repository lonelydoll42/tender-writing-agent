"""Run the public, manually authored document-relation negation regressions."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from qiaowenshu_agent.core.contracts import SkillRequest  # noqa: E402
from qiaowenshu_agent.core.files import ProjectFileRegistry  # noqa: E402
from qiaowenshu_agent.core.runtime import AgentRuntime  # noqa: E402
from qiaowenshu_agent.skills import build_default_registry  # noqa: E402
from scripts.run_document_relations_eval import (  # noqa: E402
    _source_tree_sha256,
    _validate_graph_source_references,
)


MATERIALS = ("营业执照", "审计报告")
PLACEMENTS = ("prefix", "inline", "postfix")
NEGATION_CUES = (
    ("not-needed", "不需要"),
    ("not-required", "不要求"),
    ("not-necessary", "不需"),
    ("without-need", "无需"),
    ("without-requirement", "无须"),
    ("not-necessary-must", "不必"),
    ("must-not", "不得"),
    ("not-need-short", "不须"),
)
REPORT_SCHEMA = "document-relations-negation-eval-v1"
REVIEW_STATUSES = {"candidate", "unresolved"}


def _negative_text(placement: str, cue: str) -> str:
    leaves = "（1）营业执照。\n（2）审计报告。"
    if placement == "prefix":
        return f"{cue}同时提交以下两项材料：\n{leaves}"
    if placement == "inline":
        return f"以下两项材料{cue}同时提交：（1）营业执照；（2）审计报告。"
    return f"{leaves}\n上述两项材料{cue}同时提交。"


def _positive_text(placement: str, operator: str) -> str:
    leaves = "（1）营业执照。\n（2）审计报告。"
    phrases = {
        "AND": (
            "须同时提交以下两项材料：",
            "以下两项材料须同时提交：",
            "上述两项材料须同时提交。",
        ),
        "OR": (
            "请从以下两项材料中任选一项提交：",
            "以下两项材料任选一项提交：",
            "上述两项材料任选其一提交。",
        ),
    }
    prefix, inline, postfix = phrases[operator]
    if placement == "prefix":
        return f"{prefix}\n{leaves}"
    if placement == "inline":
        return f"{inline}（1）营业执照；（2）审计报告。"
    return f"{leaves}\n{postfix}"


def _fixed_cases() -> tuple[dict[str, Any], ...]:
    cases = []
    for cue_id, cue in NEGATION_CUES:
        for placement in PLACEMENTS:
            cases.append(
                {
                    "case_id": f"negative-{placement}-{cue_id}",
                    "polarity": "negative",
                    "placement": placement,
                    "input_text": _negative_text(placement, cue),
                    "expected": {
                        "polarity": "negative",
                        "materials": list(MATERIALS),
                        "forbidden_confirmed_operators": ["AND", "OR"],
                        "negation_quote_contains": cue,
                        "operator_quote_contains": "同时提交",
                    },
                }
            )
    for operator in ("AND", "OR"):
        for placement in PLACEMENTS:
            cue = "同时提交" if operator == "AND" else "任选"
            cases.append(
                {
                    "case_id": f"positive-{placement}-{operator.lower()}",
                    "polarity": "positive",
                    "placement": placement,
                    "input_text": _positive_text(placement, operator),
                    "expected": {
                        "polarity": "positive",
                        "materials": list(MATERIALS),
                        "operator": operator,
                        "operator_quote_contains": cue,
                        "scope_quote_contains": "两项",
                    },
                }
            )
    return tuple(cases)


FIXED_CASES = _fixed_cases()


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _status(value: Any) -> str:
    return str(value or "").strip().lower()


def _references(value: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        item
        for item in _list(value.get("source_references"))
        if isinstance(item, Mapping)
    ]


def _quotes(references: list[Mapping[str, Any]]) -> list[str]:
    return [
        str(reference["quote"])
        for reference in references
        if isinstance(reference.get("quote"), str)
    ]


def _condition_nodes(graph: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        node
        for node in _list(graph.get("condition_nodes"))
        if isinstance(node, Mapping)
    ]


def _leaf_nodes(
    graph: Mapping[str, Any], materials: list[str]
) -> dict[str, list[Mapping[str, Any]]]:
    leaves = {material: [] for material in materials}
    for node in _condition_nodes(graph):
        if str(node.get("op", "")).upper() != "ATOM":
            continue
        text = str(node.get("text") or "")
        for material in materials:
            if material in text:
                leaves[material].append(node)
    return leaves


def _node_id(node: Mapping[str, Any]) -> str:
    return str(node.get("node_id") or "")


def _ids(value: Any) -> set[str]:
    return {str(item) for item in _list(value) if item is not None}


def _group_channels(graph: Mapping[str, Any]) -> list[dict[str, Any]]:
    groups = []
    for node in _condition_nodes(graph):
        operator = str(node.get("op") or "").upper()
        if operator not in {"AND", "OR"}:
            continue
        operator_relation = node.get("operator_relation")
        scope_relation = node.get("scope_relation")
        operator_relation = (
            operator_relation if isinstance(operator_relation, Mapping) else {}
        )
        scope_relation = (
            scope_relation if isinstance(scope_relation, Mapping) else {}
        )
        groups.append(
            {
                "operator": operator,
                "status": _status(node.get("status")),
                "target_node_ids": _ids(node.get("children")),
                "operator_status": _status(operator_relation.get("status")),
                "operator_quotes": _quotes(_references(operator_relation)),
                "scope_status": _status(scope_relation.get("status")),
                "scope_target_node_ids": _ids(
                    scope_relation.get("target_node_ids")
                ),
                "scope_quotes": _quotes(_references(scope_relation)),
            }
        )
    return groups


def _block_scope_channels(graph: Mapping[str, Any]) -> list[dict[str, Any]]:
    channels = []
    for block in _list(graph.get("block_relations")):
        if not isinstance(block, Mapping):
            continue
        for scope in _list(block.get("scope_relations")):
            if not isinstance(scope, Mapping):
                continue
            operator_relation = scope.get("operator_relation")
            operator_relation = (
                operator_relation if isinstance(operator_relation, Mapping) else {}
            )
            channels.append(
                {
                    "block_id": str(block.get("block_id") or ""),
                    "operator": str(scope.get("operator") or "").upper(),
                    "scope_relation_status": _status(scope.get("status")),
                    "scope_status": _status(scope.get("scope_status")),
                    "scope_target_node_ids": _ids(scope.get("target_node_ids")),
                    "scope_target_block_ids": _ids(scope.get("target_block_ids")),
                    "scope_quotes": _quotes(_references(scope)),
                    "operator_status": _status(operator_relation.get("status")),
                    "operator_quotes": _quotes(_references(operator_relation)),
                }
            )
    return channels


def _pair_block_ids(
    leaves: Mapping[str, list[Mapping[str, Any]]], materials: list[str]
) -> set[str]:
    return {
        str(block_id)
        for material in materials
        for node in leaves[material]
        for block_id in _list(node.get("source_block_ids"))
    }


def _targets_pair(
    node_ids: set[str],
    block_ids: set[str],
    pair_ids: set[str],
    pair_blocks: set[str],
) -> bool:
    return bool(pair_ids and pair_ids <= node_ids) or bool(
        pair_blocks and pair_blocks <= block_ids
    )


def _score_semantics(
    case: Mapping[str, Any], graph: Mapping[str, Any]
) -> dict[str, Any]:
    expected = case["expected"]
    materials = list(expected["materials"])
    leaves = _leaf_nodes(graph, materials)
    groups = _group_channels(graph)
    block_channels = _block_scope_channels(graph)
    leaf_ids = {
        material: [_node_id(node) for node in nodes if _node_id(node)]
        for material, nodes in leaves.items()
    }
    pair_ids = {node_id for ids in leaf_ids.values() for node_id in ids}
    pair_blocks = _pair_block_ids(leaves, materials)
    errors: list[str] = []

    for material in materials:
        if not leaves[material]:
            errors.append(f"missing material leaf: {material}")

    if expected["polarity"] == "negative":
        if any(len(leaves[material]) != 1 for material in materials):
            errors.append("negative case does not retain exactly two material leaves")
        cue = str(expected["negation_quote_contains"])
        operator_cue = str(expected["operator_quote_contains"])
        matching_groups = [
            group
            for group in groups
            if group["operator"] in expected["forbidden_confirmed_operators"]
        ]
        group_confirmed = [
            group
            for group in matching_groups
            if "confirmed"
            in {
                group["status"],
                group["operator_status"],
                group["scope_status"],
            }
        ]
        if group_confirmed:
            errors.append("an AND/OR group/operator/scope channel is confirmed")

        directive_channels = [
            channel
            for channel in block_channels
            if any(
                cue in quote
                and operator_cue in quote
                and ("两项" in quote or "上述" in quote)
                for quote in channel["scope_quotes"]
            )
        ]
        directive_quotes = [
            quote
            for channel in directive_channels
            for quote in channel["scope_quotes"]
            if cue in quote
            and operator_cue in quote
            and ("两项" in quote or "上述" in quote)
        ]
        review_directives = [
            channel
            for channel in directive_channels
            if channel["scope_relation_status"] in REVIEW_STATUSES
            and channel["scope_status"] in REVIEW_STATUSES
            and channel["operator_status"] in REVIEW_STATUSES
            and cue in channel["operator_quotes"]
        ]
        if not directive_quotes:
            errors.append("no block scope source retains the negated instruction")
        if not review_directives:
            errors.append(
                "no candidate/unresolved block scope and nested NOT operator "
                "retain the negation source"
            )
        if any(
            channel["operator_status"] == "confirmed"
            for channel in block_channels
        ):
            errors.append("a block operator channel is confirmed")
        if any(
            "confirmed"
            in {
                channel["scope_relation_status"],
                channel["scope_status"],
                channel["operator_status"],
            }
            for channel in directive_channels
        ):
            errors.append("negation directive has a confirmed scope/operator channel")

        evidence = {
            "material_leaf_ids": leaf_ids,
            "matching_group_count": len(matching_groups),
            "confirmed_group_count": len(group_confirmed),
            "candidate_directive_count": len(review_directives),
            "negation_source_quotes": directive_quotes,
            "operator_source_quotes": [
                quote
                for channel in directive_channels
                for quote in channel["operator_quotes"]
                if cue in quote
            ],
        }
    else:
        target_ids = {
            ids[0] for ids in leaf_ids.values() if len(ids) == 1 and ids[0]
        }
        confirmed_leaf_ids = {
            _node_id(node)
            for material in materials
            for node in leaves[material]
            if _status(node.get("status")) == "confirmed"
        }
        if (
            len(target_ids) != 2
            or len(pair_ids) != 2
            or confirmed_leaf_ids != target_ids
        ):
            errors.append(
                "positive case requires exactly two confirmed material leaves"
            )

        operator = str(expected["operator"])
        matching_groups = [
            group
            for group in groups
            if group["operator"] in {"AND", "OR"}
            and (
                group["target_node_ids"] == target_ids
                or group["scope_target_node_ids"] == target_ids
            )
        ]
        valid_groups = [
            group
            for group in matching_groups
            if group["operator"] == operator
            and group["target_node_ids"] == target_ids
            and group["status"] == "confirmed"
            and group["operator_status"] == "confirmed"
            and group["scope_status"] == "confirmed"
            and group["scope_target_node_ids"] == target_ids
        ]
        if len(matching_groups) != 1 or len(valid_groups) != 1:
            errors.append(
                "positive case requires exactly one confirmed two-leaf group "
                "with confirmed operator and scope"
            )
        operator_quotes = [
            quote
            for group in matching_groups
            for quote in group["operator_quotes"]
            if expected["operator_quote_contains"] in quote
        ]
        scope_quotes = [
            quote
            for group in valid_groups
            for quote in group["scope_quotes"]
            if expected["scope_quote_contains"] in quote
        ]
        if not operator_quotes:
            errors.append("positive group operator source cue is missing")
        if not scope_quotes:
            errors.append("positive group scope source evidence is missing")

        relevant_blocks = [
            channel
            for channel in block_channels
            if _targets_pair(
                channel["scope_target_node_ids"],
                channel["scope_target_block_ids"],
                target_ids,
                pair_blocks,
            )
        ]
        if not relevant_blocks:
            errors.append("positive case has no corresponding block scope relation")
        for channel in relevant_blocks:
            if (
                channel["operator"] != operator
                or channel["scope_target_node_ids"] != target_ids
                or channel["scope_relation_status"] != "confirmed"
                or channel["scope_status"] != "confirmed"
                or channel["operator_status"] != "confirmed"
                or not any(
                    expected["operator_quote_contains"] in quote
                    for quote in channel["operator_quotes"]
                )
            ):
                errors.append("positive block scope/operator channel is incomplete")
                break

        evidence = {
            "material_leaf_ids": leaf_ids,
            "matching_group_count": len(matching_groups),
            "confirmed_group_count": len(valid_groups),
            "relevant_block_scope_count": len(relevant_blocks),
            "operator_source_quotes": operator_quotes,
            "scope_source_quotes": scope_quotes,
        }

    return {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "evidence": evidence,
    }


def _source_proof(
    graph: Mapping[str, Any],
    source_context: Mapping[str, Any],
    registered_checksum: str,
    intake_structure: Mapping[str, Any] | None,
    analysis: Mapping[str, Any],
) -> dict[str, Any]:
    document_id = str(source_context["document_id"])
    source_version = str(source_context["source_version"])
    intake_structure = intake_structure or {}
    reference_check = _validate_graph_source_references(graph, source_context)
    identity = {
        "registry_document_id": document_id,
        "registry_source_version": source_version,
        "registered_input_sha256": registered_checksum,
        "raw_input_sha256": source_context["raw_input_sha256"],
        "raw_checksum_matches": (
            registered_checksum == source_context["raw_input_sha256"]
        ),
        "intake_identity_matches": (
            intake_structure.get("document_id") == document_id
            and intake_structure.get("source_version") == source_version
        ),
        "graph_identity_matches": graph.get("document_id") == document_id,
        "graph_version_matches": graph.get("source_version") == source_version,
        "graph_source_identity_status": graph.get("source_identity_status"),
        "analysis_source_identity_status": analysis.get("source_identity_status"),
        "analysis_source_reference_status": analysis.get("source_reference_status"),
    }
    references = {
        "checked": int(reference_check["checked_references"]),
        "denominator": int(reference_check["checked_references"]),
        "invalid": int(reference_check["invalid_references"]),
        "raw_offsets_checked": int(reference_check["raw_offsets_checked"]),
        "failures": reference_check["failures"],
    }
    checks = (
        identity["raw_checksum_matches"],
        identity["intake_identity_matches"],
        identity["graph_identity_matches"],
        identity["graph_version_matches"],
        identity["graph_source_identity_status"] == "registry_verified",
        identity["analysis_source_identity_status"] == "registry_verified",
        identity["analysis_source_reference_status"] == "verified",
        graph.get("schema_version") == "document-relations-v1",
        references["checked"] > 0,
        references["invalid"] == 0,
    )
    return {
        "status": "passed" if all(checks) else "failed",
        "identity": identity,
        "references": references,
    }


def _step(run_result: Any, name: str) -> tuple[str, Mapping[str, Any] | None]:
    for step in getattr(run_result, "steps", []) or []:
        if str(getattr(step, "skill_name", "")) == name:
            result = getattr(step, "result", None)
            return (
                str(getattr(result, "status", "not_run")).lower(),
                _mapping(getattr(result, "data", None)),
            )
    return "not_run", None


def _case_record(case: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "polarity": case["polarity"],
        "placement": case["placement"],
        "input": case["input_text"],
        "expected": deepcopy(case["expected"]),
        "execution_state": "not_run",
        "status": "not_run",
        "runtime": {},
        "actual_graph": None,
        "relation_analysis": None,
        "source_context": None,
        "source_verification": {
            "status": "not_run",
            "references": {
                "checked": 0,
                "denominator": 0,
                "invalid": 0,
                "raw_offsets_checked": 0,
                "failures": [],
            },
        },
        "semantic_evidence": {},
        "errors": [],
    }


async def execute_case(case: Mapping[str, Any]) -> dict[str, Any]:
    record = _case_record(case)
    input_text = str(case["input_text"])
    content = input_text.encode("utf-8")
    project_id = f"document-relations-negation-{case['case_id']}"
    registry = ProjectFileRegistry()
    registration = registry.register(
        project_id=project_id,
        file_name=f"{case['case_id']}.txt",
        file_role="tender",
        content=content,
    )
    file_id = registration.file.file_id
    checksum = str(registry.require(file_id).checksum)
    source_version = registry.file_version_token(file_id)
    source_context = {
        "document_id": file_id,
        "source_version": source_version,
        "pages": input_text.split("\f"),
        "raw_input_sha256": hashlib.sha256(content).hexdigest(),
        "coordinate_system": "1-based page and Unicode code-point character offsets",
    }
    record["source_context"] = source_context

    runtime = AgentRuntime(
        build_default_registry(file_registry=registry),
        services={"file_registry": registry},
    )
    try:
        result = await runtime.run(
            SkillRequest.create(
                {
                    "project_id": project_id,
                    "file_ids": [file_id],
                    "bidder_file_ids": [],
                    "bidder_id": "",
                    "bidder_name": "",
                    "task": "分析招标文件",
                }
            )
        )
    except Exception as exc:
        record.update(
            execution_state="failed",
            status="failed",
            errors=[f"runtime exception: {type(exc).__name__}: {exc}"],
        )
        return record

    intake_status, intake_data = _step(result, "tender-intake")
    decomposition_status, decomposition_data = _step(result, "tender-decomposition")
    record["runtime"] = {
        "run_status": str(getattr(result, "status", "unknown")),
        "intake_status": intake_status,
        "decomposition_status": decomposition_status,
    }
    if decomposition_data is None:
        record["execution_state"] = (
            "failed" if decomposition_status != "not_run" else "not_run"
        )
        record["status"] = record["execution_state"]
        record["errors"] = (
            ["decomposition returned no data"]
            if record["execution_state"] == "failed"
            else []
        )
        return record

    analysis = _mapping(decomposition_data.get("relation_analysis"))
    if analysis is None:
        record.update(
            execution_state="failed",
            status="failed",
            errors=["decomposition relation_analysis is missing"],
        )
        return record
    record["relation_analysis"] = deepcopy(dict(analysis))
    if _status(analysis.get("status")) == "not_run":
        return record

    graphs = decomposition_data.get("document_relations")
    graph = (
        _mapping(graphs[0])
        if isinstance(graphs, list) and len(graphs) == 1
        else None
    )
    if graph is None:
        record.update(
            execution_state="failed",
            status="failed",
            errors=["expected exactly one document-relations graph"],
        )
        return record

    structures = intake_data.get("document_structures") if intake_data else None
    intake_structure = (
        _mapping(structures[0]) if isinstance(structures, list) and structures else None
    )
    source = _source_proof(
        graph, source_context, checksum, intake_structure, analysis
    )
    semantic = _score_semantics(case, graph)
    errors = list(semantic["errors"])
    if source["status"] != "passed":
        errors.append("registry identity/version/character-reference validation failed")
    if intake_status not in {"success", "partial"}:
        errors.append(f"intake status is {intake_status}")
    if decomposition_status not in {"success", "partial"}:
        errors.append(f"decomposition status is {decomposition_status}")
    if _status(analysis.get("status")) not in {"executed", "success", "partial"}:
        errors.append("relation analysis did not report an executed state")

    record.update(
        execution_state="executed",
        status="passed" if not errors else "failed",
        actual_graph=deepcopy(dict(graph)),
        source_verification=source,
        semantic_evidence=semantic["evidence"],
        errors=errors,
    )
    return record


async def run_evaluation() -> dict[str, Any]:
    cases = []
    for case in FIXED_CASES:
        try:
            cases.append(await execute_case(case))
        except Exception as exc:
            record = _case_record(case)
            record.update(
                execution_state="failed",
                status="failed",
                errors=[f"case exception: {type(exc).__name__}: {exc}"],
            )
            cases.append(record)

    def counts(polarity: str) -> dict[str, int]:
        selected = [case for case in cases if case["polarity"] == polarity]
        return {
            "total": len(selected),
            "passed": sum(case["status"] == "passed" for case in selected),
            "failed": sum(case["status"] == "failed" for case in selected),
            "not_run": sum(case["status"] == "not_run" for case in selected),
        }

    checked = sum(
        case["source_verification"]["references"]["checked"] for case in cases
    )
    invalid = sum(
        case["source_verification"]["references"]["invalid"] for case in cases
    )
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now().astimezone().isoformat(),
        "classification": (
            "public manually authored regression cases; not blind and not "
            "business-material evaluation"
        ),
        "scope": "document relation semantics only",
        "source_tree_sha256": _source_tree_sha256(ROOT),
        "source_tree_sha256_algorithm": (
            "binarydigest-compatible SHA-256 over sorted src/**/*.py POSIX "
            "paths, TAB, raw file SHA-256 bytes, and LF"
        ),
        "evaluator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "summary": {
            "case_count": len(cases),
            "passed": sum(case["status"] == "passed" for case in cases),
            "failed": sum(case["status"] == "failed" for case in cases),
            "not_run": sum(case["status"] == "not_run" for case in cases),
            "negative": counts("negative"),
            "positive": counts("positive"),
            "source_references": {
                "checked": checked,
                "denominator": checked,
                "invalid": invalid,
            },
        },
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="new JSON report path; existing paths are never overwritten",
    )
    output = parser.parse_args(argv).output.resolve()
    if output.exists():
        parser.error(f"refusing to overwrite existing report: {output}")
    report = asyncio.run(run_evaluation())
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except FileExistsError:
        parser.error(f"refusing to overwrite existing report: {output}")
    if report["summary"]["failed"]:
        return 1
    return 2 if report["summary"]["not_run"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
