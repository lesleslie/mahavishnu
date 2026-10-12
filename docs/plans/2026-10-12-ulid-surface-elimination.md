# Phase 9: ULID Surface Elimination

**Status:** shipped
**Shipped:** 2026-10-12
**Date:** 2026-10-12
**Owner:** les
**Role:** canonical
**Topic:** post-Phase-8 substrate consolidation
**Related plans:** `docs/plans/2026-10-11-uuid7-only-migration.md` (Phase 9 of that plan was renamed/renumbered; this is the cleanup that should have happened in Phase 0.5 of that plan but was deferred for the "lazy dual-write" Option D)

## Why this plan exists

The 2026-10-11 UUID7 migration plan's Option D (lazy dual-write, REQ-010)
chose to keep two ID surfaces alive for "read-time acceptance" during a
migration window: `oneiric.core.ids.is_valid_id` accepts BOTH 32-hex
UUID7 and 26-char Crockford Base32 ULID, and the `reflections` table
keeps a dual-write column (`uuid7_id` alongside the legacy `id`) so
first-read backfill is non-destructive.

The migration completed (Phases 0-8 all merged to `origin/main`). The
"migration window" is over, but the dual surface is still in place.
This violates the project's `feedback-no-backwards-compat-pre-1.0.md`
rule: "replace not extend; no deprecation windows". The user has
directed: "we do not want any legacy support for ulids and do not want
to maintain surfaces for ulids and uuid7s".

This plan collapses to a single substrate (UUID7) with no ULID surface.

## Goals

1. Single validation surface in `oneiric.core.ids` — `is_valid_id` accepts UUID7 only.
2. Single column on each migrated table — drop the dual-write `uuid7_id` column.
3. Single data format in every irreplaceable store — every legacy ULID row is rewritten to a deterministic UUID7.
4. No call sites read the legacy format.

## Tasks

### T1. Tighten `oneiric.core.ids.is_valid_id` to UUID7-only

- Remove the ULID branch from `is_valid_id`. It should only accept the 32-hex UUID7 format with version=7 and variant=0b10.
- Keep `is_uuid7` as the strict predicate (already correct).
- Update or remove the alias `is_valid_id_or_legacy_ulid` if it exists in any caller.
- Update `oneiric.core.ids` docstring to remove the "read-time acceptance" claim.

### T2. Migration: re-encode legacy ULID rows in `reflections` to UUID7

For every row in `session_buddy`'s `~/.claude/data/reflection.duckdb`:
`SELECT id, length(id)` — find rows where `length(id) == 26` (ULID).

For each:
- Compute the deterministic UUID7: `uuid7(seed=hashlib.sha256(legacy_id.encode()).digest()[:8])` (the recipe from the 2026-10-11 post-mortem).
- UPDATE the row: `id = <new_uuid7>`, `uuid7_id = NULL` (no longer needed).

The post-mortem in `docs/plans/2026-10-11-uuid7-only-migration.md §11` flagged
"stale-identity-mapping" as the canonical reason for deterministic
derivation: a re-run produces the same UUID7 for the same legacy_id,
so any external consumer that pinned the prior ID is not silently
re-keyed.

After T2, the table has a single `id` column of UUID7. Drop `uuid7_id` in T3.

### T3. Drop the dual-write `uuid7_id` column

```sql
ALTER TABLE reflections DROP COLUMN uuid7_id;
```

Same on the akosha warm stores and `outbox.duckdb` if they have the column.

### T4. Update session-buddy read paths to expect UUID7 only

- `core/memory/causal.py`, `skills/distiller.py`, `channel/state_writer.py`, `mcp/tools/tasks_storage.py` — any function that reads or writes `id` no longer needs the "is this a ULID or UUID7?" branch.
- Remove the `_dhara_substrate_compat.py` shim if it still exists.
- Update the fingerprint search / quick_search response shape if it surfaces a `uuid7_id` field that no longer exists.

### T5. Update akosha read paths to expect UUID7 only

- `akosha/processing/knowledge_graph.py` (`make_ulid`, `_load_ulid_generator` were modified in Phase 4 to use UUID7 — verify the ULID-acceptance branches are gone).
- `akosha/storage/aging.py` and the warm store init: confirm the lazy backfill path is removed (no `uuid7_id` column to fill).

### T6. Grep audit

After T1-T5, run:

```bash
grep -rE "ulid|ULID" oneiric/ session_buddy/ akosha/ mahavishnu/ \
  --include="*.py" | grep -v "build/" | grep -v ".venv/"
```

Expected: zero matches in production source. The only matches should be in
`docs/plans/2026-10-12-ulid-surface-elimination.md` (this plan) and
archived migration history.

### T7. Update validation matrix in `docs/plans/2026-10-11-uuid7-only-migration.md`

The plan's validation matrix at §7 has these rows:

> | `python -c 'from oneiric.core.ids import is_valid_id; print(is_valid_id("01ARZ3NDEKTS6PQRYF"))'` | `True` (ULID read-time acceptance) | post-Phase 2 |
> | `python -c 'from oneiric.core.ids import is_uuid7; print(is_uuid7("01ARZ3NDEKTS6PQRYF"))'` | `False` (strict UUID7-only check rejects ULID) | post-Phase 2 |

After Phase 9, the first row should change to:
> | `python -c 'from oneiric.core.ids import is_valid_id; print(is_valid_id("01ARZ3NDEKTS6PQRYF"))'` | `False` (ULID rejected) | post-Phase 9 |

## Exit criteria

- T1: `is_valid_id` returns `False` for `"01ARZ3NDEKTS6PQRYF"` (legacy ULID).
- T2: `SELECT count(*) FROM reflections WHERE length(id) == 26` returns `0`.
- T3: `DESCRIBE reflections` no longer lists `uuid7_id`.
- T4-T5: no `ulid|ULID` strings in `session_buddy/`, `akosha/` production source.
- T6: the grep audit returns zero production matches.
- T7: validation matrix updated.

## Rollback

The Phase 1 archive at `~/.local/state/bodai/db-archive/2026-10-11-uuid7-migration/`
preserves the pre-Phase-9 state for all 6 repos' irreplaceable stores
(including `reflection.duckdb`). To reverse Phase 9:
1. `tar -xzf <archive-tarball> -C /` for the relevant DBs.
2. Revert the `is_valid_id` patch.
3. Revert the read-path code changes.

The archive's SHA256SUMS were verified at Phase 8 step 1.
