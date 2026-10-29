---
status: active
role: implementation
kind: plan
date: 2026-10-29
last_reviewed: 2026-10-29
superseded_by: null
blocks_on: []
topic: documentation-tooling
title: "Plan Index Store Drift — index regenerated, tool-side fix pending"
---

# Plan Index Store Drift — Index Regenerated, Tool-Side Fix Pending

> **This is a pointer plus a record of the mahavishnu-side fix.** The durable
> tool-side fix lives in the crackerjack repository. Read this for the
> diagnosis and the interim guard; implement the tool-side change in
> crackerjack.

## Diagnosis

Three different store-discovery mechanisms were in play, and they disagreed:

| Mechanism | Store discovery | Format |
|---|---|---|
| `scripts/regenerate_plan_index.py` (mahavishnu) | auto-discovered — every dir with ≥2 frontmatter'd `.md` | rich: frontmatter, Status Legend, Authority Matrix, Review Entry Points, per-store headings, "By Kind" |
| `crackerjack.tools.plan_index_sync` — legacy branch | **hardcoded 5-store tuple** (`DEFAULT_STORES`) | plain: bare store table |
| `oneiric.plan_index.regenerate` (shared) | auto-discovered | plain-ish: `Kind` column, no link rendering |

`scripts/audit_plan_index.py` delegates discovery to the **local** script —
"so the audit and the renderer never disagree about what counts as a store."
But the tool that actually regenerates `PLAN_INDEX.md` during the
`plan-index-sync` phase used the hardcoded list. So the two disagreed in
both directions, permanently:

- **Audit vs. tool** — the audit reported **82** frontmatter'd files missing
  from `PLAN_INDEX.md`, all in `docs/decisions/` and `docs/audits/`. Neither
  store is in the tool's fixed list, so every tool-driven regeneration
  silently dropped 77 rows.
- **Tool vs. repository** — the tool also re-rendered the index in a plainer
  format, rewriting a 394-insertion file back to the bare store table.

The fork's own docstring reads *"Walk the six stores"* while `DEFAULT_STORES`
has five entries — the tell that it was copied from an older revision of the
renderer and never re-synced.

**Fleet scope.** Auto-discovery is *not* the fleet baseline. All six Bodai
repositories ship a `scripts/regenerate_plan_index.py`, but only mahavishnu's
has evolved past the 16-function fixed-store-list version — oneiric,
crackerjack, session-buddy, akosha, and mcp-common each still have the
16-function version with no `discover_stores`. So this repository's script and
the tool's fork sit on opposite sides of that evolution, and the other five
repositories' copies still carry the older behavior. Delegation alone
therefore fixes the *tool*; propagating auto-discovery to the other five
repositories' copies is a separate task.

## What was done here (mahavishnu)

1. **`docs/plans/PLAN_INDEX.md` regenerated** with `scripts/regenerate_plan_index.py`.
   The audit now reports `OK: 168 paths consistent across PLAN_INDEX.md and
   filesystem`, and the 77 rows from `docs/decisions/` and `docs/audits/` are
   back. Relative-link rendering is preserved, so `check-local-links` still
   applies.

2. **Interim guard added** — `settings/crackerjack.yaml` sets
   `documentation.auto_plan_index_sync_on_publish: false`.

   The guard had to go in a new file: Oneiric resolves crackerjack's settings
   from `<project_root>/settings/{project_name}.yaml` with
   `project_name="crackerjack"`
   (`crackerjack/config/loader.py:load_settings_for_project`), so
   `settings/mahavishnu.yaml` is **not** read for these keys. Verified by
   loading `CrackerjackSettings` and asserting the value flipped to `False`.

   The phase is narrow-risk on its own — `plan_index_sync` defaults to
   `False` (`crackerjack/cli/options.py:133`), so `crackerjack run -v -f`
   does not trigger it. The guard closes the `--publish` path.

## What remains (crackerjack)

The durable fix is in the crackerjack repository:
`docs/plans/2026-10-29-plan-index-sync-delegate-to-repo-script.md`.

Three tasks:

1. **Delegate** to `<repo_root>/scripts/regenerate_plan_index.py` when it
   exists — propagate its exit code, never write a degraded index on failure,
   and do not require `--repo-root` (older copies lack it).
2. **Repair the bundled fallback** to auto-discover stores, so a repository
   without its own script still gets a complete index.
3. **Retire this interim guard** once the tool delegates.

Note that the repository-side scripts have themselves drifted: mahavishnu's
has 26 top-level functions and accepts `--repo-root`; crackerjack's own copy
has 16 and does not.

## Reproducing the diagnosis

```bash
# The audit's view (auto-discovery)
python scripts/audit_plan_index.py

# The tool's view (hardcoded stores) — this is what dropped 77 rows
python -m crackerjack.tools.plan_index_sync --repo-root . --out /tmp/tool_index.md
diff <(grep -c '' /tmp/tool_index.md) <(grep -c '' docs/plans/PLAN_INDEX.md)
```

## Integration Contract

- **Triggered from**: The `plan-index-sync` phase, the `--publish` path, or a manual run of either regenerator.
- **Returns to / updates**: `docs/plans/PLAN_INDEX.md`; `settings/crackerjack.yaml` gates the tool-driven path.
- **Demonstrable by**: `python scripts/audit_plan_index.py` reports `OK: 168 paths consistent`, and `grep -c "docs/decisions/" docs/plans/PLAN_INDEX.md` is non-zero.
- **Rollback signal**: The audit reports missing paths after a tool-driven regeneration — re-enable `auto_plan_index_sync_on_publish` and regenerate with the local script.
- **Observability added**: The audit is now green against the committed index, so a future divergence surfaces as a failing audit rather than a silent 77-row drop.

## Related

- Crackerjack plan: `~/Projects/crackerjack/docs/plans/2026-10-29-plan-index-sync-delegate-to-repo-script.md`
- Authoritative renderer: `scripts/regenerate_plan_index.py`
- Audit: `scripts/audit_plan_index.py`
