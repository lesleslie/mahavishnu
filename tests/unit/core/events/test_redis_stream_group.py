"""Unit tests for ``mahavishnu.core.events.redis_stream_group``.

Pins the contract of :class:`RedisStreamGroup` — the owner-side handle
for one Redis Stream consumer group.

The behaviours pinned here exist because of defects found in the live
system on 2026-11-21:

* coredis 6.x returns the stream key as ``bytes`` while the configured
  stream name is a ``str``. Oneiric's ``RedisStreamsQueueAdapter``
  compared the two directly, so every entry was dropped and the
  task-orphan sweeper never read a single message.
* coredis returns ``StreamEntry`` objects, not ``(id, fields)`` tuples.
* coredis returns ``bytes`` for field names and values, but the
  sweeper's channel filter compares against ``str``.
* Redis does not trim a consumer group's pending list when the stream
  is trimmed, so entries whose data is gone stay pending forever.
  ``XAUTOCLAIM`` is the only command that purges them.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Test doubles — mirror coredis's wire shapes exactly
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _StreamEntry:
    """Mirror of ``coredis.StreamEntry`` (a namedtuple of 4 fields)."""

    identifier: bytes
    field_values: "OrderedDict[bytes, bytes]"
    idle: int | None = None
    delivered: int | None = None


class _FakeRedis:
    """Records calls and returns coredis-shaped replies."""

    def __init__(self) -> None:
        self.xreadgroup_reply: Any = None
        self.acked: list[tuple[str, ...]] = []
        self.added: list[tuple[str, dict[str, Any]]] = []
        self.autoclaim_replies: list[tuple[Any, Any, Any]] = []
        self.consumers_reply: tuple[dict[Any, Any], ...] = ()
        self.groups_reply: tuple[dict[Any, Any], ...] = ()
        self.deleted_consumers: list[str] = []
        self.autoclaim_calls: list[dict[str, Any]] = []
        self.group_creates: list[tuple[str, str, str, bool]] = []

    async def xreadgroup(
        self,
        group: str,
        consumer: str,
        streams: dict[str, str],
        count: int | None = None,
        block: int | None = None,
    ) -> Any:
        return self.xreadgroup_reply

    async def xack(
        self, key: str, group: str, identifiers: list[str]
    ) -> int:
        self.acked.append((key, group, *identifiers))
        return len(identifiers)

    async def xadd(self, key: str, field_values: dict[str, Any]) -> str:
        self.added.append((key, field_values))
        return f"x-{len(self.added)}"

    async def xautoclaim(
        self,
        key: str,
        group: str,
        consumer: str,
        min_idle_time: int,
        start: str,
        count: int | None = None,
    ) -> tuple[Any, Any, Any]:
        self.autoclaim_calls.append(
            {
                "key": key,
                "group": group,
                "consumer": consumer,
                "min_idle_time": min_idle_time,
                "start": start,
                "count": count,
            }
        )
        if self.autoclaim_replies:
            return self.autoclaim_replies.pop(0)
        return (b"0-0", (), ())

    async def xinfo_consumers(
        self, key: str, groupname: str
    ) -> tuple[dict[Any, Any], ...]:
        return self.consumers_reply

    async def xgroup_delconsumer(
        self, key: str, groupname: str, consumername: str
    ) -> int:
        self.deleted_consumers.append(consumername)
        return 0

    async def xinfo_groups(self, key: str) -> tuple[dict[Any, Any], ...]:
        return self.groups_reply

    async def xgroup_create(
        self, key: str, groupname: str, identifier: str, mkstream: bool
    ) -> bool:
        self.group_creates.append((key, groupname, identifier, mkstream))
        return True


# ---------------------------------------------------------------------------
# Read — the bytes/str stream-key defect
# ---------------------------------------------------------------------------


class TestTheReadNormalisesCoredisReplies:
    """coredis 6.x answers with bytes keys and StreamEntry objects."""

    async def test_a_bytes_stream_key_still_matches_the_configured_stream(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        client = _FakeRedis()
        client.xreadgroup_reply = {
            b"bodai:events": (
                _StreamEntry(
                    identifier=b"1-0",
                    field_values=OrderedDict(
                        {b"channel": b"task.handoff_orphan", b"task_id": b"t-1"}
                    ),
                ),
            )
        }
        group = RedisStreamGroup(
            stream="bodai:events",
            group="g",
            consumer="c",
            client=client,
        )

        entries = await group.read(count=10, block_ms=100)

        assert len(entries) == 1, "a bytes stream key must still match the str setting"
        assert entries[0]["message_id"] == "1-0"
        assert entries[0]["payload"]["channel"] == "task.handoff_orphan"

    async def test_field_names_and_values_are_decoded_to_str(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        client = _FakeRedis()
        client.xreadgroup_reply = {
            b"bodai:events": (
                _StreamEntry(
                    identifier=b"2-0",
                    field_values=OrderedDict({b"channel": b"task.handoff_orphan"}),
                ),
            )
        }
        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="c", client=client
        )

        entries = await group.read(count=10, block_ms=100)

        payload = entries[0]["payload"]
        assert payload == {"channel": "task.handoff_orphan"}
        assert all(isinstance(k, str) for k in payload)
        assert all(isinstance(v, str) for v in payload.values())

    async def test_the_list_of_tuples_shape_is_also_accepted(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        client = _FakeRedis()
        client.xreadgroup_reply = [
            ("bodai:events", [(b"3-0", {b"channel": b"task.handoff_orphan"})])
        ]
        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="c", client=client
        )

        entries = await group.read(count=10, block_ms=100)

        assert len(entries) == 1
        assert entries[0]["message_id"] == "3-0"
        assert entries[0]["payload"]["channel"] == "task.handoff_orphan"

    async def test_entries_from_another_stream_are_ignored(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        client = _FakeRedis()
        client.xreadgroup_reply = {
            b"some:other:stream": (
                _StreamEntry(
                    identifier=b"4-0",
                    field_values=OrderedDict({b"channel": b"task.handoff_orphan"}),
                ),
            )
        }
        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="c", client=client
        )

        entries = await group.read(count=10, block_ms=100)

        assert entries == []

    async def test_an_empty_reply_yields_no_entries(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        client = _FakeRedis()
        client.xreadgroup_reply = None
        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="c", client=client
        )

        assert await group.read(count=10, block_ms=100) == []


# ---------------------------------------------------------------------------
# Ack and enqueue
# ---------------------------------------------------------------------------


class TestTheAckAndEnqueue:
    async def test_ack_passes_the_ids_to_xack(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        client = _FakeRedis()
        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="c", client=client
        )

        assert await group.ack(["1-0", "2-0"]) == 2
        assert client.acked == [("bodai:events", "g", "1-0", "2-0")]

    async def test_ack_with_no_ids_does_not_call_redis(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        client = _FakeRedis()
        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="c", client=client
        )

        assert await group.ack([]) == 0
        assert client.acked == []

    async def test_enqueue_adds_the_payload_to_the_stream(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        client = _FakeRedis()
        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="c", client=client
        )

        message_id = await group.enqueue({"channel": "task.handoff_completed"})

        assert message_id == "x-1"
        assert client.added == [
            ("bodai:events", {"channel": "task.handoff_completed"})
        ]


# ---------------------------------------------------------------------------
# Reclaim — the zombie purge and the stale-entry claim
# ---------------------------------------------------------------------------


class TestTheReclaim:
    async def test_claimed_entries_come_back_decoded(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        client = _FakeRedis()
        client.autoclaim_replies = [
            (
                b"0-0",
                (
                    _StreamEntry(
                        identifier=b"9-0",
                        field_values=OrderedDict({b"channel": b"task.handoff_orphan"}),
                    ),
                ),
                (b"8-0", b"7-0"),
            )
        ]
        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="c", client=client
        )

        result = await group.reclaim(min_idle_ms=1000, count=10)

        assert result.claimed_count == 1
        assert result.entries[0]["message_id"] == "9-0"
        assert result.entries[0]["payload"]["channel"] == "task.handoff_orphan"

    async def test_zombie_ids_are_reported_as_purged(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        client = _FakeRedis()
        client.autoclaim_replies = [(b"0-0", (), (b"8-0", b"7-0"))]
        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="c", client=client
        )

        result = await group.reclaim(min_idle_ms=1000, count=10)

        assert result.purged_count == 2
        assert result.deleted_ids == ["8-0", "7-0"]

    async def test_the_scan_continues_until_the_cursor_completes(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        client = _FakeRedis()
        client.autoclaim_replies = [
            (b"50-0", (), (b"1-0",)),
            (b"0-0", (), (b"2-0",)),
        ]
        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="c", client=client
        )

        result = await group.reclaim(min_idle_ms=1000, count=10)

        assert len(client.autoclaim_calls) == 2
        assert client.autoclaim_calls[1]["start"] == "50-0"
        assert result.purged_count == 2

    async def test_the_scan_is_bounded_by_the_round_cap(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        client = _FakeRedis()
        client.autoclaim_replies = [(b"50-0", (), ())] * 10
        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="c", client=client
        )

        await group.reclaim(min_idle_ms=1000, count=10, max_rounds=3)

        assert len(client.autoclaim_calls) == 3

    async def test_the_min_idle_threshold_is_passed_through(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        client = _FakeRedis()
        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="c", client=client
        )

        await group.reclaim(min_idle_ms=60_000, count=128)

        assert client.autoclaim_calls[0]["min_idle_time"] == 60_000


# ---------------------------------------------------------------------------
# Prune — the consumer leak
# ---------------------------------------------------------------------------


class TestTheConsumerPrune:
    async def test_a_stale_consumer_with_no_pending_is_removed(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        client = _FakeRedis()
        client.consumers_reply = (
            {b"name": b"mahavishnu-111", b"pending": 0, b"idle": 999_999},
        )
        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="mahavishnu-999", client=client
        )

        removed = await group.prune_consumers(
            keep="mahavishnu-999", prefix="mahavishnu-", stale_after_ms=60_000
        )

        assert removed.removed == ["mahavishnu-111"]
        assert client.deleted_consumers == ["mahavishnu-111"]

    async def test_the_live_consumer_is_never_removed(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        client = _FakeRedis()
        client.consumers_reply = (
            {b"name": b"mahavishnu-999", b"pending": 0, b"idle": 0},
        )
        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="mahavishnu-999", client=client
        )

        removed = await group.prune_consumers(
            keep="mahavishnu-999", prefix="mahavishnu-", stale_after_ms=60_000
        )

        assert removed.removed == []
        assert client.deleted_consumers == []

    async def test_a_consumer_holding_pending_is_never_removed(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        client = _FakeRedis()
        client.consumers_reply = (
            {b"name": b"mahavishnu-111", b"pending": 12, b"idle": 999_999},
        )
        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="mahavishnu-999", client=client
        )

        removed = await group.prune_consumers(
            keep="mahavishnu-999", prefix="mahavishnu-", stale_after_ms=60_000
        )

        assert removed.removed == []
        assert client.deleted_consumers == []

    async def test_a_recently_active_consumer_is_never_removed(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        client = _FakeRedis()
        client.consumers_reply = (
            {b"name": b"mahavishnu-222", b"pending": 0, b"idle": 5},
        )
        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="mahavishnu-999", client=client
        )

        removed = await group.prune_consumers(
            keep="mahavishnu-999", prefix="mahavishnu-", stale_after_ms=60_000
        )

        assert removed.removed == []

    async def test_a_consumer_outside_the_prefix_is_never_removed(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        client = _FakeRedis()
        client.consumers_reply = (
            {b"name": b"someone-else", b"pending": 0, b"idle": 999_999},
        )
        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="mahavishnu-999", client=client
        )

        removed = await group.prune_consumers(
            keep="mahavishnu-999", prefix="mahavishnu-", stale_after_ms=60_000
        )

        assert removed.removed == []


# ---------------------------------------------------------------------------
# Group state
# ---------------------------------------------------------------------------


class TestTheGroupState:
    async def test_pending_consumers_and_lag_are_read_from_the_group(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        client = _FakeRedis()
        client.groups_reply = (
            {
                b"name": b"g",
                b"consumers": 437,
                b"pending": 18_198,
                b"lag": 0,
            },
            {b"name": b"other", b"consumers": 1, b"pending": 0, b"lag": 3},
        )
        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="c", client=client
        )

        state = await group.group_state()

        assert state.pending == 18_198
        assert state.consumers == 437
        assert state.lag == 0


# ---------------------------------------------------------------------------
# Group creation
# ---------------------------------------------------------------------------


class TestTheGroupIsCreatedOnInit:
    """A group that does not exist yet must be created.

    Every command against a group that was never created fails with
    NOGROUP — the read included. Oneiric's adapter created the group
    on init; this handle has to as well, or a sweeper pointed at a
    fresh stream never reads anything.
    """

    async def test_init_creates_the_consumer_group(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        client = _FakeRedis()
        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="c", client=client
        )

        await group.init()

        assert client.group_creates == [("bodai:events", "g", "0", True)]

    async def test_init_tolerates_a_group_that_already_exists(self) -> None:
        from coredis.exceptions import ResponseError

        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        class _BusyGroup(_FakeRedis):
            async def xgroup_create(
                self, key: str, groupname: str, identifier: str, mkstream: bool
            ) -> bool:
                raise ResponseError("BUSYGROUP Consumer Group name already exists")

        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="c", client=_BusyGroup()
        )

        await group.init()  # must not raise


# ---------------------------------------------------------------------------
# A failure must never be published as a zero
# ---------------------------------------------------------------------------


class TestAFailureIsNeverPublishedAsAZero:
    """A probe that failed did not measure zero.

    Returning ``GroupState()`` or ``[]`` when the probe raises makes
    "could not be determined" indistinguishable from "nothing is
    wrong" — and the health payload then reads as pristine on a group
    that could not be inspected at all.
    """

    async def test_a_failed_group_state_read_raises(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        class _BrokenGroups(_FakeRedis):
            async def xinfo_groups(self, key: str) -> tuple[dict[Any, Any], ...]:
                raise ConnectionError("redis is down")

        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="c", client=_BrokenGroups()
        )

        with pytest.raises(ConnectionError):
            await group.group_state()

    async def test_a_failed_consumer_listing_raises(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        class _BrokenConsumers(_FakeRedis):
            async def xinfo_consumers(
                self, key: str, groupname: str
            ) -> tuple[dict[Any, Any], ...]:
                raise ConnectionError("redis is down")

        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="c", client=_BrokenConsumers()
        )

        with pytest.raises(ConnectionError):
            await group.prune_consumers(keep="c", prefix="mahavishnu-")


# ---------------------------------------------------------------------------
# A prune that destroyed a message is a message-loss event
# ---------------------------------------------------------------------------


class TestAPruneThatDestroysAMessage:
    """``XGROUP DELCONSUMER`` returns how many pending messages the
    consumer owned. A non-zero return means the delete destroyed
    messages that were never acknowledged and can never be reclaimed.
    """

    async def test_the_destroyed_message_count_is_reported(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        class _RacingConsumer(_FakeRedis):
            async def xgroup_delconsumer(
                self, key: str, groupname: str, consumername: str
            ) -> int:
                return 3

        client = _RacingConsumer()
        client.consumers_reply = (
            {b"name": b"mahavishnu-111", b"pending": 0, b"idle": 999_999},
        )
        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="mahavishnu-999", client=client
        )

        result = await group.prune_consumers(
            keep="mahavishnu-999", prefix="mahavishnu-", stale_after_ms=60_000
        )

        assert result.removed == ["mahavishnu-111"]
        assert result.destroyed_messages == 3


# ---------------------------------------------------------------------------
# The reclaim bounds the work it hands back, not just the scan
# ---------------------------------------------------------------------------


class TestTheReclaimBoundsTheWork:
    async def test_the_claimed_entries_are_capped(self) -> None:
        from mahavishnu.core.events.redis_stream_group import RedisStreamGroup

        client = _FakeRedis()
        client.autoclaim_replies = [
            (
                b"0-0",
                tuple(
                    _StreamEntry(
                        identifier=f"{i}-0".encode(),
                        field_values=OrderedDict({b"channel": b"task.handoff_orphan"}),
                    )
                    for i in range(50)
                ),
                (),
            )
        ]
        group = RedisStreamGroup(
            stream="bodai:events", group="g", consumer="c", client=client
        )

        result = await group.reclaim(min_idle_ms=0, count=512, max_entries=10)

        assert result.claimed_count == 10
