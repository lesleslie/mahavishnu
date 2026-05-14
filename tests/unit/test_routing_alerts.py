"""Tests for core/routing_alerts.py — Alert dataclass, handlers, RoutingAlertManager."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.metrics_schema import AdapterType
from mahavishnu.core.routing_alerts import (
    Alert,
    AlertHandler,
    AlertSeverity,
    AlertType,
    LoggingAlertHandler,
    RoutingAlertManager,
    WebhookAlertHandler,
    get_alert_manager,
    initialize_alert_manager,
)

# =========================================================================
# Alert dataclass
# =========================================================================


class TestAlert:
    def test_to_dict_full(self):
        alert = Alert(
            alert_type=AlertType.ADAPTER_DEGRADATION,
            severity=AlertSeverity.WARNING,
            message="Success rate dropped",
            adapter=AdapterType.PREFECT,
            current_value=0.85,
            threshold_value=0.95,
            metadata={"key": "val"},
        )
        d = alert.to_dict()
        assert d["alert_type"] == "adapter_degradation"
        assert d["severity"] == "warning"
        assert d["message"] == "Success rate dropped"
        assert d["adapter"] == "prefect"
        assert d["current_value"] == 0.85
        assert d["threshold_value"] == 0.95
        assert d["metadata"] == {"key": "val"}
        assert "timestamp" in d

    def test_to_dict_no_adapter(self):
        alert = Alert(
            alert_type=AlertType.COST_SPIKE,
            severity=AlertSeverity.CRITICAL,
            message="Cost spike",
        )
        d = alert.to_dict()
        assert d["adapter"] is None
        assert d["current_value"] is None

    def test_default_timestamp_is_recent(self):
        before = datetime.now(UTC)
        alert = Alert(alert_type=AlertType.COST_SPIKE, severity=AlertSeverity.INFO, message="test")
        after = datetime.now(UTC)
        assert before <= alert.timestamp <= after

    def test_all_severity_values(self):
        for sev in AlertSeverity:
            alert = Alert(alert_type=AlertType.ADAPTER_DEGRADATION, severity=sev, message="m")
            assert alert.severity.value in ("info", "warning", "critical")

    def test_all_type_values(self):
        for t in AlertType:
            alert = Alert(alert_type=t, severity=AlertSeverity.INFO, message="m")
            assert isinstance(alert.alert_type.value, str)


# =========================================================================
# AlertHandler base
# =========================================================================


class TestAlertHandler:
    async def test_base_raises_not_implemented(self):
        handler = AlertHandler()
        alert = Alert(alert_type=AlertType.COST_SPIKE, severity=AlertSeverity.INFO, message="m")
        with pytest.raises(NotImplementedError):
            await handler.send_alert(alert)


# =========================================================================
# LoggingAlertHandler
# =========================================================================


class TestLoggingAlertHandler:
    async def test_send_alert_info(self):
        handler = LoggingAlertHandler()
        alert = Alert(
            alert_type=AlertType.ADAPTER_DEGRADATION,
            severity=AlertSeverity.INFO,
            message="info msg",
        )
        # Should not raise
        await handler.send_alert(alert)

    async def test_send_alert_critical(self):
        handler = LoggingAlertHandler()
        alert = Alert(
            alert_type=AlertType.BUDGET_EXCEEDED,
            severity=AlertSeverity.CRITICAL,
            message="budget exceeded",
        )
        await handler.send_alert(alert)


# =========================================================================
# RoutingAlertManager — cost anomalies
# =========================================================================


class TestRoutingAlertManagerCost:
    async def test_no_alert_on_first_evaluation(self):
        mgr = RoutingAlertManager(handlers=[])
        alerts = await mgr.evaluate_cost_anomalies(100.0)
        assert alerts == []
        # First call sets baseline
        assert mgr._previous_cost_usd == 100.0

    async def test_no_alert_on_normal_increase(self):
        mgr = RoutingAlertManager(handlers=[])
        # Set baseline
        mgr._previous_cost_usd = 100.0
        # 20% increase — below 1.5x multiplier
        alerts = await mgr.evaluate_cost_anomalies(120.0)
        assert alerts == []

    async def test_warning_on_moderate_spike(self):
        mgr = RoutingAlertManager(handlers=[])
        mgr._previous_cost_usd = 100.0
        # 60% increase — between 1.5x and 2x
        alerts = await mgr.evaluate_cost_anomalies(160.0)
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.WARNING
        assert "60%" in alerts[0].message

    async def test_critical_on_large_spike(self):
        mgr = RoutingAlertManager(handlers=[])
        mgr._previous_cost_usd = 100.0
        # 150% increase — above 2x multiplier
        alerts = await mgr.evaluate_cost_anomalies(250.0)
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.CRITICAL
        assert "150%" in alerts[0].message

    async def test_no_alert_when_previous_is_zero(self):
        mgr = RoutingAlertManager(handlers=[])
        mgr._previous_cost_usd = 0.0
        alerts = await mgr.evaluate_cost_anomalies(100.0)
        assert alerts == []

    async def test_updates_previous_cost(self):
        mgr = RoutingAlertManager(handlers=[])
        mgr._previous_cost_usd = 50.0
        await mgr.evaluate_cost_anomalies(75.0)
        assert mgr._previous_cost_usd == 75.0

    async def test_alert_has_metadata(self):
        mgr = RoutingAlertManager(handlers=[])
        mgr._previous_cost_usd = 100.0
        alerts = await mgr.evaluate_cost_anomalies(300.0)
        assert alerts[0].metadata["previous_cost"] == 100.0
        assert "change_percent" in alerts[0].metadata


# =========================================================================
# RoutingAlertManager — fallback patterns
# =========================================================================


class TestRoutingAlertManagerFallback:
    async def test_no_alert_on_zero_executions(self):
        mgr = RoutingAlertManager(handlers=[])
        alerts = await mgr.evaluate_fallback_patterns(5, 0)
        assert alerts == []

    async def test_no_alert_below_threshold(self):
        mgr = RoutingAlertManager(fallback_rate_threshold=0.1)
        alerts = await mgr.evaluate_fallback_patterns(5, 100)
        # 5% fallback rate, below 10% threshold
        assert alerts == []

    async def test_warning_on_moderate_fallbacks(self):
        mgr = RoutingAlertManager(fallback_rate_threshold=0.1)
        alerts = await mgr.evaluate_fallback_patterns(20, 100)
        # 20% fallback rate — above 10%, below 30%
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.WARNING
        assert "20/100" in alerts[0].message

    async def test_critical_on_excessive_fallbacks(self):
        mgr = RoutingAlertManager(fallback_rate_threshold=0.1)
        alerts = await mgr.evaluate_fallback_patterns(40, 100)
        # 40% fallback rate — above 30%
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.CRITICAL

    async def test_alert_metadata(self):
        mgr = RoutingAlertManager(fallback_rate_threshold=0.1)
        alerts = await mgr.evaluate_fallback_patterns(15, 100)
        assert alerts[0].metadata["fallback_count"] == 15
        assert alerts[0].metadata["total_executions"] == 100


# =========================================================================
# RoutingAlertManager — get_status
# =========================================================================


class TestRoutingAlertManagerStatus:
    def test_initial_status(self):
        mgr = RoutingAlertManager(
            success_rate_threshold=0.9,
            fallback_rate_threshold=0.15,
            latency_p95_threshold_ms=3000,
            cost_spike_multiplier=3.0,
            evaluation_interval_seconds=30,
        )
        status = mgr.get_status()
        assert status["success_rate_threshold"] == 0.9
        assert status["fallback_rate_threshold"] == 0.15
        assert status["latency_p95_threshold_ms"] == 3000
        assert status["cost_spike_multiplier"] == 3.0
        assert status["evaluation_interval_seconds"] == 30
        assert status["handlers_count"] == 1  # Default LoggingAlertHandler
        assert status["running"] is False
        assert status["last_evaluation"] is None

    def test_status_with_custom_handlers(self):
        handler = LoggingAlertHandler()
        mgr = RoutingAlertManager(handlers=[handler, handler])
        assert mgr.get_status()["handlers_count"] == 2

    @pytest.mark.asyncio
    async def test_status_running_after_start(self):
        mgr = RoutingAlertManager(handlers=[], evaluation_interval_seconds=3600)
        await mgr.start()
        try:
            status = mgr.get_status()
            assert status["running"] is True
        finally:
            await mgr.stop()

    @pytest.mark.asyncio
    async def test_status_stopped_after_stop(self):
        mgr = RoutingAlertManager(handlers=[], evaluation_interval_seconds=3600)
        await mgr.start()
        await mgr.stop()
        assert mgr.get_status()["running"] is False


# =========================================================================
# RoutingAlertManager — start/stop lifecycle
# =========================================================================


class TestRoutingAlertManagerLifecycle:
    async def test_start_creates_task(self):
        mgr = RoutingAlertManager(handlers=[], evaluation_interval_seconds=3600)
        await mgr.start()
        try:
            assert mgr._alert_task is not None
            assert not mgr._alert_task.done()
        finally:
            await mgr.stop()

    async def test_double_start_warns(self):
        mgr = RoutingAlertManager(handlers=[], evaluation_interval_seconds=3600)
        await mgr.start()
        try:
            # Second start should not create a new task
            first_task = mgr._alert_task
            await mgr.start()
            assert mgr._alert_task is first_task
        finally:
            await mgr.stop()

    async def test_stop_cancels_task(self):
        mgr = RoutingAlertManager(handlers=[], evaluation_interval_seconds=3600)
        await mgr.start()
        await mgr.stop()
        assert mgr._alert_task.done()

    async def test_stop_without_start(self):
        mgr = RoutingAlertManager(handlers=[])
        await mgr.stop()  # Should not raise


# =========================================================================
# get_alert_manager / initialize_alert_manager
# =========================================================================


# =========================================================================
# WebhookAlertHandler
# =========================================================================


class TestWebhookAlertHandler:
    def test_init_stores_url_and_timeout(self):
        handler = WebhookAlertHandler("https://example.com/hook", timeout_seconds=10)
        assert handler.webhook_url == "https://example.com/hook"
        assert handler.timeout_seconds == 10

    def test_init_default_timeout(self):
        handler = WebhookAlertHandler("https://example.com/hook")
        assert handler.timeout_seconds == 5

    def _make_session_mock(self, status: int) -> MagicMock:
        """Build a properly-wired aiohttp.ClientSession mock."""
        mock_response = MagicMock()
        mock_response.status = status

        mock_post_ctx = MagicMock()
        mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post.return_value = mock_post_ctx
        return mock_session

    @pytest.mark.asyncio
    async def test_send_alert_success(self):
        handler = WebhookAlertHandler("https://example.com/hook")
        alert = Alert(
            alert_type=AlertType.ADAPTER_DEGRADATION,
            severity=AlertSeverity.WARNING,
            message="Adapter degraded",
        )
        with patch("aiohttp.ClientSession", return_value=self._make_session_mock(200)):
            await handler.send_alert(alert)  # Should not raise

    @pytest.mark.asyncio
    async def test_send_alert_http_error(self):
        handler = WebhookAlertHandler("https://example.com/hook")
        alert = Alert(
            alert_type=AlertType.COST_SPIKE,
            severity=AlertSeverity.CRITICAL,
            message="Cost spike detected",
        )
        with patch("aiohttp.ClientSession", return_value=self._make_session_mock(500)):
            await handler.send_alert(alert)  # Should log error, not raise

    @pytest.mark.asyncio
    async def test_send_alert_exception(self):
        handler = WebhookAlertHandler("https://example.com/hook")
        alert = Alert(
            alert_type=AlertType.EXCESSIVE_FALLBACKS,
            severity=AlertSeverity.WARNING,
            message="Too many fallbacks",
        )
        with patch("aiohttp.ClientSession", side_effect=RuntimeError("network error")):
            await handler.send_alert(alert)  # Should log error, not raise


# =========================================================================
# initialize_alert_manager
# =========================================================================


class TestInitializeAlertManager:
    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        import mahavishnu.core.routing_alerts as mod

        original = mod._manager
        mod._manager = None
        yield
        mod._manager = original

    @pytest.mark.asyncio
    async def test_initialize_creates_and_starts_manager(self):
        mgr = await initialize_alert_manager(
            success_rate_threshold=0.90,
            fallback_rate_threshold=0.15,
            handlers=[],
        )
        assert isinstance(mgr, RoutingAlertManager)
        assert mgr._alert_task is not None
        await mgr.stop()

    @pytest.mark.asyncio
    async def test_initialize_reuses_existing_manager(self):
        mgr1 = await initialize_alert_manager(handlers=[])
        mgr2 = await initialize_alert_manager(handlers=[])
        assert mgr1 is mgr2
        await mgr1.stop()


# =========================================================================
# get_alert_manager / initialize_alert_manager
# =========================================================================


class TestGlobalAlertManager:
    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        import mahavishnu.core.routing_alerts as mod

        original = mod._manager
        mod._manager = None
        yield
        mod._manager = original

    def test_get_alert_manager_creates_singleton(self):
        mgr = get_alert_manager()
        assert isinstance(mgr, RoutingAlertManager)

    def test_get_alert_manager_returns_same(self):
        mgr1 = get_alert_manager()
        mgr2 = get_alert_manager()
        assert mgr1 is mgr2
