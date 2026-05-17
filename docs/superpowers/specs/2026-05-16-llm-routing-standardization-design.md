# LLM Routing Standardization — Design Spec

**Date:** 2026-05-16
**Status:** Approved (rev 2 — post multi-agent review)
**Scope:** crackerjack, session-buddy, mahavishnu, akosha, dhara (all Bodai components)

______________________________________________________________________

## 1. Background and Motivation

Anthropic's June 15, 2026 billing change moves `claude -p` and the Agent SDK to a separate programmatic credit pool ($20–$200/mo, non-rollover). This makes subscription-based LLM usage untenable for programmatic Bodai services. The goal is to standardize all components on API-plan-only providers with a well-defined three-tier fallback chain.

MiniMax's Token Plan (March 23, 2026) provides a single API key covering all modalities (text, image, audio, video) and explicitly allows concurrent Claude Code + API usage, making it the correct primary cloud provider.

______________________________________________________________________

## 2. Provider Hierarchy

| Tier | Provider | Base URL | Model (text) | Purpose |
|------|----------|----------|--------------|---------|
| 1 (primary) | MiniMax | `https://api.minimax.io/v1` | `MiniMax-M2.7` | Quality cloud tasks |
| 1 (fast) | MiniMax | `https://api.minimax.io/v1` | `MiniMax-M2.7-highspeed` | SWARM, QUICK, background |
| 2 (secondary local) | llama-server | `http://localhost:8081/v1` | `Qwen3-8B-8.2B-Q4_K_M` | Privacy, latency, cost |
| 3 (tertiary local) | ollama | `http://localhost:11434/v1` | `qwen2.5-coder:7b` | Last-resort fallback |

**Key constraint:** llama-server runs on port **8081**, ollama on **11434**. These are separate processes and must not be conflated in configuration. Both services must bind to `127.0.0.1` (not `0.0.0.0`) — document this explicitly in the deployment runbook.

______________________________________________________________________

## 3. Architecture

### 3.1 Shared LLM Layer Location

The shared adapter and routing logic lives in **Oneiric** (`oneiric/llm/`). This is semantically correct: LLM providers are adapters, and Oneiric owns the adapter system, lifecycle management, and runtime orchestration for all Bodai components.

**DTO placement (corrected from rev 1):** `LLMMessage`, `LLMUsage`, and `LLMResponse` DTOs live in **Oneiric** (`oneiric/llm/models.py`), not mcp-common. Reason: mcp-common already depends on `oneiric>=0.3.6`; placing DTOs in mcp-common and importing them from Oneiric would create a dependency cycle. mcp-common may re-export the Oneiric DTOs for convenience.

### 3.2 Module Structure

```
oneiric/llm/
├── models.py         # LLMMessage, LLMUsage, LLMResponse DTOs  ← moved here
├── base.py           # LLMAdapter ABC + UnsupportedModalityError + security hooks
├── openai_compat.py  # OpenAICompatAdapter (covers all three tiers)
├── hailuo.py         # HailuoAdapter (MiniMax video, async polling)
├── chain.py          # LLMProviderChain with circuit breaker + fallback
└── config.py         # LLMTierConfig, LLMChainConfig (Pydantic)

mcp_common/llm/
└── __init__.py       # Re-exports oneiric.llm.models (LLMMessage, LLMUsage, LLMResponse)
```

### 3.3 Two-Level Routing Hierarchy

Mahavishnu maintains two complementary routing layers that operate at different abstraction levels:

- **Mahavishnu `task_router.py`** (semantic/content layer): `classify_task(prompt)` → `TaskCategory` → model variant selection. Operates on prompt content. Its output is passed as the `x-bf-task` header when Bifrost is active.
- **Bifrost** (operational/traffic layer): CEL expression rules on `x-bf-task` header → semantic cache lookup + load-aware routing. Operates on HTTP traffic. Optional via `BIFROST_BASE_URL` env var.

**Authority contract:** `task_router.py` determines the task category and model variant. Bifrost's CEL rules use `x-bf-task` to make operational decisions (cache, load balancing, priority queuing) — they do not override the model variant selected by task_router. This ensures task_router remains the single authoritative source of model selection when Bifrost is active.

______________________________________________________________________

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

    # Security hooks — called by LLMProviderChain, not subclasses
    def sanitize_input(self, messages: list[LLMMessage]) -> list[LLMMessage]: ...
    def sanitize_error(self, error: str) -> str: ...
    def validate_output(self, content: str) -> tuple[bool, str]: ...
```

**Security hooks** are defined on the base class and called by `LLMProviderChain` (not by individual adapters):

- `sanitize_input` — strips prompt injection patterns before any tier call (preserves the logic from `crackerjack/adapters/ai/base.py:_sanitize_prompt_input`)
- `sanitize_error` — strips paths, API keys (`sk-[a-zA-Z0-9]{20,}` — note: fix stray space in existing regex), secrets before logging or raising
- `validate_output` — for code-fixing callers: dangerous pattern detection + AST security scan (preserves `_validate_ai_generated_code` from crackerjack). Optional — callers that don't need code validation skip this hook.

These hooks apply uniformly to **all** consumers (crackerjack, session-buddy, akosha, mahavishnu) — not just crackerjack.

### 4.2 `OpenAICompatAdapter` (openai_compat.py)

Single implementation covering all three tiers via configurable `base_url` and `model`. Supports: CODE_GENERATION, CODE_REVIEW, DEBUGGING, REFACTORING, DOCUMENTATION, TESTING, REASONING, CREATIVE, ANALYSIS, EMBEDDING, GENERAL, SWARM, QUICK, ML_INFERENCE, AGENT_LOOP, IMAGE_UNDERSTANDING, AUDIO_SPEECH, AUDIO_TRANSCRIPTION.

Does **not** support: IMAGE_GENERATION, VIDEO_GENERATION (these require HailuoAdapter or provider-specific endpoints).

**Streaming requirement:** Always use `/v1/chat/completions` endpoint — never `/api/chat` (ollama's native non-SSE endpoint). Older ollama versions may omit the final `data: [DONE]` SSE frame; the `stream()` implementation must not await it and must instead rely on `finish_reason` or connection close to detect end of stream.

### 4.3 `HailuoAdapter` (hailuo.py)

Async polling adapter for MiniMax Hailuo video generation. Supports: VIDEO_GENERATION only.

**SSRF constraints (mandatory):**

- Poll URL is constructed from a fixed base (`https://api.minimax.io/v1/video_generation/{job_id}`) — never from a URL returned in the job-submit response
- HTTP redirects disabled on all poll requests
- Hard cap: 60 poll iterations, 300s wall-clock maximum
- Response body size bounded before deserialization (max 1MB for status responses, configurable max for video artifact)
- No `Authorization` header on artifact download URLs (pre-signed URLs only)

### 4.4 `LLMProviderChain` (chain.py)

**Corrected pseudocode** (retry loop now explicitly composed within tier iteration):

```python
class LLMProviderChain:
    async def complete(self, messages, *, category, timeout=None) -> LLMResponse:
        messages = self._security.sanitize_input(messages)

        for tier in self._tiers_for(category):
            if self._circuit_open(tier):
                continue
            tier_timeout = tier.config.timeout_seconds  # from LLMTierConfig, not call arg

            for attempt in range(tier.config.max_attempts):  # default 3
                try:
                    resp = await asyncio.wait_for(
                        tier.complete(messages, category=category),
                        timeout=tier_timeout,
                    )
                    if resp.content:
                        self._reset_circuit(tier)
                        return resp
                    # empty → count as failure, retry
                except asyncio.CancelledError:
                    raise  # never swallow
                except Exception as e:
                    sanitized = self._security.sanitize_error(str(e))
                    logger.warning("Tier %s attempt %d failed: %s", tier.name, attempt, sanitized)
                    if attempt < tier.config.max_attempts - 1:
                        await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s
                        continue

                self._record_failure(tier)  # counts per tier-call (all retries exhausted)
                break

        raise AllTiersExhausted(sanitized_summary)
```

**Circuit breaker:** Failure unit is **per tier-call** (after all retries for that tier are exhausted), not per attempt. N=5 consecutive tier-call failures → 60s cooldown.

**Caller-level timeout:** The optional `timeout` parameter on `complete()` is an outer deadline wrapping the entire chain (all tiers). Tier-level timeouts come from `LLMTierConfig.timeout_seconds` (30s/60s/120s). The outer deadline, if set, preempts tier timeouts via `asyncio.wait_for` wrapping the full chain call — it is never used as the per-tier timeout.

**Error sanitization:** All exception messages pass through `sanitize_error` before logging or inclusion in `AllTiersExhausted`. Provider SDK exceptions frequently embed the `Authorization` header value; this must be stripped before surfacing.

**API key fail-closed:** At chain initialization, any tier with `api_key_env` set must validate the env var is present and non-empty. If missing, the tier is removed from the chain and a startup WARNING is logged — the chain does not silently advance to local tiers at request time, which would mask misconfiguration. `api_key_env: null` (ollama) guarantees no `Authorization` header is sent.

### 4.5 `LLMChainConfig` (config.py)

YAML-driven, loaded via Oneiric's layered config system. The `providers` block must define all named keys used in `task_tiers`, including model-variant sub-entries:

```yaml
# settings/models.yaml
providers:
  minimax:
    base_url: "https://api.minimax.io/v1"
    api_key_env: "MINIMAX_API_KEY"
    model: "MiniMax-M2.7"
    timeout_seconds: 30
  minimax_highspeed:
    base_url: "https://api.minimax.io/v1"
    api_key_env: "MINIMAX_API_KEY"
    model: "MiniMax-M2.7-highspeed"
    timeout_seconds: 15
  minimax_hailuo:
    base_url: "https://api.minimax.io/v1"
    api_key_env: "MINIMAX_API_KEY"
    model: "MiniMax-Video-01"
    timeout_seconds: 300  # async polling max
  llama_server:
    base_url: "http://localhost:8081/v1"
    api_key_env: "LLAMA_SERVER_API_KEY"
    model: "Qwen3-8B-8.2B-Q4_K_M"
    timeout_seconds: 60
  ollama:
    base_url: "http://localhost:11434/v1"
    api_key_env: null
    model: "qwen2.5-coder:7b"
    timeout_seconds: 120

task_tiers:
  default: [minimax, llama_server, ollama]
  quick: [minimax_highspeed, llama_server, ollama]
  image_generation: [minimax_hailuo]
  video_generation: [minimax_hailuo]
  audio: [minimax_audio, ollama]
```

**YAML schema migration:** The existing `settings/models.yaml` uses top-level provider names with nested `task_routing:` dicts keyed by uppercase string enum names (e.g. `VISION`). The new schema is a **breaking change**. `LLMChainConfig` must include a Pydantic `model_validator` that accepts both the old shape (for backward compat during transition) and the new shape, with a deprecation warning on old-format load.

______________________________________________________________________

## 5. Extended TaskCategory Enum

New variants added to `oneiric/llm/categories.py`. **`VISION` is retained as a deprecated alias** for one release cycle to avoid breaking 18+ call sites across mahavishnu, ollama worker, models.yaml, and test files before they can be migrated:

```python
class TaskCategory(StrEnum):
    # ... existing 14 categories (unchanged) ...
    VISION              = "vision"              # DEPRECATED — alias for IMAGE_UNDERSTANDING
    IMAGE_GENERATION    = "image_generation"
    IMAGE_UNDERSTANDING = "image_understanding"
    AUDIO_SPEECH        = "audio_speech"
    AUDIO_TRANSCRIPTION = "audio_transcription"
    VIDEO_GENERATION    = "video_generation"
```

`classify_task()` maps `VISION` detections to `IMAGE_UNDERSTANDING` internally. Callers using `TaskCategory.VISION` continue to work but receive a deprecation warning. The following files require explicit migration (grep target: `TaskCategory.VISION`, `"VISION"`, `task_category == "vision"`):

- `mahavishnu/workers/task_router.py` (lines 107, 182, 228, 248, 279)
- `mahavishnu/workers/ollama.py` (lines 63, 134, 212, 275)
- `settings/models.yaml` (lines 36, 59 — string key `VISION`)
- `tests/unit/test_task_router_and_auth.py` (11 assertions)
- `tests/unit/test_ollama_worker.py`

**Multimodal model routing:**

| Category | MiniMax model | llama-server | ollama |
|----------|--------------|--------------|--------|
| IMAGE_GENERATION | MiniMax-Image-01 | ✗ | llava:7b |
| IMAGE_UNDERSTANDING | MiniMax-VL-01 | llava (if available) | llava:7b |
| AUDIO_SPEECH | MiniMax-Speech-02 | ✗ | ✗ |
| AUDIO_TRANSCRIPTION | MiniMax-Speech-02-Turbo | whisper.cpp if local | ✗ |
| VIDEO_GENERATION | MiniMax-Video-01 (Hailuo) | ✗ | ✗ |

______________________________________________________________________

## 6. Data Flow

```
prompt
  │
  ▼
classify_task()  ──────────────────────────────►  TaskCategory
  │
  ▼
LLMProviderChain.complete()
  │  sanitize_input(messages)   ← security hook, always runs
  │
  ├── Tier 1: MiniMax (OpenAICompatAdapter)
  │   └── Timeout: 30s (from LLMTierConfig) │ Circuit: 5 tier-calls / 60s cooldown
  │   └── Retry: 3 attempts, 1s/2s/4s backoff within tier
  │
  ├── Tier 2: llama-server :8081 (OpenAICompatAdapter)
  │   └── Timeout: 60s │ Circuit: 5 tier-calls / 60s cooldown
  │
  └── Tier 3: ollama :11434 (OpenAICompatAdapter)
      └── Timeout: 120s │ Circuit: 5 tier-calls / 60s cooldown
  │
  ▼  sanitize_error() on any failure path
  ▼
LLMResponse(content, provider, model, usage, latency_ms)
```

**Bifrost overlay** (Phase 2, optional): When `BIFROST_BASE_URL` is set, Tier 1 requests route through Bifrost at `http://127.0.0.1:8471`. The `x-bf-task` header carries the `TaskCategory` value. Bifrost adds semantic caching (5m TTL, Redis Stack port 6380 — ensure cached prompts/responses contain no secrets as cache keys) and load-aware routing. Bifrost does **not** override the model variant chosen by task_router. Tiers 2 and 3 bypass Bifrost.

______________________________________________________________________

## 7. Error Handling and Edge Cases

| Edge Case | Handling | Priority |
|-----------|----------|----------|
| Tier timeout | Per-tier `asyncio.wait_for` from `LLMTierConfig`, advance to next | P0 |
| Circuit breaker | N tier-call failures (post all retries) → 60s skip, WARN log | P0 |
| Retry with backoff | 3 attempts (1s/2s/4s) within tier before advancing | P0 |
| `asyncio.CancelledError` | Never caught — always propagates | P0 |
| API key missing at startup | Tier removed from chain, startup WARNING — fail-closed | P0 |
| Error message sanitization | All exceptions stripped of paths/keys before log/raise | P0 |
| Empty response | Treated as failure, retry within tier then advance | P1 |
| Streaming fallback | Try tiers in order; first stream wins; no [DONE] await for ollama | P1 |
| Modality not supported | `UnsupportedModalityError` if no tier supports category | P1 |
| HailuoAdapter SSRF | Poll URL from fixed base + job_id only; redirects disabled; 300s cap | P1 |
| Malformed JSON from provider | sanitize_error → log DEBUG, count as failure | P2 |
| Token limit exceeded | Log WARN with usage info, do not retry | P2 |

______________________________________________________________________

## 8. Per-Repository Migration

**Release sequencing:** Oneiric must be released with the `oneiric/llm/` module (targeting version `0.4.0`) before any downstream repo migration begins. Pin `oneiric>=0.4.0` in all consuming repos.

### 8.1 Oneiric (ships first — target v0.4.0)

- **Add**: `oneiric/llm/` module (models, base, openai_compat, hailuo, chain, config)
- **Add**: `TaskCategory` enum (extended, with VISION deprecation alias)
- **Add**: `classify_task()` core logic
- **Add**: Security hooks to `LLMAdapter` base

### 8.2 mcp-common

- **Add**: `mcp_common/llm/__init__.py` — re-exports `LLMMessage`, `LLMUsage`, `LLMResponse` from `oneiric.llm.models`
- (No new DTOs defined here — avoids dependency cycle)

### 8.3 crackerjack

- **Remove**: `adapters/ai/claude.py`, `adapters/ai/qwen.py`, `adapters/ai/minimax.py`, `adapters/ai/ollama.py`, `adapters/ai/registry.py`
- **Update** (these import from registry.py and must be migrated simultaneously):
  - `agents/enhanced_coordinator.py` — replace `ProviderChain`/`ProviderID` imports
  - `cli/handlers/provider_selection.py` — replace `ProviderFactory`/`ProviderID`/`ProviderInfo` imports
  - `adapters/ai/__init__.py` — update re-exports
  - `adapters/factory.py` — update factory logic
  - `tests/adapters/test_provider_chain.py` — rewrite against Oneiric chain interface
- **Keep**: Security validation logic (`_validate_ai_generated_code`, `_check_dangerous_patterns`, `_sanitize_prompt_input`) — these migrate to Oneiric's `LLMAdapter.validate_output` / `sanitize_input` hooks
- **Change**: `ai_provider: "minimax"` (was `"claude"`) in `config/settings.py`
- **Change**: `ai_providers: ["minimax", "llama_server", "ollama"]`
- **Change dep**: `oneiric>=0.4.0` (was `>=0.3.x`)

### 8.4 session-buddy

- **Remove**: `llm/providers/anthropic_provider.py`, `llm/providers/gemini_provider.py`
- **Keep**: `llm/providers/openai_provider.py` as reference during transition
- **Add dep**: `oneiric>=0.4.0` (currently missing from pyproject.toml)
- **Verify**: `default_provider = "minimax"` already set in settings.py ✓

### 8.5 akosha

- **Audit**: Enumerate all LLM call sites in akosha before migration; add `test_akosha_llm_migration.py` parity test (mirrors crackerjack's approach)
- **Add dep**: `mcp-common>=0.13.x` (currently missing from pyproject.toml)
- **Remove**: try/except MCPBaseSettings fallback in `akosha/config.py`
- **Add**: Oneiric LLMProviderChain for each identified LLM call site

### 8.6 mahavishnu

- **Update**: `mahavishnu/workers/task_router.py` — extend TaskCategory, keep VISION alias, align model names
- **Update**: `settings/models.yaml` — migrate to new `providers` + `task_tiers` schema with backward-compat validator
- **Migrate**: String key `"VISION"` → `"IMAGE_UNDERSTANDING"` in models.yaml after VISION alias ships
- **Remove**: `mahavishnu/workers/cloud_worker.py` and `mahavishnu/workers/ollama_worker.py` (replaced by Oneiric chain)
- **Update**: Bifrost config — add audio/video route rules, re-enable image route
- **Bifrost Phase 2**: Reactivate via LaunchAgent after three-tier chain is stable

### 8.7 dhara

- Verify via grep: `grep -r "llm\|LLM\|openai\|anthropic\|minimax" /path/to/dhara --include="*.py" -l`
- If no results: no changes required

______________________________________________________________________

## 9. Testing Strategy

### 9.1 Unit Tests (no external services)

- `tests/unit/test_llm_classify.py` — parametrized classify_task() including empty prompt, new modality categories, VISION→IMAGE_UNDERSTANDING redirect
- `tests/unit/test_llm_chain.py` — mocked tiers: fallback on failure, circuit breaker counts per tier-call not per attempt, CancelledError propagates, empty response retries within tier then advances, error messages are sanitized before surfacing
- `tests/unit/test_modality_routing.py` — UnsupportedModalityError from OpenAICompatAdapter for VIDEO_GENERATION, video routed to HailuoAdapter
- `tests/unit/test_security_hooks.py` — sanitize_input strips injection patterns, sanitize_error strips API keys and paths
- `@given(st.text(max_size=5000))` Hypothesis test: classify_task() never raises

### 9.2 Integration Tests (require live services)

Run condition: `BODAI_INTEGRATION_TESTS=1` **and** `conftest.py` port-reachability check. Both must pass — the env var gates the suite, the fixture skips individual tests if the specific service is down:

```python
# conftest.py
@pytest.fixture(autouse=True)
def skip_if_service_down(request):
    if "BODAI_INTEGRATION_TESTS" not in os.environ:
        pytest.skip("set BODAI_INTEGRATION_TESTS=1 to run integration tests")
    if request.node.get_closest_marker("requires_ollama"):
        if not is_port_open("127.0.0.1", 11434):
            pytest.skip("ollama not reachable")
    if request.node.get_closest_marker("requires_llama_server"):
        if not is_port_open("127.0.0.1", 8081):
            pytest.skip("llama-server not reachable")
```

### 9.3 Per-Repo Test Additions

| Repo | New test files |
|------|---------------|
| oneiric | `test_llm_chain.py`, `test_llm_classify.py`, `test_modality_routing.py`, `test_security_hooks.py`, `test_local_tiers.py` |
| crackerjack | `test_ai_registry_migration.py` (parity: old ProviderChain API → new Oneiric chain) |
| session-buddy | `test_provider_migration.py` |
| akosha | `test_akosha_llm_migration.py` (enumerate + verify each migrated call site) |
| mahavishnu | extend `test_task_router.py` for new TaskCategory variants + VISION alias |

______________________________________________________________________

## 10. Bifrost Phase 2 (Deferred)

Bifrost stays **optional** via `BIFROST_BASE_URL` env var until three-tier chain is stable end-to-end. No code change required to make Bifrost optional — the env var gate already exists in `mahavishnu/llm_gateway/client.py`.

When ready to activate:

1. Add audio/video CEL route rules to `config/bifrost/config.template.json`
1. Re-enable image route rule (already drafted, currently disabled)
1. Restore LaunchAgent via `docs/bifrost-reactivation-runbook.md`
1. Set `BIFROST_BASE_URL=http://127.0.0.1:8471` in local environment
1. Verify Redis Stack (port 6380) TTL enforcement and confirm no secrets are used as cache keys

______________________________________________________________________

## 11. Dependency Corrections and Release Order

### Pre-migration corrections (do first):

| Repo | Action |
|------|--------|
| session-buddy | Add `oneiric>=0.4.0` to `pyproject.toml` |
| akosha | Add `mcp-common>=0.13.x` to `pyproject.toml` |
| akosha | Remove try/except MCPBaseSettings fallback in `config.py` |
| akosha | Enumerate LLM call sites (audit step before migration) |
| dhara | Grep for LLM usage; confirm clean |
| mahavishnu | Confirm llama-server at port 8081, ollama at 11434, both bound to 127.0.0.1 |

### Release order (strict):

1. **Oneiric v0.4.0** — ships `oneiric/llm/` module with VISION alias
1. **mcp-common** — adds re-export shim
1. **crackerjack, session-buddy, akosha, mahavishnu** — can migrate in parallel after step 2
1. **VISION alias removal** — one release cycle after step 3, after all call sites confirmed migrated
