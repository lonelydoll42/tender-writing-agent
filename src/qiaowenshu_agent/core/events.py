"""Execution events emitted by the agent runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Protocol


EventType = Literal[
    "run_started",
    "plan_created",
    "skill_started",
    "skill_finished",
    "run_finished",
    "run_failed",
]


@dataclass(frozen=True)
class AgentEvent:
    event_type: EventType
    run_id: str
    skill_name: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "run_id": self.run_id,
            "skill_name": self.skill_name,
            "payload": dict(self.payload),
            "created_at": self.created_at.isoformat(),
        }


class EventSink(Protocol):
    def emit(self, event: AgentEvent) -> None:
        ...


class InMemoryEventSink:
    """Default sink used by tests and synchronous API responses."""

    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    def emit(self, event: AgentEvent) -> None:
        self.events.append(event)

    def snapshot(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self.events]
