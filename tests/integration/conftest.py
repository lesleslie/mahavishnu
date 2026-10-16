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

Phase G (v1.5 Bifrost spec): the ``bifrost_reachable`` and
``llama_server_reachable`` fixtures are the operator-side skip
guards promised by the plan's §5 Phase E (Bifrost) and §5 Phase G
(llama-server) risks. They run ``lsof -nP -iTCP:<port> -sTCP:LISTEN``
to probe port reachability and ``pytest.skip(...)`` when the service
is not running locally. e2e tests opt in via the fixture parameter;
the skip is silent (not a failure) per the plan's risk-mitigation
language.
"""

from __future__ import annotations

import asyncio
import shutil
import socket
import subprocess

import pytest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


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


def _port_listening(port: int) -> bool:
    """Return ``True`` when ``lsof`` reports a LISTEN on the given port.

    Uses ``lsof -nP -iTCP:<port> -sTCP:LISTEN`` (the project's
    pre-flight convention for the Bifrost / llama-server risk
    mitigations). Falls back to a TCP-connect probe when ``lsof`` is
    not on PATH (e.g. minimal CI containers) so the skip-fixture is
    still useful in lean environments.
    """
    if shutil.which("lsof"):
        try:
            result = subprocess.run(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                capture_output=True,
                timeout=2,
                check=False,
            )
            # lsof returns 0 with a header line + at least one match
            # when something is listening. Empty stdout (header only)
            # means nothing is listening.
            return bool(result.stdout.strip().splitlines()[1:])
        except (OSError, subprocess.TimeoutExpired):
            pass
    # Fallback: cheap TCP connect probe.
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def bifrost_reachable() -> bool:
    """Session-scoped guard: True when Bifrost is listening on :8471.

    e2e tests that depend on the Bifrost gateway being up should
    take this fixture; the fixture skips the test (rather than
    fails) when the gateway is not running locally. The skip
    reason follows the project convention ``pytest.skip(reason)``
    so the operator-visible skip message names the missing service.
    """
    if not _port_listening(8471):
        pytest.skip("Bifrost gateway not reachable on 127.0.0.1:8471")
    return True


@pytest.fixture(scope="session")
def llama_server_reachable() -> bool:
    """Session-scoped guard: True when llama-server is listening on :8081.

    Phase G: the local llama-server e2e tests (background routing,
    classify routing, health sub-shape) depend on the launchd plist
    actually running the process. This fixture skips when the
    process is absent. Per the plan §5 Phase G exit criteria, the
    e2e test ``test_llama_server_health_endpoint`` IS the gate
    that catches a future plist regression; this fixture is the
    general-purpose skip-guard for the other 5 e2e tests in
    ``test_bifrost_local_provider_e2e.py``.
    """
    if not _port_listening(8081):
        pytest.skip("llama-server not reachable on 127.0.0.1:8081")
    return True


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
        except Exception:  # best-effort operation — broad catch is the documented contract  # best-effort operation — broad catch is the documented contract  # noqa: BLE001, RUF100
            pass
