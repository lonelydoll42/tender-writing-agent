from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.core.files import ProjectFileRegistry
from qiaowenshu_agent.core.runtime import AgentRuntime
from qiaowenshu_agent.skills import build_default_registry


_PUBLIC_NESTED_CASES = (
    {
        "case_id": "case-03",
        "text": (
            "两组要求均须满足。\n"
            "第一组任选其一：营业执照复印件；资质证书。\n"
            "第二组必须提交：项目负责人授权书。"
        ),
        "atoms": {
            "A1": "营业执照复印件",
            "A2": "资质证书",
            "A3": "项目负责人授权书",
        },
        "inner_groups": (
            {
                "id": "S1",
                "operator": "OR",
                "members": ("A1", "A2"),
                "operator_cue": "任选其一",
                "scope_cue": "第一组",
            },
        ),
        "root_children": ("S1", "A3"),
        "root_operator_cue": "均须满足",
        "root_scope_cue": "两",
        "root_scope_member_cues": ("第一组", "第二组"),
    },
    {
        "case_id": "case-11",
        "text": (
            "以下两组材料均须提交，但每组只需择一：\n"
            "第一组：（1）近两年1.9号表；（2）近两年1.10号表。\n"
            "第二组：（1）近三年1.9号表；（2）近三年1.10号表。"
        ),
        "atoms": {
            "A1": "近两年1.9号表",
            "A2": "近两年1.10号表",
            "A3": "近三年1.9号表",
            "A4": "近三年1.10号表",
        },
        "inner_groups": (
            {
                "id": "S1",
                "operator": "OR",
                "members": ("A1", "A2"),
                "operator_cue": "每组只需择一",
                "scope_cue": "第一组",
            },
            {
                "id": "S2",
                "operator": "OR",
                "members": ("A3", "A4"),
                "operator_cue": "每组只需择一",
                "scope_cue": "第二组",
            },
        ),
        "root_children": ("S1", "S2"),
        "root_operator_cue": "均须提交",
        "root_scope_cue": "两",
        "root_scope_member_cues": ("第一组", "第二组"),
    },
)


def _run_registered_text(
    case_id: str,
    text: str,
) -> tuple[dict[str, Any], dict[str, Any], Mapping[str, Any], str, str]:
    project_id = f"nested-relations-{case_id}"
    registry = ProjectFileRegistry()
    registration = registry.register(
        project_id=project_id,
        file_name=f"{case_id}.txt",
        file_role="tender",
        content=text.encode("utf-8"),
    )
    document_id = registration.file.file_id
    source_version = registry.file_version_token(document_id)
    runtime = AgentRuntime(
        build_default_registry(file_registry=registry),
        services={"file_registry": registry},
    )
    result = asyncio.run(
        runtime.run(
            SkillRequest.create(
                {
                    "project_id": project_id,
                    "file_ids": [document_id],
                    "task": "分析招标文件",
                }
            )
        )
    )

    intake = next(step for step in result.steps if step.skill_name == "tender-intake")
    decomposition = next(
        step for step in result.steps if step.skill_name == "tender-decomposition"
    )
    structure = intake.result.data["document_structures"][0]
    analysis = decomposition.result.data["relation_analysis"]
    graphs = decomposition.result.data["document_relations"]
    assert isinstance(graphs, list) and len(graphs) == 1, analysis
    graph = graphs[0]

    assert result.status in {"success", "partial"}
    assert graph["document_id"] == document_id
    assert graph["source_version"] == source_version
    assert graph["source_identity_status"] == "registry_verified"
    assert analysis["status"] == "executed"
    assert analysis["source_identity_status"] == "registry_verified"
    assert analysis["source_reference_status"] == "verified"
    assert analysis["coverage_status"] == "partial"
    assert analysis["needs_human_review"] is True
    return graph, analysis, structure, document_id, source_version


def _nodes(graph: Mapping[str, Any]) -> list[dict[str, Any]]:
    nodes = graph.get("condition_nodes") or []
    assert isinstance(nodes, list)
    return [node for node in nodes if isinstance(node, dict)]


def _atom(graph: Mapping[str, Any], marker: str) -> dict[str, Any]:
    matches = [
        node
        for node in _nodes(graph)
        if node.get("op") == "ATOM" and marker in str(node.get("text") or "")
    ]
    assert len(matches) == 1, marker
    assert matches[0]["status"] == "confirmed", marker
    assert matches[0].get("source_references"), marker
    return matches[0]


def _confirmed_group(
    graph: Mapping[str, Any],
    operator: str,
    direct_children: list[str],
) -> dict[str, Any]:
    expected = set(direct_children)
    matches = [
        node
        for node in _nodes(graph)
        if node.get("op") == operator
        and set(node.get("children") or []) == expected
        and len(node.get("children") or []) == len(expected)
    ]
    assert len(matches) == 1, (operator, direct_children)
    group = matches[0]
    assert group["status"] == "confirmed"
    assert group["operator_relation"]["status"] == "confirmed"
    assert group["scope_relation"]["status"] == "confirmed"
    assert set(group["scope_relation"]["target_node_ids"]) == expected
    assert len(group["scope_relation"]["target_node_ids"]) == len(expected)
    return group


def _assert_channel_cites(
    group: Mapping[str, Any],
    channel_name: str,
    cue: str,
) -> None:
    relation = group.get(channel_name)
    assert isinstance(relation, Mapping)
    reference_field = (
        "scope_source_references"
        if channel_name == "scope_relation"
        else "source_references"
    )
    references = relation.get(reference_field)
    assert isinstance(references, list) and references
    assert any(
        (
            str(reference.get("quote") or "") == cue
            if channel_name == "scope_relation"
            else cue in str(reference.get("quote") or "")
        )
        for reference in references
        if isinstance(reference, Mapping)
    )


def _assert_child_parent_evidence(
    parent: Mapping[str, Any],
    nodes: Mapping[str, Mapping[str, Any]],
    *,
    operator_cue: str,
    scope_cue: str,
) -> None:
    parent_id = str(parent["node_id"])
    scope = parent["scope_relation"]
    boundary_references = scope.get("boundary_source_references")
    assert isinstance(boundary_references, list) and boundary_references
    boundary_quotes = {
        str(reference["quote"])
        for reference in boundary_references
        if isinstance(reference, Mapping) and reference.get("quote")
    }
    assert boundary_quotes
    parent_quotes = set(_quotes(parent))
    assert boundary_quotes <= parent_quotes

    for child_id in parent["children"]:
        child = nodes[child_id]
        edges = [
            relation
            for relation in child.get("parent_relations", [])
            if isinstance(relation, Mapping)
            and relation.get("layer") == "semantic_parent"
            and relation.get("target_node_ids") == [parent_id]
        ]
        assert len(edges) == 1
        edge = edges[0]
        assert edge["status"] == "confirmed"
        edge_references = edge.get("source_references")
        assert isinstance(edge_references, list) and edge_references
        edge_keys = {
            (
                reference.get("document_id"),
                reference.get("source_version"),
                reference.get("page"),
                reference.get("char_start"),
                reference.get("char_end"),
                reference.get("quote"),
            )
            for reference in edge.get("source_references", [])
            if isinstance(reference, Mapping)
        }
        parent_scope = parent["scope_relation"]
        for reference_field in ("source_references", "boundary_source_references"):
            parent_references = parent_scope.get(reference_field)
            assert isinstance(parent_references, list) and parent_references
            parent_keys = {
                (
                    reference.get("document_id"),
                    reference.get("source_version"),
                    reference.get("page"),
                    reference.get("char_start"),
                    reference.get("char_end"),
                    reference.get("quote"),
                )
                for reference in parent_references
                if isinstance(reference, Mapping)
            }
            assert parent_keys <= edge_keys

        edge_quotes = {
            str(reference.get("quote") or "")
            for reference in edge_references
            if isinstance(reference, Mapping) and reference.get("quote")
        }
        child_quotes = {
            str(reference["quote"])
            for reference in child.get("source_references", [])
            if isinstance(reference, Mapping) and reference.get("quote")
        }
        assert child_quotes <= edge_quotes
        assert any(scope_cue in quote for quote in edge_quotes)
        assert any(operator_cue in quote for quote in edge_quotes)


def _iter_references(value: Any):
    if isinstance(value, Mapping):
        if {"page", "char_start", "char_end", "quote"} <= value.keys():
            yield value
        for child in value.values():
            yield from _iter_references(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _iter_references(child)


def _assert_exact_registry_references(
    graph: Mapping[str, Any],
    structure: Mapping[str, Any],
    document_id: str,
    source_version: str,
) -> None:
    pages = {page["page_number"]: page["raw_text"] for page in structure["pages"]}
    references = list(_iter_references(graph))
    assert references
    for reference in references:
        assert reference.get("document_id") == document_id
        assert reference.get("source_version") == source_version
        page_number = reference["page"]
        start = reference["char_start"]
        end = reference["char_end"]
        quote = reference["quote"]
        assert isinstance(page_number, int) and not isinstance(page_number, bool)
        assert isinstance(start, int) and not isinstance(start, bool)
        assert isinstance(end, int) and not isinstance(end, bool)
        assert isinstance(quote, str) and quote
        raw_text = pages[page_number]
        assert 0 <= start < end <= len(raw_text)
        assert raw_text[start:end] == quote


@pytest.mark.parametrize(
    "case",
    _PUBLIC_NESTED_CASES,
    ids=lambda case: case["case_id"],
)
def test_public_nested_cases_keep_oracle_tree_and_registry_sources(
    case: Mapping[str, Any],
) -> None:
    graph, _analysis, structure, document_id, source_version = _run_registered_text(
        case["case_id"], case["text"]
    )
    atoms = {atom_id: _atom(graph, marker) for atom_id, marker in case["atoms"].items()}
    atom_ids = {node["node_id"] for node in atoms.values()}
    groups: dict[str, dict[str, Any]] = {}

    for spec in case["inner_groups"]:
        group = _confirmed_group(
            graph,
            spec["operator"],
            [atoms[member]["node_id"] for member in spec["members"]],
        )
        _assert_channel_cites(group, "operator_relation", spec["operator_cue"])
        _assert_channel_cites(group, "scope_relation", spec["scope_cue"])
        groups[spec["id"]] = group

    nodes = {node["node_id"]: node for node in _nodes(graph)}
    for spec in case["inner_groups"]:
        _assert_child_parent_evidence(
            groups[spec["id"]],
            nodes,
            operator_cue=spec["operator_cue"],
            scope_cue=spec["scope_cue"],
        )

    root = _confirmed_group(
        graph,
        "AND",
        [
            groups[child]["node_id"] if child in groups else atoms[child]["node_id"]
            for child in case["root_children"]
        ],
    )
    _assert_channel_cites(root, "operator_relation", case["root_operator_cue"])
    _assert_channel_cites(root, "scope_relation", case["root_scope_cue"])
    root_scope_quotes = {
        reference["quote"]
        for reference in root["scope_relation"]["scope_source_references"]
    }
    assert set(case["root_scope_member_cues"]) <= root_scope_quotes
    _assert_child_parent_evidence(
        root,
        nodes,
        operator_cue=case["root_operator_cue"],
        scope_cue=case["root_scope_cue"],
    )
    or_leaf_ids = {
        atoms[member]["node_id"]
        for spec in case["inner_groups"]
        if spec["operator"] == "OR"
        for member in spec["members"]
    }
    assert not (or_leaf_ids & set(root["children"]))
    assert root["node_id"] in graph["roots"]
    assert not (or_leaf_ids & set(graph["roots"]))

    _assert_exact_registry_references(
        graph,
        structure,
        document_id,
        source_version,
    )
    if case["case_id"] == "case-11":
        numbered_atoms = {
            node["node_id"]
            for node in _nodes(graph)
            if node.get("op") == "ATOM"
            and (
                "1.9" in str(node.get("text") or "")
                or "1.10" in str(node.get("text") or "")
            )
        }
        assert numbered_atoms == atom_ids
        assert graph.get("references") == []


def _quotes(value: Any) -> list[str]:
    return [str(reference.get("quote") or "") for reference in _iter_references(value)]


def _descendants(
    node: Mapping[str, Any], nodes: Mapping[str, Mapping[str, Any]]
) -> set[str]:
    descendants: set[str] = set()
    pending = list(node.get("children") or [])
    while pending:
        node_id = str(pending.pop())
        if node_id in descendants:
            continue
        descendants.add(node_id)
        child = nodes.get(node_id)
        if child is not None:
            pending.extend(child.get("children") or [])
    return descendants


@pytest.mark.parametrize(
    ("case_id", "text", "directive", "member_markers"),
    [
        (
            "missing-group",
            "以下两组材料均须提交，但每组只需择一：\n"
            "第一组：（1）近两年1.9号表；（2）近两年1.10号表。",
            "以下两组材料均须提交",
            ("近两年1.9号表", "近两年1.10号表"),
        ),
        (
            "duplicate-group-name",
            "以下两组材料均须提交，但每组只需择一：\n"
            "第一组：（1）近两年1.9号表；（2）近两年1.10号表。\n"
            "第一组：（1）近三年1.9号表；（2）近三年1.10号表。",
            "以下两组材料均须提交",
            (
                "近两年1.9号表",
                "近两年1.10号表",
                "近三年1.9号表",
                "近三年1.10号表",
            ),
        ),
        (
            "negated-upper-directive",
            "以下两组材料并非均须提交，但每组只需择一：\n"
            "第一组：（1）近两年1.9号表；（2）近两年1.10号表。\n"
            "第二组：（1）近三年1.9号表；（2）近三年1.10号表。",
            "并非均须提交",
            (
                "近两年1.9号表",
                "近两年1.10号表",
                "近三年1.9号表",
                "近三年1.10号表",
            ),
        ),
    ],
    ids=[
        "missing-group",
        "duplicate-group-name",
        "negated-upper-directive",
    ],
)
def test_incomplete_ambiguous_or_negated_outer_scope_stays_under_review(
    case_id: str,
    text: str,
    directive: str,
    member_markers: tuple[str, ...],
) -> None:
    graph, analysis, structure, document_id, source_version = _run_registered_text(
        case_id,
        text,
    )
    nodes = {node["node_id"]: node for node in _nodes(graph)}
    member_ids = {
        node["node_id"]
        for marker in member_markers
        for node in _nodes(graph)
        if node.get("op") == "ATOM" and marker in str(node.get("text") or "")
    }
    confirmed_ands = [
        node
        for node in nodes.values()
        if node.get("op") == "AND"
        and node.get("status") == "confirmed"
        and (
            directive in _quotes(node)
            or (member_ids and member_ids <= _descendants(node, nodes))
        )
    ]

    assert confirmed_ands == []
    assert analysis["coverage_status"] == "partial"
    assert analysis["needs_human_review"] is True
    _assert_exact_registry_references(
        graph,
        structure,
        document_id,
        source_version,
    )


def test_named_groups_do_not_absorb_an_independent_third_requirement() -> None:
    text = (
        "以下两组材料均须满足：\n"
        "第一组任选其一：营业执照复印件；资质证书。\n"
        "第二组任选其一：近两年1.9号表；近两年1.10号表。\n"
        "此外必须提交项目负责人授权书。"
    )
    graph, _analysis, structure, document_id, source_version = _run_registered_text(
        "independent-third-requirement",
        text,
    )
    nodes = {node["node_id"]: node for node in _nodes(graph)}
    atoms = {
        "A1": _atom(graph, "营业执照复印件"),
        "A2": _atom(graph, "资质证书"),
        "B1": _atom(graph, "近两年1.9号表"),
        "B2": _atom(graph, "近两年1.10号表"),
        "C": _atom(graph, "项目负责人授权书"),
    }
    first_group = _confirmed_group(
        graph,
        "OR",
        [atoms["A1"]["node_id"], atoms["A2"]["node_id"]],
    )
    _assert_child_parent_evidence(
        first_group,
        nodes,
        operator_cue="任选其一",
        scope_cue="第一组",
    )
    second_group = _confirmed_group(
        graph,
        "OR",
        [atoms["B1"]["node_id"], atoms["B2"]["node_id"]],
    )
    _assert_child_parent_evidence(
        second_group,
        nodes,
        operator_cue="任选其一",
        scope_cue="第二组",
    )
    outer_group = _confirmed_group(
        graph,
        "AND",
        [first_group["node_id"], second_group["node_id"]],
    )
    outer_children = [nodes[node_id] for node_id in outer_group["children"]]
    assert len(outer_children) == 2
    assert all(
        child["op"] == "OR" and child["status"] == "confirmed"
        for child in outer_children
    )
    _assert_child_parent_evidence(
        outer_group,
        nodes,
        operator_cue="均须满足",
        scope_cue="两组材料",
    )

    third_id = atoms["C"]["node_id"]
    assert third_id not in _descendants(outer_group, nodes)
    _assert_exact_registry_references(
        graph,
        structure,
        document_id,
        source_version,
    )
