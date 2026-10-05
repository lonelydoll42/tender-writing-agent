from __future__ import annotations

from typing import Any

import pytest

from scripts.run_raw_file_eval import (
    EXPECTED_WORKFLOW,
    MUST_NOT_PASS,
    _requirement_metrics,
    run_raw_file_eval,
)


@pytest.fixture(scope="module")
def report() -> dict[str, Any]:
    return run_raw_file_eval()


def _case(report: dict[str, Any], case_id: str) -> dict[str, Any]:
    return next(item for item in report["cases"] if item["case_id"] == case_id)


def test_minimal_raw_files_reach_full_runtime_and_reproduce_parser_fixes(
    report: dict[str, Any],
) -> None:
    minimal = _case(report, "minimal_repro")
    assert minimal["execution_status"] in {"completed", "partial"}
    assert all(step in minimal["workflow_steps"] for step in EXPECTED_WORKFLOW)
    assert minimal["decomposition_extraction_complete"] is False
    assert minimal["business_status"] == "needs_review"
    assert minimal["scoped_gate_passed"] is False
    assert any(
        "独立承担民事责任" in item["description"]
        and item["category"] == "qualification"
        for item in minimal["requirements"]
    )
    assert [item["max_score"] for item in minimal["scoring_items"]] == [10.0]

    cross_page = _case(report, "cross_page_score")
    score = next(
        item for item in cross_page["scoring_items"] if item["max_score"] == 10.0
    )
    assert {
        item["page"] for item in score["source_references"]
    } == {1, 2, 3}


def test_conflicting_score_caps_warn_and_do_not_emit_a_score_item(
    report: dict[str, Any],
) -> None:
    case = _case(report, "conflicting_scores")
    assert case["execution_status"] in {"completed", "partial"}
    assert "compliance-review" in case["workflow_steps"]
    assert case["scoring_items"] == []
    assert len(case["decomposition_warnings"]) >= 2
    assert case["business_status"] == "needs_review"


def test_amount_units_and_unknown_amount_fields_are_reported_separately(
    report: dict[str, Any],
) -> None:
    minimal = _case(report, "minimal_repro")
    materials = {item["title"]: item["metadata"] for item in minimal["materials"]}
    assert materials["contract_135wan.txt"]["amount"] == "1350000"
    assert materials["bond_40000.txt"]["amount"] == "40000"

    metric = report["metrics"]["amount_unknown_safety"]
    assert metric["denominator"] == 2
    assert metric["unsafe_extraction_count"] == 0
    assert all(item["amount_emitted"] is None for item in metric["samples"])


def test_correction_notice_is_not_auto_merged_and_requires_review(
    report: dict[str, Any],
) -> None:
    case = _case(report, "correction_conflict")
    assert case["execution_status"] in {"completed", "partial"}
    assert case["business_status"] == "needs_review"
    assert case["correction_handling"]["automatic_override_resolution"] == (
        "not_attempted"
    )
    assert case["correction_handling"]["human_review_requested"] is True
    assert case["correction_handling"]["source_values_preserved"] is True


def test_iso27001_requirement_does_not_pass_with_only_iso9001_material(
    report: dict[str, Any],
) -> None:
    case = _case(report, "iso_standard_mismatch")
    assert "iso_standard_mismatch" in MUST_NOT_PASS
    assert case["execution_status"] in {"completed", "partial"}
    assert all(step in case["workflow_steps"] for step in EXPECTED_WORKFLOW)
    assert case["business_status"] in {"failed", "needs_review"}
    assert case["scoped_gate_passed"] is False
    assert case["bid_feasibility"]["decision"] != "bid"

    requirement = next(
        item
        for item in case["requirements"]
        if "ISO27001" in item["description"]
    )
    assert requirement["evidence_required"] == ["ISO27001"]
    assert requirement["check_rule"]["rule_ast"]["evidence_types"] == [
        "ISO27001"
    ]
    requirement_match = next(
        item
        for item in case["evidence_matches"]
        if item["requirement_id"] == requirement["requirement_id"]
    )
    assert requirement_match["status"] != "matched"

    score = next(
        item
        for item in case["scoring_items"]
        if "ISO认证评分" in item["criteria"]
    )
    score_match = next(
        item
        for item in case["evidence_matches"]
        if item["requirement_id"] == score["item_id"]
    )
    assert score_match["status"] == "matched"

    iso9001 = next(
        item
        for item in case["materials"]
        if item["title"] == "ISO9001证明.txt"
    )
    assert iso9001["material_type"] == "certification"
    assert iso9001["metadata"]["verification_status"] == "verified"

    metric = report["metrics"]["hard_false_release"]
    evaluated_case = next(
        item
        for item in metric["evaluated_cases"]
        if item["case_id"] == "iso_standard_mismatch"
    )
    assert evaluated_case["false_release"] is False


def test_requirement_metric_requires_all_constraint_groups() -> None:
    ground_truth = {
        "mandatory_requirements": [
            {
                "id": "Q3",
                "requirement": "2023年以来至少1个同类项目合同额不低于100万元",
            },
            {
                "id": "Q5",
                "requirement": "项目经理证书及2026年3月至8月连续社保",
            },
        ]
    }
    partial_case = {
        "requirements": [
            {
                "requirement_id": "R-1",
                "description": "项目经理应满足项目管理要求",
            },
            {
                "requirement_id": "R-2",
                "description": "同类项目合同额不低于100万元",
            },
        ]
    }

    metric = _requirement_metrics(partial_case, ground_truth)

    assert metric["denominator"] == 2
    assert metric["matched_count"] == 0
    assert metric["omission_count"] == 2
    by_id = {item["requirement_id"]: item for item in metric["items"]}
    assert by_id["Q3"]["status"] == "missing"
    assert by_id["Q3"]["missing_groups"]
    assert by_id["Q3"]["ambiguous_candidates"][0]["requirement_id"] == "R-2"
    assert by_id["Q3"]["ambiguous_candidates"][0]["counted_as_success"] is False
    assert by_id["Q5"]["status"] == "missing"
    assert by_id["Q5"]["ambiguous_candidates"][0]["requirement_id"] == "R-1"
    assert metric["executable_rule_completeness"] == {
        "status": "not_measured",
        "value": None,
    }


def test_unrun_pdf_requirement_metric_is_null_not_a_zero_error_result() -> None:
    metric = _requirement_metrics(
        None,
        {"mandatory_requirements": [{"id": "Q1", "requirement": "营业执照"}]},
    )

    assert metric["status"] == "not_run"
    assert metric["denominator"] == 0
    assert metric["matched_count"] is None
    assert metric["omission_count"] is None
    assert metric["omission_rate"] is None


def test_hard_false_release_denominator_excludes_inconclusive_cases(
    report: dict[str, Any],
) -> None:
    metric = report["metrics"]["hard_false_release"]
    assert metric["false_release_count"] == 0
    assert metric["denominator"] >= 3
    assert metric["denominator"] + metric["inconclusive_count"] == len(
        MUST_NOT_PASS
    )
    assert "不证明资格识别准确率" in metric["interpretation"]


def test_pdf_metric_and_ocr_simulation_are_explicit_about_boundaries(
    report: dict[str, Any],
) -> None:
    assert report["input_policy"]["ground_truth_loaded_after_runtime"] is True
    assert report["input_policy"]["ground_truth_registered_as_input"] is False
    assert report["input_policy"]["structured_requirement_or_material_inputs"] is False
    assert report["raw_local_extraction_policy"]["extraction_complete"] is False
    assert report["raw_local_extraction_policy"]["business_status"] == (
        "needs_review"
    )
    assert not any(
        "ground_truth" in file_name or file_name.startswith("00_")
        for case in report["cases"]
        for file_name in case.get("source_files") or []
    )
    requirement_metric = report["metrics"]["requirement_omission"]
    if report["poppler"]["available"]:
        assert requirement_metric["status"] == "measured"
        assert requirement_metric["denominator"] == requirement_metric["expected_count"]
    else:
        assert requirement_metric["status"] == "not_run"
        assert requirement_metric["denominator"] == 0
        assert requirement_metric["omission_count"] is None

    simulated = report["simulated_ocr"]
    assert simulated["is_real_ocr_accuracy_measurement"] is False
    assert "+08:00" in report["generated_at"]
    assert report["timezone"] == "Asia/Shanghai"
