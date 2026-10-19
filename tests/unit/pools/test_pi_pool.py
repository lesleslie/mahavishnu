"""Unit tests for PiPool — per-task subprocess mocked via ``subprocess_runner`` seam.

The pool's per-task invocation is one ``asyncio.create_subprocess_exec``
call; tests inject an in-memory coroutine that returns a canned
``(returncode, stdout, stderr)`` triple instead of spawning a real
subprocess. This keeps the test suite hermetic (no Node.js / npx
required to run) while preserving the public surface.

Req: REQ-PI-008
"""  # req: REQ-PI-008

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Protocol
from unittest.mock import MagicMock

import pytest

from mahavishnu.core.errors import PiUnavailable
from mahavishnu.pools._registry import list_pool_types
from mahavishnu.pools.base import PoolConfig, PoolStatus
from mahavishnu.pools.pi_pool import (
    PiPool,
    SubprocessRunner,
    _looks_like_error_output,
)


class _FakeRunner:
    """In-memory ``SubprocessRunner`` that returns canned results.

    Tests call ``set_return`` to queue a return tuple; the next call
    pops it (FIFO). ``set_side_effect`` lets a test install an
    exception to be raised (e.g. ``asyncio.TimeoutError``).
    """

    def __init__(self) -> None:
        self.returns: list[tuple[int, str, str]] = []
        self.side_effects: list[BaseException] = []
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        *,
        argv: tuple[str, ...],
        env: dict[str, str],
        timeout: float,
    ) -> tuple[int, str, str]:
        self.calls.append({"argv": argv, "env": dict(env), "timeout": timeout})
        if self.returns:
            return self.returns.pop(0)
        if self.side_effects:
            raise self.side_effects.pop(0)
        return (0, "", "")

    def set_return(self, returncode: int, stdout: str, stderr: str = "") -> None:
        self.returns.append((returncode, stdout, stderr))

    def set_side_effect(self, exc: BaseException) -> None:
        self.side_effects.append(exc)


def _make_fake_runner() -> _FakeRunner:
    """Build a fresh fake runner with default success return."""
    runner = _FakeRunner()
    runner.set_return(0, "1.0.0")  # for the start() --version probe
    return runner


def _make_pool(
    *,
    config: PoolConfig | None = None,
    runner: _FakeRunner | None = None,
    runtime_probe=None,
    env_allowlist: tuple[str, ...] | None = None,
) -> tuple[PiPool, _FakeRunner]:
    """Build a PiPool with a deterministic in-memory runner.

    Returns ``(pool, runner)``. The pool is *not* started; tests call
    ``pool.start()`` themselves when they want the version probe to
    run.
    """
    if config is None:
        config = PoolConfig(
            name="test-pi",
            pool_type="pi",
            min_workers=1,
            max_workers=1,
        )
    if runner is None:
        runner = _make_fake_runner()
    pool = PiPool(
        config=config,
        runtime_probe=runtime_probe,
        subprocess_runner=runner,
        env_allowlist=env_allowlist,
    )
    return pool, runner


# --- scale() --------------------------------------------------------------


@pytest.mark.asyncio
async def test_scale_n_greater_than_one_raises_not_implemented_error() -> None:
    pool, _ = _make_pool()
    with pytest.raises(NotImplementedError) as excinfo:
        await pool.scale(2)
    msg = str(excinfo.value)
    assert "fixed worker count" in msg.lower()
    assert "1" in msg
    # Matches SessionBuddyPool error wording for consistency.
    assert "Spawn additional pools" in msg


@pytest.mark.asyncio
async def test_scale_n_equals_one_is_noop() -> None:
    pool, _ = _make_pool()
    # Should NOT raise.
    await pool.scale(1)
    # Internal state must be untouched (we never started the pool).
    assert pool._status == PoolStatus.PENDING


@pytest.mark.parametrize("n", [0, -1, -5])
@pytest.mark.asyncio
async def test_scale_n_less_than_one_raises_value_error(n: int) -> None:
    """scale(n < 1) must raise ValueError — not silently no-op."""
    pool, _ = _make_pool()
    with pytest.raises(ValueError) as excinfo:
        await pool.scale(n)
    assert "target_worker_count" in str(excinfo.value)


def test_init_rejects_max_workers_greater_than_one() -> None:
    """PiPool has fixed worker count (1). max_workers > 1 must raise at __init__."""
    from mahavishnu.pools.base import PoolConfig
    from mahavishnu.pools.pi_pool import PiPool

    config = PoolConfig(
        name="bad-pool",
        pool_type="pi",
        min_workers=1,
        max_workers=5,
    )
    with pytest.raises(ValueError) as excinfo:
        PiPool(config=config)
    assert "max_workers" in str(excinfo.value)
    assert "1" in str(excinfo.value)


# --- npx_command validation ----------------------------------------------


def test_npx_command_rejects_non_npx_binary() -> None:
    """Settings must reject cmd[0] not in {npx, /usr/bin/env, /usr/local/bin/npx}."""
    from mahavishnu.core.config import PiPoolSettings
    from mahavishnu.core.errors import ConfigurationError

    with pytest.raises(ConfigurationError) as excinfo:
        PiPoolSettings(npx_command=("/bin/sh", "-c", "evil"))  # type: ignore[arg-type]
    assert "npx, /usr/bin/env, or /usr/local/bin/npx" in str(excinfo.value)


def test_npx_command_requires_pi_package_name() -> None:
    from mahavishnu.core.config import PiPoolSettings
    from mahavishnu.core.errors import ConfigurationError

    with pytest.raises(ConfigurationError) as excinfo:
        PiPoolSettings(npx_command=("npx", "-y", "evil-package"))  # type: ignore[arg-type]
    assert "@earendil-works/pi-coding-agent" in str(excinfo.value)


# --- registry self-registration ------------------------------------------


def test_pi_pool_registers_itself_on_import() -> None:
    """``import mahavishnu.pools.pi_pool`` registers "pi" in the pool registry."""
    types = list_pool_types()
    assert "pi" in types
    # Sanity: alphabetical ordering preserved.
    assert tuple(sorted(types)) == types


# --- start() populates version -------------------------------------------


@pytest.mark.asyncio
async def test_start_populates_version_in_health_check() -> None:
    runner = _FakeRunner()
    runner.set_return(0, "2.1.3")  # --version probe output
    pool, _ = _make_pool(runner=runner)
    await pool.start()
    assert pool._status == PoolStatus.RUNNING
    health = await pool.health_check()
    assert health["worker_health"]["version"] == "2.1.3"
    assert health["worker_health"]["startup_self_test"]["passed"] is True
    assert health["worker_health"]["startup_self_test"]["version"] == "2.1.3"


@pytest.mark.asyncio
async def test_start_probe_failure_does_not_block_start() -> None:
    """A failed --version probe leaves version=None but the pool is still RUNNING."""
    runner = _FakeRunner()
    runner.set_side_effect(PiUnavailable("npx missing"))
    pool, _ = _make_pool(runner=runner)
    # Must not raise — probe is best-effort.
    await pool.start()
    assert pool._status == PoolStatus.RUNNING
    health = await pool.health_check()
    assert health["worker_health"]["version"] is None
    assert health["worker_health"]["startup_self_test"]["passed"] is False


# --- error repr/str redaction --------------------------------------------


def test_error_repr_redacts_secret_fields() -> None:
    from mahavishnu.core.errors import PiProtocolError, PiRPCTimeout, PiUnavailable

    e1 = PiUnavailable(
        "subprocess failed",
        install_hint="npm i npx",
        details={"api_token": "sk-abc1234567890", "runtime": "pi"},
    )
    e2 = PiRPCTimeout(
        "timed out",
        method="complete",
        timeout_seconds=5.0,
        details={"auth_bearer": "bearer abc123", "method": "complete"},
    )
    e3 = PiProtocolError(
        "bad frame",
        frame_excerpt="Content-Length: 100",
        details={"secret_key": "sk-abcdef1234567890"},
    )

    for err in (e1, e2, e3):
        rendered = repr(err) + " " + str(err)
        # The secret-shaped values must NEVER appear in the rendered form.
        assert "sk-abc1234567890" not in rendered
        assert "bearer abc123" not in rendered
        assert "sk-abcdef1234567890" not in rendered
        # The redacted placeholder is present in the details dict (used by to_dict()).
        assert err.details  # non-empty


# --- execute_task happy path ---------------------------------------------


@pytest.mark.asyncio
async def test_execute_task_completed() -> None:
    runner = _FakeRunner()
    runner.set_return(0, "2.1.3")  # start probe
    runner.set_return(0, "Hello from pi")  # actual task
    pool, _ = _make_pool(runner=runner)
    await pool.start()
    result = await pool.execute_task({"prompt": "hello"})
    assert result["status"] == "completed"
    assert result["pool_id"] == pool.pool_id
    assert result["output"] == "Hello from pi"
    assert result["error"] is None
    assert result["duration"] >= 0.0
    assert result["worker_id"].startswith(f"{pool.pool_id}:pi-")


@pytest.mark.asyncio
async def test_execute_task_missing_prompt_returns_failed() -> None:
    runner = _FakeRunner()
    runner.set_return(0, "1.0.0")
    pool, _ = _make_pool(runner=runner)
    await pool.start()
    result = await pool.execute_task({"timeout": 1})
    assert result["status"] == "failed"
    assert "prompt" in (result["error"] or "").lower()


@pytest.mark.asyncio
async def test_execute_task_timeout_marks_status_timeout() -> None:
    runner = _FakeRunner()
    runner.set_return(0, "1.0.0")  # start probe
    runner.set_side_effect(asyncio.TimeoutError())
    pool, _ = _make_pool(runner=runner)
    await pool.start()
    result = await pool.execute_task({"prompt": "slow"})
    assert result["status"] == "timeout"
    assert "timeout" in (result["error"] or "").lower()


@pytest.mark.asyncio
async def test_execute_task_nonzero_returncode_marks_failed() -> None:
    runner = _FakeRunner()
    runner.set_return(0, "1.0.0")  # start probe
    runner.set_return(1, "some output", "boom")
    pool, _ = _make_pool(runner=runner)
    await pool.start()
    result = await pool.execute_task({"prompt": "x"})
    assert result["status"] == "failed"
    assert "boom" in (result["error"] or "") or "1" in (result["error"] or "")


@pytest.mark.asyncio
async def test_execute_task_openai_error_line_marks_failed() -> None:
    """v1.x prints OpenAI errors to stdout; detect them even with rc=0."""
    runner = _FakeRunner()
    runner.set_return(0, "1.0.0")  # start probe
    runner.set_return(
        0,
        "OpenAI API error (401): Incorrect API key provided",
    )
    pool, _ = _make_pool(runner=runner)
    await pool.start()
    result = await pool.execute_task({"prompt": "x"})
    assert result["status"] == "failed"
    assert "OpenAI API error" in (result["error"] or "")


@pytest.mark.asyncio
async def test_execute_task_unavailable_translates_to_failed() -> None:
    runner = _FakeRunner()
    runner.set_return(0, "1.0.0")  # start probe
    runner.set_side_effect(PiUnavailable("npx missing"))
    pool, _ = _make_pool(runner=runner)
    await pool.start()
    result = await pool.execute_task({"prompt": "x"})
    assert result["status"] == "failed"
    assert "unavailable" in (result["error"] or "").lower()


# --- env_allowlist forwarded through subprocess_runner --------------------


@pytest.mark.asyncio
async def test_execute_task_forwards_env_allowlist_keys() -> None:
    """The pool must hand ``env_allowlist`` keys to the subprocess runner."""
    runner = _FakeRunner()
    runner.set_return(0, "1.0.0")  # start probe
    runner.set_return(0, "ok")
    monkeypatch_keys = {
        "OPENAI_API_KEY": "sk-test-key-12345",
        "OPENAI_BASE_URL": "http://127.0.0.1:8471/v1",
    }
    with pytest.MonkeyPatch.context() as mp:
        for k, v in monkeypatch_keys.items():
            mp.setenv(k, v)
        pool, _ = _make_pool(runner=runner)
        await pool.start()
        await pool.execute_task({"prompt": "x"})
    # The second runner call is the execute_task invocation.
    task_call = runner.calls[-1]
    assert task_call["env"]["OPENAI_API_KEY"] == "sk-test-key-12345"
    assert task_call["env"]["OPENAI_BASE_URL"] == "http://127.0.0.1:8471/v1"


# --- argv construction ---------------------------------------------------


@pytest.mark.asyncio
async def test_execute_task_appends_prompt_as_positional_arg() -> None:
    runner = _FakeRunner()
    runner.set_return(0, "1.0.0")  # start probe
    runner.set_return(0, "ok")
    pool, _ = _make_pool(runner=runner)
    await pool.start()
    await pool.execute_task({"prompt": "What is 2+2?"})
    task_call = runner.calls[-1]
    assert task_call["argv"][-1] == "What is 2+2?"


@pytest.mark.asyncio
async def test_execute_task_appends_provider_and_model_flags() -> None:
    runner = _FakeRunner()
    runner.set_return(0, "1.0.0")  # start probe
    runner.set_return(0, "ok")
    pool, _ = _make_pool(runner=runner)
    await pool.start()
    await pool.execute_task(
        {"prompt": "x", "provider": "openai", "model": "gpt-4o-mini"}
    )
    task_call = runner.calls[-1]
    assert "--provider" in task_call["argv"]
    assert "openai" in task_call["argv"]
    assert "--model" in task_call["argv"]
    assert "gpt-4o-mini" in task_call["argv"]


# --- _looks_like_error_output --------------------------------------------


@pytest.mark.parametrize(
    "stdout,expected",
    [
        ("", None),
        ("Some legitimate model output\nwith multiple lines", None),
        ("Error: invalid prompt", "Error: invalid prompt"),
        ("OpenAI API error (401): bad key", "OpenAI API error (401): bad key"),
        ("Anthropic API error: rate limit", "Anthropic API error: rate limit"),
        ("AuthenticationError: missing token", "AuthenticationError: missing token"),
        ("RateLimitError: try later", "RateLimitError: try later"),
        # The first matching line wins.
        (
            "Some preamble\nError: real failure",
            "Error: real failure",
        ),
    ],
)
def test_looks_like_error_output(stdout: str, expected: str | None) -> None:
    assert _looks_like_error_output(stdout) == expected


# ============================================================================
# REQ-BIFROST-014 (defense-in-depth)
# ============================================================================


def test_env_allowlist_excludes_bifrost_prefixes() -> None:
    """REQ-BIFROST-014 defense-in-depth: the PiPool subprocess's
    ``env_allowlist`` (the positive list of env-var prefixes forwarded
    to the subprocess) must not include ``MAHAVISHNU_BIFROST__`` or
    ``ONEIRIC_BIFROST_`` prefixes. The denylist at
    ``mahavishnu.pools.pi_pool._FORBIDDEN_ENV_PREFIXES`` is the first
    line of defense; this test is the second (the allowlist must not
    even permit the prefix).
    """
    pool, _ = _make_pool()
    for prefix in pool._env_allowlist:
        assert not prefix.startswith("MAHAVISHNU_"), (
            f"PiPool env_allowlist contains mahavishnu config prefix: {prefix!r}"
        )
        assert not prefix.startswith("BIFROST_"), (
            f"PiPool env_allowlist contains bifrost config prefix: {prefix!r}"
        )
        assert not prefix.startswith("ONEIRIC_"), (
            f"PiPool env_allowlist contains oneiric config prefix: {prefix!r}"
        )
