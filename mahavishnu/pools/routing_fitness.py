"""Routing fitness signals read from Dhara.

Provides `FitnessSignal` (data) and `RoutingFitnessReader` which reads signals
from Dhara's `routing_fitness/{task_class}/{selector}` keyspace and selects the
best-performing selector for a given task class.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

logger = __import__("logging").getLogger(__name__)

# UTC-aware datetime helper (avoids compat imports where not needed)
_KEY_COMPONENT_RE = re.compile(r"^[a-zA-Z0-9_]{1,50}$")
_INVALID_KEY_PLACEHOLDER = "unknown"


def _sanitize_key_component(value: str) -> str:
    """Sanitize a key path component to prevent path injection.

    Dhara key paths use '/' as separator. Only alphanumeric + underscore
    (max 50 chars) are allowed in path components.
    """
    if _KEY_COMPONENT_RE.match(value):
        return value
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", value)[:50]
    return sanitized if sanitized else _INVALID_KEY_PLACEHOLDER


@dataclass
class FitnessSignal:
    """Fitness signal for a (task_class, selector) pair.

    Attributes:
        score: 1 - failure_rate (higher = better, range [0.0, 1.0])
        samples: Number of routing decisions in the rolling window
        failure_rate: Fraction of decisions where outcome == "error"
        p99_latency_ms: 99th percentile task duration in milliseconds
        updated_at: ISO timestamp of last update
        window_start: ISO timestamp of rolling window start
        component_count: How many Bodai components contributed traces
    """

    score: float = 0.0
    samples: int = 0
    failure_rate: float = 0.0
    p99_latency_ms: float = 0.0
    updated_at: str = ""
    window_start: str = ""
    component_count: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FitnessSignal:
        """Reconstruct from a Dhara value dict."""
        return cls(
            score=float(data.get("score", 0.0)),
            samples=int(data.get("samples", 0)),
            failure_rate=float(data.get("failure_rate", 0.0)),
            p99_latency_ms=float(data.get("p99_latency_ms", 0.0)),
            updated_at=str(data.get("updated_at", "")),
            window_start=str(data.get("window_start", "")),
            component_count=int(data.get("component_count", 0)),
        )


class RoutingFitnessReader:
    """Reads routing fitness signals from Dhara.

    Uses DharaStateBackend.list_prefix() to fetch all signals for a given
    task_class and returns them keyed by selector name.

    The caller is responsible for providing a properly-configured
    DharaStateBackend instance (or None for graceful degradation).
    """

    def __init__(self, dhara_state: Any | None = None) -> None:
        """Initialize reader.

        Args:
            dhara_state: DharaStateBackend instance; may be None for fallback-only
                         operation (always returns empty results).
        """
        self._dhara_state = dhara_state

    async def get_fitness_signals(self, task_class: str) -> dict[str, FitnessSignal]:
        """Return fitness signals for all selectors for a task class.

        Args:
            task_class: Task classification string (e.g. "code_generation")

        Returns:
            Dict mapping selector name (e.g. "least_loaded") → FitnessSignal.
            Returns empty dict if Dhara is unavailable or no signals exist.
        """
        if self._dhara_state is None:
            return {}

        safe_task_class = _sanitize_key_component(task_class)
        prefix = f"routing_fitness/{safe_task_class}/"
        try:
            entries = await self._dhara_state.list_prefix(prefix)
        except Exception as exc:
            logger.debug("Failed to list_prefix(%r) from Dhara: %s", prefix, exc)
            return {}

        signals: dict[str, FitnessSignal] = {}
        for key, value in entries:
            # Key format: routing_fitness/{task_class}/{selector}
            parts = key.rsplit("/", 2)
            if len(parts) >= 3:
                selector = parts[-1]
                if selector:
                    try:
                        signals[selector] = FitnessSignal.from_dict(value)
                    except Exception as exc:
                        logger.debug("Failed to parse fitness signal at %r: %s", key, exc)

        return signals

    async def get_best_selector(self, task_class: str) -> str | None:
        """Return the selector with the highest fitness score for a task class.

        Args:
            task_class: Task classification string.

        Returns:
            Selector name with highest score, or None if no signals available.
        """
        signals = await self.get_fitness_signals(task_class)
        if not signals:
            return None

        best_selector: str | None = None
        best_score = float("-inf")
        for selector, signal in signals.items():
            if signal.score > best_score:
                best_score = signal.score
                best_selector = selector
        return best_selector
