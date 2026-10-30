"""Unit tests for the task system's session-buddy MCP client.

The client is the narrow bridge between mahavishnu and session-buddy
for the back-link channel. Two things about it are worth pinning:

* The **envelope unwrap**. FastMCP returns a ``CallToolResult``, not a
  dict. The task tools index the payload directly
  (``task.get("content", "")``), so handing them the raw envelope would
  make every task look empty and every dispatch fail on "task content
  is empty".
* The **surface**. The client exposes ``tasks_get`` and
  ``tasks_link_workflow`` — and nothing else. ``tasks_link_workflow`` is
  the only channel that writes ``Task.workflow_id``; the generic
  ``tasks_update`` metadata bag cannot reach the field.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.mcp.tools.tasks_session_buddy_client import (
    SessionBuddyTaskClient,
    _unwrap_tool_result,
)


class _FakeContentBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeCallToolResult:
    def __init__(
        self,
        *,
        structured: dict[str, Any] | None = None,
        content: list[Any] | None = None,
    ) -> None:
        self.structuredContent = structured
        self.content = content or []


@pytest.mark.unit
def test_unwrap_passes_a_plain_dict_through() -> None:
    assert _unwrap_tool_result({"id": "t-1"}) == {"id": "t-1"}


@pytest.mark.unit
def test_unwrap_reads_structured_content() -> None:
    """The shape FastMCP actually returns."""
    raw = _FakeCallToolResult(
        structured={"result": {"id": "t-1", "content": "do the thing"}},
    )
    assert _unwrap_tool_result(raw) == {"id": "t-1", "content": "do the thing"}


@pytest.mark.unit
def test_unwrap_falls_back_to_the_text_block() -> None:
    """Older clients put the payload in ``content[0].text`` as JSON."""
    raw = _FakeCallToolResult(
        content=[_FakeContentBlock(json.dumps({"id": "t-1"}))],
    )
    assert _unwrap_tool_result(raw) == {"id": "t-1"}


@pytest.mark.unit
def test_unwrap_returns_empty_for_junk() -> None:
    """A malformed response must not crash the caller.

    It surfaces as an empty task, which the caller's own validation
    rejects — a loud, typed failure rather than an opaque crash.
    """
    assert _unwrap_tool_result(_FakeCallToolResult(content=[_FakeContentBlock("not json")])) == {}
    assert _unwrap_tool_result(None) == {}
    assert _unwrap_tool_result("nonsense") == {}


@pytest.mark.unit
async def test_tasks_get_calls_the_right_tool() -> None:
    client = SessionBuddyTaskClient("http://127.0.0.1:8678/mcp")
    fake = AsyncMock(
        return_value=_FakeCallToolResult(
            structured={"result": {"id": "t-1", "content": "hello"}},
        ),
    )
    with patch.object(client._client, "call_tool", new=fake):
        result = await client.tasks_get("t-1")

    fake.assert_awaited_once_with("tasks_get", {"task_id": "t-1"})
    assert result["content"] == "hello"


@pytest.mark.unit
async def test_tasks_link_workflow_calls_the_typed_channel() -> None:
    """The link goes through ``tasks_link_workflow`` — never
    ``tasks_update`` with a metadata patch.

    The metadata bag is caller-supplied content; a server-set field
    sourced from it would let any caller forge a workflow binding.
    """
    client = SessionBuddyTaskClient("http://127.0.0.1:8678/mcp")
    fake = AsyncMock(
        return_value=_FakeCallToolResult(structured={"result": {"id": "t-1"}}),
    )
    with patch.object(client._client, "call_tool", new=fake):
        await client.tasks_link_workflow("t-1", "wf_abc")

    fake.assert_awaited_once_with(
        "tasks_link_workflow",
        {"task_id": "t-1", "workflow_id": "wf_abc"},
    )


@pytest.mark.unit
async def test_aclose_closes_the_underlying_session() -> None:
    """The client holds a persistent MCP session; it must be closed."""
    client = SessionBuddyTaskClient("http://127.0.0.1:8678/mcp")
    closer = AsyncMock()
    with patch.object(client._client, "aclose", new=closer):
        await client.aclose()
    closer.assert_awaited_once()


@pytest.mark.unit
def test_the_client_rejects_a_bad_url() -> None:
    with pytest.raises(ValueError):
        SessionBuddyTaskClient("not-a-url")


@pytest.mark.unit
def test_the_process_client_is_a_singleton() -> None:
    """One client, one MCP session.

    The client holds a persistent connection, so one per process is the
    right cardinality — one per call would open a connection per call.
    """
    from mahavishnu.mcp.tools.tasks_session_buddy_client import (
        get_session_buddy_task_client,
    )

    first = get_session_buddy_task_client()
    second = get_session_buddy_task_client()
    assert first is second
    assert isinstance(first, SessionBuddyTaskClient)


@pytest.mark.unit
def test_the_client_exposes_only_the_task_surface() -> None:
    """The client is a narrow adapter, not a general MCP proxy."""
    client = SessionBuddyTaskClient("http://127.0.0.1:8678/mcp")
    public = {name for name in dir(client) if not name.startswith("_")}
    assert "tasks_get" in public
    assert "tasks_link_workflow" in public
    assert "tasks_update" not in public, (
        "the generic update path must not be part of the back-link client"
    )


@pytest.mark.unit
def test_the_client_does_not_expose_a_raw_call_tool() -> None:
    """Callers go through the named methods, not raw MCP calls."""
    client = SessionBuddyTaskClient("http://127.0.0.1:8678/mcp")
    assert not hasattr(client, "call_tool")


@pytest.mark.unit
def test_the_underlying_transport_is_not_leaked() -> None:
    """``_client`` is private; nothing outside should reach the session."""
    client = SessionBuddyTaskClient("http://127.0.0.1:8678/mcp")
    assert isinstance(client._client, MagicMock | type(client._client))
