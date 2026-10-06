from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts.run_raw_requirement_holdout_eval import (
    _citation_check,
    _git_metadata,
    _logic_check,
    _parser_snapshot,
    evaluate_case,
    main,
    validate_oracle_coverage,
    verify_freeze,
)


ROOT = Path(__file__).resolve().parents[2]
ORACLE_PATH = ROOT / "benchmarks/raw_requirement_holdout/oracle/cases.json"
MANIFEST_PATH = ROOT / "benchmarks/raw_requirement_holdout/freeze-manifest.json"


def _load_oracle() -> dict[str, Any]:
    return json.loads(ORACLE_PATH.read_text(encoding="utf-8"))


def _logic_requirement(tree: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"check_rule": {"condition_logic": tree}}]


def test_parser_snapshot_preserves_actual_skill_result_without_oracle_merge() -> None:
    condition_logic = {
        "op": "all",
        "conditions": [{"op": "comparison", "field": "version", "value": 14}],
    }
    actual_output = {
        "requirements": [{"check_rule": {"condition_logic": condition_logic}}],
        "extraction_complete": False,
        "needs_human_review": True,
        "skill_extra": {"untouched": ["runtime", "data"]},
    }
    snapshot = _parser_snapshot(actual_output)
    assert snapshot["parser_output"] == actual_output
    assert snapshot["parser_output"]["requirements"][0]["check_rule"] == {
        "condition_logic": condition_logic
    }
    assert snapshot["decomposition_extraction_complete"] is False
    assert snapshot["decomposition_needs_human_review"] is True

    missing = _parser_snapshot(None)
    assert missing["parser_output"] is None
    assert missing["parser"]["status"] == "not_run"


def test_git_metadata_never_uses_a_parent_repository_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_root = tmp_path / "export"
    archive_root.mkdir()

    def parent_repo(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args[0], 0, stdout=str(tmp_path), stderr="")

    monkeypatch.setattr(subprocess, "run", parent_repo)
    metadata = _git_metadata(archive_root)
    assert metadata["repository_context"] == "archive/no_local_git_root"
    assert metadata["git_revision_at_run"] is None
    assert metadata["git_worktree_dirty"] is None


def test_git_metadata_records_head_and_dirty_source_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def local_repo(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        command = list(args[0])
        calls.append(command)
        if command[:3] == ["git", "rev-parse", "--show-toplevel"]:
            stdout = str(tmp_path)
        elif command[:3] == ["git", "rev-parse", "HEAD"]:
            stdout = "abc123\n"
        elif "--" in command:
            stdout = " M src/module.py\n"
        else:
            stdout = " M src/module.py\n?? new-file.txt\n"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", local_repo)
    metadata = _git_metadata(tmp_path)
    assert metadata["repository_context"] == "git_worktree"
    assert metadata["git_revision_at_run"] == "abc123"
    assert metadata["git_worktree_dirty"] is True
    assert metadata["git_src_worktree_dirty"] is True
    assert metadata["git_src_worktree_status"] == [" M src/module.py"]
    assert len(calls) == 4


def test_frozen_assets_and_machine_oracle_cover_exactly_eight_inputs() -> None:
    result = verify_freeze()
    assert result["valid"] is True
    assert result["runner_hash_frozen"] is False
    oracle = _load_oracle()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    validate_oracle_coverage(manifest, oracle)
    assert len(oracle["cases"]) == 8


def test_empty_oracle_and_removed_case_fail_coverage() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    oracle = _load_oracle()
    with pytest.raises(ValueError, match="exactly match"):
        validate_oracle_coverage(manifest, {**oracle, "cases": []})
    with pytest.raises(ValueError, match="exactly match"):
        validate_oracle_coverage(manifest, {**oracle, "cases": oracle["cases"][:-1]})


def test_any_requires_distinct_semantic_leaf_branches_not_source_text() -> None:
    spec = [{"op": "any", "branches": [["business_license"], ["legal_entity"]]}]
    fake = {
        "op": "any",
        "source_text": "business_license OR legal_entity",
        "conditions": [
            {"op": "evidence", "material_type": "business_license"},
            {"op": "evidence", "material_type": "legal_entity"},
        ],
    }
    assert _logic_check(_logic_requirement(fake), spec)["status"] == "passed"

    source_only = {"op": "any", "source_text": "business_license OR legal_entity"}
    assert _logic_check(_logic_requirement(source_only), spec)["status"] == "failed"

    extra_branch = {
        "op": "any",
        "conditions": [
            {"op": "evidence", "material_type": "business_license"},
            {"op": "evidence", "material_type": "legal_entity"},
            {"op": "evidence", "material_type": "unrelated_alternative"},
        ],
    }
    assert _logic_check(_logic_requirement(extra_branch), spec)["status"] == "failed"

    empty_extra_branch = {
        "op": "any",
        "conditions": [
            {"op": "evidence", "material_type": "business_license"},
            {"op": "evidence", "material_type": "legal_entity"},
            {"op": "and", "conditions": []},
        ],
    }
    assert (
        _logic_check(_logic_requirement(empty_extra_branch), spec)["status"] == "failed"
    )

    reused_leaf = {
        "op": "any",
        "conditions": [
            {
                "op": "evidence",
                "material_type": "business_license_legal_entity",
            }
        ],
    }
    assert _logic_check(_logic_requirement(reused_leaf), spec)["status"] == "failed"


def test_and_uses_unordered_independent_branches_and_real_leaf_predicates() -> None:
    spec = [{"op": "and", "branches": [["certificate"], ["social_security"]]}]
    valid = {
        "op": "all",
        "conditions": [
            {"op": "evidence", "material_type": "social_security"},
            {"op": "evidence", "material_type": "certificate"},
            {"op": "evidence", "material_type": "extra_required_condition"},
        ],
    }
    assert _logic_check(_logic_requirement(valid), spec)["status"] == "passed"

    malformed = {
        "op": "all",
        "conditions": [
            {"op": "comparison", "material_type": "certificate"},
            {"op": "comparison"},
        ],
    }
    assert _logic_check(_logic_requirement(malformed), spec)["status"] == "failed"


def test_sameperson_requires_subject_person_employer_and_date_in_same_scope() -> None:
    spec = [
        {
            "op": "sameperson",
            "person_aliases": ["personnel_certificate"],
            "employer_aliases": ["bidder_employer_relationship"],
            "date_field": "social_security_month",
            "start": "2026-03",
            "end": "2026-08",
            "continuous": True,
        }
    ]
    valid = {
        "op": "sameperson",
        "person_field": "person_id",
        "conditions": [
            {"op": "evidence", "material_type": "personnel_certificate"},
            {"op": "evidence", "material_type": "bidder_employer_relationship"},
            {
                "op": "date_range",
                "field": "social_security_month",
                "start": "2026-03",
                "end": "2026-08",
                "continuous": True,
            },
        ],
    }
    assert _logic_check(_logic_requirement(valid), spec)["status"] == "passed"

    moved_date = {
        "op": "all",
        "conditions": [
            {
                "op": "sameperson",
                "person_field": "person_id",
                "conditions": [
                    {"op": "evidence", "material_type": "personnel_certificate"},
                    {"op": "evidence", "material_type": "bidder_employer_relationship"},
                ],
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
    assert _logic_check(_logic_requirement(moved_date), spec)["status"] == "failed"


def test_not_target_tls_threshold_postgres_floor_and_manual_are_structural() -> None:
    not_spec = [
        {
            "op": "not",
            "target": {
                "field": "tls_version",
                "operator": "in",
                "value": ["1.0", "1.1"],
            },
        }
    ]
    wrong_not = {
        "op": "not",
        "condition": {
            "op": "comparison",
            "field": "identity_changed",
            "operator": "eq",
            "value": True,
        },
    }
    assert _logic_check(_logic_requirement(wrong_not), not_spec)["status"] == "failed"

    tls_spec = [
        {"op": "threshold", "field": "tls_version", "operator": "gte", "value": "1.2"}
    ]
    bad_tls = {
        "op": "comparison",
        "field": "tls_version",
        "operator": "eq",
        "value": "1.2",
    }
    assert _logic_check(_logic_requirement(bad_tls), tls_spec)["status"] == "failed"
    good_tls = {
        "op": "comparison",
        "field": "tls_version",
        "operator": "gte",
        "value": "1.2",
    }
    assert _logic_check(_logic_requirement(good_tls), tls_spec)["status"] == "passed"

    pg_spec = [{"op": "version_floor", "product": "PostgreSQL", "minimum": 14}]
    assert (
        _logic_check(
            _logic_requirement(
                {
                    "op": "comparison",
                    "field": "postgresql_version",
                    "operator": "gte",
                    "value": 14,
                }
            ),
            pg_spec,
        )["status"]
        == "passed"
    )
    assert (
        _logic_check(
            _logic_requirement(
                {
                    "op": "comparison",
                    "field": "postgresql_version",
                    "operator": "eq",
                    "value": 14,
                }
            ),
            pg_spec,
        )["status"]
        == "failed"
    )

    manual_spec = [{"op": "manual", "target": "sensitive_database_fields"}]
    source_only_manual = {
        "op": "manual_review",
        "source_text": "manual review sensitive_database_fields",
    }
    assert (
        _logic_check(_logic_requirement(source_only_manual), manual_spec)["status"]
        == "failed"
    )


def test_citation_must_match_page_physical_line_and_locator() -> None:
    pages = ["header\n exact clause \nfooter", "other page"]
    valid = {
        "document_id": "file_123",
        "source_version": "file_123:v1",
        "page": 1,
        "locator": "artifact_file_123:p1:l2",
        "quote": "exact clause",
    }
    result = _citation_check(valid, pages, "file_123", "file_123:v1")
    assert result["quote_matches_physical_line"] is True
    assert result["locator_valid"] is True

    wrong_page = {**valid, "page": 2}
    assert (
        _citation_check(wrong_page, pages, "file_123", "file_123:v1")[
            "quote_matches_physical_line"
        ]
        is False
    )
    wrong_locator = {**valid, "locator": "artifact_file_123:p1:l3"}
    assert (
        _citation_check(wrong_locator, pages, "file_123", "file_123:v1")[
            "quote_matches_physical_line"
        ]
        is False
    )
    substring_quote = {**valid, "quote": "clause"}
    assert (
        _citation_check(substring_quote, pages, "file_123", "file_123:v1")[
            "quote_matches_physical_line"
        ]
        is False
    )


def test_empty_requirements_and_missing_references_cannot_pass() -> None:
    case = {
        "case_id": "H00",
        "required_text_groups": [["required phrase"]],
        "logic": [{"op": "any", "branches": [["first"], ["second"]]}],
        "quotes": ["source line"],
    }
    parser = {"status": "executed", "requirements": []}
    result = evaluate_case(case, parser, "source line", "file_123", "file_123:v1")
    assert result["finite_check_status"] == "failed"

    requirement = {
        "description": "required phrase",
        "check_rule": {
            "condition_logic": {
                "op": "any",
                "conditions": [
                    {"op": "evidence", "material_type": "first"},
                    {"op": "evidence", "material_type": "second"},
                ],
            }
        },
        "source_references": [],
    }
    result = evaluate_case(
        case,
        {"status": "executed", "requirements": [requirement]},
        "source line",
        "file_123",
        "file_123:v1",
    )
    assert result["finite_check_status"] == "failed"


def test_existing_output_is_refused_before_running_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "existing.json"
    output.write_text("preserve", encoding="utf-8")

    def unexpected_run() -> dict[str, Any]:
        raise AssertionError("evaluation must not run for an existing output path")

    monkeypatch.setattr(
        "scripts.run_raw_requirement_holdout_eval.run_evaluation", unexpected_run
    )
    with pytest.raises(SystemExit):
        main(["--output", str(output)])
    assert output.read_text(encoding="utf-8") == "preserve"
