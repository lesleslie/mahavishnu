#!/usr/bin/env python3
# ruff: noqa: EXE001
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

Phase 12 Task 2 (option B): augments the original hook with bridge
routing to ``mahavishnu.bodai_hook_bridge.handle`` for bus publish +
audit. The existing logic is preserved verbatim — bridge failure can
never alter the authoritative exit code (spec §4.13.3).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

CLAUDE_PROJECT_DIR = os.environ.get("CLAUDE_PROJECT_DIR")
if CLAUDE_PROJECT_DIR:
    sys.path.insert(0, CLAUDE_PROJECT_DIR)

from mahavishnu.bodai_hook_bridge import handle
from mahavishnu.jot.drain import surface_relevant

EVENT_NAME = "SessionStart"


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


def _safe_parse_payload() -> dict[str, object]:
    """Parse stdin JSON; return empty dict on any parse failure.

    SessionStart payloads may omit the prompt or session_id; we
    only need the payload to forward to the bridge routing layer
    (the original hook reads os.getcwd() directly, not stdin).
    """
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


def _run_hook() -> int:
    """Original main() body, extracted for the bridge augmentation.

    SessionStart derives context from os.getcwd() (no prompt available),
    so this helper takes no parameters. The bridge routing in main()
    reads stdin separately to forward the canonical envelope.
    """
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


def main() -> int:
    """Bridge-augmented entry point.

    Runs the original hook logic via :func:`_run_hook`, captures the
    authoritative exit code, then fire-and-forgets the bridge routing.
    The bridge call's result is intentionally ignored — the original
    exit code from :func:`_run_hook` is authoritative per spec §4.13.3.
    """
    existing_exit_code = _run_hook()
    payload = _safe_parse_payload()

    # Bridge routing — fire-and-forget. Failures (bus down, adapter
    # missing, etc.) must NEVER alter the authoritative exit code.
    try:
        handle(event_name=EVENT_NAME, harness="claude", payload=payload)
    except Exception:  # noqa: BLE001 - bridge telemetry is observation-only
        sys.stderr.write("Hook output: jot-session-start bridge routing failed\n")
        sys.stderr.flush()

    return existing_exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - boundary handler: never block SessionStart
        sys.stderr.write("Hook output: jot-session-start unhandled error\n")
        sys.stderr.flush()
        sys.exit(0)
