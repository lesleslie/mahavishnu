# Session-Buddy Extension Design (Mahavishnu seam hardening)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this design task-by-task. The implementation plan will live at `docs/superpowers/plans/2026-07-29-session-buddy-extension.md` once the writing-plans skill runs.

**Goal:** Close the Mahavishnu↔Session-Buddy seam so pool memory, hook commits, code-graph reads, and the Phase 1.5 conscious-agent loop are durable, cheap, and discoverable — without coupling the two repos beyond what's already necessary.

**Architecture:** Symmetric extension. Mahavishnu owns a local DuckDB WAL + outbox writer that absorbs Session-Buddy outages. Session-Buddy owns the hook single-flight gate, the plugin manifest, and the canonical code-graph index exposed via a read-through facade. Crackerjack owns the Phase 1.5 pre-commit gate consuming `distilled_skill_health`. Each component owns one concern; the circuit breaker already in `mahavishnu/pools/memory_aggregator.py` becomes the durable seam between them.

**Tech Stack:** DuckDB (Mahavishnu WAL + existing Session-Buddy v2 tables), Pydantic v2, FastMCP, asyncio, Crackerjack pre-commit hooks. No new infra, no new services.

## Global Constraints

- Mahavishnu WAL lives at `~/.mahavishnu/outbox.duckdb` — symmetric with the existing `~/.mahavishnu/state.duckdb` convention.
- WAL schema is `memory_outbox(id BIGSERIAL, key TEXT, payload JSON, enqueued_at TIMESTAMP, attempts INT, last_error TEXT, status TEXT CHECK in ('pending','drained','failed'))`. Status default `'pending'`. Index on `(enqueued_at, id) WHERE status='pending'` for ordered drain.
- Single-flight TTL is `5.0` seconds — long enough to coalesce paired checkpoint events, short enough to never drop a real human-initiated checkpoint.
- Drain batch size is `50`. Max drain attempts is `5` (matches the existing circuit breaker's `failure_threshold=5`).
- Plugin manifest ships exactly two artifacts: `plugin.json` (namespaced commands) and `hooks/PreCompact.md` (calls `mcp__session-buddy__pre_compact_sync`). No sub-agents, no skill templates.
- Crackerjack pre-commit gate is **warn-only by default** (exit code 1). Operators opt into blocking via existing `crackerjack run --strict` flag if they want it. `--no-verify` skips it (per existing convention). The gate does not change the default exit-code semantics of `crackerjack run`; passing `--strict` is the only way to make a warning become a failure.
- Read-through facade for code-graph is **additive**. Akosha and Mahavishnu retain their own indexes as fallback when the facade is unreachable. Session-Buddy becomes canonical, not exclusive.
- All five answers in the brainstorm (Q1–Q5) locked in via the answers received during the brainstorming session. Anything that contradicts them is a spec defect.

## Components

### Mahavishnu — `mahavishnu/pools/outbox/`

New package with three modules + one schema file:

| File | Responsibility |
|---|---|
| `table.py` | `MemoryOutboxRow` Pydantic model. `OutboxStatus = Literal["pending","drained","failed"]`. |
| `schema.sql` | `CREATE TABLE IF NOT EXISTS memory_outbox(...)`. Applied on first start. Idempotent. |
| `writer.py` | `MemoryOutboxWriter(db_path: pathlib.Path)`. Async `enqueue(key, payload) -> int`. `pending_count() -> int`. |
| `drainer.py` | `MemoryOutboxDrainer(writer, breaker, sink, batch_size=50, max_attempts=5)`. Async `drain_once() -> DrainResult`. |

Wiring: `MemoryAggregator.start_periodic_sync()` is the single entry point that gets a new collaborator (`outbox_writer` + `outbox_drainer`). The aggregator's existing `_CircuitBreaker(name="session-buddy", failure_threshold=5, recovery_timeout=60.0)` is passed straight through to the drainer — no new breaker, no new config.

The aggregator's existing batched-insert flow gains a parallel enqueue step: every reflection it would have sent to Session-Buddy is also written to the WAL before the network call. If the network call succeeds, the WAL row is marked `drained`. If it fails, the WAL row stays `pending` and the drainer picks it up on the next cycle.

### Session-Buddy — `session_buddy/hooks/single_flight.py`

New module:

```python
class HookSingleFlight:
    def __init__(self, ttl_seconds: float = 5.0) -> None: ...
    async def __call__(self, key: tuple[str, int], coro_factory: Callable[[], Awaitable[None]]) -> bool:
        """Returns True if the coro ran; False if coalesced. Key is (project_path, agent_idx)."""
```

Wiring: extends the existing single-flight pattern around `commands/checkpoint.py`. Applied to the `PreCompact` and `PostToolUse` hooks. `ttl_seconds=5.0` is a constant — not configurable per the existing single-flight pattern.

Session-Buddy's plugin manifest update lands as part of the next release (target 0.21.0):

- `plugins/session-buddy/.claude-plugin/plugin.json` declares the namespaced commands (additive to v0.20.0).
- `plugins/session-buddy/hooks/PreCompact.md` calls `mcp__session-buddy__pre_compact_sync` (existing MCP tool).

The code-graph read-through facade adds one new MCP tool: `mcp__session-buddy__search_code_graph(query, project)`. Backed by the existing `code_graphs` v2 table. Akosha's `search_code_patterns` and Mahavishnu's `treesitter_*` shims can call it instead of running their own DuckDB queries.

### Crackerjack — `crackerjack/hooks/skill_coverage.py`

New module:

```python
async def pre_commit_skill_coverage_gate(repo_path: pathlib.Path) -> int:
    """Returns 0 (pass), 1 (warn), 2 (block). Reads mcp__session-buddy__distilled_skill_health
    and emits skill_coverage_report. Bounded by commit count, not by CI minutes."""
```

Wired into `crackerjack/hooks/pre_commit.py` *after* format/lint gates but *before* the test gate. Warn-only by default (exit 1) — operators opt into blocking via `--strict`. `--no-verify` skips per existing convention. The LLM-Cost-Ceiling is enforced by the existing crackerjack LLM budget gate (100 calls/week) — this new gate is non-LLM and does not consume budget.

## Data flow

```
[Pool writes memory]
        ↓
[MemoryAggregator]
        ↓
[MemoryOutboxWriter.enqueue()] ──► [DuckDB WAL: memory_outbox table]
                                              ↓ (breaker closed)
                                       [MemoryOutboxDrainer.drain_once()]
                                              ↓ (async, batch_size=50)
                                       [Session-Buddy MCP: store_reflection]
                                              ↓
                                       [Session-Buddy v2 tables]

[Crackerjack pre-commit]
        ↓
[pre_commit_skill_coverage_gate()]
        ↓
[mcp__session-buddy__distilled_skill_health]
        ↓
[skill_coverage_report]
        ↓
[exit code 0 / 1 / 2]
```

## Interfaces

### Mahavishnu — `MemoryOutboxRow`

```python
class MemoryOutboxRow(BaseModel):
    id: int
    key: str
    payload: dict[str, object]
    enqueued_at: dt.datetime
    attempts: int = 0
    last_error: str | None = None
    status: Literal["pending", "drained", "failed"] = "pending"
```

### Mahavishnu — `MemoryOutboxWriter`

```python
class MemoryOutboxWriter:
    def __init__(self, db_path: pathlib.Path) -> None: ...
    async def enqueue(self, key: str, payload: dict[str, object]) -> int:
        """Insert a new pending row. Returns the assigned id."""
    async def pending_count(self) -> int:
        """Count rows where status='pending'."""
    async def mark_drained(self, ids: list[int]) -> int:
        """Bulk-mark rows drained. Returns count actually updated."""
    async def mark_failed(self, ids: list[int], error: str) -> int:
        """Bulk-mark rows failed. Sets last_error and attempts+=1."""
```

### Mahavishnu — `MemoryOutboxDrainer`

```python
@dataclass
class DrainResult:
    drained: int
    deferred: int
    failed: int

class MemoryOutboxDrainer:
    def __init__(
        self,
        writer: MemoryOutboxWriter,
        breaker: CircuitBreaker,
        sink: Callable[[str, dict[str, object]], Awaitable[None]],
        batch_size: int = 50,
        max_attempts: int = 5,
    ) -> None: ...

    async def drain_once(self) -> DrainResult:
        """If breaker is open: return drained=0, deferred=N, failed=0 immediately.
        Else: pull up to batch_size pending rows ordered by (enqueued_at, id);
        call sink for each; on success mark_drained; on retryable error mark_failed
        with attempts++; on non-retryable error mark_failed and stop retrying that row.
        Stop the batch on the first sink exception to preserve ordering."""
```

### Session-Buddy — `HookSingleFlight`

```python
class HookSingleFlight:
    def __init__(self, ttl_seconds: float = 5.0) -> None: ...
    async def __call__(
        self,
        key: tuple[str, int],
        coro_factory: Callable[[], Awaitable[None]],
    ) -> bool:
        """If a call with the same key started within ttl_seconds, return False without running coro_factory.
        Otherwise: record (key, now) and run coro_factory, return True."""
```

### Session-Buddy — `search_code_graph` MCP tool

```python
@mcp.tool()
async def search_code_graph(query: str, project: str) -> list[CodeGraphHit]:
    """Search the canonical code graph for symbols matching query in project.
    Delegates to the existing v2 code_graphs table via the existing DuckDB connection.
    Returns up to 50 hits sorted by relevance (call-graph proximity, then alpha)."""
```

### Crackerjack — `pre_commit_skill_coverage_gate`

```python
async def pre_commit_skill_coverage_gate(repo_path: pathlib.Path) -> int:
    """Returns:
    - 0 if distilled_skill_health reports all skills fresh
    - 1 if any skill is stale or unreachable (warn-only default)
    - 2 only on programming bug (assertion failed, schema mismatch)
    Never blocks on budget — non-LLM gate."""
```

## Error handling

| Layer | Failure | Response | Recovery |
|---|---|---|---|
| WAL enqueue | DuckDB disk full / perms | Raise `MemoryOutboxWriteError`. Aggregator logs CRITICAL, stops processing batch. | Operator expands disk or fixes perms. |
| WAL enqueue | Schema mismatch / DuckDB unavailable | Raise `MemoryOutboxSchemaError`. Process exits non-zero. | Hot-fix; no auto-recovery. |
| Drainer | Session-Buddy 5xx | Increment `attempts`. After 5 attempts, mark `status='failed'`. Breaker counter increments. | Breaker opens; pending rows wait; drainer resumes when breaker half-opens. |
| Drainer | Session-Buddy 4xx | Mark `status='failed'` immediately. Log ERROR with id + truncated payload. | Operator inspects `failed` rows. |
| Drainer | Breaker open | Skip; return `DrainResult(drained=0, deferred=N, failed=0)`. | Breaker half-opens on `recovery_timeout=60s`. |
| Hook single-flight | TTL window hit | Drop second event silently. Log DEBUG. | Next event outside TTL runs normally. |
| Hook single-flight | Underlying MCP error | Existing path. | Same as today. |
| Crackerjack gate | MCP unreachable | Print warning to stderr. Return 1. | Operator re-runs with session-buddy up. |
| Crackerjack gate | Stale skill detected | Print report. Return 1. | Operator runs `distill_skills_now`. |

## Testing strategy

**Functional** — `tests/unit/mahavishnu/pools/outbox/`:

- `test_writer_enqueues_and_round_trips`
- `test_writer_pending_count_filters_correctly`
- `test_drainer_drains_pending_when_breaker_closed`
- `test_drainer_skips_when_breaker_open`
- `test_drainer_marks_failed_after_max_attempts`

**Fault injection** — `tests/integration/mahavishnu/pools/outbox/`:

- `test_disk_full_during_enqueue_raises_write_error`
- `test_session_buddy_5xx_then_recovery`
- `test_partial_drain_failure_continues_batch`

**Operator-experience** — `tests/unit/crackerjack/hooks/`, `tests/unit/session_buddy/hooks/`:

- `test_skill_coverage_pre_commit_passes_with_fresh_skills`
- `test_skill_coverage_pre_commit_warns_on_stale`
- `test_skill_coverage_pre_commit_warns_when_unreachable`
- `test_hook_single_flight_drops_second_within_ttl`
- `test_hook_single_flight_allows_second_after_ttl`
- `test_hook_single_flight_distinct_keys_dont_block`

**End-to-end** — `tests/e2e/mahavishnu_session_buddy/`:

- `test_pool_memory_survives_session_buddy_outage`

## Rollout

| Phase | What ships | Feature flag | Rollback |
|---|---|---|---|
| 1 | WAL writer + schema migration, not wired to aggregator | `MAHAVISHNU_OUTBOX_ENABLED=false` (default) | Schema is `IF NOT EXISTS`; safe. |
| 2 | Drainer wired to aggregator, write-through mode | `MAHAVISHNU_OUTBOX_DRAIN=true` | Drainer is idempotent; old path stays live. |
| 3 | Hook single-flight in Session-Buddy | `SESSION_BUDDY_HOOK_SINGLE_FLIGHT=true` (default false for one week) | Flag off → identical to today. |
| 4 | Crackerjack pre-commit gate | Opt-in via `crackerjack run --with-skill-coverage` | Default behavior unchanged. |
| 5 | Plugin manifest update | Ships with Session-Buddy release 0.21.0 (the next minor version after v0.20.0). Coordinated with the Session-Buddy maintainer — if 0.21.0 slips, phase 5 rolls forward with it. | Plugin is additive; old plugin still works. |
| 6 | Read-through facade for code-graph | `SESSION_BUDDY_CODE_GRAPH_FACADE=true` (default false) | Old paths unchanged. |

Each phase is independently shippable and rollback-able. Phase 1 is a 2-day task; phases 2–6 are 1–2 days each.

## Out of scope

- **Embedding model pin changes** (prep Q7): freeze on `all-MiniLM-L6-v2` for now. Reopen only if a project concretely hits the 384-dim wall.
- **Channel-session aggregation tools** (prep Q8): defer to a separate brainstorm. The current scope is Q1–Q5 only.
- **Worktree lifecycle primitives** (`merge_worktree`, `prune_worktree`, etc.): those stay in Mahavishnu's `pools/worktree_pool`. Session-Buddy remains "list + create + remove" as a query/audit surface.
- **Replacing the existing `_CircuitBreaker`**: it's the right shape; the WAL just makes its open→closed transition safe instead of lossy.

## Open questions

None. All five brainstorm questions (Q1–Q5) locked in via user answers during the brainstorming session. Three architectural sections (architecture, components, error handling + testing + rollout) approved. The implementation plan will be written by the writing-plans skill next.
