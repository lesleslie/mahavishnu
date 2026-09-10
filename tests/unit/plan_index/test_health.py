"""Unit tests for mahavishnu.plan_index.health."""

from __future__ import annotations

import time

from mahavishnu.plan_index.health import PlanIndexFeedState


class TestAsDictContract:
    def test_exactly_five_keys(self) -> None:
        state = PlanIndexFeedState(
            entities_count=42,
            last_updated_timestamp=1_700_000_000_000,
            errors_total=0,
            cycles_total=10,
        )
        d = state.as_dict()
        # MUST match SignerFeedState.as_dict() shape (mahavishnu/mcp/signer_feed.py:203).
        # The discipline doc mandates the feed_ prefix.
        assert set(d.keys()) == {
            "ok",
            "feed_entities_count",
            "feed_last_updated_timestamp",
            "feed_errors_total",
            "feed_cycles_total",
        }
        # CRITICAL: 4-signal contract. successful_cycles_total is NOT here.

    def test_ok_present_and_boolean(self) -> None:
        state = PlanIndexFeedState(
            entities_count=0,
            last_updated_timestamp=int(time.time() * 1000),
            errors_total=0,
            cycles_total=0,
        )
        d = state.as_dict()
        assert isinstance(d["ok"], bool)


class TestIsOk:
    def test_recent_timestamp_is_ok(self) -> None:
        state = PlanIndexFeedState(
            entities_count=0,
            last_updated_timestamp=int(time.time() * 1000),
            errors_total=0,
            cycles_total=0,
        )
        assert state.is_ok() is True

    def test_stale_timestamp_is_not_ok(self) -> None:
        # 6 hours ago = past 5× cron_every_seconds at default 3600s
        six_hours_ago_ms = int(time.time() * 1000) - 6 * 3600 * 1000
        state = PlanIndexFeedState(
            entities_count=0,
            last_updated_timestamp=six_hours_ago_ms,
            errors_total=0,
            cycles_total=0,
        )
        assert state.is_ok() is False

    def test_boundary_at_5x_cron(self) -> None:
        # Exactly 5× cron interval ago: just at threshold
        five_hours_ago_ms = int(time.time() * 1000) - 5 * 3600 * 1000
        state = PlanIndexFeedState(
            entities_count=0,
            last_updated_timestamp=five_hours_ago_ms,
            errors_total=0,
            cycles_total=0,
        )
        # At exactly 5×cron: not strictly less than, so is_ok returns False
        # (depends on implementation; we test that 6 hours is False and now is True)
        assert state.is_ok() is False

    def test_custom_cron_interval(self) -> None:
        six_hours_ago_ms = int(time.time() * 1000) - 6 * 3600 * 1000
        state = PlanIndexFeedState(
            entities_count=0,
            last_updated_timestamp=six_hours_ago_ms,
            errors_total=0,
            cycles_total=0,
        )
        # With cron at 1 hour, threshold is 5 hours; 6 hours is stale
        assert state.is_ok(cron_every_seconds=3600) is False
        # With cron at 24 hours, threshold is 5 days; 6 hours is fine
        assert state.is_ok(cron_every_seconds=24 * 3600) is True
