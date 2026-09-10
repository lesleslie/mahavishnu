"""Per-tool e2e: ``mcp__mahavishnu__plan_search``.

REQ-PLAN-007 (§4 gate): non-empty result returns a ``list[dict]`` with
matched records; empty query short-circuits to ``[]`` (not an error);
user_id is forwarded by default.
"""

from __future__ import annotations

from typing import Any

from mahavishnu.plan_index.record import PlanRecord


def _record(plan_id: str, title: str, topic: str) -> PlanRecord:
    return PlanRecord(
        plan_id=plan_id,
        path=f"docs/plans/{plan_id[:6]}.md",
        title=title,
        status="active",
        role="implementation",
        topic=topic,
        date="2026-09-15",
        last_reviewed="2026-09-15",
        superseded_by=None,
        blocks_on=[],
        sha="f" * 40,
        repo="github.com/example/repo",
        updated_at_ms=1700000000000,
    )


class TestPlanSearchE2E:
    async def test_search_returns_list_of_matched_records(
        self, call_tool: Any, store: Any
    ) -> None:
        """A query that matches two records returns a list of two dicts."""
        await store.upsert(_record("a" * 32, "Routing Plan", "routing"))
        await store.upsert(_record("b" * 32, "Other Routing", "routing"))
        await store.upsert(_record("c" * 32, "Indexing", "indexing"))

        result = await call_tool("plan_search", {"query": "routing"})

        assert isinstance(result, list)
        assert len(result) == 2
        # Topic-or-title matches both records; the indexing record must not appear.
        assert all(rec["topic"] == "routing" for rec in result)

    async def test_search_matches_on_topic_not_only_title(
        self, call_tool: Any, store: Any
    ) -> None:
        """``store.search`` matches both title and topic (lexical)."""
        await store.upsert(_record("d" * 32, "generic", "observability"))

        # Match by topic
        matched = await call_tool("plan_search", {"query": "observability"})

        assert len(matched) == 1
        assert matched[0]["topic"] == "observability"

    async def test_search_empty_query_returns_empty_list_not_error(
        self, call_tool: Any, store: Any
    ) -> None:
        """Empty-string query short-circuits to ``[]`` rather than hitting the store."""
        await store.upsert(_record("e" * 32, "Present", "routing"))

        result = await call_tool("plan_search", {"query": ""})

        assert result == []

    async def test_search_no_match_returns_empty_list(
        self, call_tool: Any, store: Any
    ) -> None:
        """A query with no matches returns ``[]`` (not an error envelope)."""
        await store.upsert(_record("f" * 32, "Bogus", "routing"))

        result = await call_tool("plan_search", {"query": "zzz-no-match"})

        assert isinstance(result, list)
        assert result == []

    async def test_search_without_user_id_returns_auth_required_envelope(
        self, call_tool: Any
    ) -> None:
        """REQ-PLAN-010: missing ``user_id`` returns envelope, not raise."""
        result = await call_tool(
            "plan_search", {"query": "routing"}, user_id=None
        )

        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_REQUIRED"
