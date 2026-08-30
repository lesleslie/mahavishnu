# Bodai CLI Audit — Cross-Repo Synthesis (Phase 2)

**Date:** 2026-08-29
**Source data:** `docs/audit-inventory/{mcp-common,oneiric,dhara,session-buddy,akosha,crackerjack,mahavishnu}-cli-inventory.json`
**Baseline:** `docs/audit-inventory/PHASE_0_BASELINE.json`

## 1. Per-repo command counts

| Repo | Top-level | Sub-cmds | Total | Notes |
|---|---|---|---|---|
| mcp-common | 0 | 0 | 0 | library-only |
| oneiric | 22 | 0 | 30 | |
| dhara | 6 | 0 | 15 | |
| session-buddy | 3 | 0 | 16 | |
| akosha | 8 | 0 | 9 | |
| crackerjack | 11 | 0 | 32 | |
| mahavishnu | 19 | 0 | 159 | |

## 2. Cross-repo command-name duplications

Top-level command names appearing in 2+ repos. Coordinated-by-design duplications (e.g., `version` from OneiricCLIBase base class) are noted as such.

| Command name | Repos (count) | Notes |
|---|---|---|
| `adapter` | 1 (mahavishnu) | |
| `analytics` | 1 (session-buddy) | |
| `audit` | 1 (crackerjack) | |
| `backup` | 1 (mahavishnu) | |
| `coord` | 1 (mahavishnu) | |
| `coverage-ratchet` | 1 (crackerjack) | |
| `db` | 1 (dhara) | |
| `docs` | 2 (crackerjack, mahavishnu) | |
| `doctor` | 6 (akosha, crackerjack, dhara, mahavishnu, oneiric, session-buddy) | coordinated (oneiric.cli.base inherited) |
| `ecosystem` | 1 (mahavishnu) | |
| `events` | 1 (mahavishnu) | |
| `health` | 6 (akosha, crackerjack, dhara, mahavishnu, oneiric, session-buddy) | |
| `index` | 1 (mahavishnu) | |
| `ingest` | 1 (mahavishnu) | |
| `manifest` | 1 (oneiric) | |
| `mcp` | 4 (akosha, crackerjack, dhara, mahavishnu) | |
| `metrics` | 1 (mahavishnu) | |
| `monitor` | 1 (mahavishnu) | |
| `pool` | 1 (mahavishnu) | |
| `precommit` | 1 (mahavishnu) | |
| `production` | 1 (mahavishnu) | |
| `quality` | 1 (mahavishnu) | |
| `repo` | 1 (mahavishnu) | |
| `rollback` | 1 (mahavishnu) | |
| `routing` | 1 (mahavishnu) | |
| `scaffold` | 1 (mahavishnu) | |
| `server` | 1 (session-buddy) | |
| `shell` | 4 (akosha, crackerjack, mahavishnu, oneiric) | |
| `sop` | 1 (mahavishnu) | |
| `start` | 3 (akosha, crackerjack, oneiric) | |
| `status` | 2 (crackerjack, oneiric) | |
| `stop` | 2 (crackerjack, oneiric) | |
| `team` | 1 (mahavishnu) | |
| `terminal` | 1 (mahavishnu) | |
| `version` | 6 (akosha, crackerjack, dhara, mahavishnu, oneiric, session-buddy) | |
| `workers` | 1 (mahavishnu) | |
| `workflow` | 2 (mahavishnu, oneiric) | |
| `worktree` | 1 (mahavishnu) | |

## 3. Orphan sub-CLI modules

Modules defining commands that no other module imports. These indicate dead code or future-API experiments.

| Module | Repo | Command count | Notes |
|---|---|---|---|
| `akosha.cli` | akosha | 6 | mono-repo |
| `crackerjack.__main__` | crackerjack | 4 | mono-repo |
| `crackerjack.cli.audit_cli` | crackerjack | 3 | mono-repo |
| `crackerjack.cli.coverage_ratchet_cli` | crackerjack | 3 | mono-repo |
| `crackerjack.cli.docs_cli` | crackerjack | 8 | mono-repo |
| `crackerjack.cli.mcp_cli` | crackerjack | 5 | mono-repo |
| `dhara.cli` | dhara | 7 | mono-repo |
| `mahavishnu._main_cli` | mahavishnu | 45 | mono-repo |
| `mahavishnu.backup_cli` | mahavishnu | 6 | mono-repo |
| `mahavishnu.cli.config_validator` | mahavishnu | 6 | mono-repo |
| `mahavishnu.cli.index_cli` | mahavishnu | 4 | mono-repo |
| `mahavishnu.cli.monitoring_cli` | mahavishnu | 5 | mono-repo |
| `mahavishnu.cli.precommit_cli` | mahavishnu | 3 | mono-repo |
| `mahavishnu.cli.scaffold_cli` | mahavishnu | 6 | mono-repo |
| `mahavishnu.cli.sop_cli` | mahavishnu | 3 | mono-repo |

## 4. Hidden / deprecated commands still referenced

Commands with `deprecated: true` or `hidden: true` flags.

| Command | Repo | Flags | Notes |
|---|---|---|---|
| [`db server`](../audit-inventory/dhara-cli-inventory.json#L125) | dhara | hidden | — |

## 5. Stale commands

`staleness_verdict != 'current'`. Per the inventory tool: deprecated, or experimental-and-stub, or `todo_markers >= 3`, or `last_activity_days > 365` with at least one TODO marker.

| Command | Repo | Staleness verdict | Reason |
|---|---|---|---|
|_No stale commands. All commands are `current`._|

## 6. Top-10 most-changed commands

Sorted by `last_modified_date` (most recent first). Since the inventory tool does not yet populate `last_modified_sha` / `last_modified_date` from git history per command file, this table shows commands with non-zero `last_activity_days`.

| Command | Repo | Last activity (days) | Module |
|---|---|---|---|
| [`checkpoint cleanup-snapshots`](../audit-inventory/session-buddy-cli-inventory.json#L105) | session-buddy | 1 | `session_buddy.cli.checkpoint_cli` |
| [`workflow sweep`](../audit-inventory/mahavishnu-cli-inventory.json#L245) | mahavishnu | 1 | `mahavishnu._main_cli` |
| [`workflow quality-check`](../audit-inventory/mahavishnu-cli-inventory.json#L265) | mahavishnu | 1 | `mahavishnu._main_cli` |
| [`workflow heal`](../audit-inventory/mahavishnu-cli-inventory.json#L285) | mahavishnu | 1 | `mahavishnu._main_cli` |
| [`workflow fix`](../audit-inventory/mahavishnu-cli-inventory.json#L305) | mahavishnu | 1 | `mahavishnu._main_cli` |
| [`workflow review`](../audit-inventory/mahavishnu-cli-inventory.json#L325) | mahavishnu | 1 | `mahavishnu._main_cli` |
| [`workflow prefect-list-deployments`](../audit-inventory/mahavishnu-cli-inventory.json#L345) | mahavishnu | 1 | `mahavishnu._main_cli` |
| [`workflow prefect-get-deployment`](../audit-inventory/mahavishnu-cli-inventory.json#L365) | mahavishnu | 1 | `mahavishnu._main_cli` |
| [`workflow prefect-list-flow-runs`](../audit-inventory/mahavishnu-cli-inventory.json#L385) | mahavishnu | 1 | `mahavishnu._main_cli` |
| [`workflow prefect-cancel-flow-run`](../audit-inventory/mahavishnu-cli-inventory.json#L405) | mahavishnu | 1 | `mahavishnu._main_cli` |

______________________________________________________________________

_Synthesis run completed: 7 repos, 261 total commands._
