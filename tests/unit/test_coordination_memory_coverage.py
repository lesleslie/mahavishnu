"""Tests for mahavishnu.core.coordination.memory.

Covers SessionBuddyMemoryClient, CoordinationMemory, and
CoordinationManagerWithMemory public surface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mahavishnu.core.coordination.manager import CoordinationManager
from mahavishnu.core.coordination.memory import (
    CoordinationManagerWithMemory,
    CoordinationMemory,
    SessionBuddyMemoryClient,
)
from mahavishnu.core.coordination.models import (
    CrossRepoIssue,
    CrossRepoPlan,
    CrossRepoTodo,
    Dependency,
    DependencyType,
    Priority,
)
from mahavishnu.core.status import (
    DependencyStatus,
    IssueStatus,
    PlanStatus,
    TodoStatus,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _make_issue(**overrides: Any) -> CrossRepoIssue:
    defaults: dict[str, Any] = {
        "id": "ISSUE-001",
        "title": "Test issue",
        "description": "Test description",
        "status": IssueStatus.PENDING,
        "priority": Priority.HIGH,
        "severity": "bug",
        "repos": ["mahavishnu"],
        "created": "2026-01-31T00:00:00",
        "updated": "2026-01-31T00:00:00",
        "assignee": "alice",
    }
    defaults.update(overrides)
    return CrossRepoIssue(**defaults)


def _make_todo(**overrides: Any) -> CrossRepoTodo:
    defaults: dict[str, Any] = {
        "id": "TODO-001",
        "task": "Implement something",
        "description": "Detail",
        "repo": "mahavishnu",
        "status": TodoStatus.PENDING,
        "priority": Priority.MEDIUM,
        "created": "2026-01-31T00:00:00",
        "updated": "2026-01-31T00:00:00",
        "estimated_hours": 4.0,
    }
    defaults.update(overrides)
    return CrossRepoTodo(**defaults)


def _make_dependency(**overrides: Any) -> Dependency:
    defaults: dict[str, Any] = {
        "id": "DEP-001",
        "consumer": "fastblocks",
        "provider": "oneiric",
        "type": DependencyType.RUNTIME,
        "version_constraint": ">=0.2.0",
        "status": DependencyStatus.SATISFIED,
        "created": "2026-01-15T00:00:00",
        "updated": "2026-01-30T00:00:00",
        "notes": "needs oneiric 0.2.0+",
    }
    defaults.update(overrides)
    return Dependency(**defaults)


def _make_plan(**overrides: Any) -> CrossRepoPlan:
    defaults: dict[str, Any] = {
        "id": "PLAN-001",
        "title": "Q1 plan",
        "description": "Big plan",
        "status": PlanStatus.DRAFT,
        "repos": ["mahavishnu"],
        "created": "2026-01-31T00:00:00",
        "updated": "2026-01-31T00:00:00",
        "target": "2026-04-30T00:00:00",
    }
    defaults.update(overrides)
    return CrossRepoPlan(**defaults)


# ---------------------------------------------------------------------------
# SessionBuddyMemoryClient
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSessionBuddyMemoryClient:
    def test_init_strips_trailing_slash(self) -> None:
        client = SessionBuddyMemoryClient(base_url="http://localhost:8678/mcp/")
        assert client._base_url == "http://localhost:8678/mcp"

    def test_init_keeps_url_without_slash(self) -> None:
        client = SessionBuddyMemoryClient(base_url="http://localhost:8678/mcp")
        assert client._base_url == "http://localhost:8678/mcp"

    @pytest.mark.asyncio
    async def test_store_memory_returns_result_field(self) -> None:
        client = SessionBuddyMemoryClient(base_url="http://x")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"id": "abc"}}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._client, "post", new=AsyncMock(return_value=mock_response)):
            result = await client.store_memory("c1", "hello", {"k": "v"})
        assert result == {"id": "abc"}

    @pytest.mark.asyncio
    async def test_store_memory_returns_payload_when_no_result(self) -> None:
        client = SessionBuddyMemoryClient(base_url="http://x")
        mock_response = MagicMock()
        mock_response.json.return_value = ["raw", "payload"]
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._client, "post", new=AsyncMock(return_value=mock_response)):
            result = await client.store_memory("c1", "hello", {})
        assert result == ["raw", "payload"]

    @pytest.mark.asyncio
    async def test_store_memory_raises_on_http_error(self) -> None:
        client = SessionBuddyMemoryClient(base_url="http://x")
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPError("boom")

        with patch.object(client._client, "post", new=AsyncMock(return_value=mock_response)):
            with pytest.raises(httpx.HTTPError):
                await client.store_memory("c1", "hello", {})

    @pytest.mark.asyncio
    async def test_search_returns_list_result(self) -> None:
        client = SessionBuddyMemoryClient(base_url="http://x")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": [{"id": "x"}, {"id": "y"}]}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._client, "post", new=AsyncMock(return_value=mock_response)):
            results = await client.search("query", filters={"a": 1}, limit=5)
        assert results == [{"id": "x"}, {"id": "y"}]

    @pytest.mark.asyncio
    async def test_search_returns_results_key_in_dict(self) -> None:
        client = SessionBuddyMemoryClient(base_url="http://x")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"results": [{"id": "a"}]}}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._client, "post", new=AsyncMock(return_value=mock_response)):
            results = await client.search("q", filters={}, limit=10)
        assert results == [{"id": "a"}]

    @pytest.mark.asyncio
    async def test_search_returns_items_key_in_dict(self) -> None:
        client = SessionBuddyMemoryClient(base_url="http://x")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"items": [{"id": "a"}]}}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._client, "post", new=AsyncMock(return_value=mock_response)):
            results = await client.search("q", filters={}, limit=10)
        assert results == [{"id": "a"}]

    @pytest.mark.asyncio
    async def test_search_returns_conversations_key_in_dict(self) -> None:
        client = SessionBuddyMemoryClient(base_url="http://x")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"conversations": [{"id": "c"}]}}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._client, "post", new=AsyncMock(return_value=mock_response)):
            results = await client.search("q", filters={}, limit=10)
        assert results == [{"id": "c"}]

    @pytest.mark.asyncio
    async def test_search_returns_empty_on_unrecognised_payload(self) -> None:
        client = SessionBuddyMemoryClient(base_url="http://x")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"unknown_key": "stuff"}}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._client, "post", new=AsyncMock(return_value=mock_response)):
            results = await client.search("q", filters={}, limit=10)
        assert results == []

    @pytest.mark.asyncio
    async def test_search_returns_empty_on_top_level_non_dict(self) -> None:
        client = SessionBuddyMemoryClient(base_url="http://x")
        mock_response = MagicMock()
        mock_response.json.return_value = "string payload"
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._client, "post", new=AsyncMock(return_value=mock_response)):
            results = await client.search("q", filters={}, limit=10)
        assert results == []

    @pytest.mark.asyncio
    async def test_search_raises_on_http_error(self) -> None:
        client = SessionBuddyMemoryClient(base_url="http://x")
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPError("bad")

        with patch.object(client._client, "post", new=AsyncMock(return_value=mock_response)):
            with pytest.raises(httpx.HTTPError):
                await client.search("q", filters={}, limit=10)

    @pytest.mark.asyncio
    async def test_aclose_delegates_to_underlying_client(self) -> None:
        client = SessionBuddyMemoryClient(base_url="http://x")
        with patch.object(client._client, "aclose", new=AsyncMock()) as mock_close:
            await client.aclose()
        mock_close.assert_awaited_once()


# ---------------------------------------------------------------------------
# CoordinationMemory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCoordinationMemoryInit:
    def test_init_without_session_buddy(self) -> None:
        mem = CoordinationMemory()
        assert mem.session_buddy is None
        assert mem.collection == "mahavishnu_coordination"
        assert mem._akosha_url is None
        assert mem._http is None

    def test_init_with_akosha_url_creates_http(self) -> None:
        mem = CoordinationMemory(akosha_url="http://akosha:8682/mcp")
        assert mem._akosha_url == "http://akosha:8682/mcp"
        assert mem._http is not None
        assert isinstance(mem._http, httpx.AsyncClient)


@pytest.mark.unit
class TestCoordinationMemoryStoreIssueEvent:
    @pytest.mark.asyncio
    async def test_returns_early_without_session_buddy(self) -> None:
        mem = CoordinationMemory()
        issue = _make_issue()
        # Should not raise even without a session_buddy client
        await mem.store_issue_event("created", issue)

    @pytest.mark.asyncio
    async def test_stores_event_with_minimal_args(self) -> None:
        sb = MagicMock()
        sb.store_memory = AsyncMock()
        mem = CoordinationMemory(session_buddy_client=sb)
        issue = _make_issue()

        await mem.store_issue_event("created", issue)

        sb.store_memory.assert_awaited_once()
        kwargs = sb.store_memory.await_args.kwargs
        assert kwargs["collection"] == "mahavishnu_coordination"
        assert "Created issue ISSUE-001" in kwargs["content"]
        meta = kwargs["metadata"]
        assert meta["event_type"] == "created"
        assert meta["entity_id"] == "ISSUE-001"
        assert meta["entity_type"] == "issue"
        assert meta["title"] == "Test issue"
        assert meta["status"] == IssueStatus.PENDING.value
        assert meta["priority"] == Priority.HIGH.value
        assert meta["repos"] == ["mahavishnu"]
        assert meta["assignee"] == "alice"
        assert "timestamp" in meta
        # no `changes` key when not provided
        assert "changes" not in meta

    @pytest.mark.asyncio
    async def test_stores_event_with_changes(self) -> None:
        sb = MagicMock()
        sb.store_memory = AsyncMock()
        mem = CoordinationMemory(session_buddy_client=sb)
        issue = _make_issue()

        changes = {"status": "closed"}
        await mem.store_issue_event("updated", issue, changes=changes)

        meta = sb.store_memory.await_args.kwargs["metadata"]
        assert meta["changes"] == changes
        assert meta["event_type"] == "updated"

    @pytest.mark.asyncio
    async def test_logs_error_when_session_buddy_fails(self) -> None:
        sb = MagicMock()
        sb.store_memory = AsyncMock(side_effect=RuntimeError("boom"))
        mem = CoordinationMemory(session_buddy_client=sb)
        issue = _make_issue()

        # Should not raise -- failure is logged and swallowed
        await mem.store_issue_event("created", issue)

    @pytest.mark.asyncio
    async def test_capitalizes_event_type_in_content(self) -> None:
        sb = MagicMock()
        sb.store_memory = AsyncMock()
        mem = CoordinationMemory(session_buddy_client=sb)

        await mem.store_issue_event("closed", _make_issue())
        content = sb.store_memory.await_args.kwargs["content"]
        assert content.startswith("Closed issue")


@pytest.mark.unit
class TestCoordinationMemoryStoreTodoEvent:
    @pytest.mark.asyncio
    async def test_returns_early_without_session_buddy(self) -> None:
        mem = CoordinationMemory()
        await mem.store_todo_event("created", _make_todo())

    @pytest.mark.asyncio
    async def test_stores_todo_event_with_metadata(self) -> None:
        sb = MagicMock()
        sb.store_memory = AsyncMock()
        mem = CoordinationMemory(session_buddy_client=sb)
        todo = _make_todo(estimated_hours=8.0, assignee="bob")

        await mem.store_todo_event("created", todo)

        sb.store_memory.assert_awaited_once()
        kwargs = sb.store_memory.await_args.kwargs
        assert "Created todo TODO-001" in kwargs["content"]
        assert "mahavishnu" in kwargs["content"]
        meta = kwargs["metadata"]
        assert meta["event_type"] == "created"
        assert meta["entity_id"] == "TODO-001"
        assert meta["entity_type"] == "todo"
        assert meta["task"] == "Implement something"
        assert meta["repo"] == "mahavishnu"
        assert meta["status"] == TodoStatus.PENDING.value
        assert meta["priority"] == Priority.MEDIUM.value
        assert meta["assignee"] == "bob"
        assert meta["estimated_hours"] == 8.0
        assert "timestamp" in meta
        assert "changes" not in meta

    @pytest.mark.asyncio
    async def test_stores_todo_event_with_changes(self) -> None:
        sb = MagicMock()
        sb.store_memory = AsyncMock()
        mem = CoordinationMemory(session_buddy_client=sb)
        changes = {"status": "completed"}
        await mem.store_todo_event("updated", _make_todo(), changes=changes)
        meta = sb.store_memory.await_args.kwargs["metadata"]
        assert meta["changes"] == changes


@pytest.mark.unit
class TestCoordinationMemoryStoreDependencyEvent:
    @pytest.mark.asyncio
    async def test_returns_early_without_session_buddy(self) -> None:
        mem = CoordinationMemory()
        await mem.store_dependency_event("validated", _make_dependency())

    @pytest.mark.asyncio
    async def test_stores_dependency_event_with_metadata(self) -> None:
        sb = MagicMock()
        sb.store_memory = AsyncMock()
        mem = CoordinationMemory(session_buddy_client=sb)
        dep = _make_dependency()

        await mem.store_dependency_event("validated", dep)

        sb.store_memory.assert_awaited_once()
        kwargs = sb.store_memory.await_args.kwargs
        content = kwargs["content"]
        assert "Validated dependency DEP-001" in content
        assert "fastblocks" in content
        assert "oneiric" in content
        assert ">=0.2.0" in content
        meta = kwargs["metadata"]
        assert meta["event_type"] == "validated"
        assert meta["entity_id"] == "DEP-001"
        assert meta["entity_type"] == "dependency"
        assert meta["consumer"] == "fastblocks"
        assert meta["provider"] == "oneiric"
        assert meta["type"] == DependencyType.RUNTIME.value
        assert meta["version_constraint"] == ">=0.2.0"
        assert meta["status"] == DependencyStatus.SATISFIED.value
        assert "validation" not in meta

    @pytest.mark.asyncio
    async def test_stores_dependency_event_with_validation_result(self) -> None:
        sb = MagicMock()
        sb.store_memory = AsyncMock()
        mem = CoordinationMemory(session_buddy_client=sb)

        validation = {"ok": True}
        await mem.store_dependency_event("validated", _make_dependency(), validation_result=validation)
        meta = sb.store_memory.await_args.kwargs["metadata"]
        assert meta["validation"] == validation


@pytest.mark.unit
class TestCoordinationMemoryStorePlanEvent:
    @pytest.mark.asyncio
    async def test_returns_early_without_session_buddy(self) -> None:
        mem = CoordinationMemory()
        await mem.store_plan_event("created", _make_plan())

    @pytest.mark.asyncio
    async def test_stores_plan_event_with_metadata(self) -> None:
        sb = MagicMock()
        sb.store_memory = AsyncMock()
        mem = CoordinationMemory(session_buddy_client=sb)
        plan = _make_plan()

        await mem.store_plan_event("created", plan)

        sb.store_memory.assert_awaited_once()
        kwargs = sb.store_memory.await_args.kwargs
        content = kwargs["content"]
        assert "Created plan PLAN-001" in content
        assert "Q1 plan" in content
        meta = kwargs["metadata"]
        assert meta["event_type"] == "created"
        assert meta["entity_id"] == "PLAN-001"
        assert meta["entity_type"] == "plan"
        assert meta["title"] == "Q1 plan"
        assert meta["status"] == PlanStatus.DRAFT.value
        assert meta["repos"] == ["mahavishnu"]
        assert meta["target"] == "2026-04-30T00:00:00"
        assert meta["milestone_count"] == 0
        assert "milestone" not in meta

    @pytest.mark.asyncio
    async def test_stores_plan_event_with_milestone(self) -> None:
        sb = MagicMock()
        sb.store_memory = AsyncMock()
        mem = CoordinationMemory(session_buddy_client=sb)

        await mem.store_plan_event("milestone_completed", _make_plan(), milestone="M-1")
        meta = sb.store_memory.await_args.kwargs["metadata"]
        assert meta["milestone"] == "M-1"

    @pytest.mark.asyncio
    async def test_milestone_count_reflects_plan_milestones(self) -> None:
        from mahavishnu.core.coordination.models import Milestone

        sb = MagicMock()
        sb.store_memory = AsyncMock()
        mem = CoordinationMemory(session_buddy_client=sb)
        plan = _make_plan(
            milestones=[
                Milestone(
                    id="M-1",
                    name="alpha",
                    description="d",
                    due="2026-02-01T00:00:00",
                ),
                Milestone(
                    id="M-2",
                    name="beta",
                    description="d",
                    due="2026-03-01T00:00:00",
                ),
            ]
        )

        await mem.store_plan_event("created", plan)
        meta = sb.store_memory.await_args.kwargs["metadata"]
        assert meta["milestone_count"] == 2


@pytest.mark.unit
class TestCoordinationMemorySearch:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_session_buddy(self) -> None:
        mem = CoordinationMemory()
        assert await mem.search_coordination_history("any") == []

    @pytest.mark.asyncio
    async def test_search_builds_minimal_filters(self) -> None:
        sb = MagicMock()
        sb.search = AsyncMock(return_value=[{"id": "1"}])
        mem = CoordinationMemory(session_buddy_client=sb)

        results = await mem.search_coordination_history("hello")

        sb.search.assert_awaited_once()
        kwargs = sb.search.await_args.kwargs
        assert kwargs["query"] == "hello"
        assert kwargs["filters"] == {"collection": "mahavishnu_coordination"}
        assert kwargs["limit"] == 20
        assert results == [{"id": "1"}]

    @pytest.mark.asyncio
    async def test_search_with_entity_type_filter(self) -> None:
        sb = MagicMock()
        sb.search = AsyncMock(return_value=[])
        mem = CoordinationMemory(session_buddy_client=sb)

        await mem.search_coordination_history("foo", entity_type="issue")
        filters = sb.search.await_args.kwargs["filters"]
        assert filters["entity_type"] == "issue"
        assert filters["collection"] == "mahavishnu_coordination"

    @pytest.mark.asyncio
    async def test_search_with_repo_filter(self) -> None:
        sb = MagicMock()
        sb.search = AsyncMock(return_value=[])
        mem = CoordinationMemory(session_buddy_client=sb)

        await mem.search_coordination_history("foo", repo="mahavishnu")
        filters = sb.search.await_args.kwargs["filters"]
        assert filters["$or"] == [{"repos": "mahavishnu"}, {"repo": "mahavishnu"}]

    @pytest.mark.asyncio
    async def test_search_with_all_filters(self) -> None:
        sb = MagicMock()
        sb.search = AsyncMock(return_value=[])
        mem = CoordinationMemory(session_buddy_client=sb)

        await mem.search_coordination_history(
            "foo", entity_type="todo", repo="x", limit=5
        )
        kwargs = sb.search.await_args.kwargs
        assert kwargs["limit"] == 5
        assert kwargs["filters"]["entity_type"] == "todo"
        assert "$or" in kwargs["filters"]

    @pytest.mark.asyncio
    async def test_search_returns_empty_on_exception(self) -> None:
        sb = MagicMock()
        sb.search = AsyncMock(side_effect=RuntimeError("network"))
        mem = CoordinationMemory(session_buddy_client=sb)

        results = await mem.search_coordination_history("foo")
        assert results == []


@pytest.mark.unit
class TestCoordinationMemoryTrends:
    @pytest.mark.asyncio
    async def test_trends_returns_error_without_session_buddy(self) -> None:
        mem = CoordinationMemory()
        result = await mem.get_coordination_trends()
        assert result == {"error": "Session-Buddy not available"}

    @pytest.mark.asyncio
    async def test_trends_returns_placeholder_with_session_buddy(self) -> None:
        sb = MagicMock()
        mem = CoordinationMemory(session_buddy_client=sb)
        result = await mem.get_coordination_trends(repo="x", days=7)
        assert result["message"] == "Trend analysis not yet implemented"
        assert result["repo"] == "x"
        assert result["days"] == 7

    @pytest.mark.asyncio
    async def test_trends_defaults(self) -> None:
        sb = MagicMock()
        mem = CoordinationMemory(session_buddy_client=sb)
        result = await mem.get_coordination_trends()
        assert result["repo"] is None
        assert result["days"] == 30


# ---------------------------------------------------------------------------
# CoordinationMemory._push_to_akosha
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCoordinationMemoryAkoshaPush:
    @pytest.mark.asyncio
    async def test_push_to_akosha_no_http(self) -> None:
        mem = CoordinationMemory()  # no akosha url
        # Should silently no-op
        await mem._push_to_akosha("content", {"k": "v"})

    @pytest.mark.asyncio
    async def test_push_to_akosha_with_http(self) -> None:
        mem = CoordinationMemory(akosha_url="http://akosha:8682/mcp")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch.object(mem._http, "post", new=AsyncMock(return_value=mock_response)) as mock_post:
            await mem._push_to_akosha("c", {"m": 1})

        mock_post.assert_awaited_once()
        url = mock_post.await_args.args[0]
        assert url == "http://akosha:8682/mcp/tools/call"
        body = mock_post.await_args.kwargs["json"]
        assert body["name"] == "store_memory"
        assert body["arguments"]["content"] == "c"
        assert body["arguments"]["metadata"] == {"m": 1}
        assert body["arguments"]["collection"] == "mahavishnu_coordination"

    @pytest.mark.asyncio
    async def test_push_to_akosha_http_error_logged(self) -> None:
        mem = CoordinationMemory(akosha_url="http://akosha:8682/mcp")
        with patch.object(
            mem._http, "post", new=AsyncMock(side_effect=httpx.TransportError("x"))
        ):
            # Should not raise
            await mem._push_to_akosha("c", {})

    @pytest.mark.asyncio
    async def test_push_to_akosha_httperror_logged(self) -> None:
        mem = CoordinationMemory(akosha_url="http://akosha:8682/mcp")
        with patch.object(
            mem._http, "post", new=AsyncMock(side_effect=httpx.HTTPError("bad"))
        ):
            await mem._push_to_akosha("c", {})

    @pytest.mark.asyncio
    async def test_close_closes_http(self) -> None:
        mem = CoordinationMemory(akosha_url="http://akosha:8682/mcp")
        with patch.object(mem._http, "aclose", new=AsyncMock()) as mock_aclose:
            await mem.close()
        mock_aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_without_http(self) -> None:
        mem = CoordinationMemory()
        # Should not raise when no http client
        await mem.close()


# ---------------------------------------------------------------------------
# CoordinationMemory.search_semantic
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCoordinationMemorySearchSemantic:
    @pytest.mark.asyncio
    async def test_search_semantic_no_akosha(self) -> None:
        mem = CoordinationMemory()
        assert await mem.search_semantic("q") == []

    @pytest.mark.asyncio
    async def test_search_semantic_returns_results_key(self) -> None:
        mem = CoordinationMemory(akosha_url="http://akosha:8682/mcp")
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": [{"id": "a"}]}
        mock_response.raise_for_status = MagicMock()

        with patch.object(mem._http, "post", new=AsyncMock(return_value=mock_response)):
            results = await mem.search_semantic("q", limit=3)

        assert results == [{"id": "a"}]

    @pytest.mark.asyncio
    async def test_search_semantic_returns_result_key(self) -> None:
        mem = CoordinationMemory(akosha_url="http://akosha:8682/mcp")
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": [{"id": "b"}]}
        mock_response.raise_for_status = MagicMock()

        with patch.object(mem._http, "post", new=AsyncMock(return_value=mock_response)):
            results = await mem.search_semantic("q", limit=3)

        assert results == [{"id": "b"}]

    @pytest.mark.asyncio
    async def test_search_semantic_empty_results(self) -> None:
        mem = CoordinationMemory(akosha_url="http://akosha:8682/mcp")
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = MagicMock()

        with patch.object(mem._http, "post", new=AsyncMock(return_value=mock_response)):
            assert await mem.search_semantic("q") == []

    @pytest.mark.asyncio
    async def test_search_semantic_non_list_results(self) -> None:
        mem = CoordinationMemory(akosha_url="http://akosha:8682/mcp")
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": "not a list"}
        mock_response.raise_for_status = MagicMock()

        with patch.object(mem._http, "post", new=AsyncMock(return_value=mock_response)):
            assert await mem.search_semantic("q") == []

    @pytest.mark.asyncio
    async def test_search_semantic_http_error_returns_empty(self) -> None:
        mem = CoordinationMemory(akosha_url="http://akosha:8682/mcp")
        with patch.object(
            mem._http, "post", new=AsyncMock(side_effect=httpx.HTTPError("bad"))
        ):
            assert await mem.search_semantic("q") == []

    @pytest.mark.asyncio
    async def test_search_semantic_transport_error_returns_empty(self) -> None:
        mem = CoordinationMemory(akosha_url="http://akosha:8682/mcp")
        with patch.object(
            mem._http, "post", new=AsyncMock(side_effect=httpx.TransportError("net"))
        ):
            assert await mem.search_semantic("q") == []


# ---------------------------------------------------------------------------
# CoordinationManagerWithMemory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCoordinationManagerWithMemoryInit:
    def test_init_creates_inner_manager_and_memory(self) -> None:
        sb = MagicMock()
        mgr = CoordinationManagerWithMemory(
            ecosystem_path="settings/ecosystem.yaml",
            session_buddy_client=sb,
        )
        assert isinstance(mgr._coordination_mgr, CoordinationManager)
        assert mgr._coordination_path == "settings/ecosystem.yaml"
        assert isinstance(mgr.memory, CoordinationMemory)
        assert mgr.memory.session_buddy is sb


@pytest.mark.unit
class TestCoordinationManagerWithMemoryDelegation:
    def _make_manager(self) -> CoordinationManagerWithMemory:
        # Build a real manager with default ecosystem path; tests will
        # patch individual methods to verify delegation.
        return CoordinationManagerWithMemory(
            ecosystem_path="settings/ecosystem.yaml",
            session_buddy_client=MagicMock(),
        )

    def test_reload_delegates(self) -> None:
        mgr = self._make_manager()
        with patch.object(mgr._coordination_mgr, "reload") as mock_reload:
            mgr.reload()
        mock_reload.assert_called_once_with()

    def test_save_delegates(self) -> None:
        mgr = self._make_manager()
        with patch.object(mgr._coordination_mgr, "save") as mock_save:
            mgr.save()
        mock_save.assert_called_once_with()

    def test_list_issues_delegates(self) -> None:
        mgr = self._make_manager()
        with patch.object(
            mgr._coordination_mgr, "list_issues", return_value=["i"]
        ) as mock_method:
            assert mgr.list_issues("a", key="v") == ["i"]
        mock_method.assert_called_once_with("a", key="v")

    def test_get_issue_delegates(self) -> None:
        mgr = self._make_manager()
        with patch.object(
            mgr._coordination_mgr, "get_issue", return_value="got"
        ) as mock_method:
            assert mgr.get_issue("X") == "got"
        mock_method.assert_called_once_with("X")

    def test_create_issue_delegates(self) -> None:
        mgr = self._make_manager()
        with patch.object(
            mgr._coordination_mgr, "create_issue", return_value="created"
        ) as mock_method:
            assert mgr.create_issue("a") == "created"
        mock_method.assert_called_once_with("a")

    def test_update_issue_delegates(self) -> None:
        mgr = self._make_manager()
        with patch.object(
            mgr._coordination_mgr, "update_issue", return_value="updated"
        ) as mock_method:
            assert mgr.update_issue("a", b="c") == "updated"
        mock_method.assert_called_once_with("a", b="c")

    def test_delete_issue_delegates(self) -> None:
        mgr = self._make_manager()
        with patch.object(
            mgr._coordination_mgr, "delete_issue", return_value="deleted"
        ) as mock_method:
            assert mgr.delete_issue("a") == "deleted"
        mock_method.assert_called_once_with("a")

    def test_list_plans_delegates(self) -> None:
        mgr = self._make_manager()
        with patch.object(mgr._coordination_mgr, "list_plans", return_value=[]) as m:
            assert mgr.list_plans() == []
        m.assert_called_once_with()

    def test_get_plan_delegates(self) -> None:
        mgr = self._make_manager()
        with patch.object(mgr._coordination_mgr, "get_plan", return_value="p") as m:
            assert mgr.get_plan("P1") == "p"
        m.assert_called_once_with("P1")

    def test_list_todos_delegates(self) -> None:
        mgr = self._make_manager()
        with patch.object(mgr._coordination_mgr, "list_todos", return_value=[]) as m:
            assert mgr.list_todos() == []
        m.assert_called_once_with()

    def test_get_todo_delegates(self) -> None:
        mgr = self._make_manager()
        with patch.object(mgr._coordination_mgr, "get_todo", return_value="t") as m:
            assert mgr.get_todo("T1") == "t"
        m.assert_called_once_with("T1")

    def test_list_dependencies_delegates(self) -> None:
        mgr = self._make_manager()
        with patch.object(
            mgr._coordination_mgr, "list_dependencies", return_value=[]
        ) as m:
            assert mgr.list_dependencies() == []
        m.assert_called_once_with()

    def test_check_dependencies_delegates(self) -> None:
        mgr = self._make_manager()
        with patch.object(
            mgr._coordination_mgr, "check_dependencies", return_value={}
        ) as m:
            assert mgr.check_dependencies() == {}
        m.assert_called_once_with()

    def test_get_blocking_issues_delegates(self) -> None:
        mgr = self._make_manager()
        with patch.object(
            mgr._coordination_mgr, "get_blocking_issues", return_value=[]
        ) as m:
            assert mgr.get_blocking_issues() == []
        m.assert_called_once_with()

    def test_get_repo_status_delegates(self) -> None:
        mgr = self._make_manager()
        with patch.object(
            mgr._coordination_mgr, "get_repo_status", return_value={"a": 1}
        ) as m:
            assert mgr.get_repo_status() == {"a": 1}
        m.assert_called_once_with()


@pytest.mark.unit
class TestCoordinationManagerWithMemoryIssueMethods:
    @pytest.mark.asyncio
    async def test_create_issue_with_memory(self) -> None:
        mgr = CoordinationManagerWithMemory(
            ecosystem_path="settings/ecosystem.yaml",
            session_buddy_client=MagicMock(),
        )
        issue = _make_issue()

        with patch.object(mgr, "create_issue") as mock_create, patch.object(
            mgr.memory, "store_issue_event", new=AsyncMock()
        ) as mock_store:
            await mgr.create_issue_with_memory(issue)

        mock_create.assert_called_once_with(issue)
        mock_store.assert_awaited_once_with("created", issue)

    @pytest.mark.asyncio
    async def test_update_issue_with_memory(self) -> None:
        mgr = CoordinationManagerWithMemory(
            ecosystem_path="settings/ecosystem.yaml",
            session_buddy_client=MagicMock(),
        )
        issue = _make_issue()

        with patch.object(mgr, "get_issue", return_value=issue) as mock_get, patch.object(
            mgr, "update_issue"
        ) as mock_update, patch.object(
            mgr.memory, "store_issue_event", new=AsyncMock()
        ) as mock_store:
            await mgr.update_issue_with_memory("ISSUE-001", {"status": "closed"})

        # get_issue called twice: once for old, once for new
        assert mock_get.call_count == 2
        mock_update.assert_called_once_with("ISSUE-001", {"status": "closed"})
        mock_store.assert_awaited_once()
        args = mock_store.await_args.args
        kwargs = mock_store.await_args.kwargs
        assert args[0] == "updated"
        assert kwargs["changes"] == {"status": "closed"}
        assert args[1] is issue

    @pytest.mark.asyncio
    async def test_close_issue_with_memory(self) -> None:
        mgr = CoordinationManagerWithMemory(
            ecosystem_path="settings/ecosystem.yaml",
            session_buddy_client=MagicMock(),
        )
        issue = _make_issue()

        with patch.object(mgr, "get_issue", return_value=issue), patch.object(
            mgr, "update_issue"
        ) as mock_update, patch.object(
            mgr.memory, "store_issue_event", new=AsyncMock()
        ) as mock_store:
            await mgr.close_issue_with_memory("ISSUE-001")

        mock_update.assert_called_once_with("ISSUE-001", {"status": "closed"})
        mock_store.assert_awaited_once_with("closed", issue)


@pytest.mark.unit
class TestCoordinationManagerWithMemoryTodoMethods:
    @pytest.mark.asyncio
    async def test_create_todo_with_memory(self) -> None:
        mgr = CoordinationManagerWithMemory(
            ecosystem_path="settings/ecosystem.yaml",
            session_buddy_client=MagicMock(),
        )
        mgr._coordination_mgr._coordination = {"todos": []}
        todo = _make_todo()

        with patch.object(mgr, "save") as mock_save, patch.object(
            mgr.memory, "store_todo_event", new=AsyncMock()
        ) as mock_store:
            await mgr.create_todo_with_memory(todo)

        assert mgr._coordination_mgr._coordination["todos"] == [todo.model_dump(mode="json")]
        mock_save.assert_called_once_with()
        mock_store.assert_awaited_once_with("created", todo)

    @pytest.mark.asyncio
    async def test_complete_todo_with_memory_marks_completed(self) -> None:
        mgr = CoordinationManagerWithMemory(
            ecosystem_path="settings/ecosystem.yaml",
            session_buddy_client=MagicMock(),
        )
        todo = _make_todo()
        mgr._coordination_mgr._coordination = {
            "todos": [todo.model_dump(mode="json")]
        }

        with patch.object(mgr, "save") as mock_save, patch.object(
            mgr.memory, "store_todo_event", new=AsyncMock()
        ) as mock_store:
            await mgr.complete_todo_with_memory("TODO-001")

        saved = mgr._coordination_mgr._coordination["todos"][0]
        assert saved["status"] == "completed"
        assert "updated" in saved
        mock_save.assert_called_once_with()
        mock_store.assert_awaited_once()
        args = mock_store.await_args.args
        assert args[0] == "completed"
        assert args[1].id == "TODO-001"

    @pytest.mark.asyncio
    async def test_complete_todo_with_memory_raises_when_not_found(self) -> None:
        mgr = CoordinationManagerWithMemory(
            ecosystem_path="settings/ecosystem.yaml",
            session_buddy_client=MagicMock(),
        )
        mgr._coordination_mgr._coordination = {"todos": []}

        with pytest.raises(ValueError, match="TODO-999 not found"):
            await mgr.complete_todo_with_memory("TODO-999")


@pytest.mark.unit
class TestCoordinationManagerWithMemoryCheckDependencies:
    @pytest.mark.asyncio
    async def test_check_dependencies_with_memory_stores_events(self) -> None:
        mgr = CoordinationManagerWithMemory(
            ecosystem_path="settings/ecosystem.yaml",
            session_buddy_client=MagicMock(),
        )
        dep_info = {
            "id": "DEP-001",
            "consumer": "fastblocks",
            "provider": "oneiric",
            "type": DependencyType.RUNTIME.value,
            "version_constraint": ">=0.2.0",
            "status": DependencyStatus.SATISFIED.value,
            "validation": {"ok": True},
        }
        check_result = {"dependencies": [dep_info]}

        with patch.object(
            mgr._coordination_mgr,
            "check_dependencies",
            return_value=check_result,
        ), patch.object(
            mgr.memory, "store_dependency_event", new=AsyncMock()
        ) as mock_store:
            result = await mgr.check_dependencies_with_memory()

        assert result == check_result
        mock_store.assert_awaited_once()
        args = mock_store.await_args.args
        kwargs = mock_store.await_args.kwargs
        dep = args[1]
        assert dep.id == "DEP-001"
        assert dep.consumer == "fastblocks"
        assert dep.provider == "oneiric"
        assert dep.type == DependencyType.RUNTIME
        assert dep.status == DependencyStatus.SATISFIED
        assert args[0] == "validated"
        assert kwargs["validation_result"] == {"ok": True}

    @pytest.mark.asyncio
    async def test_check_dependencies_with_memory_no_validation(self) -> None:
        mgr = CoordinationManagerWithMemory(
            ecosystem_path="settings/ecosystem.yaml",
            session_buddy_client=MagicMock(),
        )
        dep_info = {
            "id": "DEP-002",
            "consumer": "x",
            "provider": "y",
            "type": DependencyType.MCP.value,
            "version_constraint": "*",
            "status": DependencyStatus.UNKNOWN.value,
        }
        check_result = {"dependencies": [dep_info]}

        with patch.object(
            mgr._coordination_mgr,
            "check_dependencies",
            return_value=check_result,
        ), patch.object(
            mgr.memory, "store_dependency_event", new=AsyncMock()
        ) as mock_store:
            await mgr.check_dependencies_with_memory(consumer="x")

        kwargs = mock_store.await_args.kwargs
        # validation_result absent in dep_info -> not passed
        assert "validation_result" not in kwargs or kwargs.get("validation_result") is None

    @pytest.mark.asyncio
    async def test_check_dependencies_with_memory_consumer_passed_through(self) -> None:
        mgr = CoordinationManagerWithMemory(
            ecosystem_path="settings/ecosystem.yaml",
            session_buddy_client=MagicMock(),
        )
        check_result = {"dependencies": []}

        with patch.object(
            mgr._coordination_mgr,
            "check_dependencies",
            return_value=check_result,
        ) as mock_check:
            await mgr.check_dependencies_with_memory(consumer="myrepo")

        mock_check.assert_called_once_with(consumer="myrepo")
