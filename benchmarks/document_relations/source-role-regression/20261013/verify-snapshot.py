"""Verify frozen historical bytes and staged code against a canonical export."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
ALLOWED = {
    ".gitattributes",
    "src/qiaowenshu_agent/domain/document_relations.py",
    "docs/document_relations_acceptance.md",
    "benchmarks/document_relations/README.md",
    "benchmarks/document_relations/publication-record.json",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def index():
    raw = subprocess.check_output(
        ["git", "ls-files", "--stage", "-z"], cwd=ROOT
    ).decode("utf-8")
    result = {}
    for item in raw.split("\0"):
        if item:
            metadata, path = item.split("\t", 1)
            mode, blob, stage = metadata.split()
            if stage != "0":
                raise ValueError(f"unmerged index entry: {path}")
            result[path] = {"mode": mode, "blob": blob}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.baseline = args.baseline.resolve()
    args.export = args.export.resolve()
    frozen = json.loads(args.baseline.read_bytes())
    staged = index()
    regression = args.baseline.parent
    frozen_assets = []
    for name, expected in (
        ("contract.md", frozen["contract_sha256"]),
        ("isolation-status.json", frozen["isolation_sha256"]),
    ):
        frozen_assets.append(
            {
                "path": (regression / name).relative_to(ROOT).as_posix(),
                "matches": sha(regression / name) == expected,
            }
        )
    for freeze_name, replacements in (
        (
            "source-test-freeze.json",
            {
                "tests/test_document_relations_source_roles.py":
                    regression / "source-test-first.py.txt",
            },
        ),
        (
            "header-test-first-freeze.json",
            {
                "tests/test_document_relations_proof_headers.py":
                    regression / "header-test-first.py.txt",
            },
        ),
        ("final-public-test-freeze.json", {}),
    ):
        test_freeze = json.loads((regression / freeze_name).read_bytes())
        for relative, expected in test_freeze["files"].items():
            path = replacements.get(relative, ROOT / relative)
            frozen_assets.append(
                {
                    "freeze": freeze_name,
                    "path": path.relative_to(ROOT).as_posix(),
                    "matches": sha(path) == expected,
                }
            )
    protected, changed = [], []
    for relative, expected in frozen["tracked_files"].items():
        path = ROOT / relative
        working = sha(path) if path.is_file() else None
        blob = (staged.get(relative) or {}).get("blob")
        row = {
            "path": relative,
            "working_sha256": working,
            "git_blob": blob,
            "original_working_sha256": expected["working_sha256"],
            "original_git_blob": expected["git_blob"],
        }
        if relative in ALLOWED:
            if (
                working != expected["working_sha256"]
                or blob != expected["git_blob"]
            ):
                changed.append(row)
        else:
            row["unchanged"] = (
                working == expected["working_sha256"]
                and blob == expected["git_blob"]
            )
            protected.append(row)
    proof = []
    aggregate = hashlib.sha256()
    for relative, expected in sorted(staged.items()):
        selected = (
            relative.startswith("src/") and relative.endswith(".py")
        ) or (
            relative.endswith(".py")
            and (
                relative.startswith("scripts/run_document_relations")
                or relative.startswith("tests/") and "document_relations" in relative
                or relative.startswith(
                    "benchmarks/document_relations/source-role-regression/"
                )
            )
        )
        if not selected:
            continue
        path = args.export / relative
        raw = path.read_bytes()
        blob = hashlib.sha1(
            b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
        ).hexdigest()
        digest = hashlib.sha256(raw).hexdigest()
        proof.append(
            {
                "path": relative,
                "canonical_sha256": digest,
                "git_blob": expected["blob"],
                "export_git_blob": blob,
                "matches": blob == expected["blob"],
            }
        )
        if relative.startswith("src/"):
            aggregate.update(
                relative.encode() + b"\t" + bytes.fromhex(digest) + b"\n"
            )
    valid = (
        all(row["unchanged"] for row in protected)
        and all(row["matches"] for row in proof)
        and all(row["matches"] for row in frozen_assets)
    )
    report = {
        "schema": "source-role-canonical-proof-v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "baseline_sha256": sha(args.baseline),
        "source_tree_sha256": aggregate.hexdigest(),
        "protected_files": len(protected),
        "protected_unchanged": sum(row["unchanged"] for row in protected),
        "canonical_code_files": len(proof),
        "canonical_matches": sum(row["matches"] for row in proof),
        "frozen_contract_test_assets": len(frozen_assets),
        "frozen_contract_test_matches": sum(
            row["matches"] for row in frozen_assets
        ),
        "status": "passed" if valid else "failed",
        "allowed_changes": changed,
        "code_proof": proof,
        "frozen_contract_test_proof": frozen_assets,
        "protected_proof": protected,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(
        json.dumps(
            {
                key: value
                for key, value in report.items()
                if not isinstance(value, list)
            },
            indent=2,
        )
    )
    if not valid:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
