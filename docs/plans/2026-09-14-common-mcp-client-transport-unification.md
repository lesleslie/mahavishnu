---
status: draft
role: umbrella
kind: plan
date: 2026-09-14
last_reviewed: 2026-09-14
superseded_by: null
topic: mcp-transport-unification
revision: 2
---

# CommonMCPClient Transport Unification Across Bodai (v2)

> **v2 revision notes (2026-09-14)**: addresses structural findings from a 5-lens
> multi-agent review. Major changes from v1:
> - Phase 1 is now "extract `BodaiComponentMCPClient` from akosha into mcp-common"
>   rather than "write 120 LOC of new SDK" (saves ~90 LOC of duplicate code).
> - Phase 3 task explicitly removes the Dhara `/mcp/tools/call` HTTP-style mount
>   in the same commit as the `DharaServiceRegistryClient` caller removal.
> - Phase 4 keeps the `register_http_health_route` 200-always contract; the new
>   `status` enum (`healthy | warming_up | degraded | failed`) lives in the
>   body, **not** in the HTTP status code (the launchd wrapper relies on 200).
> - `mcp-common` version target corrected from 0.22.0 → 0.26.0 (current: 0.25.3).
> - Phase 1 SDK location: `mcp_common/clients/` (not `interfaces/`, which is
>   populated with `DualUseTool` / `ensure_dual_use`).
> - Merging order: `mcp-common → dhara → session-buddy → akosha → mahavishnu`
>   (bottom-up DAG; dhara is the deepest leaf).
> - REQ-007 + REQ-008 now have explicit Phase ownership markers in code.
> - 17+ test fixture sites added to Phase 2 audit.
> - `warming_up` overclaim split into two distinct success signals.

## 1. Outcome

Every Bodai MCP server ↔ MCP-server call uses FastMCP streamable-HTTP at
`/mcp` (JSON-RPC body) via a shared `CommonMCPClient` shipped from
`mcp-common`. Every Bodai MCP server's `/health` endpoint reports feed
state via a **time-bounded** aggregator. The aggregator's body uses a
4-value top-level `status` enum; HTTP code stays **200 always** to
preserve the existing `register_http_health_route` contract that 9
sibling servers and the launchd wrapper depend on.

**Two distinct success signals** (which v1 conflated):
1. **Warming-up narrative**: empty-feed + ingester-running case
   already ships in akosha today (per `akosha/mcp/server.py:790-806`).
   Phase 4 makes the narrative explicit in JSON instead of being
   buried in code comments — `status: "warming_up"` is conveyed in
   the body, the wrapper still sees 200.
2. **Time-bounded decay**: a feed whose latest error is older than
   `HEALTH_FEED_HALFLIFE_SECONDS` (default 300s) is reported as
   healthy even if `errors_total > 0`. This is the genuinely new
   Phase 1 + Phase 4 behavior.

## 2. Goals

1. Ship `mcp-common/mcp_common/clients/common_mcp_client.py` —
   extracted from `akosha/akosha/mcp/client.py:BodaiComponentMCPClient`
   (renamed and Bodai-flavored bits untangled). Add
   `mcp_common/health/feed.py` with the `HealthFeedState` dataclass
   + `aggregate_feed_states()` helper that produces the
   `status: healthy | warming_up | degraded | failed` enum and a
   `reason_codes: list[ReasonCode]` array.
2. Replace all 84 production `f"{base}/tools/call"` HTTP call sites
   across 5 repos with `await client.call(name=…, arguments=…)`.
   Merge order: `mcp-common → dhara → session-buddy → akosha →
   mahavishnu` (bottom-up DAG; no repo pulls a consumer before the
   server-2 dep is in place).
3. Remove the `DharaServiceRegistryClient` class in akosha AND the
   `@server.custom_route("/mcp/tools/call", ...)` handler in Dhara
   in the **same commit** (one-release deprecation window with
   `DhARA_LEGACY_TOOLS_CALL_ENABLED` env flag). After Phase 3 the
   `DharaServiceRegistryClient` has zero callers and the
   `Dhara /mcp/tools/call` mount has zero callers.
4. Standardize default URLs: every `<COMPONENT>_MCP_URL` env var
   default ends in `/mcp`. The 4 wrong-default sites (see §4.2) plus
   the 17+ test fixture sites (see §4.5) updated.
5. Per-repo `/health` aggregator delegates to `aggregate_feed_states`
   while preserving the existing `register_http_health_route`
   200-always contract. Each per-feed `ok` predicate becomes
   time-bounded.
6. After Phase 4 lands: akosha's `/health=200` `status: "warming_up"`
   with `reason_codes: ["warming_up_empty_feed"]` matches the runbook.
7. `mcp-common` coverage gate remains ≥80% post-rollout; per-repo
   coverage drops by no more than 0.5 percentage points without a
   compensating test.

## 3. Non-Goals

1. **HNSW-on-DuckDB bug** in akosha: `code_graphs_feed` repeatedly
   fails to create HNSW indexes because DuckDB has no native
   support. Tracked separately at
   `docs/followups/2026-09-14-akosha-hnsw-on-duckdb.md`. Out of
   scope here; the warming_up predicate is hardened below (§5 Phase
   4 task 6) so HNSW failures cannot masquerade as healthy.
2. **Streamable-HTTP session-ID state machine** in depth:
   streamable-HTTP session lifecycle (capability negotiation, peer
   negotiation, async generator fan-out). Existing per-tool pagination
   works; deeper coverage is out of scope.
3. **Streaming responses** (SSE for tool results exceeding the buffer
   threshold). All existing tools return ≤64KB JSON.
4. **TLS verification** between cross-server calls. Production mTLS
   via the existing `mcp_common.auth` token verifier is already in
   place.
5. **Renaming `HealthFeedState` field names** to be generic. The
   Bodai contract is the source of truth for the field vocabulary
   (`entities_count`, `last_updated_timestamp`, `cycles_total`,
   `errors_total`, `last_error_at`, `errors_within_window`); renaming
   would force30+ consumer call-site updates out of scope.
6. **Generalizing the SDK beyond MCP** (e.g., gRPC, raw TCP).
   `CommonMCPClient` is a common-Vocabulary MCP client, not a
   general-purpose RPC client.

## 4. Current Findings

### 4.1 Cross-server HTTP transport drift (84 production references)

```
$ grep -rn '/tools/call' session-buddy/ mahavishnu/ dhara/ akosha/ \
    --include='*.py' | grep -v __pycache__ | wc -l
84
mahavishnu: 34 sites
akosha:     33 sites (incl. 3 in DharaServiceRegistryClient)
dhara:      12 sites
session-buddy: 5 sites
crackerjack: 0 (uses local tools only)
```

The pattern is `f"{base_url}/tools/call"` in 84 production files.
Three transports co-exist on Bodai servers today:

```
POST http://localhost:8683/tools/call       →  404 (wrong - double-mount leak)
POST http://localhost:8678/mcp/tools/call   →  404 (wrong - Dhara-only quirk)
POST http://localhost:8683/mcp/tools/call   →  200 (Dhara default FastMCP mount)
POST http://localhost:8680/mcp              →  200 (universal, all servers)
POST http://localhost:8678/mcp              →  200 (universal, all servers)
```

Two of five patterns work universally. The 5-repos'd `f"{base}/tools/call"`
works against Dhara by accident; breaks against every other server.

### 4.2 Inconsistent default URLs (5 sites in 4 repos)

```
akosha/processing/fitness_analyzer.py:34    _DHARA_DEFAULT_URL = "http://localhost:8683"    ← no /mcp
akosha/mcp/server.py:52                    DHARA_DEFAULT_URL = "http://localhost:8683"    ← no /mcp
akosha/mcp/tools/__init__.py:238           default = "http://localhost:8683/mcp"           ← /mcp
akosha/mcp/tools/ecosystem_skills.py:115   default = "http://localhost:8683/mcp"           ← /mcp
akosha/storage/dhara_http_client.py:31     DHARA_DEFAULT_URL = "http://localhost:8683/mcp" ← /mcp
```

### 4.3 The Dhara `/mcp/tools/call` mount is hand-rolled, not a FastMCP default

```
dhara/dhara/mcp/server_core.py:693-770  @self.server.custom_route("/mcp/tools/call", methods=["POST"])
```

Docstring at line 693 states: *"REST-style tool call endpoint for
Akosha client compatibility. Akosha's DharaServiceRegistryClient
calls `{base_url}/tools/call` where `base_url` ends in `/mcp`,
producing `/mcp/tools/call`."*

**The active caller is** `akosha/akosha/mcp/client.py:170
DharaServiceRegistryClient` (3 call sites at lines 202, 226, 240).
There is exactly one caller; once Phase 3 deletes that caller, the
mount becomes dead public surface. Phase 3 commits must delete
both sides in the same change.

### 4.4 `BodaiComponentMCPClient` already implements the SDK

`akosha/akosha/mcp/client.py:31` defines `BodaiComponentMCPClient`
(137 LOC). It already does:
- Uses `mcp.client.streamable_http.streamable_http_client` (line 97-101).
- Manages session lifecycle through `ClientSession.__aenter__/__aexit__` (lines 103-106,161-167).
- Exposes `call_tool(name, arguments)` (line 110-128).
- SSRF protection via `_ALLOWED_SCHREFS = frozenset({"http", "https"})` (lines 45-60).

The plan extracts this class into `mcp-common/mcp_common/clients/`
as `CommonMCPClient`, untangling Bodai-flavored helpers (the
`query_local_traces` helpers at `akosha/mcp/client.py:130-158` stay
in akosha as a thin re-export shim). Adds a `timeout` kwarg.

### 4.5 Test-fixture coverage gap (17+ sites)

The Phase 2 grep at §6 won't catch fixture URLs. Sites already known
from a pre-plan audit:

```
akosha/tests/unit/test_mcp_phase0_registration.py:172, 205, 245, 250, 284, 317, 345, 394   — 8 fixtures
akosha/tests/unit/test_mcp_phase0_registration.py:284                                            — 1 host fixture
akosha/tests/unit/test_mcp_server_lifespan.py:96                                                — 1 fixture
akosha/tests/unit/mcp/test_client.py:207, 212, 230, 249, 271, 290, 309, 331, 344            — 9 fixtures
```

Plus unknowns in mahavishnu/dhara/session-buddy/crackerjack.
Phase 2 task list must include a *test-fixture* audit specifically.

### 4.6 Cumulative counter semantics

Same diagnostic surface as v1's §4.4. Plan's fix: time-bounded decay
(`last_error_at + errors_within_window`) and a `reason_codes`
vocabulary that distinguishes historical noise from active failure.

### 4.7 `warming_up` semantics are already shipping in akosha

`akosha/mcp/server.py:790-806` already implements `kg_warming_up`
(empty-feed-and-running returns 200). Phase 4 makes the narrative
explicit in the JSON body rather than buried in code comments; this
is a documentation/wire-format change, not a feature.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-001
    title: "CommonMCPClient extracted from akosha; streamable-HTTP JSON-RPC; session-ID lifecycle"
  - id: REQ-002
    title: "HealthFeedState exposes last_error_at + errors_within_window rolling counter"
  - id: REQ-003
    title: "aggregate_feed_states produces 4-value top-level status enum + reason_codes enum"
  - id: REQ-004
    title: "All 84 production /tools/call sites replaced with CommonMCPClient"
  - id: REQ-005
    title: "<COMPONENT>_MCP_URL defaults (4 prod + 17 test fixtures) end in /mcp"
  - id: REQ-006
    title: "Each repo's /health aggregator delegates to aggregate_feed_states"
  - id: REQ-007
    title: "Cumulative feed errors do not block /health=200 after halflife elapses"
  - id: REQ-008
    title: "Empty-feed + ingester-running reports status: warming_up with reason_codes: [warming_up_empty_feed]"
  - id: REQ-009
    title: "Cross-repo smoke test: akosha → session-buddy via CommonMCPClient returns non-empty"
```

All 9 REQ IDs are referenced from at least one Phase's Integration
Contract Demonstrable-by (§5). REQ-007 and REQ-008 have explicit
Phase-4 ownership via the `# Implements: REQ-007` / `# Implements:
REQ-008` markers in the cited call sites.

## 5. Implementation Phases

### Phase 1: Extract `CommonMCPClient` from akosha into mcp-common

**Goal**: ship the SDK as a thin rename of an existing 137-LOC class.

**Tasks**:
1. Confirm `mcp-common/mcp_common/clients/` package does not yet exist
   (`interfaces/` is populated with `DualUseTool`; do not touch it).
2. Move `akosha/akosha/mcp/client.py:BodaiComponentMCPClient` to
   `mcp-common/mcp_common/clients/common_mcp_client.py`, renamed
   `CommonMCPClient`. Keep `mcp.client.streamable_http.streamable_http_client`
   transport; keep `ClientSession` lifecycle; keep SSRF guard. Add a
   `timeout: float | None = 5.0` kwarg to `call_tool()`.
3. Akosha keeps a thin re-export shim
   `akosha/mcp/client.py:BodaiComponentMCPClient = CommonMCPClient`
   for one minor release.
4. Add `mcp-common/mcp_common/health/feed.py` with `HealthFeedState`
   dataclass fields: `entities_count`, `last_updated_timestamp`,
   `cycles_total`, `errors_total`, `last_error_at: float | None`,
   `errors_within_window: int`, `first_unhealthy_at: float | None`,
   `ingester_running: bool`. Helpers:
   `record_success(state)` resets `errors_within_window` AND clears
   `first_unhealthy_at` (the field tracks the *entry* into
   unhealthy state — clearing it on success lets the next
   unhealthy entry reset the burn-rate anchor); `record_error(state)`
   updates `last_error_at` and sets `first_unhealthy_at` on the
   healthy→unhealthy transition (idempotent on subsequent errors).
   `is_healthy(state, halflife_seconds=300)` returns
   `(healthy: bool, status: StatusValue, reason_codes: list[ReasonCode])`.
   `StatusValue` and `ReasonCode` are `str, Enum`s with values
   defined in §5 Phase 4 task 5.
5. Add `mcp-common/mcp_common/health/aggregator.py` with
   `aggregate_feed_states(states: dict[str, HealthFeedState], halflife_seconds=300) ->
   dict` returning:
   ```json
   {"status": "healthy", "checks": {<feed>: {...}}, "reason_codes": [...]}
   ```
   `status` is the worst-case across all feeds:
   `failed > degraded > warming_up > healthy`.
6. Bump `mcp-common` version `0.25.3 → 0.26.0` (semver-minor,
   additive public surface). Per `crackerjack-version-bumping-manual.md`,
   the user initiates the PyPI publish; the plan's exit criteria
   mark "user has approved the publish" as Phase 1 done.
7. Tests (`mcp-common/tests/unit/clients/test_common_mcp_client.py`):
   - **Wire-shape contract tests** (3): JSON-RPC envelope shape;
     `Mcp-Session-Id` header sent on second request, not first;
     response body parsed from `result.payload`.
   - **Negative tests** (4): `{"error":{...}}` envelope raises;
     5xx raises `MCPClientHTTPError`; `httpx.ReadTimeout` raises
     `MCPClientTimeoutError`; malformed JSON raises.
   - **Lifecycle** (4): session-ID handshake after first response;
     reconnect on 410 with new session-ID; multiple calls reuse
     session; SSRF guard rejects `file://`.
   - Mark each test with `@pytest.mark.req(["REQ-001"])`.
   - **Akosha-side behavior tests** to migrate alongside
     `BodaiComponentMCPClient` extraction: the tests currently
     in `akosha/tests/unit/mcp/test_client.py` and
     `akosha/tests/unit/test_mcp_phase0_registration.py`
     that assert specific `BodaiComponentMCPClient.call_tool`
     behavior (session-ID reuse, error envelope unwrap, JSON-RPC
     envelope shape). These tests should be re-pinned to
     `CommonMCPClient` (or — if the test exists in the new
     `mcp-common/tests/unit/clients/test_common_mcp_client.py`
     as one of the 11 above — deleted from akosha in
     the same commit, with a deprecation line indicating the
     canonical test now lives in mcp-common).
8. Tests (`mcp-common/tests/unit/health/test_aggregator.py`):
   - `is_healthy_true_when_no_errors`
   - `is_healthy_true_when_error_outside_halflife` (marks
     REQ-007)
   - `is_degraded_when_error_within_halflife` (marks REQ-007)
   - `is_warming_up_when_empty_and_no_errors_and_ingester_running`
     (marks REQ-008)
   - `aggregate_picks_worst_status` (failed > degraded >
     warming_up > healthy)
   - Mark each with `@pytest.mark.req(["REQ-002","REQ-003","REQ-007","REQ-008"])`.

#### Phase 1 Integration Contract

**Triggered from**:
- Library import only at this stage; no production runtime caller
  yet. The first production caller is wired in **Phase 3** when
  `akosha/mcp/client.py` (the `BodaiComponentMCPClient` re-export
  shim) and `mahavishnu/core/dhara_adapter.py` import from
  `mcp_common.clients`. Rationale: SDK deliverable; wiring is a
  downstream Phase 3 task that requires the SDK to exist first.

**Returns to / updates**:
- `mcp-common/mcp_common/clients/common_mcp_client.py` (new
  home of the renamed class).
- `mcp-common/mcp_common/health/feed.py` (new `HealthFeedState`
  dataclass + helpers).
- `mcp-common/mcp_common/health/aggregator.py` (new
  `aggregate_feed_states` function).

**Demonstrable by** (single command):
```bash
$ pytest mcp-common/tests/unit/clients/ mcp-common/tests/unit/health/ -v \
    --cov=mcp_common --cov-fail-under=80
```
(Implements REQ-001, REQ-002, REQ-003.)

**Rollback signal**:
- The pytest above exits non-zero.
- `mcp-common/scripts/smoke_common_mcp_client.py` (operable
  without consumer-repo dependency, see below) exits non-zero
  against any of `{localhost:8678/mcp, localhost:8682/mcp, localhost:8683/mcp, localhost:8676/mcp}`.

**Observability added**:
- OTel span `mcp_common.client.call` (collector: standard OTel
  pipeline via `mahavishnu/observability/sampler.py`) with
  attributes `mcp_server`, `tool`, `jsonrpc.id`, `duration_ms`,
  `status`.
- OTel event `mcp_common.client.session.reconnect` on 401/410.
- Structured log line `mcp_common.client.{tool}` at INFO with
  `outcome, duration_ms` keys; WARNING if timeout; ERROR on 5xx.
  Destination: Oneiric logger (`oneiric.logging`, configured in
  `settings/mahavishnu.yaml`) → stdout in dev / Loki in prod.
- Standalone smoke scripts in `mcp-common/scripts/`:
  - `smoke_common_mcp_client.py` (CLI: `--target URL --tool NAME`).
  - `smoke_health_feed.py` (offline, in-memory).

### Phase 2: Standardize env defaults (production + test fixtures)

**Goal**: every `<COMPONENT>_MCP_URL` default ends in `/mcp`. Both
production code AND test fixtures updated.

**Tasks**:
1. Audit (5 repos): `grep -rn 'DEFAULT_URL.*"http://localhost:[0-9]*"\|setenv.*MCP_URL.*"http\|base_url="http://[a-z]*:[0-9]*"' {5 repos} --include='*.py' | grep -v __pycache__`.
2. Update production sites (4 known): `akosha/processing/fitness_analyzer.py:34`,
   `akosha/mcp/server.py:52`, plus equivalent literals in `mahavishnu/...`,
   `dhara/...` (lines TBD by Task 1 grep).
3. Update test-fixture sites (17+ known — see §4.5): append `/mcp`
   to `monkeypatch.setenv("DHARA_MCP_URL", ...)` and `base_url="..."`
   literals. Same-commit rule.
4. Each update leaves a 2-line marker: `# Implements: REQ-005`.
   See `2026-09-14-common-mcp-client-transport-unification.md` §Phase 2.

#### Phase 2 Integration Contract

**Triggered from**:
- Boot-time env-var lookup in each repo's Oneiric config loader:
  `mahavishnu.core.config.load_settings()`,
  `akosha.mcp.server._load_dhara_url()` (line 271 of
  `akosha/mcp/server.py`),
  `akosha.processing.fitness_analyzer.__init__` (line 91),
  `dhara.dhara.config.load_settings()`. These are the existing
  entry points that read `*_MCP_URL` env vars.

**Returns to / updates**:
- Updated URL strings at the four production literal sites:
  - `akosha/akosha/processing/fitness_analyzer.py:34`
  - `akosha/akosha/mcp/server.py:52`
  - `mahavishnu/<TBD by audit>` and `dhara/<TBD by audit>`
- Test-fixture URLs at the 17+ known sites plus any discovered
  by Task 1 grep (specifically: `akosha/tests/unit/test_mcp_phase0_registration.py`,
  `akosha/tests/unit/test_mcp_server_lifespan.py`,
  `akosha/tests/unit/mcp/test_client.py` and their equivalents
  in other repos).
- Same-commit marker comments per §6 requirements.

**Demonstrable by** (single command; covers both prod and fixtures):
```bash
$ grep -rn \
    -e 'DEFAULT_URL.*"http://localhost:[0-9]*"' \
    -e 'setenv.*MCP_URL.*"http' \
    -e 'base_url="http://[a-z]*:[0-9]*"' \
    {5 repos}/**/*.py | grep -v '/mcp"' | wc -l
0
```
(Implements REQ-005.)

**Rollback signal**:
- The grep above returns >0.
- Any Bodai server fails to bind during `launch_with_healthcheck.sh`
  probe cycle (the new default URL fails the `_load_dhara_url` call).

**Observability added**:
- Structured log line `mcp_common.client.url_normalized` at startup
  with keys `from`, `to`, `env_var` — confirms operator can audit
  effective URLs per process.

### Phase 3: Migrate all 84 call sites to `CommonMCPClient`

**Goal**: every cross-server POST in production uses `client.call(...)`.

**Tasks**:
1. Per-repo worktree fan-out. Each repo gets one worktree, one
   branch (`fix/common-mcp-client-migration`), one commit that
   does the file-by-file replacement. Per
   `feedback-flipping-degraded-feeds-without-fixing-source-causes-bad-signal`,
   the migration order is bottom-up DAG: dhara → session-buddy →
   akosha → mahavishnu. (mcp-common itself is Phase 1; published
   0.26.0 before any migration commit lands.)
2. **Dhara**: replace `DharaServiceRegistryClient`
   (`akosha/mcp/client.py:170`) and the three call sites
   (lines 202, 226, 240). After this commit: zero callers of
   `DharaServiceRegistryClient`. Leave the Dhara
   `_register_tools_call_route` method in place for this
   release — but **gate it behind `DhARA_LEGACY_TOOLS_CALL_ENABLED`
   env flag** (default `true` for one release, default `false`
   next minor). Emit `WARNING: dhara /mcp/tools/call is
   deprecated; will be removed in the next minor release.
   Set `DhARA_LEGACY_TOOLS_CALL_ENABLED=false` to disable.`
   once per process at startup. The route + flag are
   removed together in the next minor release — that
   combined commit is the Phase 5 followup and is out of
   scope here.
3. **Session-Buddy**: replace 5 sites at `server_optimized.py:118`,
   `channel_tracking_tools.py:72`, plus any discovered by audit grep.
4. **Akosha**: replace 33 sites (excluding the 3 already done
   in Task 2): `ingestion/code_graph_ingester.py:157, 208`;
   `processing/fitness_analyzer.py:189`; `mcp/server.py:227`;
   `storage/dhara_http_client.py:82, 103`; `mcp/tools/ecosystem_skills.py`
   needs no changes (already uses streamable-HTTP).
5. **Mahavishnu**: replace 34 sites. Mostly 1-to-1 substitutions:
   `evidence_store.py:44, 102`; `evidence_retriever.py:125, 172`;
   `evidence_collector.py:39`; `otel_ingester.py:236, 289, 326`;
   `memory_aggregator.py:366, 568, 640`; `session_buddy_pool.py:97`;
   `core/dhara_adapter.py` is rewritten in place.
6. Each replacement carries a 2-line marker:
   `# Implements: REQ-004`.

#### Phase 3 Integration Contract

**Triggered from**:
- Bodai boot path: `mahavishnu mcp start`, `akosha mcp start`,
  `session-buddy mcp start`, `dhara mcp start` (each lifespan
  initializes its MCP-federation clients via `CommonMCPClient`).
- Runtime: any module that calls cross-server MCP (e.g., akosha's
  `_kg_refresh_loop()` at `akosha/mcp/server.py:630-680`;
  mahavishnu's `memory_aggregator.py:_call_session_buddy()`;
  session-buddy's `server_optimized.py:_federate_to_dhara()`).

**Returns to / updates**:
- Cross-server tool-call JSON-RPC results are returned in-process
  to the calling module's local variables. Phase 3 itself does NOT
  persist. Downstream code at each call site then writes to its
  own existing destination, which is unchanged by this phase:
  - `akosha.mcp.server._kg_refresh_loop()` →
    `hot_store.query_traces()` →
    DuckDB at `~/.akosha/local_traces.duckdb`
  - `mahavishnu.core.dhara_adapter.get/put()` →
    Dhara KV at `~/.dhara/kv/<namespace>/<key>`
  - `session_buddy.server_optimized` →
    in-memory dispatch table
  - `mahavishnu.otel_ingester.query_remote_spans()` →
    `otel_traces/<service.name>`
  Rationale: Phase 3 changes the *transport* (HTTP `/tools/call` →
  streamable-HTTP JSON-RPC), not the *destination*.

**Demonstrable by** (single command):
```bash
$ pytest tests/integration/mcp/test_common_mcp_client.py -v
```
including `tests/integration/mcp/test_cross_repo_smoke.py`
which spins up akosha + session-buddy in subprocesses and asserts
`akosha → session-buddy liveness` returns non-empty over the new
SDK. (Implements REQ-004, REQ-009.)

**Rollback signal**:
- The pytest above exits non-zero.
- Bodai mcp server `/health` flips to 503 because the federation
  call raised an exception under new transport.
- `mcp-common/scripts/smoke_common_mcp_client.py` exits non-zero.

**Observability added**:
- `mcp_common.client.{tool}.duration_ms` metric histogram by
  server and outcome (`ok`/`timeout`/`error`), labels include
  `mcp_server`, `tool`.
- OTel span `mcp_common.client.call` from Phase 1 surfaces in
  every consumer.

### Phase 4: Unify `/health` aggregator to `aggregate_feed_states`

**Goal**: replace per-repo custom aggregator with
`aggregate_feed_states`. Preserve the
`register_http_health_route` 200-always contract (the launchd
wrapper relies on 200).

**Tasks**:
1. Add `<repo>/tests/integration/mcp/test_health_aggregator.py`
   per repo asserting: time-bounded decay works; warming_up
   predicate works; empty-but-running feeds report 200; HNSW
   failures cannot masquerade as warming_up; reason_codes populates.
2. Replace each repo's `_default_health_probe` body with one call:
   ```python
   from mcp_common.health.aggregator import aggregate_feed_states
   return aggregate_feed_states({
       "local_traces": local_traces_state,    # HealthFeedState
       "code_graphs": code_graphs_state,
       ...
   }, halflife_seconds=int(os.getenv("HEALTH_FEED_HALFLIFE_SECONDS", "300")))
   ```
   HTTP code stays **200 always** (per existing 503-reserved-for-
   /readyz contract in `mcp-common/mcp_common/health.py:836-839`).
   Body adds the `status` enum and `reason_codes` array.
3. Wire `last_error_at` tracking at each per-feed mutation site
   (`hot_store.insert(record)` failure path,
   `code_graph_ingester._ingest_graph()` failure path, etc.).
4. Wire `HealthFeedState.ingester_running` flag at each producer
   task's lifecycle (start/stop).
5. Define the enums in `mcp-common/mcp_common/health/feed.py`
   using `class StatusValue(str, Enum)` and `class ReasonCode(str, Enum)`
   patterns (per Phase 1 task 4):

   ```python
   class StatusValue(str, Enum):
       HEALTHY = "healthy"
       WARMING_UP = "warming_up"
       DEGRADED = "degraded"
       FAILED = "failed"

   class ReasonCode(str, Enum):
       WARMING_UP_EMPTY_FEED = "warming_up_empty_feed"
       WARMING_UP_NEVER_CYCLED = "warming_up_never_cycled"
       INGESTER_NOT_RUNNING = "ingester_not_running"
       FEED_NEVER_POPULATED = "feed_never_populated"
       RECENT_ERROR_IN_WINDOW = "recent_error_in_window"
       NO_PRODUCER_EVER_CYCLED = "no_producer_ever_cycled"
       PRODUCER_NOT_ALIVE = "producer_not_alive"
   ```

   `aggregate_feed_states()` picks worst-status across all feeds
   in order `failed > degraded > warming_up > healthy` (see Phase 1
   test `aggregate_picks_worst_status`). Aggregate pulls a
   `reason_codes` enum from the worst feed's state.
6. **Hardening against HNSW-on-DuckDB** (out-of-plan bug): the
   `warming_up` predicate requires `cycles_total > 0 AND
   last_error_at IS NOT None`. A feed where the very first cycle
   raises is **not** warming_up — it's `degraded: feed_never_populated`.
   Mark with `# Implements: REQ-008`.
7. Per-repo CLI flag `--health-disable-decay` for ops emergency:
   emits `WARNING: HEALTH_FEED_HALFLIFE_SECONDS=0; time-bounded
   semantics disabled` at startup; emits OTel event
   `health.aggregate.decay_disabled`; documented in
   `docs/runbooks/health_reason_codes.md`.

#### Phase 4 Integration Contract

**Triggered from**:
- Bodai launcher's wrapper script (`launch_with_healthcheck.sh`)
  polling `GET /health` every probe_interval_s.
- Operators reading `/health` directly via `curl -fsS | jq`.

**Returns to / updates**:
- `/health` JSON response body. Schema at top level
  (`{status, checks, reason_codes, ...}`) and per-feed
  (`checks[k]` gets `reason_codes: list[ReasonCode]`).
- Returns HTTP 200 unconditionally; body `status` carries
  the operator-facing signal.

**Demonstrable by** (single command):
```bash
$ pytest tests/integration/mcp/test_health_aggregator.py::test_akosha_health_returns_200_when_errors_outside_halflife -v
```
(Body assertion: `.checks.local_traces.reason_codes ==
["warming_up_empty_feed"]` and `.status == "warming_up"`. Implements
REQ-006, REQ-007, REQ-008.)

**Rollback signal**:
- `/health` returns 5xx (server-side aggregator crashes).
- PromQL alert:
  `mcp_common_health_halflife_seconds{repo="X"} == 0` for >5m
  — flags silent decode disable.

**Observability added**:
- `mcp_common.health.aggregate.duration_ms` histogram.
- `mcp_common_health_halflife_seconds{repo}` gauge.
- `health.feed.errors_within_window{repo, feed}` gauge.
- Structured log line `health.aggregate.complete` with
  `healthy` and `degraded` keys.
- New runbook: `docs/runbooks/health_reason_codes.md` —
  one section per `ReasonCode` enum value, mapping to operator
  action (monitor 60s, no restart) vs. escalation.

### Phase 5: HNSW-on-DuckDB fix (out-of-plan, separate followup)

Tracked at `docs/followups/2026-09-14-akosha-hnsw-on-duckdb.md`.

## 6. Required Code Changes

```yaml
mcp-common:
  - path: mcp-common/mcp_common/clients/__init__.py
    change: NEW
  - path: mcp-common/mcp_common/clients/common_mcp_client.py
    change: NEW (extracted from akosha/akosha/mcp/client.py:BodaiComponentMCPClient;
      unchanged behavior except timeout kwarg)
  - path: mcp-common/mcp_common/health/feed.py
    change: NEW (~80 LOC; HealthFeedState + StatusValue + ReasonCode enums)
  - path: mcp-common/mcp_common/health/aggregator.py
    change: NEW (~50 LOC; aggregate_feed_states())
  - path: mcp-common/tests/unit/clients/test_common_mcp_client.py
    change: NEW (11 tests; see Phase 1 task 7)
  - path: mcp-common/tests/unit/health/test_feed.py
    change: NEW (5 tests)
  - path: mcp-common/tests/unit/health/test_aggregator.py
    change: NEW (4 tests)
  - path: mcp-common/scripts/smoke_common_mcp_client.py
    change: NEW (operator-runnable offline smoke)
  - path: mcp-common/scripts/smoke_health_feed.py
    change: NEW (operator-runnable offline smoke)
  - path: mcp-common/pyproject.toml
    change: EDIT — bump 0.25.3 → 0.26.0
  - path: mcp-common/CHANGELOG.md
    change: EDIT — add entry for SDK extraction release
  - path: mcp-common/mcp_common/interfaces/__init__.py
    change: UNTOUCHED (already exports DualUseTool, ensure_dual_use)

dhara:
  - path: dhara/dhara/mcp/server_core.py
    change: GATE the `_register_tools_call_route` method
      (lines 693-770) behind `DhARA_LEGACY_TOOLS_CALL_ENABLED`
      env flag. Default `true` for one release (current),
      default `false` next minor. Emit a single WARNING line
      at startup when the flag is `true` (route active).
  - path: tests/integration/mcp/test_common_mcp_client.py
    change: NEW (consumer test for CommonMCPClient → dhara KV)

session-buddy:
  - path: session-buddy/session_buddy/server_optimized.py
    change: replace 1 call site at line 118
  - path: session-buddy/session_buddy/mcp/tools/session/channel_tracking_tools.py
    change: replace 1 call site at line 72
  - path: tests/integration/mcp/test_common_mcp_client.py
    change: NEW
  - path: tests/integration/mcp/test_health_aggregator.py
    change: NEW

akosha:
  - path: akosha/akosha/mcp/client.py
    change: REMOVE `DharaServiceRegistryClient` class (lines 31-260);
      keep `BodaiComponentMCPClient` as `= CommonMCPClient` re-export
      shim (one minor release)
  - path: akosha/akosha/ingestion/code_graph_ingester.py
    change: replace 2 call sites at lines 157, 208
  - path: akosha/akosha/processing/fitness_analyzer.py
    change: replace 1 call site at line 189; fix _DHARA_DEFAULT_URL
      literal at line 34 (Phase 2)
  - path: akosha/akosha/mcp/server.py
    change: replace 1 call site at line 227; replace
      _default_health_probe; fix DHARA_DEFAULT_URL literal at
      line 52 (Phase 2)
  - path: akosha/akosha/storage/dhara_http_client.py
    change: replace 2 call sites (lines 82, 103)
  - path: akosha/tests/unit/test_mcp_phase0_registration.py
    change: 8 `monkeypatch.setenv` URLs to end in /mcp (Phase 2)
  - path: akosha/tests/unit/test_mcp_phase0_registration.py
    change: 1 `setenv("DHARA_MCP_URL", "http://custom-dhara:9999")` → add /mcp (Phase 2)
  - path: akosha/tests/unit/test_mcp_server_lifespan.py
    change: 1 fixture URL at line 96 (Phase 2)
  - path: akosha/tests/unit/mcp/test_client.py
    change: 9 `base_url="..."` fixtures at lines 207-344 (Phase 2)
  - path: tests/integration/mcp/test_common_mcp_client.py
    change: NEW
  - path: tests/integration/mcp/test_health_aggregator.py
    change: NEW

mahavishnu:
  - path: mahavishnu/mahavishnu/core/dhara_adapter.py
    change: REWRITE — delegate get/put/list_prefix/delete to
      CommonMCPClient; remove DharaClient direct call_tool
  - path: mahavishnu/mahavishnu/core/state_backends/dhara.py
    change: REWRITE get/put/list_prefix/delete to delegate via
      CommonMCPClient
  - path: mahavishnu/mahavishnu/core/evidence_store.py
    change: replace 2 call sites (lines 44, 102)
  - path: mahavishnu/mahavishnu/core/evidence_retriever.py
    change: replace 2 call sites (lines 125, 172)
  - path: mahavishnu/mahavishnu/core/evidence_collector.py
    change: replace 1 call site at line 39
  - path: mahavishnu/mahavishnu/ingesters/otel_ingester.py
    change: replace 3 call sites (lines 236, 289, 326)
  - path: mahavishnu/mahavishnu/mcp/health.py
    change: REWRITE _default_health_probe to delegate to
      aggregate_feed_states (Phase 4)
  - path: mahavishnu/mahavishnu/mcp/lifecycle.py
    change: replace ad-hoc DharaClient construction with
      CommonMCPClient; remove DharaKvClient (DONE in
      commit 6da50168 of this session)
  - path: mahavishnu/mahavishnu/pools/session_buddy_pool.py
    change: replace 1 call site at line 97
  - path: mahavishnu/mahavishnu/pools/memory_aggregator.py
    change: replace 3 call sites (lines 366, 568, 640)
  - path: tests/unit/test_dhara_adapter.py
    change: UPDATE assertions to mock CommonMCPClient instead of
      mock DharaClient (Phase 3)
  - path: tests/integration/mcp/test_common_mcp_client.py
    change: NEW
  - path: tests/integration/mcp/test_cross_repo_smoke.py
    change: NEW (akosha + session-buddy in subprocesses; REQ-009)
  - path: tests/integration/mcp/test_health_aggregator.py
    change: NEW

crackerjack:
  - path: tests/integration/mcp/test_common_mcp_client.py
    change: NEW (smoke test against the published SDK)
```

## 7. Validation Matrix

| Tool / Command | Expected outcome | Evidence location | Implemented by |
|---|---|---|---|
| `pytest mcp-common/tests/unit/clients/ mcp-common/tests/unit/health/ -v --cov=mcp_common --cov-fail-under=80` | All 20 tests pass; coverage ≥80% | `mcp-common/htmlcov/`, exit 0 | REQ-001/002/003 |
| `python mcp-common/scripts/smoke_common_mcp_client.py --target http://localhost:8678/mcp --tool session_buddy_get_liveness` | Exit 0; prints `{"status":"ok", ...}` | script stdout | REQ-001 |
| `python mcp-common/scripts/smoke_health_feed.py` | Exit 0; prints time-bounded decay narrative | script stdout | REQ-002/007/008 |
| `grep -rn -e 'DEFAULT_URL.*"http://localhost:[0-9]*"' -e 'setenv.*MCP_URL.*"http' -e 'base_url="http://[a-z]*:[0-9]*"' {5 repos}/**/*.py \| grep -v '/mcp"' \| wc -l` | `0` | shell exit 0 | REQ-005 |
| `pytest tests/integration/mcp/test_common_mcp_client.py` | Passes; logs OTel spans `mcp_common.client.call` per consumer-repo | `pytest -v` stdout | REQ-004 |
| `pytest tests/integration/mcp/test_cross_repo_smoke.py -v` (one consumer + one producer + one observer in subprocesses; akosha → session-buddy liveness) | Passes | `pytest -v` stdout | REQ-009 |
| `pytest tests/integration/mcp/test_health_aggregator.py::test_akosha_health_returns_200_when_errors_outside_halflife -v` | Passes; assertion `.checks.local_traces.reason_codes == ["warming_up_empty_feed"]` and `.status == "warming_up"` | `pytest -v` stdout | REQ-006/007/008 |
| `curl -fsS http://localhost:8682/health` | HTTP 200 (always), body `status` in `{healthy, warming_up, degraded, failed}` | jq filter | REQ-006 |
| `python scripts/audit_orphans.py` per repo | Zero `f"{base}/tools/call"` patterns; zero `DharaServiceRegistryClient` references post-Phase 3 | shell exit 0 | REQ-004 |
| `git grep -n DhARA_LEGACY_TOOLS_CALL_ENABLED dhara/` | Single hit at the env-flag declaration (a one-release deprecation window) | grep exit 0 | — |

## 8. Risks

| Risk | Likelihood | Mitigation | Realism |
|---|---|---|---|
| Merge order: dhara → session-buddy → akosha → mahavishnu but a consumer pulls in a not-yet-merged server dep | medium | Phase 1 lands first and is published as `0.26.0` before any Phase 3 commit. Consumer commits include a `pyproject.toml` constraint `mcp-common>=0.26.0,<0.27.0`. | partially mitigates |
| `CommonMCPClient` session-ID handling differs subtly across FastMCP versions | low | Phase 1 contract tests pin the wire shape (JSON-RPC envelope + header behavior) so any SDK regression is caught at PR time. Plus `fastmcp` constraint locked to `~=3.4` in `mcp-common/pyproject.toml`. | mitigates |
| Time-bounded `/health` halflife could mask a real recent failure | medium | New alert: `mcp_common_health_feed.errors_within_window{repo, feed} > 5 for 2m` — independent of the body `status`. Decay escape hatch visible via `--health-disable-decay` startup log. | partially mitigates |
| `HNSW-on-DuckDB` bug initially satisfies warming_up predicate (empty + running + no errors at first cycle) | medium | Phase 4 task 6: warming_up requires `cycles_total > 0 AND last_error_at IS NOT None`. A feed where first cycle raises goes to `degraded: feed_never_populated`. | mitigates |
| Launchd wrapper treats degraded-but-200 as service ready | low | `launch_with_healthcheck.sh:89` (`curl -fsS`) treats 2xx as success; we keep 200-always. Body `status` carries the operator-facing signal. | mitigates |
| Existing `/mcp/tools/call` mount on Dhara is needed by an un-enumerated caller | low (now) | One-release deprecation window via `DhARA_LEGACY_TOOLS_CALL_ENABLED` env flag. Audit grep across all 5 repos during Phase 3 confirms no remaining callers. | partially mitigates |
| Per-repo tests rely on literal mock-URL strings | medium | Same-commit rule for both production and test-fixture URLs (Phase 2). 17+ known fixture sites enumerated explicitly in §6. | mitigates |
| `audit_orphans.py` quirks (`crackerjack-ratchet-cli-defects.md`) | low | Phase 4 §7 Validation Matrix adds `python scripts/audit_orphans.py` per repo as automated acceptance; `audit_requirements.py` enforces REQ traceability via `@pytest.mark.req(["REQ-NNN"])` markers (added in Phase 1 task 7). | partially mitigates |
| Plan published 0.26.0 with breaking changes vs. 0.25.3 | medium | Phase 1 ships `0.26.0` (additive new public surface; existing mcp-common API unchanged). Public surface (`interfaces/__init__.py:DualUseTool`, etc.) is unaffected. | mitigates |

## 9. Decision Rule

Plan is "done enough" when:

1. Phases 1-4 merged to main on each of the 5 repos **in the
   declared bottom-up DAG order**: mcp-common first; then dhara
   (with the `DharaServiceRegistryClient` + mount removal in one
   commit); then session-buddy; then akosha; then mahavishnu.
2. `mcp-common` published to PyPI as `0.26.0` — **user-initiated**
   per `crackerjack-version-bumping-manual.md`. The user
   explicitly approves the publish; do NOT push without
   authorization (per `feedback-bodai-push-is-user-controlled.md`).
3. The 9 production REQ IDs (REQ-001 … REQ-009) are referenced
   via `@pytest.mark.req(["REQ-NNN"])` in the corresponding
   tests, traceable by `python scripts/audit_requirements.py` (or
   equivalent once implemented).
4. Akosha's `/health` returns HTTP 200 always (per the
   preserved contract) with body `status == "warming_up"` and
   `reason_codes == ["warming_up_empty_feed"]`, captured in
   `docs/announcements/2026-09-14-mcp-transport-unification.md`
   with before/after transcripts.
5. `docs/runbooks/health_reason_codes.md` is merged and linked
   from the new alert annotations in
   `mahavishnu/config/alerts/akosha_feed_degradation.yml`.
6. The `DhARA_LEGACY_TOOLS_CALL_ENABLED` env flag is wired with a
   one-release deprecation log line; `git grep` for `DhARA_LEGACY_TOOLS_CALL_ENABLED` returns exactly one hit
   in `dhara/`.

Plan is **not** "done" when:
- `/health` returns non-2xx (regression — 200-always contract
  violated).
- `f"{base}/tools/call"` reappears in any production call site.
- A consumer repo merges before mcp-common's `0.26.0` is
  published.
- `audit_requirements.py` reports REQ IDs declared but not
  tested.

## 10. References

- `docs/plans/TEMPLATE.md` — plan template this document follows.
- `.claude/decisions/wire-up-contract.md` — Integration Contract policy.
- `docs/schemas/document-frontmatter-v1.md` — frontmatter schema.
- `bodai-pre-1.0-merge-policy.md` — direct-to-main merge rule.
- `feedback-bodai-push-is-user-controlled.md` — never push
  without explicit user approval.
- `feedback-flipping-degraded-feeds-without-fixing-source-causes-bad-signal`
  — why Phase 4 (time-bounded semantics) is the honest fix.
- `crackerjack-version-bumping-manual.md` — user initiates PyPI publish.
- `mcp-backend-wiring-discipline.md` — `/health` aggregator + per-tool
  integration tests mandatory.
- `akoshac/akosha/mcp/client.py:BodaiComponentMCPClient` — the
  class being extracted in Phase 1.
- `akoshac/akosha/mcp/client.py:DharaServiceRegistryClient` — the
  class being deleted in Phase 3 (with the Dhara mount in same commit).
- `dhara/dhara/mcp/server_core.py:693-770` — the `_register_tools_call_route`
  method being deleted in Phase 3.
- `mcp-common/mcp_common/health.py:836-839` — the existing
  `register_http_health_route` 200-always contract documentation.
- `docs/followups/2026-09-14-akosha-hnsw-on-duckdb.md` — out-of-plan
  followup (Phase 5 stub).
- `mcp-backend-wiring-discipline.md` — Bodai FeedState contract.
- `dhara-startup-hang-8683.md` (memory) — launchd wrapper unreliability.

## 11. Operator Ergonomics (Tier 3 polish — separate section for reviewability)

`★ Insight ─────────────────────────────────────`
**The plan presents `/health` semantics change; operator-handbook updates must ship with it.** A new `/health` body shape is operator-hostile if there's no runbook. Tier 3 polish items gather here so reviewers can sign off on operator experience independently from technical correctness.
`─────────────────────────────────────────────────`

### 11.1 Status enum (top-level, not buried)

HTTP 200 always (per `register_http_health_route` 200-always
contract). Body:

```json
{
  "status": "warming_up",
  "checks": {
    "local_traces": {
      "ok": true,
      "entities_count": 0,
      "cycles_total": 4642,
      "errors_total": 10,
      "last_error_at": 1789368401.5,
      "errors_within_window": 0,
      "ingester_running": true,
      "reason_codes": ["warming_up_empty_feed"]
    }
  },
  "reason_codes": ["warming_up_empty_feed"]
}
```

`status ∈ {healthy, warming_up, degraded, failed}` is the worst
across all feeds. Operators read it with `jq .status` for
3am triage.

### 11.2 Reason-code enum

```python
ReasonCode = (
    "warming_up_empty_feed"             # feed not yet populated, no errors
    "warming_up_never_cycled"           # producer never started
    "ingester_not_running"               # producer task absent
    "feed_never_populated"               # first cycle raised; flagged degraded
    "recent_error_in_window"             # error within halflife
    "no_producer_ever_cycled"            # no producer task has cycled yet
    "producer_not_alive"                 # task is done/cancelled
)
```

Action mapping lives in `docs/runbooks/health_reason_codes.md` —
**delivered as part of Phase 4**, not a follow-up.

### 11.3 Runbook (delivered with Phase 4)

`docs/runbooks/health_reason_codes.md` per-reason sections with:
- `/health` signal the operator sees
- What it does NOT mean (so they don't restart)
- Action to take
- Action explicitly NOT to take
- When to escalate

Linked from new PromQL alert `runbook` annotations.

### 11.4 Alerting rules (PromQL, in `mahavishnu/config/alerts/`)

```yaml
- alert: BodaiFeedRecentError
  expr: mcp_common_health_feed_errors_within_window{repo=~".*"} > 5
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "Feed {{ $labels.feed }} in {{ $labels.repo }} has >5 errors in window"
    runbook: docs/runbooks/health_reason_codes.md#recent_error_in_window

- alert: BodaiFeedDecayDisabled
  expr: mcp_common_health_halflife_seconds{repo=~".*"} == 0
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "{{ $labels.repo }} has HEALTH_FEED_HALFLIFE_SECONDS=0"
    runbook: docs/runbooks/health_reason_codes.md#manual-override
```

### 11.5 Phase 1 hardening: `first_unhealthy_at`

`HealthFeedState.first_unhealthy_at: float | None` is set on every
healthy→unhealthy transition and cleared on reverse. Surfaces SLO
burn-rate calculation per the Google SRE Workbook style.

(Per v1 review: this field is needed for prospective alerting;
omitted fields surface only "current" state, not "how long".)
