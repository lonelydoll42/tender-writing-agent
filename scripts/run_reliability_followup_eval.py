"""Run fixed reliability follow-up cases without exposing their oracle to skills."""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.core.registry import SkillRegistry
from qiaowenshu_agent.core.runtime import AgentRuntime
from qiaowenshu_agent.skills.compliance_review.skill import ComplianceReviewSkill
from qiaowenshu_agent.skills.document_writing import DocumentWritingSkill


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_ROOT = ROOT / "benchmarks" / "reliability_followup"
CASES_PATH = BENCHMARK_ROOT / "cases.json"
ORACLE_PATH = BENCHMARK_ROOT / "oracle.json"
AS_OF = "2026-10-05"
_ORACLE_KEYS = {"expected", "label", "oracle", "must_block", "must_pass"}
class FixtureWritingLLM:
    """Return only fixture model output and retain actual invocation counts."""

    def __init__(self, outputs: Mapping[str, Mapping[str, Any]]) -> None:
        self.outputs = copy.deepcopy(dict(outputs))
        self.calls: list[dict[str, Any]] = []

    async def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        purpose: str,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        user_message = next(
            (
                item.get("content", "")
                for item in reversed(messages)
                if item.get("role") == "user"
            ),
            "",
        )
        try:
            prompt = json.loads(user_message)
        except (TypeError, ValueError):
            prompt = {}
        section = prompt.get("section") or {}
        section_id = str(section.get("section_id") or "")
        response = self.outputs.get(section_id)
        if response is None:
            raise ValueError(f"fixture has no model output for section {section_id!r}")
        self.calls.append({"purpose": purpose, "section_id": section_id})
        return copy.deepcopy(response), SimpleNamespace(usage={"total_tokens": 8})


class CountingDocumentWritingSkill(DocumentWritingSkill):
    def __init__(self, *, llm: FixtureWritingLLM) -> None:
        super().__init__(llm=llm)
        self.invocations = 0

    async def execute(
        self,
        request: SkillRequest,
        context: SkillContext,
    ) -> Any:
        self.invocations += 1
        return await super().execute(request, context)


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return data


def _assert_no_oracle_fields(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        present = _ORACLE_KEYS.intersection(str(key) for key in value)
        if present:
            raise ValueError(
                f"oracle-only field(s) leaked into evaluated input at {path}: "
                f"{sorted(present)}"
            )
        for key, child in value.items():
            _assert_no_oracle_fields(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_oracle_fields(child, path=f"{path}[{index}]")


def _writing_input(fixture: Mapping[str, Any]) -> dict[str, Any]:
    requirement = fixture.get("requirement")
    return {
        "project_id": fixture["project_id"],
        "bidder_profile": copy.deepcopy(fixture.get("bidder_profile") or {}),
        "sections": [copy.deepcopy(fixture["section"])],
        "requirements": [copy.deepcopy(requirement)] if requirement else [],
        "scoring_items": [],
        "materials": copy.deepcopy(fixture.get("materials") or []),
        "evidence_matches": [],
        "as_of": AS_OF,
    }


def _claim_verification(data: Mapping[str, Any]) -> dict[str, Any] | None:
    value = data.get("claim_verification")
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    return None


async def _run_writing_case(
    case_id: str,
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    payload = _writing_input(fixture)
    _assert_no_oracle_fields(payload)
    llm = FixtureWritingLLM(
        {str(fixture["section"]["section_id"]): fixture["model_output"]}
    )
    skill = DocumentWritingSkill(llm=llm)
    result = await skill.execute(
        SkillRequest.create(payload),
        SkillContext(run_id=f"followup-{case_id}", request=SkillRequest.create()),
    )
    data = result.data if isinstance(result.data, Mapping) else {}
    claim_verification = _claim_verification(data)
    unsupported_claim_count = (
        claim_verification.get("unsupported_claim_count")
        if claim_verification
        else None
    )
    return {
        "case_id": case_id,
        "domain": "writing",
        "execution_status": "completed" if result.ok else "failed",
        "skill_status": result.status,
        "business_status": data.get("business_status"),
        "needs_human_review": data.get("needs_human_review"),
        "submission_allowed": data.get("submission_allowed"),
        "model_call_count": len(llm.calls),
        "writer_invocation_count": 1,
        "claims_scanned": (
            claim_verification.get("detected_claim_count")
            if claim_verification
            else None
        ),
        "unsupported_claim_count": unsupported_claim_count,
        "scanner_coverage": _scanner_coverage(data),
        "claim_verification": claim_verification,
        "claim_evidence_mapping": copy.deepcopy(
            data.get("claim_evidence_mapping") or []
        ),
        "verification_findings": copy.deepcopy(
            data.get("verification_findings") or []
        ),
        "error": result.message if not result.ok else None,
    }


def _complete_runtime_input(
    value: Mapping[str, Any],
    *,
    sections: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = copy.deepcopy(dict(value))
    project_id = str(payload.get("project_id") or "")
    versions = payload.pop("source_file_versions", [])
    payload.setdefault("scoring_items", [])
    payload.setdefault("sections", copy.deepcopy(list(sections or [])))
    payload.setdefault("tender_profile", {"project_id": project_id})
    payload.setdefault("bidder_profile", {"bidder_id": "bid-alpha", "name": "甲公司"})
    payload.setdefault("materials", [])
    payload.setdefault("evidence_matches", [])
    payload.setdefault("confirmed_facts", [])
    payload.setdefault("approved_commitments", [])
    payload.setdefault("tender_text", "")
    payload.setdefault("as_of", AS_OF)

    if isinstance(versions, (list, tuple)) and versions:
        requirements = payload.get("requirements")
        if isinstance(requirements, list) and requirements:
            first = requirements[0]
            if isinstance(first, dict):
                references = first.setdefault("source_references", [])
                if isinstance(references, list):
                    references.extend(
                        {
                            "document_id": str(version).rsplit(":v", 1)[0],
                            "file_version": f"v{str(version).rsplit(':v', 1)[1]}",
                        }
                        for version in versions
                    )
    return payload


def _runtime_plan(fixture: Mapping[str, Any]) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    review_input = fixture.get("review_input")
    if isinstance(review_input, Mapping):
        writer_input = fixture["writer_input"]
        completed_review = _complete_runtime_input(
            review_input,
            sections=writer_input.get("sections") or [],
        )
        plan.append(
            {
                "skill_name": "compliance-review",
                "input": completed_review,
            }
        )
    completed_writer = _complete_runtime_input(fixture["writer_input"])
    plan.append(
        {
            "skill_name": "document-writing",
            "input": completed_writer,
        }
    )
    return plan


async def _run_runtime_case(
    case_id: str,
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    request_data: dict[str, Any] = {
        "project_id": fixture["run_project_id"],
        "plan": _runtime_plan(fixture),
    }
    request_data.update(copy.deepcopy(fixture.get("forged_request_fields") or {}))
    _assert_no_oracle_fields(request_data)

    llm = FixtureWritingLLM(fixture["model_outputs"])
    writer = CountingDocumentWritingSkill(llm=llm)
    registry = SkillRegistry()
    registry.register(ComplianceReviewSkill())
    registry.register(writer)
    runtime = AgentRuntime(registry)
    result = await runtime.run(SkillRequest.create(request_data))

    review_data: Mapping[str, Any] = {}
    writer_data: Mapping[str, Any] = {}
    for step in result.steps:
        data = step.result.data if isinstance(step.result.data, Mapping) else {}
        if step.skill_name == "compliance-review":
            review_data = data
        elif step.skill_name == "document-writing":
            writer_data = data

    decision = writer_data.get("scope_binding_decision")
    decision = decision if isinstance(decision, Mapping) else {}
    raw_reasons = decision.get("reasons")
    reasons = (
        [
            copy.deepcopy(dict(item))
            for item in raw_reasons
            if isinstance(item, Mapping) and str(item.get("code") or "").strip()
        ]
        if isinstance(raw_reasons, list)
        else []
    )
    review_binding = review_data.get("runtime_scope_binding")
    review_binding = review_binding if isinstance(review_binding, Mapping) else {}
    authorization = writer_data.get("runtime_scope_authorization")
    authorization = authorization if isinstance(authorization, Mapping) else {}
    return {
        "case_id": case_id,
        "domain": "runtime",
        "execution_status": result.execution_status,
        "run_status": result.status,
        "business_status": result.business_status,
        "scoped_gate_passed": result.scoped_gate_passed,
        "scope_authorization_status": authorization.get("status"),
        "writer_invocation_count": writer.invocations,
        "model_call_count": len(llm.calls),
        "review_business_status": review_data.get("business_status"),
        "review_scope_binding_status": review_binding.get("status"),
        "scope_match_kind": authorization.get("match_kind"),
        "scope_binding_decision": copy.deepcopy(dict(decision)),
        "scope_rejection_reasons": reasons,
        "error": result.message,
    }


def _scanner_coverage(data: Mapping[str, Any]) -> dict[str, Any]:
    claim_verification = _claim_verification(data)
    coverage_value = claim_verification.get("coverage") if claim_verification else None
    coverage = (
        copy.deepcopy(dict(coverage_value))
        if isinstance(coverage_value, Mapping)
        else None
    )
    raw_status = coverage.get("status") if coverage else None
    return {
        "status": str(raw_status or "not_reported"),
        "coverage": coverage,
        "claim_verification_status": (
            str(claim_verification.get("status") or "not_reported")
            if claim_verification
            else "not_reported"
        ),
        "claim_verification_reported": claim_verification is not None,
        "scanned_claim_count": (
            claim_verification.get("detected_claim_count")
            if claim_verification
            else None
        ),
        "unsupported_claim_count": (
            claim_verification.get("unsupported_claim_count")
            if claim_verification
            else None
        ),
    }


async def _run_observations(
    manifest: Mapping[str, Any],
    writing_fixtures: Mapping[str, Any],
    runtime_fixtures: Mapping[str, Any],
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for case in manifest["cases"]:
        fixture_set = (
            writing_fixtures
            if case["domain"] == "writing"
            else runtime_fixtures
        )
        fixture = fixture_set["cases"][case["fixture_key"]]
        try:
            if case["domain"] == "writing":
                row = await _run_writing_case(case["case_id"], fixture)
            else:
                row = await _run_runtime_case(case["case_id"], fixture)
        except Exception as exc:
            row = {
                "case_id": case["case_id"],
                "domain": case["domain"],
                "execution_status": "not_run",
                "model_call_count": 0,
                "writer_invocation_count": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }
        observations.append(row)
    return observations


def _case_evaluation(
    observation: Mapping[str, Any],
    oracle: Mapping[str, Any],
) -> str:
    if observation.get("execution_status") == "not_run":
        return "not_run"
    domain = oracle["domain"]
    positive = oracle["label"] == "positive"
    if domain == "writing":
        status = observation.get("business_status")
        if oracle.get("must_scan_claim") is True:
            scanner_coverage = observation.get("scanner_coverage")
            scanner_coverage = (
                scanner_coverage if isinstance(scanner_coverage, Mapping) else {}
            )
            coverage = scanner_coverage.get("coverage")
            coverage = coverage if isinstance(coverage, Mapping) else {}
            coverage_complete = (
                scanner_coverage.get("claim_verification_reported") is True
                and coverage.get("status") == "complete"
                and isinstance(coverage.get("scanned_sentence_count"), int)
                and coverage["scanned_sentence_count"] > 0
                and isinstance(coverage.get("recognized_claim_count"), int)
                and coverage["recognized_claim_count"] > 0
                and coverage.get("unclassified_high_risk_claim_count") == 0
            )
            if not coverage_complete:
                if status == "passed":
                    return "inconclusive" if positive else "false_release"
                return "false_block" if positive else "inconclusive"
        if status == "passed":
            return "correct_pass" if positive else "false_release"
        if status in {"failed", "needs_review", "not_checked"}:
            return "false_block" if positive else "correct_block"
        return "inconclusive"

    writer_calls = observation.get("writer_invocation_count")
    model_calls = observation.get("model_call_count")
    business_status = observation.get("business_status")
    execution_status = observation.get("execution_status")
    reasons = observation.get("scope_rejection_reasons") or []
    if positive:
        authorized_match = (
            observation.get("review_scope_binding_status") == "bound"
            and observation.get("review_business_status") == "passed"
            and observation.get("scope_authorization_status") == "authorized"
            and observation.get("scope_match_kind")
            == oracle.get("expected_match_kind")
        )
        if (
            writer_calls == 1
            and model_calls == 1
            and business_status == "passed"
            and execution_status == "completed"
            and authorized_match
        ):
            return "correct_pass"
        if (
            writer_calls != 1
            or model_calls != 1
            or business_status in {"failed", "needs_review", "not_checked"}
            or execution_status in {"blocked", "failed"}
        ):
            return "false_block"
        return "inconclusive"
    if isinstance(writer_calls, int) and writer_calls > 0:
        return "false_release"
    if writer_calls == 0 and (
        execution_status == "blocked"
        or business_status in {"failed", "needs_review", "not_checked"}
        or reasons
    ):
        return "correct_block"
    return "inconclusive"


def _rate(count: int, denominator: int) -> dict[str, Any]:
    return {
        "count": count,
        "denominator": denominator,
        "rate": count / denominator if denominator else None,
    }


def _domain_metrics(
    domain: str,
    observations: Sequence[Mapping[str, Any]],
    oracle_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    relevant = [row for row in oracle_rows if row["domain"] == domain]
    oracle_by_id = {str(row["case_id"]): row for row in relevant}
    evaluated: list[dict[str, Any]] = []
    for observation in observations:
        if observation["domain"] != domain:
            continue
        oracle = oracle_by_id[str(observation["case_id"])]
        evaluated.append(
            {
                **copy.deepcopy(dict(observation)),
                "label": oracle["label"],
                "expected": oracle["expected"],
                "oracle_assertions": {
                    key: copy.deepcopy(value)
                    for key, value in oracle.items()
                    if key not in {"case_id", "domain", "label", "expected"}
                },
                "evaluation": _case_evaluation(observation, oracle),
            }
        )

    positives = [row for row in relevant if row["label"] == "positive"]
    negatives = [row for row in relevant if row["label"] == "negative"]
    correct_pass = sum(item["evaluation"] == "correct_pass" for item in evaluated)
    false_block = sum(item["evaluation"] == "false_block" for item in evaluated)
    false_release = sum(item["evaluation"] == "false_release" for item in evaluated)
    correct_block = sum(item["evaluation"] == "correct_block" for item in evaluated)
    not_run = sum(item["evaluation"] == "not_run" for item in evaluated)
    inconclusive = sum(item["evaluation"] == "inconclusive" for item in evaluated)
    scope_reasons = [
        {
            "case_id": item["case_id"],
            "reasons": item.get("scope_rejection_reasons") or [],
        }
        for item in evaluated
        if domain == "runtime" and item["label"] == "negative"
    ]
    scanner_cases = [
        {
            "case_id": item["case_id"],
            **copy.deepcopy(item.get("scanner_coverage") or {}),
        }
        for item in evaluated
        if domain == "writing"
    ]
    return {
        "case_count": len(relevant),
        "positive_denominator": len(positives),
        "negative_denominator": len(negatives),
        "run_count": len(evaluated) - not_run,
        "not_run_count": not_run,
        "inconclusive_count": inconclusive,
        "correct_pass_count": correct_pass,
        "correct_pass_rate": _rate(correct_pass, len(positives)),
        "false_block_count": false_block,
        "false_block_rate": _rate(false_block, len(positives)),
        "correct_block_count": correct_block,
        "false_release_count": false_release,
        "false_release_rate": _rate(false_release, len(negatives)),
        "model_call_count": sum(
            int(item.get("model_call_count") or 0) for item in evaluated
        ),
        "writer_invocation_count": sum(
            int(item.get("writer_invocation_count") or 0) for item in evaluated
        ),
        "scope_rejection_reasons": scope_reasons,
        "scanner_coverage": scanner_cases,
        "cases": evaluated,
        "rate_denominator_note": (
            "Rates use all fixed oracle cases of that polarity, including not_run "
            "and inconclusive cases in the denominator; those outcomes are also "
            "reported separately."
        ),
    }


def run_reliability_followup_eval() -> dict[str, Any]:
    manifest = _load_json(CASES_PATH)
    writing_fixture_path = BENCHMARK_ROOT / manifest["writing_fixture"]
    runtime_fixture_path = BENCHMARK_ROOT / manifest["runtime_fixture"]
    writing_fixtures = _load_json(writing_fixture_path)
    runtime_fixtures = _load_json(runtime_fixture_path)

    observations = asyncio.run(
        _run_observations(manifest, writing_fixtures, runtime_fixtures)
    )

    # Load expected labels only after every test input and mock model output ran.
    oracle = _load_json(ORACLE_PATH)
    oracle_rows = oracle["cases"]
    expected_ids = {str(item["case_id"]) for item in manifest["cases"]}
    oracle_ids = {str(item["case_id"]) for item in oracle_rows}
    if expected_ids != oracle_ids:
        raise ValueError(
            "case/oracle ID mismatch: "
            f"missing oracle={sorted(expected_ids - oracle_ids)}, "
            f"orphan oracle={sorted(oracle_ids - expected_ids)}"
        )
    if len(oracle_ids) != len(oracle_rows):
        raise ValueError("oracle contains duplicate case IDs")

    now = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    return {
        "schema_version": 1,
        "benchmark": "reliability_followup",
        "generated_at": now,
        "timezone": "Asia/Shanghai",
        "input_policy": {
            "oracle_loaded_after_runtime": True,
            "oracle_registered_or_injected_as_input": False,
            "fixtures_contain_expected_labels": False,
            "mock_model_returns_only_fixture_output": True,
            "real_model_called": False,
            "real_ocr_called": False,
        },
        "raw_file_baseline": {
            "status": "not_retested_in_this_followup",
            "constraint_text_coverage": {"matched": 4, "denominator": 10},
            "known_omissions": 6,
            "production_extraction_complete": False,
            "note": (
                "保留前次独立原始文件评测的4/10结果；本轮不修复、重跑或改写"
                "剩余6项遗漏，也不将本组模拟服务反例称为生产准确率。"
            ),
        },
        "metrics": {
            "writing": _domain_metrics("writing", observations, oracle_rows),
            "runtime": _domain_metrics("runtime", observations, oracle_rows),
        },
        "limitations": [
            "模拟LLM只用于复现服务边界行为，不测量真实模型准确率。",
            "固定用例只覆盖列出的认证标准、主体归属、案例数量和运行范围反例。",
            "扫描覆盖状态是当前实现的可观测结果；未扫描或状态未报告不得解释为事实通过。",
            "原始文件约束文本覆盖仍为4/10，6项遗漏未在本轮整改。",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="write the report to this new path; existing files are never overwritten",
    )
    args = parser.parse_args(argv)
    try:
        report = run_reliability_followup_eval()
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output is None:
            sys.stdout.write(rendered)
            return 0
        output = args.output
        if output.exists():
            parser.error(f"refusing to overwrite existing report: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(output)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
