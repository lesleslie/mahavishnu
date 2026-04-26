"""Canonical status types and normalization for the Bodai ecosystem control plane."""

from __future__ import annotations

from enum import Enum
from typing import Literal


class CanonicalStatus(str, Enum):
    """Single canonical status vocabulary for all operator-facing surfaces."""

    OK = "ok"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"
    DISABLED = "disabled"


class DegradationTrend(str, Enum):
    """Trend direction for a degrading component."""

    IMPROVING = "improving"
    STABLE = "stable"
    WORSENING = "worsening"


# Mapping from adapter-native statuses to canonical.
# This is the single source of truth for status normalization.
ADAPTER_STATUS_MAP: dict[str, CanonicalStatus] = {
    "healthy": CanonicalStatus.OK,
    "ok": CanonicalStatus.OK,
    "degraded": CanonicalStatus.DEGRADED,
    "unhealthy": CanonicalStatus.UNHEALTHY,
    "error": CanonicalStatus.UNHEALTHY,
    "not_configured": CanonicalStatus.DISABLED,
}

# Severity ordering for aggregation.
# Higher number = worse status. Used to compute overall status from components.
STATUS_SEVERITY: dict[CanonicalStatus, int] = {
    CanonicalStatus.DISABLED: 0,
    CanonicalStatus.UNKNOWN: 1,
    CanonicalStatus.OK: 2,
    CanonicalStatus.DEGRADED: 3,
    CanonicalStatus.UNHEALTHY: 4,
}

# Valid status transitions. Any transition not in this set is logged as suspicious.
VALID_TRANSITIONS: dict[CanonicalStatus, set[CanonicalStatus]] = {
    CanonicalStatus.OK: {CanonicalStatus.DEGRADED, CanonicalStatus.UNKNOWN, CanonicalStatus.DISABLED},
    CanonicalStatus.DEGRADED: {CanonicalStatus.OK, CanonicalStatus.UNHEALTHY, CanonicalStatus.UNKNOWN, CanonicalStatus.DISABLED},
    CanonicalStatus.UNHEALTHY: {CanonicalStatus.DEGRADED, CanonicalStatus.UNKNOWN, CanonicalStatus.DISABLED},
    CanonicalStatus.UNKNOWN: {CanonicalStatus.OK, CanonicalStatus.DEGRADED, CanonicalStatus.UNHEALTHY, CanonicalStatus.DISABLED},
    CanonicalStatus.DISABLED: {CanonicalStatus.OK, CanonicalStatus.UNKNOWN},
}


def normalize_status(raw: str) -> CanonicalStatus:
    """Map an adapter-native status string to the canonical vocabulary.

    Unknown raw values map to UNKNOWN.
    """
    return ADAPTER_STATUS_MAP.get(raw.lower(), CanonicalStatus.UNKNOWN)


def aggregate_statuses(statuses: list[CanonicalStatus]) -> CanonicalStatus:
    """Compute the overall status from a list of component statuses.

    Returns the worst status by severity. Empty list returns UNKNOWN.
    """
    if not statuses:
        return CanonicalStatus.UNKNOWN
    return max(statuses, key=lambda s: STATUS_SEVERITY.get(s, 1))


def is_valid_transition(from_status: CanonicalStatus, to_status: CanonicalStatus) -> bool:
    """Check whether a status transition is valid."""
    return to_status in VALID_TRANSITIONS.get(from_status, set())


def aggregate_with_optional(
    required: list[CanonicalStatus],
    optional: list[CanonicalStatus],
) -> CanonicalStatus:
    """Aggregate statuses with required vs optional semantics.

    Required unhealthy -> overall unhealthy.
    Optional unhealthy -> overall degraded (not unhealthy).
    """
    required_overall = aggregate_statuses(required) if required else CanonicalStatus.OK
    optional_overall = aggregate_statuses(optional) if optional else CanonicalStatus.OK

    if required_overall == CanonicalStatus.UNHEALTHY:
        return CanonicalStatus.UNHEALTHY
    if required_overall == CanonicalStatus.DEGRADED:
        return CanonicalStatus.DEGRADED

    # Required is OK or UNKNOWN -- check optional
    if optional_overall == CanonicalStatus.UNHEALTHY:
        return CanonicalStatus.DEGRADED  # Optional downgrades don't fail readiness
    if optional_overall == CanonicalStatus.DEGRADED:
        return CanonicalStatus.DEGRADED

    # If optional is UNKNOWN and required is OK, stay OK
    if optional_overall == CanonicalStatus.UNKNOWN:
        return CanonicalStatus.OK

    return CanonicalStatus.OK
