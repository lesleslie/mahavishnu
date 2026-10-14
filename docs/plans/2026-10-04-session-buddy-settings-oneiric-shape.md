---
date: 2026-10-04
status: active
role: implementation
topic: session-buddy-settings-oneiric-shape
last_reviewed: 2026-10-04
superseded_by: null
---

# Plan: Convert `SessionMgmtSettings` → `SessionBuddySettings` (Oneiric-shaped)

## Context

**Why this change**: Session-buddy's `SessionMgmtSettings` is a flat
`OneiricMCPConfig` subclass with **95+ top-level fields** and only two
nested groups (`LLMProvidersConfig`, `BodaiEventsConfig`). This is the
opposite of the Oneiric settings convention used by the rest of the
Bodai fleet:

- **OneiricSettings** (`oneiric/core/config.py:245`) — nested
  `app`/`adapters`/`services`/`secrets`/`logging`/`lifecycle`/`plugins`/`profile`/`runtime_paths`/`runtime_supervisor` groups, all
  `extra="forbid"`, recursive `_deep_merge` across config layers.
- **MahavishnuSettings** (`mahavishnu/core/config.py:2627`) — ~60 leaf
  `*Config(BaseModel)` groups, all `extra="forbid"`, two-level nesting
  (e.g. `agno.llm`, `pool.target_size`).

The flat shape has caused four concrete problems:

1. **Drift** — `local.yaml`'s partial `llm_providers:` block was wiped
   the moment a flat-YAML loader loop overwrote nested dicts (fixed
   2026-10-04 in commit `941d4536`); the underlying duplication of
   `default_provider` vs `default_llm_provider`, `fallback_providers` vs
   `llm_fallback_chain` remains.
2. **Dead code** — the `LLMProvidersConfig` nested block is read by
   exactly one test and one cosmetic `llm/base.py:25` logger-name
   string; the production path goes through the flat
   `get_llm_api_key()` lookup table.
3. **Loader complexity** — `load()` (settings.py:849-938) has a manual
   flat-YAML re-read loop because `_oneiric_load` returns a
   `OneiricSettings` instance that doesn't know about session-buddy's
   flat fields. OneiricSettings already does `_deep_merge`
   (oneiric/core/config.py:728-739), so the whole flat-YAML loop can
   be deleted once the schema matches.
4. **Inconsistent `extra` policy** — flat top-level fields silently
   accept any operator typo (e.g. `database_pat:` in YAML becomes
   a no-op override); nested groups under `extra="forbid"` reject
   typos at parse time, catching config drift at startup.

**Intended outcome**:

- `SessionMgmtSettings` → `SessionBuddySettings(OneiricMCPConfig)`
  composed of ~22 nested `*Config(BaseModel)` groups (one per
  domain). Every leaf group sets `extra="forbid"`.
- Every flat field reorganized into its domain group (e.g.
  `database_path` → `database.path`, `minimax_api_key` →
  `llm.api_keys.minimax`, `enable_conscious_agent` →
  `feature_flags.enable_conscious_agent`).
- All consumer code rewired to read the new shape, **including all
  `getattr(settings, "X", default)` defensive sites** (the biggest
  silent-regression risk).
- `settings/session-buddy.yaml` and `settings/local.yaml` re-nested
  to match the Oneiric convention.
- Manual flat-YAML loader loop deleted; Oneiric's loader becomes
  the single source of truth.
- The existing CLI-side `SessionBuddySettings` classes in
  `cli/base.py:72` and `cli_with_modes.py:50` are **renamed to
  `CLILaunchSettings`** to clear the name before the new schema
  class is introduced.
- Env vars adopt the Oneiric prefix + nested-delimiter pattern:
  `SESSION_BUDDY_LLM__DEFAULT_PROVIDER` (was: `SESSION_BUDDY_*` flat
  on `MCPBaseSettings`).

**Repo**: `/Users/les/Projects/session-buddy` (working tree clean, on
`main`, ahead 3 of `origin/main`).

## Scope (from inventory)

- **~27 production files** consume flat fields (mcp/server.py,
  adapters/storage_oneiric.py, llm/security.py,
  storage/akosha_config.py, feature_flags.py, doctor.py,
  mcp/tools/*, memory/*, core/*, cli/*, utils/*).
- **~50 test files** touch settings (mock_settings fixture in
  `tests/conftest.py:1312-1431` sets every flat attribute by hand;
  ~30 test files assert on flat field defaults).
- **~95 flat fields** to migrate into nested groups.
- **2 existing nested groups** (`LLMProvidersConfig`,
  `BodaiEventsConfig`) — `BodaiEventsConfig` stays; `LLMProvidersConfig`
  is absorbed into the new `LLMConfig` group.
- **Adapter settings dataclasses** (`StorageAdapterSettings`,
  `ReflectionAdapterSettings`, `KnowledgeGraphAdapterSettings`) — out of
  scope; they live on adapter classes, not on SessionMgmtSettings.

## Plan structure — 3 PRs, smallest revert surface

Per `feedback-bodai-merge-workflow`, this is one logical change but
ships as 3 reviewable PRs so each phase is reviewable and the high-
blast-radius work is isolated.

### PR 1 — Schema + loader (Phases 1, 2 below; ~15 files)

Rename CLI's `SessionBuddySettings` to clear the name. Introduce the
new schema. Replace the manual flat-YAML loader with Oneiric's
loader. No production-consumer rewiring, no YAML reshape yet.

### PR 2 — Consumer migration + tests (Phases 3, 5 below; ~50 files)

Rewire every production reader to `settings.<group>.<field>`. Rewrite
every test file's flat-key asserts into nested form. **Biggest
revert surface if a runtime regression slips past the smoke tests.**

### PR 3 — YAML reshape + CLI rename fallout + docs (Phases 4, 6 below; ~10 files)

Re-nest `settings/session-buddy.yaml` and `settings/local.yaml` to
match the new schema. Update `~/.config/session-buddy/local.yaml`
comments. Update docs and the audit script.

## Phase 1 — Schema + class skeleton

### 1a. Pre-phase: rename existing CLI-side `SessionBuddySettings` classes

**Blocker** flagged by all 3 reviewers: a class named
`SessionBuddySettings` already exists at
`session_buddy/cli/base.py:72` and again at
`session_buddy/cli_with_modes.py:50`. Both extend
`OneiricMCPConfig` and both are imported by ~20 test files (via
`session_buddy/cli/__init__.py:28,69`).

**Rename both classes to `CLILaunchSettings` BEFORE introducing the
new schema class.** The CLI ones are launch/transport-only (a
handful of fields and the three path-helper methods); `CLILaunchSettings`
captures their scope better than `SessionBuddySettings`.

Files touched:
- `session_buddy/cli/base.py:72` — class rename + import-site
  updates inside the file
- `session_buddy/cli_with_modes.py:50` — same
- `session_buddy/cli/__init__.py:28,69` — re-export name
- 20+ test files under `tests/` and `tests/cli/` that reference
  `from session_buddy.cli import SessionBuddySettings` (grep + replace
  `SessionBuddySettings` → `CLILaunchSettings`)

### 1b. Define all `*Config` groups in `session_buddy/settings.py`

Add (above the existing `SessionMgmtSettings`):

```python
from pydantic import ConfigDict

class _BaseConfig(BaseModel):
    """Base for every nested ``*Config`` group.

    Adds the Oneiric/Mahavishnu ``extra=\"forbid\"`` policy so typo'd
    YAML keys raise a parse error rather than silently being ignored.
    """
    model_config = ConfigDict(extra="forbid")
```

Then one `<Domain>Config(_BaseConfig)` class per row in the Proposed
group structure table below. Field types, defaults, validators, and
`ge`/`le`/`min_length` constraints are copied verbatim from the
current flat declarations.

### 1c. Define `SessionBuddySettings`

```python
class SessionBuddySettings(OneiricMCPConfig):
    """Oneiric-shaped session-buddy settings.

    Inherits ``http_port``, ``http_host``, ``enable_http_transport``,
    ``debug``, ``environment``, ``cache_dir`` from OneiricMCPConfig.
    Adds the ~22 nested ``*Config`` groups below.

    Root-level ``extra=\"allow\"`` (Mahavishnu pattern) so unknown
    keys from Oneiric framework groups (``app``, ``adapters``, ...)
    that the Oneiric loader returns are silently filtered out by
    the Phase 2 loader — they never reach ``model_validate``.
    Per-leaf ``extra=\"forbid\"`` (the actual safety policy) is set
    by ``_BaseConfig``.
    """
    model_config = ConfigDict(
        env_prefix="SESSION_BUDDY_",
        env_nested_delimiter="__",
        extra="allow",
    )

    mcp_server: ServerIdentityConfig = Field(...)
    mcp_transport: MCPTransportConfig = Field(...)
    paths: PathsConfig = Field(...)
    database: DatabaseConfig = Field(...)
    multi_project: MultiProjectConfig = Field(...)
    search: SearchConfig = Field(...)
    tokens: TokensConfig = Field(...)
    session: SessionConfig = Field(...)
    conversation_storage: ConversationStorageConfig = Field(...)
    reflection_auto_store: ReflectionAutoStoreConfig = Field(...)
    integrations: IntegrationsConfig = Field(...)
    git_maintenance: GitMaintenanceConfig = Field(...)
    prometheus: PrometheusConfig = Field(...)
    development: DevelopmentConfig = Field(...)
    logging: LoggingConfig = Field(...)
    security: SecurityConfig = Field(...)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    entity_extraction: EntityExtractionConfig = Field(...)
    feature_flags: FeatureFlagsConfig = Field(...)
    filesystem_extraction: FilesystemExtractionConfig = Field(...)
    cloud_sync: AkoshaSyncConfig = Field(...)
    bodai_events: BodaiEventsConfig = Field(...)
```

Methods kept on the root class (delegating to the new groups):
- `pid_path()`, `health_snapshot_path()`, `telemetry_snapshot_path()` —
  read `cache_dir` from OneiricMCPConfig.
- `get_masked_key(key_name, visible_chars)` — generic, walks the
  settings tree to read any path.
- `get_api_key(key_name)` — kept for migration-compat with tests.
- `get_api_key_secure(key_name, provider)` — kept for migration-compat.

### 1d. Validators migrate with their fields

- `expand_user_paths` → `@field_validator("*")` on `PathsConfig` (or
  per-field `@field_validator` on each `Path` field)
- `validate_commit_template` → `@field_validator` on
  `SessionConfig.commit_message_template`
- `validate_prune_delay` → `@field_validator` on
  `GitMaintenanceConfig.git_gc_prune_delay`
- `map_legacy_debug_flag` → `@model_validator(mode="before")` on
  `SessionBuddySettings` (translates `debug: true` YAML → root
  `debug=True`, same as today)

### Proposed group structure

Names follow Mahavishnu `<Domain>Config` convention. Every leaf
extends `_BaseConfig` (`extra="forbid"`).

| Group | Field origin (current flat name) |
|---|---|
| `ServerIdentityConfig` | `server_name`, `server_description`, `log_level`, `enable_debug_mode` |
| `MCPTransportConfig` | `server_host`, `server_port`, `enable_websockets` |
| `PathsConfig` | `data_dir`, `log_dir`, `global_workspace_path`, `log_file_path` |
| `DatabaseConfig` | `database_path` (renamed to `path`), `database_connection_timeout` (→ `connection_timeout`), `database_query_timeout` (→ `query_timeout`), `database_max_connections` (→ `max_connections`) |
| `MultiProjectConfig` | `enable_multi_project`, `auto_detect_projects`, `project_groups_enabled` |
| `SearchConfig` | 13 search/embedding fields (full inventory in `§2.3` of `/Users/les/.claude/plans/stateful-mixing-moore-agent-a3a2d5f011e2fb65b.md`) |
| `TokensConfig` | 8 token-optimization fields |
| `SessionConfig` | 10 session/checkpoint fields |
| `ConversationStorageConfig` | 5 conversation-storage fields |
| `ReflectionAutoStoreConfig` | 5 reflection-auto-store fields |
| `IntegrationsConfig` | `enable_crackerjack`, `crackerjack_command`, `enable_git_integration`, `git_auto_stage` (**drop `enable_crackerjack_fallback`** — it's already in `FeatureFlagsConfig`; this is a shadow duplicate, see §De-duplication) |
| `GitMaintenanceConfig` | `git_auto_gc`, `git_gc_prune_delay`, `git_gc_auto_threshold`, `git_gc_only_when_clean` |
| `PrometheusConfig` | `enable_prometheus_metrics`, `prometheus_metrics_port`, `prometheus_metrics_path` |
| `DevelopmentConfig` | `enable_hot_reload` |
| `LoggingConfig` | 8 logging fields |
| `SecurityConfig` | `anonymize_paths`, `enable_rate_limiting`, `max_requests_per_minute`, `max_query_length`, `max_content_length` |
| `LLMConfig` | (consolidates LLM) — `default_provider`, `fallback_providers`, `ollama_base_url`, `ollama_default_model`, `llama_server_default_model`, `minimax_base_url`, `minimax_default_model`, `zai_base_url`, `zai_default_model`, `llama_server_model`, plus nested `LLMApiKeysConfig` (`openai_api_key`, `anthropic_api_key`, `gemini_api_key`, `qwen_api_key`, `minimax_api_key`, `zai_api_key`). The nested `api_keys` follows the `agno.llm` precedent (Mahavishnu's `AgnoAdapterConfig.llm: AgnoLLMConfig`). |
| `EntityExtractionConfig` | `enable_llm_entity_extraction`, `llm_extraction_timeout`, `llm_extraction_retries` (renamed from `LLMExtractionConfig` to match the `enable_llm_entity_extraction` field name and the `GoalParsingConfig` Mahavishnu precedent) |
| `FeatureFlagsConfig` | `enable_anthropic`, `enable_ollama`, `enable_conscious_agent`, `enable_filesystem_extraction` (toggle co-located with `FilesystemExtractionConfig` per architectural review), `enable_crackerjack_fallback` |
| `FilesystemExtractionConfig` | `filesystem_dedupe_ttl_seconds`, `filesystem_max_file_size_bytes`, `filesystem_ignore_dirs` |
| `AkoshaSyncConfig` | 13 `akosha_*` fields (renamed from `CloudSyncConfig`; matches the existing `akosha_config.py:from_settings()` pattern that strips the `akosha_` prefix) |
| `BodaiEventsConfig` | (already exists — unchanged) — `enabled`, `stream`, `consumer_group` |

### De-duplication (real conflicts)

- `default_provider` (nested, in `LLMProvidersConfig`) vs
  `default_llm_provider` (flat) → keep `llm.default_provider` (the
  Oneiric naming convention wins). Tests touching
  `test_default_llm_provider_default` /
  `test_llm_fallback_chain_default` rewrite to the canonical name.
- `fallback_providers` (nested) vs `llm_fallback_chain` (flat) → keep
  `llm.fallback_providers`.
- `enable_crackerjack_fallback` (currently in flat)
  appears in BOTH `IntegrationsConfig` AND `FeatureFlagsConfig` in
  the original plan. Resolve to **`FeatureFlagsConfig`** only (it's a
  feature-flag toggle; `feature_flags.py` is the consumer). Drop from
  `IntegrationsConfig`.

## Phase 2 — Loader and module helpers

**File**: `session_buddy/settings.py` (lines 849-938)

Replace `load()` with a Oneiric-delegating loader that **filters the
14 framework groups** so `extra="forbid"` validation doesn't trip on
`app`/`adapters`/`services`/`tasks`/`events`/`workflows`/`actions`/
`secrets`/`remote`/`logging`/`lifecycle`/`plugins`/`profile`/
`runtime_paths`/`runtime_supervisor` (which Oneiric returns but
session-buddy doesn't declare):

```python
@classmethod
def load(cls, *, config_path=None):
    """Load with Oneiric's layered config (no manual YAML re-read)."""
    from pathlib import Path
    from oneiric.core.config import load_settings as _oneiric_load

    loaded = _oneiric_load(
        path=str(config_path) if config_path else None,
        project_name="session-buddy",
        project_root=Path(__file__).resolve().parent.parent,
    )
    # Oneiric returns 14 framework groups we don't declare.
    # Filter to only the keys we model, then validate.
    relevant = {
        k: v
        for k, v in loaded.model_dump().items()
        if k in cls.model_fields
    }
    return cls.model_validate(relevant)
```

Drop (now redundant):
- The flat YAML re-read loop (lines 899-936) — Oneiric handles it.
- The `relevant_data` filter pattern (currently flat-key-aware;
  re-implement as group-key-aware — same idea, fits the new schema).
- The nested-dict merge branch (lines 931-934, commit `941d4536`) —
  Oneiric's `_deep_merge` (oneiric/core/config.py:728-739) already
  handles nested blocks.

Update `get_settings()` / `reload_settings()` to delegate to
`SessionBuddySettings.load()`.

Update module-level helpers to read the new shape:
- `get_database_path()` → `settings.database.path` joined with
  `settings.paths.data_dir` if relative.
- `get_log_file_path()` → `settings.paths.log_file_path` joined with
  `settings.paths.log_dir` if relative.
- `get_llm_api_key(provider)` → `settings.llm.api_keys.<provider>`
  (drop the hardcoded `field_map`; the new path is self-describing).
- `get_api_key(key_name)` / `get_api_key_secure(key_name, provider)` —
  kept as migration shims; delegate to `getattr(self, key_name, None)`
  with logging.

## Phase 3 — Migrate production code (~27 files)

**Pattern** (mechanical rewrite):
```python
# Before
get_settings().minimax_api_key
# After
get_settings().llm.api_keys.minimax
```

```python
# Before
settings.database_path
# After
settings.database.path
```

Special handling:
- **MCPTransportConfig-derived fields** (`http_port`, `http_host`,
  `enable_http_transport`, `server_port`, `server_host`,
  `enable_websockets`) stay at the OneiricMCPConfig root, not nested.
  Consumers like `cli/base.py` keep reading them flat.
- **`enable_crackerjack_fallback`** lives in `FeatureFlagsConfig`
  only; `feature_flags.py:74-83` becomes
  `settings.feature_flags.enable_crackerjack_fallback`.

### 3a. Migration sweep: `getattr(settings, "X", default)` pattern

**Biggest single risk** flagged by the code-architect reviewer: at
least 8 production files use `getattr(settings, "X", default)`
defensively. After the refactor, every such call returns the
**default value silently** because the field has moved to a nested
group. Crackerjack's pytest gate cannot catch this.

Grep `session_buddy/` for `getattr\(settings,` and rewrite each
match. Known sites:

| File | Line | Pattern | After |
|---|---|---|---|
| `memory/conscious_agent.py` | 83 | `getattr(settings, "enable_conscious_agent", False)` | `settings.feature_flags.enable_conscious_agent` |
| `memory/persistence.py` | 41 | `getattr(settings, "database_path", "...")` | `settings.database.path` |
| `doctor.py` | 222 | `getattr(settings, "database_path", None)` | `settings.database.path` |
| `doctor.py` | 223 | `getattr(settings, "reflection_db_path", None)` | delete (field never existed) |
| `config/feature_flags.py` | 74-83 | 6 `getattr(settings, ...)` for flags | `settings.feature_flags.<flag>` |
| `llm/security.py` | 47 | `getattr(settings, key_field, None)` | `settings.llm.api_keys.<provider>` |
| `llm_providers.py` | 381, 429 | same | same |
| `mcp/server.py` | 338, 352, 360 | 3 `getattr(settings, "midpoint_*", ...)` | `settings.session.midpoint_*` |
| `core/conversation_storage.py` | 166, 191, 202 | 3 `getattr(settings, "conversation_*", ...)` | `settings.conversation_storage.<field>` |
| `storage/akosha_config.py` | 295-319 | 8 `getattr(settings, "akosha_*", ...)` with `name.removeprefix("akosha_")` fallback | rewrite to `settings.cloud_sync.<field>`; **drop the `removeprefix` fallback** (the 2 tests covering that fallback become assertions on the new shape) |

### 3b. `field_map` deduplication (4× duplicates)

The hardcoded `field_map` dict (`{"openai": "openai_api_key", ...}`)
appears in 4 sites. Consolidate:

- `session_buddy/settings.py:1043-1050` — `get_llm_api_key(provider)`
- `session_buddy/llm/security.py:37-44` — `get_masked_api_key`
- `session_buddy/llm_providers.py:371-378` — `get_masked_api_key`
- `session_buddy/llm_providers.py:419-426` —
  `_get_provider_api_key_and_env`

Decision: **delete all four `field_map` dicts**; each function reads
`settings.llm.api_keys[provider]` directly. The
`get_masked_api_key` return value (e.g. `"settings.minimax_api_key"`)
is part of the public contract per tests at
`tests/unit/test_settings.py:1553` and
`tests/unit/test_llm_providers.py:361` — keep the string format
identical (return `"settings.llm.api_keys.<provider>"`).

### 3c. File-by-file work

High-blast-radius first:

- `session_buddy/mcp/server.py` — bodai_events (already nested);
  midpoint_commit_interval_s → `session.midpoint_commit_interval_s`;
  auto_checkpoint_interval → `session.auto_checkpoint_interval`
- `session_buddy/config/feature_flags.py` — 6 flag reads →
  `settings.feature_flags.<flag>`
- `session_buddy/llm/security.py` — `openai_api_key` etc. →
  `settings.llm.api_keys.<provider>`; consolidate `field_map`
- `session_buddy/storage/akosha_config.py` — 13 `akosha_*` reads →
  `settings.cloud_sync.<field>`; drop `removeprefix` fallback
- `session_buddy/utils/reflection_utils.py` — 5 auto-store reads →
  `settings.reflection_auto_store.<field>`
- `session_buddy/core/session_manager.py` — 4 git-gc reads →
  `settings.git_maintenance.<field>`
- `session_buddy/memory/entity_extractor.py` — 2 reads →
  `settings.entity_extraction.<field>`
- `session_buddy/memory/conscious_agent.py` — see §3a
- `session_buddy/memory/persistence.py` — see §3a
- `session_buddy/adapters/storage_oneiric.py` — bucket / gcs_*
  paths → `settings.database.*` (storage concerns move to the
  database/storage group)
- `session_buddy/cli/base.py` — `http_port`, `pid_path()`,
  `websocket_port` — stays as-is (MCP-transport root); the class
  rename in Phase 1.4 makes this `CLILaunchSettings`
- `session_buddy/cli_with_modes.py` — `server_name` →
  `settings.mcp_server.server_name`; class rename in Phase 1.4
- `session_buddy/cli/__init__.py` — re-export name update
- `session_buddy/doctor.py` — see §3a
- `session_buddy/analytics/session_analytics.py` — `database_path` →
  `settings.database.path`
- `session_buddy/app_monitor.py` — flags → `settings.feature_flags.*`
- `session_buddy/utils/crackerjack/fallback.py` —
  `enable_crackerjack_fallback` →
  `settings.feature_flags.enable_crackerjack_fallback`
- `session_buddy/utils/runtime_snapshots.py` — path helpers on
  `SessionBuddySettings` (root class, unchanged)
- `session_buddy/mcp/tools/infrastructure/feature_flags_tools.py` —
  6 flag reads → `settings.feature_flags.<flag>`
- `session_buddy/mcp/tools/advanced/entity_extraction_tools.py`,
  `conscious_agent_tools.py` — flag reads →
  `settings.feature_flags.<flag>`
- `session_buddy/mcp/tools/infrastructure/access_log_tools.py` —
  `get_database_path()` (unchanged)
- `session_buddy/core/bottleneck_detector.py`,
  `core/memory_health.py`, `core/session_analytics.py` — `database_path`
  → `settings.database.path`

### 3d. Integration Contract (per `wire-up-contract.md`)

- **Triggered from**: Operator starts the session-buddy MCP server
  (or runs `crackerjack`); the new `SessionBuddySettings.load()`
  runs at process startup.
- **Returns to / updates**: All consumer sites listed in §3c read
  from the new nested shape; settings file (`settings/session-buddy.yaml`)
  is rewritten in Phase 4.
- **Demonstrable by**: Phase 7 verification commands (load + dump).
- **Rollback signal**: `git revert` of the PR reverts all 27 files
  and 50 test files to the flat shape; production code falls back
  to `SessionMgmtSettings`.
- **Observability added**: One log line per settings load — emits
  the resolved group structure summary. Failed `model_validate`
  errors include the offending YAML file path.

## Phase 4 — YAML config files

**File**: `settings/session-buddy.yaml` (192 lines)

Re-nest every flat key under its group:

```yaml
mcp_server:
  server_name: "Session Buddy MCP"
  server_description: "Session management and tooling MCP server"
  log_level: "INFO"
  enable_debug_mode: false

paths:
  data_dir: "~/.claude/data"
  log_dir: "~/.claude/logs"
  global_workspace_path: "~/Projects/claude"
  log_file_path: "~/.claude/logs/session-buddy.log"

database:
  path: "~/.claude/data/reflection.duckdb"
  connection_timeout: 30
  query_timeout: 120
  max_connections: 10

# ... one nested group per table row ...

llm:
  default_provider: "minimax"
  ollama_base_url: "http://localhost:11434"
  ollama_default_model: "Qwen3-8B-8.2B-Q4_K_M"
  llama_server_default_model: "qwen3.5"
  minimax_base_url: "https://api.minimax.io/v1"
  minimax_default_model: "MiniMax-M2.7"
  zai_base_url: "https://api.z.ai/api/coding/paas/v4"
  zai_default_model: "glm-4.7"
  fallback_providers: ["minimax", "llama_server", "ollama"]
  api_keys:
    openai: null
    anthropic: null
    gemini: null
    qwen: null
    minimax: null
    zai: null

feature_flags:
  enable_anthropic: true
  enable_ollama: false
  enable_conscious_agent: true
  enable_filesystem_extraction: true
  enable_crackerjack_fallback: false
  enable_llm_entity_extraction: true

# ... etc.
```

**File**: `settings/local.yaml` (your override)

Update to nested shape:

```yaml
llm:
  default_provider: "minimax"
  fallback_providers: ["minimax", "llama_server", "ollama"]

feature_flags:
  enable_conscious_agent: true
```

**File**: `~/.config/session-buddy/local.yaml`

Update the comment-only documentation to reflect the nested shape
(operator site — no live overrides are currently set, so this is
comment refresh only).

### Operator migration note

Operators with existing `~/.config/session-buddy/local.yaml` flat
keys must manually migrate. Per the pre-1.0 replace-not-extend
policy, no compat alias is provided. Document in the release
notes / `docs/plans/` follow-up.

## Phase 5 — Tests (~50 files)

### 5a. Heavy (will break under the new schema — assert on flat fields)

- `tests/unit/test_settings_core.py` (~700 lines, 10 test classes,
  asserts every flat default) — rewrite every assertion to
  `settings.<group>.<field>`.
- `tests/unit/test_settings.py` (1700+ lines) — rewrite all flat-
  field asserts; the 6 `TestSessionMgmtSettingsAPIKeys` tests
  (lines 913-956) become `settings.llm.api_keys.<provider>` reads;
  the 3 `TestLLMProvidersConfig`/`TestLLMFallback` tests
  (lines 160-179) for flat duplicates rewrite to canonical nested
  names; the `TestLoadSettingsWithLocalOverrides` integration
  tests (lines 1700-1782) test the flat-YAML loader — Phase 2
  deletes it, so these tests rewrite to a new "nested YAML
  loader" smoke test.
- `tests/unit/test_settings_defaults.py`,
  `tests/unit/test_adapters_settings.py`,
  `tests/unit/test_reflection_utils.py`,
  `tests/unit/test_persistence.py` and
  `tests/unit/memory/test_persistence.py`,
  `tests/unit/test_knowledge_graph_db.py`,
  `tests/unit/test_session_manager_high_impact.py`,
  `tests/unit/test_mcp_server_core.py` and
  `tests/unit/test_server_core.py`,
  `tests/unit/test_access_log_stats.py`,
  `tests/unit/test_conscious_agent.py` and
  `tests/unit/memory/test_conscious_agent.py`,
  `tests/unit/test_feature_flags.py`,
  `tests/unit/test_llm_security.py`,
  `tests/unit/llm/test_security.py`,
  `tests/unit/test_llm_providers.py`,
  `tests/unit/test_llm_helper_functions.py`,
  `tests/unit/test_doctor.py`,
  `tests/unit/test_session_tools_v2.py`,
  `tests/unit/test_app_monitor.py`,
  `tests/unit/test_app_monitor_thresholds.py`,
  `tests/unit/storage/test_akosha_config.py` (the 2 tests covering
  `removeprefix("akosha_")` fallback become assertions on
  `settings.cloud_sync.<field>`),
  `tests/unit/test_storage_oneiric.py`,
  `tests/unit/test_reflection_adapter_oneiric.py`,
  `tests/unit/test_reflection_provenance.py`,
  `tests/unit/test_lifecycle_cleanup.py`,
  `tests/unit/test_git_operations.py`,
  `tests/unit/test_session_storage_adapter.py`,
  `tests/unit/test_knowledge_graph_adapter.py`,
  `tests/unit/test_embedding_quantization.py`,
  `tests/unit/test_hnsw_indexing.py`,
  `tests/unit/test_reflection_tools.py`,
  `tests/unit/test_akosha_tools.py`,
  `tests/unit/test_bodai_events_publisher.py`,
  `tests/unit/core/checkpoint/test_working_tree_invariant.py`,
  `tests/unit/test_action_kit_adoption.py`,
  `tests/unit/test_utilities_property_based.py`,
  `tests/unit/test_cli.py`,
  `tests/unit/test_cli/test_cli_commands.py`,
  `tests/unit/test_cli_with_modes.py`,
  `tests/cli/test_base.py`,
  `tests/cli/test_start_server_handler.py`,
  `tests/integration/test_bodai_events_publisher_e2e.py`,
  `tests/integration/test_akosha_sync_integration.py`,
  `tests/integration/test_conscious_agent_metrics.py`,
  `tests/integration/test_conscious_agent_periodic_jobs.py`,
  `tests/integration/test_filesystem_extraction.py`,
  `tests/integration/test_doctor_command.py`,
  `tests/integration/test_init_reflection_adapter.py`,
  `tests/integration/test_zai_fallback_chain.py`,
  `tests/integration/test_sync.py`,
  `tests/integration/test_session_tools.py`,
  `tests/integration/test_conversation_storage.py`,
  `tests/integration/test_conscious_agent_writes.py`,
  `tests/integration/test_phase6_success_criteria.py`,
  `tests/unit/mcp/tools/memory/test_akosha_tools.py`,
  `tests/unit/mcp/tools/session/test_session_tools.py`,
  `tests/unit/mcp/tools/session/test_start_session_returns_typed_envelope.py`,
  `tests/unit/mcp/tools/session/test_channel_tracking_tools.py`,
  `tests/unit/mcp/tools/infrastructure/test_access_log_tools.py`,
  `tests/unit/mcp/test_server_lifespan.py`,
  `tests/unit/mcp/test_auto_checkpoint_timer.py`.

### 5b. Light (use a fixture, don't assert field values directly)

- `tests/conftest.py` `mock_settings` fixture (lines 1312-1431) —
  **rewrite to construct a real `SessionBuddySettings` instance**
  with defaults overridden per test, rather than a `Mock()` with 70+
  flat attributes set by hand. The fixture MUST also reset
  `settings_module._settings = None` after the test (so the next
  test gets a fresh load). Strategy:

```python
@pytest.fixture
def mock_settings(monkeypatch):
    """Build a real SessionBuddySettings with sensible defaults."""
    from session_buddy.settings import SessionBuddySettings
    settings = SessionBuddySettings(
        feature_flags=FeatureFlagsConfig(
            enable_conscious_agent=True, ...
        ),
        llm=LLMConfig(
            api_keys=LLMApiKeysConfig(minimax="test-key"),
            ...
        ),
        database=DatabaseConfig(path=Path("/tmp/test.duckdb")),
        ...
    )
    monkeypatch.setattr("session_buddy.settings._settings", settings)
    return settings
```

- `tests/conftest.py:1417-1424` `mock_model_validate` shim — preserves
  the `debug` → `enable_debug_mode` flag mapping. The new
  `SessionBuddySettings` `@model_validator(mode="before")` handles
  this in production; the test shim must still patch
  `SessionBuddySettings.model_validate` (not `SessionMgmtSettings`).
- `tests/conftest.py:1427,438` `_settings = mock_settings_instance` —
  replaced by the real-instance fixture above.
- `tests/conftest.py:382-432` `isolated_test_db_path` autouse fixture —
  update path-redirect logic to set
  `settings.database.path` (nested) instead of `settings.database_path`
  (flat).
- `tests/unit/conftest.py`,
  `tests/unit/core/test_conversation_storage.py`,
  `tests/unit/test_akosha_tools.py`,
  `tests/unit/mcp/tools/session/test_session_tools.py`,
  `tests/unit/mcp/tools/session/test_start_session_returns_typed_envelope.py`,
  `tests/unit/mcp/tools/session/test_channel_tracking_tools.py`,
  `tests/unit/mcp/tools/infrastructure/test_access_log_tools.py`,
  `tests/unit/test_akosha_tools.py`,
  `tests/unit/test_session_storage_adapter.py`,
  `tests/unit/test_knowledge_graph_adapter.py`,
  `tests/integration/test_phase6_success_criteria.py`,
  `tests/integration/test_conversation_storage.py`,
  `tests/integration/test_conscious_agent_writes.py`,
  `tests/integration/test_session_tools.py`,
  `tests/integration/test_doctor_command.py`,
  `tests/integration/test_sync.py`,
  `tests/integration/test_init_reflection_adapter.py`,
  `tests/integration/test_zai_fallback_chain.py`,
  `tests/integration/test_akosha_sync_integration.py`,
  `tests/integration/test_conscious_agent_metrics.py`,
  `tests/integration/test_conscious_agent_periodic_jobs.py`,
  `tests/integration/test_filesystem_extraction.py`,
  `tests/integration/test_bodai_events_publisher_e2e.py`,
  `tests/integration/test_init_reflection_adapter.py`.

### 5c. Nested constructor syntax cheatsheet

Tests that currently construct `SessionMgmtSettings(<flat_kwarg>=...)`
(lines 178, 1553, 1567, 1590 in `test_settings.py`) need the
equivalent nested syntax:

```python
# Before
SessionMgmtSettings(minimax_api_key="test-key")

# After
SessionBuddySettings(
    llm=LLMConfig(api_keys=LLMApiKeysConfig(minimax="test-key"))
)
```

For tests that build `FeatureFlags(minimax_api_key="...")` directly
(test fixtures, not the dataclass), keep the kwargs style — the
`FeatureFlags` dataclass is unchanged.

## Phase 6 — Delete `SessionMgmtSettings` + docs/scripts cleanup

- Delete the old `SessionMgmtSettings` class and its flat
  declarations (settings.py:80-844).
- Delete the hardcoded `field_map` (settings.py:1041-1059) —
  replaced in Phase 3b.
- Update or delete `scripts/audit_session_buddy_settings_wiring.py`
  (lines 119, 176, 360, 522, 535 reference `SessionMgmtSettings`)
  to walk `SessionBuddySettings` instead.
- Update `tests/test_settings.yaml` documentation stub (8 flat keys →
  nested shape). The file is documentation, not a test fixture
  (per the inventory's §3.3); confirm and update.
- Add a docs audit sub-task (see §6a).

### 6a. Documentation update sub-task

Grep and rewrite references to flat-shape names in markdown:

- `AGENTS.md:39` — `from session_buddy.settings import SessionMgmtSettings`
  → `SessionBuddySettings`.
- `CLAUDE.md:541-548` — flat `default_llm_provider`,
  `llm_fallback_chain`, `SessionMgmtSettings` references.
- `docs/specs/2026-07-27-quality-scoring-crackerjack-fallback-design.md:189,191`
  — flat `enable_crackerjack_fallback` references.
- `docs/plans/2026-07-27-quality-scoring-crackerjack-fallback.md` —
  30+ flat-key references throughout.
- `docs/migrations/ONEIRIC_MIGRATION_PLAN.md:220` —
  `SessionMgmtSettings.load("session-buddy")` as verification
  pattern.
- `docs/PATHWAY_1_IMPLEMENTATION_PLAN.md:404,405` —
  `openai_api_key`/`anthropic_api_key` flat dataclass fields.
- `docs/AKOSHA_USER_GUIDE.md:71-383` — `akosha_cloud_bucket` flat
  YAML key.
- `docs/PHASE2_3_SINGLETON_CLEANUP_PLAN.md` — **out of scope**: it's
  an unrelated future plan about replacing `get_settings()` with
  `depends.get_sync`; mark as not-affected.

### 6b. Integration Contract

- **Triggered from**: PR 3 squash-merge.
- **Returns to**: New nested YAML schema is the canonical form;
  audit script + AGENTS.md + CLAUDE.md + specs all reference
  `SessionBuddySettings` and the new flat→nested group mappings.
- **Demonstrable by**: `rg "SessionMgmtSettings|minimax_base_url|default_llm_provider" docs/` returns zero matches.
- **Rollback signal**: revert PR 3 (smallest revert surface).
- **Observability added**: a one-line log on settings load surfaces
  the resolved group tree; per-YAML-key validation errors.

## Phase 7 — Verification

After every phase and once more at the end:

1. **Settings round-trip**:
   ```
   .venv/bin/python -c "
   from session_buddy.settings import get_settings, SessionBuddySettings
   s = get_settings()
   print(s.llm.default_provider, s.database.path, s.feature_flags.enable_conscious_agent)
   "
   ```
   Prints `minimax ~/.claude/data/reflection.duckdb True`.

2. **`extra="forbid"` policy works**:
   ```
   .venv/bin/python -c "from session_buddy.settings import SessionBuddySettings; SessionBuddySettings.model_validate({'llm': {'default_provider': 'ollama'}})"
   ```
   succeeds.
   ```
   .venv/bin/python -c "from session_buddy.settings import SessionBuddySettings; SessionBuddySettings.model_validate({'llm': {'unknown_field': 'x'}})"
   ```
   raises `ValidationError` (forbid policy works).

3. **Env-var override** (Oneiric prefix + `__` delimiter):
   ```
   SESSION_BUDDY_LLM__DEFAULT_PROVIDER=zai .venv/bin/python -c "
   from session_buddy.settings import get_settings; print(get_settings().llm.default_provider)
   "
   ```
   Prints `zai`.

4. **XDG layer override**:
   ```
   echo 'feature_flags:\n  enable_conscious_agent: false' > /tmp/xdg-test.yaml
   XDG_CONFIG_HOME=/tmp .venv/bin/python -c "
   from session_buddy.settings import get_settings; print(get_settings().feature_flags.enable_conscious_agent)
   "
   ```
   Prints `False`.

5. **Explicit config_path override**:
   ```
   echo 'llm:\n  default_provider: anthropic' > /tmp/cfg.yaml
   .venv/bin/python -c "
   from session_buddy.settings import SessionBuddySettings; print(SessionBuddySettings.load(config_path='/tmp/cfg.yaml').llm.default_provider)
   "
   ```
   Prints `anthropic`.

6. **End-to-end feature-flag smoke**:
   ```
   .venv/bin/python -c "
   from session_buddy.config.feature_flags import get_feature_flags
   f = get_feature_flags()
   assert f.enable_conscious_agent is True
   assert f.enable_filesystem_extraction is True
   print('feature flags OK')
   "
   ```
   Verifies the getattr-migration-sweep didn't miss any
   `feature_flags.py` reads.

7. **Env-var count assertion**: `rg "SESSION_BUDDY_" session_buddy/` —
   the only hits should be inside `feature_flags.py` env-var lookups
   (which keep their existing `SESSION_BUDDY_ENABLE_*` names for
   backwards compatibility) and docstrings.

8. **Targeted test runs** (high-blast-radius areas):
   - `.venv/bin/pytest tests/unit/test_settings_core.py tests/unit/test_settings.py tests/unit/test_settings_defaults.py -v`
   - `.venv/bin/pytest tests/unit/test_feature_flags.py tests/unit/test_llm_security.py tests/unit/test_llm_providers.py -v`
   - `.venv/bin/pytest tests/unit/test_conscious_agent.py tests/unit/test_reflection_utils.py tests/unit/test_doctor.py -v`
   - `.venv/bin/pytest tests/unit/storage/test_akosha_config.py -v`
   - `.venv/bin/pytest tests/integration/test_conversation_storage.py tests/integration/test_conscious_agent_writes.py -v`

9. **Full unit suite**: `.venv/bin/pytest tests/unit/ --tb=short --timeout=60`.

10. **Crackerjack** (no `-p` per `feedback-crackerjack-publish-stage-is-user`):
    `.venv/bin/crackerjack run -v`.

11. **Doctor**: `.venv/bin/python -m session_buddy.doctor --check`.

12. **Settings load smoke**:
    ```
    .venv/bin/python -c "
    from session_buddy.settings import get_settings
    s = get_settings()
    print('llm:', s.llm.model_dump())
    print('database:', s.database.model_dump())
    print('feature_flags:', s.feature_flags.model_dump())
    "
    ```

## Critical files

**Code paths**:
- `session_buddy/settings.py` (rewrite)
- `session_buddy/__init__.py` (no change required — the plan's earlier claim about line 9 re-exporting was incorrect)
- `session_buddy/cli/base.py` (class rename Phase 1.4 + consumer Phase 3)
- `session_buddy/cli_with_modes.py` (same)
- `session_buddy/cli/__init__.py` (re-export name)
- `session_buddy/mcp/server.py`, `mcp/server_core.py`
- `session_buddy/config/feature_flags.py`
- `session_buddy/llm/security.py`, `llm_providers.py`
- `session_buddy/storage/akosha_config.py`
- `session_buddy/utils/reflection_utils.py`, `utils/crackerjack/fallback.py`, `utils/runtime_snapshots.py`
- `session_buddy/core/session_manager.py`, `core/conversation_storage.py`, `core/bottleneck_detector.py`, `core/memory_health.py`, `core/session_analytics.py`
- `session_buddy/memory/conscious_agent.py`, `memory/entity_extractor.py`, `memory/persistence.py`
- `session_buddy/adapters/storage_oneiric.py`, `adapters/lifecycle.py`, `adapters/session_storage_adapter.py`, `adapters/settings.py`
- `session_buddy/cli/base.py`, `cli_with_modes.py`
- `session_buddy/doctor.py`, `analytics/session_analytics.py`, `app_monitor.py`
- `session_buddy/mcp/tools/infrastructure/feature_flags_tools.py`, `mcp/tools/infrastructure/access_log_tools.py`, `mcp/tools/advanced/entity_extraction_tools.py`, `mcp/tools/advanced/conscious_agent_tools.py`, `mcp/tools/memory/akosha_tools.py`, `mcp/tools/session/session_tools.py`, `mcp/tools/session/channel_tracking_tools.py`
- `scripts/audit_session_buddy_settings_wiring.py`

**Config files**:
- `settings/session-buddy.yaml` (rewrite to nested)
- `settings/local.yaml` (rewrite to nested)
- `~/.config/session-buddy/local.yaml` (comment updates only)

**Test files** (~50 listed in Phase 5; biggest blast is
`tests/conftest.py`'s `mock_settings` fixture and the `mock_model_validate`
shim).

**Docs/scripts**:
- `AGENTS.md:39`, `CLAUDE.md:541-548`, all docs in `docs/`
  (see Phase 6a sub-task for full list).

## Out of scope

- **No version bump** — per `feedback-mcp-common-version-bump-is-user`.
- **No commit / push** — per `feedback-bodai-push-is-user-controlled`.
- **No adapter settings dataclasses** — `StorageAdapterSettings`,
  `ReflectionAdapterSettings`, `KnowledgeGraphAdapterSettings` stay on
  their own dataclasses.
- **No OneiricSettings extension** — `SessionBuddySettings` extends
  `OneiricMCPConfig` (current parent) because session-buddy IS an
  MCP server; broader OneiricSettings groups (`app`, `adapters`,
  `services`, etc.) are Oneiric infrastructure config, not
  session-buddy domain config.
- **No PHASE2_3_SINGLETON_CLEANUP migration** — that's an unrelated
  future plan about replacing `get_settings()` with
  `depends.get_sync`. This refactor is shape-only.
- **No Crackerjack migration** — Crackerjack's
  `crackerjack/config/settings.py` is its own flat-shaped config;
  out of session-buddy's scope.
- **No `SESSION_BUDDY_*` env-var binding migration** for non-settings
  paths (e.g. `SESSION_BUDDY_ENVIRONMENT`,
  `SESSION_BUDDY_JWT_SECRET`, `SESSION_BUDDY_MODE`) — those are
  consumed via `os.getenv()` directly and don't flow through the
  settings class. They keep their existing names.

## Risks

- **Single-shot refactor across ~60 files** — mitigated by 3-PR
  split: PR 1 (schema) is reviewable as a class-only refactor;
  PR 2 (consumer migration) is the high-blast-radius step with
  feature-flag smoke tests; PR 3 (YAML + docs) is small.
- **`getattr(settings, "X", default)` silent regression** (the
  biggest single risk) — mitigated by an explicit Phase 3a
  migration sweep + Phase 7 end-to-end feature-flag smoke test.
- **`extra="forbid"` policy rejects unknown YAML keys** —
  documented in the operator migration note; operators with stale
  flat YAML get a clear parse error at startup.
- **Env-var name change incidental** — `SESSION_BUDDY_*` flat
  settings bindings become unconfigured after the refactor
  (settings was routed through `MCPBaseSettings` env prefix before;
  now uses Oneiric's `SESSION_BUDDY_LLM__*` pattern via
  `SettingsConfigDict(env_prefix="SESSION_BUDDY_")`). 90 files
  reference `SESSION_BUDDY_*`; ~6 are settings bindings that
  need migration (the `feature_flags.py` env-var lookups), the
  rest are env-direct (unchanged).
- **Settings.load() double-loads OneiricSettings** — the
  `model_dump()` filter + `model_validate()` boundary is the
  contract point; if OneiricSettings changes its returned groups,
  Phase 2 will need updating.
- **One-shot delete of `SessionMgmtSettings` (Phase 6)** — no
  compat alias per `feedback-no-backwards-compat-pre-1.0`. Any
  external import (already grep'd clean across the Bodai fleet)
  would fail fast at import time.