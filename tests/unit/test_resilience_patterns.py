"""Tests for core.resilience — CircuitBreaker, RetryPolicy, retry_async, ResilienceMetrics, ResiliencePatterns."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, UTC
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from mahavishnu.core.resilience import (
    CircuitBreaker,
    CircuitBreakerPolicy,
    CircuitState,
    DependencyProfile,
    ErrorCategory,
    ErrorRecoveryManager,
    RecoveryAction,
    RecoveryStrategy,
    ResilienceMetrics,
    ResiliencePatterns,
    RetryExhaustedError,
    RetryPolicy,
    circuit_breaker,
    retry_async,
)


# ---------------------------------------------------------------------------
# RetryPolicy
# ---------------------------------------------------------------------------


class TestRetryPolicy:
    def test_default_values(self):
        p = RetryPolicy()
        assert p.max_attempts == 4
        assert p.initial_delay_seconds == 1.0
        assert p.max_delay_seconds == 30.0
        assert p.backoff_factor == 2.0
        assert p.jitter_ratio == 0.0

    def test_delay_first_attempt(self):
        p = RetryPolicy()
        assert p.delay_for_attempt(1) == 1.0

    def test_delay_exponential_growth(self):
        p = RetryPolicy(initial_delay_seconds=2.0, backoff_factor=3.0)
        assert p.delay_for_attempt(1) == 2.0
        assert p.delay_for_attempt(2) == 6.0
        assert p.delay_for_attempt(3) == 18.0

    def test_delay_capped_at_max(self):
        p = RetryPolicy(initial_delay_seconds=10.0, backoff_factor=10.0, max_delay_seconds=50.0)
        assert p.delay_for_attempt(1) == 10.0
        assert p.delay_for_attempt(2) == 50.0  # capped
        assert p.delay_for_attempt(3) == 50.0

    def test_delay_with_zero_jitter(self):
        p = RetryPolicy(jitter_ratio=0.0, initial_delay_seconds=10.0)
        assert p.delay_for_attempt(1) == 10.0

    def test_delay_with_jitter_stays_non_negative(self):
        p = RetryPolicy(jitter_ratio=1.0, initial_delay_seconds=1.0)
        for _ in range(100):
            assert p.delay_for_attempt(1) >= 0.0

    def test_delay_for_attempt_zero_clamped(self):
        p = RetryPolicy()
        # attempt 0 → max(0, ...) = 0 * factor^0 = 1.0
        assert p.delay_for_attempt(0) == 1.0

    def test_custom_retryable_exceptions(self):
        p = RetryPolicy(retryable_exceptions=(ValueError, TypeError))
        assert p.retryable_exceptions == (ValueError, TypeError)


# ---------------------------------------------------------------------------
# CircuitBreakerPolicy & DependencyProfile
# ---------------------------------------------------------------------------


class TestCircuitBreakerPolicy:
    def test_defaults(self):
        cbp = CircuitBreakerPolicy()
        assert cbp.failure_threshold == 5
        assert cbp.recovery_timeout_seconds == 60.0
        assert cbp.reset_timeout_seconds == 60.0


class TestDependencyProfile:
    def test_defaults(self):
        dp = DependencyProfile(name="cache")
        assert dp.required is True
        assert isinstance(dp.retry_policy, RetryPolicy)
        assert isinstance(dp.circuit_breaker_policy, CircuitBreakerPolicy)

    def test_custom_policies(self):
        rp = RetryPolicy(max_attempts=10)
        cbp = CircuitBreakerPolicy(failure_threshold=3)
        dp = DependencyProfile(name="db", retry_policy=rp, circuit_breaker_policy=cbp)
        assert dp.retry_policy.max_attempts == 10
        assert dp.circuit_breaker_policy.failure_threshold == 3


# ---------------------------------------------------------------------------
# RetryExhaustedError
# ---------------------------------------------------------------------------


class TestRetryExhaustedError:
    def test_with_exception(self):
        exc = RuntimeError("boom")
        err = RetryExhaustedError(exc, 5)
        assert err.last_exception is exc
        assert err.attempts == 5
        assert "boom" in str(err)

    def test_with_none_exception(self):
        err = RetryExhaustedError(None, 3)
        assert err.last_exception is None
        assert err.attempts == 3
        assert "Retry exhausted" in str(err)


# ---------------------------------------------------------------------------
# CircuitBreaker — state transitions
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def test_initial_state_closed(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_record_failure_increments_count(self):
        cb = CircuitBreaker(threshold=5)
        for _ in range(3):
            cb.record_failure()
        assert cb.failure_count == 3
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(threshold=3)
        for _ in range(2):
            cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_record_success_resets_count(self):
        cb = CircuitBreaker(threshold=5)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    def test_record_success_in_half_open_transitions_to_closed(self):
        cb = CircuitBreaker(threshold=1, timeout=0)
        cb.record_failure()  # opens
        assert cb.state == CircuitState.OPEN
        cb.allow_request()  # transitions to half-open
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_record_failure_in_half_open_reopens(self):
        cb = CircuitBreaker(threshold=1)
        cb.record_failure()  # opens
        cb.allow_request()  # half-open
        cb.record_failure()  # should reopen
        assert cb.state == CircuitState.OPEN

    def test_last_failure_time_set(self):
        cb = CircuitBreaker()
        cb.record_failure()
        assert cb.last_failure_time is not None
        assert isinstance(cb.last_failure_time, datetime)


# ---------------------------------------------------------------------------
# CircuitBreaker — allow_request
# ---------------------------------------------------------------------------


class TestCircuitBreakerAllowRequest:
    def test_closed_allows(self):
        cb = CircuitBreaker()
        assert cb.allow_request() is True

    def test_open_blocks(self):
        cb = CircuitBreaker(threshold=1, timeout=60)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_open_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker(threshold=1, timeout=0)
        cb.record_failure()  # opens
        assert cb.allow_request() is True  # timeout=0, immediate half-open
        assert cb.state == CircuitState.HALF_OPEN

    def test_open_no_last_failure_time_blocks(self):
        cb = CircuitBreaker(threshold=1, timeout=0)
        cb.state = CircuitState.OPEN
        cb.last_failure_time = None
        assert cb.allow_request() is False

    def test_half_open_allows(self):
        cb = CircuitBreaker(threshold=1, timeout=0)
        cb.record_failure()
        cb.allow_request()  # half-open
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request() is True

    def test_zero_timeout_always_allows(self):
        cb = CircuitBreaker(threshold=1, timeout=0)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is True  # timeout=0


# ---------------------------------------------------------------------------
# CircuitBreaker — async call
# ---------------------------------------------------------------------------


class TestCircuitBreakerCall:
    @pytest.mark.asyncio
    async def test_call_success(self):
        cb = CircuitBreaker(threshold=3)
        async def ok():
            return "result"
        result = await cb.call(ok)
        assert result == "result"
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_call_records_failure(self):
        cb = CircuitBreaker(threshold=3)
        async def fail():
            raise RuntimeError("err")
        with pytest.raises(RuntimeError):
            await cb.call(fail)
        assert cb.failure_count == 1

    @pytest.mark.asyncio
    async def test_call_blocked_when_open(self):
        cb = CircuitBreaker(threshold=1, timeout=60)
        cb.record_failure()
        async def ok():
            return "result"
        with pytest.raises(Exception, match="open"):
            await cb.call(ok)

    @pytest.mark.asyncio
    async def test_call_works_with_sync_function(self):
        cb = CircuitBreaker(threshold=3)
        def sync_ok():
            return "sync_result"
        result = await cb.call(sync_ok)
        assert result == "sync_result"
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_call_sync_failure_records(self):
        cb = CircuitBreaker(threshold=3)
        def sync_fail():
            raise ValueError("v")
        with pytest.raises(ValueError):
            await cb.call(sync_fail)
        assert cb.failure_count == 1


# ---------------------------------------------------------------------------
# CircuitBreaker — sync call_sync
# ---------------------------------------------------------------------------


class TestCircuitBreakerCallSync:
    def test_call_sync_success(self):
        cb = CircuitBreaker(threshold=3)
        assert cb.call_sync(lambda: "ok") == "ok"
        assert cb.failure_count == 0

    def test_call_sync_records_failure(self):
        cb = CircuitBreaker(threshold=3)
        with pytest.raises(RuntimeError):
            cb.call_sync(lambda: (_ for _ in ()).throw(RuntimeError("err")))
        assert cb.failure_count == 1

    def test_call_sync_blocked_when_open(self):
        cb = CircuitBreaker(threshold=1, timeout=60)
        cb.record_failure()
        with pytest.raises(Exception, match="open"):
            cb.call_sync(lambda: "nope")


# ---------------------------------------------------------------------------
# circuit_breaker decorator
# ---------------------------------------------------------------------------


class TestCircuitBreakerDecorator:
    @pytest.mark.asyncio
    async def test_async_function_decorator(self):
        @circuit_breaker(threshold=3)
        async def flaky(n):
            if n < 0:
                raise RuntimeError("neg")
            return n

        result = await flaky(5)
        assert result == 5

    @pytest.mark.asyncio
    async def test_async_function_opens(self):
        call_count = 0

        @circuit_breaker(threshold=2)
        async def fail():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("fail")

        for _ in range(2):
            with pytest.raises(RuntimeError):
                await fail()
        # Now it should be open
        with pytest.raises(Exception, match="open"):
            await fail()

    def test_sync_function_decorator(self):
        @circuit_breaker(threshold=3)
        def ok():
            return 42

        assert ok() == 42

    def test_sync_function_opens(self):
        call_count = 0

        @circuit_breaker(threshold=2)
        def fail():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("fail")

        for _ in range(2):
            with pytest.raises(RuntimeError):
                fail()
        with pytest.raises(Exception, match="open"):
            fail()


# ---------------------------------------------------------------------------
# ResilienceMetrics
# ---------------------------------------------------------------------------


class TestResilienceMetrics:
    def test_record_retry_attempt_no_prometheus(self):
        metrics = ResilienceMetrics()
        metrics._enabled = False  # simulate no prometheus
        metrics.record_retry_attempt("dep", "op", "success")  # no error

    def test_record_retry_amplification_no_prometheus(self):
        metrics = ResilienceMetrics()
        metrics._enabled = False
        metrics.record_retry_amplification("dep", 3)  # no error

    def test_record_circuit_transition_no_prometheus(self):
        metrics = ResilienceMetrics()
        metrics._enabled = False
        metrics.record_circuit_transition("dep", "closed", "open")  # no error


# ---------------------------------------------------------------------------
# retry_async
# ---------------------------------------------------------------------------


class TestRetryAsync:
    @pytest.mark.asyncio
    async def test_success_first_try(self):
        async def ok():
            return "done"

        result, attempts = await retry_async(ok)
        assert result == "done"
        assert attempts == 1

    @pytest.mark.asyncio
    async def test_success_after_retries(self):
        count = 0

        async def flaky():
            nonlocal count
            count += 1
            if count < 3:
                raise ConnectionError("temp")
            return "ok"

        result, attempts = await retry_async(flaky)
        assert result == "ok"
        assert attempts == 3

    @pytest.mark.asyncio
    async def test_exhausted_raises(self):
        async def always_fail():
            raise ConnectionError("nope")

        with pytest.raises(RetryExhaustedError) as exc_info:
            await retry_async(always_fail, policy=RetryPolicy(max_attempts=2))
        assert exc_info.value.attempts == 2
        assert exc_info.value.last_exception is not None

    @pytest.mark.asyncio
    async def test_custom_retry_policy(self):
        policy = RetryPolicy(max_attempts=5, initial_delay_seconds=0.01)
        count = 0

        async def flaky():
            nonlocal count
            count += 1
            if count < 4:
                raise ConnectionError("temp")

        result, attempts = await retry_async(flaky, policy=policy)
        assert attempts == 4

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self):
        async def cancel():
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await retry_async(cancel)

    @pytest.mark.asyncio
    async def test_non_retryable_exception_not_retried(self):
        async def fail():
            raise ValueError("not retryable")

        policy = RetryPolicy(max_attempts=3, retryable_exceptions=(ConnectionError,))

        # retry_async lets non-retryable exceptions propagate directly
        with pytest.raises(ValueError, match="not retryable"):
            await retry_async(fail, policy=policy)

    @pytest.mark.asyncio
    async def test_args_and_kwargs_passed(self):
        async def add(a, b, c=0):
            return a + b + c

        result, attempts = await retry_async(add, 1, 2, c=3)
        assert result == 6
        assert attempts == 1


# ---------------------------------------------------------------------------
# ErrorRecoveryManager — additional coverage
# ---------------------------------------------------------------------------


def _mock_app():
    """Create a mock app suitable for ErrorRecoveryManager tests."""
    app = Mock()
    app.observability = Mock()
    app.opensearch_integration = AsyncMock()
    app.workflow_state_manager = AsyncMock()
    return app


class TestErrorRecoveryManagerFallback:
    @pytest.mark.asyncio
    async def test_fallback_strategy_executes_fallback(self):
        app = _mock_app()
        mgr = ErrorRecoveryManager(app)

        async def always_fail():
            raise MemoryError("oom")

        result = await mgr.execute_with_resilience(always_fail)
        # RESOURCE error → FALLBACK strategy → _resource_fallback
        assert result["success"] is True  # fallback returns success
        assert result["recovered"] is True
        assert result["result"]["status"] == "fallback_executed"

    @pytest.mark.asyncio
    async def test_fallback_failure_returns_false(self):
        app = _mock_app()
        mgr = ErrorRecoveryManager(app)

        # Override the fallback to fail
        async def bad_fallback(*args, **kwargs):
            raise MemoryError("still oom")

        mgr.recovery_actions["RESOURCE"] = RecoveryAction(
            strategy=RecoveryStrategy.FALLBACK,
            category=ErrorCategory.RESOURCE,
            fallback_function=bad_fallback,
        )

        async def always_fail():
            raise MemoryError("oom")

        result = await mgr.execute_with_resilience(always_fail)
        assert result["success"] is False
        assert result["recovered"] is False


class TestErrorRecoveryManagerNotify:
    @pytest.mark.asyncio
    async def test_notify_strategy(self):
        app = _mock_app()
        mgr = ErrorRecoveryManager(app)

        # Override a category to use NOTIFY strategy
        mgr.recovery_actions["PERMANENT"] = RecoveryAction(
            strategy=RecoveryStrategy.NOTIFY,
            category=ErrorCategory.PERMANENT,
            notify_on_failure=True,
        )

        async def permanent_fail():
            raise RuntimeError("hard fail")

        result = await mgr.execute_with_resilience(permanent_fail)
        assert result["success"] is False
        assert result["recovered"] is False


class TestErrorRecoveryManagerHeal:
    @pytest.mark.asyncio
    async def test_heal_workflow_success(self):
        app = _mock_app()
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[
            {"id": "wf1", "task": {"adapter": "prefect", "id": "t1"}, "repos": ["/repo1"],
            "errors": []},
        ])
        app.execute_workflow = AsyncMock(return_value={"status": "ok"})
        app.workflow_state_manager.update = AsyncMock()

        mgr = ErrorRecoveryManager(app)
        await mgr.monitor_and_heal_workflows()

        app.execute_workflow.assert_awaited_once()
        app.workflow_state_manager.update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_heal_workflow_too_many_errors(self):
        app = _mock_app()
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[
            {"id": "wf1", "errors": ["e"] * 6, "task": {"adapter": "prefect"}, "repos": ["/r"]},
        ])

        mgr = ErrorRecoveryManager(app)
        await mgr.monitor_and_heal_workflows()
        app.execute_workflow.assert_not_called()  # skipped

    @pytest.mark.asyncio
    async def test_heal_workflow_missing_task(self):
        app = _mock_app()
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[
            {"id": "wf1", "errors": [], "task": {}, "repos": []},
        ])

        mgr = ErrorRecoveryManager(app)
        await mgr.monitor_and_heal_workflows()
        app.execute_workflow.assert_not_called()

    @pytest.mark.asyncio
    async def test_monitor_and_heal_graceful_error(self):
        app = _mock_app()
        app.workflow_state_manager.list_workflows = AsyncMock(side_effect=RuntimeError("db down"))

        mgr = ErrorRecoveryManager(app)
        await mgr.monitor_and_heal_workflows()  # no exception


class TestErrorRecoveryManagerStuckWorkflows:
    @pytest.mark.asyncio
    async def test_stuck_workflow_marked_failed(self):
        app = _mock_app()
        stuck_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[
            {"id": "wf_stuck", "updated_at": stuck_time},
        ])
        app.workflow_state_manager.update = AsyncMock()

        mgr = ErrorRecoveryManager(app)
        await mgr._check_stuck_workflows()

        app.workflow_state_manager.update.assert_awaited_once()
        call_kwargs = app.workflow_state_manager.update.call_args[1]
        assert call_kwargs["status"] == "failed"
        assert "timed_out" in call_kwargs

    @pytest.mark.asyncio
    async def test_recent_workflow_not_marked(self):
        app = _mock_app()
        recent_time = datetime.now(UTC).isoformat()
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[
            {"id": "wf_ok", "updated_at": recent_time},
        ])

        mgr = ErrorRecoveryManager(app)
        await mgr._check_stuck_workflows()
        app.workflow_state_manager.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stuck_workflow_bad_timestamp_skipped(self):
        app = _mock_app()
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[
            {"id": "wf_bad", "updated_at": "not-a-date"},
        ])

        mgr = ErrorRecoveryManager(app)
        await mgr._check_stuck_workflows()  # no exception

    @pytest.mark.asyncio
    async def test_stuck_check_graceful_error(self):
        app = _mock_app()
        app.workflow_state_manager.list_workflows = AsyncMock(side_effect=RuntimeError("fail"))

        mgr = ErrorRecoveryManager(app)
        await mgr._check_stuck_workflows()  # no exception


# ---------------------------------------------------------------------------
# ResiliencePatterns
# ---------------------------------------------------------------------------


class TestResiliencePatterns:
    @pytest.mark.asyncio
    async def test_resilient_workflow_execution(self):
        app = _mock_app()
        app.execute_workflow_parallel = AsyncMock(return_value={"status": "ok"})
        patterns = ResiliencePatterns(app)

        result = await patterns.resilient_workflow_execution(
            task={"id": "t1"}, adapter_name="prefect", repos=["/repo1"]
        )
        app.execute_workflow_parallel.assert_awaited_once()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_resilient_repo_operation(self):
        app = _mock_app()
        patterns = ResiliencePatterns(app)

        async def op(x):
            return x * 2

        result = await patterns.resilient_repo_operation(op, "/repo", 5)
        assert result["success"] is True
        assert result["result"] == 10

    @pytest.mark.asyncio
    async def test_start_monitoring_service(self):
        app = _mock_app()
        patterns = ResiliencePatterns(app)
        await patterns.start_monitoring_service()
        assert patterns._shutdown_event.is_set() is False

    @pytest.mark.asyncio
    async def test_stop_monitoring_service(self):
        app = _mock_app()
        patterns = ResiliencePatterns(app)
        await patterns.stop_monitoring_service()
        assert patterns._shutdown_event.is_set() is True
