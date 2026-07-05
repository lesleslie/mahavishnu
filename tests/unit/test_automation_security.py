"""Unit tests for mahavishnu.automation.security.

Covers the AutomationSecurity class and module-level helpers:
- is_app_allowed / validate_app (allowlist and blocklist)
- is_text_allowed / validate_text (pattern and regex checks)
- check_rate_limit / validate_rate_limit
- requires_confirmation
- add/remove blocked/allowed apps
- get_stats / to_dict
- security_check decorator
- configure_security / get_security
"""

from __future__ import annotations

import pytest

from mahavishnu.automation.errors import (
    BlockedAppError,
    BlockedTextError,
    RateLimitedError,
)
from mahavishnu.automation.models import AutomationConfig
from mahavishnu.automation.security import (
    DEFAULT_BLOCKED_APPS,
    DEFAULT_BLOCKED_PATTERNS,
    AutomationSecurity,
    configure_security,
    get_security,
    security_check,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def security() -> AutomationSecurity:
    return AutomationSecurity()


@pytest.fixture
def custom_config() -> AutomationConfig:
    return AutomationConfig(
        max_operations_per_second=3,
        blocked_apps={"com.custom.blocked"},
        allowed_apps=None,
        blocked_text_patterns={"custom_blocked"},
        require_confirmation_for={"dangerous_op"},
    )


# =============================================================================
# Construction & Defaults
# =============================================================================


class TestAutomationSecurityInit:
    @pytest.mark.unit
    def test_default_config(self, security):
        assert isinstance(security.config, AutomationConfig)
        # default blocklist includes the built-ins plus defaults from config
        assert "com.apple.securityd" in security._blocked_apps
        assert "com.agilebits.onepassword" in security._blocked_apps

    @pytest.mark.unit
    def test_explicit_config(self, custom_config):
        s = AutomationSecurity(custom_config)
        assert s.config is custom_config
        assert "com.custom.blocked" in s._blocked_apps
        # also includes the built-in default blocklist
        assert "com.apple.securityd" in s._blocked_apps
        assert "custom_blocked" in s._blocked_patterns
        assert "password" in s._blocked_patterns  # from defaults

    @pytest.mark.unit
    def test_blocked_pattern_regex_compiles(self, security):
        assert security._blocked_pattern_regex is not None

    @pytest.mark.unit
    def test_rate_limit_state_isolated_per_key(self, security):
        # First call for key "a" must not affect key "b"
        security.check_rate_limit("a")
        assert len(security._rate_limit_state["a"].operations) == 1
        assert len(security._rate_limit_state.get("b", [])) == 0


# =============================================================================
# is_app_allowed / validate_app
# =============================================================================


class TestIsAppAllowed:
    @pytest.mark.unit
    def test_unblocked_app_allowed(self, security):
        assert security.is_app_allowed("com.apple.Safari") is True

    @pytest.mark.unit
    def test_blocked_app_disallowed(self, security):
        assert security.is_app_allowed("com.apple.securityd") is False

    @pytest.mark.unit
    def test_case_insensitive(self, security):
        # mixed case should still match the (lowercased) blocklist
        assert security.is_app_allowed("COM.Apple.SecurityD") is False
        assert security.is_app_allowed("com.apple.SAFARI") is True

    @pytest.mark.unit
    def test_strips_whitespace(self, security):
        assert security.is_app_allowed("  com.apple.Safari  ") is True

    @pytest.mark.unit
    def test_allowlist_overrides_blocklist(self):
        config = AutomationConfig(allowed_apps={"com.allowed.app"})
        s = AutomationSecurity(config)
        # allowlist mode means anything not on allowlist is rejected
        assert s.is_app_allowed("com.allowed.app") is True
        assert s.is_app_allowed("com.apple.Safari") is False
        # even if the bundle id is also on the default blocklist
        assert s.is_app_allowed("com.apple.securityd") is False

    @pytest.mark.unit
    def test_add_blocked_app(self, security):
        security.add_blocked_app("com.temporarily.blocked")
        assert security.is_app_allowed("com.temporarily.blocked") is False

    @pytest.mark.unit
    def test_remove_blocked_app(self, security):
        security.add_blocked_app("com.example.x")
        assert security.is_app_allowed("com.example.x") is False
        security.remove_blocked_app("com.example.x")
        assert security.is_app_allowed("com.example.x") is True

    @pytest.mark.unit
    def test_remove_unknown_app_is_safe(self, security):
        # discard() must not raise for unknown entries
        security.remove_blocked_app("com.never.added")
        assert security.is_app_allowed("com.never.added") is True

    @pytest.mark.unit
    def test_add_allowed_app(self):
        config = AutomationConfig(allowed_apps={"com.already.allowed"})
        s = AutomationSecurity(config)
        s.add_allowed_app("com.new.allowed")
        assert s.is_app_allowed("com.new.allowed") is True


class TestValidateApp:
    @pytest.mark.unit
    def test_valid_app_does_not_raise(self, security):
        # should be a no-op
        security.validate_app("com.apple.Safari")

    @pytest.mark.unit
    def test_blocked_app_raises(self, security):
        with pytest.raises(BlockedAppError) as exc:
            security.validate_app("com.apple.securityd")
        assert exc.value.details["bundle_id"] == "com.apple.securityd"

    @pytest.mark.unit
    def test_error_includes_recovery_hint(self, security):
        with pytest.raises(BlockedAppError) as exc:
            security.validate_app("com.apple.securityd")
        assert exc.value.recovery_hint is not None
        assert "allowed_apps" in exc.value.recovery_hint


# =============================================================================
# is_text_allowed / validate_text
# =============================================================================


class TestIsTextAllowed:
    @pytest.mark.unit
    def test_empty_text_allowed(self, security):
        assert security.is_text_allowed("") == (True, None)

    @pytest.mark.unit
    def test_benign_text_allowed(self, security):
        assert security.is_text_allowed("Hello, world!") == (True, None)

    @pytest.mark.unit
    def test_password_blocked(self, security):
        is_allowed, pattern = security.is_text_allowed("My password is hunter2")
        assert is_allowed is False
        assert pattern == "password"

    @pytest.mark.unit
    def test_api_key_blocked(self, security):
        is_allowed, pattern = security.is_text_allowed("api_key=abc123def456ghi789jkl012")
        assert is_allowed is False
        assert pattern in {"api_key", "sensitive_data_pattern"}

    @pytest.mark.unit
    def test_aws_access_key_blocked(self, security):
        is_allowed, _ = security.is_text_allowed("AKIAIOSFODNN7EXAMPLE")
        assert is_allowed is False

    @pytest.mark.unit
    def test_jwt_token_blocked(self, security):
        # Build a JWT-shaped string from parts; never embed a literal token
        header = "x" * 32
        payload = "x" * 32
        signature = "x" * 32
        synthetic_jwt = f"eyJ{header}.eyJ{payload}.{signature}"
        is_allowed, _ = security.is_text_allowed(synthetic_jwt)
        assert is_allowed is False

    @pytest.mark.unit
    def test_private_key_marker_blocked(self, security):
        is_allowed, _ = security.is_text_allowed("-----BEGIN RSA PRIVATE KEY-----")
        assert is_allowed is False

    @pytest.mark.unit
    def test_text_in_middle_of_word_allowed(self, security):
        # The default regex uses word boundaries, so "passport" must not match
        assert security.is_text_allowed("Please bring your passport") == (True, None)


class TestValidateText:
    @pytest.mark.unit
    def test_benign_text_passes(self, security):
        security.validate_text("Hello, world!")

    @pytest.mark.unit
    def test_blocked_text_raises(self, security):
        with pytest.raises(BlockedTextError) as exc:
            security.validate_text("My password is hunter2")
        # The pattern is stored in details
        assert exc.value.details["pattern"] == "password"


# =============================================================================
# Rate Limiting
# =============================================================================


class TestRateLimit:
    @pytest.mark.unit
    def test_under_limit_returns_true(self, security):
        assert security.check_rate_limit("session-1") is True

    @pytest.mark.unit
    def test_multiple_keys_independent(self, security):
        for _ in range(3):
            assert security.check_rate_limit("k1") is True
        # different key starts fresh
        assert security.check_rate_limit("k2") is True

    @pytest.mark.unit
    def test_exceeding_max_ops_returns_false(self):
        cfg = AutomationConfig(max_operations_per_second=2)
        s = AutomationSecurity(cfg)
        assert s.check_rate_limit("k") is True
        assert s.check_rate_limit("k") is True
        # third call within one second must be blocked
        assert s.check_rate_limit("k") is False

    @pytest.mark.unit
    def test_validate_rate_limit_raises_on_exceed(self):
        cfg = AutomationConfig(max_operations_per_second=1)
        s = AutomationSecurity(cfg)
        s.check_rate_limit("k")
        with pytest.raises(RateLimitedError) as exc:
            s.validate_rate_limit("k")
        assert exc.value.details["retry_after"] >= 0

    @pytest.mark.unit
    def test_validate_rate_limit_no_operations(self):
        # No operations yet, validate should pass
        cfg = AutomationConfig(max_operations_per_second=2)
        s = AutomationSecurity(cfg)
        s.validate_rate_limit("fresh-key")  # should not raise


# =============================================================================
# requires_confirmation
# =============================================================================


class TestRequiresConfirmation:
    @pytest.mark.unit
    def test_default_confirmation_set_includes_quit_app(self, security):
        # quit_app is in the default config's require_confirmation_for
        assert security.requires_confirmation("quit_app") is True

    @pytest.mark.unit
    def test_random_op_does_not_require_confirmation(self, security):
        assert security.requires_confirmation("click") is False

    @pytest.mark.unit
    def test_custom_confirmation(self, custom_config):
        s = AutomationSecurity(custom_config)
        assert s.requires_confirmation("dangerous_op") is True
        assert s.requires_confirmation("quit_app") is False  # not in custom set


# =============================================================================
# Stats and Dicts
# =============================================================================


class TestStatsAndDicts:
    @pytest.mark.unit
    def test_get_blocked_apps_returns_copy(self, security):
        result = security.get_blocked_apps()
        assert "com.apple.securityd" in result
        # mutating the returned set must not affect internal state
        result.discard("com.apple.securityd")
        assert "com.apple.securityd" in security._blocked_apps

    @pytest.mark.unit
    def test_get_allowed_apps_none(self, security):
        # no allowlist configured
        assert security.get_allowed_apps() is None

    @pytest.mark.unit
    def test_get_allowed_apps_with_set(self):
        config = AutomationConfig(allowed_apps={"a", "b"})
        s = AutomationSecurity(config)
        result = s.get_allowed_apps()
        assert result == {"a", "b"}
        # mutating the returned set must not affect internal state
        result.discard("a")
        assert "a" in s._allowed_apps

    @pytest.mark.unit
    def test_get_stats(self, security):
        stats = security.get_stats()
        assert stats["blocked_apps_count"] == len(DEFAULT_BLOCKED_APPS)
        assert stats["allowed_apps_count"] is None
        assert stats["blocked_patterns_count"] == len(DEFAULT_BLOCKED_PATTERNS)
        assert stats["rate_limit_per_second"] == 10
        assert stats["active_rate_limit_keys"] == 0

    @pytest.mark.unit
    def test_get_stats_after_rate_limit(self, security):
        security.check_rate_limit("user-1")
        assert security.get_stats()["active_rate_limit_keys"] == 1

    @pytest.mark.unit
    def test_to_dict_keys(self, security):
        result = security.to_dict()
        for key in (
            "blocked_apps",
            "allowed_apps",
            "blocked_patterns",
            "rate_limit",
            "require_confirmation_for",
        ):
            assert key in result

    @pytest.mark.unit
    def test_to_dict_values_are_sorted(self, security):
        result = security.to_dict()
        # Each list should be sorted
        for _blocked in result["blocked_apps"]:
            pass  # just ensure iteration works
        assert result["blocked_apps"] == sorted(result["blocked_apps"])


# =============================================================================
# security_check decorator
# =============================================================================


class _DummySelf:
    """Stand-in for the class instance the decorator expects."""

    def __init__(self, security: AutomationSecurity | None) -> None:
        self._security = security


class TestSecurityCheckDecorator:
    @pytest.mark.unit
    async def test_no_security_instance_bypasses_check(self):
        class C:
            @security_check(bundle_id="bundle")
            async def op(self, bundle):
                return bundle

        c = C.__new__(C)  # bypass __init__; _security is missing
        # getattr returns None; decorator must call the underlying function
        assert await c.op("com.apple.finder") == "com.apple.finder"

    @pytest.mark.unit
    async def test_valid_app_and_text_runs(self):
        cfg = AutomationConfig()
        s = AutomationSecurity(cfg)

        class C:
            @security_check(bundle_id="bid", text="txt")
            async def op(self, bid, txt):
                return (bid, txt)

        c = C()
        c._security = s
        bid, txt = await c.op("com.apple.Safari", "hello")
        assert bid == "com.apple.Safari"
        assert txt == "hello"

    @pytest.mark.unit
    async def test_blocked_app_raises(self):
        s = AutomationSecurity()

        class C:
            @security_check(bundle_id="bid")
            async def op(self, bid):
                return bid

        c = C()
        c._security = s
        with pytest.raises(BlockedAppError):
            await c.op("com.apple.securityd")

    @pytest.mark.unit
    async def test_blocked_text_raises(self):
        s = AutomationSecurity()

        class C:
            @security_check(text="txt")
            async def op(self, txt):
                return txt

        c = C()
        c._security = s
        with pytest.raises(BlockedTextError):
            await c.op("my password is secret123")

    @pytest.mark.unit
    async def test_rate_limit_uses_kwargs(self):
        s = AutomationSecurity()

        class C:
            @security_check(rate_limit_key="rl_key")
            async def op(self, rl_key):
                return rl_key

        c = C()
        c._security = s
        await c.op(rl_key="user-42")
        assert "user-42" in s._rate_limit_state
        assert len(s._rate_limit_state["user-42"].operations) == 1

    @pytest.mark.unit
    async def test_rate_limit_missing_kwarg_uses_default(self):
        s = AutomationSecurity()

        class C:
            @security_check(rate_limit_key="missing_kwarg")
            async def op(self, **kwargs):
                return kwargs

        c = C()
        c._security = s
        await c.op()
        # missing kwarg falls back to "default"
        assert "default" in s._rate_limit_state

    @pytest.mark.unit
    async def test_positional_args_used_for_validation(self):
        s = AutomationSecurity()

        class C:
            @security_check(bundle_id="bid")
            async def op(self, bid):
                return bid

        c = C()
        c._security = s
        with pytest.raises(BlockedAppError):
            await c.op("com.apple.securityd")


# =============================================================================
# Module-level helpers
# =============================================================================


class TestModuleLevelHelpers:
    @pytest.mark.unit
    def test_configure_security_replaces_global(self):
        get_security()
        try:
            new_cfg = AutomationConfig(max_operations_per_second=1)
            configure_security(new_cfg)
            assert get_security().config is new_cfg
        finally:
            # restore default for other tests
            configure_security(AutomationConfig())
        # sanity check restoration
        assert get_security().config.max_operations_per_second == 10
        # also restore original instance reference
        globals()  # silence linters

    @pytest.mark.unit
    def test_get_security_returns_singleton(self):
        a = get_security()
        b = get_security()
        assert a is b
