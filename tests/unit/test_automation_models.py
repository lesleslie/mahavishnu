"""Tests for automation Pydantic models."""

from pydantic import ValidationError
import pytest

from mahavishnu.automation.base import KeyModifier, MouseButton
from mahavishnu.automation.models import (
    ApplicationOperation,
    AutomationConfig,
    AutomationOperation,
    AutomationResult,
    ClickOperation,
    DragOperation,
    KeyPressOperation,
    LaunchAppOperation,
    MenuClickOperation,
    MoveWindowOperation,
    OperationStatus,
    OperationType,
    QuitAppOperation,
    ResizeWindowOperation,
    ScreenshotOperation,
    ScreenshotRegionOperation,
    TypeTextOperation,
    WindowOperation,
)


class TestOperationType:
    def test_values(self):
        assert OperationType.LAUNCH_APP == "launch_app"
        assert OperationType.CLICK == "click"
        assert OperationType.SCREENSHOT == "screenshot"

    def test_count(self):
        assert len(OperationType) >= 16


class TestOperationStatus:
    def test_values(self):
        assert OperationStatus.SUCCESS == "success"
        assert OperationStatus.FAILED == "failed"
        assert OperationStatus.DRY_RUN == "dry_run"
        assert OperationStatus.CANCELLED == "cancelled"
        assert OperationStatus.TIMEOUT == "timeout"


class TestAutomationOperation:
    def test_defaults(self):
        op = AutomationOperation(operation_type=OperationType.CLICK)
        assert op.dry_run is False
        assert op.timeout == 30.0

    def test_timeout_validation(self):
        with pytest.raises(ValidationError):
            AutomationOperation(operation_type=OperationType.CLICK, timeout=0.0)
        with pytest.raises(ValidationError):
            AutomationOperation(operation_type=OperationType.CLICK, timeout=500.0)

    def test_extra_forbid(self):
        with pytest.raises(ValidationError):
            AutomationOperation(operation_type=OperationType.CLICK, extra_field="bad")


class TestApplicationOperation:
    def test_valid_bundle_id(self):
        op = ApplicationOperation(
            operation_type=OperationType.LAUNCH_APP, bundle_id="com.apple.finder"
        )
        assert op.bundle_id == "com.apple.finder"

    def test_wildcard_bundle_id(self):
        op = ApplicationOperation(operation_type=OperationType.LAUNCH_APP, bundle_id="*")
        assert op.bundle_id == "*"

    def test_empty_bundle_id(self):
        with pytest.raises(ValidationError):
            ApplicationOperation(operation_type=OperationType.LAUNCH_APP, bundle_id="")

    def test_no_dot_bundle_id(self):
        with pytest.raises(ValidationError, match="reverse domain"):
            ApplicationOperation(operation_type=OperationType.LAUNCH_APP, bundle_id="finder")

    def test_whitespace_stripped(self):
        op = ApplicationOperation(
            operation_type=OperationType.LAUNCH_APP, bundle_id="  com.apple.finder  "
        )
        assert op.bundle_id == "com.apple.finder"


class TestLaunchAppOperation:
    def test_defaults(self):
        op = LaunchAppOperation(bundle_id="com.apple.finder")
        assert op.operation_type == OperationType.LAUNCH_APP
        assert op.activate is True
        assert op.wait_for_launch is True
        assert op.launch_timeout == 10.0

    def test_launch_timeout_validation(self):
        with pytest.raises(ValidationError):
            LaunchAppOperation(bundle_id="com.apple.finder", launch_timeout=0.0)


class TestQuitAppOperation:
    def test_defaults(self):
        op = QuitAppOperation(bundle_id="com.apple.finder")
        assert op.operation_type == OperationType.QUIT_APP
        assert op.force is False
        assert op.save_documents is True


class TestWindowOperation:
    def test_valid(self):
        op = WindowOperation(operation_type=OperationType.ACTIVATE_WINDOW, window_id="123")
        assert op.window_id == "123"
        assert op.bundle_id is None

    def test_with_bundle_id(self):
        op = WindowOperation(
            operation_type=OperationType.ACTIVATE_WINDOW,
            window_id="123",
            bundle_id="com.apple.finder",
        )
        assert op.bundle_id == "com.apple.finder"

    def test_empty_window_id(self):
        with pytest.raises(ValidationError):
            WindowOperation(operation_type=OperationType.ACTIVATE_WINDOW, window_id="")


class TestResizeWindowOperation:
    def test_valid(self):
        op = ResizeWindowOperation(
            operation_type=OperationType.RESIZE_WINDOW,
            window_id="123",
            width=800,
            height=600,
        )
        assert op.width == 800
        assert op.height == 600

    def test_dimension_validation(self):
        with pytest.raises(ValidationError):
            ResizeWindowOperation(
                operation_type=OperationType.RESIZE_WINDOW,
                window_id="123",
                width=50,
                height=600,
            )
        with pytest.raises(ValidationError):
            ResizeWindowOperation(
                operation_type=OperationType.RESIZE_WINDOW,
                window_id="123",
                width=800,
                height=50,
            )


class TestMoveWindowOperation:
    def test_negative_coords(self):
        op = MoveWindowOperation(
            operation_type=OperationType.MOVE_WINDOW,
            window_id="123",
            x=-100,
            y=-200,
        )
        assert op.x == -100
        assert op.y == -200

    def test_coord_bounds(self):
        with pytest.raises(ValidationError):
            MoveWindowOperation(
                operation_type=OperationType.MOVE_WINDOW,
                window_id="123",
                x=10000,
                y=0,
            )


class TestMenuClickOperation:
    def test_valid(self):
        op = MenuClickOperation(
            operation_type=OperationType.CLICK_MENU,
            bundle_id="com.apple.finder",
            menu_path=["File", "New", "Folder"],
        )
        assert op.menu_path == ["File", "New", "Folder"]

    def test_empty_menu_path(self):
        with pytest.raises(ValidationError):
            MenuClickOperation(
                operation_type=OperationType.CLICK_MENU,
                bundle_id="com.apple.finder",
                menu_path=[],
            )

    def test_strips_whitespace(self):
        op = MenuClickOperation(
            operation_type=OperationType.CLICK_MENU,
            bundle_id="com.apple.finder",
            menu_path=["  File  ", " New "],
        )
        assert op.menu_path == ["File", "New"]


class TestTypeTextOperation:
    def test_valid(self):
        op = TypeTextOperation(operation_type=OperationType.TYPE_TEXT, text="hello world")
        assert op.text == "hello world"
        assert op.interval == 0.05

    def test_null_bytes_rejected(self):
        with pytest.raises(ValidationError, match="null byte"):
            TypeTextOperation(operation_type=OperationType.TYPE_TEXT, text="hello\x00world")

    def test_max_length(self):
        long_text = "a" * 10001
        with pytest.raises(ValidationError):
            TypeTextOperation(operation_type=OperationType.TYPE_TEXT, text=long_text)


class TestKeyPressOperation:
    def test_valid_keys(self):
        for key in ["return", "tab", "escape", "f1", "a", "0"]:
            op = KeyPressOperation(operation_type=OperationType.PRESS_KEY, key=key)
            assert op.key == key

    def test_single_char(self):
        op = KeyPressOperation(operation_type=OperationType.PRESS_KEY, key="Z")
        assert op.key == "z"  # Validator lowercases

    def test_invalid_key(self):
        with pytest.raises(ValidationError, match="Invalid key"):
            KeyPressOperation(operation_type=OperationType.PRESS_KEY, key="not_a_key")

    def test_modifiers(self):
        op = KeyPressOperation(
            operation_type=OperationType.PRESS_KEY,
            key="c",
            modifiers=[KeyModifier.CMD, KeyModifier.SHIFT],
        )
        assert len(op.modifiers) == 2


class TestClickOperation:
    def test_valid(self):
        op = ClickOperation(
            operation_type=OperationType.CLICK,
            x=100,
            y=200,
            button=MouseButton.RIGHT,
            clicks=2,
        )
        assert op.x == 100
        assert op.y == 200
        assert op.button == MouseButton.RIGHT
        assert op.clicks == 2

    def test_clicks_validation(self):
        with pytest.raises(ValidationError):
            ClickOperation(operation_type=OperationType.CLICK, x=0, y=0, clicks=0)
        with pytest.raises(ValidationError):
            ClickOperation(operation_type=OperationType.CLICK, x=0, y=0, clicks=5)


class TestDragOperation:
    def test_valid(self):
        op = DragOperation(
            operation_type=OperationType.DRAG,
            start_x=0,
            start_y=0,
            end_x=100,
            end_y=200,
        )
        assert op.duration == 0.5

    def test_duration_bounds(self):
        with pytest.raises(ValidationError):
            DragOperation(
                operation_type=OperationType.DRAG,
                start_x=0,
                start_y=0,
                end_x=100,
                end_y=200,
                duration=0.0,
            )


class TestScreenshotRegionOperation:
    def test_valid(self):
        op = ScreenshotRegionOperation(
            operation_type=OperationType.SCREENSHOT_REGION,
            region=(100, 100, 800, 600),
        )
        assert op.region == (100, 100, 800, 600)

    def test_zero_dimensions(self):
        with pytest.raises(ValidationError, match="must be positive"):
            ScreenshotRegionOperation(
                operation_type=OperationType.SCREENSHOT_REGION,
                region=(0, 0, 0, 100),
            )

    def test_negative_coords(self):
        with pytest.raises(ValidationError, match="non-negative"):
            ScreenshotRegionOperation(
                operation_type=OperationType.SCREENSHOT_REGION,
                region=(-1, 0, 100, 100),
            )


class TestScreenshotOperation:
    def test_format_validation(self):
        op = ScreenshotOperation(operation_type=OperationType.SCREENSHOT)
        assert op.format == "png"
        assert op.quality == 95

    def test_invalid_format(self):
        with pytest.raises(ValidationError):
            ScreenshotOperation(operation_type=OperationType.SCREENSHOT, format="bmp")


class TestAutomationResult:
    def test_success_factory(self):
        result = AutomationResult.success(OperationType.CLICK, data={"x": 100})
        assert result.status == OperationStatus.SUCCESS
        assert result.error is None

    def test_success_dry_run(self):
        result = AutomationResult.success(OperationType.CLICK, dry_run=True)
        assert result.status == OperationStatus.DRY_RUN

    def test_failure_factory(self):
        result = AutomationResult.failure(
            OperationType.CLICK,
            error="Window not found",
            error_code="WINDOW_404",
        )
        assert result.status == OperationStatus.FAILED
        assert result.error == "Window not found"

    def test_timestamp(self):
        result = AutomationResult.success(OperationType.CLICK)
        assert result.timestamp is not None


class TestAutomationConfig:
    def test_defaults(self):
        config = AutomationConfig()
        assert config.enabled is True
        assert config.default_backend == "auto"
        assert config.dry_run_default is False
        assert config.max_operations_per_second == 10

    def test_blocked_apps(self):
        config = AutomationConfig()
        assert "com.apple.securityd" in config.blocked_apps
        assert "com.agilebits.onepassword" in config.blocked_apps

    def test_blocked_text_patterns(self):
        config = AutomationConfig()
        assert "password" in config.blocked_text_patterns
        assert "api_key" in config.blocked_text_patterns

    def test_extra_forbid(self):
        with pytest.raises(ValidationError):
            AutomationConfig(extra_field="bad")

    def test_max_ops_validation(self):
        with pytest.raises(ValidationError):
            AutomationConfig(max_operations_per_second=0)
        with pytest.raises(ValidationError):
            AutomationConfig(max_operations_per_second=200)
