"""Integration-test conftest for the ``requires_network`` Redis fixtures.

Task 12 of the v1.1 Bodai task-system plan provisions a coredis client
backed by a locally reachable Redis (``127.0.0.1:6379``) for the
sweeper e2e test. Tests that need real Redis stream round-trips
should depend on the ``redis_client`` session-scoped fixture below;
the fixture auto-skips when Redis is unreachable (per the
``requires_network`` convention).

Why a fresh ``tests/integration/conftest.py`` rather than folding
into ``conftest_wireups.py``: the wireups module is T-0 platform
bootstrapping (DB, XDG, settings, mocks) and is pulled in by every
integration test. The Redis client is a narrow, optional dependency
that should NOT cost an import for the 200+ tests that don't touch
Redis. Keeping it in its own conftest file scopes the import to the
few tests that opt in via the ``redis_client`` parameter.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Iterator

import pytest


def _redis_reachable(host: str = "127.0.0.1", port: int = 6379) -> bool:
    """Return ``True`` when a TCP connection to ``host:port`` succeeds.

    Cheap pre-flight: avoids paying the coredis import cost in CI
    jobs that lack a local Redis. ``pytest.skip`` reasons are
    propagated by the caller.
    """
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def redis_client() -> Iterator:
    """Session-scoped coredis client backed by ``redis://127.0.0.1:6379/0``.

    Skips (rather than fails) when the local Redis is unreachable so
    the test is runnable on laptops without a running daemon. The
    ``requires_network`` marker in the consuming test makes the skip
    policy explicit.

    coredis 6.x requires explicit pool init via the async context
    manager — see :class:`oneiric.adapters.queue.redis_streams` for
    the same pattern. We bracket init/teardown in the fixture so
    consumers never see ``RuntimeError: Connection pool is not
    initialized``.
    """
    if not _redis_reachable():
        pytest.skip("Redis not reachable on 127.0.0.1:6379")

    # coredis is an optional dep — guard the import so a lean install
    # that omits the ``cache`` extra still collects this test (as a
    # skip, never as an import-time collection error).
    try:
        from coredis import Redis
    except ImportError as exc:  # pragma: no cover - exercised on lean installs
        pytest.skip(f"coredis not installed: {exc}")

    client = Redis.from_url("redis://127.0.0.1:6379/0")
    # coredis 6.x pool init MUST run inside the same async context
    # that uses the client. pytest-asyncio's session-scoped fixture
    # doesn't get a default loop, so we drive the init/teardown on
    # the current loop at fixture-yield time.
    try:
        asyncio.get_event_loop().run_until_complete(client.__aenter__())
    except RuntimeError:
        # No running loop at collection time (e.g. plain pytest
        # without asyncio_mode). Spin up a temporary loop.
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(client.__aenter__())
        finally:
            loop.close()

    try:
        yield client
    finally:
        # Teardown mirrors init: pick whichever loop the runtime
        # gives us. Suppress cleanup errors so a Redis hiccup at
        # teardown doesn't mask a real test failure.
        try:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    raise RuntimeError("loop running")
                loop.run_until_complete(client.__aexit__(None, None, None))
            except RuntimeError:
                tl = asyncio.new_event_loop()
                try:
                    tl.run_until_complete(client.__aexit__(None, None, None))
                finally:
                    tl.close()
        except Exception:
            pass
