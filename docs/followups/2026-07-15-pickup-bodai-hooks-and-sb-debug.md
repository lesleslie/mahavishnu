# Pickup Prompt — Bodai Claude Code Hook Health + Session-Buddy MCP Debug

**Created**: 2026-07-15
**Purpose**: Stand-up prompt for a future Claude Code session to (a) debug the
Session-Buddy MCP transport-closed / mid-call-drop issue, and (b) audit the
Bodai Claude Code session hooks (SessionStart, Stop, etc.) to confirm they're
firing correctly.

**Originating session**: 2026-07-15 comprehensive-hooks-cleanup wave
(pre-existing checkpoint at `docs/followups/2026-07-15-comprehensive-hooks-cleanup-checkpoint.md`).
The MCP transport dropped twice during that session when invoking
`mcp__session-buddy__checkpoint` (see "Process Notes" there for the error
signatures: `-32000` connection-closed → transport dropped mid-call →
"is not connected").

---

## Step 0 — Load skills (RUN THESE FIRST, in order)

Invoke via the `Skill` tool. Each is a discrete skill load; do not skip or
reorder. They establish the procedural discipline for everything that follows.

1. **`superpowers:systematic-debugging`** — for the MCP transport bug.
   The repeated `/checkpoint` failures are an intermittent, hard-to-reproduce
   transport-layer symptom; this skill is mandatory before proposing fixes
   to transport, connection, or hook wiring problems.

2. **`superpowers:test-driven-development`** — for any code change that
   surfaces while investigating (e.g. a hook handler added, an MCP retry
   path inserted). The Bodai ecosystem enforces TDD on production code;
   see `crackerjack-compliant-code` skill for the local conventions.

3. **`superpowers:writing-skills`** — only if investigation surfaces a
   missing skill that should exist (e.g. an MCP-retry playbook that the
   team has converged on but isn't yet codified). Don't load speculatively.

4. **`crackerjack-compliant-code`** — load before making any code change
   inside `mahavishnu/`. The full procedural reference for repo conventions
   (line length, function-arg ceiling 10, branch ceiling 15, return ceiling 6,
   statement ceiling 55 with practical target 30, coverage floor 80%, type
   hints mandatory, Ruff active rules I/N/UP/B/C4/SIM/TCH + pylint P subset,
   mypy strict + pyright strict).

**Note on "SDD"**: if the project has a separate `SDD` (Skills-Driven
Development / Spec-Driven Development) skill locally at
`.claude/skills/sdd/` or `~/.claude/plugins/…/skills/sdd/`, load it here as
Step 0.3b. The originating session had no SDD-specific skill defined in its
reachable skill list; treat it as project-local-only and look it up before
assuming the four skills above cover all required disciplines.

After loading, **confirm in your first message which skills successfully
loaded** so it's auditable which discipline applies to subsequent steps.

---

## Step 1 — Establish MCP baseline before debugging

Reproduce the originating-session symptom first; without that, "fixed" is
unprovable.

```bash
# From the repo root:
cd /Users/les/Projects/mahavishnu
uv run python -c "import asyncio
from mcp import ClientSession, StdioServerParameters, stdio_client

async def probe():
    params = StdioServerParameters(command='mahavishnu', args=['mcp', 'start'])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            tools = await s.list_tools()
            return tools

tools = asyncio.run(probe())
print(f'Tools available: {len(tools.tools)}')
" 2>&1 | tail -20
```

If this fails, the failure mode tells you which path to walk in Step 2.
Then try the actual Session-Buddy MCP path the originating session used:

```bash
# Verify mahavishnu MCP can be reached by Claude Code by issuing any tiny call:
# (this relies on SessionStart having already established the connection in
# a real CC session; in a non-CC environment you'd have to start the server
# first.)
claude mcp list 2>&1
```

Record the output verbatim in the conversation transcript before proceeding.

---

## Step 2 — Systematic-debug Phase 1: root-cause the transport drop

Apply the systematic-debugging skill rigorously. The originating session
left three concrete error signatures in the same call session:

| Attempt | Error |
|---|---|
| 1 (initial `/session-buddy:checkpoint (MCP)`) | `MCP error -32000: Connection closed` |
| 2 (after `/mcp` reconnect) | `MCP server "session-buddy" transport dropped mid-call; response for tool "checkpoint" was lost` |
| 3 (immediate retry) | `MCP server "session-buddy" is not connected` |

The escalation pattern (closed → dropped → not connected) suggests the
server process is dying, not the transport being slow. Use this checklist:

1. **Server health**: `ps aux | grep -i 'session.buddy\|akosha\|mcp' | grep -v grep`
2. **Server log tail**: `tail -50 ~/.session-buddy/logs/*.log 2>/dev/null || tail -50 /tmp/session-buddy*.log 2>/dev/null`
3. **Connection establishment cost**: how long does `mcp__session-buddy__*` take from idle → first call (measure).
4. **Concurrent callers**: count how many `mcp__session-buddy__*` invocations
   happen during a Claude Code session; the originating session had at
   least one heavy user (this comprehensive-hooks session with ~10
   workflow subagents). Repeated invocations during heavy load may exceed
   the server's connection-handling capacity.
5. **MCP config in `.mcp.json`**: confirm the `session-buddy` server entry
   has timeout/retry settings. If it has a `timeout` < 30s, increase it.

Per the systematic-debugging skill's "Phase 4 step 5 — architectural
question": if 3+ investigations reveal deeper layered issues, question
the architecture (single-tenant MCP server sharing a Claude Code process,
session lifecycle, etc.). **Don't propose architectural rewrites without
discussion.**

---

## Step 3 — Verify Bodai Claude Code hooks are firing

The user wants to confirm `SessionStart`, `Stop`, and the rest of the
Bodai hook set are wired and producing the expected effects. Start with
the config, then exercise one hook each, end-to-end.

### 3a. Audit hook configuration

```bash
cat .claude/settings.json 2>&1 | head -100
ls -la .claude/hooks/ 2>&1 | head -20
ls -la ~/.claude/hooks/ 2>&1 | head -20  # global hook dir if present
```

For each hook listed, note:

- Which event it binds to (`SessionStart`, `Stop`, `UserPromptSubmit`, etc.)
- Whether the command exists and is executable
- Whether any per-event wrapper or shell entry point chains additional logic

### 3b. Exercise each hook (no live session needed for some)

| Event | How to exercise | What to check |
|---|---|---|
| `SessionStart` | Start a fresh Claude Code session in this repo | Hook output appears at session-open with the session's context payload (model, cwd, version) |
| `Stop` | Use Claude Code normally, then end the turn | Hook fires on turn boundary; output appears in the conversation log + logfile |
| `UserPromptSubmit` | Send a normal user message | Hook sees the prompt text |
| `PreToolUse` / `PostToolUse` | Run any tool | Per-tool hook fires, logfile gains a row |
| `Notification` | Trigger an idle notification | Hook receives the notification payload |

For each event, look for the hook's stdout/stderr in the transcript AND
in the corresponding logfile (path depends on hook installation; common
locations: `.claude/logs/`, `~/.claude/logs/`, `~/.mahavishnu/logs/mcp.log`).

### 3c. Verify Bodai-specific session hooks

Bodai hooks beyond the standard Claude Code set may include (per the
checkpointer output in this session's transcript):

- Mahavishnu activity-stream hook (`.claude/hooks/mahavishnu-activity-stream.py`)
- Session-Buddy checkpoint hooks (per the `session-buddy-checkpoint-hooks-fire-during-subagent-sessions` memory)
- Crackerjack workflow hooks (per `crackerjack-cleanup-wave7` skill scaffold)

Audit each of these by:

```bash
grep -rn '"hooks"\|"SessionStart"\|"Stop"' .claude/ 2>&1 | head -40
```

If any expected hook is missing from `settings.json`, surface that as a
finding. Don't auto-add — the user wants verification, not silent
re-wiring.

### 3d. Check the Claude Code logs for session-buddy `SESSION BUDDY CHECKPOINT` markers

If session-buddy checkpoints have been firing correctly during the current
project's other sessions, you should see them in:
- `~/.session-buddy/checkpoints/<project-hash>/` (file-based checkpoints)
- The Claude Code transcript at hand-off
- The Session-Buddy database (HTTP API: `curl http://localhost:8678/...`)

### 3e. Verify checkpoint hooks don't clobber subagent work via stash operations

Per the `session-buddy-checkpoint-hooks-fire-during-subagent-sessions` memory
and a 2026-07-15 follow-up observation (see
`docs/followups/2026-07-15-sb-checkpoint-stash-clobber.md`): checkpoint
hooks that include `git stash` / `git stash pop` cycles can **re-apply
the stash while a subagent is still working**, clobbering the agent's
in-flight edits. This is not the same as the parent memory's "commits
appear between plan and implementer" symptom — the new observation is
that the *working-tree state* can be silently overwritten mid-task.

To verify this isn't happening in any active hook:

1. While a subagent is dispatched (e.g. via Task tool), tail the relevant
   log for checkpoint invocations. Note any `git stash` / `git stash pop`
   / `git stash apply` calls.
2. During subagent execution, check that no stash operations occur
   against the working tree. If they do, record the hook name and the
   parent commit the stash was anchored to.
3. After subagent completion, verify the agent's work is intact in the
   working tree: `git status` should show the agent's expected files
   as modified, not clobbered by stash re-application.

If a stash re-apply is observed during subagent work, record as a finding
even if no data was lost — the next session needs to know this is a
recurring pattern, not a one-off.

Recovery (if clobbered): identical to the existing memory's recovery —
surgical `git reset --soft BASE` + targeted `git add <files>` recovers
in ~5 minutes. Document the specific hook + commit pair that triggered
the re-apply so it can be traced to a config change.

### 3f. Reference the stash-clobber fix implementation plan

For the working-tree clobber pattern tracked in Step 3e above, the
implementation plan lives at
`docs/superpowers/plans/2026-07-15-sb-checkpoint-stash-clobber-fix.md`
(spec at `docs/superpowers/specs/2026-07-15-sb-checkpoint-stash-clobber-fix-design.md`).
**This pickup prompt does NOT replace the plan** — it addresses
*additional* concerns (MCP transport drops in Steps 1-2, hook firing
verification in Step 3) that are out of scope for the stash-clobber
fix. When executing the stash-clobber fix, follow the plan task-by-task.

Coordination notes for the future session that picks this up:

- The plan's **Task 1 (Architecture Probe)** confirms the fix location;
  the remaining tasks depend on that outcome.
- The plan's **Task 7 (Wire Orchestrator)** adapts if the probe shows
  the stash lives in `crackerjack` instead of `session-buddy` — the
  plan explicitly branches there.
- The plan's **Task 10 (Manual Claude Code Hook Verification)**
  overlaps with this pickup prompt's Step 3 — coordinate to avoid
  duplicate verification work; either task is sufficient evidence.
- After plan execution, the resolution doc per the plan's Task 11
  (`docs/followups/2026-07-15-bodai-hooks-sb-debug-resolution.md`) should
  cross-reference the plan's commit hashes, not re-derive them.

---

## Step 4 — Iterative fix loop (only after Phase 1 root cause is identified)

Apply systematic-debugging discipline:

1. Form one hypothesis at a time. Example: "the session-buddy server dies
   after handling N concurrent MCP calls because its connection pool has
   a leak."
2. Test minimally — change one variable (timeout, env var, max-connections).
3. Verify before continuing — re-run the reproduction probe from Step 1.
4. If 3 fixes fail → STOP and question the architecture.

Document each attempt with:

- Hypothesis (1 sentence)
- Change applied (1-3 lines max)
- Result (pass/fail with exit code)
- Reproduction probe retried: yes/no

---

## Step 5 — Acceptance criteria

The pickup is **done** when ALL of:

1. ✅ `mcp__session-buddy__checkpoint` runs to completion (or its
   alternative — direct DB/file write if MCP is intentionally avoided —
   succeeds) for THIS repo (`/Users/les/Projects/mahavishnu`)
2. ✅ All Bodai Claude Code hooks listed in `settings.json` are confirmed
   firing (each: logfile row exists, transcript shows hook output)
3. ✅ Any missing/firing-incorrectly hook has a recommendation recorded
   in `docs/followups/<date>-<topic>.md`
4. ✅ No regression in the comprehensive-hooks-cleanup gates
   (`pyscn`, `ty`, `creosote` all green; the 5 originally-failing pytests
   still pass).
5. ✅ The four skills loaded in Step 0 are referenced in the future
   session's first response so it's clear which discipline applied.
6. ✅ During at least one subagent dispatch observed in this session, no
   `git stash pop` / `git stash apply` occurred mid-task against the
   working tree (or, if it did occur, the trigger hook is recorded as a
   finding in `docs/followups/<date>-<topic>.md`)

---

## Step 6 — Report back

When done, write a follow-up note at
`docs/followups/2026-07-15-bodai-hooks-sb-debug-resolution.md` with:

- Root cause identified (or "still open, escalated")
- One-paragraph fix summary per finding
- Updated Session-Buddy MCP baseline (now-stable reproduction)
- Any new skills or hooks added (with file paths)

Then post a brief summary in the conversation: what was fixed, what
remains. Use the explanatory output style insight format for any
non-trivial decisions.

---

## Quick-reference for the next session

```bash
# Verify MCP is responsive
cd /Users/les/Projects/mahavishnu
uv run python -c "asyncio.run(check_sb_mcp())"  # customize with the probe from Step 1

# Show hook config + paths
cat .claude/settings.json | jq '.hooks' 2>/dev/null || cat .claude/settings.json
ls -la .claude/hooks/ ~/.claude/hooks/ 2>&1

# Re-read the originating checkpoint for full context
cat docs/followups/2026-07-15-comprehensive-hooks-cleanup-checkpoint.md
```

If after one thorough pass the MCP transport issue cannot be reproduced
deterministically, escalate to the user with the specific symptom that
*does* reproduce and the failure mode observed, rather than guessing at
causes.
