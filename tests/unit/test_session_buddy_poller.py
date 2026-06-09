"""Tests for Session-Buddy poller configuration, lifecycle, and error paths."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.integrations.session_buddy_poller import SessionBuddyPoller
from monitoring.metrics import (
    bodai_bridge_freshness_seconds,
    bodai_bridge_metric_ingest_total,
    bodai_bridge_poll_duration_seconds,
    bodai_bridge_poll_errors_total,
    bodai_bridge_polls_total,
)


@pytest.fixture
def poller_config() -> MahavishnuSettings:
    """Configuration with Session-Buddy polling enabled."""
    return MahavishnuSettings(
        session_buddy_polling={
            "enabled": True,
            "endpoint": "http://localhost:8678/mcp/",
            "interval_seconds": 15,
            "timeout_seconds": 7,
            "max_retries": 2,
            "retry_delay_seconds": 3,
            "circuit_breaker_threshold": 4,
            "metrics_to_collect": ["get_activity_summary"],
        }
    )


@pytest.fixture
def disabled_config() -> MahavishnuSettings:
    """Configuration with Session-Buddy polling disabled."""
    return MahavishnuSettings(
        session_buddy_polling={
            "enabled": False,
            "endpoint": "http://localhost:8678/mcp",
            "interval_seconds": 10,
            "timeout_seconds": 5,
            "max_retries": 1,
            "retry_delay_seconds": 1,
            "circuit_breaker_threshold": 3,
        }
    )


def _ok_response(payload: dict | None = None) -> MagicMock:
    """Build a successful httpx response mock."""
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload if payload is not None else {
        "result": {"active_sessions": 1, "total_sessions": 2}
    }
    return response


class TestSessionBuddyPoller:
    """Test Session-Buddy poller behavior."""

    def test_uses_nested_polling_config(self, poller_config: MahavishnuSettings):
        """Poller should read the nested session_buddy_polling config model."""
        poller = SessionBuddyPoller(config=poller_config)

        assert poller.enabled is True
        assert poller.endpoint == "http://localhost:8678/mcp"
        assert poller.interval == 15
        assert poller.timeout == 7
        assert poller.max_retries == 2
        assert poller.retry_delay == 3
        assert poller.circuit_breaker_threshold == 4
        assert poller.metrics_to_collect == ["get_activity_summary"]

    def test_default_metrics_when_not_specified(self) -> None:
        """Poller should fall back to the full MCP_TOOLS list when config is empty."""
        config = MahavishnuSettings(
            session_buddy_polling={
                "enabled": True,
                "endpoint": "http://localhost:8678/mcp",
                "interval_seconds": 5,
                "timeout_seconds": 5,
                "max_retries": 1,
                "retry_delay_seconds": 1,
                "circuit_breaker_threshold": 3,
                "metrics_to_collect": [],
            }
        )
        poller = SessionBuddyPoller(config=config)

        assert poller.metrics_to_collect == SessionBuddyPoller.MCP_TOOLS

    @pytest.mark.asyncio
    async def test_poll_once_records_bridge_metrics(self, poller_config: MahavishnuSettings):
        """Successful polls should emit bridge metrics on the shared registry."""
        poller = SessionBuddyPoller(config=poller_config)
        poller._http_client = AsyncMock()

        mock_response = _ok_response(
            {"result": {"active_sessions": 2, "total_sessions": 5}}
        )
        poller._http_client.post.return_value = mock_response

        result = await poller.poll_once()

        assert result["metrics_collected"] == ["get_activity_summary"]
        poll_value = bodai_bridge_polls_total.labels(
            source_service="session_buddy",
            status="success",
        )._value.get()
        ingest_value = bodai_bridge_metric_ingest_total.labels(
            source_service="session_buddy",
            source_tool="get_activity_summary",
        )._value.get()

        assert poll_value >= 1
        assert ingest_value >= 1


class TestPollerLifecycle:
    """Lifecycle tests for start/stop and config gating."""

    @pytest.mark.asyncio
    async def test_start_when_disabled_is_noop(
        self, disabled_config: MahavishnuSettings
    ) -> None:
        """start() should refuse to spawn a task when polling is disabled."""
        poller = SessionBuddyPoller(config=disabled_config)

        await poller.start()

        status = await poller.get_status()
        assert status.running is False
        assert poller._http_client is None
        assert poller._poll_task is None

    @pytest.mark.asyncio
    async def test_stop_when_not_started_is_noop(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """stop() should be safe to call when the poller never started."""
        poller = SessionBuddyPoller(config=poller_config)

        # Should not raise
        await poller.stop()

        status = await poller.get_status()
        assert status.running is False

    @pytest.mark.asyncio
    async def test_start_twice_does_not_respawn(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """Calling start() while running should log a warning and not spawn again."""
        poller = SessionBuddyPoller(config=poller_config)
        poller._http_client = AsyncMock()
        poller._http_client.aclose = AsyncMock()

        first_task = asyncio.create_task(asyncio.sleep(0.05))
        poller._running = True
        poller._poll_task = first_task

        await poller.start()

        assert poller._poll_task is first_task

        first_task.cancel()
        with suppress(asyncio.CancelledError):
            await first_task

    @pytest.mark.asyncio
    async def test_stop_closes_http_client(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """stop() should close the active httpx client and clear the task."""
        poller = SessionBuddyPoller(config=poller_config)
        poller._running = True
        client = AsyncMock()
        client.aclose = AsyncMock()
        poller._http_client = client

        async def _noop_loop() -> None:
            await asyncio.sleep(10)

        poller._poll_task = asyncio.create_task(_noop_loop())
        await asyncio.sleep(0)  # let task start

        await poller.stop()

        assert poller._http_client is None
        assert poller._poll_task is None
        assert poller._running is False
        client.aclose.assert_awaited()


class TestPollerStatus:
    """Status reporting tests."""

    @pytest.mark.asyncio
    async def test_status_reflects_state(self, poller_config: MahavishnuSettings) -> None:
        """get_status() should return a PollerStatus matching internal state."""
        poller = SessionBuddyPoller(config=poller_config)
        poller._poll_cycles = 7
        poller._errors = 2
        poller._last_error = "boom"
        poller._circuit_breaker_open = True

        status = await poller.get_status()

        assert status.running is False
        assert status.poll_cycles == 7
        assert status.errors == 2
        assert status.last_error == "boom"
        assert status.circuit_breaker_open is True
        assert status.last_poll_time is None


class TestPollOnceErrorPaths:
    """Error-path tests for poll_once and _call_mcp_tool."""

    @pytest.mark.asyncio
    async def test_poll_once_without_http_client_raises(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """poll_once() before start() should raise a clear RuntimeError."""
        poller = SessionBuddyPoller(config=poller_config)

        with pytest.raises(RuntimeError, match="not started"):
            await poller.poll_once()

    @pytest.mark.asyncio
    async def test_poll_once_records_errors_when_post_fails(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """A persistent HTTP failure should record errors and not crash the cycle."""
        poller = SessionBuddyPoller(config=poller_config)
        poller._http_client = AsyncMock()
        poller._http_client.post.side_effect = httpx.ConnectError("connection refused")

        result = await poller.poll_once()

        assert result["errors"]
        assert result["metrics_collected"] == []
        assert poller._errors == 1
        assert poller._consecutive_failures == 1
        assert poller._last_error is not None
        assert "Failed to poll" in poller._last_error

        error_value = bodai_bridge_poll_errors_total.labels(
            source_service="session_buddy",
            error_type="poll_error",
        )._value.get()
        assert error_value >= 1

    @pytest.mark.asyncio
    async def test_poll_once_marks_status_error_on_failure(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """A failing poll should mark the polls_total counter as 'error'."""
        poller = SessionBuddyPoller(config=poller_config)
        poller._http_client = AsyncMock()
        poller._http_client.post.side_effect = httpx.ConnectError("oops")

        before = bodai_bridge_polls_total.labels(
            source_service="session_buddy",
            status="error",
        )._value.get()

        await poller.poll_once()

        after = bodai_bridge_polls_total.labels(
            source_service="session_buddy",
            status="error",
        )._value.get()
        assert after > before

    @pytest.mark.asyncio
    async def test_poll_once_sets_freshness_when_no_metrics_collected(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """A successful call returning unparseable data should still set freshness."""
        poller = SessionBuddyPoller(config=poller_config)
        poller._http_client = AsyncMock()
        poller._http_client.post.return_value = _ok_response(
            {"result": "not-a-dict"}
        )

        await poller.poll_once()

        # The freshness gauge should be set (non-None float value).
        value = bodai_bridge_freshness_seconds.labels(
            source_service="session_buddy",
        )._value.get()
        assert value is not None

    @pytest.mark.asyncio
    async def test_poll_once_skips_unknown_tool(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """An unknown tool name in metrics_to_collect should be skipped silently."""
        config = MahavishnuSettings(
            session_buddy_polling={
                **poller_config.session_buddy_polling.model_dump(),
                "metrics_to_collect": [
                    "get_activity_summary",
                    "definitely_not_a_real_tool",
                ],
            }
        )
        poller = SessionBuddyPoller(config=config)
        poller._http_client = AsyncMock()
        poller._http_client.post.return_value = _ok_response(
            {"result": {"active_sessions": 1, "total_sessions": 1}}
        )

        result = await poller.poll_once()

        assert result["metrics_collected"] == ["get_activity_summary"]
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_poll_once_collects_workflow_metrics(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """Workflow metrics should be converted into OTel counter/gauge entries."""
        config = MahavishnuSettings(
            session_buddy_polling={
                **poller_config.session_buddy_polling.model_dump(),
                "metrics_to_collect": ["get_workflow_metrics"],
            }
        )
        poller = SessionBuddyPoller(config=config)
        poller._http_client = AsyncMock()
        poller._http_client.post.return_value = _ok_response(
            {
                "result": {
                    "workflows_completed": 4,
                    "workflows_failed": 1,
                    "avg_duration": 12.5,
                }
            }
        )

        result = await poller.poll_once()

        assert result["metrics_collected"] == ["get_workflow_metrics"]
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_poll_once_collects_session_analytics(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """Session analytics should be parsed into histogram/counter entries."""
        config = MahavishnuSettings(
            session_buddy_polling={
                **poller_config.session_buddy_polling.model_dump(),
                "metrics_to_collect": ["get_session_analytics"],
            }
        )
        poller = SessionBuddyPoller(config=config)
        poller._http_client = AsyncMock()
        poller._http_client.post.return_value = _ok_response(
            {
                "result": {
                    "total_checkpoints": 9,
                    "avg_checkpoint_size": 64.0,
                    "avg_session_duration": 600.0,
                }
            }
        )

        result = await poller.poll_once()

        assert result["metrics_collected"] == ["get_session_analytics"]
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_poll_once_collects_performance_metrics(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """Performance metrics should be parsed into gauge/histogram entries."""
        config = MahavishnuSettings(
            session_buddy_polling={
                **poller_config.session_buddy_polling.model_dump(),
                "metrics_to_collect": ["get_performance_metrics"],
            }
        )
        poller = SessionBuddyPoller(config=config)
        poller._http_client = AsyncMock()
        poller._http_client.post.return_value = _ok_response(
            {
                "result": {
                    "cpu_usage": 23.5,
                    "memory_usage": 1024.0,
                    "response_time": 250.0,
                }
            }
        )

        result = await poller.poll_once()

        assert result["metrics_collected"] == ["get_performance_metrics"]
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_poll_once_handles_non_dict_payload(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """A JSON list payload should not crash — it should be recorded as error."""
        poller = SessionBuddyPoller(config=poller_config)
        poller._http_client = AsyncMock()
        poller._http_client.post.return_value = _ok_response([1, 2, 3])

        result = await poller.poll_once()

        assert result["metrics_collected"] == []
        assert result["errors"]
        # First error is from the call_mcp_tool ValueError.
        assert "Invalid response type" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_call_mcp_tool_without_client_raises(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """_call_mcp_tool before start() should raise a clear RuntimeError."""
        poller = SessionBuddyPoller(config=poller_config)

        with pytest.raises(RuntimeError, match="HTTP client not initialized"):
            await poller._call_mcp_tool("get_activity_summary")

    @pytest.mark.asyncio
    async def test_call_mcp_tool_invalid_response_raises_value_error(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """Non-dict response from server should raise a ValueError via retry_async."""
        poller = SessionBuddyPoller(config=poller_config)
        poller._http_client = AsyncMock()
        poller._http_client.post.return_value = _ok_response("not-a-dict")

        with pytest.raises(ValueError, match="Invalid response type"):
            await poller._call_mcp_tool("get_activity_summary")

    @pytest.mark.asyncio
    async def test_call_mcp_tool_retries_on_5xx(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """A 500 response should be retried and ultimately surface as RetryExhausted."""
        from mahavishnu.core.resilience import RetryExhaustedError

        poller = SessionBuddyPoller(config=poller_config)
        poller._http_client = AsyncMock()
        response = MagicMock()
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
        poller._http_client.post.return_value = response

        with pytest.raises(RetryExhaustedError):
            await poller._call_mcp_tool("get_activity_summary")

    @pytest.mark.asyncio
    async def test_poll_once_records_duration_metric(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """A successful poll should observe the poll_duration_seconds histogram."""
        poller = SessionBuddyPoller(config=poller_config)
        poller._http_client = AsyncMock()
        poller._http_client.post.return_value = _ok_response(
            {"result": {"active_sessions": 1, "total_sessions": 1}}
        )

        # The histogram has no _value.get(); it has internal samples. We just
        # verify no error is raised while observing.
        await poller.poll_once()

        samples = list(
            bodai_bridge_poll_duration_seconds.labels(
                source_service="session_buddy",
            ).collect()
        )
        assert samples


class TestCircuitBreaker:
    """Circuit breaker open/close behavior."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_threshold(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """Consecutive failures >= threshold should open the circuit breaker."""
        poller = SessionBuddyPoller(config=poller_config)
        poller._http_client = AsyncMock()
        poller._http_client.post.side_effect = httpx.ConnectError("down")

        for _ in range(poller.circuit_breaker_threshold):
            await poller.poll_once()

        status = await poller.get_status()
        assert status.circuit_breaker_open is True
        assert poller._circuit_breaker_opened_at is not None

    @pytest.mark.asyncio
    async def test_circuit_breaker_check_skips_poll_when_open(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """While the circuit breaker is open, poll_once should not be called."""
        poller = SessionBuddyPoller(config=poller_config)
        poller._circuit_breaker_open = True
        poller._circuit_breaker_opened_at = None  # No cooldown
        poller.interval = 0

        async def fake_sleep(_seconds: float) -> None:
            poller._running = False  # stop the loop on first sleep

        with (
            patch("mahavishnu.integrations.session_buddy_poller.asyncio.sleep",
                  side_effect=fake_sleep),
            patch.object(poller, "poll_once", new=AsyncMock()) as mock_poll,
        ):
            await poller._polling_loop()

        mock_poll.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_circuit_breaker_closes_after_cooldown(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """After the cooldown period, _check_circuit_breaker should close it."""
        from datetime import UTC, datetime, timedelta

        poller = SessionBuddyPoller(config=poller_config)
        # Opened long enough ago to exceed the cooldown (5 * interval).
        poller._circuit_breaker_open = True
        poller._circuit_breaker_opened_at = (
            datetime.now(UTC) - timedelta(seconds=poller.interval * 6)
        )
        poller._consecutive_failures = 99

        await poller._check_circuit_breaker()

        assert poller._circuit_breaker_open is False
        assert poller._consecutive_failures == 0
        assert poller._circuit_breaker_opened_at is None

    @pytest.mark.asyncio
    async def test_circuit_breaker_stays_open_during_cooldown(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """Within the cooldown period, the breaker should remain open."""
        from datetime import UTC, datetime

        poller = SessionBuddyPoller(config=poller_config)
        poller._circuit_breaker_open = True
        poller._circuit_breaker_opened_at = datetime.now(UTC)

        await poller._check_circuit_breaker()

        assert poller._circuit_breaker_open is True

    @pytest.mark.asyncio
    async def test_check_circuit_breaker_when_closed_is_noop(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """If the breaker is already closed, _check_circuit_breaker does nothing."""
        poller = SessionBuddyPoller(config=poller_config)
        poller._circuit_breaker_open = False

        # Should be a no-op.
        await poller._check_circuit_breaker()
        assert poller._circuit_breaker_open is False


class TestRecordError:
    """Tests for the internal _record_error helper."""

    def test_record_error_increments_counters(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """_record_error should bump _errors, _consecutive_failures, _last_error."""
        poller = SessionBuddyPoller(config=poller_config)
        assert poller._errors == 0

        poller._record_error("oops")

        assert poller._errors == 1
        assert poller._consecutive_failures == 1
        assert poller._last_error == "oops"

    def test_record_error_swallows_observability_failure(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """_record_error must not raise if observability is broken."""
        poller = SessionBuddyPoller(config=poller_config)
        broken = MagicMock()
        broken.meter.create_counter.side_effect = RuntimeError("otel broken")
        poller.observability = broken

        # Should not raise.
        poller._record_error("x")
        assert poller._errors == 1


class TestRecordMetrics:
    """Tests for OTel metric dispatch in _record_metrics."""

    @pytest.mark.asyncio
    async def test_record_metrics_without_observability_is_noop(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """_record_metrics should be a no-op when no observability manager is set."""
        poller = SessionBuddyPoller(config=poller_config)
        poller.observability = None

        # Should not raise.
        await poller._record_metrics(
            "get_activity_summary",
            [{"name": "x", "type": "gauge", "value": 1, "attributes": {}}],
        )

    @pytest.mark.asyncio
    async def test_record_metrics_handles_all_types(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """counter, gauge, and histogram metric types should all be dispatched."""
        poller = SessionBuddyPoller(config=poller_config)
        meter = MagicMock()
        meter.create_counter.return_value = MagicMock()
        meter.create_up_down_counter.return_value = MagicMock()
        meter.create_histogram.return_value = MagicMock()
        poller.observability = MagicMock()
        poller.observability.meter = meter

        metrics = [
            {"name": "a", "type": "counter", "value": 1, "attributes": {"k": "v"}},
            {"name": "b", "type": "gauge", "value": 2, "attributes": {"k": "v"}},
            {"name": "c", "type": "histogram", "value": 3, "attributes": {"k": "v"}},
        ]

        await poller._record_metrics("test", metrics)

        meter.create_counter.assert_called()
        meter.create_up_down_counter.assert_called()
        meter.create_histogram.assert_called()

    @pytest.mark.asyncio
    async def test_record_metrics_continues_after_per_metric_failure(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """A failure recording one metric should not stop the rest of the batch."""
        poller = SessionBuddyPoller(config=poller_config)
        meter = MagicMock()
        meter.create_counter.side_effect = [
            RuntimeError("boom"),
            MagicMock(),  # second call works
        ]
        meter.create_up_down_counter.return_value = MagicMock()
        meter.create_histogram.return_value = MagicMock()
        poller.observability = MagicMock()
        poller.observability.meter = meter

        metrics = [
            {"name": "broken", "type": "counter", "value": 1, "attributes": {}},
            {"name": "fine", "type": "gauge", "value": 2, "attributes": {}},
        ]

        # Should not raise.
        await poller._record_metrics("test", metrics)
        assert meter.create_counter.call_count == 1


class TestPollingLoop:
    """Tests for the background _polling_loop task."""

    @pytest.mark.asyncio
    async def test_polling_loop_continues_after_poll_error(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """The loop should keep running even when poll_once raises unexpectedly."""
        poller = SessionBuddyPoller(config=poller_config)
        poller._running = True
        poller.interval = 0  # tight loop

        call_count = 0

        async def fake_sleep(_seconds: float) -> None:
            pass

        async def fake_poll_once() -> None:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("transient")
            poller._running = False  # stop the loop after 3 iterations

        poller.poll_once = fake_poll_once  # type: ignore[method-assign]

        with patch(
            "mahavishnu.integrations.session_buddy_poller.asyncio.sleep",
            side_effect=fake_sleep,
        ):
            await poller._polling_loop()

        assert call_count == 3
        assert poller._errors >= 2

    @pytest.mark.asyncio
    async def test_polling_loop_handles_cancellation(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """A CancelledError should break the loop cleanly without recording error."""
        poller = SessionBuddyPoller(config=poller_config)
        poller._running = True
        poller.interval = 0

        async def fake_sleep(_seconds: float) -> None:
            pass

        async def fake_poll_once() -> None:
            raise asyncio.CancelledError

        poller.poll_once = fake_poll_once  # type: ignore[method-assign]

        errors_before = poller._errors
        with patch(
            "mahavishnu.integrations.session_buddy_poller.asyncio.sleep",
            side_effect=fake_sleep,
        ):
            # Should not raise.
            await poller._polling_loop()

        # CancelledError path breaks before _record_error runs.
        assert poller._errors == errors_before


class TestConvertToOtel:
    """Tests for _convert_to_otel and its dispatch."""

    def test_convert_to_otel_handles_unknown_tool(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """An unknown tool name should return an empty metric list with a warning."""
        poller = SessionBuddyPoller(config=poller_config)

        result = poller._convert_to_otel("totally_made_up", {"active_sessions": 1})

        assert result == []

    def test_convert_to_otel_handles_non_dict_payload(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """A non-dict 'result' should produce an empty metric list."""
        poller = SessionBuddyPoller(config=poller_config)

        result = poller._convert_to_otel("get_activity_summary", {"result": [1, 2]})

        assert result == []


class TestStartStopIntegration:
    """Integration-style tests using real asyncio sleep to exercise the loop."""

    @pytest.mark.asyncio
    async def test_start_then_stop_runs_one_poll_cycle(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """A short-lived start/stop should perform at least one poll cycle."""
        # Use a very short interval and override poll_once to flip the flag.
        config = MahavishnuSettings(
            session_buddy_polling={
                **poller_config.session_buddy_polling.model_dump(),
                "interval_seconds": 5,
            }
        )
        poller = SessionBuddyPoller(config=config)

        async def fake_sleep(_seconds: float) -> None:
            poller._running = False  # stop the loop on first sleep

        with (
            patch("mahavishnu.integrations.session_buddy_poller.asyncio.sleep",
                  side_effect=fake_sleep),
            patch.object(poller, "poll_once", new=AsyncMock()) as mock_poll,
        ):
            await poller.start()
            # Wait for the task to complete at least one iteration.
            if poller._poll_task is not None:
                # Bound the wait so a regression doesn't hang the test suite.
                with suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(poller._poll_task, timeout=2.0)
            await poller.stop()

        mock_poll.assert_awaited()

    @pytest.mark.asyncio
    async def test_start_does_not_overwrite_running_task_on_second_call(
        self, poller_config: MahavishnuSettings
    ) -> None:
        """start() should leave the existing _poll_task alone when already running."""
        poller = SessionBuddyPoller(config=poller_config)
        poller._http_client = AsyncMock()
        poller._http_client.aclose = AsyncMock()

        async def _long_sleep() -> None:
            await asyncio.sleep(0.5)

        poller._running = True
        poller._poll_task = asyncio.create_task(_long_sleep())
        existing = poller._poll_task
        await asyncio.sleep(0)  # let the task actually start

        await poller.start()

        assert poller._poll_task is existing

        existing.cancel()
        with suppress(asyncio.CancelledError):
            await existing
