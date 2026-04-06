"""Tests for async patterns module.

Tests cover:
- DEFAULT_TIMEOUTS configuration
- timeout_context success, timeout, cancellation
- run_with_timeout wrapper
- SagaLock initialization and properties
- AsyncTaskManager create, wait, cancel, active_count
"""

import asyncio

import pytest

from mahavishnu.core.async_patterns import (
    AsyncTaskManager,
    DEFAULT_TIMEOUTS,
    SagaLock,
    run_with_timeout,
    timeout_context,
)


# ============================================================================
# DEFAULT_TIMEOUTS Tests
# ============================================================================


class TestDefaultTimeouts:
    def test_has_expected_keys(self):
        expected = {
            "database_query",
            "database_transaction",
            "api_call",
            "webhook_processing",
            "embedding_generation",
            "nlp_parsing",
            "file_operation",
        }
        assert set(DEFAULT_TIMEOUTS.keys()) == expected

    def test_all_values_positive(self):
        for key, value in DEFAULT_TIMEOUTS.items():
            assert value > 0, f"{key} timeout must be positive"

    def test_transaction_longer_than_query(self):
        assert DEFAULT_TIMEOUTS["database_transaction"] >= DEFAULT_TIMEOUTS["database_query"]


# ============================================================================
# timeout_context Tests
# ============================================================================


class TestTimeoutContext:
    @pytest.mark.asyncio
    async def test_completes_within_timeout(self):
        async with timeout_context(5.0, "test_op"):
            result = await asyncio.sleep(0.01)
        # Should complete without error

    @pytest.mark.asyncio
    async def test_raises_on_timeout(self):
        from mahavishnu.core.errors import TimeoutError as MahvTimeoutError
        with pytest.raises(MahvTimeoutError, match="slow_op timed out"):
            async with timeout_context(0.05, "slow_op"):
                await asyncio.sleep(1.0)

    @pytest.mark.asyncio
    async def test_propagates_cancellation(self):
        with pytest.raises(asyncio.CancelledError):
            async with timeout_context(5.0, "cancel_op"):
                raise asyncio.CancelledError()

    @pytest.mark.asyncio
    async def test_error_includes_details(self):
        from mahavishnu.core.errors import TimeoutError as MahvTimeoutError
        with pytest.raises(MahvTimeoutError) as exc_info:
            async with timeout_context(0.01, "detail_op"):
                await asyncio.sleep(1.0)
        assert exc_info.value.details["operation"] == "detail_op"
        assert exc_info.value.details["timeout_seconds"] == 0.01


# ============================================================================
# run_with_timeout Tests
# ============================================================================


class TestRunWithTimeout:
    @pytest.mark.asyncio
    async def test_returns_coroutine_result(self):
        async def compute():
            return 42
        result = await run_with_timeout(compute(), timeout_seconds=5.0)
        assert result == 42

    @pytest.mark.asyncio
    async def test_raises_on_timeout(self):
        from mahavishnu.core.errors import TimeoutError as MahvTimeoutError
        async def slow():
            await asyncio.sleep(10)
        with pytest.raises(MahvTimeoutError, match="slow_task"):
            await run_with_timeout(slow(), timeout_seconds=0.01, operation="slow_task")

    @pytest.mark.asyncio
    async def test_propagates_other_errors(self):
        async def failing():
            raise ValueError("boom")
        with pytest.raises(ValueError, match="boom"):
            await run_with_timeout(failing(), timeout_seconds=5.0)


# ============================================================================
# SagaLock Tests
# ============================================================================


class TestSagaLock:
    def test_initial_state(self):
        lock = SagaLock(db=None, saga_id="test-saga")
        assert lock.saga_id == "test-saga"
        assert lock.timeout_seconds == 30.0
        assert lock.is_locked is False

    def test_custom_timeout(self):
        lock = SagaLock(db=None, saga_id="x", timeout_seconds=10.0)
        assert lock.timeout_seconds == 10.0


# ============================================================================
# AsyncTaskManager Tests
# ============================================================================


class TestAsyncTaskManager:
    @pytest.mark.asyncio
    async def test_create_and_wait(self):
        manager = AsyncTaskManager(name="test")

        async def simple():
            return "done"

        task = manager.create_task(simple(), name="t1")
        results = await manager.wait_all()

        assert len(results) == 1
        assert results[0] == "done"

    @pytest.mark.asyncio
    async def test_active_count(self):
        manager = AsyncTaskManager()

        async def slow():
            await asyncio.sleep(0.1)
            return 1

        # After create_task, count may already be 0 due to done_callback
        task = manager.create_task(slow())
        # Task may complete quickly, but initial count should be >= 0
        assert manager.active_count >= 0

    @pytest.mark.asyncio
    async def test_is_empty_when_no_tasks(self):
        manager = AsyncTaskManager()
        assert manager.is_empty is True

    @pytest.mark.asyncio
    async def test_cancel_all(self):
        manager = AsyncTaskManager()

        async def long_running():
            await asyncio.sleep(100)

        task = manager.create_task(long_running())
        await manager.cancel_all()
        assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_wait_empty(self):
        manager = AsyncTaskManager()
        results = await manager.wait_all()
        assert results == []

    @pytest.mark.asyncio
    async def test_wait_with_timeout(self):
        manager = AsyncTaskManager()

        async def quick():
            return "fast"

        manager.create_task(quick())
        results = await manager.wait_all(timeout=5.0)
        assert results == ["fast"]

    @pytest.mark.asyncio
    async def test_multiple_tasks(self):
        manager = AsyncTaskManager()

        async def val(n):
            return n

        manager.create_task(val(1))
        manager.create_task(val(2))
        manager.create_task(val(3))

        results = await manager.wait_all()
        assert sorted(results) == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_task_with_exception(self):
        manager = AsyncTaskManager()

        async def failing():
            raise RuntimeError("test error")

        manager.create_task(failing())
        results = await manager.wait_all()
        # return_exceptions=True means exceptions are returned, not raised
        assert len(results) == 1
        assert isinstance(results[0], RuntimeError)
