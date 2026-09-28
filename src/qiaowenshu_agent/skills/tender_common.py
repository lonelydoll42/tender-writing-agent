"""Shared parsing helpers for tender-oriented Skills."""

from __future__ import annotations

from typing import Any, Mapping

from qiaowenshu_agent.domain.models import ScoringItem, TenderRequirement


def parse_requirements(value: Any) -> list[TenderRequirement]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError("requirements must be a list")
    return [TenderRequirement.from_mapping(item) for item in value]


def parse_scoring_items(value: Any) -> list[ScoringItem]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError("scoring_items must be a list")
    return [ScoringItem.from_mapping(item) for item in value]


def mapping_list(value: Any, field_name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be a list")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(f"{field_name} items must be objects")
        result.append({str(key): value for key, value in item.items()})
    return result


def checklist_by_category(
    requirements: list[TenderRequirement],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for requirement in requirements:
        result.setdefault(requirement.category, []).append(requirement.to_dict())
    return result
