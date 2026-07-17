______________________________________________________________________

## name: mahavishnu-status description: Check current Mahavishnu worker pool, verification, and dispatch status — equivalent to running pool list/health/metrics from a separate terminal.

Check current Mahavishnu worker pool, verification, and dispatch status.

This command runs `mahavishnu pool list`, `mahavishnu pool health`, and `mahavishnu metrics status` sequentially (and, once Phases 1 and 3 of the ultracode integration plan land, also `mahavishnu metrics verification` and `mahavishnu metrics dispatch`), then formats the output as a single status table. Use it instead of opening a second terminal to tail logs.

Run the following invocations in order, using the Bash tool (tool ID `Bash`) for each. Collect all output before formatting.

### 1. Pool list (always)

```bash
mahavishnu pool list
```

### 2. Pool health (always)

```bash
mahavishnu pool health
```

### 3. Metrics status (always)

```bash
mahavishnu metrics status
```

### 4. Verification metrics (conditional — only after Phase 1 lands)

Detect whether the verification subcommand is registered. If `mahavishnu metrics verification --help` exits with status 0, run it; otherwise skip the Verification section and note that verification is not yet wired.

```bash
if mahavishnu metrics verification --help >/dev/null 2>&1; then
  mahavishnu metrics verification
else
  echo "verification: not registered (Phase 1 not yet merged)"
fi
```

### 5. Dispatch metrics (conditional — only after Phase 3 lands)

Same gating pattern. Only run when `mahavishnu metrics dispatch --help` exits 0.

```bash
if mahavishnu metrics dispatch --help >/dev/null 2>&1; then
  mahavishnu metrics dispatch
else
  echo "dispatch: not registered (Phase 3 not yet merged)"
fi
```

After collecting all output, format a single markdown table with these sections (skip empty sections):

| Section | Source |
|---|---|
| Pool Status | `mahavishnu pool list` output — one row per pool (pool_id, type, worker count, status) |
| Pool Health | `mahavishnu pool health` output — one row per pool with health summary |
| Recent Activity | `mahavishnu metrics status` output — most recent workflow / execution counts |
| Verification | `mahavishnu metrics verification` output — consensus counts (when available) |
| Dispatch | `mahavishnu metrics dispatch` output — quota + result-write-failure counters (when available) |

If a section's command is not yet registered (Phases 1 or 3 not merged), render a single placeholder row: `| verification | not yet wired (Phase 1 pending) |` or `| dispatch | not yet wired (Phase 3 pending) |`.

Notes:

- Mirror the verbose-status.md format (heading + descriptive paragraph + fenced code blocks), but use `bash` fenced blocks here instead of `python` since this command shells out rather than reading local state.
- Do **not** add WebSocket subscriber logic here — that lives in `.claude/hooks/mahavishnu-activity-stream.py` (Task 5.4).
- Do **not** add the auto-trigger phrasing — that lives in `.claude/skills/vishnu-status/SKILL.md` (Task 5.2).
- The command does not modify any state; it is read-only and safe to invoke at any time.
