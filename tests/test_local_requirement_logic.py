from __future__ import annotations

from datetime import date

import pytest

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.domain.models import EvidenceMaterial
from qiaowenshu_agent.skills.bid_feasibility.skill import evaluate_feasibility
from qiaowenshu_agent.skills.evidence_matching import EvidenceMatchingSkill
from qiaowenshu_agent.skills.local_requirement_logic import (
    build_local_requirement_rule,
)
from qiaowenshu_agent.skills.rule_engine import evaluate_rule_ast


def _conditions(node: dict[str, object]) -> list[dict[str, object]]:
    return node["conditions"]  # type: ignore[return-value]


def test_q1_preserves_real_alternative_and_does_not_invent_one() -> None:
    rule = build_local_requirement_rule("提供有效营业执照或法人登记证明。")

    assert rule["coverage_status"] == "partial"
    assert rule["source_text"] == "提供有效营业执照或法人登记证明。"
    assert rule["evaluation_capability"] == {
        "automatic": "unsupported",
        "human_review": True,
    }
    logic = rule["condition_logic"]
    assert logic["op"] == "any"
    assert {item["material_type"] for item in _conditions(logic)} == {
        "business_license",
        "legal_entity_registration",
    }
    assert all(item["validity"]["required"] for item in _conditions(logic))

    single = build_local_requirement_rule("提供营业执照。")
    assert single["condition_logic"]["op"] == "evidence"
    assert "conditions" not in single["condition_logic"]


def test_q2_keeps_year_and_real_or_branch() -> None:
    rule = build_local_requirement_rule(
        "提供2025年度审计报告关键页或银行资信证明。"
    )
    logic = rule["condition_logic"]

    assert logic["op"] == "any"
    audit, bank = _conditions(logic)
    assert audit["material_type"] == "audit_report_key_pages"
    assert audit["year"] == 2025
    assert bank["material_type"] == "bank_credit_reference"


def test_q5_is_explicit_all_sameperson_and_keeps_scope_and_dates() -> None:
    source = (
        "拟任项目经理须具有信息系统项目管理师证书，且为投标人连续缴纳"
        "2026年3月至8月社会保险。"
    )
    rule = build_local_requirement_rule(source)
    logic = rule["condition_logic"]

    assert logic["op"] == "all"
    sameperson = _conditions(logic)[0]
    assert sameperson["op"] == "sameperson"
    inner = _conditions(sameperson)[0]
    assert inner["op"] == "all"
    conditions = _conditions(inner)
    date_range = next(item for item in conditions if item["op"] == "date_range")
    assert date_range["start"] == "2026-03"
    assert date_range["end"] == "2026-08"
    assert date_range["continuous"] is True
    assert any(
        item.get("material_type") == "bidder_employer_relationship"
        for item in conditions
    )

    without_scope = build_local_requirement_rule(
        "项目经理具有信息系统项目管理师证书并缴纳2026年3月至8月社会保险。"
    )
    without_scope_conditions = _conditions(
        _conditions(without_scope["condition_logic"])[0]
    )
    assert not any(
        item.get("material_type") == "bidder_employer_relationship"
        for item in without_scope_conditions
    )


def test_t1_keeps_not_and_only_protocols_present() -> None:
    source = (
        "支持与采购人现有统一身份平台通过OAuth2.0/OIDC对接；"
        "不得要求更换现有身份系统。"
    )
    rule = build_local_requirement_rule(source)
    logic = rule["condition_logic"]

    assert logic["op"] == "all"
    conditions = _conditions(logic)
    protocol = conditions[0]
    assert protocol["op"] == "any"
    assert {item["material_type"] for item in _conditions(protocol)} == {
        "oauth2",
        "oidc",
    }
    negated = conditions[-1]
    assert negated["op"] == "not"
    assert "不得要求更换" in negated["condition"]["source_terms"]
    assert rule["rule_ast"]["source_text"] == source

    oauth_only = build_local_requirement_rule(
        "支持通过OAuth2.0对接现有身份系统。"
    )
    oauth_logic = oauth_only["condition_logic"]
    assert _conditions(oauth_logic)[0]["op"] == "evidence"
    assert _conditions(oauth_logic)[0]["material_type"] == "oauth2"


def test_t3_has_outer_all_and_local_crypto_any_only() -> None:
    source = (
        "敏感字段传输须采用TLS1.2及以上；"
        "数据库敏感字段支持国密算法或等效强度加密。"
    )
    rule = build_local_requirement_rule(source)
    logic = rule["condition_logic"]

    assert logic["op"] == "all"
    conditions = _conditions(logic)
    tls = next(item for item in conditions if item["op"] == "comparison")
    assert tls["field"] == "tls_version"
    assert tls["value"] == "1.2"
    crypto = next(
        item
        for item in conditions
        if item.get("op") == "any"
    )
    assert {item["material_type"] for item in _conditions(crypto)} == {
        "national_cryptography",
        "equivalent_strength_encryption",
    }
    assert rule["rule_ast"]["op"] == "manual_review"


def test_manual_review_reaches_rule_engine_and_does_not_match_metadata() -> None:
    source = "支持通过OAuth2.0对接现有身份系统。"
    rule = build_local_requirement_rule(source)
    material = EvidenceMaterial(
        material_id="arbitrary",
        material_type="任意材料",
        title="OAuth2.0",
        content="现有身份系统",
        metadata={"tls_version": "1.3", "matched": True},
    )

    evaluation = evaluate_rule_ast(
        rule["rule_ast"],
        [material],
        as_of=date(2026, 10, 6),
    )
    assert evaluation.status == "human_review"
    assert evaluation.details["source_text"] == source


@pytest.mark.asyncio
async def test_manual_review_is_used_by_evidence_matching_and_bid_feasibility() -> None:
    source = "支持通过OAuth2.0对接现有身份系统。"
    rule = build_local_requirement_rule(source)
    material = {
        "material_id": "arbitrary",
        "material_type": "任意材料",
        "title": "OAuth2.0",
        "content": "现有身份系统",
        "metadata": {"matched": True},
    }
    request = SkillRequest.create(
        {
            "requirements": [
                {
                    "requirement_id": "t1",
                    "title": "身份系统对接",
                    "description": source,
                    "mandatory": True,
                    "check_rule": rule,
                }
            ],
            "materials": [material],
            "as_of": "2026-10-06",
        },
        skill_name="evidence-matching",
    )
    matching = await EvidenceMatchingSkill().execute(
        request,
        SkillContext(run_id="local-rule-test", request=request),
    )
    assert matching.data["matches"][0]["status"] == "human_review"

    decision = evaluate_feasibility(
        "project-1",
        [
            {
                "requirement_id": "t1",
                "title": "身份系统对接",
                "description": source,
                "mandatory": True,
                "check_rule": rule,
            }
        ],
        {"bidder_id": "bidder-1", "materials": [material]},
        options={"as_of": "2026-10-06"},
    )
    assert decision.decision == "human_review"
    assert decision.checks[0].status == "unknown"
