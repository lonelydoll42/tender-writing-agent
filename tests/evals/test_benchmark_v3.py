from __future__ import annotations

from scripts.run_benchmark_v3 import DEFAULT_ANSWERS, DEFAULT_CORPUS, run_corpus


def test_benchmark_v3_challenge_has_no_critical_false_pass() -> None:
    report = run_corpus(DEFAULT_CORPUS, DEFAULT_ANSWERS)

    assert report["case_count"] == 8
    metrics = report["metrics"]
    assert metrics["decision_accuracy"]["value"] == 1.0
    assert metrics["evidence_status_accuracy"]["value"] == 1.0
    assert metrics["feasibility_status_accuracy"]["value"] == 1.0
    assert metrics["hard_negative_false_pass"]["value"] == 0.0
    assert metrics["critical_false_pass"]["value"] == 0.0
    assert metrics["ocr_critical_false_pass"]["value"] == 0.0
    assert metrics["ocr_human_review_recall"]["value"] == 1.0
    assert metrics["conflict_recall"]["value"] == 1.0


def test_benchmark_v3_reports_mutation_and_amendment_deltas() -> None:
    report = run_corpus(DEFAULT_CORPUS, DEFAULT_ANSWERS)
    by_id = {case["case_id"]: case for case in report["cases"]}

    mutation = by_id["HN_ISO9001_FOR_ISO27001"]["mutations"][0]
    assert mutation["passed"] is True
    assert mutation["actual_delta"]["decision_from"] == "human_review"
    assert mutation["actual_delta"]["decision_to"] == "bid"

    amendment = by_id["AMENDMENT_AMOUNT_CHANGE"]["variants"]
    assert all(item["passed"] for item in amendment)
    amended = next(
        item for item in amendment if item["variant_id"] == "amended-2000000"
    )
    assert amended["observed"]["decision"] == "no_bid"
    assert report["mutation_summary"]["value"] == 1.0
    assert report["variant_summary"]["value"] == 1.0


def test_benchmark_v3_keeps_answers_out_of_skill_observations() -> None:
    report = run_corpus(DEFAULT_CORPUS, DEFAULT_ANSWERS)

    for case in report["cases"]:
        observed = case["observed"]
        assert "expected" not in observed
        assert "ground_truth" not in observed
