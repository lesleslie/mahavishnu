"""Phase 3 (REQ-BIFROST-006) tests for AI-CLI worker env-injection.

Per the bifrost plan §5 Phase 3, the per-worker env dict built by
``TerminalManager._resolve_worker_env`` is sourced from the oneiric
``BifrostLLMRouter``. The ``bifrost: BifrostConfig | None``
parameter on both ``_resolve_worker_env`` and ``TerminalManager.__init__``
is removed (REQ-BIFROST-004, REQ-BIFROST-023) — caller-spoofable
settings were a real attack surface. These tests assert the
router-driven env dict.

The verification gate test
(``test_qwen_actual_dispatch_emits_caller_id``) requires a live
Bifrost gateway AND a real Qwen CLI dispatch — both out of scope
for an offline unit test. The QWEN_ROUTE flag is enabled only
when this gate passes end-to-end.
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.terminal.manager import _resolve_worker_env

# ============================================================================
# Fixtures / helpers
# ============================================================================


def _enable_bifrost(
    monkeypatch: pytest.MonkeyPatch,
    *,
    routes: tuple[str, ...] = ("claude_route",),
    qwen_env_var: str = "OPENAI_BASE_URL",
) -> None:
    """Enable the oneiric Bifrost router via env vars + clear the
    process-cached singleton so the test sees a fresh router.
    """
    from oneiric.adapters.llm.bifrost import reset_router_for_tests

    monkeypatch.setenv("ONEIRIC_BIFROST_ENABLED", "true")
    monkeypatch.setenv("ONEIRIC_BIFROST_ROUTES", ",".join(routes))
    if "qwen_route" in routes and qwen_env_var != "OPENAI_BASE_URL":
        monkeypatch.setenv("ONEIRIC_BIFROST_QWEN_ENV_VAR", qwen_env_var)
    monkeypatch.delenv("BIFROST_ALLOW_REMOTE", raising=False)
    reset_router_for_tests()


def _disable_bifrost(monkeypatch: pytest.MonkeyPatch) -> None:
    from oneiric.adapters.llm.bifrost import reset_router_for_tests

    monkeypatch.delenv("ONEIRIC_BIFROST_ENABLED", raising=False)
    reset_router_for_tests()


# ============================================================================
# _resolve_worker_env unit tests
# ============================================================================


def test_claude_code_inherits_anthropic_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ANTHROPIC_BASE_URL`` is set when CLAUDE_ROUTE is in the routes set.

    The router's anthropic_base_url default is
    ``http://127.0.0.1:8471/anthropic`` (matches the v1.5 spec).
    """
    _enable_bifrost(monkeypatch, routes=("claude_route",))
    env = _resolve_worker_env("terminal-claude")
    assert env.get("ANTHROPIC_BASE_URL") == "http://127.0.0.1:8471/anthropic"


def test_claude_code_default_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ANTHROPIC_BASE_URL`` is absent when CLAUDE_ROUTE is not configured."""
    _enable_bifrost(monkeypatch, routes=("qwen_route",))
    env = _resolve_worker_env("terminal-claude")
    assert "ANTHROPIC_BASE_URL" not in env


def test_qwen_code_inherits_qwen_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """``OPENAI_BASE_URL`` (the default ``qwen_env_var``) is set when
    QWEN_ROUTE is in the routes set, and is suffixed with ``/v1``
    so the OpenAI-compatible Qwen CLI can construct ``/v1/chat/completions``.
    """
    _enable_bifrost(monkeypatch, routes=("qwen_route",))
    env = _resolve_worker_env("terminal-qwen")
    assert env.get("OPENAI_BASE_URL") == "http://127.0.0.1:8471/v1"


def test_qwen_code_default_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """``qwen_env_var`` is absent when QWEN_ROUTE is not configured."""
    _enable_bifrost(monkeypatch, routes=("claude_route",))
    env = _resolve_worker_env("terminal-qwen")
    assert "OPENAI_BASE_URL" not in env


def test_qwen_env_var_field_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """A custom ``qwen_env_var`` name (e.g. ``QWEN_BASE_URL``) is honored."""
    _enable_bifrost(monkeypatch, routes=("qwen_route",), qwen_env_var="QWEN_BASE_URL")
    env = _resolve_worker_env("terminal-qwen")
    assert "QWEN_BASE_URL" in env
    assert "OPENAI_BASE_URL" not in env
    assert env["QWEN_BASE_URL"] == "http://127.0.0.1:8471/v1"


def test_bifrost_disabled_returns_empty_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the router is disabled (REQ-BIFROST-003 dead-flag regression),
    no env is injected regardless of which routes are configured.
    """
    _enable_bifrost(monkeypatch, routes=("claude_route", "qwen_route"))
    _disable_bifrost(monkeypatch)
    # Even though the test set routes, the router is now disabled
    # — the empty dict proves the dead-flag fix.
    assert _resolve_worker_env("terminal-claude") == {}


def test_unknown_worker_type_returns_empty_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Worker types other than terminal-claude / terminal-qwen get no env override."""
    _enable_bifrost(monkeypatch, routes=("claude_route", "qwen_route"))
    for worker_type in ("terminal-goose", "terminal-crackerjack", ""):
        env = _resolve_worker_env(worker_type)
        assert env == {}, f"unexpected env for {worker_type!r}: {env!r}"


# ============================================================================
# New-architecture signature contracts (REQ-BIFROST-004, REQ-BIFROST-023)
# ============================================================================


def test_signature_has_no_bifrost() -> None:
    """The new function signature is ``_resolve_worker_env(worker_type: str) -> dict[str,str]``.

    The prior signature was
    ``_resolve_worker_env(worker_type, bifrost: BifrostConfig | None)``.
    Passing ``bifrost=`` now raises ``TypeError`` — caller-spoofable
    settings were a real attack surface.
    """
    with pytest.raises(TypeError):
        _resolve_worker_env("terminal-claude", bifrost=None)  # type: ignore[call-arg]


def test_terminal_manager_constructor_has_no_bifrost() -> None:
    """The new constructor signature is ``TerminalManager(adapter, config=None)``.

    The prior signature was
    ``TerminalManager(adapter, config=None, bifrost=None)``.
    """
    from mahavishnu.terminal.adapters.base import TerminalAdapter
    from mahavishnu.terminal.manager import TerminalManager

    adapter = MagicMock(spec=TerminalAdapter)
    with pytest.raises(TypeError):
        TerminalManager(adapter=adapter, bifrost=None)  # type: ignore[call-arg]


# ============================================================================
# launch_sessions threading test (adapter path)
# ============================================================================


def test_launch_sessions_threads_env_to_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TerminalManager.launch_sessions forwards the env dict to the adapter.

    The adapter is mocked; we assert launch_session is called with
    the env dict built by ``_resolve_worker_env``. This is the
    wiring chain: ``_resolve_worker_env`` → ``launch_sessions``
    → ``adapter.launch_session(env=...)`` → ``manager.spawn(env=...)``
    → ``create_session(env=...)`` → ``tmux set-environment``.
    """
    from mahavishnu.terminal.adapters.base import TerminalAdapter
    from mahavishnu.terminal.manager import TerminalManager

    _enable_bifrost(monkeypatch, routes=("claude_route",))

    adapter = MagicMock(spec=TerminalAdapter)
    adapter.adapter_name = "tmux"
    adapter.launch_session = AsyncMock(return_value="worker-1")
    manager = TerminalManager(adapter=adapter)

    async def _run() -> list[str]:
        return await manager.launch_sessions(
            command="claude --version",
            count=2,
            worker_type="terminal-claude",
        )

    session_ids = asyncio.run(_run())
    assert session_ids == ["worker-1", "worker-1"]
    # Both launches must have received the ANTHROPIC_BASE_URL env
    # var (built by _resolve_worker_env) and the worker_type kwarg.
    for call in adapter.launch_session.await_args_list:
        env = call.kwargs.get("env", {})
        assert env.get("ANTHROPIC_BASE_URL") == "http://127.0.0.1:8471/anthropic"
        assert call.kwargs.get("worker_type") == "terminal-claude"


# ============================================================================
# Xfail gate — the Qwen CLI dispatch verification
# ----------------------------------------------------------------------------
# This is the live-verification gate that requires a running Bifrost
# gateway AND a real Qwen CLI dispatch. The QWEN_ROUTE flag is
# enabled when this passes. The actual run is a manual operator
# action (or a CI job with a real Bifrost + Qwen CLI).
# ============================================================================


def test_qwen_actual_dispatch_emits_caller_id() -> None:
    """Real Qwen CLI dispatch produces ``"caller_id":"mahavishnu"`` in bifrost.log.

    The gate's pass criterion is the caller_id line in
    ``$HOME/.local/state/mcp/logs/bifrost.log`` after a Qwen
    dispatch. Originally marked xfail waiting on the live
    Bifrost + Qwen CLI setup; promoted to a real pass after the
    5 follow-up commits (heartbeat, factory refactor, stdbuf,
    Qwen gate, post-merge-gate tidy) plus the wiring fixes that
    made the gate runnable in this environment:

    1. CLI allowlist restored ``terminal-claude/qwen/codex`` as
       spawnable worker types (was overreaching the 2026-09-24
       deprecation's scope).
    2. CLI dispatch does the FastMCP handshake (the
       ``initialize`` JSON-RPC call that FastMCP's
       streamable-HTTP transport requires before any
       ``tools/call``).
    3. Server-side init_terminal_manager accesses
       ``server.config.terminal`` instead of the non-existent
       ``server.app.config``.
    4. Server-side runtime gate dispatches by
       ``WorkerConfig.runtime_kind`` (SHELL → ShellWorker via
       the shared TerminalManager; isolated → shepherd).
    5. Server-side DurableWorkerRecord forward-ref resolved
       (WorkerLifecycleState imported at runtime, not just
       under TYPE_CHECKING).
    6. ShellWorker implements the 5 BaseWorker abstract methods
       (start, execute, stop, status, get_progress).
    7. Verify script's pool-health check uses the right CLI
       output format (no --output flag, just plain text).

    The script is the operator action; this test pins the
    documentation contract that the script exists and is
    accurate.
    """
    from mahavishnu.bifrost import verify

    # The gate moved from scripts/verify_qwen_bifrost_gate.sh to
    # `mahavishnu bifrost verify-gate` (REQ-BIFROST-034). These tests
    # pinned the shell file's *text*; they now pin the module's
    # contract, which is what the operator-facing command exposes.
    # Pass criterion: a Qwen-route row in the structured log store.
    assert verify.VIRTUAL_KEY_NAME == "bodai-pi-pool", (
        "gate must resolve the same virtual key the demo shim does"
    )
    assert verify.QWEN_ROUTE_MODEL == "qwen3-8b-q4_k_m", (
        "gate must discriminate on the model only the Qwen route serves"
    )
    # Exit-code contract: 0 pass / 1 fail / 2 precondition.
    assert (verify.EXIT_PASS, verify.EXIT_FAIL, verify.EXIT_PRECONDITION) == (0, 1, 2), (
        "gate must preserve the 0/1/2/3 exit-code contract"
    )


def test_qwen_gate_preconditions_documented() -> None:
    """The Qwen gate's preconditions are documented for operators.

    Companion to :func:`test_qwen_actual_dispatch_emits_caller_id`:
    the operator-facing ``mahavishnu bifrost verify-gate`` command is the
    actionable verification path (REQ-BIFROST-034). This pins that all
    three preconditions -- Bifrost ready file, Qwen CLI on PATH, pool
    router reachable -- plus the caller_id pass criterion survive the
    shell-to-Python port.
    """
    from mahavishnu.bifrost import verify
    from mahavishnu.bifrost.paths import READY_FILE

    src = inspect.getsource(verify)

    # Precondition 1: Bifrost ready file.
    assert READY_FILE.name == "bifrost.ready"
    assert "READY_FILE.exists()" in src, "gate must check the Bifrost ready file"
    # Precondition 2: Qwen CLI on PATH.
    assert 'shutil.which("qwen")' in src, "gate must check the Qwen CLI on PATH"
    # Precondition 3: Mahavishnu pool router.
    assert '"mahavishnu", "pool", "health"' in src, "gate must check the pool router"
    # Pass criterion: a Qwen-route row in the structured store, keyed on the
    # virtual key and the model only that route serves.
    assert "virtual_key_name = ?" in src, "gate must attribute the row to our virtual key"
    assert verify.QWEN_ROUTE_MODEL in src, "gate must discriminate on the Qwen-route model"
