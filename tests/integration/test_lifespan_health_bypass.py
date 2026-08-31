"""Regression test for the ``/health`` lifespan bypass.

Guards commit ``94741625`` (Phase 1 of
``docs/plans/2026-08-20-mahavishnu-lifespan-health-bypass.md``), which moved
``FastMCP`` creation and ``/health`` route registration to the *top* of
``FastMCPServer.__init__`` -- before ``self.app = MahavishnuApp(config)``, the
call that blocks on heavy adapter initialization (OpenSearch, LlamaIndex,
Agno, session-buddy poller, repo loader).

Before that commit the ``/health`` route was only attached to the FastMCP
instance *after* the blocking init returned, so an ASGI app built while the
init was still running had no ``/health`` route at all. The launchd
``launch_with_healthcheck.sh`` wrapper polls ``/health`` with a 60s timeout
and killed the process 10+ consecutive times on 2026-08-20.

Test strategy
-------------
``MahavishnuApp.__init__`` is synchronous and is called from inside
``FastMCPServer.__init__``, so the blocking init is reproduced with a stub
app whose ``_initialize_runtime_services`` performs a blocking
``time.sleep``. The construction runs on a worker thread (via
``asyncio.to_thread``) so the test event loop stays free to:

1. grab the ``FastMCP`` instance the moment it is created (before the
   blocking init begins),
2. build its ASGI app and serve it with Uvicorn on an ephemeral port,
3. poll ``/health`` within a 1s deadline while the init is still blocked.

Without commit ``94741625`` step 3 gets a 404 because the route had not been
registered yet, and the test fails.

Readiness note
--------------
The MCP ASGI surface only exposes ``/health``, ``/healthz`` and ``/metrics``
(see ``mahavishnu.mcp.bootstrap.register_health_endpoint``). The plan's
``/ready`` + ``_ready_flag`` work was explicitly *not* delivered in Phase 1 --
the commit message records that it was deemed unnecessary once the handler
was found to be independent of app state.
``test_ready_route_absent_from_mcp_surface`` pins that as the current,
intentional shape so a future ``/ready`` addition has to update this file
deliberately.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os
import threading
import time
from typing import TYPE_CHECKING
from unittest.mock import Mock

import httpx2 as httpx
from oneiric.core.logging import get_logger
import pytest
import uvicorn

from mahavishnu.mcp import server_core

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = get_logger(__name__)

pytestmark = [pytest.mark.integration, pytest.mark.slow]


# How long the simulated runtime init blocks. The plan calls for 30s; CI
# runners can shorten it via the env var without editing the test. Keep it
# comfortably above HEALTH_DEADLINE_SECONDS or the test proves nothing.
SLOW_INIT_SECONDS = float(os.environ.get("MHV_LIFESPAN_TEST_SLEEP", "30"))

# The plan's success metric: /health must answer in under a second.
HEALTH_DEADLINE_SECONDS = 1.0

# Upper bound on how long we wait for the FastMCP object to be captured and
# for Uvicorn to bind. Both happen before the blocking init in the fixed code.
BOOT_DEADLINE_SECONDS = 5.0

_POLL_INTERVAL_SECONDS = 0.02


def _stub_config() -> Mock:
    """Build the minimal config surface ``FastMCPServer.__init__`` reads."""
    config = Mock()
    config.server_name = "mahavishnu"
    config.max_concurrent_workflows = 10
    config.auth.enabled = False
    config.qc.enabled = False
    config.session.enabled = False
    config.subscription_auth.enabled = False
    config.subscription_auth.secret = None
    config.observability.tracing_enabled = False
    config.terminal.enabled = False
    config.terminal.adapter_preference = "mock"
    return config


class _SlowInitApp:
    """Stand-in for ``MahavishnuApp`` whose runtime init blocks.

    Mirrors the real class's shape: ``__init__`` calls
    ``_initialize_runtime_services`` synchronously, which is exactly where
    the production 4.7s OpenSearch round-trip (and friends) lives.
    """

    init_started = threading.Event()
    init_finished = threading.Event()
    sleep_seconds = SLOW_INIT_SECONDS

    def __init__(self, config=None) -> None:
        self.config = _stub_config()
        self.pool_manager = None
        self._initialize_runtime_services()

    def _initialize_runtime_services(self) -> None:
        type(self).init_started.set()
        time.sleep(type(self).sleep_seconds)
        type(self).init_finished.set()


@asynccontextmanager
async def _serve_asgi(asgi_app) -> AsyncIterator[int]:
    """Serve ``asgi_app`` with Uvicorn on an ephemeral port; yield the port.

    ``lifespan="off"`` keeps the FastMCP session-manager startup out of the
    picture -- ``/health`` is a plain Starlette route and does not need it,
    and skipping it removes a source of flakiness.
    """
    config = uvicorn.Config(
        asgi_app,
        host="127.0.0.1",
        port=0,
        log_level="warning",
        lifespan="off",
    )
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve())

    deadline = time.monotonic() + BOOT_DEADLINE_SECONDS
    while not server.started:
        if serve_task.done():  # surfaces a bind failure instead of hanging
            await serve_task
        if time.monotonic() > deadline:
            raise TimeoutError("Uvicorn did not bind within the boot deadline")
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield port
    finally:
        server.should_exit = True
        await serve_task


async def _wait_for(predicate, deadline_seconds: float, description: str) -> None:
    """Poll ``predicate`` until true or the deadline elapses."""
    deadline = time.monotonic() + deadline_seconds
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError(f"Timed out waiting for {description}")
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


@pytest.fixture
def slow_init_server(monkeypatch):
    """Patch ``server_core`` so construction blocks and the FastMCP is captured.

    Yields a ``(captured, start_construction)`` pair:

    - ``captured`` is a list that receives the ``FastMCP`` instance as soon as
      ``FastMCPServer.__init__`` creates it.
    - ``start_construction`` launches ``FastMCPServer()`` on a worker thread
      and returns the awaitable task.
    """
    _SlowInitApp.init_started.clear()
    _SlowInitApp.init_finished.clear()

    captured: list = []
    real_fastmcp = server_core.FastMCP

    def _capturing_fastmcp(*args, **kwargs):
        instance = real_fastmcp(*args, **kwargs)
        captured.append(instance)
        return instance

    monkeypatch.setattr(server_core, "FastMCP", _capturing_fastmcp)
    monkeypatch.setattr(server_core, "MahavishnuApp", _SlowInitApp)

    yield captured, lambda: asyncio.create_task(asyncio.to_thread(server_core.FastMCPServer))


async def test_health_responds_while_runtime_init_blocks(slow_init_server):
    """``/health`` answers in under 1s while runtime init sleeps for 30s.

    This is the regression guard. Reverting commit ``94741625`` moves
    ``/health`` registration back below the blocking ``MahavishnuApp(...)``
    call, so the ASGI app built here has no ``/health`` route and the request
    404s.
    """
    captured, start_construction = slow_init_server
    construct_task = start_construction()

    try:
        # The FastMCP object and the /health route are created before the
        # blocking init in the fixed code -- this wait should be near-instant.
        await _wait_for(
            lambda: bool(captured),
            BOOT_DEADLINE_SECONDS,
            "FastMCP instance to be created",
        )
        await _wait_for(
            _SlowInitApp.init_started.is_set,
            BOOT_DEADLINE_SECONDS,
            "runtime init to start blocking",
        )

        asgi_app = captured[0].http_app()

        async with _serve_asgi(asgi_app) as port:
            # Sanity: we are genuinely mid-init, not measuring a warm server.
            assert not _SlowInitApp.init_finished.is_set(), (
                "runtime init finished before /health was polled -- "
                f"raise MHV_LIFESPAN_TEST_SLEEP above {SLOW_INIT_SECONDS}s"
            )
            assert not construct_task.done()

            started = time.monotonic()
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                response = await client.get("/health", timeout=HEALTH_DEADLINE_SECONDS)
            elapsed = time.monotonic() - started
            logger.info("health_probe_elapsed_seconds=%.4f", elapsed)

            assert response.status_code == 200, (
                "/health did not answer while runtime init was blocked -- "
                "the route was registered after MahavishnuApp.__init__ "
                "(regression of commit 94741625)"
            )
            assert elapsed < HEALTH_DEADLINE_SECONDS, (
                f"/health took {elapsed:.3f}s, over the {HEALTH_DEADLINE_SECONDS}s budget"
            )

            payload = response.json()
            assert payload["status"] == "ok"
            assert payload["service"] == "mahavishnu"
            assert payload["version"]

            # The init must still be blocked: proves the 200 above was served
            # concurrently with, not after, runtime initialization.
            assert not _SlowInitApp.init_finished.is_set()
    finally:
        await construct_task


async def test_health_still_responds_after_runtime_init_completes(slow_init_server):
    """After the blocked init finishes, ``/health`` keeps answering 200.

    Stands in for the plan's "poll ``/ready`` again after 30s, assert 200"
    step: the MCP ASGI surface has no ``/ready`` route (see the module
    docstring), so readiness is observed as "construction returned and the
    server is fully wired" instead.
    """
    captured, start_construction = slow_init_server
    server = await start_construction()

    assert _SlowInitApp.init_finished.is_set()
    assert server.app.config.server_name == "mahavishnu"

    async with _serve_asgi(captured[0].http_app()) as port:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            response = await client.get("/health", timeout=HEALTH_DEADLINE_SECONDS)
            healthz = await client.get("/healthz", timeout=HEALTH_DEADLINE_SECONDS)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert healthz.status_code == 200
    assert healthz.json()["status"] == "ok"


async def test_ready_route_absent_from_mcp_surface(slow_init_server):
    """Pin the current MCP surface: ``/ready`` is not served on this app.

    ``/ready`` exists only on the separate FastAPI worker health app
    (``mahavishnu.health.create_health_app``), not on the MCP ASGI app that
    launchd polls. Phase 1 of the plan deliberately shipped without the
    ``_ready_flag`` / ``/ready`` warming-up semantics. If that work lands
    later, this test should be replaced with real warming-up assertions.
    """
    captured, start_construction = slow_init_server
    server = await start_construction()
    assert server is not None

    async with _serve_asgi(captured[0].http_app()) as port:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            response = await client.get("/ready", timeout=HEALTH_DEADLINE_SECONDS)

    assert response.status_code == 404, (
        "/ready is now served by the MCP app -- update this test with the "
        "warming-up assertions from "
        "docs/plans/2026-08-20-mahavishnu-lifespan-health-bypass.md Phase 1"
    )
