"""Unit tests for per-engine ``emit_node`` dispatch and level-by-level DAG dispatch.

Covers the five supported engines (Prefect, LlamaIndex, Agno, Hatchet,
pydantic_ai) plus the unsupported-engine fallback, the pydantic_ai
missing-dependency-group branch, and the level-by-level wave algorithm
in ``mahavishnu.core.conductor._dispatch_dag_waves``.

Every test mocks the underlying ``OrchestratorAdapter.execute()`` so we
don't need a live Prefect/LlamaIndex/Agno/Hatchet/pydantic_ai backend —
the only real I/O is the MCP-backed envelope persistence, which a
``_FakeMCPClient`` stub absorbs in memory.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.core.adapters.base import OrchestratorAdapter
from mahavishnu.core.capabilities import (
    CapabilityEnvelope,
    DAGNode,
    EnvelopeId,
    TraceId,
    TypeSchema,
)
from mahavishnu.core.conductor import (
    _dispatch_dag_waves,
    _EMIT_NODE_DISPATCH,
    emit_node,
)
from mahavishnu.core.conductor_types import NodeHandle, NodeSpec
from mahavishnu.engines import emit_node_dispatch

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeMCPClient:
    """In-memory implementation of the slice of MCPClient that envelopes need.

    Records every ``put`` so tests can assert envelope persistence without a
    live MCP server. Returns ``None`` from ``call_tool('get', ...)`` so a
    missing key behaves like an empty store.
    """

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    async def put(self, key: str, value: Any, ttl: int | None = None) -> Any:
        if isinstance(value, str):
            self.store[key] = value.encode()
        else:
            self.store[key] = bytes(value)
        return None

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "get":
            return self.store.get(arguments["key"])
        if name == "list_keys":
            prefix = arguments.get("prefix", "")
            return [k for k in self.store if k.startswith(prefix)]
        return None


@pytest.fixture
def fake_mcp() -> _FakeMCPClient:
    return _FakeMCPClient()


def _make_adapter_mock() -> MagicMock:
    """Return a fresh AsyncMock-spec'd OrchestratorAdapter per test."""
    adapter = MagicMock(spec=OrchestratorAdapter)
    adapter.execute = AsyncMock(
        return_value={
            "status": "completed",
            "results": [{"repo": "/tmp/r", "status": "completed", "output": "ok"}],
            "flow_run_id": "test-123",
            "run_id": "hatchet-123",
        }
    )
    return adapter


@pytest.fixture
def adapters() -> dict[str, MagicMock]:
    """Fresh per-test registry of mocked adapter instances.

    The plan calls out (per ``feedback-workflow-parallel-same-repo-no-isolation``
    and the test-coverage-review rule on shared mutable state) that the
    registry must not be module-level singleton — each test gets its own
    mocks via ``register(adapters)``.
    """
    return {
        "prefect": _make_adapter_mock(),
        "llamaindex": _make_adapter_mock(),
        "agno": _make_adapter_mock(),
        "hatchet": _make_adapter_mock(),
        "pydantic_ai": _make_adapter_mock(),
    }


def _register(adapters: dict[str, MagicMock]) -> None:
    """Install mocks into the dispatch table for one test.

    The dispatch registry is module-level (intentional — the conductor's
    ``emit_node`` is one global lookup), but the *adapter instances* are
    per-test, so two parallel test classes can each refresh the registry
    without rewriting dispatcher code.
    """
    emit_node_dispatch.register(adapters)


def _make_node(engine_id: str) -> DAGNode:
    return DAGNode(
        node_id=f"n-{engine_id}",
        engine_id=engine_id,  # type: ignore[arg-type]
        capability_id="engine:durable-flow",  # type: ignore[arg-type]
        inputs=TypeSchema(),
        outputs=TypeSchema(),
    )


# ---------------------------------------------------------------------------
# Per-engine dispatcher tests (Phase 4 Steps 4.4 - 4.6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("engine_id", "dispatcher_name"),
    [
        ("prefect", "emit_prefect_node"),
        ("llamaindex", "emit_llamaindex_node"),
        ("agno", "emit_agno_node"),
        ("hatchet", "emit_hatchet_node"),
        ("pydantic_ai", "emit_pydanticai_node"),
    ],
)
async def test_emit_node_returns_handle_for_each_engine(
    engine_id: str,
    dispatcher_name: str,
    adapters: dict[str, MagicMock],
    fake_mcp: _FakeMCPClient,
) -> None:
    """Every supported engine dispatcher persists an envelope and returns a NodeHandle."""
    _register(adapters)
    node = _make_node(engine_id)
    eid = await emit_node(
        node=node,
        trace_id=TraceId("0" * 32),
        mcp=fake_mcp,  # type: ignore[arg-type]
        prompt="hello",
    )
    # Envelope persisted
    assert isinstance(eid, str)
    matching_keys = [k for k in fake_mcp.store if k.startswith(f"envelopes/{'0' * 32}/")]
    assert len(matching_keys) == 1
    persisted = json.loads(fake_mcp.store[matching_keys[0]].decode())
    assert persisted["engine_id"] == engine_id
    assert persisted["status" if "status" in persisted else "io_out"]  # envelope persisted

    # Mock was awaited once with the engine-specific task shape
    adapters[engine_id].execute.assert_awaited_once()


async def test_emit_prefect_node_surfaces_flow_run_id(
    adapters: dict[str, MagicMock],
    fake_mcp: _FakeMCPClient,
) -> None:
    """Prefect dispatcher reads ``flow_run_id`` from the response into NodeHandle."""
    adapters["prefect"].execute.return_value = {
        "status": "completed",
        "results": [{"status": "completed"}],
        "flow_run_id": "flow-abc",
    }
    _register(adapters)
    spec = NodeSpec(
        node_id="n-prefect",
        engine_id="prefect",  # type: ignore[arg-type]
        capability_id="engine:durable-flow",  # type: ignore[arg-type]
        trace_id=TraceId("0" * 32),
        prompt="hi",
    )
    handle = await emit_node_dispatch.emit_prefect_node(spec, fake_mcp)  # type: ignore[arg-type]
    assert handle.engine_id == "prefect"
    assert handle.status == "completed"
    assert handle.flow_run_id == "flow-abc"
    assert handle.error is None


async def test_emit_hatchet_node_surfaces_run_id(
    adapters: dict[str, MagicMock],
    fake_mcp: _FakeMCPClient,
) -> None:
    """Hatchet dispatcher reads ``run_id`` from the response into NodeHandle."""
    adapters["hatchet"].execute.return_value = {
        "status": "completed",
        "results": [{"status": "completed"}],
        "run_id": "run-xyz",
    }
    _register(adapters)
    spec = NodeSpec(
        node_id="n-hatchet",
        engine_id="hatchet",  # type: ignore[arg-type]
        capability_id="engine:durable-flow",  # type: ignore[arg-type]
        trace_id=TraceId("0" * 32),
        prompt="hi",
    )
    handle = await emit_node_dispatch.emit_hatchet_node(spec, fake_mcp)  # type: ignore[arg-type]
    assert handle.engine_id == "hatchet"
    assert handle.flow_run_id == "run-xyz"


async def test_emit_pydantic_ai_node_handles_missing_dep_group(
    adapters: dict[str, MagicMock],
    fake_mcp: _FakeMCPClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the ``ai`` PEP 735 group is not installed the dispatcher returns a ``failed`` handle and persists a ``status='failed'`` envelope."""
    # Force the lazy import to fail by hiding the module.
    monkeypatch.setitem(__import__("sys").modules, "mahavishnu.adapters.ai.pydantic_ai_adapter", None)  # type: ignore[arg-type]
    adapters.pop("pydantic_ai", None)
    _register(adapters)
    spec = NodeSpec(
        node_id="n-pai",
        engine_id="pydantic_ai",  # type: ignore[arg-type]
        capability_id="engine:durable-flow",  # type: ignore[arg-type]
        trace_id=TraceId("0" * 32),
        prompt="hi",
    )
    handle = await emit_node_dispatch.emit_pydanticai_node(spec, fake_mcp)  # type: ignore[arg-type]
    assert handle.status == "failed"
    assert handle.error is not None
    assert "uv sync --group ai" in handle.error
    # Failure envelope was still persisted (so observability is preserved).
    keys = [k for k in fake_mcp.store if k.startswith(f"envelopes/{'0' * 32}/")]
    assert len(keys) == 1


async def test_dispatch_persists_envelope_io_out(
    adapters: dict[str, MagicMock],
    fake_mcp: _FakeMCPClient,
) -> None:
    """The persisted envelope carries the stringified per-repo results under ``io_out.result_<i>``."""
    adapters["prefect"].execute.return_value = {
        "status": "completed",
        "results": [{"status": "completed", "output": "out-1"}],
        "flow_run_id": "fr-1",
    }
    _register(adapters)
    eid = await emit_node(
        node=_make_node("prefect"),
        trace_id=TraceId("0" * 32),
        mcp=fake_mcp,  # type: ignore[arg-type]
        prompt="x",
    )
    persisted = json.loads(fake_mcp.store[f"envelopes/{'0' * 32}/{eid}"].decode())
    assert persisted["engine_id"] == "prefect"
    assert persisted["io_out"]["result_0"].startswith("status=")


async def test_emit_node_unsupported_engine_raises(
    adapters: dict[str, MagicMock],
    fake_mcp: _FakeMCPClient,
) -> None:
    """An unknown engine_id raises ``NotImplementedError`` with a grep-friendly message."""
    _register(adapters)
    with pytest.raises(NotImplementedError, match="per-engine emit_node dispatch not registered"):
        await emit_node(
            node=_make_node("unknown-engine"),
            trace_id=TraceId("0" * 32),
            mcp=fake_mcp,  # type: ignore[arg-type]
            prompt="x",
        )


async def test_emit_node_persists_failed_envelope_on_adapter_exception(
    adapters: dict[str, MagicMock],
    fake_mcp: _FakeMCPClient,
) -> None:
    """An adapter ``execute()`` exception still persists a ``status='failed'`` envelope."""
    adapters["prefect"].execute.side_effect = RuntimeError("kaboom")
    _register(adapters)
    eid = await emit_node(
        node=_make_node("prefect"),
        trace_id=TraceId("0" * 32),
        mcp=fake_mcp,  # type: ignore[arg-type]
        prompt="x",
    )
    persisted = json.loads(fake_mcp.store[f"envelopes/{'0' * 32}/{eid}"].decode())
    assert persisted["io_out"]["error"] == "kaboom"


# ---------------------------------------------------------------------------
# Level-by-level DAG dispatch (Phase 5 Step 5.6)
# ---------------------------------------------------------------------------


async def test_dispatch_dag_waves_level_by_level(
    adapters: dict[str, MagicMock],
    fake_mcp: _FakeMCPClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DAG with one root A and two children B, C dispatches as two waves via asyncio.gather."""
    _register(adapters)
    a = DAGNode(
        node_id="A",
        engine_id="prefect",  # type: ignore[arg-type]
        capability_id="engine:durable-flow",  # type: ignore[arg-type]
        inputs=TypeSchema(),
        outputs=TypeSchema(),
    )
    b = DAGNode(
        node_id="B",
        engine_id="hatchet",  # type: ignore[arg-type]
        capability_id="engine:durable-flow",  # type: ignore[arg-type]
        inputs=TypeSchema(),
        outputs=TypeSchema(),
    )
    c = DAGNode(
        node_id="C",
        engine_id="agno",  # type: ignore[arg-type]
        capability_id="engine:durable-flow",  # type: ignore[arg-type]
        inputs=TypeSchema(),
        outputs=TypeSchema(),
    )
    edges = (
        # B and C both depend on A → level-by-level: wave 1 = {A}, wave 2 = {B,C}
        # The DAGEdge type's from_node/to_node are positional here for brevity.
        # We'll build them via the Pydantic constructor.
        __import__("mahavishnu.core.capabilities", fromlist=["DAGEdge"]).DAGEdge(
            from_node="A", to_node="B", via_field="x"
        ),
        __import__("mahavishnu.core.capabilities", fromlist=["DAGEdge"]).DAGEdge(
            from_node="A", to_node="C", via_field="y"
        ),
    )
    dag = __import__("mahavishnu.core.capabilities", fromlist=["ExecutionDAG"]).ExecutionDAG(
        nodes=(a, b, c),
        edges=edges,
        trace_id=TraceId("0" * 32),
    )

    # Capture gather call sizes to assert the second wave is one gather.
    gather_sizes: list[int] = []
    real_gather = asyncio.gather

    def _gathering(*coros: Any, **kwargs: Any) -> Any:
        gather_sizes.append(len(coros))
        return real_gather(*coros, **kwargs)

    monkeypatch.setattr("mahavishnu.core.conductor.asyncio.gather", _gathering)
    envelope_ids = await _dispatch_dag_waves(
        dag,
        trace_id=TraceId("0" * 32),
        mcp=fake_mcp,  # type: ignore[arg-type]
        prompt_for_root="root-prompt",
    )
    assert set(envelope_ids.keys()) == {"A", "B", "C"}
    # Two waves: {A} then {B, C}
    assert gather_sizes == [1, 2]
    # Three envelopes persisted
    keys = [k for k in fake_mcp.store if k.startswith(f"envelopes/{'0' * 32}/")]
    assert len(keys) == 3
