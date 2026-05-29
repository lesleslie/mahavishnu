"""Unit tests for workflow execution module.

These tests use self-contained mocks and do not rely on external projects.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.errors import AdapterError, ValidationError
from mahavishnu.core.metrics_schema import AdapterType
import mahavishnu.core.workflow_execution as we
from mahavishnu.core.workflow_execution import (
    check_dependency_health,
    create_session_checkpoint,
    execute_parallel_workflow,
    execute_workflow_with_fallback,
    execute_workflow_with_routing,
    finalize_workflow_execution,
    handle_workflow_execution_error,
    initialize_workflow_state,
    prepare_execution,
    validate_pre_execution_qc,
)

# ============================================================================
# Fixtures - Mock App Builder
# ============================================================================


def _make_mock_app(overrides=None):
    """Build a self-contained mock app for testing workflow execution functions."""
    app = MagicMock()

    # Config mock with nested attribute access
    app.config = MagicMock()
    app.config.qc.enabled = True
    app.config.session.enabled = True
    app.config.max_concurrent_workflows = 10

    # Workflow state manager mock
    app.workflow_state_manager = AsyncMock()
    app.workflow_state_manager.create = AsyncMock(
        return_value={"id": "wf_123", "status": "pending"}
    )
    app.workflow_state_manager.update = AsyncMock(return_value=None)
    app.workflow_state_manager.add_result = AsyncMock(return_value=None)
    app.workflow_state_manager.add_error = AsyncMock(return_value=None)
    app.workflow_state_manager.get_completed_count = AsyncMock(return_value=0)
    app.workflow_state_manager.update_progress = AsyncMock(return_value=None)

    # Active workflows set
    app.active_workflows = set()

    # Gauge update mock
    app._update_workflow_runtime_gauges = MagicMock()

    # OpenSearch integration mock
    app.opensearch_integration = AsyncMock()
    app.opensearch_integration.log_workflow_start = AsyncMock(return_value=None)
    app.opensearch_integration.log_workflow_completion = AsyncMock(return_value=None)
    app.opensearch_integration.log_error = AsyncMock(return_value=None)

    # QC mock
    app.qc = AsyncMock()
    app.qc.validate_pre_execution = AsyncMock(return_value=True)
    app.qc.validate_post_execution = AsyncMock(return_value=True)
    app.qc.is_healthy = AsyncMock(return_value=True)

    # Session buddy mock
    app.session_buddy = AsyncMock()
    app.session_buddy.create_checkpoint = AsyncMock(return_value="checkpoint_123")
    app.session_buddy.update_checkpoint = AsyncMock(return_value=None)
    app.session_buddy.is_healthy = AsyncMock(return_value=True)

    # Adapter mock
    mock_adapter = AsyncMock()
    mock_adapter.execute = AsyncMock(return_value={"status": "ok", "repo": "test-repo"})
    app.adapters = {"prefect": mock_adapter}

    # Circuit breaker mock
    app.circuit_breaker = MagicMock()
    app.circuit_breaker.call = AsyncMock(return_value={"status": "ok"})
    app.circuit_breaker.record_failure = MagicMock()

    # Observability mock
    app.observability = MagicMock()
    app.observability.record_repo_processing_time = MagicMock()
    app.observability.start_repo_trace = MagicMock()
    app.observability.start_repo_trace.return_value.__enter__ = MagicMock()
    app.observability.start_repo_trace.return_value.__exit__ = MagicMock()
    app.observability.create_workflow_counter = MagicMock()
    app.observability.create_repo_counter = MagicMock()
    app.observability.create_error_counter = MagicMock()
    app.observability.end_workflow_trace = MagicMock()

    # Semaphore mock
    app.semaphore = asyncio.Semaphore(5)

    # RBAC manager mock
    app.rbac_manager = AsyncMock()
    app.rbac_manager.check_permission = AsyncMock(return_value=True)

    # Apply any overrides
    if overrides:
        for key, value in overrides.items():
            parts = key.split(".")
            obj = app
            for part in parts[:-1]:
                obj = getattr(obj, part)
            setattr(obj, parts[-1], value)

    return app


# ============================================================================
# initialize_workflow_state Tests
# ============================================================================


class TestInitializeWorkflowState:
    """Test workflow state initialization."""

    @pytest.mark.asyncio
    async def test_creates_workflow_id(self):
        """initialize_workflow_state creates a workflow ID and returns it."""
        app = _make_mock_app()
        task = {"type": "code_review", "id": "task_1"}
        adapter_name = "prefect"
        validated_repos = ["/repo/a"]

        workflow_id = await initialize_workflow_state(app, task, adapter_name, validated_repos)

        assert workflow_id is not None
        assert workflow_id.startswith("wf_")
        assert "code_review" in workflow_id

    @pytest.mark.asyncio
    async def test_creates_workflow_state(self):
        """initialize_workflow_state calls workflow_state_manager.create."""
        app = _make_mock_app()
        task = {"type": "check"}
        adapter_name = "prefect"
        validated_repos = ["/repo/a"]

        await initialize_workflow_state(app, task, adapter_name, validated_repos)

        app.workflow_state_manager.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_adds_to_active_workflows(self):
        """initialize_workflow_state adds workflow_id to active_workflows set."""
        app = _make_mock_app()
        task = {"type": "check"}
        adapter_name = "prefect"
        validated_repos = ["/repo/a"]

        workflow_id = await initialize_workflow_state(app, task, adapter_name, validated_repos)

        assert workflow_id in app.active_workflows

    @pytest.mark.asyncio
    async def test_updates_workflow_status_to_running(self):
        """initialize_workflow_state updates status to 'running'."""
        app = _make_mock_app()
        task = {"type": "check"}
        adapter_name = "prefect"
        validated_repos = ["/repo/a"]

        await initialize_workflow_state(app, task, adapter_name, validated_repos)

        app.workflow_state_manager.update.assert_awaited()
        call_args = app.workflow_state_manager.update.call_args
        assert call_args.kwargs.get("status") == "running"

    @pytest.mark.asyncio
    async def test_logs_workflow_start(self):
        """initialize_workflow_state logs workflow start."""
        app = _make_mock_app()
        task = {"type": "check"}
        adapter_name = "prefect"
        validated_repos = ["/repo/a"]

        await initialize_workflow_state(app, task, adapter_name, validated_repos)

        app.opensearch_integration.log_workflow_start.assert_awaited_once()


# ============================================================================
# validate_pre_execution_qc Tests
# ============================================================================


class TestValidatePreExecutionQC:
    """Test pre-execution QC validation."""

    @pytest.mark.asyncio
    async def test_returns_early_when_qc_disabled(self):
        """Returns without checking when qc.enabled is False."""
        app = _make_mock_app()
        app.config.qc.enabled = False

        # Should not raise
        await validate_pre_execution_qc(app, "wf_123", ["/repo/a"])

    @pytest.mark.asyncio
    async def test_passes_when_qc_returns_true(self):
        """No error when QC check passes."""
        app = _make_mock_app()
        app.qc.validate_pre_execution = AsyncMock(return_value=True)

        # Should not raise
        await validate_pre_execution_qc(app, "wf_123", ["/repo/a"])

    @pytest.mark.asyncio
    async def test_raises_validation_error_when_qc_fails(self):
        """Raises ValidationError when QC check fails."""
        app = _make_mock_app()
        app.qc.validate_pre_execution = AsyncMock(return_value=False)
        app.workflow_state_manager.update = AsyncMock(return_value=None)

        with pytest.raises(Exception) as exc_info:
            await validate_pre_execution_qc(app, "wf_123", ["/repo/a"])

        # Should be ValidationError
        assert "Pre-execution QC check failed" in str(exc_info.value)


# ============================================================================
# create_session_checkpoint Tests
# ============================================================================


class TestCreateSessionCheckpoint:
    """Test session checkpoint creation."""

    @pytest.mark.asyncio
    async def test_returns_none_when_session_disabled(self):
        """Returns None when session.enabled is False."""
        app = _make_mock_app()
        app.config.session.enabled = False

        result = await create_session_checkpoint(app, {"id": "task_1"}, "prefect", ["/repo/a"])

        assert result is None

    @pytest.mark.asyncio
    async def test_creates_checkpoint_when_session_enabled(self):
        """Creates checkpoint when session.enabled is True."""
        app = _make_mock_app()
        app.config.session.enabled = True

        result = await create_session_checkpoint(
            app, {"id": "task_1", "type": "check"}, "prefect", ["/repo/a", "/repo/b"]
        )

        app.session_buddy.create_checkpoint.assert_awaited_once()
        assert result == "checkpoint_123"

    @pytest.mark.asyncio
    async def test_checkpoint_includes_task_and_adapter_info(self):
        """Checkpoint state includes task, adapter and repos."""
        app = _make_mock_app()
        app.config.session.enabled = True

        await create_session_checkpoint(
            app, {"id": "task_1", "type": "check"}, "prefect", ["/repo/a", "/repo/b"]
        )

        call_args = app.session_buddy.create_checkpoint.call_args
        state = call_args.kwargs.get("state", {})
        assert state["task"]["id"] == "task_1"
        assert state["adapter"] == "prefect"
        assert state["repos"] == ["/repo/a", "/repo/b"]
        assert state["status"] == "started"


# ============================================================================
# check_dependency_health Tests
# ============================================================================


class TestCheckDependencyHealth:
    """Test dependency health checking."""

    @pytest.mark.asyncio
    async def test_passes_when_all_dependencies_healthy(self):
        """No error when QC and Session-Buddy are healthy."""
        app = _make_mock_app()
        app.qc.is_healthy = AsyncMock(return_value=True)
        app.session_buddy.is_healthy = AsyncMock(return_value=True)
        app.config.qc.enabled = True
        app.config.session.enabled = True

        # Should not raise
        await check_dependency_health(app)

    @pytest.mark.asyncio
    async def test_passes_when_qc_disabled(self):
        """No error when QC is disabled even if unhealthy."""
        app = _make_mock_app()
        app.config.qc.enabled = False

        # Should not raise
        await check_dependency_health(app)

    @pytest.mark.asyncio
    async def test_passes_when_session_disabled(self):
        """No error when session is disabled even if unhealthy."""
        app = _make_mock_app()
        app.config.session.enabled = False

        # Should not raise
        await check_dependency_health(app)

    @pytest.mark.asyncio
    async def test_raises_external_service_error_when_qc_unhealthy(self):
        """Raises ExternalServiceError when QC is unhealthy and enabled."""
        app = _make_mock_app()
        app.config.qc.enabled = True
        app.qc.is_healthy = AsyncMock(return_value=False)
        app.session_buddy.is_healthy = AsyncMock(return_value=True)

        with pytest.raises(Exception) as exc_info:
            await check_dependency_health(app)

        assert "QC service is unreachable" in str(exc_info.value)


# ============================================================================
# prepare_execution Tests
# ============================================================================


class TestPrepareExecution:
    """Test execution preparation."""

    @pytest.mark.asyncio
    async def test_raises_error_for_unknown_adapter(self):
        """Raises ValidationError when adapter not found."""
        app = _make_mock_app()
        app.adapters = {"prefect": MagicMock()}

        with pytest.raises(Exception) as exc_info:
            await prepare_execution(app, "unknown_adapter", {}, None, None)

        assert "Adapter not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_validates_repository_paths(self):
        """Validates each repo path before execution."""
        app = _make_mock_app()

        with patch("mahavishnu.core.workflow_execution.validate_path") as mock_validate:
            mock_validate.return_value = "/validated/repo"

            adapter, validated_repos = await prepare_execution(
                app, "prefect", {"type": "check"}, ["/repo/a"], None
            )

            assert mock_validate.call_count == 1
            assert validated_repos == ["/validated/repo"]


# ============================================================================
# execute_parallel_workflow Tests
# ============================================================================


class TestExecuteParallelWorkflow:
    """Test parallel workflow execution."""

    @pytest.mark.asyncio
    async def test_runs_all_repos_concurrently(self):
        """Executes tasks for all repos concurrently."""
        app = _make_mock_app()
        adapter = AsyncMock()
        adapter.execute = AsyncMock(return_value={"status": "ok"})
        task = {"type": "check"}
        adapter_name = "prefect"
        workflow_id = "wf_123"
        validated_repos = ["/repo/a", "/repo/b", "/repo/c"]
        app.workflow_state_manager.get_completed_count = AsyncMock(return_value=0)

        execution_time, results, errors = await execute_parallel_workflow(
            app, adapter, task, adapter_name, workflow_id, validated_repos
        )

        assert execution_time >= 0
        assert len(results) == 3
        assert len(errors) == 0

    @pytest.mark.asyncio
    async def test_returns_results_and_errors(self):
        """Returns tuple of (execution_time, successful_results, errors)."""
        app = _make_mock_app()
        adapter = AsyncMock()
        adapter.execute = AsyncMock(return_value={"status": "ok"})
        task = {"type": "check"}
        adapter_name = "prefect"
        workflow_id = "wf_123"
        validated_repos = ["/repo/a"]
        app.workflow_state_manager.get_completed_count = AsyncMock(return_value=1)

        execution_time, results, errors = await execute_parallel_workflow(
            app, adapter, task, adapter_name, workflow_id, validated_repos
        )

        assert isinstance(execution_time, float)
        assert isinstance(results, list)
        assert isinstance(errors, list)


# ============================================================================
# finalize_workflow_execution Tests
# ============================================================================


class TestFinalizeWorkflowExecution:
    """Test workflow execution finalization."""

    @pytest.mark.asyncio
    async def test_updates_workflow_status_to_completed(self):
        """Updates workflow status to 'completed' when no errors."""
        app = _make_mock_app()
        app.active_workflows.add("wf_123")

        await finalize_workflow_execution(
            app=app,
            workflow_id="wf_123",
            adapter_name="prefect",
            task={"type": "check"},
            validated_repos=["/repo/a"],
            execution_time=1.5,
            successful_results=[{"status": "ok"}],
            errors=[],
            checkpoint_id="cp_123",
        )

        app.workflow_state_manager.update.assert_awaited()
        call_args = app.workflow_state_manager.update.call_args
        assert call_args.kwargs.get("status") == "completed"

    @pytest.mark.asyncio
    async def test_updates_workflow_status_to_partial(self):
        """Updates workflow status to 'partial' when some errors occurred."""
        app = _make_mock_app()
        app.active_workflows.add("wf_123")

        await finalize_workflow_execution(
            app=app,
            workflow_id="wf_123",
            adapter_name="prefect",
            task={"type": "check"},
            validated_repos=["/repo/a", "/repo/b"],
            execution_time=1.5,
            successful_results=[{"status": "ok"}],
            errors=[{"repo": "/repo/b", "error": "failed"}],
            checkpoint_id="cp_123",
        )

        call_args = app.workflow_state_manager.update.call_args
        assert call_args.kwargs.get("status") == "partial"

    @pytest.mark.asyncio
    async def test_removes_workflow_from_active_workflows(self):
        """Removes workflow_id from active_workflows set."""
        app = _make_mock_app()
        app.active_workflows.add("wf_123")

        await finalize_workflow_execution(
            app=app,
            workflow_id="wf_123",
            adapter_name="prefect",
            task={"type": "check"},
            validated_repos=["/repo/a"],
            execution_time=1.5,
            successful_results=[{"status": "ok"}],
            errors=[],
            checkpoint_id="cp_123",
        )

        assert "wf_123" not in app.active_workflows

    @pytest.mark.asyncio
    async def test_logs_workflow_completion(self):
        """Logs workflow completion to OpenSearch."""
        app = _make_mock_app()

        await finalize_workflow_execution(
            app=app,
            workflow_id="wf_123",
            adapter_name="prefect",
            task={"type": "check"},
            validated_repos=["/repo/a"],
            execution_time=1.5,
            successful_results=[{"status": "ok"}],
            errors=[],
            checkpoint_id=None,
        )

        app.opensearch_integration.log_workflow_completion.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_result_dict_with_stats(self):
        """Returns dict with workflow statistics."""
        app = _make_mock_app()

        result = await finalize_workflow_execution(
            app=app,
            workflow_id="wf_123",
            adapter_name="prefect",
            task={"type": "check"},
            validated_repos=["/repo/a", "/repo/b"],
            execution_time=2.5,
            successful_results=[{"status": "ok"}, {"status": "ok"}],
            errors=[{"repo": "/repo/c", "error": "failed"}],
            checkpoint_id="cp_123",
        )

        assert result["workflow_id"] == "wf_123"
        assert result["status"] == "partial"
        assert result["successful_repos"] == 2
        assert result["failed_repos"] == 1
        assert result["execution_time_seconds"] == 2.5


# ============================================================================
# handle_workflow_execution_error Tests
# ============================================================================


class TestHandleWorkflowExecutionError:
    """Test error handling in workflow execution."""

    @pytest.mark.asyncio
    async def test_updates_workflow_status_to_failed(self):
        """Updates workflow status to 'failed' on error (then re-raises)."""
        app = _make_mock_app()
        app.active_workflows.add("wf_123")

        error = RuntimeError("Adapter failed")
        with pytest.raises(Exception):  # Expected to raise AdapterError
            await handle_workflow_execution_error(
                app=app,
                workflow_id="wf_123",
                adapter_name="prefect",
                task={"type": "check"},
                validated_repos=["/repo/a"],
                error=error,
                checkpoint_id=None,
            )

        app.workflow_state_manager.update.assert_awaited()
        call_args = app.workflow_state_manager.update.call_args
        assert call_args.kwargs.get("status") == "failed"

    @pytest.mark.asyncio
    async def test_logs_error_to_opensearch(self):
        """Logs error to OpenSearch (then re-raises)."""
        app = _make_mock_app()

        error = RuntimeError("Adapter failed")
        with pytest.raises(Exception):  # Expected to raise AdapterError
            await handle_workflow_execution_error(
                app=app,
                workflow_id="wf_123",
                adapter_name="prefect",
                task={"type": "check"},
                validated_repos=["/repo/a"],
                error=error,
                checkpoint_id=None,
            )

        app.opensearch_integration.log_error.assert_awaited()

    @pytest.mark.asyncio
    async def test_removes_workflow_from_active_workflows_on_error(self):
        """Removes workflow from active_workflows set on error."""
        app = _make_mock_app()
        app.active_workflows.add("wf_123")

        error = RuntimeError("Adapter failed")
        try:
            await handle_workflow_execution_error(
                app=app,
                workflow_id="wf_123",
                adapter_name="prefect",
                task={"type": "check"},
                validated_repos=["/repo/a"],
                error=error,
                checkpoint_id=None,
            )
        except Exception:
            pass  # Expected - error is re-raised

        assert "wf_123" not in app.active_workflows


# ============================================================================
# Error Handling Edge Cases
# ============================================================================


class TestWorkflowExecutionErrorHandling:
    """Test error handling edge cases."""

    @pytest.mark.asyncio
    async def test_validation_error_contains_details(self):
        """ValidationError includes details dict for debugging."""
        app = _make_mock_app()
        app.qc.validate_pre_execution = AsyncMock(return_value=False)

        with pytest.raises(Exception) as exc_info:
            await validate_pre_execution_qc(app, "wf_123", ["/repo/a"])

        error = exc_info.value
        # Error should have message about QC failure
        assert "Pre-execution QC check failed" in str(error)

    @pytest.mark.asyncio
    async def test_prepare_execution_raises_for_missing_adapter(self):
        """prepare_execution raises clear error for unknown adapter."""
        app = _make_mock_app()
        app.adapters = {}

        with pytest.raises(Exception) as exc_info:
            await prepare_execution(app, "missing", {"type": "check"}, ["/repo/a"], None)

        error_message = str(exc_info.value)
        assert "Adapter not found" in error_message
        assert "missing" in error_message


class TestWorkflowExecutionCoverageAdditions:
    @pytest.mark.asyncio
    async def test_prepare_execution_uses_get_repos_and_checks_permissions(self, monkeypatch):
        app = _make_mock_app()
        app.get_repos = MagicMock(return_value=["/repo/a"])
        app.rbac_manager.check_permission = AsyncMock(return_value=True)

        monkeypatch.setattr(we, "validate_path", lambda path, allowed: Path(path), raising=True)
        monkeypatch.setattr(
            we, "check_dependency_health", AsyncMock(return_value=None), raising=True
        )

        adapter, validated_repos = await prepare_execution(
            app, "prefect", {"type": "check"}, None, "user-1"
        )

        assert adapter is app.adapters["prefect"]
        assert validated_repos == ["/repo/a"]

    @pytest.mark.asyncio
    async def test_prepare_execution_invalid_repo_path(self, monkeypatch):
        app = _make_mock_app()

        def boom(*args, **kwargs):  # noqa: ANN001,ANN002
            raise ValidationError(message="bad path", details={})

        monkeypatch.setattr(we, "validate_path", boom, raising=True)

        with pytest.raises(ValidationError, match="Invalid repository path"):
            await prepare_execution(app, "prefect", {"type": "check"}, ["/bad"], None)

    @pytest.mark.asyncio
    async def test_prepare_execution_permission_denied(self, monkeypatch):
        app = _make_mock_app()
        app.rbac_manager.check_permission = AsyncMock(return_value=False)
        monkeypatch.setattr(we, "validate_path", lambda path, allowed: Path(path), raising=True)

        with pytest.raises(ValidationError, match="does not have permission"):
            await prepare_execution(app, "prefect", {"type": "check"}, ["/repo/a"], "user-1")

    @pytest.mark.asyncio
    async def test_check_dependency_health_session_warning(self, caplog):
        app = _make_mock_app()
        app.session_buddy.is_healthy = AsyncMock(return_value=False)
        app.qc.is_healthy = AsyncMock(return_value=True)

        await check_dependency_health(app)
        assert "degraded mode" in caplog.text

    @pytest.mark.asyncio
    async def test_process_single_repo_success_and_error(self):
        app = _make_mock_app()
        adapter = MagicMock()
        workflow_id = "wf_123"
        semaphore = asyncio.Semaphore(1)
        progress_calls: list[tuple[int, int, str]] = []

        def progress_callback(done, total, repo):  # noqa: ANN001,ANN002,ANN003
            progress_calls.append((done, total, repo))

        result = await we.process_single_repo(
            app=app,
            adapter=adapter,
            task={"type": "check"},
            adapter_name="prefect",
            workflow_id=workflow_id,
            repo_path="/repo/a",
            total_repos=1,
            semaphore=semaphore,
            progress_callback=progress_callback,
        )

        assert result == {"status": "ok"}
        assert progress_calls == [(1, 1, "/repo/a")]

        app.circuit_breaker.call = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(RuntimeError):
            await we.process_single_repo(
                app=app,
                adapter=adapter,
                task={"type": "check"},
                adapter_name="prefect",
                workflow_id=workflow_id,
                repo_path="/repo/b",
                total_repos=1,
                semaphore=semaphore,
            )

    @pytest.mark.asyncio
    async def test_execute_parallel_workflow_collects_errors(self, monkeypatch):
        app = _make_mock_app()
        app.observability = MagicMock()
        app.observability.create_workflow_counter = MagicMock(return_value=None)
        app.observability.create_repo_counter = MagicMock(return_value=None)
        app.observability.create_error_counter = MagicMock(return_value=MagicMock(add=MagicMock()))
        app.observability.start_workflow_trace = MagicMock()
        app.observability.start_workflow_trace.return_value.__enter__ = MagicMock()
        app.observability.start_workflow_trace.return_value.__exit__ = MagicMock()

        async def fake_process_single_repo(**kwargs):  # noqa: ANN003
            if kwargs["repo_path"] == "/repo/b":
                return RuntimeError("boom")
            return {"repo": kwargs["repo_path"]}

        monkeypatch.setattr(we, "process_single_repo", fake_process_single_repo, raising=True)

        execution_time, results, errors = await execute_parallel_workflow(
            app,
            adapter=MagicMock(),
            task={"type": "check"},
            adapter_name="prefect",
            workflow_id="wf_123",
            validated_repos=["/repo/a", "/repo/b"],
        )

        assert execution_time >= 0
        assert len(results) == 1
        assert len(errors) == 1

    @pytest.mark.asyncio
    async def test_finalize_workflow_execution_with_checkpoint_and_qc(self):
        app = _make_mock_app()
        app.qc.validate_post_execution = AsyncMock(return_value=False)
        app.session_buddy.update_checkpoint = AsyncMock(return_value=None)

        result = await finalize_workflow_execution(
            app=app,
            workflow_id="wf_123",
            adapter_name="prefect",
            task={"type": "check"},
            validated_repos=["/repo/a"],
            execution_time=1.0,
            successful_results=[{"status": "ok"}],
            errors=[],
            checkpoint_id="cp_123",
        )

        assert result["status"] == "completed"
        app.session_buddy.update_checkpoint.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_workflow_execution_error_updates_checkpoint(self):
        app = _make_mock_app()
        app.session_buddy.update_checkpoint = AsyncMock(return_value=None)

        with pytest.raises(AdapterError):
            await handle_workflow_execution_error(
                app=app,
                workflow_id="wf_123",
                adapter_name="prefect",
                task={"type": "check"},
                validated_repos=["/repo/a"],
                error=RuntimeError("boom"),
                checkpoint_id="cp_123",
            )

        app.session_buddy.update_checkpoint.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_workflow_with_fallback_success_and_failure(self, monkeypatch):
        app = _make_mock_app()
        app._persist_workflow_start = MagicMock()
        app._persist_workflow_end = MagicMock()
        fake_router = MagicMock()
        fake_router.generate_fallback_chain.return_value = [AdapterType.AGNO, AdapterType.PREFECT]
        monkeypatch.setattr(we, "TaskRouter", lambda: fake_router, raising=True)
        app.execute_workflow_parallel = AsyncMock(side_effect=[RuntimeError("boom"), {"ok": True}])

        result = await execute_workflow_with_fallback(app, {"type": "ai_task"}, ["/repo/a"])
        assert result["success"] is True
        assert result["adapter_used"] == AdapterType.PREFECT.value

        app.execute_workflow_parallel = AsyncMock(
            side_effect=[RuntimeError("boom"), RuntimeError("oops")]
        )
        result = await execute_workflow_with_fallback(app, {"type": "ai_task"}, ["/repo/a"])
        assert result["success"] is False
        assert len(result["errors"]) == 2

    @pytest.mark.asyncio
    async def test_execute_workflow_with_routing_switches_paths(self, monkeypatch):
        app = _make_mock_app()
        app.execute_workflow_with_fallback = AsyncMock(return_value={"success": True})
        app.execute_workflow_parallel = AsyncMock(return_value={"success": True})

        result = await execute_workflow_with_routing(
            app, {"type": "ai_task"}, ["/repo/a"], routing_strategy="balanced", enable_fallback=True
        )
        assert result["success"] is True
        app.execute_workflow_with_fallback.assert_awaited_once()

        fake_router = MagicMock()
        fake_router.select_adapter = AsyncMock(return_value=AdapterType.PREFECT)
        monkeypatch.setattr(we, "TaskRouter", lambda: fake_router, raising=True)

        result = await execute_workflow_with_routing(
            app,
            {"type": "ai_task"},
            ["/repo/a"],
            routing_strategy="balanced",
            enable_fallback=False,
        )
        assert result["adapter_used"] == AdapterType.PREFECT.value

    @pytest.mark.asyncio
    async def test_execute_workflow_parallel_success(self, monkeypatch):
        app = _make_mock_app()
        app._prepare_execution = AsyncMock(return_value=(MagicMock(), ["/repo/a"]))

        monkeypatch.setattr(
            we, "initialize_workflow_state", AsyncMock(return_value="wf_123"), raising=True
        )
        monkeypatch.setattr(
            we, "validate_pre_execution_qc", AsyncMock(return_value=None), raising=True
        )
        monkeypatch.setattr(
            we, "create_session_checkpoint", AsyncMock(return_value="cp_123"), raising=True
        )
        monkeypatch.setattr(
            we,
            "execute_parallel_workflow",
            AsyncMock(return_value=(1.5, [{"ok": True}], [])),
            raising=True,
        )
        monkeypatch.setattr(
            we,
            "finalize_workflow_execution",
            AsyncMock(return_value={"workflow_id": "wf_123", "status": "completed"}),
            raising=True,
        )

        result = await we.execute_workflow_parallel(
            app=app,
            task={"type": "check"},
            adapter_name="prefect",
            repos=["/repo/a"],
        )

        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_execute_workflow_parallel_error_path(self, monkeypatch):
        app = _make_mock_app()
        app._prepare_execution = AsyncMock(return_value=(MagicMock(), ["/repo/a"]))

        monkeypatch.setattr(
            we, "initialize_workflow_state", AsyncMock(return_value="wf_123"), raising=True
        )
        monkeypatch.setattr(
            we, "validate_pre_execution_qc", AsyncMock(return_value=None), raising=True
        )
        monkeypatch.setattr(
            we, "create_session_checkpoint", AsyncMock(return_value="cp_123"), raising=True
        )
        monkeypatch.setattr(
            we,
            "execute_parallel_workflow",
            AsyncMock(side_effect=RuntimeError("boom")),
            raising=True,
        )
        handle_error = AsyncMock(return_value=None)
        monkeypatch.setattr(we, "handle_workflow_execution_error", handle_error, raising=True)

        result = await we.execute_workflow_parallel(
            app=app,
            task={"type": "check"},
            adapter_name="prefect",
            repos=["/repo/a"],
        )

        assert result is None
        handle_error.assert_awaited_once()
