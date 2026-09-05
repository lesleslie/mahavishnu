from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# _DefaultMonitorDataProvider.get_pools
# ---------------------------------------------------------------------------
#
# The provider does an *inline* ``from mahavishnu.core.app import
# MahavishnuApp`` inside the method body. Per the project's
# ``monkeypatch-inline-import-target`` rule, we patch
# ``mahavishnu.core.app.MahavishnuApp`` (the module that is actually
# imported) — NOT ``mahavishnu.tui.monitor_app.MahavishnuApp``.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_get_pools_returns_aggregate_when_healthy() -> None:
    """Success path with healthy adapter_health — worker_count surfaced, healthy=True."""
    from mahavishnu import tui
    from mahavishnu.tui import monitor_app

    mock_metrics = {"workers_running": 5, "adapter_health": "healthy"}
    mock_app_instance = MagicMock()
    mock_app_instance.get_metrics = AsyncMock(return_value=mock_metrics)
    mock_cls = MagicMock(return_value=mock_app_instance)

    # Patch at the source module — that's where the inline import resolves.
    monkey = pytest.MonkeyPatch()
    monkey.setattr("mahavishnu.core.app.MahavishnuApp", mock_cls)
    try:
        provider = monitor_app._DefaultMonitorDataProvider()
        result = await provider.get_pools()
    finally:
        monkey.undo()

    assert result == [
        {
            "name": "aggregate",
            "type": "summary",
            "worker_count": 5,
            "healthy": True,
        }
    ]
    mock_cls.assert_called_once_with()
    mock_app_instance.get_metrics.assert_awaited_once_with()
    # Silence unused-import warning while keeping the module reference for
    # static analysis (tui package is imported indirectly via monitor_app).
    _ = tui


@pytest.mark.unit
async def test_get_pools_marks_unhealthy_when_adapter_unhealthy() -> None:
    """adapter_health == 'unhealthy' must surface as healthy=False."""
    from mahavishnu.tui import monitor_app

    mock_metrics = {"workers_running": 2, "adapter_health": "unhealthy"}
    mock_app_instance = MagicMock()
    mock_app_instance.get_metrics = AsyncMock(return_value=mock_metrics)
    mock_cls = MagicMock(return_value=mock_app_instance)

    monkey = pytest.MonkeyPatch()
    monkey.setattr("mahavishnu.core.app.MahavishnuApp", mock_cls)
    try:
        provider = monitor_app._DefaultMonitorDataProvider()
        result = await provider.get_pools()
    finally:
        monkey.undo()

    assert result == [
        {
            "name": "aggregate",
            "type": "summary",
            "worker_count": 2,
            "healthy": False,
        }
    ]


@pytest.mark.unit
async def test_get_pools_handles_none_workers_running() -> None:
    """workers_running=None must coerce to worker_count=0 via the ``or 0`` fallback."""
    from mahavishnu.tui import monitor_app

    mock_metrics: dict[str, Any] = {"workers_running": None, "adapter_health": "healthy"}
    mock_app_instance = MagicMock()
    mock_app_instance.get_metrics = AsyncMock(return_value=mock_metrics)
    mock_cls = MagicMock(return_value=mock_app_instance)

    monkey = pytest.MonkeyPatch()
    monkey.setattr("mahavishnu.core.app.MahavishnuApp", mock_cls)
    try:
        provider = monitor_app._DefaultMonitorDataProvider()
        result = await provider.get_pools()
    finally:
        monkey.undo()

    assert result == [
        {
            "name": "aggregate",
            "type": "summary",
            "worker_count": 0,
            "healthy": True,
        }
    ]


@pytest.mark.unit
async def test_get_pools_returns_empty_list_on_exception() -> None:
    """Any exception inside the provider must surface as ``[]`` to keep TUI alive."""
    from mahavishnu.tui import monitor_app

    mock_cls = MagicMock(side_effect=RuntimeError("MahavishnuApp init boom"))

    monkey = pytest.MonkeyPatch()
    monkey.setattr("mahavishnu.core.app.MahavishnuApp", mock_cls)
    try:
        provider = monitor_app._DefaultMonitorDataProvider()
        result = await provider.get_pools()
    finally:
        monkey.undo()

    assert result == []


# ---------------------------------------------------------------------------
# _DefaultMonitorDataProvider.get_workers
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_get_workers_returns_running_when_workers_positive() -> None:
    """workers_running > 0 must surface status='running'."""
    from mahavishnu.tui import monitor_app

    mock_metrics = {"workers_running": 3, "adapter_health": "healthy"}
    mock_app_instance = MagicMock()
    mock_app_instance.get_metrics = AsyncMock(return_value=mock_metrics)
    mock_cls = MagicMock(return_value=mock_app_instance)

    monkey = pytest.MonkeyPatch()
    monkey.setattr("mahavishnu.core.app.MahavishnuApp", mock_cls)
    try:
        provider = monitor_app._DefaultMonitorDataProvider()
        result = await provider.get_workers()
    finally:
        monkey.undo()

    assert result == [
        {"id": "aggregate", "type": "summary", "status": "running"}
    ]


@pytest.mark.unit
async def test_get_workers_returns_idle_when_workers_zero() -> None:
    """workers_running == 0 must surface status='idle' (not running)."""
    from mahavishnu.tui import monitor_app

    mock_metrics = {"workers_running": 0, "adapter_health": "healthy"}
    mock_app_instance = MagicMock()
    mock_app_instance.get_metrics = AsyncMock(return_value=mock_metrics)
    mock_cls = MagicMock(return_value=mock_app_instance)

    monkey = pytest.MonkeyPatch()
    monkey.setattr("mahavishnu.core.app.MahavishnuApp", mock_cls)
    try:
        provider = monitor_app._DefaultMonitorDataProvider()
        result = await provider.get_workers()
    finally:
        monkey.undo()

    assert result == [
        {"id": "aggregate", "type": "summary", "status": "idle"}
    ]


@pytest.mark.unit
async def test_get_workers_returns_empty_list_on_exception() -> None:
    """Provider exception path for workers also returns ``[]``."""
    from mahavishnu.tui import monitor_app

    mock_app_instance = MagicMock()
    mock_app_instance.get_metrics = AsyncMock(side_effect=RuntimeError("metrics boom"))
    mock_cls = MagicMock(return_value=mock_app_instance)

    monkey = pytest.MonkeyPatch()
    monkey.setattr("mahavishnu.core.app.MahavishnuApp", mock_cls)
    try:
        provider = monitor_app._DefaultMonitorDataProvider()
        result = await provider.get_workers()
    finally:
        monkey.undo()

    assert result == []


# ---------------------------------------------------------------------------
# MonitorApp fallback branch (always available — no skip)
# ---------------------------------------------------------------------------
#
# Even when textual IS installed, the fallback ``MonitorApp`` is still
# reachable by patching the module-level ``TUI_AVAILABLE`` boolean to
# ``False`` before import. This is a documented escape hatch in the
# existing test suite (see test_tui_availability.py).
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fallback_monitor_app_constructor_with_no_args() -> None:
    """Fallback ``MonitorApp()`` constructs without a data_provider."""
    # Build a fresh module snapshot with TUI_AVAILABLE=False to force the
    # fallback branch. We can't just patch the imported ``MonitorApp``
    # because the module evaluated ``if TUI_AVAILABLE:`` at import time.
    import importlib
    import sys

    from mahavishnu import tui

    original_tui_available = tui.TUI_AVAILABLE
    # Force the fallback path.
    tui.TUI_AVAILABLE = False
    try:
        # Drop the cached monitor_app module so it re-evaluates against the
        # patched TUI_AVAILABLE flag.
        sys.modules.pop("mahavishnu.tui.monitor_app", None)
        fallback_module = importlib.import_module("mahavishnu.tui.monitor_app")
        MonitorApp = fallback_module.MonitorApp
        app = MonitorApp()
        # Fallback branch only sets _data_provider; no _pool_data / _worker_data.
        assert app._data_provider is None
        # Sanity-check the fallback branch type ignores (it carries the
        # ``type: ignore[no-redef]`` because the textual branch redefines
        # the symbol under the same name).
        assert not hasattr(app, "_pool_data")
    finally:
        tui.TUI_AVAILABLE = original_tui_available
        # Restore the textual-branch module so subsequent tests see it.
        sys.modules.pop("mahavishnu.tui.monitor_app", None)
        importlib.import_module("mahavishnu.tui.monitor_app")


@pytest.mark.unit
def test_fallback_monitor_app_stores_data_provider() -> None:
    """Fallback ``MonitorApp(data_provider=mock)`` stores the provider."""
    import importlib
    import sys

    from mahavishnu import tui

    original_tui_available = tui.TUI_AVAILABLE
    tui.TUI_AVAILABLE = False
    try:
        sys.modules.pop("mahavishnu.tui.monitor_app", None)
        fallback_module = importlib.import_module("mahavishnu.tui.monitor_app")
        MonitorApp = fallback_module.MonitorApp

        sentinel = object()
        app = MonitorApp(data_provider=sentinel)
        assert app._data_provider is sentinel
    finally:
        tui.TUI_AVAILABLE = original_tui_available
        sys.modules.pop("mahavishnu.tui.monitor_app", None)
        importlib.import_module("mahavishnu.tui.monitor_app")


@pytest.mark.unit
def test_fallback_monitor_app_run_prints_missing_textual_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``MonitorApp().run()`` must surface the 'Textual not installed' message."""
    import importlib
    import sys

    from mahavishnu import tui

    original_tui_available = tui.TUI_AVAILABLE
    tui.TUI_AVAILABLE = False
    try:
        sys.modules.pop("mahavishnu.tui.monitor_app", None)
        fallback_module = importlib.import_module("mahavishnu.tui.monitor_app")
        MonitorApp = fallback_module.MonitorApp

        # Redirect get_console() to a buffer-backed Console so we can assert.
        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        # ``get_console`` is module-level cached, so we patch it on the
        # fallback module — that's where the ``run`` method calls it from.
        monkey = pytest.MonkeyPatch()
        buf_console = Console(file=buf, width=120, no_color=True, force_terminal=False)
        monkey.setattr(fallback_module, "get_console", lambda: buf_console)
        try:
            MonitorApp().run()
        finally:
            monkey.undo()

        output = buf.getvalue()
        assert "Textual not installed" in output
        assert "uv add --group tui textual" in output
    finally:
        tui.TUI_AVAILABLE = original_tui_available
        sys.modules.pop("mahavishnu.tui.monitor_app", None)
        importlib.import_module("mahavishnu.tui.monitor_app")


# ---------------------------------------------------------------------------
# MonitorApp Textual branch (skip if textual not installed)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_textual_monitor_app_constructor_stores_empty_buffers() -> None:
    """Constructor initialises _pool_data=[] and _worker_data=[] (Textual branch)."""
    from mahavishnu.tui import TUI_AVAILABLE
    from mahavishnu.tui.monitor_app import MonitorApp

    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed; MonitorApp not importable")

    provider = object()
    app = MonitorApp(data_provider=provider)
    assert app._data_provider is provider
    assert app._pool_data == []
    assert app._worker_data == []


@pytest.mark.unit
def test_textual_monitor_app_constructor_default_provider_is_none() -> None:
    """Default constructor leaves _data_provider=None."""
    from mahavishnu.tui import TUI_AVAILABLE
    from mahavishnu.tui.monitor_app import MonitorApp

    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed; MonitorApp not importable")

    app = MonitorApp()
    assert app._data_provider is None
    assert app._pool_data == []
    assert app._worker_data == []


@pytest.mark.unit
def test_textual_monitor_app_compose_yields_header_containers_footer() -> None:
    """compose() yields Header + 2 ScrollableContainer + Footer."""
    from mahavishnu.tui import TUI_AVAILABLE
    from mahavishnu.tui.monitor_app import MonitorApp

    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed; MonitorApp not importable")

    app = MonitorApp()
    widgets = list(app.compose())
    # 4 yielded widgets: Header, pool-container, worker-container, Footer
    assert len(widgets) == 4


@pytest.mark.unit
def test_textual_monitor_app_on_mount_schedules_refresh() -> None:
    """on_mount() schedules an interval and a one-shot after-refresh call."""
    from mahavishnu.tui import TUI_AVAILABLE
    from mahavishnu.tui.monitor_app import MonitorApp

    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed; MonitorApp not importable")

    app = MonitorApp()
    set_interval = MagicMock()
    call_after_refresh = MagicMock()
    app.set_interval = set_interval  # type: ignore[method-assign]
    app.call_after_refresh = call_after_refresh  # type: ignore[method-assign]

    app.on_mount()

    set_interval.assert_called_once()
    interval_seconds, interval_callback = set_interval.call_args.args
    assert interval_seconds == 5
    # The callback is bound to action_refresh.
    assert interval_callback.__self__ is app
    assert interval_callback.__func__ is MonitorApp.action_refresh

    call_after_refresh.assert_called_once()
    after_callback = call_after_refresh.call_args.args[0]
    assert after_callback.__self__ is app
    assert after_callback.__func__ is MonitorApp.action_refresh


@pytest.mark.unit
async def test_textual_monitor_app_action_refresh_without_provider() -> None:
    """No provider -> internal buffers stay [], no exception raised."""
    from mahavishnu.tui import TUI_AVAILABLE
    from mahavishnu.tui.monitor_app import MonitorApp

    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed; MonitorApp not importable")

    app = MonitorApp()
    # Stub render methods so we don't need a running Textual app to mount.
    app._render_pools = MagicMock()  # type: ignore[method-assign]
    app._render_workers = MagicMock()  # type: ignore[method-assign]

    await app.action_refresh()

    assert app._pool_data == []
    assert app._worker_data == []
    app._render_pools.assert_called_once_with()
    app._render_workers.assert_called_once_with()


@pytest.mark.unit
async def test_textual_monitor_app_action_refresh_with_provider_populates_state() -> None:
    """Provider result populates _pool_data and _worker_data."""
    from mahavishnu.tui import TUI_AVAILABLE
    from mahavishnu.tui.monitor_app import MonitorApp

    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed; MonitorApp not importable")

    pools_payload = [
        {"name": "p1", "type": "t", "worker_count": 3, "healthy": True}
    ]
    workers_payload = [
        {"id": "w1", "type": "t", "status": "running"}
    ]

    provider = MagicMock()
    provider.get_pools = AsyncMock(return_value=pools_payload)
    provider.get_workers = AsyncMock(return_value=workers_payload)

    app = MonitorApp(data_provider=provider)
    app._render_pools = MagicMock()  # type: ignore[method-assign]
    app._render_workers = MagicMock()  # type: ignore[method-assign]

    await app.action_refresh()

    assert app._pool_data == pools_payload
    assert app._worker_data == workers_payload
    provider.get_pools.assert_awaited_once_with()
    provider.get_workers.assert_awaited_once_with()
    app._render_pools.assert_called_once_with()
    app._render_workers.assert_called_once_with()


@pytest.mark.unit
async def test_textual_monitor_app_action_refresh_handles_provider_exception(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Provider raising -> exception caught, buffers stay at their previous values.

    Note: ``oneiric.core.logging.get_logger`` returns a structlog
    ``BoundLoggerLazyProxy`` which does not propagate through stdlib
    ``caplog``. We assert the observable behavior instead: the buffers
    stay at their initial values, the renders still run, and the
    exception is swallowed (no re-raise from the event handler).
    """
    from mahavishnu.tui import TUI_AVAILABLE
    from mahavishnu.tui.monitor_app import MonitorApp

    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed; MonitorApp not importable")

    provider = MagicMock()
    provider.get_pools = AsyncMock(side_effect=RuntimeError("provider boom"))
    provider.get_workers = AsyncMock(side_effect=RuntimeError("provider boom"))

    app = MonitorApp(data_provider=provider)
    app._render_pools = MagicMock()  # type: ignore[method-assign]
    app._render_workers = MagicMock()  # type: ignore[method-assign]

    # Should not raise — the event handler swallows the provider failure.
    await app.action_refresh()

    # Buffers untouched (constructor init values).
    assert app._pool_data == []
    assert app._worker_data == []
    # Renders still fired even though fetch failed.
    app._render_pools.assert_called_once_with()
    app._render_workers.assert_called_once_with()


@pytest.mark.unit
def test_textual_monitor_app_render_pools_mounts_widgets_per_item() -> None:
    """_render_pools() queries pool-container, clears, mounts one widget per pool."""
    from mahavishnu.tui import TUI_AVAILABLE
    from mahavishnu.tui.monitor_app import MonitorApp

    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed; MonitorApp not importable")

    app = MonitorApp()
    container = MagicMock()
    container.remove_children = MagicMock()
    container.mount = MagicMock()

    query_one = MagicMock(return_value=container)
    app.query_one = query_one  # type: ignore[method-assign]

    pools_payload = [
        {"name": "a", "type": "x", "worker_count": 1, "healthy": True},
        {"name": "b", "type": "y", "worker_count": 2, "healthy": False},
    ]
    app._pool_data = pools_payload

    app._render_pools()

    # query_one called with the pool-container id and ScrollableContainer type.
    assert query_one.call_count == 1
    q_args, _ = query_one.call_args
    assert q_args[0] == "#pool-container"
    # Second positional/keyword must reference ScrollableContainer.
    from textual.containers import ScrollableContainer as _SC

    assert q_args[1] is _SC or query_one.call_args.kwargs.get("expect_type") is _SC
    container.remove_children.assert_called_once_with()
    assert container.mount.call_count == len(pools_payload)
    # Each mounted widget got a PoolStatusWidget constructed with the pool dict.
    from mahavishnu.tui.widgets import PoolStatusWidget

    mounted_widgets = [call.args[0] for call in container.mount.call_args_list]
    assert len(mounted_widgets) == len(pools_payload)
    for mounted in mounted_widgets:
        assert isinstance(mounted, PoolStatusWidget)


@pytest.mark.unit
def test_textual_monitor_app_render_workers_mounts_widgets_per_item() -> None:
    """_render_workers() queries worker-container, clears, mounts one widget per worker."""
    from mahavishnu.tui import TUI_AVAILABLE
    from mahavishnu.tui.monitor_app import MonitorApp

    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed; MonitorApp not importable")

    app = MonitorApp()
    container = MagicMock()
    container.remove_children = MagicMock()
    container.mount = MagicMock()

    query_one = MagicMock(return_value=container)
    app.query_one = query_one  # type: ignore[method-assign]

    workers_payload = [
        {"id": "w1", "type": "x", "status": "running"},
        {"id": "w2", "type": "y", "status": "idle"},
        {"id": "w3", "type": "z", "status": "failed"},
    ]
    app._worker_data = workers_payload

    app._render_workers()

    assert query_one.call_count == 1
    q_args, _ = query_one.call_args
    assert q_args[0] == "#worker-container"
    from textual.containers import ScrollableContainer as _SC

    assert q_args[1] is _SC or query_one.call_args.kwargs.get("expect_type") is _SC
    container.remove_children.assert_called_once_with()
    assert container.mount.call_count == len(workers_payload)
    from mahavishnu.tui.widgets import WorkerStatusWidget

    mounted_widgets = [call.args[0] for call in container.mount.call_args_list]
    assert len(mounted_widgets) == len(workers_payload)
    for mounted in mounted_widgets:
        assert isinstance(mounted, WorkerStatusWidget)


@pytest.mark.unit
def test_textual_monitor_app_render_pools_empty_data_no_mounts() -> None:
    """_render_pools() with empty data still clears but mounts nothing."""
    from mahavishnu.tui import TUI_AVAILABLE
    from mahavishnu.tui.monitor_app import MonitorApp

    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed; MonitorApp not importable")

    app = MonitorApp()
    container = MagicMock()
    app.query_one = MagicMock(return_value=container)  # type: ignore[method-assign]

    app._render_pools()

    container.remove_children.assert_called_once_with()
    container.mount.assert_not_called()


@pytest.mark.unit
def test_textual_monitor_app_render_workers_empty_data_no_mounts() -> None:
    """_render_workers() with empty data still clears but mounts nothing."""
    from mahavishnu.tui import TUI_AVAILABLE
    from mahavishnu.tui.monitor_app import MonitorApp

    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed; MonitorApp not importable")

    app = MonitorApp()
    container = MagicMock()
    app.query_one = MagicMock(return_value=container)  # type: ignore[method-assign]

    app._render_workers()

    container.remove_children.assert_called_once_with()
    container.mount.assert_not_called()
