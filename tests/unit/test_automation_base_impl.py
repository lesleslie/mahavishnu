"""Unit tests for mahavishnu.automation.base dataclasses and enums.

Covers the foundational data classes for desktop automation:
- WindowState, MouseButton, KeyModifier enums
- WindowInfo, ApplicationInfo, MenuInfo, UIElement, ScreenInfo, AutomationContext dataclasses
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from mahavishnu.automation.base import (
    ApplicationInfo,
    AutomationContext,
    KeyModifier,
    MenuInfo,
    MouseButton,
    ScreenInfo,
    UIElement,
    WindowInfo,
    WindowState,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_window() -> WindowInfo:
    return WindowInfo(
        id="win-1",
        title="Test Window",
        position=(10, 20),
        size=(800, 600),
    )


@pytest.fixture
def sample_app() -> ApplicationInfo:
    return ApplicationInfo(
        bundle_id="com.example.app",
        name="ExampleApp",
        pid=1234,
    )


@pytest.fixture
def sample_menu() -> MenuInfo:
    return MenuInfo(name="File")


@pytest.fixture
def sample_ui_element() -> UIElement:
    return UIElement(role="button", title="Submit")


@pytest.fixture
def sample_screen() -> ScreenInfo:
    return ScreenInfo(
        id=0,
        name="Primary",
        position=(0, 0),
        size=(1920, 1080),
    )


@pytest.fixture
def sample_context() -> AutomationContext:
    return AutomationContext()


# =============================================================================
# Enum Tests
# =============================================================================


class TestWindowState:
    @pytest.mark.unit
    def test_enum_values(self):
        assert WindowState.NORMAL == "normal"
        assert WindowState.MINIMIZED == "minimized"
        assert WindowState.MAXIMIZED == "maximized"
        assert WindowState.FULLSCREEN == "fullscreen"
        assert WindowState.HIDDEN == "hidden"

    @pytest.mark.unit
    def test_enum_membership(self):
        # All five states are present
        assert len(WindowState) == 5

    @pytest.mark.unit
    def test_is_str_enum(self):
        # StrEnum members should be usable as plain strings
        assert WindowState.NORMAL == "normal"
        assert isinstance(WindowState.NORMAL.value, str)


class TestMouseButton:
    @pytest.mark.unit
    def test_enum_values(self):
        assert MouseButton.LEFT == "left"
        assert MouseButton.RIGHT == "right"
        assert MouseButton.MIDDLE == "middle"

    @pytest.mark.unit
    def test_enum_membership(self):
        assert len(MouseButton) == 3


class TestKeyModifier:
    @pytest.mark.unit
    def test_enum_values(self):
        assert KeyModifier.CMD == "cmd"
        assert KeyModifier.COMMAND == "command"
        assert KeyModifier.SHIFT == "shift"
        assert KeyModifier.OPTION == "option"
        assert KeyModifier.ALT == "alt"
        assert KeyModifier.CONTROL == "control"
        assert KeyModifier.CTRL == "ctrl"
        assert KeyModifier.FN == "fn"

    @pytest.mark.unit
    def test_cmd_and_command_are_distinct(self):
        # Both aliases exist independently for callers' convenience
        assert KeyModifier.CMD is not KeyModifier.COMMAND


# =============================================================================
# WindowInfo Tests
# =============================================================================


class TestWindowInfo:
    @pytest.mark.unit
    def test_construction_with_required_fields(self):
        win = WindowInfo(
            id="w1",
            title="Hello",
            position=(0, 0),
            size=(640, 480),
        )
        assert win.id == "w1"
        assert win.title == "Hello"
        assert win.position == (0, 0)
        assert win.size == (640, 480)
        assert win.state == WindowState.NORMAL
        assert win.focused is False
        assert win.bundle_id is None
        assert win.window_number is None

    @pytest.mark.unit
    def test_construction_with_all_fields(self):
        win = WindowInfo(
            id="w2",
            title="Maximized",
            position=(100, 100),
            size=(1920, 1080),
            state=WindowState.MAXIMIZED,
            focused=True,
            bundle_id="com.apple.Safari",
            window_number=2,
        )
        assert win.state == WindowState.MAXIMIZED
        assert win.focused is True
        assert win.bundle_id == "com.apple.Safari"
        assert win.window_number == 2

    @pytest.mark.unit
    def test_to_dict(self, sample_window):
        result = sample_window.to_dict()
        assert result["id"] == "win-1"
        assert result["title"] == "Test Window"
        assert result["position"] == (10, 20)
        assert result["size"] == (800, 600)
        assert result["state"] == "normal"
        assert result["focused"] is False
        assert result["bundle_id"] is None
        assert result["window_number"] is None

    @pytest.mark.unit
    def test_to_dict_uses_enum_value(self):
        win = WindowInfo(
            id="w",
            title="x",
            position=(0, 0),
            size=(0, 0),
            state=WindowState.FULLSCREEN,
        )
        assert win.to_dict()["state"] == "fullscreen"


# =============================================================================
# ApplicationInfo Tests
# =============================================================================


class TestApplicationInfo:
    @pytest.mark.unit
    def test_construction_with_required_fields(self):
        app = ApplicationInfo(bundle_id="com.app", name="App", pid=42)
        assert app.bundle_id == "com.app"
        assert app.name == "App"
        assert app.pid == 42
        assert app.frontmost is False
        assert app.windows == []
        assert app.url is None
        assert app.version is None

    @pytest.mark.unit
    def test_windows_default_factory(self):
        # Two instances must not share the same list
        app1 = ApplicationInfo(bundle_id="a", name="A", pid=1)
        app2 = ApplicationInfo(bundle_id="b", name="B", pid=2)
        app1.windows.append(WindowInfo(id="x", title="t", position=(0, 0), size=(0, 0)))
        assert app2.windows == []

    @pytest.mark.unit
    def test_to_dict(self, sample_app):
        result = sample_app.to_dict()
        assert result["bundle_id"] == "com.example.app"
        assert result["name"] == "ExampleApp"
        assert result["pid"] == 1234
        assert result["frontmost"] is False
        assert result["windows"] == []
        assert result["url"] is None
        assert result["version"] is None

    @pytest.mark.unit
    def test_to_dict_with_windows(self):
        win = WindowInfo(id="1", title="t", position=(0, 0), size=(0, 0))
        app = ApplicationInfo(
            bundle_id="com.app",
            name="App",
            pid=1,
            frontmost=True,
            windows=[win],
            url="file:///Applications/App.app",
            version="1.2.3",
        )
        result = app.to_dict()
        assert result["frontmost"] is True
        assert result["windows"] == [win.to_dict()]
        assert result["url"] == "file:///Applications/App.app"
        assert result["version"] == "1.2.3"


# =============================================================================
# MenuInfo Tests
# =============================================================================


class TestMenuInfo:
    @pytest.mark.unit
    def test_construction_with_required_fields(self):
        menu = MenuInfo(name="File")
        assert menu.name == "File"
        assert menu.path == []
        assert menu.enabled is True
        assert menu.shortcut is None
        assert menu.children == []

    @pytest.mark.unit
    def test_construction_with_all_fields(self):
        child = MenuInfo(name="Save As", path=["File", "Save As"], shortcut="Cmd+Shift+S")
        menu = MenuInfo(
            name="File",
            path=["File"],
            enabled=True,
            shortcut=None,
            children=[child],
        )
        assert menu.children[0].name == "Save As"
        assert menu.children[0].shortcut == "Cmd+Shift+S"

    @pytest.mark.unit
    def test_to_dict(self):
        child = MenuInfo(name="Quit", path=["File", "Quit"], shortcut="Cmd+Q")
        menu = MenuInfo(name="File", path=["File"], children=[child])
        result = menu.to_dict()
        assert result["name"] == "File"
        assert result["path"] == ["File"]
        assert result["enabled"] is True
        assert result["shortcut"] is None
        assert len(result["children"]) == 1
        assert result["children"][0]["name"] == "Quit"

    @pytest.mark.unit
    def test_children_default_factory_isolated(self):
        # Each instance must have its own list to avoid shared state
        a = MenuInfo(name="A")
        b = MenuInfo(name="B")
        a.children.append(MenuInfo(name="x"))
        assert b.children == []


# =============================================================================
# UIElement Tests
# =============================================================================


class TestUIElement:
    @pytest.mark.unit
    def test_construction_with_role_only(self):
        elem = UIElement(role="button")
        assert elem.role == "button"
        assert elem.title is None
        assert elem.value is None
        assert elem.position is None
        assert elem.size is None
        assert elem.enabled is True
        assert elem.focused is False
        assert elem.identifier is None
        assert elem.description is None

    @pytest.mark.unit
    def test_construction_with_all_fields(self):
        elem = UIElement(
            role="textfield",
            title="Email",
            value="user@example.com",
            position=(10, 20),
            size=(200, 30),
            enabled=True,
            focused=True,
            identifier="email-input",
            description="Email input field",
        )
        assert elem.title == "Email"
        assert elem.value == "user@example.com"
        assert elem.identifier == "email-input"
        assert elem.description == "Email input field"

    @pytest.mark.unit
    def test_to_dict(self, sample_ui_element):
        result = sample_ui_element.to_dict()
        assert result["role"] == "button"
        assert result["title"] == "Submit"
        assert result["value"] is None
        assert result["enabled"] is True
        assert result["focused"] is False

    @pytest.mark.unit
    def test_to_dict_with_value(self):
        elem = UIElement(role="checkbox", title="Agree", value=True)
        result = elem.to_dict()
        assert result["value"] is True


# =============================================================================
# ScreenInfo Tests
# =============================================================================


class TestScreenInfo:
    @pytest.mark.unit
    def test_construction_with_required_fields(self):
        screen = ScreenInfo(id=1, name="Display", position=(0, 0), size=(1920, 1080))
        assert screen.id == 1
        assert screen.name == "Display"
        assert screen.position == (0, 0)
        assert screen.size == (1920, 1080)
        assert screen.scale == 1.0
        assert screen.primary is False

    @pytest.mark.unit
    def test_construction_with_all_fields(self):
        screen = ScreenInfo(
            id=2,
            name="Retina",
            position=(1920, 0),
            size=(2560, 1600),
            scale=2.0,
            primary=True,
        )
        assert screen.scale == 2.0
        assert screen.primary is True

    @pytest.mark.unit
    def test_to_dict(self, sample_screen):
        result = sample_screen.to_dict()
        assert result["id"] == 0
        assert result["name"] == "Primary"
        assert result["position"] == (0, 0)
        assert result["size"] == (1920, 1080)
        assert result["scale"] == 1.0
        assert result["primary"] is False


# =============================================================================
# AutomationContext Tests
# =============================================================================


class TestAutomationContext:
    @pytest.mark.unit
    def test_defaults(self, sample_context):
        assert sample_context.active_bundle_id is None
        assert sample_context.active_window_id is None
        assert sample_context.last_operation is None
        assert sample_context.operation_count == 0
        assert sample_context.dry_run is False
        assert sample_context.metadata == {}

    @pytest.mark.unit
    def test_metadata_default_factory(self):
        ctx1 = AutomationContext()
        ctx2 = AutomationContext()
        ctx1.metadata["a"] = 1
        assert ctx2.metadata == {}

    @pytest.mark.unit
    def test_record_operation_increments_count(self, sample_context):
        assert sample_context.operation_count == 0
        sample_context.record_operation()
        assert sample_context.operation_count == 1
        sample_context.record_operation()
        assert sample_context.operation_count == 2

    @pytest.mark.unit
    def test_record_operation_sets_timestamp(self, sample_context):
        before = datetime.now() - timedelta(seconds=1)
        sample_context.record_operation()
        assert sample_context.last_operation is not None
        assert sample_context.last_operation >= before

    @pytest.mark.unit
    @patch("mahavishnu.automation.base.datetime")
    def test_record_operation_uses_now(self, mock_dt, sample_context):
        # Fix the return value of datetime.now() for deterministic check
        fixed = datetime(2024, 1, 1, 12, 0, 0)
        mock_dt.now.return_value = fixed
        sample_context.record_operation()
        assert sample_context.last_operation == fixed
        assert sample_context.operation_count == 1
