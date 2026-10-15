"""Reuse the frozen byte verifier with this batch's explicit inventory."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
REGRESSION = (
    ROOT / "benchmarks/document_relations/financial-context-regression/20261015"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--archive-tree", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must use a new path")
    helper = (
        ROOT / "benchmarks/document_relations"
        "/copy-alternative-regression/20261014/verify-snapshot.py"
    )
    spec = importlib.util.spec_from_file_location("_financial_byte_verifier", helper)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load frozen byte verifier")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    verifier.REGRESSION = REGRESSION
    verifier.PREVIOUS_PROOF = (
        ROOT / "benchmarks/document_relations/reports"
        "/copy-alternative-followup-20261014/reviewer/final-code-proof.json"
    )
    verifier.NEW_CODE = {
        "tests/test_document_relations_financial_context.py",
        (REGRESSION / "check-acceptance.py").relative_to(ROOT).as_posix(),
        Path(__file__).relative_to(ROOT).as_posix(),
    }
    report = verifier.verify(args.export.resolve(strict=True), args.archive_tree)
    report["schema"] = "financial-context-canonical-proof-v1"
    report["audit_wrapper_sha256"] = verifier.sha(Path(__file__))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "source_tree_sha256",
                    "canonical_code_files",
                    "protected_files",
                )
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
