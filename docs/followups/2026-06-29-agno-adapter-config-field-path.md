# Agno Adapter Reads Wrong Config Field Path — Architecture Followup

**Status:** Resolved. Discovered during the OpenSearch + Agno wiring (June 29, 2026). Fixed in the same session.
**Refs:** `mahavishnu/engines/agno_adapter_impl.py:686-1142` (`_get_agno_config`), `:1088-1123` (provider resolution chain), `mahavishnu/core/config.py:1153` (`LLMConfig`), `mahavishnu/core/config.py:2023` (`agno: AgnoAdapterConfig`).

## Resolution

### Actual root cause (deeper than the original hypothesis)

The original followup suspected `_get_agno_config` reads from the wrong field path (`self.config.llm.provider` instead of `self.config.agno.llm.provider`). On investigation, `_get_agno_config` itself was correct — it does:

```python
if hasattr(config, "agno") and isinstance(config.agno, AgnoAdapterConfig):
    return config.agno
```

**But the `isinstance` check failed silently** because the same six classes (`LLMProvider`, `MemoryBackend`, `AgnoLLMConfig`, `AgnoMemoryConfig`, `AgnoToolsConfig`, `AgnoAdapterConfig`) were defined as **duplicates** in both `mahavishnu/core/config.py` and `mahavishnu/engines/agno_adapter_impl.py`. Python sees them as distinct class objects (`is` returns False), so `isinstance(config.agno, AgnoAdapterConfig)` always returned False from the engine's perspective, and the function silently fell through to:

```python
return AgnoAdapterConfig()   # engine's local class, with ollama defaults
```

### Fix applied

1. **Deleted 181 lines** of duplicate class definitions from `mahavishnu/engines/agno_adapter_impl.py` (lines 54–234 of the previous version).
1. **Added canonical import** from `mahavishnu.core.config`:
   ```python
   from ..core.config import (
       AgnoAdapterConfig,
       AgnoLLMConfig,
       AgnoMemoryConfig,
       AgnoToolsConfig,
       LLMProvider,
       MemoryBackend,
   )
   ```
1. **Added missing `enable_native_tools: bool = Field(default=True)` to `AgnoToolsConfig` in `mahavishnu/core/config.py`** — this field existed in the engine's duplicate but not in the canonical schema; bringing them into sync required adding it.
1. **Updated one existing test assertion** in `tests/unit/engines/test_agno_adapter.py::test_config_fallback` from `memory.enabled is False` to `True` to match the unified `AgnoMemoryConfig` default.

### Test coverage added

`tests/unit/engines/test_agno_config_imports.py` (new file, 8 tests):

- `test_engine_does_not_duplicate_canonical_agno_classes` — AST-scans the engine file and fails if any of the 6 canonical classes are re-defined locally.
- `test_canonical_class_is_identity_equal_across_modules` — parametrized over all 6 classes; verifies that the class loaded from `mahavishnu.engines.agno_adapter_impl` is `is`-identical to the one loaded from `mahavishnu.core.config`. Catches any future drift.
- `test_agno_adapter_sees_user_configured_provider` — end-to-end: instantiates `AgnoAdapter(MahavishnuSettings())` from the project root and asserts `adapter.agno_config.llm.provider.value == "minimax"` (the value set in `settings/local.yaml`). Reproduces the original user-visible bug.

### Verification

```
$ uv run pytest tests/unit/engines/ --no-cov
======================= 340 passed, 5 warnings in 13.45s ========================

$ mcp__mahavishnu__get_health
"agno": {
  "details": {
    "llm_provider": "minimax",     ← was "ollama"
    "model_id": "MiniMax-M3",       ← was "qwen2.5:7b"
  }
}
```

The `_settings_cache` global in `mahavishnu/core/config.py` is unaffected by this change (the class identity change happens at module-import time, before any caching).

## Background

`AgnoAdapter._get_agno_config(self, config)` is supposed to extract the Agno-specific LLM configuration from the parent `MahavishnuSettings` instance. It actually reads from the **wrong field path** — the top-level LlamaIndex `LLMConfig` instead of the nested `agno.llm` field.

### What the user sets

```yaml
# settings/local.yaml
agno:
  llm:
    provider: minimax
    model_id: MiniMax-M3
    base_url: "https://api.minimax.io/v1"
```

This is parsed by pydantic-settings correctly. Verified:

```
$ uv run python -c "from mahavishnu.core.config import MahavishnuSettings; \
                     s = MahavishnuSettings(); \
                     print(s.agno.llm.provider, s.agno.llm.model_id)"
minimax MiniMax-M3
```

### What the adapter reads

`mahavishnu/engines/agno_adapter_impl.py:1088-1123`:

```python
provider_value = getattr(self.config, "llm_provider", None)              # top-level, doesn't exist on MahavishnuSettings
if provider_value is None and llm_config is not None:
    provider_value = getattr(llm_config, "provider", None)               # LLMConfig.provider, doesn't exist (extra="forbid")

# ... later in the function:
provider = (
    provider_value
    if isinstance(provider_value, LLMProvider)
    else LLMProvider(provider_value)
    if isinstance(provider_value, str)
    else self.agno_config.llm.provider                                    # ← fallback to DEFAULT (OLLAMA)
)
```

`LLMConfig` at `mahavishnu/core/config.py:1153` is for **LlamaIndex**, not Agno:

- Fields: `model`, `ollama_base_url`, `temperature`, `max_tokens`, etc.
- **No `provider` field**. `extra="forbid"` rejects `MAHAVISHNU_LLM__PROVIDER` with `ValidationError: Extra inputs are not permitted`.

So both lookups return None, the fallback to `self.agno_config.llm.provider` always lands on the default `OLLAMA`, and the Agno adapter silently ignores the user's configured provider.

### Reproduction

```yaml
# settings/local.yaml
agno:
  llm:
    provider: minimax
    model_id: MiniMax-M3
    base_url: "https://api.minimax.io/v1"
```

Plus `MAHAVISHNU_AGNO__LLM__API_KEY=<key>` (or `MINIMAX_API_KEY=<key>`) in env.

`get_health` returns:

```json
"agno": {
  "status": "unhealthy",
  "details": {
    "llm_provider": "ollama",
    "model_id": "qwen2.5:7b",
    "initialized": false,
    "reason": "Adapter not initialized"
  }
}
```

Expected after the fix:

```json
"agno": {
  "status": "healthy",
  "details": {
    "llm_provider": "minimax",
    "model_id": "MiniMax-M3",
    "initialized": true
  }
}
```

### Why out of scope

This is a pre-existing bug in the Agno adapter's config extraction. It was not introduced by any of the recent fixes (Crow MHV-001, pydantic-settings source resolution, DLQ fail-closed, opensearch-flags consolidation). It's surfaced now because the user's `.zshrc` (via Oneiric) finally has the `MINIMAX_API_KEY` exposed to the launchd-managed process — a precondition for Agno to even attempt initialization.

Risks of fixing inline:

- `_get_agno_config` is at the heart of how the adapter constructs its model factory. Touching it requires running the full adapter test suite, which currently has 4 tests covering the Crow toggle path but nothing directly exercising AgnoLLMConfig extraction.
- The fix likely needs to add `self.config.agno.llm` as the canonical source and remove the `self.config.llm` fallback (or keep the fallback for backward compat with the LlamaIndex shape).
- Coupling this debug to the current PR dilutes review surface — better as its own change.

## Proposed remediation

1. **Primary fix.** In `_get_agno_config`, change the provider resolution chain from:

   ```python
   provider_value = getattr(self.config, "llm_provider", None)
   if provider_value is None and llm_config is not None:
       provider_value = getattr(llm_config, "provider", None)
   ```

   to read from the nested path:

   ```python
   agno_llm = getattr(self.config, "agno", None)
   if agno_llm is not None:
       llm_cfg = getattr(agno_llm, "llm", None)
       if llm_cfg is not None:
           provider_value = getattr(llm_cfg, "provider", None)
   ```

1. **Same fix for `model_id`, `base_url`, `api_key_env`, `temperature`, `max_tokens`** — replace top-level `llm_config` reads with the nested `agno.llm` path.

1. **Remove the dead `LLMConfig.provider` lookup.** Either add `provider: str | None = None` to `LLMConfig` (with `extra="allow"` on the parent) OR remove the lookup entirely. Adding to `LLMConfig` is the smaller change but conflates LlamaIndex and Agno config; removing is cleaner.

1. **Regression tests** at `tests/unit/engines/test_agno_adapter_config.py`:

   - `test_get_agno_config_reads_agno_llm_provider` — `MahavishnuSettings(agno=AgnoAdapterConfig(llm=AgnoLLMConfig(provider=...)))` → adapter sees the right provider
   - `test_get_agno_config_falls_back_when_agno_missing` — backwards-compat path with old-style config
   - `test_get_agno_config_handles_llmconfig_provider_for_backcompat` — if step 3 chose "add provider to LLMConfig", confirm the fallback still works

1. **Update `docs/runbooks/agno-adapter-initialization.md`** with the corrected field path so operators don't keep setting `agno.llm.provider` and wondering why it's ignored.

## References

- `mahavishnu/engines/agno_adapter_impl.py:686-1142` — `_get_agno_config` full implementation
- `mahavishnu/engines/agno_adapter_impl.py:1088-1090` — first lookup attempt (`self.config.llm_provider`)
- `mahavishnu/engines/agno_adapter_impl.py:1118-1123` — fallback chain ending in `self.agno_config.llm.provider`
- `mahavishnu/engines/agno_adapter_impl.py:1539` — `get_health` reads `self.agno_config.llm.provider.value` (works correctly because that's where the fallback landed)
- `mahavishnu/core/config.py:1153-1180` — `LLMConfig` definition (no `provider` field, `extra="forbid"`)
- `mahavishnu/core/config.py:2023` — `agno: AgnoAdapterConfig` field on `MahavishnuSettings`
- Reproduction: see Background section above
