"""Security validation for desktop automation.

Provides safety checks including:
- Application blocklist/allowlist
- Text pattern validation
- Rate limiting integration
- Operation confirmation

This module implements the security-first design principle with comprehensive
protection against automating sensitive applications and typing sensitive data.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import wraps
from logging import getLogger
import re
import time
from typing import Any

from mahavishnu.automation.errors import (
    BlockedAppError,
    BlockedTextError,
    RateLimitedError,
)
from mahavishnu.automation.models import AutomationConfig

logger = getLogger(__name__)


# Default blocked applications - security critical
# These should NEVER be automated
DEFAULT_BLOCKED_APPS: set[str] = {
    # System security
    "com.apple.securityd",  # Security daemon
    "com.apple.KeychainAccess",  # Keychain Access
    "com.apple.systempreferences",  # System Preferences/Settings
    "com.apple.Passwords",  # Passwords app (macOS 14+)
    "com.apple.loginwindow",  # Login window
    "com.apple.ScreenSaverEngine",  # Screen saver
    "com.apple.screensharing.agent",  # Screen sharing
    "com.apple.RemoteDesktop",  # Remote Desktop
    # Password managers
    "com.agilebits.onepassword",  # 1Password
    "com.agilebits.onepassword7",  # 1Password 7
    "com.agilebits.onepassword8",  # 1Password 8
    "com.lastpass.LastPass",  # LastPass
    "com.lastpass.LastPassDesktop",  # LastPass Desktop
    "com.bitwarden.desktop",  # Bitwarden
    "com.8bit.bitwarden",  # Bitwarden (alternative ID)
    "com.dashlane.dashlanephonefinal",  # Dashlane
    "maccatalyst.com.8bit.bitwarden",  # Bitwarden Catalyst
    # Financial apps (extend as needed)
    "com.intuit.QuickBooks",  # QuickBooks
    "com.quicken.Quicken",  # Quicken
    "com.paypal.universal",  # PayPal
    "com.robinhood.Robinhood",  # Robinhood
    "com.coinbase.pro",  # Coinbase Pro
    "com.coinbase.crypto",  # Coinbase
    # Banking (common patterns)
    "com.chase.mobile",  # Chase
    "com.bankofamerica.BankOfAmerica",  # Bank of America
    "com.wellsfargo.mobilebanking",  # Wells Fargo
    # System utilities that could be dangerous
    "com.apple.ActivityMonitor",  # Activity Monitor (can kill processes)
    "com.apple.Console",  # Console (may show logs)
    "com.apple.DiskUtility",  # Disk Utility (dangerous operations)
}

# Default blocked text patterns - sensitive data that should never be typed
DEFAULT_BLOCKED_PATTERNS: set[str] = {
    "password",
    "passwd",
    "pwd",
    "api_key",
    "apikey",
    "api-key",
    "secret",
    "token",
    "credential",
    "private_key",
    "private-key",
    "privatekey",
    "auth_token",
    "access_token",
    "refresh_token",
    "bearer",
    "authorization",
}

# Regex patterns for sensitive data detection
SENSITIVE_REGEX_PATTERNS: list[re.Pattern] = [
    # API keys (common formats)
    re.compile(r"(?i)(?:api[_-]?key|apikey)\s*[=:]\s*['\"]?[\w-]{20,}['\"]?"),
    # AWS keys
    re.compile(r"AKIA[0-9A-Z]{16}"),
    # JWT tokens (partial match)
    re.compile(r"eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*"),
    # Private key markers
    re.compile(r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----"),
    # Password patterns
    re.compile(r"(?i)(?:password|passwd|pwd)\s*[=:]\s*['\"]?[^\s'\"]{8,}['\"]?"),
]


@dataclass
class RateLimitState:
    """State for rate limiting."""

    operations: list[float] = field(default_factory=list)
    violations: int = 0


class AutomationSecurity:
    """Security validation for desktop automation.

    This class provides comprehensive security checks for automation operations:

    1. **Application Blocklist**: Prevents automating security-sensitive apps
    2. **Text Pattern Blocking**: Prevents typing sensitive data
    3. **Rate Limiting**: Prevents automation abuse
    4. **Input Sanitization**: Validates all inputs

    Usage:
        security = AutomationSecurity(config)

        # Validate application
        if security.is_app_allowed("com.apple.finder"):
            # Safe to automate

        # Validate text
        if security.is_text_allowed("Hello World"):
            # Safe to type

        # Check rate limit
        if security.check_rate_limit("session-123"):
            # Operation allowed
    """

    def __init__(self, config: AutomationConfig | None = None) -> None:
        """Initialize security with configuration.

        Args:
            config: Automation configuration. If None, uses defaults.
        """
        self.config = config or AutomationConfig()

        # Initialize blocklist (merge with defaults)
        self._blocked_apps = DEFAULT_BLOCKED_APPS | self.config.blocked_apps

        # Initialize allowed apps
        self._allowed_apps = self.config.allowed_apps

        # Initialize blocked patterns
        self._blocked_patterns = DEFAULT_BLOCKED_PATTERNS | self.config.blocked_text_patterns

        # Rate limiting state
        self._rate_limit_state: dict[str, RateLimitState] = defaultdict(RateLimitState)

        # Compile blocked patterns for faster matching
        self._blocked_pattern_regex = re.compile(
            r"(?i)\b(" + "|".join(re.escape(p) for p in self._blocked_patterns) + r")\b"
        )

    def is_app_allowed(self, bundle_id: str) -> bool:
        """Check if an application is allowed to be automated.

        Args:
            bundle_id: Application bundle identifier.

        Returns:
            True if the app is allowed, False if blocked.
        """
        # Normalize bundle ID
        bundle_id = bundle_id.strip().lower()

        # Check allowlist first (if configured)
        if self._allowed_apps is not None:
            return bundle_id in {a.lower() for a in self._allowed_apps}

        # Check blocklist
        if bundle_id in {b.lower() for b in self._blocked_apps}:
            return False

        return True

    def validate_app(self, bundle_id: str) -> None:
        """Validate that an app can be automated.

        Args:
            bundle_id: Application bundle identifier.

        Raises:
            BlockedAppError: If the app is in the blocklist.
        """
        if not self.is_app_allowed(bundle_id):
            raise BlockedAppError(bundle_id)

    def is_text_allowed(self, text: str) -> tuple[bool, str | None]:
        """Check if text is allowed to be typed.

        Args:
            text: Text to validate.

        Returns:
            Tuple of (is_allowed, blocked_pattern). If blocked, returns the
            pattern that caused the block.
        """
        if not text:
            return True, None

        # Check for blocked patterns
        match = self._blocked_pattern_regex.search(text)
        if match:
            return False, match.group(1)

        # Check for sensitive data patterns
        for pattern in SENSITIVE_REGEX_PATTERNS:
            if pattern.search(text):
                return False, "sensitive_data_pattern"

        return True, None

    def validate_text(self, text: str) -> None:
        """Validate that text can be typed.

        Args:
            text: Text to validate.

        Raises:
            BlockedTextError: If the text contains blocked patterns.
        """
        is_allowed, pattern = self.is_text_allowed(text)
        if not is_allowed:
            raise BlockedTextError(pattern or "unknown")

    def check_rate_limit(self, key: str = "default") -> bool:
        """Check if an operation is allowed under rate limiting.

        Args:
            key: Rate limit key (e.g., session ID or user ID).

        Returns:
            True if operation is allowed, False if rate limited.
        """
        now = time.time()
        state = self._rate_limit_state[key]
        max_ops = self.config.max_operations_per_second

        # Clean old operations (older than 1 second)
        state.operations = [t for t in state.operations if now - t < 1.0]

        # Check if under limit
        if len(state.operations) >= max_ops:
            return False

        # Record operation
        state.operations.append(now)
        return True

    def validate_rate_limit(self, key: str = "default") -> None:
        """Validate that operation is allowed under rate limiting.

        Args:
            key: Rate limit key.

        Raises:
            RateLimitedError: If rate limit is exceeded.
        """
        state = self._rate_limit_state[key]
        max_ops = self.config.max_operations_per_second

        if not self.check_rate_limit(key):
            # Calculate retry time
            if state.operations:
                oldest = min(state.operations)
                retry_after = 1.0 - (time.time() - oldest)
            else:
                retry_after = 1.0

            raise RateLimitedError(retry_after=retry_after)

    def requires_confirmation(self, operation: str) -> bool:
        """Check if an operation requires user confirmation.

        Args:
            operation: Operation type name.

        Returns:
            True if confirmation is required.
        """
        return operation in self.config.require_confirmation_for

    def get_blocked_apps(self) -> set[str]:
        """Get the set of blocked applications.

        Returns:
            Set of blocked bundle IDs.
        """
        return self._blocked_apps.copy()

    def get_allowed_apps(self) -> set[str] | None:
        """Get the set of allowed applications.

        Returns:
            Set of allowed bundle IDs, or None if all apps are allowed
            (except blocked ones).
        """
        return self._allowed_apps.copy() if self._allowed_apps else None

    def add_blocked_app(self, bundle_id: str) -> None:
        """Add an application to the blocklist.

        Args:
            bundle_id: Application bundle identifier.
        """
        self._blocked_apps.add(bundle_id.lower())

    def remove_blocked_app(self, bundle_id: str) -> None:
        """Remove an application from the blocklist.

        Args:
            bundle_id: Application bundle identifier.
        """
        self._blocked_apps.discard(bundle_id.lower())

    def add_allowed_app(self, bundle_id: str) -> None:
        """Add an application to the allowlist.

        Note: Setting an allowlist means only those apps can be automated.

        Args:
            bundle_id: Application bundle identifier.
        """
        if self._allowed_apps is None:
            self._allowed_apps = set()
        self._allowed_apps.add(bundle_id.lower())

    def get_stats(self) -> dict[str, Any]:
        """Get security statistics.

        Returns:
            Dictionary with security stats.
        """
        return {
            "blocked_apps_count": len(self._blocked_apps),
            "allowed_apps_count": len(self._allowed_apps) if self._allowed_apps else None,
            "blocked_patterns_count": len(self._blocked_patterns),
            "rate_limit_per_second": self.config.max_operations_per_second,
            "active_rate_limit_keys": len(self._rate_limit_state),
        }

    def to_dict(self) -> dict[str, Any]:
        """Get security configuration as dictionary."""
        return {
            "blocked_apps": sorted(self._blocked_apps),
            "allowed_apps": sorted(self._allowed_apps) if self._allowed_apps else None,
            "blocked_patterns": sorted(self._blocked_patterns),
            "rate_limit": self.config.max_operations_per_second,
            "require_confirmation_for": sorted(self.config.require_confirmation_for),
        }


def security_check(
    bundle_id: str | None = None,
    text: str | None = None,
    rate_limit_key: str | None = None,
) -> Callable:
    """Decorator for security checks on automation methods.

    Usage:
        @security_check(bundle_id="bundle_id_arg")
        async def launch_app(self, bundle_id_arg: str):
            ...

        @security_check(text="text_arg")
        async def type_text(self, text_arg: str):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            # Get security instance from self
            security = getattr(self, "_security", None)
            if security is None:
                # No security configured, proceed
                return await func(self, *args, **kwargs)

            # Check bundle ID if specified
            if bundle_id:
                bid = kwargs.get(bundle_id) or (args[0] if args else None)
                if bid:
                    security.validate_app(bid)

            # Check text if specified
            if text:
                txt = kwargs.get(text) or (args[0] if args else None)
                if txt:
                    security.validate_text(txt)

            # Check rate limit if specified
            if rate_limit_key:
                key = kwargs.get(rate_limit_key, "default")
                security.validate_rate_limit(key)

            return await func(self, *args, **kwargs)

        return wrapper

    return decorator


# Global security instance (lazy initialized)
_security: AutomationSecurity | None = None


def get_security(config: AutomationConfig | None = None) -> AutomationSecurity:
    """Get the global security instance."""
    global _security
    if _security is None:
        _security = AutomationSecurity(config)
    return _security


def configure_security(config: AutomationConfig) -> None:
    """Configure the global security instance."""
    global _security
    _security = AutomationSecurity(config)
