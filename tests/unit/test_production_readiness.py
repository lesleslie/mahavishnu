"""Unit tests for core.production_readiness."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import mahavishnu.core.production_readiness as pr
from mahavishnu.core.production_readiness import (
    IntegrationTestSuite,
    PerformanceBenchmark,
    ProductionReadinessChecker,
    _calculate_overall_assessment,
    run_production_readiness_suite,
)


class _FakeAdapter:
    def __init__(
        self, health: dict[str, object] | None = None, error: Exception | None = None
    ) -> None:
        self.health = health or {"status": "healthy"}
        self.error = error

    async def get_health(self):
        if self.error is not None:
            raise self.error
        return self.health


def _make_config(
    *,
    auth_enabled: bool = True,
    secret: str = "x" * 40,
    algorithm: str = "HS256",
    repos_path: str = "/tmp/repos.txt",
    max_concurrent_workflows: int = 8,
    llm_model: str = "gpt-test",
    ollama_base_url: str = "http://localhost:11434",
    retry_max_attempts: int = 3,
    timeout_per_repo: int = 120,
    opensearch_use_ssl: bool = True,
    opensearch_ssl: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        auth=SimpleNamespace(
            enabled=auth_enabled,
            secret=secret,
            algorithm=algorithm,
        ),
        resilience=SimpleNamespace(
            retry_max_attempts=retry_max_attempts,
            timeout_per_repo=timeout_per_repo,
        ),
        opensearch=SimpleNamespace(use_ssl=opensearch_ssl),
        opensearch_use_ssl=opensearch_use_ssl,
        repos_path=repos_path,
        max_concurrent_workflows=max_concurrent_workflows,
        llm_model=llm_model,
        ollama_base_url=ollama_base_url,
    )


def _make_app(
    *,
    config: object,
    adapters: dict[str, object] | None = None,
    repos: list[str] | None = None,
    execute_workflow_result: object | None = None,
    execute_workflow_error: Exception | None = None,
    rbac_result: bool = True,
    rbac_error: Exception | None = None,
    state_manager: object | None = None,
    observability: object | None = None,
):
    async def _execute_workflow(task, adapter_name, repo_subset):  # noqa: ANN001
        if execute_workflow_error is not None:
            raise execute_workflow_error
        return execute_workflow_result or {
            "status": "completed",
            "task": task,
            "adapter_name": adapter_name,
            "repos": repo_subset,
        }

    async def _check_permission(user, repo, permission):  # noqa: ANN001
        if rbac_error is not None:
            raise rbac_error
        return rbac_result

    if state_manager is None:
        state_store: dict[str, dict[str, object]] = {}

        async def _create(workflow_id, task, workflow_repos):  # noqa: ANN001
            state_store[workflow_id] = {
                "id": workflow_id,
                "task": task,
                "repos": workflow_repos,
            }
            return state_store[workflow_id]

        async def _get(workflow_id):  # noqa: ANN001
            return state_store.get(workflow_id)

        async def _delete(workflow_id):  # noqa: ANN001
            state_store.pop(workflow_id, None)

        state_manager = SimpleNamespace(create=_create, get=_get, delete=_delete)

    if observability is None:

        class _Counter:
            def __init__(self) -> None:
                self.calls: list[tuple[int, dict[str, str] | None]] = []

            def add(self, value, labels=None):  # noqa: ANN001
                self.calls.append((value, labels))

        class _Observability:
            def __init__(self) -> None:
                self.counter = _Counter()
                self.logged: list[tuple[str, dict[str, object] | None]] = []
                self.logs = ["log-1", "log-2"]

            def log_info(self, message, metadata=None):  # noqa: ANN001
                self.logged.append((message, metadata))

            def create_workflow_counter(self):
                return self.counter

            def get_logs(self, limit=10):  # noqa: ANN001
                return self.logs[:limit]

        observability = _Observability()

    return SimpleNamespace(
        config=config,
        adapters=adapters or {},
        get_repos=lambda: repos or [],
        execute_workflow=_execute_workflow,
        rbac_manager=SimpleNamespace(check_permission=_check_permission),
        workflow_state_manager=state_manager,
        observability=observability,
    )


def _run_in_new_loop(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _sync_check(name: str, result: bool):
    def _check(self):  # noqa: ANN001
        self.results[name[7:]] = {"status": "PASS" if result else "FAIL"}
        return result

    _check.__name__ = name
    return _check


def _async_check(name: str, result: bool):
    async def _check(self):  # noqa: ANN001
        self.results[name[7:]] = {"status": "PASS" if result else "FAIL"}
        return result

    _check.__name__ = name
    return _check


def _raising_check(name: str):
    def _check(self):  # noqa: ANN001
        raise RuntimeError("boom")

    _check.__name__ = name
    return _check


def _sync_suite_test(result: bool):
    def _test(self):  # noqa: ANN001
        return result

    return _test


def _async_suite_test(result: bool):
    async def _test(self):  # noqa: ANN001
        return result

    return _test


def _raising_suite_test():
    def _test(self):  # noqa: ANN001
        raise RuntimeError("boom")

    return _test


def test_config_resource_security_and_adapter_checks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _make_config(repos_path=str(tmp_path / "repos.txt"))
    checker = ProductionReadinessChecker(_make_app(config=config))

    assert checker._check_config_validity() is True
    assert checker.results["config_validity"]["status"] == "PASS"

    config.auth.secret = "short"
    assert checker._check_config_validity() is False

    missing_field_config = SimpleNamespace(
        auth=SimpleNamespace(enabled=True, secret="x" * 40, algorithm="HS256"),
        resilience=SimpleNamespace(retry_max_attempts=3, timeout_per_repo=120),
        repos_path=str(tmp_path / "repos.txt"),
        max_concurrent_workflows=8,
        ollama_base_url="http://localhost:11434",
    )
    assert (
        ProductionReadinessChecker(_make_app(config=missing_field_config))._check_config_validity()
        is False
    )

    class _BrokenApp:
        @property
        def config(self):  # noqa: D401
            raise RuntimeError("broken")

        adapters: dict[str, object] = {}

    assert ProductionReadinessChecker(_BrokenApp())._check_config_validity() is False

    config = _make_config(
        repos_path=str(tmp_path / "repos.txt"),
        max_concurrent_workflows=5,
        retry_max_attempts=4,
        timeout_per_repo=60,
    )
    checker = ProductionReadinessChecker(_make_app(config=config))
    assert checker._check_resource_limits() is True
    assert checker.results["resource_limits"]["status"] == "PASS"

    config.max_concurrent_workflows = 0
    assert checker._check_resource_limits() is False
    config.max_concurrent_workflows = 5
    config.resilience.retry_max_attempts = 11
    assert checker._check_resource_limits() is False
    config.resilience.retry_max_attempts = 4
    config.resilience.timeout_per_repo = 10
    assert checker._check_resource_limits() is False

    config = _make_config(auth_enabled=False, opensearch_ssl=False)
    checker = ProductionReadinessChecker(_make_app(config=config))
    assert checker._check_security_settings() is True
    assert checker.results["security_settings"]["status"] == "PASS"

    config.auth.enabled = True
    config.auth.secret = "short"
    assert checker._check_security_settings() is False
    config.auth.secret = "x" * 40
    config.auth.algorithm = "bad"
    assert checker._check_security_settings() is False
    config.auth.algorithm = "HS256"
    assert checker._check_security_settings() is True

    healthy_app = _make_app(
        config=_make_config(),
        adapters={
            "a": _FakeAdapter(),
            "b": _FakeAdapter(),
        },
    )
    checker = ProductionReadinessChecker(healthy_app)
    monkeypatch.setattr(pr.asyncio, "run", _run_in_new_loop, raising=True)
    assert checker._check_adapter_health() is True
    assert checker.results["adapter_health"]["status"] == "PASS"

    unhealthy_app = _make_app(
        config=_make_config(),
        adapters={
            "a": _FakeAdapter(),
            "b": _FakeAdapter({"status": "unhealthy"}),
        },
    )
    assert ProductionReadinessChecker(unhealthy_app)._check_adapter_health() is False

    error_app = _make_app(
        config=_make_config(),
        adapters={
            "a": _FakeAdapter(),
            "b": _FakeAdapter(error=RuntimeError("bad")),
        },
    )
    assert ProductionReadinessChecker(error_app)._check_adapter_health() is False

    class _BrokenAdaptersApp:
        config = _make_config()

        @property
        def adapters(self):  # noqa: D401
            raise RuntimeError("broken")

    assert ProductionReadinessChecker(_BrokenAdaptersApp())._check_adapter_health() is False


@pytest.mark.asyncio
async def test_workflow_execution_and_integration_suite_paths(tmp_path: Path) -> None:
    app = _make_app(
        config=_make_config(repos_path=str(tmp_path / "repos.txt")),
        adapters={"adapter": _FakeAdapter()},
        repos=[str(tmp_path / "repo-a"), str(tmp_path / "repo-b")],
    )
    checker = ProductionReadinessChecker(app)

    assert await checker._check_workflow_execution() is True
    assert checker.results["workflow_execution"]["status"] == "PASS"

    no_repos = _make_app(
        config=_make_config(repos_path=str(tmp_path / "repos.txt")),
        adapters={"adapter": _FakeAdapter()},
        repos=[],
    )
    assert await ProductionReadinessChecker(no_repos)._check_workflow_execution() is True

    no_adapters = _make_app(
        config=_make_config(repos_path=str(tmp_path / "repos.txt")),
        adapters={},
        repos=[str(tmp_path / "repo-a")],
    )
    assert await ProductionReadinessChecker(no_adapters)._check_workflow_execution() is False

    failing = _make_app(
        config=_make_config(repos_path=str(tmp_path / "repos.txt")),
        adapters={"adapter": _FakeAdapter()},
        repos=[str(tmp_path / "repo-a")],
        execute_workflow_result={"status": "failed"},
    )
    assert await ProductionReadinessChecker(failing)._check_workflow_execution() is False

    raising = _make_app(
        config=_make_config(repos_path=str(tmp_path / "repos.txt")),
        adapters={"adapter": _FakeAdapter()},
        repos=[str(tmp_path / "repo-a")],
        execute_workflow_error=RuntimeError("boom"),
    )
    assert await ProductionReadinessChecker(raising)._check_workflow_execution() is False

    suite_app = _make_app(
        config=_make_config(repos_path=str(tmp_path / "repos.txt")),
        adapters={"adapter": _FakeAdapter()},
        repos=[str(tmp_path / "repo-a")],
    )
    suite = IntegrationTestSuite(suite_app)
    assert await suite._test_basic_workflow_execution() is True
    assert await suite._test_rbac_permissions() is True
    assert await suite._test_workflow_state_management() is True
    assert await suite._test_observation_logging() is True
    assert suite.test_results

    no_adapter_suite = IntegrationTestSuite(_make_app(config=_make_config(), adapters={}, repos=[]))
    assert await no_adapter_suite._test_basic_workflow_execution() is True

    no_repo_suite = IntegrationTestSuite(
        _make_app(config=_make_config(), adapters={"adapter": object()}, repos=[])
    )
    assert await no_repo_suite._test_basic_workflow_execution() is True

    class _BadRbac:
        async def check_permission(self, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003
            raise RuntimeError("rbac")

    bad_rbac_suite = IntegrationTestSuite(
        _make_app(config=_make_config(), adapters={"adapter": object()}, repos=["repo"])
    )
    bad_rbac_suite.app.rbac_manager = _BadRbac()
    assert await bad_rbac_suite._test_rbac_permissions() is False

    class _BadStateManager:
        async def create(self, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003
            raise RuntimeError("state")

        async def get(self, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003
            raise RuntimeError("state")

        async def delete(self, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003
            raise RuntimeError("state")

    bad_state_suite = IntegrationTestSuite(
        _make_app(config=_make_config(), adapters={"adapter": object()}, repos=["repo"])
    )
    bad_state_suite.app.workflow_state_manager = _BadStateManager()
    assert await bad_state_suite._test_workflow_state_management() is False

    assert (
        await IntegrationTestSuite(
            _make_app(config=_make_config(), adapters={"adapter": object()}, repos=["repo"])
        )._test_observation_logging()
        is True
    )

    no_obs_suite = IntegrationTestSuite(
        _make_app(
            config=_make_config(),
            adapters={"adapter": object()},
            repos=["repo"],
            observability=False,
        )
    )
    assert await no_obs_suite._test_observation_logging() is True

    class _BadObs:
        def log_info(self, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003
            raise RuntimeError("obs")

        def create_workflow_counter(self):
            return None

        def get_logs(self, limit=10):  # noqa: ANN001
            return []

    bad_obs_suite = IntegrationTestSuite(
        _make_app(config=_make_config(), adapters={"adapter": object()}, repos=["repo"])
    )
    bad_obs_suite.app.observability = _BadObs()
    assert await bad_obs_suite._test_observation_logging() is False


@pytest.mark.asyncio
async def test_suite_runners_and_benchmarks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Defensive cleanup: a sibling test file (``test_production_cli``) drives
    # ``unittest.mock.patch`` on these classes via context managers. The
    # teardown path stores the *return value* of ``__enter__`` (a MagicMock)
    # on the app and iterates it in the ``finally`` block, so the patcher's
    # own ``__exit__`` is never invoked and the real class never gets
    # restored. If we run after such a leak, ``pr.ProductionReadinessChecker``
    # is a MagicMock, ``monkeypatch.setattr`` lands on the mock (not the
    # class), and ``run_production_readiness_suite`` ends up building its
    # result from a mock that returns ``{"status": "ok", "checks": []}``
    # instead of the expected ``{"summary": {...}}`` shape. Restore the
    # originals for the duration of this test and put any leaked mock back
    # afterwards so we never observe (or mutate) a corrupted module.
    leaked: dict[str, object] = {}
    real_classes = {
        "ProductionReadinessChecker": ProductionReadinessChecker,
        "IntegrationTestSuite": IntegrationTestSuite,
        "PerformanceBenchmark": PerformanceBenchmark,
    }
    for attr, real_cls in real_classes.items():
        current = getattr(pr, attr, None)
        if isinstance(current, MagicMock):
            leaked[attr] = current
            setattr(pr, attr, real_cls)
    try:
        # Build a private subclass so the per-method stubs are applied to *this*
        # class only, not to the shared ``ProductionReadinessChecker`` /
        # ``IntegrationTestSuite`` classes. This makes the test self-contained
        # and immune to leaked ``unittest.mock.patch`` substitutions on the
        # originals. The originals retain their real implementations for any
        # other code path that needs them.
        checker_cls = type(
            "_PatchedReadinessChecker",
            (ProductionReadinessChecker,),
            {
                "_check_config_validity": _sync_check("_check_config_validity", True),
                "_check_adapter_health": _sync_check("_check_adapter_health", False),
                "_check_repo_accessibility": _raising_check("_check_repo_accessibility"),
                "_check_workflow_execution": _async_check("_check_workflow_execution", True),
                "_check_resource_limits": _sync_check("_check_resource_limits", True),
                "_check_security_settings": _sync_check("_check_security_settings", False),
            },
        )
        checker = checker_cls(
            _make_app(config=_make_config(repos_path=str(tmp_path / "repos.txt")))
        )

        summary = await checker.run_all_checks()
        assert summary["summary"]["total_checks"] == 6
        assert summary["summary"]["checks_passed"] == 3
        assert summary["summary"]["status"] == "FAIL"
        assert "config_validity" in summary["details"]

        suite_cls = type(
            "_PatchedIntegrationTestSuite",
            (IntegrationTestSuite,),
            {
                "_test_basic_workflow_execution": _async_suite_test(True),
                "_test_rbac_permissions": _async_suite_test(False),
                "_test_workflow_state_management": _raising_suite_test(),
                "_test_observation_logging": _async_suite_test(True),
            },
        )
        suite = suite_cls(
            _make_app(config=_make_config(), adapters={"adapter": object()}, repos=["repo"])
        )

        test_summary = await suite.run_all_tests()
        assert test_summary["summary"]["total_tests"] == 4
        assert test_summary["summary"]["tests_passed"] == 2
        assert test_summary["summary"]["status"] == "FAIL"

        app = _make_app(
            config=_make_config(),
            adapters={"adapter": object()},
            repos=["repo-a", "repo-b", "repo-c"],
        )
        benchmark = PerformanceBenchmark(app)
        bench_summary = await benchmark.run_benchmarks()
        assert bench_summary["summary"]["status"] in {"EXCELLENT", "GOOD"}
        assert set(bench_summary["benchmarks"]) == {
            "workflow_execution",
            "concurrent_workflows",
            "repo_operations",
        }

        empty_benchmark = PerformanceBenchmark(
            _make_app(config=_make_config(), adapters={}, repos=[])
        )
        await empty_benchmark._benchmark_workflow_execution()
        await empty_benchmark._benchmark_concurrent_workflows()
        await empty_benchmark._benchmark_repo_operations()
        assert empty_benchmark.benchmarks == {}

        async def _fake_run_all_checks(self):  # noqa: ANN001
            return {"summary": {"score_percentage": 95}, "details": {}}

        async def _fake_run_all_tests(self):  # noqa: ANN001
            return {"summary": {"score_percentage": 90}, "details": []}

        async def _fake_run_benchmarks(self):  # noqa: ANN001
            return {"summary": {"performance_score": 92}, "benchmarks": {}}

        monkeypatch.setattr(
            pr.ProductionReadinessChecker, "run_all_checks", _fake_run_all_checks, raising=True
        )
        monkeypatch.setattr(
            pr.IntegrationTestSuite, "run_all_tests", _fake_run_all_tests, raising=True
        )
        monkeypatch.setattr(
            pr.PerformanceBenchmark, "run_benchmarks", _fake_run_benchmarks, raising=True
        )

        first = await run_production_readiness_suite(app)
        assert "production_readiness" in first
        assert "overall_assessment" in first
    finally:
        # Put any leaked MagicMock back so the next test in this worker sees
        # the same starting state we did (the leaked mock is the
        # ``return_value`` of the original ``__enter__`` so dropping it is a
        # no-op for the patcher that left it behind).
        for attr, mock in leaked.items():
            setattr(pr, attr, mock)


@pytest.mark.asyncio
async def test_remaining_readiness_branches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class _RepoErrorApp:
        def __init__(self, repos: list[str] | None = None) -> None:
            self._repos = repos or []
            self.config = _make_config(repos_path=str(tmp_path / "repos.txt"))

        def get_repos(self):
            return self._repos

    repo_root = tmp_path / "repos"
    repo_root.mkdir(parents=True, exist_ok=True)
    repo_a = repo_root / "a"
    repo_b = repo_root / "b"
    repo_a.mkdir(parents=True, exist_ok=True)

    repo_checker = ProductionReadinessChecker(_RepoErrorApp([str(repo_a), str(repo_b)]))
    assert repo_checker._check_repo_accessibility() is False
    assert repo_checker.results["repo_accessibility"]["status"] == "CAUTION"

    repo_c = repo_root / "c"
    repo_d = repo_root / "d"
    repo_c.mkdir(parents=True, exist_ok=True)
    repo_d.mkdir(parents=True, exist_ok=True)
    all_accessible = ProductionReadinessChecker(_RepoErrorApp([str(repo_c), str(repo_d)]))
    assert all_accessible._check_repo_accessibility() is True
    assert all_accessible.results["repo_accessibility"]["status"] == "PASS"

    empty_repo_checker = ProductionReadinessChecker(_RepoErrorApp([]))
    assert empty_repo_checker._check_repo_accessibility() is True
    assert (
        empty_repo_checker.results["repo_accessibility"]["message"] == "No repositories configured"
    )

    original_exists = pr.Path.exists

    def fake_exists(self):  # noqa: ANN001
        if self.name == "boom":
            raise OSError("bad")
        return original_exists(self)

    monkeypatch.setattr(pr.Path, "exists", fake_exists, raising=True)
    boom_repo = repo_root / "boom"
    boom_repo.mkdir(parents=True, exist_ok=True)
    assert (
        ProductionReadinessChecker(_RepoErrorApp([str(boom_repo)]))._check_repo_accessibility()
        is False
    )

    class _BrokenReposApp:
        config = _make_config(repos_path=str(tmp_path / "repos.txt"))

        def get_repos(self):
            raise RuntimeError("repos")

    assert ProductionReadinessChecker(_BrokenReposApp())._check_repo_accessibility() is False

    class _ConfigErrorApp:
        @property
        def config(self):  # noqa: D401
            raise RuntimeError("config")

        adapters: dict[str, object] = {}

    assert ProductionReadinessChecker(_ConfigErrorApp())._check_resource_limits() is False
    assert ProductionReadinessChecker(_ConfigErrorApp())._check_security_settings() is False

    workflow_error = _make_app(
        config=_make_config(repos_path=str(tmp_path / "repos.txt")),
        adapters={"adapter": _FakeAdapter()},
        repos=[str(repo_a)],
        execute_workflow_error=RuntimeError("workflow"),
    )
    assert await ProductionReadinessChecker(workflow_error)._check_workflow_execution() is False

    workflow_raise = _make_app(
        config=_make_config(repos_path=str(tmp_path / "repos.txt")),
        adapters={"adapter": _FakeAdapter()},
        repos=[str(repo_a)],
    )
    workflow_raise.execute_workflow = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("workflow")
    )
    assert await IntegrationTestSuite(workflow_raise)._test_basic_workflow_execution() is False

    bench_error = _make_app(
        config=_make_config(),
        adapters={"adapter": _FakeAdapter()},
        repos=[str(repo_a)],
        execute_workflow_error=RuntimeError("boom"),
    )
    workflow_benchmark = PerformanceBenchmark(bench_error)
    await workflow_benchmark._benchmark_workflow_execution()
    assert "workflow_execution" in workflow_benchmark.benchmarks

    class _BenchErrorApp:
        def __init__(self) -> None:
            self.adapters = {"adapter": _FakeAdapter()}

        def get_repos(self):
            raise RuntimeError("repos")

    assert await PerformanceBenchmark(_BenchErrorApp())._benchmark_workflow_execution() is None

    no_repo_benchmark = PerformanceBenchmark(
        _make_app(config=_make_config(), adapters={"adapter": _FakeAdapter()}, repos=[])
    )
    await no_repo_benchmark._benchmark_workflow_execution()
    assert no_repo_benchmark.benchmarks == {}

    concurrent_empty = PerformanceBenchmark(
        _make_app(config=_make_config(), adapters={"adapter": _FakeAdapter()}, repos=[])
    )
    await concurrent_empty._benchmark_concurrent_workflows()
    assert concurrent_empty.benchmarks == {}

    empty_runner = PerformanceBenchmark(_make_app(config=_make_config(), adapters={}, repos=[]))
    summary = await empty_runner.run_benchmarks()
    assert summary["summary"]["performance_score"] == 100

    class _RaisingRepoBenchApp:
        def __init__(self) -> None:
            self.adapters = {"adapter": _FakeAdapter()}
            self.config = _make_config()

        def get_repos(self):
            raise RuntimeError("repos")

    assert (
        await PerformanceBenchmark(_RaisingRepoBenchApp())._benchmark_concurrent_workflows() is None
    )
    assert await PerformanceBenchmark(_RaisingRepoBenchApp())._benchmark_repo_operations() is None


def test_overall_assessment_thresholds() -> None:
    readiness = {"summary": {"score_percentage": 95}}
    tests = {"summary": {"score_percentage": 95}}
    benchmarks = {"summary": {"performance_score": 95}}
    assert (
        _calculate_overall_assessment(readiness, tests, benchmarks)["status"] == "PRODUCTION READY"
    )

    readiness["summary"]["score_percentage"] = 80
    tests["summary"]["score_percentage"] = 80
    benchmarks["summary"]["performance_score"] = 80
    assert _calculate_overall_assessment(readiness, tests, benchmarks)["status"] == "NEARLY READY"

    readiness["summary"]["score_percentage"] = 60
    tests["summary"]["score_percentage"] = 60
    benchmarks["summary"]["performance_score"] = 60
    assert (
        _calculate_overall_assessment(readiness, tests, benchmarks)["status"] == "NEEDS IMPROVEMENT"
    )

    readiness["summary"]["score_percentage"] = 40
    tests["summary"]["score_percentage"] = 40
    benchmarks["summary"]["performance_score"] = 40
    assert _calculate_overall_assessment(readiness, tests, benchmarks)["status"] == "NOT READY"
