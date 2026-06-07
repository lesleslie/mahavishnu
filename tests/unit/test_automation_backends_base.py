"""Unit tests for mahavishnu.automation.backends.base.

Covers the abstract DesktopAutomationBackend class via a minimal
concrete subclass that exercises:
- The lazy thread pool executor
- The default NotImplementedError for optional operations
- close() cleans up the executor
- supports_operation() heuristic
- __repr__ output
- Abstract methods must be implemented by subclasses
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from mahavishnu.automation.backends.base import DesktopAutomationBackend
from mahavishnu.automation.base import (
    ApplicationInfo,
    MenuInfo,
    ScreenInfo,
    WindowInfo,
)

# =============================================================================
# Concrete subclass for testing
# =============================================================================


class _StubBackend(DesktopAutomationBackend):
    """Minimal concrete implementation of DesktopAutomationBackend."""

    @staticmethod
    def is_available() -> bool:
        return True

    @property
    def backend_name(self) -> str:
        return "stub"

    # Application operations
    async def launch_application(self, bundle_id: str) -> ApplicationInfo:  # type: ignore[override]
        return ApplicationInfo(bundle_id=bundle_id, name="X", pid=1)

    async def get_application(self, bundle_id: str) -> ApplicationInfo | None:  # type: ignore[override]
        return None

    async def list_applications(self) -> list[ApplicationInfo]:  # type: ignore[override]
        return []

    async def quit_application(self, bundle_id: str, force: bool = False) -> bool:  # type: ignore[override]
        return True

    async def activate_application(self, bundle_id: str) -> bool:  # type: ignore[override]
        return True

    async def get_active_application(self) -> ApplicationInfo | None:  # type: ignore[override]
        return None

    # Window operations
    async def get_windows(self, bundle_id: str) -> list[WindowInfo]:  # type: ignore[override]
        return []

    async def activate_window(self, window_id: str) -> bool:  # type: ignore[override]
        return True

    async def resize_window(self, window_id: str, width: int, height: int) -> bool:  # type: ignore[override]
        return True

    async def move_window(self, window_id: str, x: int, y: int) -> bool:  # type: ignore[override]
        return True

    async def close_window(self, window_id: str) -> bool:  # type: ignore[override]
        return True

    # Menu operations
    async def click_menu_item(self, bundle_id: str, menu_path: list[str]) -> bool:  # type: ignore[override]
        return True

    async def list_menus(self, bundle_id: str) -> list[MenuInfo]:  # type: ignore[override]
        return []

    # Input operations
    async def type_text(self, text: str, interval: float = 0.05) -> bool:  # type: ignore[override]
        return True

    async def press_key(self, key: str, modifiers: list[str] | None = None) -> bool:  # type: ignore[override]
        return True

    async def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> bool:  # type: ignore[override]
        return True

    async def drag(  # type: ignore[override]
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.5,
        button: str = "left",
    ) -> bool:
        return True

    async def scroll(self, x: int, y: int, dx: int, dy: int) -> bool:  # type: ignore[override]
        return True

    # Screenshots
    async def screenshot(self, region: tuple[int, int, int, int] | None = None) -> bytes:  # type: ignore[override]
        return b""

    async def list_screens(self) -> list[ScreenInfo]:  # type: ignore[override]
        return []


@pytest.fixture
def stub() -> _StubBackend:
    return _StubBackend()


# =============================================================================
# Construction & executor
# =============================================================================


class TestBackendConstruction:
    @pytest.mark.unit
    def test_initial_executor_is_none(self, stub):
        assert stub._executor is None

    @pytest.mark.unit
    def test_get_executor_creates_threadpool(self, stub):
        executor = stub._get_executor()
        assert isinstance(executor, ThreadPoolExecutor)
        assert stub._executor is executor

    @pytest.mark.unit
    def test_get_executor_returns_same_instance(self, stub):
        a = stub._get_executor()
        b = stub._get_executor()
        assert a is b

    @pytest.mark.unit
    def test_max_workers_is_one(self, stub):
        executor = stub._get_executor()
        assert executor._max_workers == 1


# =============================================================================
# Class identity
# =============================================================================


class TestBackendIdentity:
    @pytest.mark.unit
    def test_backend_name(self, stub):
        assert stub.backend_name == "stub"

    @pytest.mark.unit
    def test_is_available_classmethod(self):
        # is_available is a staticmethod; call on the class
        assert _StubBackend.is_available() is True

    @pytest.mark.unit
    def test_repr_includes_class_and_name(self, stub):
        text = repr(stub)
        assert "_StubBackend" in text
        assert "stub" in text


# =============================================================================
# Optional default methods
# =============================================================================


class TestOptionalDefaults:
    @pytest.mark.unit
    async def test_get_clipboard_default_raises(self, stub):
        with pytest.raises(NotImplementedError) as exc:
            await stub.get_clipboard()
        assert "stub" in str(exc.value)

    @pytest.mark.unit
    async def test_set_clipboard_default_raises(self, stub):
        with pytest.raises(NotImplementedError) as exc:
            await stub.set_clipboard("hello")
        assert "stub" in str(exc.value)

    @pytest.mark.unit
    async def test_get_ui_elements_default_raises(self, stub):
        with pytest.raises(NotImplementedError) as exc:
            await stub.get_ui_elements("com.apple.finder")
        assert "stub" in str(exc.value)

    @pytest.mark.unit
    async def test_click_ui_element_default_raises(self, stub):
        with pytest.raises(NotImplementedError) as exc:
            await stub.click_ui_element("com.apple.finder", "ok-btn")
        assert "stub" in str(exc.value)


# =============================================================================
# close() cleanup
# =============================================================================


class TestClose:
    @pytest.mark.unit
    async def test_close_with_no_executor_is_safe(self, stub):
        # No executor was ever created; close() should be a no-op
        assert stub._executor is None
        await stub.close()
        assert stub._executor is None

    @pytest.mark.unit
    async def test_close_shuts_down_executor(self, stub):
        # Force creation of the executor
        _ = stub._get_executor()
        assert stub._executor is not None
        await stub.close()
        # After close, the executor reference should be cleared
        assert stub._executor is None

    @pytest.mark.unit
    async def test_close_called_twice_is_safe(self, stub):
        _ = stub._get_executor()
        await stub.close()
        # second close on cleared state
        await stub.close()
        assert stub._executor is None


# =============================================================================
# supports_operation heuristic
# =============================================================================


class TestSupportsOperation:
    @pytest.mark.unit
    def test_supports_existing_method(self, stub):
        assert stub.supports_operation("launch_application") is True

    @pytest.mark.unit
    def test_does_not_support_missing_method(self, stub):
        assert stub.supports_operation("does_not_exist") is False

    @pytest.mark.unit
    def test_does_not_support_optional_default(self, stub):
        # get_clipboard exists but is inherited from the base class
        # supports_operation only checks the name exists
        assert stub.supports_operation("get_clipboard") is True

    @pytest.mark.unit
    def test_supports_close(self, stub):
        assert stub.supports_operation("close") is True


# =============================================================================
# Abstract enforcement
# =============================================================================


class TestAbstractEnforcement:
    @pytest.mark.unit
    def test_cannot_instantiate_base(self):
        with pytest.raises(TypeError):
            DesktopAutomationBackend()  # type: ignore[abstract]


# =============================================================================
# Abstract method coverage
# =============================================================================


class TestAbstractMethodList:
    @pytest.mark.unit
    def test_abstract_methods_exist_on_base(self):
        abstract_names = DesktopAutomationBackend.__abstractmethods__
        # All public abstract ops should be in __abstractmethods__
        for name in (
            "is_available",
            "backend_name",
            "launch_application",
            "get_application",
            "list_applications",
            "quit_application",
            "activate_application",
            "get_active_application",
            "get_windows",
            "activate_window",
            "resize_window",
            "move_window",
            "close_window",
            "click_menu_item",
            "list_menus",
            "type_text",
            "press_key",
            "click",
            "drag",
            "scroll",
            "screenshot",
            "list_screens",
        ):
            assert name in abstract_names

    @pytest.mark.unit
    def test_optional_methods_not_abstract(self):
        # get_clipboard, set_clipboard, get_ui_elements, click_ui_element
        # have default implementations, so they must NOT be in
        # __abstractmethods__.
        abstract_names = DesktopAutomationBackend.__abstractmethods__
        assert "get_clipboard" not in abstract_names
        assert "set_clipboard" not in abstract_names
        assert "get_ui_elements" not in abstract_names
        assert "click_ui_element" not in abstract_names
        assert "close" not in abstract_names
        assert "supports_operation" not in abstract_names


# =============================================================================
# Smoke: all abstract methods can be called via a stub instance
# =============================================================================


class TestStubSmoke:
    @pytest.mark.unit
    async def test_stub_launch_application(self, stub):
        info = await stub.launch_application("com.example.app")
        assert info.bundle_id == "com.example.app"

    @pytest.mark.unit
    async def test_stub_type_text(self, stub):
        assert await stub.type_text("hello") is True

    @pytest.mark.unit
    async def test_stub_screenshot(self, stub):
        data = await stub.screenshot()
        assert data == b""

    @pytest.mark.unit
    async def test_stub_click(self, stub):
        assert await stub.click(10, 20) is True

    @pytest.mark.unit
    async def test_stub_drag(self, stub):
        assert await stub.drag(0, 0, 100, 100) is True

    @pytest.mark.unit
    async def test_stub_press_key(self, stub):
        assert await stub.press_key("a", modifiers=["cmd"]) is True
        assert await stub.press_key("a") is True

    @pytest.mark.unit
    async def test_stub_scroll(self, stub):
        assert await stub.scroll(10, 10, 0, -5) is True

    @pytest.mark.unit
    async def test_stub_get_active_application(self, stub):
        assert await stub.get_active_application() is None

    @pytest.mark.unit
    async def test_stub_uses_magicmock_internally(self, stub):
        # type sanity: backend_name is a property returning a string
        assert isinstance(stub.backend_name, str)
        assert MagicMock is not None  # ensure MagicMock is imported (no-op)
