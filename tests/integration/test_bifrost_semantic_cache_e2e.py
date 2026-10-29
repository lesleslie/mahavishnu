"""End-to-end verification that the Bifrost semantic cache actually caches.

Why this file exists
--------------------
The cache was live, enabled, backed by a Redis Stack vector store,
and serving *something* -- while performing no semantic matching at
all. The direct (exact-match) path kept working, which is exactly
why the failure survived: a smoke test that sends one request and
gets a 200 sees a healthy cache.

These tests assert the behaviour a user actually cares about, against
the running gateway:

1. ``test_embedding_model_is_callable`` -- the configured embedding
   model is reachable with the configured credential. This is the
   "is there credit / is the key valid" check, isolated from the
   gateway so a failure points at the credential rather than at the
   cache.
2. ``test_live_config_is_in_semantic_mode`` -- the *running* config
   (not just the repo template) is in semantic mode and its embedding
   model is allowed by the provider's key allowlist.
3. ``test_exact_repeat_is_a_direct_cache_hit`` -- the same prompt
   twice: the second is served from cache.
4. ``test_paraphrase_is_a_semantic_cache_hit`` -- a *reworded* prompt:
   the second is served from cache via **vector similarity**, at or
   above the configured threshold. This is the test the original bug
   made impossible.
5. ``test_unrelated_prompt_does_not_hit_the_cache`` -- a prompt about
   something else entirely must **not** be served from the cache.
   Guards the false-positive risk that a similarity threshold
   introduces.

Skip behaviour
--------------
Every test skips (rather than fails) when the gateway, the
credential, or the embedding provider is unavailable, matching the
project's ``bifrost_reachable`` convention in
``tests/integration/conftest.py``. A missing local dependency is not
a defect in the cache.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any
import uuid

import pytest
import requests

pytestmark = [pytest.mark.integration, pytest.mark.requires_network]

BIFROST_BASE = os.environ.get("BIFROST_BASE_URL", "http://127.0.0.1:8471")
LIVE_CONFIG = Path.home() / ".config" / "bifrost" / "config.json"

#: Candidate upstream models for the LLM call, most-preferred first.
#: The local llama-server is preferred because it is free and
#: hermetic; MiniMax is the fallback. The *response content* is
#: irrelevant to every assertion here -- only the cache headers
#: matter -- so a deterministic local model is ideal.
CANDIDATE_MODELS = (
    "llama-server/qwen3-8b-q4_k_m",
    "minimax-openai/MiniMax-M3",
)

#: Per-request timeout. Generous, because the upstream is not under the
#: test's control: the local llama-server degrades to seconds-per-token
#: when the machine is loaded.
REQUEST_TIMEOUT = 300

#: Timeout for the *probe* that selects an upstream model. Kept short so
#: that a starved local model falls through to the next candidate instead
#: of stalling the whole suite. The probe only has to answer "are you
#: responsive?", not "are you fast?".
PROBE_TIMEOUT = 45

#: How long to keep re-requesting while waiting for the plugin's
#: asynchronous cache write to land.
CACHE_WRITE_TIMEOUT = 180


@pytest.fixture(scope="module")
def live_config() -> dict[str, Any]:
    """The Bifrost config the running gateway actually loaded."""
    if not LIVE_CONFIG.exists():
        pytest.skip(f"live Bifrost config not present at {LIVE_CONFIG}")
    return json.loads(LIVE_CONFIG.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def virtual_key() -> str:
    """The gateway's virtual key, from the environment or the secret store."""
    from mahavishnu.bifrost.gateway import load_secrets_env

    key = os.environ.get("BIFROST_VIRTUAL_KEY", "").strip()
    if not key:
        key = load_secrets_env().get("BIFROST_VIRTUAL_KEY", "").strip()
    if not key:
        pytest.skip("BIFROST_VIRTUAL_KEY is not available")
    return key


@pytest.fixture(scope="module")
def semantic_cache_config(live_config: dict[str, Any]) -> dict[str, Any]:
    """The ``semantic_cache`` plugin config from the live gateway config."""
    for plugin in live_config.get("plugins", []):
        if plugin.get("name") == "semantic_cache":
            config = plugin.get("config")
            assert isinstance(config, dict)
            return config
    pytest.skip("semantic_cache plugin is not present in the live Bifrost config")


@pytest.fixture(scope="module")
def embedding_model(semantic_cache_config: dict[str, Any]) -> str:
    """The embedding model the plugin is configured to use."""
    model = semantic_cache_config.get("embedding_model")
    if not isinstance(model, str) or not model:
        pytest.skip("live semantic_cache config declares no embedding_model")
    return model


@pytest.fixture(scope="module")
def cache_threshold(semantic_cache_config: dict[str, Any]) -> float:
    """The configured cosine similarity threshold."""
    threshold = semantic_cache_config.get("threshold")
    if not isinstance(threshold, (int, float)):
        pytest.skip("live semantic_cache config declares no numeric threshold")
    return float(threshold)


@pytest.fixture(scope="module")
def upstream_model(virtual_key: str) -> str:
    """First candidate upstream model the gateway can serve *responsively*.

    The probe is deliberately time-boxed. The local llama-server is free
    and hermetic, but it degrades to seconds-per-token when the machine
    is loaded -- and a slow upstream must not stall the suite. A model
    that cannot answer the probe within ``PROBE_TIMEOUT`` is skipped in
    favour of the next candidate.
    """
    for model in CANDIDATE_MODELS:
        try:
            body = _post_chat(
                virtual_key,
                model,
                "reply with the single word PONG",
                "probe-model-select",
                timeout=PROBE_TIMEOUT,
            )
        except requests.exceptions.Timeout:
            continue
        if body.get("status") == 200 and "choices" in body.get("payload", {}):
            return model
    pytest.skip(
        "no candidate upstream model responded within "
        f"{PROBE_TIMEOUT}s through the Bifrost gateway; "
        f"tried {list(CANDIDATE_MODELS)}"
    )


def _post_chat(
    virtual_key: str,
    model: str,
    prompt: str,
    cache_key: str,
    timeout: int = REQUEST_TIMEOUT,
) -> dict[str, Any]:
    """POST a chat completion through Bifrost and return status/headers/payload.

    The ``x-bf-cache-key`` header gives the request an explicit cache
    bucket. Without it, the plugin falls back to ``default_cache_key``
    and the request would land in the shared bucket alongside real
    traffic -- which would make these assertions depend on whatever
    else happens to be cached.
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 16,
    }
    response = requests.post(
        f"{BIFROST_BASE}/v1/chat/completions",
        json=payload,
        headers={
            "x-bf-vk": virtual_key,
            "x-bf-cache-key": cache_key,
            "Content-Type": "application/json",
        },
        timeout=timeout,
    )
    try:
        parsed = response.json()
    except ValueError:
        parsed = {}
    return {"status": response.status_code, "headers": response.headers, "payload": parsed}


def _cache_headers(result: dict[str, Any]) -> dict[str, str]:
    """Extract the ``X-Bifrost-Cache-*`` response headers."""
    headers = result.get("headers") or {}
    return {k: v for k, v in headers.items() if k.lower().startswith("x-bifrost-cache")}


def _poll_for_hit(
    virtual_key: str,
    model: str,
    prompt: str,
    cache_key: str,
    expected_type: str,
    timeout: float = CACHE_WRITE_TIMEOUT,
) -> dict[str, Any]:
    """Repeat a request until the expected cache hit appears.

    The plugin flushes a cache entry **asynchronously** after the
    response is delivered, so the entry is not necessarily readable on
    the very next request. Against a fast local provider the gap is
    large enough to matter: the repeat arrives before the write lands
    and sees a miss.

    Polling turns that race into a wait instead of a flake. The budget
    has to cover the upstream's own latency as well as the write: a
    single poll iteration is one full round trip.

    The final result is returned so the caller can assert on its headers.
    """
    deadline = time.monotonic() + timeout
    result: dict[str, Any] = {}
    while time.monotonic() < deadline:
        result = _post_chat(virtual_key, model, prompt, cache_key)
        headers = _cache_headers(result)
        if headers.get("X-Bifrost-Cache-Hit") == "true":
            if headers.get("X-Bifrost-Cache-Hit-Type") == expected_type:
                break
        time.sleep(0.5)
    return result


def test_embedding_model_is_callable(embedding_model: str) -> None:
    """The configured embedding model answers a real embeddings request.

    Isolates the credential from the cache: if this fails, the cause
    is the key or the account, not Bifrost's routing. A 400
    ``maximum context length`` here would mean the model is reachable
    but the input is too large -- a different failure with a different
    fix.
    """
    from mahavishnu.bifrost.gateway import load_secrets_env

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        api_key = load_secrets_env().get("OPENAI_API_KEY", "").strip()
    if not api_key:
        pytest.skip("OPENAI_API_KEY is not available")

    response = requests.post(
        "https://api.openai.com/v1/embeddings",
        json={"model": embedding_model, "input": "semantic cache liveness probe"},
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=30,
    )
    assert response.status_code == 200, (
        f"embedding model {embedding_model!r} is not usable with the configured "
        f"credential (HTTP {response.status_code}): {response.text[:300]}"
    )
    data = response.json()
    vector = data["data"][0]["embedding"]
    assert len(vector) > 0, "embedding response carried an empty vector"


def test_live_config_is_in_semantic_mode(
    live_config: dict[str, Any],
    semantic_cache_config: dict[str, Any],
    embedding_model: str,
) -> None:
    """The running gateway is configured for semantic matching, not direct-hash.

    Guards against a live config that drifted from the repo template
    -- ``mahavishnu bifrost rebootstrap`` re-seeds it, but an operator
    can also edit ``~/.config/bifrost/config.json`` directly.
    """
    dimension = semantic_cache_config.get("dimension")
    assert isinstance(dimension, int) and dimension > 1, (
        f"live semantic_cache dimension is {dimension!r}; dimension=1 is "
        "direct-hash mode, where the plugin performs no similarity matching"
    )
    provider = semantic_cache_config.get("provider")
    assert isinstance(provider, str) and provider, (
        "live semantic_cache config declares no embedding provider"
    )

    keys = (live_config.get("providers") or {}).get(provider, {}).get("keys") or []
    allowed: set[str] = set()
    for key in keys:
        models = key.get("models")
        if isinstance(models, list):
            allowed.update(str(m) for m in models)
    assert embedding_model in allowed, (
        f"live {provider!r} provider does not allow {embedding_model!r}; Bifrost "
        "rejects the embedding locally with 'no_key_supports_model' and never "
        "reaches the provider"
    )


def test_exact_repeat_is_a_direct_cache_hit(
    virtual_key: str,
    upstream_model: str,
) -> None:
    """The same prompt sent twice is served from cache the second time."""
    cache_key = f"test-direct-{uuid.uuid4().hex[:12]}"
    prompt = f"cache probe {cache_key}: reply with the single word PONG"

    first = _post_chat(virtual_key, upstream_model, prompt, cache_key)
    assert first["status"] == 200, f"seed request failed: {first['payload']}"

    second = _poll_for_hit(virtual_key, upstream_model, prompt, cache_key, "direct")
    assert second["status"] == 200, f"repeat request failed: {second['payload']}"

    headers = _cache_headers(second)
    assert headers.get("X-Bifrost-Cache-Hit") == "true", (
        f"repeat request was not served from the cache; headers were {headers}"
    )
    assert headers.get("X-Bifrost-Cache-Hit-Type") == "direct", (
        f"expected a direct (exact-match) hit, got {headers.get('X-Bifrost-Cache-Hit-Type')!r}"
    )


def test_paraphrase_is_a_semantic_cache_hit(
    virtual_key: str,
    upstream_model: str,
    embedding_model: str,
    cache_threshold: float,
) -> None:
    """A *reworded* prompt is served from cache via vector similarity.

    This is the behaviour that was completely absent while the cache
    reported itself enabled. The two prompts differ by one word, so
    they must not match the direct path -- only the embedding
    comparison can connect them.
    """
    cache_key = f"test-semantic-{uuid.uuid4().hex[:12]}"
    token = cache_key
    seed_prompt = f"semantic probe {token}: reply with the single word PONG"
    paraphrase = f"semantic probe {token}: please reply with the single word PONG"

    seed = _post_chat(virtual_key, upstream_model, seed_prompt, cache_key)
    assert seed["status"] == 200, f"seed request failed: {seed['payload']}"

    result = _poll_for_hit(virtual_key, upstream_model, paraphrase, cache_key, "semantic")
    assert result["status"] == 200, f"paraphrase request failed: {result['payload']}"

    headers = _cache_headers(result)
    assert headers.get("X-Bifrost-Cache-Hit") == "true", (
        f"paraphrase was not served from the cache; headers were {headers}. "
        "A semantic miss here means the embedding provider is unreachable or "
        "the embedding model is not allowed by the provider's key allowlist."
    )
    assert headers.get("X-Bifrost-Cache-Hit-Type") == "semantic", (
        f"expected a semantic (similarity) hit, got "
        f"{headers.get('X-Bifrost-Cache-Hit-Type')!r}; headers were {headers}"
    )
    assert headers.get("X-Bifrost-Cache-Model-Used") == embedding_model, (
        f"cache used embedding model {headers.get('X-Bifrost-Cache-Model-Used')!r}, "
        f"expected {embedding_model!r}"
    )

    similarity = headers.get("X-Bifrost-Cache-Similarity")
    assert similarity is not None, "semantic hit did not report a similarity score"
    assert float(similarity) >= cache_threshold, (
        f"similarity {similarity} is below the configured threshold {cache_threshold}"
    )


def test_unrelated_prompt_does_not_hit_the_cache(
    virtual_key: str,
    upstream_model: str,
) -> None:
    """A prompt about an unrelated subject must not be served from the cache.

    The mirror image of the paraphrase test. A similarity threshold is
    only safe if genuinely different prompts fall below it; without
    this assertion the cache could serve a stale answer for an
    unrelated request and every test above would still pass.
    """
    cache_key = f"test-negative-{uuid.uuid4().hex[:12]}"
    token = cache_key
    seed_prompt = f"negative probe {token}: reply with the single word PONG"

    seed = _post_chat(virtual_key, upstream_model, seed_prompt, cache_key)
    assert seed["status"] == 200, f"seed request failed: {seed['payload']}"

    # Wait until the seed is actually readable. Without this the
    # unrelated request below would miss trivially -- the cache would
    # hold nothing yet -- and the assertion would prove nothing.
    seeded = _poll_for_hit(virtual_key, upstream_model, seed_prompt, cache_key, "direct")
    assert _cache_headers(seeded).get("X-Bifrost-Cache-Hit") == "true", (
        "the seed request was never cached, so the negative assertion below would be vacuous"
    )

    unrelated = _post_chat(
        virtual_key,
        upstream_model,
        "What is the capital of France? Answer in one short sentence.",
        cache_key,
    )
    assert unrelated["status"] == 200, f"unrelated request failed: {unrelated['payload']}"

    headers = _cache_headers(unrelated)
    assert headers.get("X-Bifrost-Cache-Hit") != "true", (
        f"an unrelated prompt was served from the cache -- false positive; headers were {headers}"
    )
