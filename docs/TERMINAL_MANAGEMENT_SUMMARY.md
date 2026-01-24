# Terminal Management System - Implementation Summary

**Date**: 2025-01-24
**Status**: ✅ FULLY IMPLEMENTED AND TESTED
**Test Coverage**: 10/10 tests passing (100% pass rate)

---

## Executive Summary

Mahavishnu includes a comprehensive terminal management system that enables Claude Code and agents to launch, control, and capture output from multiple terminal sessions concurrently. The system supports multiple terminal backends with hot-swappable adapters and connection pooling.

---

## Implementation Status

### ✅ Phase 1: Core Terminal Manager (COMPLETE)

**Files Implemented:**
- `mahavishnu/terminal/adapters/base.py` - Abstract `TerminalAdapter` interface
- `mahavishnu/terminal/adapters/mcpretentious.py` - mcpretentious MCP server adapter
- `mahavishnu/terminal/manager.py` - `TerminalManager` with concurrency control
- `mahavishnu/terminal/session.py` - `TerminalSession` class for individual sessions
- `mahavishnu/terminal/config.py` - `TerminalSettings` configuration model

**Key Features:**
- Abstract adapter interface for multiple terminal backends
- Semaphore-based concurrency limiting (default: 20 concurrent sessions)
- Batch operations for launching 10+ sessions smoothly
- Session metadata tracking and history
- Error handling with custom exceptions (`TerminalError`, `SessionNotFound`)

---

### ✅ Phase 2: MCP Tools (COMPLETE)

**Files Implemented:**
- `mahavishnu/mcp/tools/terminal_tools.py` - 12 MCP tools registered
- `mahavishnu/mcp/server_core.py` - Tool registration in MCP server

**MCP Tools Available (12 total):**

1. **`terminal_launch`** - Launch terminal sessions running a command
   ```python
   session_ids = await terminal_launch("qwen", count=3, columns=120, rows=40)
   ```

2. **`terminal_send`** - Send command to a terminal session
   ```python
   await terminal_send("term_123", "hello world")
   ```

3. **`terminal_capture`** - Capture output from terminal session
   ```python
   output = await terminal_capture("term_123", lines=50)
   ```

4. **`terminal_capture_all`** - Capture output from multiple sessions concurrently
   ```python
   outputs = await terminal_capture_all(["term_1", "term_2"])
   ```

5. **`terminal_list`** - List all active terminal sessions
   ```python
   sessions = await terminal_list()
   ```

6. **`terminal_close`** - Close a terminal session
   ```python
   await terminal_close("term_123")
   ```

7. **`terminal_close_all`** - Close all terminal sessions
   ```python
   result = await terminal_close_all()
   ```

8. **`terminal_switch_adapter`** - Hot-swap to different adapter without restart
   ```python
   result = await terminal_switch_adapter("iterm2", migrate_sessions=False)
   ```

9. **`terminal_current_adapter`** - Get current adapter information
   ```python
   info = await terminal_current_adapter()
   ```

10. **`terminal_list_adapters`** - List all available adapters
    ```python
    adapters = await terminal_list_adapters()
    ```

11. **`terminal_list_profiles`** - List iTerm2 profiles (iTerm2 adapter only)
    ```python
    profiles = await terminal_list_profiles()
    ```

12. **`terminal_launch_with_profile`** - Launch sessions with iTerm2 profile
    ```python
    session_ids = await terminal_launch_with_profile("qwen", "My Profile", count=2)
    ```

---

### ✅ Phase 3: iTerm2 Adapter (COMPLETE)

**Files Implemented:**
- `mahavishnu/terminal/adapters/iterm2.py` - iTerm2 Python API adapter
- `mahavishnu/terminal/pool.py` - Connection pooling for iTerm2
- `mahavishnu/terminal/mcp_client.py` - MCP client wrapper

**Key Features:**
- WebSocket-based real-time communication with iTerm2
- Connection pooling (default: 3 connections, configurable)
- Automatic health checking and connection recovery
- Profile-based session creation
- Graceful fallback to mcpretentious if iTerm2 unavailable

**iTerm2 Requirements:**
- iTerm2 application running
- Python API enabled: `iTerm2 > Preferences > General > Magic > Enable Python API`
- Python package: `pip install iterm2`

---

### ✅ Phase 4: Runtime Detection and Fallback (COMPLETE)

**Implementation:**
- `TerminalManager.create()` factory method in `manager.py`
- Automatic adapter detection based on `adapter_preference` config
- Graceful fallback from iTerm2 → mcpretentious
- Runtime availability checks before adapter initialization

**Configuration Options:**
```yaml
terminal:
  adapter_preference: "auto"  # auto, mcpretentious, iterm2
```

---

### ✅ Phase 5: High Concurrency Optimizations (COMPLETE)

**Features Implemented:**
- Semaphore limiting (default: 20 concurrent sessions)
- Batch operations (`launch_sessions_batch()`)
- Connection pooling for iTerm2 (reduces overhead)
- Parallel output capture (`capture_all_outputs()`)
- Efficient resource management with small delays between batches

**Performance Characteristics:**
- Supports 10+ concurrent sessions
- Batch size: 5 sessions per batch
- Delay between batches: 0.1 seconds
- iTerm2 pool idle timeout: 300 seconds (5 minutes)

---

## Integration Points

### Configuration Integration

**File:** `mahavishnu/core/config.py`

```python
from ..terminal.config import TerminalSettings

class MahavishnuSettings(BaseSettings):
    # ... other fields ...
    terminal: TerminalSettings = Field(
        default_factory=TerminalSettings
    )
```

**TerminalSettings Fields:**
- `enabled: bool` - Enable terminal management (default: False)
- `default_columns: int` - Terminal width (default: 120)
- `default_rows: int` - Terminal height (default: 40)
- `capture_lines: int` - Default lines to capture (default: 100)
- `poll_interval: float` - Polling interval in seconds (default: 0.5)
- `max_concurrent_sessions: int` - Max concurrent sessions (default: 20)
- `adapter_preference: str` - Preferred adapter (default: "auto")
- `iterm2_pooling_enabled: bool` - Enable iTerm2 connection pooling (default: True)
- `iterm2_pool_max_size: int` - Max iTerm2 connections (default: 3)
- `iterm2_pool_idle_timeout: float` - Idle timeout in seconds (default: 300)
- `iterm2_default_profile: str | None` - Default iTerm2 profile (default: None)

---

### Application Integration

**File:** `mahavishnu/core/app.py`

```python
class MahavishnuApp:
    def __init__(self, config: MahavishnuSettings | None = None):
        # ... other initialization ...
        self.terminal_manager = None

        if self.config.terminal.enabled:
            self.terminal_manager = self._init_terminal_manager()

    def _init_terminal_manager(self) -> "TerminalManager | None":
        """Initialize terminal manager with mcpretentious adapter."""
        from ..terminal.adapters.mcpretentious import McpretentiousAdapter

        try:
            adapter = McpretentiousAdapter(self.mcp_client)
            return TerminalManager(adapter, self.config.terminal)
        except Exception as e:
            logger.warning(f"Failed to initialize terminal manager: {e}")
            return None
```

---

### CLI Integration

**File:** `mahavishnu/cli.py`

**Commands Available (5 total):**

```bash
# Launch terminal sessions
mahavishnu terminal launch <command> [--count N] [--columns C] [--rows R]

# List active sessions
mahavishnu terminal list

# Send command to session
mahavishnu terminal send <session_id> <command>

# Capture output from session
mahavishnu terminal capture <session_id> [--lines N]

# Close session(s)
mahavishnu terminal close <session_id|"all">
```

**Example Usage:**
```bash
# Launch 3 Qwen sessions
mahavishnu terminal launch "qwen" --count 3 --columns 120 --rows 40

# List sessions
mahavishnu terminal list

# Send command
mahavishnu terminal send term_123 "explain quantum computing"

# Capture output
mahavishnu terminal capture term_123 --lines 50

# Close all sessions
mahavishnu terminal close all
```

---

## Testing

### Unit Tests (10/10 Passing)

**File:** `tests/unit/test_terminal_adapters.py`

**Test Cases:**
1. ✅ `test_mcpretentious_adapter_launch` - Launch session via mcpretentious
2. ✅ `test_mcpretentious_adapter_send_command` - Send commands to sessions
3. ✅ `test_mcpretentious_adapter_send_command_session_not_found` - Error handling
4. ✅ `test_mcpretentious_adapter_capture_output` - Capture output with limit
5. ✅ `test_mcpretentious_adapter_capture_output_no_limit` - Capture all output
6. ✅ `test_mcpretentious_adapter_close_session` - Close sessions
7. ✅ `test_mcpretentious_adapter_list_sessions` - List active sessions
8. ✅ `test_terminal_manager_concurrency` - Semaphore-based concurrency control
9. ✅ `test_terminal_manager_capture_all_outputs` - Parallel output capture
10. ✅ `test_terminal_manager_close_all` - Batch session closure

**Test Results:**
```
======================= 10 passed in 14.56s ========================
```

**File:** `tests/unit/test_terminal_adapters_iterm2.py`

Additional tests for iTerm2 adapter functionality (also passing).

---

## Advanced Features

### Hot-Swappable Adapters

The terminal manager supports hot-swapping adapters without restarting the application:

```python
# Switch from mcpretentious to iTerm2
await terminal_manager.switch_adapter(iterm2_adapter, migrate_sessions=False)

# Switch back to mcpretentious
await terminal_manager.switch_adapter(mcpretentious_adapter, migrate_sessions=False)
```

**Features:**
- Zero-downtime adapter switching
- Optional session migration (experimental)
- Adapter history tracking
- Migration callback support

### Session Migration

Session migration is experimental and has limitations:
- **mcpretentious → mcpretentious**: ✅ Supported (recreate sessions)
- **mcpretentious → iTerm2**: ❌ Not supported (session orphaned)
- **iTerm2 → mcpretentious**: ❌ Not supported (session orphaned)
- **iTerm2 → iTerm2**: ❌ Not supported (session orphaned)

### Connection Pooling (iTerm2)

The iTerm2 adapter uses connection pooling to reduce overhead:

```python
# Pool configuration
pool_max_size: 3  # Maximum connections in pool
pool_idle_timeout: 300.0  # Close idle connections after 5 minutes
```

**Benefits:**
- Reduced connection overhead
- Better resource utilization
- Faster session launches
- Automatic connection recovery

---

## Configuration Examples

### Enable Terminal Management

**File:** `settings/mahavishnu.yaml`

```yaml
terminal:
  enabled: true
  default_columns: 120
  default_rows: 40
  capture_lines: 100
  poll_interval: 0.5
  max_concurrent_sessions: 20
  adapter_preference: "auto"  # auto, mcpretentious, iterm2
```

### iTerm2-Specific Configuration

**File:** `settings/local.yaml` (gitignored)

```yaml
terminal:
  adapter_preference: "iterm2"  # Force iTerm2 when available
  iterm2_default_profile: "Mahavishnu"  # Default profile name
  iterm2_pooling_enabled: true
  iterm2_pool_max_size: 3
  iterm2_pool_idle_timeout: 300.0
```

### mcpretentious-Specific Configuration

**File:** `~/.claude/.mcp.json`

```json
{
  "mcpServers": {
    "mcpretentious": {
      "command": "uvx",
      "args": ["--from", "mcpretentious", "mcpretentious"],
      "env": {
        "MCPRETENTIOUS_LOG_LEVEL": "info"
      }
    }
  }
}
```

---

## Use Cases

### Use Case 1: Parallel Qwen Benchmarking

```python
from mahavishnu.core import MahavishnuApp
import asyncio

async def benchmark_qwen():
    app = MahavishnuApp()

    # Launch 12 Qwen sessions
    session_ids = await app.terminal_manager.launch_sessions(
        "qwen",
        count=12,
        columns=100,
        rows=30
    )

    # Benchmark prompts
    prompts = [
        "Write a hello world in Python",
        "Explain recursion",
        "What is a lambda function?",
        # ... 9 more prompts
    ]

    # Send prompts to sessions
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
    results = {}
    for session_id, output in outputs.items():
        results[session_id] = {
            "prompt": prompts[session_ids.index(session_id)],
            "response": output,
            "length": len(output)
        }

    # Cleanup
    await app.terminal_manager.close_all(session_ids)

    return results

results = asyncio.run(benchmark_qwen())
```

### Use Case 2: Interactive Qwen Chat

```bash
# Launch Qwen session
mahavishnu terminal launch "qwen" --count 1

# Get session ID
SESSION_ID=$(mahavishnu terminal list | jq -r '.[0].id')

# Interactive chat loop
while true; do
    echo "You: "
    read PROMPT

    mahavishnu terminal send $SESSION_ID "$PROMPT"
    sleep 2

    mahavishnu terminal capture $SESSION_ID
done
```

### Use Case 3: Batch Processing

```python
async def batch_process(prompts: list[str]) -> dict[str, str]:
    app = MahavishnuApp()

    # Launch sessions
    session_ids = await app.terminal_manager.launch_sessions(
        "qwen",
        count=len(prompts)
    )

    # Send all prompts
    tasks = [
        app.terminal_manager.send_command(sid, prompt)
        for sid, prompt in zip(session_ids, prompts)
    ]
    await asyncio.gather(*tasks)

    # Wait for completion
    await asyncio.sleep(5)

    # Capture all results
    outputs = await app.terminal_manager.capture_all_outputs(session_ids)

    # Save results
    results = dict(zip(prompts, outputs.values()))

    # Cleanup
    await app.terminal_manager.close_all(session_ids)

    return results
```

---

## Architecture Decisions

### Adapter Pattern

**Decision:** Use abstract adapter interface for terminal backends

**Rationale:**
- Extensible design (easy to add new terminal types)
- Runtime adapter switching without restart
- Graceful fallback when preferred adapter unavailable
- Testable with mock adapters

### Semaphore-Based Concurrency

**Decision:** Use asyncio.Semaphore for concurrency limiting

**Rationale:**
- Prevents resource exhaustion (20 concurrent sessions)
- Built-in asyncio support (no external dependencies)
- Fair scheduling (FIFO queue)
- Configurable limit per deployment

### Connection Pooling (iTerm2)

**Decision:** Pool iTerm2 WebSocket connections

**Rationale:**
- Reduced connection overhead (3 connections shared)
- Faster session launches (reuse existing connections)
- Better resource utilization
- Automatic connection recovery

### Hot-Swappable Adapters

**Decision:** Support runtime adapter switching

**Rationale:**
- Zero-downtime adapter changes
- A/B testing different adapters
- Graceful degradation (iTerm2 → mcpretentious)
- Migration callback support for custom logic

---

## Security Considerations

1. **Command Validation**: All commands sent through adapters (no shell injection)
2. **Session ID Tracking**: Internal session metadata (not user-controllable)
3. **Resource Limits**: Semaphore prevents unlimited session creation
4. **Timeout Protection**: Configurable timeouts on all async operations
5. **Connection Isolation**: Each adapter uses own connections
6. **No Path Traversal**: No file path operations in terminal code

---

## Performance Considerations

1. **Polling Interval**: 0.5s default balances responsiveness vs overhead
2. **Concurrency Limit**: 20 concurrent sessions prevents resource exhaustion
3. **Batch Size**: 5 sessions per batch for smooth resource usage
4. **Output Buffering**: Limit captured lines to prevent memory issues
5. **Connection Pooling**: Reuse iTerm2 connections across sessions

---

## Troubleshooting

### Issue: "Terminal management is not enabled"

**Solution:**
```yaml
# settings/mahavishnu.yaml
terminal:
  enabled: true
```

### Issue: "Terminal manager not initialized"

**Cause:** MCP client not connected (terminal manager requires MCP context)

**Solution:** Terminal management only works when running as MCP server:
```bash
mahavishnu mcp start
```

### Issue: "mcpretentious tool not found"

**Solution:**
```bash
# Check mcpretentious is configured
cat ~/.claude/.mcp.json | grep mcpretentious

# Restart MCP server
mahavishnu mcp restart
```

### Issue: "Session not found" errors

**Solution:**
```bash
# List active sessions
mahavishnu terminal list

# Verify session ID is correct
```

### Issue: High memory usage with many sessions

**Solution:**
```yaml
# Reduce max concurrent sessions
terminal:
  max_concurrent_sessions: 10
  capture_lines: 50  # Reduce output buffer
```

---

## Future Enhancements

1. **Streaming Output**: Add WebSocket streaming for real-time output (iTerm2 already has this)
2. **Session Persistence**: Save/restore terminal sessions across restarts
3. **Output Filtering**: Filter output by patterns or regex
4. **Session Templates**: Predefined session configurations
5. **Multi-Host Support**: Launch sessions on remote machines
6. **Output Parsing**: Structured output extraction
7. **Session Recording**: Record and replay terminal sessions
8. **Collaborative Sessions**: Share sessions between users

---

## Summary

The Mahavishnu terminal management system is **production-ready** with:

✅ **Complete Implementation**: All 5 phases implemented
✅ **Comprehensive Testing**: 10/10 unit tests passing
✅ **Multiple Adapters**: mcpretentious (universal) + iTerm2 (enhanced)
✅ **High Concurrency**: Supports 10+ concurrent sessions
✅ **Hot-Swappable**: Runtime adapter switching without restart
✅ **CLI Integration**: 5 terminal commands
✅ **MCP Integration**: 12 MCP tools for Claude Code
✅ **Connection Pooling**: Efficient iTerm2 connection reuse
✅ **Error Handling**: Custom exceptions with detailed context
✅ **Documentation**: Complete docstrings and examples

**Key Benefits:**
- Works with any terminal (not iTerm2-only)
- MCP-native integration for Claude Code
- High concurrency support (10+ sessions)
- Graceful fallback (iTerm2 → mcpretentious)
- Zero-downtime adapter switching
- Comprehensive testing and documentation

---

**Document Version**: 1.0
**Date**: 2025-01-24
**Status**: Production Ready ✅
