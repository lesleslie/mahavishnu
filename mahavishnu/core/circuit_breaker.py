"""Circuit breaker implementation for Mahavishnu."""

import asyncio
from collections.abc import Callable
from datetime import datetime
from enum import Enum
import logging
from typing import Any


class CircuitState(Enum):
    """Possible states of the circuit breaker."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Tripped, requests blocked
    HALF_OPEN = "half_open"  # Testing if failure condition is resolved


class CircuitBreaker:
    """Circuit breaker for failing services."""

    def __init__(self, threshold: int = 5, timeout: int = 60, reset_timeout: int = 60):
        """
        Initialize circuit breaker.

        Args:
            threshold: Number of failures before opening circuit (default 5)
            timeout: Time in seconds to keep circuit open (default 60)
            reset_timeout: Time in seconds to attempt reset (default 60)
        """
        self.threshold = threshold
        self.timeout = timeout
        self.reset_timeout = reset_timeout

        self.failure_count = 0
        self.state = CircuitState.CLOSED
        self.last_failure_time = None
        self.logger = logging.getLogger(__name__)

    def record_failure(self):
        """Record a failure and potentially open circuit."""
        self.failure_count += 1
        self.last_failure_time = datetime.now()

        if self.failure_count >= self.threshold and self.state != CircuitState.OPEN:
            self.state = CircuitState.OPEN
            self.logger.warning(f"Circuit breaker opened after {self.failure_count} failures")

    def record_success(self):
        """Record a success and reset failure count."""
        self.failure_count = 0
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            self.logger.info("Circuit breaker closed after successful request")

    def allow_request(self) -> bool:
        """Check if request is allowed.

        Returns:
            True if request is allowed, False otherwise
        """
        if self.state == CircuitState.CLOSED:
            return True
        elif self.state == CircuitState.OPEN:
            # Check if timeout has elapsed
            if (datetime.now() - self.last_failure_time).seconds > self.timeout:
                self.state = CircuitState.HALF_OPEN
                self.logger.info("Circuit breaker transitioning to half-open for test")
                return True
            return False
        elif self.state == CircuitState.HALF_OPEN:
            return True

        return False  # Default to deny if in unknown state

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Call a function with circuit breaker protection.

        Args:
            func: Function to call
            *args: Arguments to pass to function
            **kwargs: Keyword arguments to pass to function

        Returns:
            Result of function call

        Raises:
            Exception: If circuit breaker is open or function fails
        """
        if not self.allow_request():
            raise Exception(f"Circuit breaker is {self.state.value}, request denied")

        try:
            result = (
                await func(*args, **kwargs)
                if asyncio.iscoroutinefunction(func)
                else func(*args, **kwargs)
            )
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise e


# Decorator version for easy use
def circuit_breaker(threshold: int = 5, timeout: int = 60, reset_timeout: int = 60):
    """Decorator to apply circuit breaker pattern to a function."""
    cb = CircuitBreaker(threshold, timeout, reset_timeout)

    def decorator(func):
        async def async_wrapper(*args, **kwargs):
            return await cb.call(func, *args, **kwargs)

        def sync_wrapper(*args, **kwargs):
            return cb.call(func, *args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator
