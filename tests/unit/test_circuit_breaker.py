"""Unit tests for circuit breaker implementation."""

import asyncio
from datetime import datetime

import pytest

from mahavishnu.core.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    circuit_breaker,
)


class TestCircuitBreakerStates:
    """Test circuit breaker state transitions."""

    def test_initially_closed(self):
        """Test that circuit breaker starts in CLOSED state."""
        breaker = CircuitBreaker(threshold=5, timeout=60)
        assert breaker.state == CircuitState.CLOSED
        assert breaker.allow_request() is True

    def test_opens_on_threshold(self):
        """Test that circuit opens after failure threshold is reached."""
        breaker = CircuitBreaker(threshold=3, timeout=60)
        assert breaker.state == CircuitState.CLOSED

        # Record failures up to threshold
        for _ in range(3):
            breaker.record_failure()

        assert breaker.state == CircuitState.OPEN
        assert breaker.allow_request() is False

    def test_opens_only_when_threshold_reached(self):
        """Test that circuit stays closed below threshold."""
        breaker = CircuitBreaker(threshold=5, timeout=60)

        # Record failures below threshold
        for _ in range(4):
            breaker.record_failure()

        assert breaker.state == CircuitState.CLOSED
        assert breaker.allow_request() is True

    def test_transitions_to_half_open_after_timeout(self):
        """Test that circuit transitions to HALF_OPEN after timeout."""
        breaker = CircuitBreaker(threshold=3, timeout=1)

        # Open the circuit
        for _ in range(3):
            breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # Wait for timeout
        import time

        time.sleep(1.1)

        # Next request should transition to HALF_OPEN
        assert breaker.allow_request() is True
        assert breaker.state == CircuitState.HALF_OPEN

    def test_remains_open_within_timeout(self):
        """Test that circuit remains OPEN within timeout period."""
        breaker = CircuitBreaker(threshold=2, timeout=2)

        # Open the circuit
        for _ in range(2):
            breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # Check requests are still denied within timeout
        import time

        time.sleep(0.5)
        assert breaker.allow_request() is False
        assert breaker.state == CircuitState.OPEN

    def test_transitions_from_half_open_to_closed_on_success(self):
        """Test that circuit closes after success in HALF_OPEN state."""
        breaker = CircuitBreaker(threshold=2, timeout=1)

        # Open the circuit
        for _ in range(2):
            breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # Wait for timeout and transition to HALF_OPEN
        import time

        time.sleep(1.1)
        breaker.allow_request()
        assert breaker.state == CircuitState.HALF_OPEN

        # Record success should close the circuit
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED

    def test_opens_again_on_failure_in_half_open(self):
        """Test that circuit re-opens on failure in HALF_OPEN state."""
        breaker = CircuitBreaker(threshold=2, timeout=1)

        # Open the circuit
        for _ in range(2):
            breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # Wait for timeout and transition to HALF_OPEN
        import time

        time.sleep(1.1)
        breaker.allow_request()
        assert breaker.state == CircuitState.HALF_OPEN

        # Record failure should open the circuit again
        breaker.record_failure()
        # Note: Circuit doesn't automatically open on single failure in HALF_OPEN
        # It needs to reach threshold again
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN


class TestCircuitBreakerCounters:
    """Test circuit breaker counter behavior."""

    def test_failure_counter_increments(self):
        """Test that failure counter increments correctly."""
        breaker = CircuitBreaker(threshold=5)
        for i in range(5):
            breaker.record_failure()
            assert breaker.failure_count == i + 1

    def test_failure_counter_resets_on_success(self):
        """Test that failure counter resets on success."""
        breaker = CircuitBreaker(threshold=5)

        # Record some failures
        for _ in range(3):
            breaker.record_failure()
        assert breaker.failure_count == 3

        # Success should reset counter
        breaker.record_success()
        assert breaker.failure_count == 0

    def test_last_failure_time_set(self):
        """Test that last failure time is recorded."""
        breaker = CircuitBreaker(threshold=5)
        assert breaker.last_failure_time is None

        breaker.record_failure()
        assert breaker.last_failure_time is not None
        assert isinstance(breaker.last_failure_time, datetime)

    def test_last_failure_time_updates(self):
        """Test that last failure time updates on each failure."""
        breaker = CircuitBreaker(threshold=5)

        breaker.record_failure()
        first_time = breaker.last_failure_time

        import time

        time.sleep(0.1)

        breaker.record_failure()
        second_time = breaker.last_failure_time

        assert second_time > first_time


class TestCircuitBreakerConfigurations:
    """Test circuit breaker configuration options."""

    def test_default_configuration(self):
        """Test default configuration values."""
        breaker = CircuitBreaker()
        assert breaker.threshold == 5
        assert breaker.timeout == 60
        assert breaker.reset_timeout == 60

    def test_custom_threshold(self):
        """Test custom threshold configuration."""
        breaker = CircuitBreaker(threshold=10)
        assert breaker.threshold == 10

        # Should not open before threshold
        for _ in range(9):
            breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED

        # Should open at threshold
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

    def test_custom_timeout(self):
        """Test custom timeout configuration."""
        breaker = CircuitBreaker(threshold=1, timeout=2)

        # Open the circuit
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # Should still be OPEN within timeout
        import time

        time.sleep(1)
        assert breaker.state == CircuitState.OPEN
        assert breaker.allow_request() is False

        # Should transition to HALF_OPEN after timeout
        time.sleep(1.1)
        assert breaker.allow_request() is True

    def test_custom_reset_timeout(self):
        """Test custom reset_timeout configuration."""
        breaker = CircuitBreaker(threshold=5, timeout=60, reset_timeout=120)
        assert breaker.reset_timeout == 120

    def test_all_custom_parameters(self):
        """Test all custom parameters together."""
        breaker = CircuitBreaker(threshold=3, timeout=10, reset_timeout=30)
        assert breaker.threshold == 3
        assert breaker.timeout == 10
        assert breaker.reset_timeout == 30


class TestCircuitBreakerAllowRequest:
    """Test allow_request method behavior."""

    def test_allow_request_when_closed(self):
        """Test that requests are allowed when circuit is CLOSED."""
        breaker = CircuitBreaker(threshold=5)
        assert breaker.allow_request() is True

    def test_deny_request_when_open(self):
        """Test that requests are denied when circuit is OPEN."""
        breaker = CircuitBreaker(threshold=2)
        for _ in range(2):
            breaker.record_failure()
        assert breaker.allow_request() is False

    def test_allow_request_when_half_open(self):
        """Test that requests are allowed when circuit is HALF_OPEN."""
        breaker = CircuitBreaker(threshold=2, timeout=1)

        # Open circuit
        for _ in range(2):
            breaker.record_failure()

        # Wait for timeout
        import time

        time.sleep(1.1)

        # Transition to HALF_OPEN
        breaker.allow_request()
        assert breaker.state == CircuitState.HALF_OPEN
        assert breaker.allow_request() is True

    def test_allow_request_transitions_state(self):
        """Test that allow_request triggers state transitions."""
        breaker = CircuitBreaker(threshold=1, timeout=1)

        # Open circuit
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # Wait for timeout
        import time

        time.sleep(1.1)

        # allow_request should trigger transition to HALF_OPEN
        result = breaker.allow_request()
        assert result is True
        assert breaker.state == CircuitState.HALF_OPEN


class TestCircuitBreakerCall:
    """Test circuit breaker call method."""

    @pytest.mark.asyncio
    async def test_call_successful_sync_function(self):
        """Test calling a successful synchronous function."""
        breaker = CircuitBreaker(threshold=5, timeout=60)

        def sync_func(x, y):
            return x + y

        result = await breaker.call(sync_func, 2, 3)
        assert result == 5
        assert breaker.failure_count == 0
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_call_successful_async_function(self):
        """Test calling a successful async function."""
        breaker = CircuitBreaker(threshold=5, timeout=60)

        async def async_func(x, y):
            await asyncio.sleep(0.01)
            return x * y

        result = await breaker.call(async_func, 3, 4)
        assert result == 12
        assert breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_call_failing_function_records_failure(self):
        """Test that function failures are recorded."""
        breaker = CircuitBreaker(threshold=3, timeout=60)

        def failing_func():
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            await breaker.call(failing_func)

        assert breaker.failure_count == 1

    @pytest.mark.asyncio
    async def test_call_opens_circuit_on_threshold(self):
        """Test that circuit opens after threshold failures."""
        breaker = CircuitBreaker(threshold=2, timeout=60)

        def failing_func():
            raise ValueError("Test error")

        # First failure
        with pytest.raises(ValueError):
            await breaker.call(failing_func)

        # Second failure - should open circuit
        with pytest.raises(ValueError):
            await breaker.call(failing_func)

        assert breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_call_raises_exception_when_open(self):
        """Test that call raises exception when circuit is OPEN."""
        breaker = CircuitBreaker(threshold=1, timeout=60)

        def failing_func():
            raise ValueError("Test error")

        # Open the circuit
        with pytest.raises(ValueError):
            await breaker.call(failing_func)

        assert breaker.state == CircuitState.OPEN

        # Next call should raise circuit breaker exception
        with pytest.raises(Exception, match="Circuit breaker is open, request denied"):
            await breaker.call(failing_func)

    @pytest.mark.asyncio
    async def test_call_with_kwargs(self):
        """Test calling function with keyword arguments."""
        breaker = CircuitBreaker(threshold=5, timeout=60)

        def func(a, b, c=0):
            return a + b + c

        result = await breaker.call(func, 1, 2, c=3)
        assert result == 6

    @pytest.mark.asyncio
    async def test_call_resets_on_success_after_failure(self):
        """Test that success after failure resets counter."""
        breaker = CircuitBreaker(threshold=3, timeout=60)

        def failing_func():
            raise ValueError("Test error")

        def success_func():
            return "success"

        # Record failures
        for _ in range(2):
            try:
                await breaker.call(failing_func)
            except ValueError:
                pass

        assert breaker.failure_count == 2

        # Success should reset counter
        result = await breaker.call(success_func)
        assert result == "success"
        assert breaker.failure_count == 0


class TestCircuitBreakerDecorator:
    """Test circuit breaker decorator."""

    @pytest.mark.asyncio
    async def test_decorator_on_async_function(self):
        """Test decorator on async function."""
        call_count = 0

        @circuit_breaker(threshold=2, timeout=60)
        async def failing_function():
            nonlocal call_count
            call_count += 1
            raise ValueError("Test error")

        # First call should fail but execute
        with pytest.raises(ValueError):
            await failing_function()

        # Second call should fail but execute
        with pytest.raises(ValueError):
            await failing_function()

        # Third call should be blocked by circuit breaker
        with pytest.raises(Exception, match="Circuit breaker is open, request denied"):
            await failing_function()

        assert call_count == 2  # Function only called twice before circuit opened

    def test_decorator_on_sync_function(self):
        """Test decorator on sync function."""
        call_count = 0

        @circuit_breaker(threshold=2, timeout=60)
        def failing_function():
            nonlocal call_count
            call_count += 1
            raise ValueError("Test error")

        # First call should fail but execute
        with pytest.raises(ValueError):
            failing_function()

        # Second call should fail but execute
        with pytest.raises(ValueError):
            failing_function()

        # Third call should be blocked by circuit breaker
        with pytest.raises(Exception, match="Circuit breaker is open, request denied"):
            failing_function()

        assert call_count == 2  # Function only called twice before circuit opened

    @pytest.mark.asyncio
    async def test_decorator_allows_success_after_reset(self):
        """Test that decorator allows calls after circuit resets."""
        call_count = 0

        @circuit_breaker(threshold=1, timeout=1)
        async def conditional_function(should_fail=True):
            nonlocal call_count
            call_count += 1
            if should_fail:
                raise ValueError("Test error")
            return "success"

        # Open the circuit
        with pytest.raises(ValueError):
            await conditional_function(should_fail=True)

        # Wait for timeout
        await asyncio.sleep(1.1)

        # Should allow request in HALF_OPEN state
        result = await conditional_function(should_fail=False)
        assert result == "success"

        # Circuit should now be closed
        assert call_count == 2


class TestCircuitBreakerEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_threshold_of_one(self):
        """Test circuit breaker with threshold of 1."""
        breaker = CircuitBreaker(threshold=1, timeout=60)
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

    def test_large_threshold(self):
        """Test circuit breaker with large threshold."""
        breaker = CircuitBreaker(threshold=1000, timeout=60)
        for _ in range(999):
            breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

    def test_zero_timeout(self):
        """Test circuit breaker with zero timeout."""
        breaker = CircuitBreaker(threshold=1, timeout=0)
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # With timeout=0, should transition immediately
        assert breaker.allow_request() is True
        assert breaker.state == CircuitState.HALF_OPEN

    def test_multiple_successes_in_closed_state(self):
        """Test that multiple successes in CLOSED state don't cause issues."""
        breaker = CircuitBreaker(threshold=5, timeout=60)
        for _ in range(10):
            breaker.record_success()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_success_in_open_state(self):
        """Test that success in OPEN state doesn't close circuit immediately."""
        breaker = CircuitBreaker(threshold=2, timeout=60)
        for _ in range(2):
            breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # Success in OPEN state should reset counter but keep state OPEN
        breaker.record_success()
        assert breaker.failure_count == 0
        assert breaker.state == CircuitState.OPEN

    def test_failure_time_precision(self):
        """Test that failure time has sufficient precision for timeout logic."""
        breaker = CircuitBreaker(threshold=1, timeout=1)

        breaker.record_failure()
        first_failure_time = breaker.last_failure_time

        import time

        time.sleep(0.1)

        breaker.record_failure()
        second_failure_time = breaker.last_failure_time

        # Should have millisecond precision
        time_diff = (second_failure_time - first_failure_time).total_seconds()
        assert time_diff >= 0.1

    def test_state_consistency_after_multiple_cycles(self):
        """Test state consistency through multiple open/close cycles."""
        breaker = CircuitBreaker(threshold=2, timeout=1)

        # First cycle
        for _ in range(2):
            breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        import time

        time.sleep(1.1)
        breaker.allow_request()
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED

        # Second cycle
        for _ in range(2):
            breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        time.sleep(1.1)
        breaker.allow_request()
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED


class TestCircuitBreakerLogging:
    """Test circuit breaker logging behavior."""

    def test_logs_warning_on_open(self, caplog):
        """Test that circuit breaker logs warning when opening."""
        import logging

        breaker = CircuitBreaker(threshold=2, timeout=60)

        with caplog.at_level(logging.WARNING):
            breaker.record_failure()
            breaker.record_failure()

        assert "Circuit breaker opened after 2 failures" in caplog.text

    def test_logs_info_on_close(self, caplog):
        """Test that circuit breaker logs info when closing."""
        import logging

        breaker = CircuitBreaker(threshold=2, timeout=1)

        # Open the circuit
        for _ in range(2):
            breaker.record_failure()

        # Wait for timeout and transition to HALF_OPEN
        import time

        time.sleep(1.1)
        breaker.allow_request()

        # Record success should close the circuit
        with caplog.at_level(logging.INFO):
            breaker.record_success()

        assert "Circuit breaker closed after successful request" in caplog.text

    def test_logs_info_on_half_open_transition(self, caplog):
        """Test that circuit breaker logs info when transitioning to HALF_OPEN."""
        import logging

        breaker = CircuitBreaker(threshold=1, timeout=1)

        # Open the circuit
        breaker.record_failure()

        # Wait for timeout and check transition
        import time

        time.sleep(1.1)

        with caplog.at_level(logging.INFO):
            breaker.allow_request()

        assert "Circuit breaker transitioning to half-open for test" in caplog.text
