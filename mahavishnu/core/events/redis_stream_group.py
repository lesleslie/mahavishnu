"""Owner-side handle for one Redis Stream consumer group.

A Redis consumer group needs three kinds of maintenance, and this module
owns all three for the groups mahavishnu runs:

**Read.** ``coredis`` 6.x answers ``XREADGROUP`` with a mapping keyed by
the *stream name as bytes*, holding ``StreamEntry`` objects whose field
names and values are also bytes. Oneiric's ``RedisStreamsQueueAdapter``
compared that bytes key against the configured ``str`` stream name
directly, so it discarded every entry it was handed. The task-orphan
sweeper built on that adapter therefore read **nothing**: it delivered
18,198 messages into its group's pending list and acknowledged 5.

**Reclaim.** ``XREADGROUP`` with ``>`` delivers only *new* messages, so a
message handed to a consumer that died before acknowledging it stays in
the pending list forever. ``XAUTOCLAIM`` is the command that takes those
back.

**Purge.** Redis does **not** trim a group's pending list when the
stream is trimmed. Every trimmed message leaves a pending entry behind
pointing at an id that no longer exists: permanently un-ackable, and
invisible to ``>`` reads. ``XAUTOCLAIM`` reports them in its deleted-ids
array and removes them from the pending list as it goes.

A third, smaller leak completes the picture: a consumer registered under
a fresh name per process start is never removed by Redis, so the
consumer table grows without bound. ``XGROUP DELCONSUMER`` removes one —
but only when it owns no pending messages, because deleting a consumer
destroys its pending entries rather than releasing them.

The client is coredis, the same client oneiric's adapter uses, so no new
dependency is introduced.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import inspect
import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Default Redis URL. Overridden per instance by callers that need it.
DEFAULT_REDIS_URL = "redis://localhost:6379/0"

#: Default number of entries pulled per read.
DEFAULT_READ_COUNT = 10

#: Default blocking window for a read, in milliseconds.
DEFAULT_READ_BLOCK_MS = 5000

#: Minimum idle time before a pending entry may be claimed, in ms.
#:
#: Long enough that an entry the live process is still working on is
#: never stolen from it. Redis purges trimmed ("zombie") entries from
#: the pending list *regardless* of this threshold, so the value only
#: governs which live entries are reclaimed.
DEFAULT_RECLAIM_MIN_IDLE_MS = 60_000

#: Number of pending entries examined per ``XAUTOCLAIM`` call.
DEFAULT_RECLAIM_COUNT = 512

#: Upper bound on ``XAUTOCLAIM`` calls per sweep, so one sweep cannot
#: hold the event loop indefinitely on a very large pending list.
DEFAULT_RECLAIM_MAX_ROUNDS = 64

#: Delete a consumer, but only if it owns no pending messages.
#:
#: Reading the pending list and deleting the consumer are two commands,
#: so an ``XREADGROUP`` can interleave between them: the consumer takes
#: delivery of a message and the delete destroys it. A Lua script runs
#: atomically, so nothing can interleave. The script returns the number
#: of pending messages the consumer had (always zero, because it is
#: only deleted when it owns nothing) or ``-1`` when the consumer was
#: left alone.
#:
#: Verified against Redis 7.4: ``XPENDING`` and ``XGROUP DELCONSUMER``
#: are both callable from a script.
_DELETE_CONSUMER_IF_EMPTY = (
    "local pending = redis.call('XPENDING', KEYS[1], ARGV[1], '-', '+', 1, ARGV[2]); "
    "if #pending == 0 then "
    "return redis.call('XGROUP', 'DELCONSUMER', KEYS[1], ARGV[1], ARGV[2]); "
    "else return -1 end"
)

#: Upper bound on the entries one sweep hands back for processing.
#:
#: The scan continues past this cap -- the zombies beyond it are still
#: purged -- but the entries past it are left pending for a later
#: sweep. Each entry costs several round trips (read the task, link
#: it, emit the completion, acknowledge it), so an unbounded backlog
#: would otherwise monopolise the event loop in one pass.
DEFAULT_RECLAIM_MAX_ENTRIES = 100

#: A consumer that has not read for this long is treated as dead.
DEFAULT_PRUNE_STALE_AFTER_MS = 300_000


def _as_text(value: Any) -> str:
    """Return ``value`` as text, decoding bytes and leaving ``str`` alone."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _row_field(row: Mapping[Any, Any], name: str, default: Any = None) -> Any:
    """Read ``name`` from a reply row whose keys may be bytes or ``str``.

    coredis answers ``XINFO`` with bytes keys; the in-memory fixtures
    used by the tests use ``str``. Both are read the same way.
    """
    if name in row:
        return row[name]
    encoded = name.encode("utf-8")
    if encoded in row:
        return row[encoded]
    return default


@dataclass(frozen=True)
class ReclaimResult:
    """Outcome of one ``XAUTOCLAIM`` sweep over a group's pending list.

    ``entries`` are the messages that still have data and were idle long
    enough to be reclaimed — the work to redo. ``deleted_ids`` are the
    pending entries whose stream data is gone; Redis removed them from
    the pending list while answering, so they need no further work.
    """

    entries: list[dict[str, Any]] = field(default_factory=list)
    deleted_ids: list[str] = field(default_factory=list)
    cursor: str = "0-0"

    @property
    def claimed_count(self) -> int:
        """Number of live entries reclaimed for reprocessing."""
        return len(self.entries)

    @property
    def purged_count(self) -> int:
        """Number of zombie pending entries purged by Redis."""
        return len(self.deleted_ids)


@dataclass(frozen=True)
class PruneResult:
    """Outcome of one consumer prune.

    ``destroyed_messages`` is how many pending messages the deletes
    destroyed. ``XGROUP DELCONSUMER`` returns the number of pending
    messages the consumer owned, and a non-zero return means messages
    that were never acknowledged have just been made unrecoverable.
    """

    removed: list[str] = field(default_factory=list)
    destroyed_messages: int = 0


@dataclass(frozen=True)
class GroupState:
    """A snapshot of one consumer group's size."""

    pending: int = 0
    consumers: int = 0
    lag: int | None = None


class RedisStreamGroup:
    """Owner-side access to one Redis Stream consumer group.

    Owns its own coredis client. The client may be injected, which is
    how the tests exercise this class without touching Redis.
    """

    def __init__(
        self,
        *,
        stream: str,
        group: str,
        consumer: str,
        redis_url: str = DEFAULT_REDIS_URL,
        client: Any | None = None,
    ) -> None:
        self._stream = stream
        self._group = group
        self._consumer = consumer
        self._redis_url = redis_url
        self._client = client
        self._owns_client = client is None

    # -- properties ------------------------------------------------------

    @property
    def stream(self) -> str:
        """Name of the stream this handle reads and writes."""
        return self._stream

    @property
    def group(self) -> str:
        """Name of the consumer group this handle maintains."""
        return self._group

    @property
    def consumer(self) -> str:
        """Name this handle reads under."""
        return self._consumer

    # -- lifecycle -------------------------------------------------------

    async def init(self) -> None:
        """Open the client, initialise its pool, and create the group.

        coredis 6.x requires the pool to be entered explicitly before
        the first command; without it every call raises "Connection
        pool is not initialized or has exited".

        The consumer group is created here because every command
        against a group that does not exist fails with NOGROUP — the
        read included. Oneiric's adapter did the same.
        """
        if self._client is None:
            from coredis import Redis

            self._client = Redis.from_url(self._redis_url)
        if self._owns_client:
            aenter = getattr(self._client, "__aenter__", None)
            if aenter is not None:
                await aenter()
        await self._ensure_consumer_group()

    async def _ensure_consumer_group(self) -> None:
        """Create the consumer group if it does not exist yet.

        Tolerates "group already exists", which is the case on every
        start after the first. Any other failure is a real problem and
        propagates: the caller degrades rather than reading a group
        that is not there.
        """
        client = self._ensure_client()
        try:
            await client.xgroup_create(
                self._stream,
                self._group,
                identifier="0",
                mkstream=True,
            )
        except Exception as exc:
            if "BUSYGROUP" in str(exc).upper():
                return
            logger.warning(
                "redis_stream_group: xgroup_create failed for %s/%s: %s",
                self._stream,
                self._group,
                exc,
            )
            raise

    async def cleanup(self) -> None:
        """Close the client and release its pool, if this handle owns it."""
        client = self._client
        self._client = None
        if client is None or not self._owns_client:
            return
        close = getattr(client, "close", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result
        disconnect = getattr(
            getattr(client, "connection_pool", None), "disconnect", None
        )
        if disconnect is not None:
            result = disconnect()
            if inspect.isawaitable(result):
                await result

    def _ensure_client(self) -> Any:
        """Return the client, or fail loudly when it was never opened."""
        if self._client is None:
            raise RuntimeError("redis_stream_group: client not initialised")
        return self._client

    # -- reading ---------------------------------------------------------

    async def read(
        self,
        *,
        count: int = DEFAULT_READ_COUNT,
        block_ms: int = DEFAULT_READ_BLOCK_MS,
    ) -> list[dict[str, Any]]:
        """Read new messages and return them in the normalised shape.

        Each entry is ``{"message_id": str, "payload": dict[str, str]}``.
        # req: REQ-SWEEPERHYGIENE-001
        Field names and values are decoded to ``str`` because the
        consumers filter on them against ``str`` channel names.
        """
        client = self._ensure_client()
        response = await client.xreadgroup(
            self._group,
            self._consumer,
            streams={self._stream: ">"},
            count=count,
            block=block_ms,
        )
        return self._format_entries(response)

    def _format_entries(self, response: Any) -> list[dict[str, Any]]:
        """Normalise a read reply into ``{"message_id", "payload"}`` entries.

        Two reply shapes are accepted: coredis 6.x's mapping keyed by
        the stream name, and the older list of ``(stream, messages)``
        tuples. The stream key is compared as *text* — coredis returns
        it as bytes, and comparing bytes to the configured ``str`` name
        is what silently discarded every message.
        """
        if not response:
            return []
        pairs = response.items() if isinstance(response, Mapping) else response
        formatted: list[dict[str, Any]] = []
        for stream_key, messages in pairs:
            if _as_text(stream_key) != self._stream:
                continue
            formatted.extend(self._format_messages(messages))
        return formatted

    def _format_messages(self, messages: Any) -> list[dict[str, Any]]:
        """Normalise the messages of one stream into entries."""
        formatted: list[dict[str, Any]] = []
        for message in messages or ():
            message_id, payload = self._split_entry(message)
            if message_id is None:
                continue
            formatted.append({"message_id": message_id, "payload": payload})
        return formatted

    @staticmethod
    def _split_entry(message: Any) -> tuple[str | None, dict[str, str]]:
        """Split one message into its id and decoded field mapping.

        coredis yields ``StreamEntry`` objects; older coredis and the
        in-memory fixtures yield ``(id, fields)`` tuples. Both are
        accepted.
        """
        identifier = getattr(message, "identifier", None)
        field_values = getattr(message, "field_values", None)
        if identifier is not None and field_values is not None:
            return _as_text(identifier), _decode_fields(field_values)
        if isinstance(message, Sequence) and not isinstance(message, str | bytes):
            if len(message) == 2:
                message_id, fields = message
                return _as_text(message_id), _decode_fields(fields)
        return None, {}

    # -- acknowledging and publishing ------------------------------------

    async def ack(self, message_ids: Sequence[str]) -> int:
        """Acknowledge ``message_ids`` and return how many were removed."""
        if not message_ids:
            return 0
        client = self._ensure_client()
        return int(await client.xack(self._stream, self._group, list(message_ids)))

    async def enqueue(self, data: Mapping[str, Any]) -> str:
        """Append ``data`` to the stream and return the new message id."""
        client = self._ensure_client()
        message_id = await client.xadd(self._stream, dict(data))
        return _as_text(message_id)

    # -- maintenance -----------------------------------------------------

    async def reclaim(
        self,
        *,
        min_idle_ms: int = DEFAULT_RECLAIM_MIN_IDLE_MS,
        count: int = DEFAULT_RECLAIM_COUNT,
        max_rounds: int = DEFAULT_RECLAIM_MAX_ROUNDS,
        max_entries: int = DEFAULT_RECLAIM_MAX_ENTRIES,
    ) -> ReclaimResult:
        """Sweep the pending list: reclaim stale messages, purge zombies.

        The sweep continues until Redis reports the scan complete (the
        cursor returns to ``0-0``) or ``max_rounds`` calls have been
        made. Trimming the stream does not trim the pending list, so
        the zombies accumulate; a single pass that stops early would
        leave them for another pass to find.

        ``max_entries`` bounds the *work handed back*, not the scan.
        The scan continues past the cap so the zombies beyond it are
        still purged; the entries past the cap are simply not
        accumulated. They stay pending under this consumer and are
        reclaimed by a later pass, so a huge backlog drains over
        several passes instead of in one monopolising sweep.
        # req: REQ-SWEEPERHYGIENE-002, REQ-SWEEPERHYGIENE-003
        """
        client = self._ensure_client()
        entries: list[dict[str, Any]] = []
        deleted: list[str] = []
        cursor = "0-0"
        for _ in range(max_rounds):
            reply = await client.xautoclaim(
                self._stream,
                self._group,
                self._consumer,
                min_idle_time=min_idle_ms,
                start=cursor,
                count=count,
            )
            next_cursor, claimed, purged = reply
            for message in claimed or ():
                if len(entries) >= max_entries:
                    break
                message_id, payload = self._split_entry(message)
                if message_id is None:
                    continue
                entries.append({"message_id": message_id, "payload": payload})
            deleted.extend(_as_text(message_id) for message_id in (purged or ()))
            cursor = _as_text(next_cursor)
            if not cursor or cursor == "0-0":
                break
        return ReclaimResult(entries=entries, deleted_ids=deleted, cursor=cursor)

    async def prune_consumers(
        self,
        *,
        keep: str,
        prefix: str | None = None,
        stale_after_ms: int = DEFAULT_PRUNE_STALE_AFTER_MS,
    ) -> PruneResult:
        """Remove consumers that are gone, and report what that cost.

        A consumer is removed only when all of the following hold: it is
        not ``keep`` (this handle's own consumer), it matches ``prefix``
        when one is given, it owns **no** pending messages, and it has
        not read for ``stale_after_ms``. Deleting a consumer that still
        owns pending messages destroys them, so a stale consumer is left
        in place rather than risk losing a message.

        ``XGROUP DELCONSUMER`` returns how many pending messages the
        consumer owned when it was deleted. The listing above is
        inherently racy -- a consumer can take delivery of a message
        between the listing and the delete -- so a non-zero return is
        reported as ``destroyed_messages`` rather than counted as a
        clean prune.
        # req: REQ-SWEEPERHYGIENE-004
        """
        client = self._ensure_client()
        rows = await client.xinfo_consumers(self._stream, self._group)
        removed: list[str] = []
        destroyed = 0
        for row in rows or ():
            name = _as_text(_row_field(row, "name"))
            if not name or name == keep:
                continue
            if prefix and not name.startswith(prefix):
                continue
            if int(_row_field(row, "pending", 0) or 0) > 0:
                continue
            if int(_row_field(row, "idle", 0) or 0) < stale_after_ms:
                continue
            # The check and the delete are one atomic server-side
            # operation. The listing above is a snapshot, and two
            # commands would let an XREADGROUP interleave between the
            # check and the delete: the consumer takes delivery of a
            # message and the delete destroys it -- neither acked nor
            # redelivered, and never reclaimable.
            outcome = int(
                await client.eval(
                    _DELETE_CONSUMER_IF_EMPTY,
                    [self._stream],
                    [self._group, name],
                )
                or 0
            )
            if outcome < 0:
                # The consumer owns pending messages: it was left in
                # place rather than risk losing one.
                continue
            if outcome:
                logger.error(
                    "redis_stream_group: deleting %s destroyed %d pending "
                    "message(s) -- they were never acknowledged",
                    name,
                    outcome,
                )
                destroyed += outcome
            removed.append(name)
        return PruneResult(removed=removed, destroyed_messages=destroyed)

    async def group_state(self) -> GroupState:
        """Return the group's pending count, consumer count and lag.

        A failed read raises. It must not return an empty
        :class:`GroupState`: "could not be determined" and "zero" are
        different facts, and only one of them is safe to publish.
        """
        client = self._ensure_client()
        rows = await client.xinfo_groups(self._stream)
        for row in rows or ():
            if _as_text(_row_field(row, "name")) != self._group:
                continue
            lag = _row_field(row, "lag")
            return GroupState(
                pending=int(_row_field(row, "pending", 0) or 0),
                consumers=int(_row_field(row, "consumers", 0) or 0),
                lag=None if lag is None else int(lag),
            )
        return GroupState()


def _decode_fields(fields: Any) -> dict[str, str]:
    """Decode a message's field mapping to ``str`` keys and values."""
    if not fields:
        return {}
    return {_as_text(key): _as_text(value) for key, value in dict(fields).items()}
