"""Phase D (REQ-004) tests for AI-CLI worker env-injection.

Per docs/plans/2026-10-15-bifrost-gateway-wiring.md §5 Phase D exit
criteria. These tests assert the per-worker env dict built by
``TerminalManager._resolve_worker_env`` and threaded through
``TmuxTerminalAdapter.launch_session``/``launch_sessions`` to
``DurableWorkerManager.spawn`` and finally to
``create_session``'s ``tmux set-environment -t <session> KEY VAL``
emission.

The verification gate test
(``test_qwen_actual_dispatch_emits_caller_id``) is marked
``pytest.mark.xfail`` because it requires a live Bifrost gateway
AND a real Qwen CLI dispatch — both out of scope for an offline
unit test. Phase D ships with ``route_qwen_code: false`` by
default; the flag is enabled only when this gate passes.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.core.config import BifrostConfig
from mahavishnu.terminal.manager import _resolve_worker_env

# ============================================================================
# _resolve_worker_env unit tests
# ============================================================================


def _bifrost(**overrides: object) -> BifrostConfig:
    """Build a BifrostConfig with the given field overrides."""
    return BifrostConfig.model_validate(overrides)


def test_claude_code_inherits_anthropic_base_url() -> None:
    """``ANTHROPIC_BASE_URL`` is set when route_claude_code is true."""
    bifrost = _bifrost(enabled=True, route_claude_code=True)
    env = _resolve_worker_env("terminal-claude", bifrost)
    assert env.get("ANTHROPIC_BASE_URL") == bifrost.anthropic_base_url
    assert env.get("ANTHROPIC_BASE_URL") == "http://127.0.0.1:8471/anthropic"


def test_claude_code_default_unchanged() -> None:
    """``ANTHROPIC_BASE_URL`` is absent when route_claude_code is false (default)."""
    bifrost = _bifrost(enabled=True)  # route_claude_code defaults to False
    env = _resolve_worker_env("terminal-claude", bifrost)
    assert "ANTHROPIC_BASE_URL" not in env


def test_qwen_code_inherits_qwen_env_var() -> None:
    """``OPENAI_BASE_URL`` (the default ``qwen_env_var``) is set when route_qwen_code is true."""
    bifrost = _bifrost(enabled=True, route_qwen_code=True)
    env = _resolve_worker_env("terminal-qwen", bifrost)
    # The env var name is bifrost.qwen_env_var; the value is the
    # Bifrost OpenAI-compatible provider's base URL.
    assert env.get("OPENAI_BASE_URL") == "http://127.0.0.1:8471/v1"


def test_qwen_code_default_unchanged() -> None:
    """``qwen_env_var`` is absent when route_qwen_code is false (default)."""
    bifrost = _bifrost(enabled=True)  # route_qwen_code defaults to False
    env = _resolve_worker_env("terminal-qwen", bifrost)
    assert "OPENAI_BASE_URL" not in env


def test_qwen_env_var_field_override() -> None:
    """A custom ``qwen_env_var`` name is honored."""
    bifrost = _bifrost(
        enabled=True,
        route_qwen_code=True,
        qwen_env_var="QWEN_BASE_URL",
    )
    env = _resolve_worker_env("terminal-qwen", bifrost)
    assert "QWEN_BASE_URL" in env
    assert "OPENAI_BASE_URL" not in env
    assert env["QWEN_BASE_URL"] == "http://127.0.0.1:8471/v1"


def test_bifrost_disabled_returns_empty_env() -> None:
    """When ``bifrost.enabled`` is False (default), no env is injected regardless of route flags."""
    bifrost = _bifrost()  # enabled defaults to False
    assert _resolve_worker_env("terminal-claude", bifrost) == {}
    bifrost_with_flags = _bifrost(route_claude_code=True)
    assert _resolve_worker_env("terminal-claude", bifrost_with_flags) == {}


def test_unknown_worker_type_returns_empty_env() -> None:
    """Worker types other than terminal-claude / terminal-qwen get no env override."""
    bifrost = _bifrost(enabled=True, route_claude_code=True, route_qwen_code=True)
    for worker_type in ("terminal-goose", "terminal-crackerjack", ""):
        env = _resolve_worker_env(worker_type, bifrost)
        assert env == {}, f"unexpected env for {worker_type!r}: {env!r}"


def test_none_bifrost_returns_empty_env() -> None:
    """When bifrost is None (no settings wired), the helper returns empty."""
    assert _resolve_worker_env("terminal-claude", None) == {}


# ============================================================================
# launch_sessions threading test (adapter path)
# ============================================================================


def test_launch_sessions_threads_env_to_adapter() -> None:
    """TerminalManager.launch_sessions forwards the env dict to the adapter.

    The adapter is mocked; we assert launch_session is called with
    the env dict built by ``_resolve_worker_env``. This is the
    wiring chain: ``_resolve_worker_env`` → ``launch_sessions``
    → ``adapter.launch_session(env=...)`` → ``manager.spawn(env=...)``
    → ``create_session(env=...)`` → ``tmux set-environment``.
    """
    from mahavishnu.terminal.adapters.base import TerminalAdapter
    from mahavishnu.terminal.manager import TerminalManager

    bifrost = _bifrost(enabled=True, route_claude_code=True)
    adapter = MagicMock(spec=TerminalAdapter)
    adapter.adapter_name = "tmux"
    # AsyncMock makes `await adapter.launch_session(...)` return
    # the worker_id string directly. MagicMock's `return_value`
    # is what the awaited result unwraps to.
    adapter.launch_session = AsyncMock(return_value="worker-1")
    manager = TerminalManager(adapter=adapter, bifrost=bifrost)

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
# gateway AND a real Qwen CLI dispatch. Phase D ships with
# route_qwen_code: false; the flag is enabled when this passes.
# It is documented as xfail so the suite still ships in CI; the
# actual run is a manual operator action (or a CI job with a real
# Bifrost + Qwen CLI).
# ============================================================================


@pytest.mark.xfail(
    reason="Verification gate — requires live Bifrost + Qwen CLI. Run scripts/verify_qwen_bifrost_gate.sh manually; flip xfail → real pass when the script returns 0.",
    strict=False,
)
def test_qwen_actual_dispatch_emits_caller_id() -> None:
    """Real Qwen CLI dispatch produces ``"caller_id":"mahavishnu"`` in bifrost.log.

    This is the gate test. It is structurally a real-network test
    that requires:
    1. Bifrost running on 127.0.0.1:8471 (the ready file at
       ``$HOME/.local/state/mcp/ready/bifrost.ready`` must exist).
    2. A real Qwen CLI binary on PATH (with the correct env-var
       name verified — the plan's default of OPENAI_BASE_URL is
       a guess; the actual name may be QWEN_BASE_URL or
       DASHSCOPE_API_BASE per the Qwen CLI version).
    3. A `mahavishnu pool route_execute` against a Qwen worker.

    The xfail annotation is the test's CI posture: when CI runs
    without the real Bifrost + Qwen CLI setup, the test xfails
    gracefully and the suite ships. The operator-facing
    verification is :file:`scripts/verify_qwen_bifrost_gate.sh`:
    run that script manually against your local Bifrost + Qwen CLI
    setup, and when it returns 0 the gate is satisfied — flip the
    xfail to a real assertion (assert the caller_id line is in
    bifrost.log after the gate script's dispatch) and set
    ``bifrost.route_qwen_code: true`` in
    ``settings/mahavishnu.yaml``.

    Marked xfail (not skip) so CI surfaces the gate's pending
    state in the rollup. ``strict=False`` so the test remains
    pending — the xfail never becomes a hard fail in CI, only
    operator action can promote it to a real pass.
    """
    # The xfail annotation is the test; raise explicitly so the
    # contract is enforced even when -O is set (ruff B011 rule).
    raise AssertionError("verification gate — run scripts/verify_qwen_bifrost_gate.sh")


def test_qwen_gate_preconditions_documented() -> None:
    """The Qwen gate's preconditions are documented for operators.

    Companion to :func:`test_qwen_actual_dispatch_emits_caller_id`:
    when the env is ready, the operator-facing script at
    ``scripts/verify_qwen_bifrost_gate.sh`` is the actionable
    verification path. This test pins the file's existence and
    that it documents all three preconditions (Bifrost ready
    file, Qwen CLI on PATH, Mahavishnu pool router reachable)
    plus the pass criterion (caller_id line in bifrost.log).
    """
    import shutil as _shutil
    from pathlib import Path as _Path

    repo_root = _Path(__file__).resolve().parent.parent.parent
    script = repo_root / "scripts" / "verify_qwen_bifrost_gate.sh"
    assert script.exists(), f"missing operator gate script at {script}"
    assert _shutil.which("bash") is not None, "bash required for the gate script"
    text = script.read_text(encoding="utf-8")
    # Precondition 1: Bifrost ready file.
    assert "bifrost.ready" in text, "gate script must check the Bifrost ready file"
    # Precondition 2: Qwen CLI on PATH.
    assert "qwen" in text, "gate script must check the Qwen CLI on PATH"
    # Precondition 3: Mahavishnu pool router.
    assert "mahavishnu pool health" in text, "gate script must check the pool router"
    # Pass criterion: caller_id line in bifrost.log.
    assert '"caller_id":"mahavishnu"' in text, (
        "gate script must assert the caller_id line is in bifrost.log"
    )
    # Exit-code contract.
    assert "exit 0" in text and "exit 1" in text and "exit 2" in text, (
        "gate script must document the 0/1/2/3 exit-code contract"
    )
