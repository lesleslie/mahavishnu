"""End-to-end test for ``mahavishnu_get_agent`` MCP tool (Phase 3).

Per plan §5 Phase 3 exit criteria: ``mahavishnu_get_agent(name)``
round-trips and ``content_hash`` matches body bytes. Verifies the
signed metadata + body response shape from B-6 / plan §5 Phase 3
task #2.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

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
    from mahavishnu.mcp.signer_feed import init_signer_feed_state

    server = await build_mahavishnu_mcp_server()
    init_signer_feed_state()
    yield server


@pytest.mark.asyncio
async def test_get_agent_returns_signed_metadata_and_body(_server) -> None:
    """``mahavishnu_get_agent`` returns ``{success, metadata, body}`` with signature populated."""
    result = await _server.server.call_tool(
        "mahavishnu_get_agent", {"name": "mahavishnu-specialist"}
    )

    assert result is not None
    assert hasattr(result, "content")
    payload = json.loads(result.content[0].text)
    assert payload["success"] is True
    assert "metadata" in payload
    assert "body" in payload

    metadata = payload["metadata"]
    assert metadata["signature"] is not None
    assert metadata["server_pubkey_id"] is not None
    assert metadata["name"] == "mahavishnu-specialist"
    assert metadata["server_key"] == "mahavishnu"


@pytest.mark.asyncio
async def test_get_agent_content_hash_matches_body_bytes(_server) -> None:
    """``metadata.content_hash`` matches sha256(body) (per plan §5 Phase 3 exit criteria)."""
    for name in ("mahavishnu-specialist", "pool-router-agent", "workflow-monitor"):
        result = await _server.server.call_tool(
            "mahavishnu_get_agent", {"name": name}
        )
        payload = json.loads(result.content[0].text)
        assert payload["success"] is True, (
            f"get_agent({name!r}) returned {payload}"
        )

        metadata = payload["metadata"]
        body = payload["body"]

        # B-1 / plan §11 B-1: the client asserts the content_hash matches
        # the body bytes BEFORE writing to ~/.claude/agents/<name>.md.
        expected_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        assert metadata["content_hash"] == expected_hash, (
            f"{name!r}: content_hash {metadata['content_hash']!r} "
            f"!= sha256(body) {expected_hash!r}"
        )


@pytest.mark.asyncio
async def test_get_agent_body_matches_system_prompt(_server) -> None:
    """Per B-6: ``body == metadata.system_prompt`` (per plan §5 Phase 3 task #2).

    The installer can write either field directly; the dual surface is
    intentional so a client that already cached ``system_prompt`` from
    ``list_agents`` can skip a second body read.
    """
    result = await _server.server.call_tool(
        "mahavishnu_get_agent", {"name": "pool-router-agent"}
    )
    payload = json.loads(result.content[0].text)

    assert payload["success"] is True
    assert payload["body"] == payload["metadata"]["system_prompt"]


@pytest.mark.asyncio
async def test_get_agent_unknown_name_returns_error_envelope(_server) -> None:
    """An unknown agent name returns a uniform error envelope (B-4 / H-6)."""
    result = await _server.server.call_tool(
        "mahavishnu_get_agent", {"name": "nonexistent-agent"}
    )
    payload = json.loads(result.content[0].text)

    assert payload["success"] is False
    assert "error" in payload
    assert "not found" in payload["error"].lower()


@pytest.mark.asyncio
async def test_get_agent_path_traversal_blocked(_server) -> None:
    """B-4: a path-traversal ``name`` returns an error envelope rather than raising."""
    for bad_name in ("../../etc/passwd", "foo/bar", ".hidden", "FOO"):
        result = await _server.server.call_tool(
            "mahavishnu_get_agent", {"name": bad_name}
        )
        payload = json.loads(result.content[0].text)
        assert payload["success"] is False, (
            f"path-traversal name {bad_name!r} should have been rejected"
        )
        assert "allowlist" in payload["error"].lower()
