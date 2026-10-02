"""Wire feed-state provider, register /health, verify plan_index.ok computed correctly.

When last_updated_timestamp is 8 days old (past 5× cron_every_seconds at
default 3600s), the plan_index feed's as_dict() returns ok=False and the
registered /health handler returns HTTP 503 per
mcp-backend-wiring-discipline.md.

Round-3 fix: the previous version used a subprocess `plan_index_mcp_server`
fixture and set the feed-state global in the TEST process, which never
reached the server's own global state. This version drives the
registration directly with a FakeFastMCP that captures custom_route
handlers, then invokes the captured /health function in-process — no
subprocess boundary to cross.
"""

# REQ-PLAN-018: /health aggregation reports degraded on stale feed

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import AsyncMock

from mahavishnu.mcp.bootstrap import register_health_endpoint
from mahavishnu.plan_index.health import (
    PlanIndexFeedState,
    set_plan_index_feed_state,
)


class _FakeFastMCP:
    """Stub matching the FastMCPServer shape `register_health_endpoint`
    consumes. The real server has `server.server.custom_route(path, methods=...)`
    which `register_health_endpoint` decorates with the health handler.
    We capture each (path, method) -> handler so the test can invoke
    the handler directly without an HTTP server.
    """

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Any] = {}

        outer = self

        class _Server:
            def custom_route(self, path: str, methods: list[str]) -> Any:
                def _decorator(fn: Any) -> Any:
                    for method in methods:
                        outer.routes[(path, method)] = fn
                    return fn

                return _decorator

        self.server = _Server()


class TestHealthCheckAggregates:
    async def test_stale_feed_returns_503(self) -> None:
        # Force a stale feed state (8 days ago = past 5× cron threshold).
        eight_days_ago_ms = int(time.time() * 1000) - 8 * 24 * 3600 * 1000
        set_plan_index_feed_state(
            PlanIndexFeedState(
                entities_count=10,
                last_updated_timestamp=eight_days_ago_ms,
                errors_total=0,
                cycles_total=5,
            )
        )

        # Register the health endpoint on a fake FastMCP server and capture
        # the /health handler so we can invoke it in-process.
        fake = _FakeFastMCP()
        register_health_endpoint(fake, version="test")
        health_handler = fake.routes.get(("/health", "GET"))
        assert health_handler is not None, (
            "register_health_endpoint must register a ('/health', 'GET') route"
        )

        # Invoke the registered handler. It returns an object with .body
        # (JSON string) and .status_code.
        response = await health_handler()
        assert response.status_code == 503, (
            f"/health should return 503 on stale feed, got {response.status_code}"
        )

        body = json.loads(response.body)
        assert body["status"] == "degraded"
        assert "checks" in body
        assert "plan_index" in body["checks"]
        assert body["checks"]["plan_index"]["ok"] is False, (
            f"plan_index feed check must report ok=False on stale timestamp, "
            f"got {body['checks']['plan_index']!r}"
        )


class TestTaskOrphanSweeperHealthAggregation:
    """Task 10 — ``/health`` must surface ``sweeper.health()`` as
    ``task_orphan_sweeper.ok``. When the sweeper reports unhealthy
    (e.g. 3+ consecutive read failures), the /health aggregate flips
    to HTTP 503 and the per-feed ``ok`` is False.

    Mirrors :class:`TestHealthCheckAggregates`'s FakeFastMCP pattern —
    drive the registration directly and invoke the captured /health
    handler in-process.
    """

    def setup_method(self) -> None:
        # The /health aggregator unions skills_signer, plan_index, and
        # task_orphan_sweeper. The earlier ``TestHealthCheckAggregates``
        # test seeds a stale plan_index state without resetting, so a
        # naive run-order would see /health=503 here for the wrong
        # reason. Reset both module globals to ``None`` so the only
        # signal under test is the sweeper.
        from mahavishnu.mcp.signer_feed import reset_signer_feed_state
        from mahavishnu.plan_index.health import reset_plan_index_feed_state

        reset_signer_feed_state()
        reset_plan_index_feed_state()

    async def test_sweeper_degraded_returns_503(self) -> None:
        # Stash a sweeper stub on the fake server with health() -> False.
        # The /health handler in ``register_health_endpoint`` reads
        # ``server._task_orphan_sweeper`` via ``getattr`` (the seam
        # established by ``mahavishnu.mcp.lifecycle.start_server``).
        sweeper = type(
            "StubSweeper",
            (),
            {"health": AsyncMock(return_value=False)},
        )()
        fake = _FakeFastMCP()
        fake._task_orphan_sweeper = sweeper
        register_health_endpoint(fake, version="test")
        health_handler = fake.routes.get(("/health", "GET"))
        assert health_handler is not None, (
            "register_health_endpoint must register a ('/health', 'GET') route"
        )

        response = await health_handler()
        assert response.status_code == 503, (
            f"/health should return 503 when task_orphan_sweeper is degraded, "
            f"got {response.status_code}"
        )

        body = json.loads(response.body)
        assert body["status"] == "degraded"
        assert "task_orphan_sweeper" in body["checks"], (
            f"/health must include task_orphan_sweeper check, "
            f"got checks={list(body['checks'])}"
        )
        assert body["checks"]["task_orphan_sweeper"]["ok"] is False, (
            f"task_orphan_sweeper feed check must report ok=False when "
            f"sweeper.health() returns False, got {body['checks']['task_orphan_sweeper']!r}"
        )
        sweeper.health.assert_awaited_once()

    async def test_sweeper_healthy_returns_200(self) -> None:
        """Healthy sweeper — /health stays 200 and the per-feed
        ``ok`` is True. This is the success-side counterpart to the
        degraded test above; without it, the new wiring could
        accidentally always-report degraded.
        """
        sweeper = type(
            "StubSweeper",
            (),
            {"health": AsyncMock(return_value=True)},
        )()
        fake = _FakeFastMCP()
        fake._task_orphan_sweeper = sweeper
        register_health_endpoint(fake, version="test")
        health_handler = fake.routes.get(("/health", "GET"))

        response = await health_handler()
        assert response.status_code == 200, (
            f"/health should return 200 when sweeper is healthy, "
            f"got {response.status_code}"
        )

        body = json.loads(response.body)
        assert body["status"] == "ok"
        assert body["checks"]["task_orphan_sweeper"]["ok"] is True
        sweeper.health.assert_awaited_once()

    async def test_sweeper_absent_warms_up(self) -> None:
        """When start_server never ran (test-only server, or
        sweeper spawn raised), the /health handler must report
        "warming_up" rather than degraded — same fix as
        skills_signer / plan_index branches. Without this guard,
        every test that constructs a server by hand would flip
        /health to 503 before start_server gets a chance to attach
        the sweeper.
        """
        fake = _FakeFastMCP()
        # Intentionally do NOT attach _task_orphan_sweeper.
        register_health_endpoint(fake, version="test")
        health_handler = fake.routes.get(("/health", "GET"))

        response = await health_handler()
        # plan_index + skills_signer are not seeded here either, but
        # those are module-globals that default to "warming up".
        # The per-feed check for task_orphan_sweeper is what we care about.
        body = json.loads(response.body)
        assert "task_orphan_sweeper" in body["checks"]
        assert body["checks"]["task_orphan_sweeper"]["status"] == "warming_up", (
            f"task_orphan_sweeper must report warming_up when absent, "
            f"got {body['checks']['task_orphan_sweeper']!r}"
        )
        assert body["checks"]["task_orphan_sweeper"]["ok"] is True
