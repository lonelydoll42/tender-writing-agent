"""Build a source release archive without local secrets or build caches."""

from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path


EXCLUDED_NAMES = {
    ".env",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".qiaowenshu",
    "dist",
    "build",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".egg-info"}
SECRET_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|secret|password|token)[ \t]*[:=][ \t]*['\"]?"
    r"([A-Za-z0-9_\-/.+=]{16,})"
)
KNOWN_TEST_VALUES = {"should-not-appear", "example-placeholder"}


def build_archive(root: Path, output: Path) -> list[str]:
    output = output.resolve()
    included: list[str] = []
    findings: list[str] = []
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.resolve() == output:
                continue
            relative = path.relative_to(root)
            if _excluded(relative):
                continue
            if _looks_like_text(path):
                try:
                    content = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    content = ""
                if _has_suspect_secret(content):
                    findings.append(str(relative))
                    continue
            archive.write(path, relative.as_posix())
            included.append(relative.as_posix())
    if findings:
        output.unlink(missing_ok=True)
        raise RuntimeError(
            "possible secret values found; archive was not created: "
            + ", ".join(findings)
        )
    return included


def _excluded(path: Path) -> bool:
    return any(
        part in EXCLUDED_NAMES
        or part.endswith(tuple(EXCLUDED_SUFFIXES))
        or part.startswith("trace-")
        for part in path.parts
    )


def _looks_like_text(path: Path) -> bool:
    return path.suffix.lower() in {
        ".env",
        ".example",
        ".json",
        ".md",
        ".py",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
    }


def _has_suspect_secret(content: str) -> bool:
    for match in SECRET_PATTERN.finditer(content):
        value = match.group(1).strip("'\"")
        if value in KNOWN_TEST_VALUES or value.startswith("test-"):
            continue
        return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="dist/qiaowenshu-agent-source.zip")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = (root / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    files = build_archive(root, output)
    print(f"created {output} with {len(files)} files")


if __name__ == "__main__":
    main()
