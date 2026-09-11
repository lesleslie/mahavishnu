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
"""
from __future__ import annotations

import json
import sys

from mahavishnu.hooks.jot_capture import capture_hook


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
    prompt = payload.get("prompt", "")
    if not isinstance(prompt, str):
        prompt = str(prompt) if prompt is not None else ""

    session_id = payload.get("session_id", "")
    if not isinstance(session_id, str):
        session_id = str(session_id) if session_id is not None else ""

    files = payload.get("files", [])
    if not isinstance(files, list):
        files = []

    try:
        return capture_hook(prompt, session_id=session_id, files=files)
    except Exception as exc:  # noqa: BLE001 - boundary handler: never block UserPromptSubmit
        sys.stderr.write(f"Hook output: jot-capture wrapper error: {exc}\n")
        sys.stderr.flush()
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - boundary handler: never block UserPromptSubmit
        sys.stderr.write("Hook output: jot-capture wrapper unhandled error\n")
        sys.stderr.flush()
        sys.exit(0)
