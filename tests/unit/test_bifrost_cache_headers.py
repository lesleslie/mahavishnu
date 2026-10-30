"""Unit tests for the Bifrost cache-header builder.

req: REQ-BIFROST-035, REQ-BIFROST-037

``BifrostLLMSettings.cache_mode`` was advisory-only: the
``mahavishnu/llm_gateway`` package that read it was deleted in commit
``03146be0``, so the setting never reached a request. These tests pin the
translation from a cache mode to the ``x-bf-cache-*`` headers the gateway
actually honours, and the virtual-key header that goes with them.

The header semantics themselves were determined empirically against the
running gateway (see
``docs/plans/2026-10-29-bifrost-bodai-cache-wiring.md`` §4.4):

- ``x-bf-cache-key`` selects the cache bucket.
- ``x-bf-cache-type`` narrows the lookup to ``direct`` or ``semantic``.
- ``x-bf-cache-no-store`` suppresses the cache **write**; reads still
  happen, because Bifrost exposes no header that suppresses the read.
"""

from __future__ import annotations

from typing import Any

import pytest

from mahavishnu.bifrost.cache_headers import (
    CACHE_KEY_HEADER,
    CACHE_NO_STORE_HEADER,
    CACHE_TYPE_HEADER,
    DEFAULT_CACHE_BUCKET,
    TRAFFIC_CLASS_AGNO_OPENAI,
    TRAFFIC_CLASS_WORKER,
    VIRTUAL_KEY_HEADER,
    build_cache_headers,
    build_gateway_headers,
    gateway_host_is_trusted,
    resolve_cache_bucket,
    resolve_cache_mode,
    resolve_virtual_key,
)

pytestmark = pytest.mark.unit

#: The gateway's own deployment address: loopback, so it may carry the
#: virtual key over plain HTTP.
LOOPBACK_URL = "http://127.0.0.1:8471/v1"


@pytest.fixture
def cache_mode(monkeypatch: pytest.MonkeyPatch):
    """Set the operator-visible ``cache_mode`` the way an operator would.

    ``BifrostLLMSettings`` reads the environment (``ONEIRIC_BIFROST_``
    prefix), so the test drives the real settings path rather than
    stubbing a router -- which would not exercise the code under test.
    """

    def _install(mode: str) -> None:
        monkeypatch.setenv("ONEIRIC_BIFROST_CACHE_MODE", mode)

    return _install


@pytest.fixture
def no_credential_store(monkeypatch: pytest.MonkeyPatch):
    """Make the operator credential store unreadable.

    Without this the tests reach the real ``~/.config/secrets.env``, which
    on a developer machine holds a live virtual key -- so a test that
    expects "no key" would depend on the machine it runs on.
    """
    import mahavishnu.bifrost.gateway as gateway_mod

    def _boom(*_args: Any, **_kwargs: Any) -> dict[str, str]:
        raise OSError("no credential store in this test")

    monkeypatch.setattr(gateway_mod, "load_secrets_env", _boom)


@pytest.mark.parametrize(
    ("mode", "expected_type"),
    [("direct", "direct"), ("semantic", "semantic")],
)
def test_cache_type_header_narrows_the_lookup(mode: str, expected_type: str) -> None:
    """``direct`` / ``semantic`` map onto ``x-bf-cache-type``."""
    headers = build_cache_headers(mode)  # type: ignore[arg-type]
    assert headers[CACHE_TYPE_HEADER] == expected_type
    assert CACHE_NO_STORE_HEADER not in headers


def test_off_mode_suppresses_the_write() -> None:
    """``off`` maps onto ``x-bf-cache-no-store``, not onto a cache type."""
    headers = build_cache_headers("off")
    assert headers[CACHE_NO_STORE_HEADER] == "true"
    assert CACHE_TYPE_HEADER not in headers


def test_off_mode_cannot_be_served_from_a_cache() -> None:
    """``off`` must not be answered out of the cache.

    Bifrost v2.4.0 has no header that suppresses a cache *read*:
    ``x-bf-cache-no-store`` is documented upstream as "skip writing the
    response to cache (still served from cache on hit)". A mode named
    ``off`` that still performs cross-session lookups is a retention
    control that reads as a privacy control and is not one.

    The bucket is what closes it. The cache key is encoded into the
    direct cache ID (``generateDirectCacheID``) and is an equality
    filter on the semantic search (``cache_key``), so a bucket nothing
    was ever written to cannot be hit on either path. ``off`` therefore
    points at a bucket of its own, and two ``off`` requests never share
    one.
    """
    first = build_cache_headers("off")
    second = build_cache_headers("off")

    assert first[CACHE_KEY_HEADER] != second[CACHE_KEY_HEADER], (
        "two 'off' requests shared a bucket; a bucket another request wrote to "
        "would be served to it"
    )
    assert first[CACHE_KEY_HEADER] != DEFAULT_CACHE_BUCKET
    assert first[CACHE_KEY_HEADER] != resolve_cache_bucket("", None), (
        "'off' pointed at the derived bucket; a response cached under it would be "
        "served to a request that asked for no cache"
    )


def test_every_mode_carries_a_cache_bucket() -> None:
    """The cache key header is always present -- it selects the bucket."""
    for mode in ("off", "direct", "semantic"):
        headers = build_cache_headers(mode)  # type: ignore[arg-type]
        assert CACHE_KEY_HEADER in headers


def test_the_bucket_cannot_be_chosen_by_the_caller() -> None:
    """A caller-chosen bucket is a caller-chosen *selector*.

    Whoever holds a credential could name another bucket and read what
    is in it, so the bucket is derived rather than passed in. The
    keyword-only signature is what enforces that.
    """
    with pytest.raises(TypeError):
        build_cache_headers("semantic", "tenant-a")  # type: ignore[call-arg]


def test_the_traffic_class_separates_the_buckets() -> None:
    """Two protocol surfaces must not share a bucket."""
    worker = build_cache_headers("semantic", traffic_class=TRAFFIC_CLASS_WORKER)
    agno = build_cache_headers("semantic", traffic_class=TRAFFIC_CLASS_AGNO_OPENAI)
    assert worker[CACHE_KEY_HEADER] != agno[CACHE_KEY_HEADER]
    assert worker[CACHE_KEY_HEADER] != DEFAULT_CACHE_BUCKET


def test_a_blank_traffic_class_still_yields_a_bucket() -> None:
    """A missing traffic class does not fall back to the shared bucket."""
    headers = build_cache_headers("direct", traffic_class="   ")
    assert CACHE_KEY_HEADER in headers
    assert headers[CACHE_KEY_HEADER] != DEFAULT_CACHE_BUCKET


def test_resolve_cache_mode_reads_the_settings(cache_mode: Any) -> None:
    """The mode comes from the Oneiric Bifrost settings."""
    cache_mode("semantic")
    assert resolve_cache_mode() == "semantic"


def test_resolve_cache_mode_falls_back_to_off(cache_mode: Any) -> None:
    """An unknown mode is treated as ``off`` -- never as "cache everything"."""
    cache_mode("something-else")
    assert resolve_cache_mode() == "off"


def test_resolve_cache_mode_survives_broken_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Settings that cannot be loaded must not silently enable caching."""
    import oneiric.adapters.llm.bifrost as bifrost_mod

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("settings unavailable")

    monkeypatch.setattr(bifrost_mod, "BifrostLLMSettings", _boom)
    assert resolve_cache_mode() == "off"


def test_resolve_virtual_key_prefers_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The environment wins over the credential store."""
    monkeypatch.setenv("BIFROST_VIRTUAL_KEY", "sk-bf-from-env")
    assert resolve_virtual_key() == "sk-bf-from-env"


def test_resolve_virtual_key_is_none_when_unavailable(
    monkeypatch: pytest.MonkeyPatch, no_credential_store: None
) -> None:
    """No virtual key anywhere means ``None``, not an empty string."""
    monkeypatch.delenv("BIFROST_VIRTUAL_KEY", raising=False)
    assert resolve_virtual_key() is None


def test_resolve_virtual_key_falls_back_to_the_credential_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A launchd-started process inherits no environment, so the file is read."""
    monkeypatch.delenv("BIFROST_VIRTUAL_KEY", raising=False)
    import mahavishnu.bifrost.gateway as gateway_mod

    monkeypatch.setattr(
        gateway_mod,
        "load_secrets_env",
        lambda keys=None: {"BIFROST_VIRTUAL_KEY": "sk-bf-from-file"},
    )
    assert resolve_virtual_key() == "sk-bf-from-file"


def test_gateway_headers_carry_the_virtual_key(
    cache_mode: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gateway-routed request must carry ``x-bf-vk``.

    Bifrost rejects a provider key with ``401 - virtual key is required``.
    """
    monkeypatch.setenv("BIFROST_VIRTUAL_KEY", "sk-bf-test-key")
    cache_mode("semantic")
    headers = build_gateway_headers(LOOPBACK_URL)
    assert headers[VIRTUAL_KEY_HEADER] == "sk-bf-test-key"
    assert headers[CACHE_TYPE_HEADER] == "semantic"


def test_cache_headers_survive_a_missing_virtual_key(
    cache_mode: Any, monkeypatch: pytest.MonkeyPatch, no_credential_store: None
) -> None:
    """A missing credential must not invert ``cache_mode``.

    This is the failure the coupling caused: with no virtual key the whole
    header set came back empty, so no ``x-bf-cache-no-store`` was sent and
    the gateway resolved the bucket from its own ``default_cache_key`` and
    wrote the prompt and response into the shared cache -- the exact
    opposite of ``cache_mode: off``.

    The bucket is still derived rather than shared, so a deployment with
    no credential configured does not fall back into the fleet-wide
    namespace -- and ``off`` points at a bucket of its own, so it cannot
    be answered out of a cache at all.
    """
    monkeypatch.delenv("BIFROST_VIRTUAL_KEY", raising=False)
    cache_mode("off")
    headers = build_gateway_headers(LOOPBACK_URL)
    assert VIRTUAL_KEY_HEADER not in headers
    assert headers[CACHE_NO_STORE_HEADER] == "true"
    assert headers[CACHE_KEY_HEADER] != DEFAULT_CACHE_BUCKET
    assert headers[CACHE_KEY_HEADER] != resolve_cache_bucket("", None)


# ---------------------------------------------------------------------------
# The bucket is derived, not chosen
# ---------------------------------------------------------------------------


def test_the_bucket_is_never_the_shared_default(
    cache_mode: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Production traffic must not share the fleet-wide namespace.

    The shared ``default`` bucket puts every request in one namespace.
    With the semantic cache's ``exclude_system_prompt: true`` -- which
    drops the system prompt from the cache key -- two agents with
    different personas but the same user turn collide, and one is served
    the other's cached response.
    """
    monkeypatch.setenv("BIFROST_VIRTUAL_KEY", "sk-bf-test-key")
    cache_mode("semantic")
    headers = build_gateway_headers(
        LOOPBACK_URL, traffic_class=TRAFFIC_CLASS_WORKER
    )
    assert headers[CACHE_KEY_HEADER] != DEFAULT_CACHE_BUCKET


def test_different_traffic_classes_get_different_buckets(
    cache_mode: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same user turn over two protocol surfaces must not collide."""
    monkeypatch.setenv("BIFROST_VIRTUAL_KEY", "sk-bf-test-key")
    cache_mode("semantic")
    worker = build_gateway_headers(
        LOOPBACK_URL, traffic_class=TRAFFIC_CLASS_WORKER
    )
    agno = build_gateway_headers(
        LOOPBACK_URL, traffic_class=TRAFFIC_CLASS_AGNO_OPENAI
    )
    assert worker[CACHE_KEY_HEADER] != agno[CACHE_KEY_HEADER]


def test_different_principals_get_different_buckets(
    cache_mode: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second virtual key gets its own namespace, with no code change."""
    cache_mode("semantic")
    monkeypatch.setenv("BIFROST_VIRTUAL_KEY", "sk-bf-key-one")
    first = build_gateway_headers(
        LOOPBACK_URL, traffic_class=TRAFFIC_CLASS_WORKER
    )
    monkeypatch.setenv("BIFROST_VIRTUAL_KEY", "sk-bf-key-two")
    second = build_gateway_headers(
        LOOPBACK_URL, traffic_class=TRAFFIC_CLASS_WORKER
    )
    assert first[CACHE_KEY_HEADER] != second[CACHE_KEY_HEADER]


def test_the_bucket_is_stable_for_one_principal(
    cache_mode: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A derived bucket still has to be stable, or the cache never hits."""
    monkeypatch.setenv("BIFROST_VIRTUAL_KEY", "sk-bf-test-key")
    cache_mode("semantic")
    first = build_gateway_headers(
        LOOPBACK_URL, traffic_class=TRAFFIC_CLASS_WORKER
    )
    second = build_gateway_headers(
        LOOPBACK_URL, traffic_class=TRAFFIC_CLASS_WORKER
    )
    assert first[CACHE_KEY_HEADER] == second[CACHE_KEY_HEADER]


def test_the_credential_does_not_appear_in_the_bucket(
    cache_mode: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bucket travels in a header that gets logged."""
    monkeypatch.setenv("BIFROST_VIRTUAL_KEY", "sk-bf-super-secret-key")
    cache_mode("semantic")
    headers = build_gateway_headers(
        LOOPBACK_URL, traffic_class=TRAFFIC_CLASS_WORKER
    )
    assert "sk-bf-super-secret-key" not in headers[CACHE_KEY_HEADER]


def test_the_traffic_class_is_sanitised() -> None:
    """A traffic class is an inert token, not a header injection."""
    bucket = resolve_cache_bucket("Worker Pool; DROP", "sk-bf-test-key")
    assert bucket.startswith("worker-pool-drop:")
    assert ";" not in bucket
    assert " " not in bucket


def test_virtual_key_is_withheld_from_an_untrusted_transport(
    cache_mode: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain-HTTP remote host does not get the gateway credential.

    The virtual key can spend money through the gateway's provider keys
    and read the shared cache; sending it in cleartext across a network
    hop would expose it.
    """
    monkeypatch.setenv("BIFROST_VIRTUAL_KEY", "sk-bf-test-key")
    cache_mode("semantic")
    headers = build_gateway_headers("http://remote.internal:8471/v1")
    assert VIRTUAL_KEY_HEADER not in headers
    # The cache headers still apply -- they are a retention control, not
    # a credential.
    assert headers[CACHE_TYPE_HEADER] == "semantic"


@pytest.mark.parametrize(
    ("url", "trusted"),
    [
        ("http://127.0.0.1:8471/v1", True),
        ("http://localhost:8471/v1", True),
        ("http://[::1]:8471/v1", True),
        ("https://gateway.example.com/v1", True),
        ("http://gateway.example.com/v1", False),
        ("https://", False),
    ],
)
def test_gateway_host_is_trusted(url: str, trusted: bool) -> None:
    """Only https, and plain http on loopback, may carry the credential."""
    assert gateway_host_is_trusted(url) is trusted


def test_gateway_headers_respect_an_explicit_mode(
    cache_mode: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit mode overrides the router setting."""
    monkeypatch.setenv("BIFROST_VIRTUAL_KEY", "sk-bf-test-key")
    cache_mode("semantic")
    headers = build_gateway_headers(LOOPBACK_URL, "direct")
    assert headers[CACHE_TYPE_HEADER] == "direct"
