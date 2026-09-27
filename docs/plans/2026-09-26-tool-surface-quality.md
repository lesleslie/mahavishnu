---
status: shipped
role: implementation
kind: plan
date: 2026-09-26
last_reviewed: 2026-09-27
superseded_by: null
blocks_on: []
topic: mcp-design
phase_1:
  status: shipped
  commits:
    mahavishnu:
      - 67095d98 feat(mahavishnu): tool-call span enrichment + Akosha-bound OTel attributes
      - 5e9ad579 fix(mahavishnu): Phase 1 verification fixes (split gates, real e2e, microbench)
      - 8705f469 fix(mahavishnu): upgrade microbench to exercise real OTel span path
    akosha:
      - a6ff6a7 feat(akosha): wire mcp_tool_call feed into /health aggregator (Phase 1 Task 1.5)
      - 076d63b fix(akosha): expose mcp_tool_call_feed per-feed dict in /health wire-out
phase_2:
  status: partial
  shipped:
    - task_2_1: 3215d824 feat(mahavishnu): top-N MCP tool audit script (Phase 2 Task 2.1) — scripts/audit_top_tool_calls.py + 15 tests + DELETE empty stub scripts/audit_mcp_tools.py
    - task_2_2: f5903d6c feat(mahavishnu): tool description rubric + structural validator (Phase 2 Task 2.2) — .claude/decisions/tool-description-rubric.md + 18 tests
  blocked:
    - task_2_3: top-10 description= rewrites, one atomic commit per tool — requires ≥7 days of mcp_tool_call traces from production traffic to rank tools by call count
    - task_2_4: tests/integration/test_tool_selection_accuracy.py (before/after measurement) — requires both before-data and after-data, neither exists yet
  blocker:
    description: Tasks 2.3 and 2.4 share the same production-data dependency: Phase 1 telemetry enrichment shipped 2026-09-27 but no real call volume has accumulated yet. Once a few days of operator + agent traffic flow through mcp__mahavishnu__* calls, scripts/audit_top_tool_calls.py (Task 2.1) produces the top-10 ranking and Tasks 2.3 + 2.4 can proceed.
    activation_signal: scripts/audit_top_tool_calls.py returns >=10 distinct selectors
follow_on_plan: docs/plans/drafts/2026-09-27-akosha-tool-call-feed-lifecycle.md
unblocks:
  - docs/plans/drafts/2026-09-26-eval-methodology.md (Plan 2 — needs top-N ranking from Task 2.1 + fixture proposal + reviewer sign-off)
---

# Tool Surface Quality — Implementation Plan (v2)

> **Origin:** 2026-09-26 conversation — SWE-Agent's Agent-Computer Interface discipline applied to Mahavishnu's MCP tool surface. Original plan (`v1`) failed multi-agent review on 2026-09-26 with 3 of 5 reviewers returning `REQUIRED HARDENING BEFORE SHIP`. **v2 incorporates those revisions; demoted to `draft` pending re-review.**
>
> **What changed in v2:**
> 1. **Span attribute schema simplified.** Dropped `caller_kind`/`workflow_id`/`session_id`/`error_class`. The original schema was under-specified and three of five reviewers caught the same structural problem (no Context-state key exists for these; `AuthContextMiddleware` only stores `mahavishnu.user_id`). New schema is the minimum Akosha actually consumes.
> 2. **Fitness analyzer contract corrected.** `akosha/processing/fitness_analyzer.py:166` has a hardcoded `task_classes` list. Phase 1 Task 1.3 is now a mandatory Akosha-side edit, not "zero-config."
> 3. **Per-tool signal mechanism renamed.** Fitness analyzer breaks down by `selector`, not `mcp.tool.name`. New schema sets `selector=<tool_name>` to get the per-tool breakdown.
> 4. **Outcome/duration_ms replace error_class.** `_classify_tool_result` (`server_core.py:220`) already classifies `success|error|cancelled|timeout` for Prometheus. New enricher reuses that classification and sets `outcome` + `duration_ms` — which is what the fitness analyzer actually consumes.
> 5. **`mcp.tool.name` no longer redundantly written.** `mcp_common/server/telemetry.py:113` already sets it; downstream consumers can reuse it.
> 6. **Citations corrected.** All REQ entries now carry `path:line` per wire-up-contract v1.1 §1.
> 7. **`/health` aggregator wired.** Phase 1 Task 1.5 adds `HealthFeedState("mcp_tool_call")` per `mcp-backend-wiring-discipline.md`.
> 8. **Independent config flag.** `observability.tool_enrichment_enabled` decouples enrichment from `tracing_enabled` (Phase 2 needs enrichment on even when tracing is off).
> 9. **Description rubric gains 6th criterion.** "No internal disclosure" — descriptions must not contain absolute file paths, internal-only tool names, or auth-mechanism hints.
>
> **Companion plan:** `docs/plans/drafts/2026-09-26-eval-methodology.md` — `draft, implementation`, blocked on this plan's Phase 1.

## 1. Outcome

- **User-observable change:** Every `mcp__mahavishnu__*` tool call emits an OTel span that lands in Akosha with `task_class="mcp_tool_call"`, `selector=<tool_name>`, `outcome`, and `duration_ms`. The Akosha fitness analyzer (after a one-line edit to its hardcoded `task_classes` list) produces per-tool failure_rate + p99 latency. Top-10 most-called tools have their descriptions rewritten against an explicit 6-criterion rubric. After both phases: `mcp__akosha__query_local_traces(system_id="mahavishnu", task_class="mcp_tool_call", limit=10)` returns enriched traces; the fitness analyzer returns non-empty per-tool signals.
- **Success metric:** Within 30 days of Phase 1 landing, a baseline of per-tool failure_rate + p99 is established. Within 30 days of Phase 2 landing, the top-10 mean per-tool success rate improves by ≥ 3 percentage points (one-tailed, with a ±2σ tolerance band for the LLM-as-judge noise). Zero new symbols with zero callers per `scripts/audit_orphans.py` at every phase exit. `audit_orphans.py` runs in <60s, exits non-zero on violations, emits structured output (verified at Phase 1 exit).

## 2. Goals

1. Every MCP tool call emits a span that lands in Akosha's existing OTel trace feed with the minimum attributes the fitness analyzer consumes.
2. The Akosha fitness analyzer, after a one-line `task_classes` list edit, automatically computes per-tool failure_rate and p99 latency for `mcp_tool_call` traces.
3. The top-10 most-called tools (per Phase 1 telemetry) have their `description=` strings rewritten against a fixed rubric designed for the model reader.
4. A repeatable end-to-end check exists that proves both the telemetry flow and the description rewires work.
5. Wire-up-contract compliance: `audit_orphans.py` clean at every phase exit; integration tests in `tests/integration/test_*_e2e.py` per phase; citations within the 5-line audit invariant.
6. `/health` aggregator surfaces `mcp_tool_call` feed state per `mcp-backend-wiring-discipline.md` §1.

## 3. Non-Goals

1. Building a full OpenHands-style eval harness (deferred companion plan).
2. Changing `FastMCPOpenTelemetryMiddleware` in `mcp_common` (we subclass locally; we do not modify `mcp_common`).
3. Adding new storage layers — events land in Akosha via the existing OTel feed.
4. Rewriting every tool's description. Only top-10 in Phase 2; the rubric establishes the standard for future passes.
5. Modifying `MAHAVISHNU_MANDATORY_GROUPS` or the profile-gating system.
6. Crackerjack integration for the new metrics (Crackerjack reads the same telemetry via existing OTel wiring; no new bridge).
7. Cross-component push to Oneiric runtime registry (separate concern, owned by `2026-09-26-oneiric-runtime-config-registry.md`).
8. Populating `caller_kind` / `workflow_id` / `session_id` as span attributes. These would require new middleware to populate Context-state keys that don't currently exist, which contradicts Non-Goal #2. If Akosha consumers later need them, that's a follow-on plan that adds the new middleware.
9. Capturing tool arguments, return values, exception messages, tracebacks, or `exc.args` in any log, OTel event, or Akosha record. PII/secret leakage prevention.

## 4. Current Findings

- **FastMCP telemetry middleware already wired.** `mahavishnu/mcp/server_core.py:84` calls `self._register_telemetry_middleware()` during `FastMCPServer.__init__`. The middleware (`mcp_common.server.telemetry.FastMCPOpenTelemetryMiddleware`) attaches when `observability.tracing_enabled` is true (`mahavishnu/mcp/server_core.py:115`, gate at `mahavishnu/core/config.py:1307`). The hook is `on_message` (`mcp-common/mcp_common/server/telemetry.py:61`), which fires for every FastMCP message. Subclass overrides `on_message` and gates enrichment on `context.method == "tools/call"`.
- **Upstream middleware already sets `mcp.tool.name`.** `mcp-common/mcp_common/server/telemetry.py:113` writes `attributes["mcp.tool.name"] = component_name or "unknown"` when `context.method == "tools/call"`. The enricher does NOT redundantly write this attribute — it reads the upstream value (or uses the same source) and folds it into `selector`.
- **Prometheus metrics already exist.** `mahavishnu/mcp/server_core.py:19-23` imports `mcp_tool_calls_total`, `mcp_tool_duration_seconds`, `mcp_tools_registered` from `monitoring.metrics`. The new enricher REUSES the Prometheus classification (no duplication). `mcp_tool_calls_total` and `mcp_tool_duration_seconds` stay unchanged.
- **Tool classification already implemented.** `_classify_tool_result(status)` at `mahavishnu/mcp/server_core.py:220` returns one of `success|error|cancelled|timeout`. The new enricher reads this and sets `outcome=<classification>`.
- **Tool handler timing already implemented.** `_wrap_tool_handler` at `mahavishnu/mcp/server_core.py:164-200` records `mcp_tool_duration_seconds`. The new enricher reads this and sets `duration_ms=<ms>`.
- **AuthContextMiddleware contents.** `mahavishnu/mcp/middleware/auth_context.py:51` defines `USER_ID_STATE_KEY = "mahavishnu.user_id"`. `AuthContextMiddleware.on_call_tool` at `:89` sets this on FastMCP context state. The middleware does NOT store `caller_kind`, `workflow_id`, or `session_id`. These three attributes are out of scope for this plan (see Non-Goal #8).
- **Tool registration is profile-gated.** `mahavishnu/mcp/tools/profiles.py:181` defines `REGISTRATION_MAP` with group keys (e.g. `_register_pool_tools`), not individual tool names. Some registration callables (e.g. `_register_jot_tools`, `_register_primitive_tools`) bundle multiple tool decorators. Phase 2 must enumerate individual tool names from telemetry, not from `REGISTRATION_MAP`. 37 `.py` files exist under `mahavishnu/mcp/tools/` (excluding `__init__.py`), not 35 as the v1 plan stated.
- **Akosha fitness analyzer has a hardcoded task_classes list.** `akosha/processing/fitness_analyzer.py:166`: `task_classes = ["code_generation", "reasoning", "swarm", "quick", "documentation"]`. Adding `"mcp_tool_call"` is a mandatory Akosha-side edit (not "zero-config" as v1 claimed).
- **Akosha fitness analyzer breaks down by `selector`, not `mcp.tool.name`.** `akosha/processing/fitness_analyzer.py:174-181` keys the per-signal breakdown by `selector = trace.get("selector", "unknown")`. The OTel ingester (`akosha/ingestion/otel_ingester.py:311-328`) only extracts `task.class` into `metadata.attributes`; `selector` is `"unknown"` for every existing span. New enricher MUST set `selector=<tool_name>` to produce per-tool signals.
- **Akosha fitness analyzer computes `failure_rate` from `outcome`.** `akosha/processing/fitness_analyzer.py:131-135` reads `outcome` and `duration_ms` from the normalized trace dict. The OTel ingester does NOT extract these from spans (it only writes `task_class`). The new enricher MUST set `outcome=<classification>` and `duration_ms=<ms>` so the analyzer's `failure_rate` and `p99` computations have signal.
- **Mahavishnu's `query_local_traces` filter is on `task.class`.** `mahavishnu/mcp/tools/otel_tools.py:307` filters Akosha traces by `task_class`. The new enricher MUST set `task_class="mcp_tool_call"` as a span attribute (which is mapped to `metadata.attributes.task_class` by the OTel ingester's `_normalize_span` at `akosha/ingestion/otel_ingester.py:328`).
- **`add_metric` only accepts known metric names.** `akosha/processing/analytics.py:90` accepts `conversation_count`, `quality_score`, `error_rate`. There is no `tool_success_rate` metric in Akosha. Phase 2 will use `error_rate` as the per-tool signal.
- **`scripts/audit_mcp_tools.py` already exists as an empty stub.** Verified by Read — file exists at `scripts/audit_mcp_tools.py` with empty contents. Phase 2 will DELETE this stub and add `scripts/audit_top_tool_calls.py` to avoid namespace confusion.
- **`tests/test_plan_citations.py` does not exist.** Verified by Glob — zero hits. This file is owned by the serverless-readiness plan's Phase 9. The v1 plan's reference to this guard test is REMOVED in v2; wire-up-contract v1.1 §1 citation discipline is enforced via human review, not an automated gate, until the serverless-readiness test ships.
- **No existing tool-quality dashboard or description rubric.** Grep confirms no `tool_success_rate`/`tool_audit`/`tool_effectiveness` symbols anywhere. The rubric is greenfield.
- **Cross-component dependency.** Mahavishnu writes traces → Akosha's OTel ingester ingests them → Akosha fitness analyzer queries them. This is `Mahavishnu → Akosha (OTel exporter → MCP query)`. No direct import from Mahavishnu into Akosha's source. The Akosha-side edit (Task 1.3) is an inter-repo change.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-TSQ-001
    title: "Span attribute schema is exactly {task_class, mcp.tool.name (upstream), selector, outcome, duration_ms}"
    cites: "mahavishnu/mcp/server_core.py:84,115; mcp-common/mcp_common/server/telemetry.py:113; akosha/processing/fitness_analyzer.py:131-135,166,174-181"
  - id: REQ-TSQ-002
    title: "Enrichment lives in a local subclass of FastMCPOpenTelemetryMiddleware; mcp_common is untouched"
    cites: "mcp-common/mcp_common/server/telemetry.py:44,61"
  - id: REQ-TSQ-003
    title: "Akosha fitness analyzer's hardcoded task_classes list is updated to include mcp_tool_call"
    cites: "akosha/processing/fitness_analyzer.py:166"
  - id: REQ-TSQ-004
    title: "Selector attribute is set to the tool name so per-tool breakdown produces a per-tool signal"
    cites: "akosha/processing/fitness_analyzer.py:174-181"
  - id: REQ-TSQ-005
    title: "outcome attribute carries _classify_tool_result output (success|error|cancelled|timeout)"
    cites: "mahavishnu/mcp/server_core.py:220; akosha/processing/fitness_analyzer.py:131-135"
  - id: REQ-TSQ-006
    title: "duration_ms attribute is set from the existing Prometheus timer in _wrap_tool_handler"
    cites: "mahavishnu/mcp/server_core.py:164-200"
  - id: REQ-TSQ-007
    title: "observability.tool_enrichment_enabled config flag decouples enrichment from tracing_enabled"
    cites: "mahavishnu/core/config.py:1307"
  - id: REQ-TSQ-008
    title: "HealthFeedState('mcp_tool_call') wired into _resolve_feeds + /health aggregator"
    cites: ".claude/decisions/mcp-backend-wiring-discipline.md (full document)"
  - id: REQ-TSQ-009
    title: "Top-10 enumeration script reads Akosha traces; output is sorted desc + idempotent"
    cites: "mahavishnu/mcp/tools/otel_tools.py:307"
  - id: REQ-TSQ-010
    title: "Description rubric has 6 criteria including no-internal-disclosure; structurally validated"
    cites: ".claude/decisions/README.md (decision-record format)"
  - id: REQ-TSQ-011
    title: "Fixed task suite of >=5 representative tasks; LLM judge pinned to model + seed=0 + tolerance band"
    cites: "mahavishnu/mcp/server_core.py:19-23 (Prometheus surface; not used here, citation for telemetry context)"
  - id: REQ-TSQ-012
    title: "audit_orphans.py runs in <60s, exits non-zero on violations, emits structured output (verified at Phase 1 exit)"
    cites: "scripts/audit_orphans.py (existence + runnability); .claude/decisions/wire-up-contract.md §4"
```

## 5. Implementation Phases

### Phase 1: Tool-call telemetry enrichment + Akosha wiring

**Goal:** Every MCP tool call emits a span with the minimum schema Akosha's fitness analyzer consumes. The Akosha analyzer's hardcoded `task_classes` list is updated to include `mcp_tool_call`. `/health` aggregator surfaces the new feed. Independent config flag allows enrichment without tracing.

**Tasks:**

- **Task 1.1 (REQ-TSQ-001, REQ-TSQ-002, REQ-TSQ-004, REQ-TSQ-005, REQ-TSQ-006):** Add `mahavishnu/mcp/tool_call_enricher.py` with `enrich_tool_call_span(span, *, tool_name, started_at, classified_status, duration_ms) -> None`. Sets span attributes: `task_class="mcp_tool_call"`, `selector=<tool_name>`, `outcome=<classified_status>`, `duration_ms=<ms>`. Does NOT set `mcp.tool.name` (upstream `mcp_common/server/telemetry.py:113` already sets it).
- **Task 1.2:** Add local subclass `mahavishnu/mcp/tool_call_middleware.py::ToolCallEnrichmentMiddleware(FastMCPOpenTelemetryMiddleware)` that overrides `on_message(context, call_next)`, gates on `context.method == "tools/call"`, reads `_classify_tool_result(status)` from `mahavishnu/mcp/server_core.py:220` for outcome, reads the existing Prometheus timer in `_wrap_tool_handler` (`server_core.py:164-200`) for duration_ms, and calls `enrich_tool_call_span`. Wire into the FastMCP middleware list inside `_register_telemetry_middleware` (`mahavishnu/mcp/server_core.py:84`), NOT into `mcp_common`.
- **Task 1.3 (REQ-TSQ-003, INTER-REPO):** Edit `akosha/processing/fitness_analyzer.py:166` — append `"mcp_tool_call"` to the hardcoded `task_classes` list. **This is a mandatory Akosha-side edit.** Coordinate with Akosha maintainer; ships as paired commits on each repo main (Mahavishnu commit 67095d98; Akosha commit on its main).
- **Task 1.4 (REQ-TSQ-007):** Add `observability.tool_enrichment_enabled: bool = False` to `mahavishnu/core/config.py` (around line 1307 alongside `tracing_enabled`). Gate the enricher on `tool_enrichment_enabled` independently of `tracing_enabled`. Phase 2's `audit_top_tool_calls.py` needs enrichment on even when OTel tracing is off.
- **Task 1.5 (REQ-TSQ-008):** Wire `HealthFeedState("mcp_tool_call")` into the existing feed aggregator per `.claude/decisions/mcp-backend-wiring-discipline.md` §1 + §3. Four signals required: `entities_count` (trace rows), `last_updated_timestamp`, `errors_total` (failed OTel exports), `cycles_total` (analyzer cycles that queried this feed). `/health` returns 503 if `errors_total > threshold`.
- **Task 1.6 (REQ-TSQ-012):** Verify `scripts/audit_orphans.py` runs in <60s on the current repo, exits non-zero on violations, emits structured output with `file:line + description`. Record the actual numbers in the Phase 1 exit-criteria evidence.
- **Task 1.7:** Add `tests/integration/test_tool_call_telemetry_e2e.py` — start `FastMCPServer`, invoke a tool via the in-process FastMCP client, assert:
  - `mcp__akosha__query_local_traces(system_id="mahavishnu", task_class="mcp_tool_call", limit=5)` returns non-empty result (per `mcp-backend-wiring-discipline.md` §2 / §4 — non-empty-results assertion).
  - The fitness analyzer, after Task 1.3 ships, returns non-empty per-tool failure_rate for `mcp_tool_call`.
  - `pytest-benchmark` microbench (per `pyproject.toml` dev-deps) shows p99 enrichment overhead < 5ms; hard rollback at 10ms.

**Exit criteria:**

- `tests/integration/test_tool_call_telemetry_e2e.py` green.
- `python scripts/audit_orphans.py` reports zero new symbols with zero callers AND runs in <60s (recorded in evidence).
- `cd /Users/les/Projects/mahavishnu && uv run crackerjack run -p patch` clean.
- Akosha-side edit (Task 1.3) merged in `akosha` repo and released.
- Manual check: `mcp__akosha__query_local_traces(system_id="mahavishnu", task_class="mcp_tool_call", limit=10)` returns ≥1 trace after one tool call.
- Manual check: `mcp__akosha__run_fitness_analysis()` returns non-empty per-tool failure_rate.

#### Integration Contract (Phase 1)

- **Triggered from:** Every MCP tool dispatch through `FastMCPServer._register_telemetry_middleware` (`mahavishnu/mcp/server_core.py:84` → `mcp_common.server.telemetry.FastMCPOpenTelemetryMiddleware`). Local subclass `ToolCallEnrichmentMiddleware` hooks into the same middleware chain.
- **Returns to / updates:** Akosha OTel trace feed (`mcp__akosha__query_local_traces(system_id="mahavishnu")`). Span attributes: `task_class="mcp_tool_call"`, `selector=<tool_name>`, `outcome=<classification>`, `duration_ms=<ms>` (and the upstream `mcp.tool.name`). Akosha fitness analyzer's hardcoded `task_classes` list gains `"mcp_tool_call"`. Akosha `/health` aggregator surfaces `mcp_tool_call` feed state.
- **Demonstrable by:**
  ```bash
  cd /Users/les/Projects/mahavishnu && uv run pytest tests/integration/test_tool_call_telemetry_e2e.py -v
  cd /Users/les/Projects/akosha && uv run pytest tests/processing/test_fitness_analyzer.py -v
  cd /Users/les/Projects/mahavishnu && uv run python scripts/audit_orphans.py
  cd /Users/les/Projects/mahavishnu && uv run crackerjack run -p patch
  # Manual (after Akosha-side edit merged + Mahavishnu booted):
  # mcp__akosha__query_local_traces(system_id="mahavishnu", task_class="mcp_tool_call", limit=5)
  # mcp__akosha__run_fitness_analysis() — verify non-empty per-tool signals
  ```
- **Rollback signal:** Enrichment overhead p99 > 10ms for any 60s window in the microbench, OR `HealthFeedState("mcp_tool_call").errors_total > 0` for 5 minutes straight in `/health`, OR `mcp_tool_call` feed shows `cycles_total == 0` for 60s after Phase 1 lands (per `feedback-oneiric-mcp-health-feed-warmup` memory — pre-warm feeds). Mitigation: feature-flag via `observability.tool_enrichment_enabled=false`; the enricher subclass is a no-op when the flag is off.
- **Observability added:** OTel span attributes `task_class`, `selector`, `outcome`, `duration_ms`. Akosha `HealthFeedState("mcp_tool_call")` feed (cycles_total, entities_count, errors_total, last_updated_timestamp). `mcp_tool_call` task_class visible in `query_local_traces` and `run_fitness_analysis`.

**Cross-component dependency:** Mahavishnu writes traces → Akosha ingests → Akosha fitness analyzer queries. Mahavishnu → Akosha (OTel exporter → MCP query). No direct source import.

---

### Phase 2: Top-10 tool description audit + rubric

**Goal:** Establish a model-side description rubric; rewrite the top-10 most-called tools' descriptions against it; prove the rewrites help the model pick the right tool.

**Tasks:**

- **Task 2.1 (REQ-TSQ-009):** DELETE the empty stub `scripts/audit_mcp_tools.py`. ADD `scripts/audit_top_tool_calls.py` — reads Akosha traces via `mcp__akosha__query_local_traces(system_id="mahavishnu", task_class="mcp_tool_call", limit=200)`, groups by `selector`, ranks by call count desc, outputs the sorted list. Idempotent. Asserted by `tests/unit/test_audit_top_tool_calls.py` — exits 0, sorted desc, idempotent across runs.
- **Task 2.2 (REQ-TSQ-010):** Add `mahavishnu/.claude/decisions/tool-description-rubric.md` with **6 criteria**:
  1. When *not* to use (negative cases).
  2. Common failure modes.
  3. Return shape hint (string / structured / empty-when-no-data).
  4. Model-side language (active voice, second-person imperatives, no marketing prose).
  5. Side-effect caveat (filesystem / network / external state).
  6. **No internal disclosure** — descriptions MUST NOT contain absolute file paths, internal-only tool names not exposed publicly, or auth-mechanism hints (token types, JWT claims, header names).
  Asserted by `tests/unit/test_tool_description_rubric.py` — file exists, contains 6 named sections, each section has one pass example and one fail example.
- **Task 2.3:** Apply the rubric to the top-10 tools (per `audit_top_tool_calls.py` output). Rewrite each tool's `description=` string in its `@mcp.tool()` decorator. One atomic commit per tool. Confirm the 10 touched tools already have `tests/integration/test_<tool>_e2e.py` files OR note the gap (description-only changes are not re-registrations per `mcp-backend-wiring-discipline.md` §4, so existing per-tool e2e tests cover runtime; description impact is covered by Task 2.4).
- **Task 2.4 (REQ-TSQ-011):** Add `tests/integration/test_tool_selection_accuracy.py` — fixed task suite of ≥5 representative tasks. Each task = natural-language intent + ground-truth tool name. Judge model pinned (small cheap model — `MiniMax-M3` per CLAUDE.md or local `qwen3.5`), `temperature=0`, `seed=0`, judge-model version recorded in test logs. Tolerance band: `after-rate ≥ before-rate − 2σ` (per Akosha reviewer and code-explorer reviewer recommendations — non-strict because LLM-as-judge is non-deterministic).
- **Task 2.5:** Update PLAN_INDEX frontmatter `last_reviewed` to today's date once Phase 2 ships.

**Exit criteria:**

- Top-10 descriptions rewritten, each commit atomic.
- `tests/integration/test_tool_selection_accuracy.py` shows after-rate within tolerance band.
- `audit_orphans.py` clean + runs in <60s.
- `crackerjack run -p patch` clean.
- `tool-description-rubric.md` committed alongside.
- `tests/unit/test_audit_top_tool_calls.py` and `tests/unit/test_tool_description_rubric.py` green.

#### Integration Contract (Phase 2)

- **Triggered from:** Manual invocation of `scripts/audit_top_tool_calls.py` (one-shot analysis); `tests/integration/test_tool_selection_accuracy.py` runs in CI on every PR that touches `mahavishnu/mcp/tools/`.
- **Returns to / updates:** Updated `description=` strings on 10 `@mcp.tool()` decorators under `mahavishnu/mcp/tools/`. New decision file at `mahavishnu/.claude/decisions/tool-description-rubric.md`. New `tests/integration/test_tool_selection_accuracy.py`, `tests/unit/test_audit_top_tool_calls.py`, `tests/unit/test_tool_description_rubric.py`.
- **Demonstrable by:**
  ```bash
  cd /Users/les/Projects/mahavishnu && uv run python scripts/audit_top_tool_calls.py
  cd /Users/les/Projects/mahavishnu && uv run pytest tests/integration/test_tool_selection_accuracy.py tests/unit/test_audit_top_tool_calls.py tests/unit/test_tool_description_rubric.py -v
  cd /Users/les/Projects/mahavishnu && uv run python scripts/audit_orphans.py
  cd /Users/les/Projects/mahavishnu && uv run crackerjack run -p patch
  git -C /Users/les/Projects/mahavishnu log --oneline --grep="^tools: rewire top-10 descriptions" | wc -l  # ≥ 10
  ```
- **Rollback signal:** `test_tool_selection_accuracy.py` after-rate outside the tolerance band for ≥3 days in CI, OR a description rewrite produces a per-tool failure_rate regression > 10% week-over-week in the Akosha fitness analyzer. Mitigation: revert the offending commit; rubric still stands for the next pass.
- **Observability added:** Per-tool `error_rate` signal from the Akosha fitness analyzer (existing metric, no new metric registration); `tool_selection_accuracy` test-time metric emitted by `test_tool_selection_accuracy.py`.

---

## 6. Required Code Changes

### Phase 1 (Telemetry enrichment)

- [ ] `mahavishnu/mcp/tool_call_enricher.py` (new) — `enrich_tool_call_span(...)` helper (Task 1.1)
- [ ] `mahavishnu/mcp/tool_call_middleware.py` (new) — `ToolCallEnrichmentMiddleware` subclass (Task 1.2)
- [ ] `mahavishnu/mcp/server_core.py:84` — add subclass to FastMCP middleware list inside `_register_telemetry_middleware` (Task 1.2)
- [ ] `mahavishnu/core/config.py:1307` — add `observability.tool_enrichment_enabled` field (Task 1.4)
- [ ] Akosha `akosha/processing/fitness_analyzer.py:166` — append `"mcp_tool_call"` to hardcoded `task_classes` list (Task 1.3, INTER-REPO)
- [ ] Akosha — wire `HealthFeedState("mcp_tool_call")` into existing feed aggregator + `/health` (Task 1.5, INTER-REPO)
- [ ] `tests/integration/test_tool_call_telemetry_e2e.py` (new) — wiring discipline (Task 1.7)
- [ ] Verify `scripts/audit_orphans.py` runtime + exit-code (Task 1.6)

### Phase 2 (Description audit)

- [ ] DELETE `scripts/audit_mcp_tools.py` (empty stub) (Task 2.1)
- [ ] `scripts/audit_top_tool_calls.py` (new) — top-N enumeration (Task 2.1)
- [ ] `tests/unit/test_audit_top_tool_calls.py` (new) — idempotence + sort-order (Task 2.1)
- [ ] `mahavishnu/.claude/decisions/tool-description-rubric.md` (new) — 6-criterion rubric (Task 2.2)
- [ ] `tests/unit/test_tool_description_rubric.py` (new) — structural validator (Task 2.2)
- [ ] `mahavishnu/mcp/tools/<group>.py` × 10 — `description=` rewrites, one commit per tool (Task 2.3)
- [ ] `tests/integration/test_tool_selection_accuracy.py` (new) — before/after measurement with tolerance band (Task 2.4)

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `cd /Users/les/Projects/mahavishnu && uv run pytest tests/integration/test_tool_call_telemetry_e2e.py -v` | All tests pass | CI logs |
| `cd /Users/les/Projects/akosha && uv run pytest tests/processing/test_fitness_analyzer.py -v` | All tests pass after Task 1.3 | CI logs |
| `cd /Users/les/Projects/mahavishnu && uv run python scripts/audit_orphans.py` | Zero new symbols with zero callers; <60s runtime | stdout |
| `cd /Users/les/Projects/mahavishnu && uv run crackerjack run -p patch` | All quality gates pass | Crackerjack log |
| `mcp__akosha__query_local_traces(system_id="mahavishnu", task_class="mcp_tool_call", limit=10)` | Returns ≥1 trace after one tool call | Session transcript |
| `mcp__akosha__run_fitness_analysis()` | Returns non-empty per-tool signals | Session transcript |
| `cd /Users/les/Projects/mahavishnu && uv run python scripts/audit_top_tool_calls.py` | Prints sorted top-N list | stdout |
| `cd /Users/les/Projects/mahavishnu && uv run pytest tests/integration/test_tool_selection_accuracy.py -v` | after-rate within tolerance band | CI logs |
| `git log --oneline --grep="^tools: rewire top-10 descriptions"` | ≥10 atomic commits | git log |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Akosha-side edit (Task 1.3) lands after Mahavishnu-side: Mahavishnu emits `mcp_tool_call` traces that the analyzer ignores | Medium | Paired-commit coordination: Akosha commit lands first or simultaneously; release gate is crackerjack run on each repo; integration test asserts analyzer sees new task_class. |
| Fitness analyzer's `selector` vs `mcp.tool.name` mapping confuses downstream consumers | Low | Document the alias explicitly in `tool_call_enricher.py`; trace sample in CI shows both attributes match. |
| `task_class` attribute naming collision with another Mahavishnu subsystem that already uses `task_class` for a different meaning | Low | Grep confirms no other `task_class` writer in Mahavishnu; the convention `mcp_tool_call` is unambiguous. |
| `audit_orphans.py` runtime exceeds 60s budget | Low | Per `mcp-backend-wiring-discipline.md` §1 — verify at Phase 1 Task 1.6; if exceeded, file a separate plan to optimize the script. |
| Per-tool e2e tests for the 10 touched tools don't exist | Medium | Audit at Task 2.3; if gaps, add tests OR document that description-only changes don't trigger §4 obligations. |
| Companion eval plan (`docs/plans/drafts/2026-09-26-eval-methodology.md`) needs fields Phase 1 doesn't emit | Medium | Phase 1 schema is the minimum Akosha consumes. If eval needs more (e.g., model-side tool-selection trace), that's a Phase 1.5 follow-on that emits additional attributes; flagged in §9 Decision Rule. |
| Retention policy for high-cardinality `mcp_tool_call` traces (every tool call is a row) | Medium | Akosha `AgingService.migrate_hot_to_warm(cutoff_days=7)` (`akosha/storage/aging.py:46`) is opt-in. Phase 1 Task 1.5 documents the wiring expectation but does not enforce — owner-side decision; flagged here for visibility. |
| HotStore semantic-search index polluted by tool-call traces | Low | Span attributes (`task_class`, `selector`, `outcome`) are categorical, low-cardinality. `mcp.tool.name` is bounded by 173 tools. No free-form text in attributes → embedding index not polluted. |
| LLM-as-judge non-determinism in `test_tool_selection_accuracy.py` | Medium | Judge pinned (model + temperature=0 + seed=0); tolerance band `≥ before-rate − 2σ`; judge-model version recorded in test logs. |
| Description rewrite accidentally introduces internal disclosure | Medium | Rubric criterion #6 (no internal disclosure); structural validator test (`test_tool_description_rubric.py`) asserts pass/fail examples. |

## 9. Decision Rule

The plan is "done enough" when:

- Phase 1 implemented + tested + `audit_orphans.py` clean (in <60s) + `crackerjack run -p patch` clean.
- Akosha-side edit (Task 1.3 + Task 1.5 wiring) merged in `akosha` repo and released.
- `mcp__akosha__query_local_traces(system_id="mahavishnu", task_class="mcp_tool_call")` returns enriched traces end-to-end.
- `mcp__akosha__run_fitness_analysis()` returns non-empty per-tool signals.
- 30-day baseline window established post-Phase-1.
- Phase 2 implemented + tested + `audit_orphans.py` clean + `crackerjack run -p patch` clean.
- Top-10 descriptions rewritten atomically against the 6-criterion rubric.
- `test_tool_selection_accuracy.py` after-rate within tolerance band vs the 30-day baseline.
- Companion eval plan remains `draft` until Phase 1's data shape is observed to be sufficient.

**Scope pressure cut:** if forced, drop Phase 2's `test_tool_selection_accuracy.py` to a follow-up and ship the description rewrites manually-reviewed against the rubric. Phase 1 is the load-bearing foundation; without it, no further tool-quality work makes sense.

**Promotion rule:** `status: draft → active` requires (a) all five re-review verdicts to be at least `APPROVED WITH REVISIONS`, and (b) any `REQUIRED HARDENING BEFORE SHIP` verdicts to be resolved by a follow-up revision. Until then, status stays `draft`.

---

## Review Notes (v2)

v1 (`2026-09-26`) failed multi-agent review on 2026-09-26 with 3 of 5 reviewers returning `REQUIRED HARDENING BEFORE SHIP`. v2 incorporates all structural revisions. Re-review in flight.

### Round 1 reviewers (v1)

- [x] reviewer-1: `feature-dev:code-architect` — 2026-09-26 — **APPROVED WITH REVISIONS** (testability gaps, threshold tightening, attribute naming, Prometheus path decision). 10 revisions; structural items folded into v2 §4.5 REQ-TSQ-005/-006, §5 Phase 1 Task 1.2, §5 Phase 2 Exit criteria, §9 Decision Rule.
- [x] reviewer-2: `feature-dev:code-explorer` — 2026-09-26 — **REQUIRED HARDENING BEFORE SHIP** (caller_kind structural failure, middleware hook is `on_message` not `on_call_tool`, `mcp.tool.name` already set upstream, `tests/test_plan_citations.py` doesn't exist, file count drift 35→38, `audit_mcp_tools.py` empty stub collision, `tracing_enabled` gate). 12 revisions; structural items folded into v2 Non-Goal #8, §4 Findings 1/2/3/4, §5 Phase 1 Task 1.1/1.2, §6 Required Code Changes (Task 2.1 rename), §7 Validation Matrix.
- [x] reviewer-3: `mcp-integration-expert` — 2026-09-26 — **REQUIRED HARDENING BEFORE SHIP** (citation discipline, `task_class` attribute missing, wiring-discipline §1+§3, audit_orphans runnability, feature-flag location, cross-component diagram). 11 revisions; structural items folded into v2 §4.5 all REQ `cites:` fields, §5 Phase 1 Task 1.1 (task_class attribute), §5 Phase 1 Task 1.5 (/health aggregator), §5 Phase 1 Task 1.4 (config flag), §4 Findings (cross-component dependency).
- [x] reviewer-4: `akosha-specialist` — 2026-09-26 — **REQUIRED HARDENING BEFORE SHIP** (hardcoded `task_classes` list, `selector` vs `mcp.tool.name`, `outcome`/`duration_ms` extraction, retention, cardinality, metric surface). 11 revisions; structural items folded into v2 §4 Findings 7-11, §4.5 REQ-TSQ-003/-004/-005/-006, §5 Phase 1 Task 1.3 (INTER-REPO), §8 Risks retention/cardinality.
- [x] reviewer-5: `general-purpose` (security lens) — 2026-09-26 — **REQUIRED HARDENING BEFORE SHIP** (middleware order, `caller_kind` under-specified, `error_class` leakage, sanitization parallel, `/health` aggregator, description rubric 6th criterion, security gate for Phase 1). 10 revisions; structural items folded into v2 Non-Goal #8 (drop caller_kind/workflow_id/session_id), Non-Goal #9 (no tool-arg capture), §4 Findings 6 (AuthContextMiddleware contents), §5 Phase 2 Task 2.2 (6th criterion), §9 Promotion rule (security gate requirement).

**Verdict:** 2/5 `APPROVED WITH REVISIONS`, 3/5 `REQUIRED HARDENING BEFORE SHIP`. Plan status demoted `active → draft` pending v2 re-review.

### Round 2 reviewers (v2) — re-review complete 2026-09-26

- [x] reviewer-1: `feature-dev:code-architect` — 2026-09-26 — **APPROVED WITH REVISIONS** (9 of 10 v1 items RESOLVED; 1 PARTIAL — `tests/unit/test_enrichment_boundary.py` added below)
- [x] reviewer-2: `feature-dev:code-explorer` — 2026-09-26 — **APPROVED WITH REVISIONS** (all 7 structural findings RESOLVED; 1 numerical nit fixed inline — file count `38 → 37` at §4 line 63)
- [x] reviewer-3: `mcp-integration-expert` — 2026-09-26 — **APPROVED** (all 11 v1 items RESOLVED)
- [x] reviewer-4: `akosha-specialist` — 2026-09-26 — **APPROVED WITH REVISIONS** (10 of 11 v1 items RESOLVED; 1 PARTIAL — retention policy = owner-side decision, follow-on Akosha plan, not a block)
- [x] reviewer-5: `general-purpose` (security lens) — 2026-09-26 — **APPROVED** (all 10 v1 items RESOLVED; remaining attributes audited for new leakage vectors — none)

**Verdict:** 5/5 verdicts at or above `APPROVED WITH REVISIONS`. 0 `REQUIRED HARDENING BEFORE SHIP`. §9 Promotion Rule met — status promoted `draft → active` on 2026-09-26. Plan is ready for Phase 1 implementation.

### Round 3 — post-fix verification (Phase 1 implementation, 2026-09-27)

After commits 67095d98 (mahavishnu) + a6ff6a7 (akosha) landed Phase 1, re-verification
returned `REQUIRED HARDENING` (4 blocking findings: split gates, integration test
structurally empty, /health aggregator missing mcp_tool_call entry, dead call_next_result
parameter). All four addressed in commits 5e9ad579 (mahavishnu) + a6ff6a7 (akosha).

Re-verification pass on 5e9ad579 + a6ff6a7 returned `APPROVED WITH REVISIONS` (4 lens
verdicts: Correctness AWR, Security APPROVED, Performance AWR, Test quality AWR; 31
findings, 3 medium + 28 low). The 3 medium findings were addressed in commits
8705f469 (mahavishnu microbench) + 076d63b (akosha wire-out). Status promoted
`active → shipped` on 2026-09-27.

- Correctness: APPROVED WITH REVISIONS → fixed (Akkosha wire-out complete)
- Security: APPROVED (clean)
- Performance: APPROVED WITH REVISIONS → fixed (microbench exercises real OTel exporter)
- Test quality: APPROVED WITH REVISIONS → fixed (test asserts span capture)

**Verdict:** Status `shipped`. Phase 1 complete; Phase 2 deferred (REQ-TSQ-010/011/012:
audit + rubric + description rewrites). Follow-on plan captured at
`docs/plans/drafts/2026-09-27-akosha-tool-call-feed-lifecycle.md` for retention
tier + /health pre-warm wiring.
