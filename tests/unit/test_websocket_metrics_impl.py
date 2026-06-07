"""Unit tests for mahavishnu/websocket/metrics.py.

Covers the WebSocketMetrics collector, the get_metrics factory, the
start_metrics_server helper, and the reset_metrics utility. The Prometheus
client is patched so the tests never reach the real registry, and the
module-level _instances dict is reset around each test to keep things
isolated.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.websocket import metrics as metrics_module
from mahavishnu.websocket.metrics import (
    PROMETHEUS_AVAILABLE,
    WebSocketMetrics,
    get_metrics,
    reset_metrics,
    start_metrics_server,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _reset_instances():
    """Clear the module-level cache before AND after each test."""
    metrics_module._instances.clear()
    yield
    metrics_module._instances.clear()


@pytest.fixture
def counter_mock():
    """A MagicMock that imitates a Prometheus Counter (labels().inc())."""
    counter = MagicMock(name="counter")
    counter.labels.return_value = counter
    return counter


@pytest.fixture
def gauge_mock():
    """A MagicMock that imitates a Prometheus Gauge (labels().inc/.set)."""
    gauge = MagicMock(name="gauge")
    gauge.labels.return_value = gauge
    return gauge


@pytest.fixture
def histogram_mock():
    """A MagicMock that imitates a Prometheus Histogram (labels().observe)."""
    hist = MagicMock(name="histogram")
    hist.labels.return_value = hist
    return hist


# =============================================================================
# Module-Level Constants
# =============================================================================


class TestPrometheusAvailability:
    """Tests for the module-level PROMETHEUS_AVAILABLE constant."""

    def test_prometheus_flag_is_boolean(self):
        """PROMETHEUS_AVAILABLE is set to a real bool at import time."""
        assert isinstance(PROMETHEUS_AVAILABLE, bool)


# =============================================================================
# WebSocketMetrics Construction
# =============================================================================


class TestWebSocketMetricsInit:
    """Tests for the WebSocketMetrics constructor."""

    def test_server_name_stored(self):
        """server_name is preserved on the instance."""
        m = WebSocketMetrics("test-server")

        assert m.server_name == "test-server"

    def test_init_with_prometheus_enabled(self):
        """When Prometheus is available, _enabled is True."""
        if PROMETHEUS_AVAILABLE:
            m = WebSocketMetrics("s")
            assert m._enabled is True
        else:
            pytest.skip("prometheus_client not installed in this environment")

    def test_init_without_prometheus_disables_metrics(self, monkeypatch):
        """Without prometheus_client, _enabled is False and all operations no-op."""
        monkeypatch.setattr(metrics_module, "PROMETHEUS_AVAILABLE", False)
        m = WebSocketMetrics("s")

        assert m._enabled is False
        # The summary method references attributes that only exist once
        # metrics are wired up - pre-create them as empty so the call
        # doesn't raise.
        m._broadcast_histograms = {}  # type: ignore[attr-defined]
        m._error_counters = {}  # type: ignore[attr-defined]
        # Every method should silently no-op
        m.inc_message("request")
        m.set_connections(5)
        m.adjust_connections(1)
        m.observe_broadcast("ch", 0.1)
        m.set_subscriptions(2)
        m.inc_error("auth")
        m.on_broadcast("ch", 0.1)
        # get_metrics_summary should still work
        summary = m.get_metrics_summary()
        assert summary["enabled"] is False
        assert summary["initialized"] is False

    def test_metrics_start_uninitialized(self):
        """Lazy metric slots are None until first use."""
        m = WebSocketMetrics("s")

        assert m._metrics_initialized is False
        assert m._message_counter is None
        assert m._connection_gauge is None
        assert m._broadcast_histogram is None
        assert m._subscription_gauge is None
        assert m._error_counter is None


# =============================================================================
# inc_message() Tests
# =============================================================================


class TestIncMessage:
    """Tests for the inc_message counter helper."""

    def test_inc_message_calls_labels_and_inc(self, counter_mock):
        """inc_message delegates to labels(server, message_type).inc()."""
        m = WebSocketMetrics("svc")
        m._message_counter = counter_mock
        m._metrics_initialized = True
        m._enabled = True

        m.inc_message("request", amount=3)

        counter_mock.labels.assert_called_with(server="svc", message_type="request")
        counter_mock.labels.return_value.inc.assert_called_with(3)

    def test_inc_message_default_amount_is_one(self, counter_mock):
        """Default amount argument is 1."""
        m = WebSocketMetrics("svc")
        m._message_counter = counter_mock
        m._metrics_initialized = True
        m._enabled = True

        m.inc_message("event")

        counter_mock.labels.return_value.inc.assert_called_with(1)

    @pytest.mark.parametrize("message_type", ["request", "response", "event", "error"])
    def test_inc_message_supports_various_types(self, counter_mock, message_type):
        """inc_message passes the message type to labels."""
        m = WebSocketMetrics("svc")
        m._message_counter = counter_mock
        m._metrics_initialized = True
        m._enabled = True

        m.inc_message(message_type)

        counter_mock.labels.assert_called_with(server="svc", message_type=message_type)

    def test_inc_message_swallows_label_errors(self):
        """If labels() raises ValueError, inc_message falls back to the bare counter."""
        m = WebSocketMetrics("svc")
        counter = MagicMock()
        counter.labels.side_effect = ValueError("unknown label")
        m._message_counter = counter
        m._metrics_initialized = True
        m._enabled = True

        # Should not raise
        m.inc_message("request", amount=2)
        counter.inc.assert_called_with(2)

    def test_inc_message_swallows_metric_update_errors(self):
        """A failure in the underlying inc() does not propagate."""
        m = WebSocketMetrics("svc")
        counter = MagicMock()
        counter.labels.return_value = counter
        counter.inc.side_effect = RuntimeError("boom")
        m._message_counter = counter
        m._metrics_initialized = True
        m._enabled = True

        # Should not raise
        m.inc_message("request")


# =============================================================================
# set_connections / adjust_connections Tests
# =============================================================================


class TestConnectionMetrics:
    """Tests for the connection gauge helpers."""

    def test_set_connections_calls_set(self, gauge_mock):
        """set_connections delegates to labels(server).set(count)."""
        m = WebSocketMetrics("svc")
        m._connection_gauge = gauge_mock
        m._metrics_initialized = True
        m._enabled = True

        m.set_connections(42)

        gauge_mock.labels.assert_called_with(server="svc")
        gauge_mock.labels.return_value.set.assert_called_with(42)

    def test_adjust_connections_calls_inc(self, gauge_mock):
        """adjust_connections uses .inc() with the signed delta."""
        m = WebSocketMetrics("svc")
        m._connection_gauge = gauge_mock
        m._metrics_initialized = True
        m._enabled = True

        m.adjust_connections(-1)

        gauge_mock.labels.assert_called_with(server="svc")
        gauge_mock.labels.return_value.inc.assert_called_with(-1)

    def test_adjust_connections_with_positive_delta(self, gauge_mock):
        """Positive delta increments the gauge."""
        m = WebSocketMetrics("svc")
        m._connection_gauge = gauge_mock
        m._metrics_initialized = True
        m._enabled = True

        m.adjust_connections(5)

        gauge_mock.labels.return_value.inc.assert_called_with(5)

    def test_set_connections_swallows_set_errors(self):
        """Errors during .set() are silently dropped."""
        m = WebSocketMetrics("svc")
        gauge = MagicMock()
        gauge.labels.return_value = gauge
        gauge.set.side_effect = RuntimeError("boom")
        m._connection_gauge = gauge
        m._metrics_initialized = True
        m._enabled = True

        # Should not raise
        m.set_connections(0)


# =============================================================================
# observe_broadcast / on_broadcast Tests
# =============================================================================


class TestBroadcastMetrics:
    """Tests for the broadcast histogram helpers."""

    def test_observe_broadcast_creates_histogram_once(self, histogram_mock):
        """First observe_broadcast creates a histogram, subsequent calls reuse it."""
        m = WebSocketMetrics("svc")
        m._enabled = True

        with patch.object(metrics_module, "Histogram", return_value=histogram_mock):
            m.observe_broadcast("ch-a", 0.1)
            m.observe_broadcast("ch-b", 0.2)

        # The histogram should be created only once
        assert m._broadcast_histogram is histogram_mock
        # Each call observes on the same histogram, labelled per-channel
        assert histogram_mock.labels.call_count == 2
        histogram_mock.labels.assert_any_call(server="svc", channel="ch-a")
        histogram_mock.labels.assert_any_call(server="svc", channel="ch-b")

    def test_observe_broadcast_calls_observe(self, histogram_mock):
        """observe_broadcast records the duration."""
        m = WebSocketMetrics("svc")
        m._enabled = True
        m._broadcast_histogram = histogram_mock  # pre-set to skip create

        m.observe_broadcast("ch", 0.123)

        histogram_mock.labels.return_value.observe.assert_called_with(0.123)

    def test_on_broadcast_is_alias_for_observe(self, histogram_mock):
        """on_broadcast is a backward-compatible alias for observe_broadcast."""
        m = WebSocketMetrics("svc")
        m._enabled = True
        m._broadcast_histogram = histogram_mock

        m.on_broadcast("ch", 0.5)

        histogram_mock.labels.return_value.observe.assert_called_with(0.5)

    def test_observe_broadcast_swallows_observe_errors(self):
        """A broken histogram does not propagate errors."""
        m = WebSocketMetrics("svc")
        hist = MagicMock()
        hist.labels.return_value = hist
        hist.observe.side_effect = RuntimeError("boom")
        m._broadcast_histogram = hist
        m._enabled = True

        # Should not raise
        m.observe_broadcast("ch", 0.1)


# =============================================================================
# set_subscriptions / inc_error Tests
# =============================================================================


class TestOtherMetrics:
    """Tests for subscription and error helpers."""

    def test_set_subscriptions_calls_set(self, gauge_mock):
        """set_subscriptions updates the subscription gauge."""
        m = WebSocketMetrics("svc")
        m._subscription_gauge = gauge_mock
        m._metrics_initialized = True
        m._enabled = True

        m.set_subscriptions(7)

        gauge_mock.labels.assert_called_with(server="svc")
        gauge_mock.labels.return_value.set.assert_called_with(7)

    def test_inc_error_creates_counter_and_increments(self):
        """inc_error creates a new error counter on first use."""
        m = WebSocketMetrics("svc")
        m._enabled = True
        # Pre-initialize so _initialize_metrics does not also call Counter
        # for the message counter.
        m._metrics_initialized = True
        m._message_counter = MagicMock()
        m._connection_gauge = MagicMock()
        m._subscription_gauge = MagicMock()

        fake_counter = MagicMock()
        fake_counter.labels.return_value = fake_counter

        with patch.object(metrics_module, "Counter", return_value=fake_counter) as counter_cls:
            m.inc_error("auth", amount=2)

        counter_cls.assert_called_once()
        fake_counter.labels.assert_called_with(server="svc", error_type="auth")
        fake_counter.labels.return_value.inc.assert_called_with(2)
        assert m._error_counter is fake_counter

    def test_inc_error_reuses_counter(self):
        """Subsequent inc_error calls reuse the same counter."""
        m = WebSocketMetrics("svc")
        m._enabled = True
        m._metrics_initialized = True
        m._message_counter = MagicMock()
        m._connection_gauge = MagicMock()
        m._subscription_gauge = MagicMock()

        fake_counter = MagicMock()
        fake_counter.labels.return_value = fake_counter
        m._error_counter = fake_counter

        with patch.object(metrics_module, "Counter") as counter_cls:
            m.inc_error("parse")
            m.inc_error("auth")

        # Counter constructor not called again - we reuse _error_counter
        counter_cls.assert_not_called()
        # labels() called twice with the right error types
        assert fake_counter.labels.call_count == 2


# =============================================================================
# get_metrics_summary() Tests
# =============================================================================


class TestGetMetricsSummary:
    """Tests for the get_metrics_summary introspection helper."""

    def test_summary_when_uninitialized(self):
        """A fresh instance reports enabled=True (PROM available) but not initialized."""
        m = WebSocketMetrics("svc")
        # The summary helper references plural attribute names that
        # are only populated after the metrics are wired up - pre-create
        # them as empty containers so the call doesn't raise.
        m._broadcast_histograms = {}  # type: ignore[attr-defined]
        m._error_counters = {}  # type: ignore[attr-defined]

        summary = m.get_metrics_summary()

        assert summary["server"] == "svc"
        assert summary["enabled"] == PROMETHEUS_AVAILABLE
        assert summary["initialized"] is False
        assert summary["connection_tracking"] is False
        assert summary["subscription_tracking"] is False
        assert summary["broadcast_tracking"] is False
        assert summary["error_types_tracked"] == []

    def test_summary_after_initialization(self):
        """After _initialize_metrics runs, connection/subscription tracking are true."""
        m = WebSocketMetrics("svc")
        m._message_counter = MagicMock()
        m._connection_gauge = MagicMock()
        m._subscription_gauge = MagicMock()
        m._metrics_initialized = True
        m._broadcast_histograms = {"ch-a": MagicMock()}  # type: ignore[attr-defined]
        m._error_counters = {"auth": MagicMock()}  # type: ignore[attr-defined]

        summary = m.get_metrics_summary()

        assert summary["initialized"] is True
        assert summary["connection_tracking"] is True
        assert summary["subscription_tracking"] is True
        assert summary["broadcast_tracking"] is True
        assert summary["error_types_tracked"] == ["auth"]

    def test_summary_disabled_when_prometheus_missing(self, monkeypatch):
        """If Prometheus is unavailable the summary reports enabled=False."""
        monkeypatch.setattr(metrics_module, "PROMETHEUS_AVAILABLE", False)
        m = WebSocketMetrics("svc")
        m._broadcast_histograms = {}  # type: ignore[attr-defined]
        m._error_counters = {}  # type: ignore[attr-defined]

        summary = m.get_metrics_summary()

        assert summary["enabled"] is False
        assert summary["initialized"] is False


# =============================================================================
# get_metrics() Factory
# =============================================================================


class TestGetMetricsFactory:
    """Tests for the get_metrics() factory function."""

    def test_get_metrics_creates_instance(self):
        """First call creates a new instance for a given server name."""
        m = get_metrics("svc-a")

        assert isinstance(m, WebSocketMetrics)
        assert m.server_name == "svc-a"

    def test_get_metrics_returns_same_instance(self):
        """Subsequent calls with the same name return the cached instance."""
        first = get_metrics("svc-b")
        second = get_metrics("svc-b")

        assert first is second

    def test_get_metrics_different_names_different_instances(self):
        """Different server names produce different instances."""
        a = get_metrics("svc-c")
        b = get_metrics("svc-d")

        assert a is not b
        assert a.server_name == "svc-c"
        assert b.server_name == "svc-d"


# =============================================================================
# start_metrics_server() Tests
# =============================================================================


class TestStartMetricsServer:
    """Tests for the start_metrics_server helper."""

    def test_start_metrics_server_returns_thread_when_prometheus_available(self):
        """If Prometheus is available, start_http_server is called and result returned."""
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not installed in this environment")

        with patch.object(metrics_module, "start_http_server", return_value="thread-1") as start:
            result = start_metrics_server(port=9999)

        start.assert_called_once_with(9999)
        assert result == "thread-1"

    def test_start_metrics_server_handles_oserror(self):
        """OSError from start_http_server is caught and returns None."""
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not installed in this environment")

        with patch.object(metrics_module, "start_http_server", side_effect=OSError("port in use")):
            result = start_metrics_server(port=9999)

        assert result is None

    def test_start_metrics_server_returns_none_when_prometheus_missing(self, monkeypatch):
        """Without prometheus_client, start_metrics_server returns None and warns."""
        monkeypatch.setattr(metrics_module, "PROMETHEUS_AVAILABLE", False)

        result = start_metrics_server(port=9999)

        assert result is None


# =============================================================================
# reset_metrics() Tests
# =============================================================================


class TestResetMetrics:
    """Tests for the reset_metrics utility."""

    def test_reset_metrics_clears_instances(self):
        """reset_metrics empties the _instances dict."""
        get_metrics("svc-1")
        get_metrics("svc-2")
        assert len(metrics_module._instances) == 2

        reset_metrics()

        assert metrics_module._instances == {}

    def test_reset_metrics_unregisters_collectors(self):
        """reset_metrics attempts to unregister Prometheus collectors."""
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not installed in this environment")

        fake_collector = MagicMock()
        registry = MagicMock()
        registry._collector_to_names = {fake_collector: ["x"]}

        with patch.object(metrics_module, "REGISTRY", registry):
            reset_metrics()

        registry.unregister.assert_called_once_with(fake_collector)

    def test_reset_metrics_noop_without_prometheus(self, monkeypatch):
        """Without prometheus_client, reset_metrics is still safe."""
        monkeypatch.setattr(metrics_module, "PROMETHEUS_AVAILABLE", False)
        # No exception should be raised
        reset_metrics()
        assert metrics_module._instances == {}


# =============================================================================
# _initialize_metrics() Tests
# =============================================================================


class TestInitializeMetrics:
    """Tests for the internal _initialize_metrics bootstrap."""

    def test_initialize_metrics_is_idempotent(self):
        """Calling _initialize_metrics twice does not recreate counters."""
        m = WebSocketMetrics("svc")
        m._enabled = True

        fake_msg_counter = MagicMock()
        fake_conn_gauge = MagicMock()
        fake_sub_gauge = MagicMock()
        with (
            patch.object(metrics_module, "Counter", return_value=fake_msg_counter),
            patch.object(metrics_module, "Gauge", side_effect=[fake_conn_gauge, fake_sub_gauge]),
        ):
            m._initialize_metrics()
            first_msg_counter = m._message_counter
            first_conn_gauge = m._connection_gauge
            m._initialize_metrics()  # second call should be a no-op

        assert m._message_counter is first_msg_counter
        assert m._connection_gauge is first_conn_gauge

    def test_initialize_metrics_marks_initialized(self):
        """After _initialize_metrics, _metrics_initialized is True."""
        m = WebSocketMetrics("svc")
        m._enabled = True

        with (
            patch.object(metrics_module, "Counter", return_value=MagicMock()),
            patch.object(metrics_module, "Gauge", return_value=MagicMock()),
        ):
            m._initialize_metrics()

        assert m._metrics_initialized is True

    def test_initialize_metrics_uses_unique_metric_names(self):
        """The three base metrics get distinct Prometheus names."""
        m = WebSocketMetrics("svc")
        m._enabled = True

        with (
            patch.object(metrics_module, "Counter") as counter_cls,
            patch.object(metrics_module, "Gauge") as gauge_cls,
        ):
            m._initialize_metrics()

        # Counter: messages
        counter_cls.assert_called_once()
        msg_name = counter_cls.call_args.args[0]
        assert msg_name == "websocket_messages_total"
        # Gauge: connections + subscriptions
        assert gauge_cls.call_count == 2
        gauge_names = {c.args[0] for c in gauge_cls.call_args_list}
        assert gauge_names == {"websocket_connections", "websocket_subscriptions"}
