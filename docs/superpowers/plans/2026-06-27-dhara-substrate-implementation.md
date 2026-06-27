# Dhara Substrate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **TDD discipline is non-negotiable.** Every new module gets a failing test first, the smallest implementation that turns it green, then refactor. Use `pytest` markers `unit` and `integration` already configured in `pyproject.toml`.

**Goal:** Stand up the missing Dhara persistence/event substrate so the 10 blocked specs (6 SQL-blocked, 3 HTTP-blocked, plus migration-dependent) can run their test suites against a real (or in-memory) Dhara instance.

**Architecture:** Dhara gains two new MCP-exposed capabilities — a generic SQL proxy backed by asyncpg (or DuckDB in tests) and three HTTP CRUD routes for adapters/tenants/workflows. Migrations become first-class and runnable. Events gain a pluggable subscriber base. Mahavishnu gains a thin `dhara_client.py` proxy with `execute`/`query` that talks to the new MCP surface.

**Tech Stack:** FastMCP (Dhara), asyncpg + DuckDB (SQL proxy), Oneiric config (`DHARA__*`), Pydantic v2 models, `pytest-asyncio` (already configured), Mahavishnu thin client uses `httpx` async.

**Estimated effort:** 6–9 working days across 4 workstreams running in parallel after Workstream A unblocks B.

______________________________________________________________________

## Section 1 — Substrate Components

### 1.1 New / modified files

| Component | Path | Status | Repo |
|---|---|---|---|
| Mahavishnu thin client | `/Users/les/Projects/mahavishnu/mahavishnu/core/dhara_client.py` | **MOD** — add `execute(sql, params)` and `query(sql, params)` methods | mahavishnu |
| Dhara SQL proxy (new MCP tool module) | `/Users/les/Projects/dhara/dhara/mcp/tools/sql_proxy.py` | **NEW** | dhara |
| Dhara MCP server registration | `/Users/les/Projects/dhara/dhara/mcp/server.py` | **MOD** — register 3 new HTTP CRUD routes + import `sql_proxy` | dhara |
| Migration runner | `/Users/les/Projects/dhara/dhara/migrations/runner.py` | **NEW** | dhara |
| Initial migration | `/Users/les/Projects/dhara/dhara/migrations/sql/0001_initial.sql` | **NEW** | dhara |
| Subscriber base class | `/Users/les/Projects/dhara/dhara/events/subscribers/base.py` | **NEW** | dhara |
| Example subscriber | `/Users/les/Projects/dhara/dhara/events/subscribers/audit_log.py` | **NEW** | dhara |
| Subscriber registry | `/Users/les/Projects/dhara/dhara/events/subscribers/registry.py` | **NEW** | dhara |
| Postgres adapter (verify exists) | `/Users/les/Projects/dhara/dhara/storage/postgres.py` | **VERIFY** — already added 2026-05-25 | dhara |

### 1.2 Component responsibilities

**`mahavishnu/core/dhara_client.py` (MOD)**
- Add `execute(sql: str, params: Sequence | None = None) -> list[dict[str, Any]]`
- Add `query(sql: str, params: Sequence | None = None) -> list[dict[str, Any]]`
- Both methods POST to the Dhara MCP `sql_proxy/execute` (or `sql_proxy/query`) tool endpoint using the existing `MCPClient` already used elsewhere in the file; one `_request(tool_name, payload)` private helper.
- Keep existing adapter-discovery methods untouched. `execute` and `query` are additive.

**`dhara/mcp/tools/sql_proxy.py` (NEW)**
- Module-level `@mcp.tool()` decorated functions: `sql_proxy_execute`, `sql_proxy_query`, `sql_proxy_health`.
- Wraps a storage-agnostic `SQLBackend` protocol. Default backend: `PostgresBackend(asyncpg pool)`. Test/dev backend: `DuckDBBackend(":memory:")`.
- Backend selected via `DHARA__SQL__BACKEND` env var (`postgres` | `duckdb`). DuckDB mode is the in-memory test target — keeps pytest fast without a Postgres dependency.
- `execute` returns rowcount + statement status (for INSERT/UPDATE/DELETE). `query` returns list of dict rows.
- Parameter binding must go through backend — never string-interpolate. asyncpg uses `$1` placeholders; DuckDB uses `?`. The proxy translates via backend-specific formatter.
- Hard cap: refuse any statement whose SQL doesn't start with `SELECT`/`WITH` for `query`; `execute` allows `INSERT`/`UPDATE`/`DELETE`/`CREATE` but not `DROP DATABASE`/`DROP SCHEMA`.

**`dhara/mcp/server.py` (MOD)**
- Add three HTTP CRUD route registrations alongside existing routes:
  - `POST /adapters`, `GET /adapters/{id}`, `PUT /adapters/{id}`, `DELETE /adapters/{id}`
  - `POST /tenants`, `GET /tenants/{id}`, `PUT /tenants/{id}`, `DELETE /tenants/{id}`
  - `POST /workflows`, `GET /workflows/{id}`, `PUT /workflows/{id}`, `DELETE /workflows/{id}`
- Each route maps to a thin handler that delegates to existing `dhara.adapters.*`, `dhara.tenants.*`, `dhara.workflows.*` modules (already present per audit).
- Register the `sql_proxy` MCP tools via `from dhara.mcp.tools import sql_proxy as _sql_proxy` and explicit `mcp.add_tool(...)` calls (matches existing pattern in `dhara/mcp/server.py`).
- Auth: reuse the existing `dhara/mcp/auth.py` middleware; new routes go through it automatically because they're registered on the same FastMCP app. **Do not** add a new unauthenticated bypass.

**`dhara/migrations/runner.py` (NEW)**
- `MigrationRunner(asyncpg_pool)` discovers files in `dhara/migrations/sql/` matching `^\d{4}_.*\.sql$`, sorts lexicographically, tracks applied set in a `schema_migrations(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ)` table.
- `apply_pending()` returns list of `(version, applied_at)` rows. Idempotent.
- `status()` returns `(current_version, pending_count)`.
- Run mode callable from CLI: `python -m dhara.migrations apply` (registered in `dhara/__main__.py`).
- No DOWN migrations — only forward. Reversibility is via a new migration.

**`dhara/migrations/sql/0001_initial.sql` (NEW)**
- Creates the tables Dhara's existing modules already assume: `adapters`, `tenants`, `workflows`, `workflow_runs`, `events_outbox`, plus `schema_migrations` bookkeeping table.
- Keep IDs as `TEXT` (ULIDs), not `BIGINT` — matches existing adapter metadata layer.

**`dhara/events/subscribers/base.py` (NEW)**
- `class Subscriber(Protocol): async def handle(self, event: Event) -> None`
- `class SubscriberBase(ABC): async def handle(self, event: Event) -> None` — abstract; subclasses override.
- `Event` is a `pydantic.BaseModel` with `event_type: str`, `payload: dict[str, Any]`, `tenant_id: str | None`, `occurred_at: datetime`.

**`dhara/events/subscribers/audit_log.py` (NEW)**
- `class AuditLogSubscriber(SubscriberBase)` writes each event to `events_audit` table (added in 0001 migration). Demonstrates the pattern; kept under 80 lines.

**`dhara/events/subscribers/registry.py` (NEW)**
- `class SubscriberRegistry`: `register(name, subscriber)`, `dispatch(event)` fans out to all subscribers concurrently via `asyncio.gather`, returns when all complete or raises `ExceptionGroup` on any failure (Python 3.11+).
- Loaded at Dhara startup from `DHARA__EVENTS__SUBSCRIBERS` (comma-separated names of entry-points registered under `dhara.events.subscribers` group).

**`dhara/storage/postgres.py` (VERIFY)**
- Already exists from `2026-05-25-dhara-serverless-implementation-plan.md`. Reuse as-is for the SQL proxy `PostgresBackend`.
- **Verification step in Section 2** confirms the public surface (`acquire()`, `execute()`, `fetch()`) is sufficient.

______________________________________________________________________

## Section 2 — TDD Test Plan

Test conventions follow `mahavishnu/CLAUDE.md`: `from __future__ import annotations`, async tests don't need `@pytest.mark.asyncio` (auto mode), per-test timeout 300s, mark >10s tests `@pytest.mark.slow`, use `unit` / `integration` markers, prefer `httpx.AsyncClient` for HTTP tests, no blocking calls in async code.

### 2.1 Test fixtures

**`dhara/tests/conftest.py` (MOD if needed, NEW only if absent)** — add:

```python
@pytest.fixture
async def duckdb_pool() -> AsyncIterator[duckdb.DuckDBPyConnection]:
    """In-memory DuckDB pool for unit tests; bypasses asyncpg entirely."""
    conn = duckdb.connect(":memory:")
    yield conn
    await conn.close()

@pytest.fixture
async def sql_proxy_backend(duckdb_pool) -> SQLBackend:
    return DuckDBBackend(duckdb_pool)

@pytest.fixture
async def migration_runner(duckdb_pool) -> MigrationRunner:
    return MigrationRunner(duckdb_pool, migrations_dir=Path(__file__).parent / "fixtures" / "migrations")

@pytest.fixture
def audit_subscriber(duckdb_pool) -> AuditLogSubscriber:
    return AuditLogSubscriber(duckdb_pool)
```

### 2.2 Per-module test files

| Module | Test file | Approx. test count | Coverage focus |
|---|---|---|---|
| `mahavishnu/core/dhara_client.py` thin client | `mahavishnu/tests/unit/core/test_dhara_client.py` | **8** | `execute` happy path, `query` happy path, connection failure, MCP error surface, param forwarding, empty result, retry once on 5xx, HTTP timeout |
| `dhara/mcp/tools/sql_proxy.py` | `dhara/tests/unit/mcp/tools/test_sql_proxy.py` | **14** | backend selection via env, parameter binding for both backends, dangerous-statement guard (DROP DATABASE rejected), transaction rollback on error, connection-pool acquire failure, row mapping to dict, param-style translation `$1` ↔ `?`, empty result, large result truncation at 10k rows |
| `dhara/mcp/server.py` new HTTP routes | `dhara/tests/integration/mcp/test_http_crud_routes.py` | **12** (4 per resource) | POST creates + returns id; GET retrieves; PUT updates; DELETE removes; 404 on missing; auth required on every route; tenant isolation; workflow cascade delete |
| `dhara/migrations/runner.py` | `dhara/tests/unit/migrations/test_runner.py` | **7** | discovers files in order, applies pending only, idempotent re-run, status accuracy, missing dir error, bad filename ignored, applied_at timestamp |
| `dhara/events/subscribers/base.py` + `registry.py` + `audit_log.py` | `dhara/tests/unit/events/test_subscribers.py` | **9** | SubscriberBase enforce-abstract, registry fan-out, gather failure surfaces ExceptionGroup, AuditLogSubscriber writes row, registry empty list is no-op, duplicate registration raises, dispatch is concurrent (timing check with `@pytest.mark.slow`), subscriber timeout cancels dispatch |
| `dhara/storage/postgres.py` (VERIFY only) | `dhara/tests/unit/storage/test_postgres_storage.py` | **0 new** | Confirm existing tests pass; no new test count |

**Estimated total new tests: 8 + 14 + 12 + 7 + 9 = 50 tests.**

Test count ceiling: keep each file under the 55-statement function limit; if a test class grows past ~8 cases, split into focused classes (one per behavior group).

### 2.3 Fixtures for in-memory DuckDB mode

- `conftest.py` exposes `duckdb_pool` fixture that creates a fresh `:memory:` connection per test — no cross-test pollution.
- A second fixture `seeded_duckdb_pool` runs the same migrations the production runner would apply against Postgres, so SQL-proxy tests exercise realistic schema (tables exist, FK constraints enforced).
- For HTTP CRUD integration tests: spin up FastMCP via `httpx.AsyncClient` with `ASGITransport(app=mcp_app)` — no live socket.

### 2.4 Test ordering constraints

- `dhara_client.py` tests in mahavishnu require Workstream B's sql_proxy tools to be running in the test Dhara instance → the cross-repo tests use `mcp` profile fixtures that boot a real (in-memory) Dhara subprocess. Mark `@pytest.mark.integration` so they're excluded from `pytest -m "not slow and not integration"`.

______________________________________________________________________

## Section 3 — Worktree Strategy (4 workstreams)

Use `git worktree add` per `superpowers:using-git-worktrees`. Each workstream is one branch in one repo. **Branch names follow `feat/dhara-substrate-<workstream>-<short-slug>`** so they merge cleanly into the parent branch in dependency order.

### Workstream A — Mahavishnu thin client
- **Repo:** `/Users/les/Projects/mahavishnu`
- **Branch:** `feat/dhara-substrate-A-thin-client`
- **Base:** `main`
- **Scope:** Modify only `mahavishnu/core/dhara_client.py` and add `mahavishnu/tests/unit/core/test_dhara_client.py`. No Dhara changes.
- **Exit criteria:** All 8 tests green; `crackerjack run` passes locally; PR opened.
- **Duration:** 1 day.
- **Parallelizable with B/C/D:** Yes (touches a different repo).

### Workstream B — Dhara SQL proxy + `dhara_client` bridge
- **Repo:** `/Users/les/Projects/dhara`
- **Branch:** `feat/dhara-substrate-B-sql-proxy`
- **Base:** `main`
- **Scope:** New file `dhara/mcp/tools/sql_proxy.py`, register in `dhara/mcp/server.py` (import + `mcp.add_tool`), tests. Touches nothing else.
- **Exit criteria:** 14 tests green; `crackerjack run` passes; PR opened.
- **Duration:** 2 days.
- **Parallelizable with A/C/D:** Yes (independent file paths inside dhara).

### Workstream C — Dhara HTTP CRUD routes
- **Repo:** `/Users/les/Projects/dhara`
- **Branch:** `feat/dhara-substrate-C-http-crud`
- **Base:** `main`
- **Scope:** Add the three CRUD route sets to `dhara/mcp/server.py`, register them through the existing auth middleware, write `dhara/tests/integration/mcp/test_http_crud_routes.py`. Reuses existing `dhara.adapters.*`, `dhara.tenants.*`, `dhara.workflows.*` modules per audit.
- **Exit criteria:** 12 tests green; auth tests verify each route returns 401 without token; PR opened.
- **Duration:** 2 days.
- **Parallelizable with A/B/D:** Yes (different file region in `dhara/mcp/server.py` than B — coordinate merge order to avoid conflicts on the same server.py file: **C merges first, then B**, because C adds routes and B adds tool registrations to the same file).

### Workstream D — Dhara migration runner + events/subscribers
- **Repo:** `/Users/les/Projects/dhara`
- **Branch:** `feat/dhara-substrate-D-migrations-events`
- **Base:** `main`
- **Scope:** New directories `dhara/migrations/`, `dhara/events/subscribers/`, plus `dhara/__main__.py` registration for `python -m dhara.migrations apply`.
- **Exit criteria:** 16 tests green (7 migration + 9 subscriber); CLI smoke test `python -m dhara.migrations status` returns `pending=1` against an empty DuckDB; PR opened.
- **Duration:** 2 days.
- **Parallelizable with A/B/C:** Yes (entirely new directories — no overlap).

### Cross-repo coordination

- Workstream A produces no dependency on B/C/D being merged first; A's tests run against a `mock_dhara_mcp_server` fixture until B's branch is merged into a shared integration branch.
- The 3 dhara workstreams (B, C, D) **must merge in the order C → B → D** into `main` to avoid file-level conflicts in `dhara/mcp/server.py`. D touches no shared file with B or C, so D can merge anytime.

______________________________________________________________________

## Section 4 — Substrate-Dependency Unlock Matrix

10 blocked specs identified by audit. ID placeholders used here (`SPEC-NN`) since the original IDs live in the upstream audit doc. Replace at execution time with the real IDs from the audit report.

| Spec ID | Type | Currently blocked by | Unlocked by workstream | Notes |
|---|---|---|---|---|
| SPEC-01 | SQL-blocked | Missing `execute` in `dhara_client.py` + missing SQL proxy | **A + B** | Needs both — A adds the thin client method, B exposes the backend. Cannot test until both merge. |
| SPEC-02 | SQL-blocked | Same as SPEC-01 | **A + B** | Same. |
| SPEC-03 | SQL-blocked | Same as SPEC-01 | **A + B** | Same. |
| SPEC-04 | SQL-blocked | Same as SPEC-01 | **A + B** | Same. |
| SPEC-05 | SQL-blocked | Same as SPEC-01 | **A + B** | Same. |
| SPEC-06 | SQL-blocked | Same as SPEC-01 | **A + B** | Same. |
| SPEC-07 | HTTP-blocked | Missing `/adapters` CRUD | **C** | Standalone — needs only C merged. |
| SPEC-08 | HTTP-blocked | Missing `/tenants` CRUD | **C** | Standalone. |
| SPEC-09 | HTTP-blocked | Missing `/workflows` CRUD | **C** | Standalone. |
| SPEC-10 | Schema-blocked | No migration runner, no schema for events_outbox | **D** | SPEC-10 tests the event subscriber pipeline end-to-end and requires the `events_outbox` table from migration 0001. Unblocked only after D merges. |

**None yet:** none. Every spec has a clear unblocker once the relevant workstream merges.

### Unblock summary by workstream

```
A: SPEC-01, SPEC-02, SPEC-03, SPEC-04, SPEC-05, SPEC-06  (jointly with B)
B: SPEC-01, SPEC-02, SPEC-03, SPEC-04, SPEC-05, SPEC-06  (jointly with A)
C: SPEC-07, SPEC-08, SPEC-09
D: SPEC-10
```

### Specs unblocked only after BOTH A and B merge

Specs 01–06 require the round-trip Mahavishnu → Dhara → SQL backend to work. Without A, Mahavishnu can't talk. Without B, Dhara can't execute SQL. Therefore these six specs only flip from blocked → unblocked once both branches are merged into `main` **and** the dhara_client integration test fixture (mocking the MCP layer) is replaced with a live-test against a running Dhara.

______________________________________________________________________

## Section 5 — Risk Register (top 3)

### Risk 1 — asyncpg ↔ DuckDB API divergence

**Scenario:** SQL proxy uses different parameter binding syntax per backend (`$1` vs `?`) and different result shapes (`asyncpg.Record` vs `duckdb.DuckDBPyRow`). The translator may silently miscount parameters or mis-map types.

**Likelihood:** High — these APIs are genuinely different and the test surface for parameter translation is exactly the kind of thing that passes locally and breaks in CI with a different Python or asyncpg version.

**Mitigation in plan:**
- The SQL proxy defines a `SQLBackend` Protocol with `execute(query, params)` and `fetch(query, params)`. Translators are isolated to backend implementations; tests cover **both backends** with the same fixture data.
- A cross-backend property test (`pytest.mark.property`) runs the same INSERT/SELECT against both backends and asserts identical row outputs.
- Crackerjack `crackerjack run` includes the new tests; if the property test is flaky, pin to specific asyncpg/DuckDB versions in `pyproject.toml`.

### Risk 2 — Auth bypass on new HTTP CRUD routes

**Scenario:** Adding routes to `dhara/mcp/server.py` requires re-running them through the `auth.py` middleware. If a route is registered before the middleware wraps the FastMCP app (or via a code path that skips the wrapper), it could be reachable without a token. The 2026-05-25 serverless plan changed auth wiring; new routes might inherit the new wrapper or miss it depending on registration order.

**Likelihood:** Medium — registration order is exactly the kind of thing a code reviewer misses on a fast PR.

**Mitigation in plan:**
- One of the 12 integration tests for Workstream C is parametrized over every new route + a missing/expired/invalid token. All three cases must return 401.
- Add a smoke test that boots the full FastMCP app and asserts every registered route (collectible from the app's router) is wrapped by the auth middleware.
- The integration test fixture spins up the real FastMCP app — no mocked middleware.

### Risk 3 — Migration ordering & idempotency

**Scenario:** `MigrationRunner` discovers files alphabetically. A developer adds `0010_add_index.sql` before `0002_*.sql` exists, or renames `0001_initial.sql` to `0001_v2_initial.sql`, breaking the applied-set lookup. Also: a partial migration failure leaves the `schema_migrations` row unwritten but the schema partially applied, so the next run thinks 0001 is unapplied and tries to re-run it.

**Likelihood:** Medium — migration tooling is famously where teams lose weekends.

**Mitigation in plan:**
- The runner wraps each migration in a single transaction (`BEGIN ... COMMIT`); on error, `ROLLBACK` and the `schema_migrations` row is never written. Tests cover the partial-failure case with a deliberately failing 0002 migration.
- The runner refuses to apply a migration whose `version` already exists with a different checksum (defends against rename-after-apply). Test exists.
- File naming is enforced by the discovery regex (`^\d{4}_.*\.sql$`); files outside that pattern are ignored with a warning. Test exists for `README.sql` being ignored.
- The initial migration uses `CREATE TABLE IF NOT EXISTS` for safety even though the runner is idempotent at the version level.

### Honorable-mention risks (not in top 3, but tracked)

- Subscriber `ExceptionGroup` semantics in Python 3.11+ — Python 3.13 is the target per `CLAUDE.md`, so this is fine, but document it.
- `dhara_client.py` retry-on-5xx: needs an upper bound to avoid infinite loops; cap at 3 attempts with exponential backoff.
- `duckdb` is synchronous — wrapping it in async requires care (use `asyncio.to_thread`); the SQL proxy must not block the event loop on a long-running query. Add a query timeout fixture.

______________________________________________________________________

## Section 6 — Execution Order & Dispatch

1. **Day 0:** Create the 4 worktree branches from `main`. Verify all 4 trees build cleanly.
2. **Day 1–2:** Dispatch Workstreams A, C, D in parallel (no shared files). Workstream B starts after A's contract for `dhara_client.execute/query` is settled (Day 0.5) so B's mock-server fixture matches A's real request shape.
3. **Day 2:** Merge C (HTTP CRUD) into `main` first to free up `dhara/mcp/server.py` for B's edits.
4. **Day 3:** Merge B (SQL proxy) into `main`. A's integration test fixture swaps from mock → live Dhara.
5. **Day 3:** Merge D (migrations + events) — independent file paths, no ordering constraint with A/B/C.
6. **Day 4:** Merge A (thin client) into `main`. Now all 10 specs are unblocked.
7. **Day 4–6:** Spec authors pick up the 10 unblocked specs. Each spec is its own worktree; dispatch as parallel agents per `superpowers:dispatching-parallel-agents`.

### Recommended dispatch order (one string array)

```python
recommended_dispatch_order = [
    "Workstream A — mahavishnu thin client",          # 1 day, isolated repo
    "Workstream C — dhara HTTP CRUD routes",          # 2 days, merges first
    "Workstream D — dhara migrations + events",       # 2 days, independent dirs
    "Workstream B — dhara SQL proxy",                 # 2 days, after C merges
    "Merge gate: all 4 workstreams on main",          # critical for spec unblock
    "Specs 07-09 (HTTP CRUD consumers)",              # only need C
    "Specs 01-06 (SQL consumers)",                    # need A+B merged
    "Spec 10 (events subscriber e2e)",                 # needs D
]
```

______________________________________________________________________

## Appendix A — Why no production code in this plan

This plan intentionally contains zero implementation code. The next phase (per `superpowers:executing-plans`) opens each workstream as its own worktree, writes the failing test first, then implements the smallest change that turns it green. The test files in Section 2 are sketches only — they become real code in the respective worktree sessions.

## Appendix B — Spec ID resolution

The 10 blocked spec IDs (`SPEC-01` through `SPEC-10`) are placeholders. Before dispatching Workstream A, locate the actual IDs in the upstream audit document and replace each occurrence in Section 4. Do not start any workstream with placeholder IDs still in place.

## Appendix C — Crackerjack gate expectations

Each workstream's exit criteria include `crackerjack run` passing locally. This means:
- Ruff passes (max-args 10, max-branches 15, max-returns 6, line-length 100).
- Mypy strict passes (no `Any` in tool inputs, no `Optional[X]`).
- Pyright strict passes.
- Bandit B101 clean (no asserts in production code under `dhara/`).
- pytest with `--cov-fail-under=80` passes for the new code paths.

If a workstream's `crackerjack run` blocks on a pre-existing issue unrelated to the new code, file a tracking issue and proceed with a focused pytest run for the new tests; do not let unrelated debt block the substrate work.