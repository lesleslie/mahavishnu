# Plan: Wire-up PRs — Borrowed Features from Conductor OSS / conductross.com

**Date:** 2026-09-26
**Status:** Draft — **round-3 corrections + round-4 (8-agent) review + niche filter + no-backcompat policy applied**. Needs further per-commit code correction before implementation phase. Direct-to-main commits per Bodai merge policy. Pre-1.0, **no backwards compatibility** per `feedback-no-backwards-compat-pre-1.0`.
**Origin research:** [`docs/plans/2026-09-26-conductor-comparison-report.md`](2026-09-26-conductor-comparison-report.md) (companion comparison doc).
**Companion ADR:** [`docs/adr/0001-mahavishnu-niche.md`](../../adr/0001-mahavishnu-niche.md) — defines the deepening filter that drops C-7 and radically simplifies C-10.

## Review history

This plan has been through four rounds of multi-agent review.

- **Round 1** (7 reviewers) — Meta-cuts. Identified that most of the original 10-feature wishlist was already shipped under different names. Cut to **6 wire-up PRs**.
- **Round 2** (6 reviewers) — Implementation realism. Caught citation drift, TOCTOU race in WP-3, sync I/O in async code, missing CLI companions, Akosha integration misses, exception-type gaps.
- **Round 3** (6 reviewers) — Verification of round-2 corrections plus operational readiness. Caught remaining API drift (`EventBridgePublisher.publish()`, Oneiric `Action.execute()` uniform pattern), DB schema conflict between `init.sql` and consolidated migration, watcher deadlock (`watchfiles.awatch` + NFS), missing alert thresholds/runbooks/SLO docs, missing `EventBridgePublisher` injection helper.
- **Round 4** (8 reviewers, 2026-09-26) — Cross-domain adversarial review with non-overlapping lenses:
    - mahavishnu-specialist (wiring correctness) → needs-major-revisions
    - oneiric-specialist (config + action-kit API) → needs-minor-fixes
    - mcp-integration-expert (FastMCP wiring) → needs-major-revisions
    - backend-developer (crackerjack gates) → needs-major-revisions
    - api-security-specialist (HMAC, rate-limiting, secrets) → needs-major-revisions
    - devops-troubleshooter (DB migrations, observability) → needs-major-revisions
    - test-coverage-review-specialist (race tests, audit CI) → needs-major-revisions
    - pr-review-toolkit:code-reviewer (ace, confidence-filtered) → needs-major-revisions
    - **Union verdict**: needs-major-revisions. **21 critical findings**; cross-cutting criticals (3+ lens confirmation) include: `wait_for(async_generator)` TypeError (C-11), `pool_route_execute` arg-count failure (C-6+C-8), C-6/C-10 idempotency-key format mismatch, missing `@pytest.mark.req` marker + audit CI, `TaskEventType.PENDING` fictional, `oneiric_actions_compression_hash` fictional, `create_event_envelope` import path fictional, `severity=`/`topic=` kwargs fictional.

## Constraints (Bodai convention)

Per `bodai-pre-1.0-merge-policy.md`, all Bodai merges go directly to local `main` pre-1.0. **No PRs.** Each wire-up lands as a single-author series of commits on `main`:

| Commit | Repo | Land target | LoC |
|--------|------|-------------|-----|
| C-1 (config models prep) | mahavishnu | `main` | ~250 |
| C-2 (T-0 test scaffolding) | mahavishnu | `main` | ~300-400 |
| C-3 (event-history persistence) | mahavishnu | `main` | ~200-300 |
| C-4 (WP-precond-1: schema reconciliation) | mahavishnu | `main` | ~150 |
| C-5 (WP-precond-2: EventBridgePublisher helper) | mahavishnu | `main` | ~50 |
| ~~C-7 (WP-3b webhook nonce sweeper)~~ | mahavishnu | **DROPPED** | n/a |
| C-8 (WP-1 worktree isolation) | mahavishnu | `main` | ~130 |
| C-9 (WP-4 concurrency limit) | mahavishnu | `main` | ~250-300 |
| C-10 (radically simplified ecosystem intake) | mahavishnu | `main` | ~80-120 |
| C-11 (WP-5 markdown board — scoped to jot files) | mahavishnu | `main` | ~350-450 |
| C-12 (WP-6 executions show CLI) | mahavishnu | `main` | ~150-200 |
| C-13 (WP-7 crackerjack review-pr) | crackerjack | `main` | ~200-300 |

**Total realistic LoC after all corrections: ~3,500-4,500 LoC** (per round-4 ace reviewer pacing estimate; reduced from ~5,000 by the niche filter dropping C-7 and radically simplifying C-10).

Each commit is independently revertible via `git revert <sha>`. CI gate is `crackerjack run -p minor` per `crackerjack-cli-run-subcommand.md`; user-initiated version bumps per `crackerjack-version-bumping-manual.md`.

## Policy: No backwards compatibility / legacy support

This plan lands pre-1.0. There is **no supported backwards-compatible path** to any prior implementation. Every commit replaces as needed (per `feedback-no-backwards-compat-pre-1.0` memory):

- **Methods**: replaced, not extended with deprecation windows. Old signatures go away.
- **Settings namespaces**: consolidated, not duplicated as siblings. New keys land in existing sections.
- **Migrations**: forward-only. No `downgrade()` body. Recovery = follow-up forward migration.
- **Auth/signature schemes**: final version only. No V1 readers with 7-day flag windows. No dual-secret rotation.
- **Dual-API patterns**: drop to single-API. Pick one, delete the other.
- **No phase-in feature flags** (`<thing>_ENABLED: bool`). Just enable.
- **No bidirectional branching** ("if old_key use old_value; else new_value"). Just use new_value.

Reviewers who reflexively add "backwards-compat for X" by default should **not**.

## Strategic niche filter

Per [`docs/adr/0001-mahavishnu-niche.md`](../../adr/0001-mahavishnu-niche.md), every borrowed feature must pass the **deepening filter**:

1. Does it deepen our niche (LLM control plane + repo orchestrator)?
2. Does it advance Bodai integration (Session-Buddy / Akosha / Crackerjack / Oneiric / mcp-common)?
3. Does it compete with the source tool's core niche? ("yes" = drop or radically simplify)

Score **"no, no, yes"** = pivot, not deepening. Drop or simplify before committing LoC.

**Filter verdicts for the 13 commits** (none carried forward without amendment):

| Commit | Deepens? | Bodai? | Competes? | Verdict |
|---|---|---|---|---|
| C-1 config models | yes (precondition) | yes | no | **keep** |
| C-2 test scaffolding | yes (test infra) | yes | no | **keep** |
| C-3 event-history | yes (LLM observability) | yes (EventStore) | no | **keep** |
| C-4 schema reconciliation | yes (idempotency infra) | yes | no | **keep** |
| C-5 EventBridgePublisher helper | yes (Bodai infra) | yes | no | **keep**, drop server-scoped dual-API |
| C-6 idempotency on `pool_route_execute` | yes (LLM dispatch reliability) | yes | no | **keep** |
| **C-7 webhook nonce sweeper** | no (Conductor-shape) | △ | **yes** | **drop — Conductor's niche, not ours** |
| C-8 worktree isolation | yes (repo orchestrator core) | yes | no | **keep** |
| C-9 ConcurrencyGate per TaskCategory | yes (LLM routing determinism) | yes | no | **keep** |
| **C-10 webhook intake + HMAC + DLQ** | partial | partial | **yes** (Conductor's core) | **simplify drastically** — strip HMAC, nonce, DLQ, multi-secret rotation, register tool; keep only `/webhooks/ecosystem/{source}` allowlist + sanitize |
| C-11 markdown board watcher | partial (only as own jot surface) | yes (jot is ours) | no | **keep**, scope to our jot files |
| C-12 executions CLI | yes (LLM execution history) | yes | no | **keep** |
| C-13 crackerjack review-pr | yes | yes (Crackerjack is core Bodai) | no | **keep** |

**Outcome**: **C-7 is dropped**, **C-10 radically simplified**. The remaining 11 commits pass the filter and proceed with the 21 critical corrections from round 4.

## Round-4 criticals (load-bearing for implementation)

These are the cross-cutting bugs that must be fixed before any commit lands. Many are applied in the per-commit sections below; the rest are queued.

- **C-11 `wait_for(async_generator)` TypeError** — confirmed by 3 lenses (ops, ace, code-quality). Replace with `async with asyncio.timeout(...)`.
- **`pool_route_execute` arg count will exceed `max-args=10`** (13 params) — confirmed by mcp + code-quality. Group into `WorktreeOptions`/`IdempotencyOptions` dataclasses.
- **C-6/C-10 idempotency key format mismatch** (raw `f"{source}:{nonce}"` vs hashed) — ace + security.
- **Fictional APIs**: `TaskEventType.PENDING`, `oneiric_actions_compression_hash`, `severity=`/`topic=` on `create_event_envelope`, security sub-module imports — mahavishnu + oneiric + code-quality.
- **`create_event_envelope` import path** wrong (lives in `mahavishnu.core.events.contract`, not `oneiric.runtime.events`).
- **C-10 sync dispatch collapses under 1000 webhooks/min** — RESOLVED by C-10 simplification (no dispatch path; just `safe_publish`).
- **`Permission.MANAGE_WEBHOOK` enum missing** — RESOLVED by C-10 simplification (no `webhook_register` tool).
- **`@pytest.mark.req` marker not registered**, no audit CI workflow file.
- **No SLO on `pool_route_execute`** (primary dispatch path) — fixed in SLOs section.
- **C-4 `CREATE INDEX CONCURRENTLY` in Alembic transaction block** (well-known PG gotcha) — fixed in C-4.
- **C-4 forward-only contradicts "reverse Alembic revision" rollback** — RESOLVED (forward-only, no downgrade).
- **Nonce TTL / sweeper-interval race** — RESOLVED (C-7 dropped).
- **HMAC signs body only** — RESOLVED (C-10 simplified, no HMAC).
- **ConcurrencyGate per-process scope silently fails in multi-worker pools** — flagged; C-9 must document explicitly.
- **`_main_cli.py` path is `mahavishnu/_main_cli.py`** (package root, not `cli/`) — fixed in C-12.
- **`event_store.delete_expired_nonces` method doesn't exist** — RESOLVED (C-7 dropped, no longer needed).
- **7 line-length violations** would fail `ruff E501` — fix during implementation.
- **C-10 `handle_webhook` exceeds `max-returns=6`** — RESOLVED by C-10 simplification (now 1 return).
- **Runbooks listed as deliverables but empty** — 4 runbooks remain (worktree, concurrency, ecosystem-intake, markdown-watcher, executions-cli).
- **Pacing undercounted ~2x** — RESOLVED (LoC totals updated).
- **C-13 cross-repo coupling un-pinned** — fix in C-13.

## Traceable spec IDs (REQ-NNN)

Per `crackerjack-compliant-code` skill, each wire-up declares REQ-NNN IDs in `## 4.5 Requirements` (YAML under `requirements:`). Code references via inline marker `# req: REQ-001` (or comma-separated) or docstring marker `# Implements: REQ-001`. Audit via `python scripts/audit_requirements.py --json`.

| REQ ID | Description | Wire-up |
|--------|-------------|---------|
| REQ-001 | Oneiric nested settings models (consolidated under existing namespaces — no new top-level siblings) | C-1 |
| REQ-002 | T-0 test scaffolding (8 fixtures, autouse cleanup) | C-2 |
| REQ-003 | Execution events persistence layer | C-3 |
| REQ-004 | Schema reconciliation migration (`idempotency_key VARCHAR(255) UNIQUE` on `audit.task_events`) | C-4 |
| REQ-005 | EventBridgePublisher singleton module (replaces server-scoped path; single-API) | C-5 |
| REQ-006 | `pool_route_execute(idempotency=IdempotencyOptions(...))` with single-row in-place PENDING→COMPLETED update | C-6 |
| REQ-007 | DB-level unique constraint enforcement + asyncio.Lock fallback | C-6 |
| REQ-008 | SHA-256 hex fingerprinting via Oneiric `HashAction().execute(...)["digest"]` | C-6 |
| ~~REQ-009~~ | ~~Webhook nonce cleanup sweeper~~ — REMOVED (C-7 dropped per niche filter) | n/a |
| REQ-010 | `pool_route_execute(worktree=WorktreeOptions(...))` with REPLACED `WorktreeInfo` (diff/merge/files_touched + `complete_worktree()` returns them) | C-8 |
| REQ-011 | `WorktreeLockedError` exception reused (no competing subclass) | C-8 |
| REQ-012 | `ConcurrencyGate` per-TaskCategory with shard locks by `(category, pool_id)` | C-9 |
| REQ-013 | Token-bucket rate limiting with fail-closed default | C-9 |
| REQ-014 | (Dropped — replaced by C-10 ecosystem intake, which uses sanitize-only, not HMAC) | n/a |
| REQ-015 | (Dropped — no `webhook_register` MCP tool; ecosystem intake uses configured allowlist) | n/a |
| REQ-016 | 200 vs 202 response distinction (kept for C-10 simplified) | C-10 |
| REQ-017 | Markdown board watcher with `async with asyncio.timeout(...)` deadlock mitigation + `fcntl.flock` sidecar | C-11 |
| REQ-018 | `mahavishnu board {init,status,validate}` companion CLIs (scoped to our jot files) | C-11 |
| REQ-019 | `mahavishnu executions {list,show}` Typer sub-app | C-12 |
| REQ-020 | Oneiric `ValidationSchemaAction` + `DataTransformAction` + `DataSanitizeAction` for board parsing (with real payload shapes from `oneiric/actions/data.py`) | C-11 |

---

## What already exists (verified across 19+ reviewers)

| Concern | Existing primitive | Verified by |
|---------|--------------------|-------------|
| Saga/failure cleanup | `mahavishnu/core/dead_letter_queue.py` (928 LoC, `RetryPolicy.{NEVER,LINEAR,EXPONENTIAL,IMMEDIATE}`, automatic retry processor, manual `retry_task()`, archival, statistics) + `dlq_integration.py` + `dlq_metrics.py` + `config_dlq.py` + `retry_policy.py` + `circuit_breaker.py` + `heal_workflows()` at `mcp/server_core.py:907` + structured exception hierarchy in `errors.py` | Round-1 + round-2 |
| Idempotency | `mahavishnu/core/event_store.py:95` (`idempotency_key` field on `TaskEvent`) + `get_event_by_idempotency_key()` at line 510 + `webhook_handler.py:345` (duplicate check) + `migrations/init.sql:110` (`idempotency_key VARCHAR(255) UNIQUE`) | Round-1 + round-3 (schema drift) |
| Rate limiting | `mahavishnu/core/rate_limit.py:152` (`is_allowed(key, config) -> tuple[bool, RateLimitInfo]` — **not** `.allow()`) + `budget.py` (`BudgetSpec` per-workflow `@dataclass`) + `budget_enforce` at `pool_tools.py:203` | Round-3 |
| ~~Webhooks (full surface)~~ | **Dropped for HMAC + nonce + DLQ** (C-10 simplified). Existing `mahavishnu/webhooks/{models,receiver,replay,router}.py` and `mcp/tools/webhook_tools.py:webhook_replay_tool` retained for legacy OpenClaw routes only. | C-10 simplification |
| Worktree isolation | `mahavishnu/core/worktree_manager.py:228` `create_worktree(task_id, repo_path, branch_name, base_branch="main")` + line 324 `complete_worktree(worktree_id, merge, repo_path)` + `WorktreeInfo` `@dataclass` (only `to_dict()` exists; C-8 **REPLACES** the class with diff/merge/files_touched) + `worktree_session_registry.py` + `mcp/tools/worktree_tools.py` (`worktree_manage` MCP tool) | Round-3 |
| Task board | `mahavishnu/jot/` (function-module style: `handle.py`, `events.py`, `fold.py`, `render.py`; JSONL event log at `paths.py:log_path()`) — **no `JotStore` class, no `upsert_from_board` method**. C-11 stays in this style; nothing new. | Round-3 |
| Execution drill-down | `mcp/server_core.py:917` `get_monitoring_dashboard()` + `mahavishnu/websocket/server.py:415` `get_workflow_status` (request handler — **NOT** an event log). C-3 provides event log; C-12 reads it. | Round-3 |
| Oneiric action kits | `oneiric/actions/{security,data,compression,...}.py` — every `Action` exposes `async execute(payload: dict) -> dict`. Real names: `SecuritySignatureAction`, `SecuritySecureAction`, `HashAction`, `ValidationSchemaAction`, `DataTransformAction`, `DataSanitizeAction`. Imports are flat (`from oneiric.actions.X import Y`), not sub-module paths. | Round-4 oneiric |
| Akosha seam | `EventBridgePublisher.publish(envelope: OneiricEventEnvelope)` at `mahavishnu/core/events/eventbridge_adapter.py:41`; instantiated via module-global singleton in `mahavishnu/core/events/publisher.py:25` (added by C-5); envelope helper at `mahavishnu/core/events/contract.py:36` as `create_event_envelope(event_type, payload, source, ...)` (NOT `topic`, NOT `oneiric.runtime.events`). Server-scoped `eventbridge_resolver.resolve_event_publisher()` removed per no-backcompat policy. | Round-4 mahavishnu + oneiric |
| TaskCategory | `mahavishnu/core/model_routing.py` (`TaskCategory` enum) — Phase 3b atomic migration | Round-1 |
| Terminal adapter registry | `mahavishnu/terminal/adapters/{crow,goose,mock,tmux,base}.py` | Round-1 |
| TaskEventType enum | `mahavishnu/core/event_store.py:49-81` — has 19 values; C-3 adds `PENDING = "pending"` | Round-4 mahavishnu |
| Oneiric logger | `oneiric.logging.getLogger` (project-standard; not stdlib `logging`, not `print`) | Round-4 oneiric + crackerjack |

---

## C-1 (config models prep — must land FIRST)

**Goal:** Add five new Oneiric Pydantic settings models to `mahavishnu/core/config.py` as a single prep-commit. **Per the no-backcompat policy, new sections are consolidated into existing namespaces** (no new sibling top-level sections). Without this, the existing `ConfigDict(extra="forbid")` semantics on nested sections will reject unknown keys at startup.

**File scope:** `mahavishnu/core/config.py` (add `WorktreeStorageSettings`, `IdempotencySettings`, `WebhookIntakeSettings`, `ConcurrencyLimitsSettings`, `MarkdownBoardSettings` Pydantic models — the first extends an existing settings block, the other four are net-new top-level sections), `settings/mahavishnu.yaml` (add empty top-level sections with defaults), `tests/unit/test_config_sections.py`. **Plus** `pyproject.toml`: register `@pytest.mark.req` marker; **Plus** `.github/workflows/audit_requirements_advisory.yml` + `_gate.yml` (weekly + monthly).

**Settings (per no-backcompat, nested YAML; new sections follow existing `changepoint:`, `hatchet:` precedent):**
```yaml
# Worktree settings: nested under EXISTING worktree_storage (NOT a new sibling).
# Real precedent sections for new siblings: changepoint:, hatchet:,
# oneiric_mcp:, goal_teams:, learning:, adapter_registry:, engines:,
# health:, integrations:, mcp_state:.
worktree_storage:
  enabled: false                  # default off until C-8 lands
  default_isolation: "host"       # when pool_route_execute(worktree=...) is None
  base_branch: "main"             # default for worktree isolation
  storage_root: null              # null = $XDG_DATA_HOME/mahavishnu/worktrees/
  max_concurrent: 5
  cleanup_grace_seconds: 300
  ttl_seconds: 86400

idempotency:
  enabled: true
  default_ttl_seconds: 86400
  fail_mode: "closed"             # "open" = proceed on DB outage; "closed" = reject
  storage_backend: "event_store"  # alternative: "session_buddy"
  pending_timeout_seconds: 30

webhook_intake:
  enabled: false
  bind_host: "127.0.0.1"
  bind_port: 8695                 # PENDING BODAI_REPO_REGISTRY.md confirmation (must verify during C-1 impl)
  tls_required: true
  max_payload_size_bytes: 1048576

concurrency_limits:
  enabled: true
  default: null                   # null = unlimited
  by_category: {}                 # map of TaskCategory -> ConcurrencyLimitSpec

markdown_board:
  enabled: false
  default_path: ".mahavishnu/board.md"
  path_resolution: "repo"         # "repo" or "global" — restricted to repo paths per niche scope
  watcher_debounce_seconds: 1.0
  watcher_lag_seconds: 30.0
  state_sidecar_suffix: ".state.json"
  section_mapping:
    backlog: "backlog"
    ready: "ready"
    in_progress: "in_progress"
    done: "done"
```

**Env vars (MAHAVISHNU_*):**
- `MAHAVISHNU_WORKTREE_STORAGE__ENABLED`, `__DEFAULT_ISOLATION`, `__BASE_BRANCH`, `__STORAGE_ROOT`, `__MAX_CONCURRENT`, `__CLEANUP_GRACE_SECONDS`, `__TTL_SECONDS`
- `MAHAVISHNU_IDEMPOTENCY__ENABLED`, `__DEFAULT_TTL_SECONDS`, `__FAIL_MODE`, `__STORAGE_BACKEND`, `__PENDING_TIMEOUT_SECONDS`
- `MAHAVISHNU_WEBHOOK_INTAKE__ENABLED`, `__BIND_HOST`, `__BIND_PORT`, `__TLS_REQUIRED`, `__MAX_PAYLOAD_SIZE_BYTES`
- `MAHAVISHNU_CONCURRENCY_LIMITS__ENABLED`, `__DEFAULT`
- `MAHAVISHNU_MARKDOWN_BOARD__ENABLED`, `__DEFAULT_PATH`, `__PATH_RESOLUTION`, `__WATCHER_DEBOUNCE_SECONDS`, `__WATCHER_LAG_SECONDS`, `__STATE_SIDECAR_SUFFIX`

**Removed env vars per C-10 simplification + no-backcompat:** `__DEFAULT_RATE_LIMIT_PER_MINUTE`, `__DEFAULT_REPLAY_WINDOW_SECONDS`, `__FAIL_CLOSED_ON_STORE_UNAVAILABLE`, `__NONCE_STORE` (pertained to dropped HMAC+nonce+DLQ surface).

**No secret-naming convention** — C-10 simplified intake has no per-source secrets.

**Oneiric config update:** update `docs/CONFIGURATION.md` "Configuration Block Reference" with all new sections + env-var table. Required for `crackerjack-gitignore-sync-dev-dep-downgrade.md` style automation.

**Wire-up contract:**
- *Triggered from:* operator upgrading or fresh-installing Mahavishnu.
- *Returns to / updates:* `MahavishnuSettings` (top-level wrapper, `extra="allow"` at top; nested sections have `extra="forbid"` per `mahavishnu/core/config.py:2633-2637`).
- *Demonstrable by:* `pytest tests/unit/test_config_sections.py::test_<each>_settings_loads_with_defaults`; `mahavishnu mcp start` does not fail with `ValidationError: extra fields not permitted`. **Plus** `pytest --markers` shows `req` registered. **Plus** `python scripts/audit_requirements.py --json` exits 0.
- *Rollback signal:* N/A (precondition). Recovery = forward-only correction.
- *Observability added:* N/A at config-load.
- *Health aggregation:* `_register_health_tools` includes config loader status.
- *Acceptance criteria:* `@pytest.mark.req(["REQ-001"])` on every new test; `audit_requirements.py` reports 0 orphans; no `downgrade()` path on the Alembic revisions later.

---

## C-2 (T-0 test scaffolding — lands AFTER C-1, BEFORE all wire-ups)

**Goal:** Ship `tests/integration/conftest_wireups.py` with shared fixtures before any wire-up test lands.

**File scope:** `tests/integration/conftest_wireups.py` (new, ~300-400 LoC — round 3 said ~50% larger than round-2 estimate).

**Fixtures to ship:**
- `isolated_database` — uses `tempfile.NamedTemporaryFile(suffix=".db")` (NOT `aiosqlite :memory:`, which is per-connection and shared across xdist workers per round-3 QA review). Per-test fresh DB.
- `tmp_xdg_state_dir` — context manager monkeypatches `platformdirs`-derived paths to temp dir.
- `controllable_pool_manager_mock` — counts `route_task` calls, can block on `asyncio.Event` for pending-status tests.
- `worktree_manager_factory` — constructs `WorktreeManager` against `temp_git_repo` with temp `base_path`.
- `ecosystem_intake_signed_post` — generates sanitized POST payloads for C-10 tests (no HMAC, just dict-to-JSON).
- `ecosystem_intake_test_client` — `fastapi.testclient.TestClient` wrapping fresh `FastAPI()` with ecosystem intake router injected.
- `ecosystem_dlq_inspector` — reads through Akosha pattern events (NOT `mahavishnu/core/dead_letter_queue.py`; intake has no DLQ).
- `mark_finished_tasks` autouse — explicit `try/finally` body: scan `$XDG_DATA_HOME/mahavishnu/worktrees/` for worktrees newer than test invocation, `git worktree remove --force` on failure path.
- `frozen_clock` fixture — **new**, uses `freezegun.freeze_time()` for `time.time` + `datetime.now(UTC)` per round-3 QA. Existing `clock` fixture at `tests/conftest.py:233` (only patches `time.time`) is preserved unchanged.
- Per-test `idempotency_flag_monkeypatch` — patches `get_settings()` cache so `idempotency.fail_mode` is per-test, not global. Required because xdist workers race on global flag.
- Per-test `safe_publisher_monkeypatch` — patches `mahavishnu.core.events.publisher.set_publisher` for isolated publishing assertions.

**Test runtime budget:** mark slow tests `@pytest.mark.slow` (per CLAUDE.md convention); cap suite wall-clock via `pytest -n auto --dist=loadfile` so worktree tests serialise on one worker. Each new test decorated `@pytest.mark.req(["REQ-NNN"])` per the REQ it covers.

**Wire-up contract:**
- *Triggered from:* pytest collection.
- *Returns to:* existing `tests/conftest.py` (`frozen_clock` is new, `clock` reuses existing).
- *Demonstrable by:* each fixture has its own unit test in `tests/unit/test_conftest_wireups.py`.
- *Rollback signal:* N/A.
- *Observability:* N/A.

---

## C-3 (event-history persistence — precondition for C-12 and C-6)

**Goal:** Add `execution_events` table so `mahavishnu executions show` (C-12) has historical data to query. **Also add `TaskEventType.PENDING = "pending"` to the enum** (C-6 + C-10 historical webhook path both reference this value; without it C-6 raises `AttributeError`).

**File scope:** `mahavishnu/core/event_store.py` (add `execution_events` table + `record_execution_event()` method + `get_execution_events(execution_id) -> list[ExecutionEvent]` + **add `PENDING = "pending"` to `TaskEventType` StrEnum at lines 49-81**), `mahavishnu/core/errors.py` (add `IdempotencyStoreUnavailable` exception class — used by C-6 and C-10 fail-closed paths), Alembic revision `migrations/versions/V202609260003__execution_events.sql`, `tests/integration/test_event_store_execution_events.py`.

**Net-new symbols:**
- `TaskEventType.PENDING = "pending"` (one line, one commit)
- `record_execution_event(execution_id, event_type, data, actor, *, correlation_id=None, occurred_at=None)`
- `get_execution_events(execution_id) -> list[ExecutionEvent]`
- `execution_events` SQLAlchemy table + Alembic migration
- `IdempotencyStoreUnavailable` exception (in `mahavishnu/core/errors.py`)

**Sketch:**
```python
# In mahavishnu/core/event_store.py
class TaskEventType(StrEnum):
    # ... existing values (CREATED, UPDATED, ..., SYNCED) ...
    PENDING = "pending"  # NEW per round-4 review (mahavishnu specialist); C-6 + C-10 historical use
    # ... rest unchanged


class IdempotencyStoreUnavailable(MahavishnuError):
    """Idempotency store unreachable; fail-CLOSED behavior expected."""


def record_execution_event(
    execution_id: str,
    event_type: TaskEventType,
    data: dict[str, Any],
    actor: str,
    *,
    correlation_id: str | None = None,
    occurred_at: datetime | None = None,
) -> None:
    ...


def get_execution_events(execution_id: str) -> list[ExecutionEvent]:
    ...
```

**Wire-up contract:**
- *Triggered from:* every workflow lifecycle event (`workflow.started`, `workflow.stage_started`, `workflow.stage_completed`, `workflow.completed`, `workflow.failed`).
- *Returns to:* `EventStore`; `mahavishnu executions show` (after C-12 lands).
- *Demonstrable by:* e2e test runs a 3-stage workflow, queries `event_store.get_execution_events(execution_id)`, asserts all 5+ events returned; `TaskEventType.PENDING.value == "pending"`.
- *Rollback signal:* N/A (forward-only).
- *Observability added:* `execution_events_total{event_type}`, `execution_event_log_latency_seconds`.
- *Acceptance criteria:* `@pytest.mark.req(["REQ-003"])` on tests; `PENDING` enum value works in C-6's idempotency path; no `downgrade()` body on the Alembic revision.

---

## C-4 (WP-precond-1: schema reconciliation migration — must land BEFORE C-6)

**Goal:** Resolve schema conflict between `migrations/init.sql:110` (which has `idempotency_key VARCHAR(255) UNIQUE`) and `migrations/versions/V202604021200__initial_consolidated_schema.sql:103` (which defines `audit.task_events` WITHOUT the `idempotency_key` column). Without this, `EventStore.append(idempotency_key=...)` throws `asyncpg.UndefinedColumnError` on production deployments that have run the consolidated migration. **Forward-only. No `downgrade()`.**

**File scope:** `migrations/versions/V202609260001__idempotency_key_unique.sql` (new forward-only Alembic revision), `tests/integration/test_migration_idempotency_key.py`.

**Migration:**
```sql
-- V202609260001__idempotency_key_unique.sql
-- Forward-only. No downgrade. Recovery is a follow-up forward migration if needed.
-- IMPORTANT: CREATE UNIQUE INDEX CONCURRENTLY cannot run inside a transaction block.
-- Alembic's default uses transactions. Set `transaction_per_migration = False`
-- in env.py for THIS revision, OR use op.execute() per-statement (autocommit).
-- Recommendation: split into two revisions:
--   rev A (transactional): add the column
--   rev B (non-transactional): create the unique index via op.execute() post-COMMIT

DO $$
BEGIN
    -- Pre-flight: detect duplicate idempotency_keys before adding the constraint
    IF EXISTS (
        SELECT 1 FROM (
            SELECT COUNT(*) - COUNT(DISTINCT idempotency_key) AS dup_count
            FROM audit.task_events
            WHERE idempotency_key IS NOT NULL
        ) sub WHERE dup_count > 0
    ) THEN
        RAISE EXCEPTION 'pre-flight: duplicate idempotency_keys detected; dedupe before migrating';
    END IF;
END$$;

-- Add the column (transactional — fast)
ALTER TABLE audit.task_events ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(255);
```

And (separate revision B):
```sql
-- V202609260001b__idempotency_key_index.sql
-- Non-transactional: op.execute() runs outside the Alembic transaction
COMMIT;
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_task_events_idempotency_key
    ON audit.task_events (idempotency_key)
    WHERE idempotency_key IS NOT NULL;
```

**Implementation note**: Pick the two-revision approach (rev A = column, rev B = index). Avoid `transaction_per_migration = False` globally because other migrations may need transactional safety.

**Wire-up contract:**
- *Triggered from:* operator runs `alembic upgrade head` (or whatever the migration runner is — project uses `migrations/versions/V*.sql`, runner unclear; verify before landing).
- *Returns to:* `EventStore` no longer broken on consolidated-schema deployments.
- *Demonstrable by:* integration test against a DB initialized with `V202604021200__initial_consolidated_schema.sql`, run `V202609260001` and `V202609260001b`, assert column exists + index created; pre-flight throws if duplicate keys present.
- *Rollback signal:* N/A (forward-only). Recovery = follow-up forward migration.
- *Observability added:* `migration_duration_seconds{revision, direction}` (Counter with `_bucket` histogram).
- *Acceptance criteria:* migration runs end-to-end on the consolidated-schema DB; pre-flight trips if duplicate keys present; `alembic downgrade -1` is undefined (intentional); test `@pytest.mark.req(["REQ-004"])`.

---

## C-5 (WP-precond-2: EventBridgePublisher module-global singleton — must land BEFORE all wire-ups that publish to Akosha)

**Goal:** Provide a module-global singleton `get_publisher() -> EventBridgePublisher | None` helper so wire-ups have a real acquisition point. **Per the no-backcompat policy, the module-global replaces the existing server-scoped `eventbridge_resolver.resolve_event_publisher(server)` path entirely** — both cannot coexist; one replaces the other.

**File scope:** `mahavishnu/core/events/publisher.py` (new, ~50 LoC), `mahavishnu/factories.py` (wire `set_publisher()` to the existing `_wire_eventbridge_publisher`; **delete the server-scoped downstream callers that had been patched through** `eventbridge_resolver.resolve_event_publisher(server)` — they now use the global), `tests/unit/test_publisher.py`.

**Sketch:**
```python
from __future__ import annotations

from typing import TYPE_CHECKING
from oneiric.logging import getLogger  # project-standard logger, not stdlib

if TYPE_CHECKING:
    from mahavishnu.core.events.eventbridge_adapter import EventBridgePublisher
    from mahavishnu.core.events.contract import OneiricEventEnvelope


_publisher: EventBridgePublisher | None = None
logger = getLogger(__name__)


def set_publisher(publisher: EventBridgePublisher | None) -> None:
    """Inject the publisher singleton. Called by mahavishnu/factories.py at app boot."""
    global _publisher
    _publisher = publisher


def get_publisher() -> EventBridgePublisher | None:
    """Return the injected publisher, or None if not configured.
    All wire-up Akosha integrations must handle None gracefully (log + metric, no-op)."""
    return _publisher


async def safe_publish(envelope: OneiricEventEnvelope) -> bool:
    """Fire-and-forget publish. Returns True if published, False if skipped (Akosha down or unconfigured).
    NEVER raises — observability must never block the dispatch path.
    Catches Exception (not BaseException) so CancelledError propagates per crackerjack-compliant-code."""
    publisher = get_publisher()
    if publisher is None:
        return False
    try:
        await publisher.publish(envelope)
        return True
    except Exception:
        logger.exception("EventBridge publish failed",
                          extra={"envelope_event_type": getattr(envelope, "event_type", None)})
        return False
```

**Wire-up contract:**
- *Triggered from:* `mahavishnu/factories.py:_wire_eventbridge_publisher` at app boot (already exists).
- *Returns to:* singleton publisher for the whole process.
- *Demonstrable by:* positive `test_publisher_safe_publish_returns_true_when_configured`; negative `test_publisher_safe_publish_handles_none_publisher`; exception-path `test_publisher_safe_publish_swallows_exception`; round-trip `test_set_publisher_roundtrip`.
- *Rollback signal:* N/A (precondition).
- *Observability added:* `eventbridge_publish_total{envelope_event_type, result}` (success/skip/error).
- *Acceptance criteria:* `set_publisher` injects; `get_publisher` returns; `safe_publish` returns True on success / False on None / False on exception (without raising); server-scoped resolver callers migrated to global.

---

## ~~C-7 (Webhook→EventStore nonce cleanup sweeper)~~ — DROPPED per niche filter

**Decision**: Per [`docs/adr/0001-mahavishnu-niche.md`](../../adr/0001-mahavishnu-niche.md), the webhook nonce sweeper is a **Conductor-shape feature** that competes with the source tool's core niche, not Mahavishnu's. The webhook→EventStore nonce eviction loop serves external webhook intake — Mahavishnu is an LLM control plane + repo orchestrator, not an event intake daemon. **Drop.** The associated REQ-009 is removed from the traceable-spec IDs table.

**Replacement event flow for cross-system triggers** (notifies C-13): External systems that need to trigger Mahavishnu work should publish to Akosha via standard Akosha publishers (not via Mahavishnu webhook intake). Crackerjack's `review-pr` skill then subscribes to an Akosha pattern, not to a Mahavishnu HTTP endpoint.

---

## C-8 (WP-1: `pool_route_execute(worktree=WorktreeOptions(...))` — lands AFTER C-6)

**Goal:** Add `worktree` Pydantic input model to `pool_route_execute`. **Per no-backcompat, REPLACE `WorktreeInfo` outright** — don't extend the existing class with `diff()`, `merge()`, `files_touched()` methods. Compute those fields in `complete_worktree()` and attach to a fresh `WorktreeInfo` shape. **Also: drop the invented `GitRunner`** — use `asyncio.to_thread(git_subprocess_call)` directly in `complete_worktree`.

**File scope:** `mahavishnu/mcp/tools/pool_tools.py` (extend signature with `worktree: WorktreeOptions | None = None`), `mahavishnu/core/worktree_manager.py` (REPLACE `WorktreeInfo` — new shape includes `diff: str`, `merge: bool`, `files_touched: list[str]`; `complete_worktree` computes these), `mahavishnu/core/errors.py` (verify existing `WorktreeLockedError` at line 1792 + `WorktreeError` at line 1769), `tests/integration/test_pool_worktree_isolation.py`, `tests/property/test_worktree_path_uniqueness_property.py`.

**Sketch (corrected — group params into WorktreeOptions):**
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Any
from uuid import uuid4

from mahavishnu.core.worktree_manager import WorktreeLockedError, WorktreeError


@dataclass(frozen=True)
class WorktreeOptions:
    """Pydantic input model for pool_route_execute(worktree=...)."""
    isolation: Literal["host", "worktree"] = "host"
    base_branch: str = "main"
    ttl_seconds: int = 86_400
    on_completion: Literal["auto_merge", "discard", "return_diff"] = "return_diff"


async def pool_route_execute(
    prompt: str,
    pool_selector: str = "least_loaded",
    idempotency: "IdempotencyOptions | None" = None,
    worktree: WorktreeOptions | None = None,  # Pydantic input model — keeps arg count under max-args=10
) -> dict[str, Any]:
    worktree_info = None
    execution_id = str(uuid4())
    settings = get_settings()

    effective_isolation = worktree.isolation if worktree else settings.worktree_storage.default_isolation
    repo_nickname = _resolve_repo_nickname(prompt)  # impl detail

    if effective_isolation == "worktree" and await _repo_has_git(repo_nickname):
        try:
            worktree_info = await worktree_manager.create_worktree(
                task_id=execution_id,
                repo_path=_resolve_repo_path(repo_nickname),
                branch_name=f"feature/{execution_id}-{uuid4().hex[:8]}",
                base_branch=worktree.base_branch if worktree else settings.worktree_storage.base_branch,
                ttl_seconds=worktree.ttl_seconds if worktree else settings.worktree_storage.ttl_seconds,
            )
            await safe_publish(create_event_envelope(
                event_type="insight.generated",
                payload={"insight_type": "worktree_created",
                         "worktree_id": worktree_info.worktree_id,
                         "repo_nickname": repo_nickname},
                source="mahavishnu.pool_route_execute",
                correlation_id=execution_id,
            ))
        except WorktreeLockedError as exc:
            logger.exception("worktree lock conflict",
                            extra={"error_id": "WORKTREE_LOCK_CONFLICT"})
            metrics.worktree_creation_total.labels(result="lock_conflict").inc()
            await safe_publish(create_event_envelope(
                event_type="anomaly.detected",
                payload={"anomaly_type": "worktree_lock_conflict",
                         "execution_id": execution_id},
                source="mahavishnu.pool_route_execute",
                metadata={"severity": "medium"},
            ))
            return {"status": "worktree_conflict", "error": str(exc)}
        except WorktreeError:
            logger.exception("worktree creation failed",
                            extra={"error_id": "WORKTREE_CREATION_FAILED"})
            metrics.worktree_creation_total.labels(result="error").inc()
            raise

    try:
        result = await _dispatch_internal(prompt, pool_selector, execution_id)
        if worktree_info and effective_isolation == "worktree":
            on_completion = worktree.on_completion if worktree else "return_diff"
            completion = await worktree_manager.complete_worktree(
                worktree_id=worktree_info.worktree_id,
                merge=(on_completion == "auto_merge"),
                repo_path=_resolve_repo_path(repo_nickname),
            )
            # complete_worktree now returns WorktreeInfo with diff/merge/files_touched
            worktree_info = completion.info  # REPLACES WorktreeInfo with full shape
            result["worktree"] = {
                "diff": worktree_info.diff,
                "merge": worktree_info.merge,
                "files_touched": worktree_info.files_touched,
            }
            await safe_publish(create_event_envelope(
                event_type="insight.generated",
                payload={"insight_type": "worktree_completed",
                         "worktree_id": worktree_info.worktree_id,
                         "files_touched": worktree_info.files_touched},
                source="mahavishnu.pool_route_execute",
                correlation_id=execution_id,
            ))
        return result
    finally:
        if worktree_info and effective_isolation == "worktree":
            await worktree_manager.cleanup_worktree(
                worktree_id=worktree_info.worktree_id,
                repo_path=_resolve_repo_path(repo_nickname),
            )
```

**Companion CLI:** `mahavishnu worktree status` (uses existing `worktree_manage(action="list", ...)`).

**Property test:** `test_for_distinct_task_ids_paths_are_distinct` using `hypothesis.strategies.uuids()`.

**Wire-up contract:** *Triggered from:* `pool_route_execute(worktree=WorktreeOptions(...), ...)`. *Demonstrable by:* integration + property test. *Rollback signal:* `worktree_storage.enabled: false` (C-1). *Observability:* `worktree_creation_total{result}`, `worktree_active_count`, `worktree_disk_bytes`. *Acceptance criteria:* `WorktreeInfo` REPLACED (no `WorktreeInfo.diff` method exists; the data field is set by `complete_worktree`); no `GitRunner` symbol; C-8 worktree operations stay within max-concurrent (settings.worktree_storage.max_concurrent * active_pool_count); `@pytest.mark.req(["REQ-010", "REQ-011"])` on tests.

---

## C-9 (WP-4: Per-TaskCategory concurrency limits — lands AFTER C-1, parallel-safe with C-6)

**Goal:** Add `ConcurrencyGate` keyed on `TaskCategory`. Per security round-4 finding: **document the per-process scope prominently** (effective limit is N × spec.limit across N workers); add `pool_worker_id` label to metrics for aggregation.

**File scope:** `mahavishnu/core/rate_limit.py` (~80 LoC, extend `RateLimiter`), `mahavishnu/core/concurrency_gate.py` (new, ~150 LoC, with helper extraction per round-4 code-quality), `mahavishnu/mcp/tools/pool_tools.py` (wire at `budget_enforce` site), `settings/models.yaml` (extend per-TaskCategory limit config), `tests/integration/test_pool_concurrency_limit.py`, `tests/property/test_pool_concurrency_limit_property.py`.

**Sketch (corrected — uses real `is_allowed` signature, helper extraction, typed):**
```python
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING

from cachetools import LRUCache  # bounds shard_locks per round-4 security finding

if TYPE_CHECKING:
    from mahavishnu.core.model_routing import TaskCategory


class ConcurrencyGate:
    """Per-TaskCategory concurrency counter.

    LIMITATION: per-process scope. With N workers, effective limit is
    N × spec.concurrency_limit. Documented in docs/runbooks/concurrency-limit-storm.md.
    Fix path: replace with Redis/Dhara-backed shared counter when cross-pool
    guarantees are required.
    """

    def __init__(self, settings: "ConcurrencyLimitsSettings") -> None:
        self._specs: dict[TaskCategory, ConcurrencyLimitSpec] = settings.by_category
        self._counters: dict[tuple[TaskCategory, str | None], int] = defaultdict(int)
        self._shard_locks: LRUCache = LRUCache(maxsize=1024)

    async def try_acquire(self, category: TaskCategory, pool_id: str | None) -> bool:
        spec = self._specs.get(category)
        if spec is None or spec.concurrency_limit is None:
            return True
        key = (category, None if spec.global_override else pool_id)
        lock = self._shard_locks.get(key) or asyncio.Lock()
        self._shard_locks[key] = lock
        async with lock:
            if self._counters[key] >= spec.concurrency_limit:
                return False
            self._counters[key] += 1
            return True

    async def release(self, category: TaskCategory, pool_id: str | None) -> None:
        spec = self._specs.get(category)
        if spec is None:
            return
        key = (category, None if spec.global_override else pool_id)
        lock = self._shard_locks.get(key)
        if lock is None:
            return
        async with lock:
            self._counters[key] = max(0, self._counters[key] - 1)

    def spec_for(self, category: TaskCategory) -> ConcurrencyLimitSpec | None:
        """Public accessor — replaces direct `_specs` access."""
        return self._specs.get(category)


# In pool_tools.py around line 203
async def _enforce_concurrency_limit(task_category: TaskCategory, pool_id: str) -> None:
    if not await concurrency_gate.try_acquire(task_category, pool_id):
        spec = concurrency_gate.spec_for(task_category)
        raise RateLimitError(
            limit=spec.concurrency_limit if spec else None,
            retry_after_seconds=_estimate_retry(spec),
            domain=f"task_category={task_category.value}",
        )
```

**`_estimate_retry` formula:** `return 1.0 if spec.refill_rate_per_second <= 0 else max(1.0, 1.0 / spec.refill_rate_per_second)` (per round-4 LOW finding: avoid `ZeroDivisionError` on `refill_rate_per_second == 0`).

**Companion CLI:** `mahavishnu concurrency status [--category CODE_GENERATION]` (reads metrics), `mahavishnu concurrency reset --category CODE_GENERATION` (per-process only — documented limitation).

**Property test:** `tests/property/test_pool_concurrency_limit_property.py::test_invariant_active_count_never_exceeds_limit` — stateful Hypothesis test, **with `@pytest.mark.slow` + `@pytest.mark.timeout(120)`** per round-4 test lens.

**Wire-up contract:** *Demonstrable by:* integration + property test. *Observability:* `task_domain_concurrency{domain, pool_worker_id}` (gauge — added `pool_worker_id` label per security), `task_domain_rate_limited_total{domain}`, `task_domain_queue_depth{domain}`, `task_domain_throughput{domain}`, `task_domain_concurrency_drift_total` (atomicity-violation metric). *Acceptance criteria:* `@pytest.mark.req(["REQ-012", "REQ-013"])`; documented per-process limitation in runbook.

---

## C-10 (ecosystem event intake — radically simplified; lands AFTER C-5)

**Decision**: The original C-10 (HMAC + nonce + DLQ + multi-secret rotation + register MCP tool) is **Conductor-shape scope** that competes with the source tool's niche. Mahavishnu is not a general-purpose webhook router. **Replace with the minimal viable ecosystem intake below.**

**Goal**: One endpoint: `POST /webhooks/ecosystem/{source_name}`. Source must be in a configured allowlist (NOT a registered dynamic source). Body is sanitized via `DataSanitizeAction` and forwarded via `safe_publish`. **No HMAC, no nonce, no DLQ, no registration MCP tool, no multi-secret support.**

**Why this is Mahavishnu-shaped**: Bodai components (crontroller, git-monitor, internal ops bridge) push events into Mahavishnu's intake. External systems (GitHub, Stripe) publish to **Akosha directly** via the standard Akosha publisher. Crackerjack's `review-pr` skill subscribes to an Akosha pattern.

**File scope:** `mahavishnu/webhooks/ecosystem_intake.py` (new, ~40-60 LoC), `mahavishnu/webhooks/receiver.py` (register the new route alongside existing OpenClaw routes), `mahavishnu/core/errors.py` (add `EcosystemIntakeError` — one exception class), `tests/integration/test_ecosystem_intake.py`.

**Net-new symbols:** `EcosystemIntakeError`, `ALLOWED_SOURCES` frozenset. **Not added:** `WebhookSecretMissingError`, `webhook_register` MCP tool, `WebhookAuthError` (kept in `errors.py` for legacy paths; not relevant here), separate webhook DLQ, `webhook/registry.py`, `webhook/hmac.py`.

**Sketch:**
```python
from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from oneiric.actions.data import DataSanitizeAction
from oneiric.logging import getLogger

from mahavishnu.core.config import get_settings
from mahavishnu.core.errors import EcosystemIntakeError
from mahavishnu.core.events.contract import create_event_envelope
from mahavishnu.core.events.publisher import safe_publish


router = APIRouter()
ALLOWED_SOURCES: frozenset[str] = frozenset({"git-monitor", "crontroller", "ops-bridge"})
logger = getLogger(__name__)


@router.post("/webhooks/ecosystem/{source_name}")
async def ecosystem_intake(source_name: str, request: Request) -> JSONResponse:
    if source_name not in ALLOWED_SOURCES:
        return JSONResponse({"status": "not_found"}, status_code=404)
    settings = get_settings()
    if not settings.webhook_intake.enabled:
        return JSONResponse({"status": "disabled"}, status_code=503)
    payload = await request.body()
    if len(payload) > settings.webhook_intake.max_payload_size_bytes:
        return JSONResponse({"status": "too_large"}, status_code=413)
    try:
        sanitized = await DataSanitizeAction().execute({
            "data": payload.decode(errors="replace"),
            "mask_fields": ["Authorization", "token", "key", "secret"],
        })
        envelope = create_event_envelope(
            event_type="ecosystem.event.received",
            payload={"source": source_name, "data": sanitized.get("data", "")},
            source=f"mahavishnu.webhooks.ecosystem.{source_name}",
            correlation_id=str(uuid4()),
            metadata={"severity": "info"},
        )
        published = await safe_publish(envelope)
    except EcosystemIntakeError:
        raise
    except Exception:
        # Catch Exception, not BaseException — CancelledError propagates
        logger.exception("ecosystem intake failed", extra={"source": source_name})
        return JSONResponse({"status": "error"}, status_code=500)
    return JSONResponse(
        {"status": "accepted" if published else "queued_no_publisher"},
        status_code=202,
    )
```

**Companion CLI:** `mahavishnu ecosystem list [--json]` — shows allowlist source names. No register/rotate/test/dlq.

**Runbook:** `docs/runbooks/ecosystem-intake.md` (3 scenarios).

**SLO:** `ecosystem_intake_total{source, result}`, `ecosystem_intake_sanitize_duration_seconds_bucket`. Critical: `ecosystem_intake_total{result="error"} rate > 0.05/s for 5m` → Slack.

**Wire-up contract:** *Demonstrable by:* 4 integration tests — allowed source 202, disallowed source 404, oversized 413, sanitization strips `Authorization`. Plus 1 unit test for `DataSanitizeAction` payload shape. *Rollback signal:* `webhook_intake.enabled: false` returns 503. *Observability:* as above. *Health aggregation:* `pool_health` reports `degraded` if `safe_publish` returns False >10% over 5m.

---

## C-11 (WP-5: markdown board watcher — scoped to our jot files)

**Goal:** Build `mahavishnu jot export --output .mahavishnu/board.md` and a file watcher that imports our jot cards. **Per niche filter, scoped to our jot files only** (not a generic markdown-board engine).

**File scope:** `mahavishnu/jot/markdown_export.py` (new, ~80 LoC), `mahavishnu/jot/markdown_watcher.py` (new, ~150 LoC — corrected from round-3's 120 due to genuine complexity), `mahavishnu/jot/markdown_parser.py` (new, ~100-150 LoC with explicit `ValidationFieldRule` list), `mahavishnu/cli/jot_cli.py` (add `export`, `watch` Typer commands), `mahavishnu/cli/board_cli.py` (new — `mahavishnu board {init,status,validate}`), `mahavishnu/mcp/tools/jot_tools.py` (add `jot_export_markdown` MCP tool), `mahavishnu/jot/state_persistence.py` (new, ~50 LoC, sidecar atomic write via `fcntl.flock` in `try/finally`), `pyproject.toml` (add `watchfiles` dep: `watchfiles~=1.0,<1.1` per `feedback-crackerjack-gitignore-sync-dev-dep-downgrade.md`), `tests/integration/test_jot_markdown_roundtrip.py`, `tests/property/test_jot_markdown_property.py`.

**New exception classes:** `MarkdownWatcherDied`, `MarkdownParseError`.

**Critical corrections (round-4 review):**
- **`wait_for(async_generator)` TypeError fixed** — replace with `async with asyncio.timeout(settings.markdown_board.watcher_lag_seconds * 3):` (Python 3.11+) around `async for changes in watchfiles.awatch(...)`.
- **`except (OSError, FileNotFoundError)` redundancy fixed** — `FileNotFoundError` is a subclass of `OSError` per PEP 3151. Use `except OSError:` only.
- **MHCard adds `from __future__ import annotations`** (crackerjack rule).
- **Drop unused `Field` import** (crackerjack rule).
- **Line length fix** for `await f.write(...)` line — extract helper.
- **fcntl.flock in `try/finally`** invariant documented; lock-fd leak risk flagged.

**Companion CLIs:** Same as round-3 (init/status/validate). **Scoped** to our repo's `.mahavishnu/board.md`.

**Watcher sketch (corrected):**
```python
from __future__ import annotations

import json
import asyncio
import fcntl
from enum import Enum
from pathlib import Path

import aiofiles
from watchfiles import awatch, Change
from oneiric.logging import getLogger

from mahavishnu.jot.paths import log_path as jot_paths_log_path
from mahavishnu.core.events.contract import create_event_envelope
from mahavishnu.core.events.publisher import safe_publish


logger = getLogger(__name__)


async def watch_board(board_path: Path, state_sidecar: Path,
                     watcher_lag_seconds: float) -> None:
    metrics.markdown_board_watcher_up.set(1)
    while True:
        try:
            async with asyncio.timeout(watcher_lag_seconds * 3):
                async for changes in awatch(str(board_path)):
                    for change_type, path in changes:
                        if change_type is Change.modified:
                            await _handle_modified(path, board_path, state_sidecar)
        except asyncio.TimeoutError:
            logger.warning("watcher timeout — restarting")
            metrics.markdown_board_watcher_restarts_total.inc()
            continue
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            logger.exception("watcher crashed; supervisor will restart")
            metrics.markdown_board_watcher_up.set(0)
            await safe_publish(create_event_envelope(
                event_type="anomaly.detected",
                payload={"anomaly_type": "markdown_watcher_died", "error": str(exc)},
                source="mahavishnu.jot.markdown_watcher",
                metadata={"severity": "high"},
            ))
            raise
```

**MHCard Pydantic model (corrected):**
```python
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel


CardSection = Literal["backlog", "ready", "in_progress", "done"]


class MHCard(BaseModel):
    id: str
    status: CardSection
    title: str
    pool: str
    prompt: str
    expected_revision: int | None = None  # CAS token for human-edit conflict detection
```

**Wire-up contract:** *Demonstrable by:* integration test (roundtrip, watcher dispatch, malformed skip, file edit during dispatch, watcher crash recovery, sidecar consistency) + property test (`parse(render(cards)) == cards`) + race test (`asyncio.gather(N=10) with asyncio.Event` barrier). *Observability:* `markdown_board_watcher_up`, `markdown_board_watcher_restarts_total`, `markdown_board_card_age_seconds{section}`, `markdown_board_dispatch_total{section, result}`, `markdown_board_conflict_total`, `markdown_board_parse_errors_total`. *Acceptance criteria:* `@pytest.mark.req(["REQ-017", "REQ-018", "REQ-020"])`; concrete `ValidationFieldRule` list passed; full `from __future__ import annotations`.

---

## C-12 (WP-6: `mahavishnu executions show` CLI — lands AFTER C-3)

**Goal:** Add a Typer CLI to surface execution history.

**Critical correction (round-4):** the click-vs-typer note cites `mahavishnu/_main_cli.py:164-165` (package ROOT), NOT `mahavishnu/cli/_main_cli.py:164-165` (which doesn't exist). **Plus**, the original spec's "renamed from `mahavishnu debug`" rationale is vacuous — `mahavishnu debug` doesn't exist anywhere in the codebase. Drop that line.

**File scope:** `mahavishnu/cli/executions_cli.py` (new, ~150-200 LoC), `tests/integration/test_executions_cli.py`, `tests/e2e/test_executions_show_e2e.py` (per `.claude/decisions/mcp-backend-wiring-discipline.md`).

**Sketch (corrected):**
```python
from __future__ import annotations

import asyncio
import json
import uuid

import typer
from oneiric.logging import getLogger

from mahavishnu.core.config import get_settings
from mahavishnu.core.event_store import get_execution_events
from mahavishnu.core.errors import MahavishnuError


logger = getLogger(__name__)
executions_app = typer.Typer(help="Inspect workflow executions (LLM history)")


@executions_app.command("list")
def list_cmd(
    status: str | None = typer.Option(None, "--status"),
    workflow_id: str | None = typer.Option(None, "--workflow"),
    limit: int = typer.Option(50, "--limit"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """List recent executions."""
    asyncio.run(_list_async(status, workflow_id, limit, json_output))


@executions_app.command("show")
def show_cmd(
    execution_id: str = typer.Argument(...),
    step: str | None = typer.Option(None, "--step"),
    watch: bool = typer.Option(False, "--watch"),
    fmt: str = typer.Option("markdown", "--format"),
    raw: bool = typer.Option(False, "--raw"),
) -> None:
    """Show execution details for a given execution_id."""
    try:
        asyncio.run(_show_async(execution_id, step, watch, fmt, raw))
    except MahavishnuError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1)
```

**Wire-up contract:** *Demonstrable by:* integration tests including known execution, `--step N`, unknown execution graceful error, `--watch` streaming, pagination at 10k+ events. *Rollback signal:* standalone CLI. *Observability:* standard CLI invocation metrics + Akosha `pattern.detected` on recurring debug sessions. *Acceptance criteria:* `_main_cli.py:164-165` is correct path; no `mahavishnu debug` rename claim; tests `@pytest.mark.req(["REQ-019"])`.

---

## C-13 (WP-7: crackerjack review-pr skill — separate repo, separate plan)

**Goal:** Crackerjack skill that subscribes to an Akosha pattern (per round-4 niche filter — no Mahavishnu webhook trigger), pulls GitHub PR diff via `CRACKERJACK_GITHUB_TOKEN` env var, runs Crackerjack quality gates, dispatches code-review agent via Mahavishnu, posts review back as PR comment.

**Repo:** Crackerjack (separate). Lands on `main` per Bodai merge policy. **No** PR-based CI; per `crackerjack-cli-run-subcommand.md`, `crackerjack run -p minor` is the gate (user-initiated bumps).

**File scope (specific filenames, not vague terms):** `crackerjack/skills/review_pr.py` (new, ~120 LoC), `crackerjack/skills/__init__.py` (registration), `crackerjack/skills/github_client.py` (new, ~60 LoC, `respx` mocks for CI), `crackerjack/skills/comment_poster.py` (new, ~40 LoC), `crackerjack/skills/durable_queue.py` (new, ~50 LoC — local queue for retry on GitHub 5xx), `crackerjack/tests/integration/test_review_pr.py` (5 error paths), `crackerjack/tests/e2e/test_review_pr_e2e.py` (per `mcp-backend-wiring-discipline.md`).

**Crackerjack-side config:**
```yaml
# crackerjack/settings/ai.yaml
crack:
  github:
    api_key_env: "CRACKERJACK_GITHUB_TOKEN"  # env-var reference, NEVER raw
    fork_pr_quota_buffer: 10
```

**Env var:** `CRACKERJACK_GITHUB_TOKEN` (referenced via `api_key_env` per Oneiric convention).

**Trigger pattern (replaces webhook trigger):** Crackerjack subscribes to Akosha pattern `ecosystem.event.received{source="git-monitor"}`. No Mahavishnu webhook dependency. Pattern detection at `mcp__akosha__detect_anomalies` or equivalent.

**Wire-up contract:** *Demonstrable by:* `tests/integration/test_review_pr.py` with `respx` mocks for GitHub API covering: 5xx, 429 with backoff, auth failure, malformed PR diff, network timeout. Plus e2e smoke test against real GitHub test repo. *Rollback signal:* disabled in skill registry (binary flag). *Observability:* `pr_review_duration_seconds_bucket`, `pr_review_post_total{result}`, `github_api_quota_remaining`, `pr_review_fork_pr_total{result}`, Akosha `pattern.detected` for recurring review findings.

**Cross-repo coupling:** Version-pin to `mahavishnu >= 0.29` (C-5 publishes `safe_publish`); write contract test asserting `MahavishnuSettings.webhook_intake.enabled` is queryable from crackerjack via the configured channel.

---

## Cross-cutting requirements

### Runbooks (per-wire-up deliverables)

Every wire-up must ship a runbook in `docs/runbooks/` following the Symptoms/Diagnosis/Recovery/Verification/Postmortem format from `docs/runbooks/on_call_handbook.md`:

- `docs/runbooks/worktree-isolation.md` (C-8): 3 scenarios — worktree_conflict envelope, idempotency store unavailable, worktree leak detection
- `docs/runbooks/concurrency-limit-storm.md` (C-9): 2 scenarios — rate_limited envelope flood, atomicity drift tick, **per-process limitation** warning
- `docs/runbooks/ecosystem-intake.md` (C-10): 3 scenarios — source not in allowlist, payload too large, `safe_publish` returns False
- `docs/runbooks/markdown-watcher.md` (C-11): 4 scenarios — `markdown_board_watcher_up=0`, restarts_total climbing, cards stuck in ready, sidecar drift
- `docs/runbooks/executions-cli.md` (C-12): 1 scenario — `--watch` loses WebSocket for 5 retries

### SLO / alerting docs

Per `docs/slos/_TEMPLATE.md`, every feature needs an SLO doc with burn-rate alert + page-after field:

- `docs/slos/2026-09-26-wireup-pool-dispatch.md` (C-6 + C-8 + C-9)
- `docs/slos/2026-09-26-wireup-ecosystem-intake.md` (C-10)
- `docs/slos/2026-09-26-wireup-markdown-board.md` (C-11)

Critical alerts (round-3 + round-4 ops gap-fix):

| Metric | Threshold | Route |
|--------|-----------|-------|
| `markdown_board_watcher_up = 0 for 2m` | PagerDuty/Grafana Incident OnCall |
| `markdown_board_watcher_restarts_total > 3/min for 5m` | Slack `#mahavishnu-ops` |
| `ecosystem_intake_total{result="error"} rate > 0.05/s for 5m` | Slack (C-10) |
| `idempotency_key_storage_errors_total rate > 0.1/s for 2m` | Slack (DB struggling) |
| `idempotency_key_lookup_latency_seconds_bucket{p99} > 500ms for 5m` | Slack (DB hot path) |
| **`pool_route_execute_duration_seconds_bucket{p99} > 30s for 5m`** | **Slack** (primary dispatch path latency; was missing pre-round-4) |
| **`pool_route_execute_total{result="error"} rate > 0.05/s for 5m`** | **Slack** (primary dispatch error rate) |
| `worktree_disk_bytes > 80% disk` | Slack; > 95% → page |
| `worktree_active_count > settings.worktree_storage.max_concurrent * active_pool_count` | Slack (operator leak) |
| `task_domain_rate_limited_total{domain} rate > 1/s for 5m` | Slack |
| `task_domain_concurrency_drift_total > 0 in 5m` | Slack (atomicity broken — code bug) |

### Documentation deliverables per wire-up

Per round-3 DX reviewer, every wire-up must formally own its docs:

- `docs/features/markdown-board.md` (C-11) — 30-second demo, why-this-matters, what-this-replaces
- `docs/security/ecosystem-intake.md` (C-10) — sanitization rules, allowlist extension procedure, fail-503 switch
- `docs/ops/jot-watcher.md` (C-11) — launchd plist + systemd unit snippets
- `docs/cli/executions-show.schema.json` (C-12) — JSON output schema
- Update `docs/CLI_REFERENCE.md` — every new command
- Update `docs/CONFIGURATION.md` — every new section + env-var table

### Companion CLIs (per round-3 DX reviewer)

- `mahavishnu config get <dotted-key>` / `set <dotted-key> <value>` — Oneiric config discovery
- `mahavishnu akosha status` — verify Akosha received events
- `mahavishnu diagnostics collect [--redact] [--output PATH]` — bug-report bundle
- `mahavishnu ecosystem list [--json]` (C-10) — shows ecosystem intake allowlist

### Oneiric action-kit usage (real API)

Every Oneiric action reference in this plan uses the real `await Action().execute(payload: dict) -> dict` pattern. **No** `.verify()`, `.apply()`, `.compute()`, or function-style invocations. Imports are flat (`from oneiric.actions.security import SecuritySignatureAction`), not sub-module paths.

| Spec intent | Real call | Source |
|-------------|-----------|--------|
| HMAC SHA-256 verify (not used in C-10 simplified, retained for completeness) | `await SecuritySignatureAction().execute({"body": payload, "secret": secret, "algorithm": "sha256", "encoding": "hex"})` | `oneiric/actions/security.py:43` |
| Constant-time compare (not used in C-10 simplified, retained) | `await SecuritySecureAction().execute({"mode": "compare", "a": a, "b": b})` | `oneiric/actions/security.py:140` |
| SHA-256 hex fingerprint (C-6) | `await HashAction().execute({"data": key, "algorithm": "sha256", "encoding": "hex"})` → `result["digest"]` | `oneiric/actions/compression.py:128, 178` |
| Schema validation (C-11 board parser) | Build explicit `[ValidationFieldRule(name=..., type=..., required=True), ...]` then `await ValidationSchemaAction().execute({"data": raw, "fields": rules})`. Do NOT pass `MHCard.model_fields` — wrong type. | `oneiric/actions/data.py:308` |
| Data transform (C-11 board projection) | `await DataTransformAction().execute({"data": raw, "include_fields": [...]})`. Do NOT pass a `target` kwarg — no such key. | `oneiric/actions/data.py:55-72` |
| Data sanitize (C-10 ecosystem intake) | `await DataSanitizeAction().execute({"data": raw, "mask_fields": ["Authorization", "token", "key", "secret"]})` | `oneiric/actions/data.py:163` |

### Akosha integration (real API)

Every Akosha publish uses `mahavishnu.core.events.contract.create_event_envelope` (NOT `oneiric.runtime.events` — that module does NOT export `create_event_envelope`). Envelopes carry `event_type`, not `topic`. Severity (optional, only for `anomaly.detected`) lives in the `metadata` dict, not as a top-level kwarg.

```python
from mahavishnu.core.events.contract import create_event_envelope
from mahavishnu.core.events.publisher import safe_publish

envelope = create_event_envelope(
    event_type="insight.generated",  # or anomaly.detected, pattern.detected, ecosystem.event.received
    payload={"insight_type": "...", "key": "value"},
    source="mahavishnu.<component>",
    correlation_id=execution_id,  # optional
    metadata={"severity": "medium"},  # optional, only used for anomaly.detected routing
)
await safe_publish(envelope)  # NEVER raises; returns True if published, False if skipped
```

**Never** `await akosha.publish_to_eventbridge(...)` — that symbol doesn't exist. **Never** `await eventbridge_publisher.publish(...)` without first acquiring via `get_publisher()`. **Never** let observability block the dispatch path.

### Typing standards (crackerjack-compliant-code skill)

Per the skill:
- `from __future__ import annotations` as first non-comment line of every source file
- Imports ordered: stdlib → third-party → first-party
- Full type annotations on all functions
- Modern Python syntax: `X | None`, `list[str]`, `pathlib.Path`
- No `assert` in production code
- Per-file function complexity ≤ 15, parameters ≤ 10, return points ≤ 6, statements ≤ 55

For `ty` suppressions:
- `# ty: ignore[invalid-argument-type]` for None-to-required-T fixes; prefer `assert x is not None` or `t.cast("T", value)`
- **NEVER** bare `# type: ignore` — ty silently ignores mypy/ruff syntax
- If > 5 `# ty: ignore` in a single file, audit before adding more

### crackerjack gates (per commit)

Per `crackerjack-cli-run-subcommand.md`:
- `crackerjack run -p minor` triggers ruff, mypy, pyright, ty, pytest `--cov-fail-under=89.01682905225863`, bandit, complexipy, refurb, safety, creosote, detect-secrets, pip-audit
- **C-4 (schema reconciliation)** may trigger `crackerjack-staged-oneiric-downgrade.md` per memory — first crackerjack run stages oneiric `>=0.19.1`→`>=0.19.0` downgrade; expect and commit
- `crackerjack-gitignore-sync-dev-dep-downgrade.md` per memory: `gitignore sync` modifies pyproject.toml; tight pins (`watchfiles~=1.0,<1.1`) survive; loose pins (`watchfiles>=0.1`) get clobbered

### Audit infrastructure (C-1 includes)

Per `crackerjack-compliant-code` skill:
- `pyproject.toml [tool.pytest] markers]` adds: `req = "REQ-NNN requirement IDs this test covers"`
- `.github/workflows/audit_requirements_advisory.yml` — `cron: '0 6 * * 1'` Mon 06:00 UTC (advisory)
- `.github/workflows/audit_requirements_gate.yml` — `cron: '0 6 1 * *'` first of month (hard gate after 30-day advisory window)
- Both workflows run `python scripts/audit_requirements.py --json`

---

## Sequencing (risk-front-loaded, niche-filter applied)

| # | Commit | Repo | Risk | Dependencies |
|---|--------|------|------|--------------|
| 1 | **C-1** config models prep | mahavishnu | Low | none |
| 2 | **C-2** T-0 test scaffolding | mahavishnu | Low | C-1 |
| 3 | **C-3** event-history + PENDING enum | mahavishnu | Low | C-1, C-2 |
| 4 | **C-4** schema reconciliation migration | mahavishnu | Medium | C-1, C-2 (tests need fresh DB) |
| 5 | **C-5** EventBridgePublisher module-global | mahavishnu | Low | C-1 |
| ~~7~~ | **~~C-7~~ WP-3b nonce sweeper** | **DROPPED** | n/a | n/a |
| 7 | **C-8** WP-1 worktree isolation | mahavishnu | Medium | C-1, C-2, C-5, C-6 |
| 8 | **C-9** WP-4 concurrency limits | mahavishnu | Medium | C-1, C-2 |
| 9 | **C-10** radically simplified ecosystem intake | mahavishnu | Low (allowlist + sanitize; no auth) | C-1, C-5 |
| 10 | **C-11** WP-5 markdown board (scoped to jot) | mahavishnu | Medium (new code + Akosha integration) | C-1, C-2, C-3, C-5 |
| 11 | **C-12** WP-6 executions show CLI | mahavishnu | Low | C-1, C-2, C-3 |
| 12 | **C-13** WP-7 crackerjack review-pr | crackerjack | Medium | **C-5** (Akosha publisher only — webhook trigger dropped per niche filter) |

**Hidden coupling** (round-3 backend, updated post-round-4 + niche filter):
- C-6 → C-4 (schema reconciliation must precede; `idempotency_key UNIQUE` on `audit.task_events`)
- ~~C-10 → C-6~~ (REMOVED — radically simplified C-10 no longer uses `idempotency_key`)
- ~~C-10 → C-7~~ (REMOVED — C-7 dropped entirely)
- C-11 → C-3 (markdown board dispatches may want execution event correlation; C-3 provides)
- ~~C-13 → C-10~~ (REMOVED — C-13's PR trigger comes from Akosha pattern subscription)
- **C-13 → C-5** (crackerjack review-pr needs Akosha publisher wired in `mahavishnu/factories.py:145`, which C-5 establishes)

---

## Headline picks for announcement

Per niche filter + competitive-positioning reviewer, the strongest public-facing announcement now combines (revised post-C-7-drop + C-10-simplification):

1. **C-11 (markdown board, scoped to our jot files)** — uniquely Mahavishnu-shaped (we own jot; we don't try to be a generic markdown-board engine). Pairs with Akosha pattern detection.
2. **C-8 (worktree isolation)** + **C-6 (idempotency)** — uniquely Mahavishnu; addresses documented PiPool/SessionBuddyPool pain. Stays intact through the niche filter.

Pair naturally: a markdown-board card (C-11) dispatches work with idempotency (C-6) and creates a worktree (C-8), capturing a diff. This is the feature combo no competitor has, and **none of the dropped commitments (webhook nonce sweeper, multi-secret HMAC rotation, multi-source DLQ UI) detract from it**.

**Note on what we DON'T lead with** (per niche filter):
- Webhook intake is minimal ecosystem intake only, not a feature. External systems publish to Akosha directly.
- Crackerjack review-pr integration is a Bodai synergy, not a headline; it works because Akosha is the bus, not because of fancy webhook plumbing.

Philosophical anchor: P5 — *"the routing layer is deterministic; LLM responses are allowed to vary"* — competes with Temporal's durability narrative on Mahavishnu's home turf. Adopt in `CLAUDE.md` documentation.

---

## Deferred items

These were in the original spec but are explicitly deferred to a future plan:

- **F8 multi-CLI subprocess pool** — extend `mahavishnu/terminal/adapters/` with Claude Code adapter when there's demand. Existing `crow.py`, `goose.py`, `mock.py`, `tmux.py` already cover the canonical extension surface.
- **F9 restart/rerun/retry** — depends on workflow DSL (P1) shipping first. Without typed workflow graph, `from_task_id` is undefined.
- **F10 drill-down UI** (web) — drop. C-12 `mahavishnu executions show` CLI replaces it; Akosha + Grafana drill-downs cover the rest.
- **P1 workflow graph as data** — load-bearing for F1/F9; should be its own plan.
- **P2 backend-agnostic persistence** — multi-year architecture decision, not a feature.
- **P4 PyOxidizer single binary** — contradicts MCP-first posture; track for separate packaging/distribution roadmap.
- **P5 "engine deterministic, code free to be non-deterministic"** — adopt as framing in `CLAUDE.md`; no implementation work.
- **C-7 webhook nonce sweeper** — dropped per niche filter (see Strategic niche filter above); REQ-009 removed.
- **HMAC webhook verification** — replaced by sanitization-only ecosystem intake (C-10); REQ-014 removed.
- **Multi-secret webhook rotation** — replaced by configured allowlist (C-10); REQ-015 (webhook_register MCP tool) removed.

---

**Implementation phase**: ready to begin via implementation plan docs at `docs/plans/2026-09-26-impl-C-{N}-{slug}.md` (one per kept commit).
