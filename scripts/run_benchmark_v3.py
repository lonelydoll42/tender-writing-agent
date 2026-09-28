"""Run the holdout-oriented Benchmark V3 challenge corpus.

The corpus and answer key are loaded separately.  Only the business input is
passed to Skills; expected statuses are consulted after execution for scoring.
"""

from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.skills.bid_feasibility import BidFeasibilitySkill
from qiaowenshu_agent.skills.evidence_matching import EvidenceMatchingSkill


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "benchmarks" / "challenge" / "tender_v3_cases.json"
DEFAULT_ANSWERS = ROOT / "benchmarks" / "challenge" / "tender_v3_answers.json"


async def evaluate_corpus(
    corpus: Mapping[str, Any],
    answers: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    answer_map = _answers_by_id(answers or {})
    cases: list[dict[str, Any]] = []
    for raw_case in corpus.get("cases") or []:
        case = _mapping(raw_case, "case")
        case_id = str(case.get("id") or "").strip()
        expected = _mapping(answer_map.get(case_id, {}).get("expected"), "expected")
        observed = await _evaluate_input(_mapping(case.get("input"), "input"))
        mutations = await _evaluate_mutations(
            case,
            observed,
            _mapping(answer_map.get(case_id), "case answer"),
        )
        variants = await _evaluate_variants(
            case,
            _mapping(answer_map.get(case_id), "case answer"),
        )
        cases.append(
            {
                "case_id": case_id,
                "kind": str(case.get("kind") or "evidence_and_feasibility"),
                "observed": observed,
                "metrics": _case_metrics(expected, observed),
                "mutations": mutations,
                "variants": variants,
            }
        )

    return {
        "protocol_version": str(corpus.get("protocol_version") or "3.0"),
        "benchmark_name": str(corpus.get("benchmark_name") or "benchmark-v3"),
        "evaluation_mode": str(corpus.get("evaluation_mode") or "holdout"),
        "case_count": len(cases),
        "cases": cases,
        "metrics": _aggregate_metrics(cases),
        "mutation_summary": _mutation_summary(cases),
        "variant_summary": _variant_summary(cases),
    }


def run_corpus(
    corpus_path: str | Path = DEFAULT_CORPUS,
    answers_path: str | Path | None = DEFAULT_ANSWERS,
) -> dict[str, Any]:
    corpus = json.loads(Path(corpus_path).read_text(encoding="utf-8"))
    answers = (
        json.loads(Path(answers_path).read_text(encoding="utf-8"))
        if answers_path is not None
        else {}
    )
    return asyncio.run(evaluate_corpus(corpus, answers))


async def _evaluate_input(data: Mapping[str, Any]) -> dict[str, Any]:
    requirements = list(data.get("requirements") or [])
    materials = list(data.get("materials") or [])
    evidence_payload = {
        "project_id": str(data.get("project_id") or "benchmark-v3"),
        "requirements": requirements,
        "scoring_items": list(data.get("scoring_items") or []),
        "materials": materials,
        "as_of": data.get("as_of"),
    }
    evidence_request = SkillRequest.create(
        evidence_payload,
        skill_name="evidence-matching",
    )
    evidence_result = await EvidenceMatchingSkill().execute(
        evidence_request,
        SkillContext(run_id="benchmark-v3-evidence", request=evidence_request),
    )
    if evidence_result.status != "success":
        raise RuntimeError(evidence_result.message or "evidence matching failed")

    bidder = deepcopy(data.get("bidder_profile") or {})
    if not isinstance(bidder, Mapping):
        raise ValueError("input.bidder_profile must be an object")
    bidder = dict(bidder)
    bidder.setdefault("bidder_id", str(data.get("bidder_id") or "benchmark-bidder"))
    if "attributes" not in bidder and data.get("bidder_attributes") is not None:
        bidder["attributes"] = data.get("bidder_attributes")
    if materials:
        bidder["materials"] = materials
    else:
        materials = list(bidder.get("materials") or [])
    feasibility_payload = {
        "project_id": str(data.get("project_id") or "benchmark-v3"),
        "requirements": requirements,
        "bidder_profile": bidder,
        "options": {"as_of": data.get("as_of")},
    }
    feasibility_request = SkillRequest.create(
        feasibility_payload,
        skill_name="bid-feasibility",
    )
    feasibility_result = await BidFeasibilitySkill().execute(
        feasibility_request,
        SkillContext(run_id="benchmark-v3-feasibility", request=feasibility_request),
    )
    if feasibility_result.status != "success":
        raise RuntimeError(feasibility_result.message or "bid feasibility failed")

    evidence_data = evidence_result.data
    feasibility_data = feasibility_result.data
    return {
        "decision": str(feasibility_data.get("decision") or ""),
        "evidence_statuses": _status_map(evidence_data.get("matches")),
        "feasibility_statuses": _status_map(feasibility_data.get("checks")),
        "evidence_matches": list(evidence_data.get("matches") or []),
        "feasibility_checks": list(feasibility_data.get("checks") or []),
    }


async def _evaluate_mutations(
    case: Mapping[str, Any],
    original: Mapping[str, Any],
    answer: Mapping[str, Any],
) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    expected_mutations = _mapping(answer.get("mutations"), "mutations")
    base_input = _mapping(case.get("input"), "input")
    for raw_mutation in case.get("mutations") or []:
        mutation = _mapping(raw_mutation, "mutation")
        mutation_id = str(mutation.get("id") or "").strip()
        overrides = _mapping(mutation.get("input_overrides"), "input_overrides")
        mutated_input = _deep_merge(base_input, overrides)
        observed = await _evaluate_input(mutated_input)
        actual_delta = _actual_delta(original, observed)
        expected = _mapping(expected_mutations.get(mutation_id), "mutation answer")
        expected_delta = _mapping(expected.get("expected_delta"), "expected_delta")
        reports.append(
            {
                "mutation_id": mutation_id,
                "observed": observed,
                "expected_delta": expected_delta,
                "actual_delta": actual_delta,
                "passed": _delta_matches(expected_delta, actual_delta),
            }
        )
    return reports


async def _evaluate_variants(
    case: Mapping[str, Any],
    answer: Mapping[str, Any],
) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    expected_variants = _mapping(answer.get("variants"), "variants")
    for raw_variant in case.get("variants") or []:
        variant = _mapping(raw_variant, "variant")
        variant_id = str(variant.get("id") or "").strip()
        observed = await _evaluate_input(
            _mapping(variant.get("input"), "variant.input")
        )
        expected = _mapping(expected_variants.get(variant_id), "variant answer")
        reports.append(
            {
                "variant_id": variant_id,
                "observed": observed,
                "passed": _variant_matches(expected, observed),
            }
        )
    return reports


def _case_metrics(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> dict[str, Any]:
    evidence_expected = _mapping(expected.get("evidence_statuses"), "evidence_statuses")
    feasibility_expected = _mapping(
        expected.get("feasibility_statuses"),
        "feasibility_statuses",
    )
    evidence_statuses = _mapping(
        observed.get("evidence_statuses"),
        "observed.evidence_statuses",
    )
    feasibility_statuses = _mapping(
        observed.get("feasibility_statuses"),
        "observed.feasibility_statuses",
    )
    metrics = {
        "decision_accuracy": _metric(
            int(
                not expected.get("decision")
                or str(observed.get("decision")) == str(expected.get("decision"))
            ),
            1 if expected.get("decision") else 0,
        ),
        "evidence_status_accuracy": _mapping_accuracy(
            evidence_statuses,
            evidence_expected,
        ),
        "feasibility_status_accuracy": _mapping_accuracy(
            feasibility_statuses,
            feasibility_expected,
        ),
        "evidence_recall": _set_recall(
            _matching_ids(evidence_statuses),
            _string_set(expected.get("evidence_matched_ids")),
        ),
        "critical_false_pass": _false_pass_metric(
            feasibility_statuses,
            _string_set(expected.get("critical_requirement_ids")),
        ),
        "hard_negative_false_pass": _false_pass_metric(
            feasibility_statuses,
            _string_set(expected.get("non_pass_requirement_ids")),
        ),
        "conflict_recall": _set_recall(
            {
                identifier
                for identifier, status in evidence_statuses.items()
                if str(status) == "conflict"
            },
            _string_set(expected.get("conflict_ids")),
        ),
        "ocr_human_review_precision": _ocr_precision(
            evidence_statuses,
            expected,
        ),
        "ocr_human_review_recall": _ocr_recall(
            evidence_statuses,
            expected,
        ),
        "ocr_critical_false_pass": _false_pass_metric(
            feasibility_statuses,
            _string_set(expected.get("human_review_targets")),
        ),
    }
    return metrics


def _aggregate_metrics(cases: list[Mapping[str, Any]]) -> dict[str, Any]:
    names = (
        "decision_accuracy",
        "evidence_status_accuracy",
        "feasibility_status_accuracy",
        "evidence_recall",
        "critical_false_pass",
        "hard_negative_false_pass",
        "conflict_recall",
        "ocr_human_review_precision",
        "ocr_human_review_recall",
        "ocr_critical_false_pass",
    )
    result: dict[str, Any] = {}
    for name in names:
        values = [
            _mapping(case.get("metrics"), "case.metrics")[name]
            for case in cases
            if _mapping(case.get("metrics"), "case.metrics")[name]["value"]
            is not None
        ]
        numerator = sum(float(item.get("numerator", 0)) for item in values)
        denominator = sum(float(item.get("denominator", 0)) for item in values)
        result[name] = {
            "value": round(numerator / denominator, 4) if denominator else None,
            "numerator": _number(numerator),
            "denominator": _number(denominator),
            "case_count": len(values),
        }
    return result


def _mutation_summary(cases: list[Mapping[str, Any]]) -> dict[str, Any]:
    reports = [
        mutation
        for case in cases
        for mutation in case.get("mutations") or []
    ]
    passed = sum(1 for item in reports if item.get("passed"))
    return {
        "total": len(reports),
        "passed": passed,
        "value": passed / len(reports) if reports else None,
    }


def _variant_summary(cases: list[Mapping[str, Any]]) -> dict[str, Any]:
    reports = [
        variant
        for case in cases
        for variant in case.get("variants") or []
    ]
    passed = sum(1 for item in reports if item.get("passed"))
    return {
        "total": len(reports),
        "passed": passed,
        "value": passed / len(reports) if reports else None,
    }


def _mapping_accuracy(
    observed: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> dict[str, Any]:
    if not expected:
        return _metric(0, 0)
    correct = sum(
        1
        for identifier, status in expected.items()
        if str(observed.get(identifier)) == str(status)
    )
    return _metric(correct, len(expected))


def _ocr_precision(
    observed: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> dict[str, Any]:
    targets = _string_set(expected.get("ocr_targets"))
    expected_review = _string_set(expected.get("human_review_targets"))
    predicted = {
        identifier
        for identifier, status in observed.items()
        if str(status) == "human_review" and identifier in targets
    }
    return _metric(len(predicted & expected_review), len(predicted))


def _ocr_recall(
    observed: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> dict[str, Any]:
    expected_review = _string_set(expected.get("human_review_targets"))
    predicted = {
        identifier
        for identifier, status in observed.items()
        if str(status) == "human_review"
    }
    return _metric(len(predicted & expected_review), len(expected_review))


def _false_pass_metric(
    statuses: Mapping[str, Any],
    identifiers: set[str],
) -> dict[str, Any]:
    false_pass_ids = sorted(
        identifier
        for identifier in identifiers
        if str(statuses.get(identifier)) == "pass"
    )
    return {
        "value": len(false_pass_ids),
        "numerator": len(false_pass_ids),
        "denominator": len(identifiers),
        "false_pass_ids": false_pass_ids,
    }


def _set_recall(predicted: set[str], expected: set[str]) -> dict[str, Any]:
    return _metric(len(predicted & expected), len(expected))


def _matching_ids(statuses: Mapping[str, Any]) -> set[str]:
    return {
        identifier
        for identifier, status in statuses.items()
        if status == "matched"
    }


def _metric(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "value": round(numerator / denominator, 4) if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
    }


def _actual_delta(
    original: Mapping[str, Any],
    mutation: Mapping[str, Any],
) -> dict[str, Any]:
    identifiers = set(original.get("feasibility_statuses", {})) | set(
        mutation.get("feasibility_statuses", {})
    )
    status_changes = {
        identifier: {
            "from": original.get("feasibility_statuses", {}).get(identifier),
            "to": mutation.get("feasibility_statuses", {}).get(identifier),
        }
        for identifier in sorted(identifiers)
        if original.get("feasibility_statuses", {}).get(identifier)
        != mutation.get("feasibility_statuses", {}).get(identifier)
    }
    return {
        "decision_from": original.get("decision"),
        "decision_to": mutation.get("decision"),
        "decision_changed": original.get("decision") != mutation.get("decision"),
        "status_changes": status_changes,
    }


def _delta_matches(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> bool:
    if not expected:
        return True
    if (
        expected.get("decision_changed_to") is not None
        and actual.get("decision_to") != expected.get("decision_changed_to")
    ):
        return False
    if (
        expected.get("decision_changed") is not None
        and actual.get("decision_changed") != expected.get("decision_changed")
    ):
        return False
    expected_changes = expected.get("status_changes") or {}
    actual_changes = actual.get("status_changes") or {}
    for identifier, expected_value in expected_changes.items():
        actual_value = actual_changes.get(identifier)
        if isinstance(expected_value, Mapping):
            if not isinstance(actual_value, Mapping):
                return False
            for key, value in expected_value.items():
                if actual_value.get(key) != value:
                    return False
        elif not actual_value or actual_value.get("to") != expected_value:
            return False
    return True


def _variant_matches(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> bool:
    if (
        expected.get("decision")
        and observed.get("decision") != expected.get("decision")
    ):
        return False
    for key in ("evidence_statuses", "feasibility_statuses"):
        expected_statuses = _mapping(expected.get(key), key)
        observed_statuses = _mapping(observed.get(key), f"observed.{key}")
        if any(
            str(observed_statuses.get(identifier)) != str(status)
            for identifier, status in expected_statuses.items()
        ):
            return False
    return True


def _deep_merge(
    base: Mapping[str, Any],
    overrides: Mapping[str, Any],
) -> dict[str, Any]:
    result = deepcopy(dict(base))
    for key, value in overrides.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _status_map(items: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items or []:
        if not isinstance(item, Mapping):
            continue
        identifier = str(
            item.get("requirement_id") or item.get("item_id") or ""
        ).strip()
        if identifier:
            result[identifier] = str(item.get("status") or "")
    return result


def _answers_by_id(answers: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(item.get("id") or "").strip(): _mapping(item, "answer")
        for item in answers.get("cases") or []
        if isinstance(item, Mapping) and str(item.get("id") or "").strip()
    }


def _string_set(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value.strip()} if value.strip() else set()
    if not isinstance(value, (list, tuple, set)):
        return set()
    return {str(item).strip() for item in value if str(item).strip()}


def _number(value: float) -> int | float:
    numeric = float(value)
    return int(numeric) if numeric.is_integer() else round(numeric, 4)


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return {str(key): item for key, item in value.items()}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--answers", type=Path, default=DEFAULT_ANSWERS)
    parser.add_argument(
        "--blind",
        action="store_true",
        help="run the challenge input without loading its answer key",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = run_corpus(args.corpus, None if args.blind else args.answers)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
