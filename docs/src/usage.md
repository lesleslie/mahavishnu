# Usage

This guide covers how to use Mahavishnu for managing development workflows.

## Basic Commands

### Sweep Command

Perform an AI sweep across repositories with a specific tag:

```bash
mahavishnu sweep --tag agent --adapter langgraph
```

### List Repositories

List all repositories:

```bash
mahavishnu list-repos
```

List repositories with a specific tag:

```bash
mahavishnu list-repos --tag python
```

### Start MCP Server

Start the MCP server to expose tools via mcp-common:

```bash
mahavishnu mcp-serve
```

## Repository Configuration

Create a `repos.yaml` file to define your repositories:

```yaml
repos:
  - name: "my-project"
    package: "my_project"
    path: "/path/to/my-project"
    tags: ["backend", "python"]
    description: "My backend services repository"
    mcp: "native"
```

## Adapter Selection

Mahavishnu supports multiple orchestration engines:

- `langgraph`: For AI agent workflows
- `prefect`: For general workflow orchestration
- `agno`: For experimental AI agent runtime
- `airflow`: Legacy support (migration recommended)
- `crewai`: Deprecated (use LangGraph instead)

## MCP Server Usage

The MCP server exposes tools for repository management and workflow execution:

### Available Tools

- `list_repos`: List repositories with optional filtering
- `trigger_workflow`: Trigger workflow execution
- `get_workflow_status`: Get status of a workflow execution
- `cancel_workflow`: Cancel a running workflow
- `list_adapters`: List available adapters
- `get_health`: Get overall health status

### Example MCP Client Usage

```python
from mcp.client import Client

async def example():
    async with Client("ws://localhost:3000") as client:
        # List repositories
        repos = await client.call("tools/list_repos", {"tag": "python"})

        # Trigger workflow
        result = await client.call("tools/trigger_workflow", {
            "adapter": "langgraph",
            "task_type": "code_sweep",
            "tag": "agent"
        })
```

## Parallel Execution

Mahavishnu executes workflows in parallel across repositories with configurable concurrency:

```bash
# Set maximum concurrent workflows (default is 10)
export MAHAVISHNU_MAX_CONCURRENT_WORKFLOWS=20

mahavishnu sweep --tag backend --adapter prefect
```

## Quality Control Integration

With QC enabled, workflows will run quality checks before and after execution:

```bash
# Enable QC checks
export MAHAVISHNU_QC_ENABLED=true

mahavishnu sweep --tag python --adapter langgraph
``
```
