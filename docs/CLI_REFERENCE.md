# CLI Reference

Quick reference for Mahavishnu CLI commands. Every command listed below is
verified against `mahavishnu/_main_cli.py` and the per-subsystem CLI source
under `mahavishnu/` and `mahavishnu/cli/`.

## Top-level discovery

```bash
mahavishnu --help                # List top-level groups
mahavishnu list-agents           # Discover registered agents
mahavishnu list-skills           # Discover registered skills
mahavishnu list-mcp-servers      # Discover registered MCP servers
mahavishnu validate              # Validate configuration
mahavishnu sync-from-global      # Sync local config from global
mahavishnu rollback              # Rollback specific subsystems
mahavishnu health                # Service health probe
mahavishnu version               # Version information
mahavishnu shell                 # Interactive admin shell (IPython)
mahavishnu dashboard             # Read-only ecosystem TUI dashboard
mahavishnu generate-claude-token <user_id>   # Mint a Claude Code token
mahavishnu generate-codex-token <user_id>    # Mint a Codex token
```

## Repository Management

```bash
mahavishnu list-repos                          # List all repositories
mahavishnu list-repos --tag backend            # Filter by tag
mahavishnu list-repos --role orchestrator      # Filter by role
mahavishnu list-roles                          # Show all available roles
mahavishnu show-role tool                      # Details about a role
mahavishnu list-nicknames                      # All repository nicknames
```

## Adapter Management

```bash
mahavishnu adapter list                                # List registered adapters
mahavishnu adapter list --domain orchestration        # Filter by domain
mahavishnu adapter list --healthy                      # Only healthy adapters
mahavishnu adapter resolve <task_type> --cap <cap...>  # Resolve best adapter
mahavishnu adapter resolve <task_type> --domain orchestration --cap text_generation
mahavishnu adapter health                              # Check all adapter health
mahavishnu adapter health <name>                       # Check one adapter
```

## MCP Server

```bash
mahavishnu mcp start    # Start MCP server (foreground)
mahavishnu mcp stop     # Stop server (not implemented; use Ctrl+C)
mahavishnu mcp restart  # Restart server (not implemented)
mahavishnu mcp status   # Check status / configuration
mahavishnu mcp health   # Health probe
```

## Pool Management

```bash
mahavishnu pool spawn --type mahavishnu --name local --min 2 --max 5
mahavishnu pool spawn -t mahavishnu -n comms --worker-type gateway-openclaw
mahavishnu pool spawn --type session-buddy --name delegated --min 1 --max 3
mahavishnu pool list
mahavishnu pool execute <pool_id> --prompt "Write code" --timeout 300
mahavishnu pool route --prompt "Write code" --selector least_loaded
mahavishnu pool route --prompt "Write code" --selector capability_score --timeout 600
mahavishnu pool scale <pool_id> --target 10
mahavishnu pool health
mahavishnu pool close <pool_id>
mahavishnu pool close-all
```

Available `--type` values: `mahavishnu`, `session-buddy`, `runpod` (canonical
hyphen forms; legacy `session_buddy` underscore form is also accepted).
Available `--selector` values: `capability_score`, `random`,
`least_loaded`, `round_robin`.

## Workers

```bash
mahavishnu workers spawn --type terminal-claude --count 3
mahavishnu workers spawn -t gateway-openclaw -n 2
mahavishnu workers execute --prompt "Implement a REST API"
mahavishnu workers execute -p "Review this patch" -t terminal-codex -T 600
mahavishnu workers list-types
mahavishnu workers list-types --ready           # Routable types only
mahavishnu workers list-types --ready --explain
mahavishnu workers list-types --all --probe     # Force live probe
```

`--type` choices: `terminal-claude`, `terminal-codex`, `terminal-qwen`
(legacy), `gateway-openclaw`, `container-executor`.

## Workflow & Sweep

```bash
mahavishnu sweep --tag python --adapter prefect
mahavishnu workflow sweep --tag <tag> --adapter <adapter>            # Canonical
mahavishnu workflow quality-check --tag <tag> [--repo <nickname>...]
mahavishnu workflow heal                                             # Dead-letter queue
mahavishnu workflow fix --pool <id> --issue <id> [--desc <text>] [--file <path>...]
mahavishnu workflow review [--scope critical|security|performance|quality|all]
                            [--fix] [--dry-run]
mahavishnu workflow prefect-list-deployments [--flow <name>] [--tag <t>...] [--limit N] [--offset N]
mahavishnu workflow prefect-get-deployment <deployment_id>
mahavishnu workflow prefect-list-flow-runs [--deployment <id>] [--state <s>...] [--limit N] [--offset N]
mahavishnu workflow prefect-cancel-flow-run <flow_run_id>
mahavishnu workflow prefect-list-work-pools
mahavishnu workflow prefect-clear-schedule <deployment_id>
```

## Routing System

```bash
mahavishnu routing stats [--repo <nickname>] [--limit N]   # Show routing statistics
mahavishnu routing reset <repo> [--confirm]                # Reset routing stats for one repo
```

## Quality

```bash
mahavishnu quality check [<path>] [--verbose]      # Run quality checks on a path
mahavishnu quality check .                          # Check current directory
mahavishnu quality fix <path> [--auto]              # Fix quality issues (--auto runs ruff fix + format)
```

## Content Ingestion

```bash
mahavishnu ingest url <url> [--chunk-size 1000] [--chunk-overlap 200]
                           [--output ingested] [--provider fastembed|ollama|openai]
mahavishnu ingest file <path> [--chunk-size N] [--chunk-overlap N] [--provider <p>]
mahavishnu ingest batch <urls.txt> [--parallel N] [--provider <p>]
mahavishnu ingest stats [--provider <p>]
```

`--provider` overrides the oneiric probe-chain auto-selection. When
omitted, `llama_cpp -> ollama -> minimax -> model2vec -> mock` is consulted
in order.

## Coordination

```bash
# Issues
mahavishnu coord list-issues
mahavishnu coord show-issue <id>
mahavishnu coord create-issue --title <t> [--desc <d>] [--priority <p>] [--tag <t>...]
mahavishnu coord update-issue <id> [--status <s>] [--assignee <user>]
mahavishnu coord close-issue <id>

# Todos
mahavishnu coord list-todos
mahavishnu coord show-todo <id>
mahavishnu coord create-todo --title <t> [--desc <d>] [--issue <id>]
mahavishnu coord complete-todo <id>

# Plans, deps, status
mahavishnu coord list-plans
mahavishnu coord list-deps
mahavishnu coord check-deps
mahavishnu coord status
mahavishnu coord blocking
mahavishnu coord ecosystem-status
mahavishnu coord roadmap
```

## Repositories (data layer)

```bash
mahavishnu repo list-tasks
mahavishnu repo show-task <id>
mahavishnu repo list-runs
mahavishnu repo list-events
mahavishnu repo create-event [--type <t>] [--payload <json>]
mahavishnu repo diff <nickname>              # Show repo diff
mahavishnu repo pr-create <nickname>         # Create a PR
```

## Monitoring

```bash
mahavishnu monitor get-dashboard [--config <path>] [--output <file>]
mahavishnu monitor get-alerts   [--config <path>] [--output <file>]
mahavishnu monitor acknowledge-alert <alert_id> [--user <user>] [--config <path>]
mahavishnu monitor trigger-test-alert [--severity low|medium|high|critical]
                                     [--title <t>] [--desc <d>] [--config <path>]
mahavishnu monitor watch                  # Live Textual monitor (requires `tui` extra)
```

## Metrics

```bash
mahavishnu metrics collect [--create-issues] [--min-coverage 80.0]
                          [--store-metrics] [--output text|json]
mahavishnu metrics report  [--format text|json|markdown] [--output <file>]
mahavishnu metrics status  [--repo <name>] [--role <role>]
mahavishnu metrics history [--limit N]
mahavishnu metrics dashboard [--output <html>] [--open]
mahavishnu metrics verify-endpoints [--inventory <yml>]
                                [--write-verified-file <yml>]
                                [--output text|json] [--timeout 2.0]
                                [--service <name>...]
mahavishnu metrics engines [--source auto|postgres|prometheus] [--dsn <url>]
                          [--metrics-url <url>] [--days N] [--output table|json]
mahavishnu metrics bodai [--scope 24h|7d|all] [--component mahavishnu|akosha|crackerjack]
                        [--queue-path <p>] [--state-path <p>] [--queue-cap 100]
mahavishnu metrics verification [--since 24h|7d|30m|all] [--dhara-url <url>]
                               [--output table|json]
mahavishnu metrics dispatch [--since 24h|7d|30m|all] [--dhara-url <url>]
                           [--output table|json]
```

## Ecosystem

```bash
mahavishnu ecosystem validate
mahavishnu ecosystem list [--category <c>] [--status enabled|disabled]
mahavishnu ecosystem generate-claude-config [--output <path>] [--dry-run]
mahavishnu ecosystem audit [<server_name>]
mahavishnu ecosystem update-audit <server_name> <field> <value> [--notes <n>]
mahavishnu ecosystem urls <server_name>
mahavishnu ecosystem repo-urls <repo_name>
mahavishnu ecosystem list-lsp [--language <lang>] [--enabled true|false]
mahavishnu ecosystem lsp-info [<server_name>]
mahavishnu ecosystem ports [--type MCP|LSP|WebSocket] [--status enabled|disabled]
mahavishnu ecosystem status [--json]
mahavishnu ecosystem capabilities [--json] [--capability <name>]
```

## Backup

```bash
mahavishnu backup create   [--type full|incremental]
mahavishnu backup list
mahavishnu backup restore  <backup_id>
mahavishnu backup info     <backup_id>
mahavishnu backup check
mahavishnu backup procedures
```

## Production Readiness

```bash
mahavishnu production check     [--detailed]
mahavishnu production test      [--detailed]
mahavishnu production benchmark [--detailed]
mahavishnu production suite     [--detailed]
```

## Worktree Management

```bash
mahavishnu worktree create <repo_nickname> <branch> [--name <name>] [--create-branch]
mahavishnu worktree remove <repo_nickname> <worktree_path> [--force] [--force-reason <text>]
mahavishnu worktree list [--repo <repo_nickname>]
mahavishnu worktree prune <repo_nickname>
mahavishnu worktree prune-merged [--repo <nickname>] [--ttl-days N]
                              [--include-dirty --force-reason <text>]
                              [--dry-run] [--json]
mahavishnu worktree list-sessions [--state active|abandoned|all]
                                [--older-than-days N] [--registry-path <path>] [--json]
mahavishnu worktree prune-abandoned [--older-than-days N] [--dry-run]
                                 [--registry-path <path>] [--json]
mahavishnu worktree scan [--repo ALL|<path>] [--format text|json]
                       [--age-threshold-days <a>,<c>]
mahavishnu worktree safety-status <repo_nickname> <worktree_path>
mahavishnu worktree provider-health
```

### Per-session worktree isolation (multi-Claude-session safety)

When multiple Claude Code sessions run concurrently in the same repo, each session can use its own worktree via `MAHAVISHNU_AUTO_WORKTREE=1` (see [Configuration Reference](CONFIGURATION.md#per-session-worktree-isolation)). The CLI commands below manage the registry that maps session_ids to worktrees.

```bash
# Inspect which sessions are using which worktrees
mahavishnu worktree list-sessions
mahavishnu worktree list-sessions --state abandoned
mahavishnu worktree list-sessions --state all --older-than-days 7

# Preview cleanup of abandoned entries
mahavishnu worktree prune-abandoned --older-than-days 7 --dry-run

# Remove abandoned registry entries older than 7 days
# (the git worktrees themselves stay on disk; remove explicitly with
#  `mahavishnu worktree remove <repo_nickname> <path>`)
mahavishnu worktree prune-abandoned --older-than-days 7

# Override the registry file location (default: XDG state dir)
mahavishnu worktree list-sessions --registry-path /tmp/registry.json
```

The registry never auto-removes worktrees — manual cleanup is the only path to disk reclamation. Use `list-sessions` regularly to monitor growth; run `prune-abandoned` periodically to drop stale entries.

## Terminal Sessions

```bash
mahavishnu terminal launch "<command>" [--count N] [--columns 120] [--rows 40]
mahavishnu terminal list
mahavishnu terminal send <session_id> "<command>"
mahavishnu terminal capture <session_id> [--lines 100]
mahavishnu terminal close <session_id|all>
```

## Indexing

```bash
mahavishnu index repo [<path>]
mahavishnu index status
mahavishnu index install-hooks
mahavishnu index uninstall-hooks
```

## Docs

```bash
mahavishnu docs audit
```

## Events

```bash
mahavishnu events validate [--schema <path>] [--events <file>]
mahavishnu events export   [--output <file>] [--format json]
```

## SOPs

```bash
mahavishnu sop list   [--tag <t>] [--category <c>]
mahavishnu sop show   <name>
mahavishnu sop propose --name <n> [--body <md>] [--tag <t>...]
```

## Patterns (scaffold sub-tool)

```bash
mahavishnu scaffold patterns list   [--tag <t>] [--category <c>]
mahavishnu scaffold patterns show   <name>
mahavishnu scaffold patterns validate
mahavishnu scaffold patterns search [--query <q>]
mahavishnu scaffold                 # Scaffold a project from a pattern
mahavishnu scaffold validate        # Validate scaffold artifacts
```

## Pre-commit

```bash
mahavishnu precommit lock
mahavishnu precommit verify
mahavishnu precommit check-post-hoc
```

## Rollback

```bash
mahavishnu rollback bodai-crow          # Roll back the bodai-crow subsystem
mahavishnu rollback distilled-workflow  # Roll back the distilled-workflow lane
```

## Team

```bash
mahavishnu team create --name <name> [--role <r>] [--skill <s>...]
mahavishnu team parse <file>
mahavishnu team skills <name>
mahavishnu team list
mahavishnu team learning [--limit N]
mahavishnu team recommend [--goal <g>]
mahavishnu team flags <name>
```

## Settle

```bash
mahavishnu settle status [--run-ref <ref>]
mahavishnu settle start  --run-ref <ref> --bindings <json>
```

## Testing & Quality

```bash
pytest
pytest --cov=mahavishnu --cov-report=html
crackerjack run
```

## Notes

- Subcommands and flags shown above were verified against the source tree
  under `mahavishnu/` (and `mahavishnu/cli/`) on the date of this doc
  revision.
- The bare top-level command **`mahavishnu websocket start --port <port>`**
  shown in earlier revisions of this doc is **not a real command**. The
  WebSocket server is started as part of `mahavishnu mcp start` and
  inspected via the MCP server status commands. There is no `monitor
  pools` / `monitor workflows` command either — the `monitor` sub-app only
  exposes `get-dashboard`, `get-alerts`, `acknowledge-alert`,
  `trigger-test-alert`, and `watch`.
- The bare top-level command **`mahavishnu routing recalculate`,
  `routing set-budget`, `routing set-strategy`, `routing list-budgets`,
  `routing delete-budget`** shown in earlier revisions of this doc are
  **not real commands**. The `routing` sub-app only exposes `stats` and
  `reset`.
- The `quality evaluate --content-id <id>` command shown in earlier
  revisions is **not real**. Quality has `check` and `fix` only.
