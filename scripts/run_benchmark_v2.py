"""Run the metric-based Benchmark V2 corpus without a weighted total score."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Mapping

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.skills.evidence_matching import EvidenceMatchingSkill

from scripts.run_tender_v2_eval import analyze_scenario, load_business_input


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "benchmarks" / "tender_v2_corpus.json"


async def evaluate_corpus(corpus: Mapping[str, Any]) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for raw_case in corpus.get("cases") or []:
        case = _mapping(raw_case, "case")
        cases.append(await _evaluate_case(case))
    return {
        "protocol_version": str(corpus.get("protocol_version") or "2.0"),
        "benchmark_name": str(corpus.get("benchmark_name") or "benchmark-v2"),
        "case_count": len(cases),
        "cases": cases,
        "metrics": _aggregate_metrics(cases),
    }


def run_corpus(corpus_path: str | Path = DEFAULT_CORPUS) -> dict[str, Any]:
    corpus = json.loads(Path(corpus_path).read_text(encoding="utf-8"))
    return asyncio.run(evaluate_corpus(corpus))


async def _evaluate_case(case: Mapping[str, Any]) -> dict[str, Any]:
    case_id = str(case.get("id") or "").strip()
    expected = _mapping(case.get("expected"), "expected")
    kind = str(case.get("kind") or "tender_v2")
    if kind == "tender_v2":
        analysis = await analyze_scenario(str(case["scenario_id"]))
        observed = _tender_observed(analysis)
        input_data = load_business_input(str(case["scenario_id"]))
        known_references = _known_references(input_data)
    elif kind == "evidence_matching":
        analysis = await _run_evidence_matching(_mapping(case.get("input"), "input"))
        observed = _evidence_observed(analysis)
        known_references = _known_references(_mapping(case.get("input"), "input"))
    else:
        raise ValueError(f"unsupported benchmark case kind: {kind}")

    metrics = _case_metrics(expected, observed, known_references)
    return {
        "case_id": case_id,
        "kind": kind,
        "metrics": metrics,
        "observed": observed,
    }


async def _run_evidence_matching(data: Mapping[str, Any]) -> dict[str, Any]:
    request = SkillRequest.create(data, skill_name="evidence-matching")
    result = await EvidenceMatchingSkill().execute(
        request,
        SkillContext(run_id="benchmark-v2-ocr", request=request),
    )
    if result.status in {"error", "retryable_error", "blocked"}:
        raise RuntimeError(result.message or "evidence matching failed")
    return result.data


def _tender_observed(analysis: Mapping[str, Any]) -> dict[str, Any]:
    steps = _mapping(analysis.get("steps"), "analysis.steps")
    evidence = _mapping(steps.get("evidence_matching"), "evidence_matching")
    feasibility = _mapping(steps.get("bid_feasibility"), "bid_feasibility")
    scoring = _mapping(steps.get("scoring_strategy"), "scoring_strategy")
    return {
        "evidence_matches": list(evidence.get("matches") or []),
        "feasibility_checks": list(feasibility.get("checks") or []),
        "scoring_items": list(scoring.get("scoring_items") or []),
    }


def _evidence_observed(result: Mapping[str, Any]) -> dict[str, Any]:
    return {"evidence_matches": list(result.get("matches") or [])}


def _case_metrics(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
    known_references: set[tuple[str, int | None, str]],
) -> dict[str, Any]:
    evidence_matches = _by_id(observed.get("evidence_matches"))
    feasibility_checks = _by_id(observed.get("feasibility_checks"))
    scoring_items = _by_id(observed.get("scoring_items"))
    evidence_positive = {
        identifier
        for identifier, item in evidence_matches.items()
        if str(item.get("status")) == "matched"
    }
    expected_covered = _string_set(expected.get("evidence_covered_ids"))
    expected_hard = _string_set(expected.get("hard_requirement_ids"))
    expected_scoring = _string_set(expected.get("scoring_item_ids"))
    expected_conflicts = _string_set(expected.get("conflict_ids"))
    critical_ids = _string_set(expected.get("critical_requirement_ids"))

    return {
        "hard_requirement_recall": _recall(
            set(feasibility_checks), expected_hard
        ),
        "scoring_item_recall": _recall(set(scoring_items), expected_scoring),
        "source_reference_accuracy": _source_reference_accuracy(
            evidence_matches.values(), known_references
        ),
        "evidence_precision": _precision(evidence_positive, expected_covered),
        "evidence_recall": _recall(evidence_positive, expected_covered),
        "conflict_recall": _recall(
            {
                identifier
                for identifier, item in evidence_matches.items()
                if str(item.get("status")) == "conflict"
            },
            expected_conflicts,
        ),
        "critical_false_pass": _critical_false_pass(
            feasibility_checks, critical_ids
        ),
        "ocr_human_review_precision": _ocr_precision(
            evidence_matches, expected
        ),
    }


def _aggregate_metrics(cases: list[Mapping[str, Any]]) -> dict[str, Any]:
    names = (
        "hard_requirement_recall",
        "scoring_item_recall",
        "source_reference_accuracy",
        "evidence_precision",
        "evidence_recall",
        "conflict_recall",
        "critical_false_pass",
        "ocr_human_review_precision",
    )
    result: dict[str, Any] = {}
    for name in names:
        values = [
            _mapping(case.get("metrics"), "case.metrics")[name]
            for case in cases
            if _mapping(case.get("metrics"), "case.metrics")[name]["value"]
            is not None
        ]
        if not values:
            result[name] = {"value": None, "case_count": 0}
            continue
        numerator = sum(float(item.get("numerator", 0)) for item in values)
        denominator = sum(float(item.get("denominator", 0)) for item in values)
        value = numerator / denominator if denominator else None
        result[name] = {
            "value": round(value, 4) if value is not None else None,
            "numerator": _number(numerator),
            "denominator": _number(denominator),
            "case_count": len(values),
        }
    return result


def _source_reference_accuracy(
    matches: Any,
    known: set[tuple[str, int | None, str]],
) -> dict[str, Any]:
    references = [
        reference
        for match in matches
        if isinstance(match, Mapping)
        for reference in match.get("source_references") or []
        if isinstance(reference, Mapping)
    ]
    valid = sum(1 for reference in references if _reference_key(reference) in known)
    return _metric(valid, len(references))


def _critical_false_pass(
    checks: Mapping[str, Mapping[str, Any]],
    critical_ids: set[str],
) -> dict[str, Any]:
    false_pass = sum(
        1
        for identifier in critical_ids
        if str(checks.get(identifier, {}).get("status")) == "pass"
    )
    return {
        "value": false_pass,
        "numerator": false_pass,
        "denominator": len(critical_ids),
        "false_pass_ids": [
            identifier
            for identifier in sorted(critical_ids)
            if str(checks.get(identifier, {}).get("status")) == "pass"
        ],
    }


def _ocr_precision(
    matches: Mapping[str, Mapping[str, Any]],
    expected: Mapping[str, Any],
) -> dict[str, Any]:
    targets = _string_set(expected.get("ocr_targets"))
    expected_review = _string_set(expected.get("human_review_targets"))
    predicted = {
        identifier
        for identifier, item in matches.items()
        if identifier in targets and str(item.get("status")) == "human_review"
    }
    true_positive = len(predicted & expected_review)
    return _metric(
        true_positive,
        len(predicted),
        extra={"predicted": sorted(predicted)},
    )


def _known_references(data: Mapping[str, Any]) -> set[tuple[str, int | None, str]]:
    references: list[Any] = []
    project = data.get("project")
    if isinstance(project, Mapping):
        references.extend(project.get("source_references") or [])
    for key in ("requirements", "scoring_items", "materials"):
        for item in data.get(key) or []:
            if isinstance(item, Mapping):
                references.extend(item.get("source_references") or [])
    return {
        key
        for item in references
        if isinstance(item, Mapping)
        for key in [_reference_key(item)]
    }


def _by_id(value: Any) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for item in value or []:
        if not isinstance(item, Mapping):
            continue
        identifier = str(
            item.get("requirement_id") or item.get("item_id") or ""
        ).strip()
        if identifier:
            result[identifier] = item
    return result


def _reference_key(value: Mapping[str, Any]) -> tuple[str, int | None, str]:
    page = value.get("page", value.get("page_number"))
    try:
        page = int(page) if page is not None else None
    except (TypeError, ValueError):
        page = None
    return (
        str(value.get("document_id") or value.get("file_id") or ""),
        page,
        str(value.get("section") or value.get("section_path") or ""),
    )


def _precision(predicted: set[str], expected: set[str]) -> dict[str, Any]:
    return _metric(len(predicted & expected), len(predicted))


def _recall(predicted: set[str], expected: set[str]) -> dict[str, Any]:
    return _metric(len(predicted & expected), len(expected))


def _metric(
    numerator: int,
    denominator: int,
    *,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    value = numerator / denominator if denominator else None
    result: dict[str, Any] = {
        "value": round(value, 4) if value is not None else None,
        "numerator": numerator,
        "denominator": denominator,
    }
    result.update(dict(extra or {}))
    return result


def _string_set(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value.strip()} if value.strip() else set()
    if not isinstance(value, (list, tuple, set)):
        return set()
    return {str(item).strip() for item in value if str(item).strip()}


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return {str(key): item for key, item in value.items()}


def _number(value: float) -> int | float:
    return int(value) if value.is_integer() else round(value, 4)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = run_corpus(args.corpus)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
