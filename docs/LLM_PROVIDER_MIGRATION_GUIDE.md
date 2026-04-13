# Adding a New LLM Provider to the Bodai Ecosystem

This guide documents how to add a new LLM provider (e.g., Qwen, DeepSeek, Mistral) to the Bodai ecosystem following the patterns established in the ZAI reconfiguration (April 2026).

## Overview

All LLM providers in the ecosystem use the OpenAI-compatible API pattern. This means any provider with an OpenAI-compatible chat completions endpoint can be integrated with minimal code changes.

## Step-by-Step Process

### Step 1: Add Provider Configuration to mcp-common

File: `mcp_common/llm/config.py`

The provider will use `OpenAICompatibleProvider` automatically — no new provider class needed.

```yaml
# settings/models.yaml or settings/llm.yaml
new_provider:
  enabled: true
  base_url: "https://api.newprovider.com/v1"
  api_key: "${NEW_PROVIDER_API_KEY}"
  priority: 3  # Lower = preferred
  timeout: 30
  max_retries: 2
  task_routing:
    CODE_GENERATION: "provider-model-id"
    GENERAL: "provider-general-model"
```

### Step 2: Add Settings Fields

For each repo that uses the provider, add settings fields:

**Session-Buddy** (`session_buddy/settings.py`):
```python
new_provider_api_key: str | None = Field(
    default=None,
    description="New provider API key (overrides NEW_PROVIDER_API_KEY)",
)
```

Update `get_llm_api_key()` field_map:
```python
field_map = {
    ...
    "new_provider": "new_provider_api_key",
}
```

**Crackerjack** (`crackerjack/config/settings.py`):
Add to the AI settings or load from YAML.

### Step 3: Register the Provider

**Session-Buddy** (`session_buddy/llm_providers.py`):

1. Add env var mapping in `_get_provider_api_key_and_env()`:
```python
"new_provider": "NEW_PROVIDER_API_KEY",
```

2. Add to `_get_configured_providers()`:
```python
"NEW_PROVIDER_API_KEY": "new_provider",
```

3. Add config loading in `_load_config()`:
```python
if not config["providers"].get("new_provider"):
    config["providers"]["new_provider"] = {
        "api_key": os.getenv("NEW_PROVIDER_API_KEY"),
        "base_url": os.getenv("NEW_PROVIDER_BASE_URL", "https://api.newprovider.com/v1"),
        "default_model": os.getenv("NEW_PROVIDER_DEFAULT_MODEL", "default-model"),
    }
```

4. Add to `_initialize_providers()`:
```python
"new_provider": OpenAIProvider,  # Uses OpenAI-compatible API
```

**Crackerjack** (`crackerjack/adapters/ai/registry.py`):
1. Add to `ProviderID` enum
2. Register in `ProviderFactory`

### Step 4: Update Fallback Chain

**Session-Buddy** (`settings.py`):
```python
llm_fallback_chain: list[str] = Field(
    default=["zai", "new_provider", "ollama"],
    description="Ordered list of LLM providers for fallback",
)
```

### Step 5: Add Tests

Follow the pattern in `tests/integration/test_zai_fallback_chain.py`:

```python
class TestNewProviderFallback:
    @pytest.mark.asyncio
    async def test_fallback_to_new_provider_when_zai_unavailable(self, messages):
        # Mock ZAI as unavailable
        # Mock new_provider as available
        # Verify fallback works
        ...
```

### Step 6: Update CLAUDE.md

Add the new provider to the LLM configuration section in each repo's CLAUDE.md.

## Key Principles

1. **OpenAI-Compatible First**: All providers use `OpenAIProvider` or `OpenAICompatibleProvider`. No custom provider classes needed.

2. **YAML-Driven Configuration**: Provider settings come from YAML files with env var resolution (`${ENV_VAR}`).

3. **Fallback Chain**: Every provider should have a fallback. The chain is `primary → secondary → ollama`.

4. **API Key Security**: Use `SecretStr` in Pydantic models. Never log full API keys.

5. **Task-Based Routing**: Map task categories to optimal models per provider.

## File Reference

| Repository | Files to Modify |
|-----------|----------------|
| mcp-common | `mcp_common/llm/config.py`, `mcp_common/llm/provider.py` |
| Session-Buddy | `settings.py`, `llm_providers.py`, `llm/security.py` |
| Crackerjack | `config/settings.py`, `adapters/ai/registry.py` |
| Mahavishnu | `settings/models.yaml`, `workers/task_router.py` |

## Testing Checklist

- [ ] Provider initializes correctly with valid API key
- [ ] Provider falls back to next in chain when unavailable
- [ ] API key masking works correctly
- [ ] Task routing selects correct model
- [ ] Free tier fallback works (if applicable)
- [ ] CLAUDE.md updated in all repos
- [ ] Integration tests pass
