"""Unit tests for mahavishnu.automation.backends.native_macos.

Mocks subprocess.run for osascript/cliclick/screencapture calls so no
real shell commands execute. Covers:
- is_available
- _run_osascript / _run_cliclick success and failure
- _parse_bool
- Application operations (launch, get, list, quit, activate, get_active)
- Window operations (get_windows, activate, close; resize/move not supported)
- Menu operations (click_menu_item, list_menus)
- Clipboard operations
- Input operations (type_text, press_key, click, drag, scroll)
- Screenshot using screencapture
- list_screens
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.automation.backends.native_macos import (
    NativeMacOSBackend,
    _parse_bool,
    _run_cliclick,
    _run_osascript,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def backend() -> NativeMacOSBackend:
    return NativeMacOSBackend()


@pytest.fixture
def mock_subprocess_run():
    """Patch subprocess.run at the module level."""
    with patch("mahavishnu.automation.backends.native_macos.subprocess.run") as m:
        # Default: success with empty stdout
        m.return_value = MagicMock(returncode=0, stdout="", stderr="")
        yield m


def _ok(stdout: str = "") -> MagicMock:
    return MagicMock(returncode=0, stdout=stdout, stderr="")


def _fail(stderr: str = "boom") -> MagicMock:
    return MagicMock(returncode=1, stdout="", stderr=stderr)


# =============================================================================
# is_available
# =============================================================================


class TestIsAvailable:
    @pytest.mark.unit
    def test_not_macos(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        with patch(
            "mahavishnu.automation.backends.native_macos.shutil.which",
            return_value="/usr/local/bin/cliclick",
        ):
            assert NativeMacOSBackend.is_available() is False

    @pytest.mark.unit
    def test_macos_without_cliclick(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        with patch(
            "mahavishnu.automation.backends.native_macos.shutil.which",
            return_value=None,
        ):
            assert NativeMacOSBackend.is_available() is False

    @pytest.mark.unit
    def test_macos_with_cliclick(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        with patch(
            "mahavishnu.automation.backends.native_macos.shutil.which",
            return_value="/usr/local/bin/cliclick",
        ):
            assert NativeMacOSBackend.is_available() is True


# =============================================================================
# Module-level helpers
# =============================================================================


class TestRunOsascript:
    @pytest.mark.unit
    def test_success_returns_stdout(self, mock_subprocess_run):
        mock_subprocess_run.return_value = _ok("ok result")
        result = _run_osascript('tell app "Finder" to activate')
        assert result == "ok result"

    @pytest.mark.unit
    def test_failure_raises_runtime_error(self, mock_subprocess_run):
        mock_subprocess_run.return_value = _fail("permission denied")
        with pytest.raises(RuntimeError) as exc:
            _run_osascript("bad script")
        assert "permission denied" in str(exc.value)

    @pytest.mark.unit
    def test_strips_stdout(self, mock_subprocess_run):
        mock_subprocess_run.return_value = _ok("  result  \n")
        result = _run_osascript("echo")
        assert result == "result"


class TestRunCliclick:
    @pytest.mark.unit
    def test_success(self, mock_subprocess_run):
        mock_subprocess_run.return_value = _ok("OK")
        result = _run_cliclick("c:100,200")
        assert result == "OK"

    @pytest.mark.unit
    def test_failure(self, mock_subprocess_run):
        mock_subprocess_run.return_value = _fail("click failed")
        with pytest.raises(RuntimeError):
            _run_cliclick("c:0,0")


class TestParseBool:
    @pytest.mark.unit
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("true", True),
            ("false", False),
            ("True", True),
            ("TRUE", True),
            ("anything_else", False),
            ("", False),
        ],
    )
    def test_parse_bool(self, value: str, expected: bool):
        assert _parse_bool(value) is expected


# =============================================================================
# Identity
# =============================================================================


class TestIdentity:
    @pytest.mark.unit
    def test_backend_name(self, backend):
        assert backend.backend_name == "native_macos"

    @pytest.mark.unit
    def test_repr(self, backend):
        text = repr(backend)
        assert "NativeMacOSBackend" in text
        assert "native_macos" in text


# =============================================================================
# Application operations
# =============================================================================


class TestLaunchApplication:
    @pytest.mark.unit
    async def test_launch_success(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _ok("name:Finder|pid:1234")
        info = await backend.launch_application("com.apple.finder")
        assert info.bundle_id == "com.apple.finder"
        assert info.name == "Finder"
        assert info.pid == 1234
        assert info.frontmost is True

    @pytest.mark.unit
    async def test_launch_parses_script(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _ok("name:Safari|pid:9999")
        await backend.launch_application("com.apple.Safari")
        # Inspect the call args for the osascript invocation
        first_call_args = mock_subprocess_run.call_args_list[0]
        cmd = first_call_args.args[0]
        assert cmd[0] == "osascript"
        assert cmd[1] == "-e"

    @pytest.mark.unit
    async def test_launch_failure_raises(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _fail("not allowed")
        with pytest.raises(RuntimeError):
            await backend.launch_application("com.banned.app")


class TestGetApplication:
    @pytest.mark.unit
    async def test_get_success(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _ok("name:Finder|pid:1|frontmost:true")
        info = await backend.get_application("com.apple.finder")
        assert info is not None
        assert info.name == "Finder"
        assert info.pid == 1
        assert info.frontmost is True

    @pytest.mark.unit
    async def test_get_returns_none_on_error(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _fail("not running")
        info = await backend.get_application("com.apple.missing")
        assert info is None


class TestListApplications:
    @pytest.mark.unit
    async def test_list_empty(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _ok("{}")
        apps = await backend.list_applications()
        assert apps == []

    @pytest.mark.unit
    async def test_list_apps_parses(self, backend, mock_subprocess_run):
        out = (
            "name:Finder|pid:1|frontmost:true|bundle:com.apple.finder\n"
            "name:Safari|pid:2|frontmost:false|bundle:com.apple.Safari"
        )
        mock_subprocess_run.return_value = _ok(out)
        apps = await backend.list_applications()
        assert len(apps) == 2
        assert apps[0].name == "Finder"
        assert apps[1].bundle_id == "com.apple.Safari"
        assert apps[1].frontmost is False

    @pytest.mark.unit
    async def test_list_apps_handles_exception(self, backend, mock_subprocess_run):
        mock_subprocess_run.side_effect = RuntimeError("boom")
        apps = await backend.list_applications()
        assert apps == []


class TestQuitApplication:
    @pytest.mark.unit
    async def test_quit_normal(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _ok("")
        result = await backend.quit_application("com.apple.finder")
        assert result is True

    @pytest.mark.unit
    async def test_quit_force(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _ok("")
        result = await backend.quit_application("com.apple.finder", force=True)
        assert result is True
        # Force-quit uses `tell application id "X" to quit` form
        first_call = mock_subprocess_run.call_args_list[0]
        script = first_call.args[0][2]
        assert "quit" in script
        assert "tell application id" in script

    @pytest.mark.unit
    async def test_quit_failure_returns_false(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _fail("nope")
        result = await backend.quit_application("com.apple.finder")
        assert result is False


class TestActivateApplication:
    @pytest.mark.unit
    async def test_activate_success(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _ok("")
        assert await backend.activate_application("com.apple.finder") is True

    @pytest.mark.unit
    async def test_activate_failure(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _fail("nope")
        assert await backend.activate_application("com.apple.finder") is False


class TestGetActiveApplication:
    @pytest.mark.unit
    async def test_get_active(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _ok("name:Terminal|pid:42|bundle:com.apple.Terminal")
        info = await backend.get_active_application()
        assert info is not None
        assert info.name == "Terminal"
        assert info.pid == 42
        assert info.bundle_id == "com.apple.Terminal"
        assert info.frontmost is True

    @pytest.mark.unit
    async def test_get_active_returns_none_on_error(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _fail("none")
        assert await backend.get_active_application() is None


# =============================================================================
# Window operations
# =============================================================================


class TestGetWindows:
    @pytest.mark.unit
    async def test_get_windows_empty(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _ok("")
        assert await backend.get_windows("com.apple.finder") == []

    @pytest.mark.unit
    async def test_get_windows_parses(self, backend, mock_subprocess_run):
        out = (
            "idx:1|title:Window One|x:10|y:20|w:800|h:600|mini:false|front:true\n"
            "idx:2|title:Window Two|x:0|y:0|w:400|h:300|mini:false|front:false"
        )
        mock_subprocess_run.return_value = _ok(out)
        windows = await backend.get_windows("com.apple.finder")
        assert len(windows) == 2
        assert windows[0].title == "Window One"
        assert windows[0].position == (10, 20)
        assert windows[0].size == (800, 600)
        assert windows[1].title == "Window Two"

    @pytest.mark.unit
    async def test_get_windows_skips_unparseable_lines(self, backend, mock_subprocess_run):
        # A line that cannot be split on ':' raises ValueError on int() and
        # is skipped by the (ValueError, IndexError) handler.
        # The garbage line contains no digits, so int(parts.get("idx", "0"))
        # would actually succeed; force a real ValueError by using non-numeric
        # coordinates in a line that has all expected keys.
        bad_line = "idx:bad|title:OK|x:not_a_number|y:0|w:1|h:1|mini:false|front:false"
        good_line = "idx:1|title:Window|x:0|y:0|w:800|h:600|mini:false|front:false"
        mock_subprocess_run.return_value = _ok(f"{bad_line}\n{good_line}")
        windows = await backend.get_windows("com.apple.finder")
        assert isinstance(windows, list)
        # Only the well-formed line should survive
        titles = [w.title for w in windows]
        assert "Window" in titles
        assert "OK" not in titles

    @pytest.mark.unit
    async def test_get_windows_failure_returns_empty(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _fail("nope")
        assert await backend.get_windows("com.apple.finder") == []


class TestActivateWindow:
    @pytest.mark.unit
    async def test_activate_window_success(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _ok("")
        assert await backend.activate_window("1") is True

    @pytest.mark.unit
    async def test_activate_window_failure(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _fail("nope")
        assert await backend.activate_window("1") is False


class TestResizeMoveWindow:
    @pytest.mark.unit
    async def test_resize_returns_false(self, backend, mock_subprocess_run):
        # The implementation just logs a warning and returns False
        assert await backend.resize_window("1", 800, 600) is False

    @pytest.mark.unit
    async def test_move_returns_false(self, backend, mock_subprocess_run):
        assert await backend.move_window("1", 10, 20) is False


class TestCloseWindow:
    @pytest.mark.unit
    async def test_close_window_success(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _ok("")
        assert await backend.close_window("1") is True

    @pytest.mark.unit
    async def test_close_window_failure(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _fail("nope")
        assert await backend.close_window("1") is False


# =============================================================================
# Menu operations
# =============================================================================


class TestMenuOperations:
    @pytest.mark.unit
    async def test_click_menu_item_short_path_returns_false(self, backend, mock_subprocess_run):
        # A path with fewer than 2 entries is rejected
        assert await backend.click_menu_item("com.apple.finder", ["File"]) is False
        # No subprocess call should have been made
        mock_subprocess_run.assert_not_called()

    @pytest.mark.unit
    async def test_click_menu_item_success(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _ok("")
        assert await backend.click_menu_item("com.apple.finder", ["File", "Save"]) is True

    @pytest.mark.unit
    async def test_click_menu_item_failure(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _fail("not found")
        assert await backend.click_menu_item("com.apple.finder", ["File", "Save"]) is False

    @pytest.mark.unit
    async def test_list_menus_returns_empty(self, backend, mock_subprocess_run):
        # AppleScript can't reliably enumerate; always empty
        assert await backend.list_menus("com.apple.finder") == []


# =============================================================================
# Clipboard operations
# =============================================================================


class TestClipboard:
    @pytest.mark.unit
    async def test_get_clipboard_success(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _ok("clipboard contents")
        result = await backend.get_clipboard()
        assert result == "clipboard contents"

    @pytest.mark.unit
    async def test_get_clipboard_failure_returns_empty(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _fail("nope")
        assert await backend.get_clipboard() == ""

    @pytest.mark.unit
    async def test_set_clipboard_success(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _ok("")
        assert await backend.set_clipboard("hello") is True

    @pytest.mark.unit
    async def test_set_clipboard_failure(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _fail("nope")
        assert await backend.set_clipboard("hello") is False

    @pytest.mark.unit
    async def test_set_clipboard_escapes_quotes(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _ok("")
        await backend.set_clipboard('say "hi"')
        # Verify that the script has the escaped form
        first_call = mock_subprocess_run.call_args_list[0]
        script = first_call.args[0][2]
        assert '\\"' in script


# =============================================================================
# Input operations
# =============================================================================


class TestTypeText:
    @pytest.mark.unit
    async def test_type_text_uses_space_for_spaces(self, backend, mock_subprocess_run):
        await backend.type_text("a b", interval=0.0)
        # Three chars: 'a', ' ', 'b' -> three cliclick invocations
        # _run_cliclick builds ["cliclick"] + args.split() so each call's
        # full argv (after the program name) is a list of subcommand tokens.
        # For ' ' the source passes "t:' '" which .split()s into
        # ["t:'", "'"] — two tokens, the second being the apostrophe quote.
        commands = [
            " ".join(call.args[0][1:])  # join the cliclick sub-args
            for call in mock_subprocess_run.call_args_list
        ]
        assert "t:a" in commands
        assert any("' '" in c or c == "'" for c in commands)
        assert "t:b" in commands

    @pytest.mark.unit
    async def test_type_text_failure_returns_false(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _fail("nope")
        result = await backend.type_text("a")
        assert result is False


class TestPressKey:
    @pytest.mark.unit
    async def test_press_key_no_modifiers(self, backend, mock_subprocess_run):
        await backend.press_key("a")
        first_call = mock_subprocess_run.call_args_list[0]
        cmd = first_call.args[0]
        assert cmd[0] == "cliclick"
        # The third element of the command list joined gives "k:a"
        assert cmd[-1].endswith("k:a")

    @pytest.mark.unit
    async def test_press_key_with_modifiers(self, backend, mock_subprocess_run):
        await backend.press_key("c", modifiers=["cmd", "shift"])
        first_call = mock_subprocess_run.call_args_list[0]
        cmd = first_call.args[0]
        joined = " ".join(cmd[1:])
        assert joined == "k:cmd+shift+c"

    @pytest.mark.unit
    async def test_press_key_failure(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _fail("nope")
        result = await backend.press_key("a")
        assert result is False


class TestClick:
    @pytest.mark.unit
    async def test_single_click(self, backend, mock_subprocess_run):
        await backend.click(100, 200)
        cmd = mock_subprocess_run.call_args_list[0].args[0]
        assert cmd == ["cliclick", "100,200"]

    @pytest.mark.unit
    async def test_double_click(self, backend, mock_subprocess_run):
        await backend.click(10, 20, clicks=2)
        cmd = mock_subprocess_run.call_args_list[0].args[0]
        assert cmd == ["cliclick", "dc:10,20"]

    @pytest.mark.unit
    async def test_triple_click(self, backend, mock_subprocess_run):
        await backend.click(10, 20, clicks=3)
        cmd = mock_subprocess_run.call_args_list[0].args[0]
        assert cmd == ["cliclick", "tc:10,20"]

    @pytest.mark.unit
    async def test_click_more_than_three_does_nothing(self, backend, mock_subprocess_run):
        # Implementation only handles 1/2/3; otherwise nothing happens
        result = await backend.click(10, 20, clicks=4)
        assert result is True
        # No cliclick invocation for clicks=4
        assert mock_subprocess_run.call_count == 0

    @pytest.mark.unit
    async def test_click_failure(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _fail("nope")
        result = await backend.click(10, 20)
        assert result is False


class TestDrag:
    @pytest.mark.unit
    async def test_drag(self, backend, mock_subprocess_run):
        await backend.drag(0, 0, 100, 200, duration=0.0)
        # Two invocations: dc at start, then move to end
        assert mock_subprocess_run.call_count == 2
        first = mock_subprocess_run.call_args_list[0].args[0]
        assert first[-1] == "dc:0,0"
        second = mock_subprocess_run.call_args_list[1].args[0]
        assert second[-1] == "100,200"

    @pytest.mark.unit
    async def test_drag_failure(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _fail("nope")
        result = await backend.drag(0, 0, 1, 1)
        assert result is False


class TestScroll:
    @pytest.mark.unit
    async def test_scroll(self, backend, mock_subprocess_run):
        await backend.scroll(50, 60, dx=0, dy=-3)
        # Two invocations: move then scroll
        first = mock_subprocess_run.call_args_list[0].args[0]
        assert first[-1] == "m:50,60"
        second = mock_subprocess_run.call_args_list[1].args[0]
        assert second[-1] == "sw:0,-3"

    @pytest.mark.unit
    async def test_scroll_failure(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _fail("nope")
        result = await backend.scroll(0, 0, 0, -1)
        assert result is False


# =============================================================================
# Screenshot
# =============================================================================


class TestScreenshot:
    @pytest.mark.unit
    async def test_screenshot_full_screen(self, backend, mock_subprocess_run, tmp_path):
        # Create a real PNG file that the screencapture command will write
        png_file = tmp_path / "screen.png"
        png_file.write_bytes(b"\x89PNG_FAKE_DATA")

        # Patch tempfile.NamedTemporaryFile at the global level; the source
        # imports tempfile inside the function so we patch the stdlib name.
        fake_temp = MagicMock()
        fake_temp.name = str(png_file)

        def fake_named_temp(*args, **kwargs):
            # The implementation uses `with tempfile.NamedTemporaryFile(...) as tmp:`
            # which calls __enter__ on the return value
            fake_temp.__enter__ = MagicMock(return_value=fake_temp)
            fake_temp.__exit__ = MagicMock(return_value=False)
            return fake_temp

        with patch("tempfile.NamedTemporaryFile", side_effect=fake_named_temp):
            data = await backend.screenshot()

        assert data == b"\x89PNG_FAKE_DATA"
        # screencapture was invoked
        first_cmd = mock_subprocess_run.call_args_list[0].args[0]
        assert first_cmd[0] == "screencapture"
        assert first_cmd[1] == "-x"

    @pytest.mark.unit
    async def test_screenshot_with_region(self, backend, mock_subprocess_run, tmp_path):
        png_file = tmp_path / "screen.png"
        png_file.write_bytes(b"\x89PNG")

        fake_temp = MagicMock()
        fake_temp.name = str(png_file)
        fake_temp.__enter__ = MagicMock(return_value=fake_temp)
        fake_temp.__exit__ = MagicMock(return_value=False)

        def fake_named_temp(*args, **kwargs):
            return fake_temp

        with patch("tempfile.NamedTemporaryFile", side_effect=fake_named_temp):
            data = await backend.screenshot(region=(10, 20, 100, 100))
        assert data == b"\x89PNG"
        first_cmd = mock_subprocess_run.call_args_list[0].args[0]
        # -R flag and coordinates
        assert "-R" in first_cmd
        assert "10,20,100,100" in first_cmd

    @pytest.mark.unit
    async def test_screenshot_timeout(self, backend, mock_subprocess_run):
        import subprocess

        mock_subprocess_run.side_effect = subprocess.TimeoutExpired(cmd="screencapture", timeout=10)
        with pytest.raises(RuntimeError) as exc:
            await backend.screenshot()
        assert "timed out" in str(exc.value)

    @pytest.mark.unit
    async def test_screenshot_generic_failure(self, backend, mock_subprocess_run):
        mock_subprocess_run.side_effect = OSError("display gone")
        with pytest.raises(RuntimeError):
            await backend.screenshot()


# =============================================================================
# list_screens
# =============================================================================


class TestListScreens:
    @pytest.mark.unit
    async def test_list_screens_empty(self, backend, mock_subprocess_run):
        mock_subprocess_run.return_value = _ok("")
        assert await backend.list_screens() == []

    @pytest.mark.unit
    async def test_list_screens_parses(self, backend, mock_subprocess_run):
        out = (
            "idx:1|name:Display 1|x:0|y:0|w:1920|h:1080|primary:true\n"
            "idx:2|name:Display 2|x:1920|y:0|w:2560|h:1440|primary:false"
        )
        mock_subprocess_run.return_value = _ok(out)
        screens = await backend.list_screens()
        assert len(screens) == 2
        assert screens[0].primary is True
        assert screens[0].size == (1920, 1080)
        assert screens[1].name == "Display 2"
        assert screens[1].primary is False

    @pytest.mark.unit
    async def test_list_screens_handles_exception(self, backend, mock_subprocess_run):
        mock_subprocess_run.side_effect = RuntimeError("boom")
        screens = await backend.list_screens()
        assert screens == []
