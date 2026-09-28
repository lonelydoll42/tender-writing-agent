from __future__ import annotations

import pytest

from qiaowenshu_agent.core.contracts import SkillManifest
from qiaowenshu_agent.core.registry import DuplicateSkillError, SkillRegistry


class DummySkill:
    manifest = SkillManifest(
        name="dummy",
        version="1.0.0",
        description="test skill",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )


def test_registry_rejects_duplicate_names() -> None:
    registry = SkillRegistry()
    registry.register(DummySkill())

    with pytest.raises(DuplicateSkillError):
        registry.register(DummySkill())


def test_registry_exposes_sorted_manifests() -> None:
    registry = SkillRegistry()
    registry.register(DummySkill())

    assert registry.names() == ["dummy"]
    assert registry.manifest_dicts()[0]["name"] == "dummy"
