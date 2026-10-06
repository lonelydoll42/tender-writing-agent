"""Run the public raw-requirement regression corpus through the real workflow."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qiaowenshu_agent.core.contracts import SkillRequest  # noqa: E402
from qiaowenshu_agent.core.files import ProjectFileRegistry  # noqa: E402
from qiaowenshu_agent.core.runtime import AgentRuntime  # noqa: E402
from qiaowenshu_agent.skills import build_default_registry  # noqa: E402


BUNDLE = ROOT / "benchmarks" / "raw_requirement_holdout"
MANIFEST_PATH = BUNDLE / "freeze-manifest.json"
ORACLE_PATH = BUNDLE / "oracle" / "cases.json"
MACHINE_FREEZE_PATH = BUNDLE / "oracle" / "machine-freeze.json"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _git_metadata(root: Path) -> dict[str, Any]:
    top_level = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if (
        top_level.returncode != 0
        or Path(top_level.stdout.strip()).resolve() != root.resolve()
    ):
        return {
            "repository_context": "archive/no_local_git_root",
            "git_revision_at_run": None,
            "git_worktree_dirty": None,
            "git_worktree_dirty_scope": "unavailable",
            "git_src_worktree_dirty": None,
            "git_src_worktree_status": None,
        }

    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    worktree = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    source = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", "src"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "repository_context": "git_worktree",
        "git_revision_at_run": (
            revision.stdout.strip() if revision.returncode == 0 else None
        ),
        "git_worktree_dirty": (
            bool(worktree.stdout.strip()) if worktree.returncode == 0 else None
        ),
        "git_worktree_dirty_scope": "entire local worktree including untracked files",
        "git_src_worktree_dirty": (
            bool(source.stdout.strip()) if source.returncode == 0 else None
        ),
        "git_src_worktree_status": (
            source.stdout.splitlines() if source.returncode == 0 else None
        ),
    }


def validate_oracle_coverage(
    manifest: Mapping[str, Any], oracle: Mapping[str, Any]
) -> None:
    manifest_raw = {
        item["path"]
        for item in manifest["inputs"]["documents"]
        if item["path"].startswith("raw/")
    }
    oracle_raw = {case["file"] for case in oracle.get("cases", [])}
    if (
        len(oracle.get("cases", [])) != 8
        or len(oracle_raw) != 8
        or oracle_raw != manifest_raw
    ):
        raise ValueError(
            "machine oracle cases do not exactly match the 8 frozen raw inputs"
        )


def verify_freeze() -> dict[str, Any]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    machine_freeze = json.loads(MACHINE_FREEZE_PATH.read_text(encoding="utf-8"))
    cases_bytes = ORACLE_PATH.read_bytes()
    cases_hash = _sha256(cases_bytes)
    if cases_hash != machine_freeze["cases_sha256"]:
        raise ValueError("machine oracle hash mismatch")
    oracle = json.loads(cases_bytes.decode("utf-8"))
    validate_oracle_coverage(manifest, oracle)
    checked: list[dict[str, Any]] = []
    for item in manifest["inputs"]["documents"]:
        path = BUNDLE / item["path"]
        raw = path.read_bytes()
        checked.append(
            {
                "path": item["path"],
                "expected_sha256": item["sha256"],
                "actual_sha256": _sha256(raw),
                "expected_bytes": item["bytes"],
                "actual_bytes": len(raw),
            }
        )
    oracle_path = BUNDLE / manifest["oracle"]["path"]
    oracle_bytes = oracle_path.read_bytes()
    checked.append(
        {
            "path": manifest["oracle"]["path"],
            "expected_sha256": manifest["oracle"]["sha256"],
            "actual_sha256": _sha256(oracle_bytes),
            "expected_bytes": None,
            "actual_bytes": len(oracle_bytes),
        }
    )
    canonical = "".join(
        f"{item['path']}\t{item['actual_sha256']}\n"
        for item in sorted(checked, key=lambda entry: entry["path"])
    ).encode("utf-8")
    actual_fingerprint = _sha256(canonical)
    valid = (
        all(
            item["expected_sha256"] == item["actual_sha256"]
            and (
                item["expected_bytes"] is None
                or item["expected_bytes"] == item["actual_bytes"]
            )
            for item in checked
        )
        and actual_fingerprint == manifest["bundle_fingerprint"]["value"]
    )
    if not valid:
        raise ValueError("frozen raw/oracle hashes or bundle fingerprint mismatch")
    return {
        "files": checked,
        "bundle_fingerprint": actual_fingerprint,
        "machine_oracle_sha256": cases_hash,
        "machine_oracle_freeze": machine_freeze,
        "runner_sha256": _sha256(Path(__file__).read_bytes()),
        "runner_hash_frozen": False,
        "valid": valid,
    }


def _walk(value: Any):
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


STRUCTURAL_OPS = {
    "all",
    "and",
    "any",
    "or",
    "not",
    "sameperson",
    "date_range",
    "comparison",
    "evidence",
    "manual",
    "manual_review",
    "version_floor",
}
NON_SEMANTIC_FIELDS = {
    "source_text",
    "text",
    "description",
    "title",
    "note",
    "message",
    "reason_text",
    "quote",
    "raw_text",
}


def _condition_trees(requirements: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    trees = []
    for requirement in requirements:
        rule = requirement.get("check_rule")
        logic = rule.get("condition_logic") if isinstance(rule, Mapping) else None
        if isinstance(logic, Mapping):
            trees.append(logic)
    return trees


def _semantic_values(node: Mapping[str, Any]) -> str:
    return " ".join(
        str(value)
        for key, value in node.items()
        if key not in NON_SEMANTIC_FIELDS
        and key not in {"conditions", "condition", "children"}
        and not isinstance(value, (dict, list))
    ).casefold()


def _children(node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    children = node.get("conditions", node.get("children"))
    if isinstance(children, list):
        return [child for child in children if isinstance(child, Mapping)]
    condition = node.get("condition")
    return [condition] if isinstance(condition, Mapping) else []


def _meaningful_leaf(node: Mapping[str, Any]) -> bool:
    op = str(node.get("op", "")).lower()
    if op not in {"evidence", "comparison", "date_range", "version_floor"}:
        return False
    if _children(node):
        return False
    if op == "evidence":
        return bool(node.get("material_type") or node.get("evidence_type"))
    if op == "comparison":
        return (
            bool(node.get("field"))
            and str(node.get("operator", "")).lower()
            in {
                "eq",
                "ne",
                "gte",
                "gt",
                "lte",
                "lt",
                ">=",
                ">",
                "<=",
                "<",
                "in",
                "not_in",
            }
            and "value" in node
        )
    if op == "date_range":
        return (
            bool(node.get("field"))
            and bool(node.get("start"))
            and bool(node.get("end"))
            and node.get("continuous") in {True, False}
        )
    return (
        bool(node.get("field") or node.get("product"))
        and bool(node.get("minimum") or node.get("value"))
        and str(node.get("operator", "gte")).lower() in {"gte", ">=", "at_least"}
    )


def _walk_logic(node: Mapping[str, Any]):
    if str(node.get("op", "")).lower() not in STRUCTURAL_OPS:
        return
    yield node
    for child in _children(node):
        yield from _walk_logic(child)


def _branch_has_leaf(branch: Mapping[str, Any], aliases: list[str] | None) -> bool:
    leaves = [node for node in _walk_logic(branch) if _meaningful_leaf(node)]
    if not leaves:
        return False
    if not aliases:
        return True
    return any(
        any(alias.casefold() in _semantic_values(leaf) for alias in aliases)
        for leaf in leaves
    )


def _predicate_matches(node: Mapping[str, Any], predicate: Mapping[str, Any]) -> bool:
    op = str(predicate["op"])
    actual = str(node.get("op", "")).lower()
    if op == "date_range":
        return (
            actual == "date_range"
            and _meaningful_leaf(node)
            and node.get("start") == predicate["start"]
            and node.get("end") == predicate["end"]
            and node.get("continuous") is predicate["continuous"]
        )
    if op == "sameperson":
        if actual != "sameperson":
            return False
        subject_field = node.get("person_field") or node.get("subject_field")
        if subject_field not in {"person_id", "person", "subject_id", "person_name"}:
            return False
        nested = list(_walk_logic(node))
        leaves = [item for item in nested if _meaningful_leaf(item)]
        person = any(
            any(
                token in _semantic_values(leaf) for token in predicate["person_aliases"]
            )
            for leaf in leaves
        )
        employer = any(
            any(
                token in _semantic_values(leaf)
                for token in predicate["employer_aliases"]
            )
            for leaf in leaves
        )
        date_in_scope = any(
            str(item.get("op", "")).lower() == "date_range"
            and item.get("field") == predicate["date_field"]
            and _meaningful_leaf(item)
            and item.get("start") == predicate["start"]
            and item.get("end") == predicate["end"]
            and item.get("continuous") is predicate["continuous"]
            for item in nested
        )
        return bool(subject_field and person and employer and date_in_scope)
    if op == "not":
        if actual != "not":
            return False
        target = node.get("condition")
        if not isinstance(target, Mapping):
            return False
        return _meaningful_leaf(target) and all(
            target.get(key) == value for key, value in predicate["target"].items()
        )
    if op == "threshold":
        return (
            actual == "comparison"
            and node.get("field") == predicate["field"]
            and str(node.get("operator", "")).lower() == predicate["operator"]
            and str(node.get("value")) == str(predicate["value"])
            and _meaningful_leaf(node)
        )
    if op == "version_floor":
        actual_product = str(node.get("product", node.get("field", ""))).casefold()
        product_matches = actual_product in {
            "postgresql",
            "postgresql_version",
            "postgres_version",
            "postgres_version_number",
        }
        operator = str(node.get("operator", "gte")).lower()
        return (
            actual in {"version_floor", "comparison"}
            and product_matches
            and operator in {"gte", ">=", "at_least"}
            and str(node.get("minimum", node.get("value"))) == str(predicate["minimum"])
            and _meaningful_leaf(node)
        )
    if op == "manual":
        return (
            actual in {"manual", "manual_review"}
            and node.get("required") is True
            and bool(node.get("target"))
            and node.get("target") == predicate["target"]
        )
    return False


def _logic_check(
    requirements: list[Mapping[str, Any]], specs: list[dict[str, Any]]
) -> dict[str, Any]:
    trees = [
        node for tree in _condition_trees(requirements) for node in _walk_logic(tree)
    ]
    results = []
    for spec in specs:
        op = spec["op"]
        if op in {"any", "and"}:
            wanted = "any" if op == "any" else "all"
            acceptable = {"any", "or"} if wanted == "any" else {"all", "and"}
            found = False
            for node in trees:
                children = _children(node)
                if str(node.get("op", "")).lower() not in acceptable:
                    continue
                if len(children) < len(spec["branches"]):
                    continue
                if op == "any" and len(children) != len(spec["branches"]):
                    continue
                candidates = [
                    [
                        index
                        for index, child in enumerate(children)
                        if _branch_has_leaf(child, aliases)
                    ]
                    for aliases in spec["branches"]
                ]

                def has_distinct_assignment(position: int, used: set[int]) -> bool:
                    if position == len(candidates):
                        return True
                    return any(
                        index not in used
                        and has_distinct_assignment(position + 1, used | {index})
                        for index in candidates[position]
                    )

                if has_distinct_assignment(0, set()):
                    found = True
                    break
        else:
            found = any(_predicate_matches(node, spec) for node in trees)
        results.append({"spec": spec, "passed": found})
    return {
        "status": "passed"
        if results and all(item["passed"] for item in results)
        else "failed",
        "checks": results,
        "tree_count": len(trees),
    }


def _line_number(raw_text: str, quote: str) -> int | None:
    for number, line in enumerate(raw_text.splitlines(), 1):
        if quote and quote in line:
            return number
    return None


def _citation_check(
    ref: Mapping[str, Any],
    raw_pages: list[str],
    file_id: str,
    version_token: str,
) -> dict[str, Any]:
    page = ref.get("page") or ref.get("page_number")
    quote = str(ref.get("quote") or ref.get("exact_quote") or ref.get("text") or "")
    locator = str(ref.get("locator") or "")
    match = re.search(r":p(\d+):l(\d+)$", locator)
    page_text = (
        raw_pages[page - 1]
        if isinstance(page, int) and 1 <= page <= len(raw_pages)
        else None
    )
    lines = page_text.splitlines() if page_text is not None else []
    locator_page = int(match.group(1)) if match else None
    line_number = int(match.group(2)) if match else None
    physical_line = (
        lines[line_number - 1].strip()
        if line_number is not None and 1 <= line_number <= len(lines)
        else None
    )
    ref_file_id = ref.get("file_id") or ref.get("document_id")
    return {
        "registry_id": ref_file_id,
        "registry_id_valid": ref_file_id == file_id,
        "source_version": ref.get("source_version"),
        "source_version_valid": ref.get("source_version") == version_token,
        "page": page,
        "locator": locator,
        "locator_valid": bool(match) and locator_page == page,
        "quote": quote,
        "physical_line": physical_line,
        "quote_matches_physical_line": bool(quote) and quote == physical_line,
    }


def evaluate_case(
    case: dict[str, Any],
    parser: dict[str, Any],
    raw_text: str,
    file_id: str,
    version_token: str,
) -> dict[str, Any]:
    requirements = parser["requirements"]
    searchable_text = " ".join(
        str(value)
        for requirement in requirements
        for value in (
            requirement.get("title"),
            requirement.get("description"),
            requirement.get("evidence_required"),
        )
        if value is not None
    ).casefold()
    text_groups = [
        {
            "alternatives": group,
            "passed": bool(group)
            and any(term.casefold() in searchable_text for term in group),
        }
        for group in case["required_text_groups"]
    ]
    source_refs = [
        ref
        for requirement in requirements
        for ref in requirement.get("source_references", [])
        if isinstance(ref, Mapping)
    ]
    raw_pages = raw_text.split("\f")
    ref_checks = []
    for ref in source_refs:
        ref_checks.append(_citation_check(ref, raw_pages, file_id, version_token))
    anchor_scope = case.get("anchor_scope", {})
    oracle_quotes = [
        {
            "anchor": quote,
            "scope": anchor_scope.get(quote, "diagnostic_requirement_text"),
            "present_in_raw_line": any(
                quote in line for page in raw_pages for line in page.splitlines()
            ),
        }
        for quote in case["quotes"]
    ]
    logic = _logic_check(requirements, case["logic"])
    executed = parser["status"] in {"executed", "executed_empty"}
    checks_pass = (
        executed
        and bool(requirements)
        and all(item["passed"] for item in text_groups)
        and logic["status"] == "passed"
        and bool(ref_checks)
        and all(
            ref["registry_id_valid"]
            and ref["source_version_valid"]
            and ref["locator_valid"]
            and ref["quote_matches_physical_line"]
            and isinstance(ref["page"], int)
            for ref in ref_checks
        )
        and all(item["present_in_raw_line"] for item in oracle_quotes)
        and all(
            not (
                isinstance(requirement.get("check_rule"), Mapping)
                and isinstance(
                    requirement["check_rule"].get("condition_logic"), Mapping
                )
            )
            or bool(requirement.get("source_references"))
            for requirement in requirements
        )
    )
    return {
        "case_id": case["case_id"],
        "finite_check_status": (
            "passed" if checks_pass else ("failed" if executed else "not_run")
        ),
        "finite_check_scope": (
            "limited structural and provenance checks only; not a complete "
            "semantic assessment"
        ),
        "requirement_count": len(requirements),
        "text_groups": text_groups,
        "logic": logic,
        "source_references": ref_checks,
        "oracle_quotes": oracle_quotes,
        "citation_scope": (
            "denominator is parser-emitted source_references only; each must "
            "resolve to an exact raw physical line. Requirement branches need "
            "references on their own requirement. Embedded table/example "
            "anchors are diagnostic and are not business evidence."
        ),
    }


def _parser_snapshot(decomposition_data: Any) -> dict[str, Any]:
    if not isinstance(decomposition_data, Mapping):
        return {
            "parser": {"status": "not_run", "requirements": []},
            "parser_output": None,
            "decomposition_extraction_complete": None,
            "decomposition_needs_human_review": None,
        }
    requirements = list(decomposition_data.get("requirements") or [])
    return {
        "parser": {
            "status": "executed" if requirements else "executed_empty",
            "requirements": requirements,
        },
        "parser_output": dict(decomposition_data),
        "decomposition_extraction_complete": decomposition_data.get(
            "extraction_complete"
        ),
        "decomposition_needs_human_review": decomposition_data.get(
            "needs_human_review"
        ),
    }


async def _run_case(case: dict[str, Any]) -> dict[str, Any]:
    path = BUNDLE / case["file"]
    content = path.read_bytes()
    raw_text = content.decode("utf-8")
    project_id = f"raw-requirement-holdout-{case['case_id']}"
    registry = ProjectFileRegistry()
    registration = registry.register(
        project_id=project_id,
        file_name=path.name,
        file_role="tender",
        content=content,
    )
    file_id = registration.file.file_id
    token = registry.file_version_token(file_id)
    runtime = AgentRuntime(
        build_default_registry(file_registry=registry),
        services={"file_registry": registry},
    )
    result = await runtime.run(
        SkillRequest.create(
            {
                "project_id": project_id,
                "file_ids": [file_id],
                "bidder_file_ids": [],
                "bidder_id": "public-regression-no-business-materials",
                "bidder_name": "无投标材料（仅回归解析）",
                "as_of": "2026-10-06T00:00:00+08:00",
                "task": "这个项目能不能投？",
            }
        )
    )
    intake_steps = [step for step in result.steps if step.skill_name == "tender-intake"]
    decomposition_steps = [
        step for step in result.steps if step.skill_name == "tender-decomposition"
    ]
    intake_data = intake_steps[-1].result.data if intake_steps else None
    decomposition_data = (
        decomposition_steps[-1].result.data if decomposition_steps else None
    )
    parser_snapshot = _parser_snapshot(
        decomposition_data if decomposition_steps else None
    )
    parser = parser_snapshot["parser"]
    artifact = registry.parse(file_id)
    registry_pages = artifact.get("pages") or []
    raw_pages = raw_text.split("\f")
    registry_page_texts = [str(item.get("text") or "") for item in registry_pages]
    pages_match_raw = len(registry_page_texts) == len(raw_pages) and all(
        registered.strip() == raw_page.strip()
        for registered, raw_page in zip(registry_page_texts, raw_pages, strict=True)
    )
    case_result = evaluate_case(case, parser, raw_text, file_id, token)
    if not pages_match_raw:
        case_result["finite_check_status"] = (
            "failed" if parser["status"] != "not_run" else "not_run"
        )
    return {
        **case_result,
        **parser_snapshot,
        "file": path.name,
        "raw_sha256": _sha256(content),
        "inline_source_version_label": (
            re.search(r"(?m)^source_version:\s*(\S+)\s*$", raw_text).group(1)
            if re.search(r"(?m)^source_version:\s*(\S+)\s*$", raw_text)
            else None
        ),
        "registry": {
            "file_id": file_id,
            "source_version": token,
            "registered_checksum": registry.require(file_id).checksum,
            "registered_checksum_matches_raw": registry.require(file_id).checksum
            == _sha256(content),
        },
        "runtime": {
            "execution_status": result.execution_status,
            "execution_message": result.message,
            "intake_step_status": intake_steps[-1].result.status
            if intake_steps
            else "not_run",
            "intake_result_present": isinstance(intake_data, Mapping),
            "decomposition_step_status": decomposition_steps[-1].result.status
            if decomposition_steps
            else "not_run",
            "decomposition_result_present": isinstance(decomposition_data, Mapping),
        },
        "registry_pages": {
            "count": len(registry_pages),
            "form_feed_boundaries_preserved": len(registry_pages) == len(raw_pages),
            "page_text_matches_raw_pages": pages_match_raw,
        },
        "business_evidence": "not_run",
    }


async def run_evaluation() -> dict[str, Any]:
    freeze = verify_freeze()
    oracle = json.loads(ORACLE_PATH.read_text(encoding="utf-8"))
    git = _git_metadata(ROOT)
    product_files = sorted((ROOT / "src").rglob("*.py"))
    product_hash = hashlib.sha256()
    for path in product_files:
        relative = path.relative_to(ROOT).as_posix()
        product_hash.update(relative.encode("utf-8") + b"\t")
        product_hash.update(bytes.fromhex(_sha256(path.read_bytes())) + b"\n")
    cases = [await _run_case(case) for case in oracle["cases"]]
    return {
        "schema": "raw-requirement-holdout-eval-v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "classification": "public_regression_not_blind_holdout",
        "evaluation_baseline_revision": "9ac022b",
        **git,
        "source_tree_sha256": product_hash.hexdigest(),
        "source_tree_sha256_scope": (
            "SHA-256 over sorted src/**/*.py relative paths and their file SHA-256; "
            "this is the measured source snapshot, independent of Git revision"
        ),
        "freeze": freeze,
        "case_count": len(cases),
        "denominator": 8,
        "finite_checks_passed": sum(
            case["finite_check_status"] == "passed" for case in cases
        ),
        "finite_checks_failed": sum(
            case["finite_check_status"] == "failed" for case in cases
        ),
        "not_run": sum(case["finite_check_status"] == "not_run" for case in cases),
        "oracle_scope": {
            "machine_oracle_is_limited_public_regression": True,
            "not_equivalent_to_historical_full_semantic_assessment": True,
            "embedded_evidence_anchors_are_diagnostic_only": True,
            "business_evidence": "not_run/8",
        },
        "business_evidence": {"status": "not_run", "denominator": 8},
        "claims": {
            "real_model_used": False,
            "real_ocr_used": False,
            "blind_holdout": False,
            "business_material_registered": False,
        },
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="write JSON to this path only if it does not already exist",
    )
    args = parser.parse_args(argv)
    if args.output is not None:
        output = args.output.resolve()
        if output.exists():
            parser.error(f"refusing to overwrite existing report: {output}")
    report = asyncio.run(run_evaluation())
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(rendered)
    return 0 if report["finite_checks_failed"] == 0 and report["not_run"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
