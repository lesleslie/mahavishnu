# Status Enum Consolidation Plan for Mahavishnu (MHV-008)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Consolidate 24+ duplicate status enums into 4 base enums with domain-specific extensions

**Architecture:** Hierarchical enum system with BaseTaskStatus, BaseWorkflowStatus, BaseResourceStatus, BaseHealthStatus as foundations

**Tech Stack:** Python 3.13+, StrEnum, Pydantic integration

---

## Executive Summary

**Problem**: 20+ status enums scattered across the codebase with duplicate values (PENDING, IN_PROGRESS, COMPLETED, FAILED, etc.) creating inconsistent state management.

**Solution**: Consolidate to **4 base status enums** organized by domain with clear inheritance hierarchy:

1. `BaseTaskStatus` - Generic task/work item states
2. `BaseWorkflowStatus` - Multi-step workflow states
3. `BaseResourceStatus` - Infrastructure resource states
4. `BaseHealthStatus` - Health/quality assessment states

**Benefits**:
- Single source of truth for common states
- Type-safe domain-specific extensions
- Reduced code duplication by ~60%
- Consistent state transition semantics
- Easier testing and validation

---

## Current State Analysis

### Status Enum Inventory

| Enum Name | File | Values | Domain |
|-----------|------|--------|--------|
| `TaskStatus` | task_store.py:51 | PENDING, IN_PROGRESS, COMPLETED, FAILED, CANCELLED, BLOCKED | Task management |
| `TaskStatus` | dependency_manager.py:31 | PENDING, IN_PROGRESS, COMPLETED, FAILED, CANCELLED | Dependency tasks |
| `WorkflowStatus` | workflow_state.py:17 | PENDING, RUNNING, COMPLETED, FAILED, CANCELLED, TIMEOUT | Workflows |
| `PoolStatus` | pools/base.py:9 | PENDING, INITIALIZING, RUNNING, SCALING, DEGRADED, STOPPED, FAILED | Pool resources |
| `WorkerStatus` | workers/base.py:10 | PENDING, STARTING, RUNNING, COMPLETED, FAILED, TIMEOUT, CANCELLED | Worker execution |
| `ExecutionStatus` | metrics_schema.py:47 | SUCCESS, FAILURE, TIMEOUT, CANCELLED | Execution outcomes |
| `IssueStatus` | coordination/models.py:15 | PENDING, IN_PROGRESS, BLOCKED, RESOLVED, CLOSED | Issue tracking |
| `TodoStatus` | coordination/models.py:44 | PENDING, IN_PROGRESS, BLOCKED, COMPLETED, CANCELLED | Task todos |
| `PlanStatus` | coordination/models.py:34 | DRAFT, ACTIVE, ON_HOLD, COMPLETED, CANCELLED | Planning |
| `DependencyStatus` | coordination/models.py:64 | SATISFIED, UNSATISFIED, UNKNOWN, DEPRECATED | Dependencies |
| `DependencyStatus` | dependency_graph.py:33 | PENDING, SATISFIED, FAILED | Dependency graph |
| `DependencyStatus` | cross_repo_dependency.py:48 | PENDING, SATISFIED, FAILED | Cross-repo deps |
| `DeploymentStatus` | deployment_manager.py:35 | PENDING, DEPLOYING, ACTIVE, INACTIVE, FAILED, ROLLING_BACK | Deployments |
| `MigrationStatus` | migrator.py:55 | PENDING, IN_PROGRESS, COMPLETED, FAILED, ROLLED_BACK | Migrations |
| `MigrationStatus` | db_migrations.py:41 | PENDING, RUNNING, COMPLETED, FAILED, ROLLED_BACK | DB migrations |
| `DeadLetterStatus` | dead_letter_queue.py:75 | PENDING, RETRYING, EXHAUSTED, COMPLETED, ARCHIVED | DLQ items |
| `CoordinationStatus` | multi_repo_coordinator.py:45 | PENDING, IN_PROGRESS, COMPLETED, FAILED, ROLLED_BACK | Coordination |
| `BlockingStatus` | cross_repo_blocker.py:43 | ACTIVE, RESOLVED, ESCALATED | Blockers |
| `SyncStatus` | sync_coordinator.py:38 | PENDING, APPROVED, SYNCED, FAILED | Sync state |
| `OnboardingStatus` | onboarding.py:34 | NOT_STARTED, IN_PROGRESS, COMPLETED, SKIPPED | Onboarding |
| `DatabaseStatus` | database.py:37 | DISCONNECTED, CONNECTING, CONNECTED, ERROR | DB connections |
| `HealthStatus` | monitoring_infra.py:55 | HEALTHY, DEGRADED, UNHEALTHY | Health checks |
| `ReadinessStatus` | production_readiness_standalone.py:17 | PASS, FAIL, WARN | Readiness checks |

**Total: 24 enums** with 8 duplicates (same name in different files) and significant value overlap.

---

## Implementation Plan

### Task 1: Create Consolidated Status Module

**Files:**
- Create: `mahavishnu/core/status.py`
- Test: `tests/unit/test_status_enums.py`

**Step 1: Create the base status module**

```python
# mahavishnu/core/status.py
"""Consolidated status enums for Mahavishnu.

This module provides a unified hierarchy of status enums to eliminate
duplication and ensure consistent state management across the codebase.

Design Principles:
- Single source of truth for common states
- Domain-specific extensions inherit from base enums
- Backward compatibility through type aliases
- Clear state transition semantics
"""

from enum import StrEnum


class BaseTaskStatus(StrEnum):
    """Base status for task-like entities.

    Core lifecycle states for any discrete work item that can be
    created, worked on, and brought to completion.
    """
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class BaseWorkflowStatus(StrEnum):
    """Base status for multi-step workflows.

    Extends task states with workflow-specific states for
    coordinating multiple tasks across repositories.
    """
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    ROLLED_BACK = "rolled_back"


class BaseResourceStatus(StrEnum):
    """Base status for infrastructure resources.

    Lifecycle states for managed resources like pools, workers,
    connections, and deployments.
    """
    PENDING = "pending"
    INITIALIZING = "initializing"
    RUNNING = "running"
    ACTIVE = "active"
    DEGRADED = "degraded"
    STOPPED = "stopped"
    FAILED = "failed"


class BaseHealthStatus(StrEnum):
    """Base status for health/quality assessments.

    Assessment states for health checks, readiness probes,
    dependency satisfaction, and quality gates.
    """
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


# Domain-specific enums (used in application code)

class TaskStatus(BaseTaskStatus):
    """Task status for task_store and dependency_manager."""
    pass


class WorkflowStatus(BaseWorkflowStatus):
    """Workflow status for workflow_state."""
    pass


class PoolStatus(BaseResourceStatus):
    """Pool status for pools/base."""
    SCALING = "scaling"


class WorkerStatus(BaseTaskStatus):
    """Worker status for workers/base."""
    STARTING = "starting"
    RUNNING = "running"
    TIMEOUT = "timeout"


class ExecutionStatus(StrEnum):
    """Execution outcome status for metrics."""
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class IssueStatus(BaseTaskStatus):
    """Issue tracking status for coordination/models."""
    RESOLVED = "resolved"
    CLOSED = "closed"


class TodoStatus(BaseTaskStatus):
    """Todo status for coordination/models."""
    pass


class PlanStatus(StrEnum):
    """Plan status for coordination/models."""
    DRAFT = "draft"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class DependencyStatus(StrEnum):
    """Dependency status for coordination/models."""
    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    UNKNOWN = "unknown"
    DEPRECATED = "deprecated"
    PENDING = "pending"
    FAILED = "failed"


class DeploymentStatus(BaseResourceStatus):
    """Deployment status for deployment_manager."""
    DEPLOYING = "deploying"
    INACTIVE = "inactive"
    ROLLING_BACK = "rolling_back"


class MigrationStatus(BaseTaskStatus):
    """Migration status for migrator and db_migrations."""
    ROLLED_BACK = "rolled_back"


class DeadLetterStatus(StrEnum):
    """Dead letter status for dead_letter_queue."""
    PENDING = "pending"
    RETRYING = "retrying"
    EXHAUSTED = "exhausted"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class CoordinationStatus(BaseTaskStatus):
    """Coordination status for multi_repo_coordinator."""
    ROLLED_BACK = "rolled_back"


class BlockingStatus(StrEnum):
    """Blocking status for cross_repo_blocker."""
    ACTIVE = "active"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class SyncStatus(StrEnum):
    """Sync status for sync_coordinator."""
    PENDING = "pending"
    APPROVED = "approved"
    SYNCED = "synced"
    FAILED = "failed"


class OnboardingStatus(StrEnum):
    """Onboarding status for onboarding."""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class DatabaseStatus(BaseResourceStatus):
    """Database status for database."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class HealthStatus(BaseHealthStatus):
    """Health status for monitoring_infra."""
    pass


class ReadinessStatus(StrEnum):
    """Readiness status for production_readiness."""
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
```

**Step 2: Verify the module loads correctly**

Run: `python -c "from mahavishnu.core.status import TaskStatus; print(TaskStatus.PENDING)"`
Expected: `pending`

**Step 3: Create unit tests**

Create comprehensive tests in `tests/unit/test_status_enums.py` covering:
- All base enum values
- Domain-specific enum extensions
- Enum semantics (string comparison, iteration)
- Backward compatibility

**Step 4: Commit**

```bash
git add mahavishnu/core/status.py tests/unit/test_status_enums.py
git commit -m "feat: add consolidated status enum module (MHV-008 Phase 1)

- Create BaseTaskStatus, BaseWorkflowStatus, BaseResourceStatus, BaseHealthStatus
- Add domain-specific extensions: TaskStatus, WorkflowStatus, PoolStatus, etc.
- Consolidate 24 duplicate enums into unified hierarchy
- Add comprehensive unit tests"
```

---

### Task 2: Migrate Core Modules

**Files:**
- Modify: `mahavishnu/core/coordination/models.py`
- Modify: `mahavishnu/core/task_store.py`
- Modify: `mahavishnu/core/dependency_manager.py`
- Modify: `mahavishnu/core/workflow_state.py`

**Step 1: Update coordination/models.py**

Remove local enum definitions and add import:
```python
from mahavishnu.core.status import IssueStatus, TodoStatus, PlanStatus, DependencyStatus
```

**Step 2: Update task_store.py**

Remove local TaskStatus definition and add import:
```python
from mahavishnu.core.status import TaskStatus
```

**Step 3: Update dependency_manager.py**

Remove local TaskStatus definition and add import:
```python
from mahavishnu.core.status import TaskStatus
```

**Step 4: Update workflow_state.py**

Remove local WorkflowStatus definition and add import:
```python
from mahavishnu.core.status import WorkflowStatus
```

**Step 5: Run tests**

Run: `pytest tests/unit/ -v`
Expected: All tests pass

**Step 6: Commit**

```bash
git add mahavishnu/core/coordination/models.py mahavishnu/core/task_store.py \
        mahavishnu/core/dependency_manager.py mahavishnu/core/workflow_state.py
git commit -m "refactor: migrate core modules to consolidated status enums (MHV-008 Phase 2a)"
```

---

### Task 3: Migrate Infrastructure Modules

**Files:**
- Modify: `mahavishnu/pools/base.py`
- Modify: `mahavishnu/workers/base.py`
- Modify: `mahavishnu/core/metrics_schema.py`
- Modify: `mahavishnu/core/dead_letter_queue.py`

**Step 1: Update pools/base.py**

Remove local PoolStatus definition and add import:
```python
from mahavishnu.core.status import PoolStatus
```

**Step 2: Update workers/base.py**

Remove local WorkerStatus definition and add import:
```python
from mahavishnu.core.status import WorkerStatus
```

**Step 3: Update metrics_schema.py**

Remove local ExecutionStatus definition and add import:
```python
from mahavishnu.core.status import ExecutionStatus
```

**Step 4: Update dead_letter_queue.py**

Remove local DeadLetterStatus definition and add import:
```python
from mahavishnu.core.status import DeadLetterStatus
```

**Step 5: Run tests**

Run: `pytest tests/unit/ -v`
Expected: All tests pass

**Step 6: Commit**

```bash
git add mahavishnu/pools/base.py mahavishnu/workers/base.py \
        mahavishnu/core/metrics_schema.py mahavishnu/core/dead_letter_queue.py
git commit -m "refactor: migrate infrastructure modules to consolidated status enums (MHV-008 Phase 2b)"
```

---

### Task 4: Migrate Remaining Modules

**Files:**
- Modify: `mahavishnu/core/deployment_manager.py`
- Modify: `mahavishnu/core/migrator.py`
- Modify: `mahavishnu/core/db_migrations.py`
- Modify: `mahavishnu/core/multi_repo_coordinator.py`
- Modify: `mahavishnu/core/cross_repo_blocker.py`
- Modify: `mahavishnu/core/sync_coordinator.py`
- Modify: `mahavishnu/core/onboarding.py`
- Modify: `mahavishnu/core/database.py`
- Modify: `mahavishnu/core/monitoring_infra.py`
- Modify: `mahavishnu/core/production_readiness_standalone.py`
- Modify: `mahavishnu/core/dependency_graph.py`
- Modify: `mahavishnu/core/cross_repo_dependency.py`

**Step 1: Update each file**

For each file, remove local enum definition and add appropriate import.

**Step 2: Run full test suite**

Run: `pytest`
Expected: All tests pass

**Step 3: Commit**

```bash
git add mahavishnu/core/*.py
git commit -m "refactor: migrate remaining modules to consolidated status enums (MHV-008 Phase 2c)"
```

---

### Task 5: Update Documentation

**Files:**
- Modify: `CLAUDE.md`
- Create: `docs/STATUS_ENUMS.md`

**Step 1: Update CLAUDE.md**

Add reference to new status module:
```markdown
## Key File Locations

### Status Enums
- **Consolidated status enums**: `mahavishnu/core/status.py` - All status enums in unified hierarchy
```

**Step 2: Create STATUS_ENUMS.md**

Document the new enum hierarchy with usage examples.

**Step 3: Commit**

```bash
git add CLAUDE.md docs/STATUS_ENUMS.md
git commit -m "docs: document consolidated status enum system (MHV-008 Phase 5)"
```

---

## Success Criteria

1. **Zero duplicate status enum definitions** across the codebase
2. **All tests passing** after migration
3. **No breaking changes** to public APIs
4. **Documentation updated** with new enum locations
5. **Code reduction** of ~250 lines

## Rollback Plan

If critical issues arise:
1. Revert commits module-by-module
2. Use git to identify problematic commits
3. Re-deploy previous stable version
