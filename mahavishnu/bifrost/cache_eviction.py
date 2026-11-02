"""Reclaim expired entries from the Bifrost cache store in Redis.

Why this file exists
--------------------
Bifrost enforces the semantic cache's TTL *in band*: every entry is a
Redis ``HASH`` carrying an ``expires_at`` field, and the plugin checks
that field when it reads the entry. The Redis key TTL is ``-1`` -- never
expires -- so an expired entry is **skipped, not deleted**.

Nothing reclaims the space. The plugin's ``cleanup_on_shutdown: true``
fires only when the gateway exits, and the gateway is a launchd
``KeepAlive`` job, so it can run for weeks without exiting. Measured on
2026-11-01 against the live store: 1488 of 1504 entries in the semantic
store were expired, holding ~19.3 MB of response payloads, in a Redis
with no ``maxmemory`` limit set.

This module deletes what is expired, and only what is expired.

The rule
--------
An entry is removed when it declares an ``expires_at`` that has already
passed. Three properties matter, and the tests pin each:

1. **Only the Bifrost namespaces are touched.** The store shares a Redis
   with the event bus (``bodai:events``) and the Oneiric queue
   (``oneiric-queue``). Those are not cache entries and must survive.
2. **An entry with no readable ``expires_at`` is kept.** Unknown state is
   never deleted -- the safe direction, because deleting a live entry
   costs a cache miss while deleting the wrong key costs correctness.
3. **The delete is atomic against a concurrent write.** The candidate's
   expiry is re-read inside a Lua script and the key is deleted only if
   it is *still* expired. Without that, an entry rewritten between the
   scan and the delete would be dropped even though it is live.

The third property is why this is a Lua script and not a ``DEL`` loop.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import TYPE_CHECKING, Protocol, cast

import anyio
from oneiric.core.logging import get_logger

from .paths import BIFROST_CONFIG_DIR

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Sequence
    from pathlib import Path

logger = get_logger(__name__)

#: The Redis key prefixes that hold Bifrost cache entries.
#:
#: ``BifrostSemanticCachePlugin:`` is the vector-store payload, indexed by
#: RediSearch under the same name -- deleting the HASH key removes the
#: document from the index. ``BifrostSemanticCachePlugin_d1:`` is a
#: leftover namespace from an older Bifrost layout (``FT._LIST`` reports
#: only the two plugin names as indexes); it is swept on the same rule.
#: ``BifrostLocalCachePlugin:`` is Bifrost's own local cache.
#:
#: The event-bus and queue keys (``bodai:events:*``, ``oneiric-queue``) are
#: deliberately absent.
CACHE_PREFIXES: tuple[str, ...] = (
    "BifrostSemanticCachePlugin:",
    "BifrostSemanticCachePlugin_d1:",
    "BifrostLocalCachePlugin:",
)

#: The hash field carrying the entry's expiry, in epoch seconds.
EXPIRES_FIELD = "expires_at"

#: Delete a key only if its ``expires_at`` is still in the past.
#:
#: Atomic per batch, so an entry rewritten between the scan and the delete
#: survives: the script re-reads the field and only deletes when the value
#: it finds is still expired. An entry with no ``expires_at`` is left
#: alone.
#:
#: This is Redis's server-side ``EVAL`` (a sandboxed Lua script), not
#: Python's :func:`eval`. The script is a constant with no interpolation
#: of caller input -- the expiry and the field name arrive as ``ARGV``.
DELETE_IF_EXPIRED_LUA = """
local deleted = 0
for i = 1, #KEYS do
  local raw = redis.call('HGET', KEYS[i], ARGV[1])
  if raw then
    local expires_at = tonumber(raw)
    if expires_at and expires_at <= tonumber(ARGV[2]) then
      redis.call('DEL', KEYS[i])
      deleted = deleted + 1
    end
  end
end
return deleted
"""

#: How many keys the scan asks for per round trip. Small enough that a
#: large store does not stall the server, large enough that the sweep is
#: not dominated by round trips.
SCAN_COUNT = 256


class RedisLike(Protocol):
    """The narrow slice of the Redis API the sweep uses.

    Declared as a protocol so the sweep can be unit-tested against a fake
    without a Redis server, and so the concrete client stays an edge
    concern.
    """

    def scan_iter(self, match: str, count: int) -> AsyncIterator[bytes]:
        """Iterate the keys matching ``match``."""
        ...

    def hget(self, key: bytes, field: bytes) -> Awaitable[bytes | None]:
        """Return one field of the hash at ``key``.

        Only the expiry field is read, never the whole hash: an entry's
        ``response`` payload is kilobytes, and fetching it for every key
        in the store turns a sweep into a bulk download.

        Returns an ``Awaitable`` rather than being a coroutine, because
        ``coredis`` types its command methods as returning a
        ``CommandRequest``.
        """
        ...

    def eval(self, script: str, keys: list[bytes], args: list[bytes]) -> Awaitable[int]:
        """Run a Lua script and return its integer result.

        Declared as returning an ``Awaitable`` rather than as a coroutine
        because ``coredis`` types its command methods as returning a
        ``CommandRequest``, which is awaitable but not a coroutine.
        """
        ...


@dataclass(frozen=True)
class SweepResult:
    """What a sweep found and what it did.

    Attributes:
        scanned: Keys examined.
        live: Keys whose ``expires_at`` is still in the future.
        expired: Keys whose ``expires_at`` had already passed.
        unknown_expiry: Keys with no readable ``expires_at``. These are
            never deleted.
        deleted: Keys actually removed. Zero in a dry run.
        errors: Keys that could not be read or deleted.
        elapsed_seconds: Wall time for the sweep.
    """

    scanned: int = 0
    live: int = 0
    expired: int = 0
    unknown_expiry: int = 0
    deleted: int = 0
    errors: int = 0
    elapsed_seconds: float = 0.0

    @property
    def deleted_or_expired(self) -> int:
        """Expired entries that are still resident (non-zero after a sweep)."""
        return self.expired - self.deleted


def parse_expiry(raw: bytes | str | None) -> float | None:
    """Read an ``expires_at`` field as epoch seconds.

    Args:
        raw: The raw field value, or ``None`` when the field is absent.

    Returns:
        The expiry as a float, or ``None`` when the field is missing or
        unparsable.
    """
    if raw is None:
        return None
    if isinstance(raw, bytes | bytearray):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        return float(raw)
    except TypeError, ValueError:
        return None


def is_expired(raw: bytes | str | None, now: float) -> bool:
    """True when the entry declares an expiry that has already passed.

    An entry with no readable ``expires_at`` is **not** expired: unknown
    state is kept, never deleted.

    Args:
        raw: The raw ``expires_at`` field value.
        now: The current time, in epoch seconds.

    Returns:
        True when the entry is expired and safe to remove.
    """
    expires_at = parse_expiry(raw)
    if expires_at is None:
        return False
    return expires_at <= now


def resolve_vector_store_addr(
    config_path: Path | None = None,
) -> tuple[str, int]:
    """Read the Redis address the gateway's vector store uses.

    The sweep must target the same Redis the gateway writes to, so the
    address comes from the gateway's own config rather than a constant
    here.

    Args:
        config_path: The gateway config to read. Defaults to the live
            config under ``~/.config/bifrost``.

    Returns:
        The ``(host, port)`` pair. Falls back to ``localhost:6379`` when
        the config is missing or does not declare a vector store.
    """
    path = config_path or (BIFROST_CONFIG_DIR / "config.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        logger.warning(
            "Could not read the Bifrost config at %s; using the default Redis address", path
        )
        return ("localhost", 6379)

    vector_store = payload.get("vector_store")
    if not isinstance(vector_store, dict):
        return ("localhost", 6379)
    config = vector_store.get("config")
    if not isinstance(config, dict):
        return ("localhost", 6379)
    addr = config.get("addr")
    if not isinstance(addr, str) or ":" not in addr:
        return ("localhost", 6379)
    host, _, port = addr.rpartition(":")
    try:
        return (host or "localhost", int(port))
    except ValueError:
        return ("localhost", 6379)


async def sweep_expired_entries(
    client: RedisLike,
    *,
    prefixes: Sequence[str] = CACHE_PREFIXES,
    now: float | None = None,
    dry_run: bool = False,
    batch_size: int = SCAN_COUNT,
) -> SweepResult:
    """Remove expired cache entries from the given key prefixes.

    Args:
        client: The Redis client to sweep through.
        prefixes: The key prefixes to sweep. Defaults to the Bifrost
            cache namespaces.
        now: The time to compare against, in epoch seconds. Defaults to
            the current time.
        dry_run: When true, classify the entries but delete nothing.
        batch_size: How many candidate keys to collect before issuing a
            delete.

    Returns:
        What the sweep found and did.
    """
    cutoff = time.time() if now is None else now
    started = time.monotonic()

    scanned = 0
    live = 0
    expired = 0
    unknown = 0
    deleted = 0
    errors = 0
    pending: list[bytes] = []

    async def flush() -> None:
        """Delete the collected candidates that are still expired."""
        nonlocal deleted, errors
        if not pending:
            return
        if not dry_run:
            try:
                deleted += int(
                    await client.eval(
                        DELETE_IF_EXPIRED_LUA,
                        list(pending),
                        [EXPIRES_FIELD.encode("utf-8"), str(int(cutoff)).encode("utf-8")],
                    )
                )
            except Exception:
                logger.exception("Could not delete a batch of expired cache entries")
                errors += len(pending)
        pending.clear()

    field = EXPIRES_FIELD.encode("utf-8")
    for prefix in prefixes:
        async for key in client.scan_iter(match=f"{prefix}*", count=SCAN_COUNT):
            scanned += 1
            try:
                raw = await client.hget(key, field)
            except Exception:
                logger.exception("Could not read the cache entry at %s", key)
                errors += 1
                continue

            if raw is None:
                unknown += 1
                continue
            if is_expired(raw, cutoff):
                expired += 1
                pending.append(key)
                if len(pending) >= batch_size:
                    await flush()
            else:
                live += 1

    await flush()

    result = SweepResult(
        scanned=scanned,
        live=live,
        expired=expired,
        unknown_expiry=unknown,
        deleted=deleted,
        errors=errors,
        elapsed_seconds=time.monotonic() - started,
    )
    logger.info(
        "cache_sweep_completed scanned=%d live=%d expired=%d deleted=%d unknown_expiry=%d errors=%d elapsed=%.3fs",
        result.scanned,
        result.live,
        result.expired,
        result.deleted,
        result.unknown_expiry,
        result.errors,
        result.elapsed_seconds,
    )
    return result


def run_sweep(
    *,
    host: str = "localhost",
    port: int = 6379,
    prefixes: Sequence[str] = CACHE_PREFIXES,
    now: float | None = None,
    dry_run: bool = False,
) -> SweepResult:
    """Connect to Redis, sweep, and disconnect.

    The synchronous entry point the CLI and the launchd timer use.

    Driven by ``anyio.run`` rather than ``asyncio.run``: ``coredis``
    keeps a reader and a writer task per connection inside an **anyio**
    task group, and ``anyio.run`` is the entry point its own
    documentation prescribes. Under a plain ``asyncio.run`` the group is
    never cancelled on the way out -- ``asyncio.run``'s shutdown cancels
    the tasks it can see, not the ones anyio owns -- so the process
    completes the sweep, then blocks forever waiting for a socket read
    that never returns. It looks like a hung job: the work is done, the
    process never exits, and a stdout redirected to a file stays empty
    because the buffer is never flushed.

    Args:
        host: The Redis host.
        port: The Redis port.
        prefixes: The key prefixes to sweep.
        now: The time to compare against, in epoch seconds.
        dry_run: When true, classify the entries but delete nothing.

    Returns:
        What the sweep found and did.
    """

    async def _run() -> SweepResult:
        import coredis

        async with coredis.Redis(host=host, port=port) as client:
            # ``coredis`` types its command methods as returning a
            # ``CommandRequest[ResponseType]`` over a union that includes
            # non-integer responses, so the checker cannot prove that
            # ``EVAL`` yields an ``int``. It does: the script returns the
            # count of deleted keys. The cast is at the boundary, where
            # that is known.
            typed = cast("RedisLike", client)
            return await sweep_expired_entries(typed, prefixes=prefixes, now=now, dry_run=dry_run)

    return anyio.run(_run, backend="asyncio")


def sweep_from_gateway_config(
    *,
    dry_run: bool = False,
    config_path: Path | None = None,
) -> SweepResult:
    """Sweep the Redis store the gateway's own config points at.

    Args:
        dry_run: When true, classify the entries but delete nothing.
        config_path: The gateway config to read the address from.

    Returns:
        What the sweep found and did.
    """
    host, port = resolve_vector_store_addr(config_path)
    return run_sweep(host=host, port=port, dry_run=dry_run)


__all__ = [
    "CACHE_PREFIXES",
    "DELETE_IF_EXPIRED_LUA",
    "EXPIRES_FIELD",
    "SCAN_COUNT",
    "RedisLike",
    "SweepResult",
    "is_expired",
    "parse_expiry",
    "resolve_vector_store_addr",
    "run_sweep",
    "sweep_expired_entries",
    "sweep_from_gateway_config",
]
