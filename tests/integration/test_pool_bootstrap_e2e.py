"""End-to-end integration test for the pool bootstrap flow.

Verifies the wiring contract from docs/plans/2026-10-09-pool-bootstrap-mcp-tool.md
Commit 2: simulate the SessionStart hook calling mcp__mahavishnu__pool_bootstrap
via JSON-RPC 2.0, confirm the registry goes from 0 pools to 1 pool.
"""
from __future__ import annotations

import os
import time
import uuid

import httpx
import pytest

pytestmark = pytest.mark.integration

# FastMCP's streamable-HTTP transport lives at /mcp (not /tools/<name>).
# See fastmcp/settings.py:201 and mahavishnu/mcp/crow/raw_jsonrpc.py:234.
MCP_PATH = "/mcp"


def _mcp_url() -> str:
    return os.environ.get("MAHAVISHNU_MCP_URL", "http://localhost:8680")


def _is_mcp_reachable() -> bool:
    """Skip the test if the MCP server isn't running locally."""
    try:
        with httpx.Client(timeout=1.0) as client:
            response = client.get(f"{_mcp_url()}/health")
            return response.status_code in (200, 503)
    except Exception:
        return False


def _jsonrpc(method: str, params: dict[str, object]) -> dict[str, object]:
    """Build a JSON-RPC 2.0 request body."""
    return {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params}


def _call_tool(client: httpx.Client, name: str, arguments: dict[str, object] | None = None) -> dict[str, object]:
    """Invoke a tool via FastMCP's JSON-RPC 2.0 tools/call endpoint.

    Returns the unwrapped result dict. Raises on JSON-RPC error.
    """
    envelope = _jsonrpc("tools/call", {"name": name, "arguments": arguments or {}})
    response = client.post(
        f"{_mcp_url()}{MCP_PATH}",
        json=envelope,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        timeout=5.0,
    )
    response.raise_for_status()
    body = response.json()
    if "error" in body:
        raise RuntimeError(f"JSON-RPC error: {body['error']}")
    result = body.get("result", {})
    if isinstance(result, dict) and "structuredContent" in result:
        return result["structuredContent"]  # type: ignore[return-value]
    if isinstance(result, dict) and "content" in result and result["content"]:
        first = result["content"][0]
        if isinstance(first, dict) and "text" in first:
            import json as _json
            return _json.loads(first["text"])  # type: ignore[return-value]
    if isinstance(result, dict):
        return result
    raise RuntimeError(f"unexpected JSON-RPC result shape: {result!r}")


@pytest.mark.skipif(
    not _is_mcp_reachable(),
    reason="MCP server not reachable; start it with `mahavishnu mcp start`",
)
def test_pool_bootstrap_e2e_empty_registry_spawns() -> None:
    """SessionStart with empty registry → pool_bootstrap spawns a default pool."""
    with httpx.Client(timeout=5.0) as client:
        # 1. Close any existing pools to get a clean state (best-effort)
        try:
            _call_tool(client, "pool_close_all")
            time.sleep(0.5)
        except Exception:
            pass  # OK if pool_close_all doesn't exist or registry is already empty

        # 2. Verify empty
        health = _call_tool(client, "pool_health")
        assert health.get("pools_active", -1) == 0, f"setup failed: registry not empty: {health}"

        # 3. Bootstrap
        result = _call_tool(client, "pool_bootstrap")
        assert result["status"] in ("spawned", "warning"), f"unexpected status: {result}"

        # 4. Confirm the pool is now in the registry
        health_after = _call_tool(client, "pool_health")
        assert health_after.get("pools_active", 0) >= 1, (
            f"bootstrap did not add a pool: {health_after}"
        )


@pytest.mark.skipif(
    not _is_mcp_reachable(),
    reason="MCP server not reachable",
)
def test_pool_bootstrap_e2e_populated_registry_is_no_op() -> None:
    """SessionStart with non-empty registry → pool_bootstrap returns status='skipped'."""
    with httpx.Client(timeout=5.0) as client:
        result = _call_tool(client, "pool_bootstrap")
        assert result["status"] == "skipped", f"expected skipped, got: {result}"
        assert result["pools_active_before"] >= 1
