"""Unit tests for core.repository_surface."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.core.errors import ValidationError
import mahavishnu.core.repository_surface as rs


class _Metric:
    def __init__(self) -> None:
        self.labels_kwargs: dict[str, object] | None = None
        self.values: list[float] = []

    def labels(self, **kwargs):  # noqa: ANN003
        self.labels_kwargs = kwargs
        return self

    def set(self, value: float) -> None:
        self.values.append(value)


def _make_app(**kwargs):
    app = SimpleNamespace(
        config=SimpleNamespace(
            allowed_repo_paths=kwargs.get("allowed_repo_paths", []), max_concurrent_workflows=4
        ),
        repos_config=kwargs.get("repos_config", {"repos": [], "roles": []}),
        _dhara_state=kwargs.get("_dhara_state"),
        rbac_manager=kwargs.get(
            "rbac_manager", SimpleNamespace(check_permission=AsyncMock(return_value=True))
        ),
        adapters=kwargs.get("adapters", {}),
        workflow_state_manager=kwargs.get("workflow_state_manager", AsyncMock()),
        active_workflows=kwargs.get("active_workflows", []),
        workflow_queue=kwargs.get("workflow_queue", SimpleNamespace(qsize=lambda: 0)),
    )
    if "roles_config" in kwargs:
        app.roles_config = kwargs["roles_config"]
    return app


class TestValidatePath:
    def test_rejects_directory_traversal(self):
        with pytest.raises(ValidationError, match="directory traversal"):
            rs.validate_path("../etc/passwd")

    def test_rejects_outside_allowed_base(self, tmp_path):
        safe = tmp_path / "safe.txt"
        safe.write_text("ok")
        with pytest.raises(ValidationError, match="outside allowed directory"):
            rs.validate_path(str(safe), allowed_base_paths=["/etc"])

    def test_allows_safe_path(self, tmp_path):
        safe = tmp_path / "safe.txt"
        safe.write_text("ok")
        assert rs.validate_path(str(safe), allowed_base_paths=[str(tmp_path)]) == safe.resolve()


class TestWorkflowPersistence:
    def test_noop_when_no_dhara_state(self):
        app = _make_app()
        rs.persist_workflow_start(app, "exec-1", "demo", {"a": 1})
        rs.persist_workflow_end(app, "exec-1", "demo", "completed")

    def test_schedule_put_called(self):
        dhara_state = SimpleNamespace(schedule_put=MagicMock())
        app = _make_app(_dhara_state=dhara_state)

        rs.persist_workflow_start(app, "exec-1", "demo", {"a": 1})
        rs.persist_workflow_end(app, "exec-1", "demo", "failed", error="boom")

        assert dhara_state.schedule_put.call_count == 2
        first_call = dhara_state.schedule_put.call_args_list[0]
        second_call = dhara_state.schedule_put.call_args_list[1]
        assert first_call.args[0] == "workflow/v1/exec-1"
        assert first_call.args[1]["status"] == "running"
        assert second_call.args[1]["status"] == "failed"


class TestRepoFiltering:
    def test_filter_repos_by_criteria(self):
        repos = [
            {"path": "a", "tags": ["x"], "role": "dev"},
            {"path": "b", "tags": ["y"], "role": "ops"},
            {"path": "c"},
        ]
        assert rs._filter_repos_by_criteria(repos, "x", None) == ["a"]
        assert rs._filter_repos_by_criteria(repos, None, "ops") == ["b"]
        assert rs._filter_repos_by_criteria(repos, None, None) == ["a", "b", "c"]

    def test_collect_valid_repo_variants(self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        repo.mkdir()
        app = _make_app(allowed_repo_paths=[str(tmp_path)])
        logger = MagicMock()

        assert rs._collect_valid_repo(app, str(repo), None, logger) == str(repo.resolve())

        missing = tmp_path / "missing"
        assert rs._collect_valid_repo(app, str(missing), None, logger) is None

        monkeypatch.setattr(
            rs, "check_user_repo_permission", lambda *args, **kwargs: False, raising=True
        )
        assert rs._collect_valid_repo(app, str(repo), "user-1", logger) is None

        monkeypatch.setattr(
            rs,
            "validate_path",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                ValidationError(message="bad", details={})
            ),
            raising=True,
        )
        assert rs._collect_valid_repo(app, str(repo), None, logger) is None

    def test_get_repos_validations_and_filtering(self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        repo.mkdir()
        app = _make_app(
            allowed_repo_paths=[str(tmp_path)],
            repos_config={
                "repos": [{"path": str(repo), "tags": ["python"], "role": "dev"}],
                "roles": [{"name": "dev"}],
            },
        )

        with pytest.raises(ValidationError, match="Invalid tag"):
            rs.get_repos(app, tag="bad tag")

        with pytest.raises(ValidationError, match="Invalid role"):
            rs.get_repos(app, role="ops")

        monkeypatch.setattr(
            rs, "_collect_valid_repo", lambda *args, **kwargs: str(repo.resolve()), raising=True
        )
        assert rs.get_repos(app, tag="python", role="dev") == [str(repo.resolve())]


class TestPermissions:
    def test_check_user_repo_permission_asyncio_thread_branch(self, monkeypatch):
        async def _check_permission(user_id, repo_path, permission):  # noqa: ANN001
            return True

        app = _make_app(rbac_manager=SimpleNamespace(check_permission=_check_permission))
        monkeypatch.setattr(asyncio, "get_running_loop", lambda: object(), raising=True)

        class _Future:
            def __init__(self, value):
                self._value = value

            def result(self, timeout=None):  # noqa: ARG002
                return self._value

        class _Executor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):  # noqa: ANN001,ANN002,ANN003
                return False

            def submit(self, fn, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003
                return _Future(fn(*args, **kwargs))

        monkeypatch.setattr(
            rs.concurrent.futures, "ThreadPoolExecutor", lambda: _Executor(), raising=True
        )

        assert rs.check_user_repo_permission(app, "u1", "/repo") is True

    def test_check_user_repo_permission_asyncio_run_branch(self, monkeypatch):
        async def _check_permission(user_id, repo_path, permission):  # noqa: ANN001
            return False

        app = _make_app(rbac_manager=SimpleNamespace(check_permission=_check_permission))
        monkeypatch.setattr(
            asyncio,
            "get_running_loop",
            lambda: (_ for _ in ()).throw(RuntimeError("no loop")),
            raising=True,
        )
        assert rs.check_user_repo_permission(app, "u1", "/repo") is False

    def test_check_user_repo_permission_exception_falls_back_true(self, monkeypatch):
        async def _boom(user_id, repo_path, permission):  # noqa: ANN001
            raise ValueError("boom")

        app = _make_app(rbac_manager=SimpleNamespace(check_permission=_boom))
        monkeypatch.setattr(
            asyncio,
            "get_running_loop",
            lambda: (_ for _ in ()).throw(RuntimeError("no loop")),
            raising=True,
        )
        assert rs.check_user_repo_permission(app, "u1", "/repo") is True


class TestAccessors:
    def test_role_and_repo_accessors(self):
        app = _make_app(
            repos_config={
                "repos": [
                    {"path": "a", "name": "repo-a", "role": "dev"},
                    {"path": "b", "name": "repo-b", "role": "ops"},
                ],
                "roles": [{"name": "dev"}, {"name": "ops"}],
            },
            roles_config=[{"name": "dev"}, {"name": "ops"}],
        )

        assert rs.get_all_repos(app)[0]["path"] == "a"
        assert rs.get_all_repo_paths(app) == ["a", "b"]
        assert rs.get_roles(app) == [{"name": "dev"}, {"name": "ops"}]
        assert rs.get_role_by_name(app, "ops") == {"name": "ops"}
        assert rs.get_role_by_name(app, "missing") is None
        with pytest.raises(ValidationError, match="Invalid role"):
            rs.get_repos_by_role(app, "missing")
        assert rs.get_repos_by_role(app, "dev") == [{"path": "a", "name": "repo-a", "role": "dev"}]

    def test_all_nicknames(self):
        app = _make_app(
            repos_config={
                "repos": [{"path": "a", "name": "repo-a", "nicknames": ["alpha", "beta"]}]
            }
        )
        assert rs.get_all_nicknames(app) == {"alpha": "repo-a", "beta": "repo-a"}


class TestHealthAndMetrics:
    @pytest.mark.asyncio
    async def test_is_healthy_branches(self):
        app = _make_app(adapters={})
        assert await rs.is_healthy(app) is False

        healthy_adapter = SimpleNamespace(get_health=AsyncMock(return_value={"status": "healthy"}))
        unhealthy_adapter = SimpleNamespace(
            get_health=AsyncMock(return_value={"status": "degraded"})
        )
        app = _make_app(adapters={"a": healthy_adapter, "b": unhealthy_adapter})
        assert await rs.is_healthy(app) is False
        app = _make_app(adapters={"a": healthy_adapter})
        assert await rs.is_healthy(app) is True

        boom_adapter = SimpleNamespace(get_health=AsyncMock(side_effect=RuntimeError("boom")))
        app = _make_app(adapters={"a": boom_adapter})
        assert await rs.is_healthy(app) is False

    @pytest.mark.asyncio
    async def test_get_active_workflows(self):
        workflow_state_manager = AsyncMock()
        workflow_state_manager.list_workflows.return_value = [
            {"id": "w1"},
            {"id": ""},
            {"id": "w2"},
        ]
        app = _make_app(workflow_state_manager=workflow_state_manager)
        assert await rs.get_active_workflows(app) == ["w1", "w2"]

    def test_update_workflow_runtime_gauges(self):
        active = _Metric()
        queue = _Metric()
        utilization = _Metric()
        app = _make_app(
            active_workflows=["a", "b"],
            workflow_queue=SimpleNamespace(qsize=lambda: 3),
        )

        original = (
            rs.mahavishnu_active_workflows,
            rs.mahavishnu_workflow_queue_depth,
            rs.mahavishnu_workflow_concurrency_utilization,
        )
        try:
            rs.mahavishnu_active_workflows = active
            rs.mahavishnu_workflow_queue_depth = queue
            rs.mahavishnu_workflow_concurrency_utilization = utilization
            rs.update_workflow_runtime_gauges(app)
        finally:
            (
                rs.mahavishnu_active_workflows,
                rs.mahavishnu_workflow_queue_depth,
                rs.mahavishnu_workflow_concurrency_utilization,
            ) = original

        assert active.values == [2]
        assert queue.values == [3]
        assert utilization.values == [0.5]
