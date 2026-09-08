"""OpenTelemetry instruments for the Pi coding-agent pool.

Emits the three metrics documented in :mod:`mahavishnu.pools.pi_pool`'s
module docstring (REQ-PI observability contract from
``docs/plans/2026-09-07-pi-pool-backend.md`` §D1.5):

- ``mahavishnu.pi.tasks.executed`` — counter, labeled by ``status``
  (``completed`` / ``failed`` / ``timeout``).
- ``mahavishnu.pi.task.duration`` — histogram in seconds, no labels.
- ``mahavishnu.pi.heartbeat.missed_total`` — counter, no labels.

Pattern: matches :mod:`mahavishnu.core.events.observability` (module-level
``_meter`` + named instruments + thin helper API). The larger
:mod:`mahavishnu.observability.metrics` module's label-allowlist
machinery is intentionally NOT reused here — the PiPool metric surface
has bounded label cardinality (``status`` has exactly 3 values; the
duration histogram and heartbeat counter carry no labels), so the
allowlist guard adds ceremony without payoff. If Pi-pool cardinality
ever grows, lift the helper structure from
``mahavishnu.observability.metrics._validate_labels``.

Why lazy: OTel's ``opentelemetry.metrics.set_meter_provider`` is
documented as one-shot per process — once a real ``MeterProvider`` is
installed, subsequent ``set_meter_provider`` calls are silent no-ops
(logged as "Overriding of current MeterProvider is not allowed").
Eagerly creating instruments at import time would lock the module to
whatever provider is installed when ``pi_observability`` first
imports, breaking tests that install an ``InMemoryMetricReader``
fixture. The ``_get_*`` helpers resolve instruments on first call,
which lets the module-level meter proxy pick up whichever
``MeterProvider`` is active at the moment of the first emit.
"""

from __future__ import annotations

from functools import cache

from opentelemetry import metrics
from opentelemetry.metrics import (  # noqa: TC002 — used as runtime return annotations
    Counter,
    Histogram,
)


@cache
def _tasks_executed() -> Counter:
    return metrics.get_meter("mahavishnu.pi").create_counter(
        name="mahavishnu.pi.tasks.executed",
        description="Pi pool task outcomes, labeled by status (completed/failed/timeout).",
    )


@cache
def _task_duration() -> Histogram:
    return metrics.get_meter("mahavishnu.pi").create_histogram(
        name="mahavishnu.pi.task.duration",
        unit="s",
        description="Pi pool task duration in seconds (success and failure paths).",
    )


@cache
def _heartbeat_missed_total() -> Counter:
    return metrics.get_meter("mahavishnu.pi").create_counter(
        name="mahavishnu.pi.heartbeat.missed_total",
        description="Count of watchdog-detected heartbeat misses on the JSON-RPC stdio client.",
    )


def record_task_completed(duration_seconds: float) -> None:
    """Record a successful Pi task execution.

    Args:
        duration_seconds: Wall-clock duration of the task in seconds.
    """
    _tasks_executed().add(1, attributes={"status": "completed"})
    _task_duration().record(duration_seconds)


def record_task_failed(
    duration_seconds: float,
    *,
    timed_out: bool = False,
) -> None:
    """Record a failed Pi task execution (covers timeout and error paths).

    Args:
        duration_seconds: Wall-clock duration of the task in seconds.
        timed_out: When True, the failure was a timeout (RPC watchdog or
            explicit timeout); emits ``status="timeout"`` label. When
            False, the failure was a protocol/RPC error; emits
            ``status="failed"``.
    """
    status = "timeout" if timed_out else "failed"
    _tasks_executed().add(1, attributes={"status": status})
    _task_duration().record(duration_seconds)


def record_heartbeat_missed() -> None:
    """Record a single watchdog-detected heartbeat miss.

    Called from :meth:`JSONRPCStdioClient._watchdog_loop` when the
    inbound-frame interval exceeds ``heartbeat_interval *
    watchdog_timeout_multiplier``.
    """
    _heartbeat_missed_total().add(1)


# Exposed for tests that need to invalidate the lazy cache when
# installing a fresh MeterProvider between test cases.
def _reset_instrument_cache() -> None:
    """Clear the lazy instrument cache so the next emit re-resolves.

    Tests that install a new ``MeterProvider`` via
    ``metrics.set_meter_provider`` must call this *after* the swap so
    that subsequent emits rebind to the new provider. Production code
    should not call this — instrument caching is the whole point of
    lazy initialization.
    """
    _tasks_executed.cache_clear()
    _task_duration.cache_clear()
    _heartbeat_missed_total.cache_clear()


__all__ = [
    "_reset_instrument_cache",
    "record_heartbeat_missed",
    "record_task_completed",
    "record_task_failed",
]
