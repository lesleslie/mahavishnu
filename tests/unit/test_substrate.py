"""Tests for the substrate facade — ``mahavishnu/core/substrate.py``.

The facade replaced a dynamic ``importlib.import_module("mcp")`` lookup
that resolved to the MCP Python SDK, which has none of the retired
service's functions. Every lookup returned ``None`` and every producer
silently discarded its data.

These tests pin the contract the call sites depend on:

* ``put`` is **synchronous** — the producers that call it are sync
  functions, and an un-awaited coroutine would discard the write.
* ``get`` is **awaitable** — reads were MCP tool calls.
* values round-trip as JSON, so a sibling reading the same key through
  ``mahavishnu_kv_get`` sees the same payload.
"""

from __future__ import annotations

import pytest

from mahavishnu.core import substrate
from mahavishnu.core.kv_store import kv_store


@pytest.fixture(autouse=True)
def _clean_store():
    """Leave the shared store empty around each test."""
    kv_store.clear()
    yield
    kv_store.clear()


class TestPutGetRoundTrip:
    def test_put_then_get_returns_the_payload(self) -> None:
        substrate.put("workflow/v1/wf-1", {"status": "running"})

        assert substrate.kv_store.get("workflow/v1/wf-1") is not None

    @pytest.mark.asyncio
    async def test_dict_round_trips(self) -> None:
        substrate.put("k1", {"a": 1, "b": [2, 3]})

        assert await substrate.get("k1") == {"a": 1, "b": [2, 3]}

    @pytest.mark.asyncio
    async def test_list_round_trips(self) -> None:
        substrate.put("k2", [{"service_id": "a"}, {"service_id": "b"}])

        assert await substrate.get("k2") == [{"service_id": "a"}, {"service_id": "b"}]

    @pytest.mark.asyncio
    async def test_get_on_a_miss_returns_none(self) -> None:
        assert await substrate.get("absent") is None

    def test_put_is_synchronous(self) -> None:
        """A sync producer must not create an un-awaited coroutine."""
        substrate.put("k3", {"x": 1})

        assert kv_store.get("k3") is not None


class TestEncoding:
    @pytest.mark.asyncio
    async def test_msgspec_struct_is_encoded_as_builtins(self) -> None:
        import msgspec

        class Sample(msgspec.Struct):
            name: str
            count: int

        substrate.put("k4", Sample(name="a", count=2))

        assert await substrate.get("k4") == {"name": "a", "count": 2}

    @pytest.mark.asyncio
    async def test_a_string_round_trips(self) -> None:
        """A bare string must not be confused with an undecodable record."""
        substrate.put("k5", "plain text")

        assert await substrate.get("k5") == "plain text"

    @pytest.mark.asyncio
    async def test_a_corrupt_record_reads_as_absent(self) -> None:
        kv_store.put("k6", "{not json")

        assert await substrate.get("k6") is None


class TestListPrefix:
    def test_lists_only_matching_keys(self) -> None:
        substrate.put("ecosystem-services/a/", {"service_id": "a"})
        substrate.put("ecosystem-services/b/", {"service_id": "b"})
        substrate.put("ecosystem-events/c/", {"event_id": "c"})

        found = substrate.list_prefix("ecosystem-services/")

        assert found == [{"service_id": "a"}, {"service_id": "b"}]

    def test_an_unmatched_prefix_returns_empty(self) -> None:
        substrate.put("a/1", {"x": 1})

        assert substrate.list_prefix("b/") == []


class TestSharedWithTheKvTools:
    """The facade and the public KV tools must see one store."""

    def test_a_facade_write_is_visible_to_the_kv_tool_store(self) -> None:
        from mahavishnu.mcp.tools.kv_tools import kv_store as tool_store

        substrate.put("ecosystem-services/x/", {"service_id": "x"})

        assert tool_store.get("ecosystem-services/x/") is not None
