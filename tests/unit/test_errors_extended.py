"""Tests for Extended Error Module.

Tests cover:
- Recovery guidance for all error codes
- Contextual help functions
- Error formatting
- Error templates
"""

from __future__ import annotations

import pytest

from mahavishnu.core.errors import (
    ErrorCode,
    MahavishnuError,
    ValidationError,
    DatabaseError,
    ConfigurationError,
    TaskNotFoundError,
    RepositoryNotFoundError,
    WebhookAuthError,
    ExternalServiceError,
    get_contextual_help,
    format_error_for_cli,
    create_error_from_exception,
    ErrorTemplates,
)


class TestErrorCodeCoverage:
    """Test that all error codes have recovery guidance."""

    def test_all_codes_have_guidance(self) -> None:
        """Test all ErrorCode values have recovery guidance."""
        missing = []
        for code in ErrorCode:
            if code.value not in MahavishnuError.RECOVERY_GUIDANCE:
                missing.append(code.value)

        assert not missing, f"Missing recovery guidance for: {missing}"

    def test_guidance_not_empty(self) -> None:
        """Test recovery guidance is not empty."""
        for code, guidance in MahavishnuError.RECOVERY_GUIDANCE.items():
            assert guidance, f"Empty guidance for {code}"
            assert len(guidance) >= 1, f"Too few steps for {code}"


class TestContextualHelp:
    """Test contextual help functions."""

    def test_get_contextual_help_basic(self) -> None:
        """Test basic contextual help."""
        help_text = get_contextual_help(ErrorCode.TASK_NOT_FOUND)

        assert "TASK NOT FOUND" in help_text.upper()
        assert "MHV-100" in help_text
        assert "How to resolve" in help_text

    def test_get_contextual_help_with_context(self) -> None:
        """Test contextual help with additional context."""
        help_text = get_contextual_help(
            ErrorCode.TASK_NOT_FOUND,
            context={"task_id": "task-123", "user": "test@example.com"},
        )

        assert "task-123" in help_text
        assert "test@example.com" in help_text
        assert "Context:" in help_text

    def test_get_contextual_help_includes_documentation(self) -> None:
        """Test help includes documentation URL."""
        help_text = get_contextual_help(ErrorCode.VALIDATION_ERROR)

        assert "docs.mahavishnu.org" in help_text
        assert "mhv-003" in help_text.lower()


class TestFormatErrorForCLI:
    """Test CLI error formatting."""

    def test_format_brief(self) -> None:
        """Test brief format (default)."""
        error = ValidationError("Invalid input", details={"field": "title"})
        formatted = format_error_for_cli(error, verbose=False)

        assert "MHV-003" in formatted
        assert "Invalid input" in formatted
        assert "--verbose" in formatted

    def test_format_verbose(self) -> None:
        """Test verbose format."""
        error = ValidationError("Invalid input", details={"field": "title"})
        formatted = format_error_for_cli(error, verbose=True)

        assert "MHV-003" in formatted
        assert "Invalid input" in formatted
        assert "Recovery steps" in formatted

    def test_format_includes_first_recovery_step(self) -> None:
        """Test brief format includes first recovery step."""
        error = TaskNotFoundError("task-123")
        formatted = format_error_for_cli(error, verbose=False)

        assert "Try:" in formatted


class TestCreateErrorFromException:
    """Test creating errors from generic exceptions."""

    def test_create_from_value_error(self) -> None:
        """Test creating from ValueError."""
        original = ValueError("Invalid value")
        error = create_error_from_exception(original, ErrorCode.VALIDATION_ERROR)

        assert error.error_code == ErrorCode.VALIDATION_ERROR
        assert "Invalid value" in error.message
        assert error.details["original_type"] == "ValueError"

    def test_create_with_context(self) -> None:
        """Test creating with additional context."""
        original = ConnectionError("Connection refused")
        error = create_error_from_exception(
            original,
            ErrorCode.DATABASE_CONNECTION_ERROR,
            context={"host": "localhost", "port": 5432},
        )

        assert error.details["host"] == "localhost"
        assert error.details["port"] == 5432

    def test_created_error_is_serializable(self) -> None:
        """Test created error can be serialized."""
        original = RuntimeError("Something went wrong")
        error = create_error_from_exception(original, ErrorCode.INTERNAL_ERROR)

        d = error.to_dict()
        assert d["error_code"] == "MHV-007"
        assert "original_type" in d["details"]


class TestErrorTemplates:
    """Test error templates."""

    def test_task_create_validation_template(self) -> None:
        """Test task creation validation template."""
        error = ErrorTemplates.task_create_validation(
            title="AB",
            repository="invalid",
            issues=["Title too short", "Repository not found"],
        )

        assert isinstance(error, ValidationError)
        assert "title" in error.details
        assert "repository" in error.details
        assert len(error.details["issues"]) == 2

    def test_database_connection_template(self) -> None:
        """Test database connection error template."""
        error = ErrorTemplates.database_connection_failed(
            host="localhost",
            port=5432,
            original_error="Connection refused",
        )

        assert isinstance(error, DatabaseError)
        assert error.details["host"] == "localhost"
        assert error.details["port"] == 5432
        assert "Connection refused" in error.details["original_error"]

    def test_search_failed_template(self) -> None:
        """Test search failed template."""
        error = ErrorTemplates.search_failed(
            query="bug fix",
            reason="Embedding service unavailable",
        )

        assert isinstance(error, ExternalServiceError)
        assert error.details["service"] == "embedding"
        assert "bug fix" in error.message

    def test_config_file_error_template(self) -> None:
        """Test config file error template."""
        error = ErrorTemplates.config_file_error(
            file_path="settings/repos.yaml",
            issue="Invalid YAML syntax",
        )

        assert isinstance(error, ConfigurationError)
        assert "repos.yaml" in error.message
        assert "Invalid YAML" in error.message

    def test_webhook_failed_template(self) -> None:
        """Test webhook failed template."""
        error = ErrorTemplates.webhook_failed(
            event_type="task.created",
            reason="Invalid signature",
            payload_id="payload-123",
        )

        assert isinstance(error, WebhookAuthError)
        assert error.details["event_type"] == "task.created"
        assert error.details["payload_id"] == "payload-123"


class TestErrorSerialization:
    """Test error serialization."""

    def test_to_dict_complete(self) -> None:
        """Test complete to_dict serialization."""
        error = TaskNotFoundError("task-123")
        d = error.to_dict()

        assert "error_code" in d
        assert "message" in d
        assert "recovery" in d
        assert "details" in d
        assert "timestamp" in d
        assert "documentation" in d

    def test_to_dict_includes_details(self) -> None:
        """Test to_dict includes details."""
        error = RepositoryNotFoundError("my-repo", details={"path": "/invalid/path"})
        d = error.to_dict()

        assert d["details"]["repository"] == "my-repo"
        assert d["details"]["path"] == "/invalid/path"


class TestErrorStr:
    """Test error string representation."""

    def test_str_includes_recovery(self) -> None:
        """Test string includes recovery steps."""
        error = ValidationError("Test error")
        s = str(error)

        assert "MHV-003" in s
        assert "Test error" in s
        assert "Recovery steps" in s

    def test_str_includes_documentation(self) -> None:
        """Test string includes documentation URL."""
        error = TaskNotFoundError("task-123")
        s = str(error)

        assert "docs.mahavishnu.org" in s
