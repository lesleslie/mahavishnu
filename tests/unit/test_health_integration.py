"""Tests for core/health_integration.py — adapter health monitoring.

Tests cover:
- HealthIntegrationConfig defaults and custom values
- AdapterHealthState.update() state transitions
- AdapterHealthState.to_dict() serialization
- AdapterHealthMonitor initialization and adapter access
- AdapterHealthMonitor.check_adapter_health() with various adapter types
- AdapterHealthMonitor.check_all_health() aggregation
- Health state change handling (broadcast, alert, router, persistence)
- Periodic check lifecycle (start/stop)
- Health summary and single-adapter queries
- Singleton functions (get_health_monitor, initialize_health_monitor)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.health_integration import (
    AdapterHealthMonitor,
    AdapterHealthState,
    HealthIntegrationConfig,
    get_health_monitor,
    initialize_health_monitor,
)

# ---------------------------------------------------------------------------
# HealthIntegrationConfig
# ---------------------------------------------------------------------------


class TestHealthIntegrationConfig:
    def test_defaults(self):
        cfg = HealthIntegrationConfig()
        assert cfg.check_interval_seconds == 60
        assert cfg.unhealthy_threshold == 3
        assert cfg.recovery_threshold == 1
        assert cfg.broadcast_changes is True
        assert cfg.persist_to_storage is True
        assert cfg.update_router_preferences is True

    def test_custom_values(self):
        cfg = HealthIntegrationConfig(
            check_interval_seconds=30,
            unhealthy_threshold=5,
            recovery_threshold=2,
            broadcast_changes=False,
            persist_to_storage=False,
            update_router_preferences=False,
        )
        assert cfg.check_interval_seconds == 30
        assert cfg.unhealthy_threshold == 5
        assert cfg.recovery_threshold == 2
        assert cfg.broadcast_changes is False


# ---------------------------------------------------------------------------
# AdapterHealthState
# ---------------------------------------------------------------------------


class TestAdapterHealthState:
    def test_initial_state(self):
        state = AdapterHealthState(adapter_name="test_adapter")
        assert state.adapter_name == "test_adapter"
        assert state.is_healthy is True
        assert state.consecutive_failures == 0
        assert state.consecutive_successes == 0
        assert state.current_health == {}
        assert state.last_check_time is None
        assert state.last_state_change is None
        assert state.failure_history == []

    def test_update_healthy_no_change(self):
        cfg = HealthIntegrationConfig()
        state = AdapterHealthState(adapter_name="a")
        changed = state.update({"status": "healthy"}, cfg)
        assert changed is False
        assert state.is_healthy is True
        assert state.consecutive_successes == 1
        assert state.last_check_time is not None

    def test_update_healthy_increments_successes(self):
        cfg = HealthIntegrationConfig(recovery_threshold=2)
        state = AdapterHealthState(adapter_name="a", is_healthy=False)
        # First healthy check: not yet recovered (need 2)
        changed = state.update({"status": "healthy"}, cfg)
        assert changed is False
        assert state.is_healthy is False
        assert state.consecutive_successes == 1
        # Second healthy check: now recovered
        changed = state.update({"status": "healthy"}, cfg)
        assert changed is True
        assert state.is_healthy is True

    def test_update_unhealthy_resets_successes(self):
        cfg = HealthIntegrationConfig(unhealthy_threshold=2)
        state = AdapterHealthState(adapter_name="a")
        state.consecutive_successes = 5
        changed = state.update({"status": "unhealthy"}, cfg)
        assert changed is False
        assert state.consecutive_successes == 0
        assert state.consecutive_failures == 1

    def test_update_unhealthy_triggers_threshold(self):
        cfg = HealthIntegrationConfig(unhealthy_threshold=2)
        state = AdapterHealthState(adapter_name="a")
        state.update({"status": "unhealthy"}, cfg)
        changed = state.update({"status": "unhealthy"}, cfg)
        assert changed is True
        assert state.is_healthy is False
        assert state.last_state_change is not None

    def test_update_degraded_counts_as_failure(self):
        cfg = HealthIntegrationConfig(unhealthy_threshold=1)
        state = AdapterHealthState(adapter_name="a")
        changed = state.update({"status": "degraded"}, cfg)
        assert changed is True
        assert state.is_healthy is False

    def test_update_records_failure_history(self):
        cfg = HealthIntegrationConfig()
        state = AdapterHealthState(adapter_name="a")
        state.update({"status": "unhealthy", "error": "conn refused"}, cfg)
        assert len(state.failure_history) == 1
        assert "conn refused" in state.failure_history[0]

    def test_update_failure_history_bounded(self):
        cfg = HealthIntegrationConfig()
        state = AdapterHealthState(adapter_name="a")
        for i in range(15):
            state.update({"status": "unhealthy", "error": f"err-{i}"}, cfg)
        assert len(state.failure_history) == 10

    def test_update_unknown_status_no_change(self):
        cfg = HealthIntegrationConfig()
        state = AdapterHealthState(adapter_name="a")
        changed = state.update({"status": "unknown"}, cfg)
        assert changed is False
        assert state.is_healthy is True

    def test_update_healthy_resets_failures(self):
        cfg = HealthIntegrationConfig()
        state = AdapterHealthState(adapter_name="a")
        state.consecutive_failures = 5
        state.update({"status": "healthy"}, cfg)
        assert state.consecutive_failures == 0
        assert state.consecutive_successes == 1

    def test_recovery_threshold_default(self):
        """Default recovery_threshold=1 means one healthy check recovers."""
        cfg = HealthIntegrationConfig()
        state = AdapterHealthState(adapter_name="a", is_healthy=False)
        changed = state.update({"status": "healthy"}, cfg)
        assert changed is True
        assert state.is_healthy is True

    def test_to_dict(self):
        state = AdapterHealthState(adapter_name="test")
        state.update({"status": "healthy", "extra": True}, HealthIntegrationConfig())
        d = state.to_dict()
        assert d["adapter_name"] == "test"
        assert d["is_healthy"] is True
        assert d["current_status"] == "healthy"
        assert d["consecutive_failures"] == 0
        assert d["consecutive_successes"] == 1
        assert d["last_check_time"] is not None
        assert d["failure_count"] == 0
        assert d["details"]["extra"] is True

    def test_to_dict_no_timestamps(self):
        state = AdapterHealthState(adapter_name="x")
        d = state.to_dict()
        assert d["last_check_time"] is None
        assert d["last_state_change"] is None


# ---------------------------------------------------------------------------
# AdapterHealthMonitor._get_adapters
# ---------------------------------------------------------------------------


class TestGetAdapters:
    def test_dict_registry(self):
        monitor = AdapterHealthMonitor(registry={"a": MagicMock(), "b": MagicMock()})
        adapters = monitor._get_adapters()
        assert set(adapters.keys()) == {"a", "b"}

    def test_object_with_adapters_attr(self):
        registry = MagicMock()
        registry.adapters = {"x": MagicMock()}
        monitor = AdapterHealthMonitor(registry=registry)
        adapters = monitor._get_adapters()
        assert "x" in adapters

    def test_unknown_type_returns_empty(self):
        monitor = AdapterHealthMonitor(registry="not_a_registry")
        assert monitor._get_adapters() == {}


# ---------------------------------------------------------------------------
# AdapterHealthMonitor.check_adapter_health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCheckAdapterHealth:
    async def test_missing_adapter(self):
        monitor = AdapterHealthMonitor(registry={})
        result = await monitor.check_adapter_health("nonexistent")
        assert result["status"] == "not_configured"

    async def test_adapter_with_get_health(self):
        adapter = AsyncMock()
        adapter.get_health = AsyncMock(return_value={"status": "healthy"})
        monitor = AdapterHealthMonitor(registry={"my_adapter": adapter})
        result = await monitor.check_adapter_health("my_adapter")
        assert result["status"] == "healthy"
        assert result["adapter"] == "my_adapter"
        assert "timestamp" in result

    async def test_adapter_without_get_health(self):
        adapter = MagicMock(spec=[])  # No methods at all
        monitor = AdapterHealthMonitor(registry={"basic": adapter})
        result = await monitor.check_adapter_health("basic")
        assert result["status"] == "healthy"
        assert "No health check method" in result["message"]

    async def test_adapter_health_exception(self):
        adapter = AsyncMock()
        adapter.get_health = AsyncMock(side_effect=ConnectionError("refused"))
        monitor = AdapterHealthMonitor(registry={"fail": adapter})
        result = await monitor.check_adapter_health("fail")
        assert result["status"] == "error"
        assert "refused" in result["error"]

    async def test_creates_health_state(self):
        adapter = AsyncMock()
        adapter.get_health = AsyncMock(return_value={"status": "healthy"})
        monitor = AdapterHealthMonitor(registry={"a": adapter})
        await monitor.check_adapter_health("a")
        assert "a" in monitor.health_states

    async def test_state_change_to_unhealthy(self):
        cfg = HealthIntegrationConfig(unhealthy_threshold=1)
        adapter = AsyncMock()
        adapter.get_health = AsyncMock(return_value={"status": "unhealthy", "error": "down"})
        monitor = AdapterHealthMonitor(registry={"a": adapter}, config=cfg)
        await monitor.check_adapter_health("a")
        assert monitor.health_states["a"].is_healthy is False


# ---------------------------------------------------------------------------
# AdapterHealthMonitor.check_all_health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCheckAllHealth:
    async def test_checks_all_adapters(self):
        a1 = AsyncMock()
        a1.get_health = AsyncMock(return_value={"status": "healthy"})
        a2 = AsyncMock()
        a2.get_health = AsyncMock(return_value={"status": "degraded"})
        monitor = AdapterHealthMonitor(registry={"a1": a1, "a2": a2})
        results = await monitor.check_all_health()
        assert "a1" in results
        assert "a2" in results

    async def test_handles_exception_in_check(self):
        a1 = AsyncMock()
        a1.get_health = AsyncMock(return_value={"status": "healthy"})
        a2 = AsyncMock()
        a2.get_health = AsyncMock(side_effect=RuntimeError("boom"))
        monitor = AdapterHealthMonitor(registry={"a1": a1, "a2": a2})
        results = await monitor.check_all_health()
        assert results["a2"]["status"] == "error"
        assert "boom" in results["a2"]["error"]


# ---------------------------------------------------------------------------
# AdapterHealthMonitor._update_prometheus_metrics
# ---------------------------------------------------------------------------


class TestUpdatePrometheusMetrics:
    def test_healthy_gauge(self):
        monitor = AdapterHealthMonitor(registry={})
        mock_gauge = MagicMock()
        monitor._health_gauge = mock_gauge
        monitor._update_prometheus_metrics("a", {"status": "healthy"}, MagicMock())
        mock_gauge.labels.assert_called_once_with(server="mahavishnu", adapter="a")
        mock_gauge.labels.return_value.set.assert_called_once_with(1.0)

    def test_degraded_gauge(self):
        monitor = AdapterHealthMonitor(registry={})
        mock_gauge = MagicMock()
        monitor._health_gauge = mock_gauge
        monitor._update_prometheus_metrics("a", {"status": "degraded"}, MagicMock())
        mock_gauge.labels.return_value.set.assert_called_once_with(0.5)

    def test_unhealthy_gauge(self):
        monitor = AdapterHealthMonitor(registry={})
        mock_gauge = MagicMock()
        monitor._health_gauge = mock_gauge
        monitor._update_prometheus_metrics("a", {"status": "unhealthy"}, MagicMock())
        mock_gauge.labels.return_value.set.assert_called_once_with(0.0)

    def test_no_gauge_skipped(self):
        monitor = AdapterHealthMonitor(registry={})
        monitor._health_gauge = None
        # Should not raise
        monitor._update_prometheus_metrics("a", {"status": "healthy"}, MagicMock())


# ---------------------------------------------------------------------------
# AdapterHealthMonitor._handle_health_state_change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestHandleHealthStateChange:
    async def test_broadcasts_when_configured(self):
        ws = MagicMock()
        ws.broadcast_to_room = AsyncMock()
        cfg = HealthIntegrationConfig(
            broadcast_changes=True, persist_to_storage=False, update_router_preferences=False
        )
        monitor = AdapterHealthMonitor(registry={}, websocket_server=ws, config=cfg)
        state = AdapterHealthState(adapter_name="a")
        state.update({"status": "unhealthy"}, cfg)
        with patch(
            "mahavishnu.core.health_integration.WebSocketProtocol", create=True
        ) as mock_proto:
            mock_proto.create_event = MagicMock(return_value={"event": "data"})
            await monitor._handle_health_state_change("a", True, state)
            ws.broadcast_to_room.assert_called_once()

    async def test_no_broadcast_when_disabled(self):
        cfg = HealthIntegrationConfig(
            broadcast_changes=False, persist_to_storage=False, update_router_preferences=False
        )
        monitor = AdapterHealthMonitor(registry={}, config=cfg)
        state = AdapterHealthState(adapter_name="a")
        # Should not raise even with no websocket
        await monitor._handle_health_state_change("a", True, state)

    async def test_alert_on_unhealthy(self):
        alert_mgr = MagicMock()
        alert_mgr.handlers = []
        cfg = HealthIntegrationConfig(persist_to_storage=False, update_router_preferences=False)
        monitor = AdapterHealthMonitor(registry={}, alert_manager=alert_mgr, config=cfg)
        state = AdapterHealthState(adapter_name="a", is_healthy=False)
        with (
            patch("mahavishnu.core.health_integration.Alert", create=True),
            patch("mahavishnu.core.health_integration.AlertSeverity", create=True),
            patch("mahavishnu.core.health_integration.AlertType", create=True),
        ):
            await monitor._handle_health_state_change("a", True, state)

    async def test_no_alert_on_recovery(self):
        alert_mgr = MagicMock()
        alert_mgr.handlers = []
        cfg = HealthIntegrationConfig(persist_to_storage=False, update_router_preferences=False)
        monitor = AdapterHealthMonitor(registry={}, alert_manager=alert_mgr, config=cfg)
        state = AdapterHealthState(adapter_name="a", is_healthy=True)
        # Recovery (healthy) should not trigger alert even with alert_manager
        await monitor._handle_health_state_change("a", False, state)


# ---------------------------------------------------------------------------
# AdapterHealthMonitor.get_health_summary
# ---------------------------------------------------------------------------


class TestGetHealthSummary:
    def test_empty_registry(self):
        monitor = AdapterHealthMonitor(registry={})
        summary = monitor.get_health_summary()
        assert summary["total_adapters"] == 0
        assert summary["healthy"] == 0
        assert summary["unhealthy"] == 0
        assert summary["health_percentage"] == 100.0
        assert summary["monitor_running"] is False

    def test_with_states(self):
        monitor = AdapterHealthMonitor(registry={"a": MagicMock(), "b": MagicMock()})
        monitor.health_states["a"] = AdapterHealthState(adapter_name="a")
        monitor.health_states["a"].is_healthy = True
        monitor.health_states["b"] = AdapterHealthState(adapter_name="b")
        monitor.health_states["b"].is_healthy = False
        summary = monitor.get_health_summary()
        assert summary["total_adapters"] == 2
        assert summary["healthy"] == 1
        assert summary["unhealthy"] == 1
        assert summary["health_percentage"] == 50.0


# ---------------------------------------------------------------------------
# AdapterHealthMonitor.get_adapter_health
# ---------------------------------------------------------------------------


class TestGetAdapterHealth:
    def test_found(self):
        monitor = AdapterHealthMonitor(registry={})
        monitor.health_states["x"] = AdapterHealthState(adapter_name="x")
        result = monitor.get_adapter_health("x")
        assert result is not None
        assert result["adapter_name"] == "x"

    def test_not_found(self):
        monitor = AdapterHealthMonitor(registry={})
        assert monitor.get_adapter_health("missing") is None


# ---------------------------------------------------------------------------
# Periodic check lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPeriodicChecks:
    async def test_start_and_stop(self):
        monitor = AdapterHealthMonitor(
            registry={},
            config=HealthIntegrationConfig(check_interval_seconds=600),
        )
        await monitor.start_periodic_checks()
        assert monitor._monitor_task is not None
        assert not monitor._monitor_task.done()
        await monitor.stop_periodic_checks()
        assert monitor._monitor_task is None

    async def test_start_twice_warns(self, caplog):
        import logging

        monitor = AdapterHealthMonitor(
            registry={},
            config=HealthIntegrationConfig(check_interval_seconds=600),
        )
        await monitor.start_periodic_checks()
        try:
            with caplog.at_level(logging.WARNING):
                await monitor.start_periodic_checks()
            assert "already running" in caplog.text.lower()
        finally:
            await monitor.stop_periodic_checks()

    async def test_stop_when_not_started(self):
        monitor = AdapterHealthMonitor(registry={})
        # Should not raise
        await monitor.stop_periodic_checks()

    async def test_start_with_custom_interval(self):
        monitor = AdapterHealthMonitor(
            registry={},
            config=HealthIntegrationConfig(check_interval_seconds=600),
        )
        await monitor.start_periodic_checks(interval=5)
        try:
            assert monitor._monitor_task is not None
        finally:
            await monitor.stop_periodic_checks()


# ---------------------------------------------------------------------------
# Singleton functions
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_raises_when_not_initialized(self):
        import mahavishnu.core.health_integration as mod

        original = mod._health_monitor
        mod._health_monitor = None
        try:
            with pytest.raises(RuntimeError, match="not initialized"):
                get_health_monitor()
        finally:
            mod._health_monitor = original

    def test_get_returns_instance(self):
        import mahavishnu.core.health_integration as mod

        mock_instance = MagicMock(spec=AdapterHealthMonitor)
        original = mod._health_monitor
        mod._health_monitor = mock_instance
        try:
            result = get_health_monitor()
            assert result is mock_instance
        finally:
            mod._health_monitor = original

    @pytest.mark.asyncio
    async def test_initialize_creates_and_starts(self):
        import mahavishnu.core.health_integration as mod

        original = mod._health_monitor
        mod._health_monitor = None
        try:
            instance = await initialize_health_monitor(
                registry={},
                config=HealthIntegrationConfig(check_interval_seconds=600),
                auto_start=True,
            )
            assert isinstance(instance, AdapterHealthMonitor)
            assert mod._health_monitor is instance
            await instance.stop_periodic_checks()
        finally:
            mod._health_monitor = original

    @pytest.mark.asyncio
    async def test_initialize_without_auto_start(self):
        import mahavishnu.core.health_integration as mod

        original = mod._health_monitor
        mod._health_monitor = None
        try:
            instance = await initialize_health_monitor(
                registry={},
                config=HealthIntegrationConfig(),
                auto_start=False,
            )
            assert isinstance(instance, AdapterHealthMonitor)
            assert instance._monitor_task is None
        finally:
            mod._health_monitor = original


# ---------------------------------------------------------------------------
# _persist_health_state (SQLite fallback)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPersistHealthState:
    async def test_persists_to_sqlite_fallback(self, tmp_path, monkeypatch):
        db_path = tmp_path / "health.db"
        monkeypatch.setattr("mahavishnu.core.health_integration._HEALTH_DB", db_path)
        cfg = HealthIntegrationConfig(persist_to_storage=True)
        monitor = AdapterHealthMonitor(registry={}, config=cfg)
        state = AdapterHealthState(adapter_name="test")
        state.update({"status": "healthy"}, cfg)
        with patch(
            "mahavishnu.core.oneiric_client.get_dhara_client",
            side_effect=ImportError("no client"),
        ):
            await monitor._persist_health_state("test", state)
        import sqlite3

        assert db_path.exists()
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM adapter_health WHERE adapter_name = 'test'")
        row = cursor.fetchone()
        conn.close()
        assert row is not None

    async def test_persist_skipped_when_disabled(self):
        """When persist_to_storage is False, the caller (_handle_health_state_change)
        skips calling _persist_health_state. But if called directly, it still
        attempts to persist — so we just verify it doesn't crash."""
        cfg = HealthIntegrationConfig(persist_to_storage=False)
        monitor = AdapterHealthMonitor(registry={}, config=cfg)
        state = AdapterHealthState(adapter_name="test")
        with patch(
            "mahavishnu.core.oneiric_client.get_dhara_client",
            side_effect=ImportError("no client"),
        ):
            # Method doesn't check config flag itself — caller does
            await monitor._persist_health_state("test", state)


# ---------------------------------------------------------------------------
# _update_router_preferences
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestUpdateRouterPreferences:
    async def test_clears_cache_on_unhealthy(self):
        cfg = HealthIntegrationConfig(update_router_preferences=True)
        monitor = AdapterHealthMonitor(registry={}, config=cfg)
        state = AdapterHealthState(adapter_name="a", is_healthy=False)
        mock_router = MagicMock()
        mock_router._preferences = {"a": 1}
        with patch(
            "mahavishnu.core.statistical_router.get_statistical_router",
            return_value=mock_router,
        ):
            await monitor._update_router_preferences("a", state)
        assert mock_router._preferences == {}

    async def test_handles_import_error(self):
        cfg = HealthIntegrationConfig(update_router_preferences=True)
        monitor = AdapterHealthMonitor(registry={}, config=cfg)
        state = AdapterHealthState(adapter_name="a", is_healthy=False)
        with patch(
            "mahavishnu.core.statistical_router.get_statistical_router",
            side_effect=ImportError,
        ):
            await monitor._update_router_preferences("a", state)
        # Should not raise
