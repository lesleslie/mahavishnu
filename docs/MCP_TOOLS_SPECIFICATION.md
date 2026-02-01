# MCP Server Tool Specification

## Overview

Mahavishnu's MCP server provides a comprehensive set of tools for managing workflows, repositories, and orchestration engines. All tools are implemented using FastMCP with async/await patterns, comprehensive error handling, and observability.

## Tool Categories

### 1. Repository Management Tools

Tools for listing, filtering, and managing repositories.

### 2. Workflow Execution Tools

Tools for triggering, monitoring, and managing workflows.

### 3. Adapter Management Tools

Tools for managing and querying orchestration adapters.

### 4. Quality Control Tools

Tools for running and managing Crackerjack QC checks.

### 5. Worker Management Tools

Tools for orchestrating headless AI workers across terminals and containers.

### 6. Session Management Tools

Tools for managing Session-Buddy checkpoints and state.

### 7. Pool Management Tools

Tools for multi-pool orchestration, routing, and scaling across local, delegated, and cloud workers.

### 8. OpenTelemetry Tools

Tools for ingesting and searching OpenTelemetry traces using Akosha HotStore (DuckDB).

______________________________________________________________________

## Tool Specifications

### Repository Management Tools

#### `list_repos`

List repositories with optional tag filtering.

**Signature:**

```python
async def list_repos(
    tag: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]
```

**Parameters:**

- `tag` (optional): Filter repositories by tag. Example: "backend", "python"
- `limit` (optional): Maximum number of repositories to return. Default: no limit
- `offset` (optional): Number of repositories to skip. Default: 0

**Returns:**

```python
[
    {
        "path": "/path/to/repo",
        "tags": ["backend", "python"],
        "description": "Backend services repository",
        "metadata": {
            "owner": "team-backend",
            "language": "python",
        }
    },
    # ... more repos
]
```

**Errors:**

- `ValueError`: If `repos.yaml` is not found or invalid
- `PermissionError`: If `repos.yaml` is not readable

**Example:**

```python
# List all backend repositories
repos = await list_repos(tag="backend")

# List first 10 repositories
repos = await list_repos(limit=10)

# Pagination
repos = await list_repos(limit=10, offset=20)
```

______________________________________________________________________

#### `get_repo_health`

Get health status for a specific repository.

**Signature:**

```python
async def get_repo_health(
    repo_path: str,
) -> dict[str, Any]
```

**Parameters:**

- `repo_path`: Path to repository (must be in `repos.yaml`)

**Returns:**

```python
{
    "path": "/path/to/repo",
    "healthy": true,
    "git_status": "clean",
    "branch": "main",
    "ahead_by": 0,
    "behind_by": 0,
    "open_prs": 3,
    "open_issues": 5,
    "last_commit": "2025-01-22T12:34:56Z",
    "last_commit_author": "user@example.com",
    "metadata": {
        "size_bytes": 1048576,
        "file_count": 42,
    }
}
```

**Errors:**

- `ValueError`: If repo is not found in `repos.yaml`
- `GitError`: If repo is not a valid git repository

**Checks Performed:**

- Git status (clean/dirty)
- Branch status (ahead/behind remote)
- Open PRs (via GitHub/GitLab API if configured)
- Open issues (via GitHub/GitLab API if configured)
- Recent activity (last commit time)

______________________________________________________________________

#### `search_repos`

Search repositories by path, tag, or description.

**Signature:**

```python
async def search_repos(
    query: str,
    search_fields: list[str] = ["path", "tags", "description"],
) -> list[dict[str, Any]]
```

**Parameters:**

- `query`: Search query (case-insensitive substring match)
- `search_fields`: Fields to search in. Default: ["path", "tags", "description"]

**Returns:**

```python
[
    {
        "path": "/path/to/python-repo",
        "tags": ["backend", "python"],
        "description": "Python backend services",
        "match_score": 0.95,
    },
    # ... more matching repos
]
```

______________________________________________________________________

### Workflow Execution Tools

#### `trigger_workflow`

Trigger a new workflow execution.

**Signature:**

```python
async def trigger_workflow(
    task_type: str,
    task_params: dict[str, Any],
    adapter: str,
    tag: str | None = None,
    repos: list[str] | None = None,
    checkpoint_enabled: bool = True,
    qc_enabled: bool = True,
) -> dict[str, Any]
```

**Parameters:**

- `task_type`: Type of task ("code_sweep", "dependency_audit", "test_generation")
- `task_params`: Task-specific parameters
- `adapter`: Orchestrator adapter to use ("prefect", "agno", "llamaindex")
- `tag` (optional): Filter repositories by tag
- `repos` (optional): Specific repositories to process (overrides tag)
- `checkpoint_enabled`: Enable Session-Buddy checkpoints. Default: true
- `qc_enabled`: Enable Crackerjack QC after execution. Default: true

**Returns:**

```python
{
    "workflow_id": "wf-abc123",
    "status": "running",
    "adapter": "prefect",
    "task_type": "code_sweep",
    "repos": ["/path/to/repo1", "/path/to/repo2"],
    "started_at": "2025-01-22T12:34:56Z",
    "estimated_completion": "2025-01-22T12:44:56Z",
    "checkpoint_path": "/path/to/checkpoint.json",
}
```

**Errors:**

- `ValueError`: If adapter is not enabled or invalid
- `ValidationError`: If task parameters are invalid
- `ResourceError`: If system is at capacity

**Example:**

```python
# Trigger code sweep on all backend repos
workflow = await trigger_workflow(
    task_type="code_sweep",
    task_params={
        "focus": ["security", "performance"],
    },
    adapter="prefect",
    tag="backend",
)

# Trigger dependency audit on specific repos
workflow = await trigger_workflow(
    task_type="dependency_audit",
    task_params={
        "check_updates": True,
        "check_vulnerabilities": True,
    },
    adapter="agno",
    repos=["/path/to/repo1", "/path/to/repo2"],
)
```

______________________________________________________________________

#### `get_workflow_status`

Get status of a running or completed workflow.

**Signature:**

```python
async def get_workflow_status(
    workflow_id: str,
) -> dict[str, Any]
```

**Parameters:**

- `workflow_id`: Workflow identifier (from `trigger_workflow`)

**Returns:**

```python
{
    "workflow_id": "wf-abc123",
    "status": "running",  # "running", "completed", "failed", "cancelled"
    "adapter": "prefect",
    "task_type": "code_sweep",
    "started_at": "2025-01-22T12:34:56Z",
    "completed_at": None,
    "progress": {
        "total_repos": 10,
        "completed_repos": 5,
        "failed_repos": 1,
        "percentage": 50,
    },
    "repos": [
        {
            "path": "/path/to/repo1",
            "status": "completed",
            "duration_seconds": 45.2,
        },
        {
            "path": "/path/to/repo2",
            "status": "running",
            "duration_seconds": 23.1,
        },
        # ... more repos
    ],
    "qc_results": {
        "enabled": true,
        "completed_checks": 5,
        "total_checks": 10,
        "average_score": 85,
    },
}
```

**Errors:**

- `ValueError`: If workflow_id is not found

______________________________________________________________________

#### `cancel_workflow`

Cancel a running workflow.

**Signature:**

```python
async def cancel_workflow(
    workflow_id: str,
    reason: str | None = None,
) -> dict[str, Any]
```

**Parameters:**

- `workflow_id`: Workflow identifier
- `reason` (optional): Reason for cancellation

**Returns:**

```python
{
    "workflow_id": "wf-abc123",
    "status": "cancelled",
    "cancelled_at": "2025-01-22T12:40:00Z",
    "reason": "User requested cancellation",
    "progress": {
        "total_repos": 10,
        "completed_repos": 5,
        "failed_repos": 0,
    },
    "checkpoint_saved": True,
}
```

**Errors:**

- `ValueError`: If workflow_id is not found
- `StateError`: If workflow is already completed

______________________________________________________________________

#### `list_workflows`

List workflow executions with optional filtering.

**Signature:**

```python
async def list_workflows(
    status: str | None = None,
    adapter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]
```

**Parameters:**

- `status` (optional): Filter by status ("running", "completed", "failed", "cancelled")
- `adapter` (optional): Filter by adapter
- `limit`: Maximum number of workflows to return. Default: 50
- `offset`: Number of workflows to skip. Default: 0

**Returns:**

```python
[
    {
        "workflow_id": "wf-abc123",
        "status": "completed",
        "adapter": "prefect",
        "task_type": "code_sweep",
        "started_at": "2025-01-22T12:34:56Z",
        "completed_at": "2025-01-22T12:44:56Z",
        "duration_seconds": 600,
        "repos_count": 10,
        "success_count": 9,
        "failure_count": 1,
    },
    # ... more workflows
]
```

______________________________________________________________________

### Adapter Management Tools

#### `list_adapters`

List available orchestration adapters.

**Signature:**

```python
async def list_adapters() -> list[dict[str, Any]]
```

**Returns:**

```python
[
    {
        "name": "prefect",
        "enabled": true,
        "healthy": true,
        "version": "0.0.40",
        "capabilities": [
            "stateful_workflows",
            "checkpointing",
            "conditional_routing",
        ],
        "stats": {
            "executions": 42,
            "successes": 40,
            "failures": 2,
        },
    },
    {
        "name": "crewai",
        "enabled": true,
        "healthy": true,
        "version": "0.28.0",
        "capabilities": [
            "multi_agent_coordination",
            "tool_integration",
        ],
        "stats": {
            "executions": 15,
            "successes": 14,
            "failures": 1,
        },
    },
    # ... more adapters
]
```

______________________________________________________________________

#### `get_adapter_health`

Get health status for a specific adapter.

**Signature:**

```python
async def get_adapter_health(
    adapter_name: str,
) -> dict[str, Any]
```

**Parameters:**

- `adapter_name`: Name of adapter ("prefect", "agno", "llamaindex")

**Returns:**

```python
{
    "name": "prefect",
    "healthy": true,
    "status": "operational",
    "version": "0.0.40",
    "dependencies": {
        "llm_provider": "healthy",
        "database": "healthy",
        "checkpoint_dir": "accessible",
    },
    "stats": {
        "executions": 42,
        "successes": 40,
        "failures": 2,
        "average_duration_seconds": 450,
    },
    "last_health_check": "2025-01-22T12:34:56Z",
}
```

**Errors:**

- `ValueError`: If adapter_name is not found

______________________________________________________________________

#### `enable_adapter / disable_adapter`

Enable or disable an adapter.

**Signature:**

```python
async def enable_adapter(adapter_name: str) -> dict[str, Any]
async def disable_adapter(adapter_name: str) -> dict[str, Any]
```

**Parameters:**

- `adapter_name`: Name of adapter

**Returns:**

```python
{
    "adapter_name": "langgraph",
    "enabled": True,
    "message": "Adapter enabled successfully",
    "requires_restart": False,
}
```

**Errors:**

- `ValueError`: If adapter_name is not found
- `StateError`: If adapter is already in target state

______________________________________________________________________

### Quality Control Tools

#### `run_qc`

Run Crackerjack QC checks on a repository.

**Signature:**

```python
async def run_qc(
    repo_path: str,
    checks: list[str] | None = None,
    autofix: bool = False,
) -> dict[str, Any]
```

**Parameters:**

- `repo_path`: Path to repository
- `checks` (optional): List of checks to run. Default: from config
- `autofix`: Enable automatic fixes. Default: false

**Returns:**

```python
{
    "repo_path": "/path/to/repo",
    "score": 85,
    "passed": true,
    "checks": [
        {
            "name": "linting",
            "enabled": true,
            "score": 90,
            "passed": true,
            "issues_found": 5,
            "issues_fixed": 3 if autofix else 0,
            "duration_seconds": 30,
        },
        {
            "name": "type_checking",
            "enabled": true,
            "score": 80,
            "passed": true,
            "issues_found": 3,
            "issues_fixed": 0,
            "duration_seconds": 45,
        },
        {
            "name": "security_scan",
            "enabled": true,
            "score": 85,
            "passed": true,
            "issues_found": 2,
            "issues_fixed": 0,
            "duration_seconds": 20,
        },
    ],
    "total_duration_seconds": 95,
    "threshold": 80,
}
```

**Available Checks:**

- `linting`: Code style linting (flake8, black, isort)
- `type_checking`: Static type checking (mypy)
- `security_scan`: Security vulnerability scanning (bandit)
- `complexity`: Code complexity analysis (mccabe)
- `formatting`: Code formatting (black, prettier)

______________________________________________________________________

#### `get_qc_thresholds`

Get QC threshold configuration.

**Signature:**

```python
async def get_qc_thresholds() -> dict[str, Any]
```

**Returns:**

```python
{
    "min_score": 80,
    "checks": {
        "linting": {
            "enabled": true,
            "weight": 30,
            "threshold": 75,
        },
        "type_checking": {
            "enabled": true,
            "weight": 30,
            "threshold": 80,
        },
        "security_scan": {
            "enabled": true,
            "weight": 40,
            "threshold": 90,
        },
    },
}
```

______________________________________________________________________

#### `set_qc_thresholds`

Set QC threshold configuration.

**Signature:**

```python
async def set_qc_thresholds(
    min_score: int | None = None,
    check_thresholds: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]
```

**Parameters:**

- `min_score` (optional): Overall minimum score (0-100)
- `check_thresholds` (optional): Per-check thresholds

**Returns:**

```python
{
    "min_score": 80,
    "checks": {
        "linting": {
            "enabled": true,
            "weight": 30,
            "threshold": 75,
        },
        # ... more checks
    },
    "message": "Thresholds updated successfully",
}
```

**Errors:**

- `ValueError`: If thresholds are out of range (0-100)

______________________________________________________________________

### Session Management Tools

#### `list_checkpoints`

List Session-Buddy checkpoints.

**Signature:**

```python
async def list_checkpoints(
    workflow_id: str | None = None,
) -> list[dict[str, Any]]
```

**Parameters:**

- `workflow_id` (optional): Filter by workflow ID

**Returns:**

```python
[
    {
        "workflow_id": "wf-abc123",
        "checkpoint_path": "/path/to/checkpoint.json",
        "created_at": "2025-01-22T12:34:56Z",
        "state": {
            "task": {...},
            "repos": ["/path/to/repo1", "/path/to/repo2"],
            "completed_repos": ["/path/to/repo1"],
            "failed_repos": [],
            "current_step": "processing_repo_2",
        },
    },
    # ... more checkpoints
]
```

______________________________________________________________________

#### `resume_workflow`

Resume a workflow from checkpoint.

**Signature:**

```python
async def resume_workflow(
    workflow_id: str,
) -> dict[str, Any]
```

**Parameters:**

- `workflow_id`: Workflow identifier

**Returns:**

```python
{
    "workflow_id": "wf-abc123",
    "status": "running",
    "resumed_at": "2025-01-22T12:40:00Z",
    "remaining_repos": ["/path/to/repo2", "/path/to/repo3"],
    "completed_repos": ["/path/to/repo1"],
    "failed_repos": [],
    "current_step": "processing_repo_2",
    "checkpoint_used": "/path/to/checkpoint.json",
}
```

**Errors:**

- `ValueError`: If checkpoint is not found

______________________________________________________________________

#### `delete_checkpoint`

Delete a workflow checkpoint.

**Signature:**

```python
async def delete_checkpoint(
    workflow_id: str,
) -> dict[str, Any]
```

**Parameters:**

- `workflow_id`: Workflow identifier

**Returns:**

```python
{
    "workflow_id": "wf-abc123",
    "deleted": True,
    "deleted_at": "2025-01-22T12:40:00Z",
}
```

**Errors:**

- `ValueError`: If checkpoint is not found

______________________________________________________________________

### Worker Management Tools

#### `worker_spawn`

Spawn worker instances for task execution.

**Signature:**

```python
async def worker_spawn(
    worker_type: str = "terminal-qwen",
    count: int = 1,
) -> list[str]
```

**Parameters:**

- `worker_type`: Type of worker to spawn. Options:
  - `"terminal-qwen"`: Headless Qwen CLI execution
  - `"terminal-claude"`: Headless Claude Code CLI execution
  - `"container-executor"`: Containerized task execution
- `count`: Number of workers to spawn (1-50). Default: 1

**Returns:**

```python
[
    "term_abc123",
    "term_def456",
    "term_ghi789",
    # ... more worker IDs
]
```

**Errors:**

- `ValueError`: If worker_type is unknown
- `RuntimeError`: If worker fails to start
- `ResourceError`: If system is at capacity (max concurrent workers)

**Example:**

```python
# Spawn 3 Qwen workers
worker_ids = await worker_spawn(worker_type="terminal-qwen", count=3)

# Spawn 5 Claude workers
worker_ids = await worker_spawn(worker_type="terminal-claude", count=5)

# Spawn 2 container workers
worker_ids = await worker_spawn(worker_type="container-executor", count=2)
```

______________________________________________________________________

#### `worker_execute`

Execute task on a specific worker.

**Signature:**

```python
async def worker_execute(
    worker_id: str,
    prompt: str,
    timeout: int = 300,
) -> dict[str, Any]
```

**Parameters:**

- `worker_id`: Worker identifier (from `worker_spawn`)
- `prompt`: Task prompt for AI workers
- `timeout`: Execution timeout in seconds (30-3600). Default: 300

**Returns:**

```python
{
    "worker_id": "term_abc123",
    "status": "completed",  # "pending", "running", "completed", "failed", "timeout", "cancelled"
    "output": "Task completed successfully",
    "error": None,
    "exit_code": 0,
    "duration_seconds": 45.2,
    "metadata": {
        "worker_type": "terminal-qwen",
        "last_output": "Final response",
        "output_lines": 10,
    },
}
```

**Errors:**

- `ValueError`: If worker_id not found
- `TimeoutError`: If task execution exceeds timeout
- `RuntimeError`: If worker fails during execution

**Example:**

```python
# Execute task on specific worker
result = await worker_execute(
    worker_id="term_abc123",
    prompt="Implement a REST API with FastAPI",
    timeout=600,
)
```

______________________________________________________________________

#### `worker_execute_batch`

Execute tasks on multiple workers concurrently.

**Signature:**

```python
async def worker_execute_batch(
    worker_ids: list[str],
    prompts: list[str],
    timeout: int = 300,
) -> dict[str, dict[str, Any]]
```

**Parameters:**

- `worker_ids`: List of worker identifiers
- `prompts`: List of prompts (same length as worker_ids)
- `timeout`: Execution timeout in seconds (30-3600). Default: 300

**Returns:**

```python
{
    "term_abc123": {
        "worker_id": "term_abc123",
        "status": "completed",
        "output": "Task completed",
        "duration_seconds": 42.1,
    },
    "term_def456": {
        "worker_id": "term_def456",
        "status": "completed",
        "output": "Task completed",
        "duration_seconds": 43.8,
    },
    "term_ghi789": {
        "worker_id": "term_ghi789",
        "status": "failed",
        "error": "Task failed",
        "duration_seconds": 12.5,
    },
}
```

**Errors:**

- `ValueError`: If worker_ids and prompts length mismatch
- `ValueError`: If any worker_id not found

**Example:**

```python
# Execute different tasks on multiple workers
results = await worker_execute_batch(
    worker_ids=["term_abc123", "term_def456", "term_ghi789"],
    prompts=[
        "Implement user authentication",
        "Implement database models",
        "Write API documentation",
    ],
)
```

______________________________________________________________________

#### `worker_list`

List all active workers.

**Signature:**

```python
async def worker_list() -> list[dict[str, Any]]
```

**Returns:**

```python
[
    {
        "worker_id": "term_abc123",
        "worker_type": "terminal-qwen",
        "status": "running",
    },
    {
        "worker_id": "term_def456",
        "worker_type": "terminal-claude",
        "status": "completed",
    },
    {
        "worker_id": "container_ghi789",
        "worker_type": "container-executor",
        "status": "running",
    },
]
```

**Example:**

```python
# List all active workers
workers = await worker_list()
```

______________________________________________________________________

#### `worker_monitor`

Monitor status of multiple workers.

**Signature:**

```python
async def worker_monitor(
    worker_ids: list[str],
    interval: float = 1.0,
) -> dict[str, str]
```

**Parameters:**

- `worker_ids`: List of worker identifiers to monitor
- `interval`: Polling interval in seconds. Default: 1.0

**Returns:**

```python
{
    "term_abc123": "running",
    "term_def456": "completed",
    "term_ghi789": "failed",
}
```

**Errors:**

- `ValueError`: If any worker_id not found

**Example:**

```python
# Monitor multiple workers
statuses = await worker_monitor(
    worker_ids=["term_abc123", "term_def456"],
    interval=0.5,
)
```

______________________________________________________________________

#### `worker_collect_results`

Collect results from completed workers.

**Signature:**

```python
async def worker_collect_results(
    worker_ids: list[str] | None = None,
) -> dict[str, dict[str, Any]]
```

**Parameters:**

- `worker_ids` (optional): List of worker identifiers. Default: all workers

**Returns:**

```python
{
    "term_abc123": {
        "worker_id": "term_abc123",
        "status": "completed",
        "output": "Full worker output...",
        "duration_seconds": 45.2,
        "progress": {...},
    },
    "term_def456": {
        "worker_id": "term_def456",
        "status": "completed",
        "output": "Full worker output...",
        "duration_seconds": 43.8,
        "progress": {...},
    },
}
```

**Example:**

```python
# Collect results from specific workers
results = await worker_collect_results(
    worker_ids=["term_abc123", "term_def456"]
)

# Collect results from all workers
results = await worker_collect_results()
```

______________________________________________________________________

#### `worker_close`

Close a specific worker.

**Signature:**

```python
async def worker_close(
    worker_id: str,
) -> dict[str, Any]
```

**Parameters:**

- `worker_id`: Worker identifier to close

**Returns:**

```python
{
    "worker_id": "term_abc123",
    "closed": True,
    "message": "Worker closed successfully",
}
```

**Errors:**

- `ValueError`: If worker_id not found

**Example:**

```python
# Close a specific worker
result = await worker_close(worker_id="term_abc123")
```

______________________________________________________________________

#### `worker_close_all`

Close all active workers.

**Signature:**

```python
async def worker_close_all() -> dict[str, Any]
```

**Returns:**

```python
{
    "closed_count": 5,
    "failed_count": 0,
    "workers_closed": ["term_abc123", "term_def456", "term_ghi789", "container_jkl012", "term_mno345"],
}
```

**Example:**

```python
# Close all workers
result = await worker_close_all()
```

______________________________________________________________________

#### `worker_health`

Get worker system health.

**Signature:**

```python
async def worker_health() -> dict[str, Any]
```

**Returns:**

```python
{
    "status": "healthy",
    "workers_active": 3,
    "max_concurrent": 10,
    "debug_mode": false,
    "debug_monitor_active": false,
    "workers": [
        {
            "worker_id": "term_abc123",
            "worker_type": "terminal-qwen",
            "status": "running",
        },
        {
            "worker_id": "term_def456",
            "worker_type": "terminal-claude",
            "status": "running",
        },
        {
            "worker_id": "container_ghi789",
            "worker_type": "container-executor",
            "status": "running",
        },
    ],
}
```

**Example:**

```python
# Get worker system health
health = await worker_health()
```

### Pool Management Tools

#### `pool_spawn`

Spawn a new worker pool of specified type.

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

- `pool_type`: Type of pool to spawn. Options: "mahavishnu", "session-buddy", "kubernetes"
- `name`: Human-readable pool name
- `min_workers`: Minimum number of workers (1-10)
- `max_workers`: Maximum number of workers (1-100)
- `worker_type`: Worker type. Options: "terminal-qwen", "terminal-claude", "container"

**Returns:**

```python
{
    "pool_id": "mahavishnu_abc123",
    "pool_type": "mahavishnu",
    "name": "local-pool",
    "status": "created",
    "min_workers": 1,
    "max_workers": 10,
}
```

**Errors:**

- `ValueError`: If pool_type is unknown
- `RuntimeError`: If pool fails to start
- `ValueError`: If target worker count outside range [min_workers, max_workers]

**Example:**

```python
# Spawn local Mahavishnu pool
pool = await pool_spawn(
    pool_type="mahavishnu",
    name="local",
    min_workers=2,
    max_workers=5,
)

# Spawn Session-Buddy delegated pool
pool = await pool_spawn(
    pool_type="session-buddy",
    name="delegated",
)
```

______________________________________________________________________

#### `pool_execute`

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

- `pool_id`: Target pool identifier
- `prompt`: Task prompt for workers
- `timeout`: Execution timeout in seconds (30-3600). Default: 300

**Returns:**

```python
{
    "pool_id": "mahavishnu_abc123",
    "worker_id": "worker_xyz789",
    "status": "completed",
    "output": "Task output here...",
    "error": None,
    "duration": 5.2,
}
```

**Errors:**

- `ValueError`: If pool_id not found
- `RuntimeError`: If no workers available in pool

**Example:**

```python
# Execute task on specific pool
result = await pool_execute(
    pool_id="mahavishnu_abc123",
    prompt="Implement a REST API endpoint",
    timeout=300,
)
```

______________________________________________________________________

#### `pool_route_execute`

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

- `prompt`: Task prompt for workers
- `pool_selector`: Pool selection strategy. Options: "round_robin", "least_loaded", "random"
- `timeout`: Execution timeout in seconds (30-3600). Default: 300

**Returns:**

```python
{
    "pool_id": "mahavishnu_abc123",
    "worker_id": "worker_xyz789",
    "status": "completed",
    "output": "Task output here...",
    "error": None,
    "duration": 5.2,
}
```

**Errors:**

- `RuntimeError`: If no pools available
- `ValueError`: If pool_selector is invalid

**Example:**

```python
# Route to least loaded pool
result = await pool_route_execute(
    prompt="Implement API endpoint",
    pool_selector="least_loaded",
)

# Route using round-robin
result = await pool_route_execute(
    prompt="Write tests",
    pool_selector="round_robin",
)
```

______________________________________________________________________

#### `pool_list`

List all active pools.

**Signature:**

```python
async def pool_list() -> list[dict[str, Any]]
```

**Returns:**

```python
[
    {
        "pool_id": "mahavishnu_abc123",
        "pool_type": "mahavishnu",
        "name": "local",
        "status": "running",
        "workers": 5,
        "min_workers": 2,
        "max_workers": 10,
    },
    {
        "pool_id": "session_buddy_def456",
        "pool_type": "session-buddy",
        "name": "delegated",
        "status": "running",
        "workers": 3,
        "min_workers": 3,
        "max_workers": 3,
    },
]
```

**Example:**

```python
# List all active pools
pools = await pool_list()

for pool in pools:
    print(f"{pool['pool_id']}: {pool['status']} ({pool['workers']} workers)")
```

______________________________________________________________________

#### `pool_monitor`

Monitor pool status and metrics.

**Signature:**

```python
async def pool_monitor(
    pool_ids: list[str] | None = None,
) -> dict[str, dict[str, Any]]
```

**Parameters:**

- `pool_ids`: Optional list of pool IDs to monitor. None = all pools

**Returns:**

```python
{
    "mahavishnu_abc123": {
        "memory_count": 15,
        "status": "running",
        "metrics": {
            "active_workers": 5,
            "tasks_completed": 100,
            "tasks_failed": 2,
        },
    },
    "session_buddy_def456": {
        "memory_count": 8,
        "status": "running",
    },
}
```

**Example:**

```python
# Monitor all pools
metrics = await pool_monitor()

# Monitor specific pools
metrics = await pool_monitor(pool_ids=["mahavishnu_abc123"])
```

______________________________________________________________________

#### `pool_scale`

Scale pool to target worker count.

**Signature:**

```python
async def pool_scale(
    pool_id: str,
    target_workers: int,
) -> dict[str, Any]
```

**Parameters:**

- `pool_id`: Pool identifier to scale
- `target_workers`: Target worker count (1-100)

**Returns:**

```python
{
    "pool_id": "mahavishnu_abc123",
    "target_workers": 10,
    "actual_workers": 10,
    "status": "scaled",
}
```

**Errors:**

- `ValueError`: If pool_id not found
- `ValueError`: If target_workers outside [min_workers, max_workers]
- `NotImplementedError`: If pool doesn't support scaling (e.g., SessionBuddyPool)

**Example:**

```python
# Scale pool to 10 workers
result = await pool_scale(
    pool_id="mahavishnu_abc123",
    target_workers=10,
)
```

______________________________________________________________________

#### `pool_close`

Close a specific pool.

**Signature:**

```python
async def pool_close(
    pool_id: str,
) -> dict[str, Any]
```

**Parameters:**

- `pool_id`: Pool identifier to close

**Returns:**

```python
{
    "pool_id": "mahavishnu_abc123",
    "status": "closed",
}
```

**Errors:**

- `ValueError`: If pool_id not found

**Example:**

```python
# Close specific pool
result = await pool_close(pool_id="mahavishnu_abc123")
```

______________________________________________________________________

#### `pool_close_all`

Close all active pools.

**Signature:**

```python
async def pool_close_all() -> dict[str, Any]
```

**Returns:**

```python
{
    "pools_closed": 3,
    "status": "all_closed",
}
```

**Example:**

```python
# Close all pools
result = await pool_close_all()
print(f"Closed {result['pools_closed']} pools")
```

______________________________________________________________________

#### `pool_health`

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
    "pools": [
        {
            "pool_id": "mahavishnu_abc123",
            "pool_type": "mahavishnu",
            "status": "running",
            "workers": 5,
        },
        {
            "pool_id": "session_buddy_def456",
            "pool_type": "session-buddy",
            "status": "running",
            "workers": 3,
        },
    ],
}
```

**Example:**

```python
# Get pool health
health = await pool_health()

print(f"Overall status: {health['status']}")
print(f"Active pools: {health['pools_active']}")

for pool in health["pools"]:
    print(f"  {pool['pool_id']}: {pool['status']} ({pool['workers']} workers)")
```

______________________________________________________________________

#### `pool_search_memory`

Search memory across all pools.

**Signature:**

```python
async def pool_search_memory(
    query: str,
    limit: int = 100,
) -> list[dict[str, Any]]
```

**Parameters:**

- `query`: Search query string
- `limit`: Maximum results to return. Default: 100

**Returns:**

```python
[
    {
        "content": "API implementation code...",
        "metadata": {
            "pool_id": "mahavishnu_abc123",
            "pool_type": "mahavishnu",
            "worker_id": "worker_xyz789",
            "timestamp": 1234567890.0,
        },
    },
    {
        "content": "Test code...",
        "metadata": {
            "pool_id": "session_buddy_def456",
            "pool_type": "session-buddy",
            "timestamp": 1234567890.0,
        },
    },
]
```

**Errors:**

- `RuntimeError`: If search fails

**Example:**

```python
# Search across all pools
results = await pool_search_memory(
    query="API implementation",
    limit=50,
)

for result in results:
    print(f"Pool: {result['metadata']['pool_id']}")
    print(f"Content: {result['content'][:100]}...")
```

______________________________________________________________________


### OpenTelemetry Tools

Tools for ingesting and searching OpenTelemetry traces using Akosha HotStore (DuckDB).

#### `ingest_otel_traces`

Ingest OTel trace log files into HotStore with semantic embeddings.

**Signature:**

```python
async def ingest_otel_traces(
    log_files: list[str],
    batch_size: int | None = None,
) -> dict[str, Any]
```

**Parameters:**

- `log_files` (required): List of log file paths to ingest
- `batch_size` (optional): Batch size for ingestion. Default: 100

**Returns:**

```python
{
    "status": "success",
    "traces_ingested": 127,
    "storage_backend": "duckdb_hotstore",
    "ingestion_time_seconds": 0.45,
    "files_processed": 2,
}
```

**Errors:**

- `FileNotFoundError`: If log file doesn't exist
- `json.JSONDecodeError`: If file is not valid JSON
- `ValueError`: If file is not in expected OTel format
- `RuntimeError`: If embedding generation fails

**Example:**

```python
# Ingest single file
result = await ingest_otel_traces(
    log_files=["/path/to/claude/session.json"],
)

# Ingest multiple files with custom batch size
result = await ingest_otel_traces(
    log_files=[
        "/path/to/claude/session_1.json",
        "/path/to/qwen/session_1.json",
    ],
    batch_size=200,
)

print(f"Ingested {result['traces_ingested']} traces in {result['ingestion_time_seconds']:.2f}s")
```

______________________________________________________________________

#### `search_otel_traces`

Perform semantic search over ingested traces.

**Signature:**

```python
async def search_otel_traces(
    query: str,
    limit: int = 10,
    threshold: float | None = None,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]
```

**Parameters:**

- `query` (required): Natural language search query
- `limit` (optional): Maximum results to return. Default: 10
- `threshold` (optional): Minimum similarity score (0-1). Default: 0.75
- `filters` (optional): Attribute filters (e.g., `{"kind": "CLIENT"}`)

**Returns:**

```python
[
    {
        "trace_id": "trace-abc123",
        "span_id": "span-def456",
        "similarity": 0.892,
        "name": "http.client.request",
        "summary": "HTTP POST request to /api/users endpoint",
        "timestamp": "2025-01-31T14:23:45Z",
        "kind": "CLIENT",
        "status": "OK",
        "duration_ms": 1234,
        "attributes": {
            "http.method": "POST",
            "http.url": "https://api.example.com/users",
        },
    },
    # ... more results
]
```

**Errors:**

- `ValueError`: If query is empty or limit <= 0
- `ValueError`: If threshold not in range [0.0, 1.0]

**Example:**

```python
# Basic search
results = await search_otel_traces(
    query="authentication error when accessing API",
)

# Search with high similarity threshold
results = await search_otel_traces(
    query="memory usage spike",
    threshold=0.80,
)

# Search with filters
results = await search_otel_traces(
    query="database connection",
    filters={
        "kind": "CLIENT",
        "status": "ERROR",
    },
)

# Process results
for result in results:
    print(f"{result['trace_id']}: {result['summary'][:80]}...")
    print(f"  Similarity: {result['similarity']:.3f}")
```

______________________________________________________________________

#### `get_trace_by_id`

Retrieve a specific trace by ID.

**Signature:**

```python
async def get_trace_by_id(
    trace_id: str,
) -> dict[str, Any] | None
```

**Parameters:**

- `trace_id` (required): Trace identifier (hex string)

**Returns:**

```python
{
    "trace_id": "trace-abc123",
    "span_id": "span-def456",
    "parent_span_id": "span-ghi789",  # If nested
    "name": "http.client.request",
    "kind": "CLIENT",
    "status": "OK",
    "start_time": "2025-01-31T14:23:45.123456Z",
    "end_time": "2025-01-31T14:23:46.567890Z",
    "duration_ms": 1444,
    "attributes": {
        "http.method": "POST",
        "http.url": "https://api.example.com/users",
        "http.status_code": 201,
    },
    "events": [
        {
            "time": "2025-01-31T14:23:45.500000Z",
            "name": "connection.opened",
        },
    ],
    "summary": "HTTP POST request to /api/users endpoint",
    "created_at": "2025-01-31T14:23:45Z",
}
```

Returns `None` if trace not found.

**Errors:**

- `ValueError`: If trace_id is empty or invalid

**Example:**

```python
# Get specific trace
trace = await get_trace_by_id(trace_id="abc123def456")

if trace:
    print(f"Trace: {trace['name']}")
    print(f"Duration: {trace['duration_ms']}ms")
    print(f"Status: {trace['status']}")
    print(f"Summary: {trace['summary']}")
else:
    print("Trace not found")
```

______________________________________________________________________

#### `get_otel_statistics`

Get statistics about ingested traces.

**Signature:**

```python
async def get_otel_statistics() -> dict[str, Any]
```

**Parameters:** None

**Returns:**

```python
{
    "total_traces": 12458,
    "total_spans": 45623,
    "unique_names": 234,
    "avg_duration_ms": 234.5,
    "min_duration_ms": 1.2,
    "max_duration_ms": 15234.5,
    "by_status": {
        "OK": 11200,
        "ERROR": 892,
        "UNSET": 366,
    },
    "by_kind": {
        "INTERNAL": 5423,
        "SERVER": 3211,
        "CLIENT": 3456,
        "PRODUCER": 234,
        "CONSUMER": 134,
    },
    "storage_backend": "duckdb_hotstore",
    "database_size_mb": 48.2,
    "index_size_mb": 12.3,
    "cache_hit_rate": 0.85,
}
```

**Example:**

```python
# Get statistics
stats = await get_otel_statistics()

print(f"Total traces: {stats['total_traces']}")
print(f"Average duration: {stats['avg_duration_ms']:.2f}ms")
print(f"Traces by status:")
for status, count in stats['by_status'].items():
    print(f"  {status}: {count}")

# Calculate success rate
success_rate = stats['by_status']['OK'] / stats['total_traces'] * 100
print(f"Success rate: {success_rate:.1f}%")
```

______________________________________________________________________

## Authentication

All MCP tools require authentication via JWT bearer token.

### Token Format

```json
{
  "sub": "user@example.com",
  "name": "John Doe",
  "roles": ["operator"],
  "exp": 1706945696,
  "iat": 1706942096
}
```

### Authorization

- **Admin**: Full access to all tools
- **Operator**: Can trigger/view workflows, list repos, run QC
- **Viewer**: Read-only access (list tools only)

______________________________________________________________________

## Rate Limiting

- **Default**: 100 requests per minute per client
- **Burst capacity**: 20 requests
- **Configurable**: Per-client rate limits

Rate limit headers are included in responses:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1706945696
```

______________________________________________________________________

## Error Handling

All tools use consistent error handling with `ServerPanels`:

```python
try:
    result = await some_operation()
    return result
except FileNotFoundError as e:
    ServerPanels.error(
        title="Configuration Error",
        message=f"Configuration file not found",
        suggestion="Create repos.yaml with repository definitions",
        error_type=type(e).__name__,
    )
    raise
except Exception as e:
    ServerPanels.error(
        title="Unexpected Error",
        message=f"An unexpected error occurred",
        suggestion="Check logs for details",
        error_type=type(e).__name__,
    )
    raise
```

______________________________________________________________________

## Observability

All tools include:

- **Metrics**: Execution time, success/failure counts
- **Tracing**: OpenTelemetry span for each tool call
- **Logging**: Structured logs with correlation IDs

Example span attributes:

```
tool.name: "list_repos"
tool.tag: "backend"
tool.status: "success"
tool.duration_ms: 45
```
