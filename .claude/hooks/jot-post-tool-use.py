#!/usr/bin/env python3
"""Jot PostToolUse hook — surface open jots relevant to the latest tool result.

Claude Code fires PostToolUse after every matched tool invocation (matcher
``mcp__*`` per the settings.json entry). Per spec §6.9, this hook reads the
``tool_result`` field from the JSON payload, truncates to 4096 chars, and
surfaces up to 3 open jots via the ``hookSpecificOutput.additionalContext``
channel so the model can fold a relevant pending jot into the next response.

Exits 0 on all paths. The PostToolUse hook must not block tool execution,
so any unhandled exception is logged to stderr and swallowed.
"""
from __future__ import annotations

import json
import sys

from mahavishnu.jot.drain import surface_relevant

TOOL_RESULT_MAX_CHARS = 4096


def _format_matches(matches: list[object]) -> str:
    """Render a SurfacingResult.matches list as a short multi-line string."""
    if not matches:
        return ""
    lines: list[str] = []
    for m in matches:
        short_id = getattr(m, "short_id", "?")
        text = getattr(m, "text", "")
        if not text:
            continue
        snippet = text if len(text) <= 160 else text[:157] + "..."
        lines.append(f"- [{short_id}] {snippet}")
    return "\n".join(lines)


def _safe_parse_payload() -> dict[str, object]:
    """Parse stdin JSON; return empty dict on any parse failure."""
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def main() -> int:
    payload = _safe_parse_payload()
    tool_result = payload.get("tool_result", "")
    if not isinstance(tool_result, str):
        tool_result = str(tool_result) if tool_result is not None else ""
    context_text = tool_result[:TOOL_RESULT_MAX_CHARS]

    try:
        result = surface_relevant("tool_result", context_text, limit=3)
    except Exception as exc:  # noqa: BLE001 - boundary handler: never block PostToolUse
        sys.stderr.write(f"Hook output: jot-post-tool-use surface_relevant failed: {exc}\n")
        sys.stderr.flush()
        return 0

    body = _format_matches(result.matches)
    additional_context = (
        f"Open jot suggestions ({len(result.matches)} found):\n{body}"
        if body
        else "No open jot suggestions relevant to this tool result."
    )

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": additional_context,
        }
    }
    try:
        print(json.dumps(output))
    except Exception as exc:  # noqa: BLE001 - boundary handler
        sys.stderr.write(f"Hook output: jot-post-tool-use json.dumps failed: {exc}\n")
        sys.stderr.flush()
        return 0
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - boundary handler: never block PostToolUse
        sys.stderr.write("Hook output: jot-post-tool-use unhandled error\n")
        sys.stderr.flush()
        sys.exit(0)
