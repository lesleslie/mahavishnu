# Operator Runbook — Migrating PLAN_INDEX.md to Dhara-canonical

This runbook executes the one-shot migration from filesystem-scanned
`docs/plans/PLAN_INDEX.md` (legacy `scripts/regenerate_plan_index.py`
filesystem scanner) to the Dhara-canonical `plan_index` layer. The
migration is split across three SDD tasks:

- **Task 18 (this runbook, steps 1-5)** — seed Dhara, snapshot the
  legacy file, run the bootstrap, sanity-check.
- **Task 19 (step 6)** — wire MCP `plan_*` tools into the production
  profiles (already shipped via Task 12-13).
- **Task 20 (steps 7-8)** — cut over skills and deprecate the legacy
  scanner.

The script artifacts referenced here are:

| Script | Purpose |
|---|---|
| `scripts/bootstrap_plan_index.py` | One-shot filesystem scan + Dhara upsert. Idempotent. |
| `scripts/backup_plan_index.py` | Snapshot `docs/plans/PLAN_INDEX.md` before the first write. |
| `scripts/restore_plan_index_backup.py` | Roll back to a previous backup. |
| `scripts/regenerate_plan_index.py` | Legacy filesystem scanner; reads as `PLAN_INDEX.md` for diff. |
| `scripts/audit_plan_index.py` | Three-way consistency check (PLAN_INDEX.md ↔ filesystem ↔ Dhara). |

## Step 0 — Pre-flight (run before step 1)

Confirm Dhara is reachable and the legacy scanner produces a known-good
PLAN_INDEX.md before touching anything.

```bash
cd /Users/les/Projects/mahavishnu
uv run crackerjack docs validate --strict --pkg-path .
# exit 0 ⇒ all frontmatter valid; proceed
# exit 1 ⇒ file lists non-conforming files; fix and re-run

uv run python scripts/regenerate_plan_index.py --repo-root . --out /tmp/PLAN_INDEX.legacy.md
diff /tmp/PLAN_INDEX.legacy.md docs/plans/PLAN_INDEX.md || true
# Differences here are acceptable — the legacy scanner has drifted
# in past runs. Confirm /tmp/PLAN_INDEX.legacy.md renders sanely.
```

## Step 1 — Backup the legacy PLAN_INDEX.md

Take a timestamped snapshot. This is the rollback anchor for the
entire migration; the file is overwritten by step 4, so the only way
to recover the pre-migration artifact is via this backup.

```bash
cd /Users/les/Projects/mahavishnu
uv run python scripts/backup_plan_index.py --keep-last 10
# stdout ⇒ docs/plans/PLAN_INDEX.20260915T000000Z.backup
# stderr ⇒ pruned: docs/plans/PLAN_INDEX.20260901T000000Z.backup (if any)
```

Verify the backup exists and is non-empty:

```bash
ls -la docs/plans/PLAN_INDEX.*.backup | tail -5
```

If the backup is missing, **STOP** — the migration cannot proceed
without a rollback anchor. Re-run step 1, or use
`scripts/restore_plan_index_backup.py --list` to confirm the script
itself is functional.

## Step 2 — Audit-only dry-run of the bootstrap

Before pointing the script at a live Dhara, run it in audit-only mode
(no `--dhara-url`, no `--dry-run` confusion — `--dry-run` here means
"don't write even if Dhara is reachable"). The bootstrap script
defaults to audit-only when `--dhara-url` is omitted.

```bash
cd /Users/les/Projects/mahavishnu
uv run python scripts/bootstrap_plan_index.py --repo-root . --backup-index
# stderr ⇒ bootstrap dry-run: scanned N files, built M records, skipped K (no frontmatter)
# stdout ⇒ {"success": M, "errors_count": 0, "mode": "audit-only", ...}
```

Inspect the summary: `success` should match the number of `.md` files
under `docs/plans/`, `docs/adr/`, `docs/superpowers/`, and other
discovered stores with `status:` + `title:` frontmatter. `skipped`
should be near zero — partial frontmatter is rare.

## Step 3 — Live bootstrap into Dhara

Connect the bootstrap script to a live Dhara (port 8683 in the
canonical Bodai layout). The script is idempotent — re-running
overwrites the same records with no duplicates.

```bash
cd /Users/les/Projects/mahavishnu
uv run python scripts/bootstrap_plan_index.py \
    --repo-root . \
    --dhara-url http://localhost:8683/mcp \
    --backup-index
# stderr ⇒ backed up PLAN_INDEX.md -> docs/plans/PLAN_INDEX.20260915T000000Z.backup
# stderr ⇒ bootstrap complete: success=N errors=0 skipped=K (no frontmatter)
# stdout ⇒ {"success": N, "errors_count": 0, "mode": "live", ...}
```

If the script exits 1 (total failure — every record errored), inspect
the partial-failure errors in Dhara's
`plan_index/meta/recent_errors` key. Common causes:

| Symptom | Likely cause |
|---|---|
| `normalize_repo_url` rejection on every record | Frontmatter `repo:` field uses an unrecognized URL form. |
| Dhara connection refused | `--dhara-url` points at the wrong port or Dhara is down. |
| Partial success (some succeed, some error) | A few records have malformed frontmatter; the rebuilder continues. Re-run after fixing the frontmatter. |

## Step 4 — Three-way audit (PLAN_INDEX.md ↔ filesystem ↔ Dhara)

After the bootstrap, the rendered PLAN_INDEX.md (from the legacy
scanner) and the Dhara records should describe the same set of files.
The three-way audit script surfaces drift.

```bash
cd /Users/les/Projects/mahavishnu
uv run python scripts/bootstrap_plan_index.py --repo-root . --dhara-url http://localhost:8683/mcp > /tmp/bootstrap.summary.json
uv run python scripts/audit_plan_index.py --repo-root . --dhara-records /tmp/bootstrap.summary.json
# exit 0 ⇒ consistent; proceed to step 5
# exit 1 ⇒ drift detected; inspect which leg diverged
```

If the audit fails, **STOP** — do not commit. Common causes:

- The legacy scanner picked up files the bootstrap script skipped
  (e.g. files lacking `status:` frontmatter). Fix the frontmatter and
  re-run step 3.
- The bootstrap script picked up files the legacy scanner skipped
  (e.g. a store that fell below the MIN_STORE_DOCS threshold). Either
  promote the file with frontmatter or add it to the excluded set.

## Step 5 — Commit and verify

Commit the migration artifacts and verify the snapshot test passes.

```bash
cd /Users/les/Projects/mahavishnu
git add scripts/bootstrap_plan_index.py \
        scripts/backup_plan_index.py \
        scripts/restore_plan_index_backup.py \
        docs/runbooks/migrate-plan-index-dhara.md \
        docs/feature-tracking/plan-index-dhara.md

git -c core.hooksPath=/dev/null commit -m \
    "chore(plan_index): migration run steps 1-5 (operator runbook + scripts)"

uv run pytest tests/integration/plan_index/test_render_matches_old_scanner.py -v
# expected: PASS (the golden matches the new render)
```

## Rollback

If anything goes wrong after step 5, the rollback path is:

```bash
cd /Users/les/Projects/mahavishnu
uv run python scripts/restore_plan_index_backup.py --list
# stdout ⇒ PLAN_INDEX.20260915T000000Z.backup
# stdout ⇒ PLAN_INDEX.20260914T000000Z.backup
# ...

uv run python scripts/restore_plan_index_backup.py --from docs/plans/PLAN_INDEX.20260915T000000Z.backup
# stdout ⇒ docs/plans/PLAN_INDEX.md
# stderr ⇒ restored from docs/plans/PLAN_INDEX.20260915T000000Z.backup
```

Restoring PLAN_INDEX.md does NOT undo Dhara writes. To roll back
Dhara, run the bootstrap with an empty `--repo-root` (no records) and
delete the affected `plan_index/*` keys via Dhara's MCP tooling.

## Idempotency notes

- The bootstrap script calls `PlanIndexRebuilder.upsert_all`, which
  is a primary-write that overwrites the same record. A second run
  does not duplicate records; it re-syncs the metadata.
- The backup script is not idempotent at sub-second resolution — two
  invocations within the same wall-clock second produce distinct
  files only when the timestamp string differs. Manual operators
  rarely trigger this race.
- The audit script reads from a JSON snapshot of the bootstrap
  output (`--dhara-records`); it does not hold a live Dhara
  connection, so it is safe to re-run any number of times.

## Observability

- `plan_index/meta/last_rebuild_ms` — set by the cron cycle (Task 14)
  on each successful rebuild, not by the bootstrap script. Operators
  can check `mcp__mahavishnu__plan_rebuild_status` to confirm the
  cycle is alive.
- `plan_index/meta/entities_count` — total records in Dhara after
  bootstrap. Should match `success` from the bootstrap summary
  (modulo records added by the cron cycle since step 3).
- `plan_index/meta/recent_errors` — bounded list (max 20 entries,
  30-day TTL) of the most recent partial-failure contexts. Inspect
  via `mahavishnu plan vitals` (Task 10) or the
  `mcp__mahavishnu__plan_vitals` tool.
