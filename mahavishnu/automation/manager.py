"""Automation Manager for desktop automation.

Provides a unified interface for desktop automation with:
- Automatic backend selection
- Security validation
- Permission checking
- Dry run support
- Rate limiting

Usage:
    from mahavishnu.automation import AutomationManager

    manager = AutomationManager()
    await manager.initialize()

    # Launch and control applications
    app = await manager.launch_application("com.apple.finder")
    windows = await manager.get_windows("com.apple.finder")
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from logging import getLogger
import time
from typing import Any, TypeVar

from mahavishnu.automation.backends.atomac import ATOMacBackend
from mahavishnu.automation.backends.base import DesktopAutomationBackend
from mahavishnu.automation.backends.pyautogui import PyAutoGUIBackend
from mahavishnu.automation.backends.pyxa import PyXABackend
from mahavishnu.automation.capabilities import Capability, CapabilityDetector
from mahavishnu.automation.errors import (
    NoBackendAvailableError,
    PermissionDeniedError,
)
from mahavishnu.automation.models import (
    AutomationConfig,
    AutomationResult,
    OperationType,
)
from mahavishnu.automation.permissions import PermissionChecker
from mahavishnu.automation.security import AutomationSecurity, get_security

logger = getLogger(__name__)

T = TypeVar("T")


@dataclass
class ManagerStats:
    """Statistics for the automation manager."""

    operations_total: int = 0
    operations_success: int = 0
    operations_failed: int = 0
    operations_dry_run: int = 0
    last_operation: datetime | None = None
    backend_name: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "operations_total": self.operations_total,
            "operations_success": self.operations_success,
            "operations_failed": self.operations_failed,
            "operations_dry_run": self.operations_dry_run,
            "last_operation": self.last_operation.isoformat() if self.last_operation else None,
            "backend_name": self.backend_name,
        }


class AutomationManager:
    """Unified automation manager with automatic backend selection.

    This class provides the main interface for desktop automation,
    automatically selecting the best available backend and enforcing
    security policies.

    Features:
    - Automatic backend selection (PyXA > ATOMac > PyAutoGUI)
    - Security validation (blocklist, text patterns, rate limiting)
    - Permission checking (accessibility, screen recording)
    - Dry run mode for testing
    - Operation statistics

    Example:
        ```python
        from mahavishnu.automation import AutomationManager

        manager = AutomationManager()
        await manager.initialize()

        # Launch Finder
        app = await manager.launch_application("com.apple.finder")
        print(f"Launched: {app.name}")

        # List windows
        windows = await manager.get_windows("com.apple.finder")
        for win in windows:
            print(f"Window: {win.title}")

        # Type text
        await manager.type_text("Hello World")

        # Take screenshot
        screenshot = await manager.screenshot()

        await manager.close()
        ```
    """

    def __init__(
        self,
        config: AutomationConfig | None = None,
        preferred_backend: str = "auto",
    ) -> None:
        """Initialize the automation manager.

        Args:
            config: Automation configuration. If None, uses defaults.
            preferred_backend: Preferred backend name ("auto", "pyxa", "atomac", "pyautogui").
        """
        self.config = config or AutomationConfig()
        self.preferred_backend = preferred_backend

        self._backend: DesktopAutomationBackend | None = None
        self._security: AutomationSecurity | None = None
        self._permission_checker: PermissionChecker | None = None
        self._capability_detector: CapabilityDetector | None = None

        self._initialized = False
        self._stats = ManagerStats()

    async def initialize(self) -> None:
        """Initialize the automation manager.

        This method:
        1. Checks permissions
        2. Detects available backends
        3. Selects the best backend
        4. Initializes security

        Raises:
            NoBackendAvailableError: If no backend is available.
            PermissionDeniedError: If accessibility permissions are not granted.
        """
        if self._initialized:
            return

        logger.info("Initializing automation manager...")

        # Check permissions if required
        if self.config.require_accessibility_check:
            self._permission_checker = PermissionChecker()
            if not self._permission_checker.check_accessibility():
                logger.warning("Accessibility permissions not granted")
                if not self._permission_checker.request_accessibility():
                    raise PermissionDeniedError("Accessibility permissions required for automation")

        # Initialize security
        self._security = get_security(self.config)

        # Detect and select backend
        self._capability_detector = CapabilityDetector()
        self._select_backend()

        if self._backend is None:
            raise NoBackendAvailableError()

        self._stats.backend_name = self._backend.backend_name
        self._initialized = True

        logger.info(f"Automation manager initialized with backend: {self._backend.backend_name}")

    def _select_backend(self) -> None:
        """Select the best available backend."""
        backends_to_try = []

        if self.preferred_backend == "auto":
            # Try in order of preference
            backends_to_try = [
                ("pyxa", PyXABackend),
                ("atomac", ATOMacBackend),
                ("pyautogui", PyAutoGUIBackend),
            ]
        else:
            # Use specified backend
            backend_map = {
                "pyxa": PyXABackend,
                "atomac": ATOMacBackend,
                "pyautogui": PyAutoGUIBackend,
            }
            if self.preferred_backend in backend_map:
                backends_to_try = [(self.preferred_backend, backend_map[self.preferred_backend])]
            else:
                logger.warning(f"Unknown backend '{self.preferred_backend}', using auto")
                backends_to_try = [
                    ("pyxa", PyXABackend),
                    ("atomac", ATOMacBackend),
                    ("pyautogui", PyAutoGUIBackend),
                ]

        for name, backend_cls in backends_to_try:
            if backend_cls.is_available():
                try:
                    self._backend = backend_cls()
                    logger.info(f"Selected backend: {name}")
                    return
                except Exception as e:
                    logger.warning(f"Failed to initialize {name} backend: {e}")
                    continue

        logger.error("No automation backend available")

    def _record_operation(self, success: bool, dry_run: bool = False) -> None:
        """Record operation statistics."""
        self._stats.operations_total += 1
        self._stats.last_operation = datetime.now()

        if dry_run:
            self._stats.operations_dry_run += 1
        elif success:
            self._stats.operations_success += 1
        else:
            self._stats.operations_failed += 1

    async def _execute(
        self,
        operation_type: OperationType,
        operation: callable,
        *args,
        **kwargs,
    ) -> AutomationResult:
        """Execute an operation with security checks and statistics."""
        start_time = time.time()

        if not self._initialized:
            await self.initialize()

        if self._backend is None:
            return AutomationResult.failure(
                operation_type=operation_type,
                error="No backend available",
                error_code="NO_BACKEND",
            )

        # Check dry run - handle None explicitly to use config default
        dry_run_arg = kwargs.pop("dry_run", None)
        dry_run = dry_run_arg if dry_run_arg is not None else self.config.dry_run_default

        if dry_run:
            self._record_operation(True, dry_run=True)
            return AutomationResult.success(
                operation_type=operation_type,
                data={"dry_run": True, "operation": operation_type.value},
                dry_run=True,
            )

        # Execute operation
        try:
            result = await operation(*args, **kwargs)
            duration_ms = (time.time() - start_time) * 1000
            self._record_operation(True)

            return AutomationResult.success(
                operation_type=operation_type,
                data=result if isinstance(result, dict) else {"result": result},
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self._record_operation(False)
            logger.error(f"Operation {operation_type} failed: {e}")

            return AutomationResult.failure(
                operation_type=operation_type,
                error=str(e),
                error_code=type(e).__name__,
                duration_ms=duration_ms,
            )

    # =========================================================================
    # Application Operations
    # =========================================================================

    async def launch_application(
        self,
        bundle_id: str,
        dry_run: bool | None = None,
    ) -> AutomationResult:
        """Launch an application by bundle identifier.

        Args:
            bundle_id: Application bundle identifier.
            dry_run: Override dry run setting.

        Returns:
            AutomationResult with ApplicationInfo.
        """
        # Security check
        if self._security:
            self._security.validate_app(bundle_id)

        return await self._execute(
            OperationType.LAUNCH_APP,
            self._backend.launch_application,
            bundle_id,
            dry_run=dry_run,
        )

    async def get_application(self, bundle_id: str) -> AutomationResult:
        """Get information about a running application."""
        return await self._execute(
            OperationType.GET_ACTIVE_APP,
            self._backend.get_application,
            bundle_id,
        )

    async def list_applications(self) -> AutomationResult:
        """List all running applications."""
        return await self._execute(
            OperationType.LIST_APPS,
            self._backend.list_applications,
        )

    async def quit_application(
        self,
        bundle_id: str,
        force: bool = False,
        dry_run: bool | None = None,
    ) -> AutomationResult:
        """Quit an application.

        Args:
            bundle_id: Application bundle identifier.
            force: Force quit if normal quit fails.
            dry_run: Override dry run setting.
        """
        # Security check
        if self._security:
            self._security.validate_app(bundle_id)

        return await self._execute(
            OperationType.QUIT_APP,
            self._backend.quit_application,
            bundle_id,
            force=force,
            dry_run=dry_run,
        )

    async def activate_application(self, bundle_id: str) -> AutomationResult:
        """Activate (bring to front) an application."""
        if self._security:
            self._security.validate_app(bundle_id)

        return await self._execute(
            OperationType.ACTIVATE_APP,
            self._backend.activate_application,
            bundle_id,
        )

    async def get_active_application(self) -> AutomationResult:
        """Get the currently active application."""
        return await self._execute(
            OperationType.GET_ACTIVE_APP,
            self._backend.get_active_application,
        )

    # =========================================================================
    # Window Operations
    # =========================================================================

    async def get_windows(self, bundle_id: str) -> AutomationResult:
        """Get all windows for an application."""
        return await self._execute(
            OperationType.LIST_WINDOWS,
            self._backend.get_windows,
            bundle_id,
        )

    async def activate_window(self, window_id: str) -> AutomationResult:
        """Activate (bring to front) a window."""
        return await self._execute(
            OperationType.ACTIVATE_WINDOW,
            self._backend.activate_window,
            window_id,
        )

    async def resize_window(
        self,
        window_id: str,
        width: int,
        height: int,
    ) -> AutomationResult:
        """Resize a window."""
        return await self._execute(
            OperationType.RESIZE_WINDOW,
            self._backend.resize_window,
            window_id,
            width,
            height,
        )

    async def move_window(
        self,
        window_id: str,
        x: int,
        y: int,
    ) -> AutomationResult:
        """Move a window to a new position."""
        return await self._execute(
            OperationType.MOVE_WINDOW,
            self._backend.move_window,
            window_id,
            x,
            y,
        )

    async def close_window(self, window_id: str) -> AutomationResult:
        """Close a window."""
        return await self._execute(
            OperationType.CLOSE_WINDOW,
            self._backend.close_window,
            window_id,
        )

    # =========================================================================
    # Menu Operations
    # =========================================================================

    async def click_menu_item(
        self,
        bundle_id: str,
        menu_path: list[str],
    ) -> AutomationResult:
        """Navigate menu and click an item.

        Args:
            bundle_id: Application bundle identifier.
            menu_path: Path to menu item (e.g., ["File", "Save"]).
        """
        if self._security:
            self._security.validate_app(bundle_id)

        return await self._execute(
            OperationType.CLICK_MENU,
            self._backend.click_menu_item,
            bundle_id,
            menu_path,
        )

    async def list_menus(self, bundle_id: str) -> AutomationResult:
        """List all menus for an application."""
        return await self._execute(
            OperationType.LIST_MENUS,
            self._backend.list_menus,
            bundle_id,
        )

    # =========================================================================
    # Input Operations
    # =========================================================================

    async def type_text(
        self,
        text: str,
        interval: float = 0.05,
        dry_run: bool | None = None,
    ) -> AutomationResult:
        """Type text at the current cursor position.

        Args:
            text: Text to type.
            interval: Delay between keystrokes.
            dry_run: Override dry run setting.
        """
        # Security check for text
        if self._security:
            self._security.validate_text(text)

        return await self._execute(
            OperationType.TYPE_TEXT,
            self._backend.type_text,
            text,
            interval=interval,
            dry_run=dry_run,
        )

    async def press_key(
        self,
        key: str,
        modifiers: list[str] | None = None,
    ) -> AutomationResult:
        """Press a key with optional modifiers.

        Args:
            key: Key to press (e.g., "return", "a", "f1").
            modifiers: List of modifiers (e.g., ["cmd", "shift"]).
        """
        return await self._execute(
            OperationType.PRESS_KEY,
            self._backend.press_key,
            key,
            modifiers=modifiers,
        )

    async def click(
        self,
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
    ) -> AutomationResult:
        """Click at coordinates.

        Args:
            x: X coordinate.
            y: Y coordinate.
            button: Mouse button ("left", "right", "middle").
            clicks: Number of clicks.
        """
        return await self._execute(
            OperationType.CLICK,
            self._backend.click,
            x,
            y,
            button=button,
            clicks=clicks,
        )

    async def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.5,
        button: str = "left",
    ) -> AutomationResult:
        """Drag from one point to another."""
        return await self._execute(
            OperationType.DRAG,
            self._backend.drag,
            start_x,
            start_y,
            end_x,
            end_y,
            duration=duration,
            button=button,
        )

    async def scroll(
        self,
        x: int,
        y: int,
        dx: int,
        dy: int,
    ) -> AutomationResult:
        """Scroll at coordinates."""
        return await self._execute(
            OperationType.SCROLL,
            self._backend.scroll,
            x,
            y,
            dx,
            dy,
        )

    # =========================================================================
    # Screenshot Operations
    # =========================================================================

    async def screenshot(
        self,
        region: tuple[int, int, int, int] | None = None,
    ) -> AutomationResult:
        """Capture a screenshot.

        Args:
            region: Optional region as (x, y, width, height).
        """
        return await self._execute(
            OperationType.SCREENSHOT,
            self._backend.screenshot,
            region=region,
        )

    # =========================================================================
    # Screen Operations
    # =========================================================================

    async def list_screens(self) -> AutomationResult:
        """List all connected displays."""
        return await self._execute(
            OperationType.LIST_WINDOWS,
            self._backend.list_screens,
        )

    # =========================================================================
    # UI Element Operations
    # =========================================================================

    async def get_ui_elements(
        self,
        bundle_id: str,
        window_id: str | None = None,
    ) -> AutomationResult:
        """Get UI elements for an application."""
        return await self._execute(
            OperationType.LIST_WINDOWS,
            self._backend.get_ui_elements,
            bundle_id,
            window_id=window_id,
        )

    # =========================================================================
    # Utility Methods
    # =========================================================================

    async def check_permissions(self) -> AutomationResult:
        """Check automation permissions."""
        if self._permission_checker is None:
            self._permission_checker = PermissionChecker()

        permissions = self._permission_checker.get_all_permissions()
        return AutomationResult.success(
            operation_type=OperationType.CHECK_PERMISSIONS,
            data={
                "permissions": [p.to_dict() for p in permissions],
                "all_granted": self._permission_checker.check_accessibility(),
                "can_screenshot": self._permission_checker.check_screen_recording(),
            },
        )

    def get_stats(self) -> dict[str, Any]:
        """Get manager statistics."""
        return self._stats.to_dict()

    def get_backend_name(self) -> str | None:
        """Get the name of the current backend."""
        return self._backend.backend_name if self._backend else None

    def get_capabilities(self) -> set[Capability]:
        """Get the capabilities of the current backend."""
        if self._capability_detector is None:
            return set()

        status = self._capability_detector.get_backend_status(
            self._backend.backend_name if self._backend else ""
        )
        if status.capabilities:
            return status.capabilities.capabilities
        return set()

    async def close(self) -> None:
        """Clean up manager resources."""
        if self._backend:
            await self._backend.close()
            self._backend = None

        self._initialized = False
        logger.info("Automation manager closed")

    async def __aenter__(self) -> AutomationManager:
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()
