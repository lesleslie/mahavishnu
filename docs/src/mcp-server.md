# MCP Server

The MCP (Machine Learning Communication Protocol) server enables integration with AI tools like Claude Desktop.

## Overview

The MCP server exposes Mahavishnu functionality through standardized MCP tools, allowing AI assistants to interact with your development workflows.

## Starting the Server

```bash
mahavishnu mcp-serve
```

## Available Tools

### list_repos

List repositories with optional filtering:

```json
{
  "name": "list_repos",
  "arguments": {
    "tag": "string | null",
    "limit": "integer | null",
    "offset": "integer | null"
  }
}
```

### trigger_workflow

Trigger workflow execution:

```json
{
  "name": "trigger_workflow",
  "arguments": {
    "adapter": "string",
    "task_type": "string",
    "params": "object",
    "tag": "string | null",
    "repos": "string[] | null",
    "timeout": "integer | null"
  }
}
```

### get_workflow_status

Get status of a workflow execution:

```json
{
  "name": "get_workflow_status",
  "arguments": {
    "workflow_id": "string"
  }
}
```

### cancel_workflow

Cancel a running workflow:

```json
{
  "name": "cancel_workflow",
  "arguments": {
    "workflow_id": "string"
  }
}
```

### list_adapters

List available adapters:

```json
{
  "name": "list_adapters",
  "arguments": {}
}
```

### get_health

Get overall health status:

```json
{
  "name": "get_health",
  "arguments": {}
}
```

## Configuration

Configure the MCP server in your settings:

```yaml
mcp:
  enabled: true
  host: "127.0.0.1"
  port: 3000
  timeout: 30
  max_connections: 100
```

## Security

When exposing the MCP server externally, ensure:

- Authentication is enabled
- Network access is restricted
- Requests are properly validated
- Rate limiting is configured