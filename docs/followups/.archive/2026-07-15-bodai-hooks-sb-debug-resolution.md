______________________________________________________________________

## status: resolved role: implementation date: 2026-07-16 last_reviewed: 2026-07-16 superseded_by: null topic: bodai-hooks-sb-debug

# Resolution — Bodai Hooks + Session-Buddy MCP Debug (2026-07-15)

## Status

**Resolved (partial).** The pickup prompt's headline symptom (`-32000 transport dropped` during `mcp__session-buddy__checkpoint`) is now
explained as **multi-session MCP contention**, not a single-session
transport bug. A failing validator test is in place to catch the
underlying config-format regression so the silent failure mode can't
return.

| Item | State |
|------|-------|
| Root cause | **Identified** — see §Root cause below |
| Failing test | **`tests/unit/test_claude_settings_hooks_format.py`** — RED on current state |
| Proposed fix | **Documented (not applied)** — see §Proposed fix |
| Other sessions running concurrently | 4 Claude Code processes observed at debug time (PIDs 24036, 21307, 23712, 26880) |

## Root cause

The pickup prompt framed this as a Session-Buddy server bug. It is not.
The bug is the **combination of two findings**:

### Finding 1 — `.claude/settings.json` uses the wrong JSON shape for hooks

The project's `.claude/settings.json` declares hooks at the top level:

```json
{
    "SessionStart": [...],
    "PostToolUse":  [...],
    "SessionEnd":   [...]
}
```

Claude Code's loader requires hooks nested under a top-level `"hooks"`
key:

```json
{
    "hooks": {
        "SessionStart": [...],
        "PostToolUse":  [...],
        "SessionEnd":   [...]
    }
}
```

The flat layout is **silently ignored** — no error, no warning, no firing.
That is why `bodai-activity-post-tool-use.py` and
`bodai-activity-subscriber.py` are wired but never produced any of their
expected artifacts in `~/.mahavishnu/`:

- `bodai-subscriber-state.json` — missing (would exist if SessionStart fired)
- `bodai-post-tool-use-state.json` — missing (would exist if PostToolUse fired)
- `bodai-event-queue.json` — missing (would exist after first EventBridge envelope)

`~/.mahavishnu/fallback-queue/dlq-fail-closed-2026-07-16.json` and
`~/.mahavishnu/verification-dead-letter/test.json` *do* exist, proving
that other Mahavishnu components write to `~/.mahavishnu/` correctly.
The hook scripts themselves are functional: a direct invocation of
`python3 .claude/hooks/bodai-activity-subscriber.py session-start`
spawned the EventBridge subscriber (pid 87411) and wrote the state file.
The bug is purely a config-format issue.

### Finding 2 — Multi-session MCP contention, not a server bug

The pickup prompt's symptom (`-32000 transport dropped`) reproduces when
**multiple Claude Code sessions call `mcp__session-buddy__*`
concurrently**. Diagnostic evidence:

- 4 Claude Code processes running at debug time
  (PIDs 24036, 21307, 23712, 26880)
- Each session's `~/.claude/settings.local.json` fires
  `python3 /Users/les/.claude/scripts/sb_checkpoint.py` on every Stop
  event — that script calls session-buddy over HTTP at `/mcp`
- Sessions start/stop independently, so multiple Stop events can fire
  in the same second, all hammering the same HTTP endpoint
- session-buddy has been up 14+ hours with no restarts; the server
  itself is healthy (`claude mcp list` reports ✔ Connected)

The pickup prompt's "raise timeouts / add retries" recommendations would
mask the symptom, not fix it. The architectural fix is per-session
isolation (worktrees), which already exists at
`/Users/les/Projects/mahavishnu/.claude/worktrees/` but is not
universally adopted.

## Verification of hooks (pickup-prompt Step 3b/3c/3e)

| Question | Answer | Evidence |
|----------|--------|----------|
| Are bodai-activity-\* hooks firing? | **NO** | Missing `~/.mahavishnu/bodai-*.json` artifacts |
| Are sb\_\* hooks firing? | YES | Local `~/.claude/settings.local.json` uses nested format |
| Do any hooks do `git stash` / `git stash pop`? | NO | Read both hook scripts; only HTTP/Redis ops |
| Is the stash-clobber fix plan relevant here? | Indirectly | Plan covers a different defect; this bug is unrelated |

## Proposed fix (not applied)

Apply the JSON shape fix to `.claude/settings.json`. Wrap the existing
hook entries in a `"hooks"` key. The `permissions` block stays at the
top level (Claude Code docs put `permissions` and `hooks` as siblings).

```diff
 {
+  "permissions": { ... },
+  "hooks": {
     "PostToolUse": [
       {
         "hooks": [
           {
             "command": "python3 .claude/hooks/bodai-activity-post-tool-use.py",
             "type": "command"
           }
         ],
         "matcher": "mcp__*"
       }
     ],
     "SessionEnd": [...],
     "SessionStart": [...]
+  }
 }
```

**Do not auto-apply.** Reasons:

1. Four Claude Code sessions are actively running; a hot config change
   could re-trigger hook firing mid-session.
1. The working tree has 47 dirty `docs/superpowers/plans/*.md` files
   from another session's normalization wave. Bundling this fix with
   those changes risks the drift-bundling pattern flagged in the
   project memory.
1. Per project CLAUDE.md: "Settings are intended to stay local and
   configuration-driven, not hard-coded." The user may prefer to move
   bodai hooks to a project-local `.claude/settings.local.json` instead.

## Recommended steps after applying the fix

1. Apply the fix above manually.
1. Run the validator: `.venv/bin/python3 -m pytest tests/unit/test_claude_settings_hooks_format.py -v` — expect 4 passed.
1. Restart Claude Code for this project (or run `/exit` then re-open) so the SessionStart hook fires.
1. Verify `~/.mahavishnu/bodai-subscriber-state.json` exists after restart.
1. Call any `mcp__*` tool and verify `~/.mahavishnu/bodai-post-tool-use-state.json` appears.

## Cross-references

- **Originating pickup prompt**: `docs/followups/2026-07-15-pickup-bodai-hooks-and-sb-debug.md`
- **Failing test**: `tests/unit/test_claude_settings_hooks_format.py`
- **Stash-clobber fix plan (separate defect)**: `docs/superpowers/plans/2026-07-15-sb-checkpoint-stash-clobber-fix.md`
- **Project session log**: `docs/followups/2026-07-16-dlq-fail-closed-session-checkpoint.md` (DLQ work the previous day that hit the same transport-drop symptom)
- **Global hook overlay (correct shape)**: `~/.claude/settings.local.json`
- **Pre-existing checkpoint from originating wave**: `docs/followups/.archive/2026-07-15-comprehensive-hooks-cleanup-checkpoint.md`

## Open follow-up (not in this resolution)

The multi-session contention concern (Finding 2) is a separate
architectural issue. Recommend opening a new followup:
`docs/followups/<date>-multi-session-mcp-contention.md` to track
adoption of worktree-isolated sessions for new Claude Code instances
in this project.
