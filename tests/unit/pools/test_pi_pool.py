"""Unit tests for PiPool — subprocess mocked via rpc_factory seam.

Req: REQ-PI-008
"""  # req: REQ-PI-008

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.core.errors import PiProtocolError, PiRPCTimeout
from mahavishnu.core.json_rpc_stdio import JSONRPCStdioClient
from mahavishnu.pools._registry import list_pool_types
from mahavishnu.pools.base import PoolConfig, PoolStatus
from mahavishnu.pools.pi_pool import PiPool


def _make_fake_client(
    *,
    startup_version: str = "1.0.0",
    is_started: bool = True,
    watchdog_failed: bool = False,
    protocol_errors: int = 0,
    request_side_effect: Exception | None = None,
    request_return: object = {"ok": True},
) -> AsyncMock:
    """Build a fake JSONRPCStdioClient that satisfies the PiPool surface."""
    client = AsyncMock(spec=JSONRPCStdioClient)
    client.start = AsyncMock(return_value=startup_version)
    client.stop = AsyncMock(return_value=None)
    client.is_started = is_started
    client.is_stopped = False
    client.startup_version = startup_version
    client.watchdog_failed = watchdog_failed
    client.protocol_errors = protocol_errors
    if request_side_effect is not None:
        client.request = AsyncMock(side_effect=request_side_effect)
    else:
        client.request = AsyncMock(return_value=request_return)
    client.ping = AsyncMock(return_value=12.3)
    client._request_timeout = 30.0
    return client


def _make_pool(
    *,
    config: PoolConfig | None = None,
    client: AsyncMock | None = None,
    rpc_factory=None,
    env_allowlist: tuple[str, ...] | None = None,
) -> tuple[PiPool, AsyncMock]:
    """Build a PiPool with a deterministic fake client."""
    if config is None:
        config = PoolConfig(
            name="test-pi",
            pool_type="pi",
            min_workers=1,
            max_workers=1,  # PiPool is fixed-count; see test_init_rejects_max_workers_greater_than_one
            extra_config={"npx_command": ["npx", "@earendil-works/pi-coding-agent", "--rpc"]},
        )
    if rpc_factory is None:
        fake_client = client or _make_fake_client()
        rpc_factory = MagicMock(return_value=fake_client)
    else:
        fake_client = None
    pool = PiPool(
        config=config,
        rpc_factory=rpc_factory,
        env_allowlist=env_allowlist,
    )
    return pool, fake_client  # type: ignore[return-value]


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
    from mahavishnu.pools.pi_pool import PiPool
    from mahavishnu.pools.base import PoolConfig

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
        PiPoolSettings(npx_command=("/bin/sh", "-c", "evil", "--rpc"))  # type: ignore[arg-type]
    assert "npx, /usr/bin/env, or /usr/local/bin/npx" in str(excinfo.value)


def test_npx_command_requires_rpc_flag() -> None:
    from mahavishnu.core.config import PiPoolSettings
    from mahavishnu.core.errors import ConfigurationError

    with pytest.raises(ConfigurationError) as excinfo:
        PiPoolSettings(npx_command=("npx", "@earendil-works/pi-coding-agent"))  # type: ignore[arg-type]
    assert "--rpc" in str(excinfo.value)


def test_npx_command_requires_pi_package_name() -> None:
    from mahavishnu.core.config import PiPoolSettings
    from mahavishnu.core.errors import ConfigurationError

    with pytest.raises(ConfigurationError) as excinfo:
        PiPoolSettings(npx_command=("npx", "-y", "evil-package", "--rpc"))  # type: ignore[arg-type]
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
    pool, fake = _make_pool(client=_make_fake_client(startup_version="2.1.3"))
    await pool.start()
    assert pool._status == PoolStatus.RUNNING
    health = await pool.health_check()
    assert health["worker_health"]["version"] == "2.1.3"
    assert health["worker_health"]["startup_self_test"]["passed"] is True
    assert health["worker_health"]["startup_self_test"]["version"] == "2.1.3"


# --- error repr/str redaction --------------------------------------------


def test_error_repr_redacts_secret_fields() -> None:
    from mahavishnu.core.errors import PiUnavailable, PiProtocolError, PiRPCTimeout

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
    pool, fake = _make_pool(client=_make_fake_client(request_return={"text": "ok"}))
    await pool.start()
    result = await pool.execute_task({"prompt": "hello"})
    assert result["status"] == "completed"
    assert result["pool_id"] == pool.pool_id
    assert result["output"] == {"text": "ok"}
    assert result["error"] is None
    assert result["duration"] >= 0.0
    assert result["worker_id"].startswith(f"{pool.pool_id}:pi-")


@pytest.mark.asyncio
async def test_execute_task_missing_prompt_returns_failed() -> None:
    pool, _ = _make_pool(client=_make_fake_client())
    await pool.start()
    result = await pool.execute_task({"timeout": 1})
    assert result["status"] == "failed"
    assert "prompt" in (result["error"] or "").lower()


@pytest.mark.asyncio
async def test_execute_task_timeout_marks_status_timeout() -> None:
    pool, fake = _make_pool(
        client=_make_fake_client(request_side_effect=PiRPCTimeout("slow", method="complete")),
    )
    await pool.start()
    result = await pool.execute_task({"prompt": "slow"})
    assert result["status"] == "timeout"


@pytest.mark.asyncio
async def test_execute_task_protocol_error_marks_failed() -> None:
    pool, fake = _make_pool(
        client=_make_fake_client(request_side_effect=PiProtocolError("bad", frame_excerpt="x")),
    )
    await pool.start()
    result = await pool.execute_task({"prompt": "x"})
    assert result["status"] == "failed"
    assert "Pi protocol error" in (result["error"] or "")


# --- PiUnavailable surfaced when subprocess missing ---------------------


@pytest.mark.asyncio
async def test_start_raises_pi_unavailable_when_probe_returns_false() -> None:
    from mahavishnu.core.errors import PiUnavailable

    pool, _ = _make_pool()
    pool._runtime_probe = lambda: (False, "npx not on PATH")
    with pytest.raises(PiUnavailable) as excinfo:
        await pool.start()
    assert excinfo.value.details.get("runtime") == "pi"
    assert excinfo.value.details.get("install_hint")
    assert pool._status == PoolStatus.FAILED


@pytest.mark.asyncio
async def test_start_translates_pi_protocol_error_to_pi_unavailable() -> None:
    from mahavishnu.core.errors import PiUnavailable

    fake = _make_fake_client()
    fake.start = AsyncMock(side_effect=PiProtocolError("spawn failed", frame_excerpt="x"))
    pool, _ = _make_pool(client=fake)
    with pytest.raises(PiUnavailable):
        await pool.start()
    assert pool._status == PoolStatus.FAILED
