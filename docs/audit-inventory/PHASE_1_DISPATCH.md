# Phase 1 Subagent Dispatch Template

Per Plan Task 1.1, the per-repo inventory dispatch uses this prompt
template (one per Core 7 repo, with `<name>` substituted).

## Subagent Prompt

```
You are auditing the Bodai CLI surface for `<name>`.

Read:
- `/Users/les/Projects/mahavishnu/docs/plans/2026-08-25-bodai-cli-audit.md` §11 (per-repo shell status)
- `/Users/les/Projects/mahavishnu/scripts/audit_cli_inventory.py` (the tool)

Tasks:
1. Run from the per-repo worktree (NOT the main checkout):
     cd /Users/les/Projects/<name>/.claude/worktrees/bodai-cli-audit-phase-1-<name> \
       && uv sync \
       && uv run python /Users/les/Projects/mahavishnu/.claude/worktrees/bodai-cli-audit-phase-0/scripts/audit_cli_inventory.py \
            repo --repo <name> --repo-path "$PWD" \
            --out-dir /Users/les/Projects/mahavishnu/.claude/worktrees/bodai-cli-audit-phase-0/docs/audit-inventory

2. Verify the JSON in
   `/Users/les/Projects/mahavishnu/.claude/worktrees/bodai-cli-audit-phase-0/docs/audit-inventory/<name>-cli-inventory.json`:
   - `command_count` matches `<name> --help 2>&1 | awk '/^  [A-Za-z]/ {print $1}' | sort -u | wc -l`
   - No `notes` field contains `inventory_failed`

3. Write
   `/Users/les/Projects/mahavishnu/.claude/worktrees/bodai-cli-audit-phase-0/docs/audit-inventory/<name>-cli-inventory.md`:
   - One paragraph summary (total commands, surface character, notable groupings)
   - Table of commands (command_path | short_help | staleness_verdict | notes)
   - Drift observations vs the per-repo README and CLAUDE.md

4. Cross-check the inventory against the per-repo README and CLAUDE.md;
   document any drift in the MD file.

5. Report back: total command count, number of stale/deprecated, any drift.

DO NOT edit source code in the <name> repo. The only output files are
the JSON (written by the inventory script) and the MD summary.
```

## Worktree Conventions

Per-repo worktrees live at:
```
/Users/les/Projects/<repo>/.claude/worktrees/bodai-cli-audit-phase-1-<repo>
```

Already created for: oneiric, dhara, session-buddy, akosha, crackerjack.

Mahavishnu reuses `bodai-cli-audit-phase-0` (the same worktree that
contains the inventory script and the centralized audit-inventory dir).

## Why run from a worktree, not main checkout

The inventory script does `sys.path.insert(0, repo_path)` to import the
target repo's Typer app. If repo_path is the main checkout and the main
checkout has uncommitted modifications (e.g. another session's work),
the import may fail or produce wrong results. Running from a clean
worktree with `--repo-path "$PWD"` avoids this entirely.

The `--repo-path` flag was added in commit `26e39d3c`; the `--out-dir`
flag was added for the `repo` subcommand, and `--out-dir` + `--projects-root`
for the `all` subcommand (same commit).

## Validation Gate (already passed for all 7 repos)

```bash
python3 -c "
import json
counts = {'mahavishnu': 50, 'oneiric': 30, 'dhara': 15, 'crackerjack': 28,
          'session-buddy': 5, 'akosha': 5, 'mcp-common': 0}
for r, min_n in counts.items():
    data = json.load(open(f'docs/audit-inventory/{r}-cli-inventory.json'))
    n = len(data['commands'])
    assert n >= min_n, f'{r}: expected >= {min_n}, got {n}'
print('OK: all minimum thresholds met')
"
```

## Current State (after commit 26e39d3c)

| Repo         | Commands | Min | Status   | Notes |
|--------------|----------|-----|----------|-------|
| mahavishnu   | 159      | 50  | OK       | Includes OneiricCLIBase surface |
| crackerjack  | 32       | 28  | OK       | |
| oneiric      | 30       | 30  | OK       | |
| session-buddy| 16       | 5   | OK       | |
| dhara        | 15       | 15  | OK       | dhara/cli.py uses `app = create_cli()` pattern |
| akosha       | 9        | 5   | OK       | Run from akosha's worktree (pyarrow dep) |
| mcp-common   | 0        | 0   | OK       | Library-only, branch short-circuits |

Total: 261 commands. PHASE_0_BASELINE.json written.

## Outstanding for Phase 1 completion

Per Plan Task 1.1:
- [x] 7 inventory JSON files written
- [x] PHASE_0_BASELINE.json written
- [x] All minimum thresholds met
- [ ] Per-repo MD summaries (`<name>-cli-inventory.md`) — 0 of 7 written
- [ ] Cross-checks against README/CLAUDE.md per repo — 0 of 7 done

The JSON-only output is enough to proceed to Phase 2 (cross-repo synthesis).
The MD summaries and cross-checks can be filled in by subagents during
Phase 2 dispatch or as a follow-up.

## Task 1.2: mcp-common confirmation

Plan Task 1.2 is library-only confirmation — already verified:
- `mcp-common-cli-inventory.json` shows `command_count: 0`
- The `mcp-common` branch in `inventory_one_repo` short-circuits to
  `{"repo": "mcp-common", "command_count": 0, "commands": [],
    "notes": ["library-only; no CLI surface"], "version": "..."}`

No follow-up needed for Task 1.2.