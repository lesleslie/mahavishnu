"""End-to-end verification of the Bodai -> Bifrost path.

req: REQ-BIFROST-035, REQ-BIFROST-037

Two things were broken on this path, and neither was visible from the
gateway side (the gateway was healthy; the *callers* were wrong):

1. **Authentication.** The cloud worker routed its MiniMax provider to
   the gateway but authenticated with the *provider* key, which the
   gateway rejects with ``401 - virtual key is required``. Every Bodai
   call failed and silently fell through to the local provider.
2. **Cache mode.** ``BifrostLLMSettings.cache_mode`` had no consumer, so
   it never reached a request and the cache headers were never sent.

These tests drive the real ``CloudWorker`` against the running gateway.

Skip behaviour: the gateway, the credentials, and the upstream provider
must all be reachable; otherwise the test skips rather than fails.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
import urllib.error
import urllib.request
import uuid

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.requires_network]

GATEWAY = os.environ.get("BIFROST_BASE_URL", "http://127.0.0.1:8471")


def _load_credentials() -> dict[str, str]:
    """Read the operator credential store for the keys this path needs."""
    from mahavishnu.bifrost.gateway import load_secrets_env

    return load_secrets_env()


_CREDENTIAL_HEADERS = frozenset({"x-bf-vk", "authorization", "x-api-key"})


def _redact_headers(headers: dict[str, Any]) -> dict[str, Any]:
    """Return the headers with credential values masked.

    ``default_headers`` carries the gateway virtual key (``x-bf-vk``).
    Interpolating it into an assertion message would write the credential
    into the test output and into any CI log that captures it. Matching is
    case-insensitive because ``default_headers`` merges several sources and
    the casing is not guaranteed.
    """
    return {
        key: ("***" if key.lower() in _CREDENTIAL_HEADERS else value)
        for key, value in headers.items()
    }


@pytest.fixture(scope="module")
def credentials() -> dict[str, str]:
    """Secrets for the gateway and the upstream provider."""
    creds = _load_credentials()
    if not creds.get("BIFROST_VIRTUAL_KEY"):
        pytest.skip("BIFROST_VIRTUAL_KEY is not available")
    return creds


@pytest.fixture
def bodai_provider(credentials: dict[str, str], monkeypatch: pytest.MonkeyPatch):
    """The cloud worker's primary provider, built the way production builds it.

    Returns the ``OpenAICompatibleProvider`` the worker would use, so the
    test asserts on the headers that actually go out.
    """
    from oneiric.adapters.llm.bifrost import reset_router_for_tests

    monkeypatch.setenv("ONEIRIC_BIFROST_ENABLED", "true")
    monkeypatch.setenv("ONEIRIC_BIFROST_ROUTES", "claude_route,qwen_route")
    monkeypatch.setenv("ONEIRIC_BIFROST_BASE_URL", "http://127.0.0.1:8471/v1")
    monkeypatch.setenv("ONEIRIC_BIFROST_CACHE_MODE", "semantic")
    monkeypatch.setenv("BIFROST_VIRTUAL_KEY", credentials["BIFROST_VIRTUAL_KEY"])
    monkeypatch.setenv("MINIMAX_API_KEY", credentials.get("MINIMAX_API_KEY", "unset"))
    reset_router_for_tests()

    from mahavishnu.workers.cloud_worker import CloudWorkerConfig, _build_fallback_chain

    chain = _build_fallback_chain(CloudWorkerConfig())
    try:
        yield chain._providers[0]
    finally:
        # The oneiric router is a process-wide singleton that captures
        # its settings at construction. Resetting it only on setup would
        # leave the router reporting "enabled, gateway at :8471, cache
        # mode semantic" for the rest of the session -- even though
        # monkeypatch has reverted the environment. Every other repo file
        # that flips the router resets it in a paired teardown.
        reset_router_for_tests()


def test_bodai_provider_points_at_the_gateway(bodai_provider: Any) -> None:
    """The Bodai provider's base_url is the gateway, not MiniMax directly."""
    base_url = str(bodai_provider._config.base_url)
    assert base_url.rstrip("/").endswith("8471/v1"), (
        f"Bodai provider is not routed through the gateway: {base_url}"
    )


def test_bodai_provider_carries_the_virtual_key(bodai_provider: Any) -> None:
    """The provider carries ``x-bf-vk`` -- the gateway rejects anything else."""
    headers = bodai_provider._config.default_headers
    assert headers.get("x-bf-vk"), (
        "Bodai provider carries no virtual key; the gateway will answer "
        "'401 - virtual key is required'"
    )


def test_bodai_provider_carries_the_cache_mode(bodai_provider: Any) -> None:
    """``cache_mode`` reaches the request as a cache header."""
    headers = bodai_provider._config.default_headers
    assert headers.get("x-bf-cache-type") == "semantic", (
        f"cache_mode did not reach the request; headers were {_redact_headers(headers)}"
    )


async def test_cloud_worker_completes_through_the_gateway(
    bifrost_reachable: bool, credentials: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real ``CloudWorker.execute()`` succeeds against the gateway.

    Before the fix this failed with ``401 - virtual key is required`` and
    fell through to the local provider.
    """
    del bifrost_reachable
    monkeypatch.setenv("MINIMAX_API_KEY", credentials.get("MINIMAX_API_KEY", "unset"))

    from mahavishnu.workers.cloud_worker import CloudWorker, CloudWorkerConfig

    worker = CloudWorker(CloudWorkerConfig())
    await worker.start()
    result = await worker.execute({"prompt": "say the single word PONG", "max_tokens": 8})

    assert result.status.value == "completed", (
        f"Bodai call through the gateway failed: {result.error}"
    )
    assert result.output, "Bodai call through the gateway returned no output"


def test_bodai_headers_produce_a_cache_hit(bodai_provider: Any, bifrost_reachable: bool) -> None:
    """Headers built the Bodai way make the gateway serve from cache.

    The provider does not surface the gateway's response headers, so the
    request is replayed over HTTP with the same header set the worker
    sends. The second, differently-worded request must be served from
    the cache by similarity.
    """
    del bifrost_reachable
    headers = dict(bodai_provider._config.default_headers)
    model = bodai_provider._config.base_url.rstrip("/") + "/chat/completions"
    token = uuid.uuid4().hex[:12]
    bucket = f"bodai-e2e-{token}"

    def call(prompt: str) -> dict[str, str]:
        payload = json.dumps(
            {
                "model": "minimax-openai/MiniMax-M3",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 16,
            }
        ).encode()
        request_headers = {**headers, "x-bf-cache-key": bucket, "Content-Type": "application/json"}
        req = urllib.request.Request(model, data=payload, headers=request_headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return {k.lower(): v for k, v in resp.getheaders()}
        except urllib.error.HTTPError as exc:
            pytest.fail(
                f"gateway rejected the Bodai-style request: HTTP {exc.code} {exc.read()[:200]!r}"
            )
        except urllib.error.URLError as exc:
            # The gateway went away between the reachability check and the
            # request. That is an environment problem, not a defect in the
            # headers, so it skips rather than errors -- the module's
            # contract is that an unreachable gateway skips.
            pytest.skip(f"gateway became unreachable during the test: {exc.reason}")

    call(f"bodai cache probe {token}: reply with the single word PONG")

    # The plugin flushes a cache entry asynchronously, so the seed may
    # not be readable on the very next request. Poll for the hit. The
    # budget covers the upstream's latency as well as the write.
    deadline = time.monotonic() + 180.0
    repeat: dict[str, str] = {}
    while time.monotonic() < deadline:
        repeat = call(f"bodai cache probe {token}: please reply with the single word PONG")
        if repeat.get("x-bifrost-cache-hit") == "true":
            break
        time.sleep(0.5)

    assert repeat.get("x-bifrost-cache-hit") == "true", (
        f"Bodai-style headers did not produce a cache hit; headers were {repeat}"
    )
    assert repeat.get("x-bifrost-cache-hit-type") == "semantic", (
        f"expected a similarity hit, got {repeat.get('x-bifrost-cache-hit-type')!r}"
    )
