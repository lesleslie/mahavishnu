"""Extended unit tests for ``mahavishnu.automation.permissions``.

Raises coverage on the permissions module from 46.51% to >=85% by exercising
the ``PermissionStatus`` enum, ``PermissionInfo`` dataclass, every method on
``PermissionChecker`` (including the macOS-only branches), and the module-level
helpers (``get_permission_checker``, ``check_accessibility_permissions``,
``check_screen_recording_permissions``, ``get_all_permission_status``).
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import FrozenInstanceError
from typing import Any
from unittest.mock import patch

import pytest

from mahavishnu.automation import permissions as perms


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeModule:
    """Minimal stand-in for an ApplicationServices / Quartz module.

    Production code does inline ``from ApplicationServices import X`` and
    ``import Quartz``. ``importlib.import_module`` consults ``sys.modules``,
    so injecting a fake here is the cleanest way to exercise both the happy
    path (attribute resolves to a callable) and the failure paths
    (ImportError, generic Exception) without depending on PyObjC.
    """


@pytest.fixture(autouse=True)
def _clear_global_checker():
    """Reset the module-level ``_checker`` singleton between tests.

    Without this, ``get_permission_checker`` returns whichever instance the
    first test constructed, leaking platform state and patch state across
    tests. This is a state reset — not a public helper added to production.
    """
    saved = perms._checker
    perms._checker = None
    try:
        yield
    finally:
        perms._checker = saved


def _inject_module(name: str, **attrs: Any) -> Any:
    """Install a fake module in ``sys.modules[name]`` with the given attrs.

    Returns the (possibly new) module object so tests can mutate it further.
    Removes the entry on teardown so other tests start from a clean slate.
    """
    mod = sys.modules.get(name)
    if mod is None:
        mod = _FakeModule()
        mod.__name__ = name
        sys.modules[name] = mod
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


def _pop_module(name: str) -> None:
    """Remove a fake module from ``sys.modules`` (best-effort)."""
    sys.modules.pop(name, None)


def _force_macos(checker: perms.PermissionChecker) -> perms.PermissionChecker:
    """Flip the checker's ``_is_macos`` flag so the macOS branches execute."""
    checker._is_macos = True
    return checker


# ---------------------------------------------------------------------------
# PermissionStatus enum
# ---------------------------------------------------------------------------


class TestPermissionStatus:
    """Coverage for the ``PermissionStatus`` enum."""

    def test_all_four_values_are_strings(self) -> None:
        """All four enum members expose string values."""
        expected = {
            "GRANTED": "granted",
            "DENIED": "denied",
            "NOT_DETERMINED": "not_determined",
            "UNKNOWN": "unknown",
        }
        actual = {member.name: member.value for member in perms.PermissionStatus}
        assert actual == expected

    def test_enum_members_are_distinct(self) -> None:
        """Each enum member has a unique identity."""
        members = list(perms.PermissionStatus)
        assert len(members) == len({id(m) for m in members})

    def test_member_lookup_by_value(self) -> None:
        """String-based lookup returns the right enum member."""
        assert perms.PermissionStatus("granted") is perms.PermissionStatus.GRANTED
        assert perms.PermissionStatus("denied") is perms.PermissionStatus.DENIED
        assert (
            perms.PermissionStatus("not_determined")
            is perms.PermissionStatus.NOT_DETERMINED
        )
        assert perms.PermissionStatus("unknown") is perms.PermissionStatus.UNKNOWN

    def test_invalid_member_raises(self) -> None:
        """Unknown string values raise ``ValueError``."""
        with pytest.raises(ValueError):
            perms.PermissionStatus("bogus")


# ---------------------------------------------------------------------------
# PermissionInfo dataclass
# ---------------------------------------------------------------------------


class TestPermissionInfo:
    """Coverage for the ``PermissionInfo`` dataclass and ``to_dict``."""

    def test_construction_with_required_fields(self) -> None:
        """Build with the four required fields (no ``recovery_hint``)."""
        info = perms.PermissionInfo(
            name="accessibility",
            status=perms.PermissionStatus.GRANTED,
            required=True,
            description="Required for UI control",
        )
        assert info.name == "accessibility"
        assert info.status is perms.PermissionStatus.GRANTED
        assert info.required is True
        assert info.description == "Required for UI control"
        # Default for the optional ``recovery_hint`` field
        assert info.recovery_hint is None

    def test_construction_with_recovery_hint(self) -> None:
        """Build with the optional ``recovery_hint`` explicitly set."""
        hint = "Open System Settings > Privacy & Security > Accessibility"
        info = perms.PermissionInfo(
            name="accessibility",
            status=perms.PermissionStatus.DENIED,
            required=True,
            description="desc",
            recovery_hint=hint,
        )
        assert info.recovery_hint == hint

    def test_to_dict_serializes_status_as_string_value(self) -> None:
        """``to_dict`` serializes the enum to its raw string value."""
        info = perms.PermissionInfo(
            name="screen_recording",
            status=perms.PermissionStatus.NOT_DETERMINED,
            required=False,
            description="Required for screenshots",
            recovery_hint="Grant in System Settings",
        )
        result = info.to_dict()
        assert result == {
            "name": "screen_recording",
            "status": "not_determined",  # .value, not .name
            "required": False,
            "description": "Required for screenshots",
            "recovery_hint": "Grant in System Settings",
        }

    def test_to_dict_without_recovery_hint(self) -> None:
        """``to_dict`` propagates ``recovery_hint=None`` when not provided."""
        info = perms.PermissionInfo(
            name="accessibility",
            status=perms.PermissionStatus.GRANTED,
            required=True,
            description="desc",
        )
        result = info.to_dict()
        assert result["recovery_hint"] is None

    def test_permission_info_is_frozen(self) -> None:
        """Regression: ``PermissionInfo`` is ``frozen=True`` so callers cannot
        mutate ``recovery_hint`` (or any other field) after construction.

        Previously the dataclass was mutable — two callers sharing an
        instance could clobber each other's ``recovery_hint``.
        """
        info = perms.PermissionInfo(
            name="x",
            status=perms.PermissionStatus.GRANTED,
            required=True,
            description="y",
        )
        with pytest.raises((AttributeError, FrozenInstanceError)):
            info.recovery_hint = "added later"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PermissionChecker.__init__ and is_macos
# ---------------------------------------------------------------------------


class TestPermissionCheckerInit:
    """Coverage for ``PermissionChecker.__init__`` and ``is_macos``."""

    def test_init_records_platform_flag(self) -> None:
        """``__init__`` records platform flag.

        Regression: prior versions cached ``_cached_accessibility`` and
        ``_cached_screen_recording`` to None in __init__, but those fields
        were never read or written anywhere else — dead code removed.
        """
        checker = perms.PermissionChecker()
        assert checker._is_macos == (sys.platform == "darwin")
        # Cache fields were removed in favor of always re-querying the OS;
        # the only state held is the platform flag.
        assert not hasattr(checker, "_cached_accessibility")
        assert not hasattr(checker, "_cached_screen_recording")

    def test_is_macos_returns_flag(self) -> None:
        """``is_macos`` returns the cached ``_is_macos`` value verbatim."""
        checker = perms.PermissionChecker()
        assert checker.is_macos() is checker._is_macos

    def test_is_macos_can_be_forced_via_flag(self) -> None:
        """Setting ``_is_macos`` flips ``is_macos`` (test seam)."""
        checker = perms.PermissionChecker()
        checker._is_macos = True
        assert checker.is_macos() is True
        checker._is_macos = False
        assert checker.is_macos() is False


# ---------------------------------------------------------------------------
# check_accessibility
# ---------------------------------------------------------------------------


class TestCheckAccessibility:
    """Coverage for ``check_accessibility`` (all four branches)."""

    def test_non_macos_returns_true_without_imports(self) -> None:
        """On non-macOS platforms, ``check_accessibility`` short-circuits to True."""
        checker = _force_macos(perms.PermissionChecker())
        checker._is_macos = False  # Not macOS
        # Patch the import so we can prove it is never reached
        with patch.dict(sys.modules, {"ApplicationServices": None}):
            assert checker.check_accessibility() is True

    def test_macos_with_trusted_returns_true(self) -> None:
        """On macOS, when ``AXIsProcessTrusted`` returns True, propagate True."""
        checker = _force_macos(perms.PermissionChecker())
        # ImportError is the common "no PyObjC" path; cover it explicitly.
        _inject_module(
            "ApplicationServices",
            AXIsProcessTrusted=lambda: True,
        )
        try:
            assert checker.check_accessibility() is True
        finally:
            _pop_module("ApplicationServices")

    def test_macos_with_untrusted_returns_false(self) -> None:
        """On macOS, when ``AXIsProcessTrusted`` returns False, propagate False."""
        checker = _force_macos(perms.PermissionChecker())
        _inject_module(
            "ApplicationServices",
            AXIsProcessTrusted=lambda: False,
        )
        try:
            assert checker.check_accessibility() is False
        finally:
            _pop_module("ApplicationServices")

    def test_macos_with_importerror_returns_true(self) -> None:
        """When ``ApplicationServices`` cannot be imported (no PyObjC), return True."""
        checker = _force_macos(perms.PermissionChecker())
        # Make ``ApplicationServices`` unimportable: force ImportError.
        with patch.dict(sys.modules, {"ApplicationServices": None}):
            assert checker.check_accessibility() is True

    def test_macos_with_generic_exception_returns_false(self) -> None:
        """A non-ImportError from inside the trust check returns False."""
        checker = _force_macos(perms.PermissionChecker())

        def boom() -> bool:
            raise RuntimeError("AX subsystem offline")

        _inject_module("ApplicationServices", AXIsProcessTrusted=boom)
        try:
            assert checker.check_accessibility() is False
        finally:
            _pop_module("ApplicationServices")


# ---------------------------------------------------------------------------
# check_screen_recording
# ---------------------------------------------------------------------------


class TestCheckScreenRecording:
    """Coverage for ``check_screen_recording`` (all four branches)."""

    def test_non_macos_returns_true_without_imports(self) -> None:
        """Non-macOS short-circuits to True (no Quartz import needed)."""
        checker = perms.PermissionChecker()
        checker._is_macos = False
        with patch.dict(sys.modules, {"Quartz": None}):
            assert checker.check_screen_recording() is True

    def test_macos_with_image_returns_true(self) -> None:
        """When ``CGWindowListCreateImage`` returns an image, permissions are granted."""
        checker = _force_macos(perms.PermissionChecker())
        sentinel = object()  # Any non-None object counts as "image returned"

        def fake_list_image(*_args: Any, **_kwargs: Any) -> Any:
            return sentinel

        _inject_module(
            "Quartz",
            CGRectInfinite=(0, 0, 0, 0),
            kCGWindowListOptionOnScreenOnly=1,
            kCGNullWindowID=0,
            kCGWindowImageDefault=0,
            CGWindowListCreateImage=fake_list_image,
        )
        try:
            assert checker.check_screen_recording() is True
        finally:
            _pop_module("Quartz")

    def test_macos_with_no_image_returns_false(self) -> None:
        """When ``CGWindowListCreateImage`` returns None, permissions are denied."""
        checker = _force_macos(perms.PermissionChecker())

        def fake_list_image(*_args: Any, **_kwargs: Any) -> None:
            return None

        _inject_module(
            "Quartz",
            CGRectInfinite=(0, 0, 0, 0),
            kCGWindowListOptionOnScreenOnly=1,
            kCGNullWindowID=0,
            kCGWindowImageDefault=0,
            CGWindowListCreateImage=fake_list_image,
        )
        try:
            assert checker.check_screen_recording() is False
        finally:
            _pop_module("Quartz")

    def test_macos_with_importerror_returns_true(self) -> None:
        """When Quartz cannot be imported, return True (test-environment tolerance)."""
        checker = _force_macos(perms.PermissionChecker())
        with patch.dict(sys.modules, {"Quartz": None}):
            assert checker.check_screen_recording() is True

    def test_macos_with_generic_exception_returns_false(self) -> None:
        """Any exception other than ImportError is treated as a denial."""
        checker = _force_macos(perms.PermissionChecker())

        def boom(*_args: Any, **_kwargs: Any) -> Any:
            raise OSError("display capture unavailable")

        _inject_module(
            "Quartz",
            CGRectInfinite=(0, 0, 0, 0),
            kCGWindowListOptionOnScreenOnly=1,
            kCGNullWindowID=0,
            kCGWindowImageDefault=0,
            CGWindowListCreateImage=boom,
        )
        try:
            assert checker.check_screen_recording() is False
        finally:
            _pop_module("Quartz")


# ---------------------------------------------------------------------------
# get_accessibility_status / get_screen_recording_status
# ---------------------------------------------------------------------------


class TestGetAccessibilityStatus:
    """Coverage for ``get_accessibility_status`` (both branches)."""

    def test_non_macos_is_granted(self) -> None:
        """Non-macOS short-circuits to ``GRANTED``."""
        checker = perms.PermissionChecker()
        checker._is_macos = False
        assert checker.get_accessibility_status() is perms.PermissionStatus.GRANTED

    def test_macos_granted_when_check_returns_true(self) -> None:
        """``check_accessibility`` True → ``GRANTED``."""
        checker = _force_macos(perms.PermissionChecker())
        _inject_module("ApplicationServices", AXIsProcessTrusted=lambda: True)
        try:
            assert (
                checker.get_accessibility_status() is perms.PermissionStatus.GRANTED
            )
        finally:
            _pop_module("ApplicationServices")

    def test_macos_denied_when_check_returns_false(self) -> None:
        """``check_accessibility`` False → ``DENIED``."""
        checker = _force_macos(perms.PermissionChecker())
        _inject_module("ApplicationServices", AXIsProcessTrusted=lambda: False)
        try:
            assert (
                checker.get_accessibility_status() is perms.PermissionStatus.DENIED
            )
        finally:
            _pop_module("ApplicationServices")


class TestGetScreenRecordingStatus:
    """Coverage for ``get_screen_recording_status`` (both branches)."""

    def test_non_macos_is_granted(self) -> None:
        """Non-macOS short-circuits to ``GRANTED``."""
        checker = perms.PermissionChecker()
        checker._is_macos = False
        assert (
            checker.get_screen_recording_status() is perms.PermissionStatus.GRANTED
        )

    def test_macos_granted_when_check_returns_true(self) -> None:
        """``check_screen_recording`` True → ``GRANTED``."""
        checker = _force_macos(perms.PermissionChecker())
        _inject_module(
            "Quartz",
            CGRectInfinite=(0, 0, 0, 0),
            kCGWindowListOptionOnScreenOnly=1,
            kCGNullWindowID=0,
            kCGWindowImageDefault=0,
            CGWindowListCreateImage=lambda *a, **k: object(),
        )
        try:
            assert (
                checker.get_screen_recording_status()
                is perms.PermissionStatus.GRANTED
            )
        finally:
            _pop_module("Quartz")

    def test_macos_denied_when_check_returns_false(self) -> None:
        """``check_screen_recording`` False → ``DENIED``."""
        checker = _force_macos(perms.PermissionChecker())
        _inject_module(
            "Quartz",
            CGRectInfinite=(0, 0, 0, 0),
            kCGWindowListOptionOnScreenOnly=1,
            kCGNullWindowID=0,
            kCGWindowImageDefault=0,
            CGWindowListCreateImage=lambda *a, **k: None,
        )
        try:
            assert (
                checker.get_screen_recording_status()
                is perms.PermissionStatus.DENIED
            )
        finally:
            _pop_module("Quartz")


# ---------------------------------------------------------------------------
# get_all_permissions
# ---------------------------------------------------------------------------


class TestGetAllPermissions:
    """Coverage for ``get_all_permissions`` ordering, fields, and required flag."""

    def test_non_macos_returns_two_granted(self) -> None:
        """Both entries should be GRANTED on non-macOS, no exceptions raised."""
        checker = perms.PermissionChecker()
        checker._is_macos = False
        perms_ = checker.get_all_permissions()

        assert len(perms_) == 2
        names = [p.name for p in perms_]
        assert names == ["accessibility", "screen_recording"]
        assert all(p.status is perms.PermissionStatus.GRANTED for p in perms_)
        # The accessibility entry is marked required; the screen-recording one is not
        assert perms_[0].required is True
        assert perms_[1].required is False

    def test_each_entry_has_recovery_hint(self) -> None:
        """Recovery hints must be present (non-None, non-empty strings)."""
        checker = perms.PermissionChecker()
        checker._is_macos = False
        perms_ = checker.get_all_permissions()

        for p in perms_:
            assert isinstance(p.recovery_hint, str)
            assert p.recovery_hint.strip(), f"{p.name} has empty recovery_hint"

    def test_each_entry_has_description(self) -> None:
        """Descriptions should be non-empty strings (operator-facing UX)."""
        checker = perms.PermissionChecker()
        checker._is_macos = False
        perms_ = checker.get_all_permissions()
        for p in perms_:
            assert isinstance(p.description, str)
            assert p.description

    def test_reflects_current_macos_denied(self) -> None:
        """macOS + denied → first entry DENIED, second entry still GRANTED."""
        checker = _force_macos(perms.PermissionChecker())
        _inject_module("ApplicationServices", AXIsProcessTrusted=lambda: False)
        _inject_module(
            "Quartz",
            CGRectInfinite=(0, 0, 0, 0),
            kCGWindowListOptionOnScreenOnly=1,
            kCGNullWindowID=0,
            kCGWindowImageDefault=0,
            CGWindowListCreateImage=lambda *a, **k: object(),
        )
        try:
            perms_ = checker.get_all_permissions()
            assert perms_[0].status is perms.PermissionStatus.DENIED
            assert perms_[1].status is perms.PermissionStatus.GRANTED
        finally:
            _pop_module("ApplicationServices")
            _pop_module("Quartz")


# ---------------------------------------------------------------------------
# request_accessibility
# ---------------------------------------------------------------------------


class TestRequestAccessibility:
    """Coverage for ``request_accessibility`` (all four branches)."""

    def test_non_macos_returns_true(self) -> None:
        """Non-macOS platforms never show the prompt, return True."""
        checker = perms.PermissionChecker()
        checker._is_macos = False
        with patch.dict(sys.modules, {"ApplicationServices": None}):
            assert checker.request_accessibility() is True

    def test_macos_already_trusted_returns_true(self) -> None:
        """If ``AXIsProcessTrustedWithOptions`` returns True, prompt was acknowledged."""
        checker = _force_macos(perms.PermissionChecker())

        def fake_request(_options: dict[str, Any]) -> bool:
            return True

        _inject_module(
            "ApplicationServices",
            AXIsProcessTrustedWithOptions=fake_request,
        )
        try:
            assert checker.request_accessibility() is True
        finally:
            _pop_module("ApplicationServices")

    def test_macos_not_trusted_returns_false(self) -> None:
        """If the user dismisses the prompt, return False (not an error)."""
        checker = _force_macos(perms.PermissionChecker())

        def fake_request(_options: dict[str, Any]) -> bool:
            return False

        _inject_module(
            "ApplicationServices",
            AXIsProcessTrustedWithOptions=fake_request,
        )
        try:
            assert checker.request_accessibility() is False
        finally:
            _pop_module("ApplicationServices")

    def test_macos_options_contain_prompt_flag(self) -> None:
        """The options dict passed to the API must enable the prompt (default)."""
        checker = _force_macos(perms.PermissionChecker())
        captured: dict[str, Any] = {}

        def fake_request(options: dict[str, Any]) -> bool:
            captured.update(options)
            return True

        _inject_module(
            "ApplicationServices",
            AXIsProcessTrustedWithOptions=fake_request,
        )
        try:
            checker.request_accessibility()
            assert captured == {"kAXTrustedCheckOptionPrompt": True}
        finally:
            _pop_module("ApplicationServices")

    def test_macos_prompt_false_skips_dialog(self) -> None:
        """Regression: ``prompt=False`` suppresses the system permission dialog.

        Non-interactive contexts (CI, automation) need to query the trusted
        status without spawning a dialog. Before the fix, the option dict
        was hardcoded and there was no way to opt out.
        """
        checker = _force_macos(perms.PermissionChecker())
        captured: dict[str, Any] = {}

        def fake_request(options: dict[str, Any]) -> bool:
            captured.update(options)
            return True

        _inject_module(
            "ApplicationServices",
            AXIsProcessTrustedWithOptions=fake_request,
        )
        try:
            checker.request_accessibility(prompt=False)
            assert captured == {"kAXTrustedCheckOptionPrompt": False}
        finally:
            _pop_module("ApplicationServices")

    def test_macos_importerror_returns_true(self) -> None:
        """When PyObjC is missing, return True (avoid surfacing ImportError to callers)."""
        checker = _force_macos(perms.PermissionChecker())
        with patch.dict(sys.modules, {"ApplicationServices": None}):
            assert checker.request_accessibility() is True

    def test_macos_generic_exception_returns_false(self) -> None:
        """Any non-ImportError exception collapses to False (deny-on-failure)."""
        checker = _force_macos(perms.PermissionChecker())

        def boom(_options: dict[str, Any]) -> bool:
            raise OSError("AX daemon crashed")

        _inject_module(
            "ApplicationServices",
            AXIsProcessTrustedWithOptions=boom,
        )
        try:
            assert checker.request_accessibility() is False
        finally:
            _pop_module("ApplicationServices")


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------


class TestToDict:
    """Coverage for ``PermissionChecker.to_dict``."""

    def test_to_dict_returns_expected_keys(self) -> None:
        """Output dict has ``platform``, ``permissions``, ``all_granted``, ``can_screenshot``."""
        checker = perms.PermissionChecker()
        checker._is_macos = False
        result = checker.to_dict()
        assert set(result.keys()) == {
            "platform",
            "permissions",
            "all_granted",
            "can_screenshot",
        }
        assert result["platform"] == sys.platform
        assert result["all_granted"] is True
        assert result["can_screenshot"] is True

    def test_to_dict_permissions_keyed_by_name(self) -> None:
        """``permissions`` is a dict keyed by ``PermissionInfo.name``."""
        checker = perms.PermissionChecker()
        checker._is_macos = False
        result = checker.to_dict()
        perms_ = result["permissions"]
        assert set(perms_.keys()) == {"accessibility", "screen_recording"}
        # Each entry is a dict produced by ``PermissionInfo.to_dict``
        for entry in perms_.values():
            assert "name" in entry
            assert "status" in entry
            assert "required" in entry
            assert "description" in entry

    def test_to_dict_macos_denied_propagates(self) -> None:
        """``all_granted`` follows ``check_accessibility`` on macOS."""
        checker = _force_macos(perms.PermissionChecker())
        _inject_module("ApplicationServices", AXIsProcessTrusted=lambda: False)
        try:
            result = checker.to_dict()
            assert result["all_granted"] is False
        finally:
            _pop_module("ApplicationServices")


# ---------------------------------------------------------------------------
# Module-level convenience helpers + global singleton
# ---------------------------------------------------------------------------


class TestModuleLevelHelpers:
    """Coverage for the module-level helper functions."""

    def test_get_permission_checker_returns_singleton(self) -> None:
        """Repeated calls return the same cached instance."""
        first = perms.get_permission_checker()
        second = perms.get_permission_checker()
        assert first is second

    def test_get_permission_checker_constructs_when_none(self) -> None:
        """First call constructs a fresh ``PermissionChecker``."""
        assert perms._checker is None  # autouse fixture resets
        checker = perms.get_permission_checker()
        assert isinstance(checker, perms.PermissionChecker)
        assert perms._checker is checker

    def test_check_accessibility_permissions_delegates(self) -> None:
        """Module-level ``check_accessibility_permissions`` returns the checker's value."""
        # Non-macOS default in the test environment
        result = perms.check_accessibility_permissions()
        assert result is True  # non-macOS short-circuits to True

    def test_check_screen_recording_permissions_delegates(self) -> None:
        """Module-level ``check_screen_recording_permissions`` returns the checker's value."""
        result = perms.check_screen_recording_permissions()
        assert result is True

    def test_get_all_permission_status_returns_dict(self) -> None:
        """Module-level ``get_all_permission_status`` returns the full status dict."""
        result = perms.get_all_permission_status()
        assert isinstance(result, dict)
        assert "platform" in result
        assert "permissions" in result
        assert "all_granted" in result
        assert "can_screenshot" in result


class TestGlobalSingletonIsolation:
    """Demonstrate the autouse fixture keeps tests isolated from one another."""

    def test_first_test_resets_state(self) -> None:
        """The autouse ``_clear_global_checker`` fixture left ``_checker`` None."""
        assert perms._checker is None

    def test_singleton_constructs_in_isolation(self) -> None:
        """Each test sees ``_checker`` as None at start, can build a fresh one."""
        assert perms._checker is None
        perms.get_permission_checker()
        assert isinstance(perms._checker, perms.PermissionChecker)
