"""Unit tests for additional pydantic models in mahavishnu.automation.models.

Complements the existing tests/unit/test_automation_models.py by covering
operation subclasses and edge cases that file does not exercise.
"""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from mahavishnu.automation.models import (
    ActivateAppOperation,
    ActivateWindowOperation,
    AutomationConfig,
    AutomationResult,
    CheckPermissionsOperation,
    ClickOperation,
    CloseWindowOperation,
    DragOperation,
    GetActiveAppOperation,
    KeyPressOperation,
    LaunchAppOperation,
    ListAppsOperation,
    ListMenusOperation,
    ListWindowsOperation,
    MoveWindowOperation,
    OperationStatus,
    OperationType,
    QuitAppOperation,
    ResizeWindowOperation,
    ScreenshotOperation,
    ScreenshotRegionOperation,
    ScrollOperation,
    TypeTextOperation,
)

# =============================================================================
# ActivateAppOperation Tests
# =============================================================================


class TestActivateAppOperation:
    @pytest.mark.unit
    def test_defaults(self):
        op = ActivateAppOperation(bundle_id="com.apple.finder")
        assert op.operation_type == OperationType.ACTIVATE_APP
        assert op.bundle_id == "com.apple.finder"
        assert op.dry_run is False
        assert op.timeout == 30.0

    @pytest.mark.unit
    def test_inherits_bundle_id_validation(self):
        with pytest.raises(ValidationError):
            ActivateAppOperation(bundle_id="")


# =============================================================================
# ListAppsOperation Tests
# =============================================================================


class TestListAppsOperation:
    @pytest.mark.unit
    def test_defaults(self):
        op = ListAppsOperation()
        assert op.operation_type == OperationType.LIST_APPS
        assert op.include_windows is False

    @pytest.mark.unit
    def test_include_windows_true(self):
        op = ListAppsOperation(include_windows=True)
        assert op.include_windows is True


# =============================================================================
# Window Operations Tests
# =============================================================================


class TestListWindowsOperation:
    @pytest.mark.unit
    def test_operation_type_locked(self):
        op = ListWindowsOperation(bundle_id="com.apple.finder")
        assert op.operation_type == OperationType.LIST_WINDOWS


class TestActivateWindowOperation:
    @pytest.mark.unit
    def test_construction(self):
        op = ActivateWindowOperation(
            window_id="42",
            bundle_id="com.apple.finder",
        )
        assert op.operation_type == OperationType.ACTIVATE_WINDOW
        assert op.window_id == "42"
        assert op.bundle_id == "com.apple.finder"


class TestCloseWindowOperation:
    @pytest.mark.unit
    def test_construction(self):
        op = CloseWindowOperation(window_id="42")
        assert op.operation_type == OperationType.CLOSE_WINDOW
        assert op.window_id == "42"
        assert op.bundle_id is None


class TestResizeWindowOperationBounds:
    @pytest.mark.unit
    def test_width_at_lower_bound(self):
        op = ResizeWindowOperation(window_id="1", width=100, height=600)
        assert op.width == 100
        assert op.height == 600

    @pytest.mark.unit
    def test_width_at_upper_bound(self):
        op = ResizeWindowOperation(window_id="1", width=8192, height=600)
        assert op.width == 8192

    @pytest.mark.unit
    def test_height_at_upper_bound(self):
        op = ResizeWindowOperation(window_id="1", width=200, height=8192)
        assert op.height == 8192

    @pytest.mark.unit
    def test_width_below_lower_bound(self):
        with pytest.raises(ValidationError):
            ResizeWindowOperation(window_id="1", width=99, height=600)

    @pytest.mark.unit
    def test_height_below_lower_bound(self):
        with pytest.raises(ValidationError):
            ResizeWindowOperation(window_id="1", width=200, height=50)


class TestMoveWindowOperationBounds:
    @pytest.mark.unit
    def test_negative_origin(self):
        op = MoveWindowOperation(window_id="1", x=-8192, y=-8192)
        assert op.x == -8192
        assert op.y == -8192

    @pytest.mark.unit
    def test_positive_max(self):
        op = MoveWindowOperation(window_id="1", x=8192, y=8192)
        assert op.x == 8192
        assert op.y == 8192

    @pytest.mark.unit
    def test_x_out_of_bounds(self):
        with pytest.raises(ValidationError):
            MoveWindowOperation(window_id="1", x=10000, y=0)

    @pytest.mark.unit
    def test_y_out_of_bounds(self):
        with pytest.raises(ValidationError):
            MoveWindowOperation(window_id="1", x=0, y=10000)


# =============================================================================
# Menu / Application Operations Tests
# =============================================================================


class TestListMenusOperation:
    @pytest.mark.unit
    def test_construction(self):
        op = ListMenusOperation(bundle_id="com.apple.finder")
        assert op.operation_type == OperationType.LIST_MENUS
        assert op.bundle_id == "com.apple.finder"


# =============================================================================
# Input Operations Extended Tests
# =============================================================================


class TestClickOperationBounds:
    @pytest.mark.unit
    def test_zero_coordinate_allowed(self):
        op = ClickOperation(x=0, y=0)
        assert op.x == 0
        assert op.y == 0

    @pytest.mark.unit
    def test_x_at_max(self):
        op = ClickOperation(x=16384, y=0)
        assert op.x == 16384

    @pytest.mark.unit
    def test_y_at_max(self):
        op = ClickOperation(x=0, y=16384)
        assert op.y == 16384

    @pytest.mark.unit
    def test_negative_x_rejected(self):
        with pytest.raises(ValidationError):
            ClickOperation(x=-1, y=0)

    @pytest.mark.unit
    def test_negative_y_rejected(self):
        with pytest.raises(ValidationError):
            ClickOperation(x=0, y=-1)

    @pytest.mark.unit
    def test_clicks_lower_bound(self):
        with pytest.raises(ValidationError):
            ClickOperation(x=0, y=0, clicks=0)

    @pytest.mark.unit
    def test_clicks_upper_bound(self):
        with pytest.raises(ValidationError):
            ClickOperation(x=0, y=0, clicks=4)

    @pytest.mark.unit
    def test_clicks_three_allowed(self):
        op = ClickOperation(x=0, y=0, clicks=3)
        assert op.clicks == 3


class TestDragOperationBounds:
    @pytest.mark.unit
    def test_all_coordinates_zero(self):
        op = DragOperation(start_x=0, start_y=0, end_x=0, end_y=0)
        assert op.start_x == 0
        assert op.end_y == 0

    @pytest.mark.unit
    def test_duration_upper_bound(self):
        op = DragOperation(start_x=0, start_y=0, end_x=1, end_y=1, duration=10.0)
        assert op.duration == 10.0

    @pytest.mark.unit
    def test_duration_below_lower_bound(self):
        with pytest.raises(ValidationError):
            DragOperation(start_x=0, start_y=0, end_x=1, end_y=1, duration=0.05)


class TestScrollOperation:
    @pytest.mark.unit
    def test_defaults(self):
        op = ScrollOperation(x=100, y=100)
        assert op.operation_type == OperationType.SCROLL
        assert op.dx == 0
        assert op.dy == 0

    @pytest.mark.unit
    def test_scroll_deltas(self):
        op = ScrollOperation(x=200, y=300, dx=10, dy=-20)
        assert op.dx == 10
        assert op.dy == -20

    @pytest.mark.unit
    def test_dx_out_of_bounds(self):
        with pytest.raises(ValidationError):
            ScrollOperation(x=0, y=0, dx=200)

    @pytest.mark.unit
    def test_dy_out_of_bounds(self):
        with pytest.raises(ValidationError):
            ScrollOperation(x=0, y=0, dy=-200)


# =============================================================================
# TypeTextOperation Extended Tests
# =============================================================================


class TestTypeTextOperationExtended:
    @pytest.mark.unit
    def test_interval_zero(self):
        op = TypeTextOperation(text="hello", interval=0.0)
        assert op.interval == 0.0

    @pytest.mark.unit
    def test_interval_max(self):
        op = TypeTextOperation(text="hello", interval=1.0)
        assert op.interval == 1.0

    @pytest.mark.unit
    def test_interval_out_of_bounds(self):
        with pytest.raises(ValidationError):
            TypeTextOperation(text="hello", interval=2.0)

    @pytest.mark.unit
    def test_exactly_max_length(self):
        op = TypeTextOperation(text="a" * 10000)
        assert len(op.text) == 10000


# =============================================================================
# KeyPressOperation Extended Tests
# =============================================================================


class TestKeyPressOperationExtended:
    @pytest.mark.unit
    @pytest.mark.parametrize(
        "key",
        [
            "return",
            "tab",
            "space",
            "escape",
            "esc",
            "up",
            "down",
            "left",
            "right",
            "home",
            "end",
            "pageup",
            "pagedown",
            "f1",
            "f12",
            "-",
            "=",
            "[",
            "]",
            "\\",
            ";",
            "'",
            ",",
            ".",
            "/",
        ],
    )
    def test_named_and_symbol_keys_normalized_to_lowercase(self, key: str):
        op = KeyPressOperation(key=key)
        assert op.key == key.lower()

    @pytest.mark.unit
    def test_key_too_long(self):
        with pytest.raises(ValidationError):
            KeyPressOperation(key="a" * 51)

    @pytest.mark.unit
    def test_uppercase_letter_normalized(self):
        op = KeyPressOperation(key="Q")
        assert op.key == "q"


# =============================================================================
# Launch / Quit Operations Extended
# =============================================================================


class TestLaunchAppOperationExtended:
    @pytest.mark.unit
    def test_launch_timeout_upper_bound(self):
        op = LaunchAppOperation(bundle_id="com.apple.finder", launch_timeout=60.0)
        assert op.launch_timeout == 60.0

    @pytest.mark.unit
    def test_launch_timeout_above_max(self):
        with pytest.raises(ValidationError):
            LaunchAppOperation(bundle_id="com.apple.finder", launch_timeout=61.0)

    @pytest.mark.unit
    def test_deactivate(self):
        op = LaunchAppOperation(bundle_id="com.apple.finder", activate=False)
        assert op.activate is False

    @pytest.mark.unit
    def test_dont_wait(self):
        op = LaunchAppOperation(bundle_id="com.apple.finder", wait_for_launch=False)
        assert op.wait_for_launch is False


class TestQuitAppOperationExtended:
    @pytest.mark.unit
    def test_force_true(self):
        op = QuitAppOperation(bundle_id="com.apple.finder", force=True)
        assert op.force is True

    @pytest.mark.unit
    def test_no_save(self):
        op = QuitAppOperation(bundle_id="com.apple.finder", save_documents=False)
        assert op.save_documents is False


# =============================================================================
# ScreenshotOperation Extended Tests
# =============================================================================


class TestScreenshotOperationExtended:
    @pytest.mark.unit
    @pytest.mark.parametrize("fmt", ["png", "jpeg", "webp"])
    def test_all_supported_formats(self, fmt: str):
        op = ScreenshotOperation(format=fmt)
        assert op.format == fmt

    @pytest.mark.unit
    def test_unsupported_format(self):
        with pytest.raises(ValidationError):
            ScreenshotOperation(format="gif")

    @pytest.mark.unit
    def test_quality_bounds(self):
        op_min = ScreenshotOperation(quality=1)
        op_max = ScreenshotOperation(quality=100)
        assert op_min.quality == 1
        assert op_max.quality == 100

    @pytest.mark.unit
    def test_quality_below_min(self):
        with pytest.raises(ValidationError):
            ScreenshotOperation(quality=0)

    @pytest.mark.unit
    def test_quality_above_max(self):
        with pytest.raises(ValidationError):
            ScreenshotOperation(quality=101)

    @pytest.mark.unit
    def test_screen_id_none(self):
        op = ScreenshotOperation(screen_id=None)
        assert op.screen_id is None

    @pytest.mark.unit
    def test_screen_id_value(self):
        op = ScreenshotOperation(screen_id=2)
        assert op.screen_id == 2


class TestScreenshotRegionOperationExtended:
    @pytest.mark.unit
    def test_positive_dimensions(self):
        op = ScreenshotRegionOperation(region=(10, 20, 800, 600))
        assert op.region == (10, 20, 800, 600)

    @pytest.mark.unit
    def test_zero_height(self):
        with pytest.raises(ValidationError, match="must be positive"):
            ScreenshotRegionOperation(region=(0, 0, 100, 0))

    @pytest.mark.unit
    def test_zero_width(self):
        with pytest.raises(ValidationError, match="must be positive"):
            ScreenshotRegionOperation(region=(0, 0, 0, 100))


# =============================================================================
# Get / Check Operations Tests
# =============================================================================


class TestGetActiveAppOperation:
    @pytest.mark.unit
    def test_construction(self):
        op = GetActiveAppOperation()
        assert op.operation_type == OperationType.GET_ACTIVE_APP
        assert op.dry_run is False


class TestCheckPermissionsOperation:
    @pytest.mark.unit
    def test_construction(self):
        op = CheckPermissionsOperation()
        assert op.operation_type == OperationType.CHECK_PERMISSIONS


# =============================================================================
# AutomationResult Tests
# =============================================================================


class TestAutomationResultExtended:
    @pytest.mark.unit
    def test_success_with_data(self):
        result = AutomationResult.success(
            OperationType.LAUNCH_APP,
            data={"pid": 1234, "name": "Finder"},
            duration_ms=12.5,
        )
        assert result.status == OperationStatus.SUCCESS
        assert result.data == {"pid": 1234, "name": "Finder"}
        assert result.duration_ms == 12.5
        assert result.error is None
        assert result.error_code is None

    @pytest.mark.unit
    def test_success_no_data(self):
        result = AutomationResult.success(OperationType.CLICK)
        assert result.data is None
        assert result.duration_ms is None

    @pytest.mark.unit
    def test_failure_with_data(self):
        result = AutomationResult.failure(
            OperationType.LAUNCH_APP,
            error="boom",
            error_code="E_BOOM",
            data={"attempted": "com.bad.app"},
        )
        assert result.status == OperationStatus.FAILED
        assert result.error == "boom"
        assert result.error_code == "E_BOOM"
        assert result.data == {"attempted": "com.bad.app"}

    @pytest.mark.unit
    def test_direct_construction(self):
        result = AutomationResult(
            operation_type=OperationType.PRESS_KEY,
            status=OperationStatus.TIMEOUT,
            error="timed out",
        )
        assert result.status == "timeout"
        assert result.error == "timed out"


# =============================================================================
# AutomationConfig Extended Tests
# =============================================================================


class TestAutomationConfigExtended:
    @pytest.mark.unit
    def test_default_timeout_bounds(self):
        # in-range
        config = AutomationConfig(default_timeout=100.0)
        assert config.default_timeout == 100.0
        # below minimum
        with pytest.raises(ValidationError):
            AutomationConfig(default_timeout=0.5)
        # above maximum
        with pytest.raises(ValidationError):
            AutomationConfig(default_timeout=400.0)

    @pytest.mark.unit
    def test_allowed_apps_when_set(self):
        config = AutomationConfig(allowed_apps={"com.app.allowed"})
        assert config.allowed_apps == {"com.app.allowed"}

    @pytest.mark.unit
    def test_require_confirmation_for_set(self):
        config = AutomationConfig(require_confirmation_for={"quit_app", "force_quit"})
        assert "quit_app" in config.require_confirmation_for
        assert "force_quit" in config.require_confirmation_for

    @pytest.mark.unit
    def test_blocked_apps_contains_security(self):
        config = AutomationConfig()
        # security daemon and a password manager must be blocked
        assert "com.apple.securityd" in config.blocked_apps
        assert "com.apple.KeychainAccess" in config.blocked_apps
        assert "com.agilebits.onepassword" in config.blocked_apps

    @pytest.mark.unit
    def test_blocked_text_patterns_contains_secrets(self):
        config = AutomationConfig()
        for pattern in ("password", "api_key", "secret", "token"):
            assert pattern in config.blocked_text_patterns

    @pytest.mark.unit
    def test_extra_forbid(self):
        with pytest.raises(ValidationError):
            AutomationConfig(unknown_field="x")
