#!/usr/bin/env python3
"""SessionStart hook: ensure a default pool exists via mcp__mahavishnu__pool_bootstrap.

Mirrors the pattern of .claude/hooks/jot-session-start.py — the script
does the actual work (JSON-RPC 2.0 call to the FastMCP server's /mcp
endpoint), then calls handle() for the bridge audit trail. Returns 0
on every path so SessionStart never blocks the harness.

Per design (docs/plans/2026-10-09-pool-bootstrap-mcp-tool.md Commit 2):
the work lives in the standalone script because bridge handlers run
in subprocess context without PoolManager access. Future work may
move the body into the bridge handler once the bridge has direct
MCP access.
"""
from __future__ import annotations

import json
import os
import sys

CLAUDE_PROJECT_DIR = os.environ.get("CLAUDE_PROJECT_DIR")
if CLAUDE_PROJECT_DIR:
    sys.path.insert(0, CLAUDE_PROJECT_DIR)

import httpx

# Wire-protocol helpers (initialize handshake, SSE parsing, tools/call)
# live in a sibling module. See _bodai_mcp_client.py for the session
# handshake rationale — without it, FastMCP's streamable-HTTP transport
# returns HTTP 400 "Missing session ID" on every tools/call.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _bodai_mcp_client import call_tool, init_session  # noqa: E402

from mahavishnu.bodai_hook_bridge import handle

EVENT_NAME = "SessionStart"
DEFAULT_MCP_URL = "http://localhost:8680/mcp"
# 1.0s fail-fast: SessionStart is on the critical path. If the MCP server
# is slow on lifespan init, the existing mcp-pre-checkpoint-sync.sh
# scripts in ~/.claude/scripts/ pre-warm the server — the bootstrap
# itself should never wait.
REQUEST_TIMEOUT_SECONDS = 1.0


def _safe_parse_payload() -> dict[str, object]:
    """Parse stdin JSON; return empty dict on any parse failure."""
    try:
        raw = sys.stdin.read()
    except Exception:  # hook handler — broad catch is the documented contract  # hook handler — broad catch is the documented contract  # noqa: BLE001, RUF100
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _invoke_bootstrap() -> dict[str, object] | None:
    """Call mcp__mahavishnu__pool_bootstrap via JSON-RPC 2.0 over FastMCP.

    Returns the parsed result dict on success, or None on any failure.
    Uses the shared wire helpers in ``_bodai_mcp_client.py``: the
    two-step shape is REQUIRED for FastMCP's streamable-HTTP transport
    (``initialize`` → capture ``mcp-session-id`` → ``tools/call`` with
    the header echoed). Skipping the handshake returns HTTP 400.
    """
    mcp_url = os.environ.get("MAHAVISHNU_MCP_URL", DEFAULT_MCP_URL)
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            session_id = init_session(client, mcp_url)
            if session_id is None:
                return None
            result = call_tool(client, mcp_url, "pool_bootstrap", session_id, {})
    except Exception as exc:  # hook handler — broad catch is the documented contract  # noqa: BLE001
        sys.stderr.write(f"Hook output: pool_bootstrap call failed: {exc}\n")
        sys.stderr.flush()
        return None
    if not isinstance(result, dict):
        return None
    return result


def _format_result(result: dict[str, object]) -> str:
    """Render the bootstrap result as a short additionalContext line."""
    status = result.get("status", "unknown")
    if status == "skipped":
        pools_active = result.get("pools_active_after", "?")
        return f"Mahavishnu pool registry already populated ({pools_active} pool(s))."
    if status == "spawned":
        pool_id = result.get("pool_id", "?")
        return f"Mahavishnu pool bootstrap: spawned default pool (id={pool_id})."
    if status == "warning":
        pool_id = result.get("pool_id", "?")
        warning = result.get("warning", "")
        return f"Mahavishnu pool bootstrap: spawned (id={pool_id}). Note: {warning}"
    if status == "failed":
        error = result.get("error", "unknown error")
        return f"Mahavishnu pool bootstrap FAILED: {error}. Local work can proceed via degraded mode."
    return f"Mahavishnu pool bootstrap: unexpected status={status!r}."


def main() -> int:
    """SessionStart entry point.

    Returns 0 on every path. Calls handle() for bridge audit after
    the work; the handle() result is intentionally ignored per the
    existing pattern in jot-session-start.py (the work result is
    authoritative, bridge telemetry is observation-only).
    """
    payload = _safe_parse_payload()
    result = _invoke_bootstrap()

    additional_context = _format_result(result) if result is not None else (
        "Mahavishnu pool bootstrap: MCP unreachable, session proceeds in degraded mode."
    )
    output = {
        "hookSpecificOutput": {
            "hookEventName": EVENT_NAME,
            "additionalContext": additional_context,
        }
    }
    try:
        print(json.dumps(output))
    except Exception as exc:  # hook handler — broad catch is the documented contract  # noqa: BLE001, RUF100
        sys.stderr.write(f"Hook output: json.dumps failed: {exc}\n")
        sys.stderr.flush()

    # Bridge audit (fire-and-forget; failures ignored)
    try:
        handle(event_name=EVENT_NAME, harness="claude", payload=payload)
    except Exception:  # hook handler — broad catch is the documented contract  # noqa: BLE001, RUF100
        sys.stderr.write("Hook output: pool-bootstrap bridge routing failed\n")
        sys.stderr.flush()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # hook handler — broad catch is the documented contract  # noqa: BLE001, RUF100
        sys.stderr.write("Hook output: pool-bootstrap unhandled error\n")
        sys.stderr.flush()
        sys.exit(0)
