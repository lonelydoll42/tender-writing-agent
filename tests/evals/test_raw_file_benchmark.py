from __future__ import annotations

from typing import Any

import pytest

from scripts.run_raw_file_eval import (
    EXPECTED_WORKFLOW,
    MUST_NOT_PASS,
    _strict_source_check,
    _strict_tree_check,
    _strict_text_match,
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
    strict = metric["strict_local_rule"]
    assert strict["status"] == "not_run"
    assert strict["family_count"] == 6
    assert strict["text_coverage"]["denominator"] == 6
    assert strict["text_coverage"]["not_run_count"] == 6
    assert strict["structure_tree"]["denominator"] == 6
    assert strict["automatic_verification_support"]["supported_count"] is None
    assert strict["automatic_verification_support"]["denominator"] == 6


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


def test_strict_text_oracle_normalizes_hidden_same_year_end_month() -> None:
    matched, groups, missing = _strict_text_match(
        "Q5",
        "拟任项目经理持有信息系统项目管理师证书，并提供2026年3月至8月社会保险证明。",
    )

    assert matched is True
    assert {item["group_id"] for item in groups} == {1, 2, 3, 4, 5}
    assert missing == []


def test_strict_text_oracle_does_not_join_unrelated_requirements() -> None:
    q5 = "拟任项目经理持有信息系统项目管理师证书。"
    social = "投标人应提供2026年3月至8月社会保险证明。"
    assert _strict_text_match("Q5", q5)[0] is False
    assert _strict_text_match("Q5", social)[0] is False


def test_strict_text_oracle_accepts_actual_t4_prohibition_wording() -> None:
    matched, groups, missing = _strict_text_match(
        "T4",
        "应支持采购人现有国产 Linux、PostgreSQL 兼容数据库环境，"
        "不得绑定单一公有云",
    )

    assert matched is True
    assert {item["group_id"] for item in groups} == {1, 2, 3}
    assert missing == []


def test_strict_source_validation_requires_registry_identity_version_page_and_quote(
) -> None:
    provenance = [
        {
            "artifact_id": "artifact_file-tender",
            "file_id": "file-tender",
            "source_version": "file-tender:v1",
            "pages": [
                {
                    "page_number": 2,
                    "text": "页眉\n原始条款：提供有效营业执照。\n页脚",
                }
            ],
        }
    ]
    requirement = {
        "source_references": [
            {
                "document_id": "file-tender",
                "page": 2,
                "source_version": "file-tender:v1",
                "quote": "原始条款：提供有效营业执照。",
                "locator": "artifact_file-tender:p2:l2",
            }
        ]
    }
    result = _strict_source_check(requirement, provenance)
    assert result["all_valid"] is True

    tampered_line = {
        "source_references": [
            {
                "document_id": "file-tender",
                "page": 2,
                "source_version": "file-tender:v1",
                "quote": "原始条款：提供有效营业执照。",
                "locator": "artifact_file-tender:p2:l1",
            }
        ]
    }
    assert _strict_source_check(tampered_line, provenance)["all_valid"] is False

    truncated_quote = {
        "source_references": [
            {
                "document_id": "file-tender",
                "page": 2,
                "source_version": "file-tender:v1",
                "quote": "提供有效营业执照。",
                "locator": "artifact_file-tender:p2:l2",
            }
        ]
    }
    assert _strict_source_check(truncated_quote, provenance)["all_valid"] is False

    wrong_version = {
        "source_references": [
            {
                "document_id": "file-tender",
                "page": 2,
                "source_version": "file-tender:v2",
                "quote": "原始条款：提供有效营业执照。",
                "locator": "artifact_file-tender:p2:l2",
            }
        ]
    }
    assert _strict_source_check(wrong_version, provenance)["all_valid"] is False

    unrelated_document = {
        "source_references": [
            {
                "document_id": "productdescription",
                "page": 2,
                "source_version": "file-tender:v1",
                "quote": "原始条款：提供有效营业执照。",
                "locator": "artifact_file-tender:p2:l2",
            }
        ]
    }
    assert _strict_source_check(unrelated_document, provenance)["all_valid"] is False


def test_strict_metrics_keep_tree_presence_separate_from_automatic_support(
    report: dict[str, Any],
) -> None:
    strict = report["metrics"]["strict_local_rule"]
    assert strict["status"] == "measured"
    assert strict["text_coverage"]["denominator"] == 6
    assert strict["automatic_verification_support"]["supported_count"] == 0
    assert strict["structure_tree"]["denominator"] == 6
    assert strict["source_reference_validation"]["denominator"] == 6
    assert all(
        not item["automatic_supported"]
        for item in strict["items"]
    )


def test_strict_tree_oracle_uses_frozen_semantic_mappings() -> None:
    q5 = {
        "condition_logic": {
            "op": "all",
            "conditions": [
                {
                    "op": "sameperson",
                    "person_field": "person_id",
                    "conditions": [
                        {
                            "op": "all",
                            "conditions": [
                                {
                                    "op": "evidence",
                                    "material_type": "personnel_certificate",
                                },
                                {
                                    "op": "evidence",
                                    "material_type": "social_security_record",
                                },
                                {
                                    "op": "evidence",
                                    "material_type": "bidder_employer_relationship",
                                    "source_terms": ["投标人", "缴纳"],
                                },
                                {
                                    "op": "date_range",
                                    "field": "social_security_month",
                                    "start": "2026-03",
                                    "end": "2026-08",
                                    "continuous": True,
                                },
                            ],
                        }
                    ],
                }
            ],
        }
    }
    assert _strict_tree_check("Q5", q5)["semantic_completeness"]["correct"]

    t1 = {
        "condition_logic": {
            "op": "all",
            "source_text": "支持与现有身份平台通过OAuth2.0/OIDC对接",
            "conditions": [
                {
                    "op": "any",
                    "conditions": [
                        {
                            "op": "evidence",
                            "material_type": "oauth2",
                            "source_terms": ["OAuth2.0"],
                        },
                        {
                            "op": "evidence",
                            "material_type": "oidc",
                            "source_terms": ["OIDC"],
                        },
                    ],
                },
                {"op": "evidence", "material_type": "existing_identity_system"},
                {
                    "op": "not",
                    "condition": {
                        "op": "comparison",
                        "field": "identity_system_changed",
                        "operator": "eq",
                        "value": True,
                    },
                },
            ],
        }
    }
    assert _strict_tree_check("T1", t1)["semantic_completeness"]["correct"]

    t1_without_not = {
        "condition_logic": {
            **t1["condition_logic"],
            "conditions": t1["condition_logic"]["conditions"][:2],
        }
    }
    assert not _strict_tree_check(
        "T1", t1_without_not
    )["semantic_completeness"]["correct"]

    t4 = {
        "condition_logic": {
            "op": "all",
            "conditions": [
                {"op": "evidence", "material_type": "domestic_linux"},
                {"op": "evidence", "material_type": "postgresql_compatibility"},
                {
                    "op": "not",
                    "condition": {
                        "op": "comparison",
                        "field": "single_public_cloud_binding",
                        "operator": "eq",
                        "value": True,
                    },
                },
            ],
        }
    }
    assert _strict_tree_check("T4", t4)["semantic_completeness"]["correct"]

    t4_wrong_polarity = {
        "condition_logic": {
            **t4["condition_logic"],
            "conditions": t4["condition_logic"]["conditions"][:2]
            + [
                {
                    "op": "not",
                    "condition": {
                        "op": "comparison",
                        "field": "single_public_cloud_binding",
                        "operator": "eq",
                        "value": False,
                    },
                }
            ],
        }
    }
    assert not _strict_tree_check(
        "T4", t4_wrong_polarity
    )["semantic_completeness"]["correct"]
