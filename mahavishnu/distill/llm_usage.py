"""File-backed weekly usage tracker for distillation LLM calls (audit H5).

Plan 5's distillation loop used an in-memory counter for its weekly LLM
cap, which a process restart could bypass. This module provides a
``UsageTracker`` that persists call timestamps as JSON to
``~/.cache/mahavishnu/llm_usage.json`` (overridable via
``MAHAVISHNU_LLM_USAGE_PATH``) and serialises writers with ``fcntl.flock``
so two processes cannot both cross the cap simultaneously.

Counter shape::

    {"calls": ["2026-06-27T12:00:00+00:00", ...]}

Stale entries (older than ``window_days``) are pruned on every read so
the on-disk file stays small. The rolling window is implemented with
``datetime.now(UTC)`` minus ``window_days``; the clock is injectable via
the ``_now`` class attribute so tests can freeze time deterministically.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
from typing import cast

from mahavishnu.core.json_state_store import locked_json_modify

# Default cap and rolling window — exported as constants so the runbook
# and tests reference the same numbers as the implementation.
DEFAULT_WEEKLY_CAP = 100
DEFAULT_WINDOW_DAYS = 7

# Env var names — kept stable for the runbook (H5) and config docs.
ENV_CAP = "MAHAVISHNU_DISTILL_LLM_WEEKLY_CAP"
ENV_PATH = "MAHAVISHNU_LLM_USAGE_PATH"
ENV_WINDOW = "MAHAVISHNU_DISTILL_LLM_WINDOW_DAYS"

# Cache directory fallback when ``MAHAVISHNU_LLM_USAGE_PATH`` is unset.
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "mahavishnu"
DEFAULT_USAGE_FILE = DEFAULT_CACHE_DIR / "llm_usage.json"


class CostCeilingExceeded(Exception):  # noqa: N818 — public name pinned by audit H5 contract
    """Raised when a record_call would breach the weekly LLM cap.

    Carries the current count, the cap, and the remaining budget so the
    CLI can surface actionable diagnostics (audit H5 acceptance criteria).
    """

    def __init__(self, *, current: int, cap: int, remaining: int) -> None:
        super().__init__(
            f"LLM weekly cap reached: {current}/{cap} calls in the last "
            f"{DEFAULT_WINDOW_DAYS} days (remaining={remaining}). "
            f"Override with {ENV_CAP} or wait for the rolling window to expire."
        )
        self.current = current
        self.cap = cap
        self.remaining = remaining


def _default_path() -> Path:
    """Resolve the on-disk path honouring ``MAHAVISHNU_LLM_USAGE_PATH``.

    Falls back to ``~/.cache/mahavishnu/llm_usage.json`` and creates the
    parent directory on first use. We intentionally do not raise if the
    cache directory cannot be created — the caller (UsageTracker.record_call)
    treats storage failure as a hard error so the operator notices.
    """
    override = os.environ.get(ENV_PATH)
    if override:
        return Path(override)
    DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_USAGE_FILE


class UsageTracker:
    """Rolling-window LLM call counter, persisted as JSON under fcntl lock.

    Construct directly with a fixed cap, or use ``UsageTracker.from_env()``
    to honour ``MAHAVISHNU_DISTILL_LLM_WEEKLY_CAP`` (H5 acceptance
    criterion: env var override must take precedence over the constructor
    default).

    Concurrency: every mutating operation (``record_call``) opens the file,
    takes an exclusive ``fcntl.flock``, reads the current payload,
    prunes stale entries, checks the cap, appends the new timestamp, and
    flushes — all under the lock. The lock is released in the ``finally``
    block so a crashed reader does not deadlock the next writer.
    """

    # Injectable clock for deterministic tests. Defaults to UTC now.
    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    def __init__(
        self,
        *,
        weekly_cap: int = DEFAULT_WEEKLY_CAP,
        window_days: int = DEFAULT_WINDOW_DAYS,
        path: Path | None = None,
    ) -> None:
        if weekly_cap < 0:
            raise ValueError("weekly_cap must be >= 0")
        if window_days <= 0:
            raise ValueError("window_days must be > 0")

        self.weekly_cap = weekly_cap
        self.window_days = window_days
        self.path = Path(path) if path is not None else _default_path()

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        *,
        weekly_cap_default: int = DEFAULT_WEEKLY_CAP,
        window_days_default: int = DEFAULT_WINDOW_DAYS,
        path: Path | None = None,
    ) -> UsageTracker:
        """Build a tracker honouring ``MAHAVISHNU_DISTILL_LLM_WEEKLY_CAP``.

        Env var precedence (highest first):
            1. ``MAHAVISHNU_DISTILL_LLM_WEEKLY_CAP`` — overrides cap
            2. ``MAHAVISHNU_DISTILL_LLM_WINDOW_DAYS`` — overrides window
            3. Constructor defaults
        """
        cap_env = os.environ.get(ENV_CAP)
        window_env = os.environ.get(ENV_WINDOW)

        cap = int(cap_env) if cap_env else weekly_cap_default
        window = int(window_env) if window_env else window_days_default

        return cls(weekly_cap=cap, window_days=window, path=path)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _prune(self, payload: dict[str, object], cutoff: datetime) -> None:
        """Drop call timestamps strictly older than ``cutoff`` in place."""
        calls = payload.get("calls", [])
        if not isinstance(calls, list):
            payload["calls"] = []
            return
        kept: list[str] = []
        for entry in calls:
            if not isinstance(entry, str):
                continue
            try:
                ts = datetime.fromisoformat(entry)
            except ValueError:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if ts >= cutoff:
                kept.append(entry)
        payload["calls"] = kept

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def current_count(self) -> int:
        """Return the number of calls within the rolling window.

        Persists the prune back to disk so the on-disk file reflects
        the active window even if no new call is recorded.

        Corrupt JSON is treated as empty (legacy behaviour — the
        distiller shouldn't crash on a process-killed-mid-write file).
        """
        cutoff = self._now() - timedelta(days=self.window_days)

        def modifier(data):
            payload: dict[str, object] = data if data is not None else {"calls": []}
            self._prune(payload, cutoff)
            return payload

        try:
            new_data = locked_json_modify(
                self.path, modifier, default_factory=lambda: {"calls": []}
            )
        except json.JSONDecodeError:
            return 0
        calls = new_data.get("calls", [])
        return len(calls) if isinstance(calls, list) else 0

    def remaining(self) -> int:
        """Return ``cap - current_count``, clamped at zero."""
        return max(0, self.weekly_cap - self.current_count())

    def record_call(self) -> None:
        """Append a timestamped entry, raising if it would breach the cap.

        Raises ``CostCeilingExceeded`` when the call would push the count
        above ``weekly_cap``. The check happens BEFORE the append so a
        failed call does not consume budget.

        Corrupt JSON is treated as empty: the file is unlinked and the
        call is recorded against a fresh empty state. This preserves
        the legacy behaviour where a process-killed-mid-write file
        would not crash subsequent operations.
        """
        now = self._now()
        cutoff = now - timedelta(days=self.window_days)

        def modifier(data):
            payload: dict[str, object] = data if data is not None else {"calls": []}
            self._prune(payload, cutoff)
            calls_raw = payload.get("calls", [])
            calls: list[str] = cast("list[str]", calls_raw) if isinstance(calls_raw, list) else []
            if len(calls) >= self.weekly_cap:
                raise CostCeilingExceeded(
                    current=len(calls),
                    cap=self.weekly_cap,
                    remaining=0,
                )
            calls.append(now.isoformat())
            payload["calls"] = calls
            return payload

        try:
            locked_json_modify(self.path, modifier, default_factory=lambda: {"calls": []})
        except json.JSONDecodeError:
            # Quarantine the corrupt file and retry — the modifier
            # will see default_factory's empty payload.
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            locked_json_modify(self.path, modifier, default_factory=lambda: {"calls": []})
