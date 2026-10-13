from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import pytest

from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.core.files import ProjectFileRegistry
from qiaowenshu_agent.core.runtime import AgentRuntime
from qiaowenshu_agent.domain.document_relations import build_document_relations
from qiaowenshu_agent.skills import build_default_registry
from scripts import run_document_relations_boundary_rescore as frozen_105
from scripts import run_document_relations_rescore as frozen_103


_RAW_DIRECTORY = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "document_relations"
    / "boundary-evidence-regression"
    / "20261013"
    / "reserved-exposed"
    / "raw"
)
_H03_PATH = _RAW_DIRECTORY / "H03.txt"
_SOURCE_FIELDS = {
    "source_references",
    "operator_source_references",
    "scope_source_references",
    "boundary_source_references",
    "member_source_references",
    "candidate_source_references",
    "candidate_target_source_references",
    "candidate_target_context_references",
}


def _run_registered_h03(raw: bytes | None = None) -> dict[str, Any]:
    content = _H03_PATH.read_bytes() if raw is None else raw
    project_id = "document-relations-source-roles"
    registry = ProjectFileRegistry()
    registration = registry.register(
        project_id=project_id,
        file_name="H03.txt",
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
    assert structure["document_id"] == registration.file.file_id
    assert structure["source_version"] == registry.file_version_token(
        registration.file.file_id
    )
    assert graph["document_id"] == structure["document_id"]
    assert graph["source_version"] == structure["source_version"]
    assert graph["source_identity_status"] == "registry_verified"
    assert analysis["status"] == "executed"
    assert analysis["source_identity_status"] == "registry_verified"
    assert analysis["source_reference_status"] == "verified"
    return {
        "registry": registry,
        "structure": structure,
        "graph": graph,
        "analysis": analysis,
    }


def _block_relation(
    graph: Mapping[str, Any],
    block_id: str,
) -> Mapping[str, Any]:
    matches = [
        relation
        for relation in graph.get("block_relations", [])
        if isinstance(relation, Mapping) and relation.get("block_id") == block_id
    ]
    assert len(matches) == 1
    return matches[0]


def _reference_payload(value: Any):
    if isinstance(value, Mapping):
        if {"page", "char_start", "char_end", "quote"} <= value.keys():
            yield value
            return
        for child in value.values():
            yield from _reference_payload(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _reference_payload(child)


def _source_evidence_references(value: Any):
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in _SOURCE_FIELDS:
                yield from _reference_payload(child)
            else:
                yield from _source_evidence_references(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _source_evidence_references(child)


def _position_at_line(page_text: str, line_number: int) -> int:
    return sum(len(line) + 1 for line in page_text.split("\n")[: line_number - 1])


def _assert_blank_positions_are_separate_from_evidence(
    structure: Mapping[str, Any],
    graph: Mapping[str, Any],
    *,
    expected_quotes: set[str],
) -> None:
    page_text = structure["pages"][0]["raw_text"]
    blank_blocks = [
        block
        for block in structure["blocks"]
        if block.get("kind") == "blank"
    ]
    assert {block["raw_text"] for block in blank_blocks} == expected_quotes

    for block in blank_blocks:
        position = _position_at_line(page_text, block["line_number"])
        span = block["source_span"]
        assert span == {
            "page_number": 1,
            "start": position,
            "end": position + len(block["raw_text"]),
        }
        raw_reference = block["source_references"][0]
        assert raw_reference["document_id"] == structure["document_id"]
        assert raw_reference["source_version"] == structure["source_version"]
        assert raw_reference["page"] == 1
        assert raw_reference["char_start"] == position
        assert raw_reference["char_end"] == position + len(block["raw_text"])
        assert raw_reference["quote"] == block["raw_text"]
        assert raw_reference["locator"] == (
            f"p1:c{position}-{position + len(block['raw_text'])}"
        )
        assert page_text[position : position + len(block["raw_text"])] == (
            block["raw_text"]
        )

        relation = _block_relation(graph, block["block_id"])
        parent = relation["parent_relation"]
        positions = parent.get("position_references")
        assert isinstance(positions, list)
        assert any(
            reference.get("document_id") == structure["document_id"]
            and reference.get("source_version") == structure["source_version"]
            and reference.get("page") == 1
            and reference.get("char_start") == position
            and reference.get("char_end") == position + len(block["raw_text"])
            and reference.get("quote") == block["raw_text"]
            for reference in positions
            if isinstance(reference, Mapping)
        )
        assert parent["status"] != "confirmed"
        assert all(
            scope.get("status") != "confirmed"
            for scope in relation.get("scope_relations", [])
        )

    evidence_references = list(_source_evidence_references(graph))
    assert evidence_references
    for reference in evidence_references:
        quote = reference.get("quote")
        assert isinstance(quote, str) and quote.strip()
        assert reference["page"] == 1
        start = reference["char_start"]
        end = reference["char_end"]
        assert reference.get("document_id") == structure["document_id"]
        assert reference.get("source_version") == structure["source_version"]
        assert page_text[start:end] == quote
        assert end > start


@pytest.mark.parametrize(
    ("raw", "expected_quotes"),
    [
        pytest.param(None, {""}, id="original-h03-empty-lines"),
        pytest.param(
            "whitespace",
            {"", " \t"},
            id="h03-whitespace-only-line",
        ),
    ],
)
def test_h03_preserves_verified_blank_positions_without_using_them_as_evidence(
    raw: bytes | str | None,
    expected_quotes: set[str],
) -> None:
    content = _H03_PATH.read_bytes()
    if raw == "whitespace":
        content = content.replace(b"\n\n", b"\n \t\n", 1)
    run = _run_registered_h03(content if raw is not None else None)

    _assert_blank_positions_are_separate_from_evidence(
        run["structure"],
        run["graph"],
        expected_quotes=expected_quotes,
    )


@pytest.mark.parametrize("mutation", ["document_id", "source_version", "coordinates"])
def test_unverified_blank_identity_or_coordinates_do_not_create_positions(
    mutation: str,
) -> None:
    run = _run_registered_h03()
    structure = deepcopy(run["structure"])
    block = next(
        item for item in structure["blocks"] if item.get("kind") == "blank"
    )
    reference = block["source_references"][0]
    if mutation == "document_id":
        reference["document_id"] = "different-document"
    elif mutation == "source_version":
        reference["source_version"] = "different-version"
    else:
        reference["char_start"] += 1

    graph = build_document_relations(structure)
    parent = _block_relation(graph, block["block_id"])["parent_relation"]
    positions = parent.get("position_references")
    assert isinstance(positions, list)
    assert positions == []


def _source_context(
    structure: Mapping[str, Any],
    graph: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "document_id": graph["document_id"],
        "source_version": graph["source_version"],
        "pages": [page["raw_text"] for page in structure["pages"]],
    }


def _frozen_validator(grader: str):
    if grader == "1.0.3":
        return frozen_103.load_evaluator("1.0.3")
    assert grader == "1.0.5"
    assert frozen_105.EVALUATOR_VERSION == "1.0.5"
    # The 1.0.5 boundary scorer delegates raw-reference checks to frozen 1.0.4.
    return frozen_105.load_evaluator("1.0.4")


@pytest.mark.parametrize("grader", ["1.0.3", "1.0.5"])
def test_complete_registered_h03_tree_passes_frozen_global_source_validation(
    grader: str,
) -> None:
    run = _run_registered_h03()
    validator = _frozen_validator(grader)
    result = validator._validate_graph_source_references(
        run["graph"],
        _source_context(run["structure"], run["graph"]),
    )

    assert result["checked_references"] > 0
    assert result["invalid_references"] == 0, result["failures"]


def _remove_blank_evidence_references(value: Any) -> Any:
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, child in value.items():
            if key in _SOURCE_FIELDS and isinstance(child, list):
                output[key] = [
                    _remove_blank_evidence_references(reference)
                    for reference in child
                    if not (
                        isinstance(reference, Mapping)
                        and isinstance(reference.get("quote"), str)
                        and not reference["quote"].strip()
                    )
                ]
            else:
                output[key] = _remove_blank_evidence_references(child)
        return output
    if isinstance(value, list):
        return [_remove_blank_evidence_references(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_remove_blank_evidence_references(item) for item in value)
    return deepcopy(value)


def _add_blank_to_evidence_channel(
    graph: dict[str, Any],
    channel: str,
    blank_reference: Mapping[str, Any],
) -> None:
    if channel == "operator":
        target = next(
            node
            for node in graph["condition_nodes"]
            if node.get("op") in {"AND", "OR"}
        )["operator_relation"]
        references = target["source_references"]
    elif channel == "scope":
        target = next(
            node
            for node in graph["condition_nodes"]
            if node.get("op") in {"AND", "OR"}
        )["scope_relation"]
        references = target["source_references"]
    elif channel == "boundary":
        target = next(
            node
            for node in graph["condition_nodes"]
            if node.get("op") in {"AND", "OR"}
        )["scope_relation"]
        references = target["boundary_source_references"]
    elif channel == "parent":
        target = next(
            relation
            for node in graph["condition_nodes"]
            for relation in node.get("parent_relations", [])
            if relation.get("layer") == "semantic_parent"
        )
        references = target["source_references"]
    elif channel == "physical-parent":
        target = graph["block_relations"][0]["parent_relation"]
        references = target["source_references"]
    else:
        raise AssertionError(f"unknown evidence channel: {channel}")
    references.append(dict(blank_reference))


@pytest.mark.parametrize("grader", ["1.0.3", "1.0.5"])
@pytest.mark.parametrize(
    "channel",
    ["operator", "scope", "boundary", "parent", "physical-parent"],
)
def test_frozen_global_validator_rejects_empty_h03_position_in_evidence(
    grader: str,
    channel: str,
) -> None:
    run = _run_registered_h03()
    validator = _frozen_validator(grader)
    context = _source_context(run["structure"], run["graph"])
    blank_block = next(
        block
        for block in run["structure"]["blocks"]
        if block.get("kind") == "blank"
    )
    blank_reference = blank_block["source_references"][0]
    clean_graph = _remove_blank_evidence_references(run["graph"])

    baseline = validator._validate_graph_source_references(clean_graph, context)
    assert baseline["invalid_references"] == 0, baseline["failures"]

    mutated_graph = deepcopy(clean_graph)
    _add_blank_to_evidence_channel(mutated_graph, channel, blank_reference)
    result = validator._validate_graph_source_references(mutated_graph, context)

    assert result["invalid_references"] == 1
    assert [failure["reason"] for failure in result["failures"]] == [
        "missing exact source quote"
    ]
