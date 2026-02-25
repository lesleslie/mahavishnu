"""MCP tools for desktop automation.

Exposes desktop automation capabilities via MCP protocol for remote access.
Provides comprehensive tools for application, window, input, and screenshot operations.

Usage:
    These tools are registered with the FastMCP server when the automation
    module is initialized.
"""

from __future__ import annotations

import base64
from typing import Annotated, Any

from mcp_common.types import Field

from mahavishnu.automation import AutomationManager
from mahavishnu.automation.models import AutomationConfig

# Global manager instance
_manager: AutomationManager | None = None


def get_manager() -> AutomationManager:
    """Get or create the automation manager."""
    global _manager
    if _manager is None:
        config = AutomationConfig()
        _manager = AutomationManager(config=config)
    return _manager


def register_desktop_automation_tools(mcp: Any) -> None:
    """Register all desktop automation tools with the MCP server.

    Args:
        mcp: FastMCP server instance.
    """

    # =========================================================================
    # Permission Tools
    # =========================================================================

    @mcp.tool()
    async def automation_check_permissions() -> dict:
        """Check automation permissions (accessibility, screen recording).

        Returns:
            Dictionary with permission status.
        """
        manager = get_manager()
        await manager.initialize()

        result = await manager.check_permissions()
        return result.to_dict()

    @mcp.tool()
    async def automation_status() -> dict:
        """Get automation manager status and statistics.

        Returns:
            Dictionary with backend info and operation statistics.
        """
        manager = get_manager()

        if not manager._initialized:
            await manager.initialize()

        return {
            "backend": manager.get_backend_name(),
            "stats": manager.get_stats(),
            "capabilities": [str(c) for c in manager.get_capabilities()],
        }

    # =========================================================================
    # Application Tools
    # =========================================================================

    @mcp.tool()
    async def automation_launch_app(
        bundle_id: Annotated[str, Field(description="Application bundle identifier")],
        dry_run: Annotated[bool, Field(description="Simulate without executing")] = False,
    ) -> dict:
        """Launch an application by bundle identifier.

        Args:
            bundle_id: Application bundle ID (e.g., com.apple.finder).
            dry_run: If true, simulate without executing.

        Returns:
            Dictionary with application info.
        """
        manager = get_manager()
        await manager.initialize()

        result = await manager.launch_application(bundle_id, dry_run=dry_run)
        return result.to_dict()

    @mcp.tool()
    async def automation_quit_app(
        bundle_id: Annotated[str, Field(description="Application bundle identifier")],
        force: Annotated[bool, Field(description="Force quit")] = False,
    ) -> dict:
        """Quit an application.

        Args:
            bundle_id: Application bundle ID.
            force: Force quit if normal quit fails.

        Returns:
            Dictionary with operation result.
        """
        manager = get_manager()
        await manager.initialize()

        result = await manager.quit_application(bundle_id, force=force)
        return result.to_dict()

    @mcp.tool()
    async def automation_activate_app(
        bundle_id: Annotated[str, Field(description="Application bundle identifier")],
    ) -> dict:
        """Activate (bring to front) an application.

        Args:
            bundle_id: Application bundle ID.

        Returns:
            Dictionary with operation result.
        """
        manager = get_manager()
        await manager.initialize()

        result = await manager.activate_application(bundle_id)
        return result.to_dict()

    @mcp.tool()
    async def automation_list_apps() -> dict:
        """List all running applications.

        Returns:
            Dictionary with list of running applications.
        """
        manager = get_manager()
        await manager.initialize()

        result = await manager.list_applications()
        return result.to_dict()

    @mcp.tool()
    async def automation_get_active_app() -> dict:
        """Get the currently active (frontmost) application.

        Returns:
            Dictionary with active application info.
        """
        manager = get_manager()
        await manager.initialize()

        result = await manager.get_active_application()
        return result.to_dict()

    # =========================================================================
    # Window Tools
    # =========================================================================

    @mcp.tool()
    async def automation_list_windows(
        bundle_id: Annotated[str, Field(description="Application bundle identifier")],
    ) -> dict:
        """List all windows for an application.

        Args:
            bundle_id: Application bundle ID.

        Returns:
            Dictionary with list of windows.
        """
        manager = get_manager()
        await manager.initialize()

        result = await manager.get_windows(bundle_id)
        return result.to_dict()

    @mcp.tool()
    async def automation_resize_window(
        window_id: Annotated[str, Field(description="Window identifier")],
        width: Annotated[int, Field(description="New width in pixels")],
        height: Annotated[int, Field(description="New height in pixels")],
    ) -> dict:
        """Resize a window.

        Args:
            window_id: Window identifier.
            width: New width.
            height: New height.

        Returns:
            Dictionary with operation result.
        """
        manager = get_manager()
        await manager.initialize()

        result = await manager.resize_window(window_id, width, height)
        return result.to_dict()

    @mcp.tool()
    async def automation_move_window(
        window_id: Annotated[str, Field(description="Window identifier")],
        x: Annotated[int, Field(description="New X position")],
        y: Annotated[int, Field(description="New Y position")],
    ) -> dict:
        """Move a window to a new position.

        Args:
            window_id: Window identifier.
            x: New X position.
            y: New Y position.

        Returns:
            Dictionary with operation result.
        """
        manager = get_manager()
        await manager.initialize()

        result = await manager.move_window(window_id, x, y)
        return result.to_dict()

    @mcp.tool()
    async def automation_close_window(
        window_id: Annotated[str, Field(description="Window identifier")],
    ) -> dict:
        """Close a window.

        Args:
            window_id: Window identifier.

        Returns:
            Dictionary with operation result.
        """
        manager = get_manager()
        await manager.initialize()

        result = await manager.close_window(window_id)
        return result.to_dict()

    # =========================================================================
    # Menu Tools
    # =========================================================================

    @mcp.tool()
    async def automation_click_menu(
        bundle_id: Annotated[str, Field(description="Application bundle identifier")],
        menu_path: Annotated[list[str], Field(description="Menu path (e.g., ['File', 'Save'])")],
    ) -> dict:
        """Navigate menu and click an item.

        Args:
            bundle_id: Application bundle ID.
            menu_path: Path to menu item.

        Returns:
            Dictionary with operation result.
        """
        manager = get_manager()
        await manager.initialize()

        result = await manager.click_menu_item(bundle_id, menu_path)
        return result.to_dict()

    @mcp.tool()
    async def automation_list_menus(
        bundle_id: Annotated[str, Field(description="Application bundle identifier")],
    ) -> dict:
        """List all menus for an application.

        Args:
            bundle_id: Application bundle ID.

        Returns:
            Dictionary with list of menus.
        """
        manager = get_manager()
        await manager.initialize()

        result = await manager.list_menus(bundle_id)
        return result.to_dict()

    # =========================================================================
    # Input Tools
    # =========================================================================

    @mcp.tool()
    async def automation_type_text(
        text: Annotated[str, Field(description="Text to type")],
        interval: Annotated[float, Field(description="Delay between keystrokes")] = 0.05,
        dry_run: Annotated[bool, Field(description="Simulate")] = False,
    ) -> dict:
        """Type text at current cursor position.

        Args:
            text: Text to type.
            interval: Delay between keystrokes.
            dry_run: Simulate without executing.

        Returns:
            Dictionary with operation result.
        """
        manager = get_manager()
        await manager.initialize()

        result = await manager.type_text(text, interval=interval, dry_run=dry_run)
        return result.to_dict()

    @mcp.tool()
    async def automation_press_key(
        key: Annotated[str, Field(description="Key to press")],
        modifiers: Annotated[
            list[str] | None, Field(description="Modifiers (e.g., ['cmd', 'shift'])")
        ] = None,
    ) -> dict:
        """Press a key with optional modifiers.

        Args:
            key: Key to press (e.g., 'return', 'a', 'f1').
            modifiers: List of modifiers.

        Returns:
            Dictionary with operation result.
        """
        manager = get_manager()
        await manager.initialize()

        result = await manager.press_key(key, modifiers=modifiers)
        return result.to_dict()

    @mcp.tool()
    async def automation_click(
        x: Annotated[int, Field(description="X coordinate")],
        y: Annotated[int, Field(description="Y coordinate")],
        button: Annotated[str, Field(description="Mouse button (left/right/middle)")] = "left",
        clicks: Annotated[int, Field(description="Number of clicks")] = 1,
    ) -> dict:
        """Click at coordinates.

        Args:
            x: X coordinate.
            y: Y coordinate.
            button: Mouse button.
            clicks: Number of clicks (1=single, 2=double).

        Returns:
            Dictionary with operation result.
        """
        manager = get_manager()
        await manager.initialize()

        result = await manager.click(x, y, button=button, clicks=clicks)
        return result.to_dict()

    @mcp.tool()
    async def automation_drag(
        start_x: Annotated[int, Field(description="Starting X coordinate")],
        start_y: Annotated[int, Field(description="Starting Y coordinate")],
        end_x: Annotated[int, Field(description="Ending X coordinate")],
        end_y: Annotated[int, Field(description="Ending Y coordinate")],
        duration: Annotated[float, Field(description="Duration in seconds")] = 0.5,
    ) -> dict:
        """Drag from one point to another.

        Args:
            start_x: Starting X.
            start_y: Starting Y.
            end_x: Ending X.
            end_y: Ending Y.
            duration: Drag duration.

        Returns:
            Dictionary with operation result.
        """
        manager = get_manager()
        await manager.initialize()

        result = await manager.drag(start_x, start_y, end_x, end_y, duration=duration)
        return result.to_dict()

    @mcp.tool()
    async def automation_scroll(
        x: Annotated[int, Field(description="X coordinate")],
        y: Annotated[int, Field(description="Y coordinate")],
        dx: Annotated[int, Field(description="Horizontal scroll amount")] = 0,
        dy: Annotated[int, Field(description="Vertical scroll amount")] = 0,
    ) -> dict:
        """Scroll at coordinates.

        Args:
            x: X coordinate.
            y: Y coordinate.
            dx: Horizontal scroll.
            dy: Vertical scroll (negative = down).

        Returns:
            Dictionary with operation result.
        """
        manager = get_manager()
        await manager.initialize()

        result = await manager.scroll(x, y, dx, dy)
        return result.to_dict()

    # =========================================================================
    # Screenshot Tools
    # =========================================================================

    @mcp.tool()
    async def automation_screenshot(
        region: Annotated[
            list[int] | None,
            Field(description="Region [x, y, width, height] or None for full screen"),
        ] = None,
    ) -> dict:
        """Capture a screenshot.

        Args:
            region: Optional region [x, y, width, height].

        Returns:
            Dictionary with base64-encoded image.
        """
        manager = get_manager()
        await manager.initialize()

        region_tuple = tuple(region) if region else None
        result = await manager.screenshot(region=region_tuple)

        if result.status == "success" and result.data:
            # Encode image data as base64
            image_data = result.data
            if isinstance(image_data, bytes):
                image_base64 = base64.b64encode(image_data).decode("utf-8")
            elif isinstance(image_data, dict) and "result" in image_data:
                image_bytes = image_data["result"]
                image_base64 = base64.b64encode(image_bytes).decode("utf-8")
            else:
                image_base64 = None

            return {
                "status": "success",
                "image_base64": image_base64,
            }

        return result.to_dict()

    @mcp.tool()
    async def automation_list_screens() -> dict:
        """List all connected displays.

        Returns:
            Dictionary with list of displays.
        """
        manager = get_manager()
        await manager.initialize()

        result = await manager.list_screens()
        return result.to_dict()

    # =========================================================================
    # UI Element Tools
    # =========================================================================

    @mcp.tool()
    async def automation_get_ui_elements(
        bundle_id: Annotated[str, Field(description="Application bundle identifier")],
        window_id: Annotated[
            str | None, Field(description="Window identifier or None for all")
        ] = None,
    ) -> dict:
        """Get UI elements for an application.

        Args:
            bundle_id: Application bundle ID.
            window_id: Optional window ID.

        Returns:
            Dictionary with list of UI elements.
        """
        manager = get_manager()
        await manager.initialize()

        result = await manager.get_ui_elements(bundle_id, window_id=window_id)
        return result.to_dict()

    # =========================================================================
    # Utility Tools
    # =========================================================================

    @mcp.tool()
    async def automation_get_security_config() -> dict:
        """Get security configuration (blocklist, allowlist, etc.).

        Returns:
            Dictionary with security configuration.
        """
        manager = get_manager()
        if manager._security:
            return manager._security.to_dict()
        return {"error": "Security not initialized"}

    @mcp.tool()
    async def automation_close() -> dict:
        """Close the automation manager and release resources.

        Returns:
            Dictionary with status.
        """
        global _manager
        if _manager:
            await _manager.close()
            _manager = None
            return {"status": "closed"}
        return {"status": "not_initialized"}


# Tool metadata for registration
TOOLS_METADATA = {
    "prefix": "automation",
    "description": "Desktop automation tools for macOS and cross-platform",
    "tools": [
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
    ],
    "count": 22,
}
