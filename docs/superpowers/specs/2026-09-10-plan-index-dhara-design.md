---
role: spec
topic: plan-index-dhara
status: draft
date: 2026-09-10
last_reviewed: 2026-09-10
superseded_by: null
blocks_on: []
---

# Plan Index — Dhara-Canonical Metadata Layer

> **Design status:** draft, awaiting reviewer sign-off (2026-09-10). Built
> through the superpowers:brainstorming flow across three sections; this
> doc is the consolidated output of that conversation.

## Problem

`docs/plans/PLAN_INDEX.md` is the navigation map for Mahavishnu and the
broader Bodai ecosystem's plan/decisions/followups/feature-tracking/ADR
catalogue. Today it is generated mechanically by
`scripts/regenerate_plan_index.py`, which scans 24 directories on the
local filesystem, parses YAML frontmatter, and renders a markdown table.

Three failure modes the current design cannot address:

1. **Serverless / container runtime** — the scanner needs the 24 dirs
   on the local filesystem; a serverless bundle typically does not
   ship `.claude/decisions/` or `docs/adr/`, so the index cannot be
   regenerated at runtime.
2. **Cross-machine visibility** — every clone regenerates a different
   `PLAN_INDEX.md`. A developer on a laptop and a colleague on a
   workstation see different views with no easy way to merge.
3. **Action orientation** — the index is read-only. The math plan's
   `scripts/feature_eligibility.py` (Phase 9) polls four separate MCP
   endpoints to fire tier-2 follow-up triggers. A scheduler that
   drives work out of plans needs a queryable index, not a static
   file.

The jot inbox design (`docs/superpowers/specs/2026-09-09-jot-inbox-design.md`)
established the project's canonical pattern for this class of problem
(write → derive → query). This spec applies that pattern to plans,
**inverting the canonical axis** because plans are reviewable code
(git canonical) while jots are quick thoughts (Dhara canonical).

## Goals

1. **Cross-machine plan visibility** — any Mahavishnu process reading
   the index sees the same set of active/partial/canonical plans,
   regardless of which machine holds the source-of-truth `.md` file.
2. **Serverless compatibility** — a serverless bundle that ships only
   the renderer (not the 24 dirs) can serve the index by reading from
   a portable substrate.
3. **Single canonical schema** — `mcp__mahavishnu__plan_*` tools and
   the math plan's Phase 9 trigger script read from one place; no
   fan-out to per-source MCP calls.
4. **Wire-up discipline** — `/health` aggregates per-feed state
   (`entities_count`, `last_updated_timestamp`, `errors_total`,
   `cycles_total`) and returns 503 if the rebuild feed is stale,
   per `.claude/decisions/mcp-backend-wiring-discipline.md`.
5. **Git stays the only write path** — no review-process regression;
   `crackerjack docs validate` and `scripts/audit_requirements.py`
   remain authoritative.

## Non-goals

1. **Not** replacing git as the canonical store for plan content. The
   `.md` files are reviewable code; they do not move.
2. **Not** adding a cloud bucket mirror. Dhara is the substrate.
3. **Not** shipping Layer 4 (task queue + scheduler) in this spec —
   sketched only, deferred to a follow-on. The substrate (Dhara
   queryable index) is what this spec delivers.
4. **Not** semantic search via Session-Buddy in v1 — lexical match
   on `title` + `topic` only. Matches the jot spec's decision to defer
   semantic recall until drain freshness is proven.
5. **Not** cross-team federation in v1 — the record carries `repo` so
   the future federation is a CLI flag, but v1 reads Mahavishnu only.

## Decisions

### D1 — Dhara as the canonical metadata store
Plan content stays in git; **plan metadata** (frontmatter fields) lives
in Dhara. The existing Dhara instance at port 8683 is the substrate;
no new datastore ships. Cross-machine visibility is Dhara's existing
replication, which jot sub-plan 3 will harden — we ride that work.

### D2 — Git as the only write path
Promoters edit `.md` files and open PRs as today. There is no new
write step for promoters. The rebuilder reads git, parses frontmatter,
upserts to Dhara.

### D3 — `scripts/regenerate_plan_index.py` rewritten as three phases
- **Phase A** (existing): filesystem scan + frontmatter parse → list of records
- **Phase B** (new): upsert records to Dhara
- **Phase C** (refactored): render markdown from Dhara → write `PLAN_INDEX.md`

Phases B and C are pure functions in `mahavishnu/plan_index/`; the
script is the thin orchestrator. Both halves are unit-tested without
mocks; the integration test wires real Dhara.

### D4 — `sha` drift detection
Each PlanRecord carries the git blob SHA of its `.md` at rebuild
time. The rebuilder compares `sha` against the current blob; only
changed files are upserted. Makes incremental rebuilds O(changed-files)
rather than O(all-files) as the 24 dirs grow.

### D5 — 7-day `/health` staleness trip-wire
`mcp-backend-wiring-discipline.md` requires `/health` to aggregate
per-feed state. The plan_index feed reports `last_updated_timestamp =
plan_index:meta:last_rebuild_ms`; if that timestamp is more than 7
days stale, `/health` returns 503. This protects against forgotten
cron jobs and silent Dhara replication lag.

### D6 — Trip-wire for push surfaces (mirrors jot Decision 5)
`plan_query_count / plan_edit_count` (last 7d) ratio:
- ≤ 3:1 → healthy
- 3:1–10:1 → "review cadence lagging" hint in `plan_vitals()`
- > 10:1 for 2 consecutive weeks → unlocks push surfaces (Slack
  digest, etc.)

Pre-committed: if the trip-wire fires for two consecutive weeks, the
"pull-only" v1 posture unlocks into optional push v1.1.

### D7 — MCP tool group lives in FULL profile only
`mcp__mahavishnu__plan_list` / `plan_show` / `plan_search` /
`plan_vitals` / `plan_rebuild_status` ship in FULL. STANDARD tier
(the default for most installations) reads `PLAN_INDEX.md` on disk
as today. Same posture as jot's `jot_*` tool group.

### D8 — `plan_rebuild` is CLI-only in v1
No MCP tool exposes a rebuild trigger. Rebuilding from MCP is a
foot-gun (Dhara upserts can race with live edits). `plan_rebuild_status`
MCP tool exposes last errors; the actual rebuild is `python
scripts/regenerate_plan_index.py` or the fitness_analyzer poll.

### D9 — Cron lives in `mahavishnu/pools/fitness_analyzer.py`
Extend the existing `task_classes` list at line 279 to include
`plan_index_rebuild`. Reuses the 60s polling infrastructure,
`HotRecord` plumbing, Redis-stream-based `bodai:events` broadcast,
queue cap 1000, circuit breaker, and DLQ after 3 consecutive write
failures. Matches the math plan's §7 cross-repo stub pattern.

### D10 — Decommission filesystem read path at cut-over + 14 days
Step 8 of the migration. Before that, `bodai-status` and
`mahavishnu-status` skills read both Dhara and `PLAN_INDEX.md` (Dhara
authoritative, filesystem fallback). After 14 days of stable Dhara
reads, the filesystem branch is removed.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 4: Action surface (DEFERRED, sketched only)                │
│   ┌──────────────────────────┐   ┌────────────────────────┐      │
│   │ plan_task_queue           │   │ plan_scheduler         │      │
│   │ (Dhara-backed queue,     │   │ (cron-like, reads      │      │
│   │  pops plan-derived work) │   │  blocks_on graph)      │      │
│   └──────────┬────────────────┘   └────────────┬───────────┘      │
│              │  reads/writes Dhara            │  reads Dhara     │
│   ┌──────────┴────────────────────────────────┴───────────┐      │
│   │ Layer 3: Plan index in Dhara                            │      │
│   │   table: plan_index                                     │      │
│   │   row keys: plan_index:{plan_id}                        │      │
│   │   secondary keys: plan_index:status:{status}:...        │      │
│   │                   plan_index:topic:{topic}:...          │      │
│   │   meta keys: plan_index:meta:last_rebuild_ms, etc.      │      │
│   └──────────────────┬───────────────────────────────────────┘      │
│                      │                                            │
│   ┌──────────────────┴───────────────────────────────────────┐      │
│   │ Layer 2: Re-deriver + Re-renderer (CLI orchestrator)     │      │
│   │   scripts/regenerate_plan_index.py                       │      │
│   │     Phase A: scan 24 dirs (filesystem)                   │      │
│   │     Phase B: PlanIndexRebuilder.upsert_all → Dhara       │      │
│   │     Phase C: PlanIndexRenderer.write → PLAN_INDEX.md     │      │
│   └──────────────────┬───────────────────────────────────────┘      │
│                      │  reads git (filesystem)                    │
│   ┌──────────────────┴───────────────────────────────────────┐      │
│   │ Layer 1: Git — UNCHANGED                                 │      │
│   │   .md files in docs/plans/, .claude/decisions/,          │      │
│   │   docs/adr/, docs/followups/, docs/feature-tracking/     │      │
│   └──────────────────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────────────┘
```

### Read paths after the change

- **Humans**: read `docs/plans/PLAN_INDEX.md` (a *rendered artifact*,
  regenerated from Dhara on every script run)
- **AI agents in-session**: `mcp__mahavishnu__plan_list` /
  `plan_show` / `plan_search` / `plan_vitals`
- **`bodai-status` / `mahavishnu-status` skills**: during the
  14-day dual-read window, read both; after, Dhara-only

### Write paths after the change

- **Promoters**: edit `.md` files in git as today; no new write step
- **Cross-machine readers**: Dhara's existing replication
  (jot sub-plan 3 will harden this)

## Components

| Component | Location | Purpose |
|---|---|---|
| `PlanIndexStore` (new) | `mahavishnu/plan_index/store.py` | Dhara-backed metadata CRUD (`upsert`, `get`, `list_by_status`, `list_by_topic`, `list_by_date_range`, `search`, `vitals`). The only file that talks to Dhara. |
| `PlanIndexRebuilder` (new) | `mahavishnu/plan_index/rebuild.py` | Pure function: list of frontmatter dicts → list of PlanRecord. No I/O. SHA computation via `git hash-object`. |
| `PlanIndexRenderer` (new) | `mahavishnu/plan_index/render.py` | Pure function: list of PlanRecord → `PLAN_INDEX.md` markdown string. No I/O. |
| `RegeneratePlanIndexCLI` (rewritten) | `scripts/regenerate_plan_index.py` | Orchestrates A → B → C. New flags: `--check` (dry-run diff), `--skip-render` (Dhara-only), `--rebuild-from` (one-shot backfill from git history). |
| `mcp__mahavishnu__plan_*` (new tool group) | `mahavishnu/mcp/tools/plan_tools.py` | 5 tools: `plan_list`, `plan_show`, `plan_search`, `plan_vitals`, `plan_rebuild_status` |
| `mahavishnu plan …` CLI (new) | `mahavishnu/cli/plan_cli.py` | Mirrors MCP tools for shell use |
| Feed-state provider (new) | `mahavishnu/plan_index/health.py` | Returns `(entities_count, last_updated_timestamp, errors_total, cycles_total)` for `health_check()` aggregation |
| Wire-up audit script (new) | `scripts/audit_plan_index.py` | Catches "rebuild skipped, Dhara and PLAN_INDEX.md disagree" |

## Data Model

### `PlanRecord` dataclass

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlanRecord:
    plan_id: str          # SHA-derived: sha256(path).hexdigest()[:16]
    path: str             # canonical absolute path, e.g. "docs/plans/2026-09-15-foo.md"
    title: str            # H1 / first heading from the .md body
    status: str           # draft | active | partial | shipped | complete
    role: str             # canonical | implementation | umbrella | historical | superseded
    topic: str            # frontmatter topic
    date: str             # YYYY-MM-DD
    last_reviewed: str    # YYYY-MM-DD
    superseded_by: str | None
    blocks_on: list[str]  # list of plan_ids this plan depends on
    sha: str              # git blob SHA at rebuild time, for drift detection
    repo: str             # git remote URL (placeholder for cross-team federation)
    updated_at_ms: int    # server-set timestamp; trip-wires read this
```

### Dhara key conventions

Mirror `docs/decisions/dhara-key-prefixes-2026-07-15.md`:

- `plan_index:{plan_id}` → JSON record of one plan
- `plan_index:status:{status}:{date}:{plan_id}` → secondary index for status queries (lex order = chronological within filter)
- `plan_index:topic:{topic}:{date}:{plan_id}` → secondary index for topic queries
- `plan_index:meta:last_rebuild_ms` → bookkeeping for wire-up discipline
- `plan_index:meta:errors_total` → cumulative rebuild errors
- `plan_index:meta:cycles_total` → cumulative rebuild attempts
- `plan_index:meta:migration_pre_flight_errors` → list of paths that failed pre-flight
- `plan_index:meta:rebuild_lock:{hostname}:{pid}` → concurrent-rebuild lock with stale-PID detection

### Trip-wire thresholds (config)

```yaml
# settings/mahavishnu.yaml
plan_index:
  rebuild:
    cron_every_seconds: 3600      # fitness_analyzer polls every 60s; handler
                                  # only fires rebuild when
                                  # (now - last_rebuild_ms) >= this value
    health_stale_after_days: 7    # /health 503 threshold
    tripwire:
      ratio_threshold: 10
      consecutive_weeks: 2
      query_window_days: 7
```

**Cron semantics:** `mahavishnu/pools/fitness_analyzer.py` polls every
60 seconds and emits a `HotRecord` per task_class. The handler for
`task_class="plan_index_rebuild"` reads `plan_index:meta:last_rebuild_ms`
from Dhara; if `(now_ms - last_rebuild_ms) / 1000 >= cron_every_seconds`,
the rebuild runs; otherwise the handler no-ops. This pattern matches
the existing 60s polling cadence without spinning up a separate cron
job. At `cron_every_seconds: 3600` the rebuild fires at most once
per hour, regardless of poll frequency.

### Wire-up discipline feed-state contract

`health_check()` aggregates:

| Field | Source | Constraint |
|---|---|---|
| `entities_count` | `len(keys("plan_index:*")) - 7` (subtracts secondary + meta) | Monotonic increasing |
| `last_updated_timestamp` | `plan_index:meta:last_rebuild_ms` | Must be < `now - 7 days`, else 503 |
| `errors_total` | `plan_index:meta:errors_total` | Reset to 0 only via explicit operator action |
| `cycles_total` | `plan_index:meta:cycles_total` | Increments on every successful rebuild phase |

## Data flow

### Single-plan lifecycle (the happy path)

```
1. Promoter edits docs/plans/2026-XX-XX-<topic>.md in a git branch
   ↓ (git commit, push, PR review, merge to main)
2. Repo main now has the new .md with new frontmatter
   ↓
3. fitness_analyzer poll (every 60s) fires task_class=plan_index_rebuild
   ↓ Phase A: filesystem scanner reads all .md frontmatter
   ↓ Phase B: PlanIndexRebuilder.upsert_all(records) writes to Dhara
              (one transaction per record; failed records logged)
   ↓ Phase C: PlanIndexRenderer.write(markdown_string) writes to
              docs/plans/PLAN_INDEX.md
   ↓
4. /health aggregates: entities_count +1, last_updated_ms updated,
   cycles_total +1
5. Read paths see the new state:
   - mcp__mahavishnu__plan_show(path=...) reads Dhara
   - PLAN_INDEX.md on disk shows the new entry
```

### Cross-machine read path

```
Machine A (developer laptop):
  plan_edit on docs/plans/2026-09-15-foo.md → git push → machine B
  ↓
Machine B (server / serverless runtime):
  git pull (or shared cache) → fitness_analyzer poll (if not already)
  ↓
  mcp__mahavishnu__plan_list({status: "active", topic: "routing"})
  ↓
  PlanIndexStore reads Dhara:8683 (replicated from machine A's upsert)
  ↓
  returns JSON list
```

### Lock acquisition (concurrent rebuilds)

```
Rebuilder starts → set plan_index:meta:rebuild_lock:{hostname}:{pid}
  with TTL = 60s (longer than expected rebuild duration)
↓
If lock exists:
  Check TTL — if expired, take lock (stale-PID)
  Else, abort with "another rebuild in progress"
↓
On completion (success or partial failure):
  delete lock key
```

## Rebuilder invariants (stated, testable)

1. **Idempotency** — running the rebuilder twice in a row produces
   the same Dhara state (upserts by `plan_id`).
2. **Drift detection** — if `path` exists on disk but is missing
   from Dhara, the rebuilder inserts it. If `path` is in Dhara but
   missing on disk (deleted/renamed), the rebuilder marks it
   `historical` with a tombstone rather than deleting (preserves
   audit trail; read-side renders it as "removed").
3. **Frontmatter validation** — invalid frontmatter (missing
   `status` or `role`, unknown enum values) causes that record to
   be **logged to errors and skipped**, not inserted. The remaining
   records still upsert. Validation reuses the existing
   `scripts/audit_requirements.py` schema.
4. **Git as source of truth** — the rebuilder reads from the
   **filesystem view of main**, never from a worktree, never from a
   feature branch's checkout. Worktrees are excluded by path (the
   existing scanner already excludes `.claude/worktrees/`).
5. **`sha` field** — set to the git blob SHA of the `.md` file at
   rebuild time. Read paths may return stale metadata if the rebuild
   hasn't re-run since the file changed; acceptable for day-scale
   lifecycle.

## Read-path invariants

1. **`mcp__mahavishnu__plan_show(plan_id)`** returns the record from
   Dhara. If Dhara returns nothing, the tool returns `null` (NOT 404)
   — the caller decides whether the absence is "rebuild not run yet"
   vs. "plan was deleted."
2. **`mcp__mahavishnu__plan_list({status, topic, date_from, date_to})`**
   uses the secondary indexes (`plan_index:status:{status}:...` and
   `plan_index:topic:{topic}:...`). Lex order = chronological within
   filter.
3. **`mcp__mahavishnu__plan_search(query)`** returns lexical matches
   on `title` + `topic` from Dhara's primary key prefix scan. No
   Session-Buddy semantic search in v1.
4. **`mcp__mahavishnu__plan_vitals()`** returns Dhara-derived counts:
   `total`, `by_status`, `by_role`, `by_topic_top10`,
   `last_rebuild_ms`, `oldest_active_ms`,
   `tripwire_ratio` (`plan_query_count / plan_edit_count` over last 7d).

## Error handling

### The cardinal rule

**The rebuilder never destroys Dhara state on partial failure.**
Mirrors the jot spec's "never erase text you failed to store."

| Failure | Behavior | Recovery |
|---|---|---|
| Git working tree has uncommitted changes | Rebuild aborts with non-zero exit; Dhara unchanged | Commit, re-run |
| Unparseable `.md` (bad YAML, missing field) | That file logged to errors; rebuild continues | Fix frontmatter, re-run |
| Dhara write fails for one record | Logged to errors; `errors_total` incremented; rebuild continues | `mcp__mahavishnu__plan_rebuild_status` exposes last errors; re-run |
| Dhara write fails for **all** records | Rebuild aborts; partial Dhara state preserved; `cycles_total` NOT incremented | `/health` 503; investigate; re-run |
| Dhara unreachable on read | Tool returns `{"status": "degraded", "reason": "dhara_unreachable", "cached_at_ms": <last successful read>}` | Caller falls back to PLAN_INDEX.md (cached view from last successful render) |
| Dhara replication lags | Cross-machine read may miss recent edit | Acceptable; trip-wire surfaces stuck machines; 7-day staleness check in `/health` |
| Renderer markdown write fails (disk full) | Rebuild succeeds in Dhara; PLAN_INDEX.md shows previous render; warning logged | Manual re-render once disk freed |
| Concurrent rebuilds | Second script sees stale-lock, aborts with clear error | First wins; second evaluates after first completes |

## Migration plan

The existing 24 dirs already have ~150+ markdown files with valid
frontmatter. The first run of the new rebuilder is a **migration**,
not a feature:

1. **Pre-flight check** — script reads every `.md`, asserts all
   required fields present. Files with missing fields are listed in
   `plan_index:meta:migration_pre_flight_errors`; migration aborts.
2. **Investigate and fix** — operator runs `python
   scripts/audit_requirements.py --include-tests` (already exists
   for the math plan, reused here).
3. **Migration run** — script reads every `.md`, upserts to Dhara
   with `migration: true` flag. Cycles_total=1, errors_total=0.
4. **Render and commit** — script renders `PLAN_INDEX.md` from
   Dhara, writes it to disk, opens a one-time commit titled
   `chore(plan_index): first Dhara-fed rebuild`. No consumer-visible
   behavior change yet.
5. **Verify** — `diff <(old PLAN_INDEX.md) <(new PLAN_INDEX.md)`
   must be empty. If not, abort the migration.
6. **Wire MCP tools** — only after step 5 passes. Add to
   `FULL_REGISTRATIONS` + `REGISTRATION_MAP` (the 5-edit dance per
   the jot spec).
7. **Cut over** — change `bodai-status` and `mahavishnu-status`
   skill bodies to call MCP tools in parallel with reading
   `PLAN_INDEX.md`. Filesystem read stays as fallback.
8. **Decommission** — at cut-over + 14 days, remove the
   filesystem-scan branch from the skills, mark PLAN_INDEX.md as
   a *cached artifact* in its frontmatter. Plan_index.md is no
   longer the source of truth for any read path.

**Rollback signal:** if `/health` returns 503 for the plan_index
feed for >24 hours, or if `mcp__mahavishnu__plan_show` returns
degraded for the same window, step 7 is reverted. Step 8 is
delayed until the 7-day window clears.

## Testing strategy

### Unit tests (`tests/unit/plan_index/`)

| File | Coverage |
|---|---|
| `test_store.py` | PlanIndexStore against a mock Dhara — all CRUD ops, idempotency, secondary-index queries |
| `test_rebuild.py` | PlanIndexRebuilder as pure function — input list → expected PlanRecord list, no I/O |
| `test_render.py` | PlanIndexRenderer as pure function — input list → expected markdown, snapshot against existing PLAN_INDEX.md output |
| `test_cli.py` | Orchestrator CLI — phased happy path, phased with errors, lock handling |
| `test_migration_preflight.py` | Pre-flight check — valid + invalid frontmatter mixed |
| `test_sha_drift_detection.py` | SHA field semantics — unchanged file → no upsert |
| `test_lock.py` | Lock acquisition with stale-PID detection |
| `test_vitals.py` | Ratio computation, trip-wire thresholds |

### Property tests (`tests/property/plan_index/`)

| Property | Examples |
|---|---|
| `rebuild_idempotent` — same input list twice → same Dhara upserts | ≥ 100 |
| `rebuild_preserves_unrelated_records` | ≥ 50 |
| `renderer_idempotent` — same input list → same output bytes | ≥ 100 |
| `sha_collision_improbable` — 10,000 random paths → 0 collisions | ≥ 20 |

### Integration tests (`tests/integration/plan_index/`)

| Scenario | Coverage |
|---|---|
| `test_rebuild_e2e.py` | Real git repo with 3 sample plans, real Dhara (mock or container), full pipeline → PLAN_INDEX.md rendered |
| `test_concurrent_rebuilds_serialize.py` | Two CLI invocations racing, second sees stale-lock |
| `test_partial_failure_continues.py` | Inject Dhara write failure for one record |
| `test_dhara_unreachable_degrades.py` | Patch store to raise; verify degraded envelope (NOT exception) |
| `test_render_matches_old_scanner.py` | Golden comparison — byte-equivalent to today's filesystem-scanner output |
| `test_health_check_aggregates.py` | Wire feed-state provider, call `/health`, verify all four fields |

### Wire-up audit (CI gate)

Add `scripts/audit_plan_index.py`:
- Reads `PLAN_INDEX.md` and asserts every entry has a corresponding
  `.md` file on disk (no phantom entries)
- Scans every `.md` in the 24 dirs and asserts every entry is in
  `PLAN_INDEX.md` (no missing entries)
- Asserts every entry in `PLAN_INDEX.md` has a corresponding row in
  Dhara (no Dhara lag at audit time)

This catches the "rebuild skipped, Dhara and PLAN_INDEX.md disagree"
failure mode that the wire-up contract requires we detect.

### CI integration

- `make plan-index-validate` — runs `python scripts/regenerate_plan_index.py --check`
  (dry-run: scan + diff against existing `PLAN_INDEX.md`, fail if different)
- `make plan-index-rebuild` — runs the full rebuilder
- Wire `plan-index-validate` into the existing CI pipeline alongside
  `crackerjack docs validate`

## Open questions

1. **Where does the cron-driven rebuild live?** Three options:
   (a) new cronjob on the host running Mahavishnu,
   (b) Mahavishnu's existing `fitness_analyzer.py` poll loop
   (extends its `task_classes` list at line 279, per the math
   plan's cross-repo precedent),
   (c) CI nightly scheduled job.
   **Recommendation: (b)** — reuses 60s polling, `HotRecord`
   plumbing, Redis stream, queue cap 1000, circuit breaker, DLQ.

2. **Should the trip-wire threshold live in config or be hardcoded?**
   **Recommendation: config** (in `settings/mahavishnu.yaml` under
   `plan_index:`) but **start with no trip-wire action** — just
   record the ratio in vitals.

3. **Profile tier placement.** **Recommendation: FULL only** for v1
   — the tools are debugging/operations surface, not core probes.
   STANDARD tier reads `PLAN_INDEX.md` on disk instead.

4. **Should `mcp__mahavishnu__plan_rebuild` ship in v1, or be CLI-only?**
   **Recommendation: CLI-only for v1**; the MCP tool exposes
   `plan_rebuild_status` instead. Rebuilding from MCP is a foot-gun.

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Migration step 5 fails (`diff` non-empty) | Medium | Abort; renderer fix; re-migrate. No consumer impact because step 6 has not run |
| Concurrent rebuilds corrupt Dhara state | Low | Lock with stale-PID detection; second script aborts cleanly |
| Dhara unreachable breaks `bodai-status` / `mahavishnu-status` | Medium | During 14-day dual-read window, filesystem read is fallback; degraded envelope on read returns cached_at_ms |
| Trip-wire fires unexpectedly (high query count from automation) | Medium | Trip-wire action is opt-in; in v1, ratio is recorded but no push surface ships |
| 14-day decommission window too short for stability | Low | Decommission is delayed if `/health` shows any 503 in the prior 7 days |
| `scripts/audit_requirements.py` frontmatter schema drift | Low | Reuse existing schema; if schemas diverge, `audit_plan_index.py` becomes the source of truth |

## Out of scope (deferred)

- Layer 4 (task queue + scheduler). Substrate is delivered; queue
  design is a follow-on spec.
- Session-Buddy semantic search for plans. Match jot's v1 → v1.1
  upgrade path.
- Cross-team federation (Mahavishnu + Akosha + Dhara + Crackerjack +
  Session-Buddy). Record carries `repo`; future spec adds a
  `--repos` flag to the regenerator.
- Worktree-aware reading (operators testing a feature branch want
  to see what their branch's plans look like). Deferred; not
  blocking v1.

## References

- `docs/superpowers/specs/2026-09-09-jot-inbox-design.md` — pattern
  template (three-layer topology, fail-open, trip-wire)
- `docs/superpowers/specs/2026-09-09-jot-read-design.md` — pure
  function split pattern
- `docs/superpowers/specs/2026-09-09-jot-capture-design.md` —
  capture-path discipline
- `docs/plans/2026-09-10-bodai-math-initiatives-tier1.md` —
  `scripts/feature_eligibility.py` becomes a single Dhara query
  after this spec lands
- `docs/plans/TEMPLATE.md` — Integration Contract format
- `docs/plans/PLAN_INDEX.md` — the artifact this spec transforms
  from "filesystem scanner output" to "Dhara-fed render"
- `.claude/decisions/mcp-backend-wiring-discipline.md` — feed-state
  requirement
- `.claude/decisions/wire-up-contract.md` — Integration Contract
  requirement for every feature
- `.claude/decisions/followups-lifecycle.md` — `docs/followups/`
  lifecycle (Layer 4 sketch uses this)
- `.claude/decisions/dhara-key-prefixes-2026-07-15.md` — Dhara key
  naming convention
- `mahavishnu/pools/fitness_analyzer.py:279` — `task_classes`
  list that the cron-rebuild joins
- `scripts/audit_requirements.py` — frontmatter validation reused
  for the pre-flight check
- `scripts/audit_orphans.py` — wire-up contract's orphan gate
