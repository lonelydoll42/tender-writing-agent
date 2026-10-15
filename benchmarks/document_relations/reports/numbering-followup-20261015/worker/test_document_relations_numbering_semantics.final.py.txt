from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from qiaowenshu_agent.domain.document_relations import build_document_relations
from qiaowenshu_agent.domain.document_structure import build_document_structure


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = (
    ROOT
    / "benchmarks"
    / "document_relations"
    / "numbering-regression"
    / "20261015"
    / "cases.json"
)
CASES = [
    *json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"],
    *json.loads(
        CASES_PATH.with_name("reviewer-public-probes.json").read_text(encoding="utf-8")
    )["cases"],
]
POSITIVE_CASES = [case for case in CASES if case["expectation"] == "confirmed_pair"]
REVIEW_CASES = [case for case in CASES if case["expectation"] == "review_numbering"]
PRESERVE_CASES = [case for case in CASES if case["expectation"] == "preserve"]


def _structure(text: str, *, version: str = "v1") -> dict:
    return build_document_structure(
        [{"page_number": 1, "text": text}],
        document_id="numbering-semantics-test",
        source_version=version,
        source_checksum="public-regression",
    )


def _run(text: str, *, version: str = "v1") -> tuple[dict, dict]:
    structure = _structure(text, version=version)
    return structure, build_document_relations(structure)


def _nodes_for_block(graph: dict, block_id: str) -> list[dict]:
    return [
        node
        for node in graph["condition_nodes"]
        if block_id in node["source_block_ids"]
    ]


def _block_relation(graph: dict, block_id: str) -> dict:
    return next(
        relation
        for relation in graph["block_relations"]
        if relation["block_id"] == block_id
    )


def _quotes(value: object) -> list[str]:
    return [reference["quote"] for reference in _references(value)]


def _references(value: object) -> list[dict]:
    if isinstance(value, dict):
        if {"quote", "char_start", "char_end", "page"} <= value.keys():
            return [value]
        return [ref for child in value.values() for ref in _references(child)]
    if isinstance(value, list):
        return [ref for child in value for ref in _references(child)]
    return []


def _assert_verified_sources(structure: dict, value: object) -> None:
    pages = {page["page_number"]: page["raw_text"] for page in structure["pages"]}
    references = _references(value)
    assert references
    for reference in references:
        assert reference["document_id"] == structure["document_id"]
        assert reference["source_version"] == structure["source_version"]
        page = reference["page"]
        start, end = reference["char_start"], reference["char_end"]
        assert 0 <= start < end <= len(pages[page])
        assert pages[page][start:end] == reference["quote"]
        assert reference["locator"] == f"p{page}:c{start}-{end}"


@pytest.mark.parametrize("case", POSITIVE_CASES, ids=lambda case: case["case_id"])
def test_frozen_explicit_pairs_emit_two_source_verified_atoms(case: dict) -> None:
    text = case["input_text"]
    structure, graph = _run(text)
    block = structure["blocks"][0]
    nodes = _nodes_for_block(graph, block["block_id"])
    groups = [node for node in nodes if node["op"] in {"AND", "OR"}]
    assert len(groups) == 1
    assert len(nodes) == 3
    group = groups[0]
    assert group["op"] == "AND"
    assert group["status"] == "confirmed"
    assert len(group["children"]) == 2

    by_id = {node["node_id"]: node for node in graph["condition_nodes"]}
    leaves = [by_id[node_id] for node_id in group["children"]]
    expected = {f"编号{label}项" for label in case["labels"]}
    assert {node["text"] for node in leaves} == expected
    assert all(_quotes(node["source_references"]) == [node["text"]] for node in leaves)
    assert all(
        node["op"] == "ATOM" and node["status"] == "confirmed" for node in leaves
    )
    assert all(
        any(
            parent.get("layer") == "semantic_parent"
            and parent.get("status") == "confirmed"
            and parent.get("target_node_ids") == [group["node_id"]]
            for parent in node["parent_relations"]
        )
        for node in leaves
    )
    assert not any(node["op"] == "ATOM" and node["text"] == text for node in nodes)

    scope = group["scope_relation"]
    operator_quotes = _quotes(group["operator_relation"])
    scope_quotes = _quotes(scope.get("scope_source_references", []))
    boundary_quotes = _quotes(scope.get("boundary_source_references", []))
    assert any("均须提交" in quote for quote in operator_quotes)
    assert any("编号" in quote and "共" in quote for quote in scope_quotes)
    assert any(quote == text for quote in boundary_quotes)
    assert scope["status"] == "confirmed"
    assert scope["target_node_ids"] == group["children"]
    assert graph["roots"] == [group["node_id"]]
    assert "partial" == graph["coverage_status"]
    assert graph["needs_human_review"] is True

    forbidden = set(case.get("forbidden_labels", []))
    assert not any(
        any(f"编号{label}项" == node["text"] for label in forbidden) for node in leaves
    )
    block_scopes = _block_relation(graph, block["block_id"])["scope_relations"]
    assert len(block_scopes) == 1
    block_scope = block_scopes[0]
    assert block_scope["operator"] == "AND"
    assert block_scope["status"] == scope["status"]
    assert block_scope["operator_status"] == group["operator_relation"]["status"]
    assert block_scope["scope_status"] == scope["status"]
    assert block_scope["target_node_ids"] == scope["target_node_ids"]
    for field in (
        "scope_source_references",
        "member_source_references",
        "boundary_source_references",
    ):
        assert block_scope[field] == scope[field]
    assert (
        block_scope["operator_source_references"]
        == group["operator_relation"]["source_references"]
    )
    _assert_verified_sources(structure, graph)


@pytest.mark.parametrize("case", REVIEW_CASES, ids=lambda case: case["case_id"])
def test_frozen_ambiguous_numbering_is_retained_for_review(case: dict) -> None:
    text = case["input_text"]
    structure, graph = _run(text)
    assert graph["condition_nodes"]
    for block in structure["blocks"]:
        if not block["raw_text"].strip():
            continue
        nodes = _nodes_for_block(graph, block["block_id"])
        assert nodes
        if case["case_id"] != "N11-split-obligation" or "编号" in block["raw_text"]:
            assert all(node["status"] != "confirmed" for node in nodes)
        assert any(
            block["raw_text"] in quote for node in nodes for quote in _quotes(node)
        )
    relations = [
        relation
        for item in structure["blocks"]
        for relation in _block_relation(graph, item["block_id"])["scope_relations"]
    ]
    assert any(
        relation["status"] in {"candidate", "unresolved"} and relation.get("reason")
        for relation in relations
    )
    _assert_verified_sources(structure, graph)


@pytest.mark.parametrize("case", PRESERVE_CASES, ids=lambda case: case["case_id"])
def test_frozen_amounts_and_single_material_keep_existing_semantics(case: dict) -> None:
    text = case["input_text"]
    _structure_result, graph = _run(text)
    confirmed_atoms = [
        node
        for node in graph["condition_nodes"]
        if node["op"] == "ATOM" and node["status"] == "confirmed"
    ]
    for expected in case.get("confirmed_atoms", []):
        assert expected in {node["text"] for node in confirmed_atoms}
    assert {
        node["text"] for node in graph["condition_nodes"] if node["op"] == "ATOM"
    } == set(case["preserved_atoms"])
    if case["case_id"].startswith("C0") and "1.10万元" in text:
        assert not any(
            node["op"] in {"AND", "OR"} and node["status"] == "confirmed"
            for node in graph["condition_nodes"]
        )


def test_ordinary_material_list_keeps_existing_confirmed_scope() -> None:
    text = "共两项材料均须提交：营业执照；审计报告。"
    structure, graph = _run(text)
    groups = [node for node in graph["condition_nodes"] if node["op"] == "AND"]
    assert len(groups) == 1
    group = groups[0]
    assert group["status"] == "confirmed"
    by_id = {node["node_id"]: node for node in graph["condition_nodes"]}
    assert {by_id[node_id]["text"] for node_id in group["children"]} == {
        "营业执照",
        "审计报告",
    }
    assert all(by_id[node_id]["status"] == "confirmed" for node_id in group["children"])
    assert (
        _block_relation(graph, structure["blocks"][0]["block_id"])["scope_relations"][
            0
        ]["status"]
        == "confirmed"
    )
    _assert_verified_sources(structure, graph)


@pytest.mark.parametrize(
    "damage",
    [
        "span_coordinates",
        "reference_coordinates",
        "duplicate_block_id",
        "document_id",
        "source_version",
        "reference_document_id",
        "reference_source_version",
    ],
)
def test_invalid_source_identity_or_location_never_confirms(
    damage: str,
) -> None:
    text = POSITIVE_CASES[0]["input_text"]
    structure = _structure(text)
    block = structure["blocks"][0]
    if damage == "span_coordinates":
        block["source_span"]["start"] = -1
    elif damage == "reference_coordinates":
        block["source_references"][0]["char_start"] = -1
    elif damage == "duplicate_block_id":
        structure["blocks"].append(deepcopy(block))
    elif damage.startswith("reference_"):
        block["source_references"][0][damage.removeprefix("reference_")] = "conflict"
    else:
        structure[damage] = ""

    graph = build_document_relations(structure)
    assert graph["condition_nodes"]
    assert all(node["status"] == "unresolved" for node in graph["condition_nodes"])
    assert all(node["source_references"] == [] for node in graph["condition_nodes"])
    assert not any(
        value.get("status") == "confirmed"
        for node in graph["condition_nodes"]
        for value in [
            node.get("operator_relation", {}),
            node.get("scope_relation", {}),
            *node["parent_relations"],
        ]
    )
    assert all(
        relation["status"] == "unresolved"
        and relation.get("operator_status") != "confirmed"
        and relation.get("scope_status") != "confirmed"
        for item in graph["block_relations"]
        for relation in item["scope_relations"]
    )
