"""Run the frozen finite-copy attribute cases through Registry and Runtime."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from qiaowenshu_agent.core.contracts import SkillRequest  # noqa: E402
from qiaowenshu_agent.core.files import ProjectFileRegistry  # noqa: E402
from qiaowenshu_agent.core.runtime import AgentRuntime  # noqa: E402
from qiaowenshu_agent.skills import build_default_registry  # noqa: E402
from scripts import run_document_relations_eval as existing_eval  # noqa: E402


CONTRACT_PATH = (
    ROOT
    / "benchmarks"
    / "document_relations"
    / "attribute-regression"
    / "20261014"
    / "contract.md"
)
CASES_PATH = CONTRACT_PATH.with_name("cases.json")
FREEZE_PATH = CONTRACT_PATH.with_name("scope-freeze.json")
PRODUCT_SOURCE_PATH = ROOT / "src/qiaowenshu_agent/domain/document_relations.py"
REPORT_DIRECTORY = (
    ROOT
    / "benchmarks"
    / "document_relations"
    / "reports"
    / "attribute-followup-20261014"
    / "worker"
)
DEFAULT_OUTPUT = REPORT_DIRECTORY / "attribute-eval-12-current.json"
REPORT_SCHEMA = "finite-copy-attribute-runtime-eval-v1"
EXPECTED_CONTRACT_SHA256 = (
    "8204635e3ece53755fe488c05900c161d92c9dd6d0d1c3d53fff2d80612ac2f1"
)
EXPECTED_CASES_SHA256 = (
    "64c876600b0c7ba0ae504831f1a401d89c34bc0405c50ea6d6d5e080e7396605"
)
EXPECTED_BASE_COMMIT = "91fb1b9751d010af9c0f804dc6afbfee1de36dd2"
EXPECTED_BASELINE_SOURCE_TREE_SHA256 = (
    "51b1b18212c84ce50e8606106b96e4b5d5b548fb68bab491669cf08cf4e1ea34"
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _frozen_inputs() -> tuple[dict[str, Any], bytes, bytes, dict[str, Any]]:
    contract_bytes = CONTRACT_PATH.read_bytes()
    cases_bytes = CASES_PATH.read_bytes()
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    if _sha256(contract_bytes) != EXPECTED_CONTRACT_SHA256:
        raise ValueError("frozen contract SHA-256 mismatch")
    if _sha256(cases_bytes) != EXPECTED_CASES_SHA256:
        raise ValueError("frozen cases SHA-256 mismatch")
    if freeze.get("base_commit") != EXPECTED_BASE_COMMIT:
        raise ValueError("scope freeze base commit mismatch")
    if (
        freeze.get("baseline_source_tree_sha256")
        != EXPECTED_BASELINE_SOURCE_TREE_SHA256
    ):
        raise ValueError("scope freeze source-tree SHA-256 mismatch")
    cases = json.loads(cases_bytes)
    rows = cases.get("cases")
    if (
        cases.get("schema") != "finite-copy-attribute-cases-v1"
        or not isinstance(rows, list)
        or len(rows) != 12
        or len({row.get("case_id") for row in rows if isinstance(row, Mapping)}) != 12
    ):
        raise ValueError("expected twelve unique frozen finite-copy cases")
    return cases, contract_bytes, cases_bytes, freeze


def _refs_contain(value: Any, expected_quotes: set[str]) -> bool:
    if not isinstance(value, Mapping):
        return False
    references = value.get("source_references")
    if not isinstance(references, list):
        return False
    quotes = {
        reference.get("quote")
        for reference in references
        if isinstance(reference, Mapping)
    }
    return expected_quotes <= quotes


def _atoms_for_quote(graph: Mapping[str, Any], quote: str) -> list[dict[str, Any]]:
    nodes = graph.get("condition_nodes")
    if not isinstance(nodes, list):
        return []
    matches = []
    for node in nodes:
        if not isinstance(node, Mapping) or node.get("op") != "ATOM":
            continue
        references = node.get("source_references")
        source_quotes = {
            reference.get("quote")
            for reference in references
            if isinstance(reference, Mapping)
        } if isinstance(references, list) else set()
        if node.get("text") == quote or quote in source_quotes:
            matches.append(dict(node))
    return matches


def _source_block_id(node: Mapping[str, Any]) -> str | None:
    block_ids = node.get("source_block_ids")
    if not isinstance(block_ids, list) or len(block_ids) != 1:
        return None
    value = block_ids[0]
    return value if isinstance(value, str) and value else None


def _check(
    checks: dict[str, dict[str, int]],
    failures: list[dict[str, Any]],
    name: str,
    passed: bool,
    message: str,
    *,
    actual: Any = None,
) -> None:
    checks[name] = {"numerator": int(passed), "denominator": 1}
    if not passed:
        failure = {"check": name, "message": message}
        if actual is not None:
            failure["actual"] = actual
        failures.append(failure)


def _relations_for_block(
    graph: Mapping[str, Any],
    block_id: str | None,
    relation_type: str,
) -> list[dict[str, Any]]:
    rows = graph.get("block_relations")
    if not isinstance(rows, list):
        return []
    output = []
    for row in rows:
        if not isinstance(row, Mapping) or row.get("block_id") != block_id:
            continue
        scopes = row.get("scope_relations")
        if isinstance(scopes, list):
            output.extend(
                dict(scope)
                for scope in scopes
                if isinstance(scope, Mapping)
                and scope.get("relation_type") == relation_type
            )
    return output


def _evaluate_graph(
    case: Mapping[str, Any],
    graph: Mapping[str, Any],
    source_context: Mapping[str, Any],
) -> dict[str, Any]:
    checks: dict[str, dict[str, int]] = {}
    failures: list[dict[str, Any]] = []
    antecedent_text = str(case.get("antecedent_text") or "")
    attribute_text = str(case.get("attribute_text") or "")
    expected_quotes = {antecedent_text, attribute_text} - {""}
    antecedent_atoms = _atoms_for_quote(graph, antecedent_text)
    attribute_atoms = _atoms_for_quote(graph, attribute_text)
    antecedent_node = antecedent_atoms[0] if len(antecedent_atoms) == 1 else {}
    attribute_node = attribute_atoms[0] if len(attribute_atoms) == 1 else {}
    antecedent_id = antecedent_node.get("node_id")
    attribute_id = attribute_node.get("node_id")
    antecedent_block_id = _source_block_id(antecedent_node)
    attribute_block_id = _source_block_id(attribute_node)
    positives = case.get("expectation") == "confirmed_attribute"

    scopes = _relations_for_block(
        graph,
        attribute_block_id,
        "anaphoric_attribute_scope",
    )
    parents = [
        relation
        for relation in attribute_node.get("parent_relations", [])
        if isinstance(relation, Mapping)
        and relation.get("layer") == "attribute_parent"
    ]
    references = [
        reference
        for reference in graph.get("references", [])
        if isinstance(reference, Mapping)
        and reference.get("reference_kind") == "anaphora"
        and reference.get("source_block_id") == attribute_block_id
        and reference.get("reference_text") == "该复印件"
    ]

    if positives:
        _check(
            checks,
            failures,
            "atom_preservation",
            len(antecedent_atoms) == 1
            and len(attribute_atoms) == 1
            and antecedent_node.get("node_id") != attribute_node.get("node_id")
            and antecedent_node.get("op") == attribute_node.get("op") == "ATOM",
            "expected two distinct original ATOM nodes",
            actual={
                "antecedent_node_ids": [
                    node.get("node_id") for node in antecedent_atoms
                ],
                "attribute_node_ids": [
                    node.get("node_id") for node in attribute_atoms
                ],
            },
        )
        scope = scopes[0] if len(scopes) == 1 else {}
        parent = parents[0] if len(parents) == 1 else {}
        reference = references[0] if len(references) == 1 else {}
        expected_members = [antecedent_id, attribute_id]
        _check(
            checks,
            failures,
            "confirmed_scope",
            scope.get("status") == "confirmed"
            and scope.get("operator") not in {"AND", "OR"}
            and scope.get("target_node_ids") == expected_members
            and scope.get("member_node_ids") == expected_members,
            "missing confirmed nonlogical scope with exact A1/A2 members",
            actual=scope or scopes,
        )
        _check(
            checks,
            failures,
            "typed_attribute_parent",
            parent.get("status") == "confirmed"
            and bool(parent.get("basis"))
            and parent.get("target_node_ids") == [antecedent_id],
            "missing confirmed directed attribute_parent to A1",
            actual=parent or parents,
        )
        _check(
            checks,
            failures,
            "confirmed_anaphora",
            reference.get("status") == "confirmed"
            and reference.get("target_node_ids") == [antecedent_id]
            and reference.get("target_block_ids") == [antecedent_block_id],
            "confirmed reference does not target the exact A1 node and block",
            actual=reference or references,
        )
        for name, relation in (
            ("scope_source_evidence", scope),
            ("parent_source_evidence", parent),
            ("reference_source_evidence", reference),
        ):
            _check(
                checks,
                failures,
                name,
                _refs_contain(relation, expected_quotes),
                "relation source references must cite both original clauses",
                actual=relation.get("source_references", []),
            )
    else:
        _check(
            checks,
            failures,
            "attribute_atom_preservation",
            len(attribute_atoms) == 1 and attribute_node.get("op") == "ATOM",
            "expected the original attribute clause to remain one ATOM",
            actual={
                "attribute_node_ids": [
                    node.get("node_id") for node in attribute_atoms
                ],
            },
        )
        review_scopes = [
            scope
            for scope in scopes
            if scope.get("status") in {"candidate", "unresolved"}
        ]
        confirmed_parents = [
            relation
            for relation in parents
            if relation.get("status") == "confirmed"
        ]
        _check(
            checks,
            failures,
            "review_scope",
            bool(review_scopes),
            "ambiguous attribute needs a candidate or unresolved scope record",
            actual=scopes,
        )
        _check(
            checks,
            failures,
            "no_confirmed_attribute_parent",
            not confirmed_parents,
            "review case must not receive a confirmed attribute_parent",
            actual=confirmed_parents,
        )
        _check(
            checks,
            failures,
            "review_source_and_reason",
            any(
                attribute_text
                in {
                    reference.get("quote")
                    for reference in scope.get("source_references", [])
                    if isinstance(reference, Mapping)
                }
                and bool(scope.get("reason"))
                for scope in review_scopes
            ),
            "review scope must retain the attribute clause and explain review",
            actual=review_scopes,
        )

    try:
        source_check = existing_eval._validate_graph_source_references(
            graph,
            source_context,
        )
        checked = int(source_check.get("checked_references", 0))
        invalid = int(source_check.get("invalid_references", 0))
        checks["source_reference_validity"] = {
            "numerator": max(0, checked - invalid),
            "denominator": checked,
        }
        if checked == 0 or invalid:
            failures.append(
                {
                    "check": "source_reference_validity",
                    "message": "existing frozen source checker found no valid "
                    "source denominator or found invalid references",
                    "actual": {
                        "checked_references": checked,
                        "invalid_references": invalid,
                        "failures": source_check.get("failures", []),
                    },
                }
            )
        source_check_summary = {
            key: value
            for key, value in source_check.items()
            if key != "normalized_graph"
        }
    except Exception as exc:
        checks["source_reference_validity"] = {"numerator": 0, "denominator": 0}
        failures.append(
            {
                "check": "source_reference_validity",
                "message": "existing frozen source checker raised an exception",
                "actual": f"{type(exc).__name__}: {exc}",
            }
        )
        source_check_summary = {
            "checked_references": 0,
            "invalid_references": 0,
            "failures": [],
            "checker_error": f"{type(exc).__name__}: {exc}",
        }

    semantic_checks = {
        name: value
        for name, value in checks.items()
        if name != "source_reference_validity"
    }
    passed = bool(semantic_checks) and all(
        item["denominator"] > 0 and item["numerator"] == item["denominator"]
        for item in semantic_checks.values()
    )
    passed = (
        passed
        and checks["source_reference_validity"]["denominator"] > 0
        and checks["source_reference_validity"]["numerator"]
        == checks["source_reference_validity"]["denominator"]
    )
    return {
        "semantic_status": "passed" if passed else "failed",
        "checks": checks,
        "source_check": source_check_summary,
        "failures": failures,
    }


async def _execute_case(case: Mapping[str, Any]) -> dict[str, Any]:
    case_id = str(case["case_id"])
    content = str(case["input_text"]).encode("utf-8")
    input_sha256 = _sha256(content)
    source_sha256 = _sha256(PRODUCT_SOURCE_PATH.read_bytes())
    context: dict[str, Any] | None = None
    runtime_snapshot: dict[str, Any] = {"steps": []}
    graph: dict[str, Any] | None = None
    relation_data: Any = None
    execution_state = "failed"
    reason = ""
    registered_input_sha256: str | None = None

    try:
        project_id = f"attribute-followup-{case_id}"
        registry = ProjectFileRegistry()
        registration = registry.register(
            project_id=project_id,
            file_name=f"{case_id}.txt",
            file_role="tender",
            content=content,
        )
        file_id = registration.file.file_id
        registered_input_sha256 = registry.require(file_id).checksum
        source_version = registry.file_version_token(file_id)
        context = {
            "document_id": file_id,
            "source_version": source_version,
            "pages": content.decode("utf-8").split(existing_eval.BOUNDARY),
            "raw_input_sha256": input_sha256,
            "registered_input_sha256": registered_input_sha256,
        }
        if registered_input_sha256 != input_sha256:
            raise RuntimeError("Registry checksum differs from supplied input bytes")

        runtime = AgentRuntime(
            build_default_registry(file_registry=registry),
            services={"file_registry": registry},
        )
        result = await runtime.run(
            SkillRequest.create(
                {
                    "project_id": project_id,
                    "file_ids": [file_id],
                    "bidder_file_ids": [],
                    "bidder_id": "synthetic-relations-no-business-materials",
                    "bidder_name": "合成关系评测（无企业材料）",
                    "task": "分析招标文件",
                }
            )
        )
        steps = existing_eval._runtime_steps(result)
        decomposition = existing_eval._find_step(steps, "tender-decomposition")
        state, state_reason, graph_or_data = (
            existing_eval._relation_execution_state(decomposition)
        )
        relation_data = graph_or_data
        runtime_snapshot = {
            "run_id": str(getattr(result, "run_id", "")),
            "status": str(getattr(result, "status", "")),
            "step_count": len(steps),
            "steps": steps,
        }
        if state == "not_run":
            execution_state = "not_run"
            reason = state_reason
        elif state == "failed":
            execution_state = "failed"
            reason = state_reason
        else:
            graph = dict(graph_or_data)
            graph_document_id = graph.get("document_id", graph.get("docid"))
            graph_source_version = graph.get(
                "source_version",
                graph.get("version"),
            )
            if str(graph_document_id or "") != str(file_id):
                reason = "graph document identity does not match Registry input"
            elif str(graph_source_version or "") != str(source_version):
                reason = "graph source version does not match Registry input"
            else:
                execution_state = "executed"
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"

    row: dict[str, Any] = {
        "case_id": case_id,
        "expectation": case.get("expectation"),
        "input_sha256": input_sha256,
        "product_source_sha256": source_sha256,
        "registered_input_sha256": registered_input_sha256,
        "execution_state": execution_state,
        "execution_reason": reason,
        "graph": graph,
        "source_context": context,
        "runtime": runtime_snapshot,
        "relation_data": relation_data if graph is None else None,
        "semantic_status": "not_run",
        "checks": {},
        "source_check": {
            "checked_references": 0,
            "invalid_references": 0,
            "failures": [],
        },
        "failures": [],
    }

    if execution_state == "executed" and graph is not None and context is not None:
        row.update(_evaluate_graph(case, graph, context))
    elif execution_state == "not_run":
        row["failures"] = [
            {
                "check": "execution",
                "message": "Runtime did not execute relation analysis",
                "actual": reason,
            }
        ]
    else:
        row["failures"] = [
            {
                "check": "execution",
                "message": "Registry/Runtime execution failed or graph identity "
                "verification failed",
                "actual": reason,
            }
        ]
    return row


def _summarize(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    states = Counter(str(row.get("execution_state")) for row in rows)
    semantic_states = Counter(str(row.get("semantic_status")) for row in rows)
    totals: dict[str, dict[str, int]] = {}
    for row in rows:
        checks = row.get("checks")
        if not isinstance(checks, Mapping):
            continue
        for name, metric in checks.items():
            if not isinstance(metric, Mapping):
                continue
            total = totals.setdefault(name, {"numerator": 0, "denominator": 0})
            total["numerator"] += int(metric.get("numerator", 0))
            total["denominator"] += int(metric.get("denominator", 0))
    return {
        "case_count": len(rows),
        "execution_states": dict(states),
        "semantic_states": dict(semantic_states),
        "check_totals": totals,
        "failed_cases": [
            row["case_id"]
            for row in rows
            if row.get("semantic_status") != "passed"
        ],
    }


async def _run(cases: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        rows.append(await _execute_case(case))
    return rows


def _write_create_only(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    output = args.output
    if not output.is_absolute():
        output = (ROOT / output).resolve()
    if output.parent != REPORT_DIRECTORY.resolve():
        parser.error("output must be a top-level file in the frozen worker report dir")
    if output.exists():
        parser.error(f"refusing to overwrite existing report: {output}")

    try:
        case_bundle, contract_bytes, cases_bytes, freeze = _frozen_inputs()
        rows = asyncio.run(_run(case_bundle["cases"]))
        payload = {
            "schema": REPORT_SCHEMA,
            "created_at": datetime.now().astimezone().isoformat(),
            "classification": case_bundle["classification"],
            "input_hashes": {
                "contract_sha256": _sha256(contract_bytes),
                "cases_sha256": _sha256(cases_bytes),
                "scope_freeze_sha256": _sha256(FREEZE_PATH.read_bytes()),
                "baseline_source_tree_sha256": freeze[
                    "baseline_source_tree_sha256"
                ],
            },
            "product_source_sha256": _sha256(PRODUCT_SOURCE_PATH.read_bytes()),
            "runner_source_sha256": _sha256(Path(__file__).read_bytes()),
            "case_count": len(rows),
            "summary": _summarize(rows),
            "cases": rows,
        }
        serialized = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        _write_create_only(output, serialized)
    except Exception as exc:
        parser.exit(2, f"attribute eval failed without replacing existing output: "
                       f"{type(exc).__name__}: {exc}\n")

    print(
        json.dumps(
            {
                "output": str(output),
                "summary": payload["summary"],
                "product_source_sha256": payload["product_source_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return int(payload["summary"]["semantic_states"].get("failed", 0) > 0)


if __name__ == "__main__":
    raise SystemExit(main())
