from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import run_document_relations_eval as existing_eval
from scripts import run_document_relations_rescore as frozen_rescore
from qiaowenshu_agent.domain.document_relations import build_document_relations
from qiaowenshu_agent.domain.document_structure import build_document_structure


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = (
    ROOT
    / "benchmarks"
    / "document_relations"
    / "attribute-regression"
    / "20261014"
    / "cases.json"
)
CASES_SHA256 = (
    "64c876600b0c7ba0ae504831f1a401d89c34bc0405c50ea6d6d5e080e7396605"
)


def _cases() -> list[dict[str, str]]:
    raw = CASES_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == CASES_SHA256
    return json.loads(raw)["cases"]


def _structure(text: str, *, version: str = "v1") -> dict:
    pages = text.split("\f")
    return build_document_structure(
        [
            {"page_number": page_number, "text": page}
            for page_number, page in enumerate(pages, start=1)
        ],
        document_id="finite-copy-attribute-test",
        source_version=version,
        source_checksum="public-regression",
    )


def _nodes_for_block(graph: dict, block: dict) -> list[dict]:
    return [
        node
        for node in graph["condition_nodes"]
        if block["block_id"] in node["source_block_ids"]
    ]


def _block_for_text(structure: dict, text: str) -> dict:
    return next(block for block in structure["blocks"] if block["raw_text"] == text)


def _block_relation(graph: dict, block: dict) -> dict:
    return next(
        relation
        for relation in graph["block_relations"]
        if relation["block_id"] == block["block_id"]
    )


def _attribute_scope(graph: dict, block: dict) -> dict:
    return next(
        relation
        for relation in _block_relation(graph, block)["scope_relations"]
        if relation.get("relation_type") == "anaphoric_attribute_scope"
    )


def _anaphora_reference(graph: dict, block: dict) -> dict:
    return next(
        reference
        for reference in graph["references"]
        if reference.get("reference_kind") == "anaphora"
        and reference.get("source_block_id") == block["block_id"]
        and reference.get("reference_text") == "该复印件"
    )


def _assert_review_only(structure: dict, graph: dict, attribute_text: str) -> None:
    block = _block_for_text(structure, attribute_text)
    scope = _attribute_scope(graph, block)
    node = next(node for node in _nodes_for_block(graph, block) if node["op"] == "ATOM")

    assert scope["status"] in {"candidate", "unresolved"}
    assert scope["reason"]
    assert not any(
        parent.get("layer") == "attribute_parent"
        and parent.get("status") == "confirmed"
        for parent in node["parent_relations"]
    )


@pytest.mark.parametrize(
    "case",
    [case for case in _cases() if case["expectation"] == "confirmed_attribute"],
    ids=lambda case: case["case_id"],
)
def test_adjacent_single_copy_attribute_has_exact_typed_relations(
    case: dict[str, str],
) -> None:
    structure = _structure(case["input_text"])
    graph = build_document_relations(structure)
    antecedent = _block_for_text(structure, case["antecedent_text"])
    attribute = _block_for_text(structure, case["attribute_text"])
    antecedent_nodes = _nodes_for_block(graph, antecedent)
    attribute_nodes = _nodes_for_block(graph, attribute)

    assert len(antecedent_nodes) == 1
    assert antecedent_nodes[0]["op"] == "ATOM"
    assert len(attribute_nodes) == 1
    assert attribute_nodes[0]["op"] == "ATOM"
    antecedent_node, attribute_node = antecedent_nodes[0], attribute_nodes[0]
    scope = _attribute_scope(graph, attribute)
    parent = next(
        relation
        for relation in attribute_node["parent_relations"]
        if relation.get("layer") == "attribute_parent"
    )
    reference = _anaphora_reference(graph, attribute)

    assert len(
        [
            node
            for node in graph["condition_nodes"]
            if node["op"] in {"AND", "OR"}
        ]
    ) == 0
    assert scope["status"] == "confirmed"
    assert scope["relation_type"] == "anaphoric_attribute_scope"
    assert scope["operator"] not in {"AND", "OR"}
    assert scope["target_node_ids"] == [
        antecedent_node["node_id"],
        attribute_node["node_id"],
    ]
    assert scope["member_node_ids"] == scope["target_node_ids"]
    assert attribute_node["scope_relation"] == scope
    for evidence_key in ("scope_source_references", "boundary_source_references"):
        quotes = {item["quote"] for item in scope[evidence_key]}
        assert case["antecedent_text"] in quotes
        assert case["attribute_text"] in quotes
    assert case["attribute_text"] in {
        item["quote"] for item in scope["operator_source_references"]
    }
    assert parent["status"] == "confirmed"
    assert parent["basis"]
    assert parent["target_node_ids"] == [antecedent_node["node_id"]]
    assert reference["status"] == "confirmed"
    assert reference["target_node_ids"] == [antecedent_node["node_id"]]
    assert reference["target_block_ids"] == [antecedent["block_id"]]

    for relation in (scope, parent, reference):
        quotes = {
            item["quote"] for item in relation.get("source_references", [])
        }
        assert case["antecedent_text"] in quotes
        assert case["attribute_text"] in quotes


@pytest.mark.parametrize(
    "case",
    [case for case in _cases() if case["expectation"] == "review_attribute"],
    ids=lambda case: case["case_id"],
)
def test_frozen_ambiguity_and_boundary_cases_remain_reviewable(
    case: dict[str, str],
) -> None:
    structure = _structure(case["input_text"])
    graph = build_document_relations(structure)

    _assert_review_only(structure, graph, case["attribute_text"])


def test_one_atom_with_multiple_copy_objects_does_not_confirm_binding() -> None:
    antecedent_text = (
        "须提交营业执照复印件（包括法定代表人身份证复印件）。"
    )
    attribute_text = "该复印件必须加盖公章。"
    structure = _structure(f"{antecedent_text}\n{attribute_text}")
    graph = build_document_relations(structure)
    antecedent = _block_for_text(structure, antecedent_text)
    antecedent_nodes = _nodes_for_block(graph, antecedent)

    assert len(antecedent_nodes) == 1
    assert antecedent_nodes[0]["op"] == "ATOM"
    assert antecedent_nodes[0]["text"].count("复印件") == 2
    _assert_review_only(structure, graph, attribute_text)


@pytest.mark.parametrize(
    "attribute_text",
    [
        "该复印件作为附件保存，授权书必须加盖公章。",
        "该复印件必须提交；授权书须加盖公章。",
    ],
    ids=["comma-subject-switch", "semicolon-subject-switch"],
)
def test_other_subject_seal_predicate_does_not_confirm_copy_attribute(
    attribute_text: str,
) -> None:
    antecedent_text = "须提交身份证复印件。"
    structure = _structure(f"{antecedent_text}\n{attribute_text}")
    antecedent = _block_for_text(structure, antecedent_text)
    attribute = _block_for_text(structure, attribute_text)

    assert antecedent["source_references"]
    assert attribute["source_references"]
    assert all(
        reference["document_id"] == structure["document_id"]
        and reference["source_version"] == structure["source_version"]
        and reference["quote"] in {antecedent_text, attribute_text}
        for block in (antecedent, attribute)
        for reference in block["source_references"]
    )

    graph = build_document_relations(structure)
    antecedent_node = _nodes_for_block(graph, antecedent)[0]
    attribute_nodes = _nodes_for_block(graph, attribute)
    reference = _anaphora_reference(graph, attribute)

    assert antecedent_node["op"] == "ATOM"
    assert len(attribute_nodes) == 1
    assert attribute_nodes[0]["op"] == "ATOM"
    assert reference["status"] == "confirmed"
    assert reference["target_node_ids"] == [antecedent_node["node_id"]]
    reference_quotes = {
        item["quote"] for item in reference.get("source_references", [])
    }
    assert antecedent_text in reference_quotes
    assert attribute_text in reference_quotes

    source_check = existing_eval._validate_graph_source_references(
        graph,
        {
            "document_id": structure["document_id"],
            "source_version": structure["source_version"],
            "pages": [antecedent_text + "\n" + attribute_text],
        },
    )
    assert source_check["checked_references"] > 0
    assert source_check["invalid_references"] == 0

    _assert_review_only(structure, graph, attribute_text)


@pytest.mark.parametrize(
    ("input_text", "antecedent_text", "attribute_text"),
    [
        (
            "须提供税务登记证明复印件。\n该复印件应加盖公章。",
            "须提供税务登记证明复印件。",
            "该复印件应加盖公章。",
        ),
        (
            "须提交营业执照复印件。\n \n该复印件必须加盖公章。",
            "须提交营业执照复印件。",
            "该复印件必须加盖公章。",
        ),
    ],
    ids=["provided-copy", "whitespace-block"],
)
def test_post_delegation_public_positive_variants_keep_exact_binding(
    input_text: str,
    antecedent_text: str,
    attribute_text: str,
) -> None:
    structure = _structure(input_text)
    graph = build_document_relations(structure)
    antecedent = _block_for_text(structure, antecedent_text)
    attribute = _block_for_text(structure, attribute_text)
    antecedent_nodes = _nodes_for_block(graph, antecedent)
    attribute_nodes = _nodes_for_block(graph, attribute)

    assert len(antecedent_nodes) == 1
    assert len(attribute_nodes) == 1
    antecedent_node = antecedent_nodes[0]
    attribute_node = attribute_nodes[0]
    scope = _attribute_scope(graph, attribute)
    parent = next(
        relation
        for relation in attribute_node["parent_relations"]
        if relation.get("layer") == "attribute_parent"
    )
    reference = _anaphora_reference(graph, attribute)

    assert antecedent_node["op"] == attribute_node["op"] == "ATOM"
    assert scope["status"] == parent["status"] == reference["status"] == "confirmed"
    assert scope["target_node_ids"] == [
        antecedent_node["node_id"],
        attribute_node["node_id"],
    ]
    assert scope["member_node_ids"] == scope["target_node_ids"]
    assert parent["target_node_ids"] == [antecedent_node["node_id"]]
    assert reference["target_node_ids"] == [antecedent_node["node_id"]]
    for relation in (scope, parent, reference):
        quotes = {
            item["quote"] for item in relation.get("source_references", [])
        }
        assert antecedent_text in quotes
        assert attribute_text in quotes


@pytest.mark.parametrize(
    ("input_text", "attribute_text"),
    [
        (
            "须提交身份证复印件和授权书。\n该复印件必须加盖公章。",
            "该复印件必须加盖公章。",
        ),
        (
            "须提交身份证原件。\n该复印件必须加盖公章。",
            "该复印件必须加盖公章。",
        ),
        (
            "须提交身份证复印件。\n该复印件必须在需要时加盖公章。",
            "该复印件必须在需要时加盖公章。",
        ),
        (
            "（1）须提交身份证复印件。\n（2）须提供审计报告。\n"
            "该复印件必须加盖公章。",
            "该复印件必须加盖公章。",
        ),
    ],
    ids=[
        "copy-plus-other-object",
        "antecedent-without-copy",
        "condition-inside-predicate",
        "numbered-interruption",
    ],
)
def test_post_delegation_public_ambiguities_remain_reviewable(
    input_text: str,
    attribute_text: str,
) -> None:
    structure = _structure(input_text)
    graph = build_document_relations(structure)

    _assert_review_only(structure, graph, attribute_text)


def test_alternative_antecedent_does_not_confirm_attribute_binding() -> None:
    antecedent_text = "须提交法定代表人身份证复印件或营业执照复印件。"
    attribute_text = "该复印件必须加盖公章。"
    structure = _structure(f"{antecedent_text}\n{attribute_text}")
    graph = build_document_relations(structure)
    antecedent = _block_for_text(structure, antecedent_text)

    assert len(_nodes_for_block(graph, antecedent)) >= 2
    _assert_review_only(structure, graph, attribute_text)


def test_physical_parent_pointer_cannot_authorize_nonadjacent_attribute() -> None:
    antecedent_text = "须提交法定代表人身份证复印件。"
    interruption_text = "须提供审计报告。"
    attribute_text = "该复印件必须加盖公章。"
    structure = _structure(
        f"{antecedent_text}\n{interruption_text}\n{attribute_text}"
    )
    antecedent = _block_for_text(structure, antecedent_text)
    attribute = _block_for_text(structure, attribute_text)
    attribute["parent_block_id"] = antecedent["block_id"]
    graph = build_document_relations(structure)

    _assert_review_only(structure, graph, attribute_text)


@pytest.mark.parametrize(
    "tamper",
    ["document_id", "source_version", "coordinates", "duplicate_block_id"],
)
def test_forged_source_identity_coordinates_and_block_ids_never_confirm(
    tamper: str,
) -> None:
    text = "须提交法定代表人身份证复印件。\n该复印件必须加盖公章。"
    structure = _structure(text)
    antecedent, attribute = structure["blocks"]

    if tamper == "document_id":
        antecedent["source_references"][0]["document_id"] = "other-document"
    elif tamper == "source_version":
        antecedent["source_references"][0]["source_version"] = "other-version"
    elif tamper == "coordinates":
        antecedent["source_references"][0]["char_end"] += 1
        antecedent["source_span"]["end"] += 1
    else:
        attribute["block_id"] = antecedent["block_id"]

    graph = build_document_relations(structure)
    scopes = [
        relation
        for block_relation in graph["block_relations"]
        for relation in block_relation["scope_relations"]
        if relation.get("relation_type") == "anaphoric_attribute_scope"
    ]
    parents = [
        parent
        for node in graph["condition_nodes"]
        for parent in node["parent_relations"]
        if parent.get("layer") == "attribute_parent"
    ]

    assert all(scope["status"] != "confirmed" for scope in scopes)
    assert all(parent["status"] != "confirmed" for parent in parents)
    assert all(reference["status"] != "confirmed" for reference in graph["references"])


@pytest.mark.parametrize(
    ("terminal", "should_confirm"),
    [
        ("?", False),
        ("？", False),
        ("。", True),
    ],
    ids=["ascii-question", "fullwidth-question", "affirmative-full-stop"],
)
def test_question_terminators_require_attribute_review(
    terminal: str,
    should_confirm: bool,
) -> None:
    antecedent_text = "须提交身份证复印件。"
    attribute_text = f"该复印件必须加盖公章{terminal}"
    input_text = f"{antecedent_text}\n{attribute_text}"
    structure = _structure(input_text)
    graph = build_document_relations(structure)
    antecedent = _block_for_text(structure, antecedent_text)
    attribute = _block_for_text(structure, attribute_text)
    antecedent_node = _nodes_for_block(graph, antecedent)[0]
    attribute_nodes = _nodes_for_block(graph, attribute)
    reference = _anaphora_reference(graph, attribute)

    assert len(attribute_nodes) == 1
    assert reference["status"] == "confirmed"
    assert reference["target_node_ids"] == [antecedent_node["node_id"]]
    source_check = existing_eval._validate_graph_source_references(
        graph,
        {
            "document_id": structure["document_id"],
            "source_version": structure["source_version"],
            "pages": [input_text],
        },
    )
    assert source_check["checked_references"] > 0
    assert source_check["invalid_references"] == 0

    if not should_confirm:
        _assert_review_only(structure, graph, attribute_text)
        return

    attribute_node = attribute_nodes[0]
    scope = _attribute_scope(graph, attribute)
    parent = next(
        relation
        for relation in attribute_node["parent_relations"]
        if relation.get("layer") == "attribute_parent"
    )
    assert scope["status"] == parent["status"] == "confirmed"
    assert scope["target_node_ids"] == [
        antecedent_node["node_id"],
        attribute_node["node_id"],
    ]
    assert parent["target_node_ids"] == [antecedent_node["node_id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["1.0.3", "1.0.4"])
async def test_real_case09_scope_and_boundary_pass_frozen_graders(
    version: str,
    tmp_path: Path,
) -> None:
    grader_pins = {
        "scripts/run_document_relations_eval.py": (
            "26330942263746e6794deb7def70e17f4848bb64f2fe7ebb4011f5784ca57483"
        ),
        "scripts/run_document_relations_rescore.py": (
            "05380973db4fd848a4c01e043847f4b648e738f8efa9b0c0affe6bf10cb41abf"
        ),
    }
    grader_hashes = {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in grader_pins
    }
    assert grader_hashes == grader_pins
    bundle = ROOT / "benchmarks/document_relations/reserved/v2"
    freeze = existing_eval.verify_bundle(bundle)
    case = next(
        item for item in freeze["oracle"]["cases"] if item["case_id"] == "case-09"
    )
    input_path = bundle / case["input"]
    runtime = await existing_eval._run_input(input_path, case["case_id"])
    graph = runtime.get("graph")
    context = runtime.get("source_context")
    score: dict = {}
    source_check: dict = {}
    if (
        runtime["execution_state"] == "executed"
        and isinstance(graph, dict)
        and isinstance(context, dict)
    ):
        source_check = existing_eval._validate_graph_source_references(graph, context)
        score = frozen_rescore.score_case(case, graph, context, version=version)

    capture = {
        "schema": "finite-copy-attribute-frozen-case09-regression-v1",
        "classification": "public actual Registry/Runtime regression; not unseen",
        "case_id": case["case_id"],
        "evaluator_version": version,
        "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "product_source_sha256": hashlib.sha256(
            (ROOT / "src/qiaowenshu_agent/domain/document_relations.py").read_bytes()
        ).hexdigest(),
        "test_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_tree_sha256": existing_eval._source_tree_sha256(),
        "grader_hashes": grader_hashes,
        "manifest_sha256": freeze["manifest_sha256"],
        "oracle_sha256": hashlib.sha256(
            (bundle / "machine-oracle.json").read_bytes()
        ).hexdigest(),
        "oracle_case": case,
        "execution_state": runtime["execution_state"],
        "grading_status": score.get("status", "not_run"),
        "actual_graph": graph,
        "source_context": context,
        "runtime": {
            key: value
            for key, value in runtime.items()
            if key not in {"graph", "source_context"}
        },
        "source_check": {
            key: value
            for key, value in source_check.items()
            if key != "normalized_graph"
        },
        "frozen_score": score,
    }
    capture_path = tmp_path / f"case09-evidence-{version}.json"
    with capture_path.open("x", encoding="utf-8") as stream:
        json.dump(capture, stream, ensure_ascii=False, indent=2)
        stream.write("\n")

    assert runtime["execution_state"] == "executed", runtime["reason"]
    assert source_check["checked_references"] > 0
    assert source_check["invalid_references"] == 0
    assert score["status"] == "passed", score["errors"]
    assert isinstance(graph, dict)
    members = graph["condition_nodes"]
    assert len(members) == 2
    assert all(member["op"] == "ATOM" for member in members)
    scope = next(
        relation
        for block_relation in graph["block_relations"]
        for relation in block_relation["scope_relations"]
        if relation.get("relation_type") == "anaphoric_attribute_scope"
    )
    assert scope["status"] == "confirmed"
    assert set(scope["member_node_ids"]) == {
        member["node_id"] for member in members
    }
    assert scope["target_node_ids"] == scope["member_node_ids"]
    attribute_node = next(
        member
        for member in members
        if member["node_id"] == scope["member_node_ids"][-1]
    )
    assert attribute_node["scope_relation"] == scope
    assert all(
        reference in scope["operator_source_references"]
        for reference in attribute_node["source_references"]
    )
    for evidence_key in ("scope_source_references", "boundary_source_references"):
        for member in members:
            assert member["source_references"]
            assert all(
                reference in scope[evidence_key]
                for reference in member["source_references"]
            )
