# Phase 3: Cross-Repo Coordination — Gap Closure

**Date**: 2026-05-07
**Status**: In progress
**Scope**: Close the three remaining gaps in the coordination layer

## What's Already Done

The coordination infrastructure is largely complete (2951 lines, 316 passing tests):

| Component | File | Status |
|---|---|---|
| Data models | `core/coordination/models.py` (256 lines) | ✅ |
| CoordinationManager (full CRUD) | `core/coordination/manager.py` (718 lines) | ✅ |
| CoordinationMemory (Session-Buddy) | `core/coordination/memory.py` (609 lines) | ✅ |
| CoordinationExecutor (pool dispatch) | `core/coordination/executor.py` (402 lines) | ✅ |
| MCP tools (issues/todos/deps/plans/status) | `mcp/tools/coordination_tools.py` (332 lines) | ✅ |
| CLI commands (issues/todos/deps/status/blocking) | `coordination_cli.py` (586 lines) | ✅ |
| Unit tests | `tests/unit/test_coordination*.py` (316 tests) | ✅ |

## What's Missing

### Gap A: Unified Ecosystem Status Surface

The roadmap requires a single query that answers: "What is blocked, failing, and needs operator action — right now?"

Missing:
- `CoordinationManager.get_ecosystem_status()` — aggregates active plans, critical blockers, degraded deps
- `coord_get_ecosystem_status` MCP tool in `coordination_tools.py`
- `mahavishnu coord ecosystem-status` CLI command
- `mahavishnu coord roadmap` CLI command (active plans with milestone progress)

### Gap B: Akosha Integration

`CoordinationMemory` pushes events to Session-Buddy but not to Akosha. The roadmap requires operators and agents can search issues, plans, and failure patterns semantically across the ecosystem.

Missing:
- Akosha HTTP client in `CoordinationMemory.__init__`
- `_push_to_akosha()` helper — POST to `{akosha_url}/tools/call` with `store_memory` tool
- `search_semantic()` method — POST to Akosha `search_all_systems` for cross-system semantic search
- URL sourced from `config.pools.akosha_url` (already in config)

### Gap C: Tests

- Tests for `get_ecosystem_status` (empty state, populated state, degraded deps surface)
- Tests for Akosha push path (respx mock, degrade on ConnectError)
- Tests for `ecosystem-status` and `roadmap` CLI commands

## Implementation Plan

### A1: `get_ecosystem_status()` in CoordinationManager

Add to `manager.py`:

```python
def get_ecosystem_status(self) -> dict[str, Any]:
    active_plans = self.list_plans(status="active")
    critical_issues = self.list_issues(priority="critical", status=None)
    # all blocking issues (high+critical, non-closed)
    blocking_issues = [
        i for i in self.list_issues()
        if i.priority.value in ("critical", "high")
        and i.status.value not in ("resolved", "closed")
    ]
    dep_check = self.check_dependencies()
    unsatisfied_deps = [
        d for d in dep_check["dependencies"]
        if d["status"] != "satisfied"
    ]
    pending_todos = self.list_todos(status=TodoStatus.PENDING)
    in_progress_todos = self.list_todos(status=TodoStatus.IN_PROGRESS)

    return {
        "active_plans": len(active_plans),
        "plans": [{"id": p.id, "title": p.title, "target": p.target, "milestones": len(p.milestones)} for p in active_plans],
        "critical_blockers": len(blocking_issues),
        "blockers": [{"id": i.id, "title": i.title, "priority": i.priority.value, "repos": i.repos} for i in blocking_issues],
        "degraded_dependencies": len(unsatisfied_deps),
        "dependencies": unsatisfied_deps,
        "pending_todos": len(pending_todos),
        "in_progress_todos": len(in_progress_todos),
        "health": "degraded" if (blocking_issues or unsatisfied_deps) else "healthy",
    }
```

### A2: MCP tool `coord_get_ecosystem_status`

Add to `coordination_tools.py`:

```python
async def coord_get_ecosystem_status() -> dict[str, Any]:
    """Get unified ecosystem coordination status — active plans, blockers, degraded deps."""
    mgr = _get_manager()
    return mgr.get_ecosystem_status()
```

### A3: CLI commands

Add to `coordination_cli.py`:

```bash
mahavishnu coord ecosystem-status   # single-pane view: blockers, deps, plan health
mahavishnu coord roadmap             # active plans with milestone progress table
```

### B1: Akosha push in CoordinationMemory

`CoordinationMemory.__init__` accepts optional `akosha_url: str | None`. If provided, push coordination events to Akosha after Session-Buddy storage. Degrade silently on `httpx.TransportError`.

Push uses the same `/tools/call` REST pattern as other services:
```
POST {akosha_url}/tools/call
{"name": "store_memory", "arguments": {"content": ..., "metadata": ..., "collection": "coordination"}}
```

### B2: `search_semantic()` in CoordinationMemory

```python
async def search_semantic(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search coordination history semantically via Akosha."""
    # POST to akosha search_all_systems tool
```

### C: Tests

- `test_coordination.py` or new `test_coordination_status.py`:
  - `test_get_ecosystem_status_empty` — no issues/deps → health=healthy
  - `test_get_ecosystem_status_with_blockers` — critical issue → health=degraded
  - `test_get_ecosystem_status_unsatisfied_dep` — dep check failure → degraded_dependencies=1
- `test_coordination_memory.py` (new):
  - Akosha push degrades silently on ConnectError (respx mock)
  - `search_semantic` returns list on success, empty list on error

## Files to Modify

| File | Change |
|---|---|
| `mahavishnu/core/coordination/manager.py` | Add `get_ecosystem_status()` |
| `mahavishnu/core/coordination/memory.py` | Add Akosha client, `_push_to_akosha()`, `search_semantic()` |
| `mahavishnu/mcp/tools/coordination_tools.py` | Add `coord_get_ecosystem_status` tool |
| `mahavishnu/coordination_cli.py` | Add `ecosystem-status` and `roadmap` commands |
| `tests/unit/test_coordination.py` or new test file | Tests for ecosystem status and Akosha integration |

## Success Criteria (from Roadmap)

- Operators can ask Mahavishnu what is blocked, what is failing, and what should happen next → answered by `coord ecosystem-status` and `coord_get_ecosystem_status`
- Cross-repo dependencies are validated → already done; now surfaced in unified status
- Ecosystem artifacts stop fragmenting → coordination history searchable via Akosha `search_semantic`
- Coordinated work tracked as one workflow → done via executor; now visible via roadmap command
