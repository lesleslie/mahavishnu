"""Canonical retry-policy helpers built on Oneiric ``WorkflowRetryAction``.

Wave 3 (W3): Mahavishnu adapters historically decorate transient-call sites
with ``@tenacity.retry(...)`` using per-site ``wait_exponential`` parameters.
``WorkflowRetryAction`` centralises the backoff calculation so the same
delay curve is used across every Bodai component and is observable via
Dhara's audit log.

This module factors the canonical delay calculation into two helpers:

* ``compute_retry_delay(attempt, ...)`` — single-attempt delay, ready to feed
  ``asyncio.sleep`` between calls.
* ``next_retry_decision(...)`` — full envelope including ``status``
  (``scheduled`` / ``exhausted``) and the next ``attempt`` number, ready for
  loop control.

Existing ``@tenacity.retry`` decorators remain valid; this module provides
the canonical delay curve so new code (and any refactors of the legacy
``wait_exponential`` sites) inherits the Bodai-standard envelope.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from oneiric.actions.workflow import (
    WorkflowRetryAction,
    WorkflowRetrySettings,
)


@lru_cache(maxsize=1)
def _retry_action() -> WorkflowRetryAction:
    """Return the process-wide ``WorkflowRetryAction`` with Bodai defaults."""
    return WorkflowRetryAction(
        settings=WorkflowRetrySettings(
            max_attempts=3,
            base_delay_seconds=1.0,
            multiplier=2.0,
            max_delay_seconds=60.0,
            jitter=0.1,
        )
    )


async def compute_retry_delay(
    attempt: int,
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 1.0,
    multiplier: float = 2.0,
    max_delay_seconds: float = 60.0,
    jitter: float = 0.1,
) -> float:
    """Return the canonical delay (seconds) before ``attempt`` should run.

    Args:
        attempt: The attempt number that just completed (0 = first try).
        max_attempts: Total attempts before the policy is exhausted.
        base_delay_seconds: Initial delay used at ``attempt=1``.
        multiplier: Exponential growth factor between attempts.
        max_delay_seconds: Cap on the computed delay.
        jitter: Deterministic jitter factor in [0, 1].

    Returns ``0.0`` when the policy is exhausted (the kit omits the
    ``delay_seconds`` key on the exhausted branch — verified at
    ``oneiric.actions.workflow``). Callers can ``await
    asyncio.sleep(compute_retry_delay(...))`` unconditionally.
    """
    result = await _retry_action().execute(
        {
            "attempt": attempt,
            "max_attempts": max_attempts,
            "base_delay_seconds": base_delay_seconds,
            "multiplier": multiplier,
            "max_delay_seconds": max_delay_seconds,
            "jitter": jitter,
        }
    )
    return float(result.get("delay_seconds", 0.0))


async def next_retry_decision(
    attempt: int,
    **overrides: Any,
) -> dict[str, Any]:
    """Return the canonical retry envelope for the next loop iteration.

    Shape: ``{"status": "scheduled" | "exhausted", "attempt": int,
    "next_attempt": int, "delay_seconds": float, "max_attempts": int}``.

    When the policy is exhausted the kit omits ``next_attempt`` and
    ``delay_seconds``; we surface ``delay_seconds=0.0`` for symmetry so the
    loop caller can ``await asyncio.sleep(result["delay_seconds"])``
    unconditionally.
    """
    result = await _retry_action().execute({"attempt": attempt, **overrides})
    return {
        "status": result["status"],
        "attempt": result["attempt"],
        "next_attempt": result.get("next_attempt", attempt),
        "delay_seconds": result.get("delay_seconds", 0.0),
        "max_attempts": result["max_attempts"],
    }


__all__ = ["compute_retry_delay", "next_retry_decision"]
