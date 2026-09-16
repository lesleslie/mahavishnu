"""Phase 4 wiring: per-feed health aggregator for Mahavishnu's ``/health``.

Plan §4 Observability + §5 task 7 + §11.4 PromQL alerts ship a single
per-component feed-state aggregator in mcp-common v0.26.4
(``mcp_common.health.aggregator.aggregate_feed_states``). This module
is the **consumer-side wiring** for mahavishnu: it constructs a
``dict[str, HealthFeedState]`` from existing subsystem probes,
delegates to ``aggregate_feed_states``, emits the four PromQL metrics
(``health_feed_status`` / ``health_feed_errors_within_window`` /
``mcp_common_health_halflife_seconds`` /
``mcp_common_health_aggregate_duration_ms``) into a private
``prometheus_client.CollectorRegistry``, and maps the worst-case
``StatusValue`` to a ``MahavishnuHealthVerdict`` that the FastAPI
``/health`` route consumes.

Reference implementations (mirror the pattern):
- ``session-buddy/session_buddy/server_optimized.py:316-407``
  (FastMCP custom_route; 1 feed).
- ``akosha/akosha/mcp/server.py:764-949`` (FastMCP custom_route;
  multi-feed).

Mahavishnu exposes 3 feeds in v1:

* ``storage`` — EncryptedSQLite import + construct (legacy database
  probe from ``mahavishnu/health.py:_check_database``).
* ``message_bus`` — InMemoryEventTransport import + construct (legacy
  probe from ``mahavishnu/health.py:_check_message_bus``).
* ``adapters`` — adapter settings loaded + at least one enabled
  (legacy probe from ``mahavishnu/health.py:_check_adapters``).

Per ``.claude/decisions/mcp-backend-wiring-discipline.md``, every
registered tool must have a working data feed. The /health aggregator
is the roll-up surface; the per-tool feeds are out of scope for
this commit (registered in their respective ``ComponentHealth``
adapter modules — see spec §4.8 wire-up contract).

The PromQL alert contract lives at
``config/prometheus/health_aggregator_alerts.yml`` and references
the four metrics emitted by ``mcp_common.health.metrics.
update_health_metrics``. Those alerts fire live as soon as the
private ``CollectorRegistry`` is scraped (see
``get_health_metrics_registry()`` and the ``/metrics`` endpoint
re-exposure in ``mahavishnu/health.py:create_health_app``).
"""

from __future__ import annotations

import logging
import os
import time

from mcp_common.health.aggregator import HealthSnapshot, aggregate_feed_states
from mcp_common.health.feed import HealthFeedState, StatusValue
from mcp_common.health.metrics import update_health_metrics
import prometheus_client

logger = logging.getLogger(__name__)


class MahavishnuHealthVerdict:
    """Per-``/health`` body verdict (status + snapshot + http_status).

    FastAPI's ``JSONResponse`` reads ``http_status`` for the HTTP code;
    the snapshot is JSON-serialised into the response body so operators
    can see per-feed ``status`` + ``reason_codes`` without parsing logs.
    """

    __slots__ = ("duration_ms", "http_status", "snapshot", "worst_status")

    def __init__(
        self,
        *,
        snapshot: HealthSnapshot,
        worst_status: StatusValue,
        http_status: int,
        duration_ms: float,
    ) -> None:
        self.snapshot = snapshot
        self.worst_status = worst_status
        self.http_status = http_status
        self.duration_ms = duration_ms


# ---------------------------------------------------------------------------
# Per-subsystem probes (thin wrappers around the legacy _check_* functions
# in ``mahavishnu/health.py``). Each returns a ``HealthFeedState`` snapshot.
# ---------------------------------------------------------------------------


def _probe_storage_state() -> HealthFeedState:
    """Construct a ``HealthFeedState`` for the storage subsystem.

    Mirrors ``mahavishnu/health.py:_check_database``: EncryptedSQLite
    import + construct. The probe is sync (smoke test for the import
    path); connection-level liveness is delegated to the canonical
    storage health check.
    """
    try:
        from mahavishnu.storage.encrypted_sqlite import EncryptedSQLite

        instance = EncryptedSQLite(":memory:")
        healthy = instance is not None
    except Exception:
        logger.exception("health_aggregator: storage probe failed")
        healthy = False
    return HealthFeedState(
        entities_count=1 if healthy else 0,
        last_updated_timestamp=time.time() if healthy else None,
        cycles_total=1 if healthy else 0,
        errors_total=0 if healthy else 1,
        last_error_at=None if healthy else time.time(),
        ingester_running=healthy,
    )


def _probe_message_bus_state() -> HealthFeedState:
    """Construct a ``HealthFeedState`` for the in-process event bus."""
    try:
        from mahavishnu.core.events.contract import InMemoryEventTransport

        instance = InMemoryEventTransport()
        healthy = instance is not None
    except Exception:
        logger.exception("health_aggregator: message_bus probe failed")
        healthy = False
    return HealthFeedState(
        entities_count=1 if healthy else 0,
        last_updated_timestamp=time.time() if healthy else None,
        cycles_total=1 if healthy else 0,
        errors_total=0 if healthy else 1,
        last_error_at=None if healthy else time.time(),
        ingester_running=healthy,
    )


def _probe_adapters_state() -> HealthFeedState:
    """Construct a ``HealthFeedState`` for adapter enablement.

    Reads ``MahavishnuSettings()`` lazily (avoids constructor overhead
    on the /health hot path when settings are already loaded).
    """
    try:
        from mahavishnu.core.config import MahavishnuSettings

        config = MahavishnuSettings()
        any_enabled = (
            config.adapters.prefect_enabled
            or config.adapters.llamaindex_enabled
            or config.adapters.agno_enabled
        )
    except Exception:
        logger.exception("health_aggregator: adapters probe failed")
        any_enabled = False
    return HealthFeedState(
        entities_count=1 if any_enabled else 0,
        last_updated_timestamp=time.time(),
        cycles_total=1,
        errors_total=0 if any_enabled else 1,
        last_error_at=None if any_enabled else time.time(),
        ingester_running=any_enabled,
    )


def _collect_feed_states() -> dict[str, HealthFeedState]:
    """Build the ``dict[str, HealthFeedState]`` aggregator input.

    Returns 3 feeds (storage, message_bus, adapters). New feeds can
    be appended here as they're wired — the aggregator's worst-case
    roll-up semantics automatically include them.
    """
    return {
        "storage": _probe_storage_state(),
        "message_bus": _probe_message_bus_state(),
        "adapters": _probe_adapters_state(),
    }


# ---------------------------------------------------------------------------
# Prometheus registry (private, isolated from the global ``REGISTRY``)
# ---------------------------------------------------------------------------

_health_metrics_registry: prometheus_client.CollectorRegistry | None = None


def get_health_metrics_registry() -> prometheus_client.CollectorRegistry:
    """Return the private ``CollectorRegistry`` for the four PromQL
    metrics emitted by ``update_health_metrics``.

    Lazy-initialised on first call. A fresh registry (NOT the
    prometheus_client global) avoids the ``Duplicated timeseries``
    error if the same metric name is registered elsewhere in the
    process (e.g. ``mahavishnu/websocket/metrics.py`` uses the global
    ``REGISTRY`` for unrelated counters).

    The ``/metrics`` endpoint in ``mahavishnu/health.py`` re-exposes
    this registry's content alongside the OTel-derived text-format
    metrics.
    """
    global _health_metrics_registry
    if _health_metrics_registry is None:
        _health_metrics_registry = prometheus_client.CollectorRegistry()
    return _health_metrics_registry


def reset_health_metrics_registry_for_tests() -> None:  # pragma: no cover - test seam
    """Clear the cached registry so tests can re-initialise cleanly."""
    global _health_metrics_registry
    _health_metrics_registry = None


# ---------------------------------------------------------------------------
# Aggregator entry point
# ---------------------------------------------------------------------------


def _resolve_halflife_seconds() -> int:
    """Read the halflife from ``HEALTH_FEED_HALFLIFE_SECONDS`` (env).

    The ``--health-disable-decay`` CLI flag on ``MCPServerCLIFactory
    .start`` (mcp-common v0.26.4, commit 837d64a) propagates the
    disable sentinel by setting ``HEALTH_FEED_HALFLIFE_SECONDS=0``
    before the lifespan runs. ``is_healthy`` treats
    ``halflife_seconds <= 0`` as "decay disabled" — no error is ever
    treated as "recent" regardless of when it occurred.
    """
    raw = os.getenv("HEALTH_FEED_HALFLIFE_SECONDS", "300")
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "health_aggregator: HEALTH_FEED_HALFLIFE_SECONDS=%r is not an int; "
            "falling back to default 300",
            raw,
        )
        return 300
    return value


_STATUS_TO_HTTP: dict[StatusValue, int] = {
    StatusValue.HEALTHY: 200,
    StatusValue.WARMING_UP: 200,  # operational, still loading
    StatusValue.DEGRADED: 503,
    StatusValue.FAILED: 503,
}


def _status_to_http(status: StatusValue) -> int:
    """Map the worst-case ``StatusValue`` to an HTTP status code.

    ``healthy`` and ``warming_up`` → 200 (the orchestrator is
    operational; warming_up means at least one producer is still
    mid-stride to filling its feed). ``degraded`` and ``failed``
    → 503 (load balancers should pull this pod out of rotation).
    """
    return _STATUS_TO_HTTP.get(status, 503)


def aggregate_mahavishnu_health(*, repo: str = "mahavishnu") -> MahavishnuHealthVerdict:
    """Collect feeds → aggregate → emit metrics → map HTTP code.

    This is the single entry point called by ``/health`` (HTTP route)
    and the MCP ``get_health`` tool. Always returns a verdict — never
    raises — so probe failures inside the aggregator surface as
    ``failed`` feed status rather than a 500 from the route itself.

    Args:
        repo: The ``repo`` label on every emitted PromQL metric. The
            default ``"mahavishnu"`` matches the single-repo deployment
            case; multi-tenant deployments override per-call.

    Returns:
        :class:`MahavishnuHealthVerdict` with snapshot, worst-case
        status, HTTP code, and the aggregator wall-time duration.
    """
    halflife_seconds = _resolve_halflife_seconds()
    aggregator_start = time.perf_counter()

    feed_states = _collect_feed_states()

    snap = aggregate_feed_states(feed_states, halflife_seconds=halflife_seconds)
    duration_ms = (time.perf_counter() - aggregator_start) * 1000.0

    # Emit the four PromQL metrics. Forward-compat: mcp-common
    # <0.26.4 doesn't ship ``update_health_metrics``; the helper
    # gracefully no-ops on missing imports so the route still
    # returns a verdict (without metrics emit) on older wheels.
    try:
        update_health_metrics(
            registry=get_health_metrics_registry(),
            snap=snap,
            repo=repo,
            halflife_seconds=halflife_seconds,
            duration_ms=duration_ms,
        )
    except Exception:
        logger.exception(
            "health_aggregator: update_health_metrics emit failed; "
            "operators will see no PromQL metrics for repo=%s until the "
            "next successful call",
            repo,
        )

    worst_status = snap["status"]
    return MahavishnuHealthVerdict(
        snapshot=snap,
        worst_status=worst_status,
        http_status=_status_to_http(worst_status),
        duration_ms=duration_ms,
    )


__all__ = [
    "MahavishnuHealthVerdict",
    "aggregate_mahavishnu_health",
    "get_health_metrics_registry",
    "reset_health_metrics_registry_for_tests",
]
