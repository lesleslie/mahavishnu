"""Unit tests for mahavishnu.core.loop_helpers — Phase 2 Task 2.4 exit criteria.

Covers the loop-until-dry contract spelled out in the module docstring and
the Phase 2 Exit Criteria in
``docs/plans/2026-07-11-ultracode-integration-wiring.md`` §5:

- ``detect_until_dry`` stops after K consecutive empty rounds (converged)
- ``detect_until_dry`` respects ``max_iterations`` (max_iterations stop)
- ``detect_until_dry`` dedupes findings via ``dedup_key``
- ``detect_until_dry`` captures ``scan_fn`` exceptions with partial findings
- ``detect_until_dry`` captures ``dedup_key`` exceptions with partial findings
- ``detect_until_dry`` enforces per-iteration timeout
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mahavishnu.core.loop_helpers import detect_until_dry

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _finding(id_value: Any, **extras: Any) -> dict[str, Any]:
    """Build a finding dict with the canonical ``id`` key plus optional extras."""
    return {"id": id_value, **extras}


# ---------------------------------------------------------------------------
# Task 2.4 exit criteria — convergence and cap
# ---------------------------------------------------------------------------


async def test_detect_until_dry_stops_after_k_empty() -> None:
    """A scanner returning [finding], [], [] converges after 3 iterations.

    With ``k_empty_rounds=2`` (default), the loop terminates after two
    consecutive empty rounds. The first iteration surfaces the only
    finding; iterations 2 and 3 are empty; iteration 3 trips the
    convergence threshold → ``stopped_reason == "converged"``.
    """
    calls = {"n": 0}

    async def scan_fn() -> list[dict[str, Any]]:
        calls["n"] += 1
        if calls["n"] == 1:
            return [_finding(1)]
        return []

    findings, metadata = await detect_until_dry(scan_fn)

    assert calls["n"] == 3, "wrapper should drive exactly 3 iterations"
    assert metadata["iterations"] == 3
    assert metadata["empty_rounds"] == 2
    assert metadata["stopped_reason"] == "converged"
    assert metadata["error"] is None
    assert metadata["exception"] is None
    assert findings == [_finding(1)]


async def test_detect_until_dry_respects_max_iterations() -> None:
    """A non-converging scanner is capped by ``max_iterations``.

    The scanner emits one fresh finding per iteration (never empty), so
    the convergence threshold is never reached. With ``max_iterations=3``
    the loop terminates on the iteration cap → ``stopped_reason ==
    "max_iterations"``. ``empty_rounds`` stays at 0 throughout.
    """
    calls = {"n": 0}

    async def scan_fn() -> list[dict[str, Any]]:
        calls["n"] += 1
        return [_finding(calls["n"])]

    findings, metadata = await detect_until_dry(scan_fn, max_iterations=3)

    assert calls["n"] == 3
    assert metadata["iterations"] == 3
    assert metadata["empty_rounds"] == 0
    assert metadata["stopped_reason"] == "max_iterations"
    assert metadata["error"] is None
    assert metadata["exception"] is None
    assert findings == [_finding(1), _finding(2), _finding(3)]


# ---------------------------------------------------------------------------
# Task 2.4 exit criteria — dedup
# ---------------------------------------------------------------------------


async def test_detect_until_dry_dedupes_via_dedup_key() -> None:
    """Intra-iteration duplicates collapse; only unique keys survive.

    The scanner returns three findings — two with id=1, one with id=2 —
    in a single iteration. The cumulative dedup set collapses the second
    id=1; only 2 unique findings reach ``all_findings``. The first-seen
    ordering is preserved (id=1 before id=2).
    """
    calls = {"n": 0}

    async def scan_fn() -> list[dict[str, Any]]:
        calls["n"] += 1
        if calls["n"] == 1:
            return [
                _finding(1, x="first"),
                _finding(1, x="dup"),
                _finding(2, x="third"),
            ]
        return []

    findings, metadata = await detect_until_dry(scan_fn)

    assert calls["n"] == 3  # converges after two empty rounds
    assert metadata["stopped_reason"] == "converged"
    assert len(findings) == 2
    # First-seen ordering: the "first" id=1 wins over the duplicate.
    assert findings[0] == _finding(1, x="first")
    assert findings[1] == _finding(2, x="third")


# ---------------------------------------------------------------------------
# Task 2.4 exit criteria — error paths
# ---------------------------------------------------------------------------


async def test_detect_until_dry_captures_scan_fn_exception() -> None:
    """``scan_fn`` raising on iteration 2 surfaces partial findings + error.

    Iteration 1 returns one finding (merged into ``all_findings``); the
    iteration-2 raise is captured into ``stopped_reason``, ``error``,
    and ``exception``. The wrapper does NOT propagate — callers see the
    partial findings with the error context attached.
    """
    calls = {"n": 0}

    async def scan_fn() -> list[dict[str, Any]]:
        calls["n"] += 1
        if calls["n"] == 1:
            return [_finding(1)]
        raise RuntimeError("scanner broke")

    findings, metadata = await detect_until_dry(scan_fn)

    assert calls["n"] == 2
    assert metadata["iterations"] == 2
    assert metadata["stopped_reason"] == "error"
    assert metadata["error"] is not None
    assert "scanner broke" in metadata["error"]
    assert metadata["exception"] is not None
    assert isinstance(metadata["exception"], RuntimeError)
    assert str(metadata["exception"]) == "scanner broke"
    # Partial findings from iteration 1 survive.
    assert findings == [_finding(1)]


async def test_detect_until_dry_captures_dedup_key_exception() -> None:
    """A finding missing ``"id"`` raises KeyError in ``dedup_key`` → error path.

    Same outcome shape as ``test_detect_until_dry_captures_scan_fn_exception``:
    partial findings (from earlier in the same iteration) are returned,
    ``stopped_reason == "error"``, and the KeyError is captured. The
    failing finding never reaches ``all_findings``.
    """
    calls = {"n": 0}

    async def scan_fn() -> list[dict[str, Any]]:
        calls["n"] += 1
        if calls["n"] == 1:
            # First finding is well-formed; second triggers KeyError.
            return [_finding(1, ok=True), {"no_id": True}]
        return []

    findings, metadata = await detect_until_dry(scan_fn)

    assert calls["n"] == 1
    assert metadata["iterations"] == 1
    assert metadata["stopped_reason"] == "error"
    assert metadata["error"] is not None
    assert "dedup_key raised" in metadata["error"]
    assert metadata["exception"] is not None
    assert isinstance(metadata["exception"], KeyError)
    # Partial findings from the same iteration are returned.
    assert findings == [_finding(1, ok=True)]


async def test_detect_until_dry_per_iteration_timeout() -> None:
    """A scanner that sleeps longer than ``per_iteration_timeout_seconds`` times out.

    With ``per_iteration_timeout_seconds=1.0`` and a scanner that sleeps
    5 seconds, ``asyncio.wait_for`` raises ``TimeoutError`` (aliased as
    ``asyncio.TimeoutError`` since Python 3.11). The wrapper captures
    the timeout, surfaces ``stopped_reason == "error"``, and returns.
    """
    async def slow_scan_fn() -> list[dict[str, Any]]:
        await asyncio.sleep(5)
        return [_finding(1)]

    findings, metadata = await detect_until_dry(
        slow_scan_fn,
        per_iteration_timeout_seconds=1.0,
    )

    assert metadata["iterations"] == 1
    assert metadata["stopped_reason"] == "error"
    assert metadata["error"] is not None
    assert "timed out" in metadata["error"]
    assert metadata["exception"] is not None
    assert isinstance(metadata["exception"], TimeoutError)
    # No findings — the slow iteration was terminated before completion.
    assert findings == []
