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

    assert len({sid_a, sid_b, sid_c}) == 3, "Session IDs must be distinct"

    # Capture output from each — must NOT be cross-talked
    out_a, out_b, out_c = await asyncio.gather(
        adapter.capture_output(sid_a),
        adapter.capture_output(sid_b),
        adapter.capture_output(sid_c),
    )

    assert "out:" + sid_a in out_a
    assert "out:" + sid_b in out_b
    assert "out:" + sid_c in out_c


@pytest.mark.integration
async def test_canonical_session_id_path() -> None:
    """When the server returns a canonical session_id, the adapter follows it.

    Pre-T3-M1: the integration test only exercised the *fallback* branch
    of \`_canonical_session_id\` (the stub returned no \`session_id\` field).
    This test uses a stub that returns the canonical shape so the production
    code path (\`return sid or fallback\`) is covered.
    """

    canonical_sids = ["canon-A", "canon-B", "canon-C"]
    call_index = {"n": 0}
    captured_calls: list[tuple[str, dict]] = []

    class CanonicalStubMCPClient:
        """Stub that returns a canonical session_id from the open call."""

        async def call_tool(self, name: str, arguments: dict) -> dict:
            captured_calls.append((name, arguments))
            if name == "crow_terminal_open":
                # Round-robin canonical IDs to match the three concurrent
                # launches below; each one is distinct.
                sid = canonical_sids[call_index["n"] % len(canonical_sids)]
                call_index["n"] += 1
                return {"session_id": sid, "terminal_id": sid, "output": ""}
            return {"output": f"out:{arguments.get('session_id', 'anon')}"}

    adapter = CrowTerminalAdapter(mcp_client=CanonicalStubMCPClient())

    sid_a, sid_b, sid_c = await asyncio.gather(
        adapter.launch_session("qwen"),
        adapter.launch_session("claude"),
        adapter.launch_session("gemini"),
    )

    # Each adapter-returned ID must equal the canonical one the stub gave
    # us, NOT the random UUID4 the adapter generated for the open call.
    assert {sid_a, sid_b, sid_c} == set(canonical_sids), (
        f"Adapter should honor server-returned session_id; got {sid_a!r}, "
        f"{sid_b!r}, {sid_c!r} but stub returned {canonical_sids!r}."
    )

    # All captured session_ids in subsequent calls must be the canonical
    # ones — none should leak the adapter-generated UUIDs.
    subsequent_session_ids = {
        args.get("session_id")
        for name, args in captured_calls
        if name in {"crow_terminal_exec", "crow_terminal_read", "crow_terminal_close"}
        and args.get("session_id") is not None
    }
    assert subsequent_session_ids <= set(canonical_sids), (
        f"Subsequent calls leaked adapter-generated IDs: {subsequent_session_ids - set(canonical_sids)!r}"
    )
