# MCP Server

The MCP (Machine Learning Communication Protocol) server enables integration with AI tools like Claude Desktop.

**Current Status**: Terminal management tools implemented (11,453 lines). Core orchestration tools not yet implemented.

## Starting the Server

```bash
mahavishnu mcp-serve
```

## Implementation Status

### Implemented Tools

**Terminal Management** (11,453 lines of terminal tools):
- `terminal_launch`: Launch terminal sessions
- `terminal_type`: Type commands in terminals
- `terminal_read`: Read terminal output
- `terminal_close`: Close terminal sessions
- `terminal_list`: List active terminals

**Features**:
- Launch 10+ concurrent terminal sessions
- Hot-swappable adapters (iTerm2 <-> mcpretentious)
- Connection pooling for reduced overhead
- iTerm2 profile support
- Command injection and output capture

### Not Yet Implemented

**Core Orchestration Tools**:
- `list_repos`: List repositories with tag filtering
- `trigger_workflow`: Trigger workflow execution
- `get_workflow_status`: Check workflow status
- `cancel_workflow`: Cancel running workflow
- `list_adapters`: List available adapters
- `get_adapter_health`: Get health status for specific adapter

**Quality Control Tools**:
- `run_qc`: Run Crackerjack QC checks on repository
- `get_qc_thresholds`: Get QC threshold configuration
- `set_qc_thresholds`: Set QC threshold configuration

**Session Management Tools**:
- `list_checkpoints`: List Session-Buddy checkpoints
- `resume_workflow`: Resume workflow from checkpoint
- `delete_checkpoint`: Delete workflow checkpoint

See [MCP_TOOLS_SPECIFICATION.md](../MCP_TOOLS_SPECIFICATION.md) for complete tool specifications including parameters, returns, and error handling.

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

## Terminal Management

The terminal management feature is fully implemented and ready to use.

### Quick Start

```yaml
# settings/mahavishnu.yaml
terminal:
  enabled: true
  adapter_preference: "auto"  # Auto-detect iTerm2, fallback to mcpretentious
```

```bash
# Launch 3 Qwen sessions
mahavishnu terminal launch "qwen" --count 3

# Or via MCP tools (when server is running)
await mcp.call_tool("terminal_launch", {"command": "qwen", "count": 3})
```

## Security

When exposing the MCP server externally, ensure:

- Authentication is enabled (JWT with Claude Code, Qwen, or custom provider)
- Network access is restricted
- Requests are properly validated
- Path validation prevents directory traversal

### Authentication

Mahavishnu supports multiple authentication providers:
- Claude Code subscription authentication
- Qwen free service authentication
- Custom JWT tokens

Enable authentication in configuration:

```yaml
auth:
  enabled: true
  algorithm: "HS256"
  expire_minutes: 60
```

Set environment variable:
```bash
export MAHAVISHNU_AUTH_SECRET="your-secret-minimum-32-characters"
```

## Next Steps

1. Implement core orchestration tools (estimated 1 week)
2. Add adapter discovery and health checks
3. Implement QC integration with Crackerjack
4. Add Session-Buddy checkpoint integration

See [UNIFIED_IMPLEMENTATION_STATUS.md](../../UNIFIED_IMPLEMENTATION_STATUS.md) for detailed progress tracking and [TERMINAL_MANAGEMENT.md](../TERMINAL_MANAGEMENT.md) for terminal feature documentation.
