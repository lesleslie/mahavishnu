---
status: draft
role: canonical
kind: spec
date: 2026-10-15
last_reviewed: 2026-10-15
topic: bifrost-gateway-wiring
revision: v1.3
owner: platform-team
scope: mahavishnu LLM routing through Bifrost gateway + AI-CLI (Claude Code, Qwen) base URL opt-in
related: docs/decisions/wire-up-contract.md; docs/decisions/mcp-backend-wiring-discipline.md; feedback-no-backwards-compat-pre-1.0.md; feedback-cli-flag-consumer-wiring.md; docs/specs/2026-09-27-shared-bodai-substrate-design.md; settings/models.yaml; config/bifrost/config.template.json; mahavishnu/llm_gateway/
title: "Bifrost Gateway Wiring - Design v1.3"
---

# Bifrost Gateway Wiring - Design v1.3

> **v1.3 amendment (2026-10-15)**: Final-pass review by `mahavishnu-specialist` + `general-purpose` lenses surfaced 17 findings; 2 BLOCKERs converged (both lenses caught them). **Convergent blockers fixed**: (1) `_ALLOWED_LABEL_KEYS` allowlist fabrication — the citation was invented; v1.2 retconned. Phase A/E simply register counters directly against `prometheus_client` (no allowlist gate exists or is needed). (2) Phase D wiring chain structurally unreachable — `TmuxTerminalAdapter.launch_session` hardcodes `worker_type="terminal-claude"`; the chain `TerminalManager.launch_sessions()` → `TmuxTerminalAdapter.launch_session()` → `contract/tmux_adapter.create_session()` doesn't exist. Phase D now extends `TmuxTerminalAdapter.launch_session(worker_type, env)`, threads `env` through `DurableWorkerManager.spawn(...)` and into `contract/tmux_adapter.create_session(env)`, and uses **`tmux set-environment -t <session> KEY VAL`** per env entry (not `tmux new-session -e`, which doesn't propagate to spawned panes). **Unique BLOCKER fixed**: `PROVIDER_PROBES` sketch in v1.2 was unrunnable (module-level dict literal evaluated at import time before `settings` is bound); replaced with a `resolve_probe_endpoint(provider, settings)` helper called at probe time. **Factory signature** fixed: `_create_openai_model(self, model_id: str)` cannot take a second `settings` parameter — the four factory methods share a single signature dispatched via `getattr(self, factory_name)(model_id)`. Phase B adds `self._settings: MahavishnuSettings | None = None` to `LLMProviderFactory.__init__`; factory methods read `self._settings.bifrost`. **`entities_count` semantics** corrected: `HealthFeedState` expects number-of-records, not binary-reachable; Bifrost is a single upstream dependency, not a feed-of-things. Phase E drops the `HealthFeedState` integration; Bifrost surfaces under `/health.bifrost.config` (config block) + `/health.bifrost.reachable` (boolean). **Citation refinements**: `Literal` precedent should cite `ChangepointConfig.detector` (`config.py:622`) specifically (the mixed convention in `config.py` includes both `StrEnum` and `Literal`); sibling-precedent list reframed as "representative" not "verified canonical set"; `models.yaml` is loaded outside `MahavishnuSettings` envelope (via `FallbackChain`/`model_routing`) — its `bifrost:` block was structurally misplaced from day one; example log line in §5.7 disambiguated into Bifrost-side (`BifrostGatewayRequest.without_prompt()` shape) vs Mahavishnu-side (caller-side metrics); Acceptance criterion 8 references the plan file's Integration Contract blocks, not commit messages; Phase F grep scope tightened to read-only files (env-injection runtime paths excluded).
>
> **v1.2 amendment (2026-10-15, superseded)**: 4-lens review surfaced 37 findings. Convergent blockers fixed: CloudWorker scope re-anchored to surviving LLM surface; LlamaIndex adapter dropped (Ollama-only); Phase D env-injection site rewired; observability discipline added (4 mandatory feed fields, alerting backend, CLI subcommand, Node buffering mitigation); silent-failure paths closed (MINIMAX_BASE_URL precedence, Qwen env-var verification gate, host-vs-worker scope clarification); `BifrostConfig` gains `model_config = ConfigDict(extra="forbid")` and `Field(default_factory=...)` mount; `BifrostCacheMode` StrEnum replaced with `Literal`; per-Phase Integration Contracts split from §5.9.
>
> **v1.1 amendment (2026-10-15, superseded)**: Extends the AI-CLI worker opt-in scope to also cover `terminal-qwen`.

> **Why this spec exists**: The Bifrost LLM gateway runs at `:8471` and is healthy, but zero mahavishnu LLM traffic reaches it. The existing `mahavishnu/llm_gateway/` package implements the gateway envelope helpers (CCR-compatible route headers, cache scoping, prompt hashing), but has zero production consumers — `tests/unit/test_llm_gateway_*.py` import it and nothing else. `settings/models.yaml` exposes a `bifrost:` block at line 103-107 with `enabled: false` and `activate_env: "BIFROST_BASE_URL"`, but the env var is unread. This is the textbook `feedback-cli-flag-consumer-wiring.md` / `docs-audit-documented-not-wired.md` failure: the helper, the launcher, the config block, and the gateway itself are all wired except the consumer code that would actually route through them.

## 1. Outcome

After this design ships:

- **`BifrostConfig` settings class** mounted on `MahavishnuSettings` as the `bifrost:` sibling. `model_config = ConfigDict(extra="forbid")` per crackerjack hard-limit. `Field(default_factory=..., description="...")` mount per sibling precedent. Fields cover base URL, caller identity, cache mode (Literal), anthropic base URL, route-claude-code opt-in, timeout, and per-environment overrides.
- **mahavishnu LLM-calling surface routes through Bifrost when enabled.** Specifically the Agno adapter (`mahavishnu/engines/agno_adapter_impl.py`) — both `_create_openai_model` and `_create_anthropic_model` paths (with `self._settings.bifrost` plumbed via `LLMProviderFactory.__init__`), plus `mahavishnu/workers/capabilities/_probes.py:PROVIDER_PROBES["minimax"]` (via a `resolve_probe_endpoint(provider, settings)` helper called at probe time). **CloudWorker is out of scope** — `docs/feature-tracking/2026-09-25-cloud-worker-decision.md:46` records zero production or test imports outside the file itself; `WorkerManager._create_isolated_worker` is shepherd-only after Plan v3 Phase 4.5b. The LlamaIndex adapter (`mahavishnu/engines/llamaindex_adapter_impl.py`) is Ollama-only (no OpenAI or Anthropic SDK) and out of scope. When `bifrost.enabled: true`, the cloud tier hits `http://127.0.0.1:8471/v1/chat/completions` (OpenAI) or `http://127.0.0.1:8471/anthropic/v1/messages` (Anthropic) with the `BifrostGatewayRequest` envelope; the local fallback tiers (`llama_server`, `ollama`) stay direct.
- **`mahavishnu/llm_gateway/` package becomes the implementation surface.** `build_gateway_envelope()` is the single entry point for constructing base URL + path + route headers + cache headers. Agno + provider-probe consumers import it; nothing builds Bifrost headers ad hoc.
- **Claude Code Anthropic base URL stays direct-to-MiniMax by default** (`https://api.minimax.io/anthropic` via the `minimax-coding-plan` MCP server). A new field `bifrost.route_claude_code: bool` (default `false`) lets operators opt in to env-injecting `ANTHROPIC_BASE_URL=http://127.0.0.1:8471/anthropic` into Mahavishnu-spawned `terminal-claude` workers. **Scope clarification**: this affects Mahavishnu-spawned `terminal-claude` worker subprocesses only; the *host* Claude Code session's MCP transport (`~/.mcp.json:minimax-coding-plan-mcp`, `MINIMAX_API_HOST=https://api.minimax.io`) is independent and out of scope (tracked as a follow-up).
- **Qwen CLI base URL stays direct by default.** `bifrost.route_qwen_code: bool` (default `false`) opts in to env-injecting the variable named by `bifrost.qwen_env_var` (default `OPENAI_BASE_URL` — OpenAI-compatible convention; verified in Phase D) pointing at `gateway_api_base(OPENAI, bifrost.base_url)` (= `http://127.0.0.1:8471/v1`) into `terminal-qwen` workers via `tmux set-environment`. Phase D ships with `route_qwen_code: false` until the env-var name is verified end-to-end (silent-failure guard); the field is a config-tunable for forward-compat.
- **`settings/models.yaml` `bifrost:` block deleted** — `models.yaml` is loaded outside `MahavishnuSettings` envelope (via `FallbackChain`/`model_routing`); the `bifrost:` block was structurally misplaced from day one and is replaced by `settings/mahavishnu.yaml` `bifrost:` block. `BIFROST_BASE_URL` env var deleted — replaced by `MAHAVISHNU_BIFROST__BASE_URL` pydantic-settings env-prefix override per `feedback-no-backwards-compat-pre-1.0.md`.
- **`local.yaml` opt-in**: `bifrost: { enabled: true, route_claude_code: false, route_qwen_code: false }`.
- **Per-Phase Integration Contracts** (one block per Phase A-F) per `docs/decisions/wire-up-contract.md`.
- **Observability discipline per `mcp-backend-wiring-discipline.md`**: counters/histograms registered directly with `prometheus_client` against the per-server `CollectorRegistry` (no allowlist gate exists or is needed); Bifrost surfaces under `/health.bifrost.config` (config block) and `/health.bifrost.reachable` (boolean — not a `HealthFeedState` because Bifrost is a single upstream dependency, not a feed-of-things); alerting backend (`config/prometheus/bifrost_alerts.yml`); CLI subcommand `mahavishnu metrics bifrost` as Phase E sub-deliverable.
- **E2E test asserting `caller_id` appears in Bifrost log after worker dispatch** — JSON-form grep `'"caller_id":"mahavishnu"'` with 15-second timeout to absorb Node stdout buffering flake, per the project's `docs/decisions/mcp-backend-wiring-discipline.md §3`.

**Proof it worked**:
- `grep -rn "minimax\.io/v1" mahavishnu/engines mahavishnu/workers/capabilities mahavishnu/workers/cloud_worker.py mahavishnu/llm_gateway` returns zero hits outside `settings/models.yaml` (the canonical reference) and `mahavishnu/llm_gateway/` (documentation-only). Env-injection runtime paths in `mahavishnu/workers/contract/tmux_adapter.py` and `mahavishnu/terminal/adapters/tmux.py` are explicitly out of scope for this grep (they receive bifrost-aware URLs at runtime, not source literals). The four in-tree runtime hits are replaced as part of Phase F: `mahavishnu/workers/cloud_worker.py:37` (constant), `mahavishnu/engines/agno_adapter_impl.py:259` (factory default-fallback), `mahavishnu/engines/agno_adapter_impl.py:244` (docstring), `mahavishnu/workers/capabilities/_probes.py:128` (probe URL — replaced with bifrost-aware URL via `resolve_probe_endpoint`).
- `grep -rn "from mahavishnu.llm_gateway" mahavishnu/` returns hits in `engines/agno_adapter_impl.py`, `workers/capabilities/_probes.py`, plus tests.
- `tail -F ~/.local/state/mcp/logs/bifrost.log | grep '"caller_id":"mahavishnu"'` shows entries within 15 seconds of any `mcp__mahavishnu__pool_route_execute` invocation that hits the cloud tier (Node stdout block-buffering absorbed by the longer timeout).
- `curl -s http://localhost:8680/health | jq .bifrost.config` returns the config block; `curl -s http://localhost:8680/health | jq .bifrost.reachable` returns a boolean.
- `mahavishnu metrics bifrost --source auto --output table` returns non-zero counters after one dispatch against the cloud tier.
- `pytest tests/integration/test_bifrost_routing_e2e.py::test_agno_dispatch_emits_caller_id` passes.

## 2. Goals

1. **First-class settings, not env-var hack.** Mount on `MahavishnuSettings` per the `pi_pool:`, `worktree_storage:`, `goal_teams:`, `changepoint:` sibling pattern (these four are a representative subset of the ~15 sibling mounts at `mahavishnu/core/config.py:2961+`; the rest follow the same `Field(default_factory=..., description="...")` precedent). Pydantic-settings env-prefix override (`MAHAVISHNU_BIFROST__*`, lowercase per pydantic-settings default) for emergency override; the source of truth is the settings block. Apply `feedback-cli-flag-consumer-wiring.md`: every instantiation site must be grepped.
2. **Single source of truth for gateway envelope construction.** `mahavishnu/llm_gateway.build_gateway_envelope()` is the only entry point. No ad-hoc header construction in workers or adapters — that way the `caller_id`, `cache_scope_key`, and route header construction cannot drift between consumers.
3. **mahavishnu LLM callers always go through Bifrost when enabled, fail loud when not.** No "best-effort" fallback to direct MiniMax when Bifrost is unreachable — the LLM call fails and the operator sees it. Per `feedback-bodai-push-is-user-controlled.md` and the project's general posture: don't silently bypass the user-configured path.
4. **Local tiers stay direct.** `llama_server` (`:8081`) and `ollama` (`:11434`) are local-only; Bifrost is not in their chain. Routing them through Bifrost would add latency to localhost calls and create a single point of failure for no benefit.
5. **AI-CLI opt-in is a per-vendor flag set.** `bifrost.route_claude_code: bool` controls env injection into `terminal-claude` (sets `ANTHROPIC_BASE_URL`); `bifrost.route_qwen_code: bool` controls env injection into `terminal-qwen` (sets `bifrost.qwen_env_var`, default `OPENAI_BASE_URL`). Both default `false`. When an operator opts in, env injection happens at worker spawn time via `tmux set-environment -t <session> KEY VAL` per entry. Each flag is independent. **Ship gate**: `route_qwen_code` ships `false` in v1.3 until Phase D verification confirms the Qwen CLI's actual env-var name.
6. **Per-request observability.** Each Bifrost dispatch produces a log entry from Bifrost's own log emission (per the `BifrostGatewayRequest.without_prompt()` serialization in `mahavishnu/llm_gateway/contract.py:202-217`) AND a Mahavishnu-side log line (caller-side metrics: outcome, duration_ms). Counters/histograms are registered directly with `prometheus_client` against the per-server `CollectorRegistry` in `mahavishnu/observability/prometheus_metrics.py`. Bifrost surfaces under `/health.bifrost.config` (config block) + `/health.bifrost.reachable` (boolean). Rollback signal: error rate on a single provider climbs above 50% over 60s; alert lives in `config/prometheus/bifrost_alerts.yml`.
7. **Independent rollback per scope.** Setting `bifrost.enabled: false` reverts mahavishnu LLM callers; setting `bifrost.route_claude_code: false` reverts Claude Code only; setting `bifrost.route_qwen_code: false` reverts Qwen only. Each can be set independently.
8. **No backwards compatibility shims.** Pre-1.0 codebase per `feedback-no-backwards-compat-pre-1.0.md`: replace, don't extend. `BIFROST_BASE_URL` env var stops working on merge. `settings/models.yaml:bifrost` block deleted on merge.
9. **Silent-failure paths closed** (per the silent-failure-hunter pattern). `MINIMAX_BASE_URL` precedence is explicit and tested. Qwen env-var verification gate precedes `route_qwen_code` shipping enabled. Host-vs-worker scope is clarified so operators don't assume the host Claude Code session routes through Bifrost.

## 3. Non-Goals

- **Wiring CloudWorker.** Per `docs/feature-tracking/2026-09-25-cloud-worker-decision.md:46`, CloudWorker has zero production callers after Plan v3 Phase 4.5b; the resurrection path is a separate piece of work. This spec is scoped to the surviving LLM-calling surface.
- **Routing llama-server or ollama through Bifrost.** Local providers don't need gateway caching or routing rules.
- **Cross-repo Bifrost adoption.** This spec is mahavishnu-only. Akosha, Session-Buddy, Crackerjack, and the `minimax-coding-plan-mcp` server are out of scope; if they need Bifrost, they get their own specs.
- **Wiring the LlamaIndex adapter.** `mahavishnu/engines/llamaindex_adapter_impl.py:39-40, 384-386` imports only `OllamaEmbedding`/`Ollama` from `llama_index.llms.ollama` — no OpenAI or Anthropic SDK client exists to wire. The local-fallback path stays direct.
- **Bifrost semantic cache tuning.** The `recommended_cache_mode()` helper in `mahavishnu/llm_gateway/client.py:74-96` already returns the correct policy (`OFF` for image routes; `SEMANTIC`/`DIRECT` per route class). The spec consumes it; it does not redesign it.
- **Bifrost provider additions.** The `config/bifrost/config.template.json` provider set (`minimax-openai`, `anthropic`, `openai`) is the operator's concern. The spec adds the wiring; it does not add providers.
- **Custom cache TTLs per task.** The gateway envelope defaults (`cache_ttl_seconds=300`, `cache_threshold=None`, `cache_mode=off`) are correct for the current deployment. Operators can override via settings later.
- **Bifrost HTTP/WebSocket transport.** Bifrost is HTTP-only; we mirror that.
- **Rewiring the host Claude Code MCP transport.** `~/.mcp.json:minimax-coding-plan-mcp`'s `MINIMAX_API_HOST` is independent of this spec's worker-spawn env injection. Tracked as a follow-up.

## 4. Current Findings

### 4.1 Bifrost gateway runtime state (this session, 2026-10-15)

```
$ curl -sS http://localhost:8471/health
{"components":{"db_pings":"ok"},"status":"ok"}
```

Log `/Users/les/.local/state/mcp/logs/bifrost.log` (~24 MB, growing). Ready file `/Users/les/.local/state/mcp/ready/bifrost.ready` is 0 bytes (launcher's readiness probe never wrote it — separate issue tracked in followups). `caller_id` field appears 0 times in the log → no `BifrostGatewayRequest` envelope has ever been sent to this gateway.

### 4.2 Zero production consumers of `mahavishnu/llm_gateway/`

```
$ grep -rn "from mahavishnu.llm_gateway\|import mahavishnu.llm_gateway" \
        --include="*.py" | grep -v test_llm_gateway
(no output)
```

Only `tests/unit/test_llm_gateway_client.py` and `tests/unit/test_llm_gateway_contract.py` import the package.

### 4.3 Surviving mahavishnu LLM-calling surface (post-Plan v3 Phase 4.5b)

`grep -rn "OpenAI\|Anthropic\|anthropic\.com\|api\.minimax\.io\|base_url\|api_key" /Users/les/Projects/mahavishnu/mahavishnu/`:

- `mahavishnu/engines/agno_adapter_impl.py:177-216` — `_create_openai_model(self, model_id: str) -> Any` constructs `OpenAIChat(id=…, api_key=…, temperature=…, max_tokens=…)`; `_create_anthropic_model(self, model_id: str) -> Any` constructs `Claude(id=…, api_key=…, temperature=…, max_tokens=…)`. **No `base_url=` or `default_headers=` parameter is currently passed** (mcp-common `ProviderConfig` lacks `extra_headers`; Phase B coordinates an mcp-common PR or scopes to `base_url`-only rewriting + caller_id logging). All four factory methods share the `(self, model_id: str)` signature; dispatch via `getattr(self, factory_name)(model_id)`. Adding a second `settings` parameter would change the contract for all four factories.
- `mahavishnu/engines/agno_adapter_impl.py:240-262` — `_create_minimax_model` constructs an OpenAI chat with `base_url=self.config.base_url or "https://api.minimax.io/v1"`. This is the **one** place in the Agno adapter that already passes `base_url=`.
- `mahavishnu/workers/capabilities/_probes.py:127-132` — `PROVIDER_PROBES["minimax"] = ("MINIMAX_API_KEY", "https://api.minimax.io/v1/models")`. **Module-level dict literal** evaluated before `settings` is bound; cannot reference `settings.bifrost` at import time.
- `mahavishnu/workers/cloud_worker.py` — **orphaned**; `docs/feature-tracking/2026-09-25-cloud-worker-decision.md:46` records "Zero production or test imports of CloudWorker outside the file itself and its package export." `WorkerManager._create_isolated_worker` (`mahavishnu/workers/manager.py:425-490`) is shepherd-only.

No `BIFROST_BASE_URL` reads. No Bifrost provider. No `build_gateway_envelope()` call. The chain never reaches Bifrost.

### 4.4 Settings block exists but is dead config

`settings/models.yaml:103-107`:

```yaml
# Bifrost gateway (activated via env vars only)
bifrost:
  enabled: false
  base_url: "http://127.0.0.1:8471"
  activate_env: "BIFROST_BASE_URL"
```

`enabled: false`. `BIFROST_BASE_URL` is unread in production code (`grep -rn BIFROST_BASE_URL mahavishnu/ workers/ core/ pools/` returns zero hits).

**Note**: `settings/models.yaml` is loaded outside the `MahavishnuSettings` envelope (via `mahavishnu/core/model_routing.py` and `FallbackChain`). The `bifrost:` block was structurally misplaced from day one; bifrost settings belong on `MahavishnuSettings`, not on this file. Phase F deletes the misplaced block.

### 4.5 Claude Code Anthropic base URL — direct-to-MiniMax today

`~/.mcp.json:42-55`:

```json
"minimax-coding-plan": {
  "command": "uvx",
  "args": ["--from", "minimax-coding-plan-mcp", ...],
  "env": { "MINIMAX_API_HOST": "https://api.minimax.io" }
}
```

The `minimax-coding-plan-mcp` server is the *host* Claude Code Anthropic transport; per CLAUDE.md, Claude Code calls `https://api.minimax.io/anthropic`. There is no `ANTHROPIC_BASE_URL` env injection for the Mahavishnu-spawned `terminal-claude` worker today. **These are independent surfaces** — `route_claude_code: true` affects only Mahavishnu-spawned workers, not the host session.

### 4.6 Settings mount pattern (representative precedent)

`mahavishnu/core/config.py:715-718` (`PiPoolSettings`):

```python
class PiPoolSettings(BaseModel):
    """Pi pool-specific settings (Bifrost is a similar shape)."""
    # Mounted as the top-level ``pi_pool`` sibling on :class:`MahavishnuSettings`.
```

**Representative sibling blocks** at `mahavishnu/core/config.py:2961+` (~15 total; these are illustrative):

- `pi_pool` — `PiPoolSettings` at line 715; mounted at line 2961
- `changepoint` — `ChangepointConfig` at line 595; mounted at line 2972
- `otel_storage` — mounted at line 2978
- `worktree_storage` — mounted at line 2991
- `goal_teams` — `GoalTeamsSettings`; mounted at line 3132

All use `Field(default_factory=<Type>, description="...")` per the precedent.

`MahavishnuSettings` inheritance per `mahavishnu/core/config.py:2763`:

```python
class MahavishnuSettings(BaseSettings):  # NOT OneiricBaseSettings
    """mahavishnu application settings (extending MCPServerSettings)."""
```

The docstring says "extending MCPServerSettings" (from `mcp-common`); `OneiricBaseSettings` does not appear in this file.

## 5. Design

### 5.1 Settings schema

New class `BifrostConfig` in `mahavishnu/core/config.py`, mounted as `bifrost: BifrostConfig = Field(default_factory=BifrostConfig, description="Bifrost LLM gateway wiring for the surviving mahavishnu LLM-calling surface (Agno adapter, PROVIDER_PROBES, AI-CLI worker opt-in).")` on `MahavishnuSettings`.

```python
from typing import Literal

class BifrostConfig(BaseModel):
    """First-class Bifrost gateway settings.

    When ``enabled`` is True, the surviving mahavishnu LLM surface (Agno adapter,
    PROVIDER_PROBES) routes the cloud tier through the gateway at
    ``base_url``. Local fallback tiers (``llama_server``, ``ollama``) stay
    direct.

    AI-CLI worker opt-in flags control env injection at spawn time:

    - ``route_claude_code``: when True, the Mahavishnu-spawned
      ``terminal-claude`` worker inherits
      ``ANTHROPIC_BASE_URL=<anthropic_base_url>`` so the Claude Code CLI
      itself routes through Bifrost's Anthropic-compatible endpoint.

    - ``route_qwen_code``: when True, the ``terminal-qwen`` worker inherits
      the env var named by ``qwen_env_var`` (default ``OPENAI_BASE_URL``
      — Qwen's OpenAI-compatible transport; subject to Phase D
      verification) pointing at ``<base_url>`` so Qwen CLI routes through
      Bifrost's OpenAI-compatible provider.

    Each flag is independent; operators opt in per vendor.
    """

    model_config = ConfigDict(extra="forbid")  # crackerjack hard-limit

    enabled: bool = False
    base_url: str = "http://127.0.0.1:8471"
    anthropic_base_url: str = "http://127.0.0.1:8471/anthropic"
    caller_id: str = "mahavishnu"
    cache_mode: Literal["off", "direct", "semantic"] = "off"  # mirrors ChangepointConfig.detector (config.py:622) Literal[...] precedent
    cache_ttl_seconds: int = 300
    request_timeout_seconds: int = 30
    # AI-CLI worker opt-in flags (default false; each independent).
    route_claude_code: bool = False
    route_qwen_code: bool = False
    # Env var name that the Qwen CLI reads for a custom OpenAI-compatible
    # base URL. Verified in Phase D; default is the OpenAI-compatible
    # convention. Override here when the actual vendor CLI uses a
    # different name (e.g. ``QWEN_BASE_URL`` or ``DASHSCOPE_API_BASE``).
    qwen_env_var: str = "OPENAI_BASE_URL"
    # Optional bearer token for the gateway. Empty = no auth header.
    # Sourced from BIFROST_API_KEY env var if set; not stored in settings.
    auth_env: str = "BIFROST_API_KEY"
```

Mount on `MahavishnuSettings` (`mahavishnu/core/config.py:2961+` area, per the `pi_pool:` precedent):

```python
class MahavishnuSettings(BaseSettings):
    # ... existing fields ...
    bifrost: BifrostConfig = Field(
        default_factory=BifrostConfig,
        description="Bifrost LLM gateway wiring (Phase 5.1) and AI-CLI worker opt-in (Phase 5.5).",
    )
```

Pydantic-settings env-prefix: `MAHAVISHNU_BIFROST__<FIELD>` (nested delimiter `__`, lowercase per pydantic-settings default — `MAHAVISHNU_BIFROST__enabled=true` overrides `local.yaml:bifrost.enabled`). Example: `MAHAVISHNU_BIFROST__enabled=true` in `~/.zshenv`.

### 5.2 `mahavishnu/llm_gateway/` consumption

`mahavishnu/llm_gateway/build_gateway_envelope()` already returns the full envelope (base URL + path + headers). Consumers call it directly — no extra wrapper needed:

```python
# Consumer (e.g., engines/agno_adapter_impl.py)
from mahavishnu.llm_gateway import build_gateway_envelope, ProtocolFamily, CacheMode

envelope = build_gateway_envelope(
    caller_id=settings.bifrost.caller_id,
    protocol_family=ProtocolFamily.OPENAI,  # or ANTHROPIC
    model="MiniMax-M3",
    prompt=prompt,
    task_label=task_label,
    base_url=settings.bifrost.base_url,
    cache_mode=CacheMode(settings.bifrost.cache_mode),
    cache_ttl_seconds=settings.bifrost.cache_ttl_seconds,
)
# Pass envelope.api_base and envelope.request_headers into the SDK client.
```

`bifrost.enabled: False` is a no-op: callers never construct the envelope. `bifrost.enabled: True` rewrites the cloud provider's `base_url` and `headers` from the envelope.

### 5.3 Agno adapter integration (mahavishnu-LLM scope, the primary wiring surface)

`mahavishnu/engines/agno_adapter_impl.py` changes — three sites, one pattern. **All four factory methods share a `(self, model_id: str)` signature**; do **not** change the signature. Settings plumb via a new `LLMProviderFactory._settings: MahavishnuSettings | None` attribute populated in `__init__`.

**Site 1: `_create_openai_model(self, model_id: str) -> Any` (lines 177-196 today)**

```python
def _create_openai_model(self, model_id: str) -> Any:
    kwargs = dict(id=model_id, api_key=self.config.api_key, temperature=..., max_tokens=...)
    if self._settings is not None and self._settings.bifrost.enabled:
        envelope = build_gateway_envelope(
            caller_id=self._settings.bifrost.caller_id,
            protocol_family=ProtocolFamily.OPENAI,
            model=model_id,
            prompt="",  # not available at construction; env can supply
            task_label=None,
            base_url=self._settings.bifrost.base_url,
            cache_mode=CacheMode(self._settings.bifrost.cache_mode),
            cache_ttl_seconds=self._settings.bifrost.cache_ttl_seconds,
        )
        # Agno's OpenAIChat accepts base_url via constructor in current pin.
        kwargs["base_url"] = envelope.api_base  # → "http://127.0.0.1:8471/v1"
        # kwargs["default_headers"] = envelope.request_headers  # Phase B dependency (see below)
    return OpenAIChat(**kwargs)
```

**Site 2: `_create_anthropic_model(self, model_id: str) -> Any` (lines 198-216 today)**

Same pattern with `ProtocolFamily.ANTHROPIC` and `envelope.api_base` resolves to `http://127.0.0.1:8471/anthropic`. `kwargs["base_url"] = envelope.api_base`.

**Site 3: `_create_minimax_model(self, model_id: str) -> Any` (lines 240-262 today)**

The one existing place that passes `base_url=`. Rewrite the default fallback so it routes through Bifrost when enabled:

```python
def _create_minimax_model(self, model_id: str) -> Any:
    if self._settings is not None and self._settings.bifrost.enabled:
        base_url = gateway_api_base(ProtocolFamily.OPENAI, base_url=self._settings.bifrost.base_url)
    else:
        base_url = self.config.base_url or "https://api.minimax.io/v1"
    return OpenAIChat(id=model_id, api_key=self.config.api_key, base_url=base_url, ...)
```

**`LLMProviderFactory.__init__` change** (`mahavishnu/engines/agno_adapter_impl.py:115`):

```python
class LLMProviderFactory:
    def __init__(self, config: Any, settings: MahavishnuSettings | None = None) -> None:
        # Existing population of self.config from AgnoLLMConfig fields stays.
        self._settings = settings
        # ... existing init code ...
```

`AgnoAdapter.__init__` (which already has the full settings access via `config: Any = settings.agno`) passes the settings object down. The four factory methods read `self._settings.bifrost` when present; existing tests that construct `LLMProviderFactory(config)` without settings continue to work (default `None`).

**mcp-common dependency** (the gate on envelope header injection): `mcp-common/mcp_common/llm/config.py:16-33` (`ProviderConfig`, `extra="forbid"`) has no `extra_headers` field; `mcp-common/mcp_common/llm/provider.py:42-58` (`OpenAICompatibleProvider.__init__`) only sets `default_headers={"Authorization": ""}` for local providers; the cloud branch doesn't accept header injection. Phase B includes either an mcp-common PR adding `ProviderConfig.extra_headers` + `OpenAICompatibleProvider.__init__(..., default_headers=...)` OR a scoped Phase B that limits Bifrost to `base_url`-only rewriting + caller_id logging in the adapter (sufficient for the `caller_id` log requirement per §1 proof). **The choice is Phase B's decision; this spec requires the `caller_id` log assertion to pass either way.**

**`WorkerResult.metadata` clarification**: `mahavishnu/workers/base.py:37` defines `metadata: dict[str, Any] = field(default_factory=dict)` — a free-form dict, not a typed field. There is **no contract** that any worker populates `metadata["provider"]` to mean anything specific. CloudWorker's `metadata["provider"] = result.get("provider", "unknown")` was bespoke to its `FallbackChain` integration; the Agno adapter (which is what v1.3 wires) populates `WorkerResult` directly via its own execution, not via FallbackChain. The spec's v1/v1.1 `metadata.provider == "bifrost"` claim is **withdrawn**. Operators count Bifrost-routed traffic via `mahavishnu_bifrost_dispatch_total{outcome,provider,route_class}` (counter). To make `metadata.provider` contract-meaningful requires a typed `WorkerResult.provider` field in a follow-up spec.

**Site 4: `PROVIDER_PROBES["minimax"]` rewrite** (`mahavishnu/workers/capabilities/_probes.py:127-132`):

`PROVIDER_PROBES` is a module-level dict literal evaluated at import time before `settings` is bound. Phase B does **not** mutate the module-level dict literal. Instead, add a helper:

```python
def resolve_probe_endpoint(provider: str, settings: MahavishnuSettings) -> str:
    """Return the bifrost-aware probe endpoint when bifrost is enabled, else the literal."""
    if settings.bifrost.enabled and provider == "minimax":
        return settings.bifrost.base_url.rstrip("/") + "/v1/models"
    return PROVIDER_PROBES[provider][1]  # literal from the dict
```

Update `_probe_provider_request` (the consumer at `mahavishnu/workers/capabilities/_probes.py:_probe_provider_request`) to call `resolve_probe_endpoint(provider, settings)` instead of reading `PROVIDER_PROBES[provider][1]` directly. `PROVIDER_PROBES` keeps its current shape so the probe dictionary stays stable for tests.

### 5.4 Removed: LlamaIndex adapter integration

`mahavishnu/engines/llamaindex_adapter_impl.py:39-40, 384-386` imports only `OllamaEmbedding`/`Ollama` from `llama_index.llms.ollama`. There is no OpenAI or Anthropic SDK client anywhere in the file. The spec's v1/v1.1 Phase C inclusion was a structural error — Phase C is dropped entirely. LlamaIndex adapter stays as out of scope (it routes to local Ollama; `§3 Non-Goals` covers the rationale).

### 5.5 AI-CLI worker integration (mahavishnu-worker scope, opt-in, per-vendor)

When `bifrost.enabled: True` AND the corresponding per-vendor flag is also True, the worker inherits a base-URL env var at spawn time. Two flags, two workers, two env vars:

| Flag | Worker type | Env var | Value |
|---|---|---|---|
| `bifrost.route_claude_code` | `terminal-claude` | `ANTHROPIC_BASE_URL` | `bifrost.anthropic_base_url` |
| `bifrost.route_qwen_code` | `terminal-qwen` | `bifrost.qwen_env_var` (default `OPENAI_BASE_URL`) | `gateway_api_base(ProtocolFamily.OPENAI, base_url=bifrost.base_url)` (→ `http://127.0.0.1:8471/v1`) |

**Host-vs-worker scope**: this affects **mahavishnu-spawned** `terminal-claude` and `terminal-qwen` worker subprocesses only. The host Claude Code session's MCP transport (`~/.mcp.json:42-55`, `minimax-coding-plan-mcp`, `MINIMAX_API_HOST=https://api.minimax.io`) is independent. Operators who flip `route_claude_code: true` and expect the host session to route through Bifrost will be disappointed — that's a separate spec.

**Env-injection wiring site** (v1.3 corrected per mahavishnu-specialist + general-purpose lenses):

The v1.2 spec claimed a chain `TerminalManager.launch_sessions()` → `TmuxTerminalAdapter.launch_session()` → `contract/tmux_adapter.create_session()`. **That chain does not exist** — `TmuxTerminalAdapter.launch_session()` (`mahavishnu/terminal/adapters/tmux.py:22`) hardcodes `worker_type="terminal-claude"` at line 31 and delegates to `DurableWorkerManager.spawn()`, a separate path from `contract/tmux_adapter.create_session()`.

Phase D rewires:

1. `TmuxTerminalAdapter.launch_session` gains `worker_type: str = "terminal-claude"` and `env: dict[str, str] | None = None` kwargs.
2. `TerminalManager.launch_sessions()` (`mahavishnu/terminal/manager.py:240`) gains `worker_type: str = "terminal-claude"` and threads it into the adapter call.
3. `DurableWorkerManager.spawn()` gains `env: dict[str, str] | None = None` and passes it through.
4. `contract/tmux_adapter.create_session()` (`mahavishnu/workers/contract/tmux_adapter.py:84-130`) gains `env: dict[str, str] | None = None` and emits `tmux set-environment -t <session> KEY VAL` per entry.

**Env propagation mechanism**: `tmux new-session -e KEY=VAL` does **not** propagate env vars to spawned panes (the env is set on the tmux server process, not the spawned command). Phase D uses **`tmux set-environment -t <session> KEY VAL`** after `create_session` succeeds — session-scoped env vars are inherited by new panes. The test asserts from inside the spawned pane:

```bash
# tmux send-keys to the worker's pane:
tmux send-keys -t <session> 'printenv ANTHROPIC_BASE_URL' Enter
# Capture the pane contents; expect: http://127.0.0.1:8471/anthropic
```

**Phase D sketch** (corrected from v1.2):

```python
# TerminalManager.launch_sessions() — extends with worker_type and env
async def launch_sessions(
    self,
    command: str,
    *,
    count: int = 1,
    columns: int = 120,
    rows: int = 40,
    worker_type: str = "terminal-claude",  # NEW: thread to adapter
) -> list[SessionInfo]:
    env = _resolve_worker_env(worker_type, self.settings.bifrost)  # NEW: build env
    return await self.adapter.launch_sessions(
        command=command, count=count, columns=columns, rows=rows,
        worker_type=worker_type, env=env,  # NEW: pass through
    )

def _resolve_worker_env(worker_type: str, bifrost: BifrostConfig) -> dict[str, str]:
    env: dict[str, str] = {}
    if not bifrost.enabled:
        return env
    if worker_type == "terminal-claude" and bifrost.route_claude_code:
        env["ANTHROPIC_BASE_URL"] = bifrost.anthropic_base_url
    elif worker_type == "terminal-qwen" and bifrost.route_qwen_code:
        env[bifrost.qwen_env_var] = gateway_api_base(ProtocolFamily.OPENAI, base_url=bifrost.base_url)
    return env
```

```python
# contract/tmux_adapter.py — create_session extends with env, emits set-environment
def create_session(*, socket, session, window_name, command, env: dict[str, str] | None = None) -> None:
    # ... existing tmux new-session -d call ...
    if env:
        for key, val in env.items():
            subprocess.run(["tmux", "-S", socket, "set-environment", "-t", session, key, val], check=True)
```

Defaults — both flags `false` — mean today's behavior is unchanged:

- Claude Code keeps calling `https://api.minimax.io/anthropic` via the `minimax-coding-plan` MCP server (host session).
- Mahavishnu-spawned `terminal-claude` keeps reading the default Claude Code endpoint (no `ANTHROPIC_BASE_URL` injected).
- Mahavishnu-spawned `terminal-qwen` keeps reading its default endpoint (no env-var injected).

When the operator flips a flag, the worker is spawned with the env var pointing at the corresponding Bifrost endpoint. Each flag is independent: flipping `route_claude_code` does not affect Qwen workers and vice versa.

**Worker registry line citations**: `mahavishnu/workers/registry.py:131` is `terminal-claude`; `mahavishnu/workers/registry.py:116` is `terminal-qwen` (corrected from the v1.1 wrong-citation `:131`).

**Phase D verification gate**: `route_qwen_code: false` ships in v1.3 even if the operator opts in via `local.yaml`. Phase D demonstrates the env var flows into the spawned worker via `tmux send-keys 'printenv OPENAI_BASE_URL' Enter` from inside the worker's tmux session, AND runs an actual Qwen CLI dispatch to confirm the `'"caller_id":"mahavishnu"'` line appears in `bifrost.log`. If the actual Qwen env var name is `QWEN_BASE_URL` or `DASHSCOPE_API_BASE` (not `OPENAI_BASE_URL`), the operator updates `bifrost.qwen_env_var` in `local.yaml` and re-runs; the code path is unchanged.

### 5.6 Migration

**Replace, no deprecation** per `feedback-no-backwards-compat-pre-1.0.md`:

| Old | New | Action |
|---|---|---|
| `settings/models.yaml:bifrost:` block | `settings/mahavishnu.yaml:bifrost:` block (plus `local.yaml` opt-in) | Delete `models.yaml` block in same PR. `models.yaml` is loaded outside the `MahavishnuSettings` envelope (via `FallbackChain`/`model_routing`); the `bifrost:` block was structurally misplaced from day one. |
| `BIFROST_BASE_URL` env var | `MAHAVISHNU_BIFROST__BASE_URL` env-prefix | Stop reading `BIFROST_BASE_URL` in same PR. |
| `MINIMAX_BASE_URL` env var (redirect to private LLM-compatible service) | Same — keep as an explicit redirect for direct mode. **Precedence**: when `bifrost.enabled: true`, `BifrostConfig.base_url` is the source of truth and `MINIMAX_BASE_URL` is read but ignored. Enforced in code via `if settings.bifrost.enabled: base_url = gateway_api_base(...)` (Agno `_create_minimax_model` §5.3) and tested by `test_minimax_base_url_ignored_when_bifrost_enabled`. | Document precedence in code; add unit test. |

### 5.7 Observability

**Per-request log emission** — TWO log lines, distinguishing Bifrost-side (Bifrost's own emission) from Mahavishnu-side (caller-side metrics):

**Bifrost-side** (Bifrost's own log emission, already wired via `BifrostGatewayRequest.without_prompt()` serialization at `mahavishnu/llm_gateway/contract.py:202-217`):

```json
{"caller_id":"mahavishnu","provider":"minimax-openai","model":"minimax-openai/MiniMax-M3",
 "task_label":"...","request_type":"...","trusted_wrapper":"true","route_class":"default",
 "prompt_hash":"...","cache_mode":"direct","cache_scope_key":"...","ts":"2026-10-15T..."}
```

**Mahavishnu-side** (new emission, emitted by `_bifrost_dispatch_heartbeat` wrapper after every Bifrost call):

```json
{"caller_id":"mahavishnu","provider":"minimax-openai","route_class":"default",
 "outcome":"success","duration_ms":432,"ts":"2026-10-15T..."}
```

The e2e test grep pattern (`'"caller_id":"mahavishnu"'`) applies to either shape; operators should know the Bifrost-side shape lives in `bifrost.log` and the Mahavishnu-side shape lives in `mahavishnu.log`.

**Metrics registered directly with `prometheus_client`** in `mahavishnu/observability/prometheus_metrics.py` against the existing per-server `CollectorRegistry` (per `_health_metrics_registry` pattern at line 51). **No `_ALLOWED_LABEL_KEYS` allowlist gate exists or is needed** — `prometheus_client` passes whatever labels the caller provides; the discipline is to keep the label set small and bounded and to document the label names so future emitters don't drift. The label set for Bifrost metrics is bounded to {`outcome`, `provider`, `route_class`, `reason`}; new labels require a Phase A-plus-one amendment:

- `mahavishnu_bifrost_dispatch_total{outcome,provider,route_class}` (counter)
- `mahavishnu_bifrost_dispatch_latency_seconds{provider,route_class}` (histogram)
- `mahavishnu_bifrost_dispatch_failures_total{provider,reason}` (counter)

**Health surface** — Bifrost is a single upstream dependency, not a feed-of-things; it does **not** register a `HealthFeedState` (which expects number-of-records semantics). Two sub-shapes:

- `/health.bifrost.config` — config block projection (`BifrostConfig.to_public_dict()`). Operators verify live config without exposing secrets.
- `/health.bifrost.reachable` — boolean from `_probe_bifrost_state()` (an `httpx.get(bifrost.base_url + "/health", timeout=2)` returning `200 OK`). The boolean is registered into the existing `mahavishnu_health_feed_status{feed="bifrost", status}` gauge in `mahavishnu/observability/prometheus_metrics.py:89` (the canonical per-feed-status metric).

**Alerting backend**: `config/prometheus/bifrost_alerts.yml` (sibling to `config/prometheus/health_aggregator_alerts.yml`, referenced from `mahavishnu/core/health_aggregator.py:36`). Phase E ships the rule:

```yaml
- alert: MahavishnuBifrostErrorRateHigh
  expr: |
    sum(rate(mahavishnu_bifrost_dispatch_failures_total[1m]))
      / sum(rate(mahavishnu_bifrost_dispatch_total[1m])) > 0.5
  for: 1m
  annotations:
    summary: "Bifrost dispatch error rate > 50% over 1m"
```

Alternative alert destinations: `mcp__mahavishnu__trigger_test_alert` (Akosha paging path) — Phase E picks one.

**Node stdout buffering mitigation**: `scripts/bifrost-gateway.py:120-126` opens `bifrost.log` with `open(..., "ab")` and `subprocess.Popen(..., stdout=stdout_log, stderr=stderr_log)`. Node stdout is block-buffered when piped. Phase E either (a) replaces the launcher with `stdbuf -oL -eL` line-buffering, or (b) calls `os.fsync(stdout_log.fileno())` after every dispatch path so the FD is flushed. The e2e test must absorb this: assertion window is **15 seconds, not 5**, per the project's existing precedent on CI-flaky tests.

**Grep pattern for operator assertions**: Bifrost's `LOG_STYLE=json` produces JSON lines, not key=value. `grep caller_id=mahavishnu` returns zero results on JSON output. The correct pattern: `grep '"caller_id":"mahavishnu"'`. The e2e test must assert against this pattern.

**`mahavishnu metrics bifrost` CLI subcommand** (Phase E sub-deliverable): follows the existing `mahavishnu metrics engines` shape (per `mahavishnu/metrics_cli.py`); reads from the per-server `CollectorRegistry` via `prometheus_metrics.get_health_metrics_registry()` and the `mahavishnu_bifrost_*` series. Flag set: `--source {auto,prom,otel}` (default `auto`), `--output {table,json}` (default `table`). New `--provider {minimax,anthropic,all}` filter scopes the table. Canonical invocation: `mahavishnu metrics bifrost --source auto --output table`.

## Per-Phase Integration Contracts (one block per Phase, per `wire-up-contract.md`)

### Integration Contract — Phase A (settings schema + observability scaffolding)

**Triggered from**: `mahavishnu/core/config.py:load_settings()` (Oneiric loader); `mahavishnu/observability/prometheus_metrics.py` registration calls (Phase A adds the three Bifrost series).

**Returns to / updates**: `MahavishnuSettings.bifrost` field populated; `mahavishnu/observability/prometheus_metrics.py` gains `mahavishnu_bifrost_*` series; `settings/mahavishnu.yaml` and `settings/local.yaml` gain `bifrost:` blocks.

**Demonstrable by**: `mahavishnu config validate` shows the schema; `MAHAVISHNU_BIFROST__enabled=true` overrides `local.yaml` (test `TestBifrostConfigSchema::test_env_overrides_local_yaml`); `extra="forbid"` rejects stray fields (test `test_extra_forbid_rejects_unknown_field`); mount uses `Field(default_factory=...)` (test `test_mount_uses_field_default_factory`).

**Rollback signal**: revert the config mount — no production behavior change (consumers don't exist in Phase A).

**Observability added**: `mahavishnu_bifrost_*` series registered in `prometheus_metrics.py`; zero counters until Phase B.

### Integration Contract — Phase B (mahavishnu LLM-calling surface integration)

**Triggered from**: `mcp__mahavishnu__trigger_workflow(adapter="agno", ...)` (Agno adapter instantiates `OpenAIChat` / `Claude`); `mcp__mahavishnu__pool_route_execute` followed by capability probe (PROVIDER_PROBES via `resolve_probe_endpoint`).

**Returns to / updates**: Agno adapter's three sites (`_create_openai_model`, `_create_anthropic_model`, `_create_minimax_model`) consult `self._settings.bifrost` (new `LLMProviderFactory._settings` attribute, populated in `AgnoAdapter.__init__`); `_probe_provider_request` calls `resolve_probe_endpoint(provider, settings)`; `MINIMAX_BASE_URL` precedence test enforces bifrost-wins-when-enabled.

**Demonstrable by**: with `bifrost.enabled: true` in `local.yaml`, an Agno workflow invocation produces `'"caller_id":"mahavishnu"'` in `bifrost.log` within 15 seconds (test `tests/integration/test_bifrost_routing_e2e.py::test_agno_dispatch_emits_caller_id`).

**Rollback signal**: `bifrost.enabled: false` reverts to direct-to-MiniMax; per-provider error rate > 50% over 60s triggers alert.

**Observability added**: `mahavishnu_bifrost_dispatch_total{outcome,provider,route_class}` increments; per-request INFO log emitted (Bifrost-side + Mahavishnu-side).

### Integration Contract — Phase C — merged with Phase B (no separate Phase).

### Integration Contract — Phase D (AI-CLI worker env-injection)

**Triggered from**: `mcp__mahavishnu__launch_worker(worker_type="terminal-claude"|"terminal-qwen", ...)` → `TerminalManager.launch_sessions(worker_type=..., command=...)` → `TmuxTerminalAdapter.launch_session(worker_type, env)` → `DurableWorkerManager.spawn(worker_type, env)` → `contract/tmux_adapter.create_session(env)` → `tmux set-environment -t <session> KEY VAL` per env entry.

**Returns to / updates**: `terminal-claude` subprocess inherits `ANTHROPIC_BASE_URL=http://127.0.0.1:8471/anthropic` when `route_claude_code: true`; `terminal-qwen` subprocess inherits `bifrost.qwen_env_var` (= `OPENAI_BASE_URL` by default) pointing at `gateway_api_base(OPENAI, bifrost.base_url)` (`http://127.0.0.1:8471/v1`) when `route_qwen_code: true`. Both via `tmux set-environment` (not `tmux new-session -e`).

**Demonstrable by**: with `route_claude_code: true` in `local.yaml`, launch a `terminal-claude` worker; `tmux send-keys -t <session> 'printenv ANTHROPIC_BASE_URL' Enter` returns `http://127.0.0.1:8471/anthropic` (test `tests/unit/test_terminal_worker_settings.py::test_claude_code_inherits_anthropic_base_url`). With `route_qwen_code: true` AND `qwen_env_var` set to the verified Qwen CLI env-var name, an actual Qwen CLI dispatch produces a `'"caller_id":"mahavishnu"'` line in `bifrost.log` (Phase D verification gate).

**Rollback signal**: `bifrost.route_claude_code: false` reverts Claude Code; `bifrost.route_qwen_code: false` reverts Qwen. Independent flags.

**Observability added**: per-spawn INFO log emitted from `_resolve_worker_env()` showing the env-var injection.

### Integration Contract — Phase E (observability, alerts, e2e, CLI subcommand)

**Triggered from**: `mcp__mahavishnu__get_health`, `GET /health`, `mahavishnu metrics bifrost --source auto --output table`.

**Returns to / updates**: `/health.bifrost.config` returns the config block; `/health.bifrost.reachable` returns a boolean; `mahavishnu_health_feed_status{feed="bifrost",status=...}` gauge increments on probe; `mahavishnu metrics bifrost --source auto --output table` shows dispatch counts; `config/prometheus/bifrost_alerts.yml` ships the `MahavishnuBifrostErrorRateHigh` rule.

**Demonstrable by**: `curl -s http://localhost:8680/health | jq .bifrost.config` returns the config block; `curl -s http://localhost:8680/health | jq .bifrost.reachable` returns a boolean; `mahavishnu metrics bifrost` returns non-zero counters; `pytest tests/integration/test_bifrost_*.py` passes; `crackerjack run -v` green.

**Rollback signal**: per `mcp-backend-wiring-discipline.md`: when `bifrost.reachable` is false, `/health.bifrost.reachable=false` propagates to `mahavishnu_health_feed_status{feed="bifrost",status="degraded"}` and the route returns 503. Alert `MahavishnuBifrostErrorRateHigh` fires.

**Observability added**: full observability surface — Bifrost-side + Mahavishnu-side log lines, counters/histograms, alert rule, e2e tests, CLI subcommand. Node stdout buffering mitigation in `scripts/bifrost-gateway.py`.

### Integration Contract — Phase F (migration cleanup)

**Triggered from**: `git rm` of `settings/models.yaml:bifrost:` block; `git grep` over the repo.

**Returns to / updates**: `settings/models.yaml` no longer has `bifrost:` block; `BIFROST_BASE_URL` env var is no longer read; the four in-tree runtime `minimax.io/v1` hits are replaced (see §1 Proof — `cloud_worker.py:37`, `agno_adapter_impl.py:244/259`, `_probes.py:128`).

**Demonstrable by**: `grep -rn "minimax\.io/v1" mahavishnu/engines mahavishnu/workers/capabilities mahavishnu/workers/cloud_worker.py mahavishnu/llm_gateway` returns zero hits outside `settings/models.yaml` and `mahavishnu/llm_gateway/`; `grep -rn BIFROST_BASE_URL .` returns zero hits; `grep -rn "bifrost:" settings/models.yaml` returns zero hits.

**Rollback signal**: revert the four replacement edits. The `models.yaml` block deletion is a single-file revert.

**Observability added**: a docs-CI grep check enforces the proof assertions on every PR.

### 5.10 Phases

Per `wire-up-contract.md`:

**Phase A — settings schema and observability scaffolding**

- Files: `mahavishnu/core/config.py` (new `BifrostConfig` with `model_config = ConfigDict(extra="forbid")` and `Literal["off","direct","semantic"]` cache mode — citing `ChangepointConfig.detector` at `config.py:622` as the precedent; mount on `MahavishnuSettings` with `Field(default_factory=...)`); `mahavishnu/observability/prometheus_metrics.py` (register the three counter/histogram series directly with `prometheus_client`); `settings/mahavishnu.yaml` (add `bifrost:` block with defaults); `settings/local.yaml` (add `bifrost: { enabled: true }` opt-in); `mahavishnu/cli/config_validator.py` (extend `mahavishnu config validate` to show `bifrost` schema dump); `mahavishnu/metrics_cli.py` (add `bifrost` subcommand reading from local Prom registry; flags `--source {auto,prom,otel}`, `--output {table,json}`, `--provider {minimax,anthropic,all}`).
- Tests: `tests/unit/test_config.py::TestBifrostConfigSchema` (defaults, env-prefix overrides, validation, `extra="forbid"` rejects unknowns, `test_env_overrides_local_yaml`, `test_mount_uses_field_default_factory`).
- Demonstrable: `mahavishnu config validate` shows the schema; `MAHAVISHNU_BIFROST__enabled=true` overrides `local.yaml`; `mahavishnu metrics bifrost --source auto --output table` runs (zero series is acceptable pre-P).
- Rollback: revert the config mount — no production behavior change.

**Phase B — mahavishnu LLM-calling surface integration (Agno adapter + PROVIDER_PROBES)**

- Files: `mahavishnu/engines/agno_adapter_impl.py` (three sites: `_create_openai_model`, `_create_anthropic_model`, `_create_minimax_model`; `LLMProviderFactory.__init__` gains `settings: MahavishnuSettings | None = None` parameter and `self._settings` attribute); `mahavishnu/workers/capabilities/_probes.py` (new `resolve_probe_endpoint(provider, settings)` helper called from `_probe_provider_request`); **possible mcp-common PR** adding `ProviderConfig.extra_headers` + `OpenAICompatibleProvider.__init__(..., default_headers=...)` (Phase B decision: ship with `base_url`-only rewriting + caller_id logging at the call site if the mcp-common PR is not yet merged; widen to header injection when it is).
- Tests: `tests/unit/test_agno_adapter.py::TestAgnoAdapterBifrost` (openai path, anthropic path, minimax default fallback, `MINIMAX_BASE_URL` precedence test, base_url-only when no headers field, factory signature unchanged for non-bifrost tests); `tests/unit/test_provider_probes.py::TestProviderProbesBifrost` (URL resolved via `resolve_probe_endpoint` when enabled, unchanged when disabled).
- Demonstrable: with `bifrost.enabled: true` in `local.yaml`, an Agno workflow invocation produces `'"caller_id":"mahavishnu"'` in `bifrost.log` within 15 seconds.
- Rollback: `bifrost.enabled: false` reverts to direct-to-MiniMax.

**Phase C — merged with Phase B** (no separate Phase).

**Phase D — AI-CLI worker env-injection (Claude + Qwen)**

- Files: `mahavishnu/terminal/manager.py:240` (`_resolve_worker_env` helper; `launch_sessions` accepts `worker_type`); `mahavishnu/terminal/adapters/tmux.py:22` (`TmuxTerminalAdapter.launch_session` accepts `worker_type: str` and `env: dict[str, str] | None`); `mahavishnu/workers/contract/manager.py` (`DurableWorkerManager.spawn` accepts `env=`); `mahavishnu/workers/contract/tmux_adapter.py:84-130` (`create_session` accepts `env=`; emits `tmux set-environment -t <session> KEY VAL` per entry); `mahavishnu/workers/registry.py:116/131` (registry line corrections are documentation-only, no code change); `settings/mahavishnu.yaml` (document `route_claude_code: false` and `route_qwen_code: false` defaults).
- Tests: `tests/unit/test_terminal_worker_settings.py::TestTerminalWorkerSettingsBifrost` (claude inherits via tmux set-environment, claude default, qwen inherits, qwen default, qwen_env_var field override, `test_qwen_actual_dispatch_emits_caller_id` for the verification gate). Note: tests live in `tests/unit/test_terminal_worker_settings.py`, NOT `tests/unit/test_worker_contract.py` — the latter doesn't exist after Plan v3 Phase 4.5b.
- Demonstrable: with `route_claude_code: true` in `local.yaml`, launch a `terminal-claude` worker; `tmux send-keys -t <session> 'printenv ANTHROPIC_BASE_URL' Enter` returns `http://127.0.0.1:8471/anthropic`. With `route_qwen_code: true` AND `qwen_env_var` set to the verified name, an actual Qwen CLI dispatch produces a `'"caller_id":"mahavishnu"'` line in `bifrost.log` (verification gate — Phase D ships with `route_qwen_code: false` until this passes).
- Rollback: `bifrost.route_claude_code: false` reverts Claude; `bifrost.route_qwen_code: false` reverts Qwen.

**Phase E — Observability, alerts, e2e, CLI subcommand**

- Files: `mahavishnu/core/health.py` (`HealthResponse.bifrost.config` and `.reachable` sub-shapes); `mahavishnu/metrics_cli.py` (extend `bifrost_metrics` subcommand — reads `mahavishnu_bifrost_*` series from local Prom registry with `--source`, `--output`, `--provider` flags); `scripts/bifrost-gateway.py` (Node stdout buffering mitigation: `stdbuf -oL -eL` or `os.fsync`); `config/prometheus/bifrost_alerts.yml` (new — `MahavishnuBifrostErrorRateHigh` rule); `tests/integration/test_bifrost_routing_e2e.py` (new — `'"caller_id":"mahavishnu"'` grep with 15-second window); `tests/integration/test_bifrost_health_e2e.py` (new — `/health.bifrost.config` and `/health.bifrost.reachable` shape assertions).
- Demonstrable: `curl -s http://localhost:8680/health | jq .bifrost.config` returns the config block; `curl -s http://localhost:8680/health | jq .bifrost.reachable` returns a boolean; `mahavishnu metrics bifrost --source auto --output table` returns non-zero counters; `pytest tests/integration/test_bifrost_*.py` passes; `crackerjack run -v` green.
- Rollback: per `mcp-backend-wiring-discipline.md`: `/health` returns 503 when `bifrost.reachable=false`; alert `MahavishnuBifrostErrorRateHigh` fires.

**Phase F — Migration cleanup (replace-not-extend)**

- Files: `settings/models.yaml` (delete `bifrost:` block at lines 103-107); `mahavishnu/workers/cloud_worker.py:37` (delete `MINIMAX_OPENAI_BASE_URL` constant — dead after CloudWorker orphan confirmed); `mahavishnu/engines/agno_adapter_impl.py:244` (docstring fix); `mahavishnu/engines/agno_adapter_impl.py:259` (factory default-fallback now reads `BifrostConfig`); `mahavishnu/workers/capabilities/_probes.py:128` (probe URL now resolved via `resolve_probe_endpoint`); remove any `BIFROST_BASE_URL` references in docs.
- Tests: `grep -rn BIFROST_BASE_URL .` returns zero hits; `grep -rn "bifrost:" settings/models.yaml` returns zero hits; `grep -rn "minimax\.io/v1" mahavishnu/engines mahavishnu/workers/capabilities mahavishnu/workers/cloud_worker.py mahavishnu/llm_gateway` returns zero hits outside `settings/models.yaml` and `mahavishnu/llm_gateway/`.
- Demonstrable: docs-CI / pre-commit grep check enforces the proof assertions on every PR.

## 6. Tests

### 6.1 Unit tests (per-phase)

| Test | Phase | Asserts |
|---|---|---|
| `TestBifrostConfigSchema::test_defaults` | A | All defaults match §5.1 |
| `TestBifrostConfigSchema::test_env_prefix_override` | A | `MAHAVISHNU_BIFROST__enabled=true` overrides yaml |
| `TestBifrostConfigSchema::test_env_overrides_local_yaml` | A | env var wins over `local.yaml` per Oneiric precedence |
| `TestBifrostConfigSchema::test_mount_uses_field_default_factory` | A | Mount follows `Field(default_factory=...)` precedent |
| `TestBifrostConfigSchema::test_extra_forbid_rejects_unknown_field` | A | Stray `bifrost.foo` in yaml is rejected |
| `TestBifrostConfigSchema::test_validation_rejects_invalid_cache_mode` | A | `Literal["off","direct","semantic"]` enforced |
| `TestAgnoAdapterBifrost::test_openai_path_routes_through_gateway` | B | `_create_openai_model` uses bifrost base_url when enabled |
| `TestAgnoAdapterBifrost::test_anthropic_path_routes_through_gateway` | B | `_create_anthropic_model` uses bifrost anthropic base_url |
| `TestAgnoAdapterBifrost::test_minimax_default_fallback` | B | `_create_minimax_model` rewrites default to bifrost when enabled |
| `TestAgnoAdapterBifrost::test_minimax_base_url_ignored_when_bifrost_enabled` | B | `MINIMAX_BASE_URL` env var does NOT override bifrost when enabled |
| `TestAgnoAdapterBifrost::test_base_url_only_when_no_headers_field` | B | When mcp-common `extra_headers` is not yet merged, `base_url` rewriting still works |
| `TestAgnoAdapterBifrost::test_factory_signature_unchanged_for_non_bifrost_tests` | B | Existing `LLMProviderFactory(config)` calls without settings still work |
| `TestProviderProbesBifrost::test_minimax_url_resolved_when_enabled` | B | `resolve_probe_endpoint("minimax", settings)` returns bifrost URL |
| `TestProviderProbesBifrost::test_minimax_url_unchanged_when_disabled` | B | `resolve_probe_endpoint("minimax", settings)` returns literal |
| `TestTerminalWorkerSettingsBifrost::test_claude_code_inherits_anthropic_base_url` | D | `ANTHROPIC_BASE_URL` set via `tmux set-environment` when `route_claude_code: true` |
| `TestTerminalWorkerSettingsBifrost::test_claude_code_default_unchanged` | D | `ANTHROPIC_BASE_URL` absent when `route_claude_code: false` |
| `TestTerminalWorkerSettingsBifrost::test_qwen_code_inherits_qwen_env_var` | D | `qwen_env_var` (default `OPENAI_BASE_URL`) set via `tmux set-environment` when `route_qwen_code: true` |
| `TestTerminalWorkerSettingsBifrost::test_qwen_code_default_unchanged` | D | `qwen_env_var` absent when `route_qwen_code: false` |
| `TestTerminalWorkerSettingsBifrost::test_qwen_env_var_field_override` | D | Custom `qwen_env_var` setting name is honored |
| `TestTerminalWorkerSettingsBifrost::test_qwen_actual_dispatch_emits_caller_id` | D | Real Qwen CLI dispatch produces `'"caller_id":"mahavishnu"'` in bifrost.log (verification gate) |
| `TestMigration::test_no_bifrost_block_in_models_yaml` | F | `settings/models.yaml` no longer has `bifrost:` block |
| `TestMigration::test_no_bifrost_base_url_env_var` | F | `grep -rn BIFROST_BASE_URL .` returns zero hits |

### 6.2 Integration tests (`tests/integration/`)

| Test | Asserts |
|---|---|
| `test_bifrost_routing_e2e` | After an Agno workflow invocation against the cloud tier, `bifrost.log` contains `'"caller_id":"mahavishnu"'` within 15 seconds. Uses `pytest.mark.timeout(60)`. |
| `test_bifrost_dispatch_metrics_e2e` | `mahavishnu metrics bifrost --source auto --output table` shows non-zero `dispatch_total` and a populated `dispatch_latency_seconds` histogram after one dispatch. |
| `test_bifrost_health_e2e` | `GET /health` JSON includes `bifrost.config` (config block) and `bifrost.reachable` (boolean). |
| `test_bifrost_disabled_direct_path_e2e` | With `bifrost.enabled: false`, `pool_route_execute` reaches `https://api.minimax.io/v1` directly (asserted via mock or via Bifrost log absence). |
| `test_bifrost_qwen_verification_gate` | With `route_qwen_code: true` AND verified Qwen env-var name, a real Qwen CLI dispatch produces a `'"caller_id":"mahavishnu"'` line in bifrost.log. This is the gate for shipping `route_qwen_code: true` enabled by default. |

### 6.3 Regression coverage

- Existing `tests/unit/test_*.py` must continue to pass with `bifrost.enabled: false` (default).
- `pytest tests/integration/test_llm_gateway_*.py` continues to cover `build_gateway_envelope()` correctness.
- `crackerjack run -v -f` clean per `feedback-crackerjack-merge-gate-is-vf.md`.

## 7. Open Questions

1. **Should `route_claude_code` also toggle the *host* Claude Code MCP transport?** The `minimax-coding-plan-mcp` server's `MINIMAX_API_HOST` could be rewired to `http://127.0.0.1:8471/anthropic` when `route_claude_code: true`. **Decision: defer to a separate spec** for MCP server config — the env injection alone gives operators the runtime control without coupling `~/.mcp.json` to `settings/mahavishnu.yaml`. The *host* Claude Code session is independent. Tracked as a follow-up.
2. **Multi-region Bifrost?** Out of scope per `docs/decisions/`; one `base_url` per deployment. Multiple Bifrost instances would require a list field; not needed today.
3. **Bifrost auth.** The config has `auth_env: str = "BIFROST_API_KEY"` but today's gateway is auth-less (the `.mcp.json` access is by network locality). Defaulting the env var name is forward-compat; no code reads it until the gateway enforces auth. Tracked as a follow-up.
4. **What env var does the Qwen CLI actually read for a custom base URL?** The `qwen_env_var: str = "OPENAI_BASE_URL"` default is the OpenAI-compatible convention. Candidates are `QWEN_BASE_URL`, `OPENAI_BASE_URL`, and `DASHSCOPE_API_BASE`. Phase D verifies the actual name via Qwen CLI docs / `--help` output AND a real Qwen CLI dispatch (the verification gate — see `test_qwen_actual_dispatch_emits_caller_id`). Updates `settings/mahavishnu.yaml` to override the default if needed. The settings-side field exists so this becomes a config change, not a code change.
5. **`WorkerResult.metadata.provider` post-hoc rewrite.** The spec's v1/v1.1 claim that `metadata.provider == "bifrost"` when Bifrost routed the call is withdrawn (see §5.3). If operators later want post-hoc metadata rewriting, a separate spec covers a `WorkerResult.provider: Literal["bifrost", "direct", ...]` typed field. Tracked as a follow-up.

## 8. Acceptance criteria

The design ships when:

1. All six phases land in one PR (or stacked PRs gated per phase) — see §5.10.
2. `tests/integration/test_bifrost_routing_e2e.py::test_agno_dispatch_emits_caller_id` passes (15-second window).
3. `mahavishnu metrics bifrost --source auto --output table` returns non-zero counters after one dispatch against the cloud tier with `bifrost.enabled: true`.
4. `curl -s http://localhost:8680/health | jq .bifrost.reachable` returns a boolean; `/health.bifrost.config` returns the config block.
5. `crackerjack run -v -f` clean.
6. `settings/models.yaml:bifrost` block deleted; `grep -rn BIFROST_BASE_URL .` returns zero hits.
7. `local.yaml` ships `bifrost: { enabled: true, route_claude_code: false, route_qwen_code: false }`.
8. The plan file `docs/plans/2026-XX-XX-bifrost-gateway-wiring.md` (derived from this spec) contains one Integration Contract block per Phase (A-F) per `wire-up-contract.md`. `git log --grep "^Bifrost:"` shows commits in Phase A→F order. `crackerjack run -v` is clean at the merge commit.
9. `route_qwen_code` ships `false` in v1.3; the verification gate (`test_qwen_actual_dispatch_emits_caller_id`) must pass before enabling by default.

## 9. Follow-ups (out of scope)

- Rewire `~/.mcp.json:minimax-coding-plan-mcp`'s `MINIMAX_API_HOST` when `route_claude_code: true` (separate spec).
- Extend the per-vendor opt-in pattern to `terminal-codex`, `terminal-deepagents`, and `terminal-clai` workers (each needs its own `route_<vendor>_code: bool` flag and base-URL field). Note: `mahavishnu/workers/__init__.py:15-16` documents `terminal-qwen` as a legacy alias — Phase D ships it but the codebase is moving away; if `terminal-qwen` is formally deprecated, this follow-up replaces the flag with the new vendor's flag.
- `BIFROST_API_KEY` token sourcing when the gateway enables auth.
- Mahavishnu-side retry/circuit-breaker wrapping the gateway call (separate decision — currently inherits from `FallbackChain` semantics).
- Cross-component Bifrost adoption (Akosha, Session-Buddy, Crackerjack) — separate specs per component.
- Bifrost semantic cache rollout once an embedding strategy is configured (today `recommended_cache_mode()` returns `direct` per `mahavishnu/llm_gateway/client.py:74-96`).
- `WorkerResult.metadata.provider == "bifrost"` post-hoc rewrite via a typed `WorkerResult.provider` field (if operators request it after v1.3 lands).
- CloudWorker resurrection if anyone needs it (`docs/feature-tracking/2026-09-25-cloud-worker-decision.md:46` records the KEEP decision; this spec doesn't reopen it).
- The four `minimax.io/v1` runtime hits (see §1 proof) require Phase F file edits; the proof assertion is invalid until those edits land.
