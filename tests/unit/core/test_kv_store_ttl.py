"""TTL semantics of the process-local KV store.

The store is the substrate behind the ``mahavishnu_kv_*`` MCP tools and
its TTL is load-bearing: the budget watchdog's mutual-exclusion lease,
the plan_index index, the approval TTL and the adapter health cache all
rely on an expired record reading as **absent**.

The clock is injected, so none of these tests sleeps.
"""

from __future__ import annotations

import pytest

from mahavishnu.core.kv_store import ProcessLocalKV

pytestmark = pytest.mark.unit


class _Clock:
    """A manually advanced monotonic clock (seconds)."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def store(clock: _Clock) -> ProcessLocalKV:
    """A store on its own clock — not the process-wide singleton."""
    return ProcessLocalKV(now=clock)


class TestTtlExpiry:
    """An expired entry must read as absent everywhere."""

    def test_a_live_entry_is_readable(
        self, store: ProcessLocalKV, clock: _Clock
    ) -> None:
        store.put("k", "v", ttl=60)
        clock.advance(59)
        assert store.get("k") == "v"

    def test_an_expired_entry_reads_as_absent(
        self, store: ProcessLocalKV, clock: _Clock
    ) -> None:
        store.put("k", "v", ttl=60)
        clock.advance(61)
        assert store.get("k") is None

    def test_an_expired_entry_is_absent_from_a_listing(
        self, store: ProcessLocalKV, clock: _Clock
    ) -> None:
        store.put("pfx/live", "v1", ttl=600)
        store.put("pfx/dead", "v2", ttl=60)
        clock.advance(61)
        assert store.list_prefix("pfx/") == [("pfx/live", "v1")]

    def test_an_expired_entry_is_not_counted(
        self, store: ProcessLocalKV, clock: _Clock
    ) -> None:
        store.put("live", "v", ttl=600)
        store.put("dead", "v", ttl=60)
        assert store.count() == 2
        clock.advance(61)
        assert store.count() == 1

    def test_an_expired_entry_is_not_counted_without_any_ttl_entry(
        self, store: ProcessLocalKV, clock: _Clock
    ) -> None:
        store.put("dead", "v", ttl=1)
        clock.advance(2)
        assert store.count() == 0

    def test_a_zero_ttl_expires_immediately(self, store: ProcessLocalKV) -> None:
        """``ttl=0`` means "already gone" — the ``EXPIRE key 0`` semantic."""
        store.put("k", "v", ttl=0)
        assert store.get("k") is None
        assert store.list_prefix("") == []
        assert store.count() == 0

    def test_an_expired_entry_is_physically_dropped(
        self, store: ProcessLocalKV, clock: _Clock
    ) -> None:
        """The record is removed from the mapping once the store is touched."""
        store.put("k", "v", ttl=60)
        clock.advance(61)
        # Any read sweeps the lapsed entry out of the mapping.
        assert store.get("k") is None
        assert store._data == {}


class TestNoTtl:
    """An entry written without a TTL never expires."""

    def test_an_entry_without_a_ttl_never_expires(
        self, store: ProcessLocalKV, clock: _Clock
    ) -> None:
        store.put("k", "v")
        clock.advance(10_000_000)
        assert store.get("k") == "v"
        assert store.count() == 1

    def test_rewriting_a_key_without_a_ttl_clears_its_deadline(
        self, store: ProcessLocalKV, clock: _Clock
    ) -> None:
        """A TTL-less rewrite must not be evicted by the old deadline."""
        store.put("k", "v1", ttl=60)
        clock.advance(30)
        store.put("k", "v2")
        clock.advance(120)
        assert store.get("k") == "v2"

    def test_rewriting_a_key_with_a_ttl_replaces_the_deadline(
        self, store: ProcessLocalKV, clock: _Clock
    ) -> None:
        """A longer TTL must not be cut short by the previous deadline."""
        store.put("k", "v", ttl=60)
        clock.advance(30)
        store.put("k", "v", ttl=600)
        clock.advance(120)
        assert store.get("k") == "v"

    def test_a_shorter_ttl_shortens_the_deadline(
        self, store: ProcessLocalKV, clock: _Clock
    ) -> None:
        store.put("k", "v", ttl=600)
        store.put("k", "v", ttl=30)
        clock.advance(31)
        assert store.get("k") is None


class TestDeleteAndClear:
    """``delete`` and ``clear`` keep working — expiry included."""

    def test_delete_removes_the_entry(self, store: ProcessLocalKV) -> None:
        store.put("k", "v", ttl=60)
        store.delete("k")
        assert store.get("k") is None
        assert store.count() == 0

    def test_delete_removes_the_deadline_too(
        self, store: ProcessLocalKV, clock: _Clock
    ) -> None:
        """A deleted key must not leave a deadline that purges a later write."""
        store.put("k", "v", ttl=60)
        store.delete("k")
        store.put("k", "v2")
        clock.advance(120)
        assert store.get("k") == "v2"

    def test_delete_of_an_absent_key_is_a_noop(self, store: ProcessLocalKV) -> None:
        store.delete("missing")
        assert store.count() == 0

    def test_clear_removes_every_record_and_deadline(
        self, store: ProcessLocalKV, clock: _Clock
    ) -> None:
        store.put("a", "1", ttl=60)
        store.put("b", "2")
        store.clear()
        assert store.count() == 0
        assert store.list_prefix("") == []
        # A cleared store carries no stale deadline into the next write.
        store.put("c", "3")
        clock.advance(120)
        assert store.get("c") == "3"


class TestMixedEntries:
    """Live and expired entries coexist."""

    def test_only_the_live_entries_are_visible(
        self, store: ProcessLocalKV, clock: _Clock
    ) -> None:
        store.put("a", "1", ttl=600)
        store.put("b", "2", ttl=60)
        store.put("c", "3")
        clock.advance(61)
        assert store.get("b") is None
        assert store.get("a") == "1"
        assert store.get("c") == "3"
        assert store.count() == 2
        assert {key for key, _ in store.list_prefix("")} == {"a", "c"}
