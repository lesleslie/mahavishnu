---
status: complete
role: historical
topic: convergence-control-plane
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
---

# Configuration & API Compatibility Review — TensorZero Gateway Plan

## **Reviewer**: nanobot (inline) **Date**: 2026-04-06 **Document reviewed**: `docs/plans/tensorzero-gateway-plan.md`

## 🔴 Critical Issues

### C1. Missing model routing — TensorZero doesn't know which provider to use

The plan configures three providers (`zai`, `anthropic`, `openai`) but **no functions, models, or variants** that tell TensorZero how to route incoming requests. TensorZero requires explicit model definitions or function configs to map incoming model names (e.g., `glm-5-turbo`, `gpt-5`) to provider variants.

Without this, TensorZero will reject requests with "unknown model" errors because it has no routing table.

**Fix**: Add model definitions in `tensorzero.toml`. Example:

```toml
[[models]]
name = "glm-5-turbo"
endpoint_name = "zai"

[[models]]
name = "glm-4.7"
endpoint_name = "zai"

[[models]]
name = "gpt-5"
endpoint_name = "openai"

[[models]]
name = "claude-sonnet-4.5"
endpoint_name = "anthropic"
```

Or use TensorZero's function-based routing with variants for each provider.

### C2. z.ai provider type is wrong

The plan defines z.ai as `type = "openai"`:

```toml
api_base = "https://api.z.ai/api/anthropic/v1/messages"
```

But z.ai's `/api/anthropic/v1/messages` endpoint uses **Anthropic Messages format**, not OpenAI format. Setting `type = "openai"` tells TensorZero to serialize requests as OpenAI chat completions, which z.ai's Anthropic endpoint won't understand.

**Fix**: Either:

1. Use z.ai's OpenAI-compatible endpoint if one exists (e.g., `https://api.z.ai/api/openai/v1/chat/completions`) with `type = "openai"`, OR
1. Use `type = "anthropic"` with the Anthropic endpoint URL

Need to verify which API formats z.ai actually supports. The plan should document the correct endpoint + type combination.

### C3. CCR format translation may conflict with TensorZero

CCR receives Anthropic Messages format from Claude Code and translates to OpenAI format. TensorZero's `/openai/v1` endpoint receives OpenAI format and routes to providers. But:

- CCR may send Anthropic-specific headers (`anthropic-beta`, `anthropic-version`) that TensorZero doesn't expect on its OpenAI endpoint
- CCR's model name translation (e.g., mapping `opus` → `GLM-4.7`) means TensorZero receives `GLM-4.7` as the model name — which needs to match a configured model name (see C1)
- CCR's retry/fallback logic may conflict with TensorZero's own retry/fallback logic (double retry)

**Fix**: Test the CCR → TensorZero path explicitly. Consider disabling retries on one side (preferably CCR) to avoid double-retry. Verify header passthrough.

______________________________________________________________________

## 🟡 Warnings

### W1. Environment variable conflicts with OPENAI_BASE_URL

The plan sets `OPENAI_BASE_URL=http://localhost:8471/openai/v1` globally for Qwen and potentially other clients. Any other tool or script that uses the OpenAI Python SDK and relies on `OPENAI_BASE_URL` will suddenly route through TensorZero — including tools that might need to hit the real OpenAI API.

**Fix**: Use per-tool configuration where possible (Codex config file, nanobot provider config). Only set `OPENAI_BASE_URL` globally if ALL OpenAI SDK usage should go through TensorZero. Consider setting `OPENAI_API_KEY` to a sentinel value like `"tensorzero-gateway"` to make misrouting obvious.

### W2. Streaming support not verified

Coding agents (Claude Code, Codex, Qwen) all use streaming responses. The plan doesn't verify that TensorZero's `/openai/v1/chat/completions` endpoint supports Server-Sent Events (SSE) streaming, or that tool calls work correctly through the gateway.

**Fix**: Add a streaming smoke test to the deployment steps:

```bash
curl -N http://localhost:8471/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"glm-4.7","messages":[{"role":"user","content":"hi"}],"stream":true}'
```

### W3. Tool calling / function calling support

Coding agents heavily use tool calling (MCP tools, file operations, shell commands). The plan doesn't address whether TensorZero correctly passes through OpenAI-format tool calls to z.ai's Anthropic-format endpoint (if using the Anthropic provider type) or vice versa.

**Fix**: Verify tool calling round-trip with a realistic test case (agent with MCP tools).

### W4. Rate limiting config may be too aggressive or too permissive

```toml
bucket_capacity = 30
refill_rate = 10  # 10 inferences/sec
```

10 requests/second sustained is generous for a single developer. But z.ai's actual rate limits are unknown — these numbers are guesses.

**Fix**: Start with lower limits and tune based on actual usage patterns from TensorZero's metrics dashboard.

### W5. Cache config syntax may be incorrect

The plan shows:

```toml
[caching]
enabled = true
default_ttl_secs = 3600
cache_mode = "on"
```

TensorZero's actual caching config uses per-model cache settings, not a global `[caching]` block. Need to verify the correct TOML structure from TensorZero docs.

______________________________________________________________________

## 🟢 Good Practices

### ✅ G1. All clients use OpenAI-compatible format (or have a translator)

Five of six clients natively speak OpenAI format. CCR handles the one exception. This minimizes integration surface area.

### ✅ G2. Version-controlled config

`tensorzero.toml` in GitOps-friendly format. Changes are auditable and reproducible.

### ✅ G3. Independent client migration

Each client can be configured and tested independently. No big-bang cutover.

### ✅ G4. Conservative default rate limits

Starting with rate limiting enabled (even if the numbers need tuning) is safer than starting without it.

______________________________________________________________________

## Summary

| Category | Count |
|----------|-------|
| 🔴 Critical | 3 |
| 🟡 Warning | 5 |
| 🟢 Good practice | 4 |

**The biggest gap**: The `tensorzero.toml` config is incomplete — it has providers but no model routing definitions, and the z.ai provider type may be wrong. The config needs to be rewritten against actual TensorZero documentation before any testing can begin.

**Recommended next steps**:

1. Verify z.ai's API formats (OpenAI-compatible vs Anthropic) and choose correct provider types
1. Add model definitions to `tensorzero.toml` for every model name clients will send
1. Test CCR → TensorZero streaming + tool calling end-to-end before wiring other clients
1. Verify TensorZero caching config syntax against official docs
