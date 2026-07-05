# Dhara Substrate Extension Plan

**Status:** Drafted 2026-06-26, post-8-agent audit
**Owner:** TBD (no plan currently owns this work — it's the orphaned infrastructure between all open plans)
**Supersedes/extends:** [`docs/superpowers/plans/2026-05-25-dhara-serverless-implementation-plan.md`](./2026-05-25-dhara-serverless-implementation-plan.md)
**Trigger:** HANDOFF.md "Audit Findings (2026-06-26)" section, items #1, #2, #3.

## Goal

Expose the SQL `execute()` / `query()` surface and HTTP CRUD routes that the 2026-06-22 batch of 10 specs (Phase 3 in particular) assume. Today the Dhara surface is key-value/object only (`put` / `get` / `call_tool` / `list_prefix` / `query_time_series`) — five Phase 1/2 specs and four Phase 3 specs import `from mahavishnu.core.dhara_client import execute, query`, and the HTTP CRUD routes `/adapters/<id>/active-settings-version`, `/tenants/<id>/context-versions`, `/workflows/<id>/progress-snapshots` do not exist.

The 2026-05-25 serverless plan added `PostgresStorageAdapter` (asyncpg) + `RedisCacheAdapter` with SQL migrations for `dhara_objects` + `dhara_dirty_oids`, but **does NOT expose the SQL `execute()` / `query()` surface** or HTTP routes the new specs require.

## Architecture

Two new Dhara-side surfaces, plus a migration runner:

### A. SQL proxy layer (MCP tools)

Thin MCP tools proxying to the asyncpg pool already provided by `PostgresStorageAdapter` in `dhara/storage/postgres.py`. These expose `asyncpg.Connection.execute` and `asyncpg.Connection.fetch` to Mahavishnu callers.

**Why MCP tools and not a Python module:** the spec/plan codebase uses `from mahavishnu.core.dhara_client import execute, query` — that module is absent. The MCP tool path is the only authenticated way to expose the asyncpg pool without leaking the DSN into Mahavishnu's process memory.

**Surface:**

```
dhara_sql_execute(sql: str, params: list | None = None) -> int
  Returns rowcount. Auth required: write.

dhara_sql_query(sql: str, params: list | None = None) -> list[dict]
  Returns rows as list of dicts. Auth required: read.

dhara_apply_migration(name: str, sql: str) -> bool
  Applies a named migration from mahavishnu/core/dhara_migrations/{name}.sql.
  Records applied migrations in `dhara_migrations_applied` table. Idempotent.
  Refuses re-apply of a migration whose name has already been recorded.
```

### B. HTTP CRUD routes (per-resource)

New endpoints in the Dhara HTTP MCP server (currently absent):

```
# Adapter (Spec #8)
GET    /adapters/<id>/active-settings-version   → { version: int, set_at: ts }
POST   /adapters/<id>/active-settings-version   → activates a version
                                                    (deactivates previous via partial unique index)
GET    /adapters/<id>/lifecycle-events          → list of { event_type, ts, payload }
POST   /adapters/<id>/lifecycle-events          → emits a new lifecycle event
GET    /adapters/<id>/metrics                   → { ...adapter performance metrics... }

# Tenant (Spec #9)
GET    /tenants/<tenant_id>/active-context-version  → { version: int }
POST   /tenants/<tenant_id>/active-context-version  → activates a version
GET    /tenants/<tenant_id>/context-versions        → list
GET    /tenants/<tenant_id>/context-versions/<vid>/files → { ... }
POST   /tenants/<tenant_id>/context-versions        → creates a new version

# Workflow (Spec #10)
GET    /workflows/<id>/progress-snapshots   → list
POST   /workflows/<id>/progress-snapshots   → emits a new snapshot
GET    /workflows?status=running            → filter (returns list)
GET    /workflows/<id>/events               → list
```

**Partial unique indexes** enforce single-active-version semantics per resource (e.g. `(adapter_id) WHERE active=true` on `adapter_settings_versions`).

### C. Migration runner

`mahavishnu/core/dhara_migrations/{name}.sql` files run via `dhara_apply_migration` at app startup. Migration order recorded in `dhara_migrations_applied` table. Idempotent on re-apply.

## Tables to add (via migrations)

| Table | Spec / Plan | Notes |
|---|---|---|
| `dhara_migrations_applied` | this plan | name (PK), applied_at |
| `iteration_reports` | Spec #1 | workflow_id, iteration_index, payload_json, recorded_at; PK (workflow_id, iteration_index) |
| `workflow_reports` | Spec #1 | workflow_id (PK), payload_json, recorded_at |
| `skill_transitions` | Spec #5 | skill_name, transition_type, transition_at, actor, evidence_count; 2 indexes |
| `case_retrospectives` | Spec #7 | case_id (PK), recorded_at, payload_json, adjacent_problems; 2 indexes |
| `adapter_settings_versions` | Spec #8 | adapter_id, version, settings_json, activated_at, active bool; partial unique index on `(adapter_id) WHERE active=true` |
| `adapter_lifecycle_events` | Spec #8 | adapter_id, event_type, ts, payload_json |
| `adapter_performance_metrics` | Spec #8 | adapter_id, ts, metric_name, value |
| `tenant_context_versions` | Spec #9 | tenant_id, version, created_at; partial unique index on `(tenant_id) WHERE active=true` |
| `tenant_context_files` | Spec #9 | tenant_id, version, file_path, content |
| `workflow_progress_snapshots` | Spec #10 | workflow_id, ts, status, progress_json |
| `workflow_events` | Spec #10 | workflow_id, ts, event_type, payload_json |

Total: **12 new tables, ~20 indexes** (counting partial uniques).

## Phases

### Phase S1 — SQL proxy + migration runner (3–5 days)

1. **Day 1** — Add `dhara_migrations_applied` table + `dhara_apply_migration` MCP tool. Idempotency tests; partial-migration rollback on failure.
1. **Day 2** — Add `dhara_sql_execute` and `dhara_sql_query` MCP tools. Auth gates (`read`/`write`). Error class `DharaSQLError` that does **NOT** echo the DSN. Stress test: 1000 sequential execute() calls.
1. **Day 3** — Add `mahavishnu/core/dhara_client.py` thin wrapper that calls the new MCP tools. Mirrors what the specs import (`execute`, `query`). Add unit tests.
1. **Day 4** — Add `mahavishnu/core/dhara_migrations/` directory + first 4 migrations (`iteration_reports`, `workflow_reports`, `skill_transitions`, `case_retrospectives`). Each migration runs idempotently.
1. **Day 5** — Integration tests against real Postgres (Neon or local). Verify Spec #1, #5, #7 import paths work end-to-end.

### Phase S2 — HTTP CRUD server (3–4 days)

1. **Day 6** — Add 3 adapter routes (`/adapters/<id>/active-settings-version`, `/lifecycle-events`, `/metrics`). Partial unique index on `adapter_settings_versions (adapter_id) WHERE active=true`. Auth gate per route.
1. **Day 7** — Add 3 tenant routes (`/tenants/<id>/active-context-version`, `/context-versions`, `/context-versions/<vid>/files`). Partial unique index.
1. **Day 8** — Add 3 workflow routes (`/workflows/<id>/progress-snapshots`, `/workflows?status=running`, `/workflows/<id>/events`). Pagination + filter support.
1. **Day 9** — Migration DDL for 6 tables (`adapter_settings_versions`, `adapter_lifecycle_events`, `adapter_performance_metrics`, `tenant_context_versions`, `tenant_context_files`, `workflow_progress_snapshots`, `workflow_events`). Integration tests for Specs #8, #9, #10 import paths.

**Total: ~9 days.**

## Critical files

**New:**

- `mahavishnu/core/dhara_client.py` — thin wrapper exposing `execute`, `query`
- `mahavishnu/core/dhara_migrations/` — SQL migration directory
- `mahavishnu/core/dhara_migrations/0001_dhara_migrations_applied.sql`
- `mahavishnu/core/dhara_migrations/0002_iteration_reports.sql`
- `mahavishnu/core/dhara_migrations/0003_workflow_reports.sql`
- `mahavishnu/core/dhara_migrations/0004_skill_transitions.sql`
- `mahavishnu/core/dhara_migrations/0005_case_retrospectives.sql`
- `mahavishnu/core/dhara_migrations/0006_adapter_runtime.sql`
- `mahavishnu/core/dhara_migrations/0007_tenant_context.sql`
- `mahavishnu/core/dhara_migrations/0008_workflow_progress.sql`
- `mahavishnu/core/events/subscribers/__init__.py`
- `mahavishnu/core/events/subscribers/report_persister.py` — Spec #1 subscriber

**Modified:**

- `dhara/mcp/server_core.py` — add `dhara_sql_execute`, `dhara_sql_query`, `dhara_apply_migration` MCP tools + HTTP CRUD route handlers
- `dhara/storage/postgres.py` — expose asyncpg pool to the SQL proxy layer
- `mahavishnu/core/app.py` — bootstrap the migration runner at startup
- `settings/mahavishnu.yaml` — add `dhara_sql_proxy_enabled: true` config flag

## Acceptance criteria

- All 12 tables created via migrations; idempotent on re-apply.
- `from mahavishnu.core.dhara_client import execute, query` works end-to-end against a real Postgres backend.
- All 9 HTTP CRUD routes respond 200 for valid input, 4xx for invalid, 5xx only on backend failure.
- Auth gates enforced (unauthenticated calls rejected).
- DSN never appears in any error message or log line.
- Integration tests pass against Neon Postgres + DuckDB fallback.
- No regression in existing Dhara MCP tool surface (`put`, `get`, `list_prefix`, etc.).

## What this plan does NOT do

- **Plan 4 (Oneiric Adapter Config Telemetry)** — separate work. This plan only provides the substrate; Plan 4's `TrackedSettings` wrapper, debouncing, and Akosha indexing are out of scope.
- **Plan 5 (Distilled Workflows)** — separate work. This plan provides substrate that Plan 5 indirectly benefits from but does not fix Plan 5's trust model issues (source-contamination loop, LLM cap bypass, reviewer identity).
- **Phase 3 spec implementations themselves** — those come after this plan ships.
- **Plan 4 ↔ Spec #8 reconciliation** — out of scope; should happen before either ships the adapter observability surface.

## Open questions

1. **Where to put SQL proxy code:** option (a) inside `dhara/mcp/server_core.py`, option (b) new module `dhara/mcp/sql_proxy.py`. Plan 1's Bodai Crow server splits server wiring into a separate module — should we follow that pattern? **Recommend (a) for now**; refactor later if it grows.
1. **HTTP CRUD auth model:** same as existing Dhara HTTP MCP server (which today has no auth — out of scope here). **Recommend adding auth in a follow-up plan.**
1. **Migration rollback strategy:** spec assumes forward-only migrations. **Recommend:** add `dhara_rollback_migration` for emergencies, gated to operator-only.
1. **Where to host HTTP CRUD routes:** Dhara's main HTTP MCP server (port 8683) or new server (e.g. 8684)? **Recommend main server for now** to avoid splitting Dhara into two services.

## Estimated effort

- Phase S1 (SQL proxy + migration runner): **3–5 days**
- Phase S2 (HTTP CRUD server): **3–4 days**
- **Total: 6–9 days**, not the 1–2 days the prior HANDOFF estimated.

This estimate was revised upward by the 2026-06-26 audit (substrate feasibility dimension) from the original 1–2 days. The original estimate did not account for:

- (a) MCP tool registration with auth/profile gates
- (b) Migration runner DDL + idempotency tests
- (c) Integration tests against real Postgres
- (d) DSN redaction in error messages
- (e) Stress testing (1000 sequential calls)
- (f) Auth gates on the HTTP CRUD routes
