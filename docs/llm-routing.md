# LLM routing — Bifrost + oneiric

Every Bodai LLM call site routes through the oneiric
[`BifrostLLMRouter`][oneiric-router], which is a thin URL-rewriter
sitting in front of the local Bifrost gateway at
`http://127.0.0.1:8471/v1` (the OpenAI-compatible endpoint).
Anthropic-compatible calls route to `/anthropic`. The router is
the single source of truth for the gateway URL, the auth env var,
and the per-route enable flags.

This page documents the wiring so anyone changing an LLM call
site can do it without rediscovering the contract.

[oneiric-router]: https://github.com/lesleslie/oneiric/blob/main/oneiric/adapters/llm/bifrost.py

## The one-liner

```python
from oneiric.adapters.llm.bifrost import get_router, LLMProvider

base_url = get_router().resolve(LLMProvider.OPENAI)       # → "http://127.0.0.1:8471/v1"
anthropic_url = get_router().resolve(LLMProvider.ANTHROPIC) # → "http://127.0.0.1:8471/anthropic"
```

`resolve()` returns `str(settings.base_url)` (or the
anthropic_base_url) when the router is enabled and the matching
route is in `settings.routes`. It returns `None` when disabled —
the caller surfaces a clear `RuntimeError` rather than blocking
on a misconfigured gateway.

## Operator configuration

| Env var (oneiric) | Effect |
|---|---|
| `ONEIRIC_BIFROST_ENABLED=true` | Master switch (default: false → all resolve() calls return None → fall back to direct cloud) |
| `ONEIRIC_BIFROST_ROUTES=qwen_route` | Comma-separated set: `claude_route`, `qwen_route`. OPENAI maps to `qwen_route`; ANTHROPIC maps to `claude_route`. |
| `ONEIRIC_BIFROST_BASE_URL=http://127.0.0.1:8471/v1` | Override the default gateway URL (the default already includes `/v1` since oneiric 0.32.1) |
| `ONEIRIC_BIFROST_ANTHROPIC_BASE_URL=http://127.0.0.1:8471/anthropic` | Override the anthropic endpoint |
| `ONEIRIC_BIFROST_AUTH_TOKEN=…` | Bearer token for the gateway (the env-var **name** is the secret; the value is logged only at DEBUG) |
| `BIFROST_ALLOW_REMOTE=1` | Opt-in to non-loopback URLs (blocks AWS/GCP/Azure IMDS + RFC1918 even when set) |

The legacy `MAHAVISHNU_BIFROST__*` prefix is still accepted (with
a `DeprecationWarning` + structured `legacy_env_prefix_in_use` log
line); the canonical prefix is `ONEIRIC_BIFROST_`.

## Call sites (4 in-scope repos)

### mahavishnu

| File | Provider | What it does |
|---|---|---|
| `mahavishnu/terminal/manager.py:72` | Anthropic | Injects `ANTHROPIC_BASE_URL=<gateway>/anthropic` into spawned `terminal-claude` workers |
| `mahavishnu/terminal/manager.py:81` | OpenAI | Injects `OPENAI_BASE_URL=<gateway>/v1` into spawned `terminal-qwen` workers |
| `mahavishnu/workers/cloud_worker.py:93` | OpenAI | Resolves the base URL for the MiniMax OpenAI-compatible worker (replaces the legacy `BifrostClient` literal) |
| `mahavishnu/health.py:493` | n/a | `/health.bifrost.config` probe — reads `get_router()._settings.model_dump()` (the oneiric override excludes `auth_env` by default) |
| `mahavishnu/core/health.py:1314, 1334, 1337` | n/a | `_probe_bifrost_state` + `_probe_local_provider_state` — read `get_router()._settings.{base_url, local_provider_enabled, local_provider_url}` |

### session-buddy

| File | Provider | What it does |
|---|---|---|
| `session_buddy/llm_providers.py:524` | OpenAI | Resolves the OpenAI base URL for the `LLMManager._build_chain()` provider list (minimax + llama_server fallback) |
| `session_buddy/memory/entity_extractor.py:147` | OpenAI | Resolves the base URL for the entity-extraction LLM call (AsyncOpenAI client) |
| `session_buddy/worker.py:127` | OpenAI | `_resolve_bifrost_base_url()` helper used by `LLMBackend.execute` |

### crackerjack

| File | Provider | What it does |
|---|---|---|
| `crackerjack/adapters/ai/unified.py:68` | OpenAI | Resolves the base URL for `FallbackChainCodeFixer._build_llm_settings()` (minimax + llama_server fallback) |

### mcp-common

| File | Provider | What it does |
|---|---|---|
| `mcp_common/llm/provider.py:45, 54` | config-driven | Reads `config.base_url` from `LLMSettings.providers["minimax"]` (which is itself populated by the 3 consumer repos above) |

The `LLMSettings` model in `mcp_common/llm/config.py` defines
`bifrost` as a reserved key in its YAML schema — this is metadata
about what config keys are recognized, not a runtime call site.

## Call site #10 — PiPool (model-agnostic agent bridge)

`mahavishnu/pools/pi_pool.py` is a per-task spawner against
`npx @earendil-works/pi-coding-agent@1.3.0`. Each `execute_task`
call runs one `npx ... pi <prompt>` subprocess and reaps it. The
agent is a third-party tool that reads the standard
`OPENAI_API_KEY` / `OPENAI_BASE_URL` /
`ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL` env vars to call an
upstream. The pool's `env_allowlist` (see `pi_pool.py:_env_allowlist`
default) forwards these vars from the parent shell into the
per-task subprocess.

To route PiPool through Bifrost, the operator exports the standard
env vars pointed at the gateway:

```bash
export OPENAI_BASE_URL=http://127.0.0.1:8471/v1
export OPENAI_API_KEY=...                 # any non-empty value
```

The pi-coding-agent treats `OPENAI_BASE_URL` as its upstream; with
the gateway URL above, every prompt routes through Bifrost to the
configured MiniMax / Anthropic provider.

The `mahavishnu demo pool-pi` precondition check
(`_check_pool_pi_preconditions` in `cli/demo_cli.py`) fails fast
with a clear hint if no LLM credential is exported, so the
"subprocess starts, upstream returns 401" failure mode surfaces
as a visible error rather than a silent empty result.

## Local providers that bypass Bifrost

The `llama_server` provider (and any future local-only provider)
intentionally bypasses Bifrost. Its `base_url` is sourced from
the `LLAMA_SERVER_URL` env var (default `http://localhost:8081`).
No Bifrost routing is applied — the local server is the target.

```
crackerjack:  base_url = os.environ.get("LLAMA_SERVER_URL", "http://localhost:8081")
session-buddy: same pattern in LLMManager._build_chain()
```

The `audit_bifrost_callers.py` script maintains the
`LOCAL_PROVIDER_ALLOWLIST` that pins these URLs.

## `/health.bifrost.config` projection

The mahavishnu `/health` route exposes a public `bifrost` block
(the operator-visible Bifrost settings, with `auth_env` redacted
to avoid leaking the env-var name). The projection is sourced
from `oneiric.BifrostLLMSettings.model_dump()`, which excludes
every field in `_SENSITIVE_FIELDS = frozenset({"auth_env"})` by
default. This is a centralized Pydantic-level enforcement — the
three call sites that previously spelled out
`model_dump(exclude={"auth_env"})` explicitly were collapsed to
`model_dump()` in Phase 7.

```bash
$ mahavishnu config validate
Bifrost settings (settings.bifrost, auth_env redacted):
  enabled: False
  base_url: http://127.0.0.1:8471/v1
  anthropic_base_url: http://127.0.0.1:8471/anthropic
  …
```

## SSRF defense

`BifrostLLMSettings` validates the configured `base_url` /
`anthropic_base_url` / `local_provider_url` against a loopback +
IMDS denylist at construction time (the `_check_loopback_and_imds`
validator). Non-loopback URLs raise `ValueError` on settings load
unless `BIFROST_ALLOW_REMOTE=1` is set; even with the opt-in,
AWS/GCP/Azure IMDS IPs and RFC1918 ranges remain blocked. This
is the SSRF defense called out in REQ-BIFROST-016.

## Cross-repo audit

`scripts/audit_bifrost_callers.py` (this repo) walks the 4
in-scope repos and asserts that no LLM-client construction
hardcodes an upstream cloud URL. Run it as part of the merge
gate; a failure means a regression snuck a literal base URL
back into a call site.

## What about a future Phase 9 (if any)?

The plan is structurally complete after Phase 8. A hypothetical
Phase 9 would be:
- Removing the legacy `MAHAVISHNU_BIFROST__*` env-var prefix
  (post-1.0 deprecation window; per `feedback-no-backwards-compat-pre-1.0.md`,
  the deprecation window is not opened pre-1.0)
- Adding non-loopback URL redaction to `_SENSITIVE_FIELDS` for
  unauthenticated `/health` callers (the F-07 fix; pending
  oneiric-side model_dump support)
- Replacing the per-call `_resolve_bifrost_base_url()` helper in
  session-buddy with direct `get_router().resolve()` calls (cosmetic)

None of these block the plan's exit criteria.
