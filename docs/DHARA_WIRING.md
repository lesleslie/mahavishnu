# Dhara Wiring Checklist (Ecosystem)

This document describes **what still needs to be wired** to make Dhara useful
as the ecosystem’s persistent store, now that `put/get` and time‑series tools
exist in the Dhara MCP server.

## Current Consumers (Already in Code)

### Mahavishnu

- **Health persistence** uses `put(key, value, ttl)` via `DharaClient`.

  - File: `mahavishnu/core/health_integration.py`
  - Key format: `health:adapter:{adapter_name}` (TTL 7 days)
  - **Status:** Ready once Dhara MCP server is running.

- **Git analytics** reads time‑series with:

  - `query_time_series(metric_type="git_velocity", entity_id=repo_path, start_date=...)`
  - `query_time_series(metric_type="repository_health", entity_id=repo_path, limit=...)`
  - `aggregate_patterns(start_date=..., min_occurrences=...)`
  - File: `mahavishnu/mcp/tools/git_analytics.py`
  - **Status:** Reader is wired; **writers are missing**.

### Oneiric

- **Adapter registry push** writes to Dhara via `store_adapter`.
  - File: `oneiric/adapters/dhara_pusher.py`
  - **Status:** Works when Dhara MCP server is up.

## Missing Producers (Need Wiring)

### 1. Crackerjack → Dhara Time‑Series

Crackerjack is the natural producer of git metrics, but there is no code
calling `record_time_series` today.

**Needs:**

- Emit `git_velocity` records (per repo)
- Emit `repository_health` records (per repo)

**Suggested schema (JSON record):**

```
metric_type: "git_velocity"
entity_id: "<repo_path>"
record: {
  "commits": int,
  "branch_switches": int,
  "merge_conflicts": int,
  "pattern": "optional-string"
}
```

```
metric_type: "repository_health"
entity_id: "<repo_path>"
record: {
  "open_prs": int,
  "stale_prs": int,
  "stale_branches": int,
  "pattern": "optional-string"
}
```

**Where to wire:**

- The code that already collects git metrics or test results.
- If no such collector exists yet, add a small collector in Crackerjack
  that runs after quality checks and writes the metrics.

### 2. Optional: Mahavishnu → Dhara Time‑Series

If Mahavishnu generates any cross‑repo workflow metrics, those can be
persisted to Dhara too. Nothing currently writes from Mahavishnu.

**Possible schema:**

```
metric_type: "workflow_performance"
entity_id: "<repo_path>" or "<workflow_id>"
record: {
  "duration_ms": int,
  "success": bool,
  "phase": "string",
  "pattern": "optional-string"
}
```

## Tool API (Dhara MCP)

Available tools on Dhara MCP server:

- `put(key, value, ttl=None)`
- `get(key)`
- `record_time_series(metric_type, entity_id, record, timestamp=None)`
- `query_time_series(metric_type, entity_id, start_date=None, limit=None)`
- `aggregate_patterns(start_date, min_occurrences=2)`
- Adapter registry tools: `store_adapter`, `get_adapter`, `list_adapters`,
  `list_adapter_versions`, `validate_adapter`, `get_adapter_health`

## Retention & Patterns

- Time‑series retention default: **60 days**
- `aggregate_patterns` looks for any of these fields in records:
  - `pattern`, `issue_type`, `event`, `category`
  - If you want patterns, include one of those in the record payload.

## Minimal Wiring Plan

1. **Crackerjack**: add calls to `record_time_series` after git/quality runs.
1. **Mahavishnu**: no change needed for reads; it already queries Dhara.
1. **Dhara**: ensure MCP server is running on `http://localhost:8683/mcp`.
