"""Unit tests for ProcessPoolTaskExecutor.

Tests cover:
- ProcessPoolTaskExecutor initialization and defaults
- start() / shutdown() lifecycle
- submit() with mocked executor (no real process spawning)
- get_stats() at various lifecycle stages
- __del__ cleanup
- Module-level singleton functions (get_process_pool, init_process_pool, shutdown_process_pool)
- Error cases (not started, already shut down)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.process_pool_executor import (
    ProcessPoolTaskExecutor,
    _process_pool_instance,
    get_process_pool,
    init_process_pool,
    shutdown_process_pool,
)


# ============================================================================
# ProcessPoolTaskExecutor Initialization
# ============================================================================


class TestProcessPoolTaskExecutorInit:
    """Test ProcessPoolTaskExecutor.__init__."""

    def test_default_max_workers(self):
        """Default max_workers should be cpu_count - 1 (minimum 1)."""
        import multiprocessing

        expected = max(1, multiprocessing.cpu_count() - 1)
        executor = ProcessPoolTaskExecutor()
        assert executor._max_workers == expected

    def test_custom_max_workers(self):
        """Custom max_workers should be stored as-is."""
        executor = ProcessPoolTaskExecutor(max_workers=4)
        assert executor._max_workers == 4

    def test_max_workers_one(self):
        """Explicit max_workers=1 should work."""
        executor = ProcessPoolTaskExecutor(max_workers=1)
        assert executor._max_workers == 1

    def test_custom_max_tasks_per_child(self):
        """Custom max_tasks_per_child should be stored."""
        executor = ProcessPoolTaskExecutor(max_workers=2, max_tasks_per_child=50)
        assert executor._max_tasks_per_child == 50

    def test_default_max_tasks_per_child_is_none(self):
        """Default max_tasks_per_child should be None."""
        executor = ProcessPoolTaskExecutor()
        assert executor._max_tasks_per_child is None

    def test_initial_state_is_not_started(self):
        """New executor should have no internal executor and not be shut down."""
        executor = ProcessPoolTaskExecutor()
        assert executor._executor is None
        assert executor._loop is None
        assert executor._shutdown is False

    def test_init_logs_parameters(self, caplog):
        """Init should log max_workers and max_tasks_per_child."""
        with caplog.at_level("INFO"):
            ProcessPoolTaskExecutor(max_workers=2, max_tasks_per_child=10)
        assert "max_workers=2" in caplog.text
        assert "max_tasks_per_child=10" in caplog.text


# ============================================================================
# start()
# ============================================================================


class TestStart:
    """Test ProcessPoolTaskExecutor.start."""

    def test_start_creates_executor(self):
        """start() should create a ProcessPoolExecutor instance."""
        executor = ProcessPoolTaskExecutor(max_workers=2)
        executor.start()
        try:
            assert executor._executor is not None
            assert not executor._shutdown
        finally:
            executor._executor.shutdown(wait=False)

    def test_start_captures_event_loop(self):
        """start() should capture the current event loop."""
        executor = ProcessPoolTaskExecutor(max_workers=2)
        executor.start()
        try:
            assert executor._loop is not None
        finally:
            executor._executor.shutdown(wait=False)

    def test_start_resets_shutdown_flag(self):
        """start() should reset the _shutdown flag to False."""
        executor = ProcessPoolTaskExecutor(max_workers=2)
        executor._shutdown = True
        executor.start()
        try:
            assert executor._shutdown is False
        finally:
            executor._executor.shutdown(wait=False)

    def test_start_when_already_started_logs_warning(self, caplog):
        """start() on an already-started executor should log a warning."""
        executor = ProcessPoolTaskExecutor(max_workers=2)
        executor.start()
        try:
            with caplog.at_level("WARNING"):
                executor.start()
            assert "already started" in caplog.text
        finally:
            executor._executor.shutdown(wait=False)

    def test_start_logs_info(self, caplog):
        """start() should log an info message."""
        executor = ProcessPoolTaskExecutor(max_workers=2)
        with caplog.at_level("INFO"):
            executor.start()
        try:
            assert "started" in caplog.text
        finally:
            executor._executor.shutdown(wait=False)


# ============================================================================
# shutdown()
# ============================================================================


class TestShutdown:
    """Test ProcessPoolTaskExecutor.shutdown."""

    def test_shutdown_cleans_up(self):
        """shutdown() should set executor to None and flag shutdown."""
        executor = ProcessPoolTaskExecutor(max_workers=2)
        executor.start()
        asyncio.get_event_loop().run_until_complete(executor.shutdown(wait=False))
        assert executor._executor is None
        assert executor._shutdown is True

    def test_shutdown_when_not_started_is_noop(self):
        """shutdown() when not started should not raise."""
        executor = ProcessPoolTaskExecutor()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(executor.shutdown())
        finally:
            loop.close()

    def test_shutdown_when_already_shutdown_is_noop(self):
        """Double shutdown should be a no-op."""
        executor = ProcessPoolTaskExecutor(max_workers=2)
        executor.start()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(executor.shutdown(wait=False))
            # Second call should be safe
            loop.run_until_complete(executor.shutdown(wait=False))
        finally:
            loop.close()
        assert executor._executor is None

    def test_shutdown_logs_messages(self, caplog):
        """shutdown() should log shutting down and complete messages."""
        executor = ProcessPoolTaskExecutor(max_workers=2)
        executor.start()
        with caplog.at_level("INFO"):
            asyncio.get_event_loop().run_until_complete(executor.shutdown(wait=False))
        assert "shutting down" in caplog.text.lower()

    def test_shutdown_with_wait_true(self):
        """shutdown(wait=True) should pass wait flag to ProcessPoolExecutor."""
        mock_exec = MagicMock()
        executor = ProcessPoolTaskExecutor(max_workers=2)
        executor._executor = mock_exec
        executor._shutdown = False

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(executor.shutdown(wait=True))
        finally:
            loop.close()

        mock_exec.shutdown.assert_called_once_with(wait=True)


# ============================================================================
# submit()
# ============================================================================


class TestSubmit:
    """Test ProcessPoolTaskExecutor.submit."""

    def test_submit_when_not_started_raises(self):
        """submit() before start() should raise RuntimeError."""
        executor = ProcessPoolTaskExecutor()
        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(RuntimeError, match="not started"):
                loop.run_until_complete(executor.submit(lambda: 42))
        finally:
            loop.close()

    def test_submit_when_shutdown_raises(self):
        """submit() after shutdown() should raise RuntimeError."""
        executor = ProcessPoolTaskExecutor(max_workers=2)
        executor.start()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(executor.shutdown(wait=False))
            with pytest.raises(RuntimeError, match="not started"):
                loop.run_until_complete(executor.submit(lambda: 42))
        finally:
            loop.close()

    def test_submit_runs_function_in_executor(self):
        """submit() should run the function via loop.run_in_executor."""
        executor = ProcessPoolTaskExecutor(max_workers=2)
        executor.start()

        # Patch the loop's run_in_executor to return a known future
        loop = asyncio.new_event_loop()

        async def _test():
            executor._loop = loop
            mock_executor = MagicMock()
            executor._executor = mock_executor
            executor._shutdown = False

            future = loop.create_future()
            future.set_result(42)
            with patch.object(loop, "run_in_executor", return_value=future) as mock_run:
                result = await executor.submit(lambda x: x * 2, 21)
                assert result == 42
                mock_run.assert_called_once()

        try:
            loop.run_until_complete(_test())
        finally:
            loop.close()

    def test_submit_passes_args_and_kwargs(self):
        """submit() should pass *args and **kwargs to the function."""
        executor = ProcessPoolTaskExecutor(max_workers=2)
        executor.start()

        loop = asyncio.new_event_loop()

        async def _test():
            executor._loop = loop
            executor._executor = MagicMock()
            executor._shutdown = False

            # Capture what partial was created with
            captured_partial = None

            future = loop.create_future()
            future.set_result("result")

            original_partial = __import__("functools").partial

            def capture_partial(func, *args, **kwargs):
                nonlocal captured_partial
                p = original_partial(func, *args, **kwargs)
                captured_partial = p
                return p

            with (
                patch("mahavishnu.core.process_pool_executor.partial", side_effect=capture_partial),
                patch.object(loop, "run_in_executor", return_value=future),
            ):
                await executor.submit(lambda a, b, c=0: a + b + c, 1, 2, c=3)

            assert captured_partial is not None
            assert captured_partial.func(10, 20, c=30) == 60

        try:
            loop.run_until_complete(_test())
        finally:
            loop.close()

    def test_submit_reraises_exception_from_function(self):
        """submit() should re-raise exceptions from the submitted function."""
        executor = ProcessPoolTaskExecutor(max_workers=2)
        executor.start()

        loop = asyncio.new_event_loop()

        async def _test():
            executor._loop = loop
            executor._executor = MagicMock()
            executor._shutdown = False

            future = loop.create_future()
            future.set_exception(ValueError("bad value"))

            with (
                patch.object(loop, "run_in_executor", return_value=future),
                pytest.raises(ValueError, match="bad value"),
            ):
                await executor.submit(lambda: None)

        try:
            loop.run_until_complete(_test())
        finally:
            loop.close()

    def test_submit_logs_error_on_failure(self, caplog):
        """submit() should log an error when the function raises."""
        executor = ProcessPoolTaskExecutor(max_workers=2)
        executor.start()

        loop = asyncio.new_event_loop()

        async def _test():
            executor._loop = loop
            executor._executor = MagicMock()
            executor._shutdown = False

            def failing_func():
                raise TypeError("wrong type")

            future = loop.create_future()
            future.set_exception(TypeError("wrong type"))

            with caplog.at_level("ERROR"):
                with (
                    patch.object(loop, "run_in_executor", return_value=future),
                    pytest.raises(TypeError),
                ):
                    await executor.submit(failing_func)

            assert "failed" in caplog.text.lower()
            assert "failing_func" in caplog.text

        try:
            loop.run_until_complete(_test())
        finally:
            loop.close()

    def test_submit_uses_stored_loop(self):
        """submit() should prefer the stored loop over get_event_loop."""
        executor = ProcessPoolTaskExecutor(max_workers=2)
        executor.start()

        loop = asyncio.new_event_loop()

        async def _test():
            executor._loop = loop
            executor._executor = MagicMock()
            executor._shutdown = False

            future = loop.create_future()
            future.set_result("ok")

            with patch.object(loop, "run_in_executor", return_value=future) as mock_run:
                await executor.submit(lambda: "ok")
                mock_run.assert_called_once()

        try:
            loop.run_until_complete(_test())
        finally:
            loop.close()


# ============================================================================
# get_stats()
# ============================================================================


class TestGetStats:
    """Test ProcessPoolTaskExecutor.get_stats."""

    def test_stats_before_start(self):
        """Stats before start should show running=False, shutdown=False."""
        executor = ProcessPoolTaskExecutor(max_workers=4)
        stats = executor.get_stats()
        assert stats["max_workers"] == 4
        assert stats["running"] is False
        assert stats["shutdown"] is False

    def test_stats_after_start(self):
        """Stats after start should show running=True."""
        executor = ProcessPoolTaskExecutor(max_workers=3)
        executor.start()
        try:
            stats = executor.get_stats()
            assert stats["max_workers"] == 3
            assert stats["running"] is True
            assert stats["shutdown"] is False
        finally:
            executor._executor.shutdown(wait=False)

    def test_stats_after_shutdown(self):
        """Stats after shutdown should show running=False, shutdown=True."""
        executor = ProcessPoolTaskExecutor(max_workers=2)
        executor.start()
        asyncio.get_event_loop().run_until_complete(executor.shutdown(wait=False))
        stats = executor.get_stats()
        assert stats["running"] is False
        assert stats["shutdown"] is True


# ============================================================================
# __del__
# ============================================================================


class TestDestructor:
    """Test ProcessPoolTaskExecutor.__del__."""

    def test_del_cleans_up_executor(self):
        """__del__ should call shutdown(wait=False) on the executor."""
        mock_exec = MagicMock()
        executor = ProcessPoolTaskExecutor(max_workers=2)
        executor._executor = mock_exec

        executor.__del__()

        mock_exec.shutdown.assert_called_once_with(wait=False)

    def test_del_when_no_executor_is_noop(self):
        """__del__ when executor is None should not raise."""
        executor = ProcessPoolTaskExecutor()
        executor.__del__()  # Should not raise

    def test_del_ignores_shutdown_errors(self):
        """__del__ should silently ignore errors during cleanup."""
        mock_exec = MagicMock()
        mock_exec.shutdown.side_effect = RuntimeError("already shut down")
        executor = ProcessPoolTaskExecutor(max_workers=2)
        executor._executor = mock_exec

        executor.__del__()  # Should not raise


# ============================================================================
# Module-level singleton functions
# ============================================================================


class TestGetProcessPool:
    """Test get_process_pool module-level function."""

    def test_raises_when_not_initialized(self):
        """get_process_pool should raise RuntimeError when not initialized."""
        import mahavishnu.core.process_pool_executor as mod

        # Save and clear global state
        original = mod._process_pool_instance
        mod._process_pool_instance = None
        try:
            with pytest.raises(RuntimeError, match="not initialized"):
                get_process_pool()
        finally:
            mod._process_pool_instance = original

    def test_returns_instance_when_initialized(self):
        """get_process_pool should return the global instance."""
        import mahavishnu.core.process_pool_executor as mod

        mock_instance = MagicMock(spec=ProcessPoolTaskExecutor)
        original = mod._process_pool_instance
        mod._process_pool_instance = mock_instance
        try:
            result = get_process_pool()
            assert result is mock_instance
        finally:
            mod._process_pool_instance = original


class TestInitProcessPool:
    """Test init_process_pool module-level function."""

    def test_creates_and_starts_instance(self):
        """init_process_pool should create and start a ProcessPoolTaskExecutor."""
        import mahavishnu.core.process_pool_executor as mod

        original = mod._process_pool_instance
        mod._process_pool_instance = None
        try:
            loop = asyncio.new_event_loop()
            instance = loop.run_until_complete(init_process_pool(max_workers=2))
            try:
                assert isinstance(instance, ProcessPoolTaskExecutor)
                assert mod._process_pool_instance is instance
                assert instance._executor is not None
            finally:
                loop.run_until_complete(shutdown_process_pool())
                loop.close()
        finally:
            mod._process_pool_instance = original

    def test_overwrites_existing_instance(self):
        """init_process_pool should replace any existing global instance."""
        import mahavishnu.core.process_pool_executor as mod

        original = mod._process_pool_instance
        mod._process_pool_instance = None
        try:
            loop = asyncio.new_event_loop()
            first = loop.run_until_complete(init_process_pool(max_workers=2))
            try:
                assert mod._process_pool_instance is first
                # Note: in production code, calling init_process_pool again
                # without shutting down the first is a leak. Here we test
                # that the replacement happens.
                second = loop.run_until_complete(init_process_pool(max_workers=3))
                assert mod._process_pool_instance is second
                assert second is not first
            finally:
                loop.run_until_complete(shutdown_process_pool())
                loop.close()
        finally:
            mod._process_pool_instance = original


class TestShutdownProcessPool:
    """Test shutdown_process_pool module-level function."""

    def test_shutdown_clears_global_instance(self):
        """shutdown_process_pool should set global instance to None."""
        import mahavishnu.core.process_pool_executor as mod

        original = mod._process_pool_instance
        mod._process_pool_instance = None
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(init_process_pool(max_workers=2))
            assert mod._process_pool_instance is not None

            loop.run_until_complete(shutdown_process_pool())
            assert mod._process_pool_instance is None
            loop.close()
        finally:
            mod._process_pool_instance = original

    def test_shutdown_when_none_is_noop(self):
        """shutdown_process_pool when no instance exists should not raise."""
        import mahavishnu.core.process_pool_executor as mod

        original = mod._process_pool_instance
        mod._process_pool_instance = None
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(shutdown_process_pool())
            loop.close()
        finally:
            mod._process_pool_instance = original

    def test_shutdown_logs_completion(self, caplog):
        """shutdown_process_pool should log shutdown completion."""
        import mahavishnu.core.process_pool_executor as mod

        original = mod._process_pool_instance
        mod._process_pool_instance = None
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(init_process_pool(max_workers=2))
            with caplog.at_level("INFO"):
                loop.run_until_complete(shutdown_process_pool())
            loop.close()
            assert "shut down" in caplog.text.lower()
        finally:
            mod._process_pool_instance = original


# ============================================================================
# Integration-style lifecycle test
# ============================================================================


class TestLifecycle:
    """Test complete lifecycle patterns."""

    def test_full_lifecycle(self):
        """Test init -> start -> submit -> shutdown cycle with mocks."""
        executor = ProcessPoolTaskExecutor(max_workers=2)
        executor.start()

        loop = asyncio.new_event_loop()

        async def _test():
            executor._loop = loop
            executor._executor = MagicMock()
            executor._shutdown = False

            future = loop.create_future()
            future.set_result(99)

            with patch.object(loop, "run_in_executor", return_value=future):
                result = await executor.submit(lambda: 99)
                assert result == 99

            await executor.shutdown(wait=False)
            stats = executor.get_stats()
            assert stats["running"] is False
            assert stats["shutdown"] is True

        try:
            loop.run_until_complete(_test())
        finally:
            loop.close()

    def test_stats_reflect_lifecycle(self):
        """Stats should accurately reflect the executor state at each stage."""
        executor = ProcessPoolTaskExecutor(max_workers=2)

        # Before start
        assert executor.get_stats()["running"] is False

        executor.start()
        try:
            # After start
            assert executor.get_stats()["running"] is True

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(executor.shutdown(wait=False))
            finally:
                loop.close()

            # After shutdown
            assert executor.get_stats()["running"] is False
            assert executor.get_stats()["shutdown"] is True
        except Exception:
            # Clean up if test fails mid-way
            if executor._executor is not None:
                executor._executor.shutdown(wait=False)
            raise
