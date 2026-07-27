"""Spec §14 success-criteria instrumentation.

Counts and surfaces:
- Per-tool call counts (powers the Crackerjack quality dashboard).
- ``attach_events`` — fires when a ``worker_revoke`` response carries
  an ``attach_command`` that the operator later runs (drives the
  "tmux-attached operator action" success criterion).
- ``pool_share`` — ratio of pool_route_execute / terminal_launch calls
  on Claude Code sessions that opt in to the new contract. The
  spec target is ≥45% (≥0.45). Captured as numerator/denominator plus
  the ratio for fast dashboard reads.

Crackerjack quality score (spec §14: "≥75 after rollout") is sourced
from ``crackerjack run --json`` and persisted to Dhara per the
project convention; it is surfaced via
``mcp__mahavishnu__get_observability_metrics`` — not via this class.
"""

from __future__ import annotations

from collections import defaultdict
import threading


class WorkerMetrics:
    """Thread-safe counters for the spec §14 success-criteria metrics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = defaultdict(int)
        self._attach_events: int = 0
        self._pool_share_num: int = 0
        self._pool_share_den: int = 0

    def record(self, tool_name: str) -> None:
        with self._lock:
            self._counts[tool_name] += 1
            self._counts["total"] += 1

    def record_attach(self) -> None:
        with self._lock:
            self._attach_events += 1

    def record_pool_share(self, *, pool_calls: int, terminal_calls: int) -> None:
        """Increment pool-share counters; ratio = pool / (pool + terminal)."""
        with self._lock:
            self._pool_share_num += pool_calls
            self._pool_share_den += pool_calls + terminal_calls

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            out: dict[str, object] = dict(self._counts)
            out["attach_events"] = self._attach_events
            out["pool_share_numerator"] = self._pool_share_num
            out["pool_share_denominator"] = self._pool_share_den
            ratio = self._pool_share_num / self._pool_share_den if self._pool_share_den > 0 else 0.0
            out["pool_share_ratio"] = ratio
            return out
