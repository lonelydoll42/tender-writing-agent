from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.run_reliability_followup_eval import (
    _case_evaluation,
    _scanner_coverage,
    run_reliability_followup_eval,
)


@pytest.fixture(scope="module")
def report() -> dict[str, Any]:
    return run_reliability_followup_eval()


def _case(report: dict[str, Any], domain: str, case_id: str) -> dict[str, Any]:
    cases = report["metrics"][domain]["cases"]
    return next(item for item in cases if item["case_id"] == case_id)


def test_oracle_is_isolated_and_scope_is_limited(report: dict[str, Any]) -> None:
    assert report["input_policy"] == {
        "oracle_loaded_after_runtime": True,
        "oracle_registered_or_injected_as_input": False,
        "fixtures_contain_expected_labels": False,
        "mock_model_returns_only_fixture_output": True,
        "real_model_called": False,
        "real_ocr_called": False,
    }
    assert report["raw_file_baseline"]["status"] == "not_retested_in_this_followup"
    assert report["raw_file_baseline"]["constraint_text_coverage"] == {
        "matched": 4,
        "denominator": 10,
    }
    assert report["raw_file_baseline"]["known_omissions"] == 6
    assert report["raw_file_baseline"]["production_extraction_complete"] is False


@pytest.mark.parametrize(
    ("domain", "positive_denominator", "negative_denominator"),
    [
        ("writing", 6, 12),
        ("runtime", 2, 7),
    ],
)
def test_all_fixed_positive_and_negative_cases_are_classified(
    report: dict[str, Any],
    domain: str,
    positive_denominator: int,
    negative_denominator: int,
) -> None:
    metrics = report["metrics"][domain]
    assert metrics["positive_denominator"] == positive_denominator
    assert metrics["negative_denominator"] == negative_denominator
    assert metrics["not_run_count"] == 0
    assert metrics["inconclusive_count"] == 0
    assert metrics["correct_pass_rate"] == {
        "count": positive_denominator,
        "denominator": positive_denominator,
        "rate": 1.0,
    }
    assert metrics["false_block_rate"] == {
        "count": 0,
        "denominator": positive_denominator,
        "rate": 0.0,
    }
    assert metrics["false_release_count"] == 0
    assert metrics["false_release_rate"] == {
        "count": 0,
        "denominator": negative_denominator,
        "rate": 0.0,
    }


def test_writing_regressions_and_positive_boundaries(report: dict[str, Any]) -> None:
    negative_ids = (
        "W-NEG-ISO-NUMBER-COLLISION",
        "W-NEG-BIDDER-SUBJECT-MISMATCH",
        "W-NEG-BIDDER-SUBJECT-UNKNOWN",
        "W-NEG-BIDDER-SUBJECT-CONFLICT",
        "W-NEG-UNSUPPORTED-GOVERNMENT-CASES",
        "W-NEG-CMMI-LEVEL-MISMATCH",
        "W-NEG-CMMI-CERT-NUMBER-COLLISION",
        "W-NEG-ISO-METADATA-BODY-CONFLICT",
        "W-NEG-HOLDER-METADATA-BODY-CONFLICT",
        "W-NEG-SAME-NAME-DIFFERENT-CREDIT-CODE",
        "W-NEG-CROSS-SUBJECT-CASE-COUNT",
        "W-NEG-CROSS-SUBJECT-CONTRACT-AMOUNT",
    )
    for case_id in negative_ids:
        result = _case(report, "writing", case_id)
        assert result["business_status"] in {"failed", "needs_review", "not_checked"}
        assert result["evaluation"] == "correct_block"
        assert result["submission_allowed"] is False

    positive_ids = (
        "W-POS-SAME-SUBJECT-ISO27001",
        "W-POS-SAME-SUBJECT-CMMI3",
        "W-POS-EVIDENCED-CHINESE-CASE-COUNT",
        "W-POS-SAME-SUBJECT-CONTRACT-AMOUNT",
        "W-POS-TENDER-REQUIREMENT-PARAPHRASE",
        "W-POS-BENIGN-SECTION",
    )
    for case_id in positive_ids:
        result = _case(report, "writing", case_id)
        assert result["business_status"] == "passed"
        assert result["skill_status"] == "success"
        assert result["evaluation"] == "correct_pass"


def test_cmmi_number_collision_is_distinct_from_level_mismatch(
    report: dict[str, Any],
) -> None:
    collision = _case(report, "writing", "W-NEG-CMMI-CERT-NUMBER-COLLISION")
    assert collision["business_status"] in {"failed", "needs_review", "not_checked"}
    claim = next(
        item
        for item in collision["claim_evidence_mapping"]
        if item["category"] == "certification"
    )
    assert claim["standard_check"]["status"] == "mismatch"

    valid = _case(report, "writing", "W-POS-SAME-SUBJECT-CMMI3")
    assert valid["business_status"] == "passed"
    claim = next(
        item
        for item in valid["claim_evidence_mapping"]
        if item["category"] == "certification"
    )
    assert claim["standard_check"]["status"] == "matched"
    assert claim["subject_check"]["status"] == "matched"


def test_same_company_name_with_conflicting_registration_code_is_blocked(
    report: dict[str, Any],
) -> None:
    result = _case(
        report,
        "writing",
        "W-NEG-SAME-NAME-DIFFERENT-CREDIT-CODE",
    )
    claim = next(
        item
        for item in result["claim_evidence_mapping"]
        if item["category"] == "certification"
    )
    assert claim["subject_check"]["status"] == "conflict"


def test_missing_claim_coverage_contract_is_not_reported_as_success() -> None:
    observation = {
        "execution_status": "completed",
        "business_status": "passed",
        "scanner_coverage": _scanner_coverage(
            {"summary": {"claim_scan_coverage_status": "complete"}}
        ),
    }
    assert observation["scanner_coverage"]["status"] == "not_reported"
    assert (
        _case_evaluation(
            observation,
            {
                "domain": "writing",
                "label": "positive",
                "must_scan_claim": True,
            },
        )
        == "inconclusive"
    )


def test_new_counterexamples_keep_fixed_oracle_polarity() -> None:
    benchmark_root = (
        Path(__file__).resolve().parents[2]
        / "benchmarks"
        / "reliability_followup"
    )
    manifest = json.loads((benchmark_root / "cases.json").read_text(encoding="utf-8"))
    oracle = json.loads((benchmark_root / "oracle.json").read_text(encoding="utf-8"))
    manifest_by_id = {item["case_id"]: item for item in manifest["cases"]}
    oracle_by_id = {item["case_id"]: item for item in oracle["cases"]}

    assert len(manifest["cases"]) == 27
    assert sum(item["domain"] == "writing" for item in manifest["cases"]) == 18
    assert sum(item["domain"] == "runtime" for item in manifest["cases"]) == 9
    for case_id in (
        "W-NEG-CROSS-SUBJECT-CASE-COUNT",
        "W-NEG-CROSS-SUBJECT-CONTRACT-AMOUNT",
    ):
        assert manifest_by_id[case_id]["domain"] == "writing"
        assert oracle_by_id[case_id]["label"] == "negative"
        assert oracle_by_id[case_id]["expected"] == "must_block"
        assert oracle_by_id[case_id]["must_scan_claim"] is True

    amount_positive = "W-POS-SAME-SUBJECT-CONTRACT-AMOUNT"
    assert manifest_by_id[amount_positive]["domain"] == "writing"
    assert oracle_by_id[amount_positive]["label"] == "positive"
    assert oracle_by_id[amount_positive]["expected"] == "must_pass"
    assert oracle_by_id[amount_positive]["must_scan_claim"] is True

    invalid_scope = "R-NEG-INVALID-WRITING-SCOPE"
    assert manifest_by_id[invalid_scope]["domain"] == "runtime"
    assert oracle_by_id[invalid_scope]["label"] == "negative"
    assert oracle_by_id[invalid_scope]["expected"] == "must_not_invoke_writer"
    assert oracle_by_id[invalid_scope]["expected_scope_reason_codes"] == [
        "writing_scope_unresolvable"
    ]


def test_chinese_quantity_claim_has_an_explicit_scan_coverage_observation(
    report: dict[str, Any],
) -> None:
    for case_id in (
        "W-NEG-UNSUPPORTED-GOVERNMENT-CASES",
        "W-POS-EVIDENCED-CHINESE-CASE-COUNT",
        "W-NEG-CROSS-SUBJECT-CASE-COUNT",
        "W-NEG-CROSS-SUBJECT-CONTRACT-AMOUNT",
        "W-POS-SAME-SUBJECT-CONTRACT-AMOUNT",
    ):
        result = _case(report, "writing", case_id)
        coverage = result["scanner_coverage"]
        assert result["claim_verification"] is not None
        assert coverage["status"] == "complete"
        assert coverage["claim_verification_status"] in {
            "verified",
            "needs_review",
        }
        assert coverage["coverage"]["scanned_sentence_count"] >= 1
        assert coverage["coverage"]["recognized_claim_count"] >= 1
        assert coverage["scanned_claim_count"] >= 1
    negative = _case(report, "writing", "W-NEG-UNSUPPORTED-GOVERNMENT-CASES")
    assert negative["claim_verification"]["status"] == "needs_review"
    assert negative["unsupported_claim_count"] >= 1
    assert any(
        claim["category"] == "case_quantity" and claim["status"] == "unsupported"
        for claim in negative["claim_evidence_mapping"]
    )
    positive = _case(report, "writing", "W-POS-EVIDENCED-CHINESE-CASE-COUNT")
    assert positive["claim_verification"]["status"] == "verified"
    assert any(
        claim["category"] == "case_quantity" and claim["status"] == "supported"
        for claim in positive["claim_evidence_mapping"]
    )
    for case_id, category in (
        ("W-NEG-CROSS-SUBJECT-CASE-COUNT", "case_quantity"),
        ("W-NEG-CROSS-SUBJECT-CONTRACT-AMOUNT", "amount"),
    ):
        result = _case(report, "writing", case_id)
        assert result["claim_verification"]["status"] == "needs_review"
        assert any(
            claim["category"] == category and claim["status"] == "unsupported"
            for claim in result["claim_evidence_mapping"]
        )


def test_contract_amount_same_subject_positive_and_cross_subject_negative(
    report: dict[str, Any],
) -> None:
    negative = _case(
        report,
        "writing",
        "W-NEG-CROSS-SUBJECT-CONTRACT-AMOUNT",
    )
    positive = _case(
        report,
        "writing",
        "W-POS-SAME-SUBJECT-CONTRACT-AMOUNT",
    )
    negative_claim = next(
        item
        for item in negative["claim_evidence_mapping"]
        if item["category"] == "amount"
    )
    positive_claim = next(
        item
        for item in positive["claim_evidence_mapping"]
        if item["category"] == "amount"
    )
    assert negative_claim["status"] == "unsupported"
    assert positive_claim["status"] == "supported"
    assert positive["business_status"] == "passed"


def test_runtime_scope_negatives_block_before_any_writer_or_model_call(
    report: dict[str, Any],
) -> None:
    negative_ids = (
        "R-NEG-CROSS-PROJECT",
        "R-NEG-REQUIREMENT-CONTENT-CHANGED",
        "R-NEG-REQUIREMENT-SCORING-ID-COLLISION",
        "R-NEG-SOURCE-VERSION-CHANGED",
        "R-NEG-WRITING-SCOPE-EXPANDED",
        "R-NEG-FORGED-APPROVAL",
        "R-NEG-INVALID-WRITING-SCOPE",
    )
    for case_id in negative_ids:
        result = _case(report, "runtime", case_id)
        assert result["writer_invocation_count"] == 0
        assert result["model_call_count"] == 0
        assert result["evaluation"] == "correct_block"
        assert result["scope_rejection_reasons"], case_id
        actual_codes = {
            item["code"] for item in result["scope_rejection_reasons"]
        }
        expected_codes = set(
            result["oracle_assertions"]["expected_scope_reason_codes"]
        )
        assert expected_codes <= actual_codes, case_id

    runtime = report["metrics"]["runtime"]
    assert runtime["writer_invocation_count"] == 2
    assert runtime["model_call_count"] == 2


def test_same_id_requirement_and_unreviewed_scoring_item_is_a_fixed_negative(
    report: dict[str, Any],
) -> None:
    result = _case(
        report,
        "runtime",
        "R-NEG-REQUIREMENT-SCORING-ID-COLLISION",
    )
    assert result["review_business_status"] == "needs_review"
    assert result["review_scope_binding_status"] == "not_bound"
    assert result["writer_invocation_count"] == 0
    assert result["model_call_count"] == 0
    assert result["evaluation"] == "correct_block"
    assert result["scope_rejection_reasons"]
    assert "requirement_scoring_id_collision" in {
        item["code"] for item in result["scope_rejection_reasons"]
    }


def test_invalid_writing_scope_is_not_authorized_or_run(
    report: dict[str, Any],
) -> None:
    result = _case(report, "runtime", "R-NEG-INVALID-WRITING-SCOPE")
    assert result["review_scope_binding_status"] == "not_bound"
    assert result["writer_invocation_count"] == 0
    assert result["model_call_count"] == 0
    assert result["evaluation"] == "correct_block"
    assert "writing_scope_unresolvable" in {
        item["code"] for item in result["scope_rejection_reasons"]
    }


def test_scope_collision_fixture_keeps_typed_targets_distinct() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "benchmarks"
        / "reliability_followup"
        / "fixtures"
        / "runtime.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))["cases"][
        "requirement_scoring_id_collision"
    ]
    review = fixture["review_input"]
    writer = fixture["writer_input"]

    for payload in (review, writer):
        assert payload["requirements"][0]["requirement_id"] == "SAME"
        assert payload["scoring_items"][0]["item_id"] == "SAME"
        assert payload["scoring_items"][0]["max_score"] == 100
        assert payload["sections"][0]["requirement_ids"] == ["SAME"]
        assert payload["sections"][0]["scoring_item_ids"] == ["SAME"]
    assert review["requirements"][0]["description"] != (
        review["scoring_items"][0]["criteria"]
    )
    assert review["ledger"]["entries"] == [
        {
            "requirement_id": "SAME",
            "item_type": "requirement",
            "mandatory": True,
            "status": "matched",
        }
    ]
    assert review["requirements"] == writer["requirements"]
    assert review["scoring_items"] == writer["scoring_items"]
    assert review["sections"] == writer["sections"]
    assert review["writing_scope"] == writer["writing_scope"]
    assert review["project_id"] == writer["project_id"]


def test_numeric_fixtures_keep_original_subject_evidence_boundaries() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "benchmarks"
        / "reliability_followup"
        / "fixtures"
        / "writing.json"
    )
    fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))["cases"]
    quantity = fixtures["cross_subject_government_case_count"]
    quantity_material = quantity["materials"][0]
    assert quantity["bidder_profile"]["bidder_name"] == "甲公司"
    assert quantity["model_output"]["content_markdown"] == (
        "我司累计承接三十项大型政务项目。"
    )
    assert quantity_material["material_type"] == "project_cases"
    assert quantity_material["title"] == "乙公司业绩"
    assert quantity_material["content"] == "乙公司累计承接三十项大型政务项目。"
    assert quantity_material["valid_until"] == "2027-12-31"
    assert quantity_material["metadata"] == {"status": "valid"}
    assert quantity_material["source_references"] == [
        {"document_id": "source.pdf", "page": 1, "confidence": 0.95}
    ]
    evidenced_quantity = fixtures["evidenced_chinese_case_count"]
    assert evidenced_quantity["bidder_profile"] == quantity["bidder_profile"]
    assert (
        evidenced_quantity["model_output"]["content_markdown"]
        == quantity["model_output"]["content_markdown"]
    )
    assert evidenced_quantity["materials"][0]["metadata"]["owner_name"] == "甲公司"

    amount_negative = fixtures["cross_subject_contract_amount"]
    amount_positive = fixtures["same_subject_contract_amount"]
    negative_material = amount_negative["materials"][0]
    positive_material = amount_positive["materials"][0]
    assert amount_negative["requirement"] is None
    assert amount_positive["requirement"] is None
    assert amount_negative["bidder_profile"]["bidder_name"] == "甲公司"
    assert amount_positive["bidder_profile"] == amount_negative["bidder_profile"]
    assert amount_negative["model_output"] == {
        **amount_positive["model_output"],
        "evidence_used": ["MAT-CONTRACT-BETA"],
    }
    assert amount_negative["model_output"]["content_markdown"] == (
        "我司历史项目合同金额135万元。"
    )
    assert negative_material["title"] == "乙公司台账"
    assert negative_material["content"] == "乙公司历史项目合同金额135万元。"
    assert positive_material["title"] == "甲公司台账"
    assert positive_material["content"] == "甲公司历史项目合同金额135万元。"
    for material in (negative_material, positive_material):
        assert material["material_type"] == "text"
        assert material["valid_until"] == "2027-12-31"
        assert material["metadata"] == {"status": "valid"}
        assert material["source_references"] == [
            {"document_id": "source.pdf", "page": 1, "confidence": 0.95}
        ]
    assert amount_negative["model_output"]["evidence_used"] == [
        "MAT-CONTRACT-BETA"
    ]
    assert amount_positive["model_output"]["evidence_used"] == [
        "MAT-CONTRACT-ALPHA"
    ]


def test_invalid_scope_fixture_is_only_the_selector_failure() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "benchmarks"
        / "reliability_followup"
        / "fixtures"
        / "runtime.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))["cases"][
        "invalid_writing_scope"
    ]
    review = fixture["review_input"]
    writer = fixture["writer_input"]
    assert fixture["run_project_id"] == "project-alpha"
    assert review["project_id"] == writer["project_id"] == "project-alpha"
    assert review["writing_scope"] == writer["writing_scope"] == [
        "does-not-match"
    ]
    assert review["requirements"] == writer["requirements"]
    assert review["scoring_items"] == writer["scoring_items"]
    assert [item["requirement_id"] for item in review["requirements"]] == ["R-A"]
    assert [item["item_id"] for item in review["scoring_items"]] == ["S-A"]
    assert {
        item["requirement_id"] for item in review["ledger"]["entries"]
    } == {"R-A", "S-A"}
    assert all(
        item["status"] == "matched" for item in review["ledger"]["entries"]
    )
    assert [item["section_id"] for item in review["sections"]] == [
        "technical",
        "commercial",
    ]
    assert review["sections"][0]["requirement_ids"] == ["R-A"]
    assert review["sections"][1]["scoring_item_ids"] == ["S-A"]
    assert review["sections"] == writer["sections"]
    assert set(fixture["model_outputs"]) == {"technical", "commercial"}


def test_runtime_exact_scope_and_reviewed_safe_subset_invoke_writer_once(
    report: dict[str, Any],
) -> None:
    for case_id in ("R-POS-MATCHED-SCOPE", "R-POS-SAFE-SUBSET"):
        result = _case(report, "runtime", case_id)
        assert result["review_business_status"] == "passed"
        assert result["review_scope_binding_status"] == "bound"
        assert result["scope_authorization_status"] == "authorized"
        assert result["writer_invocation_count"] == 1
        assert result["model_call_count"] == 1
        assert result["evaluation"] == "correct_pass"
        assert result["scope_match_kind"] == result["oracle_assertions"][
            "expected_match_kind"
        ]


@pytest.mark.parametrize("model_call_count", [0, 2])
def test_runtime_positive_requires_exactly_one_model_call(
    model_call_count: int,
) -> None:
    observation = {
        "domain": "runtime",
        "execution_status": "completed",
        "business_status": "passed",
        "review_business_status": "passed",
        "review_scope_binding_status": "bound",
        "scope_authorization_status": "authorized",
        "scope_match_kind": "exact",
        "writer_invocation_count": 1,
        "model_call_count": model_call_count,
    }
    oracle = {
        "domain": "runtime",
        "label": "positive",
        "expected_match_kind": "exact",
    }
    assert _case_evaluation(observation, oracle) == "false_block"


def test_cli_report_rates_keep_fixed_polarity_denominators(
    report: dict[str, Any],
) -> None:
    for metrics in report["metrics"].values():
        assert metrics["correct_pass_rate"]["denominator"] == metrics[
            "positive_denominator"
        ]
        assert metrics["false_block_rate"]["denominator"] == metrics[
            "positive_denominator"
        ]
        assert metrics["false_release_rate"]["denominator"] == metrics[
            "negative_denominator"
        ]
        assert "including not_run" in metrics["rate_denominator_note"]


def test_report_writer_only_creates_a_new_explicit_output_path(
    tmp_path: Any,
) -> None:
    from scripts.run_reliability_followup_eval import main

    output = tmp_path / "followup-report.json"
    assert main(["--output", str(output)]) == 0
    original = output.read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--output", str(output)])
    assert output.read_text(encoding="utf-8") == original
