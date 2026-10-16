---
status: draft
role: implementation
kind: plan
date: 2026-10-15
last_reviewed: 2026-10-15
owner: platform-team
superseded_by: null
topic: bifrost-gateway-wiring
title: "Bifrost Gateway Wiring — Implementation Plan (off spec v1.3)"
replaces: null
related: docs/specs/2026-10-15-bifrost-gateway-wiring-design.md; docs/decisions/wire-up-contract.md; docs/decisions/mcp-backend-wiring-discipline.md; settings/models.yaml; config/bifrost/config.template.json; mahavishnu/llm_gateway/; docs/feature-tracking/2026-09-25-cloud-worker-decision.md

requirements:
  - id: REQ-001
    title: "BifrostConfig settings class on MahavishnuSettings"
  - id: REQ-002
    title: "Agno adapter routes OpenAI/Anthropic/MiniMax through Bifrost when enabled"
  - id: REQ-003
    title: "PROVIDER_PROBES routes minimax through resolve_probe_endpoint when bifrost enabled"
  - id: REQ-004
    title: "AI-CLI worker env-injection (terminal-claude + terminal-qwen) via tmux set-environment"
  - id: REQ-005
    title: "Bifrost observability: counters, /health sub-shapes, alerts, CLI subcommand, e2e tests"
  - id: REQ-006
    title: "Migration cleanup: delete settings/models.yaml:bifrost block, BIFROST_BASE_URL env var, orphan CloudWorker literal"
---

# Bifrost Gateway Wiring — Implementation Plan

> **Source of truth**: this plan is derived from
> `docs/specs/2026-10-15-bifrost-gateway-wiring-design.md` v1.3 (commit
> `2ef94387`). The spec's §5.10 per-Phase Integration Contract blocks are
> preserved verbatim in each Phase below; this plan adds the operational
> structure (Goal / Tasks / Exit criteria / Validation / Risks) that
> `docs/plans/TEMPLATE.md` requires.
>
> **Phase ordering** is independent-rollback: A→B→C-merged→D→E→F. Each
> phase has a kill-switch (set its flag to `false`) that reverts the
> relevant scope without affecting prior phases. **Phase C is merged
> with Phase B** (no separate Phase C) — the spec dropped LlamaIndex
> adapter wiring because `mahavishnu/engines/llamaindex_adapter_impl.py:39-40, 384-386`
> only imports `OllamaEmbedding`/`Ollama` (no OpenAI or Anthropic SDK).
>
> **Out of scope (per spec §3)**: CloudWorker resurrection, llama-server
> or ollama routing through Bifrost, cross-repo Bifrost adoption (Akosha,
> Session-Buddy, Crackerjack, `minimax-coding-plan-mcp`), re-wiring the
> *host* Claude Code MCP transport. See spec §9 Follow-ups for the
> full deferral list.

## 1. Outcome

After this plan ships:

- **`BifrostConfig` settings class** mounted on `MahavishnuSettings`
  (`mahavishnu/core/config.py:2763`) as the `bifrost:` sibling. The
  `extra="forbid"` crackerjack hard-limit and `Field(default_factory=...)`
  precedent from `PiPoolSettings` (`config.py:715-718`) and
  `ChangepointConfig` (`config.py:595-622`) are honored. The class lives
  next to its sibling mounts at `config.py:2961+`.
- **mahavishnu LLM-calling surface routes through Bifrost when enabled.**
  Specifically the Agno adapter (`mahavishnu/engines/agno_adapter_impl.py`)
  — both `_create_openai_model` (`:177-196`) and `_create_anthropic_model`
  (`:198-216`), plus the `_create_minimax_model` (`:240-262`) default
  fallback, plus `PROVIDER_PROBES["minimax"]`
  (`mahavishnu/workers/capabilities/_probes.py:127-132`) via a new
  `resolve_probe_endpoint(provider, settings)` helper called at probe
  time. CloudWorker is **out of scope** (orphan — `docs/feature-tracking/2026-09-25-cloud-worker-decision.md:46`).
  LlamaIndex is **out of scope** (Ollama-only).
- **AI-CLI opt-in per-vendor** via two new flags: `bifrost.route_claude_code`
  (injects `ANTHROPIC_BASE_URL=http://127.0.0.1:8471/anthropic` into
  `terminal-claude` workers) and `bifrost.route_qwen_code` (injects
  `bifrost.qwen_env_var` — default `OPENAI_BASE_URL` — pointing at
  `gateway_api_base(OPENAI, bifrost.base_url)` into `terminal-qwen`
  workers). Both default `false`. Each independent.
- **`settings/models.yaml` `bifrost:` block deleted**; `BIFROST_BASE_URL`
  env var deleted; `MINIMAX_BASE_URL` precedence enforced (bifrost-wins-when-enabled).
- **Per-Phase Integration Contracts** in each Phase below (one per Phase,
  A-F) per `docs/decisions/wire-up-contract.md`.
- **Observability discipline** per `docs/decisions/mcp-backend-wiring-discipline.md`:
  three counters/histograms registered directly with `prometheus_client`
  in `mahavishnu/observability/prometheus_metrics.py`; `/health.bifrost.config`
  and `/health.bifrost.reachable` sub-shapes added to
  `mahavishnu/core/health.py:78` `HealthResponse`; alert rule
  `config/prometheus/bifrost_alerts.yml`; CLI subcommand
  `mahavishnu metrics bifrost`; e2e test asserting
  `'"caller_id":"mahavishnu"'` in `bifrost.log` within 15s (Node stdout
  block-buffering absorbed by the longer window).

**Proof it worked** (reproducible gate):

```bash
# Source-level: no production code references direct MiniMax URLs anymore
grep -rn "minimax\.io/v1" mahavishnu/engines mahavishnu/workers/capabilities \
     mahavishnu/workers/cloud_worker.py mahavishnu/llm_gateway
# Expected: zero hits outside settings/models.yaml and mahavishnu/llm_gateway/ (docs-only)

# BIFROST_BASE_URL is no longer read anywhere
grep -rn BIFROST_BASE_URL .
# Expected: zero hits

# The llm_gateway package now has production consumers
grep -rn "from mahavishnu.llm_gateway" mahavishnu/
# Expected: hits in engines/agno_adapter_impl.py, workers/capabilities/_probes.py, plus tests

# A real Agno dispatch against the cloud tier produces caller_id in bifrost.log
tail -F ~/.local/state/mcp/logs/bifrost.log | grep '"caller_id":"mahavishnu"'
# Expected: at least one line within 15s of any pool_route_execute hitting the cloud tier

# /health surfaces Bifrost state
curl -s http://localhost:8680/health | jq .bifrost.config      # → config block
curl -s http://localhost:8680/health | jq .bifrost.reachable  # → boolean

# CLI subcommand shows non-zero counters after one dispatch
mahavishnu metrics bifrost --source auto --output table
# Expected: dispatch_total > 0; dispatch_latency_seconds populated

# E2E test passes
pytest tests/integration/test_bifrost_routing_e2e.py::test_agno_dispatch_emits_caller_id
```

## 2. Goals

1. **First-class settings, not env-var hack.** Mount on `MahavishnuSettings`
   per the `pi_pool:`, `worktree_storage:`, `goal_teams:`, `changepoint:`
   sibling pattern. Pydantic-settings env-prefix
   `MAHAVISHNU_BIFROST__<FIELD>` (nested delimiter `__`, lowercase per
   pydantic-settings default — `MAHAVISHNU_BIFROST__enabled=true`
   overrides `local.yaml:bifrost.enabled`).
2. **Single source of truth for gateway envelope construction.**
   `mahavishnu/llm_gateway.build_gateway_envelope()`
   (`mahavishnu/llm_gateway/client.py:116`) is the only entry point. No
   ad-hoc header construction in workers or adapters.
3. **mahavishnu LLM callers always go through Bifrost when enabled, fail
   loud when not.** No "best-effort" fallback to direct MiniMax when
   Bifrost is unreachable.
4. **Local tiers stay direct.** `llama_server` (`:8081`) and `ollama`
   (`:11434`) are local-only; Bifrost is not in their chain.
5. **AI-CLI opt-in is a per-vendor flag set.** `bifrost.route_claude_code: bool`
   controls env injection into `terminal-claude`; `bifrost.route_qwen_code: bool`
   controls env injection into `terminal-qwen`. Both default `false`.
   `route_qwen_code` ships `false` until the verification gate
   (`test_qwen_actual_dispatch_emits_caller_id`) passes end-to-end.
6. **Per-request observability.** Each Bifrost dispatch produces a
   log line (Bifrost-side: per `BifrostGatewayRequest.without_prompt()`
   at `mahavishnu/llm_gateway/contract.py:202-217`; Mahavishnu-side:
   caller-side metrics) AND increments counters/histograms. Counters
   are registered directly with `prometheus_client` against the
   per-server `CollectorRegistry` (no allowlist gate; the discipline is
   to keep the label set small and bounded).
7. **Independent rollback per scope.** `bifrost.enabled: false`
   reverts mahavishnu LLM callers; `route_claude_code: false` reverts
   Claude Code; `route_qwen_code: false` reverts Qwen. Each independent.
8. **No backwards compatibility shims.** Pre-1.0 codebase per
   `feedback-no-backwards-compat-pre-1.0.md`: replace, don't extend.
   `BIFROST_BASE_URL` stops working on merge. `settings/models.yaml:bifrost`
   block deleted on merge.
9. **Silent-failure paths closed** (per the silent-failure-hunter
   pattern). `MINIMAX_BASE_URL` precedence is explicit and tested.
   Qwen env-var verification gate precedes `route_qwen_code` shipping
   enabled. Host-vs-worker scope is clarified so operators don't assume
   the host Claude Code session routes through Bifrost.

## 3. Non-Goals

- **Wiring CloudWorker.** Per `docs/feature-tracking/2026-09-25-cloud-worker-decision.md:46`,
  CloudWorker has zero production callers after Plan v3 Phase 4.5b;
  resurrection is separate work.
- **Routing llama-server or ollama through Bifrost.** Local providers
  don't need gateway caching or routing rules.
- **Cross-repo Bifrost adoption.** Mahavishnu-only. Akosha, Session-Buddy,
  Crackerjack, and the `minimax-coding-plan-mcp` server are out of scope.
- **Wiring the LlamaIndex adapter.** `llamaindex_adapter_impl.py:39-40, 384-386`
  imports only `OllamaEmbedding`/`Ollama`; no OpenAI/Anthropic SDK
  client exists to wire.
- **Bifrost semantic cache tuning.** `recommended_cache_mode()`
  (`mahavishnu/llm_gateway/client.py:74-96`) returns the correct policy;
  the spec consumes it.
- **Bifrost provider additions.** The `config/bifrost/config.template.json`
  provider set is the operator's concern.
- **Custom cache TTLs per task.** Defaults are correct for current
  deployment.
- **Bifrost HTTP/WebSocket transport.** HTTP-only; we mirror that.
- **Rewiring the host Claude Code MCP transport.**
  `~/.mcp.json:minimax-coding-plan-mcp` `MINIMAX_API_HOST` is independent.
  Tracked as a follow-up.

## 4. Current Findings

(Full citations in spec §4; the operating numbers for this plan.)

### 4.1 Bifrost gateway runtime state (verified 2026-10-15)

```
$ curl -sS http://localhost:8471/health
{"components":{"db_pings":"ok"},"status":"ok"}
```

`caller_id` field appears 0 times in `~/.local/state/mcp/logs/bifrost.log`
→ no `BifrostGatewayRequest` envelope has ever been sent.

### 4.2 The gap is structural (four layers, all unwired)

1. `mahavishnu/llm_gateway/` package: complete (`build_gateway_envelope`,
   `BifrostGatewayRequest.without_prompt`, `gateway_api_base`) but zero
   production consumers.
2. `settings/models.yaml:103-107` exposes a `bifrost:` block at the
   wrong layer (outside `MahavishnuSettings` envelope).
3. CloudWorker `mahavishnu/workers/cloud_worker.py:37` hardcodes
   `MINIMAX_OPENAI_BASE_URL = "https://api.minimax.io/v1"`.
4. `PROVIDER_PROBES["minimax"]` at `_probes.py:128` hardcodes the same
   URL; module-level dict literal evaluated at import time.

### 4.3 Phase D wiring chain (was broken in v1.2; corrected in v1.3)

The v1.2 spec claimed a chain
`TerminalManager.launch_sessions() → TmuxTerminalAdapter.launch_session() → contract/tmux_adapter.create_session()`.
**That chain does not exist** — `TmuxTerminalAdapter.launch_session()`
(`mahavishnu/terminal/adapters/tmux.py:22`) hardcodes
`worker_type="terminal-claude"` at line 31 and delegates to
`DurableWorkerManager.spawn()` (`mahavishnu/workers/contract/manager.py:126`),
a separate path from `contract/tmux_adapter.create_session()`
(`mahavishnu/workers/contract/tmux_adapter.py:84`). Phase D threads
`worker_type` and `env` through both paths and uses
`tmux set-environment -t <session> KEY VAL` (not `tmux new-session -e`,
which doesn't propagate to spawned panes).

## 5. Implementation Phases

### Phase A — settings schema and observability scaffolding

**Goal**: mount `BifrostConfig` on `MahavishnuSettings`; register the
three Bifrost series in `prometheus_metrics.py`; add the CLI subcommand
skeleton. No production behavior change in this phase — consumers are
introduced in Phase B.

**Tasks** (each linked to a REQ-IDs in §4.5 above):

- [ ] **REQ-001** Add `class BifrostConfig(BaseModel)` to
  `mahavishnu/core/config.py` (next to `ChangepointConfig` at
  `config.py:595-622`). `model_config = ConfigDict(extra="forbid")`.
  Fields: `enabled: bool = False`, `base_url: str = "http://127.0.0.1:8471"`,
  `anthropic_base_url: str = "http://127.0.0.1:8471/anthropic"`,
  `caller_id: str = "mahavishnu"`,
  `cache_mode: Literal["off","direct","semantic"] = "off"`,
  `cache_ttl_seconds: int = 300`, `request_timeout_seconds: int = 30`,
  `route_claude_code: bool = False`, `route_qwen_code: bool = False`,
  `qwen_env_var: str = "OPENAI_BASE_URL"`, `auth_env: str = "BIFROST_API_KEY"`.
- [ ] **REQ-001** Mount on `MahavishnuSettings` (`config.py:2763`) at
  the `pi_pool:` precedent (line `2961+`):
  `bifrost: BifrostConfig = Field(default_factory=BifrostConfig, description="...")`.
- [ ] **REQ-001** Update `settings/mahavishnu.yaml`: add `bifrost:` block
  with defaults (commented-out for documentation; values match `BifrostConfig`).
- [ ] **REQ-001** Update `settings/local.yaml` (gitignored): add
  `bifrost: { enabled: true, route_claude_code: false, route_qwen_code: false }`
  (the opt-in shape operators use).
- [ ] **REQ-005** Register three Prom series directly in
  `mahavishnu/observability/prometheus_metrics.py` (no allowlist gate
  exists or is needed; the per-server `CollectorRegistry` is the
  registration surface at line 51):
  - `mahavishnu_bifrost_dispatch_total{outcome,provider,route_class}` (counter)
  - `mahavishnu_bifrost_dispatch_latency_seconds{provider,route_class}` (histogram)
  - `mahavishnu_bifrost_dispatch_failures_total{provider,reason}` (counter)
- [ ] **REQ-005** Add `mahavishnu metrics bifrost` subcommand skeleton to
  `mahavishnu/metrics_cli.py` (extend the existing `engines` /
  `dispatch` / `bodai` pattern at lines 296+). Flags: `--source {auto,prom,otel}`
  default `auto`, `--output {table,json}` default `table`, `--provider {minimax,anthropic,all}`
  default `all`. Zero series is acceptable pre-B.
- [ ] **REQ-001** Extend `mahavishnu/cli/config_validator.py` to dump
  the `bifrost` schema as part of `mahavishnu config validate`.
- [ ] **REQ-001** Unit tests: `tests/unit/test_config.py::TestBifrostConfigSchema`:
  - `test_defaults` — every field matches spec §5.1
  - `test_env_prefix_override` — `MAHAVISHNU_BIFROST__enabled=true` overrides yaml
  - `test_env_overrides_local_yaml` — env var wins per Oneiric precedence
  - `test_mount_uses_field_default_factory` — mount follows the precedent
  - `test_extra_forbid_rejects_unknown_field` — stray `bifrost.foo` rejected
  - `test_validation_rejects_invalid_cache_mode` — `Literal[...]` enforced

**Exit criteria**:

- `mahavishnu config validate` shows the schema dump for `bifrost`
- `mahavishnu metrics bifrost --source auto --output table` runs (zero series is acceptable)
- `pytest tests/unit/test_config.py::TestBifrostConfigSchema` all green
- `crackerjack run -v` clean
- `python scripts/audit_orphans.py` — no new orphans (BifrostConfig
  is referenced by `MahavishnuSettings` in the same commit)

#### Integration Contract — Phase A

- **Triggered from**:
  - `mahavishnu/core/config.py:load_settings()` (Oneiric loader)
  - `mahavishnu mcp start` → `prometheus_metrics.py` registration at module import
  - `mahavishnu config validate` (manual CLI invocation)
  - `mahavishnu metrics bifrost` (manual CLI invocation, post-registration)

- **Returns to / updates**:
  - `MahavishnuSettings.bifrost` field populated
  - `mahavishnu/observability/prometheus_metrics.py` gains the three
    `mahavishnu_bifrost_*` series against the per-server `CollectorRegistry`
  - `settings/mahavishnu.yaml` and `settings/local.yaml` gain `bifrost:` blocks

- **Demonstrable by**:
  - `mahavishnu config validate | jq .bifrost` shows the schema dump
  - `MAHAVISHNU_BIFROST__enabled=true mahavishnu config validate` shows
    `enabled: true` overriding `local.yaml`
  - `python -c "from mahavishnu.core.config import MahavishnuSettings; s = MahavishnuSettings(); print(s.bifrost)"` — defaults

- **Rollback signal**: revert the `BifrostConfig` mount in
  `config.py`. No production behavior change because Phase B has no
  consumers yet.

- **Observability added**: `mahavishnu_bifrost_*` series registered in
  `prometheus_metrics.py`; zero counters until Phase B dispatches.

### Phase B — mahavishnu LLM-calling surface integration (Agno + PROVIDER_PROBES)

**Goal**: route the Agno adapter's OpenAI/Anthropic/MiniMax paths and
`PROVIDER_PROBES["minimax"]` through Bifrost when enabled. Fail loud
when `bifrost.enabled: true` and Bifrost is unreachable.

**Tasks**:

- [ ] **REQ-002** `mahavishnu/engines/agno_adapter_impl.py`:
  - `LLMProviderFactory.__init__` (line 115) gains
    `settings: MahavishnuSettings | None = None` parameter and
    `self._settings` attribute. **Factory signature contract preserved**:
    the four factory methods keep `(self, model_id: str)` so existing
    `LLMProviderFactory(config)` calls without settings continue to work.
  - `_create_openai_model` (line 177) — when `self._settings.bifrost.enabled`:
    `kwargs["base_url"] = build_gateway_envelope(...).api_base`
    (returns `http://127.0.0.1:8471/v1`).
  - `_create_anthropic_model` (line 198) — same pattern with
    `ProtocolFamily.ANTHROPIC`; `envelope.api_base` resolves to
    `http://127.0.0.1:8471/anthropic`.
  - `_create_minimax_model` (line 240) — rewrite the existing
    `base_url=self.config.base_url or "https://api.minimax.io/v1"`
    default to consult `self._settings.bifrost` first; falls back to
    the literal when `bifrost.enabled: false`.
  - `AgnoAdapter.__init__` (line 481) passes `settings=self.config` (or
    equivalent) into `LLMProviderFactory.__init__`.
- [ ] **REQ-003** `mahavishnu/workers/capabilities/_probes.py`:
  - Add `resolve_probe_endpoint(provider: str, settings: MahavishnuSettings) -> str`
    helper. When `settings.bifrost.enabled and provider == "minimax"`,
    return `settings.bifrost.base_url.rstrip("/") + "/v1/models"`.
    Otherwise return `PROVIDER_PROBES[provider][1]` (the literal).
    `PROVIDER_PROBES` keeps its current shape (line 127) so the probe
    dictionary stays stable for tests.
  - Update `_probe_provider_request` (line 103) to call
    `resolve_probe_endpoint(provider, settings)` instead of reading
    `PROVIDER_PROBES[provider][1]` directly. `settings` plumbed via
    the call site (the function signature gains `settings: MahavishnuSettings | None`).
- [ ] **REQ-002** New `_bifrost_dispatch_heartbeat` wrapper in
  `mahavishnu/engines/agno_adapter_impl.py` (or a sibling helper module)
  emits the Mahavishnu-side log line and increments
  `mahavishnu_bifrost_dispatch_total{outcome,provider,route_class}` per
  dispatch. Wrap every `_create_*_model` consumer's call site (the
  chat-completion invocation, not the model construction).
- [ ] **REQ-006** `test_minimax_base_url_ignored_when_bifrost_enabled`:
  when `bifrost.enabled: true` and `MINIMAX_BASE_URL=https://example.com`,
  `_create_minimax_model` returns `gateway_api_base(OPENAI, bifrost.base_url)`
  (= `http://127.0.0.1:8471/v1`), NOT `https://example.com`. This is
  the silent-failure-hunter guard for the spec §5.6 precedence rule.
- [ ] **REQ-002** `test_factory_signature_unchanged_for_non_bifrost_tests`:
  existing `LLMProviderFactory(config)` calls (no settings) still work.
  Guard for the factory-signature contract.
- [ ] **REQ-002** mcp-common dependency gate: `mcp-common/mcp_common/llm/config.py:16-33`
  `ProviderConfig` (`extra="forbid"`) has no `extra_headers` field;
  `mcp-common/mcp_common/llm/provider.py:42-58` `OpenAICompatibleProvider.__init__`
  only sets `default_headers={"Authorization": ""}` for local providers.
  If the mcp-common PR adding `ProviderConfig.extra_headers` is not
  yet merged, ship with `base_url`-only rewriting + caller_id logging
  at the call site (sufficient for the `caller_id` log assertion per
  spec §1 proof). Widen to header injection when mcp-common merges.
- [ ] **REQ-002/003** Unit tests:
  - `tests/unit/test_agno_adapter.py::TestAgnoAdapterBifrost`:
    - `test_openai_path_routes_through_gateway`
    - `test_anthropic_path_routes_through_gateway`
    - `test_minimax_default_fallback` — `_create_minimax_model` rewrites default when enabled
    - `test_minimax_base_url_ignored_when_bifrost_enabled` (silent-failure guard)
    - `test_base_url_only_when_no_headers_field` — header-injection fallback
    - `test_factory_signature_unchanged_for_non_bifrost_tests`
  - `tests/unit/test_provider_probes.py::TestProviderProbesBifrost`:
    - `test_minimax_url_resolved_when_enabled`
    - `test_minimax_url_unchanged_when_disabled`

**Exit criteria**:

- With `bifrost.enabled: true` in `local.yaml`, an Agno workflow
  invocation produces `'"caller_id":"mahavishnu"'` in `bifrost.log`
  within 15 seconds (per the spec's Node-stdout-buffering mitigation)
- `pytest tests/unit/test_agno_adapter.py::TestAgnoAdapterBifrost` all green
- `pytest tests/unit/test_provider_probes.py::TestProviderProbesBifrost` all green
- `crackerjack run -v` clean
- `python scripts/audit_orphans.py` — no new orphans (the
  `mahavishnu/llm_gateway` imports are now real consumers)

#### Integration Contract — Phase B

- **Triggered from**:
  - `mcp__mahavishnu__trigger_workflow(adapter="agno", ...)` →
    `AgnoAdapter.execute(...)` → `LLMProviderFactory._create_*_model(...)` →
    `OpenAIChat(...)` / `Claude(...)` SDK call → HTTP POST to
    `gateway_api_base(ProtocolFamily, bifrost.base_url)` (or
    `https://api.minimax.io/v1` when `bifrost.enabled: false`).
  - `mcp__mahavishnu__pool_route_execute` followed by capability probe →
    `PROVIDER_PROBES` lookup → `resolve_probe_endpoint("minimax", settings)` →
    HTTP GET to `http://127.0.0.1:8471/v1/models` (or `https://api.minimax.io/v1/models`).

- **Returns to / updates**:
  - HTTP request to Bifrost at `http://127.0.0.1:8471/v1/...` (cloud tier)
  - `_bifrost_dispatch_heartbeat` increments
    `mahavishnu_bifrost_dispatch_total{outcome,provider,route_class}`
  - Mahavishnu-side log line emitted to `mahavishnu.log`
  - Bifrost-side log line emitted to `bifrost.log` (Bifrost's own emission
    per `BifrostGatewayRequest.without_prompt()` shape)

- **Demonstrable by**:
  - `pytest tests/integration/test_bifrost_routing_e2e.py::test_agno_dispatch_emits_caller_id`
    passes within the 15-second window
  - `tail -F ~/.local/state/mcp/logs/bifrost.log | grep '"caller_id":"mahavishnu"'`
    shows entries within 15s of `pool_route_execute` against the cloud tier

- **Rollback signal**:
  - `bifrost.enabled: false` reverts to direct-to-MiniMax (no code change required)
  - Per-provider error rate > 50% over 60s triggers the
    `MahavishnuBifrostErrorRateHigh` alert (Phase E)

- **Observability added**:
  - `mahavishnu_bifrost_dispatch_total{outcome,provider,route_class}` increments
  - `mahavishnu_bifrost_dispatch_latency_seconds{provider,route_class}` populates
  - `mahavishnu_bifrost_dispatch_failures_total{provider,reason}` on failure
  - Per-request INFO log emitted (Bifrost-side + Mahavishnu-side)

### Phase C — merged with Phase B (no separate Phase)

LlamaIndex adapter is Ollama-only per
`mahavishnu/engines/llamaindex_adapter_impl.py:39-40, 384-386` — no
OpenAI or Anthropic SDK client exists to wire. Per spec §3, this is
out of scope. No Phase C work.

### Phase D — AI-CLI worker env-injection (Claude + Qwen)

**Goal**: when an operator sets `bifrost.route_claude_code: true`, every
mahavishnu-spawned `terminal-claude` worker inherits
`ANTHROPIC_BASE_URL=http://127.0.0.1:8471/anthropic`. When
`bifrost.route_qwen_code: true`, every `terminal-qwen` worker inherits
`bifrost.qwen_env_var` (default `OPENAI_BASE_URL`) pointing at
`gateway_api_base(OPENAI, bifrost.base_url)`. **Both via `tmux
set-environment`**, not `tmux new-session -e`.

**Tasks**:

- [ ] **REQ-004** `mahavishnu/workers/contract/tmux_adapter.py:84`
  `create_session(...)` gains `env: dict[str, str] | None = None`.
  After the existing `tmux new-session -d` call, emit
  `tmux -S <socket> set-environment -t <session> KEY VAL` per entry:
  ```python
  if env:
      for key, val in env.items():
          subprocess.run(
              ["tmux", "-S", socket, "set-environment", "-t", session, key, val],
              check=True,
          )
  ```
- [ ] **REQ-004** `mahavishnu/workers/contract/manager.py:126`
  `DurableWorkerManager.spawn(...)` gains `env: dict[str, str] | None = None`
  and threads it into the `create_session` call.
- [ ] **REQ-004** `mahavishnu/terminal/adapters/tmux.py:22`
  `TmuxTerminalAdapter.launch_session(...)` gains
  `worker_type: str = "terminal-claude"` and
  `env: dict[str, str] | None = None` kwargs. Removes the hardcoded
  `worker_type="terminal-claude"` at line 31.
- [ ] **REQ-004** `mahavishnu/terminal/manager.py:240`
  `TerminalManager.launch_sessions(...)` gains
  `worker_type: str = "terminal-claude"` and threads it into the
  adapter call. Builds the `env` dict via a new helper:
  ```python
  def _resolve_worker_env(worker_type: str, bifrost: BifrostConfig) -> dict[str, str]:
      env: dict[str, str] = {}
      if not bifrost.enabled:
          return env
      if worker_type == "terminal-claude" and bifrost.route_claude_code:
          env["ANTHROPIC_BASE_URL"] = bifrost.anthropic_base_url
      elif worker_type == "terminal-qwen" and bifrost.route_qwen_code:
          env[bifrost.qwen_env_var] = gateway_api_base(
              ProtocolFamily.OPENAI, base_url=bifrost.base_url
          )
      return env
  ```
- [ ] **REQ-004** `mahavishnu/workers/registry.py:116, :131` —
  documentation-only (no code change): confirm the registry line
  citations for `terminal-claude` (`:131`) and `terminal-qwen` (`:116`).
- [ ] **REQ-004** Unit tests in
  `tests/unit/test_terminal_worker_settings.py::TestTerminalWorkerSettingsBifrost`
  (note: not `tests/unit/test_worker_contract.py` — that file doesn't
  exist after Plan v3 Phase 4.5b):
  - `test_claude_code_inherits_anthropic_base_url` — `ANTHROPIC_BASE_URL`
    set via `tmux set-environment` when `route_claude_code: true`
  - `test_claude_code_default_unchanged` — `ANTHROPIC_BASE_URL` absent
    when `route_claude_code: false`
  - `test_qwen_code_inherits_qwen_env_var` — `OPENAI_BASE_URL` (default
    `qwen_env_var`) set when `route_qwen_code: true`
  - `test_qwen_code_default_unchanged` — `qwen_env_var` absent when
    `route_qwen_code: false`
  - `test_qwen_env_var_field_override` — custom `qwen_env_var` honored
  - `test_qwen_actual_dispatch_emits_caller_id` — **the verification gate**:
    real Qwen CLI dispatch produces `'"caller_id":"mahavishnu"'` in
    `bifrost.log`. Phase D ships with `route_qwen_code: false` until
    this passes.
- [ ] **REQ-004** Documentation update in `settings/mahavishnu.yaml`:
  add inline comments documenting `route_claude_code: false` and
  `route_qwen_code: false` defaults (no code change; the YAML is the
  operator-facing surface).

**Exit criteria**:

- With `route_claude_code: true`, launch a `terminal-claude` worker;
  `tmux send-keys -t <session> 'printenv ANTHROPIC_BASE_URL' Enter`
  returns `http://127.0.0.1:8471/anthropic`
- With `route_qwen_code: true` AND `qwen_env_var` set to the verified
  Qwen CLI env-var name, an actual Qwen CLI dispatch produces
  `'"caller_id":"mahavishnu"'` line in `bifrost.log` (verification gate)
- `pytest tests/unit/test_terminal_worker_settings.py::TestTerminalWorkerSettingsBifrost`
  all green
- `route_qwen_code: false` remains the default in
  `settings/mahavishnu.yaml` until the verification gate passes
- `crackerjack run -v` clean
- `python scripts/audit_orphans.py` — no new orphans

#### Integration Contract — Phase D

- **Triggered from**:
  - `mcp__mahavishnu__launch_worker(worker_type="terminal-claude"|"terminal-qwen", ...)`
    → `TerminalManager.launch_sessions(worker_type=..., command=...)`
    → `TmuxTerminalAdapter.launch_session(worker_type, env)`
    → `DurableWorkerManager.spawn(worker_type, env)`
    → `contract/tmux_adapter.create_session(env)`
    → `tmux -S <socket> set-environment -t <session> KEY VAL` per env entry.

- **Returns to / updates**:
  - `terminal-claude` subprocess inherits `ANTHROPIC_BASE_URL` when
    `route_claude_code: true`
  - `terminal-qwen` subprocess inherits `bifrost.qwen_env_var` (= `OPENAI_BASE_URL`
    by default) when `route_qwen_code: true`
  - Per-spawn INFO log emitted from `_resolve_worker_env()` showing
    the env-var injection

- **Demonstrable by**:
  - `pytest tests/unit/test_terminal_worker_settings.py::TestTerminalWorkerSettingsBifrost::test_claude_code_inherits_anthropic_base_url` passes
  - `tmux send-keys -t <session> 'printenv ANTHROPIC_BASE_URL' Enter` →
    `http://127.0.0.1:8471/anthropic` (manual integration check; recorded
    in the Phase D run log)
  - `pytest tests/unit/test_terminal_worker_settings.py::TestTerminalWorkerSettingsBifrost::test_qwen_actual_dispatch_emits_caller_id` passes
    — **the gate for shipping `route_qwen_code: true` by default**

- **Rollback signal**:
  - `bifrost.route_claude_code: false` reverts Claude Code
  - `bifrost.route_qwen_code: false` reverts Qwen
  - Each flag is independent

- **Observability added**:
  - Per-spawn INFO log emitted from `_resolve_worker_env()` showing
    the env-var injection (`worker_type`, `KEY=VAL`)

### Phase E — Observability, alerts, e2e, CLI subcommand

**Goal**: `/health` surfaces Bifrost state; alert rule fires on
sustained error rate; e2e test asserts the `caller_id` log line;
`mahavishnu metrics bifrost` returns non-zero counters; Node stdout
buffering mitigation in `scripts/bifrost-gateway.py` so the e2e
assertion window is reliable.

**Tasks**:

- [ ] **REQ-005** `mahavishnu/core/health.py:78` `HealthResponse` gains
  - `bifrost.config: dict[str, Any] | None` — config block projection
    (`BifrostConfig.to_public_dict()`, omitting `auth_env` to avoid
    leaking the env-var name)
  - `bifrost.reachable: bool` — from `_probe_bifrost_state()` (an
    `httpx.get(bifrost.base_url + "/health", timeout=2)` returning
    `200 OK`)
  - Both fields are populated by the existing `aggregate_mahavishnu_health()`
    (called from the `/health` route per the docstring at line 109).
- [ ] **REQ-005** `mahavishnu/observability/prometheus_metrics.py:85`
  existing `mahavishnu_health_feed_status` gauge gains Bifrost
  registration: when `_probe_bifrost_state()` returns `False`, increment
  the gauge with `feed="bifrost", status="degraded"`. The canonical
  per-feed-status metric per the docstring at line 4.
- [ ] **REQ-005** `config/prometheus/bifrost_alerts.yml` — new file,
  sibling to `config/prometheus/health_aggregator_alerts.yml`:
  ```yaml
  - alert: MahavishnuBifrostErrorRateHigh
    expr: |
      sum(rate(mahavishnu_bifrost_dispatch_failures_total[1m]))
        / sum(rate(mahavishnu_bifrost_dispatch_total[1m])) > 0.5
    for: 1m
    annotations:
      summary: "Bifrost dispatch error rate > 50% over 1m"
  ```
- [ ] **REQ-005** `scripts/bifrost-gateway.py:120-126` Node stdout
  buffering mitigation. Replace the `open(..., "ab")` + `subprocess.Popen(...)`
  pattern with `stdbuf -oL -eL` line-buffering:
  ```python
  cmd = ["stdbuf", "-oL", "-eL", *cmd]  # before Popen
  ```
  Alternative: `os.fsync(stdout_log.fileno())` after every dispatch path
  (the e2e test's 15-second window absorbs the flake either way).
- [ ] **REQ-005** `mahavishnu/metrics_cli.py` — extend the
  `mahavishnu metrics bifrost` subcommand skeleton (Phase A) to read
  from the per-server `CollectorRegistry` via
  `prometheus_metrics.get_health_metrics_registry()`. Render
  `mahavishnu_bifrost_*` series with the three flags (`--source`,
  `--output`, `--provider`) per spec §5.7.
- [ ] **REQ-005** `tests/integration/test_bifrost_routing_e2e.py` — new:
  - `test_agno_dispatch_emits_caller_id` — after an Agno workflow
    invocation, `bifrost.log` contains `'"caller_id":"mahavishnu"'`
    within 15 seconds. Uses `pytest.mark.timeout(60)`.
  - `test_bifrost_dispatch_metrics_e2e` — `mahavishnu metrics bifrost`
    shows non-zero `dispatch_total` and a populated
    `dispatch_latency_seconds` histogram after one dispatch.
  - `test_bifrost_health_e2e` — `GET /health` JSON includes
    `bifrost.config` and `bifrost.reachable`.
  - `test_bifrost_disabled_direct_path_e2e` — with `bifrost.enabled: false`,
    `pool_route_execute` reaches `https://api.minimax.io/v1` directly
    (asserted via mock or via Bifrost log absence).
  - `test_bifrost_qwen_verification_gate` — with `route_qwen_code: true`
    AND verified Qwen env-var name, a real Qwen CLI dispatch produces
    a `'"caller_id":"mahavishnu"'` line in `bifrost.log`. This is the gate
    for shipping `route_qwen_code: true` enabled by default.

**Exit criteria**:

- `curl -s http://localhost:8680/health | jq .bifrost.config` returns the config block
- `curl -s http://localhost:8680/health | jq .bifrost.reachable` returns a boolean
- `mahavishnu metrics bifrost --source auto --output table` returns non-zero counters after one dispatch against the cloud tier with `bifrost.enabled: true`
- `pytest tests/integration/test_bifrost_*.py` all green
- `crackerjack run -v` clean
- `python scripts/audit_requirements.py` — zero orphans, zero phantoms

#### Integration Contract — Phase E

- **Triggered from**:
  - `mcp__mahavishnu__get_health` → `GET /health` →
    `aggregate_mahavishnu_health()` → `BifrostConfig.to_public_dict()` +
    `_probe_bifrost_state()` → populates `health.bifrost.config` and
    `health.bifrost.reachable`
  - `mahavishnu metrics bifrost` (manual CLI invocation)
  - Prom scrape → `config/prometheus/bifrost_alerts.yml` rule evaluates
    on `mahavishnu_bifrost_dispatch_*` series

- **Returns to / updates**:
  - `/health.bifrost.config` returns the config block
  - `/health.bifrost.reachable` returns a boolean
  - `mahavishnu_health_feed_status{feed="bifrost",status=...}` gauge
    increments on probe
  - `mahavishnu metrics bifrost` reads from local Prom registry
  - `config/prometheus/bifrost_alerts.yml` ships the
    `MahavishnuBifrostErrorRateHigh` rule

- **Demonstrable by**:
  - `curl -s http://localhost:8680/health | jq .bifrost.config` returns
    a JSON object (not null)
  - `curl -s http://localhost:8680/health | jq .bifrost.reachable`
    returns a boolean
  - `mahavishnu metrics bifrost --source auto --output table` shows
    non-zero `dispatch_total` after one Phase B dispatch
  - `pytest tests/integration/test_bifrost_*.py` all green

- **Rollback signal**:
  - Per `mcp-backend-wiring-discipline.md`: when `bifrost.reachable`
    is `False`, `/health.bifrost.reachable` propagates to
    `mahavishnu_health_feed_status{feed="bifrost",status="degraded"}`
    and the `/health` route returns 503
  - Alert `MahavishnuBifrostErrorRateHigh` fires when error rate > 50%
    over 1m

- **Observability added**: full observability surface —
  Bifrost-side + Mahavishnu-side log lines, counters/histograms, alert
  rule, e2e tests, CLI subcommand, Node stdout buffering mitigation.

### Phase F — Migration cleanup (replace-not-extend)

**Goal**: delete the structurally-misplaced `bifrost:` block from
`settings/models.yaml`; stop reading `BIFROST_BASE_URL`; replace the
four in-tree runtime `minimax.io/v1` hits with bifrost-aware URLs (or
delete the dead `MINIMAX_OPENAI_BASE_URL` constant in the orphan
CloudWorker).

**Tasks**:

- [ ] **REQ-006** `settings/models.yaml:103-107` — delete the `bifrost:`
  block (3 lines: `# Bifrost gateway (activated via env vars only)`,
  `bifrost:`, `  enabled: false`, `  base_url: ...`, `  activate_env: ...`).
  This file is loaded outside the `MahavishnuSettings` envelope; the
  block was structurally misplaced from day one.
- [ ] **REQ-006** `mahavishnu/workers/cloud_worker.py:37` — delete
  `MINIMAX_OPENAI_BASE_URL = "https://api.minimax.io/v1"` constant.
  CloudWorker is orphan per
  `docs/feature-tracking/2026-09-25-cloud-worker-decision.md:46`; the
  constant has zero readers. This is a dead-code deletion, not a
  refactor.
- [ ] **REQ-006** `mahavishnu/engines/agno_adapter_impl.py:244` —
  docstring fix: the comment "Base URL: https://api.minimax.io/v1"
  is updated post-Phase B (the default has moved to
  `gateway_api_base(OPENAI, bifrost.base_url)` when enabled).
- [ ] **REQ-006** `mahavishnu/engines/agno_adapter_impl.py:259` —
  factory default-fallback now reads `BifrostConfig` (the Phase B
  change is in place; this task is the "verify it's in place" check
  that the Phase F gate is meaningful).
- [ ] **REQ-006** `mahavishnu/workers/capabilities/_probes.py:128` —
  probe URL now resolved via `resolve_probe_endpoint` (the Phase B
  change is in place; this task is the verify check).
- [ ] **REQ-006** Remove any `BIFROST_BASE_URL` references in
  `docs/` and `config/`. `grep -rn BIFROST_BASE_URL .` returns zero hits.
- [ ] **REQ-006** Add a docs-CI grep check
  (`scripts/audit_bifrost_grep.py` or extend
  `scripts/audit_plan_index.py`) that enforces the four proof
  assertions from spec §1 on every PR.

**Exit criteria**:

- `grep -rn "minimax\.io/v1" mahavishnu/engines mahavishnu/workers/capabilities mahavishnu/workers/cloud_worker.py mahavishnu/llm_gateway` returns zero hits outside `settings/models.yaml` and `mahavishnu/llm_gateway/`
- `grep -rn BIFROST_BASE_URL .` returns zero hits
- `grep -rn "bifrost:" settings/models.yaml` returns zero hits
- `python scripts/audit_orphans.py` — zero new orphans; `BifrostConfig`
  has at least one consumer (the `MahavishnuSettings` mount)
- `python scripts/audit_requirements.py` — zero orphans, zero phantoms
- `crackerjack run -v` clean

#### Integration Contract — Phase F

- **Triggered from**:
  - `git rm` (or equivalent edit) of the `bifrost:` block in
    `settings/models.yaml`
  - `git grep` over the repo to verify the four proof assertions
  - The new docs-CI grep check (added in this Phase) running on
    every PR

- **Returns to / updates**:
  - `settings/models.yaml` no longer has `bifrost:` block
  - `BIFROST_BASE_URL` env var is no longer read in any code or doc
  - The four in-tree runtime `minimax.io/v1` hits are deleted
    (CloudWorker literal) or replaced (Agno default, _probes URL)
  - The docs-CI grep check is added

- **Demonstrable by**:
  - The four `grep` commands return zero hits in the listed paths
  - The new docs-CI grep check passes on a clean PR
  - The Phase A-F integration contracts still hold end-to-end

- **Rollback signal**: revert the four replacement edits. The
  `models.yaml` block deletion is a single-file revert.

- **Observability added**: a docs-CI grep check enforces the proof
  assertions on every PR. Regressions on this check alert via the
  existing `crackerjack` hooks pipeline.

## 6. Required Code Changes

Grouped by package. Each check is a one-line change in one commit
(pre-1.0: no PRs, direct merge per `bodai-pre-1.0-merge-policy.md`).

### `mahavishnu/core/`

- [ ] `config.py` — new `class BifrostConfig(BaseModel)` (Phase A)
- [ ] `config.py` — mount `bifrost: BifrostConfig` on
  `MahavishnuSettings` (Phase A)
- [ ] `config.py` — `BifrostConfig.to_public_dict()` method (Phase E)
- [ ] `health.py:78` — add `bifrost.config` and `bifrost.reachable`
  fields to `HealthResponse` (Phase E)
- [ ] `health.py` — `_probe_bifrost_state()` helper (Phase E)
- [ ] `health.py` — call `_probe_bifrost_state()` from
  `aggregate_mahavishnu_health()` (Phase E)

### `mahavishnu/observability/`

- [ ] `prometheus_metrics.py` — register `mahavishnu_bifrost_dispatch_total`,
  `mahavishnu_bifrost_dispatch_latency_seconds`,
  `mahavishnu_bifrost_dispatch_failures_total` directly with
  `prometheus_client` against the per-server `CollectorRegistry`
  (Phase A; data populates in Phase B)
- [ ] `prometheus_metrics.py:85` — register Bifrost in
  `mahavishnu_health_feed_status` gauge on probe (Phase E)

### `mahavishnu/engines/`

- [ ] `agno_adapter_impl.py:115` — `LLMProviderFactory.__init__` gains
  `settings: MahavishnuSettings | None = None` and `self._settings`
  (Phase B)
- [ ] `agno_adapter_impl.py:177` — `_create_openai_model` consults
  `self._settings.bifrost` (Phase B)
- [ ] `agno_adapter_impl.py:198` — `_create_anthropic_model` consults
  `self._settings.bifrost` (Phase B)
- [ ] `agno_adapter_impl.py:240` — `_create_minimax_model` consults
  `self._settings.bifrost` (Phase B)
- [ ] `agno_adapter_impl.py:481` — `AgnoAdapter.__init__` passes
  settings into `LLMProviderFactory` (Phase B)
- [ ] `agno_adapter_impl.py` — new `_bifrost_dispatch_heartbeat`
  wrapper (Phase B)

### `mahavishnu/workers/`

- [ ] `capabilities/_probes.py:127` — add `resolve_probe_endpoint(provider, settings)`
  helper (Phase B)
- [ ] `capabilities/_probes.py:103` — `_probe_provider_request` calls
  `resolve_probe_endpoint` (Phase B)
- [ ] `contract/tmux_adapter.py:84` — `create_session` gains
  `env: dict[str, str] | None = None`; emits
  `tmux set-environment -t <session> KEY VAL` per entry (Phase D)
- [ ] `contract/manager.py:126` — `DurableWorkerManager.spawn` gains
  `env` kwarg and threads it (Phase D)
- [ ] `cloud_worker.py:37` — delete `MINIMAX_OPENAI_BASE_URL` constant
  (Phase F)

### `mahavishnu/terminal/`

- [ ] `adapters/tmux.py:22` — `TmuxTerminalAdapter.launch_session` gains
  `worker_type: str` and `env: dict[str, str] | None` (Phase D)
- [ ] `manager.py:240` — `TerminalManager.launch_sessions` gains
  `worker_type: str` and threads it (Phase D)
- [ ] `manager.py` — new `_resolve_worker_env(worker_type, bifrost)`
  helper (Phase D)

### `mahavishnu/cli/`

- [ ] `config_validator.py` — extend `mahavishnu config validate` to
  dump the `bifrost` schema (Phase A)
- [ ] `metrics_cli.py` — add `mahavishnu metrics bifrost` subcommand
  (Phase A skeleton; Phase E full read)

### `settings/`

- [ ] `mahavishnu.yaml` — add `bifrost:` block with defaults
  (documented but commented-out) (Phase A)
- [ ] `local.yaml` — add `bifrost: { enabled: true, ... }` opt-in
  (Phase A)
- [ ] `models.yaml:103-107` — delete `bifrost:` block (Phase F)

### `config/`

- [ ] `prometheus/bifrost_alerts.yml` — new alert rule file (Phase E)
- [ ] `bifrost/config.template.json` — **no change** (Bifrost config
  template is the operator's concern; the spec does not redesign it)

### `scripts/`

- [ ] `bifrost-gateway.py:120-126` — Node stdout buffering mitigation
  (`stdbuf -oL -eL` or `os.fsync` alternative) (Phase E)
- [ ] `audit_bifrost_grep.py` — new docs-CI grep check enforcing the
  four Phase F proof assertions (Phase F; or extend
  `audit_plan_index.py` if simpler)

### `tests/`

- [ ] `unit/test_config.py::TestBifrostConfigSchema` — Phase A
- [ ] `unit/test_agno_adapter.py::TestAgnoAdapterBifrost` — Phase B
- [ ] `unit/test_provider_probes.py::TestProviderProbesBifrost` — Phase B
- [ ] `unit/test_terminal_worker_settings.py::TestTerminalWorkerSettingsBifrost` — Phase D
- [ ] `integration/test_bifrost_routing_e2e.py` — Phase E
- [ ] `integration/test_bifrost_health_e2e.py` — Phase E

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `mahavishnu config validate` | Schema dump shows `bifrost:` block with all 11 fields | stdout (CI log) |
| `MAHAVISHNU_BIFROST__enabled=true mahavishnu config validate` | `enabled: true` overrides `local.yaml` | stdout |
| `python -c "from mahavishnu.core.config import MahavishnuSettings; print(MahavishnuSettings().bifrost)"` | Defaults match spec §5.1 | stdout |
| `pytest tests/unit/test_config.py::TestBifrostConfigSchema` | All 6 tests green | CI log |
| `pytest tests/unit/test_agno_adapter.py::TestAgnoAdapterBifrost` | All 6 tests green | CI log |
| `pytest tests/unit/test_provider_probes.py::TestProviderProbesBifrost` | All 2 tests green | CI log |
| `pytest tests/unit/test_terminal_worker_settings.py::TestTerminalWorkerSettingsBifrost` | All 6 tests green | CI log |
| `pytest tests/integration/test_bifrost_routing_e2e.py::test_agno_dispatch_emits_caller_id` | Passes within 15s | CI log |
| `pytest tests/integration/test_bifrost_health_e2e.py` | `/health.bifrost.{config,reachable}` populated | CI log |
| `tail -F ~/.local/state/mcp/logs/bifrost.log \| grep '"caller_id":"mahavishnu"'` | ≥ 1 line per cloud-tier dispatch | bifrost.log (operator) |
| `curl -s http://localhost:8680/health \| jq .bifrost.config` | Config block JSON | HTTP probe |
| `curl -s http://localhost:8680/health \| jq .bifrost.reachable` | Boolean | HTTP probe |
| `mahavishnu metrics bifrost --source auto --output table` | Non-zero `dispatch_total` after one dispatch | stdout (operator) |
| `crackerjack run -v -f` | All hooks green | CI log |
| `python scripts/audit_orphans.py` | Zero new orphans | CI log |
| `python scripts/audit_requirements.py` | Zero orphans, zero phantoms | CI log |
| `grep -rn "minimax\.io/v1" mahavishnu/engines mahavishnu/workers/capabilities mahavishnu/workers/cloud_worker.py mahavishnu/llm_gateway` | Zero hits (post-Phase F) | shell |
| `grep -rn BIFROST_BASE_URL .` | Zero hits (post-Phase F) | shell |
| `grep -rn "bifrost:" settings/models.yaml` | Zero hits (post-Phase F) | shell |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| **mcp-common PR not merged before Phase B** — `ProviderConfig.extra_headers` not yet available | Medium | Phase B ships with `base_url`-only rewriting + caller_id logging at the call site (sufficient for the spec §1 `caller_id` proof). Widen to header injection in a Phase B-plus-one when mcp-common merges. |
| **Qwen CLI's actual env-var name is not `OPENAI_BASE_URL`** (candidates: `QWEN_BASE_URL`, `DASHSCOPE_API_BASE`) | Medium | `bifrost.qwen_env_var: str = "OPENAI_BASE_URL"` is operator-overridable in `local.yaml`. Phase D ships with `route_qwen_code: false` until the verification gate (`test_qwen_actual_dispatch_emits_caller_id`) passes end-to-end. |
| **Node stdout block-buffering** hides the `caller_id` log line for >5s | High | Phase E mitigates with `stdbuf -oL -eL`. The 15-second test timeout (not 5s) absorbs the flake per the existing precedent. |
| **Bifrost not running locally** at the time of testing | Medium | The verification suite documents a `lsof -nP -iTCP:8471 -sTCP:LISTEN` check before each test; tests skip (not fail) when Bifrost is unreachable. |
| **CloudWorker resurrection** reintroduces a hardcoded `minimax.io/v1` URL | Low | Phase F deletes `MINIMAX_OPENAI_BASE_URL` constant; the docs-CI grep check enforces zero hits on every PR. The orphan decision is recorded in `docs/feature-tracking/2026-09-25-cloud-worker-decision.md:46`. |
| **Pre-1.0 backwards-compat drift** (`BIFROST_BASE_URL` env var lingers) | Low | Per `feedback-no-backwards-compat-pre-1.0.md`: replace, don't extend. Phase F deletes the env var. Operators with the old env var set get a Pydantic `SettingsError` on validation, which is the correct loud-failure per `mcp-backend-wiring-discipline.md` §1. |
| **Crackerjack gate regresses** on the new `extra="forbid"` and `Field(default_factory=...)` discipline | Low | Phase A's `TestBifrostConfigSchema` asserts both explicitly; the gate is verified by `crackerjack run -v -f` clean. |
| **Spec/plan citation drift** (the file:line numbers in §4.3 and §5 shift) | Medium | The plan cites are verified at draft time (2026-10-15). The `scripts/audit_requirements.py` and the spec's own `Citation verification` (acceptance criterion 8) gate promotion. Drift during implementation = fix the citation, not the code (unless the code moved legitimately). |

## 9. Decision Rule

The plan is **done enough** when all six phases ship in one merge (or
stacked phase-gated merges — per `bodai-pre-1.0-merge-policy.md`, no
PRs; direct merge to main). Specifically:

- All four proof assertions in §1 return zero hits in the listed paths
  (post-Phase F)
- `pytest tests/integration/test_bifrost_routing_e2e.py::test_agno_dispatch_emits_caller_id`
  passes within 15 seconds
- `mahavishnu metrics bifrost --source auto --output table` returns
  non-zero `dispatch_total` after one cloud-tier dispatch
- `curl -s http://localhost:8680/health | jq .bifrost.reachable`
  returns a boolean
- `crackerjack run -v -f` is clean
- `python scripts/audit_orphans.py` reports zero new orphans
- `python scripts/audit_requirements.py` reports zero orphans, zero phantoms
- `route_qwen_code: false` remains the default in
  `settings/mahavishnu.yaml` until the verification gate passes
- `local.yaml` ships `bifrost: { enabled: true, route_claude_code: false, route_qwen_code: false }`

When scope pressure forces a cut:

- **Phase A is non-negotiable** (the settings class is the foundation)
- **Phase B is the primary value** (this is the wiring that makes
  Bifrost reachable from production code); trim mcp-common header-injection
  if the PR isn't ready
- **Phase D is operator-facing** (AI-CLI opt-in); can defer
  `route_qwen_code` to a follow-up
- **Phase E is observability discipline** (per the project rule
  `mcp-backend-wiring-discipline.md`); trim the alert rule if the
  Prom backend isn't ready, but keep the `/health` sub-shape
- **Phase F is the migration cleanup** (replace-not-extend); trim if
  the operator-conflict cost is too high (pre-1.0 only)

---

## References

- `docs/specs/2026-10-15-bifrost-gateway-wiring-design.md` — source spec
  v1.3 (commit `2ef94387`)
- `docs/decisions/wire-up-contract.md` — integration contract discipline
- `docs/decisions/mcp-backend-wiring-discipline.md` — observability + health sub-shape discipline
- `docs/plans/TEMPLATE.md` — this template
- `docs/plans/PLAN_INDEX.md` — plan index
- `docs/feature-tracking/2026-09-25-cloud-worker-decision.md:46` — CloudWorker orphan decision
- `mahavishnu/llm_gateway/` — the package this plan wires
- `config/bifrost/config.template.json` — operator's gateway config
- `settings/models.yaml` — the structurally-misplaced block this plan
  deletes in Phase F
- `feedback-no-backwards-compat-pre-1.0.md` — replace-not-extend discipline
- `feedback-cli-flag-consumer-wiring.md` — instantiation-site grep discipline
- `feedback-commit-plan-files-immediately.md` — commit plan files right
  after writing (the plan's own creation is bound by this rule)
- `feedback-bodai-push-is-user-controlled.md` — never `git push` for bodai
  without explicit approval
- `feedback-mcp-common-version-bump-is-user.md` — never bump mcp-common
  version; user does
- `scripts/audit_orphans.py`, `scripts/audit_requirements.py` — CI gates
- `crackerjack run -v -f` — final gate
