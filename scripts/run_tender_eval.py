from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.core.registry import SkillRegistry
from qiaowenshu_agent.core.runtime import DeterministicPlanner
from qiaowenshu_agent.skills.bid_feasibility.skill import BidFeasibilitySkill
from qiaowenshu_agent.skills.consistency_review import ConsistencyReviewSkill
from qiaowenshu_agent.skills.evidence_matching import EvidenceMatchingSkill
from qiaowenshu_agent.skills.document_writing import DocumentWritingSkill
from qiaowenshu_agent.skills.quotation_check import QuotationCheckSkill
from qiaowenshu_agent.skills.scoring_strategy import ScoringStrategySkill
from qiaowenshu_agent.skills.tender_decomposition.skill import (
    TenderDecompositionSkill,
)

from tests.evals.cases import (
    COMPLETE_BIDDER,
    REGRESSION_CASES,
    REQUIREMENTS,
    SCORING_TABLE,
)


def _context() -> SkillContext:
    return SkillContext(
        run_id="run-eval-report",
        request=SkillRequest.create(),
    )


class _EvalWritingLLM:
    """Deterministic local stand-in; the report must never spend API quota."""

    config = SimpleNamespace(model_for=lambda purpose: "qwen-max")

    async def complete_json(self, messages, **kwargs):
        return (
            {
                "section_id": "implementation",
                "title": "项目实施方案",
                "content_markdown": "根据招标要求编制项目实施方案。",
                "evidence_used": [],
                "unknowns": [],
                "risk_flags": [],
                "requirement_coverage": ["tech-backup"],
                "scoring_coverage": [],
            },
            SimpleNamespace(usage={"total_tokens": 32}),
        )


async def build_report() -> dict[str, Any]:
    planner = DeterministicPlanner(default_skill=None)
    positive_prompts = {
        "分析招标文件": "tender-intake",
        "拆解评分标准": "scoring-strategy",
        "检查废标风险": "bid-feasibility",
        "拆解资格条件": "tender-decomposition",
    }
    negative_prompts = ["什么叫投标保证金", "一般标书多少页"]
    positive_passed = sum(
        [
            planner.plan(SkillRequest.create({"task": prompt}), SkillRegistry())[
                0
            ].skill_name
            == expected
            for prompt, expected in positive_prompts.items()
        ]
    )
    negative_passed = sum(
        not planner.plan(SkillRequest.create({"task": prompt}), SkillRegistry())
        for prompt in negative_prompts
    )

    decomposition = await TenderDecompositionSkill().execute(
        SkillRequest.create(
            {"project_id": "benchmark-project", "requirements": REQUIREMENTS}
        ),
        _context(),
    )
    expected_ids = {item["requirement_id"] for item in REQUIREMENTS}
    actual_ids = {item["requirement_id"] for item in decomposition.data["requirements"]}
    hard_ids = {
        item["requirement_id"]
        for item in REQUIREMENTS
        if item["category"] in {"disqualification", "qualification"}
    }
    actual_hard_ids = {
        item["requirement_id"]
        for item in decomposition.data["requirements"]
        if item["category"] in {"disqualification", "qualification"}
    }

    feasibility = await BidFeasibilitySkill().execute(
        SkillRequest.create(
            {
                "project_id": "benchmark-project",
                "requirements": REQUIREMENTS,
                "bidder_profile": COMPLETE_BIDDER,
            }
        ),
        _context(),
    )
    missing_bidder = dict(COMPLETE_BIDDER)
    missing_bidder["materials"] = [
        material
        for material in COMPLETE_BIDDER["materials"]
        if material["material_id"] != "mat-iso"
    ]
    missing_evidence = await BidFeasibilitySkill().execute(
        SkillRequest.create(
            {
                "project_id": "benchmark-project",
                "requirements": REQUIREMENTS,
                "bidder_profile": missing_bidder,
            }
        ),
        _context(),
    )
    scoring = await ScoringStrategySkill().execute(
        SkillRequest.create(
            {"project_id": "benchmark-project", "scoring_table": SCORING_TABLE}
        ),
        _context(),
    )
    evidence = await EvidenceMatchingSkill().execute(
        SkillRequest.create(
            {
                "requirements": [REQUIREMENTS[2]],
                "materials": COMPLETE_BIDDER["materials"][:1],
            }
        ),
        _context(),
    )
    consistency = await ConsistencyReviewSkill().execute(
        SkillRequest.create(
            {
                "documents": [
                    {
                        "document_id": "commercial",
                        "text": "项目工期：90日历天",
                    },
                    {
                        "document_id": "technical",
                        "text": "项目工期：120日历天",
                    },
                ]
            }
        ),
        _context(),
    )
    quotation = await QuotationCheckSkill().execute(
        SkillRequest.create(
            {
                "total_price": 110,
                "line_items": [
                    {"quantity": 2, "unit_price": 30},
                    {"quantity": 1, "unit_price": 40},
                ],
            }
        ),
        _context(),
    )
    writing = await DocumentWritingSkill(llm=_EvalWritingLLM()).execute(
        SkillRequest.create(
            {
                "project_id": "benchmark-project",
                "tender_profile": {"project_name": "测试项目"},
                "sections": [
                    {
                        "section_id": "implementation",
                        "title": "项目实施方案",
                        "kind": "technical",
                    }
                ],
                "requirements": [REQUIREMENTS[-1]],
            }
        ),
        _context(),
    )

    score_components = {
        "disqualification_recall": {
            "value": len(actual_hard_ids & {"dq-bond"}) / len({"dq-bond"}),
            "weight": 20,
        },
        "qualification_recall": {
            "value": len(actual_hard_ids & (hard_ids - {"dq-bond"}))
            / len(hard_ids - {"dq-bond"}),
            "weight": 15,
        },
        "scoring_item_recall": {
            "value": len(scoring.data["scoring_items"]) / 3,
            "weight": 20,
        },
        "technical_requirement_recall": {
            "value": 1.0 if "tech-backup" in actual_ids else 0.0,
            "weight": 15,
        },
        "no_hallucination": {
            "value": 1.0
            if missing_evidence.data["decision"] == "human_review"
            and evidence.data["matches"][0]["status"] == "missing"
            else 0.0,
            "weight": 10,
        },
        "cross_document_consistency": {
            "value": 1.0 if consistency.data["summary"]["conflict_count"] == 1 else 0.0,
            "weight": 10,
        },
        "output_structure": {
            "value": 1.0
            if {
                "requirements",
                "scoring_items",
                "summary",
            }
            <= decomposition.data.keys()
            else 0.0,
            "weight": 5,
        },
        "bid_document_content_quality": {
            "value": 1.0 if writing.ok and writing.data.get("markdown") else 0.0,
            "weight": 5,
        },
    }
    weighted_score = sum(
        component["value"] * component["weight"]
        for component in score_components.values()
    )

    return {
        "trigger": {
            "positive": {"passed": positive_passed, "total": len(positive_prompts)},
            "negative": {"passed": negative_passed, "total": len(negative_prompts)},
        },
        "nodes": {
            "requirement_recall": len(actual_ids & expected_ids) / len(expected_ids),
            "hard_requirement_recall": len(actual_hard_ids & hard_ids) / len(hard_ids),
            "complete_bidder_decision": feasibility.data["decision"],
            "missing_iso_decision": missing_evidence.data["decision"],
            "missing_evidence_status": evidence.data["matches"][0]["status"],
            "scoring_total": scoring.data["summary"]["total_score"],
            "consistency_conflict_count": consistency.data["summary"]["conflict_count"],
            "quotation_failed_count": quotation.data["summary"]["failed_count"],
        },
        "quality": {
            "weighted_score": round(weighted_score, 2),
            "score_components": score_components,
            "forbidden_missing_evidence_pass": int(
                missing_evidence.data["decision"] == "bid"
            ),
        },
        "regression": {
            "supported": sum(case["supported"] for case in REGRESSION_CASES),
            "total": len(REGRESSION_CASES),
            "unsupported_cases": [
                case["id"] for case in REGRESSION_CASES if not case["supported"]
            ],
        },
        "scope": {
            "implemented_front_nodes": [
                "tender-intake",
                "tender-decomposition",
                "bid-feasibility",
                "scoring-strategy",
                "evidence-matching",
                "consistency-review",
                "quotation-check",
                "compliance-review",
                "document-writing",
            ],
            "full_bid_generation": False,
            "draft_generation": writing.status,
        },
    }


def main() -> None:
    print(json.dumps(asyncio.run(build_report()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
