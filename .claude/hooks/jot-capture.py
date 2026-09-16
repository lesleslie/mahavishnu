#!/usr/bin/env python3
"""Jot UserPromptSubmit hook — capture prompts prefixed with ',,' as jots.

Claude Code fires UserPromptSubmit on every user prompt. Per spec §6.9, this
wrapper reads the prompt from the JSON stdin payload and delegates to
``mahavishnu.hooks.jot_capture.capture_hook``, which implements the
',,'-prefix detection and JSONL log persistence.

The wrapper emits no JSON output — capture is fire-and-forget. Claude Code
relies on the wrapper's exit code (0 = passthrough, 2 = capture-and-block)
to decide whether the prompt reaches the model. The wrapper itself swallows
all exceptions so a capture-path bug can never block the user's prompt.

Phase 12 Task 2 (option B): augments the original hook with bridge
routing to ``mahavishnu.bodai_hook_bridge.handle`` for bus publish +
audit. The existing logic is preserved verbatim — bridge failure can
never alter the authoritative exit code (spec §4.13.3).
"""
from __future__ import annotations

import json
import os
import sys

CLAUDE_PROJECT_DIR = os.environ.get("CLAUDE_PROJECT_DIR")
if CLAUDE_PROJECT_DIR:
    sys.path.insert(0, CLAUDE_PROJECT_DIR)

from mahavishnu.bodai_hook_bridge import handle
from mahavishnu.hooks.jot_capture import capture_hook

EVENT_NAME = "UserPromptSubmit"


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


def _run_hook(payload: dict[str, object]) -> int:
    """Original main() body, parameterised on the parsed stdin payload.

    Extracted from the pre-Phase-12 hook so the bridge augmentation
    in main() can fire-and-forget without re-reading stdin.
    """
    prompt = payload.get("prompt", "")
    if not isinstance(prompt, str):
        prompt = str(prompt) if prompt is not None else ""

    session_id = payload.get("session_id", "")
    if not isinstance(session_id, str):
        session_id = str(session_id) if session_id is not None else ""

    files = payload.get("files", [])
    if not isinstance(files, list):
        files = []

    return capture_hook(prompt, session_id=session_id, files=files)


def main() -> int:
    """Bridge-augmented entry point.

    Reads stdin ONCE, runs the original hook logic via
    :func:`_run_hook`, captures the authoritative exit code, then
    fire-and-forgets the bridge routing. The bridge call's result
    is intentionally ignored — the original exit code from
    :func:`_run_hook` is authoritative per spec §4.13.3.
    """
    payload = _safe_parse_payload()

    try:
        existing_exit_code = _run_hook(payload)
    except Exception as exc:  # noqa: BLE001 - boundary handler: never block UserPromptSubmit
        sys.stderr.write(f"Hook output: jot-capture wrapper error: {exc}\n")
        sys.stderr.flush()
        existing_exit_code = 0

    # Bridge routing — fire-and-forget. Failures (bus down, adapter
    # missing, etc.) must NEVER alter the authoritative exit code.
    try:
        handle(event_name=EVENT_NAME, harness="claude", payload=payload)
    except Exception:  # noqa: BLE001 - bridge telemetry is observation-only
        sys.stderr.write("Hook output: jot-capture bridge routing failed\n")
        sys.stderr.flush()

    return existing_exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - boundary handler: never block UserPromptSubmit
        sys.stderr.write("Hook output: jot-capture wrapper unhandled error\n")
        sys.stderr.flush()
        sys.exit(0)
