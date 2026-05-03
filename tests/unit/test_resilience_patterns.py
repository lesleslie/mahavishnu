"""Tests for core.resilience — CircuitBreaker, RetryPolicy, retry_async, ResilienceMetrics, ResiliencePatterns."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

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
        app.workflow_state_manager.list_workflows = AsyncMock(
            return_value=[
                {
                    "id": "wf1",
                    "task": {"adapter": "prefect", "id": "t1"},
                    "repos": ["/repo1"],
                    "errors": [],
                },
            ]
        )
        app.execute_workflow = AsyncMock(return_value={"status": "ok"})
        app.workflow_state_manager.update = AsyncMock()

        mgr = ErrorRecoveryManager(app)
        await mgr.monitor_and_heal_workflows()

        app.execute_workflow.assert_awaited_once()
        app.workflow_state_manager.update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_heal_workflow_too_many_errors(self):
        app = _mock_app()
        app.workflow_state_manager.list_workflows = AsyncMock(
            return_value=[
                {"id": "wf1", "errors": ["e"] * 6, "task": {"adapter": "prefect"}, "repos": ["/r"]},
            ]
        )

        mgr = ErrorRecoveryManager(app)
        await mgr.monitor_and_heal_workflows()
        app.execute_workflow.assert_not_called()  # skipped

    @pytest.mark.asyncio
    async def test_heal_workflow_missing_task(self):
        app = _mock_app()
        app.workflow_state_manager.list_workflows = AsyncMock(
            return_value=[
                {"id": "wf1", "errors": [], "task": {}, "repos": []},
            ]
        )

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
        app.workflow_state_manager.list_workflows = AsyncMock(
            return_value=[
                {"id": "wf_stuck", "updated_at": stuck_time},
            ]
        )
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
        app.workflow_state_manager.list_workflows = AsyncMock(
            return_value=[
                {"id": "wf_ok", "updated_at": recent_time},
            ]
        )

        mgr = ErrorRecoveryManager(app)
        await mgr._check_stuck_workflows()
        app.workflow_state_manager.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stuck_workflow_bad_timestamp_skipped(self):
        app = _mock_app()
        app.workflow_state_manager.list_workflows = AsyncMock(
            return_value=[
                {"id": "wf_bad", "updated_at": "not-a-date"},
            ]
        )

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


# ---------------------------------------------------------------------------
# Additional coverage tests for uncovered lines
# ---------------------------------------------------------------------------


class TestGetResilienceMetrics:
    """Line 176: get_resilience_metrics() returns the shared singleton."""

    def test_returns_shared_instance(self):
        from mahavishnu.core.resilience import RESILIENCE_METRICS, get_resilience_metrics

        assert get_resilience_metrics() is RESILIENCE_METRICS


class TestCircuitBreakerRecordFailureHalfOpen:
    """Lines 216-221: record_failure in HALF_OPEN sets failure_count >= threshold
    and reopens the circuit, then returns early."""

    def test_half_open_failure_sets_count_to_threshold(self):
        cb = CircuitBreaker(threshold=3, timeout=0)
        # Open the circuit with 3 failures
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        # Transition to half-open (timeout=0 means immediate)
        cb.allow_request()
        assert cb.state == CircuitState.HALF_OPEN
        cb.failure_count = 0  # allow_request resets to 0
        # Now record a failure while half-open
        cb.record_failure()
        # After half-open failure, count should be >= threshold (line 216)
        assert cb.failure_count >= cb.threshold
        assert cb.state == CircuitState.OPEN


class TestClassifyError:
    """Lines 456, 472, 512, 529: classify_error for TRANSIENT, NETWORK,
    PERMISSION, VALIDATION categories."""

    @pytest.mark.asyncio
    async def test_classify_transient(self):
        app = _mock_app()
        mgr = ErrorRecoveryManager(app)
        result = await mgr.classify_error(Exception("rate limit exceeded"))
        assert result == ErrorCategory.TRANSIENT

    @pytest.mark.asyncio
    async def test_classify_transient_throttle(self):
        app = _mock_app()
        mgr = ErrorRecoveryManager(app)
        result = await mgr.classify_error(Exception("request throttled temporarily"))
        assert result == ErrorCategory.TRANSIENT

    @pytest.mark.asyncio
    async def test_classify_network(self):
        app = _mock_app()
        mgr = ErrorRecoveryManager(app)
        result = await mgr.classify_error(Exception("connection refused"))
        assert result == ErrorCategory.NETWORK

    @pytest.mark.asyncio
    async def test_classify_permission(self):
        app = _mock_app()
        mgr = ErrorRecoveryManager(app)
        result = await mgr.classify_error(Exception("permission denied for user"))
        assert result == ErrorCategory.PERMISSION

    @pytest.mark.asyncio
    async def test_classify_validation(self):
        app = _mock_app()
        mgr = ErrorRecoveryManager(app)
        result = await mgr.classify_error(Exception("invalid input schema"))
        assert result == ErrorCategory.VALIDATION


class TestAttemptRecoveryRetryStrategy:
    """Line 623: _attempt_recovery with RETRY strategy calls _retry_operation."""

    @pytest.mark.asyncio
    async def test_retry_strategy_invokes_retry(self):
        app = _mock_app()
        mgr = ErrorRecoveryManager(app)
        # TRANSIENT uses RETRY strategy by default
        call_count = 0

        async def succeed_on_second():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("temporary failure")
            return "ok"

        result = await mgr.execute_with_resilience(succeed_on_second)
        # Should succeed after retry
        assert result["success"] is True
        assert result["result"] == "ok"
        assert result["recovered"] is True


class TestAttemptRecoveryDefaultFallback:
    """Line 614: _attempt_recovery when no matching category exists creates a
    default RecoveryAction with RETRY strategy.
    Line 636: ROLLBACK (or any unmatched strategy) falls through to default retry."""

    @pytest.mark.asyncio
    async def test_unknown_category_uses_default_retry(self):
        app = _mock_app()
        mgr = ErrorRecoveryManager(app)
        # Remove all recovery actions so nothing matches
        mgr.recovery_actions.clear()

        call_count = 0

        async def succeed_eventually():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("fail")
            return "recovered"

        result = await mgr.execute_with_resilience(succeed_eventually)
        assert result["success"] is True
        assert result["result"] == "recovered"

    @pytest.mark.asyncio
    async def test_rollback_strategy_falls_through_to_retry(self):
        """ROLLBACK strategy is not explicitly handled, so it falls through
        to the default retry path (line 636)."""
        app = _mock_app()
        mgr = ErrorRecoveryManager(app)
        mgr.recovery_actions["TRANSIENT"] = RecoveryAction(
            strategy=RecoveryStrategy.ROLLBACK,
            category=ErrorCategory.TRANSIENT,
            max_attempts=2,
        )

        call_count = 0

        async def succeed_eventually():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("temporary")
            return "ok"

        result = await mgr.execute_with_resilience(succeed_eventually)
        assert result["success"] is True
        assert result["result"] == "ok"


class TestAttemptRecoverySkipStrategy:
    """Line 631: _attempt_recovery with SKIP strategy calls _skip_and_continue."""

    @pytest.mark.asyncio
    async def test_skip_strategy(self):
        app = _mock_app()
        mgr = ErrorRecoveryManager(app)
        # PERMISSION uses SKIP strategy by default

        async def always_fail():
            raise PermissionError("access denied")

        result = await mgr.execute_with_resilience(always_fail)
        assert result["success"] is False
        assert result["skipped"] is True
        assert result["recovered"] is True


class TestSkipAndContinue:
    """Lines 739-746: _skip_and_continue logs a warning and returns skipped result."""

    @pytest.mark.asyncio
    async def test_skip_and_continue_returns_skipped(self):
        app = _mock_app()
        mgr = ErrorRecoveryManager(app)
        error = RuntimeError("skip me")

        result = await mgr._skip_and_continue(error, workflow_id="wf1", repo_path="/repo")
        assert result["success"] is False
        assert result["error"] == "skip me"
        assert result["attempts"] == 1
        assert result["recovered"] is True
        assert result["skipped"] is True


class TestRetryOperationExhausted:
    """Lines 651-697: _retry_operation full retry loop with backoff and logging,
    including the exhausted path."""

    @pytest.mark.asyncio
    async def test_retry_operation_all_attempts_fail(self):
        app = _mock_app()
        mgr = ErrorRecoveryManager(app)

        async def always_fail():
            raise ConnectionError("always fails")

        result = await mgr._retry_operation(
            always_fail,
            (),
            {},
            max_attempts=3,
            backoff_factor=1.0,
            workflow_id="wf1",
            repo_path="/repo",
        )
        assert result["success"] is False
        assert result["recovered"] is False
        assert result["attempts"] == 3
        assert "always fails" in result["error"]

    @pytest.mark.asyncio
    async def test_retry_operation_succeeds_on_third(self):
        app = _mock_app()
        mgr = ErrorRecoveryManager(app)
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("flaky")
            return "success"

        result = await mgr._retry_operation(
            flaky,
            (),
            {},
            max_attempts=3,
            backoff_factor=1.0,
            workflow_id="wf1",
            repo_path="/repo",
        )
        assert result["success"] is True
        assert result["result"] == "success"
        assert result["attempts"] == 3
        assert result["recovered"] is True


class TestHealWorkflowFailure:
    """Lines 933-938: _heal_workflow when execute_with_resilience returns
    unsuccessful, and when an exception is raised during healing."""

    @pytest.mark.asyncio
    async def test_heal_workflow_execution_fails(self):
        app = _mock_app()
        app.workflow_state_manager.list_workflows = AsyncMock(
            return_value=[
                {
                    "id": "wf1",
                    "task": {"adapter": "prefect", "id": "t1"},
                    "repos": ["/repo1"],
                    "errors": [],
                },
            ]
        )
        # execute_workflow raises — so execute_with_resilience recovery fails
        app.execute_workflow = AsyncMock(side_effect=RuntimeError("unrecoverable"))

        mgr = ErrorRecoveryManager(app)
        await mgr.monitor_and_heal_workflows()
        # Workflow was not healed — no update to running
        app.workflow_state_manager.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_heal_workflow_exception_during_heal(self):
        app = _mock_app()
        app.workflow_state_manager.list_workflows = AsyncMock(
            return_value=[
                {
                    "id": "wf2",
                    "task": {"adapter": "prefect", "id": "t2"},
                    "repos": ["/repo1"],
                    "errors": [],
                },
            ]
        )
        # execute_workflow raises an exception that propagates past recovery
        app.execute_workflow = AsyncMock(side_effect=MemoryError("oom during heal"))
        app.workflow_state_manager.update = AsyncMock(side_effect=RuntimeError("db down"))

        mgr = ErrorRecoveryManager(app)
        # Should not raise — monitor_and_heal_workflows catches exceptions
        await mgr.monitor_and_heal_workflows()


class TestGetRecoveryMetrics:
    """Line 980: get_recovery_metrics returns the metrics dict."""

    @pytest.mark.asyncio
    async def test_get_recovery_metrics(self):
        app = _mock_app()
        mgr = ErrorRecoveryManager(app)
        metrics = await mgr.get_recovery_metrics()
        assert "total_recovery_attempts" in metrics
        assert "successful_recoveries" in metrics
        assert "failed_recoveries" in metrics
        assert metrics["total_recovery_attempts"] == 0

    @pytest.mark.asyncio
    async def test_get_recovery_metrics_with_history(self):
        app = _mock_app()
        mgr = ErrorRecoveryManager(app)
        mgr.recovery_history.append({"success": True})
        mgr.recovery_history.append({"success": False})
        mgr.recovery_history.append({"success": True})
        metrics = await mgr.get_recovery_metrics()
        assert metrics["total_recovery_attempts"] == 3
        assert metrics["successful_recoveries"] == 2
        assert metrics["failed_recoveries"] == 1


class TestStartMonitoringService:
    """Lines 1038, 1040, 1042-1048: monitoring_loop branches — normal timeout
    continuation and error-in-loop with shutdown/timeout handling."""

    @pytest.mark.asyncio
    async def test_monitoring_loop_shutdown_during_normal_wait(self):
        """Line 1038: shutdown event set during the 5-minute wait causes break."""
        app = _mock_app()
        patterns = ResiliencePatterns(app)

        # Make monitor_and_heal_workflows return quickly
        patterns.recovery_manager.monitor_and_heal_workflows = AsyncMock()

        # Start monitoring, then signal shutdown immediately
        await patterns.start_monitoring_service()
        # Give the loop a moment to start, then stop
        await asyncio.sleep(0.05)
        await patterns.stop_monitoring_service()
        # Allow the loop to notice shutdown
        await asyncio.sleep(0.1)
        assert patterns._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_monitoring_loop_error_then_shutdown(self):
        """Lines 1042-1048: exception in loop body triggers error logging and
        wait, then shutdown signal breaks out."""
        app = _mock_app()
        patterns = ResiliencePatterns(app)

        # Make monitor_and_heal_workflows raise
        patterns.recovery_manager.monitor_and_heal_workflows = AsyncMock(
            side_effect=RuntimeError("monitoring error")
        )

        await patterns.start_monitoring_service()
        await asyncio.sleep(0.05)
        await patterns.stop_monitoring_service()
        await asyncio.sleep(0.1)
        assert patterns._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_monitoring_loop_error_then_timeout_continues(self):
        """Lines 1047-1048: exception in loop body, then TimeoutError on the
        60s wait means the loop continues."""
        app = _mock_app()
        patterns = ResiliencePatterns(app)

        # Make monitor_and_heal_workflows raise on first call, then set shutdown
        call_count = 0

        async def failing_then_stop():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient monitoring error")
            patterns._shutdown_event.set()

        patterns.recovery_manager.monitor_and_heal_workflows = AsyncMock(
            side_effect=failing_then_stop
        )

        # Patch asyncio.wait_for to use very short timeouts so the loop
        # proceeds quickly through the error-and-continue path.
        with patch("mahavishnu.core.resilience.asyncio.wait_for") as mock_wait:
            # First call: normal 300s timeout in the try block -> TimeoutError
            # Second call: 60s timeout in the except block -> TimeoutError
            # Third call: normal 300s timeout -> event is set, returns
            mock_wait.side_effect = [
                TimeoutError(),
                TimeoutError(),
                None,  # shutdown event set, returns immediately
            ]

            await patterns.start_monitoring_service()
            await asyncio.sleep(0.2)
            assert patterns._shutdown_event.is_set()
            assert call_count >= 2
