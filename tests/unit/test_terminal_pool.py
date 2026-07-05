"""Tests for mahavishnu/terminal/pool.py."""

import asyncio
import contextlib
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from mahavishnu.terminal.pool import ITerm2SessionPool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def pool():
    """Create a test pool with AppleScript mocked at the class level."""
    with patch("mahavishnu.terminal.pool.OSASCRIPT_AVAILABLE", True):
        p = ITerm2SessionPool(max_size=5)
    # Replace the real AppleScript runner so no subprocesses are spawned
    p._run_applescript = AsyncMock(return_value="")
    return p


@pytest.fixture
def pool_small():
    """Pool with max_size=3 for exhaustion tests."""
    with patch("mahavishnu.terminal.pool.OSASCRIPT_AVAILABLE", True):
        p = ITerm2SessionPool(max_size=3)
    p._run_applescript = AsyncMock(return_value="")
    return p


# =========================================================================
# Initialization
# =========================================================================


class TestITerm2SessionPoolInitialization:
    """Test pool initialization and configuration."""

    def test_pool_init_basic(self):
        with patch("mahavishnu.terminal.pool.OSASCRIPT_AVAILABLE", True):
            pool = ITerm2SessionPool(max_size=5)

        assert pool.max_size == 5
        assert pool.idle_timeout == timedelta(seconds=300.0)
        assert pool.health_check_interval == 60.0
        assert len(pool._pool) == 0
        assert pool._health_check_task is None

    def test_pool_init_with_custom_values(self):
        with patch("mahavishnu.terminal.pool.OSASCRIPT_AVAILABLE", True):
            pool = ITerm2SessionPool(
                max_size=10,
                idle_timeout=600.0,
                health_check_interval=120.0,
            )

        assert pool.max_size == 10
        assert pool.idle_timeout == timedelta(seconds=600.0)
        assert pool.health_check_interval == 120.0

    def test_pool_init_without_osascript(self):
        with patch("mahavishnu.terminal.pool.OSASCRIPT_AVAILABLE", False):
            with pytest.raises(ImportError, match="osascript not available"):
                ITerm2SessionPool()

    def test_pool_init_idle_timeout_delta(self):
        with patch("mahavishnu.terminal.pool.OSASCRIPT_AVAILABLE", True):
            pool = ITerm2SessionPool(idle_timeout=180.0)
        assert pool.idle_timeout == timedelta(seconds=180.0)


# =========================================================================
# Session acquisition / release
# =========================================================================


class TestITerm2SessionPoolAcquireRelease:
    """Test session acquisition and release."""

    async def test_acquire_session_new(self, pool):
        session_id = await pool.acquire_session("python -m pytest")

        assert session_id is not None
        assert len(pool._pool) == 1
        assert session_id in pool._pool
        assert pool._pool[session_id]["command"] == "python -m pytest"
        assert pool._pool[session_id]["in_use"] is True
        assert pool._pool[session_id]["created_at"] is not None

    async def test_acquire_session_with_profile(self, pool):
        session_id = await pool.acquire_session("python -m qwen", profile="Python")

        assert session_id is not None
        assert pool._pool[session_id]["profile"] == "Python"

    async def test_acquire_session_reuses_idle_when_full(self, pool_small):
        """Idle sessions are only reused when pool is at capacity."""
        s1 = await pool_small.acquire_session("cmd1")
        await pool_small.acquire_session("cmd2")
        await pool_small.acquire_session("cmd3")

        # Release one — pool is still at max_size
        await pool_small.release_session(s1)

        # Next acquire should reuse the idle session
        s4 = await pool_small.acquire_session("cmd4")
        assert s4 == s1
        assert pool_small._pool[s1]["command"] == "cmd4"

    async def test_acquire_session_exhausted(self, pool_small):
        for i in range(3):
            await pool_small.acquire_session(f"cmd{i}")

        with pytest.raises(RuntimeError, match="Session pool exhausted"):
            await pool_small.acquire_session("cmd4")

    async def test_acquire_session_exhausted_after_release(self, pool_small):
        s1 = await pool_small.acquire_session("cmd1")
        await pool_small.acquire_session("cmd2")
        await pool_small.acquire_session("cmd3")

        await pool_small.release_session(s1)

        s4 = await pool_small.acquire_session("cmd4")
        assert s4 == s1

    async def test_release_unknown_session(self, pool):
        # Should not raise
        await pool.release_session("unknown123")

    async def test_release_session(self, pool):
        session_id = await pool.acquire_session("cmd1")
        assert pool._pool[session_id]["in_use"] is True

        await pool.release_session(session_id)

        assert pool._pool[session_id]["in_use"] is False
        assert pool._pool[session_id]["last_used"] is not None


# =========================================================================
# Commands & output capture
# =========================================================================


class TestITerm2SessionPoolCommands:
    """Test sending commands and capturing output."""

    async def test_send_command_success(self, pool):
        session_id = await pool.acquire_session("cmd1")
        await pool.send_command(session_id, "ls -la")

        pool._run_applescript.assert_called()

    async def test_send_command_unknown_session(self, pool):
        with pytest.raises(KeyError, match="Session unknown123 not found"):
            await pool.send_command("unknown123", "ls")

    async def test_capture_output(self, pool):
        session_id = await pool.acquire_session("cmd1")
        output = await pool.capture_output(session_id)
        assert output == f"[Output capture not available via AppleScript for session {session_id}]"

    async def test_capture_output_unknown_session(self, pool):
        with pytest.raises(KeyError, match="Session unknown123 not found"):
            await pool.capture_output("unknown123")


# =========================================================================
# Session & pool closing
# =========================================================================


class TestITerm2SessionPoolClose:
    """Test session and pool closing."""

    async def test_close_session(self, pool):
        s1 = await pool.acquire_session("cmd1")
        s2 = await pool.acquire_session("cmd2")

        await pool.close_session(s1)

        assert s1 not in pool._pool
        assert s2 in pool._pool

    async def test_close_unknown_session(self, pool):
        # Should not raise
        await pool.close_session("unknown123")

    async def test_close_all(self, pool):
        await pool.acquire_session("cmd1")
        await pool.acquire_session("cmd2")

        await pool.close_all()

        assert len(pool._pool) == 0
        assert pool._health_check_task is None

    async def test_close_all_with_health_check(self, pool):
        # Mock the health check loop so it doesn't actually sleep
        pool._health_check_loop = AsyncMock()
        await pool.start_health_check()
        assert pool._health_check_task is not None

        await pool.close_all()

        assert pool._health_check_task is None

    async def test_close_session_applescript_error(self, pool):
        """Graceful handling when AppleScript fails during close."""
        session_id = await pool.acquire_session("cmd1")

        # Make AppleScript fail AFTER session is created
        pool._run_applescript.side_effect = RuntimeError("Close failed")

        # Should NOT raise — error is caught and logged
        await pool.close_session(session_id)

        assert session_id not in pool._pool


# =========================================================================
# Health checks
# =========================================================================


class TestITerm2SessionPoolHealth:
    """Test health check functionality."""

    async def test_session_healthy(self, pool):
        pool._run_applescript.return_value = "true"
        is_healthy = await pool._is_session_healthy("session1")
        assert is_healthy is True

    async def test_session_unhealthy(self, pool):
        pool._run_applescript.side_effect = RuntimeError("Failed")
        is_healthy = await pool._is_session_healthy("session1")
        assert is_healthy is False

    async def test_start_health_check(self, pool):
        pool._health_check_loop = AsyncMock()
        assert pool._health_check_task is None
        await pool.start_health_check()
        assert pool._health_check_task is not None

    async def test_remove_stale_sessions(self, pool):
        """Idle sessions past timeout are removed; healthy idle sessions remain."""
        s1 = await pool.acquire_session("cmd1")
        s2 = await pool.acquire_session("cmd2")

        await pool.release_session(s1)
        await pool.release_session(s2)

        # Make s1 stale (past idle_timeout of 300s)
        pool._pool[s1]["last_used"] = datetime.now() - timedelta(seconds=400)
        pool._pool[s2]["last_used"] = datetime.now() - timedelta(seconds=200)

        # Health check returns True for remaining sessions
        pool._run_applescript.return_value = "true"

        await pool._remove_stale_sessions()

        assert s1 not in pool._pool  # stale
        assert s2 in pool._pool  # not stale yet


# =========================================================================
# Pool statistics
# =========================================================================


class TestITerm2SessionPoolStats:
    """Test pool statistics."""

    async def test_stats_empty(self, pool):
        stats = pool.stats()
        assert stats["total_sessions"] == 0
        assert stats["in_use"] == 0
        assert stats["idle"] == 0
        assert stats["max_size"] == 5
        assert stats["utilization_percent"] == 0.0
        assert stats["backend"] == "applescript"

    async def test_stats_partial_use(self, pool):
        s1 = await pool.acquire_session("cmd1")
        await pool.acquire_session("cmd2")
        await pool.release_session(s1)

        stats = pool.stats()
        assert stats["total_sessions"] == 2
        assert stats["in_use"] == 1
        assert stats["idle"] == 1
        assert stats["utilization_percent"] == 20.0

    async def test_stats_full_use(self, pool):
        for i in range(5):
            await pool.acquire_session(f"cmd{i}")

        stats = pool.stats()
        assert stats["total_sessions"] == 5
        assert stats["in_use"] == 5
        assert stats["idle"] == 0
        assert stats["utilization_percent"] == 100.0


# =========================================================================
# Global pool singleton
# =========================================================================


class TestGlobalPool:
    """Test global pool singleton."""

    async def test_get_global_pool(self):
        with patch("mahavishnu.terminal.pool.OSASCRIPT_AVAILABLE", True):
            import mahavishnu.terminal.pool as pool_mod

            old = pool_mod._global_pool
            pool_mod._global_pool = None

            try:
                p1 = await pool_mod.get_global_pool()
                assert p1 is not None
                p2 = await pool_mod.get_global_pool()
                assert p1 is p2
            finally:
                # Clean up health check task so it doesn't leak
                if pool_mod._global_pool and pool_mod._global_pool._health_check_task:
                    pool_mod._global_pool._shutdown_event.set()
                    pool_mod._global_pool._health_check_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await pool_mod._global_pool._health_check_task
                pool_mod._global_pool = old

    async def test_close_global_pool(self):
        with patch("mahavishnu.terminal.pool.OSASCRIPT_AVAILABLE", True):
            import mahavishnu.terminal.pool as pool_mod

            old = pool_mod._global_pool
            pool_mod._global_pool = None

            try:
                await pool_mod.get_global_pool()
                await pool_mod.close_global_pool()
                assert pool_mod._global_pool is None
            finally:
                pool_mod._global_pool = old

    async def test_close_global_pool_none(self):
        import mahavishnu.terminal.pool as pool_mod

        old = pool_mod._global_pool
        pool_mod._global_pool = None

        try:
            await pool_mod.close_global_pool()
        finally:
            pool_mod._global_pool = old


# =========================================================================
# AppleScript execution (subprocess layer)
# =========================================================================


class TestAppleScriptExecution:
    """Test AppleScript execution via subprocess."""

    async def test_run_applescript_success(self):
        """Successful osascript invocation returns stdout."""
        with patch("mahavishnu.terminal.pool.OSASCRIPT_AVAILABLE", True):
            pool = ITerm2SessionPool(max_size=1)

        script = 'tell application "iTerm2" to return "success"'
        with patch("asyncio.create_subprocess_exec") as mock_create:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"output", b""))
            mock_create.return_value = mock_proc

            result = await pool._run_applescript(script)

            assert result == "output"
            mock_create.assert_called_once_with(
                "osascript",
                "-e",
                script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

    async def test_run_applescript_failure(self):
        """Non-zero return code raises RuntimeError."""
        with patch("mahavishnu.terminal.pool.OSASCRIPT_AVAILABLE", True):
            pool = ITerm2SessionPool(max_size=1)

        with patch("asyncio.create_subprocess_exec") as mock_create:
            mock_proc = AsyncMock()
            mock_proc.returncode = 1
            mock_proc.communicate = AsyncMock(return_value=(b"", b"Script error"))
            mock_create.return_value = mock_proc

            with pytest.raises(RuntimeError, match="AppleScript failed: Script error"):
                await pool._run_applescript("bad script")

    async def test_run_applescript_exception(self):
        """Subprocess creation failure raises RuntimeError."""
        with patch("mahavishnu.terminal.pool.OSASCRIPT_AVAILABLE", True):
            pool = ITerm2SessionPool(max_size=1)

        with patch("asyncio.create_subprocess_exec", side_effect=Exception("Subprocess failed")):
            with pytest.raises(RuntimeError, match="Failed to run AppleScript"):
                await pool._run_applescript("script")


# =========================================================================
# Integration scenarios
# =========================================================================


class TestIntegrationScenarios:
    """End-to-end scenarios using the fully-mocked pool."""

    async def test_full_pool_lifecycle(self, pool_small):
        sessions = [await pool_small.acquire_session(f"cmd{i}") for i in range(3)]

        stats = pool_small.stats()
        assert stats["total_sessions"] == 3
        assert stats["in_use"] == 3
        assert stats["utilization_percent"] == 100.0

        await pool_small.release_session(sessions[0])
        stats = pool_small.stats()
        assert stats["in_use"] == 2
        assert stats["idle"] == 1

        s4 = await pool_small.acquire_session("cmd4")
        assert s4 == sessions[0]

        await pool_small.close_all()
        assert len(pool_small._pool) == 0

    async def test_concurrent_access(self, pool_small):
        session_ids = ["s1", "s2", "s3"]
        call_count = 0

        async def counting_create(command, columns, rows, profile):
            nonlocal call_count
            call_count += 1
            return session_ids[call_count - 1]

        pool_small._create_session = counting_create

        tasks = [asyncio.create_task(pool_small.acquire_session(f"cmd{i}")) for i in range(3)]
        acquired = await asyncio.gather(*tasks)

        assert len(acquired) == 3
        assert set(acquired) == set(session_ids)
        assert call_count == 3

    async def test_error_resilience_on_close(self, pool):
        session_id = await pool.acquire_session("cmd1")

        # Make AppleScript fail AFTER session is created
        pool._run_applescript.side_effect = RuntimeError("Close failed")

        await pool.close_session(session_id)

        # Session should still be removed despite AppleScript error
        assert session_id not in pool._pool
