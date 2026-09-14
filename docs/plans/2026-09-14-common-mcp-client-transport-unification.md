---
status: draft
role: umbrella
date: 2026-09-14
last_reviewed: 2026-09-14
superseded_by: null
topic: mcp-transport-unification
---

# CommonMCPClient + Time-Bounded /health Across Bodai

## 1. Outcome

Every Bodai MCP server ↔ MCP-server call uses a single canonical transport
(FastMCP streamable-HTTP at `/mcp`, JSON-RPC body) via a shared
`CommonMCPClient` shipped from `mcp-common`. Every Bodai MCP server's
`/health` endpoint reports feed state with **time-bounded** error
semantics — historical noise is no longer misread as degradation.

**Success signal**: `python scripts/audit_orphans.py` on each Bodai repo
lists zero per-repo copies of `post(f"{base}/tools/call")` and zero
ad-hoc `_default_health_probe` definitions. Every cross-server call goes
through `mcp_common.interfaces.CommonMCPClient`. Running the akosha
smoke test (`tests/integration/mcp/test_plan_index_health.py` shape)
against an akosha process whose alloy store is empty reports
`status: degraded` with `reason_hints` listing "warming_up — no traces
yet" — *not* `503`, because the empty-feed-but-healthy semantics are
now first-class.

## 2. Goals

1. Ship `mcp-common/mcp_common/interfaces/common_mcp_client.py`
   (≈120 LOC) and `mcp_common/interfaces/health_feed.py` (≈80 LOC)
   with unit tests in both repos (`mcp-common` ≥ 80% coverage on the
   new module; mahavishnu/akosha/dhara/session-buddy/crackerjack existing
   test suites still pass against the new SDK).
2. Replace all 84 production `f"{base}/tools/call"` HTTP call sites
   across 5 repos with `await client.call(name=…, arguments=…)` /
   `await client.call_dict(...)`. Achieve replacement via a one-shot
   sweep (per-repo worktree, isolated commits), not a deprecation
   bridge. Per `no-bodai-pre-commit-hook.md`, each per-repo PR is
   independent; merge order is `mcp-common → leaf consumers →
   load-bearing consumers (mahavishnu, dhara)`.
3. Standardize default URLs across all 5 repos: every
   `<COMPONENT>_MCP_URL` default now ends in `/mcp`. The 4 files
   with `/mcp`-stripped defaults (`akosha/processing/fitness_analyzer.py:34`,
   `akosha/mcp/server.py:52`, `mahavishnu/...`, `dhara/...`) updated.
4. Replace each repo's `_default_health_probe` (50-100 LOC per repo)
   with a call into `mcp_common.health.aggregate_feed_states`. The
   per-feed `ok` predicate becomes time-bounded: a feed is healthy
   when `last_error_at < now - HEALTH_FEED_HALFLIFE_SECONDS` (default
   300s) OR `errors_within_window == 0`. `warming_up` (count=0,
   ingester running, no errors) becomes an explicit healthy state.
5. Akosha's `/health=503` from cumulative `otel_errors_total` (10 stale
   errors against 4798 successful polls) flips to `/health=200` once
   Phase 4 lands, with `reason_hints: ["warming_up: empty alloy, no
   producers writing"]` surfaced in the response body.
6. Documented at `mcp-common/CHANGELOG.md` and a release announcement
   in `docs/announcements/2026-09-14-mcp-transport-unification.md`.

## 3. Non-Goals

1. **HNSW-on-DuckDB bug** in akosha: `code_graphs_feed` repeatedly
   fails to create HNSW indexes because DuckDB has no native HNSW
   support. That's a separate plan; tracked as `docs/followups/2026-09-14-akosha-hnsw-on-duckdb.md`.
2. **Streamable-HTTP session-ID state machine** in depth: the SDK
   handles "first request gets a session, reuse it for 410/401 reconnect"
   but does not aim for full MCP session lifecycle (capability
   negotiation, peer negotiation, async generator fan-out). Out of
   scope; the existing per-tool pagination already works.
3. **Streaming responses** (`streamablehttp` SSE for tool results that
   exceed the buffer threshold). All existing Bodai tools return
   <= 64KB JSON; the SDK accepts chunked responses but does not
   expose streaming to callers. Add when a tool exceeds the threshold.
4. **TLS verification** between cross-server calls (assumes
   `127.0.0.1`; production deploys already use mTLS via the
   existing `mcp_common.auth` token verifier).
5. **Removing the `/mcp/tools/call` HTTP-style mount** from Dhara. The
   mount is a FastMCP default that Dhara exposes; we don't disable
   it, we just stop calling it cross-server.

## 4. Current Findings

This plan was driven by four concrete bugs surfaced during the
`/health=503` investigation on 2026-09-13/14. Diagnostic evidence:

### 4.1 Cross-server HTTP transport drift (84 production references)

```
$ grep -rn '/tools/call' session-buddy/ mahavishnu/ dhara/ akosha/ \
    --include='*.py' | grep -v __pycache__ | wc -l
84

mahavishnu: 34 sites
akosha:     33 sites
dhara:      12 sites
session-buddy: 5 sites
crackerjack: 0 (uses local tools only)
```

The pattern is `f"{base_url}/tools/call"` in 84 production files.
Probed endpoints showed:

```
POST http://localhost:8683/tools/call      → 404
POST http://localhost:8678/mcp/tools/call  → 404 (Session-Buddy)
POST http://localhost:8683/mcp/tools/call  → 200 (Dhara — FastMCP default)
POST http://localhost:8678/mcp             → 200 (streamable-HTTP JSON-RPC, all)
POST http://localhost:8683/mcp             → 200 (streamable-HTTP JSON-RPC, all)
```

Two endpoints work, three don't. The pattern works against Dhara by
accident (FastMCP double-mount) and breaks against every other
server. **This is the root cause of the 10/4642 cumulative errors
akosha logs** — `kg_refresh` → federation helper → Session-Buddy
→ 404.

### 4.2 Inconsistent default URLs (5/5 repos affected)

```
$ grep -rn "DHARA_DEFAULT_URL\|SESSION_BUDDY_DEFAULT" \
    {5 repos}/**/*.py

akosha/processing/fitness_analyzer.py:34   _DHARA_DEFAULT_URL = "http://localhost:8683"     ← no /mcp
akosha/mcp/server.py:52                   DHARA_DEFAULT_URL = "http://localhost:8683"     ← no /mcp
akosha/mcp/tools/__init__.py:238          default = "http://localhost:8683/mcp"           ← /mcp
akosha/mcp/tools/ecosystem_skills.py:115  default = "http://localhost:8683/mcp"           ← /mcp
akosha/storage/dhara_http_client.py:31    DHARA_DEFAULT_URL = "http://localhost:8683/mcp" ← /mcp
```

Same component, two different default conventions in the same repo.

### 4.3 Per-repo `/health` aggregator duplication (4/5 repos)

`grep -n "register_health_tools\|_default_health_probe"` returns ~30-100
lines per repo. Each repo: builds its own predicate (`local_traces_ok`,
`kg_ok`, `skills_signer`), aggregates with hand-rolled precedence,
exposes via its own routing. No two repos agree on what a "healthy
feed" means for the same FeedState.

### 4.4 Cumulative counter semantics (every feed-state implementation)

`akosha/mcp/server.py:867`:
```python
otel_warming_up = local_traces_otel_running and local_traces_otel_errors == 0
local_traces_ok = otel_disabled or (count > 0) or (not cycled) or (not alive) or otel_warming_up
```

A single boot-time `httpx2.ConnectTimeout` from week-old alloy brings
`/health` to 503 forever. Live polling has been at 0.4% error rate,
error-free for the last ~3500 cycles, but `/health=503` stays because
`errors_total` never decays.

### 4.5 /health status projection doesn't match operator narrative

The current `ok: True | False` predicate is binary and silent
about *why*. Operators read launchd `exit=1` and conclude "the server
is broken" when the actual reading is "10 historical errors; empty
feed; ingester idle awaiting first spans". A 503-with-reason is
honest; a 503-without-context is noise.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-001
    title: "mcp-common exposes CommonMCPClient with streamable-HTTP JSON-RPC"
  - id: REQ-002
    title: "mcp-common exposes HealthFeedState with last_error_at + within_window counter"
  - id: REQ-003
    title: "mcp-common exposes aggregate_feed_states producing reason_hints"
  - id: REQ-004
    title: "All 84 /tools/call call sites replaced with CommonMCPClient"
  - id: REQ-005
    title: "Env defaults in 5 repos end in /mcp"
  - id: REQ-006
    title: "Each repo's /health aggregator delegates to aggregate_feed_states"
  - id: REQ-007
    title: "Cumulative feed errors do not block /health=200 after halflife elapses"
  - id: REQ-008
    title: "Empty-feed + ingester-running reports warming_up with reason_hints"
  - id: REQ-009
    title: "Integration tests in each repo prove cross-server call works"
```

## 5. Implementation Phases

### Phase 1: Foundational SDK in `mcp-common`

**Goal**: ship `CommonMCPClient`, `HealthFeedState`, `aggregate_feed_states`.

**Tasks**:
1. Add `mcp-common/mcp_common/interfaces/` package (currently empty).
2. Add `common_mcp_client.py` (~120 LOC): `async with` async client,
   JSON-RPC envelope, session-ID capture from the first 200 response's
   `Mcp-Session-Id` header, automatic reconnect on 401/410 (server
   rotated session), tool-call convenience method `call(name, *,
   arguments, timeout)` returning the JSON-decoded `result` payload.
3. Add `health_feed.py` (~80 LOC): `HealthFeedState` dataclass with
   `entities_count`, `last_updated_timestamp`, `cycles_total`,
   `errors_total`, `last_error_at: float | None`,
   `errors_within_window: int` (rolling 5-minute window). Helpers:
   `record_success(state)`, `record_error(state)`, `is_healthy(state, halflife_seconds=300)`.
4. Add `aggregate_feed_states(states: dict[str, HealthFeedState])`
   helper to `mcp_common/health.py`. Returns
   `{status, checks: dict, reason_hints: list[str], healthy, degraded,
   warming_up, failed}`. Publishes `warming_up` as healthy.
5. Tests (`mcp-common/tests/unit/interfaces/`):
   - session-ID handshake across reconnects
   - JSON-RPC error envelope unwrapping
   - 401/410 reconnect cycle
   - multiple calls in same session reuse
   - `record_success` resets `errors_within_window`
   - `is_healthy` true when `now - last_error_at > halflife`
6. Bump `mcp-common` to a minor version (`0.21.x → 0.22.0`); publish.
   Per `crackerjack-p-minor-full-lifecycle.md`, user initiates PyPI;
   flag the publish step in the commit.

#### Phase 1 Integration Contract

**Triggered from**:
- `from mcp_common.interfaces import CommonMCPClient` (added API surface).

**Returns to / updates**:
- `mcp_common.interfaces.CommonMCPClient.call(name, *, arguments,
  timeout=None)` → `dict` of the JSON-RPC `result.payload`.
- `mcp_common.interfaces.health_feed.HealthFeedState` and helpers
  mutable from caller-side; no cross-process state.

**Demonstrable by**:
```python
import asyncio
from mcp_common.interfaces import CommonMCPClient

async def smoke():
    async with CommonMCPClient(base_url="http://localhost:8678/mcp") as c:
        result = await c.call("session_buddy_get_liveness", arguments={})
    assert result["status"] == "ok"
asyncio.run(smoke())
```

Plus: `mcp-common/pytest tests/unit/interfaces/ -v` exits 0
(≥80% coverage on the new module).

**Rollback signal**:
- `mcp-common/tests/unit/interfaces/test_common_mcp_client.py::test_session_id_handshake` returns non-zero.
- `mcp-common/tests/unit/interfaces/test_health_feed.py::test_is_healthy_after_halflife` returns non-zero.
- Cross-server smoke test in any consumer repo fails (`tests/integration/mcp/test_common_mcp_client.py`).

**Observability added**:
- OTel span `mcp_common.client.call` with attributes `mcp_server`,
  `tool`, `jsonrpc.id`, `duration_ms`, `status`.
- OTel event `mcp_common.client.session.reconnect` on 401/410.
- Structured log line `mcp_common.client.{tool}` at INFO with
  outcome; at WARNING when the call exceeded the timeout.

### Phase 2: Standardize env defaults across 5 repos

**Goal**: every `<COMPONENT>_MCP_URL` env var defaults to `http://localhost:PORT/mcp`.

**Tasks**:
1. Audit: `grep -rn "DEFAULT_URL\|MCP_URL.*=" 5 repos` — 12 sites total.
2. Update the 4 wrong-default sites (see §4.2) by appending `/mcp`
   to the URL literal. Tests in each repo reference the literal
   directly (e.g., `tests/unit/test_dhara_adapter.py:35`), so the
   matching test files get updated in lockstep.
3. Add a top-of-file `ExplicitContract` comment in each `_default_*.py`
   file: "All Bodai MCP URL defaults MUST end in `/mcp` per REQ-005;
   see `docs/plans/2026-09-14-common-mcp-client-transport-unification.md`."
4. No new test surface required — Phase 4's migration tests cover
   this transitively (Phase 2 is a precondition, Phase 4 is the
   proof).

#### Phase 2 Integration Contract

**Triggered from**:
- Boot-time env lookup (Phase 1 CommonMCPClient reads env via
  delegated consumers' `mcp-client-factory-*` hook).

**Returns to / updates**:
- Updated default URL string in the four literal sites
  (`akosha/processing/fitness_analyzer.py:34`,
  `akosha/mcp/server.py:52`, `mahavishnu/...`,
  `dhara/...`). Test references for those literals
  updated in their `tests/unit/test_*.py` matches.

**Demonstrable by**:
```bash
$ grep -rn 'DEFAULT_URL.*"http://localhost:[0-9]*"' {5 repos}/**/*.py | \
    grep -v '/mcp"' | wc -l
0
```

**Rollback signal**:
- The grep above returns >0 (regression). Restart of any Bodai
  server fails to bind because `mcp_common.interfaces.CommonMCPClient`
  receives a URL without `/mcp` suffix.

**Observability added**:
- Log line at startup of each Bodai server: `client_url_normalized`
  with `from`, `to`, `env_var` keys — confirms operator can audit
  effective URLs per process.

### Phase 3: Migrate all 84 `/tools/call` call sites

**Goal**: every cross-server POST in production uses `CommonMCPClient.call`.

**Tasks**:
1. Per-repo worktree fan-out (per `feedback-fanout-pattern` and
   `ENTER_WORKTREE` guidance). Each repo gets one worktree, one
   branch (`fix/common-mcp-client-migration`), one commit that
   does the file-by-file replacement.
2. Mahavishnu: 34 files. Mostly 1-to-1 substitutions
   (`await client.put(key, value, ...)` is already async-friendly;
   `client.call("put", {"key":..., "value":...})` matches the
   existing wire shape).
3. Akosha: 33 files. Federate via `CommonMCPClient` in:
   `ingestion/code_graph_ingester.py:157, 208`,
   `processing/fitness_analyzer.py:189`,
   `mcp/server.py:227`, `mcp/client.py:202-256`,
   `storage/dhara_http_client.py:82, 103`.
4. Dhara: 12 files. (Verify with fresh grep.)
5. Session-Buddy: 5 files (`server_optimized.py:118`,
   `channel_tracking_tools.py:72`).
6. Crackerjack: 0 files (no production callers).
7. Each replacement: leave a 2-line comment marking the wiring:
   `# Implements: REQ-004. See 2026-09-14-common-mcp-client-transport-unification.md §Phase 3.`
8. Merge order: mcp-common → mahavishnu (has the most callers;
   keep Dhara backward-compatible by also keeping its MCP HTTP-style
   mount active). Per `bodai-pre-1.0-merge-policy.md`, each repo
   merges to main pre-1.0.

#### Phase 3 Integration Contract

**Triggered from**:
- Bodai boot path: `mahavishnu mcp start`, `akosha mcp start`,
  `session-buddy mcp start`, `dhara mcp start` (each lifespan
  initializes its MCP-federation clients via
  `CommonMCPClient`).
- Runtime: any module that calls cross-server MCP (e.g., akosha's
  `_kg_refresh_loop` in `akosha/mcp/server.py:630-680`).

**Returns to / updates**:
- The actual tool-call results, fed into the same downstream callsite
  in each repo (e.g., akosha's `hot_store.query_traces()`,
  mahavishnu's `dhara_state.put()`).

**Demonstrable by**:
```bash
$ for repo in mahavishnu akosha session-buddy; do
    grep -rn '"/tools/call"' "$repo"/**/*.py | wc -l   # expect 0
  done
$ # Plus an end-to-end smoke test per repo:
$ pytest tests/integration/mcp/test_common_mcp_client.py -v
```

**Rollback signal**:
- `pytest` on any consumer repo fails on `tests/integration/mcp/test_common_mcp_client.py`.
- Bodai mcp server `/health` flips to 503 because the federation
  call raised an exception under new transport.

**Observability added**:
- `mcp_common.client.{tool}.duration_ms` metric histogram by server
  and outcome (`ok`/`timeout`/`error`).
- OTel span `mcp_common.client.call` (added in Phase 1) surfaces
  across every consumer.

### Phase 4: Unify `/health` aggregator

**Goal**: replace per-repo custom aggregator with `aggregate_feed_states`.

**Tasks**:
1. Add `<repo>/tests/integration/mcp/test_health_aggregator.py` per
   repo, asserting: time-bounded error decay works, warming_up
   predicate works, empty-but-running feeds report 200.
2. Replace each repo's `_default_health_probe` body with a
   single call:
   ```python
   from mcp_common.health import aggregate_feed_states
   aggregate_feed_states({
       "local_traces": local_traces_feed_state,  # already a HealthFeedState
       "code_graphs": code_graphs_feed_state,
       ...
   })
   ```
   Adjust the per-feed `FeedState` collection in each repo so the
   dataclasses conform to `HealthFeedState` (or wire a thin
   adapter in the repo).
3. Add `last_error_at` tracking to each feed-state mutation site
   (replace any naked `_errors_total += 1` with
   `record_error(feed_state)`).
4. Boots in this phase should leave `/health=200` for akosha
   immediately (the 10-cumulative-error case is now decayed).
   Per `feedback-flipping-degraded-feeds-without-fixing-source-causes-bad-signal`,
   document why this is honest: it's not a fix-by-masking; the
   source was already healthy when we measured it.

#### Phase 4 Integration Contract

**Triggered from**:
- Bodai launcher's wrapper script (`launch_with_healthcheck.sh`)
  polling `http://localhost:$PORT/health` every probe_interval_s.
- Operators reading `/health` directly.

**Returns to / updates**:
- `/health` JSON response body. Schema is unchanged at the top
  level (`{status, checks, ...}`) but each `checks[k]` adds:
  `reason_hints: list[str]`, `last_error_at: float | None`,
  `errors_within_window: int`.

**Demonstrable by**:
```bash
$ curl -fsS http://localhost:8682/health | jq .checks.local_traces_feed.ok
true           # was false with cumulative-error semantics
$ curl -fsS http://localhost:8682/health | jq .checks.local_traces_feed.reason_hints
["warming_up: empty alloy, no producers writing"]   # explicit narrative
$ # Plus the integration test
$ pytest tests/integration/mcp/test_health_aggregator.py::test_akOSHA_health_returns_200_after_halflife
```

**Rollback signal**:
- `/health` returns 5xx (server-side aggregator crashes).
- Operator notes a feed that is genuinely failing but `/health`
  says healthy (time-bounded decay swallowed a recent error);
  rollback by setting `HEALTH_FEED_HALFLIFE_SECONDS=0` env var
  for the affected process.

**Observability added**:
- `mcp_common.health.aggregate.duration_ms` histogram.
- Per-process `health.reason_hints_count` gauge.
- Structured log line `health.aggregate.complete` with `healthy`
  and `degraded` keys.

### Phase 5: HNSW-on-DuckDB fix (out-of-plan, documented separately)

This is a real but separate problem surfaced during diagnostics.
Tracked at `docs/followups/2026-09-14-akosha-hnsw-on-duckdb.md`.
Out of scope for THIS plan.

## 6. Required Code Changes

```yaml
mcp-common:
  - path: mcp-common/mcp_common/interfaces/__init__.py
    change: NEW
  - path: mcp-common/mcp_common/interfaces/common_mcp_client.py
    change: NEW (~120 LOC)
  - path: mcp-common/mcp_common/interfaces/health_feed.py
    change: NEW (~80 LOC)
  - path: mcp-common/mcp_common/health.py
    change: EDIT — append `aggregate_feed_states` function
  - path: mcp-common/tests/unit/interfaces/test_common_mcp_client.py
    change: NEW
  - path: mcp-common/tests/unit/interfaces/test_health_feed.py
    change: NEW
  - path: mcp-common/pyproject.toml
    change: EDIT — bump version 0.21.x → 0.22.0
  - path: mcp-common/CHANGELOG.md
    change: EDIT — add entry for SDK release

mahavishnu:
  - path: mahavishnu/mahavishnu/core/dhara_adapter.py
    change: REWRITE to delegate to CommonMCPClient; remove
      DharaClient.put/call_tool
  - path: mahavishnu/mahavishnu/core/state_backends/dhara.py
    change: REWRITE get/put/list_prefix/delete to delegate
  - path: mahavishnu/mahavishnu/core/evidence_store.py
    change: replace 2 call sites
  - path: mahavishnu/mahavishnu/core/evidence_retriever.py
    change: replace 2 call sites
  - path: mahavishnu/mahavishnu/core/evidence_collector.py
    change: replace 1 call site
  - path: mahavishnu/mahavishnu/ingesters/otel_ingester.py
    change: replace 3 call sites
  - path: mahavishnu/mahavishnu/mcp/health.py
    change: REWRITE _default_health_probe to call aggregate_feed_states
  - path: mahavishnu/mahavishnu/mcp/lifecycle.py
    change: replace ad-hoc DharaClient construction with CommonMCPClient
  - path: mahavishnu/mahavishnu/pools/session_buddy_pool.py
    change: replace 1 call site
  - path: mahavishnu/mahavishnu/pools/memory_aggregator.py
    change: replace 3 call sites
  - path: tests/unit/test_dhara_adapter.py
    change: UPDATE assertions to use CommonMCPClient mock
  - path: tests/integration/mcp/test_common_mcp_client.py
    change: NEW
  - path: tests/integration/mcp/test_health_aggregator.py
    change: NEW

akosha:
  - path: akosha/akosha/ingestion/code_graph_ingester.py
    change: replace 2 call sites
  - path: akosha/akosha/processing/fitness_analyzer.py
    change: replace 1 call site; fix DEFAULT_URL literal (Phase 2)
  - path: akosha/akosha/mcp/server.py
    change: replace 1 call site; replace _default_health_probe;
      fix DEFAULT_URL literal (Phase 2)
  - path: akosha/akosha/mcp/client.py
    change: REWRITE 3 call sites
  - path: akosha/akosha/storage/dhara_http_client.py
    change: REWRITE 2 call sites
  - path: tests/integration/mcp/test_common_mcp_client.py
    change: NEW
  - path: tests/integration/mcp/test_health_aggregator.py
    change: NEW

dhara:
  - path: dhara/dhara/mcp/server_core.py
    change: keep the existing /mcp/tools/call mount active; no
      call-site changes expected
  - path: tests/integration/mcp/test_common_mcp_client.py
    change: NEW (this is the consumer test for CommonMCPClient)

session-buddy:
  - path: session-buddy/session_buddy/server_optimized.py
    change: replace 1 call site
  - path: session-buddy/session_buddy/mcp/tools/session/channel_tracking_tools.py
    change: replace 1 call site
  - path: tests/integration/mcp/test_common_mcp_client.py
    change: NEW
  - path: tests/integration/mcp/test_health_aggregator.py
    change: NEW

crackerjack:
  - path: tests/integration/mcp/test_common_mcp_client.py
    change: NEW (smoke test against the published SDK)
```

## 7. Validation Matrix

| Tool / Command | Expected outcome | Evidence |
|---|---|---|
| `pytest mcp-common/tests/unit/interfaces/` | All new SDK tests pass; coverage ≥80% on new module | `mcp-common/htmlcov/` |
| `pytest mahavishnu/tests/integration/mcp/test_common_mcp_client.py -v` | Passes; logs OTel spans `mcp_common.client.call` | `pytest -v` stdout, Jaeger UI |
| `pytest akosha/tests/integration/mcp/test_health_aggregator.py::test_akosha_health_returns_200_after_halflife` | Passes | `pytest -v` |
| `grep -rn '"/tools/call"' {5 repos}/**/*.py \| wc -l` | `0` | shell exit code 0 |
| `grep -rn 'DEFAULT_URL.*"http://localhost:[0-9]*"' {5 repos}/**/*.py \| grep -v '/mcp"'` | empty | shell exit code 0 |
| `curl -fsS http://localhost:8682/health \| jq .status` | `"healthy"` (was `"degraded"` on 2026-09-14) | jq filter |
| `curl -fsS http://localhost:8682/health \| jq .checks.local_traces_feed.reason_hints` | non-empty array of explicit narrative strings | jq filter |
| `python scripts/audit_orphans.py` per repo | Zero per-repo copies of `f"{base}/tools/call"` patterns | shell exit code 0 |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Consumer repo merge order breaks a transitive caller temporarily | medium | Phase ordering: mcp-common first; ship test-only releases, then leaf repos (session-buddy, akosha), then load-bearing (mahavishnu, dhara) |
| CommonMCPClient session-ID handling differs subtly across FastMCP versions | medium | Phase 1 contract tests pin the behavior across versions 3.0-3.x; smoke test asserts compatibility |
| Time-bounded /health masks a real recent failure | low | Configurable halflife via `HEALTH_FEED_HALFLIFE_SECONDS` env var; rollback is a config change, not a redeploy |
| Launchd wrapper treats 503→200 flip as "service ready" before the agent actually responds | low | The wrapper polls `200` only when the proxy is ready; aggregator returning 200 implies services are healthy. Document in CHANGELOG. |
| Existing `/mcp/tools/call` mount on Dhara is needed by SOME caller we haven't enumerated | low | Phase 3 audit grep covers all 5 repos; `crackerjack` reports zero callers; `mahavishnu/ot/ingesters/otel_ingester.py` calls `:4318` directly, not via Dhara mount. The mount stays. |
| HNSW-on-DuckDB bug overshadows Phase 4 success | low | Separate plan tracked at `docs/followups/2026-09-14-akosha-hnsw-on-duckdb.md` |
| Per-repo tests rely on literal mock-URL strings; updating test files in lockstep is error-prone | medium | Phase 2 + Phase 3 do test-file updates in the SAME commit as the call-site changes; per-repo PR review covers both |
| `audit_orphans.py` in mahavishnu flags removed symbols per `crackerjack-ratchet-cli-defects.md` quirks | low | Re-run audit after each phase completion to confirm no regressions |

## 9. Decision Rule

Plan is "done enough" when:

1. Phases 1-4 merged to main on each of the 5 repos (5 merge commits
   minimum, not 5×4=20; commits get rebased to be logical units).
2. `mcp-common` published to PyPI (user-initiated per
   `crackerjack-version-bumping-manual.md`; coordinated via
   `docs/announcements/2026-09-14-mcp-transport-unification.md`).
3. Akosha's `/health` flapped to `200` with `reason_hints` populated,
   captured in `docs/announcements/2026-09-14-mcp-transport-unification.md`
   with the Before/After transcripts.
4. The 8 production REQ IDs are referenced via `# Implements: REQ-NNN`
   in the corresponding code/tests, traceable by
   `python scripts/audit_requirements.py` (or equivalent, once
   implemented).

Plan is **not** "done" when:
- `/health=503` is back (regression — rollback a phase).
- Any repo's `pytest` shows new failures from the migration.
- A consumer repo merges before `mcp-common`'s SDK release lands.

## 10. References

- `docs/plans/TEMPLATE.md` — plan template this document follows.
- `.claude/decisions/wire-up-contract.md` — policy this plan satisfies.
- `docs/schemas/document-frontmatter-v1.md` — frontmatter schema.
- `bodai-pre-1.0-merge-policy.md` — direct-to-main merge rule.
- `feedback-bodai-push-is-user-controlled` — never push without
  explicit user approval.
- `feedback-flipping-degraded-feeds-without-fixing-source-causes-bad-signal`
  — why Phase 4 (time-bounded semantics) is the honest fix.
- `docs/plans/2026-09-13-migrate-no-frontmatter-plans.md` — successful
  precedent for cross-store migration shape.
- `docs/followups/2026-09-14-akosha-hnsw-on-duckdb.md` — out-of-plan
  follow-up (Phase 5 stub).
