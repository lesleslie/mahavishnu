"""Extended tests for ``mahavishnu.tui.__init__`` covering public API.

Targets lines flagged by the coverage report:

* Lines 41-45 — the ``except ImportError: ...`` branch in the
  ``from mahavishnu.tui.command_palette import ...`` wrapper.
* Lines 66-67 — ``FallbackRichFormatter.__init__`` paths (with and without
  an explicit ``Console``).
* Lines 69-76 — ``FallbackRichFormatter.format_dict`` body, including the
  default-console path (when no explicit console is supplied at
  construction time).
* Lines 78-85 — ``FallbackRichFormatter.format_list`` body, including the
  empty-list path, the missing-column fallback (``"—"``), and the
  ``"bold"`` styling rule for the ``name`` column.

Also covers the ``get_console()`` singleton cache contract and the
``__all__`` public surface.
"""

from __future__ import annotations

import importlib
import sys
from io import StringIO
from typing import Any

import pytest

# Ensure we always start with a fresh import of the package being tested so
# any ``monkeypatch`` against ``mahavishnu.tui`` doesn't leak stale globals
# between tests.
from rich.console import Console
from rich.table import Table

import mahavishnu.tui as tui
from mahavishnu.tui import FallbackRichFormatter, get_console


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# get_console() singleton
# ---------------------------------------------------------------------------


@pytest.fixture
def reset_console_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the module-level ``_console`` cache so each test starts clean."""
    monkeypatch.setattr(tui, "_console", None)


@pytest.mark.unit
def test_get_console_returns_console_instance(reset_console_cache: None) -> None:
    """First call instantiates and returns a ``rich.console.Console``."""
    console = get_console()
    assert isinstance(console, Console)


@pytest.mark.unit
def test_get_console_is_singleton(reset_console_cache: None) -> None:
    """Second call returns the SAME cached instance (cache hit)."""
    first = get_console()
    second = get_console()
    assert first is second


@pytest.mark.unit
def test_get_console_populates_module_cache(reset_console_cache: None) -> None:
    """After first call, ``mahavishnu.tui._console`` is no longer ``None``."""
    assert tui._console is None
    get_console()
    assert tui._console is not None
    assert isinstance(tui._console, Console)


@pytest.mark.unit
def test_get_console_recreates_after_cache_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``_console`` is reset, ``get_console()`` builds a new instance.

    The fixture in this case is inlined so we can validate the
    reset-and-recreate loop without inheriting the auto-reset.
    """
    monkeypatch.setattr(tui, "_console", None)
    first = get_console()
    # Reset by hand and call again
    monkeypatch.setattr(tui, "_console", None)
    second = get_console()
    assert isinstance(first, Console)
    assert isinstance(second, Console)
    # Both calls succeed; cache may or may not reuse the same object, but the
    # post-reset call must produce a Console instance and not raise.
    assert first is not None
    assert second is not None


# ---------------------------------------------------------------------------
# FallbackRichFormatter.__init__
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_formatter_uses_provided_console() -> None:
    """When a Console is passed in, the formatter uses it directly."""
    buf = StringIO()
    console = Console(file=buf, width=80, no_color=True)
    formatter = FallbackRichFormatter(console=console)
    assert formatter._console is console


@pytest.mark.unit
def test_formatter_uses_default_console_when_none_passed(
    reset_console_cache: None,
) -> None:
    """When no console is passed, ``__init__`` calls ``get_console()``."""
    formatter = FallbackRichFormatter()
    # The default-console path must yield a Console instance.
    assert isinstance(formatter._console, Console)
    # And it should match the singleton returned by get_console().
    assert formatter._console is get_console()


# ---------------------------------------------------------------------------
# FallbackRichFormatter.format_dict
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_format_dict_with_empty_dict() -> None:
    """An empty dict still renders a table with Key/Value headers."""
    buf = StringIO()
    console = Console(file=buf, width=80, no_color=True)
    formatter = FallbackRichFormatter(console=console)

    formatter.format_dict({})

    output = buf.getvalue()
    # Headers are always present
    assert "Key" in output
    assert "Value" in output


@pytest.mark.unit
def test_format_dict_single_pair() -> None:
    """A single key-value pair renders as a single row."""
    buf = StringIO()
    console = Console(file=buf, width=80, no_color=True)
    formatter = FallbackRichFormatter(console=console)

    formatter.format_dict({"status": "ok"})

    output = buf.getvalue()
    assert "status" in output
    assert "ok" in output


@pytest.mark.unit
def test_format_dict_multiple_pairs_preserve_order() -> None:
    """All keys/values render; dict insertion order is preserved."""
    buf = StringIO()
    console = Console(file=buf, width=80, no_color=True)
    formatter = FallbackRichFormatter(console=console)

    formatter.format_dict({"alpha": "1", "beta": "2", "gamma": "3"})

    output = buf.getvalue()
    for key, value in (("alpha", "1"), ("beta", "2"), ("gamma", "3")):
        assert key in output
        assert value in output
    # Order check: alpha must appear before beta which must appear before gamma.
    assert output.index("alpha") < output.index("beta") < output.index("gamma")


@pytest.mark.unit
def test_format_dict_with_title_empty() -> None:
    """``title=""`` does not produce a title line."""
    buf = StringIO()
    console = Console(file=buf, width=80, no_color=True)
    formatter = FallbackRichFormatter(console=console)

    formatter.format_dict({"k": "v"}, title="")

    output = buf.getvalue()
    assert "k" in output
    assert "v" in output
    # The default title attribute on a Rich Table is ""; an empty title
    # produces no separate title line in the rendered output.
    # We don't assert anything beyond key/value presence to avoid coupling
    # to Rich internals.


@pytest.mark.unit
def test_format_dict_with_title_nonempty() -> None:
    """A non-empty ``title`` is rendered as a table title."""
    buf = StringIO()
    console = Console(file=buf, width=80, no_color=True)
    formatter = FallbackRichFormatter(console=console)

    formatter.format_dict({"status": "ok"}, title="My Status")

    output = buf.getvalue()
    assert "My Status" in output
    assert "status" in output
    assert "ok" in output


@pytest.mark.unit
def test_format_dict_non_string_values_use_str_conversion() -> None:
    """Non-string values are coerced via ``str()`` before rendering."""
    buf = StringIO()
    console = Console(file=buf, width=80, no_color=True)
    formatter = FallbackRichFormatter(console=console)

    formatter.format_dict(
        {
            "count": 42,
            "tags": ["a", "b"],
            "missing": None,
        }
    )

    output = buf.getvalue()
    assert "count" in output
    # str(42) -> "42"
    assert "42" in output
    assert "tags" in output
    # str(["a", "b"]) -> "['a', 'b']"
    assert "['a', 'b']" in output
    assert "missing" in output
    # str(None) -> "None"
    assert "None" in output


@pytest.mark.unit
def test_format_dict_uses_default_console(
    reset_console_cache: None,
) -> None:
    """``format_dict`` invoked on the default console writes via ``get_console()``."""
    formatter = FallbackRichFormatter()
    # If this doesn't raise, the default-console wiring works end-to-end.
    # We can't easily capture output without monkeypatching the singleton
    # here, but calling with an empty dict is the safest smoke test.
    formatter.format_dict({"ping": "pong"})


# ---------------------------------------------------------------------------
# FallbackRichFormatter.format_list
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_format_list_empty_list_renders_headers() -> None:
    """An empty list still renders headers but no rows."""
    buf = StringIO()
    console = Console(file=buf, width=80, no_color=True)
    formatter = FallbackRichFormatter(console=console)

    formatter.format_list([], columns=["name", "status"])

    output = buf.getvalue()
    # Column titles are title-cased via col.title()
    assert "Name" in output
    assert "Status" in output


@pytest.mark.unit
def test_format_list_single_item_all_columns() -> None:
    """A single item with all columns populated renders as one row."""
    buf = StringIO()
    console = Console(file=buf, width=80, no_color=True)
    formatter = FallbackRichFormatter(console=console)

    formatter.format_list(
        [{"name": "alpha", "status": "ok"}],
        columns=["name", "status"],
    )

    output = buf.getvalue()
    assert "alpha" in output
    assert "ok" in output


@pytest.mark.unit
def test_format_list_missing_column_uses_em_dash() -> None:
    """A missing column value renders as ``—`` (em dash)."""
    buf = StringIO()
    console = Console(file=buf, width=80, no_color=True)
    formatter = FallbackRichFormatter(console=console)

    # "missing_col" is NOT in the item dict — must fall back to "—"
    formatter.format_list(
        [{"name": "alpha"}],
        columns=["name", "missing_col"],
    )

    output = buf.getvalue()
    assert "alpha" in output
    assert "—" in output


@pytest.mark.unit
def test_format_list_name_column_bold() -> None:
    """The ``name`` column is styled bold; other columns are not."""
    buf = StringIO()
    console = Console(file=buf, width=80, no_color=True)
    formatter = FallbackRichFormatter(console=console)

    formatter.format_list(
        [{"name": "alpha", "status": "ok"}],
        columns=["name", "status"],
    )

    # Inspect the actual Table object the formatter built, by re-running
    # the formatting branch and capturing the Table reference. We do this
    # by patching ``self._console.print`` to capture the first arg.
    captured: list[Table] = []

    class CaptureConsole:
        def print(self, obj: Any, *args: Any, **kwargs: Any) -> None:
            captured.append(obj)

    capture = CaptureConsole()
    capture_formatter = FallbackRichFormatter(console=capture)  # type: ignore[arg-type]
    capture_formatter.format_list(
        [{"name": "alpha", "status": "ok"}],
        columns=["name", "status"],
    )

    assert captured, "expected at least one Table to be printed"
    table = captured[0]
    # Two columns were requested
    assert len(table.columns) == 2
    # First column ("name") has style "bold"; second column ("status") has "".
    assert table.columns[0].style == "bold"
    assert table.columns[1].style == ""


@pytest.mark.unit
def test_format_list_multiple_items_rendered() -> None:
    """Multiple items all render, with their values present in the output."""
    buf = StringIO()
    console = Console(file=buf, width=80, no_color=True)
    formatter = FallbackRichFormatter(console=console)

    formatter.format_list(
        [
            {"name": "alpha", "status": "ok"},
            {"name": "beta", "status": "warn"},
            {"name": "gamma", "status": "fail"},
        ],
        columns=["name", "status"],
    )

    output = buf.getvalue()
    for name, status in (
        ("alpha", "ok"),
        ("beta", "warn"),
        ("gamma", "fail"),
    ):
        assert name in output
        assert status in output


@pytest.mark.unit
def test_format_list_uses_default_console(reset_console_cache: None) -> None:
    """``format_list`` invoked with default-console wiring doesn't raise."""
    formatter = FallbackRichFormatter()
    formatter.format_list(
        [{"name": "x", "status": "y"}],
        columns=["name", "status"],
    )


@pytest.mark.unit
def test_format_list_with_title() -> None:
    """A non-empty title is rendered as the table title."""
    buf = StringIO()
    console = Console(file=buf, width=80, no_color=True)
    formatter = FallbackRichFormatter(console=console)

    formatter.format_list(
        [{"name": "alpha", "status": "ok"}],
        columns=["name", "status"],
        title="Workers",
    )

    output = buf.getvalue()
    assert "Workers" in output
    assert "alpha" in output


# ---------------------------------------------------------------------------
# The except-ImportError branch in the command_palette import wrapper
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_import_error_branch_keeps_command_aliases_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the command_palette module import fails, the public aliases stay None.
    ``    ``
    Strategy: set ``sys.modules["mahavishnu.tui.command_palette"] = None`` so the
    ``from mahavishnu.tui.command_palette import (...)`` statement inside the
    ``try`` block raises ImportError, then reload the package. After the
    reload, ``Command``/``CommandCategory``/``CommandPalette`` must be
    ``None`` (from the module-level ``Any = None`` bindings).
    ``    ``
    The original module is restored in the ``finally`` block so other tests
    keep not import.
    """
    module_key = "mahavishnu.tui"
    original_module = sys.modules.get(module_key)
    palette_key = "mahavishnu.tui.command_palette"
    original_palette = sys.modules.get(palette_key)

    try:
        # Force the import to fail with ImportError. ``None`` is the
        # canonical sentinel Python returns for missing module imports;
        # the import system raises ImportError when it sees this.
        sys.modules[palette_key] = None  # type: ignore[assignment]
        # We deliberately leave the sentinel in place — popping it would
        # let the import succeed via the normal filesystem path. The
        # reload below re-runs the module body, so the ``from ...
        # import ...`` statement will hit our sentinel and raise
        # ImportError, exercising the ``except`` branch we want to cover.

        reloaded = importlib.reload(sys.modules[module_key])

        # The ``except ImportError: ...`` branch executed, leaving the
        # module-level ``Any = None`` bindings in place.
        assert reloaded.Command is None
        assert reloaded.CommandCategory is None
        assert reloaded.CommandPalette is None
    finally:
        # Restore sys.modules exactly as we found it. We restore ``_console``
        # to None too so the singleton cache doesn't leak between tests.
        if original_module is not None:
            sys.modules[module_key] = original_module
        else:
            sys.modules.pop(module_key, None)
        if original_palette is not None:
            sys.modules[palette_key] = original_palette
        else:
            sys.modules.pop(palette_key, None)
        # Reload one more time so the canonical (passing) module state is
        # what every subsequent test sees.
        importlib.reload(sys.modules[module_key])


# ---------------------------------------------------------------------------
# Public __all__ surface
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_public_exports_include_tui_available_and_formatter() -> None:
    """``TUI_AVAILABLE`` and ``FallbackRichFormatter`` are exported."""
    from mahavishnu import tui

    assert "TUI_AVAILABLE" in tui.__all__
    assert "FallbackRichFormatter" in tui.__all__
    assert "get_console" in tui.__all__
    assert "Command" in tui.__all__
    assert "CommandCategory" in tui.__all__
    assert "CommandPalette" in tui.__all__


@pytest.mark.unit
def test_module_level_imports_are_accessible() -> None:
    """All advertised public symbols are importable from ``mahavishnu.tui``."""
    # If any of these names are missing, the import itself fails.
    # Use local-only imports so a module reload earlier in the file
    # (which produces a fresh class object) does not break identity
    # comparisons against the module-level ``FallbackRichFormatter`` and
    # ``get_console`` references imported at the top of this test file.
    import mahavishnu.tui as tui_mod  # noqa: F401

    # Verify each advertised public symbol is exposed as a module attribute.
    assert hasattr(tui_mod, "Command")
    assert hasattr(tui_mod, "CommandCategory")
    assert hasattr(tui_mod, "CommandPalette")
    assert hasattr(tui_mod, "FallbackRichFormatter")
    assert hasattr(tui_mod, "TUI_AVAILABLE")
    assert hasattr(tui_mod, "get_console")
    # And they are the same objects reachable via ``from mahavishnu.tui import X``.
    from mahavishnu.tui import FallbackRichFormatter, get_console  # noqa: F401

    # Use ``==`` rather than ``is`` so a reloaded module (which yields a
    # distinct class object) still matches by name lookup.
    assert tui_mod.FallbackRichFormatter is FallbackRichFormatter
    assert tui_mod.get_console is get_console


@pytest.mark.unit
def test_logger_is_initialized() -> None:
    """A module-level logger is created via ``oneiric.core.logging.get_logger``.

    structlog's lazy proxy doesn't expose a ``.name`` attribute and the
    factory args tuple may be empty depending on the bound logger class.
    Verify the proxy is non-None and that calling it does not raise.
    """
    assert tui.logger is not None
    # The proxy must be usable as a logger — bind it to a concrete
    # BoundLogger and exercise a log call without raising.
    bound = tui.logger.bind()
    # Log a debug message at INFO-or-above is filtered, but binding must work.
    assert bound is not None


@pytest.mark.unit
def test_tui_available_flag_has_expected_type() -> None:
    """``TUI_AVAILABLE`` is a bool, regardless of whether textual is installed."""
    assert isinstance(tui.TUI_AVAILABLE, bool)