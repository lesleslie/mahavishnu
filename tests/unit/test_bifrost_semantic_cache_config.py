"""Static guards for the Bifrost semantic cache configuration.

Why this file exists
--------------------
The Bifrost semantic cache shipped enabled but *non-functional* for two
independent reasons, neither of which any existing test covered:

1. **Direct-hash mode.** ``plugins[].config.dimension`` was ``1``. Per
   Bifrost's published config schema, ``dimension: 1`` means "direct
   (hash-based) caching without an embedding provider", and the schema
   *forbids* ``embedding_model`` in that mode. The plugin was
   structurally incapable of semantic matching while reporting
   ``enabled: true``.
2. **A local model allowlist.** The semantic cache plugin generates
   embeddings through ``providers.openai``, but that provider's only
   key declared ``models: [gpt-5.4, gpt-5.4-mini, gpt-5.3-codex]``.
   Bifrost resolves keys through that allowlist *before* dispatching
   upstream, so every embedding attempt failed locally with
   ``no_key_supports_model`` -- the request never reached OpenAI, so
   no amount of upstream credit could fix it.

The observable symptom was a cache that stored 205 entries with
**empty** ``embedding`` fields and logged ``semantic search skipped:
failed to generate embedding`` on every request. The direct (exact
match) path kept working the whole time, which is why the failure was
easy to miss.

These tests are pure config assertions: no network, no gateway, no
credentials. They run in the fast unit suite and fail loudly if either
regression returns.

What each test pins
-------------------
- ``test_semantic_cache_plugin_is_enabled`` -- the plugin is registered.
- ``test_semantic_cache_is_not_in_direct_hash_mode`` -- ``dimension >= 2``.
- ``test_semantic_cache_declares_provider_and_embedding_model`` -- the
  schema requires both together.
- ``test_embedding_model_is_in_provider_key_allowlist`` -- **the bug**.
  The embedding model must appear in the ``models`` list of at least
  one key on the configured embedding provider.
- ``test_embedding_dimension_matches_model`` -- the Redis FT index is
  created with a fixed ``dim``; a mismatch makes the vector store
  reject writes, and the index cannot be resized in place.
- ``test_semantic_cache_threshold_is_a_valid_cosine`` -- in ``(0, 1]``.
- ``test_semantic_cache_has_default_cache_key`` -- without it,
  ``resolveCacheKey`` returns ``False`` and caching is disabled for
  every request that does not send an explicit ``x-bf-cache-key``.
- ``test_conversation_history_threshold_is_set`` -- the default of 3
  skips caching entirely once a conversation exceeds 3 messages, which
  disables the cache for essentially all agentic traffic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# All tests in this module are unit tests; mark them so the
# integration selector can skip them in fast feedback runs.
pytestmark = pytest.mark.unit

TEMPLATE = Path(__file__).resolve().parents[2] / "config" / "bifrost" / "config.template.json"

#: Native output dimensionality of the embedding models Bifrost is
#: configured with. The Redis Stack vector index is created with a
#: fixed ``dim``; RediSearch cannot resize an existing VECTOR
#: attribute, so a mismatch between this table and the configured
#: ``dimension`` breaks cache *writes* (not just reads).
EMBEDDING_MODEL_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


@pytest.fixture(scope="module")
def template() -> dict[str, Any]:
    """The repo's Bifrost config template -- the durable source of truth.

    ``config/bifrost/config.template.json`` is re-seeded into
    ``~/.config/bifrost/config.json`` by ``mahavishnu bifrost
    rebootstrap`` (``mahavishnu/bifrost/gateway.py`` copies it on
    first-run seed). Asserting against the template -- not the live
    config -- means the guard survives an operator editing their live
    copy, and still catches a regression landing in the repo.
    """
    if not TEMPLATE.exists():
        pytest.skip(f"Bifrost config template not present at {TEMPLATE}")
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def plugin_config(template: dict[str, Any]) -> dict[str, Any]:
    """The ``semantic_cache`` plugin's ``config`` block."""
    for plugin in template.get("plugins", []):
        if plugin.get("name") == "semantic_cache":
            config = plugin.get("config")
            assert isinstance(config, dict), "semantic_cache plugin must carry a config object"
            return config
    pytest.skip("semantic_cache plugin is not present in the Bifrost config template")


@pytest.fixture(scope="module")
def provider_keys(template: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Map of provider name -> that provider's key entries."""
    providers = template.get("providers", {})
    result: dict[str, list[dict[str, Any]]] = {}
    for name, provider in providers.items():
        keys = provider.get("keys") or []
        result[name] = [k for k in keys if isinstance(k, dict)]
    return result


def test_semantic_cache_plugin_is_enabled(template: dict[str, Any]) -> None:
    """The ``semantic_cache`` plugin must be registered and enabled."""
    plugins = {p.get("name"): p for p in template.get("plugins", []) if isinstance(p, dict)}
    assert "semantic_cache" in plugins, "semantic_cache plugin missing from the Bifrost config"
    assert plugins["semantic_cache"].get("enabled") is True, (
        "semantic_cache plugin is present but disabled -- the cache would be inert"
    )


def test_semantic_cache_is_not_in_direct_hash_mode(plugin_config: dict[str, Any]) -> None:
    """``dimension`` must be > 1; ``1`` means direct-hash mode.

    Bifrost's schema states the semantic cache plugin's ``dimension``
    of 1 selects "direct (hash-based) caching without an embedding
    provider", and in that mode ``embedding_model`` is not allowed.
    A plugin parked in direct mode stores exact-match entries but can
    never perform a similarity lookup.
    """
    dimension = plugin_config.get("dimension")
    assert isinstance(dimension, int), f"dimension must be an int, got {dimension!r}"
    assert dimension > 1, (
        f"semantic_cache dimension is {dimension}; dimension=1 selects direct-hash "
        "mode, in which the plugin performs no similarity matching at all"
    )


def test_semantic_cache_declares_provider_and_embedding_model(
    plugin_config: dict[str, Any],
) -> None:
    """``provider`` and ``embedding_model`` must both be set.

    Bifrost's schema makes these two mutually dependent: when
    ``provider`` is set, ``embedding_model`` becomes required and
    ``dimension`` must be >= 2. Without both, the plugin falls back to
    the direct path even though it is nominally "enabled".
    """
    provider = plugin_config.get("provider")
    embedding_model = plugin_config.get("embedding_model")
    assert isinstance(provider, str) and provider, (
        "semantic_cache has no embedding provider configured -- the plugin will "
        "fall back to direct-hash mode"
    )
    assert isinstance(embedding_model, str) and embedding_model, (
        "semantic_cache has no embedding_model configured -- Bifrost's schema "
        "requires it whenever provider is set"
    )


def test_embedding_model_is_in_provider_key_allowlist(
    plugin_config: dict[str, Any],
    provider_keys: dict[str, list[dict[str, Any]]],
) -> None:
    """The embedding model must be allowed by a key on the embedding provider.

    This is the regression that broke the cache. Bifrost resolves a
    key *before* dispatching upstream, and a key only serves models
    named in its ``models`` list. With ``text-embedding-3-small``
    absent from the ``openai`` provider's allowlist, every embedding
    attempt failed locally with ``no_key_supports_model`` and the
    request never reached OpenAI -- so upstream billing was never
    even in play.
    """
    provider = plugin_config["provider"]
    embedding_model = plugin_config["embedding_model"]

    keys = provider_keys.get(provider, [])
    assert keys, f"provider {provider!r} has no key entries in the Bifrost config"

    allowed: set[str] = set()
    for key in keys:
        models = key.get("models")
        if isinstance(models, list):
            allowed.update(str(m) for m in models)

    assert embedding_model in allowed, (
        f"embedding model {embedding_model!r} is not in the {provider!r} provider's "
        f"key allowlist {sorted(allowed)!r}. Bifrost will reject every embedding "
        "request locally with 'no_key_supports_model' before it reaches the "
        "provider, so the semantic cache can never store a vector."
    )


def test_embedding_dimension_matches_model(plugin_config: dict[str, Any]) -> None:
    """``dimension`` must equal the embedding model's native output size.

    The Redis Stack index backing the cache is created with a fixed
    ``dim`` (1536 today) and RediSearch cannot resize a VECTOR
    attribute in place. A dimension that disagrees with the model
    makes the vector store reject writes.
    """
    embedding_model = plugin_config["embedding_model"]
    dimension = plugin_config["dimension"]

    expected = EMBEDDING_MODEL_DIMENSIONS.get(embedding_model)
    if expected is None:
        pytest.skip(
            f"no known native dimension for embedding model {embedding_model!r}; "
            "add it to EMBEDDING_MODEL_DIMENSIONS to assert on it"
        )
    assert dimension == expected, (
        f"semantic_cache dimension is {dimension} but {embedding_model!r} emits "
        f"{expected}-dimensional vectors; the Redis vector index is created with a "
        "fixed dim and cannot be resized in place"
    )


def test_semantic_cache_threshold_is_a_valid_cosine(plugin_config: dict[str, Any]) -> None:
    """The similarity threshold must be a cosine value in ``(0, 1]``."""
    threshold = plugin_config.get("threshold")
    assert isinstance(threshold, (int, float)), f"threshold must be numeric, got {threshold!r}"
    assert 0 < threshold <= 1, f"threshold {threshold} is outside the cosine range (0, 1]"


def test_semantic_cache_has_default_cache_key(plugin_config: dict[str, Any]) -> None:
    """A default cache key is required for the cache to engage unattended.

    Bifrost's ``resolveCacheKey`` falls back to the request's
    ``x-bf-cache-key`` header and then to the plugin's
    ``default_cache_key``. With neither set it returns ``False``, and
    the plugin's pre-LLM hook exits before performing any lookup or
    write -- so the cache is silently inert for every client that does
    not know to send the header.
    """
    default_cache_key = plugin_config.get("default_cache_key")
    assert isinstance(default_cache_key, str) and default_cache_key, (
        "semantic_cache has no default_cache_key; caching is disabled for every "
        "request that does not send an explicit x-bf-cache-key header"
    )


def test_conversation_history_threshold_is_set(plugin_config: dict[str, Any]) -> None:
    """The conversation-history gate must be raised above Bifrost's default of 3.

    Bifrost skips caching *entirely* (both the direct and the
    semantic path) for requests whose conversation exceeds this many
    messages. Agentic clients resend the full transcript every turn,
    so the default of 3 disables the cache for nearly all real
    traffic.
    """
    threshold = plugin_config.get("conversation_history_threshold")
    assert isinstance(threshold, int), (
        f"conversation_history_threshold must be an int, got {threshold!r}"
    )
    assert threshold > 3, (
        f"conversation_history_threshold is {threshold}; Bifrost's default of 3 "
        "skips caching for any request with more than 3 messages, which disables "
        "the cache for essentially all agentic traffic"
    )
