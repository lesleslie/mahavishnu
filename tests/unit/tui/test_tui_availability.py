from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.unit
def test_tui_available_is_bool() -> None:
    from mahavishnu import tui

    assert isinstance(tui.TUI_AVAILABLE, bool)


@pytest.mark.unit
def test_get_console_returns_rich_console() -> None:
    from rich.console import Console

    from mahavishnu.tui import get_console

    console = get_console()
    assert isinstance(console, Console)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_default_monitor_data_provider_returns_lists() -> None:
    """_DefaultMonitorDataProvider returns list-typed results on any path.

    The provider bridges MahavishnuApp.get_metrics() to the
    get_pools()/get_workers() shape. In any environment where
    MahavishnuApp is not initialized (the test environment),
    the provider must return empty lists — not raise — so the
    TUI can render without crashing.
    """
    from mahavishnu.tui.monitor_app import _DefaultMonitorDataProvider

    provider = _DefaultMonitorDataProvider()
    pools = await provider.get_pools()
    workers = await provider.get_workers()
    assert isinstance(pools, list)
    assert isinstance(workers, list)


@pytest.mark.unit
def test_monitor_app_constructor_accepts_data_provider() -> None:
    """MonitorApp(data_provider=...) wires the provider without crashing.

    This is the smoke test for the `mahavishnu monitor watch`
    data-provider path: when the CLI passes
    ``_DefaultMonitorDataProvider()``, the TUI must construct.
    """
    from mahavishnu.tui import TUI_AVAILABLE
    from mahavishnu.tui.monitor_app import _DefaultMonitorDataProvider

    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed; MonitorApp not importable")

    from mahavishnu.tui.monitor_app import MonitorApp

    app = MonitorApp(data_provider=_DefaultMonitorDataProvider())
    assert app._data_provider is not None  # type: ignore[attr-defined]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_monitor_app_action_refresh_with_mock_provider() -> None:
    """action_refresh() populates internal state from the data provider.

    The TUI's 5s refresh loop calls action_refresh. With a mock
    provider, the test verifies the data is fetched and stored
    without raising — even if downstream widget mounting would
    fail in the headless test (which is acceptable; the
    ``try/except`` in ``action_refresh`` already covers that).
    """
    from mahavishnu.tui import TUI_AVAILABLE
    from mahavishnu.tui.monitor_app import MonitorApp

    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed; MonitorApp not importable")

    provider = AsyncMock()
    provider.get_pools = AsyncMock(
        return_value=[{"name": "p1", "type": "t", "worker_count": 3, "healthy": True}]
    )
    provider.get_workers = AsyncMock(
        return_value=[{"id": "w1", "type": "t", "status": "running"}]
    )

    app = MonitorApp(data_provider=provider)
    try:
        await app.action_refresh()
    except Exception:  # noqa: BLE001 - event handler; logs and continues
        # The Textual App lifecycle (query_one, mount) requires a
        # running app; the headless test can't satisfy that. The
        # contract we care about is that the data was fetched.
        pass

    assert provider.get_pools.await_count == 1
    assert provider.get_workers.await_count == 1
    assert app._pool_data == [  # type: ignore[attr-defined]
        {"name": "p1", "type": "t", "worker_count": 3, "healthy": True}
    ]
    assert app._worker_data == [  # type: ignore[attr-defined]
        {"id": "w1", "type": "t", "status": "running"}
    ]


@pytest.mark.unit
def test_tui_available_can_be_patched_as_boolean() -> None:
    """Confirm tests can override TUI_AVAILABLE by patching the bool attribute."""
    from mahavishnu import tui

    original = tui.TUI_AVAILABLE
    tui.TUI_AVAILABLE = False
    assert tui.TUI_AVAILABLE is False
    tui.TUI_AVAILABLE = original  # restore


@pytest.mark.unit
def test_fallback_formatter_formats_dict_as_table() -> None:
    from io import StringIO

    from rich.console import Console

    from mahavishnu.tui import FallbackRichFormatter

    buf = StringIO()
    console = Console(file=buf, width=80, no_color=True)
    formatter = FallbackRichFormatter(console=console)
    formatter.format_dict({"status": "ok", "workers": 3})
    output = buf.getvalue()
    assert "status" in output
    assert "ok" in output
