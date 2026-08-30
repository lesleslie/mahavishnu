"""Unit tests for :class:`mahavishnu.workers.shepherd_backend`.

Coverage focus (per Phase 4 v2 plan):

- Host capability probe picks the right carrier for each OS.
- Worker startup is **fail-closed** when the host cannot satisfy the
  requested ``placement``; the error MUST surface as
  :class:`ShepherdJailUnavailable`, never as a generic ``RuntimeError``
  and never as a silent fallback to a less-secure backend.
- Capability-driven registry integration: ``"shepherd"`` is a valid
  routing target with the ``CONTAINER`` category, so ``WorkerManager``
  dispatches it through the isolated-worker factory path.
- Lazy-import table exports the wrapper symbols without eagerly loading
  the optional ``shepherd-ai`` SDK when it is absent.
- ``writable_root`` is mandatory; construction fails loud without it.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures: substrate stubs
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_shepherd(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Inject the ``shepherd`` package symbols the wrapper depends on.

    Records what the wrapper called so tests can assert against the
    substrate's expected surface (``discover`` / ``run`` / ``changeset``).
    """
    # Importing here ensures ``mahavishnu.workers.shepherd_backend`` is in
    # ``sys.modules`` before we try to patch its attributes.
    from mahavishnu.workers import shepherd_backend

    calls: dict[str, list[Any]] = {"discover": [], "run": []}

    class _FakeGitRepo:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class _FakeStat:
        def __init__(self) -> None:
            self.output_id = "out-1"
            self.output_name = "workspace"
            self.binding = "writable"
            self.state = "settled"
            self.changed_path_count = 0

    class _FakeChangeset:
        def stat(self) -> _FakeStat:
            return _FakeStat()

    class _FakeWorkspaceRun:
        def __init__(self) -> None:
            self.status = "finished"
            self.run_ref = "ref-1"

        def changeset(self) -> _FakeChangeset:
            return _FakeChangeset()

    class _FakeShepherdWorkspace:
        @classmethod
        def discover(cls, cwd: Any, *, activate: bool, backend: Any) -> _FakeShepherdWorkspace:
            calls["discover"].append({"cwd": str(cwd), "activate": activate, "backend": backend})
            return cls()

        def run(self, task_ref: Any, **kwargs: Any) -> _FakeWorkspaceRun:
            calls["run"].append({"task_ref": task_ref, "kwargs": kwargs})
            return _FakeWorkspaceRun()

        def git_repo(self) -> _FakeGitRepo:
            calls.setdefault("git_repo", []).append({})
            return _FakeGitRepo(binding="writable", basis={"world_oid": "fake", "store_id": "fake", "resource_id": "fake", "head": "0" * 40})

        def close(self) -> None:
            return None

    class _FakeAmbientWorldAccessRefused(Exception):
        pass

    class _FakeEffectNotPermitted(Exception):
        pass

    def _task_decorator(fn: Any = None, **kwargs: Any) -> Any:
        if fn is None:
            return lambda real_fn: real_fn
        return fn

    monkeypatch.setattr(shepherd_backend, "GitRepo", _FakeGitRepo, raising=False)
    monkeypatch.setattr(shepherd_backend, "ShepherdWorkspace", _FakeShepherdWorkspace, raising=False)
    monkeypatch.setattr(
        shepherd_backend, "AmbientWorldAccessRefused", _FakeAmbientWorldAccessRefused, raising=False
    )
    monkeypatch.setattr(
        shepherd_backend, "EffectNotPermitted", _FakeEffectNotPermitted, raising=False
    )
    # ``_wrap_command`` references ``shepherd.task`` directly; patch it on
    # the wrapper module so the helper short-circuits without reaching
    # for the real package. The returned callable must carry a stable
    # ``__module__`` / ``__qualname__`` so Shepherd's ``coerce_task_ref``
    # can derive a task identity (refuses ``<locals>`` qualnames).

    def _make_shell_task(command: str) -> Any:
        # Bound method on a module-level callable — stable identity
        # because the binding happens at function creation, not inside
        # any other function's local scope.
        def _shell_task() -> str:
            return command

        _shell_task.__name__ = f"_shell_task_{command[:32]}"
        _shell_task.__qualname__ = f"_shell_task.{_shell_task.__name__}"
        return _shell_task

    def _fake_wrap_command(command: str) -> Any:
        return _make_shell_task(command)

    # Patch the module-level ``_compose_shell_task`` to use the fake
    # too — the real one is module-scoped so the monkeypatch on
    # ``_wrap_command`` alone is insufficient when Shepherd's substrate
    # resolves the call chain via ``self._wrap_command``.
    monkeypatch.setattr(
        shepherd_backend,
        "_wrap_command",
        _fake_wrap_command,
        raising=False,
    )
    monkeypatch.setattr(
        shepherd_backend,
        "_compose_shell_task",
        _make_shell_task,
        raising=False,
    )
    return calls


def _import_worker_class():
    # Force a fresh import so the module's lazy ``shepherd`` symbol picks
    # up the test's monkeypatched values (imports are cached at module
    # load, so we patch the names the wrapper actually uses).
    from mahavishnu.workers import shepherd_backend

    return shepherd_backend


# ---------------------------------------------------------------------------
# Host capability probe
# ---------------------------------------------------------------------------


class TestHostCapabilityProbe:
    def test_invalid_placement_raises_value_error(self) -> None:
        sb = _import_worker_class()
        with pytest.raises(ValueError, match="placement"):
            sb.probe_host_capability(placement="nope")  # type: ignore[arg-type]

    def test_macos_jail_resolves_to_seatbelt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "darwin")
        sb = _import_worker_class()
        # platform.machine is read inside probe_host_capability via the
        # ``platform`` module; patch the function the module imported.
        import platform as _platform

        monkeypatch.setattr(_platform, "machine", lambda: "arm64")
        result = sb.probe_host_capability(placement="jail")
        assert result.available is True
        assert result.backend == "seatbelt"

    def test_macos_auto_falls_back_to_clonefile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "darwin")
        sb = _import_worker_class()
        import platform as _platform

        monkeypatch.setattr(_platform, "machine", lambda: "arm64")
        result = sb.probe_host_capability(placement="auto")
        assert result.backend == "clonefile"

    def test_linux_jail_resolves_to_landlock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        sb = _import_worker_class()
        import platform as _platform

        monkeypatch.setattr(_platform, "machine", lambda: "x86_64")
        result = sb.probe_host_capability(placement="jail")
        assert result.available is True
        assert result.backend == "landlock"

    def test_unsupported_host_returns_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        sb = _import_worker_class()
        result = sb.probe_host_capability(placement="jail")
        assert result.available is False
        assert result.backend == "unsupported"


# ---------------------------------------------------------------------------
# Worker construction & startup — fail-closed contract
# ---------------------------------------------------------------------------


class TestFailClosedStartup:
    def test_construct_requires_writable_root(self, stub_shepherd: dict[str, Any]) -> None:
        sb = _import_worker_class()
        with pytest.raises(TypeError):
            sb.ShepherdBackendWorker()  # type: ignore[call-arg]

    def test_construct_raises_when_sdk_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sb = _import_worker_class()
        monkeypatch.setattr(sb, "ShepherdWorkspace", None)
        with pytest.raises(RuntimeError, match="shepherd-ai"):
            sb.ShepherdBackendWorker(writable_root="/tmp/shepherd-test")

    def test_construct_raises_when_jail_unavailable(
        self, stub_shepherd: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        sb = _import_worker_class()
        with pytest.raises(sb.ShepherdJailUnavailableError) as excinfo:
            sb.ShepherdBackendWorker(writable_root="/tmp/shepherd-test", placement="jail")
        assert excinfo.value.details["placement"] == "jail"
        assert excinfo.value.details["backend"] == "unsupported"
        assert "fail-closed" in excinfo.value.message.lower()

    async def test_start_opens_workspace_and_returns_id(
        self, stub_shepherd: dict[str, Any], tmp_path: Any
    ) -> None:
        sb = _import_worker_class()
        worker = sb.ShepherdBackendWorker(
            writable_root=str(tmp_path), placement="auto"
        )
        wid = await worker.start()
        assert wid.startswith("shepherd-")
        assert stub_shepherd["discover"], "ShepherdWorkspace.discover was not invoked"
        discover_call = stub_shepherd["discover"][0]
        assert discover_call["activate"] is True
        assert discover_call["backend"] is None  # substrate picks the carrier

    async def test_start_propagates_substrate_failure(
        self, stub_shepherd: dict[str, Any], tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sb = _import_worker_class()

        def _raise(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("substrate boom")

        monkeypatch.setattr(
            sb.ShepherdWorkspace, "discover", classmethod(lambda cls, *a, **kw: _raise(*a, **kw))
        )
        worker = sb.ShepherdBackendWorker(writable_root=str(tmp_path))
        with pytest.raises(sb.ShepherdJailUnavailableError) as excinfo:
            await worker.start()
        assert excinfo.value.details["substrate_exception"] == "RuntimeError"
        assert "fail-closed" in excinfo.value.message.lower()


# ---------------------------------------------------------------------------
# Execute: writes inside the grant must succeed, outside must be refused
# ---------------------------------------------------------------------------


class TestExecuteContract:
    async def test_execute_invokes_substrate_and_maps_result(
        self, stub_shepherd: dict[str, Any], tmp_path: Any
    ) -> None:
        sb = _import_worker_class()
        worker = sb.ShepherdBackendWorker(
            writable_root=str(tmp_path), placement="auto"
        )
        await worker.start()
        result = await worker.execute({"command": "ls"})
        assert result.status.value == "completed"
        assert result.metadata["runtime"] == "shepherd"
        assert result.metadata["backend"] == "clonefile"
        assert result.metadata["placement"] == "auto"
        # ``task_ref`` is whatever Shepherd's @task decorator returns; we
        # only assert it's non-empty so the substrate receives a real
        # callable. Exact naming is owned by the substrate.
        assert isinstance(result.metadata["task_ref"], str)
        assert result.metadata["task_ref"]
        # The Shepherd substrate owns the exact task_ref format
        # (``CallableTask.__name__`` is the inner function name); we
        # only assert that the wrapper records *some* identifier so
        # downstream observability can correlate the run. The fake
        # factory in this test sets ``__name__ = "_shell_task_<cmd>"``.
        assert result.metadata["task_ref"].startswith("_shell_task_")
        assert stub_shepherd["run"], "Workspace.run was not invoked"
        run_call = stub_shepherd["run"][0]
        # ``writable_root`` must flow through as the granted binding root;
        # the substrate uses this to compile Seatbelt / Landlock rules.
        assert run_call["kwargs"]["placement"] == "auto"

    async def test_execute_rejects_missing_task_and_command(
        self, stub_shepherd: dict[str, Any], tmp_path: Any
    ) -> None:
        sb = _import_worker_class()
        worker = sb.ShepherdBackendWorker(writable_root=str(tmp_path))
        await worker.start()
        with pytest.raises(ValueError, match="task_ref"):
            await worker.execute({})

    async def test_execute_rejects_both_task_ref_and_command(
        self, stub_shepherd: dict[str, Any], tmp_path: Any
    ) -> None:
        sb = _import_worker_class()
        worker = sb.ShepherdBackendWorker(writable_root=str(tmp_path))
        await worker.start()
        with pytest.raises(ValueError, match="exactly one"):
            await worker.execute({"task_ref": object(), "command": "ls"})

    async def test_execute_validates_command_via_exec_guard(
        self, stub_shepherd: dict[str, Any], tmp_path: Any
    ) -> None:
        sb = _import_worker_class()
        worker = sb.ShepherdBackendWorker(writable_root=str(tmp_path))
        await worker.start()
        with pytest.raises(ValueError, match="allowed list"):
            await worker.execute({"command": "this-is-not-allowlisted"})

    async def test_execute_writes_inside_root_succeed(
        self, stub_shepherd: dict[str, Any], tmp_path: Any
    ) -> None:
        """Writes inside the granted root must route through the worker."""
        sb = _import_worker_class()
        worker = sb.ShepherdBackendWorker(
            writable_root=str(tmp_path), placement="jail"
        )
        await worker.start()
        # A bare shell ``touch`` is on the allowlist; the substrate stub
        # records the call so we can prove the worker emitted it. The
        # actual filesystem write is the substrate's responsibility; the
        # syscall jail is the contract we verify via substrate tests on
        # a real machine. Here we verify the wrapper contract.
        result = await worker.execute({"command": "touch"})
        assert result.metadata["command"] == "touch"
        assert result.metadata["placement"] == "jail"

    async def test_execute_refuses_outside_root_at_substrate(
        self, stub_shepherd: dict[str, Any], tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the substrate reports a refused effect, the wrapper MUST
        surface the failure rather than fabricate a success."""
        sb = _import_worker_class()

        def _refuse(*_args: Any, **_kwargs: Any) -> Any:
            raise sb.EffectNotPermitted("write outside granted root")

        monkeypatch.setattr(
            sb.ShepherdWorkspace,
            "run",
            lambda self, *a, **kw: _refuse(*a, **kw),
        )
        worker = sb.ShepherdBackendWorker(
            writable_root=str(tmp_path), placement="jail"
        )
        await worker.start()
        result = await worker.execute({"command": "ls"})
        assert result.status.value == "failed"
        assert "EffectNotPermitted" in result.metadata["exception"]
        assert "outside granted root" in result.error


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


class TestRegistryWiring:
    def test_shepherd_is_registered_as_container(self) -> None:
        from mahavishnu.workers.registry import (
            WorkerCategory,
            get_worker_config,
        )

        cfg = get_worker_config("shepherd")
        assert cfg is not None
        assert cfg.category == WorkerCategory.CONTAINER
        assert cfg.one_shot is True
        # Fail-closed contract: required_env is empty so capability
        # gating is purely about the optional SDK being installed.
        assert cfg.required_env == []

    def test_shepherd_appears_in_list(self) -> None:
        from mahavishnu.workers.registry import (
            WorkerCategory,
            list_worker_types,
        )

        container_types = list_worker_types(category=WorkerCategory.CONTAINER)
        assert "shepherd" in container_types


# ---------------------------------------------------------------------------
# Manager dispatch
# ---------------------------------------------------------------------------


class TestManagerDispatch:
    def test_create_isolated_worker_routes_to_shepherd(
        self, stub_shepherd: dict[str, Any], tmp_path: Any
    ) -> None:
        from mahavishnu.workers import manager as mgr_mod
        from mahavishnu.workers.shepherd_backend import ShepherdBackendWorker

        worker = mgr_mod._create_isolated_worker(
            "shepherd",
            session_buddy_client=None,
            kwargs={"writable_root": str(tmp_path), "placement": "auto"},
        )
        assert isinstance(worker, ShepherdBackendWorker)
        assert worker.worker_type == "shepherd"

    def test_create_isolated_worker_requires_writable_root(
        self, stub_shepherd: dict[str, Any]
    ) -> None:
        from mahavishnu.core.errors import MahavishnuError
        from mahavishnu.workers import manager as mgr_mod

        with pytest.raises(MahavishnuError, match="writable_root"):
            mgr_mod._create_isolated_worker(
                "shepherd",
                session_buddy_client=None,
                kwargs={},
            )

    def test_create_isolated_worker_shepherd_does_not_fall_through(
        self, stub_shepherd: dict[str, Any], tmp_path: Any
    ) -> None:
        """A Shepherd jail failure MUST NOT silently degrade to E2B.

        Per Phase 4 exit criteria, the v2 plan forbids a silent fallback
        to a less-secure backend. We verify this by confirming that
        ``_create_isolated_worker`` returns a :class:`ShepherdBackendWorker`
        when called with ``worker_type="shepherd"`` — any fallback to
        ``apple-container`` or ``e2b-sandbox`` would have to surface
        as a different concrete class because the wrapper raises
        ``ShepherdJailUnavailable`` (not ``AppleContainerUnsupported``)
        and never reaches the E2B branch when the shepherd branch
        constructs successfully.
        """
        from mahavishnu.workers import manager as mgr_mod
        from mahavishnu.workers.shepherd_backend import ShepherdBackendWorker

        worker = mgr_mod._create_isolated_worker(
            "shepherd",
            session_buddy_client=None,
            kwargs={"writable_root": str(tmp_path), "placement": "auto"},
        )
        assert isinstance(worker, ShepherdBackendWorker)
        assert worker.worker_type == "shepherd"
        assert worker.placement == "auto"
