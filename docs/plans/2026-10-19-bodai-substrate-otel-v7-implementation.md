---
status: draft
role: implementation
kind: plan
date: 2026-10-19
last_reviewed: 2026-10-19
superseded_by: null
blocks_on: []
topic: substrate-otel
title: "Bodai OTel Substrate v7 — Implementation Plan (PR-0a → PR-A8)"
---

# Bodai OTel Substrate v7 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the event-sourced OTel substrate across three repos — oneiric owns the `spans_substrate` DDL, akosha owns the OTLP receiver + DLQ + heartbeat watcher + retention sweep + canary, mcp-common owns the `service.namespace` bridge and flip — such that every Bodai producer's spans land in one queryable, cardinality-bounded, retention-managed table, with an end-to-end canary proving the write path is alive.

**Architecture:** ADR 017 makes oneiric the canonical persistence substrate, so the `spans_substrate` DDL lands in `oneiric/adapters/vector/duckdb_hot_store.py` (PR-0a) and every component inherits it. Akosha runs an `OTLPReceiver` bound to `:4317` (gRPC) + `:4318` (HTTP), validating each row before batch INSERT, quarantining bad rows to a local `_dlq_rows` table, and running a 6-hour retention sweep with archival. mcp-common ships a two-release bridge (`mcp-ecosystem` → dual-label → `bodai`) so the namespace flip can't strand any consumer.

**Tech Stack:** Python 3.14, DuckDB 2.0.0-dev — the build oneiric/uv.lock pins (re-verified per spec §5.1a), OpenTelemetry `opentelemetry-proto>=1.27` + `opentelemetry-exporter-otlp-proto-grpc>=1.27`, (no migration framework — all DDL is inline `CREATE TABLE IF NOT EXISTS`), `prometheus_client` (`:9464`), `typer` (akosha CLI), `pytest` + `pytest-asyncio`.

**Spec:** `docs/specs/2026-10-19-bodai-substrate-otel-v7.md` — the substrate design. The plan argues from the spec; the spec travels with it. Every task cites the spec section it implements.

## Global Constraints

These apply to every task. A task's requirements implicitly include this section.

- **Python 3.14 only.** `from __future__ import annotations` as the first non-comment line of every new source file, after any module docstring.
- **No version bumps in any Bodai `pyproject.toml` without explicit user approval** (memory: `feedback-mcp-common-version-bump-is-user`). PR-0a's "bump oneiric minor" and the mcp-common pin in PR-A1/PR-A7 are **operator actions**. The plan implements the code and stages the commit; the operator bumps.
- **Pre-1.0 no-backwards-compat** (memory: `feedback-no-backwards-compat-pre-1.0`): replace, don't extend; no deprecation windows. Governs PR-A8's `AKOSHA_SKIP_OTEL_INGESTER` retirement and the flat→nested feature-flag rename.
- **DuckDB (2.0.0-dev) constraints** (spec §5.1a — all verified live): no `WHERE` on `CREATE INDEX`; no `ALTER TABLE ADD CONSTRAINT`; no `COPY (…) TO ?` (filename param); no `ALTER TABLE ADD COLUMN … NOT NULL DEFAULT`. `UNIQUE` must be inline in `CREATE TABLE` for `ON CONFLICT` to resolve.
- **`result.rowcount`** for DML row counts on DuckDB cursors — never `result.fetchone()[0]` (raises `TypeError`).
- **Prometheus convention:** `.labels(...).inc(amount=N)`. Never `inc(n=N)` — `n=` becomes an unlabeled kwarg.
- **Retention filters on `received_at_unix_nano`** (server-populated, clock-trustworthy), never `start_time_unix_nano` (producer clock, drift-prone). Cardinal rule.
- **COPY failure → skip DELETE.** A cold-sink error (NFS, S3 IAM, ENOSPC) must never destroy the rows that failed to archive.
- **Quality gate is `crackerjack run -v -f`.** Never `-p` (memory: `feedback-crankerjack-publish-stage-is-user`).
- **Trunk-based agent-review workflow.** `MAHAVISHNU_AUTO_MERGE=0` for the first PR in each new repo; `=1` (default) for follow-ups.
- **Cross-repo Bash runs must be in a worktree** at `~/.local/state/mahavishnu/worktrees/<repo>/`.
- **`python scripts/audit_orphans.py` must pass before any task is marked done** (per `wire-up-contract.md`). A feature with zero callers is not done.
- **Every task creates its feature-tracking file** at `docs/feature-tracking/<slug>.md` from `docs/feature-tracking/TEMPLATE.md`, with state `built` (not `wired`/`adopted` until the wiring runbook is executed by an operator).
- **No `assert` in production code** (`akosha/**`, `oneiric/**`). Use exceptions. Asserts are fine in tests.
- **Oneiric worktrees** at `~/.local/state/mahavishnu/worktrees/oneiric/`; **akosha** at `~/.local/state/mahavishnu/worktrees/akosha/`; **mcp-common** at `~/.local/state/mahavishnu/worktrees/mcp-common/`.

## Review Focus

Five failure modes the spec implies but no listed test exercises directly. Each gets a test added to the owning task, in that task's own step style.

1. **`LifecycleError` lives in oneiric, not mcp-common.** The spec §6 says `from mcp_common.errors import LifecycleError` and claims it is "confirmed exported at PR-0b commit time". Neither is true. `LifecycleError` is at `oneiric/core/lifecycle.py:25` (a bare `RuntimeError` subclass), raised throughout `oneiric/domains/events.py` and `oneiric/domains/workflows.py` with a stable message-slug style (`"workflow-queue-adapter-missing-enqueue"`). mcp-common has no such symbol at all. **Task 5 imports from oneiric** — akosha already depends on oneiric, so no new dependency is needed.
2. **`telemetry__service_namespace` exists in oneiric but nothing reads it.** `oneiric/core/substrate_settings.py:309` defines it with default `"oneiric-substrate"`. `grep -rn "telemetry__service_namespace"` across oneiric, akosha, and mahavishnu returns **only the definition** — zero consumers. Meanwhile mcp-common's `FastMCPOpenTelemetryMiddleware` hardcodes its own `"mcp-ecosystem"` default at `mcp_common/server/telemetry.py:103`, independent of oneiric. The spec's "bridge release in mcp-common" would emit a label nothing reads. **Task 1** wires the oneiric setting through to the middleware so the setting becomes load-bearing.
3. **akosha's `mcp.common` module does not exist** — the spec's §15 references `mcp_common.health.feed`. The correct import path is `mcp_common.health.feed` (confirmed at `mcp_common/health/feed.py:80`). Copy-pasting the spec's path fails.
4. **DuckDB file-lock on multi-pod sweep.** Two akosha pods running the sweep against the same DuckDB file: the second pod's `DELETE` raises an IO error and the pod dies silently. The spec §15 defers leader-election to writing-plans — **this plan ships the advisory lock in Task 8**.
5. **`archival_target` set to a path outside the four storage roots** gets regex-rejected at settings-load (spec §8.2), which is correct — but the *error message* must name the four valid roots, or the operator's 3am fix is a guess. Task 7 pins the message content.

## Spec-vs-reality gaps this plan resolves

The spec (verified against live code 2026-10-19) has five assumptions that don't hold. Each is resolved here rather than discovered mid-implementation.

| Spec says | Reality (verified 2026-10-19) | Resolution |
|---|---|---|
| §6: `from mcp_common.errors import LifecycleError` — "confirmed exported at PR-0b commit time" | mcp-common has no `LifecycleError` at all. It exists in **oneiric** at `oneiric/core/lifecycle.py:25` (a `RuntimeError` subclass), used throughout `oneiric/domains/`. | **Task 5** imports `from oneiric.core.lifecycle import LifecycleError`. No mcp-common change and no new dependency — akosha already depends on oneiric. |
| §13: mcp-common "bridge release" emits `namespace.legacy_alias`; `OTelSettings` is the settings home | No `OTelSettings` class exists in any of the four repos. The real namespace setting is oneiric's `telemetry__service_namespace` (`oneiric/core/substrate_settings.py:309`, default `"oneiric-substrate"`) and **has zero consumers** — the only fleet-wide hit is the definition itself. mcp-common's middleware hardcodes its own `"mcp-ecosystem"` default. | **Task 1** adds `telemetry__legacy_namespace_alias` to oneiric's substrate settings and wires it into mcp-common's middleware, so the setting becomes load-bearing. **Task 12** flips the default and removes the alias. |
| §13 PR-0a: "Bump oneiric minor" | Version bumps are operator-controlled (memory: `feedback-mcp-common-version-bump-is-user`). | **Task 3** stages the commit; the operator bumps oneiric's version. Recorded in the commit message. |
| §6: "Pin `mcp-common>=0.40` in your PR description" | mcp-common is at **0.31.1**. | The bridge lands as two independent operator bumps (oneiric for the setting, mcp-common for the emission). Task 1's commit message names oneiric's expected minor; Task 6's names the mcp-common floor akosha should pin. |
| §6 lifecycle: akosha CLI is `typer.Typer` | akosha's CLI is `AkoshaCLI()` (`akosha/cli.py:226`), a `typer.Typer` subclass with `add_typer` inherited. | Task 7 attaches the new sub-apps to `app` (the `AkoshaCLI` instance), matching the existing `mcp_app` registration at line 229-230. |

---

## Task 1 (PR-A1): oneiric + mcp-common — make `telemetry__service_namespace` load-bearing

**Repo:** `/Users/les/Projects/oneiric` (the setting) and `/Users/les/Projects/mcp-common` (the emission). Two branches, two commits. Worktrees at `~/.local/state/mahavishnu/worktrees/{oneiric,mcp-common}/`.

**Why this task exists:** `oneiric/core/substrate_settings.py:309` defines `telemetry__service_namespace` (default `"oneiric-substrate"`) and **nothing reads it fleet-wide** — the only hit for the identifier is its own definition. The spec assumed a bridge release would emit `namespace.legacy_alias` from mcp-common, but without a consumer for the primary setting, a bridge is a label nothing indexes. This task makes the oneiric setting authoritative and adds the alias channel for the migration window.

**Files:**
- Modify: `oneiric/oneiric/core/substrate_settings.py:308-312` (add `telemetry__legacy_namespace_alias`)
- Modify: `mcp_common/server/telemetry.py:44-121` (accept `legacy_namespace`, emit the alias, realign the default)
- Create: `oneiric/tests/unit/core/test_substrate_settings_namespace.py`
- Create: `mcp-common/tests/unit/server/test_telemetry_legacy_namespace.py`

**Interfaces:**
- Consumes: nothing (first task in the chain).
- Produces:
  - `SubstrateSettings.telemetry__legacy_namespace_alias: str | None` — new field, default `None`
  - `FastMCPOpenTelemetryMiddleware(service_name, *, environment="production", service_namespace="oneiric-substrate", legacy_namespace: str | None = None)` — note the **default changes** from `"mcp-ecosystem"` to `"oneiric-substrate"`, matching the substrate setting
  - When `legacy_namespace is not None`, `_span_attributes` returns an extra key `namespace.legacy_alias: str`
  Task 5 (akosha receiver) passes both values from oneiric's settings; Task 10 (flip) drops the alias.

- [ ] **Step 1: Write the failing oneiric settings test**

Create `/Users/les/Projects/oneiric/tests/unit/core/test_substrate_settings_namespace.py`:

```python
from __future__ import annotations

from oneiric.core.substrate_settings import SubstrateSettings


def test_legacy_alias_defaults_to_none() -> None:
    assert SubstrateSettings().telemetry__legacy_namespace_alias is None


def test_service_namespace_default_is_oneiric_substrate() -> None:
    assert SubstrateSettings().telemetry__service_namespace == "oneiric-substrate"
```

Read `SubstrateSettings`' actual class name and env-prefix convention from `oneiric/core/substrate_settings.py` before running — the module may name it differently or use an `env_prefix`. Adjust the import to match; the assertions are the contract, not the spelling.

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/les/Projects/oneiric && .venv/bin/pytest tests/unit/core/test_substrate_settings_namespace.py -v`
Expected: FAIL — `telemetry__legacy_namespace_alias` does not exist.

- [ ] **Step 3: Add the setting to oneiric**

In `oneiric/core/substrate_settings.py`, immediately after `telemetry__service_namespace` (line 309-312), add:

```python
    telemetry__legacy_namespace_alias: str | None = Field(
        default=None,
        description=(
            "Legacy service.namespace alias emitted alongside the primary "
            "value during the two-release migration "
            "(oneiric-substrate -> dual-label -> bodai). None outside the "
            "bridge window."
        ),
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/les/Projects/oneiric && .venv/bin/pytest tests/unit/core/test_substrate_settings_namespace.py -v`
Expected: PASS — 2 tests.

- [ ] **Step 5: Commit oneiric (operator bumps version afterward)**

```bash
cd /Users/les/Projects/oneiric
git add oneiric/core/substrate_settings.py tests/unit/core/test_substrate_settings_namespace.py
git commit -m "feat(oneiric): telemetry__legacy_namespace_alias — bridge window channel

telemetry__service_namespace has existed since the substrate settings
were introduced but had zero consumers fleet-wide; the only hit for
the identifier was its own definition. Adding the migration alias
beside it, so the service.namespace two-release migration
(oneiric-substrate -> dual-label -> bodai) has a real channel to move
traffic through rather than a label nothing reads.

Default None — outside the bridge window, nothing changes.

EXPECTED VERSION: minor bump — operator bumps pyproject.toml
(per feedback-mcp-common-version-bump-is-user).

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

- [ ] **Step 6: Write the failing mcp-common test**

Create `/Users/les/Projects/mcp-common/tests/unit/server/test_telemetry_legacy_namespace.py`:

```python
from __future__ import annotations

from mcp_common.server.telemetry import FastMCPOpenTelemetryMiddleware


class _Ctx:
    """Minimal stand-in for MiddlewareContext; _span_attributes reads only
    .method, .type, and .name."""
    method = "tools/call"
    type = "request"
    name = "pool_health"
    message = None


def test_dual_label_emitted_when_legacy_namespace_set() -> None:
    mw = FastMCPOpenTelemetryMiddleware(
        "mahavishnu",
        service_namespace="oneiric-substrate",
        legacy_namespace="mcp-ecosystem",
    )
    attrs = mw._span_attributes(_Ctx())
    assert attrs["service.namespace"] == "oneiric-substrate"
    assert attrs["namespace.legacy_alias"] == "mcp-ecosystem"


def test_no_alias_when_legacy_namespace_absent() -> None:
    mw = FastMCPOpenTelemetryMiddleware("mahavishnu")
    assert "namespace.legacy_alias" not in mw._span_attributes(_Ctx())


def test_default_namespace_matches_substrate_setting() -> None:
    """The middleware default must equal oneiric's substrate default, or
    the bridge reads two different namespaces depending on which layer
    constructed the middleware."""
    mw = FastMCPOpenTelemetryMiddleware("mahavishnu")
    assert mw._span_attributes(_Ctx())["service.namespace"] == "oneiric-substrate"
```

- [ ] **Step 7: Run to verify it fails**

Run: `cd /Users/les/Projects/mcp-common && .venv/bin/pytest tests/unit/server/test_telemetry_legacy_namespace.py -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'legacy_namespace'`

- [ ] **Step 8: Implement the emission in mcp-common**

In `mcp_common/server/telemetry.py`, replace the constructor at line 47-56:

```python
    def __init__(
        self,
        service_name: str,
        *,
        environment: str = "production",
        service_namespace: str = "oneiric-substrate",
        legacy_namespace: str | None = None,
    ) -> None:
        self.service_name = service_name
        self.environment = environment
        self.service_namespace = service_namespace
        self.legacy_namespace = legacy_namespace
        self._tracer = (
            trace.get_tracer(f"{__name__}.{service_name}") if _OTEL_AVAILABLE else None
        )
```

In `_span_attributes` (line 98-121), immediately after the `attributes` dict literal closes at line 106:

```python
        if self.legacy_namespace is not None:
            attributes["namespace.legacy_alias"] = self.legacy_namespace
```

- [ ] **Step 9: Run to verify it passes**

Run: `cd /Users/les/Projects/mcp-common && .venv/bin/pytest tests/unit/server/test_telemetry_legacy_namespace.py -v`
Expected: PASS — 3 tests.

- [ ] **Step 10: Run the mcp-common telemetry suite for regressions**

Run: `cd /Users/les/Projects/mcp-common && .venv/bin/pytest tests/ -k "telemetry or span or middleware" -v`
Expected: PASS. The default-namespace change from `"mcp-ecosystem"` to `"oneiric-substrate"` is the risky part — any test asserting the old default fails here, and that failure is the signal to check whether the change is intended fleet-wide or should stay component-local.

- [ ] **Step 11: Commit mcp-common**

```bash
cd /Users/les/Projects/mcp-common
git add mcp_common/server/telemetry.py tests/unit/server/test_telemetry_legacy_namespace.py
git commit -m "feat(mcp-common): emit namespace.legacy_alias; align default to substrate

Two changes for the service.namespace two-release migration
(oneiric-substrate -> dual-label -> bodai):

1. Optional legacy_namespace kwarg. When set, _span_attributes emits
   namespace.legacy_alias alongside service.namespace, so consumers
   can migrate to the new namespace before producers flip.

2. The default service.namespace moves from 'mcp-ecosystem' to
   'oneiric-substrate' to match oneiric's substrate setting
   (oneiric/core/substrate_settings.py:309). The middleware previously
   hardcoded a namespace the substrate setting never governed, so the
   two layers could disagree about what namespace a span carries.
   This is a breaking default change — grep for explicit
   service_namespace= arguments that relied on the old default.

EXPECTED VERSION: minor bump — operator bumps pyproject.toml
(per feedback-mcp-common-version-bump-is-user). Akosha pins the
resulting release.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

#### Integration Contract (Task 1)
- **Triggered from**: any Bodai `*-mcp` server constructing `FastMCPOpenTelemetryMiddleware`; akosha's Task 5 lifespan passes both `service_namespace` and `legacy_namespace` from oneiric's settings.
- **Returns to / updates**: `oneiric/core/substrate_settings.py` (new field), `mcp_common/server/telemetry.py` (`__init__` signature + default, `_span_attributes` body).
- **Demonstrable by**: `pytest tests/unit/core/test_substrate_settings_namespace.py` (oneiric, 2 passing) and `pytest tests/unit/server/test_telemetry_legacy_namespace.py` (mcp-common, 3 passing).
- **Rollback signal**: the mcp-common regression run finds a test asserting `"mcp-ecosystem"` as the default → the namespace flip is not fleet-safe yet; revert only the default change (Step 8's first hunk) and keep the alias kwarg.
- **Observability added**: none directly; `namespace.legacy_alias` on spans is the signal that the bridge window is active.

---

## Task 2 (PR-0a): oneiric — `spans_substrate` DDL

**Repo:** `/Users/les/Projects/oneiric`. Branch: `feat/spans-substrate-ddl`. Worktree at `~/.local/state/mahavishnu/worktrees/oneiric/`.

**Files:**
- Modify: `oneiric/adapters/vector/duckdb_hot_store.py:130-185` (`initialize()`; class attributes above `__init__`)
- Create: `tests/unit/adapters/vector/test_spans_substrate_ddl.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `DuckdbHotStore.spans_substrate_table: str = "spans_substrate"` (class attr)
  - `DuckdbHotStore.conversations_table: str = "conversations"` (class attr, new)
  - `async DuckdbHotStore.table_exists(self, name: str) -> bool`
  - `async DuckdbHotStore.initialize()` creates `spans_substrate` with the spec §5.1 DDL (verified live, spec §5.1a).
  Task 4 (akosha `HotStore`) subclasses this; Task 5's `OTLPReceiver.start()` calls `table_exists(spans_substrate_table)`.

- [ ] **Step 1: Write the failing test**

Create `/Users/les/Projects/oneiric/tests/unit/adapters/vector/test_spans_substrate_ddl.py`:

```python
from __future__ import annotations

import duckdb
import pytest

from oneiric.adapters.vector.duckdb_hot_store import DuckdbHotStore


@pytest.fixture
def store(tmp_path):
    return DuckdbHotStore(database_path=tmp_path / "test.duckdb", embedding_dim=4)


def test_spans_substrate_created_on_initialize(store: DuckdbHotStore) -> None:
    # The fixture has not been initialized yet.
    assert store.spans_substrate_table == "spans_substrate"


@pytest.mark.asyncio
async def test_initialize_creates_spans_substrate(store: DuckdbHotStore) -> None:
    await store.initialize()
    assert await store.table_exists("spans_substrate") is True
    assert await store.table_exists("conversations") is True


@pytest.mark.asyncio
async def test_table_exists_false_for_absent_table(store: DuckdbHotStore) -> None:
    await store.initialize()
    assert await store.table_exists("no_such_table") is False


@pytest.mark.asyncio
async def test_unique_constraint_is_declared_inline(store: DuckdbHotStore) -> None:
    """ON CONFLICT (trace_id, span_id) requires a UNIQUE CONSTRAINT, not a
    UNIQUE INDEX — DuckDB (2.0.0-dev) raises NotImplementedException for
    ALTER TABLE ADD CONSTRAINT (spec §5.1a)."""
    await store.initialize()
    rows = store.conn.execute(
        "SELECT constraint_type, constraint_column_names "
        "FROM duckdb_constraints() WHERE table_name = 'spans_substrate'"
    ).fetchall()
    uniq = [r for r in rows if r[0] == "UNIQUE"]
    assert len(uniq) == 1, f"expected exactly one UNIQUE constraint, got {uniq}"
    assert set(uniq[0][1]) == {"trace_id", "span_id"}


@pytest.mark.asyncio
async def test_initialize_is_idempotent(store: DuckdbHotStore) -> None:
    await store.initialize()
    await store.initialize()  # must not raise
    assert await store.table_exists("spans_substrate") is True
```

If `DuckdbHotStore.__init__` takes different arguments than `db_path`/`embedding_dim`, read the constructor (`oneiric/adapters/vector/duckdb_hot_store.py:100-128`) and fix the fixture. `embedding_dim` must be supplied because the `conversations` DDL interpolates `FLOAT[{self._embedding_dim}]` (line 148).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/oneiric && .venv/bin/pytest tests/unit/adapters/vector/test_spans_substrate_ddl.py -v`
Expected: FAIL with `AttributeError: 'DuckdbHotStore' object has no attribute 'spans_substrate_table'`

- [ ] **Step 3: Add the class attributes**

In `oneiric/adapters/vector/duckdb_hot_store.py`, immediately above `async def initialize` (line 130), add at class body scope:

```python
    spans_substrate_table: str = "spans_substrate"
    conversations_table: str = "conversations"
```

- [ ] **Step 4: Add the `table_exists` method**

Add after `initialize()` ends (line 185, after `logger.info("Hot store initialized")`):

```python
    async def table_exists(self, name: str) -> bool:
        """Return True if `name` is a table in the current database.

        Used by consumers (e.g. akosha's OTLPReceiver.start) to fail loud
        when the substrate has not been initialized. DuckDB (2.0.0-dev) does not
        accept a parameter marker in the duckdb_tables filter, so the name
        is escaped by comparison rather than bound.
        """
        async with self._lock:
            row = await self._conn.execute(
                "SELECT 1 FROM duckdb_tables() WHERE table_name = ? LIMIT 1", [name]
            ).fetchone()
        return row is not None
```

**If `self._conn` is not the connection attribute in this class** — the verified code uses `self.conn` (line 136, `self.conn = duckdb.connect(...)`) — use `self.conn`. Also, the verified `initialize()` uses synchronous `self.conn.execute(...)` calls, not awaited ones. Match the surrounding style: if `conn.execute` is sync, drop the `await`:

```python
    async def table_exists(self, name: str) -> bool:
        async with self._lock:
            row = self.conn.execute(
                "SELECT 1 FROM duckdb_tables() WHERE table_name = ? LIMIT 1", [name]
            ).fetchone()
        return row is not None
```

- [ ] **Step 5: Add the `spans_substrate` DDL to `initialize()`**

Immediately after the `conversations` CREATE TABLE `execute()` block closes (around line 156), insert the spec §5.1 DDL verbatim. The full DDL is at spec lines 117-174; copy it exactly, including:

```python
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS spans_substrate (
                    span_id                 TEXT PRIMARY KEY,
                    trace_id                TEXT,
                    parent_span_id          TEXT,
                    service_name            TEXT         NOT NULL,
                    service_namespace       TEXT         NOT NULL,
                    deployment_environment  TEXT,
                    telemetry_source        TEXT,
                    telemetry_source_type   TEXT,
                    span_name               TEXT         NOT NULL,
                    start_time_unix_nano    BIGINT       NOT NULL,
                    end_time_unix_nano      BIGINT,
                    received_at_unix_nano   BIGINT       NOT NULL DEFAULT (CAST(epoch_ms(now()) * 1e6 AS BIGINT)),
                    duration_ms             REAL,
                    outcome                 TEXT,
                    selector                TEXT,
                    task_class              TEXT,
                    latency_ms              REAL,
                    gen_ai_provider_name    TEXT,
                    gen_ai_request_model    TEXT,
                    gen_ai_response_model   TEXT,
                    gen_ai_usage_input_tokens INTEGER,
                    gen_ai_usage_output_tokens INTEGER,
                    gen_ai_usage_cost       NUMERIC(10, 6),
                    status_code             TEXT,
                    status_message          TEXT,
                    attributes              JSON         NOT NULL,
                    events                  JSON,
                    resource                JSON         NOT NULL,
                    has_gen_ai_attrs        BOOLEAN      NOT NULL DEFAULT FALSE,
                    has_dispatch_attrs      BOOLEAN      NOT NULL DEFAULT FALSE,
                    inserted_at             TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at              TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_span_identity UNIQUE (trace_id, span_id)
                )
            """)
            for ddl, name in (
                ("CREATE INDEX IF NOT EXISTS idx_spans_selector_task_class_outcome "
                 "ON spans_substrate(selector, task_class, outcome, received_at_unix_nano DESC)",
                 "idx_spans_selector_task_class_outcome"),
                ("CREATE INDEX IF NOT EXISTS idx_spans_service_name_recent "
                 "ON spans_substrate(service_name, received_at_unix_nano DESC)",
                 "idx_spans_service_name_recent"),
                ("CREATE INDEX IF NOT EXISTS idx_spans_source_type_recent "
                 "ON spans_substrate(telemetry_source_type, received_at_unix_nano DESC)",
                 "idx_spans_source_type_recent"),
                ("CREATE INDEX IF NOT EXISTS idx_spans_received_at_recent "
                 "ON spans_substrate(received_at_unix_nano DESC)",
                 "idx_spans_received_at_recent"),
            ):
                try:
                    self.conn.execute(ddl)
                    logger.info("Created %s index", name)
                except Exception as exc:
                    logger.warning("%s index creation failed: %s", name, exc)
```

Wrap each CREATE INDEX in try/except to match the existing index-creation pattern (line 158-183), so an index failure degrades performance rather than failing `initialize()`.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /Users/les/Projects/oneiric && .venv/bin/pytest tests/unit/adapters/vector/test_spans_substrate_ddl.py -v`
Expected: PASS — 5 tests.

- [ ] **Step 7: Verify the DDL executes live against the installed DuckDB**

Run: `cd /Users/les/Projects/oneiric && .venv/bin/python -c "
import duckdb, re, pathlib
src = pathlib.Path('oneiric/adapters/vector/duckdb_hot_store.py').read_text()
print('duckdb', duckdb.__version__)
con = duckdb.connect(':memory:')
# extract and execute the spans_substrate DDL block verbatim
block = re.search(r'CREATE TABLE IF NOT EXISTS spans_substrate.*?\)', src, re.S).group(0)
con.execute(block)
print('tables:', [r[0] for r in con.execute(\"SELECT table_name FROM duckdb_tables() WHERE table_name='spans_substrate'\").fetchall()])
con.execute(\"INSERT INTO spans_substrate (span_id, trace_id, service_name, service_namespace, span_name, start_time_unix_nano, attributes, resource) VALUES ('s1','t1','svc','bodai','n',1,'{}','{}')\")
print('rowcount:', con.execute('SELECT COUNT(*) FROM spans_substrate').fetchone()[0])
"`

Expected: prints the duckdb version oneiric pins, lists `spans_substrate`, prints `rowcount: 1`. As of 2026-10-20 that version is `2.0.0.dev2610192346`. If it differs, run `mahavishnu/scripts/verify_otel_ddl.py` — not this ad-hoc snippet — and reconcile against the spec §5.1a footer before proceeding. `result.rowcount` is version-sensitive (it returned `-1` on 1.5.6), so a `rowcount: 1` that prints as `-1` means the pin moved back to an older DuckDB and the sweep in Task 7 must not trust `rowcount`.

- [ ] **Step 8: Run the existing oneiric hot-store suite for regressions**

Run: `cd /Users/les/Projects/oneiric && .venv/bin/pytest tests/ -k "hot_store or duckdb or vector" -v`
Expected: PASS.

- [ ] **Step 9: Commit (operator bumps version afterward)**

```bash
cd /Users/les/Projects/oneiric
git add oneiric/adapters/vector/duckdb_hot_store.py tests/unit/adapters/vector/test_spans_substrate_ddl.py
git commit -m "feat(oneiric): spans_substrate DDL — Bodai OTel substrate table

Adds the spans_substrate table (spec §5.1) alongside conversations in
DuckdbHotStore.initialize(), plus spans_substrate_table /
conversations_table class attributes and table_exists().

DDL verified live against the duckdb oneiric/uv.lock pins
(2.0.0.dev2610192346) on 2026-10-20; re-verified with mahavishnu's
scripts/verify_otel_ddl.py, 12 assertions, 0 drift.
uq_span_identity UNIQUE (trace_id, span_id) is declared INLINE — ALTER
TABLE ADD CONSTRAINT is unsupported (DependencyException), and ON CONFLICT
(trace_id, span_id) only resolves against a CONSTRAINT, not an INDEX.
Note DuckDB stores it as spans_substrate_trace_id_span_id_key.

All four ordering indexes key on received_at_unix_nano DESC (the
server-populated column), per the spec's cardinal rule.

EXPECTED VERSION: minor bump — operator bumps pyproject.toml
(per feedback-mcp-common-version-bump-is-user). Akosha PR-A3 pins the
resulting oneiric release.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

- [ ] **Step 10: Record feature-tracking state**

Create `docs/feature-tracking/otel-spans-substrate-ddl.md` from the template with state `built`. Not `adopted` until the operator bumps oneiric's version and akosha's `HotStore` subclasses the new DDL (Task 4).

#### Integration Contract (Task 2)
- **Triggered from**: `uv pip install -e .` (registers nothing new); any component calling `DuckdbHotStore.initialize()` at boot.
- **Returns to / updates**: `oneiric/adapters/vector/duckdb_hot_store.py` — class attributes, `initialize()` body, new `table_exists()`.
- **Demonstrable by**: `pytest tests/unit/adapters/vector/test_spans_substrate_ddl.py -v` — 5 passing; the Step 7 live-DDL script prints `rowcount: 1`.
- **Rollback signal**: `test_unique_constraint_is_declared_inline` finds zero UNIQUE constraints → `ON CONFLICT (trace_id, span_id)` will not resolve and every batch INSERT raises `Binder Error`.
- **Observability added**: `logger.info("Created %s index", name)` per index; existing `logger.info("Hot store initialized")`.

---

## Task 3 (PR-0b): akosha — dependency move + `set_shared_otel_receiver` hook

**Repo:** `/Users/les/Projects/akosha`. Branch: `feat/otel-receiver-deps`. Worktree at `~/.local/state/mahavishnu/worktrees/akosha/`.

**Files:**
- Modify: `pyproject.toml:11-27` (add two deps to `[project.dependencies]`)
- Modify: `akosha/mcp/server.py:308-312` (`clear_shared_services`), plus new module global + getter/setter near `set_shared_hot_store` (line 282)
- Modify: `akosha/observability/tracing.py:40-68` (`setup_telemetry` signature + hardcoded namespace; spec §6.5)
- Create: `tests/unit/mcp/test_shared_otel_receiver.py`
- Create: `tests/unit/observability/test_tracing_namespace.py`

**Interfaces:**
- Consumes: `telemetry__service_namespace` and `telemetry__legacy_namespace_alias` from oneiric's settings (Task 1).
- Produces:
  - `set_shared_otel_receiver(receiver: Any) -> None`
  - `get_shared_otel_receiver() -> Any | None`
  - module global `_shared_otel_receiver: Any | None = None`
  - `clear_shared_services()` nils all three globals
  - `opentelemetry-proto>=1.27` and `opentelemetry-exporter-otlp-proto-grpc>=1.27` in `[project.dependencies]`
  - `setup_telemetry(service_name, environment, otlp_endpoint=None, enable_console_export=False, sample_rate=1.0, *, service_namespace: str | None = None, legacy_namespace: str | None = None) -> tuple[Tracer, Meter]` — the two new params are keyword-only with `None` defaults so existing call sites keep compiling
  Task 5's lifespan calls `set_shared_otel_receiver(receiver)`. Task 12 removes the `legacy_namespace` param.

- [ ] **Step 1: Write the failing test**

Create `/Users/les/Projects/akosha/tests/unit/mcp/test_shared_otel_receiver.py`:

```python
from __future__ import annotations

from akosha.mcp import server as srv


def test_set_and_get_shared_otel_receiver() -> None:
    sentinel = object()
    srv.set_shared_otel_receiver(sentinel)
    try:
        assert srv.get_shared_otel_receiver() is sentinel
    finally:
        srv.clear_shared_services()


def test_clear_shared_services_nils_receiver() -> None:
    srv.set_shared_otel_receiver(object())
    srv.clear_shared_services()
    assert srv.get_shared_otel_receiver() is None


def test_create_app_twice_does_not_leak_receiver() -> None:
    """Regression guard from spec §6: without the clear_shared_services
    extension, a second create_app() leaks the prior singleton."""
    srv.clear_shared_services()
    srv.set_shared_otel_receiver(object())
    assert srv.get_shared_otel_receiver() is not None
    srv.clear_shared_services()
    assert srv.get_shared_otel_receiver() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/unit/mcp/test_shared_otel_receiver.py -v`
Expected: FAIL with `AttributeError: module 'akosha.mcp.server' has no attribute 'set_shared_otel_receiver'`

- [ ] **Step 3: Add the module global and accessors**

In `akosha/mcp/server.py`, after `get_shared_kg_builder()` (line ~305), add:

```python
_shared_otel_receiver: Any | None = None


def set_shared_otel_receiver(receiver: Any) -> None:
    """Publish the lifespan-owned OTLPReceiver so tool-group wrappers can reuse it.

    New in PR-0b (spec §6). Mirrors :func:`set_shared_hot_store`; cleared by
    :func:`clear_shared_services` so the next ``create_app()`` starts fresh.
    """
    global _shared_otel_receiver
    _shared_otel_receiver = receiver


def get_shared_otel_receiver() -> Any | None:
    """Return the lifespan-owned OTLPReceiver, or ``None`` if unset."""
    return _shared_otel_receiver
```

- [ ] **Step 4: Extend `clear_shared_services()`**

Replace the body at line 308-312:

```python
def clear_shared_services() -> None:
    """Clear all singletons. Called from the lifespan teardown."""
    global _shared_hot_store, _shared_kg_builder, _shared_otel_receiver
    _shared_hot_store = None
    _shared_kg_builder = None
    _shared_otel_receiver = None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/unit/mcp/test_shared_otel_receiver.py -v`
Expected: PASS — 3 tests.

- [ ] **Step 6: Move the two OTel deps into `[project.dependencies]`**

In `akosha/pyproject.toml`, the existing OTel deps are at lines 22-27 inside `dependencies = [` (starts line 11). Append after line 27:

```toml
    "opentelemetry-proto>=1.27",
    "opentelemetry-exporter-otlp-proto-grpc>=1.27",
```

These are hard runtime dependencies per spec §6.4 — not PEP 735 `[dependency-groups]` entries. The previous group-based approach was wrong: PEP 735 groups never auto-install, so a fresh `uv sync` would lack them and `OTLPReceiver.start()` would fail. Verify there is no existing `[dependency-groups].otel-receiver` block to delete; if one exists, remove it (spec §6.4, "removed in v3").

- [ ] **Step 7: Verify the deps install**

Run: `cd /Users/les/Projects/akosha && uv sync && .venv/bin/python -c "
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
print('opentelemetry-proto OK')
import grpc; print('grpc OK')
"`

Expected: prints both OK lines. If `uv sync` rewrites `uv.lock` wholesale, target the update instead: `uv pip install 'opentelemetry-proto>=1.27' 'opentelemetry-exporter-otlp-proto-grpc>=1.27'`.

- [ ] **Step 8: Write the failing `tracing.py` namespace test (spec §6.5)**

Create `/Users/les/Projects/akosha/tests/unit/observability/test_tracing_namespace.py`:

```python
from __future__ import annotations

from unittest.mock import patch

from akosha.observability import tracing


def _captured_resource() -> dict:
    """Capture the Resource dict handed to Resource.create."""
    captured: dict = {}
    real = tracing.Resource.create

    def spy(attrs):
        captured.update(attrs)
        return real(attrs)

    with patch.object(tracing, "Resource", create=True) as res:
        res.create.side_effect = spy
        tracing.setup_telemetry(service_name="akosha", environment="test")
    return captured


def test_namespace_is_configurable() -> None:
    with patch.object(tracing, "Resource", create=True) as res:
        res.create.side_effect = lambda a: a
        tracing.setup_telemetry(
            service_name="akosha",
            environment="test",
            service_namespace="bodai",
        )
    assert res.create.call_args[0][0]["service.namespace"] == "bodai"


def test_namespace_defaults_to_settings_value() -> None:
    """Without an explicit override the namespace must come from oneiric's
    substrate setting, not the hardcoded \"akosha\" literal."""
    with patch.object(tracing, "Resource", create=True) as res:
        res.create.side_effect = lambda a: a
        tracing.setup_telemetry(service_name="akosha", environment="test")
    ns = res.create.call_args[0][0]["service.namespace"]
    assert ns != "akosha", "namespace still hardcoded; §6.5 not applied"


def test_legacy_namespace_emitted_when_set() -> None:
    with patch.object(tracing, "Resource", create=True) as res:
        res.create.side_effect = lambda a: a
        tracing.setup_telemetry(
            service_name="akosha",
            environment="test",
            service_namespace="oneiric-substrate",
            legacy_namespace="mcp-ecosystem",
        )
    assert res.create.call_args[0][0]["namespace.legacy_alias"] == "mcp-ecosystem"


def test_existing_callers_still_compile() -> None:
    """The new params are keyword-only with None defaults; positional
    callers must keep working."""
    import inspect

    sig = inspect.signature(tracing.setup_telemetry)
    for name in ("service_namespace", "legacy_namespace"):
        assert sig.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters[name].default is None
```

The first test's `_captured_resource` helper is unused — delete it. The three remaining tests are the contract.

- [ ] **Step 9: Run to verify it fails**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/unit/observability/test_tracing_namespace.py -v`
Expected: FAIL — `setup_telemetry` takes no `service_namespace` kwarg.

- [ ] **Step 10: Fix `tracing.py` namespace hygiene (spec §6.5)**

`akosha/observability/tracing.py` currently hardcodes `"service.namespace": "akosha"` inside the `Resource.create({...})` call at line 62. Extend the signature (line 40) and source the namespace from oneiric's settings:

```python
def setup_telemetry(
    service_name: str = "akosha",
    environment: str = "development",
    otlp_endpoint: str | None = None,
    enable_console_export: bool = False,
    sample_rate: float = 1.0,
    *,
    service_namespace: str | None = None,
    legacy_namespace: str | None = None,
) -> tuple[trace.Tracer, metrics.Meter]:
```

Then replace the resource literal at line 62:

```python
    if service_namespace is None:
        try:
            from oneiric.core.substrate_settings import SubstrateSettings

            _s = SubstrateSettings()
            service_namespace = _s.telemetry__service_namespace
            if legacy_namespace is None:
                legacy_namespace = _s.telemetry__legacy_namespace_alias
        except Exception:  # substrate settings unavailable at boot
            logger.warning(
                "substrate_settings_unavailable; falling back to "
                "service.namespace=%s", service_name,
            )
            service_namespace = service_name

    resource_attrs: dict[str, object] = {
        "service.name": service_name,
        "service.namespace": service_namespace,
        "deployment.environment": environment,
    }
    if legacy_namespace is not None:
        resource_attrs["namespace.legacy_alias"] = legacy_namespace

    resource = Resource.create(resource_attrs)
```

The `except` branch matters: `setup_telemetry` runs at boot, possibly before oneiric's settings are resolvable. Falling back to `service_name` preserves the old behavior rather than crashing the server.

Update the call site at `akosha/mcp/server.py:466` to pass the live values:

```python
        tracer, meter = setup_telemetry(
            service_name="akosha",
            environment=settings.environment,
            service_namespace=settings.telemetry__service_namespace,
            legacy_namespace=settings.telemetry__legacy_namespace_alias,
        )
```

Read the surrounding call site first — it may already pass `otlp_endpoint` and `sample_rate` positionally. Add the two new kwargs without disturbing the existing arguments.

- [ ] **Step 11: Run to verify it passes**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/unit/observability/test_tracing_namespace.py -v`
Expected: PASS — 3 tests.

- [ ] **Step 12: Run the akosha mcp + observability suites for regressions**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/unit/mcp/ tests/unit/observability/ -v`
Expected: PASS.

- [ ] **Step 13: Commit (operator bumps version afterward)**

```bash
cd /Users/les/Projects/akosha
git add pyproject.toml akosha/mcp/server.py akosha/observability/tracing.py \
  tests/unit/mcp/test_shared_otel_receiver.py \
  tests/unit/observability/test_tracing_namespace.py
git commit -m "feat(akosha): OTel receiver deps + shared-receiver singleton hook

Three edits per spec §13 PR-0b:
(a) set_shared_otel_receiver() / get_shared_otel_receiver()
(b) module-level _shared_otel_receiver: Any | None = None
(c) clear_shared_services() extended to nil the new global alongside
    _shared_hot_store and _shared_kg_builder

Without (c), test isolation regresses: a second create_app() leaks the
prior receiver singleton (regression test guards this).

opentelemetry-proto and opentelemetry-exporter-otlp-proto-grpc move to
[project.dependencies] as hard runtime deps. The prior PEP 735 group
approach was wrong — groups never auto-install, so a fresh uv sync
produced a receiver that could not deserialize an ExportTraceServiceRequest.

Also fixes spec §6.5 namespace hygiene: tracing.py hardcoded
\"service.namespace\": \"akosha\" inside Resource.create, so akosha's
outgoing spans carried a namespace no other component used and the
§13.2 validator would have needed an akosha-specific carve-out.
setup_telemetry gains keyword-only service_namespace / legacy_namespace
and sources them from oneiric's substrate settings, so every producer
carries the same namespace.

EXPECTED VERSION: minor bump — operator bumps pyproject.toml
(per feedback-mcp-common-version-bump-is-user).

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

#### Integration Contract (Task 3)
- **Triggered from**: `uv sync` (installs the new deps); `akosha/mcp/server.py` lifespan (Task 5 calls `set_shared_otel_receiver`); `clear_shared_services()` on lifespan teardown; every akosha process boot calls `setup_telemetry`.
- **Returns to / updates**: `akosha/mcp/server.py` (3 globals in `clear_shared_services`, the `setup_telemetry` call site), `akosha/observability/tracing.py` (signature + resource literal), `akosha/pyproject.toml` (`[project.dependencies]`).
- **Demonstrable by**: `pytest tests/unit/mcp/test_shared_otel_receiver.py -v` — 3 passing; `pytest tests/unit/observability/test_tracing_namespace.py -v` — 3 passing; the Step 7 import script prints OK twice.
- **Rollback signal**: existing `tests/unit/mcp/` failures asserting `clear_shared_services` clears exactly two globals → the `global` statement must list all three or the extra name leaks as a `SyntaxError` at import. `test_namespace_defaults_to_settings_value` failing → the hardcoded literal is still in place.
- **Observability added**: none (lifecycle plumbing; the namespace now shows up on every outgoing span's resource attributes).

---

## Task 4: akosha — `HotStore.insert_spans_substrate`

**Repo:** `/Users/les/Projects/akosha`. Same branch as Task 3.

**Files:**
- Modify: `akosha/storage/hot_store.py` (add `insert_spans_substrate`)
- Create: `tests/unit/storage/test_insert_spans_substrate.py`

**Interfaces:**
- Consumes: `DuckdbHotStore` from Task 2 (`spans_substrate_table` class attr, `initialize()`, `self.conn`, `self._lock`).
- Produces:
  ```python
  async def insert_spans_substrate(
      self, rows: list[dict[str, Any]]
  ) -> tuple[int, int]:
      """Returns (inserted_count, deduped_count)."""
  ```
  `deduped_count` = `len(rows) - inserted_count`. Task 5's `_handle_batch` and Task 10's canary both call this.

- [ ] **Step 1: Write the failing test**

Create `/Users/les/Projects/akosha/tests/unit/storage/test_insert_spans_substrate.py`:

```python
from __future__ import annotations

import pytest

from akosha.storage.hot_store import HotStore


def _row(span_id: str, trace_id: str = "t1") -> dict:
    return {
        "span_id": span_id,
        "trace_id": trace_id,
        "parent_span_id": None,
        "service_name": "mahavishnu",
        "service_namespace": "bodai",
        "deployment_environment": "local",
        "span_name": "test.span",
        "start_time_unix_nano": 1_700_000_000_000_000_000,
        "end_time_unix_nano": 1_700_000_000_100_000_000,
        "duration_ms": 100.0,
        "outcome": "success",
        "status_code": "STATUS_CODE_OK",
        "attributes": {"k": "v"},
        "resource": {"service.name": "mahavishnu"},
    }


@pytest.fixture
async def store(tmp_path):
    hs = HotStore(database_path=tmp_path / "t.duckdb")
    await hs.initialize()
    return hs


@pytest.mark.asyncio
async def test_inserts_new_rows(store: HotStore) -> None:
    inserted, deduped = await store.insert_spans_substrate([_row("s1"), _row("s2")])
    assert (inserted, deduped) == (2, 0)


@pytest.mark.asyncio
async def test_dedupes_on_trace_span_conflict(store: HotStore) -> None:
    await store.insert_spans_substrate([_row("s1")])
    inserted, deduped = await store.insert_spans_substrate([_row("s1")])
    assert (inserted, deduped) == (0, 1)


@pytest.mark.asyncio
async def test_partial_insert_mixed(store: HotStore) -> None:
    await store.insert_spans_substrate([_row("s1")])
    inserted, deduped = await store.insert_spans_substrate([_row("s1"), _row("s2")])
    assert (inserted, deduped) == (1, 1)


@pytest.mark.asyncio
async def test_received_at_is_server_populated(store: HotStore) -> None:
    await store.insert_spans_substrate([_row("s1")])
    row = store.conn.execute(
        "SELECT received_at_unix_nano FROM spans_substrate WHERE span_id='s1'"
    ).fetchone()
    assert row is not None
    # Non-zero and plausibly-current: the column default computes from now().
    assert row[0] > 1_600_000_000_000_000_000


@pytest.mark.asyncio
async def test_empty_rows_returns_zero(store: HotStore) -> None:
    assert await store.insert_spans_substrate([]) == (0, 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/unit/storage/test_insert_spans_substrate.py -v`
Expected: FAIL with `AttributeError: 'HotStore' object has no attribute 'insert_spans_substrate'`

- [ ] **Step 3: Read the existing `HotStore` to match its connection style**

Run: `cd /Users/les/Projects/akosha && grep -n "class HotStore\|self.conn\|_conn\|async def insert\|def _lock" akosha/storage/hot_store.py | head -20`

The verified oneiric base uses synchronous `self.conn.execute(...)` under `async with self._lock`. If akosha's `HotStore` mirrors that, match it exactly. If it uses an awaited async connection, match that instead. **Do not mix the two styles in one method.**

- [ ] **Step 4: Implement `insert_spans_substrate`**

Add to `HotStore`:

```python
    # Columns written by the receiver, in DDL order. Rows carry every
    # NOT NULL column; the rest fall back to their defaults.
    _SPAN_COLUMNS: tuple[str, ...] = (
        "span_id", "trace_id", "parent_span_id", "service_name",
        "service_namespace", "deployment_environment", "telemetry_source",
        "telemetry_source_type", "span_name", "start_time_unix_nano",
        "end_time_unix_nano", "duration_ms", "outcome", "selector",
        "task_class", "latency_ms", "gen_ai_provider_name",
        "gen_ai_request_model", "gen_ai_response_model",
        "gen_ai_usage_input_tokens", "gen_ai_usage_output_tokens",
        "gen_ai_usage_cost", "status_code", "status_message",
        "attributes", "events", "resource", "has_gen_ai_attrs",
        "has_dispatch_attrs",
    )

    async def insert_spans_substrate(
        self, rows: list[dict[str, Any]]
    ) -> tuple[int, int]:
        """Insert validated span rows; return (inserted_count, deduped_count).

        Dedup is handled by the inline UNIQUE CONSTRAINT uq_span_identity
        (trace_id, span_id) declared in the substrate DDL. ON CONFLICT DO
        NOTHING + RETURNING gives us the inserted count in a single
        round-trip; deduped is derived by subtraction because DuckDB's
        RETURNING yields only the rows that actually landed.
        """
        if not rows:
            return (0, 0)
        columns = ", ".join(self._SPAN_COLUMNS)
        placeholders = ", ".join("?" for _ in self._SPAN_COLUMNS)
        values = [row.get(col) for row in rows for col in self._SPAN_COLUMNS]
        sql = (
            f"INSERT INTO {self.spans_substrate_table} ({columns}) "
            f"VALUES ({placeholders}) "
            "ON CONFLICT (trace_id, span_id) DO NOTHING RETURNING span_id"
        )
        async with self._lock:
            result = self.conn.execute(sql, values)
            returned = result.fetchall()
        inserted = len(returned)
        return (inserted, len(rows) - inserted)
```

**Critical:** `RETURNING` must be fetched before the cursor is released — `fetchall()` inside the lock, not after. DuckDB (2.0.0-dev) returns only the rows that passed the `ON CONFLICT` filter, which is exactly the `inserted` count we need.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/unit/storage/test_insert_spans_substrate.py -v`
Expected: PASS — 5 tests.

- [ ] **Step 6: Run the existing akosha storage suite for regressions**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/unit/storage/ -v`
Expected: PASS.

- [ ] **Step 7: Run the orphan audit**

Run: `/Users/les/Projects/mahavishnu/.venv/bin/python /Users/les/Projects/mahavishnu/scripts/audit_orphans.py` — the orphan audit lives in mahavishnu, not akosha. Akosha has its own `scripts/` directory but no `audit_orphans.py` in it. Run this from the mahavishnu repo root so its git-index scan covers the changed files.
Expected: no zero-caller symbols. `insert_spans_substrate` has a test caller; if the audit flags it, Task 5 (same branch) is the consumer — note that in the commit message rather than suppressing the finding.

- [ ] **Step 8: Commit**

```bash
cd /Users/les/Projects/akosha
git add akosha/storage/hot_store.py tests/unit/storage/test_insert_spans_substrate.py
git commit -m "feat(akosha): HotStore.insert_spans_substrate — batch INSERT with ON CONFLICT dedup

Writes validated rows to the oneiric-managed spans_substrate table.
Dedup resolves against the inline uq_span_identity UNIQUE CONSTRAINT
(trace_id, span_id); RETURNING gives the inserted count in one
round-trip, deduped is derived by subtraction.

ADR 017 holds: no akosha migration writes spans_substrate. The receiver
is a substrate client, not a substrate owner.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

#### Integration Contract (Task 4)
- **Triggered from**: Task 5's `_handle_batch`; Task 10's canary emitter; Task 3's installed oneiric dependency.
- **Returns to / updates**: `akosha/storage/hot_store.py` — new `_SPAN_COLUMNS` tuple + `insert_spans_substrate` method.
- **Demonstrable by**: `pytest tests/unit/storage/test_insert_spans_substrate.py -v` — 5 passing.
- **Rollback signal**: `test_partial_insert_mixed` returns `(2, 0)` instead of `(1, 1)` → `ON CONFLICT` is not matching the constraint (the `trace_id`/`span_id` ordering in the column list must match the constraint's).
- **Observability added**: none (return-value contract; the receiver owns the metrics).

---

## Task 5 (PR-A3): akosha — `OTLPReceiver` + lifespan wiring + port move

**Repo:** `/Users/les/Projects/akosha`. Same branch as Task 3/4. **This task also touches `/Users/les/Projects/mahavishnu`** for the collector port move.

**Files:**
- Create: `akosha/observability/otlp_receiver.py`
- Modify: `akosha/mcp/server.py:398-420` (lifespan) — add receiver lifecycle
- Modify: `mahavishnu/config/otel-collector-config.yaml` (`:4317` → `:14317`, `:4318` → `:14318`)
- Test: `akosha/tests/integration/test_otlp_receiver_e2e.py`
- Test: `akosha/tests/integration/test_substrate_lifespan_order.py`

**Interfaces:**
- Consumes: `set_shared_otel_receiver` / `clear_shared_services` (Task 3), `HotStore.insert_spans_substrate` (Task 4), `DuckdbHotStore.table_exists` (Task 2), `LifecycleError` (oneiric, `oneiric/core/lifecycle.py:25`), `FastMCPOpenTelemetryMiddleware(legacy_namespace=...)` (Task 1).
- Produces:
  - `OTLPReceiver(hot_store: HotStore, settings: Any | None = None)`
  - `MAX_BATCH_SIZE=512`, `MAX_RETRIES=3`, `BACKOFF_BASE_SECONDS=1.0`, `BACKOFF_MAX_SECONDS=8.0`, `QUEUE_MAX_DEPTH=2048`, `PROMETHEUS_PORT=9464`
  - `async start() -> None` (raises `LifecycleError("spans_substrate_missing")` if the table is absent)
  - `async stop() -> None`
  - `async _handle_batch(batch: ExportTraceServiceRequest) -> BatchResult`
  - `async run_canary_emitter(stop_event: asyncio.Event) -> None` — **stub body at this task** (Task 10 swaps it)
  - `async run_retention_sweep(stop_event: asyncio.Event) -> None`
  - Error classes: `ReceiverError`, `BatchRejected`, `RowValidationError`, `DLQWriteError`, `PreValidateException`
  - `BatchResult(ok, deduped, rejected, dlq_failed, errored)` dataclass
  - `def normalize_attributes(self, span: dict) -> dict`
  - `def pre_validate(self, span: dict) -> RowValidationError | None`

- [ ] **Step 1: Write the failing lifespan-order test**

Create `/Users/les/Projects/akosha/tests/integration/test_substrate_lifespan_order.py`:

```python
from __future__ import annotations

import pytest

from akosha.observability.otlp_receiver import OTLPReceiver
from akosha.storage.hot_store import HotStore
from oneiric.core.lifecycle import LifecycleError


@pytest.mark.asyncio
async def test_start_raises_when_substrate_absent(tmp_path) -> None:
    hs = HotStore(database_path=tmp_path / "bare.duckdb")
    await hs.initialize()
    # Drop the substrate to simulate "receiver started before DDL ran".
    hs.conn.execute("DROP TABLE spans_substrate")
    hs.conn.close()

    rx = OTLPReceiver(hot_store=hs)
    with pytest.raises(LifecycleError) as exc:
        await rx.start()
    assert "spans_substrate_missing" in str(exc.value)
```

- [ ] **Step 2: Write the failing e2e test**

Create `/Users/les/Projects/akosha/tests/integration/test_otlp_receiver_e2e.py`:

```python
from __future__ import annotations

import json

import pytest
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
from opentelemetry.proto.common.v1 import common_pb2
from opentelemetry.proto.trace.v1 import trace_pb2
from google.protobuf import struct_pb2

from akosha.observability.otlp_receiver import OTLPReceiver
from akosha.storage.hot_store import HotStore


def _attr(struct: struct_pb2.Struct, key: str, value) -> None:
    struct.attributes[key] = struct_pb2.Value()


def _span(span_id: str, trace_id: str = "t1") -> trace_pb2.Span:
    s = trace_pb2.Span(
        trace_id=bytes.fromhex(trace_id * 2),
        span_id=bytes.fromhex(span_id.ljust(32, "0")),
        name="test.span",
        kind=trace_pb2.Span.SPAN_KIND_INTERNAL,
        start_time_unix_nano=1_700_000_000_000_000_000,
        end_time_unix_nano=1_700_000_000_100_000_000,
    )
    for k in ("service.name", "service.namespace"):
        _attr(s.attributes, k, None)
    return s


@pytest.mark.asyncio
async def test_handle_batch_inserts(tmp_path) -> None:
    hs = HotStore(database_path=tmp_path / "e2e.duckdb")
    await hs.initialize()
    rx = OTLPReceiver(hot_store=hs)

    batch = trace_service_pb2.ExportTraceServiceRequest()
    rs = batch.resource_spans.add()
    rs.resource.attributes["service.name"] = "mahavishnu"
    rs.scope_spans[0].spans.append(_span("aa"))

    result = await rx._handle_batch(batch)
    assert result.ok == 1
    assert result.deduped == 0
    assert result.rejected == 0


@pytest.mark.asyncio
async def test_handle_batch_dedupes(tmp_path) -> None:
    hs = HotStore(database_path=tmp_path / "e2e2.duckdb")
    await hs.initialize()
    rx = OTLPReceiver(hot_store=hs)
    batch = trace_service_pb2.ExportTraceServiceRequest()
    rs = batch.resource_spans.add()
    rs.scope_spans[0].spans.append(_span("aa"))

    await rx._handle_batch(batch)
    second = await rx._handle_batch(batch)
    assert second.ok == 0
    assert second.deduped == 1


@pytest.mark.asyncio
async def test_normalize_attributes_assigns(tmp_path) -> None:
    """Spec §9.1: the normalizer must ASSIGN, not read-and-discard."""
    hs = HotStore(database_path=tmp_path / "norm.duckdb")
    await hs.initialize()
    rx = OTLPReceiver(hot_store=hs)
    out = rx.normalize_attributes({
        "attributes": {
            "task.class": "code_generation",
            "gen_ai.usage.input_tokens": 42,
            "weird.unknown.key": "kept-as-identity",
        }
    })
    assert out == {
        "task_class": "code_generation",
        "gen_ai_usage_input_tokens": 42,
        "weird_unknown_key": "kept-as-identity",
    }
```

The `_span` helper's attribute construction is a scaffold — OTLP span attributes arrive as `KeyValue` lists, not a dict. Read the proto shape (`opentelemetry.proto.trace.v1.trace_pb2.Span.attributes` is `repeated opentelemetry.proto.common.v1.common_pb2.KeyValue`) and write a correct builder. The assertion that matters is the `BatchResult` values, not the fixture's attribute encoding.

- [ ] **Step 3: Run both tests to verify they fail**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/integration/test_otlp_receiver_e2e.py tests/integration/test_substrate_lifespan_order.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'akosha.observability.otlp_receiver'`

- [ ] **Step 4: Implement `akosha/observability/otlp_receiver.py` — skeleton, errors, BatchResult**

Create the file with `from __future__ import annotations`, the oneiric logger (`oneiric.logging.get_logger` — akosha's convention, not stdlib `logging`), and:

```python
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from akosha.storage.hot_store import HotStore
from oneiric.core.lifecycle import LifecycleError

if TYPE_CHECKING:
    from opentelemetry.proto.collector.trace.v1 import (
        trace_service_pb2,
    )


class ReceiverError(Exception):
    """Base class for OTLPReceiver failures."""


class BatchRejected(ReceiverError):
    """The whole batch was rejected; nothing was inserted."""


class RowValidationError(ReceiverError):
    """One row failed validation and was quarantined to the DLQ."""

    def __init__(self, field: str | None, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}:{field}" + (f" ({detail})" if detail else ""))
        self.field = field
        self.reason = reason
        self.detail = detail


class DLQWriteError(ReceiverError):
    """Writing to the DLQ itself failed."""


class PreValidateException(ReceiverError):
    """The validator itself raised (as opposed to returning an error)."""


@dataclass
class BatchResult:
    ok: int
    deduped: int
    rejected: int
    dlq_failed: int
    errored: int
```

- [ ] **Step 5: Implement `OTLPReceiver.__init__`, `start`, `stop`, `table_exists` guard**

```python
class OTLPReceiver:
    MAX_BATCH_SIZE: int = 512
    MAX_RETRIES: int = 3
    BACKOFF_BASE_SECONDS: float = 1.0
    BACKOFF_MAX_SECONDS: float = 8.0
    QUEUE_MAX_DEPTH: int = 2048
    PROMETHEUS_PORT: int = 9464

    def __init__(self, hot_store: HotStore, settings: Any | None = None) -> None:
        self.hot_store = hot_store
        self.settings = settings
        self._running = False
        self.canary_state: CanaryState = CanaryState()

    async def start(self) -> None:
        """Bind listeners. Fail loud when the substrate is missing."""
        if not await self.hot_store.table_exists(
            self.hot_store.spans_substrate_table
        ):
            raise LifecycleError("spans_substrate_missing")
        await self._ensure_operational_tables()
        await self._bind_grpc()
        await self._bind_http()
        await self._start_prometheus()
        self._metric_receiver_started.inc()
        self._running = True

    async def stop(self) -> None:
        """Drain in-flight batches, close listeners."""
        self._running = False
        await self._close_listeners()
```

**Metrics are module-level, not per-instance.** Declare them at module scope in `otlp_receiver.py` against akosha's shared singleton registry, exactly as `akosha/observability/prometheus_metrics.py:117-137` does:

```python
from akosha.observability.prometheus_metrics import get_metrics_registry

_metric_receiver_started: Counter = Counter(
    name="telemetry_receiver_started_total",
    documentation="OTLP receiver start() calls that bound all listeners",
    registry=get_metrics_registry(),
)
```

Do **not** create metrics inside `__init__`. `get_metrics_registry()` returns a process-wide `CollectorRegistry`, so a second `OTLPReceiver` (the lifespan test constructs one, then the real server constructs another) would raise `ValueError: Duplicated timeseries in CollectorRegistry`. Module-level construction happens once at import.

`_bind_grpc`, `_bind_http`, `_start_prometheus`, `_close_listeners` are the listener plumbing; implement them against the OTLP gRPC + HTTP receivers with `prometheus_client.start_http_server(PROMETHEUS_PORT)`. The metric names must match the spec §11.3 contract verbatim (prefixed `telemetry_receiver_` when scraped by Prometheus).

`_ensure_operational_tables` creates the two akosha-owned operational tables inline. There is no migration framework in this repo — PR-A2 was dropped (see Deferred items) — so every table is created with `CREATE TABLE IF NOT EXISTS` at its point of first use, which is idempotent and runs on every boot:

```python
async def _ensure_operational_tables(self) -> None:
    """Create the DLQ and sweep-state tables.

    These are akosha's own operational tables, not substrate — ADR 017 puts
    `spans_substrate` in oneiric, but the DLQ and the sweep advisory lock are
    receiver state that belongs beside the receiver.
    """
    for ddl in (
        """
        CREATE TABLE IF NOT EXISTS _dlq_rows (
            rejected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reason      TEXT,
            field       TEXT,
            row_json    JSON,
            trace_id    TEXT,
            span_id     TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS _akosha_otel_receiver_state (
            component                    TEXT PRIMARY KEY,
            last_applied_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sweep_lock_expires_unix_nano BIGINT
        )
        """,
    ):
        await self.hot_store.conn.execute(ddl)
```

Without this, `_dlq_insert` raises `CatalogException: Table with name _dlq_rows does not exist` on the first rejected row — a failure that only appears once the receiver has already rejected something, which is the worst time to discover it.

`CanaryState` is defined in Task 10; at this task, declare the dataclass in `otlp_receiver.py` (it moves to `canary_watcher.py` in Task 10) so the attribute exists and the module imports:

```python
@dataclass
class CanaryState:
    last_canary_success_unix_nano: int | None = None
    last_canary_failure_unix_nano: int | None = None
    canary_writes_attempted_total: int = 0
    canary_writes_succeeded_total: int = 0
    canary_writes_failed_total: int = 0
    canary_writes_rejected_total: int = 0
    bridge_failed_total: int = 0
```

- [ ] **Step 6: Implement `normalize_attributes` and `pre_validate`**

```python
def dotted_to_underscore(key: str) -> str:
    return key.replace(".", "_")


def normalize_attributes(self, span: dict) -> dict:
    """Map semconv dotted keys to underscore form.

    Assignment, not read-and-discard — the spec's §9.1 revision exists
    because v3 used `out.get(...)`, which returned {} for every input.
    """
    out: dict[str, Any] = {}
    for k, v in span.get("attributes", {}).items():
        out[dotted_to_underscore(k)] = v
    return out


def pre_validate(self, span: dict) -> RowValidationError | None:
    if not span.get("service_name"):
        return RowValidationError(field="service_name", reason="not_null")
    if span.get("status_code") not in {
        "STATUS_CODE_UNSET", "STATUS_CODE_OK", "STATUS_CODE_ERROR", None
    }:
        return RowValidationError(field="status_code", reason="enum")
    if not span.get("span_id"):
        return RowValidationError(field="span_id", reason="not_null")
    if not span.get("start_time_unix_nano"):
        return RowValidationError(field="start_time_unix_nano", reason="not_null")
    return None
```

- [ ] **Step 7: Implement `_handle_batch`**

```python
async def _handle_batch(self, batch) -> BatchResult:
    clean: list[dict] = []
    dlq: list[tuple[RowValidationError, dict]] = []
    rejected = 0

    for span in self._iter_spans(batch):
        try:
            err = self.pre_validate(span)
        except Exception as exc:  # validator itself raised
            err = RowValidationError(
                field=None, reason="validator_threw", detail=repr(exc)
            )
            self._metric_row_rejected.labels(
                reason="validator_threw", field="none"
            ).inc()
        if err:
            dlq.append((err, span))
            rejected += 1
        else:
            clean.append(span)

    dlq_failed = 0
    if dlq:
        try:
            await self._dlq_insert(dlq)
        except Exception as exc:
            dlq_failed = len(dlq)
            for err, span in dlq:
                logger.error(
                    "dlq_write_failed reason=%s span_id=%s",
                    err.reason, span.get("span_id"),
                )
            self._metric_dlq_insert_failed.labels(
                reason="exception"
            ).inc(amount=dlq_failed)
            # Clean rows still proceed — a DLQ failure never zeroes throughput.

    ok = deduped = errored = 0
    if clean:
        try:
            ok, deduped = await self.hot_store.insert_spans_substrate(clean)
        except Exception as exc:
            errored = len(clean)
            self._metric_batch_inserted.labels(outcome="err").inc(amount=len(clean))
            logger.exception("batch_insert_failed")

    if not errored:
        if dlq_failed:
            outcome = "dlq_write_failed"
        elif rejected:
            outcome = "validation_failed"
        elif deduped and not ok:
            outcome = "dedup"
        elif ok and deduped:
            outcome = "partial"
        else:
            outcome = "ok"
        self._metric_batch_inserted.labels(outcome=outcome).inc(amount=len(batch.resource_spans))

    return BatchResult(
        ok=ok, deduped=deduped, rejected=rejected,
        dlq_failed=dlq_failed, errored=errored,
    )
```

`_iter_spans`, `_dlq_insert`, and the `_metric_*` attributes are part of this implementation. `_dlq_insert` writes `(rejected_at, reason, field, row_json, trace_id, span_id)` tuples to the `_dlq_rows` table created in Task 6. If Task 5 lands before Task 6, `_dlq_insert` must fail loudly on a missing table — that is the §6.2 behavior this plan wants tested, so leave it unguarded and let the `try/except` catch it.

**Note:** the `outcome` label set is spec §6.2's enum (`ok|dedup|partial|err|validation_failed|dlq_write_failed`). Keep all six label values declared even if some never increment (the spec pins `phase="copy"` as permanently dead for the same reason).

- [ ] **Step 8: Implement the two lifespan task stubs**

```python
async def run_canary_emitter(self, stop_event: asyncio.Event) -> None:
    """Stub at this task; Task 10 swaps the body for the real emitter.

    Present as a no-op so the lifespan compiles against the spec §6
    snippet. Between this task and Task 10, canary writes succeed
    silently and the sweep_retention_late alert correctly does NOT fire
    because sweep_first_started_unix_nano == 0.
    """
    return


async def run_retention_sweep(self, stop_event: asyncio.Event) -> None:
    """Sweep loop. Task 7 implements the body (cutoff, COPY, DELETE).

    Task 5 stubs it to keep the lifespan wiring testable before the
    settings keys exist.
    """
    return
```

- [ ] **Step 9: Wire the lifespan**

In `akosha/mcp/server.py`, inside the `@asynccontextmanager async def lifespan(server: Any)` (line ~398), after `hot_store.initialize()` and before the tool-registration step, add:

```python
    # v7: stop_event pinned at lifespan scope and passed explicitly to both
    # tasks. It is set() BEFORE the gather so the await stop_event.wait(...)
    # inside each task body wakes before Task.cancel() propagates.
    stop_event = asyncio.Event()
    receiver = OTLPReceiver(hot_store=hot_store, settings=settings)
    await receiver.start()
    set_shared_otel_receiver(receiver)
    canary_task = asyncio.create_task(
        receiver.run_canary_emitter(stop_event), name="receiver_canary_stub"
    )
    retention_task = asyncio.create_task(
        receiver.run_retention_sweep(stop_event), name="spans_retention_sweep"
    )
```

Add `OTLPReceiver` and `set_shared_otel_receiver` to the imports at the top of `server.py`.

In the teardown, immediately before the existing shutdown work:

```python
    stop_event.set()
    retention_task.cancel()
    canary_task.cancel()
    await asyncio.gather(canary_task, retention_task, return_exceptions=True)
    await receiver.stop()
```

- [ ] **Step 10: Run the lifespan tests**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/integration/test_substrate_lifespan_order.py tests/integration/test_otlp_receiver_e2e.py -v`
Expected: PASS.

- [ ] **Step 11: Move the collector ports**

In `/Users/les/Projects/mahavishnu/config/otel-collector-config.yaml`:

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:14317     # was 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:14318    # was 0.0.0.0:4318
```

Leave `otlp/claude`, `otlp/qwen`, `zipkin`, `jaeger`, `pprof` unchanged (spec §13.1: claude/qwen receivers are out of scope).

- [ ] **Step 12: Drain preflight (Review Focus #4)**

Before restarting the collector, run this to confirm nothing is still pointed at `:4318`:

```bash
cd /Users/les/Projects/mahavishnu
echo "=== dashboards ==="; git grep -n ':4318' -- 'monitoring/dashboards/' || echo "clean"
echo "=== collector configs ==="; git grep -n ':4318' -- 'config/*alloy*.yaml' 'config/otel-collector-config.yaml' || echo "clean"
echo "=== settings ==="; git grep -n '4318' -- 'settings/' || echo "clean"
```

For every hit, change it to `:14318`. Record each edited file in the PR description — the spec §13.1 consumer table names Grafana dashboards, Alloy relay templates, and the Bifrost gateway UI (operator-set at runtime per sub-spec B §4.4).

- [ ] **Step 13: Commit akosha and mahavishnu separately**

```bash
cd /Users/les/Projects/akosha
git add akosha/observability/otlp_receiver.py akosha/mcp/server.py \
  tests/integration/test_otlp_receiver_e2e.py \
  tests/integration/test_substrate_lifespan_order.py
git commit -m "feat(akosha): OTLPReceiver + lifespan wiring (PR-A3)

Binds :4317 gRPC and :4318 HTTP. start() raises LifecycleError
(\"spans_substrate_missing\") when spans_substrate is absent — fail loud,
never silent boot.

_handle_batch validates each row before INSERT; bad rows quarantine to
_dlq_rows; the DLQ write is itself wrapped so a DLQ failure never
zeroes throughput (clean rows still INSERT). normalize_attributes
ASSIGNS rather than reading-and-discarding, per spec §9.1.

run_canary_emitter and run_retention_sweep ship as stubs so the
lifespan compiles; Task 10 swaps the canary body and Task 7 the sweep body.

stop_event is pinned at lifespan scope and passed as an explicit
positional arg to both tasks, and is set() BEFORE the gather teardown.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

```bash
cd /Users/les/Projects/mahavishnu
git add config/otel-collector-config.yaml 'monitoring/dashboards/' 'settings/'
git commit -m "chore(mahavishnu): move collector off :4317/:4318 to :14317/:14318

The akosha OTLPReceiver takes :4317 (gRPC) and :4318 (HTTP). The
existing collector moves to :14317/:14318.

Consuming patterns (spec §13.1): Grafana bodai dashboards, Alloy relay
templates, settings-level OTLP_ENDPOINT. Drain preflight — git grep
for :4318 across dashboards/collector-configs/settings — must return
zero hits after this change, or producers still POSTing to :4318 drop
spans silently.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

#### Integration Contract (Task 5)
- **Triggered from**: `akosha mcp start` (lifespan); any OTLP producer POSTing to `:4318/v1/traces` or the gRPC `:4317`.
- **Returns to / updates**: `akosha/observability/otlp_receiver.py` (new module), `akosha/mcp/server.py` (lifespan), `mahavishnu/config/otel-collector-config.yaml` (ports).
- **Demonstrable by**: `pytest tests/integration/test_otlp_receiver_e2e.py tests/integration/test_substrate_lifespan_order.py -v` — all passing; `curl -fsS http://localhost:9464/metrics | grep telemetry_receiver_started`.
- **Rollback signal**: `LifecycleError("spans_substrate_missing")` at boot → Task 2's DDL did not land, or oneiric's version pin is stale. Verify with `akosha hot-store inspect --table spans_substrate` once Task 6's CLI lands, or `python -c "import duckdb; ..."` in the interim.
- **Observability added**: `telemetry_receiver_started_total`, `telemetry_receiver_batch_inserted{outcome}`, `telemetry_receiver_row_rejected{reason,field}`, `telemetry_receiver_dlq_insert_failed{reason}`, `telemetry_receiver_batch_size` histogram — all on `:9464`.

---

## Task 6: akosha — `admin otel retention` CLI group

**Repo:** `/Users/les/Projects/akosha`. Same branch.

**Files:**
- Modify: `akosha/cli.py` (add `admin_app` / `otel_app` / `retention_app`)
- Modify: `settings/akosha.yaml` (add the `otel.spans_substrate` block)
- Test: `akosha/tests/unit/cli/test_admin_otel_retention_cli.py`

**Interfaces:**
- Consumes: settings via akosha's oneiric-layered config (`get_config()` → `AkoshaConfig`, `akosha/config.py:608`); the `_dlq_rows` table created inline by Task 5's `OTLPReceiver.start()`.
- Produces:
  - `akosha admin otel retention manual-run [--retention-days N] [--dry-run|--apply --confirm PHRASE]`
  - `akosha admin otel retention sweep-once`
  - `akosha admin otel retention config set [--retention-days N] [--reload]`
  - `akosha admin otel retention cardinality-report`
  - Settings keys `otel.spans_substrate.{retention_days, retention_sweep_interval_hours, archival_target}` (canonical path, sibling of `otel.receiver`, NOT nested under it — spec §11.4)

- [ ] **Step 1: Write the failing test**

Create `/Users/les/Projects/akosha/tests/unit/cli/test_admin_otel_retention_cli.py`:

```python
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from akosha.cli import app

runner = CliRunner()


def test_retention_help_lists_all_four_commands() -> None:
    res = runner.invoke(app, ["admin", "otel", "retention", "--help"])
    assert res.exit_code == 0
    for cmd in ("manual-run", "sweep-once", "config", "cardinality-report"):
        assert cmd in res.stdout


def test_manual_run_defaults_to_dry_run() -> None:
    res = runner.invoke(app, ["admin", "otel", "retention", "manual-run"])
    assert res.exit_code == 0
    assert "DRY RUN" in res.stdout.upper()


def test_cardinality_report_runs() -> None:
    res = runner.invoke(app, ["admin", "otel", "retention", "cardinality-report"])
    assert res.exit_code == 0


def test_config_set_is_dry_run_by_default() -> None:
    res = runner.invoke(
        app,
        ["admin", "otel", "retention", "config", "set", "--retention-days", "14"],
    )
    assert res.exit_code == 0
    assert "DRY RUN" in res.stdout.upper()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/unit/cli/test_admin_otel_retention_cli.py -v`
Expected: FAIL with `ExitCode: 2` (`No such command 'admin'`)

- [ ] **Step 3: Add the settings block**

In `settings/akosha.yaml`, add at top level (sibling of `otel.receiver`, **not** nested under it):

```yaml
otel:
  receiver:
    known_mcp_servers:
      - "mahavishnu"
      - "akosha"
      - "session-buddy"
      - "oneiric"
      - "crackerjack"
      - "bifrost-mcp"
  spans_substrate:
    retention_days: 30
    retention_sweep_interval_hours: 6
    archival_target: null
```

If an `otel:` block already exists, merge into it rather than creating a second one. The `known_mcp_servers` roster is Task 9's input; it is declared here so the settings shape is in one place.

- [ ] **Step 4: Implement the retention CLI group**

In `akosha/cli.py`:

```python
ARCHIVAL_TARGET_RE = re.compile(
    r"^(?:"
    r"s3://[a-z0-9][a-z0-9.\-]{1,62}/.*"
    r"|"
    r"(?:/var/log/akosha/|/var/lib/akosha/|/data/akosha/|/srv/akosha/"
    r"|/opt/akosha/|/Users/[A-Za-z0-9_.\- ]+/Library/Application Support/akosha/"
    r"|/Users/[A-Za-z0-9_.\- ]+/\.local/share/akosha/"
    r"|/home/[A-Za-z0-9_.\- ]+/\.local/share/akosha/"
    r")[\w./\-]*\.(?:parquet|csv|json)"
    r")$"
)

BLESSED_CONFIRM_PHRASES: dict[int, str] = {
    30: "delete rows older than 30 days",
    60: "delete rows older than 60 days",
    90: "delete rows older than 90 days",
}


def _retention_settings() -> Any:
    from akosha.config import get_settings
    return get_config().otel.spans_substrate


def _validate_archival_target(target: str | None) -> None:
    """Fail loud at settings-load with the four valid roots named.

    Review Focus #5: the operator's 3am fix must not be a guess.
    """
    if not target:
        return
    if not ARCHIVAL_TARGET_RE.match(target):
        raise ValueError(
            f"archival_target {target!r} is not a valid cold-sink path.\n"
            "Valid roots (see akosha/storage/path_resolver.py):\n"
            "  s3://<bucket>/<key>.{parquet,csv,json}\n"
            "  /var/log/akosha/…  /var/lib/akosha/…  /data/akosha/…\n"
            "  /srv/akosha/…     /opt/akosha/…\n"
            "  ~/Library/Application Support/akosha/…  (macOS)\n"
            "  ~/.local/share/akosha/…               (Linux)\n"
            "Filesystem targets must end in .parquet, .csv, or .json."
        )


admin_app = typer.Typer(help="operator/admin subcommands")
otel_app = typer.Typer(help="OpenTelemetry substrate commands")
retention_app = typer.Typer(help="spans_substrate retention sweep")


@retention_app.command("manual-run")
def retention_manual_run(
    retention_days: int = typer.Option(..., "--retention-days", help="days of history to keep"),
    dry_run: bool = typer.Option(True, "--dry-run/--apply", help="print SQL + preview; do not execute"),
    apply: bool = typer.Option(False, "--apply", help="actually execute (requires --confirm)"),
    confirm: str = typer.Option("", "--confirm", help="typed-phrase confirmation"),
) -> None:
    """Run the retention sweep manually. Default is dry-run."""
    _validate_archival_target(_retention_settings().archival_target)
    cutoff_ns = time.time_ns() - retention_days * 86_400 * 1_000_000_000
    sql = (
        f"DELETE FROM spans_substrate WHERE received_at_unix_nano < {cutoff_ns}"
    )
    if dry_run and not apply:
        typer.echo("DRY RUN — no rows deleted.")
        typer.echo(f"SQL: {sql}")
        typer.echo(
            "Run `akosha hot-store exec \"SELECT COUNT(*) FROM spans_substrate "
            f"WHERE received_at_unix_nano < {cutoff_ns}\"` for the row count."
        )
        return
    if apply and confirm != BLESSED_CONFIRM_PHRASES.get(retention_days):
        typer.echo(
            f"--confirm must be exactly: {BLESSED_CONFIRM_PHRASES.get(retention_days, 'delete rows older than N days')!r}"
        )
        raise typer.Exit(code=1)
    _execute_sweep(retention_days)


@retention_app.command("sweep-once")
def retention_sweep_once() -> None:
    """Run one sweep cycle now, bypassing the wait interval."""
    from akosha.observability.otlp_receiver import OTLPReceiver
    from akosha.storage.hot_store import HotStore
    s = _retention_settings()
    hs = HotStore(database_path=_resolve_hot_store_path())
    OTLPReceiver(hot_store=hs, settings=s).run_retention_sweep_once(s)


@retention_app.command("config set")
def retention_config_set(
    retention_days: int | None = typer.Option(None, "--retention-days", help="override retention_days"),
    reload: bool = typer.Option(False, "--reload", help="re-read settings after change"),
) -> None:
    """Operator-facing settings override (dry-run by default)."""
    current = _retention_settings()
    proposed = retention_days if retention_days is not None else current.retention_days
    typer.echo("DRY RUN — no file written.")
    typer.echo(f"otel.spans_substrate.retention_days: {current.retention_days} -> {proposed}")
    typer.echo("Re-run with --apply to write settings/akosha.yaml.")


@retention_app.command("cardinality-report")
def retention_cardinality_report() -> None:
    """Print row count, retention horizon, and per-service breakdown."""
    import duckdb
    con = duckdb.connect(_resolve_hot_store_path(), read_only=True)
    total = con.execute("SELECT COUNT(*) FROM spans_substrate").fetchone()[0]
    typer.echo(f"total rows: {total}")
    typer.echo("by service_name (top 20):")
    for name, cnt in con.execute(
        "SELECT service_name, COUNT(*) FROM spans_substrate "
        "GROUP BY service_name ORDER BY COUNT(*) DESC LIMIT 20"
    ).fetchall():
        typer.echo(f"  {name}: {cnt}")
    con.close()


otel_app.add_typer(retention_app, name="retention")
admin_app.add_typer(otel_app, name="otel")
app.add_typer(admin_app, name="admin")
```

`_execute_sweep` is Task 7's body — extract the sweep logic into a module-level `async def run_sweep_once(settings)` on `OTLPReceiver` and call it here. To keep this task independently testable, define `_execute_sweep(retention_days)` in this task as a thin wrapper that opens the HotStore and calls `OTLPReceiver.run_retention_sweep_once`; Task 7 fills in that method's real body. If the method does not exist yet, stub it in Task 5 alongside the other stubs.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/unit/cli/test_admin_otel_retention_cli.py -v`
Expected: PASS — 4 tests.

- [ ] **Step 6: Verify the CLI registers without shadowing**

Run: `cd /Users/les/Projects/akosha && .venv/bin/akosha --help 2>&1 | grep -E "admin|migrations|mcp"`
Expected: all three top-level groups present, and `data-migrate` still present under its original name.

- [ ] **Step 7: Commit**

```bash
cd /Users/les/Projects/akosha
git add akosha/cli.py settings/akosha.yaml tests/unit/cli/test_admin_otel_retention_cli.py
git commit -m "feat(akosha): admin otel retention CLI group (spec §11.4a)

Ships admin/otel/retention Typer sub-apps plus the canonical
otel.spans_substrate settings block. The retention/canary/heartbeat
runbooks reference these commands; without them operators hit
\"command not found\" at 3am.

All mutating commands are dry-run by default; --apply plus a typed
--confirm phrase is required to execute. The cutoff_ns is computed
inside the process so a fat-fingered shell arithmetic cannot drop hot
data.

archival_target validates at settings-load against ARCHIVAL_TARGET_RE
and the error message names the four valid storage roots (Review Focus
#5: the 3am fix must not be a guess).

otel.spans_substrate is a SIBLING of otel.receiver, not nested under
it — the sweep body reads settings.spans_substrate.*.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

#### Integration Contract (Task 6)
- **Triggered from**: operator shell at 3am following a runbook in spec §11.1.5/6/7; the `otel.spans_substrate` settings block read by Task 7's sweep.
- **Returns to / updates**: `akosha/cli.py` (3 new Typer sub-apps), `settings/akosha.yaml` (`otel.spans_substrate` block).
- **Demonstrable by**: `pytest tests/unit/cli/test_admin_otel_retention_cli.py -v` — 4 passing; `akosha admin otel retention cardinality-report` prints a row count.
- **Rollback signal**: `akosha --help` no longer lists `data-migrate` → the new `migrations` group shadowed the pre-existing Click group (spec §11.4a namespace safety).
- **Observability added**: none (operator-surface commands; the sweep they invoke emits the metrics).

---

## Task 7 (PR-A3 follow-on): akosha — retention sweep body + advisory lock + archival

**Repo:** `/Users/les/Projects/akosha`. Same branch.

**Files:**
- Modify: `akosha/observability/otlp_receiver.py` (sweep body, `run_retention_sweep_once`, `_acquire_sweep_lock`)
- Test: `akosha/tests/integration/test_spans_substrate_retention_sweep.py`

**Interfaces:**
- Consumes: `ARCHIVAL_TARGET_RE` and `_retention_settings` (Task 6), `HotStore` (Task 4), `_dlq_rows` (created inline in Task 5).
- Produces:
  - `async OTLPReceiver.run_retention_sweep_once(settings) -> int` (deleted count)
  - `async OTLPReceiver.run_retention_sweep(stop_event)` — real body
  - `async OTLPReceiver._acquire_sweep_lock(ttl_seconds) -> bool`
  - Metrics `telemetry_receiver_sweep_first_started_unix_nano`, `telemetry_receiver_sweep_last_completed_unix_nano`, `telemetry_receiver_retention_sweep_failed{phase,reason}`, `telemetry_receiver_archival_failed{reason}`

- [ ] **Step 1: Write the failing test**

Create `/Users/les/Projects/akosha/tests/integration/test_spans_substrate_retention_sweep.py`:

```python
from __future__ import annotations

import time

import pytest

from akosha.observability.otlp_receiver import OTLPReceiver
from akosha.storage.hot_store import HotStore

DAY_NS = 86_400 * 1_000_000_000


def _seed(hs: HotStore, span_id: str, age_days: int) -> None:
    now = time.time_ns()
    hs.conn.execute(
        "INSERT INTO spans_substrate (span_id, trace_id, service_name, "
        "service_namespace, span_name, start_time_unix_nano, "
        "received_at_unix_nano, attributes, resource) "
        "VALUES (?, ?, 'svc', 'bodai', 'n', ?, ?, '{}', '{}')",
        [span_id, f"t-{span_id}", now, now - age_days * DAY_NS],
    )


class _S:
    retention_days = 30
    retention_sweep_interval_hours = 6
    archival_target = None


@pytest.fixture
async def rx(tmp_path):
    hs = HotStore(database_path=tmp_path / "sweep.duckdb")
    await hs.initialize()
    return OTLPReceiver(hot_store=hs, settings=_S())


@pytest.mark.asyncio
async def test_sweep_deletes_rows_older_than_retention(rx: OTLPReceiver) -> None:
    _seed(rx.hot_store, "old", 40)
    _seed(rx.hot_store, "fresh", 1)
    deleted = await rx.run_retention_sweep_once(_S())
    assert deleted == 1
    remaining = rx.hot_store.conn.execute(
        "SELECT span_id FROM spans_substrate"
    ).fetchall()
    assert remaining == [("fresh",)]


@pytest.mark.asyncio
async def test_sweep_uses_received_at_not_start_time(rx: OTLPReceiver) -> None:
    """Cardinal rule: a span with an ancient producer start_time but a
    recent server receive time must SURVIVE."""
    now = time.time_ns()
    rx.hot_store.conn.execute(
        "INSERT INTO spans_substrate (span_id, trace_id, service_name, "
        "service_namespace, span_name, start_time_unix_nano, "
        "received_at_unix_nano, attributes, resource) "
        "VALUES ('skew', 't-skew', 'svc', 'bodai', 'n', ?, ?, '{}', '{}')",
        [now - 400 * DAY_NS, now],
    )
    assert await rx.run_retention_sweep_once(_S()) == 0
    rows = rx.hot_store.conn.execute(
        "SELECT span_id FROM spans_substrate"
    ).fetchall()
    assert rows == [("skew",)]


@pytest.mark.asyncio
async def test_dlq_rows_are_swept(rx: OTLPReceiver) -> None:
    rx.hot_store.conn.execute(
        "CREATE TABLE IF NOT EXISTS _dlq_rows (rejected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, reason TEXT, field TEXT, row_json JSON, trace_id TEXT, span_id TEXT)"
    )
    rx.hot_store.conn.execute(
        "INSERT INTO _dlq_rows (rejected_at, reason, row_json) "
        "VALUES (now() - INTERVAL '48 hours', 'not_null', '{}')"
    )
    await rx.run_retention_sweep_once(_S())
    n = rx.hot_store.conn.execute("SELECT COUNT(*) FROM _dlq_rows").fetchone()[0]
    assert n == 0
```

- [ ] **Step 2: Write the archival + COPY-failure test**

Append to the same file:

```python
@pytest.mark.asyncio
async def test_copy_failure_skips_delete(rx: OTLPReceiver, tmp_path) -> None:
    """Review Focus (spec §15 v5): a cold-sink error must never destroy
    the rows that failed to archive."""
    _seed(rx.hot_store, "old1", 40)
    _seed(rx.hot_store, "old2", 45)

    class _BadTarget:
        retention_days = 30
        retention_sweep_interval_hours = 6
        archival_target = "/data/akosha/archives/spans.parquet"  # valid regex, unwritable

    before = rx.hot_store.conn.execute(
        "SELECT COUNT(*) FROM spans_substrate"
    ).fetchone()[0]
    deleted = await rx.run_retention_sweep_once(_BadTarget())
    after = rx.hot_store.conn.execute(
        "SELECT COUNT(*) FROM spans_substrate"
    ).fetchone()[0]

    assert before == 2
    if deleted == 0:
        # COPY failed -> DELETE skipped -> both rows survive.
        assert after == 2, "COPY failure must not delete unarchived rows"
    else:
        # COPY succeeded (CI may be able to write /data) -> rows archived+deleted.
        assert after == 0
```

The test is written to pass in both worlds; the *important* assertion is the `deleted == 0 ⇒ after == 2` branch, which is the data-loss guard. Run it twice — once with the target writable, once with it made read-only — to exercise both branches.

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/integration/test_spans_substrate_retention_sweep.py -v`
Expected: FAIL with `AttributeError: 'OTLPReceiver' object has no attribute 'run_retention_sweep_once'`

- [ ] **Step 4: Implement the advisory lock (Review Focus #3)**

In `otlp_receiver.py`:

```python
async def _acquire_sweep_lock(ttl_seconds: int = 21_600) -> bool:
    """Best-effort single-writer lock for the retention sweep.

    DuckDB takes a whole-file write lock; two pods sweeping the same file
    means the loser's DELETE raises an IO error and (per spec §15 v5) the
    sweep is the only thing keeping the table from running away. This lock
    is a marker row with a TTL, refreshed by the holder each cycle — NOT a
    transaction-level lock, because the sweep spans multiple statements.

    Returns True when this process holds the lock. A stale lock (older
    than ttl_seconds) is reclaimed; a fresh lock held by another pod
    returns False and this pod skips the cycle.
    """
    now = time.time()
    cutoff = now - ttl_seconds
    async with self.hot_store._lock:
        self.hot_store.conn.execute(
            "DELETE FROM _akosha_otel_receiver_state "
            "WHERE component = 'sweep_lock' AND last_applied_at < ?",
            [cutoff],
        )
        existing = self.hot_store.conn.execute(
            "SELECT component FROM _akosha_otel_receiver_state "
            "WHERE component = 'sweep_lock'"
        ).fetchone()
        if existing is not None:
            return False
        self.hot_store.conn.execute(
            "INSERT INTO _akosha_otel_receiver_state "
            "(component, schema_version, last_applied_at) VALUES ('sweep_lock', 1, ?)",
            [now],
        )
    return True


async def _release_sweep_lock(self) -> None:
    async with self.hot_store._lock:
        self.hot_store.conn.execute(
            "DELETE FROM _akosha_otel_receiver_state WHERE component = 'sweep_lock'"
        )
```

`_akosha_otel_receiver_state.last_applied_at` is `TIMESTAMP` per the DDL Task 5 creates inline; the parameter above passes a float epoch. Change the parameter to a `datetime` (`datetime.fromtimestamp(now, tz=UTC)`) to match the column type, or store the lock's own `sweep_lock_expires_unix_nano BIGINT` column — **preferred**, because a TIMESTAMP comparison against a marker row conflates "when the lock was taken" with "when this component last recorded state", which are different facts. Add the column to the inline `CREATE TABLE` in Task 5:

```sql
-- In OTLPReceiver.start(), alongside the other inline DDL:
CREATE TABLE IF NOT EXISTS _akosha_otel_receiver_state (
    component                   TEXT PRIMARY KEY,
    last_applied_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sweep_lock_expires_unix_nano BIGINT
);
```

DuckDB supports `ALTER TABLE ADD COLUMN` without constraints, but that is irrelevant here: there is no migration framework (see Deferred items — PR-A2 was dropped), so every table this plan needs is created with `CREATE TABLE IF NOT EXISTS` at the point of first use. Inline DDL is idempotent and runs on every boot, so there is nothing to sequence.

- [ ] **Step 5: Implement `run_retention_sweep_once`**

```python
async def run_retention_sweep_once(self, settings: Any) -> int:
    """One sweep cycle. Returns deleted row count.

    Ordering is COPY-then-DELETE: an archival failure sets
    archival_succeeded=False and SKIPS the DELETE, so a cold-sink outage
    never destroys data.
    """
    import random

    sweep_started = time.time_ns()
    if self._sweep_first_started_unix_nano == 0:
        self._sweep_first_started_unix_nano = sweep_started
        self._metric_sweep_first_started.set(sweep_started)

    cutoff_ns = sweep_started - int(settings.retention_days) * 86_400 * 1_000_000_000
    deleted = 0
    archival_succeeded = True

    try:
        target = getattr(settings, "archival_target", None)
        if target:
            try:
                # v6: COPY path is INLINED, not parameterized — DuckDB (2.0.0-dev)
                # rejects COPY (…) TO ? with
                # "INTERNAL Error: Unsupported parameter type for filename".
                # The path is regex-validated at settings-load (Task 6), so
                # only safe paths reach here.
                self.hot_store.conn.execute(
                    f"COPY (SELECT * FROM spans_substrate "
                    f"WHERE received_at_unix_nano < {cutoff_ns}) TO '{target}'"
                )
            except Exception as exc:
                archival_succeeded = False
                self._metric_archival_failed.labels(
                    reason=type(exc).__name__
                ).inc()
                logger.exception("archival_failed target=%s", target)

        if archival_succeeded:
            result = self.hot_store.conn.execute(
                f"DELETE FROM spans_substrate WHERE received_at_unix_nano < {cutoff_ns}"
            )
            # v6: rowcount, NOT fetchone()[0] — a DML cursor raises TypeError
            # on fetchone()[0] in DuckDB (2.0.0-dev).
            deleted = result.rowcount
            self._metric_sweep_deleted.inc(amount=deleted)
        # else: DELETE SKIPPED. Rows stay; the next cycle retries archival.

        # DLQ retention: 24h.
        self.hot_store.conn.execute(
            "DELETE FROM _dlq_rows WHERE rejected_at < now() - INTERVAL '24 hours'"
        )
    except Exception as exc:
        self._metric_retention_sweep_failed.labels(
            phase="delete", reason=type(exc).__name__
        ).inc()
        logger.exception("retention_sweep_failed phase=delete")

    if not archival_succeeded:
        self._metric_retention_sweep_failed.labels(
            phase="copy", reason="see_archival_failed"
        ).inc(amount=0)  # label shape preserved; never increments (spec §15 v5)

    self._metric_sweep_last_completed.set(time.time_ns())
    return deleted
```

The `phase="copy"` increment with `amount=0` is deliberate: it keeps the label shape stable for dashboards without ever producing a non-zero value, per the spec's "permanently dead" decision.

- [ ] **Step 6: Implement the loop body**

Replace the `run_retention_sweep` stub from Task 6:

```python
async def run_retention_sweep(self, stop_event: asyncio.Event) -> None:
    import random

    interval = int(
        self.settings.retention_sweep_interval_hours
    ) * 3600 if self.settings else 6 * 3600
    while not stop_event.is_set():
        try:
            await stop_event.wait(interval)
        except asyncio.CancelledError:
            raise
        if stop_event.is_set():
            return
        # 0-60s jitter so multiple pods do not all wake on the same second.
        # asyncio.sleep is cancelled by Task.cancel() at the next await point,
        # so the jitter does not block graceful shutdown.
        await asyncio.sleep(random.uniform(0, 60))

        if not await self._acquire_sweep_lock():
            logger.info("sweep_skipped reason=lock_held_by_other_pod")
            continue
        try:
            await self.run_retention_sweep_once(self.settings)
        finally:
            await self._release_sweep_lock()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/integration/test_spans_substrate_retention_sweep.py -v`
Expected: PASS — 5 tests.

- [ ] **Step 8: Verify the lock actually serializes**

Append to the test file:

```python
@pytest.mark.asyncio
async def test_sweep_lock_is_exclusive(rx: OTLPReceiver) -> None:
    first = await rx._acquire_sweep_lock()
    second = await rx._acquire_sweep_lock()
    assert first is True
    assert second is False
    await rx._release_sweep_lock()
    assert await rx._acquire_sweep_lock() is True
```

- [ ] **Step 9: Commit**

```bash
cd /Users/hes/Projects/akosha
git add akosha/observability/otlp_receiver.py \
  tests/integration/test_spans_substrate_retention_sweep.py
git commit -m "feat(akosha): retention sweep body + advisory lock (spec §8.2)

Sweep filters on received_at_unix_nano (server-populated), never
start_time_unix_nano (producer clock, drift-prone) — the cardinal rule.

COPY-then-DELETE ordering: an archival failure sets
archival_succeeded=False and SKIPS the DELETE, so a cold-sink outage
(NFS, S3 IAM, ENOSPC) never destroys unarchived rows. The COPY path is
inlined because DuckDB (2.0.0-dev) rejects COPY (…) TO ?.

rowcount, not fetchone()[0] — a DML cursor raises TypeError on
fetchone()[0], which per spec §15 v6 made every sweep increment
retention_sweep_failed{phase=\"delete\"} as a false alarm.

Adds a TTL advisory lock (marker row in _akosha_otel_receiver_state)
so two pods do not race the same DuckDB file — the loser previously died
on an IO error and its failure was invisible. Resolves the deferred
\"sweep leader-election\" item from the v6 review.

Liveness: sweep_first_started_unix_nano is set once and never reset, so
operators can distinguish \"never ran on this pod\" from \"frozen on
archival\".

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

#### Integration Contract (Task 7)
- **Triggered from**: the lifespan task created in Task 5; `akosha admin otel retention sweep-once` (Task 6's CLI).
- **Returns to / updates**: `akosha/observability/otlp_receiver.py` — `run_retention_sweep` body, `run_retention_sweep_once`, `_acquire_sweep_lock`, `_release_sweep_lock`.
- **Demonstrable by**: `pytest tests/integration/test_spans_substrate_retention_sweep.py -v` — 6 passing; `curl -fsS http://localhost:9464/metrics | grep telemetry_receiver_sweep_` shows both gauges advancing.
- **Rollback signal**: `test_sweep_uses_received_at_not_start_time` deletes the `skew` row → the sweep body filtered on `start_time_unix_nano`; re-read the cutoff SQL.
- **Observability added**: `telemetry_receiver_sweep_first_started_unix_nano`, `telemetry_receiver_sweep_last_completed_unix_nano`, `telemetry_receiver_retention_sweep_failed{phase,reason}`, `telemetry_receiver_archival_failed{reason}`, `telemetry_receiver_sweep_deleted_total`.

---

## Task 8 (PR-A5): akosha — heartbeat watcher

**Repo:** `/Users/les/Projects/akosha`. Same branch.

**Files:**
- Create: `akosha/observability/heartbeat_watcher.py`
- Modify: `akosha/mcp/server.py` (register the `known_mcp_servers` feed in `/health`)
- Test: `akosha/tests/integration/test_heartbeat_watcher_e2e.py`

**Interfaces:**
- Consumes: `otel.receiver.known_mcp_servers` settings (Task 7), `HotStore` (Task 5), `HealthFeedState` from `mcp_common.health.feed` (confirmed at `mcp_common/health/feed.py:80`).
- Produces:
  - `KNOWN_MCP_SERVERS: list[str]` (module-level roster, populated at lifespan)
  - `async check_once(hot_store: HotStore) -> HeartbeatVerdict`
  - `HeartbeatVerdict` dataclass: `(service_name, status: Literal["ok","query_empty","query_threw"], consecutive_absences: int)`
  - `/health` feeds `known_mcp_servers` (kwarg-only `HealthFeedState`)

- [ ] **Step 1: Write the failing test**

Create `/Users/les/Projects/akosha/tests/integration/test_heartbeat_watcher_e2e.py`:

```python
from __future__ import annotations

import pytest

from akosha.observability import heartbeat_watcher as hw
from akosha.storage.hot_store import HotStore


@pytest.fixture(autouse=True)
def _reset_roster():
    hw.KNOWN_MCP_SERVERS.clear()
    yield
    hw.KNOWN_MCP_SERVERS.clear()


@pytest.fixture
async def hs(tmp_path):
    s = HotStore(database_path=tmp_path / "hb.duckdb")
    await s.initialize()
    return s


@pytest.mark.asyncio
async def test_query_empty_when_no_rows(hs: HotStore) -> None:
    hw.KNOWN_MCP_SERVERS[:] = ["mahavishnu"]
    verdict = await hw.check_once(hs)
    assert verdict.status == "query_empty"
    assert verdict.consecutive_absences == 1


@pytest.mark.asyncio
async def test_ok_when_recent_span_exists(hs: HotStore) -> None:
    import time
    now = time.time_ns()
    hs.conn.execute(
        "INSERT INTO spans_substrate (span_id, trace_id, service_name, "
        "service_namespace, span_name, start_time_unix_nano, "
        "received_at_unix_nano, attributes, resource) "
        "VALUES ('s1','t1','mahavishnu','bodai','n',?,?,'{}','{}')", [now, now]
    )
    hw.KNOWN_MCP_SERVERS[:] = ["mahavishnu"]
    verdict = await hw.check_once(hs)
    assert verdict.status == "ok"
    assert verdict.consecutive_absences == 0


@pytest.mark.asyncio
async def test_query_threw_suppresses_p0a(hs: HotStore) -> None:
    """Spec §11.1: query failure is tracked separately and does NOT
    count toward P0-A (absence)."""
    hw.KNOWN_MCP_SERVERS[:] = ["mahavishnu"]
    hs.conn.close()
    verdict = await hw.check_once(hs)
    assert verdict.status == "query_threw"


@pytest.mark.asyncio
async def test_empty_roster_is_p0(hs: HotStore) -> None:
    hw.KNOWN_MCP_SERVERS.clear()
    verdict = await hw.check_once(hs)
    assert verdict.status == "empty_roster"


@pytest.mark.asyncio
async def test_two_consecutive_absences_escalate(hs: HotStore) -> None:
    hw.KNOWN_MCP_SERVERS[:] = ["mahavishnu"]
    await hw.check_once(hs)
    verdict = await hw.check_once(hs)
    assert verdict.consecutive_absences == 2
    assert verdict.p0a is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/integration/test_heartbeat_watcher_e2e.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'akosha.observability.heartbeat_watcher'`

- [ ] **Step 3: Implement the heartbeat watcher**

Create `akosha/observability/heartbeat_watcher.py`:

```python
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from akosha.storage.hot_store import HotStore

# Spec §11: the roster is a module-level list[str], NOT a HealthFeedState
# field. HealthFeedState is a kwarg-only dataclass in mcp_common.health.feed;
# known_mcp_servers is not a constructor argument there.
KNOWN_MCP_SERVERS: list[str] = []

WINDOW_SECONDS: int = 60
ABSENCE_THRESHOLD: int = 2

_consecutive_absences: dict[str, int] = {}


@dataclass
class HeartbeatVerdict:
    service_name: str
    status: Literal["ok", "query_empty", "query_threw", "empty_roster"]
    consecutive_absences: int = 0
    p0a: bool = False


async def check_once(hot_store: HotStore) -> HeartbeatVerdict:
    """One heartbeat cycle over the roster.

    Distinguishes query_empty (counts toward P0-A) from query_threw
    (does NOT count toward P0-A; tracked separately per spec §11.1).
    """
    if not KNOWN_MCP_SERVERS:
        return HeartbeatVerdict(service_name="", status="empty_roster", p0a=True)

    cutoff_ns = time.time_ns() - WINDOW_SECONDS * 1_000_000_000
    worst = HeartbeatVerdict(service_name="", status="ok")

    for name in KNOWN_MCP_SERVERS:
        try:
            row = hot_store.conn.execute(
                "SELECT 1 FROM spans_substrate "
                "WHERE service_name = ? AND received_at_unix_nano > ? LIMIT 1",
                [name, cutoff_ns],
            ).fetchone()
        except Exception:
            # query_threw: suppress P0-A for this service. A DB failure is
            # an observability outage, not proof the producer is dead.
            return HeartbeatVerdict(service_name=name, status="query_threw")

        if row is None:
            n = _consecutive_absences.get(name, 0) + 1
            _consecutive_absences[name] = n
            v = HeartbeatVerdict(
                service_name=name,
                status="query_empty",
                consecutive_absences=n,
                p0a=n >= ABSENCE_THRESHOLD,
            )
            if v.p0a and not worst.p0a:
                worst = v
        else:
            _consecutive_absences[name] = 0

    return worst
```

- [ ] **Step 4: Populate the roster at lifespan startup**

In `akosha/mcp/server.py`, inside the lifespan after `hot_store.initialize()`:

```python
    from akosha.observability import heartbeat_watcher
    from akosha.config import get_settings
    heartbeat_watcher.KNOWN_MCP_SERVERS[:] = list(
        get_config().otel.receiver.known_mcp_servers or []
    )
```

- [ ] **Step 5: Register the `known_mcp_servers` health feed**

In `register_health_endpoint()` (akosha's `bootstrap.py` equivalent), add a `known_mcp_servers` key. The construction is **kwarg-only** per spec §15 v7:

```python
from mcp_common.health.feed import HealthFeedState

checks["known_mcp_servers"] = {
    "entities_count": len(heartbeat_watcher.KNOWN_MCP_SERVERS),
    "last_updated_timestamp": boot_unix_time,
    "cycles_total": 1,
    "errors_total": 0,
    "last_error_at": None,
    "ingester_running": True,
}
```

If the aggregator requires a `HealthFeedState` instance rather than a dict, construct it as:

```python
HealthFeedState(
    entities_count=len(heartbeat_watcher.KNOWN_MCP_SERVERS),
    last_updated_timestamp=boot_unix_time,
    cycles_total=1,
    errors_total=0,
    last_error_at=None,
    ingester_running=True,
)
```

`HealthFeedState` is a plain dataclass with defaults (`mcp_common/health/feed.py:103`), so keyword construction works. Do **not** call `HealthFeedState("known_mcp_servers", ...)` — that is the positional-constructor error the v7 review caught.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/integration/test_heartbeat_watcher_e2e.py -v`
Expected: PASS — 5 tests.

- [ ] **Step 7: Run the akosha health suite for regressions**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/ -k "health" -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
cd /Users/les/Projects/akosha
git add akosha/observability/heartbeat_watcher.py akosha/mcp/server.py \
  tests/integration/test_heartbeat_watcher_e2e.py
git commit -m "feat(akosha): heartbeat watcher with query-empty/query-threw split

P0-A fires after 2 consecutive 60s windows of absence. query_empty
counts toward P0-A; query_threw does NOT (a DB failure is an
observability outage, not proof the producer is dead) and is tracked
separately per spec §11.1.

An empty roster is itself a P0 — it catches a registry wipe and a
substrate lift that removed every entry.

KNOWN_MCP_SERVERS is a module-level list[str], not a HealthFeedState
field; HealthFeedState is kwarg-only (mcp_common/health/feed.py:103).
Positional construction raises TypeError.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

#### Integration Contract (Task 8)
- **Triggered from**: the akosha lifespan (roster population); a 60s heartbeat loop (wire it into the lifespan alongside the sweep task, or an existing periodic task).
- **Returns to / updates**: `akosha/observability/heartbeat_watcher.py` (new), `akosha/mcp/server.py` (roster population + `/health` feed).
- **Demonstrable by**: `pytest tests/integration/test_heartbeat_watcher_e2e.py -v` — 5 passing; `curl -fsS http://localhost:8682/health | jq '.checks.known_mcp_servers'`.
- **Rollback signal**: `test_query_threw_suppresses_p0a` returns `query_empty` → the `except` clause returns the wrong verdict; a DB outage would page P0-A for every roster entry.
- **Observability added**: `telemetry_heartbeat_watcher_query_failed{code}`; the `/health` `known_mcp_servers` feed.

---

## Task 9 (PR-A6): akosha — resource-attribute validator

**Repo:** `/Users/les/Projects/akosha`. Same branch.

**Files:**
- Create: `akosha/observability/resource_validator.py`
- Modify: `akosha/observability/otlp_receiver.py` (call the validator in `_handle_batch`)
- Test: `akosha/tests/unit/observability/test_resource_validator.py`

**Interfaces:**
- Consumes: `ALLOWED_NAMESPACES` binding from spec §13.2 (bridge set at this task; flipped by Task 10).
- Produces: `class ResourceValidator` with `record(span: dict) -> bool`, module constants `ALLOWED_NAMESPACES_BRIDGE`, `ALLOWED_NAMESPACES_POST_FLIP`, `ALLOWED_NAMESPACES`, `ROLLING_WINDOW_SECONDS`, `SPIKE_THRESHOLD`, `SUSTAINED_THRESHOLD_HR`.

- [ ] **Step 1: Write the failing test**

Create `/Users/les/Projects/akosha/tests/unit/observability/test_resource_validator.py`:

```python
from __future__ import annotations

import pytest

from akosha.observability import resource_validator as rv


def _span(ns: str) -> dict:
    return {"service_name": "x", "service_namespace": ns, "span_id": "s"}


def test_bridge_allows_legacy_and_new() -> None:
    assert "mcp-ecosystem" in rv.ALLOWED_NAMESPACES
    assert "bodai" in rv.ALLOWED_NAMESPACES


def test_unknown_namespace_is_drift() -> None:
    v = rv.ResourceValidator()
    assert v.record(_span("mystery-ns")) is False
    assert v.record(_span("bodai")) is True


def test_spike_threshold_alerts_once_per_window() -> None:
    v = rv.ResourceValidator()
    for _ in range(rv.SPIKE_THRESHOLD):
        v.record(_span("mystery-ns"))
    assert v.spike_alert_active is False  # at threshold, not over
    v.record(_span("mystery-ns"))
    assert v.spike_alert_active is True
    # Second drift in the same window does not re-alert.
    assert v.spike_alert_active is True


def test_startup_burst_does_not_trip_sustained() -> None:
    """Spec §13.2: rate-based, not count-based. A 50-drift startup burst
    inside one window is a spike, not sustained pressure."""
    v = rv.ResourceValidator()
    for _ in range(50):
        v.record(_span("mystery-ns"))
    assert v.sustained_drift_rate_hr < rv.SUSTAINED_THRESHOLD_HR * 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/unit/observability/test_resource_validator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'akosha.observability.resource_validator'`

- [ ] **Step 3: Implement the validator**

Create `akosha/observability/resource_validator.py`:

```python
from __future__ import annotations

import time

ALLOWED_NAMESPACES_BRIDGE = {"mcp-ecosystem", "bodai"}
ALLOWED_NAMESPACES_POST_FLIP = {"bodai"}

# PR-A6 ships the bridge set: the bridge release is active at this task's
# merge time, so mcp-ecosystem producers MUST be permitted or every span
# is flagged as drift. Task 10 flips this single binding.
ALLOWED_NAMESPACES = ALLOWED_NAMESPACES_BRIDGE

ROLLING_WINDOW_SECONDS = 300
SPIKE_THRESHOLD = 3
SUSTAINED_THRESHOLD_HR = 0.5


class ResourceValidator:
    """Rate-based drift detection on service.namespace."""

    def __init__(self) -> None:
        self._events: list[tuple[float, str]] = []
        self._alerted_windows: set[int] = set()
        self._baseline_start: float = time.time()

    def _prune(self, now: float) -> None:
        self._events = [e for e in self._events if now - e[0] <= ROLLING_WINDOW_SECONDS]

    def record(self, span: dict) -> bool:
        """Returns True when the span's namespace is allowlisted."""
        ns = span.get("service_namespace")
        if ns in ALLOWED_NAMESPACES:
            return True
        now = time.time()
        self._prune(now)
        self._events.append((now, str(ns)))
        window = int(now // ROLLING_WINDOW_SECONDS)
        if len(self._events) > SPIKE_THRESHOLD and window not in self._alerted_windows:
            self._alerted_windows.add(window)
        return False

    @property
    def spike_alert_active(self) -> bool:
        now = time.time()
        self._prune(now)
        return len(self._events) > SPIKE_THRESHOLD

    @property
    def sustained_drift_rate_hr(self) -> float:
        hours = max((time.time() - self._baseline_start) / 3600, 1e-9)
        return len(self._events) / hours
```

- [ ] **Step 4: Wire the validator into `_handle_batch`**

In `otlp_receiver.py`'s `__init__`, add `self._resource_validator = ResourceValidator()`. In `_handle_batch`, after `pre_validate` succeeds and before appending to `clean`:

```python
            if not self._resource_validator.record(span):
                self._metric_namespace_drift.labels(
                    namespace=str(span.get("service_namespace"))[:64]
                ).inc()
```

Label cardinality is the concern here: an unbounded namespace label can itself blow up Prometheus. Truncate to 64 chars and, if namespace values are unbounded in practice, replace the label with a constant and log the value instead.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/unit/observability/test_resource_validator.py -v`
Expected: PASS — 4 tests.

- [ ] **Step 6: Commit**

```bash
cd /Users/les/Projects/akosha
git add akosha/observability/resource_validator.py akosha/observability/otlp_receiver.py \
  tests/unit/observability/test_resource_validator.py
git commit -m "feat(akosha): rate-based resource-attribute validator (PR-A6)

Flags service.namespace values outside the allowlist. Rate-based, not
count-based: >3 drifts in a rolling 5-minute window is a P1 spike
(alerted once per window); >0.5/hour over 24h is P2 sustained. The
prior count-per-hour threshold was misclassified by both startup
bursts and slow drift.

Ships with ALLOWED_NAMESPACES = ALLOWED_NAMESPACES_BRIDGE — the bridge
release is active at merge time, so mcp-ecosystem producers must be
permitted or every span reads as drift. The flip is a single-line
binding change.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

#### Integration Contract (Task 9)
- **Triggered from**: `_handle_batch` on every span (akosha receiver).
- **Returns to / updates**: `akosha/observability/resource_validator.py` (new), `akosha/observability/otlp_receiver.py` (`__init__` + `_handle_batch`).
- **Demonstrable by**: `pytest tests/unit/observability/test_resource_validator.py -v` — 4 passing.
- **Rollback signal**: `test_bridge_allows_legacy_and_new` fails on `mcp-ecosystem` → the bridge set was not bound; every pre-flip producer span is counted as drift and the cardinality alarm fires spuriously.
- **Observability added**: `telemetry_receiver_namespace_drift{namespace}`.

---

## Task 10 (PR-A4): akosha — synthetic canary + Prometheus bridge

**Repo:** `/Users/les/Projects/akosha`. Same branch.

**Files:**
- Create: `akosha/observability/canary_watcher.py` (move `CanaryState` here from Task 5)
- Modify: `akosha/observability/otlp_receiver.py` (swap the `run_canary_emitter` stub; add `_canary_metrics_bridge`)
- Modify: `akosha/mcp/server.py` (add the `canary_metrics_task` to the lifespan)
- Test: `akosha/tests/integration/test_canary_watcher_e2e.py`

**Interfaces:**
- Consumes: `OTLPReceiver._handle_batch` (Task 5), `insert_spans_substrate` (Task 4), `stop_event` (Task 5 lifespan).
- Produces:
  - `CanaryState` dataclass, moved to `akosha/observability/canary_watcher.py` and re-exported from `otlp_receiver.py`
  - `async OTLPReceiver.run_canary_emitter(stop_event)` — real body
  - `async _canary_metrics_bridge(stop_event, receiver)`
  - Metrics `telemetry_receiver_canary_last_success_unix_nano`, `telemetry_receiver_canary_writes_{attempted,succeeded,failed,rejected}_total`, `telemetry_receiver_bridge_failed_total`

- [ ] **Step 1: Write the failing test**

Create `/Users/les/Projects/akosha/tests/integration/test_canary_watcher_e2e.py`:

```python
from __future__ import annotations

import asyncio
import time

import pytest

from akosha.observability.canary_watcher import (
    CANARY_EMIT_INTERVAL_SECONDS,
    CANARY_SERVICE_NAME,
    CANARY_SPAN_NAME,
)
from akosha.observability.otlp_receiver import OTLPReceiver
from akosha.storage.hot_store import HotStore


@pytest.fixture
async def rx(tmp_path):
    hs = HotStore(database_path=tmp_path / "canary.duckdb")
    await hs.initialize()
    return OTLPReceiver(hot_store=hs)


@pytest.mark.asyncio
async def test_three_emits_produce_three_rows(rx: OTLPReceiver) -> None:
    stop = asyncio.Event()
    for _ in range(3):
        await rx._emit_canary_once()
        await asyncio.sleep(0)
    rows = rx.hot_store.conn.execute(
        f"SELECT COUNT(*) FROM spans_substrate WHERE service_name = '{CANARY_SERVICE_NAME}'"
    ).fetchone()[0]
    assert rows == 3
    assert rx.canary_state.canary_writes_succeeded_total == 3


@pytest.mark.asyncio
async def test_success_pinned_to_ok_one_dedup_zero(rx: OTLPReceiver) -> None:
    """Spec §11.3: succeeded means BatchResult(ok=1, deduped=0) exactly.
    A deduped emit must NOT count as a success."""
    await rx._emit_canary_once()
    assert rx.canary_state.canary_writes_succeeded_total == 1
    # Force a duplicate by re-emitting with the same trace/span ids.
    rx._canary_id_override = ("_canary", "_canary_fixed")
    await rx._emit_canary_once()
    assert rx.canary_state.canary_writes_succeeded_total == 1
    assert rx.canary_state.canary_writes_rejected_total == 1


@pytest.mark.asyncio
async def test_last_success_advances(rx: OTLPReceiver) -> None:
    before = rx.canary_state.last_canary_success_unix_nano
    await rx._emit_canary_once()
    after = rx.canary_state.last_canary_success_unix_nano
    assert after is not None and (before is None or after > before)


@pytest.mark.asyncio
async def test_bridge_publishes_gauge(rx: OTLPReceiver) -> None:
    await rx._emit_canary_once()
    stop = asyncio.Event()
    task = asyncio.create_task(rx._canary_metrics_bridge(stop, interval=0.01))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.gather(task, return_exceptions=True)
    assert rx._metric_canary_last_success_unix_nano._value.get() > 0


@pytest.mark.asyncio
async def test_bridge_survives_exception(rx: OTLPReceiver) -> None:
    """Review: an uncaught exception in the bridge body kills it forever;
    the gauge freezes and P0-C pages with no cause. The bridge must retry."""
    rx.canary_state = property(lambda s: (_ for _ in ()).throw(RuntimeError("boom")))

    stop = asyncio.Event()
    task = asyncio.create_task(rx._canary_metrics_bridge(stop, interval=0.01))
    await asyncio.sleep(0.05)
    assert not task.done(), "bridge died on a transient error"
    stop.set()
    await asyncio.gather(task, return_exceptions=True)
    assert rx._metric_bridge_failed_total._value.get() > 0


@pytest.mark.asyncio
async def test_failed_emit_increments_failed_not_rejected(rx: OTLPReceiver) -> None:
    rx._emit_canary_once = lambda: (_ for _ in ()).throw(
        RuntimeError("insert boom")
    )
    await rx._emit_canary_once_safe()
    assert rx.canary_state.canary_writes_failed_total == 1
    assert rx.canary_state.canary_writes_rejected_total == 0


def test_constants_match_spec() -> None:
    assert CANARY_EMIT_INTERVAL_SECONDS == 30
    assert CANARY_SERVICE_NAME == "_receiver_canary"
    assert CANARY_SPAN_NAME == "_canary_substrate_write"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/integration/test_canary_watcher_e2e.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'akosha.observability.canary_watcher'`

- [ ] **Step 3: Create `canary_watcher.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

CANARY_EMIT_INTERVAL_SECONDS = 30
CANARY_SERVICE_NAME = "_receiver_canary"
CANARY_SPAN_NAME = "_canary_substrate_write"
CANARY_TRACE_ID = "_canary"


@dataclass
class CanaryState:
    last_canary_success_unix_nano: int | None = None
    last_canary_failure_unix_nano: int | None = None
    canary_writes_attempted_total: int = 0
    canary_writes_succeeded_total: int = 0
    canary_writes_failed_total: int = 0
    canary_writes_rejected_total: int = 0
    bridge_failed_total: int = 0
```

Delete the `CanaryState` definition that Task 5 added to `otlp_receiver.py` and import it from here instead:

```python
from akosha.observability.canary_watcher import CanaryState
```

- [ ] **Step 4: Implement `_emit_canary_once` and the loop body**

In `otlp_receiver.py`, replace the `run_canary_emitter` stub:

```python
async def _emit_canary_once_safe(self) -> None:
    """Emit one canary, converting any exception into a failed counter."""
    try:
        await self._emit_canary_once()
    except Exception as exc:
        self.canary_state.canary_writes_failed_total += 1
        self.canary_state.last_canary_failure_unix_nano = time.time_ns()
        self._metric_canary_failed.labels(
            reason=type(exc).__name__
        ).inc()


async def _emit_canary_once(self) -> None:
    """One canary write through the production _handle_batch path.

    Routing through _handle_batch (not a direct INSERT) is the point: a
    code change that breaks the live INSERT but leaves _dlq_insert
    working would otherwise pass silently.
    """
    import time as _time
    from akosha.observability.canary_watcher import (
        CANARY_SERVICE_NAME,
        CANARY_SPAN_NAME,
        CANARY_TRACE_ID,
    )

    now_ns = _time.time_ns()
    span_id = getattr(
        self, "_canary_id_override",
        ("_canary", f"_canary_{now_ns}"),
    )[1]
    trace_id = getattr(self, "_canary_id_override", (CANARY_TRACE_ID, ""))[0]

    self.canary_state.canary_writes_attempted_total += 1
    result = await self._handle_batch([{
        "span_id": span_id,
        "trace_id": trace_id,
        "service_name": CANARY_SERVICE_NAME,
        "service_namespace": "bodai",
        "span_name": CANARY_SPAN_NAME,
        "start_time_unix_nano": now_ns,
        "end_time_unix_nano": now_ns,
        "outcome": "success",
        "status_code": "STATUS_CODE_OK",
        "attributes": {"_canary": True, "_canary_version": "1"},
        "resource": {"service.name": CANARY_SERVICE_NAME},
    }])

    # Success is pinned: exactly one row inserted, none deduped.
    if result.ok == 1 and result.deduped == 0:
        self.canary_state.canary_writes_succeeded_total += 1
        self.canary_state.last_canary_success_unix_nano = now_ns
        self._metric_canary_succeeded.inc()
    elif result.deduped > 0:
        # Another pod won the race. Its own counter, not a label on
        # canary_writes_failed_total — a constraint rejection is not an
        # exception and deserves its own metric cardinality.
        self.canary_state.canary_writes_rejected_total += 1
        self._metric_canary_rejected.inc()
    else:
        self.canary_state.canary_writes_failed_total += 1
        self._metric_canary_failed.labels(reason="not_inserted").inc()


async def run_canary_emitter(self, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await stop_event.wait(CANARY_EMIT_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            raise
        if stop_event.is_set():
            return
        await self._emit_canary_once_safe()
```

**Note on `_handle_batch`'s signature:** Task 5 declares it as taking an `ExportTraceServiceRequest`. For the canary, calling it with a plain list of row dicts is simpler and exercises the same validation + INSERT + DLQ path. Either adapt `_handle_batch` to accept `list[dict] | ExportTraceServiceRequest` (dispatching on type), or build a real proto request here. Prefer the type-dispatch approach — it keeps `_handle_batch`'s single contract and lets the canary skip proto construction.

- [ ] **Step 5: Implement the bridge**

```python
async def _canary_metrics_bridge(
    self, stop_event: asyncio.Event, interval: float = 10.0
) -> None:
    """Bridge CanaryState -> Prometheus gauge on :9464.

    Observation only — never increments the write-side counters. Wrapped
    in try/except with backoff: an uncaught exception here would kill the
    bridge for the process lifetime, freezing the gauge and paging P0-C
    with no actionable cause.
    """
    backoff = 1.0
    while not stop_event.is_set():
        try:
            await stop_event.wait(interval)
        except asyncio.CancelledError:
            raise
        if stop_event.is_set():
            return
        try:
            last_success = self.canary_state.last_canary_success_unix_nano or 0
            self._metric_canary_last_success_unix_nano.set(last_success)
            self._metric_bridge_failed_total.inc(0)  # reset on a healthy pass
        except Exception:
            self._metric_bridge_failed_total.inc()
            logger.exception("canary_metrics_bridge_failed retry_after=%s", backoff)
            await stop_event.wait(backoff)
            backoff = min(backoff * 2, 60)
            continue
        backoff = 1.0
```

- [ ] **Step 6: Wire the bridge into the lifespan**

In `akosha/mcp/server.py`'s lifespan, add between `retention_task` and the `yield`:

```python
    canary_metrics_task = asyncio.create_task(
        receiver._canary_metrics_bridge(stop_event), name="canary_metrics_bridge"
    )
```

And in the teardown, add `canary_metrics_task.cancel()` plus include it in the `asyncio.gather(...)` call.

- [ ] **Step 7: Run test to verify it passes**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/integration/test_canary_watcher_e2e.py -v`
Expected: PASS — 6 tests.

- [ ] **Step 8: Commit**

```bash
cd /Users/les/Projects/akosha
git add akosha/observability/canary_watcher.py akosha/observability/otlp_receiver.py \
  akosha/mcp/server.py tests/integration/test_canary_watcher_e2e.py
git commit -m "feat(akosha): synthetic canary + Prometheus bridge (PR-A4)

The heartbeat watcher proves the substrate is queryable; it does not
prove the receiver's writes succeed. A broken _handle_batch lets
/health return green while every producer's spans silently drop. The
canary emits a deterministic marker span through the production
_handle_batch path every 30s and tracks the last successful write.

Success is pinned to BatchResult(ok=1, deduped=0) exactly. With
multiple pods racing, only one per cycle meets that bar; the losers'
UNIQUE-CONSTRAINT rejections increment canary_writes_rejected_total —
its own counter, not a label on canary_writes_failed_total, because a
constraint rejection is not an exception.

The metrics bridge is wrapped in try/except with backoff. Unwrapped,
any transient error would kill the bridge for the process lifetime,
freezing canary_last_success_unix_nano and paging P0-C with no cause.

Alerts (PromQL references the scraped gauge, not the Python field):
  receiver_canary_stale:
    time() * 1e9 - telemetry_receiver_canary_last_success_unix_nano > 90e9
  receiver_canary_bridge_dead:
    increase(telemetry_receiver_bridge_failed_total[5m]) > 0
      AND increase(telemetry_receiver_canary_writes_attempted_total[5m]) > 0

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

#### Integration Contract (Task 10)
- **Triggered from**: the lifespan tasks created in Task 5 (`receiver.run_canary_emitter`, `receiver._canary_metrics_bridge`).
- **Returns to / updates**: `akosha/observability/canary_watcher.py` (new), `akosha/observability/otlp_receiver.py` (canary body + bridge), `akosha/mcp/server.py` (third lifespan task).
- **Demonstrable by**: `pytest tests/integration/test_canary_watcher_e2e.py -v` — 6 passing; `curl -fsS http://localhost:9464/metrics | grep telemetry_receiver_canary_last_success` shows a value advancing every 30s.
- **Rollback signal**: `test_success_pinned_to_ok_one_dedup_zero` counts a deduped emit as a success → the pin was implemented as "not an exception" rather than "exactly one inserted".
- **Observability added**: `telemetry_receiver_canary_last_success_unix_nano`, `telemetry_receiver_canary_writes_attempted_total`, `..._succeeded_total`, `..._failed_total{reason}`, `..._rejected_total`, `telemetry_receiver_bridge_failed_total`.

---

## Task 11 (PR-A8): akosha — retire the `OtelTraceIngester` poller

**Repo:** `/Users/les/Projects/akosha`. Same branch.

**Files:**
- Modify: `akosha/mcp/server.py:620-660` (remove the `AKOSHA_SKIP_OTEL_INGESTER` block entirely)
- Modify: `settings/akosha.yaml` (delete the `trace_ingester_poller` key)
- Modify: `akosha/CLAUDE.md` (operator note)
- Test: `akosha/tests/integration/test_poller_retirement.py`

**Interfaces:**
- Consumes: the receiver from Task 5 (the poller's job is now the receiver's).
- Produces: no new symbols. Removes `OtelTraceIngester` from the akosha lifespan, and removes `otel.receiver.trace_ingester_poller` from the settings schema entirely. **Rollback is a git revert, not a flag flip** — the flag guarded code that no longer exists, so keeping it would advertise a control that does nothing.

- [ ] **Step 1: Write the failing test**

Create `/Users/les/Projects/akosha/tests/integration/test_poller_retirement.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

SERVER_PY = Path(__file__).resolve().parents[2] / "akosha" / "mcp" / "server.py"


def test_otel_trace_ingester_no_longer_imported() -> None:
    src = SERVER_PY.read_text()
    assert "from akosha.ingestion.otel_ingester import" not in src, (
        "PR-A8 must remove the OtelTraceIngester import, not gate it"
    )
    assert "OtelTraceIngester(" not in src


def test_env_var_shim_retired() -> None:
    """Pre-1.0 no-backcompat: the AKOSHA_SKIP_OTEL_INGESTER env var is
    removed outright. An operator's launchd plist still setting it =1
    would otherwise silently re-enable the retired poller."""
    src = SERVER_PY.read_text()
    assert "AKOSHA_SKIP_OTEL_INGESTER" not in src


def test_settings_flag_removed() -> None:
    """Pre-1.0 replace-don't-extend: the flag guarding deleted code is
    deleted too. A flag that maps to nothing is worse than no flag — an
    operator reads `trace_ingester_poller: false`, believes it is a live
    rollback lever, and is wrong."""
    from pathlib import Path

    import yaml

    cfg = Path(__file__).resolve().parents[2] / "akosha" / "settings" / "akosha.yaml"
    receiver = yaml.safe_load(cfg.read_text())["otel"]["receiver"]
    assert "trace_ingester_poller" not in receiver
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/integration/test_poller_retirement.py -v`
Expected: FAIL — the import, the env-var string, and the settings key are all still present.

- [ ] **Step 3: Remove the poller block**

In `akosha/mcp/server.py`, delete the entire block introduced by the "Wave 6" comment (around line 620-660), from `# Wave 6: start the OtelTraceIngester` through the closing of the `if not _env_truthy("AKOSHA_SKIP_OTEL_INGESTER"):` statement, including the `global _otel_trace_ingester` line and the `try/except` that constructs `OtelTraceIngester(...)`.

Then delete `akosha/ingestion/otel_ingester.py` if nothing else imports it:

```bash
cd /Users/les/Projects/akosha
grep -rn "otel_ingester\|OtelTraceIngester" --include="*.py" . | grep -v "^./akosha/ingestion/otel_ingester.py"
```

If the grep returns hits outside that file, keep the module and only remove the lifespan usage. If it returns nothing, delete the file.

Also check for the settings model — if `trace_ingester_poller` is declared as a field on a Pydantic settings class (not just YAML), remove the field too:

```bash
cd /Users/les/Projects/akosha
grep -rn "trace_ingester_poller" --include="*.py" .
```

A YAML-only deletion leaves a declared-but-unread settings field, which `scripts/audit_orphans.py` flags as a zero-caller symbol.

- [ ] **Step 4: Delete the settings key**

In `settings/akosha.yaml`, remove the `trace_ingester_poller: true` line, leaving:

```yaml
otel:
  receiver:
    known_mcp_servers:
      - "mahavishnu"
      - "akosha"
      - "session-buddy"
      - "oneiric"
      - "crackerjack"
      - "bifrost-mcp"
```

The spec §13.6 proposed keeping this flag as the rollback lever. This plan deletes it instead: the flag guarded a code path that this task removes, so flipping it back to `true` would do nothing. Advertising a rollback lever that does not work is worse than having no lever — rollback is a `git revert` of this commit, and the operator note below says so explicitly.

Record the deviation from the spec in `docs/decisions/2026-10-19-poller-retirement-no-flag.md`:

```markdown
## Context

Spec v7 §13.6 specifies `otel.receiver.trace_ingester_poller: bool` as the
rollback lever for PR-A8, flipping true → false to retire the poller.

## Decision rule

The flag is deleted rather than flipped. PR-A8 removes the poller code it
guards, so after merge the flag controls nothing. The pre-1.0 rule
(feedback-no-backwards-compat-pre-1.0) is replace-don't-extend, and a
settings key that maps to deleted code is a documentation lie.

Rollback is `git revert` of the PR-A8 commit.

## Status

active
```

- [ ] **Step 5: Update the operator note**

In `akosha/CLAUDE.md` (or wherever operators are documented for OTel), delete any `AKOSHA_SKIP_OTEL_INGESTER` or `trace_ingester_poller` reference. The OTel ingestion section should now read:

```markdown
## OTel ingestion

Akosha receives spans over OTLP (`akosha/observability/otlp_receiver.py`,
`:4317` gRPC / `:4318` HTTP) and writes them to the oneiric-managed
`spans_substrate` table. The former `OtelTraceIngester` poller and its
`AKOSHA_SKIP_OTEL_INGESTER` env var were removed in PR-A8 — there is no
ingestion toggle. Rollback is a git revert, not a config flag.
```

Then confirm the spec runbooks (§11.1.5/6/7) contain no step that tells an operator to set the retired env var.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/integration/test_poller_retirement.py -v`
Expected: PASS — 3 tests.

- [ ] **Step 7: Run the full akosha suite for regressions**

Run: `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/ -k "otel or ingest or server" -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
cd /Users/les/Projects/akosha
git add akosha/mcp/server.py settings/akosha.yaml akosha/CLAUDE.md \
  docs/decisions/2026-10-19-poller-retirement-no-flag.md \
  tests/integration/test_poller_retirement.py
git add -u
git commit -m "refactor(akosha)!: retire the OtelTraceIngester poller (PR-A8)

The OTLPReceiver owns ingestion now; the polling ingester duplicated
the write path against a table the receiver already maintains.

Removes three things: the lifespan block, the AKOSHA_SKIP_OTEL_INGESTER
env var, and the otel.receiver.trace_ingester_poller settings key.

Deleting the env var: keeping it would mean an operator's launchd plist
still setting it =1 silently re-enables the retired poller after merge.
A live launchd plist is exactly the case that motivates deleting the
shim rather than deprecating it.

Deleting the settings key DEVIATES from spec §13.6, which proposed
flipping it true -> false as the rollback lever. The flag guarded code
this commit removes, so post-merge it controls nothing — a flag that
maps to deleted code is worse than no flag, because an operator reads
it and believes they have a lever. Rollback is git revert. Recorded in
docs/decisions/2026-10-19-poller-retirement-no-flag.md.

Also deletes akosha/ingestion/otel_ingester.py when the consumer grep
finds no other importer, and removes any Pydantic settings field for
trace_ingester_poller so audit_orphans.py does not flag a
declared-but-unread symbol.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

#### Integration Contract (Task 11)
- **Triggered from**: `akosha mcp start` (lifespan).
- **Returns to / updates**: `akosha/mcp/server.py` (poller block removed), `settings/akosha.yaml` (`trace_ingester_poller` key deleted), `akosha/CLAUDE.md` (operator note), `docs/decisions/2026-10-19-poller-retirement-no-flag.md` (the spec-deviation record).
- **Demonstrable by**: `pytest tests/integration/test_poller_retirement.py -v` — 3 passing; `akosha mcp start` logs contain no `OtelTraceIngester` line.
- **Rollback signal**: any test still importing `akosha.ingestion.otel_ingester` fails at collection → the grep in Step 3 missed a consumer; restore the module and remove only the lifespan usage. Note this is a code rollback, not a config one — there is no flag to flip.
- **Observability added**: none (a removal; the receiver's existing metrics cover ingestion).

---

## Task 12 (PR-A7): mcp-common — `service.namespace` flip

**Repo:** `/Users/les/Projects/mcp-common`. New branch, gated on the consumer sweep.

**Files:**
- Modify: `mcp_common/server/telemetry.py` (flip the default; remove `legacy_namespace`)
- Modify: `oneiric/oneiric/core/substrate_settings.py` (flip `telemetry__service_namespace`; drop the alias field)
- Test: `mcp-common/tests/unit/server/test_namespace_flip.py`
- Test: `mcp-common/tests/integration/test_service_namespace_bridge.py`

**Interfaces:**
- Consumes: `legacy_namespace` / `telemetry__legacy_namespace_alias` (Task 1).
- Produces: `service.namespace` defaulting to `bodai`; the alias kwarg and setting removed (pre-1.0 replace-don't-extend).

- [ ] **Step 1: Run the consumer sweep (the gate)**

The flip cannot merge until every consumer reads `bodai`. Run this **before** writing any code:

```bash
cd /Users/les/Projects/mahavishnu
echo "=== Grafana dashboards ==="
git grep -n 'mcp-ecosystem' -- 'monitoring/dashboards/' || echo "clean"
echo "=== Alert rules ==="
git grep -n 'mcp-ecosystem' -- 'monitoring/prometheus/alerts.yml' || echo "clean"

cd /Users/les/Projects/akosha
echo "=== Akosha queries ==="
git grep -n 'mcp-ecosystem' -- 'akosha/' || echo "clean"

cd /Users/les/Projects/mcp-common
echo "=== mcp-common settings ==="
git grep -n 'mcp-ecosystem' -- 'mcp_common/' || echo "clean"
```

Every hit must be updated to read the new namespace, or the consumer must be switched to read `namespace.legacy_alias` during the bridge window. Record each edited file in the PR description.

- [ ] **Step 2: Add the CI gate**

Add a pre-merge CI step that fails if `git grep -n 'mcp-ecosystem'` returns hits in the paths above. The step belongs in the repo's existing PR-check workflow; add it as a distinct step named `service-namespace-consumer-sweep`.

- [ ] **Step 3: Write the failing flip test**

Create `/Users/les/Projects/mcp-common/tests/integration/test_service_namespace_bridge.py`:

```python
from __future__ import annotations

from mcp_common.server.telemetry import FastMCPOpenTelemetryMiddleware


class _Ctx:
    method = "tools/call"
    type = "request"
    name = "pool_health"
    message = None


def test_post_flip_default_is_bodai() -> None:
    mw = FastMCPOpenTelemetryMiddleware("mahavishnu")
    attrs = mw._span_attributes(_Ctx())
    assert attrs["service.namespace"] == "bodai"


def test_alias_is_gone_post_flip() -> None:
    """Pre-1.0: the bridge window closes and the alias kwarg is removed
    rather than deprecated."""
    mw = FastMCPOpenTelemetryMiddleware("mahavishnu")
    assert "namespace.legacy_alias" not in mw._span_attributes(_Ctx())


def test_legacy_namespace_kwarg_removed() -> None:
    import inspect
    sig = inspect.signature(FastMCPOpenTelemetryMiddleware.__init__)
    assert "legacy_namespace" not in sig.parameters


def test_consumer_sweep_returns_zero_pre_merge() -> None:
    """The CI gate from Step 2. Runs the same grep the gate runs."""
    import subprocess

    out = subprocess.run(
        ["git", "grep", "-n", "mcp-ecosystem", "--", "mcp_common/"],
        capture_output=True, text=True,
    )
    assert out.stdout.strip() == "", f"stale consumers:\n{out.stdout}"
```

- [ ] **Step 4: Run to verify it fails**

Run: `cd /Users/les/Projects/mcp-common && .venv/bin/pytest tests/integration/test_service_namespace_bridge.py -v`
Expected: FAIL — the default is still `oneiric-substrate` and `legacy_namespace` still exists.

- [ ] **Step 5: Flip oneiric's setting**

In `oneiric/core/substrate_settings.py`:

```python
    telemetry__service_namespace: str = Field(
        default="bodai",
        description="OTel service.namespace applied to substrate spans.",
    )
```

Delete the `telemetry__legacy_namespace_alias` field entirely (pre-1.0: replace, don't deprecate).

- [ ] **Step 6: Flip mcp-common and remove the alias kwarg**

In `mcp_common/server/telemetry.py`:

```python
    def __init__(
        self,
        service_name: str,
        *,
        environment: str = "production",
        service_namespace: str = "bodai",
    ) -> None:
        self.service_name = service_name
        self.environment = environment
        self.service_namespace = service_namespace
        self._tracer = (
            trace.get_tracer(f"{__name__}.{service_name}") if _OTEL_AVAILABLE else None
        )
```

Delete the `self.legacy_namespace = legacy_namespace` assignment and the `if self.legacy_namespace is not None:` block in `_span_attributes`.

- [ ] **Step 7: Flip the validator allowlist in akosha**

In `akosha/observability/resource_validator.py`, change the single binding line:

```python
ALLOWED_NAMESPACES = ALLOWED_NAMESPACES_POST_FLIP
```

Both the consumer sweep (Step 1) and the dual-label test gate this. Do not flip the allowlist before the sweep is clean — otherwise every legacy producer span reads as drift and the cardinality alarm fires spuriously.

- [ ] **Step 8: Run to verify it passes**

Run: `cd /Users/les/Projects/mcp-common && .venv/bin/pytest tests/integration/test_service_namespace_bridge.py -v`
Expected: PASS — 4 tests.

- [ ] **Step 9: Commit mcp-common and oneiric**

```bash
cd /Users/les/Projects/mcp-common
git add mcp_common/server/telemetry.py tests/integration/test_service_namespace_bridge.py
git commit -m "feat(mcp-common)!: flip service.namespace default to bodai; drop the alias

Closes the two-release migration opened by the bridge release. The
namespace.legacy_alias kwarg is REMOVED, not deprecated — pre-1.0
replace-don't-extend. After this commit a producer passing
legacy_namespace= raises TypeError, which is the intended signal that
the bridge window has closed.

Gated on the consumer sweep (all four repos return zero hits for
mcp-ecosystem) plus a CI step that keeps them at zero.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

```bash
cd /Users/les/Projects/oneiric
git add oneiric/core/substrate_settings.py
git commit -m "feat(oneiric)!: telemetry__service_namespace defaults to bodai

Drops telemetry__legacy_namespace_alias — the bridge window is closed.
Pre-1.0: replaced, not deprecated.

EXPECTED VERSION: minor bump — operator bumps pyproject.toml.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

- [ ] **Step 10: Commit the akosha allowlist flip**

```bash
cd /Users/les/Projects/akosha
git add akosha/observability/resource_validator.py
git commit -m "feat(akosha): flip the namespace allowlist post-migration

Single-line binding change from ALLOWED_NAMESPACES_BRIDGE to
ALLOWED_NAMESPACES_POST_FLIP. Do NOT flip before the consumer sweep is
clean: with mcp-ecosystem producers still emitting, every span reads as
drift and the cardinality alarm fires spuriously.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

#### Integration Contract (Task 12)
- **Triggered from**: the consumer sweep completing clean; the CI gate passing.
- **Returns to / updates**: `mcp_common/server/telemetry.py`, `oneiric/core/substrate_settings.py`, `akosha/observability/resource_validator.py`.
- **Demonstrable by**: `pytest tests/integration/test_service_namespace_bridge.py -v` — 4 passing; `git grep -n mcp-ecosystem` returns zero across all four consumer paths.
- **Rollback signal**: `test_consumer_sweep_returns_zero_pre_merge` fails → a consumer still reads the old namespace; fix the consumer rather than relaxing the test.
- **Observability added**: none (a default flip; `telemetry_receiver_namespace_drift` from Task 9 is the signal if a producer was missed).

---

## Deferred items — how this plan resolves them

The spec §1 defers four items to writing-plans. Here is where each lands.

| Deferred item | Resolution in this plan |
| **Dropped 2026-10-20:** yoyo migration framework in akosha (was PR-A2 / old Task 6) | **Not built — no migration framework is needed.** There is no yoyo in the fleet: not in akosha, not in oneiric, not in mahavishnu (only Alembic, in mahavishnu). Task 2 creates `spans_substrate` via `CREATE TABLE IF NOT EXISTS` in oneiric's `DuckdbHotStore.initialize()`, which runs on every substrate boot — idempotent, and it covers both fresh and pre-existing substrate files. A separate runner would have introduced a third framework into a repo that has none, for a substrate ADR 017 assigns to oneiric. |
| **Dropped 2026-10-20:** legacy `spans` table migration (was PR-A6.5 / old Task 11) | **Not built — there is no `spans` table to migrate.** `mahavishnu/ingesters/otel_ingester.py` never wrote one: it flattens traces into `conversations`-shaped records (`system_id`, `content`, `embedding`, `timestamp`, `metadata`) through the inherited `DuckdbHotStore.insert()`. A repo-wide grep for `CREATE TABLE.*spans` returns nothing but the spec and this plan. The retirement obligation folds into Task 11 (old Task 13), which already removes the poller. |
|---|---|
| PR-A3 port-move drain step | **Task 5, Step 12** ships the drain preflight: a `git grep ':4318'` sweep across dashboards, collector configs, and settings, run before the collector restarts. The spec's §13.1 names the consumer classes; the preflight enumerates the files. |
| PR-A3..A8 double-write artifacts DLQ classification | **Not applicable as written.** During the rollout the poller (Task 11) and the receiver (Task 5) both write spans, so a double-write looks like an `ok=0, deduped=1` result rather than a DLQ rejection. `deduped` already carries that signal; no new DLQ classification is needed. If a future phase produces artifacts that *do* quarantine, add a `reason="double_write"` label to `row_rejected` then. |
| Sweep leader-election / advisory lock | **Task 7** ships a TTL advisory lock (marker row in `_akosha_otel_receiver_state`), reclaimable after its TTL. Multi-pod sweep no longer races on the DuckDB file lock. |
| Producer-side sampling policy | **Out of scope — PR-B prerequisite.** The spec's §17 assigns the parent spec's rewrite to PR-B, and sampling is a producer-side policy decision that needs the read-side projection design first. oneiric already has `telemetry__sample_ratio` in `substrate_settings.py`; wiring it to actual head sampling is PR-B work. |

## Execution order and PR boundaries

| Task | Spec PR | Repo | Ships | Depends on |
|---|---|---|---|---|
| 1 | PR-A1 | oneiric + mcp-common | namespace bridge setting + emission | — |
| 2 | PR-0a | oneiric | `spans_substrate` DDL | — |
| 3 | PR-0b | akosha | deps + shared-receiver hook + namespace hygiene | 1 |
| 4 | (spec-cumulative) | akosha | `HotStore.insert_spans_substrate` | 2 |
| 5 | PR-A3 | akosha + mahavishnu | `OTLPReceiver` + lifespan + port move | 3, 4 |
| 6 | (spec-cumulative) | akosha | `admin otel retention` CLI | 4 |
| 7 | PR-A3 follow-on | akosha | sweep body + advisory lock | 4, 6 |
| 8 | PR-A5 | akosha | heartbeat watcher | 4 |
| 9 | PR-A6 | akosha | resource-attribute validator | 5 |
| 10 | PR-A4 | akosha | synthetic canary + bridge | 5, 7 |
| 11 | PR-A8 | akosha | poller retirement | 5, 10 |
| 12 | PR-A7 | mcp-common + oneiric + akosha | namespace flip | 1, 9, plus the consumer sweep |

**Two tasks are not in the spec's PR table:** Task 4 (`HotStore.insert_spans_substrate`) and Task 6 (`admin otel retention` CLI). Both are spec-cumulative — the spec's §5.2 names the method and §11.4a names the commands, but neither has its own PR row. They ride along with the PR whose scope covers them: both with PR-A3.

**Two spec PRs carry no task.** PR-A2 (yoyo migrations) and PR-A6.5 (legacy `spans` migration) were both dropped on 2026-10-20 because the codebase contradicts their premises — no yoyo exists in the fleet, and no `spans` table exists to migrate. The Deferred items table records the reasoning. Nothing depends on either PR landing, and no task below waits on one.

**Cross-repo coordination:** Tasks 1, 2, and 3 must land before akosha's Task 5 runs, because the receiver imports `LifecycleError` from oneiric and the middleware signature from mcp-common. The operator bumps oneiric and mcp-common versions after Tasks 1-3 and before Task 5.

**Relationship to the sibling plans:** this plan must merge through Task 12 before `docs/plans/2026-10-03-eval-adapter-phase1.md` and `docs/plans/2026-10-14-decision-adapter-category.md` open their first PRs, so all three share one oneiric/mcp-common version pin rather than racing three separate bumps.

## Post-plan verification

Before the branch merges:

- [ ] `cd oneiric && .venv/bin/pytest tests/ -v` — substrate suite green
- [ ] `cd mcp-common && .venv/bin/pytest tests/ -v` — telemetry suite green
- [ ] `cd akosha && .venv/bin/pytest tests/ -v` — receiver, CLI, migration, and sweep suites green
- [ ] `cd mahavishnu && .venv/bin/pytest tests/ -k "otel or collector" -v` — port move did not break a consumer
- [ ] `/Users/les/Projects/mahavishnu/.venv/bin/python /Users/les/Projects/mahavishnu/scripts/audit_orphans.py` — no zero-caller symbols (run from the mahavishnu repo root; the script lives there, not in akosha)
- [ ] `crackerjack run -v -f` in each of the four repos — merge gate green
- [ ] Live smoke: start akosha, confirm `/health` returns `known_mcp_servers` and `receiver_canary`, and `curl -fsS http://localhost:9464/metrics | grep telemetry_receiver` shows the canary gauge advancing
- [ ] `git grep ':4318'` returns zero hits across dashboards, collector configs, and settings
- [ ] `git grep 'mcp-ecosystem'` returns zero hits across all four consumer paths (Task 12's gate)