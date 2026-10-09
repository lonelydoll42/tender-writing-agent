from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import run_document_structure_eval as evaluation


def _make_structure(
    raw_pages: list[str],
    oracle_case: dict[str, Any],
    *,
    document_id: str = "test-document",
    source_version: str = "test-version",
) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    pages = []
    title_candidates: list[dict[str, Any]] = []
    block_ids: dict[str, str] = {}
    expected = evaluation._expanded_oracle(oracle_case, raw_pages)

    for item in expected:
        block_ids[item["locator"]] = f"block-{item['locator']}"

    for page_number, page_text in enumerate(raw_pages, start=1):
        pages.append({"page_number": page_number, "raw_text": page_text})
        for physical in evaluation._physical_lines(page_text):
            locator = f"p{page_number}l{physical['line_number']}"
            expectation = next(
                item for item in expected if item["locator"] == locator
            )
            raw_text = physical["raw_text"]
            normalized_parts: list[str] = []
            normalization_map: list[dict[str, int]] = []
            raw_cursor = 0
            norm_cursor = 0
            while raw_cursor < len(raw_text):
                raw_end = raw_cursor + 1
                if raw_text[raw_cursor].isspace():
                    while raw_end < len(raw_text) and raw_text[raw_end].isspace():
                        raw_end += 1
                    normalized_part = " "
                else:
                    while raw_end < len(raw_text) and not raw_text[raw_end].isspace():
                        raw_end += 1
                    normalized_part = raw_text[raw_cursor:raw_end]
                normalized_parts.append(normalized_part)
                normalization_map.append(
                    {
                        "normalized_start": norm_cursor,
                        "normalized_end": norm_cursor + len(normalized_part),
                        "raw_start": physical["start"] + raw_cursor,
                        "raw_end": physical["start"] + raw_end,
                    }
                )
                norm_cursor += len(normalized_part)
                raw_cursor = raw_end
            normalized_text = "".join(normalized_parts)

            source_references = []
            if raw_text:
                source_references = [
                    {
                        "document_id": document_id,
                        "source_version": source_version,
                        "page": page_number,
                        "char_start": physical["start"],
                        "char_end": physical["end"],
                        "quote": raw_text,
                    }
                ]

            parent = expectation.get("parent")
            section = expectation.get("section")
            numbering = expectation.get("numbering")
            block: dict[str, Any] = {
                "block_id": block_ids[locator],
                "kind": expectation["kind"],
                "raw_text": raw_text,
                "normalized_text": normalized_text,
                "line_ending": physical["line_ending"],
                "page_number": page_number,
                "line_number": physical["line_number"],
                "source_span": {
                    "page_number": page_number,
                    "start": physical["start"],
                    "end": physical["end"],
                },
                "normalization_map": normalization_map,
                "source_references": source_references,
                "parent_block_id": block_ids[parent] if parent else None,
                "section_block_id": block_ids[section] if section else None,
            }
            if expectation.get("title_candidate") is not None:
                title_candidates.append(
                    {
                        "candidate_kind": "document_title",
                        **expectation["title_candidate"],
                        "block_id": block_ids[locator],
                        "source_references": [
                            dict(ref) for ref in source_references
                        ],
                    }
                )
            if expectation.get("heading_candidate") is not None:
                block["heading_candidate"] = True
                block["kind_ambiguity"] = "decimal_heading_or_numbered_clause"
            if numbering is not None:
                block_numbering = dict(numbering)
                block_numbering["path"] = evaluation._path_tokens(numbering["path"])
                block["numbering"] = block_numbering
            review = expectation.get("review")
            if review is not None:
                block["relation"] = {
                    "status": review["status"],
                    "candidate_parent": review.get("candidate_parent"),
                }
            if expectation.get("kind") == "table_row":
                anchor = str(expectation["table_group"])
                block["table_group_id"] = block_ids[anchor]
                prior_rows = sum(
                    1
                    for prior in blocks
                    if prior.get("table_group_id") == block_ids[anchor]
                )
                block["table_row_index"] = prior_rows + 1
                ranges = evaluation._table_cell_ranges(raw_text)
                if ranges is not None:
                    block["cell_spans"] = [
                        {
                            "start": physical["start"] + start,
                            "end": physical["start"] + end,
                            "raw_text": cell_text,
                        }
                        for start, end, cell_text in ranges
                    ]
            blocks.append(block)

    block_by_locator = {
        f"p{block['page_number']}l{block['line_number']}": block
        for block in blocks
    }
    continuation_candidates = []
    for item in expected:
        review = item.get("review")
        if not isinstance(review, dict) or review.get("status") != "needs_review":
            continue
        preceding = block_by_locator[review["candidate_parent"]]
        current = block_by_locator[item["locator"]]
        continuation_candidates.append(
            {
                "status": "needs_review",
                "source_block_ids": [
                    preceding["block_id"],
                    current["block_id"],
                ],
                "source_references": [
                    *[dict(ref) for ref in preceding["source_references"]],
                    *[dict(ref) for ref in current["source_references"]],
                ],
            }
        )

    if len(raw_pages) > 1:
        blocks.extend(
            {
                "block_id": f"page-boundary-{index}",
                "kind": "page_boundary",
                "source_span": None,
                "source_references": [],
            }
            for index in range(1, len(raw_pages))
        )
    return {
        "pages": pages,
        "blocks": blocks,
        "continuation_candidates": continuation_candidates,
        "title_candidates": title_candidates,
    }


def test_public_bundle_is_frozen_and_oracle_covers_every_physical_line() -> None:
    manifest = evaluation.verify_freeze()
    fixture_index = evaluation._load_json(evaluation.FIXTURE_PATH)
    oracle = evaluation._load_json(evaluation.ORACLE_PATH)
    v2_manifest = evaluation._load_json(evaluation.V2_FREEZE_PATH)
    v1_manifest = evaluation._load_json(evaluation.V1_FREEZE_PATH)
    oracle_by_id = {case["case_id"]: case for case in oracle["cases"]}
    total_blocks = 0

    assert evaluation._sha256(evaluation.V1_ORACLE_PATH.read_bytes()) == (
        "186f3ae6fa2cc5327c4122138f014705b6d362bbbbd6338a16025f95af8f69f0"
    )
    assert v1_manifest["bundle_fingerprint"] == (
        "f894c05126e65e3d9504f6ac368fc6a5df814ec6e7a89fc338543eb4feb81ac1"
    )
    assert manifest["bundle_fingerprint"] == (
        "e03d75abad901766cbb7b70985bcea35c2cfa6d2a2299138d0008cd50dc6df4f"
    )
    assert v2_manifest["bundle_fingerprint"] == (
        "7f76f29b11eb0f194389599fdf689ef3064d1bac1ad3b8682208e534d8ec5314"
    )
    assert evaluation._sha256(evaluation.V2_ORACLE_PATH.read_bytes()) == (
        "007fbd2575ff99ab519e5ab84645f5fd47ffae5a3206ad778cec1be144104f11"
    )
    for fixture_case in fixture_index["cases"]:
        raw_text = (
            evaluation.ROOT / fixture_case["source_path"]
        ).read_bytes().decode("utf-8")
        pages = raw_text.split(evaluation.BOUNDARY)
        expanded = evaluation._expanded_oracle(
            oracle_by_id[fixture_case["case_id"]], pages
        )
        total_blocks += len(expanded)
        assert len(pages) == fixture_case["expected_pages"]
        assert len(expanded) == sum(
            len(evaluation._physical_lines(page)) for page in pages
        )

    h01 = oracle_by_id["H01"]
    uncertain = h01["pages"][1]["blocks"][0]
    assert uncertain["review"]["status"] == "needs_review"
    assert uncertain["parent"] is None
    assert uncertain["section"] is None
    assert total_blocks == 85
    assert sum(
        "title_candidate" in item
        for case in oracle["cases"]
        for page in case["pages"]
        for item in page["blocks"]
    ) == 3
    assert sum(
        "heading_candidate" in item
        for case in oracle["cases"]
        for page in case["pages"]
        for item in page["blocks"]
    ) == 12
    assert all(
        item["kind"] == "list_item"
        for case in oracle["cases"]
        for page in case["pages"]
        for item in page["blocks"]
        if "numbering" in item
    )
    assert all(
        "reserved" not in fixture["source_path"].replace("\\", "/").split("/")
        for fixture in fixture_index["cases"]
    )
    assert sum(
        len(evaluation._table_cell_ranges(item["raw_text"]) or [])
        for case in oracle["cases"]
        for item in evaluation._expanded_oracle(
            case,
            (
                evaluation.ROOT
                / next(
                    fixture["source_path"]
                    for fixture in fixture_index["cases"]
                    if fixture["case_id"] == case["case_id"]
                )
            )
            .read_bytes()
            .decode("utf-8")
            .split(evaluation.BOUNDARY),
        )
        if item["kind"] == "table_row"
    ) == 37


def test_physical_lines_keep_line_endings_outside_raw_text() -> None:
    page_text = "甲\r\n\r\n乙\n"
    lines = evaluation._physical_lines(page_text)

    assert [
        (line["raw_text"], line["line_ending"]) for line in lines
    ] == [("甲", "\r\n"), ("", "\r\n"), ("乙", "\n")]
    assert "".join(
        line["raw_text"] + line["line_ending"] for line in lines
    ) == page_text


def test_normalization_map_traces_identity_and_whitespace_runs_with_edge_spaces(
) -> None:
    page_text = "  短\t行 "
    block = {
        "raw_text": page_text,
        "normalized_text": " 短 行 ",
        "source_span": {"page_number": 1, "start": 0, "end": len(page_text)},
        "normalization_map": [
            {"normalized_start": 0, "normalized_end": 1, "raw_start": 0, "raw_end": 2},
            {"normalized_start": 1, "normalized_end": 2, "raw_start": 2, "raw_end": 3},
            {"normalized_start": 2, "normalized_end": 3, "raw_start": 3, "raw_end": 4},
            {"normalized_start": 3, "normalized_end": 4, "raw_start": 4, "raw_end": 5},
            {"normalized_start": 4, "normalized_end": 5, "raw_start": 5, "raw_end": 6},
        ],
    }

    assert evaluation._normalization_map_errors(
        block, page_text=page_text, expected_page=1
    ) == []

    block["normalization_map"][2]["raw_end"] = 5
    assert evaluation._normalization_map_errors(
        block, page_text=page_text, expected_page=1
    )


def test_normalization_map_rejects_a_run_that_swallows_words() -> None:
    page_text = "词甲 词乙"
    block = {
        "raw_text": page_text,
        "normalized_text": page_text,
        "source_span": {"page_number": 1, "start": 0, "end": len(page_text)},
        "normalization_map": [
            {"normalized_start": 0, "normalized_end": 2, "raw_start": 0, "raw_end": 2},
            {"normalized_start": 2, "normalized_end": 3, "raw_start": 2, "raw_end": 4},
            {"normalized_start": 3, "normalized_end": 4, "raw_start": 3, "raw_end": 4},
            {"normalized_start": 4, "normalized_end": 5, "raw_start": 4, "raw_end": 5},
        ],
    }

    errors = evaluation._normalization_map_errors(
        block, page_text=page_text, expected_page=1
    )

    assert any("traceable" in error for error in errors)


def test_oracle_label_paths_resolve_to_contract_numbering_tokens() -> None:
    assert evaluation._path_tokens(["1.", "1.1", "（a）"]) == ["1", "1", "a"]


def test_structure_reconstructs_pages_and_keeps_boundary_unreferenced() -> None:
    raw_pages = ["A\r\n", "B\n"]
    oracle_case = {
        "case_id": "T-BOUNDARY",
        "pages": [
            {"page_number": 1, "blocks": [{"line": 1, "kind": "paragraph"}]},
            {"page_number": 2, "blocks": [{"line": 1, "kind": "paragraph"}]},
        ],
    }
    structure = _make_structure(raw_pages, oracle_case)
    structure["blocks"][0]["section_block_id"] = structure["blocks"][1]["block_id"]

    result = evaluation._evaluate_structure(
        case_id="T-BOUNDARY",
        structure=structure,
        oracle_case=oracle_case,
        raw_pages=raw_pages,
        document_id="test-document",
        source_version="test-version",
    )

    assert result["all_structure_checks_passed"] is True
    assert result["wrong_parent_or_merge"]["count"] == 0
    assert result["source_gaps"]["count"] == 0
    assert result["page_boundaries"] == {
        "expected_count": 1,
        "explicit_block_count": 1,
        "preserved_by_page_array": True,
        "errors": [],
    }

    boundary = next(
        block for block in structure["blocks"] if block["kind"] == "page_boundary"
    )
    boundary["source_span"] = {
        "page_number": 1,
        "start": len(raw_pages[0]),
        "end": len(raw_pages[0]) + 1,
    }
    result_with_bad_boundary = evaluation._evaluate_structure(
        case_id="T-BOUNDARY",
        structure=structure,
        oracle_case=oracle_case,
        raw_pages=raw_pages,
        document_id="test-document",
        source_version="test-version",
    )
    assert result_with_bad_boundary["page_boundaries"]["errors"]


def test_numbering_path_and_parent_are_structural_only() -> None:
    raw_pages = ["1. Root\n1.1 Child\n"]
    oracle_case = {
        "case_id": "T-PARENT",
        "pages": [
            {
                "page_number": 1,
                "blocks": [
                    {
                        "line": 1,
                        "kind": "list_item",
                        "numbering": {
                            "label": "1.",
                            "level": 1,
                            "path": ["1."],
                        },
                        "parent": None,
                        "section": "p1l1",
                        "heading_candidate": {"status": "ambiguous"},
                    },
                    {
                        "line": 2,
                        "kind": "list_item",
                        "numbering": {
                            "label": "1.1",
                            "level": 2,
                            "path": ["1.", "1.1"],
                        },
                        "parent": "p1l1",
                        "section": "p1l1",
                    },
                ],
            }
        ],
    }
    structure = _make_structure(raw_pages, oracle_case)
    correct = evaluation._evaluate_structure(
        case_id="T-PARENT",
        structure=structure,
        oracle_case=oracle_case,
        raw_pages=raw_pages,
        document_id="test-document",
        source_version="test-version",
    )
    assert correct["wrong_parent_or_merge"]["count"] == 0
    assert correct["wrong_section"]["count"] == 0
    assert correct["wrong_numbering"]["count"] == 0

    wrong_section_structure = _make_structure(raw_pages, oracle_case)
    wrong_section_structure["blocks"][1]["section_block_id"] = "wrong-section"
    wrong_section = evaluation._evaluate_structure(
        case_id="T-PARENT",
        structure=wrong_section_structure,
        oracle_case=oracle_case,
        raw_pages=raw_pages,
        document_id="test-document",
        source_version="test-version",
    )
    assert wrong_section["wrong_parent_or_merge"]["count"] == 0
    assert wrong_section["wrong_section"]["count"] == 1

    structure["blocks"][1]["parent_block_id"] = None
    wrong_parent = evaluation._evaluate_structure(
        case_id="T-PARENT",
        structure=structure,
        oracle_case=oracle_case,
        raw_pages=raw_pages,
        document_id="test-document",
        source_version="test-version",
    )
    assert wrong_parent["wrong_parent_or_merge"]["wrong_parent_count"] == 1


def test_global_continuation_candidate_requires_exact_ids_status_and_references(
) -> None:
    fixture_index = evaluation._load_json(evaluation.FIXTURE_PATH)
    oracle = evaluation._load_json(evaluation.ORACLE_PATH)
    fixture = next(item for item in fixture_index["cases"] if item["case_id"] == "H01")
    oracle_case = next(item for item in oracle["cases"] if item["case_id"] == "H01")
    raw_pages = (
        (evaluation.ROOT / fixture["source_path"])
        .read_bytes()
        .decode("utf-8")
        .split(evaluation.BOUNDARY)
    )
    structure = _make_structure(raw_pages, oracle_case)

    def evaluate() -> dict[str, Any]:
        return evaluation._evaluate_structure(
            case_id="H01",
            structure=structure,
            oracle_case=oracle_case,
            raw_pages=raw_pages,
            document_id="test-document",
            source_version="test-version",
        )

    assert evaluate()["uncertain_relations"]["needs_review_failure_count"] == 0
    uncertain = next(
        block
        for block in structure["blocks"]
        if block.get("relation", {}).get("status") == "needs_review"
    )
    predecessor = next(
        block
        for block in structure["blocks"]
        if block["page_number"] == 1 and block["line_number"] == 16
    )
    uncertain["parent_block_id"] = predecessor["block_id"]
    uncertain["section_block_id"] = uncertain["block_id"]
    forced_relationship = evaluate()
    assert forced_relationship["wrong_parent_or_merge"]["wrong_parent_count"] == 1
    assert forced_relationship["wrong_section"]["count"] == 1
    assert forced_relationship["all_structure_checks_passed"] is False
    assert (
        forced_relationship["uncertain_relations"]["needs_review_failure_count"] > 0
    )

    structure = _make_structure(raw_pages, oracle_case)
    structure["continuation_candidates"] = []
    assert evaluate()["uncertain_relations"]["needs_review_failure_count"] > 0
    structure = _make_structure(raw_pages, oracle_case)
    candidate = structure["continuation_candidates"][0]
    candidate["source_block_ids"].reverse()
    assert evaluate()["uncertain_relations"]["needs_review_failure_count"] > 0
    structure = _make_structure(raw_pages, oracle_case)
    structure["continuation_candidates"][0]["source_references"][0]["quote"] = (
        "not the referenced source"
    )
    assert evaluate()["uncertain_relations"]["needs_review_failure_count"] == 1


def test_relationship_integrity_rejects_dangling_self_and_cyclic_parents() -> None:
    raw_pages = ["A\nB\n"]
    oracle_case = {
        "case_id": "T-RELATION-INTEGRITY",
        "pages": [
            {
                "page_number": 1,
                "blocks": [
                    {"line": 1, "kind": "paragraph"},
                    {"line": 2, "kind": "paragraph"},
                ],
            }
        ],
    }
    structure = _make_structure(raw_pages, oracle_case)
    first, second = structure["blocks"]

    first["parent_block_id"] = "absent-parent"
    first["section_block_id"] = "absent-section"
    dangling_result = evaluation._evaluate_structure(
        case_id="T-RELATION-INTEGRITY",
        structure=structure,
        oracle_case=oracle_case,
        raw_pages=raw_pages,
        document_id="test-document",
        source_version="test-version",
    )
    dangling = dangling_result["invalid_relationship_references"]
    assert dangling["dangling_parent_count"] == 1
    assert dangling["dangling_section_count"] == 1
    assert dangling_result["all_structure_checks_passed"] is False

    first["parent_block_id"] = first["block_id"]
    first["section_block_id"] = None
    self_result = evaluation._evaluate_structure(
        case_id="T-RELATION-INTEGRITY",
        structure=structure,
        oracle_case=oracle_case,
        raw_pages=raw_pages,
        document_id="test-document",
        source_version="test-version",
    )
    self_parent = self_result["invalid_relationship_references"]
    assert self_parent["self_parent_count"] == 1
    assert self_parent["failure_count"] > 0
    assert self_result["all_structure_checks_passed"] is False

    first["parent_block_id"] = second["block_id"]
    second["parent_block_id"] = first["block_id"]
    cycle_result = evaluation._evaluate_structure(
        case_id="T-RELATION-INTEGRITY",
        structure=structure,
        oracle_case=oracle_case,
        raw_pages=raw_pages,
        document_id="test-document",
        source_version="test-version",
    )
    cycle = cycle_result["invalid_relationship_references"]
    assert cycle["parent_cycle_count"] == 1
    assert cycle["failure_count"] == 1
    assert cycle_result["all_structure_checks_passed"] is False


def test_ambiguous_candidates_need_exact_status_and_real_source_references() -> None:
    oracle_case = {
        "case_id": "T-CANDIDATE",
        "pages": [
            {
                "page_number": 1,
                "blocks": [
                    {
                        "line": 1,
                        "kind": "paragraph",
                        "title_candidate": {"status": "ambiguous"},
                    },
                    {
                        "line": 2,
                        "kind": "list_item",
                        "numbering": {
                            "label": "1.",
                            "level": 1,
                            "path": ["1."],
                        },
                        "heading_candidate": {"status": "ambiguous"},
                    },
                ],
            }
        ],
    }
    structure = _make_structure(["采购需求\n1. 条款\n"], oracle_case)
    blocks_by_locator = {
        f"p{block['page_number']}l{block['line_number']}": [block]
        for block in structure["blocks"]
    }
    expected = evaluation._expanded_oracle(
        oracle_case, ["采购需求\n1. 条款\n"]
    )

    title = evaluation._evaluate_ambiguous_candidate_field(
        field_name="title_candidate",
        expected=expected,
        actual_by_locator=blocks_by_locator,
        global_candidates=structure["title_candidates"],
    )
    heading = evaluation._evaluate_ambiguous_candidate_field(
        field_name="heading_candidate",
        expected=expected,
        actual_by_locator=blocks_by_locator,
    )
    assert title["failure_count"] == 0
    assert heading["failure_count"] == 0

    structure["title_candidates"][0]["status"] = "confirmed"
    assert evaluation._evaluate_ambiguous_candidate_field(
        field_name="title_candidate",
        expected=expected,
        actual_by_locator=blocks_by_locator,
        global_candidates=structure["title_candidates"],
    )["failure_count"] == 1
    structure = _make_structure(["采购需求\n1. 条款\n"], oracle_case)
    structure["title_candidates"][0]["block_id"] = "not-a-source-block"
    blocks_by_locator = {
        f"p{block['page_number']}l{block['line_number']}": [block]
        for block in structure["blocks"]
    }
    assert evaluation._evaluate_ambiguous_candidate_field(
        field_name="title_candidate",
        expected=expected,
        actual_by_locator=blocks_by_locator,
        global_candidates=structure["title_candidates"],
    )["failure_count"] > 0
    structure = _make_structure(["采购需求\n1. 条款\n"], oracle_case)
    structure["title_candidates"][0]["candidate_kind"] = "generic_candidate"
    blocks_by_locator = {
        f"p{block['page_number']}l{block['line_number']}": [block]
        for block in structure["blocks"]
    }
    assert evaluation._evaluate_ambiguous_candidate_field(
        field_name="title_candidate",
        expected=expected,
        actual_by_locator=blocks_by_locator,
        global_candidates=structure["title_candidates"],
    )["failure_count"] == 1

    structure = _make_structure(["采购需求\n1. 条款\n"], oracle_case)
    structure["blocks"][1]["kind_ambiguity"] = "confirmed_heading"
    blocks_by_locator = {
        f"p{block['page_number']}l{block['line_number']}": [block]
        for block in structure["blocks"]
    }
    assert evaluation._evaluate_ambiguous_candidate_field(
        field_name="heading_candidate",
        expected=expected,
        actual_by_locator=blocks_by_locator,
    )["failure_count"] == 1
    structure = _make_structure(["采购需求\n1. 条款\n"], oracle_case)
    structure["blocks"][1]["source_references"] = []
    blocks_by_locator = {
        f"p{block['page_number']}l{block['line_number']}": [block]
        for block in structure["blocks"]
    }
    assert evaluation._evaluate_ambiguous_candidate_field(
        field_name="heading_candidate",
        expected=expected,
        actual_by_locator=blocks_by_locator,
    )["failure_count"] == 1
    structure = _make_structure(["采购需求\n1. 条款\n"], oracle_case)
    blocks_by_locator = {
        f"p{block['page_number']}l{block['line_number']}": [block]
        for block in structure["blocks"]
    }
    structure["title_candidates"][0]["source_references"] = []
    assert evaluation._evaluate_ambiguous_candidate_field(
        field_name="title_candidate",
        expected=expected,
        actual_by_locator=blocks_by_locator,
        global_candidates=structure["title_candidates"],
    )["failure_count"] == 1


def test_table_group_and_cell_spans_cover_all_public_table_cells() -> None:
    fixture_index = evaluation._load_json(evaluation.FIXTURE_PATH)
    oracle = evaluation._load_json(evaluation.ORACLE_PATH)
    total_cells = 0
    total_rows = 0
    for fixture in fixture_index["cases"]:
        raw_pages = (
            (evaluation.ROOT / fixture["source_path"])
            .read_bytes()
            .decode("utf-8")
            .split(evaluation.BOUNDARY)
        )
        oracle_case = next(
            case for case in oracle["cases"] if case["case_id"] == fixture["case_id"]
        )
        expected = evaluation._expanded_oracle(oracle_case, raw_pages)
        structure = _make_structure(raw_pages, oracle_case)
        matched = {
            f"p{block['page_number']}l{block['line_number']}": block
            for block in structure["blocks"]
            if block["kind"] != "page_boundary"
        }
        groups = evaluation._evaluate_table_grouping(
            expected=expected,
            matched_by_locator=matched,
        )
        cells = evaluation._evaluate_table_cell_spans(
            expected=expected,
            matched_by_locator=matched,
            raw_pages=raw_pages,
        )
        assert groups["failure_count"] == 0
        assert cells["failure_count"] == 0
        total_rows += groups["denominator"]
        total_cells += cells["denominator"]
    assert total_rows == 11
    assert total_cells == 37


def test_indented_table_cell_offsets_are_exact_and_bad_pipe_offset_fails() -> None:
    raw_pages = ["  | A | B |\n"]
    oracle_case = {
        "case_id": "T-INDENTED-TABLE",
        "pages": [
            {
                "page_number": 1,
                "blocks": [
                    {
                        "line": 1,
                        "kind": "table_row",
                        "table_group": "p1l1",
                    }
                ],
            }
        ],
    }
    structure = _make_structure(raw_pages, oracle_case)
    block = structure["blocks"][0]
    assert [cell["raw_text"] for cell in block["cell_spans"]] == [" A ", " B "]
    matched = {"p1l1": block}
    expected = evaluation._expanded_oracle(oracle_case, raw_pages)
    assert evaluation._evaluate_table_cell_spans(
        expected=expected,
        matched_by_locator=matched,
        raw_pages=raw_pages,
    )["failure_count"] == 0

    block["cell_spans"][0]["start"] = block["source_span"]["start"]
    failed = evaluation._evaluate_table_cell_spans(
        expected=expected,
        matched_by_locator=matched,
        raw_pages=raw_pages,
    )
    assert failed["failure_count"] == 1


def test_table_grouping_rejects_split_group_and_zero_based_row_index() -> None:
    raw_pages = ["| A |\n| B |\n"]
    oracle_case = {
        "case_id": "T-TABLE-GROUP",
        "pages": [
            {
                "page_number": 1,
                "blocks": [
                    {"line": 1, "kind": "table_row", "table_group": "p1l1"},
                    {"line": 2, "kind": "table_row", "table_group": "p1l1"},
                ],
            }
        ],
    }
    structure = _make_structure(raw_pages, oracle_case)
    expected = evaluation._expanded_oracle(oracle_case, raw_pages)
    matched = {
        f"p{block['page_number']}l{block['line_number']}": block
        for block in structure["blocks"]
    }
    matched["p1l2"]["table_group_id"] = "split-table"
    matched["p1l2"]["table_row_index"] = 0

    result = evaluation._evaluate_table_grouping(
        expected=expected,
        matched_by_locator=matched,
    )
    assert result["denominator"] == 2
    assert result["mismatch_count"] == 1


def test_projection_audit_follows_blocks_to_candidates_and_outcomes() -> None:
    source = {
        "blocks": [
            {"block_id": "a", "kind": "paragraph"},
            {"block_id": "b", "kind": "table_row"},
            {"block_id": "boundary", "kind": "page_boundary"},
        ]
    }
    complete = {
        "candidate_projection": {
            "status": "executed_legacy_candidate_rules",
            "blocks": [
                {
                    "block_id": "a",
                    "projection_status": "candidate",
                    "participated": True,
                    "candidate_ids": ["C-1"],
                },
                {
                    "block_id": "b",
                    "projection_status": "filtered",
                    "participated": False,
                    "filter_reason": "header",
                    "candidate_ids": [],
                },
                {
                    "block_id": "boundary",
                    "projection_status": "filtered",
                    "participated": False,
                    "filter_reason": "synthetic",
                    "candidate_ids": [],
                },
            ],
            "candidates": [
                {
                    "candidate_id": "C-1",
                    "source_block_ids": ["a"],
                    "source_blocks": [{"block_id": "a"}],
                }
            ],
        },
        "final_requirement_extraction": {
            "status": "partial_first_pass",
            "complete": False,
            "candidate_results": [
                {
                    "candidate_id": "C-1",
                    "outcomes": [
                        {
                            "outcome": "not_requirement_under_local_rules",
                            "generated_ids": [],
                        }
                    ],
                }
            ],
            "requirement_ids": [],
            "scoring_item_ids": [],
        },
    }
    result = evaluation._evaluate_block_projection_audit(
        audit=complete,
        source_structure=source,
        actual_output_ids={"requirement_ids": [], "scoring_item_ids": []},
    )
    assert result["failure_count"] == 0
    assert result["candidate_projection"]["denominator"] == 2
    assert result["candidate_projection"]["candidate_count"] == 1
    assert result["candidate_projection"]["filtered_block_count"] == 1
    assert (
        result["candidate_projection"]["ignored_synthetic_block_record_count"] == 1
    )
    assert result["final_extraction"]["denominator"] == 1
    assert result["final_extraction"]["stage_status"] == "partial_first_pass"
    assert result["final_extraction"]["complete_claim"] is False

    missing_filter_reason = json.loads(json.dumps(complete))
    missing_filter_reason["candidate_projection"]["blocks"][1]["filter_reason"] = ""
    failed_filter = evaluation._evaluate_block_projection_audit(
        audit=missing_filter_reason,
        source_structure=source,
        actual_output_ids={"requirement_ids": [], "scoring_item_ids": []},
    )
    assert failed_filter["candidate_projection"]["unsupported_count"] > 0

    broken_source_mapping = json.loads(json.dumps(complete))
    broken_source_mapping["candidate_projection"]["candidates"][0][
        "source_block_ids"
    ] = ["missing"]
    failed_mapping = evaluation._evaluate_block_projection_audit(
        audit=broken_source_mapping,
        source_structure=source,
        actual_output_ids={"requirement_ids": [], "scoring_item_ids": []},
    )
    assert failed_mapping["candidate_projection"]["mismatch_count"] > 0

    missing_outcome = json.loads(json.dumps(complete))
    missing_outcome["final_requirement_extraction"]["candidate_results"] = []
    failed_outcome = evaluation._evaluate_block_projection_audit(
        audit=missing_outcome,
        source_structure=source,
        actual_output_ids={"requirement_ids": [], "scoring_item_ids": []},
    )
    assert failed_outcome["final_extraction"]["missing_candidate_result_count"] == 1
    assert failed_outcome["failure_count"] > 0

    generated_id_mismatch = json.loads(json.dumps(complete))
    final_stage = generated_id_mismatch["final_requirement_extraction"]
    final_stage["candidate_results"][0]["outcomes"][0] = {
        "outcome": "requirement_created",
        "generated_ids": ["R-1"],
    }
    final_stage["requirement_ids"] = ["R-1"]
    failed_generated_ids = evaluation._evaluate_block_projection_audit(
        audit=generated_id_mismatch,
        source_structure=source,
        actual_output_ids={"requirement_ids": [], "scoring_item_ids": []},
    )
    assert failed_generated_ids["final_extraction"]["mismatch_count"] > 0


@pytest.mark.parametrize(
    "status",
    ["not_run_explicit_input", "bypassed_explicit_input", "future_unknown"],
)
def test_candidate_outcome_audit_rejects_unknown_or_unrun_status(
    status: str,
) -> None:
    stage = {
        "status": status,
        "complete": False,
        "candidate_results": [],
        "requirement_ids": [],
        "scoring_item_ids": [],
    }
    result = evaluation._candidate_outcomes_result(
        stage=stage,
        candidate_ids=[],
        actual_output_ids={"requirement_ids": [], "scoring_item_ids": []},
    )

    assert result["stage_status_failure_count"] == 1
    assert result["failure_count"] > 0


def test_candidate_outcomes_allow_created_and_merged_references_to_same_id() -> None:
    stage = {
        "status": "partial_first_pass",
        "complete": False,
        "candidate_results": [
            {
                "candidate_id": "C-created",
                "outcomes": [
                    {"outcome": "requirement_created", "generated_ids": ["R-1"]}
                ],
            },
            {
                "candidate_id": "C-merged",
                "outcomes": [
                    {
                        "outcome": "merged_into_existing_requirement",
                        "generated_ids": ["R-1"],
                    }
                ],
            },
        ],
        "requirement_ids": ["R-1"],
        "scoring_item_ids": [],
    }
    result = evaluation._candidate_outcomes_result(
        stage=stage,
        candidate_ids=["C-created", "C-merged"],
        actual_output_ids={"requirement_ids": ["R-1"], "scoring_item_ids": []},
    )

    assert result["failure_count"] == 0


@pytest.mark.parametrize(
    ("outcome_name", "category", "identifier"),
    [
        ("requirement_created", "requirement_ids", "R-1"),
        ("merged_into_existing_requirement", "requirement_ids", "R-1"),
        ("scoring_item_created", "scoring_item_ids", "S-1"),
        ("merged_into_existing_scoring_item", "scoring_item_ids", "S-1"),
    ],
)
def test_created_and_merged_outcomes_require_category_ids(
    outcome_name: str,
    category: str,
    identifier: str,
) -> None:
    requirement_ids = [identifier] if category == "requirement_ids" else []
    scoring_item_ids = [identifier] if category == "scoring_item_ids" else []
    stage = {
        "status": "partial_first_pass",
        "complete": False,
        "candidate_results": [
            {
                "candidate_id": "C-1",
                "outcomes": [
                    {"outcome": outcome_name, "generated_ids": [identifier]}
                ],
            }
        ],
        "requirement_ids": requirement_ids,
        "scoring_item_ids": scoring_item_ids,
    }
    result = evaluation._candidate_outcomes_result(
        stage=stage,
        candidate_ids=["C-1"],
        actual_output_ids={
            "requirement_ids": requirement_ids,
            "scoring_item_ids": scoring_item_ids,
        },
    )

    assert result["failure_count"] == 0


def test_candidate_outcome_labels_reject_unknowns_bad_categories_and_duplicate_ids(
) -> None:
    def evaluate(outcome_name: str, generated_ids: list[str], category: str) -> dict:
        requirement_ids = (
            generated_ids.copy() if category == "requirement_ids" else []
        )
        scoring_item_ids = (
            generated_ids.copy() if category == "scoring_item_ids" else []
        )
        stage = {
            "status": "partial_first_pass",
            "complete": False,
            "candidate_results": [
                {
                    "candidate_id": "C-1",
                    "outcomes": [
                        {
                            "outcome": outcome_name,
                            "generated_ids": generated_ids,
                        }
                    ],
                }
            ],
            "requirement_ids": requirement_ids,
            "scoring_item_ids": scoring_item_ids,
        }
        return evaluation._candidate_outcomes_result(
            stage=stage,
            candidate_ids=["C-1"],
            actual_output_ids={
                "requirement_ids": requirement_ids,
                "scoring_item_ids": scoring_item_ids,
            },
        )

    no_id_outcomes = (
        ("not_requirement_under_local_rules", "requirement_ids", "R-1"),
        ("score_candidate_without_reliable_ceiling", "scoring_item_ids", "S-1"),
        ("not_reconciled_after_grouping", "requirement_ids", "R-1"),
    )
    for outcome_name, category, identifier in no_id_outcomes:
        assert evaluate(outcome_name, [], category)["failure_count"] == 0
        assert evaluate(outcome_name, [identifier], category)["mismatch_count"] > 0

    unsupported_aliases = (
        "score_without_reliable_upper_bound",
        "scoring_item_without_reliable_upper_bound",
        "not_reconciled",
    )
    for outcome_name in unsupported_aliases:
        assert evaluate(outcome_name, [], "requirement_ids")["unsupported_count"] > 0

    assert evaluate("future_outcome", [], "requirement_ids")["unsupported_count"] > 0
    assert evaluate("requirement_created", [], "requirement_ids")["mismatch_count"] > 0
    assert evaluate("requirement_created", ["R-1"], "scoring_item_ids")[
        "mismatch_count"
    ] > 0
    assert evaluate("requirement_created", ["R-1", "R-1"], "requirement_ids")[
        "mismatch_count"
    ] > 0


@pytest.mark.asyncio
async def test_decomposition_failure_never_falls_back_to_intake_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_index = evaluation._load_json(evaluation.FIXTURE_PATH)
    fixture = fixture_index["cases"][0]
    source_bytes = (evaluation.ROOT / fixture["source_path"]).read_bytes()
    source_text = source_bytes.decode("utf-8")
    raw_pages = source_text.split(evaluation.BOUNDARY)
    page_values = [
        {"page_number": index, "text": page}
        for index, page in enumerate(raw_pages, start=1)
    ]

    class FakeRegistry:
        def register(self, **kwargs: Any) -> Any:
            return SimpleNamespace(
                file=SimpleNamespace(checksum=evaluation._sha256(kwargs["content"]))
            )

        def file_version_token(self, _file_id: str) -> str:
            return "test-version"

        def parse(self, _file_id: str) -> dict[str, Any]:
            return {
                "pages": page_values,
                "document_structure": {
                    "pages": [
                        {"page_number": item["page_number"], "raw_text": item["text"]}
                        for item in page_values
                    ],
                    "blocks": [
                        {"block_id": f"source-{index}", "kind": "paragraph"}
                        for index, _ in enumerate(raw_pages, start=1)
                    ],
                },
            }

    intake_structure = {"blocks": [{"block_id": "intake-only"}]}
    decomposition_structure = {"blocks": [{"block_id": "failed-decomposition"}]}

    class FakeRuntime:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        async def run(self, _request: Any) -> Any:
            return SimpleNamespace(
                execution_status="partial",
                steps=[
                    SimpleNamespace(
                        skill_name="tender-intake",
                        result=SimpleNamespace(
                            status="success",
                            data={"document_structures": [intake_structure]},
                        ),
                    ),
                    SimpleNamespace(
                        skill_name="tender-decomposition",
                        result=SimpleNamespace(
                            status="failed",
                            data={"document_structures": [decomposition_structure]},
                        ),
                    ),
                ],
            )

    monkeypatch.setattr(evaluation, "ProjectFileRegistry", FakeRegistry)
    monkeypatch.setattr(evaluation, "AgentRuntime", FakeRuntime)
    monkeypatch.setattr(
        evaluation, "build_default_registry", lambda **_kwargs: object()
    )

    result = await evaluation._run_case(fixture, {"pages": []})

    assert result["structure"]["status"] == "failed"
    assert result["structure"]["intake_structure_count"] == 1
    assert result["structure"]["decomposition_structure_count"] == 1
    assert "wrong_kind" not in result["structure"]
    assert result["runtime"]["full_chain_structure_exposure"] is False


@pytest.mark.asyncio
async def test_real_runtime_executes_both_skills_and_is_fully_captured() -> None:
    fixture_index = evaluation._load_json(evaluation.FIXTURE_PATH)
    oracle = evaluation._load_json(evaluation.ORACLE_PATH)
    fixture_case = fixture_index["cases"][0]
    oracle_case = next(
        case for case in oracle["cases"] if case["case_id"] == fixture_case["case_id"]
    )

    result = await evaluation._run_case(fixture_case, oracle_case)

    assert result["business_layer"] == "not_run"
    assert result["registry_pages"]["actual_page_count"] == fixture_case[
        "expected_pages"
    ]
    assert isinstance(
        result["registry_pages"]["page_texts_match_raw_exactly"], bool
    )
    assert result["registry_pages"]["page_texts_match_raw_exactly"] is (
        not result["registry_pages"]["mismatched_page_numbers"]
    )
    assert all(
        1 <= page <= fixture_case["expected_pages"]
        for page in result["registry_pages"]["mismatched_page_numbers"]
    )
    assert result["runtime"]["intake_step_status"] != "not_run"
    assert result["runtime"]["decomposition_step_status"] != "not_run"
    assert result["runtime"]["full_chain_structure_exposure"] is True
    assert result["runtime"]["complete_runtime_output"] is not None
    assert result["runtime"]["registry_parse_artifact"] is not None
    summary = evaluation._aggregate([result])
    assert summary["wrong_kind"]["denominator"] == result["structure"][
        "expected_block_count"
    ]
    assert summary["uncertain_relation_needs_review"]["denominator"] == 1
    assert summary["not_run_cases"]["denominator"] == 1


def test_cli_refuses_to_overwrite_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "existing-report.json"
    output.write_text('{"preserve": true}\n', encoding="utf-8")

    async def unexpected_run() -> dict[str, Any]:
        raise AssertionError("evaluation must not start for an existing output path")

    monkeypatch.setattr(evaluation, "run_evaluation", unexpected_run)
    with pytest.raises(SystemExit) as error:
        evaluation.main(["--output", str(output)])

    assert error.value.code == 2
    assert json.loads(output.read_text(encoding="utf-8")) == {"preserve": True}


def test_cli_defaults_to_stdout_and_writes_only_new_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def sample_report() -> dict[str, Any]:
        return {
            "schema": "test-report",
            "summary": {
                "structural_regression_status": "passed_on_selected_public_cases",
                "not_run": 0,
                "failed": 0,
            },
        }

    monkeypatch.setattr(evaluation, "run_evaluation", sample_report)
    assert evaluation.main([]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "schema": "test-report",
        "summary": {
            "structural_regression_status": "passed_on_selected_public_cases",
            "not_run": 0,
            "failed": 0,
        },
    }

    output = tmp_path / "new-report.json"
    assert evaluation.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "schema": "test-report",
        "summary": {
            "structural_regression_status": "passed_on_selected_public_cases",
            "not_run": 0,
            "failed": 0,
        },
    }


@pytest.mark.parametrize(
    ("status", "not_run", "failed"),
    [
        ("not_run", 3, 0),
        ("not_passed", 0, 0),
        ("not_passed", 0, 1),
        ("passed_on_selected_public_cases", 1, 0),
    ],
)
def test_cli_exits_nonzero_for_not_run_or_failed_evaluation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: str,
    not_run: int,
    failed: int,
) -> None:
    async def unsuccessful_report() -> dict[str, Any]:
        return {
            "summary": {
                "structural_regression_status": status,
                "not_run": not_run,
                "failed": failed,
            }
        }

    monkeypatch.setattr(evaluation, "run_evaluation", unsuccessful_report)
    assert evaluation.main([]) == 1
    assert json.loads(capsys.readouterr().out)["summary"][
        "structural_regression_status"
    ] == status
