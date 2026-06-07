"""Unit tests for mahavishnu/websocket/rate_limiter.py.

Covers the TokenBucketRateLimiter algorithm, RateLimitResult dataclass,
module-level singleton helpers, and the per-connection rate-limit lifecycle.
Time is injected via patch to keep the tests deterministic.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mahavishnu.websocket.rate_limiter import (
    RateLimitResult,
    TokenBucketRateLimiter,
    get_rate_limiter,
    reset_rate_limiter,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def fake_time():
    """Patch time.time() so token-bucket math is deterministic.

    Yields a list whose element 0 is the current "fake" timestamp. Tests can
    advance the clock by assigning to fake_time[0].
    """
    fake = [1_000_000.0]
    with patch("mahavishnu.websocket.rate_limiter.time.time", side_effect=lambda: fake[0]):
        yield fake


@pytest.fixture
def limiter():
    """A small, deterministic rate limiter (rate=2, burst=4)."""
    return TokenBucketRateLimiter(rate=2.0, burst_size=4.0, cleanup_interval=300.0)


# =============================================================================
# RateLimitResult Tests
# =============================================================================


class TestRateLimitResult:
    """Tests for the RateLimitResult dataclass."""

    def test_defaults(self):
        """Default values are permissive (not limited, allowed)."""
        result = RateLimitResult()

        assert result.allowed is True
        assert result.retry_after == 0.0
        assert result.tokens_remaining == 0.0
        assert result.limited is False

    def test_construction_with_values(self):
        """Construction accepts all four fields."""
        result = RateLimitResult(
            allowed=False,
            retry_after=1.5,
            tokens_remaining=0.0,
            limited=True,
        )

        assert result.allowed is False
        assert result.retry_after == 1.5
        assert result.tokens_remaining == 0.0
        assert result.limited is True

    def test_allowed_and_limited_are_independent(self):
        """`allowed` and `limited` can be set independently."""
        result = RateLimitResult(allowed=True, limited=True)

        assert result.allowed is True
        assert result.limited is True


# =============================================================================
# TokenBucketRateLimiter Construction Tests
# =============================================================================


class TestTokenBucketRateLimiterInit:
    """Tests for TokenBucketRateLimiter construction."""

    def test_default_burst_size_is_rate_times_one_point_five(self):
        """When burst_size is None the default is 1.5x the rate."""
        limiter = TokenBucketRateLimiter(rate=10.0)

        assert limiter.rate == 10.0
        assert limiter.burst_size == 15.0

    def test_explicit_burst_size_is_preserved(self):
        """Explicit burst_size overrides the default heuristic."""
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=42.0)

        assert limiter.burst_size == 42.0

    def test_buckets_and_counters_start_empty(self):
        """Internal state starts empty (no connections tracked)."""
        limiter = TokenBucketRateLimiter(rate=100.0)

        assert limiter._tokens == {}
        assert limiter._last_update == {}

    def test_custom_cleanup_interval_is_stored(self):
        """cleanup_interval is stored on the instance."""
        limiter = TokenBucketRateLimiter(rate=10.0, cleanup_interval=12.5)

        assert limiter.cleanup_interval == 12.5


# =============================================================================
# TokenBucketRateLimiter.check() Tests
# =============================================================================


class TestTokenBucketRateLimiterCheck:
    """Tests for the core check() rate-limit algorithm."""

    def test_first_call_creates_full_bucket_and_allows(self, limiter, fake_time):
        """First message for a new connection starts with a full bucket."""
        result = limiter.check("conn-1")

        assert result.allowed is True
        assert result.limited is False
        assert "conn-1" in limiter._tokens
        assert "conn-1" in limiter._last_update

    def test_consume_one_token_per_allowed_call(self, limiter, fake_time):
        """Each allowed check decrements the bucket by exactly one token."""
        first = limiter.check("conn-1")
        second = limiter.check("conn-1")
        third = limiter.check("conn-1")
        fourth = limiter.check("conn-1")

        # burst_size = 4 → first four calls allowed
        assert first.allowed is True
        assert second.allowed is True
        assert third.allowed is True
        assert fourth.allowed is True

        # Internal bucket is now drained to ~0
        assert limiter._tokens["conn-1"] == pytest.approx(0.0)

    def test_fifth_call_is_rate_limited(self, limiter, fake_time):
        """Drained bucket blocks the next message."""
        for _ in range(4):
            limiter.check("conn-1")

        result = limiter.check("conn-1")

        assert result.allowed is False
        assert result.limited is True
        assert result.retry_after > 0
        assert "conn-1" in limiter._rate_limit_events

    def test_tokens_replenish_over_time(self, limiter, fake_time):
        """Tokens are added based on elapsed seconds × rate."""
        # Drain the bucket
        for _ in range(4):
            limiter.check("conn-1")

        assert limiter._tokens["conn-1"] == pytest.approx(0.0)

        # Advance clock by 1 second → adds rate (2) tokens, capped at burst (4)
        fake_time[0] += 1.0
        result = limiter.check("conn-1")

        assert result.allowed is True
        # After consuming 1 token: 2 - 1 = 1
        assert limiter._tokens["conn-1"] == pytest.approx(1.0)

    def test_tokens_capped_at_burst_size(self, limiter, fake_time):
        """Refill never exceeds burst_size, even after a long idle period."""
        limiter.check("conn-1")  # bucket = 3 (4 - 1)
        fake_time[0] += 100.0  # would add 200 tokens, but cap at 4

        result = limiter.check("conn-1")

        assert result.allowed is True
        # The internal refill is capped at burst_size
        assert limiter._tokens["conn-1"] <= limiter.burst_size

    def test_separate_connections_have_separate_buckets(self, limiter, fake_time):
        """Per-connection isolation - draining A does not affect B."""
        for _ in range(4):
            limiter.check("conn-A")
        # conn-A is now drained
        blocked = limiter.check("conn-A")
        assert blocked.allowed is False

        # conn-B still has a full bucket
        allowed = limiter.check("conn-B")
        assert allowed.allowed is True

    def test_retry_after_inversely_proportional_to_rate(self, fake_time):
        """A higher rate yields a shorter retry_after for the same deficit."""
        slow = TokenBucketRateLimiter(rate=1.0, burst_size=2.0)
        fast = TokenBucketRateLimiter(rate=10.0, burst_size=2.0)

        # Drain both
        for _ in range(2):
            slow.check("c")
            fast.check("c")

        slow_blocked = slow.check("c")
        fast_blocked = fast.check("c")

        assert slow_blocked.allowed is False
        assert fast_blocked.allowed is False
        # fast (rate 10) should report a much smaller retry_after
        assert fast_blocked.retry_after < slow_blocked.retry_after

    def test_zero_rate_yields_infinite_retry_after(self, fake_time):
        """With rate=0 a blocked request has retry_after = inf."""
        limiter = TokenBucketRateLimiter(rate=0.0, burst_size=1.0)
        limiter.check("conn")  # consume the only token

        result = limiter.check("conn")

        assert result.allowed is False
        assert result.retry_after == float("inf")

    def test_check_returns_correct_tokens_remaining(self, limiter, fake_time):
        """tokens_remaining reflects the bucket after the check."""
        result = limiter.check("conn")

        # burst 4 - 1 = 3
        assert result.tokens_remaining == pytest.approx(3.0)

    def test_idle_connection_retains_state_across_advance(self, limiter, fake_time):
        """An idle connection that returns later still has a bucket entry."""
        limiter.check("conn-1")
        assert "conn-1" in limiter._tokens

        # Advance time well past cleanup interval
        fake_time[0] += limiter.cleanup_interval + 10

        result = limiter.check("conn-1")
        assert result.allowed is True  # bucket refilled, not cleaned up yet


# =============================================================================
# TokenBucketRateLimiter Lifecycle Tests
# =============================================================================


class TestTokenBucketRateLimiterLifecycle:
    """Tests for remove_connection, reset, and cleanup behavior."""

    def test_remove_connection_clears_state(self, limiter):
        """remove_connection() deletes all tracking for a connection."""
        limiter.check("conn-1")
        limiter.check("conn-2")
        assert "conn-1" in limiter._tokens

        limiter.remove_connection("conn-1")

        assert "conn-1" not in limiter._tokens
        assert "conn-1" not in limiter._last_update
        assert "conn-1" not in limiter._rate_limit_events
        # conn-2 is unaffected
        assert "conn-2" in limiter._tokens

    def test_remove_connection_is_idempotent(self, limiter):
        """Removing an unknown connection is a no-op (no exception)."""
        limiter.remove_connection("never-existed")
        # No assertion needed - just verifying no exception

    def test_reset_specific_connection_restores_full_bucket(self, limiter, fake_time):
        """reset(id) refills a single connection's bucket."""
        for _ in range(4):
            limiter.check("conn-1")
        assert limiter._tokens["conn-1"] == pytest.approx(0.0)

        limiter.reset("conn-1")

        assert limiter._tokens["conn-1"] == limiter.burst_size

    def test_reset_all_clears_everything(self, limiter):
        """reset() with no args clears all connection state."""
        limiter.check("a")
        limiter.check("b")
        limiter.check("c")
        assert len(limiter._tokens) == 3

        limiter.reset()

        assert limiter._tokens == {}
        assert limiter._last_update == {}
        assert dict(limiter._rate_limit_events) == {}

    def test_cleanup_idle_buckets_only_removes_idle(self, limiter, fake_time):
        """Idle connections past cutoff are removed; active ones are kept."""
        limiter.check("idle")
        limiter.check("active")

        # Push 'idle' far in the past
        limiter._last_update["idle"] = fake_time[0] - (limiter.cleanup_interval + 1)
        # 'active' is at the current fake time (set by its own check)
        assert limiter._last_update["active"] == fake_time[0]

        # Force cleanup by manipulating _last_cleanup to be old
        limiter._last_cleanup = fake_time[0] - limiter.cleanup_interval - 1
        limiter.check("trigger")  # triggers _maybe_cleanup → _cleanup_idle_buckets

        assert "idle" not in limiter._tokens
        assert "active" in limiter._tokens
        assert "trigger" in limiter._tokens

    def test_maybe_cleanup_skips_when_recent(self, limiter, fake_time):
        """Cleanup is throttled - it does not run more than once per interval."""
        # First call right after init: _last_cleanup is the real time.time()
        # We just check that after a fresh limiter, no cleanup fires.
        fake_time[0] = 2_000_000.0
        limiter._last_cleanup = fake_time[0]  # pretend we just ran it
        limiter._tokens["conn"] = 0.0
        limiter._last_update["conn"] = 0.0  # ancient

        limiter._maybe_cleanup()

        # No cleanup ran because we just ran it
        assert "conn" in limiter._tokens


# =============================================================================
# TokenBucketRateLimiter.get_stats() Tests
# =============================================================================


class TestTokenBucketRateLimiterStats:
    """Tests for get_stats() output."""

    def test_global_stats_with_no_connections(self, limiter, fake_time):
        """Empty limiter reports zero connections and a sane average."""
        stats = limiter.get_stats()

        assert stats["total_connections"] == 0
        assert stats["rate"] == limiter.rate
        assert stats["burst_size"] == limiter.burst_size
        assert stats["cleanup_interval"] == limiter.cleanup_interval
        assert stats["rate_limit_events_last_minute"] == 0
        # average_tokens falls back to burst_size when there are no connections
        assert stats["average_tokens"] == limiter.burst_size

    def test_global_stats_with_connections(self, limiter, fake_time):
        """Global stats aggregate connection count and recent events."""
        limiter.check("a")
        limiter.check("b")
        # Trigger one rate-limit event for 'c'
        for _ in range(int(limiter.burst_size) + 1):
            limiter.check("c")

        stats = limiter.get_stats()

        assert stats["total_connections"] == 3
        assert stats["rate_limit_events_last_minute"] >= 1

    def test_global_stats_average_tokens_with_one_connection(self, limiter, fake_time):
        """average_tokens equals the single connection's remaining tokens."""
        limiter.check("a")

        stats = limiter.get_stats()

        # Only 'a' is tracked, with 3 tokens remaining
        assert stats["average_tokens"] == pytest.approx(3.0)

    def test_specific_connection_stats(self, limiter, fake_time):
        """get_stats(connection_id) reports per-connection details."""
        limiter.check("conn-1")
        stats = limiter.get_stats("conn-1")

        assert stats["connection_id"] == "conn-1"
        assert stats["burst_size"] == limiter.burst_size
        assert stats["rate"] == limiter.rate
        assert "tokens" in stats
        assert "last_update" in stats
        assert stats["rate_limit_events_last_minute"] == 0

    def test_specific_connection_stats_for_unknown_returns_defaults(self, limiter, fake_time):
        """get_stats(unknown) returns a default-shaped dict (no exception)."""
        stats = limiter.get_stats("nonexistent")

        assert stats["connection_id"] == "nonexistent"
        assert stats["tokens"] == limiter.burst_size  # default to full
        assert stats["rate_limit_events_last_minute"] == 0

    def test_recent_events_window_only_counts_last_minute(self, limiter, fake_time):
        """Rate-limit events older than 60s are excluded from the count."""
        for _ in range(int(limiter.burst_size) + 1):
            limiter.check("c")
        # Move clock forward 2 minutes
        fake_time[0] += 120

        stats = limiter.get_stats("c")

        assert stats["rate_limit_events_last_minute"] == 0


# =============================================================================
# Module-level Singleton Tests
# =============================================================================


class TestRateLimiterSingleton:
    """Tests for get_rate_limiter / reset_rate_limiter."""

    def test_get_rate_limiter_creates_singleton(self):
        """First call creates a new limiter; subsequent calls return it."""
        reset_rate_limiter()

        first = get_rate_limiter(rate=50.0, burst_size=75.0)
        second = get_rate_limiter()

        assert first is second
        assert first.rate == 50.0
        assert first.burst_size == 75.0

    def test_get_rate_limiter_ignores_args_after_first_call(self):
        """Args on subsequent calls are ignored - first-call wins."""
        reset_rate_limiter()
        first = get_rate_limiter(rate=10.0)
        second = get_rate_limiter(rate=999.0)  # ignored

        assert first.rate == 10.0
        assert second.rate == 10.0

    def test_reset_rate_limiter_clears_singleton(self):
        """reset_rate_limiter() forces a fresh instance on next call."""
        reset_rate_limiter()
        first = get_rate_limiter(rate=10.0)

        reset_rate_limiter()
        second = get_rate_limiter(rate=20.0)

        assert first is not second
        assert second.rate == 20.0


# =============================================================================
# Parameterised / Time-injection Tests
# =============================================================================


class TestRateLimiterTimeInjection:
    """Tests that exercise the time-based refill math precisely."""

    @pytest.mark.parametrize(
        "elapsed_seconds, expected_after_second_check",
        [
            # After 1st check: tokens = 3. After advancing elapsed seconds,
            # refill adds (elapsed * rate) tokens, capped at burst_size (4),
            # then 2nd check consumes 1.
            (0.0, 2.0),  # min(3+0, 4) - 1 = 2
            (0.5, 3.0),  # min(3+1, 4) - 1 = 3
            (1.0, 3.0),  # min(3+2, 4) - 1 = 3 (capped)
            (2.0, 3.0),  # min(3+4, 4) - 1 = 3 (capped)
        ],
    )
    def test_refill_after_partial_drain(
        self, fake_time, elapsed_seconds, expected_after_second_check
    ):
        """Refill math: tokens_remaining = drain_count + (elapsed × rate) - 1."""
        # Use a fresh limiter per case so the test is fully isolated
        limiter = TokenBucketRateLimiter(rate=2.0, burst_size=4.0, cleanup_interval=300.0)
        # Consume exactly 1 token (4 → 3)
        limiter.check("c")
        # Advance the clock
        fake_time[0] += elapsed_seconds

        limiter.check("c")

        # Refill = 3 + (elapsed × 2), then -1 for the second check's consumption
        assert limiter._tokens["c"] == pytest.approx(expected_after_second_check)

    def test_refill_caps_at_burst_size(self, fake_time):
        """Long idle periods do not refill past burst_size."""
        limiter = TokenBucketRateLimiter(rate=2.0, burst_size=4.0, cleanup_interval=300.0)
        limiter.check("c")
        # Idle for 5 seconds → would add 10 tokens, but capped at burst_size 4.
        fake_time[0] += 5.0

        limiter.check("c")

        # Stored tokens = min(3 + 10, 4) - 1 = 3
        assert limiter._tokens["c"] == pytest.approx(3.0)

    def test_long_idle_then_check_does_not_exceed_burst(self, limiter, fake_time):
        """Even after a very long idle, bucket is capped at burst_size."""
        limiter.check("c")
        fake_time[0] += 10_000  # 10k seconds at rate=2 = 20k tokens, but capped at 4

        result = limiter.check("c")

        assert result.allowed is True
        assert limiter._tokens["c"] <= limiter.burst_size

    def test_uses_module_local_time(self, monkeypatch):
        """The limiter uses time.time from its own module namespace."""
        # check() calls time.time() multiple times (cleanup, get_or_create, refill).
        # Provide a list-based fake so any number of calls is safe.
        timestamps = [100.0, 100.0, 100.0, 100.0, 100.0]
        monkeypatch.setattr(
            "mahavishnu.websocket.rate_limiter.time.time",
            lambda: timestamps[0] if len(timestamps) == 1 else timestamps.pop(0),
        )

        limiter = TokenBucketRateLimiter(rate=1.0, burst_size=1.0)
        result = limiter.check("c")

        assert result.allowed is True
        assert limiter._last_update["c"] == 100.0
