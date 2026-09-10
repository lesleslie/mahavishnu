---
role: implementation
topic: plan-index-dhara
status: draft
date: 2026-09-10
last_reviewed: 2026-09-10
superseded_by: null
blocks_on:
  - docs/superpowers/specs/2026-09-09-jot-inbox-design.md
requirements:
  - id: REQ-PLAN-001
    title: "Dhara is the canonical store for plan metadata"
  - id: REQ-PLAN-002
    title: "Git remains the only write path for plan content"
  - id: REQ-PLAN-003
    title: "PLAN_INDEX.md on disk is regenerated from Dhara, not from filesystem scan"
  - id: REQ-PLAN-004
    title: "All five new MCP tools (plan_list, plan_show, plan_search, plan_vitals, plan_rebuild_status) return TypedDicts, no Any"
  - id: REQ-PLAN-005
    title: "/health reports plan_index feed state via plan_index:meta:meta keys with the four mandatory signals plus an ok key"
  - id: REQ-PLAN-006
    title: "Rebuild runs in a dedicated PeriodicTaskRunner, not fitness_analyzer task_classes"
  - id: REQ-PLAN-007
    title: "RELEASE-DRIVEN (D10) decommission of filesystem read path requires conditional on jot sub-plan 3 ship"
  - id: REQ-PLAN-008
    title: "scripts/audit_plan_index.py is wired into CI alongside scripts/audit_orphans.py and crackerjack docs validate"
  - id: REQ-PLAN-009
    title: "docs/feature-tracking/plan-index-dhara.md exists and tracks built/wired/adopted"
---

# Plan Index — Dhara-Canonical Metadata Layer

> **Design status:** draft, awaiting reviewer sign-off (2026-09-10).
> Built through the superpowers:brainstorming flow across three sections,
> revised after a 5-agent pentaverate review (architecture, Mahavishnu
> integration, Akosha, MCP, wire-up discipline). Inline fixes per the
> BLOCKER + HIGH findings from that review are reflected in this version.

## Problem

`docs/plans/PLAN_INDEX.md` is the navigation map for Mahavishnu and the
broader Bodai ecosystem's plan/decisions/followups/feature-tracking/ADR
catalogue. Today it is generated mechanically by
`scripts/regenerate_plan_index.py`, which auto-discovers stores
(`MIN_STORE_DOCS = 2` plus a frontmatter walk — the actual count varies
as new stores are added), parses YAML frontmatter, and renders a
markdown table.

Three failure modes the current design cannot address:

1. **Serverless / container runtime** — the scanner needs the discovered
   stores on the local filesystem; a serverless bundle typically does
   not ship `.claude/decisions/` or `docs/adr/`, so the index cannot be
   regenerated at runtime.
2. **Cross-machine visibility** — every clone regenerates a different
   `PLAN_INDEX.md`. A developer on a laptop and a colleague on a
   workstation see different views with no easy way to merge.
3. **Action orientation** — the index is read-only. The math plan's
   `scripts/feature_eligibility.py` (Phase 9) polls two MCP endpoints
   plus a frontmatter file and a query log to fire tier-2 follow-up
   triggers. A scheduler that drives work out of plans needs a
   queryable index, not a static file.

The jot inbox design (`docs/superpowers/specs/2026-09-09-jot-inbox-design.md`)
established the project's canonical pattern for this class of problem
(write → derive → query). This spec applies that pattern to plans,
**inverting the canonical axis for writes** because plans are reviewable
code (git canonical) while jots are quick thoughts (Dhara canonical).
Both use the same **read substrate topology** (Dhara canonical,
downstream derives from it).

## Goals

1. **Cross-machine plan visibility** — any Mahavishnu process reading
   the index sees the same set of active/partial/canonical plans,
   regardless of which machine holds the source-of-truth `.md` file.
2. **Serverless compatibility** — a serverless bundle that ships only
   the renderer (not the discovered stores) can serve the index by
   reading from a portable substrate.
3. **Single canonical schema for the math-plan `feature_eligibility.py`
   followup/feature-tracking half** — `mcp__mahavishnu__plan_list` /
   `plan_vitals` become a single Dhara query, not four ad-hoc MCP polls.
4. **`/health` compliance** — per `.claude/decisions/mcp-backend-wiring-discipline.md`,
   `plan_index` reports the four mandatory feed signals plus an `ok`
   key required by `mahavishnu/mcp/bootstrap.py:289`'s `all_ok`
   reduction.
5. **Git stays the only write path** — no review-process regression;
   `crackerjack docs validate` and `mcp__crackerjack__crackerjack_doc_frontmatter_validate`
   remain authoritative for frontmatter validation; `scripts/audit_requirements.py`
   is reserved for REQ-ID traceability, not frontmatter.

## Non-goals

1. **Not** replacing git as the canonical store for plan content.
2. **Not** adding a cloud bucket mirror. Dhara is the substrate.
3. **Not** shipping Layer 4 (task queue + scheduler) in this spec —
   sketched only, deferred to a follow-on. A reconciliation ticket
   against `scripts/feature_eligibility.py` (math plan §6 Phase 9)
   must land before Layer 4 ships; the spec's deferral note is
   explicit about this.
4. **Not** semantic search via Session-Buddy in v1 — lexical match
   on `title` + `topic` only. Trigger for adding Session-Buddy is
   *not* the jot "drain freshness" gate (plans have no drain problem
   — the cron bounds freshness to ≤ `cron_every_seconds`). The real
   unlock conditions are: (a) corpus exceeds ~500 entries, OR (b) lex
   noise on `title`+`topic` outweighs precision gains, OR (c) the
   Dhara change-feed primitive lands.
5. **Not** cross-team federation in v1 — the record carries `repo`
   so the future federation is a CLI flag, but v1 reads Mahavishnu
   only.

## Decisions

### D1 — Dhara as the canonical metadata store
Plan content stays in git; **plan metadata** (frontmatter fields) lives
in Dhara. Cross-machine visibility is Dhara's existing replication,
which jot sub-plan 3 will harden — we ride that work. This spec
**blocks on** `docs/superpowers/specs/2026-09-09-jot-inbox-design.md`'s
sub-plan 3 (drain hardening) for the cross-machine slice; the local
substrate works without it.

### D2 — Git as the only write path
Promoters edit `.md` files and open PRs as today. There is no new
write step for promoters. The rebuilder reads git, parses frontmatter,
upserts to Dhara. **Includes** `docs/feature-tracking/*.md`
frontmatter (the `built/wired/adopted` lifecycle vocabulary, see
`PlanRecord.lifecycle_state` below).

### D3 — `scripts/regenerate_plan_index.py` rewritten as three phases
- **Phase A** (existing): filesystem walk + frontmatter parse → list of records
- **Phase B** (new): upsert records to Dhara
- **Phase C** (refactored): render markdown from Dhara → write `PLAN_INDEX.md`

Phase B is `PlanIndexRebuilder.upsert_all(records)` (pure function over
`(records, current_dhara_state) → upserts`). Phase C splits into two
modules: `PlanIndexRenderer.render(records) -> str` (pure) and a thin
`PlanIndexWriter.write(md, path)` (I/O). The CLI is the thin
orchestrator. The CLI keeps the existing six flags
(`--dry-run`, `--out`, `--stores`, `--extra-stores`, `--json-summary`,
`--repo-root`) and adds three: `--check` (snapshot diff, fail if
different), `--skip-render` (Dhara-only), `--rebuild-from` (one-shot
backfill from git history). `--check` is documented as **not
equivalent to `--dry-run`** — the former asserts byte-equivalence with
the current `PLAN_INDEX.md`, the latter prints to stdout.

### D4 — `plan_id` derivation includes `repo`
`plan_id = sha256(f"{repo}:{path}").hexdigest()[:32]` where `path` is
**repo-relative, POSIX-separated** (e.g. `docs/plans/2026-09-15-foo.md`).
Two repos with `docs/plans/foo.md` do not collide. On the
(statistically impossible) collision, the rebuilder appends a counter
suffix (`<base>-2`, `<base>-3`, …) and logs to `errors.log`. This is
forward-compatible with the deferred cross-team federation.

### D5 — Two-tier `/health` staleness alerts
Per `mcp-backend-wiring-discipline.md` §3 ("alert when
`last_updated_timestamp` is older than `5 × polling_interval`") the
plan_index feed surfaces two distinct alerts:

| Alert | Threshold | Aggregation role |
|---|---|---|
| `feed.alive_but_silent` | `5 × cron_every_seconds` = 5 hours at default | Soft warning; degraded envelope on read |
| `feed.rebuild_abandoned` | 7 days | Hard `ok=False`; `get_health()` returns 503 (via `bootstrap.py:289` `all_ok` reduction) |

`health_stale_after_days: 7` covers the "cron died" case.
`poll_silent_after_hours: 5` covers the "feed hangs but doesn't
return error" case. Both feed into the same `last_updated_timestamp`
key; the wiring contract reads it through two different windows.

### D6 — Recency-staleness trip-wire (replaces jot's ratio math)
The spec does NOT copy jot Decision 5's `capture_review_ratio > 10:1`
pattern. That ratio is broken for plans: under v1 the read paths
(bodai-status, mahavishnu-status, agent reviews) produce 50–200
`plan_*` reads per hour per session, while edits happen 0–3 times per
day. A 10:1 ratio fires by definition within the first weekend
post-cutover and tells us nothing.

The trip-wire that actually fires is **recency-staleness**:

```
plan_edit_count_30d == 0
  AND last_edit_lag_ms > 86_400_000      # > 24h since last edit
  AND plan_query_count_30d > 0          # someone is reading
```

When this combination holds for 7 consecutive days, surface the hint
"no edits in 7 days despite N reads — review the staleness." This is
the equivalent of "review cadence lagging" for plans.

In v1 the trip-wire is recorded in `plan_vitals()` only — no action,
no push surface. The unlock condition for adding a push surface is:
either (a) 30 days of stable vitals data, OR (b) a user reports they
want the hint on Slack/email. The `pre-commitment` lock mirrors jot
Decision 5: if the trip-wire is added, it ships once and only once.

### D7 — Profile tier placement and skill migration
The five `mcp__mahavishnu__plan_*` tools ship in **FULL** only. STANDARD
tier (the default per `MAHAVISHNU_TOOL_PROFILE=standard`, which is most
production installs) reads `docs/plans/PLAN_INDEX.md` on disk —
**indefinitely**, not for 14 days. The 14-day decommission window in
migration step 8 applies to the two named skills (`bodai-status`,
`mahavishnu-status`) switching from filesystem read to MCP read; the
disk file itself remains a supported read artifact for humans,
STANDARD profile, and MINIMAL profile indefinitely.

Rationale for FULL-only tool placement (per `mahavishnu/mcp/tools/profiles.py`
precedent): `_register_search_tools`, `_register_treesitter_tools`,
`_register_pycharm_tools`, `_register_clone_tools` all live in FULL.
This is the same posture. The "same posture as jot" framing is a
fiction (jot_tools.py is unwired as of this writing — flagged in
followups); the controlling precedent is the FULL-only placement of
the four tool groups above.

### D8 — CLI-only rebuild (right decision, correct rationale)
`mcp__mahavishnu__plan_rebuild` does **not** ship. The tool
`plan_rebuild_status` is read-only and correctly safe. The actual
rebuild is `python scripts/regenerate_plan_index.py` or the
`PeriodicTaskRunner` (D9).

The foot-gun rationale from v0 is replaced with three concrete risks:

1. **Filesystem dependency inversion.** Phase A requires the
   discovered stores on local disk. Goal 2 explicitly targets
   serverless bundles that *don't ship them*. An MCP-triggered
   rebuild would 500 in exactly the deployment the spec is designed
   for.
2. **Unreviewed write to a tracked git file.** Phase C writes
   `docs/plans/PLAN_INDEX.md`. An MCP tool that dirties a tracked
   file from an agent turn conflicts with D2 and can collide with
   an in-flight branch.
3. **Cost.** A scan of the discovered stores + N Dhara upserts is
   not an interactive-latency operation; ~150 files × ≤300 ms each
   is 30–45 seconds.

The lock design + idempotency invariants in the rebuilder
adequately address the "race with live edits" worry; that was not
the real risk.

### D9 — Dedicated `PeriodicTaskRunner`, not `fitness_analyzer` task_classes
The cron lives in `mahavishnu/plan_index/cron.py::PeriodicTaskRunner`,
NOT in `mahavishnu/pools/fitness_analyzer.py:279`. The latter's
`task_classes` list is consumed by `_collect_traces(task_class)` which
calls `client.query_local_traces(...)` — it is an OTel trace-tag
filter, not a periodic-task registry. Appending
`"plan_index_rebuild"` would cause `_collect_traces` to return empty
and `continue` — a silent no-op.

`PeriodicTaskRunner`:
- asyncio sleep loop with per-task interval
- per-task lock with stale-PID detection (Dhara key
  `plan_index/meta/rebuild_lock/{hostname}/{pid}` with TTL=60s)
- per-task DLQ for Dhara write failures
- registered in `MahavishnuApp.__init__` next to where `fitness_analyzer`
  is wired
- handler signature: `async def rebuild_handler(app) -> None`

The math plan §7 cross-repo follow-on (the planned `routing_change_point`
extension to the same plumbing) converges on this same module — the
coordination doc is updated to reference `plan_index/cron.py` not
`fitness_analyzer.py:279`.

### D10 — Decommission window conditional on jot sub-plan 3
Migration step 8 (filesystem-read decommission in the two named
skills) fires at the later of (a) this spec's cut-over + 14 days, or
(b) jot sub-plan 3 ship date + 14 days. Past jot-sub-plan-3 lands the
cross-machine Dhara replication is hardened; until then, the
filesystem read is the durable backup. PLAN_INDEX.md itself remains
a supported read artifact indefinitely (per D7).

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 4: Action surface (DEFERRED, sketched only)                │
│   ┌──────────────────────────┐   ┌────────────────────────┐      │
│   │ plan_task_queue           │   │ plan_scheduler         │      │
│   │ (Dhara-backed queue,     │   │ (cron-like, reads      │      │
│   │  pops plan-derived work)  │   │  blocks_on graph)      │      │
│   └──────────┬────────────────┘   └────────────┬───────────┘      │
│              │  reads/writes Dhara            │  reads Dhara     │
│   ┌──────────┴────────────────────────────────┴───────────┐      │
│   │ Layer 3: Plan index in Dhara                            │      │
│   │   primary key prefix:  plan_index/{plan_id}            │      │
│   │   secondary prefixes:  plan_index/status/…             │      │
│   │                       plan_index/topic/…               │      │
│   │   meta key prefix:     plan_index/meta/…               │      │
│   └──────────────────┬───────────────────────────────────────┘      │
│                      │                                            │
│   ┌──────────────────┴───────────────────────────────────────┐      │
│   │ Layer 2: Re-deriver + Re-renderer (CLI orchestrator)     │      │
│   │   scripts/regenerate_plan_index.py                       │      │
│   │     Phase A: scan discovered stores (filesystem)         │      │
│   │     Phase B: PlanIndexRebuilder.upsert_all → Dhara       │      │
│   │     Phase C: PlanIndexRenderer.render →                   │      │
│   │              PlanIndexWriter.write → PLAN_INDEX.md       │      │
│   └──────────────────┬───────────────────────────────────────┘      │
│                      │  reads git (filesystem)                    │
│   ┌──────────────────┴───────────────────────────────────────┐      │
│   │ Layer 1: Git — UNCHANGED                                 │      │
│   │   .md files in docs/plans/, .claude/decisions/,           │      │
│   │   docs/adr/, docs/followups/, docs/feature-tracking/     │      │
│   │   (auto-discovered by `regenerate_plan_index.py`)        │      │
│   └──────────────────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────────────┘
```

### Read paths after the change

- **Humans**: read `docs/plans/PLAN_INDEX.md` (a *rendered artifact*
  whose header carries `<!-- Last regenerated: YYYY-MM-DD HH:MM:SS UTC
  · run mcp__mahavishnu__plan_rebuild_status for staleness check -->`).
  Indefinitely.
- **AI agents in-session**: `mcp__mahavishnu__plan_list` /
  `plan_show` / `plan_search` / `plan_vitals` / `plan_rebuild_status`
  (FULL profile only).
- **`bodai-status` / `mahavishnu-status` skills** (FULL profile):
  read via MCP tools. (STANDARD profile continues to read
  `PLAN_INDEX.md` indefinitely; this spec does not migrate the
  STANDARD read path.)

### Write paths after the change

- **Promoters**: edit `.md` files in git as today; no new write step.
- **Cross-machine readers**: Dhara's existing replication (jot
  sub-plan 3 will harden this).

## Components

| Component | Location | Purpose |
|---|---|---|
| `PlanIndexStore` (new) | `mahavishnu/plan_index/store.py` | Dhara-backed metadata CRUD. The only file that imports Dhara. Maintains `plan_index/meta/entities_count` as an explicit counter (not derived from `len(keys(...))`). |
| `PlanIndexRebuilder` (new) | `mahavishnu/plan_index/rebuild.py` | Pure function: list of frontmatter dicts → list of `PlanRecord`. SHA computed from `git hash-object` of the blob. No I/O. |
| `PlanIndexRenderer` (new) | `mahavishnu/plan_index/render.py` | Pure function: list of `PlanRecord` → `PLAN_INDEX.md` markdown string. Emits the staleness-header. No I/O. |
| `PlanIndexWriter` (new) | `mahavishnu/plan_index/writer.py` | Thin I/O wrapper: writes the rendered string to disk. |
| `PlanIndexErrors` (new) | `mahavishnu/plan_index/errors.py` | `PlanIndexError` base + `PlanNotFoundError`, `PlanIndexUnavailableError`, `PlanRebuildLockedError`, `PlanAmbiguousHandleError`. Mirrors `mahavishnu/jot/errors.py` discipline (TD-B2). |
| `PlanIndexHealth` (new) | `mahavishnu/plan_index/health.py` | `PlanIndexFeedState` (frozen, slots). Mirrors `mahavishnu/mcp/signer_feed.py::SignerFeedState` exactly — `as_dict()` returns `{"ok": bool, "entities_count": int, "last_updated_timestamp": int, "errors_total": int, "cycles_total": int, "successful_cycles_total": int}`. Registered via `register_health_endpoint` (`mahavishnu/mcp/bootstrap.py:268`) as a new `checks["plan_index"]` branch. |
| `PeriodicTaskRunner` (new) | `mahavishnu/plan_index/cron.py` | Asyncio loop hosting the rebuild task. Per-task lock + DLQ. NOT in `fitness_analyzer`. |
| `RegeneratePlanIndexCLI` (rewritten) | `scripts/regenerate_plan_index.py` | Orchestrator. Existing six flags preserved (`--dry-run`, `--out`, `--stores`, `--extra-stores`, `--json-summary`, `--repo-root`); three new (`--check`, `--skip-render`, `--rebuild-from`). |
| `mcp__mahavishnu__plan_*` (new tool group) | `mahavishnu/mcp/tools/plan_tools.py` | 5 tools. Returns TypedDicts (no `Any`). `plan_show` raises `PlanNotFoundError` (FastMCP-serialized) instead of returning `null`. `plan_rebuild_status` returns a structured envelope (never raises for "rebuild never ran yet"). |
| `mahavishnu plan …` CLI (new) | `mahavishnu/cli/plan_cli.py` | Mirrors MCP tools for shell use. |
| `docs/feature-tracking/plan-index-dhara.md` (new) | `docs/feature-tracking/` | Tracks `{built, wired, adopted}` lifecycle per `wire-up-contract.md` §4. |
| `scripts/audit_plan_index.py` (new) | `scripts/` | Three-way disk/index/Dhara consistency check. Wires into CI alongside `scripts/audit_orphans.py` and `crackerjack docs validate`. |

### Migration 5-edit dance (verbatim)

Per `mahavishnu/mcp/tools/profiles.py` precedent, the actual edits:

1. `mahavishnu/mcp/bootstrap.py` — add `def _register_plan_tools(server: FastMCPServer) -> None:` calling `plan_tools.register(server.server, ...)`.
2. `mahavishnu/mcp/tools/profiles.py` import block (lines 34–60) — add `from .bootstrap import _register_plan_tools`.
3. `mahavishnu/mcp/tools/profiles.py:93–102` `FULL_REGISTRATIONS` — add `"_register_plan_tools"` to the FULL-tier list.
4. `mahavishnu/mcp/tools/profiles.py:178–186` `REGISTRATION_MAP` (FULL section) — add `"_register_plan_tools": lambda s: _register_plan_tools(s._mhv_server)`.
5. CI guard test (`tests/unit/mcp/test_tool_profile_drift.py` or
   `tests/unit/test_mcp_tool_inventory.py`) — assert that every
   `PROFILE_REGISTRATIONS` key has a matching `REGISTRATION_MAP` entry,
   and that `FULL_REGISTRATIONS ⊇ STANDARD_REGISTRATIONS`. Both guards
   exist as precedents for the jot spec's BLOCKER TD-B1.

## Data Model

### `PlanRecord` dataclass

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class PlanRecord:
    plan_id: str                 # sha256(f"{repo}:{path}").hexdigest()[:32]
                                 # On collision: append counter suffix.
    path: str                    # repo-relative, POSIX-separated, e.g.
                                 # "docs/plans/2026-09-15-foo.md"
    title: str                   # H1 / first heading from the .md body
    status: Literal[
        "draft", "active", "partial", "shipped", "complete"
    ]
    role: Literal[
        "canonical", "implementation", "umbrella",
        "historical", "superseded"
    ]
    topic: str                   # frontmatter topic
    date: str                    # YYYY-MM-DD
    last_reviewed: str           # YYYY-MM-DD
    superseded_by: str | None
    blocks_on: list[str]         # list of plan_ids this plan depends on
    sha: str                     # git blob SHA at rebuild time
    repo: str                    # git remote URL (raw; no normalization in v1)
    id: str | None               # optional frontmatter id for cross-repo referencing
    lifecycle_state: Literal[
        "built", "wired", "adopted"
    ] | None = None              # feature-tracking docs only; None otherwise
    updated_at_ms: int           # server-set timestamp
```

### TypedDicts (CLAUDE.md "no Any" rule — REQ-PLAN-004)

```python
class PlanRecordDict(TypedDict):
    plan_id: str
    path: str
    title: str
    status: str
    role: str
    topic: str
    date: str
    last_reviewed: str
    superseded_by: str | None
    blocks_on: list[str]
    sha: str
    repo: str
    id: str | None
    lifecycle_state: str | None
    updated_at_ms: int


class PlanVitalsDict(TypedDict):
    total: int
    by_status: dict[str, int]
    by_role: dict[str, int]
    by_topic_top10: list[tuple[str, int]]
    last_rebuild_ms: int | None
    last_success_ms: int | None
    oldest_active_ms: int | None
    cycles_total: int
    successful_cycles_total: int
    errors_total: int
    recent_errors: list[PlanRebuildErrorDict]
    tripwire: "ok" | "no_recent_edits" | "no_recent_reads" | "ok"   # 4 states; recorded only in v1


class PlanRebuildStatusDict(TypedDict):
    last_rebuild_ms: int | None
    last_success_ms: int | None
    cycles_total: int
    successful_cycles_total: int
    errors_total: int
    recent_errors: list[PlanRebuildErrorDict]
    lock_held_by: str | None       # "{hostname}/{pid}" or None
    lock_age_ms: int | None
    stale: bool                    # last_rebuild older than 5× cron interval


class PlanRebuildErrorDict(TypedDict):
    ts_ms: int
    op: str                        # "scan" | "upsert" | "render" | "lock" | "..."
    err: str
    ctx: dict[str, str | int | None]


class PlanDegradedDict(TypedDict):
    status: Literal["degraded"]
    reason: str
    cached_at_ms: int | None


class PlanListResultDict(TypedDict):
    plans: list[PlanRecordDict]
    total: int                     # total matches before limit
    cached_at_ms: int | None       # set when status="degraded"
    status: Literal["ok", "degraded"]
```

### Dhara key conventions (REQ-PLAN-001)

Mirror `.claude/decisions/dhara-key-prefixes-2026-07-15.md` (slash
separator, no trailing path component in prefix, producer appends
subpath):

| Prefix | TTL | Notes |
|---|---|---|
| `plan_index/{plan_id}` | 24 h | Primary record; regenerable from git |
| `plan_index/status/{status}/{date}/{plan_id}` | inherits primary | Secondary index, lex order = chronological within status |
| `plan_index/topic/{topic}/{date}/{plan_id}` | inherits primary | Secondary index, lex order = chronological within topic |
| `plan_index/meta/last_rebuild_ms` | none | Timestamp; feeds the `/health` staleness alerts |
| `plan_index/meta/last_success_ms` | none | Timestamp of most recent successful cycle |
| `plan_index/meta/entities_count` | none | Explicit counter written by rebuilder; not derived from `len(keys(...))` (which would over-count secondary indexes and lock keys) |
| `plan_index/meta/errors_total` | none | Cumulative counter |
| `plan_index/meta/cycles_total` | none | Increments on every rebuild ATTEMPT (not just success) — per wiring-discipline §3 ("incremented each polling cycle") |
| `plan_index/meta/successful_cycles_total` | none | Counter of cycles where all writes succeeded |
| `plan_index/meta/migration_pre_flight_errors` | 7 d | Transient diagnostic; auto-expires after migration |
| `plan_index/meta/rebuild_lock/{hostname}/{pid}` | 60 s | Stale-PID takeover eligible |
| `plan_index/meta/recent_errors` | 30 d | Bounded JSON list (last 20 errors) for `plan_rebuild_status` |

Note: slash separator is required by `dhara-key-prefixes-2026-07-15.md`;
the colon-separated form in v0 of this spec was a deviation and is
corrected here.

### Wire-up discipline feed-state contract (REQ-PLAN-005)

`PlanIndexFeedState.as_dict()` returns:

```python
{
    "ok": <bool>,                              # REQUIRED by bootstrap.py:289
    "entities_count": <int>,
    "last_updated_timestamp": <int>,            # epoch ms of last_rebuild_ms
    "errors_total": <int>,
    "cycles_total": <int>,
    "successful_cycles_total": <int>,           # per wiring-discipline, separate
}
```

`ok` is computed by `PlanIndexFeedState.is_ok()` which checks
`last_updated_timestamp > now - 5 × cron_every_seconds × 1000`. The
`/health` endpoint returns 503 if any `checks["*.ok"]` is False, per
`bootstrap.py:289`'s `all_ok` reduction.

Registration is a new branch in `register_health_endpoint` at
`mahavishnu/mcp/bootstrap.py:279–288`:

```python
state = get_plan_index_feed_state()
if state is None:
    checks["plan_index"] = {"ok": False, "error": "awaiting start()"}
else:
    checks["plan_index"] = state.as_dict()
```

This mirrors the existing `skills_signer` branch exactly.

## Data flow

### Single-plan lifecycle (the happy path)

```
1. Promoter edits docs/plans/2026-XX-XX-<topic>.md in a git branch
   ↓ (git commit, push, PR review, merge to main)
2. Repo main now has the new .md with new frontmatter
   ↓
3. PeriodicTaskRunner fires every cron_every_seconds (default 3600s)
   ↓ Phase A: filesystem scanner reads all .md frontmatter
              (auto-discovers stores via MIN_STORE_DOCS=2)
   ↓ Phase B: PlanIndexRebuilder.upsert_all(records) writes to Dhara
              (one transaction per record; failed records logged)
              Updates plan_index/meta/entities_count
              Increments plan_index/meta/cycles_total
              Increments plan_index/meta/successful_cycles_total on full success
              Updates plan_index/meta/last_rebuild_ms and last_success_ms
   ↓ Phase C: PlanIndexRenderer.render(records) → markdown string
              PlanIndexWriter.write(md, PLAN_INDEX.md)
   ↓
4. OTel span `plan_index.rebuild` emitted with attributes:
     records_upserted, records_skipped, duration_ms, errors_total,
     cycles_total, lock_held_by
5. EventBridge topic `plan_index.rebuild.completed` published via
   Oneiric EventBridge (`bodai-observability-pattern.md`)
6. Prometheus metric `mahavishnu.plan_index.rebuild.duration`
   histogram incremented
7. /health aggregates: plan_index.ok computed from
   last_updated_timestamp; checks["plan_index"] updated
8. Read paths see the new state
```

### Cross-machine read path

```
Machine A (developer laptop):
  plan_edit on docs/plans/2026-09-15-foo.md → git push → machine B
  ↓
Machine B (server / serverless runtime):
  git pull (or shared cache) → PeriodicTaskRunner fires (if not already)
  ↓
  mcp__mahavishnu__plan_list({status: "active", topic: "routing"})
  ↓
  PlanIndexStore reads Dhara:8683 (replicated from machine A's upsert)
  ↓
  returns PlanListResultDict
```

### Lock acquisition (concurrent rebuilds)

```
Rebuilder starts → set plan_index/meta/rebuild_lock/{hostname}/{pid}
  with TTL = 60s (longer than expected rebuild duration, shorter than
                  cron interval)
↓
If lock exists:
  Check TTL — if expired, take lock (stale-PID)
  Else, abort with "another rebuild in progress"
↓
On completion (success or partial failure):
  delete lock key
```

The TTL uses Dhara's put-with-TTL primitive (per
`mahavishnu/pools/fitness_analyzer.py:245` precedent: `dhara_state.put(key, value, ttl=N)`).
Stale-PID detection compares `lock_acquired_at_ms` against
`plan_index/meta/last_rebuild_ms` — if the latter is older than 2×
the lock TTL, the lock is orphan.

## Rebuilder invariants (stated, testable)

1. **Idempotency** — running the rebuilder twice in a row produces
   the same Dhara state (upserts by `plan_id`). **Requires Dhara
   upsert-by-ID semantics** — see Open Question #1; the migration
   must verify empirically before step 3 runs.
2. **Drift detection** — if `path` exists on disk but is missing
   from Dhara, the rebuilder inserts it. If `path` is in Dhara but
   missing on disk (deleted/renamed), the rebuilder marks it
   `historical` with a tombstone rather than deleting (preserves
   audit trail).
3. **Frontmatter validation** — invalid frontmatter (missing
   `status` or `role`, unknown enum values) causes that record to
   be **logged to errors and skipped**, not inserted. Validation
   uses **`crackerjack docs validate`** (per
   `docs/schemas/document-frontmatter-v1.md`'s Crackerjack Surface
   section), NOT `scripts/audit_requirements.py` — the latter
   is for REQ-ID traceability, not frontmatter validation.
4. **Git as source of truth** — the rebuilder reads from the
   **filesystem view of main**, never from a worktree, never from a
   feature branch's checkout. Worktrees are excluded by path
   (existing scanner already excludes `.claude/worktrees/`).
5. **`repo` resolution** — the rebuilder reads `.git/config` files
   directly (no subprocess) and parses `[remote "origin"] url`. Raw
   URL string, no normalization in v1 (normalization belongs to the
   deferred federation follow-on).
6. **`sha` field** — set to the git blob SHA of the `.md` file at
   rebuild time (via `git hash-object`). Read paths may return
   stale metadata if the rebuild hasn't re-run since the file
   changed; acceptable for day-scale lifecycle.
7. **`entities_count` is explicit** — written by the rebuilder as
   `plan_index/meta/entities_count` at end-of-cycle. Not derived
   from `len(keys("plan_index:*"))` (that would over-count secondary
   indexes and lock keys by 3×).

## Read-path invariants

1. **`mcp__mahavishnu__plan_show(plan_id)`** returns the
   `PlanRecordDict`. If the record is missing, raises
   `PlanNotFoundError` (FastMCP-serialized). If Dhara is
   unreachable, raises `PlanIndexUnavailableError` (also serialized)
   AND the caller sees the degraded envelope shape via a separate
   `plan_show_safe` tool. Discriminated via the error class, not a
   `status` field on a successful return.
2. **`mcp__mahavishnu__plan_list({status, topic, date_from, date_to})`**
   uses the secondary indexes (`plan_index/status/{status}/...` and
   `plan_index/topic/{topic}/...`). Lex order = chronological within
   filter. Returns `PlanListResultDict`.
3. **`mcp__mahavishnu__plan_search(query)`** returns lexical matches
   on `title` + `topic` from Dhara's primary key prefix scan
   (full-table scan; O(N) acceptable at ~500 records). No
   Session-Buddy semantic search in v1.
4. **`mcp__mahavishnu__plan_vitals()`** returns `PlanVitalsDict`.
   Includes `tripwire` field with 4 states
   (`"ok" | "no_recent_edits" | "no_recent_reads" | "ok"`); in v1
   the field is recorded only — no surface action.
5. **`mcp__mahavishnu__plan_rebuild_status()`** returns
   `PlanRebuildStatusDict`. Read-only and safe.

## Error handling

### The cardinal rule

**The rebuilder never destroys Dhara state on partial failure.**
Mirrors the jot spec's "never erase text you failed to store."

| Failure | Behavior | Recovery |
|---|---|---|
| Git working tree has uncommitted changes | Rebuild aborts; Dhara unchanged | Commit, re-run |
| Unparseable `.md` (bad YAML, missing field) | Logged to errors; rebuild continues | Fix frontmatter via Crackerjack, re-run |
| Dhara write fails for one record | Logged to errors; `errors_total` incremented; rebuild continues | `mcp__mahavishnu__plan_rebuild_status` exposes last errors; re-run |
| Dhara write fails for **all** records | Rebuild aborts; `cycles_total` incremented (per wiring-discipline); `successful_cycles_total` NOT incremented; `last_rebuild_ms` NOT updated; partial Dhara state preserved | `/health` returns 503 within 5h (poll_silent alert); investigate; re-run |
| Dhara unreachable on read | Tool raises `PlanIndexUnavailableError`; caller catches and falls back to `plan_show_safe` which returns `PlanDegradedDict` with `cached_at_ms` | Operator checks `/health` |
| Renderer markdown write fails (disk full) | Rebuild succeeds in Dhara; PLAN_INDEX.md shows previous render; warning logged | Manual re-render once disk freed |
| Concurrent rebuilds | Second script sees stale-lock, aborts with clear error | First wins; second evaluates after first completes |

### Error hierarchy (`mahavishnu/plan_index/errors.py`)

```python
class PlanIndexError(Exception):
    """Base class for all plan_index errors."""

class PlanNotFoundError(PlanIndexError):
    """plan_id matched no record."""

class PlanIndexUnavailableError(PlanIndexError):
    """Dhara unreachable; caller should fall back."""

class PlanRebuildLockedError(PlanIndexError):
    """Another rebuild holds the lock."""

class PlanAmbiguousHandleError(PlanIndexError):
    """Handle matched multiple records."""
```

Subclasses carry structured context (`candidates: list[str]` on
`PlanAmbiguousHandleError`). Mirrors the jot discipline that earned
BLOCKER TD-B2 in the original review.

## Migration plan

The existing ~150+ markdown files across the discovered stores
provide valid frontmatter. The first run of the new rebuilder is a
**migration**, not a feature:

1. **Pre-flight check** — script reads every `.md`, asserts all
   required fields present (per `document-frontmatter-v1.md`).
   Files with missing fields are listed in
   `plan_index/meta/migration_pre_flight_errors`; migration aborts.
   Validate via `crackerjack docs validate --strict` (NOT
   `audit_requirements.py`).
2. **Investigate and fix** — operator runs `crackerjack docs validate
   --allow-nonstandard` to surface non-conforming files; fix
   frontmatter.
3. **Migration run** — script reads every `.md`, upserts to Dhara
   with `migration: true` flag. Cycles_total=1,
   successful_cycles_total=1, errors_total=0.
4. **Render and commit** — script renders `PLAN_INDEX.md` from
   Dhara, writes it to disk, opens a one-time commit titled
   `chore(plan_index): first Dhara-fed rebuild`.
5. **Verify (snapshot test, NOT byte diff)** — run
   `tests/integration/plan_index/test_render_matches_old_scanner.py`
   which compares the new render to a golden file checked in at
   `tests/integration/plan_index/fixtures/PLAN_INDEX.golden.md`.
   The first run *creates* the golden (operator review + commit);
   subsequent runs diff against it. If the renderer is intentionally
   improved, the golden is updated in the same commit and the test
   updated to match. **The byte-equivalence gate from v0 is replaced**
   because even trivial formatting drift (anchor ordering,
   trailing-newline, header capitalization) would fail it.
6. **Wire MCP tools** — apply the 5-edit dance (enumerated above).
   Make CI guards green.
7. **Cut over `bodai-status` / `mahavishnu-status` skills** (FULL
   profile installs only) — change skill bodies to call MCP tools
   in parallel with reading `PLAN_INDEX.md`. STANDARD-profile
   installs continue reading `PLAN_INDEX.md`.
8. **Decommission** — at the **later of** (a) this spec's cut-over
   + 14 days, or (b) jot sub-plan 3 ship date + 14 days, the
   filesystem-read branch is removed from the two named skills.
   `PLAN_INDEX.md` itself remains a supported read artifact for
   humans, STANDARD profile, and MINIMAL profile indefinitely
   (per D7). The `docs/feature-tracking/plan-index-dhara.md` file
   must record `adopted` before this step.

**Rollback signal:** `plan_index` feed reports `ok=False`
continuously for 24 hours. Revert step 7 by re-enabling the
filesystem-read branch in the two skills. Step 8 is delayed until
the rollback condition clears.

## Testing strategy

### Unit tests (`tests/unit/plan_index/`)

| File | Coverage |
|---|---|
| `test_store.py` | `PlanIndexStore` against a mock Dhara — all CRUD ops, idempotency, secondary-index queries, explicit `entities_count` |
| `test_rebuild.py` | `PlanIndexRebuilder` as pure function — input list → expected `PlanRecord` list, no I/O |
| `test_render.py` | `PlanIndexRenderer` as pure function — input list → expected markdown, staleness-header present |
| `test_writer.py` | I/O write happy + failure path |
| `test_cron.py` | `PeriodicTaskRunner` lock acquisition, stale-PID takeover, DLQ |
| `test_health.py` | `PlanIndexFeedState` is_ok() / as_dict() — `ok=False` when stale |
| `test_errors.py` | Error hierarchy; subclass relations |
| `test_collision.py` | `plan_id` derivation stable across checkout roots, collision suffix behavior |
| `test_migration_preflight.py` | Valid + invalid frontmatter mixed |

### Property tests (`tests/property/plan_index/`)

| Property | Examples |
|---|---|
| `rebuild_idempotent` — same input list twice → same Dhara upserts | ≥ 100 |
| `rebuild_preserves_unrelated_records` | ≥ 50 |
| `renderer_idempotent` — same input list → same output bytes | ≥ 100 |
| `plan_id_stable_across_checkout_roots` — same path in different checkout roots produces same `plan_id` | ≥ 30 |
| `entities_count_matches_rebuilder_state` | ≥ 30 |

### Integration tests (`tests/integration/plan_index/`)

Per `mcp-backend-wiring-discipline.md` §2 (CI smoke) and §4 (per-tool
e2e), the following tests must exist and pass:

| Scenario | Coverage |
|---|---|
| `test_plan_list_e2e.py` | §4 gate — non-empty result within smoke window |
| `test_plan_show_e2e.py` | §4 gate |
| `test_plan_search_e2e.py` | §4 gate |
| `test_plan_vitals_e2e.py` | §4 gate |
| `test_plan_rebuild_status_e2e.py` | §4 gate |
| `test_plan_index_e2e_smoke.py` | §2 gate — subprocesses the MCP server, calls each tool, asserts non-empty |
| `test_rebuild_e2e.py` | Real git repo with 3 sample plans, real Dhara (mock or container), full pipeline → `PLAN_INDEX.md` rendered |
| `test_render_matches_old_scanner.py` | Snapshot test against golden file (NOT byte-equivalence) |
| `test_concurrent_rebuilds_serialize.py` | Two CLI invocations racing, second sees stale-lock |
| `test_partial_failure_continues.py` | Inject Dhara write failure for one record |
| `test_dhara_unreachable_degrades.py` | Patch store to raise; verify `PlanIndexUnavailableError` |
| `test_health_check_aggregates.py` | Wire feed-state provider, call `/health`, verify `plan_index.ok` computed correctly and 503 fires on stale |

### CI integration (REQ-PLAN-008)

CI gates this spec requires green before any merge:

```bash
# Frontmatter validation (the right tool)
crackerjack docs validate --strict

# REQ-ID traceability (separate concern)
python scripts/audit_requirements.py --plans docs/superpowers/specs/ --include-tests

# New: three-way consistency check
python scripts/audit_plan_index.py

# Wire-up-contract §3 gate: orphans check
python scripts/audit_orphans.py

# Makefile targets
make plan-index-validate    # dry-run diff against current PLAN_INDEX.md
make plan-index-rebuild     # full rebuild
```

The 5 MCP tools + the integration test files together close
`mcp-backend-wiring-discipline.md` §4.

## Observability (REQ-PLAN-005)

Three emission surfaces, per `bodai-observability-pattern.md`:

| Surface | Identifier | Destination |
|---|---|---|
| OTel span | `plan_index.rebuild` | OTel collector (per `mahavishnu/core/observability.py`) |
| Prometheus metric | `mahavishnu.plan_index.rebuild.duration` (histogram) | Prometheus (per `mahavishnu/core/routing_metrics.py` precedent) |
| EventBridge topic | `plan_index.rebuild.completed` | Oneiric EventBridge (per `bodai-observability-pattern.md`); consumers: bodai-radar skill, future Layer 4 scheduler |

OTel span attributes: `records_upserted`, `records_skipped`, `errors_total`,
`cycles_total`, `duration_ms`, `lock_held_by`, `migration_flag`.

## Decision Rule

This spec is "done enough" when **all** of the following are true:

1. **Migration steps 1–5 complete** — Dhara populated, golden render
   snapshot test passes.
2. **`/health` reports the `plan_index` feed** with the four mandatory
   signals plus the `ok` key, and `ok=False` correctly flips when
   `last_rebuild_ms` is older than 5× `cron_every_seconds`.
3. **The 5 per-tool e2e tests** + the §2 smoke test all pass in CI.
4. **The 5-edit registration dance** is applied and CI guard tests
   are green.
5. **`docs/feature-tracking/plan-index-dhara.md` exists** with
   `status: built`. Migration step 6 flips it to `wired`; step 7
   flips it to `adopted`.

MCP tools (step 6), skill cut-over (step 7), and decommission
(step 8) are **separately cuttable** if scope pressure forces a
cut. D6's trip-wire is recorded-only in v1 regardless of the ratio
value.

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Migration step 5 golden-render gate fails | Low | Golden file is co-developed; renderer fix in same commit |
| Concurrent rebuilds corrupt Dhara state | Low | Lock with stale-PID detection; second script aborts cleanly |
| Dhara unreachable breaks read paths | Medium | Degraded envelope on read; `PlanIndexUnavailableError` for callers that need to distinguish |
| `plan_id` collision (statistically impossible at 64-bit truncation) | Very low | Counter suffix; logged to errors |
| Trip-wire fires unexpectedly under v1 read inflation | Low (was high in v0) | v1 is recorded-only; new design uses recency-staleness, not ratio |
| 14-day decommission window too short | Low | Decommission is delayed if `/health` shows any 503 in prior 7 days; conditional on jot sub-plan 3 ship date |
| PeriodicTaskRunner adds operational surface | Medium | Mirrors `fitness_analyzer` patterns; bounded by one task at v1 |
| Wire-up audit (`audit_plan_index.py`) added CI dependency | Low | Step is one bash command; bounded by discovered store count |
| Cross-machine replication lag pre-jot-sub-plan-3 | Medium | `PLAN_INDEX.md` filesystem read remains canonical for STANDARD profile until D10 condition met |

## Out of scope (deferred)

- **Layer 4 (task queue + scheduler)** — substrate delivered; queue
  design is a follow-on spec. Layer 4 deferral is paired with a
  follow-up spec to unify with `scripts/feature_eligibility.py`'s
  substrate (math plan §6 Phase 9). In the interim,
  `feature_eligibility.py` continues to poll individual MCP endpoints
  and read `docs/followups/`. A future `2026-XX-XX-followup-orchestration.md`
  plan must decide whether Layer 4 absorbs the followups file format
  or sits beside it; v1 ships without resolving that.
- **Session-Buddy semantic search for plans** — deferred per D6
  trigger conditions.
- **Cross-team federation** — `repo` field preserved; future spec
  adds a `--repos` flag to the regenerator.
- **Worktree-aware reading** — operators testing a feature branch
  wanting to see what their branch's plans look like. Deferred.

## Open Questions

1. **Dhara upsert-by-ID vs append semantics** — Required by
   invariant 1 (idempotency). Empirical check during implementation.
   If append, invariant 1 fails and the migration must gate.
   (Inherited from jot spec OQ #2; not yet resolved at design time.)

## References

- `docs/superpowers/specs/2026-09-09-jot-inbox-design.md` — pattern
  template (read substrate topology, fail-open, trip-wire philosophy)
- `docs/superpowers/specs/2026-09-09-jot-read-design.md` — pure
  function split pattern; TypedDicts + error hierarchy discipline
- `docs/superpowers/specs/2026-09-09-jot-capture-design.md` —
  capture-path discipline
- `docs/plans/2026-09-10-bodai-math-initiatives-tier1.md` —
  `scripts/feature_eligibility.py` followup/feature-tracking half
  becomes a single Dhara query after this spec lands; math plan
  §7 cross-repo follow-on points at the same plumbing (now
  `mahavishnu/plan_index/cron.py`, not `fitness_analyzer.py:279`)
- `docs/plans/TEMPLATE.md` — Integration Contract format
- `docs/plans/PLAN_INDEX.md` — the artifact this spec transforms
  from "filesystem scanner output" to "Dhara-fed render"
- `.claude/decisions/wire-up-contract.md` — Integration Contract
  requirement for every feature; `audit_orphans.py` gate
- `.claude/decisions/mcp-backend-wiring-discipline.md` — feed-state
  requirement (4 signals + ok key for `bootstrap.py:289` reduction)
- `.claude/decisions/bodai-observability-pattern.md` — Oneiric
  EventBridge canonical event envelope; forbids second bus
- `.claude/decisions/dhara-key-prefixes-2026-07-15.md` — slash
  separator convention; producer appends subpath
- `.claude/decisions/dhara-key-prefixes-2026-07-15.md` (corrected path)
- `.claude/decisions/followups-lifecycle.md` — `docs/followups/`
  lifecycle (Layer 4 sketch uses this)
- `docs/schemas/document-frontmatter-v1.md` — frontmatter schema;
  Crackerjack surface
- `mahavishnu/mcp/signer_feed.py` — reference pattern for
  `PlanIndexFeedState`
- `mahavishnu/mcp/bootstrap.py:268–296` — `register_health_endpoint`
  + `health_check` + `all_ok` reduction
- `mahavishnu/pools/fitness_analyzer.py` — `task_classes` precedent
  (DO NOT reuse for cron; D9)
- `mahavishnu/jot/errors.py` — error hierarchy discipline
- `mahavishnu/jot/short_id.py` — short_id derivation precedent
- `scripts/audit_requirements.py` — REQ-ID traceability (NOT
  frontmatter validation; do not conflate)
- `scripts/regenerate_plan_index.py` — the script being rewritten
- `scripts/audit_orphans.py` — wire-up contract's orphan gate
