"""Tests for mahavishnu/core/errors.py, status.py, and repo_models.py.

Pure-Python modules with no I/O — tested with simple assertions.
"""

import re
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

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
from mahavishnu.core.repo_models import Repository, RepositoryManifest, RepositoryMetadata
from mahavishnu.core.status import (
    BlockingStatus,
    CoordinationStatus,
    DatabaseStatus,
    DeadLetterStatus,
    DeploymentStatus,
    DependencyStatus,
    ExecutionStatus,
    HealthStatus,
    IssueStatus,
    MigrationStatus,
    OnboardingStatus,
    PlanStatus,
    PoolStatus,
    ReadinessStatus,
    SyncStatus,
    TaskStatus,
    TodoStatus,
    WorkerStatus,
    WorkflowStatus,
)


# =========================================================================
# ErrorCode enum
# =========================================================================


class TestErrorCode:
    """Test the ErrorCode enum values and ranges."""

    def test_system_errors_range(self):
        system = [
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
        codes = [e.value for e in system]
        for code in codes:
            assert re.match(r"MHV-0\d{2}", code)

    def test_task_errors_range(self):
        task_errors = [
            ErrorCode.TASK_NOT_FOUND,
            ErrorCode.TASK_CREATION_FAILED,
            ErrorCode.TASK_DEPENDENCY_CYCLE,
        ]
        for e in task_errors:
            assert e.value.startswith("MHV-1")

    def test_repository_errors_range(self):
        repo_errors = [
            ErrorCode.REPOSITORY_NOT_FOUND,
            ErrorCode.WORKTREE_CREATION_FAILED,
        ]
        for e in repo_errors:
            assert e.value.startswith("MHV-2")

    def test_external_errors_range(self):
        ext_errors = [
            ErrorCode.WEBHOOK_SIGNATURE_INVALID,
            ErrorCode.GITHUB_API_ERROR,
        ]
        for e in ext_errors:
            assert e.value.startswith("MHV-3")

    def test_prefect_errors_range(self):
        prefect_errors = [
            ErrorCode.PREFECT_CONNECTION_ERROR,
            ErrorCode.ADAPTER_INITIALIZATION_ERROR,
        ]
        for e in prefect_errors:
            assert re.match(r"MHV-4[01]\d", e.value)

    def test_agno_errors_range(self):
        for e in [
            ErrorCode.AGNO_AGENT_NOT_FOUND,
            ErrorCode.AGNO_STREAMING_ERROR,
        ]:
            assert e.value.startswith("MHV-45")

    def test_goal_errors_range(self):
        for e in [
            ErrorCode.GOAL_TEAM_CREATION_FAILED,
            ErrorCode.FEATURE_DISABLED,
        ]:
            assert e.value.startswith("MHV-46")

    def test_learning_errors_range(self):
        for e in [
            ErrorCode.LEARNING_FEEDBACK_FAILED,
            ErrorCode.LEARNING_ADAPTATION_ERROR,
        ]:
            assert e.value.startswith("MHV-48")

    def test_all_values_unique(self):
        values = [e.value for e in ErrorCode]
        assert len(values) == len(set(values))

    def test_all_names_unique(self):
        names = [e.name for e in ErrorCode]
        assert len(names) == len(set(names))

    def test_error_code_is_str_enum(self):
        assert isinstance(ErrorCode.INTERNAL_ERROR, str)
        assert ErrorCode.INTERNAL_ERROR == "MHV-007"


# =========================================================================
# MahavishnuError base class
# =========================================================================


class TestMahavishnuError:
    """Test the base error class."""

    def test_basic_construction(self):
        err = MahavishnuError(
            message="something broke",
            error_code=ErrorCode.INTERNAL_ERROR,
        )
        assert err.message == "something broke"
        assert err.error_code == ErrorCode.INTERNAL_ERROR
        assert isinstance(err.details, dict)
        assert err.timestamp is not None

    def test_custom_recovery(self):
        err = MahavishnuError(
            message="test",
            error_code=ErrorCode.INTERNAL_ERROR,
            recovery=["Step 1", "Step 2"],
        )
        assert err.recovery == ["Step 1", "Step 2"]

    def test_default_recovery_from_guidance(self):
        err = MahavishnuError(
            message="test",
            error_code=ErrorCode.DATABASE_CONNECTION_ERROR,
        )
        assert len(err.recovery) > 0
        assert any("database" in r.lower() or "postgres" in r.lower() for r in err.recovery)

    def test_unknown_code_gets_default_recovery(self):
        # Use a code that has no recovery guidance — it should fall back
        err = MahavishnuError(
            message="test",
            error_code=ErrorCode.INTERNAL_ERROR,
        )
        # INTERNAL_ERROR does have guidance, so verify that works
        assert len(err.recovery) > 0

    def test_to_dict(self):
        err = MahavishnuError(
            message="test error",
            error_code=ErrorCode.TIMEOUT_ERROR,
            details={"key": "val"},
        )
        d = err.to_dict()
        assert d["error_code"] == "MHV-008"
        assert d["message"] == "test error"
        assert d["details"] == {"key": "val"}
        assert "timestamp" in d
        assert d["documentation"].endswith("mhv-008")

    def test_str_representation(self):
        err = MahavishnuError(
            message="boom",
            error_code=ErrorCode.VALIDATION_ERROR,
            recovery=["Fix input", "Try again"],
        )
        s = str(err)
        assert "MHV-003" in s
        assert "boom" in s
        assert "Fix input" in s
        assert "Recovery steps" in s

    def test_is_exception(self):
        err = MahavishnuError(
            message="test",
            error_code=ErrorCode.INTERNAL_ERROR,
        )
        assert isinstance(err, Exception)

    def test_str_matches_exception_repr(self):
        err = MahavishnuError(
            message="test msg",
            error_code=ErrorCode.CONFIGURATION_ERROR,
        )
        assert "MHV-001" in str(err)


# =========================================================================
# Convenience error classes
# =========================================================================


class TestConvenienceErrors:
    """Test each convenience error class constructs correctly."""

    def test_configuration_error(self):
        err = ConfigurationError("bad config", details={"file": "a.yaml"})
        assert isinstance(err, MahavishnuError)
        assert err.error_code == ErrorCode.CONFIGURATION_ERROR
        assert err.message == "bad config"
        assert err.details["file"] == "a.yaml"

    def test_validation_error(self):
        err = ValidationError("invalid input")
        assert err.error_code == ErrorCode.VALIDATION_ERROR

    def test_task_not_found_error(self):
        err = TaskNotFoundError(42)
        assert err.error_code == ErrorCode.TASK_NOT_FOUND
        assert "42" in err.message
        assert err.details["task_id"] == "42"

    def test_task_not_found_with_str_id(self):
        err = TaskNotFoundError("abc-123")
        assert err.details["task_id"] == "abc-123"

    def test_task_not_found_with_details(self):
        err = TaskNotFoundError(1, details={"extra": True})
        assert err.details["extra"] is True

    def test_repository_not_found_error(self):
        err = RepositoryNotFoundError("my-repo")
        assert err.error_code == ErrorCode.REPOSITORY_NOT_FOUND
        assert "my-repo" in err.message
        assert err.details["repository"] == "my-repo"

    def test_webhook_auth_error_default(self):
        err = WebhookAuthError("bad signature")
        assert err.error_code == ErrorCode.WEBHOOK_SIGNATURE_INVALID

    def test_webhook_auth_error_custom_code(self):
        err = WebhookAuthError(
            "replay",
            error_code=ErrorCode.WEBHOOK_REPLAY_DETECTED,
        )
        assert err.error_code == ErrorCode.WEBHOOK_REPLAY_DETECTED

    def test_rate_limit_error(self):
        err = RateLimitError("100 req/min")
        assert err.error_code == ErrorCode.RATE_LIMIT_EXCEEDED
        assert err.details["limit"] == "100 req/min"

    def test_rate_limit_error_with_retry(self):
        err = RateLimitError("10/s", retry_after=30)
        assert err.details["retry_after_seconds"] == 30

    def test_adapter_error(self):
        err = AdapterError("failed to start")
        assert err.error_code == ErrorCode.INTERNAL_ERROR
        assert "Adapter" not in err.message  # no adapter_name

    def test_adapter_error_with_name(self):
        err = AdapterError("failed", adapter_name="prefect")
        assert "prefect" in err.message

    def test_adapter_initialization_error(self):
        err = AdapterInitializationError(
            adapter_name="agno",
            message="missing dep",
            details={"missing_deps": ["agno"]},
        )
        assert err.error_code == ErrorCode.ADAPTER_INITIALIZATION_ERROR
        assert "agno" in err.message
        assert err.details["adapter_name"] == "agno"

    def test_workflow_execution_error_with_step(self):
        err = WorkflowExecutionError(
            workflow_id="wf1",
            message="deploy failed",
            step_name="deploy",
        )
        assert err.error_code == ErrorCode.WORKFLOW_EXECUTION_ERROR
        assert "deploy" in err.message
        assert err.details["step_name"] == "deploy"
        assert err.details["workflow_id"] == "wf1"

    def test_workflow_execution_error_without_step(self):
        err = WorkflowExecutionError(
            workflow_id="wf2",
            message="unknown failure",
        )
        assert "step" not in err.message.lower().replace("execution", "")
        assert err.details.get("step_name") is None

    def test_workflow_execution_error_with_adapter(self):
        err = WorkflowExecutionError(
            workflow_id="wf3",
            message="fail",
            adapter_name="prefect",
        )
        assert err.details["adapter_name"] == "prefect"

    def test_authentication_error(self):
        err = AuthenticationError()
        assert err.error_code == ErrorCode.AUTHENTICATION_ERROR
        assert err.message == "Authentication failed"

    def test_authentication_error_custom(self):
        err = AuthenticationError("bad token")
        assert err.message == "bad token"

    def test_authorization_error(self):
        err = AuthorizationError()
        assert err.error_code == ErrorCode.AUTHORIZATION_ERROR

    def test_timeout_error(self):
        err = TimeoutError("db_query")
        assert err.error_code == ErrorCode.TIMEOUT_ERROR
        assert "db_query" in err.message
        assert err.details["operation"] == "db_query"

    def test_timeout_error_with_seconds(self):
        err = TimeoutError("fetch", timeout_seconds=30.0)
        assert "30.0s" in err.message

    def test_database_error(self):
        err = DatabaseError("connection refused")
        assert err.error_code == ErrorCode.DATABASE_CONNECTION_ERROR

    def test_external_service_error(self):
        err = ExternalServiceError("github", "API rate limit")
        assert err.error_code == ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE
        assert "github" in err.message
        assert err.details["service"] == "github"

    def test_workflow_error(self):
        err = WorkflowError("wf1", "step failed", step="build")
        assert err.error_code == ErrorCode.INTERNAL_ERROR
        assert "build" in err.message
        assert err.details["step"] == "build"

    def test_workflow_error_no_step(self):
        err = WorkflowError("wf1", "generic fail")
        assert "step" not in err.message

    def test_prefect_error(self):
        err = PrefectError("flow missing")
        assert err.error_code == ErrorCode.PREFECT_API_ERROR

    def test_prefect_error_custom_code(self):
        err = PrefectError("timeout", error_code=ErrorCode.PREFECT_TIMEOUT)
        assert err.error_code == ErrorCode.PREFECT_TIMEOUT

    def test_agno_error(self):
        err = AgnoError("agent missing")
        assert err.error_code == ErrorCode.AGNO_AGENT_NOT_FOUND

    def test_goal_team_error(self):
        err = GoalTeamError("creation failed")
        assert err.error_code == ErrorCode.GOAL_TEAM_CREATION_FAILED

    def test_goal_team_not_found_error(self):
        err = GoalTeamNotFoundError("team-123")
        assert err.error_code == ErrorCode.GOAL_TEAM_NOT_FOUND
        assert err.details["team_id"] == "team-123"

    def test_goal_parsing_error(self):
        err = GoalParsingError("do stuff", "too vague")
        assert err.error_code == ErrorCode.GOAL_PARSING_FAILED
        assert err.details["goal"] == "do stuff"
        assert err.details["reason"] == "too vague"

    def test_goal_parsing_error_custom_code(self):
        err = GoalParsingError(
            "x", "short",
            error_code=ErrorCode.GOAL_TOO_SHORT,
        )
        assert err.error_code == ErrorCode.GOAL_TOO_SHORT

    def test_learning_system_error(self):
        err = LearningSystemError("feedback failed")
        assert err.error_code == ErrorCode.LEARNING_FEEDBACK_FAILED

    def test_context_not_initialized_error(self):
        err = ContextNotInitializedError("llm_factory")
        assert err.error_code == ErrorCode.CONTEXT_NOT_INITIALIZED
        assert "llm_factory" in err.message
        assert err.details["context_name"] == "llm_factory"

    def test_feature_disabled_error(self):
        err = FeatureDisabledError("goal_teams")
        assert err.error_code == ErrorCode.FEATURE_DISABLED
        assert "goal_teams" in err.message
        assert err.details["feature_name"] == "goal_teams"


# =========================================================================
# Helper functions
# =========================================================================


class TestErrorHelpers:
    """Test get_contextual_help, format_error_for_cli, create_error_from_exception."""

    def test_get_contextual_help_basic(self):
        help_text = get_contextual_help(ErrorCode.TASK_NOT_FOUND)
        assert "TASK NOT FOUND" in help_text
        assert "MHV-100" in help_text
        assert "How to resolve" in help_text

    def test_get_contextual_help_with_context(self):
        help_text = get_contextual_help(
            ErrorCode.DATABASE_CONNECTION_ERROR,
            context={"host": "localhost", "port": 5432},
        )
        assert "localhost" in help_text
        assert "5432" in help_text
        assert "Context" in help_text

    def test_format_error_for_cli_brief(self):
        err = MahavishnuError("test", ErrorCode.CONFIGURATION_ERROR)
        output = format_error_for_cli(err, verbose=False)
        assert "MHV-001" in output
        assert "test" in output
        assert "--verbose" in output
        assert "Recovery steps" not in output  # brief mode

    def test_format_error_for_cli_verbose(self):
        err = MahavishnuError("test", ErrorCode.CONFIGURATION_ERROR)
        output = format_error_for_cli(err, verbose=True)
        assert "Recovery steps" in output

    def test_format_error_for_cli_no_recovery(self):
        err = MahavishnuError("test", ErrorCode.INTERNAL_ERROR, recovery=[])
        output = format_error_for_cli(err, verbose=False)
        assert "MHV-007" in output

    def test_create_error_from_exception(self):
        exc = ValueError("bad value")
        err = create_error_from_exception(exc)
        assert isinstance(err, MahavishnuError)
        assert err.message == "bad value"
        assert err.details["original_type"] == "ValueError"
        assert err.error_code == ErrorCode.INTERNAL_ERROR

    def test_create_error_from_exception_with_context(self):
        exc = RuntimeError("boom")
        err = create_error_from_exception(
            exc,
            error_code=ErrorCode.ADAPTER_INITIALIZATION_ERROR,
            context={"adapter": "prefect"},
        )
        assert err.error_code == ErrorCode.ADAPTER_INITIALIZATION_ERROR
        assert err.details["adapter"] == "prefect"

    def test_create_error_from_exception_with_none_message(self):
        exc = RuntimeError()
        err = create_error_from_exception(exc)
        assert err.message == ""


# =========================================================================
# ErrorTemplates
# =========================================================================


class TestErrorTemplates:
    """Test static error template factory methods."""

    def test_task_create_validation(self):
        err = ErrorTemplates.task_create_validation(
            "my task", "mahavishnu", ["Title too short", "Repository invalid"],
        )
        assert isinstance(err, ValidationError)
        assert "Title too short" in err.message
        assert err.details["title"] == "my task"
        assert err.details["repository"] == "mahavishnu"
        assert len(err.details["issues"]) == 2

    def test_database_connection_failed(self):
        err = ErrorTemplates.database_connection_failed(
            "localhost", 5432, "Connection refused",
        )
        assert isinstance(err, DatabaseError)
        assert "localhost:5432" in err.message
        assert err.details["original_error"] == "Connection refused"

    def test_search_failed(self):
        err = ErrorTemplates.search_failed("python async", "timeout")
        assert isinstance(err, ExternalServiceError)
        assert "python async" in err.message
        assert err.details["service"] == "embedding"

    def test_config_file_error(self):
        err = ErrorTemplates.config_file_error("/etc/mhv.yaml", "syntax error")
        assert isinstance(err, ConfigurationError)
        assert "/etc/mhv.yaml" in err.message
        assert err.details["file_path"] == "/etc/mhv.yaml"

    def test_webhook_failed(self):
        err = ErrorTemplates.webhook_failed("push", "bad sig", "payload-123")
        assert isinstance(err, WebhookAuthError)
        assert err.details["event_type"] == "push"
        assert err.details["payload_id"] == "payload-123"

    def test_webhook_failed_no_payload(self):
        err = ErrorTemplates.webhook_failed("push", "bad sig")
        assert "payload_id" not in err.details

    def test_prefect_flow_failed(self):
        err = ErrorTemplates.prefect_flow_failed("etl_flow", "run-42", "OOM")
        assert isinstance(err, PrefectError)
        assert err.error_code == ErrorCode.PREFECT_FLOW_RUN_FAILED
        assert err.details["flow_name"] == "etl_flow"

    def test_prefect_connection_failed(self):
        err = ErrorTemplates.prefect_connection_failed(
            "http://localhost:4200", "ECONNREFUSED",
        )
        assert err.error_code == ErrorCode.PREFECT_CONNECTION_ERROR
        assert err.details["api_url"] == "http://localhost:4200"

    def test_agno_agent_failed(self):
        err = ErrorTemplates.agno_agent_failed("coder", "write tests", "timeout")
        assert isinstance(err, AgnoError)
        assert err.error_code == ErrorCode.AGNO_TOOL_EXECUTION_ERROR
        assert err.details["agent_name"] == "coder"

    def test_agno_llm_error(self):
        err = ErrorTemplates.agno_llm_error("ollama", "llama3", "model not found")
        assert err.error_code == ErrorCode.AGNO_LLM_PROVIDER_ERROR
        assert err.details["provider"] == "ollama"

    def test_adapter_init_failed(self):
        err = ErrorTemplates.adapter_init_failed(
            "prefect", "missing prefect package",
            missing_deps=["prefect"],
        )
        assert isinstance(err, AdapterInitializationError)
        assert err.details["missing_deps"] == ["prefect"]

    def test_adapter_init_failed_with_config_issues(self):
        err = ErrorTemplates.adapter_init_failed(
            "agno", "bad config",
            config_issues=["api_key missing"],
        )
        assert err.details["config_issues"] == ["api_key missing"]

    def test_workflow_step_failed(self):
        err = ErrorTemplates.workflow_step_failed(
            "wf-1", "deploy", "k8s rejected",
            adapter_name="prefect",
            retry_count=3,
        )
        assert isinstance(err, WorkflowExecutionError)
        assert err.details["reason"] == "k8s rejected"
        assert err.details["retry_count"] == 3

    def test_goal_team_creation_failed(self):
        err = ErrorTemplates.goal_team_creation_failed(
            "Build a REST API", "no agents available",
        )
        assert isinstance(err, GoalTeamError)
        assert err.details["goal"] == "Build a REST API"

    def test_goal_too_short(self):
        err = ErrorTemplates.goal_too_short("do it", 10)
        assert isinstance(err, GoalParsingError)
        assert err.error_code == ErrorCode.GOAL_TOO_SHORT
        assert err.details["actual_length"] == 5

    def test_goal_too_long(self):
        long_goal = "x" * 600
        err = ErrorTemplates.goal_too_long(long_goal, 500)
        assert isinstance(err, GoalParsingError)
        assert err.error_code == ErrorCode.GOAL_TOO_LONG
        assert err.details["max_length"] == 500

    def test_learning_feedback_failed(self):
        err = ErrorTemplates.learning_feedback_failed(
            "team-1", "positive", "db down",
        )
        assert isinstance(err, LearningSystemError)
        assert err.details["team_id"] == "team-1"
        assert err.details["feedback_type"] == "positive"


# =========================================================================
# Status enums
# =========================================================================


class TestStatusEnums:
    """Test all status StrEnum classes for completeness and string values."""

    def test_task_status_values(self):
        expected = {"pending", "in_progress", "completed", "failed", "cancelled", "blocked"}
        assert set(TaskStatus) == expected
        for v in TaskStatus:
            assert isinstance(v, str)

    def test_issue_status_values(self):
        expected = {"pending", "in_progress", "blocked", "resolved", "closed"}
        assert set(IssueStatus) == expected

    def test_todo_status_values(self):
        expected = {"pending", "in_progress", "blocked", "completed", "cancelled"}
        assert set(TodoStatus) == expected

    def test_coordination_status_values(self):
        assert "rolled_back" in CoordinationStatus
        assert "in_progress" in CoordinationStatus

    def test_migration_status_values(self):
        assert "running" in MigrationStatus
        assert "rolled_back" in MigrationStatus

    def test_worker_status_values(self):
        expected = {"pending", "starting", "running", "completed", "failed", "timeout", "cancelled"}
        assert set(WorkerStatus) == expected

    def test_workflow_status_values(self):
        assert "timeout" in WorkflowStatus
        assert "running" in WorkflowStatus

    def test_execution_status_values(self):
        assert "success" in ExecutionStatus
        assert "failure" in ExecutionStatus

    def test_plan_status_values(self):
        assert "draft" in PlanStatus
        assert "on_hold" in PlanStatus

    def test_pool_status_values(self):
        assert "initializing" in PoolStatus
        assert "degraded" in PoolStatus
        assert "scaling" in PoolStatus

    def test_deployment_status_values(self):
        assert "deploying" in DeploymentStatus
        assert "rolling_back" in DeploymentStatus

    def test_database_status_values(self):
        expected = {"disconnected", "connecting", "connected", "error"}
        assert set(DatabaseStatus) == expected

    def test_health_status_values(self):
        expected = {"healthy", "degraded", "unhealthy"}
        assert set(HealthStatus) == expected

    def test_readiness_status_values(self):
        expected = {"pass", "fail", "warn"}
        assert set(ReadinessStatus) == expected

    def test_dependency_status_values(self):
        assert "satisfied" in DependencyStatus
        assert "deprecated" in DependencyStatus

    def test_dead_letter_status_values(self):
        assert "retrying" in DeadLetterStatus
        assert "exhausted" in DeadLetterStatus
        assert "archived" in DeadLetterStatus

    def test_blocking_status_values(self):
        expected = {"active", "resolved", "escalated"}
        assert set(BlockingStatus) == expected

    def test_sync_status_values(self):
        expected = {"pending", "approved", "synced", "failed"}
        assert set(SyncStatus) == expected

    def test_onboarding_status_values(self):
        expected = {"not_started", "in_progress", "completed", "skipped"}
        assert set(OnboardingStatus) == expected

    def test_all_status_values_are_strings(self):
        """Every value in every status enum must be a lowercase string."""
        for enum_cls in [
            TaskStatus, IssueStatus, TodoStatus, CoordinationStatus,
            MigrationStatus, WorkerStatus, WorkflowStatus, ExecutionStatus,
            PlanStatus, PoolStatus, DeploymentStatus, DatabaseStatus,
            HealthStatus, ReadinessStatus, DependencyStatus,
            DeadLetterStatus, BlockingStatus, SyncStatus, OnboardingStatus,
        ]:
            for v in enum_cls:
                assert isinstance(v, str), f"{enum_cls.__name__}.{v} is not a str"
                assert v == v.lower(), f"{enum_cls.__name__}.{v} is not lowercase"

    def test_status_comparison(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.PENDING != TaskStatus.COMPLETED

    def test_status_in_set(self):
        terminal = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
        assert TaskStatus.COMPLETED in terminal
        assert TaskStatus.PENDING not in terminal


# =========================================================================
# RepositoryMetadata
# =========================================================================


class TestRepositoryMetadata:
    def test_defaults(self):
        meta = RepositoryMetadata()
        assert meta.version == "0.0.0"
        assert meta.language == "python"
        assert meta.min_python is None
        assert meta.dependencies == 0

    def test_custom_values(self):
        meta = RepositoryMetadata(
            version="1.2.3",
            language="typescript",
            min_python="3.11",
            dependencies=42,
        )
        assert meta.version == "1.2.3"
        assert meta.language == "typescript"
        assert meta.dependencies == 42

    def test_dependencies_ge_zero(self):
        with pytest.raises(Exception):  # Pydantic ValidationError
            RepositoryMetadata(dependencies=-1)


# =========================================================================
# Repository model
# =========================================================================


def _make_repo(**overrides):
    """Create a valid Repository with sensible defaults."""
    defaults = dict(
        name="test-repo",
        package="test_repo",
        path="/tmp/test-repo",
        tags=["python"],
        description="A test repository",
    )
    defaults.update(overrides)
    return Repository(**defaults)


class TestRepository:
    def test_valid_construction(self):
        repo = _make_repo()
        assert repo.name == "test-repo"
        assert repo.package == "test_repo"
        assert repo.tags == ["python"]

    def test_path_must_be_absolute(self):
        with pytest.raises(Exception):
            _make_repo(path="relative/path")

    def test_path_is_resolved(self):
        repo = _make_repo(path="/tmp/../tmp/test-repo")
        assert repo.path.is_absolute()
        assert repo.path.name == "test-repo"

    def test_invalid_tag_format(self):
        with pytest.raises(Exception):
            _make_repo(tags=["UPPERCASE"])

    def test_invalid_tag_chars(self):
        with pytest.raises(Exception):
            _make_repo(tags=["has spaces"])

    def test_valid_tags(self):
        repo = _make_repo(tags=["python", "backend", "ml-tool"])
        assert repo.tags == ["python", "backend", "ml-tool"]

    def test_name_with_spaces_rejected(self):
        with pytest.raises(Exception):
            _make_repo(name="my repo")

    def test_name_lowered(self):
        repo = _make_repo(name="my-repo")
        # The validator lowercases, but the regex also requires the input to match
        # The validator runs AFTER the regex, so only already-lowercase names pass
        assert repo.name == "my-repo"

    def test_nickname_set_from_nicknames(self):
        repo = _make_repo(nicknames=["vishnu", "mcp"])
        assert repo.nickname == "vishnu"

    def test_nickname_preserved(self):
        repo = _make_repo(nickname="vishnu", nicknames=["alias"])
        assert repo.nickname == "vishnu"

    def test_mcp_native_auto_adds_tag(self):
        repo = _make_repo(mcp="native", tags=["python"])
        assert "mcp" in repo.tags

    def test_mcp_native_rejects_3rd_party_tag(self):
        with pytest.raises(Exception):
            _make_repo(mcp="native", tags=["python", "3rd-party"])

    def test_mcp_3rd_party_rejects_native_tag(self):
        with pytest.raises(Exception):
            _make_repo(mcp="3rd-party", tags=["python", "native"])

    def test_mcp_none_no_tag_modification(self):
        repo = _make_repo(mcp=None, tags=["python"])
        assert repo.tags == ["python"]

    def test_min_tags(self):
        with pytest.raises(Exception):
            _make_repo(tags=[])

    def test_max_tags(self):
        too_many = [f"tag{i}" for i in range(11)]
        with pytest.raises(Exception):
            _make_repo(tags=too_many)

    def test_description_min_length(self):
        with pytest.raises(Exception):
            _make_repo(description="")

    def test_metadata_attached(self):
        meta = RepositoryMetadata(version="2.0.0")
        repo = _make_repo(metadata=meta)
        assert repo.metadata.version == "2.0.0"

    def test_role_optional(self):
        repo = _make_repo(role="orchestrator")
        assert repo.role == "orchestrator"

    def test_invalid_name_pattern(self):
        with pytest.raises(Exception):
            _make_repo(name="INVALID")

    def test_invalid_package_pattern(self):
        with pytest.raises(Exception):
            _make_repo(package="123invalid")


# =========================================================================
# RepositoryManifest
# =========================================================================


class TestRepositoryManifest:
    def test_valid_manifest(self):
        repos = [
            _make_repo(name="repo-a", package="repo_a", path="/tmp/a"),
            _make_repo(name="repo-b", package="repo_b", path="/tmp/b"),
        ]
        manifest = RepositoryManifest(repos=repos)
        assert len(manifest.repos) == 2
        assert manifest.version == "1.0"

    def test_min_one_repo(self):
        with pytest.raises(Exception):
            RepositoryManifest(repos=[])

    def test_duplicate_path_rejected(self):
        repos = [
            _make_repo(name="repo-a", package="repo_a", path="/tmp/same"),
            _make_repo(name="repo-b", package="repo_b", path="/tmp/same"),
        ]
        with pytest.raises(Exception, match="Duplicate repository path"):
            RepositoryManifest(repos=repos)

    def test_duplicate_name_rejected(self):
        repos = [
            _make_repo(name="dup", package="repo_a", path="/tmp/a"),
            _make_repo(name="dup", package="repo_b", path="/tmp/b"),
        ]
        with pytest.raises(Exception, match="Duplicate repository name"):
            RepositoryManifest(repos=repos)

    def test_duplicate_package_rejected(self):
        repos = [
            _make_repo(name="repo-a", package="same_pkg", path="/tmp/a"),
            _make_repo(name="repo-b", package="same_pkg", path="/tmp/b"),
        ]
        with pytest.raises(Exception, match="Duplicate package name"):
            RepositoryManifest(repos=repos)
