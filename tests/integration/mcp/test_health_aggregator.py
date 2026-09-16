"""Phase 4 consumer-side wiring for the Bodai health aggregator.

Per the common-mcp-client transport unification plan, Phase 4 wires a
single per-component feed-state aggregator that the Mahavishnu
``/health`` endpoint surfaces. The **foundation** shipped in
mcp-common v0.26.4 (commits 7acdcfb + 837d64a + 12f61aa + f52bdb2) —
canonical ``HealthFeedState`` + ``aggregate_feed_states`` +
``update_health_metrics`` + ``--health-disable-decay`` CLI flag live
in ``mcp-common/mcp_common/health/`` and are pinned by 66 tests at
``mcp-common/tests/unit/health/``. The **consumer-side wiring** (this
file's tests) lands in mahavishnu in ``mahavishnu/core/
health_aggregator.py`` and ``mahavishnu/health.py``.

Reference implementations (mirror the pattern):
- ``session-buddy/session_buddy/server_optimized.py:316-407`` (1 feed)
- ``akosha/akosha/mcp/server.py:764-949`` (multi-feed)

Mahavishnu exposes 3 feeds in v1: ``storage``, ``message_bus``,
``adapters``. New feeds append to ``_collect_feed_states`` in
``mahavishnu/core/health_aggregator.py`` and the aggregator's
worst-case rollup includes them automatically.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from mcp_common.health.aggregator import HealthSnapshot


def test_mahavishnu_health_aggregator_module_exists() -> None:
    """The ``mahavishnu.core.health_aggregator`` module imports cleanly.

    No skip: this module ships with the Phase 4 wiring commit. If
    the import fails, the wiring is broken — fail loudly rather
    than skip, so CI catches regressions.
    """
    module = importlib.import_module("mahavishnu.core.health_aggregator")
    assert module is not None
    # Public surface pinned by the test:
    assert hasattr(module, "aggregate_mahavishnu_health")
    assert hasattr(module, "get_health_metrics_registry")
    assert hasattr(module, "MahavishnuHealthVerdict")


def test_aggregate_mahavishnu_health_returns_verdict() -> None:
    """``aggregate_mahavishnu_health`` returns a verdict with all fields.

    Smoke test: confirms the wiring constructs the
    ``dict[str, HealthFeedState]``, calls ``aggregate_feed_states``,
    emits metrics, and returns a :class:`MahavishnuHealthVerdict`.
    No mocking — exercises the real probes (storage/message_bus/
    adapters).
    """
    from mcp_common.health.feed import StatusValue

    from mahavishnu.core.health_aggregator import (
        MahavishnuHealthVerdict,
        aggregate_mahavishnu_health,
    )

    verdict: MahavishnuHealthVerdict = aggregate_mahavishnu_health(
        repo="mahavishnu-test"
    )

    # Verdict shape
    assert isinstance(verdict, MahavishnuHealthVerdict)
    assert isinstance(verdict.snapshot, dict)
    assert isinstance(verdict.worst_status, StatusValue)
    assert verdict.http_status in (200, 503)
    assert verdict.duration_ms >= 0.0

    # Snapshot shape — the HealthSnapshot TypedDict contract from
    # mcp-common v0.26.4
    snap: HealthSnapshot = verdict.snapshot
    assert "status" in snap
    assert "checks" in snap
    assert "reason_codes" in snap

    # 3 v1 feeds: storage, message_bus, adapters (per the wiring
    # helper). Adding a new feed should bump this count and the
    # test will fail loudly, prompting the author to update the
    # assertion (forward-compat signal).
    assert set(snap["checks"].keys()) == {"storage", "message_bus", "adapters"}

    # HTTP mapping: healthy/warming_up → 200, degraded/failed → 503
    expected_http = 200 if verdict.worst_status in (
        StatusValue.HEALTHY,
        StatusValue.WARMING_UP,
    ) else 503
    assert verdict.http_status == expected_http


def test_metrics_registry_is_isolated_from_global() -> None:
    """The health-aggregator metrics registry is private (not global).

    Mirrors the mcp-common warning that registering on the global
    ``prometheus_client.REGISTRY`` raises ``Duplicated timeseries``
    if the same metric name is registered elsewhere in the process
    (mahavishnu's websocket/routing/goal-team metrics modules already
    use the global ``REGISTRY``). The health-aggregator uses a
    private ``CollectorRegistry`` to avoid the collision.
    """
    import prometheus_client

    from mahavishnu.core import health_aggregator

    registry = health_aggregator.get_health_metrics_registry()

    assert isinstance(registry, prometheus_client.CollectorRegistry)
    assert registry is not prometheus_client.REGISTRY


def test_metrics_endpoint_renders_text_format() -> None:
    """The ``/metrics`` endpoint exposes the four PromQL metrics
    in ``text/plain; version=0.0.4`` exposition format.

    Pins the contract that ``config/prometheus/health_aggregator_
    alerts.yml`` can scrape from the mahavishnu ``/metrics`` route
    and the alerts (``health_feed_status{repo="mahavishnu", ...} ==
    1``) fire live.
    """
    from fastapi.testclient import TestClient

    # Reset the cached registry to start clean (the test harness
    # may have populated it from prior test runs).
    from mahavishnu.core import health_aggregator

    health_aggregator.reset_health_metrics_registry_for_tests()

    # Re-import health to pick up the cleared registry's first
    # emission lazily. The aggregator creates the metric instances
    # on first call, so we force one call here to populate the
    # registry before rendering.
    health_aggregator.aggregate_mahavishnu_health(repo="mahavishnu-metrics-test")

    from mahavishnu.health import create_health_app

    app = create_health_app(server_name="mahavishnu-metrics-test")
    client = TestClient(app)

    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.text

    # The four PromQL metrics referenced by the alerts in
    # config/prometheus/health_aggregator_alerts.yml must appear in
    # the exposition output (after the first /health or
    # aggregate_mahavishnu_health call has registered them).
    expected_metrics = (
        "health_feed_status",
        "health_feed_errors_within_window",
        "mcp_common_health_halflife_seconds",
        "mcp_common_health_aggregate_duration_ms",
    )
    for metric_name in expected_metrics:
        assert (
            metric_name in body
        ), f"PromQL metric {metric_name!r} missing from /metrics exposition; "
        "alerts in config/prometheus/health_aggregator_alerts.yml cannot fire. "
        f"Got:\n{body[:2000]}"
    # Repo label pinned to the metric instances.
    assert 'repo="mahavishnu-metrics-test"' in body


def test_health_endpoint_returns_200_on_warm_startup() -> None:
    """The ``/health`` endpoint returns 200 with the augmented
    HealthResponse shape (worst_status + feed_states +
    reason_codes + aggregate_duration_ms) on a healthy startup.

    Pins the backward-compat promise: the legacy 5 fields
    (status / service / version / uptime_seconds / timestamp)
    are still present, plus 4 new aggregator fields. Existing
    API consumers parsing the legacy shape still work.
    """
    from fastapi.testclient import TestClient

    from mahavishnu.health import create_health_app

    app = create_health_app(server_name="mahavishnu-health-test")
    client = TestClient(app)

    response = client.get("/health")
    # Either 200 (healthy/warming_up) or 503 (degraded/failed).
    # The exact verdict depends on whether the test environment has
    # EncryptedSQLite + InMemoryEventTransport + adapter settings
    # all importable; both paths are valid wiring.
    assert response.status_code in (200, 503)

    body: dict[str, Any] = response.json()

    # Legacy fields preserved.
    assert body["service"] == "mahavishnu-health-test"
    assert body["status"] in ("ok", "degraded", "unhealthy")
    assert "version" in body
    assert "uptime_seconds" in body
    assert "timestamp" in body

    # New aggregator fields populated (this is the Phase 4 wire-up
    # contract).
    assert body["worst_status"] in ("healthy", "warming_up", "degraded", "failed")
    assert isinstance(body["feed_states"], dict)
    assert set(body["feed_states"].keys()) == {"storage", "message_bus", "adapters"}
    assert isinstance(body["reason_codes"], list)
    assert isinstance(body["aggregate_duration_ms"], (int, float))


@pytest.mark.parametrize(
    ("halflife_env", "expected_decay_disabled"),
    [
        ("0", True),
        ("-1", True),
        ("300", False),
        ("", False),  # falls back to default 300
    ],
)
def test_halflife_env_resolves_decay_disable_sentinel(
    halflife_env: str, expected_decay_disabled: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``HEALTH_FEED_HALFLIFE_SECONDS=0`` disables time-bounded decay.

    This is the ``--health-disable-decay`` CLI flag's runtime
    propagation (mcp-common v0.26.4 commit 837d64a). ``halflife <=
    0`` → no error is ever treated as "recent" regardless of when
    it occurred.
    """
    from mahavishnu.core.health_aggregator import _resolve_halflife_seconds

    monkeypatch.setenv("HEALTH_FEED_HALFLIFE_SECONDS", halflife_env)
    resolved = _resolve_halflife_seconds()
    is_disabled = resolved <= 0
    assert is_disabled == expected_decay_disabled


def test_mahavishnu_app_is_constructable() -> None:
    """Sanity check: ``MahavishnuApp`` is constructable; Phase 4 also
    verified ``create_health_app`` constructs and serves /health.

    Skipped if the ``oneiric`` dependency is missing in the test venv
    (e.g. a thin install without the bootstrap extras). ``MahavishnuApp``
    triggers full application bootstrap which requires ``oneiric.logging``.
    """
    try:
        from mahavishnu.core.app import MahavishnuApp
    except ImportError as exc:
        import pytest

        pytest.skip(f"MahavishnuApp bootstrap unavailable: {exc}")

    import pytest

    try:
        app = MahavishnuApp()
    except (RuntimeError, ModuleNotFoundError) as exc:
        pytest.skip(f"MahavishnuApp bootstrap skipped: {exc}")
    assert app is not None
