"""Tests for mahavishnu/core/resilience.py targeting >=80% line+branch coverage."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core import resilience as resilience_mod
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
    get_resilience_metrics,
    retry_async,
)
from mahavishnu.core.workflow_state import WorkflowStatus


# ---------------------------------------------------------------------------
# Shared metrics fix-up
#
# The module uses prometheus_client's default global registry. The first
# test that calls _initialize() registers metrics, and any later test that
# tries to register the same metric names again raises ValueError. We avoid
# this by replacing _initialize on the SHARED singleton with a no-op that
# just sets the metric attributes, and patching Prometheus calls on the
# attributes directly in each test.
# ---------------------------------------------------------------------------


class _FakeLabels:
    def __init__(self) -> None:
        self.inc = MagicMock()
        self.set = MagicMock()


class _FakeCounter:
    def __init__(self) -> None:
        self.labels = MagicMock(return_value=_FakeLabels())


class _FakeGauge:
    def __init__(self) -> None:
        self.labels = MagicMock(return_value=_FakeLabels())


def _patch_singleton_metrics() -> None:
    """Reset shared singleton metrics to fake ones so tests can run repeatedly."""
    shared = resilience_mod.RESILIENCE_METRICS
    shared._enabled = True
    shared._metrics_initialized = True
    shared._retry_attempts_total = _FakeCounter()
    shared._retry_amplification_gauge = _FakeGauge()
    shared._circuit_transitions_total = _FakeCounter()


def _disable_singleton_metrics() -> None:
    shared = resilience_mod.RESILIENCE_METRICS
    shared._enabled = False
    shared._metrics_initialized = False


@pytest.fixture(autouse=True)
def _reset_shared_metrics() -> None:
    _patch_singleton_metrics()
    yield
    _disable_singleton_metrics()


# ---------------------------------------------------------------------------
# Enum / dataclass / exception tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCircuitStateEnum:
    def test_values(self) -> None:
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"


@pytest.mark.unit
class TestRetryPolicy:
    def test_delay_for_attempt_no_jitter(self) -> None:
        p = RetryPolicy(initial_delay_seconds=1.0, backoff_factor=2.0, max_delay_seconds=100.0)
        assert p.delay_for_attempt(1) == 1.0
        assert p.delay_for_attempt(2) == 2.0
        assert p.delay_for_attempt(3) == 4.0

    def test_delay_for_attempt_caps_at_max(self) -> None:
        p = RetryPolicy(initial_delay_seconds=1.0, backoff_factor=10.0, max_delay_seconds=5.0)
        assert p.delay_for_attempt(2) == 5.0
        assert p.delay_for_attempt(5) == 5.0

    def test_delay_for_attempt_attempt_zero(self) -> None:
        p = RetryPolicy(initial_delay_seconds=2.0, backoff_factor=2.0)
        # attempt 0 => max(0-1, 0) = 0 in exponent; delay = 2.0
        assert p.delay_for_attempt(0) == 2.0

    def test_delay_for_attempt_with_jitter(self) -> None:
        p = RetryPolicy(
            initial_delay_seconds=10.0,
            backoff_factor=2.0,
            max_delay_seconds=100.0,
            jitter_ratio=0.5,
        )
        delay = p.delay_for_attempt(2)
        # With jitter, delay may differ from base 20.0 but must be >= 0
        assert delay >= 0.0

    def test_delay_with_jitter_can_clamp_to_zero(self) -> None:
        # Very small base delay with strong negative jitter; should clamp to 0.0
        p = RetryPolicy(
            initial_delay_seconds=0.001,
            backoff_factor=1.0,
            max_delay_seconds=10.0,
            jitter_ratio=1.0,
        )
        # Run many times - at least one trial could clamp
        for _ in range(50):
            d = p.delay_for_attempt(1)
            assert d >= 0.0


@pytest.mark.unit
class TestCircuitBreakerPolicy:
    def test_defaults(self) -> None:
        p = CircuitBreakerPolicy()
        assert p.failure_threshold == 5
        assert p.recovery_timeout_seconds == 60.0
        assert p.reset_timeout_seconds == 60.0


@pytest.mark.unit
class TestDependencyProfile:
    def test_defaults_use_factories(self) -> None:
        a = DependencyProfile(name="x")
        b = DependencyProfile(name="y")
        # default_factory must give independent objects
        assert a.retry_policy is not b.retry_policy
        assert a.circuit_breaker_policy is not b.circuit_breaker_policy
        assert a.required is True


@pytest.mark.unit
class TestRetryExhaustedError:
    def test_with_exception(self) -> None:
        exc = ValueError("boom")
        e = RetryExhaustedError(exc, attempts=3)
        assert e.last_exception is exc
        assert e.attempts == 3
        assert "boom" in str(e)

    def test_without_exception(self) -> None:
        e = RetryExhaustedError(None, attempts=1)
        assert e.last_exception is None
        assert e.attempts == 1
        assert str(e) == "Retry exhausted"


# ---------------------------------------------------------------------------
# ResilienceMetrics
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResilienceMetrics:
    def test_get_resilience_metrics_singleton(self) -> None:
        a = get_resilience_metrics()
        b = get_resilience_metrics()
        assert a is b

    def test_initialize_sets_metrics(self) -> None:
        m = ResilienceMetrics()
        # Pre-set metrics; idempotency check is the same as the next test
        m._retry_attempts_total = _FakeCounter()
        m._retry_amplification_gauge = _FakeGauge()
        m._circuit_transitions_total = _FakeCounter()
        m._metrics_initialized = True
        # If _initialize() is called again, it short-circuits
        m._initialize()
        assert m._metrics_initialized is True
        assert m._retry_attempts_total is not None
        assert m._retry_amplification_gauge is not None
        assert m._circuit_transitions_total is not None

    def test_initialize_idempotent(self) -> None:
        m = ResilienceMetrics()
        # Avoid the prometheus global registry by faking the metrics
        m._retry_attempts_total = _FakeCounter()
        m._retry_amplification_gauge = _FakeGauge()
        m._circuit_transitions_total = _FakeCounter()
        first = m._retry_attempts_total
        m._metrics_initialized = True
        m._initialize()
        # Idempotent: same object retained
        assert m._retry_attempts_total is first
        assert m._retry_amplification_gauge is not None
        assert m._circuit_transitions_total is not None

    def test_record_retry_attempt_when_disabled(self) -> None:
        m = ResilienceMetrics()
        m._enabled = False
        m.record_retry_attempt("dep", "op", "success")
        assert m._metrics_initialized is False

    def test_record_retry_amplification_when_disabled(self) -> None:
        m = ResilienceMetrics()
        m._enabled = False
        m.record_retry_amplification("dep", attempts=2)
        assert m._metrics_initialized is False

    def test_record_circuit_transition_when_disabled(self) -> None:
        m = ResilienceMetrics()
        m._enabled = False
        m.record_circuit_transition("dep", "closed", "open")
        assert m._metrics_initialized is False

    def test_record_retry_attempt_success(self) -> None:
        m = ResilienceMetrics()
        m._enabled = True
        # Inject fake metrics to avoid prometheus global registry clashes
        m._retry_attempts_total = _FakeCounter()
        m._retry_amplification_gauge = _FakeGauge()
        m._circuit_transitions_total = _FakeCounter()
        m._metrics_initialized = True
        m.record_retry_attempt("dep", "op", "success", attempts=1)
        counter = m._retry_attempts_total
        counter.labels.assert_called_once_with(dependency="dep", operation="op", outcome="success")
        counter.labels.return_value.inc.assert_called_once_with(1)

    def test_record_retry_attempt_with_amount(self) -> None:
        m = ResilienceMetrics()
        m._enabled = True
        m._retry_attempts_total = _FakeCounter()
        m._retry_amplification_gauge = _FakeGauge()
        m._circuit_transitions_total = _FakeCounter()
        m._metrics_initialized = True
        m.record_retry_attempt("dep", "op", "failure", attempts=3)
        counter = m._retry_attempts_total
        counter.labels.return_value.inc.assert_called_once_with(3)

    def test_record_retry_amplification_with_metric(self) -> None:
        m = ResilienceMetrics()
        m._enabled = True
        m._retry_attempts_total = _FakeCounter()
        m._retry_amplification_gauge = _FakeGauge()
        m._circuit_transitions_total = _FakeCounter()
        m._metrics_initialized = True
        m.record_retry_amplification("dep", attempts=4, successes=2)
        gauge = m._retry_amplification_gauge
        # ratio = 4 / max(2,1) = 4/2 = 2
        gauge.labels.assert_called_once_with(dependency="dep")
        gauge.labels.return_value.set.assert_called_once_with(2.0)

    def test_record_retry_amplification_min_successes(self) -> None:
        m = ResilienceMetrics()
        m._enabled = True
        m._retry_attempts_total = _FakeCounter()
        m._retry_amplification_gauge = _FakeGauge()
        m._circuit_transitions_total = _FakeCounter()
        m._metrics_initialized = True
        m.record_retry_amplification("dep", attempts=4, successes=0)
        gauge = m._retry_amplification_gauge
        # ratio = 4 / max(0,1) = 4.0
        gauge.labels.return_value.set.assert_called_once_with(4.0)

    def test_record_circuit_transition_with_metric(self) -> None:
        m = ResilienceMetrics()
        m._enabled = True
        m._retry_attempts_total = _FakeCounter()
        m._retry_amplification_gauge = _FakeGauge()
        m._circuit_transitions_total = _FakeCounter()
        m._metrics_initialized = True
        m.record_circuit_transition("dep", "closed", "open")
        counter = m._circuit_transitions_total
        counter.labels.assert_called_once_with(
            dependency="dep", from_state="closed", to_state="open"
        )
        counter.labels.return_value.inc.assert_called_once_with()


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCircuitBreaker:
    def test_initial_state(self) -> None:
        cb = CircuitBreaker(threshold=3, timeout=10, dependency_name="dep")
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.last_failure_time is None

    def test_record_failure_increments_and_sets_time(self) -> None:
        cb = CircuitBreaker(threshold=3, timeout=10, dependency_name="dep")
        cb.record_failure()
        assert cb.failure_count == 1
        assert cb.last_failure_time is not None
        assert cb.state == CircuitState.CLOSED

    def test_record_failure_opens_at_threshold(self) -> None:
        cb = CircuitBreaker(threshold=2, timeout=10, dependency_name="dep")
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_record_failure_in_half_open_reopens(self) -> None:
        cb = CircuitBreaker(threshold=3, timeout=10, dependency_name="dep")
        cb.state = CircuitState.HALF_OPEN
        cb.failure_count = 0
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 3

    def test_record_success_resets_count(self) -> None:
        cb = CircuitBreaker(threshold=3, timeout=10, dependency_name="dep")
        cb.failure_count = 2
        cb.record_success()
        assert cb.failure_count == 0

    def test_record_success_in_half_open_closes(self) -> None:
        cb = CircuitBreaker(threshold=3, timeout=10, dependency_name="dep")
        cb.state = CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_record_success_in_closed_noop(self) -> None:
        cb = CircuitBreaker(threshold=3, timeout=10, dependency_name="dep")
        cb.state = CircuitState.CLOSED
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_transition_no_op_when_same_state(self) -> None:
        cb = CircuitBreaker(threshold=3, timeout=10, dependency_name="dep")
        with patch.object(cb.metrics, "record_circuit_transition") as rec:
            cb._transition(CircuitState.CLOSED)
            rec.assert_not_called()

    def test_allow_request_closed(self) -> None:
        cb = CircuitBreaker()
        assert cb.allow_request() is True

    def test_allow_request_open_without_last_failure(self) -> None:
        cb = CircuitBreaker()
        cb.state = CircuitState.OPEN
        cb.last_failure_time = None
        assert cb.allow_request() is False

    def test_allow_request_open_within_timeout(self) -> None:
        cb = CircuitBreaker(timeout=60)
        cb.state = CircuitState.OPEN
        cb.last_failure_time = cb._now_mock = None
        from datetime import datetime

        cb.last_failure_time = datetime.now()
        assert cb.allow_request() is False

    def test_allow_request_open_after_timeout_transitions_to_half_open(self) -> None:
        from datetime import datetime, timedelta

        cb = CircuitBreaker(timeout=0)
        cb.state = CircuitState.OPEN
        cb.last_failure_time = datetime.now() - timedelta(seconds=10)
        result = cb.allow_request()
        assert result is True
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.failure_count == 0

    def test_allow_request_half_open(self) -> None:
        cb = CircuitBreaker()
        cb.state = CircuitState.HALF_OPEN
        assert cb.allow_request() is True

    async def test_call_async_success(self) -> None:
        cb = CircuitBreaker(threshold=2, timeout=10, dependency_name="dep")

        async def coro():
            return "ok"

        result = await cb.call(coro)
        assert result == "ok"
        assert cb.failure_count == 0

    async def test_call_sync_function_through_async_call(self) -> None:
        cb = CircuitBreaker(threshold=2, timeout=10, dependency_name="dep")

        def sync():
            return 42

        result = await cb.call(sync)
        assert result == 42

    async def test_call_async_failure(self) -> None:
        cb = CircuitBreaker(threshold=2, timeout=10, dependency_name="dep")

        async def coro():
            raise RuntimeError("bad")

        with pytest.raises(RuntimeError):
            await cb.call(coro)
        assert cb.failure_count == 1

    async def test_call_denied_when_open(self) -> None:
        cb = CircuitBreaker(threshold=1, timeout=10, dependency_name="dep")
        cb.state = CircuitState.OPEN

        async def coro():
            return "ok"

        with pytest.raises(Exception, match="Circuit breaker is open"):
            await cb.call(coro)

    def test_call_sync_success(self) -> None:
        cb = CircuitBreaker(threshold=2, timeout=10, dependency_name="dep")
        result = cb.call_sync(lambda: 99)
        assert result == 99

    def test_call_sync_failure(self) -> None:
        cb = CircuitBreaker(threshold=2, timeout=10, dependency_name="dep")
        with pytest.raises(RuntimeError):
            cb.call_sync(lambda: (_ for _ in ()).throw(RuntimeError("bad")))
        assert cb.failure_count == 1

    def test_call_sync_denied_when_open(self) -> None:
        cb = CircuitBreaker(threshold=1, timeout=10, dependency_name="dep")
        cb.state = CircuitState.OPEN
        with pytest.raises(Exception, match="Circuit breaker is open"):
            cb.call_sync(lambda: 1)

    def test_call_sync_records_success(self) -> None:
        cb = CircuitBreaker(threshold=5, timeout=10, dependency_name="dep")
        cb.call_sync(lambda: 1)
        assert cb.failure_count == 0


# ---------------------------------------------------------------------------
# circuit_breaker decorator
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCircuitBreakerDecorator:
    async def test_decorator_async(self) -> None:
        @circuit_breaker(threshold=2, timeout=10)
        async def fn(x):
            return x * 2

        result = await fn(3)
        assert result == 6

    def test_decorator_sync(self) -> None:
        @circuit_breaker(threshold=2, timeout=10)
        def fn(x):
            return x + 1

        assert fn(4) == 5


# ---------------------------------------------------------------------------
# retry_async
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRetryAsync:
    async def test_success_first_try(self) -> None:
        async def op():
            return "ok"

        result, attempts = await retry_async(op, operation="op", dependency="dep")
        assert result == "ok"
        assert attempts == 1

    async def test_success_after_failures(self) -> None:
        call_count = 0

        async def op():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "done"

        policy = RetryPolicy(max_attempts=5, initial_delay_seconds=0.0, max_delay_seconds=0.0)
        result, attempts = await retry_async(
            op, policy=policy, operation="op", dependency="dep"
        )
        assert result == "done"
        assert attempts == 3

    async def test_exhausted_raises(self) -> None:
        async def op():
            raise ValueError("always fails")

        policy = RetryPolicy(max_attempts=3, initial_delay_seconds=0.0, max_delay_seconds=0.0)
        with pytest.raises(RetryExhaustedError) as ei:
            await retry_async(op, policy=policy, operation="op", dependency="dep")
        assert ei.value.attempts == 3
        assert isinstance(ei.value.last_exception, ValueError)

    async def test_cancelled_propagates(self) -> None:
        async def op():
            raise asyncio.CancelledError()

        policy = RetryPolicy(max_attempts=3, initial_delay_seconds=0.0)
        with pytest.raises(asyncio.CancelledError):
            await retry_async(op, policy=policy)

    async def test_non_retryable_exception_reraises(self) -> None:
        class NonRetryable(Exception):
            pass

        async def op():
            raise NonRetryable()

        policy = RetryPolicy(
            max_attempts=3,
            initial_delay_seconds=0.0,
            retryable_exceptions=(ValueError,),
        )
        with pytest.raises(NonRetryable):
            await retry_async(op, policy=policy)

    async def test_with_positional_args(self) -> None:
        async def op(a, b):
            return a + b

        result, _ = await retry_async(op, 1, 2, operation="add", dependency="dep")
        assert result == 3

    async def test_with_kwargs(self) -> None:
        async def op(a, b=10):
            return a + b

        result, _ = await retry_async(op, 1, b=20, operation="add", dependency="dep")
        assert result == 21

    async def test_uses_default_policy_when_none(self) -> None:
        async def op():
            return "ok"

        # Patch asyncio.sleep to ensure we don't actually sleep
        result, _ = await retry_async(op)
        assert result == "ok"

    async def test_passes_args_and_kwargs(self) -> None:
        seen = []

        async def op(*args, **kwargs):
            seen.append((args, kwargs))
            return "x"

        await retry_async(op, 1, 2, 3, k=4, v=5)
        assert seen == [((1, 2, 3), {"k": 4, "v": 5})]

    async def test_uses_provided_metrics(self) -> None:
        m = ResilienceMetrics()
        m._enabled = False  # short-circuit

        async def op():
            return "ok"

        result, _ = await retry_async(op, metrics=m, operation="op", dependency="dep")
        assert result == "ok"


# ---------------------------------------------------------------------------
# RecoveryStrategy / ErrorCategory / RecoveryAction
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRecoveryStrategy:
    def test_values(self) -> None:
        assert RecoveryStrategy.RETRY.value == "retry"
        assert RecoveryStrategy.FALLBACK.value == "fallback"
        assert RecoveryStrategy.SKIP.value == "skip"
        assert RecoveryStrategy.ROLLBACK.value == "rollback"
        assert RecoveryStrategy.NOTIFY.value == "notify"


@pytest.mark.unit
class TestErrorCategory:
    def test_values(self) -> None:
        assert ErrorCategory.TRANSIENT.value == "transient"
        assert ErrorCategory.PERMANENT.value == "permanent"
        assert ErrorCategory.RESOURCE.value == "resource"
        assert ErrorCategory.PERMISSION.value == "permission"
        assert ErrorCategory.NETWORK.value == "network"
        assert ErrorCategory.VALIDATION.value == "validation"


@pytest.mark.unit
class TestRecoveryAction:
    def test_defaults(self) -> None:
        a = RecoveryAction(strategy=RecoveryStrategy.RETRY, category=ErrorCategory.TRANSIENT)
        assert a.max_attempts == 3
        assert a.backoff_factor == 2.0
        assert a.notify_on_failure is False
        assert a.fallback_function is None

    def test_fallback_function_attached(self) -> None:
        async def fb(*args, **kwargs):
            return "fb"

        a = RecoveryAction(
            strategy=RecoveryStrategy.FALLBACK,
            category=ErrorCategory.RESOURCE,
            fallback_function=fb,
            notify_on_failure=True,
        )
        assert a.fallback_function is fb
        assert a.notify_on_failure is True


# ---------------------------------------------------------------------------
# ErrorRecoveryManager
# ---------------------------------------------------------------------------


def _make_app():
    app = MagicMock()
    app.observability = None
    app.opensearch_integration = None
    app.workflow_state_manager = MagicMock()
    app.execute_workflow = AsyncMock()
    return app


@pytest.mark.unit
class TestErrorRecoveryManagerInit:
    def test_default_recovery_patterns_initialized(self) -> None:
        app = _make_app()
        mgr = ErrorRecoveryManager(app)
        assert "TRANSIENT" in mgr.recovery_actions
        assert "NETWORK" in mgr.recovery_actions
        assert "RESOURCE" in mgr.recovery_actions
        assert "PERMISSION" in mgr.recovery_actions
        assert "PERMANENT" in mgr.recovery_actions

    def test_resource_recovery_uses_resource_fallback(self) -> None:
        app = _make_app()
        mgr = ErrorRecoveryManager(app)
        # Pull the function reference via the dataclass — should be bound
        # to the manager instance, identical to _resource_fallback method
        fb = mgr.recovery_actions["RESOURCE"].fallback_function
        # Call the bound method and confirm we get the resource-fallback shape
        result = asyncio.run(fb())
        assert result["status"] == "fallback_executed"


@pytest.mark.unit
class TestClassifyError:
    async def test_transient_keywords(self) -> None:
        app = _make_app()
        mgr = ErrorRecoveryManager(app)
        for msg in [
            "rate limit exceeded",
            "ratelimit",
            "rate-limit hit",
            "request throttled",
            "throttling active",
            "temporary error",
            "temporaryerror raised",
            "service busy",
            "servicebusy",
            "service is busy",
            "service unavailable",
            "node offline",
            "retryable error",
            "retryableerror",
        ]:
            cat = await mgr.classify_error(Exception(msg))
            assert cat is ErrorCategory.TRANSIENT, f"msg={msg!r} -> {cat}"

    async def test_network_keywords(self) -> None:
        app = _make_app()
        mgr = ErrorRecoveryManager(app)
        for msg in [
            "connection refused",
            "operation timeout",
            "network unreachable",
            "connectivity lost",
            "socket error",
            "ssl handshake failed",
            "certificate verify failed",
            "tls handshake error",
        ]:
            cat = await mgr.classify_error(Exception(msg))
            assert cat is ErrorCategory.NETWORK, f"msg={msg!r} -> {cat}"

    async def test_resource_keywords(self) -> None:
        app = _make_app()
        mgr = ErrorRecoveryManager(app)
        for msg in [
            "out of memory",
            "disk full",
            "quota exceeded",
            "capacity limit",
            "resource exhausted",
            "OOM killed",
            "no space left on device",
        ]:
            cat = await mgr.classify_error(Exception(msg))
            assert cat is ErrorCategory.RESOURCE, f"msg={msg!r} -> {cat}"

    async def test_resource_excluded_by_index(self) -> None:
        app = _make_app()
        mgr = ErrorRecoveryManager(app)
        # "out of" + "index" should NOT match resource; falls through
        cat = await mgr.classify_error(Exception("out of range index error"))
        assert cat is not ErrorCategory.RESOURCE

    async def test_permission_keywords(self) -> None:
        app = _make_app()
        mgr = ErrorRecoveryManager(app)
        for msg in [
            "permission denied",
            "access denied",
            "forbidden",
            "unauthorized",
            "auth failed",
            "invalid credentials",
        ]:
            cat = await mgr.classify_error(Exception(msg))
            assert cat is ErrorCategory.PERMISSION, f"msg={msg!r} -> {cat}"

    async def test_validation_keywords(self) -> None:
        app = _make_app()
        mgr = ErrorRecoveryManager(app)
        for msg in [
            "invalid input",
            "malformed data",
            "validation failed",
            "bad format",
            "valueerror raised",
            "typeerror thrown",
            "schema mismatch",
            "assertion failed",
            "assertionerror raised",
        ]:
            cat = await mgr.classify_error(Exception(msg))
            assert cat is ErrorCategory.VALIDATION, f"msg={msg!r} -> {cat}"

    async def test_default_permanent(self) -> None:
        app = _make_app()
        mgr = ErrorRecoveryManager(app)
        cat = await mgr.classify_error(Exception("some random unknown error xyz"))
        assert cat is ErrorCategory.PERMANENT

    async def test_transient_takes_priority_over_resource(self) -> None:
        # "rate limit" + "limit" — must classify as TRANSIENT
        app = _make_app()
        mgr = ErrorRecoveryManager(app)
        cat = await mgr.classify_error(Exception("rate limit exceeded"))
        assert cat is ErrorCategory.TRANSIENT


@pytest.mark.unit
class TestExecuteWithResilience:
    async def test_success(self) -> None:
        app = _make_app()

        async def op():
            return "ok"

        mgr = ErrorRecoveryManager(app)
        result = await mgr.execute_with_resilience(op)
        assert result["success"] is True
        assert result["result"] == "ok"
        assert result["attempts"] == 1

    async def test_retry_recovery(self) -> None:
        app = _make_app()
        mgr = ErrorRecoveryManager(app)

        # Use retry strategy explicitly with 2 attempts
        call_count = 0

        async def op():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                # Use a real TRANSIENT keyword so the recovery action picks RETRY
                raise Exception("service busy")
            return "ok"

        # TRANSIENT default has max_attempts=5
        with patch("mahavishnu.core.resilience.random.uniform", return_value=0.0):
            result = await mgr.execute_with_resilience(op)
        assert result["success"] is True
        assert result["recovered"] is True

    async def test_skip_recovery(self) -> None:
        app = _make_app()
        mgr = ErrorRecoveryManager(app)

        async def op():
            raise Exception("permission denied")

        result = await mgr.execute_with_resilience(op)
        assert result["success"] is False
        assert result["skipped"] is True
        assert result["recovered"] is True

    async def test_fallback_recovery(self) -> None:
        app = _make_app()
        mgr = ErrorRecoveryManager(app)

        async def op():
            raise Exception("resource exhausted")

        result = await mgr.execute_with_resilience(op)
        assert result["success"] is True
        assert result["recovered"] is True

    async def test_retry_exhausted(self) -> None:
        app = _make_app()
        mgr = ErrorRecoveryManager(app)

        async def op():
            raise Exception("transient unavailable")

        # Patch random to avoid jitter variance
        with patch("mahavishnu.core.resilience.random.uniform", return_value=0.0):
            result = await mgr.execute_with_resilience(op)
        assert result["success"] is False
        assert result["recovered"] is False
        assert result["attempts"] >= 1

    async def test_default_recovery_action_when_unknown_category(self) -> None:
        # Build manager without a category match — patch classify_error
        app = _make_app()
        mgr = ErrorRecoveryManager(app)
        # Remove the uppercased category to force default branch
        mgr.recovery_actions.pop("TRANSIENT", None)

        async def op():
            raise Exception("transient busy")

        with patch("mahavishnu.core.resilience.random.uniform", return_value=0.0):
            result = await mgr.execute_with_resilience(op)
        # Default recovery action has max_attempts=3 + retry strategy
        assert result["success"] is False
        assert result["recovered"] is False

    async def test_fallback_fails(self) -> None:
        app = _make_app()
        mgr = ErrorRecoveryManager(app)
        # Replace resource fallback with one that fails
        async def bad_fallback(*args, **kwargs):
            raise RuntimeError("fb failed")

        mgr.recovery_actions["RESOURCE"].fallback_function = bad_fallback

        async def op():
            raise Exception("resource exhausted")

        result = await mgr.execute_with_resilience(op)
        assert result["success"] is False
        assert result["recovered"] is False

    async def test_notify_strategy(self) -> None:
        app = _make_app()
        mgr = ErrorRecoveryManager(app)
        mgr.recovery_actions["PERMANENT"] = RecoveryAction(
            strategy=RecoveryStrategy.NOTIFY,
            category=ErrorCategory.PERMANENT,
        )

        async def op():
            raise Exception("some unknown error")

        result = await mgr.execute_with_resilience(op)
        assert result["success"] is False
        assert result["recovered"] is False


@pytest.mark.unit
class TestSkipAndContinue:
    async def test_skip(self) -> None:
        app = _make_app()
        mgr = ErrorRecoveryManager(app)
        result = await mgr._skip_and_continue(RuntimeError("nope"), workflow_id="wf1")
        assert result["success"] is False
        assert result["recovered"] is True
        assert result["skipped"] is True
        assert result["error"] == "nope"


@pytest.mark.unit
class TestNotifyError:
    async def test_notify(self) -> None:
        app = _make_app()
        mgr = ErrorRecoveryManager(app)
        result = await mgr._notify_error(RuntimeError("bad"), workflow_id="wf1")
        assert result["success"] is False
        assert result["recovered"] is False
        assert result["error"] == "bad"


@pytest.mark.unit
class TestResourceFallback:
    async def test_returns_fallback_result(self) -> None:
        app = _make_app()
        mgr = ErrorRecoveryManager(app)
        result = await mgr._resource_fallback()
        assert result["status"] == "fallback_executed"


@pytest.mark.unit
class TestLogOperationResult:
    async def test_log_success_with_observability(self) -> None:
        app = _make_app()
        obs = MagicMock()
        app.observability = obs
        mgr = ErrorRecoveryManager(app)
        await mgr._log_operation_result(
            workflow_id="wf1", repo_path="repo1", success=True, execution_time=0.1, result="x"
        )
        obs.log_info.assert_called_once()

    async def test_log_failure_with_observability(self) -> None:
        app = _make_app()
        obs = MagicMock()
        app.observability = obs
        mgr = ErrorRecoveryManager(app)
        await mgr._log_operation_result(
            workflow_id="wf1",
            repo_path="repo1",
            success=False,
            execution_time=0.1,
            error="bad",
            error_category="PERMANENT",
        )
        obs.log_error.assert_called_once()

    async def test_log_with_opensearch_success(self) -> None:
        app = _make_app()
        oi = MagicMock()
        oi.log_workflow_update = AsyncMock()
        oi.log_error = AsyncMock()
        app.opensearch_integration = oi
        mgr = ErrorRecoveryManager(app)
        await mgr._log_operation_result(
            workflow_id="wf1", repo_path="repo1", success=True, execution_time=0.1, result="x"
        )
        oi.log_workflow_update.assert_awaited_once()

    async def test_log_with_opensearch_failure(self) -> None:
        app = _make_app()
        oi = MagicMock()
        oi.log_workflow_update = AsyncMock()
        oi.log_error = AsyncMock()
        app.opensearch_integration = oi
        mgr = ErrorRecoveryManager(app)
        await mgr._log_operation_result(
            workflow_id="wf1",
            repo_path="repo1",
            success=False,
            execution_time=0.1,
            error="bad",
            error_category="PERMANENT",
        )
        oi.log_error.assert_awaited_once()


@pytest.mark.unit
class TestLogRecoveryAction:
    async def test_log_recovery_with_observability(self) -> None:
        app = _make_app()
        obs = MagicMock()
        app.observability = obs
        mgr = ErrorRecoveryManager(app)
        await mgr._log_recovery_action(
            workflow_id="wf1", repo_path="repo1", action="retry_success", attempt=1
        )
        obs.log_info.assert_called_once()

    async def test_log_recovery_with_opensearch(self) -> None:
        app = _make_app()
        oi = MagicMock()
        oi.log_workflow_update = AsyncMock()
        app.opensearch_integration = oi
        mgr = ErrorRecoveryManager(app)
        await mgr._log_recovery_action(
            workflow_id="wf1", repo_path="repo1", action="retry_success", attempt=1
        )
        oi.log_workflow_update.assert_awaited_once()


@pytest.mark.unit
class TestMonitorAndHealWorkflows:
    async def test_heals_failed_workflow(self) -> None:
        app = _make_app()
        wsm = MagicMock()
        wsm.list_workflows = AsyncMock(
            return_value=[
                {
                    "id": "wf1",
                    "task": {"id": "t1", "adapter": "llamaindex"},
                    "repos": ["repo1"],
                    "errors": [],
                }
            ]
        )
        wsm.update = AsyncMock()
        app.workflow_state_manager = wsm
        app.execute_workflow = AsyncMock(return_value="ok")

        mgr = ErrorRecoveryManager(app)
        with patch.object(
            ErrorRecoveryManager, "execute_with_resilience", new=AsyncMock(return_value={"success": True})
        ):
            await mgr.monitor_and_heal_workflows()
        wsm.update.assert_awaited()

    async def test_heals_workflow_with_workflow_id_key(self) -> None:
        app = _make_app()
        wsm = MagicMock()
        wsm.list_workflows = AsyncMock(
            return_value=[
                {
                    "workflow_id": "wf2",
                    "task": {"id": "t2"},
                    "repos": ["repo2"],
                    "errors": [],
                }
            ]
        )
        wsm.update = AsyncMock()
        app.workflow_state_manager = wsm

        mgr = ErrorRecoveryManager(app)
        with patch.object(
            ErrorRecoveryManager, "execute_with_resilience", new=AsyncMock(return_value={"success": True})
        ):
            await mgr.monitor_and_heal_workflows()
        wsm.update.assert_awaited()

    async def test_skips_workflow_with_too_many_errors(self) -> None:
        app = _make_app()
        wsm = MagicMock()
        wsm.list_workflows = AsyncMock(
            return_value=[
                {
                    "id": "wf1",
                    "task": {"id": "t1"},
                    "repos": ["repo1"],
                    "errors": [1, 2, 3, 4, 5, 6],
                }
            ]
        )
        wsm.update = AsyncMock()
        app.workflow_state_manager = wsm

        mgr = ErrorRecoveryManager(app)
        await mgr.monitor_and_heal_workflows()
        wsm.update.assert_not_called()

    async def test_skips_workflow_with_no_task_or_repos(self) -> None:
        app = _make_app()
        wsm = MagicMock()
        wsm.list_workflows = AsyncMock(
            return_value=[
                {"id": "wf1", "errors": []},
            ]
        )
        wsm.update = AsyncMock()
        app.workflow_state_manager = wsm

        mgr = ErrorRecoveryManager(app)
        await mgr.monitor_and_heal_workflows()
        wsm.update.assert_not_called()

    async def test_heal_failure_path(self) -> None:
        app = _make_app()
        wsm = MagicMock()
        wsm.list_workflows = AsyncMock(
            return_value=[
                {
                    "id": "wf1",
                    "task": {"id": "t1"},
                    "repos": ["repo1"],
                    "errors": [],
                }
            ]
        )
        wsm.update = AsyncMock()
        app.workflow_state_manager = wsm

        mgr = ErrorRecoveryManager(app)
        with patch.object(
            ErrorRecoveryManager,
            "execute_with_resilience",
            new=AsyncMock(return_value={"success": False, "error": "nope"}),
        ):
            await mgr.monitor_and_heal_workflows()
        wsm.update.assert_not_called()

    async def test_heal_workflow_raises_caught(self) -> None:
        app = _make_app()
        wsm = MagicMock()
        wsm.list_workflows = AsyncMock(
            return_value=[
                {
                    "id": "wf1",
                    "task": {"id": "t1"},
                    "repos": ["repo1"],
                    "errors": [],
                }
            ]
        )
        app.workflow_state_manager = wsm

        mgr = ErrorRecoveryManager(app)
        with patch.object(
            ErrorRecoveryManager,
            "execute_with_resilience",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            await mgr.monitor_and_heal_workflows()  # must not raise

    async def test_monitor_handles_top_level_exception(self) -> None:
        app = _make_app()
        wsm = MagicMock()
        wsm.list_workflows = AsyncMock(side_effect=RuntimeError("top level"))
        app.workflow_state_manager = wsm

        mgr = ErrorRecoveryManager(app)
        await mgr.monitor_and_heal_workflows()  # must not raise


@pytest.mark.unit
class TestCheckStuckWorkflows:
    async def test_marks_stuck_workflows(self) -> None:
        app = _make_app()
        wsm = MagicMock()
        # updated_at 2 hours ago, should be marked stuck
        old_ts = "2020-01-01T00:00:00+00:00"
        wsm.list_workflows = AsyncMock(
            return_value=[
                {"id": "wf1", "updated_at": old_ts},
            ]
        )
        wsm.update = AsyncMock()
        app.workflow_state_manager = wsm

        mgr = ErrorRecoveryManager(app)
        await mgr._check_stuck_workflows()
        wsm.update.assert_awaited()
        kwargs = wsm.update.await_args.kwargs
        assert kwargs["status"] == "failed"
        assert kwargs["timed_out"] is True

    async def test_skips_workflows_with_unparseable_date(self) -> None:
        app = _make_app()
        wsm = MagicMock()
        wsm.list_workflows = AsyncMock(
            return_value=[{"id": "wf1", "updated_at": "not-a-date"}]
        )
        wsm.update = AsyncMock()
        app.workflow_state_manager = wsm

        mgr = ErrorRecoveryManager(app)
        await mgr._check_stuck_workflows()
        wsm.update.assert_not_called()

    async def test_no_workflows(self) -> None:
        app = _make_app()
        wsm = MagicMock()
        wsm.list_workflows = AsyncMock(return_value=[])
        wsm.update = AsyncMock()
        app.workflow_state_manager = wsm

        mgr = ErrorRecoveryManager(app)
        await mgr._check_stuck_workflows()
        wsm.update.assert_not_called()

    async def test_workflow_without_id_skipped(self) -> None:
        app = _make_app()
        wsm = MagicMock()
        wsm.list_workflows = AsyncMock(
            return_value=[{"updated_at": "2020-01-01T00:00:00+00:00"}]
        )
        wsm.update = AsyncMock()
        app.workflow_state_manager = wsm

        mgr = ErrorRecoveryManager(app)
        await mgr._check_stuck_workflows()
        wsm.update.assert_not_called()

    async def test_check_stuck_handles_exception(self) -> None:
        app = _make_app()
        wsm = MagicMock()
        wsm.list_workflows = AsyncMock(side_effect=RuntimeError("boom"))
        app.workflow_state_manager = wsm

        mgr = ErrorRecoveryManager(app)
        await mgr._check_stuck_workflows()  # must not raise


@pytest.mark.unit
class TestGetRecoveryMetrics:
    async def test_returns_metrics(self) -> None:
        app = _make_app()
        mgr = ErrorRecoveryManager(app)
        mgr.recovery_history = [
            {"success": True},
            {"success": False},
        ]
        result = await mgr.get_recovery_metrics()
        assert result["total_recovery_attempts"] == 2
        assert result["successful_recoveries"] == 1
        assert result["failed_recoveries"] == 1
        assert "most_common_error_categories" in result
        assert "average_recovery_time" in result
        assert "recovery_effectiveness_rate" in result


# ---------------------------------------------------------------------------
# ResiliencePatterns
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResiliencePatternsEdgeBranches:
    async def test_default_strategy_unknown_recovery_action_uses_retry(self) -> None:
        # Force a code path through _attempt_recovery where strategy isn't
        # one of the recognized ones, hitting the default retry branch.
        app = _make_app()
        mgr = ErrorRecoveryManager(app)
        mgr.recovery_actions["TRANSIENT"] = RecoveryAction(
            strategy=RecoveryStrategy.ROLLBACK,  # not handled in _attempt_recovery
            category=ErrorCategory.TRANSIENT,
            max_attempts=2,
            backoff_factor=1.0,
        )

        async def op():
            raise Exception("service busy")

        with patch("mahavishnu.core.resilience.random.uniform", return_value=0.0):
            result = await mgr.execute_with_resilience(op)
        # Default branch retries with max_attempts=2; both fail; success=False
        assert result["success"] is False
        assert result["recovered"] is False
        assert result["attempts"] == 3  # 1 initial + 2 retries


@pytest.mark.unit
class TestResiliencePatterns:
    def test_init(self) -> None:
        app = _make_app()
        rp = ResiliencePatterns(app)
        assert rp.app is app
        assert isinstance(rp.recovery_manager, ErrorRecoveryManager)
        assert rp._shutdown_event is not None

    async def test_resilient_workflow_execution(self) -> None:
        app = _make_app()
        rp = ResiliencePatterns(app)
        with patch.object(
            ErrorRecoveryManager,
            "execute_with_resilience",
            new=AsyncMock(return_value={"success": True, "result": "x"}),
        ) as ewr:
            result = await rp.resilient_workflow_execution(
                task={"id": "t1"},
                adapter_name="llamaindex",
                repos=["repo1"],
                user_id="u1",
            )
        assert result["success"] is True
        ewr.assert_awaited_once()
        # Check kwargs
        kwargs = ewr.await_args.kwargs
        assert kwargs["workflow_id"] == "t1"
        assert kwargs["user_id"] == "u1"

    async def test_resilient_workflow_execution_default_id(self) -> None:
        app = _make_app()
        rp = ResiliencePatterns(app)
        with patch.object(
            ErrorRecoveryManager,
            "execute_with_resilience",
            new=AsyncMock(return_value={"success": True}),
        ) as ewr:
            await rp.resilient_workflow_execution(
                task={}, adapter_name="llamaindex", repos=["repo1"]
            )
        kwargs = ewr.await_args.kwargs
        assert kwargs["workflow_id"].startswith("resilient_")

    async def test_resilient_repo_operation(self) -> None:
        app = _make_app()
        rp = ResiliencePatterns(app)

        async def op(*args, **kwargs):
            return "ok"

        with patch.object(
            ErrorRecoveryManager,
            "execute_with_resilience",
            new=AsyncMock(return_value={"success": True, "result": "x"}),
        ) as ewr:
            result = await rp.resilient_repo_operation(op, "repo1", 1, 2, workflow_id="wf1", k=3)
        assert result["success"] is True
        kwargs = ewr.await_args.kwargs
        assert kwargs["repo_path"] == "repo1"
        assert kwargs["workflow_id"] == "wf1"
        assert kwargs["k"] == 3

    async def test_start_and_stop_monitoring(self) -> None:
        app = _make_app()
        rp = ResiliencePatterns(app)
        await rp.start_monitoring_service()
        # Give the task time to spin
        await asyncio.sleep(0.05)
        assert rp._shutdown_event.is_set() is False
        await rp.stop_monitoring_service()
        assert rp._shutdown_event.is_set() is True
        # Allow the monitoring loop task to finish
        await asyncio.sleep(0.05)
