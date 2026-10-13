from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

import pytest

from scripts import run_document_relations_current_rescore as current_rescore


ROOT = Path(__file__).resolve().parents[2]
WORKER_REPORTS = (
    ROOT
    / "benchmarks"
    / "document_relations"
    / "reports"
    / "current-baseline-20e79af-20261013"
    / "worker"
)
PRODUCT_CAPTURE = WORKER_REPORTS / "current-product-20e79af-capture.json"
BUNDLE = ROOT / "benchmarks" / "document_relations" / "reserved" / "v2"
EXPECTED_CASE_IDS = tuple(f"case-{index:02d}" for index in range(1, 15))
OVERLAY_PATH = (
    ROOT
    / "benchmarks"
    / "document_relations"
    / "boundary-evidence-regression"
    / "20261013"
    / "historical-overlay.json"
)


def _capture() -> dict[str, Any]:
    return json.loads(PRODUCT_CAPTURE.read_text(encoding="utf-8"))


def _capture_sha256() -> str:
    return hashlib.sha256(PRODUCT_CAPTURE.read_bytes()).hexdigest()


def _save_report(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None]
) -> tuple[Path, str]:
    report = deepcopy(_capture())
    mutate(report)
    path = tmp_path / "mutated-product-report.json"
    raw = (
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def _rescore(
    report_path: Path = PRODUCT_CAPTURE,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    return current_rescore.rescore_report(
        BUNDLE,
        report_path,
        expected_report_sha256=expected_sha256 or _capture_sha256(),
        main_reviewer_authorized=True,
    )


def test_valid_capture_scores_views_and_preserves_material() -> None:
    product_capture = _capture()
    report = _rescore()

    assert report["classification"] == (
        "offline current-capture scoring through frozen 1.0.5 API"
    )
    assert report["source_capture"]["sha256"] == _capture_sha256()
    assert report["source_capture"]["classification"] == product_capture[
        "classification"
    ]
    for version in ("1.0.3", "1.0.4", "1.0.5"):
        assert report["scoring_views"][version]["case_count"] == 14
        assert report["scoring_views"][version]["not_run"] == 0
    assert list(row["case_id"] for row in report["cases"]) == list(
        EXPECTED_CASE_IDS
    )

    original_by_id = {row["case_id"]: row for row in product_capture["cases"]}
    for row in report["cases"]:
        original = original_by_id[row["case_id"]]
        assert row["execution_state"] == original["execution_state"]
        assert row["product_capture_status"] == original["status"]
        assert row["runtime"] == original["runtime"]
        assert row.get("actual_graph") == original.get("actual_graph")
        assert row.get("source_context") == original.get("source_context")

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
                row["scores"][version]["execution_state"]
                == row["execution_state"]
                for version in ("1.0.3", "1.0.4", "1.0.5")
            )

        if row["case_id"] in {"case-03", "case-11"}:
            assert row["scores"]["1.0.5"]["scorer_version"] == "1.0.5"
            assert row["scores"]["1.0.5"]["scoring_method"] == (
                "frozen 1.0.5 score_case with validated historical evidence contract"
            )
        else:
            assert row["scores"]["1.0.5"]["scorer_version"] == "1.0.4"
            assert row["scores"]["1.0.5"]["scoring_method"] == (
                "frozen 1.0.4 score_case; case is outside the historical overlay"
            )

    assert report["historical_af7_reference"]["passed"] == 10
    assert report["historical_af7_reference"]["classification"] == (
        "historical only; not the current baseline"
    )


def test_changed_product_report_hash_is_rejected() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        _rescore(expected_sha256="0" * 64)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda report: report.update(source_tree_sha256="a" * 64),
            "expected current product source-tree",
        ),
        (
            lambda report: report["cases"][0]["runtime"].update(
                registered_input_sha256="0" * 64
            ),
            "runtime input checksum mismatch",
        ),
        (
            lambda report: report["cases"][2]["source_context"]["pages"].__setitem__(
                0, "tampered raw page"
            ),
            "pages do not match frozen input",
        ),
        (
            lambda report: report["cases"][2]["actual_graph"].update(
                document_id="other-document"
            ),
            "graph/source_context identity mismatch",
        ),
        (
            lambda report: (
                report["cases"][2]["source_context"].update(
                    source_version="tampered:v1"
                ),
                report["cases"][2]["actual_graph"].update(
                    source_version="tampered:v1"
                ),
            ),
            "Registry source_version",
        ),
        (
            lambda report: report["evaluator"].update(version="1.0.4"),
            "frozen 1.0.3 evaluator",
        ),
    ],
)
def test_changed_capture_identity_or_replay_material_fails_closed(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    path, digest = _save_report(tmp_path, mutate)

    with pytest.raises(ValueError, match=message):
        _rescore(path, expected_sha256=digest)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda report: report["cases"][13].update(case_id="case-01"),
            "case IDs must be unique",
        ),
        (
            lambda report: report["cases"].pop(),
            "exactly 14 cases",
        ),
    ],
)
def test_duplicate_or_missing_cases_are_rejected(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    path, digest = _save_report(tmp_path, mutate)

    with pytest.raises(ValueError, match=message):
        _rescore(path, expected_sha256=digest)


def test_tampered_historical_evidence_contract_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overlay = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))
    overlay["cases"][0]["evidence_contract"]["groups"]["S1"]["operator"] = "AND"
    path = tmp_path / "tampered-historical-overlay.json"
    path.write_text(
        json.dumps(overlay, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(current_rescore, "HISTORICAL_OVERLAY_PATH", path)

    with pytest.raises(ValueError, match="hash mismatch: historical_overlay"):
        _rescore()


@pytest.mark.parametrize(
    ("path_attribute", "filename", "message"),
    [
        ("CONTRACT_PATH", "contract.md", "contract SHA-256"),
        ("SCOPE_FREEZE_PATH", "scope-freeze.json", "scope freeze SHA-256"),
        (
            "PRODUCT_SNAPSHOT_PROOF_PATH",
            "product-snapshot-proof.json",
            "product snapshot proof SHA-256",
        ),
    ],
)
def test_changed_frozen_baseline_documents_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path_attribute: str,
    filename: str,
    message: str,
) -> None:
    frozen_path = getattr(current_rescore, path_attribute)
    tampered_path = tmp_path / filename
    tampered_path.write_bytes(frozen_path.read_bytes() + b"\n")
    monkeypatch.setattr(current_rescore, path_attribute, tampered_path)

    with pytest.raises(ValueError, match=message):
        _rescore()


def test_offline_scoring_requires_main_reviewer_authorization() -> None:
    with pytest.raises(PermissionError, match="authorization"):
        current_rescore.rescore_report(
            BUNDLE,
            PRODUCT_CAPTURE,
            expected_report_sha256=_capture_sha256(),
            main_reviewer_authorized=False,
        )


def test_cli_refuses_to_overwrite_an_existing_output(
    tmp_path: Path,
) -> None:
    output = tmp_path / "existing-report.json"
    output.write_text("preserve-existing\n", encoding="utf-8")
    before = output.read_bytes()

    with pytest.raises(SystemExit) as error:
        current_rescore.main(
            [
                "--bundle",
                str(BUNDLE),
                "--product-report",
                str(PRODUCT_CAPTURE),
                "--expected-report-sha256",
                _capture_sha256(),
                "--output",
                str(output),
                "--main-reviewer-authorized",
            ]
        )

    assert error.value.code == 2
    assert output.read_bytes() == before
