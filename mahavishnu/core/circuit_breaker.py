"""Compatibility shim for the shared resilience circuit breaker."""

from __future__ import annotations

from mahavishnu.core.resilience import CircuitBreaker, CircuitState, circuit_breaker

__all__ = ["CircuitBreaker", "CircuitState", "circuit_breaker"]
