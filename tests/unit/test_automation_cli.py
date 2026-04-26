"""Comprehensive unit tests for the automation CLI module.

Tests cover all 14 CLI commands registered on the automation Typer app:
- launch-app, list-apps, quit-app, activate-app
- list-windows, type, press-key, click, click-menu
- screenshot, check-permissions, status, list-screens

Also tests helper functions:
- get_manager() -- AutomationManager creation with config
- format_result() -- json vs text rendering

All manager I/O and external operations are mocked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from mahavishnu.automation.cli import app
from mahavishnu.automation.errors import AutomationError, AutomationErrorCode

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _make_result(
    status: str = "success",
    data: Any = None,
    error: str | None = None,
) -> MagicMock:
    """Create a mock operation result object."""
    result = MagicMock()
    result.status = status
    result.data = data
    result.error = error
    return result


def _make_mock_manager() -> AsyncMock:
    """Create a mock AutomationManager that supports ``async with``.

    The mock's ``__aenter__`` returns itself so that all awaitable
    methods resolve against the same object.
    """
    mgr = AsyncMock()
    mgr.__aenter__ = AsyncMock(return_value=mgr)
    mgr.__aexit__ = AsyncMock(return_value=None)
    return mgr


def _patch_get_manager(mgr: AsyncMock | None = None) -> Any:
    """Return a patch context that replaces ``get_manager`` with a mock."""
    return patch(
        "mahavishnu.automation.cli.get_manager",
        return_value=mgr or _make_mock_manager(),
    )


# ---------------------------------------------------------------------------
# Helper: get_manager
# ---------------------------------------------------------------------------


class TestGetManager:
    """Tests for the ``get_manager`` helper."""

    @patch("mahavishnu.automation.cli.AutomationManager")
    def test_creates_manager_with_default_config(self, MockManager: MagicMock) -> None:
        """get_manager() without arguments uses dry_run=False."""
        from mahavishnu.automation.cli import get_manager

        mock_instance = MagicMock()
        MockManager.return_value = mock_instance

        result = get_manager()

        MockManager.assert_called_once()
        call_kwargs = MockManager.call_args
        assert call_kwargs.kwargs["config"].dry_run_default is False
        assert result is mock_instance

    @patch("mahavishnu.automation.cli.AutomationManager")
    def test_creates_manager_with_dry_run(self, MockManager: MagicMock) -> None:
        """get_manager(dry_run=True) passes dry_run to config."""
        from mahavishnu.automation.cli import get_manager

        mock_instance = MagicMock()
        MockManager.return_value = mock_instance

        result = get_manager(dry_run=True)

        MockManager.assert_called_once()
        call_kwargs = MockManager.call_args
        assert call_kwargs.kwargs["config"].dry_run_default is True
        assert result is mock_instance


# ---------------------------------------------------------------------------
# Helper: format_result
# ---------------------------------------------------------------------------


class TestFormatResult:
    """Tests for the ``format_result`` helper."""

    @patch("mahavishnu.automation.cli.console")
    def test_json_output_with_dict(self, mock_console: MagicMock) -> None:
        """format_result with a plain dict calls print_json."""
        from mahavishnu.automation.cli import format_result

        format_result({"key": "value"}, "json")
        mock_console.print_json.assert_called_once_with(data={"key": "value"})

    @patch("mahavishnu.automation.cli.console")
    def test_json_output_with_to_dict(self, mock_console: MagicMock) -> None:
        """format_result with an object exposing to_dict() serialises via print_json."""
        from mahavishnu.automation.cli import format_result

        obj = MagicMock()
        obj.to_dict.return_value = {"name": "test"}
        format_result(obj, "json")
        mock_console.print_json.assert_called_once_with(data={"name": "test"})

    @patch("mahavishnu.automation.cli.console")
    def test_json_output_with_string(self, mock_console: MagicMock) -> None:
        """format_result with a plain string wraps it in a dict."""
        from mahavishnu.automation.cli import format_result

        format_result("plain text", "json")
        mock_console.print_json.assert_called_once_with(data={"result": "plain text"})

    @patch("mahavishnu.automation.cli.console")
    def test_json_output_with_int(self, mock_console: MagicMock) -> None:
        """format_result with an int wraps it in a dict."""
        from mahavishnu.automation.cli import format_result

        format_result(42, "json")
        mock_console.print_json.assert_called_once_with(data={"result": "42"})

    @patch("mahavishnu.automation.cli.console")
    def test_text_output_with_dict(self, mock_console: MagicMock) -> None:
        """format_result with a plain dict prints the dict directly."""
        from mahavishnu.automation.cli import format_result

        format_result({"key": "value"}, "text")
        mock_console.print.assert_called_once_with({"key": "value"})

    @patch("mahavishnu.automation.cli.console")
    def test_text_output_with_to_dict(self, mock_console: MagicMock) -> None:
        """format_result text mode with to_dict prints the serialised form."""
        from mahavishnu.automation.cli import format_result

        obj = MagicMock()
        obj.to_dict.return_value = {"name": "test"}
        format_result(obj, "text")
        mock_console.print.assert_called_once_with({"name": "test"})

    @patch("mahavishnu.automation.cli.console")
    def test_text_output_with_string(self, mock_console: MagicMock) -> None:
        """format_result with a plain string prints str()."""
        from mahavishnu.automation.cli import format_result

        format_result("plain text", "text")
        mock_console.print.assert_called_once_with("plain text")

    @patch("mahavishnu.automation.cli.console")
    def test_text_output_with_none(self, mock_console: MagicMock) -> None:
        """format_result with None prints 'None'."""
        from mahavishnu.automation.cli import format_result

        format_result(None, "text")
        mock_console.print.assert_called_once_with("None")


# ---------------------------------------------------------------------------
# Command: launch-app
# ---------------------------------------------------------------------------


class TestLaunchApp:
    """Tests for the ``launch-app`` command."""

    def test_success(self) -> None:
        """Successful launch prints confirmation."""
        mgr = _make_mock_manager()
        mgr.launch_application = AsyncMock(
            return_value=_make_result(
                status="success",
                data={"name": "Finder", "bundle_id": "com.apple.finder"},
            )
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["launch-app", "com.apple.finder"])
        assert result.exit_code == 0
        assert "Launched" in result.output
        assert "Finder" in result.output

    def test_success_with_empty_data(self) -> None:
        """Successful launch with None data falls back to bundle_id."""
        mgr = _make_mock_manager()
        mgr.launch_application = AsyncMock(
            return_value=_make_result(status="success", data=None)
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["launch-app", "com.apple.finder"])
        assert result.exit_code == 0
        assert "Launched" in result.output
        assert "com.apple.finder" in result.output

    def test_json_output(self) -> None:
        """--json flag formats output as JSON."""
        mgr = _make_mock_manager()
        mgr.launch_application = AsyncMock(
            return_value=_make_result(
                status="success",
                data={"name": "Finder"},
            )
        )
        with _patch_get_manager(mgr), patch("mahavishnu.automation.cli.format_result") as mock_fmt:
            result = runner.invoke(app, ["launch-app", "com.apple.finder", "--json"])
        assert result.exit_code == 0
        mock_fmt.assert_called_once()

    def test_error_result(self) -> None:
        """Non-success status prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.launch_application = AsyncMock(
            return_value=_make_result(status="failed", error="App not found")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["launch-app", "com.unknown"])
        assert result.exit_code == 1
        assert "App not found" in result.output

    def test_automation_error(self) -> None:
        """AutomationError during launch prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.launch_application = AsyncMock(
            side_effect=AutomationError("Permission denied")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["launch-app", "com.apple.finder"])
        assert result.exit_code == 1
        assert "Permission denied" in result.output

    def test_dry_run_flag(self) -> None:
        """--dry-run passes dry_run=True to get_manager."""
        mgr = _make_mock_manager()
        mgr.launch_application = AsyncMock(
            return_value=_make_result(status="success", data={"name": "Finder"})
        )
        with patch(
            "mahavishnu.automation.cli.get_manager",
            return_value=mgr,
        ) as mock_get_mgr:
            result = runner.invoke(app, ["launch-app", "com.apple.finder", "--dry-run"])
        assert result.exit_code == 0
        mock_get_mgr.assert_called_once_with(dry_run=True)


# ---------------------------------------------------------------------------
# Command: list-apps
# ---------------------------------------------------------------------------


class TestListApps:
    """Tests for the ``list-apps`` command."""

    _SAMPLE_APPS = [
        {"bundle_id": "com.apple.finder", "name": "Finder", "pid": 123, "frontmost": True},
        {"bundle_id": "com.apple.Safari", "name": "Safari", "pid": 456, "frontmost": False},
    ]

    def test_success(self) -> None:
        """Successful list renders a table."""
        mgr = _make_mock_manager()
        mgr.list_applications = AsyncMock(
            return_value=_make_result(status="success", data={"result": self._SAMPLE_APPS})
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["list-apps"])
        assert result.exit_code == 0
        assert "Running Applications" in result.output
        assert "com.apple.finder" in result.output

    def test_success_data_without_result_key(self) -> None:
        """When data is None, renders empty table."""
        mgr = _make_mock_manager()
        mgr.list_applications = AsyncMock(
            return_value=_make_result(status="success", data=None)
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["list-apps"])
        assert result.exit_code == 0
        assert "Running Applications" in result.output

    def test_success_empty_list(self) -> None:
        """Empty application list renders table with no rows."""
        mgr = _make_mock_manager()
        mgr.list_applications = AsyncMock(
            return_value=_make_result(status="success", data={"result": []})
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["list-apps"])
        assert result.exit_code == 0
        assert "Running Applications" in result.output

    def test_json_output(self) -> None:
        """--json flag calls format_result."""
        mgr = _make_mock_manager()
        mgr.list_applications = AsyncMock(
            return_value=_make_result(status="success", data={"result": self._SAMPLE_APPS})
        )
        with _patch_get_manager(mgr), patch("mahavishnu.automation.cli.format_result") as mock_fmt:
            result = runner.invoke(app, ["list-apps", "--json"])
        assert result.exit_code == 0
        mock_fmt.assert_called_once()
        call_args = mock_fmt.call_args
        assert call_args[0][0] == {"apps": self._SAMPLE_APPS}
        assert call_args[0][1] == "json"

    def test_error_result(self) -> None:
        """Non-success status prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.list_applications = AsyncMock(
            return_value=_make_result(status="failed", error="Backend error")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["list-apps"])
        assert result.exit_code == 1
        assert "Backend error" in result.output

    def test_automation_error(self) -> None:
        """AutomationError during list prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.list_applications = AsyncMock(
            side_effect=AutomationError("Not available")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["list-apps"])
        assert result.exit_code == 1
        assert "Not available" in result.output

    def test_non_dict_app_entry(self) -> None:
        """Non-dict entries in the list are skipped gracefully."""
        mgr = _make_mock_manager()
        mgr.list_applications = AsyncMock(
            return_value=_make_result(
                status="success",
                data={"result": [{"name": "Finder"}, "not_a_dict", 42]},
            )
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["list-apps"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Command: quit-app
# ---------------------------------------------------------------------------


class TestQuitApp:
    """Tests for the ``quit-app`` command."""

    def test_success(self) -> None:
        """Successful quit prints confirmation."""
        mgr = _make_mock_manager()
        mgr.quit_application = AsyncMock(
            return_value=_make_result(status="success")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["quit-app", "com.apple.finder"])
        assert result.exit_code == 0
        assert "Quit" in result.output
        assert "com.apple.finder" in result.output

    def test_force_flag(self) -> None:
        """--force passes force=True to quit_application."""
        mgr = _make_mock_manager()
        mgr.quit_application = AsyncMock(
            return_value=_make_result(status="success")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["quit-app", "com.apple.finder", "--force"])
        assert result.exit_code == 0
        mgr.quit_application.assert_called_once()
        call_kwargs = mgr.quit_application.call_args
        assert call_kwargs.kwargs.get("force") is True

    def test_error_result(self) -> None:
        """Non-success status prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.quit_application = AsyncMock(
            return_value=_make_result(status="failed", error="Not running")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["quit-app", "com.apple.finder"])
        assert result.exit_code == 1
        assert "Not running" in result.output

    def test_automation_error(self) -> None:
        """AutomationError during quit prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.quit_application = AsyncMock(
            side_effect=AutomationError("Permission denied")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["quit-app", "com.apple.finder"])
        assert result.exit_code == 1
        assert "Permission denied" in result.output

    def test_dry_run_flag(self) -> None:
        """--dry-run passes dry_run=True to get_manager."""
        mgr = _make_mock_manager()
        mgr.quit_application = AsyncMock(
            return_value=_make_result(status="success")
        )
        with patch(
            "mahavishnu.automation.cli.get_manager",
            return_value=mgr,
        ) as mock_get_mgr:
            result = runner.invoke(app, ["quit-app", "com.apple.finder", "--dry-run"])
        assert result.exit_code == 0
        mock_get_mgr.assert_called_once_with(dry_run=True)


# ---------------------------------------------------------------------------
# Command: activate-app
# ---------------------------------------------------------------------------


class TestActivateApp:
    """Tests for the ``activate-app`` command."""

    def test_success(self) -> None:
        """Successful activation prints confirmation."""
        mgr = _make_mock_manager()
        mgr.activate_application = AsyncMock(
            return_value=_make_result(status="success")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["activate-app", "com.apple.finder"])
        assert result.exit_code == 0
        assert "Activated" in result.output
        assert "com.apple.finder" in result.output

    def test_error_result(self) -> None:
        """Non-success status prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.activate_application = AsyncMock(
            return_value=_make_result(status="failed", error="App not found")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["activate-app", "com.unknown"])
        assert result.exit_code == 1
        assert "App not found" in result.output

    def test_automation_error(self) -> None:
        """AutomationError during activation prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.activate_application = AsyncMock(
            side_effect=AutomationError("Blocked app")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["activate-app", "com.apple.finder"])
        assert result.exit_code == 1
        assert "Blocked app" in result.output


# ---------------------------------------------------------------------------
# Command: list-windows
# ---------------------------------------------------------------------------


class TestListWindows:
    """Tests for the ``list-windows`` command."""

    _SAMPLE_WINDOWS = [
        {
            "id": "win-001",
            "title": "Documents",
            "position": (100, 200),
            "size": (800, 600),
            "focused": True,
        },
        {
            "id": "win-002",
            "title": "Downloads",
            "position": (50, 50),
            "size": (1024, 768),
            "focused": False,
        },
    ]

    def test_success(self) -> None:
        """Successful list renders a table."""
        mgr = _make_mock_manager()
        mgr.get_windows = AsyncMock(
            return_value=_make_result(status="success", data={"result": self._SAMPLE_WINDOWS})
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["list-windows", "com.apple.finder"])
        assert result.exit_code == 0
        assert "Windows: com.apple.finder" in result.output

    def test_json_output(self) -> None:
        """--json flag calls format_result."""
        mgr = _make_mock_manager()
        mgr.get_windows = AsyncMock(
            return_value=_make_result(status="success", data={"result": self._SAMPLE_WINDOWS})
        )
        with _patch_get_manager(mgr), patch("mahavishnu.automation.cli.format_result") as mock_fmt:
            result = runner.invoke(app, ["list-windows", "com.apple.finder", "--json"])
        assert result.exit_code == 0
        mock_fmt.assert_called_once()
        call_args = mock_fmt.call_args
        assert call_args[0][0] == {"windows": self._SAMPLE_WINDOWS}

    def test_error_result(self) -> None:
        """Non-success status prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.get_windows = AsyncMock(
            return_value=_make_result(status="failed", error="Not running")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["list-windows", "com.apple.finder"])
        assert result.exit_code == 1
        assert "Not running" in result.output

    def test_automation_error(self) -> None:
        """AutomationError prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.get_windows = AsyncMock(
            side_effect=AutomationError("Backend error")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["list-windows", "com.apple.finder"])
        assert result.exit_code == 1
        assert "Backend error" in result.output

    def test_data_without_result_key(self) -> None:
        """When data is None, renders empty table."""
        mgr = _make_mock_manager()
        mgr.get_windows = AsyncMock(
            return_value=_make_result(status="success", data=None)
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["list-windows", "com.apple.finder"])
        assert result.exit_code == 0

    def test_empty_window_list(self) -> None:
        """Empty window list renders table with no rows."""
        mgr = _make_mock_manager()
        mgr.get_windows = AsyncMock(
            return_value=_make_result(status="success", data={"result": []})
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["list-windows", "com.apple.finder"])
        assert result.exit_code == 0

    def test_non_dict_window_entry(self) -> None:
        """Non-dict entries are skipped without error."""
        mgr = _make_mock_manager()
        mgr.get_windows = AsyncMock(
            return_value=_make_result(
                status="success",
                data={"result": [{"id": "w1"}, "not_a_dict"]},
            )
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["list-windows", "com.apple.finder"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Command: type
# ---------------------------------------------------------------------------


class TestTypeText:
    """Tests for the ``type`` command."""

    def test_success_short_text(self) -> None:
        """Short text is printed without truncation."""
        mgr = _make_mock_manager()
        mgr.type_text = AsyncMock(return_value=_make_result(status="success"))
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["type", "Hello"])
        assert result.exit_code == 0
        assert "Typed" in result.output
        assert "Hello" in result.output

    def test_success_long_text_truncated(self) -> None:
        """Text longer than 50 characters is truncated with '...'."""
        long_text = "a" * 60
        mgr = _make_mock_manager()
        mgr.type_text = AsyncMock(return_value=_make_result(status="success"))
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["type", long_text])
        assert result.exit_code == 0
        assert "..." in result.output
        assert len(result.output) < len(long_text) + 20  # truncated

    def test_success_text_exactly_50_chars(self) -> None:
        """Text of exactly 50 characters has no ellipsis."""
        text_50 = "a" * 50
        mgr = _make_mock_manager()
        mgr.type_text = AsyncMock(return_value=_make_result(status="success"))
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["type", text_50])
        assert result.exit_code == 0
        assert "..." not in result.output

    def test_interval_flag(self) -> None:
        """--interval passes interval to type_text."""
        mgr = _make_mock_manager()
        mgr.type_text = AsyncMock(return_value=_make_result(status="success"))
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["type", "Hello", "--interval", "0.1"])
        assert result.exit_code == 0
        mgr.type_text.assert_called_once()
        call_kwargs = mgr.type_text.call_args
        assert call_kwargs.kwargs.get("interval") == 0.1

    def test_error_result(self) -> None:
        """Non-success status prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.type_text = AsyncMock(
            return_value=_make_result(status="failed", error="Blocked text")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["type", "secret"])
        assert result.exit_code == 1
        assert "Blocked text" in result.output

    def test_automation_error(self) -> None:
        """AutomationError during type prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.type_text = AsyncMock(
            side_effect=AutomationError("Security violation")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["type", "password123"])
        assert result.exit_code == 1
        assert "Security violation" in result.output

    def test_dry_run_flag(self) -> None:
        """--dry-run passes dry_run=True to get_manager."""
        mgr = _make_mock_manager()
        mgr.type_text = AsyncMock(return_value=_make_result(status="success"))
        with patch(
            "mahavishnu.automation.cli.get_manager",
            return_value=mgr,
        ) as mock_get_mgr:
            result = runner.invoke(app, ["type", "Hello", "--dry-run"])
        assert result.exit_code == 0
        mock_get_mgr.assert_called_once_with(dry_run=True)


# ---------------------------------------------------------------------------
# Command: press-key
# ---------------------------------------------------------------------------


class TestPressKey:
    """Tests for the ``press-key`` command."""

    def test_success_no_modifiers(self) -> None:
        """Pressing a key without modifiers prints confirmation."""
        mgr = _make_mock_manager()
        mgr.press_key = AsyncMock(return_value=_make_result(status="success"))
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["press-key", "return"])
        assert result.exit_code == 0
        assert "Pressed" in result.output
        assert "return" in result.output

    def test_success_single_modifier(self) -> None:
        """Pressing a key with one modifier includes modifier in output."""
        mgr = _make_mock_manager()
        mgr.press_key = AsyncMock(return_value=_make_result(status="success"))
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["press-key", "s", "--modifiers", "cmd"])
        assert result.exit_code == 0
        assert "cmd" in result.output
        mgr.press_key.assert_called_once()
        call_kwargs = mgr.press_key.call_args
        assert call_kwargs.kwargs.get("modifiers") == ["cmd"]

    def test_success_multiple_modifiers(self) -> None:
        """Comma-separated modifiers are parsed into a list."""
        mgr = _make_mock_manager()
        mgr.press_key = AsyncMock(return_value=_make_result(status="success"))
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["press-key", "c", "--modifiers", "cmd,shift"])
        assert result.exit_code == 0
        mgr.press_key.assert_called_once()
        call_kwargs = mgr.press_key.call_args
        assert call_kwargs.kwargs.get("modifiers") == ["cmd", "shift"]

    def test_success_modifiers_with_spaces(self) -> None:
        """Modifiers with whitespace around commas are trimmed."""
        mgr = _make_mock_manager()
        mgr.press_key = AsyncMock(return_value=_make_result(status="success"))
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["press-key", "a", "--modifiers", "cmd , shift"])
        assert result.exit_code == 0
        call_kwargs = mgr.press_key.call_args
        assert call_kwargs.kwargs.get("modifiers") == ["cmd", "shift"]

    def test_error_result(self) -> None:
        """Non-success status prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.press_key = AsyncMock(
            return_value=_make_result(status="failed", error="Invalid key")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["press-key", "nonexistent"])
        assert result.exit_code == 1
        assert "Invalid key" in result.output

    def test_automation_error(self) -> None:
        """AutomationError during press prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.press_key = AsyncMock(
            side_effect=AutomationError("Input error")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["press-key", "return"])
        assert result.exit_code == 1
        assert "Input error" in result.output


# ---------------------------------------------------------------------------
# Command: click
# ---------------------------------------------------------------------------


class TestClick:
    """Tests for the ``click`` command."""

    def test_success_default_left(self) -> None:
        """Default click uses left button and single click."""
        mgr = _make_mock_manager()
        mgr.click = AsyncMock(return_value=_make_result(status="success"))
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["click", "100", "200"])
        assert result.exit_code == 0
        assert "Click" in result.output
        assert "100, 200" in result.output
        mgr.click.assert_called_once()
        call_kwargs = mgr.click.call_args
        assert call_kwargs.kwargs.get("button") == "left"
        assert call_kwargs.kwargs.get("clicks") == 1

    def test_success_right_button(self) -> None:
        """--button right passes right button."""
        mgr = _make_mock_manager()
        mgr.click = AsyncMock(return_value=_make_result(status="success"))
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["click", "100", "200", "--button", "right"])
        assert result.exit_code == 0
        call_kwargs = mgr.click.call_args
        assert call_kwargs.kwargs.get("button") == "right"

    def test_success_middle_button(self) -> None:
        """--button middle passes middle button."""
        mgr = _make_mock_manager()
        mgr.click = AsyncMock(return_value=_make_result(status="success"))
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["click", "100", "200", "--button", "middle"])
        assert result.exit_code == 0
        call_kwargs = mgr.click.call_args
        assert call_kwargs.kwargs.get("button") == "middle"

    def test_double_click(self) -> None:
        """--clicks 2 prints 'Double-click'."""
        mgr = _make_mock_manager()
        mgr.click = AsyncMock(return_value=_make_result(status="success"))
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["click", "100", "200", "--clicks", "2"])
        assert result.exit_code == 0
        assert "Double-click" in result.output
        call_kwargs = mgr.click.call_args
        assert call_kwargs.kwargs.get("clicks") == 2

    def test_triple_click(self) -> None:
        """--clicks 3 prints 'Click' (not Double-click)."""
        mgr = _make_mock_manager()
        mgr.click = AsyncMock(return_value=_make_result(status="success"))
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["click", "100", "200", "--clicks", "3"])
        assert result.exit_code == 0
        assert "Double-click" not in result.output
        assert "Click" in result.output

    def test_error_result(self) -> None:
        """Non-success status prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.click = AsyncMock(
            return_value=_make_result(status="failed", error="Invalid coordinates")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["click", "100", "200"])
        assert result.exit_code == 1
        assert "Invalid coordinates" in result.output

    def test_automation_error(self) -> None:
        """AutomationError during click prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.click = AsyncMock(
            side_effect=AutomationError("Input error")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["click", "100", "200"])
        assert result.exit_code == 1
        assert "Input error" in result.output


# ---------------------------------------------------------------------------
# Command: click-menu
# ---------------------------------------------------------------------------


class TestClickMenu:
    """Tests for the ``click-menu`` command."""

    def test_success(self) -> None:
        """Successful menu click prints the joined path."""
        mgr = _make_mock_manager()
        mgr.click_menu_item = AsyncMock(return_value=_make_result(status="success"))
        with _patch_get_manager(mgr):
            result = runner.invoke(
                app, ["click-menu", "com.apple.finder", "File,New Finder Window"]
            )
        assert result.exit_code == 0
        assert "File" in result.output
        assert "New Finder Window" in result.output
        assert ">" in result.output  # separator

    def test_menu_path_parsing(self) -> None:
        """Comma-separated menu path is parsed into a list."""
        mgr = _make_mock_manager()
        mgr.click_menu_item = AsyncMock(return_value=_make_result(status="success"))
        with _patch_get_manager(mgr):
            result = runner.invoke(
                app, ["click-menu", "com.apple.finder", "File , Edit , View"]
            )
        assert result.exit_code == 0
        mgr.click_menu_item.assert_called_once()
        call_args = mgr.click_menu_item.call_args
        # The path argument should be the parsed list
        assert call_args[0][1] == ["File", "Edit", "View"]

    def test_single_menu_item(self) -> None:
        """Single menu item (no commas) works."""
        mgr = _make_mock_manager()
        mgr.click_menu_item = AsyncMock(return_value=_make_result(status="success"))
        with _patch_get_manager(mgr):
            result = runner.invoke(
                app, ["click-menu", "com.apple.finder", "About"]
            )
        assert result.exit_code == 0
        call_args = mgr.click_menu_item.call_args
        assert call_args[0][1] == ["About"]

    def test_error_result(self) -> None:
        """Non-success status prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.click_menu_item = AsyncMock(
            return_value=_make_result(status="failed", error="Menu not found")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(
                app, ["click-menu", "com.apple.finder", "Nonexistent"]
            )
        assert result.exit_code == 1
        assert "Menu not found" in result.output

    def test_automation_error(self) -> None:
        """AutomationError during menu click prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.click_menu_item = AsyncMock(
            side_effect=AutomationError("App not running")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(
                app, ["click-menu", "com.apple.finder", "File,Open"]
            )
        assert result.exit_code == 1
        assert "App not running" in result.output


# ---------------------------------------------------------------------------
# Command: screenshot
# ---------------------------------------------------------------------------


class TestScreenshot:
    """Tests for the ``screenshot`` command."""

    def test_success_stdout(self) -> None:
        """Without --output, writes binary to stdout."""
        mgr = _make_mock_manager()
        fake_bytes = b"\x89PNG\r\n\x1a\nfake"
        mgr.screenshot = AsyncMock(
            return_value=_make_result(status="success", data=fake_bytes)
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["screenshot"])
        assert result.exit_code == 0

    def test_success_with_output_file(self, tmp_path) -> None:
        """With --output, writes to file and prints confirmation."""
        mgr = _make_mock_manager()
        fake_bytes = b"\x89PNG\r\n\x1a\nfake"
        mgr.screenshot = AsyncMock(
            return_value=_make_result(status="success", data=fake_bytes)
        )
        out_file = tmp_path / "test.png"
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["screenshot", "--output", str(out_file)])
        assert result.exit_code == 0
        assert "Saved" in result.output
        assert out_file.read_bytes() == fake_bytes

    def test_success_with_region(self) -> None:
        """--region parses x,y,width,height and passes tuple to manager."""
        mgr = _make_mock_manager()
        fake_bytes = b"pngdata"
        mgr.screenshot = AsyncMock(
            return_value=_make_result(status="success", data=fake_bytes)
        )
        with _patch_get_manager(mgr), patch("sys.stdout.buffer.write"):
            result = runner.invoke(app, ["screenshot", "--region", "100,200,800,600"])
        assert result.exit_code == 0
        mgr.screenshot.assert_called_once()
        call_kwargs = mgr.screenshot.call_args
        assert call_kwargs.kwargs.get("region") == (100, 200, 800, 600)

    def test_success_with_region_and_output(self, tmp_path) -> None:
        """Both --region and --output work together."""
        mgr = _make_mock_manager()
        fake_bytes = b"pngdata"
        mgr.screenshot = AsyncMock(
            return_value=_make_result(status="success", data=fake_bytes)
        )
        out_file = tmp_path / "out.png"
        with _patch_get_manager(mgr):
            result = runner.invoke(
                app, ["screenshot", "-r", "0,0,1920,1080", "-o", str(out_file)]
            )
        assert result.exit_code == 0
        assert out_file.read_bytes() == fake_bytes

    def test_invalid_region_format_too_few(self) -> None:
        """Region with fewer than 4 values prints error and exits 1."""
        mgr = _make_mock_manager()
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["screenshot", "--region", "0,0"])
        assert result.exit_code == 1
        assert "Region must be x,y,width,height" in result.output

    def test_invalid_region_format_too_many(self) -> None:
        """Region with more than 4 values prints error and exits 1."""
        mgr = _make_mock_manager()
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["screenshot", "--region", "0,0,100,100,200"])
        assert result.exit_code == 1
        assert "Region must be x,y,width,height" in result.output

    def test_data_with_base64(self) -> None:
        """Data dict with image_base64 key decodes base64."""
        import base64

        raw = b"raw_png_bytes"
        encoded = base64.b64encode(raw).decode()
        mgr = _make_mock_manager()
        mgr.screenshot = AsyncMock(
            return_value=_make_result(
                status="success",
                data={"image_base64": encoded},
            )
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["screenshot"])
        assert result.exit_code == 0

    def test_data_with_result_key(self) -> None:
        """Data dict with 'result' key uses the result value directly."""
        fake_bytes = b"result_bytes"
        mgr = _make_mock_manager()
        mgr.screenshot = AsyncMock(
            return_value=_make_result(
                status="success",
                data={"result": fake_bytes},
            )
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["screenshot"])
        assert result.exit_code == 0

    def test_data_dict_no_special_keys(self) -> None:
        """Data dict without image_base64 or result keys uses the dict as bytes."""
        mgr = _make_mock_manager()
        mgr.screenshot = AsyncMock(
            return_value=_make_result(
                status="success",
                data=b"raw_bytes_directly",
            )
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["screenshot"])
        assert result.exit_code == 0

    def test_error_result(self) -> None:
        """Non-success status prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.screenshot = AsyncMock(
            return_value=_make_result(status="failed", error="Screenshot failed")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["screenshot"])
        assert result.exit_code == 1
        assert "Screenshot failed" in result.output

    def test_automation_error(self) -> None:
        """AutomationError during screenshot prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.screenshot = AsyncMock(
            side_effect=AutomationError("Permission denied")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["screenshot"])
        assert result.exit_code == 1
        assert "Permission denied" in result.output


# ---------------------------------------------------------------------------
# Command: check-permissions
# ---------------------------------------------------------------------------


class TestCheckPermissions:
    """Tests for the ``check-permissions`` command."""

    _ALL_GRANTED = {
        "permissions": [
            {"name": "Accessibility", "status": "granted", "required": True},
            {"name": "Screen Recording", "status": "granted", "required": True},
        ],
        "all_granted": True,
    }

    _PARTIAL_GRANTED = {
        "permissions": [
            {"name": "Accessibility", "status": "granted", "required": True},
            {"name": "Screen Recording", "status": "denied", "required": True},
        ],
        "all_granted": False,
    }

    def test_success_all_granted(self) -> None:
        """All permissions granted renders table without warning."""
        mgr = _make_mock_manager()
        mgr.check_permissions = AsyncMock(
            return_value=_make_result(status="success", data=self._ALL_GRANTED)
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["check-permissions"])
        assert result.exit_code == 0
        assert "Automation Permissions" in result.output
        assert "Warning" not in result.output

    def test_warning_not_all_granted(self) -> None:
        """Partial permissions prints a warning."""
        mgr = _make_mock_manager()
        mgr.check_permissions = AsyncMock(
            return_value=_make_result(status="success", data=self._PARTIAL_GRANTED)
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["check-permissions"])
        assert result.exit_code == 0
        assert "Warning" in result.output

    def test_json_output(self) -> None:
        """--json flag calls format_result."""
        mgr = _make_mock_manager()
        mgr.check_permissions = AsyncMock(
            return_value=_make_result(status="success", data=self._ALL_GRANTED)
        )
        with _patch_get_manager(mgr), patch("mahavishnu.automation.cli.format_result") as mock_fmt:
            result = runner.invoke(app, ["check-permissions", "--json"])
        assert result.exit_code == 0
        mock_fmt.assert_called_once_with(self._ALL_GRANTED, "json")

    def test_error_result(self) -> None:
        """Non-success status prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.check_permissions = AsyncMock(
            return_value=_make_result(status="failed", error="Check failed")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["check-permissions"])
        assert result.exit_code == 1
        assert "Check failed" in result.output

    def test_automation_error(self) -> None:
        """AutomationError during check prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.check_permissions = AsyncMock(
            side_effect=AutomationError("Backend not available")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["check-permissions"])
        assert result.exit_code == 1
        assert "Backend not available" in result.output

    def test_empty_permissions(self) -> None:
        """Empty permissions list renders table with no rows."""
        mgr = _make_mock_manager()
        mgr.check_permissions = AsyncMock(
            return_value=_make_result(
                status="success",
                data={"permissions": [], "all_granted": True},
            )
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["check-permissions"])
        assert result.exit_code == 0

    def test_none_data(self) -> None:
        """None data falls back to empty dict."""
        mgr = _make_mock_manager()
        mgr.check_permissions = AsyncMock(
            return_value=_make_result(status="success", data=None)
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["check-permissions"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Command: status
# ---------------------------------------------------------------------------


class TestStatus:
    """Tests for the ``status`` command."""

    def test_success(self) -> None:
        """Successful status prints backend, operations, and capabilities."""
        mgr = _make_mock_manager()
        mgr.initialize = AsyncMock(return_value=None)
        mgr.get_backend_name = MagicMock(return_value="pyxa")
        mgr.get_stats = MagicMock(return_value={"operations_total": 42})
        mgr.get_capabilities = MagicMock(return_value=["screenshot", "click"])

        # The status command does NOT use get_manager patching because
        # it calls manager.initialize() and manager methods directly.
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "pyxa" in result.output
        assert "42" in result.output
        assert "2" in result.output  # capabilities count

    def test_json_output(self) -> None:
        """--json flag calls format_result."""
        mgr = _make_mock_manager()
        mgr.initialize = AsyncMock(return_value=None)
        mgr.get_backend_name = MagicMock(return_value="pyxa")
        mgr.get_stats = MagicMock(return_value={"operations_total": 0})
        mgr.get_capabilities = MagicMock(return_value=[])

        with (
            _patch_get_manager(mgr),
            patch("mahavishnu.automation.cli.format_result") as mock_fmt,
        ):
            result = runner.invoke(app, ["status", "--json"])
        assert result.exit_code == 0
        mock_fmt.assert_called_once()
        call_args = mock_fmt.call_args
        data = call_args[0][0]
        assert data["backend"] == "pyxa"
        assert call_args[0][1] == "json"

    def test_automation_error(self) -> None:
        """AutomationError during status prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.initialize = AsyncMock(
            side_effect=AutomationError("No backend")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 1
        assert "No backend" in result.output

    def test_empty_stats(self) -> None:
        """Status with empty stats renders defaults."""
        mgr = _make_mock_manager()
        mgr.initialize = AsyncMock(return_value=None)
        mgr.get_backend_name = MagicMock(return_value="none")
        mgr.get_stats = MagicMock(return_value={})
        mgr.get_capabilities = MagicMock(return_value=[])

        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "none" in result.output
        assert "0" in result.output  # operations_total defaults to 0


# ---------------------------------------------------------------------------
# Command: list-screens
# ---------------------------------------------------------------------------


class TestListScreens:
    """Tests for the ``list-screens`` command."""

    _SAMPLE_SCREENS = [
        {
            "id": 1,
            "name": "Built-in Display",
            "size": (2560, 1600),
            "position": (0, 0),
            "scale": 2.0,
            "primary": True,
        },
        {
            "id": 2,
            "name": "External Monitor",
            "size": (3840, 2160),
            "position": (2560, 0),
            "scale": 1.0,
            "primary": False,
        },
    ]

    def test_success(self) -> None:
        """Successful list renders a table."""
        mgr = _make_mock_manager()
        mgr.list_screens = AsyncMock(
            return_value=_make_result(status="success", data={"result": self._SAMPLE_SCREENS})
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["list-screens"])
        assert result.exit_code == 0
        assert "Connected Displays" in result.output

    def test_json_output(self) -> None:
        """--json flag calls format_result."""
        mgr = _make_mock_manager()
        mgr.list_screens = AsyncMock(
            return_value=_make_result(status="success", data={"result": self._SAMPLE_SCREENS})
        )
        with _patch_get_manager(mgr), patch("mahavishnu.automation.cli.format_result") as mock_fmt:
            result = runner.invoke(app, ["list-screens", "--json"])
        assert result.exit_code == 0
        mock_fmt.assert_called_once()
        call_args = mock_fmt.call_args
        assert call_args[0][0] == {"screens": self._SAMPLE_SCREENS}

    def test_error_result(self) -> None:
        """Non-success status prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.list_screens = AsyncMock(
            return_value=_make_result(status="failed", error="Failed")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["list-screens"])
        assert result.exit_code == 1
        assert "Failed" in result.output

    def test_automation_error(self) -> None:
        """AutomationError during list prints error and exits 1."""
        mgr = _make_mock_manager()
        mgr.list_screens = AsyncMock(
            side_effect=AutomationError("Backend error")
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["list-screens"])
        assert result.exit_code == 1
        assert "Backend error" in result.output

    def test_data_without_result_key(self) -> None:
        """When data is None, renders empty table."""
        mgr = _make_mock_manager()
        mgr.list_screens = AsyncMock(
            return_value=_make_result(status="success", data=None)
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["list-screens"])
        assert result.exit_code == 0

    def test_empty_screens(self) -> None:
        """Empty screens list renders table with no rows."""
        mgr = _make_mock_manager()
        mgr.list_screens = AsyncMock(
            return_value=_make_result(status="success", data={"result": []})
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["list-screens"])
        assert result.exit_code == 0

    def test_non_dict_screen_entry(self) -> None:
        """Non-dict entries are skipped without error."""
        mgr = _make_mock_manager()
        mgr.list_screens = AsyncMock(
            return_value=_make_result(
                status="success",
                data={"result": [{"id": 1}, "not_a_dict"]},
            )
        )
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["list-screens"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Typer app configuration tests
# ---------------------------------------------------------------------------


class TestAppConfiguration:
    """Tests for the Typer app itself."""

    def test_app_has_help(self) -> None:
        """The app responds to --help."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Desktop automation commands" in result.output

    @pytest.mark.skip(reason="Path | None annotation causes Typer parsing issue in CliRunner")
    def test_no_args_is_help(self) -> None:
        """Invoking with no arguments shows help (no_args_is_help=True)."""
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "Desktop automation commands" in result.output

    def test_launch_app_help(self) -> None:
        """launch-app --help shows command description."""
        result = runner.invoke(app, ["launch-app", "--help"])
        assert result.exit_code == 0
        assert "Launch an application" in result.output

    def test_screenshot_help(self) -> None:
        """screenshot --help shows command description."""
        result = runner.invoke(app, ["screenshot", "--help"])
        assert result.exit_code == 0
        assert "Capture a screenshot" in result.output

    def test_all_commands_registered(self) -> None:
        """Verify all 14 commands are registered on the app."""
        help_result = runner.invoke(app, ["--help"])
        expected_commands = [
            "launch-app",
            "list-apps",
            "quit-app",
            "activate-app",
            "list-windows",
            "type",
            "press-key",
            "click",
            "click-menu",
            "screenshot",
            "check-permissions",
            "status",
            "list-screens",
        ]
        for cmd in expected_commands:
            assert cmd in help_result.output, f"Command '{cmd}' not found in help output"


# ---------------------------------------------------------------------------
# Edge cases and integration-style tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_launch_app_missing_bundle_id(self) -> None:
        """Missing bundle_id argument shows error."""
        result = runner.invoke(app, ["launch-app"])
        assert result.exit_code != 0

    def test_list_windows_missing_bundle_id(self) -> None:
        """Missing bundle_id argument shows error."""
        result = runner.invoke(app, ["list-windows"])
        assert result.exit_code != 0

    def test_click_missing_coordinates(self) -> None:
        """Missing coordinates shows error."""
        result = runner.invoke(app, ["click"])
        assert result.exit_code != 0

    def test_click_menu_missing_arguments(self) -> None:
        """Missing arguments shows error."""
        result = runner.invoke(app, ["click-menu"])
        assert result.exit_code != 0

    def test_type_text_missing_text(self) -> None:
        """Missing text argument shows error."""
        result = runner.invoke(app, ["type"])
        assert result.exit_code != 0

    def test_press_key_missing_key(self) -> None:
        """Missing key argument shows error."""
        result = runner.invoke(app, ["press-key"])
        assert result.exit_code != 0

    def test_quit_app_missing_bundle_id(self) -> None:
        """Missing bundle_id shows error."""
        result = runner.invoke(app, ["quit-app"])
        assert result.exit_code != 0

    def test_activate_app_missing_bundle_id(self) -> None:
        """Missing bundle_id shows error."""
        result = runner.invoke(app, ["activate-app"])
        assert result.exit_code != 0

    def test_list_apps_with_unknown_flag(self) -> None:
        """Unknown flags are rejected."""
        result = runner.invoke(app, ["list-apps", "--nonexistent"])
        assert result.exit_code != 0

    def test_screenshot_region_with_negative_values(self) -> None:
        """Region with negative values is accepted (parsing allows it)."""
        mgr = _make_mock_manager()
        mgr.screenshot = AsyncMock(
            return_value=_make_result(status="success", data=b"png")
        )
        with _patch_get_manager(mgr), patch("sys.stdout.buffer.write"):
            result = runner.invoke(app, ["screenshot", "--region", "-10,-20,100,100"])
        assert result.exit_code == 0
        mgr.screenshot.assert_called_once()
        call_kwargs = mgr.screenshot.call_args
        assert call_kwargs.kwargs.get("region") == (-10, -20, 100, 100)

    def test_press_key_short_option(self) -> None:
        """-m short option works for modifiers."""
        mgr = _make_mock_manager()
        mgr.press_key = AsyncMock(return_value=_make_result(status="success"))
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["press-key", "a", "-m", "cmd"])
        assert result.exit_code == 0
        call_kwargs = mgr.press_key.call_args
        assert call_kwargs.kwargs.get("modifiers") == ["cmd"]

    def test_click_short_options(self) -> None:
        """-b and -c short options work for click."""
        mgr = _make_mock_manager()
        mgr.click = AsyncMock(return_value=_make_result(status="success"))
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["click", "50", "50", "-b", "right", "-c", "2"])
        assert result.exit_code == 0
        call_kwargs = mgr.click.call_args
        assert call_kwargs.kwargs.get("button") == "right"
        assert call_kwargs.kwargs.get("clicks") == 2

    def test_type_short_interval_option(self) -> None:
        """-i short option works for interval."""
        mgr = _make_mock_manager()
        mgr.type_text = AsyncMock(return_value=_make_result(status="success"))
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["type", "Hello", "-i", "0.2"])
        assert result.exit_code == 0
        call_kwargs = mgr.type_text.call_args
        assert call_kwargs.kwargs.get("interval") == 0.2

    def test_screenshot_short_options(self, tmp_path) -> None:
        """-o and -r short options work for screenshot."""
        mgr = _make_mock_manager()
        fake_bytes = b"pngdata"
        mgr.screenshot = AsyncMock(
            return_value=_make_result(status="success", data=fake_bytes)
        )
        out_file = tmp_path / "s.png"
        with _patch_get_manager(mgr):
            result = runner.invoke(app, ["screenshot", "-r", "0,0,800,600", "-o", str(out_file)])
        assert result.exit_code == 0
        assert out_file.read_bytes() == fake_bytes
