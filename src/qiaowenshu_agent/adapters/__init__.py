"""Adapters that connect independent Skills to existing services."""

from qiaowenshu_agent.adapters.reference import (
    CallableBackend,
    ReferenceDocumentProfileBackend,
)

__all__ = ["CallableBackend", "ReferenceDocumentProfileBackend"]
