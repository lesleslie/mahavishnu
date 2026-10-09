#!/usr/bin/env python3
# ruff: noqa: EXE001
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
import uuid

CLAUDE_PROJECT_DIR = os.environ.get("CLAUDE_PROJECT_DIR")
if CLAUDE_PROJECT_DIR:
    sys.path.insert(0, CLAUDE_PROJECT_DIR)

import httpx  # noqa: E402 - import after sys.path tweak

from mahavishnu.bodai_hook_bridge import handle  # noqa: E402

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
    except Exception:
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _invoke_bootstrap() -> dict[str, object] | None:
    """Call mcp__mahavishnu__pool_bootstrap via JSON-RPC 2.0 tools/call.

    Returns the parsed result dict on success, or None on any failure.
    The wire shape is JSON-RPC 2.0 over the FastMCP streamable-HTTP
    transport (POST /mcp). See mahavishnu/mcp/crow/raw_jsonrpc.py:234
    for the existing wire shape.
    """
    mcp_url = os.environ.get("MAHAVISHNU_MCP_URL", DEFAULT_MCP_URL)
    request = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tools/call",
        "params": {"name": "pool_bootstrap", "arguments": {}},
    }
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = client.post(
                mcp_url,
                json=request,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )
            if response.status_code != 200:
                sys.stderr.write(
                    f"Hook output: pool_bootstrap returned HTTP {response.status_code}\n"
                )
                sys.stderr.flush()
                return None
            envelope = response.json()
            # JSON-RPC 2.0 envelope: {"jsonrpc": "2.0", "id": ..., "result": ...}
            # or {"jsonrpc": "2.0", "id": ..., "error": ...}
            if "error" in envelope:
                sys.stderr.write(
                    f"Hook output: pool_bootstrap JSON-RPC error: "
                    f"{envelope['error']}\n"
                )
                sys.stderr.flush()
                return None
            result = envelope.get("result", {})
            # FastMCP wraps the tool return as either:
            #   {"content": [{"type": "text", "text": "..."}], "structuredContent": {...}}
            # or just the dict directly. Prefer structuredContent; fall
            # back to parsing the first text content as JSON.
            if isinstance(result, dict) and "structuredContent" in result:
                return result["structuredContent"]
            if isinstance(result, dict) and "content" in result:
                first = result["content"][0] if result["content"] else {}
                if isinstance(first, dict) and "text" in first:
                    try:
                        return json.loads(first["text"])
                    except (json.JSONDecodeError, ValueError):
                        return None
            if isinstance(result, dict):
                return result
            return None
    except Exception as exc:  # noqa: BLE001 - boundary: hook must never block SessionStart
        sys.stderr.write(f"Hook output: pool_bootstrap call failed: {exc}\n")
        sys.stderr.flush()
        return None


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
    except Exception as exc:  # noqa: BLE001 - boundary: output rendering must not block
        sys.stderr.write(f"Hook output: json.dumps failed: {exc}\n")
        sys.stderr.flush()

    # Bridge audit (fire-and-forget; failures ignored)
    try:
        handle(event_name=EVENT_NAME, harness="claude", payload=payload)
    except Exception:  # noqa: BLE001 - boundary: bridge is observation-only
        sys.stderr.write("Hook output: pool-bootstrap bridge routing failed\n")
        sys.stderr.flush()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - boundary: never block SessionStart
        sys.stderr.write("Hook output: pool-bootstrap unhandled error\n")
        sys.stderr.flush()
        sys.exit(0)
