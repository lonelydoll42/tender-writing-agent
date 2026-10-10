from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from scripts import run_document_relations_eval as evaluation


SYNTHETIC_PAGE = "甲材料 甲乙择一\n乙材料\n丙材料 丙丁均须提交\n丁材料\n两组均须满足"


def _reference(page: int, line: int, quote: str) -> dict[str, Any]:
    return {"page": page, "line": line, "quote": quote}


def _product_reference(
    page_text: str,
    line_number: int,
    quote: str,
    *,
    document_id: str = "synthetic-document",
    source_version: str = "synthetic-v1",
) -> dict[str, Any]:
    lines = page_text.split("\n")
    line_start = sum(len(line) + 1 for line in lines[: line_number - 1])
    quote_start = lines[line_number - 1].index(quote)
    char_start = line_start + quote_start
    return {
        "document_id": document_id,
        "source_version": source_version,
        "page": 1,
        "line_number": line_number,
        "quote": quote,
        "char_start": char_start,
        "char_end": char_start + len(quote),
    }


def _char_reference(
    page_text: str,
    line_number: int,
    quote: str,
    *,
    document_id: str = "synthetic-document",
    source_version: str = "synthetic-v1",
) -> dict[str, Any]:
    lines = page_text.split("\n")
    line_start = sum(len(line) + 1 for line in lines[: line_number - 1])
    char_start = line_start + lines[line_number - 1].index(quote)
    char_end = char_start + len(quote)
    return {
        "document_id": document_id,
        "source_version": source_version,
        "page": 1,
        "locator": f"p1:c{char_start}-{char_end}",
        "char_start": char_start,
        "char_end": char_end,
        "quote": quote,
    }


def _synthetic_source_context(
    page_text: str = SYNTHETIC_PAGE,
) -> dict[str, Any]:
    return {
        "document_id": "synthetic-document",
        "source_version": "synthetic-v1",
        "pages": [page_text],
        "raw_input_sha256": "synthetic-only",
    }


def _synthetic_case() -> dict[str, Any]:
    atoms = [
        ("A1", "甲材料", _reference(1, 1, "甲材料")),
        ("A2", "乙材料", _reference(1, 2, "乙材料")),
        ("A3", "丙材料", _reference(1, 3, "丙材料")),
        ("A4", "丁材料", _reference(1, 4, "丁材料")),
    ]
    return {
        "case_id": "synthetic-nested",
        "conditions": [
            {
                "id": atom_id,
                "text": text,
                "certainty": "confirmed",
                "source": source,
            }
            for atom_id, text, source in atoms
        ],
        "expect_confirmed": {
            "conditions": ["A1", "A2", "A3", "A4"],
            "relations": [
                {
                    "type": "parent",
                    "parent": "合成根组",
                    "children": ["S1", "S2"],
                    "source": [_reference(1, 5, "两组均须满足")],
                }
            ],
        },
        "groups": [
            {
                "id": "S1",
                "status": "confirmed",
                "operator": "OR",
                "members": ["A1", "A2"],
                "boundary_basis": [_reference(1, 1, "甲乙择一")],
            },
            {
                "id": "S2",
                "status": "confirmed",
                "operator": "AND",
                "members": ["A3", "A4"],
                "boundary_basis": [_reference(1, 3, "丙丁均须提交")],
            },
            {
                "id": "S0",
                "status": "confirmed",
                "operator": "AND",
                "members": ["S1", "S2"],
                "boundary_basis": [_reference(1, 5, "两组均须满足")],
            },
        ],
        "forbidden": [],
        "needs_review": [],
        "denominators": {
            "confirmed_atom_count": 4,
            "condition_omission": 4,
            "wrong_merge_pairs": 6,
            "wrong_split_atom_units": 4,
            "confirmed_scope_count": 3,
            "scope_membership_decisions": 12,
        },
    }


def _atom(
    node_id: str, text: str, source: dict[str, Any], status: str = "confirmed"
) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "op": "ATOM",
        "status": status,
        "text": text,
        "children": [],
        "source_block_ids": [f"block-{node_id}"],
        "source_references": [source],
    }


def _candidate_literal_fixture(
    *,
    page_text: str = "项目联系人表一份。",
    expected_quote: str = "项目联系人表一份。",
    expected_line: int = 1,
    actual_ref: dict[str, Any] | None = None,
    actual_text: str | None = None,
    actual_status: str = "candidate",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    expected_ref = _reference(1, expected_line, expected_quote)
    expected = {
        "id": "A3",
        "text": "可能要求提交项目联系人表；仅作candidate",
        "certainty": "candidate",
        "source": [expected_ref],
    }
    case = {
        "case_id": "synthetic-candidate-source-literal",
        "conditions": [expected],
        "expect_confirmed": {"conditions": [], "relations": []},
        "groups": [],
        "forbidden": [],
        "needs_review": [
            {
                "type": "condition",
                "condition_id": "A3",
                "status": "candidate",
                "source": [expected_ref],
            }
        ],
        "denominators": {
            "confirmed_atom_count": 0,
            "condition_omission": 0,
            "wrong_merge_pairs": 0,
            "wrong_split_atom_units": 0,
            "confirmed_scope_count": 0,
            "scope_membership_decisions": 0,
        },
    }
    actual_ref = actual_ref or _product_reference(
        page_text, expected_line, expected_quote
    )
    graph = {
        "schema": "document-relations-v1",
        "document_id": "synthetic-document",
        "source_version": "synthetic-v1",
        "block_relations": [],
        "condition_nodes": [
            _atom(
                "candidate-node",
                actual_text if actual_text is not None else expected_quote,
                actual_ref,
                actual_status,
            )
        ],
        "roots": ["candidate-node"],
        "references": [],
        "coverage_status": "partial",
        "needs_human_review": True,
    }
    return case, graph, _synthetic_source_context(page_text)


def _group(
    node_id: str,
    operator: str,
    children: list[str],
    source: dict[str, Any],
    status: str = "confirmed",
) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "op": operator,
        "status": status,
        "text": f"synthetic {operator}",
        "children": children,
        "source_block_ids": [],
        "source_references": [source],
        "operator_relation": {
            "status": status,
            "source_references": [source],
        },
        "scope_relation": {
            "status": status,
            "target_node_ids": children,
            "source_references": [source],
            "boundary_source_references": [source],
        },
    }


def _synthetic_graph() -> dict[str, Any]:
    refs = {
        "A1": _product_reference(SYNTHETIC_PAGE, 1, "甲材料"),
        "A2": _product_reference(SYNTHETIC_PAGE, 2, "乙材料"),
        "A3": _product_reference(SYNTHETIC_PAGE, 3, "丙材料"),
        "A4": _product_reference(SYNTHETIC_PAGE, 4, "丁材料"),
    }
    nodes = [
        _atom("n1", "甲材料", refs["A1"]),
        _atom("n2", "乙材料", refs["A2"]),
        _atom("n3", "丙材料", refs["A3"]),
        _atom("n4", "丁材料", refs["A4"]),
        _group(
            "g1",
            "OR",
            ["n1", "n2"],
            _product_reference(SYNTHETIC_PAGE, 1, "甲乙择一"),
        ),
        _group(
            "g2",
            "AND",
            ["n3", "n4"],
            _product_reference(SYNTHETIC_PAGE, 3, "丙丁均须提交"),
        ),
        _group(
            "g0",
            "AND",
            ["g1", "g2"],
            _product_reference(SYNTHETIC_PAGE, 5, "两组均须满足"),
        ),
    ]
    return {
        "schema": "document-relations-v1",
        "document_id": "synthetic-document",
        "source_version": "synthetic-v1",
        "block_relations": [],
        "condition_nodes": nodes,
        "roots": ["g0"],
        "references": [],
        "coverage_status": "partial",
        "needs_human_review": False,
    }


def test_correct_nested_and_or_hierarchy_passes() -> None:
    result = evaluation._score_case(
        _synthetic_case(), _synthetic_graph(), _synthetic_source_context()
    )

    assert result["status"] == "passed"
    assert result["matched_group_ids"] == ["S0", "S1", "S2"]
    assert result["actual_source_validation"]["invalid_references"] == 0
    assert result["metrics"]["operator_group_structure"] == {
        "numerator": 0,
        "denominator": 3,
    }


@pytest.mark.parametrize(
    "bad_operator_quote",
    [
        _product_reference(SYNTHETIC_PAGE, 3, "均须提交"),
        _product_reference(SYNTHETIC_PAGE, 1, "甲材料"),
    ],
)
def test_operator_relation_must_cite_its_own_explicit_cue(
    bad_operator_quote: dict[str, Any],
) -> None:
    graph = _synthetic_graph()
    or_node = next(node for node in graph["condition_nodes"] if node["node_id"] == "g1")
    or_node["operator_relation"]["source_references"] = [bad_operator_quote]
    result = evaluation._score_case(
        _synthetic_case(), graph, _synthetic_source_context()
    )

    assert result["status"] == "failed"
    assert result["metrics"]["operator_evidence"] == {
        "numerator": 1,
        "denominator": 3,
    }
    assert any(
        error["metric"] == "operator_evidence" and error["expected_group_id"] == "S1"
        for error in result["errors"]
    )


def _operator_review_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    source = _reference(1, 1, "范围仍需复核")
    item = {
        "type": "operator",
        "allowed_statuses": {"unresolved"},
        "sources": [source],
    }
    return item, source


@pytest.mark.parametrize(
    "channel",
    ["condition_node", "node_scope", "block_scope", "block_operator_relations"],
)
def test_operator_review_collects_explicit_relation_channels(channel: str) -> None:
    item, source = _operator_review_fixture()
    relation = {"status": "unresolved", "source_references": [source]}
    graph: dict[str, Any] = {"condition_nodes": [], "block_relations": []}
    if channel == "condition_node":
        graph["condition_nodes"] = [{"operator_relation": relation}]
    elif channel == "node_scope":
        graph["condition_nodes"] = [
            {"scope_relation": {"status": "candidate", "operator_relation": relation}}
        ]
    elif channel == "block_scope":
        graph["block_relations"] = [
            {
                "scope_relations": [
                    {"status": "unresolved", "operator_relation": relation}
                ]
            }
        ]
    else:
        graph["block_relations"] = [{"operator_relations": [relation]}]

    assert evaluation._review_item_covered(item, graph, {}) == (True, "")


def test_unresolved_scope_does_not_promote_candidate_operator() -> None:
    item, source = _operator_review_fixture()
    graph = {
        "block_relations": [
            {
                "scope_relations": [
                    {
                        "status": "unresolved",
                        "operator_relation": {
                            "status": "candidate",
                            "source_references": [source],
                        },
                    }
                ]
            }
        ]
    }

    assert evaluation._review_item_covered(item, graph, {})[0] is False


def test_operator_status_without_relation_and_sources_is_not_evidence() -> None:
    item, _ = _operator_review_fixture()
    graph = {
        "condition_nodes": [{"operator_status": "unresolved"}],
        "block_relations": [{"operator_status": "unresolved"}],
    }

    assert evaluation._review_item_covered(item, graph, {})[0] is False


@pytest.mark.parametrize(
    ("source", "wrapper_status"),
    [
        (_reference(1, 2, "其他范围"), None),
        (_reference(1, 1, "范围仍需复核"), "candidate"),
    ],
)
def test_operator_review_rejects_wrong_source_or_wrapper_conflict(
    source: dict[str, Any], wrapper_status: str | None
) -> None:
    item, _ = _operator_review_fixture()
    scope: dict[str, Any] = {
        "operator_relation": {
            "status": "unresolved",
            "source_references": [source],
        }
    }
    if wrapper_status is not None:
        scope["operator_status"] = wrapper_status
    graph = {"block_relations": [{"scope_relations": [scope]}]}

    assert evaluation._review_item_covered(item, graph, {})[0] is False


def test_separate_operator_scope_member_and_boundary_sources_pass() -> None:
    graph = _synthetic_graph()
    or_node = next(node for node in graph["condition_nodes"] if node["node_id"] == "g1")
    cue = _product_reference(SYNTHETIC_PAGE, 1, "择一")
    scope_basis = _product_reference(SYNTHETIC_PAGE, 1, "甲乙择一")
    or_node["operator_relation"]["source_references"] = [cue]
    or_node["scope_relation"]["source_references"] = [scope_basis]
    or_node["scope_relation"]["boundary_source_references"] = [scope_basis]

    result = evaluation._score_case(
        _synthetic_case(), graph, _synthetic_source_context()
    )

    assert result["status"] == "passed"
    assert result["metrics"]["operator_evidence"] == {
        "numerator": 0,
        "denominator": 3,
    }
    assert result["metrics"]["scope_evidence"]["numerator"] == 0
    assert result["metrics"]["boundary_evidence"]["numerator"] == 0


@pytest.mark.parametrize(
    ("relation_field", "expected_metric"),
    [
        ("source_references", "scope_evidence"),
        ("boundary_source_references", "boundary_evidence"),
    ],
)
def test_group_level_refs_cannot_substitute_for_scope_or_boundary_refs(
    relation_field: str, expected_metric: str
) -> None:
    graph = _synthetic_graph()
    or_node = next(node for node in graph["condition_nodes"] if node["node_id"] == "g1")
    or_node["scope_relation"][relation_field] = []

    result = evaluation._score_case(
        _synthetic_case(), graph, _synthetic_source_context()
    )

    assert result["status"] == "failed"
    assert result["metrics"][expected_metric]["numerator"] == 1
    assert any(
        error["metric"] == expected_metric and error["expected_group_id"] == "S1"
        for error in result["errors"]
    )


def _scope_parent_fixture(
    *, semantic_scope_evidence: bool
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    raw_page = "甲材料\n乙材料\n两项同属一个范围"
    parent_source = _reference(1, 3, "两项同属一个范围")
    case = {
        "case_id": "synthetic-scope-parent",
        "conditions": [
            {
                "id": "A1",
                "text": "甲材料",
                "certainty": "confirmed",
                "source": _reference(1, 1, "甲材料"),
            },
            {
                "id": "A2",
                "text": "乙材料",
                "certainty": "confirmed",
                "source": _reference(1, 2, "乙材料"),
            },
        ],
        "expect_confirmed": {
            "conditions": ["A1", "A2"],
            "relations": [
                {
                    "type": "parent",
                    "parent": "语义范围",
                    "children": ["A1", "A2"],
                    "source": [parent_source],
                }
            ],
        },
        "groups": [
            {
                "id": "S1",
                "status": "confirmed",
                "operator": "SCOPE",
                "members": ["A1", "A2"],
                "boundary_basis": [parent_source],
            }
        ],
        "forbidden": [],
        "needs_review": [],
        "denominators": {
            "confirmed_atom_count": 2,
            "condition_omission": 2,
            "wrong_merge_pairs": 1,
            "wrong_split_atom_units": 2,
            "confirmed_scope_count": 1,
            "scope_membership_decisions": 2,
        },
    }
    atom_a = _atom(
        "n1",
        "甲材料",
        _product_reference(raw_page, 1, "甲材料"),
    )
    atom_b = _atom(
        "n2",
        "乙材料",
        _product_reference(raw_page, 2, "乙材料"),
    )
    blocks = [
        {
            "block_id": "legacy-parent",
            "parent_relation": {
                "status": "confirmed",
                "target_block_ids": ["legacy-child"],
                "source_references": [
                    _product_reference(raw_page, 3, "两项同属一个范围")
                ],
            },
        }
    ]
    if semantic_scope_evidence:
        atom_a["scope_relation"] = {
            "status": "confirmed",
            "target_node_ids": ["n2"],
            "source_references": [_product_reference(raw_page, 3, "两项同属一个范围")],
            "boundary_source_references": [
                _product_reference(raw_page, 3, "两项同属一个范围")
            ],
        }
    graph = {
        "schema": "document-relations-v1",
        "document_id": "synthetic-document",
        "source_version": "synthetic-v1",
        "block_relations": blocks,
        "condition_nodes": [atom_a, atom_b],
        "roots": ["n1", "n2"],
        "references": [],
        "coverage_status": "partial",
        "needs_human_review": False,
    }
    return case, graph, _synthetic_source_context(raw_page)


def test_confirmed_scope_member_graph_can_prove_semantic_parent() -> None:
    case, graph, context = _scope_parent_fixture(semantic_scope_evidence=True)

    result = evaluation._score_case(case, graph, context)

    assert result["status"] == "passed"
    assert result["matched_group_ids"] == ["S1"]
    assert result["metrics"]["parent_relations"] == {
        "numerator": 0,
        "denominator": 1,
    }


def test_legacy_physical_parent_alone_cannot_prove_semantic_parent() -> None:
    case, graph, context = _scope_parent_fixture(semantic_scope_evidence=False)

    result = evaluation._score_case(case, graph, context)

    assert result["status"] == "failed"
    assert result["metrics"]["parent_relations"] == {
        "numerator": 1,
        "denominator": 1,
    }
    assert any(error["metric"] == "parent_relations" for error in result["errors"])


def _structural_list_fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    page = "材料项如下\n1. 甲材料\n2. 乙材料"
    header = _product_reference(page, 1, "材料项如下")
    first_item = _product_reference(page, 2, "1. 甲材料")
    second_item = _product_reference(page, 3, "2. 乙材料")
    expected_sources = [
        _reference(1, 1, "材料项如下"),
        _reference(1, 2, "1. 甲材料"),
        _reference(1, 3, "2. 乙材料"),
    ]
    case = {
        "case_id": "synthetic-structural-list",
        "conditions": [
            {
                "id": "A1",
                "text": "甲材料",
                "certainty": "confirmed",
                "source": [_reference(1, 2, "甲材料")],
            },
            {
                "id": "A2",
                "text": "乙材料",
                "certainty": "confirmed",
                "source": [_reference(1, 3, "乙材料")],
            },
        ],
        "expect_confirmed": {
            "conditions": ["A1", "A2"],
            "relations": [
                {
                    "type": "parent",
                    "layer": "structural_list",
                    "parent": "材料项如下",
                    "children": ["A1", "A2"],
                    "claim": "两项属于同一文本清单；不表示业务逻辑合取",
                    "source": expected_sources,
                }
            ],
        },
        "groups": [],
        "forbidden": [],
        "needs_review": [
            {
                "type": "scope",
                "status": "unresolved",
                "claim": "文本清单归属不确认业务逻辑作用域",
                "source": expected_sources,
            }
        ],
        "denominators": {
            "confirmed_atom_count": 2,
            "condition_omission": 2,
            "wrong_merge_pairs": 1,
            "wrong_split_atom_units": 2,
            "confirmed_scope_count": 0,
            "scope_membership_decisions": 0,
        },
    }
    graph = {
        "schema": "document-relations-v1",
        "document_id": "synthetic-document",
        "source_version": "synthetic-v1",
        "block_relations": [
            {
                "block_id": "header",
                "parent_relation": {
                    "status": "unresolved",
                    "target_block_ids": [],
                    "source_references": [header],
                },
                "scope_relations": [
                    {
                        "status": "unresolved",
                        "source_references": [header, first_item, second_item],
                    }
                ],
            },
            {
                "block_id": "item-1",
                "parent_relation": {
                    "status": "confirmed",
                    "layer": "structural_list",
                    "basis": "explicit_list_cue",
                    "target_block_ids": ["header"],
                    "source_references": [header, first_item],
                },
            },
            {
                "block_id": "item-2",
                "parent_relation": {
                    "status": "confirmed",
                    "layer": "structural_list",
                    "basis": "explicit_list_cue",
                    "target_block_ids": ["header"],
                    "source_references": [header, second_item],
                },
            },
        ],
        "condition_nodes": [
            {
                **_atom(
                    "n1",
                    "甲材料",
                    _product_reference(page, 2, "甲材料"),
                ),
                "source_block_ids": ["item-1"],
            },
            {
                **_atom(
                    "n2",
                    "乙材料",
                    _product_reference(page, 3, "乙材料"),
                ),
                "source_block_ids": ["item-2"],
            },
        ],
        "roots": ["n1", "n2"],
        "references": [],
        "coverage_status": "partial",
        "needs_human_review": True,
    }
    return case, graph, _synthetic_source_context(page)


def test_confirmed_structural_list_parent_does_not_require_logical_scope() -> None:
    case, graph, context = _structural_list_fixture()

    result = evaluation._score_case(case, graph, context)

    assert result["status"] == "passed"
    assert result["metrics"]["parent_relations"] == {
        "numerator": 0,
        "denominator": 1,
    }
    assert result["metrics"]["scope_membership_decisions"] == {
        "numerator": 0,
        "denominator": 0,
    }
    assert result["metrics"]["review_handling"] == {
        "numerator": 0,
        "denominator": 1,
        "raw_needs_review_items": 1,
    }
    assert not any(node["op"] in {"AND", "OR"} for node in graph["condition_nodes"])


def test_frozen_visible_enumeration_parent_is_classified_as_structural() -> None:
    relation = {
        "type": "parent",
        "parent": "以下三类中任取两类提交",
        "children": ["A1", "A2"],
        "claim": "A1、A2 是已枚举的可见条目",
    }

    assert evaluation._parent_relation_kind(relation) == "structural_list"


def test_structural_parent_rejects_missing_shared_target() -> None:
    case, graph, _ = _structural_list_fixture()
    for block in graph["block_relations"]:
        if block["block_id"].startswith("item-"):
            block["parent_relation"]["target_block_ids"] = ["missing-header"]

    relation = case["expect_confirmed"]["relations"][0]
    matched, missing = evaluation._semantic_parent_match(
        relation,
        case,
        {},
        {},
        evaluation._node_map(graph),
        {"A1": "n1", "A2": "n2"},
        graph,
    )

    assert not matched
    assert "target does not exist" in missing[0]


def test_structural_parent_rejects_a_list_quote_borrowed_by_the_child_edges() -> None:
    case, graph, _ = _structural_list_fixture()
    header = next(
        block for block in graph["block_relations"] if block["block_id"] == "header"
    )
    header["parent_relation"]["source_references"] = [
        _product_reference("材料项如下\n1. 甲材料\n2. 乙材料", 2, "1. 甲材料")
    ]

    relation = case["expect_confirmed"]["relations"][0]
    matched, missing = evaluation._semantic_parent_match(
        relation,
        case,
        {},
        {},
        evaluation._node_map(graph),
        {"A1": "n1", "A2": "n2"},
        graph,
    )

    assert not matched
    assert "target has no source-backed explicit list cue" in missing[0]


@pytest.mark.parametrize("basis", [None, "", {"claim": ""}, [None]])
def test_structural_layer_marker_without_basis_is_not_evidence(
    basis: Any,
) -> None:
    case, graph, _ = _structural_list_fixture()
    for block in graph["block_relations"]:
        if block["block_id"].startswith("item-"):
            if basis is None:
                block["parent_relation"].pop("basis")
            else:
                block["parent_relation"]["basis"] = basis

    relation = case["expect_confirmed"]["relations"][0]
    matched, _ = evaluation._semantic_parent_match(
        relation,
        case,
        {},
        {},
        evaluation._node_map(graph),
        {"A1": "n1", "A2": "n2"},
        graph,
    )

    assert not matched


def test_promoted_physical_parent_with_borrowed_list_quote_is_not_typed() -> None:
    case, graph, _ = _structural_list_fixture()
    for block in graph["block_relations"]:
        if block["block_id"].startswith("item-"):
            parent = block["parent_relation"]
            parent.pop("layer")
            parent.pop("basis")
            parent["source_references"] = [
                _product_reference(
                    "材料项如下\n1. 甲材料\n2. 乙材料", 1, "材料项如下"
                )
            ]

    relation = case["expect_confirmed"]["relations"][0]
    matched, _ = evaluation._semantic_parent_match(
        relation,
        case,
        {},
        {},
        evaluation._node_map(graph),
        {"A1": "n1", "A2": "n2"},
        graph,
    )

    assert not matched


def test_numbering_only_parent_does_not_pass_as_structural_list_membership() -> None:
    page = "2. 财务材料\n2.1 营业执照\n2.2 财务报表"
    first = _product_reference(page, 2, "2.1 营业执照")
    second = _product_reference(page, 3, "2.2 财务报表")
    parent_ref = _product_reference(page, 1, "2. 财务材料")
    relation = {
        "type": "parent",
        "parent": "2",
        "children": ["A1", "A2"],
        "claim": "编号2.1与2.2共享物理编号父级，不据此确认业务父级",
        "source": [
            _reference(1, 1, "2. 财务材料"),
            _reference(1, 2, "2.1 营业执照"),
            _reference(1, 3, "2.2 财务报表"),
        ],
    }
    case = {"expect_confirmed": {"relations": [relation]}, "groups": []}
    graph = {
        "block_relations": [
            {
                "block_id": "section-2",
                "parent_relation": {
                    "status": "unresolved",
                    "source_references": [parent_ref],
                },
            },
            {
                "block_id": "item-2-1",
                "parent_relation": {
                    "status": "confirmed",
                    "target_block_ids": ["section-2"],
                    "source_references": [parent_ref, first],
                },
            },
            {
                "block_id": "item-2-2",
                "parent_relation": {
                    "status": "confirmed",
                    "target_block_ids": ["section-2"],
                    "source_references": [parent_ref, second],
                },
            },
        ],
        "condition_nodes": [
            {**_atom("n1", "营业执照", first), "source_block_ids": ["item-2-1"]},
            {**_atom("n2", "财务报表", second), "source_block_ids": ["item-2-2"]},
        ],
    }

    assert evaluation._parent_relation_kind(relation) == "semantic"
    matched, _ = evaluation._semantic_parent_match(
        relation,
        case,
        {},
        {},
        evaluation._node_map(graph),
        {"A1": "n1", "A2": "n2"},
        graph,
    )
    assert not matched


def _explicit_semantic_parent_fixture() -> (
    tuple[dict[str, Any], dict[str, Any], dict[str, Any]]
):
    page = "提交主体材料\n该材料须附盖章副本"
    parent_ref = _product_reference(page, 1, "提交主体材料")
    child_ref = _product_reference(page, 2, "盖章副本")
    case = {
        "case_id": "synthetic-explicit-semantic-parent",
        "conditions": [
            {
                "id": "A1",
                "text": "提交主体材料",
                "certainty": "confirmed",
                "source": [_reference(1, 1, "提交主体材料")],
            },
            {
                "id": "A2",
                "text": "提交盖章副本",
                "certainty": "confirmed",
                "source": [_reference(1, 2, "盖章副本")],
            },
        ],
        "expect_confirmed": {
            "conditions": ["A1", "A2"],
            "relations": [
                {
                    "type": "parent",
                    "parent": "A1 主体材料",
                    "children": ["A2"],
                    "source": [
                        _reference(1, 1, "主体材料"),
                        _reference(1, 2, "盖章副本"),
                    ],
                }
            ],
        },
        "groups": [],
        "forbidden": [],
        "needs_review": [],
        "denominators": {
            "confirmed_atom_count": 2,
            "condition_omission": 2,
            "wrong_merge_pairs": 1,
            "wrong_split_atom_units": 2,
            "confirmed_scope_count": 0,
            "scope_membership_decisions": 0,
        },
    }
    parent = _atom("n1", "提交主体材料", parent_ref)
    child = _atom("n2", "提交盖章副本", child_ref)
    child["parent_relations"] = [
        {
            "status": "confirmed",
            "layer": "attribute_parent",
            "basis": "explicit_attribute_reference",
            "target_node_ids": ["n1"],
            "source_references": [parent_ref, child_ref],
        }
    ]
    graph = {
        "schema": "document-relations-v1",
        "document_id": "synthetic-document",
        "source_version": "synthetic-v1",
        "block_relations": [],
        "condition_nodes": [parent, child],
        "roots": ["n1", "n2"],
        "references": [],
        "coverage_status": "partial",
        "needs_human_review": False,
    }
    return case, graph, _synthetic_source_context(page)


def test_typed_explicit_semantic_parent_with_source_is_confirmed() -> None:
    case, graph, context = _explicit_semantic_parent_fixture()

    result = evaluation._score_case(case, graph, context)

    assert result["status"] == "passed"
    assert result["metrics"]["parent_relations"] == {
        "numerator": 0,
        "denominator": 1,
    }


@pytest.mark.parametrize("failure", ["missing_basis", "wrong_source"])
def test_explicit_semantic_parent_rejects_missing_or_wrong_evidence(
    failure: str,
) -> None:
    case, graph, context = _explicit_semantic_parent_fixture()
    parent = graph["condition_nodes"][1]["parent_relations"][0]
    if failure == "missing_basis":
        parent.pop("basis")
    else:
        parent["source_references"] = [
            _product_reference(context["pages"][0], 2, "盖章副本")
        ]

    result = evaluation._score_case(case, graph, context)

    assert result["status"] == "failed"
    assert result["metrics"]["parent_relations"] == {
        "numerator": 1,
        "denominator": 1,
    }


@pytest.mark.parametrize(
    "scope_kind", ["attribute_scope", "contextual_scope_no_flat_operator"]
)
def test_nonlogical_scope_kinds_do_not_require_fabricated_and(
    scope_kind: str,
) -> None:
    case, graph, context = _scope_parent_fixture(semantic_scope_evidence=True)
    case["groups"][0]["operator"] = scope_kind

    result = evaluation._score_case(case, graph, context)

    assert result["status"] == "passed"
    assert result["matched_group_ids"] == ["S1"]
    assert not any(
        node["op"] in {"AND", "OR"} for node in graph["condition_nodes"]
    )


def test_flattened_tree_fails_even_when_leaf_atoms_are_present() -> None:
    case = _synthetic_case()
    graph = _synthetic_graph()
    graph["condition_nodes"] = [
        node for node in graph["condition_nodes"] if node["node_id"] not in {"g1", "g2"}
    ]
    root = next(node for node in graph["condition_nodes"] if node["node_id"] == "g0")
    root["children"] = ["n1", "n2", "n3", "n4"]
    root["scope_relation"]["target_node_ids"] = ["n1", "n2", "n3", "n4"]

    result = evaluation._score_case(case, graph, _synthetic_source_context())

    assert result["status"] == "failed"
    assert any(
        error["metric"] == "group_structure" and error.get("expected_group_id") == "S0"
        for error in result["errors"]
    )


def test_all_candidate_output_fails_confirmed_positive_expectations() -> None:
    graph = _synthetic_graph()
    for node in graph["condition_nodes"]:
        node["status"] = "candidate"
        if isinstance(node.get("operator_relation"), dict):
            node["operator_relation"]["status"] = "candidate"
        if isinstance(node.get("scope_relation"), dict):
            node["scope_relation"]["status"] = "candidate"

    result = evaluation._score_case(
        _synthetic_case(), graph, _synthetic_source_context()
    )

    assert result["status"] == "failed"
    assert any(error["metric"] == "condition_status" for error in result["errors"])
    assert result["matched_group_ids"] == []
    assert all(
        0 <= metric["numerator"] <= metric["denominator"]
        for metric in result["metrics"].values()
    )
    assert result["event_counts"]["error_events"] >= sum(
        metric["numerator"] for metric in result["metrics"].values()
    )


def test_candidate_atom_maps_from_literal_source_beneath_oracle_explanation() -> None:
    case, graph, context = _candidate_literal_fixture()

    result = evaluation._score_case(case, graph, context)

    assert result["status"] == "passed"
    assert result["matched_atom_ids"] == ["A3"]
    assert result["metrics"]["review_handling"] == {
        "numerator": 0,
        "denominator": 1,
        "raw_needs_review_items": 1,
    }


def test_candidate_literal_match_rejects_a_different_quote_on_the_same_line() -> None:
    raw_page = "项目联系人表一份。联系人签字。"
    wrong_quote = _product_reference(raw_page, 1, "联系人签字。")
    case, graph, context = _candidate_literal_fixture(
        page_text=raw_page,
        actual_ref=wrong_quote,
    )

    result = evaluation._score_case(case, graph, context)

    assert result["status"] == "failed"
    assert result["matched_atom_ids"] == []
    assert result["metrics"]["source_invalid"]["numerator"] == 0
    assert result["metrics"]["review_handling"]["numerator"] == 1


def test_candidate_literal_match_rejects_the_same_quote_at_another_line() -> None:
    quote = "项目联系人表一份。"
    raw_page = f"{quote}\n{quote}"
    wrong_line = _product_reference(raw_page, 2, quote)
    case, graph, context = _candidate_literal_fixture(
        page_text=raw_page,
        actual_ref=wrong_line,
    )

    result = evaluation._score_case(case, graph, context)

    assert result["status"] == "failed"
    assert result["matched_atom_ids"] == []
    assert result["metrics"]["source_invalid"]["numerator"] == 0
    assert result["metrics"]["review_handling"]["numerator"] == 1


def test_candidate_literal_match_rejects_invalid_raw_character_bounds() -> None:
    quote = "项目联系人表一份。"
    raw_page = f"{quote}附注"
    invalid_ref = _product_reference(raw_page, 1, quote)
    invalid_ref["char_start"] += 1
    invalid_ref["char_end"] += 1
    case, graph, context = _candidate_literal_fixture(
        page_text=raw_page,
        actual_ref=invalid_ref,
    )

    result = evaluation._score_case(case, graph, context)

    assert result["status"] == "failed"
    assert result["matched_atom_ids"] == []
    assert result["metrics"]["source_invalid"]["numerator"] == 1
    assert result["metrics"]["review_handling"]["numerator"] == 1


def test_candidate_literal_match_rejects_unrelated_actual_text() -> None:
    case, graph, context = _candidate_literal_fixture(actual_text="电子签章方式")

    result = evaluation._score_case(case, graph, context)

    assert result["status"] == "failed"
    assert result["matched_atom_ids"] == []
    assert result["metrics"]["source_invalid"]["numerator"] == 0
    assert result["metrics"]["review_handling"]["numerator"] == 1


def test_candidate_source_literal_fallback_does_not_apply_to_confirmed_atoms() -> None:
    case, graph, context = _candidate_literal_fixture(actual_status="confirmed")
    case["conditions"][0]["certainty"] = "confirmed"
    case["expect_confirmed"]["conditions"] = ["A3"]
    case["needs_review"] = []
    case["denominators"].update(
        {
            "confirmed_atom_count": 1,
            "condition_omission": 1,
            "wrong_split_atom_units": 1,
        }
    )

    result = evaluation._score_case(case, graph, context)

    assert result["status"] == "failed"
    assert result["matched_atom_ids"] == []
    assert result["metrics"]["condition_omission"] == {
        "numerator": 1,
        "denominator": 1,
    }


def test_candidate_literal_match_does_not_override_actual_confirmed_status() -> None:
    case, graph, context = _candidate_literal_fixture(actual_status="confirmed")

    result = evaluation._score_case(case, graph, context)

    assert result["status"] == "failed"
    assert result["matched_atom_ids"] == ["A3"]
    assert result["metrics"]["review_handling"]["numerator"] == 1


def test_one_candidate_node_cannot_match_two_same_source_candidate_atoms() -> None:
    case, graph, context = _candidate_literal_fixture()
    second = deepcopy(case["conditions"][0])
    second["id"] = "A4"
    second["text"] = "可能要求联系人签字；对象待确认"
    case["conditions"].append(second)
    case["needs_review"].append(
        {
            "type": "condition",
            "condition_id": "A4",
            "status": "candidate",
            "source": deepcopy(second["source"]),
        }
    )

    result = evaluation._score_case(case, graph, context)

    assert result["status"] == "failed"
    assert len(result["matched_atom_ids"]) == 1
    assert result["metrics"]["review_handling"] == {
        "numerator": 1,
        "denominator": 2,
        "raw_needs_review_items": 2,
    }


def test_group_structure_ratio_counts_unique_expected_and_or_units() -> None:
    errors = [
        {"metric": "group_structure", "expected_group_id": "S1"},
        {"metric": "group_structure", "expected_group_id": "S1"},
        {"metric": "group_structure", "expected_group_id": "S-review"},
    ]

    failed_units = evaluation._unique_group_failures(
        errors, "group_structure", {"S1", "S2"}
    )

    assert failed_units == {"S1"}
    assert len(failed_units) <= 2


def test_ratio_metric_bounds_reject_numerator_above_denominator() -> None:
    with pytest.raises(ValueError, match="outside its denominator"):
        evaluation._assert_ratio_metric_bounds(
            {"operator_group_structure": {"numerator": 17, "denominator": 14}}
        )


def test_one_confirmed_atom_cannot_collapse_two_expected_conditions() -> None:
    case = _synthetic_case()
    case["conditions"] = case["conditions"][:2]
    case["expect_confirmed"]["conditions"] = ["A1", "A2"]
    case["conditions"][0]["source"] = _reference(1, 1, "甲材料")
    case["conditions"][1]["source"] = _reference(1, 1, "乙材料")
    case["expect_confirmed"]["relations"] = []
    case["groups"] = []
    case["denominators"] = {
        "confirmed_atom_count": 2,
        "condition_omission": 2,
        "wrong_merge_pairs": 1,
        "wrong_split_atom_units": 2,
        "confirmed_scope_count": 0,
        "scope_membership_decisions": 0,
    }
    page_text = "甲材料和乙材料"
    source = _product_reference(page_text, 1, "甲材料和乙材料")
    graph = {
        "condition_nodes": [_atom("merged", "甲材料和乙材料", source)],
        "block_relations": [],
        "references": [],
    }

    result = evaluation._score_case(case, graph, _synthetic_source_context(page_text))

    assert result["status"] == "failed"
    assert result["metrics"]["wrong_merge_pairs"]["numerator"] == 1
    assert result["metrics"]["condition_omission"] == {
        "numerator": 1,
        "denominator": 2,
    }
    assert result["metrics"]["wrong_merge_pairs"]["denominator"] == 1


@pytest.mark.parametrize(
    ("claim", "expected"),
    [
        ("不得因分页而把明确承接的条件排除在该组之外", "require_members"),
        ("不得忽略组号而把四项并成一个组", "prohibit_merge"),
        ("严格禁止把可见材料确认为完整候选集", "prohibit_confirmation"),
        ("严格禁止确认三项共享一个业务逻辑作用域", "prohibit_confirmation"),
    ],
)
def test_forbidden_scope_direction_uses_claim_semantics(
    claim: str, expected: str
) -> None:
    assert evaluation._classify_forbidden_scope(claim) == expected


def test_forbidden_flattened_scope_allows_nested_or_groups_under_and() -> None:
    case = _synthetic_case()
    case["forbidden"] = [
        {
            "type": "scope",
            "claim": "不得把四项并成一个全提交组",
            "members": ["A1", "A2", "A3", "A4"],
        }
    ]
    graph = _synthetic_graph()

    result = evaluation._score_case(case, graph, _synthetic_source_context())

    assert result["status"] == "passed"
    assert result["metrics"]["forbidden_claims"] == {
        "numerator": 0,
        "denominator": 1,
    }


@pytest.mark.parametrize("operator", ["AND", "OR"])
def test_forbidden_flattened_scope_rejects_flat_direct_children(
    operator: str,
) -> None:
    case = _synthetic_case()
    case["forbidden"] = [
        {
            "type": "scope",
            "claim": "不得把四项并成一个全提交组",
            "members": ["A1", "A2", "A3", "A4"],
        }
    ]
    graph = _synthetic_graph()
    graph["condition_nodes"] = [
        node for node in graph["condition_nodes"] if node["node_id"] not in {"g1", "g2"}
    ]
    flat_group = next(
        node for node in graph["condition_nodes"] if node["node_id"] == "g0"
    )
    flat_group["op"] = operator
    flat_group["children"] = ["n1", "n2", "n3", "n4"]
    flat_group["scope_relation"]["target_node_ids"] = ["n1", "n2", "n3", "n4"]

    result = evaluation._score_case(case, graph, _synthetic_source_context())

    assert result["status"] == "failed"
    assert result["metrics"]["forbidden_claims"] == {
        "numerator": 1,
        "denominator": 1,
    }
    assert any(
        error["metric"] == "forbidden_claims"
        and error["reason"]
        == "forbidden scope members were flattened into direct children"
        for error in result["errors"]
    )


def test_forbidden_numeric_condition_does_not_ban_a_legal_budget_atom() -> None:
    raw_page = "预算金额为1.10万元"
    case = {
        "case_id": "synthetic-budget",
        "conditions": [
            {
                "id": "A1",
                "text": "预算金额为1.10万元",
                "certainty": "confirmed",
                "source": _reference(1, 1, raw_page),
            }
        ],
        "expect_confirmed": {"conditions": ["A1"], "relations": []},
        "groups": [],
        "forbidden": [
            {
                "type": "condition",
                "claim": "严格禁止把1.10万元识别成编号1.10的材料条件",
                "source": [_reference(1, 1, raw_page)],
            }
        ],
        "needs_review": [],
        "denominators": {
            "confirmed_atom_count": 1,
            "condition_omission": 1,
            "wrong_merge_pairs": 0,
            "wrong_split_atom_units": 1,
            "confirmed_scope_count": 0,
            "scope_membership_decisions": 0,
        },
    }
    legal_atom = _atom(
        "budget",
        "预算金额为1.10万元",
        _product_reference(raw_page, 1, raw_page),
    )
    graph = {
        "condition_nodes": [legal_atom],
        "block_relations": [],
        "references": [],
    }
    context = _synthetic_source_context(raw_page)

    assert evaluation._score_case(case, graph, context)["status"] == "passed"

    extra_material_atom = _atom(
        "misread-number",
        "编号1.10材料证明",
        _product_reference(raw_page, 1, raw_page),
    )
    graph["condition_nodes"].append(extra_material_atom)
    result = evaluation._score_case(case, graph, context)

    assert result["status"] == "failed"
    assert any(
        error["metric"] == "forbidden_claims"
        and error["reason"] == "forbidden candidate condition was confirmed"
        for error in result["errors"]
    )


def test_not_run_is_distinct_from_runtime_failure_and_executed_graph() -> None:
    assert evaluation._relation_execution_state(None)[:2] == (
        "not_run",
        "tender-decomposition step absent",
    )
    not_run = {
        "status": "success",
        "data": {"relation_analysis": {"status": "not_run"}},
    }
    assert evaluation._relation_execution_state(not_run)[0] == "not_run"
    failed = {"status": "error", "data": {}}
    assert evaluation._relation_execution_state(failed)[0] == "failed"
    executed = {
        "status": "success",
        "data": {
            "relation_analysis": {"status": "executed"},
            "document_relations": [
                {
                    "schema": "document-relations-v1",
                    "condition_nodes": [],
                    "block_relations": [],
                }
            ],
        },
    }
    assert evaluation._relation_execution_state(executed)[0] == "executed"


@pytest.mark.parametrize(
    ("reason", "expected_state"),
    [
        ("builder_failed", "failed"),
        ("no_document_structures", "not_run"),
    ],
)
def test_unprocessed_structure_reason_controls_execution_classification(
    reason: str, expected_state: str
) -> None:
    decomposition_step = {
        "status": "success",
        "data": {
            "relation_analysis": {
                "status": "not_run",
                "executed": False,
                "not_run": True,
                "unprocessed_structures": {"reason": reason},
            }
        },
    }

    state, detail, data = evaluation._relation_execution_state(decomposition_step)

    assert state == expected_state
    assert data == decomposition_step["data"]
    if reason == "builder_failed":
        assert "builder failed" in detail
    else:
        assert detail == "relation_analysis explicitly reports not_run"


def test_source_reference_matching_requires_page_line_and_quote() -> None:
    expected = _reference(2, 3, "精确引文")
    actual = {
        "page_number": 2,
        "line_number": 3,
        "quote": "这是精确引文的原文片段",
    }
    assert evaluation._reference_matches(actual, expected)
    assert not evaluation._reference_matches(_reference(2, 4, "精确引文"), expected)
    assert not evaluation._reference_matches(_reference(2, 3, "不同引文"), expected)


def test_reference_inventory_keeps_196_occurrences_and_88_unique() -> None:
    unique_refs = [_reference(1, index + 1, f"引用{index:02d}") for index in range(88)]
    occurrences = [unique_refs[index % len(unique_refs)] for index in range(196)]

    all_refs, unique = evaluation._reference_inventory(occurrences)

    assert len(all_refs) == 196
    assert len(unique) == 88


@pytest.mark.parametrize(
    ("changes", "expected_reason"),
    [
        (
            {"quote": "伪造引文"},
            "raw character offsets do not select the exact quote on one line",
        ),
        (
            {"char_end": 100},
            "raw character offsets are outside the registered page",
        ),
        ({"source_version": "other-v"}, "source version mismatch"),
        (
            {"line_number": 2},
            "line_number disagrees with the char_start-derived line",
        ),
    ],
)
def test_actual_source_reference_tampering_is_rejected(
    changes: dict[str, Any], expected_reason: str
) -> None:
    raw_page = "原文引句\n第二行"
    reference = _product_reference(raw_page, 1, "原文引句")
    reference.update(changes)
    graph = {
        "condition_nodes": [
            {"node_id": "n1", "op": "ATOM", "source_references": [reference]}
        ],
        "block_relations": [],
        "references": [],
    }

    checked = evaluation._validate_graph_source_references(
        graph,
        {
            "document_id": "synthetic-document",
            "source_version": "synthetic-v1",
            "pages": [raw_page],
        },
    )

    assert checked["invalid_references"] == 1
    assert expected_reason in {failure["reason"] for failure in checked["failures"]}
    shadow_reference = checked["normalized_graph"]["condition_nodes"][0][
        "source_references"
    ][0]
    assert shadow_reference["_raw_coordinate_valid"] is False


def test_real_registry_txt_accepts_char_only_source_references(tmp_path: Path) -> None:
    raw_page = "公开合成TXT标题\n必须提交许可证明"
    input_path = tmp_path / "public-source-contract.txt"
    input_path.write_bytes(raw_page.encode("utf-8"))
    content = input_path.read_bytes()

    registry = evaluation.ProjectFileRegistry()
    registration = registry.register(
        project_id="public-source-contract",
        file_name=input_path.name,
        file_role="tender",
        content=content,
    )
    document_id = registration.file.file_id
    source_version = registry.file_version_token(document_id)
    actual_reference = _char_reference(
        raw_page,
        2,
        "许可证明",
        document_id=document_id,
        source_version=source_version,
    )
    graph = {
        "schema": "document-relations-v1",
        "document_id": document_id,
        "source_version": source_version,
        "block_relations": [],
        "condition_nodes": [_atom("n1", "许可证明", actual_reference)],
        "roots": ["n1"],
        "references": [],
        "coverage_status": "partial",
        "needs_human_review": False,
    }
    case = {
        "case_id": "registry-char-reference-contract",
        "conditions": [
            {
                "id": "A1",
                "text": "许可证明",
                "certainty": "confirmed",
                "source": [_reference(1, 2, "许可证明")],
            }
        ],
        "expect_confirmed": {"conditions": ["A1"], "relations": []},
        "groups": [],
        "forbidden": [],
        "needs_review": [],
        "denominators": {
            "confirmed_atom_count": 1,
            "condition_omission": 1,
            "wrong_merge_pairs": 0,
            "wrong_split_atom_units": 1,
            "confirmed_scope_count": 0,
            "scope_membership_decisions": 0,
        },
    }
    context = {
        "document_id": document_id,
        "source_version": source_version,
        "pages": raw_page.split(evaluation.BOUNDARY),
        "raw_input_sha256": evaluation._sha256(content),
    }

    result = evaluation._score_case(case, graph, context)

    assert result["status"] == "passed"
    assert result["actual_source_validation"]["invalid_references"] == 0
    assert result["actual_source_validation"]["line_numbers_derived"] == 1
    assert "line_number" not in actual_reference

    checked = evaluation._validate_graph_source_references(graph, context)
    shadow_reference = checked["normalized_graph"]["condition_nodes"][0][
        "source_references"
    ][0]
    assert shadow_reference["line_number"] == 2
    assert shadow_reference["_raw_coordinate_valid"] is True
    assert "line_number" not in graph["condition_nodes"][0]["source_references"][0]


@pytest.mark.parametrize(
    ("changes", "expected_reason"),
    [
        (
            {"line_number": 1},
            "line_number disagrees with the char_start-derived line",
        ),
        (
            {"quote": "伪造引文"},
            "raw character offsets do not select the exact quote on one line",
        ),
        (
            {"char_end": 100},
            "raw character offsets are outside the registered page",
        ),
        ({"source_version": "wrong-version"}, "source version mismatch"),
    ],
)
def test_char_only_reference_tampering_is_rejected(
    changes: dict[str, Any], expected_reason: str
) -> None:
    raw_page = "首行\n目标引文\n末行"
    reference = _char_reference(raw_page, 2, "目标引文")
    reference.update(changes)
    graph = {
        "condition_nodes": [
            {"node_id": "n1", "op": "ATOM", "source_references": [reference]}
        ],
        "block_relations": [],
        "references": [],
    }

    checked = evaluation._validate_graph_source_references(
        graph,
        {
            "document_id": "synthetic-document",
            "source_version": "synthetic-v1",
            "pages": [raw_page],
        },
    )

    assert checked["invalid_references"] == 1
    assert expected_reason in {failure["reason"] for failure in checked["failures"]}


def test_invalid_actual_source_reference_fails_scored_case() -> None:
    graph = _synthetic_graph()
    graph["condition_nodes"][0]["source_references"][0]["quote"] = "假引文"

    result = evaluation._score_case(
        _synthetic_case(), graph, _synthetic_source_context()
    )

    assert result["status"] == "failed"
    assert result["metrics"]["source_invalid"]["numerator"] == 1
    assert result["metrics"]["source_invalid"]["denominator"] > 0


def test_replay_payload_preserves_raw_graph_and_registered_source_pages() -> None:
    raw_page = "第一行\n目标引文"
    reference = _char_reference(raw_page, 2, "目标引文")
    graph = {
        "document_id": "synthetic-document",
        "source_version": "synthetic-v1",
        "condition_nodes": [
            {"node_id": "n1", "op": "ATOM", "source_references": [reference]}
        ],
    }
    runtime = {
        "graph": graph,
        "registered_input_sha256": "registered-hash",
        "source_context": {
            **_synthetic_source_context(raw_page),
            "raw_input_sha256": "registered-hash",
        },
    }

    payload = evaluation._runtime_replay_material(runtime)

    assert payload["actual_graph"] == graph
    assert (
        "line_number"
        not in payload["actual_graph"]["condition_nodes"][0]["source_references"][0]
    )
    assert payload["source_context"]["pages"] == [raw_page]
    assert payload["source_context"]["registered_input_sha256"] == "registered-hash"
    assert payload["source_context"]["page_separator"] == evaluation.BOUNDARY


def test_required_group_accepts_atom_or_confirmed_unary_and() -> None:
    raw_page = "单项材料 必须提交单项材料"
    condition = {
        "id": "A1",
        "text": "单项材料",
        "certainty": "confirmed",
        "source": _reference(1, 1, "单项材料"),
    }
    case = {
        "case_id": "synthetic-required",
        "conditions": [condition],
        "expect_confirmed": {"conditions": ["A1"], "relations": []},
        "groups": [
            {
                "id": "S1",
                "status": "confirmed",
                "operator": "REQUIRED",
                "members": ["A1"],
                "boundary_basis": [_reference(1, 1, "必须提交单项材料")],
            }
        ],
        "forbidden": [],
        "needs_review": [],
        "denominators": {
            "confirmed_atom_count": 1,
            "condition_omission": 1,
            "wrong_merge_pairs": 0,
            "wrong_split_atom_units": 1,
            "confirmed_scope_count": 1,
            "scope_membership_decisions": 1,
        },
    }
    atom_ref = _product_reference(raw_page, 1, "单项材料")
    unary_ref = _product_reference(raw_page, 1, "必须提交单项材料")
    graph = {
        "condition_nodes": [
            _atom("n1", "单项材料", atom_ref),
            _group("g1", "AND", ["n1"], unary_ref),
        ],
        "block_relations": [],
        "references": [],
    }
    context = _synthetic_source_context(raw_page)
    group_map, _, errors = evaluation._match_groups(case, graph, {"A1": "n1"})

    assert errors == []
    assert group_map == {"S1": "g1"}
    assert evaluation._score_case(case, graph, context)["status"] == "passed"

    atom_only = deepcopy(graph)
    atom_only["condition_nodes"] = atom_only["condition_nodes"][:1]
    atom_group_map, _, atom_errors = evaluation._match_groups(
        case, atom_only, {"A1": "n1"}
    )
    assert atom_errors == []
    assert atom_group_map == {"S1": "n1"}


def test_cli_refuses_to_score_without_main_reviewer_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_run(_: Path) -> dict[str, Any]:
        raise AssertionError("scoring must not start without authorization")

    monkeypatch.setattr(evaluation, "run_evaluation", unexpected_run)
    with pytest.raises(SystemExit) as error:
        evaluation.main(
            [
                "--bundle",
                str(tmp_path / "bundle"),
                "--output",
                str(tmp_path / "report.json"),
            ]
        )
    assert error.value.code == 2


def test_scoring_fixtures_are_local_synthetic_objects() -> None:
    case = _synthetic_case()
    copied = deepcopy(case)
    assert copied == case
    assert copied["case_id"] == "synthetic-nested"


def test_evaluator_version_and_report_schema_are_frozen() -> None:
    assert evaluation.EVALUATOR_VERSION == "1.0.3"
    assert evaluation.REPORT_SCHEMA == "document-relations-acceptance-eval-v1"
