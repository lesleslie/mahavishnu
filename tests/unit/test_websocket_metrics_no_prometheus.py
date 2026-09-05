"""Fallback path tests for ``mahavishnu.websocket.metrics`` when ``prometheus_client`` is missing.

Locks the install-hint fallback path for when ``prometheus_client`` is missing;
complements ``test_websocket_metrics_coverage.py``.

When ``prometheus_client`` is not installed (e.g. a lean ``uv sync`` without the
optional observability extras), the module's top-level ``try/except ImportError``
guard yields ``PROMETHEUS_AVAILABLE = False`` plus dummy ``Counter`` / ``Gauge`` /
``Histogram`` classes. ``WebSocketMetrics._ensure_enabled()`` short-circuits to
``False`` so every public method is a no-op, and ``start_metrics_server`` returns
``None`` while logging an install hint.

These tests exercise that fallback path by:

- Loading a fresh metrics-module instance under a sentinel ``sys.modules`` key
  so it cannot collide with the module pinned by
  ``test_websocket_metrics_coverage.py`` (``mahavishnu.websocket.metrics``).
- Using ``monkeypatch.setitem(sys.modules, "prometheus_client", None)`` to make
  ``from prometheus_client import ...`` raise ``ImportError`` inside the reload.
- Relying on ``monkeypatch`` to restore ``sys.modules["prometheus_client"]``
  after each test, so other tests in the suite that depend on the real package
  continue to see it.
"""

from __future__ import annotations

import importlib.util
from contextlib import suppress
from pathlib import Path
import sys
from unittest.mock import patch

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_METRICS_PATH = _REPO_ROOT / "mahavishnu" / "websocket" / "metrics.py"
_SENTINEL_KEY = "mahavishnu_websocket_metrics_no_prometheus_under_test"


def _reload_without_prometheus(monkeypatch: pytest.MonkeyPatch):
    """Reload a fresh metrics module with ``prometheus_client`` patched out.

    The patch is honoured on test teardown — ``prometheus_client`` is restored to
    its prior entry so other tests that depend on it still see the real module.
    """
    monkeypatch.setitem(sys.modules, "prometheus_client", None)
    # Always start from a clean sentinel entry so previous test state cannot
    # leak into the new module instance.
    sys.modules.pop(_SENTINEL_KEY, None)
    spec = importlib.util.spec_from_file_location(_SENTINEL_KEY, _METRICS_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_SENTINEL_KEY] = mod
    spec.loader.exec_module(mod)
    return mod


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _cleanup_sentinel() -> None:
    """Drop the sentinel module entry between tests so each starts clean."""
    yield
    with suppress(KeyError):
        sys.modules.pop(_SENTINEL_KEY)


# ---------------------------------------------------------------------------
# Module-level fallback path
# ---------------------------------------------------------------------------


class TestModuleFallbackPath:
    """``PROMETHEUS_AVAILABLE`` flag and dummy-class fallbacks."""

    def test_prometheus_available_flag_is_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mod = _reload_without_prometheus(monkeypatch)
        assert mod.PROMETHEUS_AVAILABLE is False

    def test_dummy_counter_methods_are_noop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mod = _reload_without_prometheus(monkeypatch)
        c = mod.Counter("foo", "bar", ["server"])
        # labels().inc() chain is a no-op
        c.labels(server="x").inc()
        c.labels(server="y").inc(5)
        # count() always reports 0 — callers can rely on this for diagnostics
        assert c.count() == 0

    def test_dummy_gauge_methods_are_noop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mod = _reload_without_prometheus(monkeypatch)
        g = mod.Gauge("foo", "bar", ["server"])
        g.labels(server="x").set(42)
        g.set(7)
        g.set_to_current_value()

    def test_dummy_histogram_methods_are_noop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mod = _reload_without_prometheus(monkeypatch)
        h = mod.Histogram("foo", "bar", ["server", "channel"])
        h.labels(server="x", channel="y").observe(0.05)
        h.observe(1.23)

    def test_dummy_start_http_server_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mod = _reload_without_prometheus(monkeypatch)
        with patch.object(mod.logger, "warning") as warn:
            result = mod.start_http_server(9090)
        assert result is None
        warn.assert_called()


# ---------------------------------------------------------------------------
# ``WebSocketMetrics`` disabled mode
# ---------------------------------------------------------------------------


class TestWebSocketMetricsDisabledMode:
    """Every public method must be a safe no-op when prometheus is missing."""

    def _make(self, monkeypatch: pytest.MonkeyPatch, name: str = "no-prom-server"):
        mod = _reload_without_prometheus(monkeypatch)
        return mod.WebSocketMetrics(name)

    def test_constructor_sets_enabled_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        m = self._make(monkeypatch, "srv")
        assert m._enabled is False
        assert m.server_name == "srv"

    def test_constructor_logs_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mod = _reload_without_prometheus(monkeypatch)
        with patch.object(mod.logger, "warning") as warn:
            mod.WebSocketMetrics("srv")
        warn.assert_called()

    def test_ensure_enabled_returns_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        m = self._make(monkeypatch)
        assert m._ensure_enabled() is False
        assert m._metrics_initialized is False

    @pytest.mark.parametrize(
        ("method_name", "args"),
        [
            ("inc_message", ("request",)),
            ("inc_message", ("response", 5)),
            ("set_connections", (0,)),
            ("set_connections", (42,)),
            ("adjust_connections", (1,)),
            ("adjust_connections", (-3,)),
            ("observe_broadcast", ("pool:abc", 0.1)),
            ("set_subscriptions", (7,)),
            ("inc_error", ("connection",)),
            ("inc_error", ("parse", 4)),
            ("on_broadcast", ("chan1", 0.1)),
        ],
    )
    def test_public_method_is_noop(
        self,
        monkeypatch: pytest.MonkeyPatch,
        method_name: str,
        args: tuple,
    ) -> None:
        m = self._make(monkeypatch, "srv")
        getattr(m, method_name)(*args)
        # No state was mutated — fallback short-circuits before init
        assert m._metrics_initialized is False

    def test_get_metrics_summary_reports_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        m = self._make(monkeypatch, "summary-srv")
        summary = m.get_metrics_summary()
        assert summary == {
            "server": "summary-srv",
            "enabled": False,
            "initialized": False,
            "connection_tracking": False,
            "broadcast_tracking": False,
            "subscription_tracking": False,
            "error_types_tracked": [],
        }


# ---------------------------------------------------------------------------
# ``start_metrics_server`` fallback
# ---------------------------------------------------------------------------


class TestStartMetricsServerFallback:
    """``start_metrics_server`` must log an install hint and return ``None``."""

    def test_returns_none_and_logs_install_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mod = _reload_without_prometheus(monkeypatch)
        with patch.object(mod.logger, "warning") as warn:
            result = mod.start_metrics_server(9091)
        assert result is None
        messages = " ".join(
            str(c.args[0]) for c in warn.call_args_list
        ).lower()
        # The fallback path advertises how to install prometheus_client
        assert "prometheus" in messages or "install" in messages


# ---------------------------------------------------------------------------
# Module-level helpers under the fallback
# ---------------------------------------------------------------------------


class TestModuleLevelHelpersUnderFallback:
    """``get_metrics`` and ``reset_metrics`` must remain safe under the fallback."""

    def test_get_metrics_returns_disabled_instance(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mod = _reload_without_prometheus(monkeypatch)
        m = mod.get_metrics("lean-install-server")
        assert isinstance(m, mod.WebSocketMetrics)
        assert m._enabled is False
        # Same server name returns the cached instance
        m2 = mod.get_metrics("lean-install-server")
        assert m2 is m

    def test_reset_metrics_safe(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mod = _reload_without_prometheus(monkeypatch)
        mod._instances["a"] = mod.WebSocketMetrics("a")
        mod._instances["b"] = mod.WebSocketMetrics("b")
        with patch.object(mod.logger, "info") as info:
            mod.reset_metrics()
        assert mod._instances == {}
        info.assert_called()

    def test_reload_is_idempotent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Re-loading the module under the sentinel does not raise."""
        mod1 = _reload_without_prometheus(monkeypatch)
        mod2 = _reload_without_prometheus(monkeypatch)
        mod3 = _reload_without_prometheus(monkeypatch)
        for mod in (mod1, mod2, mod3):
            assert mod.PROMETHEUS_AVAILABLE is False
        # Each reload creates a distinct dummy Counter class — no shared state
        # across module instances.
        c1 = mod1.Counter("a", "b")
        c2 = mod2.Counter("a", "b")
        assert type(c1) is not type(c2)
        assert c1 is not c2


class TestCoverageOfFallbackBranches:
    """Parametrized cases that exercise fallback branches with multiple labels."""

    @pytest.mark.parametrize(
        "label_pairs",
        [
            ({"server": "alpha"},),
            ({"server": "alpha", "message_type": "request"},),
            ({"server": "alpha", "channel": "pool:local"},),
            ({"server": "alpha", "error_type": "connection"},),
        ],
    )
    def test_disabled_labeled_methods_noop(
        self,
        monkeypatch: pytest.MonkeyPatch,
        label_pairs: tuple,
    ) -> None:
        m = _reload_without_prometheus(monkeypatch).WebSocketMetrics("srv")
        kwargs = label_pairs[0]
        if "message_type" in kwargs:
            m.inc_message(kwargs["message_type"])
        if "channel" in kwargs:
            m.observe_broadcast(kwargs["channel"], 0.5)
        if "error_type" in kwargs:
            m.inc_error(kwargs["error_type"])

    def test_disabled_metrics_summary_idempotent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Calling ``get_metrics_summary`` repeatedly remains safe and stable."""
        m = _reload_without_prometheus(monkeypatch).WebSocketMetrics("srv")
        s1 = m.get_metrics_summary()
        s2 = m.get_metrics_summary()
        assert s1 == s2
        assert s1["enabled"] is False