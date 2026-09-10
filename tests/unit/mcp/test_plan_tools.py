"""Unit tests for the ``plan_*`` MCP tools (Task 11, REQ-PLAN-010).

Covers registration (all five tools land on the FastMCP server), the
``store_provider`` DI contract, and the per-tool behaviour reached through
the ``require_mcp_auth`` wrapper.

The FastMCP stand-in below mirrors the real ``FastMCP.tool`` signature
closely enough for these tests: ``tool(name=..., **kwargs)`` returns a
decorator. It returns the decorated function unchanged (the real decorator
returns a ``FunctionTool``) so the tests can invoke the wrapped coroutine
directly.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from mahavishnu.mcp.tools.plan_tools import (
    plan_tools_default_store_provider,
    register_plan_tools,
)
from mahavishnu.plan_index.errors import PlanNotFoundError
from mahavishnu.plan_index.record import PlanRecord
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.testing import FakeDhara

TOOL_NAMES = (
    "plan_list",
    "plan_show",
    "plan_search",
    "plan_vitals",
    "plan_rebuild_status",
)


class FakeMCP:
    """Minimal FastMCP stand-in that captures decorated tool functions."""

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, name: str | None = None, **kwargs: Any) -> Any:
        def decorator(fn: Any) -> Any:
            self.tools[name or fn.__name__] = fn
            return fn

        return decorator


def _sample_record(plan_id: str = "1" * 32) -> PlanRecord:
    return PlanRecord(
        plan_id=plan_id,
        path="docs/plans/x.md",
        title="X",
        status="active",
        role="implementation",
        topic="routing",
        date="2026-09-15",
        last_reviewed="2026-09-15",
        superseded_by=None,
        blocks_on=[],
        sha="f" * 40,
        repo="github.com/example/repo",
        updated_at_ms=1700000000000,
    )


@pytest.fixture
def store() -> PlanIndexStore:
    """A single FakeDhara-backed store shared across one test."""
    return PlanIndexStore(FakeDhara())


@pytest.fixture
def tools(store: PlanIndexStore) -> dict[str, Any]:
    """Register the five tools against a shared store and return them by name."""
    mcp = FakeMCP()

    def provider() -> PlanIndexStore:
        return store

    register_plan_tools(mcp, store_provider=provider)
    return mcp.tools


class TestRegisterPlanTools:
    def test_register_returns_none(self) -> None:
        """Registration with the default dev provider must not raise."""
        mcp = FakeMCP()
        result = register_plan_tools(mcp, store_provider=plan_tools_default_store_provider)
        assert result is None

    def test_decorators_callable(self) -> None:
        """All five tools are registered under their spec names."""
        mcp = FakeMCP()
        register_plan_tools(mcp, store_provider=plan_tools_default_store_provider)

        assert len(mcp.tools) == 5
        for name in TOOL_NAMES:
            assert name in mcp.tools
            assert inspect.iscoroutinefunction(mcp.tools[name])

    def test_store_provider_is_keyword_only_and_required(self) -> None:
        """``store_provider`` has no default and cannot be passed positionally."""
        sig = inspect.signature(register_plan_tools)
        param = sig.parameters["store_provider"]

        assert param.kind is inspect.Parameter.KEYWORD_ONLY
        assert param.default is inspect.Parameter.empty

    def test_missing_store_provider_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            register_plan_tools(FakeMCP())  # type: ignore[call-arg]

    def test_default_store_provider_returns_fresh_store(self) -> None:
        first = plan_tools_default_store_provider()
        second = plan_tools_default_store_provider()

        assert isinstance(first, PlanIndexStore)
        assert isinstance(second, PlanIndexStore)
        assert first is not second


class TestPlanListTool:
    async def test_returns_result_envelope(
        self, tools: dict[str, Any], store: PlanIndexStore
    ) -> None:
        await store.upsert(_sample_record())

        result = await tools["plan_list"](user_id="alice")

        assert result["status"] == "ok"
        assert result["total"] == len(result["plans"])
        assert result["total"] == 1
        assert result["plans"][0]["plan_id"] == "1" * 32

    async def test_status_filter_routes_to_list_by_status(
        self, tools: dict[str, Any], store: PlanIndexStore
    ) -> None:
        await store.upsert(_sample_record())

        result = await tools["plan_list"](status="active", user_id="alice")

        assert result["total"] == 1
        assert result["plans"][0]["status"] == "active"

    async def test_topic_filter_routes_to_list_by_topic(
        self, tools: dict[str, Any], store: PlanIndexStore
    ) -> None:
        await store.upsert(_sample_record())

        matched = await tools["plan_list"](topic="routing", user_id="alice")
        unmatched = await tools["plan_list"](topic="unrelated", user_id="alice")

        assert matched["total"] == 1
        assert unmatched["total"] == 0

    async def test_date_range_filter(self, tools: dict[str, Any], store: PlanIndexStore) -> None:
        await store.upsert(_sample_record())

        inside = await tools["plan_list"](
            date_from="2026-09-01", date_to="2026-09-30", user_id="alice"
        )
        outside = await tools["plan_list"](
            date_from="2026-01-01", date_to="2026-01-31", user_id="alice"
        )

        assert inside["total"] == 1
        assert outside["total"] == 0

    async def test_empty_store_returns_zero_total(self, tools: dict[str, Any]) -> None:
        result = await tools["plan_list"](user_id="alice")

        assert result == {"plans": [], "total": 0, "status": "ok"}


class TestPlanShowTool:
    async def test_round_trip_upsert_then_show(
        self, tools: dict[str, Any], store: PlanIndexStore
    ) -> None:
        await store.upsert(_sample_record())

        result = await tools["plan_show"](plan_id="1" * 32, user_id="alice")

        assert result["plan_id"] == "1" * 32
        assert result["path"] == "docs/plans/x.md"
        assert result["status"] == "active"

    async def test_missing_plan_raises_plan_not_found(self, tools: dict[str, Any]) -> None:
        with pytest.raises(PlanNotFoundError) as excinfo:
            await tools["plan_show"](plan_id="0" * 32, user_id="alice")

        assert excinfo.value.plan_id == "0" * 32


class TestPlanSearchTool:
    async def test_matches_on_title(self, tools: dict[str, Any], store: PlanIndexStore) -> None:
        await store.upsert(_sample_record())

        result = await tools["plan_search"](query="routing", user_id="alice")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["plan_id"] == "1" * 32

    async def test_empty_query_returns_empty_list(
        self, tools: dict[str, Any], store: PlanIndexStore
    ) -> None:
        await store.upsert(_sample_record())

        assert await tools["plan_search"](query="", user_id="alice") == []

    async def test_no_match_returns_empty_list(
        self, tools: dict[str, Any], store: PlanIndexStore
    ) -> None:
        await store.upsert(_sample_record())

        assert await tools["plan_search"](query="zzzz-nomatch", user_id="alice") == []


class TestPlanVitalsTool:
    async def test_returns_vitals_shape(self, tools: dict[str, Any], store: PlanIndexStore) -> None:
        await store.upsert(_sample_record())

        result = await tools["plan_vitals"](user_id="alice")

        for key in (
            "total",
            "by_status",
            "by_role",
            "by_topic_top10",
            "cycles_total",
            "successful_cycles_total",
            "errors_total",
            "recent_errors",
            "tripwire",
        ):
            assert key in result
        assert result["total"] == 1
        assert result["by_status"] == {"active": 1}


class TestPlanRebuildStatusTool:
    async def test_returns_rebuild_status_shape(self, tools: dict[str, Any]) -> None:
        result = await tools["plan_rebuild_status"](user_id="alice")

        assert result["cycles_total"] == 0
        assert result["successful_cycles_total"] == 0
        assert result["errors_total"] == 0
        assert result["recent_errors"] == []
        assert result["stale"] is True
        assert result.get("last_rebuild_ms") is None


class TestAuthEnvelope:
    """``require_mcp_auth`` short-circuits every tool when ``user_id`` is absent."""

    @pytest.mark.parametrize("tool_name", TOOL_NAMES)
    async def test_missing_user_id_returns_auth_required(
        self, tools: dict[str, Any], tool_name: str
    ) -> None:
        kwargs: dict[str, Any] = {}
        if tool_name == "plan_show":
            kwargs["plan_id"] = "1" * 32
        elif tool_name == "plan_search":
            kwargs["query"] = "routing"

        result = await tools[tool_name](**kwargs)

        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_REQUIRED"

    @pytest.mark.parametrize("tool_name", TOOL_NAMES)
    async def test_tools_accept_user_id_kwarg(self, tools: dict[str, Any], tool_name: str) -> None:
        """Each tool must declare ``user_id`` so the auth decorator can forward it."""
        fn = tools[tool_name]
        sig = inspect.signature(inspect.unwrap(fn))

        assert "user_id" in sig.parameters
