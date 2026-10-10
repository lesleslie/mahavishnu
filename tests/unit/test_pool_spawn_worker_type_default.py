"""Test: ``worker_type`` defaults across pool surfaces point at a
non-retired, registered worker (shepherd).

Wave 7 (2026-10-09) wiring fix. The 2026-09-24 worker-substrate
deprecation retired ``terminal-claude``, ``terminal-qwen``,
``terminal-codex``, and ``container-executor`` in favor of
``shepherd`` (default, fail-closed OS-level syscall jail) and
``gateway-openclaw``. The pre-fix code still defaulted to the
retired ``terminal-claude`` string in three places:

- ``mahavishnu.pools.base.PoolConfig.worker_type`` — the dataclass
  default consumed by every consumer that doesn't override
  explicitly.
- ``mahavishnu.mcp.tools.pool_tools.pool_spawn`` — the MCP tool
  signature default exposed to JSON-RPC callers.
- ``mahavishnu.pools.manager.PoolManager._resolve_auto_spawn_defaults``
  — the classmethod that surfaces config-driven defaults to
  ``pool_bootstrap`` (SessionStart hook).

Pinning the default to a registered, non-retired name at all three
sites is the wiring contract: any caller that doesn't pass an
explicit ``worker_type`` MUST land on a substrate the runtime can
actually execute (``WorkerManager.WORKER_SUPPORTED_TYPES`` is
``frozenset({"shepherd"})``).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from mahavishnu.workers.registry import WORKER_REGISTRY


def test_poolconfig_default_worker_type_is_shepherd() -> None:
    """``PoolConfig()`` (no kwargs) must default ``worker_type`` to
    a registered, non-retired substrate. Shepherd is the only
    post-deprecation default supported by the runtime.
    """
    from mahavishnu.pools.base import PoolConfig

    config = PoolConfig(name="test", pool_type="mahavishnu")

    assert config.worker_type == "shepherd", (
        f"PoolConfig.worker_type default is {config.worker_type!r}; "
        "expected 'shepherd' (the post-2026-09-24 default)"
    )
    assert config.worker_type in WORKER_REGISTRY, (
        f"PoolConfig.worker_type default {config.worker_type!r} is "
        "not in WORKER_REGISTRY — pool_spawn will reject it"
    )
    # The deprecation note retired the terminal-claude family; even
    # though WORKER_REGISTRY still has the entry (for legacy
    # `workers execute` calls), the runtime refuses to use it for
    # pool spawn. Pin that the default is NOT a terminal-* alias.
    assert not config.worker_type.startswith("terminal-"), (
        f"PoolConfig.worker_type default {config.worker_type!r} "
        "starts with 'terminal-' (a 2026-09-24 retired family)"
    )


def test_pool_spawn_mcp_tool_default_worker_type_is_shepherd() -> None:
    """The ``pool_spawn`` MCP tool's ``worker_type`` parameter must
    default to a registered, non-retired substrate — same contract
    as ``PoolConfig``. The tool is registered through a closure
    inside ``register_pool_tools``, so we inspect the registered
    function's signature via a stand-in FastMCP.

    Source-grep guard for the literal string catches future
    regressions even if the surrounding code is restructured.
    """
    import inspect
    from pathlib import Path

    pool_tools_src = Path(
        "mahavishnu/mcp/tools/pool_tools.py"
    ).read_text(encoding="utf-8")
    # The pool_spawn tool defines its own default. We assert that:
    #   1) it is the string "shepherd" (not a terminal-* alias), and
    #   2) the parameter annotation default on the inner function is
    #      bound to a registered worker.
    assert 'worker_type: str = "shepherd"' in pool_tools_src, (
        "pool_spawn MCP tool default for worker_type is not "
        "'shepherd' — pool_spawn will produce a config that "
        "WorkerManager cannot execute"
    )

    class _NoOpMcp:
        def __init__(self) -> None:
            self._registered: dict[str, Any] = {}

        def tool(self) -> Any:
            def _decorator(fn: Any) -> Any:
                self._registered[fn.__name__] = fn
                return fn

            return _decorator

    from mahavishnu.mcp.tools.pool_tools import register_pool_tools

    mcp = _NoOpMcp()
    register_pool_tools(mcp, MagicMock())  # type: ignore[arg-type]
    spawn = mcp._registered["pool_spawn"]
    sig = inspect.signature(spawn)
    assert sig.parameters["worker_type"].default == "shepherd", (
        f"pool_spawn worker_type default is "
        f"{sig.parameters['worker_type'].default!r}; expected 'shepherd'"
    )


def test_resolve_auto_spawn_defaults_includes_worker_type() -> None:
    """``PoolManager._resolve_auto_spawn_defaults`` (classmethod) must
    surface a ``worker_type`` key so the SessionStart bootstrap hook
    can build a PoolConfig that the runtime accepts. Without this
    key, the bootstrap would default to whatever ``PoolConfig``
    picks — which after the fix is shepherd, but the explicit
    surface here is the contract that lets the bootstrap override
    the default via config (e.g. set ``gateway-openclaw`` for
    environments with ``OPENCLAW_GATEWAY_URL``).
    """
    from mahavishnu.pools.manager import PoolManager

    result = PoolManager._resolve_auto_spawn_defaults()
    assert "worker_type" in result, (
        "_resolve_auto_spawn_defaults() must surface a "
        "'worker_type' key — without it, pool_bootstrap cannot "
        "honor per-environment worker overrides"
    )
    assert result["worker_type"] in WORKER_REGISTRY, (
        f"_resolve_auto_spawn_defaults() surfaced "
        f"{result['worker_type']!r}, not in WORKER_REGISTRY"
    )


def test_worker_manager_runtime_accepts_default() -> None:
    """The runtime side must accept the same default that
    ``PoolConfig`` and the MCP tool surface — the worker type the
    default produces MUST be in the runtime's ``WORKER_SUPPORTED_TYPES``
    module constant. Otherwise a default-driven spawn hard-fails with
    ``ValueError("Unsupported worker type ...")`` before any
    substrate code runs.

    The constant lives at module scope (not on the ``WorkerManager``
    class) so we import it directly from the workers.manager module.
    """
    from mahavishnu.pools.base import PoolConfig
    from mahavishnu.workers.manager import WORKER_SUPPORTED_TYPES

    config = PoolConfig(name="test", pool_type="mahavishnu")
    assert config.worker_type in WORKER_SUPPORTED_TYPES, (
        f"PoolConfig default {config.worker_type!r} is NOT in "
        f"workers.manager.WORKER_SUPPORTED_TYPES "
        f"({sorted(WORKER_SUPPORTED_TYPES)}) — "
        "WorkerManager would refuse to spawn this pool"
    )
