"""Verify exported code bytes and protected history against Git and the freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
REGRESSION = ROOT / "benchmarks/document_relations/attribute-regression/20261014"
OLD_PROOF = (
    ROOT / "benchmarks/document_relations/reports"
    "/current-baseline-20e79af-20261013/reviewer/final-code-proof.json"
)
NEW_CODE = (
    "scripts/run_document_relations_attribute_eval.py",
    "scripts/run_document_relations_snapshot_rescore.py",
    "tests/test_document_relations_attributes.py",
    "tests/evals/test_document_relations_snapshot_rescore.py",
    "benchmarks/document_relations/attribute-regression/20261014/check-acceptance.py",
)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        encoding="utf-8",
    ).stdout


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(export: Path, tree: str, include_audit_tool: bool) -> dict:
    frozen = json.loads((REGRESSION / "scope-freeze.json").read_bytes())
    previous = json.loads(OLD_PROOF.read_bytes())
    index = {}
    for line in git("ls-files", "-s").splitlines():
        metadata, path = line.split("\t", 1)
        _mode, blob, stage = metadata.split()
        if stage != "0":
            raise ValueError(f"unmerged index: {path}")
        index[path] = blob
    archived = {}
    for line in git("ls-tree", "-r", tree).splitlines():
        metadata, path = line.split("\t", 1)
        _mode, kind, blob = metadata.split()
        if kind != "blob":
            raise ValueError(f"unexpected archive object: {path}")
        archived[path] = blob
    for path, expected in archived.items():
        if (
            git("hash-object", "--no-filters", "--", str(export / path)).strip()
            != expected
        ):
            raise ValueError(f"export does not match Git tree: {path}")

    paths = {row["path"] for row in previous["code"]} | set(NEW_CODE)
    if include_audit_tool:
        paths.add(Path(__file__).relative_to(ROOT).as_posix())
    code = []
    for path in sorted(paths):
        if archived.get(path) != index.get(path) or path not in archived:
            raise ValueError(f"exported code does not match index: {path}")
        code.append(
            {
                "path": path,
                "canonical_sha256": sha(export / path),
                "git_blob": archived[path],
                "matches": True,
            }
        )
    source = [row for row in code if row["path"].startswith("src/")]
    digest = hashlib.sha256()
    for row in source:
        digest.update(row["path"].encode("utf-8") + b"\t")
        digest.update(bytes.fromhex(row["canonical_sha256"]) + b"\n")
    actual_source = {
        path.relative_to(export).as_posix() for path in (export / "src").rglob("*.py")
    }
    if actual_source != {row["path"] for row in source}:
        raise ValueError("source inventory differs from the code proof")

    protected = []
    for path, expected in sorted(frozen["tracked_files"].items()):
        if path in frozen["allowed_existing_changes"]:
            continue
        working = sha(ROOT / path)
        if (
            working != expected["working_sha256"]
            or index.get(path) != expected["git_blob"]
        ):
            raise ValueError(f"protected historical file changed: {path}")
        protected.append(
            {
                "path": path,
                "working_sha256": working,
                "git_blob": index[path],
                "matches": True,
            }
        )
    return {
        "schema": "attribute-code-snapshot-proof-v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "base_commit": frozen["base_commit"],
        "code_archive_base_tree": tree,
        "archive_scope": (
            "Code and pre-publication asset snapshot; final docs and metadata "
            "are added later. Code blobs must still match the final commit."
        ),
        "source_tree_sha256": digest.hexdigest(),
        "product_source_files": len(source),
        "canonical_code_files": len(code),
        "canonical_git_blob_matches": len(code),
        "exported_git_files": len(archived),
        "exported_git_blob_matches": len(archived),
        "protected_files": len(protected),
        "protected_working_and_index_matches": len(protected),
        "scope_freeze_sha256": sha(REGRESSION / "scope-freeze.json"),
        "audit_tool_sha256": sha(Path(__file__)),
        "audit_tool_in_export": include_audit_tool,
        "code": code,
        "protected": protected,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--archive-tree", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-audit-tool", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must be a new path")
    result = verify(
        args.export.resolve(strict=True), args.archive_tree, args.include_audit_tool
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(
        json.dumps(
            {
                key: result[key]
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
