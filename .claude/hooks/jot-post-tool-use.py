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
import os
import sys

from mahavishnu.jot.drain import surface_relevant

EVENT_NAME = "PostToolUse"
TOOL_RESULT_MAX_CHARS = 4096

# Bridge dispatch — fire-and-forget; sync-blocking exit codes are preserved.
CLAUDE_PROJECT_DIR = os.environ.get("CLAUDE_PROJECT_DIR")
if CLAUDE_PROJECT_DIR:
    sys.path.insert(0, CLAUDE_PROJECT_DIR)
from mahavishnu.bodai_hook_bridge import handle


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


def _safe_parse_payload(raw: str | None = None) -> dict[str, object]:
    """Parse JSON; return empty dict on any parse failure.

    When called with no argument, reads from stdin (original behaviour).
    When called with ``raw`` text, parses that text instead — used by
    ``main`` so stdin is consumed exactly once for both ``_run_hook`` and
    the bridge dispatch.
    """
    if raw is None:
        raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _run_hook(payload: dict[str, object]) -> int:
    """Original hook logic, parameterised on the parsed stdin payload.

    Returns the exit code (always 0 on the success paths; failure paths
    also return 0 because PostToolUse must never block tool execution).
    """
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


def main() -> int:
    payload_text = sys.stdin.read()
    payload = _safe_parse_payload(payload_text)

    exit_code = _run_hook(payload)

    # Bridge routing for bus publish + audit (fire-and-forget; does not
    # influence the existing exit code).
    try:
        handle(event_name=EVENT_NAME, harness="claude", payload=payload)
    except Exception as exc:  # noqa: BLE001 - boundary handler
        sys.stderr.write(f"Hook output: jot-post-tool-use bridge dispatch failed: {exc}\n")
        sys.stderr.flush()

    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - boundary handler: never block PostToolUse
        sys.stderr.write("Hook output: jot-post-tool-use unhandled error\n")
        sys.stderr.flush()
        sys.exit(0)