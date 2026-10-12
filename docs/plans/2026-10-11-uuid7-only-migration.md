---
status: partial
role: canonical
kind: plan
date: 2026-10-11
last_reviewed: 2026-10-12
superseded_by: null
topic: uuid7-migration
title: "UUID7-Only Migration — Eliminate ULID Across Bodai Core Components (Option B — Strict-UUID7 Offline Migration with Consolidation)"

---

# UUID7-Only Migration — Eliminate ULID Across Bodai Core Components

> **Why this plan exists.** Three facts converge: (a) `dhara` (the canonical ULID
> backend, rebranded from `druva`) has been removed from all six core component
> `pyproject.toml` manifests; (b) the entire ULID generator surface is now
> running on three independent hand-rolled pure-Python Crockford Base32
> encoders (oneiric, session-buddy, crackerjack); (c) session-buddy's new
> tasks system and cracker's ai_fix_event_bus have already committed to
> UUID7. The remaining ULID code is scaffolding for a backend that no longer
> exists, with no migration story behind it. Bodai is internal-only and the
> user has confirmed no backwards-compat concern. The right move is to delete
> ULID and standardize on stdlib `uuid.uuid7()` (Python 3.14, the project
> target).
>
> **Strategy: Option B (Strict-UUID7 offline migration with
> consolidation).** No transition period, no dual-write. The substrate
> and every consumer repo commit to UUID7-only at the end of the
> migration. Existing rows are converted by a one-time offline script
> (an ALTER TABLE ADD COLUMN + backfill + DROP COLUMN pattern);
> legacy tables that represent abandoned storage are absorbed into
> canonical tables. The migration produces a smaller, cleaner schema
> than the codebase has today — `_v2` suffixes and `default_*` legacy
> names disappear.
>
> **Naming convention decided by user 2026-10-11**: `reflections_v2`
> is renamed to **`reflections`** (drop the `_v2` once the migration
> is canonical). `default_reflections` content is absorbed into
> `reflections`. Legacy `reflections` (0 rows v0) drops after the
> merge. Same simplification applies to conversations
> (`conversations_v2` → `conversations`; `default_conversations` and
> legacy `conversations` drop). The session-buddy tables avoid the
> word `memory` in their content stores (only `reflection_access_log` is
> preserved, and that's an event log — a different concept from
> MEMORY.md or the renamed content tables).
> _See `.claude/decisions/wire-up-contract.md` for the wiring rules this
> plan follows._

## 1. Outcome

**User-observable change.** Every ID generated, stored, indexed, or
referenced by the 6 Bodai core components (mahavishnu, akosha, session-buddy,
crackerjack, oneiric, mcp-common) is a UUID7 hex string (32 lowercase
characters, no dashes). Every database column, file, log line, MCP
parameter, and CLI identifier that carried a ULID before this migration
carries a UUID7 after.

**Concrete success signal.** A single `python -c 'from uuid import uuid7,
print(uuid7().hex)'` from the active Python 3.14 venv of any core component
returns a value that:
1. round-trips through `uuid.UUID(value)` with `version == 7`,
2. is the primary-key value present on a freshly written row in that
   component's database after the wipe-and-restart.

## 2. Goals

1. **Single canonical generator.** `from uuid import uuid7` is the only ID
   generation entry point across the 6 components. No substrate wrapper.
2. **Substrate exposes UUID7 directly.** Replace `oneiric.core.ulid` with a
   minimal `oneiric.core.ids` module that wraps stdlib UUID7 for timestamp
   extraction and validation; no Crockford Base32 anywhere.
3. **Cross-system registry survives, format-changed.** The
   `system_id`-keyed reference store (formerly `oneiric.core.ulid_resolution`)
   stays; only its key format changes from ULID to UUID7.
4. **Storage columns are text-format-agnostic.** SQLite `TEXT` and DuckDB
   `VARCHAR` columns that held ULID strings now hold UUID7 hex strings.
   Column types do not change; row contents do.
5. **Archive is auditable.** Every `.db` and `.duckdb` file is copied (not
   moved) to `~/.local/state/bodai/db-archive/2026-10-11-uuid7-migration/`
   before deletion. A `manifest.json` records paths, sha256, and pre-migration
   row counts.
6. **MCP server feed-warmup is wired.** Per
   `feedback-oneiric-mcp-health-feed-warmup.md`, every Bodai MCP server must
   surface non-zero `cycles_total` after restart; pre-warm feeds at boot
   so post-restart `/health` checks don't transient-503.

## 3. Non-Goals

1. **No backwards compatibility for ID *generation*.** New IDs are UUID7
   only. ULID generation is removed, not deprecated. Per
   `feedback-no-backwards-compat-pre-1.0`.
2. **No row-by-row offline migration of stored ULIDs.** No bulk `UPDATE`
   sweep across existing rows changing ID columns in place. The format
   evolution is one of two paths:
   - **Wipe-and-recreate** for the regenerable stores (crackerjack
     SQLite, metrics, caches).
   - **Lazy dual-write migration** (two columns, one truth) for the
     irreplaceable stores (session-buddy `reflections_v2`,
     akosha warm store). New rows always write the UUID7 column;
     the legacy ULID column is read-only; reads lazily populate
     the UUID7 column on first access; the legacy column drops
     later when empty.
3. **No external API compatibility.** No compat shims on the wire (MCP
   tool parameter names, HTTP response shapes); if an external caller
   existed, that was already out of scope (Bodai is internal-first).
4. **No Prefect backend compatibility fix.** Per
   `prefect-adapter-bugs-2026-10-11`, the Prefect 3.x adapter integration
   is currently broken (`client.wait_for_flow_run` removed,
   timedelta-Pydantic coercion, `PREFECT_API_URL` gated on `api_key`).
   Per user message 2026-10-11, those bugs are being fixed in a
   parallel workstream. **This plan does not touch Prefect storage.**
   Prefect pids stay running; the user is the canonical owner.
5. **No new features on top of UUID7.** This is a migration, not a
   re-architecture. New functionality waits.
6. **No `git push` for bodai.** Per `feedback-bodai-push-is-user-controlled`,
   branches are created locally and merged per the trunk-based agent-review
   workflow; the user pushes.
7. **No PRs.** Per `bodai-pre-1.0-merge-policy.md`, this project is
   pre-1.0; merges go directly to `main` via the agent-review workflow,
   not via GitHub PR.

## 4. Current Findings

| Finding | Citation |
|---|---|
| `dhara`/`druva` removed from all 6 `pyproject.toml` manifests | `grep dhara\|druva /Users/les/Projects/{m,s,a,c,o,n}*/pyproject.toml` → empty |
| Three hand-rolled Crockford Base32 fallback encoders | `oneiric/core/ulid.py`, `session_buddy/core/ulid_generator.py`, `crackerjack/services/ulid_generator.py` |
| Dead `dhara` try-import branches in production source | `akosha/processing/knowledge_graph.py:15-25`, `oneiric/core/ulid.py:43-65`, `session_buddy/_dhara_substrate_compat.py:35`, `mahavishnu/core/_dhara_substrate_compat.py` (mirror) |
| `make_ulid()` in akosha returns `""` because druva is gone | `akosha/processing/knowledge_graph.py:34-36` |
| Substrate-compat shim pattern is force-loaded | Two files: `session_buddy/_dhara_substrate_compat.py`, `mahavishnu/core/_dhara_substrate_compat.py` — user decision 2026-10-11: delete both |
| Migration scripts still reference `dhara` | `mahavishnu/scripts/migrate_akosha_to_ulid.py:36,69,114` |
| session-buddy tasks system is already UUID7 | `session_buddy/mcp/tools/tasks_models.py:26,65` uses `from uuid import uuid7` |
| crackerjack ai_fix_event_bus is already uuid7 | `crackerjack/core/ai_fix_event_bus.py`, `models/issues.py`, `services/improvement_generator.py` |
| Storage holds ULID TEXT columns | Crackerjack V5/V6 (`crackerjack/storage/migrations/V5__ulid_migration*.sql`, `V6__ulid_contract*.sql`); session-buddy `reflections_v2.id VARCHAR` |
| MCP servers are running and holding file locks | pids 31310, 33486/33488, 35302, 37970 (crackerjack, akosha, session-buddy, mahavishnu) |
| Prefect backend storage path | `/Users/les/prefect/` and `/Users/les/.prefect/` (per `prefect-adapter-bugs-2026-10-11`, integration is broken) |
| `feedback-bodai-push-is-user-controlled` — `git push` for bodai needs explicit approval | memory `feedback-bodai-push-is-user-controlled.md` |
| `crackerjack-publish-stage-is-user` — never `crackerjack run -p` | memory `feedback-crackerjack-publish-stage-is-user.md` |
| Prefect bugs make the integration currently broken | memory `prefect-adapter-bugs-2026-10-11.md` |
| UUID7 is in stdlib on the project's Python target (3.14) | CLAUDE.md targets Python 3.14; `uuid.uuid7()` stdlib since 3.14 |

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-001
    title: "Single canonical ID format"
    description: "All new ID generation across the 6 components emits UUID7 hex. No ULID generation paths remain."
  - id: REQ-002
    title: "Substrate is a thin wrapper over stdlib"
    description: "`oneiric.core.ids.generate_id()` calls `uuid.uuid7()` directly with no fallback chain."
  - id: REQ-003
    title: "Archive-before-delete is mandatory"
    description: "Every `.db` and `.duckdb` file is copied to the archive location before any deletion. Deletion without a matching archive entry is a failure."
  - id: REQ-004
    title: "Cross-system registry survives"
    description: "`oneiric.core.system_registry` (replacing `ulid_resolution`) registers and resolves `system_id`-keyed references; key format is UUID7."
  - id: REQ-005
    title: "Substrate-compat shims are deleted"
    description: "`session_buddy/_dhara_substrate_compat.py` and `mahavishnu/core/_dhara_substrate_compat.py` are deleted (user decision 2026-10-11)."
  - id: REQ-006
    title: "Per-repo migration is independent"
    description: "Each of the 6 components has a standalone feature branch that merges to main independently of the others. Branches live under `~/.local/state/mahavishnu/worktrees/`; no `git push` from Claude Code per `feedback-bodai-push-is-user-controlled`."
  - id: REQ-007
    title: "No fresh ULID generation paths remain"
    description: "Grep for `from ulid import`, `from druva import`, `from dhara import`, `dhara_calltime`, `make_ulid`, `ulid_generator.generate_ulid`, `ULID(` across `mahavishnu/`, `akosha/`, `session_buddy/`, `crackerjack/`, `oneiric/`, `mcp_common/` returns zero matches (tests and `docs/` exempt, scoped per implementation phase). Read-time ULID acceptance in substrate's `is_valid_id()` is allowed under REQ-010."
  - id: REQ-008
    title: "MCP feed warmup after restart"
    description: "Per `feedback-oneiric-mcp-health-feed-warmup.md`, every Bodai MCP server's first write after restart is logged so `/health` `cycles_total` increments within the first scan window."
  - id: REQ-009
    title: "Worktree-based execution"
    description: "Per CLAUDE.md and `feedback-worktree-update-ref-drops-parallel-commits.md`, all work happens in `~/.local/state/mahavishnu/worktrees/<repo>/`; never edit a checked-out main directly."
  - id: REQ-010
    title: "Lazy dual-write migration for irreplaceable stores"
    description: "session-buddy `reflections_v2` and akosha `warm.db` keep a legacy ULID column AND a new `uuid7_id` column. Reads lazily backfill the UUID7 column on first access (single UPDATE in the same transaction as the read). The legacy column drops after all observable rows have been touched. Crackerjack SQLite and metrics/caches get wiped; lazy migration only applies where data is irreplaceable."
  - id: REQ-011
    title: "Crackerjack SQLite is wiped clean"
    description: "Crackerjack job/error/hook/test history is regenerable from CI runs. No lazy migration; the wipe in Phase 8 recreates empty tables with the V5 UUID7 schema."
  - id: REQ-012
    title: "Substrate accepts ULID only for read-time lazy migration"
    description: "`oneiric.core.ids.is_valid_id()` accepts UUID7 only (Phase 9 T1 collapsed is_valid_id to is_uuid7; the pre-2026-10-11 ULID read-time acceptance is removed); `is_uuid7()` is strict UUID7-only and is the canonical generator output check."
```</new_string>


## 5. Implementation Phases

### Phase 1: Archive (no code changes)

**Goal:** Snapshot every ULID-backed database file to a gitignored location
before any code deletion. The archive is the rollback surface.

**Tasks:**
1. Stop MCP servers to release file locks. `kill <pid>` for pids 31310,
   33486, 33488, 35302, 37970; let Prefect pids 29137 and 30233 keep
   running (separate concerns).
2. Create archive root: `mkdir -p
   ~/.local/state/bodai/db-archive/2026-10-11-uuid7-migration/{mahavishnu,akosha,session-buddy,crackerjack,oneiric,mcp-common}`
3. For each database file in the list below, `tar -czf` the original
   path into the matching component subdirectory under the archive
   root. Preserve the absolute path so de-archival restores 1:1.
4. Compute `sha256sum` of each archive tarball; record in
   `~/.local/state/bodai/db-archive/2026-10-11-uuid7-migration/MANIFEST.json`.
5. Pre-migration row counts: for every SQLite `*.db` file, count
   `SELECT COUNT(*) FROM <table>` on each known table; for every DuckDB
   `*.duckdb` file, run `duckdb -c "SELECT COUNT(*) FROM <table>"`. Append
   to `MANIFEST.json` under `row_counts`.
6. Verify archive: extract one tarball to `/tmp/archive-smoke/<file>` and
   `diff -q` against the source to confirm a clean copy.

**Database files to archive (verified by `find` 2026-10-11):**

| Component | Path |
|---|---|
| crackerjack | `/Users/les/databases/crackerjack.db` |
| crackerjack | `/Users/les/.crackerjack/metrics.db` |
| crackerjack | `/Users/les/.cache/crackerjack/metrics.db` |
| crackerjack | `/Users/les/.claude/data/crackerjack_integration.db` |
| crackerjack | `/Users/les/.local/state/development/session-buddy/crackerjack/skills.db` |
| crackerjack | `/Users/les/.crackerjack/adapter_learning.db` (under each project root) |
| session-buddy | `/Users/les/.claude/data/reflection.duckdb` |
| session-buddy | `/Users/les/.mahavishnu/outbox.duckdb` |
| session-buddy | `/Users/les/.claude/data/sessions.duckdb` |
| session-buddy | `/Users/les/.claude/data/knowledge_graph_*.duckdb` |
| akosha | `/Users/les/.akosha/state/metrics.db` |
| akosha | `/Users/les/Library/Application Support/akosha/warm/warm.db` |
| akosha | `/Users/les/Projects/akosha/data/warm/warm.db` |
| akosha | `/Users/les/.akosha/state/*.db` (any other state files) |
| _(prefect)_ | **excluded** — handled by parallel workstream |

**Exit criteria:**
- `MANIFEST.json` exists, contains one entry per archived file, validates as JSON.
- Every archive tarball's sha256 is recorded in the manifest.
- One tarball round-trips byte-perfect via `tar -xzf`.

#### Integration Contract — Phase 1 archive snapshot

- **Triggered from**: explicit user invocation of the migration (`yes, draft the plan` + go-ahead).
- **Returns to / updates**: `~/.local/state/bodai/db-archive/2026-10-11-uuid7-migration/` (one tarball per source file, plus `MANIFEST.json`).
- **Demonstrable by**: `jq '.files | length' ~/.local/state/bodai/db-archive/2026-10-11-uuid7-migration/MANIFEST.json` returns ≥ 12.
- **Rollback signal**: any archive tarball whose sha256 differs from the source's content hash (i.e. corruption between snapshot and restore). Wipe phase is blocked until this passes.
- **Observability added**: archive creation log line `"migration.archive.completed" files=<n> bytes=<n>` at the end of Phase 1.

### Phase 0: Migration scripts (write-only, dry-run against archive)

**Goal:** Write the offline migration scripts that produce a strict-UUID7
end state with consolidated/renamed tables. Scripts are written
separately from code changes so they can be reviewed, dry-run against
the Phase 1 archive, and merged as a discrete PR.

**Tasks:**
1. Worktree: `git worktree add
   ~/.local/state/mahavishnu/worktrees/session-buddy/ -b
   migration/2026-10-11-uuid7-only` (one worktree for both
   migration scripts and the post-migration code).
2. Create `session_buddy/migrations/2026_10_11_uuid7_consolidation/`:
   - `001_consolidate_conversations.sql`:
     1. `ALTER TABLE conversations RENAME TO conversations_legacy;` (move
        the v0 `conversations` table out of the way so the rename below
        doesn't collide with it).
     2. `ALTER TABLE conversations_v2 RENAME TO conversations;` (canonical
        name; matches the user-decided naming convention).
     3. `INSERT INTO conversations (...) SELECT ... FROM
        conversations_legacy WHERE id NOT IN (SELECT id FROM
        conversations);` — absorbs the 265 v0-unique rows. Backfills
        v2-only columns with NULL/default. Includes a `uuid7_id` backfill
        via a small Python helper (DuckDB Python extension or
        `read_csv(...).to_sql(...)` pattern). 935 + 265 = 1,200 distinct
        rows.
     4. `INSERT INTO conversations (...) SELECT ... FROM
        default_conversations WHERE id NOT IN (SELECT id FROM
        conversations);` — absorbs the 5 default-conversations rows
        (previously dropped silently by `004`; the parallel
        `default_reflections` IS absorbed in `002`, so the asymmetric
        treatment is fixed here). 1,200 + 5 = 1,205 distinct rows in
        the merged table.
   - `002_consolidate_reflections.sql` — DDL:
     - `ALTER TABLE reflections_v2 RENAME TO reflections;` (drop the `_v2`
       migration marker; `reflections` is now canonical)
     - `ALTER TABLE reflections ADD COLUMN usage_count INTEGER DEFAULT 0;`
     - `ALTER TABLE reflections ADD COLUMN last_used_at TIMESTAMP;`
     - `ALTER TABLE reflections ADD COLUMN confidence_score FLOAT
       DEFAULT 0.5;`
     - `ALTER TABLE reflections ADD COLUMN conversation_id VARCHAR;`
     - `INSERT INTO reflections (id, content, embedding, tags, metadata,
       usage_count, last_used_at, confidence_score, insight_type,
       subcategory, created_at, updated_at, ...)
       SELECT uuid7()::VARCHAR, content, embedding, tags, metadata,
       usage_count, last_used_at, confidence_score, insight_type,
       subcategory, created_at, updated_at, conversation_id
       FROM default_reflections;` — absorbs 1,232 rows.
     - `DROP TABLE default_reflections;`
   - `003_drop_legacy_conversations.sql` — `DROP TABLE
     conversations_legacy;` (renamed from `conversations` in `001`; its
     rows are already absorbed into the new `conversations` via
     `001` step 3). The original `conversations` drop target is
     renamed to avoid colliding with the canonical `conversations`
     (which is the renamed v2).
   - `004_drop_legacy_default_conversations.sql` — `DROP TABLE
     default_conversations;` (5 rows; merged via `001` step 4).
   - `005_drop_legacy_reflections.sql` — `DROP TABLE reflections;`
     (0 rows; vestigial reads only).
   - `006_drop_vestigial.sql` — `DROP TABLE access_log_v2; DROP TABLE
     query_cache_l2; DROP TABLE schema_meta; DROP TABLE
     schema_migrations;`
   - `007_id_swap_load_bearing.sql` — for `conversations` (merged),
     `reflections` (renamed-and-merged), `code_graphs`, `session_windows`,
     **`memory_access_log`** (not `reflection_access_log` — the
     production schema in `session_buddy/memory/schema_v2.py` defines
     `memory_access_log`; the manifest confirms this is the actual
     table name with 3 real rows): rename `id` to `legacy_id`, add
     `uuid7_id TEXT NOT NULL`, backfill via `uuid7()` UDF, drop
     `legacy_id`, rename `uuid7_id` to `id`, rebuild PK constraints and
     indexes. The `reflection_access_log` reference in the original
     plan was a stale name (the rename pass didn't propagate to the
     migration-script descriptions; this fixes it).
   - `008_id_swap_dormant_active.sql` — same pattern for
     `causal_links`, `distilled_skills`, `cross_repo_work_v2`,
     `user_models`, `reflection_entities`, `reflection_relationships`,
     `reflection_subcategories`, `reflection_promotions`, `reflection_provenance`,
     `archived_subcategories`, `category_evolution_snapshots`,
     `content_fingerprints`, `project_dependencies`, `project_groups`,
     `reflection_tags`, `result_interactions`, `rewritten_queries`,
     `session_links`, `usage_metrics_summary`,
     `intelligence_cross_project_patterns`,
     `intelligence_learned_skills`,
     `intelligence_pattern_applications`,
     `intelligence_pattern_instances`,
     **`memory_entities`, `memory_relationships`, `memory_promotions`,
     `memory_provenance`, `memory_subcategories`** (the 5 V2
     canonical tables from `session_buddy/memory/schema_v2.py` that
     were missing from the original `008` list; all 0 rows today, so
     the migration produces their UUID7 schema for the next writer)
     — these are empty today but the migration produces their UUID7
     schema for the next writer. (`memory_access_log` is in `007`
     because it has 3 real rows and is load-bearing; the other 5
     `memory_*` tables are 0-row and dormant.)
   - `009_drop_sessions_duckdb.sql` — touch `sessions.duckdb`'s
     connection string to drop the file entirely (`rm` rather than
     DDL; the underlying DuckDB engine handles it). See Phase 0.5
     execution step.
   - `010_drop_akosha_warm_mahavishnu_outbox.sql` — same; `rm` step.
3. Each `*.sql` file is paired with a small `*.py` test under
   `tests/integration/test_uuid7_consolidation.py`:
   - `test_conversations_merged` — confirms 1,205 distinct rows
     (935 V2 + 265 V0-unique + 5 default_conversations)
   - `test_reflections_renamed` — confirms `reflections` table exists with
     `reflections_v2` columns plus the four absorbed columns
   - `test_legacy_reflections_dropped`
   - `test_uuid7_pk_format` — confirms every PK in preserved tables
     round-trips through `uuid.UUID(v).version == 7`
4. Dry-run: extract the Phase 1 archive to a temp dir, run each
   script against a fresh DuckDB seeded from the extracted file;
   verify row counts match expectations.

**Exit criteria:**
- All 10 SQL files reviewable in one PR.
- Dry-run against the archive confirms row count deltas match the
  plan: `conversations` ends at 1,205; `reflections` ends at 1,485;
  every preserved table has UUID7 PKs.
- Tests pass.
- No references to `reflections_v2` or `default_reflections` survive
  in the script's drop statements — DROP must reach the renamed
  table.

#### Integration Contract — Phase 0 migration scripts

- **Triggered from**: explicit user invocation of the migration phase.
- **Returns to / updates**: `session_buddy/migrations/2026_10_11_uuid7_consolidation/*.sql` and the matching test file.
- **Demonstrable by**: dry-run against Phase 1's archive produces the expected row counts and table presence; `pytest tests/integration/test_uuid7_consolidation.py` passes.
- **Rollback signal**: any test failure means the script is wrong — revert the PR and don't promote to Phase 0.5.
- **Observability added**: each migration step logs a structured `migration.<step>.rows_affected=<n>` line at the end; the consolidated test prints the canonical final state.

### Phase 0.5: Maintenance window (offline migration run)

**Goal:** Stop MCPs holding database locks; apply Phase 0 scripts to the
live `reflections.duckdb`; verify end state matches dry-run; restart.

**Tasks:**
1. Stop MCP servers: `kill <sb_pid> <akosha_pid>` (crackerjack and
   mahavishnu can stay running; they don't hold `reflection.duckdb`
   locks).
2. Back up `~/.claude/data/reflection.duckdb` to the Phase 1 archive
   pattern (already done; archive is the rollback surface).
3. Run each Phase 0 SQL file in numeric order against the live DB
   using `duckdb <reflection.duckdb> < 00X_*.sql`.
4. For Python helpers that use `uuid7()` UDF, run them via
   `python3 -m session_buddy.migrations.<helper>` which the script
   delegates to.
5. Verify state:
   - `duckdb ~/.claude/data/reflection.duckdb -c ".tables"` shows the
     expected consolidated table list (24 tables: `conversations`,
     `reflections`, `causal_links`, ..., `usage_metrics_summary`).
   - `SELECT COUNT(*) FROM reflections;` returns ≥ 1,485.
   - `SELECT COUNT(*) FROM conversations;` returns 1,205.
   - `SELECT id FROM reflections LIMIT 5` shows UUID7 hex strings.
   - No remaining reference to `reflections_v2` or `default_reflections`.
6. `rm -f /Users/les/.claude/data/sessions.duckdb*` (the duplicate
   file dropped in `009_drop_sessions_duckdb.sql`).
7. `rm -rf /Users/les/Library/Application\ Support/akosha/warm`
   (the dead warm dir; untracked, no live writes).
8. `rm -f /Users/les/.mahavishnu/outbox.duckdb*`.
9. Restart MCP servers: `launchctl load` the relevant plists OR
   use `.local/state/mcp/scripts/launch_with_healthcheck.sh`; verify
   `mcp__<server>__get_liveness` returns 200.
10. Smoke test that the new `reflections` table accepts new writes
    with UUID7 PKs:
    `mcp__session-buddy__store_reflection(content="post-migration smoke",
    tags=["reflections-test"])` then `SELECT id FROM reflections WHERE
    tags @> ARRAY['reflections-test']` returns one row with a UUID7 hex
    PK.

**Exit criteria:**
- Table list matches the planned `reflections`-canonical schema.
- Row counts match the plan.
- New writes produce UUID7 PKs.
- MCP servers respond 200.
- Original data is preserved (1,485 reflections + 1,205 conversations
  + dormant tables populated as before).
- No legacy `default_reflections`, `default_conversations`,
  `reflections`, `reflections_v2`, `conversations` (old v0),
  `access_log_v2`, `query_cache_l2`, `schema_meta`,
  `schema_migrations` tables remain — they were dropped in
  Phases 0 through 0.5.

#### Integration Contract — Phase 0.5 maintenance window

- **Triggered from**: user activation of the migration window (explicit go for a low-traffic moment).
- **Returns to / updates**: live `reflection.duckdb`; the Phase 1 archive tarball.
- **Demonstrable by**: table list, row counts, and UUID7 PK verification queries all return the planned values.
- **Rollback signal**: any unexpected error during script execution OR row count mismatch → restore from archive tarball: `tar -xzf <archive-tarball> -C /Users/les/.claude/data/`; restart MCPs; investigate.
- **Observability added**: structured log line `"migration.phase_0_5.<step>.rows_affected=<n> elapsed_ms=<n>"` per step; a final `"migration.phase_0_5.complete"` summary log on success.

### Phase 2: Substrate (oneiric)

**Goal:** Replace `oneiric/core/ulid*.py` with a minimal UUID7 facade,
**plus** the read-time ULID acceptance needed by Option D's lazy
dual-write migration (REQ-010, REQ-012).

**Tasks:**
1. Worktree: per CLAUDE.md, `git worktree add
   ~/.local/state/mahavishnu/worktrees/mahavishnu/ -b
   migration/2026-10-11-uuid7-only` from the mahavishnu repo root.
   Inside oneiric, create the oneiric worktree at
   `~/.local/state/mahavishnu/worktrees/oneiric/`.
2. In the oneiric worktree:
   - **Delete** `oneiric/core/ulid.py` (399 LOC).
   - **Delete** `oneiric/core/ulid_resolution.py` (210 LOC).
   - **Delete** `oneiric/core/ulid_migration.py` (241 LOC).
   - **Delete** `oneiric/core/ulid_collision.py` (114 LOC).
   - **Delete** `tests/test_ulid_*.py`, `tests/core/test_ulid_*.py`,
     `tests/core/test_core_coverage_gaps.py` (ULID-specific test
     surface).
   - **Delete** `benches/test_ulid_resolution_performance.py`.
   - **Create** `oneiric/core/ids.py` containing:
     - `generate_id() -> str` — UUID7 hex (`uuid.uuid7().hex`).
     - `is_uuid7(value: str) -> bool` — strict UUID7 check (canonical
       generator output check).
     - `is_valid_id(value: str) -> bool` — accepts both UUID7 hex
       AND 26-char Crockford Base32 ULID (read-time acceptance for
       legacy rows; not a generator output). REQ-012.
     - `extract_timestamp_ms(value: str) -> int` — UUID7 timestamp
       extraction per RFC 9562 bit layout (`UUID(value).int >> 80`).
     - `extract_timestamp_seconds`.
     - `ConfigTraceability` — rewritten to use UUID7 keys instead of
       ULID strings.
   - **Create** `oneiric/core/system_registry.py` — registry-shaped
     module keyed by `system_id`. APIs: `register`, `find_entities_by_system`,
     `find_related_entities`, `export`, `import_from`, `get_stats`.
     The ULID-shaped `register_reference` becomes `register(entity_id,
     system_id, metadata)` where `entity_id` is UUID7.
3. Update any intra-oneiric callers of `from oneiric.core.ulid import
   ...` to import from `oneiric.core.ids` and `oneiric.core.system_registry`.
4. Run `crackerjack run -v` (not `-p`); per
   `feedback-crackerjack-publish-stage-is-user`, debug only.
5. Merge to `main` via the trunk-based agent-review workflow.
   **No PR** (per `bodai-pre-1.0-merge-policy.md`).
   **No `git push`** (per `feedback-bodai-push-is-user-controlled`); the
   user pushes.

**Exit criteria:**
- `pytest tests/` passes.
- `crackerjack run -v` passes.
- `grep -rE "from oneiric.core.ulid|from oneiric.core.ulid_resolution|from oneiric.core.ulid_migration|from oneiric.core.ulid_collision" oneiric/` returns zero.
- `python -c 'from oneiric.core.ids import generate_id; print(generate_id())' | xargs -I{} python -c 'import uuid; print(uuid.UUID("{}").version)'` prints `7`.
- `python -c 'from oneiric.core.ids import is_valid_id; print(is_valid_id("01ARZ3NDEKTS6PQRYF"))'` prints `False` (ULID read-time acceptance removed; see Phase 9 T1).
- `python -c 'from oneiric.core.ids import is_uuid7; print(is_uuid7("01ARZ3NDEKTS6PQRYF"))'` prints `False` (strict UUID7-only check rejects ULIDs).

#### Integration Contract — Phase 2 substrate

- **Triggered from**: `from oneiric.core.ids import generate_id` (called by mahavishnu, crackerjack, akosha, session-buddy downstream — these callsites are updated in Phases 3-6).
- **Returns to / updates**: `oneiric/core/ids.py` + `oneiric/core/system_registry.py` modules; the deleted `ulid*.py` modules' `__all__` exports are no longer importable.
- **Demonstrable by**: `python -c 'from oneiric.core.ids import generate_id; print(generate_id())'` returns 32 lowercase hex chars; `from uuid import UUID; UUID(generate_id()).version == 7`. The legacy acceptance path is also verified by `is_valid_id(<ulid_string>) == True` and `is_uuid7(<ulid_string>) == False`.
- **Rollback signal**: any non-version-7 UUID emitted by `generate_id()` (would indicate stdlib regression or a mistaken hand-roll). On detection, `git revert` to the oneiric pre-migration commit; do not delete archived databases.
- **Observability added**: structured log line `"oneiric.ids.generated" uuid_version=7` per call (sampled at 1/100 to keep volume low).

### Phase 3: crackerjack

**Goal:** Schema migration from ULID PKs to UUID7 PKs; UUID7 emitted from
production call sites.

**Tasks:**
1. Worktree: `git worktree add ~/.local/state/mahavishnu/worktrees/crackerjack/ -b migration/2026-10-11-uuid7-only`.
2. **Delete** `crackerjack/services/ulid_generator.py`.
3. **Delete** `crackerjack/storage/migrations/V5__ulid_migration__up.sql`,
   `V5__ulid_migration__down.sql`, `V6__ulid_contract__up.sql`,
   `V6__ulid_contract__down.sql`.
4. **Create** `crackerjack/storage/migrations/V5__uuid7_contract__up.sql`
   and matching `__down.sql`. New schema:
   - `jobs.job_id TEXT PRIMARY KEY` (UUID7 32-hex).
   - `errors.error_ulid TEXT` → rename to `error_id TEXT`.
   - `hook_executions.hook_ulid TEXT` → rename to `hook_id TEXT`.
   - `test_executions.test_ulid TEXT` → rename to `test_id TEXT`.
   - `individual_test_executions.test_execution_ulid TEXT` → rename to `execution_id TEXT`.
   - All FK columns referencing the old ULID columns are renamed alongside.
5. **Update** `tests/unit/services/test_ulid_generator.py`,
   `tests/unit/services/test_ulid_generator_direct.py`,
   `tests/services/test_ulid_generator.py` — delete or rewrite as
   UUID7 tests (`tests/unit/services/test_uuid7_generator.py` if needed).
6. **Update** the three already-UUID7 files (`core/ai_fix_event_bus.py`,
   `models/issues.py`, `services/improvement_generator.py`) — verify the
   UUID7 schema keys align (no `from uuid_utils import uuid7` mismatch).
7. **Update** any production call sites that imported
   `from ...ulid_generator import generate_ulid` to
   `from uuid import uuid7; uuid7().hex`.
8. Run `crackerjack run -v` on the crackerjack venv.
9. Open crackerjack PR.

**Exit criteria:**
- All `crackerjack/storage/migrations/V*.sql` migrations are reversible
  (the new V5 has a clean `down`).
- `pytest tests/` passes.
- `grep -rE "ulid_generator|ulid_migration|ulid_contract|generate_ulid" crackerjack/` (excluding `docs/`) returns zero.

#### Integration Contract — Phase 3 crackerjack

- **Triggered from**: `crackerjack run` and `crackerjack services ulid_generator` legacy import paths are gone; the canonical entry is `from uuid import uuid7` direct call.
- **Returns to / updates**: `crackerjack/storage/migrations/V5__uuid7_contract__up.sql` schema (PK columns); the deleted `services/ulid_generator.py` module.
- **Demonstrable by**: `crackerjack run -v`; `sqlite3 /Users/les/databases/crackerjack.db ".schema jobs"` shows `job_id TEXT PRIMARY KEY`; `crackerjack run --job-id $(python -c 'from uuid import uuid7; print(uuid7())')` succeeds end-to-end.
- **Rollback signal**: any `INSERT OR FAIL` or `IntegrityError` on `jobs` between migration and the wipe phase (Phase 8) means the schema is hot; revert the migration and stop MCP servers.
- **Observability added**: per-insert log `"crackerjack.jobs.row_written" job_id=<uuid7_hex>` for the first 100 rows after migration (sampled thereafter).

### Phase 4: akosha

**Goal:** **Lazy dual-write migration** for the warm store — keep
existing ULID rows, transition via read-time backfill (Option D,
REQ-010). Generator switches to UUID7 only.

**Tasks:**
1. Worktree: `git worktree add ~/.local/state/mahavishnu/worktrees/akosha/ -b migration/2026-10-11-uuid7-only`.
2. **Update** `akosha/processing/knowledge_graph.py`:
   - **Delete** `_load_ulid_generator()` (lines 15-25).
   - **Delete** `_ulid_impl` module-level global.
   - **Replace** `make_ulid()` with `from uuid import uuid7; uuid7().hex`.
   - Existing entity-ID fallbacks (`system:{system_id}`,
     `user:{user_id}`, `project:{project}`) stay — they're slug-shaped
     identifiers, separate concern.
3. **Update** `akosha/storage/warm_store.py` (and any sibling query
   helpers) to implement the lazy dual-write pattern:
   - Add a `uuid7_id TEXT` column to the warm store schema (CREATE
     TABLE migration is idempotent — `ALTER TABLE ... ADD COLUMN`
     if the table pre-exists without the column).
   - Add a `UNIQUE` index on `uuid7_id` (NULL values don't conflict
     per SQLite/DuckDB semantics).
   - On every read of a row whose `uuid7_id` is `NULL` but `entity_id`
     is non-NULL: synthesize a UUID7 (`uuid.uuid7().hex`), `UPDATE`
     the row in the same transaction, return the row with `uuid7_id`
     populated.
   - Writes from `make_ulid()` always populate both columns.
   - Slug-shaped `entity_id` rows (rows where `entity_id` matches
     `^[a-z]+:[a-zA-Z0-9._-]+$`) skip the `uuid7_id` population
     entirely — slugs stay slugs.
4. **Verify** the legacy `make_ulid()` shape (Crockford Base32 ULID
   string) is **never produced again** by the substrate: `grep -rE
   'ulid_generator|generate_ulid|make_ulid|ulid\.new' akosha/` returns zero.
   (The old ULID rows in the warm store remain readable for the
   duration of the lazy migration window.)
5. Run `crackerjack run -v`.
6. Merge to `main` via the trunk-based agent-review workflow.
   **No PR. No `git push` from Claude Code.**

**Exit criteria:**
- `pytest tests/` passes.
- `grep -rE "ulid|ULID|druva|dhara" akosha/` (excluding `docs/` and `__pycache__`) returns zero in source — but the schema column may still exist.
- `python -c 'from akosha.processing.knowledge_graph import make_ulid; v = make_ulid(); import uuid; print(uuid.UUID(v).version)'` prints `7`.
- Reading any pre-migration ULID row from `warm.db` returns a populated `uuid7_id` after first read (test with a fixture).

#### Integration Contract — Phase 4 akosha

- **Triggered from**: any `GraphEntity(entity_id=..., entity_type=..., ...)` constructor call in `akosha/processing/knowledge_graph.py` (writes); any warm-store read (reads).
- **Returns to / updates**: `akosha/data/warm/warm.db` entity rows — legacy `entity_id` ULID values remain in the legacy column; new rows have UUID7 in `uuid7_id`; reads lazily populate `uuid7_id` for legacy rows.
- **Demonstrable by**: `python -c 'from akosha.processing.knowledge_graph import make_ulid; v = make_ulid(); import uuid; print(uuid.UUID(v).version)'` prints `7`. Manual smoke test: open a pre-migration warm.db, read an ULID-shaped row, observe `uuid7_id` populated; second read returns the cached value with no rewrite.
- **Rollback signal**: warm-store read reports `IntegrityError` (would indicate the dual-write transaction is unsound). Roll back the akosha branch; the warm store data is intact because the legacy `entity_id` column was never rewritten.
- **Observability added**: log `"akosha.entity.dual_written" legacy_entity_id=<ulid> uuid7_id=<hex>` for the first 50 backfill events after migration, then sampled.

### Phase 5: session-buddy

**Goal:** Apply the post-Phase-0 code changes that point session-buddy's
production code at the new `reflections` table and the UUID7-only
substrate. Phase 0 already migrated the schema; this phase rewrites the
read/write paths and deletes the legacy ULID machinery.

**Tasks:**
1. Worktree: same `migration/2026-10-11-uuid7-only` branch as Phase 0
   (continuation work; the offline migration scripts PR and this code
   PR land as one combined change OR as a stacked PR — whichever the
   review prefers).
2. **Delete** `session_buddy/core/ulid_generator.py` (full file).
3. **Delete** `session_buddy/_dhara_substrate_compat.py` (per user
   decision 2026-10-11 — substrate-compat shim goes; the
   `dhara_calltime()` import path dies with it).
4. **Delete** `session_buddy/mcp/tools/tasks_legacy.py` (the
   legacy-ULID-vs-UUID7 split exists only because ULID existed; with
   UUID7 only, `tasks_models.py` is the single path).
5. **Update** `session_buddy/memory/causal.py`:
   - **Delete** `from ulid import ULID`.
   - **Replace** `link_id = str(ULID())` (lines 158, 230) with
     `from uuid import uuid7; link_id = uuid7().hex`.
6. **Update** `session_buddy/adapters/reflection_adapter_oneiric.py`:
   - **Delete** `from ulid import ULID`.
   - **Update** every SELECT/INSERT against the legacy
     `reflections_v2` table to use the renamed `reflections` table. The
     schema is the same shape post-Phase-0; only the table name
     differs.
   - Update write path to call `uuid7().hex` for new rows.
   - **No dual-write codepath is needed.** Phase 0 already converted
     every existing row to a UUID7 `id`, so reads simply return
     UUID7 hex strings. The legacy `id` column doesn't exist anymore
     — it was renamed to `uuid7_id` and backfilled, then renamed
     back to `id`. The current `id` IS the UUID7.
7. **Update** `session_buddy/skills/distiller.py`:
   - **Delete** `from ulid import ULID`.
   - **Replace** `str(ULID())` with `uuid7().hex`.
8. **Update** `session_buddy/mcp/tools/tasks_storage.py`:
   - The tasks metadata schema becomes UUID7-only; the schema
     comment block no longer mentions ULID.
9. **`session_buddy/mcp/tools/tasks_models.py`** already UUID7 — no
   change.
10. **Update** consumer modules currently importing `dhara_calltime`:
    - `session_buddy/mcp/tools/session/channel_session_state_tools.py:38`
      — delete the `from session_buddy._dhara_substrate_compat import
      dhara_calltime` import; delete the `dhara_calltime("get")`
      graceful-degrade path that calls it.
    - `session_buddy/channel/state_writer.py:37` — same.
11. **Update / delete** ULID-related tests:
    - **Delete** `tests/unit/test_ulid_generator.py`.
    - **Update** `tests/unit/test_reflection_provenance.py` to assert
      UUID7 format in the source-session-id / source-artifact-uri
      tags.
    - **Update** `tests/unit/test_session_manager_high_impact.py`.
    - **Update** `tests/unit/memory/test_causal.py` (ULID import → UUID7).
    - **Update** `tests/integration/test_causal_chains.py`.
    - **Update** `tests/integration/test_skill_distillation.py`.
    - **Update** `tests/integration/test_delete_conversation_cascade.py`.
    - **Delete** `scripts/run_ulid_migration.py` (the legacy offline
      ULID script is no longer relevant post-Phase-0).
    - **Add** new tests verifying the canonical `reflections` table:
      - `tests/integration/test_reflections_table.py` — schema check
        (every column on the v2 reflections table is present;
        plus the four absorbed columns from `default_reflections`);
        UUID7 PK format on every row; foreign-key integrity from
        `conversation_id` to `conversations.id`.
      - `tests/integration/test_conversations_merged.py` — confirms
        1,205 distinct rows; UUID7 PK; legacy `conversations`
        legacy v0 table no longer exists.
12. Run `crackerjack run -v`.
13. **Delete** `session_buddy/storage/migrations/V5__ulid_migration__up.sql`,
    `V5__ulid_migration__down.sql`, `V6__ulid_contract__up.sql`,
    `V6__ulid_contract__down.sql`. These are ULID hedge migrations
    (V5 added `conversation_ulid` / `reflection_ulid` / `code_graph_ulid`
    shadow columns; V6 renamed `id` → `*_ulid` and added a new `id`
    column). Phase 0 already converted every row to UUID7 and Phase 5
    step 2–6 removes the ULID generator; the V5/V6 hedge files become
    cargo-culted dead code. (Phase 3 already deletes the parallel
    files in `crackerjack/storage/migrations/`; this is the
    session-buddy side of the same cleanup.) The V1–V4 skill-table
    migrations stay — they're unrelated to the ULID substrate (and
    are slated for cold-archive deletion by Shared Oneiric Substrate
    Phase B in 90 days).
14. Merge to `main` via the trunk-based agent-review workflow.
    **No PR. No `git push` from Claude Code.**

**Exit criteria:**
- `pytest tests/` passes (including the new `reflections`-table tests).
- `grep -rE "from ulid import|_dhara_substrate_compat|ulid_generator|generate_ulid|reflections_v2|default_reflections" session_buddy/` (excluding `docs/` and `migrations/` — those still have the legacy names) returns zero in **production** source code.
- New reflections created via `mcp__session-buddy__store_reflection` round-trip with `id` being UUID7 hex only (no legacy column).
- `duckdb ~/.claude/data/reflection.duckdb -c "SELECT COUNT(*) FROM reflections"` returns ≥ 1,485.
- `duckdb ~/.claude/data/reflection.duckdb -c "SELECT COUNT(*) FROM conversations"` returns 1,205.
- Pre-migration rows from the archive tarball still returnable through `mcp__session-buddy__quick_search` after the migration (history preserved).

#### Integration Contract — Phase 5 session-buddy

- **Triggered from**: `mcp__session-buddy__store_reflection(...)` (writes); `mcp__session-buddy__query_session(...)` and `mcp__session-buddy__quick_search(...)` (reads).
- **Returns to / updates**: `~/.claude/data/reflection.duckdb` reads/writes against the renamed `reflections` table; legacy ULID machinery removed from production code.
- **Demonstrable by**: insert a memory via `mcp__session-buddy__store_reflection`; verify the returned record has `id` as a 32-char lowercase hex string that round-trips through `uuid.UUID(v).version == 7`; query the memory back; verify `id` matches.
- **Rollback signal**: any `IntegrityError`, 5xx, or schema-missing table. Revert the session-buddy branch; data is preserved in the Phase 1 archive tarball.
- **Observability added**: `session-buddy.memory.created` log on each new memory write, with `id=<uuid7_hex>`. `session-buddy.query_session` logs each query with row-count and latency.

### Phase 6: mahavishnu

**Goal:** Repoint substrate consumers; remove ULID from scripts and adapters.

**Tasks:**
1. Worktree: `git worktree add ~/.local/state/mahavishnu/worktrees/mahavishnu/ -b migration/2026-10-11-uuid7-only` (already exists from Phase 2 substrate work).
2. **Delete** `mahavishnu/core/_dhara_substrate_compat.py` (per user
   decision 2026-10-11).
3. **Delete** `mahavishnu/scripts/migrate_akosha_to_ulid.py`,
   `migrate_crackerjack_to_ulid.py`, `migrate_session_buddy_to_ulid.py`.
4. **Update** `mahavishnu/distill/distiller.py`:
   - **Delete** `from ulid import ULID  # ty: ignore[unresolved-import]`.
   - **Replace** `str(ULID())` with `uuid7().hex` at lines 202 and 261.
5. **Update** `mahavishnu/scripts/tool_frontmatter_validator.py`:
   - **Replace** the `generate_ulid()` shim (lines 29+) with
     `from uuid import uuid7; return uuid7().hex`.
   - **Replace** `ULID_PATTERN = re.compile(r"^[0-9A-Z]{26}$")` (line
     109) with a UUID7 hex pattern
     `^[0-9a-f]{32}$` and UUID version check.
6. **Update** `mahavishnu/core/workflow_models.py`:
   - `from oneiric.core.ulid import generate as _generate_ulid` →
     `from oneiric.core.ids import generate_id`.
   - `_generate_ulid()` → `generate_id()`.
7. **Update** `mahavishnu/core/metrics_schema.py`,
   `metrics_collector.py`, `unified_orchestrator.py`,
   `cost_optimizer.py`, `events/canonical.py`, `distill/schema.py`,
   `cli/rollback_cli.py`, `adapters/ai/pydantic_ai_adapter.py` —
   any reference to "ULID" in docstrings/identifiers becomes "UUID7";
   any `from oneiric.core.ulid import ...` becomes
   `from oneiric.core.ids import ...`.
8. **Update** `mahavishnu/core/jot/*` (jot identifiers) — search for
    any ULID-shaped identifiers in jot storage.
9. Run `crackerjack run -v`. Open mahavishnu PR.

**Exit criteria:**
- `pytest tests/` passes.
- `grep -rE "from ulid import|from druva import|from dhara import|ulid_generator|make_ulid|dhara_substrate_compat|_generate_ulid" mahavishnu/` (excluding `docs/` and `.venv/`) returns zero.
- A mahavishnu-triggered workflow via `mcp__mahavishnu__pool_route_execute` writes to the workflow_models store with UUID7 keys.

#### Integration Contract — Phase 6 mahavishnu

- **Triggered from**: `mcp__mahavishnu__pool_route_execute`, `mcp__mahavishnu__launch_worker`, `distill_distill_workflow` CLI.
- **Returns to / updates**: `workflow_models.WorkflowExecution.workflow_id` field; `metrics_schema.ExecutionRecord.id`, `metrics_schema.RoutingDecision.id`; all stored records get UUID7 keys.
- **Demonstrable by**: `mahavishnu pool route --prompt "smoke-test-uuid7"` followed by `duckdb outbox.duckdb -c "SELECT workflow_id FROM workflows ORDER BY created_at DESC LIMIT 1"` shows a 32-char hex string.
- **Rollback signal**: `WorkflowExecution.create` IntegrityError on UUID7 schema column; rollback by reverting Phase 6 PR before Phase 8 wipe.
- **Observability added**: `mahavishnu.workflow.created` log includes `workflow_id=<uuid7_hex>` (sampled).

### Phase 7: mcp-common

**Goal:** Verify and confirm no ULID.

**Tasks:**
1. Worktree: `git worktree add ~/.local/state/mahavishnu/worktrees/mcp-common/ -b migration/2026-10-11-uuid7-only`.
2. `grep -rE "ulid|ULID|druva|dhara" mcp_common/` (excluding `docs/`,
   `tests/` if unrelated, `.venv/`) — record findings.
3. If zero matches: delete the worktree, close phase as no-op.
4. If matches: update per Phase 6 pattern.

**Exit criteria:** as Phase 7 confirms/closes.

#### Integration Contract — Phase 7 mcp-common

- **Triggered from**: none if no ULID usage.
- **Returns to / updates**: none if no ULID usage.
- **Demonstrable by**: `grep -rE "ulid|ULID" mcp_common/` returns zero (post-clean).
- **Rollback signal**: not applicable.
- **Observability added**: none.

### Phase 8: Selective wipe (after all branches merged)

**Goal:** Wipe the regenerable stores only. Preserve the
irreplaceable stores (session-buddy `reflections_v2`, akosha warm)
because Option D's lazy dual-write migration in Phase 5 and Phase 4
is in flight on those tables.

**Tasks:**
1. **Verify archive integrity** (final pre-wipe sanity): re-run
   `sha256sum` against `MANIFEST.json` for every tarball; every
   match.
2. **Stop MCP servers** (release SQLite locks):
   `kill 31310 33486 33488 35302 37970`. Note: akosha and
   session-buddy MCPs are stopped **even though their data is
   preserved**, because the migration finishes on next read; they
   must come up under the new substrate to read correctly.
3. **Wipe the regenerable database files** (REQ-011):
   - **crackerjack SQLite** (the wipe target per Option D): `rm -f
     /Users/les/databases/crackerjack.db /Users/les/.crackerjack/metrics.db
     /Users/les/.cache/crackerjack/metrics.db /Users/les/.claude/data/crackerjack_integration.db
     /Users/les/.local/state/development/session-buddy/crackerjack/skills.db`.
     The crackerjack SQLite recreates from V5 UUID7 on first
     write.
   - **All `.crackerjack/adapter_learning.db` files** under each
     project root (regenerable cache).
4. **Do NOT touch Prefect.** Per user message 2026-10-11, Prefect
   storage is being handled by a parallel workstream
   ("prefect bugs are currently being fixed in another session"),
   and the current Prefect data is "old/test demo data" that does
   not need preservation. Prefect pids 29137 and 30233 stay
   running through Phase 8; the user is the canonical owner.
5. **Do NOT wipe** (these are lazy-migration targets):
   - `~/.claude/data/reflection.duckdb` (session-buddy reflections_v2
     — Phase 5 dual-write is in flight).
   - `/Users/les/Library/Application Support/akosha/warm/warm.db` and
     `/Users/les/Projects/akosha/data/warm/warm.db` (Phase 4
     dual-write is in flight).
   - `/Users/les/.mahavishnu/outbox.duckdb`, etc. (any other
     session-buddy-backed DuckDB file). The lazy migration reads
     these on first access to backfill `uuid7_id`.
6. **Restart MCP servers** via `launchctl load` plists OR via the
   `.local/state/mcp/scripts/launch_with_healthcheck.sh` paths; verify
   `mcp__<server>__get_liveness` returns 200 across all five.
7. **Pre-warm feeds** to satisfy `feedback-oneiric-mcp-health-feed-warmup`:
   each Bodai MCP server writes one deterministic entry on boot
   so `cycles_total >= 1` immediately after restart.
8. **Smoke test happy path** (confirms writes use UUID7 going forward):
   a. `crackerjack run -v` from any repo.
   b. `mcp__session-buddy__store_reflection(content="...", tags=["migration-smoke"])` then
      `mcp__session-buddy__quick_search(query="migration-smoke")` — return the just-written reflection (asserts `id` is UUID7 hex).
   c. `mcp__mahavishnu__pool_route_execute(prompt="smoke-test")` end-to-end.
   d. `mcp__akosha__search_all_systems(query="migration-smoke")` returns non-empty (asserts `entity_id` is UUID7 hex).
9. **Smoke test the lazy migration path** (confirms legacy rows are still queryable):
   a. `mcp__session-buddy__query_session(<one legacy ULID reflection_id>)` returns the row and records a `uuid7_id` backfill event.
   b. `duckdb ~/.claude/data/reflection.duckdb -c "SELECT id, uuid7_id FROM reflections_v2 WHERE id LIKE '01%'"` lists backfilled rows where `uuid7_id IS NOT NULL`.
   c. Repeat the lookup; the second read must NOT log a new `dual_written` event (idempotent guard).
   d. Repeat the smoke for `akosha/data/warm/warm.db`.

**Exit criteria:**
- Wiped DBs are 1:1 with the wipe list in the manifest.
- `mcp__<server>__get_liveness` returns 200 for all five core Bodai MCP servers.
- Smoke path produces UUID7 keys end-to-end.
- Lazy-migration smoke path backfills and is idempotent.
- Archive directory is preserved (not deleted).
- Prefect data untouched.

#### Integration Contract — Phase 8 selective wipe + restart

- **Triggered from**: all 6 component branches merged to main.
- **Returns to / updates**: only the crackerjack storage is removed. Session-buddy and akosha data is preserved (lazy-migration in flight). Prefect untouched.
- **Demonstrable by**: `find /Users/les ~/.local/state /Users/les/Library/Application\ Support -maxdepth 6 -name "*.db" -o -name "*.duckdb" 2>/dev/null | grep -iE "crackerjack|akosha|session-buddy|reflection|warm|mahavishnu.*outbox"` returns the wipe-target entries as **missing** and the preserved entries as **present** (reflection.duckdb, warm.db).
- **Rollback signal**: any MCP server's `/health` returns 503 after restart. Restore path: `tar -xzf <archive-tarball> -C /` for any wiped DB; the lazy-migration legacy `id` columns are unchanged in the preserved DBs so they remain queryable.
- **Observability added**: per-server `restart.first_write` log with `id_format=uuid7`; `archive.manifest.served` log on smoke test entry.

## 6. Required Code Changes

- [ ] Phase 1 archive manifest at `~/.local/state/bodai/db-archive/2026-10-11-uuid7-migration/MANIFEST.json`
- [ ] **Phase 0** — session-buddy: write 10 SQL files under `session_buddy/migrations/2026_10_11_uuid7_consolidation/` (001–010 per Phase 0 task 2) plus matching integration tests under `tests/integration/test_uuid7_consolidation.py`; dry-run against the Phase 1 archive; PR review
- [ ] **Phase 0.5** — session-buddy: stop relevant MCPs (session-buddy, akosha); execute the Phase 0 scripts against live `reflection.duckdb`; verify the consolidated 24-table list and `reflections` row count ≥ 1,485 / `conversations` row count = 1,205; restart
- [ ] oneiric — Phase 2: delete `oneiric/core/ulid.py`, `ulid_resolution.py`, `ulid_migration.py`, `ulid_collision.py`; create `oneiric/core/ids.py` (with `is_valid_id` accepting both UUID7 and 26-char ULID per REQ-012 — REMOVED in Phase 9 T1, see docs/plans/2026-10-12-ulid-surface-elimination.md) and `oneiric/core/system_registry.py`
- [ ] oneiric — Phase 2: delete ULID-related tests
- [ ] crackerjack — Phase 3: delete `crackerjack/services/ulid_generator.py`; `V5__ulid_migration*`, `V6__ulid_contract*`; create `V5__uuid7_contract*`
- [ ] crackerjack — Phase 3: delete/rewrite `tests/{unit,services}/test_ulid_generator*`
- [ ] akosha — Phase 4: update `akosha/processing/knowledge_graph.py` (`make_ulid`, `_load_ulid_generator`); UUID7 generation only (Phase 0.5 handles akosha warm separately)
- [ ] akosha — Phase 4: tests asserting UUID7 keys on new entity writes
- [ ] session-buddy — Phase 5: delete `core/ulid_generator.py`, `_dhara_substrate_compat.py`, `mcp/tools/tasks_legacy.py`
- [ ] session-buddy — Phase 5: rewrite `memory/causal.py`, `skills/distiller.py`, `channel/state_writer.py`, `mcp/tools/session/channel_session_state_tools.py`, `mcp/tools/tasks_storage.py`, `adapters/reflection_adapter_oneiric.py` to point reads/writes at the renamed `reflections` table with `uuid7().hex` PKs only
- [ ] session-buddy — Phase 5: delete or rewrite ULID-shaped tests; add `tests/integration/test_reflections_table.py` and `tests/integration/test_conversations_merged.py`; delete `scripts/run_ulid_migration.py`
- [ ] mahavishnu — Phase 6: delete `core/_dhara_substrate_compat.py`, `scripts/migrate_*_to_ulid.py`
- [ ] mahavishnu — Phase 6: update `distill/distiller.py`, `core/workflow_models.py`, `core/metrics_schema.py`, `core/metrics_collector.py`, `core/unified_orchestrator.py`, `core/cost_optimizer.py`, `core/events/canonical.py`, `distill/schema.py`, `cli/rollback_cli.py`, `adapters/ai/pydantic_ai_adapter.py`, `scripts/tool_frontmatter_validator.py`
- [ ] mahavishnu — Phase 6: search and update `core/jot/*` for ULID shapes
- [ ] mcp-common — Phase 7: confirm/close
- [ ] Phase 8: archive verify; MCP stop; selective wipe (crackerjack SQLite + metrics + caches; **Prefect skipped per parallel workstream**; session-buddy/akosha warm already migrated in Phase 0.5); MCP restart; happy-path smoke (UUID7 writes against the new `reflections` table)

### Cross-plan patches (see §10)

- [ ] `docs/plans/2026-10-03-eval-adapter-phase1.md` — add UUID7 generation to new `runs` / `case_results` / `scores` PKs
- [ ] `docs/plans/2026-08-04-d-lock.md` — `substrate_locks.id` is UUID7 hex in migration 0003
- [ ] `docs/plans/2026-08-10-m-approval-log.md` — repoint to oneiric substrate, UUID7 IDs, serverless-safe storage path
- [ ] `docs/plans/2026-08-10-m-workflow-outcome.md` — same
- [ ] `docs/plans/2026-08-10-m-webhook-durable.md` — same
- [ ] `docs/plans/2026-09-10-jot-capture.md` — pin to local-only v1 (serverless scope)
- [ ] `docs/plans/2026-09-10-jot-inbox.md` — same
- [ ] `docs/plans/2026-09-10-jot-read.md` — same
- [ ] `docs/plans/2026-09-10-jot-drain.md` (complete) — verify final form is local-only v1

## 7. Validation Matrix

| Tool/Command | Expected outcome | Evidence location |
|---|---|---|
| `python -c 'from uuid import uuid7; print(uuid7().hex)'` | 32 lowercase hex chars | any `venv/bin/python3.14` |
| `python -c 'from oneiric.core.ids import generate_id; print(uuid.UUID(generate_id()).version)'` | `7` | oneiric venv, post-Phase 2 |
| `python -c 'from oneiric.core.ids import is_valid_id; print(is_valid_id("01ARZ3NDEKTS6PQRYF"))'` | `False` (ULID rejected; Phase 9 T1 collapsed is_valid_id = is_uuid7) | post-Phase 9 |
| `python -c 'from oneiric.core.ids import is_uuid7; print(is_uuid7("01ARZ3NDEKTS6PQRYF"))'` | `False` (strict UUID7-only check rejects ULID) | post-Phase 2 |
| `grep -rE "ulid\|ULID\|druva\|dhara" {m,a,s,c,o,n}*/{core,services,adapters,mcp,storage,scripts,mahavishnu,akosha,session_buddy,crackerjack,oneiric} ` (scoped) | zero matches in production source | local shell |
| `crackerjack run -v` per repo | passes; no `-p` ever | each repo's CI log |
| `mcp__<server>__get_liveness` per Bodai MCP server | 200 | per-server `/health` |
| `mcp__session-buddy__quick_search(query="post-migration")` | non-empty after smoke test | session-buddy substrate |
| `duckdb -c "SELECT id, uuid7_id FROM reflections_v2 WHERE id LIKE '01%' LIMIT 1" ~/.claude/data/reflection.duckdb` | legacy ULID `id` AND populated `uuid7_id` both visible (post-Phase 5 + lazy-write triggered) | session-buddy warm path |
| `mcp__session-buddy__query_session(<legacy ulid-id>)` called twice in succession | both calls return the same row; only the first logs `dual_written` event (idempotent) | lazy-write smoke in Phase 8 |
| `sqlite3 /Users/les/databases/crackerjack.db ".schema jobs"` | empty file or `job_id TEXT PRIMARY KEY` after first write | post-Phase 8 wipe |
| `mcp__akosha__get_system_metrics()` | feed cycle counts ≥ 1 (post-warmup) | post-Phase 8 |
| `find /Users/les ~/.local/state -name "*.db" -o -name "*.duckdb" \| grep -iE "crackerjack"` | empty post-wipe | post-Phase 8 |
| `find /Users/les -name "reflection.duckdb"` | present (preserved by lazy-write) | post-Phase 8 |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Archive tarball corrupted pre-wipe | low | Phase 1 step 6 round-trip smoke + manifest sha256 verify; abort Phase 8 if mismatch |
| Out-of-tree dependency injects a fresh ULID call after the migration | low | Phase 7 grep + post-Phase-8 re-grep across the merged `main` of all 6 repos |
| Prefect data wipe breaks workflows in flight | n/a | This plan does not touch Prefect storage (user-owned parallel workstream). |
| Lazy dual-write transaction races (two concurrent reads on a pre-migration row both fire UPDATE) | medium-low | The `uuid7_id IS NULL` guard in the UPDATE WHERE clause is idempotent — only one of two concurrent UPDATEs lands a value; the other is a no-op. The transaction is single-row; race produces no inconsistency. |
| Legacy `id` columns on session-buddy / akosha never get fully backfilled | medium | Two-column schema stays until a separate cleanup migration runs. The dual-write codepath is at-most-O(N) reads over the legacy rows. Worst case: legacy columns persist indefinitely. Acceptable: the columns are TEXT, the SELECT path returns either form. |
| Crackerjack FK column rename in V5 leaves orphaned rows | low | REQ-011 says wipe; no live rows at wipe time. Migrations are applied before any new rows; FK enforcement is off during rename. |
| MCP server fails to start with empty crackerjack DB (no schema) | low | V5 migration applies on first write; smoke test in Phase 8 triggers a write to materialize it |
| Cross-branch merge drift (one consumer branch merges before producer) | low | oneiric merges first as cascade source; the rest follow |
| User changes mind mid-migration | low | Archive is the rollback; archive survives Phase 8; recover by `tar -xzf` |
| Python 3.14 `uuid.uuid7()` regression or behavior change | very low | stdlib since 3.14 (2024); verified at integration test in Phase 2 |
| Substrate-compat shims were load-bearing for paths not yet seen | low | Phase 5 step 10 deletes the consumer call sites; if a third-party caller shows up later, the import error surfaces immediately |
| `git push` performed by Claude Code without user approval | low | Plan body and Phase exit criteria explicitly forbid push; per `feedback-bodai-push-is-user-controlled`, the user pushes |
| The lazy-write smoke test discovers that some reflection rows have UUID-shaped (but not UUID7) legacy IDs | low | Step 9b of Phase 8 catches this; mitigation is to broaden `is_valid_id` to accept other UUID versions for read-time validation (still rejecting them in the strict `is_uuid7` path) |

## 9. Decision Rule

This plan is **done** when REQ-001 through REQ-008 are evidenced by the
validation matrix in `docs/plans/2026-10-11-uuid7-only-migration.md`,
**and** every entry in REQ-007's grep scope returns zero matches.

Scope-pressure cut: if Phases 5 or 6 drag, drop the docstring / comment
updates and keep only the code paths. The grep gate is on code paths,
not prose.

---

## 10. Cross-plan Patches (coordinated with this migration)

While this plan is open, several ACTIVE plans add new persistent state
in a way that would either need rework post-migration, or reference
substrate packages that no longer exist, or assume a local filesystem
that serverless operation forbids. Patching them in this same worktree
pass costs one cross-file doc edit per plan and prevents future
rework.

**Why this section exists.** Two facts from the live tree:

1. **Dhara is removed from Bodai core** (per `feedback-substrate-compat-shim-rot.md`,
   confirmed 2026-10-11). Every plan that still does
   `from dhara.schema.X import Y` or `dhara.put(...)` will fail to
   import on next `pip install` once the substrate shim is fully
   deleted.
2. **Serverless operation is a hard requirement** (per
   `2026-09-14-bodai-serverless-readiness-and-component-substitution.md`).
   Local filesystem paths like `approval-history/{id}/` and
   `~/.claude/jot/` are 404 in a serverless deploy. (ADR 018 is the
   MCP gateway pattern evaluation, NOT the serverless-readiness
   decision; the serverless rationale is carried by the
   serverless-readiness plan + ADR 017 substrate alignment.)

**Target substrate for repointing.** All `dhara.*` imports move to
**oneiric substrate** per **ADR 017** (canonical role, **draft status**
at the time of this patch — see "ADR 017 is draft" footnote below;
already in active implementation via the Shared Oneiric Substrate
phases A–E2). Specifically:
- Schema validation surface → oneiric's persisted payload validators.
- `dhara.put(...)` → **explicit per-adapter call**: `oneiric.adapters.storage.LocalStorageAdapter.save(key, data: bytes)`
  (local file in dev); `oneiric.adapters.storage.S3StorageAdapter.upload(key, ...)`
  (S3 in serverless); `oneiric.adapters.storage.AzureStorageAdapter.upload(...)`
  / `save_stream(...)` (Azure); same `upload`/`save_stream` pattern for
  GCS. **There is no unified `put()` facade in oneiric's storage
  adapter family today** — pick the backend explicitly via the config
  layer. The `oneiric.adapters.storage.put(...)` shorthand used in the
  first draft of this plan is incorrect; the explicit `save`/`upload`
  method is the live surface.
- ID format in payloads → UUID7 hex (caller-supplied; this plan
  makes UUID7 the only legal generation path).

> **ADR 017 is `status: draft` at the time of this patch** (per
> `docs/plans/PLAN_INDEX.md` frontmatter: `status: draft`, `role: canonical`).
> If the ADR is rejected or amended during review, re-validate the
> substrate repointing direction. The patches below are
> directionally correct today, but the substrate target is a moving
> target until the ADR is ratified.

**Patches (10 plans + 1 follow-up, 1 worktree, same branch):**

| # | Plan | Status | Patch |
|---|---|---|---|
| 1 | `2026-10-03-eval-adapter-phase1.md` | active | Add UUID7 generation to the new `runs` / `case_results` / `scores` PKs. Default `id TEXT` should be UUID7 hex generated **in the app layer** (`from uuid import uuid7; uuid7().hex` in the writer). Do NOT use `gen_random_uuid7()::TEXT` as a SQL default — oneiric has no `extensions/` or `sql/` directory and ships no such UDF. (If/when the eval DB is migrated to PG, swap to `pgcrypto.gen_random_bytes(16)` + a wrapper, but that's out of scope here.) |
| 2 | `2026-08-04-d-lock.md` | active | Migration 0003 `substrate_locks.id` should be UUID7 hex. App-layer generation only (no oneiric UDF). `lock_key` and `owner_token` follow the same rule. |
| 3 | `2026-08-10-m-approval-log.md` | active | Repoint `from dhara.schema.approval_log import ApprovalLog` → oneiric substrate. Local path `approval-history/{approval_id}/` → explicit `LocalStorageAdapter.save(key, data: bytes)` (or cloud equivalent per substrate config); `approval_id` is UUID7. The plan must also call out the 4-signal feed contract (`feed.entities_count`, `feed.last_updated_timestamp`, `feed.errors_total`, `cycles_total`) for the new `list_approval_history` MCP tool, per `.claude/decisions/mcp-backend-wiring-discipline.md` §3. |
| 4 | `2026-08-10-m-workflow-outcome.md` | active | Same: repoint substrate, serverless-safe storage, UUID7 `workflow_id`. 4-signal feed contract required for the new `workflow_get_outcome(workflow_id)` MCP tool. The plan's Task 4 `pytest.skip("Replace with the actual Dhara fixture once located")` placeholder must be replaced with a real aggregator-verdict test (`tests/integration/test_workflow_tools_e2e.py` asserting real HTTP `/health` verdict), per `feedback-mcp-test-must-assert-aggregator-verdict`. |
| 5 | `2026-08-10-m-webhook-durable.md` | active | Same: repoint `WebhookIngress` to oneiric substrate, serverless path, UUID7 `webhook_id`. **The `audit_record` emission side-effect (Dhara's D-AUDIT subscriber) needs a migration path forward** — oneiric has no equivalent audit-on-write adapter; the patch's `## Coordination notes` section already flags this TBD. **Resolution required before merge:** the webhook surface needs an OTel span `webhook.ingress.record_written` (with `audit_record=true` attribute) so the audit feed is observable through the existing OTel → Akosha path. The actual `audit_record` event emission is the responsibility of the m-webhook-durable plan's own PR (out of scope for this worktree). |
| 6 | `2026-09-10-jot-capture.md` | active | Add a "Serverless scope" section pinning jot to **local-only v1** (host filesystem). Justification: jot is a per-user quick-capture scratchpad with a 30-day retention per `2026-09-10-jot-inbox.md`; the cloud-repointing scope is bigger than this migration and should land separately if desired. **Serverless disable mechanism:** the `jot-session-start.py` SessionStart hook in `.claude/settings.json` MUST become a no-op (or be removed) in serverless deploys because `~/.claude/jot/` doesn't exist. Document this; the existing implementation in `mahavishnu/hooks/jot_capture.py` already falls back to `errors.log` + passthrough on `PermissionError`, but the SessionStart hook (which surfaces jots via `mcp__mahavishnu__jot_resurface`) needs the same fallback or removal. |
| 7 | `2026-09-10-jot-inbox.md` | active | Same: local-only v1 + serverless disable mechanism. |
| 8 | `2026-09-10-jot-read.md` | active | Same: local-only v1 + serverless disable mechanism. |
| 9 | `2026-09-10-jot-drain.md` | complete | Verify the shipped form already says local-only v1; if not, pin it. Same serverless disable note as capture/inbox/read. |
| 10 | `2026-09-10-plan-index-dhara.md` (+ `docs/specs/2026-09-10-plan-index-dhara-design.md`) | active / draft | **Missed in the v1 audit** — the entire architecture is "Dhara-canonical metadata index" with `await self._dhara.put(self._primary_key(d["plan_id"]), json.dumps(d), ttl=86400)` calls. Repoint to explicit oneiric storage (per-adapter selection per row 3). Slash-prefixed keys (`envelopes/...` / `plan-index/...`) move to the substrate-abstracted path namespace. Archive `docs/decisions/dhara-key-prefixes-2026-07-15.md` next to the substrate-compat deletion (per `feedback-substrate-compat-shim-rot.md`). The companion spec gets the same repointing note. |

**Patches that are NOT this plan's job** (out of scope; mention for traceability):

- **MCP-launcher plans** (`2026-09-26-mcp-launcher-standardization.md`) — does not touch substrate.
- **Mahavishnu durable worker plans** (`2026-07-26-durable-local-workers.md`,
  `2026-08-10-auto-checkpoint-*.md`) — Git-based, no substrate. Serverless
  mode needs `git clone target_repo` as a precondition; document the
  constraint, do not change the plan.
- **Worker readiness** (`2026-07-21-worker-readiness.md`) — in-process
  capability report, no persistence, no change needed.
- **`2026-08-29-worker-registry-capability-refactor.md`** (active,
  borderline) — Test fixtures inject `AsyncMock` for `DharaAdapter.put`
  (the `envelopes/...` slash-keys are Dhara-shaped, but the runtime
  abstraction is `DharaAdapter` so the production call site is
  substrate-portable). The parent refactor's own substrate swap will
  handle this; the patch here is informational only. (Listed because
  the plan index audit criterion "any plan that references `dhara.*`"
  flags it; the actual fix is downstream.)

**How these patches ship.** Each plan file is edited in the same
worktree branch (`migration/2026-10-11-uuid7-only`) as one
`docs(plans): patch <plan-name> for UUID7 + substrate + serverless`
commit. The patches are docs-only — no runtime code changes
(resulting PRs from those plans still need their own runtime
changes per their own exit criteria, but those are independent of
this migration).

**Why docs-only and not runtime.** A subset of the 9 plans
(eval-adapter, d-lock, the m-* durable plans) reference
`dhara.schema` in their code blocks, not just their docs. Patching
the docs to say "use oneiric substrate and UUID7" makes the design
direction correct; the actual `import` lines are rewritten when
the plan's own PR is implemented (in a separate worktree, per the
plan's own exit criteria). Coordinating the docs in this worktree
prevents 9 future worktrees from each discovering the same problem
independently.

**Validation.** After all 9 patches land:
- `grep -rE "dhara.schema|dhara\.put|approval-history|workflow-results|~/.claude/jot" docs/plans/2026-1{0,1}*.md` returns zero matches (or matches only in the new "was-Dhara-now-oneiric" callout that this section adds).
- `python -c "import uuid; uuid.uuid7().hex"` is the only sanctioned generation path (no `from uuid_utils import uuid7`, no `from ulid import ULID`, no `from oneiric.core.ids import ulid*`).

---

## References

- `.claude/decisions/wire-up-contract.md` — Integration Contract policy.
- `docs/plans/TEMPLATE.md` — plan shape this document follows.
- `docs/feature-tracking/TEMPLATE.md` — feature-state lifecycle.
- Memory `feedback-no-backwards-compat-pre-1.0.md` — replace-not-extend.
- Memory `feedback-bodai-push-is-user-controlled.md` — never `git push` for bodai without approval.
- Memory `feedback-crackerjack-publish-stage-is-user.md` — never `crackerjack run -p`.
- Memory `feedback-oneiric-mcp-health-feed-warmup.md` — `cycles_total == 0` → 503.
- Memory `prefect-adapter-bugs-2026-10-11.md` — Prefect 3.x integration is currently broken.
- Memory `feedback-worktree-update-ref-drops-parallel-commits.md` — worktree conventions.
- CLAUDE.md § "Process Discipline" — wire-up contract + integration contract.
- CLAUDE.md § "Plans / specs path preference" — `docs/plans/YYYY-MM-DD-…`.

---

## 11. Phase 0 Post-Mortem (commit `52e70f5d`, 2026-10-11)

Phase 0 shipped on `main` (and `origin/main`) at commit `52e70f5d` after a 4-iteration chain test (001-007 PASS on a fresh DuckDB 1.5.6) and a 6-reviewer adversarial pass (B-step verdict: GO after 3 blockers fixed). The 8 known follow-ups below are non-blocking but should be addressed in the Phase 0.5 maintenance window work.

### Known follow-ups (non-blocking)

1. **`source_type` CHECK constraint lost in 007's rebuild.** `schema_v2.py:70-74` declares `source_type TEXT CHECK (source_type IS NULL OR source_type IN (...))`. DuckDB has no `ALTER TABLE ADD CONSTRAINT`, and 007's `CREATE TABLE conversations_new` omits the CHECK. After migration, any string is accepted for `source_type` — the rest of session-buddy's provenance contract is silently weakened. **Fix**: inline the CHECK clause into the new CREATE TABLE in 007.

2. **`session_metadata` type drift in 007.** 007 declares `session_metadata TEXT`; `schema_v2.py:372` declares `JSON`. 0-row table today hides the bug; first writer after migration hits it. **Fix**: align to `JSON` in 007 (matches the schema_v2.py declaration).

3. **No per-table `migration.<step>.rows_affected=<n>` log.** Plan §0 Integration Contract requires structured observability; the SQL files are silent. **Fix**: add `SELECT COUNT(*)` lines per rebuild, or delegate to the Phase 0.5 Python runner which is the documented owner.

4. **`tests/integration/test_uuid7_consolidation.py` does not exist.** Plan §0 task 3 requires 4 named integration tests; only the ad-hoc chain test exercises the migration. **Fix**: add the file in a follow-up.

5. **`scripts/test_database_status.py:82` still lists `access_log_v2`.** Sibling status script contradicts the vestigial-table story. **Fix**: drop `access_log_v2` from the expected-tables list (or rewrite the status check to use the `__uuid7_migration_done` marker).

6. **Plan body row-count drift: `1,200` vs `1,205`.** Plan body line 358, 422-424, 845-846 still assert `conversations=1,205` after Phase 0. The script correctly produces `1,205` (935 v2 + 265 v0-unique + 5 default_conversations, per plan body line 273-276). **Fix**: update the validation matrix and exit-criteria lines to `1,205`.

7. **001 category backfill uses case-sensitive `LIKE`.** Mixed-case legacy v0 content (e.g. `'Prefer'`) misclassifies to `facts`. **Fix**: use `LOWER(legacy.content) LIKE '%prefer%'` or `ILIKE`.

8. **001 `default_conversations` sentinel has unused `fingerprint` column.** Harmless. **Fix**: drop the column from the sentinel CREATE TABLE.

### Security review findings (post-commit, 2026-10-11)

- **`control-regression` in `008_id_swap_dormant_active.sql`:** the explicit `PRAGMA foreign_keys = OFF` / `PRAGMA foreign_keys = ON` sandwich was removed in the DuckDB rewrite. FK safety is preserved via inlined `CREATE TABLE ... FOREIGN KEY` + ordered DROP, but the explicit toggle that operators can audit is gone. **Fix**: add a header comment block in 008 documenting the safety contract — pure documentation, no behavior change.

- **`stale-identity-mapping` in `007_id_swap_load_bearing.sql`:** `conv_id_map` is populated with `uuid7()` (timestamp + random per call), so the mapping is not stable across re-runs. A second migration run would silently re-encode every row with new UUID7s, breaking any external consumer that pinned the prior IDs. **Fix**: switch to a deterministic UUID7 derivation (e.g. `uuid7(seed=hash(legacy_id))`); the deterministic UDF is properly a Phase 0.5 runner concern (the runner owns the UDF registry) — do not put the helper in the SQL file.

### Process notes for Phase 0.5

- The chain test that found 7 of the 8 known follow-ups used a *test seed* that was more permissive than the live archive. Always run the final chain test against a fixture that mirrors the **production** schema, not a hand-written minimum. The blocker-level finding (003's `conversation_id` reference) was only caught when an adversarial reviewer DESCRIBEd the live `reflections_v2` table — 24 columns, no `conversation_id`.
- DuckDB 1.5.6 rejects `ALTER TABLE ADD COLUMN ... NOT NULL DEFAULT` at the parser. The CTAS rebuild pattern is the canonical DuckDB migration idiom; the entire 007 rewrite is the canonical example for future 5xx-style "swap all primary keys" migrations.
- The `__uuid7_migration_done` marker is a forward-looking gate. The b-step patch tried to use it as a conditional in `fix_database_issues.py` but the marker is only created when the migration runs; the gate was dormant on a fresh DB. The final b-step patch removed the recreate entirely (don't recreate vestigial tables; the migration drops them).
