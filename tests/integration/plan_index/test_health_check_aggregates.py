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
