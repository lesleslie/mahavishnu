"""Tests for ``mahavishnu.tui.widgets``.

Coverage strategy:
* FALLBACK branch (TUI_AVAILABLE=False): always available. Reloads the module
  with the flag patched to exercise lines 64-72.
* TEXTUAL branch (TUI_AVAILABLE=True): gated by pytest.skip when textual is
  not installed. Patches ``Static.__init__`` to capture the label string
  without spinning up a Textual app.
* ``_WidgetBase`` ImportError fallback (lines 12-15): reloads with
  ``sys.modules['textual.widgets']`` set to ``None`` so the import fails.
"""

from __future__ import annotations

from importlib import reload
from typing import Any

import pytest

from mahavishnu.tui import TUI_AVAILABLE
from mahavishnu.tui import widgets as widgets_module


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def capture_static_init(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch ``textual.widgets.Static.__init__`` to capture the label."""
    from textual.widgets import Static

    captured: dict[str, Any] = {}

    def fake_init(self: Any, content: Any, *args: Any, **kwargs: Any) -> None:
        captured["content"] = content

    monkeypatch.setattr(Static, "__init__", fake_init)
    return captured


def _restore_widgets_module(tui_module: Any) -> None:
    """Reload ``widgets_module`` after TUI_AVAILABLE has been reset to True."""
    tui_module.TUI_AVAILABLE = True
    # Clear any stale ``None`` entries left over from ImportError tests.
    import sys as _sys

    if _sys.modules.get("textual.widgets") is None:
        del _sys.modules["textual.widgets"]
    reload(widgets_module)


# ============================================================
# TEXTUAL branch — PoolStatusWidget (lines 31-39)
# ============================================================


@pytest.mark.unit
def test_pool_status_widget_healthy_renders_green_ok(
    capture_static_init: dict[str, Any],
) -> None:
    """PoolStatusWidget renders [green]OK when healthy=True."""
    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed")

    from mahavishnu.tui.widgets import PoolStatusWidget

    PoolStatusWidget(
        {"name": "prod", "type": "mahavishnu", "worker_count": 5, "healthy": True}
    )

    label = capture_static_init["content"]
    assert "[bold]prod[/bold]" in label
    assert "type=mahavishnu" in label
    assert "workers=5" in label
    assert "[green]OK[/]" in label


@pytest.mark.unit
def test_pool_status_widget_unhealthy_renders_red_down(
    capture_static_init: dict[str, Any],
) -> None:
    """PoolStatusWidget renders [red]DOWN when healthy=False."""
    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed")

    from mahavishnu.tui.widgets import PoolStatusWidget

    PoolStatusWidget(
        {"name": "broken", "type": "session_buddy", "worker_count": 0, "healthy": False}
    )

    label = capture_static_init["content"]
    assert "[bold]broken[/bold]" in label
    assert "type=session_buddy" in label
    assert "workers=0" in label
    assert "[red]DOWN[/]" in label


@pytest.mark.unit
def test_pool_status_widget_missing_keys_uses_defaults(
    capture_static_init: dict[str, Any],
) -> None:
    """PoolStatusWidget uses defaults (em-dash, ?, 0, DOWN) for missing keys."""
    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed")

    from mahavishnu.tui.widgets import PoolStatusWidget

    PoolStatusWidget({})

    label = capture_static_init["content"]
    assert "[bold]—[/bold]" in label
    assert "type=?" in label
    assert "workers=0" in label
    assert "[red]DOWN[/]" in label


@pytest.mark.unit
def test_pool_status_widget_healthy_missing_is_falsy(
    capture_static_init: dict[str, Any],
) -> None:
    """PoolStatusWidget treats missing 'healthy' key as falsy (DOWN)."""
    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed")

    from mahavishnu.tui.widgets import PoolStatusWidget

    PoolStatusWidget({"name": "x"})  # no 'healthy' key

    assert "[red]DOWN[/]" in capture_static_init["content"]


@pytest.mark.unit
def test_pool_status_widget_partial_keys(capture_static_init: dict[str, Any]) -> None:
    """PoolStatusWidget mixes provided and default fields gracefully."""
    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed")

    from mahavishnu.tui.widgets import PoolStatusWidget

    PoolStatusWidget({"name": "alpha", "worker_count": 7})

    label = capture_static_init["content"]
    assert "[bold]alpha[/bold]" in label
    assert "type=?" in label
    assert "workers=7" in label
    assert "[red]DOWN[/]" in label


# ============================================================
# TEXTUAL branch — WorkerStatusWidget (lines 50-62)
# ============================================================


@pytest.mark.unit
def test_worker_status_widget_running_renders_green(
    capture_static_init: dict[str, Any],
) -> None:
    """WorkerStatusWidget renders green for status='running'."""
    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed")

    from mahavishnu.tui.widgets import WorkerStatusWidget

    WorkerStatusWidget({"id": "w-001", "type": "cloud", "status": "running"})

    label = capture_static_init["content"]
    assert "[green]w-001[/]" in label
    assert "type=cloud" in label
    assert "[green]running[/]" in label


@pytest.mark.unit
def test_worker_status_widget_idle_renders_cyan(
    capture_static_init: dict[str, Any],
) -> None:
    """WorkerStatusWidget renders cyan for status='idle'."""
    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed")

    from mahavishnu.tui.widgets import WorkerStatusWidget

    WorkerStatusWidget({"id": "w-002", "type": "local", "status": "idle"})

    label = capture_static_init["content"]
    assert "[cyan]w-002[/]" in label
    assert "[cyan]idle[/]" in label


@pytest.mark.unit
def test_worker_status_widget_failed_renders_red(
    capture_static_init: dict[str, Any],
) -> None:
    """WorkerStatusWidget renders red for status='failed'."""
    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed")

    from mahavishnu.tui.widgets import WorkerStatusWidget

    WorkerStatusWidget({"id": "w-003", "type": "local", "status": "failed"})

    label = capture_static_init["content"]
    assert "[red]w-003[/]" in label
    assert "[red]failed[/]" in label


@pytest.mark.unit
def test_worker_status_widget_unknown_status_renders_white(
    capture_static_init: dict[str, Any],
) -> None:
    """WorkerStatusWidget falls back to white for unknown status values."""
    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed")

    from mahavishnu.tui.widgets import WorkerStatusWidget

    WorkerStatusWidget({"id": "w-004", "type": "local", "status": "weird"})

    label = capture_static_init["content"]
    assert "[white]w-004[/]" in label
    assert "[white]weird[/]" in label


@pytest.mark.unit
def test_worker_status_widget_missing_status_defaults_to_unknown(
    capture_static_init: dict[str, Any],
) -> None:
    """WorkerStatusWidget defaults missing 'status' to 'unknown' (white)."""
    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed")

    from mahavishnu.tui.widgets import WorkerStatusWidget

    WorkerStatusWidget({"id": "w-005", "type": "local"})  # status missing

    label = capture_static_init["content"]
    assert "[white]w-005[/]" in label
    assert "[white]unknown[/]" in label
    assert "type=local" in label


@pytest.mark.unit
def test_worker_status_widget_missing_id_uses_em_dash(
    capture_static_init: dict[str, Any],
) -> None:
    """WorkerStatusWidget defaults missing 'id' to em-dash."""
    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed")

    from mahavishnu.tui.widgets import WorkerStatusWidget

    WorkerStatusWidget({"status": "running"})  # id missing

    label = capture_static_init["content"]
    assert "[green]—[/]" in label
    assert "type=?" in label


@pytest.mark.unit
def test_worker_status_widget_all_fields_missing(
    capture_static_init: dict[str, Any],
) -> None:
    """WorkerStatusWidget uses defaults when all fields are missing."""
    if not TUI_AVAILABLE:
        pytest.skip("Textual not installed")

    from mahavishnu.tui.widgets import WorkerStatusWidget

    WorkerStatusWidget({})

    label = capture_static_init["content"]
    assert "[white]—[/]" in label
    assert "type=?" in label
    assert "[white]unknown[/]" in label


# ============================================================
# FALLBACK branch (else) — TUI_AVAILABLE=False (lines 64-72)
# ============================================================


@pytest.mark.unit
def test_fallback_pool_status_widget_stores_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fallback PoolStatusWidget stores the input dict on ``_data``."""
    import mahavishnu.tui as tui_module

    monkeypatch.setattr(tui_module, "TUI_AVAILABLE", False)
    try:
        reloaded = reload(widgets_module)
        data = {
            "name": "fallback-pool",
            "type": "x",
            "worker_count": 3,
            "healthy": True,
        }
        widget = reloaded.PoolStatusWidget(data)
        assert widget._data == data
    finally:
        _restore_widgets_module(tui_module)


@pytest.mark.unit
def test_fallback_pool_status_widget_with_empty_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fallback PoolStatusWidget handles empty input dict."""
    import mahavishnu.tui as tui_module

    monkeypatch.setattr(tui_module, "TUI_AVAILABLE", False)
    try:
        reloaded = reload(widgets_module)
        widget = reloaded.PoolStatusWidget({})
        assert widget._data == {}
    finally:
        _restore_widgets_module(tui_module)


@pytest.mark.unit
def test_fallback_worker_status_widget_stores_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fallback WorkerStatusWidget stores the input dict on ``_data``."""
    import mahavishnu.tui as tui_module

    monkeypatch.setattr(tui_module, "TUI_AVAILABLE", False)
    try:
        reloaded = reload(widgets_module)
        data = {"id": "w-001", "type": "x", "status": "running"}
        widget = reloaded.WorkerStatusWidget(data)
        assert widget._data == data
    finally:
        _restore_widgets_module(tui_module)


@pytest.mark.unit
def test_fallback_worker_status_widget_with_empty_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fallback WorkerStatusWidget handles empty input dict."""
    import mahavishnu.tui as tui_module

    monkeypatch.setattr(tui_module, "TUI_AVAILABLE", False)
    try:
        reloaded = reload(widgets_module)
        widget = reloaded.WorkerStatusWidget({})
        assert widget._data == {}
    finally:
        _restore_widgets_module(tui_module)


# ============================================================
# try/except ImportError for _WidgetBase (lines 12-15)
# ============================================================


@pytest.mark.unit
def test_widget_base_falls_back_to_object_when_textual_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When textual.widgets import fails, _WidgetBase falls back to object."""
    import sys

    import mahavishnu.tui as tui_module

    monkeypatch.setitem(sys.modules, "textual.widgets", None)
    monkeypatch.setattr(tui_module, "TUI_AVAILABLE", False)
    try:
        reloaded = reload(widgets_module)
        assert reloaded._WidgetBase is object
    finally:
        _restore_widgets_module(tui_module)


@pytest.mark.unit
def test_widget_base_object_fallback_classes_still_construct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Classes inheriting from the object-based _WidgetBase construct and store data."""
    import sys

    import mahavishnu.tui as tui_module

    monkeypatch.setitem(sys.modules, "textual.widgets", None)
    monkeypatch.setattr(tui_module, "TUI_AVAILABLE", False)
    try:
        reloaded = reload(widgets_module)

        pool = reloaded.PoolStatusWidget({"name": "obj-pool"})
        worker = reloaded.WorkerStatusWidget({"id": "obj-worker"})

        assert pool._data == {"name": "obj-pool"}
        assert worker._data == {"id": "obj-worker"}
    finally:
        _restore_widgets_module(tui_module)