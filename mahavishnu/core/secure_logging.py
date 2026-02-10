"""Secure logging with automatic credential redaction.

This module provides structured logging with automatic redaction of sensitive
information including SSH keys, passwords, API keys, tokens, and other credentials.

Key Features:
- Automatic credential detection and redaction
- Structured logging with consistent JSON format
- Integration with structlog for production-ready logging
- Comprehensive pattern matching for various credential types
"""

from enum import StrEnum
import json
import logging
from pathlib import Path
import re
from typing import Any

from pydantic import SecretStr

logger = logging.getLogger(__name__)


# =============================================================================
# CREDENTIAL TYPES
# =============================================================================


class CredentialType(StrEnum):
    """Type of credential to redact."""

    SSH_PRIVATE_KEY = "ssh_private_key"
    SSH_PUBLIC_KEY = "ssh_public_key"
    API_KEY = "api_key"
    PASSWORD = "password"
    TOKEN = "token"
    SECRET = "secret"
    CERTIFICATE = "certificate"
    PRIVATE_KEY = "private_key"
    DATABASE_URL = "database_url"
    CONNECTION_STRING = "connection_string"
    BEARER_TOKEN = "bearer_token"
    BASIC_AUTH = "basic_auth"
    COOKIE = "cookie"
    SESSION_ID = "session_id"


# =============================================================================
# CREDENTIAL PATTERNS
# =============================================================================


class CredentialPatterns:
    """Regular expression patterns for detecting credentials."""

    # SSH private keys (RSA, ECDSA, Ed25519, DSA)
    SSH_PRIVATE_KEY_PATTERNS = [
        r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----",
        r"-----BEGIN\s+EC\s+PRIVATE\s+KEY-----",
        r"-----BEGIN\s+OPENSSH\s+PRIVATE\s+KEY-----",
        r"-----BEGIN\s+DSA\s+PRIVATE\s+KEY-----",
        r"-----BEGIN\s+PGP\s+PRIVATE\s+KEY-----",
    ]

    # SSH public keys
    SSH_PUBLIC_KEY_PATTERNS = [
        r"ssh-rsa\s+[A-Za-z0-9+/]+[=]{0,2}\s+\S+",
        r"ssh-ed25519\s+[A-Za-z0-9+/]+[=]{0,2}\s+\S+",
        r"ssh-ecdsa\s+[A-Za-z0-9+/]+[=]{0,2}\s+\S+",
        r"ssh-dss\s+[A-Za-z0-9+/]+[=]{0,2}\s+\S+",
    ]

    # API keys (common patterns)
    API_KEY_PATTERNS = [
        r'(?i)(api[_-]?key|apikey)["\']?\s*[:=]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?',
        r"(?i)(sk_|ak_|ai_|api_)[a-zA-Z0-9_\-]{15,}",
        r'(?i)(key|token)["\']?\s*[:=]\s*["\']?([a-zA-Z0-9_\-]{32,})["\']?',
        # AWS access keys
        r"AKIA[0-9A-Z]{16,}",
        # GitHub personal access tokens (31-40 characters after ghp_/gho_/etc)
        r"ghp_[a-zA-Z0-9]{31,}",
        r"gho_[a-zA-Z0-9]{31,}",
        r"ghu_[a-zA-Z0-9]{31,}",
        r"ghs_[a-zA-Z0-9]{31,}",
        r"ghr_[a-zA-Z0-9]{31,}",
        # Stripe API keys
        r"sk_(live|test)_[0-9a-zA-Z]{24,}",
    ]

    # Bearer tokens
    BEARER_TOKEN_PATTERNS = [
        r"Bearer\s+[A-Za-z0-9_\-\.~=]{20,}",
        r"authorization:\s*Bearer\s+[A-Za-z0-9_\-\.~=]{20,}",
    ]

    # Database URLs
    DATABASE_URL_PATTERNS = [
        r"(postgresql|mysql|sqlite|mongodb|redis)://[^:]+:[^@]+@",
        r"(postgres|mysql|mongodb|redis)://[^:]+:[^@]+@",
    ]

    # Connection strings
    CONNECTION_STRING_PATTERNS = [
        r"(Server|Host|Data Source)[^;=;]*[=;][^;:]+:[^;@]+",
        r"(User ID|Username)[^;=]*[=;][^;]+;(Password|Pass)[^;=]*[=;][^;]+",
    ]

    # Basic authentication
    BASIC_AUTH_PATTERNS = [
        r"basic\s+[A-Za-z0-9+/=]{20,}",
        r"authorization:\s*basic\s+[A-Za-z0-9+/=]{20,}",
    ]

    # Session IDs and cookies
    SESSION_PATTERNS = [
        r'session[_-]?id["\']?\s*[:=]\s*["\']?([a-zA-Z0-9_\-]{20,})',
        r'cookie["\']?\s*[:=]\s*["\']?([a-zA-Z0-9_%\-\.]{20,})',
    ]

    # Certificates
    CERTIFICATE_PATTERNS = [
        r"-----BEGIN\s+CERTIFICATE-----",
        r"-----BEGIN\s+X509\s+CERTIFICATE-----",
    ]

    @classmethod
    def all_patterns(cls) -> dict[str, list[str]]:
        """Get all credential patterns organized by type."""
        return {
            CredentialType.SSH_PRIVATE_KEY: cls.SSH_PRIVATE_KEY_PATTERNS,
            CredentialType.SSH_PUBLIC_KEY: cls.SSH_PUBLIC_KEY_PATTERNS,
            CredentialType.API_KEY: cls.API_KEY_PATTERNS,
            CredentialType.BEARER_TOKEN: cls.BEARER_TOKEN_PATTERNS,
            CredentialType.DATABASE_URL: cls.DATABASE_URL_PATTERNS,
            CredentialType.CONNECTION_STRING: cls.CONNECTION_STRING_PATTERNS,
            CredentialType.BASIC_AUTH: cls.BASIC_AUTH_PATTERNS,
            CredentialType.SESSION_ID: cls.SESSION_PATTERNS,
            CredentialType.CERTIFICATE: cls.CERTIFICATE_PATTERNS,
        }


# =============================================================================
# CREDENTIAL REDACTOR
# =============================================================================


class CredentialRedactor:
    """Redact credentials from strings and dictionaries."""

    def __init__(self, redaction_string: str = "***REDACTED***"):
        """Initialize credential redactor.

        Args:
            redaction_string: String to replace credentials with
        """
        self.redaction_string = redaction_string
        self.patterns = CredentialPatterns.all_patterns()

    def redact_string(self, text: str) -> str:
        """Redact credentials from a string.

        Args:
            text: String that may contain credentials

        Returns:
            String with credentials redacted
        """
        if not isinstance(text, str):
            return text

        redacted = text

        # Apply all patterns
        for cred_type, patterns in self.patterns.items():
            for pattern in patterns:
                try:
                    # For multi-line SSH keys, use different replacement
                    if cred_type == CredentialType.SSH_PRIVATE_KEY:
                        redacted = self._redact_ssh_key(redacted, pattern)
                    elif cred_type == CredentialType.CERTIFICATE:
                        redacted = self._redact_certificate(redacted, pattern)
                    else:
                        redacted = re.sub(
                            pattern,
                            self._replacement_for_type(cred_type),
                            redacted,
                            flags=re.IGNORECASE | re.MULTILINE,
                        )
                except re.error:
                    # Skip invalid patterns
                    continue

        return redacted

    def _redact_ssh_key(self, text: str, pattern: str) -> str:
        """Redact SSH private key (multi-line block)."""
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            # Find the entire key block
            match = re.search(
                pattern
                + r".*?-----END\s+(RSA\s+|EC\s+|OPENSSH\s+|DSA\s+|PGP\s+)?PRIVATE\s+KEY-----",
                text,
                flags=re.IGNORECASE | re.DOTALL | re.MULTILINE,
            )
            if match:
                return text[: match.start()] + self.redaction_string + text[match.end() :]
        return text

    def _redact_certificate(self, text: str, pattern: str) -> str:
        """Redact certificate (multi-line block)."""
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            # Find the entire certificate block
            match = re.search(
                pattern + r".*?-----END\s+(X509\s+)?CERTIFICATE-----",
                text,
                flags=re.IGNORECASE | re.DOTALL | re.MULTILINE,
            )
            if match:
                return text[: match.start()] + self.redaction_string + text[match.end() :]
        return text

    def _replacement_for_type(self, cred_type: str) -> str:
        """Get replacement string for credential type."""
        return f"[REDACTED:{cred_type.upper()}]"

    def redact_dict(
        self, data: dict[str, Any], sensitive_keys: list[str] | None = None
    ) -> dict[str, Any]:
        """Redact credentials from dictionary.

        Args:
            data: Dictionary that may contain credentials
            sensitive_keys: List of keys to always redact (default: use built-in list)

        Returns:
            Dictionary with credentials redacted
        """
        if sensitive_keys is None:
            sensitive_keys = [
                "password",
                "passwd",
                "pass",
                "secret",
                "token",
                "key",
                "credential",
                "api_key",
                "apikey",
                "auth_token",
                "access_token",
                "refresh_token",
                "ssh_key",
                "private_key",
                "passphrase",
                "jwt_secret",
                "session_token",
                "bearer_token",
                "basic_auth",
                "authorization",
                "cookie",
                "session_id",
                "connection_string",
                "database_url",
                "db_url",
                "dsn",
                "host",
            ]

        redacted = {}

        for key, value in data.items():
            key_lower = key.lower()

            # Check if this is a sensitive key
            is_sensitive = any(sensitive in key_lower for sensitive in sensitive_keys)

            if is_sensitive:
                # Redact the entire value
                if isinstance(value, str):
                    # Show first 4 characters for debugging
                    preview = value[:4] if len(value) > 4 else value
                    redacted[key] = f"{preview}{self.redaction_string}"
                elif isinstance(value, SecretStr):
                    redacted[key] = self.redaction_string
                else:
                    redacted[key] = self.redaction_string
            elif isinstance(value, SecretStr):
                # Pydantic SecretStr
                redacted[key] = self.redaction_string
            elif isinstance(value, dict):
                # Recursively redact nested dictionaries
                redacted[key] = self.redact_dict(value, sensitive_keys)
            elif isinstance(value, list):
                # Redact list items
                redacted[key] = [
                    self.redact_dict(item, sensitive_keys)
                    if isinstance(item, dict)
                    else self.redact_string
                    if is_sensitive
                    else item
                    for item in value
                ]
            elif isinstance(value, str):
                # Redact credentials from string values
                if is_sensitive:
                    redacted[key] = self.redaction_string
                else:
                    redacted[key] = self.redact_string(value)
            else:
                redacted[key] = value

        return redacted

    def redact_log_message(self, message: str, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        """Redact credentials from log message and context.

        Args:
            message: Log message string
            **kwargs: Additional context to redact

        Returns:
            Tuple of (redacted_message, redacted_context)
        """
        redacted_message = self.redact_string(message)
        redacted_context = self.redact_dict(kwargs) if kwargs else {}

        return redacted_message, redacted_context


# =============================================================================
# SECURE LOGGER
# =============================================================================


class SecureLogger:
    """Secure logger with automatic credential redaction."""

    def __init__(
        self,
        name: str,
        log_path: Path | str | None = None,
        redaction_string: str = "***REDACTED***",
    ):
        """Initialize secure logger.

        Args:
            name: Logger name
            log_path: Optional file path for log output
            redaction_string: String to replace credentials with
        """
        self.logger = logging.getLogger(name)
        self.redactor = CredentialRedactor(redaction_string)

        if log_path:
            log_path = Path(log_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            # Add file handler
            handler = logging.FileHandler(log_path)
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

        # Ensure logger level is set
        self.logger.setLevel(logging.DEBUG)

    def _redact_and_log(self, level: int, message: str, **kwargs: Any) -> None:
        """Redact credentials and log message.

        Args:
            level: Logging level (logging.INFO, etc.)
            message: Log message
            **kwargs: Additional context
        """
        redacted_message, redacted_context = self.redactor.redact_log_message(message, **kwargs)

        # Format context if present
        if redacted_context:
            log_message = f"{redacted_message} | Context: {json.dumps(redacted_context)}"
        else:
            log_message = redacted_message

        self.logger.log(level, log_message)

    def info(self, message: str, **kwargs) -> None:
        """Log info message with credential redaction."""
        self._redact_and_log(logging.INFO, message, **kwargs)

    def debug(self, message: str, **kwargs) -> None:
        """Log debug message with credential redaction."""
        self._redact_and_log(logging.DEBUG, message, **kwargs)

    def warning(self, message: str, **kwargs) -> None:
        """Log warning message with credential redaction."""
        self._redact_and_log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs) -> None:
        """Log error message with credential redaction."""
        self._redact_and_log(logging.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs) -> None:
        """Log critical message with credential redaction."""
        self._redact_and_log(logging.CRITICAL, message, **kwargs)

    def exception(self, message: str, **kwargs) -> None:
        """Log exception with credential redaction."""
        redacted_message, redacted_context = self.redactor.redact_log_message(message, **kwargs)

        if redacted_context:
            log_message = f"{redacted_message} | Context: {json.dumps(redacted_context)}"
        else:
            log_message = redacted_message

        self.logger.exception(log_message)

    def close(self) -> None:
        """Close logger and flush all handlers."""
        for handler in self.logger.handlers[:]:
            handler.flush()
            handler.close()
            self.logger.removeHandler(handler)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def get_secure_logger(
    name: str,
    log_path: Path | str | None = None,
) -> SecureLogger:
    """Get or create a secure logger instance.

    Args:
        name: Logger name
        log_path: Optional file path for log output

    Returns:
        SecureLogger instance
    """
    return SecureLogger(name, log_path=log_path)


def redact_credentials(message: str) -> str:
    """Redact credentials from a string.

    Args:
        message: String that may contain credentials

    Returns:
        String with credentials redacted
    """
    redactor = CredentialRedactor()
    return redactor.redact_string(message)


def redact_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Redact credentials from a dictionary.

    Args:
        data: Dictionary that may contain credentials

    Returns:
        Dictionary with credentials redacted
    """
    redactor = CredentialRedactor()
    return redactor.redact_dict(data)
