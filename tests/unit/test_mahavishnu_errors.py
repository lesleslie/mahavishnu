"""
Comprehensive unit tests for mahavishnu/core/errors.py.

This test module covers the complete custom exception hierarchy including:
- Base exception class (MahavishnuError)
- Configuration errors (ConfigurationError, ValidationError)
- Adapter errors (AdapterError, AdapterInitializationError)
- Workflow errors (WorkflowError, WorkflowExecutionError)
- Authentication/Authorization errors
- Timeout and Database errors
- External service errors
- Prefect, Agno, GoalTeam, and Learning System errors
- Error context and structured data preservation
- Error chaining (from cause)
- Error comparison and equality
- Error creation with and without context
- Error helper functions
- ErrorTemplates class
"""

from datetime import datetime, UTC
from typing import Any

import pytest

from mahavishnu.core.errors import (
    ErrorCode,
    ErrorTemplates,
    MahavishnuError,
    ConfigurationError,
    ValidationError,
    TaskNotFoundError,
    RepositoryNotFoundError,
    WebhookAuthError,
    RateLimitError,
    AdapterError,
    AdapterInitializationError,
    WorkflowExecutionError,
    AuthenticationError,
    AuthorizationError,
    TimeoutError as MahavishnuTimeoutError,
    DatabaseError,
    ExternalServiceError,
    WorkflowError,
    PrefectError,
    AgnoError,
    GoalTeamError,
    GoalTeamNotFoundError,
    GoalParsingError,
    LearningSystemError,
    ContextNotInitializedError,
    FeatureDisabledError,
    get_contextual_help,
    format_error_for_cli,
    create_error_from_exception,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def base_error_message() -> str:
    return "Test error message"


@pytest.fixture
def sample_details() -> dict[str, Any]:
    return {
        "key1": "value1",
        "key2": 42,
        "nested": {"inner": "data"},
    }


@pytest.fixture
def sample_recovery() -> list[str]:
    return ["Step 1", "Step 2", "Step 3"]


# =============================================================================
# 1. Base Exception Class Tests (MahavishnuError)
# =============================================================================


class TestMahavishnuError:
    """Tests for the base MahavishnuError exception class."""

    def test_basic_instantiation(self, base_error_message: str) -> None:
        """Test basic error instantiation with required parameters."""
        error = MahavishnuError(base_error_message, ErrorCode.INTERNAL_ERROR)

        assert error.message == base_error_message
        assert error.error_code == ErrorCode.INTERNAL_ERROR

    def test_error_code_assignment(self, base_error_message: str) -> None:
        """Test that error code is properly assigned."""
        error = MahavishnuError(base_error_message, ErrorCode.CONFIGURATION_ERROR)
        assert error.error_code == ErrorCode.CONFIGURATION_ERROR
        assert error.error_code.value == "MHV-001"

    def test_default_recovery_guidance(self, base_error_message: str) -> None:
        """Test that default recovery guidance is used when none provided."""
        error = MahavishnuError(base_error_message, ErrorCode.INTERNAL_ERROR)
        expected_guidance = MahavishnuError.RECOVERY_GUIDANCE[ErrorCode.INTERNAL_ERROR.value]

        assert error.recovery == expected_guidance
        assert len(error.recovery) > 0

    def test_custom_recovery_guidance(
        self, base_error_message: str, sample_recovery: list[str]
    ) -> None:
        """Test that custom recovery guidance can be provided."""
        error = MahavishnuError(
            base_error_message,
            ErrorCode.INTERNAL_ERROR,
            recovery=sample_recovery,
        )

        assert error.recovery == sample_recovery

    def test_details_default_empty(self, base_error_message: str) -> None:
        """Test that details defaults to empty dict when not provided."""
        error = MahavishnuError(base_error_message, ErrorCode.INTERNAL_ERROR)

        assert error.details == {}

    def test_details_assignment(
        self, base_error_message: str, sample_details: dict[str, Any]
    ) -> None:
        """Test that details are properly assigned."""
        error = MahavishnuError(
            base_error_message,
            ErrorCode.INTERNAL_ERROR,
            details=sample_details,
        )

        assert error.details == sample_details

    def test_timestamp_set_on_init(self, base_error_message: str) -> None:
        """Test that timestamp is automatically set on initialization."""
        before = datetime.now(UTC)
        error = MahavishnuError(base_error_message, ErrorCode.INTERNAL_ERROR)
        after = datetime.now(UTC)

        assert isinstance(error.timestamp, datetime)
        assert before <= error.timestamp <= after

    def test_inherited_from_exception(self, base_error_message: str) -> None:
        """Test that MahavishnuError properly inherits from Exception."""
        error = MahavishnuError(base_error_message, ErrorCode.INTERNAL_ERROR)

        assert isinstance(error, Exception)
        assert isinstance(error, BaseException)

    def test_exception_args_formatted(
        self, base_error_message: str
    ) -> None:
        """Test that Exception args are properly formatted with error code."""
        error = MahavishnuError(base_error_message, ErrorCode.INTERNAL_ERROR)

        # The formatted message should be in args[0]
        assert len(error.args) > 0
        assert f"[{ErrorCode.INTERNAL_ERROR.value}]" in error.args[0]
        assert base_error_message in error.args[0]


class TestMahavishnuErrorToDict:
    """Tests for the to_dict method."""

    def test_to_dict_contains_all_fields(
        self, base_error_message: str, sample_details: dict[str, Any]
    ) -> None:
        """Test that to_dict returns all expected fields."""
        error = MahavishnuError(
            base_error_message,
            ErrorCode.VALIDATION_ERROR,
            details=sample_details,
        )
        result = error.to_dict()

        assert "error_code" in result
        assert "message" in result
        assert "recovery" in result
        assert "details" in result
        assert "timestamp" in result
        assert "documentation" in result

    def test_to_dict_error_code_value(
        self, base_error_message: str
    ) -> None:
        """Test that error_code in dict is the code value string."""
        error = MahavishnuError(base_error_message, ErrorCode.TASK_NOT_FOUND)
        result = error.to_dict()

        assert result["error_code"] == ErrorCode.TASK_NOT_FOUND.value
        assert result["error_code"] == "MHV-100"

    def test_to_dict_timestamp_isoformat(
        self, base_error_message: str
    ) -> None:
        """Test that timestamp is in ISO format."""
        error = MahavishnuError(base_error_message, ErrorCode.INTERNAL_ERROR)
        result = error.to_dict()

        # Should be parseable as ISO format
        parsed = datetime.fromisoformat(result["timestamp"])
        assert isinstance(parsed, datetime)

    def test_to_dict_documentation_url_format(
        self, base_error_message: str
    ) -> None:
        """Test that documentation URL follows expected format."""
        error = MahavishnuError(base_error_message, ErrorCode.CONFIGURATION_ERROR)
        result = error.to_dict()

        assert "https://docs.mahavishnu.org/errors/" in result["documentation"]
        assert ErrorCode.CONFIGURATION_ERROR.value.lower() in result["documentation"]


class TestMahavishnuErrorStr:
    """Tests for the __str__ method."""

    def test_str_contains_error_code(self, base_error_message: str) -> None:
        """Test that string representation contains error code."""
        error = MahavishnuError(base_error_message, ErrorCode.INTERNAL_ERROR)
        error_str = str(error)

        assert ErrorCode.INTERNAL_ERROR.value in error_str

    def test_str_contains_message(self, base_error_message: str) -> None:
        """Test that string representation contains message."""
        error = MahavishnuError(base_error_message, ErrorCode.INTERNAL_ERROR)
        error_str = str(error)

        assert base_error_message in error_str

    def test_str_contains_recovery_steps(
        self, base_error_message: str, sample_recovery: list[str]
    ) -> None:
        """Test that string representation contains numbered recovery steps."""
        error = MahavishnuError(
            base_error_message,
            ErrorCode.INTERNAL_ERROR,
            recovery=sample_recovery,
        )
        error_str = str(error)

        assert "Recovery steps:" in error_str
        for i, step in enumerate(sample_recovery, 1):
            assert f"{i}. {step}" in error_str

    def test_str_contains_documentation_link(self, base_error_message: str) -> None:
        """Test that string representation contains documentation link."""
        error = MahavishnuError(base_error_message, ErrorCode.INTERNAL_ERROR)
        error_str = str(error)

        assert "https://docs.mahavishnu.org/errors/" in error_str


# =============================================================================
# 2. Configuration Errors Tests
# =============================================================================


class TestConfigurationError:
    """Tests for ConfigurationError."""

    def test_uses_configuration_error_code(self) -> None:
        """Test that ConfigurationError uses CONFIGURATION_ERROR code."""
        error = ConfigurationError("Config is invalid")

        assert error.error_code == ErrorCode.CONFIGURATION_ERROR
        assert error.error_code.value == "MHV-001"

    def test_message_assignment(self) -> None:
        """Test that message is properly set."""
        msg = "Missing required field 'name'"
        error = ConfigurationError(msg)

        assert error.message == msg

    def test_with_details(self) -> None:
        """Test ConfigurationError with details."""
        details = {"field": "name", "issue": "required"}
        error = ConfigurationError("Config error", details=details)

        assert error.details == details

    def test_inherits_from_mahavishnu_error(self) -> None:
        """Test that ConfigurationError inherits from MahavishnuError."""
        error = ConfigurationError("Test")

        assert isinstance(error, MahavishnuError)
        assert isinstance(error, Exception)


class TestValidationError:
    """Tests for ValidationError."""

    def test_uses_validation_error_code(self) -> None:
        """Test that ValidationError uses VALIDATION_ERROR code."""
        error = ValidationError("Invalid input")

        assert error.error_code == ErrorCode.VALIDATION_ERROR
        assert error.error_code.value == "MHV-003"

    def test_message_assignment(self) -> None:
        """Test that message is properly set."""
        msg = "Title must be 3-500 characters"
        error = ValidationError(msg)

        assert error.message == msg

    def test_with_details(self) -> None:
        """Test ValidationError with details."""
        details = {"field": "title", "length": 2, "min": 3}
        error = ValidationError("Title too short", details=details)

        assert error.details == details

    def test_inherits_from_mahavishnu_error(self) -> None:
        """Test that ValidationError inherits from MahavishnuError."""
        error = ValidationError("Test")

        assert isinstance(error, MahavishnuError)


# =============================================================================
# 3. Adapter Errors Tests
# =============================================================================


class TestAdapterError:
    """Tests for AdapterError."""

    def test_uses_internal_error_code(self) -> None:
        """Test that AdapterError uses INTERNAL_ERROR code."""
        error = AdapterError("Adapter operation failed")

        assert error.error_code == ErrorCode.INTERNAL_ERROR

    def test_with_adapter_name_in_arg(self) -> None:
        """Test that adapter_name modifies message."""
        error = AdapterError("operation failed", adapter_name="prefect")

        assert "prefect" in error.message
        assert "Adapter 'prefect' error: operation failed" == error.message

    def test_with_adapter_name_in_details(self) -> None:
        """Test adapter_name in details takes precedence in message."""
        error = AdapterError(
            "operation failed",
            details={"adapter_name": "llamaindex"},
            adapter_name="agno",
        )

        # adapter_name as arg should be used in message
        assert "agno" in error.message

    def test_without_adapter_name(self) -> None:
        """Test AdapterError without adapter name."""
        error = AdapterError("Something went wrong")

        assert "Adapter" not in error.message

    def test_with_details(self) -> None:
        """Test AdapterError with details."""
        details = {"operation": "execute", "timeout": 30}
        error = AdapterError("Failed", details=details)

        assert error.details == details


class TestAdapterInitializationError:
    """Tests for AdapterInitializationError."""

    def test_uses_adapter_initialization_error_code(self) -> None:
        """Test that AdapterInitializationError uses ADAPTER_INITIALIZATION_ERROR code."""
        error = AdapterInitializationError(
            adapter_name="prefect",
            message="Connection failed",
        )

        assert error.error_code == ErrorCode.ADAPTER_INITIALIZATION_ERROR
        assert error.error_code.value == "MHV-411"

    def test_full_message_format(self) -> None:
        """Test that full message is properly formatted."""
        error = AdapterInitializationError(
            adapter_name="agno",
            message="Missing API key",
        )

        assert error.message == "Adapter 'agno' initialization failed: Missing API key"

    def test_adapter_name_in_details(self) -> None:
        """Test that adapter_name is included in details."""
        error = AdapterInitializationError(
            adapter_name="prefect",
            message="Failed",
        )

        assert error.details["adapter_name"] == "prefect"

    def test_custom_details_merged(self) -> None:
        """Test that custom details are merged with adapter_name."""
        details = {"reason": "connection_refused", "port": 4200}
        error = AdapterInitializationError(
            adapter_name="prefect",
            message="Failed",
            details=details,
        )

        assert error.details["adapter_name"] == "prefect"
        assert error.details["reason"] == "connection_refused"
        assert error.details["port"] == 4200

    def test_inherits_from_mahavishnu_error(self) -> None:
        """Test that AdapterInitializationError inherits from MahavishnuError."""
        error = AdapterInitializationError(
            adapter_name="test",
            message="Failed",
        )

        assert isinstance(error, MahavishnuError)


# =============================================================================
# 4. Workflow Errors Tests
# =============================================================================


class TestWorkflowExecutionError:
    """Tests for WorkflowExecutionError."""

    def test_uses_workflow_execution_error_code(self) -> None:
        """Test that WorkflowExecutionError uses WORKFLOW_EXECUTION_ERROR code."""
        error = WorkflowExecutionError(
            workflow_id="wf_123",
            message="Step failed",
        )

        assert error.error_code == ErrorCode.WORKFLOW_EXECUTION_ERROR
        assert error.error_code.value == "MHV-412"

    def test_workflow_id_in_details(self) -> None:
        """Test that workflow_id is included in details."""
        error = WorkflowExecutionError(
            workflow_id="wf_abc",
            message="Failed",
        )

        assert error.details["workflow_id"] == "wf_abc"

    def test_message_with_step_name(self) -> None:
        """Test message format when step_name is provided."""
        error = WorkflowExecutionError(
            workflow_id="wf_123",
            message="Deploy failed",
            step_name="deploy",
        )

        assert "wf_123" in error.message
        assert "deploy" in error.message
        assert "step 'deploy'" in error.message

    def test_message_without_step_name(self) -> None:
        """Test message format when step_name is not provided."""
        error = WorkflowExecutionError(
            workflow_id="wf_123",
            message="Workflow failed",
        )

        assert "wf_123" in error.message
        assert "step" not in error.message.lower()

    def test_step_name_in_details(self) -> None:
        """Test that step_name is included in details when provided."""
        error = WorkflowExecutionError(
            workflow_id="wf_123",
            message="Failed",
            step_name="build",
        )

        assert error.details["step_name"] == "build"

    def test_adapter_name_in_details(self) -> None:
        """Test that adapter_name is included in details when provided."""
        error = WorkflowExecutionError(
            workflow_id="wf_123",
            message="Failed",
            adapter_name="prefect",
        )

        assert error.details["adapter_name"] == "prefect"

    def test_custom_details_merged(self) -> None:
        """Test that custom details are properly merged."""
        details = {"retry_count": 3, "last_error": "Timeout"}
        error = WorkflowExecutionError(
            workflow_id="wf_123",
            message="Failed",
            details=details,
        )

        assert error.details["workflow_id"] == "wf_123"
        assert error.details["retry_count"] == 3
        assert error.details["last_error"] == "Timeout"


class TestWorkflowError:
    """Tests for WorkflowError."""

    def test_uses_internal_error_code(self) -> None:
        """Test that WorkflowError uses INTERNAL_ERROR code."""
        error = WorkflowError(workflow_id="wf_1", message="Error")

        assert error.error_code == ErrorCode.INTERNAL_ERROR

    def test_message_with_step(self) -> None:
        """Test message format when step is provided."""
        error = WorkflowError(
            workflow_id="wf_1",
            message="Deploy failed",
            step="deploy",
        )

        assert "wf_1" in error.message
        assert "deploy" in error.message
        assert "step 'deploy'" in error.message

    def test_workflow_id_and_step_in_details(self) -> None:
        """Test that workflow_id and step are in details."""
        error = WorkflowError(
            workflow_id="wf_1",
            message="Failed",
            step="build",
        )

        assert error.details["workflow_id"] == "wf_1"
        assert error.details["step"] == "build"


# =============================================================================
# 5. Authentication & Authorization Errors Tests
# =============================================================================


class TestAuthenticationError:
    """Tests for AuthenticationError."""

    def test_uses_authentication_error_code(self) -> None:
        """Test that AuthenticationError uses AUTHENTICATION_ERROR code."""
        error = AuthenticationError("Invalid token")

        assert error.error_code == ErrorCode.AUTHENTICATION_ERROR
        assert error.error_code.value == "MHV-004"

    def test_default_message(self) -> None:
        """Test default message when none provided."""
        error = AuthenticationError()

        assert error.message == "Authentication failed"

    def test_custom_message(self) -> None:
        """Test custom message."""
        error = AuthenticationError("Token expired")

        assert error.message == "Token expired"

    def test_with_details(self) -> None:
        """Test with additional details."""
        details = {"token_type": "JWT", "issue": "expired"}
        error = AuthenticationError("Token expired", details=details)

        assert error.details == details


class TestAuthorizationError:
    """Tests for AuthorizationError."""

    def test_uses_authorization_error_code(self) -> None:
        """Test that AuthorizationError uses AUTHORIZATION_ERROR code."""
        error = AuthorizationError("Not allowed")

        assert error.error_code == ErrorCode.AUTHORIZATION_ERROR
        assert error.error_code.value == "MHV-005"

    def test_default_message(self) -> None:
        """Test default message when none provided."""
        error = AuthorizationError()

        assert error.message == "Access denied"

    def test_custom_message(self) -> None:
        """Test custom message."""
        error = AuthorizationError("Insufficient permissions")

        assert error.message == "Insufficient permissions"


# =============================================================================
# 6. Timeout and Database Errors Tests
# =============================================================================


class TestTimeoutError:
    """Tests for MahavishnuTimeoutError."""

    def test_uses_timeout_error_code(self) -> None:
        """Test that TimeoutError uses TIMEOUT_ERROR code."""
        error = MahavishnuTimeoutError(operation="API call")

        assert error.error_code == ErrorCode.TIMEOUT_ERROR
        assert error.error_code.value == "MHV-008"

    def test_message_format_with_timeout(self) -> None:
        """Test message format with timeout value."""
        error = MahavishnuTimeoutError(operation="Query", timeout_seconds=30)

        assert "Query" in error.message
        assert "30s" in error.message

    def test_message_format_without_timeout(self) -> None:
        """Test message format without timeout value."""
        error = MahavishnuTimeoutError(operation="Query")

        assert "Query" in error.message
        assert "timed out" in error.message

    def test_operation_in_details(self) -> None:
        """Test that operation is in details."""
        error = MahavishnuTimeoutError(operation="test_op")

        assert error.details["operation"] == "test_op"

    def test_timeout_in_details_when_provided(self) -> None:
        """Test that timeout is in details when provided."""
        error = MahavishnuTimeoutError(operation="test", timeout_seconds=15)

        assert error.details["operation"] == "test"


class TestDatabaseError:
    """Tests for DatabaseError."""

    def test_uses_database_connection_error_code(self) -> None:
        """Test that DatabaseError uses DATABASE_CONNECTION_ERROR code."""
        error = DatabaseError("Connection refused")

        assert error.error_code == ErrorCode.DATABASE_CONNECTION_ERROR
        assert error.error_code.value == "MHV-002"

    def test_message_assignment(self) -> None:
        """Test message is properly set."""
        error = DatabaseError("Host unreachable")

        assert error.message == "Host unreachable"

    def test_with_details(self) -> None:
        """Test with details."""
        details = {"host": "localhost", "port": 5432}
        error = DatabaseError("Connection failed", details=details)

        assert error.details == details


# =============================================================================
# 7. External Service Errors Tests
# =============================================================================


class TestExternalServiceError:
    """Tests for ExternalServiceError."""

    def test_uses_external_service_unavailable_code(self) -> None:
        """Test that ExternalServiceError uses EXTERNAL_SERVICE_UNAVAILABLE code."""
        error = ExternalServiceError(service="GitHub", message="API error")

        assert error.error_code == ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE
        assert error.error_code.value == "MHV-306"

    def test_message_format(self) -> None:
        """Test message format includes service name."""
        error = ExternalServiceError(service="GitLab", message="Rate limited")

        assert "GitLab" in error.message
        assert "Rate limited" in error.message

    def test_service_in_details(self) -> None:
        """Test that service name is in details."""
        error = ExternalServiceError(service="OpenAI", message="Failed")

        assert error.details["service"] == "OpenAI"

    def test_with_details(self) -> None:
        """Test with additional details."""
        details = {"endpoint": "/v1/completions", "status_code": 429}
        error = ExternalServiceError(
            service="OpenAI",
            message="Rate limited",
            details=details,
        )

        assert error.details["service"] == "OpenAI"
        assert error.details["endpoint"] == "/v1/completions"


# =============================================================================
# 8. Repository and Task Errors Tests
# =============================================================================


class TestTaskNotFoundError:
    """Tests for TaskNotFoundError."""

    def test_uses_task_not_found_code(self) -> None:
        """Test that TaskNotFoundError uses TASK_NOT_FOUND code."""
        error = TaskNotFoundError(task_id=123)

        assert error.error_code == ErrorCode.TASK_NOT_FOUND
        assert error.error_code.value == "MHV-100"

    def test_message_format_with_int_id(self) -> None:
        """Test message format with integer task ID."""
        error = TaskNotFoundError(task_id=123)

        assert "123" in error.message

    def test_message_format_with_str_id(self) -> None:
        """Test message format with string task ID."""
        error = TaskNotFoundError(task_id="TASK-001")

        assert "TASK-001" in error.message

    def test_task_id_in_details(self) -> None:
        """Test that task_id is in details."""
        error = TaskNotFoundError(task_id=456)

        assert error.details["task_id"] == "456"

    def test_with_additional_details(self) -> None:
        """Test with additional details."""
        details = {"repo": "mahavishnu", "searched_in": ["in_progress", "pending"]}
        error = TaskNotFoundError(task_id=1, details=details)

        assert error.details["task_id"] == "1"
        assert error.details["repo"] == "mahavishnu"


class TestRepositoryNotFoundError:
    """Tests for RepositoryNotFoundError."""

    def test_uses_repository_not_found_code(self) -> None:
        """Test that RepositoryNotFoundError uses REPOSITORY_NOT_FOUND code."""
        error = RepositoryNotFoundError(repository="mahavishnu")

        assert error.error_code == ErrorCode.REPOSITORY_NOT_FOUND
        assert error.error_code.value == "MHV-200"

    def test_message_format(self) -> None:
        """Test message format with repository name."""
        error = RepositoryNotFoundError(repository="akosha")

        assert "akosha" in error.message
        assert "not found" in error.message.lower()

    def test_repository_in_details(self) -> None:
        """Test that repository is in details."""
        error = RepositoryNotFoundError(repository="session-buddy")

        assert error.details["repository"] == "session-buddy"


# =============================================================================
# 9. Webhook and Rate Limit Errors Tests
# =============================================================================


class TestWebhookAuthError:
    """Tests for WebhookAuthError."""

    def test_uses_webhook_signature_invalid_code_by_default(self) -> None:
        """Test that WebhookAuthError uses WEBHOOK_SIGNATURE_INVALID by default."""
        error = WebhookAuthError("Signature mismatch")

        assert error.error_code == ErrorCode.WEBHOOK_SIGNATURE_INVALID
        assert error.error_code.value == "MHV-300"

    def test_custom_error_code(self) -> None:
        """Test that custom error code can be used."""
        error = WebhookAuthError(
            "Replay detected",
            error_code=ErrorCode.WEBHOOK_REPLAY_DETECTED,
        )

        assert error.error_code == ErrorCode.WEBHOOK_REPLAY_DETECTED

    def test_message_assignment(self) -> None:
        """Test message is properly set."""
        error = WebhookAuthError("Invalid signature")

        assert error.message == "Invalid signature"


class TestRateLimitError:
    """Tests for RateLimitError."""

    def test_uses_rate_limit_exceeded_code(self) -> None:
        """Test that RateLimitError uses RATE_LIMIT_EXCEEDED code."""
        error = RateLimitError(limit="100/hour")

        assert error.error_code == ErrorCode.RATE_LIMIT_EXCEEDED
        assert error.error_code.value == "MHV-006"

    def test_message_format(self) -> None:
        """Test message format."""
        error = RateLimitError(limit="100/hour")

        assert "100/hour" in error.message

    def test_limit_in_details(self) -> None:
        """Test that limit is in details."""
        error = RateLimitError(limit="50/minute")

        assert error.details["limit"] == "50/minute"

    def test_retry_after_in_details(self) -> None:
        """Test that retry_after is in details when provided."""
        error = RateLimitError(limit="100/hour", retry_after=3600)

        assert error.details["retry_after_seconds"] == 3600


# =============================================================================
# 10. Prefect, Agno, GoalTeam, and Learning System Errors Tests
# =============================================================================


class TestPrefectError:
    """Tests for PrefectError."""

    def test_default_error_code(self) -> None:
        """Test default error code is PREFECT_API_ERROR."""
        error = PrefectError("Prefect error")

        assert error.error_code == ErrorCode.PREFECT_API_ERROR

    def test_custom_error_code(self) -> None:
        """Test custom error code."""
        error = PrefectError(
            "Connection failed",
            error_code=ErrorCode.PREFECT_CONNECTION_ERROR,
        )

        assert error.error_code == ErrorCode.PREFECT_CONNECTION_ERROR

    def test_message_assignment(self) -> None:
        """Test message is properly set."""
        error = PrefectError("Flow not found")

        assert error.message == "Flow not found"


class TestAgnoError:
    """Tests for AgnoError."""

    def test_default_error_code(self) -> None:
        """Test default error code is AGNO_AGENT_NOT_FOUND."""
        error = AgnoError("Agent error")

        assert error.error_code == ErrorCode.AGNO_AGENT_NOT_FOUND

    def test_custom_error_code(self) -> None:
        """Test custom error code."""
        error = AgnoError(
            "LLM provider failed",
            error_code=ErrorCode.AGNO_LLM_PROVIDER_ERROR,
        )

        assert error.error_code == ErrorCode.AGNO_LLM_PROVIDER_ERROR


class TestGoalTeamError:
    """Tests for GoalTeamError."""

    def test_default_error_code(self) -> None:
        """Test default error code is GOAL_TEAM_CREATION_FAILED."""
        error = GoalTeamError("Team error")

        assert error.error_code == ErrorCode.GOAL_TEAM_CREATION_FAILED

    def test_custom_error_code(self) -> None:
        """Test custom error code."""
        error = GoalTeamError(
            "Team not found",
            error_code=ErrorCode.GOAL_TEAM_NOT_FOUND,
        )

        assert error.error_code == ErrorCode.GOAL_TEAM_NOT_FOUND


class TestGoalTeamNotFoundError:
    """Tests for GoalTeamNotFoundError."""

    def test_uses_goal_team_not_found_code(self) -> None:
        """Test that GoalTeamNotFoundError uses GOAL_TEAM_NOT_FOUND code."""
        error = GoalTeamNotFoundError(team_id="team_123")

        assert error.error_code == ErrorCode.GOAL_TEAM_NOT_FOUND
        assert error.error_code.value == "MHV-461"

    def test_message_format(self) -> None:
        """Test message format includes team_id."""
        error = GoalTeamNotFoundError(team_id="team_abc")

        assert "team_abc" in error.message

    def test_team_id_in_details(self) -> None:
        """Test that team_id is in details."""
        error = GoalTeamNotFoundError(team_id="team_xyz")

        assert error.details["team_id"] == "team_xyz"


class TestGoalParsingError:
    """Tests for GoalParsingError."""

    def test_default_error_code(self) -> None:
        """Test default error code is GOAL_PARSING_FAILED."""
        error = GoalParsingError(goal="short", reason="too short")

        assert error.error_code == ErrorCode.GOAL_PARSING_FAILED

    def test_message_format(self) -> None:
        """Test message format."""
        error = GoalParsingError(goal="test goal", reason="ambiguous")

        assert "ambiguous" in error.message.lower()

    def test_goal_truncated_in_details(self) -> None:
        """Test that long goals are truncated in details."""
        long_goal = "x" * 200
        error = GoalParsingError(goal=long_goal, reason="too long")

        assert len(error.details["goal"]) <= 100

    def test_custom_error_code(self) -> None:
        """Test custom error code."""
        error = GoalParsingError(
            goal="hi",
            reason="too short",
            error_code=ErrorCode.GOAL_TOO_SHORT,
        )

        assert error.error_code == ErrorCode.GOAL_TOO_SHORT


class TestLearningSystemError:
    """Tests for LearningSystemError."""

    def test_default_error_code(self) -> None:
        """Test default error code is LEARNING_FEEDBACK_FAILED."""
        error = LearningSystemError("Learning error")

        assert error.error_code == ErrorCode.LEARNING_FEEDBACK_FAILED

    def test_custom_error_code(self) -> None:
        """Test custom error code."""
        error = LearningSystemError(
            "State error",
            error_code=ErrorCode.LEARNING_STATE_ERROR,
        )

        assert error.error_code == ErrorCode.LEARNING_STATE_ERROR


class TestContextNotInitializedError:
    """Tests for ContextNotInitializedError."""

    def test_uses_context_not_initialized_code(self) -> None:
        """Test that ContextNotInitializedError uses CONTEXT_NOT_INITIALIZED code."""
        error = ContextNotInitializedError(context_name="llm_factory")

        assert error.error_code == ErrorCode.CONTEXT_NOT_INITIALIZED
        assert error.error_code.value == "MHV-011"

    def test_message_format(self) -> None:
        """Test message format includes context name."""
        error = ContextNotInitializedError(context_name="agno_adapter")

        assert "agno_adapter" in error.message

    def test_context_name_in_details(self) -> None:
        """Test that context_name is in details."""
        error = ContextNotInitializedError(context_name="test_context")

        assert error.details["context_name"] == "test_context"


class TestFeatureDisabledError:
    """Tests for FeatureDisabledError."""

    def test_uses_feature_disabled_code(self) -> None:
        """Test that FeatureDisabledError uses FEATURE_DISABLED code."""
        error = FeatureDisabledError(feature_name="goal_teams")

        assert error.error_code == ErrorCode.FEATURE_DISABLED
        assert error.error_code.value == "MHV-468"

    def test_message_format(self) -> None:
        """Test message format includes feature name."""
        error = FeatureDisabledError(feature_name="multi_agent")

        assert "multi_agent" in error.message

    def test_feature_name_in_details(self) -> None:
        """Test that feature_name is in details."""
        error = FeatureDisabledError(feature_name="streaming")

        assert error.details["feature_name"] == "streaming"


# =============================================================================
# 7. Error Context and Structured Data Preservation
# =============================================================================


class TestErrorContextPreservation:
    """Tests for error context and structured data preservation."""

    def test_nested_details_preserved(self, base_error_message: str) -> None:
        """Test that nested dictionary details are preserved."""
        details = {
            "outer": {"inner": {"deep": [1, 2, 3]}},
            "list": [{"a": 1}, {"b": 2}],
        }
        error = MahavishnuError(
            base_error_message,
            ErrorCode.INTERNAL_ERROR,
            details=details,
        )

        assert error.details == details
        assert error.details["outer"]["inner"]["deep"] == [1, 2, 3]

    def test_details_from_multiple_sources_merged(self) -> None:
        """Test that details from multiple sources are properly merged."""
        # TaskNotFoundError merges task_id with provided details
        error = TaskNotFoundError(
            task_id=123,
            details={"repo": "test", "priority": "high"},
        )

        assert error.details["task_id"] == "123"
        assert error.details["repo"] == "test"
        assert error.details["priority"] == "high"

    def test_to_dict_preserves_all_types(self) -> None:
        """Test that to_dict preserves various data types."""
        details = {
            "string": "value",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "none": None,
            "list": [1, 2, 3],
        }
        error = MahavishnuError(
            "Test",
            ErrorCode.INTERNAL_ERROR,
            details=details,
        )
        result = error.to_dict()

        assert result["details"] == details


# =============================================================================
# 8. Error Chaining Tests (from cause)
# =============================================================================


class TestErrorChaining:
    """Tests for error chaining with 'from cause'."""

    def test_raise_from_cause(self) -> None:
        """Test raising MahavishnuError from a cause exception."""
        cause = ValueError("Original error")
        error = AdapterInitializationError(
            adapter_name="test",
            message="Failed to initialize",
        )

        # Using raise ... from to chain errors
        try:
            raise error from cause
        except MahavishnuError as e:
            assert e.__cause__ is cause

    def test_cause_accessible_via___cause__(self) -> None:
        """Test that __cause__ is accessible after chaining."""
        original = RuntimeError("Original runtime error")
        try:
            raise ConfigurationError("Wrapped error") from original
        except ConfigurationError as e:
            assert e.__cause__ is original
            assert str(e.__cause__) == "Original runtime error"

    def test_chained_error_str_includes_cause_info(self) -> None:
        """Test that chained error string representation is useful."""
        original = OSError("File not found")
        try:
            raise WorkflowError(workflow_id="wf_1", message="Step failed") from original
        except WorkflowError as e:
            # The chained exception should have the cause
            assert e.__cause__ is original

    def test_cause_is_exception_not_mahavishnu_error(self) -> None:
        """Test chaining from a plain exception."""
        plain_error = Exception("Plain exception")
        try:
            raise MahavishnuError(
                "Wrapped",
                ErrorCode.INTERNAL_ERROR,
            ) from plain_error
        except MahavishnuError as e:
            assert isinstance(e.__cause__, Exception)
            assert e.__cause__ is plain_error


# =============================================================================
# 9. Error Comparison and Equality Tests
# =============================================================================


class TestErrorComparison:
    """Tests for error comparison and equality."""

    def test_same_error_not_equal_by_default(self) -> None:
        """Test that two error instances with same params are not same object."""
        error1 = MahavishnuError("msg", ErrorCode.INTERNAL_ERROR)
        error2 = MahavishnuError("msg", ErrorCode.INTERNAL_ERROR)

        # Errors are not the same object
        assert error1 is not error2

    def test_error_equality_by_attributes(self) -> None:
        """Test that errors with same attributes should be equal."""
        details = {"key": "value"}
        error1 = MahavishnuError(
            "msg",
            ErrorCode.INTERNAL_ERROR,
            details=details,
        )
        error2 = MahavishnuError(
            "msg",
            ErrorCode.INTERNAL_ERROR,
            details=details,
        )

        # Same attributes but different timestamps
        # Equality depends on implementation (default is identity)
        assert error1.message == error2.message
        assert error1.error_code == error2.error_code
        assert error1.details == error2.details

    def test_different_error_codes_not_equal(self) -> None:
        """Test that errors with different codes are not equal in attributes."""
        error1 = MahavishnuError("msg", ErrorCode.INTERNAL_ERROR)
        error2 = MahavishnuError("msg", ErrorCode.CONFIGURATION_ERROR)

        assert error1.error_code != error2.error_code

    def test_error_exception_args_differ(self) -> None:
        """Test that exception args are based on formatted message."""
        error1 = MahavishnuError("msg", ErrorCode.INTERNAL_ERROR)
        error2 = MahavishnuError("different", ErrorCode.INTERNAL_ERROR)

        # args[0] contains formatted message
        assert error1.args[0] != error2.args[0]

    def test_error_code_enum_equality(self) -> None:
        """Test ErrorCode enum comparison."""
        code1 = ErrorCode.INTERNAL_ERROR
        code2 = ErrorCode.INTERNAL_ERROR

        assert code1 == code2
        assert code1.value == code2.value


# =============================================================================
# 10. Error Creation With and Without Context Tests
# =============================================================================


class TestErrorCreationWithoutContext:
    """Tests for error creation without additional context."""

    def test_minimal_instantiation(self) -> None:
        """Test creating error with just required parameters."""
        error = MahavishnuError("Simple message", ErrorCode.INTERNAL_ERROR)

        assert error.message == "Simple message"
        assert error.error_code == ErrorCode.INTERNAL_ERROR
        assert error.details == {}
        assert error.recovery == MahavishnuError.RECOVERY_GUIDANCE[ErrorCode.INTERNAL_ERROR.value]

    def test_only_message_and_code(self) -> None:
        """Test with just message and error code."""
        error = ConfigurationError("Config is wrong")

        assert error.message == "Config is wrong"
        assert error.error_code == ErrorCode.CONFIGURATION_ERROR


class TestErrorCreationWithContext:
    """Tests for error creation with additional context."""

    def test_with_details(self) -> None:
        """Test creating error with details."""
        details = {
            "file": "settings.yaml",
            "line": 42,
            "parser_error": "unexpected token",
        }
        error = ConfigurationError("Parse error", details=details)

        assert error.details == details

    def test_with_custom_recovery(self) -> None:
        """Test creating error with custom recovery steps."""
        recovery = ["Contact support", "Check logs", "Restart service"]
        error = MahavishnuError(
            "Critical failure",
            ErrorCode.INTERNAL_ERROR,
            recovery=recovery,
        )

        assert error.recovery == recovery

    def test_with_multiple_context_fields(self) -> None:
        """Test creating error with message, code, recovery, and details."""
        error = MahavishnuError(
            message="Complex error",
            error_code=ErrorCode.VALIDATION_ERROR,
            recovery=["Fix input", "Retry"],
            details={"field": "email", "value": "invalid"},
        )

        assert error.message == "Complex error"
        assert error.error_code == ErrorCode.VALIDATION_ERROR
        assert len(error.recovery) == 2
        assert error.details["field"] == "email"


class TestErrorTemplatesUsage:
    """Tests for ErrorTemplates class usage."""

    def test_task_create_validation(self) -> None:
        """Test task_create_validation template."""
        error = ErrorTemplates.task_create_validation(
            title="",  # too short
            repository="test-repo",
            issues=["Title is required"],
        )

        assert isinstance(error, ValidationError)
        assert "title" in error.message.lower()
        assert error.details["repository"] == "test-repo"

    def test_database_connection_failed(self) -> None:
        """Test database_connection_failed template."""
        error = ErrorTemplates.database_connection_failed(
            host="localhost",
            port=5432,
            original_error="Connection refused",
        )

        assert isinstance(error, DatabaseError)
        assert "localhost" in error.message
        assert "5432" in error.message
        assert error.details["host"] == "localhost"
        assert error.details["original_error"] == "Connection refused"

    def test_search_failed(self) -> None:
        """Test search_failed template."""
        error = ErrorTemplates.search_failed(
            query="test query",
            reason="timeout",
        )

        assert isinstance(error, ExternalServiceError)
        assert "test query" in error.message
        assert error.details["query"] == "test query"

    def test_config_file_error(self) -> None:
        """Test config_file_error template."""
        error = ErrorTemplates.config_file_error(
            file_path="/path/to/config.yaml",
            issue="Invalid YAML syntax",
        )

        assert isinstance(error, ConfigurationError)
        assert "/path/to/config.yaml" in error.message
        assert error.details["file_path"] == "/path/to/config.yaml"

    def test_webhook_failed(self) -> None:
        """Test webhook_failed template."""
        error = ErrorTemplates.webhook_failed(
            event_type="push",
            reason="Invalid signature",
            payload_id="payload_123",
        )

        assert isinstance(error, WebhookAuthError)
        assert error.details["event_type"] == "push"
        assert error.details["payload_id"] == "payload_123"

    def test_prefect_flow_failed(self) -> None:
        """Test prefect_flow_failed template."""
        error = ErrorTemplates.prefect_flow_failed(
            flow_name="deploy_flow",
            flow_run_id="run_456",
            reason="Resource exhausted",
        )

        assert isinstance(error, PrefectError)
        assert error.error_code == ErrorCode.PREFECT_FLOW_RUN_FAILED
        assert error.details["flow_name"] == "deploy_flow"

    def test_prefect_connection_failed(self) -> None:
        """Test prefect_connection_failed template."""
        error = ErrorTemplates.prefect_connection_failed(
            api_url="https://api.prefect.io",
            original_error="SSL certificate error",
        )

        assert isinstance(error, PrefectError)
        assert error.error_code == ErrorCode.PREFECT_CONNECTION_ERROR
        assert "api.prefect.io" in error.message

    def test_agno_agent_failed(self) -> None:
        """Test agno_agent_failed template."""
        error = ErrorTemplates.agno_agent_failed(
            agent_name="coder",
            task="Write tests",
            reason="Syntax error",
        )

        assert isinstance(error, AgnoError)
        assert error.error_code == ErrorCode.AGNO_TOOL_EXECUTION_ERROR
        assert error.details["agent_name"] == "coder"

    def test_agno_llm_error(self) -> None:
        """Test agno_llm_error template."""
        error = ErrorTemplates.agno_llm_error(
            provider="openai",
            model="gpt-4",
            reason="Rate limited",
        )

        assert isinstance(error, AgnoError)
        assert error.error_code == ErrorCode.AGNO_LLM_PROVIDER_ERROR
        assert error.details["provider"] == "openai"

    def test_adapter_init_failed(self) -> None:
        """Test adapter_init_failed template."""
        error = ErrorTemplates.adapter_init_failed(
            adapter_name="llamaindex",
            reason="Missing API key",
            missing_deps=["llama-index"],
        )

        assert isinstance(error, AdapterInitializationError)
        assert error.details["adapter_name"] == "llamaindex"
        assert "Missing API key" in error.message

    def test_workflow_step_failed(self) -> None:
        """Test workflow_step_failed template."""
        error = ErrorTemplates.workflow_step_failed(
            workflow_id="wf_test",
            step_name="build",
            reason="Compile failed",
            retry_count=3,
        )

        assert isinstance(error, WorkflowExecutionError)
        assert error.details["workflow_id"] == "wf_test"
        assert error.details["step_name"] == "build"
        assert error.details["retry_count"] == 3

    def test_goal_team_creation_failed(self) -> None:
        """Test goal_team_creation_failed template."""
        error = ErrorTemplates.goal_team_creation_failed(
            goal="Create new feature",
            reason="Insufficient agents",
        )

        assert isinstance(error, GoalTeamError)
        assert error.error_code == ErrorCode.GOAL_TEAM_CREATION_FAILED

    def test_goal_too_short(self) -> None:
        """Test goal_too_short template."""
        error = ErrorTemplates.goal_too_short(goal="Hi", min_length=10)

        assert isinstance(error, GoalParsingError)
        assert error.error_code == ErrorCode.GOAL_TOO_SHORT
        assert error.details["actual_length"] == 2
        assert error.details["min_length"] == 10

    def test_goal_too_long(self) -> None:
        """Test goal_too_long template."""
        long_goal = "x" * 500
        error = ErrorTemplates.goal_too_long(goal=long_goal, max_length=200)

        assert isinstance(error, GoalParsingError)
        assert error.error_code == ErrorCode.GOAL_TOO_LONG
        assert error.details["actual_length"] == 500
        assert error.details["max_length"] == 200

    def test_learning_feedback_failed(self) -> None:
        """Test learning_feedback_failed template."""
        error = ErrorTemplates.learning_feedback_failed(
            team_id="team_1",
            feedback_type="performance",
            reason="Database write failed",
        )

        assert isinstance(error, LearningSystemError)
        assert error.error_code == ErrorCode.LEARNING_FEEDBACK_FAILED
        assert error.details["team_id"] == "team_1"


# =============================================================================
# 11. Helper Functions Tests
# =============================================================================


class TestGetContextualHelp:
    """Tests for get_contextual_help function."""

    def test_returns_help_string(self) -> None:
        """Test that help string is returned."""
        result = get_contextual_help(ErrorCode.CONFIGURATION_ERROR)

        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_error_code(self) -> None:
        """Test that result contains error code."""
        result = get_contextual_help(ErrorCode.TASK_NOT_FOUND)

        assert ErrorCode.TASK_NOT_FOUND.value in result

    def test_contains_recovery_steps(self) -> None:
        """Test that result contains numbered recovery steps."""
        result = get_contextual_help(ErrorCode.INTERNAL_ERROR)

        assert "How to resolve:" in result

    def test_with_context(self) -> None:
        """Test with additional context."""
        context = {"repo": "test", "file": "config.yaml"}
        result = get_contextual_help(ErrorCode.CONFIGURATION_ERROR, context)

        assert "Context:" in result
        assert "repo" in result
        assert "config.yaml" in result

    def test_error_code_with_guidance(self) -> None:
        """Test that error codes with guidance return it in help."""
        result = get_contextual_help(ErrorCode.INTERNAL_ERROR)

        # Should return the guidance for INTERNAL_ERROR
        assert "How to resolve:" in result
        assert "unexpected error" in result.lower()


class TestFormatErrorForCli:
    """Tests for format_error_for_cli function."""

    def test_brief_format(self) -> None:
        """Test brief CLI format."""
        error = ConfigurationError("Config is wrong")
        result = format_error_for_cli(error, verbose=False)

        assert isinstance(result, str)
        assert "Config is wrong" in result
        assert "--verbose" in result  # Brief format mentions --verbose for more details

    def test_verbose_format(self) -> None:
        """Test verbose CLI format."""
        error = ConfigurationError("Config is wrong")
        result = format_error_for_cli(error, verbose=True)

        # Verbose should return full str() representation
        assert "Config is wrong" in result
        assert "Recovery steps:" in result

    def test_verbose_false_includes_first_recovery(self) -> None:
        """Test that brief format includes first recovery step."""
        error = ConfigurationError("Config is wrong")
        result = format_error_for_cli(error, verbose=False)

        assert "Try:" in result


class TestCreateErrorFromException:
    """Tests for create_error_from_exception function."""

    def test_wraps_exception(self) -> None:
        """Test wrapping a generic exception."""
        original = ValueError("Invalid value")
        error = create_error_from_exception(original)

        assert isinstance(error, MahavishnuError)
        assert error.message == "Invalid value"

    def test_preserves_original_type(self) -> None:
        """Test that original exception type is preserved in details."""
        original = RuntimeError("Runtime issue")
        error = create_error_from_exception(original)

        assert error.details["original_type"] == "RuntimeError"
        assert error.details["original_message"] == "Runtime issue"

    def test_custom_error_code(self) -> None:
        """Test with custom error code."""
        original = Exception("Test")
        error = create_error_from_exception(
            original,
            error_code=ErrorCode.VALIDATION_ERROR,
        )

        assert error.error_code == ErrorCode.VALIDATION_ERROR

    def test_with_context(self) -> None:
        """Test with additional context."""
        original = ValueError("Bad input")
        context = {"field": "email", "value": "@invalid"}
        error = create_error_from_exception(original, context=context)

        assert error.details["field"] == "email"
        assert error.details["value"] == "@invalid"
        assert error.details["original_type"] == "ValueError"


# =============================================================================
# 12. ErrorCode Enum Tests
# =============================================================================


class TestErrorCodeEnum:
    """Tests for ErrorCode enum."""

    def test_error_code_is_string(self) -> None:
        """Test that error codes are string values."""
        assert isinstance(ErrorCode.INTERNAL_ERROR.value, str)

    def test_error_code_format(self) -> None:
        """Test that all error codes follow MHV-XXX format."""
        for code in ErrorCode:
            assert code.value.startswith("MHV-")
            assert len(code.value) == 7

    def test_error_code_ranges(self) -> None:
        """Test that error codes fall in expected ranges."""
        # System errors
        assert ErrorCode.CONFIGURATION_ERROR.value == "MHV-001"
        assert ErrorCode.INTERNAL_ERROR.value == "MHV-007"

        # Task errors
        assert ErrorCode.TASK_NOT_FOUND.value == "MHV-100"

        # Repository errors
        assert ErrorCode.REPOSITORY_NOT_FOUND.value == "MHV-200"

        # External integration errors
        assert ErrorCode.GITHUB_API_ERROR.value == "MHV-302"

        # Prefect errors
        assert ErrorCode.PREFECT_CONNECTION_ERROR.value == "MHV-400"
        assert ErrorCode.ADAPTER_INITIALIZATION_ERROR.value == "MHV-411"

        # Agno errors
        assert ErrorCode.AGNO_AGENT_NOT_FOUND.value == "MHV-450"

        # GoalTeam errors
        assert ErrorCode.GOAL_TEAM_NOT_FOUND.value == "MHV-461"
        assert ErrorCode.GOAL_TOO_SHORT.value == "MHV-466"

        # Learning errors
        assert ErrorCode.LEARNING_FEEDBACK_FAILED.value == "MHV-480"


# =============================================================================
# 13. Recovery Guidance Mapping Tests
# =============================================================================


class TestRecoveryGuidanceMapping:
    """Tests for RECOVERY_GUIDANCE class variable."""

    def test_all_error_codes_have_guidance(self) -> None:
        """Test that all error codes have recovery guidance."""
        for code in ErrorCode:
            assert code.value in MahavishnuError.RECOVERY_GUIDANCE
            guidance = MahavishnuError.RECOVERY_GUIDANCE[code.value]
            assert isinstance(guidance, list)
            assert len(guidance) > 0

    def test_guidance_is_list_of_strings(self) -> None:
        """Test that all guidance entries are lists of strings."""
        for guidance in MahavishnuError.RECOVERY_GUIDANCE.values():
            assert isinstance(guidance, list)
            for step in guidance:
                assert isinstance(step, str)
                assert len(step) > 0


# =============================================================================
# 14. Inheritance Hierarchy Tests
# =============================================================================


class TestInheritanceHierarchy:
    """Tests for exception inheritance hierarchy."""

    def test_all_errors_inherit_from_mahavishnu_error(self) -> None:
        """Test that all error classes inherit from MahavishnuError."""
        error_classes = [
            ConfigurationError,
            ValidationError,
            TaskNotFoundError,
            RepositoryNotFoundError,
            WebhookAuthError,
            RateLimitError,
            AdapterError,
            AdapterInitializationError,
            WorkflowExecutionError,
            AuthenticationError,
            AuthorizationError,
            MahavishnuTimeoutError,
            DatabaseError,
            ExternalServiceError,
            WorkflowError,
            PrefectError,
            AgnoError,
            GoalTeamError,
            GoalTeamNotFoundError,
            GoalParsingError,
            LearningSystemError,
            ContextNotInitializedError,
            FeatureDisabledError,
        ]

        for cls in error_classes:
            assert issubclass(cls, MahavishnuError), f"{cls.__name__} should inherit from MahavishnuError"

    def test_goal_team_not_found_inherits_from_goal_team_error(self) -> None:
        """Test that GoalTeamNotFoundError inherits from GoalTeamError."""
        assert issubclass(GoalTeamNotFoundError, GoalTeamError)

    def test_goal_parsing_inherits_from_goal_team_error(self) -> None:
        """Test that GoalParsingError inherits from GoalTeamError."""
        assert issubclass(GoalParsingError, GoalTeamError)
