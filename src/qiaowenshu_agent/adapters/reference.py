"""Adapters for progressively reusing the reference repositories.

These adapters accept already-imported objects or callables. The new project
does not import the reference repositories at package-import time, which keeps
Skill loading independent from deployment layout.
"""

from __future__ import annotations

import inspect
from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Mapping

from qiaowenshu_agent.core.context import SkillContext


class CallableBackend:
    """Turn a host-provided callable into the common backend protocol."""

    def __init__(self, runner: Callable[..., Any]) -> None:
        self.runner = runner

    async def run(
        self,
        payload: Mapping[str, Any],
        context: SkillContext,
    ) -> Any:
        result = self.runner(dict(payload), context)
        if inspect.isawaitable(result):
            return await result
        return result


class ReferenceDocumentProfileBackend:
    """Bridge to knowleagev1.0 ``ProfileAgent`` without importing it here."""

    def __init__(self, profile_agent: Any) -> None:
        self.profile_agent = profile_agent

    def run(
        self,
        payload: Mapping[str, Any],
        _context: SkillContext,
    ) -> Any:
        file_path = payload.get("file_path")
        job_id = str(payload.get("job_id") or payload.get("file_id") or "")
        if not file_path:
            raise ValueError("reference ProfileAgent requires file_path")
        kwargs = {
            "output_dir": payload.get("output_dir"),
        }
        mode = str(payload.get("mode") or "coarse")
        if mode == "coarse":
            method = getattr(self.profile_agent, "run_coarse")
        elif mode == "lightweight" and hasattr(
            self.profile_agent, "run_lightweight_anatomy"
        ):
            method = getattr(self.profile_agent, "run_lightweight_anatomy")
        else:
            method = getattr(self.profile_agent, "run")
        result = method(str(file_path), job_id, **kwargs)
        return serialize_reference_value(result)


def serialize_reference_value(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return {
            str(key): serialize_reference_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [serialize_reference_value(item) for item in value]
    return value
