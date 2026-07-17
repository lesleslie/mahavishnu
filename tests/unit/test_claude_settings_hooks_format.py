"""Validate .claude/settings.json follows the documented Claude Code hook schema.

Why this test exists
====================

Claude Code loads project hooks from ``.claude/settings.json``. The
documented schema requires hooks nested under a top-level ``"hooks"`` key::

    {
        "permissions": {...},
        "hooks": {
            "SessionStart": [{"matcher": "...", "hooks": [...]}],
            "PostToolUse": [...],
            ...
        }
    }

A *flat* layout (``{"SessionStart": [...]}`` at the top level) is silently
ignored by Claude Code — no warning, no error, no firing. This test pins
the nested layout so the silent regression is caught at CI time instead
of in production.

The bug was discovered during the 2026-07-15 comprehensive-hooks-cleanup
wave (see ``docs/followups/2026-07-15-bodai-hooks-sb-debug.md``):
``bodai-activity-post-tool-use.py`` and ``bodai-activity-subscriber.py``
were wired but never fired because the project's ``.claude/settings.json``
used the flat layout. The ``~/.claude/settings.local.json`` overlay
already uses the correct nested layout for its ``sb_*`` scripts and those
fire as expected.
"""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_SETTINGS = PROJECT_ROOT / ".claude/settings.json"

# Claude Code supports these hook events. Any other top-level key that
# looks hook-shaped (SessionStart, PostToolUse, PreToolUse, etc.) signals
# a flat-layout regression.
SUPPORTED_HOOK_EVENTS: frozenset[str] = frozenset(
    {
        "PreToolUse",
        "PostToolUse",
        "Notification",
        "Stop",
        "SubagentStop",
        "PreCompact",
        "SessionStart",
        "SessionEnd",
        "UserPromptSubmit",
    }
)


def _load_settings() -> dict[str, object]:
    """Read the project settings.json; tests fail if it is missing."""
    assert PROJECT_SETTINGS.is_file(), (
        f"project settings file missing: {PROJECT_SETTINGS}"
    )
    return json.loads(PROJECT_SETTINGS.read_text(encoding="utf-8"))


def test_project_settings_has_hooks_top_level_key() -> None:
    """Project settings must declare hooks under a top-level ``hooks`` key.

    Without this nested key Claude Code silently ignores all hook entries.
    """
    settings = _load_settings()
    assert "hooks" in settings, (
        ".claude/settings.json must declare hooks under a top-level "
        "'hooks' key (Claude Code schema). Currently the file uses a "
        "flat layout where SessionStart/PostToolUse sit at the top level "
        "and are silently ignored — the bodai-activity-* scripts are "
        "wired but never fire."
    )
    assert isinstance(settings["hooks"], dict), (
        f"top-level 'hooks' must be a mapping of event name to handler "
        f"list, got {type(settings['hooks']).__name__}"
    )


def test_project_settings_no_flat_event_keys() -> None:
    """No hook-event keys (SessionStart, PostToolUse, ...) at the top level.

    Flat-layout entries are silently ignored by Claude Code — the file
    looks correct but the hooks do not fire. Catching the flat layout
    early prevents the silent-regression foot-gun.
    """
    settings = _load_settings()
    flat_event_keys = sorted(
        event for event in settings if event in SUPPORTED_HOOK_EVENTS
    )
    assert not flat_event_keys, (
        ".claude/settings.json has flat-layout hook keys "
        f"{flat_event_keys} at the top level. Claude Code only honours "
        "hooks nested under a top-level 'hooks' key. Move each entry "
        "inside 'hooks': { ... } to fix."
    )


def test_project_settings_hook_commands_resolve() -> None:
    """Every hook command's script path must exist on disk.

    Relative paths are resolved against the repo root (Claude Code runs
    the hook with CWD at the project root).
    """
    settings = _load_settings()
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        # Covered by test_project_settings_has_hooks_top_level_key.
        return

    missing: list[str] = []
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            inner = entry.get("hooks") if isinstance(entry, dict) else None
            if not isinstance(inner, list):
                continue
            for handler in inner:
                cmd = handler.get("command") if isinstance(handler, dict) else None
                if not isinstance(cmd, str):
                    continue
                # Take the first whitespace-separated token; commands may
                # have args appended (e.g. ``...py session-start``).
                first_token = cmd.split()[0]
                # Strip a leading ``python3`` / ``python`` interpreter
                # — the second token is the actual script.
                tokens = cmd.split()
                script_token = (
                    tokens[1]
                    if tokens[0] in {"python", "python3"} and len(tokens) > 1
                    else first_token
                )
                # Absolute paths are resolved as-is; relative paths are
                # resolved against the project root (Claude Code's CWD).
                script_path = Path(script_token)
                if not script_path.is_absolute():
                    script_path = PROJECT_ROOT / script_path
                if not script_path.is_file():
                    missing.append(f"{event}: {cmd} -> {script_path}")

    assert not missing, (
        "Hook commands reference scripts that do not exist on disk:\n  "
        + "\n  ".join(missing)
        + "\nMove each script into the project tree or fix the path."
    )


def test_project_settings_known_bodai_hooks_present() -> None:
    """The bodai-activity-* hooks should appear under the nested 'hooks' key.

    Sanity check: after the format fix, these two script references must
    be reachable via the nested layout. Catches accidental deletion of
    the hook entries when restructuring the file.
    """
    settings = _load_settings()
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        # Covered by test_project_settings_has_hooks_top_level_key.
        return

    expected_substrings = (
        "bodai-activity-post-tool-use.py",
        "bodai-activity-subscriber.py session-start",
        "bodai-activity-subscriber.py session-end",
    )

    flattened = json.dumps(hooks)
    missing = [s for s in expected_substrings if s not in flattened]
    assert not missing, (
        "Expected bodai-activity-* hook entries to be present under "
        f".claude/settings.json:hooks. Missing: {missing}"
    )
