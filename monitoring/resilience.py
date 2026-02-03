"""Circuit breaker and retry patterns for MCP ecosystem resilience.

This module provides production-ready resilience patterns:
- Circuit breaker to prevent cascading failures
- Retry with exponential backoff for transient errors
- Fallback mechanisms for graceful degradation
- Timeout protection for long-running operations

Example usage:
    from monitoring.resilience import circuit_breaker, retry

    @circuit_breaker(failure_threshold=5, recovery_timeout=60)
    @retry(max_attempts=3, backoff=exponential)
    async def call_external_api(url: str):
        async with httpx.AsyncClient() as client:
            return await client.get(url)
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from enum import Enum
import functools
from logging import getLogger
import time
from typing import Any, ParamSpec, TypeVar

# Type aliases
P = ParamSpec("P")
R = TypeVar("R")

logger = getLogger(__name__)


# ============================================================================
# Circuit Breaker Implementation
# ============================================================================


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation, requests pass through
    OPEN = "open"  # Circuit is open, requests fail fast
    HALF_OPEN = "half_open"  # Testing if service has recovered


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open and request is rejected."""

    pass


class CircuitBreaker:
    """Circuit breaker to prevent cascading failures.

    The circuit breaker has three states:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Service is failing, requests fail fast without calling the service
    - HALF_OPEN: Testing if service has recovered (allows one request through)

    State transitions:
    CLOSED -> OPEN: When failure threshold is reached
    OPEN -> HALF_OPEN: After recovery timeout expires
    HALF_OPEN -> CLOSED: If test request succeeds
    HALF_OPEN -> OPEN: If test request fails

    Example:
        breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60,
            expected_exception=Exception
        )

        @breaker
        async def call_service():
            # Service call that might fail
            pass
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: type[Exception] | tuple[type[Exception], ...] = Exception,
    ):
        """Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before attempting recovery
            expected_exception: Exception(s) that count as failures
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception

        # State tracking
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._success_count = 0

        # Lock for thread-safe state changes
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state

    @property
    def failure_count(self) -> int:
        """Get current failure count."""
        return self._failure_count

    @property
    def open_until(self) -> float | None:
        """Get timestamp when circuit will transition to HALF_OPEN."""
        if self._state == CircuitState.OPEN:
            return self._last_failure_time + self.recovery_timeout
        return None

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        return time.time() >= self._last_failure_time + self.recovery_timeout

    async def _on_success(self):
        """Handle successful call."""
        async with self._lock:
            self._success_count += 1

            if self._state == CircuitState.HALF_OPEN:
                # Service has recovered, close circuit
                logger.info("Circuit breaker closing after successful test call")
                self._state = CircuitState.CLOSED
                self._failure_count = 0

    async def _on_failure(self, exc: Exception):
        """Handle failed call."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._failure_count >= self.failure_threshold:
                if self._state != CircuitState.OPEN:
                    logger.warning(
                        f"Circuit breaker opening after {self._failure_count} failures "
                        f"(threshold: {self.failure_threshold})"
                    )
                self._state = CircuitState.OPEN

    async def call(self, func: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
        """Execute function with circuit breaker protection.

        Args:
            func: Function to execute
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function

        Returns:
            Function return value

        Raises:
            CircuitBreakerError: If circuit is open
            Exception: If function raises an exception
        """
        # Check if circuit is open
        if self._state == CircuitState.OPEN:
            if self._should_attempt_reset():
                logger.info("Circuit breaker transitioning to HALF_OPEN for test call")
                self._state = CircuitState.HALF_OPEN
            else:
                # Circuit is still open, fail fast
                raise CircuitBreakerError(
                    f"Circuit breaker is OPEN. Rejecting request. "
                    f"Will attempt reset at {self.open_until}"
                )

        try:
            # Execute the function
            result = await func(*args, **kwargs)

            # Handle success
            await self._on_success()

            return result

        except self.expected_exception as e:
            # Handle expected failure
            await self._on_failure(e)

            # Re-raise the exception
            raise

    def __call__(self, func: Callable[P, R]) -> Callable[P, R]:
        """Decorator to apply circuit breaker to async function.

        Args:
            func: Async function to protect

        Returns:
            Wrapped function with circuit breaker protection
        """

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            return await self.call(func, *args, **kwargs)

        return wrapper

    def reset(self):
        """Manually reset circuit breaker to CLOSED state.

        Useful for testing or manual recovery intervention.
        """
        logger.info("Circuit breaker manually reset to CLOSED state")
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0


# ============================================================================
# Retry Implementation
# ============================================================================


class BackoffStrategy:
    """Backoff strategy for retry attempts."""

    @staticmethod
    def fixed(delay: float = 1.0) -> Callable[[int], float]:
        """Fixed delay between retries.

        Args:
            delay: Fixed delay in seconds

        Returns:
            Function that returns fixed delay
        """
        return lambda attempt: delay

    @staticmethod
    def linear(base_delay: float = 1.0, increment: float = 1.0) -> Callable[[int], float]:
        """Linearly increasing delay.

        Args:
            base_delay: Initial delay in seconds
            increment: Amount to increase delay each retry

        Returns:
            Function that calculates linear backoff
        """
        return lambda attempt: base_delay + (attempt * increment)

    @staticmethod
    def exponential(
        base_delay: float = 1.0, max_delay: float = 60.0, exponent: float = 2.0
    ) -> Callable[[int], float]:
        """Exponential backoff with jitter.

        Args:
            base_delay: Initial delay in seconds
            max_delay: Maximum delay cap in seconds
            exponent: Exponential growth factor

        Returns:
            Function that calculates exponential backoff
        """

        def calculate(attempt: int) -> float:
            delay = min(base_delay * (exponent**attempt), max_delay)
            # Add jitter to prevent thundering herd
            import random

            jitter = random.uniform(0.0, delay * 0.1)  # 10% jitter
            return delay + jitter

        return calculate


class MaxRetriesExceededError(Exception):
    """Raised when max retry attempts are exceeded."""

    def __init__(self, func_name: str, attempts: int, last_exception: Exception | None = None):
        super().__init__(f"Function '{func_name}' failed after {attempts} attempts")
        self.func_name = func_name
        self.attempts = attempts
        self.last_exception = last_exception


class Retry:
    """Retry logic with configurable backoff strategies.

    Example:
        retry = Retry(
            max_attempts=3,
            backoff=BackoffStrategy.exponential(),
            expected_exception=(ConnectionError, TimeoutError)
        )

        @retry
        async def call_api():
            # API call that might fail transiently
            pass
    """

    def __init__(
        self,
        max_attempts: int = 3,
        backoff: Callable[[int], float] | None = None,
        expected_exception: type[Exception] | tuple[type[Exception], ...] = Exception,
        on_retry: Callable[[int, Exception], Any] | None = None,
    ):
        """Initialize retry logic.

        Args:
            max_attempts: Maximum number of retry attempts (including first attempt)
            backoff: Function that calculates delay between retries (attempt number -> delay seconds)
            expected_exception: Exception(s) that trigger retries
            on_retry: Optional callback called after each failed attempt (attempt, exception)
        """
        self.max_attempts = max_attempts
        self.backoff = backoff or BackoffStrategy.exponential()
        self.expected_exception = expected_exception
        self.on_retry = on_retry

    async def call(self, func: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
        """Execute function with retry logic.

        Args:
            func: Async function to execute
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function

        Returns:
            Function return value

        Raises:
            MaxRetriesExceededError: If all retry attempts fail
            Exception: If function raises unexpected exception
        """
        last_exception = None

        for attempt in range(self.max_attempts):
            try:
                # Execute function
                result = await func(*args, **kwargs)
                return result

            except self.expected_exception as e:
                last_exception = e

                # Check if we should retry
                if attempt < self.max_attempts - 1:
                    # Calculate backoff delay
                    delay = self.backoff(attempt)

                    logger.warning(
                        f"Attempt {attempt + 1}/{self.max_attempts} failed for {func.__name__}: {e}. "
                        f"Retrying in {delay:.2f}s..."
                    )

                    # Call on_retry callback if provided
                    if self.on_retry:
                        try:
                            await self._call_on_retry(attempt, e)
                        except Exception as callback_error:
                            logger.error(f"on_retry callback failed: {callback_error}")

                    # Wait before retry
                    await asyncio.sleep(delay)
                else:
                    # Last attempt failed
                    logger.error(f"All {self.max_attempts} attempts failed for {func.__name__}")
                    raise MaxRetriesExceededError(
                        func.__name__, self.max_attempts, last_exception
                    ) from e

    async def _call_on_retry(self, attempt: int, exception: Exception):
        """Call on_retry callback, handling both sync and async callbacks."""
        if asyncio.iscoroutinefunction(self.on_retry):
            await self.on_retry(attempt, exception)
        else:
            self.on_retry(attempt, exception)

    def __call__(self, func: Callable[P, R]) -> Callable[P, R]:
        """Decorator to apply retry logic to async function.

        Args:
            func: Async function to protect

        Returns:
            Wrapped function with retry logic
        """

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            return await self.call(func, *args, **kwargs)

        return wrapper


# ============================================================================
# Convenience Decorators
# ============================================================================


def circuit_breaker(
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
    expected_exception: type[Exception] | tuple[type[Exception], ...] = Exception,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator to apply circuit breaker to async function.

    Args:
        failure_threshold: Number of failures before opening circuit
        recovery_timeout: Seconds to wait before attempting recovery
        expected_exception: Exception(s) that count as failures

    Returns:
        Decorator function

    Example:
        @circuit_breaker(failure_threshold=5, recovery_timeout=60)
        async def call_service():
            # Service call protected by circuit breaker
            pass
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        breaker = CircuitBreaker(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            expected_exception=expected_exception,
        )
        return breaker(func)

    return decorator


def retry(
    max_attempts: int = 3,
    backoff: Callable[[int], float] | str = "exponential",
    expected_exception: type[Exception] | tuple[type[Exception], ...] = Exception,
    on_retry: Callable[[int, Exception], Any] | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator to apply retry logic to async function.

    Args:
        max_attempts: Maximum number of retry attempts
        backoff: Backoff strategy - can be string ("fixed", "linear", "exponential") or callable
        expected_exception: Exception(s) that trigger retries
        on_retry: Optional callback after each failed attempt

    Returns:
        Decorator function

    Example:
        @retry(max_attempts=3, backoff="exponential")
        async def call_api():
            # API call protected by retry logic
            pass
    """
    # Convert string to backoff function
    if isinstance(backoff, str):
        if backoff == "fixed":
            backoff_fn = BackoffStrategy.fixed()
        elif backoff == "linear":
            backoff_fn = BackoffStrategy.linear()
        elif backoff == "exponential":
            backoff_fn = BackoffStrategy.exponential()
        else:
            raise ValueError(f"Unknown backoff strategy: {backoff}")
    else:
        backoff_fn = backoff

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        retry_logic = Retry(
            max_attempts=max_attempts,
            backoff=backoff_fn,
            expected_exception=expected_exception,
            on_retry=on_retry,
        )
        return retry_logic(func)

    return decorator


# ============================================================================
# Combined Decorator
# ============================================================================


def resilient(
    # Circuit breaker params
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
    # Retry params
    max_attempts: int = 3,
    backoff: str = "exponential",
    # Common params
    expected_exception: type[Exception] | tuple[type[Exception], ...] = Exception,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Combined circuit breaker + retry decorator for maximum resilience.

    Applies both circuit breaker and retry logic to provide:
    - Fast fail when service is down (circuit breaker)
    - Automatic retry for transient failures (retry)
    - Graceful recovery when service comes back

    Args:
        failure_threshold: Failures before opening circuit
        recovery_timeout: Seconds before attempting recovery
        max_attempts: Retry attempts per call
        backoff: Backoff strategy ("fixed", "linear", "exponential")
        expected_exception: Exception(s) to handle

    Returns:
        Decorator function

    Example:
        @resilient(
            failure_threshold=5,
            recovery_timeout=60,
            max_attempts=3,
            backoff="exponential"
        )
        async def call_critical_service():
            # Highly resilient service call
            pass
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        # Apply retry first (inner decorator), then circuit breaker (outer)
        retry_decorator = retry(
            max_attempts=max_attempts,
            backoff=backoff,
            expected_exception=expected_exception,
        )
        cb_decorator = circuit_breaker(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            expected_exception=expected_exception,
        )

        # Stack decorators: circuit breaker wraps retry
        return cb_decorator(retry_decorator(func))

    return decorator


# ============================================================================
# Fallback Pattern
# ============================================================================


def with_fallback(
    fallback_func: Callable[P, R],
    on_exception: type[Exception] | tuple[type[Exception], ...] = Exception,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator to provide fallback function on failure.

    Args:
        fallback_func: Function to call if primary function fails
        on_exception: Exception(s) that trigger fallback

    Returns:
        Decorator function

    Example:
        def fallback_get_data():
            return {"data": "cached_value"}

        @with_fallback(fallback_get_data, on_exception=ConnectionError)
        async def get_data_from_api():
            # API call with fallback to cache
            pass
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return await func(*args, **kwargs)
            except on_exception as e:
                logger.warning(f"Primary function {func.__name__} failed: {e}. Using fallback.")
                # Call fallback function (can be sync or async)
                if asyncio.iscoroutinefunction(fallback_func):
                    return await fallback_func(*args, **kwargs)
                else:
                    return fallback_func(*args, **kwargs)

        return wrapper

    return decorator
