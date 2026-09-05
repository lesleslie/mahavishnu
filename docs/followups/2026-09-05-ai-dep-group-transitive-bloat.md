---
status: active
role: implementation
date: 2026-09-05
last_reviewed: 2026-09-05
topic: ai-dep-group-transitive-bloat
---

# `ai` optional dep group pulls 5 LLM providers + heavy `google-cloud-*` chain

## Status

🟡 **Documented; remediation deferred** — the `ai` group is declared optional
in `pyproject.toml` and only installed when explicitly requested
(`uv sync --group ai`). Most operators will never install it. The bloat
is real but cosmetic; only matters for an operator who explicitly opts in.

## Observation

`pyproject.toml:200-202`:

```toml
ai = [
    "pydantic-ai-slim[mcp,openai,anthropic,google,groq]>=2.33.0",
]
```

A single optional group pulls in five distinct LLM provider SDKs plus a
significant chain of `google-cloud-*` packages for things unrelated to
LLM inference.

Verified 2026-09-05 by `uv sync --group ai` and `pip list`:

| Pulled in | Why |
|---|---|
| `openai 3.8.0` | `pydantic-ai-slim[openai]` |
| `anthropic 1.3.0` | `pydantic-ai-slim[anthropic]` |
| `groq 1.7.0` | `pydantic-ai-slim[groq]` |
| `google-genai 2.22.0` | `pydantic-ai-slim[google]` |
| `google-api-core 2.36.0` | transitive of `google-genai` |
| `google-auth 2.57.1` | transitive of `google-genai` |
| `google-cloud-core 2.7.0` | transitive |
| `google-cloud-secret-manager 2.30.0` | transitive — *secret manager* is unrelated to LLM inference |
| `google-cloud-storage 3.13.1` | transitive — *file storage* is unrelated to LLM inference |
| `google-crc32c 1.8.0` | transitive |
| `google-resumable-media 2.10.2` | transitive |
| `googleapis-common-protos 1.75.3` | transitive |
| `grpc-google-iam-v1 0.14.5` | transitive |
| `mcp 1.29.1` | `pydantic-ai-slim[mcp]` |
| `fastmcp 3.4.7` + `fastmcp-slim 3.4.7` | transitive |
| `mcp-common 0.24.3` | transitive |
| `pillow 12.3.0` | transitive of `anthropic` SDK |

The original worry about `pytesseract`/`pyautogui` from the prior plan was
incorrect — those come from a different path (likely `pyinstaller`-bundled
OCR tools or downstream of `easyocr`, not from `pydantic-ai-slim` extras).
The actual bloat is the LLM-SDK proliferation and the `google-cloud-*`
chain.

## Suggested remediation (when ready)

Split into per-provider sub-groups:

```toml
ai = ["pydantic-ai-slim[mcp]>=2.33.0"]                  # base, only MCP
ai-openai = ["pydantic-ai-slim[openai]>=2.33.0"]
ai-anthropic = ["pydantic-ai-slim[anthropic]>=2.33.0"]
ai-google = ["pydantic-ai-slim[google]>=2.33.0"]        # warning: pulls google-cloud-*
ai-groq = ["pydantic-ai-slim[groq]>=2.33.0"]
```

Then operators `uv sync --group ai --group ai-anthropic` to get only
what they need. The base `ai` group stays installable for testing.

**Cost of NOT splitting**: ~50 MB of additional disk per install, and
~10 extra top-level packages that surface in `pip list` / dependency
audits. Mostly invisible — the `ai` group is opt-in.

## Why deferred

- The `ai` group is **already** optional and gated behind explicit install.
- All 5 provider SDKs are needed for the tests of `pydantic_ai_adapter` to
  exercise model-agnostic routing logic.
- Splitting is a rip-and-replace of test fixtures and dev workflows; not
  a one-line change.

Filed for future consideration when the install footprint becomes a real
problem (e.g., edge deployments or constrained CI runners).
