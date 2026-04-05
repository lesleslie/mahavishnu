---
name: session-buddy
description: >
  Automatic session lifecycle integration with Session-Buddy. Tracks session start/end events,
  creates checkpoints, and syncs context before compaction. Use this skill when:
  (1) Starting a new session or first interaction of the day,
  (2) User says "checkpoint", "save progress", or "session checkpoint",
  (3) User says "end session", "session end", or similar,
  (4) Context is being compacted or consolidated,
  (5) User asks about session status or history.
always: false
---

# Session-Buddy Lifecycle

Manage session tracking with Session-Buddy via MCP tools.

## Session Start

On first interaction of a new session (no active session tracked today), call:

```
mcp_session-buddy_track_session_start(
  event_version="1.0",
  event_id=<uuid4>,
  event_type="session_start",
  component_name="nanobot",
  shell_type="NanobotGateway",
  timestamp=<now ISO 8601 UTC>,
  pid=<os.getpid() via exec>,
  user={"username": "les", "home": "/Users/les"},
  hostname=<hostname via exec>,
  environment={"python_version": <version>, "platform": <platform>, "cwd": workspace}
)
```

Get runtime values with `exec`:
- `python3 -c "import uuid; print(uuid.uuid4())"` for event_id
- `python3 -c "import os; print(os.getpid())"` for pid
- `hostname` for hostname
- `python3 -c "import sys, platform; print(f'{sys.version.split()[0]}|{platform.platform()}')"` for env

Store the returned `session_id` in MEMORY.md under `## Session-Buddy State` so it persists across messages.

## Session End

When user says "end session", "session end", "goodbye", or similar:
1. Call `mcp_session-buddy_track_session_end(session_id=<stored_id>, timestamp=<now ISO 8601 UTC>)`
2. Clear the session_id from MEMORY.md

## Checkpoint

When user says "checkpoint", "save progress", "session checkpoint":
- Call `mcp_session-buddy_checkpoint(working_directory="/Users/les/Projects/mahavishnu")`

## Pre-Compact Sync

When context is being compacted (user says "compact" or system consolidation triggers):
- Call `mcp_session-buddy_pre_compact_sync()`

## Auto-Checkpoint Reminder

If active for 2+ hours without a checkpoint, remind the user:
> "You've been working for a while — want me to save a checkpoint?"

Use `cron` to set a one-time reminder if needed.

## State Key in MEMORY.md

```markdown
## Session-Buddy State
- Active session ID: <id or "none">
- Last checkpoint: <timestamp or "never">
- Session started: <timestamp>
```

Update this section whenever state changes.
