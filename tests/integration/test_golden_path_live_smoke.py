"""Opt-in live smoke test for the deterministic C5 golden-path flow."""

from __future__ import annotations

import os
from types import SimpleNamespace

import httpx
import pytest

from mahavishnu.core.coordination.memory import CoordinationMemory
from mahavishnu.core.state_backends.dhara import DharaStateBackend, DharaStateConfig
from mahavishnu.session.checkpoint import SessionBuddy
from tests.fixtures.golden_path_fixture import golden_path_incident_fixture

SKIP_REASON = (
    "set MAHAVISHNU_C5_LIVE_SMOKE=1 and the live service URLs to run the C5 smoke test"
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("MAHAVISHNU_C5_LIVE_SMOKE") != "1"
        or not os.getenv("MAHAVISHNU_SESSION_BUDDY_URL")
        or not os.getenv("MAHAVISHNU_DHARA_STATE_URL")
        or not os.getenv("MAHAVISHNU_AKOSHA_URL"),
        reason=SKIP_REASON,
    ),
]


class LiveMcpToolClient:
    """Minimal MCP tool client for live smoke validation."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def call_tool(self, name: str, arguments: dict[str, object]) -> object:
        response = await self._client.post(
            f"{self._base_url}/tools/call",
            json={"name": name, "arguments": arguments},
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and "result" in payload:
            return payload["result"]
        return payload

    async def store_memory(
        self,
        collection: str,
        content: str,
        metadata: dict[str, object],
    ) -> object:
        return await self.call_tool(
            "store_memory",
            {
                "collection": collection,
                "content": content,
                "metadata": metadata,
            },
        )

    async def search(self, query: str, filters: dict[str, object], limit: int) -> object:
        return await self.call_tool(
            "search_all_systems",
            {
                "query": query,
                "limit": limit,
                "filters": filters,
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()


def _mock_config(session_buddy_url: str) -> SimpleNamespace:
    return SimpleNamespace(
        session=SimpleNamespace(enabled=True, checkpoint_interval=60),
        pools=SimpleNamespace(session_buddy_url=session_buddy_url),
    )


@pytest.mark.asyncio
async def test_live_golden_path_smoke_round_trip() -> None:
    fixture = golden_path_incident_fixture()
    session_buddy_url = os.environ["MAHAVISHNU_SESSION_BUDDY_URL"]
    dhara_state_url = os.environ["MAHAVISHNU_DHARA_STATE_URL"]
    akosha_url = os.environ["MAHAVISHNU_AKOSHA_URL"]

    session_buddy = SessionBuddy(_mock_config(session_buddy_url))
    dhara = DharaStateBackend(
        base_url=dhara_state_url,
        config=DharaStateConfig(enabled=True),
    )
    akosha = LiveMcpToolClient(akosha_url)
    coordination_memory = CoordinationMemory(
        session_buddy_client=akosha,
        akosha_url=None,
    )

    try:
        checkpoint_id = await session_buddy.create_checkpoint(
            fixture.workflow_id,
            {"correlation_id": fixture.correlation_id, "issue_id": fixture.issue_id},
        )
        assert checkpoint_id

        await coordination_memory.store_issue_event(
            "created",
            SimpleNamespace(
                id=fixture.issue_id,
                title=fixture.summary,
                status=SimpleNamespace(value="open"),
                priority=SimpleNamespace(value="high"),
                repos=[fixture.repo],
                assignee="operator",
            ),
        )

        await akosha.store_memory(
            "mahavishnu_coordination",
            f"Golden path incident {fixture.correlation_id}",
            {
                "incident_id": fixture.incident_id,
                "correlation_id": fixture.correlation_id,
                "workflow_id": fixture.workflow_id,
            },
        )

        await dhara.persist_workflow(
            fixture.workflow_id,
            {
                "incident_id": fixture.incident_id,
                "correlation_id": fixture.correlation_id,
                "checkpoint_id": checkpoint_id,
                "status": "running",
            },
        )
        await dhara.persist_pool(
            "pool-golden-path",
            {"workflow_id": fixture.workflow_id, "status": "ready"},
        )
        await dhara.persist_routing_decision(
            "workflow",
            {"workflow_id": fixture.workflow_id, "pool_id": "pool-golden-path"},
        )
        await dhara.persist_approval(
            "approval-001",
            {"workflow_id": fixture.workflow_id, "approved": True},
        )

        search_results = await akosha.search(
            fixture.correlation_id,
            {"entity_type": "issue"},
            5,
        )
        recovered_workflows = await dhara.recover_workflows()
        recovered_approvals = await dhara.recover_approvals()

        assert recovered_workflows
        assert recovered_workflows[0]["correlation_id"] == fixture.correlation_id
        assert recovered_approvals
        assert recovered_approvals[0]["workflow_id"] == fixture.workflow_id
        assert isinstance(search_results, list)
        assert any(
            fixture.correlation_id in str(item) or fixture.issue_id in str(item)
            for item in search_results
        )
    finally:
        await akosha.aclose()
        await dhara.aclose()
