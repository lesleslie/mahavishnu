# Pydantic-Settings Source Resolution Bug — Architecture Followup

**Status:** Resolved. Discovered during the OpenSearch dev-config wiring (June 29, 2026).
**Refs:** `mahavishnu/core/config.py:1814` (`MahavishnuSettings`), `:677-708` (`OpenSearchConfig`), `:1814-1860` (`SettingsConfigDict`), `:2092-2109` (`settings_customise_sources`), `:2023` (`agno: AgnoAdapterConfig`), `:189` (`AgnoAdapterConfig`).

## Resolution

### Root cause

pydantic-settings' built-in `_settings_build_values` (in
`pydantic_settings/main.py`) merges sources with the loop:

```python
state = deep_update(source_state, state)
```

`deep_update(mapping, *updating_mappings)` copies `mapping` as the base
and overlays the `updating_mappings` onto it, so the **older accumulated
state wins** over the newer `source_state`. With the customiser order
`init, mahavishnu.yaml, local.yaml, env, dotenv, secrets`, the loop
effectively applies sources in **reverse** priority — `init` and
`mahavishnu.yaml` mask everything that follows.

The bug is invisible for subtrees absent from `settings/mahavishnu.yaml`
(e.g. `agno`, which is configured only in `settings/local.yaml`) because
the upstream YAML state is empty for that subtree, so later sources
actually appear in the merged state. For subtrees present in
`settings/mahavishnu.yaml` (notably `opensearch`, `auth`, `prefect`,
`pools`, `qc`, `workers`, `llm`, `hatchet`, `oneiric_mcp`, etc.) the YAML
defaults win over both `local.yaml` overrides and `MAHAVISHNU_*` env
vars. The followup's note that `yaml_files=...` in `SettingsConfigDict`
is a typo for `yaml_file` was a red herring; the real bug is in the
merge order, not the key name.

### Fix applied

`mahavishnu/core/config.py:2141-2202` — `MahavishnuSettings._settings_build_values`
override. Two changes:

1. **Reorder sources** so the `InitSettingsSource` is processed last
   (init kwargs remain the documented highest-precedence source).
   Uses `type(source) is InitSettingsSource` (exact type) because
   `YamlConfigSettingsSource` subclasses `InitSettingsSource`.
1. **Swap `deep_update` arguments** from `deep_update(source_state, state)`
   to `deep_update(state, source_state)` so the newer source overlays
   the accumulated state.

Net result: `init_settings > env_settings > dotenv_settings > file_secret_settings > local.yaml > mahavishnu.yaml > defaults`,
which matches the precedence documented in the existing
`MahavishnuSettings` docstring.

### Test coverage added

`tests/unit/test_config_source_resolution.py` (36 tests, all passing):

- **Parametric env-var coverage** (24 cases) — for every nested config
  field on `MahavishnuSettings` that has a primitive leaf (opensearch,
  agno, auth, prefect, otel_ingester, pools, qc, resilience, session,
  workers, llm, hatchet, oneiric_mcp, adapter_registry, dhara_state,
  monitoring, session_buddy_polling, learning, integrations), assert
  that `MAHAVISHNU_<FIELD>__<LEAF>=<value>` is applied.
- **local.yaml coverage** (5 cases) — assert `settings/local.yaml`
  overrides `settings/mahavishnu.yaml` for opensearch, auth, qc.
- **Env > local.yaml** (1 case) — assert env wins over local.yaml.
- **Init kwargs > everything** (1 case) — assert `MahavishnuSettings(opensearch=...)`
  wins over env vars.
- **Defaults unchanged** (1 case) — assert defaults stand when no
  overrides are set.
- **Multi-level deep paths** (2 cases) — `agno.llm.provider` and
  `hatchet.namespace` (3-level deep).

### Verification

```
$ uv run pytest tests/unit/test_config_source_resolution.py
36 passed
$ uv run pytest tests/unit/test_config*.py tests/property/test_config_properties.py
261 passed
$ uv run ruff check mahavishnu/core/config.py tests/unit/test_config_source_resolution.py
All checks passed!
$ uv run ruff format --check mahavishnu/core/config.py tests/unit/test_config_source_resolution.py
2 files already formatted
```

The reproduction from the followup now passes:

```
$ MAHAVISHNU_AGNO__LLM__PROVIDER=minimax \
  MAHAVISHNU_OPENSEARCH__ENDPOINT=http://localhost:9200 \
  MAHAVISHNU_OPENSEARCH__USE_SSL=false \
  uv run python -c "from mahavishnu.core.config import MahavishnuSettings; \
                    s = MahavishnuSettings(); \
                    print(s.agno.llm.provider, s.opensearch.endpoint, s.opensearch.use_ssl)"
minimax http://localhost:9200 False
```

## Background

A reproducible bug in how `MahavishnuSettings` resolves values from layered sources (init kwargs, YAML files, env vars). Env vars and `local.yaml` overrides work for the `agno` subtree but are **silently ignored** for the `opensearch` subtree.

### Reproduction (from `uv run python -c "..."` against the live codebase)

Set env vars on the command line and instantiate `MahavishnuSettings`:

```bash
MAHAVISHNU_AGNO__LLM__PROVIDER=minimax \
MAHAVISHNU_OPENSEARCH__ENDPOINT=http://localhost:9200 \
MAHAVISHNU_OPENSEARCH__USE_SSL=false \
  uv run python -c "from mahavishnu.core.config import MahavishnuSettings; \
                     s = MahavishnuSettings(); \
                     print(s.agno.llm.provider, s.opensearch.endpoint, s.opensearch.use_ssl)"
```

Actual output:

```
minimax https://localhost:9200 True
```

Expected output:

```
minimax http://localhost:9200 False
```

The Agno env var applies; the OpenSearch env vars are silently overridden by the YAML default from `settings/mahavishnu.yaml:48-55` (`endpoint: https://localhost:9200`, `use_ssl: true`).

### What still works for `opensearch`

- `MahavishnuSettings(opensearch={"endpoint": "http://localhost:9200", ...})` (init kwargs) — works ✓
- `s.opensearch.endpoint = "http://localhost:9200"` (post-mutation) — works ✓
- The integration itself (`OpenSearchIntegration.health_check()`) — returns `{"status": "healthy", ...}` once the right config is passed in

### What does NOT work for `opensearch`

- Env vars (`MAHAVISHNU_OPENSEARCH__*`) — silently ignored
- `settings/local.yaml` overrides — silently ignored
- This is the same on `endpoint`, `use_ssl`, `verify_certs`, `ssl_assert_hostname` (all four fields tested)

### Ruled out

- **Validators** — `OpenSearchConfig` has no `field_validator` or `model_validator` (lines 677-708). Verified.
- **Field declarations** — `opensearch: OpenSearchConfig = Field(default_factory=OpenSearchConfig)` at line 1941 is identical to `agno: AgnoAdapterConfig = Field(default_factory=AgnoAdapterConfig)` at line 2023 (both default_factory, no alias, no validation_alias).
- **Post-init** — no `__post_init__` or `model_post_init` on either side.
- **XDG layers** — `~/.config/mahavishnu/` does not exist; `MAHAVISHNU_CONFIG` env var is unset.
- **Pydantic-settings source customizer** — `settings_customise_sources` (lines 2092-2109) adds both YAML files plus env_settings, in the standard order; nothing about the customizer explains the asymmetry.

## Why out of scope

This is a debug task that requires focused time on pydantic-settings source resolution semantics — likely a 1-2 hour investigation, possibly involving a minimal repro outside the Mahavishnu codebase. Out of scope for the current runbook + Crow fix + dev-config PRs. Also requires auditing **every other nested config** for the same silent-ignore failure mode, which is broader than a single-file fix.

Risks of inlining into the current PR:

- Couples a debug session to documentation/config changes
- The fix might span `config.py` (`SettingsConfigDict` params) AND `settings_customise_sources` AND per-config-class `model_config` choices — not a one-line change as originally hypothesized
- Other configs that today look "fine" (because YAML defaults match production) might be silently broken too — better to audit holistically than patch one

## Proposed remediation

1. **Minimal repro outside the codebase.** Build a 30-line standalone pydantic-settings script that mirrors `MahavishnuSettings`'s `model_config` (`yaml_files`, `env_prefix`, `env_nested_delimiter`, `extra`) and a `settings_customise_sources` that adds both YAML files. Reproduce the asymmetry between two nested `BaseModel` subtrees (one nested, one flat, or with different `extra` settings) and bisect.

1. **Audit all nested configs.** Once the root cause is known, scan every nested `BaseModel` field on `MahavishnuSettings` and verify env-var + local.yaml overrides apply. At minimum:

   - `agno` (works)
   - `opensearch` (broken)
   - `auth` (works in tests, but only when `enabled=True` — partial)
   - `prefect`, `otel_storage`, `otel_ingester`, `adapters`, `llm`, `terminal`, `pools`, `workflow_state`, `health` — all need the same probe

1. **Likely fix locations** (in order of probability):

   - The `yaml_files` field in `SettingsConfigDict` is **not a real pydantic-settings field** — pydantic-settings uses `yaml_file` (singular). The plural `yaml_files` in `model_config` is being silently ignored, while `settings_customise_sources` adds the YAML sources manually. The customizer's source ordering may interact badly with `case_sensitive=False` or `nested_model_default_partial_update`.
   - Move from custom `settings_customise_sources` to pydantic-settings' native `yaml_file` config (single path) plus `init_kwargs` precedence.
   - Or remove `extra="forbid"` from the nested models and rely on `extra="ignore"` with explicit field whitelisting at the parent.

1. **Add a regression test** at `tests/unit/test_config_source_resolution.py` that:

   - For each nested config field, sets an env var and asserts the value is applied
   - For each nested config field, writes a `local.yaml` override and asserts the value is applied
   - Fails fast if any nested subtree goes back to silent-ignore mode

## References

- `mahavishnu/core/config.py:677-708` — `OpenSearchConfig` declaration (the affected model)
- `mahavishnu/core/config.py:1814-1860` — `MahavishnuSettings.model_config` (SettingsConfigDict)
- `mahavishnu/core/config.py:1941-1945` — `opensearch` field declaration on `MahavishnuSettings`
- `mahavishnu/core/config.py:2023-2027` — `agno` field declaration on `MahavishnuSettings` (the working model)
- `mahavishnu/core/config.py:2092-2109` — `settings_customise_sources` (custom YAML source loader)
- `mahavishnu/engines/agno_adapter_impl.py:425-429` — Agno adapter's `_get_api_key("MINIMAX_API_KEY", ...)` (downstream consumer that exposes the asymmetry)
- `mahavishnu/core/opensearch_integration.py:370-388` — `health_check()` method (returns misleading "Cannot connect to OpenSearch" when the underlying cause is config-not-applied)
- Reproduction script in Background section above
