# LLM Provider Reconfiguration Plan v2 (Reviewed)

**Date**: 2026-04-13
**Status**: Reviewed — ready for implementation
**Replaces**: `peppy-cooking-graham.md` plan (superseded)

______________________________________________________________________

## Executive Summary

This plan reconfigures the Bodai Ecosystem's LLM provider system across 4 repositories (Mahavishnu, Crackerjack, Session-Buddy, mcp-common) to:

1. **Use ZAI GLM models as primary cloud provider** via coding plan subscription
1. **Keep Ollama as local fallback** (GPT4All dropped)
1. **Keep Bifrost gateway as optional** cross-client caching layer (not routing)
1. **Make all LLM defaults YAML-configurable** with clear provider names
1. **Consolidate duplicated LLM code** into `mcp_common/llm/`
1. **Use free GLM models** when subscription credits run out

### What Changed from v1

| v1 Assumption | v2 Reality |
|---------------|-----------|
| GPT4All replaces Ollama | **Dropped — keeping Ollama** |
| GLM-5-turbo best for swarms | glm-4.5-air is better (no thinking overhead, 5x cheaper) |
| Bifrost needed for routing | Bifrost optional — only for cross-client caching |
| Qwen env vars for ZAI config | New YAML-driven config with clear provider names |
| OpenAI as fallback | Keep as emergency fallback only |

______________________________________________________________________

## 1. ZAI API Landscape

### Three API Endpoints

| Endpoint | Purpose | Notes |
|----------|---------|-------|
| `https://api.z.ai/api/anthropic` | **Claude Code integration** | Anthropic-compatible API for Claude Code, OpenClaw, etc. |
| `https://api.z.ai/api/coding/paas/v4` | **Coding plan subscription** | OpenAI-compatible. Verified working with subscription key. |
| `https://open.bigmodel.cn/api/paas/v4` | Pay-per-use API | **Do not use** — empty balance, separate credit pool |

### Thinking Mode Is Optional

ZAI's documentation confirms that thinking/reasoning is **opt-in, not automatic**. It's controlled via:

```python
extra_body={"thinking": {"type": "enabled"}}
```

My earlier tests showed reasoning tokens because the coding plan endpoint may enable thinking by default. The Anthropic-compatible endpoint (`/api/anthropic`) used by Claude Code may behave differently. This means the "thinking overhead" cost concern is less severe than initially estimated — thinking can be disabled for routine tasks.

### Verified Model Availability (Coding Plan)

All tested against `https://api.z.ai/api/coding/paas/v4` on 2026-04-13:

#### Subscription Models (Working)

| Model | Thinking-capable? | Input $/MTok | Output $/MTok | Cached $/MTok | Best For |
|-------|-------------------|-------------|--------------|--------------|----------|
| **glm-5** | Yes | $1.00 | $3.20 | $0.20 | 5th-gen flagship — balanced quality/concurrency |
| **glm-5.1** | Yes | $1.40 | $4.40 | $0.26 | **Opus tier** — ZAI recommended for Claude Code Opus |
| **glm-5.1** | Yes | $1.40 | $4.40 | $0.26 | Complex reasoning, architecture |
| **glm-5-turbo** | Yes | $1.20 | $4.00 | $0.24 | Fast 5th-gen |
| **glm-4.7** | Yes | $0.60 | $2.20 | $0.11 | **Sonnet tier** — SWE-bench 73.8%, ZAI recommended |
| **glm-4.6** | Yes | $0.60 | $2.20 | $0.11 | New flagship reasoning |
| **glm-4.5** | No (always) | $0.60 | $2.20 | $0.11 | General tasks, no reasoning overhead |
| **glm-4.5-air** | No (always) | $0.20 | $1.10 | $0.03 | **Haiku tier / Swarms** — ZAI recommended, cheapest paid |
| **GLM-4.5V** | No | $0.60 | $1.80 | $0.11 | Vision tasks |
| **GLM-4.6V** | Yes | $0.30 | $0.90 | $0.05 | Newer vision |

#### Free Models (No Credits Needed)

| Model | Notes |
|-------|-------|
| **glm-4.7-flash** | Free, good quality — swarm workers when credits run out |
| **glm-4.5-flash** | Free alternative |
| **glm-4.6v-flash** | Free vision (currently overloaded — popular) |

#### NOT in Coding Plan

| Model | Reason |
|-------|--------|
| glm-4.7-flashx | Separate paid tier ($0.07/$0.40) — not covered |
| glm-4.5-x | Separate paid tier ($2.20/$8.90) — premium |
| glm-4.5-airx | Separate paid tier ($1.10/$4.50) — premium |
| glm-5v-turbo | Not in current subscription plan |

______________________________________________________________________

## 2. Task-to-Model Mapping

### ZAI Official Tier Mapping (for Claude Code)

Per ZAI documentation, the intended mapping for Claude Code tiers:

| Tier | ZAI Model | Price | Role |
|------|----------|-------|------|
| **Opus** | `glm-5.1` | $1.40/$4.40 | Complex architecture, multi-file reasoning |
| **Sonnet** | `glm-4.7` | $0.60/$2.20 | Daily coding, code generation, editing |
| **Haiku** | `glm-4.5-air` | $0.20/$1.10 | Quick tasks, classification, summaries |

### Ecosystem Task Routing (for Mahavishnu/Crackerjack/Session-Buddy)

| Task Category | Primary Model | Fallback (subscription) | Fallback (free) | Local |
|---------------|--------------|------------------------|-----------------|-------|
| Complex reasoning | glm-5.1 | glm-4.7 | glm-4.7-flash | llama3:8b |
| Code generation | glm-4.7 | glm-4.5 | glm-4.7-flash | qwen2.5-coder:7b |
| Code review | glm-4.7 | glm-4.5 | glm-4.7-flash | qwen2.5-coder:7b |
| Debugging | glm-4.7 | glm-4.5 | glm-4.7-flash | qwen2.5-coder:7b |
| General chat | glm-4.5 | glm-4.5-air | glm-4.5-flash | llama3:8b |
| Analysis | glm-4.5 | glm-4.5-air | glm-4.7-flash | llama3:8b |
| Swarm workers | glm-4.5-air | glm-4.7-flash | N/A | qwen2.5-coder:7b |
| Documentation | glm-4.5-air | glm-4.5-flash | N/A | llama3:8b |
| Vision | GLM-4.5V | GLM-4.6V | glm-4.6v-flash | N/A |
| Quick/simple | glm-4.5-air | glm-4.7-flash | N/A | llama3:8b |

### Why These Choices

- **glm-5.1 for Opus/reasoning**: ZAI's recommended Opus-tier model. Best reasoning quality in the lineup.
- **glm-4.7 for code/Sonnet**: ZAI's own recommendation. SWE-bench 73.8%. Thinking is optional — disable for routine edits, enable for complex debugging.
- **glm-4.5-air for Haiku/swarms**: ZAI's own recommendation for Haiku. $0.20/$1.10, never produces reasoning tokens, cheapest subscription model.
- **glm-4.7-flash for free fallback**: Zero cost, good quality, high concurrency.
- **Ollama for offline**: No API dependency, privacy for sensitive code.

______________________________________________________________________

## 3. Seven LLM Selection Scenarios

### Scenario 1: Crackerjack AI Code Fixing

**Where**: `crackerjack/adapters/ai/` (qwen.py, claude.py, ollama.py)
**Trigger**: User runs `crackerjack run` with AI fix enabled
**Current**: Defaults to `claude`, falls back to `qwen`, then `ollama`
**Problem**: ProviderID hardcoded as `Literal["claude", "qwen", "ollama"]`. QwenCodeFixer abuses env var names when targeting ZAI.

**Proposed**:

- Provider enum becomes config-driven from `settings/ai.yaml`
- Default chain: `zai → ollama`
- Rename `QwenCodeFixer` to `ZAICodeFixer` (or generic `OpenAICompatFixer`)
- Settings: `base_url`, `api_key`, `model`, `provider_chain` all from YAML

### Scenario 2: Mahavishnu Worker Task Execution

**Where**: `mahavishnu/workers/ollama.py`
**Trigger**: Pool spawns workers to execute tasks
**Current**: OllamaWorker uses Ollama-specific HTTP API (`/api/chat`, `/api/generate`)
**Problem**: Cannot swap to cloud provider — different API format

**Proposed**:

- New `CloudWorker` class using OpenAI-compatible API (handles ZAI, Qwen, OpenAI)
- Keep `OllamaWorker` for local execution only
- Extract shared task routing logic into `TaskRouter` utility (both workers use it)
- `WorkerFactory` selects worker type based on task routing
- Config in `settings/models.yaml`

### Scenario 3: Mahavishnu Agno Agent Teams

**Where**: `mahavishnu/engines/agno_adapter_impl.py`, `settings/agno_teams/*.yaml`
**Trigger**: Multi-agent team execution (code review, etc.)
**Current**: Team YAMLs hardcode `claude-sonnet-4-6`
**Problem**: Claude not available without subscription

**Proposed**:

- Add `zai` case to `LLMProviderFactory` using Agno's `OpenAIChat` with ZAI base URL
- Factory must pass `base_url="https://api.z.ai/api/coding/paas/v4"` and `api_key`
- Update team YAMLs to use GLM model IDs
- Default: `zai` provider with `glm-4.7` model
- Fallback: `ollama` with `qwen2.5-coder:7b`

### Scenario 4: Session-Buddy LLM Features

**Where**: `session_buddy/llm_providers.py`
**Trigger**: Reflection generation, conversation summarization, intent detection
**Current**: Fallback chain: `openai → anthropic → gemini → ollama`
**Problem**: Defaults to OpenAI/Anthropic which cost money or aren't configured

**Proposed**:

- Default chain: `zai → ollama`
- ZAI provider uses coding plan endpoint
- Ollama for offline/privacy-sensitive operations
- Use `mcp_common.llm` shared module

### Scenario 5: Bifrost Cross-Client Caching

**Where**: `config/bifrost/config.template.json`, `mahavishnu/llm_gateway/`
**Trigger**: Clients opt in via `BIFROST_BASE_URL` env var
**Current**: Paused (LaunchAgents removed 2026-04-09)
**Problem**: Config has wrong ZAI API path (`/api/paas/v4/` instead of `/api/coding/paas/v4/`)

**Proposed**:

- Fix API path in Bifrost config template
- Update model lists with verified available models
- Keep as optional — activated via env vars only
- Document reactivation procedure

### Scenario 6: mcp-common Shared LLM Module

**Where**: New `mcp_common/llm/` package
**Trigger**: Any component needs LLM access
**Current**: Duplicated OpenAI client creation in 5+ places across 3 repos
**Problem**: Different defaults, inconsistent error handling, duplicated code

**Proposed**:

- Single `OpenAICompatibleProvider` class for ZAI/Qwen/OpenAI
- Shared configuration loading from YAML
- Built-in prompt caching (ZAI native cache)
- Circuit breaker and fallback logic
- All repos import from mcp-common

### Scenario 7: Direct CLI Usage

**Where**: Claude Code, OpenClaw, Nanobot, terminal sessions
**Trigger**: User invokes AI tools directly
**Current**: Each client has its own LLM configuration
**Problem**: No cross-client caching without Bifrost

**Proposed**:

- Claude Code uses ZAI's Anthropic-compatible endpoint (`/api/anthropic`)
- OpenClaw and Nanobot can optionally route through Bifrost
- Terminal workers (Mahavishnu) use `settings/models.yaml`

______________________________________________________________________

## 4. Bifrost Configuration Fix

### Current Bug

The `zai-openai` provider in `config/bifrost/config.template.json` points to:

```json
"chat_completion": "/api/paas/v4/chat/completions"
```

This hits the pay-per-use credit pool (empty balance). Must be:

```json
"chat_completion": "/api/coding/paas/v4/chat/completions"
```

### Model List Update

Update routing rules and datasheets:

| Route | Current | Updated |
|-------|---------|---------|
| `think` | `anthropic/GLM-4.7` | `zai-openai/glm-5.1` |
| `long_context` | `anthropic/GLM-4.7` | `zai-openai/glm-4.5` (200K context) |
| `web_search` | `anthropic/GLM-4.7` | `zai-openai/glm-4.7` |
| `image` | `anthropic/GLM-4.5V` | `zai-openai/GLM-4.5V` |
| `background` | `anthropic/GLM-4.5-Air` | `zai-openai/glm-4.5-air` |
| `cheap` | `anthropic/GLM-4.5-Air` | `zai-openai/glm-4.5-air` |

### Reactivation

No code changes needed. When ready to reactivate:

1. Fix the config template path
1. Run `scripts/bifrost-ctl rebootstrap`
1. Set `BIFROST_BASE_URL=http://127.0.0.1:8471` in client environments

______________________________________________________________________

## 5. mcp-common LLM Consolidation

### New Package: `mcp_common/llm/`

```
mcp_common/llm/
├── __init__.py              # Public API
├── provider.py              # OpenAICompatibleProvider (ZAI, Qwen, OpenAI)
├── config.py                # YAML-driven provider configuration
├── fallback.py              # Fallback chain with circuit breaker
├── cache.py                 # Prompt cache (ZAI native — defer semantic cache)
├── exceptions.py            # LLM-specific exceptions
└── types.py                 # Shared types (TaskType, ModelInfo, etc.)
```

### Core Design

```python
# mcp_common/llm/config.py
from pydantic import BaseModel, SecretStr, model_validator

class ProviderConfig(BaseModel):
    """YAML-driven provider configuration."""
    name: str                          # "zai", "qwen", "openai", "ollama"
    enabled: bool = True
    base_url: str
    api_key: SecretStr = SecretStr("") # From env var — always SecretStr
    models: dict[str, str]            # task_type → model_id mapping
    priority: int = 1                  # Lower = preferred
    timeout: int = 30
    max_retries: int = 2

    @model_validator(mode="after")
    def resolve_env_vars(self) -> "ProviderConfig":
        """Resolve ${ENV_VAR} patterns in api_key and base_url."""
        ...

class LLMSettings(BaseModel):
    """Loaded from settings/models.yaml or equivalent."""
    providers: dict[str, ProviderConfig]
    default_provider: str = "zai"
    fallback_chain: list[str] = ["zai", "ollama"]
    free_tier_provider: str = "zai-free"
```

```python
# mcp_common/llm/provider.py
class OpenAICompatibleProvider:
    """Single provider for ZAI, Qwen, OpenAI — all use same API."""

    def __init__(self, config: ProviderConfig):
        # Lazy import — openai is an optional dependency
        import openai

        self._config = config
        self._client = openai.AsyncOpenAI(
            api_key=config.api_key.get_secret_value(),
            base_url=config.base_url,
            max_retries=config.max_retries,
        )

    async def execute(self, task: dict) -> dict:
        """Execute a chat completion request."""
        response = await self._client.chat.completions.create(
            model=task["model"],
            messages=task["messages"],
            max_tokens=task.get("max_tokens", 4096),
            temperature=task.get("temperature", 0.7),
        )
        return {
            "content": response.choices[0].message.content,
            "provider": self._config.name,
            "model": task["model"],
            "usage": response.usage.model_dump() if response.usage else {},
        }

    async def health_check(self) -> bool:
        """Lightweight health check."""
        ...
```

```python
# mcp_common/llm/fallback.py
class FallbackChain:
    """Ordered provider list with circuit breaker."""

    def __init__(self, providers: list[OpenAICompatibleProvider]):
        self._providers = providers
        self._circuit_breakers: dict[str, CircuitBreaker] = {
            p.name: CircuitBreaker(
                failure_threshold=5,     # [Review finding #8]
                reset_timeout=60,        # 60s before retry
                half_open_probes=1,      # Single probe before full reopen
            )
            for p in providers
        }

    async def execute(self, task: dict) -> dict:
        """Try providers in order, fall back on failure."""
        last_error = None
        for provider in self._providers:
            if not self._circuit_breakers[provider.name].is_open:
                try:
                    result = await provider.execute(task)
                    self._circuit_breakers[provider.name].record_success()
                    return result
                except Exception as e:
                    last_error = e   # [Review finding #2 — preserve error chain]
                    logger.warning("Provider %s failed: %s", provider.name, e, exc_info=True)
                    self._circuit_breakers[provider.name].record_failure()
        raise AllProvidersExhaustedError(
            f"All {len(self._providers)} providers failed"
        ) from last_error  # [Review finding #2 — chain the last error]
```

### Dependency: Optional, Not Core

`openai` is an **optional** dependency of mcp-common. Following the existing pattern in `pyproject.toml`:

```toml
[project.optional-dependencies]
llm = [
    "openai>=1.0.0",
]
all = [
    "mcp-common[all-prompts,dev,treesitter,llm]",
]
```

The provider module lazy-imports `openai` and raises a clear `ImportError` if not installed. This preserves mcp-common's zero-network-dependency philosophy.

### Migration Path

For each repo:

1. Add `mcp-common[llm]>=0.10.0` dependency
1. Replace inline `openai.AsyncOpenAI(...)` calls with `from mcp_common.llm import LLMSettings, FallbackChain`
1. Remove repo-specific provider configuration code
1. Point to shared `settings/models.yaml` or `settings/llm.yaml`

______________________________________________________________________

## 6. Repository-Specific Changes

### 6.1 Crackerjack

**Files to modify**:

| File | Change |
|------|--------|
| `crackerjack/config/settings.py` | Replace `Literal["claude", "qwen", "ollama"]` with `str` + runtime validation against YAML providers |
| `crackerjack/adapters/ai/registry.py` | Add `ZAI` to `ProviderID` enum, load from config |
| `crackerjack/adapters/ai/qwen.py` | Keep as generic OpenAI-compatible fixer (rename later) |
| `crackerjack/adapters/ai/claude.py` | Keep for Bifrost/subscription users, but not default |

**New default settings** (`settings/ai.yaml`):

```yaml
providers:
  zai:
    enabled: true
    base_url: "https://api.z.ai/api/coding/paas/v4"
    api_key: "${ZAI_API_KEY}"
    model: "glm-4.7"
    priority: 1

  ollama:
    enabled: true
    base_url: "http://localhost:11434/v1"
    api_key: "ollama"
    model: "qwen2.5-coder:7b"
    priority: 2

default_provider: "zai"
fallback_chain: ["zai", "ollama"]
```

### 6.2 Mahavishnu

**Files to create**:

| File | Purpose |
|------|---------|
| `mahavishnu/workers/cloud_worker.py` | OpenAI-compatible worker for ZAI/Qwen/OpenAI |
| `mahavishnu/workers/task_router.py` | Shared task classification + model selection logic |

**Files to modify**:

| File | Change |
|------|--------|
| `settings/models.yaml` | Add ZAI provider config, update task routing |
| `mahavishnu/engines/agno_adapter_impl.py` | Add `zai` case to LLMProviderFactory with `base_url` kwarg |
| `settings/agno_teams/*.yaml` | Replace `claude-sonnet-4-6` with GLM model IDs |
| `mahavishnu/workers/ollama.py` | Extract shared routing into `task_router.py` |
| `config/bifrost/config.template.json` | Fix API path, update models |

**Updated `settings/models.yaml`**:

```yaml
# Cloud providers (priority order)
zai:
  enabled: true
  base_url: "https://api.z.ai/api/coding/paas/v4"
  api_key: "${ZAI_API_KEY}"
  priority: 1
  task_routing:
    CODE_GENERATION: "glm-4.7"
    CODE_REVIEW: "glm-4.7"
    DEBUGGING: "glm-4.7"
    REFACTORING: "glm-4.7"
    TESTING: "glm-4.7"
    REASONING: "glm-5.1"
    GENERAL: "glm-4.5"
    ANALYSIS: "glm-4.5"
    DOCUMENTATION: "glm-4.5-air"
    SWARM: "glm-4.5-air"
    SWARM_FREE: "glm-4.7-flash"
    VISION: "GLM-4.5V"
    QUICK: "glm-4.5-air"
  fallback:
    subscription_exhausted: "glm-4.7-flash"

# Local provider
ollama:
  enabled: true
  base_url: "http://localhost:11434"
  priority: 2
  task_routing:
    CODE_GENERATION: "qwen2.5-coder:7b"
    REASONING: "llama3:8b"
    GENERAL: "qwen2.5-coder:7b"

# Optional Bifrost gateway (activated via env vars)
bifrost:
  enabled: false
  base_url: "http://127.0.0.1:8471"
  activate_env: "BIFROST_BASE_URL"

# Future provider (easy to add)
qwen:
  enabled: false
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  api_key: "${QWEN_API_KEY}"
  task_routing:
    CODE_GENERATION: "qwen-coder-plus"
    GENERAL: "qwen-plus"
```

### 6.3 Session-Buddy

**Files to modify**:

| File | Change |
|------|--------|
| `session_buddy/llm_providers.py` | Default chain: `zai → ollama`, import from `mcp_common.llm` |

### 6.4 Bifrost Config

**File**: `config/bifrost/config.template.json`

Changes:

1. Fix zai-openai provider `request_path_overrides` from `/api/paas/v4/` to `/api/coding/paas/v4/`
1. Add new models to datasheets: `glm-5`, `glm-5-turbo`, `glm-4.6`, `glm-4.5-flash`
1. Update governance routing to use `zai-openai/` namespace
1. Remove model references not in coding plan (glm-4.7-flashx, glm-4.5-x)

______________________________________________________________________

## 7. Implementation Phases

### Phase 1: Config Foundation + Agno Factory (Days 1-2)

**Goal**: Get the right API endpoint and models configured. Make Agno recognize ZAI.

1. Add `ZAI` to `LLMProvider` enum in Agno adapter
1. Add `zai` case to `LLMProviderFactory` with ZAI base_url and api_key kwargs
1. Fix Bifrost config template API path
1. Update `settings/models.yaml` with ZAI provider and task routing
1. Update Agno team YAMLs with GLM model IDs
1. Verify ZAI API access from each component

**Validation**: Agno teams can use `glm-4.7` through the coding plan endpoint.

### Phase 2: mcp-common LLM Module (Days 3-5)

**Goal**: Create shared LLM infrastructure in mcp-common.

1. Create `mcp_common/llm/` package with provider, config, fallback, exceptions, types modules
1. Implement `OpenAICompatibleProvider` (handles ZAI, Qwen, OpenAI) with lazy import
1. Implement `FallbackChain` with circuit breaker (threshold=5, reset=60s, chained errors)
1. Implement `LLMSettings` with YAML loading, env var resolution, `SecretStr` for keys
1. Add `[llm]` optional dependency group to pyproject.toml
1. Write tests with mocked API responses
1. Publish mcp-common v0.10.0

**Validation**: Unit tests pass, provider can make real API calls when key is available.

### Phase 3: Crackerjack Integration (Days 6-7)

**Goal**: Make Crackerjack's AI config intuitive and YAML-driven.

1. Create `settings/ai.yaml` with provider configuration
1. Update `AISettings` — change `ai_provider` type from `Literal` to `str` with runtime validation against YAML
1. Add `ZAI` to `ProviderID` enum
1. Update `ProviderFactory` to create ZAI provider from config
1. Default chain: `zai → ollama`
1. Test `crackerjack run` with ZAI provider

**Validation**: `crackerjack run --ai-fix` works with ZAI GLM-4.7.

### Phase 4: Mahavishnu Integration (Days 8-10)

**Goal**: Add cloud worker support and update all LLM touchpoints.

1. Extract shared task routing logic from `OllamaWorker` into `TaskRouter` utility
1. Create `CloudWorker` class (OpenAI-compatible, for ZAI/Qwen/OpenAI) using `TaskRouter`
1. Update pool routing to prefer cloud workers for complex tasks
1. Update WebSocket monitoring for cloud worker events
1. Test swarm execution with `glm-4.5-air`

**Validation**: Pool can spawn both Ollama and cloud workers, routes correctly.

### Phase 5: Session-Buddy Migration (Days 11-12)

**Goal**: Switch Session-Buddy to shared mcp-common LLM module.

1. Replace inline provider creation with `mcp_common.llm` imports
1. Update default fallback chain to `zai → ollama`
1. Test reflection generation, conversation summarization

**Validation**: Session-Buddy LLM features work with ZAI provider.

### Phase 6: Testing and Documentation (Days 13-14)

**Goal**: Comprehensive testing and documentation.

1. Integration tests across all repos
1. Fallback chain validation (ZAI down → Ollama works)
1. Free tier fallback (credits exhausted → glm-4.7-flash works)
1. Bifrost reactivation test (optional)
1. Update CLAUDE.md in all repos
1. Create migration guide for future provider additions (e.g., Qwen)

______________________________________________________________________

## 8. Configuration Reference

### Environment Variables

| Variable | Purpose | Required |
|----------|---------|----------|
| `ZAI_API_KEY` | ZAI coding plan subscription key | Yes |
| `OLLAMA_BASE_URL` | Ollama server URL (default: `http://localhost:11434`) | No |
| `BIFROST_BASE_URL` | Enable Bifrost gateway (e.g., `http://127.0.0.1:8471`) | No |
| `QWEN_API_KEY` | Future: Qwen API key (Alibaba) | No |
| `OPENAI_API_KEY` | Emergency fallback only | No |

### Key Principle: No More Abuse of Env Var Names

The old pattern of setting `QWEN_API_KEY` to a ZAI key and `BIFROST_OPENAI_BASE_URL` to ZAI's endpoint is replaced with clear YAML config:

```yaml
# OLD (confusing):
# QWEN_API_KEY=<zai-key>
# QWEN_BASE_URL=https://api.z.ai/api/coding/paas/v4

# NEW (clear):
# settings/models.yaml
zai:
  api_key: "${ZAI_API_KEY}"
  base_url: "https://api.z.ai/api/coding/paas/v4"
```

______________________________________________________________________

## 9. Cost Analysis

### Monthly Token Budget Estimate

Assuming moderate usage (50 coding tasks/day, 10 swarm tasks/day):

| Component | Model | Est. Tokens/Day | Daily Cost | Monthly Cost |
|-----------|-------|----------------|------------|--------------|
| Crackerjack fixes | glm-4.7 | 50k input + 10k output | ~$0.05 | ~$1.50 |
| Agno teams | glm-4.5 | 30k input + 15k output | ~$0.05 | ~$1.50 |
| Swarm workers (10/day) | glm-4.5-air | 100k input + 50k output | ~$0.08 | ~$2.40 |
| Session-Buddy LLM | glm-4.5-air | 20k input + 10k output | ~$0.02 | ~$0.60 |
| Reasoning tasks (5/day) | glm-5.1 | 50k input + 10k output | ~$0.11 | ~$3.30 |
| **Total** | | | **~$0.31** | **~$9.30** |

**With ZAI native prompt caching** (80% cached input discount): ~$5-6/month.

**Free tier fallback** (glm-4.7-flash): $0 when credits exhausted.

### Why This Is Lower Than the v2 Draft

The v2 draft estimated $14/month because it assumed all thinking models always produce reasoning tokens. Context7 revealed that thinking is **opt-in** (`extra_body={"thinking": {"type": "enabled"}}`). For routine API calls without thinking enabled, models like glm-4.7 produce output directly without reasoning overhead.

______________________________________________________________________

## 10. Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|-----------|
| ZAI API downtime | All cloud LLM stops | Automatic fallback to Ollama via circuit breaker |
| Credits exhausted mid-cycle | Paid models stop | Automatic fallback to glm-4.7-flash (free) |
| Thinking enabled unexpectedly | Token cost spike | Explicit opt-in for thinking in config; default off |
| Bifrost config drift | Cache misses | Pin config version, validate on startup |
| Ollama not running | Local fallback fails | Health check with graceful error message |
| Wrong API endpoint | Balance errors | Config validation rejects non-coding-plan URLs |
| Prompt cache cross-session leak | Data exposure | Cache keyed by session/namespace identifier |

______________________________________________________________________

## 11. Future Providers

### Adding Qwen (Alibaba Cloud)

When Qwen API tokens are available:

1. Add to `settings/models.yaml`:

```yaml
qwen:
  enabled: true
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  api_key: "${QWEN_API_KEY}"
  task_routing:
    CODE_GENERATION: "qwen-coder-plus"
    GENERAL: "qwen-plus"
```

2. No code changes needed — `OpenAICompatibleProvider` handles Qwen's OpenAI-compatible API.

### Adding OpenAI as Fallback

Already supported — just add to fallback chain:

```yaml
openai:
  enabled: true
  api_key: "${OPENAI_API_KEY}"
  task_routing:
    fallback: "gpt-4.1-mini"
```

______________________________________________________________________

## Appendix A: Review Findings Incorporated

This section documents all findings from the three-agent review and how they were addressed.

### Architecture Review

| # | Finding | Severity | Resolution |
|---|---------|----------|-----------|
| 1 | `openai` dep breaks mcp-common philosophy | CRITICAL | Made optional via `mcp-common[llm]` dependency group |
| 2 | FallbackChain silently swallows exceptions | CRITICAL | Added logging + error chaining (`raise ... from last_error`) |
| 3 | `api_key: str` leaks secrets | CRITICAL | Changed to `SecretStr` in `ProviderConfig` |
| 4 | CloudWorker duplicates OllamaWorker routing | IMPORTANT | Extract shared `TaskRouter` utility |
| 5 | Agno factory needs explicit `base_url` | IMPORTANT | Specified exact factory method with `base_url` kwarg |
| 6 | ProviderID Literal annotations break | IMPORTANT | Change to `str` + runtime validation |
| 7 | Phase 1 Agno changes will fail | SUGGESTION | Moved enum+factory changes into Phase 1 |
| 8 | Circuit breaker params undefined | SUGGESTION | Defined: threshold=5, reset=60s, half-open probes=1 |
| 9 | `cache.py` not designed | SUGGESTION | Deferred semantic cache; leverage ZAI native caching |

### Security Review

| # | Finding | Severity | Resolution |
|---|---------|----------|-----------|
| 1 | Bifrost config.db stores resolved keys | CRITICAL | Document as security boundary; restrict file permissions |
| 2 | Prompt cache cross-session leakage | HIGH | Cache must be keyed by session/namespace |
| 3 | Env var cascade creates implicit trust | MEDIUM | One explicit env var per provider |
| 4 | No input validation on task dicts | MEDIUM | Add Pydantic model validation |
| 5 | Cloud-to-local fallback data path | MEDIUM | Document as a feature (data stays local) |

### Cost-Performance Review

| # | Finding | Severity | Resolution |
|---|---------|----------|-----------|
| 1 | glm-4.5-air vs glm-4.7-flash for swarms | IMPORTANT | Threshold: \<10 workers free, >=10 workers paid |
| 2 | Sonnet thinking overhead expensive | IMPORTANT | ZAI recommends glm-4.7; thinking is opt-in (Context7) |
| 3 | $14/month estimate too optimistic | IMPORTANT | Revised to $8/month with opt-in thinking |
| 4 | Prompt caching underleveraged | IMPORTANT | Standardize system prompts per task type |
| 5 | glm-4.6 deserves a task role | SUGGESTION | Listed as option; test vs glm-4.7 for code |

______________________________________________________________________

## Appendix B: Thinking vs Non-Thinking Model Cheat Sheet

**Thinking-capable models** (reasoning available via `extra_body={"thinking": {"type": "enabled"}}`):

- glm-5, glm-5.1, glm-5-turbo, glm-4.7, glm-4.6
- Enable thinking for: Complex reasoning, multi-step debugging, architecture decisions
- Disable thinking for: Routine edits, formatting, simple Q&A

**Non-thinking models** (no reasoning capability):

- glm-4.5, glm-4.5-air, GLM-4.5V
- Always use for: Swarm workers, bulk operations, documentation, quick queries

**Free models** (no credits needed):

- glm-4.7-flash, glm-4.5-flash
- Use for: Swarm workers when credits exhausted, low-stakes tasks

## Appendix C: Files Touched Summary

### New Files (8)

1. `mcp_common/llm/__init__.py`
1. `mcp_common/llm/provider.py`
1. `mcp_common/llm/config.py`
1. `mcp_common/llm/fallback.py`
1. `mcp_common/llm/cache.py`
1. `mcp_common/llm/exceptions.py`
1. `mcp_common/llm/types.py`
1. `mahavishnu/workers/task_router.py`

### Modified Files (12)

1. `mahavishnu/settings/models.yaml` — Add ZAI provider config
1. `mahavishnu/config/bifrost/config.template.json` — Fix API path
1. `mahavishnu/mahavishnu/engines/agno_adapter_impl.py` — Add ZAI case
1. `mahavishnu/settings/agno_teams/*.yaml` — Replace Claude model IDs
1. `crackerjack/crackerjack/config/settings.py` — Dynamic provider config
1. `crackerjack/crackerjack/adapters/ai/registry.py` — Add ZAI to ProviderID
1. `crackerjack/settings/ai.yaml` — New provider config file
1. `session_buddy/session_buddy/llm_providers.py` — Use mcp-common module
1. `mcp-common/pyproject.toml` — Add `[llm]` optional dependency group
1. `mahavishnu/mahavishnu/workers/ollama.py` — Extract shared routing
1. `mahavishnu/CLAUDE.md` — Update LLM configuration section
1. `crackerjack/CLAUDE.md` — Update AI provider section
