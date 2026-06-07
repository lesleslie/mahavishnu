"""Unit tests for mahavishnu.automation.backends.pyautogui.

Mocks pyautogui at module level so importing it does not move the real
mouse. Covers:
- is_available
- _get_pyautogui
- _run_sync / executor
- Application operations (most raise AutomationError)
- Window operations (most raise AutomationError)
- Menu operations (raise AutomationError)
- Input operations (type_text, press_key, click, drag, scroll)
- _normalize_key
- Screenshot (mss and pyautogui paths)
- list_screens
- move_to, get_mouse_position, locate_on_screen, locate_center_on_screen
- alert, confirm, prompt
- close() cleanup
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.automation.backends.pyautogui import PyAutoGUIBackend
from mahavishnu.automation.errors import AutomationError, ScreenshotError

# =============================================================================
# Module-level mock for pyautogui to prevent real mouse movement
# =============================================================================


@pytest.fixture(autouse=True)
def mock_pyautogui_module():
    """Inject a mock pyautogui module so any import gets a MagicMock."""
    mock_module = MagicMock()
    mock_module.FAILSAFE = False
    mock_module.PAUSE = 0.0
    with patch.dict(sys.modules, {"pyautogui": mock_module}):
        # Also clear any cached backend instance
        yield mock_module


@pytest.fixture
def backend() -> PyAutoGUIBackend:
    return PyAutoGUIBackend()


# =============================================================================
# is_available
# =============================================================================


class TestIsAvailable:
    @pytest.mark.unit
    def test_is_available_true_when_imported(self, mock_pyautogui_module):
        with patch.dict(sys.modules, {"pyautogui": mock_pyautogui_module}):
            assert PyAutoGUIBackend.is_available() is True

    @pytest.mark.unit
    def test_is_available_false_on_import_error(self):
        # When the module is None, the import inside is_available raises ImportError
        with patch.dict(sys.modules, {"pyautogui": None}):
            assert PyAutoGUIBackend.is_available() is False


# =============================================================================
# Identity
# =============================================================================


class TestIdentity:
    @pytest.mark.unit
    def test_backend_name(self, backend):
        assert backend.backend_name == "pyautogui"

    @pytest.mark.unit
    def test_initial_pyautogui_is_none(self, backend):
        assert backend._pyautogui is None

    @pytest.mark.unit
    def test_executor_created_at_init(self, backend):
        assert backend._executor is not None
        from concurrent.futures import ThreadPoolExecutor

        assert isinstance(backend._executor, ThreadPoolExecutor)


# =============================================================================
# _get_pyautogui
# =============================================================================


class TestGetPyautogui:
    @pytest.mark.unit
    def test_caches_pyautogui(self, backend, mock_pyautogui_module):
        first = backend._get_pyautogui()
        second = backend._get_pyautogui()
        assert first is second
        assert first is mock_pyautogui_module

    @pytest.mark.unit
    def test_configures_safety(self, backend, mock_pyautogui_module):
        backend._get_pyautogui()
        # The implementation sets these to True / 0.05
        assert mock_pyautogui_module.FAILSAFE is True
        assert mock_pyautogui_module.PAUSE == 0.05

    @pytest.mark.unit
    def test_import_error_raises_automation_error(self, backend):
        # If pyautogui is removed from sys.modules AFTER caching, the cached
        # attribute still works. To exercise the ImportError path, we
        # override _pyautogui to None and force a re-import.
        backend._pyautogui = None
        with patch.dict(sys.modules, {"pyautogui": None}):
            with pytest.raises(AutomationError) as exc:
                backend._get_pyautogui()
        assert "pyautogui" in str(exc.value).lower()


# =============================================================================
# Application operations (mostly not supported)
# =============================================================================


class TestApplicationOperations:
    @pytest.mark.unit
    async def test_launch_application_raises(self, backend):
        with pytest.raises(AutomationError) as exc:
            await backend.launch_application("com.apple.finder")
        assert "Application management" in str(exc.value)

    @pytest.mark.unit
    async def test_get_application_returns_none(self, backend):
        assert await backend.get_application("com.apple.finder") is None

    @pytest.mark.unit
    async def test_list_applications_returns_empty(self, backend):
        assert await backend.list_applications() == []

    @pytest.mark.unit
    async def test_quit_application_raises(self, backend):
        with pytest.raises(AutomationError):
            await backend.quit_application("com.apple.finder")

    @pytest.mark.unit
    async def test_quit_application_force_kwarg_ignored(self, backend):
        # force=True is accepted but the operation still raises
        with pytest.raises(AutomationError):
            await backend.quit_application("com.apple.finder", force=True)

    @pytest.mark.unit
    async def test_activate_application_raises(self, backend):
        with pytest.raises(AutomationError):
            await backend.activate_application("com.apple.finder")

    @pytest.mark.unit
    async def test_get_active_application_returns_none(self, backend):
        assert await backend.get_active_application() is None


# =============================================================================
# Window operations (mostly not supported)
# =============================================================================


class TestWindowOperations:
    @pytest.mark.unit
    async def test_get_windows_returns_empty(self, backend):
        assert await backend.get_windows("com.apple.finder") == []

    @pytest.mark.unit
    async def test_activate_window_raises(self, backend):
        with pytest.raises(AutomationError):
            await backend.activate_window("42")

    @pytest.mark.unit
    async def test_resize_window_raises(self, backend):
        with pytest.raises(AutomationError):
            await backend.resize_window("42", 800, 600)

    @pytest.mark.unit
    async def test_move_window_raises(self, backend):
        with pytest.raises(AutomationError):
            await backend.move_window("42", 10, 20)

    @pytest.mark.unit
    async def test_close_window_raises(self, backend):
        with pytest.raises(AutomationError):
            await backend.close_window("42")


# =============================================================================
# Menu operations
# =============================================================================


class TestMenuOperations:
    @pytest.mark.unit
    async def test_click_menu_item_raises(self, backend):
        with pytest.raises(AutomationError):
            await backend.click_menu_item("com.apple.finder", ["File", "Save"])

    @pytest.mark.unit
    async def test_list_menus_returns_empty(self, backend):
        assert await backend.list_menus("com.apple.finder") == []


# =============================================================================
# Input operations
# =============================================================================


class TestTypeText:
    @pytest.mark.unit
    async def test_type_text_calls_write(self, backend, mock_pyautogui_module):
        result = await backend.type_text("hello", interval=0.0)
        assert result is True
        mock_pyautogui_module.write.assert_called_once_with("hello", interval=0.0)

    @pytest.mark.unit
    async def test_type_text_uses_default_interval(self, backend, mock_pyautogui_module):
        result = await backend.type_text("x")
        assert result is True
        mock_pyautogui_module.write.assert_called_once_with("x", interval=0.05)

    @pytest.mark.unit
    async def test_type_text_failure_returns_false(self, backend, mock_pyautogui_module):
        mock_pyautogui_module.write.side_effect = RuntimeError("boom")
        result = await backend.type_text("x")
        assert result is False


class TestPressKey:
    @pytest.mark.unit
    async def test_press_key_no_modifiers(self, backend, mock_pyautogui_module):
        result = await backend.press_key("enter")
        assert result is True
        mock_pyautogui_module.press.assert_called_once_with("enter")

    @pytest.mark.unit
    async def test_press_key_with_modifiers(self, backend, mock_pyautogui_module):
        result = await backend.press_key("a", modifiers=["cmd", "shift"])
        assert result is True
        # hotkey called with all keys including the normalized one
        mock_pyautogui_module.hotkey.assert_called_once_with("cmd", "shift", "a")

    @pytest.mark.unit
    async def test_press_key_failure_returns_false(self, backend, mock_pyautogui_module):
        mock_pyautogui_module.press.side_effect = RuntimeError("boom")
        result = await backend.press_key("a")
        assert result is False


class TestNormalizeKey:
    @pytest.mark.unit
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("return", "enter"),
            ("enter", "enter"),
            ("escape", "escape"),
            ("esc", "escape"),
            ("pageup", "pageup"),
            ("pagedown", "pagedown"),
            ("capslock", "capslock"),
            ("a", "a"),
            ("A", "A"),  # single char returned as-is
            ("f1", "f1"),
            ("F12", "f12"),
            ("unknown", "unknown"),
        ],
    )
    def test_normalize_key_mapping(self, backend, raw: str, expected: str):
        assert backend._normalize_key(raw) == expected


class TestClick:
    @pytest.mark.unit
    async def test_click(self, backend, mock_pyautogui_module):
        result = await backend.click(100, 200)
        assert result is True
        mock_pyautogui_module.click.assert_called_once_with(100, 200, clicks=1, button="left")

    @pytest.mark.unit
    async def test_click_right_double(self, backend, mock_pyautogui_module):
        result = await backend.click(10, 20, button="right", clicks=2)
        assert result is True
        mock_pyautogui_module.click.assert_called_once_with(10, 20, clicks=2, button="right")

    @pytest.mark.unit
    async def test_click_failure(self, backend, mock_pyautogui_module):
        mock_pyautogui_module.click.side_effect = RuntimeError("boom")
        result = await backend.click(0, 0)
        assert result is False


class TestDrag:
    @pytest.mark.unit
    async def test_drag(self, backend, mock_pyautogui_module):
        result = await backend.drag(0, 0, 100, 200, duration=0.5)
        assert result is True
        mock_pyautogui_module.moveTo.assert_called_once_with(0, 0)
        mock_pyautogui_module.drag.assert_called_once_with(100, 200, duration=0.5, button="left")

    @pytest.mark.unit
    async def test_drag_failure(self, backend, mock_pyautogui_module):
        mock_pyautogui_module.moveTo.side_effect = RuntimeError("boom")
        result = await backend.drag(0, 0, 1, 1)
        assert result is False


class TestScroll:
    @pytest.mark.unit
    async def test_scroll(self, backend, mock_pyautogui_module):
        result = await backend.scroll(50, 60, dx=0, dy=-3)
        assert result is True
        mock_pyautogui_module.moveTo.assert_called_once_with(50, 60)
        mock_pyautogui_module.scroll.assert_called_once_with(-3, 50, 60)

    @pytest.mark.unit
    async def test_scroll_failure(self, backend, mock_pyautogui_module):
        mock_pyautogui_module.moveTo.side_effect = RuntimeError("boom")
        result = await backend.scroll(0, 0, 0, -1)
        assert result is False


# =============================================================================
# Screenshot
# =============================================================================


class TestScreenshot:
    @pytest.mark.unit
    async def test_screenshot_pyautogui_path(self, backend, mock_pyautogui_module):
        from PIL import Image

        with patch.dict(sys.modules, {"mss": None}):
            # mss is None -> ImportError -> falls back to pyautogui
            mock_pyautogui_module.screenshot.return_value = Image.new("RGB", (10, 10))
            result = await backend.screenshot()
        assert isinstance(result, bytes)
        assert len(result) > 0  # PNG header bytes

    @pytest.mark.unit
    async def test_screenshot_with_region(self, backend, mock_pyautogui_module):
        from PIL import Image

        with patch.dict(sys.modules, {"mss": None}):
            mock_pyautogui_module.screenshot.return_value = Image.new("RGB", (10, 10))
            result = await backend.screenshot(region=(10, 20, 100, 100))
        assert isinstance(result, bytes)
        mock_pyautogui_module.screenshot.assert_called_with(region=(10, 20, 100, 100))

    @pytest.mark.unit
    async def test_screenshot_failure_raises_screenshot_error(self, backend, mock_pyautogui_module):
        with patch.dict(sys.modules, {"mss": None}):
            mock_pyautogui_module.screenshot.side_effect = RuntimeError("display gone")
            with pytest.raises(ScreenshotError) as exc:
                await backend.screenshot()
        assert "display gone" in str(exc.value)

    @pytest.mark.unit
    async def test_screenshot_uses_mss_when_available(self, backend, mock_pyautogui_module):
        # Build a fake mss screenshot
        fake_screenshot = MagicMock()
        fake_screenshot.size = (10, 10)
        fake_screenshot.bgra = b"\x00" * (10 * 10 * 4)

        mss_ctx = MagicMock()
        mss_ctx.monitors = [
            {"left": 0, "top": 0, "width": 100, "height": 100},
            {"left": 0, "top": 0, "width": 100, "height": 100},
        ]
        mss_ctx.grab.return_value = fake_screenshot
        mss_module = MagicMock()
        mss_module.mss.return_value.__enter__.return_value = mss_ctx

        # PIL Image.frombytes returns a real Image we can save

        with patch.dict(sys.modules, {"mss": mss_module}):
            result = await backend.screenshot()
        assert isinstance(result, bytes)
        # mss path was used
        mss_ctx.grab.assert_called_once()


# =============================================================================
# list_screens
# =============================================================================


class TestListScreens:
    @pytest.mark.unit
    async def test_list_screens_primary_only(self, backend, mock_pyautogui_module):
        # Force mss import to fail
        with patch.dict(sys.modules, {"mss": None}):
            size = MagicMock()
            size.width = 1920
            size.height = 1080
            mock_pyautogui_module.size.return_value = size
            screens = await backend.list_screens()
        assert len(screens) == 1
        assert screens[0].name == "Primary Display"
        assert screens[0].size == (1920, 1080)
        assert screens[0].primary is True

    @pytest.mark.unit
    async def test_list_screens_failure_returns_empty(self, backend, mock_pyautogui_module):
        mock_pyautogui_module.size.side_effect = RuntimeError("no display")
        screens = await backend.list_screens()
        assert screens == []


# =============================================================================
# Additional PyAutoGUI methods
# =============================================================================


class TestAdditionalMethods:
    @pytest.mark.unit
    async def test_move_to(self, backend, mock_pyautogui_module):
        result = await backend.move_to(50, 60, duration=0.1)
        assert result is True
        mock_pyautogui_module.moveTo.assert_called_once_with(50, 60, duration=0.1)

    @pytest.mark.unit
    async def test_move_to_failure(self, backend, mock_pyautogui_module):
        mock_pyautogui_module.moveTo.side_effect = RuntimeError("fail")
        result = await backend.move_to(0, 0)
        assert result is False

    @pytest.mark.unit
    async def test_get_mouse_position(self, backend, mock_pyautogui_module):
        pos = MagicMock()
        pos.x = 100
        pos.y = 200
        mock_pyautogui_module.position.return_value = pos
        result = await backend.get_mouse_position()
        assert result == (100, 200)

    @pytest.mark.unit
    async def test_locate_on_screen_found(self, backend, mock_pyautogui_module):
        loc = MagicMock()
        loc.left = 10
        loc.top = 20
        loc.width = 100
        loc.height = 50
        mock_pyautogui_module.locateOnScreen.return_value = loc
        result = await backend.locate_on_screen("/tmp/foo.png")
        assert result == (10, 20, 100, 50)

    @pytest.mark.unit
    async def test_locate_on_screen_not_found(self, backend, mock_pyautogui_module):
        mock_pyautogui_module.locateOnScreen.return_value = None
        result = await backend.locate_on_screen("/tmp/foo.png")
        assert result is None

    @pytest.mark.unit
    async def test_locate_on_screen_error(self, backend, mock_pyautogui_module):
        mock_pyautogui_module.locateOnScreen.side_effect = RuntimeError("fail")
        result = await backend.locate_on_screen("/tmp/foo.png")
        assert result is None

    @pytest.mark.unit
    async def test_locate_center_on_screen_found(self, backend, mock_pyautogui_module):
        loc = MagicMock()
        loc.x = 100
        loc.y = 200
        mock_pyautogui_module.locateCenterOnScreen.return_value = loc
        result = await backend.locate_center_on_screen("/tmp/foo.png")
        assert result == (100, 200)

    @pytest.mark.unit
    async def test_locate_center_on_screen_not_found(self, backend, mock_pyautogui_module):
        mock_pyautogui_module.locateCenterOnScreen.return_value = None
        result = await backend.locate_center_on_screen("/tmp/foo.png")
        assert result is None

    @pytest.mark.unit
    async def test_alert(self, backend, mock_pyautogui_module):
        await backend.alert("hello", title="My Alert")
        mock_pyautogui_module.alert.assert_called_once_with(text="hello", title="My Alert")

    @pytest.mark.unit
    async def test_confirm_returns_true_for_ok(self, backend, mock_pyautogui_module):
        mock_pyautogui_module.confirm.return_value = "OK"
        result = await backend.confirm("Are you sure?")
        assert result is True

    @pytest.mark.unit
    async def test_confirm_returns_false_for_cancel(self, backend, mock_pyautogui_module):
        mock_pyautogui_module.confirm.return_value = "Cancel"
        result = await backend.confirm("Are you sure?")
        assert result is False

    @pytest.mark.unit
    async def test_prompt_returns_user_input(self, backend, mock_pyautogui_module):
        mock_pyautogui_module.prompt.return_value = "user typed this"
        result = await backend.prompt("Enter name:", default="foo")
        assert result == "user typed this"
        mock_pyautogui_module.prompt.assert_called_once_with(
            text="Enter name:", title="Prompt", default="foo"
        )

    @pytest.mark.unit
    async def test_prompt_returns_none_on_cancel(self, backend, mock_pyautogui_module):
        mock_pyautogui_module.prompt.return_value = None
        result = await backend.prompt("Enter:")
        assert result is None


# =============================================================================
# close()
# =============================================================================


class TestClose:
    @pytest.mark.unit
    async def test_close_shuts_down_and_clears(self, backend):
        executor = backend._executor
        assert executor is not None
        await backend.close()
        assert backend._executor is None
        assert backend._pyautogui is None

    @pytest.mark.unit
    async def test_close_when_already_closed(self, backend):
        await backend.close()
        # second close should be a no-op, not raise
        await backend.close()
        assert backend._executor is None
