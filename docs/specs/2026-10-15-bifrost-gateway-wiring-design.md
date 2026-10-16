---
status: draft
role: canonical
kind: spec
date: 2026-10-15
last_reviewed: 2026-10-15
topic: bifrost-gateway-wiring
revision: v1.2
owner: platform-team
scope: Mahavishnu LLM routing through Bifrost gateway + AI-CLI (Claude Code, Qwen) base URL opt-in
related: docs/decisions/wire-up-contract.md; docs/decisions/mcp-backend-wiring-discipline.md; feedback-no-backwards-compat-pre-1.0.md; feedback-cli-flag-consumer-wiring.md; docs/specs/2026-09-27-shared-bodai-substrate-design.md; settings/models.yaml; config/bifrost/config.template.json; mahavishnu/llm_gateway/
title: "Bifrost Gateway Wiring - Design v1.2"
---

# Bifrost Gateway Wiring - Design v1.2

> **v1.2 amendment (2026-10-15)**: 4-lens review surfaced 37 findings across general-purpose, code-architect, code-explorer (citation audit), and mcp-integration-expert lenses. **Convergent blockers fixed**: (1) `CloudWorker` is orphaned — Plan v3 Phase 4.5b removed all callers; scope re-anchored to the surviving Vishnu LLM surface (Agno adapter, `PROVIDER_PROBES`, agno `_create_anthropic_model`, AI-CLI worker opt-in). LlamaIndex adapter dropped from Phase C (Ollama-only; no cloud SDK to wire). Phase D env-injection site rewired from non-existent `contract/manager.py:launch()` to `TerminalManager.launch_sessions()` → `tmux_adapter.create_session(env=...)`. `BifrostConfig` gains `model_config = ConfigDict(extra="forbid")` (crackerjack hard-limit) and `Field(default_factory=...)` mount. `BifrostCacheMode` StrEnum replaced with `Literal["off","direct","semantic"]`. **Observability discipline added**: 4 mandatory `HealthFeedState` fields per `mcp-backend-wiring-discipline.md §3`; alerting backend (`config/prometheus/bifrost_alerts.yml`); CLI subcommand `mahavishnu metrics bifrost` as Phase E sub-deliverable. **Silent-failure paths closed**: explicit `MINIMAX_BASE_URL` precedence (bifrost wins when enabled) + test; Qwen env-var verification gate before `route_qwen_code` ships enabled; JSON-form log grep pattern. **Per-Phase Integration Contracts**: §5.9 split into one block per Phase (A-F) per `wire-up-contract.md`. **Citations corrected**: `mahavishnu/adapters/llamaindex_adapter.py` → `mahavishnu/engines/llamaindex_adapter_impl.py` (6 places); sibling-precedent list trimmed to 4 real siblings; `MahavishnuSettings(BaseSettings)` (not `OneiricBaseSettings`); `mahavishnu/core/metrics.py` → `mahavishnu/observability/prometheus_metrics.py`; test paths corrected; `registry.py:131` → `:116` for terminal-qwen; `model: "MiniMax-M2.7"` → `MiniMax-M3`. **Phase ordering**: B+C merged (Vishnu LLM adapters).
>
> **v1.1 amendment (2026-10-15, superseded)**: Extends the AI-CLI worker opt-in scope to also cover `terminal-qwen`. Adds `bifrost.route_qwen_code: bool` (default `false`), `bifrost.qwen_env_var: str` (default `OPENAI_BASE_URL`).

> **Why this spec exists**: The Bifrost LLM gateway runs at `:8471` and is healthy, but zero Vishnu LLM traffic reaches it. The existing `mahavishnu/llm_gateway/` package implements the gateway envelope helpers (CCR-compatible route headers, cache scoping, prompt hashing), but has zero production consumers — `tests/unit/test_llm_gateway_*.py` import it and nothing else. `settings/models.yaml` exposes a `bifrost:` block at line 103-107 with `enabled: false` and `activate_env: "BIFROST_BASE_URL"`, but the env var is unread. This is the textbook `feedback-cli-flag-consumer-wiring.md` / `docs-audit-documented-not-wired.md` failure: the helper, the launcher, the config block, and the gateway itself are all wired except the consumer code that would actually route through them.

## 1. Outcome

After this design ships:

- **`BifrostConfig` settings class** mounted on `MahavishnuSettings` as the `bifrost:` sibling. `model_config = ConfigDict(extra="forbid")` per crackerjack hard-limit. `Field(default_factory=..., description="...")` mount per sibling precedent. Fields cover base URL, caller identity, cache mode (Literal), anthropic base URL, route-claude-code opt-in, timeout, and per-environment overrides.
- **Vishnu LLM-calling surface routes through Bifrost when enabled.** Specifically the Agno adapter (`mahavishnu/engines/agno_adapter_impl.py`) — both `_create_openai_model` and `_create_anthropic_model` paths, plus `mahavishnu/workers/capabilities/_probes.py:PROVIDER_PROBES["minimax"]` (pre-flight capability probes). **CloudWorker is out of scope** — `docs/feature-tracking/2026-09-25-cloud-worker-decision.md:46` records zero production or test imports outside the file itself; `WorkerManager._create_isolated_worker` is shepherd-only after Plan v3 Phase 4.5b. The LlamaIndex adapter (`mahavishnu/engines/llamaindex_adapter_impl.py`) is Ollama-only (no OpenAI or Anthropic SDK) and out of scope. When `bifrost.enabled: true`, the cloud tier hits `http://127.0.0.1:8471/v1/chat/completions` (OpenAI) or `http://127.0.0.1:8471/anthropic/v1/messages` (Anthropic) with the `BifrostGatewayRequest` envelope; the local fallback tiers (`llama_server`, `ollama`) stay direct.
- **`mahavishnu/llm_gateway/` package becomes the implementation surface.** `build_gateway_envelope()` is the single entry point for constructing base URL + path + route headers + cache headers. Agno + provider-probe consumers import it; nothing builds Bifrost headers ad hoc.
- **Claude Code Anthropic base URL stays direct-to-MiniMax by default** (`https://api.minimax.io/anthropic` via the `minimax-coding-plan` MCP server). A new field `bifrost.route_claude_code: bool` (default `false`) lets operators opt in to env-injecting `ANTHROPIC_BASE_URL=http://127.0.0.1:8471/anthropic` into Mahavishnu-spawned `terminal-claude` workers. **Scope clarification**: this affects Mahavishnu-spawned `terminal-claude` worker subprocesses only; the *host* Claude Code session's MCP transport (`~/.mcp.json:minimax-coding-plan-mcp`, `MINIMAX_API_HOST=https://api.minimax.io`) is independent and out of scope (tracked as a follow-up).
- **Qwen CLI base URL stays direct by default.** `bifrost.route_qwen_code: bool` (default `false`) opts in to env-injecting the variable named by `bifrost.qwen_env_var` (default `OPENAI_BASE_URL` — OpenAI-compatible convention; verified in Phase D) pointing at `bifrost.base_url` into `terminal-qwen` workers. Phase D ships with `route_qwen_code: false` until the env-var name is verified end-to-end (silent-failure guard); the field is a config-tunable for forward-compat.
- **`settings/models.yaml` `bifrost:` block deleted** — replaced by `settings/mahavishnu.yaml` `bifrost:` block. `BIFROST_BASE_URL` env var deleted — replaced by `MAHAVISHNU_BIFROST__BASE_URL` pydantic-settings env-prefix override per `feedback-no-backwards-compat-pre-1.0.md`.
- **`local.yaml` opt-in**: `bifrost: { enabled: true, route_claude_code: false, route_qwen_code: false }`.
- **Per-Phase Integration Contracts** (one block per Phase A-F) per `docs/decisions/wire-up-contract.md`.
- **Observability discipline per `mcp-backend-wiring-discipline.md`**: 4 mandatory `HealthFeedState` fields (`entities_count`, `last_updated_timestamp`, `errors_total`, `cycles_total`) for the bifrost feed; alerting backend (`config/prometheus/bifrost_alerts.yml`); CLI subcommand `mahavishnu metrics bifrost` as Phase E sub-deliverable.
- **E2E test asserting `caller_id` appears in Bifrost log after worker dispatch** — JSON-form grep `'"caller_id":"mahavishnu"'` with 15-second timeout to absorb Node stdout buffering flake, per the project's `docs/decisions/mcp-backend-wiring-discipline.md §3`.

**Proof it worked**:
- `grep -rn "minimax\.io/v1" mahavishnu/` returns zero hits outside `settings/models.yaml` (the canonical reference) and `mahavishnu/llm_gateway/` (documentation-only). The four in-tree runtime hits are replaced as part of Phase F: `mahavishnu/workers/cloud_worker.py:37` (constant), `mahavishnu/engines/agno_adapter_impl.py:259` (factory default-fallback), `mahavishnu/engines/agno_adapter_impl.py:244` (docstring), `mahavishnu/workers/capabilities/_probes.py:128` (probe URL — replaced with bifrost-aware URL).
- `grep -rn "from mahavishnu.llm_gateway" mahavishnu/` returns hits in `engines/agno_adapter_impl.py`, `workers/capabilities/_probes.py`, plus tests.
- `tail -F ~/.local/state/mcp/logs/bifrost.log | grep '"caller_id":"mahavishnu"'` shows entries within 15 seconds of any `mcp__mahavishnu__pool_route_execute` invocation that hits the cloud tier (Node stdout block-buffering absorbed by the longer timeout).
- `curl -s http://localhost:8680/health | jq .checks.bifrost` returns a `HealthFeedState` shape; `curl -s http://localhost:8680/health | jq .bifrost` returns the config block.
- `mahavishnu metrics bifrost` returns non-zero counters after one dispatch against the cloud tier.
- `pytest tests/integration/test_bifrost_routing_e2e.py::test_agno_dispatch_emits_caller_id` passes.

## 2. Goals

1. **First-class settings, not env-var hack.** Mount on `MahavishnuSettings` per the `pi_pool:`, `worktree_storage:`, `goal_teams:`, `changepoint:` sibling pattern (these four are the verified precedent; `runpod_pool:`, `caller_quota:`, `verification:`, `task_orphan_sweeper:` are not implemented sibling blocks per `mahavishnu/core/config.py` audit — see §4.6). Pydantic-settings env-prefix override (`MAHAVISHNU_BIFROST__*`, lowercase per pydantic-settings default) for emergency override; the source of truth is the settings block. Apply `feedback-cli-flag-consumer-wiring.md`: every instantiation site must be grepped.
2. **Single source of truth for gateway envelope construction.** `mahavishnu/llm_gateway.build_gateway_envelope()` is the only entry point. No ad-hoc header construction in workers or adapters — that way the `caller_id`, `cache_scope_key`, and route header construction cannot drift between consumers.
3. **Vishnu LLM callers always go through Bifrost when enabled, fail loud when not.** No "best-effort" fallback to direct MiniMax when Bifrost is unreachable — the LLM call fails and the operator sees it. Per `feedback-bodai-push-is-user-controlled.md` and the project's general posture: don't silently bypass the user-configured path.
4. **Local tiers stay direct.** `llama_server` (`:8081`) and `ollama` (`:11434`) are local-only; Bifrost is not in their chain. Routing them through Bifrost would add latency to localhost calls and create a single point of failure for no benefit.
5. **AI-CLI opt-in is a per-vendor flag set.** `bifrost.route_claude_code: bool` controls env injection into `terminal-claude` (sets `ANTHROPIC_BASE_URL`); `bifrost.route_qwen_code: bool` controls env injection into `terminal-qwen` (sets `bifrost.qwen_env_var`, default `OPENAI_BASE_URL`). Both default `false`. When an operator opts in, env injection happens at worker spawn time via `TerminalManager.launch_sessions()` → `tmux_adapter.create_session(env=...)`. Each flag is independent. **Ship gate**: `route_qwen_code` ships `false` in v1.2 until Phase D verification confirms the Qwen CLI's actual env-var name.
6. **Per-request observability.** Each dispatch logs `caller_id`, `provider`, `model`, `task_category` at INFO level; emits metrics `mahavishnu_bifrost_dispatch_total{outcome,provider,route_class}` and `mahavishnu_bifrost_dispatch_latency_seconds` (histogram) registered in `mahavishnu/observability/prometheus_metrics.py`. Bifrost feed state appears in `/health.checks.bifrost` (HealthFeedState shape) with the four mandatory fields per `mcp-backend-wiring-discipline.md §3`. Rollback signal: error rate on a single provider climbs above 50% over 60s; alert lives in `config/prometheus/bifrost_alerts.yml`.
7. **Independent rollback per scope.** Setting `bifrost.enabled: false` reverts Vishnu LLM callers; setting `bifrost.route_claude_code: false` reverts Claude Code only; setting `bifrost.route_qwen_code: false` reverts Qwen only. Each can be set independently.
8. **No backwards compatibility shims.** Pre-1.0 codebase per `feedback-no-backwards-compat-pre-1.0.md`: replace, don't extend. `BIFROST_BASE_URL` env var stops working on merge. `settings/models.yaml:bifrost` block deleted on merge.
9. **Silent-failure paths closed** (per the silent-failure-hunter pattern). `MINIMAX_BASE_URL` precedence is explicit and tested. Qwen env-var verification gate precedes `route_qwen_code` shipping enabled. Host-vs-worker scope is clarified so operators don't assume the host Claude Code session routes through Bifrost.

## 3. Non-Goals

- **Wiring CloudWorker.** Per `docs/feature-tracking/2026-09-25-cloud-worker-decision.md:46`, CloudWorker has zero production callers after Plan v3 Phase 4.5b; the resurrection path is a separate piece of work. This spec is scoped to the surviving LLM-calling surface.
- **Routing llama-server or ollama through Bifrost.** Local providers don't need gateway caching or routing rules.
- **Cross-repo Bifrost adoption.** This spec is Mahavishnu-only. Akosha, Session-Buddy, Crackerjack, and the `minimax-coding-plan-mcp` server are out of scope; if they need Bifrost, they get their own specs.
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

### 4.3 Surviving Vishnu LLM-calling surface (post-Plan v3 Phase 4.5b)

`grep -rn "OpenAI\|Anthropic\|anthropic\.com\|api\.minimax\.io\|base_url\|api_key" /Users/les/Projects/mahavishnu/mahavishnu/`:

- `mahavishnu/engines/agno_adapter_impl.py:177-216` — `_create_openai_model` constructs `OpenAIChat(id=…, api_key=…, temperature=…, max_tokens=…)`; `_create_anthropic_model` constructs `Claude(id=…, api_key=…, temperature=…, max_tokens=…)`. **No `base_url=` or `default_headers=` parameter is currently passed** (mcp-common `ProviderConfig` lacks `extra_headers`; Phase B coordinates an mcp-common PR or scopes to `base_url`-only rewriting + caller_id logging).
- `mahavishnu/engines/agno_adapter_impl.py:240-262` — `_create_minimax_model` constructs an OpenAI chat with `base_url=self.config.base_url or "https://api.minimax.io/v1"`. This is the **one** place in the Agno adapter that already passes `base_url=`.
- `mahavishnu/workers/capabilities/_probes.py:127-132` — `PROVIDER_PROBES["minimax"] = ("MINIMAX_API_KEY", "https://api.minimax.io/v1/models")`. Pre-flight capability probes bypass FallbackChain.
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

### 4.6 Settings mount pattern (verified precedents)

`mahavishnu/core/config.py:715-718` (`PiPoolSettings`):

```python
class PiPoolSettings(BaseModel):
    """Pi pool-specific settings (Bifrost is a similar shape)."""
    # Mounted as the top-level ``pi_pool`` sibling on :class:`MahavishnuSettings`.
```

**Verified sibling blocks** (grep of `mahavishnu/core/config.py` for class definitions + sibling mounts):

- `pi_pool` — `PiPoolSettings` at line 715; mounted at line 2961
- `worktree_storage` — `WorktreeStorageConfig`; mounted at line 2991
- `goal_teams` — `GoalTeamsSettings`; mounted at line 3132
- `changepoint` — `ChangepointConfig` at line 595; mounted at line 2972

Other names mentioned in `CLAUDE.md` / docs (`runpod_pool`, `caller_quota`, `verification`, `task_orphan_sweeper`) are **not** sibling blocks in `mahavishnu/core/config.py` — they appear only in comments. The `BifrostConfig` mount pattern uses the four verified siblings as precedent.

`MahavishnuSettings` inheritance per `mahavishnu/core/config.py:2763`:

```python
class MahavishnuSettings(BaseSettings):  # NOT OneiricBaseSettings
    """Mahavishnu application settings (extending MCPServerSettings)."""
```

The docstring says "extending MCPServerSettings" (from `mcp-common`); `OneiricBaseSettings` does not appear in this file.

## 5. Design

### 5.1 Settings schema

New class `BifrostConfig` in `mahavishnu/core/config.py`, mounted as `bifrost: BifrostConfig = Field(default_factory=BifrostConfig, description="Bifrost LLM gateway wiring for the surviving Vishnu LLM-calling surface (Agno adapter, PROVIDER_PROBES, AI-CLI worker opt-in).")` on `MahavishnuSettings`.

```python
from typing import Literal

class BifrostConfig(BaseModel):
    """First-class Bifrost gateway settings.

    When ``enabled`` is True, the surviving Vishnu LLM surface (Agno adapter,
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
    cache_mode: Literal["off", "direct", "semantic"] = "off"
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

### 5.3 Agno adapter integration (Vishnu-LLM scope, the primary wiring surface)

`mahavishnu/engines/agno_adapter_impl.py` changes — three sites, one pattern:

**Site 1: `_create_openai_model` (lines 177-196 today)**

```python
def _create_openai_model(self, *, model: str, settings: MahavishnuSettings) -> OpenAIChat:
    kwargs = dict(id=model, api_key=self.config.api_key, temperature=..., max_tokens=...)
    if settings.bifrost.enabled:
        envelope = build_gateway_envelope(
            caller_id=settings.bifrost.caller_id,
            protocol_family=ProtocolFamily.OPENAI,
            model=model,
            prompt="",  # not available at construction; env can supply
            task_label=None,
            base_url=settings.bifrost.base_url,
            cache_mode=CacheMode(settings.bifrost.cache_mode),
            cache_ttl_seconds=settings.bifrost.cache_ttl_seconds,
        )
        # Agno's OpenAIChat accepts base_url via constructor in current pin;
        # envelope headers may require a mcp-common `ProviderConfig.extra_headers`
        # field (see §5.3 dependency). If mcp-common PR isn't ready at ship,
        # scope to base_url-only and add caller_id logging at the call site.
        kwargs["base_url"] = envelope.api_base  # → "http://127.0.0.1:8471/v1"
        # kwargs["default_headers"] = envelope.request_headers  # Phase B dependency
    return OpenAIChat(**kwargs)
```

**Site 2: `_create_anthropic_model` (lines 198-216 today)**

Same pattern with `ProtocolFamily.ANTHROPIC` and `envelope.api_base` resolves to `http://127.0.0.1:8471/anthropic`. `kwargs["base_url"] = envelope.api_base`.

**Site 3: `_create_minimax_model` (lines 240-262 today)**

The one existing place that passes `base_url=`. Rewrite the default fallback so it routes through Bifrost when enabled:

```python
def _create_minimax_model(self, *, model: str, settings: MahavishnuSettings) -> OpenAIChat:
    if settings.bifrost.enabled:
        base_url = gateway_api_base(ProtocolFamily.OPENAI, base_url=settings.bifrost.base_url)
    else:
        base_url = self.config.base_url or "https://api.minimax.io/v1"
    return OpenAIChat(id=model, api_key=self.config.api_key, base_url=base_url, ...)
```

**mcp-common dependency** (the gate on envelope header injection): `mcp-common/mcp_common/llm/config.py:16-33` (`ProviderConfig`, `extra="forbid"`) has no `extra_headers` field; `mcp-common/mcp_common/llm/provider.py:42-58` (`OpenAICompatibleProvider.__init__`) only sets `default_headers={"Authorization": ""}` for local providers; the cloud branch doesn't accept header injection. Phase B includes either an mcp-common PR adding `ProviderConfig.extra_headers` + `OpenAICompatibleProvider.__init__(..., default_headers=...)` OR a scoped Phase B that limits Bifrost to `base_url`-only rewriting + caller_id logging in the adapter (sufficient for the `caller_id` log requirement per §1 proof).** The choice is Phase B's decision; this spec requires the `caller_id` log assertion to pass either way.

**`WorkerResult.metadata.provider` clarification**: `FallbackChain.from_settings()` (where used) returns the provider key from the configured `providers` dict. Phase B does **not** add a second `bifrost` provider entry to that dict; instead, `minimax` is the configured key and the `base_url` swap changes the routing. `WorkerResult.metadata.provider` therefore remains `minimax` regardless of Bifrost's enabled flag. Operators should grep `mahavishnu_bifrost_dispatch_total` (counter) rather than `metadata.provider` to count Bifrost-routed traffic. The spec's v1/v1.1 `metadata.provider == "bifrost"` claim is **withdrawn** (see §9 follow-ups for the post-hoc rewrite path if it's ever needed).

**`PROVIDER_PROBES["minimax"]` integration** (`mahavishnu/workers/capabilities/_probes.py:127-132`):

```python
PROVIDER_PROBES = {
    "minimax": ("MINIMAX_API_KEY", settings.bifrost.base_url + "/v1/models" if settings.bifrost.enabled else "https://api.minimax.io/v1/models"),
    # ... other providers unchanged
}
```

The probe URL is a pre-flight HTTP GET to `/v1/models`; Bifrost accepts the same path, so this is a simple URL rewrite. No protocol change.

### 5.4 Removed: LlamaIndex adapter integration

`mahavishnu/engines/llamaindex_adapter_impl.py:39-40, 384-386` imports only `OllamaEmbedding`/`Ollama` from `llama_index.llms.ollama`. There is no OpenAI or Anthropic SDK client anywhere in the file. The spec's v1/v1.1 Phase C inclusion was a structural error — Phase C is dropped entirely. LlamaIndex adapter stays as out of scope (it routes to local Ollama; `§3 Non-Goals` covers the rationale).

### 5.5 AI-CLI worker integration (Vishnu-worker scope, opt-in, per-vendor)

When `bifrost.enabled: True` AND the corresponding per-vendor flag is also True, the worker inherits a base-URL env var at spawn time. Two flags, two workers, two env vars:

| Flag | Worker type | Env var | Value |
|---|---|---|---|
| `bifrost.route_claude_code` | `terminal-claude` | `ANTHROPIC_BASE_URL` | `bifrost.anthropic_base_url` |
| `bifrost.route_qwen_code` | `terminal-qwen` | `bifrost.qwen_env_var` (default `OPENAI_BASE_URL`) | `gateway_api_base(ProtocolFamily.OPENAI, base_url=bifrost.base_url)` (→ `http://127.0.0.1:8471/v1`) |

**Host-vs-worker scope**: this affects **Mahavishnu-spawned** `terminal-claude` and `terminal-qwen` worker subprocesses only. The host Claude Code session's MCP transport (`~/.mcp.json:42-55`, `minimax-coding-plan-mcp`, `MINIMAX_API_HOST=https://api.minimax.io`) is independent. Operators who flip `route_claude_code: true` and expect the host session to route through Bifrost will be disappointed — that's a separate spec.

**Env-injection wiring site**: `TerminalManager.launch_sessions()` (`mahavishnu/terminal/manager.py:240`) → adapter `launch_session()` → `tmux_adapter.create_session(env=...)` (`mahavishnu/terminal/adapters/tmux.py:22`, `mahavishnu/workers/contract/tmux_adapter.py:84-130`). The existing `subprocess.run(["tmux", "-S", socket, "new-session", "-d", ...])` call does not currently accept `env=`; **Phase D includes the addition of `env: dict[str, str] | None` to `create_session()` and to the tmux `new-session -e KEY=VAL` invocation** (or, if tmux version doesn't support `-e`, env mutation on the parent shell before the tmux fork).

```python
# Sketch: TerminalManager.launch_sessions() (line 240 area)
def _resolve_worker_env(worker_type: str, base_env: dict[str, str], settings: MahavishnuSettings) -> dict[str, str]:
    env = dict(base_env)
    if settings.bifrost.enabled:
        if worker_type == "terminal-claude" and settings.bifrost.route_claude_code:
            env["ANTHROPIC_BASE_URL"] = settings.bifrost.anthropic_base_url
        elif worker_type == "terminal-qwen" and settings.bifrost.route_qwen_code:
            env[settings.bifrost.qwen_env_var] = gateway_api_base(
                ProtocolFamily.OPENAI, base_url=settings.bifrost.base_url
            )
    return env
```

Defaults — both flags `false` — mean today's behavior is unchanged:

- Claude Code keeps calling `https://api.minimax.io/anthropic` via the `minimax-coding-plan` MCP server (host session).
- Mahavishnu-spawned `terminal-claude` keeps reading the default Claude Code endpoint (no `ANTHROPIC_BASE_URL` injected).
- Mahavishnu-spawned `terminal-qwen` keeps reading its default endpoint (no env-var injected).

When the operator flips a flag, the worker is spawned with the env var pointing at the corresponding Bifrost endpoint. Each flag is independent: flipping `route_claude_code` does not affect Qwen workers and vice versa.

**Worker registry line citations**: `mahavishnu/workers/registry.py:131` is `terminal-claude`; `mahavishnu/workers/registry.py:116` is `terminal-qwen` (corrected from the v1.1 wrong-citation `:131`).

**Phase D verification gate**: `route_qwen_code: false` ships in v1.2 even if the operator opts in via `local.yaml`. Phase D demonstrates the env var flows into the spawned worker via `printenv` from inside the worker's tmux session, AND runs an actual Qwen CLI dispatch to confirm the `caller_id=mahavishnu` line appears in `bifrost.log`. If the actual Qwen env var name is `QWEN_BASE_URL` or `DASHSCOPE_API_BASE` (not `OPENAI_BASE_URL`), the operator updates `bifrost.qwen_env_var` in `local.yaml` and re-runs; the code path is unchanged.

### 5.6 Migration

**Replace, no deprecation** per `feedback-no-backwards-compat-pre-1.0.md`:

| Old | New | Action |
|---|---|---|
| `settings/models.yaml:bifrost:` block | `settings/mahavishnu.yaml:bifrost:` block (plus `local.yaml` opt-in) | Delete `models.yaml` block in same PR. |
| `BIFROST_BASE_URL` env var | `MAHAVISHNU_BIFROST__BASE_URL` env-prefix | Stop reading `BIFROST_BASE_URL` in same PR. |
| `MINIMAX_BASE_URL` env var (redirect to private LLM-compatible service) | Same — keep as an explicit redirect for direct mode. **Precedence**: when `bifrost.enabled: true`, `BifrostConfig.base_url` is the source of truth and `MINIMAX_BASE_URL` is read but ignored. Enforced in code via `if settings.bifrost.enabled: base_url = gateway_api_base(...)` (Agno `_create_minimax_model` §5.3) and tested by `test_minimax_base_url_ignored_when_bifrost_enabled`. | Document precedence in code; add unit test. |

### 5.7 Observability

**Per-request log line at INFO level** (Bifrost emits JSON; key=value is illustrative for human grep):

```
{"caller_id":"mahavishnu","provider":"minimax-openai","model":"MiniMax-M3",
 "route_class":"default","cache_mode":"off","outcome":"success","duration_ms":432,
 "ts":"2026-10-15T..."}
```

**Metrics registered in `mahavishnu/observability/prometheus_metrics.py`** (per `mahavishnu/core/health_aggregator.py:36` precedent for `_ALLOWED_LABEL_KEYS` allowlist). Phase E adds the four mandatory label keys (`outcome`, `provider`, `route_class`, `reason`) to the allowlist so labels are not stripped at emit time:

- `mahavishnu_bifrost_dispatch_total{outcome,provider,route_class}` (counter)
- `mahavishnu_bifrost_dispatch_latency_seconds{provider,route_class}` (histogram)
- `mahavishnu_bifrost_dispatch_failures_total{provider,reason}` (counter)

**Health surface — two distinct sub-shapes** per `mcp-backend-wiring-discipline.md §1` (config surface) and §3 (per-feed health verdicts):

- `/health.checks.bifrost` — `HealthFeedState` (status, reason_codes, last_updated_timestamp). Aggregator extension at `mahavishnu/core/health_aggregator.py:_collect_feed_states()` adds the bifrost feed.
- `/health.bifrost` — config block projection (`BifrostConfig.to_public_dict()`). Operators verify live config without exposing secrets.

**`HealthFeedState` four mandatory fields per §3**:

| Field | Source | Definition |
|---|---|---|
| `entities_count` | `_probe_bifrost_state()` | `int(200 OK == bifrost_probe_result)`; `1` iff Bifrost is reachable. |
| `last_updated_timestamp` | Dispatch wrapper side-effect | Bumped by `_bifrost_dispatch_heartbeat` module variable on every successful dispatch. |
| `cycles_total` | `_probe_bifrost_state()` | Bumped on every probe call (probe runs every `sampler_cadence_seconds` per `ChangepointConfig`). |
| `errors_total` | `_probe_bifrost_state()` | Bumped on probe non-200 or timeout. |

The feed returns `degraded` when `errors_total / cycles_total > 0.5` over a 60s window, which triggers the `/health` route to return 503 per the project's `mcp-backend-wiring-discipline.md §1`.

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

## Per-Phase Integration Contracts (one block per Phase, per `wire-up-contract.md`)

### Integration Contract — Phase A (settings schema + `mahavishnu/llm_gateway` consumption helper)

**Triggered from**: `mahavishnu/core/config.py:load_settings()` (Oneiric loader); `mahavishnu/llm_gateway/__init__.py:from mahavishnu.llm_gateway import build_gateway_envelope` (test fixtures only today).

**Returns to / updates**: `MahavishnuSettings.bifrost` field populated; `mahavishnu/observability/prometheus_metrics.py` gains `mahavishnu_bifrost_*` series definitions; `settings/mahavishnu.yaml` and `settings/local.yaml` gain `bifrost:` blocks.

**Demonstrable by**: `mahavishnu config validate` shows the schema; `MAHAVISHNU_BIFROST__enabled=true` overrides `local.yaml` (test `TestBifrostConfigSchema::test_env_overrides_local_yaml`); `extra="forbid"` rejects stray fields (test `test_extra_forbid_rejects_unknown_field`); mount uses `Field(default_factory=...)` (test `test_mount_uses_field_default_factory`).

**Rollback signal**: revert the config mount — no production behavior change (consumers don't exist in Phase A).

**Observability added**: none in Phase A.

### Integration Contract — Phase B (Vishnu LLM-calling surface integration)

**Triggered from**: `mcp__mahavishnu__trigger_workflow(adapter="agno", ...)` (Agno adapter instantiates `OpenAIChat` / `Claude`); `mcp__mahavishnu__pool_route_execute` followed by capability probe (PROVIDER_PROBES).

**Returns to / updates**: Agno adapter's three sites (`_create_openai_model`, `_create_anthropic_model`, `_create_minimax_model`) consult `BifrostConfig`; `PROVIDER_PROBES["minimax"]` URL rewrites to bifrost base URL; `MINIMAX_BASE_URL` precedence test enforces bifrost-wins-when-enabled.

**Demonstrable by**: with `bifrost.enabled: true` in `local.yaml`, an Agno workflow invocation produces `'"caller_id":"mahavishnu"'` in `bifrost.log` within 15 seconds (test `tests/integration/test_bifrost_routing_e2e.py::test_agno_dispatch_emits_caller_id`).

**Rollback signal**: `bifrost.enabled: false` reverts to direct-to-MiniMax; per-provider error rate > 50% over 60s triggers alert.

**Observability added**: `mahavishnu_bifrost_dispatch_total{outcome,provider,route_class}` increments; per-request INFO log emitted.

### Integration Contract — Phase C (merged with B per review)

Originally Phase C (Agno + LlamaIndex). Per v1.2 review, LlamaIndex dropped (Ollama-only; no SDK to wire). Merged into Phase B above. **No separate Phase C**.

### Integration Contract — Phase D (AI-CLI worker env-injection)

**Triggered from**: `mcp__mahavishnu__launch_worker(worker_type="terminal-claude"|"terminal-qwen", ...)` → `TerminalManager.launch_sessions()` (`mahavishnu/terminal/manager.py:240`) → adapter `launch_session()` → `tmux_adapter.create_session(env=...)`.

**Returns to / updates**: `terminal-claude` subprocess inherits `ANTHROPIC_BASE_URL=http://127.0.0.1:8471/anthropic` when `route_claude_code: true`; `terminal-qwen` subprocess inherits `bifrost.qwen_env_var` (= `OPENAI_BASE_URL` by default) pointing at `gateway_api_base(OPENAI, bifrost.base_url)` (`http://127.0.0.1:8471/v1`) when `route_qwen_code: true`.

**Demonstrable by**: with `route_claude_code: true` in `local.yaml`, launch a `terminal-claude` worker; `printenv ANTHROPIC_BASE_URL` from inside the worker's tmux session returns `http://127.0.0.1:8471/anthropic` (test `tests/unit/test_terminal_worker_settings.py::test_claude_code_inherits_anthropic_base_url` — note: tests live in `test_terminal_worker_settings.py`, NOT `test_worker_contract.py`; the latter doesn't exist after Plan v3 Phase 4.5b). With `route_qwen_code: true` AND `qwen_env_var` set to the verified Qwen CLI env-var name, an actual Qwen CLI dispatch produces a `'"caller_id":"mahavishnu"'` line in `bifrost.log` (Phase D verification gate).

**Rollback signal**: `bifrost.route_claude_code: false` reverts Claude Code; `bifrost.route_qwen_code: false` reverts Qwen. Independent flags.

**Observability added**: per-spawn INFO log emitted from `_resolve_worker_env()` showing the env-var injection.

### Integration Contract — Phase E (observability, alerts, e2e)

**Triggered from**: `mcp__mahavishnu__get_health`, `GET /health`, `mahavishnu metrics bifrost` CLI subcommand.

**Returns to / updates**: `/health.checks.bifrost` returns a `HealthFeedState` with the four mandatory fields; `/health.bifrost` returns the config block; `mahavishnu metrics bifrost --source auto` shows dispatch counts; `config/prometheus/bifrost_alerts.yml` ships the `MahavishnuBifrostErrorRateHigh` rule.

**Demonstrable by**: `curl -s http://localhost:8680/health | jq .checks.bifrost` returns a populated `HealthFeedState`; `mahavishnu metrics bifrost` returns non-zero counters after one dispatch against the cloud tier; `pytest tests/integration/test_bifrost_routing_e2e.py` passes with 15-second window; `pytest tests/integration/test_bifrost_health_e2e.py` passes; `crackerjack run -v` green.

**Rollback signal**: per `mcp-backend-wiring-discipline.md`: `/health` returns 503 when bifrost feed state is `degraded` (>50% error rate over 60s). Alert `MahavishnuBifrostErrorRateHigh` fires.

**Observability added**: full observability surface — log lines, metrics, alerts, e2e tests. Node stdout buffering mitigation in `scripts/bifrost-gateway.py`.

### Integration Contract — Phase F (migration cleanup)

**Triggered from**: `git rm` of `settings/models.yaml:bifrost:` block; `git grep` over the repo.

**Returns to / updates**: `settings/models.yaml` no longer has `bifrost:` block; `BIFROST_BASE_URL` env var is no longer read; the four in-tree runtime `minimax.io/v1` hits are replaced (see §1 Proof — `cloud_worker.py:37`, `agno_adapter_impl.py:244/259`, `_probes.py:128`).

**Demonstrable by**: `grep -rn "minimax\.io/v1" mahavishnu/` returns zero hits outside `settings/models.yaml` and `mahavishnu/llm_gateway/`; `grep -rn BIFROST_BASE_URL .` returns zero hits; `grep -rn "bifrost:" settings/models.yaml` returns zero hits.

**Rollback signal**: revert the four replacement edits. The `models.yaml` block deletion is a single-file revert.

**Observability added**: a docs-CI grep check enforces the proof assertions on every PR.

### 5.10 Phases

Per `wire-up-contract.md`:

**Phase A — settings schema and `mahavishnu/observability` integration**

- Files: `mahavishnu/core/config.py` (new `BifrostConfig` with `model_config = ConfigDict(extra="forbid")` and `Literal["off","direct","semantic"]` cache mode; mount on `MahavishnuSettings` with `Field(default_factory=...)`); `mahavishnu/observability/prometheus_metrics.py` (register the three counter/histogram series; add `outcome`, `provider`, `route_class`, `reason` to `_ALLOWED_LABEL_KEYS`); `settings/mahavishnu.yaml` (add `bifrost:` block with defaults); `settings/local.yaml` (add `bifrost: { enabled: true }` opt-in); `mahavishnu/cli/config_validator.py` (extend `mahavishnu config validate` to show `bifrost` schema dump); `mahavishnu/metrics_cli.py` (add `bifrost` subcommand reading from local Prom registry).
- Tests: `tests/unit/test_config.py::TestBifrostConfigSchema` (defaults, env-prefix overrides, validation, `extra="forbid"` rejects unknowns, `test_env_overrides_local_yaml`, `test_mount_uses_field_default_factory`).
- Demonstrable: `mahavishnu config validate` shows the schema; `MAHAVISHNU_BIFROST__enabled=true` overrides `local.yaml`; `mahavishnu metrics bifrost --source auto` runs (zero series is acceptable pre-P).
- Rollback: revert the config mount — no production behavior change.

**Phase B — Vishnu LLM-calling surface integration (Agno adapter + PROVIDER_PROBES)**

- Files: `mahavishnu/engines/agno_adapter_impl.py` (three sites: `_create_openai_model`, `_create_anthropic_model`, `_create_minimax_model`); `mahavishnu/workers/capabilities/_probes.py` (`PROVIDER_PROBES["minimax"]` URL rewrite); **possible mcp-common PR** adding `ProviderConfig.extra_headers` + `OpenAICompatibleProvider.__init__(..., default_headers=...)` (Phase B decision: ship with `base_url`-only rewriting + caller_id logging at the call site if the mcp-common PR is not yet merged; widen to header injection when it is).
- Tests: `tests/unit/test_agno_adapter.py::TestAgnoAdapterBifrost` (openai path, anthropic path, minimax default fallback, `MINIMAX_BASE_URL` precedence test, base_url-only mode assertion); `tests/unit/test_provider_probes.py::TestProviderProbesBifrost` (URL rewritten when enabled, unchanged when disabled).
- Demonstrable: with `bifrost.enabled: true` in `local.yaml`, an Agno workflow invocation produces `'"caller_id":"mahavishnu"'` in `bifrost.log` within 15 seconds.
- Rollback: `bifrost.enabled: false` reverts to direct-to-MiniMax.

**Phase C — merged with Phase B** (no separate Phase).

**Phase D — AI-CLI worker env-injection (Claude + Qwen)**

- Files: `mahavishnu/terminal/manager.py:240` (`_resolve_worker_env` helper); `mahavishnu/workers/contract/tmux_adapter.py:84-130` (`create_session(env=...)` extension); `mahavishnu/terminal/adapters/tmux.py:22` (TmuxTerminalAdapter `launch_session(env=...)` extension); `mahavishnu/workers/registry.py:116/131` (registry line corrections are documentation-only, no code change); `settings/mahavishnu.yaml` (document `route_claude_code: false` and `route_qwen_code: false` defaults).
- Tests: `tests/unit/test_terminal_worker_settings.py::TestTerminalWorkerSettingsBifrost` (claude inherits, claude default, qwen inherits, qwen default, qwen_env_var field override, `test_qwen_actual_dispatch_emits_caller_id` for the verification gate). Note: tests live in `tests/unit/test_terminal_worker_settings.py`, NOT `tests/unit/test_worker_contract.py` — the latter doesn't exist after Plan v3 Phase 4.5b.
- Demonstrable: with `route_claude_code: true` in `local.yaml`, launch a `terminal-claude` worker; `printenv ANTHROPIC_BASE_URL` from inside the worker's tmux session returns `http://127.0.0.1:8471/anthropic`. With `route_qwen_code: true` AND `qwen_env_var` set to the verified name, an actual Qwen CLI dispatch produces a `'"caller_id":"mahavishnu"'` line in `bifrost.log` (verification gate — Phase D ships with `route_qwen_code: false` until this passes).
- Rollback: `bifrost.route_claude_code: false` reverts Claude; `bifrost.route_qwen_code: false` reverts Qwen.

**Phase E — Observability, alerts, e2e, CLI subcommand**

- Files: `mahavishnu/core/health_aggregator.py` (`_collect_feed_states()` adds bifrost feed with the four mandatory `HealthFeedState` fields); `mahavishnu/core/health.py` (`HealthResponse.bifrost` config-block sub-shape); `mahavishnu/metrics_cli.py` (extend `bifrost_metrics` subcommand — read `mahavishnu_bifrost_*` series from local Prom registry); `scripts/bifrost-gateway.py` (Node stdout buffering mitigation: `stdbuf -oL -eL` or `os.fsync`); `config/prometheus/bifrost_alerts.yml` (new — `MahavishnuBifrostErrorRateHigh` rule); `tests/integration/test_bifrost_routing_e2e.py` (new — `'"caller_id":"mahavishnu"'` grep with 15-second window); `tests/integration/test_bifrost_health_e2e.py` (new — `/health.checks.bifrost` and `/health.bifrost` shape assertions).
- Demonstrable: `curl -s http://localhost:8680/health | jq .checks.bifrost` returns a populated `HealthFeedState`; `mahavishnu metrics bifrost` returns non-zero counters; `pytest tests/integration/test_bifrost_*.py` passes; `crackerjack run -v` green.
- Rollback: per `mcp-backend-wiring-discipline.md`: `/health` returns 503 when bifrost feed state is `degraded`; alert `MahavishnuBifrostErrorRateHigh` fires.

**Phase F — Migration cleanup (replace-not-extend)**

- Files: `settings/models.yaml` (delete `bifrost:` block at lines 103-107); `mahavishnu/workers/cloud_worker.py:37` (delete `MINIMAX_OPENAI_BASE_URL` constant — dead after CloudWorker orphan confirmed); `mahavishnu/engines/agno_adapter_impl.py:244` (docstring fix); `mahavishnu/engines/agno_adapter_impl.py:259` (factory default-fallback now reads `BifrostConfig`); `mahavishnu/workers/capabilities/_probes.py:128` (probe URL now reads `BifrostConfig`); remove any `BIFROST_BASE_URL` references in docs.
- Tests: `grep -rn BIFROST_BASE_URL .` returns zero hits; `grep -rn "bifrost:" settings/models.yaml` returns zero hits; `grep -rn "minimax\.io/v1" mahavishnu/` returns zero hits outside `settings/models.yaml` and `mahavishnu/llm_gateway/`.
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
| `TestProviderProbesBifrost::test_minimax_url_rewritten_when_enabled` | B | `PROVIDER_PROBES["minimax"]` URL = bifrost base |
| `TestProviderProbesBifrost::test_minimax_url_unchanged_when_disabled` | B | `PROVIDER_PROBES["minimax"]` URL = direct MiniMax |
| `TestTerminalWorkerSettingsBifrost::test_claude_code_inherits_anthropic_base_url` | D | `ANTHROPIC_BASE_URL` injected when `route_claude_code: true` |
| `TestTerminalWorkerSettingsBifrost::test_claude_code_default_unchanged` | D | `ANTHROPIC_BASE_URL` absent when `route_claude_code: false` |
| `TestTerminalWorkerSettingsBifrost::test_qwen_code_inherits_qwen_env_var` | D | `qwen_env_var` (default `OPENAI_BASE_URL`) injected when `route_qwen_code: true` |
| `TestTerminalWorkerSettingsBifrost::test_qwen_code_default_unchanged` | D | `qwen_env_var` absent when `route_qwen_code: false` |
| `TestTerminalWorkerSettingsBifrost::test_qwen_env_var_field_override` | D | Custom `qwen_env_var` setting name is honored |
| `TestTerminalWorkerSettingsBifrost::test_qwen_actual_dispatch_emits_caller_id` | D | Real Qwen CLI dispatch produces `'"caller_id":"mahavishnu"'` in bifrost.log (verification gate) |
| `TestMigration::test_no_bifrost_block_in_models_yaml` | F | `settings/models.yaml` no longer has `bifrost:` block |
| `TestMigration::test_no_bifrost_base_url_env_var` | F | `grep -rn BIFROST_BASE_URL .` returns zero hits |

### 6.2 Integration tests (`tests/integration/`)

| Test | Asserts |
|---|---|
| `test_bifrost_routing_e2e` | After an Agno workflow invocation against the cloud tier, `bifrost.log` contains `'"caller_id":"mahavishnu"'` within 15 seconds. Uses `pytest.mark.timeout(60)`. |
| `test_bifrost_dispatch_metrics_e2e` | `mahavishnu metrics bifrost --source auto` shows non-zero `dispatch_total` and a populated `dispatch_latency_seconds` histogram after one dispatch. |
| `test_bifrost_health_e2e` | `GET /health` JSON includes `checks.bifrost` (HealthFeedState with entities_count, last_updated_timestamp, errors_total, cycles_total) and `bifrost` config-block sub-shape. |
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
5. **`WorkerResult.metadata.provider` post-hoc rewrite.** The spec's v1/v1.1 claim that `metadata.provider == "bifrost"` when Bifrost routed the call is withdrawn (see §5.3). If operators later want post-hoc metadata rewriting, a separate spec covers the `FallbackChain` extension. Tracked as a follow-up.

## 8. Acceptance criteria

The design ships when:

1. All six phases land in one PR (or stacked PRs gated per phase) — see §5.10.
2. `tests/integration/test_bifrost_routing_e2e.py::test_agno_dispatch_emits_caller_id` passes (15-second window).
3. `mahavishnu metrics bifrost` returns non-zero counters after one dispatch against the cloud tier with `bifrost.enabled: true`.
4. `curl -s http://localhost:8680/health | jq .checks.bifrost` returns a populated `HealthFeedState`.
5. `crackerjack run -v -f` clean.
6. `settings/models.yaml:bifrost` block deleted; `grep -rn BIFROST_BASE_URL .` returns zero hits.
7. `local.yaml` ships `bifrost: { enabled: true, route_claude_code: false, route_qwen_code: false }`.
8. `git log` shows Phase commits in order with one Integration Contract block per Phase per `wire-up-contract.md`.
9. `route_qwen_code` ships `false` in v1.2; the verification gate (`test_qwen_actual_dispatch_emits_caller_id`) must pass before enabling by default.

## 9. Follow-ups (out of scope)

- Rewire `~/.mcp.json:minimax-coding-plan-mcp`'s `MINIMAX_API_HOST` when `route_claude_code: true` (separate spec).
- Extend the per-vendor opt-in pattern to `terminal-codex`, `terminal-deepagents`, and `terminal-clai` workers (each needs its own `route_<vendor>_code: bool` flag and base-URL field). Note: `mahavishnu/workers/__init__.py:15-16` documents `terminal-qwen` as a legacy alias — Phase D ships it but the codebase is moving away; if `terminal-qwen` is formally deprecated, this follow-up replaces the flag with the new vendor's flag.
- `BIFROST_API_KEY` token sourcing when the gateway enables auth.
- Mahavishnu-side retry/circuit-breaker wrapping the gateway call (separate decision — currently inherits from `FallbackChain` semantics).
- Cross-component Bifrost adoption (Akosha, Session-Buddy, Crackerjack) — separate specs per component.
- Bifrost semantic cache rollout once an embedding strategy is configured (today `recommended_cache_mode()` returns `direct` per `mahavishnu/llm_gateway/client.py:74-96`).
- `WorkerResult.metadata.provider == "bifrost"` post-hoc rewrite (if operators request it after v1.2 lands).
- CloudWorker resurrection if anyone needs it (`docs/feature-tracking/2026-09-25-cloud-worker-decision.md:46` records the KEEP decision; this spec doesn't reopen it).
- The four `minimax.io/v1` runtime hits (see §1 proof) require Phase F file edits; the proof assertion is invalid until those edits land.