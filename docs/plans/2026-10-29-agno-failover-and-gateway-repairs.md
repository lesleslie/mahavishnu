---
status: active
role: implementation
date: 2026-10-29
last_reviewed: 2026-10-29
superseded_by: null
topic: agno-failover-gateway
title: "Agno failover, gateway credential resolution, and the Pi pool's missing Bifrost key"
---

# Agno failover, gateway credential resolution, and the Pi pool's missing Bifrost key

Follow-up to `docs/plans/2026-10-29-agno-llm-provider-chain.md`. That plan
made MiniMax the primary provider and llama-server the fallback **at model
construction time**. This plan closes the remaining gaps.

## 1. Outcome

1. The Agno adapter fails over **mid-run** — a provider that dies after the
   agent has already made tool calls falls through to the next provider.
2. The adapter requests a model id the Bifrost gateway's Anthropic surface
   actually serves.
3. The Pi pool authenticates against the Bifrost gateway when Mahavishnu
   was spawned by launchd.
4. The three stale test assertions that failed before this work pass.

## 2. Goals

1. Failover happens per LLM call, not only at model construction.
2. A gateway-routed provider asks for a model the gateway serves.
3. The pool's gateway credential comes from the canonical source, not from
   an inherited interactive environment.
4. The credential a *fallback* provider uses is never the primary's.

## 3. Non-Goals

1. **Not** changing Bifrost's live SQLite config store. The `anthropic`
   provider is declared in `config/bifrost/config.template.json` but is
   absent from the live store — see §4.6 for why repairing that is an
   operator decision.
2. **Not** making `mcp_common`'s `FallbackChain` drive the Agno agent loop
   (it drops `tool_calls`).
3. **Not** changing the `search_code` tool's path validation — a separate
   pre-existing gap (§4.7).

## 4. Current Findings

### 4.1 Failover was construction-time only

`LLMProviderFactory.create_model()` picked the first provider with usable
credentials and returned it. If that provider failed *during* a run — the
MiniMax API rate-limiting on turn four, after three tool calls — the whole
run died, even though llama-server was configured as a fallback.

Agno's agent loop calls `Model.invoke` (or `ainvoke`) once per turn — see
`agno.models.base.Model._process_model_response` — so overriding those two
methods is sufficient to fail over mid-loop.

### 4.2 The gateway's Anthropic surface serves MiniMax, not Claude

Bifrost's provider named `anthropic` is a *custom* provider with
`base_provider_type: "anthropic"` pointing at `https://api.minimax.io`
with the request-path override `/anthropic/v1/messages`, and its key's
model list is `["MiniMax-M3", "MiniMax-M3.1-Flash"]`.

The adapter asked for `claude-sonnet-4-6`, which the gateway does not
serve, so the request failed with
`failed to get config for provider anthropic: not found`.

There is no real Anthropic API key in this deployment: `ANTHROPIC_API_KEY`
is absent from `~/.config/secrets.env`, and the `ANTHROPIC_AUTH_TOKEN` in
`~/.claude/settings.json` is the same length as `MINIMAX_API_KEY` with
MiniMax model names. The gateway's Anthropic surface is therefore the
*only* Anthropic-protocol backend available.

### 4.3 The Pi pool had no gateway credential under launchd

`PiPool._build_subprocess_env` forwards allowlisted names from
`os.environ`. Mahavishnu's launchd plist
(`~/Library/LaunchAgents/com.mcp.mahavishnu.plist`) exports only `LANG`,
`LOG_LEVEL`, `MAHAVISHNU_OTEL_METRICS_ENABLED`,
`MAHAVISHNU_TOOL_PROFILE`, `MCP_PORT`, the two `OTEL_*` names, and `PATH`
— no `BODAI_BIFROST_VK`.

Pi's `~/.pi/agent/models.json` declares
`apiKey: "$BODAI_BIFROST_VK"` for the `minimax-via-bifrost` provider, and
Pi interpolates `$NAME` from its own environment. With the variable
absent, Pi fails with `No API key found for minimax-via-bifrost`
(reproduced by running the agent with a launchd-equivalent environment).

The repo already has the right resolver:
`mahavishnu.bifrost.cache_headers.resolve_virtual_key()` reads the
environment, then `~/.config/secrets.env` — explicitly for the
"launchd spawns this process without a shell" case.

### 4.4 A fallback provider could inherit the primary's credential

`AgnoLLMConfig.base_url` and `api_key_env` are provider-scoped, but
`_resolve_endpoint` applied them to *every* provider in the chain. With
`provider: minimax` and `fallback_providers: [openai]`, the OpenAI
fallback would have been given `MINIMAX_API_KEY` — the primary's
credential posted to a different vendor's endpoint. Fixed: the configured
overrides apply to the configured provider only.

### 4.5 Three stale test assertions

| Test | Drift |
|---|---|
| `TestAgnoToolsConfigModel::test_default_values` | asserted `mcp_transport == "sse"`; the source has been `streamable-http` since 2026-10-05 |
| `TestAgnoAdapterEntryPoint::test_agno_adapter_entries` | subscripted `agno_adapter_entries()`, which returns `AdapterMetadata` models |
| `tests/unit/test_adapters/test_worker_adapter.py::test_worker_adapter_entries_shape` | the same `AdapterMetadata` drift for the worker adapter |

### 4.6 Bifrost's live store has no `anthropic` provider

`config_providers` in `~/.config/bifrost/config.db` holds `llama-server`,
`minimax-openai`, and `openai` — no `anthropic` row, and no such row in
any of the store backups from 2026-10-29 either. The `anthropic` provider
exists in `config/bifrost/config.template.json` but has never been in the
SQLite store, so the `claude_route` surface 400s for every request.

Repairing it needs an operator decision, because the sanctioned tool is
destructive:

- `mahavishnu bifrost rebootstrap` copies the template to `config.json`
  and restarts the gateway, but the SQLite store is authoritative and is
  *not* re-imported — verified: the provider count was unchanged after a
  rebootstrap.
- `mahavishnu bifrost rebootstrap --drop-db` re-seeds from the template
  (restoring `anthropic`), but drops the virtual key, the dashboard admin
  account, and the governance config, and generates a *new* virtual key —
  every client reading `BIFROST_VIRTUAL_KEY` would need updating.

The adapter-side fix in §5 makes the path correct the moment the provider
is present.

### 4.7 Not addressed: the `search_code` path check

`tests/unit/engines/test_agno_tools.py::TestSearchCode::test_search_code_not_directory`
expects `AgnoError` when the search path is not a directory; the
implementation does not raise. Unrelated to LLM routing — left alone.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-AGNO-006
    title: "The agno.llm block is authoritative over the legacy flat config shapes"
  - id: REQ-AGNO-007
    title: "Per-call provider failover in the Agno agent loop"
  - id: REQ-AGNO-008
    title: "A gateway-routed provider requests a model the gateway serves"
  - id: REQ-AGNO-009
    title: "A fallback provider never inherits the primary's credential or endpoint"
  - id: REQ-PI-006
    title: "The Pi pool resolves the Bifrost virtual key from the canonical source"
```

## 5. Implementation Phases

### Phase 1: Credential and endpoint isolation

**Goal:** a fallback provider never inherits the primary's credential.

**Tasks:**
- `_resolve_endpoint` applies `config.base_url` / `config.api_key_env` only
  to the configured provider; a fallback uses its own standard env var and
  resolves its own endpoint.

#### Integration Contract ← REQUIRED
- **Triggered from:** `LLMProviderFactory._resolve_endpoint`, called from
  `create_model_chain`.
- **Returns to / updates:** the `_ResolvedEndpoint` for each candidate.
- **Demonstrable by:** `pytest tests/unit/test_agno_adapter_impl.py::TestLLMProviderChain`
  — `test_fallback_does_not_inherit_primary_credential` and
  `test_fallback_does_not_inherit_primary_base_url`.
- **Rollback signal:** a fallback provider 401s against a vendor that never
  received its key — the isolation was removed.
- **Observability added:** none (resolution only).

### Phase 2: Per-call failover

**Goal:** a provider that fails mid-run falls through to the next one.

**Tasks:**
- New `mahavishnu/engines/agno_fallback_model.py` with `FallbackModel`,
  an `agno.models.base.Model` subclass overriding `invoke`, `ainvoke`,
  `invoke_stream`, and `ainvoke_stream`.
- `LLMProviderFactory._available_models` builds a model for *every* usable
  provider; `create_model_chain` returns a `FallbackModel` when more than
  one is usable.
- `AgnoAdapter._get_llm` uses the chain.

#### Integration Contract ← REQUIRED
- **Triggered from:** `AgnoAdapter._get_llm` → `create_model_chain`; the
  chain is then invoked once per turn by Agno's agent loop.
- **Returns to / updates:** the model attached to the Agno `Agent`/`Team`.
- **Demonstrable by:**
  `python -c "from mahavishnu.core.config import MahavishnuSettings; ..."`
  printing a `FallbackModel` over `[MiniMax-via-Bifrost, llama-server]`;
  `pytest tests/unit/engines/test_agno_fallback_model.py`.
- **Rollback signal:** `pool`/`agent` runs failing with a provider 5xx
  mid-run instead of completing on the fallback.
- **Observability added:** `WARNING "Agno failover: provider %s failed (%s);
  trying the next provider"` per failover event.

### Phase 3: Gateway model id

**Goal:** a gateway-routed Anthropic provider asks for a served model.

**Tasks:**
- `core/config.py`: `GATEWAY_ANTHROPIC_MODEL_ID = "anthropic/MiniMax-M3"`.
- `_ResolvedEndpoint` carries an optional `gateway_model_id`;
  `_model_id_for` prefers it unless the operator pinned `model_id`.

#### Integration Contract ← REQUIRED
- **Triggered from:** `LLMProviderFactory._resolve_endpoint`.
- **Returns to / updates:** the model id passed to the Agno model.
- **Demonstrable by:** `pytest tests/unit/test_agno_adapter_impl.py::TestBifrostGatewayRouting`.
- **Rollback signal:** `failed to get config for provider anthropic: not found`.
- **Observability added:** the selected model id is logged with the chain.

### Phase 4: Pi pool credential

**Goal:** the Pi subprocess gets the gateway credential regardless of how
the server was launched.

**Tasks:**
- `pi_pool.BODAI_VIRTUAL_KEY_ENV = "BODAI_BIFROST_VK"`.
- `_build_subprocess_env` resolves the credential via
  `bifrost.cache_headers.resolve_virtual_key()` and exposes it under that
  name when the parent env does not carry it.

#### Integration Contract ← REQUIRED
- **Triggered from:** `PiPool.execute_task` and
  `PiPool._startup_version_probe`, both of which build the subprocess env.
- **Returns to / updates:** the Pi subprocess environment.
- **Demonstrable by:** `pytest tests/unit/pools/test_pi_pool_gateway_credential.py`.
- **Rollback signal:** `No API key found for minimax-via-bifrost` in the Pi
  subprocess output.
- **Observability added:** none (the credential is not logged).

### Phase 5: Stale assertions

**Goal:** the three drifting tests pass.

**Tasks:** update the `mcp_transport` assertions and convert the two
`AdapterMetadata` subscript assertions to attribute access.

#### Integration Contract ← REQUIRED
- **Triggered from:** the repo test suite.
- **Returns to / updates:** `tests/unit/test_agno_adapter_impl.py`,
  `tests/unit/engines/test_agno_adapter.py`,
  `tests/unit/test_adapters/test_worker_adapter.py`.
- **Demonstrable by:** `pytest` on those three files.
- **Rollback signal:** n/a (tests only).
- **Observability added:** none.

## 6. Required Code Changes

- [ ] `mahavishnu/core/config.py` — `GATEWAY_ANTHROPIC_MODEL_ID`.
- [ ] `mahavishnu/engines/agno_adapter_impl.py` — endpoint isolation,
      gateway model id, `_available_models`, `create_model_chain`.
- [ ] `mahavishnu/engines/agno_fallback_model.py` — new `FallbackModel`.
- [ ] `mahavishnu/pools/pi_pool.py` — gateway credential resolution.
- [ ] `tests/unit/engines/test_agno_fallback_model.py` — new.
- [ ] `tests/unit/pools/test_pi_pool_gateway_credential.py` — new.
- [ ] `tests/unit/test_agno_adapter_impl.py`,
      `tests/unit/engines/test_agno_adapter.py`,
      `tests/unit/test_adapters/test_worker_adapter.py` — updated assertions.

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `pytest tests/unit/engines/test_agno_fallback_model.py -v` | 12 passed | stdout |
| `pytest tests/unit/pools/test_pi_pool_gateway_credential.py -v` | 5 passed | stdout |
| `pytest tests/unit/test_agno_adapter_impl.py -v` | all pass | stdout |
| `ruff check` / `ruff format --check` on changed files | clean | stdout |
| `ty check` on changed source files | pass | stdout |
| `python scripts/audit_orphans.py` | no orphans dated 2026-10-29 | stdout |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| A fallback provider receives a transcript it cannot parse | low | Agno formats messages itself; every provider in the chain speaks the OpenAI chat-completions shape |
| `FallbackModel` breaks Agno's structured-output path | low | The wrapper mirrors the primary's capability flags |
| The Pi pool hands the gateway key to a third-party subprocess | medium | It is the credential Pi's `models.json` already expects, and the pool is gateway-first by design; the `BIFROST_*` denylist still blocks every other gateway var |
| The gateway's `anthropic` provider stays absent | high | The adapter asks for a served model id, so the path works as soon as the provider is restored; restoring it is §4.6 |

## 9. Decision Rule

Ship when the affected suites pass, the gates are clean, and the live
adapter reports a `FallbackModel` over `[MiniMax-via-Bifrost,
llama-server]`.

## 10. Operator Decision — Deferred Store Repair

Restoring Bifrost's `anthropic` provider to the live store (§4.6) was
put to the operator on 2026-10-29. **Decision: leave the live store
alone.**

Rationale:

1. The adapter-side fix is the durable deliverable — a gateway-routed
   Anthropic provider now requests ``anthropic/MiniMax-M3``, which the
   gateway serves. The path is correct the moment the provider is
   present.
2. The Anthropic provider is not in the active chain
   (``minimax -> llama_server``), so the missing store row does not
   affect the adapter's default behaviour.
3. A concurrent session was actively editing ``config/bifrost/*`` and
   ``mahavishnu/bifrost/gateway.py``, and its plan references
   ``mahavishnu bifrost rebootstrap`` — a store write from this plan
   would risk a write-conflict.
4. The sanctioned repair (``--drop-db``) regenerates the virtual key,
   which every client reads from ``~/.config/secrets.env`` and
   ``~/.claude/settings.json``.

**Follow-up**: if the ``anthropic`` provider is restored to the store
later, no adapter change is needed — the model id is already correct.
