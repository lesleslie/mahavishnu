"""Comprehensive unit tests for mahavishnu/websocket/rate_limiter.py."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.websocket.rate_limiter import (
    RateLimitResult,
    TokenBucketRateLimiter,
    get_rate_limiter,
    reset_rate_limiter,
)


# ---------------------------------------------------------------------------
# RateLimitResult dataclass
# ---------------------------------------------------------------------------


class TestRateLimitResult:
    """Tests for the RateLimitResult dataclass."""

    def test_default_values_allow(self):
        result = RateLimitResult()
        assert result.allowed is True
        assert result.retry_after == 0.0
        assert result.tokens_remaining == 0.0
        assert result.limited is False

    def test_explicit_values_deny(self):
        result = RateLimitResult(
            allowed=False,
            retry_after=0.5,
            tokens_remaining=0.2,
            limited=True,
        )
        assert result.allowed is False
        assert result.retry_after == 0.5
        assert result.tokens_remaining == 0.2
        assert result.limited is True

    def test_partial_override(self):
        result = RateLimitResult(allowed=False, limited=True)
        assert result.allowed is False
        assert result.limited is True
        assert result.retry_after == 0.0
        assert result.tokens_remaining == 0.0


# ---------------------------------------------------------------------------
# TokenBucketRateLimiter.__init__
# ---------------------------------------------------------------------------


class TestTokenBucketRateLimiterInit:
    """Tests for TokenBucketRateLimiter initialization."""

    def test_default_burst_size_is_1_5x_rate(self):
        limiter = TokenBucketRateLimiter(rate=100.0)
        assert limiter.rate == 100.0
        assert limiter.burst_size == 150.0

    def test_custom_burst_size(self):
        limiter = TokenBucketRateLimiter(rate=100.0, burst_size=200.0)
        assert limiter.burst_size == 200.0

    def test_custom_cleanup_interval(self):
        limiter = TokenBucketRateLimiter(cleanup_interval=600.0)
        assert limiter.cleanup_interval == 600.0

    def test_zero_rate(self):
        limiter = TokenBucketRateLimiter(rate=0.0, burst_size=0.0)
        assert limiter.rate == 0.0
        assert limiter.burst_size == 0.0

    def test_small_rate_and_burst(self):
        limiter = TokenBucketRateLimiter(rate=1.0, burst_size=2.0)
        assert limiter.rate == 1.0
        assert limiter.burst_size == 2.0

    def test_fractional_rate(self):
        limiter = TokenBucketRateLimiter(rate=0.5, burst_size=1.0)
        assert limiter.rate == 0.5
        assert limiter.burst_size == 1.0

    def test_initial_internal_state(self):
        limiter = TokenBucketRateLimiter()
        assert limiter._tokens == {}
        assert limiter._last_update == {}
        assert len(limiter._rate_limit_events) == 0
        # _last_cleanup should be approximately now
        assert abs(time.time() - limiter._last_cleanup) < 1.0


# ---------------------------------------------------------------------------
# _get_or_create_bucket
# ---------------------------------------------------------------------------


class TestGetOrCreateBucket:
    """Tests for the _get_or_create_bucket method."""

    def test_new_connection_starts_with_full_bucket(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=15.0)
        tokens, last_update = limiter._get_or_create_bucket("conn_1")
        assert tokens == 15.0
        assert abs(time.time() - last_update) < 0.01

    def test_existing_connection_returns_current_state(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=15.0)
        # First call creates the bucket
        limiter._get_or_create_bucket("conn_1")
        # Mutate internal state to verify it's returned on subsequent call
        limiter._tokens["conn_1"] = 7.5
        tokens, last_update = limiter._get_or_create_bucket("conn_1")
        assert tokens == 7.5

    def test_multiple_connections_are_independent(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=15.0)
        limiter._get_or_create_bucket("conn_a")
        limiter._get_or_create_bucket("conn_b")
        limiter._tokens["conn_a"] = 3.0
        limiter._tokens["conn_b"] = 10.0
        tokens_a, _ = limiter._get_or_create_bucket("conn_a")
        tokens_b, _ = limiter._get_or_create_bucket("conn_b")
        assert tokens_a == 3.0
        assert tokens_b == 10.0


# ---------------------------------------------------------------------------
# _refill_tokens
# ---------------------------------------------------------------------------


class TestRefillTokens:
    """Tests for the _refill_tokens method."""

    def test_no_elapsed_time_returns_same_tokens(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=15.0)
        now = time.time()
        result = limiter._refill_tokens("conn_1", 5.0, now)
        assert result == pytest.approx(5.0, abs=0.001)

    def test_refill_adds_tokens_based_on_elapsed_time(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=15.0)
        past = time.time() - 1.0  # 1 second ago
        result = limiter._refill_tokens("conn_1", 5.0, past)
        # 5.0 + (1.0 * 10.0) = 15.0
        assert result == pytest.approx(15.0, abs=0.01)

    def test_refill_caps_at_burst_size(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=15.0)
        past = time.time() - 10.0  # 10 seconds ago, would add 100 tokens
        result = limiter._refill_tokens("conn_1", 5.0, past)
        # Capped at burst_size 15.0
        assert result == pytest.approx(15.0, abs=0.01)

    def test_partial_refill(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=15.0)
        past = time.time() - 0.3  # 0.3 seconds ago
        result = limiter._refill_tokens("conn_1", 5.0, past)
        # 5.0 + (0.3 * 10.0) = 8.0
        assert result == pytest.approx(8.0, abs=0.01)

    def test_refill_from_zero(self):
        limiter = TokenBucketRateLimiter(rate=5.0, burst_size=10.0)
        past = time.time() - 1.0
        result = limiter._refill_tokens("conn_1", 0.0, past)
        # 0.0 + (1.0 * 5.0) = 5.0
        assert result == pytest.approx(5.0, abs=0.01)


# ---------------------------------------------------------------------------
# check - allow decisions
# ---------------------------------------------------------------------------


class TestCheckAllow:
    """Tests for the check method when messages are allowed."""

    def test_first_check_is_allowed(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=15.0)
        result = limiter.check("conn_1")
        assert result.allowed is True
        assert result.limited is False
        assert result.retry_after == 0.0
        # Consumed 1 token from burst_size
        assert result.tokens_remaining == pytest.approx(14.0, abs=0.01)

    def test_consecutive_checks_within_burst(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=5.0)
        for i in range(5):
            result = limiter.check("conn_1")
            assert result.allowed is True, f"Check {i} should be allowed"
        # All 5 burst tokens consumed
        assert result.tokens_remaining == pytest.approx(0.0, abs=0.01)

    def test_check_refills_over_time(self):
        limiter = TokenBucketRateLimiter(rate=100.0, burst_size=5.0)
        # Consume all burst tokens
        for _ in range(5):
            limiter.check("conn_1")

        # Wait briefly for some refill
        time.sleep(0.02)  # 20ms -> ~2 tokens
        result = limiter.check("conn_1")
        assert result.allowed is True

    def test_check_returns_correct_tokens_remaining(self):
        limiter = TokenBucketRateLimiter(rate=100.0, burst_size=10.0)
        result = limiter.check("conn_1")
        assert result.tokens_remaining == pytest.approx(9.0, abs=0.1)
        result = limiter.check("conn_1")
        assert result.tokens_remaining == pytest.approx(8.0, abs=0.1)


# ---------------------------------------------------------------------------
# check - deny / rate limit decisions
# ---------------------------------------------------------------------------


class TestCheckDeny:
    """Tests for the check method when messages are rate limited."""

    def test_exhausted_bucket_returns_limited(self):
        limiter = TokenBucketRateLimiter(rate=0.0, burst_size=1.0)
        # First check consumes the only token
        limiter.check("conn_1")
        # Second check should be rate limited
        result = limiter.check("conn_1")
        assert result.allowed is False
        assert result.limited is True

    def test_rate_limited_result_has_retry_after(self):
        limiter = TokenBucketRateLimiter(rate=0.0, burst_size=1.0)
        limiter.check("conn_1")
        result = limiter.check("conn_1")
        # With rate=0, tokens_needed = 1.0, retry_after = 1.0 / 0.0 = inf
        assert result.retry_after == float("inf")

    def test_rate_limited_result_with_positive_rate(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=1.0)
        limiter.check("conn_1")
        result = limiter.check("conn_1")
        # tokens_needed ~ 1.0, retry_after ~ 0.1
        assert result.retry_after > 0.0
        assert result.retry_after < 1.0

    def test_rate_limited_tracks_events(self):
        limiter = TokenBucketRateLimiter(rate=0.0, burst_size=1.0)
        limiter.check("conn_1")
        limiter.check("conn_1")
        limiter.check("conn_1")
        events = limiter._rate_limit_events["conn_1"]
        assert len(events) == 2  # First check was allowed

    def test_tokens_remaining_on_rate_limit(self):
        limiter = TokenBucketRateLimiter(rate=0.0, burst_size=2.0)
        limiter.check("conn_1")  # 1 token remaining
        limiter.check("conn_1")  # 0 tokens remaining
        result = limiter.check("conn_1")  # rate limited
        assert result.allowed is False
        assert result.tokens_remaining == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# Per-client rate limiting
# ---------------------------------------------------------------------------


class TestPerClientRateLimiting:
    """Tests for per-client (per-connection) rate limiting isolation."""

    def test_clients_are_independent(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=3.0)
        # Exhaust client A
        for _ in range(3):
            limiter.check("client_a")
        result_a = limiter.check("client_a")
        assert result_a.allowed is False

        # Client B should still be allowed
        result_b = limiter.check("client_b")
        assert result_b.allowed is True

    def test_client_burst_exhaustion(self):
        limiter = TokenBucketRateLimiter(rate=0.0, burst_size=2.0)
        # Client A can send 2 messages
        assert limiter.check("a").allowed is True
        assert limiter.check("a").allowed is True
        assert limiter.check("a").allowed is False

        # Client B also gets its own 2 messages
        assert limiter.check("b").allowed is True
        assert limiter.check("b").allowed is True
        assert limiter.check("b").allowed is False

    def test_many_clients_tracked_separately(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=5.0)
        client_ids = [f"client_{i}" for i in range(100)]
        for cid in client_ids:
            result = limiter.check(cid)
            assert result.allowed is True
        # Each client should have 4 tokens remaining
        for cid in client_ids:
            assert limiter._tokens[cid] == pytest.approx(4.0, abs=0.01)


# ---------------------------------------------------------------------------
# Configurable thresholds
# ---------------------------------------------------------------------------


class TestConfigurableThresholds:
    """Tests for different rate and burst configurations."""

    def test_high_rate_allows_many_requests(self):
        limiter = TokenBucketRateLimiter(rate=10000.0, burst_size=1000.0)
        for i in range(500):
            result = limiter.check("conn")
            assert result.allowed is True, f"Request {i} should be allowed"
        assert result.tokens_remaining > 0

    def test_low_burst_exhausts_quickly(self):
        limiter = TokenBucketRateLimiter(rate=0.0, burst_size=1.0)
        limiter.check("conn")
        result = limiter.check("conn")
        assert result.allowed is False

    def test_burst_one_allows_only_one_message(self):
        limiter = TokenBucketRateLimiter(rate=0.0, burst_size=1.0)
        assert limiter.check("conn").allowed is True
        assert limiter.check("conn").allowed is False

    def test_large_burst_allows_many_messages(self):
        limiter = TokenBucketRateLimiter(rate=0.0, burst_size=1000.0)
        for i in range(1000):
            assert limiter.check("conn").allowed is True, f"Message {i}"
        assert limiter.check("conn").allowed is False


# ---------------------------------------------------------------------------
# remove_connection
# ---------------------------------------------------------------------------


class TestRemoveConnection:
    """Tests for the remove_connection method."""

    def test_remove_existing_connection(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=5.0)
        limiter.check("conn_1")
        assert "conn_1" in limiter._tokens
        limiter.remove_connection("conn_1")
        assert "conn_1" not in limiter._tokens
        assert "conn_1" not in limiter._last_update
        assert "conn_1" not in limiter._rate_limit_events

    def test_remove_nonexistent_connection_does_not_raise(self):
        limiter = TokenBucketRateLimiter()
        limiter.remove_connection("nonexistent")  # Should not raise

    def test_remove_connection_with_rate_limit_events(self):
        limiter = TokenBucketRateLimiter(rate=0.0, burst_size=1.0)
        limiter.check("conn_1")  # allowed
        limiter.check("conn_1")  # rate limited, event recorded
        assert len(limiter._rate_limit_events["conn_1"]) == 1
        limiter.remove_connection("conn_1")
        assert "conn_1" not in limiter._rate_limit_events

    def test_removed_connection_gets_new_bucket_on_next_check(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=5.0)
        limiter.check("conn_1")
        limiter.check("conn_1")  # 3 tokens left
        limiter.remove_connection("conn_1")
        result = limiter.check("conn_1")  # Should create new full bucket
        assert result.allowed is True
        assert result.tokens_remaining == pytest.approx(4.0, abs=0.01)


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------


class TestGetStats:
    """Tests for the get_stats method."""

    def test_global_stats_empty_limiter(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=15.0)
        stats = limiter.get_stats()
        assert stats["total_connections"] == 0
        assert stats["rate"] == 10.0
        assert stats["burst_size"] == 15.0
        assert stats["average_tokens"] == 15.0  # burst_size when empty
        assert stats["rate_limit_events_last_minute"] == 0
        assert stats["cleanup_interval"] == 300.0

    def test_global_stats_with_connections(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=15.0)
        limiter.check("conn_a")
        limiter.check("conn_b")
        stats = limiter.get_stats()
        assert stats["total_connections"] == 2
        # Each consumed 1 token, so 14 each -> avg 14
        assert stats["average_tokens"] == pytest.approx(14.0, abs=0.01)

    def test_per_connection_stats(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=15.0)
        limiter.check("conn_1")
        limiter.check("conn_1")
        stats = limiter.get_stats("conn_1")
        assert stats["connection_id"] == "conn_1"
        assert stats["tokens"] == pytest.approx(13.0, abs=0.01)
        assert stats["burst_size"] == 15.0
        assert stats["rate"] == 10.0
        assert stats["rate_limit_events_last_minute"] == 0

    def test_per_connection_stats_unknown_connection(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=15.0)
        stats = limiter.get_stats("unknown_conn")
        assert stats["connection_id"] == "unknown_conn"
        assert stats["tokens"] == 15.0  # Default burst_size for unknown

    def test_per_connection_stats_includes_rate_limit_events(self):
        limiter = TokenBucketRateLimiter(rate=0.0, burst_size=1.0)
        limiter.check("conn_1")  # allowed
        limiter.check("conn_1")  # rate limited
        stats = limiter.get_stats("conn_1")
        assert stats["rate_limit_events_last_minute"] == 1


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


class TestReset:
    """Tests for the reset method."""

    def test_reset_all_clears_everything(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=5.0)
        limiter.check("conn_a")
        limiter.check("conn_b")
        limiter.reset()
        assert limiter._tokens == {}
        assert limiter._last_update == {}
        assert len(limiter._rate_limit_events) == 0

    def test_reset_specific_connection(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=5.0)
        limiter.check("conn_a")
        limiter.check("conn_a")  # 3 tokens left
        limiter.check("conn_b")
        limiter.reset("conn_a")
        # conn_a should be back to full burst
        assert limiter._tokens["conn_a"] == 5.0
        # conn_b should be unchanged
        assert limiter._tokens["conn_b"] == pytest.approx(4.0, abs=0.01)

    def test_reset_specific_connection_clears_events(self):
        limiter = TokenBucketRateLimiter(rate=0.0, burst_size=1.0)
        limiter.check("conn_1")
        limiter.check("conn_1")  # rate limited
        assert len(limiter._rate_limit_events["conn_1"]) == 1
        limiter.reset("conn_1")
        assert "conn_1" not in limiter._rate_limit_events

    def test_reset_unknown_connection_creates_it(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=5.0)
        limiter.reset("new_conn")
        assert limiter._tokens["new_conn"] == 5.0
        assert "new_conn" in limiter._last_update


# ---------------------------------------------------------------------------
# _maybe_cleanup / _cleanup_idle_buckets
# ---------------------------------------------------------------------------


class TestCleanup:
    """Tests for idle bucket cleanup."""

    def test_cleanup_not_triggered_before_interval(self):
        limiter = TokenBucketRateLimiter(cleanup_interval=300.0)
        limiter.check("conn_1")
        # Cleanup should not run immediately
        original_tokens = dict(limiter._tokens)
        limiter._maybe_cleanup()
        assert limiter._tokens == original_tokens

    def test_cleanup_removes_idle_connections(self):
        limiter = TokenBucketRateLimiter(cleanup_interval=0.0)
        limiter.check("conn_1")
        # With cleanup_interval=0, any connection is idle immediately
        limiter._cleanup_idle_buckets()
        assert "conn_1" not in limiter._tokens
        assert "conn_1" not in limiter._last_update

    def test_cleanup_removes_rate_limit_events_for_idle(self):
        limiter = TokenBucketRateLimiter(cleanup_interval=0.0)
        limiter.check("conn_1")
        limiter._rate_limit_events["conn_1"].append(time.time())
        limiter._cleanup_idle_buckets()
        assert "conn_1" not in limiter._rate_limit_events

    def test_cleanup_keeps_active_connections(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=5.0, cleanup_interval=300.0)
        limiter.check("conn_1")
        # Simulate a recent update
        limiter._last_update["conn_1"] = time.time()
        limiter._cleanup_idle_buckets()
        assert "conn_1" in limiter._tokens

    def test_cleanup_with_no_connections(self):
        limiter = TokenBucketRateLimiter(cleanup_interval=0.0)
        limiter._cleanup_idle_buckets()  # Should not raise
        assert limiter._tokens == {}


# ---------------------------------------------------------------------------
# _log_rate_limit
# ---------------------------------------------------------------------------


class TestLogRateLimit:
    """Tests for throttled rate limit logging."""

    def test_first_event_logs_warning(self):
        limiter = TokenBucketRateLimiter(rate=0.0, burst_size=1.0)
        limiter.check("conn_1")  # allowed
        with patch("mahavishnu.websocket.rate_limiter.logger.warning") as mock_warning:
            limiter.check("conn_1")  # rate limited, should log
            mock_warning.assert_called_once()

    def test_subsequent_events_within_one_second_are_throttled(self):
        limiter = TokenBucketRateLimiter(rate=0.0, burst_size=1.0)
        limiter.check("conn_1")
        # First rate limit event
        with patch("mahavishnu.websocket.rate_limiter.logger.warning") as mock_warning:
            limiter.check("conn_1")
            limiter.check("conn_1")
            limiter.check("conn_1")
            # Only the first event in this second should log
            mock_warning.assert_called_once()

    def test_log_message_contains_connection_id(self):
        limiter = TokenBucketRateLimiter(rate=0.0, burst_size=1.0)
        limiter.check("conn_1")
        with patch("mahavishnu.websocket.rate_limiter.logger.warning") as mock_warning:
            limiter.check("conn_1")
            call_args = mock_warning.call_args[0][0]
            assert "conn_1" in call_args

    def test_log_message_contains_retry_after(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=1.0)
        limiter.check("conn_1")
        with patch("mahavishnu.websocket.rate_limiter.logger.warning") as mock_warning:
            limiter.check("conn_1")
            call_args = mock_warning.call_args[0][0]
            assert "retry_after=" in call_args


# ---------------------------------------------------------------------------
# Module-level singleton: get_rate_limiter / reset_rate_limiter
# ---------------------------------------------------------------------------


class TestGetRateLimiter:
    """Tests for the module-level singleton functions."""

    def setup_method(self):
        reset_rate_limiter()

    def teardown_method(self):
        reset_rate_limiter()

    def test_get_rate_limiter_creates_instance(self):
        limiter = get_rate_limiter(rate=50.0, burst_size=75.0)
        assert isinstance(limiter, TokenBucketRateLimiter)
        assert limiter.rate == 50.0
        assert limiter.burst_size == 75.0

    def test_get_rate_limiter_returns_same_instance(self):
        limiter1 = get_rate_limiter(rate=50.0)
        limiter2 = get_rate_limiter(rate=999.0)  # Args ignored on subsequent calls
        assert limiter1 is limiter2
        assert limiter2.rate == 50.0  # Uses first call's rate

    def test_reset_rate_limiter_allows_new_instance(self):
        limiter1 = get_rate_limiter(rate=50.0)
        reset_rate_limiter()
        limiter2 = get_rate_limiter(rate=200.0)
        assert limiter1 is not limiter2
        assert limiter2.rate == 200.0

    def test_reset_rate_limiter_idempotent(self):
        reset_rate_limiter()
        reset_rate_limiter()  # Should not raise
        limiter = get_rate_limiter()
        assert isinstance(limiter, TokenBucketRateLimiter)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases and unusual configurations."""

    def test_zero_rate_zero_burst_never_allows(self):
        limiter = TokenBucketRateLimiter(rate=0.0, burst_size=0.0)
        result = limiter.check("conn")
        assert result.allowed is False
        assert result.limited is True

    def test_zero_rate_nonzero_burst_allows_burst_then_blocks(self):
        limiter = TokenBucketRateLimiter(rate=0.0, burst_size=3.0)
        assert limiter.check("conn").allowed is True
        assert limiter.check("conn").allowed is True
        assert limiter.check("conn").allowed is True
        assert limiter.check("conn").allowed is False
        # Even after waiting, no refill occurs
        time.sleep(0.05)
        assert limiter.check("conn").allowed is False

    def test_burst_size_zero_with_positive_rate(self):
        """burst_size=0 caps refill at 0, so limiter is permanently locked."""
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=0.0)
        result = limiter.check("conn")
        assert result.allowed is False
        # Even after time passes, burst_size=0 caps refill at 0
        time.sleep(0.2)
        result = limiter.check("conn")
        assert result.allowed is False

    def test_very_large_burst_size(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=1_000_000.0)
        result = limiter.check("conn")
        assert result.allowed is True
        assert result.tokens_remaining == pytest.approx(999_999.0, abs=0.01)

    def test_check_updates_last_update_timestamp(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=5.0)
        limiter.check("conn")
        first_update = limiter._last_update["conn"]
        time.sleep(0.01)
        limiter.check("conn")
        second_update = limiter._last_update["conn"]
        assert second_update > first_update

    def test_check_with_empty_connection_id(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=5.0)
        result = limiter.check("")
        assert result.allowed is True

    def test_concurrent_different_connections(self):
        """Simulate rapid checks across many connections."""
        limiter = TokenBucketRateLimiter(rate=1000.0, burst_size=1000.0)
        results = []
        for i in range(500):
            results.append(limiter.check(f"conn_{i}"))
        assert all(r.allowed for r in results)

    def test_single_connection_burst_then_refill_cycle(self):
        limiter = TokenBucketRateLimiter(rate=100.0, burst_size=5.0)
        # Exhaust burst
        for _ in range(5):
            limiter.check("conn")
        assert limiter.check("conn").allowed is False

        # Wait for enough refill for 1 token
        time.sleep(0.02)  # ~2 tokens at 100/s
        result = limiter.check("conn")
        assert result.allowed is True

    def test_fractional_token_accumulation(self):
        """Verify that fractional tokens accumulate correctly."""
        limiter = TokenBucketRateLimiter(rate=1.0, burst_size=3.0)
        # Exhaust all tokens
        for _ in range(3):
            limiter.check("conn")
        assert limiter.check("conn").allowed is False

        # Wait 0.5 seconds -> 0.5 tokens, still not enough for 1 message
        time.sleep(0.5)
        result = limiter.check("conn")
        assert result.allowed is False

        # Wait another 0.6 seconds -> ~1.1 total tokens, enough for 1 message
        time.sleep(0.6)
        result = limiter.check("conn")
        assert result.allowed is True

    def test_burst_size_none_uses_default(self):
        limiter = TokenBucketRateLimiter(rate=20.0, burst_size=None)
        assert limiter.burst_size == 30.0  # 1.5 * 20

    def test_stats_after_reset_all(self):
        limiter = TokenBucketRateLimiter(rate=10.0, burst_size=5.0)
        limiter.check("a")
        limiter.check("b")
        limiter.reset()
        stats = limiter.get_stats()
        assert stats["total_connections"] == 0
        assert stats["average_tokens"] == 5.0  # burst_size when empty
