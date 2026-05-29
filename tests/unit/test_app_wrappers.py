"""Focused tests for wrapper-heavy portions of core.app."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import mahavishnu.core.app as app_module
from mahavishnu.core.app import MahavishnuApp
import mahavishnu.core.bootstrap as bootstrap_module


def _fake_config() -> SimpleNamespace:
    return SimpleNamespace(
        max_concurrent_workflows=4,
        resilience=SimpleNamespace(circuit_breaker_threshold=7, retry_base_delay=2),
        allowed_repo_paths=["/repos"],
        repos_config={"repos": [], "roles": []},
        auth=SimpleNamespace(enabled=False),
        health=SimpleNamespace(
            dependencies={"dhara": SimpleNamespace(use_tls=False, host="localhost", port=8683)}
        ),
    )


def _make_app_instance() -> MahavishnuApp:
    app = object.__new__(MahavishnuApp)
    app.config = _fake_config()
    app._health_endpoint = "health"
    app.active_workflows = set()
    app.workflow_queue = SimpleNamespace(qsize=lambda: 0)
    app.adapters = {}
    app.observability = None
    return app


class TestMahavishnuAppInit:
    def test_load_returns_instance(self, monkeypatch):
        monkeypatch.setattr(MahavishnuApp, "__init__", lambda self, config=None: None, raising=True)
        assert isinstance(MahavishnuApp.load(), MahavishnuApp)

    def test_init_sets_runtime_state(self, monkeypatch):
        calls: list[str] = []

        class _CircuitBreaker:
            def __init__(self, threshold, timeout):  # noqa: ANN001
                self.threshold = threshold
                self.timeout = timeout

        monkeypatch.setattr(app_module, "CircuitBreaker", _CircuitBreaker, raising=True)
        monkeypatch.setattr(
            app_module, "_load_repos_helper", lambda self: calls.append("repos"), raising=True
        )
        monkeypatch.setattr(
            bootstrap_module,
            "initialize_adapters",
            lambda self: calls.append("adapters"),
            raising=True,
        )
        monkeypatch.setattr(
            bootstrap_module,
            "set_app_context",
            lambda self: calls.append("context"),
            raising=True,
        )
        monkeypatch.setattr(
            app_module, "_init_observability_helper", lambda self: "obs", raising=True
        )
        monkeypatch.setattr(
            app_module, "_init_health_endpoint_helper", lambda self: "health", raising=True
        )
        monkeypatch.setattr(
            app_module,
            "_initialize_runtime_services_helper",
            lambda self: calls.append("runtime"),
            raising=True,
        )

        app = MahavishnuApp(config=_fake_config())

        assert app.dhara_url is not None
        assert app.circuit_breaker.threshold == 7
        assert app.circuit_breaker.timeout == 20
        assert app.observability == "obs"
        assert app.health_endpoint == "health"
        assert calls == ["repos", "adapters", "context", "runtime"]


class TestWrapperMethods:
    def test_sync_wrappers(self, monkeypatch):
        app = _make_app_instance()

        monkeypatch.setattr(
            app_module, "_init_terminal_manager_helper", lambda self: "terminal", raising=True
        )
        monkeypatch.setattr(
            app_module, "_initialize_runtime_services_helper", lambda self: "runtime", raising=True
        )
        monkeypatch.setattr(
            app_module, "_init_observability_helper", lambda self: "observability", raising=True
        )
        monkeypatch.setattr(
            app_module, "_init_health_endpoint_helper", lambda self: "health", raising=True
        )
        monkeypatch.setattr(
            app_module, "_init_pool_manager_helper", lambda self: "pool", raising=True
        )
        monkeypatch.setattr(
            app_module, "_init_memory_aggregator_helper", lambda self: "memory", raising=True
        )
        monkeypatch.setattr(
            app_module, "_init_learning_pipeline_helper", lambda self: "learning", raising=True
        )
        monkeypatch.setattr(app_module, "_load_config_helper", lambda: "config", raising=True)
        monkeypatch.setattr(app_module, "_load_repos_helper", lambda self: "loaded", raising=True)
        monkeypatch.setattr(
            bootstrap_module, "initialize_adapters", lambda self: "adapters", raising=True
        )
        monkeypatch.setattr(
            bootstrap_module, "set_app_context", lambda self: "context", raising=True
        )
        monkeypatch.setattr(
            app_module, "_resolve_dhara_url_helper", lambda config: "http://dhara", raising=True
        )
        monkeypatch.setattr(
            app_module, "_get_recovery_summary", AsyncMock(return_value={"ok": True}), raising=True
        )
        monkeypatch.setattr(
            app_module,
            "_get_recovered_routing_decisions",
            AsyncMock(return_value=[{"id": 1}]),
            raising=True,
        )
        monkeypatch.setattr(
            app_module, "_record_event_activity", lambda self, envelope: envelope, raising=True
        )
        monkeypatch.setattr(
            app_module, "_get_event_activity", lambda self, limit=25: [limit], raising=True
        )
        monkeypatch.setattr(
            app_module, "_record_fix_trace", lambda self, *args, **kwargs: None, raising=True
        )
        monkeypatch.setattr(
            app_module,
            "_get_fix_trace",
            lambda self, correlation_id=None, limit=25: [correlation_id, limit],
            raising=True,
        )
        monkeypatch.setattr(
            app_module,
            "_get_correlation_status",
            lambda self, correlation_id=None: {"id": correlation_id},
            raising=True,
        )
        monkeypatch.setattr(
            app_module, "_list_pending_approvals", lambda self: ["approval"], raising=True
        )
        monkeypatch.setattr(
            app_module, "_request_approval", lambda self, **kwargs: kwargs, raising=True
        )
        monkeypatch.setattr(
            app_module, "_respond_to_approval", lambda self, **kwargs: kwargs, raising=True
        )
        monkeypatch.setattr(
            app_module, "_persist_workflow_start_helper", lambda *args, **kwargs: None, raising=True
        )
        monkeypatch.setattr(
            app_module, "_persist_workflow_end_helper", lambda *args, **kwargs: None, raising=True
        )
        monkeypatch.setattr(
            app_module, "_get_repos_helper", lambda self, **kwargs: ["repo"], raising=True
        )
        monkeypatch.setattr(
            app_module,
            "_check_user_repo_permission_helper",
            lambda self, user_id, repo_path: True,
            raising=True,
        )
        monkeypatch.setattr(
            app_module, "_get_all_repos_helper", lambda self: [{"path": "/repo"}], raising=True
        )
        monkeypatch.setattr(
            app_module, "_get_all_repo_paths_helper", lambda self: ["/repo"], raising=True
        )
        monkeypatch.setattr(
            app_module, "_get_roles_helper", lambda self: [{"name": "dev"}], raising=True
        )
        monkeypatch.setattr(
            app_module,
            "_get_role_by_name_helper",
            lambda self, role_name: {"name": role_name},
            raising=True,
        )
        monkeypatch.setattr(
            app_module,
            "_get_repos_by_role_helper",
            lambda self, role_name: [{"role": role_name}],
            raising=True,
        )
        monkeypatch.setattr(
            app_module, "_get_all_nicknames_helper", lambda self: {"nick": "repo"}, raising=True
        )
        monkeypatch.setattr(
            app_module, "_is_healthy_helper", AsyncMock(return_value=True), raising=True
        )
        monkeypatch.setattr(
            app_module,
            "_get_active_workflows_helper",
            AsyncMock(return_value=["wf-1"]),
            raising=True,
        )
        monkeypatch.setattr(
            app_module, "_update_workflow_runtime_gauges_helper", lambda self: None, raising=True
        )

        assert app._init_terminal_manager() == "terminal"
        assert app._initialize_runtime_services() == "runtime"
        assert app._init_observability() == "observability"
        assert app._init_health_endpoint() == "health"
        assert app._init_pool_manager() == "pool"
        assert app._init_memory_aggregator() == "memory"
        assert app._init_learning_pipeline() == "learning"
        assert app._load_config() == "config"
        app._load_repos()
        app._initialize_adapters()
        app._set_app_context()
        assert app._resolve_dhara_url() == "http://dhara"

        assert app.health_endpoint == "health"
        assert asyncio.run(app.get_recovery_summary()) == {"ok": True}
        assert asyncio.run(app.get_recovered_routing_decisions()) == [{"id": 1}]
        app.record_event_activity({"id": "event"})
        assert app.get_event_activity(limit=3) == [3]
        app.record_fix_trace("c1", "stage", "message")
        assert app.get_fix_trace("c1", limit=4) == ["c1", 4]
        assert app.get_correlation_status("c2") == {"id": "c2"}
        assert app.list_pending_approvals() == ["approval"]
        assert app.request_approval("deploy", {"id": 1}) == {
            "approval_type": "deploy",
            "context": {"id": 1},
            "options": None,
            "timeout_minutes": None,
        }
        assert app.respond_to_approval("r1", True) == {
            "request_id": "r1",
            "approved": True,
            "selected_option": None,
            "rejection_reason": None,
        }
        app._persist_workflow_start("e1", "wf", {"x": 1})
        app._persist_workflow_end("e1", "wf", "completed")
        assert app.get_repos(tag="x") == ["repo"]
        assert app._check_user_repo_permission("u", "/repo") is True
        assert app.get_all_repos() == [{"path": "/repo"}]
        assert app.get_all_repo_paths() == ["/repo"]
        assert app.get_roles() == [{"name": "dev"}]
        assert app.get_role_by_name("dev") == {"name": "dev"}
        assert app.get_repos_by_role("dev") == [{"role": "dev"}]
        assert app.get_all_nicknames() == {"nick": "repo"}
        assert MahavishnuApp.get_repo_nicknames({"nicknames": ["alpha"], "path": "/repo"}) == [
            "alpha"
        ]
        assert asyncio.run(app.is_healthy()) is True
        assert asyncio.run(app.get_active_workflows()) == ["wf-1"]
        app._update_workflow_runtime_gauges()

    @pytest.mark.asyncio
    async def test_async_wrappers(self, monkeypatch):
        app = _make_app_instance()

        monkeypatch.setattr(
            app_module, "_start_poller_helper", AsyncMock(return_value=None), raising=True
        )
        monkeypatch.setattr(
            app_module, "_wait_for_dependencies_helper", AsyncMock(return_value=True), raising=True
        )
        monkeypatch.setattr(
            app_module, "_stop_poller_helper", AsyncMock(return_value=None), raising=True
        )
        monkeypatch.setattr(
            app_module,
            "_start_learning_pipeline_helper",
            AsyncMock(return_value=None),
            raising=True,
        )
        monkeypatch.setattr(
            app_module, "_stop_learning_pipeline_helper", AsyncMock(return_value=None), raising=True
        )
        monkeypatch.setattr(
            app_module,
            "_initialize_worktree_coordinator_helper",
            AsyncMock(return_value=None),
            raising=True,
        )
        monkeypatch.setattr(
            app_module,
            "_recover_workflow_state_from_dhara_helper",
            AsyncMock(return_value=None),
            raising=True,
        )
        monkeypatch.setattr(
            app_module,
            "_recover_approvals_from_dhara_helper",
            AsyncMock(return_value=None),
            raising=True,
        )
        monkeypatch.setattr(
            app_module,
            "_prepare_execution_helper",
            AsyncMock(return_value=("adapter", ["/repo"])),
            raising=True,
        )
        monkeypatch.setattr(
            app_module,
            "_check_dependency_health_helper",
            AsyncMock(return_value=None),
            raising=True,
        )
        monkeypatch.setattr(
            app_module,
            "_initialize_workflow_state_helper",
            AsyncMock(return_value="wf-1"),
            raising=True,
        )
        monkeypatch.setattr(
            app_module,
            "_validate_pre_execution_qc_helper",
            AsyncMock(return_value=None),
            raising=True,
        )
        monkeypatch.setattr(
            app_module,
            "_create_session_checkpoint_helper",
            AsyncMock(return_value="cp-1"),
            raising=True,
        )
        monkeypatch.setattr(
            app_module,
            "_process_single_repo_helper",
            AsyncMock(return_value={"ok": True}),
            raising=True,
        )
        monkeypatch.setattr(
            app_module,
            "_execute_parallel_workflow_helper",
            AsyncMock(return_value=(1.0, [{"ok": True}], [])),
            raising=True,
        )
        monkeypatch.setattr(
            app_module,
            "_finalize_workflow_execution_helper",
            AsyncMock(return_value={"status": "completed"}),
            raising=True,
        )
        monkeypatch.setattr(
            app_module,
            "_handle_workflow_execution_error_helper",
            AsyncMock(return_value=None),
            raising=True,
        )
        monkeypatch.setattr(
            app_module,
            "_execute_workflow_parallel_helper",
            AsyncMock(return_value={"status": "ok"}),
            raising=True,
        )
        monkeypatch.setattr(
            app_module,
            "_execute_workflow_with_fallback_helper",
            AsyncMock(return_value={"status": "ok"}),
            raising=True,
        )
        monkeypatch.setattr(
            app_module,
            "_execute_workflow_with_routing_helper",
            AsyncMock(return_value={"status": "ok"}),
            raising=True,
        )
        monkeypatch.setattr(
            app_module, "_get_recovery_summary", AsyncMock(return_value={"ok": True}), raising=True
        )

        await app.start_poller()
        assert await app.wait_for_dependencies() is True
        await app.stop_poller()
        await app.start_learning_pipeline()
        await app.stop_learning_pipeline()
        await app.initialize_worktree_coordinator()
        await app._recover_workflow_state_from_dhara()
        await app._recover_approvals_from_dhara()
        assert await app._prepare_execution("prefect", {"type": "check"}, ["/repo"], None) == (
            "adapter",
            ["/repo"],
        )
        await app._check_dependency_health()
        assert (
            await app._initialize_workflow_state({"type": "check"}, "prefect", ["/repo"]) == "wf-1"
        )
        await app._validate_pre_execution_qc("wf-1", ["/repo"])
        assert (
            await app._create_session_checkpoint({"type": "check"}, "prefect", ["/repo"]) == "cp-1"
        )
        assert await app._process_single_repo(
            "a", {"type": "check"}, "prefect", "wf-1", "/repo", 1, asyncio.Semaphore(1)
        ) == {"ok": True}
        assert await app._execute_parallel_workflow(
            "a", {"type": "check"}, "prefect", "wf-1", ["/repo"]
        ) == (1.0, [{"ok": True}], [])
        assert await app._finalize_workflow_execution(
            "wf-1", "prefect", {"type": "check"}, ["/repo"], 1.0, [{"ok": True}], [], None
        ) == {"status": "completed"}
        await app._handle_workflow_execution_error(
            "wf-1", "prefect", {"type": "check"}, ["/repo"], RuntimeError("boom"), None
        )
        assert await app.execute_workflow_parallel({"type": "check"}, "prefect", ["/repo"]) == {
            "status": "ok"
        }
        assert await app.execute_workflow_with_fallback({"type": "check"}, ["/repo"]) == {
            "status": "ok"
        }
        assert await app.execute_workflow_with_routing({"type": "check"}, ["/repo"]) == {
            "status": "ok"
        }

    @pytest.mark.asyncio
    async def test_execute_workflow_success_and_error(self, monkeypatch):
        app = _make_app_instance()
        adapter = AsyncMock()
        adapter.execute = AsyncMock(return_value={"status": "ok"})
        workflow_counter = MagicMock(add=MagicMock())
        app.observability = MagicMock()
        app.observability.create_workflow_counter = MagicMock(return_value=workflow_counter)
        app.observability.create_error_counter = MagicMock(return_value=MagicMock(add=MagicMock()))
        app.opensearch_integration = MagicMock()
        app.opensearch_integration.log_error = AsyncMock(return_value=None)

        monkeypatch.setattr(
            app_module,
            "_prepare_execution_helper",
            AsyncMock(return_value=(adapter, ["/repo"])),
            raising=True,
        )

        result = await app.execute_workflow({"type": "check"}, "prefect", ["/repo"])
        assert result == {"status": "ok"}
        workflow_counter.add.assert_called_once()

        adapter.execute = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(app_module.AdapterError):
            await app.execute_workflow({"type": "check"}, "prefect", ["/repo"])
