from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts import run_document_relations_negation_eval as evaluation


def _case(case_id: str) -> dict[str, Any]:
    return next(case for case in evaluation.FIXED_CASES if case["case_id"] == case_id)


def _reference(quote: str) -> dict[str, str]:
    return {"quote": quote}


def _negative_graph() -> dict[str, Any]:
    quote = "以下两项材料不需要同时提交：（1）营业执照；（2）审计报告。"
    return {
        "condition_nodes": [
            {
                "node_id": "license",
                "op": "ATOM",
                "status": "confirmed",
                "text": "营业执照",
                "source_block_ids": ["license-block"],
            },
            {
                "node_id": "audit",
                "op": "ATOM",
                "status": "confirmed",
                "text": "审计报告",
                "source_block_ids": ["audit-block"],
            },
        ],
        "block_relations": [
            {
                "block_id": "license-block",
                "list_membership_relations": [{"status": "confirmed"}],
                "scope_relations": [
                    {
                        "operator": "UNRESOLVED",
                        "status": "candidate",
                        "scope_status": "candidate",
                        "target_node_ids": [],
                        "target_block_ids": [],
                        "source_references": [_reference(quote)],
                        "operator_relation": {
                            "status": "candidate",
                            "source_references": [_reference("不需要")],
                        },
                    }
                ],
            }
        ],
    }


def _positive_candidate_graph() -> dict[str, Any]:
    graph = _negative_graph()
    graph["condition_nodes"] = [
        {
            "node_id": "license",
            "op": "ATOM",
            "status": "candidate",
            "text": "营业执照",
            "source_block_ids": ["license-block"],
        },
        {
            "node_id": "audit",
            "op": "ATOM",
            "status": "candidate",
            "text": "审计报告",
            "source_block_ids": ["audit-block"],
        },
        {
            "node_id": "group",
            "op": "AND",
            "status": "candidate",
            "children": ["license", "audit"],
            "operator_relation": {
                "status": "candidate",
                "source_references": [_reference("须同时提交")],
            },
            "scope_relation": {
                "status": "candidate",
                "target_node_ids": ["license", "audit"],
                "source_references": [_reference("以下两项材料")],
            },
        },
    ]
    return graph


def test_fixed_cases_have_24_negative_and_6_positive_with_true_inline_lines() -> None:
    cases = evaluation.FIXED_CASES
    assert len(cases) == 30
    assert sum(case["polarity"] == "negative" for case in cases) == 24
    assert sum(case["polarity"] == "positive" for case in cases) == 6
    for case in cases:
        if case["placement"] == "inline":
            assert "\n" not in case["input_text"]


def test_confirmed_structural_list_membership_does_not_fail_negative() -> None:
    result = evaluation._score_semantics(
        _case("negative-inline-not-needed"), _negative_graph()
    )

    assert result["status"] == "passed", result["errors"]


def test_negative_rejects_confirmed_group_channels_even_without_targets() -> None:
    graph = _negative_graph()
    graph["condition_nodes"].append(
        {
            "node_id": "candidate-group",
            "op": "AND",
            "status": "candidate",
            "children": [],
            "operator_relation": {
                "status": "confirmed",
                "source_references": [_reference("同时提交")],
            },
            "scope_relation": {
                "status": "confirmed",
                "target_node_ids": [],
                "source_references": [_reference("两项材料")],
            },
        }
    )

    result = evaluation._score_semantics(
        _case("negative-inline-not-needed"), graph
    )

    assert result["status"] == "failed"
    assert any(
        "group/operator/scope channel is confirmed" in error
        for error in result["errors"]
    )


def test_negative_requires_negation_evidence_on_its_own_channels() -> None:
    graph = _negative_graph()
    relation = graph["block_relations"][0]["scope_relations"][0]
    relation["operator_relation"]["source_references"] = [
        _reference("同时提交以下两项材料")
    ]

    wrapper_only = evaluation._score_semantics(
        _case("negative-inline-not-needed"), graph
    )
    assert wrapper_only["status"] == "failed"
    assert any("nested NOT operator" in error for error in wrapper_only["errors"])

    relation["source_references"] = [_reference("同时提交以下两项材料")]
    relation["operator_relation"]["source_references"] = [
        _reference("同时提交以下两项材料")
    ]

    result = evaluation._score_semantics(
        _case("negative-inline-not-needed"), graph
    )

    assert result["status"] == "failed"
    assert any("negated instruction" in error for error in result["errors"])


def test_positive_rejects_all_candidate_graph() -> None:
    result = evaluation._score_semantics(
        _case("positive-inline-and"), _positive_candidate_graph()
    )

    assert result["status"] == "failed"
    assert any("confirmed material leaves" in error for error in result["errors"])
    assert any(
        "exactly one confirmed two-leaf group" in error
        for error in result["errors"]
    )


def test_cli_refuses_existing_output_before_running_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "existing.json"
    output.write_text("keep", encoding="utf-8")

    def unexpected_run() -> dict[str, Any]:
        raise AssertionError("existing output must be rejected first")

    monkeypatch.setattr(evaluation, "run_evaluation", unexpected_run)
    with pytest.raises(SystemExit) as error:
        evaluation.main(["--output", str(output)])

    assert error.value.code == 2
    assert output.read_text(encoding="utf-8") == "keep"
