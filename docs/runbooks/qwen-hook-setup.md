# Qwen Code hook bridge setup

> **Audience:** Operators installing Qwen Code on a machine where
> Mahavishnu's Bodai EventBridge subscription should run.
>
> **Runbook for:** Phase 12b task 2 (bridge files) + Phase 12b task 3
> (`~/.qwen/settings.json` registration).

## What this runbook installs

Qwen Code emits events via shell hooks the same way Claude Code
does. Each hook event is a separate executable that Qwen invokes
when the event fires. We install two things:

1. **11 Qwen-only bridge files** at `~/.qwen/hooks/<event>` —
   these are the operator-side files that normalize Qwen's JSON
   payload into the canonical envelope and delegate to
   `mahavishnu.bodai_hook_bridge.handle()`.
2. **One settings.json registration** — registers each bridge
   with Qwen's hook dispatcher.

After installation, every Qwen event lands on the unified Bodai
EventBridge stream (Redis Streams transport via
`oneiric.adapters.queue.redis_streams`) under channels named
`bodai.hooks.<kebab-case-event>`. Subscribers don't care which
harness fired — the bus is harness-agnostic and the `harness`
attribute on each envelope distinguishes Claude-fire from
Qwen-fire in the audit feed.

## Prerequisites

- Qwen Code installed and discoverable on `PATH` (verify with
  `which qwen` or `qwen --version`).
- Mahavishnu repo cloned at a known path. The bridges import
  `mahavishnu.bodai_hook_bridge`, so they need to know where the
  package lives. Set `QWEN_PROJECT_DIR=/path/to/mahavishnu` in
  your shell rc (or pass it explicitly when running the install
  script below).
- Python 3.14 (matches the project's `.python-version`).
- Optional: Redis reachable at `redis://localhost:6379/0` for
  the bus publish to succeed. Without Redis, the bridge still
  runs (fire-and-forget contract — publish failure is logged,
  not propagated).

## Step 1: Install the 11 Qwen-only bridge files

Run this **operator-side script** (it writes to `~/.qwen/hooks/`,
which is **not version-controlled** because the path is
user-global, like `.git/hooks/`):

```bash
#!/usr/bin/env bash
# install_qwen_bridges.sh — operator-side installer.
# Writes 19 Qwen bridge files (11 Qwen-only + 8 shared with Claude)
# at ~/.qwen/hooks/<event>. Idempotent: overwrites existing files.

set -euo pipefail

QWEN_HOOKS_DIR="${HOME}/.qwen/hooks"
mkdir -p "${QWEN_HOOKS_DIR}"

# 11 Qwen-only events (no Claude equivalent) + 8 shared events.
# The Qwen-only set comes from spec §4.13.2 schema table; the
# shared set is the Claude/Qwen overlap.
EVENTS=(
  # Qwen-only events (Phase 12b task 1):
  posttoolusefailure
  sessiondelete
  messagedisplay
  stopfailure
  subagentstart
  precompact
  postcompact
  permissionrequest
  permissiondenied
  todocreated
  todocompleted
  # Shared events (Claude + Qwen):
  posttooluse
  sessionstart
  sessionend
  stop
  subagentstop
  userpromptsubmit
  pretooluse
  notification
)

BRIDGE_TEMPLATE='#!/usr/bin/env python3
"""Qwen Code bridge — normalizes Qwen JSON to canonical envelope and
invokes mahavishnu.bodai_hook_bridge.handle().

Per spec §4.13.5 — bridges are per-harness thin normalizers.
"""
import json
import os
import sys
from pathlib import Path

# QWEN_PROJECT_DIR points at the mahavishnu repo root so the
# ``from bodai_hook_bridge import handle`` import below resolves.
# Set this in your shell rc, e.g.
#     export QWEN_PROJECT_DIR=/Users/les/Projects/mahavishnu
QWEN_PROJECT_DIR = os.environ.get("QWEN_PROJECT_DIR")
if QWEN_PROJECT_DIR:
    sys.path.insert(0, str(Path(QWEN_PROJECT_DIR)))

from bodai_hook_bridge import handle  # noqa: E402


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    # Qwen passes event name via argv[1] (canonical) or falls back
    # to the payload field if argv is empty.
    event_name = (
        sys.argv[1]
        if len(sys.argv) > 1
        else payload.get("hook_event_name", "?")
    )
    return handle(event_name=event_name, harness="qwen", payload=payload)


if __name__ == "__main__":
    sys.exit(main())
'

for event in "${EVENTS[@]}"; do
  target="${QWEN_HOOKS_DIR}/${event}"
  printf "%s\n" "${BRIDGE_TEMPLATE}" > "${target}"
  chmod +x "${target}"
  echo "wrote ${target}"
done

echo "installed ${#EVENTS[@]} Qwen bridge files at ${QWEN_HOOKS_DIR}"
```

Save this as `~/.qwen/hooks/install_qwen_bridges.sh` (or anywhere
convenient) and run it once per Qwen-using machine:

```bash
chmod +x ~/.qwen/hooks/install_qwen_bridges.sh
~/.qwen/hooks/install_qwen_bridges.sh
```

Expected output:

```
wrote /Users/<you>/.qwen/hooks/posttoolusefailure
wrote /Users/<you>/.qwen/hooks/sessiondelete
... (19 lines total)
installed 19 Qwen bridge files at /Users/<you>/.qwen/hooks
```

Verify each file is executable:

```bash
ls -la ~/.qwen/hooks/
# expect 19 bridge files, all with -rwxr-xr-x
```

## Step 2: Register bridges in `~/.qwen/settings.json`

Add (or merge into) the `hooks` block of your Qwen settings file.
This is the **canonical template** — copy it verbatim, then edit
the `command` paths to match your home directory if needed:

```json
{
  "hooks": {
    "PostToolUse": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/posttooluse"}]}],
    "PostToolUseFailure": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/posttoolusefailure"}]}],
    "SessionStart": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/sessionstart"}]}],
    "SessionEnd": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/sessionend"}]}],
    "SessionDelete": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/sessiondelete"}]}],
    "MessageDisplay": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/messagedisplay"}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/stop"}]}],
    "StopFailure": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/stopfailure"}]}],
    "SubagentStart": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/subagentstart"}]}],
    "SubagentStop": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/subagentstop"}]}],
    "PreCompact": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/precompact"}]}],
    "PostCompact": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/postcompact"}]}],
    "Notification": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/notification"}]}],
    "PermissionRequest": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/permissionrequest"}]}],
    "PermissionDenied": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/permissiondenied"}]}],
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/userpromptsubmit"}]}],
    "PreToolUse": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/pretooluse"}]}],
    "TodoCreated": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/todocreated"}]}],
    "TodoCompleted": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/todocompleted"}]}]
  }
}
```

If a `hooks` block already exists (e.g., from a prior Qwen
install), merge the missing entries rather than overwriting.

Validate the JSON before Qwen loads it:

```bash
cat ~/.qwen/settings.json | python -m json.tool > /dev/null && echo OK
```

## Step 3: Verify

Run the e2e suite — it executes each bridge as a subprocess and
verifies exit code 0 or 2 (handler decision, not bus failure):

```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/python -m pytest mahavishnu/tests/integration/test_qwen_hook_bridge_e2e.py -v
```

Expected:

- **19 passes** (one per event) when bridges are installed.
- **19 skips + 1 pass** when bridges are missing (the runbook
  existence test still passes — operators have the runbook to
  install the bridges).

## Step 4: Manual smoke test

After installation, start a Qwen session and run a tool call.
Verify the event lands on the bus:

```bash
# In one terminal, tail the bus (or the bridge's stderr):
redis-cli -u redis://localhost:6379/0 XLEN bodai:events
# expect: increasing count as you use Qwen

# Or via the bodai-status command:
/bodai-status
# expect: rows under [qwen] source column
```

If nothing appears on the bus, check:

1. `QWEN_PROJECT_DIR` is set in the shell that invoked Qwen
   (Qwen inherits the env from its parent shell).
2. Redis is reachable from the Qwen shell context.
3. `~/.qwen/settings.json` parses as JSON
   (`python -m json.tool ~/.qwen/settings.json`).
4. Each bridge file is executable (`ls -la ~/.qwen/hooks/`).

## Rollback

Removing the bridges is the inverse of installing them:

```bash
rm -rf ~/.qwen/hooks/{posttoolusefailure,sessiondelete,messagedisplay,stopfailure,subagentstart,precompact,postcompact,permissionrequest,permissiondenied,todocreated,todocompleted,posttooluse,sessionstart,sessionend,stop,subagentstop,userpromptsubmit,pretooluse,notification}
```

Then remove the `hooks` block (or relevant entries) from
`~/.qwen/settings.json`.

Qwen falls back to no-op behavior when a hook is registered but
the executable is missing — no error to the user, the event is
just not surfaced.

## Why this is operator-side

`~/.qwen/hooks/` is **not version-controlled** for the same
reason `.git/hooks/` isn't: it lives outside the project tree
and is per-machine. The Claude hooks live in
`mahavishnu/.claude/hooks/` because the project's `.claude/`
folder is in-repo; Qwen's hooks directory follows Qwen's
convention (user-global, like git hooks).

The runbook itself **is** version-controlled — operators
shouldn't need to guess where the install instructions live.
`docs/runbooks/qwen-hook-setup.md` is the source of truth; the
test
`mahavishnu/tests/integration/test_qwen_hook_bridge_e2e.py::test_qwen_bridge_module_documents_runbook_reference`
pins its existence.

## Cross-references

- Spec: `docs/superpowers/specs/2026-09-14-dhara-mcp-decomposition-design.md` §4.13
- Plan: `docs/superpowers/plans/2026-09-14-dhara-mcp-decomposition-implementation.md` §5 Phase 12b
- Bridge module: `mahavishnu/bodai_hook_bridge.py` (canonical handler + `_EVENT_HANDLERS` dispatch)
- E2E test: `mahavishnu/tests/integration/test_qwen_hook_bridge_e2e.py`
- Unit tests: `mahavishnu/tests/unit/test_bodai_hook_bridge.py` (Qwen-only parametrized tests)
