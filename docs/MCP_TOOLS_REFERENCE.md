# MCP Tools Reference

Complete reference for all Mahavishnu MCP server tools with status indicators, signatures, parameters, return values, and usage examples.

## Quick Reference

- **[Pool Management Tools](#pool-management-tools)** - 10 tools for multi-pool orchestration
- **[Worker Tools](#worker-tools)** - 8 tools for headless AI worker orchestration
- **[Coordination Tools](#coordination-tools)** - 13 tools for cross-repository coordination
- **[Repository Messaging Tools](#repository-messaging-tools)** - 7 tools for inter-repo communication
- **[Session Buddy Tools](#session-buddy-tools)** - 7 tools for session management integration
- **[OpenTelemetry Tools](#opentelemetry-tools)** - 4 tools for trace ingestion and search

**Legend:**
- ✅ **Production Ready** - Fully implemented and tested
- 🚧 **In Development** - Partially implemented, may have limitations
- ⚠️ **Deprecated** - Planned for removal, use alternatives

---

## Pool Management Tools

Manage multi-pool orchestration across local, delegated, and cloud workers.

### `pool_spawn` ✅

Spawn a new worker pool.

**Signature:**
```python
async def pool_spawn(
    pool_type: str = "mahavishnu",
    name: str = "default",
    min_workers: int = 1,
    max_workers: int = 10,
    worker_type: str = "terminal-qwen",
) -> dict[str, Any]
```

**Parameters:**
- `pool_type` - Pool type: `"mahavishnu"`, `"session-buddy"`, `"kubernetes"`
- `name` - Pool name for identification
- `min_workers` - Minimum worker count (1-10)
- `max_workers` - Maximum worker count (1-100)
- `worker_type` - Worker type: `"terminal-qwen"`, `"terminal-claude"`, `"container"`

**Returns:**
```python
{
    "pool_id": "pool_abc123",
    "pool_type": "mahavishnu",
    "name": "local-pool",
    "status": "created",
    "min_workers": 2,
    "max_workers": 5
}
```

**Example:**
```python
result = await pool_spawn(
    pool_type="mahavishnu",
    name="local-pool",
    min_workers=2,
    max_workers=5
)
print(f"Created pool: {result['pool_id']}")
```

---

### `pool_execute` ✅

Execute task on specific pool.

**Signature:**
```python
async def pool_execute(
    pool_id: str,
    prompt: str,
    timeout: int = 300,
) -> dict[str, Any]
```

**Parameters:**
- `pool_id` - Target pool ID (from `pool_spawn`)
- `prompt` - Task prompt for AI worker
- `timeout` - Execution timeout in seconds (30-3600)

**Returns:**
```python
{
    "pool_id": "pool_abc123",
    "worker_id": "term_xyz789",
    "status": "completed",
    "output": "Task output here...",
    "duration": 45.2
}
```

**Example:**
```python
result = await pool_execute(
    pool_id="pool_abc123",
    prompt="Write a Python REST API with FastAPI",
    timeout=600
)
print(f"Output: {result['output']}")
```

---

### `pool_route_execute` ✅

Execute task with automatic pool routing.

**Signature:**
```python
async def pool_route_execute(
    prompt: str,
    pool_selector: str = "least_loaded",
    timeout: int = 300,
) -> dict[str, Any]
```

**Parameters:**
- `prompt` - Task prompt
- `pool_selector` - Selection strategy: `"round_robin"`, `"least_loaded"`, `"random"`, `"affinity"`
- `timeout` - Execution timeout in seconds

**Returns:**
```python
{
    "pool_id": "pool_abc123",
    "status": "completed",
    "output": "Task output...",
    "routing_strategy": "least_loaded"
}
```

**Example:**
```python
result = await pool_route_execute(
    prompt="Refactor database layer",
    pool_selector="least_loaded",
    timeout=300
)
print(f"Executed on: {result['pool_id']}")
```

---

### `pool_list` ✅

List all active pools.

**Signature:**
```python
async def pool_list() -> list[dict[str, Any]]
```

**Returns:**
```python
[
    {
        "pool_id": "pool_abc123",
        "pool_type": "mahavishnu",
        "name": "local-pool",
        "status": "running",
        "workers_active": 3,
        "workers_total": 5
    }
]
```

**Example:**
```python
pools = await pool_list()
for pool in pools:
    print(f"{pool['pool_id']}: {pool['pool_type']} - {pool['status']}")
```

---

### `pool_monitor` ✅

Monitor pool status and metrics.

**Signature:**
```python
async def pool_monitor(
    pool_ids: list[str] | None = None,
) -> dict[str, dict[str, Any]]
```

**Parameters:**
- `pool_ids` - List of pool IDs (None = all pools)

**Returns:**
```python
{
    "pool_abc123": {
        "status": "healthy",
        "workers_active": 3,
        "tasks_completed": 42,
        "tasks_failed": 1,
        "average_latency": 2.3
    }
}
```

**Example:**
```python
metrics = await pool_monitor(pool_ids=["pool_abc", "pool_def"])
for pool_id, pool_metrics in metrics.items():
    print(f"{pool_id}: {pool_metrics['status']}")
```

---

### `pool_scale` ✅

Scale pool to target worker count.

**Signature:**
```python
async def pool_scale(
    pool_id: str,
    target_workers: int,
) -> dict[str, Any]
```

**Parameters:**
- `pool_id` - Pool ID to scale
- `target_workers` - Target worker count

**Returns:**
```python
{
    "pool_id": "pool_abc123",
    "target_workers": 10,
    "actual_workers": 10,
    "status": "scaled"
}
```

**Error Cases:**
- Returns error if pool doesn't support scaling (e.g., SessionBuddyPool is fixed at 3 workers)

**Example:**
```python
result = await pool_scale(pool_id="pool_abc123", target_workers=10)
print(f"Scaled to {result['actual_workers']} workers")
```

---

### `pool_close` ✅

Close a specific pool.

**Signature:**
```python
async def pool_close(
    pool_id: str,
) -> dict[str, Any]
```

**Parameters:**
- `pool_id` - Pool ID to close

**Returns:**
```python
{
    "pool_id": "pool_abc123",
    "status": "closed"
}
```

**Example:**
```python
result = await pool_close(pool_id="pool_abc123")
print(f"Pool {result['pool_id']} closed")
```

---

### `pool_close_all` ✅

Close all active pools.

**Signature:**
```python
async def pool_close_all() -> dict[str, Any]
```

**Returns:**
```python
{
    "pools_closed": 3,
    "status": "all_closed"
}
```

**Example:**
```python
result = await pool_close_all()
print(f"Closed {result['pools_closed']} pools")
```

---

### `pool_health` ✅

Get health status of all pools.

**Signature:**
```python
async def pool_health() -> dict[str, Any]
```

**Returns:**
```python
{
    "status": "healthy",
    "pools_active": 3,
    "pools_total": 3,
    "workers_active": 12,
    "details": {
        "pool_abc123": {"status": "healthy"},
        "pool_def456": {"status": "healthy"}
    }
}
```

**Example:**
```python
health = await pool_health()
print(f"Overall: {health['status']}, Active: {health['pools_active']}")
```

---

### `pool_search_memory` ✅

Search memory across all pools.

**Signature:**
```python
async def pool_search_memory(
    query: str,
    limit: int = 100,
) -> list[dict[str, Any]]
```

**Parameters:**
- `query` - Semantic search query
- `limit` - Maximum results to return

**Returns:**
```python
[
    {
        "content": "Task output or memory content...",
        "pool_id": "pool_abc123",
        "worker_id": "term_xyz789",
        "timestamp": "2025-01-22T12:34:56Z",
        "similarity": 0.92
    }
]
```

**Example:**
```python
results = await pool_search_memory(query="API implementation", limit=50)
for result in results:
    print(f"{result['content'][:100]}... (similarity: {result['similarity']})")
```

---

## Worker Tools

Orchestrate headless AI workers for parallel task execution.

### `worker_spawn` ✅

Spawn worker instances for task execution.

**Signature:**
```python
async def worker_spawn(
    worker_type: str = "terminal-qwen",
    count: int = 1,
) -> list[str]
```

**Parameters:**
- `worker_type` - Worker type: `"terminal-qwen"`, `"terminal-claude"`, `"container-executor"`
- `count` - Number of workers to spawn (1-50)

**Returns:**
```python
["term_abc123", "term_def456", "term_ghi789"]
```

**Example:**
```python
worker_ids = await worker_spawn(worker_type="terminal-qwen", count=3)
print(f"Spawned {len(worker_ids)} workers")
```

---

### `worker_execute` ✅

Execute task on specific worker.

**Signature:**
```python
async def worker_execute(
    worker_id: str,
    prompt: str,
    timeout: int = 300,
) -> dict
```

**Parameters:**
- `worker_id` - Worker ID (from `worker_spawn`)
- `prompt` - Task prompt
- `timeout` - Timeout in seconds (30-3600)

**Returns:**
```python
{
    "worker_id": "term_abc123",
    "status": "completed",
    "output": "Task output here...",
    "error": None,
    "duration": 45.2,
    "has_output": true
}
```

**Example:**
```python
result = await worker_execute(
    worker_id="term_abc123",
    prompt="Implement a REST API with FastAPI",
    timeout=600
)
print(f"Status: {result['status']}")
```

---

### `worker_execute_batch` ✅

Execute tasks on multiple workers concurrently.

**Signature:**
```python
async def worker_execute_batch(
    worker_ids: list[str],
    prompts: list[str],
    timeout: int = 300,
) -> dict
```

**Parameters:**
- `worker_ids` - List of worker IDs
- `prompts` - List of prompts (same length as worker_ids)
- `timeout` - Timeout for all tasks

**Returns:**
```python
{
    "term_abc123": {
        "status": "completed",
        "output": "Output from worker 1...",
        "duration": 42.1
    },
    "term_def456": {
        "status": "completed",
        "output": "Output from worker 2...",
        "duration": 38.7
    }
}
```

**Example:**
```python
results = await worker_execute_batch(
    worker_ids=["term_abc", "term_def"],
    prompts=["Task 1", "Task 2"],
    timeout=600
)
for wid, result in results.items():
    print(f"{wid}: {result['status']}")
```

---

### `worker_list` ✅

List all active workers.

**Signature:**
```python
async def worker_list() -> list[dict]
```

**Returns:**
```python
[
    {
        "worker_id": "term_abc123",
        "worker_type": "terminal-qwen",
        "status": "running",
        "pool_id": "pool_xyz789"
    }
]
```

**Example:**
```python
workers = await worker_list()
print(f"Active workers: {len(workers)}")
```

---

### `worker_monitor` ✅

Monitor worker status in real-time.

**Signature:**
```python
async def worker_monitor(
    worker_ids: list[str] | None = None,
    interval: float = 1.0,
) -> dict
```

**Parameters:**
- `worker_ids` - List of worker IDs (None = all workers)
- `interval` - Polling interval in seconds (0.1-10.0)

**Returns:**
```python
{
    "term_abc123": "running",
    "term_def456": "idle",
    "term_ghi789": "completed"
}
```

**Example:**
```python
statuses = await worker_monitor(interval=0.5)
for wid, status in statuses.items():
    print(f"{wid}: {status}")
```

---

### `worker_collect_results` ✅

Collect results from completed workers.

**Signature:**
```python
async def worker_collect_results(
    worker_ids: list[str] | None = None,
) -> dict
```

**Parameters:**
- `worker_ids` - List of worker IDs (None = all workers)

**Returns:**
```python
{
    "term_abc123": {
        "status": "completed",
        "output": "Full output here...",
        "error": None,
        "duration": 45.2,
        "has_output": true
    }
}
```

**Example:**
```python
results = await worker_collect_results(["term_abc", "term_def"])
for wid, result in results.items():
    if result["status"] == "completed":
        print(f"{wid}: {result['output'][:100]}...")
```

---

### `worker_close` ✅

Close a specific worker.

**Signature:**
```python
async def worker_close(worker_id: str) -> dict
```

**Parameters:**
- `worker_id` - Worker ID to close

**Returns:**
```python
{
    "success": true,
    "worker_id": "term_abc123"
}
```

**Example:**
```python
result = await worker_close("term_abc123")
print(f"Closed: {result['success']}")
```

---

### `worker_close_all` ✅

Close all active workers.

**Signature:**
```python
async def worker_close_all() -> dict
```

**Returns:**
```python
{
    "closed_count": 5
}
```

**Example:**
```python
result = await worker_close_all()
print(f"Closed {result['closed_count']} workers")
```

---

### `worker_health` ✅

Get worker system health.

**Signature:**
```python
async def worker_health() -> dict
```

**Returns:**
```python
{
    "status": "healthy",
    "workers_active": 5,
    "max_concurrent": 10,
    "details": {
        "pools_healthy": 2,
        "workers_idle": 3,
        "workers_busy": 2
    }
}
```

**Example:**
```python
health = await worker_health()
print(f"Status: {health['status']}, Active: {health['workers_active']}")
```

---

## Coordination Tools

Track and coordinate work across multiple repositories.

### `coord_list_issues` ✅

List cross-repository issues with optional filtering.

**Signature:**
```python
async def coord_list_issues(
    status: str | None = None,
    priority: str | None = None,
    repo: str | None = None,
    assignee: str | None = None,
) -> list[dict[str, Any]]
```

**Parameters:**
- `status` - Filter by status: `"pending"`, `"in_progress"`, `"blocked"`, `"resolved"`, `"closed"`
- `priority` - Filter by priority: `"critical"`, `"high"`, `"medium"`, `"low"`
- `repo` - Filter by repository nickname
- `assignee` - Filter by assignee username

**Returns:**
```python
[
    {
        "id": "ISSUE-001",
        "title": "Add authentication to API",
        "status": "in_progress",
        "priority": "high",
        "repos": ["my-api", "auth-service"],
        "assignee": "user@example.com"
    }
]
```

**Example:**
```python
issues = await coord_list_issues(status="in_progress", priority="high")
for issue in issues:
    print(f"{issue['id']}: {issue['title']}")
```

---

### `coord_get_issue` ✅

Get detailed information about a specific issue.

**Signature:**
```python
async def coord_get_issue(
    issue_id: str,
) -> dict[str, Any]
```

**Parameters:**
- `issue_id` - Issue identifier (e.g., `"ISSUE-001"`)

**Returns:**
```python
{
    "id": "ISSUE-001",
    "title": "Add authentication to API",
    "description": "Implement JWT authentication...",
    "status": "in_progress",
    "priority": "high",
    "repos": ["my-api", "auth-service"],
    "dependencies": ["ISSUE-002"],
    "blocking": ["ISSUE-003"],
    "assignee": "user@example.com",
    "created": "2025-01-22T12:00:00Z",
    "updated": "2025-01-23T09:30:00Z"
}
```

**Example:**
```python
issue = await coord_get_issue("ISSUE-001")
print(f"Issue: {issue['title']}")
print(f"Blocking {len(issue['blocking'])} other issues")
```

---

### `coord_create_issue` ✅

Create a new cross-repository issue.

**Signature:**
```python
async def coord_create_issue(
    title: str,
    description: str,
    repos: list[str],
    priority: str = "medium",
    severity: str = "normal",
    assignee: str | None = None,
    target: str | None = None,
    labels: list[str] | None = None,
) -> dict[str, Any]
```

**Parameters:**
- `title` - Issue title
- `description` - Detailed issue description
- `repos` - List of repository nicknames affected
- `priority` - Priority level: `"critical"`, `"high"`, `"medium"`, `"low"`
- `severity` - Severity level (e.g., `"bug"`, `"feature"`, `"migration"`)
- `assignee` - Assignee username (optional)
- `target` - Target completion date (ISO 8601 format, optional)
- `labels` - Labels for categorization (optional)

**Returns:**
```python
{
    "id": "ISSUE-001",
    "title": "Add authentication to API",
    "status": "pending",
    "priority": "high",
    "repos": ["my-api", "auth-service"]
}
```

**Example:**
```python
issue = await coord_create_issue(
    title="Add authentication",
    description="Implement JWT authentication for all API endpoints",
    repos=["my-api", "auth-service"],
    priority="high",
    assignee="user@example.com"
)
print(f"Created {issue['id']}")
```

---

### `coord_update_issue` ✅

Update an existing issue.

**Signature:**
```python
async def coord_update_issue(
    issue_id: str,
    status: str | None = None,
    priority: str | None = None,
) -> dict[str, Any]
```

**Parameters:**
- `issue_id` - Issue identifier
- `status` - New status: `"pending"`, `"in_progress"`, `"blocked"`, `"resolved"`, `"closed"`
- `priority` - New priority: `"critical"`, `"high"`, `"medium"`, `"low"`

**Returns:**
```python
{
    "id": "ISSUE-001",
    "status": "in_progress",
    "priority": "high",
    "updated": "2025-01-23T10:00:00Z"
}
```

**Example:**
```python
issue = await coord_update_issue(
    issue_id="ISSUE-001",
    status="in_progress"
)
print(f"Updated {issue['id']} to {issue['status']}")
```

---

### `coord_close_issue` ✅

Close an issue.

**Signature:**
```python
async def coord_close_issue(
    issue_id: str,
) -> dict[str, Any]
```

**Parameters:**
- `issue_id` - Issue identifier

**Returns:**
```python
{
    "id": "ISSUE-001",
    "status": "closed",
    "updated": "2025-01-23T11:00:00Z"
}
```

**Example:**
```python
issue = await coord_close_issue("ISSUE-001")
print(f"Closed {issue['id']}")
```

---

### `coord_list_todos` ✅

List todo items with optional filtering.

**Signature:**
```python
async def coord_list_todos(
    status: str | None = None,
    repo: str | None = None,
    assignee: str | None = None,
) -> list[dict[str, Any]]
```

**Parameters:**
- `status` - Filter by status: `"pending"`, `"in_progress"`, `"blocked"`, `"completed"`, `"cancelled"`
- `repo` - Filter by repository nickname
- `assignee` - Filter by assignee username

**Returns:**
```python
[
    {
        "id": "TODO-001",
        "task": "Write unit tests for auth module",
        "repo": "my-api",
        "status": "in_progress",
        "priority": "medium",
        "estimate_hours": 4.0
    }
]
```

**Example:**
```python
todos = await coord_list_todos(repo="my-api", status="pending")
for todo in todos:
    print(f"{todo['id']}: {todo['task']}")
```

---

### `coord_get_todo` ✅

Get detailed information about a specific todo.

**Signature:**
```python
async def coord_get_todo(
    todo_id: str,
) -> dict[str, Any]
```

**Parameters:**
- `todo_id` - Todo identifier (e.g., `"TODO-001"`)

**Returns:**
```python
{
    "id": "TODO-001",
    "task": "Write unit tests for auth module",
    "description": "Add comprehensive unit tests...",
    "repo": "my-api",
    "status": "in_progress",
    "priority": "medium",
    "estimated_hours": 4.0,
    "acceptance_criteria": [
        "Test all authentication endpoints",
        "Achieve 80% code coverage"
    ]
}
```

**Example:**
```python
todo = await coord_get_todo("TODO-001")
print(f"Task: {todo['task']}")
print(f"Estimate: {todo['estimated_hours']} hours")
```

---

### `coord_create_todo` ✅

Create a new todo item.

**Signature:**
```python
async def coord_create_todo(
    task: str,
    description: str,
    repo: str,
    estimate_hours: float,
    priority: str = "medium",
    assignee: str | None = None,
    blocked_by: list[str] | None = None,
    labels: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
) -> dict[str, Any]
```

**Parameters:**
- `task` - Task description
- `description` - Detailed task description
- `repo` - Repository nickname
- `estimate_hours` - Estimated time to complete (in hours)
- `priority` - Priority level: `"critical"`, `"high"`, `"medium"`, `"low"`
- `assignee` - Assignee username (optional)
- `blocked_by` - List of issue/todo IDs blocking this task (optional)
- `labels` - Labels for categorization (optional)
- `acceptance_criteria` - Criteria for completion (optional)

**Returns:**
```python
{
    "id": "TODO-001",
    "task": "Write unit tests for auth module",
    "repo": "my-api",
    "status": "pending",
    "priority": "medium",
    "estimated_hours": 4.0
}
```

**Example:**
```python
todo = await coord_create_todo(
    task="Write unit tests",
    description="Add comprehensive unit tests for auth module",
    repo="my-api",
    estimate_hours=4.0,
    priority="high",
    acceptance_criteria=["Test all endpoints", "80% coverage"]
)
print(f"Created {todo['id']}")
```

---

### `coord_complete_todo` ✅

Mark a todo as completed.

**Signature:**
```python
async def coord_complete_todo(
    todo_id: str,
) -> dict[str, Any]
```

**Parameters:**
- `todo_id` - Todo identifier

**Returns:**
```python
{
    "id": "TODO-001",
    "status": "completed",
    "updated": "2025-01-23T12:00:00Z"
}
```

**Example:**
```python
todo = await coord_complete_todo("TODO-001")
print(f"Completed {todo['id']}")
```

---

### `coord_get_blocking_issues` ✅

Get all issues blocking a specific repository.

**Signature:**
```python
async def coord_get_blocking_issues(
    repo: str,
) -> list[dict[str, Any]]
```

**Parameters:**
- `repo` - Repository nickname

**Returns:**
```python
[
    {
        "id": "ISSUE-001",
        "title": "Add authentication",
        "status": "in_progress",
        "priority": "high"
    }
]
```

**Example:**
```python
blocking = await coord_get_blocking_issues("my-api")
print(f"Blocking issues: {len(blocking)}")
```

---

### `coord_check_dependencies` ✅

Validate inter-repository dependencies.

**Signature:**
```python
async def coord_check_dependencies(
    consumer: str | None = None,
) -> dict[str, Any]
```

**Parameters:**
- `consumer` - Optional consumer repository to filter by

**Returns:**
```python
{
    "total": 10,
    "satisfied": 8,
    "unsatisfied": 2,
    "dependencies": [
        {
            "consumer": "my-api",
            "provider": "auth-service",
            "type": "runtime",
            "satisfied": true
        }
    ]
}
```

**Example:**
```python
results = await coord_check_dependencies(consumer="my-api")
print(f"Dependencies: {results['satisfied']}/{results['total']} satisfied")
```

---

### `coord_get_repo_status` ✅

Get comprehensive coordination status for a repository.

**Signature:**
```python
async def coord_get_repo_status(
    repo: str,
) -> dict[str, Any]
```

**Parameters:**
- `repo` - Repository nickname

**Returns:**
```python
{
    "issues": [...],
    "todos": [...],
    "dependencies_outgoing": [...],
    "dependencies_incoming": [...],
    "blocking": [...],
    "blocked_by": [...]
}
```

**Example:**
```python
status = await coord_get_repo_status("my-api")
print(f"Issues: {len(status['issues'])}")
print(f"Todos: {len(status['todos'])}")
```

---

### `coord_list_plans` ✅

List cross-repository plans with optional filtering.

**Signature:**
```python
async def coord_list_plans(
    status: str | None = None,
    repo: str | None = None,
) -> list[dict[str, Any]]
```

**Parameters:**
- `status` - Filter by status: `"draft"`, `"active"`, `"on_hold"`, `"completed"`, `"cancelled"`
- `repo` - Filter by repository nickname

**Returns:**
```python
[
    {
        "id": "PLAN-001",
        "title": "Q1 Feature Sprint",
        "status": "active",
        "repos": ["my-api", "my-frontend"]
    }
]
```

**Example:**
```python
plans = await coord_list_plans(status="active")
for plan in plans:
    print(f"{plan['id']}: {plan['title']}")
```

---

### `coord_list_dependencies` ✅

List inter-repository dependencies with optional filtering.

**Signature:**
```python
async def coord_list_dependencies(
    consumer: str | None = None,
    provider: str | None = None,
    dependency_type: str | None = None,
) -> list[dict[str, Any]]
```

**Parameters:**
- `consumer` - Filter by consumer repository
- `provider` - Filter by provider repository
- `dependency_type` - Filter by type: `"runtime"`, `"development"`, `"mcp"`, `"test"`, `"documentation"`

**Returns:**
```python
[
    {
        "consumer": "my-api",
        "provider": "auth-service",
        "type": "runtime",
        "satisfied": true
    }
]
```

**Example:**
```python
deps = await coord_list_dependencies(consumer="my-api", type="runtime")
for dep in deps:
    print(f"{dep['consumer']} -> {dep['provider']}")
```

---

## Repository Messaging Tools

Send and receive messages between repositories.

### `send_repository_message` ✅

Send a message from one repository to another.

**Signature:**
```python
async def send_repository_message(
    sender_repo: str,
    receiver_repo: str,
    message_type: str,
    content: dict[str, Any],
    priority: str = "NORMAL",
) -> dict[str, Any]
```

**Parameters:**
- `sender_repo` - Repository sending the message
- `receiver_repo` - Repository receiving the message
- `message_type` - Type: `"CODE_CHANGE_NOTIFICATION"`, `"WORKFLOW_STATUS_UPDATE"`, etc.
- `content` - Message content as dictionary
- `priority` - Priority: `"LOW"`, `"NORMAL"`, `"HIGH"`, `"CRITICAL"`

**Returns:**
```python
{
    "status": "success",
    "message_id": "msg_abc123",
    "sent_at": "2025-01-23T12:00:00Z",
    "priority": "NORMAL"
}
```

**Example:**
```python
result = await send_repository_message(
    sender_repo="my-api",
    receiver_repo="my-frontend",
    message_type="CODE_CHANGE_NOTIFICATION",
    content={"file": "auth.py", "change": "Added JWT endpoint"},
    priority="HIGH"
)
print(f"Sent: {result['message_id']}")
```

---

### `broadcast_repository_message` ✅

Broadcast a message to multiple repositories.

**Signature:**
```python
async def broadcast_repository_message(
    sender_repo: str,
    message_type: str,
    content: dict[str, Any],
    target_repos: list[str] | None = None,
    priority: str = "NORMAL",
) -> dict[str, Any]
```

**Parameters:**
- `sender_repo` - Repository sending the message
- `message_type` - Type of message
- `content` - Message content
- `target_repos` - List of target repositories (None = all repositories)
- `priority` - Message priority

**Returns:**
```python
{
    "status": "success",
    "messages_sent": 3,
    "message_ids": ["msg_abc", "msg_def", "msg_ghi"],
    "target_repos": ["repo1", "repo2", "repo3"]
}
```

**Example:**
```python
result = await broadcast_repository_message(
    sender_repo="my-api",
    message_type="WORKFLOW_STATUS_UPDATE",
    content={"workflow_id": "wf_123", "status": "completed"},
    target_repos=["my-frontend", "my-docs"]
)
print(f"Broadcast to {result['messages_sent']} repos")
```

---

### `get_repository_messages` ✅

Get messages for a specific repository.

**Signature:**
```python
async def get_repository_messages(
    receiver_repo: str,
    message_type: str | None = None,
    limit: int = 50,
    since: str | None = None,
) -> dict[str, Any]
```

**Parameters:**
- `receiver_repo` - Repository to get messages for
- `message_type` - Optional message type filter
- `limit` - Maximum messages to return
- `since` - Optional ISO datetime string filter

**Returns:**
```python
{
    "status": "success",
    "messages": [
        {
            "id": "msg_abc123",
            "sender_repo": "my-api",
            "receiver_repo": "my-frontend",
            "message_type": "CODE_CHANGE_NOTIFICATION",
            "content": {"file": "auth.py"},
            "priority": "NORMAL",
            "timestamp": "2025-01-23T12:00:00Z"
        }
    ],
    "count": 1
}
```

**Example:**
```python
result = await get_repository_messages(
    receiver_repo="my-frontend",
    message_type="CODE_CHANGE_NOTIFICATION",
    limit=10
)
print(f"Messages: {result['count']}")
```

---

### `acknowledge_repository_message` ✅

Acknowledge receipt of a message.

**Signature:**
```python
async def acknowledge_repository_message(
    message_id: str,
    receiver_repo: str,
) -> dict[str, Any]
```

**Parameters:**
- `message_id` - ID of the message to acknowledge
- `receiver_repo` - Repository acknowledging the message

**Returns:**
```python
{
    "status": "success",
    "message_id": "msg_abc123",
    "acknowledged_by": "my-frontend",
    "success": true
}
```

**Example:**
```python
result = await acknowledge_repository_message(
    message_id="msg_abc123",
    receiver_repo="my-frontend"
)
print(f"Acknowledged: {result['success']}")
```

---

### `notify_repository_changes` ✅

Notify other repositories about changes in a repository.

**Signature:**
```python
async def notify_repository_changes(
    repo_path: str,
    changes: list[dict[str, Any]],
) -> dict[str, Any]
```

**Parameters:**
- `repo_path` - Path of the repository with changes
- `changes` - List of changes to notify about

**Returns:**
```python
{
    "status": "success",
    "messages_sent": 2,
    "changes_notified": 2
}
```

**Example:**
```python
result = await notify_repository_changes(
    repo_path="/path/to/my-api",
    changes=[
        {"type": "file_modified", "path": "auth.py"},
        {"type": "file_added", "path": "tests/test_auth.py"}
    ]
)
print(f"Notified {result['messages_sent']} repos")
```

---

### `notify_workflow_status` ✅

Notify other repositories about workflow status changes.

**Signature:**
```python
async def notify_workflow_status(
    workflow_id: str,
    status: str,
    repo_path: str,
    target_repos: list[str] | None = None,
) -> dict[str, Any]
```

**Parameters:**
- `workflow_id` - ID of the workflow
- `status` - New status of the workflow
- `repo_path` - Repository where workflow is running
- `target_repos` - Optional list of target repositories

**Returns:**
```python
{
    "status": "success",
    "messages_sent": 3,
    "workflow_id": "wf_abc123"
}
```

**Example:**
```python
result = await notify_workflow_status(
    workflow_id="wf_abc123",
    status="completed",
    repo_path="/path/to/my-api",
    target_repos=["my-frontend"]
)
print(f"Notified {result['messages_sent']} repos")
```

---

### `send_quality_alert` ✅

Send a quality alert to other repositories.

**Signature:**
```python
async def send_quality_alert(
    repo_path: str,
    alert_type: str,
    description: str,
    severity: str = "medium",
) -> dict[str, Any]
```

**Parameters:**
- `repo_path` - Repository sending the alert
- `alert_type` - Type of quality alert
- `description` - Description of the quality issue
- `severity` - Severity: `"low"`, `"medium"`, `"high"`, `"critical"`

**Returns:**
```python
{
    "status": "success",
    "messages_sent": 3,
    "alert_type": "security_vulnerability",
    "severity": "high"
}
```

**Example:**
```python
result = await send_quality_alert(
    repo_path="/path/to/my-api",
    alert_type="security_vulnerability",
    description="SQL injection vulnerability in auth.py",
    severity="critical"
)
print(f"Alert sent to {result['messages_sent']} repos")
```

---

## Session Buddy Tools

Integration with Session Buddy for session management and code analysis.

### `index_code_graph` 🚧

Index codebase structure for better context in Session Buddy.

**Signature:**
```python
async def index_code_graph(
    project_path: str,
    include_docs: bool = True,
) -> dict[str, Any]
```

**Parameters:**
- `project_path` - Path to the project to analyze
- `include_docs` - Whether to include documentation indexing

**Returns:**
```python
{
    "status": "success",
    "result": {
        "files_indexed": 42,
        "functions_indexed": 156,
        "classes_indexed": 23
    }
}
```

**Example:**
```python
result = await index_code_graph(
    project_path="/path/to/my-project",
    include_docs=True
)
print(f"Indexed {result['result']['functions_indexed']} functions")
```

---

### `get_function_context` 🚧

Get caller/callee context for a function.

**Signature:**
```python
async def get_function_context(
    project_path: str,
    function_name: str,
) -> dict[str, Any]
```

**Parameters:**
- `project_path` - Path to the project
- `function_name` - Name of the function to analyze

**Returns:**
```python
{
    "status": "success",
    "result": {
        "function": "authenticate_user",
        "callers": ["login", "verify_token"],
        "callees": ["validate_password", "generate_jwt"]
    }
}
```

**Example:**
```python
result = await get_function_context(
    project_path="/path/to/my-project",
    function_name="authenticate_user"
)
print(f"Called by: {result['result']['callers']}")
```

---

### `find_related_code` 🚧

Find code related by imports/calls.

**Signature:**
```python
async def find_related_code(
    project_path: str,
    file_path: str,
) -> dict[str, Any]
```

**Parameters:**
- `project_path` - Path to the project
- `file_path` - Path to the file to analyze

**Returns:**
```python
{
    "status": "success",
    "result": {
        "imports": ["auth", "database"],
        "imported_by": ["api", "tests"],
        "related_files": ["auth.py", "models.py"]
    }
}
```

**Example:**
```python
result = await find_related_code(
    project_path="/path/to/my-project",
    file_path="api/auth.py"
)
print(f"Related files: {result['result']['related_files']}")
```

---

### `index_documentation` 🚧

Extract docstrings and index for semantic search.

**Signature:**
```python
async def index_documentation(
    project_path: str,
) -> dict[str, Any]
```

**Parameters:**
- `project_path` - Path to the project

**Returns:**
```python
{
    "status": "success",
    "result": {
        "docstrings_indexed": 87,
        "modules_indexed": 12
    }
}
```

**Example:**
```python
result = await index_documentation(project_path="/path/to/my-project")
print(f"Indexed {result['result']['docstrings_indexed']} docstrings")
```

---

### `search_documentation` 🚧

Search through indexed documentation.

**Signature:**
```python
async def search_documentation(
    query: str,
) -> dict[str, Any]
```

**Parameters:**
- `query` - Search query

**Returns:**
```python
{
    "status": "success",
    "result": [
        {
            "content": "Function docstring...",
            "file": "auth.py",
            "line": 42,
            "score": 0.95
        }
    ]
}
```

**Example:**
```python
result = await search_documentation(query="authentication function")
for match in result['result']:
    print(f"{match['file']}:{match['line']} - {match['content'][:50]}...")
```

---

### `send_project_message` 🚧

Send message between projects for Session Buddy.

**Signature:**
```python
async def send_project_message(
    from_project: str,
    to_project: str,
    subject: str,
    message: str,
    priority: str = "NORMAL",
) -> dict[str, Any]
```

**Parameters:**
- `from_project` - Source project identifier
- `to_project` - Destination project identifier
- `subject` - Message subject
- `message` - Message content
- `priority` - Priority: `"NORMAL"`, `"HIGH"`, `"CRITICAL"`

**Returns:**
```python
{
    "status": "success",
    "result": {
        "message_id": "proj_msg_abc123",
        "sent_at": "2025-01-23T12:00:00Z"
    }
}
```

**Example:**
```python
result = await send_project_message(
    from_project="my-api",
    to_project="my-frontend",
    subject="API breaking change",
    message="JWT endpoint signature changed",
    priority="HIGH"
)
print(f"Sent: {result['result']['message_id']}")
```

---

### `list_project_messages` 🚧

List messages for a project in Session Buddy.

**Signature:**
```python
async def list_project_messages(
    project: str,
) -> dict[str, Any]
```

**Parameters:**
- `project` - Project identifier

**Returns:**
```python
{
    "status": "success",
    "result": [
        {
            "message_id": "proj_msg_abc123",
            "from_project": "my-api",
            "subject": "API breaking change",
            "timestamp": "2025-01-23T12:00:00Z"
        }
    ]
}
```

**Example:**
```python
result = await list_project_messages(project="my-frontend")
for msg in result['result']:
    print(f"{msg['subject']} from {msg['from_project']}")
```

---

## OpenTelemetry Tools

Ingest and search OpenTelemetry traces using Akosha HotStore (DuckDB).

### `ingest_otel_traces` ✅

Ingest OpenTelemetry traces from log files or direct trace data.

**Signature:**
```python
async def ingest_otel_traces(
    log_files: list[str] | None = None,
    trace_data: list[dict] | None = None,
    system_id: str = "unknown",
) -> dict[str, Any]
```

**Parameters:**
- `log_files` - Optional list of log file paths to ingest (JSON format)
- `trace_data` - Optional list of trace dictionaries to ingest directly
- `system_id` - System identifier (e.g., `"claude"`, `"qwen"`, or custom name)

**Returns:**
```python
{
    "status": "success",
    "traces_ingested": 150,
    "files_processed": 2,
    "errors": [],
    "system_id": "claude",
    "storage_backend": "duckdb_hotstore"
}
```

**Example:**
```python
result = await ingest_otel_traces(
    log_files=["/path/to/claude_session.json"],
    system_id="claude"
)
print(f"Ingested {result['traces_ingested']} traces")
```

---

### `search_otel_traces` ✅

Semantic search over OTel traces using vector embeddings.

**Signature:**
```python
async def search_otel_traces(
    query: str,
    system_id: str | None = None,
    limit: int = 10,
    threshold: float | None = None,
) -> list[dict[str, Any]]
```

**Parameters:**
- `query` - Natural language search query (e.g., `"RAG pipeline timeout"`)
- `system_id` - Optional system filter (e.g., `"claude"`, `"qwen"`)
- `limit` - Maximum results to return
- `threshold` - Optional minimum similarity score (0.0-1.0)

**Returns:**
```python
[
    {
        "conversation_id": "conv_abc123",
        "system_id": "claude",
        "content": "Discussion about RAG pipeline...",
        "timestamp": "2025-01-23T12:00:00Z",
        "similarity": 0.92,
        "metadata": {...}
    }
]
```

**Example:**
```python
results = await search_otel_traces(
    query="RAG pipeline failed with timeout",
    system_id="claude",
    limit=5,
    threshold=0.75
)
for result in results:
    print(f"{result['content'][:100]}... (similarity: {result['similarity']})")
```

---

### `get_otel_trace` ✅

Retrieve a specific OTel trace by ID.

**Signature:**
```python
async def get_otel_trace(
    trace_id: str,
) -> dict[str, Any] | None
```

**Parameters:**
- `trace_id` - Unique trace identifier (conversation_id in HotStore)

**Returns:**
```python
{
    "conversation_id": "conv_abc123",
    "system_id": "claude",
    "content": "Full trace content...",
    "timestamp": "2025-01-23T12:00:00Z",
    "metadata": {...}
}
```

Returns `None` if trace not found.

**Example:**
```python
trace = await get_otel_trace(trace_id="conv_abc123")
if trace:
    print(f"Found trace from {trace['timestamp']}")
else:
    print("Trace not found")
```

---

### `otel_ingester_stats` ✅

Get statistics about the OTel trace ingester.

**Signature:**
```python
async def otel_ingester_stats() -> dict[str, Any]
```

**Returns:**
```python
{
    "storage_backend": "duckdb_hotstore",
    "hot_store_path": ":memory:",
    "embedding_model": "all-MiniLM-L6-v2",
    "cache_size": 1000,
    "similarity_threshold": 0.7,
    "status": "healthy",
    "total_traces": "unknown",
    "traces_by_system": {}
}
```

**Example:**
```python
stats = await otel_ingester_stats()
print(f"Storage: {stats['storage_backend']}")
print(f"Status: {stats['status']}")
```

---

## Summary

**Total MCP Tools: 49**

- **Pool Management:** 10 tools (✅ Production Ready)
- **Worker Orchestration:** 8 tools (✅ Production Ready)
- **Coordination:** 13 tools (✅ Production Ready)
- **Repository Messaging:** 7 tools (✅ Production Ready)
- **Session Buddy:** 7 tools (🚧 In Development)
- **OpenTelemetry:** 4 tools (✅ Production Ready)

For more detailed specifications, see [MCP_TOOLS_SPECIFICATION.md](MCP_TOOLS_SPECIFICATION.md).

For usage examples, see [GETTING_STARTED.md](GETTING_STARTED.md).
