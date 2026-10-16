---
status: active
role: implementation
kind: plan
date: 2026-10-15
last_reviewed: 2026-10-16
owner: platform-team
superseded_by: null
topic: bifrost-gateway-wiring
title: "Bifrost Gateway Wiring — Implementation Plan (off spec v1.5)"
replaces: null
related: docs/specs/2026-10-15-bifrost-gateway-wiring-design.md; docs/decisions/wire-up-contract.md; docs/decisions/mcp-backend-wiring-discipline.md; settings/models.yaml; config/bifrost/config.template.json; mahavishnu/llm_gateway/; docs/feature-tracking/2026-09-25-cloud-worker-decision.md; ~/Library/LaunchAgents/com.bodai.llama-server.plist

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
    title: "Migration cleanup: delete settings/models.yaml:bifrost block, BIFROST_BASE_URL env var, preserve CloudWorker KEEP"
  - id: REQ-007
    title: "Local llama-server provider (Phase G): Bifrost config block, launchd plist fix, model download, e2e health gate"
---

# Bifrost Gateway Wiring — Implementation Plan

> **v1.2 amendment applied (2026-10-16)**: **Local llama-server provider as a first-class Bifrost target (Phase G).** Operator decision: keep llama-server (port 8081) and add it to the Bifrost gateway alongside the cloud LLMs; ollama is being removed from the ecosystem in a separate session. The previous "Routing llama-server or ollama through Bifrost" non-goal is dropped; the previous "Bifrost provider additions" non-goal is dropped for llama-server specifically. **Three new files in Phase G**: `config/bifrost/config.template.json` (add `llama-server` provider block + update `route-background` rule to prefer local with MiniMax fallback + add new `route-classify` rule for cheap classification/extraction); `~/Library/LaunchAgents/com.bodai.llama-server.plist` (correct argv — drop the broken `-tb 256` pair, change `-fa` to `-fa on`, change `-port 11434` to `--port 8081` with `--host 127.0.0.1`, point `-m` at a real model file); downloaded GGUF model at `/usr/local/share/llama-server/models/qwen3-8b-q4_k_m.gguf` (Qwen3-8B Q4_K_M, ~4.5GB, from Hugging Face `Qwen/Qwen3-8B-GGUF` repo). **Three new `BifrostConfig` fields**: `local_provider_enabled: bool = True` (runtime kill-switch), `local_provider_url: str = "http://127.0.0.1:8081"`, `local_provider_model: str = "qwen3-8b-q4_k_m"`. **`BifrostHealth` sub-model gains `local_provider_reachable: bool`**. **New counter**: `mahavishnu_bifrost_local_dispatch_total{outcome, model}` (label set extended by one — still bounded). **New e2e test file**: `tests/integration/test_bifrost_local_provider_e2e.py` with `test_llama_server_health_endpoint` (the gate that catches a future regression — if the plist is broken or the model is missing, this test fails). **Phase ordering extended to A→B→C-merged-into-B→D→E→F→G**[^phase-letters]. **Reasoning-class rules stay cloud-only**: `route-think`, `route-long-context`, `route-web-search` do NOT route to llama-server — local models are not appropriate for high-reasoning tasks, 100K+ context, or tool-use. **REQ-007** declared in the plan frontmatter.
>
> **v1.1 amendment applied (2026-10-16)**: post-3-lens review corrections re-applied (the merge-to-main pipeline had rolled them back between commits — restoring these now). **Convergent BLOCKER across `mahavishnu-specialist` + `mcp-integration-expert` lenses**: **CloudWorker KEEP correction** — §4.2 item 3, §5.10 Phase F, §6 Required Code Changes, §7 Validation Matrix, §8 Risks, and §9 Decision Rule all cite `docs/feature-tracking/2026-09-25-cloud-worker-decision.md:58` (Decision: KEEP) instead of `:46` (audit finding, which is the rationale for KEEP, not orphan evidence). The `mahavishnu/workers/cloud_worker.py:37` `MINIMAX_OPENAI_BASE_URL` constant is preserved (it is read as the `MINIMAX_BASE_URL` env-var `default_factory` fallback at `cloud_worker.py:57`); §5.10 Phase F grep scope tightened to exclude `mahavishnu/workers/cloud_worker.py`; the §7 Validation Matrix row for the minimax.io/v1 grep drops the `cloud_worker.py` path. **GAP (`mcp-integration-expert`)**: **Phase D plural `launch_sessions` threading** — `TmuxTerminalAdapter.launch_sessions()` (plural, `tmux.py:37`) is an explicit thread-through point: the adapter's plural method gains `worker_type` and `env` kwargs and forwards them to `launch_session()` per iteration, which calls `self._manager.spawn(worker_type, env)`. Without the plural update, `TerminalManager.launch_sessions(worker_type=..., env=env)` fails at the adapter boundary (the current plural `async def launch_sessions(self, command: str, count: int) -> list[str]` accepts neither kwarg). **NIT (`mcp-integration-expert`)**: **BifrostHealth sub-model shape** — §5 Phase E explicitly names the `class BifrostHealth(BaseModel)` sub-model with `model_config = ConfigDict(extra="forbid")`, `config: dict[str, Any] | None`, `reachable: bool`; mounted as `bifrost: BifrostHealth = Field(default_factory=BifrostHealth, ...)` on `HealthResponse` (NOT `bifrost: BifrostHealth | None` — Pydantic v2 forbids dotted field names). **Status promoted to `active`**.
>
> **Source of truth**: this plan is derived from
> `docs/specs/2026-10-15-bifrost-gateway-wiring-design.md` v1.5 (Phase G
> added the local llama-server provider). The spec's §5.10 per-Phase
> Integration Contract blocks are preserved verbatim in each Phase below;
> this plan adds the operational structure (Goal / Tasks / Exit criteria /
> Validation / Risks) that `docs/plans/TEMPLATE.md` requires.
>
> **Phase ordering** is independent-rollback: A→B→C-merged-into-B→D→E→F→G[^phase-letters]. Each
> phase has a kill-switch (set its flag to `false`) that reverts the
> relevant scope without affecting prior phases. **Phase C is merged
> with Phase B** (no separate Phase C) — the spec dropped LlamaIndex
> adapter wiring because `mahavishnu/engines/llamaindex_adapter_impl.py:39-40, 384-386`
> only imports `OllamaEmbedding`/`Ollama` (no OpenAI or Anthropic SDK).
> **Phase G is independently kill-switched** via `bifrost.local_provider_enabled: bool` — when `False`, the local provider is bypassed without removing the plist or the provider block.
>
> **Out of scope (per spec §3)**: CloudWorker resurrection, ollama
> routing through Bifrost (ollama is being removed from the ecosystem
> in a separate session), cross-repo Bifrost adoption (Akosha,
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
- **Local llama-server provider (Phase G)** — `config/bifrost/config.template.json`
  registers a `llama-server` provider at `http://127.0.0.1:8081`. The
  `route-background` and `route-classify` routing rules prefer
  `llama-server/qwen3-8b-q4_k_m` first, fall back to
  `minimax-openai/MiniMax-M3` on local failure. Three new
  `BifrostConfig` fields gate the integration: `local_provider_enabled: bool = True`
  (runtime kill-switch), `local_provider_url: str = "http://127.0.0.1:8081"`,
  `local_provider_model: str = "qwen3-8b-q4_k_m"`. The launchd plist
  `~/Library/LaunchAgents/com.bodai.llama-server.plist` is corrected
  (Phase G real wiring deliverable — argv mis-shape + missing model
  path are fixed; a real GGUF model is downloaded). Reasoning-class
  rules stay cloud-only.
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
     mahavishnu/llm_gateway
# Expected: zero hits. (CloudWorker excluded per the KEEP decision at
# docs/feature-tracking/2026-09-25-cloud-worker-decision.md:58 — see §5.10
# Phase F notes.)

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

- **Wiring CloudWorker.** Per `docs/feature-tracking/2026-09-25-cloud-worker-decision.md:58` (Decision: KEEP),
  CloudWorker is preserved as a public API surface exported via
  `mahavishnu/workers/__init__.py:32`. The audit finding on line 46
  (zero production or test imports outside the file itself and its
  package export) is the *rationale* for KEEP, NOT evidence of orphan
  status. The constant `MINIMAX_OPENAI_BASE_URL` at
  `cloud_worker.py:37` is read as the `MINIMAX_BASE_URL` env-var
  `default_factory` fallback at `cloud_worker.py:57`; deleting it
  breaks `CloudWorkerConfig()` at import time. The constant is preserved.
- **Routing ollama through Bifrost.** Ollama is being removed from the
  ecosystem in a separate session. While it lives, ollama's `:11434`
  stays direct (not a Bifrost target). The distinction from llama-server
  is deliberate: llama-server is wired into a launchd plist that we
  can fix and gate via e2e; ollama is going away. **llama-server is in scope** — Phase G wires it as a first-class Bifrost provider at `:8081`.
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
   `MINIMAX_OPENAI_BASE_URL = "https://api.minimax.io/v1"`. **The constant
   is preserved per the KEEP decision at
   `docs/feature-tracking/2026-09-25-cloud-worker-decision.md:58`**
   (CloudWorker is a public API surface exported via
   `mahavishnu/workers/__init__.py:32`; the audit finding on line 46
   — "zero production or test imports of CloudWorker outside the file
   itself and its package export" — is the *rationale* for the KEEP
   decision, NOT evidence of orphan status. The decision is on line
   58 and reads "KEEP" on five counts: external API surface, doc
   contract, working code, retirement cost > benefit, wrapper value.).
   The constant is read as the `MINIMAX_BASE_URL` env-var fallback at
   `cloud_worker.py:57`
   (`default_factory=lambda: os.environ.get("MINIMAX_BASE_URL") or MINIMAX_OPENAI_BASE_URL`),
   so deleting it breaks `CloudWorkerConfig()` instantiation at module
   import time. **This plan inherits an upstream spec drift on this
   point** (the v1.3 spec §5.10 carried the same "CloudWorker orphan"
   misread; flag for a v1.4 amendment).
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
  Each field uses `Field(default=..., description="...")` per the
  `ChangepointConfig.detector` precedent at `config.py:622`:
  ```python
  enabled: bool = Field(default=False, description="Enable Bifrost gateway routing for mahavishnu LLM callers")
  base_url: str = Field(default="http://127.0.0.1:8471", description="Bifrost gateway base URL")
  anthropic_base_url: str = Field(default="http://127.0.0.1:8471/anthropic", description="Bifrost Anthropic-compatible base URL")
  caller_id: str = Field(default="mahavishnu", description="Caller identity sent in BifrostGatewayRequest envelope")
  cache_mode: Literal["off","direct","semantic"] = Field(default="off", description="Bifrost cache mode; see BifrostGatewayRequest")
  cache_ttl_seconds: int = Field(default=300, description="Bifrost cache TTL in seconds")
  request_timeout_seconds: int = Field(default=30, description="Per-request HTTP timeout for Bifrost dispatch")
  route_claude_code: bool = Field(default=False, description="Inject ANTHROPIC_BASE_URL into terminal-claude workers when bifrost.enabled")
  route_qwen_code: bool = Field(default=False, description="Inject qwen_env_var into terminal-qwen workers when bifrost.enabled")
  qwen_env_var: str = Field(default="OPENAI_BASE_URL", description="Env var name that the Qwen CLI reads for a custom OpenAI-compatible base URL")
  auth_env: str = Field(default="BIFROST_API_KEY", description="Env var name carrying the optional Bifrost bearer token (omitted from /health.bifrost.config to avoid leaking the env-var name)")
  ```
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
  `dispatch` / `bodai` pattern — `engines` at line 781, `dispatch`
  at line 1244, `bodai` at line 1287 in the current file). Flags: `--source {auto,prom,otel}`
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

- **Rollback signal**: no operational signal needed in Phase A — zero
  Bifrost traffic until Phase B dispatches. The validation gate is
  `mahavishnu metrics bifrost --source auto --output table` shows zero
  counters; if any `mahavishnu_bifrost_*` series is non-zero before
  Phase B, revert the `BifrostConfig` mount in `config.py`. The
  absence-of-counter is the rollback signal.

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
- [ ] **REQ-004** `mahavishnu/terminal/adapters/tmux.py:22` and `:37` —
  `TmuxTerminalAdapter.launch_session(...)` (singular) and
  `launch_sessions(...)` (plural) both gain
  `worker_type: str = "terminal-claude"` and
  `env: dict[str, str] | None = None` kwargs. **Both methods** thread
  the new params into the underlying
  `self._manager.spawn(worker_type=..., env=...)` call — the singular
  makes the `spawn` call directly; the plural calls `launch_session`
  per iteration and forwards `worker_type` and `env`. Removes the
  hardcoded `worker_type="terminal-claude"` at line 31. Without the
  plural update, the manager's call
  `self.adapter.launch_sessions(worker_type=..., env=env)` fails at
  the adapter boundary (the current plural
  `async def launch_sessions(self, command: str, count: int) -> list[str]`
  accepts neither kwarg).
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
  a `bifrost: BifrostHealth | None` field via a new sub-model
  (Pydantic v2 forbids dotted field names, so the sub-model shape
  is required to surface `bifrost.config` and `bifrost.reachable`
  in the JSON response):
  ```python
  class BifrostHealth(BaseModel):
      model_config = ConfigDict(extra="forbid")
      config: dict[str, Any] | None = None  # BifrostConfig.to_public_dict() projection (omits auth_env)
      reachable: bool = False               # from _probe_bifrost_state()
  ```
  Mounted as `bifrost: BifrostHealth = Field(default_factory=BifrostHealth, description="...")` on `HealthResponse`. Both fields are populated by the existing
  `aggregate_mahavishnu_health()` (called from the `/health` route
  per the docstring at line 109). `_probe_bifrost_state()` is an
  `httpx.get(bifrost.base_url + "/health", timeout=2)` returning
  `200 OK` (boolean). `to_public_dict()` omits `auth_env` to avoid
  leaking the env-var name.
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
- [ ] `tests/integration/conftest.py` — add skip-fixture that runs `lsof -nP -iTCP:8471 -sTCP:LISTEN` and `pytest.skip(...)` when Bifrost is unreachable. Apply via `pytestmark = pytest.mark.skipif(...)` in each `tests/integration/test_bifrost_*.py`. The risk-mitigation in §8 row "Bifrost not running locally" promises this behavior but it is not implemented today.

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
three in-tree runtime `minimax.io/v1` hits
(`_probes.py:128`, `agno_adapter_impl.py:244` docstring,
`agno_adapter_impl.py:259` factory default-fallback) with
bifrost-aware URLs. **CloudWorker is OUT of scope for Phase F** —
the KEEP decision at
`docs/feature-tracking/2026-09-25-cloud-worker-decision.md:58`
preserves `cloud_worker.py:37` `MINIMAX_OPENAI_BASE_URL`. The
Phase F grep scope excludes `mahavishnu/workers/cloud_worker.py`.

**Tasks**:

- [ ] **REQ-006** `settings/models.yaml:103-107` — delete the `bifrost:`
  block (5 lines: `# Bifrost gateway (activated via env vars only)`,
  `bifrost:`, `  enabled: false`, `  base_url: ...`, `  activate_env: ...`).
  This file is loaded outside the `MahavishnuSettings` envelope; the
  block was structurally misplaced from day one.
- [ ] **REQ-006** **CloudWorker is out of scope for Phase F.** Per
  `docs/feature-tracking/2026-09-25-cloud-worker-decision.md:58`
  (Decision: KEEP), CloudWorker is a public API surface exported
  via `mahavishnu/workers/__init__.py:32`. The audit finding on
  line 46 ("zero production or test imports outside the file itself
  and its package export") is the rationale for KEEP, not for
  retirement. The constant `MINIMAX_OPENAI_BASE_URL` at
  `cloud_worker.py:37` is read as the `default_factory` fallback at
  `cloud_worker.py:57` and is preserved per the KEEP decision.
  **This is a spec drift fix** — the v1.3 spec §5.10 carried the
  same "CloudWorker orphan" misread; flag for a v1.4 amendment.
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

- `grep -rn "minimax\.io/v1" mahavishnu/engines mahavishnu/workers/capabilities mahavishnu/llm_gateway` returns zero hits (CloudWorker excluded per the KEEP decision at `docs/feature-tracking/2026-09-25-cloud-worker-decision.md:58`)
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
  - The three in-tree runtime `minimax.io/v1` hits are deleted or
    replaced: `_probes.py:128` (probe URL → `resolve_probe_endpoint`),
    `agno_adapter_impl.py:244` (docstring), `agno_adapter_impl.py:259`
    (factory default-fallback → `BifrostConfig`)
  - The CloudWorker `MINIMAX_OPENAI_BASE_URL` constant at
    `cloud_worker.py:37` is **preserved** per the KEEP decision
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

### Phase G — Local llama-server provider integration (real wiring deliverable)

**Goal**: register llama-server as a first-class Bifrost provider, fix
the broken launchd plist, download a real GGUF model, and gate the
integration on a `curl http://127.0.0.1:8081/health` e2e check so a
future regression is caught. The v1.4 state on this machine had
`~/Library/LaunchAgents/com.bodai.llama-server.plist` in a perpetual
crash-loop: argv mis-shape (`-fa` was being parsed with `-tb` as its
value, the arg parser rejects it) and the model path didn't exist
(`/usr/local/bin/models/...` is a symlink to a Homebrew formula
binary). Phase G corrects both, downloads a real model, and adds the
e2e gate.

**Tasks**:

- [ ] **REQ-007** `config/bifrost/config.template.json` — add
  `llama-server` provider block at `http://127.0.0.1:8081` with
  `base_provider_type: openai`, models list `["qwen3-8b-q4_k_m"]`,
  key sourced from `env.LLAMA_SERVER_API_KEY` (default empty — open
  on localhost).
  Update `route-background` rule (priority 50) to target
  `llama-server/qwen3-8b-q4_k_m` first, fallback
  `minimax-openai/MiniMax-M3`. Add new `route-classify` rule
  (priority 60) with the same target/fallback for `x-bf-task: classify`
  / `x-bf-route: classify` / `x-bf-task: extract` / `x-bf-route: extract`.
  Reasoning-class rules (`route-think`, `route-long-context`,
  `route-web-search`) do NOT change.
- [ ] **REQ-007** `~/Library/LaunchAgents/com.bodai.llama-server.plist`
  — replace the broken plist with the corrected version:
  - **Drop the broken `-tb 256` pair** (the parser was reading `-tb` as the value of `-fa`).
  - **Change `-fa` to `-fa on`** (explicit Flash Attention enable; llama.cpp expects `on|off|auto` — numeric values like `-fa 1` are rejected with the same "unknown value for --flash-attn" error that crashed the original plist).
  - **Change `-port 11434` to `--port 8081`** with `--host 127.0.0.1` (move from ollama's port to the standard local-LLM port; bind to loopback only).
  - **Model path: `/usr/local/share/llama-server/models/qwen3-8b-q4_k_m.gguf`** (Qwen3-8B Q4_K_M, ~4.5GB; fits on Apple Silicon with 99 GPU layers).
  - Keep `RunAtLoad: true` and `KeepAlive: true`.
- [ ] **REQ-007** Download the GGUF model:
  ```bash
  mkdir -p /usr/local/share/llama-server/models
  huggingface-cli download Qwen/Qwen3-8B-GGUF qwen3-8b-q4_k_m.gguf \
      --local-dir /usr/local/share/llama-server/models/
  ```
  (Requires `huggingface-cli` on PATH; install via `pipx install
  huggingface_hub` or `uv tool install huggingface-hub` if not
  present. Phase G assumes the operator's machine has network access
  to Hugging Face.)
- [ ] **REQ-007** Reload the plist so the corrected argv takes effect:
  ```bash
  launchctl unload ~/Library/LaunchAgents/com.bodai.llama-server.plist
  launchctl load ~/Library/LaunchAgents/com.bodai.llama-server.plist
  ```
  Verify with `launchctl print gui/$(id -u)/com.bodai.llama-server` —
  must report `state = running` and `last exit code = 0`. If still
  crashing, check `~/Library/Logs/llama-server.err.log` for the
  specific error (Phase G's e2e test surfaces this).
- [ ] **REQ-007** `mahavishnu/core/config.py` — `BifrostConfig` gains
  three new fields with `Field(default=..., description="...")` per the
  `ChangepointConfig.detector` precedent:
  ```python
  local_provider_enabled: bool = Field(default=True, description="Enable local llama-server as a Bifrost target for cheap/background tasks")
  local_provider_url: str = Field(default="http://127.0.0.1:8081", description="llama-server base URL (Bifrost-side)")
  local_provider_model: str = Field(default="qwen3-8b-q4_k_m", description="Default local model name for routing rules")
  ```
- [ ] **`mahavishnu/llm_gateway/contract.py`** — add `CLASSIFY = "classify"` and `EXTRACT = "extract"` to the `RouteClass` enum (line 20-30); add corresponding entries in `_TASK_LABEL_MAP` (line 41-55). This is the prerequisite for the `route-classify` Bifrost rule to fire on the wire — without it, the rule is structurally dead code (the contract's `route_headers` only emits values from this enum, and the existing enum doesn't have CLASSIFY/EXTRACT).
- [ ] **`mahavishnu/engines/agno_adapter_impl.py`** — extend the `_bifrost_dispatch_heartbeat` wrapper to increment `mahavishnu_bifrost_local_dispatch_total{outcome, provider="llama-server", route_class}` on both success and failure paths of the local route. The counter is registered in Phase A but no current code path increments it; this gap was caught by the 3-lens review (would fail the e2e `test_local_dispatch_metrics` assertion).
- [ ] **Prerequisite**: `command -v huggingface-cli || uv tool install huggingface-hub` — verify `huggingface-cli` is on PATH before the model download task. The download line in this Phase assumes the tool is available; on a clean machine the operator hits a 404 from Hugging Face before realizing the tool isn't installed. Add to Phase G exit criteria: ``command -v huggingface-cli`` exits 0 on the operator's machine.
- [ ] **REQ-007** `settings/mahavishnu.yaml` — add the three new fields
  with the same defaults (commented-out for documentation; values
  match `BifrostConfig`).
- [ ] **REQ-007** `settings/local.yaml` — default opt-in:
  `bifrost: { enabled: true, ..., local_provider_enabled: true, ... }`.
- [ ] **REQ-007** `mahavishnu/core/health.py` — `BifrostHealth` sub-model
  gains a `local_provider_reachable: bool = False` field (with
  `ConfigDict(extra="forbid")` and the existing `config` /
  `reachable` fields). `_probe_local_provider_state()` is a new helper
  that does `httpx.get(bifrost.local_provider_url + "/health",
  timeout=2)` returning `200 OK` (boolean), called from
  `aggregate_mahavishnu_health()`.
- [ ] **REQ-007** `mahavishnu/observability/prometheus_metrics.py` —
  register `mahavishnu_bifrost_local_dispatch_total{outcome, model}`
  counter (label set extended by one — still bounded under 5 total).
- [ ] **REQ-007** `config/prometheus/bifrost_alerts.yml` — append
  `MahavishnuBifrostLocalErrorRateHigh` rule (per-provider error rate
  > 50% over 1m on local target).
- [ ] **REQ-007** `tests/unit/test_config.py::TestBifrostConfigSchema`
  — new tests:
  - `test_local_provider_enabled_default` — defaults to `True`.
  - `test_local_provider_url_default` — defaults to
    `http://127.0.0.1:8081`.
  - `test_local_provider_model_default` — defaults to
    `qwen3-8b-q4_k_m`.
  - `test_local_provider_enabled_env_override` —
    `MAHAVISHNU_BIFROST__local_provider_enabled=false` overrides yaml.
  - `test_local_provider_url_env_override` — same for url.
- [ ] `tests/unit/test_llm_gateway_contract.py::test_classify_routes_via_classify_route_class` (NEW — contract-layer Phase G change verification)
- [ ] `test_local_provider_empty_api_key_does_not_send_bearer` (NEW — silent-failure guard for the empty `LLAMA_SERVER_API_KEY` case)
- [ ] **REQ-007** `tests/integration/test_bifrost_local_provider_e2e.py`
  (new file) — e2e tests:
  - `test_llama_server_health_endpoint` — `curl -s
    http://127.0.0.1:8081/health` returns 200 OK within 5 seconds.
    Uses `pytest.mark.timeout(30)`. **Skips (not fails) when
    `bifrost.local_provider_enabled: false`** (documented expectation).
  - `test_route_background_prefers_local` — a Bifrost dispatch with
    `x-bf-task: background` (and a stub `llama-server` returning 200)
    reaches the local target before falling back to MiniMax. Asserts
    `provider=llama-server` appears in the Mahavishnu-side log line.
  - `test_route_classify_prefers_local` — same as above for
    `x-bf-task: classify`.
  - `test_local_provider_disabled_falls_through_to_cloud` — with
    `bifrost.local_provider_enabled: false`, a `x-bf-task: background`
    request skips the local target and reaches
    `minimax-openai/MiniMax-M3` directly. Asserts no
    `provider=llama-server` log line.
  - `test_local_provider_health_subshape` —
    `GET /health | jq .bifrost.local_provider_reachable` returns a boolean.
  - `test_local_dispatch_metrics` — `mahavishnu metrics bifrost
    --source auto --output table` shows non-zero `local_dispatch_total`
    after one local dispatch.

**Exit criteria**:

- `launchctl print gui/$(id -u)/com.bodai.llama-server` reports
  `state = running` and `last exit code = 0`
- `curl -s http://127.0.0.1:8081/health` returns 200 OK within 5 seconds
- `curl -s http://127.0.0.1:8081/v1/models` lists the configured model
- `grep -c 'qwen3-8b-q4_k_m' config/bifrost/config.template.json` ≥ 2
  (provider block + routing rule)
- `curl -s http://localhost:8680/health | jq .bifrost.local_provider_reachable`
  returns a boolean
- `pytest tests/unit/test_config.py::TestBifrostConfigSchema::test_local_provider_*` all green
- `pytest tests/integration/test_bifrost_local_provider_e2e.py` all green (or skipped if `local_provider_enabled: false`)
- `mahavishnu metrics bifrost --source auto --output table` shows
  non-zero `local_dispatch_total` after one local dispatch
- `python scripts/audit_orphans.py` — no new orphans
- `crackerjack run -v` clean
- ``command -v huggingface-cli`` exits 0 (prerequisite for the model download task; covers the case where the tool isn't installed on a clean machine)
- `pytest tests/unit/test_llm_gateway_contract.py::test_classify_routes_via_classify_route_class` passes (Phase G contract change verified)
- `pytest tests/integration/test_bifrost_local_provider_e2e.py::test_local_dispatch_metrics` asserts non-zero `local_dispatch_total` (positive-result; the e2e gate is **not vacuous** — distinguishes the real-wiring receipt from the kill-switch smoke-test that may skip)

#### Integration Contract — Phase G

- **Triggered from**:
  - Any Bifrost dispatch with `x-bf-task` header in `{background,
    cheap, high_throughput, classify, extract}` (Bifrost's CEL
    engine matches against the routing rules)
  - `launchctl load` of the corrected plist on boot
  - `mcp__mahavishnu__get_health` for the
    `local_provider_reachable` sub-shape

- **Returns to / updates**:
  - `config/bifrost/config.template.json` gains the `llama-server`
    provider block and the updated `route-background` rule plus the
    new `route-classify` rule
  - `~/Library/LaunchAgents/com.bodai.llama-server.plist` is corrected
    (argv, port, model path) and reloaded
  - `/usr/local/share/llama-server/models/qwen3-8b-q4_k_m.gguf`
    exists and is the loaded model
  - `BifrostConfig` gains `local_provider_enabled`, `local_provider_url`,
    `local_provider_model` fields
  - `BifrostHealth` sub-model gains `local_provider_reachable` field
  - `mahavishnu_bifrost_local_dispatch_total{outcome, model}` counter
    registered
  - `config/prometheus/bifrost_alerts.yml` gains
    `MahavishnuBifrostLocalErrorRateHigh` rule

- **Demonstrable by**:
  - `launchctl print gui/$(id -u)/com.bodai.llama-server` reports
    `state = running` and `last exit code = 0`
  - `curl -s http://127.0.0.1:8081/health` returns 200 OK
  - `curl -s http://127.0.0.1:8081/v1/models` lists the configured model
  - `grep -c 'qwen3-8b-q4_k_m' config/bifrost/config.template.json` ≥ 2
  - `curl -s http://localhost:8680/health | jq .bifrost.local_provider_reachable`
    returns a boolean
  - `pytest tests/integration/test_bifrost_local_provider_e2e.py` all green
  - `mahavishnu metrics bifrost --source auto --output table` shows
    non-zero `local_dispatch_total` after one local dispatch

- **Rollback signal**:
  - `bifrost.local_provider_enabled: false` reverts to cloud-only
    routing (the local provider is bypassed without removing the plist
    or the provider block)
  - Per-provider error rate > 50% over 60s on the local target triggers the `MahavishnuBifrostLocalErrorRateHigh` alert with PromQL: `sum(rate(mahavishnu_bifrost_local_dispatch_total{outcome="failure"}[1m])) / sum(rate(mahavishnu_bifrost_local_dispatch_total[1m])) > 0.5` (mirrors Phase E's `MahavishnuBifrostErrorRateHigh` shape; uses the new `outcome` label filter rather than the legacy `provider` filter, since the local counter is registered with `{outcome, provider, route_class}` per the mcp-integration-expert lens's recommendation)
  - `/health.bifrost.local_provider_reachable=false` propagates to
    `mahavishnu_health_feed_status{feed="bifrost",status="degraded"}`
    (operator-visible but not page-able — cloud fallback handles it)

- **Observability added**:
  - `mahavishnu_bifrost_local_dispatch_total{outcome, provider, route_class}` counter (label set normalized to match the master `mahavishnu_bifrost_dispatch_total` shape for dashboard tier uniformity per the mcp-integration-expert lens's GAP-2 recommendation; the Bifrost label-set bound expands to 5 — `{outcome, provider, route_class, reason, model}` — per the v1.5 amendment)
  - `mahavishnu_health_feed_status{feed="bifrost",status="degraded"}`
    gauge increments on local-unreachable probe
  - `/health.bifrost.local_provider_reachable` boolean in the
    `BifrostHealth` sub-model
  - Per-dispatch INFO log line with `provider=llama-server` (or
    `provider=minimax-openai` on cloud fallback)
  - launchd plist stdout/stderr at `~/Library/Logs/llama-server.log`
    and `~/Library/Logs/llama-server.err.log` (operator-side
    observability for the local process)

## 6. Required Code Changes

Grouped by package. Each check is a one-line change in one commit
(pre-1.0: no PRs, direct merge per `bodai-pre-1.0-merge-policy.md`).

### `mahavishnu/core/`

- [ ] `config.py` — new `class BifrostConfig(BaseModel)` (Phase A)
- [ ] `config.py` — mount `bifrost: BifrostConfig` on
  `MahavishnuSettings` (Phase A)
- [ ] `config.py` — `BifrostConfig.to_public_dict()` method (Phase E)
- [ ] `config.py` — `BifrostConfig` gains `local_provider_enabled`,
  `local_provider_url`, `local_provider_model` fields (Phase G)
- [ ] `health.py:78` — add `bifrost.config` and `bifrost.reachable`
  fields to `HealthResponse` (Phase E)
- [ ] `health.py` — `_probe_bifrost_state()` helper (Phase E)
- [ ] `health.py` — call `_probe_bifrost_state()` from
  `aggregate_mahavishnu_health()` (Phase E)
- [ ] `health.py` — `BifrostHealth` sub-model gains
  `local_provider_reachable: bool` field (Phase G)
- [ ] `health.py` — `_probe_local_provider_state()` helper (Phase G)
- [ ] `health.py` — call `_probe_local_provider_state()` from
  `aggregate_mahavishnu_health()` (Phase G)

### `mahavishnu/observability/`

- [ ] `prometheus_metrics.py` — register `mahavishnu_bifrost_dispatch_total`,
  `mahavishnu_bifrost_dispatch_latency_seconds`,
  `mahavishnu_bifrost_dispatch_failures_total` directly with
  `prometheus_client` against the per-server `CollectorRegistry`
  (Phase A; data populates in Phase B)
- [ ] `prometheus_metrics.py` — register
  `mahavishnu_bifrost_local_dispatch_total{outcome, model}` counter
  (Phase G; data populates when local provider is exercised)
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
- [ ] `agno_adapter_impl.py` — extend `_bifrost_dispatch_heartbeat` wrapper to increment `mahavishnu_bifrost_local_dispatch_total{outcome, provider, route_class}` on both success and failure paths of the local route (Phase G)

### `mahavishnu/llm_gateway/`

- [ ] `contract.py` — add `CLASSIFY = "classify"` and `EXTRACT = "extract"` to the `RouteClass` enum; add corresponding entries in `_TASK_LABEL_MAP` (Phase G; prerequisite for the `route-classify` Bifrost rule to fire on the wire)

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
- [ ] `cloud_worker.py:37` — **NO CHANGE** (preserved per the KEEP
  decision at `docs/feature-tracking/2026-09-25-cloud-worker-decision.md:58`;
  see §5.10 Phase F notes)

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
- [ ] `mahavishnu.yaml` — extend `bifrost:` block with the three
  Phase G fields (`local_provider_enabled`, `local_provider_url`,
  `local_provider_model`) (Phase G)
- [ ] `local.yaml` — add `bifrost: { enabled: true, ... }` opt-in
  (Phase A)
- [ ] `local.yaml` — extend opt-in with `local_provider_enabled: true`
  (Phase G)
- [ ] `models.yaml:103-107` — delete `bifrost:` block (Phase F)

### `config/`

- [ ] `prometheus/bifrost_alerts.yml` — new alert rule file (Phase E)
- [ ] `prometheus/bifrost_alerts.yml` — append
  `MahavishnuBifrostLocalErrorRateHigh` rule (Phase G)
- [ ] `bifrost/config.template.json` — add `llama-server` provider
  block at `http://127.0.0.1:8081`; update `route-background` rule
  to target `llama-server/qwen3-8b-q4_k_m` first with
  `minimax-openai/MiniMax-M3` fallback; add new `route-classify` rule
  (Phase G)

### `~/Library/LaunchAgents/`

- [ ] `com.bodai.llama-server.plist` — correct argv (drop broken
  `-tb 256` pair, change `-fa` to `-fa on`, change `-port 11434` to
  `--port 8081` with `--host 127.0.0.1`, point `-m` at
  `/usr/local/share/llama-server/models/qwen3-8b-q4_k_m.gguf`); reload
  via `launchctl unload && launchctl load` (Phase G)

### Model downloads (one-time)

- [ ] `huggingface-cli download Qwen/Qwen3-8B-GGUF qwen3-8b-q4_k_m.gguf
  --local-dir /usr/local/share/llama-server/models/` — ~4.5GB
  (Phase G)

### `scripts/`

- [ ] `bifrost-gateway.py:120-126` — Node stdout buffering mitigation
  (`stdbuf -oL -eL` or `os.fsync` alternative) (Phase E)
- [ ] `audit_bifrost_grep.py` — new docs-CI grep check enforcing the
  four Phase F proof assertions (Phase F; or extend
  `audit_plan_index.py` if simpler)

### `tests/`

- [ ] `unit/test_config.py::TestBifrostConfigSchema` — Phase A
- [ ] `unit/test_config.py::TestBifrostConfigSchema::test_local_provider_*` — Phase G
- [ ] `unit/test_llm_gateway_contract.py::test_classify_routes_via_classify_route_class` — Phase G contract change verification
- [ ] `unit/test_agno_adapter.py::TestAgnoAdapterBifrost` — Phase B
- [ ] `unit/test_provider_probes.py::TestProviderProbesBifrost` — Phase B
- [ ] `unit/test_terminal_worker_settings.py::TestTerminalWorkerSettingsBifrost` — Phase D
- [ ] `integration/test_bifrost_routing_e2e.py` — Phase E
- [ ] `integration/test_bifrost_health_e2e.py` — Phase E
- [ ] `integration/conftest.py` — skip-fixture for offline Bifrost (`lsof -nP -iTCP:8471 -sTCP:LISTEN` check + `pytest.skip(...)`; covers the risk-mitigation promised in §8 row "Bifrost not running locally" but not implemented today) (Phase E)
- [ ] `integration/test_bifrost_local_provider_e2e.py` — new file (Phase G)

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `mahavishnu config validate` | Schema dump shows `bifrost:` block with all 14 fields (11 Phase A + 3 Phase G) | stdout (CI log) |
| `MAHAVISHNU_BIFROST__enabled=true mahavishnu config validate` | `enabled: true` overrides `local.yaml` | stdout |
| `python -c "from mahavishnu.core.config import MahavishnuSettings; print(MahavishnuSettings().bifrost)"` | Defaults match spec §5.1 | stdout |
| `pytest tests/unit/test_config.py::TestBifrostConfigSchema` | All 11 tests green (Phase A: 6 tests + Phase G: 5 new = 11 total) | CI log |
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
| `grep -rn "minimax\.io/v1" mahavishnu/engines mahavishnu/workers/capabilities mahavishnu/llm_gateway` | Zero hits (post-Phase F; CloudWorker excluded per KEEP decision) | shell |
| `grep -rn BIFROST_BASE_URL .` | Zero hits (post-Phase F) | shell |
| `grep -rn "bifrost:" settings/models.yaml` | Zero hits (post-Phase F) | shell |
| `launchctl print gui/$(id -u)/com.bodai.llama-server` | `state = running`, `last exit code = 0` (post-Phase G) | launchctl |
| `curl -s http://127.0.0.1:8081/health` | 200 OK (post-Phase G) | HTTP probe |
| `curl -s http://127.0.0.1:8081/v1/models` | Lists `qwen3-8b-q4_k_m` (post-Phase G) | HTTP probe |
| `grep -c 'qwen3-8b-q4_k_m' config/bifrost/config.template.json` | ≥ 3 (1 provider block + 2 routing rules — `route-background` and `route-classify`) (post-Phase G) | shell |
| `curl -s http://localhost:8680/health \| jq .bifrost.local_provider_reachable` | Boolean (post-Phase G) | HTTP probe |
| `pytest tests/unit/test_config.py::TestBifrostConfigSchema::test_local_provider_*` | All 5 new tests green (Phase A: 6 tests + Phase G: 5 new = 11 total) | CI log |
| `pytest tests/integration/test_bifrost_local_provider_e2e.py` | All green or skipped (post-Phase G) | CI log |
| `pytest tests/unit/test_llm_gateway_contract.py::test_classify_routes_via_classify_route_class` | Passes (Phase G contract change verified) | CI log |
| `mahavishnu metrics bifrost --source auto --output table` | Non-zero `local_dispatch_total` after one local dispatch (post-Phase G) | stdout (operator) |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| **mcp-common PR not merged before Phase B** — `ProviderConfig.extra_headers` not yet available | Medium | Phase B ships with `base_url`-only rewriting + caller_id logging at the call site (sufficient for the spec §1 `caller_id` proof). Widen to header injection in a Phase B-plus-one when mcp-common merges. |
| **Qwen CLI's actual env-var name is not `OPENAI_BASE_URL`** (candidates: `QWEN_BASE_URL`, `DASHSCOPE_API_BASE`) | Medium | `bifrost.qwen_env_var: str = "OPENAI_BASE_URL"` is operator-overridable in `local.yaml`. Phase D ships with `route_qwen_code: false` until the verification gate (`test_qwen_actual_dispatch_emits_caller_id`) passes end-to-end. |
| **Node stdout block-buffering** hides the `caller_id` log line for >5s | High | Phase E mitigates with `stdbuf -oL -eL`. The 15-second test timeout (not 5s) absorbs the flake per the existing precedent. |
| **Bifrost not running locally** at the time of testing | Medium | The verification suite documents a `lsof -nP -iTCP:8471 -sTCP:LISTEN` check before each test; tests skip (not fail) when Bifrost is unreachable. |
| **CloudWorker resurrection** reintroduces a hardcoded `minimax.io/v1` URL | Low | Phase F is **out of scope** for CloudWorker per the KEEP decision at `docs/feature-tracking/2026-09-25-cloud-worker-decision.md:58`. The constant `MINIMAX_OPENAI_BASE_URL` at `cloud_worker.py:37` is preserved (read as `default_factory` fallback at `cloud_worker.py:57`). The Phase F grep scope excludes `mahavishnu/workers/cloud_worker.py`. A separate decision is needed before any future CloudWorker deletion. |
| **Pre-1.0 backwards-compat drift** (`BIFROST_BASE_URL` env var lingers) | Low | Per `feedback-no-backwards-compat-pre-1.0.md`: replace, don't extend. Phase F deletes the env var. Operators with the old env var set get a Pydantic `SettingsError` on validation, which is the correct loud-failure per `mcp-backend-wiring-discipline.md` §1. |
| **Crackerjack gate regresses** on the new `extra="forbid"` and `Field(default_factory=...)` discipline | Low | Phase A's `TestBifrostConfigSchema` asserts both explicitly; the gate is verified by `crackerjack run -v -f` clean. |
| **llama-server launchd plist breaks again after Phase G** (e.g., Homebrew `llama` formula update changes `llama-server` argv shape, or the model file is removed) | Medium | The `test_llama_server_health_endpoint` e2e test gates on `curl -s http://127.0.0.1:8081/health` returning 200 — any future plist breakage or missing model file is caught at CI time. The `local_provider_enabled: false` runtime kill-switch lets operators bypass the integration without removing the plist. |
| **Qwen3-8B quality insufficient for the routed task classes** (background/cheap/classify) | Low | The routing rules only target llama-server for `x-bf-task in {background, cheap, high_throughput, classify, extract}` — all latency-tolerant, cost-sensitive, and relatively simple. Reasoning-class tasks (`route-think`, `route-long-context`, `route-web-search`) stay cloud-only. If the Qwen3-8B model proves insufficient, the operator edits `bifrost.local_provider_model` to a different model name (e.g., `qwen3-8b-q4_k_m`) without code changes; the model file is the only thing that needs to be re-downloaded. |
| **Spec/plan citation drift** (the file:line numbers in §4.3 and §5 shift) | Medium | The plan cites are verified at draft time (2026-10-15). The `scripts/audit_requirements.py` and the spec's own `Citation verification` (acceptance criterion 8) gate promotion. Drift during implementation = fix the citation, not the code (unless the code moved legitimately). |

## 9. Decision Rule

The plan is **done enough** when all seven phases ship in one merge (or
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
- `local.yaml` ships `bifrost: { enabled: true, route_claude_code: false, route_qwen_code: false, local_provider_enabled: true }`
- **Phase G gate (REQ-007)**: `launchctl print
  gui/$(id -u)/com.bodai.llama-server` reports `state = running`;
  `curl -s http://127.0.0.1:8081/health` returns 200 OK; `grep -c
  'qwen3-8b-q4_k_m' config/bifrost/config.template.json` ≥ 2;
  `pytest tests/integration/test_bifrost_local_provider_e2e.py` all
  green (or skipped if `local_provider_enabled: false`); the
  e2e gate catches a future regression

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

[^phase-letters]: (Phase letters do not track alphabet after the C→B merge; Phase G is real and follows F.)

## References

- `docs/specs/2026-10-15-bifrost-gateway-wiring-design.md` — source spec
  v1.5 (Phase G: local llama-server provider)
- `docs/decisions/wire-up-contract.md` — integration contract discipline
- `docs/decisions/mcp-backend-wiring-discipline.md` — observability + health sub-shape discipline
- `docs/plans/TEMPLATE.md` — this template
- `docs/plans/PLAN_INDEX.md` — plan index
- `docs/feature-tracking/2026-09-25-cloud-worker-decision.md:58` —
  CloudWorker **KEEP** decision (the audit finding on line 46 is the
  *rationale* for the KEEP decision, not orphan evidence)
- `mahavishnu/llm_gateway/` — the package this plan wires
- `config/bifrost/config.template.json` — operator's gateway config
  (Phase G: `llama-server` provider block + updated `route-background`
  rule + new `route-classify` rule)
- `settings/models.yaml` — the structurally-misplaced block this plan
  deletes in Phase F
- `~/Library/LaunchAgents/com.bodai.llama-server.plist` — Phase G
  real wiring deliverable (corrected argv + port + model path)
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

## Amendment history

- **v1.2 (2026-10-16)** — local llama-server provider as a first-class
  Bifrost target. Phase G added. Three new `BifrostConfig` fields
  (`local_provider_enabled`, `local_provider_url`,
  `local_provider_model`); new `route-classify` rule and updated
  `route-background` rule; launchd plist fix (argv mis-shape + missing
  model path); e2e gate `test_llama_server_health_endpoint` catches
  future regressions. Mirrored in spec v1.5 amendment paragraph.
  REQ-007 declared in the plan frontmatter.

- **v1.1 (2026-10-16)** — 3-correction post-plan-review amendment. Applied
  to the plan body and mirrored in the spec (spec v1.4 amendment
  paragraph):
  1. **CloudWorker KEEP correction** (BLOCKER, both lenses) — re-cite
     `:58` instead of `:46`; preserve `cloud_worker.py:37` constant;
     narrow Phase F grep scope to exclude `cloud_worker.py`.
  2. **Phase D plural `launch_sessions` threading** (GAP,
     mcp-integration-expert) — adapter plural method gains `worker_type`
     and `env` kwargs; threads into per-iteration `launch_session()`.
  3. **BifrostHealth sub-model** (NIT, mcp-integration-expert) — name
     the sub-model class explicitly; mount with `default_factory=`,
     not `BifrostHealth | None`.
  Plus four NIT-level corrections to the plan body that did not require
  spec amendment (see the v1.1 amendment applied paragraph at the top
  of this file).

- **v1.0 (2026-10-15)** — initial plan off spec v1.3.
