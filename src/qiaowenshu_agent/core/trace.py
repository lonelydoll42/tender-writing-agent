"""In-process trace recorder with a serializable representation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class TraceEntry:
    sequence: int
    event_type: str
    skill_name: str | None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "event_type": self.event_type,
            "skill_name": self.skill_name,
            "payload": dict(self.payload),
            "created_at": self.created_at.isoformat(),
        }


class TraceRecorder:
    def __init__(self) -> None:
        self._entries: list[TraceEntry] = []

    def record(
        self,
        event_type: str,
        *,
        skill_name: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> TraceEntry:
        entry = TraceEntry(
            sequence=len(self._entries),
            event_type=event_type,
            skill_name=skill_name,
            payload=dict(payload or {}),
        )
        self._entries.append(entry)
        return entry

    def snapshot(self) -> list[dict[str, Any]]:
        return [entry.to_dict() for entry in self._entries]
