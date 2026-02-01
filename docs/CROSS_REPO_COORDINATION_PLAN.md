# Cross-Repository Coordination System Implementation Plan

**Status:** Proposed
**Date:** 2026-01-31
**Author:** @les
**Priority:** High

## Executive Summary

Add a cross-repository orchestration and tracking layer to Mahavishnu that enables:

1. **Issue Tracking** - Global issues affecting multiple repositories
2. **Plan Management** - Cross-repo roadmaps and milestones
3. **Task Orchestration** - Decomposed tasks with dependencies and blocking
4. **Dependency Management** - Inter-repo dependency tracking and validation
5. **Workflow Coordination** - Automated execution across repositories

## Goals

### Primary Goals

1. **Single Source of Truth** - Centralized coordination data in ecosystem.yaml
2. **Role-Based Routing** - Leverage existing role taxonomy for intelligent task distribution
3. **Dependency-Aware** - Track and resolve inter-repo dependencies
4. **Memory Integration** - Store coordination history in Session-Buddy/AgentDB
5. **Pool Execution** - Distribute tasks across worker pools

### Non-Goals

- Replace GitHub/GitLab issue tracking (local coordination, not remote)
- Build a full project management system (focused on orchestration, not PM)
- UI/dashboard (CLI-first, can add web UI later)

## Architecture

### Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    CoordinationManager                          │
│  • Load/parse coordination section from ecosystem.yaml          │
│  • Validate dependencies and constraints                        │
│  • Provide query API (blocking issues, repo status, etc.)       │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ├─→ CLI Commands (coord *)
                           │
                           ├─→ MCP Tools (coord_*)
                           │
                           ├─→ Memory Integration (Session-Buddy)
                           │
                           └─→ Pool Execution (dispatch tasks)
```

### Schema Design

**coordination section in ecosystem.yaml:**

```yaml
coordination:
  # Global issues affecting multiple repos
  issues:
    - id: "ISSUE-001"
      title: "Update all repos to Python 3.13"
      description: "Comprehensive Python 3.13 migration across ecosystem"
      status: "in_progress"
      priority: "high"
      severity: "migration"
      repos: ["mahavishnu", "session-buddy", "crackerjack", "fastblocks"]
      created: "2026-01-31"
      updated: "2026-01-31"
      target: "2026-02-15"
      dependencies: []
      blocking: []
      assignee: "les"
      labels: ["migration", "python", "breaking"]
      metadata:
        migration_guide: "docs/python-3.13-migration.md"
        test_plan: "tests/test_python_3_13_compatibility.py"

  # Cross-repo plans/roadmaps
  plans:
    - id: "PLAN-001"
      title: "Q1 2026 Feature Roadmap"
      description: "Strategic initiatives for Q1 2026"
      status: "active"
      repos: ["mahavishnu", "oneiric", "session-buddy"]
      created: "2026-01-01"
      updated: "2026-01-31"
      target: "2026-03-31"
      milestones:
        - id: "MILESTONE-001"
          name: "Memory Integration Complete"
          description: "Unified memory architecture across all repos"
          due: "2026-02-28"
          status: "in_progress"
          dependencies: []
          completion_criteria:
            - "All repos using Session-Buddy memory"
            - "AgentDB backend operational"
            - "Cross-project search working"
          deliverables:
            - "docs/MEMORY_INTEGRATION.md"
            - "tests/test_memory_integration.py"

  # Decomposed tasks (atomic units of work)
  todos:
    - id: "TODO-001"
      task: "Implement unified memory service"
      description: "Create MahavishnuMemoryIntegration class"
      repo: "mahavishnu"
      status: "pending"
      priority: "high"
      created: "2026-01-31"
      updated: "2026-01-31"
      estimated_hours: 24
      actual_hours: null
      blocked_by: ["ISSUE-001"]
      blocking: ["TODO-002", "TODO-003"]
      assignee: "les"
      labels: ["memory", "integration"]
      acceptance_criteria:
        - "Implements MahavishnuMemoryIntegration class"
        - "Passes all unit tests"
        - "Documented in docs/MEMORY_INTEGRATION.md"

  # Inter-repo dependencies
  dependencies:
    - id: "DEP-001"
      consumer: "fastblocks"
      provider: "oneiric"
      type: "runtime"
      version_constraint: ">=0.2.0"
      status: "satisfied"
      created: "2026-01-15"
      updated: "2026-01-30"
      notes: "FastBlocks requires Oneiric 0.2.0+ for lifecycle management"
      validation:
        command: "pip show oneiric | grep Version"
        expected_pattern: "^Version: 0\\.2\\."

    - id: "DEP-002"
      consumer: "mahavishnu"
      provider: "session-buddy"
      type: "mcp"
      version_constraint: ">=0.1.0"
      status: "satisfied"
      created: "2026-01-15"
      updated: "2026-01-30"
      notes: "Mahavishnu requires Session-Buddy MCP server for memory"
      validation:
        health_check: "http://127.0.0.1:8678/health"
        expected_status: 200
```

### CLI Commands

```bash
# Issue management
mahavishnu coord list-issues                    # List all issues
mahavishnu coord list-issues --status in_progress --priority high
mahavishnu coord show-issue ISSUE-001           # Show issue details
mahavishnu coord create-issue --title "..." --repos "mahavishnu,session-buddy"
mahavishnu coord update-issue ISSUE-001 --status resolved
mahavishnu coord close-issue ISSUE-001

# Plan management
mahavishnu coord list-plans                     # List all plans
mahavishnu coord show-plan PLAN-001             # Show plan details
mahavishnu coord create-plan --title "..." --milestones "..."
mahavishnu coord update-plan PLAN-001 --status completed

# Todo management
mahavishnu coord list-todos                     # List all todos
mahavishnu coord list-todos --repo session-buddy
mahavishnu coord list-todos --assignee les
mahavishnu coord show-todo TODO-001             # Show todo details
mahavishnu coord create-todo --repo mahavishnu --task "..." --estimate "3d"
mahavishnu coord update-todo TODO-001 --status in_progress
mahavishnu coord complete-todo TODO-001

# Dependency management
mahavishnu coord list-deps                      # List all dependencies
mahavishnu coord check-deps                     # Validate all dependencies
mahavishnu coord check-deps --consumer fastblocks
mahavishnu coord dep-graph                      # Generate dependency graph
mahavishnu coord validate-repo mahavishnu       # Validate repo's dependencies

# Status and reports
mahavishnu coord status --repo mahavishnu       # Show repo coordination status
mahavishnu coord blocking mahavishnu            # Show what's blocking a repo
mahavishnu coord blocked-by mahavishnu          # Show what this repo blocks
mahavishnu coord roadmap                        # Show all active plans
mahavishnu coord workload                       # Show workload distribution

# Workflow integration
mahavishnu coord execute TODO-001               # Execute todo via pool
mahavishnu coord sweep --plan PLAN-001          # Execute all todos in plan
mahavishnu coord validate --plan PLAN-001       # Validate plan completion
```

### MCP Tools

```python
@mcp.tool()
async def coord_list_issues(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    repo: Optional[str] = None,
) -> List[Dict]:
    """List cross-repository issues with filtering."""

@mcp.tool()
async def coord_create_issue(
    title: str,
    description: str,
    repos: List[str],
    priority: str = "medium",
    target: Optional[str] = None,
) -> Dict:
    """Create a new cross-repository issue."""

@mcp.tool()
async def coord_get_blocking_issues(repo: str) -> List[Dict]:
    """Get all issues blocking a specific repository."""

@mcp.tool()
async def coord_check_dependencies(consumer: Optional[str] = None) -> Dict:
    """Validate inter-repository dependencies."""

@mcp.tool()
async def coord_get_repo_status(repo: str) -> Dict:
    """Get comprehensive coordination status for a repository."""

@mcp.tool()
async def coord_create_todo(
    task: str,
    repo: str,
    description: str,
    estimate_hours: float,
    blocked_by: Optional[List[str]] = None,
) -> Dict:
    """Create a new task/todo item."""
```

## Implementation Phases

### Phase 1: Core Data Models (Day 1)

**File:** `mahavishnu/core/coordination/models.py`

- [ ] Define Pydantic models for Issue, Plan, Todo, Dependency
- [ ] Implement status enums and validation
- [ ] Add type hints throughout
- [ ] Write unit tests for models
- [ ] Document all models with docstrings

**Models to implement:**

```python
class IssueStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    RESOLVED = "resolved"
    CLOSED = "closed"

class Priority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class CrossRepoIssue(BaseModel):
    """Issue affecting multiple repositories."""
    id: str
    title: str
    description: str
    status: IssueStatus
    priority: Priority
    severity: str
    repos: List[str]
    created: str
    updated: str
    target: Optional[str]
    dependencies: List[str]
    blocking: List[str]
    assignee: Optional[str]
    labels: List[str]
    metadata: Dict[str, Any]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "ISSUE-001",
                "title": "Update all repos to Python 3.13",
                "status": "in_progress",
                "priority": "high",
            }
        }
    )
```

### Phase 2: Coordination Manager (Day 1-2)

**File:** `mahavishnu/core/coordination/manager.py`

- [ ] Implement CoordinationManager class
- [ ] Load/parse coordination section from ecosystem.yaml
- [ ] Implement query methods (get_blocking_issues, etc.)
- [ ] Add validation logic for dependencies
- [ ] Implement CRUD operations for issues/plan/todos
- [ ] Add proper error handling
- [ ] Write unit tests
- [ ] Add docstrings

**Key methods:**

```python
class CoordinationManager:
    """Manage cross-repository coordination data."""

    def __init__(self, ecosystem_path: str = "settings/ecosystem.yaml") -> None:
        """Initialize coordination manager."""
        self.ecosystem_path = Path(ecosystem_path)
        self.ecosystem = self._load_ecosystem()
        self.coordination = self.ecosystem.get("coordination", {})

    def get_blocking_issues(self, repo: str) -> List[CrossRepoIssue]:
        """Get all issues blocking a specific repository."""

    def create_issue(self, issue: CrossRepoIssue) -> None:
        """Create a new cross-repository issue."""

    def check_dependencies(self, consumer: Optional[str] = None) -> Dict[str, Any]:
        """Validate inter-repository dependencies."""

    def get_repo_status(self, repo: str) -> Dict[str, Any]:
        """Get comprehensive coordination status for a repository."""
```

### Phase 3: CLI Commands (Day 2-3)

**File:** `mahavishnu/cli.py` (extend existing)

- [ ] Add `coord` command group
- [ ] Implement issue management commands
- [ ] Implement plan management commands
- [ ] Implement todo management commands
- [ ] Implement dependency management commands
- [ ] Implement status/report commands
- [ ] Add proper error handling and user feedback
- [ ] Write integration tests

**Command structure:**

```python
@app.command_group("coord")
def coord() -> None:
    """Cross-repository coordination and tracking."""

@coord.command("list-issues")
def list_issues(
    status: Optional[str] = typer.Option(None, "--status"),
    priority: Optional[str] = typer.Option(None, "--priority"),
    repo: Optional[str] = typer.Option(None, "--repo"),
) -> None:
    """List cross-repository issues with optional filtering."""
```

### Phase 4: MCP Tools Integration (Day 3-4)

**File:** `mahavishnu/mcp/tools/coordination_tools.py`

- [ ] Create MCP tool file
- [ ] Implement coord_list_issues tool
- [ ] Implement coord_create_issue tool
- [ ] Implement coord_get_blocking_issues tool
- [ ] Implement coord_check_dependencies tool
- [ ] Implement coord_get_repo_status tool
- [ ] Implement coord_create_todo tool
- [ ] Register tools in MCP server
- [ ] Write integration tests

### Phase 5: Memory Integration (Day 4)

**File:** `mahavishnu/core/coordination/memory.py`

- [ ] Implement memory storage for coordination events
- [ ] Store issue/plan/todo changes in Session-Buddy
- [ ] Enable semantic search across coordination history
- [ ] Add analytics and trends detection
- [ ] Write tests for memory integration

```python
class CoordinationMemory:
    """Store coordination events in memory systems."""

    async def store_event(
        self,
        event_type: str,
        entity_id: str,
        data: Dict[str, Any],
    ) -> None:
        """Store coordination event in Session-Buddy."""
        await self.session_buddy.store_memory(
            collection="mahavishnu_coordination",
            content=f"{event_type}: {entity_id}",
            metadata=data,
        )
```

### Phase 6: Pool Integration (Day 5)

**File:** `mahavishnu/core/coordination/executor.py`

- [ ] Implement task execution via pools
- [ ] Add dispatch logic for todos
- [ ] Implement plan sweep execution
- [ ] Add progress tracking
- [ ] Handle failures and retries
- [ ] Write integration tests

```python
class CoordinationExecutor:
    """Execute coordination tasks via worker pools."""

    async def execute_todo(
        self,
        todo_id: str,
        pool_type: PoolType = PoolType.MAHAVISHNU,
    ) -> Dict[str, Any]:
        """Execute a todo via specified pool."""

    async def sweep_plan(
        self,
        plan_id: str,
        pool_selector: PoolSelector = PoolSelector.LEAST_LOADED,
    ) -> Dict[str, Any]:
        """Execute all pending todos in a plan."""
```

### Phase 7: Testing & Documentation (Day 5-6)

- [ ] Comprehensive unit tests (>80% coverage)
- [ ] Integration tests for CLI commands
- [ ] Integration tests for MCP tools
- [ ] End-to-end tests for workflows
- [ ] Documentation in docs/CROSS_REPO_COORDINATION.md
- [ ] Add examples and usage guides
- [ ] Update CLAUDE.md

## Dependencies

### Required Dependencies (Already Installed)

- `pydantic>=2.0` - Data validation
- `pyyaml` - YAML parsing
- `typer` - CLI framework
- `rich` - Terminal output
- `structlog` - Structured logging

### New Dependencies (None)

All functionality can be built with existing dependencies.

## Configuration

### ecosystem.yaml Updates

Add `coordination` section to `settings/ecosystem.yaml`:

```yaml
coordination:
  issues: []
  plans: []
  todos: []
  dependencies: []
```

### mahavishnu.yaml Updates

Add coordination settings:

```yaml
coordination:
  enabled: true
  memory_enabled: true
  pool_execution_enabled: true
  auto_dependency_check: true
  dependency_check_interval_minutes: 60
```

## Migration Strategy

### Phase 1: Additive (No Breaking Changes)

- Add coordination section to ecosystem.yaml
- Implement CoordinationManager side-by-side with existing code
- Add new CLI commands without modifying existing ones
- New MCP tools don't affect existing tools

### Phase 2: Integration (Optional Enhancements)

- Integrate with existing adapters (LlamaIndex, Agno, Prefect)
- Add coordination checks to workflow execution
- Enhance pool management with coordination awareness

### Phase 3: Automation (Future Enhancements)

- Automatic dependency validation on repo changes
- Auto-creation of issues on dependency conflicts
- Automated testing via coordination system

## Success Metrics

### Functional Requirements

- ✅ Create/read/update/delete issues, plans, todos
- ✅ Query by status, priority, repo, assignee
- ✅ Validate inter-repo dependencies
- ✅ Execute tasks via pools
- ✅ Store events in memory systems
- ✅ Generate reports and status

### Quality Metrics

- ✅ Test coverage >80%
- ✅ All models have type hints
- ✅ All functions have docstrings
- ✅ No error suppression
- ✅ Proper error handling with custom exceptions

### Performance Metrics

- ✅ Load ecosystem.yaml <100ms
- ✅ Query operations <50ms
- ✅ Dependency validation <500ms
- ✅ Status report generation <1s

## Risks & Mitigations

### Risk 1: Complexity Explosion

**Risk:** Coordination system becomes too complex to maintain

**Mitigation:**
- Start simple, add features incrementally
- Keep schema flexible but structured
- Document all patterns and conventions
- Regular refactoring

### Risk 2: Data Synchronization

**Risk:** ecosystem.yaml becomes stale vs. reality

**Mitigation:**
- Auto-update timestamps on every operation
- Validation commands to detect inconsistencies
- Integration with git for version control
- Regular audits via crackerjack

### Risk 3: Performance at Scale

**Risk:** System slows down with many issues/todos

**Mitigation:**
- Efficient query patterns with indexing
- Lazy loading of coordination data
- Caching frequently accessed data
- Database backend for large deployments (future)

## Open Questions

1. **Issue ID Generation:** Auto-generate or manual? (Recommend: auto-generate with prefix)
2. **Version Control:** Should coordination data be in git? (Recommend: yes, ecosystem.yaml is committed)
3. **Remote Integration:** Sync with GitHub/GitLab issues? (Recommend: future enhancement)
4. **Web UI:** Build dashboard for visualization? (Recommend: future, CLI-first)
5. **Access Control:** Multi-user support? (Recommend: single-user for now)

## Timeline

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| Phase 1 | Day 1 | Data models with tests |
| Phase 2 | Day 1-2 | CoordinationManager with tests |
| Phase 3 | Day 2-3 | CLI commands with tests |
| Phase 4 | Day 3-4 | MCP tools with tests |
| Phase 5 | Day 4 | Memory integration with tests |
| Phase 6 | Day 5 | Pool integration with tests |
| Phase 7 | Day 5-6 | Documentation and examples |

**Total: 6 days**

## References

- [ADR 001: Use Oneiric](./adr/001-use-oneiric.md) - Configuration patterns
- [ADR 002: MCP-First Design](./adr/002-mcp-first-design.md) - MCP architecture
- [ADR 004: Adapter Architecture](./adr/004-adapter-architecture.md) - Multi-adapter patterns
- [ADR 005: Unified Memory Architecture](./adr/005-memory-architecture.md) - Memory integration
- [ECOSYSTEM.md](./ECOSYSTEM.md) - Ecosystem catalog
- [POOL_ARCHITECTURE.md](./POOL_ARCHITECTURE.md) - Pool management
