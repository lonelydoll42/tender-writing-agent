from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Mapping

import pytest

from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.core.files import ProjectFileRegistry
from qiaowenshu_agent.core.runtime import AgentRuntime
from qiaowenshu_agent.skills import build_default_registry


_RAW_DIRECTORY = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "document_relations"
    / "boundary-evidence-regression"
    / "20261013"
    / "reserved-exposed"
    / "raw"
)
_H01_PATH = _RAW_DIRECTORY / "H01.txt"
_H03_PATH = _RAW_DIRECTORY / "H03.txt"
_H01_HEADER = "以下两组证明均须提交，但每组任选一项："
_H01_GROUPS = (
    ("第一组", ("服务回执甲", "服务回执乙")),
    ("第二组", ("验收回执甲", "验收回执乙")),
)
_H03_HEADER = "以下两组材料均须提交，但每组只需择一："
_H03_GROUPS = (
    ("第一组", ("设备清单甲", "设备清单乙")),
    ("第二组", ("备件清单甲", "备件清单乙")),
)
_H01_BODY = (
    "第一组：（1）服务回执甲；（2）服务回执乙。\n"
    "第二组：（1）验收回执甲；（2）验收回执乙。"
)


def _run_registered_text(
    case_id: str,
    text: str | bytes,
) -> dict[str, Any]:
    content = text.encode("utf-8") if isinstance(text, str) else text
    project_id = f"document-relations-proof-header-{case_id}"
    registry = ProjectFileRegistry()
    registration = registry.register(
        project_id=project_id,
        file_name=f"{case_id}.txt",
        file_role="tender",
        content=content,
    )
    runtime = AgentRuntime(
        build_default_registry(file_registry=registry),
        services={"file_registry": registry},
    )
    result = asyncio.run(
        runtime.run(
            SkillRequest.create(
                {
                    "project_id": project_id,
                    "file_ids": [registration.file.file_id],
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
    assert isinstance(graphs, list) and len(graphs) == 1
    graph = graphs[0]

    assert result.status in {"success", "partial"}
    assert graph["document_id"] == registration.file.file_id
    assert graph["source_version"] == registry.file_version_token(
        registration.file.file_id
    )
    assert graph["source_identity_status"] == "registry_verified"
    assert analysis["status"] == "executed"
    assert analysis["source_identity_status"] == "registry_verified"
    assert analysis["coverage_status"] == "partial"
    assert analysis["needs_human_review"] is True
    assert graph["coverage_status"] == "partial"
    assert graph["needs_human_review"] is True
    return {
        "structure": structure,
        "graph": graph,
        "analysis": analysis,
    }


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
    return matches[0]


def _confirmed_group(
    graph: Mapping[str, Any],
    operator: str,
    direct_children: list[str],
) -> dict[str, Any]:
    matches = [
        node
        for node in _nodes(graph)
        if node.get("op") == operator and node.get("children") == direct_children
    ]
    assert len(matches) == 1, (operator, direct_children)
    group = matches[0]
    assert group["status"] == "confirmed"
    assert group["operator_relation"]["status"] == "confirmed"
    assert group["scope_relation"]["status"] == "confirmed"
    assert group["scope_relation"]["target_node_ids"] == direct_children
    return group


def _walk_references(
    value: Any,
    *,
    field: str = "",
):
    if isinstance(value, Mapping):
        if {"page", "char_start", "char_end", "quote"} <= value.keys():
            yield field, value
            return
        for key, child in value.items():
            yield from _walk_references(child, field=str(key))
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_references(child, field=field)


def _reference_key(reference: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        reference.get("document_id"),
        reference.get("source_version"),
        reference.get("page"),
        reference.get("char_start"),
        reference.get("char_end"),
        reference.get("quote"),
    )


def _source_references(value: Any) -> list[Mapping[str, Any]]:
    return [
        reference
        for field, reference in _walk_references(value)
        if field != "position_references"
    ]


def _quotes(value: Any) -> set[str]:
    return {
        str(reference.get("quote") or "")
        for reference in _source_references(value)
    }


def _assert_exact_registry_references(
    graph: Mapping[str, Any],
    structure: Mapping[str, Any],
) -> None:
    pages = {
        page["page_number"]: page["raw_text"]
        for page in structure["pages"]
    }
    references = list(_walk_references(graph))
    assert references
    for field, reference in references:
        page_number = reference["page"]
        start = reference["char_start"]
        end = reference["char_end"]
        quote = reference["quote"]
        assert reference.get("document_id") == graph["document_id"]
        assert reference.get("source_version") == graph["source_version"]
        assert isinstance(page_number, int) and not isinstance(page_number, bool)
        assert isinstance(start, int) and not isinstance(start, bool)
        assert isinstance(end, int) and not isinstance(end, bool)
        assert isinstance(quote, str)
        assert 0 <= start <= end <= len(pages[page_number])
        assert pages[page_number][start:end] == quote
        if field != "position_references":
            assert quote.strip()
            assert end > start


def _assert_group_quotes(
    group: Mapping[str, Any],
    *,
    operator_cue: str,
    scope_cues: tuple[str, ...],
) -> None:
    operator_quotes = _quotes(group.get("operator_relation", {}))
    scope = group["scope_relation"]
    scope_quotes = _quotes(scope)
    assert any(operator_cue in quote for quote in operator_quotes)
    assert all(
        any(cue in quote for quote in scope_quotes)
        for cue in scope_cues
    )


def _assert_direct_parent_edges(
    parent: Mapping[str, Any],
    nodes: Mapping[str, Mapping[str, Any]],
) -> None:
    parent_id = str(parent["node_id"])
    parent_keys = {
        _reference_key(reference)
        for relation_name in ("operator_relation", "scope_relation")
        for reference in _source_references(parent.get(relation_name, {}))
    }
    for child_id in parent["children"]:
        child = nodes[child_id]
        edges = [
            relation
            for relation in child.get("parent_relations", [])
            if relation.get("layer") == "semantic_parent"
            and relation.get("target_node_ids") == [parent_id]
        ]
        assert len(edges) == 1, (parent_id, child_id)
        edge = edges[0]
        assert edge["status"] == "confirmed"
        edge_keys = {
            _reference_key(reference)
            for reference in _source_references(edge)
        }
        child_keys = {
            _reference_key(reference)
            for reference in _source_references(child)
        }
        assert parent_keys <= edge_keys
        assert child_keys <= edge_keys


def _positive_case(case_id: str) -> tuple[bytes, str, str, tuple[Any, ...]]:
    if case_id == "H01":
        return (
            _H01_PATH.read_bytes(),
            _H01_HEADER,
            "每组任选一项",
            _H01_GROUPS,
        )
    if case_id == "H03":
        return (
            _H03_PATH.read_bytes(),
            _H03_HEADER,
            "每组只需择一",
            _H03_GROUPS,
        )
    title = {
        "title-materials": "材料",
        "title-requirements": "要求",
        "title-conditions": "条件",
    }[case_id]
    header = f"以下两组{title}均须提交，但每组任选一项："
    return (
        f"{header}\n{_H01_BODY}".encode("utf-8"),
        header,
        "每组任选一项",
        _H01_GROUPS,
    )


@pytest.mark.parametrize(
    "case_id",
    [
        "H01",
        "title-materials",
        "title-requirements",
        "title-conditions",
        "H03",
    ],
    ids=[
        "original-H01-proof-header",
        "synonym-materials",
        "synonym-requirements",
        "synonym-conditions",
        "blank-lines-and-inherited-choice",
    ],
)
def test_public_proof_headers_form_complete_directly_owned_nested_tree(
    case_id: str,
) -> None:
    text, header, inherited_choice, group_specs = _positive_case(case_id)
    run = _run_registered_text(case_id, text)
    graph = run["graph"]

    atoms = {
        marker: _atom(graph, marker)
        for _label, markers in group_specs
        for marker in markers
    }
    assert len({node["node_id"] for node in atoms.values()}) == 4
    nodes = {node["node_id"]: node for node in _nodes(graph)}
    inner_groups: list[dict[str, Any]] = []
    for label, markers in group_specs:
        children = [atoms[marker]["node_id"] for marker in markers]
        group = _confirmed_group(graph, "OR", children)
        _assert_group_quotes(
            group,
            operator_cue=inherited_choice,
            scope_cues=(label, *markers),
        )
        _assert_direct_parent_edges(group, nodes)
        inner_groups.append(group)

    outer = _confirmed_group(
        graph,
        "AND",
        [group["node_id"] for group in inner_groups],
    )
    assert outer["node_id"] in graph["roots"]
    assert {
        node["node_id"]
        for node in _nodes(graph)
        if node.get("op") == "OR" and node.get("status") == "confirmed"
    } == {group["node_id"] for group in inner_groups}
    assert any(
        "均须提交" in quote
        for quote in _quotes(outer.get("operator_relation", {}))
    )
    outer_scope_quotes = _quotes(outer["scope_relation"])
    assert any(header.split("均须提交", 1)[0] in quote for quote in outer_scope_quotes)
    assert all(
        any(label in quote for quote in outer_scope_quotes)
        for label, _markers in group_specs
    )
    _assert_direct_parent_edges(outer, nodes)
    _assert_exact_registry_references(graph, run["structure"])


def _cites_exact_header_operator_source(
    node: Mapping[str, Any],
    graph: Mapping[str, Any],
    source_text: str,
) -> bool:
    cue = "均须提交"
    cue_start = source_text.index(cue)
    cue_end = cue_start + len(cue)
    for reference in _source_references(node.get("operator_relation", {})):
        page = reference.get("page")
        start = reference.get("char_start")
        end = reference.get("char_end")
        quote = reference.get("quote")
        if (
            reference.get("document_id") != graph["document_id"]
            or reference.get("source_version") != graph["source_version"]
            or not isinstance(page, int)
            or isinstance(page, bool)
            or page != 1
            or not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or not (0 <= start <= end <= len(source_text))
            or not (start <= cue_start and cue_end <= end)
            or not isinstance(quote, str)
        ):
            continue
        if cue in quote and source_text[start:end] == quote:
            return True
    return False


_NEGATIVE_CASES = (
    pytest.param(
        "local-submit-all",
        (
            f"{_H01_HEADER}\n"
            "第一组须同时提交：（1）服务回执甲；（2）服务回执乙。\n"
            "第二组任选一项：（1）验收回执甲；（2）验收回执乙。"
        ),
        id="local-and-conflicts-with-inherited-or",
    ),
    pytest.param(
        "choose-two",
        (
            "以下两组证明均须提交，但每组任选两项：\n"
            "第一组：（1）服务回执甲；（2）服务回执乙。\n"
            "第二组：（1）验收回执甲；（2）验收回执乙。"
        ),
        id="unsupported-k-of-n",
    ),
    pytest.param(
        "local-choose-two",
        (
            f"{_H01_HEADER}\n"
            "第一组任选两项：服务回执甲；服务回执乙；资质回执；\n"
            "第二组任选一项：验收回执甲；验收回执乙。"
        ),
        id="local-k-of-n-conflicts-with-inherited-choice",
    ),
    pytest.param(
        "group-count-mismatch",
        (
            f"{_H01_HEADER}\n"
            "第一组：（1）服务回执甲；（2）服务回执乙。\n"
            "第二组：（1）验收回执甲；（2）验收回执乙。\n"
            "第三组：（1）检测回执甲；（2）检测回执乙。"
        ),
        id="declared-two-groups-but-three-labels",
    ),
    pytest.param(
        "missing-label",
        (
            f"{_H01_HEADER}\n"
            "第一组：（1）服务回执甲；（2）服务回执乙。\n"
            "（1）验收回执甲；（2）验收回执乙。"
        ),
        id="second-group-label-missing",
    ),
    pytest.param(
        "duplicate-label",
        (
            f"{_H01_HEADER}\n"
            "第一组：（1）服务回执甲；（2）服务回执乙。\n"
            "第一组：（1）验收回执甲；（2）验收回执乙。"
        ),
        id="group-label-repeated",
    ),
    pytest.param(
        "cross-paragraph-interruption",
        (
            f"{_H01_HEADER}\n"
            "第一组：（1）服务回执甲；（2）服务回执乙。\n\n"
            "本段为采购背景说明，与上述证明组无关。\n\n"
            "第二组：（1）验收回执甲；（2）验收回执乙。"
        ),
        id="substantive-paragraph-breaks-scope",
    ),
)


@pytest.mark.parametrize(
    ("case_id", "text"),
    _NEGATIVE_CASES,
)
def test_ambiguous_or_interrupted_proof_headers_do_not_confirm_complete_outer_and(
    case_id: str,
    text: str,
) -> None:
    run = _run_registered_text(case_id, text)
    graph = run["graph"]
    header_relations = [
        node
        for node in _nodes(graph)
        if _cites_exact_header_operator_source(node, graph, text)
    ]

    assert all(
        not (
            relation.get("status") == "confirmed"
            and relation.get("operator_relation", {}).get("status") == "confirmed"
            and relation.get("scope_relation", {}).get("status") == "confirmed"
        )
        for relation in header_relations
    )
    assert run["analysis"]["coverage_status"] == "partial"
    assert run["analysis"]["needs_human_review"] is True
