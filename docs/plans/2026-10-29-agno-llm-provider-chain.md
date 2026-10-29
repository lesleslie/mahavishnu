---
status: complete
role: implementation
date: 2026-10-29
last_reviewed: 2026-10-29
superseded_by: null
topic: agno-llm-routing
title: "Agno LLM provider chain — MiniMax primary, llama-server as fallback"
---

# Agno LLM provider chain — MiniMax primary, llama-server as fallback

## 1. Outcome

The Agno adapter dispatches LLM calls to **MiniMax (via the Bifrost gateway)**
whenever MiniMax credentials are present, and falls back to the local
**llama-server** only when they are not.

Success signal:

```bash
python -c "
from mahavishnu.core.config import MahavishnuSettings
print(MahavishnuSettings().agno.llm.provider)"
# -> minimax
```

and an end-to-end Agno run against Bifrost returns content (not an empty
string) in single-digit seconds.

## 2. Goals

1. `agno.llm.provider` defaults to `minimax`, not `llama_server`.
1. `llama_server` is reachable only as an ordered fallback, never as the
   default target.
1. `agno.llm.base_url` stops defaulting to the llama-server URL, so
   selecting `minimax`/`openai`/`anthropic` cannot silently talk to
   `localhost:8081`.
1. `agno.llm.model_id` stops naming the nonexistent `qwen2.5:7b` and
   resolves per provider (`MiniMax-M3`, `qwen3.5`, `claude-sonnet-4-6`,
   `gpt-4o`).
1. When the resolved base URL points at the Bifrost gateway, the
   client-facing credential is the gateway **virtual key**, not the
   provider's own API key.

## 3. Non-Goals

1. **Not** reusing `mcp_common.llm.FallbackChain` for the Agno agent loop.
   `OpenAICompatibleProvider.execute()` returns only `content` — it drops
   `tool_calls` — so it cannot drive Agno's tool-calling loop. See §4.5.
1. **Not** implementing mid-loop per-call failover. See §4.5 for why the
   tool-call replay semantics make it a separate, riskier change.
1. **Not** renaming the repo-wide `qwen3.5` label to the literal GGUF
   filename `Qwen3-8B-Q4_K_M.gguf`. See §4.4.
1. **Not** adding a `settings/models.yaml` loader. The repo's established
   pattern is in-code constants in `core/model_routing.py`, pinned to the
   YAML by `tests/unit/test_task_router.py::TestYAMLRoutingSync`.
1. **Not** touching `settings/local.yaml` in version control — it is
   gitignored operator-local state.

## 4. Current Findings

### 4.1 The adapter already supports four providers

`mahavishnu/engines/agno_adapter_impl.py:183-188` maps four providers to
four Agno model factories:

| Provider | Agno class | Factory |
|---|---|---|
| `anthropic` | `Claude` | `_create_anthropic_model` |
| `openai` | `OpenAIChat` | `_create_openai_model` |
| `minimax` | `OpenAIChat` | `_create_minimax_model` |
| `llama_server` | `OpenAIChat` (`agno.models.openai.like`) | `_create_llama_server_model` |

So the answer to "does Agno only use llama-server?" is **no** — but the
*effective* answer on this machine was yes, for three compounding reasons.

### 4.2 The default is llama-server and nothing overrides it

`mahavishnu/core/config.py:150-165` defaulted `provider=llama_server`,
`model_id="qwen2.5:7b"`, `base_url="http://localhost:8081"`. There is **no
`agno:` section** in `settings/mahavishnu.yaml` or `settings/local.yaml`.
Verified at runtime before the change:

```
provider : llama_server
model_id : qwen2.5:7b
base_url : http://localhost:8081
```

### 4.3 `base_url` leaks across every provider (the latent bug)

`base_url` carried a *provider-agnostic* default pinned to the llama-server
URL. `_resolve_openai_base_url()` (`agno_adapter_impl.py:402-404`) checks
`self.config.base_url` **first** and returns it, so the Bifrost router was
never consulted for `minimax`/`openai`. Reproduced before the change:

```
minimax      -> OpenAIChat  base_url='http://localhost:8081'   <-- leak
openai       -> OpenAIChat  base_url='http://localhost:8081'   <-- leak
anthropic    -> Claude      (ignores config.base_url entirely)
llama_server -> OpenAIChat  base_url='http://localhost:8081'
```

Only `anthropic` escaped, because `_create_anthropic_model` reads
`ANTHROPIC_BASE_URL` from the Bifrost router instead of `config.base_url`.

### 4.4 `qwen2.5:7b` names a model that does not exist

The local server serves exactly one GGUF:
`/usr/local/share/llama-server/models/Qwen3-8B-Q4_K_M.gguf`. There is no
`qwen2.5:7b` and no `qwen3.5` file. llama.cpp ignores the `model` field
when a single model is loaded — all of `qwen3.5`, `Qwen3-8B-Q4_K_M`, and
the full GGUF path returned HTTP 200 in testing — so the id is a label,
not a selector.

The repo-wide convention for that label is **`qwen3.5`**
(`core/model_routing.py:217` `DEFAULT_LLAMA_SERVER_ROUTING`,
`settings/models.yaml:63-75`, `core/config.py:1892`). `AgnoLLMConfig` was
the single outlier still saying `qwen2.5:7b`. This plan aligns Agno with
the convention rather than renaming the convention.

### 4.5 Why `mcp_common.llm.FallbackChain` is not reused

`mcp_common/llm/provider.py:98-103` returns only `content`, `provider`,
`model`, and `usage` — **`tool_calls` are dropped**. Agno's agent loop
depends on tool calls to drive its tool-use cycle, so the chain's response
shape cannot back an Agno `Model`.

Mid-loop per-call failover is additionally deferred: when provider A emits
a tool call and provider B answers the next turn, B receives a transcript
containing A's tool-call turns. Supporting that across providers is a
distinct design problem (not a config problem), and it is worth its own
plan rather than being smuggled into a routing change.

This plan therefore implements failover **at model-selection time**: the
adapter picks the first *available* provider from the ordered chain when it
builds the model. That is the failure mode that actually matters (MiniMax
credentials absent, Bifrost down, MiniMax API unreachable at startup).

### 4.6 Measured on this machine (2026-10-29)

| Backend | Model | Time | Result |
|---|---|---|---|
| llama-server `:8081` | `Qwen3-8B-Q4_K_M` | **43.4 s** | empty content (16 tokens spent on `reasoning_content`) |
| Bifrost `:8471` | `minimax-openai/MiniMax-M3` | **1.9 s** | `OK` |
| Bifrost `:8471` | `openai/gpt-5.4-mini` | **5.1 s** | `OK` |

### 4.7 The actual root cause: a legacy shim overrode `agno.llm`

Found while verifying the fix end-to-end. The `AgnoAdapter` had **two
inconsistent LLM resolution paths**:

- `initialize()` used `self.agno_config.llm` — the `agno.llm` block.
- `_get_llm()` used `_resolve_legacy_llm_config()`, which reads the
  **top-level `llm:` block** (`model: qwen3.5`, `base_url:
  http://localhost:8081`) — the llama-server endpoint that block exists
  for (LlamaIndex/embeddings).

`_resolve_legacy_llm_config()` applied the legacy values *over* the
`agno.llm` values, so the top-level block's llama-server model and URL
won. With `agno.llm.provider: minimax` configured and the top-level
`llm:` block present, the adapter still dialled `localhost:8081`.

Measured through the real adapter, before the precedence fix:

```
selected class : OpenAIChat
base_url       : http://localhost:8081
model id       : qwen3.5
latency        : 146.46s
reply          : 'OK'
```

After the fix:

```
selected class : OpenAIChat
base_url       : http://127.0.0.1:8471/v1
model id       : MiniMax-M3
latency        : 1.76s
reply          : 'OK'
```

**146 s → 1.8 s** for the same adapter call.

The fix: the `agno.llm` block is authoritative whenever the caller's
config carries one. The legacy flat shapes (`config.llm_provider`,
`config.llm.model`, `config.llm.base_url`) are consulted only for
callers that predate the block — detected by
`AgnoAdapter._has_agno_block()`, which checks for a real
`AgnoAdapterConfig` rather than a `MagicMock` attribute.

Note that `MahavishnuSettings.agno.model_fields_set` is **empty** even
when the YAML sets `agno.llm`, so "was this explicitly configured?" is
*not* answerable via `model_fields_set` — pydantic-settings does not
propagate it into nested models. The `_has_agno_block()` shape check is
used instead.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-AGNO-001
    title: "Agno LLM provider defaults to MiniMax"
  - id: REQ-AGNO-002
    title: "llama-server reachable only as an ordered fallback"
  - id: REQ-AGNO-003
    title: "base_url no longer defaults to the llama-server URL"
  - id: REQ-AGNO-004
    title: "model_id resolves per provider and drops qwen2.5:7b"
  - id: REQ-AGNO-005
    title: "Bifrost-routed calls authenticate with the gateway virtual key"
  - id: REQ-AGNO-006
    title: "The agno.llm block is authoritative over the legacy flat config shapes"
```

## 5. Implementation Phases

### Phase 1: Configuration corrections (`core/config.py`)

**Goal:** remove the three config-level defects (default provider, leaking
`base_url`, fictional `model_id`).

**Tasks:**
- `AgnoLLMConfig.provider` default → `LLMProvider.MINIMAX`.
- `AgnoLLMConfig.base_url` default → `None`.
- `AgnoLLMConfig.model_id` default → per-provider resolution via a
  `mode="after"` validator that consults `model_fields_set`, mirroring the
  existing `_default_api_key_env` validator (`core/config.py:181-206`).
- Add `AgnoLLMConfig.fallback_providers: list[LLMProvider]` defaulting to
  `[LLMProvider.LLAMA_SERVER]`.
- Refresh the three docstrings that still show `qwen2.5:7b`
  (`core/config.py:145`, `:340`, `:2838`).

**Exit criteria:** `MahavishnuSettings().agno.llm.provider` is `minimax`;
`model_id` is `MiniMax-M3`; `base_url` is `None`; `fallback_providers` is
`[llama_server]`.

#### Integration Contract ← REQUIRED
- **Triggered from:** `MahavishnuSettings()` load — `core/config.py`
  `AgnoAdapterConfig.llm` default factory.
- **Returns to / updates:** `mahavishnu/core/config.py` (`AgnoLLMConfig`);
  every consumer reading `settings.agno.llm`.
- **Demonstrable by:** `python -c "from mahavishnu.core.config import MahavishnuSettings; print(MahavishnuSettings().agno.llm)"`.
- **Rollback signal:** `AgnoError: Unsupported LLM provider` at adapter init
  — the provider enum and the factory map disagree.
- **Observability added:** none (declarative config only).

### Phase 2: Provider chain in the factory (`engines/agno_adapter_impl.py`)

**Goal:** build the model from the first *available* provider in
`[provider] + fallback_providers`.

**Tasks:**
- `LLMProviderFactory.create_model()` iterates the ordered chain and
  returns the first provider whose credentials are present.
- Add `_provider_available(provider)` — credential-presence check per
  provider (cloud providers need their key env var; `llama_server` is
  local and always considered available).
- Per-provider `model_id` when the chain advances past the configured
  provider, so the llama-server fallback does not inherit `MiniMax-M3`.
- Bind the Bifrost **virtual key** when the resolved base URL is the
  gateway, instead of the provider's own key.
- Make the `agno.llm` block authoritative in
  `_resolve_legacy_llm_config()` — see §4.7. Without this, the
  top-level `llm:` block still steered the adapter to llama-server.

**Exit criteria:** with `MINIMAX_API_KEY` absent, the factory returns the
llama-server model; with it present, it returns the MiniMax model pointed
at Bifrost.

#### Integration Contract ← REQUIRED
- **Triggered from:** `AgnoAdapter._get_llm()` →
  `LLMProviderFactory.create_model()` (`agno_adapter_impl.py:1342-1361`),
  called from `_create_agent` (`:1204`) when building `Agent(model=...)`.
- **Returns to / updates:** the Agno `Agent`/`Team` `model` attribute;
  `AgnoAdapter._llm_factory`.
- **Demonstrable by:**
  `python -c "from mahavishnu.engines.agno_adapter_impl import LLMProviderFactory; ..."`
  printing a `base_url` of `http://127.0.0.1:8471/v1` under MiniMax and
  `http://localhost:8081` under llama-server.
- **Rollback signal:** `AgnoError: Failed to create LLM model` with
  `details.provider` set — the chain exhausted every candidate.
- **Observability added:** `logger.info("Agno LLM provider selected:
  provider=%s model_id=%s base_url=%s")` at selection time.

### Phase 3: Settings, tests, and documentation

**Goal:** make the new defaults the shipped defaults and pin them with
tests.

**Tasks:**
- Add an `agno:` block to `settings/mahavishnu.yaml` recording the
  intended provider chain.
- Update `tests/unit/test_agno_adapter_impl.py:248` (asserts the old
  `qwen2.5:7b` default) and add coverage for the chain, the per-provider
  `model_id`, and the Bifrost virtual-key binding.
- Update `CLAUDE.md` § "LLM Provider Configuration" to state that the Agno
  adapter uses the same MiniMax-primary chain as the cloud worker.

**Exit criteria:** `pytest tests/unit/test_agno_adapter_impl.py` passes;
`crackerjack run -v -f` passes.

#### Integration Contract ← REQUIRED
- **Triggered from:** repo test suite and the Crackerjack merge gate.
- **Returns to / updates:** `settings/mahavishnu.yaml`, `CLAUDE.md`,
  `tests/unit/test_agno_adapter_impl.py`.
- **Demonstrable by:** `pytest tests/unit/test_agno_adapter_impl.py -v`.
- **Rollback signal:** the CI guard test
  `tests/unit/test_task_router.py::TestYAMLRoutingSync` failing — the
  in-code routing drifted from `settings/models.yaml`.
- **Observability added:** none (test/config only).

## 6. Required Code Changes

- [ ] `mahavishnu/core/config.py` — `AgnoLLMConfig`: provider default,
      `base_url` default, per-provider `model_id`, `fallback_providers`,
      docstrings.
- [ ] `mahavishnu/engines/agno_adapter_impl.py` — `LLMProviderFactory`:
      ordered chain selection, availability check, per-provider model id,
      Bifrost virtual-key binding, selection log line.
- [ ] `settings/mahavishnu.yaml` — `agno:` block.
- [ ] `tests/unit/test_agno_adapter_impl.py` — updated default assertion
      plus new chain/model-id/virtual-key tests.
- [ ] `CLAUDE.md` — document the Agno provider chain.

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `python -c "from mahavishnu.core.config import MahavishnuSettings; print(MahavishnuSettings().agno.llm.provider)"` | `minimax` | stdout |
| `pytest tests/unit/test_agno_adapter_impl.py -v` | all pass | stdout |
| `pytest tests/unit/test_task_router.py::TestYAMLRoutingSync -v` | pass (no routing drift) | stdout |
| `crackerjack run -v -f` | pass | crackerjack output |
| `python scripts/audit_orphans.py` | no newly-orphaned symbols | stdout |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| A machine without `MINIMAX_API_KEY` loses its LLM entirely | low | `fallback_providers` includes `llama_server`; availability check falls through |
| Bifrost gateway down | medium | The chain falls through to `llama_server`, which is local |
| Changing `base_url` default breaks an operator's pinned setting | low | Explicit `base_url` in `settings/local.yaml` still wins — only the *default* changed |
| `model_id` semantics change breaks a caller expecting a fixed string | medium | Per-provider resolution keeps the configured provider's explicit `model_id`; only the *default* is derived |
| Bifrost virtual key absent while Bifrost is the resolved endpoint | medium | Availability check treats a missing virtual key as "Bifrost unavailable" and falls through |

## 9. Decision Rule

Ship when: the default provider is `minimax`, the fallback chain resolves
llama-server only when MiniMax is unavailable, `qwen2.5:7b` no longer
appears in `mahavishnu/core/config.py`, the unit tests cover chain
selection and per-provider model ids, and `crackerjack run -v -f` passes.

Mid-loop per-call failover (§4.5) is explicitly **out of scope**; if it is
wanted later it needs its own plan because it crosses into tool-call
transcript semantics.

## 10. Verification

### 10.1 Runtime resolution

```console
$ python -c "from mahavishnu.core.config import MahavishnuSettings; \
    a = MahavishnuSettings().agno.llm; \
    print(a.provider, a.model_id, a.base_url, a.fallback_providers)"
minimax MiniMax-M3 None [LLMProvider.LLAMA_SERVER]
```

### 10.2 Live adapter call, before and after

Through the real `AgnoAdapter` with `MahavishnuSettings()`:

| | base_url | model id | latency | reply |
|---|---|---|---|---|
| before | `http://localhost:8081` | `qwen3.5` | **146.46 s** | `OK` |
| after | `http://127.0.0.1:8471/v1` | `MiniMax-M3` | **1.76 s** | `OK` |

### 10.3 Provider selection

| Scenario | Selected | base_url |
|---|---|---|
| Default config, credentials present | `minimax` | `http://127.0.0.1:8471/v1` |
| Default config, no credentials | `llama_server` | `http://localhost:8081` |
| `fallback_providers: []`, no credentials | *raises* `ConfigurationError: API key not found. Set MINIMAX_API_KEY…` | — |
| `provider: llama_server` pinned | `llama_server` | `http://localhost:8081` |
| Gateway enabled | `minimax` + **gateway virtual key** | `http://127.0.0.1:8471/v1` |
| Explicit `base_url` set | provider key, not the virtual key | the explicit URL |

### 10.4 Gates

- `ty check` on the changed source files — **passes**.
- `ruff check` on the changed source files — **passes**.
- `ruff format --check` on the changed source files — **passes**.
- `python scripts/audit_orphans.py` — no orphans dated 2026-10-29 (every
  reported orphan is pre-existing, dated 2026-10-15 through 2026-10-28).
- `pytest tests/unit/test_agno_adapter_impl.py` — 168 passed, 2 failed.
  Both failures are **pre-existing** and unrelated (see §10.5).

### 10.5 Pre-existing failures not addressed by this plan

These fail at `HEAD` (8f149717) as well, and are outside this plan's scope:

| Test | Cause |
|---|---|
| `TestAgnoToolsConfigModel::test_default_values` | asserts `mcp_transport == "sse"`; the source has been `streamable-http` since the 2026-10-05 flip |
| `TestAgnoAdapterEntryPoint::test_agno_adapter_entries` | subscripts `agno_adapter_entries()`, which returns `AdapterMetadata` objects, not dicts |
| `test_agno_adapter_initialize_success` | asserts a health-check `GET` that commit `7900620a` deliberately removed |
| `test_wiring.py::test_*_matches_golden_fixture` | MCP tool-name golden fixtures have drifted from the registered tool set |

The first of these is in a file this plan edits, so it was left failing
rather than silently expanding the diff into unrelated drift; the others are
in files this plan does not touch.

### 10.6 `qwen2.5:7b` removal

`qwen2.5:7b` no longer appears in `mahavishnu/` or `settings/`. It remains
only in the two dated `docs/analysis/HIVE_*.md` records (2026-02-21, one
marked SUPERSEDED) and in this plan, where it is quoted as the defect
being fixed.
