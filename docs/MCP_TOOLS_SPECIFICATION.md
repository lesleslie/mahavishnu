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

### 5. Session Management Tools

Tools for managing Session-Buddy checkpoints and state.

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
