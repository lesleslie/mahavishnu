"""Error hierarchy for plan_index.

Subclasses carry structured context. FastMCP subclass serialization
is verified by tests/integration/plan_index/test_fastmcp_error_serialization.py.
"""

from __future__ import annotations

__all__ = ["PlanIndexError", "PlanIndexUnavailableError", "PlanNotFoundError", "PlanRebuildLockedError"]


class PlanIndexError(Exception):
    """Base class for all plan_index errors."""


class PlanNotFoundError(PlanIndexError):
    """plan_id matched no record."""

    def __init__(self, plan_id: str, message: str | None = None) -> None:
        super().__init__(message or f"Plan not found: {plan_id}")
        self.plan_id = plan_id


class PlanIndexUnavailableError(PlanIndexError):
    """Dhara unreachable; caller should fall back to filesystem read."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"plan_index unavailable: {reason}")
        self.reason = reason


class PlanRebuildLockedError(PlanIndexError):
    """Another rebuild holds the lock."""

    def __init__(self, holder: str, age_ms: int) -> None:
        super().__init__(f"plan_index rebuild locked by {holder} ({age_ms}ms)")
        self.holder = holder
        self.age_ms = age_ms
