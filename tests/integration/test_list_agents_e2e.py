"""End-to-end test for ``mahavishnu_list_agents`` MCP tool (Phase 3).

Per plan §5 Phase 3 exit criteria: ``mahavishnu_list_agents()`` returns
≥3 entries with non-empty ``system_prompt`` field. Verifies the wire
shape and the body content of every advertised agent.

The test uses the in-process FastMCP server (no HTTP) so it runs
without launching the daemon.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Pin signer key path so tests don't touch the user's real key.
_TEST_KEY_DIR = tempfile.mkdtemp(prefix="mahavishnu-test-signer-")
os.environ["MAHAVISHNU_SKILLS_SIGNER_KEY_PATH"] = str(
    Path(_TEST_KEY_DIR) / "private_key.pem"
)


@pytest.fixture(autouse=True)
async def _server():
    """Build a fresh server per test with the FULL profile."""
    from mahavishnu.mcp.server import build_mahavishnu_mcp_server

    server = await build_mahavishnu_mcp_server()
    # Init signer feed state so get_agent can produce signatures
    # (list_agents does not require it, but tests run in random order).
    from mahavishnu.mcp.signer_feed import init_signer_feed_state

    init_signer_feed_state()
    yield server


@pytest.mark.asyncio
async def test_list_agents_returns_at_least_three_entries(_server) -> None:
    """``mahavishnu_list_agents`` returns ≥3 entries (per plan §5 Phase 3 exit criteria)."""
    result = await _server.server.call_tool("mahavishnu_list_agents", {})

    assert result is not None
    assert hasattr(result, "content")
    payload = result.content[0].text
    # ``payload`` is a JSON-encoded list of dicts.
    import json

    agents = json.loads(payload)
    assert isinstance(agents, list)
    assert len(agents) >= 3, f"expected ≥3 agents, got {len(agents)}"


@pytest.mark.asyncio
async def test_list_agents_each_entry_has_non_empty_system_prompt(_server) -> None:
    """Every entry must carry a non-empty ``system_prompt`` (per B-6 / plan §5 Phase 3 task #2)."""
    import json

    result = await _server.server.call_tool("mahavishnu_list_agents", {})
    payload = result.content[0].text
    agents = json.loads(payload)

    for entry in agents:
        assert "system_prompt" in entry, (
            f"agent {entry.get('name')!r} missing 'system_prompt' field"
        )
        assert entry["system_prompt"], (
            f"agent {entry.get('name')!r} has empty 'system_prompt'"
        )
        assert isinstance(entry["system_prompt"], str)


@pytest.mark.asyncio
async def test_list_agents_advertises_three_named_specialists(_server) -> None:
    """The 3 starter agents from the catalog are advertised by name."""
    import json

    result = await _server.server.call_tool("mahavishnu_list_agents", {})
    payload = result.content[0].text
    agents = json.loads(payload)
    names = {a["name"] for a in agents}

    expected = {"mahavishnu-specialist", "pool-router-agent", "workflow-monitor"}
    assert expected.issubset(names), (
        f"missing expected agents: {expected - names}"
    )


@pytest.mark.asyncio
async def test_list_agents_metadata_shape_matches_schema(_server) -> None:
    """Every entry validates against the AgentMetadata schema (server_key, id, model, tools)."""
    from mahavishnu.mcp.agent_schema import AgentMetadata

    import json

    result = await _server.server.call_tool("mahavishnu_list_agents", {})
    payload = result.content[0].text
    agents = json.loads(payload)

    for entry in agents:
        # Pydantic v2 — re-parse the wire dict to enforce the schema.
        m = AgentMetadata(**entry)
        assert m.server_key == "mahavishnu"
        assert m.id.startswith("mahavishnu:")
        assert m.model  # non-empty
        assert isinstance(m.tools, list)


@pytest.mark.asyncio
async def test_list_agents_body_size_at_least_200_chars(_server) -> None:
    """Every ``system_prompt`` body is at least 200 chars of real content (per brief)."""
    import json

    result = await _server.server.call_tool("mahavishnu_list_agents", {})
    payload = result.content[0].text
    agents = json.loads(payload)

    for entry in agents:
        body = entry["system_prompt"]
        assert len(body) >= 200, (
            f"agent {entry['name']!r} body has {len(body)} chars; "
            "expected ≥200 per brief"
        )
