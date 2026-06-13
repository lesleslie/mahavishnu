"""Comprehensive unit tests for mahavishnu/websocket/rate_limiter.py."""

from __future__ import annotations

import importlib
import logging
import sys
from types import ModuleType
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Import the rate_limiter module under its canonical package name so that
# coverage.py can find it. We pre-create the parent package as a stub to
# avoid executing mahavishnu/websocket/__init__.py (which imports
# prometheus_client-backed metrics that clash on the default registry).
# ---------------------------------------------------------------------------

_RL_PATH = "mahavishnu.websocket.rate_limiter"
if _RL_PATH in sys.modules:
    rl_mod = sys.modules[_RL_PATH]
else:
    # Stub parent packages so importing the submodule doesn't execute
    # the websocket __init__ (which imports the prometheus metrics).
    if "mahavishnu" not in sys.modules:
        sys.modules["mahavishnu"] = ModuleType("mahavishnu")
    if "mahavishnu.websocket" not in sys.modules:
        import os
        # __file__ is tests/unit/...; go up 3 levels to repo root
        repo_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        ws_pkg = ModuleType("mahavishnu.websocket")
        # Set __path__ to the real directory so submodule imports work
        ws_pkg.__path__ = [os.path.join(repo_root, "mahavishnu", "websocket")]
        sys.modules["mahavishnu.websocket"] = ws_pkg
    rl_mod = importlib.import_module(_RL_PATH)

RateLimitResult = rl_mod.RateLimitResult
TokenBucketRateLimiter = rl_mod.TokenBucketRateLimiter
get_rate_limiter = rl_mod.get_rate_limiter
reset_rate_limiter = rl_mod.reset_rate_limiter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeTime:
    """A fake `time` module replacement for deterministic tests."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.current = start

    def time(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


@pytest.fixture
def fake_time() -> _FakeTime:
    """Provide a fake `time` module patched into the rate limiter module.

    The source module calls ``time.time()`` directly, so we swap the
    ``time`` attribute on the module for an object that exposes
    a ``time()`` method.
    """
    fake = _FakeTime()

    class _FakeTimeModule:
        @staticmethod
        def time() -> float:
            return fake.time()

    with patch.object(rl_mod, "time", _FakeTimeModule):
        yield fake


@pytest.fixture(autouse=True)
def _patch_module_logger() -> None:
    """Suppress noisy logger output during tests."""
    rl_mod.logger.setLevel(logging.CRITICAL)


# ---------------------------------------------------------------------------
# RateLimitResult dataclass
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRateLimitResult:
    def test_defaults(self) -> None:
        result = RateLimitResult()
        assert result.allowed is True
        assert result.retry_after == 0.0
        assert result.tokens_remaining == 0.0
        assert result.limited is False

    def test_custom_values(self) -> None:
        result = RateLimitResult(
            allowed=False,
            retry_after=1.5,
            tokens_remaining=0.25,
            limited=True,
        )
        assert result.allowed is False
        assert result.retry_after == 1.5
        assert result.tokens_remaining == 0.25
        assert result.limited is True


# ---------------------------------------------------------------------------
# TokenBucketRateLimiter: init & defaults
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTokenBucketRateLimiterInit:
    def test_defaults(self) -> None:
        limiter = TokenBucketRateLimiter()
        assert limiter.rate == 100.0
        # burst_size defaults to rate * 1.5
        assert limiter.burst_size == 150.0
        assert limiter.cleanup_interval == 300.0
        assert limiter._tokens == {}
        assert limiter._last_update == {}

    def test_custom_rate_only(self) -> None:
        limiter = TokenBucketRateLimiter(rate=50.0)
        assert limiter.rate == 50.0
        assert limiter.burst_size == 75.0

    def test_custom_burst_size(self) -> None:
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=20.0)
        assert limiter.burst_size == 20.0

    def test_custom_cleanup_interval(self) -> None:
        limiter = TokenBucketRateLimiter(rate=10.0, cleanup_interval=60.0)
        assert limiter.cleanup_interval == 60.0


# ---------------------------------------------------------------------------
# check() — happy path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckHappyPath:
    def test_new_connection_starts_with_full_bucket(self, fake_time: _FakeTime) -> None:
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=10.0)
        result = limiter.check("conn1")
        assert result.allowed is True
        assert result.limited is False
        assert result.tokens_remaining == 9.0

    def test_multiple_checks_decrement_tokens(self, fake_time: _FakeTime) -> None:
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=5.0)
        results = [limiter.check("conn1") for _ in range(3)]
        assert all(r.allowed for r in results)
        # 5 - 3 = 2
        assert results[-1].tokens_remaining == 2.0

    def test_independent_buckets_per_connection(self, fake_time: _FakeTime) -> None:
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=10.0)
        r1 = limiter.check("conn_a")
        r2 = limiter.check("conn_b")
        # Both started at full bucket
        assert r1.tokens_remaining == 9.0
        assert r2.tokens_remaining == 9.0

    def test_refill_between_calls(self, fake_time: _FakeTime) -> None:
        limiter = TokenBucketRateLimiter(rate=2.0, burst_size=2.0)
        r1 = limiter.check("c")  # bucket = 2, consume 1, leaves 1
        fake_time.advance(0.5)  # refill 1 token
        r2 = limiter.check("c")  # bucket should be 1 + 1 = 2, consume 1, leaves 1
        assert r1.allowed is True
        assert r2.allowed is True
        assert r1.tokens_remaining == 1.0
        assert r2.tokens_remaining == 1.0

    def test_refill_caps_at_burst(self, fake_time: _FakeTime) -> None:
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=5.0)
        r1 = limiter.check("c")  # tokens: 5 - 1 = 4
        fake_time.advance(100.0)  # many seconds pass
        r2 = limiter.check("c")
        # Capped at burst_size - 1
        assert r2.tokens_remaining == 4.0

    def test_returns_dataclass_instance(self, fake_time: _FakeTime) -> None:
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=10.0)
        result = limiter.check("c")
        assert isinstance(result, RateLimitResult)


# ---------------------------------------------------------------------------
# check() — rate-limited path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckRateLimited:
    def test_burst_exhausted_returns_limited(self, fake_time: _FakeTime) -> None:
        limiter = TokenBucketRateLimiter(rate=1.0, burst_size=2.0)
        limiter.check("c")  # 1 left
        limiter.check("c")  # 0 left
        result = limiter.check("c")
        assert result.allowed is False
        assert result.limited is True
        assert result.retry_after > 0.0
        assert result.tokens_remaining == 0.0

    def test_retry_after_uses_rate(self, fake_time: _FakeTime) -> None:
        limiter = TokenBucketRateLimiter(rate=2.0, burst_size=1.0)
        limiter.check("c")  # consume the only token
        result = limiter.check("c")
        # Need 1 token at 2 tokens/sec = 0.5s
        assert result.retry_after == 0.5

    def test_zero_rate_yields_infinite_retry(self, fake_time: _FakeTime) -> None:
        limiter = TokenBucketRateLimiter(rate=0.0, burst_size=0.0)
        result = limiter.check("c")
        # burst_size = 0, so first check has 0 tokens => limited
        assert result.allowed is False
        assert result.retry_after == float("inf")

    def test_rate_limit_event_recorded(self, fake_time: _FakeTime) -> None:
        limiter = TokenBucketRateLimiter(rate=1.0, burst_size=1.0)
        limiter.check("c")  # consume
        limiter.check("c")  # limited
        assert "c" in limiter._rate_limit_events
        assert len(limiter._rate_limit_events["c"]) == 1


# ---------------------------------------------------------------------------
# _log_rate_limit (throttled)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLogRateLimit:
    def test_first_event_in_window_logs(
        self,
        fake_time: _FakeTime,
    ) -> None:
        rl_mod.logger.setLevel(logging.DEBUG)
        with patch.object(rl_mod.logger, "warning") as warn:
            limiter = TokenBucketRateLimiter(rate=1.0, burst_size=1.0)
            limiter.check("c")  # consume
            warn.reset_mock()
            limiter.check("c")  # limited
        # only one event => log emitted
        assert warn.call_count == 1
        assert "Rate limit applied" in warn.call_args.args[0]

    def test_subsequent_events_within_window_skip_log(
        self,
        fake_time: _FakeTime,
    ) -> None:
        rl_mod.logger.setLevel(logging.DEBUG)
        with patch.object(rl_mod.logger, "warning") as warn:
            limiter = TokenBucketRateLimiter(rate=1.0, burst_size=1.0)
            limiter.check("c")
            warn.reset_mock()
            limiter.check("c")  # 1st event - logs
            warn.reset_mock()
            limiter.check("c")  # 2nd event within 1s - skipped
        # 2 events in window => no log
        assert warn.call_count == 0

    def test_event_after_window_logs_again(
        self,
        fake_time: _FakeTime,
    ) -> None:
        # Use rate=0 so refill never restores tokens. The connection
        # is permanently limited after the first check, allowing us
        # to test the time-window filtering in _log_rate_limit.
        rl_mod.logger.setLevel(logging.DEBUG)
        with patch.object(rl_mod.logger, "warning") as warn:
            limiter = TokenBucketRateLimiter(
                rate=0.0, burst_size=1.0, cleanup_interval=10.0
            )
            limiter.check("c")  # consume the single token
            limiter.check("c")  # 1st event - logs (1 in window)
            warn.reset_mock()
            limiter.check("c")  # 2nd event within 1s - skipped
            assert warn.call_count == 0
            # Advance past the 1s window for ALL prior events. With
            # rate=0 no refill happens, so the connection stays limited.
            fake_time.advance(2.0)
            warn.reset_mock()
            limiter.check("c")  # 3rd event, new window - should log
        assert warn.call_count == 1
        assert "Rate limit applied" in warn.call_args.args[0]


# ---------------------------------------------------------------------------
# _maybe_cleanup / _cleanup_idle_buckets
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCleanup:
    def test_cleanup_skipped_within_interval(self, fake_time: _FakeTime) -> None:
        limiter = TokenBucketRateLimiter(
            rate=10.0, burst_size=10.0, cleanup_interval=100.0
        )
        limiter.check("c")
        # advance less than cleanup_interval
        fake_time.advance(50.0)
        limiter._maybe_cleanup()
        # bucket still present
        assert "c" in limiter._tokens

    def test_cleanup_runs_after_interval(self, fake_time: _FakeTime) -> None:
        limiter = TokenBucketRateLimiter(
            rate=10.0, burst_size=10.0, cleanup_interval=10.0
        )
        limiter.check("c1")
        limiter.check("c2")
        # advance beyond cleanup_interval
        fake_time.advance(11.0)
        limiter._maybe_cleanup()
        # both should be cleaned up
        assert "c1" not in limiter._tokens
        assert "c2" not in limiter._tokens

    def test_cleanup_does_not_remove_recent_buckets(
        self, fake_time: _FakeTime
    ) -> None:
        limiter = TokenBucketRateLimiter(
            rate=10.0, burst_size=10.0, cleanup_interval=10.0
        )
        limiter.check("c1")
        fake_time.advance(11.0)
        limiter.check("c2")  # recent
        fake_time.advance(0.001)
        limiter._maybe_cleanup()
        assert "c1" not in limiter._tokens
        assert "c2" in limiter._tokens

    def test_cleanup_removes_rate_limit_events(self, fake_time: _FakeTime) -> None:
        limiter = TokenBucketRateLimiter(
            rate=1.0, burst_size=1.0, cleanup_interval=10.0
        )
        limiter.check("c")
        limiter.check("c")  # adds event
        assert "c" in limiter._rate_limit_events
        fake_time.advance(11.0)
        limiter._maybe_cleanup()
        assert "c" not in limiter._rate_limit_events

    def test_cleanup_skips_when_no_idle(self, fake_time: _FakeTime) -> None:
        # No buckets, no logging of "Cleaned up"
        limiter = TokenBucketRateLimiter(cleanup_interval=1.0)
        fake_time.advance(2.0)
        limiter._maybe_cleanup()
        # No exceptions, no buckets
        assert limiter._tokens == {}


# ---------------------------------------------------------------------------
# remove_connection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveConnection:
    def test_remove_existing(self, fake_time: _FakeTime) -> None:
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=10.0)
        limiter.check("c1")
        limiter.check("c2")
        limiter.remove_connection("c1")
        assert "c1" not in limiter._tokens
        assert "c1" not in limiter._last_update
        assert "c1" not in limiter._rate_limit_events
        assert "c2" in limiter._tokens

    def test_remove_nonexistent_is_noop(self, fake_time: _FakeTime) -> None:
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=10.0)
        # Should not raise
        limiter.remove_connection("nonexistent")

    def test_remove_does_not_affect_other_data(self, fake_time: _FakeTime) -> None:
        limiter = TokenBucketRateLimiter(rate=1.0, burst_size=1.0)
        limiter.check("c")
        limiter.check("c")  # triggers event
        assert len(limiter._rate_limit_events["c"]) == 1
        limiter.remove_connection("c")
        assert "c" not in limiter._tokens
        assert "c" not in limiter._rate_limit_events


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetStats:
    def test_global_empty(self) -> None:
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=10.0)
        stats = limiter.get_stats()
        assert stats["total_connections"] == 0
        assert stats["rate"] == 10.0
        assert stats["burst_size"] == 10.0
        assert stats["rate_limit_events_last_minute"] == 0
        assert stats["cleanup_interval"] == 300.0
        # When no connections, average_tokens = burst_size
        assert stats["average_tokens"] == 10.0

    def test_global_with_connections(self, fake_time: _FakeTime) -> None:
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=10.0)
        limiter.check("c1")
        limiter.check("c2")
        stats = limiter.get_stats()
        assert stats["total_connections"] == 2
        # Average tokens = (9 + 9) / 2 = 9.0
        assert stats["average_tokens"] == 9.0

    def test_global_counts_recent_rate_limit_events(
        self, fake_time: _FakeTime
    ) -> None:
        limiter = TokenBucketRateLimiter(rate=1.0, burst_size=1.0)
        limiter.check("c1")
        limiter.check("c1")  # limited
        limiter.check("c2")
        limiter.check("c2")  # limited
        stats = limiter.get_stats()
        assert stats["rate_limit_events_last_minute"] == 2

    def test_specific_connection_existing(self, fake_time: _FakeTime) -> None:
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=10.0)
        limiter.check("c1")
        stats = limiter.get_stats("c1")
        assert stats["connection_id"] == "c1"
        assert stats["tokens"] == 9.0
        assert stats["burst_size"] == 10.0
        assert stats["rate"] == 10.0
        assert stats["rate_limit_events_last_minute"] == 0

    def test_specific_connection_nonexistent_uses_defaults(
        self, fake_time: _FakeTime
    ) -> None:
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=10.0)
        stats = limiter.get_stats("nope")
        # Defaults to burst_size tokens and current time for last_update
        assert stats["tokens"] == 10.0
        assert stats["rate_limit_events_last_minute"] == 0

    def test_specific_connection_recent_event_count(
        self, fake_time: _FakeTime
    ) -> None:
        limiter = TokenBucketRateLimiter(rate=1.0, burst_size=1.0)
        limiter.check("c")
        limiter.check("c")  # limited
        limiter.check("c")  # limited
        stats = limiter.get_stats("c")
        assert stats["rate_limit_events_last_minute"] == 2

    def test_specific_connection_filters_old_events(
        self, fake_time: _FakeTime
    ) -> None:
        limiter = TokenBucketRateLimiter(rate=1.0, burst_size=1.0)
        limiter.check("c")
        limiter.check("c")  # limited at t0
        # Move forward past 60s
        fake_time.advance(70.0)
        stats = limiter.get_stats("c")
        assert stats["rate_limit_events_last_minute"] == 0


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReset:
    def test_reset_specific_connection(self, fake_time: _FakeTime) -> None:
        limiter = TokenBucketRateLimiter(rate=1.0, burst_size=5.0)
        limiter.check("c1")
        limiter.check("c2")
        limiter.reset("c1")
        # c1 back to burst_size
        assert limiter._tokens["c1"] == 5.0
        # c2 untouched
        assert limiter._tokens["c2"] == 4.0

    def test_reset_specific_clears_events(self, fake_time: _FakeTime) -> None:
        limiter = TokenBucketRateLimiter(rate=1.0, burst_size=1.0)
        limiter.check("c")
        limiter.check("c")
        assert "c" in limiter._rate_limit_events
        limiter.reset("c")
        assert "c" not in limiter._rate_limit_events

    def test_reset_all(self, fake_time: _FakeTime) -> None:
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=10.0)
        limiter.check("c1")
        limiter.check("c2")
        limiter.reset()
        assert limiter._tokens == {}
        assert limiter._last_update == {}
        # defaultdict pop returns None for missing key, but the .clear()
        # on a defaultdict leaves it empty (not a fresh default)
        assert len(limiter._rate_limit_events) == 0

    def test_reset_unknown_connection_creates_entry(
        self, fake_time: _FakeTime
    ) -> None:
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=10.0)
        limiter.reset("brand_new")
        assert "brand_new" in limiter._tokens
        assert limiter._tokens["brand_new"] == 10.0


# ---------------------------------------------------------------------------
# get_rate_limiter / reset_rate_limiter (module-level singleton)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModuleLevelSingleton:
    def test_get_rate_limiter_creates(self) -> None:
        reset_rate_limiter()
        try:
            limiter = get_rate_limiter(rate=42.0, burst_size=50.0)
            assert isinstance(limiter, TokenBucketRateLimiter)
            assert limiter.rate == 42.0
            assert limiter.burst_size == 50.0
        finally:
            reset_rate_limiter()

    def test_get_rate_limiter_returns_singleton(self) -> None:
        reset_rate_limiter()
        try:
            first = get_rate_limiter(rate=10.0)
            second = get_rate_limiter(rate=999.0)  # ignored
            assert first is second
            assert first.rate == 10.0
        finally:
            reset_rate_limiter()

    def test_get_rate_limiter_uses_defaults(self) -> None:
        reset_rate_limiter()
        try:
            limiter = get_rate_limiter()
            assert limiter.rate == 100.0
            assert limiter.burst_size == 150.0
        finally:
            reset_rate_limiter()

    def test_reset_rate_limiter_clears_singleton(self) -> None:
        reset_rate_limiter()
        first = get_rate_limiter(rate=10.0)
        reset_rate_limiter()
        second = get_rate_limiter(rate=20.0)
        assert first is not second
        assert second.rate == 20.0
        reset_rate_limiter()

    def test_burst_size_none_uses_rate_times_1_5(self) -> None:
        reset_rate_limiter()
        try:
            limiter = get_rate_limiter(rate=20.0, burst_size=None)
            assert limiter.burst_size == 30.0
        finally:
            reset_rate_limiter()
