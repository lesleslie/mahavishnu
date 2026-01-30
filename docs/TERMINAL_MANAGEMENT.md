# Terminal Management

Mahavishnu provides terminal session management capabilities for launching, controlling, and capturing output from multiple terminal sessions concurrently.

## Features

- **Multi-session management**: Launch and control 10+ concurrent terminal sessions
- **Command injection**: Send commands to terminal sessions
- **Output capture**: Retrieve terminal output (with line limits)
- **Session lifecycle**: Launch, list, and close sessions
- **High concurrency**: Semaphore-based resource management
- **MCP integration**: Full support via MCP tools
- **CLI interface**: Command-line tools for terminal operations
- **Hot-swappable adapters**: Switch terminal backends without restart (Phase 4)
- **Connection pooling**: Reuse iTerm2 WebSocket connections (Phase 5)
- **Profile selection**: Use custom iTerm2 profiles per session (Phase 6)

## Configuration

Enable terminal management in `settings/mahavishnu.yaml`:

```yaml
terminal:
  enabled: true
  default_columns: 120
  default_rows: 40
  capture_lines: 100
  poll_interval: 0.5
  max_concurrent_sessions: 20
  adapter_preference: "auto"  # Options: "auto", "iterm2", "mcpretentious"
```

### Adapter Options

**Auto-Detection (default: `"auto"`):**

- Automatically detects and uses iTerm2 if available (requires iTerm2 running)
- Falls back to mcpretentious if iTerm2 is not available

**iTerm2 Adapter (`"iterm2"`):**

- Uses native iTerm2 Python API via WebSocket
- Requires iTerm2 to be running with Python API enabled:
  - iTerm2 → Preferences → General → Magic → Enable Python API
- Install: `pip install iterm2`
- Provides native iTerm2 integration with tabs and windows

**mcpretentious Adapter (`"mcpretentious"`):**

- Uses mcpretentious MCP server for PTY-based terminal management
- Works with any terminal (not iTerm2-specific)
- Started on-demand by Mahavishnu when needed
- No additional installation required (uses uvx)

### Advanced Configuration (Optional)

**Connection Pooling (iTerm2):**

```yaml
terminal:
  enabled: true
  adapter_preference: "iterm2"
  iterm2_pooling_enabled: true  # Enable connection pooling
  iterm2_pool_max_size: 3        # Max pooled connections
  iterm2_pool_idle_timeout: 300  # Close idle connections after 5 minutes
```

**Profile Selection (iTerm2):**

```yaml
terminal:
  enabled: true
  adapter_preference: "iterm2"
  iterm2_default_profile: "My Profile"  # Default profile for all sessions
```

**Configuration Benefits:**

- **Pooling**: Reduces connection overhead by reusing WebSocket connections
- **Profiles**: Customize appearance, color schemes, and behavior per session
- **Auto-detection**: Seamlessly falls back if iTerm2 unavailable

## CLI Usage

### Launch Sessions

```bash
# Launch single Qwen session
mahavishnu terminal launch "qwen" --count 1

# Launch multiple sessions
mahavishnu terminal launch "qwen" --count 5 --columns 120 --rows 40
```

### List Sessions

```bash
mahavishnu terminal list
```

### Send Commands

```bash
# Get session ID from list command
SESSION_ID="term_123"

# Send command
mahavishnu terminal send $SESSION_ID "what is 2+2?"
```

### Capture Output

```bash
# Capture output (default 100 lines)
mahavishnu terminal capture $SESSION_ID

# Capture specific number of lines
mahavishnu terminal capture $SESSION_ID --lines 50
```

### Close Sessions

```bash
# Close specific session
mahavishnu terminal close term_123

# Close all sessions
mahavishnu terminal close all
```

## MCP Tool Usage

When the Mahavishnu MCP server is running with terminal management enabled, the following tools are available:

### `terminal_launch`

Launch terminal sessions running a command.

**Parameters:**

- `command` (str): Command to run in each terminal
- `count` (int): Number of sessions to launch (default: 1)
- `columns` (int): Terminal width in characters (default: 120)
- `rows` (int): Terminal height in lines (default: 40)

**Returns:** List of session IDs

**Example:**

```python
session_ids = await mcp.call_tool("terminal_launch", {
    "command": "qwen",
    "count": 3
})
```

### `terminal_send`

Send command to a terminal session.

**Parameters:**

- `session_id` (str): Terminal session ID
- `command` (str): Command to send

**Example:**

```python
await mcp.call_tool("terminal_send", {
    "session_id": "term_123",
    "command": "hello world"
})
```

### `terminal_capture`

Capture output from a terminal session.

**Parameters:**

- `session_id` (str): Terminal session ID
- `lines` (int | None): Number of lines to capture (default: 100, None for all)

**Returns:** Terminal output as string

**Example:**

```python
output = await mcp.call_tool("terminal_capture", {
    "session_id": "term_123",
    "lines": 50
})
```

### `terminal_capture_all`

Capture output from multiple terminal sessions concurrently.

**Parameters:**

- `session_ids` (list[str]): List of session IDs
- `lines` (int | None): Number of lines to capture per session

**Returns:** Dictionary mapping session_id -> output

**Example:**

```python
outputs = await mcp.call_tool("terminal_capture_all", {
    "session_ids": ["term_1", "term_2", "term_3"],
    "lines": 50
})
```

### `terminal_list`

List all active terminal sessions.

**Returns:** List of session information dictionaries

**Example:**

```python
sessions = await mcp.call_tool("terminal_list", {})
```

### `terminal_close`

Close a terminal session.

**Parameters:**

- `session_id` (str): Terminal session ID to close

**Example:**

```python
await mcp.call_tool("terminal_close", {
    "session_id": "term_123"
})
```

### `terminal_close_all`

Close all terminal sessions.

**Returns:** Dictionary with count of closed sessions

**Example:**

```python
result = await mcp.call_tool("terminal_close_all", {})
```

## Advanced MCP Tool Usage (Phases 4-6)

### `terminal_switch_adapter`

Hot-swap to a different terminal adapter without restart.

**Parameters:**

- `adapter_name` (str): Name of adapter to switch to ("iterm2" or "mcpretentious")
- `migrate_sessions` (bool): If True, attempt to migrate existing sessions (experimental)

**Returns:** Dictionary with switch result

**Example:**

```python
# Switch to iTerm2 adapter
result = await mcp.call_tool("terminal_switch_adapter", {
    "adapter_name": "iterm2",
    "migrate_sessions": False
})

# Check result
if result["status"] == "success":
    print(f"Switched from {result['previous_adapter']} to {result['new_adapter']}")
```

### `terminal_current_adapter`

Get information about the current terminal adapter.

**Returns:** Dictionary with adapter name and switch history

**Example:**

```python
info = await mcp.call_tool("terminal_current_adapter", {})
print(f"Current adapter: {info['adapter']}")
print(f"Switch history: {info['history']}")
```

### `terminal_list_adapters`

List all available terminal adapters and their status.

**Returns:** Dictionary with available adapters

**Example:**

```python
adapters = await mcp.call_tool("terminal_list_adapters", {})
for name, info in adapters['adapters'].items():
    print(f"{name}: {info['status']} - {info['description']}")
```

### `terminal_list_profiles` (iTerm2 only)

List available iTerm2 profiles (requires iTerm2 adapter).

**Returns:** Dictionary with list of profile names

**Example:**

```python
profiles = await mcp.call_tool("terminal_list_profiles", {})
if profiles["status"] == "success":
    print(f"Available profiles: {profiles['profiles']}")
```

### `terminal_launch_with_profile` (iTerm2 only)

Launch terminal sessions with a specific iTerm2 profile.

**Parameters:**

- `command` (str): Command to run in each terminal
- `profile_name` (str): iTerm2 profile name to use
- `count` (int): Number of sessions to launch (default: 1)
- `columns` (int): Terminal width in characters (default: 120)
- `rows` (int): Terminal height in lines (default: 40)

**Returns:** List of session IDs

**Example:**

```python
# Launch with custom profile
session_ids = await mcp.call_tool("terminal_launch_with_profile", {
    "command": "qwen",
    "profile_name": "My Custom Profile",
    "count": 3
})
```

## Python API Usage

### Direct TerminalManager

```python
from mahavishnu.core import MahavishnuApp
import asyncio

async def main():
    app = MahavishnuApp()

    if app.terminal_manager:
        # Launch 3 Qwen sessions
        session_ids = await app.terminal_manager.launch_sessions(
            "qwen",
            count=3,
            columns=120,
            rows=40
        )

        # Send different prompts to each
        prompts = [
            "Explain recursion",
            "What is async/await?",
            "Describe decorators"
        ]

        for session_id, prompt in zip(session_ids, prompts):
            await app.terminal_manager.send_command(session_id, prompt)

        # Wait for responses
        await asyncio.sleep(5)

        # Capture all outputs concurrently
        outputs = await app.terminal_manager.capture_all_outputs(
            session_ids,
            lines=50
        )

        # Process results
        for session_id, output in outputs.items():
            print(f"Session {session_id}:")
            print(output[:100] + "...")

        # Cleanup
        await app.terminal_manager.close_all(session_ids)

asyncio.run(main())
```

### Using TerminalSession

```python
from mahavishnu.terminal import TerminalSession

async def interactive_session(session_id: str, adapter):
    """Interactive terminal session."""
    session = TerminalSession(session_id, "qwen", adapter)

    try:
        while True:
            prompt = input("You: ")
            await session.send(prompt)

            # Wait for response
            await asyncio.sleep(2)

            # Read output
            output = await session.read(lines=50)
            print(f"Qwen: {output}")
    finally:
        await session.close()
```

## Requirements

- Python 3.10+
- uvx (for running mcpretentious)
- mcpretentious package (auto-installed via uvx)

## Architecture

The terminal management system uses a layered architecture:

1. **Adapter Interface** (`TerminalAdapter`): Abstract interface for different backends
1. **mcpretentious Adapter** (`McpretentiousAdapter`): Communicates with mcpretentious MCP server
1. **Terminal Manager** (`TerminalManager`): High-level orchestration with concurrency control
1. **MCP Tools**: 7 tools for Claude Code integration
1. **CLI Commands**: User-friendly command-line interface

## Concurrency Management

The terminal manager uses semaphores to limit concurrent sessions and prevent resource exhaustion:

- Default: 20 concurrent sessions (configurable via `max_concurrent_sessions`)
- Batch operations: Launches 5 sessions at a time for better resource management
- Automatic cleanup: Sessions are properly closed on shutdown

## Error Handling

The terminal management system includes comprehensive error handling:

- `TerminalError`: Base exception for terminal operations
- `SessionNotFound`: Raised when operating on non-existent session
- Graceful degradation: Falls back to alternative adapters if preferred adapter unavailable
- Resource cleanup: Ensures sessions are closed even on errors

## Troubleshooting

### "mcpretentious server not configured"

Ensure uvx is installed:

```bash
pip install uvx
```

### "Failed to start mcpretentious server"

The mcpretentious package will be auto-installed by uvx on first use. If it fails, install manually:

```bash
uvx --from mcpretentious mcpretentious
```

### High memory usage with many sessions

Reduce `max_concurrent_sessions` in configuration:

```yaml
terminal:
  max_concurrent_sessions: 10
  capture_lines: 50
```

### Sessions not closing properly

Use `mahavishnu terminal close all` to force cleanup. The MCP server also includes automatic cleanup on shutdown.

## Future Enhancements

Planned features for future releases:

1. **iTerm2 Adapter**: Native iTerm2 integration with WebSocket streaming
1. **Session Persistence**: Save/restore terminal sessions
1. **Output Filtering**: Filter output by patterns or regex
1. **Session Templates**: Predefined session configurations
1. **Multi-Host Support**: Launch sessions on remote machines
1. **Output Parsing**: Structured output extraction

## See Also

- [MCP Tools Specification](./MCP_TOOLS_SPECIFICATION.md)
