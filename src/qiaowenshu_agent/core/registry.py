"""Explicit registry for independent skills."""

from __future__ import annotations

from typing import Any

from qiaowenshu_agent.core.contracts import Skill, SkillManifest


class DuplicateSkillError(ValueError):
    pass


class SkillNotFoundError(LookupError):
    pass


class SkillRegistry:
    """Keeps skill discovery explicit and free of import side effects."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill, *, replace: bool = False) -> None:
        name = skill.manifest.name
        if not name.strip():
            raise ValueError("skill name cannot be empty")
        if name in self._skills and not replace:
            raise DuplicateSkillError(f"skill already registered: {name}")
        self._skills[name] = skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def require(self, name: str) -> Skill:
        skill = self.get(name)
        if skill is None:
            raise SkillNotFoundError(f"skill not found: {name}")
        return skill

    def names(self) -> list[str]:
        return sorted(self._skills)

    def manifests(self) -> list[SkillManifest]:
        return [self._skills[name].manifest for name in self.names()]

    def manifest_dicts(self) -> list[dict[str, Any]]:
        return [manifest.to_dict() for manifest in self.manifests()]
