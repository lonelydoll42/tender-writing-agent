"""Stable contracts between the agent runtime and independent skills."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Protocol, TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from qiaowenshu_agent.core.context import SkillContext


SkillStatus = Literal["success", "partial", "blocked", "retryable_error", "error"]


@dataclass(frozen=True)
class SkillManifest:
    """Machine-readable metadata for one independently loadable skill."""

    name: str
    version: str
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    capabilities: tuple[str, ...] = ()
    required_permissions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "input_schema": dict(self.input_schema),
            "output_schema": dict(self.output_schema),
            "capabilities": list(self.capabilities),
            "required_permissions": list(self.required_permissions),
        }


@dataclass(frozen=True)
class SkillRequest:
    """Input envelope passed to a skill by the runtime."""

    request_id: str
    input: dict[str, Any]
    skill_name: str | None = None
    user_id: str | None = None
    tenant_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        input: Mapping[str, Any] | None = None,
        *,
        skill_name: str | None = None,
        user_id: str | None = None,
        tenant_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "SkillRequest":
        return cls(
            request_id=f"req_{uuid4().hex[:16]}",
            input=dict(input or {}),
            skill_name=skill_name,
            user_id=user_id,
            tenant_id=tenant_id,
            metadata=dict(metadata or {}),
        )


@dataclass
class SkillResult:
    """Reason-bearing result returned by every skill invocation."""

    status: SkillStatus
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    error_code: str | None = None
    warnings: list[str] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def ok(self) -> bool:
        return self.status in {"success", "partial"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "data": self.data,
            "message": self.message,
            "error_code": self.error_code,
            "warnings": list(self.warnings),
            "artifacts": list(self.artifacts),
            "usage": dict(self.usage),
            "trace_id": self.trace_id,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def success(
        cls,
        data: Mapping[str, Any] | None = None,
        *,
        message: str = "",
        **kwargs: Any,
    ) -> "SkillResult":
        return cls(status="success", data=dict(data or {}), message=message, **kwargs)

    @classmethod
    def partial(
        cls,
        data: Mapping[str, Any] | None = None,
        *,
        message: str = "",
        warnings: list[str] | None = None,
        **kwargs: Any,
    ) -> "SkillResult":
        return cls(
            status="partial",
            data=dict(data or {}),
            message=message,
            warnings=list(warnings or []),
            **kwargs,
        )

    @classmethod
    def blocked(cls, *, message: str, error_code: str) -> "SkillResult":
        return cls(status="blocked", message=message, error_code=error_code)

    @classmethod
    def failure(
        cls,
        *,
        message: str,
        error_code: str,
        retryable: bool = False,
        warnings: list[str] | None = None,
        usage: Mapping[str, Any] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
    ) -> "SkillResult":
        return cls(
            status="retryable_error" if retryable else "error",
            message=message,
            error_code=error_code,
            warnings=list(warnings or []),
            usage=dict(usage or {}),
            artifacts=list(artifacts or []),
        )


class Skill(Protocol):
    """Runtime protocol implemented by every independent skill."""

    @property
    def manifest(self) -> SkillManifest:
        ...

    async def execute(
        self,
        request: SkillRequest,
        context: "SkillContext",
    ) -> SkillResult:
        ...
