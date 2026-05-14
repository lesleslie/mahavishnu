# LLM Inventory

Date: 2026-04-09

## Current State

- Bifrost and the dedicated Redis Stack cache are intentionally dormant.
- Installed user LaunchAgent copies were removed from `~/Library/LaunchAgents` on 2026-04-09.
- Source launchd plists are still stored in the repo under `config/launchd/` for later reuse.
- Subscription-backed coding tools are routed directly to their native provider endpoints again.

## User-Facing Clients

| Client | Current path | Base URL / mode | Notes |
|---|---|---|---|
| Codex | Direct native Codex/OpenAI path | Native Codex login/API behavior | `openai_base_url` override removed |
| Claude Code | Direct z.ai Anthropic-compatible path | `https://api.z.ai/api/anthropic` | Uses `glm-4.5-air` / `glm-4.7` model ids; optional configurable path, not default |
| Qwen | Direct DashScope OpenAI-compatible path | `https://dashscope.aliyuncs.com/compatible-mode/v1` | Supported configurable external path; not part of the default config |
| OpenClaw | Direct z.ai provider | `https://api.z.ai/api/coding/paas/v4` | Optional configurable provider restored from pre-Bifrost backup |
| Mahavishnu terminal workers | Native CLI config | No forced gateway | `terminal-claude` is the default; `terminal-qwen` is retained as a supported non-default worker type |

## Session-Buddy

Primary entrypoint:

- `session_buddy/llm_providers.py`

Provider order:

- default provider: `openai`
- fallbacks: `anthropic -> gemini -> ollama`

Important callsites:

- `session_buddy/mcp/tools/intelligence/llm_tools.py`
  - operator-facing MCP tools for listing, testing, configuring, and generating with LLM providers
- `session_buddy/memory/entity_extractor.py`
  - direct `AsyncOpenAI(...)` path for structured memory extraction
  - cascade extraction engine that tries `openai`, then `anthropic`, then `gemini`, then pattern extraction
- `session_buddy/llm/providers/openai_provider.py`
  - OpenAI-compatible provider
- `session_buddy/llm/providers/anthropic_provider.py`
  - Anthropic-compatible provider
- `session_buddy/llm/providers/ollama_provider.py`
  - local Ollama provider

Practical reading:

- Session-Buddy is not local-Ollama-first.
- If OpenAI is configured and available, it is the first paid path.
- Ollama is the tail fallback, not the default.

## Crackerjack

Primary entrypoint:

- `crackerjack/adapters/ai/registry.py`

Provider order:

- default configured provider in `crackerjack/config/settings.py`: `claude`
- provider chain: `claude -> ollama` with Qwen retained as an explicit configurable fallback

Important callsites:

- `crackerjack/adapters/ai/claude.py`
  - `anthropic.AsyncAnthropic(...)`
- `crackerjack/adapters/ai/qwen.py`
  - `openai.AsyncOpenAI(...)` against DashScope-compatible Qwen endpoints
- `crackerjack/adapters/ai/ollama.py`
  - local Ollama code fixer
- `crackerjack/agents/enhanced_coordinator.py`
  - constructs and uses the provider chain
- `crackerjack/agents/claude_code_bridge.py`
  - Claude-assisted issue handling and specialist consultation logic
- `crackerjack/services/doc_update_service.py`
  - direct `anthropic.Anthropic(...)` use for AI-powered documentation updates

Practical reading:

- Crackerjack is not local-first by default.
- Claude is the primary external provider.
- Qwen is a supported configurable external path kept for explicit compatibility workflows.
- Ollama is the local fallback.

## Mahavishnu

Mahavishnu has multiple LLM paths rather than one global default.

### Agno path

Primary config:

- `mahavishnu/core/config.py`

Defaults:

- provider: `ollama`
- model: `qwen2.5:7b`
- base URL: `http://localhost:11434`

Runtime path:

- `mahavishnu/core/app.py`
  - `DefaultLLMFactory.create_llm(...)` uses the configured Agno provider

Practical reading:

- The Agno-based orchestration path is local-Ollama-first by default.

### Retired Nanobot in-process path

Primary callsites:

- `mahavishnu/core/app.py`
- `mahavishnu/core/adapters/worker.py`

Behavior:

- creates `nanobot.providers.OpenAICompatProvider`
- uses `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_BASE_URL`

Practical reading:

- This path is retired/historical. When those env vars were present in older
  setups, it used a remote Anthropic-compatible endpoint, not Ollama.

### Terminal worker path

Primary config:

- `mahavishnu/workers/registry.py`

Relevant workers:

- `terminal-claude`
- `terminal-qwen`
- `terminal-codex`
- `terminal-openclaw`
- `terminal-ollama`

Practical reading:

- These workers now defer to each CLI's native configuration.
- The explicit local path is `terminal-ollama`.
- The non-Ollama terminal workers are provider-neutral CLI shims that use whatever their corresponding CLI is configured to use.

### RAG and embeddings

Primary callsites:

- `mahavishnu/engines/llamaindex_adapter_impl.py`
- `mahavishnu/core/embeddings.py`

Behavior:

- LlamaIndex uses `OllamaEmbedding(...)` and `Ollama(...)`
- embedding fallback order is `FastEmbed -> Ollama -> OpenAI`

Practical reading:

- Mahavishnu is strongly local-first for embeddings and LlamaIndex-backed retrieval.

## Bottom Line

| Component | Most likely actual path |
|---|---|
| Session-Buddy | Remote API first, Ollama last |
| Crackerjack | Claude first, then Ollama; Qwen is retained as an explicit configurable compatibility option |
| Mahavishnu Agno / LlamaIndex / embeddings | Local Ollama or local embedding stack first |
| Retired Nanobot in-process workers | Retired historical path; no longer part of active fleet |
| Mahavishnu terminal workers | Whatever the CLI itself is configured to use |

## Bifrost Economics

This section assumes Bifrost is reactivated later and used as an API gateway with caching.

### What Bifrost cache can save

- Exact-match response cache can avoid the full upstream request on a cache hit.
- That means the savings are closer to full request cost avoidance than to provider-side prompt-cache discounts.
- Semantic cache can add more hits for near-duplicate prompts, but the actual win rate depends heavily on how standardized the prompts are.

### Rough savings model

Approximation:

- request cost = input tokens × input price + output tokens × output price
- gateway cache savings = cache hit rate × request cost

This is intentionally rough. It ignores local infra cost because on this machine that cost is negligible compared with provider spend.

### Example: OpenAI `gpt-5.4-mini`

Reference pricing:

- input: `$0.75 / 1M`
- cached input at provider: `$0.075 / 1M`
- output: `$4.50 / 1M`

Example request:

- 20k input tokens
- 2k output tokens

Approximate cost without gateway cache:

- input: `$0.015`
- output: `$0.009`
- total: `$0.024`

Approximate savings per 1,000 similar requests:

| Cache hit rate | Savings |
|---|---|
| 25% | about `$6` |
| 50% | about `$12` |
| 75% | about `$18` |

### Example: OpenAI `gpt-5.4`

Reference pricing:

- input: `$2.50 / 1M`
- cached input at provider: `$0.25 / 1M`
- output: `$15 / 1M`

Same example request:

- 20k input tokens
- 2k output tokens

Approximate cost without gateway cache:

- input: `$0.05`
- output: `$0.03`
- total: `$0.08`

Approximate savings per 1,000 similar requests:

| Cache hit rate | Savings |
|---|---|
| 25% | about `$20` |
| 50% | about `$40` |
| 75% | about `$60` |

### What is realistic

Rough expectations for coding-agent workloads:

| Workload shape | Likely savings |
|---|---|
| Mostly unique human prompts | low, often under 10% |
| Standardized internal prompts and repeated scaffolding | moderate, often 10% to 30% |
| Highly repetitive agent loops, retries, summaries, and templated tasks | strong, often 30% to 60% |

Practical reading:

- Exact-match cache helps most when agents repeat the same prompt structure with similar context.
- Semantic cache helps when prompts vary a bit but still land in a stable intent pattern.
- The larger the model and the more output-heavy the task, the more valuable a cache hit becomes.

### Subscription vs API

- For supported coding tools on z.ai, subscription use is usually cheaper than API billing.
- For Codex-style subscription use, native subscription-backed access is usually cheaper than API billing at moderate or heavy usage.
- For internal services like Session-Buddy and Crackerjack, subscriptions generally do not apply, so the realistic comparison is local models versus paid API spend.

## Sources

- OpenAI API pricing: https://openai.com/api/pricing/
- GPT-5.4 mini model page: https://developers.openai.com/api/docs/models/gpt-5.4-mini
- OpenAI pricing overview: https://openai.com/pricing/
- Z.ai DevPack quick start: https://docs.z.ai/devpack/quick-start
- Z.ai DevPack FAQ: https://docs.z.ai/devpack/faq
- Z.ai pricing overview: https://docs.z.ai/guides/overview/pricing
