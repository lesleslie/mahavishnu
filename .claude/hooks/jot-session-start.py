#!/usr/bin/env python3
"""Jot SessionStart hook — surface open jots relevant to the current session.

Claude Code fires SessionStart on startup (and on resume). Per spec §6.9,
this hook surfaces up to 3 open jots via the ``hookSpecificOutput.additionalContext``
channel so the model sees pending work before the user issues the first prompt.

SessionStart payloads may not include a prompt — there is nothing to score
against, so the context is the cwd/repo path. Surfacing relies on lexical
overlap between that context and the open-jot corpus; semantic fallback
runs when lexical yields zero hits.

Exits 0 on all paths. Any unhandled exception is logged to stderr and the
hook exits 0 (Claude Code surfaces stderr as "Hook output" but never blocks
session start on a hook failure).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from mahavishnu.jot.drain import surface_relevant


def _format_matches(matches: list[object]) -> str:
    """Render a SurfacingResult.matches list as a short multi-line string."""
    if not matches:
        return ""
    lines: list[str] = []
    for m in matches:
        # JotSummary dataclass — read short_id and text defensively.
        short_id = getattr(m, "short_id", "?")
        text = getattr(m, "text", "")
        if not text:
            continue
        # Truncate each line to keep additionalContext compact.
        snippet = text if len(text) <= 160 else text[:157] + "..."
        lines.append(f"- [{short_id}] {snippet}")
    return "\n".join(lines)


def _build_context_text() -> str:
    """Best-effort ambient context for SessionStart (no prompt available).

    Falls back to the cwd + repo directory name so lexical scoring has
    something to compare against when the user hasn't typed yet.
    """
    cwd = os.getcwd()
    repo = Path(cwd).name
    return f"{repo} {cwd}".strip()


def main() -> int:
    context_text = _build_context_text()
    try:
        result = surface_relevant("session_start", context_text, limit=3)
    except Exception as exc:  # noqa: BLE001 - boundary handler: hook must never block SessionStart
        sys.stderr.write(f"Hook output: jot-session-start surface_relevant failed: {exc}\n")
        sys.stderr.flush()
        return 0

    body = _format_matches(result.matches)
    if not body:
        # No matches — emit an empty additionalContext so Claude Code
        # still receives the hookSpecificOutput envelope (consistent shape).
        body = ""
    additional_context = (
        f"Open jot suggestions ({len(result.matches)} found):\n{body}"
        if body
        else "No open jot suggestions for this session."
    )

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": additional_context,
        }
    }
    try:
        print(json.dumps(output))
    except Exception as exc:  # noqa: BLE001 - boundary handler
        sys.stderr.write(f"Hook output: jot-session-start json.dumps failed: {exc}\n")
        sys.stderr.flush()
        return 0
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - boundary handler: never block SessionStart
        sys.stderr.write("Hook output: jot-session-start unhandled error\n")
        sys.stderr.flush()
        sys.exit(0)
