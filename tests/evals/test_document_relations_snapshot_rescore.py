from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

import pytest

from scripts import run_document_relations_snapshot_rescore as snapshot_rescore


ROOT = Path(__file__).resolve().parents[2]
REPORT_DIRECTORY = (
    ROOT
    / "benchmarks"
    / "document_relations"
    / "reports"
    / "current-baseline-20e79af-20261013"
    / "worker"
)
PRODUCT_CAPTURE = REPORT_DIRECTORY / "current-product-20e79af-capture.json"
BUNDLE = ROOT / "benchmarks" / "document_relations" / "reserved" / "v2"
EXPECTED_CASE_IDS = tuple(f"case-{index:02d}" for index in range(1, 15))
EXPECTED_SOURCE_TREE_SHA256 = (
    "51b1b18212c84ce50e8606106b96e4b5d5b548fb68bab491669cf08cf4e1ea34"
)
ATTRIBUTE_CONTRACT_SHA256 = (
    "8204635e3ece53755fe488c05900c161d92c9dd6d0d1c3d53fff2d80612ac2f1"
)
ATTRIBUTE_CASES_SHA256 = (
    "64c876600b0c7ba0ae504831f1a401d89c34bc0405c50ea6d6d5e080e7396605"
)
OVERLAY_CASE_IDS = {"case-03", "case-11"}


def _capture() -> dict[str, Any]:
    return json.loads(PRODUCT_CAPTURE.read_text(encoding="utf-8"))


def _capture_sha256() -> str:
    return hashlib.sha256(PRODUCT_CAPTURE.read_bytes()).hexdigest()


def _save_capture(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None]
) -> tuple[Path, str]:
    report = deepcopy(_capture())
    mutate(report)
    path = tmp_path / "mutated-product-report.json"
    raw = (
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def _rescore(
    product_report: Path = PRODUCT_CAPTURE,
    *,
    expected_report_sha256: str | None = None,
    expected_source_tree_sha256: str = EXPECTED_SOURCE_TREE_SHA256,
    main_reviewer_authorized: bool = True,
) -> dict[str, Any]:
    return snapshot_rescore.rescore_report(
        BUNDLE,
        product_report,
        expected_report_sha256=expected_report_sha256 or _capture_sha256(),
        expected_source_tree_sha256=expected_source_tree_sha256,
        main_reviewer_authorized=main_reviewer_authorized,
    )


def test_versioned_capture_scores_three_views_and_preserves_replay_material() -> None:
    original = _capture()
    result = _rescore()

    assert result["schema"] == "document-relations-source-snapshot-rescore-v1"
    assert result["classification"] == (
        "offline scoring of preserved product capture through frozen 1.0.5 API"
    )
    assert result["source_capture"]["sha256"] == _capture_sha256()
    assert result["source_capture"]["source_tree_sha256"] == (
        EXPECTED_SOURCE_TREE_SHA256
    )
    assert result["source_identity"]["expected_source_tree_sha256"] == (
        EXPECTED_SOURCE_TREE_SHA256
    )
    assert result["source_identity"]["metadata_match"] is True
    assert result["source_identity"]["git_proof_performed"] is False
    assert result["source_identity"]["git_proof_status"] == (
        "not_performed_main_reviewer_proof_required"
    )
    assert result["product_source"]["source_tree_sha256"] == (
        EXPECTED_SOURCE_TREE_SHA256
    )
    assert result["product_source"]["expected_source_tree_sha256"] == (
        EXPECTED_SOURCE_TREE_SHA256
    )
    assert result["product_source"]["product_commit_attested"] is False
    assert result["helper"]["sha256"] == hashlib.sha256(
        Path(snapshot_rescore.__file__).read_bytes()
    ).hexdigest()
    assert result["frozen_inputs"]["attribute_contract_sha256"] == (
        ATTRIBUTE_CONTRACT_SHA256
    )
    assert result["frozen_inputs"]["attribute_cases_sha256"] == (
        ATTRIBUTE_CASES_SHA256
    )

    for version in ("1.0.3", "1.0.4", "1.0.5"):
        assert result["scoring_views"][version]["case_count"] == 14
        assert result["scoring_views"][version]["not_run"] == 0
    assert [row["case_id"] for row in result["cases"]] == list(EXPECTED_CASE_IDS)

    original_by_id = {row["case_id"]: row for row in original["cases"]}
    for row in result["cases"]:
        source = original_by_id[row["case_id"]]
        assert row["execution_state"] == source["execution_state"]
        assert row["product_capture_status"] == source["status"]
        assert row["runtime"] == source["runtime"]
        assert row.get("actual_graph") == source.get("actual_graph")
        assert row.get("source_context") == source.get("source_context")
        assert row["product_capture_errors"] == source.get("errors", [])
        if row["execution_state"] == "executed":
            assert row["product_capture_1_0_3_score"]["errors"] == source.get(
                "errors", []
            )
            assert isinstance(
                row["capture_1_0_3_parity"]["errors_order_only_difference"], bool
            )
        fingerprints = [
            row["scores"][version]["replay_fingerprints"]
            for version in ("1.0.3", "1.0.4", "1.0.5")
        ]
        assert fingerprints[0] == fingerprints[1] == fingerprints[2]

        if row["execution_state"] == "executed":
            assert all(
                row["scores"][version]["scored"]
                for version in ("1.0.3", "1.0.4", "1.0.5")
            )
        else:
            assert all(
                not row["scores"][version]["scored"]
                for version in ("1.0.3", "1.0.4", "1.0.5")
            )
            assert all(
                row["scores"][version]["execution_state"] == row["execution_state"]
                for version in ("1.0.3", "1.0.4", "1.0.5")
            )

        if row["case_id"] in OVERLAY_CASE_IDS:
            assert row["scores"]["1.0.5"]["scorer_version"] == "1.0.5"
            assert row["scores"]["1.0.5"]["scored"] is True
        else:
            assert row["scores"]["1.0.5"]["scorer_version"] == "1.0.4"
            assert row["scores"]["1.0.5"]["scoring_method"] == (
                "frozen 1.0.4 score_case; case is outside the historical overlay"
            )

    assert result["historical_af7_reference"]["passed"] == 10
    assert result["historical_af7_reference"]["classification"] == (
        "historical only; not the current baseline"
    )
    assert result["claims"]["product_runtime_invoked_during_rescore"] is False
    assert result["claims"]["model_invoked_during_rescore"] is False
    assert result["claims"]["product_capture_reexecuted"] is False


def test_frozen_1_0_5_scorer_is_called_only_for_overlay_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_score_case = snapshot_rescore.boundary.score_case
    called_case_ids: list[str] = []

    def record_call(case: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
        called_case_ids.append(str(case["case_id"]))
        return original_score_case(case, *args, **kwargs)

    monkeypatch.setattr(snapshot_rescore.boundary, "score_case", record_call)
    _rescore()

    assert called_case_ids == ["case-03", "case-11"]


def test_expected_source_hash_is_required_valid_and_bound_to_capture() -> None:
    with pytest.raises(ValueError, match="expected_source_tree_sha256"):
        _rescore(expected_source_tree_sha256="not-a-sha256")

    with pytest.raises(ValueError, match="does not match product report metadata"):
        _rescore(expected_source_tree_sha256="0" * 64)


def test_synthetic_source_identity_metadata_mutation_is_not_git_proof(
    tmp_path: Path,
) -> None:
    synthetic_source_sha256 = "f" * 64
    product_report, report_sha256 = _save_capture(
        tmp_path,
        lambda report: report.update(source_tree_sha256=synthetic_source_sha256),
    )

    result = _rescore(
        product_report,
        expected_report_sha256=report_sha256,
        expected_source_tree_sha256=synthetic_source_sha256,
    )

    assert result["source_capture"]["source_tree_sha256"] == synthetic_source_sha256
    assert result["source_identity"]["metadata_match"] is True
    assert result["source_identity"]["git_proof_performed"] is False
    assert result["claims"]["product_capture_reexecuted"] is False


def test_changed_report_hash_is_rejected() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        _rescore(expected_report_sha256="0" * 64)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda report: report.update(schema="unknown-product-report-v99"),
            "unsupported product report schema",
        ),
        (
            lambda report: report["cases"][0]["source_context"]["pages"].__setitem__(
                0, "synthetic page mutation"
            ),
            "pages do not match frozen input",
        ),
        (
            lambda report: report["cases"][13].update(case_id="case-01"),
            "case IDs must be unique",
        ),
        (
            lambda report: report["cases"].pop(),
            "exactly 14 cases",
        ),
        (
            lambda report: report["evaluator"].update(version="1.0.4"),
            "frozen 1.0.3 evaluator",
        ),
        (
            lambda report: (
                report["cases"][2]["source_context"].update(
                    source_version="synthetic-version:v1"
                ),
                report["cases"][2]["actual_graph"].update(
                    source_version="synthetic-version:v1"
                ),
            ),
            "captured Registry source_version",
        ),
    ],
)
def test_original_rescore_input_guards_are_reused(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    product_report, report_sha256 = _save_capture(tmp_path, mutate)

    with pytest.raises(ValueError, match=message):
        _rescore(product_report, expected_report_sha256=report_sha256)


def test_changed_attribute_contract_freeze_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    changed_contract = tmp_path / "contract.md"
    changed_contract.write_bytes(snapshot_rescore.CONTRACT_PATH.read_bytes())
    with changed_contract.open("ab") as handle:
        handle.write(b"\n")
    monkeypatch.setattr(snapshot_rescore, "CONTRACT_PATH", changed_contract)

    with pytest.raises(ValueError, match="attribute contract SHA-256"):
        _rescore()


def test_changed_historical_overlay_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = snapshot_rescore.current.HISTORICAL_OVERLAY_PATH
    changed_overlay = tmp_path / "historical-overlay.json"
    changed_overlay.write_bytes(original.read_bytes() + b"\n")
    monkeypatch.setattr(
        snapshot_rescore.current, "HISTORICAL_OVERLAY_PATH", changed_overlay
    )

    with pytest.raises(ValueError, match="frozen scorer/rule hash mismatch"):
        _rescore()


@pytest.mark.parametrize(
    ("case_id", "execution_state"),
    [("case-03", "failed"), ("case-11", "not_run")],
)
def test_nonexecuted_overlay_case_is_not_scored_or_given_context(
    tmp_path: Path, case_id: str, execution_state: str
) -> None:
    status = "failed" if execution_state == "failed" else "not_run"

    def mark_nonexecuted(report: dict[str, Any]) -> None:
        row = next(case for case in report["cases"] if case["case_id"] == case_id)
        row.update(
            execution_state=execution_state,
            status=status,
            actual_graph=None,
            source_context=None,
            reason=f"synthetic test mutation: {execution_state}",
        )

    product_report, report_sha256 = _save_capture(tmp_path, mark_nonexecuted)
    result = _rescore(product_report, expected_report_sha256=report_sha256)
    row = next(case for case in result["cases"] if case["case_id"] == case_id)

    assert row["execution_state"] == execution_state
    assert "actual_graph" not in row
    assert "source_context" not in row
    assert row["reason"] == f"synthetic test mutation: {execution_state}"
    assert all(
        row["scores"][version]["scored"] is False
        and row["scores"][version]["execution_state"] == execution_state
        for version in ("1.0.3", "1.0.4", "1.0.5")
    )
    assert (
        row["scores"]["1.0.5"]["evidence_contract_validation"]["status"]
        == "not_validated_non_executed"
    )


def test_offline_scoring_requires_main_reviewer_authorization() -> None:
    with pytest.raises(PermissionError, match="authorization"):
        _rescore(main_reviewer_authorized=False)


def test_cli_requires_source_hash_and_refuses_to_overwrite(
    tmp_path: Path,
) -> None:
    missing_source = tmp_path / "missing-source.json"
    with pytest.raises(SystemExit) as missing_error:
        snapshot_rescore.main(
            [
                "--bundle",
                str(BUNDLE),
                "--product-report",
                str(PRODUCT_CAPTURE),
                "--expected-report-sha256",
                _capture_sha256(),
                "--output",
                str(missing_source),
                "--main-reviewer-authorized",
            ]
        )
    assert missing_error.value.code == 2
    assert not missing_source.exists()

    output = tmp_path / "existing-report.json"
    output.write_text("preserve-existing\n", encoding="utf-8")
    before = output.read_bytes()
    with pytest.raises(SystemExit) as overwrite_error:
        snapshot_rescore.main(
            [
                "--bundle",
                str(BUNDLE),
                "--product-report",
                str(PRODUCT_CAPTURE),
                "--expected-report-sha256",
                _capture_sha256(),
                "--expected-source-tree-sha256",
                EXPECTED_SOURCE_TREE_SHA256,
                "--output",
                str(output),
                "--main-reviewer-authorized",
            ]
        )

    assert overwrite_error.value.code == 2
    assert output.read_bytes() == before
