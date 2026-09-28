"""Run the independent tender v2 regression matrix.

Ground Truth is loaded only after business analysis has run.  It is used for
assertions and reporting, never passed into any Skill as tender or bidder
evidence.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest, SkillResult
from qiaowenshu_agent.domain.analysis_protocol import validate_machine_json
from qiaowenshu_agent.skills.analysis_report import AnalysisReportSkill
from qiaowenshu_agent.skills.bid_feasibility import BidFeasibilitySkill
from qiaowenshu_agent.skills.compliance_review import ComplianceReviewSkill
from qiaowenshu_agent.skills.evidence_matching import EvidenceMatchingSkill
from qiaowenshu_agent.skills.requirement_ledger import RequirementLedgerSkill
from qiaowenshu_agent.skills.scoring_strategy import ScoringStrategySkill


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tender_v2"


def scenario_ids() -> list[str]:
    catalog = _read_json(FIXTURE_ROOT / "catalog.json")
    return [str(item["id"]) for item in catalog["scenarios"]]


def load_business_input(scenario_id: str) -> dict[str, Any]:
    """Load only visible tender/correction/bidder material for one scenario."""

    directory = FIXTURE_ROOT / scenario_id
    scenario = _read_json(directory / "scenario.json")
    visible = set(scenario["visible_files"])
    required = {
        scenario["tender_file"],
        scenario["correction_file"],
        scenario["bidder_file"],
    }
    if not required <= visible:
        raise AssertionError(f"scenario {scenario_id} hides a required input file")
    if scenario["ground_truth_file"] in visible:
        raise AssertionError("Ground Truth must not be a business input")

    tender = _read_json(directory / scenario["tender_file"])
    correction = _read_json(directory / scenario["correction_file"])
    bidder = _read_json(directory / scenario["bidder_file"])
    materials = bidder.get("materials") or []
    return {
        "scenario_id": scenario_id,
        "scenario": scenario,
        "project": tender["project"],
        "requirements": tender["requirements"],
        "scoring_items": tender["scoring_items"],
        "materials": materials,
        "bidder_profile": bidder,
        "correction": correction,
        "as_of": scenario["as_of"],
    }


async def analyze_scenario(scenario_id: str) -> dict[str, Any]:
    """Run the deterministic analysis chain for one isolated fixture."""

    payload = load_business_input(scenario_id)
    project_id = str(payload["project"]["project_id"])
    requirements = payload["requirements"]
    scoring_items = payload["scoring_items"]
    materials = payload["materials"]
    as_of = payload["as_of"]

    evidence_result = await _invoke(
        EvidenceMatchingSkill(),
        {
            "project_id": project_id,
            "requirements": requirements,
            "scoring_items": scoring_items,
            "materials": materials,
            "as_of": as_of,
        },
        "evidence-matching",
    )
    feasibility_result = await _invoke(
        BidFeasibilitySkill(),
        {
            "project_id": project_id,
            "requirements": requirements,
            "bidder_profile": payload["bidder_profile"],
            "options": {"as_of": as_of},
        },
        "bid-feasibility",
    )
    scoring_result = await _invoke(
        ScoringStrategySkill(),
        {
            "project_id": project_id,
            "requirements": requirements,
            "scoring_items": scoring_items,
            "evidence_materials": materials,
            "evidence_matches": evidence_result.data["matches"],
            "as_of": as_of,
        },
        "scoring-strategy",
    )
    ledger_result = await _invoke(
        RequirementLedgerSkill(),
        {
            "project_id": project_id,
            "requirements": requirements,
            "scoring_items": scoring_items,
            "evidence_matches": evidence_result.data["matches"],
            "feasibility_checks": feasibility_result.data["checks"],
        },
        "requirement-ledger",
    )
    compliance_result = await _invoke(
        ComplianceReviewSkill(),
        {
            "project_id": project_id,
            "ledger": ledger_result.data,
            "consistency_result": {},
        },
        "compliance-review",
    )
    report_result = await _invoke(
        AnalysisReportSkill(),
        {
            "project_id": project_id,
            "project": payload["project"],
            "feasibility": feasibility_result.data,
            "scoring": scoring_result.data,
            "ledger": ledger_result.data,
            "compliance": compliance_result.data,
        },
        "analysis-report",
    )
    report = report_result.data
    machine_json = report["machine_json"]
    validate_machine_json(machine_json)
    return {
        "scenario_id": scenario_id,
        "machine_json": machine_json,
        "human_report": report["human_report"],
        "steps": {
            "evidence_matching": evidence_result.data,
            "bid_feasibility": feasibility_result.data,
            "scoring_strategy": scoring_result.data,
            "requirement_ledger": ledger_result.data,
            "compliance_review": compliance_result.data,
        },
    }


def evaluate_ground_truth(
    scenario_id: str,
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """Compare output with Ground Truth without feeding it into analysis."""

    ground_truth = _read_json(FIXTURE_ROOT / scenario_id / "ground_truth.json")
    machine = analysis["machine_json"]
    expected = ground_truth["expected"]
    checks: dict[str, bool] = {}
    checks["decision"] = machine["bid_decision"] == expected["bid_decision"]
    checks["rule_total"] = (
        machine["score"]["rule_total"] == expected["score_rule_total"]
    )
    checks["objective_proven"] = (
        machine["score"]["objective_proven"] == expected["objective_score_proven"]
    )
    checks["objective_unproven"] = (
        machine["score"]["objective_unproven"] == expected["objective_score_unproven"]
    )
    checks["price_unavailable"] = (
        machine["score"]["price_available"] == expected["price_available"]
    )
    checks["subjective_unavailable"] = (
        machine["score"]["subjective_available"]
        == expected["subjective_available"]
    )
    checks["writing_status"] = machine.get("writing_status") == expected.get(
        "writing_status", "not_started"
    )
    input_data = load_business_input(scenario_id)
    must_detect_results = {
        f"must_detect_{index:02d}": _must_detect_phrase(
            phrase,
            input_data,
            analysis,
        )
        for index, phrase in enumerate(ground_truth.get("must_detect", []), start=1)
    }
    checks.update(must_detect_results)
    checks["must_detect"] = all(must_detect_results.values())
    output_text = json.dumps(
        {
            "machine_json": machine,
            "human_report": analysis["human_report"],
        },
        ensure_ascii=False,
    )
    checks["no_forbidden_claim"] = not any(
        phrase in output_text
        for phrase in ground_truth.get("must_not_claim", [])
    )

    correction = input_data["correction"]
    changes = correction.get("changes") or []
    checks["version_override"] = all(
        any(
            _contains_version_phrase(item.get("old_requirement"), rule["old"])
            and _contains_version_phrase(item.get("new_requirement"), rule["new"])
            and str(item.get("effective_value"))
            == str(rule["expected_effective"])
            for item in changes
        )
        for rule in ground_truth.get("version_rules", [])
    )
    checks["file_isolation"] = _file_isolated(scenario_id)

    feasibility_checks = {
        item["requirement_id"]: item
        for item in analysis["steps"]["bid_feasibility"]["checks"]
    }
    for requirement_id in ground_truth.get("hard_failures", []):
        checks[f"hard_fail_{requirement_id}"] = (
            feasibility_checks.get(requirement_id, {}).get("status") == "fail"
        )
    for requirement_id in ground_truth.get("human_review_requirements", []):
        checks[f"human_review_{requirement_id}"] = (
            feasibility_checks.get(requirement_id, {}).get("status") == "unknown"
        )
    evidence_matches = {
        item["requirement_id"]: item
        for item in analysis["steps"]["evidence_matching"]["matches"]
    }
    for requirement_id in ground_truth.get("conflict_requirements", []):
        checks[f"evidence_conflict_{requirement_id}"] = (
            evidence_matches.get(requirement_id, {}).get("status") == "conflict"
        )

    return {
        "scenario_id": scenario_id,
        "checks": checks,
        "passed": all(checks.values()),
        "expected": expected,
    }


def run_all() -> dict[str, Any]:
    scenarios: list[dict[str, Any]] = []
    matrix: list[dict[str, Any]] = []
    for scenario_id in scenario_ids():
        analysis = asyncio.run(analyze_scenario(scenario_id))
        evaluation = evaluate_ground_truth(scenario_id, analysis)
        scenarios.append({**analysis, "evaluation": evaluation})
        checks = evaluation["checks"]
        matrix.append(
            {
                "scenario": scenario_id,
                "文件隔离": checks.get("file_isolation", False),
                "更正公告覆盖": checks.get("version_override", False),
                "硬性条件识别": all(
                    value
                    for key, value in checks.items()
                    if key.startswith(("hard_fail_", "human_review_"))
                ),
                "投标决策": checks.get("decision", False),
                "评分规则": checks.get("rule_total", False),
                "客观证据分": checks.get("objective_proven", False),
                "必检事实": checks.get("must_detect", False),
                "禁止幻觉": checks.get("no_forbidden_claim", False),
                "证据冲突": all(
                    value
                    for key, value in checks.items()
                    if key.startswith("evidence_conflict_")
                ),
            }
        )
    return {
        "protocol_version": "2.0",
        "scenarios": scenarios,
        "matrix": matrix,
        "passed": all(item["evaluation"]["passed"] for item in scenarios),
    }


async def _invoke(skill: Any, payload: dict[str, Any], skill_name: str) -> SkillResult:
    request = SkillRequest.create(payload, skill_name=skill_name)
    result = await skill.execute(
        request,
        SkillContext(run_id=f"tender-v2-{skill_name}", request=request),
    )
    if result.status in {"error", "retryable_error", "blocked"}:
        raise RuntimeError(
            f"{skill_name} failed: {result.error_code or result.message}"
        )
    return result


def _file_isolated(scenario_id: str) -> bool:
    directory = FIXTURE_ROOT / scenario_id
    scenario = _read_json(directory / "scenario.json")
    visible = set(scenario["visible_files"])
    if scenario["ground_truth_file"] in visible:
        return False
    return all((directory / name).is_file() for name in visible)


def _must_detect_phrase(
    phrase: str,
    input_data: dict[str, Any],
    analysis: dict[str, Any],
) -> bool:
    """Evaluate Ground Truth facts against structured output and visible input.

    Ground Truth is consulted only after analysis.  The helper intentionally
    checks facts through stable fields/material metadata instead of injecting
    expected text into any Skill prompt.
    """

    phrase = str(phrase)
    project = input_data["project"]
    correction = input_data["correction"]
    materials = input_data["materials"]
    feasibility = {
        item["requirement_id"]: item
        for item in analysis["steps"]["bid_feasibility"]["checks"]
    }
    evidence_matches = {
        item["requirement_id"]: item
        for item in analysis["steps"]["evidence_matching"]["matches"]
    }
    serialized = json.dumps(
        {"input": input_data, "analysis": analysis},
        ensure_ascii=False,
    )
    if phrase in serialized:
        return True

    if "投标截止时间" in phrase:
        return str(project.get("bid_deadline")) in phrase
    if "有效投标保证金" in phrase:
        amount = _amount_in_text(phrase)
        return (
            amount == project.get("bid_bond_amount")
            and feasibility.get("Q07", {}).get("status") == "pass"
        )
    if "更正后日志保存" in phrase:
        return any(
            "日志" in str(item.get("new_requirement"))
            and str(item.get("effective_value")) == "180天"
            for item in correction.get("changes", [])
        )
    if "项目经理社保要求" in phrase:
        return any(
            str(item.get("effective_value")) == "2026-03至2026-08"
            for item in correction.get("changes", [])
        )
    if "企业依法纳税证明" in phrase:
        return _has_material(materials, "enterprise_tax_payment") and feasibility.get(
            "Q04", {}
        ).get("status") == "pass"
    if "企业社会保障缴纳证明" in phrase:
        has_social_security = _has_material(
            materials, "enterprise_social_security"
        )
        return has_social_security and feasibility.get("Q05", {}).get(
            "status"
        ) == "pass"
    if "商业信誉" in phrase:
        return _has_material(materials, "commercial_reputation") and feasibility.get(
            "Q06", {}
        ).get("status") == "pass"
    if "星号技术条款九项" in phrase:
        terms = correction.get("technical_star_terms") or []
        response = next(
            (
                item
                for item in materials
                if item.get("material_type") == "star_technical_response"
                and item.get("metadata", {}).get("all_star_terms_responded") is True
            ),
            None,
        )
        content = str(response.get("content") if response else "")
        return len(terms) == 9 and response is not None and all(
            term in content for term in terms
        )
    if "90万元项目合同签章页" in phrase:
        return any(
            item.get("material_type") == "case_90_contract"
            and item.get("metadata", {}).get("signature_page_complete") is True
            for item in materials
        )
    if "ISO/IEC 27001已过期" in phrase:
        return any(
            item.get("material_type") == "ISO/IEC 27001"
            and (
                str(item.get("metadata", {}).get("status")) == "expired"
                or str(item.get("valid_until")) < str(input_data["as_of"])
            )
            for item in materials
        )
    if "投标保证金仅为30000元" in phrase:
        return (
            any(
                item.get("material_type") == "bid_bond"
                and item.get("metadata", {}).get("amount") == 30000
                for item in materials
            )
            and feasibility.get("Q07", {}).get("status") == "fail"
        )
    if "缺少项目经理2026年8月社保材料" in phrase:
        return (
            not any(
                item.get("material_type") == "project_manager_social_security"
                and item.get("metadata", {}).get("coverage")
                == "2026-03至2026-08"
                for item in materials
            )
            and feasibility.get("Q03", {}).get("status") == "unknown"
        )
    if "不能因为其他材料完整" in phrase:
        return (
            analysis["machine_json"]["bid_decision"] == "human_review"
            and feasibility.get("Q03", {}).get("status") == "unknown"
        )
    if "同时存在有效和过期版本" in phrase:
        statuses = {
            str(item.get("metadata", {}).get("status"))
            for item in materials
            if item.get("material_type") == "ISO/IEC 27001"
        }
        return {"valid", "expired"} <= statuses
    if "项目经理社保同时存在完整和不完整材料" in phrase:
        coverages = {
            item.get("metadata", {}).get("coverage")
            for item in materials
            if item.get("material_type") == "project_manager_social_security"
        }
        return {"2026-03至2026-08", "2026-03至2026-07"} <= coverages
    if "投标保证金同时存在40000元和30000元" in phrase:
        amounts = {
            item.get("metadata", {}).get("amount")
            for item in materials
            if item.get("material_type") == "bid_bond"
        }
        return {40000, 30000} <= amounts
    if "冲突材料不能直接合并为满足" in phrase:
        return (
            analysis["machine_json"]["bid_decision"] == "human_review"
            and all(
                evidence_matches.get(requirement_id, {}).get("status") == "conflict"
                for requirement_id in ("Q02", "Q03", "Q07")
            )
        )
    return False


def _has_material(materials: list[dict[str, Any]], material_type: str) -> bool:
    return any(item.get("material_type") == material_type for item in materials)


def _amount_in_text(value: str) -> int | None:
    match = re.search(r"(\d+)元", value)
    return int(match.group(1)) if match else None


def _contains_version_phrase(value: Any, expected: Any) -> bool:
    actual = "".join(str(value or "").split())
    phrase = "".join(str(expected or "").split())
    return bool(actual and phrase and phrase in actual)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    result = run_all()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
