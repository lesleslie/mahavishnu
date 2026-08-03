"""Tests for the durable-worker manager bootstrap wiring.

The whole-branch review of the durable-local-workers plan identified
that ``_durable_worker_manager`` was never set on ``server.app``
anywhere in production. ``mahavishnu.mcp.bootstrap._register_worker_contract_block``
fell through to ``_build_noop_worker_manager()`` and the 26-task
contract was unreachable in production.

These tests pin the wiring: when tmux is available,
``_register_worker_contract_block`` must construct a real
``DurableWorkerManager`` and stash it on ``server.app._durable_worker_manager``.
When tmux is missing, the noop fallback must be used (CI/dev machines
without Homebrew should still start the MCP server).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mahavishnu.mcp import bootstrap

pytestmark = pytest.mark.unit


class _StubServer:
    """Minimal FastMCPServer stand-in.

    ``bootstrap._register_worker_contract_block`` only reads ``server.app``
    (attribute access) and writes ``server.app._durable_worker_manager``.
    A real ``FastMCPServer`` requires FastMCP lifecycle machinery that
    is not relevant for the wiring under test.
    """

    def __init__(self) -> None:
        self.app = SimpleNamespace()
        self.server = MagicMock()
        # The register function will call ``server.server.tool()`` once per
        # worker-contract tool (7 tools). Capture the tool registrations so
        # the assertion below can confirm the manager was actually wired.
        self.tool_decorators: list = []

        def _tool_decorator():
            def decorator(fn):
                self.tool_decorators.append(fn)
                return fn

            return decorator

        self.server.tool = _tool_decorator


def test_register_worker_contract_block_wires_real_manager_when_tmux_available(
    monkeypatch,
) -> None:
    """When tmux is on PATH, the block constructs a real DurableWorkerManager
    and stashes it on ``server.app._durable_worker_manager``.

    Regression test for FIX-FIRST #1 of the whole-branch review: without
    this wiring, the 26-task durable-local-workers contract was unreachable
    in production and all 7 worker-contract tools returned
    ``state="manager_unconfigured"``.
    """
    fake_manager = MagicMock(name="DurableWorkerManager")
    monkeypatch.setattr(bootstrap, "_try_build_durable_worker_manager", lambda: fake_manager)
    monkeypatch.setattr(bootstrap.shutil, "which", lambda binary: "/usr/bin/tmux")

    server = _StubServer()

    # Patch the worker_contract_tools.register so the test does not pull
    # in the full FastMCP machinery; we only care about the wiring.
    def _fake_register(app, manager):
        # Capture which manager was handed to the tool surface.
        server.tool_decorators.append(("registered_manager", manager))

    monkeypatch.setattr(
        "mahavishnu.mcp.tools.worker_contract_tools.register_worker_contract_tools",
        _fake_register,
    )

    bootstrap._register_worker_contract_block(server)

    # The real manager must have been stashed on the app.
    assert server.app._durable_worker_manager is fake_manager
    # The real manager must have been passed to the tool surface.
    # The decorator function appends a tuple marker; pull it back out.
    registered = [
        entry[1]
        for entry in server.tool_decorators
        if isinstance(entry, tuple) and entry[0] == "registered_manager"
    ]
    assert registered and registered[0] is fake_manager


def test_register_worker_contract_block_falls_back_to_noop_when_tmux_missing(
    monkeypatch,
    caplog,
) -> None:
    """When tmux is not on PATH, the block logs a warning and uses noop.

    CI containers and dev machines without Homebrew must still be able to
    start the MCP server — the noop fallback is the documented safety net.
    """
    monkeypatch.setattr(
        bootstrap, "_try_build_durable_worker_manager", lambda: None
    )
    monkeypatch.setattr(bootstrap.shutil, "which", lambda binary: None)

    server = _StubServer()

    def _fake_register(app, manager):
        # The noop manager must reach the tool surface.
        assert hasattr(manager, "spawn"), "manager must be the noop shim"
        server.tool_decorators.append(("registered_manager", manager))

    monkeypatch.setattr(
        "mahavishnu.mcp.tools.worker_contract_tools.register_worker_contract_tools",
        _fake_register,
    )

    with caplog.at_level("WARNING"):
        bootstrap._register_worker_contract_block(server)

    # No real manager was wired.
    assert not hasattr(server.app, "_durable_worker_manager")
    # The noop shim was passed to the tool surface.
    assert any(
        isinstance(entry, tuple) and entry[0] == "registered_manager"
        for entry in server.tool_decorators
    )
    assert "manager_unconfigured" in caplog.text


def test_try_build_durable_worker_manager_returns_none_when_tmux_missing(
    monkeypatch,
) -> None:
    """``_try_build_durable_worker_manager`` returns ``None`` when tmux
    is not on PATH.

    Pinned so a future change that always instantiates the manager
    surfaces an immediate test failure on machines without tmux.
    """
    monkeypatch.setattr(bootstrap.shutil, "which", lambda binary: None)

    result = bootstrap._try_build_durable_worker_manager()

    assert result is None


def test_try_build_durable_worker_manager_uses_canonical_publisher_bridge(
    monkeypatch,
) -> None:
    """``_try_build_durable_worker_manager`` constructs a manager whose
    publisher adapts ``EventPublisher.emit(payload, topic)`` to the
    canonical ``EventEnvelope`` shape (FIX-FIRST #2 verification).

    The bridge in :mod:`mahavishnu.terminal.manager` already handles the
    argument-order drift between
    ``mahavishnu.workers.contract.manager.EventPublisher`` and
    ``CanonicalEnvelopePublisher``; the bootstrap path reuses it so the
    mismatch is contained to one place.
    """
    fake_manager = MagicMock(name="DurableWorkerManager")
    captured: dict[str, object] = {}

    def _fake_constructor(*args, **kwargs):
        captured.update(kwargs)
        return fake_manager

    monkeypatch.setattr(bootstrap.shutil, "which", lambda binary: "/usr/bin/tmux")
    monkeypatch.setattr(
        "mahavishnu.workers.contract.manager.DurableWorkerManager", _fake_constructor
    )

    # Stub the bridge so we don't pull in the real EventEnvelope import
    # path; the contract test is that the bridge is *invoked* with the
    # canonical sink, not that the sink itself is wired.
    class _FakeBridge:
        def __init__(self, sink):
            captured["bridge_sink"] = sink

    monkeypatch.setattr(
        "mahavishnu.terminal.manager._ManagerEventPublisher", _FakeBridge
    )

    result = bootstrap._try_build_durable_worker_manager()

    assert result is fake_manager
    # The bridge was constructed with the canonical ``_enqueue_to_eventbridge``
    # sink (no-op until Task 13 wires the real producer, per
    # ``terminal/manager.py``).
    assert "bridge_sink" in captured
    assert callable(captured["bridge_sink"])