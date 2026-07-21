# Configuration Reference

Configuration uses Oneiric layered loading: defaults → `settings/mahavishnu.yaml` → `settings/local.yaml` → environment variables (`MAHAVISHNU_*`).

## Main Configuration File

**Location**: `settings/mahavishnu.yaml` (committed)

```yaml
server_name: "Mahavishnu Orchestrator"

# Adapters
adapters:
  prefect: true        # Prefect workflow orchestration
  llamaindex: true     # RAG pipelines
  agno: true           # Multi-agent teams

# Quality control
qc:
  enabled: true
  min_score: 80

# WebSocket real-time updates
websocket:
  enabled: true
  host: "127.0.0.1"
  port: 8690

# Pool management
pools_enabled: true
default_pool_type: "mahavishnu"  # mahavishnu, session_buddy, runpod

# Content ingestion
ingestion:
  enabled: true
  quality_threshold: 0.7

# Authentication
auth:
  enabled: true
  algorithm: "HS256"
  expire_minutes: 60

# Routing system
routing:
  enabled: true
  cost_budget_type: "daily"
  cost_limit: 100
  optimization_strategy: "cost"
```

## Local Configuration

**Location**: `settings/local.yaml` (gitignored)

Override any settings for local development without affecting committed config.

## Required Environment Variables

- `MAHAVISHNU_AUTH_SECRET` — JWT secret (minimum 32 characters)
- `RUNPOD_API_KEY` — Required for RunPodPool (set before spawning)

## Per-Session Worktree Isolation

When **multiple Claude Code sessions run concurrently** in the same repo, they share the same working directory and conflict on file writes, branch state, and dirty-tree merges. The per-session worktree feature provisions a per-session git worktree at SessionStart so each session edits its own tree.

| Variable | Default | Effect |
|----------|---------|--------|
| `MAHAVISHNU_AUTO_WORKTREE` | unset = **enabled** | Unset or truthy (`1`/`true`/`yes`/`on`) → per-session worktree isolation is on. Falsy (`0`/`false`/`no`/`off`) → opt out and emit a stderr hint. |
| `MAHAVISHNU_AUTO_WORKTREE_ROOT` | `~/worktrees` | Parent directory for auto-provisioned worktrees. Matches `WorktreePathValidator`'s default. |
| `MAHAVISHNU_AUTO_WORKTREE_BRANCH_BASE` | current branch in cwd | Base branch when creating the new session branch. Falls back to `main` when discovery fails (detached HEAD, non-git dir). |
| `MAHAVISHNU_AUTO_WORKTREE_CLEANUP` | `mark` | `mark` records the worktree as `abandoned` in the registry at SessionEnd (recommended). `keep` is a no-op. The plan never auto-removes worktrees — see [`mahavishnu worktree prune-abandoned`](#cli-cleanup) below. |
| `MAHAVISHNU_AUTO_WORKTREE_DEBUG` | unset | Set truthy to emit `[debug]`-prefixed lines to stderr (cwd, branch, target path, branch_base, timeout). Useful for operators debugging without enabling the full feature. |
| `MAHAVISHNU_AUTO_WORKTREE_TIMEOUT` | `10` (max 60) | Seconds to wait for `git worktree add`. |

### Opt-out (kill-switch)

The feature is on by default. To disable per-session worktree isolation, set the env var to any falsy value:

```bash
export MAHAVISHNU_AUTO_WORKTREE=0   # explicit opt-out
export MAHAVISHNU_AUTO_WORKTREE=false  # also works
unset MAHAVISHNU_AUTO_WORKTREE   # re-enable (back to default)
```

When the opt-out fires, the SessionStart hook prints a one-line stderr hint so the user knows the feature is normally on:

```
mahavishnu: per-session worktree isolation is on (set MAHAVISHNU_AUTO_WORKTREE=0 to disable); see docs/CONFIGURATION.md
```

The hint fires ONLY when ALL of these are true:

1. Mode is `session-start` (never on `session-end`)
2. `MAHAVISHNU_AUTO_WORKTREE` is explicitly set to a falsy value
3. `cwd` is non-empty
4. `cwd` is not already inside a worktree
5. `cwd` is a git repo (or a sub-directory of one)
6. `MAHAVISHNU_AUTO_WORKTREE_ROOT` (default `~/worktrees`) does not yet exist

The hint is purely informational — no filesystem mutation, no mahavishnu import, no registry write.

### Internal-team default-on context

This feature defaults to on because the Bodai ecosystem is currently
used only by the internal team that wrote and reviewed this code. Per
the decision record, this posture should be revisited at v1.0 / external
adoption: the trade-off is "discoverability for new external users" vs.
"productivity tax for the existing internal team", and the answer
flips when the audience flips.

State file path: XDG state dir (default `~/.local/state/mahavishnu/session-worktrees.json` on Linux, `~/Library/Application Support/mahavishnu/...` on macOS). The path is resolved by `mahavishnu.core.paths.get_state_path("session-worktrees.json")` and honors `XDG_STATE_HOME`. The standard `MAHAVISHNU_HOME` env override applies if `get_state_path` is configured for it.

CLI cleanup: `mahavishnu worktree prune-abandoned --older-than-days 7` removes abandoned registry entries older than 7 days (the registry entry only — the git worktree itself stays until you `mahavishnu worktree remove` it explicitly).

For the full design rationale and tradeoffs, see `docs/followups/2026-07-16-session-worktree-isolation.md` and `.claude/decisions/session-worktree-defaults.md`.

## Other Configuration Files

- `settings/repos.yaml` — Repository manifest with tags and metadata
- `settings/embeddings.yaml` — Embedding model configuration for content ingestion
- `settings/models.yaml` — LLM provider and model routing configuration
- `oneiric.yaml` — Legacy Oneiric config (backward compatible)

## Key Environment Variables

Access via `MAHAVISHNU_{FIELD}` pattern:

```bash
export MAHAVISHNU_AUTH_SECRET="your-secret-minimum-32-characters"
export MAHAVISHNU_POOLS_ENABLED=true
export MAHAVISHNU_DEFAULT_POOL_TYPE=mahavishnu
export MAHAVISHNU_TOOL_PROFILE=full  # full, standard, minimal

# Optional: per-session worktree isolation (multi-session setups)
export MAHAVISHNU_AUTO_WORKTREE=1          # opt-in gate
export MAHAVISHNU_AUTO_WORKTREE_ROOT=~/worktrees  # default
```

## LLM Provider Configuration

See `docs/plans/2026-05-10-minimax27-provider-migration.md` for current provider setup. Primary provider is MiniMax M2.7 with Ollama local fallback.

Task-based routing maps categories to optimal models via `mahavishnu/workers/task_router.py`.
