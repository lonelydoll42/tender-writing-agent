"""Verify this batch's canonical export, code and frozen historical bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
REGRESSION = ROOT / "benchmarks/document_relations/copy-alternative-regression/20261014"
PREVIOUS_PROOF = (
    ROOT / "benchmarks/document_relations/reports"
    "/attribute-followup-20261014/reviewer/final-code-proof.json"
)
NEW_CODE = {
    "tests/test_document_relations_copy_alternatives.py",
    Path(__file__).relative_to(ROOT).as_posix(),
}


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


def tree_blobs(tree: str) -> dict[str, str]:
    result = {}
    for line in git("ls-tree", "-r", tree).splitlines():
        metadata, path = line.split("\t", 1)
        _mode, kind, blob = metadata.split()
        if kind != "blob":
            raise ValueError(f"unsupported non-blob export entry: {path}")
        result[path] = blob
    return result


def raw_blob(path: Path) -> str:
    content = path.read_bytes()
    header = b"blob " + str(len(content)).encode("ascii") + b"\0"
    return hashlib.sha1(header + content).hexdigest()


def verify(export: Path, tree: str) -> dict:
    if git("rev-parse", "--show-object-format").strip() != "sha1":
        raise ValueError("this verifier requires a SHA-1 Git object repository")
    frozen = json.loads((REGRESSION / "scope-freeze.json").read_bytes())
    for name in ("contract", "cases"):
        if (
            sha(REGRESSION / f"{name}.{'md' if name == 'contract' else 'json'}")
            != (frozen["frozen_inputs"][f"{name}_sha256"])
        ):
            raise ValueError(f"frozen input changed: {name}")
    index = {}
    for line in git("ls-files", "-s").splitlines():
        metadata, path = line.split("\t", 1)
        _mode, blob, stage = metadata.split()
        if stage != "0":
            raise ValueError(f"unmerged index: {path}")
        index[path] = blob
    archived = tree_blobs(tree)
    for path, expected in archived.items():
        if raw_blob(export / path) != expected:
            raise ValueError(f"export differs from raw Git bytes: {path}")

    previous = json.loads(PREVIOUS_PROOF.read_bytes())
    paths = {row["path"] for row in previous["code"]} | NEW_CODE
    code = []
    for path in sorted(paths):
        expected = archived.get(path)
        if not expected or expected != index.get(path):
            raise ValueError(f"code tree differs from current index: {path}")
        if git("hash-object", f"--path={path}", "--", str(ROOT / path)).strip() != (
            expected
        ):
            raise ValueError(f"working code differs from filtered Git bytes: {path}")
        code.append(
            {
                "path": path,
                "canonical_sha256": sha(export / path),
                "git_blob": expected,
                "matches": True,
            }
        )
    source = [row for row in code if row["path"].startswith("src/")]
    actual_source = {
        path.relative_to(export).as_posix() for path in (export / "src").rglob("*.py")
    }
    if actual_source != {row["path"] for row in source}:
        raise ValueError("source inventory differs from the prior code proof")
    digest = hashlib.sha256()
    for row in source:
        digest.update(row["path"].encode("utf-8") + b"\t")
        digest.update(bytes.fromhex(row["canonical_sha256"]) + b"\n")

    protected = []
    for path, expected in sorted(frozen["tracked_files"].items()):
        if path in frozen["allowed_existing_changes"]:
            continue
        working = sha(ROOT / path)
        if (
            working != expected["working_sha256"]
            or index.get(path) != expected["git_blob"]
            or archived.get(path) != expected["git_blob"]
        ):
            raise ValueError(f"protected historical file changed: {path}")
        protected.append(
            {
                "path": path,
                "working_sha256": working,
                "git_blob": expected["git_blob"],
                "matches": True,
            }
        )
    return {
        "schema": "copy-alternative-canonical-proof-v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "base_commit": frozen["base_commit"],
        "archive_tree": tree,
        "archive_scope": (
            "Canonical code and pre-publication assets. Later reports/docs/metadata "
            "are outside this tree; final commit must retain all code blobs."
        ),
        "source_tree_sha256": digest.hexdigest(),
        "product_source_files": len(source),
        "canonical_code_files": len(code),
        "canonical_git_blob_matches": len(code),
        "exported_git_files": len(archived),
        "exported_git_blob_matches": len(archived),
        "protected_files": len(protected),
        "protected_matches": len(protected),
        "scope_freeze_sha256": sha(REGRESSION / "scope-freeze.json"),
        "audit_tool_sha256": sha(Path(__file__)),
        "code": code,
        "protected": protected,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--archive-tree", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must be a new path")
    report = verify(args.export.resolve(strict=True), args.archive_tree)
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
