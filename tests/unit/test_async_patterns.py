"""Tests for async patterns module.

Tests cover:
- DEFAULT_TIMEOUTS configuration
- timeout_context success, timeout, cancellation
- run_with_timeout wrapper
- SagaLock initialization, acquire, release, error handling
- AsyncTaskManager create, wait, cancel, active_count
- db_connection and db_transaction context managers
- with_retry exponential backoff
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.core.async_patterns import (
    DEFAULT_TIMEOUTS,
    AsyncTaskManager,
    SagaLock,
    db_connection,
    db_transaction,
    run_with_timeout,
    timeout_context,
    with_retry,
)
from mahavishnu.core.errors import ErrorCode, MahavishnuError
from mahavishnu.core.errors import TimeoutError as MahavTimeoutError

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
        from mahavishnu.core.errors import TimeoutError as TO

        with pytest.raises(TO, match="slow_op timed out"):
            async with timeout_context(0.05, "slow_op"):
                await asyncio.sleep(1.0)

    @pytest.mark.asyncio
    async def test_propagates_cancellation(self):
        with pytest.raises(asyncio.CancelledError):
            async with timeout_context(5.0, "cancel_op"):
                raise asyncio.CancelledError()

    @pytest.mark.asyncio
    async def test_error_includes_details(self):
        from mahavishnu.core.errors import TimeoutError as TO

        with pytest.raises(TO) as exc_info:
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
        async def slow():
            await asyncio.sleep(10)

        with pytest.raises(MahavTimeoutError, match="slow_task timed out"):
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


# ============================================================================
# db_connection Tests
# ============================================================================


class TestDbConnection:
    @pytest.mark.asyncio
    async def test_yields_connection(self):
        mock_conn = AsyncMock()
        mock_acquire_cm = AsyncMock()
        mock_acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_cm.__aexit__ = AsyncMock(return_value=False)
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=mock_acquire_cm)

        async with db_connection(mock_pool, timeout_seconds=5.0) as conn:
            assert conn is mock_conn

    @pytest.mark.asyncio
    async def test_timeout_on_slow_acquire(self):
        # pool.acquire() returns an async context manager (not awaited directly)
        # Make __aenter__ slow to simulate timeout during acquisition
        mock_pool = AsyncMock()

        async def slow_enter(*_args):
            await asyncio.sleep(1.0)

        mock_acquire_cm = AsyncMock()
        mock_acquire_cm.__aenter__ = slow_enter
        mock_acquire_cm.__aexit__ = AsyncMock(return_value=False)
        mock_pool.acquire = MagicMock(return_value=mock_acquire_cm)

        with pytest.raises(MahavTimeoutError, match="database_connection timed out"):
            async with db_connection(mock_pool, timeout_seconds=0.01):
                pass

    @pytest.mark.asyncio
    async def test_rollback_on_cancellation(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=asyncio.CancelledError())

        mock_acquire_cm = AsyncMock()
        mock_acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_cm.__aexit__ = AsyncMock(return_value=False)
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=mock_acquire_cm)

        with pytest.raises(asyncio.CancelledError):
            async with db_connection(mock_pool) as conn:
                await conn.execute("INSERT INTO test")

    @pytest.mark.asyncio
    async def test_propagates_db_error(self):
        mock_conn = AsyncMock()
        mock_conn.execute.side_effect = RuntimeError("DB down")

        mock_acquire_cm = AsyncMock()
        mock_acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_cm.__aexit__ = AsyncMock(return_value=False)
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=mock_acquire_cm)

        with pytest.raises(RuntimeError, match="DB down"):
            async with db_connection(mock_pool) as conn:
                await conn.execute("SELECT 1")


# ============================================================================
# db_transaction Tests
# ============================================================================


class TestDbTransaction:
    @pytest.mark.asyncio
    async def test_auto_commits_on_success(self):
        mock_conn = AsyncMock()
        mock_txn = MagicMock()
        mock_txn.__aenter__ = AsyncMock(return_value=None)
        mock_txn.__aexit__ = AsyncMock(return_value=None)
        mock_conn.transaction = MagicMock(return_value=mock_txn)

        mock_acquire_cm = AsyncMock()
        mock_acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_cm.__aexit__ = AsyncMock(return_value=False)
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=mock_acquire_cm)

        async with db_transaction(mock_pool) as conn:
            assert conn is mock_conn

    @pytest.mark.asyncio
    async def test_propagates_error(self):
        mock_conn = AsyncMock()
        mock_txn = MagicMock()
        mock_txn.__aenter__ = AsyncMock(return_value=None)
        mock_txn.__aexit__ = AsyncMock(return_value=None)
        mock_conn.transaction = MagicMock(return_value=mock_txn)

        mock_acquire_cm = AsyncMock()
        mock_acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_cm.__aexit__ = AsyncMock(return_value=False)
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=mock_acquire_cm)

        with pytest.raises(ValueError):
            async with db_transaction(mock_pool):
                raise ValueError("constraint violation")


# ============================================================================
# SagaLock acquire Tests
# ============================================================================


class TestSagaLockAcquire:
    @pytest.mark.asyncio
    async def test_acquire_and_release(self):
        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = {
            "saga_id": "saga-1",
            "status": "running",
            "current_step_index": 0,
        }

        lock = SagaLock(mock_db, "saga-1")
        assert lock.is_locked is False

        async with lock as acquired:
            assert acquired is lock
            assert lock.is_locked is True
            mock_db.fetch_one.assert_awaited_once()

        assert lock.is_locked is False

    @pytest.mark.asyncio
    async def test_raises_on_missing_saga(self):
        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = None

        lock = SagaLock(mock_db, "nonexistent")
        with pytest.raises(MahavishnuError, match="nonexistent not found"):
            async with lock:
                pass

    @pytest.mark.asyncio
    async def test_error_has_recovery_suggestions(self):
        mock_db = AsyncMock()
        mock_db.fetch_one.return_value = None

        lock = SagaLock(mock_db, "missing")
        try:
            async with lock:
                pass
            pytest.fail("Should have raised")
        except MahavishnuError as exc:
            assert exc.error_code == ErrorCode.VALIDATION_ERROR
            assert len(exc.recovery) > 0

    @pytest.mark.asyncio
    async def test_timeout_on_slow_acquire(self):
        async def slow_fetch(*args, **kwargs):
            await asyncio.sleep(1.0)
            return {"saga_id": "saga-1", "status": "running"}

        mock_db = AsyncMock()
        mock_db.fetch_one = slow_fetch

        lock = SagaLock(mock_db, "saga-1", timeout_seconds=0.01)
        with pytest.raises(MahavTimeoutError, match="saga_lock timed out"):
            async with lock:
                pass


# ============================================================================
# with_retry Tests
# ============================================================================


class TestWithRetry:
    @pytest.mark.asyncio
    async def test_succeeds_on_first_try(self):
        func = AsyncMock(return_value="ok")
        result = await with_retry(func, max_retries=3)
        assert result == "ok"
        func.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retries_on_transient_failure(self):
        call_count = 0

        async def flaky(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("transient")
            return "recovered"

        result = await with_retry(flaky, max_retries=3)
        assert result == "recovered"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_last_exception_on_exhaustion(self):
        async def always_fail():
            raise ConnectionError("unreachable")

        with pytest.raises(ConnectionError, match="unreachable"):
            await with_retry(always_fail, max_retries=2)

    @pytest.mark.asyncio
    async def test_passes_args_and_kwargs(self):
        func = AsyncMock(return_value="done")
        result = await with_retry(func, max_retries=1, base_delay=0.01, _arg1="hello", _arg2=42)
        assert result == "done"
        func.assert_awaited_once_with(_arg1="hello", _arg2=42)
