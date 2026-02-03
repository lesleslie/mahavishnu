"""Tests for circuit breaker and retry patterns.

Tests cover:
- Circuit breaker state transitions
- Retry logic with various backoff strategies
- Combined circuit breaker + retry
- Fallback patterns
- Edge cases and error conditions
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from monitoring.resilience import (
    CircuitBreaker,
    CircuitBreakerError,
    CircuitState,
    Retry,
    BackoffStrategy,
    MaxRetriesExceededError,
    circuit_breaker,
    retry,
    resilient,
    with_fallback,
)


# ============================================================================
# Circuit Breaker Tests
# ============================================================================

class TestCircuitBreaker:
    """Test circuit breaker functionality."""

    @pytest.mark.asyncio
    async def test_circuit_closed_initially(self):
        """Circuit should start in CLOSED state."""
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_circuit_opens_after_threshold(self):
        """Circuit should open after failure threshold is reached."""
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60)

        async def failing_function():
            raise ConnectionError("Connection failed")

        # First two failures should not open circuit
        for i in range(2):
            with pytest.raises(ConnectionError):
                await breaker.call(failing_function)
            assert breaker.state == CircuitState.CLOSED
            assert breaker.failure_count == i + 1

        # Third failure should open circuit
        with pytest.raises(ConnectionError):
            await breaker.call(failing_function)
        assert breaker.state == CircuitState.OPEN
        assert breaker.failure_count == 3

    @pytest.mark.asyncio
    async def test_circuit_rejects_calls_when_open(self):
        """Circuit should reject calls when OPEN without executing function."""
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=60)

        async def failing_function():
            raise ConnectionError("Connection failed")

        # Open the circuit
        with pytest.raises(ConnectionError):
            await breaker.call(failing_function)
        with pytest.raises(ConnectionError):
            await breaker.call(failing_function)

        assert breaker.state == CircuitState.OPEN

        # Next call should fail fast with CircuitBreakerError
        # without calling the function
        with pytest.raises(CircuitBreakerError):
            await breaker.call(failing_function)

    @pytest.mark.asyncio
    async def test_circuit_transitions_to_half_open_after_timeout(self):
        """Circuit should transition to HALF_OPEN after recovery timeout."""
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=0.2)  # 200ms

        async def failing_function():
            raise ConnectionError("Connection failed")

        # Open the circuit
        with pytest.raises(ConnectionError):
            await breaker.call(failing_function)
        with pytest.raises(ConnectionError):
            await breaker.call(failing_function)

        assert breaker.state == CircuitState.OPEN
        assert breaker.failure_count == 2

        # Wait for recovery timeout + buffer
        await asyncio.sleep(0.25)

        # Next call should transition to HALF_OPEN and attempt call
        with pytest.raises(ConnectionError):
            await breaker.call(failing_function)

        # After call fails in HALF_OPEN, should reopen to OPEN
        assert breaker.state == CircuitState.OPEN
        assert breaker.failure_count == 3

    @pytest.mark.asyncio
    async def test_circuit_closes_after_successful_half_open_call(self):
        """Circuit should close after successful call in HALF_OPEN state."""
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)

        # Track function calls
        call_count = 0

        async def sometimes_failing():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Connection failed")
            return "success"

        # Open circuit
        with pytest.raises(ConnectionError):
            await breaker.call(sometimes_failing)
        with pytest.raises(ConnectionError):
            await breaker.call(sometimes_failing)

        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(0.15)

        # Next call should succeed and close circuit
        result = await breaker.call(sometimes_failing)
        assert result == "success"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_circuit_reopens_after_failed_half_open_call(self):
        """Circuit should reopen if call fails in HALF_OPEN state."""
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)

        async def always_failing():
            raise ConnectionError("Connection failed")

        # Open circuit
        with pytest.raises(ConnectionError):
            await breaker.call(always_failing)
        with pytest.raises(ConnectionError):
            await breaker.call(always_failing)

        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(0.15)

        # Call should fail and reopen circuit
        with pytest.raises(ConnectionError):
            await breaker.call(always_failing)

        assert breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_circuit_decorator(self):
        """Circuit breaker should work as a decorator."""
        breaker = circuit_breaker(failure_threshold=2, recovery_timeout=60)

        @breaker
        async def protected_function():
            raise ConnectionError("Connection failed")

        # Open circuit with decorator
        with pytest.raises(ConnectionError):
            await protected_function()
        with pytest.raises(ConnectionError):
            await protected_function()

        # Next call should fail fast
        with pytest.raises(CircuitBreakerError):
            await protected_function()

    @pytest.mark.asyncio
    async def test_circuit_manual_reset(self):
        """Manual reset should close circuit regardless of state."""
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=60)

        async def failing_function():
            raise ConnectionError("Connection failed")

        # Open circuit
        with pytest.raises(ConnectionError):
            await breaker.call(failing_function)
        with pytest.raises(ConnectionError):
            await breaker.call(failing_function)

        assert breaker.state == CircuitState.OPEN

        # Manually reset
        breaker.reset()

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

        # Should now allow calls
        with pytest.raises(ConnectionError):
            await breaker.call(failing_function)

        assert breaker.state == CircuitState.CLOSED  # Only 1 failure so far

    @pytest.mark.asyncio
    async def test_circuit_only_counts_expected_exceptions(self):
        """Circuit should only count exceptions that match expected_exception."""
        breaker = CircuitBreaker(
            failure_threshold=2,
            expected_exception=ConnectionError,  # Only count ConnectionError
        )

        call_count = 0

        async def raise_connection_errors():
            """Only raises ConnectionError."""
            raise ConnectionError("Connection failed")

        async def raise_value_errors():
            """Only raises ValueError (shouldn't count)."""
            raise ValueError("Invalid value")

        # First call raises ConnectionError (counts as failure)
        with pytest.raises(ConnectionError):
            await breaker.call(raise_connection_errors)
        assert breaker.failure_count == 1
        assert breaker.state == CircuitState.CLOSED

        # Second call raises ValueError (doesn't count as failure)
        with pytest.raises(ValueError):
            await breaker.call(raise_value_errors)
        assert breaker.failure_count == 1  # Still 1
        assert breaker.state == CircuitState.CLOSED

        # Third call raises ConnectionError (opens circuit)
        with pytest.raises(ConnectionError):
            await breaker.call(raise_connection_errors)
        assert breaker.failure_count == 2
        assert breaker.state == CircuitState.OPEN


# ============================================================================
# Retry Tests
# ============================================================================

class TestRetry:
    """Test retry functionality."""

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_first_attempt(self):
        """Retry should return immediately if function succeeds."""
        retry_logic = Retry(max_attempts=3)

        async def successful_function():
            return "success"

        result = await retry_logic.call(successful_function)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self):
        """Retry should succeed if function succeeds on retry."""
        retry_logic = Retry(max_attempts=3)

        call_count = 0

        async def fails_then_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("Connection failed")
            return "success"

        result = await retry_logic.call(fails_then_succeeds)
        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_fails_after_max_attempts(self):
        """Retry should raise MaxRetriesExceededError after max attempts."""
        retry_logic = Retry(max_attempts=3)

        async def always_failing():
            raise ConnectionError("Connection failed")

        with pytest.raises(MaxRetriesExceededError) as exc_info:
            await retry_logic.call(always_failing)

        assert exc_info.value.func_name == "always_failing"
        assert exc_info.value.attempts == 3
        assert isinstance(exc_info.value.last_exception, ConnectionError)

    @pytest.mark.asyncio
    async def test_retry_with_fixed_backoff(self):
        """Retry should use fixed delay between attempts."""
        retry_logic = Retry(
            max_attempts=3,
            backoff=BackoffStrategy.fixed(delay=0.1),
        )

        call_times = []

        async def failing_function():
            call_times.append(asyncio.get_event_loop().time())
            raise ConnectionError("Connection failed")

        with pytest.raises(MaxRetriesExceededError):
            await retry_logic.call(failing_function)

        # Should have 3 calls with ~0.1s delay between them
        assert len(call_times) == 3
        delay_1 = call_times[1] - call_times[0]
        delay_2 = call_times[2] - call_times[1]
        assert 0.08 < delay_1 < 0.15  # Allow small timing variance
        assert 0.08 < delay_2 < 0.15

    @pytest.mark.asyncio
    async def test_retry_with_exponential_backoff(self):
        """Retry should use exponential delay between attempts."""
        retry_logic = Retry(
            max_attempts=4,
            backoff=BackoffStrategy.exponential(base_delay=0.1, max_delay=1.0, exponent=2.0),
        )

        call_times = []

        async def failing_function():
            call_times.append(asyncio.get_event_loop().time())
            raise ConnectionError("Connection failed")

        with pytest.raises(MaxRetriesExceededError):
            await retry_logic.call(failing_function)

        # Check exponential growth: 0.1, 0.2, 0.4 (capped at 1.0)
        assert len(call_times) == 4
        delay_1 = call_times[1] - call_times[0]
        delay_2 = call_times[2] - call_times[1]
        delay_3 = call_times[3] - call_times[2]

        assert 0.08 < delay_1 < 0.15  # ~0.1s
        assert 0.15 < delay_2 < 0.30  # ~0.2s
        assert 0.30 < delay_3 < 0.50  # ~0.4s

    @pytest.mark.asyncio
    async def test_retry_with_linear_backoff(self):
        """Retry should use linear delay between attempts."""
        retry_logic = Retry(
            max_attempts=4,
            backoff=BackoffStrategy.linear(base_delay=0.1, increment=0.1),
        )

        call_times = []

        async def failing_function():
            call_times.append(asyncio.get_event_loop().time())
            raise ConnectionError("Connection failed")

        with pytest.raises(MaxRetriesExceededError):
            await retry_logic.call(failing_function)

        # Check linear growth: 0.1, 0.2, 0.3
        assert len(call_times) == 4
        delay_1 = call_times[1] - call_times[0]
        delay_2 = call_times[2] - call_times[1]
        delay_3 = call_times[3] - call_times[2]

        assert 0.08 < delay_1 < 0.15  # ~0.1s
        assert 0.15 < delay_2 < 0.30  # ~0.2s
        assert 0.25 < delay_3 < 0.40  # ~0.3s

    @pytest.mark.asyncio
    async def test_retry_decorator(self):
        """Retry should work as a decorator."""
        @retry(max_attempts=3)
        async def protected_function():
            raise ConnectionError("Connection failed")

        with pytest.raises(MaxRetriesExceededError):
            await protected_function()

    @pytest.mark.asyncio
    async def test_retry_with_on_retry_callback(self):
        """Retry should call on_retry callback after each failure."""
        callback_calls = []

        async def on_retry_callback(attempt: int, exception: Exception):
            callback_calls.append((attempt, type(exception).__name__))

        retry_logic = Retry(
            max_attempts=3,
            on_retry=on_retry_callback,
        )

        async def failing_function():
            raise ConnectionError("Connection failed")

        with pytest.raises(MaxRetriesExceededError):
            await retry_logic.call(failing_function)

        # Should have called callback twice (after attempts 0 and 1)
        assert len(callback_calls) == 2
        assert callback_calls[0] == (0, "ConnectionError")
        assert callback_calls[1] == (1, "ConnectionError")

    @pytest.mark.asyncio
    async def test_retry_only_retries_expected_exceptions(self):
        """Retry should only retry for exceptions matching expected_exception."""
        retry_logic = Retry(
            max_attempts=3,
            expected_exception=ConnectionError,
        )

        call_count = 0

        async def raise_different_errors():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("Invalid value")  # Not retryable
            raise ConnectionError("Connection failed")

        # Should not retry on ValueError
        with pytest.raises(ValueError):
            await retry_logic.call(raise_different_errors)

        assert call_count == 1  # Only called once


# ============================================================================
# Combined Resilience Tests
# ============================================================================

class TestCombinedResilience:
    """Test combined circuit breaker + retry patterns."""

    @pytest.mark.asyncio
    async def test_resilient_decorator(self):
        """Resilient decorator should combine circuit breaker and retry."""
        @resilient(
            failure_threshold=3,
            recovery_timeout=60,
            max_attempts=2,
            backoff="exponential",
        )
        async def protected_function():
            raise ConnectionError("Connection failed")

        # Each call will be retried twice (max_attempts=2)
        # After 3 failed calls, circuit opens
        # Total attempts = 3 * 2 = 6 failures

        # First 2 calls should be retried (circuit stays closed)
        for _ in range(2):
            with pytest.raises(MaxRetriesExceededError):
                await protected_function()

        # 3rd call should open circuit after retries
        with pytest.raises(MaxRetriesExceededError):
            await protected_function()

        # 4th call should fail fast with circuit breaker open
        with pytest.raises(CircuitBreakerError):
            await protected_function()


# ============================================================================
# Fallback Tests
# ============================================================================

class TestFallback:
    """Test fallback pattern."""

    @pytest.mark.asyncio
    async def test_fallback_on_exception(self):
        """Fallback should be called when primary function raises exception."""
        async def primary_function():
            raise ConnectionError("Primary failed")

        async def fallback_function():
            return "fallback_value"

        decorated = with_fallback(
            fallback_function,
            on_exception=ConnectionError,
        )(primary_function)

        result = await decorated()
        assert result == "fallback_value"

    @pytest.mark.asyncio
    async def test_fallback_not_called_on_success(self):
        """Fallback should not be called when primary function succeeds."""
        async def primary_function():
            return "primary_value"

        async def fallback_function():
            return "fallback_value"

        decorated = with_fallback(
            fallback_function,
            on_exception=ConnectionError,
        )(primary_function)

        result = await decorated()
        assert result == "primary_value"

    @pytest.mark.asyncio
    async def test_fallback_with_sync_fallback_function(self):
        """Fallback should work with synchronous fallback function."""
        async def primary_function():
            raise ConnectionError("Primary failed")

        def sync_fallback():
            return "sync_fallback_value"

        decorated = with_fallback(
            sync_fallback,
            on_exception=ConnectionError,
        )(primary_function)

        result = await decorated()
        assert result == "sync_fallback_value"

    @pytest.mark.asyncio
    async def test_fallback_only_for_specified_exceptions(self):
        """Fallback should only trigger for specified exceptions."""
        async def primary_function():
            raise ValueError("Invalid value")

        async def fallback_function():
            return "fallback_value"

        decorated = with_fallback(
            fallback_function,
            on_exception=ConnectionError,  # Different exception
        )(primary_function)

        # Should raise ValueError, not use fallback
        with pytest.raises(ValueError):
            await decorated()


# ============================================================================
# Integration Tests
# ============================================================================

class TestResilienceIntegration:
    """Integration tests for resilience patterns."""

    @pytest.mark.asyncio
    async def test_full_resilience_stack(self):
        """Test full resilience stack with realistic scenario."""
        # Simulate external API that sometimes fails
        call_count = 0
        failure_count = 0

        @resilient(
            failure_threshold=3,
            recovery_timeout=0.2,
            max_attempts=2,
            backoff="exponential",
        )
        async def external_api_call():
            nonlocal call_count, failure_count
            call_count += 1

            # Fail first 4 actual API calls (not retries)
            # Each "top-level call" tries twice (max_attempts=2)
            # So call_count 1-2 = first attempt, 3-4 = second, etc.
            # We want first 2 top-level attempts to fail completely (4 calls)
            # Then succeed on 3rd attempt
            if call_count <= 4:
                failure_count += 1
                raise ConnectionError("API unavailable")

            return {"data": "success"}

        # First 2 top-level calls will be retried (circuit stays closed)
        # Each retries once, so 4 total failures
        for i in range(2):
            with pytest.raises(MaxRetriesExceededError):
                await external_api_call()

        # Circuit should still be closed (only 2 failures counted so far)
        # 3rd top-level call - first retry succeeds
        result = await external_api_call()
        assert result == {"data": "success"}

        # Verify call counts
        # 2 failed attempts * 2 retries = 4 failures
        # 1 successful attempt = 1 success (on second retry)
        assert call_count == 5
        assert failure_count == 4
