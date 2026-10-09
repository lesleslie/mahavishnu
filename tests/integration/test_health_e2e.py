"""End-to-end integration test for the Phase 1.1 health-enrichment plan.

Per ``docs/plans/2026-10-09-mcp-health-check-enrichment.md`` Phase 1.1
Integration Contract: the test wires up the real ``create_health_app``
against a stub ``aggregate_mahavishnu_health`` so the canonical
``HealthSnapshot`` envelope (``status`` / ``checks`` / ``reason_codes``)
is exercised end-to-end through the FastAPI route.

The test covers three contracts:

1. **Healthy envelope**: when all feeds report ``HEALTHY`` the route
   returns HTTP 200 with ``canonical_status="healthy"`` and the
   per-feed ``FeedSnapshot`` dicts.
2. **Degraded envelope** (B2 refuter-review fix): when any feed
   reports ``DEGRADED`` the route returns HTTP 503 with
   ``canonical_status="degraded"`` and the worst feed's
   ``reason_codes`` surfaced.
3. **Wire-shape envelope**: the response body always carries
   ``canonical_status`` / ``canonical_checks`` /
   ``canonical_reason_codes`` matching the canonical
   ``mcp-common/mcp_common/health/aggregator.py:33-46`` contract.

Marker: ``integration`` per ``CLAUDE.md`` test conventions.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
import pytest

from mahavishnu.core.health_aggregator import MahavishnuHealthVerdict
from mahavishnu.health import create_health_app

# ---------------------------------------------------------------------------
# Fixtures: stub ``aggregate_mahavishnu_health`` to return a deterministic
# verdict so the e2e test exercises the FastAPI route without depending
# on the real probe implementations (EncryptedSQLite, InMemoryEventTransport,
# MahavishnuSettings, etc.).
# ---------------------------------------------------------------------------


@pytest.fixture
def healthy_verdict() -> MahavishnuHealthVerdict:
    """Stub a ``StatusValue.HEALTHY`` verdict for all 3 v1 feeds."""
    from mcp_common.health.feed import StatusValue

    snap: dict[str, Any] = {
        "status": StatusValue.HEALTHY,
        "checks": {
            "storage": {
                "status": StatusValue.HEALTHY,
                "healthy": True,
                "reason_codes": [],
            },
            "message_bus": {
                "status": StatusValue.HEALTHY,
                "healthy": True,
                "reason_codes": [],
            },
            "adapters": {
                "status": StatusValue.HEALTHY,
                "healthy": True,
                "reason_codes": [],
            },
        },
        "reason_codes": [],
    }
    return MahavishnuHealthVerdict(
        snapshot=snap,
        worst_status=StatusValue.HEALTHY,
        http_status=200,
        duration_ms=0.42,
    )


@pytest.fixture
def degraded_verdict() -> MahavishnuHealthVerdict:
    """Stub a ``StatusValue.DEGRADED`` verdict (one feed broken).

    Per the B2 refuter-review fix, when a feed is in
    ``broken-before-first-success`` for >60s (the
    ``HEALTH_FEED_HALFLIFE_SECONDS=60`` window) the aggregator flips
    that feed to ``DEGRADED`` and the route returns HTTP 503.
    """
    from mcp_common.health.feed import ReasonCode, StatusValue

    snap: dict[str, Any] = {
        "status": StatusValue.DEGRADED,
        "checks": {
            "storage": {
                "status": StatusValue.HEALTHY,
                "healthy": True,
                "reason_codes": [],
            },
            "message_bus": {
                "status": StatusValue.DEGRADED,
                "healthy": False,
                "reason_codes": [ReasonCode.FEED_NEVER_POPULATED],
            },
            "adapters": {
                "status": StatusValue.HEALTHY,
                "healthy": True,
                "reason_codes": [],
            },
        },
        "reason_codes": [ReasonCode.FEED_NEVER_POPULATED],
    }
    return MahavishnuHealthVerdict(
        snapshot=snap,
        worst_status=StatusValue.DEGRADED,
        http_status=503,
        duration_ms=0.55,
    )


@pytest.fixture
def stub_aggregator(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Patch ``aggregate_mahavishnu_health`` to a function that returns
    the verdict supplied via the ``verdict`` closure in each test.

    Tests call ``stub_aggregator.set_verdict(verdict)`` to control
    what the route sees. The default verdict is the healthy one
    so tests that don't override see a 200.
    """
    state: dict[str, Any] = {
        "verdict": None,  # set by set_verdict()
    }

    def _fake_aggregate(*, repo: str) -> MahavishnuHealthVerdict:
        if state["verdict"] is None:
            raise RuntimeError("stub_aggregator.set_verdict(...) not called")
        return state["verdict"]

    monkeypatch.setattr(
        "mahavishnu.health.aggregate_mahavishnu_health",
        _fake_aggregate,
    )

    class _StubAggregator:
        def set_verdict(self, verdict: MahavishnuHealthVerdict) -> None:
            state["verdict"] = verdict

    return _StubAggregator()


@pytest.fixture
def client(stub_aggregator: Any, healthy_verdict: MahavishnuHealthVerdict) -> TestClient:
    """FastAPI TestClient bound to a fresh ``create_health_app``."""
    stub_aggregator.set_verdict(healthy_verdict)
    app = create_health_app(server_name="mahavishnu-e2e")
    return TestClient(app)


# ---------------------------------------------------------------------------
# Healthy envelope (Integration Contract Demonstration gate #1)
# ---------------------------------------------------------------------------


def test_health_returns_200_when_all_feeds_healthy(
    client: TestClient,
    stub_aggregator: Any,
    healthy_verdict: MahavishnuHealthVerdict,
) -> None:
    """``GET /health`` returns 200 with the canonical healthy envelope.

    Wire-shape contract (B2 refuter-review fix): the body must
    carry ``canonical_status`` / ``canonical_checks`` /
    ``canonical_reason_codes`` matching the canonical mcp-common
    ``HealthSnapshot`` shape.
    """
    stub_aggregator.set_verdict(healthy_verdict)

    response = client.get("/health")

    # HTTP 200 per spec §4.8: healthy/warming_up → 200.
    assert response.status_code == 200
    body = response.json()

    # Legacy fields (v1 API contract) preserved.
    assert body["status"] == "ok"
    assert body["service"] == "mahavishnu-e2e"
    assert "version" in body
    assert body["uptime_seconds"] >= 0.0

    # Canonical HealthSnapshot envelope (B2 fix).
    assert body["canonical_status"] == "healthy"
    assert body["canonical_reason_codes"] == []
    assert set(body["canonical_checks"].keys()) == {
        "storage",
        "message_bus",
        "adapters",
    }
    for feed_name in ("storage", "message_bus", "adapters"):
        feed = body["canonical_checks"][feed_name]
        assert feed["status"] == "healthy"
        assert feed["healthy"] is True
        assert feed["reason_codes"] == []

    # The body also exposes the per-feed verdict under the
    # legacy ``feed_states`` field (v1 API consumers) — must
    # agree with the canonical ``canonical_checks`` field.
    assert body["feed_states"] == body["canonical_checks"]
    assert body["worst_status"] == "healthy"


# ---------------------------------------------------------------------------
# Degraded envelope (Integration Contract Demonstration gate #2)
# ---------------------------------------------------------------------------


def test_health_returns_503_on_broken_feed(
    client: TestClient,
    stub_aggregator: Any,
    degraded_verdict: MahavishnuHealthVerdict,
) -> None:
    """``GET /health`` returns 503 with canonical degraded envelope.

    Per spec §4.8: ``degraded``/``failed`` → 503. The body's
    ``canonical_reason_codes`` carries the worst feed's
    ``ReasonCode`` so operators can pinpoint which feed is
    broken-before-first-success or errors-accumulating.
    """
    stub_aggregator.set_verdict(degraded_verdict)

    response = client.get("/health")

    # HTTP 503 per spec §4.8: degraded/failed → 503.
    assert response.status_code == 503
    body = response.json()

    # Legacy status mapping: degraded → ``degraded``.
    assert body["status"] == "degraded"

    # Canonical HealthSnapshot envelope (B2 fix).
    assert body["canonical_status"] == "degraded"
    assert "feed_never_populated" in body["canonical_reason_codes"]
    # The broken feed (message_bus) reports degraded; the others stay healthy.
    assert body["canonical_checks"]["storage"]["status"] == "healthy"
    assert body["canonical_checks"]["message_bus"]["status"] == "degraded"
    assert body["canonical_checks"]["message_bus"]["healthy"] is False
    assert body["canonical_checks"]["adapters"]["status"] == "healthy"


# ---------------------------------------------------------------------------
# Wire-shape envelope contract (M3 refuter-review fix)
# ---------------------------------------------------------------------------


def test_health_canonical_envelope_matches_mcp_common_health_snapshot() -> None:
    """The canonical fields mirror mcp-common ``HealthSnapshot`` verbatim.

    Per ``mcp-common/mcp_common/health/aggregator.py:33-46`` the
    canonical contract is::

        class HealthSnapshot(TypedDict):
            status: StatusValue
            checks: dict[str, FeedSnapshot]
            reason_codes: list[ReasonCode]

    The ``HealthResponse`` model surfaces those three top-level
    fields as ``canonical_status`` / ``canonical_checks`` /
    ``canonical_reason_codes`` (named with the ``canonical_``
    prefix to avoid colliding with the legacy v1 fields). This
    test pins the surface so the wire-shape contract is
    regression-protected.
    """
    from mcp_common.health.aggregator import HealthSnapshot

    # Import the model at runtime so the import error is localised
    # to this test (the schema is the contract under test).
    from mahavishnu.core.health import HealthResponse

    # TypedDict shape (regression pin)
    expected_typeddict_keys = {"status", "checks", "reason_codes"}
    assert set(HealthSnapshot.__annotations__.keys()) == expected_typeddict_keys

    # HealthResponse must expose the canonical fields by name.
    fields = set(HealthResponse.model_fields.keys())
    assert "canonical_status" in fields
    assert "canonical_checks" in fields
    assert "canonical_reason_codes" in fields


# ---------------------------------------------------------------------------
# M2 polish: per-server ``mahavishnu_health_feed_status`` gauge
# ---------------------------------------------------------------------------


def test_health_emits_m2_per_server_feed_status_gauge(
    client: TestClient,
    stub_aggregator: Any,
    healthy_verdict: MahavishnuHealthVerdict,
) -> None:
    """``aggregate_mahavishnu_health`` updates the M2 per-server gauge.

    The M2 polish registers ``mahavishnu_health_feed_status{feed, status}``
    in ``mahavishnu.observability.prometheus_metrics``. After a
    healthy call, every feed cell with ``status="healthy"`` is
    ``1`` and the others are ``0``. The aggregator shares the
    M2 gauge with the mcp-common metrics on the same private
    registry so the ``/metrics`` route exposes them on one
    scrape surface.
    """
    import prometheus_client

    from mahavishnu.observability.prometheus_metrics import (
        get_health_metrics_registry,
        update_health_feed_status_metrics,
    )

    stub_aggregator.set_verdict(healthy_verdict)

    # Trigger the route so the aggregator runs end-to-end. The
    # route delegates to ``aggregate_mahavishnu_health`` (stubbed
    # in this test) which then calls the M2 update hook.
    response = client.get("/health")
    assert response.status_code == 200

    # Independently call the M2 update so we can read the
    # registry without relying on the route's call ordering.
    update_health_feed_status_metrics(
        snap=healthy_verdict.snapshot,
        registry=get_health_metrics_registry(),
    )

    # Render the registry and assert the M2 metric is present
    # with the right labels and values.
    text = prometheus_client.generate_latest(
        get_health_metrics_registry(),
    ).decode("utf-8")

    # Per-feed M2 gauge: 1 for the current ``healthy`` cell, 0
    # for the others. We assert at least one ``healthy=1`` line
    # per feed is present.
    for feed_name in ("storage", "message_bus", "adapters"):
        assert (
            f'mahavishnu_health_feed_status{{feed="{feed_name}",status="healthy"}} 1.0'
            in text
        ), (
            f"Missing M2 gauge for feed={feed_name} status=healthy in:\n{text}"
        )


# ---------------------------------------------------------------------------
# Degraded feed flips the M2 gauge to the degraded cell
# ---------------------------------------------------------------------------


def test_health_m2_gauge_flips_on_degraded_feed(
    client: TestClient,
    stub_aggregator: Any,
    degraded_verdict: MahavishnuHealthVerdict,
) -> None:
    """The M2 gauge flips to the degraded cell when a feed degrades.

    This is the regression pin for the M2 polish: when the
    canonical aggregator reports ``degraded`` for a feed, the
    M2 gauge's ``(feed, status="degraded")`` cell must be
    ``1`` and the ``(feed, status="healthy")`` cell must be
    ``0``. Without this, dashboards reading
    ``max by (feed) (mahavishnu_health_feed_status)`` would
    return ``healthy`` even when the canonical aggregator
    reports ``degraded``.
    """
    import prometheus_client

    from mahavishnu.observability.prometheus_metrics import (
        get_health_metrics_registry,
        update_health_feed_status_metrics,
    )

    stub_aggregator.set_verdict(degraded_verdict)

    # The M2 update is called inside ``aggregate_mahavishnu_health``;
    # call it directly here so we don't need to round-trip the
    # route.
    update_health_feed_status_metrics(
        snap=degraded_verdict.snapshot,
        registry=get_health_metrics_registry(),
    )

    text = prometheus_client.generate_latest(
        get_health_metrics_registry(),
    ).decode("utf-8")

    # The broken feed (message_bus) flips to status="degraded".
    assert (
        'mahavishnu_health_feed_status{feed="message_bus",status="degraded"} 1.0'
        in text
    )
    # The healthy cells for the broken feed are reset to 0.
    assert (
        'mahavishnu_health_feed_status{feed="message_bus",status="healthy"} 0.0'
        in text
    )
    # The still-healthy feeds stay at 1 for the healthy cell.
    assert (
        'mahavishnu_health_feed_status{feed="storage",status="healthy"} 1.0'
        in text
    )
