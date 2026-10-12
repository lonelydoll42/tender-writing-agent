from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.core.files import ProjectFileRegistry
from qiaowenshu_agent.core.runtime import AgentRuntime
from qiaowenshu_agent.skills import build_default_registry


def _run_registered_text(
    case_id: str,
    text: str,
) -> tuple[dict[str, Any], dict[str, Any], Mapping[str, Any], str, str]:
    project_id = f"relation-inheritance-{case_id}"
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


def _assert_relation_cites(
    group: Mapping[str, Any],
    relation_name: str,
    cue: str,
) -> None:
    relation = group.get(relation_name)
    assert isinstance(relation, Mapping)
    refs = relation.get(
        "scope_source_references"
        if relation_name == "scope_relation"
        else "source_references"
    )
    assert isinstance(refs, list) and refs
    assert any(
        cue in str(reference.get("quote") or "")
        for reference in refs
        if isinstance(reference, Mapping)
    )


def _iter_references(value: Any):
    if isinstance(value, Mapping):
        if {"page", "char_start", "char_end", "quote"} <= value.keys():
            yield value
        for child in value.values():
            yield from _iter_references(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _iter_references(child)


def _quotes(value: Any) -> list[str]:
    return [str(reference.get("quote") or "") for reference in _iter_references(value)]


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
    assert boundary_quotes <= set(_quotes(parent))

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
            for reference in edge_references
            if isinstance(reference, Mapping)
        }
        for reference_field in ("source_references", "boundary_source_references"):
            parent_references = scope.get(reference_field)
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


def _descendants(
    node: Mapping[str, Any],
    nodes: Mapping[str, Mapping[str, Any]],
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


def _confirmed_named_or(graph: Mapping[str, Any], group_name: str) -> dict[str, Any]:
    matches = [
        node
        for node in _nodes(graph)
        if node.get("op") == "OR"
        and node.get("status") == "confirmed"
        and group_name in _quotes(node.get("scope_relation") or {})
    ]
    assert len(matches) == 1, group_name
    group = matches[0]
    assert group["operator_relation"]["status"] == "confirmed"
    assert group["scope_relation"]["status"] == "confirmed"
    assert group["children"]
    assert group["scope_relation"]["target_node_ids"] == group["children"]
    return group


@pytest.mark.parametrize(
    ("case_id", "local_instruction", "members"),
    [
        (
            "inherited-or-conflicts-with-local-and",
            "第一组须同时提交：营业执照；审计报告。",
            ("营业执照", "审计报告"),
        ),
        (
            "inherited-or-conflicts-with-k-of-n",
            "第一组任选两项：营业执照；审计报告；资质证明。",
            ("营业执照", "审计报告", "资质证明"),
        ),
    ],
    ids=["local-and-conflicts", "local-cardinality-conflicts"],
)
def test_conflicting_local_instruction_stays_candidate_and_blocks_outer_confirmation(
    case_id: str,
    local_instruction: str,
    members: tuple[str, ...],
) -> None:
    text = (
        "两组材料均须提交，但每组任选一项：\n"
        f"{local_instruction}\n"
        "第二组任选一项：授权书；委托书。"
    )
    graph, analysis, structure, document_id, source_version = _run_registered_text(
        case_id,
        text,
    )
    nodes = {node["node_id"]: node for node in _nodes(graph)}

    retained = [
        node
        for node in nodes.values()
        if node.get("text") == local_instruction
        and node.get("status") in {"candidate", "unresolved"}
    ]
    assert len(retained) == 1
    local = retained[0]
    assert local_instruction in _quotes(local)
    assert not any(
        node.get("op") == "OR"
        and node.get("status") == "confirmed"
        and (
            node.get("text") == local_instruction
            or all(
                any(
                    marker in str(nodes[node_id].get("text") or "")
                    for node_id in _descendants(node, nodes) | {node["node_id"]}
                    if node_id in nodes
                )
                for marker in members
            )
        )
        for node in nodes.values()
    )

    outer_groups = [
        node
        for node in nodes.values()
        if node.get("op") == "AND"
        and (
            "两组材料均须提交" in _quotes(node)
            or "两组材料均须提交" in str(node.get("text") or "")
        )
    ]
    assert len(outer_groups) == 1
    outer = outer_groups[0]
    assert outer["operator_relation"]["status"] == "confirmed"
    assert any(
        "均须提交" in quote for quote in _quotes(outer["operator_relation"])
    )
    assert outer["scope_relation"]["status"] in {"candidate", "unresolved"}
    assert outer["status"] in {"candidate", "unresolved"}
    complete_outer_groups = [
        node
        for node in nodes.values()
        if node.get("op") == "AND"
        and node.get("status") == "confirmed"
        and node.get("scope_relation", {}).get("status") == "confirmed"
        and (
            "两组材料均须提交" in str(node.get("text") or "")
            or (
                "两组材料均须提交" in _quotes(node)
                and local["node_id"] in _descendants(node, nodes)
            )
        )
    ]
    assert complete_outer_groups == []

    second_group = _confirmed_named_or(graph, "第二组")
    second_descendants = _descendants(second_group, nodes) | {
        second_group["node_id"]
    }
    second_text = " ".join(
        str(nodes[node_id].get("text") or "")
        for node_id in second_descendants
        if node_id in nodes
    )
    assert "授权书" in second_text or "授权书" in str(second_group.get("text") or "")
    assert "委托书" in second_text or "委托书" in str(second_group.get("text") or "")
    _assert_child_parent_evidence(
        second_group,
        nodes,
        operator_cue="任选一项",
        scope_cue="第二组",
    )
    assert analysis["coverage_status"] == "partial"
    assert analysis["needs_human_review"] is True
    _assert_exact_registry_references(
        graph,
        structure,
        document_id,
        source_version,
    )


@pytest.mark.parametrize(
    ("case_id", "first_group", "local_selection"),
    [
        (
            "inherit-both-groups",
            "第一组：营业执照；审计报告。",
            None,
        ),
        (
            "inherit-second-group",
            "第一组任选一项：营业执照；审计报告。",
            "第一组任选一项",
        ),
    ],
    ids=["both-groups-inherit", "one-local-one-inherited"],
)
def test_unconflicted_group_selection_inherits_as_confirmed_and_of_ors(
    case_id: str,
    first_group: str,
    local_selection: str | None,
) -> None:
    text = (
        "两组材料均须提交，但每组任选一项：\n"
        f"{first_group}\n"
        "第二组：授权书；委托书。"
    )
    graph, _analysis, structure, document_id, source_version = _run_registered_text(
        case_id,
        text,
    )
    nodes = {node["node_id"]: node for node in _nodes(graph)}
    atoms = {
        "license": _atom(graph, "营业执照"),
        "audit": _atom(graph, "审计报告"),
        "authorization": _atom(graph, "授权书"),
        "entrustment": _atom(graph, "委托书"),
    }
    first = _confirmed_group(
        graph,
        "OR",
        [atoms["license"]["node_id"], atoms["audit"]["node_id"]],
    )
    second = _confirmed_group(
        graph,
        "OR",
        [atoms["authorization"]["node_id"], atoms["entrustment"]["node_id"]],
    )
    first_operator_cue = local_selection or "每组任选一项"
    _assert_relation_cites(first, "operator_relation", first_operator_cue)
    _assert_relation_cites(first, "scope_relation", "第一组")
    _assert_relation_cites(second, "operator_relation", "每组任选一项")
    _assert_relation_cites(second, "scope_relation", "第二组")
    _assert_child_parent_evidence(
        first,
        nodes,
        operator_cue=first_operator_cue,
        scope_cue="第一组",
    )
    _assert_child_parent_evidence(
        second,
        nodes,
        operator_cue="每组任选一项",
        scope_cue="第二组",
    )

    root = _confirmed_group(
        graph,
        "AND",
        [first["node_id"], second["node_id"]],
    )
    assert root["node_id"] in graph["roots"]
    assert all(
        nodes[child_id]["op"] == "OR"
        and nodes[child_id]["status"] == "confirmed"
        for child_id in root["children"]
    )
    _assert_relation_cites(root, "operator_relation", "均须提交")
    _assert_relation_cites(root, "scope_relation", "两组材料")
    root_scope_quotes = {
        reference["quote"]
        for reference in root["scope_relation"]["scope_source_references"]
    }
    assert {"第一组", "第二组"} <= root_scope_quotes
    _assert_child_parent_evidence(
        root,
        nodes,
        operator_cue="均须提交",
        scope_cue="两组材料",
    )
    assert not (
        {atoms["license"]["node_id"], atoms["audit"]["node_id"]}
        & set(root["children"])
    )
    assert not (
        {atoms["authorization"]["node_id"], atoms["entrustment"]["node_id"]}
        & set(root["children"])
    )
    _assert_exact_registry_references(
        graph,
        structure,
        document_id,
        source_version,
    )
