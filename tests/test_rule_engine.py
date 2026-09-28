from __future__ import annotations

from datetime import date

from qiaowenshu_agent.domain.models import EvidenceMaterial
from qiaowenshu_agent.skills.rule_engine import evaluate_rule_ast


AS_OF = date(2026, 8, 17)


def _material(
    material_id: str,
    material_type: str,
    *,
    case_id: str | None = None,
    **metadata: object,
) -> EvidenceMaterial:
    if case_id is not None:
        metadata["case_id"] = case_id
    metadata.setdefault("status", "valid")
    return EvidenceMaterial(
        material_id=material_id,
        material_type=material_type,
        metadata=metadata,
    )


def test_all_and_any_rules_are_composable() -> None:
    materials = [
        _material("contract-1", "contract"),
        _material("acceptance-1", "acceptance"),
    ]

    result = evaluate_rule_ast(
        {
            "op": "all",
            "conditions": [
                {"op": "exists", "evidence_types": ["contract"]},
                {
                    "op": "any",
                    "conditions": [
                        {"op": "exists", "evidence_types": ["acceptance"]},
                        {"op": "exists", "evidence_types": ["ISO27001"]},
                    ],
                },
            ],
        },
        materials,
        as_of=AS_OF,
    )

    assert result.status == "matched"
    assert set(result.material_ids) == {"contract-1", "acceptance-1"}


def test_bundle_count_does_not_merge_unrelated_cases() -> None:
    materials = [
        _material("a-contract", "contract", case_id="a"),
        _material("b-acceptance", "acceptance", case_id="b"),
    ]

    result = evaluate_rule_ast(
        {
            "op": "bundle_count",
            "group_by": "case_id",
            "evidence_types": ["contract", "acceptance"],
            "minimum": 1,
        },
        materials,
        as_of=AS_OF,
    )

    assert result.status == "partial"


def test_valid_and_expired_versions_require_review() -> None:
    materials = [
        _material("valid", "ISO27001", valid_until="2027-01-01"),
        _material("expired", "ISO27001", valid_until="2026-01-01"),
    ]

    result = evaluate_rule_ast(
        {"op": "exists", "evidence_types": ["ISO27001"]},
        materials,
        as_of=AS_OF,
    )

    assert result.status == "conflict"
