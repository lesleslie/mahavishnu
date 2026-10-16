---
status: draft
role: canonical
kind: spec
date: 2026-10-15
last_reviewed: 2026-10-15
topic: bifrost-gateway-wiring
revision: v1.1
owner: platform-team
scope: Mahavishnu worker LLM routing + AI-CLI (Claude Code, Qwen) base URL opt-in
related: docs/decisions/wire-up-contract.md; docs/decisions/mcp-backend-wiring-discipline.md; feedback-no-backwards-compat-pre-1.0.md; feedback-cli-flag-consumer-wiring.md; docs/specs/2026-09-27-shared-bodai-substrate-design.md; settings/models.yaml; config/bifrost/config.template.json; mahavishnu/llm_gateway/
title: "Bifrost Gateway Wiring - Design v1.1"
---

# Bifrost Gateway Wiring - Design v1.1

> **v1.1 amendment (2026-10-15)**: Extends the AI-CLI worker opt-in scope to also cover `terminal-qwen`. Adds `bifrost.route_qwen_code: bool` (default `false`), `bifrost.qwen_env_var: str` (default `OPENAI_BASE_URL`) so the Qwen CLI inherits an OpenAI-compatible base URL pointing at Bifrost when opted in. Qwen CLI's actual base-URL env-var name is verified in Phase D; the `qwen_env_var` setting field exists so a non-default name is a config change, not a code change. Each vendor's opt-in flag is independent.

> **Why this spec exists**: The Bifrost LLM gateway runs at `:8471` and is healthy, but zero Vishnu worker traffic reaches it. The existing `mahavishnu/llm_gateway/` package implements the gateway envelope helpers (CCR-compatible route headers, cache scoping, prompt hashing), but has zero production consumers — `tests/unit/test_llm_gateway_*.py` import it and nothing else. `settings/models.yaml` exposes a `bifrost:` block at line 103-107 with `enabled: false` and `activate_env: "BIFROST_BASE_URL"`, but the env var is unread. This is the textbook `feedback-cli-flag-consumer-wiring.md` / `docs-audit-documented-not-wired.md` failure: the helper, the launcher, the config block, and the gateway itself are all wired except the consumer code that would actually route through them.

## 1. Outcome

After this design ships:

- **`BifrostConfig` settings class** mounted on `MahavishnuSettings` as the `bifrost:` sibling. Disabled by default. Fields cover base URL, caller identity, cache mode, anthropic base URL, route-claude-code opt-in, timeout, and per-environment overrides.
- **Vishnu workers and Vishnu LLM callers route through Bifrost when enabled.** Specifically `CloudWorker` (`mahavishnu/workers/cloud_worker.py`), the Agno adapter (`mahavishnu/engines/agno_adapter_impl.py`), the LlamaIndex adapter (`mahavishnu/adapters/llamaindex_adapter.py`), and any other Vishnu code path that constructs an OpenAI/Anthropic SDK client. When `bifrost.enabled: true`, the cloud tier (`minimax`) hits `http://127.0.0.1:8471/v1/chat/completions` with the `BifrostGatewayRequest` envelope; the local fallback tiers (`llama_server`, `ollama`) stay direct.
- **`mahavishnu/llm_gateway/` package becomes the implementation surface.** `build_gateway_envelope()` is the single entry point for constructing base URL + path + route headers + cache headers. CloudWorker and the adapters import it; nothing builds Bifrost headers ad hoc.
- **Claude Code Anthropic base URL stays direct-to-MiniMax by default** (`https://api.minimax.io/anthropic` via the `minimax-coding-plan` MCP server). A new field `bifrost.route_claude_code: bool` (default `false`) lets operators opt in to env-injecting `ANTHROPIC_BASE_URL=http://127.0.0.1:8471/anthropic` into the `terminal-claude` worker process.
- **Qwen CLI base URL stays direct by default.** A parallel field `bifrost.route_qwen_code: bool` (default `false`) opts in to env-injecting the variable named by `bifrost.qwen_env_var` (default `OPENAI_BASE_URL` — the OpenAI-compatible convention; verified in Phase D) pointing at `bifrost.base_url` into the `terminal-qwen` worker process. Each opt-in flag is independent; operators can route Claude through Bifrost without routing Qwen, or vice versa.
- **`settings/models.yaml` `bifrost:` block deleted** — replaced by `settings/mahavishnu.yaml` `bifrost:` block. `BIFROST_BASE_URL` env var deleted — replaced by `MAHAVISHNU_BIFROST__BASE_URL` pydantic-settings env-prefix override per `feedback-no-backwards-compat-pre-1.0.md`.
- **`local.yaml` opt-in**: `bifrost: { enabled: true, route_claude_code: false, route_qwen_code: false }`.
- **Integration Contract per phase** (Triggered from / Returns to / Demonstrable by / Rollback signal / Observability added) per `docs/decisions/wire-up-contract.md`.
- **E2E test asserting `caller_id` appears in Bifrost log after worker dispatch** per `docs/decisions/mcp-backend-wiring-discipline.md §3`.

**Proof it worked**:
- `grep -rn "minimax\.io/v1" mahavishnu/` returns zero hits outside `settings/models.yaml` (the canonical reference) and `mahavishnu/llm_gateway/` (which only references it for documentation).
- `grep -rn "from mahavishnu.llm_gateway" mahavishnu/` returns hits in `workers/cloud_worker.py`, `engines/agno_adapter_impl.py`, `adapters/llamaindex_adapter.py`, plus tests.
- `tail -F ~/.local/state/mcp/logs/bifrost.log | grep caller_id` shows entries within 5 seconds of any `mcp__mahavishnu__pool_route_execute` invocation that hits the cloud tier.
- `curl -s http://localhost:8680/health | jq .bifrost` shows `{enabled: true, base_url: "http://127.0.0.1:8471", caller_id: "mahavishnu", route_claude_code: false, route_qwen_code: false, qwen_env_var: "OPENAI_BASE_URL"}` in the response.
- `pytest tests/integration/test_bifrost_routing_e2e.py::test_cloud_worker_emits_caller_id` passes.

## 2. Goals

1. **First-class settings, not env-var hack.** Mount on `MahavishnuSettings` per the `pi_pool:`, `worktree_storage:`, `goal_teams:` sibling pattern. Pydantic-settings env-prefix override (`MAHAVISHNU_BIFROST__*`) for emergency override, but the source of truth is the settings block. Apply `feedback-cli-flag-consumer-wiring.md`: every instantiation site must be grepped.
2. **Single source of truth for gateway envelope construction.** `mahavishnu/llm_gateway.build_gateway_envelope()` is the only entry point. No ad-hoc header construction in workers or adapters — that way the `caller_id`, `cache_scope_key`, and route header construction cannot drift between consumers.
3. **Vishnu workers always go through Bifrost when enabled, fail loud when not.** No "best-effort" fallback to direct MiniMax when Bifrost is unreachable — the LLM call fails and the operator sees it. Per `feedback-bodai-push-is-user-controlled.md` and the project's general posture: don't silently bypass the user-configured path.
4. **Local tiers stay direct.** `llama_server` (`:8081`) and `ollama` (`:11434`) are local-only; Bifrost is not in their chain. Routing them through Bifrost would add latency to localhost calls and create a single point of failure for no benefit.
5. **AI-CLI opt-in is a per-vendor flag set.** `bifrost.route_claude_code: bool` controls env injection into `terminal-claude` (sets `ANTHROPIC_BASE_URL`); `bifrost.route_qwen_code: bool` controls env injection into `terminal-qwen` (sets `bifrost.qwen_env_var`, default `OPENAI_BASE_URL`). Both default `false`. When an operator opts in, env injection happens at worker spawn time via the existing `worker_contract.metadata.env` extension. Each flag is independent.
6. **Per-request observability.** Each dispatch logs `caller_id`, `provider`, `model`, `task_category` at INFO level; emits metrics `mahavishnu_bifrost_dispatch_total{outcome,provider,route_class}` and `mahavishnu_bifrost_dispatch_latency_seconds` (histogram). Rollback signal: error rate on a single provider climbs above 50% over 60s.
7. **Independent rollback per scope.** Setting `bifrost.enabled: false` reverts Vishnu workers; setting `bifrost.route_claude_code: false` reverts Claude Code only; setting `bifrost.route_qwen_code: false` reverts Qwen only. Each can be set independently.
8. **No backwards compatibility shims.** Pre-1.0 codebase per `feedback-no-backwards-compat-pre-1.0.md`: replace, don't extend. `BIFROST_BASE_URL` env var stops working on merge. `settings/models.yaml:bifrost` block deleted on merge.

## 3. Non-Goals

- **Routing llama-server or ollama through Bifrost.** Local providers don't need gateway caching or routing rules.
- **Cross-repo Bifrost adoption.** This spec is Mahavishnu-only. Akosha, Session-Buddy, Crackerjack, and the `minimax-coding-plan-mcp` server are out of scope; if they need Bifrost, they get their own specs.
- **Bifrost semantic cache tuning.** The `recommended_cache_mode()` helper in `mahavishnu/llm_gateway/client.py:74-96` already returns the correct policy (`OFF` for image routes; `SEMANTIC`/`DIRECT` per route class). The spec consumes it; it does not redesign it.
- **Bifrost provider additions.** The `config/bifrost/config.template.json` provider set (`minimax-openai`, `anthropic`, `openai`) is the operator's concern. The spec adds the wiring; it does not add providers.
- **Replacing the CloudWorker FallbackChain.** The three-tier chain (`minimax → llama_server → ollama`) stays. The only change is that the `minimax` tier's `base_url` is rewritten to the gateway when Bifrost is enabled.
- **Custom cache TTLs per task.** The gateway envelope defaults (`cache_ttl_seconds=300`, `cache_threshold=None`, `cache_mode=OFF`) are correct for the current deployment. Operators can override via settings later.
- **Bifrost HTTP/WebSocket transport.** Bifrost is HTTP-only; we mirror that.
- **Anthropic Messages API direct path on the worker.** The worker uses OpenAI-compatible `chat_completions`. Anthropic Messages is wired only for Claude Code's opt-in path.

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

### 4.3 CloudWorker hardcoded direct-to-MiniMax

`mahavishnu/workers/cloud_worker.py:37, 56-58, 78-106`:

```python
MINIMAX_OPENAI_BASE_URL = "https://api.minimax.io/v1"

@dataclass
class CloudWorkerConfig:
    minimax_url: str = field(
        default_factory=lambda: os.environ.get("MINIMAX_BASE_URL") or MINIMAX_OPENAI_BASE_URL
    )

def _build_fallback_chain(config):
    settings = LLMSettings(
        providers={
            "minimax": {"base_url": config.minimax_url, ...},
            "llama_server": {...},
            "ollama": {...},
        },
        fallback_chain=["minimax", "llama_server", "ollama"],   # ← no Bifrost slot
    )
```

No `BIFROST_BASE_URL` read. No Bifrost provider. No `build_gateway_envelope()` call. The chain never reaches Bifrost.

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

The `minimax-coding-plan-mcp` server is the Claude Code Anthropic transport; per CLAUDE.md, Claude Code calls `https://api.minimax.io/anthropic`. There is no `ANTHROPIC_BASE_URL` env injection for the `terminal-claude` worker today.

### 4.6 Settings mount pattern (existing precedents)

`mahavishnu/core/config.py:715-718` (`PiPoolSettings`):

```python
class PiPoolSettings(BaseModel):
    """Pi pool-specific settings (Bifrost is a similar shape)."""
    Mounted as the top-level ``pi_pool`` sibling on :class:`MahavishnuSettings`.
```

`goal_teams:`, `worktree_storage:`, `pi_pool:`, `runpod_pool:`, `caller_quota:`, `verification:`, `changepoint:`, `task_orphan_sweeper:` all follow the pattern: pydantic BaseModel, mounted as `MahavishnuSettings.<name>: <Type>`, default values that produce a working deployment when the block is absent.

## 5. Design

### 5.1 Settings schema

New class `BifrostConfig` in `mahavishnu/core/config.py`, mounted as `bifrost: BifrostConfig = BifrostConfig()` on `MahavishnuSettings`.

```python
from enum import StrEnum

class BifrostCacheMode(StrEnum):
    """Cache policy passed to Bifrost on every request envelope."""
    OFF = "off"
    DIRECT = "direct"
    SEMANTIC = "semantic"


class BifrostConfig(BaseModel):
    """First-class Bifrost gateway settings.

    When ``enabled`` is True, all Vishnu LLM callers route the cloud tier
    through the gateway at ``base_url``. The local fallback chain
    (llama_server, ollama) stays direct.

    AI-CLI worker opt-in flags control env injection at spawn time:

    - ``route_claude_code``: when True, the ``terminal-claude`` worker
      inherits ``ANTHROPIC_BASE_URL=<anthropic_base_url>`` so the Claude
      Code CLI itself routes through Bifrost's Anthropic-compatible
      endpoint.

    - ``route_qwen_code``: when True, the ``terminal-qwen`` worker
      inherits the env var named by ``qwen_env_var`` (default
      ``OPENAI_BASE_URL`` — Qwen's OpenAI-compatible transport) pointing
      at ``<base_url>`` so Qwen CLI routes through Bifrost's OpenAI-
      compatible provider.

    Each flag is independent; operators opt in per vendor. Add a sibling
    flag and base URL field for each new AI-CLI worker type registered
    in the worker_registry (currently terminal-codex, terminal-deepagents,
    terminal-clai — see follow-ups).
    """

    enabled: bool = False
    base_url: str = "http://127.0.0.1:8471"
    anthropic_base_url: str = "http://127.0.0.1:8471/anthropic"
    caller_id: str = "mahavishnu"
    cache_mode: BifrostCacheMode = BifrostCacheMode.OFF
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

Mount on `MahavishnuSettings`:

```python
class MahavishnuSettings(OneiricBaseSettings):
    # ... existing fields ...
    bifrost: BifrostConfig = BifrostConfig()
```

Pydantic-settings env-prefix: `MAHAVISHNU_BIFROST__<FIELD>` (nested delimiter `__`). Example: `MAHAVISHNU_BIFROST__ENABLED=true` in `~/.zshenv` overrides `local.yaml`.

### 5.2 `mahavishnu/llm_gateway/` consumption

`mahavishnu/llm_gateway/build_gateway_envelope()` already returns the full envelope (base URL + path + headers). The consumer code collapses to one call:

```python
# New helper in mahavishnu/llm_gateway/__init__.py or a sibling module
def build_provider_envelope(
    *,
    base_url: str,
    protocol_family: ProtocolFamily,
    model: str,
    prompt: str,
    task_label: str | None,
    settings: BifrostConfig,
) -> GatewayRequestEnvelope:
    return build_gateway_envelope(
        caller_id=settings.caller_id,
        protocol_family=protocol_family,
        model=model,
        prompt=prompt,
        task_label=task_label,
        base_url=base_url,
        cache_mode=CacheMode(settings.cache_mode),
        cache_ttl_seconds=settings.cache_ttl_seconds,
    )
```

`bifrost.enabled: False` is a no-op: callers never call the helper. `bifrost.enabled: True` rewrites the cloud provider's `base_url` and `headers` from the envelope.

### 5.3 CloudWorker integration (Vishnu-worker scope, mandatory)

`mahavishnu/workers/cloud_worker.py:_build_fallback_chain()` change:

```python
def _build_fallback_chain(config: CloudWorkerConfig, bifrost: BifrostConfig | None = None) -> FallbackChain:
    minimax_routing = routing_to_task_map(config.model_routing or DEFAULT_MINIMAX_ROUTING)

    # Resolve the cloud tier base_url: when Bifrost is enabled, route through it.
    if bifrost and bifrost.enabled:
        minimax_base_url = gateway_api_base(
            ProtocolFamily.OPENAI,
            base_url=bifrost.base_url,
        )  # → "http://127.0.0.1:8471/v1"
    else:
        minimax_base_url = config.minimax_url  # → "https://api.minimax.io/v1"

    settings = LLMSettings(
        providers={
            "minimax": {
                "name": "minimax",
                "base_url": minimax_base_url,
                "api_key": "${MINIMAX_API_KEY}",
                "require_auth": True,
                "task_routing": minimax_routing,
                "timeout_seconds": config.timeout,
            },
            "llama_server": {...},  # unchanged, always direct
            "ollama": {...},        # unchanged, always direct
        },
        fallback_chain=["minimax", "llama_server", "ollama"],
    )
    chain = FallbackChain.from_settings(settings)
    ...
```

The `start()` method takes `bifrost: BifrostConfig` from `MahavishnuSettings.get_settings()` and threads it through. **No** `BIFROST_BASE_URL` env var reads.

When `bifrost.enabled: True` and Bifrost is unreachable, the `minimax` tier fails (no silent fallback). The local tiers remain as backups.

### 5.4 Agno + LlamaIndex adapter integration (Vishnu-worker scope, mandatory)

Same pattern. The adapters construct OpenAI/Anthropic clients; they consult `MahavishnuSettings.get_settings().bifrost` and rewrite the base URL + add envelope headers when enabled.

```python
# mahavishnu/engines/agno_adapter_impl.py (sketch)
def _build_agno_client(settings: MahavishnuSettings) -> LLMProviderFactory:
    if settings.bifrost.enabled:
        envelope = build_provider_envelope(
            base_url=settings.bifrost.base_url,
            protocol_family=ProtocolFamily.OPENAI,
            model="...",
            prompt="",
            task_label=None,
            settings=settings.bifrost,
        )
        return LLMProviderFactory(base_url=envelope.api_base, headers=envelope.request_headers, ...)
    return LLMProviderFactory(base_url=config.minimax_base_url, ...)
```

LlamaIndex analog in `mahavishnu/adapters/llamaindex_adapter.py`. Both adapters add the same call; the existing `LLMProviderFactory` accepts extra headers without a signature change.

### 5.5 AI-CLI worker integration (Vishnu-worker scope, opt-in, per-vendor)

When `bifrost.enabled: True` AND the corresponding per-vendor flag is also True, the worker inherits a base-URL env var at spawn time. Two flags, two workers, two env vars:

| Flag | Worker type | Env var | Value |
|---|---|---|---|
| `bifrost.route_claude_code` | `terminal-claude` | `ANTHROPIC_BASE_URL` | `bifrost.anthropic_base_url` |
| `bifrost.route_qwen_code` | `terminal-qwen` | `bifrost.qwen_env_var` (default `OPENAI_BASE_URL`) | `bifrost.base_url` |

The injection happens in `mahavishnu/workers/contract/manager.py:launch()`:

```python
# Sketch
def _resolve_worker_env(worker_type: str, base_env: dict[str, str], settings: MahavishnuSettings) -> dict[str, str]:
    env = dict(base_env)
    if settings.bifrost.enabled:
        if worker_type == "terminal-claude" and settings.bifrost.route_claude_code:
            env["ANTHROPIC_BASE_URL"] = settings.bifrost.anthropic_base_url
        elif worker_type == "terminal-qwen" and settings.bifrost.route_qwen_code:
            env[settings.bifrost.qwen_env_var] = settings.bifrost.base_url
    return env
```

Defaults — both flags `false` — mean today's behavior is unchanged:

- Claude Code keeps calling `https://api.minimax.io/anthropic` via the `minimax-coding-plan` MCP server.
- Qwen CLI keeps calling its default endpoint (the `mahavishnu/workers/registry.py:131` `terminal-qwen` entry's `command_argv` does not inject any base URL today).

When the operator flips a flag, the worker is spawned with the env var pointing at the corresponding Bifrost endpoint. Each flag is independent: flipping `route_claude_code` does not affect Qwen workers and vice versa.

Phase D verifies the actual env var name Qwen CLI reads (the candidate `OPENAI_BASE_URL` default is the OpenAI-compatible convention; alternatives are `QWEN_BASE_URL` or `DASHSCOPE_API_BASE`). The `qwen_env_var` field exists exactly so the operator can correct it without a code change when the verification surface becomes clear.

### 5.6 Migration

**Replace, no deprecation** per `feedback-no-backwards-compat-pre-1.0.md`:

| Old | New | Action |
|---|---|---|
| `settings/models.yaml:bifrost:` block | `settings/mahavishnu.yaml:bifrost:` block (plus `local.yaml` opt-in) | Delete `models.yaml` block in same PR. |
| `BIFROST_BASE_URL` env var | `MAHAVISHNU_BIFROST__BASE_URL` env-prefix | Stop reading `BIFROST_BASE_URL` in same PR. |
| `MINIMAX_BASE_URL` env var (currently the only way to redirect minimax tier away from `https://api.minimax.io/v1`) | Same — keep as an explicit redirect for direct mode. When Bifrost is enabled, `MINIMAX_BASE_URL` is ignored in favor of the gateway URL. | Document precedence. |

### 5.7 Observability

Per-request log line at INFO level:

```
bifrost_dispatch caller_id=mahavishnu provider=minimax-openai model=MiniMax-M3
              route_class=default cache_mode=off duration_ms=432 outcome=success
```

Metrics (registered in `mahavishnu/core/metrics.py`):

- `mahavishnu_bifrost_dispatch_total{outcome,provider,route_class}` (counter)
- `mahavishnu_bifrost_dispatch_latency_seconds{provider,route_class}` (histogram)
- `mahavishnu_bifrost_dispatch_failures_total{provider,reason}` (counter)

Health surface (`mcp__mahavishnu__get_health` and `/health`) exposes `bifrost.enabled` and `bifrost.base_url` so operators can verify the live configuration.

### 5.9 Integration Contract

Per `docs/decisions/wire-up-contract.md`:

**Triggered from**:
1. `mcp__mahavishnu__pool_route_execute(prompt)` (worker dispatch)
2. `mcp__mahavishnu__trigger_workflow(adapter, task_type)` (workflow execution)
3. `CloudWorker.execute(task)` (terminal-claude terminal-qwen spawn)
4. Agno and LlamaIndex adapter `invoke()` / `chat()` calls
5. `mahavishnu/workers/contract/manager.py:launch()` for `terminal-claude` (when `route_claude_code: true`) and `terminal-qwen` (when `route_qwen_code: true`)

**Returns to / updates**:
1. LLM SDK receives a response (success or failure) — same surface as today
2. `WorkerResult.metadata.provider` is `bifrost` when Bifrost routed the call (distinct from `minimax-openai`)
3. `Session-Buddy reflection` carries `bifrost: true/false` in metadata
4. `terminal-claude` subprocess inherits `ANTHROPIC_BASE_URL` env when `route_claude_code: true`; `terminal-qwen` subprocess inherits `bifrost.qwen_env_var` (default `OPENAI_BASE_URL`) env when `route_qwen_code: true`
5. `/health` and `mcp__mahavishnu__get_health` reflect `bifrost: {enabled, base_url, route_claude_code, route_qwen_code, qwen_env_var, caller_id}`

**Demonstrable by**:
1. `grep -rn "from mahavishnu.llm_gateway" mahavishnu/ --include="*.py" | grep -v test_` returns hits in `workers/cloud_worker.py`, `engines/agno_adapter_impl.py`, `adapters/llamaindex_adapter.py`.
2. `tail -F ~/.local/state/mcp/logs/bifrost.log | grep caller_id=mahavishnu` shows entries within 5 seconds of `pool_route_execute` invocations against the cloud tier.
3. `pytest tests/integration/test_bifrost_routing_e2e.py` — see §6.2.
4. `curl -s http://localhost:8680/health | jq .bifrost` returns the config block.
5. `mahavishnu metrics bifrost --source auto --output table` shows non-zero `dispatch_total` after a worker run.

**Rollback signal**:
- Per `mcp-backend-wiring-discipline.md`: Bifrost-dependent dispatch error rate (5xx from gateway + provider errors within 60s window) exceeds 50% triggers an alert.
- Manual rollback: `bifrost: { enabled: false }` in `settings/local.yaml` + restart. Reverts to direct-to-MiniMax immediately.
- `MAHAVISHNU_BIFROST__ENABLED=false` env override is the emergency knob.

**Observability added**:
1. Per-request INFO log with `caller_id`, `provider`, `model`, `route_class`, `cache_mode`, `outcome`, `duration_ms`
2. `mahavishnu_bifrost_dispatch_total{outcome,provider,route_class}` counter
3. `mahavishnu_bifrost_dispatch_latency_seconds{provider,route_class}` histogram
4. `mahavishnu_bifrost_dispatch_failures_total{provider,reason}` counter
5. `/health.bifrost` sub-shape returned by `mcp__mahavishnu__get_health` and `GET /health`

### 5.10 Phases

Per `wire-up-contract.md`:

**Phase A — settings schema and `mahavishnu/llm_gateway` consumption helper (Phase 1 wiring)**

- Files: `mahavishnu/core/config.py` (new `BifrostConfig`, mount on `MahavishnuSettings`); `mahavishnu/llm_gateway/__init__.py` (export `build_provider_envelope`); `settings/mahavishnu.yaml` (add `bifrost:` block with defaults); `settings/local.yaml` (add `bifrost: { enabled: true }` opt-in).
- Tests: `tests/unit/test_config.py::TestBifrostConfigSchema` (defaults, env-prefix overrides, validation).
- Demonstrable: `mahavishnu settings dump | jq .bifrost` shows expected shape; `MAHAVISHNU_BIFROST__ENABLED=true` overrides local.yaml.
- Rollback: revert the config mount — no production behavior change because consumers don't call it yet.

**Phase B — CloudWorker integration (Phase 2 wiring, Vishnu-worker mandatory scope)**

- Files: `mahavishnu/workers/cloud_worker.py` (thread `bifrost` through `_build_fallback_chain`); `mahavishnu/pools/mahavishnu_pool.py` (pass settings to worker init).
- Tests: `tests/unit/test_cloud_worker.py::test_bifrost_enabled_rewrites_minimax_base_url`; `tests/unit/test_cloud_worker.py::test_bifrost_disabled_uses_direct_url`; `tests/unit/test_cloud_worker.py::test_bifrost_unreachable_fails_loud`.
- Demonstrable: with `bifrost.enabled: true` in `local.yaml`, dispatch a prompt via `mcp__mahavishnu__pool_route_execute` and observe `caller_id=mahavishnu` entry in `bifrost.log` within 5 seconds.
- Rollback: `bifrost.enabled: false` reverts to direct-to-MiniMax.

**Phase C — Agno and LlamaIndex adapter integration**

- Files: `mahavishnu/engines/agno_adapter_impl.py`; `mahavishnu/adapters/llamaindex_adapter.py`.
- Tests: `tests/unit/test_agno_adapter.py::test_bifrost_enabled_routes_through_gateway`; `tests/unit/test_llamaindex_adapter.py::test_bifrost_disabled_uses_direct_url`.
- Demonstrable: invoke an Agno workflow via `mcp__mahavishnu__trigger_workflow(adapter="agno", ...)` and observe `caller_id=mahavishnu` in `bifrost.log`.

**Phase D — AI-CLI worker Anthropic/OpenAI base URL opt-in (per vendor)**

- Files: `mahavishnu/workers/contract/manager.py` (env injection for both Claude and Qwen); `mahavishnu/workers/registry.py` (no signature change); `settings/mahavishnu.yaml` (document `route_claude_code: false` and `route_qwen_code: false` defaults).
- Tests: `tests/unit/test_worker_contract.py::test_claude_code_inherits_anthropic_base_url_when_route_claude_code_true`; `tests/unit/test_worker_contract.py::test_claude_code_default_anthropic_base_url_unchanged`; `tests/unit/test_worker_contract.py::test_qwen_code_inherits_qwen_env_var_when_route_qwen_code_true`; `tests/unit/test_worker_contract.py::test_qwen_code_default_qwen_env_var_unchanged`; `tests/unit/test_worker_contract.py::test_qwen_env_var_field_override` (verifying `qwen_env_var` setting is honored when set to a non-default name).
- Demonstrable:
  - With `route_claude_code: true` in `local.yaml`, launch a `terminal-claude` worker and `printenv ANTHROPIC_BASE_URL` from inside the worker's tmux session — should be `http://127.0.0.1:8471/anthropic`. Without the flag, `ANTHROPIC_BASE_URL` is unset (Claude Code reads `MINIMAX_API_HOST` via `minimax-coding-plan-mcp`).
  - With `route_qwen_code: true` in `local.yaml`, launch a `terminal-qwen` worker and `printenv OPENAI_BASE_URL` (or whatever `qwen_env_var` is set to) — should be `http://127.0.0.1:8471`. Without the flag, the env var is unset. **Phase D verifies the actual Qwen CLI env-var name** via the Qwen CLI docs or `--help` output; the `qwen_env_var` setting field exists exactly so this is a one-line config change when the actual name is discovered.

**Phase E — Observability and e2e tests**

- Files: `mahavishnu/core/metrics.py` (register counters/histogram); `mahavishnu/core/health_aggregator.py` (include `bifrost` feed state); `tests/integration/test_bifrost_routing_e2e.py` (new — asserts `caller_id` appears in `bifrost.log` after `pool_route_execute`); `tests/integration/test_bifrost_health_e2e.py` (new — asserts `/health.bifrost` shape).
- Demonstrable: `mahavishnu metrics bifrost` returns non-zero counters after one dispatch; `crackerjack run -v` green.

**Phase F — Migration cleanup (replace-not-extend)**

- Files: `settings/models.yaml` (delete `bifrost:` block at lines 103-107); `mahavishnu/workers/cloud_worker.py` (delete `os.environ.get("BIFROST_BASE_URL")` reads — none exist yet but verify); remove `BIFROST_BASE_URL` references in any docs.
- Tests: `grep -rn BIFROST_BASE_URL .` returns zero hits; `grep -rn "bifrost:" settings/models.yaml` returns zero hits.
- Demonstrable: docs CI / pre-commit grep check.

## 6. Tests

### 6.1 Unit tests (per-phase)

| Test | Phase | Asserts |
|---|---|---|
| `TestBifrostConfigSchema::test_defaults` | A | All defaults match §5.1 |
| `TestBifrostConfigSchema::test_env_prefix_override` | A | `MAHAVISHNU_BIFROST__ENABLED=true` overrides yaml |
| `TestBifrostConfigSchema::test_validation_rejects_invalid_cache_mode` | A | `BifrostCacheMode` enum enforced |
| `TestCloudWorkerBifrost::test_enabled_rewrites_minimax_base_url` | B | CloudWorker constructs provider with gateway URL when enabled |
| `TestCloudWorkerBifrost::test_disabled_uses_direct_url` | B | CloudWorker constructs provider with `https://api.minimax.io/v1` when disabled |
| `TestCloudWorkerBifrost::test_unreachable_fails_loud` | B | `minimax` tier raises on gateway 5xx (no silent fallback) |
| `TestCloudWorkerBifrost::test_local_tiers_unaffected_by_bifrost` | B | `llama_server` and `ollama` URLs unchanged |
| `TestAgnoAdapterBifrost::test_enabled_routes_through_gateway` | C | Same envelope constructed |
| `TestLlamaIndexAdapterBifrost::test_enabled_routes_through_gateway` | C | Same envelope constructed |
| `TestWorkerContractBifrost::test_claude_code_inherits_anthropic_base_url` | D | `ANTHROPIC_BASE_URL` injected when `route_claude_code: true` |
| `TestWorkerContractBifrost::test_claude_code_default_unchanged` | D | `ANTHROPIC_BASE_URL` absent when `route_claude_code: false` |
| `TestWorkerContractBifrost::test_qwen_code_inherits_qwen_env_var` | D | `qwen_env_var` (default `OPENAI_BASE_URL`) injected when `route_qwen_code: true` |
| `TestWorkerContractBifrost::test_qwen_code_default_unchanged` | D | `qwen_env_var` absent when `route_qwen_code: false` |
| `TestWorkerContractBifrost::test_qwen_env_var_field_override` | D | Custom `qwen_env_var` setting name is honored |
| `TestMigration::test_no_bifrost_block_in_models_yaml` | F | `settings/models.yaml` no longer has `bifrost:` block |

### 6.2 Integration tests (`tests/integration/`)

| Test | Asserts |
|---|---|
| `test_bifrost_routing_e2e` | After `pool_route_execute(prompt)`, `bifrost.log` contains a `caller_id=mahavishnu` line within 5 seconds. |
| `test_bifrost_dispatch_metrics_e2e` | `mahavishnu metrics bifrost --source auto` shows non-zero `dispatch_total` and a populated `dispatch_latency_seconds` histogram after one dispatch. |
| `test_bifrost_health_e2e` | `GET /health` JSON includes a `bifrost` block with `enabled`, `base_url`, `caller_id`, `route_claude_code`. |
| `test_bifrost_disabled_direct_path_e2e` | With `bifrost.enabled: false`, `pool_route_execute(prompt)` reaches `https://api.minimax.io/v1` directly (asserted via mock or via Bifrost log absence). |

### 6.3 Regression coverage

- Existing `tests/unit/test_cloud_worker.py` (full suite) must continue to pass with `bifrost.enabled: false` (default).
- `pytest tests/integration/test_llm_gateway_*.py` continues to cover `build_gateway_envelope()` correctness.
- `crackerjack run -v -f` clean per `feedback-crackerjack-merge-gate-is-vf.md`.

## 7. Open Questions

1. **Should `route_claude_code` also toggle Claude Code's MCP transport?** The `minimax-coding-plan-mcp` server's `MINIMAX_API_HOST` could be rewired to `http://127.0.0.1:8471/anthropic` when `route_claude_code: true`. The spec currently scopes `route_claude_code` to the worker-process env injection only. **Decision: defer to a separate spec** for MCP server config — the env injection alone gives operators the runtime control without coupling `~/.mcp.json` to `settings/mahavishnu.yaml`. Tracked as a follow-up.
2. **Multi-region Bifrost?** Out of scope per `docs/decisions/`; one `base_url` per deployment. Multiple Bifrost instances would require a list field; not needed today.
3. **Bifrost auth.** The config has `auth_env: str = "BIFROST_API_KEY"` but today's gateway is auth-less (the `.mcp.json` access is by network locality). Defaulting the env var name is forward-compat; no code reads it until the gateway enforces auth. Tracked as a follow-up.
4. **What env var does the Qwen CLI actually read for a custom base URL?** The `qwen_env_var: str = "OPENAI_BASE_URL"` default is the OpenAI-compatible convention. Candidates are `QWEN_BASE_URL`, `OPENAI_BASE_URL`, and `DASHSCOPE_API_BASE`. Phase D verifies the actual name via Qwen CLI docs / `--help` output and updates `settings/mahavishnu.yaml` to override the default if needed. The settings-side field exists so this becomes a config change, not a code change.

## 8. Acceptance criteria

The design ships when:

1. All six phases land in one PR (or stacked PRs gated per phase) — see §5.10.
2. `tests/integration/test_bifrost_routing_e2e.py` passes.
3. `mahavishnu metrics bifrost` returns non-zero counters after one dispatch against the cloud tier with `bifrost.enabled: true`.
4. `crackerjack run -v -f` clean.
5. `settings/models.yaml:bifrost` block deleted; `grep -rn BIFROST_BASE_URL .` returns zero hits.
6. `local.yaml` ships `bifrost: { enabled: true, route_claude_code: false }`.
7. `git log` shows Phase commits in order with Integration Contract blocks per `wire-up-contract.md`.
8. `/health.bifrost` returns the expected shape per §5.9.

## 9. Follow-ups (out of scope)

- Rewire `~/.mcp.json:minimax-coding-plan-mcp`'s `MINIMAX_API_HOST` when `route_claude_code: true` (separate spec).
- Extend the per-vendor opt-in pattern to `terminal-codex`, `terminal-deepagents`, and `terminal-clai` workers (each needs its own `route_<vendor>_code: bool` flag and base-URL field).
- `BIFROST_API_KEY` token sourcing when the gateway enables auth.
- Mahavishnu-side retry/circuit-breaker wrapping the gateway call (separate decision — currently inherits from `FallbackChain` semantics).
- Cross-component Bifrost adoption (Akosha, Session-Buddy, Crackerjack) — separate specs per component.
- Bifrost semantic cache rollout once an embedding strategy is configured (today `recommended_cache_mode()` returns `DIRECT` per `mahavishnu/llm_gateway/client.py:74-96`).