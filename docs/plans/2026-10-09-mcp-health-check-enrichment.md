---
status: draft
role: implementation
kind: plan
date: 2026-10-09
last_reviewed: 2026-10-09
superseded_by: null
blocks_on:
  - docs/plans/2026-10-09-bodai-search-infrastructure-fix.md
topic: mcp-design
---

# Bodai MCP `/health` Enrichment — Fleet-Wide Feed Aggregation + 503 on Degraded

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` for the per-repo worktrees. Each repo runs in its own worktree at `~/.local/state/mahavishnu/worktrees/<repo>/`. Per `feedback-workflow-parallel-same-repo-no-isolation.md`, worktrees are independent.
>
> **Origin of this plan:** §10 of `docs/plans/2026-10-09-bodai-search-infrastructure-fix.md` flagged health-check enrichment as out-of-scope for that plan (separate code path, separate ownership, separate policy concerns under `mcp-backend-wiring-discipline.md`). The akosha Phase 4 work landed as `cd4733b` on akosha local main on 2026-10-09 (the count→work→sleep reorder + the mcp_tool_call_feed health routing fix) — that's the pilot for the fleet-wide pattern. The remaining 4 Bodai core repos need the same treatment, plus the canonical `/health` aggregator and the 503-on-degraded contract.
>
> **Architectural constraints (from `.claude/decisions/mcp-backend-wiring-discipline.md`):**
> - Every Bodai MCP server's `/health` must aggregate per-feed state and return 503 on degraded
> - Every registered tool must have a working data feed (`feed.entities_count`, `feed.last_updated_timestamp`, `feed.errors_total`, `cycles_total`)
> - Every tool registration requires `tests/integration/test_<tool>_e2e.py` asserting non-empty results
> - End-to-end smoke tests in CI must spin up the server and assert non-empty responses per tool
> - Audit cadence: monthly Bodai-wide

**Goal:** When this plan ships, every Bodai core MCP server's `GET /health` returns:
- `200 OK` with `{"status": "ok", "feeds": {...}, "tools": [...]}` when every feed has `cycles_total > 0` and `errors_total == 0`
- `503 Service Unavailable` with `{"status": "degraded", "feeds": {...}, "tools": [...], "degraded_feeds": [...]}` when any feed reports `cycles_total == 0` for more than 60s OR `errors_total > 0` for more than 60s
- The aggregator must surface the same feed-state across `mcp__<server>__get_health()` AND `/health` — disagreement between them is a bug (per `mcp-backend-wiring-discipline.md`)

**Tech Stack:** Python 3.14, FastMCP 2.x, mcp-common `HealthFeedState` + `HealthAggregator` (already shipped in `mcp-common/health/` — adoption is the work), per-server MCP tools.

**Architecture:** 4 merge cycles (one per repo — akosha already done in `cd4733b`; mahavishnu, crackerjack, session-buddy, oneiric remain). The project uses ephemeral branches + squash-merge to local `main` + auto-push (per `docs/specs/2026-10-03-agent-reviewed-trunk-based-dev.md` §4). No shared release, no version bump — each repo picks up the fix on its own cadence. Per `feedback-bodai-push-is-user-controlled.md`, `git push origin main` is governed by the user.

**Spec:** `mcp-common` already ships the canonical `HealthFeedState` and `HealthAggregator`. The work is *adoption* (call them in the right place) not *implementation*. See `mcp-common/mcp_common/health/aggregator.py` and `mcp-common/mcp_common/health/feed.py` for the contract.

## 1. Outcome

When this plan ships:

- `mcp__akosha__get_health()` and `GET /health` on akosha: `200` when every feed is healthy-or-warming-up; `503` when any feed has been broken-before-first-success for more than 60s OR has accumulating errors.
- `mcp__crackerjack__get_health()` and `GET /health` on crackerjack: same contract.
- `mcp__session-buddy__get_health()` and `GET /health` on session-buddy: same contract.
- `mcp__mahavishnu__get_health()` and `GET /health` on mahavishnu: same contract.
- `mcp__oneiric__get_health()` and `GET /health` on oneiric: same contract.
- The HNSW hardening branch in each server's `/health` consumer no longer fires on a fresh server with no data yet (the `cycles_total == 0` false-positive that the akosha `cd4733b` fix addressed fleet-wide).
- Monthly `mcp audit_health` CLI runs against all 5 core repos and reports any server that returns `200` for a degraded feed state.

**Done when** (acceptance gates):
- All 5 repos have landed the changes (4 new merge cycles + 1 already done)
- 17 new validation probes (per §7 below) all pass when run against each released version
- No new `/health` route was added (each repo already has one)
- The fleet-wide audit (`mahavishnu mcp audit_health --all-repos`) reports 0 silent-degraded servers

## 2. Goals

1. **Adopt the mcp-common `HealthAggregator`** in each of the 5 Bodai core MCP servers, replacing any local per-feed health-state construction with the canonical aggregator. (REQ-HC-001)
2. **Return 503 on degraded** in each server's `/health` route when the aggregator reports any feed in `broken-before-first-success` or `errors-accumulating` state for more than 60s. The route currently returns 200 with a degraded envelope in the body — that's the bug. (REQ-HC-002)
3. **Make `mcp__<server>__get_health()` and `GET /health` agree** on the same feed-state. Today they can disagree (per the akosha Phase 4 example: the MCP tool reported `degraded` while `/health` returned 200 with `status: ok` in the body). The fix is to route both through the same aggregator. (REQ-HC-003)
4. **Ship a monthly `mahavishnu mcp audit_health` CLI** that iterates the 5 core repos, calls `/health` on each, and reports any server that returns 200 with a degraded feed state (the silent-degraded case). Cadence: monthly, owned by the operator. (REQ-HC-004)

## 3. Non-Goals

- **No new metrics.** The four mandatory signals (`entities_count`, `last_updated_timestamp`, `cycles_total`, `errors_total`) are already in `mcp-common` and are already emitted by each repo's ingesters. We are not adding new Prometheus metrics or new OTel spans.
- **No changes to the MCP transport.** The wire-shape envelope for `mcp__<server>__get_health()` is unchanged.
- **No removal of the existing `/health` route.** Each server already has one; we're changing its return code logic and routing it through the canonical aggregator, not adding a new route.
- **No version bumps, no `crackerjack run -p`, no PyPI publish.** Per `feedback-mcp-common-version-bump-is-user.md` and `feedback-crackerjack-publish-stage-is-user.md`, the user owns version and release.
- **No federation changes.** The fleet-wide audit CLI is a one-shot per-repo call, not a federation layer.
- **No rewrite of the ingester cycle-ordering pattern.** That was akosha's `cd4733b` — done. The other 4 repos may or may not have the same bug; this plan audits + fixes, not rewrites.

## 4. Current Findings

### 4.1 Akosha: Phase 4 already landed (`cd4733b`)

Verified in `git log -1 main` of `/Users/les/Projects/akosha`:
- `akosha/mcp/server.py:566-625` — kg_refresh loop reordered to count → work → sleep (matches `code_graph_ingester.py:129` / `otel_ingester.py:156` pattern). Reason: the prior `sleep(interval)` before the increment meant fresh servers sat at `cycles=0` (DEGRADED) for one full interval.
- `akosha/mcp/server.py:911-983` — `mcp_tool_call_feed` cycles/errors now source from the OTel ingester's OVERALL counters (not per-task-class). Reason: per-task-class counts stay at 0 on a fresh server until a `mcp_tool_call`-class span flows through, which made the HNSW hardening branch fire on every cold start.

**This plan does NOT re-do akosha.** The pilot is shipped. The other 4 repos need an audit + targeted fix (the same pattern may apply, may not).

### 4.2 Other 4 repos: not yet audited

Plan §4.5 of the prior workflow flagged this as the §10 followup. The audit hasn't been done yet. The likely scope is the same pattern (cycle-ordering + feed counter routing), but the exact files differ per repo. Each repo's Phase 1 will be a recon agent that:
1. Reads the server's `create_app` (or equivalent) to find the cycle/sleep ordering
2. Reads the `/health` route + the `mcp__<server>__get_health()` tool body
3. Identifies any per-task-class feed that might be subject to the broken-before-first-success false positive
4. Reports back: is the same pattern present? If yes, which files:lines?

### 4.3 Per-server scope (read-from-CLAUDE.md, not yet verified)

| Server | Health tool name | /health route | Source of cycle ordering |
|---|---|---|---|
| **akosha** | `mcp__akosha__get_health()` | `akosha/mcp/server.py:create_app` | `cd4733b` (done) |
| **mahavishnu** | `mcp__mahavishnu__get_health()` | `mahavishnu/mcp/server_core.py` | TBD by Phase 1 recon |
| **crackerjack** | `mcp__crackerjack__get_health()` | `crackerjack/mcp/server.py:create_app` | TBD by Phase 1 recon |
| **session-buddy** | `mcp__session-buddy__get_health()` | `session_buddy/server.py:create_app` | TBD by Phase 1 recon |
| **oneiric** | `mcp__oneiric__get_health()` | (not yet shipped — oneiric may not have an MCP server) | TBD by Phase 1 recon |

### 4.4 Requirements

```yaml
requirements:
  - id: REQ-HC-001
    title: "Each Bodai core MCP server's get_health + /health route sources from mcp-common HealthAggregator (no local per-feed construction)"
  - id: REQ-HC-002
    title: "/health returns 503 when any feed has been broken-before-first-success OR errors-accumulating for >60s"
  - id: REQ-HC-003
    title: "mcp__<server>__get_health() and GET /health report the same feed-state on every call"
  - id: REQ-HC-004
    title: "mahavishnu mcp audit_health --all-repos CLI: monthly, reports any server that returns 200 with degraded feed state"
```

## 5. Implementation Phases

### Phase 1: Audit + adopt mcp-common HealthAggregator in each of the 4 remaining repos

**Goal:** Each repo's `mcp__<server>__get_health()` and `/health` route route through the canonical `mcp_common.health.aggregator.HealthAggregator`. The akosha pilot is the reference implementation.

**Per-repo worktree setup:**
1. `git fetch origin main` from the source repo
2. `git worktree add ~/.local/state/mahavishnu/worktrees/<repo>-health-enrichment -b phase-<N>-health-enrichment origin/main`
3. `uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"`
4. Verify Python 3.14.x

**Tasks per repo:**
1. **Recon:** Read the current `create_app` (or equivalent), the `mcp__<server>__get_health()` tool body, the `/health` route, and any per-feed state construction. Identify which feeds are subject to the broken-before-first-success false positive.
2. **Adopt the aggregator:** Replace any local feed-state construction with a single `HealthAggregator` instance, fed by the existing ingester/processor cycle counters. The aggregator is the single source of truth for both `mcp__<server>__get_health()` and `/health`.
3. **Wire 503:** Change the `/health` route's return code from `200` to `503` when the aggregator reports any feed in `broken-before-first-success` for >60s OR `errors-accumulating` for >60s. The body remains the same envelope (operators can still inspect which feed is degraded).
4. **Add the `get_health` MCP tool** if not already present. Most repos already have it; verify it routes through the same aggregator.
5. **Tests:** Add `tests/integration/test_health_e2e.py` that:
   - Asserts the FastMCP tool returns 200 + ok envelope when every feed is healthy
   - Asserts the tool returns 503 + degraded envelope when a stub feed reports `cycles_total=0` for >60s
   - Asserts the wire-shape envelope (per REQ-012 pattern from the prior plan)
6. **`crackerjack run -v`** (NEVER `-p`)
7. **Commit + squash-merge** to local main

**Exit criteria per repo:** `mcp__<server>__get_health()` and `/health` agree, both return 503 on degraded, all tests pass.

#### Integration Contract — Phase 1.1 (mahavishnu)
- **Triggered from**: `GET /health` on mahavishnu (HTTP route, port 8680); `mcp__mahavishnu__get_health()` (MCP tool invocation); `mahavishnu mcp audit_health --repo mahavishnu` (CLI)
- **Returns to / updates**: HTTP response code (200 or 503) and JSON envelope (status, feeds, tools, degraded_feeds)
- **Demonstrable by**: `curl -sI http://localhost:8680/health` returns 200 (or 503 in degraded); `pytest tests/integration/test_health_e2e.py::test_health_returns_503_on_broken_feed` passes
- **Rollback signal**: If `mcp__mahavishnu__get_health()` and `/health` disagree, OR if `/health` returns 503 when all feeds are healthy (false-positive 503), revert via `git reset --hard HEAD~1` on the worktree branch
- **Observability added**: `mahavishnu.health.feed_status{feed, status}` counter, `mahavishnu.health.aggregate_status` counter
- **Fulfils**: REQ-HC-001, REQ-HC-002, REQ-HC-003

#### Integration Contract — Phase 1.2 (crackerjack)
- **Triggered from**: `GET /health` on crackerjack (port 8676); `mcp__crackerjack__get_health()`; `mahavishnu mcp audit_health --repo crackerjack`
- **Returns to / updates**: HTTP response code + JSON envelope
- **Demonstrable by**: `curl -sI http://localhost:8676/health` returns 200 (or 503); `pytest tests/integration/test_health_e2e.py` passes
- **Rollback signal**: Same as Phase 1.1
- **Observability added**: `crackerjack.health.feed_status{feed, status}` counter
- **Fulfils**: REQ-HC-001, REQ-HC-002, REQ-HC-003

#### Integration Contract — Phase 1.3 (session-buddy)
- **Triggered from**: `GET /health` on session-buddy (port 8678); `mcp__session-buddy__get_health()`; `mahavishnu mcp audit_health --repo session-buddy`
- **Returns to / updates**: HTTP response code + JSON envelope
- **Demonstrable by**: `curl -sI http://localhost:8678/health`; `pytest tests/integration/test_health_e2e.py` passes
- **Rollback signal**: Same
- **Observability added**: `session_buddy.health.feed_status{feed, status}` counter
- **Fulfils**: REQ-HC-001, REQ-HC-002, REQ-HC-003

#### Integration Contract — Phase 1.4 (oneiric)
- **Triggered from**: `GET /health` on oneiric (if oneiric ships an MCP server; verify in recon); `mcp__oneiric__get_health()` (if it exists)
- **Returns to / updates**: HTTP response code + JSON envelope
- **Demonstrable by**: `curl -sI http://localhost:<oneiric-port>/health`; `pytest tests/integration/test_health_e2e.py` passes
- **Rollback signal**: Same
- **Observability added**: `oneiric.health.feed_status{feed, status}` counter
- **Fulfils**: REQ-HC-001, REQ-HC-002, REQ-HC-003

### Phase 2: Fleet-wide audit CLI

**Goal:** `mahavishnu mcp audit_health --all-repos` runs against all 5 Bodai core repos, calls `/health` on each, reports any server that returns 200 with a degraded feed state (the silent-degraded case).

**Tasks:**
1. Add `mahavishnu/mcp/tools/audit_health_tool.py` (or extend an existing audit tool) with the `mcp__mahavishnu__audit_health` MCP tool.
2. The tool iterates `settings/ecosystem.yaml` for the 5 core repos, calls `/health` on each, and returns a list of `{repo, status, silent_degraded_feeds, http_code}`.
3. `mahavishnu mcp audit_health --all-repos` CLI wraps the MCP tool.
4. Add `mahavishnu/tests/integration/test_audit_health.py` that:
   - Stubs the 5 repos and asserts the tool reports the right number of healthy vs degraded
   - Stubs a server returning 200 with a degraded feed state and asserts the tool flags it as `silent_degraded`

**Exit criteria:** CLI runs end-to-end against a stub set of repos; integration test passes.

#### Integration Contract — Phase 2
- **Triggered from**: `mahavishnu mcp audit_health --all-repos` (CLI); `mcp__mahavishnu__audit_health()` (MCP tool); monthly cron (operator-owned)
- **Returns to / updates**: stdout (CLI) or JSON envelope (MCP tool) listing per-repo health + silent-degraded flags
- **Demonstrable by**: `mahavishnu mcp audit_health --all-repos` returns a JSON report; `pytest tests/integration/test_audit_health.py` passes
- **Rollback signal**: If the audit reports a false-positive silent-degraded (i.e., the actual feed is healthy but the report flags it), revert via `git reset --hard HEAD~1`
- **Observability added**: `mahavishnu.audit.health_checked_repos{repo, status, http_code}` counter
- **Fulfils**: REQ-HC-004

## 6. Required Code Changes

**Phase 1 per repo (4 repos: mahavishnu, crackerjack, session-buddy, oneiric):**
- [ ] Recon: identify local feed-state construction + cycle-ordering pattern
- [ ] Replace local feed-state with `mcp_common.health.aggregator.HealthAggregator`
- [ ] Wire `/health` route to return 503 on degraded
- [ ] Wire `mcp__<server>__get_health()` MCP tool to the same aggregator
- [ ] Add `tests/integration/test_health_e2e.py`
- [ ] Add `crackerjack run -v` gate
- [ ] Commit + squash-merge

**Phase 2 (mahavishnu only):**
- [ ] Add `mahavishnu/mcp/tools/audit_health_tool.py` with the MCP tool
- [ ] Add `mahavishnu mcp audit_health --all-repos` CLI wrapper
- [ ] Add `mahavishnu/tests/integration/test_audit_health.py`

## 7. Validation Matrix

| Probe | Expected | Evidence |
|---|---|---|
| `curl -sI http://localhost:8680/health` (mahavishnu healthy) | `200 OK` | `mahavishnu/tests/integration/test_health_e2e.py` |
| `curl -sI http://localhost:8680/health` (mahavishnu degraded) | `503 Service Unavailable` | Same test, `test_health_returns_503_on_broken_feed` |
| `curl -sI http://localhost:8682/health` (akosha) | `200` (or `503` if any feed in degraded state) | akosha regression test |
| `mcp__mahavishnu__get_health()` | Same feed-state as `/health` | `test_get_health_matches_http_health` |
| `mahavishnu mcp audit_health --all-repos` | JSON report listing per-repo status | `mahavishnu/tests/integration/test_audit_health.py` |
| `pytest tests/integration/test_health_e2e.py` (per repo) | All pass | Per-repo CI |
| `pytest tests/integration/test_audit_health.py` (mahavishnu) | All pass | mahavishnu CI |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| False-positive 503 (every fresh server returns 503 for the first 60s) | Medium | The pilot's count→work→sleep reorder pattern (akosha `cd4733b`) must be applied where the same bug exists. Audit per repo will surface. |
| Inflight rollout — mahavishnu adoption flips /health from 200 to 503 and breaks a load balancer | Low | Add a feature flag `MAHAVISHNU_HEALTH_ENFORCED` (default `false`); the route always populates the body but only returns 503 when the flag is on. Operators opt in per environment. |
| The mcp-common `HealthAggregator` has a bug that surfaces in fleet-wide adoption | Low | Akosha pilot (4 months in production) is the reference. If a bug surfaces, fix in mcp-common and roll out. |
| 503 returned when only one tool is degraded, taking the whole server out of LB rotation | Medium | The aggregator's `errors-accumulating` threshold (>60s) is meant to suppress transient single-tool blips. Tune per environment. |

## 9. Decision Rule

This plan is "done enough" when:

- **Phase 1 (4 repos):** Each repo's `mcp__<server>__get_health()` and `/health` agree, both return 503 on degraded, integration test passes, `crackerjack run -v` clean, commit + squash-merge to local main. No push (user-controlled).
- **Phase 2:** `mahavishnu mcp audit_health --all-repos` runs end-to-end and the integration test passes. Feature-flagged rollout is acceptable.

**Scope-pressure cut line:** If a repo's health-check pattern is fundamentally different (e.g., oneiric has no MCP server, or its `/health` is implemented in a non-Python language), that repo is carved out of Phase 1 into a separate plan. The other 3 repos still ship.

**Sequencing note:** Per `feedback-bodai-push-is-user-controlled.md`, all merges are local-only. Push is the user's call per repo. The user owns version bumps, PyPI publishes, and any cross-repo release coordination. This plan does NOT introduce shared release pressure.

**Cross-plan dependency:** This plan is sequenced after `docs/plans/2026-10-09-bodai-search-infrastructure-fix.md` (status: `active` → `shipped`). The prior plan landed Phase 1 (akosha) of this scope as `cd4733b`. Phases 2-3 of the prior plan (crackerjack + session-buddy substantive search fixes) are shipped as `39c0f82` and `64714e8` respectively.

## 10. Followup Plan

This is itself a followup plan to `docs/plans/2026-10-09-bodai-search-infrastructure-fix.md`. No further followups are anticipated from this scope. If a future plan emerges (e.g., adding per-feed HTTP-level metrics endpoints), it would be a separate plan.
