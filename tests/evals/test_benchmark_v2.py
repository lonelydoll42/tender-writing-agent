from __future__ import annotations

from scripts.run_benchmark_v2 import DEFAULT_CORPUS, run_corpus


def test_benchmark_v2_reports_independent_metrics() -> None:
    report = run_corpus(DEFAULT_CORPUS)

    assert report["case_count"] == 5
    metrics = report["metrics"]
    assert metrics["hard_requirement_recall"]["value"] == 1.0
    assert metrics["scoring_item_recall"]["value"] == 1.0
    assert metrics["source_reference_accuracy"]["value"] == 1.0
    assert metrics["conflict_recall"]["value"] == 1.0
    assert metrics["critical_false_pass"]["value"] == 0.0
    assert metrics["ocr_human_review_precision"]["value"] == 1.0
    assert "weighted_score" not in report


def test_benchmark_v2_keeps_case_level_signal() -> None:
    report = run_corpus(DEFAULT_CORPUS)
    by_id = {case["case_id"]: case for case in report["cases"]}

    assert by_id["D_conflict"]["metrics"]["conflict_recall"]["value"] == 1.0
    assert (
        by_id["ocr_low_confidence"]["metrics"][
            "ocr_human_review_precision"
        ]["value"]
        == 1.0
    )
