from __future__ import annotations

import asyncio
from typing import Any

import pytest

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.skills.compliance_review import ComplianceReviewSkill


def _execute(payload: dict[str, Any]):
    request = SkillRequest.create(payload, skill_name="compliance-review")
    return asyncio.run(
        ComplianceReviewSkill().execute(
            request,
            SkillContext(run_id="compliance-reliability", request=request),
        )
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"project_id": "project-1"},
        {"ledger": {}},
        {"ledger": {"entries": []}},
        {"requirements": []},
    ],
)
def test_empty_or_metadata_only_scope_is_not_checked(payload: dict[str, Any]) -> None:
    result = _execute(payload)

    assert result.status == "partial"
    assert result.data["business_status"] == "not_checked"
    assert result.data["checked"] is False
    assert result.data["submission_allowed"] is False
    assert result.data["needs_human_review"] is True
    assert result.data["summary"]["passed"] is False
    assert result.data["check_coverage"]["completed_checks"] == []


@pytest.mark.parametrize(
    ("payload", "finding_id"),
    [
        ({"ledger": "not-an-object"}, "INPUT-LEDGER-SHAPE"),
        ({"ledger": {"entries": [None]}}, "INPUT-LEDGER-ENTRY-001"),
        (
            {
                "ledger": {
                    "entries": [
                        {
                            "requirement_id": "Q-001",
                            "mandatory": True,
                            "status": "unrecognized",
                        }
                    ]
                }
            },
            "INPUT-LEDGER-STATUS-001",
        ),
    ],
)
def test_corrupt_ledger_shapes_and_statuses_are_reported(
    payload: dict[str, Any],
    finding_id: str,
) -> None:
    result = _execute(payload)

    assert result.status == "partial"
    assert result.data["business_status"] == "needs_review"
    assert result.data["submission_allowed"] is False
    assert finding_id in {
        finding["finding_id"] for finding in result.data["findings"]
    }
    assert result.data["summary"]["high_risk_count"] >= 1


@pytest.mark.parametrize("mandatory_value", ["true", "false"])
def test_string_mandatory_values_never_become_booleans(
    mandatory_value: str,
) -> None:
    result = _execute(
        {
            "requirements": [
                {"requirement_id": "Q-001", "mandatory": True}
            ],
            "ledger": {
                "entries": [
                    {
                        "requirement_id": "Q-001",
                        "mandatory": mandatory_value,
                        "status": "matched",
                    }
                ]
            },
        }
    )

    assert result.status == "partial"
    assert result.data["business_status"] == "needs_review"
    assert result.data["submission_allowed"] is False
    assert any(
        finding["type"] == "input_integrity"
        and "mandatory" in finding["message"]
        for finding in result.data["findings"]
    )


def test_missing_hard_requirement_record_is_blocking_but_diagnostic_partial() -> None:
    result = _execute(
        {
            "project_id": "project-1",
            "requirements": [
                {"requirement_id": "HARD-001", "mandatory": True},
                {"requirement_id": "OPTIONAL-001", "mandatory": False},
            ],
            "ledger": {"entries": []},
        }
    )

    assert result.status == "partial"
    assert result.data["business_status"] == "failed"
    assert result.data["checked"] is True
    assert result.data["submission_allowed"] is False
    assert result.data["needs_human_review"] is True
    assert result.data["summary"]["passed"] is False
    assert result.data["summary"]["blocker_count"] == 1
    assert result.data["summary"]["warning_count"] == 2
    coverage = result.data["check_coverage"]
    assert coverage["missing_record_requirement_ids"] == [
        "HARD-001",
        "OPTIONAL-001",
    ]
    assert "requirement_ledger" in coverage["pending_checks"]
    assert coverage["requirement_coverage_complete"] is False


@pytest.mark.parametrize("status", ["matched", "pass"])
def test_legacy_success_statuses_pass_only_with_reviewable_records(
    status: str,
) -> None:
    result = _execute(
        {
            "requirements": [
                {"requirement_id": "Q-001", "mandatory": True}
            ],
            "ledger": {
                "entries": [
                    {
                        "requirement_id": "Q-001",
                        "mandatory": True,
                        "status": status,
                    }
                ]
            },
        }
    )

    assert result.status == "success"
    assert result.data["business_status"] == "passed"
    assert result.data["submission_allowed"] is False
    assert result.data["scoped_gate_passed"] is True
    assert result.data["summary"]["passed"] is True


def test_unknown_ledger_reference_requires_review() -> None:
    result = _execute(
        {
            "requirements": [
                {"requirement_id": "Q-001", "mandatory": True}
            ],
            "ledger": {
                "entries": [
                    {
                        "requirement_id": "Q-001",
                        "mandatory": True,
                        "status": "matched",
                    },
                    {
                        "requirement_id": "GHOST-001",
                        "mandatory": False,
                        "status": "matched",
                    },
                ]
            },
        }
    )

    assert result.data["business_status"] == "needs_review"
    assert result.data["submission_allowed"] is False
    assert result.data["check_coverage"]["unknown_ledger_requirement_ids"] == [
        "GHOST-001"
    ]


def test_blocker_and_human_review_have_distinct_business_statuses() -> None:
    blocker = _execute(
        {
            "ledger": {
                "entries": [
                    {
                        "requirement_id": "HARD-001",
                        "mandatory": True,
                        "status": "missing",
                    }
                ]
            }
        }
    )
    human_review = _execute(
        {
            "ledger": {
                "entries": [
                    {
                        "requirement_id": "HARD-002",
                        "mandatory": True,
                        "status": "human_review",
                    }
                ]
            }
        }
    )

    assert blocker.status == "partial"
    assert blocker.data["business_status"] == "failed"
    assert blocker.data["summary"]["blocker_count"] == 1
    assert blocker.data["submission_allowed"] is False
    assert human_review.status == "partial"
    assert human_review.data["business_status"] == "needs_review"
    assert human_review.data["needs_human_review"] is True
    assert human_review.data["summary"]["high_risk_count"] == 1


def test_completed_risk_free_checks_can_pass_with_explicit_scope_limit() -> None:
    result = _execute(
        {
            "project_id": "project-1",
            "requirements": [
                {"requirement_id": "Q-001", "mandatory": True}
            ],
            "ledger": {
                "entries": [
                    {
                        "requirement_id": "Q-001",
                        "mandatory": True,
                        "status": "matched",
                    }
                ]
            },
            "quotation_result": {
                "checks": [{"check_id": "QUOTE-001", "status": "passed"}],
                "summary": {"check_count": 1},
            },
            "consistency_result": {
                "conflicts": [],
                "summary": {"documents_checked": 2, "conflict_count": 0},
            },
            "required_attachments": ["quotation.pdf"],
            "present_attachments": ["quotation.pdf"],
            "signatures": {"bidder_seal": True},
            "draft": {"text": "已完成的投标文件正文"},
        }
    )

    assert result.status == "success"
    assert result.data["business_status"] == "passed"
    assert result.data["checked"] is True
    assert result.data["submission_allowed"] is False
    assert result.data["scoped_gate_passed"] is True
    assert result.data["summary"]["passed"] is True
    coverage = result.data["check_coverage"]
    assert {
        "requirement_coverage",
        "requirement_ledger",
        "consistency",
        "quotation",
        "attachments",
        "signatures",
        "draft",
    } <= set(coverage["completed_checks"])
    assert coverage["scope_limited"] is True
    assert coverage["final_submission_readiness_certified"] is False


def test_empty_quotation_result_cannot_supply_a_pass_scope() -> None:
    result = _execute(
        {
            "project_id": "project-1",
            "quotation_result": {
                "checks": [],
                "summary": {"check_count": 0, "passed": True},
            },
        }
    )

    assert result.data["business_status"] == "not_checked"
    assert result.data["checked"] is False
    assert result.data["submission_allowed"] is False


@pytest.mark.parametrize(
    ("input_key", "input_value", "pending_name"),
    [
        ("quotation_result", {}, "quotation"),
        ("consistency_result", {}, "consistency"),
        ("draft", {}, "draft"),
        ("signatures", {}, "signatures"),
        ("required_attachments", [], "attachments"),
    ],
)
def test_empty_declared_check_stays_pending_alongside_valid_ledger(
    input_key: str,
    input_value: Any,
    pending_name: str,
) -> None:
    result = _execute(
        {
            "ledger": {
                "entries": [
                    {
                        "requirement_id": "Q-001",
                        "mandatory": True,
                        "status": "matched",
                    }
                ]
            },
            input_key: input_value,
        }
    )

    assert result.status == "partial"
    assert result.data["business_status"] == "needs_review"
    assert result.data["checked"] is True
    assert result.data["scoped_gate_passed"] is False
    assert result.data["submission_allowed"] is False
    assert pending_name in result.data["check_coverage"]["pending_checks"]
    assert result.data["summary"]["passed"] is False


@pytest.mark.parametrize(
    "signature_value",
    [None, "unknown", "approved", "yes", "true", 1],
)
def test_ambiguous_signature_state_cannot_pass(signature_value: Any) -> None:
    result = _execute(
        {
            "ledger": {
                "entries": [
                    {
                        "requirement_id": "Q-001",
                        "mandatory": True,
                        "status": "matched",
                    }
                ]
            },
            "signatures": {"盖章": signature_value},
        }
    )

    assert result.status == "partial"
    assert result.data["business_status"] == "needs_review"
    assert result.data["needs_human_review"] is True
    assert result.data["submission_allowed"] is False
    assert result.data["summary"]["high_risk_count"] >= 1


@pytest.mark.parametrize("signature_value", [True, "pass", "passed"])
def test_explicitly_valid_signature_is_accepted(signature_value: Any) -> None:
    result = _execute(
        {
            "ledger": {
                "entries": [
                    {
                        "requirement_id": "Q-001",
                        "mandatory": True,
                        "status": "matched",
                    }
                ]
            },
            "signatures": {"盖章": signature_value},
        }
    )

    assert result.data["business_status"] == "passed"
    assert result.data["scoped_gate_passed"] is True
    assert result.data["submission_allowed"] is False


def test_mandatory_not_applicable_requires_an_auditable_reason() -> None:
    base = {
        "requirements": [
            {"requirement_id": "Q-001", "mandatory": True}
        ],
        "ledger": {
            "entries": [
                {
                    "requirement_id": "Q-001",
                    "mandatory": True,
                    "status": "not_applicable",
                }
            ]
        },
    }

    unresolved = _execute(base)
    justified = _execute(
        {
            **base,
            "ledger": {
                "entries": [
                    {
                        **base["ledger"]["entries"][0],
                        "not_applicable_reason": (
                            "招标文件第 4.2 条明确说明本项目不涉及该项资质"
                        ),
                    }
                ]
            },
        }
    )

    assert unresolved.data["business_status"] == "needs_review"
    assert unresolved.data["submission_allowed"] is False
    assert any(
        finding["finding_id"] == "LEDGER-Q-001-NOT-APPLICABLE"
        for finding in unresolved.data["findings"]
    )
    assert justified.data["business_status"] == "passed"
    assert justified.data["scoped_gate_passed"] is True
    assert justified.data["submission_allowed"] is False
