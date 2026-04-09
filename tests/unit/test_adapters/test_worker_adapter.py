"""Unit tests for core.adapters.worker."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import mahavishnu.core.adapters.worker as wa


class _Result:
    def __init__(self, status: str, output: str | None, duration: float, ok: bool) -> None:
        self.status = SimpleNamespace(value=status)
        self.output = output
        self.duration_seconds = duration
        self._ok = ok

    def is_success(self) -> bool:
        return self._ok

    def has_output(self) -> bool:
        return bool(self.output)


class _Manager:
    def __init__(self) -> None:
        self.nanobot_provider = object()
        self.spawn_calls: list[tuple[str, int]] = []
        self.exec_calls: list[tuple[list[str], list[dict]]] = []
        self.collect_calls: list[list[str]] = []
        self.raise_spawn = False
        self.raise_exec = False

    async def spawn_workers(self, worker_type: str, count: int) -> list[str]:
        self.spawn_calls.append((worker_type, count))
        if self.raise_spawn:
            raise RuntimeError("spawn failed")
        return [f"w{i}" for i in range(count)]

    async def execute_batch(self, worker_ids: list[str], tasks: list[dict]) -> dict[str, _Result]:
        self.exec_calls.append((worker_ids, tasks))
        if self.raise_exec:
            raise RuntimeError("exec failed")
        return {
            worker_ids[0]: _Result("completed", "ok", 1.0, True),
            worker_ids[1]: _Result("failed", "x" * 250, 2.0, False),
        }

    async def collect_results(self, worker_ids: list[str]) -> dict[str, _Result]:
        self.collect_calls.append(worker_ids)
        return {worker_ids[0]: _Result("completed", "fallback", 1.1, True)}

    async def health_check(self) -> dict:
        return {"workers_active": 1, "max_concurrent": 10, "debug_mode": False}


def test_adapter_properties_and_init_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = _Manager()
    a = wa.WorkerOrchestratorAdapter(worker_manager=mgr)
    assert a.adapter_type.value == "worker"
    assert a.name == "worker"
    assert a.capabilities.can_monitor_execution is True
    assert a.capabilities.supports_batch_execution is True

    # config-as-manager path
    monkeypatch.setattr(wa, "WorkerManager", _Manager)
    mgr2 = _Manager()
    a2 = wa.WorkerOrchestratorAdapter(config=mgr2)
    assert a2.worker_manager is mgr2

    with pytest.raises(ValueError):
        wa.WorkerOrchestratorAdapter(config=None, worker_manager=None)


@pytest.mark.asyncio
async def test_execute_validation_and_success_and_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = _Manager()
    adapter = wa.WorkerOrchestratorAdapter(worker_manager=mgr)
    monkeypatch.setattr(wa, "resolve_worker_type", lambda req, task_type, prompt: "terminal-qwen")

    with pytest.raises(ValueError):
        await adapter.execute({"prompt": ""}, ["/repo"])
    with pytest.raises(ValueError):
        await adapter.execute({"prompt": "x", "count": 0}, ["/repo"])

    out = await adapter.execute(
        {"worker_type": "terminal-qwen", "prompt": "do thing", "count": 2, "task_type": "general"},
        ["/repo1", "/repo2"],
    )
    assert out["worker_count"] == 2
    assert out["resolved_worker_type"] == "terminal-qwen"
    assert out["successful"] == 1
    assert out["failed"] == 1
    assert out["status"] == "partial"
    assert out["results"]["w1"]["output"].endswith("...")

    # execute_batch failure -> collect_results fallback
    mgr.raise_exec = True
    out2 = await adapter.execute({"prompt": "x", "count": 1}, ["/repo"])
    assert out2["successful"] == 1
    assert mgr.collect_calls

    # spawn failure surfaces
    mgr.raise_spawn = True
    with pytest.raises(RuntimeError):
        await adapter.execute({"prompt": "x", "count": 1}, ["/repo"])


@pytest.mark.asyncio
async def test_health_and_lifecycle_methods() -> None:
    mgr = _Manager()
    adapter = wa.WorkerOrchestratorAdapter(worker_manager=mgr)
    assert await adapter.initialize() is None
    assert await adapter.cleanup() is None
    health = await adapter.get_health()
    assert health["status"] == "healthy"
    assert health["nanobot_available"] is True

    # degraded branch
    async def hc():
        return {"workers_active": 10, "max_concurrent": 10}

    mgr.health_check = hc  # type: ignore[method-assign]
    health2 = await adapter.get_health()
    assert health2["status"] == "degraded"


def test_nanobot_provider_fallback_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    # token missing -> None
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert wa.WorkerOrchestratorAdapter._init_nanobot_provider_fallback() is None

    # import error -> None
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    import builtins

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001,ANN002,ANN003
        if name == "nanobot.providers":
            raise ImportError("missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)
    assert wa.WorkerOrchestratorAdapter._init_nanobot_provider_fallback() is None
    monkeypatch.setattr("builtins.__import__", real_import)

    # success path
    class _Provider:
        def __init__(self, api_key: str, base_url: str) -> None:
            self.api_key = api_key
            self.base_url = base_url

    mod = SimpleNamespace(OpenAICompatProvider=_Provider)
    import sys

    sys.modules["nanobot.providers"] = mod
    p = wa.WorkerOrchestratorAdapter._init_nanobot_provider_fallback()
    assert p is not None
    assert p.api_key == "tok"
    assert p.base_url == "https://api.anthropic.com"

    # gateway override path
    monkeypatch.setenv("BIFROST_BASE_URL", "http://127.0.0.1:8471")
    p2 = wa.WorkerOrchestratorAdapter._init_nanobot_provider_fallback()
    assert p2 is not None
    assert p2.base_url == "http://127.0.0.1:8471/v1"
    monkeypatch.delenv("BIFROST_BASE_URL", raising=False)

    # generic exception path
    class _BadProvider:
        def __init__(self, api_key: str, base_url: str) -> None:  # noqa: ARG002
            raise RuntimeError("bad")

    sys.modules["nanobot.providers"] = SimpleNamespace(OpenAICompatProvider=_BadProvider)
    assert wa.WorkerOrchestratorAdapter._init_nanobot_provider_fallback() is None


def test_worker_adapter_entries_shape() -> None:
    entries = wa.worker_adapter_entries()
    assert len(entries) == 1
    e = entries[0]
    assert e["provider"] == "worker"
    assert e["domain"] == "orchestration"
    assert "parallel_execution" in e["capabilities"]


def test_init_with_config_branch_uses_terminal_and_context(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class _WM:
        def __init__(self, **kwargs):  # noqa: ANN003
            captured.update(kwargs)
            self.nanobot_provider = kwargs.get("nanobot_provider")

    monkeypatch.setattr(wa, "WorkerManager", _WM)
    monkeypatch.setattr("mahavishnu.terminal.manager.TerminalManager.create", lambda cfg, mcp_client=None: "tmgr")
    import mahavishnu.core.context as ctx

    monkeypatch.setattr(ctx, "get_app_context", lambda: {"nanobot_provider": "ctx-provider"}, raising=False)

    cfg = SimpleNamespace(workers=SimpleNamespace(max_concurrent=7))
    adapter = wa.WorkerOrchestratorAdapter(config=cfg)
    assert adapter.worker_manager.nanobot_provider == "ctx-provider"
    assert captured["terminal_manager"] == "tmgr"
    assert captured["max_concurrent"] == 7

    # fallback provider branch when context has no provider
    monkeypatch.setattr(ctx, "get_app_context", lambda: {}, raising=False)
    monkeypatch.setattr(
        wa.WorkerOrchestratorAdapter,
        "_init_nanobot_provider_fallback",
        staticmethod(lambda: "fallback-provider"),
    )
    adapter2 = wa.WorkerOrchestratorAdapter(config=cfg)
    assert adapter2.worker_manager.nanobot_provider == "fallback-provider"
