"""Translate the operator's ``cache_mode`` setting into Bifrost request headers.

# Implements: REQ-BIFROST-037

``BifrostLLMSettings.cache_mode`` (``off`` | ``direct`` | ``semantic``) had no
consumer: the ``mahavishnu/llm_gateway`` package that read it was deleted in
commit ``03146be0``, leaving the setting advisory-only while the gateway
cached everything that reached it.

The gateway expresses the same three choices as request headers, mapped in
``transports/bifrost-http/lib/ctx.go`` and honoured by
``plugins/semanticcache``:

======================  =====================================================
Header                  Effect
======================  =====================================================
``x-bf-cache-key``      Selects the cache bucket. Without it *and* without the
                        plugin's ``default_cache_key``, caching never engages.
``x-bf-cache-type``     Narrows the lookup to one path: ``direct`` (exact
                        match) or ``semantic`` (vector similarity).
``x-bf-cache-no-store`` Suppresses the cache **write**.
======================  =====================================================

Each mapping was confirmed empirically against the running gateway before
being encoded here; see
``docs/plans/2026-10-29-bifrost-bodai-cache-wiring.md`` §4.4.

Note the scope of the bucket. It used to be ``default`` for every caller,
and the gateway's own ``default_cache_key`` was ``"default"``, so there was
one shared bucket across the fleet. Combined with the semantic cache's
``exclude_system_prompt: true`` -- which drops the system prompt from the
cache key -- two agents with different personas but the same user turn
could collide, and one could be served the other's cached response. Both
halves of that are fixed at the gateway now: the template leaves
``default_cache_key`` unset, so a request that names no bucket cannot
engage the cache at all, and it restores ``exclude_system_prompt`` to the
upstream default of ``false``, so the system prompt -- which carries the
persona, the working directory and the date -- participates in the key.

The bucket is now **derived** (see :func:`resolve_cache_bucket`) from the
traffic class and the credential the request presents, so it is never the
shared default and never a bucket the caller chose. The credential is the
gateway virtual key -- the identity the gateway authenticates the request
as -- hashed rather than used verbatim, because the bucket travels in a
logged header. A second principal gets a second bucket with no code
change.

What this does **not** do is separate two agents of the same principal.
The bucket is chosen when the client is constructed, and the client is
reused across requests, so a per-agent bucket would need a per-request
header. The gateway would also have to refuse a bucket the presented
credential does not own -- a change in Bifrost itself, not here. The
system prompt carrying the discriminator is what closes that gap from
this side.

``off`` means *off*: neither a read nor a write. Bifrost v2.4.0 has no
header that suppresses the read directly -- ``x-bf-cache-no-store`` is
documented upstream as "skip writing the response to cache (still served
from cache on hit)" -- but the bucket gives the same guarantee. The cache
key is encoded into the direct cache ID (``generateDirectCacheID``) and is
an equality filter on the semantic search (``cache_key``), so a bucket
nothing was ever written to cannot be hit on either path. ``off``
therefore points at a bucket that is never written, and adds the no-store
header so the write is suppressed even against a gateway that still
carries a ``default_cache_key``.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
from typing import Literal, cast
from urllib.parse import urlparse

from oneiric.core.logging import get_logger

from .models import VIRTUAL_KEY_ENV, VIRTUAL_KEY_HEADER

logger = get_logger(__name__)

CacheMode = Literal["off", "direct", "semantic"]

#: Header selecting the cache bucket.
CACHE_KEY_HEADER = "x-bf-cache-key"
#: Header narrowing the lookup to the direct or semantic path.
CACHE_TYPE_HEADER = "x-bf-cache-type"
#: Header suppressing the cache write.
CACHE_NO_STORE_HEADER = "x-bf-cache-no-store"

#: Bucket used when the caller does not name one.
DEFAULT_CACHE_BUCKET = "default"

#: The mode assumed when the router settings cannot be read.
DEFAULT_CACHE_MODE: CacheMode = "off"

#: Hosts that are trusted with the gateway virtual key over plain HTTP.
#:
#: The virtual key can spend money through the gateway's provider keys and
#: read the shared cache, so it must not cross a network hop in cleartext.
#: Loopback is the deployment this project ships (the gateway listens on
#: 127.0.0.1:8471); everything else needs TLS.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

#: Errors that mean "the operator credential store is not readable".
#:
#: Held in a tuple constant rather than written inline: ruff-format on
#: Python 3.14 rewrites ``except (A, B):`` into the unparenthesised
#: PEP 758 form, which semgrep cannot parse. The constant form is left
#: alone.
_CREDENTIAL_ERRORS = (ImportError, OSError, RuntimeError, TypeError, ValueError)

VALID_CACHE_MODES: frozenset[str] = frozenset({"off", "direct", "semantic"})

#: Traffic classes used to separate protocol surfaces within one
#: principal's cache namespace. Two surfaces can carry the same user
#: turn -- the same prompt over the OpenAI protocol and over the
#: Anthropic one -- so without this they would share a bucket.
TRAFFIC_CLASS_WORKER = "worker"
TRAFFIC_CLASS_AGNO_OPENAI = "agno-openai"
TRAFFIC_CLASS_AGNO_ANTHROPIC = "agno-anthropic"

#: Characters allowed in a bucket name. The bucket travels in a header,
#: so it is restricted to an unambiguous, inert alphabet.
_BUCKET_PART = re.compile(r"[^a-z0-9_-]+")


def _sanitise_bucket_part(value: str) -> str:
    """Reduce a traffic class to an inert, bounded token.

    Args:
        value: The raw traffic class.

    Returns:
        A lowercase token of at most 32 characters.
    """
    cleaned = _BUCKET_PART.sub("-", value.strip().lower()).strip("-")
    return cleaned[:32]


def resolve_cache_mode() -> CacheMode:
    """Read ``cache_mode`` from the Oneiric Bifrost settings.

    Falls back to ``"off"`` when the settings cannot be loaded -- a
    missing configuration must not silently turn caching on.

    The settings class is read directly rather than through
    ``get_router()._settings``: the router's ``_settings`` attribute is
    private, and the router constructs it as
    ``settings or BifrostLLMSettings()`` -- so in the default
    configuration the two are the same object. Reading the settings
    class also re-reads the environment on every call rather than
    freezing the mode at router-construction time, so a mode change
    does not need a process restart to take effect.

    Returns:
        The configured cache mode.
    """
    try:
        from oneiric.adapters.llm.bifrost import BifrostLLMSettings

        raw = str(BifrostLLMSettings().cache_mode)
    except _CREDENTIAL_ERRORS:
        # The settings are optional and may be unconfigured. Falling back
        # to "off" is the safe direction: a missing configuration must
        # never turn caching on.
        #
        # Logged at WARNING, not DEBUG: this is the only failure in the
        # module that fails *silent*. A missing virtual key logs a
        # warning, a missing cache-mode source does not -- so cache
        # population stops with nothing visible and the operator sees a
        # cache that never hits and no explanation.
        logger.warning(
            "Could not read the Bifrost cache mode; falling back to %r. "
            "Cache population is disabled until the settings load.",
            DEFAULT_CACHE_MODE,
            exc_info=True,
        )
        return DEFAULT_CACHE_MODE
    if raw not in VALID_CACHE_MODES:
        logger.warning("Unknown Bifrost cache mode %r; falling back to %r", raw, DEFAULT_CACHE_MODE)
        return DEFAULT_CACHE_MODE
    return cast("CacheMode", raw)


def _uncacheable_bucket() -> str:
    """Return a bucket name that no cache entry can ever live in.

    Bifrost v2.4.0 has no header that suppresses a cache *read*: the
    ``x-bf-cache-no-store`` header is documented upstream as "skip writing
    the response to cache (still served from cache on hit)". A bucket
    achieves the same thing, because the cache key participates in both
    lookup paths -- it is encoded into the direct cache ID
    (``generateDirectCacheID``) and is an equality filter on the semantic
    search (``cache_key``). A bucket nothing was written to therefore
    cannot be hit on either path.

    The name is random per call, so two ``off`` requests never share a
    bucket and neither can collide with an entry another principal
    wrote. It carries the same inert alphabet as a derived bucket.

    Returns:
        A bucket name that no entry has ever been written to.
    """
    return f"off-{secrets.token_hex(8)}"


def _cache_headers_for(mode: CacheMode, bucket: str) -> dict[str, str]:
    """Assemble the cache headers for a mode and an already-chosen bucket.

    Private because the bucket is a *selector*: a caller that can name a
    bucket can read what is in it. Only :func:`build_cache_headers` and
    :func:`build_gateway_headers` may call this, and both derive the
    bucket rather than accepting one.

    Args:
        mode: One of ``off``, ``direct``, ``semantic``.
        bucket: The bucket to scope entries to.

    Returns:
        Headers to attach to the outbound request. Never empty: every mode
        carries the cache-bucket header, and the mode-specific header
        selects the lookup and write behaviour. ``off`` carries a bucket
        nothing was ever written to, so it neither reads nor writes --
        see the module docstring.
    """
    headers: dict[str, str] = {}
    if mode == "off":
        # No cache interaction at all. The bucket is one nothing was ever
        # written to, so the lookup cannot hit; the no-store header
        # suppresses the write even against a gateway that still carries
        # a default_cache_key.
        headers[CACHE_KEY_HEADER] = _uncacheable_bucket()
        headers[CACHE_NO_STORE_HEADER] = "true"
        return headers

    key = bucket.strip() or DEFAULT_CACHE_BUCKET
    headers[CACHE_KEY_HEADER] = key
    headers[CACHE_TYPE_HEADER] = "direct" if mode == "direct" else "semantic"
    return headers


def build_cache_headers(mode: CacheMode, *, traffic_class: str = "") -> dict[str, str]:
    """Build the ``x-bf-cache-*`` headers for a cache mode.

    The bucket is derived from the traffic class and the credential the
    request presents (see :func:`resolve_cache_bucket`). It cannot be
    passed in: a caller-chosen bucket is a caller-chosen *selector*, so
    whoever holds a credential could name another bucket and read what
    is in it.

    Args:
        mode: One of ``off``, ``direct``, ``semantic``.
        traffic_class: What kind of traffic this is. Separates protocol
            surfaces within one principal's namespace.

    Returns:
        Headers to attach to the outbound request. Never empty: every mode
        carries the cache-bucket header, and the mode-specific header
        selects the lookup and write behaviour. ``off`` carries a bucket
        nothing was ever written to, so it neither reads nor writes.
    """
    return _cache_headers_for(mode, resolve_cache_bucket(traffic_class, resolve_virtual_key()))


def resolve_virtual_key() -> str | None:
    """Return the Bifrost virtual key, or ``None`` when it is unavailable.

    Read from the environment first, then from the operator credential
    store (``~/.config/secrets.env``) via the gateway's own loader -- a
    process launched by launchd inherits no interactive environment.

    Returns:
        The virtual key, or ``None``.
    """
    value = os.environ.get(VIRTUAL_KEY_ENV, "").strip()
    if value:
        return value
    try:
        from .gateway import load_secrets_env

        # Narrowed to the one key: the loader parses the whole file
        # regardless, but returning only this key keeps the other
        # credentials out of the caller's hands.
        value = load_secrets_env((VIRTUAL_KEY_ENV,)).get(VIRTUAL_KEY_ENV, "").strip()
    except _CREDENTIAL_ERRORS:
        logger.debug("Could not read the operator credential store", exc_info=True)
        return None
    return value or None


def gateway_host_is_trusted(base_url: str) -> bool:
    """True when ``base_url`` is safe to carry a gateway credential to.

    The virtual key can spend money through the gateway's provider keys
    and read the shared cache. Sending it over plain HTTP to a non-local
    host would put it on the wire in cleartext, so that combination is
    refused. HTTPS is trusted regardless of host; plain HTTP is trusted
    only for loopback, which is the deployment the gateway ships in.

    Args:
        base_url: The gateway base URL the request will be sent to.

    Returns:
        True when the credential may be attached to this URL.
    """
    try:
        parsed = urlparse(base_url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        # A URL with no host is malformed; it cannot be a trustworthy
        # destination for a credential.
        return False
    scheme = (parsed.scheme or "").lower()
    if scheme == "https":
        return True
    return scheme == "http" and host in LOOPBACK_HOSTS


def resolve_cache_bucket(traffic_class: str, principal: str | None = None) -> str:
    """Derive the cache bucket for a request.

    The bucket is **derived**, never taken from the caller. Two things
    make that matter:

    * The shared :data:`DEFAULT_CACHE_BUCKET` puts every request in the
      fleet into one namespace. With the semantic cache dropping the
      system prompt from the cache key, two agents with different
      personas but the same user turn collide, and one is served the
      other's cached response.
    * A caller-supplied bucket is a caller-supplied *selector*. Whoever
      holds a credential could name another bucket and read what is in
      it. Deriving the bucket from the credential the request actually
      presents closes that: a caller cannot select a bucket it does not
      hold the key for.

    The principal is the gateway virtual key -- the identity the gateway
    authenticates the request as. It is hashed rather than used
    verbatim, because the bucket travels in a header that gets logged.
    Two principals therefore get separate buckets automatically, with no
    code change when a second key is issued.

    Args:
        traffic_class: What kind of traffic this is (for example
            ``"worker"`` or ``"agno-openai"``). It separates protocol
            surfaces, which can otherwise collide on an identical user
            turn.
        principal: The authenticated principal -- the gateway virtual
            key. ``None`` when no credential is available.

    Returns:
        A bucket name that is never the shared default.
    """
    scope = _sanitise_bucket_part(traffic_class) or "unknown"
    if principal:
        digest = hashlib.sha256(principal.encode("utf-8")).hexdigest()[:12]
    else:
        # No credential means the gateway will reject the request
        # anyway. The bucket is still not the shared one, so a
        # misconfigured deployment cannot fall back into the fleet-wide
        # namespace.
        digest = "nokey"
    return f"{scope}:{digest}"


def build_gateway_headers(
    base_url: str,
    mode: CacheMode | None = None,
    *,
    traffic_class: str = "",
) -> dict[str, str]:
    """Build the full header set for a Bifrost-routed request.

    Carries the cache headers for the resolved cache mode plus -- when one
    is available and the transport can carry it -- the gateway virtual key.
    Bifrost rejects a provider key with ``401 virtual key is required``.

    The cache headers are emitted unconditionally. They express the
    operator's ``cache_mode``, and coupling them to the presence of a
    credential would mean a missing key silently inverted ``off`` into
    "cache everything": without ``x-bf-cache-no-store`` the gateway
    resolves the bucket from its own ``default_cache_key`` and writes the
    prompt and response into the shared cache. A missing credential must
    not change what gets retained.

    The bucket is **derived** from the traffic class and the credential
    the request presents (see :func:`resolve_cache_bucket`). There is
    deliberately no way to pass one in: a caller-supplied bucket is a
    caller-supplied *selector*, so whoever holds a credential could name
    another bucket and read what is in it. Deriving it from the
    credential the request actually presents closes that -- a caller
    cannot select a bucket it does not hold the key for -- and it means
    the bucket is never the shared :data:`DEFAULT_CACHE_BUCKET`.

    The virtual key is attached only when the target URL is trusted (see
    :func:`gateway_host_is_trusted`). An untrusted target gets the cache
    headers and no credential; the caller can tell the difference by the
    absence of ``x-bf-vk``.

    Args:
        base_url: The gateway base URL the request will be sent to. Used
            to decide whether the credential may cross this hop.
        mode: Cache mode. Resolved from the router settings when omitted.
        traffic_class: What kind of traffic this is. Separates protocol
            surfaces within one principal's namespace.

    Returns:
        Headers to attach to the outbound request.
    """
    virtual_key = resolve_virtual_key()
    bucket = resolve_cache_bucket(traffic_class, virtual_key)
    headers = _cache_headers_for(mode or resolve_cache_mode(), bucket)

    if not virtual_key:
        logger.warning(
            "No Bifrost virtual key is available (set %s); the request will "
            "not carry x-bf-vk and the gateway will reject it",
            VIRTUAL_KEY_ENV,
        )
        return headers

    if not gateway_host_is_trusted(base_url):
        logger.error(
            "Refusing to send the Bifrost virtual key to %s: the target is "
            "neither https nor loopback, so the credential would cross the "
            "network in cleartext",
            base_url,
        )
        return headers

    headers[VIRTUAL_KEY_HEADER] = virtual_key
    return headers


__all__ = [
    "CACHE_KEY_HEADER",
    "CACHE_NO_STORE_HEADER",
    "CACHE_TYPE_HEADER",
    "DEFAULT_CACHE_BUCKET",
    "DEFAULT_CACHE_MODE",
    "LOOPBACK_HOSTS",
    "TRAFFIC_CLASS_AGNO_ANTHROPIC",
    "TRAFFIC_CLASS_AGNO_OPENAI",
    "TRAFFIC_CLASS_WORKER",
    "VALID_CACHE_MODES",
    "VIRTUAL_KEY_HEADER",
    "CacheMode",
    "build_cache_headers",
    "build_gateway_headers",
    "gateway_host_is_trusted",
    "resolve_cache_bucket",
    "resolve_cache_mode",
    "resolve_virtual_key",
]
