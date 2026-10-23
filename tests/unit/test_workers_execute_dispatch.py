"""``mahavishnu workers execute`` -- Phase 4 dispatch wiring.

The command used to print its DAG and stop with "Per-engine dispatch lands
in Phase 4", exiting 0 having dispatched nothing, so every caller waited on
side effects that could not occur (``bifrost verify-gate`` did exactly this).

These tests cover the wiring only. The substrate call is stubbed -- a live
dispatch spawns a terminal session and bills a model provider.
"""

from __future__ import annotations

from typing import Any

import pytest
import typer

from mahavishnu import _main_cli


class _Node:
    def __init__(self, node_id: str, engine_id: str, capability_id: str) -> None:
        self.node_id = node_id
        self.engine_id = engine_id
        self.capability_id = capability_id


class _Dag:
    def __init__(self, nodes: list[_Node]) -> None:
        self.nodes = nodes
        self.edges: list[Any] = []


DAG = _Dag(
    [
        _Node("n0", "prefect", "engine:durable-flow"),
        _Node("n1", "worker", _main_cli.TERMINAL_EXECUTION_CAPABILITY),
    ]
)


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record what reaches the adapter instead of running workers."""
    seen: list[dict[str, Any]] = []

    class _Adapter:
        def __init__(self, config: Any = None) -> None:
            self.worker_manager = None

        async def execute(self, task: dict[str, Any], repos: list[str]) -> dict[str, Any]:
            seen.append({"task": task, "repos": repos})
            return {"status": "completed", "worker_count": 1, "successful": 1}

    import mahavishnu.core.adapters.worker as worker_mod

    monkeypatch.setattr(worker_mod, "WorkerOrchestratorAdapter", _Adapter)
    return seen


async def _run(dag: _Dag, dispatched: list[dict[str, Any]], **kw: Any) -> None:
    await _main_cli._dispatch_dag_nodes(
        dag,
        config=object(),
        prompt="add a test",
        worker_type="terminal-qwen",
        count=1,
        timeout=60,
        repo=kw.get("repo"),
    )


async def test_dispatches_the_terminal_execution_node(dispatched: list[dict[str, Any]]) -> None:
    await _run(DAG, dispatched)

    assert len(dispatched) == 1, "only the terminal-execution node is actionable"
    assert dispatched[0]["task"]["worker_type"] == "terminal-qwen"
    assert dispatched[0]["task"]["prompt"] == "add a test"


async def test_durable_flow_node_is_not_dispatched(dispatched: list[dict[str, Any]]) -> None:
    """Prefect plans; it does not run prompts. One call, not two."""
    await _run(DAG, dispatched)

    assert len(dispatched) == 1


async def test_defaults_to_the_repo_root(dispatched: list[dict[str, Any]]) -> None:
    await _run(DAG, dispatched)

    assert dispatched[0]["repos"] == ["/Users/les/Projects/mahavishnu"]


async def test_explicit_repo_is_used(dispatched: list[dict[str, Any]]) -> None:
    await _run(DAG, dispatched, repo="/tmp/somewhere")

    assert dispatched[0]["repos"] == ["/tmp/somewhere"]


async def test_dag_without_a_terminal_node_fails(
    dispatched: list[dict[str, Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    empty = _Dag([_Node("n0", "prefect", "engine:durable-flow")])

    with pytest.raises(typer.Exit) as exit_info:
        await _run(empty, dispatched)

    assert exit_info.value.exit_code == 1
    assert dispatched == []
    assert "nothing was dispatched" in capsys.readouterr().err


async def test_partial_failure_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A worker that reports ``partial`` must not be reported as success."""

    class _Adapter:
        def __init__(self, config: Any = None) -> None:
            self.worker_manager = None

        async def execute(self, task: dict[str, Any], repos: list[str]) -> dict[str, Any]:
            return {"status": "partial", "worker_count": 1, "successful": 0, "failed": 1}

    import mahavishnu.core.adapters.worker as worker_mod

    monkeypatch.setattr(worker_mod, "WorkerOrchestratorAdapter", _Adapter)

    with pytest.raises(typer.Exit) as exit_info:
        await _run(DAG, [])

    assert exit_info.value.exit_code == 1
    assert "1/1 dispatch node(s) failed" in capsys.readouterr().err


async def test_adapter_exception_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class _Adapter:
        def __init__(self, config: Any = None) -> None:
            self.worker_manager = None

        async def execute(self, task: dict[str, Any], repos: list[str]) -> dict[str, Any]:
            raise RuntimeError("spawn refused")

    import mahavishnu.core.adapters.worker as worker_mod

    monkeypatch.setattr(worker_mod, "WorkerOrchestratorAdapter", _Adapter)

    with pytest.raises(typer.Exit) as exit_info:
        await _run(DAG, [])

    assert exit_info.value.exit_code == 1
    assert "spawn refused" in capsys.readouterr().err


async def test_worker_manager_is_closed(dispatched: list[dict[str, Any]]) -> None:
    """Sessions must be reaped; a dispatch that leaks panes wedges the pool."""
    closed: list[str] = []

    class _Manager:
        async def close_all(self) -> None:
            closed.append("closed")

    class _Adapter:
        def __init__(self, config: Any = None) -> None:
            self.worker_manager = _Manager()

        async def execute(self, task: dict[str, Any], repos: list[str]) -> dict[str, Any]:
            return {"status": "completed", "worker_count": 1, "successful": 1}

    import mahavishnu.core.adapters.worker as worker_mod

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(worker_mod, "WorkerOrchestratorAdapter", _Adapter)
    try:
        await _run(DAG, dispatched)
    finally:
        monkeypatch.undo()

    assert closed == ["closed"]


def test_capability_id_exists_in_the_worker_engine() -> None:
    """The node filter must name a capability some engine actually provides."""
    from mahavishnu.core.config import MahavishnuSettings
    from mahavishnu.engines import load_engine_registrations

    provided = {
        capability.id
        for registration in load_engine_registrations(MahavishnuSettings())
        for capability in registration.provides
    }

    assert _main_cli.TERMINAL_EXECUTION_CAPABILITY in provided
    assert not any(capability.startswith("worker:") for capability in provided), (
        "no worker:* capability exists; a dispatch requirement built by "
        "interpolation made plan() raise MHV-009 for every --type"
    )