# Mahavishnu Task Orchestration System - Master Plan

**Status**: DRAFT - Pending Power Trio Reviews
**Created**: 2025-02-18
**Author**: Claude Sonnet 4.5 + User Collaboration
**Version**: 1.0

---

## Executive Summary

The Mahavishnu Task Orchestration System (MTOS) is a natural language-powered task management platform designed specifically for multi-repository software development ecosystems. It leverages the existing Mahavishnu ecosystem components (Akosha, Dhruva, Session-Buddy, Crackerjack) to provide intelligent task creation, semantic search, predictive insights, and seamless workflow orchestration.

**Key Differentiators:**
- Natural language task creation with semantic understanding
- Multi-repository task coordination and dependency management
- Ecosystem-aware (uses existing Akosha/Dhruva/Session-Buddy/Crackerjack)
- One-way sync from GitHub/GitLab (with approval workflow)
- Quality gate integration (Crackerjack)
- Worktree-aware development workflow
- Multiple interface options (CLI, TUI, GUI, Web)

**Target Users:**
- Developers working across multiple repositories
- Technical leads coordinating cross-repo features
- Open source maintainers managing external issues
- Engineering teams needing AI-assisted task prioritization

---

## Table of Contents

1. [Vision & Goals](#vision--goals)
2. [Ecosystem Integration](#ecosystem-integration)
3. [Architecture](#architecture)
4. [Core Features](#core-features)
5. [Storage Strategy](#storage-strategy)
6. [User Interfaces](#user-interfaces)
7. [External Integrations](#external-integrations)
8. [Implementation Phases](#implementation-phases)
9. [Success Metrics](#success-metrics)
10. [Risks & Mitigations](#risks--mitigations)

---

## Vision & Goals

### Vision

Create a unified task orchestration system that understands developer intent, coordinates work across multiple repositories, and leverages AI to predict and prevent blockers before they happen.

### Primary Goals

1. **Natural Language Interface**: Create and manage tasks using plain English
2. **Ecosystem Coordination**: Seamlessly coordinate tasks across multiple repositories
3. **Predictive Insights**: Use AI to detect patterns, predict blockers, and optimize workflows
4. **Developer-Centric**: Designed for actual development workflows (worktrees, quality gates, git)
5. **One-Way Sync**: Import external issues without polluting GitHub/GitLab

### Non-Goals

- Bi-directional sync with GitHub/GitLab (one-way only, with approval)
- Enterprise project management (sprints, story points, burndown charts)
- Non-technical task tracking (marketing, sales, HR tasks)
- Replacing existing project management tools (complement, not replace)

---

## Ecosystem Integration

### Component Responsibilities

| Component | Role | Rationale |
|-----------|------|-----------|
| **Akosha** | Semantic search, pattern detection, dependency inference, knowledge graph | Already has vector DB + graph relationships |
| **Dhruva** | Task workflow configuration (ONEIRIC), component lifecycle management | Already handles ONEIRIC config + lifecycle |
| **Mahavishnu** | Task execution orchestration, cross-repo coordination, worktree integration | Already has worktree + quality gate orchestration |
| **Session-Buddy** | Task context, conversation history, session tracking | Already tracks sessions + memory |
| **Crackerjack** | Quality gate validation, test execution, code quality checks | Already has quality gate infrastructure |
| **SQLite/DuckDB** | Primary structured task storage (fast queries, ACID) | Performance + reliability for core data |

### Data Flow

```
User Input: "Create task to fix auth bug in session-buddy by Friday"

1. NLP Parser (Mahavishnu)
   ├─ Extract: repo=session-buddy, type=bug, priority=high, deadline=Friday
   └─ Parse: Acceptance criteria from natural language

2. Task Storage (Hybrid)
   ├─ SQLite: Store structured task data (primary)
   ├─ Akosha: Store embedding + relationships + patterns
   └─ Session-Buddy: Store creation context + conversation

3. Pattern Detection (Akosha)
   ├─ "Similar to task #123 (completed in 4h)"
   ├─ "Likely to block task #45"
   └─ "Tasks in auth scope take 2x longer than average"

4. Workflow Config (Dhruva)
   ├─ Load: tasks/bug-fix-workflow.yaml
   └─ Stages: setup → development → validation → completion

5. Orchestration (Mahavishnu)
   ├─ Create worktree: fix-auth-bug
   ├─ Open terminal/editor
   ├─ Run baseline tests
   └─ Track progress

6. Quality Gates (Crackerjack)
   ├─ Validate: Tests passing? (pytest)
   ├─ Validate: Quality score > 80? (ruff, complexity)
   ├─ Validate: No security issues? (bandit)
   └─ Allow completion only if all gates pass
```

---

## Architecture

### System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  User Interfaces                                                │
│  ├─ CLI (mhv task ...)                                          │
│  ├─ TUI (textual)                                              │
│  ├─ GUI (Electron)                                             │
│  └─ Web (FastAPI + React)                                       │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│  Task Orchestrator (Mahavishnu)                                 │
│  ├─ NLP Task Parser                                             │
│  ├─ Task Command Handler                                        │
│  ├─ Workflow Executor                                           │
│  └─ Quality Gate Coordinator                                    │
└────────────────┬────────────────────────────────────────────────┘
                 │
        ┌────────┴────────┐
        │                 │
        ▼                 ▼
┌──────────────┐  ┌──────────────────────────────────────┐
│  Storage     │  │  Ecosystem Components                │
│  Layer       │  │                                      │
│              │  │  ┌──────────┐  ┌──────────────┐      │
│  ┌────────┐  │  │  │ Akosha   │  │   Dhruva     │      │
│  │SQLite  │  │  │  │          │  │              │      │
│  │(Tasks) │  │  │  │ • Semantic│  │ • ONEIRIC   │      │
│  └────────┘  │  │  │   Search  │  │   Config    │      │
│              │  │  │ • Patterns│  │ • Lifecycle  │      │
│  ┌────────┐  │  │  │ • Graph   │  │              │      │
│  │Akosha │  │  │  └──────────┘  └──────────────┘      │
│  │(Graph) │  │  │                                      │
│  └────────┘  │  │  ┌──────────────┐  ┌──────────────┐ │
│              │  │  │Session-Buddy │  │  Crackerjack │ │
│  ┌────────┐  │  │  │              │  │              │ │
│  │Session │  │  │  │ • Context    │  │ • Quality    │ │
│  │Buddy  │  │  │  │ • History   │  │   Gates      │ │
│  │(Memory)│  │  │  │ • Sessions  │  │ • Testing    │ │
│  └────────┘  │  │  │              │  │              │ │
│              │  │  └──────────────┘  └──────────────┘ │
└──────────────┘  └──────────────────────────────────────┘
                 │
        ┌────────┴────────┐
        │                 │
        ▼                 ▼
┌──────────────┐  ┌─────────────────┐
│  External    │  │  Development    │
│  Systems     │  │  Tools         │
│              │  │                 │
│  ┌────────┐  │  │  ┌──────────┐  │
│  │GitHub  │  │  │  │ Worktree │  │
│  │Issues  │  │  │  │    Mgmt  │  │
│  │(One-   │  │  │  └──────────┘  │
│  │ way)   │  │  │                 │
│  └────────┘  │  │  ┌──────────┐  │
│              │  │  │Terminal  │  │
│  ┌────────┐  │  │  │Manager   │  │
│  │GitLab  │  │  │  └──────────┘  │
│  │Issues  │  │  │                 │
│  │(One-   │  │  │  ┌──────────┐  │
│  │way)    │  │  │  │   Git    │  │
│  └────────┘  │  │  │ Integration││
└──────────────┘  └─────────────────┘
```

### Component Details

#### 1. Task Orchestrator (Mahavishnu)

**Location**: `mahavishnu/core/task_orchestrator.py`

**Responsibilities**:
- NLP task parsing (extract repo, priority, deadline from natural language)
- Task CRUD operations
- Workflow execution (call Dhruva for config, execute stages)
- Cross-repo coordination (manage dependencies across repos)
- Worktree integration (create worktrees for tasks)
- Quality gate coordination (call Crackerjack for validation)

**Key Methods**:
```python
class TaskOrchestrator:
    async def create_task(self, description: str) -> Task:
        """Parse natural language, create task across all stores."""

    async def execute_task_workflow(self, task_id: str):
        """Load workflow from Dhruva, execute stages."""

    async def coordinate_multi_repo_task(self, tasks: list[RepoTask]):
        """Coordinate tasks across multiple repositories."""

    async def validate_task_completion(self, task_id: str) -> bool:
        """Run quality gates via Crackerjack."""
```

#### 2. Semantic Layer (Akosha)

**Integration Point**: Use existing Akosha knowledge graph

**Task-Specific Operations**:
```python
# Task as knowledge graph entity
task_entity = {
    "entity_type": "task",
    "id": "task-42",
    "properties": {
        "title": "Fix auth bug",
        "status": "in_progress",
        "priority": "high",
        "repository": "session-buddy",
    },
    "embedding": generate_embedding(title + description),  # Semantic search
    "relationships": [
        {"type": "blocks", "target": "task-43"},
        {"type": "related_to", "target": "github-issue-123"},
        {"type": "in_repo", "target": "session-buddy"},
        {"type": "requires_completion_of", "target": "task-41"},
    ]
}

# Semantic search
similar_tasks = await akosha.semantic_search(
    entity_type="task",
    query="authentication bug",
    threshold=0.8,
)

# Pattern detection
patterns = await akosha.detect_patterns([
    "Tasks in auth scope take 2x longer",
    "Tasks created Friday have 40% abandonment",
])

# Dependency inference
inferred_deps = await akosha.infer_relationships(
    entity_type="task",
    entity_id="task-42",
    reasoning="Both touch same files, similar to historical pairs",
)
```

#### 3. Configuration Layer (Dhruva)

**Integration Point**: Use ONEIRIC configuration for task workflows

**Task Workflow Config** (`tasks/task-42.yaml`):
```yaml
component:
  type: task
  name: fix-auth-bug
  version: 1.0

providers:
  worktree:
    type: mahavishnu
    config:
      repo: session-buddy
      branch: fix-auth-bug

  quality:
    type: crackerjack
    config:
      min_score: 80
      checks: [test, lint, security]

workflow:
  stages:
    - name: setup
      provider: worktree
      action: create

    - name: development
      provider: terminal
      action: open_editor

    - name: validation
      provider: quality
      action: run_gates

    - name: completion
      provider: git
      action: create_pr
```

**Lifecycle Management**:
```python
# Activate task with workflow
await dhruva.activate_component(
    component_type="task",
    component_id="task-42",
    config_path="tasks/task-42.yaml",
)

# Execute specific stage
await dhruva.resolve_and_execute(
    component="task-42",
    stage="validation",
    context={"repo": "session-buddy"},
)

# Swap workflow approach mid-execution
await dhruva.swap_component(
    component_id="task-42",
    new_config="tasks/task-42-alternative.yaml",
    reason="Trying different approach",
)
```

#### 4. Storage Layer (Hybrid)

**Primary Storage**: SQLite/DuckDB (structured data, fast queries)

**Schema**:
```sql
-- Tasks table
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'in_progress', 'blocked', 'completed', 'cancelled')),
    priority TEXT NOT NULL CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    repository TEXT NOT NULL,
    deadline TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    created_by TEXT,

    -- External sync tracking
    source TEXT CHECK (source IN ('manual', 'github', 'gitlab')),
    source_id TEXT,  -- GitHub/GitLab issue ID
    github_issue_id INTEGER,
    github_synced BOOLEAN DEFAULT FALSE,

    -- Worktree tracking
    worktree_path TEXT,
    worktree_branch TEXT,

    -- Quality gates
    quality_status TEXT CHECK (quality_status IN ('pending', 'passed', 'failed')),
    quality_score INTEGER,

    -- Metadata
    metadata JSON,  -- Flexible metadata storage
);

-- Dependencies table
CREATE TABLE task_dependencies (
    dependent_task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
    blocks_task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
    dependency_type TEXT CHECK (dependency_type IN ('blocks', 'relates_to', 'suggests')),
    inferred BOOLEAN DEFAULT FALSE,  -- True if inferred by Akosha
    confidence REAL,  -- 0.0-1.0 for inferred dependencies
    PRIMARY KEY (dependent_task_id, blocks_task_id)
);

-- Full-text search
CREATE VIRTUAL TABLE tasks_fts USING fts5(
    title,
    description,
    content=tasks,
    content_rowid=rowid
);

-- Triggers to keep FTS in sync
CREATE TRIGGER tasks_fts_insert AFTER INSERT ON tasks BEGIN
    INSERT INTO tasks_fts(rowid, title, description)
    VALUES (new.rowid, new.title, new.description);
END;

CREATE TRIGGER tasks_fts_delete AFTER DELETE ON tasks BEGIN
    DELETE FROM tasks_fts WHERE rowid = old.rowid;
END;

CREATE TRIGGER tasks_fts_update AFTER UPDATE ON tasks BEGIN
    DELETE FROM tasks_fts WHERE rowid = old.rowid;
    INSERT INTO tasks_fts(rowid, title, description)
    VALUES (new.rowid, new.title, new.description);
END;

-- Embeddings table (for vector similarity search - optional DuckDB extension)
CREATE TABLE task_embeddings (
    task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    embedding FLOAT[768],  -- Size depends on model (e.g., sentence-transformers)
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_priority ON tasks(priority);
CREATE INDEX idx_tasks_repository ON tasks(repository);
CREATE INDEX idx_tasks_deadline ON tasks(deadline);
CREATE INDEX idx_tasks_source ON tasks(source, source_id);
CREATE INDEX idx_dependencies_dependent ON task_dependencies(dependent_task_id);
CREATE INDEX idx_dependencies_blocks ON task_dependencies(blocks_task_id);
```

**Secondary Storage**: Akosha Knowledge Graph (embeddings, relationships, patterns)

**Tertiary Storage**: Session-Buddy Memory (conversation history, context)

---

## Core Features

### 1. Natural Language Task Creation

**User Experience**:
```bash
mhv task add "Fix authentication bug in session-buddy by Friday, high priority"
```

**System Processing**:
```python
# 1. NLP Parser extracts:
{
    "action": "fix",
    "type": "bug",  # inferred from "bug"
    "scope": "authentication",
    "repository": "session-buddy",
    "deadline": "this Friday",  # parsed to date
    "priority": "high",
}

# 2. Repository validation
repo = repo_manager.get_by_name("session-buddy")
if not repo:
    return {"error": "Repository not found"}

# 3. Create task
task = await task_orchestrator.create_task(
    title="Fix authentication bug",
    repository="session-buddy",
    priority="high",
    deadline=parse_date("this Friday"),
    type="bug",
)

# 4. Akosha: Semantic search for similar tasks
similar = await akosha.semantic_search(
    query="authentication bug session-buddy",
    threshold=0.8,
)
if similar:
    print(f"⚠️  Note: You have {len(similar)} similar tasks:")
    for s in similar:
        print(f"   - {s['title']} ({s['status']})")

# 5. Akosha: Pattern detection
patterns = await akosha.detect_task_patterns(task)
if patterns:
    print(f"🔮 Predictions:")
    for p in patterns:
        print(f"   - {p['pattern']} ({p['confidence']}% confidence)")

# 6. Akosha: Infer dependencies
deps = await akosha.infer_task_dependencies(task)
if deps:
    print(f"🔗 Suggested dependencies:")
    for d in deps:
        print(f"   - Blocks: {d['blocks_task']} ({d['confidence']}% confidence)")
        confirm = input(f"Add dependency? [y/N] ")
        if confirm.lower() == 'y':
            await task_orchestrator.add_dependency(
                dependent_task=task.id,
                blocks_task=d['blocks_task'],
            )
```

**Supported Natural Language Patterns**:
- Time: "by Friday", "in 2 days", "tomorrow", "next week"
- Priority: "high priority", "urgent", "critical", "ASAP"
- Task type: "bug", "feature", "refactor", "test", "docs"
- Repository: "in session-buddy", "for mahavishnu", "in the API repo"
- Dependencies: "blocking task #5", "depends on X", "after Y is done"

### 2. Semantic Task Search

**User Experience**:
```bash
mhv task find "all authentication issues that are blocking frontend work"
```

**System Processing**:
```python
# Akosha: Semantic search across all tasks
results = await akosha.semantic_search(
    entity_type="task",
    query="authentication issues blocking frontend",
    threshold=0.7,
    filters={
        "status": ["in_progress", "pending"],
        "repository": ["session-buddy", "mahavishnu"],
    },
)

# Returns semantically similar tasks, even without exact keyword matches
for task in results:
    print(f"Task #{task['id']}: {task['title']}")
    print(f"  Similarity: {task['similarity']:.2%}")
    print(f"  Repository: {task['repository']}")
    print(f"  Status: {task['status']}")
```

**Why Semantic Search Matters**:
- Finds tasks without exact keyword matches
- Understands intent ("auth issues" ≈ "authentication problems" ≈ "login bugs")
- Discovers hidden relationships (tasks that block each other indirectly)
- Multimodal search (search by title, description, comments, code changes)

### 3. Cross-Repo Dependency Management

**User Experience**:
```bash
mhv task add "Update API in backend-api, then update frontend and docs"
```

**System Processing**:
```python
# NLP Parser detects multi-repo task
subtasks = [
    {"repo": "backend-api", "task": "Update API"},
    {"repo": "frontend", "task": "Update client", "depends_on": "backend-api"},
    {"repo": "docs", "task": "Update docs", "depends_on": "frontend"},
]

# Create tasks with dependencies
for i, subtask in enumerate(subtasks):
    task = await task_orchestrator.create_task(**subtask)

    # Add dependency if not first task
    if i > 0:
        await task_orchestrator.add_dependency(
            dependent_task=task.id,
            blocks_task=subtasks[i-1]["task_id"],
        )

    print(f"✅ Created task #{task.id}: {task['title']}")
    print(f"   Repository: {task['repository']}")
    if task.get("dependencies"):
        print(f"   Dependencies: {task['dependencies']}")

# Visualization
print("\n📊 Task Dependency Graph:")
await task_orchestrator.print_dependency_graph(task_ids=[t.id for t in tasks])
# Output:
# backend-api#1 → frontend#2 → docs#3
```

**Dependency Management Features**:
- **Explicit**: User specifies "after X is done"
- **Implicit**: Akosha infers from historical patterns
- **Validation**: Prevents circular dependencies
- **Visualization**: ASCII/mermaid graphs of dependency chains
- **Blocker Detection**: Alert when a task has >3 blocking tasks

### 4. Worktree Integration

**User Experience**:
```bash
mhv task start 42
```

**System Processing**:
```python
# 1. Get task details
task = await task_store.get(task_id=42)

# 2. Create worktree (using existing worktree coordinator)
worktree_result = await worktree_coordinator.create_worktree(
    repo_nickname=task["repository"],
    branch=f"task-{task_id}-{task['title'].slugify()}",
    reason=f"Task #{task_id}: {task['title']}",
)

# 3. Open terminal (using existing terminal manager)
terminal_session = await terminal_manager.launch_iterm2(
    working_directory=worktree_result["worktree_path"],
    title=f"Task #{task_id}: {task['title']}",
    profile_name=f"task-{task_id}",
)

# 4. Run baseline tests (show current state)
test_result = await crackerjack.run_tests(
    worktree_path=worktree_result["worktree_path"],
)

# 5. Update task with worktree info
await task_store.update(task_id, {
    "status": "in_progress",
    "worktree_path": worktree_result["worktree_path"],
    "worktree_branch": worktree_result["branch"],
    "terminal_session_id": terminal_session,
})

# 6. Open editor (optional)
if user_prefs.get("auto_open_editor"):
    await editor_manager.open(
        path=worktree_result["worktree_path"],
        type=user_prefs.get("editor", "nvim"),
    )

print(f"✅ Started task #{task_id}")
print(f"   Worktree: {worktree_result['worktree_path']}")
print(f"   Terminal: {terminal_session}")
print(f"   Baseline tests: {test_result['passed']}/{test_result['total']} passing")
```

**Worktree Management**:
- Automatic creation when task starts
- Automatic cleanup when task completes
- Worktree命名: `task-{id}-{slug(title)}`
- Integration with existing worktree safety mechanisms
- Track worktree → task mapping in SQLite

### 5. Quality Gate Integration

**User Experience**:
```bash
mhv task complete 42
```

**System Processing**:
```python
# 1. Get task details
task = await task_store.get(task_id=42)

# 2. Check uncommitted changes (using existing worktree coordinator)
has_uncommitted = await worktree_coordinator._check_uncommitted_changes(
    task["worktree_path"]
)

if has_uncommitted:
    print("⚠️  Worktree has uncommitted changes")
    confirm = input("Commit before completing? [y/N] ")
    if confirm.lower() == 'y':
        # Run git commit workflow
        await git_workflow.commit_and_push(
            worktree_path=task["worktree_path"],
            message=f"Complete task #{task_id}: {task['title']}",
        )

# 3. Run quality gates (via Crackerjack)
gates = await crackerjack.run_quality_gates(
    worktree_path=task["worktree_path"],
    gates={
        "test": {"min_pass_rate": 1.0},  # 100% tests passing
        "quality": {"min_score": 80},  # Ruff quality score
        "security": {"max_issues": 0},  # No security issues
    }
)

# 4. Check gate results
all_passed = all(gate["passed"] for gate in gates.values())

if not all_passed:
    print("❌ Quality gates failed:")
    for gate_name, gate_result in gates.items():
        if not gate_result["passed"]:
            print(f"   {gate_name}: {gate_result['reason']}")

    # Ask if user wants to complete anyway
    confirm = input("Complete anyway? [y/N] ")
    if confirm.lower() != 'y':
        return {"success": False, "error": "Quality gates failed"}

# 5. Mark task as completed
await task_store.update(task_id, {
    "status": "completed",
    "completed_at": datetime.now(UTC),
    "quality_status": "passed",
    "quality_score": gates["quality"]["score"],
})

# 6. Clean up worktree (optional, ask user)
confirm = input("Clean up worktree? [Y/n] ")
if confirm.lower() != 'n':
    # Prune worktree
    await worktree_coordinator.remove_worktree(
        repo_nickname=task["repository"],
        worktree_path=task["worktree_path"],
    )
    await task_store.update(task_id, {"worktree_path": None})

print(f"✅ Completed task #{task_id}")
```

**Quality Gates**:
- Tests: 100% pass rate (pytest)
- Coverage: Minimum 80% (pytest-cov)
- Quality: Score ≥80 (Ruff)
- Security: 0 issues (Bandit)
- Type Safety: No errors (mypy)
- Documentation: All public functions documented

### 6. Predictive Insights (Akosha)

**User Experience**:
```bash
mhv task insights 42
```

**System Processing**:
```python
# Akosha: Analyze task and provide predictions
insights = await akosha.generate_task_insights(task_id=42)

print(f"🔮 Insights for Task #{task_id}:")
print()

# Prediction 1: Completion time
if insights["predicted_duration"]:
    print(f"⏱️  Predicted duration: {insights['predicted_duration']['hours']} hours")
    print(f"    Confidence: {insights['predicted_duration']['confidence']}%")
    print(f"    Reason: {insights['predicted_duration']['reason']}")
    print()

# Prediction 2: Likely blockers
if insights["predicted_blockers"]:
    print(f"⚠️  Potential blockers:")
    for blocker in insights["predicted_blockers"]:
        print(f"   - {blocker['task_title']} (#{blocker['task_id']})")
        print(f"     Confidence: {blocker['confidence']}%")
        print(f"     Reason: {blocker['reason']}")
    print()

# Prediction 3: Similar historical tasks
if insights["similar_tasks"]:
    print(f"📊 Similar tasks:")
    for similar in insights["similar_tasks"]:
        print(f"   - #{similar['id']}: {similar['title']}")
        print(f"     Status: {similar['status']}")
        print(f"     Duration: {similar['duration_hours']}h")
        print(f"     Similarity: {similar['similarity']}%")
    print()

# Prediction 4: Success probability
if insights["success_probability"]:
    print(f"📈 Success probability: {insights['success_probability']}%")
    print(f"    Factors:")
    for factor in insights["success_factors"]:
        print(f"      - {factor['name']}: {factor['impact']}")
```

**Insight Types**:
- **Duration Prediction**: Based on similar historical tasks
- **Blocker Detection**: Tasks likely to block this one
- **Success Probability**: Likelihood of on-time completion
- **Risk Factors**: Specific concerns (complexity, dependencies, developer availability)
- **Suggestions**: Optimization opportunities (split task, get help, etc.)

---

## Storage Strategy

### Hybrid Storage Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Task Storage (Hybrid)                                     │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │   SQLite     │  │   Akosha     │  │ Session-     │    │
│  │   (Primary)  │  │   (Semantic) │  │ Buddy        │    │
│  │              │  │              │  │ (Context)    │    │
│  │ • Tasks      │  │ • Entities   │  │              │    │
│  │ • Deps       │  │ • Embeddings │  │ • Memories   │    │
│  │ • FTS        │  │ • Graph      │  │ • Chats      │    │
│  │ • Metadata   │  │ • Patterns   │  │ • History    │    │
│  └──────────────┘  └──────────────┘  └──────────────┘    │
│                                                             │
│  Query Router:                                              │
│  • Structured queries → SQLite                             │
│  • Semantic search → Akosha                                 │
│  • Context/history → Session-Buddy                          │
│  • Hybrid queries → All 3                                   │
└─────────────────────────────────────────────────────────────┘
```

### Data Distribution

**SQLite (Structured Data)**:
- Task core data (id, title, status, priority, etc.)
- Dependencies
- External sync tracking (GitHub/GitLab IDs)
- Worktree tracking
- Quality gate results
- Full-text search index

**Akosha (Semantic + Graph)**:
- Task entity with embedding vector
- Relationships (blocks, relates_to, suggests)
- Pattern detection results
- Similar task recommendations
- Dependency inference results

**Session-Buddy (Context)**:
- Task creation conversation
- Progress updates history
- Developer notes/discussions
- Decision rationale
- Session tracking (who worked on what)

### Sync Strategy

```python
class HybridTaskStore:
    """
    Coordinate writes across all 3 storage systems.
    """

    async def create_task(self, task: Task) -> Task:
        """
        Create task across all stores (transactional).
        """
        # 1. Primary: SQLite (with rollback on failure)
        try:
            task_id = await self.sqlite.insert(task)
        except Exception as e:
            logger.error(f"Failed to insert task into SQLite: {e}")
            raise

        # 2. Semantic: Akosha (best-effort, non-blocking)
        try:
            await self.akosha.create_entity({
                "entity_type": "task",
                "id": task_id,
                "properties": task.model_dump(),
                "embedding": generate_embedding(task.title + task.description),
                "relationships": [],  # Will be added later
            })
        except Exception as e:
            logger.warning(f"Failed to index task in Akosha: {e}")
            # Don't fail - task still exists in SQLite

        # 3. Context: Session-Buddy (best-effort, non-blocking)
        try:
            await self.session_buddy.store_memory(
                session_id=f"task-{task_id}",
                content=f"Created task: {task.title}",
                metadata=task.model_dump(),
            )
        except Exception as e:
            logger.warning(f"Failed to store task context: {e}")

        return task

    async def search_tasks(self, query: str, method: str = "semantic") -> list[Task]:
        """
        Search using appropriate method.
        """
        if method == "semantic":
            # Use Akosha for semantic search
            results = await self.akosha.semantic_search(
                entity_type="task",
                query=query,
                threshold=0.7,
            )
            # Hydrate from SQLite
            return [await self.sqlite.get_by_id(r["id"]) for r in results]

        elif method == "fulltext":
            # Use SQLite full-text search
            return await self.sqlite.fulltext_search(query)

        elif method == "hybrid":
            # Combine both (semantic + fulltext)
            semantic_results = await self.akosha.semantic_search(query, threshold=0.6)
            fts_results = await self.sqlite.fulltext_search(query)

            # Merge and deduplicate
            all_ids = set([r["id"] for r in semantic_results] + [r["id"] for r in fts_results])
            return [await self.sqlite.get_by_id(id) for id in all_ids]

    async def get_task_context(self, task_id: str) -> list[Memory]:
        """
        Get task conversation/history from Session-Buddy.
        """
        return await self.session_buddy.get_session(f"task-{task_id}")
```

### Backup & Recovery

**SQLite**:
- Regular backups: `sqlite3 tasks.db .backup > backup_$(date +%Y%m%d).db`
- Point-in-time recovery: WAL mode
- Easy restore: Copy database file

**Akosha**:
- Knowledge graph exports: GraphML, JSON
- Embeddings backup: Vector export
- Relationship backup: Adjacency list export

**Session-Buddy**:
- Session exports: JSON per session
- Memory dumps: Full memory snapshot
- Easy restore: Import sessions

---

## User Interfaces

### 1. CLI (Command Line Interface)

**Framework**: Typer (already used in Mahavishnu)

**Commands**:
```bash
# Task creation
mhv task add "Fix auth bug in session-buddy by Friday"
mhv task add "Update API in backend-api, then update frontend and docs"

# Task listing
mhv task list
mhv task list --status pending
mhv task list --repo session-buddy
mhv task list --priority high,critical

# Task search
mhv task find "authentication issues"
mhv task find "blocking frontend" --repo mahavishnu

# Task details
mhv task show 42
mhv task insights 42  # Predictive insights from Akosha

# Task lifecycle
mhv task start 42     # Create worktree, open terminal
mhv task complete 42  # Run quality gates, mark complete
mhv task cancel 42    # Cancel task

# Task dependencies
mhv task depend 42 --blocks 45
mhv task depend 42 --unblocks 43
mhv task graph 42     # Show dependency graph

# External sync
mhv task approvals    # Show pending GitHub/GitLab approvals
mhv task approve 42   # Approve external issue → task
mhv task reject 42 --reason "Duplicate"
mhv task push 42 --to-github  # Push task to GitHub (exceptional)

# Task management
mhv task edit 42 --priority high
mhv task delete 42
mhv task archive --completed  # Archive completed tasks

# Task analytics
mhv task stats        # Overall statistics
mhv task report       # Generate report
```

**Examples**:
```bash
# Create task
$ mhv task add "Fix authentication bug in session-buddy by Friday, high priority"
✅ Created task #42: Fix authentication bug
   Repository: session-buddy
   Priority: HIGH
   Deadline: 2025-02-21
   ⚠️  Note: 3 similar tasks found
   🔮 Predicted duration: 4 hours (87% confidence)
   🔗 Suggested dependency: Blocks task #45 (Update frontend)

# List tasks
$ mhv task list --repo session-buddy --status pending
📋 Pending Tasks in session-buddy (3):
  #42  🔴 Fix authentication bug          (HIGH)    Due: Fri
  #43  🟡 Update JWT library              (MEDIUM)  Due: Mon
  #44  🟢 Add auth tests                   (LOW)    Due: Next week

# Start task
$ mhv task start 42
✅ Starting task #42: Fix authentication bug
   Creating worktree: ~/worktrees/session-buddy/task-42-fix-auth-bug
   Opening terminal: session-abc123
   Running baseline tests: 15/18 passing
   Worktree is ready: cd ~/worktrees/session-buddy/task-42-fix-auth-bug

# Complete task
$ mhv task complete 42
✅ Running quality gates...
   Tests: 18/18 passing ✅
   Coverage: 85% ✅
   Quality: 82/100 ✅
   Security: 0 issues ✅
   All gates passed! ✅
✅ Completed task #42: Fix authentication bug
   Duration: 3.5 hours
   Clean up worktree? [Y/n] Y
   ✅ Worktree removed
```

### 2. TUI (Terminal User Interface)

**Framework**: Textual (modern async TUI)

**Features**:
- Keyboard-driven (vim-style navigation)
- Real-time updates (WebSocket integration)
- Rich text (syntax highlighting, emoji status)
- Split panels (task list + details + activity)
- Visual mode (bulk actions)

**Screen Layout**:
```
┌────────────────────────────────────────────────────────────────┐
│  Mahavishnu Task Manager                          [All Tasks ▼]│
│                                                                  │
│  ┌────────────────────┐  ┌────────────────────────────────────┐│
│  │ 📋 Task List (23)  │  │ 🔍 Task Details                     ││
│  │                    │  │                                    ││
│  │ [ACTIVE]           │  │ Task #42: Fix auth bug              ││
│  │ ▶ Fix auth bug     │  │                                    ││
│  │   ⏱  2h elapsed   │  │ Repository: session-buddy           ││
│  │   ⚠  1 blocker    │  │ Priority: HIGH 🔴                   ││
│  │                    │  │ Deadline: 2025-02-21 (3 days)      ││
│  │ [BLOCKED]          │  │                                    ││
│  │ ◼ Update API       │  │ Description:                        ││
│  │   ⛔  blocked by   │  │ JWT validation fails when token...  ││
│  │   ⏸  3 days idle  │  │                                    ││
│  │                    │  │ Dependencies:                       ││
│  │ [QUEUED]           │  │ ✅ #40: Update JWT lib (complete)   ││
│  │ ⏸ Add tests       │  │ ⏳ #41: Fix tests (in progress)     ││
│  │   ✓ no blockers    │  │                                    ││
│  │                    │  │ Quality Gates:                      ││
│  │                    │  │ ⏳ Tests: 15/18 passing              ││
│  │                    │  │ ❌ Coverage: 62% (needs 80%)       ││
│  └────────────────────┘  │ ⚠️  Security: 1 issue found        ││
│                          │                                    ││
│  ┌────────────────────────┴──────────────────────────────────┐│
│  │ Dhruva Insights ⚡                                           ││
│  │ 🔮 Predicted: 4h remaining (87% confidence)                  ││
│  │ ⚠️  Warning: Blocks task #45 (Update frontend)             ││
│  │ 💡 Suggestion: Consider splitting into 2 subtasks          ││
│  └────────────────────────────────────────────────────────────┘│
│                                                                  │
│  [n] New  [s] Start  [c] Complete  [d] Delete  [q] Quit          │
└──────────────────────────────────────────────────────────────────┘
```

**Key Bindings**:
```vim
# Navigation
j/k     : Up/down
Enter   : View task details
/       : Search
f       : Filter (by repo, status, priority)
v       : Visual mode (bulk actions)

# Actions
s       : Start task (create worktree, open terminal)
c       : Complete task (run quality gates)
d       : Delete task
e       : Edit task
n       : Create new task
q       : Quit

# Visual mode
V       : Enter visual mode
j/k     : Select tasks
d       : Delete selected
c       : Complete selected
```

### 3. GUI (Native Desktop)

**Framework**: Electron + React + TypeScript

**Features**:
- Drag-and-drop task reordering
- Kanban board view
- Real-time sync (WebSocket)
- Native notifications
- Menu bar integration (macOS)
- Keyboard shortcuts (⌘N, ⌘Enter, ⌘K)

**Screen Layout**:
```
┌──────────────────────────────────────────────────────────────────┐
│  Mahavishnu Tasks                                   🔍 Filter... │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  📊 Dashboard                                        New Task +   │
│  ┌────────────┬────────────┬────────────┬────────────┐          │
│  │ 23 Active  │ 12 Blocked  │ 5 Overdue  │ 156 Total  │          │
│  └────────────┴────────────┴────────────┴────────────┘          │
│                                                                   │
│  🔥 High Priority                                                │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │ 🔴 Fix auth bug in session-buddy              [2h] ⚠️     │     │
│  │    Blocked by: Update JWT library                        │     │
│  │    [Start] [Complete] [Details]                           │     │
│  └─────────────────────────────────────────────────────────┘     │
│                                                                   │
│  📋 All Tasks                                                    │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │ 🟢 Update API in backend-api                [Today]     │     │
│  │ 🟡 Add tests for pool manager               [Tomorrow]  │     │
│  │ 🟢 Fix memory leak                          [This week] │     │
│  │ 🔴 Update documentation                     [Overdue]   │     │
│  └─────────────────────────────────────────────────────────┘     │
│                                                                   │
│  📈 Analytics                                                    │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │ Task Completion Rate: ▄▃▅▆▇█ 85%                        │     │
│  │ Avg Cycle Time: 2.3 days                                │     │
│  │ Most Blocked Repo: session-buddy (7 tasks)              │     │
│  └─────────────────────────────────────────────────────────┘     │
└───────────────────────────────────────────────────────────────────┘
```

**Menu Bar Integration** (macOS):
```
Click menu bar icon:
┌─────────────────────────────┐
│  Mahavishnu Tasks           │
│  ─────────────────────────  │
│  🔴 Fix auth bug    [Start] │
│  🟡 Update API      [Start] │
│  🟢 Add tests       [Start] │
│  ─────────────────────────  │
│  Open Task Manager...       │
│  Create New Task...         │
│  Settings                   │
│  Quit                       │
└─────────────────────────────┘
```

**Keyboard Shortcuts**:
- `⌘N` - New task
- `⌘O` - Open task manager
- `⌘⇧C` - Complete selected task(s)
- `⌘⇧S` - Start selected task(s)
- `⌘F` - Search tasks
- `⌘,` - Open preferences

### 4. Web UI

**Framework**: FastAPI + React + Next.js

**Features**:
- Mobile-responsive design
- Real-time collaboration
- Rich dashboard with analytics
- RESTful API for integrations
- Webhook support (GitHub/GitLab)

**Screen Layout**:
```
┌─────────────────────────────────────────────────────────────────┐
│  Mahavishnu Task Portal                            @les  [⚙]   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  [Tasks] [Analytics] [Settings]                                  │
│                                                                 │
│  Quick Add Task                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 📝 "Fix auth bug in session-buddy by Friday"           │    │
│  │                                              [Add] [AI] │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  Active Tasks (23)                                              │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Filter: [All repos ▼] [All statuses ▼] [All priorities▼]│    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 🔴 Fix auth bug                           High  2h     │    │
│  │    session-buddy  •  Started 2h ago  • 1 blocker       │    │
│  │    [Start Worktree] [Complete] [Details]                │    │
│  ├─────────────────────────────────────────────────────────┤    │
│  │ 🟡 Update API                            Med   Today   │    │
│  │    backend-api  •  Due today  •  No blockers           │    │
│  │    [Start Worktree] [Complete] [Details]                │    │
│  ├─────────────────────────────────────────────────────────┤    │
│  │ 🟢 Add tests                            Low   Tomorrow│    │
│  │    mahavishnu  •  Due tomorrow  •  No blockers         │    │
│  │    [Start Worktree] [Complete] [Details]                │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  Dhruva Insights ⚡                                             │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 🔮 Predicted: "Fix auth bug" will take 4h (2h remaining) │    │
│  │ ⚠️  Warning: "Update API" blocked by missing dependency │    │
│  │ 💡 Suggestion: Combine "Add tests" with "Fix coverage"   │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

**Mobile View**:
```
┌─────────────────────────────┐
│  ☰  Tasks             @les  │
├─────────────────────────────┤
│                             │
│  [+ New Task]               │
│                             │
│  🔴 Fix auth bug            │
│     session-buddy  • 2h    │
│     [Start] [Complete]      │
│                             │
│  🟡 Update API              │
│     backend-api  • Today   │
│     [Start] [Complete]      │
│                             │
│  🟢 Add tests               │
│     mahavishnu  • Tomorrow │
│     [Start] [Complete]      │
│                             │
│  [Load More...]             │
└─────────────────────────────┘
```

**API Endpoints**:
```python
# REST API
GET    /api/tasks              # List tasks
POST   /api/tasks              # Create task
GET    /api/tasks/{id}         # Get task
PUT    /api/tasks/{id}         # Update task
DELETE /api/tasks/{id}         # Delete task
POST   /api/tasks/{id}/start   # Start task
POST   /api/tasks/{id}/complete # Complete task

# Search
GET    /api/tasks/search?q={query}  # Full-text search
POST   /api/tasks/semantic         # Semantic search (Akosha)

# Analytics
GET    /api/analytics/stats        # Overall statistics
GET    /api/analytics/predictions  # Dhruva insights

# External sync
GET    /api/sync/approvals        # Pending approvals
POST   /api/sync/approve/{id}     # Approve proposal
POST   /api/sync/reject/{id}      # Reject proposal

# WebSocket
WS     /ws/tasks               # Real-time task updates
WS     /ws/analytics           # Real-time analytics
```

---

## External Integrations

### One-Way Sync: GitHub/GitLab → Mahavishnu

**Design Decision**: One-way sync with approval workflow

**Rationale**:
- Mahavishnu is the source of truth
- No GitHub issue pollution with internal tasks
- Can track external issues without creating duplicates
- Approval workflow prevents spam
- Selective pushback (only high-value tasks)

### Architecture

```
GitHub/GitLab Webhook → Mahavishnu API → Approval Queue → Task Creation
```

**Implementation**:

```python
class OneWaySyncHandler:
    """
    Handle one-way sync from GitHub/GitLab to Mahavishnu.
    """

    async def on_github_issue_created(self, issue: GitHubIssue) -> None:
        """
        Called when GitHub issue is created (webhook).
        Does NOT automatically create task - requires approval.
        """
        # Create pending task proposal
        proposal = TaskProposal(
            source="github",
            source_id=issue.id,
            title=issue.title,
            description=issue.body,
            labels=issue.labels,
            assignee=issue.assignee,
            status="pending_approval",
            created_at=datetime.now(UTC),
        )

        # Store in approval queue (SQLite)
        await self.approval_queue.enqueue(proposal)

        # Notify user (via WebSocket to all connected UIs)
        await self.notification_service.broadcast(
            event_type="task_proposal",
            data={
                "message": f"📥 New GitHub issue pending approval: {issue.title}",
                "proposal": proposal.model_dump(),
            }
        )

    async def approve_task_proposal(self, proposal_id: str) -> Task:
        """
        User approves - convert proposal to real task.
        """
        proposal = await self.approval_queue.get(proposal_id)

        if not proposal:
            raise ValueError(f"Proposal {proposal_id} not found")

        # Parse repository from issue (if available)
        repo = self._extract_repo_from_issue(proposal)

        # Create the actual task
        task = await self.task_orchestrator.create_task(
            title=proposal.title,
            description=proposal.description,
            repository=repo,
            source="github",
            source_id=proposal.source_id,
            metadata={
                "github_url": proposal.url,
                "github_labels": proposal.labels,
                "github_number": proposal.source_id,
            }
        )

        # Mark proposal as approved
        proposal.status = "approved"
        proposal.task_id = task.id
        proposal.approved_at = datetime.now(UTC)
        await self.approval_queue.update(proposal)

        # Optional: Add comment to GitHub issue
        await self.github_client.add_comment(
            repo=repo,
            issue_number=proposal.source_id,
            body=f"This issue is being tracked internally as task #{task.id}",
        )

        return task

    async def reject_task_proposal(self, proposal_id: str, reason: str) -> None:
        """
        User rejects - don't create task.
        """
        proposal = await self.approval_queue.get(proposal_id)

        if not proposal:
            raise ValueError(f"Proposal {proposal_id} not found")

        proposal.status = "rejected"
        proposal.rejection_reason = reason
        proposal.rejected_at = datetime.now(UTC)
        await self.approval_queue.update(proposal)

        # Optional: Add comment to GitHub issue
        await self.github_client.add_comment(
            repo=proposal.repository,
            issue_number=proposal.source_id,
            body=f"This issue was reviewed internally but not accepted. Reason: {reason}",
        )

    async def push_to_github(self, task_id: str) -> GitHubIssue:
        """
        EXCEPTIONAL: Push Mahavishnu task to GitHub (manual, opt-in).
        Only for high-value tasks that need public visibility.
        """
        task = await self.task_store.get(task_id)

        if not task:
            raise ValueError(f"Task {task_id} not found")

        # Require explicit user confirmation
        if not task.should_push_to_github():
            raise PermissionError(
                "Task not marked for GitHub sync. "
                "Mark with --github flag or set metadata.github_sync=true"
            )

        # Create GitHub issue
        gh_issue = await self.github_client.create_issue(
            repo=task["repository"],
            title=task["title"],
            body=self._format_task_description(task),
            labels=self._map_priority_to_labels(task["priority"]),
        )

        # Link task to GitHub issue
        await self.task_store.update(task_id, {
            "github_issue_id": gh_issue.id,
            "github_issue_url": gh_issue.url,
            "github_synced": True,
        })

        # Store in Akosha (relationship)
        await self.akosha.create_relationship(
            from_entity="task",
            from_id=task_id,
            to_entity="github_issue",
            to_id=str(gh_issue.id),
            relationship_type="synced_to",
        )

        return gh_issue

    def _format_task_description(self, task: Task) -> str:
        """
        Format task for GitHub issue description.
        """
        return f"""
# {task['title']}

**Status**: {task['status']}
**Priority**: {task['priority']}
**Repository**: {task['repository']}

## Description
{task.get('description', 'No description')}

## Acceptance Criteria
{self._format_acceptance_criteria(task)}

## Progress
- **Created**: {task['created_at']}
- **Started**: {task.get('started_at', 'Not started')}
- **Completed**: {task.get('completed_at', 'In progress')}

## Quality Gates
- **Tests**: {task.get('test_pass_rate', 'N/A')}
- **Coverage**: {task.get('coverage', 'N/A')}
- **Quality Score**: {task.get('quality_score', 'N/A')}

---
_Tracked by Mahavishnu Task Orchestrator_
_Task ID: {task['id']}_
""".strip()
```

**CLI Interface**:
```bash
# View pending approvals
$ mhv task approvals
ID  | Source | Title                          | Created
----|--------|--------------------------------|----------
42  | GitHub | Fix auth bug in session-buddy  | 2m ago
43  | GitLab | Update API in backend-api      | 1h ago

# Approve (creates task)
$ mhv task approve 42
✅ Created task #123: "Fix auth bug in session-buddy"
   Repository: session-buddy
   Source: GitHub issue #42
   🔗 Linked: https://github.com/user/repo/issues/42

# Reject (doesn't create task)
$ mhv task reject 42 --reason "Duplicate, already tracking as task #100"
❌ Rejected proposal #42
   Reason: Duplicate, already tracking as task #100
   Comment added to GitHub issue

# Exceptional push to GitHub (manual, opt-in)
$ mhv task push 123 --to-github
⚠️  This will create a public GitHub issue. Continue? [y/N] y
✅ Created GitHub issue #45
   URL: https://github.com/user/repo/issues/45
   Task #123 linked to issue

# Mark task for GitHub sync (create time)
$ mhv task add "Public-facing feature" --github
✅ Created task #124: "Public-facing feature"
   Marked for GitHub sync (create GitHub issue when ready)
```

**Webhook Configuration**:

GitHub:
```yaml
# GitHub webhook settings
URL: https://mahavishnu.example.com/api/webhooks/github
Secret: ${GITHUB_WEBHOOK_SECRET}
Events:
  - Issues
  - Issue comment
```

GitLab:
```yaml
# GitLab webhook settings
URL: https://mahavishnu.example.com/api/webhooks/gitlab
Secret: ${GITLAB_WEBHOOK_SECRET}
Triggers:
  - Issue
  - Note (comment)
```

---

## Implementation Phases

### Phase 1: Foundation (Week 1-2)

**Goal**: Basic task CRUD with CLI interface

**Deliverables**:
1. SQLite schema and migrations
2. Basic Task model with Pydantic
3. CLI commands: add, list, show, delete
4. Simple regex-based NLP parser
5. Repository manager integration
6. Unit tests (80% coverage)

**Tasks**:
- [ ] Create `mahavishnu/core/task_model.py` (Task Pydantic model)
- [ ] Create `mahavishnu/core/task_store.py` (SQLite backend)
- [ ] Create `mahavishnu/core/task_parser.py` (Regex NLP parser)
- [ ] Create `mahavishnu/task_cli.py` (Typer CLI commands)
- [ ] Create `tests/unit/test_task_model.py`
- [ ] Create `tests/unit/test_task_store.py`
- [ ] Create `tests/integration/test_task_cli.py`

**Acceptance Criteria**:
- Can create task via CLI
- Can list tasks with filters
- Can view task details
- Unit tests passing
- CLI help documentation complete

### Phase 2: Semantic Search & Akosha Integration (Week 3-4)

**Goal**: Semantic task search and pattern detection

**Deliverables**:
1. Akosha integration (task entities, embeddings)
2. Semantic search CLI command
3. Pattern detection (Akosha)
4. Dependency inference (Akosha)
5. Similar task recommendations

**Tasks**:
- [ ] Create `mahavishnu/core/task_akosha.py` (Akosha integration)
- [ ] Add embedding generation (sentence-transformers)
- [ ] Implement semantic search CLI: `mhv task find`
- [ ] Implement pattern detection: `mhv task insights`
- [ ] Create dependency inference
- [ ] Add similar task detection
- [ ] Create tests for Akosha integration

**Acceptance Criteria**:
- Semantic search finds relevant tasks
- Pattern detection provides insights
- Dependency inference suggests relationships
- Similar tasks recommended on creation

### Phase 3: Workflow Orchestration & Dhruva Integration (Week 5-6)

**Goal**: ONEIRIC task workflows and lifecycle management

**Deliverables**:
1. Dhruva integration (ONEIRIC task config)
2. Task workflow execution
3. Worktree integration (start command)
4. Quality gate integration (complete command)
5. Component lifecycle management

**Tasks**:
- [ ] Create task workflow schemas (ONEIRIC YAML)
- [ ] Create `mahavishnu/core/task_dhruva.py` (Dhruva integration)
- [ ] Implement `mhv task start` (worktree creation)
- [ ] Implement `mhv task complete` (quality gates)
- [ ] Create `tasks/` directory with workflow templates
- [ ] Integrate with worktree coordinator
- [ ] Integrate with Crackerjack quality gates
- [ ] Add task lifecycle tests

**Acceptance Criteria**:
- `mhv task start` creates worktree and opens terminal
- `mhv task complete` runs quality gates
- ONEIRIC workflows load and execute
- Worktree cleanup on completion

### Phase 4: Cross-Repo Coordination (Week 7)

**Goal**: Multi-repository task management

**Deliverables**:
1. Cross-repo task creation
2. Dependency management across repos
3. Multi-repo task graphs
4. Coordinated task execution

**Tasks**:
- [ ] Implement multi-repo NLP parsing
- [ ] Create dependency graph visualization
- [ ] Implement cross-repo dependency tracking
- [ ] Add `mhv task graph` command
- [ ] Implement coordinated task execution
- [ ] Add cross-repo tests

**Acceptance Criteria**:
- Can create tasks across multiple repos
- Dependencies tracked across repos
- Dependency graphs visualized
- Coordinated execution works

### Phase 5: External Sync (Week 8)

**Goal**: One-way sync from GitHub/GitLab

**Deliverables**:
1. GitHub webhook handler
2. GitLab webhook handler
3. Approval queue
4. CLI approval commands
5. Exceptional pushback to GitHub

**Tasks**:
- [ ] Create `mahavishnu/core/task_sync.py` (sync handler)
- [ ] Implement GitHub webhook endpoint
- [ ] Implement GitLab webhook endpoint
- [ ] Create approval queue (SQLite)
- [ ] Implement `mhv task approvals` command
- [ ] Implement `mhv task approve/reject` commands
- [ ] Implement `mhv task push --to-github` command
- [ ] Add webhook tests
- [ ] Add sync integration tests

**Acceptance Criteria**:
- GitHub issues create task proposals
- Approval workflow works
- Pushback to GitHub works
- Webhooks tested end-to-end

### Phase 6: TUI (Week 9-10)

**Goal**: Terminal user interface

**Deliverables**:
1. Textual TUI implementation
2. Real-time updates (WebSocket)
3. Keyboard navigation
4. Task details panel
5. Visual mode (bulk actions)

**Tasks**:
- [ ] Set up Textual project
- [ ] Create TUI layout (split panels)
- [ ] Implement task list widget
- [ ] Implement task details widget
- [ ] Add keyboard bindings
- [ ] Add WebSocket integration
- [ ] Add visual mode
- [ ] Create TUI tests

**Acceptance Criteria**:
- TUI launches and displays tasks
- Keyboard navigation works
- Real-time updates via WebSocket
- Can start/complete tasks from TUI
- Bulk actions work

### Phase 7: GUI & Web (Week 11-14)

**Goal**: Native desktop and web interfaces

**GUI Tasks**:
- [ ] Set up Electron project
- [ ] Create React components (task list, details, dashboard)
- [ ] Implement drag-and-drop
- [ ] Add Kanban board view
- [ ] Integrate WebSocket for real-time updates
- [ ] Add native notifications
- [ ] Create menu bar app (macOS)
- [ ] Package desktop app

**Web Tasks**:
- [ ] Set up FastAPI backend
- [ ] Create React/Next.js frontend
- [ ] Implement REST API endpoints
- [ ] Add WebSocket endpoints
- [ ] Create mobile-responsive design
- [ ] Add authentication (if needed)
- [ ] Deploy web app

**Acceptance Criteria**:
- GUI app launches and works
- Kanban board functional
- Real-time updates work
- Mobile web interface functional
- API documented

### Phase 8: Advanced Features (Week 15-16)

**Goal**: AI-powered features and optimization

**Deliverables**:
1. Advanced NLP (LLM-based parsing)
2. Voice command interface
3. Predictive analytics
4. Task recommendations
5. Performance optimization

**Tasks**:
- [ ] Integrate LLM for advanced NLP
- [ ] Implement voice commands (Speech-to-Text)
- [ ] Add predictive analytics
- [ ] Implement task recommendations
- [ ] Optimize SQLite queries
- [ ] Add query caching
- [ ] Performance testing
- [ ] Load testing

**Acceptance Criteria**:
- LLM parses complex task descriptions
- Voice commands work
- Predictions accurate (>80%)
- Performance <100ms for most queries
- System handles 1000+ tasks

---

## Success Metrics

### User Adoption

- **Week 1-4**: 10+ active users (internal testing)
- **Week 5-8**: 50+ active users (friends/family testing)
- **Week 9-12**: 100+ active users (public beta)
- **Week 13+**: 500+ active users (public release)

### Engagement

- **Tasks Created**: 1000+ tasks in first month
- **Tasks Completed**: >70% completion rate
- **Semantic Search**: >50% of searches use semantic (not full-text)
- **Worktree Integration**: >60% of tasks use worktree workflow

### Quality

- **Test Coverage**: >80% across all modules
- **Performance**: <100ms p95 for task queries
- **Uptime**: >99% for sync services
- **Bugs**: <10 critical bugs in first month

### Ecosystem Integration

- **Akosha**: 100% of tasks indexed with embeddings
- **Dhruva**: >80% of tasks use ONEIRIC workflows
- **Session-Buddy**: 100% of tasks have conversation history
- **Crackerjack**: >90% of completed tasks pass quality gates

---

## Risks & Mitigations

### Risk 1: NLP Parsing Accuracy

**Risk**: Natural language parser fails to extract correct metadata

**Impact**: High (user frustration, incorrect task creation)

**Mitigation**:
- Start with regex-based parser (Phase 1)
- Add LLM-based parser later (Phase 8)
- Always confirm extracted metadata with user
- Allow manual editing via CLI/GUI
- Continuous improvement from user feedback

**Contingency**: Fallback to manual task creation (CLI flags)

### Risk 2: Akosha Integration Complexity

**Risk**: Akosha integration is more complex than expected

**Impact**: Medium (semantic search delayed)

**Mitigation**:
- Start with full-text search (SQLite FTS)
- Add Akosha integration in Phase 2 (separate milestone)
- Design abstraction layer to swap search backends
- Test Akosha integration early

**Contingency**: Use full-text search initially, add semantic later

### Risk 3: One-Way Sync Approval Fatigue

**Risk**: Too many GitHub/GitLab issues to approve manually

**Impact**: Medium (workflow friction)

**Mitigation**:
- Auto-approve issues from trusted sources
- Filter by labels (e.g., auto-approve "bug" label)
- Bulk approval commands
- Smart approval suggestions (AI-based)

**Contingency**: Allow auto-approval rules

### Risk 4: Worktree Integration Edge Cases

**Risk**: Worktree creation fails in some scenarios

**Impact**: Medium (can't start task)

**Mitigation**:
- Test worktree integration thoroughly
- Provide fallback (manual worktree creation)
- Clear error messages
- Retry logic with exponential backoff

**Contingency**: Allow task without worktree

### Risk 5: Quality Gate Failures

**Risk**: Quality gates too strict, block legitimate completions

**Impact**: Medium (user frustration)

**Mitigation**:
- Make quality gates configurable
- Allow override with confirmation
- Provide clear feedback on failures
- Progressive enforcement (warn → block)

**Contingency**: Allow manual override with reason

### Risk 6: Performance at Scale

**Risk**: System slows down with 1000+ tasks

**Impact**: High (user experience degradation)

**Mitigation**:
- Database indexing from start
- Query optimization (EXPLAIN ANALYZE)
- Pagination for list views
- Caching layer (Redis)
- Load testing before public release

**Contingency**: Archive old tasks, implement cleanup

---

## Open Questions

1. **Task Deletion**: Should we allow hard delete or soft delete? (Recommend: Soft delete with archive)
2. **Task Ownership**: Single assignee or multiple? (Recommend: Single primary, multiple watchers)
3. **Task Priority**: Fixed set (low/medium/high/critical) or custom? (Recommend: Fixed + custom field)
4. **Worktree Naming**: `task-{id}-{slug}` or user-defined? (Recommend: Auto-generated with override)
5. **Quality Gates**: All gates required or configurable? (Recommend: Configurable per repo)
6. **Voice Commands**: Include in Phase 1 or Phase 8? (Recommend: Phase 8, advanced feature)
7. **Authentication**: Required for Web/GUI? (Recommend: Optional, local-first)
8. **Mobile Apps**: Native or responsive web? (Recommend: Responsive web first)

---

## Next Steps

1. **Review this master plan** with power trios
2. **Incorporate feedback** from reviews
3. **Create proof-of-concept** (minimal working prototype)
4. **Begin Phase 1** implementation
5. **Iterate based on user testing**

---

**Document Status**: DRAFT - Pending Review
**Last Updated**: 2025-02-18
**Version**: 1.0
