"""Dependency-injected context visible to skills during one run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from qiaowenshu_agent.core.budget import BudgetLedger
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.core.events import AgentEvent, EventSink
from qiaowenshu_agent.core.trace import TraceRecorder


@dataclass
class SkillContext:
    run_id: str
    request: SkillRequest
    services: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    budget: BudgetLedger = field(default_factory=BudgetLedger)
    trace: TraceRecorder = field(default_factory=TraceRecorder)
    event_sink: EventSink | None = None

    def get_service(self, name: str, default: Any = None) -> Any:
        return self.services.get(name, default)

    def emit(
        self,
        event_type: Any,
        *,
        skill_name: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        event = AgentEvent(
            event_type=event_type,
            run_id=self.run_id,
            skill_name=skill_name,
            payload=dict(payload or {}),
        )
        self.trace.record(
            event_type,
            skill_name=skill_name,
            payload=event.payload,
        )
        if self.event_sink is not None:
            self.event_sink.emit(event)
