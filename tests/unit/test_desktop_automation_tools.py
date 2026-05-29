# tests/unit/test_desktop_automation_tools.py
"""Unit tests for desktop_automation_tools MCP module."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Import the module under test (conftest.py handles mcp_common.types shim).
import mahavishnu.mcp.tools.desktop_automation_tools as dat_module


# Session-scoped fixture: replace AutomationManager with _FakeManager for the
# entire test module so that get_manager() always gets our fake.
@pytest.fixture(scope="module", autouse=True)
def fake_automation_manager():
    with patch.object(dat_module, "AutomationManager", return_value=_FakeManager()):
        yield


# This fixture must remain autouse=True so that _manager is reset between tests.
# The session-scoped fake_automation_manager patch applies before this runs.
@pytest.fixture(autouse=True)
def reset_manager():
    """Reset the global _manager before and after each test."""
    dat_module._manager = None
    yield
    dat_module._manager = None


# ---------------------------------------------------------------------------
# Fake AutomationManager
# ---------------------------------------------------------------------------


def _make_fake_result(
    status: str = "success",
    data: Any = None,
    message: str = "ok",
    **extra: Any,
) -> MagicMock:
    """Return a fake AutomationResult with .to_dict() support."""
    r = MagicMock()
    r.status = status
    r.data = data
    r.message = message
    r.to_dict.return_value = {"status": status, "data": data, "message": message, **extra}
    return r


class _FakeManager:
    _initialized = True

    def __init__(self, config=None) -> None:
        self._config = config

    async def initialize(self) -> None:
        self._initialized = True

    async def close(self) -> None:
        self._initialized = False

    def get_backend_name(self) -> str:
        return "fake-backend"

    def get_stats(self) -> dict[str, Any]:
        return {"total_ops": 1}

    def get_capabilities(self) -> list[str]:
        return ["launch_app", "quit_app", "type_text", "screenshot"]

    # ── permission ──────────────────────────────────────────────────────────

    async def check_permissions(self) -> MagicMock:
        return _make_fake_result(permissions={"accessibility": True})

    # ── app ──────────────────────────────────────────────────────────────────

    async def launch_application(self, bundle_id: str, dry_run: bool = False) -> MagicMock:
        return _make_fake_result(launched=bundle_id)

    async def quit_application(self, bundle_id: str, force: bool = False) -> MagicMock:
        return _make_fake_result(quit=bundle_id)

    async def activate_application(self, bundle_id: str) -> MagicMock:
        return _make_fake_result(activated=bundle_id)

    async def list_applications(self) -> MagicMock:
        return _make_fake_result(data=[{"bundle_id": "com.apple.finder", "name": "Finder"}])

    async def get_active_application(self) -> MagicMock:
        return _make_fake_result(data={"bundle_id": "com.apple.Terminal", "name": "Terminal"})

    # ── window ───────────────────────────────────────────────────────────────

    async def get_windows(self, bundle_id: str) -> MagicMock:
        return _make_fake_result(data=[{"id": "win1", "title": "Test"}])

    async def resize_window(self, window_id: str, width: int, height: int) -> MagicMock:
        return _make_fake_result(resized=(window_id, width, height))

    async def move_window(self, window_id: str, x: int, y: int) -> MagicMock:
        return _make_fake_result(moved=(window_id, x, y))

    async def close_window(self, window_id: str) -> MagicMock:
        return _make_fake_result(closed=window_id)

    # ── menu ─────────────────────────────────────────────────────────────────

    async def click_menu_item(self, bundle_id: str, menu_path: list[str]) -> MagicMock:
        return _make_fake_result(clicked=(bundle_id, menu_path))

    async def list_menus(self, bundle_id: str) -> MagicMock:
        return _make_fake_result(data=["File", "Edit"])

    # ── input ────────────────────────────────────────────────────────────────

    async def type_text(
        self, text: str, interval: float = 0.05, dry_run: bool = False
    ) -> MagicMock:
        return _make_fake_result(typed=text)

    async def press_key(self, key: str, modifiers: list[str] | None = None) -> MagicMock:
        return _make_fake_result(pressed=(key, modifiers))

    async def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> MagicMock:
        return _make_fake_result(clicked=(x, y, button, clicks))

    async def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.5,
    ) -> MagicMock:
        return _make_fake_result(dragged=(start_x, start_y, end_x, end_y, duration))

    async def scroll(self, x: int, y: int, dx: int = 0, dy: int = 0) -> MagicMock:
        return _make_fake_result(scrolled=(x, y, dx, dy))

    # ── screenshot ────────────────────────────────────────────────────────────

    async def screenshot(self, region=None) -> MagicMock:
        return _make_fake_result(
            status="success",
            data=b"FAKE_IMAGE_BYTES",
        )

    async def list_screens(self) -> MagicMock:
        return _make_fake_result(data=[{"id": "main", "width": 1920, "height": 1080}])

    # ── ui elements ──────────────────────────────────────────────────────────

    async def get_ui_elements(self, bundle_id: str, window_id: str | None = None) -> MagicMock:
        return _make_fake_result(data=[{"label": "OK", "type": "button"}])

    # ── security ────────────────────────────────────────────────────────────

    @property
    def _security(self) -> MagicMock:
        s = MagicMock()
        s.to_dict.return_value = {"blocklist": [], "allowlist": []}
        return s


# ---------------------------------------------------------------------------
# Fake FastMCP
# ---------------------------------------------------------------------------


class _FakeMCP:
    """Fake FastMCP that records @mcp.tool() decorated callables."""

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        """Decorator that registers a function without doing anything special."""

        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


# ---------------------------------------------------------------------------
# Tests: get_manager() lazy initialisation
# ---------------------------------------------------------------------------


def test_get_manager_creates_instance_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_manager() should create exactly one manager (singleton)."""
    created = []

    def factory(*args, **kwargs):
        created.append((args, kwargs))
        return _FakeManager(*args, **kwargs)

    monkeypatch.setattr(dat_module, "AutomationManager", factory)

    m1 = dat_module.get_manager()
    m2 = dat_module.get_manager()
    assert m1 is m2
    assert len(created) == 1


def test_get_manager_with_custom_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_manager() should pass a default AutomationConfig when no config is provided."""
    received_config = []

    def factory(config=None, **kwargs):
        if config is not None:
            received_config.append(config)
        return _FakeManager(config=config, **kwargs)

    monkeypatch.setattr(dat_module, "AutomationManager", factory)

    dat_module.get_manager()
    assert len(received_config) == 1
    assert received_config[0] is not None


# ---------------------------------------------------------------------------
# Tests: tool registration
# ---------------------------------------------------------------------------


def test_tools_registered_with_fake_mcp() -> None:
    """All 22 tools should be registered when register_desktop_automation_tools is called."""
    fake_mcp = _FakeMCP()
    with patch.object(dat_module, "AutomationManager", return_value=_FakeManager()):
        dat_module.register_desktop_automation_tools(fake_mcp)

    # Assert all 22 tools are present
    assert len(fake_mcp.tools) == 23, (
        f"Expected 23 tools, got {len(fake_mcp.tools)}: {list(fake_mcp.tools)}"
    )

    expected = {
        "automation_check_permissions",
        "automation_status",
        "automation_launch_app",
        "automation_quit_app",
        "automation_activate_app",
        "automation_list_apps",
        "automation_get_active_app",
        "automation_list_windows",
        "automation_resize_window",
        "automation_move_window",
        "automation_close_window",
        "automation_click_menu",
        "automation_list_menus",
        "automation_type_text",
        "automation_press_key",
        "automation_click",
        "automation_drag",
        "automation_scroll",
        "automation_screenshot",
        "automation_list_screens",
        "automation_get_ui_elements",
        "automation_get_security_config",
        "automation_close",
    }
    assert set(fake_mcp.tools.keys()) == expected


# ---------------------------------------------------------------------------
# Tests: TOOLS_METADATA
# ---------------------------------------------------------------------------


def test_tools_metadata_count_matches() -> None:
    """TOOLS_METADATA should list all 22 tools."""
    assert dat_module.TOOLS_METADATA["count"] == 22
    assert set(dat_module.TOOLS_METADATA["tools"]) == {
        "automation_check_permissions",
        "automation_status",
        "automation_launch_app",
        "automation_quit_app",
        "automation_activate_app",
        "automation_list_apps",
        "automation_get_active_app",
        "automation_list_windows",
        "automation_resize_window",
        "automation_move_window",
        "automation_close_window",
        "automation_click_menu",
        "automation_list_menus",
        "automation_type_text",
        "automation_press_key",
        "automation_click",
        "automation_drag",
        "automation_scroll",
        "automation_screenshot",
        "automation_list_screens",
        "automation_get_ui_elements",
        "automation_get_security_config",
        "automation_close",
    }


# ---------------------------------------------------------------------------
# Tests: individual tool execution (all use the fake manager)
# ---------------------------------------------------------------------------


def _run_tool(name: str, **kwargs) -> dict[str, Any]:
    """Helper: call a registered tool by name with the given kwargs."""
    fake_mcp = _FakeMCP()
    with patch.object(dat_module, "AutomationManager", return_value=_FakeManager()):
        dat_module.register_desktop_automation_tools(fake_mcp)
    return fake_mcp.tools[name](**kwargs)


@pytest.mark.asyncio
async def test_automation_check_permissions() -> None:
    result = await _run_tool("automation_check_permissions")
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_status() -> None:
    result = await _run_tool("automation_status")
    assert "backend" in result
    assert "stats" in result
    assert "capabilities" in result


@pytest.mark.asyncio
async def test_automation_launch_app() -> None:
    result = await _run_tool("automation_launch_app", bundle_id="com.apple.Finder")
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_launch_app_dry_run() -> None:
    result = await _run_tool("automation_launch_app", bundle_id="com.apple.Finder", dry_run=True)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_quit_app() -> None:
    result = await _run_tool("automation_quit_app", bundle_id="com.apple.Finder")
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_quit_app_force() -> None:
    result = await _run_tool("automation_quit_app", bundle_id="com.apple.Finder", force=True)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_activate_app() -> None:
    result = await _run_tool("automation_activate_app", bundle_id="com.apple.Terminal")
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_list_apps() -> None:
    result = await _run_tool("automation_list_apps")
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_get_active_app() -> None:
    result = await _run_tool("automation_get_active_app")
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_list_windows() -> None:
    result = await _run_tool("automation_list_windows", bundle_id="com.apple.Finder")
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_resize_window() -> None:
    result = await _run_tool("automation_resize_window", window_id="win1", width=800, height=600)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_move_window() -> None:
    result = await _run_tool("automation_move_window", window_id="win1", x=100, y=200)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_close_window() -> None:
    result = await _run_tool("automation_close_window", window_id="win1")
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_click_menu() -> None:
    result = await _run_tool(
        "automation_click_menu", bundle_id="com.apple.Finder", menu_path=["File", "Save"]
    )
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_list_menus() -> None:
    result = await _run_tool("automation_list_menus", bundle_id="com.apple.Finder")
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_type_text() -> None:
    result = await _run_tool("automation_type_text", text="hello")
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_type_text_dry_run() -> None:
    result = await _run_tool("automation_type_text", text="hello", dry_run=True)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_press_key() -> None:
    result = await _run_tool("automation_press_key", key="return")
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_press_key_with_modifiers() -> None:
    result = await _run_tool("automation_press_key", key="s", modifiers=["cmd"])
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_click() -> None:
    result = await _run_tool("automation_click", x=100, y=200)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_click_right_button() -> None:
    result = await _run_tool("automation_click", x=100, y=200, button="right", clicks=2)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_drag() -> None:
    result = await _run_tool("automation_drag", start_x=0, start_y=0, end_x=100, end_y=100)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_scroll() -> None:
    result = await _run_tool("automation_scroll", x=100, y=100, dy=-50)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_screenshot_no_region() -> None:
    """Screenshot should return base64-encoded image data on success."""
    result = await _run_tool("automation_screenshot")
    assert result["status"] == "success"
    assert "image_base64" in result


@pytest.mark.asyncio
async def test_automation_screenshot_with_region() -> None:
    result = await _run_tool("automation_screenshot", region=[0, 0, 800, 600])
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_list_screens() -> None:
    result = await _run_tool("automation_list_screens")
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_get_ui_elements() -> None:
    result = await _run_tool("automation_get_ui_elements", bundle_id="com.apple.Finder")
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_get_ui_elements_with_window() -> None:
    result = await _run_tool(
        "automation_get_ui_elements", bundle_id="com.apple.Finder", window_id="win1"
    )
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_automation_get_security_config() -> None:
    result = await _run_tool("automation_get_security_config")
    assert "blocklist" in result


@pytest.mark.asyncio
async def test_automation_close() -> None:
    # Manually set _manager so the close actually runs
    dat_module._manager = _FakeManager()
    result = await _run_tool("automation_close")
    assert result["status"] == "closed"


# ---------------------------------------------------------------------------
# Test: automation_close when not initialized
# ---------------------------------------------------------------------------


def test_automation_close_when_not_initialized() -> None:
    """automation_close should return 'not_initialized' when _manager is None."""
    # Ensure manager is not set
    assert dat_module._manager is None

    async def run():
        return await _run_tool("automation_close")

    # Should not raise, should return not_initialized
    import asyncio

    result = asyncio.run(run())
    assert result["status"] == "not_initialized"
