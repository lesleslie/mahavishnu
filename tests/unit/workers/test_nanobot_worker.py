"""Unit tests for NanobotWorker — covers all 6 Phase B spec requirements."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import mahavishnu.core.app as appmod
from mahavishnu.workers.base import WorkerResult
from mahavishnu.workers.nanobot_worker import NanobotWorker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_provider() -> MagicMock:
    """Create a mock provider with a `complete` attribute."""
    provider = MagicMock()
    provider.complete = AsyncMock(return_value="done")
    return provider


def _install_nanobot_runner_mock(response: str = "runner output") -> dict:
    """Inject a fake nanobot.agent.runner into sys.modules."""
    mock_runner_instance = MagicMock()
    mock_runner_instance.run = AsyncMock(return_value=response)
    runner_ns = SimpleNamespace(AgentRunner=MagicMock(return_value=mock_runner_instance))
    agent_ns = SimpleNamespace(runner=runner_ns, loop=SimpleNamespace(AgentLoop=MagicMock()))
    nanobot_ns = SimpleNamespace(agent=agent_ns)
    return {
        "nanobot": nanobot_ns,
        "nanobot.agent": agent_ns,
        "nanobot.agent.runner": runner_ns,
    }


# ---------------------------------------------------------------------------
# Spec #1 — construction with no provider
# ---------------------------------------------------------------------------

def test_construction_with_no_provider() -> None:
    """NanobotWorker(worker_type='in-process-nanobot') constructs without error;
    _nanobot_provider is None."""
    worker = NanobotWorker(worker_type="in-process-nanobot")
    assert worker._nanobot_provider is None


# ---------------------------------------------------------------------------
# Spec #2 — initialize raises when provider is None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_initialize_raises_when_provider_none() -> None:
    """start() raises RuntimeError mentioning 'provider' when no provider is set."""
    worker = NanobotWorker(worker_type="in-process-nanobot")
    with pytest.raises(RuntimeError, match="provider"):
        await worker.start()


# ---------------------------------------------------------------------------
# Spec #3 — execute calls provider and returns WorkerResult(success=True)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_calls_provider_and_returns_result() -> None:
    """With a mock provider, initialize() succeeds, execute() returns WorkerResult
    with success=True (status=COMPLETED)."""
    provider = _mock_provider()
    worker = NanobotWorker(worker_type="in-process-nanobot", nanobot_provider=provider)

    # Patch AgentRunner via sys.modules (lazy import inside _execute_runner)
    modules = _install_nanobot_runner_mock("task completed")
    with patch.dict(sys.modules, modules, clear=False):
        await worker.start()
        result = await worker.execute({"prompt": "hello"})

    assert isinstance(result, WorkerResult)
    assert result.is_success() is True


# ---------------------------------------------------------------------------
# Spec #4 — worker_id starts with "nanobot_"
# ---------------------------------------------------------------------------

def test_worker_id_starts_with_nanobot() -> None:
    """worker_id property returns a string starting with 'nanobot_'."""
    worker = NanobotWorker()
    assert worker.worker_id.startswith("nanobot_")


# ---------------------------------------------------------------------------
# Spec #5 — loop mode construction sets _is_loop_mode = True
# ---------------------------------------------------------------------------

def test_loop_mode_construction() -> None:
    """NanobotWorker(worker_type='in-process-nanobot-loop') sets _is_loop_mode=True."""
    worker = NanobotWorker(worker_type="in-process-nanobot-loop")
    assert worker._is_loop_mode is True


# ---------------------------------------------------------------------------
# Spec #6 — _init_nanobot_provider returns None when ZAI_API_KEY not set
# ---------------------------------------------------------------------------

def test_init_nanobot_provider_returns_none_when_key_not_set(monkeypatch) -> None:
    """MahavishnuApp._init_nanobot_provider() returns None when ZAI_API_KEY is absent."""
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    app = appmod.MahavishnuApp.__new__(appmod.MahavishnuApp)
    result = appmod.MahavishnuApp._init_nanobot_provider(app)
    assert result is None
