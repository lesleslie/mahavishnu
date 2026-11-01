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

Per ``docs/decisions/mcp-backend-wiring-discipline.md``, every
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

from datetime import UTC, datetime
import logging
import os
import time
from typing import TYPE_CHECKING, Any

from mcp_common.health.aggregator import HealthSnapshot, aggregate_feed_states
from mcp_common.health.feed import HealthFeedState, StatusValue
from mcp_common.health.metrics import update_health_metrics
import prometheus_client

if TYPE_CHECKING:
    from collections.abc import Mapping

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

    The substrate was rewired off the decommissioned ``EncryptedSQLite``
    onto the server's own process-local KV
    (:mod:`mahavishnu.core.kv_store`), which backs the
    ``mahavishnu_kv_*`` MCP tools and the substrate facade that the
    server's own producers — the ecosystem registry, the workflow
    outcome log, the approval decision log, the webhook ingress log —
    write through.

    Probing ``EncryptedSQLite`` instead made the whole service report
    degraded on any host that did not set ``SQLCIPHER_KEY`` — a key
    the running server never needs, because the class it guarded has
    no production consumer left.

    The probe reads the live singleton and counts its records, so
    ``entities_count`` describes the feed rather than the probe.
    """
    try:
        from mahavishnu.core.kv_store import kv_store

        entities = kv_store.count()
        healthy = True
    except Exception:
        logger.exception("health_aggregator: storage probe failed")
        entities = 0
        healthy = False
    return HealthFeedState(
        entities_count=entities if healthy else 0,
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

    Phase 1.1 (B1 refuter-review fix): the per-adopter default is
    60s, not the mcp-common default of 300s. Per
    ``docs/plans/2026-10-09-mcp-health-check-enrichment.md`` §1
    Outcome, every Bodai core repo overrides ``HEALTH_FEED_HALFLIFE_SECONDS``
    to 60s so a feed that has been broken-before-first-success OR
    errors-accumulating for >60s is flagged DEGRADED and the
    ``/health`` route returns 503. The 60s halflife is the soft
    rollout — fresh servers recover before any operator notices.
    """
    raw = os.getenv("HEALTH_FEED_HALFLIFE_SECONDS", "60")
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "health_aggregator: HEALTH_FEED_HALFLIFE_SECONDS=%r is not an int; "
            "falling back to default 60",
            raw,
        )
        return 60
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

    # Phase 1.1 (M2 polish): also emit the per-server
    # ``mahavishnu_health_feed_status{feed, status}`` gauge from
    # ``mahavishnu.observability.prometheus_metrics`` so dashboards
    # can target the mahavishnu view directly without PromQL
    # filtering on ``{repo="mahavishnu"}``. The canonical
    # mcp-common metric above is the source of truth for the
    # alerts; this M2 gauge is a server-specific convenience view.
    # The M2 gauge shares the aggregator's private registry so the
    # ``/metrics`` route exposes it on the same scrape surface as
    # the canonical mcp-common metrics (no separate registry
    # plumbing required).
    try:
        from mahavishnu.observability.prometheus_metrics import (
            update_health_feed_status_metrics,
        )

        update_health_feed_status_metrics(
            snap=snap,
            registry=get_health_metrics_registry(),
        )
    except Exception:
        logger.exception(
            "health_aggregator: M2 mahavishnu_health_feed_status emit failed; "
            "operators will see no per-server gauge until the next "
            "successful call",
        )

    worst_status = snap["status"]
    return MahavishnuHealthVerdict(
        snapshot=snap,
        worst_status=worst_status,
        http_status=_status_to_http(worst_status),
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# The one /health body
# ---------------------------------------------------------------------------

#: Severity order for the canonical status enum. Used to fold a
#: component check's failure into the overall verdict without losing
#: the aggregator's own worst status.
_STATUS_SEVERITY: dict[str, int] = {
    StatusValue.HEALTHY.value: 0,
    StatusValue.WARMING_UP.value: 1,
    StatusValue.DEGRADED.value: 2,
    StatusValue.FAILED.value: 3,
}

#: Canonical status -> the legacy v1 status string the health body's
#: ``status`` field has always carried. ``warming_up`` folds into
#: ``healthy`` because the orchestrator is operational while its
#: producers fill their feeds -- that distinction lives in
#: ``canonical_status`` / ``worst_status``, which keep the precise
#: canonical value. The MCP ``get_health`` tool's contract depends on
#: this mapping, so it is preserved here rather than folded away.
_STATUS_TO_LEGACY: dict[str, str] = {
    StatusValue.HEALTHY.value: "healthy",
    StatusValue.WARMING_UP.value: "healthy",
    StatusValue.DEGRADED.value: "degraded",
    StatusValue.FAILED.value: "unhealthy",
}


def _normalise_component_check(check: Mapping[str, Any]) -> dict[str, Any]:
    """Give a component check the same field vocabulary as a data feed.

    The canonical ``FeedSnapshot`` carries ``status`` / ``healthy`` /
    ``reason_codes``; the MCP-local checks (skills_signer, plan_index,
    task_orphan_sweeper) carry ``ok`` / ``status``. Merging them into
    one ``checks`` dict only reads well if every entry answers the same
    three questions, so the missing ones are filled in here.
    """
    normalised: dict[str, Any] = dict(check)
    ok = bool(normalised.get("ok", True))
    raw_status = str(normalised.get("status", ""))
    if raw_status in _STATUS_SEVERITY:
        status = raw_status
    else:
        # The MCP-local feeds speak the ``ok`` boolean plus the 4-signal
        # ``feed_*`` contract; they carry no canonical status string.
        status = StatusValue.HEALTHY.value if ok else StatusValue.DEGRADED.value
    normalised["ok"] = ok
    normalised["status"] = status
    normalised["healthy"] = ok
    normalised.setdefault("reason_codes", [])
    return normalised


def build_mahavishnu_health_body(
    *,
    repo: str = "mahavishnu",
    service_name: str = "mahavishnu",
    version: str = "unknown",
    uptime_seconds: float = 0.0,
    component_checks: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any], int]:
    """Build the one ``/health`` body every surface serves.

    This is the single source of truth behind the HTTP ``GET /health``
    route on the MCP server's port and the MCP ``get_health`` tool.
    Both surfaces used to be independent implementations: the route
    hand-rolled a check set from the signer / plan-index / sweeper
    feeds and never called the canonical aggregator, while the tool
    called :func:`aggregate_mahavishnu_health`. One process could
    therefore answer HTTP 200 ``"ok"`` and MCP 503 ``"degraded"`` at
    the same instant. Per
    ``docs/decisions/mcp-backend-wiring-discipline.md`` that
    disagreement is a bug.

    The canonical aggregator owns the three subsystem feeds (storage,
    message_bus, adapters). ``component_checks`` carries the
    MCP-local feeds the aggregator does not own; they are merged into
    the same ``checks`` dict, and a failing component check escalates
    the overall verdict to ``degraded``.

    Args:
        repo: Label for the emitted PromQL metrics. Stable component
            name (``"mahavishnu"``), matching the fleet convention —
            not a display name from settings.
        service_name: Value of the body's ``service`` field.
        version: Value of the body's ``version`` field.
        uptime_seconds: Seconds since process start.
        component_checks: MCP-local feed checks to merge in.

    Returns:
        ``(body, http_status)``. The HTTP status is 200 for
        ``healthy``/``warming_up`` and 503 for ``degraded``/``failed``.
    """
    verdict = aggregate_mahavishnu_health(repo=repo)

    canonical_checks: dict[str, dict[str, Any]] = {
        feed_name: {
            "status": feed_snapshot["status"].value,
            "healthy": feed_snapshot["healthy"],
            "reason_codes": [rc.value for rc in feed_snapshot["reason_codes"]],
            "entities_count": feed_snapshot["entities_count"],
            "last_updated_timestamp": feed_snapshot["last_updated_timestamp"],
            "cycles_total": feed_snapshot["cycles_total"],
            "errors_total": feed_snapshot["errors_total"],
        }
        for feed_name, feed_snapshot in verdict.snapshot["checks"].items()
    }
    reason_codes = [rc.value for rc in verdict.snapshot["reason_codes"]]
    canonical_status = verdict.worst_status.value

    checks: dict[str, dict[str, Any]] = dict(canonical_checks)
    overall = canonical_status
    for name, raw in (component_checks or {}).items():
        normalised = _normalise_component_check(raw)
        checks[name] = normalised
        if not normalised["ok"]:
            # A failing component check degrades the verdict, but never
            # softens one the aggregator already reached.
            if _STATUS_SEVERITY.get(overall, 0) < _STATUS_SEVERITY[StatusValue.DEGRADED.value]:
                overall = StatusValue.DEGRADED.value

    http_status = _status_to_http(StatusValue(overall))

    body: dict[str, Any] = {
        # The legacy v1 status string, unchanged for the consumers that
        # already read it. ``canonical_status`` / ``worst_status`` carry
        # the precise canonical verdict -- the worst case across every
        # feed, canonical and MCP-local alike, so nothing in the body
        # contradicts anything else in it.
        "status": _STATUS_TO_LEGACY.get(overall, "unhealthy"),
        "canonical_status": overall,
        "service": service_name,
        "version": version,
        "uptime_seconds": uptime_seconds,
        "timestamp": datetime.now(UTC).isoformat(),
        "launcher": _launcher_stamp(),
        # Every feed, canonical and MCP-local, in one dict.
        "checks": checks,
        "canonical_checks": canonical_checks,
        "canonical_reason_codes": reason_codes,
        "reason_codes": reason_codes,
        "worst_status": overall,
        "feed_states": canonical_checks,
        "aggregate_duration_ms": verdict.duration_ms,
        "http_status": http_status,
    }
    return body, http_status


def _launcher_stamp() -> str:
    """The launcher identity operators grep for during an incident."""
    import mcp_common

    return f"mcp_common.server.launcher@{mcp_common.__version__}"


__all__ = [
    "MahavishnuHealthVerdict",
    "aggregate_mahavishnu_health",
    "build_mahavishnu_health_body",
    "get_health_metrics_registry",
    "reset_health_metrics_registry_for_tests",
]
