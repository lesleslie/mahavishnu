# LLM Routing Standardization — Design Spec
**Date:** 2026-05-16
**Status:** Approved
**Scope:** crackerjack, session-buddy, mahavishnu, akosha, dhara (all Bodai components)

---

## 1. Background and Motivation

Anthropic's June 15, 2026 billing change moves `claude -p` and the Agent SDK to a separate programmatic credit pool ($20–$200/mo, non-rollover). This makes subscription-based LLM usage untenable for programmatic Bodai services. The goal is to standardize all components on API-plan-only providers with a well-defined three-tier fallback chain.

MiniMax's Token Plan (March 23, 2026) provides a single API key covering all modalities (text, image, audio, video) and explicitly allows concurrent Claude Code + API usage, making it the correct primary cloud provider.

---

## 2. Provider Hierarchy

| Tier | Provider | Base URL | Model (text) | Purpose |
|------|----------|----------|--------------|---------|
| 1 (primary) | MiniMax | `https://api.minimax.io/v1` | `MiniMax-M2.7` | Quality cloud tasks |
| 1 (fast) | MiniMax | `https://api.minimax.io/v1` | `MiniMax-M2.7-highspeed` | SWARM, QUICK, background |
| 2 (secondary local) | llama-server | `http://localhost:8081/v1` | `Qwen3-8B-8.2B-Q4_K_M` | Privacy, latency, cost |
| 3 (tertiary local) | ollama | `http://localhost:11434/v1` | `qwen2.5-coder:7b` | Last-resort fallback |

**Key constraint:** llama-server runs on port **8081**, ollama on **11434**. These are separate processes and must not be conflated in configuration.

---

## 3. Architecture

### 3.1 Shared LLM Layer Location

The shared adapter and routing logic lives in **Oneiric** (`oneiric/llm/`). This is semantically correct: LLM providers are adapters, and Oneiric owns the adapter system, lifecycle management, and runtime orchestration for all Bodai components.

**mcp-common** holds only pure DTOs (`LLMMessage`, `LLMUsage`, `LLMResponse`) — no business logic.

### 3.2 Module Structure

```
oneiric/llm/
├── base.py           # LLMAdapter ABC + UnsupportedModalityError
├── openai_compat.py  # OpenAICompatAdapter (covers all three tiers)
├── hailuo.py         # HailuoAdapter (MiniMax video, async polling)
├── chain.py          # LLMProviderChain with circuit breaker + fallback
└── config.py         # LLMTierConfig, LLMChainConfig (Pydantic)

mcp_common/llm/
└── models.py         # LLMMessage, LLMUsage, LLMResponse DTOs
```

### 3.3 Two-Level Routing Hierarchy

Mahavishnu maintains two complementary routing layers that operate at different abstraction levels:

- **Mahavishnu `task_router.py`** (semantic/content layer): `classify_task(prompt)` → `TaskCategory` → model variant selection. Operates on prompt content.
- **Bifrost** (operational/traffic layer): CEL expression rules on `x-bf-task` header → model variant + semantic cache. Operates on HTTP traffic. Optional via `BIFROST_BASE_URL` env var.

These layers are not redundant — they solve different problems and compose cleanly.

---

## 4. Components

### 4.1 `LLMAdapter` (base.py)

```python
class LLMAdapter(ABC):
    supported_modalities: frozenset[TaskCategory] = frozenset()

    @abstractmethod
    async def complete(self, messages, *, category, timeout, stream) -> LLMResponse: ...
    async def stream(self, messages, *, category, timeout) -> AsyncIterator[str]: ...

    def supports(self, category: TaskCategory) -> bool:
        return category in self.supported_modalities
```

### 4.2 `OpenAICompatAdapter` (openai_compat.py)

Single implementation covering all three tiers via configurable `base_url` and `model`. Supports: CODE_GENERATION, CODE_REVIEW, DEBUGGING, REFACTORING, DOCUMENTATION, TESTING, REASONING, CREATIVE, ANALYSIS, EMBEDDING, GENERAL, SWARM, QUICK, ML_INFERENCE, AGENT_LOOP, IMAGE_UNDERSTANDING, AUDIO_SPEECH, AUDIO_TRANSCRIPTION.

Does **not** support: IMAGE_GENERATION, VIDEO_GENERATION (these require HailuoAdapter or provider-specific endpoints).

### 4.3 `HailuoAdapter` (hailuo.py)

Async polling adapter for MiniMax Hailuo video generation. POST job → poll GET status until complete or timeout. Not OpenAI-compatible. Supports: VIDEO_GENERATION only.

### 4.4 `LLMProviderChain` (chain.py)

```python
class LLMProviderChain:
    async def complete(self, messages, *, category, timeout=30.0) -> LLMResponse:
        for tier in self._tiers_for(category):
            if self._circuit_open(tier):
                continue
            try:
                resp = await asyncio.wait_for(tier.complete(...), timeout)
                if resp.content:
                    self._reset_circuit(tier)
                    return resp
                # empty → treat as failure
            except asyncio.CancelledError:
                raise  # never swallow
            except Exception:
                self._record_failure(tier)
        raise AllTiersExhausted(...)
```

**Circuit breaker**: N consecutive failures (default 5) → 60s cooldown per tier.

**Retry policy**: 3 attempts with exponential backoff (1s, 2s, 4s) within a single tier before advancing to next.

**Streaming**: `chain.stream()` tries tiers in order; first successful stream is returned without buffering the full response.

### 4.5 `LLMChainConfig` (config.py)

YAML-driven, loaded via Oneiric's layered config system:

```yaml
# settings/models.yaml
providers:
  minimax:
    base_url: "https://api.minimax.io/v1"
    api_key_env: "MINIMAX_API_KEY"
  llama_server:
    base_url: "http://localhost:8081/v1"
    api_key_env: "LLAMA_SERVER_API_KEY"
  ollama:
    base_url: "http://localhost:11434/v1"
    api_key_env: null

task_tiers:
  default: [minimax, llama_server, ollama]
  quick: [minimax_highspeed, llama_server, ollama]
  image_generation: [minimax_hailuo]
  video_generation: [minimax_hailuo]
  audio: [minimax_audio, ollama]
```

---

## 5. Extended TaskCategory Enum

New variants added to `oneiric/llm/categories.py`:

```python
class TaskCategory(StrEnum):
    # ... existing 14 categories ...
    IMAGE_GENERATION    = "image_generation"
    IMAGE_UNDERSTANDING = "image_understanding"  # replaces VISION
    AUDIO_SPEECH        = "audio_speech"
    AUDIO_TRANSCRIPTION = "audio_transcription"
    VIDEO_GENERATION    = "video_generation"
```

**Multimodal model routing:**

| Category | MiniMax model | llama-server | ollama |
|----------|--------------|--------------|--------|
| IMAGE_GENERATION | MiniMax-Image-01 | ✗ | llava:7b |
| IMAGE_UNDERSTANDING | MiniMax-VL-01 | llava (if available) | llava:7b |
| AUDIO_SPEECH | MiniMax-Speech-02 | ✗ | ✗ |
| AUDIO_TRANSCRIPTION | MiniMax-Speech-02-Turbo | whisper.cpp if local | ✗ |
| VIDEO_GENERATION | MiniMax-Video-01 (Hailuo) | ✗ | ✗ |

---

## 6. Data Flow

```
prompt
  │
  ▼
classify_task()  ──────────────────────────────►  TaskCategory
  │
  ▼
LLMProviderChain._tiers_for(category)
  │
  ├── Tier 1: MiniMax (OpenAICompatAdapter, base_url=minimax)
  │   └── Timeout: 30s │ Circuit: 5 failures / 60s cooldown
  │
  ├── Tier 2: llama-server :8081 (OpenAICompatAdapter, base_url=llama_server)
  │   └── Timeout: 60s │ Circuit: 5 failures / 60s cooldown
  │
  └── Tier 3: ollama :11434 (OpenAICompatAdapter, base_url=ollama)
      └── Timeout: 120s │ Circuit: 5 failures / 60s cooldown
  │
  ▼
LLMResponse(content, provider, model, usage, latency_ms)
```

**Bifrost overlay** (Phase 2, optional): When `BIFROST_BASE_URL` is set, Tier 1 requests are routed through Bifrost at `http://127.0.0.1:8471`. Bifrost adds semantic caching (5m TTL, Redis Stack port 6380) and CEL-based model variant selection. Tiers 2 and 3 bypass Bifrost.

---

## 7. Error Handling and Edge Cases

| Edge Case | Handling | Priority |
|-----------|----------|----------|
| Tier timeout | `asyncio.wait_for` per tier, advance to next | P0 |
| Circuit breaker | N failures → 60s skip, logged as WARN | P0 |
| Retry with backoff | 3 attempts (1s/2s/4s) within tier | P0 |
| `asyncio.CancelledError` | Never caught — always propagates | P0 |
| Empty response | Treated as failure, advance to next tier | P1 |
| Streaming fallback | Try tiers in order; first stream wins | P1 |
| Modality not supported | `UnsupportedModalityError` if no tier supports | P1 |
| Malformed JSON from provider | Log DEBUG, count as failure | P2 |
| Token limit exceeded | Log WARN with usage info, do not retry | P2 |

---

## 8. Per-Repository Migration

### 8.1 Oneiric
- **Add**: `oneiric/llm/` module (base, openai_compat, hailuo, chain, config)
- **Add**: `TaskCategory` enum (extended)
- **Add**: `classify_task()` core logic (Mahavishnu keeps its own overlay for Mahavishnu-specific categories)

### 8.2 mcp-common
- **Add**: `mcp_common/llm/models.py` — LLMMessage, LLMUsage, LLMResponse DTOs

### 8.3 crackerjack
- **Remove**: `adapters/ai/claude.py`, `adapters/ai/qwen.py`, `adapters/ai/minimax.py`, `adapters/ai/ollama.py`
- **Remove**: `adapters/ai/registry.py` ProviderChain (replace with Oneiric's)
- **Keep**: Security validation logic from `adapters/ai/base.py` — move to crackerjack's own code fixer layer
- **Change**: `ai_provider: "minimax"` (was `"claude"`) in `config/settings.py`
- **Change**: `ai_providers: ["minimax", "llama_server", "ollama"]`
- **Add dep**: `oneiric>=0.3.x`

### 8.4 session-buddy
- **Remove**: `llm/providers/anthropic_provider.py`, `llm/providers/gemini_provider.py`
- **Keep**: `llm/providers/openai_provider.py` as reference (superseded by Oneiric's adapter)
- **Add dep**: `oneiric>=0.3.x` (currently missing from pyproject.toml)
- **Verify**: `default_provider = "minimax"` already set in settings.py ✓

### 8.5 akosha
- **Add dep**: `mcp-common>=0.13.x` (currently missing from pyproject.toml)
- **Remove**: try/except MCPBaseSettings fallback in `akosha/config.py`
- **Add**: Oneiric LLMProviderChain for any LLM calls

### 8.6 mahavishnu
- **Update**: `mahavishnu/workers/task_router.py` — extend TaskCategory, align model names
- **Update**: `settings/models.yaml` — restructure to new `providers` + `task_tiers` schema, split llama-server (8081) from ollama (11434)
- **Remove**: `mahavishnu/workers/cloud_worker.py` and `mahavishnu/workers/ollama_worker.py` (replaced by Oneiric chain)
- **Update**: Bifrost config — add audio/video route rules, re-enable image route
- **Bifrost Phase 2**: Reactivate via LaunchAgent after three-tier chain is stable

### 8.7 dhara
- Dhara has no direct LLM usage — no changes required

---

## 9. Testing Strategy

### 9.1 Unit Tests (no external services)
- `tests/unit/test_llm_classify.py` — parametrized classify_task() including empty prompt, new modality categories
- `tests/unit/test_llm_chain.py` — mocked tiers: fallback on failure, circuit breaker opens after N failures, CancelledError propagates, empty response advances chain
- `tests/unit/test_modality_routing.py` — UnsupportedModalityError from OpenAICompatAdapter, video routed to HailuoAdapter
- `@given(st.text(max_size=5000))` Hypothesis test: classify_task() never raises

### 9.2 Integration Tests (require live services, `BODAI_INTEGRATION_TESTS=1`)
- `@pytest.mark.requires_ollama` — live ollama tier smoke test
- `@pytest.mark.requires_llama_server` — live llama-server tier smoke test
- `conftest.py` auto-skips if port is not reachable

### 9.3 Per-Repo Test Additions

| Repo | New test files |
|------|---------------|
| oneiric | `test_llm_chain.py`, `test_llm_classify.py`, `test_modality_routing.py`, `test_local_tiers.py` |
| crackerjack | `test_ai_registry_migration.py` (parity check) |
| session-buddy | `test_provider_migration.py` |
| mahavishnu | extend `test_task_router.py` for new TaskCategory variants |

---

## 10. Bifrost Phase 2 (Deferred)

Bifrost stays **optional** via `BIFROST_BASE_URL` env var until three-tier chain is stable end-to-end. No code change required to make Bifrost optional — the env var gate already exists in `mahavishnu/llm_gateway/client.py`.

When ready to activate:
1. Add audio/video CEL route rules to `config/bifrost/config.template.json`
2. Re-enable image route rule (already drafted, currently disabled)
3. Restore LaunchAgent via `docs/bifrost-reactivation-runbook.md`
4. Set `BIFROST_BASE_URL=http://127.0.0.1:8471` in local environment

---

## 11. Dependency Corrections Required (Pre-Migration)

Before implementation begins:

| Repo | Action |
|------|--------|
| session-buddy | Add `oneiric>=0.3.x` to `pyproject.toml` |
| akosha | Add `mcp-common>=0.13.x` to `pyproject.toml` |
| akosha | Remove try/except MCPBaseSettings fallback in `config.py` |
| mahavishnu | Confirm llama-server configured at port 8081 in all settings files |
