# Mahavishnu Admin Shell

**Status**: ✅ Fully Implemented (January 2025)

The Mahavishnu Admin Shell is an IPython-based interactive debugging and monitoring interface for workflow orchestration. It provides real-time visibility into workflows, repositories, and system state.

## Features

### Convenience Functions

The shell provides pre-configured async helper functions:

- **`ps()`** - Show all workflows
- **`top()`** - Show active workflows with progress details
- **`errors(n=10)`** - Show recent errors (default: 10)
- **`sync()`** - Sync workflow state from OpenSearch backend

### Magic Commands

IPython magic commands for quick repository and workflow inspection:

- **`%repos [tag]`** - List repositories, optionally filtered by tag
- **`%workflow <id>`** - Show detailed workflow information
- **`%help_shell`** - Show shell-specific help
- **`%status`** - Show shell and application status

### Pre-Configured Namespace

The shell includes useful objects and imports:

```python
app              # MahavishnuApp instance
asyncio          # Asyncio module
run              # Shortcut for asyncio.run()
WorkflowStatus   # Workflow status enum
MahavishnuApp    # App class for introspection
logger           # Structlog logger
```

## Quick Start

### Basic Usage

```bash
# Start the admin shell
mahavishnu shell

# Inside the shell:
Mahavishnu> ps()                    # List all workflows
Mahavishnu> top()                   # Show active workflows
Mahavishnu> errors(5)               # Show last 5 errors
Mahavishnu> %repos                  # List all repositories
Mahavishnu> %repos python           # List repositories with 'python' tag
Mahavishnu> %workflow wf-123        # Show workflow details
Mahavishnu> exit                    # Quit shell
```

### Advanced Usage

**Inspect application state:**

```python
# View app configuration
Mahavishnu> app.config

# View active adapters
Mahavishnu> app.adapters.keys()

# Check workflow manager
Mahavishnu> app.workflow_state_manager

# Run custom queries
Mahavishnu> import asyncio
Mahavishnu> workflows = asyncio.run(app.workflow_state_manager.list_workflows())
```

**Execute async operations:**

```python
# Sync with backend
Mahavishnu> sync()

# Get specific workflow
Mahavishnu> wf = asyncio.run(app.workflow_state_manager.get("wf-id"))

# List repositories
Mahavishnu> repos = app.get_repos(tag="python")
```

## Architecture

The admin shell uses a two-layer architecture:

### Oneiric Layer (Reusable)

Located in `/Users/les/Projects/oneiric/oneiric/shell/`:

```
oneiric/shell/
├── __init__.py        # Package exports
├── config.py          # ShellConfig (Pydantic)
├── core.py            # AdminShell base class
├── formatters.py      # Base table/log/progress formatters
└── magics.py          # Base IPython magic commands
```

**Components:**

- **`AdminShell`** - Base class with IPython integration
- **`ShellConfig`** - Configuration model (banner, table width, etc.)
- **`BaseTableFormatter`** - Rich table formatting with fallback
- **`BaseLogFormatter`** - Log entry display with filtering
- **`BaseProgressFormatter`** - Progress bars for long operations

### Mahavishnu Layer (Domain-Specific)

Located in `/Users/les/Projects/mahavishnu/mahavishnu/shell/`:

```
mahavishnu/shell/
├── __init__.py        # Package exports
├── adapter.py         # MahavishnuShell extends AdminShell
├── formatters.py      # Workflow/log/repo formatters
├── helpers.py         # ps(), top(), errors(), sync()
└── magics.py          # %repos, %workflow magic commands
```

**Components:**

- **`MahavishnuShell`** - App-specific shell with workflow helpers
- **`WorkflowFormatter`** - Workflow table display with status colors
- **`LogFormatter`** - OpenSearch log integration with filtering
- **`RepoFormatter`** - Repository listing with tags
- **Helper functions** - Async wrappers for workflow operations

## Configuration

The admin shell is controlled by the `shell_enabled` configuration field:

**Enable/disable shell** (in `settings/mahavishnu.yaml`):

```yaml
shell_enabled: true    # Default: true
```

**Via environment variable:**

```bash
export MAHAVISHNU_SHELL_ENABLED=false
mahavishnu shell  # Will show error and exit
```

**Shell configuration options** (in `settings/mahavishnu.yaml`):

```yaml
shell:
  banner: "Mahavishnu Orchestrator Shell"
  display_prompt: true
  table_max_width: 120
  show_tracebacks: false
  auto_refresh_enabled: false
  auto_refresh_interval: 5.0
```

## Examples

### Workflow Monitoring

```bash
# Start shell
mahavishnu shell

# Check all workflows
Mahavishnu> ps()

# View active workflows
Mahavishnu> top()

# Show specific workflow
Mahavishnu> %workflow wf-abc-123

# Monitor errors
Mahavishnu> errors(20)
```

### Repository Inspection

```bash
# List all repositories
Mahavishnu> %repos

# Filter by tag
Mahavishnu> %repos python

# Multiple tags (AND logic)
Mahavishnu> repos = app.get_repos(tags=["python", "testing"])
Mahavishnu> for r in repos: print(r['path'])
```

### Debugging

```bash
# Enable debug mode
Mahavishnu> import logging
Mahavishnu> logging.basicConfig(level=logging.DEBUG)

# Inspect workflow state
Mahavishnu> wf = asyncio.run(app.workflow_state_manager.get("wf-id"))
Mahavishnu> wf.keys()

# Check adapter status
Mahavishnu> for name, adapter in app.adapters.items():
...:     print(f"{name}: {adapter.__class__.__name__}")
```

### Custom Queries

```python
# Get workflows by status
Mahavishnu> workflows = asyncio.run(
...:     app.workflow_state_manager.list_workflows(status="running")
...: )

# Count workflows by adapter
Mahavishnu> from collections import Counter
Mahavishnu> workflows = asyncio.run(app.workflow_state_manager.list_workflows())
Mahavishnu> Counter(w['adapter'] for w in workflows)
```

## Rich Integration

The shell uses Rich for beautiful terminal output when available:

**Status colors:**

- 🟢 **Completed** - Green
- 🟡 **Running** - Yellow
- 🔴 **Failed** - Red
- 🔵 **Pending** - Blue

**Log level colors:**

- **ERROR** - Bold red
- **WARNING** - Bold yellow
- **INFO** - Blue
- **DEBUG** - Dim

If Rich is not available, the shell gracefully falls back to plain text formatting.

## Testing

Unit tests for shell components:

```bash
# Run shell formatter tests
pytest tests/unit/test_shell_formatters.py -v

# Run with coverage
pytest tests/unit/test_shell_formatters.py --cov=mahavishnu/shell
```

**Test coverage:**

- WorkflowFormatter: ✅ 6 tests passing
- LogFormatter: ✅ Filter and validation tests
- RepoFormatter: ✅ Display and tag tests

## Troubleshooting

### Shell won't start

**Error:** "Admin shell is disabled"

**Solution:** Check `shell_enabled` in configuration:

```yaml
shell_enabled: true  # Must be true
```

### Magic commands not found

**Error:** "%repos: command not found"

**Solution:** Ensure you're in the MahavishnuShell (not plain IPython):

```bash
mahavishnu shell  # Starts MahavishnuShell with magics
```

### Rich formatting issues

**Error:** Tables display incorrectly

**Solution:** Install Rich for best experience:

```bash
uv pip install rich
```

The shell will automatically detect Rich and use it.

## Development

### Extending the Shell

**Add new helper function** (in `mahavishnu/shell/helpers.py`):

```python
async def my_helper(app: MahavishnuApp) -> None:
    """Custom helper function."""
    # Your logic here
    pass
```

**Register in shell** (in `mahavishnu/shell/adapter.py`):

```python
def _add_mahavishnu_namespace(self) -> None:
    self.namespace.update({
        "my_helper": lambda: asyncio.run(my_helper(self.app)),
    })
```

**Add new magic command** (in `mahavishnu/shell/magics.py`):

```python
@line_magic
def my_command(self, line: str) -> None:
    """Custom magic command."""
    # Your logic here
    pass
```

### Testing Extensions

```python
# Test helper function
@pytest.mark.asyncio
async def test_my_helper():
    app = MahavishnuApp()
    await my_helper(app)  # Should not raise

# Test magic command
def test_my_magic():
    shell = MahavishnuShell(app)
    shell.run_line("%my_command arg1")
```

## Performance Considerations

- **Startup time:** ~1-2 seconds (IPython initialization)
- **Memory overhead:** ~50MB additional (IPython + Rich)
- **Concurrent sessions:** Each shell is independent
- **Async execution:** Helpers use `asyncio.run()` for async operations

## Security

The admin shell respects all Mahavishnu security settings:

- ✅ Authentication required if `auth_enabled` is true
- ✅ Path validation for repository access
- ✅ No secret exposure in namespace
- ✅ Controlled by `shell_enabled` configuration

## Future Enhancements

Planned features for future versions:

- [ ] Auto-refresh mode for monitoring workflows
- [ ] Persistent command history across sessions
- [ ] Custom color schemes and themes
- [ ] Multi-shell sessions (attach to running shell)
- [ ] Remote shell access via WebSocket
- [ ] Notebook integration (Jupyter kernel)

## Related Documentation

- [Architecture](../ARCHITECTURE.md) - System architecture overview
- [Configuration](../README.md#configuration) - Configuration system
- [MCP Tools](../docs/MCP_TOOLS_SPECIFICATION.md) - MCP tool API
- [Terminal Management](../docs/TERMINAL_MANAGEMENT.md) - Terminal features

## Contributing

When extending the admin shell:

1. **Follow the two-layer architecture** - keep Oneiric reusable
1. **Add tests** - maintain 100% test coverage
1. **Document magic commands** - add help text
1. **Use Rich formatting** - beautiful output matters
1. **Graceful fallbacks** - work without Rich

## License

MIT License - See main project LICENSE file.
