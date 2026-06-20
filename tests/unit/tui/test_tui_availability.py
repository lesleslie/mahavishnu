from __future__ import annotations

import pytest


@pytest.mark.unit
def test_tui_available_is_bool() -> None:
    import mahavishnu.tui as tui

    assert isinstance(tui.TUI_AVAILABLE, bool)


@pytest.mark.unit
def test_get_console_returns_rich_console() -> None:
    from rich.console import Console

    from mahavishnu.tui import get_console

    console = get_console()
    assert isinstance(console, Console)


@pytest.mark.unit
def test_tui_available_can_be_patched_as_boolean() -> None:
    """Confirm tests can override TUI_AVAILABLE by patching the bool attribute."""
    import mahavishnu.tui as tui

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
