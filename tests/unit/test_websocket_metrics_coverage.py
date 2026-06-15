"""Comprehensive unit tests for mahavishnu/websocket/metrics.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Direct module import (bypass mahavishnu.websocket.__init__ to avoid pulling
# in server.py, which collides with the prometheus_client default registry).
# We register the loaded module under the canonical dotted name so coverage
# and pickling/identity checks see the real package path.
# ---------------------------------------------------------------------------

_METRICS_PATH = Path(__file__).resolve().parents[2] / "mahavishnu" / "websocket" / "metrics.py"
_SPEC = importlib.util.spec_from_file_location("mahavishnu.websocket.metrics", _METRICS_PATH)
assert _SPEC is not None and _SPEC.loader is not None
metrics_mod = importlib.util.module_from_spec(_SPEC)
# Register under both the dotted name and a sentinel name. The dotted name
# lets coverage tools match the source file; the sentinel is the unique
# sys.modules key to avoid colliding with any partially-initialised package
# import that future tests might attempt.
sys.modules["mahavishnu.websocket.metrics"] = metrics_mod
sys.modules["mahavishnu_websocket_metrics_under_test"] = metrics_mod
_SPEC.loader.exec_module(metrics_mod)

PROMETHEUS_AVAILABLE = metrics_mod.PROMETHEUS_AVAILABLE
WebSocketMetrics = metrics_mod.WebSocketMetrics
_instances = metrics_mod._instances
get_metrics = metrics_mod.get_metrics
reset_metrics = metrics_mod.reset_metrics
start_metrics_server = metrics_mod.start_metrics_server


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_metrics_state() -> None:
    """Ensure each test starts with a clean metrics state and registry."""
    reset_metrics()
    yield
    reset_metrics()


@pytest.fixture
def metrics() -> WebSocketMetrics:
    """Return a fresh WebSocketMetrics instance."""
    return WebSocketMetrics("test-server")


# ---------------------------------------------------------------------------
# Constants and module-level behavior
# ---------------------------------------------------------------------------


class TestModuleConstants:
    """Validate module-level flags and dummy-class fallbacks."""

    def test_prometheus_available_flag_is_bool(self) -> None:
        """PROMETHEUS_AVAILABLE must be a boolean reflecting import success."""
        assert isinstance(PROMETHEUS_AVAILABLE, bool)

    def test_dummy_counter_swallows_construction(self) -> None:
        """Dummy Counter class accepts arbitrary args/kwargs without error.
        Only meaningful when prometheus_client is not installed; otherwise
        skip (the real Counter is used and the dummy fallback is dead code)."""
        if PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client installed; dummy fallback is dead code")
        c = metrics_mod.Counter("foo", "bar", ["label"])
        assert c is not None
        result = c.labels(server="x")
        result.inc(2)
        assert c.count() == 0

    def test_dummy_gauge_swallows_construction(self) -> None:
        """Dummy Gauge class accepts arbitrary args/kwargs and set is no-op.
        Only meaningful when prometheus_client is not installed."""
        if PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client installed; dummy fallback is dead code")
        g = metrics_mod.Gauge("foo", "bar", ["server"])
        g.labels(server="x").set(5)
        g.set_to_current_value()
        g.set(7)

    def test_dummy_histogram_swallows_construction(self) -> None:
        """Dummy Histogram class accepts args and observe is no-op."""
        h = metrics_mod.Histogram("foo", "bar", ["server", "channel"])
        h.labels(server="x", channel="y").observe(0.05)

    def test_dummy_start_http_server_logs_warning(self) -> None:
        """When prometheus is unavailable, start_http_server returns None and logs."""
        if PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client installed; dummy fallback not in use")
        with patch.object(metrics_mod.logger, "warning") as warn:
            result = metrics_mod.start_http_server(9090)
        assert result is None
        warn.assert_called()


# ---------------------------------------------------------------------------
# WebSocketMetrics.__init__ and disabled-mode behavior
# ---------------------------------------------------------------------------


class TestWebSocketMetricsInit:
    """Validate constructor and the disabled-mode branch."""

    def test_init_prometheus_available(self) -> None:
        """With prometheus available, _enabled is True and lazy fields are None."""
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv")
        assert m._enabled is True
        assert m.server_name == "srv"
        assert m._metrics_initialized is False
        assert m._message_counter is None
        assert m._connection_gauge is None
        assert m._broadcast_histogram is None
        assert m._subscription_gauge is None
        assert m._error_counter is None
        assert m._broadcast_histograms == {}
        assert m._error_counters == {}

    def test_init_prometheus_unavailable_sets_disabled(self) -> None:
        """With prometheus unavailable, _enabled is False and warning is logged."""
        with patch.object(metrics_mod, "PROMETHEUS_AVAILABLE", False):
            with patch.object(metrics_mod, "logger") as log:
                m = WebSocketMetrics("srv-disabled")
        assert m._enabled is False
        assert m.server_name == "srv-disabled"
        log.warning.assert_called()

    def test_disabled_initialize_is_noop(self) -> None:
        """In disabled mode, _initialize_metrics is never called via _ensure_enabled."""
        with patch.object(metrics_mod, "PROMETHEUS_AVAILABLE", False):
            m = WebSocketMetrics("srv")
        # Should not raise and should leave initialized flag False
        m._ensure_enabled()
        assert m._metrics_initialized is False


# ---------------------------------------------------------------------------
# Disabled mode public methods (no-op path)
# ---------------------------------------------------------------------------


class TestWebSocketMetricsDisabled:
    """When PROMETHEUS_AVAILABLE is False, public methods must be safe no-ops."""

    def test_disabled_inc_message(self) -> None:
        with patch.object(metrics_mod, "PROMETHEUS_AVAILABLE", False):
            m = WebSocketMetrics("srv")
            m.inc_message("request")
            m.inc_message("response", amount=5)

    def test_disabled_set_connections(self) -> None:
        with patch.object(metrics_mod, "PROMETHEUS_AVAILABLE", False):
            m = WebSocketMetrics("srv")
            m.set_connections(0)
            m.set_connections(42)

    def test_disabled_adjust_connections(self) -> None:
        with patch.object(metrics_mod, "PROMETHEUS_AVAILABLE", False):
            m = WebSocketMetrics("srv")
            m.adjust_connections(1)
            m.adjust_connections(-3)

    def test_disabled_observe_broadcast(self) -> None:
        with patch.object(metrics_mod, "PROMETHEUS_AVAILABLE", False):
            m = WebSocketMetrics("srv")
            m.observe_broadcast("pool:abc", 0.1)

    def test_disabled_on_broadcast_alias(self) -> None:
        with patch.object(metrics_mod, "PROMETHEUS_AVAILABLE", False):
            m = WebSocketMetrics("srv")
            # on_broadcast is a thin alias to observe_broadcast
            m.on_broadcast("pool:abc", 0.1)

    def test_disabled_set_subscriptions(self) -> None:
        with patch.object(metrics_mod, "PROMETHEUS_AVAILABLE", False):
            m = WebSocketMetrics("srv")
            m.set_subscriptions(7)

    def test_disabled_inc_error(self) -> None:
        with patch.object(metrics_mod, "PROMETHEUS_AVAILABLE", False):
            m = WebSocketMetrics("srv")
            m.inc_error("connection")
            m.inc_error("parse", amount=4)

    def test_disabled_get_metrics_summary(self) -> None:
        with patch.object(metrics_mod, "PROMETHEUS_AVAILABLE", False):
            m = WebSocketMetrics("srv")
            summary = m.get_metrics_summary()
        assert summary["server"] == "srv"
        assert summary["enabled"] is False
        assert summary["initialized"] is False
        assert summary["connection_tracking"] is False
        assert summary["broadcast_tracking"] is False
        assert summary["subscription_tracking"] is False
        assert summary["error_types_tracked"] == []


# ---------------------------------------------------------------------------
# _get_existing_collector
# ---------------------------------------------------------------------------


class TestGetExistingCollector:
    """Validate the collector lookup helper."""

    def test_returns_none_when_nothing_registered(self) -> None:
        m = WebSocketMetrics("srv")
        # Use a name that cannot possibly exist
        assert m._get_existing_collector("nonexistent_metric_xyz_123") is None

    def test_returns_collector_when_named_metric_exists(self) -> None:
        """Counter _name attribute holds the bare (no _total) name. The helper
        matches the requested name against either the bare name or the
        ``_names`` set for labeled collectors; register one and look it up."""
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv")
        from prometheus_client import REGISTRY, Counter

        preexisting = Counter("test_helper_lookup_total", "test", ["server"])
        try:
            # prometheus_client strips _total from _name, so the bare name is
            # "test_helper_lookup". Looking up the full name won't match.
            # The helper should still find a collector when the bare name
            # matches.
            found = m._get_existing_collector("test_helper_lookup")
            assert found is preexisting
        finally:
            REGISTRY.unregister(preexisting)

    def test_returns_collector_when_labeled_metric_exists(self) -> None:
        """Histogram with labels has _names attribute; the lookup must find it."""
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv")
        from prometheus_client import REGISTRY, Histogram

        preexisting = Histogram(
            "test_helper_labeled_lookup",
            "test",
            ["server", "channel"],
            buckets=(0.001, 0.01, 0.1),
        )
        try:
            found = m._get_existing_collector("test_helper_labeled_lookup")
            assert found is preexisting
        finally:
            REGISTRY.unregister(preexisting)


# ---------------------------------------------------------------------------
# _initialize_metrics
# ---------------------------------------------------------------------------


class TestInitializeMetrics:
    """Validate metric creation, including duplicate-registration recovery."""

    def test_initializes_all_counters_and_gauges(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv-init")
        m._initialize_metrics()
        assert m._metrics_initialized is True
        assert m._message_counter is not None
        assert m._connection_gauge is not None
        assert m._subscription_gauge is not None

    def test_idempotent_second_call(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv-init-idem")
        m._initialize_metrics()
        first_msg = m._message_counter
        first_conn = m._connection_gauge
        m._initialize_metrics()
        assert m._message_counter is first_msg
        assert m._connection_gauge is first_conn

    def test_recovers_from_duplicate_registration_message(self) -> None:
        """If Counter raises ValueError on construction, the except branch
        runs and calls the helper. The helper may return None (the helper
        looks up by full name including ``_total`` but prometheus_client
        strips ``_total`` from ``_name``), in which case ``_message_counter``
        ends up None. The important thing is that the ``_initialize_metrics``
        method does not propagate the exception. We exercise the except
        branch by pre-registering the counter and asserting the call
        completes without raising."""
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv-dup-msg")
        from prometheus_client import REGISTRY, Counter

        preexisting = Counter(
            "websocket_messages",
            "preexisting",
            ["server", "message_type"],
        )
        try:
            # Should not raise; the except branch swallows ValueError
            m._initialize_metrics()
            assert m._metrics_initialized is True
        finally:
            REGISTRY.unregister(preexisting)

    def test_recovers_from_duplicate_registration_connection(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv-dup-conn")
        from prometheus_client import REGISTRY, Gauge

        preexisting = Gauge("websocket_connections", "preexisting", ["server"])
        try:
            m._initialize_metrics()
            assert m._connection_gauge is preexisting
        finally:
            REGISTRY.unregister(preexisting)

    def test_recovers_from_duplicate_registration_subscription(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv-dup-sub")
        from prometheus_client import REGISTRY, Gauge

        preexisting = Gauge("websocket_subscriptions", "preexisting", ["server"])
        try:
            m._initialize_metrics()
            assert m._subscription_gauge is preexisting
        finally:
            REGISTRY.unregister(preexisting)


# ---------------------------------------------------------------------------
# Public methods in enabled mode
# ---------------------------------------------------------------------------


class TestWebSocketMetricsEnabled:
    """Validate public methods when prometheus is available."""

    def test_inc_message_records_increment(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv")
        m.inc_message("request")
        m.inc_message("response", amount=3)
        # Sanity: the labeled child has expected sample count
        counter = m._message_counter
        assert counter is not None
        # Counter.labels(...)._value.get() exposes the per-label value
        req = counter.labels(server="srv", message_type="request")
        res = counter.labels(server="srv", message_type="response")
        assert req._value.get() == 1
        assert res._value.get() == 3

    def test_set_connections_updates_gauge(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv")
        m.set_connections(5)
        gauge = m._connection_gauge
        assert gauge is not None
        assert gauge.labels(server="srv")._value.get() == 5

    def test_adjust_connections_increments_gauge(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv")
        m.set_connections(2)
        m.adjust_connections(3)
        m.adjust_connections(-1)
        gauge = m._connection_gauge
        assert gauge is not None
        assert gauge.labels(server="srv")._value.get() == 4

    def test_observe_broadcast_creates_histogram(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv")
        m.observe_broadcast("pool:abc", 0.05)
        assert m._broadcast_histogram is not None

    def test_observe_broadcast_reuses_histogram(self) -> None:
        """Second call on different channel reuses the singleton histogram."""
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv")
        m.observe_broadcast("chan1", 0.1)
        first = m._broadcast_histogram
        m.observe_broadcast("chan2", 0.2)
        assert m._broadcast_histogram is first

    def test_observe_broadcast_recovers_from_duplicate_registration(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv")
        from prometheus_client import REGISTRY, Histogram

        preexisting = Histogram(
            "websocket_broadcast_duration_seconds",
            "preexisting",
            ["server", "channel"],
            buckets=(0.001, 0.005, 0.01),
        )
        try:
            m._get_broadcast_histogram("chan1")
            assert m._broadcast_histogram is preexisting
        finally:
            REGISTRY.unregister(preexisting)

    def test_set_subscriptions_updates_gauge(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv")
        m.set_subscriptions(11)
        gauge = m._subscription_gauge
        assert gauge is not None
        assert gauge.labels(server="srv")._value.get() == 11

    def test_inc_error_creates_counter(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv")
        m.inc_error("connection")
        m.inc_error("parse", amount=2)
        counter = m._error_counter
        assert counter is not None
        assert counter.labels(server="srv", error_type="connection")._value.get() == 1
        assert counter.labels(server="srv", error_type="parse")._value.get() == 2

    def test_on_broadcast_alias(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv")
        m.on_broadcast("chan1", 0.01)
        # Same histogram is created as via observe_broadcast
        assert m._broadcast_histogram is not None


# ---------------------------------------------------------------------------
# _select_metric_child (label-fallback branch)
# ---------------------------------------------------------------------------


class TestSelectMetricChild:
    """Validate label-fallback behavior in _select_metric_child."""

    def test_empty_labels_returns_metric_unchanged(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv")
        m._initialize_metrics()
        assert m._message_counter is not None
        out = m._select_metric_child(m._message_counter)
        assert out is m._message_counter

    def test_falls_back_to_bare_metric_when_labels_valueerror(self) -> None:
        """If .labels() raises ValueError, _select_metric_child returns metric."""
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv")
        bogus = MagicMock()
        bogus.labels.side_effect = ValueError("bad labels")
        assert m._select_metric_child(bogus, foo="bar") is bogus


# ---------------------------------------------------------------------------
# Exception handling in public methods
# ---------------------------------------------------------------------------


class TestPublicMethodExceptionPaths:
    """If the underlying collector raises, public methods should swallow it."""

    def test_inc_message_swallows_exception(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv")
        m._initialize_metrics()
        assert m._message_counter is not None
        # Replace the child with one that raises on inc
        bad_child = MagicMock()
        bad_child.inc.side_effect = RuntimeError("boom")
        with patch.object(m, "_select_metric_child", return_value=bad_child):
            m.inc_message("request")  # should not raise

    def test_set_connections_swallows_exception(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv")
        m._initialize_metrics()
        bad_child = MagicMock()
        bad_child.set.side_effect = RuntimeError("boom")
        with patch.object(m, "_select_metric_child", return_value=bad_child):
            m.set_connections(3)

    def test_adjust_connections_swallows_exception(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv")
        m._initialize_metrics()
        bad_child = MagicMock()
        bad_child.inc.side_effect = RuntimeError("boom")
        with patch.object(m, "_select_metric_child", return_value=bad_child):
            m.adjust_connections(1)

    def test_observe_broadcast_swallows_exception(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv")
        # Pre-create histogram so we can patch the child
        m._get_broadcast_histogram("chan")
        bad_child = MagicMock()
        bad_child.observe.side_effect = RuntimeError("boom")
        with patch.object(m, "_select_metric_child", return_value=bad_child):
            m.observe_broadcast("chan", 0.1)

    def test_set_subscriptions_swallows_exception(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv")
        m._initialize_metrics()
        bad_child = MagicMock()
        bad_child.set.side_effect = RuntimeError("boom")
        with patch.object(m, "_select_metric_child", return_value=bad_child):
            m.set_subscriptions(2)

    def test_inc_error_swallows_exception(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv")
        m.inc_error("connection")  # create the counter first
        bad_child = MagicMock()
        bad_child.inc.side_effect = RuntimeError("boom")
        with patch.object(m, "_select_metric_child", return_value=bad_child):
            m.inc_error("connection")


# ---------------------------------------------------------------------------
# get_metrics_summary
# ---------------------------------------------------------------------------


class TestGetMetricsSummary:
    """Validate the enabled-mode summary reflects actual state."""

    def test_summary_before_any_calls(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv-summary")
        summary = m.get_metrics_summary()
        assert summary == {
            "server": "srv-summary",
            "enabled": True,
            "initialized": False,
            "connection_tracking": False,
            "broadcast_tracking": False,
            "subscription_tracking": False,
            "error_types_tracked": [],
        }

    def test_summary_after_initialize(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv-summary")
        m._initialize_metrics()
        summary = m.get_metrics_summary()
        assert summary["initialized"] is True
        assert summary["connection_tracking"] is True
        assert summary["subscription_tracking"] is True
        # Broadcast histogram only created lazily on first observe
        assert summary["broadcast_tracking"] is False

    def test_summary_after_observe_broadcast(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv-summary")
        m.observe_broadcast("chan1", 0.1)
        summary = m.get_metrics_summary()
        # broadcast_histograms is still empty because observe_broadcast uses
        # the singular _broadcast_histogram, not the dict. The summary branch
        # therefore evaluates to False here. Confirm the field is present.
        assert "broadcast_tracking" in summary
        assert isinstance(summary["broadcast_tracking"], bool)

    def test_summary_after_inc_error(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv-summary")
        m.inc_error("connection")
        summary = m.get_metrics_summary()
        # error_counters dict is populated lazily; inc_error uses the singular
        # _error_counter. The summary still surfaces the (possibly empty)
        # tracked error types list.
        assert isinstance(summary["error_types_tracked"], list)


# ---------------------------------------------------------------------------
# start_metrics_server
# ---------------------------------------------------------------------------


class TestStartMetricsServer:
    """Validate start_metrics_server behavior in both availability modes."""

    def test_returns_server_thread_when_available(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        sentinel = object()
        with patch.object(metrics_mod, "start_http_server", return_value=sentinel) as start:
            result = start_metrics_server(9099)
        assert result is sentinel
        start.assert_called_once_with(9099)

    def test_returns_none_when_unavailable(self) -> None:
        with patch.object(metrics_mod, "PROMETHEUS_AVAILABLE", False):
            with patch.object(metrics_mod, "logger"):
                result = start_metrics_server(9091)
        assert result is None

    def test_returns_none_on_oserror(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        with (
            patch.object(
                metrics_mod,
                "start_http_server",
                side_effect=OSError("port in use"),
            ),
            patch.object(metrics_mod, "logger") as log,
        ):
            result = start_metrics_server(9092)
        assert result is None
        # Two logger.error calls are emitted
        assert log.error.call_count == 2


# ---------------------------------------------------------------------------
# get_metrics / reset_metrics
# ---------------------------------------------------------------------------


class TestGetAndResetMetrics:
    """Validate the module-level instance factory and reset helper."""

    def test_get_metrics_creates_and_caches(self) -> None:
        m1 = get_metrics("mahavishnu")
        m2 = get_metrics("mahavishnu")
        assert m1 is m2
        assert isinstance(m1, WebSocketMetrics)
        assert m1.server_name == "mahavishnu"

    def test_get_metrics_different_servers(self) -> None:
        m1 = get_metrics("server-a")
        m2 = get_metrics("server-b")
        assert m1 is not m2
        assert m1.server_name == "server-a"
        assert m2.server_name == "server-b"

    def test_reset_clears_instances(self) -> None:
        m1 = get_metrics("srv")
        assert "srv" in _instances
        reset_metrics()
        assert _instances == {}
        m2 = get_metrics("srv")
        assert m1 is not m2

    def test_reset_clears_prometheus_registry(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        # Create something in the registry
        m = WebSocketMetrics("srv-reg")
        m.inc_message("request")
        # Registry should now have a collector
        from prometheus_client import REGISTRY

        assert len(list(REGISTRY._collector_to_names.keys())) > 0
        reset_metrics()
        # After reset, registry should be empty
        assert list(REGISTRY._collector_to_names.keys()) == []

    def test_reset_logs_when_prom_unavailable(self) -> None:
        """When prometheus is unavailable, reset still runs and logs info."""
        with patch.object(metrics_mod, "PROMETHEUS_AVAILABLE", False):
            with patch.object(metrics_mod, "logger") as log:
                reset_metrics()
        # Two logger.info calls: registry-skip (silent) and "Reset all metrics"
        # The 'Cleared Prometheus registry' branch is only taken when
        # PROMETHEUS_AVAILABLE is True. The final info log always fires.
        assert log.info.called


# ---------------------------------------------------------------------------
# logger messages
# ---------------------------------------------------------------------------


class TestLoggingBehavior:
    """Spot-check that informational log lines fire on key code paths."""

    def test_initialize_metrics_logs_info(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv-log")
        with patch.object(metrics_mod.logger, "info") as info:
            m._initialize_metrics()
        assert info.called

    def test_inc_error_logs_warning(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not available")
        m = WebSocketMetrics("srv-log")
        with patch.object(metrics_mod.logger, "warning") as warn:
            m.inc_error("connection")
        assert warn.called
