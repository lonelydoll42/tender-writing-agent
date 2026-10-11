from __future__ import annotations

import asyncio
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from scripts import run_document_relations_eval as frozen
from scripts import run_document_relations_nested_eval as nested


TEXT = (
    "以下两组材料均须满足：第一组甲材料或乙材料；"
    "第二组丙材料且丁材料。另须提交其他证明。"
)
DOCUMENT_ID = "synthetic-document"
SOURCE_VERSION = "synthetic-v1"


def _ref(text: str, quote: str) -> dict[str, Any]:
    start = text.index(quote)
    page_start = text.rfind("\f", 0, start) + 1
    local_start = start - page_start
    line = text[page_start:start].count("\n") + 1
    return {
        "document_id": DOCUMENT_ID,
        "source_version": SOURCE_VERSION,
        "page": 1,
        "line": line,
        "locator": f"p1:c{local_start}-{local_start + len(quote)}",
        "char_start": local_start,
        "char_end": local_start + len(quote),
        "quote": quote,
    }


def _atom(node_id: str, text: str, source_text: str = TEXT) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "op": "ATOM",
        "status": "confirmed",
        "text": text,
        "children": [],
        "source_references": [_ref(source_text, text)],
        "parent_relations": [],
    }


def _group(
    node_id: str,
    op: str,
    children: list[str],
    operator_quote: str,
    scope_quote: str,
    boundary_quote: str,
    source_text: str = TEXT,
) -> dict[str, Any]:
    cue = {"AND": "均须满足", "OR": "或", "INNER_AND": "且"}[op]
    relation_op = "AND" if op == "INNER_AND" else op
    operator_source = _ref(source_text, cue)
    scope_source = _ref(source_text, scope_quote)
    atom_text = {"a": "甲材料", "b": "乙材料", "c": "丙材料", "d": "丁材料"}
    members = [
        _ref(source_text, atom_text[child]) for child in children if child in atom_text
    ]
    scope = {
        "status": "confirmed",
        "target_node_ids": list(children),
        "source_references": [scope_source, *members],
        "scope_source_references": [scope_source],
        "boundary_source_references": [_ref(source_text, boundary_quote)],
    }
    return {
        "node_id": node_id,
        "op": relation_op,
        "status": "confirmed",
        "text": operator_quote,
        "children": list(children),
        "source_references": [operator_source, scope_source, *members],
        "operator_relation": {
            "status": "confirmed",
            "source_references": [operator_source],
        },
        "scope_relation": scope,
        "parent_relations": [],
    }


def _positive_fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    case = {
        "id": "nested-positive",
        "text": TEXT,
        "expected_tree": {
            "op": "AND",
            "operator_quote": "以下两组材料均须满足",
            "scope_quote": "以下两组材料",
            "children": [
                {
                    "op": "OR",
                    "operator_quote": "第一组甲材料或乙材料",
                    "scope_quote": "第一组",
                    "children": ["甲材料", "乙材料"],
                },
                {
                    "op": "AND",
                    "operator_quote": "第二组丙材料且丁材料",
                    "scope_quote": "第二组",
                    "children": ["丙材料", "丁材料"],
                },
            ],
        },
        "outside_atoms": ["其他证明"],
    }
    atoms = {
        key: _atom(key, text)
        for key, text in {
            "a": "甲材料",
            "b": "乙材料",
            "c": "丙材料",
            "d": "丁材料",
        }.items()
    }
    group1 = _group("g1", "OR", ["a", "b"], "第一组甲材料或乙材料", "第一组", "；")
    group2 = _group(
        "g2", "INNER_AND", ["c", "d"], "第二组丙材料且丁材料", "第二组", "。"
    )
    root = _group(
        "g0", "AND", ["g1", "g2"], "以下两组材料均须满足", "以下两组材料", "。"
    )
    for child, parent, cue in [
        (group1, "g0", "均须"),
        (group2, "g0", "均须"),
        (atoms["a"], "g1", "或"),
        (atoms["b"], "g1", "或"),
        (atoms["c"], "g2", "且"),
        (atoms["d"], "g2", "且"),
    ]:
        child["parent_relations"] = [
            {
                "status": "confirmed",
                "layer": "semantic_parent",
                "basis": "explicit confirmed logical scope",
                "target_node_ids": [parent],
                "source_references": [_ref(TEXT, cue)],
            }
        ]
    outside = {
        "node_id": "outside",
        "op": "ATOM",
        "status": "candidate",
        "text": "另须提交其他证明",
        "children": [],
        "source_references": [_ref(TEXT, "其他证明")],
        "parent_relations": [],
    }
    graph = {
        "schema": "document-relations-v1",
        "document_id": DOCUMENT_ID,
        "source_version": SOURCE_VERSION,
        "roots": ["g0"],
        "block_relations": [],
        "condition_nodes": [root, group1, group2, *atoms.values(), outside],
    }
    context = {
        "document_id": DOCUMENT_ID,
        "source_version": SOURCE_VERSION,
        "pages": [TEXT],
        "raw_input_sha256": hashlib.sha256(TEXT.encode()).hexdigest(),
    }
    return case, graph, context


def _runtime(case: dict[str, Any], graph: Any, context: Any) -> dict[str, Any]:
    return {
        "execution_state": "executed",
        "registered_input_sha256": hashlib.sha256(case["text"].encode()).hexdigest(),
        "graph": deepcopy(graph),
        "source_context": deepcopy(context),
    }


def test_correct_nested_tree_and_predicate_prefixed_outside_atom_pass() -> None:
    case, graph, context = _positive_fixture()
    assert nested._positive(case, graph, context) == []

    ancestor_graph = deepcopy(graph)
    ancestor_graph["roots"].append("ancestor")
    ancestor_graph["condition_nodes"].append(
        {
            "node_id": "ancestor",
            "op": "AND",
            "status": "confirmed",
            "children": ["g0"],
        }
    )
    assert nested._positive(case, ancestor_graph, context) == []

    flat = _group(
        "flat",
        "AND",
        ["a", "b", "c", "d"],
        "以下两组材料均须满足",
        "以下两组材料",
        "。",
    )
    flat["parent_relations"] = []
    conflicting = deepcopy(graph)
    conflicting["roots"].append("flat")
    conflicting["condition_nodes"].append(flat)
    for node in conflicting["condition_nodes"]:
        if node["node_id"] in {"a", "b", "c", "d"}:
            node["parent_relations"].append(
                {
                    "status": "confirmed",
                    "basis": "explicit flat group",
                    "target_node_ids": ["flat"],
                    "source_references": [_ref(TEXT, "均须")],
                }
            )
    source_check = frozen._validate_graph_source_references(conflicting, context)
    assert source_check["invalid_references"] == 0
    assert any(
        "reuses expected-tree nodes" in error
        for error in nested._positive(case, conflicting, context)
    )

    flat = deepcopy(graph)
    root = next(node for node in flat["condition_nodes"] if node["node_id"] == "g0")
    root["children"] = ["a", "b", "c", "d"]
    root["scope_relation"]["target_node_ids"] = ["a", "b", "c", "d"]
    assert nested._positive(case, flat, context)


def test_wrong_sibling_boundary_is_semantic_failure_with_valid_source_coords() -> None:
    case, graph, context = _positive_fixture()
    changed = deepcopy(graph)
    group = next(node for node in changed["condition_nodes"] if node["node_id"] == "g1")
    group["scope_relation"]["boundary_source_references"] = [_ref(TEXT, "。")]
    validation = frozen._validate_graph_source_references(changed, context)
    assert validation["invalid_references"] == 0
    assert validation["checked_references"] > 0
    assert any(
        "terminal" in error for error in nested._positive(case, changed, context)
    )

    header = deepcopy(graph)
    group = next(node for node in header["condition_nodes"] if node["node_id"] == "g1")
    group["scope_relation"]["boundary_source_references"] = [_ref(TEXT, "：")]
    assert (
        frozen._validate_graph_source_references(header, context)["invalid_references"]
        == 0
    )
    assert any("terminal" in error for error in nested._positive(case, header, context))


def test_operator_swap_missing_parent_wrong_scope_bad_source_and_cycle_fail() -> None:
    case, graph, context = _positive_fixture()
    changed = deepcopy(graph)
    next(node for node in changed["condition_nodes"] if node["node_id"] == "g1")[
        "op"
    ] = "AND"
    assert nested._positive(case, changed, context)

    missing_parent = deepcopy(graph)
    next(node for node in missing_parent["condition_nodes"] if node["node_id"] == "a")[
        "parent_relations"
    ] = []
    assert any(
        "parent evidence" in error
        for error in nested._positive(case, missing_parent, context)
    )

    wrong_scope = deepcopy(graph)
    next(node for node in wrong_scope["condition_nodes"] if node["node_id"] == "g1")[
        "scope_relation"
    ]["target_node_ids"] = ["a", "d"]
    assert any(
        "scope targets" in error
        for error in nested._positive(case, wrong_scope, context)
    )

    bad_source = deepcopy(graph)
    next(node for node in bad_source["condition_nodes"] if node["node_id"] == "a")[
        "source_references"
    ][0]["char_start"] += 1
    assert (
        frozen._validate_graph_source_references(bad_source, context)[
            "invalid_references"
        ]
        > 0
    )

    nodes, _ = nested._nodes(graph)
    nodes["g1"] = {**nodes["g1"], "children": ["g1", "b"]}
    assert nested._match("g1", case["expected_tree"]["children"][0], nodes) is None


def test_unary_required_wrapper_is_checked_and_string_children_recurse() -> None:
    text = "两部分均须满足：第一部分甲材料必须提交；第二部分乙材料或丙材料。"
    case = {
        "id": "unary-and",
        "text": text,
        "expected_tree": {
            "op": "AND",
            "operator_quote": "两部分均须满足",
            "scope_quote": "两部分",
            "children": [
                "甲材料",
                {
                    "op": "OR",
                    "operator_quote": "第二部分乙材料或丙材料",
                    "scope_quote": "第二部分",
                    "children": ["乙材料", "丙材料"],
                },
            ],
        },
    }
    required = _ref(text, "必须提交")
    atom_a = _atom("a", "甲材料", text)
    unary = {
        "node_id": "unary",
        "op": "AND",
        "status": "confirmed",
        "text": "甲材料必须提交",
        "children": ["a"],
        "operator_relation": {
            "status": "confirmed",
            "kind": "unary_required_normalization",
            "basis": "single_item_requirement",
            "source_references": [required],
        },
        "scope_relation": {
            "status": "confirmed",
            "target_node_ids": ["a"],
            "source_references": [_ref(text, "第一部分"), _ref(text, "甲材料")],
            "boundary_source_references": [_ref(text, "；")],
        },
        "parent_relations": [],
    }
    atom_a["parent_relations"] = [
        {
            "status": "confirmed",
            "basis": "required unary scope",
            "target_node_ids": ["unary"],
            "source_references": [required],
        }
    ]
    atom_b = _atom("b", "乙材料", text)
    atom_c = _atom("c", "丙材料", text)
    group = _group(
        "g1", "OR", ["b", "c"], "第二部分乙材料或丙材料", "第二部分", "。", text
    )
    root = _group("g0", "AND", ["unary", "g1"], "两部分均须满足", "两部分", "。", text)
    for child_id, child, cue in [
        ("unary", unary, "均须"),
        ("g1", group, "均须"),
        ("b", atom_b, "或"),
        ("c", atom_c, "或"),
    ]:
        parent = "g0" if child_id in {"unary", "g1"} else "g1"
        child["parent_relations"] = [
            {
                "status": "confirmed",
                "basis": "explicit scope",
                "target_node_ids": [parent],
                "source_references": [_ref(text, cue)],
            }
        ]
    graph = {
        "schema": "document-relations-v1",
        "document_id": DOCUMENT_ID,
        "source_version": SOURCE_VERSION,
        "roots": ["g0"],
        "condition_nodes": [root, unary, group, atom_a, atom_b, atom_c],
        "block_relations": [],
    }
    context = {
        "document_id": DOCUMENT_ID,
        "source_version": SOURCE_VERSION,
        "pages": [text],
        "raw_input_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }
    assert nested._positive(case, graph, context) == []


def test_full_executed_chain_preserves_graph_and_reports_source_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case, graph, context = _positive_fixture()

    async def executed(path: Path, case_id: str) -> dict[str, Any]:
        return _runtime(case, graph, context)

    monkeypatch.setattr(frozen, "_run_input", executed)
    raw = json.dumps(
        {"schema_version": "1", "cases": [case]}, ensure_ascii=False
    ).encode()
    report = asyncio.run(
        nested.run_evaluation({"schema_version": "1", "cases": [case]}, raw)
    )
    row = report["cases"][0]
    assert row["status"] == "passed"
    assert row["execution_state"] == "executed"
    assert row["actual_graph"] == graph
    assert row["source_context"] == context
    assert row["source_identity"]["status"] == "registry_verified"
    assert row["source_validation"]["invalid_references"] == 0
    assert row["source_validation"]["checked_references"] > 0
    assert report["summary"] == {
        "passed": 1,
        "failed": 0,
        "not_run": 0,
        "executed": 1,
        "total": 1,
        "positive_passed": 1,
        "positive_total": 1,
        "review_handled": 0,
        "review_total": 0,
        "source_references": {
            "invalid": 0,
            "checked": row["source_validation"]["checked_references"],
        },
    }
    assert not any("rate" in key for key in report["summary"])


def test_zero_source_denominator_cannot_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    case, _, context = _positive_fixture()
    graph = {
        "schema": "document-relations-v1",
        "document_id": DOCUMENT_ID,
        "source_version": SOURCE_VERSION,
        "roots": ["g0"],
        "condition_nodes": [],
        "block_relations": [],
    }

    async def executed(path: Path, case_id: str) -> dict[str, Any]:
        return _runtime(case, graph, context)

    monkeypatch.setattr(frozen, "_run_input", executed)
    report = asyncio.run(
        nested.run_evaluation(
            {"schema_version": "1", "cases": [case]}, b'{"cases":[{}]}'
        )
    )
    row = report["cases"][0]
    assert row["execution_state"] == "executed"
    assert row["status"] == "failed"
    assert row["source_validation"]["checked_references"] == 0
    assert any("zero references" in error for error in row["errors"])


def test_runtime_failed_and_not_run_states_remain_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case, _, _ = _positive_fixture()

    async def failed(path: Path, case_id: str) -> dict[str, Any]:
        return {"execution_state": "failed", "reason": "relation builder failed"}

    monkeypatch.setattr(frozen, "_run_input", failed)
    report = asyncio.run(
        nested.run_evaluation({"schema_version": "1", "cases": [case]}, b"{}")
    )
    assert report["cases"][0]["status"] == "failed"
    assert report["cases"][0]["execution_state"] == "failed"
    assert report["summary"]["failed"] == 1
    assert report["summary"]["not_run"] == 0
    assert report["summary"]["executed"] == 0

    async def not_run(path: Path, case_id: str) -> dict[str, Any]:
        return {"execution_state": "not_run", "reason": "runtime not invoked"}

    monkeypatch.setattr(frozen, "_run_input", not_run)
    report = asyncio.run(
        nested.run_evaluation({"schema_version": "1", "cases": [case]}, b"{}")
    )
    assert report["cases"][0]["status"] == "not_run"
    assert report["cases"][0]["execution_state"] == "not_run"
    assert report["summary"]["passed"] == 0
    assert report["summary"]["executed"] == 0


def test_review_keeps_opaque_multi_material_atom_and_allows_local_or() -> None:
    text = "以下两项材料均须提交，范围尚不明确：甲材料或丙材料；另须提交乙材料。"
    case = {
        "id": "review-only",
        "text": text,
        "review_only": True,
        "forbidden_operator_quote": "以下两项材料均须提交",
        "review_quote": "范围尚不明确",
        "retained_atoms": ["甲材料", "乙材料"],
    }
    header = {
        "node_id": "header",
        "op": "AND",
        "status": "candidate",
        "children": [],
        "operator_relation": {
            "status": "confirmed",
            "source_references": [_ref(text, "均须")],
        },
        "scope_relation": {
            "status": "candidate",
            "target_node_ids": [],
            "source_references": [_ref(text, "范围尚不明确")],
        },
    }
    local_or = {
        "node_id": "local-or",
        "op": "OR",
        "status": "confirmed",
        "children": [],
        "operator_relation": {
            "status": "confirmed",
            "source_references": [_ref(text, "或")],
        },
        "scope_relation": {
            "status": "confirmed",
            "target_node_ids": [],
            "source_references": [_ref(text, "甲材料")],
        },
    }
    opaque = {
        "node_id": "retained",
        "op": "ATOM",
        "status": "candidate",
        "text": "需提交甲材料并另须提交乙材料",
        "children": [],
        "source_references": [
            _ref(text, "范围尚不明确"),
            _ref(text, "甲材料"),
            _ref(text, "乙材料"),
        ],
    }
    graph = {"condition_nodes": [header, local_or, opaque], "block_relations": []}
    context = {
        "pages": [text],
        "document_id": DOCUMENT_ID,
        "source_version": SOURCE_VERSION,
    }
    assert nested._review(case, graph, context) == []

    forbid_operator = {**case, "forbid_confirmed_operator": True}
    assert any(
        "confirms its operator" in error
        for error in nested._review(forbid_operator, graph, context)
    )
    confirmed_scope = deepcopy(graph)
    confirmed_scope["condition_nodes"][0]["scope_relation"]["status"] = "confirmed"
    assert any(
        "complete group/scope" in error
        for error in nested._review(case, confirmed_scope, context)
    )


def test_existing_output_is_rejected_before_cases_read(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    output.write_text("preserve", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        nested.main(
            ["--cases", str(tmp_path / "missing.json"), "--output", str(output)]
        )
    assert exc.value.code == 2
    assert output.read_text(encoding="utf-8") == "preserve"
