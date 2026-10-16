#!/usr/bin/env python3
"""Shared FastMCP streamable-HTTP wire helpers for Bodai SessionStart hooks.

Background
----------
FastMCP's streamable-HTTP transport requires an `initialize` JSON-RPC
handshake on every logical session. The server returns 200 + an
`mcp-session-id` header; every subsequent call on that session MUST
echo that header. Forgetting the handshake yields HTTP 400 "Missing
session ID" — a silent-fail mode that bit two operational hooks
(``bodai-agent-mirror.py``, ``mahavishnu-pool-bootstrap.py``) before
this module was extracted.

Successful ``tools/call`` responses are wrapped in
``text/event-stream`` (``event: message\\ndata: {json}\\n\\n``), not
plain JSON. Error responses are plain JSON. ``parse_sse_or_json``
handles both.

Why this lives next to the hooks (not inside the ``mahavishnu``
package) — portability. ``bodai-agent-mirror.py`` is intended to be
mirror-copied to ``~/.claude/hooks/`` for user-global coverage; if
its wire helpers lived inside the ``mahavishnu`` package, the
user-global copy would break. A sibling-module import (this file) is
portable as long as the hook and the helper travel together.

Wire shape reference
--------------------
::

    POST /mcp
    Content-Type: application/json
    Accept: application/json, text/event-stream
    mcp-session-id: <id from initialize>

    {"jsonrpc": "2.0", "id": "<uuid>", "method": "tools/call",
     "params": {"name": "<tool>", "arguments": {...}}}

    -> 200 + body either SSE-wrapped JSON-RPC envelope or plain JSON
       on error.

Usage
-----
::

    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from _bodai_mcp_client import init_session, call_tool, parse_sse_or_json

    with httpx.Client(timeout=1.0) as client:
        sid = init_session(client, "http://localhost:8680/mcp")
        if sid is None:
            return  # caller decides fallback
        result = call_tool(client, url, "pool_bootstrap", sid)
        # result is the unwrapped tool return (dict/list) or None
"""
from __future__ import annotations

import json
import sys
import uuid

INITIALIZE_PROTOCOL_VERSION = "2025-03-26"
CLIENT_NAME = "bodai-hook"
CLIENT_VERSION = "0.2.0"


def parse_sse_or_json(body: str) -> object | None:
    """FastMCP streamable-HTTP wraps successful results in SSE.

    Body shape on success: ``event: message\\ndata: {json}\\n\\n``.
    Body shape on error: plain JSON like ``{"jsonrpc": ..., "error": ...}``.
    Try JSON first; fall back to scanning for the first ``data:`` line.
    Returns the parsed object or None on any failure.
    """
    if not body:
        return None
    try:
        return json.loads(body)
    except (json.JSONDecodeError, ValueError):
        pass
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            return json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def init_session(client, url: str) -> str | None:
    """Send the FastMCP ``initialize`` handshake. Returns the session ID.

    Returns None on any failure (network error, non-200, missing header).
    Logs the failure to stderr so the hook's hook-output channel surfaces
    it to the operator; callers treat None as "skip this server".
    """
    request = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "initialize",
        "params": {
            "protocolVersion": INITIALIZE_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
        },
    }
    try:
        response = client.post(
            url,
            json=request,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
    except Exception as exc:  # hook handler — broad catch is the documented contract  # noqa: BLE001
        sys.stderr.write(f"Hook output: initialize failed for {url}: {exc!r}\n")
        sys.stderr.flush()
        return None
    if response.status_code != 200:
        sys.stderr.write(
            f"Hook output: initialize returned HTTP {response.status_code} for {url}\n"
        )
        sys.stderr.flush()
        return None
    session_id = response.headers.get("mcp-session-id")
    if not session_id:
        sys.stderr.write(
            f"Hook output: initialize response missing mcp-session-id for {url}\n"
        )
        sys.stderr.flush()
        return None
    return session_id


def call_tool(
    client,
    url: str,
    tool_name: str,
    session_id: str,
    arguments: dict | None = None,
) -> object | None:
    """POST jsonrpc 2.0 ``tools/call`` with the session id.

    Returns the unwrapped tool return value (dict or list) on success,
    or None on any failure. Unwrapping order:
      1. ``structuredContent`` if the envelope is a dict (preferred).
      2. ``content[0].text`` parsed as JSON/SSE if the envelope
         carries a content array (legacy MCP).
      3. The whole ``result`` field as a fallback when it is a
         dict or list directly.
    """
    request = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments or {}},
    }
    try:
        response = client.post(
            url,
            json=request,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "mcp-session-id": session_id,
            },
        )
    except Exception as exc:  # hook handler — broad catch is the documented contract  # noqa: BLE001
        sys.stderr.write(f"Hook output: {tool_name} call failed: {exc!r}\n")
        sys.stderr.flush()
        return None
    if response.status_code != 200:
        sys.stderr.write(
            f"Hook output: {tool_name} returned HTTP {response.status_code}\n"
        )
        sys.stderr.flush()
        return None
    parsed = parse_sse_or_json(response.text)
    if not isinstance(parsed, dict):
        return None
    if "error" in parsed:
        sys.stderr.write(f"Hook output: {tool_name} jsonrpc error: {parsed['error']}\n")
        sys.stderr.flush()
        return None
    result = parsed.get("result", {})
    if isinstance(result, dict) and "structuredContent" in result:
        return result["structuredContent"]
    if isinstance(result, dict) and result.get("content"):
        first = result["content"][0] if result["content"] else {}
        if isinstance(first, dict) and isinstance(first.get("text"), str):
            return parse_sse_or_json(first["text"])
    return result if isinstance(result, (dict, list)) else None
