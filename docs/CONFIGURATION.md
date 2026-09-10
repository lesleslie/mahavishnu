# Configuration Reference

Configuration uses Oneiric layered loading: defaults → `settings/mahavishnu.yaml` → `settings/local.yaml` → environment variables (`MAHAVISHNU_*`). For nested settings, the environment separator is `__` (for example, `MAHAVISHNU_POOLS__ENABLED`). The examples below use verified configuration field names; nested YAML fields mirror Pydantic models for typed blocks, while the WebSocket integration explicitly reads the documented flat keys.

## Main Configuration File

**Location**: `settings/mahavishnu.yaml` (committed)

```yaml
server_name: "Mahavishnu Orchestrator"

# Adapter enablement
adapters:
  prefect_enabled: true
  llamaindex_enabled: true
  agno_enabled: true
  hatchet_enabled: false

# Quality control (off by default)
qc:
  enabled: false
  min_score: 80

# WebSocket integration reads these flat settings
websocket_enabled: true
websocket_host: "127.0.0.1"
websocket_port: 8690

# Pool management
pools:
  enabled: true
  default_type: "mahavishnu"
  routing_strategy: "least_loaded"
  min_workers: 1
  max_workers: 10
  memory_aggregation_enabled: true
  memory_sync_interval: 60
  session_buddy_url: "http://localhost:8678/mcp"
  akosha_url: "http://localhost:8682/mcp"

# Authentication
auth:
  enabled: false
  algorithm: "HS256"
  expire_minutes: 60
```

## Local Configuration

**Location**: `settings/local.yaml` (gitignored)

Override any settings for local development without affecting committed config. Secrets should be supplied through environment variables rather than committed YAML.

## Required Environment Variables

- `MAHAVISHNU_AUTH__SECRET` — JWT secret (minimum 32 characters when authentication is enabled). `MAHAVISHNU_AUTH_SECRET` is the legacy single-underscore alias.
- `RUNPOD_API_KEY` — Required for `runpod_pool` and RunPodPool operations.
- `MINIMAX_API_KEY` — MiniMax cloud-provider API key.
- `HATCHET_CLIENT_TOKEN` — Required when `adapters.hatchet_enabled: true`.

## Per-Session Worktree Isolation

When **multiple Claude Code sessions run concurrently** in the same repo, they share the same working directory and conflict on file writes, branch state, and dirty-tree merges. The per-session worktree feature provisions a per-session git worktree at SessionStart so each session edits its own tree.

| Variable | Default | Effect |
|----------|---------|--------|
| `MAHAVISHNU_AUTO_WORKTREE` | unset = **enabled** | Unset or truthy (`1`/`true`/`yes`/`on`) → per-session worktree isolation is on. Falsy (`0`/`false`/`no`/`off`) → opt out and emit a stderr hint. |
| `MAHAVISHNU_AUTO_WORKTREE_ROOT` | `~/worktrees` | Parent directory for auto-provisioned worktrees. Resolved via `mahavishnu.core.paths.get_worktree_base_path()`. **Deprecated alias for `MAHAVISHNU_WORKTREE_BASE_PATH`** (canonical v4 name). |
| `MAHAVISHNU_AUTO_WORKTREE_BRANCH_BASE` | current branch in cwd | Base branch when creating the new session branch. Falls back to `main` when discovery fails. |
| `MAHAVISHNU_AUTO_WORKTREE_CLEANUP` | `mark` | `mark` records the worktree as `abandoned` in the registry at SessionEnd. `keep` is a no-op. Worktrees are not auto-removed; use `mahavishnu worktree prune-abandoned` for registry cleanup. |
| `MAHAVISHNU_AUTO_WORKTREE_DEBUG` | unset | Set truthy to emit `[debug]`-prefixed lines to stderr. |
| `MAHAVISHNU_AUTO_WORKTREE_TIMEOUT` | `10` (max 60) | Seconds to wait for `git worktree add`. |

### Worktree env override

`MAHAVISHNU_WORKTREE_BASE_PATH` is the canonical v4 environment variable. It is a top-level field override, not a nested `__` form:

```bash
export MAHAVISHNU_WORKTREE_BASE_PATH="$HOME/worktrees"
```

### Opt-out (kill-switch)

The feature is on by default. To disable per-session worktree isolation, set the env var to any falsy value:

```bash
export MAHAVISHNU_AUTO_WORKTREE=0
export MAHAVISHNU_AUTO_WORKTREE=false
unset MAHAVISHNU_AUTO_WORKTREE
```

When the opt-out fires, the SessionStart hook prints a one-line stderr hint so the user knows the feature is normally on:

```
mahavishnu: per-session worktree isolation is on (set MAHAVISHNU_AUTO_WORKTREE=0 to disable); see docs/CONFIGURATION.md
```

State file path: XDG state dir (default `~/.local/state/mahavishnu/session-worktrees.json` on Linux, `~/Library/Application Support/mahavishnu/...` on macOS). The standard `MAHAVISHNU_HOME` env override applies if `get_state_path` is configured for it.

CLI cleanup: `mahavishnu worktree prune-abandoned --older-than-days 7` removes abandoned registry entries older than 7 days (the registry entry only — the git worktree itself stays until `mahavishnu worktree remove` is run explicitly).

For the full design rationale and tradeoffs, see `docs/followups/2026-07-16-session-worktree-isolation.md` and `.claude/decisions/session-worktree-defaults.md`.

## Other Configuration Files

- `settings/repos.yaml` — Repository manifest with tags and metadata.
- `settings/embeddings.yaml` — Embedding model configuration used by content-ingestion components.
- `settings/models.yaml` — LLM provider and task-routing model registry.
- `oneiric.yaml` — Legacy Oneiric config (backward compatible).

## Key Environment Variables

Nested settings use the pydantic-settings `__` delimiter. A single-underscore top-level name is valid only when it is the actual field name or an explicitly documented compatibility alias; it does not address a nested field.

```bash
# Canonical nested forms
export MAHAVISHNU_POOLS__ENABLED=true
export MAHAVISHNU_POOLS__DEFAULT_TYPE=mahavishnu
export MAHAVISHNU_AUTH__SECRET="your-secret-minimum-32-characters"
export MAHAVISHNU_WEBSOCKET_ENABLED=true

# Top-level field forms
export MAHAVISHNU_WORKTREE_BASE_PATH="$HOME/worktrees"
export MAHAVISHNU_CROSS_PROJECT_AUTH_SECRET="cross-project-secret"
export MAHAVISHNU_TOOL_PROFILE=full  # full, standard, minimal

# Optional: per-session worktree isolation
export MAHAVISHNU_AUTO_WORKTREE=1
export MAHAVISHNU_AUTO_WORKTREE_ROOT=~/worktrees
```

Additional supported overrides include:

- `MAHAVISHNU_OPENSEARCH__VERIFY_CERTS` — OpenSearch certificate verification (`true`).
- `MAHAVISHNU_OPENSEARCH__CA_CERTS` — OpenSearch CA certificate path (`null` unless configured).
- `MAHAVISHNU_TERMINAL__GOOSE_SECRET_KEY` — Secret for the optional Goose terminal adapter.
- `MAHAVISHNU_PERSISTENCE__POSTGRES_URL` — PostgreSQL URL for the storage-consolidation persistence block.
- `MAHAVISHNU_OTEL_STORAGE__CONNECTION_STRING` — PostgreSQL + pgvector URL for OTel storage.
- `MAHAVISHNU_SUBSCRIPTION_AUTH__SECRET` — Subscription-auth secret.
- `MAHAVISHNU_HEALTH__DEPENDENCIES__SESSION_BUDDY__HOST` — Health dependency host; the same `__` form applies to `PORT`, `USE_TLS`, and other dependency fields.
- `MAHAVISHNU_AGNO__LLM__PROVIDER` — Agno LLM provider (`anthropic`, `openai`, `minimax`, or `ollama`).
- `MAHAVISHNU_AGNO__MEMORY__CONNECTION_STRING` — Agno PostgreSQL memory connection string.
- `MAHAVISHNU_AGNO__LLM__API_KEY` — not a direct Agno settings field; Agno exposes `agno.llm.api_key_env` to name the credential variable instead (for example, `api_key_env: MINIMAX_API_KEY`).
- `MINIMAX_API_HOST` — MiniMax API host override.
- `HATCHET_CLIENT_TOKEN` — Hatchet client token.

## Top-Level Scalar Settings

- `cross_project_auth_secret` — `str | null`, default `None`; cross-project authentication secret.
- `repos_path` — `str`, default `settings/ecosystem.yaml`; repository-manifest path.
- `allowed_repo_paths` — `list[str]`, default `["/Users/les/Projects"]`; allowed repository base paths.
- `max_concurrent_workflows` — `int`, default `10`; concurrent workflow limit (1–100).
- `shell_enabled` — `bool`, default `True`; enables the admin shell.
- `capability_enabled` — `bool`, default `False`; enables capability tools.
- `capability_scopes` — `list[str]`, default `[]`; capability-scope allowlist.
- `legacy_tools` — `bool`, default `False`; enables legacy tool deprecation behavior.
- `unified_validation_enabled` — `bool`, default `False`; enables cross-file configuration validation.

## Configuration Block Reference

The defaults in this section are Pydantic model defaults for typed blocks when a block is absent. Compatibility YAML blocks identify their committed YAML defaults separately. The committed `settings/mahavishnu.yaml` can intentionally override model defaults.

### WebSocket flat settings

- `websocket_enabled` — `bool`, default `False` in the integration fallback; enables the real-time WebSocket server.
- `websocket_host` — `str`, default `127.0.0.1`; bind host.
- `websocket_port` — `int`, default `8690`; bind port.

### `pools.*` — multi-pool orchestration

- `enabled` — `bool`, default `True`; enables pool management.
- `default_type` — `str`, default `mahavishnu`; default pool type.
- `routing_strategy` — `str`, default `least_loaded`; selection strategy.
- `min_workers` / `max_workers` — `int`, defaults `1` / `10`; worker bounds.
- `memory_aggregation_enabled` — `bool`, default `True`; cross-pool memory aggregation.
- `memory_sync_interval` — `int`, default `60`; seconds between memory syncs.
- `session_buddy_url` — `str`, default `http://localhost:8678/mcp`; delegated Session-Buddy endpoint.
- `akosha_url` — `str`, default `http://localhost:8682/mcp`; cross-pool analytics endpoint.

Example:

```yaml
pools:
  enabled: true
  default_type: mahavishnu
  routing_strategy: least_loaded
  min_workers: 1
  max_workers: 10
```

### `pi_pool.*` — Pi coding-agent pool

- `enabled` — `bool`, default `False`; opt-in pool backend.
- `npx_command` — `tuple[str, ...]`, default `("npx", "-y", "@earendil-works/pi-coding-agent", "--rpc")`; allowlisted Pi invocation.
- `default_model` — `str`, default `claude-sonnet-4-5`; default Pi model.
- `rpc_timeout_seconds` — `float`, default `30.0`; JSON-RPC timeout.
- `probe_timeout_seconds` — `float`, default `3.0`; startup probe timeout.
- `heartbeat_interval_seconds` — `float`, default `30.0`; watchdog interval.
- `recipe_path` — `str | null`, default `None`; optional recipe file.
- `env_allowlist` — `tuple[str, ...]`, default `("PATH", "HOME", "LANG", "NODE_PATH", "NODE_ENV", "TMPDIR")`; non-sensitive variables forwarded to Pi.
- `pinned_version` — `str`, default `@earendil-works/pi-coding-agent@^1.0.0`; pinned package range.

### `otel_storage.*` and `otel_ingester.*` — OpenTelemetry

**`otel_storage`** (PostgreSQL + pgvector):

- `enabled` — `bool`, default `False`; enables the storage backend.
- `connection_string` — `str`, default `""`; PostgreSQL URL required when enabled.
- `embedding_model` — `str`, default `all-MiniLM-L6-v2`; semantic embedding model.
- `embedding_dimension` — `int`, default `384`; vector dimension.
- `cache_size` — `int`, default `10000`; in-memory embedding cache size.
- `similarity_threshold` — `float`, default `0.85`; minimum search score.
- `batch_size` / `batch_interval_seconds` — `int`, defaults `100` / `5`; batch write controls.
- `max_retries` — `int`, default `3`; retry attempts.
- `circuit_breaker_threshold` — `int`, default `5`; failures before opening the circuit.
- `hnsw.m` / `hnsw.ef_construction` / `hnsw.ef_search` — `int`, defaults `16` / `64` / `40`; HNSW index tuning.

**`otel_ingester`** (DuckDB or pgvector):

- `enabled` — `bool`, default `False`; enables the ingester.
- `hot_store_path` — `str | null`, default `None`; DuckDB file path, or XDG data path when omitted.
- `storage_type` — `str`, default `duckdb`; `duckdb` or `postgresql`.
- `storage_pg_url` — `str`, default `""`; PostgreSQL URL when `storage_type` is `postgresql`.
- `embedding_model` — `str`, default `all-MiniLM-L6-v2`; semantic embedding model.
- `cache_size` — `int`, default `1000`; embedding cache size.
- `similarity_threshold` — `float`, default `0.7`; minimum search score.
- `turboquant_bits` — `int | null`, default `4`; TurboQuant cache compression bits (`3` or `4`).

### `opensearch.*` — OpenSearch

- `endpoint` — `str`, default `https://localhost:9200`; OpenSearch endpoint.
- `index_name` — `str`, default `mahavishnu_code`; vector index.
- `verify_certs` — `bool`, default `True`; verify TLS certificates.
- `ca_certs` — `str | null`, default `None`; optional CA certificate path.
- `use_ssl` — `bool`, default `True`; use TLS.
- `ssl_assert_hostname` — `bool`, default `True`; verify the TLS hostname.
- `ssl_show_warn` — `bool`, default `True`; show TLS warnings.

### `dlq.*` — dead letter queue

- `fail_on_opensearch_unavailable` — `bool`, default `False`; fail closed when OpenSearch is unavailable instead of using the in-memory fallback.
- `max_size` — `int`, default `10000`; maximum in-memory failed-task count.

### `auth.*` and `subscription_auth.*`

Both JWT-style blocks use these fields:

- `enabled` — `bool`, default `False`; enable the authentication provider.
- `secret` — `str | null`, default `None`; secret required when enabled.
- `algorithm` — `str`, default `HS256`; signing algorithm.
- `expire_minutes` — `int`, default `60`; token lifetime in minutes (5–1440).

Use `MAHAVISHNU_AUTH__SECRET` or `MAHAVISHNU_SUBSCRIPTION_AUTH__SECRET`; the latter is separate from the regular JWT secret.

### `session_buddy_polling.*` and `session.*`

**`session_buddy_polling`**:

- `enabled` — `bool`, default `False`; enables Session-Buddy telemetry polling.
- `endpoint` — `str`, default `http://localhost:8678/mcp`; polling endpoint.
- `interval_seconds` — `int`, default `30`; polling interval.
- `timeout_seconds` — `int`, default `10`; MCP call timeout.
- `max_retries` — `int`, default `3`; retry attempts.
- `retry_delay_seconds` — `int`, default `5`; base retry delay.
- `circuit_breaker_threshold` — `int`, default `5`; consecutive failures before opening the circuit.
- `metrics_to_collect` — `list[str]`, default `get_activity_summary`, `get_workflow_metrics`, `get_session_analytics`, `get_performance_metrics`; polled tools.

**`session`**:

- `enabled` — `bool`, default `True`; enables Session-Buddy checkpoints.
- `checkpoint_interval` — `int`, default `60`; checkpoint interval in seconds (10–600).

### `resilience.*`, `observability.*`, and `monitoring.*`

**`resilience`**:

- `retry_max_attempts` — `int`, default `3`; maximum retry attempts.
- `retry_base_delay` — `float`, default `1.0`; base retry delay in seconds.
- `circuit_breaker_threshold` — `int`, default `5`; failures before the circuit opens.
- `timeout_per_repo` — `int`, default `300`; per-repository timeout in seconds.

**`observability`**:

- `metrics_enabled` — `bool`, default `True`; enables OpenTelemetry metrics.
- `tracing_enabled` — `bool`, default `True`; enables distributed tracing.
- `otlp_endpoint` — `str`, default `http://localhost:4317`; OTLP endpoint.

**`monitoring`**:

- `routing_metrics_port` — `int`, default `9091`; deprecated dedicated routing-metrics port.
- `routing_metrics_enabled` — `bool`, default `True`; enables routing metrics on the shared metrics endpoint.

### `a2a.*` and `openhands.*`

**`a2a`** (Agent-to-Agent):

- `enabled` — `bool`, default `False`; enables A2A support.
- `require_auth` — `bool`, default `True`; requires a bearer token for task endpoints.
- `task_timeout_seconds` — `float`, default `600.0`; task timeout.
- `card` — `A2ACardSettings`, default agent card with name `Mahavishnu`, description `Bodai ecosystem orchestrator`, streaming `True`, push notifications `False`.
- `agents` — `list[A2AAgentEntry]`, default `[]`; outbound agent registry.

**`openhands`**:

- `enabled` — `bool`, default `True`; enables the OpenHands integration.
- `base_url` — `str`, default `http://localhost:3000`; OpenHands API URL.
- `workspace_root` / `workspace_dir` — `Path`, defaults `/tmp` / `/tmp/openhands-workspace`; validated workspace paths.
- `timeout_seconds` — `int`, default `600`; request timeout.
- `poll_interval_seconds` — `float`, default `3.0`; polling interval.

### `workers.*`, `worker_registry.*`, and `worker_contract.*`

**`workers`** (runtime orchestration):

- `enabled` — `bool`, default `True`; enables worker orchestration.
- `max_concurrent` — `int`, default `10`; maximum concurrent workers.
- `default_type` — `str`, default `terminal-claude`; default worker type.
- `timeout_seconds` — `int`, default `300`; default worker timeout.
- `session_buddy_integration` — `bool`, default `True`; stores worker results in Session-Buddy.
- `container.runtime` — `str | null`, default `None`; auto-detects OrbStack, Docker, or Podman.
- `container.socket_path` — `str | null`, default `None`; optional container socket override.

**`worker_registry`**:

- `entries` — `list[WorkerEntry]`, default `[]`; capability-bearing worker definitions. Each entry requires `worker_type`; `name`, `description`, `command_argv`, `completion_markers`, `provides`, `tags`, `required_env`, and `one_shot` have model defaults.

**`worker_contract`** (compatibility YAML block):

- `enabled` — `bool`, default `False`; enables the worker contract runtime.
- `default_session_mode` — `str`, default `managed_tmux`; default session mode.
- `default_backend` — `str`, default `claude_tui`; default worker backend.
- `max_wait_ms` — `int`, default `30000`; maximum worker startup wait.
- `default_grace_ms` — `int`, default `5000`; graceful shutdown wait.
- `socket_dir` / `records_dir` — `str`, defaults `~/.mahavishnu/tmux` / `~/.mahavishnu/worker-sessions`; runtime state locations.
- `event_topic_prefix` — `str`, default `worker`; worker event topic prefix.

### `worktree_providers.*` and worktree storage/cache

**`worktree_providers`** (compatibility YAML block):

- `session_buddy_enabled` — `bool`, default `True`; registers the Session-Buddy provider before the direct Git fallback.

**`worktree_storage`**:

- `backend_preference` — `list[str]`, default `["local", "s3"]`; provider selection order.
- `local.base_path` — `Path`, default from `get_worktree_base_path()`; local worktree directory.
- `local.create_parents` — `bool`, default `True`; creates missing parent directories.
- `s3.bucket` / `s3.region` / `s3.endpoint_url` — `str | null`, default `None`; optional S3-compatible storage.
- `gcs.bucket` / `gcs.credentials_path` — `str | null`, default `None`; optional GCS storage.
- `azure.container` — `str | null`, default `None`; optional Azure Blob container.

**`worktree_cache`**:

- `l1_enabled` — `bool`, default `True`; enables the in-memory tier.
- `l1_max_entries` — `int`, default `1024`; L1 entry limit.
- `l1_ttl_seconds` — `float`, default `600.0`; L1 entry lifetime.
- `l2_enabled` — `bool`, default `True`; enables Redis L2.
- `l2_url` / `l2_host` / `l2_port` / `l2_db` — URL and Redis connection settings; defaults `None`, `localhost`, `6379`, `1`.
- `l2_ttl_seconds` — `int`, default `86400`; L2 entry lifetime.
- `l2_password` — `str | null`, default `None`; optional Redis password.
- `l2_ssl` — `bool`, default `False`; enables TLS for L2.
- `key_prefix` — `str`, default `mahavishnu:worktree-cache:`; Redis key prefix.
- `default_ttl_seconds` — `int`, default `3600`; cache fallback lifetime.

### `hatchet.*` — durable workflow engine

- `server_url` — `str`, default `localhost:7077`; Hatchet gRPC endpoint.
- `namespace` — `str`, default `mahavishnu`; workflow namespace.
- `max_runs` — `int`, default `10`; concurrent runs.
- `poll_interval_seconds` — `float`, default `2.0`; completion polling interval.
- `task_timeout_seconds` — `int`, default `300`; per-task timeout.

Set `adapters.hatchet_enabled: true` and provide `HATCHET_CLIENT_TOKEN` to activate the adapter.

### `llm.*` and `agno.*` — LLM and Agno

**`llm`**:

- `model` — `str`, default `nomic-embed-text`; embedding/LLM model name.
- `ollama_base_url` — `str`, default `http://localhost:11434`; Ollama endpoint.

**`agno`**:

- `enabled` — `bool`, default `True`; enables the Agno adapter.
- `llm.provider` — `LLMProvider`, default `ollama`; provider enum.
- `llm.model_id` — `str`, default `qwen2.5:7b`; provider model.
- `llm.api_key_env` — `str | null`, default `None`; environment variable containing the provider key.
- `llm.base_url` — `str | null`, default `http://localhost:11434`; provider/Ollama endpoint.
- `llm.temperature` — `float`, default `0.7`; sampling temperature.
- `llm.max_tokens` — `int`, default `4096`; response token limit.
- `memory.enabled` — `bool`, default `True`; enables Agno memory.
- `memory.backend` — `MemoryBackend`, default `none`; `sqlite`, `postgres`, or `none`.
- `memory.db_path` — `str`, default `data/agno.db`; SQLite path.
- `memory.connection_string` — `str | null`, default `None`; PostgreSQL memory URL.
- `memory.num_history_runs` — `int`, default `10`; retained historical runs.
- `teams_config_path` — `str`, default `settings/agno_teams`; team configuration directory.
- `default_timeout_seconds` — `int`, default `300`; agent timeout.
- `max_concurrent_agents` — `int`, default `5`; agent concurrency.
- `telemetry_enabled` — `bool`, default `True`; enables instrumentation.

### `oneiric_mcp.*` and `adapter_registry.*`

**`oneiric_mcp`** (Dhara adapter discovery compatibility block):

- `enabled` — `bool`, default `False`; enables discovery through Dhara.
- `base_url` — `str`, default `http://localhost:8683/mcp`; Dhara MCP URL.
- `timeout_sec` — `int`, default `30`; request timeout.
- `cache_ttl_sec` — `int`, default `300`; adapter cache lifetime.
- `token` — `str | null`, default `None`; optional bearer token.
- `circuit_breaker_threshold` — `int`, default `3`; failures before opening the circuit.
- `circuit_breaker_duration_sec` — `int`, default `300`; circuit-open duration.

**`adapter_registry`**:

- `enabled` — `bool`, default `True`; enables hybrid adapter discovery.
- `allowlist_patterns` — `list[str]`, default `mahavishnu.adapters.*`, `mahavishnu.engines.*`; allowed module patterns.
- `verify_signatures` — `bool`, default `False`; signature verification.
- `reject_unsigned` — `bool`, default `False`; reject unsigned adapters.
- `cache_ttl_seconds` — `int`, default `300`; metadata cache lifetime.
- `discovery_timeout_seconds` — `int`, default `30`; discovery timeout.

### `goal_teams.*` and `engines.*`

**`goal_teams`**:

- `enabled` — `bool`, default `False`; enables goal-driven teams.
- `goal_parsing.min_length` / `max_length` — `int`, defaults `10` / `2000`; accepted goal size.
- `goal_parsing.fallback_strategy` — `str`, default `simple`; `simple`, `reject`, or `default_team`.
- `limits.max_teams_per_user` — `int`, default `10`; active team limit.
- `limits.team_ttl_hours` — `int`, default `24`; team lifetime (`0` disables expiry).
- `limits.max_concurrent_executions` — `int`, default `5`; concurrent team executions.
- `feature_flags.mcp_tools_enabled` / `cli_commands_enabled` — `bool`, default `True`; tool and CLI access.
- `feature_flags.llm_fallback_enabled` / `websocket_broadcasts_enabled` / `prometheus_metrics_enabled` — `bool`, default `True`; fallback, broadcasts, and metrics.
- `feature_flags.learning_system_enabled` / `custom_skills_enabled` — `bool`, default `False`; experimental capabilities.
- `feature_flags.auto_mode_selection_enabled` — `bool`, default `True`; automatic mode selection.

**`engines`**:

- `disabled` — `list[str]`, default `[]`; engine IDs omitted from engine registration.

### `health.*` and `health.dependencies.*`

**`health`**:

- `enabled` — `bool`, default `True`; enables the health-check system.
- `check_timeout_seconds` — `int`, default `5`; individual request timeout.
- `retry_base_delay_seconds` / `retry_max_delay_seconds` — `float`, defaults `1.0` / `16.0`; exponential-backoff bounds.
- `dependencies` — `dict[str, DependencyConfig]`, default `{}`; service dependency map.

Each dependency has `host: str` (`localhost`), `port: int` (`8080`), `required: bool` (`True`), `timeout_seconds: int` (`30`), and `use_tls: bool` (`False`). The committed YAML registers Session-Buddy, Akosha, Dhara, Crackerjack, and Crow MCP with their service-specific ports and required flags.

### `persistence.*`, `verification.*`, `caller_quota.*`, and `feature_flags.*`

These are storage- and workflow-control YAML compatibility blocks. The values below are the committed YAML defaults; `MahavishnuSettings` currently permits extra YAML keys for them.

- `persistence.write_mode` — `str`, default `dual`; `dual`, `legacy`, or `postgres`.
- `persistence.read_source` — `str`, default `legacy`; `legacy` or `postgres`.
- `persistence.postgres_url` — `str`, default `""`; PostgreSQL URL.
- `persistence.task_store_write` / `search_write` / `event_write` — `str | null`, default `null`; per-component write overrides.
- `verification.enabled` — `bool`, default `True`; enables proposal verification.
- `verification.alert_threshold` — `float`, default `0.5`; reject-rate alert threshold.
- `verification.block_on_reject` — `bool`, default `False`; block approval on rejection.
- `verification.timeout_seconds` — `int`, default `30`; per-refuter timeout.
- `caller_quota.enabled` — `bool`, default `True`; enforces caller-kind quotas.
- `caller_quota.default` — `int`, default `100`; default quota per window.
- `caller_quota.window_seconds` — `int`, default `3600`; rolling quota window.
- `feature_flags.use_hybrid_registry` — `bool`, default `True`; uses the hybrid registry.
- `feature_flags.use_capability_routing` — `bool`, default `True`; uses capability routing.
- `feature_flags.fallback_to_legacy` — `bool`, default `True`; falls back to legacy initialization.

### `embeddings.*` and `runpod_pool.*`

**`embeddings`**:

- `provider` — `str`, default `auto`; `auto`, `fastembed`, `ollama`, or `openai`.
- `model` — `str`, default `BAAI/bge-small-en-v1.5`; embedding model.
- `dimension` — `int`, default `384`; vector dimension.
- `cache` — nested cache settings; default L1 size `10000`, L2 enabled, Redis URL `redis://localhost:6379/0`, L2 TLS disabled, verification enabled, auth disabled, TTL `86400` seconds.
- `rate_limit.enabled` — `bool`, default `True`; enables rate limiting.
- `rate_limit.max_batch_size` / `max_text_length` / `max_concurrent` — `int`, defaults `100` / `100000` / `5`.
- `rate_limit.timeout_seconds` — `float`, default `60.0`; request timeout.
- `budget.enabled` — `bool`, default `False`; enables budget tracking.
- `budget.daily_limit` — `int`, default `1000000`; daily embedding budget.
- `budget.alert_threshold` — `float`, default `0.8`; alert threshold.

**`runpod_pool`**:

- `enabled` — `bool`, default `False`; enables RunPod pool spawning.
- `default_gpu` — `str`, default `NVIDIA_GEFORCE_RTX_4090`; default GPU.
- `default_workers` — `int`, default `3`; default worker count.
- `default_endpoint_name` — `str`, default `mahavishnu-worker`; endpoint name.
- `default_dependencies` — `list[str]`, default `torch`, `transformers`; endpoint dependencies.

### `terminal.*`, `eventbridge.*`, and `dhara_state.*`

**`terminal`**:

- `enabled` — `bool`, default `False`; enables terminal management.
- `default_columns` / `default_rows` — `int`, defaults `120` / `40`; terminal dimensions.
- `capture_lines` — `int`, default `100`; captured output lines.
- `poll_interval` — `float`, default `0.5`; output polling interval.
- `max_concurrent_sessions` — `int`, default `20`; session limit.
- `adapter_preference` — `str`, default `mock`; `mock`, `tmux`, `crow`, `goose`, or `auto`.
- `fallback_on_probe_failure` — `bool`, default `False`; fallback to the mock adapter on probe failure.
- `crow_enabled` — `bool`, default `False`; enables the Crow adapter.
- `crow_http_host` / `crow_http_port` — `str` / `int`, defaults `127.0.0.1` / `8693`; Crow server endpoint.
- `goose_enabled` — `bool`, default `False`; enables the Goose adapter.
- `goose_http_host` / `goose_http_port` — `str` / `int`, defaults `127.0.0.1` / `8694`; Goose endpoint.
- `goose_secret_key` — `SecretStr | null`, default `None`; set with `MAHAVISHNU_TERMINAL__GOOSE_SECRET_KEY`.
- `goose_poll_interval` — `float`, default `0.5`; Goose capture polling interval.

**`eventbridge`**:

- `enabled` — `bool`, default `False`; constructs the EventBridge publisher.
- `endpoint` — `str`, default `""`; optional external ingestion URL.
- `dry_run` — `bool`, default `True`; logs envelopes without transmitting them.

**`dhara_state`**:

- `enabled` — `bool`, default `True`; enables durable state persistence.
- `flush_interval_seconds` — `int`, default `60`; periodic routing-buffer flush interval.
- `max_routing_buffer_age_seconds` — `int`, default `3600`; retained routing-decision age.

### `integrations.*`, `learning.*`, and `distill.*`

**`integrations`**:

- `pydantic_ai_enabled` — `bool`, default `False`; enables Pydantic AI integration.
- `openclaw_webhooks_enabled` — `bool`, default `True`; enables OpenClaw webhook endpoints.
- `omo_enabled` — `bool`, default `False`; enables OMO integration.
- `cross_platform_memory_enabled` — `bool`, default `True`; enables Session-Buddy/Akosha memory sharing.

**`learning`**:

- `enabled` — `bool`, default `False`; enables the review-gated learning pipeline.
- `collection_interval_seconds` — `int`, default `300`; evidence collection interval.
- `max_evidence_per_cycle` — `int`, default `50`; maximum evidence per cycle.
- `synthesis_min_evidence` — `int`, default `5`; minimum evidence before synthesis.
- `retention_days` — `int`, default `90`; raw-evidence retention.
- `max_drafts_per_cycle` — `int`, default `3`; synthesized drafts per cycle.
- `store_timeout_seconds` / `retrieve_timeout_seconds` — `int`, defaults `10` / `15`; storage and retrieval timeouts.

**`distill`**:

- `publisher_allowlist` — `str | null`, default `None`; publisher allowlist path or comma-separated list.
- `evidence_threshold` — `int`, default `3`; minimum tool-call count for a candidate.
- `require_reviewer` — `bool`, default `True`; rejects sessions without reviewer identity.

### `merge_driver.*` — mergiraf merge driver (Phase 4)

Top-level fields on `MahavishnuSettings` (NOT a nested block — the names are flat on the model). See `mahavishnu/core/config.py:2756-2788` for the field declarations and `mahavishnu/settle/merge.py` for the runtime resolution matrix.

- `merge_driver_default` — `str`, default `"line"`; global merge strategy. `"line"` uses `git merge-file` (Phase 0 default); `"mergiraf"` uses entity-aware `mergiraf merge`. Stays `"line"` for one release cycle; the follow-up plan (`docs/plans/2026-09-10-settle-semantic-merge-default-flip.md`) flips to `"mergiraf"` after a 30-day telemetry gate. Override via env `MAHAVISHNU_MERGE_DRIVER_DEFAULT`.
- `merge_driver_required` — `bool`, default `False`; when `True`, the startup guard in `MahavishnuApp._init_observability` raises `MergeDriverUnavailableError` if `mergiraf` is missing from `$PATH`. Loud-failure semantics: the app refuses to boot rather than crash on first apply. Override via env `MAHAVISHNU_MERGE_DRIVER_REQUIRED`.

Environment variables (transitional alias for `merge_driver_required` only, removed after one release cycle): `MAHAVISHNU_REQUIRE_MERGE_DRIVER` is a legacy single-underscore form for the same flag — `MAHAVISHNU_MERGE_DRIVER_REQUIRED` is the canonical dotted form.

## Merge Driver Rollback

If `mahavishnu` refuses to boot with `MergeDriverUnavailableError: ... mergiraf binary not found ...`, the following escape paths restore service without code changes. Pick the one that matches the operator's environment and constraints.

1. **Quick disable**: set `MAHAVISHNU_MERGE_DRIVER_REQUIRED=false` and restart. This is the fastest unblock for fresh installs and container builds; the default fallback (Phase 4 R3 #3 mitigation) emits a `WARNING merge.semantic.unavailable` log per call and stamps `merge_driver.degraded_since` on the `/health` payload so operators can see the degradation.
2. **Install mergiraf**: `brew install mergiraf`. Homebrew bundles the `tree-sitter-python` and other language grammars by default; `cargo binstall mergiraf` and most CI images ship only the binary (R4 #C: missing grammars silently fatal-error on files of that language). For CI/container deployments use the Homebrew install path, a custom container image with the grammars baked in, or run `mergiraf install-grammar python` post-install.
3. **Switch to LINE-only**: set `MAHAVISHNU_MERGE_DRIVER_DEFAULT=line`. With `default="line"` the default-resolution matrix always picks `git merge-file` regardless of whether `mergiraf` is installed. Per-binding requests that explicitly pass `strategy=MergeStrategy.SEMANTIC` still fail loudly with `MergeDriverUnavailableError` when the binary is missing — that is intentional, not a bug (silently falling back would mask worker contract violations). Use this when the cluster won't have mergiraf for the foreseeable future.
4. **Verify install**: `python scripts/check_merge_driver.py --json`. Exit code 0 with `passed == total` means every probe (binary, version, python grammar, git version ≥ 2.38) passed. Non-zero exit codes include a remediation hint per failure. `check_merge_driver.py` is the REQ-SM-008 operator-facing pre-flight; it's safe to run in CI before `mahavishnu mcp start`.
5. **Pre-flight in CI**: add `python scripts/check_merge_driver.py` to the CI job that boots the MCP server. The script's exit code propagates and blocks the deploy — surface the failure on the same CI step that runs `mahavishnu mcp start`, not as a separate check.

The startup guard fires whenever `merge_driver_required=True` regardless of `merge_driver_default`. An operator on the default `"line"` who flips `merge_driver_required=True` (e.g. to opt into a future default) gets the same boot-time protection as a `"mergiraf"` operator (Round-4 review fix C2).

See `scripts/check_merge_driver.py` for the full pre-flight matrix (binary PATH probe, version parse, tree-sitter-python grammar check, `git --version ≥ 2.38` requirement for `git merge-tree --write-tree` in Phase 6).

## LLM Provider Configuration

See `settings/models.yaml` for the provider registry and task-based model routing. MiniMax M3 is the primary cloud provider; MiniMax M2.7 and M2.7-highspeed are fallback models. Local `llama_server` (qwen3.5) and `ollama` (qwen2.5-coder) remain secondary fallbacks.

Task-based routing maps categories to optimal models via `mahavishnu/workers/task_router.py`; the YAML and in-code routing are intentionally pinned together.
