import json
from pathlib import Path

import pytest

from scripts import run_document_relations_eval as existing_eval
from qiaowenshu_agent.domain.document_relations import build_document_relations
from qiaowenshu_agent.domain.document_structure import build_document_structure


ROOT = Path(__file__).resolve().parents[1]
ATTRIBUTE_CASES = (
    ROOT / "benchmarks/document_relations/attribute-regression/20261014/cases.json"
)
ATTRIBUTE_PROBES = (
    ROOT / "benchmarks/document_relations/attribute-regression/20261014/"
    "reviewer-public-probes.json"
)
ALTERNATIVE_CASES = (
    ROOT / "benchmarks/document_relations/copy-alternative-regression/20261014/"
    "cases.json"
)
ALTERNATIVE_PROBES = (
    ROOT / "benchmarks/document_relations/copy-alternative-regression/20261014/"
    "reviewer-public-probes.json"
)


def _load_cases(path: Path) -> list[dict[str, str]]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def _positive_cases() -> list[dict[str, str]]:
    cases = [
        case
        for path in (ATTRIBUTE_CASES, ATTRIBUTE_PROBES)
        for case in _load_cases(path)
        if case["expectation"] == "confirmed_attribute"
    ]
    cases.extend(
        case
        for case in _load_cases(ALTERNATIVE_PROBES)
        if case["case_id"] in {"AP01-issued-single-copy", "AP02-provided-single-copy"}
    )
    return cases


def _structure(text: str) -> dict:
    return build_document_structure(
        [
            {"page_number": page_number, "text": page}
            for page_number, page in enumerate(text.split("\f"), start=1)
        ],
        document_id="copy-alternative-regression",
        source_version="copy-alternative-test-v1",
        source_checksum="public-regression",
    )


def _block(structure: dict, text: str) -> dict:
    return next(item for item in structure["blocks"] if item["raw_text"] == text)


def _nodes(graph: dict, block: dict) -> list[dict]:
    return [
        node
        for node in graph["condition_nodes"]
        if block["block_id"] in node["source_block_ids"]
    ]


def _scope(graph: dict, block: dict) -> dict:
    relation = next(
        item
        for item in graph["block_relations"]
        if item["block_id"] == block["block_id"]
    )
    return next(
        item
        for item in relation["scope_relations"]
        if item.get("relation_type") == "anaphoric_attribute_scope"
    )


def _anaphora(graph: dict, block: dict) -> dict:
    return next(
        item
        for item in graph["references"]
        if item.get("reference_kind") == "anaphora"
        and item.get("source_block_id") == block["block_id"]
        and item.get("reference_text") == "该复印件"
    )


def _antecedent_text(input_text: str, attribute_text: str) -> str:
    prefix = input_text.rsplit(attribute_text, 1)[0]
    return next(line for line in reversed(prefix.splitlines()) if line.strip())


def _assert_source_evidence(
    graph: dict,
    structure: dict,
    input_text: str,
    antecedent_text: str,
    attribute_text: str,
) -> None:
    references = list(existing_eval._walk_actual_source_references(graph))
    quotes = {reference.get("quote") for reference in references}
    assert antecedent_text in quotes
    assert attribute_text in quotes

    result = existing_eval._validate_graph_source_references(
        graph,
        {
            "document_id": structure["document_id"],
            "source_version": structure["source_version"],
            "pages": input_text.split("\f"),
        },
    )
    assert result["checked_references"] > 0
    assert result["invalid_references"] == 0


@pytest.mark.parametrize("case", _positive_cases(), ids=lambda case: case["case_id"])
def test_finite_single_copy_antecedent_confirms_typed_attribute_parent(
    case: dict[str, str],
) -> None:
    structure = _structure(case["input_text"])
    graph = build_document_relations(structure)
    antecedent = _block(structure, case["antecedent_text"])
    attribute = _block(structure, case["attribute_text"])
    antecedent_nodes = _nodes(graph, antecedent)
    attribute_nodes = _nodes(graph, attribute)
    scope = _scope(graph, attribute)
    reference = _anaphora(graph, attribute)

    assert len(antecedent_nodes) == 1
    assert len(attribute_nodes) == 1
    antecedent_node = antecedent_nodes[0]
    attribute_node = attribute_nodes[0]
    assert antecedent_node["op"] == attribute_node["op"] == "ATOM"
    assert scope["status"] == "confirmed"
    assert scope["target_node_ids"] == [
        antecedent_node["node_id"],
        attribute_node["node_id"],
    ]
    assert scope["member_node_ids"] == scope["target_node_ids"]
    assert attribute_node["scope_relation"] == scope

    parent = next(
        item
        for item in attribute_node["parent_relations"]
        if item.get("layer") == "attribute_parent"
    )
    assert parent["status"] == "confirmed"
    assert parent["target_node_ids"] == [antecedent_node["node_id"]]
    assert reference["status"] == "confirmed"
    assert reference["target_node_ids"] == [antecedent_node["node_id"]]
    _assert_source_evidence(
        graph,
        structure,
        case["input_text"],
        case["antecedent_text"],
        case["attribute_text"],
    )


def _review_cases() -> list[dict[str, str]]:
    originals = [
        case
        for case in _load_cases(ALTERNATIVE_CASES)
        if case["expectation"] == "review_attribute"
    ]
    probes = {case["case_id"]: case for case in _load_cases(ALTERNATIVE_PROBES)}
    variants = [
        probes[case_id]
        for case_id in (
            "AR02-fullwidth-slash",
            "AR03-ascii-substitution",
            "AR04-internal-choice",
            "AR06-selection-prefix",
            "AR08-unsupported-purpose-suffix",
        )
    ]
    variants.append(
        {
            "case_id": "ALT03-unknown-compound",
            "expectation": "review_attribute",
            "input_text": ("须提交身份证复印件等相关材料。\n该复印件必须加盖公章。"),
            "attribute_text": "该复印件必须加盖公章。",
        }
    )
    return originals + variants


@pytest.mark.parametrize("case", _review_cases(), ids=lambda case: case["case_id"])
def test_choice_substitution_and_unparsed_antecedents_remain_candidates(
    case: dict[str, str],
) -> None:
    structure = _structure(case["input_text"])
    graph = build_document_relations(structure)
    attribute = _block(structure, case["attribute_text"])
    antecedent_text = case.get("antecedent_text") or _antecedent_text(
        case["input_text"], case["attribute_text"]
    )
    scope = _scope(graph, attribute)
    attribute_nodes = _nodes(graph, attribute)

    assert scope["status"] in {"candidate", "unresolved"}
    assert attribute_nodes
    assert all(node["op"] == "ATOM" for node in attribute_nodes)
    parents = [
        item
        for node in attribute_nodes
        for item in node["parent_relations"]
        if item.get("layer") == "attribute_parent"
    ]
    assert parents
    assert all(item["status"] != "confirmed" for item in parents)
    _assert_source_evidence(
        graph,
        structure,
        case["input_text"],
        antecedent_text,
        case["attribute_text"],
    )
