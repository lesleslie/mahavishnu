# API Reference

This section provides reference documentation for the Mahavishnu API.

## Core Classes

### MahavishnuApp

The main application class that manages configuration, repository loading, and adapter initialization.

#### Methods

- `__init__(config: MahavishnuSettings | None = None)` - Initialize the application
- `get_repos(tag: str | None = None) -> list[str]` - Get repository paths based on tag
- `get_all_repos() -> list[dict[str, Any]]` - Get all repositories with full metadata
- `get_all_repo_paths() -> list[str]` - Get all repository paths
- `is_healthy() -> bool` - Check if application is healthy
- `get_active_workflows() -> list[str]` - Get list of active workflow IDs
- `execute_workflow(task: dict[str, Any], adapter_name: str, repos: list[str] | None = None) -> dict[str, Any]` - Execute a workflow using the specified adapter

### MahavishnuSettings

Configuration class extending MCPServerSettings with application-specific settings.

#### Fields

- `repos_path: str` - Path to repos.yaml repository manifest
- `max_concurrent_workflows: int` - Maximum number of concurrent workflows (1-100)
- `airflow_enabled: bool` - Enable Airflow adapter
- `crewai_enabled: bool` - Enable CrewAI adapter
- `langgraph_enabled: bool` - Enable LangGraph adapter
- `agno_enabled: bool` - Enable Agno adapter
- `qc_enabled: bool` - Enable Crackerjack QC
- `qc_min_score: int` - Minimum QC score threshold (0-100)
- `session_enabled: bool` - Enable Session-Buddy checkpoints
- `checkpoint_interval: int` - Checkpoint interval in seconds (10-600)
- `retry_max_attempts: int` - Maximum retry attempts (1-10)
- `retry_base_delay: float` - Base retry delay in seconds (0.1-60.0)
- `circuit_breaker_threshold: int` - Consecutive failures before circuit opens (1-100)
- `timeout_per_repo: int` - Timeout per repo in seconds (30-3600)
- `metrics_enabled: bool` - Enable OpenTelemetry metrics
- `tracing_enabled: bool` - Enable distributed tracing
- `otlp_endpoint: str` - OTLP endpoint for metrics/traces
- `auth_enabled: bool` - Enable JWT authentication
- `auth_secret: str | None` - JWT secret (must be set via environment if auth enabled)
- `auth_algorithm: str` - JWT algorithm (HS256 or RS256)
- `auth_expire_minutes: int` - JWT token expiration in minutes (5-1440)

## Adapters

### OrchestratorAdapter

Base class for orchestrator adapters.

#### Abstract Methods

- `async def execute(self, task: Dict[str, Any], repos: List[str]) -> Dict[str, Any]` - Execute a task using the orchestrator engine asynchronously
- `async def get_health(self) -> Dict[str, Any]` - Get adapter health status asynchronously

## CLI Commands

### sweep

Perform an AI sweep across repositories with a specific tag.

```bash
mahavishnu sweep --tag TAG --adapter ADAPTER
```

### list-repos

List repositories in repos.yaml.

```bash
mahavishnu list-repos [--tag TAG]
```

### mcp-serve

Start the MCP server to expose tools via mcp-common.

```bash
mahavishnu mcp-serve
```

## MCP Server Tools

### list_repos

List repositories with optional filtering and pagination.

### trigger_workflow

Trigger workflow execution.

### get_workflow_status

Get status of a workflow execution.

### cancel_workflow

Cancel a running workflow.

### list_adapters

List available adapters.

### get_health

Get overall health status of the system.