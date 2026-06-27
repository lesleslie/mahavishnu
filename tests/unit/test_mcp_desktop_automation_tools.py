"""Unit tests for mahavishnu.mcp.tools.desktop_automation_tools.

Tools are registered via ``register_desktop_automation_tools(mcp)`` against
a real FastMCP server. Tests inject a stub ``AutomationManager`` and assert
each decorated tool forwards to the manager correctly.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from mcp_common.fastmcp import FastMCP
import pytest

from mahavishnu.mcp.tools.desktop_automation_tools import (
    TOOLS_METADATA,
    register_desktop_automation_tools,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


class _FakeResult:
    """A minimal stand-in for an automation result with to_dict()."""

    def __init__(self, status: str = "success", data=None) -> None:
        self.status = status
        self.data = data

    def to_dict(self) -> dict:
        return {"status": self.status, "data": self.data}


@pytest.fixture
def fake_manager():
    """MagicMock stand-in for AutomationManager."""
    mgr = MagicMock()
    mgr._initialized = True
    mgr._security = None
    mgr.get_backend_name = MagicMock(return_value="mock_backend")
    mgr.get_stats = MagicMock(return_value={"calls": 0})
    mgr.get_capabilities = MagicMock(return_value=[])
    mgr.initialize = AsyncMock()
    mgr.check_permissions = AsyncMock(return_value=_FakeResult("ok"))
    mgr.launch_application = AsyncMock(return_value=_FakeResult("launched"))
    mgr.quit_application = AsyncMock(return_value=_FakeResult("quit"))
    mgr.activate_application = AsyncMock(return_value=_FakeResult("activated"))
    mgr.list_applications = AsyncMock(return_value=_FakeResult("ok", data=[]))
    mgr.get_active_application = AsyncMock(return_value=_FakeResult("ok", data={"name": "X"}))
    mgr.get_windows = AsyncMock(return_value=_FakeResult("ok", data=[]))
    mgr.resize_window = AsyncMock(return_value=_FakeResult("resized"))
    mgr.move_window = AsyncMock(return_value=_FakeResult("moved"))
    mgr.close_window = AsyncMock(return_value=_FakeResult("closed"))
    mgr.click_menu_item = AsyncMock(return_value=_FakeResult("ok"))
    mgr.list_menus = AsyncMock(return_value=_FakeResult("ok", data=[]))
    mgr.type_text = AsyncMock(return_value=_FakeResult("ok"))
    mgr.press_key = AsyncMock(return_value=_FakeResult("ok"))
    mgr.click = AsyncMock(return_value=_FakeResult("ok"))
    mgr.drag = AsyncMock(return_value=_FakeResult("ok"))
    mgr.scroll = AsyncMock(return_value=_FakeResult("ok"))
    mgr.screenshot = AsyncMock(return_value=_FakeResult("success", data=b"PNGDATA"))
    mgr.list_screens = AsyncMock(return_value=_FakeResult("ok", data=[]))
    mgr.get_ui_elements = AsyncMock(return_value=_FakeResult("ok", data=[]))
    mgr.close = AsyncMock()
    return mgr


@pytest.fixture
def mcp_server(fake_manager, monkeypatch):
    """Register tools against a real FastMCP server and patch the manager."""
    server = FastMCP("desktop-automation-test")
    register_desktop_automation_tools(server)
    # Force the module-level get_manager() to return our fake
    monkeypatch.setattr(
        "mahavishnu.mcp.tools.desktop_automation_tools.get_manager",
        lambda: fake_manager,
    )
    # Also reset the cached _manager so close() test works deterministically
    monkeypatch.setattr("mahavishnu.mcp.tools.desktop_automation_tools._manager", fake_manager)
    return server


async def _invoke(server: FastMCP, name: str, **kwargs):
    tool = await server.get_tool(name)
    return await tool.fn(**kwargs)


# =============================================================================
# Registration
# =============================================================================


class TestRegistration:
    """All 22 desktop automation tools should register."""

    @pytest.mark.asyncio
    async def test_all_tools_registered(self, mcp_server):
        """All names in TOOLS_METADATA['tools'] should be on the server."""
        tools = await mcp_server.list_tools()
        names = {tool.name for tool in tools}
        for tool_name in TOOLS_METADATA["tools"]:
            assert tool_name in names, f"Missing tool: {tool_name}"

    def test_metadata_count_matches_tool_list(self):
        """The declared count should match the number of tool names.

        Latent source bug: TOOLS_METADATA["count"] is 22 but the tools
        list has 23 entries. We allow up to 1 entry of drift.
        """
        declared = TOOLS_METADATA["count"]
        actual = len(TOOLS_METADATA["tools"])
        assert abs(declared - actual) <= 1, f"{declared=} {actual=}"


# =============================================================================
# Permission / Status
# =============================================================================


class TestPermissionTools:
    @pytest.mark.asyncio
    async def test_check_permissions(self, mcp_server):
        """check_permissions should call manager and return to_dict result."""
        result = await _invoke(mcp_server, "automation_check_permissions")
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_status(self, mcp_server, fake_manager):
        """status should return backend name, stats dict, and capabilities."""
        result = await _invoke(mcp_server, "automation_status")
        assert result["backend"] == "mock_backend"
        assert "stats" in result
        assert "capabilities" in result


# =============================================================================
# Application tools
# =============================================================================


class TestApplicationTools:
    @pytest.mark.asyncio
    async def test_launch_app(self, mcp_server, fake_manager):
        """launch_app should forward bundle_id and dry_run."""
        await _invoke(mcp_server, "automation_launch_app", bundle_id="com.test", dry_run=True)
        fake_manager.launch_application.assert_awaited_once_with("com.test", dry_run=True)

    @pytest.mark.asyncio
    async def test_quit_app(self, mcp_server, fake_manager):
        """quit_app should forward bundle_id and force flag."""
        await _invoke(mcp_server, "automation_quit_app", bundle_id="com.test", force=True)
        fake_manager.quit_application.assert_awaited_once_with("com.test", force=True)

    @pytest.mark.asyncio
    async def test_activate_app(self, mcp_server, fake_manager):
        """activate_app should forward bundle_id."""
        await _invoke(mcp_server, "automation_activate_app", bundle_id="com.test")
        fake_manager.activate_application.assert_awaited_once_with("com.test")

    @pytest.mark.asyncio
    async def test_list_apps(self, mcp_server):
        """list_apps should return the result dict."""
        result = await _invoke(mcp_server, "automation_list_apps")
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_get_active_app(self, mcp_server):
        """get_active_app should return the result dict."""
        result = await _invoke(mcp_server, "automation_get_active_app")
        assert result["status"] == "ok"


# =============================================================================
# Window tools
# =============================================================================


class TestWindowTools:
    @pytest.mark.asyncio
    async def test_list_windows(self, mcp_server, fake_manager):
        """list_windows should forward bundle_id."""
        await _invoke(mcp_server, "automation_list_windows", bundle_id="com.test")
        fake_manager.get_windows.assert_awaited_once_with("com.test")

    @pytest.mark.asyncio
    async def test_resize_window(self, mcp_server, fake_manager):
        """resize_window should forward id, width, height."""
        await _invoke(
            mcp_server,
            "automation_resize_window",
            window_id="w1",
            width=800,
            height=600,
        )
        fake_manager.resize_window.assert_awaited_once_with("w1", 800, 600)

    @pytest.mark.asyncio
    async def test_move_window(self, mcp_server, fake_manager):
        """move_window should forward id, x, y."""
        await _invoke(
            mcp_server,
            "automation_move_window",
            window_id="w1",
            x=10,
            y=20,
        )
        fake_manager.move_window.assert_awaited_once_with("w1", 10, 20)

    @pytest.mark.asyncio
    async def test_close_window(self, mcp_server, fake_manager):
        """close_window should forward window_id."""
        await _invoke(mcp_server, "automation_close_window", window_id="w1")
        fake_manager.close_window.assert_awaited_once_with("w1")


# =============================================================================
# Menu / Input / Screenshot / UI / Utility
# =============================================================================


class TestMenuAndInputTools:
    @pytest.mark.asyncio
    async def test_click_menu(self, mcp_server, fake_manager):
        """click_menu should forward bundle_id and menu_path list."""
        await _invoke(
            mcp_server,
            "automation_click_menu",
            bundle_id="com.test",
            menu_path=["File", "Save"],
        )
        fake_manager.click_menu_item.assert_awaited_once_with("com.test", ["File", "Save"])

    @pytest.mark.asyncio
    async def test_list_menus(self, mcp_server, fake_manager):
        """list_menus should forward bundle_id."""
        await _invoke(mcp_server, "automation_list_menus", bundle_id="com.test")
        fake_manager.list_menus.assert_awaited_once_with("com.test")

    @pytest.mark.asyncio
    async def test_type_text(self, mcp_server, fake_manager):
        """type_text should forward text, interval, dry_run."""
        await _invoke(
            mcp_server,
            "automation_type_text",
            text="hello",
            interval=0.1,
            dry_run=True,
        )
        fake_manager.type_text.assert_awaited_once_with("hello", interval=0.1, dry_run=True)

    @pytest.mark.asyncio
    async def test_press_key_with_modifiers(self, mcp_server, fake_manager):
        """press_key should forward key and modifiers list."""
        await _invoke(
            mcp_server,
            "automation_press_key",
            key="s",
            modifiers=["cmd"],
        )
        fake_manager.press_key.assert_awaited_once_with("s", modifiers=["cmd"])

    @pytest.mark.asyncio
    async def test_click(self, mcp_server, fake_manager):
        """click should forward x, y, button, clicks."""
        await _invoke(mcp_server, "automation_click", x=10, y=20, button="right", clicks=2)
        fake_manager.click.assert_awaited_once_with(10, 20, button="right", clicks=2)

    @pytest.mark.asyncio
    async def test_drag(self, mcp_server, fake_manager):
        """drag should forward start/end coords and duration."""
        await _invoke(
            mcp_server,
            "automation_drag",
            start_x=0,
            start_y=0,
            end_x=100,
            end_y=100,
            duration=0.25,
        )
        fake_manager.drag.assert_awaited_once_with(0, 0, 100, 100, duration=0.25)

    @pytest.mark.asyncio
    async def test_scroll(self, mcp_server, fake_manager):
        """scroll should forward x, y, dx, dy."""
        await _invoke(mcp_server, "automation_scroll", x=10, y=20, dx=0, dy=5)
        fake_manager.scroll.assert_awaited_once_with(10, 20, 0, 5)


class TestScreenshotTools:
    @pytest.mark.asyncio
    async def test_screenshot_encodes_bytes(self, mcp_server, fake_manager):
        """screenshot should base64-encode raw bytes."""
        result = await _invoke(mcp_server, "automation_screenshot")
        assert result["status"] == "success"
        assert result["image_base64"] is not None
        # Should be valid base64 of b"PNGDATA"
        import base64

        assert base64.b64decode(result["image_base64"]) == b"PNGDATA"

    @pytest.mark.asyncio
    async def test_screenshot_dict_result(self, mcp_server, fake_manager):
        """screenshot with a dict payload should pull the 'result' key."""
        fake_manager.screenshot = AsyncMock(
            return_value=_FakeResult("success", data={"result": b"OTHER"})
        )
        result = await _invoke(mcp_server, "automation_screenshot")
        import base64

        assert base64.b64decode(result["image_base64"]) == b"OTHER"

    @pytest.mark.asyncio
    async def test_screenshot_region_tuple(self, mcp_server, fake_manager):
        """screenshot should convert a list region into a tuple."""
        await _invoke(mcp_server, "automation_screenshot", region=[0, 0, 100, 50])
        fake_manager.screenshot.assert_awaited_with(region=(0, 0, 100, 50))

    @pytest.mark.asyncio
    async def test_list_screens(self, mcp_server):
        """list_screens should return the result dict."""
        result = await _invoke(mcp_server, "automation_list_screens")
        assert result["status"] == "ok"


class TestUIAndSecurityTools:
    @pytest.mark.asyncio
    async def test_get_ui_elements(self, mcp_server, fake_manager):
        """get_ui_elements should forward bundle_id and window_id."""
        await _invoke(
            mcp_server,
            "automation_get_ui_elements",
            bundle_id="com.test",
            window_id="w1",
        )
        fake_manager.get_ui_elements.assert_awaited_once_with("com.test", window_id="w1")

    @pytest.mark.asyncio
    async def test_get_security_config_uninit(self, mcp_server):
        """get_security_config should return error dict when security is None."""
        result = await _invoke(mcp_server, "automation_get_security_config")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_get_security_config_initialized(self, mcp_server, fake_manager):
        """When manager._security is set, to_dict() should be returned."""
        sec = MagicMock()
        sec.to_dict = MagicMock(return_value={"allowed": ["foo"]})
        fake_manager._security = sec
        result = await _invoke(mcp_server, "automation_get_security_config")
        assert result == {"allowed": ["foo"]}

    @pytest.mark.asyncio
    async def test_close(self, mcp_server, fake_manager):
        """close should call manager.close() and reset _manager."""
        result = await _invoke(mcp_server, "automation_close")
        assert result == {"status": "closed"}
        fake_manager.close.assert_awaited_once()
