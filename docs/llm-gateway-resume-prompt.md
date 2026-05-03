# LLM Gateway — Resume Prompt

> Paste this into Claude Code, Codex, or any coding agent to continue the work.

______________________________________________________________________

## Context

I'm building an LLM gateway/proxy on macOS (Intel x86_64) to unify multiple AI coding clients behind a single endpoint for rate limiting, caching, retry, observability, and cost tracking.

### The Problem

I have 5+ LLM clients that all hit z.ai (GLM models from Zhipu AI) independently:

- **Claude Code** (via CCR — Claude Code Router, installed at `/usr/local/bin/ccr`)
- **Codex CLI** (OpenAI-compatible)
- **Qwen CLI** (OpenAI-compatible)
- **Nanobot** (my AI assistant, OpenAI-compatible)
- **Vish Workers** (OpenAI-compatible)

z.ai has two API formats:

- **OpenAI-compatible**: `https://api.z.ai/api/paas/v4/chat/completions` (glm-5, glm-5-turbo, glm-4.7, glm-4.5, etc.)
- **Anthropic Messages**: `https://api.z.ai/api/anthropic/v1/messages` (GLM-4.7, GLM-4.5-Air, GLM-4.5V, GLM-4.6V)
- **Coding Plan** (cheaper, rate-limited): `https://api.z.ai/api/coding/paas/v4/chat/completions`

Auth: `Authorization: Bearer $Z_AI_API_KEY`

### What We've Done

1. **Evaluated TensorZero** as the gateway — wrote a 1047-line implementation plan at `docs/plans/tensorzero-gateway-plan.md` (v3.0, Postgres auth + Tempo tracing)
1. **Got stuck trying to install it** — the TensorZero Rust binary wouldn't build on macOS, Docker on OrbStack had issues, Python embedded gateway was unclear
1. **Explored alternatives** — Bifrost, Helicone, BricksLLM, Portkey, LunarGate, any-llm-gateway, llms.py — all either SaaS/cloud-only, unmaintained, or over-engineered for this use case

### What I Actually Need

A **simple, self-hosted LLM proxy** that:

1. Listens on localhost:8471
1. Exposes OpenAI-compatible `/v1/chat/completions` endpoint
1. Routes requests to z.ai's OpenAI-compatible endpoint with the API key injected
1. Has basic rate limiting (per-minute or per-model)
1. Optionally caches identical requests
1. Logs requests/responses for observability (structured JSON logs are fine)
1. Can be run as a macOS LaunchAgent (survives reboots)

**CCR (Claude Code Router)** already handles the Anthropic-format translation for Claude Code, so the gateway only needs to speak OpenAI format.

### Existing Infrastructure

- **macOS Intel x86_64**, 16 GB RAM
- **Python 3.13** via `uv`
- **Go 1.26.1** at `/usr/local/bin/go`
- **Postgres 18** via Homebrew (running, `tensorzero` database exists with `pg_trgm` and `vector` extensions)
- **Redis** via Homebrew (running, localhost:6379)
- **Grafana** on port 3030 (with mcp-grafana proxy on port 3035)
- **Tempo** built from source at `~/.local/share/tempo/bin/tempo` (v2.10.3, NOT currently running)
- **uv** preferred over pip
- **Homebrew binaries** at `/usr/local/opt/` (NOT `/opt/homebrew/`)

### Key Files

| File | Purpose |
|---|---|
| `docs/plans/tensorzero-gateway-plan.md` | Full 1047-line TensorZero plan (reference for requirements) |
| `~/.config/tensorzero/tensorzero.toml` | TensorZero config (101 lines, already written) |
| `~/Library/LaunchAgents/com.tensorzero.gateway.plist` | TensorZero LaunchAgent (already written, not loaded) |
| `~/.config/tempo/tempo.yaml` | Tempo config (already written, not loaded) |
| `/usr/local/bin/ccr` | Claude Code Router (not currently running) |

### Constraints

- Must be **simple** — I prefer the simplest solution that works
- **No Docker** — native install only
- **localhost only** — no external exposure needed
- Must work with `OPENAI_BASE_URL=http://127.0.0.1:8471/v1` for OpenAI-compatible clients
- Must not conflict with Claude Code's own timeout (900s) or Nanobot's retry logic (3 attempts, 7s total)

### What I Want You To Do

Evaluate the simplest path to get a working LLM gateway running on this machine. Options include but aren't limited to:

1. **Build a minimal FastAPI proxy** (~200-300 lines Python) with rate limiting via Redis
1. **Get TensorZero working** (the plan exists, just needs installation troubleshooting)
1. **Use any-llm-gateway or llms.py** if they're viable
1. **Something else entirely** that I haven't considered

Then implement whichever option is simplest and most reliable. Create a LaunchAgent plist so it survives reboots. Verify it works by sending a test request with `curl`.

After the gateway is running, the next step would be reconfiguring CCR and the other clients to point at it — but get the gateway running first.

______________________________________________________________________

## Environment Notes

- Shell: bash, Homebrew at `/usr/local/`
- `psql` full path: `/usr/local/opt/postgresql@18/bin/psql`
- Python: system `python`/`python3` alias points to 3.12 — use full path for non-default venvs
- `.bash_profile` has two stale source lines (harmless but noisy): `/Users/les/.cargo/env` is a directory, `/Users/les/.config/broot/launcher/bash/br` doesn't exist
- `Z_AI_API_KEY` env var is not currently set anywhere persistent — you'll need to ask me for it
