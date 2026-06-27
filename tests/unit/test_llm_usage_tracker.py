"""TDD tests for the file-backed LLM weekly cap (audit finding H5).

The current in-memory counter is bypassable by restarting the process. The
new ``UsageTracker`` writes a JSON file under ``~/.cache/mahavishnu/llm_usage.json``
protected by ``fcntl.flock`` so concurrent processes cannot exceed the cap
either.

These tests are RED at the time of writing — the implementation file
``mahavishnu/distill/llm_usage.py`` does not yet exist.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture
def usage_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect tracker storage to a temp file (do not touch real ~/.cache)."""
    target = tmp_path / "llm_usage.json"
    monkeypatch.setenv("MAHAVISHNU_LLM_USAGE_PATH", str(target))
    return target


@pytest.fixture
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> Callable[[datetime], None]:
    """Return a setter that injects ``datetime.now(UTC)`` into the tracker."""
    from mahavishnu.distill.llm_usage import UsageTracker

    holder: dict[str, datetime] = {"now": datetime(2026, 6, 27, 12, 0, 0, tzinfo=UTC)}
    monkeypatch.setattr(UsageTracker, "_now", staticmethod(lambda: holder["now"]))

    def _set(value: datetime) -> None:
        holder["now"] = value

    return _set


def test_increment_records_each_call(usage_path: Path) -> None:
    """Each ``record_call`` appends one entry to the underlying JSON."""
    from mahavishnu.distill.llm_usage import UsageTracker

    tracker = UsageTracker(weekly_cap=5)
    assert tracker.current_count() == 0

    tracker.record_call()
    tracker.record_call()
    tracker.record_call()

    assert tracker.current_count() == 3
    payload = json.loads(usage_path.read_text())
    assert isinstance(payload["calls"], list)
    assert len(payload["calls"]) == 3


def test_counter_persists_across_process_restart(usage_path: Path) -> None:
    """Reconstructing the tracker from the same file preserves prior calls."""
    from mahavishnu.distill.llm_usage import UsageTracker

    first = UsageTracker(weekly_cap=10)
    first.record_call()
    first.record_call()

    second = UsageTracker(weekly_cap=10)
    assert second.current_count() == 2

    second.record_call()
    third = UsageTracker(weekly_cap=10)
    assert third.current_count() == 3


def test_cap_enforcement_raises(usage_path: Path) -> None:
    """Exceeding the cap raises ``CostCeilingExceeded``."""
    from mahavishnu.distill.llm_usage import CostCeilingExceeded, UsageTracker

    tracker = UsageTracker(weekly_cap=2)
    tracker.record_call()
    tracker.record_call()

    with pytest.raises(CostCeilingExceeded):
        tracker.record_call()


def test_env_var_overrides_default_cap(
    usage_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``MAHAVISHNU_DISTILL_LLM_WEEKLY_CAP`` overrides the constructor arg."""
    from mahavishnu.distill.llm_usage import CostCeilingExceeded, UsageTracker

    monkeypatch.setenv("MAHAVISHNU_DISTILL_LLM_WEEKLY_CAP", "3")

    tracker = UsageTracker.from_env(weekly_cap_default=100)
    tracker.record_call()
    tracker.record_call()
    tracker.record_call()

    with pytest.raises(CostCeilingExceeded):
        tracker.record_call()


def test_default_cap_is_100_per_week(usage_path: Path) -> None:
    """Out-of-the-box cap is 100 calls per rolling 7-day window."""
    from mahavishnu.distill.llm_usage import UsageTracker

    tracker = UsageTracker.from_env()
    assert tracker.weekly_cap == 100
    assert tracker.window_days == 7


def test_rolling_window_drops_old_calls(
    usage_path: Path,
    frozen_now: Callable[[datetime], None],
) -> None:
    """Calls older than 7 days are excluded from the active count."""
    from mahavishnu.distill.llm_usage import UsageTracker

    frozen_now(datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC))
    tracker = UsageTracker(weekly_cap=5)
    tracker.record_call()
    tracker.record_call()
    assert tracker.current_count() == 2

    frozen_now(datetime(2026, 6, 9, 12, 0, 1, tzinfo=UTC))
    fresh = UsageTracker(weekly_cap=5)
    assert fresh.current_count() == 0
    assert fresh.remaining() == 5


def test_remaining_reports_remaining_budget(
    usage_path: Path,
) -> None:
    """``remaining()`` returns ``cap - current_count``, clamped at 0."""
    from mahavishnu.distill.llm_usage import UsageTracker

    tracker = UsageTracker(weekly_cap=4)
    assert tracker.remaining() == 4
    tracker.record_call()
    assert tracker.remaining() == 3


def test_corrupt_file_is_treated_as_empty(
    usage_path: Path,
) -> None:
    """A bad JSON file should not crash the tracker — treat as zeroed."""
    from mahavishnu.distill.llm_usage import UsageTracker

    usage_path.write_text("not-json")
    tracker = UsageTracker(weekly_cap=2)
    assert tracker.current_count() == 0
    tracker.record_call()
    assert tracker.current_count() == 1


def test_concurrent_processes_serialise_via_flock(
    usage_path: Path,
) -> None:
    """``record_call`` must take ``fcntl.flock`` to serialise writers."""
    import fcntl as _fcntl
    from unittest.mock import patch

    from mahavishnu.distill.llm_usage import UsageTracker

    captured: list[tuple[int, int]] = []
    real_flock = _fcntl.flock

    def spy_flock(fd: int, op: int) -> None:
        # ``fcntl.flock`` receives a raw file descriptor (int), not a
        # file-like object — record the int directly.
        captured.append((int(fd), op))
        real_flock(fd, op)

    tracker = UsageTracker(weekly_cap=5)

    with patch("mahavishnu.distill.llm_usage.fcntl.flock", side_effect=spy_flock):
        tracker.record_call()

    ops = [op for _fd, op in captured]
    assert _fcntl.LOCK_EX in ops
    assert _fcntl.LOCK_UN in ops
