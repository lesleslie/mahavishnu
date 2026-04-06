"""Comprehensive tests for error handling hierarchy and helpers.

Tests cover:
- ErrorCode enum values and coverage
- MahavishnuError base class (to_dict, __str__, recovery guidance)
- All convenience exception classes
- ErrorTemplates factory methods
- Helper functions (get_contextual_help, format_error_for_cli, create_error_from_exception)
"""

import re
from datetime import datetime, timezone

import pytest

from mahavishnu.core.errors import (
    AdapterError,
    AdapterInitializationError,
    AgnoError,
    AuthenticationError,
    AuthorizationError,
    ConfigurationError,
    ContextNotInitializedError,
    DatabaseError,
    ErrorCode,
    ErrorTemplates,
    ExternalServiceError,
    FeatureDisabledError,
    GoalParsingError,
    GoalTeamError,
    GoalTeamNotFoundError,
    LearningSystemError,
    MahavishnuError,
    PrefectError,
    RateLimitError,
    RepositoryNotFoundError,
    TaskNotFoundError,
    TimeoutError,
    ValidationError,
    WebhookAuthError,
    WorkflowError,
    WorkflowExecutionError,
    create_error_from_exception,
    format_error_for_cli,
    get_contextual_help,
)


# ============================================================================
# ErrorCode Enum Tests
# ============================================================================


class TestErrorCode:
    """Test ErrorCode enum."""

    def test_all_codes_have_mhv_prefix(self):
        """Every error code should start with MHV-."""
        for code in ErrorCode:
            assert code.value.startswith("MHV-"), f"{code.name} missing MHV- prefix"

    def test_system_errors_range(self):
        """System errors should be MHV-001 to MHV-099."""
        system_codes = [
            ErrorCode.CONFIGURATION_ERROR,
            ErrorCode.DATABASE_CONNECTION_ERROR,
            ErrorCode.VALIDATION_ERROR,
            ErrorCode.AUTHENTICATION_ERROR,
            ErrorCode.AUTHORIZATION_ERROR,
            ErrorCode.RATE_LIMIT_EXCEEDED,
            ErrorCode.INTERNAL_ERROR,
            ErrorCode.TIMEOUT_ERROR,
            ErrorCode.RESOURCE_NOT_FOUND,
            ErrorCode.OPERATION_CANCELLED,
            ErrorCode.CONTEXT_NOT_INITIALIZED,
        ]
        for code in system_codes:
            num = int(code.value.split("-")[1])
            assert 1 <= num <= 99, f"{code.name} ({code.value}) outside system range"

    def test_task_errors_range(self):
        """Task errors should be MHV-100 to MHV-199."""
        task_codes = [
            ErrorCode.TASK_NOT_FOUND,
            ErrorCode.TASK_CREATION_FAILED,
            ErrorCode.TASK_UPDATE_FAILED,
            ErrorCode.TASK_DELETION_FAILED,
            ErrorCode.TASK_ALREADY_COMPLETED,
            ErrorCode.TASK_BLOCKED,
            ErrorCode.TASK_INVALID_STATUS,
            ErrorCode.TASK_DEADLINE_PASSED,
            ErrorCode.TASK_ASSIGNMENT_FAILED,
            ErrorCode.TASK_DEPENDENCY_CYCLE,
        ]
        for code in task_codes:
            num = int(code.value.split("-")[1])
            assert 100 <= num <= 199, f"{code.name} ({code.value}) outside task range"

    def test_repository_errors_range(self):
        """Repository errors should be MHV-200 to MHV-299."""
        repo_codes = [
            ErrorCode.REPOSITORY_NOT_FOUND,
            ErrorCode.REPOSITORY_NOT_CONFIGURED,
            ErrorCode.WORKTREE_CREATION_FAILED,
            ErrorCode.WORKTREE_NOT_FOUND,
            ErrorCode.WORKTREE_CLEANUP_FAILED,
            ErrorCode.REPOSITORY_CLONE_FAILED,
            ErrorCode.REPOSITORY_ACCESS_DENIED,
        ]
        for code in repo_codes:
            num = int(code.value.split("-")[1])
            assert 200 <= num <= 299, f"{code.name} ({code.value}) outside repo range"

    def test_enum_is_str(self):
        """ErrorCode should be usable as strings."""
        assert isinstance(ErrorCode.CONFIGURATION_ERROR, str)
        assert ErrorCode.CONFIGURATION_ERROR == "MHV-001"

    def test_all_codes_have_recovery_guidance(self):
        """Most error codes should have recovery guidance."""
        # These are the primary codes that should have guidance
        critical_codes = [
            ErrorCode.CONFIGURATION_ERROR,
            ErrorCode.VALIDATION_ERROR,
            ErrorCode.AUTHENTICATION_ERROR,
            ErrorCode.TASK_NOT_FOUND,
            ErrorCode.REPOSITORY_NOT_FOUND,
            ErrorCode.PREFECT_CONNECTION_ERROR,
            ErrorCode.WORKFLOW_EXECUTION_ERROR,
        ]
        for code in critical_codes:
            assert code in MahavishnuError.RECOVERY_GUIDANCE or code.value in [
                v.value for v in MahavishnuError.RECOVERY_GUIDANCE
            ], f"{code.name} missing recovery guidance"

    def test_total_error_code_count(self):
        """Should have a reasonable number of error codes."""
        # The module defines ~50+ error codes
        assert len(ErrorCode) >= 40


# ============================================================================
# MahavishnuError Base Class Tests
# ============================================================================


class TestMahavishnuError:
    """Test MahavishnuError base exception."""

    def test_basic_creation(self):
        err = MahavishnuError("Something broke", ErrorCode.INTERNAL_ERROR)
        assert err.message == "Something broke"
        assert err.error_code == ErrorCode.INTERNAL_ERROR
        assert err.details == {}

    def test_with_details(self):
        err = MahavishnuError(
            "Task failed",
            ErrorCode.TASK_NOT_FOUND,
            details={"task_id": "abc123"},
        )
        assert err.details == {"task_id": "abc123"}

    def test_with_custom_recovery(self):
        custom_recovery = ["Step 1", "Step 2"]
        err = MahavishnuError(
            "Custom error",
            ErrorCode.INTERNAL_ERROR,
            recovery=custom_recovery,
        )
        assert err.recovery == custom_recovery

    def test_default_recovery_from_guidance(self):
        err = MahavishnuError("Config bad", ErrorCode.CONFIGURATION_ERROR)
        # Should use RECOVERY_GUIDANCE for this code
        assert len(err.recovery) > 0
        assert "repos.yaml" in err.recovery[0] or "validate" in err.recovery[0].lower()

    def test_unknown_code_gets_default_recovery(self):
        err = MahavishnuError("Unknown", ErrorCode.INTERNAL_ERROR)
        assert len(err.recovery) > 0  # Has guidance for INTERNAL_ERROR

    def test_to_dict(self):
        err = MahavishnuError(
            "Test error",
            ErrorCode.VALIDATION_ERROR,
            details={"field": "name"},
        )
        d = err.to_dict()

        assert d["error_code"] == "MHV-003"
        assert d["message"] == "Test error"
        assert d["details"] == {"field": "name"}
        assert "recovery" in d
        assert "timestamp" in d
        assert "documentation" in d
        assert d["documentation"].endswith("/mhv-003")

    def test_timestamp_is_utc(self):
        err = MahavishnuError("test", ErrorCode.INTERNAL_ERROR)
        assert err.timestamp.tzinfo is not None

    def test_str_format(self):
        err = MahavishnuError("Test error", ErrorCode.VALIDATION_ERROR)
        s = str(err)
        assert "MHV-003" in s
        assert "Test error" in s
        assert "Recovery steps" in s
        assert "docs.mahavishnu.org" in s

    def test_is_exception(self):
        err = MahavishnuError("test", ErrorCode.INTERNAL_ERROR)
        assert isinstance(err, Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(MahavishnuError) as exc_info:
            raise MahavishnuError("boom", ErrorCode.INTERNAL_ERROR)
        assert exc_info.value.message == "boom"


# ============================================================================
# Convenience Exception Classes Tests
# ============================================================================


class TestConfigurationError:
    def test_creates_with_mhv001(self):
        err = ConfigurationError("Bad config")
        assert err.error_code == ErrorCode.CONFIGURATION_ERROR
        assert err.error_code.value == "MHV-001"
        assert "Bad config" in str(err)

    def test_with_details(self):
        err = ConfigurationError("Bad config", details={"file": "test.yaml"})
        assert err.details["file"] == "test.yaml"


class TestValidationError:
    def test_creates_with_mhv003(self):
        err = ValidationError("Invalid input")
        assert err.error_code == ErrorCode.VALIDATION_ERROR
        assert err.error_code.value == "MHV-003"


class TestTaskNotFoundError:
    def test_includes_task_id(self):
        err = TaskNotFoundError(task_id="abc123")
        assert "abc123" in err.message
        assert err.details["task_id"] == "abc123"
        assert err.error_code == ErrorCode.TASK_NOT_FOUND

    def test_numeric_task_id(self):
        err = TaskNotFoundError(task_id=42)
        assert err.details["task_id"] == "42"


class TestRepositoryNotFoundError:
    def test_includes_repository_name(self):
        err = RepositoryNotFoundError("mahavishnu")
        assert "mahavishnu" in err.message
        assert err.details["repository"] == "mahavishnu"
        assert err.error_code == ErrorCode.REPOSITORY_NOT_FOUND


class TestWebhookAuthError:
    def test_default_code(self):
        err = WebhookAuthError("Bad signature")
        assert err.error_code == ErrorCode.WEBHOOK_SIGNATURE_INVALID

    def test_custom_code(self):
        err = WebhookAuthError(
            "Replay detected",
            error_code=ErrorCode.WEBHOOK_REPLAY_DETECTED,
        )
        assert err.error_code == ErrorCode.WEBHOOK_REPLAY_DETECTED


class TestRateLimitError:
    def test_basic(self):
        err = RateLimitError("100 req/min")
        assert "100 req/min" in err.message
        assert err.details["limit"] == "100 req/min"
        assert "retry_after" not in err.details

    def test_with_retry_after(self):
        err = RateLimitError("100 req/min", retry_after=60)
        assert err.details["retry_after_seconds"] == 60


class TestAdapterError:
    def test_without_adapter_name(self):
        err = AdapterError("Connection failed")
        assert "Connection failed" in err.message

    def test_with_adapter_name(self):
        err = AdapterError("Connection failed", adapter_name="prefect")
        assert "prefect" in err.message


class TestAdapterInitializationError:
    def test_message_format(self):
        err = AdapterInitializationError("prefect", "Missing dependency")
        assert "prefect" in err.message
        assert "initialization failed" in err.message
        assert err.error_code == ErrorCode.ADAPTER_INITIALIZATION_ERROR
        assert err.details["adapter_name"] == "prefect"

    def test_with_details(self):
        err = AdapterInitializationError(
            "agno",
            "No API key",
            details={"missing_deps": ["agno"]},
        )
        assert err.details["missing_deps"] == ["agno"]


class TestWorkflowExecutionError:
    def test_without_step(self):
        err = WorkflowExecutionError("wf_123", "Execution failed")
        assert "wf_123" in err.message
        assert "Execution failed" in err.message
        assert err.details["workflow_id"] == "wf_123"

    def test_with_step(self):
        err = WorkflowExecutionError(
            "wf_123", "Deploy failed", step_name="deploy"
        )
        assert "deploy" in err.message
        assert err.details["step_name"] == "deploy"

    def test_with_adapter(self):
        err = WorkflowExecutionError(
            "wf_123", "Failed", adapter_name="prefect"
        )
        assert err.details["adapter_name"] == "prefect"


class TestAuthenticationError:
    def test_default_message(self):
        err = AuthenticationError()
        assert err.message == "Authentication failed"
        assert err.error_code == ErrorCode.AUTHENTICATION_ERROR

    def test_custom_message(self):
        err = AuthenticationError("Token expired")
        assert err.message == "Token expired"


class TestAuthorizationError:
    def test_default_message(self):
        err = AuthorizationError()
        assert err.message == "Access denied"
        assert err.error_code == ErrorCode.AUTHORIZATION_ERROR


class TestTimeoutErrorClass:
    def test_basic(self):
        err = TimeoutError("api_call")
        assert "api_call" in err.message
        assert err.details["operation"] == "api_call"

    def test_with_timeout_seconds(self):
        err = TimeoutError("api_call", timeout_seconds=30.0)
        assert "30.0s" in err.message


class TestDatabaseError:
    def test_creation(self):
        err = DatabaseError("Connection refused")
        assert err.error_code == ErrorCode.DATABASE_CONNECTION_ERROR
        assert "Connection refused" in err.message


class TestExternalServiceError:
    def test_service_included(self):
        err = ExternalServiceError("github", "Rate limited")
        assert "github" in err.message
        assert err.details["service"] == "github"


class TestWorkflowError:
    def test_without_step(self):
        err = WorkflowError("wf_1", "Generic error")
        assert "wf_1" in err.message

    def test_with_step(self):
        err = WorkflowError("wf_1", "Step error", step="build")
        assert "build" in err.message


class TestPrefectError:
    def test_default_code(self):
        err = PrefectError("Flow failed")
        assert err.error_code == ErrorCode.PREFECT_API_ERROR

    def test_custom_code(self):
        err = PrefectError("Timeout", error_code=ErrorCode.PREFECT_TIMEOUT)
        assert err.error_code == ErrorCode.PREFECT_TIMEOUT


class TestAgnoError:
    def test_default_code(self):
        err = AgnoError("Agent failed")
        assert err.error_code == ErrorCode.AGNO_AGENT_NOT_FOUND


class TestGoalTeamError:
    def test_default_code(self):
        err = GoalTeamError("Team creation failed")
        assert err.error_code == ErrorCode.GOAL_TEAM_CREATION_FAILED


class TestGoalTeamNotFoundError:
    def test_includes_team_id(self):
        err = GoalTeamNotFoundError("team_abc")
        assert "team_abc" in err.message
        assert err.error_code == ErrorCode.GOAL_TEAM_NOT_FOUND


class TestGoalParsingError:
    def test_basic(self):
        err = GoalParsingError("my goal", "Too vague")
        assert err.details["goal"] == "my goal"
        assert err.details["reason"] == "Too vague"

    def test_goal_truncated(self):
        long_goal = "x" * 200
        err = GoalParsingError(long_goal, "Too long")
        assert len(err.details["goal"]) == 100  # Truncated to 100 chars


class TestLearningSystemError:
    def test_default_code(self):
        err = LearningSystemError("Feedback failed")
        assert err.error_code == ErrorCode.LEARNING_FEEDBACK_FAILED


class TestContextNotInitializedError:
    def test_includes_context_name(self):
        err = ContextNotInitializedError("llm_factory")
        assert "llm_factory" in err.message
        assert err.details["context_name"] == "llm_factory"
        assert err.error_code == ErrorCode.CONTEXT_NOT_INITIALIZED


class TestFeatureDisabledError:
    def test_includes_feature_name(self):
        err = FeatureDisabledError("goal_teams")
        assert "goal_teams" in err.message
        assert err.details["feature_name"] == "goal_teams"
        assert err.error_code == ErrorCode.FEATURE_DISABLED


# ============================================================================
# ErrorTemplates Tests
# ============================================================================


class TestErrorTemplates:
    def test_task_create_validation(self):
        err = ErrorTemplates.task_create_validation(
            "My Task", "test-repo", ["title too short"]
        )
        assert isinstance(err, ValidationError)
        assert err.details["title"] == "My Task"
        assert err.details["repository"] == "test-repo"
        assert "title too short" in err.details["issues"]

    def test_database_connection_failed(self):
        err = ErrorTemplates.database_connection_failed(
            "localhost", 5432, "Connection refused"
        )
        assert isinstance(err, DatabaseError)
        assert "localhost" in err.message
        assert err.details["host"] == "localhost"
        assert err.details["port"] == 5432

    def test_search_failed(self):
        err = ErrorTemplates.search_failed("python async", "Timeout")
        assert isinstance(err, ExternalServiceError)
        assert "python async" in err.message

    def test_config_file_error(self):
        err = ErrorTemplates.config_file_error("/etc/config.yaml", "Parse error")
        assert isinstance(err, ConfigurationError)
        assert "/etc/config.yaml" in err.message

    def test_webhook_failed(self):
        err = ErrorTemplates.webhook_failed(
            "push", "Invalid signature", payload_id="abc"
        )
        assert isinstance(err, WebhookAuthError)
        assert err.details["payload_id"] == "abc"

    def test_webhook_failed_without_payload_id(self):
        err = ErrorTemplates.webhook_failed("push", "Invalid sig")
        assert "payload_id" not in err.details

    def test_prefect_flow_failed(self):
        err = ErrorTemplates.prefect_flow_failed(
            "my-flow", "run_123", "Timeout"
        )
        assert isinstance(err, PrefectError)
        assert err.error_code == ErrorCode.PREFECT_FLOW_RUN_FAILED
        assert "my-flow" in err.message

    def test_prefect_connection_failed(self):
        err = ErrorTemplates.prefect_connection_failed(
            "http://localhost:4200", "Connection refused"
        )
        assert err.error_code == ErrorCode.PREFECT_CONNECTION_ERROR

    def test_agno_agent_failed(self):
        err = ErrorTemplates.agno_agent_failed("coder", "build", "OOM")
        assert isinstance(err, AgnoError)
        assert err.error_code == ErrorCode.AGNO_TOOL_EXECUTION_ERROR

    def test_agno_llm_error(self):
        err = ErrorTemplates.agno_llm_error("ollama", "qwen2.5", "No model")
        assert err.error_code == ErrorCode.AGNO_LLM_PROVIDER_ERROR

    def test_adapter_init_failed(self):
        err = ErrorTemplates.adapter_init_failed(
            "prefect", "No API key", missing_deps=["prefect"]
        )
        assert isinstance(err, AdapterInitializationError)
        assert err.details["missing_deps"] == ["prefect"]

    def test_adapter_init_failed_with_config_issues(self):
        err = ErrorTemplates.adapter_init_failed(
            "agno", "Bad config", config_issues=["missing url"]
        )
        assert err.details["config_issues"] == ["missing url"]

    def test_workflow_step_failed(self):
        err = ErrorTemplates.workflow_step_failed(
            "wf_1", "build", "Compile error", retry_count=3
        )
        assert isinstance(err, WorkflowExecutionError)
        assert err.details["retry_count"] == 3

    def test_goal_team_creation_failed(self):
        err = ErrorTemplates.goal_team_creation_failed(
            "Build the API", "No agents available"
        )
        assert isinstance(err, GoalTeamError)
        assert len(err.details["goal"]) <= 100

    def test_goal_too_short(self):
        err = ErrorTemplates.goal_too_short("hi", min_length=10)
        assert isinstance(err, GoalParsingError)
        assert err.error_code == ErrorCode.GOAL_TOO_SHORT
        assert err.details["actual_length"] == 2
        assert err.details["min_length"] == 10

    def test_goal_too_long(self):
        long_goal = "x" * 5000
        err = ErrorTemplates.goal_too_long(long_goal, max_length=2000)
        assert err.error_code == ErrorCode.GOAL_TOO_LONG
        assert err.details["actual_length"] == 5000

    def test_learning_feedback_failed(self):
        err = ErrorTemplates.learning_feedback_failed(
            "team_1", "positive", "DB error"
        )
        assert isinstance(err, LearningSystemError)
        assert "team_1" in err.message


# ============================================================================
# Helper Function Tests
# ============================================================================


class TestGetContextualHelp:
    def test_returns_help_string(self):
        help_text = get_contextual_help(ErrorCode.CONFIGURATION_ERROR)
        assert "CONFIGURATION ERROR" in help_text
        assert "MHV-001" in help_text
        assert "How to resolve" in help_text
        assert "docs.mahavishnu.org" in help_text

    def test_with_context(self):
        help_text = get_contextual_help(
            ErrorCode.TASK_NOT_FOUND, context={"task_id": "abc"}
        )
        assert "abc" in help_text
        assert "task_id" in help_text

    def test_unknown_code_gets_default_help(self):
        # Use a code that might not have specific guidance
        help_text = get_contextual_help(ErrorCode.INTERNAL_ERROR)
        assert "INTERNAL ERROR" in help_text


class TestFormatErrorForCli:
    def test_brief_format(self):
        err = MahavishnuError("Something broke", ErrorCode.INTERNAL_ERROR)
        output = format_error_for_cli(err, verbose=False)
        assert "MHV-007" in output
        assert "Something broke" in output
        assert "--verbose" in output

    def test_verbose_format(self):
        err = MahavishnuError("Something broke", ErrorCode.INTERNAL_ERROR)
        output = format_error_for_cli(err, verbose=True)
        # Verbose format is the full __str__
        assert "MHV-007" in output
        assert "Recovery steps" in output

    def test_brief_includes_first_recovery(self):
        err = ConfigurationError("Bad config")
        output = format_error_for_cli(err, verbose=False)
        assert "Try:" in output


class TestCreateErrorFromException:
    def test_wraps_generic_exception(self):
        original = ValueError("bad value")
        err = create_error_from_exception(original)
        assert isinstance(err, MahavishnuError)
        assert err.message == "bad value"
        assert err.error_code == ErrorCode.INTERNAL_ERROR
        assert err.details["original_type"] == "ValueError"

    def test_custom_error_code(self):
        original = ConnectionError("timeout")
        err = create_error_from_exception(
            original, error_code=ErrorCode.DATABASE_CONNECTION_ERROR
        )
        assert err.error_code == ErrorCode.DATABASE_CONNECTION_ERROR

    def test_with_context(self):
        original = RuntimeError("test")
        err = create_error_from_exception(
            original, context={"adapter": "prefect"}
        )
        assert err.details["adapter"] == "prefect"
        assert err.details["original_type"] == "RuntimeError"

    def test_preserves_original_message(self):
        original = OSError("File not found")
        err = create_error_from_exception(original)
        assert err.details["original_message"] == "File not found"
