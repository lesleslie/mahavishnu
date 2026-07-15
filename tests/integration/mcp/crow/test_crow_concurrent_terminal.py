"""Three concurrent pool workers must get isolated PTYs.

This is the regression test that fails on the pre-Task-3 implementation
(where every caller shares one PTY). It must pass once Task 3 lands.
"""

from __future__ import annotations

import asyncio

import pytest

from mahavishnu.terminal.adapters.crow import CrowTerminalAdapter


@pytest.mark.integration
async def test_three_concurrent_workers_get_isolated_sessions() -> None:
    """Three concurrent launch_session calls return distinct session_ids
    and produce output that is NOT cross-talked between workers."""

    # Stub MCP client that records every call and returns deterministic
    # output for each session_id we hand it.
    captured_calls: list[tuple[str, dict]] = []

    class StubMCPClient:
        async def call_tool(self, name: str, arguments: dict) -> dict:
            captured_calls.append((name, arguments))
            session_id = arguments.get("session_id") or arguments.get("handle")
            return {
                "terminal_id": session_id or "anon",
                "output": f"out:{session_id}",
            }

    adapter = CrowTerminalAdapter(mcp_client=StubMCPClient())

    # Launch three concurrent sessions
    sid_a, sid_b, sid_c = await asyncio.gather(
        adapter.launch_session("qwen"),
        adapter.launch_session("claude"),
        adapter.launch_session("gemini"),
    )

    assert sid_a != sid_b != sid_c, "Session IDs must be distinct"

    # Capture output from each — must NOT be cross-talked
    out_a, out_b, out_c = await asyncio.gather(
        adapter.capture_output(sid_a),
        adapter.capture_output(sid_b),
        adapter.capture_output(sid_c),
    )

    assert "out:" + sid_a in out_a
    assert "out:" + sid_b in out_b
    assert "out:" + sid_c in out_c
