---
role: implementation
topic: dhara-substrate-extension
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
    title: "/health reports plan_index feed state via plan_index/meta keys with the four mandatory signals plus an ok key"
  - id: REQ-PLAN-006
    title: "Rebuild runs in a dedicated PeriodicTaskRunner, not fitness_analyzer task_classes"
  - id: REQ-PLAN-007
    title: "D10 decommission of filesystem read path requires conditional on jot sub-plan 3 ship"
  - id: REQ-PLAN-008
    title: "scripts/audit_plan_index.py is wired into CI alongside scripts/audit_orphans.py and crackerjack docs validate"
  - id: REQ-PLAN-009
    title: "docs/feature-tracking/plan-index-dhara.md exists and tracks built/wired/adopted"
  - id: REQ-PLAN-010
    title: "All five new plan_* MCP tools are gated with @require_mcp_auth when auth_enabled=True"
  - id: REQ-PLAN-011
    title: "PlanIndexRebuilder.normalize_repo_url() runs before plan_id derivation"
  - id: REQ-PLAN-012
    title: "errors.log never contains raw path or repo (only path_hash and normalized repo_url_hash)"
---

# Plan Index — Dhara-Canonical Metadata Layer

> **Design status:** draft, awaiting reviewer sign-off (2026-09-10).
> Built through the superpowers:brainstorming flow across three sections,
> revised after a 5-agent pentaverate review (round 1: architecture,
> Mahavishnu integration, Akosha, MCP, wire-up discipline) and a 4-agent
> rotated-angle review (round 2: test strategy, type design, migration /
> operator UX, security / privacy). Inline fixes per the BLOCKER +
> HIGH findings from both rounds are reflected in this version.

## Problem

`docs/plans/PLAN_INDEX.md` is the navigation map for Mahavishnu and the
broader Bodai ecosystem's plan/decisions/followups/feature-tracking/ADR
catalogue. Today it is generated mechanically by
`scripts/regenerate_plan_index.py`, which auto-discovers stores
(`MIN_STORE_DOCS = 2` plus a frontmatter walk), parses YAML frontmatter,
and renders a markdown table.

Three failure modes the current design cannot address:

1. **Serverless / container runtime** — the scanner needs the discovered
   stores on the local filesystem; a serverless bundle typically does
   not ship `.claude/decisions/` or `docs/adr/`, so the index cannot be
   regenerated at runtime.
2. **Cross-machine visibility** — every clone regenerates a different
   `PLAN_INDEX.md`. Same query, different views, no merge.
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
   must land before Layer 4 ships.
4. **Not** semantic search via Session-Buddy in v1 — lexical match
   on `title` + `topic` only. Trigger for adding Session-Buddy:
   (a) corpus exceeds ~500 entries, OR (b) lex noise on
   `title`+`topic` outweighs precision gains, OR (c) the Dhara
   change-feed primitive lands.
5. **Not** cross-team federation in v1 — the record carries
   `repo` (normalized, see Security §D11) so the future federation is
   a CLI flag, but v1 reads Mahavishnu only.

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

New CLI flag (round-2 fix): `--exclude <pattern>` and `--exclude-from
<file>` (gitignore-style) for sensitive workspace patterns. The
existing `SYSTEM_DIR_PARTS` is a system-only deny-list
(`scripts/regenerate_plan_index.py:88–110`); the operator-configurable
excludes are read from CLI args, env var
`PLAN_INDEX_EXCLUDE_FILE`, or a repo-local `.plan_indexignore`.

### D4 — `plan_id` derivation includes normalized `repo` (round-2 fix)
`plan_id = sha256(f"{normalized_repo}:{normalized_path}").hexdigest()[:32]`
where `normalized_repo` is the output of
`PlanIndexRebuilder.normalize_repo_url()` (see Security §D11) and
`normalized_path` is **repo-relative, POSIX-separated** (e.g.
`docs/plans/2026-09-15-foo.md`). Two URL forms of the same repo
(`git@github.com:foo/bar.git` vs `https://github.com/foo/bar.git`)
produce the same `plan_id`; two repos with the same path do not
collide. On the (statistically impossible) collision, the rebuilder
appends a counter suffix (`<base>-2`, `<base>-3`, …) and logs to
`errors.log`.

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

The TypedDict literal is **four distinct states**:

```python
tripwire: Literal[
    "ok",                          # healthy state
    "no_recent_edits",             # no edits in 30d but reads continue
    "no_recent_reads",             # edits continue but no reads (rare; means nobody cares)
    "review_cadence_lagging",      # combined condition (D6 above) fired
]
```

In v1 the trip-wire is recorded in `plan_vitals()` only — no action,
no push surface.

### D7 — Profile tier placement, auth gate, and skill migration (round-2 fix)
The five `mcp__mahavishnu__plan_*` tools ship in **FULL** only.
STANDARD tier (an opt-in override; `full` is the production default
per `CLAUDE.md`) reads `docs/plans/PLAN_INDEX.md` on disk indefinitely.
The 14-day decommission window in migration step 8 applies to the
two named skills (`bodai-status`, `mahavishnu-status`) switching from
filesystem read to MCP read; the disk file itself remains a supported
read artifact for humans, STANDARD profile, and MINIMAL profile
indefinitely.

**Auth gate (round-2 BLOCKER fix — REQ-PLAN-010)**: all five tools
require `@require_mcp_auth(required_permission=Permission.READ_PLAN_INDEX)`
when `MAHAVISHNU_AUTH_ENABLED=true`. The permission is added to
`mahavishnu/core/permissions.py:18–30`. When `auth_enabled=false`,
the tools are ungated (consistent with `capability_tools.py:5`'s
introspection posture). The decorator is added to all five tools in
the same PR as the 5-edit registration dance.

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
  `plan_index/meta/rebuild_lock/{hostname_hash}/{pid}` with TTL=60s)
  — note hostname_hash not raw hostname (D5 medium fix)
- per-task DLQ for Dhara write failures
- registered in `MahavishnuApp.__init__` next to where `fitness_analyzer`
  is wired

### D10 — Decommission window conditional on jot sub-plan 3
Migration step 8 (filesystem-read decommission in the two named
skills) fires at the later of (a) this spec's cut-over + 14 days, or
(b) jot sub-plan 3 ship date + 14 days. If jot sub-plan 3 has no
ship date at evaluation time (it's currently deferred per
`docs/superpowers/specs/2026-09-09-jot-read-design.md` line 5),
condition (b) is treated as unsatisfiable and step 8 reduces to
condition (a) + feature-tracking `adopted` status. **PLAN_INDEX.md
itself remains a supported read artifact indefinitely** (per D7).

### D11 — Security posture (round-2 fix)
The spec inherits the project's standard security posture and adds
three spec-specific concerns:

1. **`@require_mcp_auth` gate** (REQ-PLAN-010) — see D7.
2. **`PlanIndexRebuilder.normalize_repo_url()`** (REQ-PLAN-011):
   - Strip userinfo (`user:pass@` and `user@` segments).
   - Lowercase the host.
   - Replace the path with `sha256("/".join(path_segments)).hexdigest()[:12]`
     — preserve collision-resistance while obscuring repo names.
   - Reject URLs with control characters or that fail
     `^(git@|https?://|ssh://)[A-Za-z0-9._-]+(/|:).+$`. Logged at WARN
     with the path and a truncated hostname for operator triage.
   - The normalized form is what gets stored on `PlanRecord.repo` AND
     fed into the `plan_id` hash (D4).
3. **Errors-log redaction** (REQ-PLAN-012): `PlanRebuildErrorDict.ctx`
   uses a `TypedDict, total=False` schema with `path_hash: NotRequired[str]`
   (sha256(path)[:12]), `plan_id: NotRequired[str]`, `op: NotRequired[str]`.
   Raw `path` and `repo` are NEVER written to `errors.log`. The existing
   `~/.mahavishnu/jot/errors.log` (mode 0o600) is the precedent.

The spec also defers the following security concerns to follow-ons
(see Open Questions): `/health` cadence intel unauthenticated (k8s
liveness probe convention); GDPR / right-to-erasure / decommission
operator CLI.

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
│   │                       plan_index/blocked_by/{…}        │      │
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
│   │   (auto-discovered; honor --exclude and SYSTEM_DIR_PARTS)│      │
│   └──────────────────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────────────┘
```

### Read paths after the change

- **Humans**: read `docs/plans/PLAN_INDEX.md` (a *rendered artifact*
  whose header carries `<!-- Last regenerated: YYYY-MM-DD HH:MM:SS UTC
  · run mcp__mahavishnu__plan_rebuild_status for staleness check -->`).
  Indefinitely.
- **AI agents in-session (FULL profile, auth enabled)**:
  `mcp__mahavishnu__plan_list` / `plan_show` / `plan_search` /
  `plan_vitals` / `plan_rebuild_status`, all gated by
  `@require_mcp_auth(Permission.READ_PLAN_INDEX)`.
- **AI agents in-session (FULL profile, auth disabled)**: tools
  ungated (consistent with `capability_tools.py:5`'s introspection
  posture; documented in D7).
- **AI agents in-session (STANDARD / MINIMAL profile)**: read
  `docs/plans/PLAN_INDEX.md` indefinitely.
- **`bodai-status` / `mahavishnu-status` skills** (FULL profile, post
  step 7): read via MCP tools.

### Write paths after the change

- **Promoters**: edit `.md` files in git as today; no new write step.
- **Cross-machine readers**: Dhara's existing replication (jot
  sub-plan 3 will harden this).

## Components

| Component | Location | Purpose |
|---|---|---|
| `PlanId = NewType("PlanId", str)` | `mahavishnu/plan_index/__init__.py` | Typed ID (CLAUDE.md "no Any" applied to identifiers). |
| `PlanIndexStore` (new) | `mahavishnu/plan_index/store.py` | Dhara-backed metadata CRUD. The only file that imports Dhara. Maintains `plan_index/meta/entities_count` as an explicit counter. |
| `PlanIndexRebuilder` (new) | `mahavishnu/plan_index/rebuild.py` | Pure function over `(records, current_dhara_state) → upserts`. SHA from `git hash-object`. `normalize_repo_url()` is a module-level helper called once per record before any other field is computed. |
| `PlanIndexRenderer` (new) | `mahavishnu/plan_index/render.py` | Pure function: list of `PlanRecord` → `PLAN_INDEX.md` markdown string. Emits the staleness-header. No I/O. |
| `PlanIndexWriter` (new) | `mahavishnu/plan_index/writer.py` | Thin I/O wrapper: writes the rendered string to disk. |
| `PlanIndexErrors` (new) | `mahavishnu/plan_index/errors.py` | `PlanIndexError` base + `PlanNotFoundError`, `PlanIndexUnavailableError`, `PlanRebuildLockedError`. (Dropped: `PlanAmbiguousHandleError` — dead code in v1 since `plan_id` is hash-derived; no realistic ambiguity source pre-federation.) |
| `PlanIndexHealth` (new) | `mahavishnu/plan_index/health.py` | `PlanIndexFeedState` (frozen, slots). Mirrors `mahavishnu/mcp/signer_feed.py::SignerFeedState`. `as_dict()` returns exactly `{ok, entities_count, last_updated_timestamp, errors_total, cycles_total}` — the four mandatory signals plus `ok`. `successful_cycles_total` is tracked as a Dhara meta key but **NOT** in `as_dict()` (the wire-up discipline's 4-signal contract is strict; do not unilaterally extend). |
| `PeriodicTaskRunner` (new) | `mahavishnu/plan_index/cron.py` | Asyncio loop hosting the rebuild task. Per-task lock + DLQ. NOT in `fitness_analyzer`. Lock uses hostname_hash not raw hostname (D5 medium fix). |
| `RegeneratePlanIndexCLI` (rewritten) | `scripts/regenerate_plan_index.py` | Orchestrator. Six existing flags preserved + three new (`--check`, `--skip-render`, `--rebuild-from`) + `--exclude` / `--exclude-from` (D3). |
| `mcp__mahavishnu__plan_*` (new tool group) | `mahavishnu/mcp/tools/plan_tools.py` | 5 tools. Returns TypedDicts (no `Any`). Each tool decorated with `@require_mcp_auth(Permission.READ_PLAN_INDEX)` when auth is enabled. `plan_show` raises `PlanNotFoundError` (FastMCP-serialized) instead of returning `null`. `plan_rebuild_status` returns a structured envelope. |
| `mahavishnu plan …` CLI (new) | `mahavishnu/cli/plan_cli.py` | Mirrors MCP tools for shell use. |
| `mahavishnu plan purge --plan-id <id>` (new) | `mahavishnu/cli/plan_cli.py` | Operator CLI for explicit Dhara-record deletion (decommission procedure). |
| `docs/feature-tracking/plan-index-dhara.md` (new) | `docs/feature-tracking/` | Tracks `{built, wired, adopted}` lifecycle per `wire-up-contract.md` §4. |
| `scripts/audit_plan_index.py` (new) | `scripts/` | Three-way disk/index/Dhara consistency check. Wires into CI alongside `scripts/audit_orphans.py` and `crackerjack docs validate`. |

### Migration 5-edit dance (verbatim)

Per `mahavishnu/mcp/tools/profiles.py` precedent, the actual edits:

1. `mahavishnu/mcp/bootstrap.py` — add `def _register_plan_tools(server: FastMCPServer) -> None:` calling `plan_tools.register(server.server, ...)`.
2. `mahavishnu/mcp/tools/profiles.py` import block (lines 34–60) — add `from .bootstrap import _register_plan_tools`.
3. `mahavishnu/mcp/tools/profiles.py:93–102` `FULL_REGISTRATIONS` — add `"_register_plan_tools"` to the FULL-tier list.
4. `mahavishnu/mcp/tools/profiles.py:178–186` `REGISTRATION_MAP` (FULL section) — add `"_register_plan_tools": lambda s: _register_plan_tools(s._mhv_server)`.
5. CI guard test — assert that every `PROFILE_REGISTRATIONS` key has a matching `REGISTRATION_MAP` entry, and that `FULL_REGISTRATIONS ⊇ STANDARD_REGISTRATIONS`.

**Land all five in a single commit.** Intermediate CI runs between
edits 1–4 and edit 5 fail on missing-map-entry; ordering across
PRs introduces avoidable intermediate breakage.

### Permission registration

In `mahavishnu/core/permissions.py:18–30` add:

```python
READ_PLAN_INDEX = "READ_PLAN_INDEX"
```

The constant is referenced by the new tool group's auth decorator.

## Data Model

### Type aliases

```python
from typing import NewType

PlanId = NewType("PlanId", str)   # sha256(repo + path)[:32]
```

### `PlanRecord` dataclass

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanRecord:
    plan_id: PlanId                 # sha256(f"{normalized_repo}:{normalized_path}").hexdigest()[:32]
                                 # On collision: counter suffix (-2, -3, …).
    path: str                    # repo-relative, POSIX-separated
                                 # (e.g. "docs/plans/2026-09-15-foo.md").
                                 # Cross-platform contract: always forward-slash
                                 # regardless of host OS.
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
    blocks_on: list[PlanId]       # list of plan_ids this plan depends on
    sha: str                     # git blob SHA at rebuild time
    repo: str                    # NORMALIZED git remote URL (per D11)
    lifecycle_state: Literal[
        "built", "wired", "adopted"
    ] | None = None              # feature-tracking docs only
    updated_at_ms: int           # server-set timestamp; assumes NTP-synced
                                 # hosts within ≤1s for cross-machine ordering.
```

Note: an optional `id` field for cross-repo referencing was in v2;
removed in v3 because (a) no v1 caller exists, (b) federation is
non-goal #5, (c) it duplicates the canonical `plan_id` semantic.
Re-introduce only when concrete federation work lands.

### TypedDicts (CLAUDE.md "no Any" rule — REQ-PLAN-004)

```python
from typing import NotRequired, TypedDict


class PlanRecordDict(TypedDict):
    plan_id: str
    path: str
    title: str
    status: str
    role: str
    topic: str
    date: str
    last_reviewed: str
    superseded_by: NotRequired[str]      # omitted when absent, not null
    blocks_on: list[str]
    sha: str
    repo: str
    lifecycle_state: NotRequired[str]
    updated_at_ms: int


class RebuildErrorCtx(TypedDict, total=False):
    """Structured context for PlanRebuildErrorDict."""
    plan_id: NotRequired[str]
    path_hash: NotRequired[str]          # sha256(path).hexdigest()[:12]; never raw path
    op: NotRequired[str]                 # "scan" | "upsert" | "render" | "lock" | ...
    attempt: NotRequired[int]


class PlanVitalsDict(TypedDict):
    total: int                          # post-filter (matches the returned list)
    by_status: dict[str, int]
    by_role: dict[str, int]
    by_topic_top10: list[tuple[str, int]]
    last_rebuild_ms: NotRequired[int]
    last_success_ms: NotRequired[int]
    oldest_active_ms: NotRequired[int]
    cycles_total: int
    successful_cycles_total: int       # kept here for vitals; NOT in FeedState
    errors_total: int
    recent_errors: list[PlanRebuildErrorDict]
    tripwire: Literal[
        "ok", "no_recent_edits", "no_recent_reads", "review_cadence_lagging"
    ]


class PlanRebuildStatusDict(TypedDict):
    last_rebuild_ms: NotRequired[int]
    last_success_ms: NotRequired[int]
    cycles_total: int
    successful_cycles_total: int       # kept here; NOT in FeedState
    errors_total: int
    recent_errors: list[PlanRebuildErrorDict]
    lock_held_by: NotRequired[str]       # "{hostname_hash[:8]}/{pid}" — redacted
    lock_age_ms: NotRequired[int]
    stale: bool


class PlanRebuildErrorDict(TypedDict):
    ts_ms: int
    op: str
    err: str
    ctx: RebuildErrorCtx                # TypedDict; never dict[str, Any]


class PlanListResultDict(TypedDict):
    plans: list[PlanRecordDict]
    total: int                          # post-filter count (= len(plans) unless paged)
    cached_at_ms: NotRequired[int]      # set when degraded
    status: Literal["ok", "degraded"]


class PlanDegradedDict(TypedDict):
    """Discriminated by absence of the 'plans' field. No 'status' literal
    (single-value Literal is a code smell — the type IS the discriminator)."""
    reason: str
    cached_at_ms: int | None
```

### Dhara key conventions (REQ-PLAN-001)

Mirror `.claude/decisions/dhara-key-prefixes-2026-07-15.md` (slash
separator; producer appends subpath):

| Prefix | TTL | Notes |
|---|---|---|
| `plan_index/{plan_id}` | 24 h | Primary record; regenerable from git |
| `plan_index/status/{status}/{date}/{plan_id}` | inherits primary | Secondary index, lex order = chronological within status |
| `plan_index/topic/{topic}/{date}/{plan_id}` | inherits primary | Secondary index, lex order = chronological within topic |
| `plan_index/blocked_by/{plan_id}/{dependent_plan_id}` | inherits primary | Reverse index for `blocks_on` (round-2 MEDIUM fix M4) |
| `plan_index/meta/last_rebuild_ms` | none | Timestamp; feeds the `/health` staleness alerts |
| `plan_index/meta/last_success_ms` | none | Timestamp of most recent successful cycle |
| `plan_index/meta/entities_count` | none | Explicit counter written by rebuilder; not derived from `len(keys(...))` |
| `plan_index/meta/errors_total` | none | Cumulative counter |
| `plan_index/meta/cycles_total` | none | Increments on every rebuild ATTEMPT (per wiring-discipline §3) |
| `plan_index/meta/successful_cycles_total` | none | Counter of cycles where all writes succeeded. **Tracked as Dhara meta only — NOT in `PlanIndexFeedState.as_dict()`** (4-signal contract) |
| `plan_index/meta/migration_pre_flight_errors` | 7 d | Transient diagnostic |
| `plan_index/meta/rebuild_lock/{hostname_hash[:8]}/{pid}` | 60 s | Stale-PID takeover eligible; hostname redacted (D5 medium fix) |
| `plan_index/meta/recent_errors` | 30 d | Bounded JSON list (last 20 errors) |
| `plan_index/sensitive/normalized_repo_url/{plan_id}` | none | Stored for operator triage; not in any MCP read path |

### Wire-up discipline feed-state contract (REQ-PLAN-005, round-2 fix)

`PlanIndexFeedState.as_dict()` returns exactly the four mandatory
signals plus the `ok` key:

```python
{
    "ok": <bool>,                       # REQUIRED by bootstrap.py:289 all_ok
    "entities_count": <int>,
    "last_updated_timestamp": <int>,     # epoch ms of last_rebuild_ms
    "errors_total": <int>,
    "cycles_total": <int>,
}
```

`successful_cycles_total` is **NOT** in `as_dict()` — it is tracked
separately as a Dhara meta key for vitals, but the discipline doc's
4-signal contract is strict and we do not unilaterally extend it.
Dashboards compute success ratio from `1 - errors_total / cycles_total`.

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
              (auto-discovers stores; honors --exclude and SYSTEM_DIR_PARTS)
   ↓ Phase B: PlanIndexRebuilder.normalize_repo_url() on each record
              PlanIndexRebuilder.upsert_all(records) writes to Dhara
              (one transaction per record; failed records logged)
              Updates plan_index/meta/entities_count
              Increments plan_index/meta/cycles_total
              Increments plan_index/meta/successful_cycles_total on full success
              Updates plan_index/meta/last_rebuild_ms and last_success_ms
   ↓ Phase C: PlanIndexRenderer.render(records) → markdown string
              PlanIndexWriter.write(md, PLAN_INDEX.md)
   ↓
4. OTel span `plan_index.rebuild` emitted with attributes:
     records_upserted, records_skipped, errors_total, cycles_total,
     duration_ms, lock_held_by, migration_flag (true only on cycle 1)
5. EventBridge topic `plan_index.rebuild.completed` published via
   Oneiric EventBridge (`bodai-observability-pattern.md`)
6. Prometheus histogram `mahavishnu.plan_index.rebuild.duration`
   with labels `{status, op}` (added to _ALLOWED_LABEL_KEYS at
   mahavishnu/observability/metrics.py:74 in the same PR)
7. /health aggregates: plan_index.ok computed; checks["plan_index"] updated
8. Read paths see the new state
```

### Cross-machine read path

Same as v2 — Dhara replication handles cross-machine visibility once
jot sub-plan 3 hardens it. Cross-machine `updated_at_ms` assumes
NTP-synced hosts within ≤1s; larger skew will surface as
secondary-index ordering anomalies on read (round-2 LOW fix L1).

### Lock acquisition (concurrent rebuilds)

Rebuilder starts → set `plan_index/meta/rebuild_lock/{hostname_hash[:8]}/{pid}`
with TTL = 60s. Stale-PID detection compares `lock_acquired_at_ms`
against `plan_index/meta/last_rebuild_ms` — if the latter is older
than 2× the lock TTL, the lock is orphan.

`hostname_hash = sha256(socket.gethostname()).hexdigest()[:8]` —
hostname is hashed to keep FQDNs (`node.dc1.example.com`) from
breaking Dhara key prefix parsing (round-2 MEDIUM fix M11).

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
   uses `crackerjack docs validate`. **The migration pre-flight
   (step 1) matches runtime behavior**: skip-and-count, write
   `migration_pre_flight_errors` but do NOT abort unless
   `--preflight-mode=strict` is set (default is `lenient`).
4. **Git as source of truth** — the rebuilder reads from the
   **filesystem view of main**, never from a worktree, never from a
   feature branch's checkout. Worktrees are excluded by path
   (existing scanner already excludes `.claude/worktrees/`).
5. **`repo` resolution and normalization** — the rebuilder reads
   `.git/config` directly (no subprocess) and parses
   `[remote "origin"] url`. The raw URL is passed through
   `normalize_repo_url()` (D11, REQ-PLAN-011): strip userinfo,
   lowercase host, hash path segments, reject control characters.
   Rejected URLs are logged at WARN with truncated hostname. The
   normalized form is what gets stored on `PlanRecord.repo` and
   fed into the `plan_id` hash (D4).
6. **`sha` field** — set to the git blob SHA of the `.md` file at
   rebuild time (via `git hash-object`). Read paths may return
   stale metadata if the rebuild hasn't re-run since the file
   changed; acceptable for day-scale lifecycle.
7. **`entities_count` is explicit** — written by the rebuilder as
   `plan_index/meta/entities_count` at end-of-cycle. Not derived
   from `len(keys("plan_index:*"))` (that would over-count secondary
   indexes and lock keys by 3×).
8. **Operator exclude patterns** — `--exclude` and `--exclude-from`
   flags plus `PLAN_INDEX_EXCLUDE_FILE` env var plus repo-local
   `.plan_indexignore` are read in addition to the system
   `SYSTEM_DIR_PARTS`. Excluded paths are NOT read, NOT persisted,
   NOT logged with raw path (only `path_hash`).
9. **Errors-log redaction** (REQ-PLAN-012) — `PlanRebuildErrorDict.ctx`
   is a `TypedDict` with `path_hash` (sha256[:12]) and `plan_id`,
   never raw `path` or `repo`. The `~/.mahavishnu/plan_index/errors.log`
   file has mode 0o600 (per jot precedent at `mahavishnu/jot/paths.py`).

## Read-path invariants

1. **`mcp__mahavishnu__plan_show(plan_id)`** returns the
   `PlanRecordDict`. If the record is missing, raises
   `PlanNotFoundError` (FastMCP-serialized). If Dhara is
   unreachable, raises `PlanIndexUnavailableError`. Both subclasses
   must round-trip through FastMCP without losing their discriminator
   (verified by `test_fastmcp_error_serialization.py`).
2. **`mcp__mahavishnu__plan_list({status, topic, date_from, date_to})`**
   uses the secondary indexes. Returns `PlanListResultDict`.
3. **`mcp__mahavishnu__plan_search(query)`** returns lexical matches
   on `title` + `topic` from Dhara's primary key prefix scan
   (full-table scan; O(N) acceptable at ~500 records). Empty query
   returns empty list; regex special characters treated literally.
4. **`mcp__mahavishnu__plan_vitals()`** returns `PlanVitalsDict`
   with `tripwire` field carrying the 4 distinct states from D6.
5. **`mcp__mahavishnu__plan_rebuild_status()`** returns
   `PlanRebuildStatusDict` with `lock_held_by` redacted
   (`{hostname_hash[:8]}/{pid}`).
6. **Auth gate** (REQ-PLAN-010) — all five tools are gated by
   `@require_mcp_auth(required_permission=Permission.READ_PLAN_INDEX)`
   when `MAHAVISHNU_AUTH_ENABLED=true`. The decorator is applied in
   migration step 6.

## Error handling

### The cardinal rule

**The rebuilder never destroys Dhara state on partial failure.**
Mirrors the jot spec's "never erase text you failed to store."

| Failure | Behavior | Recovery |
|---|---|---|
| Git working tree has uncommitted changes | Rebuild aborts; Dhara unchanged | Commit, re-run |
| Unparseable `.md` (bad YAML, missing field) | Logged to errors; rebuild continues | Fix frontmatter, re-run |
| Dhara write fails for one record | Logged to errors (`path_hash`, no raw path); `errors_total` incremented | `mcp__mahavishnu__plan_rebuild_status` exposes last errors; re-run |
| Dhara write fails for **all** records | Rebuild aborts; `cycles_total` incremented; `successful_cycles_total` NOT incremented; partial Dhara state preserved | `/health` 503 within 5h (poll_silent); investigate; re-run |
| Dhara unreachable on read | Tool raises `PlanIndexUnavailableError`; caller may fall back to `plan_show_safe` which returns `PlanDegradedDict` | Operator checks `/health` |
| Renderer markdown write fails (disk full) | Rebuild succeeds in Dhara; PLAN_INDEX.md shows previous render; warning logged | Manual re-render once disk freed |
| Concurrent rebuilds | Second script sees stale-lock, aborts | First wins; second evaluates after first completes |
| Rebuilder `--exclude` matches a path | Path is skipped entirely; no Dhara write attempted; no entry in `recent_errors` | Operator verifies `.plan_indexignore` |
| `normalize_repo_url()` rejects a URL | WARN log with truncated hostname; record skipped | Operator triages the rejection; manual `.git/config` fix |

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
```

Subclasses carry structured context. FastMCP serialization is
verified by `test_fastmcp_error_serialization.py` — the wire format
must preserve the subclass discriminator (the test asserts each
subclass round-trips with `code` field, not just the stringified
exception).

## Migration plan

The existing ~150+ markdown files across the discovered stores
provide valid frontmatter. The first run of the new rebuilder is a
**migration**, not a feature:

### Step 1 — Pre-flight check (lenient by default)
Script reads every `.md`, asserts all required fields present (per
`document-frontmatter-v1.md`). Files with missing fields are listed
in `plan_index/meta/migration_pre_flight_errors`; migration
**continues** with the valid records and reports the count. Validate
via `crackerjack docs validate --allow-nonstandard`. Use
`--preflight-mode=strict` to abort on any pre-flight error (matches
v0 behavior; kept as opt-in for environments that prefer fail-fast).

**Per-step rollback matrix:**

| Step | Success signal | Failure signal | Recovery action |
|---|---|---|---|
| 1 — pre-flight | `migration_pre_flight_errors` empty (lenient) or abort with full list (strict) | Non-conforming files counted | Fix files OR re-run with `--preflight-mode=strict` removed |
| 2 — investigate | All files fixed | Time-out | Continue with valid subset |
| 3 — migration run | Dhara populated; `cycles_total=1`, `successful_cycles_total=1`, `errors_total=0` | Dhara write fails; partial state | Re-run with idempotency; records overwritten by upsert |
| 4 — render+commit | `PLAN_INDEX.md` written; commit created | Renderer fails; previous `PLAN_INDEX.md` retained | Fix renderer; re-run step 4 |
| 5 — snapshot test | Golden test passes (first run: golden created; subsequent: diff clean) | Golden mismatch | Operator reviews diff; intentional updates commit golden in same change |
| 6 — 5-edit dance | All five edits in single commit; CI guard tests pass | CI guard fails | Amend the single commit; do not split |
| 7 — skill cut-over | `bodai-status` / `mahavishnu-status` skills read MCP | Skill regressions | Revert skill body; filesystem fallback continues |
| 8 — decommission | Skill bodies use MCP only | User reports regression | Re-enable filesystem-read branch in the two skills; see D10 conditional |

### Step 2 — Investigate and fix
Operator runs `crackerjack docs validate --allow-nonstandard` to
surface non-conforming files; fix frontmatter.

### Step 3 — Migration run (round-2 timing fix)
Script reads every `.md`, upserts to Dhara with `migration: true`
flag. Cycles_total=1, successful_cycles_total=1, errors_total=0.

**Timing semantics** (round-2 fix — was missing in v0):
- Per-record timeout default: 30 s
- Global timeout default: 5 min
- `--verbose` flag emits per-record progress to stderr
- Step 3 is **fail-fast on global timeout** (current behavior);
  per-record failures are recorded but don't abort (per invariant 3)
- **Elapsed budget**: ≤2 min on local Dhara, ≤10 min on remote
- `successful_cycles_total` only increments if all writes succeed

### Step 4 — Render and commit
Step 4a: script renders and writes `PLAN_INDEX.md` (no commit).
Step 4b: operator commits the file with message
`chore(plan_index): first Dhara-fed rebuild`. The script can suggest
the commit message via `--commit-msg-file` if desired.

### Step 5 — Verify (snapshot test, NOT byte diff)
Run `tests/integration/plan_index/test_render_matches_old_scanner.py`
which compares the new render to a golden file at
`tests/integration/plan_index/fixtures/PLAN_INDEX.golden.md`. The
first run **creates** the golden (operator review + commit);
subsequent runs diff against it.

**Golden review checklist** (operator signs off on each):
1. Section count matches
2. Status legend present
3. Authority matrix table present
4. Per-store registry row count matches `entities_count`
5. No broken relative links
6. Staleness-header present

Golden updates require a second implementer review, recorded in
the commit message trailer (`Co-authored-by:`).

### Step 6 — Wire MCP tools (single commit)
Apply the 5-edit dance (enumerated above) AND the `@require_mcp_auth`
decorator AND the new `Permission.READ_PLAN_INDEX` constant AND the
`_ALLOWED_LABEL_KEYS` allowlist extension for the Prometheus
histogram labels. **All FIVE edits in a single commit.** Make CI
guards green before merge.

### Step 7 — Cut over `bodai-status` / `mahavishnu-status` skills (FULL profile)
Change skill bodies to call MCP tools in parallel with reading
`PLAN_INDEX.md`. STANDARD-profile installs continue reading
`PLAN_INDEX.md` indefinitely.

### Step 8 — Decommission
At the **later of** (a) this spec's cut-over + 14 days, or (b) jot
sub-plan 3 ship date + 14 days. If jot sub-plan 3 has no ship date,
condition (b) is unsatisfiable → step 8 reduces to (a) +
`docs/feature-tracking/plan-index-dhara.md` `adopted` status. The
filesystem-read branch is removed from the two named skills.
`PLAN_INDEX.md` itself remains a supported read artifact for
humans, STANDARD profile, and MINIMAL profile indefinitely (per D7).

**Step 8 readiness check** is `scripts/check_step8_ready.py`
which prints "yes/no" based on (a) feature-tracking `adopted`,
(b) date arithmetic, (c) jot sub-plan 3 ship date (queried from a
registry or env var). Operator runs it before pulling the trigger.

### Notification surface (round-2 fix)
On `plan_index.ok` transitions (False or True), publish to EventBridge
topic `plan_index.health_changed`. Prometheus alert rule
`plan_index_ok_false_for_24h` is configured in
`settings/mahavishnu.yaml` alerts section. Operators are notified
within minutes, not via 24h `/health` polling.

### Global rollback signal
`plan_index` feed reports `ok=False` continuously for 24 hours.
Revert step 7 by re-enabling the filesystem-read branch in the two
skills. Step 8 is delayed until the rollback condition clears.

## Testing strategy

### Unit tests (`tests/unit/plan_index/`)

| File | Coverage |
|---|---|
| `test_store.py` | `PlanIndexStore` against a mock Dhara — CRUD, idempotency, secondary indexes, explicit `entities_count` |
| `test_rebuild.py` | `PlanIndexRebuilder` as pure function — input list → expected `PlanRecord` list. `sha` field uses a parameterized `sha_provider: Callable[[Path], str]` so the test injects a fake (round-2 fix — rebuilder is "almost-pure" with one I/O boundary) |
| `test_render.py` | `PlanIndexRenderer` — input list → expected markdown, staleness-header present |
| `test_writer.py` | I/O write happy + failure |
| `test_cron.py` | `PeriodicTaskRunner` lock acquisition, stale-PID takeover, DLQ |
| `test_health.py` | `PlanIndexFeedState` is_ok() / as_dict() — strict 4-signal contract; `ok=False` when stale; boundary cases (4×, 6× cron interval; never-rebuilt) |
| `test_errors.py` | Error hierarchy; FastMCP subclass serialization (round-2 H3) |
| `test_collision.py` | `plan_id` derivation stability across checkout roots; collision suffix |
| `test_migration_preflight.py` | Valid + invalid frontmatter mixed → skip-and-count; no Dhara writes on invalid records |
| `test_plan_id_normalize_repo_url.py` | (round-2) — three URL forms → same `plan_id`; userinfo stripped; control chars rejected; failed normalize logs WARN |
| `test_security_exclude_patterns.py` | (round-2) — `--exclude` and `.plan_indexignore` honored; excluded path NOT in Dhara; excluded path NOT in `errors.log` |
| `test_errors_log_redaction.py` | (round-2) — property test: `errors.log` line never matches raw `path` or `repo` patterns; only `path_hash` present |
| `test_canonicalization.py` | (round-2) — `PlanListResultDict.total` is post-filter; `cached_at_ms` only when degraded; `lock_held_by` format string regex |

### Property tests (`tests/property/plan_index/`)

| Property | Examples |
|---|---|
| `rebuild_idempotent` — same input list twice → same Dhara upserts | ≥ 100 |
| `rebuild_preserves_unrelated_records_with_no_disk_change` (round-2 fix — explicit invariant name) | ≥ 50 |
| `renderer_idempotent` — replaced with `renderer_semantically_idempotent` (round-2 fix): parse output back to canonical form, assert equality | ≥ 100 |
| `plan_id_stable_across_checkout_roots` | ≥ 30 |
| `plan_id_stable_across_url_normalizations` (round-2) — same repo in three URL forms produces same plan_id | ≥ 30 |
| `entities_count_matches_rebuilder_state` — AND `test_entities_count_read_path_uses_explicit_counter` (unit): patches `keys()` to over-count, asserts read path returns rebuilder's counter | ≥ 30 |

### Integration tests (`tests/integration/plan_index/`)

Per `mcp-backend-wiring-discipline.md` §2 (CI smoke) and §4
(per-tool e2e), the following tests must exist and pass:

| Scenario | Coverage |
|---|---|
| `test_plan_list_e2e.py` | §4 gate — non-empty result within smoke window; auth gate enforced |
| `test_plan_show_e2e.py` | §4 gate |
| `test_plan_search_e2e.py` | §4 gate; empty query returns empty list; regex chars literal |
| `test_plan_vitals_e2e.py` | §4 gate |
| `test_plan_rebuild_status_e2e.py` | §4 gate; `lock_held_by` is redacted |
| `test_plan_index_e2e_smoke.py` | §2 gate — subprocesses the MCP server, calls each tool, asserts non-empty + auth-gated |
| `test_plan_show_missing_record.py` | (round-2) — `PlanNotFoundError` raised; FastMCP discriminator preserved |
| `test_plan_rebuild_status_never_ran.py` | (round-2) — fresh Dhara, no rebuilder fired; `last_rebuild_ms is None`, `cycles_total == 0`, `stale == True` |
| `test_rebuild_e2e.py` | Real git repo with 3 sample plans, real Dhara, full pipeline → `PLAN_INDEX.md` rendered |
| `test_render_matches_old_scanner.py` | Snapshot test against golden file (NOT byte-equivalence); round-2 golden workflow |
| `test_golden_first_run.py` | (round-2) — first run creates golden; subsequent runs diff; CI guard asserts golden committed |
| `test_concurrent_rebuilds_serialize.py` | Two CLI invocations racing, second sees stale-lock |
| `test_stale_pid_takeover.py` | (round-2) — lock written 5 minutes old, second process takes over via stale-PID detection |
| `test_periodic_runner_dlq.py` | (round-2) — 3 transient Dhara write failures; rebuilder continues; `plan_index/meta/recent_errors` has 3 entries |
| `test_partial_failure_continues.py` | Inject Dhara write failure for one record |
| `test_dhara_unreachable_degrades.py` | Patch store to raise; verify `PlanIndexUnavailableError` |
| `test_fastmcp_error_serialization.py` | (round-2) — raise each subclass via MCP, assert wire format preserves discriminator |
| `test_health_check_aggregates.py` | Wire feed-state provider, call `/health`, verify `plan_index.ok` computed correctly and 503 fires on stale |
| `test_plan_record_dict_14_field_roundtrip.py` | (round-2) — construct with all 14 fields including None-valued; serialize through Dhara; assert equality |
| `test_migration_flag_otel.py` | (round-2) — span on cycle 1 has `migration_flag=true`; span on cycle 2 has attribute absent or `false` |
| `test_auth_gate_e2e.py` | (round-2) — request with no `user_id` rejected when `auth_enabled=true` |
| `test_lock_held_by_format.py` | (round-2) — `assert re.match(r"^[a-f0-9]{8}/\d+$", lock_held_by)` |
| `test_feature_tracking_lifecycle.py` | (round-2) — `docs/feature-tracking/plan-index-dhara.md` exists with required fields; status flips correctly |

### CLI integration tests (`tests/integration/regenerate_plan_index/`)

`--check` semantics (round-2 fix): "fail if rendered output differs from
current `PLAN_INDEX.md` on disk." `--check` is NOT equivalent to
`--dry-run` (which prints to stdout). The `--rebuild-from <arg>` arg
is a git revision range (`HEAD~5..HEAD`); single SHA also accepted.

### CI integration (REQ-PLAN-008)

CI gates this spec requires green before any merge:

```bash
# Frontmatter validation (the right tool)
crackerjack docs validate --strict

# REQ-ID traceability (separate concern)
python scripts/audit_requirements.py --plans docs/superpowers/specs/ --include-tests

# Three-way consistency check (NEW)
python scripts/audit_plan_index.py

# Wire-up-contract §3 gate
python scripts/audit_orphans.py

# Step 8 readiness check (NEW, run before decommission)
python scripts/check_step8_ready.py

# Makefile targets
make plan-index-validate    # runs --check (exit-code gate, not stdout diff)
make plan-index-rebuild     # full rebuild
```

The 5 MCP tools + the integration test files together close
`mcp-backend-wiring-discipline.md` §4.

## Observability (REQ-PLAN-005)

Three emission surfaces, per `bodai-observability-pattern.md`:

| Surface | Identifier | Destination |
|---|---|---|
| OTel span | `plan_index.rebuild` | OTel collector (per `mahavishnu/core/observability.py`) |
| Prometheus metric | `mahavishnu.plan_index.rebuild.duration` (histogram) | Prometheus; labels `{status, op}` |
| EventBridge topic | `plan_index.rebuild.completed` | Oneiric EventBridge (per `bodai-observability-pattern.md`) |
| EventBridge topic | `plan_index.health_changed` | (round-2) — published on `plan_index.ok` transitions |

OTel span attributes: `records_upserted`, `records_skipped`, `errors_total`,
`cycles_total`, `duration_ms`, `lock_held_by`, `migration_flag`
(true only on cycle 1; absent or false on subsequent cycles).

Prometheus labels (`{status, op}`) require extending the
`_ALLOWED_LABEL_KEYS` frozenset at `mahavishnu/observability/metrics.py:74`
in the same PR — the math-plan precedent at lines 91–100 documents
the batch pattern. Emission with an unlisted label raises
`ValueError` and silently drops the metric.

## Decision Rule

This spec is "done enough" when **all** of the following are true:

1. **Migration steps 1–5 complete** — Dhara populated, golden render
   snapshot test passes, secrets are not in `errors.log`, exclude
   patterns are honored.
2. **`/health` reports the `plan_index` feed** with the four mandatory
   signals plus the `ok` key, and `ok=False` correctly flips when
   `last_updated_timestamp` is older than 5× `cron_every_seconds`.
3. **The 5 per-tool e2e tests** + the §2 smoke test all pass in CI;
   each tool is auth-gated (REQ-PLAN-010).
4. **The 5-edit registration dance** is applied in a single commit and
   CI guard tests are green.
5. **Round-2 security fixes applied**: `normalize_repo_url()` runs
   before `plan_id` derivation (REQ-PLAN-011); `errors.log` contains
   only `path_hash`, never raw `path` or `repo` (REQ-PLAN-012); the
   `@require_mcp_auth` decorator is on all five tools.
6. **`docs/feature-tracking/plan-index-dhara.md` exists** with
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
| 14-day decommission window too short | Low | Decommission is delayed if `/health` shows any 503 in prior 7 days; conditional on jot sub-plan 3 ship |
| PeriodicTaskRunner adds operational surface | Medium | Mirrors `fitness_analyzer` patterns; bounded by one task at v1 |
| Raw `repo` URL leaks internal hostname before normalization (round-2 risk) | High if spec ships without D11 | `normalize_repo_url()` BEFORE persistence; verified by `test_plan_id_normalize_repo_url.py` |
| `errors.log` leaks `path` or `repo` (round-2 risk) | High if spec ships without ctx TypedDict | `RebuildErrorCtx` TypedDict with `path_hash` only; verified by `test_errors_log_redaction.py` |
| Ungated MCP tool returns `repo` URL to any caller (round-2 BLOCKER) | Certain if decorator missing | `@require_mcp_auth(Permission.READ_PLAN_INDEX)` on all five tools; verified by `test_auth_gate_e2e.py` |
| Cross-machine replication lag pre-jot-sub-plan-3 | Medium | `PLAN_INDEX.md` filesystem read remains canonical for STANDARD profile until D10 condition met |
| Sensitive workspace subtree gets persisted (round-2 risk) | Medium | `--exclude` / `--exclude-from` + `.plan_indexignore`; verified by `test_security_exclude_patterns.py` |

## Out of scope (deferred)

- **Layer 4 (task queue + scheduler)** — substrate delivered; queue
  design is a follow-on spec. Layer 4 deferral is paired with a
  follow-up spec to unify with `scripts/feature_eligibility.py`'s
  substrate.
- **Session-Buddy semantic search for plans** — deferred per D6
  trigger conditions.
- **Cross-team federation** — `repo` field preserved (normalized);
  future spec adds a `--repos` flag to the regenerator.
- **Worktree-aware reading** — operators testing a feature branch
  wanting to see what their branch's plans look like.
- **`/health` cadence intel unauthenticated** — round-2 MEDIUM
  finding. Splitting `/health` into `/health/live` (process-up,
  ungated, k8s liveness) and `/health/ready` (auth-gated, operator
  intel) is a follow-on. Plan INDEX `ok` field is intentionally
  detailed for now.
- **GDPR / right-to-erasure / decommission operator CLI** — round-2
  MEDIUM finding. `mahavishnu plan purge --plan-id <id>` ships as a
  first-class CLI in v1 per the Components table, but the broader
  decommission story (machine-level Dhara wipe, audit-log retention)
  is follow-on.

## Open Questions

1. **Dhara upsert-by-ID vs append semantics** — Required by
   invariant 1 (idempotency). Empirical check during implementation.
   If append, invariant 1 fails and the migration must gate.
   (Inherited from jot spec OQ #2; not yet resolved at design time.)
2. **Auth-default posture when `auth_enabled=false`** — the spec
   currently says tools are ungated in that case (mirroring
   `capability_tools.py:5`). If a deployment runs with auth disabled
   AND a public-internet MCP endpoint, the raw `repo` URL is exposed.
   Trade-off: enable auth by default (one-time operational cost)
   vs. accept the leak surface. Recommend a one-line check in the
   security checklist at install time.
3. **GDPR / data retention policy** — formal policy on what happens
   to plan metadata when a machine is decommissioned, or when a
   repo is deleted. Out-of-scope for this spec; tracked under
   "Out of scope (deferred)" but flagged here so the issue is
   captured.

## References

- `docs/superpowers/specs/2026-09-09-jot-inbox-design.md` — pattern
  template (read substrate topology, fail-open, trip-wire philosophy)
- `docs/superpowers/specs/2026-09-09-jot-read-design.md` — pure
  function split pattern; TypedDicts + error hierarchy discipline
- `docs/superpowers/specs/2026-09-09-jot-capture-design.md` —
  capture-path discipline; redaction patterns
- `docs/plans/2026-09-10-bodai-math-initiatives-tier1.md` —
  `scripts/feature_eligibility.py` followup/feature-tracking half
  becomes a single Dhara query after this spec lands
- `docs/plans/TEMPLATE.md` — Integration Contract format
- `docs/plans/PLAN_INDEX.md` — the artifact this spec transforms
- `docs/schemas/document-frontmatter-v1.md` — frontmatter schema;
  Crackerjack surface
- `docs/security/SECURITY_CHECKLIST.md` — sensitive information is
  not logged in plaintext
- `.claude/decisions/wire-up-contract.md` — Integration Contract
  requirement for every feature; `audit_orphans.py` gate
- `.claude/decisions/mcp-backend-wiring-discipline.md` — 4-signal
  feed-state contract (strict; do not unilaterally extend)
- `.claude/decisions/bodai-observability-pattern.md` — Oneiric
  EventBridge canonical event envelope; forbids second bus
- `.claude/decisions/dhara-key-prefixes-2026-07-15.md` — slash
  separator convention
- `.claude/decisions/followups-lifecycle.md` — `docs/followups/`
  lifecycle (Layer 4 sketch uses this)
- `mahavishnu/mcp/auth.py` — `@require_mcp_auth` decorator +
  `AuthAuditEvent` (round-2 reference)
- `mahavishnu/core/permissions.py` — `Permission` registry; add
  `READ_PLAN_INDEX` (round-2)
- `mahavishnu/observability/metrics.py:74` — `_ALLOWED_LABEL_KEYS`
  frozenset (extend for new Prometheus labels)
- `mahavishnu/mcp/signer_feed.py` — reference pattern for
  `PlanIndexFeedState`
- `mahavishnu/mcp/bootstrap.py:268–296` — `register_health_endpoint`
  + `health_check` + `all_ok` reduction
- `mahavishnu/pools/fitness_analyzer.py` — counter / TTL patterns;
  do NOT reuse for cron (D9)
- `mahavishnu/jot/errors.py` — error hierarchy discipline
- `mahavishnu/jot/short_id.py` — short_id derivation precedent
- `scripts/regenerate_plan_index.py:84–135` — `SYSTEM_DIR_PARTS`,
  `SELF_SKIP_REL` (existing scanner's deny-list baseline)
- `scripts/audit_requirements.py` — REQ-ID traceability (NOT
  frontmatter validation; do not conflate)
- `scripts/audit_orphans.py` — wire-up contract's orphan gate
