---
status: draft
role: implementation
kind: plan
date: 2026-09-27
last_reviewed: 2026-09-27
topic: shared-oneiric-substrate-phase-b
---

# Phase B: SB Warm Tier = pgvector — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace Session-Buddy's DuckDB VSS warm-tier with `oneiric.adapters.vector.pgvector.PgvectorAdapter` (shared Postgres database, `sb.*` schema namespace).

**Architecture:** Wrap `PgvectorAdapter` with `SBWarmStore`; one-shot migration script exports `reflection.duckdb` → Parquet → pgvector (`sb.reflections` table), verifies count + `numpy.allclose(atol=1e-5)`. Freeze window on SB `/health` during migration. Akosha already on pgvector since 2026-09-27 (`akosha/storage/pgvector_warm_store.py:150`).

**Tech Stack:** Python 3.14, pgvector, `oneiric.adapters.vector.pgvector`, Parquet via pyarrow, numpy.

**Spec:** `docs/specs/2026-09-27-shared-bodai-substrate-design.md` §6.2, §6.7 (Phase B1+B2).

## Global Constraints

Verbatim from spec §12:

- **Pre-1.0 replace, not deprecate** — DuckDB VSS config knobs (`hnsw_m`, `hnsw_ef_construction`, `hnsw_ef_search`, `enable_quantization`) removed in same commit.
- **Direct merge to main, no PRs** (`bodai-pre-1.0-merge-policy.md`).
- **No `git push`** for bodai without explicit approval (`feedback-bodai-push-is-user-controlled.md`).
- **No version bumps** in any Bodai `pyproject.toml` — user does.
- **No `Co-Authored-By` trailer**.
- **Wire-up contract** per `.claude/decisions/wire-up-contract.md`.

## 1. Outcome

- SB writes and reads embeddings via pgvector (`sb.reflections` table in shared Postgres).
- 461 MB `session_buddy/storage/reflection.duckdb` becomes cold-tier archive (kept 90 days for recovery).
- `session_buddy/storage/cloud_sync.py` S3-only legacy surface remains until Phase C (NOT deleted here).
- `grep -rn "duckdb.*reflection\|reflection.duckdb" session_buddy/storage/ session_buddy/adapters/reflection_adapter_oneiric.py` returns zero hits.
- Akosha can read `sb.reflections` only via explicit `cross_namespace_grant` (ACL test).

## 2. Goals

1. SB warm tier uses `oneiric.adapters.vector.pgvector.PgvectorAdapter` with namespace `sb`.
2. Migration script ports ~all existing SB reflections from DuckDB to pgvector; count + embedding equality verified.
3. SB exposes freeze-window state in `/health` (`state=migrating` → 503).
4. Cross-namespace search raises `PermissionError` by default; explicit grant required.
5. Akosha search code keeps working (no cross-component changes required for Akosha in Phase B; consolidation only via existing pgvector warm store).

## 3. Non-Goals

- No Mahavishnu OTel change (`HotStore` adopted per ADR 017).
- No cold-tier change (Phase C).
- No embedding change (Phase D).
- No settings layer (Phase E1).
- No DuckDB → pgvector zero-downtime; freeze window is required (audit finding 7).

## 4. Current Findings

- **SB DuckDB VSS implementation**: `session_buddy/adapters/reflection_adapter_oneiric.py:1049-1134`. Settings: `session_buddy/adapters/settings.py:24-52` (`enable_hnsw_index`, `hnsw_m=16`, `hnsw_ef_construction=200`, `hnsw_ef_search=64`, `enable_quantization`, `quantization_method="scalar"`).
- **Database path**: `session_buddy/storage/reflection.duckdb` (~461 MB).
- **PgvectorAdapter exists**: `oneiric/adapters/vector/pgvector.py` (class `PgvectorAdapter`).
- **Akosha already on pgvector**: `akosha/storage/pgvector_warm_store.py:150`, settings `akosha/config.py:110-141` (`WarmStorageConfig`).
- **Migrations are runtime CREATE TABLE blocks** (NOT migration scripts): `session_buddy/storage/migrations/V1__V6__*.sql` are about `initial_schema`, `add_semantic_search`, `add_workflow_correlation`, `phase4_extensions`, `ulid_migration`, `ulid_contract` — **none** are about `query_cache_l2`.
- **No `akosha/storage/migrations/` directory** — Phase B has no Akosha DB-migration work.

## 5. Requirements

```yaml
requirements:
  - id: REQ-OSUB-B-001
    title: "SBWarmStore wraps PgvectorAdapter with namespace=sb"
    dep: "SB → oneiric (PgvectorAdapter)"
  - id: REQ-OSUB-B-002
    title: "Migration script DuckDB → pgvector verifies count + numpy.allclose(atol=1e-5)"
    dep: "SB → oneiric (PgvectorAdapter); migration script → SB storage"
  - id: REQ-OSUB-B-003
    title: "SB /health returns 503 with state=migrating during freeze window"
    dep: "SB mcp server → SB warm store; freeze is in-process flag"
  - id: REQ-OSUB-B-004
    title: "Cross-namespace ACL denies sb.* reads from akosha.* processes without explicit grant"
    dep: "Akosha → oneiric (PgvectorAdapter ACL); SB → oneiric (PgvectorAdapter ACL)"
  - id: REQ-OSUB-B-005
    title: "SB p99 quick_search read latency ≤ 10ms from local pgvector"
    dep: "SB → oneiric (PgvectorAdapter)"
  - id: REQ-OSUB-B-006
    title: "Delete DuckDB VSS HNSW knobs from session_buddy/adapters/settings.py"
    dep: "SB → oneiric (PgvectorAdapter); deletes duckdb internals"
  - id: REQ-OSUB-B-007
    title: "Delete legacy DuckDB SQL migrations V1–V6 after 90-day archive window"
    dep: "SB (deletes its own migrations); gated on DuckDB cold archive"
```

## 6. Implementation Tasks

### Task 1: SBWarmStore wraps PgvectorAdapter (warm-write/read path)

**Files:**
- Create: `session_buddy/storage/pgvector.py`
- Modify: `session_buddy/adapters/reflection_adapter_oneiric.py` (switch warm tier from DuckDB to `SBWarmStore`)

#### Integration Contract ← REQUIRED

- **Triggered from**: First `mcp__session-buddy__store_reflection` call after SB restart (warm write); first `mcp__session-buddy__quick_search` call (warm read).
- **Returns to**: SB reflections persist in `sb.reflections` table (pgvector, shared Postgres, namespace `sb`).
- **Demonstrable by**: `python -c "import session_buddy.adapters.reflection_adapter_oneiric as r; print(r.SCHEMA_VERSION)"` prints `"pgvector_v1"`; `SELECT count(*) FROM sb.reflections` matches pre-migration count.
- **Rollback signal**: p99 `quick_search` latency > 200ms; pgvector connection error rate > 1% over 5 minutes.
- **Observability added**: OTel span `warm.pgvector.upsert/search` with `namespace`, `entities_count`, `latency_ms` attributes.

- [ ] **Step 1: Write failing test for SBWarmStore round-trip**

```python
# session_buddy/tests/integration/test_sb_warm_pgvector.py
import numpy as np
from session_buddy.storage.pgvector import SBWarmStore

def test_sb_warm_store_upsert_and_search_round_trip():
    ws = SBWarmStore(namespace="sb", pg_url="postgresql://localhost:5432/oneiric_substrate_test")
    vec = np.random.rand(384).astype(np.float32)
    ws.upsert(reflection_id="r1", embedding=vec, metadata={"text": "hello"})
    results = ws.search(embedding=vec, top_k=5)
    assert any(r["reflection_id"] == "r1" for r in results)
```

- [ ] **Step 2: Run, expect failure** — `SBWarmStore` does not exist yet.

- [ ] **Step 3: Implement SBWarmStore** — wraps `PgvectorAdapter` with `namespace="sb"`, exposes `upsert(reflection_id, embedding, metadata)` and `search(embedding, top_k)` plus `count()`.

- [ ] **Step 4: Re-run, expect pass** (requires local pgvector running; use existing `akosha/dev/docker-compose.yml` stack — verify URL set in env).

- [ ] **Step 5: Switch `reflection_adapter_oneiric.py` warm-tier initialization to `SBWarmStore`** — replace any `import duckdb` or `VSSIndex` references at the warm-write hot path.

- [ ] **Step 6: Re-run migration E2E test (later in Task 3), verify integration**.

- [ ] **Step 7: Commit**:

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/storage/pgvector.py session_buddy/adapters/reflection_adapter_oneiric.py session_buddy/tests/integration/test_sb_warm_pgvector.py
git commit -m "feat(session-buddy): warm tier via PgvectorAdapter"
```

### Task 2: Delete DuckDB VSS HNSW config knobs (settings cleanup)

**Files:**
- Modify: `session_buddy/adapters/settings.py:24-52`

#### Integration Contract ← REQUIRED (v5 addition)

- **Triggered from**: SB restart after Task 1 lands; the unused knobs become dead-on-arrival.
- **Returns to**: `session_buddy/adapters/settings.py` no longer carries HNSW/DuckDB VSS knobs; `ReflectionAdapterSettings` shrinks to only pgvector-relevant fields.
- **Demonstrable by**: `grep -rn "hnsw_m\|hnsw_ef_construction\|hnsw_ef_search\|enable_quantization" session_buddy/` returns zero hits.
- **Rollback signal**: SB settings loader raises `ValidationError` on field removal (revert to keep both).
- **Observability added**: count of `ReflectionAdapterSettings` fields logged at startup via `oneiric.logging` (drift detection).

- [ ] **Step 1: Verify knobs are no longer read** — `grep -rn "hnsw_m\|hnsw_ef_construction\|hnsw_ef_search\|enable_quantization" session_buddy/` after Task 1 lands → expect zero hits in code (only in `settings.py` itself).

- [ ] **Step 2: Delete the HNSW knobs** — `enable_hnsw_index`, `hnsw_m`, `hnsw_ef_construction`, `hnsw_ef_search`, `enable_quantization`, `quantization_method`, `quantization_accuracy_threshold`.

- [ ] **Step 3: Commit** (separate from Task 1 for clean rollback):

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/adapters/settings.py
git commit -m "refactor(session-buddy): remove obsolete DuckDB VSS HNSW knobs"
```

### Task 3: Migration script — DuckDB → Parquet → pgvector

**Files:**
- Create: `scripts/migrate_sb_reflection_duckdb_to_pgvector.py` (one-shot)

#### Integration Contract

- **Triggered from**: Operator runs `python scripts/migrate_sb_reflection_duckdb_to_pgvector.py` during a controlled freeze window.
- **Returns to**: pgvector `sb.reflections` table populated; `reflection.duckdb` left in place as cold archive.
- **Demonstrable by**: `pytest tests/integration/test_sb_migrated_from_duckdb.py -v` PASS (count + `numpy.allclose(atol=1e-5)` match).
- **Rollback signal**: numpy.allclose mismatch on any record → script aborts before commit; SB falls back to DuckDB read-only mode.
- **Observability added**: log lines per batch: `migrated batch i/N, count_so_far=X, embeddings_equal=Y`.

- [ ] **Step 1: Write the migration integration test first**:

```python
# tests/integration/test_sb_migrated_from_duckdb.py
def test_migration_script_count_and_embedding_equality():
    """Round-trip a DuckDB fixture through the script and assert pgvector matches."""
    # Fixture: spin up temporary DuckDB with 100 seeded reflections.
    # Run script against fixture.
    # Compare counts + per-embedding distance via numpy.allclose.
    ...
```

- [ ] **Step 2: Run, expect failure** (script doesn't exist).

- [ ] **Step 3: Implement the script**:
  - Read `~/.claude/data/reflection.duckdb` (or `data_dir / "reflection.duckdb"` per SB settings).
  - Export to Parquet intermediate (`reflection-export-<timestamp>.parquet`).
  - Ingest batch-wise (default batch=1000) into pgvector `sb.reflections`.
  - After each batch: re-read both stores, count match + per-row `numpy.allclose(atol=1e-5)` check.
  - On mismatch: abort, log mismatched ids, leave DuckDB intact.

- [ ] **Step 4: Run script against test fixture (Task 3 test now passes)**.

- [ ] **Step 5: Document the freeze window** in operator runbook — `docs/session-buddy/operations/migrate-to-pgvector.md` (new file).

- [ ] **Step 6: Commit**:

```bash
cd /Users/les/Projects/mahavishnu
git add scripts/migrate_sb_reflection_duckdb_to_pgvector.py tests/integration/test_sb_migrated_from_duckdb.py docs/session-buddy/operations/migrate-to-pgvector.md
git commit -m "feat(session-buddy): DuckDB to pgvector migration script"
```

### Task 4: Freeze window mechanism on SB `/health`

**Files:**
- Modify: `session_buddy/mcp/server.py` (or wherever `/health` aggregates; check via `grep -rn "/health" session_buddy/mcp/`)

#### Integration Contract ← REQUIRED (v5 addition; also documents freeze ↔ migration sequencing per spec §6.7)

- **Triggered from**: Operator sets `SB_MIGRATION_IN_PROGRESS=1` (or `/tmp/sb_migration_in_progress` flag) before running the Task 3 migration script. **Sequencing** (per spec §6.7): Task 4 must land and the operator must signal freeze BEFORE Task 3 runs; otherwise writes accumulate on both backends and the count + `numpy.allclose` equality check cannot verify. Document this in `docs/session-buddy/operations/migrate-to-pgvector.md` (created in Task 3).
- **Returns to**: SB `/health` returns 503 with `{"status": "degraded", "state": "migrating", "feeds": {...}}` while freeze is active; clients/pool routers reject writes.
- **Demonstrable by**: `pytest ... -v` asserts 503 when freeze is signaled.
- **Rollback signal**: `SB_MIGRATION_IN_PROGRESS` flag stale for > 1 hour (operator forgot to clear) → 503 stuck → operator clears flag, `/health` returns 200.
- **Observability added**: OTel span `health.freeze_window.active` with `actor`, `since_ts`; log line on entry/exit.

- [ ] **Step 1: Identify current `/health` shape**.

- [ ] **Step 2: Add freeze window state** — when an operator signals "freeze" (env var `SB_MIGRATION_IN_PROGRESS=1` or file flag `/tmp/sb_migration_in_progress`), `/health` returns 503 with `{"status": "degraded", "state": "migrating", "feeds": {...}}`.

- [ ] **Step 3: Test**:

```python
def test_health_503_during_migration_freeze(monkeypatch, sb_health_callable):
    monkeypatch.setenv("SB_MIGRATION_IN_PROGRESS", "1")
    assert sb_health_callable().status_code == 503
```

- [ ] **Step 4: Commit**.

### Task 5: Cross-namespace ACL test (REQ-OSUB-B-004)

**Files:**
- Create: `tests/integration/test_cross_namespace_acl_sb.py`
- Create: `akosha/tests/integration/test_akosha_searches_sb_namespace.py` (v5 addition — positive cross-namespace path required by spec §6.2)

#### Integration Contract ← REQUIRED (v5 addition; also covers Observability)

- **Triggered from**: CI gate on every PR touching `oneiric/adapters/vector/pgvector.py` or akosha search paths.
- **Returns to**: `tests/integration/test_cross_namespace_acl_sb.py` asserts negative path (default-deny); `akosha/tests/integration/test_akosha_searches_sb_namespace.py` asserts positive path (admin-granted read of `sb.reflections`).
- **Demonstrable by**: `pytest tests/integration/test_cross_namespace_acl_sb.py akosha/tests/integration/test_akosha_searches_sb_namespace.py -v` PASS.
- **Rollback signal**: ACL raises on legitimate reads (false positive) OR returns silently on denied reads (false negative — `tests/integration/test_cross_namespace_acl_sb.py` catches false negative).
- **Observability added**: OTel span `warm.pgvector.acl.assert` with `caller_namespace`, `target_namespace`, `decision=allow|deny` per `mcp-backend-wiring-discipline.md §3`.

- [ ] **Step 1: Write the negative test**:

```python
def test_akosha_namespace_cannot_read_sb_namespace_by_default():
    """Per spec §6.2 — cross-namespace search raises PermissionError without grant."""
    from oneiric.adapters.vector.pgvector import PgvectorAdapter
    adapter = PgvectorAdapter(namespace="akosha", pg_url="...")
    with pytest.raises(PermissionError):
        adapter.search(embedding=[0.0]*384, top_k=5, namespace="sb")
```

- [ ] **Step 1b: Write the positive cross-namespace test** in `akosha/tests/integration/test_akosha_searches_sb_namespace.py`:

```python
def test_akosha_granted_admin_reads_sb_namespace():
    """Per spec §6.2 — admin grant permits Akosha caller to read sb.*  reflections."""
    from oneiric.adapters.vector.pgvector import PgvectorAdapter
    adapter = PgvectorAdapter(
        namespace="akosha", pg_url="...",
        cross_namespace_grant=True,
    )
    results = adapter.search(embedding=[0.0]*384, top_k=5, namespace="sb")
    # Successful cross-namespace read returns rows; assertion is non-empty + log entries.
    assert isinstance(results, list)
```

- [ ] **Step 2: Verify permission logic exists in `PgvectorAdapter`** — `oneiric/adapters/vector/pgvector.py` already namespaced? If not, add `assert_caller_namespace_allowed(target_namespace)` method (skeleton acceptable — full implementation lives in Phase C; this test pins the API).

- [ ] **Step 3: Run, expect pass** with explicit `cross_namespace_grant=True` test variant.

- [ ] **Step 4: Commit**.

### Task 6: Delete legacy DuckDB SQL migrations V1–V6 after archive window

**Files:**
- Delete: `session_buddy/storage/migrations/V1__initial_schema.sql`
- Delete: `session_buddy/storage/migrations/V2__add_semantic_search.sql`
- Delete: `session_buddy/storage/migrations/V3__add_workflow_correlation.sql`
- Delete: `session_buddy/storage/migrations/V4__phase4_extensions.sql`
- Delete: `session_buddy/storage/migrations/V5__ulid_migration.sql`
- Delete: `session_buddy/storage/migrations/V6__ulid_contract.sql`

**v5 addition (per spec §6.2 "Files (delete after migration verified + 90-day cold-tier archive window)")**: tasks were absent in v4 plans.

#### Integration Contract ← REQUIRED (v5 addition)

- **Triggered from**: SB operator, 90+ days after Phase B Phase B2 release-train gate closes; or operator-decision to retire the cold-tier archive earlier.
- **Returns to**: `session_buddy/storage/migrations/` no longer contains DuckDB V1-V6 SQL files (none of which were about `query_cache_l2` — that table was runtime-CREATE'd in code, not migration'd).
- **Demonstrable by**: `ls session_buddy/storage/migrations/` shows only migrations post-V6 (if any); `pytest` still passes.
- **Rollback signal**: SB boot fails because a future migration runner depends on a V1-V6 file → restore from git.
- **Observability added**: OTel span `migrations.legacy.duckdb.delete` with `count=6`, `since_commit_sha`.

- [ ] **Step 1: Verify archive window closed** — `git log --since="90 days ago" -- session_buddy/storage/migrations/` shows no recent reference; cold archive of `reflection.duckdb` exists in R2 (`sb/cold/reflection.duckdb`).

- [ ] **Step 2: Delete V1-V6 via `git rm`**:

```bash
cd /Users/les/Projects/session-buddy
git rm session_buddy/storage/migrations/V[1-6]__*.sql
git commit -m "refactor(session-buddy): delete legacy DuckDB V1-V6 migrations (post archive window)"
```

### Task 7: Performance test — p99 quick_search read latency ≤ 10ms

**Files:**
- Create: `tests/performance/test_sb_pgvector_p99.py` (per spec §6.2 Validation Matrix and §13 test list)

**v5 addition (per spec §6.2 Demonstrable by implications and §13 test-list)**: was missing in v4 plans.

#### Integration Contract ← REQUIRED (v5 addition)

- **Triggered from**: Pre-merge performance gate on every PR touching `session_buddy/storage/pgvector.py` or `session_buddy/adapters/reflection_adapter_oneiric.py`.
- **Returns to**: `tests/performance/test_sb_pgvector_p99.py` reports `p99 quick_search latency ≤ 10ms` from local pgvector; CI passes the threshold.
- **Demonstrable by**: `pytest tests/performance/test_sb_pgvector_p99.py -v --benchmark-disable-gc` PASS; `pytest-benchmark` report shows p99 within budget.
- **Rollback signal**: p99 > 10ms over 3 consecutive runs → investigate warm-tier index; possibly disable HNSW knobs.
- **Observability added**: histogram metric `warm.pgvector.search.duration_ms` with bucket `le="0.005","0.01","0.05","0.1","0.5","1","5","+Inf"`.

- [ ] **Step 1: Write the test**:

```python
import time
import statistics
from session_buddy.storage.pgvector import SBWarmStore

def test_sb_warm_pgvector_p99_under_10ms():
    ws = SBWarmStore(namespace="sb", pg_url="postgresql://localhost:5432/oneiric_substrate_test")
    seed = [[0.01 * i] * 384 for i in range(50)]
    for vec in seed: ws.upsert(reflection_id=f"bench-{vec!r}", embedding=vec, metadata={})
    durations_ms = []
    for _ in range(1000):
        t0 = time.perf_counter()
        ws.search(embedding=seed[0], top_k=10)
        durations_ms.append((time.perf_counter() - t0) * 1000)
    p99 = statistics.quantiles(durations_ms, n=100)[-1]
    assert p99 <= 10.0, f"p99={p99}ms exceeds 10ms budget"
```

- [ ] **Step 2: Run locally against docker-compose stack; record p99**; if > 10ms, investigate before promoting.

- [ ] **Step 3: Commit**:

```bash
cd /Users/les/Projects/mahavishnu
git add tests/performance/test_sb_pgvector_p99.py
git commit -m "test(perf): SB p99 pgvector ≤ 10ms"
```

## 7. Required Code Changes

| File | Action | Phase task |
|---|---|---|
| `session_buddy/storage/pgvector.py` | CREATE: SBWarmStore class | Task 1 |
| `session_buddy/adapters/reflection_adapter_oneiric.py` | MODIFY: switch warm tier to SBWarmStore | Task 1 |
| `session_buddy/tests/integration/test_sb_warm_pgvector.py` | CREATE | Task 1 |
| `session_buddy/adapters/settings.py:24-52` | MODIFY: delete DuckDB VSS knobs | Task 2 |
| `scripts/migrate_sb_reflection_duckdb_to_pgvector.py` | CREATE | Task 3 |
| `tests/integration/test_sb_migrated_from_duckdb.py` | CREATE | Task 3 |
| `docs/session-buddy/operations/migrate-to-pgvector.md` | CREATE | Task 3 |
| `session_buddy/mcp/server.py` (or health handler) | MODIFY: freeze window | Task 4 |
| `tests/integration/test_cross_namespace_acl_sb.py` | CREATE | Task 5 |
| `oneiric/adapters/vector/pgvector.py` | (optional) MODIFY: add namespace-assertion API | Task 5 |

## 8. Validation Matrix

| Tool / Command | Expected outcome | Evidence |
|---|---|---|
| `grep -rn "duckdb.*reflection\|reflection.duckdb" session_buddy/storage/ session_buddy/adapters/` | zero hits | shell exit code 1 |
| `grep -rn "hnsw_m\|hnsw_ef_construction\|enable_quantization" session_buddy/` | zero hits outside settings | shell exit code 1 |
| `pytest session_buddy/tests/integration/test_sb_warm_pgvector.py -v` | PASS | pytest exit 0 |
| `pytest tests/integration/test_sb_migrated_from_duckdb.py -v` | PASS | pytest exit 0 |
| `pytest tests/integration/test_cross_namespace_acl_sb.py -v` | PASS (PermissionError raised) | pytest exit 0 |
| `pytest akosha/tests/integration/test_akosha_searches_sb_namespace.py -v` | PASS (admin-granted read works) | pytest exit 0 |
| `pytest tests/performance/test_sb_pgvector_p99.py -v` | p99 ≤ 10ms | benchmark report |
| `python scripts/migrate_sb_reflection_duckdb_to_pgvector.py` (against staging copy) | exit 0; counts match | shell exit 0 |
| `ls session_buddy/storage/migrations/` post-Task-6 | only migrations post-V6 (or empty dir) | shell output |
| `crackerjack run -v` (SB) | green | exit code 0 |

## 9. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Migration loses data | Medium | numpy.allclose(atol=1e-5) per record; abort on mismatch; reflection.duckdb kept as cold archive 90 days |
| pgvector pool saturation | Medium | `warm__pg_pool_size=8` per component; sum=24 vs Postgres default 100; Prometheus alert on `pg_stat_activity` > 80 |
| Freeze window blocks writes during migration | Low (intended) | Operators explicitly signal freeze; `/health` 503 returns clearly to clients |
| Cross-namespace data leak | Low | ACL test in Task 5; default-deny; explicit `cross_namespace_grant` required |
| Akosha on different pgvector schema breaks Akosha | Low | Akosha namespace `akosha.*` independent; ACL isolation per spec §5.2 |
| **(Meta, spec §10 #7) oneiric becomes a hard substrate dependency** | Medium | `oneiric>=<pinned>` to SB `pyproject.toml` already required for the cache substrate (Phase A); Phase B extends to PgvectorAdapter import. CI guard test asserts minimum version. |
| **(Meta, spec §10 #8) Cross-component import direction violation** | Medium | Phase B adds SB → oneiric (PgvectorAdapter) and Akosha → oneiric (PgvectorAdapter); no Akosha→Mahavishnu / SB→Mahavishnu imports introduced. CI guard: `grep -rn "from mahavishnu" akosha/ session_buddy/` returns zero hits. |
| **(Meta, spec §10 #9) Rollback complexity across 6 phases × 4 repos** | Medium for Phase B | Phase B is the largest phase (DuckDB→pgvector migration). Task 6 deletes DuckDB V1-V6 SQL only AFTER 90-day archive window. Earlier rollback restores DuckDB; later rollback points require cold-archive restore. Per spec §6.7 cross-phase rollback is union of per-phase rollbacks. |

## 10. Decision Rule

Phase B is complete when ALL of:

- All 5 tasks land as commits.
- Migration script verified against a test fixture (count + embedding equality).
- Cross-namespace ACL test passes (PermissionError by default, grant required).
- SB p99 quick_search ≤ 10ms from local pgvector.
- `crackerjack run -v` green on SB.

**Release-train gate** (per spec §6.7): oneiric ACL module shipped + SB green + user bumps oneiric + user bumps SB + DuckDB→pgvector migration verified + freeze window handled.

## References

- `docs/specs/2026-09-27-shared-bodai-substrate-design.md` §6.2 — Phase B contract
- `oneiric/adapters/vector/pgvector.py` — PgvectorAdapter
- `akosha/storage/pgvector_warm_store.py:150` — Akosha's pre-existing pgvector integration
- `akosha/dev/docker-compose.yml` — local pgvector stack for tests
- `.claude/decisions/wire-up-contract.md` — Integration Contract rules
