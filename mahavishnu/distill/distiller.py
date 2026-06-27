"""Distiller scaffold (Plan 5 Phase B placeholder).

Plan 5's distillation loop will consume LLM calls (problem-pattern
synthesis, skill consolidation, etc.). The weekly cost ceiling for that
loop is enforced here via ``UsageTracker`` so a runaway batch cannot
drain the budget unnoticed.

This module is intentionally minimal: the full distiller is being
designed in parallel. Adding the cap check now (rather than bolting it on
later) prevents the original audit finding H5 — the in-memory counter
that process restart could bypass.
"""

from __future__ import annotations

from mahavishnu.distill.llm_usage import CostCeilingExceeded, UsageTracker


def build_default_tracker() -> UsageTracker:
    """Return a tracker honouring ``MAHAVISHNU_DISTILL_LLM_WEEKLY_CAP``.

    The distiller instantiates one tracker per run and passes it down to
    every LLM-bound call site. The env var lookup happens once here so
    future call sites do not have to repeat the precedence logic.
    """
    return UsageTracker.from_env()


def check_budget(tracker: UsageTracker) -> None:
    """Raise if the next LLM call would breach the weekly cap.

    Call sites invoke this *before* dispatching the LLM request so a
    refused call does not consume budget. The check is cheap (one JSON
    read under flock) and is the single chokepoint that Plan 5 phase B
    must route every LLM call through.
    """
    if tracker.remaining() <= 0:
        raise CostCeilingExceeded(
            current=tracker.current_count(),
            cap=tracker.weekly_cap,
            remaining=0,
        )


__all__ = ["CostCeilingExceeded", "UsageTracker", "build_default_tracker", "check_budget"]
