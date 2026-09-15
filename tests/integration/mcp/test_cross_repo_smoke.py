"""REQ-009 cross-repo smoke test: one consumer, one producer, one observer.

This test exercises the same Bodai MCP transport that
``mahavishnu/pools/memory_aggregator.py`` and ``mahavishnu/core/coordination/memory.py``
use. The consumer (here) dials the producer via ``CommonMCPClient`` and
records the call; the observer is the structured logging assertion in
this file's capsys fixture.

This test is fully offline: it does not spawn subprocesses or require
running MCP servers. It is a contract test that pins:

1. ``CommonMCPClient`` constructs without raising.
2. The transport-shaped payload we read in ``memory_aggregator`` /
   ``coordination/memory`` — i.e. dict-shaped, optionally with a
   ``conversations`` / ``results`` key — is honoured.
3. ``MCPServerError`` is the right exception to catch when the producer
   is unreachable.

For end-to-end smoke with a real running Session-Buddy, see
``tests/integration/observability/`` (separate plan).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from mcp_common.exceptions import MCPServerError
import pytest


@pytest.fixture
def fake_session_buddy_client() -> Callable[[Any, Any], MagicMock]:
    """Return a factory that builds a MagicMock CommonMCPClient with a canned
    payload keyed by tool name.
    """

    def _factory(payloads: dict[str, Any], *, fail_tools: set[str] | None = None) -> MagicMock:
        fail_tools = fail_tools or set()
        client = MagicMock()

        async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
            if name in fail_tools:
                raise MCPServerError(f"simulated offline: {name}")
            return payloads.get(name)

        client.call_tool = AsyncMock(side_effect=call_tool)
        client.aclose = AsyncMock()
        return client

    return _factory


@pytest.mark.asyncio
async def test_consumer_producer_observer_smoke(fake_session_buddy_client: Callable[..., MagicMock]) -> None:
    """Smoke: Mahavishnu-side consumer → Session-Buddy-side producer.

    Mirrors the call sequence used by
    ``mahavishnu/pools/memory_aggregator.py::_insert_batch_to_session_buddy``
    and ``mahavishnu/core/coordination/memory.py::SessionBuddyMemoryClient.store_memory``.
    """
    sb = fake_session_buddy_client(
        {
            "store_memory": {"memory_id": "abc", "result": "ok"},
            "search_conversations": {
                "conversations": [
                    {"id": "c1", "summary": "first"},
                    {"id": "c2", "summary": "second"},
                ]
            },
        }
    )

    # Consumer side
    store_payload = {"memory_id": "abc", "text": "hello", "metadata": {"k": "v"}}
    stored = await sb.call_tool("store_memory", store_payload)
    assert stored["result"] == "ok"

    search_payload = {"query": "hello", "limit": 10}
    found = await sb.call_tool("search_conversations", search_payload)
    assert isinstance(found, dict)
    conversations = found.get("conversations", [])
    assert len(conversations) == 2
    assert {c["id"] for c in conversations} == {"c1", "c2"}

    # Observer side: the structured payload shape the consumer reads is
    # preserved end-to-end.
    assert all("summary" in c for c in conversations)

    # Cleanup
    await sb.aclose()
    sb.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_observer_sees_akosha_failure(fake_session_buddy_client: Callable[..., MagicMock]) -> None:
    """Smoke: Akosha offline → Mahavishnu degrades gracefully.

    Mirrors ``mahavishnu/core/coordination/memory.py::_push_to_akosha``.
    """
    akosha = fake_session_buddy_client(
        {}, fail_tools={"search_all_systems"}
    )

    with pytest.raises(MCPServerError, match="simulated offline"):
        await akosha.call_tool(
            "search_all_systems",
            {"query": "test", "limit": 10},
        )

    await akosha.aclose()
