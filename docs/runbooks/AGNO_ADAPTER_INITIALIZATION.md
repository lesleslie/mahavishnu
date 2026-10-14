# Agno Adapter Initialization — Operator Runbook

**Status:** Active. Use when `get_health` reports the Agno adapter as healthy (`adapter: "agno"` present) but with `agents_cached=0, mcp_tools_initialized=false`.

**Plan:** `docs/AGNO_ADAPTER_IMPLEMENTATION_PLAN.md`

## 1. Severity

**Medium.** The orchestration engine is wired into the health surface (the adapter is reachable), but it has no agents in cache and no MCP tools initialized. Workflows that route to the `agno` adapter will fail at dispatch with `NoAgentsAvailable` or equivalent. Other adapters (Prefect, LlamaIndex) are unaffected.

## 2. Detection

Run the MCP `get_health` tool or `mahavishnu mcp health` from the CLI. Look for the `agno` block in the adapters section. An unhealthy initialization looks like:

```yaml
status: "degraded"
adapters:
  agno:
    adapter: "agno"
    enabled: true
    healthy: true
    agents_cached: 0
    mcp_tools_initialized: false
    last_error: null   # often null even on init failure; check logs
```

Healthy shape (target):

```yaml
status: "healthy"
adapters:
  agno:
    adapter: "agno"
    enabled: true
    healthy: true
    agents_cached: 3   # matches teams_config_path agent count
    mcp_tools_initialized: true
```

The status block at `mahavishnu/engines/agno_adapter_impl.py:1527-1568` is the single source of truth for these fields. If `agents_cached=0` and `mcp_tools_initialized=false` persist for more than one boot, treat it as a configuration problem and proceed to Diagnosis.

## 3. Diagnosis

Two failure modes account for nearly every case. The master switch is **already on by default**, so failure mode 2 (initialize failed) is the common one.

### 3.1 Master switch off

Rare. The default in `settings/mahavishnu.yaml:30` is `adapters.agno_enabled: true`, so this only fires if an operator deliberately disabled it or an env override is set.

```bash
# Check the committed default
grep -n "agno_enabled" settings/mahavishnu.yaml

# Check for an env override that wins over YAML
env | grep -i MAHAVISHNU_AGNO__ENABLED
```

If `MAHAVISHNU_AGNO__ENABLED=0` is set, that is the cause. Fix by unsetting it or by setting `adapters.agno_enabled: true` in `settings/local.yaml`.

### 3.2 Initialize failed (`agno_enabled: true` but init raised)

This is the common case. `AgnoAdapter.initialize()` populates `_agents` and `_mcp_registry`; if it raises (missing API key, unreachable provider, bad model id), both remain empty and the status block reports zeros and `false`.

```bash
# 1. Is the LLM API key present?
env | grep MAHAVISHNU_AGNO__LLM__API_KEY   # should print a non-empty value

# 2. Is the provider one we support?
env | grep MAHAVISHNU_AGNO__LLM__PROVIDER  # expect: anthropic | openai | minimax | ollama

# 3. Is the base URL reachable from this host?
curl -fsS --max-time 5 "$MAHAVISHNU_AGNO__LLM__BASE_URL/v1/models"
# Anthropic: https://api.anthropic.com
# OpenAI-compatible (OpenAI / MiniMax / Ollama): see provider docs

# 4. Memory backend reachable?
env | grep MAHAVISHNU_AGNO__MEMORY__BACKEND         # expect: sqlite | postgres | none
env |grep MAHAVISHNU_AGNO__MEMORY__CONNECTION_STRING  # required if backend=postgres
```

If any of those checks fails, the corresponding env var is the problem.

## 4. Remediation

Numbered steps. Apply in order; each step is independently reversible.

1. **Set the API key.** Confirm `MAHAVISHNU_AGNO__LLM__API_KEY` is exported in the shell that started the MCP server. Use a non-empty value — a literal `"changeme"` or empty string triggers init failure. Restart the server after changing it.

   ```bash
   export MAHAVISHNU_AGNO__LLM__API_KEY="sk-..."   # load from your secrets manager
   ```

1. **Pick a supported provider.** `MAHAVISHNU_AGNO__LLM__PROVIDER` must be one of `anthropic`, `openai`, `minimax`, `ollama`. Typos (`antropic`, `minimaxio`) and unsupported names (`bedrock`, `vertex`) silently fail inside `initialize()`. Local fallbacks (`ollama` at `http://localhost:11434`, `llama_server` at `http://localhost:8081`) work without a cloud key.

   ```bash
   export MAHAVISHNU_AGNO__LLM__PROVIDER="anthropic"
   export MAHAVISHNU_AGNO__LLM__MODEL_ID="claude-sonnet-4-5"
   ```

1. **Confirm `BASE_URL` is reachable.** The `curl` above must return `2xx`. For Anthropic, the expected base is `https://api.anthropic.com`. For OpenAI-compatible providers, append `/v1/models` to whatever your proxy publishes.

   ```bash
   export MAHAVISHNU_AGNO__LLM__BASE_URL="https://api.anthropic.com"
   curl -fsS --max-time 5 "$MAHAVISHNU_AGNO__LLM__BASE_URL/v1/models"
   ```

1. **If using Postgres memory, set the connection string.** `MAHAVISHNU_AGNO__MEMORY__BACKEND=postgres` requires `MAHAVISHNU_AGNO__MEMORY__CONNECTION_STRING` in standard DSN form. A missing string with `backend=postgres` raises during init, while `backend=sqlite` (the default if unset) needs nothing.

   ```bash
   export MAHAVISHNU_AGNO__MEMORY__BACKEND="postgres"
   export MAHAVISHNU_AGNO__MEMORY__CONNECTION_STRING="postgresql://user:pass@host:5432/agno"
   ```

1. **Persist in `settings/local.yaml`** if these values are environment-specific. Follow the inline `# comment` style already used in `settings/local.yaml.example`:

   ```yaml
   adapters:
     agno_enabled: true   # master switch, default true; only set false to disable

   agno:
     llm:
       provider: "anthropic"
       model_id: "claude-sonnet-4-5"
       api_key: "sk-..."   # prefer MAHAVISHNU_AGNO__LLM__API_KEY over in-YAML secrets
       base_url: "https://api.anthropic.com"
     memory:
       backend: "sqlite"   # sqlite | postgres | none
       connection_string: ""   # required only when backend=postgres
     telemetry_enabled: false
   ```

1. **Restart the MCP server.** Configuration loaded at startup; an in-process reload won't pick up env changes.

   ```bash
   mahavishnu mcp restart
   ```

## 5. Verification

Re-run health and confirm the Agno block reports initialized state.

```bash
mahavishnu mcp health
# or via MCP tool:
# mcp__mahavishnu__get_health()
```

Healthy Agno shape:

```yaml
status: "healthy"
adapters:
  agno:
    adapter: "agno"
    enabled: true
    healthy: true
    agents_cached: 3   # > 0 confirms initialize() populated self._agents
    mcp_tools_initialized: true   # confirms _mcp_registry._initialized is True
```

Pass criteria: `agents_cached > 0` AND `mcp_tools_initialized: true`. Anything else means `initialize()` still raised — re-check the four env vars from section 4 against the Diagnosis grep commands.

Smoke-test dispatch with one workflow to confirm the adapter actually runs agents end-to-end:

```bash
mahavishnu pool route --prompt "summarize: hello world" --selector least_loaded
```

If the routed worker reports `engine: agno` and returns a result, the adapter is fully operational.

## 6. References

- `mahavishnu/engines/agno_adapter_impl.py:1527-1568` — adapter status block (`agents_cached`, `mcp_tools_initialized`, `healthy`)
- `mahavishnu/core/config.py:2023` — `AgnoAdapterConfig` Pydantic model (`llm`, `memory`, `tools`, `teams_config_path`, `default_timeout_seconds`, `max_concurrent_agents`, `telemetry_enabled`)
- `settings/mahavishnu.yaml:30` — `adapters.agno_enabled` master switch (defaults `true`)
- `docs/AGNO_ADAPTER_IMPLEMENTATION_PLAN.md` — implementation roadmap and configuration surface
