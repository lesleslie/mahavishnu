# CLI Shell Guide

## Overview

The CLI shell system provides a universal admin shell interface for Python-based components with Typer CLIs. It combines the power of IPython's interactive environment with seamless CLI command invocation - no prefixes required.

### Key Features

- **No-Prefix CLI Commands**: Invoke CLI commands directly without prefixes like `!` or `%`
- **Dynamic Command Discovery**: Automatically discovers commands from your Typer app
- **Python REPL**: Full IPython environment with tab completion, history, and magic commands
- **Component-Specific Extensions**: Easy to extend for any component
- **Convenience Helpers**: Pre-built helper functions for common operations
- **Automatic Session Tracking**: Tracks shell lifecycle for monitoring and analytics

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     User Input                              │
│                   (CLI or Python)                           │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              InputPreprocessor                              │
│    Routes CLI commands vs Python code                       │
│    - Checks command registry                                │
│    - Invokes CLI or passes to Python                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
           ┌───────────┴───────────┐
           │                       │
           ▼                       ▼
┌──────────────────┐    ┌──────────────────────┐
│   CLI Invoker    │    │   IPython Shell      │
│                  │    │                      │
│ python -m comp   │    │ - Python code        │
│ <command>        │    │ - Magic commands     │
│                  │    │ - Helpers            │
└──────────────────┘    └──────────────────────┘
           │                       │
           ▼                       ▼
┌─────────────────────────────────────────────────────────────┐
│                    Component App                             │
│              (MahavishnuApp, etc.)                          │
└─────────────────────────────────────────────────────────────┘
```

### Component Layers

```
┌─────────────────────────────────────────────────────────────┐
│  AdminShell (Oneiric - Base Class)                          │
│  - IPython shell setup                                      │
│  - Input preprocessing                                      │
│  - Magic commands                                           │
│  - Namespace management                                     │
│  - Session lifecycle tracking                               │
└──────────────────────┬──────────────────────────────────────┘
                       │ extends
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  MahavishnuShell (Component-Specific)                       │
│  - Workflow helpers (ps, top, errors, sync)                │
│  - Mahavishnu magics (%repos, %workflow)                   │
│  - Rich formatters                                          │
│  - Component name for CLI discovery                         │
└─────────────────────────────────────────────────────────────┘
```

---

## Usage Guide

### Starting the Shell

```bash
# Start Mahavishnu shell
python -m mahavishnu shell

# Or using the CLI command
mahavishnu shell
```

You'll see a banner like this:

```
Mahavishnu Admin Shell
============================================================
Active Adapters: llamaindex, agno, prefect

Session Tracking: ✓ Enabled (Session-Buddy connected)
  Session ID: sess_abc123
  Tracking: http://localhost:8678/mcp

CLI Commands: ✓ Enabled (no prefix required)
  list-repos              - List all repositories
  sweep --tag <tag>       - Sweep repositories by tag
  validate-production     - Production readiness checks

Convenience Functions:
  ps()          - Show all workflows
  top()         - Show active workflows with progress
  errors(n=10)  - Show recent errors
  sync()        - Sync workflow state from backend

Magic Commands:
  %repos        - List repositories
  %workflow <id> - Show workflow details

Type 'help()' for Python help or %help_shell for shell commands
============================================================
```

### Command Types

The shell supports three types of commands:

#### 1. CLI Commands (No Prefix)

```python
# Direct CLI invocation - no prefix needed!
Mahavishnu> list-repos
Mahavishnu> list-repos --tag python
Mahavishnu> list-repos --role orchestrator
Mahavishnu> sweep --tag backend --adapter llamaindex
Mahavishnu> validate-production
Mahavishnu> validate-production -c environment --json
Mahavishnu> pool list
Mahavishnu> pool spawn --type mahavishnu --name local --min 2 --max 5
```

**How it works:**
- InputPreprocessor checks if the first word matches a known CLI command
- If matched, invokes `python -m mahavishnu <args>` via subprocess
- If not matched, passes to Python interpreter

#### 2. Python Code

```python
# Python expressions work normally
Mahavishnu> x = 5
Mahavishnu> repos = app.get_repos(tag="python")
Mahavishnu> print(f"Found {len(repos)} repos")

# Use convenience helpers
Mahavishnu> ps()
Mahavishnu> top()
Mahavishnu> errors(5)
Mahavishnu> sync()
```

#### 3. Magic Commands

```python
# IPython magics start with % or %%
Mahavishnu> %repos              # List all repos
Mahavishnu> %repos python       # Filter by tag
Mahavishnu> %workflow wf_abc123 # Show workflow details
Mahavishnu> %help_shell         # Show shell help
Mahavishnu> %timeit ps()        # Time execution
```

### Common Workflows

#### Repository Management

```python
# List all repositories
list-repos

# Filter by tag
list-repos --tag python

# Filter by role
list-repos --role orchestrator

# Show role details
show-role orchestrator

# List all available roles
list-roles
```

#### Workflow Orchestration

```python
# Sweep repositories with AI tasks
sweep --tag backend --adapter llamaindex

# Monitor workflows with helpers
ps()              # Show all workflows
top()             # Show active workflows
errors(10)        # Show recent errors
sync()            # Sync from OpenSearch

# Get workflow details
%workflow wf_abc123
```

#### Pool Management

```python
# List active pools
pool list

# Spawn new pool
pool spawn --type mahavishnu --name local --min 2 --max 5

# Execute on specific pool
pool execute pool_abc --prompt "Write Python code"

# Auto-route to best pool
pool route --prompt "Write tests" --selector least_loaded

# Scale pool
pool scale pool_abc --target 10

# Monitor health
pool health

# Cleanup
pool close pool_abc
pool close-all
```

#### Production Validation

```python
# Run all production checks
validate-production

# Run specific check
validate-production -c environment

# Output as JSON
validate-production --json

# Save report to file
validate-production --save
```

#### Python Inspection

```python
# Inspect app state
print(app.config)
print(app.adapters.keys())

# Check workflow state
wf = await app.workflow_state_manager.get("wf_abc123")
print(wf)

# Use Rich formatting
from rich import print
print(app.config)
```

### Tab Completion

The shell supports IPython's tab completion:

```python
# Complete CLI commands
Mahavishnu> list-<TAB>
list-repos  list-roles  list_nicknames

# Complete Python attributes
Mahavishnu> app.<TAB>
app.adapters  app.config  app.get_repos  ...

# Complete file paths
Mahavishnu> open /usr/<TAB>
```

---

## Session Tracking

### Overview

The admin shell automatically tracks its lifecycle (start/end events) with Session-Buddy MCP. This enables:

- **Monitoring**: See which shells are active across your ecosystem
- **Analytics**: Track shell usage patterns and duration
- **Audit**: Maintain audit trail of admin access
- **Debugging**: Identify long-running or stuck shells

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Component Admin Shell                     │
│  (MahavishnuShell, SessionBuddyShell, OneiricShell, etc.) │
│                                                                   │
│  1. User starts shell: $ python -m mahavishnu shell        │
│  2. AdminShell.start() called                                  │
│  3. SessionEventEmitter emits session_start event              │
│     → MCP call to session-buddy: track_session_start           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Session-Buddy MCP Server                       │
│                                                                   │
│  1. Receives session_start event                               │
│  2. Creates session record in database                         │
│  3. Tracks PID, component name, start time, user info          │
│  4. Returns session_id                                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Session Lifecycle                            │
│  - User executes commands in shell                             │
│  - Session remains active                                       │
│  - Session-Buddy tracks activity                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Shell Exit Trigger                            │
│  1. User types exit() or Ctrl-D                                │
│  2. IPython exit hook triggered                                │
│  3. SessionEventEmitter emits session_end event                │
│     → MCP call to session-buddy: track_session_end             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Session-Buddy MCP Server                       │
│  1. Receives session_end event                                 │
│  2. Updates session record with end time                       │
│  3. Calculates session duration                                │
│  4. Archives session for historical analysis                   │
└─────────────────────────────────────────────────────────────────┘
```

### How It Works

#### Automatic Integration

Session tracking is **automatic** for all admin shells. No configuration required:

```python
# Any shell extending AdminShell gets session tracking automatically
from oneiric.shell import AdminShell

class MyComponentShell(AdminShell):
    def _get_component_name(self) -> str:
        return "mycomponent"  # Enables session tracking

# That's it! Session tracking is now enabled
```

#### Session Metadata

Each session tracks rich metadata:

```python
{
    "session_id": "sess_abc123",
    "component_name": "mahavishnu",
    "shell_type": "MahavishnuShell",
    "pid": 12345,
    "username": "les",
    "hostname": "mbp-local",
    "start_time": "2026-02-06T10:30:00Z",
    "end_time": "2026-02-06T10:35:00Z",
    "duration_seconds": 300,
    "python_version": "3.13.0",
    "platform": "macOS-15.2-arm64-arm-64bit",
    "working_directory": "/Users/les/Projects/mahavishnu",
    "metadata": {
        "component_version": "1.0.0",
        "cli_enabled": true,
        "adapters": ["llamaindex", "agno", "prefect"]
    }
}
```

#### Graceful Degradation

Session tracking degrades gracefully if Session-Buddy is unavailable:

```python
# Session-Buddy unavailable
# → Shell starts normally
# → Warning logged: "Session-Buddy MCP unavailable - session not tracked"
# → session_id set to None
# → All shell features work normally
```

### Verifying Session Tracking

#### Check Active Sessions

```bash
# Using Session-Buddy CLI
session-buddy list-sessions --type admin_shell

# Output:
┌──────────────┬──────────────┬──────────┬────────────────┐
│ Session ID   │ Component    │ User     │ Started        │
├──────────────┼──────────────┼──────────┼────────────────┤
│ sess_abc123  │ mahavishnu   │ les      │ 10:30:00       │
│ sess_def456  │ session-buddy│ les      │ 10:25:00       │
└──────────────┴──────────────┴──────────┴────────────────┘
```

#### View Session Details

```bash
# Show specific session
session-buddy show-session sess_abc123

# Output:
┌────────────────────────────────────────────────────────────┐
│ Session: sess_abc123                                        │
├────────────────────────────────────────────────────────────┤
│ Component:     mahavishnu                                  │
│ Shell Type:    MahavishnuShell                             │
│ User:          les                                         │
│ PID:           12345                                       │
├────────────────────────────────────────────────────────────┤
│ Start Time:    2026-02-06 10:30:00 UTC                    │
│ End Time:      2026-02-06 10:35:00 UTC                    │
│ Duration:      300 seconds (5 minutes)                    │
├────────────────────────────────────────────────────────────┤
│ Python:        3.13.0                                      │
│ Platform:      macOS-15.2-arm64-arm-64bit                 │
│ Working Dir:   /Users/les/Projects/mahavishnu             │
├────────────────────────────────────────────────────────────┤
│ Adapters:      llamaindex, agno, prefect                   │
│ CLI Enabled:   true                                        │
│ Version:       1.0.0                                       │
└────────────────────────────────────────────────────────────┘
```

#### Query Session History

```bash
# List recent sessions
session-buddy list-sessions --type admin_shell --limit 10

# Filter by component
session-buddy list-sessions --component mahavishnu

# Filter by user
session-buddy list-sessions --user les

# Filter by date range
session-buddy list-sessions --after "2026-02-01" --before "2026-02-07"
```

### Troubleshooting Session Tracking

#### Session Tracking Not Working

**Problem**: Shell banner shows "Session Tracking: ✗ Disabled"

**Diagnosis**:
```bash
# Check if Session-Buddy MCP is running
mahavishnu mcp status

# Check Session-Buddy health
curl http://localhost:8678/health

# Check authentication secret
echo $MAHAVISHNU_CROSS_PROJECT_AUTH_SECRET
```

**Solutions**:

1. **Start Session-Buddy MCP**:
   ```bash
   cd /Users/les/Projects/session-buddy
   session-buddy mcp start
   ```

2. **Set authentication secret**:
   ```bash
   export MAHAVISHNU_CROSS_PROJECT_AUTH_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
   ```

3. **Check network connectivity**:
   ```bash
   # Verify Session-Buddy reachable
   telnet localhost 8678
   ```

#### Session ID is None

**Problem**: `shell.session_id` is `None` after starting shell

**Causes**:
- Session-Buddy MCP unavailable
- Authentication failed
- Network error

**Diagnosis**:
```python
# Check session tracking status in shell
Mahavishnu> print(shell.session_id)
None

# Check Session-Buddy availability
Mahavishnu> import logging
Mahavishnu> logging.basicConfig(level=logging.DEBUG)
Mahavishnu> # Look for "Session-Buddy MCP unavailable" messages
```

**Solutions**:
1. Verify Session-Buddy MCP is running
2. Check authentication configuration
3. Review logs for specific error messages
4. Continue using shell (works without session tracking)

#### Session End Not Recorded

**Problem**: Session start recorded, but session end not in database

**Causes**:
- Shell crashed (not clean exit)
- Session-Buddy unavailable at exit time
- Network timeout during session_end event

**Solutions**:
1. **Check Session-Buddy logs**:
   ```bash
   # Look for session_end errors
   tail -f /path/to/session-buddy/logs/mcp.log
   ```

2. **Verify clean shell exit**:
   ```python
   # Use exit() not Ctrl+C
   Mahavishnu> exit()  # Clean exit with session_end
   # Ctrl+C may skip cleanup
   ```

3. **Manual session cleanup** (if needed):
   ```bash
   # Manually end stuck sessions
   session-buddy end-session sess_abc123
   ```

#### Circuit Breaker Open

**Problem**: "Circuit breaker opened - Session-Buddy unavailable" in logs

**Meaning**: Session-Buddy failed 3 consecutive times, circuit opened for 60 seconds

**Behavior**:
- Session tracking temporarily disabled
- Automatic retry after 60 seconds
- Shell continues normally

**Solutions**:
1. **Wait for circuit to reset** (60 seconds)
2. **Fix Session-Buddy connectivity**:
   - Restart Session-Buddy MCP
   - Check network configuration
   - Verify authentication
3. **Monitor circuit breaker state**:
   ```python
   Mahavishnu> print(shell.session_tracker._circuit_open_until)
   ```

### Testing Session Tracking

#### Manual Testing

```bash
# Terminal 1: Start Session-Buddy MCP
cd /Users/les/Projects/session-buddy
session-buddy mcp start

# Terminal 2: Start Mahavishnu shell
cd /Users/les/Projects/mahavishnu
export MAHAVISHNU_CROSS_PROJECT_AUTH_SECRET="test-secret-for-development"
python -m mahavishnu shell

# Terminal 3: Check active sessions
session-buddy list-sessions --type admin_shell

# Terminal 2: Exit shell
exit()

# Terminal 3: Verify session ended
session-buddy show-session <session_id>
```

#### Automated Testing

```python
# Test session tracking with mocked Session-Buddy
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_session_start_emitted():
    """Test session_start event emitted on shell start."""
    with patch("oneiric.shell.session_tracker.SessionEventEmitter") as mock_emitter:
        # Configure mock
        mock_emitter.return_value.emit_session_start = AsyncMock(
            return_value="sess_test123"
        )

        # Create shell
        from mahavishnu.shell import MahavishnuShell
        from mahavishnu.core.app import MahavishnuApp

        app = MahavishnuApp()
        shell = MahavishnuShell(app)
        shell.session_tracker = mock_emitter.return_value

        # Trigger session start
        await shell._notify_session_start()

        # Verify emitted
        shell.session_tracker.emit_session_start.assert_called_once()
        assert shell.session_id == "sess_test123"
```

See `tests/integration/test_session_tracking_e2e.py` for comprehensive test suite.

### Configuration

Session tracking uses these environment variables:

```bash
# Cross-project authentication (for Session-Buddy MCP)
export MAHAVISHNU_CROSS_PROJECT_AUTH_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"

# Session-Buddy MCP endpoint (default: http://localhost:8678/mcp)
export SESSION_BUDDY_MCP_ENDPOINT="http://localhost:8678/mcp"

# Session-Buddy path (for stdio MCP transport)
export SESSION_BUDDY_PATH="/Users/les/Projects/session-buddy"
```

### Best Practices

1. **Always use `exit()` for clean shutdown**:
   ```python
   Mahavishnu> exit()  # Triggers session_end event
   # Avoid: Ctrl+C (may skip cleanup)
   ```

2. **Monitor session duration**:
   ```bash
   # Find long-running sessions
   session-buddy list-sessions --duration-greater 3600  # > 1 hour
   ```

3. **Audit admin access**:
   ```bash
   # Review all admin shell sessions
   session-buddy list-sessions --type admin_shell --after "2026-02-01"
   ```

4. **Clean up stuck sessions**:
   ```bash
   # End sessions that didn't clean up
   session-buddy end-session sess_abc123
   ```

5. **Use authentication in production**:
   ```bash
   # Set strong authentication secret
   export MAHAVISHNU_CROSS_PROJECT_AUTH_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
   ```

---

## Component Adoption Guide

### Adding CLI Shell to Your Component

The CLI shell system is designed to be universal. Any component with a Typer CLI can adopt it.

#### Step 1: Install Oneiric

```bash
# Oneiric contains the base AdminShell class
pip install oneiric
```

#### Step 2: Create Component-Specific Shell

Create a shell adapter in your component:

```python
"""My component's admin shell."""

import asyncio
from oneiric.shell import AdminShell, ShellConfig
from myapp import MyApp

class MyComponentShell(AdminShell):
    """Component-specific admin shell."""

    def __init__(self, app: MyApp, config: ShellConfig | None = None):
        super().__init__(app, config)
        self._add_component_namespace()

    def _add_component_namespace(self):
        """Add component-specific helpers."""
        self.namespace.update({
            "myapp": MyApp,
            "status": lambda: asyncio.run(self._get_status()),
            "logs": lambda limit=10: asyncio.run(self._get_logs(limit)),
        })

    def _get_component_name(self) -> str | None:
        """Return component name for CLI discovery."""
        return "mycomponent"  # Matches your Python module name

    def _get_banner(self) -> str:
        """Custom banner."""
        return f"""
MyComponent Admin Shell
{'=' * 60}
CLI Commands: ✓ Enabled (no prefix required)
  status    - Show component status
  logs      - View logs
  deploy    - Deploy component

Convenience Functions:
  status()  - Get status
  logs(n=10) - View logs

Type 'help()' for Python help or %help_shell for shell commands
{'=' * 60}
"""
```

#### Step 3: Add Shell Command to CLI

```python
# In mycomponent/cli.py
import typer
from myapp import MyApp
from mycomponent.shell import MyComponentShell

@app.command()
def shell():
    """Start the interactive admin shell."""
    app = MyApp()

    # Check if shell is enabled
    if not getattr(app.config, "shell_enabled", True):
        typer.echo("ERROR: Admin shell is disabled")
        raise typer.Exit(code=1)

    # Create and start shell
    shell = MyComponentShell(app)
    shell.start()
```

#### Step 4: Start Shell

```bash
python -m mycomponent shell
```

### Customization Options

#### Add Custom Helpers

```python
def _add_component_namespace(self):
    """Add custom helpers."""

    # Async helper
    async def get_status():
        status = await self.app.get_status()
        print(f"Status: {status}")

    # Sync wrapper for async
    self.namespace.update({
        "status": lambda: asyncio.run(get_status()),

        # Direct function references
        "restart": self.app.restart,
        "reload_config": self.app.reload_config,
    })
```

#### Add Custom Magics

```python
# In mycomponent/shell/magics.py
from IPython.core.magic import Magics, line_magic, magics_class

@magics_class
class MyComponentMagics(Magics):
    @line_magic
    def instances(self, line: str):
        """List instances. Usage: %instances [region]"""
        region = line.strip() or None
        instances = self.app.list_instances(region=region)
        for i in instances:
            print(f"  - {i['id']}: {i['status']}")

# In MyComponentShell._register_magics()
def _register_magics(self):
    super()._register_magics()
    magics = MyComponentMagics(self.shell)
    magics.set_app(self.app)
    self.shell.register_magics(magics)
```

#### Custom Formatters

```python
# In mycomponent/shell/formatters.py
from rich.console import Console
from rich.table import Table

class InstanceFormatter:
    def __init__(self):
        self.console = Console()

    def format_instances(self, instances):
        table = Table(title="Instances")
        table.add_column("ID", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Region", style="yellow")

        for instance in instances:
            table.add_row(instance["id"], instance["status"], instance["region"])

        self.console.print(table)
```

### Shell Configuration

Control shell behavior via `ShellConfig`:

```python
from oneiric.shell import ShellConfig

config = ShellConfig(
    banner="Custom Banner",
    cli_preprocessing_enabled=True,  # Enable CLI commands
)

shell = MyComponentShell(app, config)
shell.start()
```

---

## Mahavishnu-Specific Features

### Helper Functions

Mahavishnu provides convenience helpers for workflow management:

#### `ps()` - Show All Workflows

```python
Mahavishnu> ps()

# Output:
┌────────────────────────────────────────────────────────────┐
│ Workflows (100)                                             │
├──────────────┬──────────┬─────────┬────────────────────────┤
│ ID           │ Status   │ Adapter │ Created                │
├──────────────┼──────────┼─────────┼────────────────────────┤
│ wf_abc123    │ running  │ llama   │ 2026-02-06 10:30:00    │
│ wf_def456    │ complete │ agno    │ 2026-02-06 10:15:00    │
│ wf_ghi789    │ failed   │ llama   │ 2026-02-06 10:00:00    │
└──────────────┴──────────┴─────────┴────────────────────────┘
```

#### `top()` - Show Active Workflows

```python
Mahavishnu> top()

# Output: Shows only running workflows with progress details
┌────────────────────────────────────────────────────────────┐
│ Active Workflows (3)                                        │
├──────────────┬──────────┬─────────┬────────────┬───────────┤
│ ID           │ Status   │ Adapter │ Progress   │ Duration  │
├──────────────┼──────────┼─────────┼────────────┼───────────┤
│ wf_abc123    │ running  │ llama   │ 75%        │ 00:05:23  │
│ wf_xyz111    │ running  │ agno    │ 40%        │ 00:02:15  │
└──────────────┴──────────┴─────────┴────────────┴───────────┘
```

#### `errors(n=10)` - Show Recent Errors

```python
Mahavishnu> errors(5)

# Output:
┌────────────────────────────────────────────────────────────┐
│ Recent Errors (5)                                           │
├──────────────┬──────────┬──────────────────────────────────┤
│ Workflow     │ Time     │ Error                           │
├──────────────┼──────────┼──────────────────────────────────┤
│ wf_ghi789    │ 10:00:00 │ Connection timeout              │
│ wf_jkl012    │ 09:45:00 │ Invalid repo path               │
│ wf_mno345    │ 09:30:00 │ Adapter not found               │
└──────────────┴──────────┴──────────────────────────────────┘
```

#### `sync()` - Sync Workflow State

```python
Mahavishnu> sync()

# Output:
Syncing workflow state from OpenSearch...
OpenSearch status: green
Total workflows: 1000
Sync complete
```

### Magic Commands

#### `%repos` - List Repositories

```python
# List all repos
Mahavishnu> %repos

# Filter by tag
Mahavishnu> %repos python

# Output:
┌────────────────────────────────────────────────────────────┐
│ Repositories with tag 'python' (15)                         │
├─────────────────┬──────────────┬──────────────┬────────────┤
│ Name            │ Role         │ Tags         │ Path       │
├─────────────────┼──────────────┼──────────────┼────────────┤
│ mahavishnu      │ orchestrator │ python, backend│ /path/... │
│ session-buddy   │ manager      │ python       │ /path/... │
└─────────────────┴──────────────┴──────────────┴────────────┘
```

#### `%workflow <id>` - Show Workflow Details

```python
Mahavishnu> %workflow wf_abc123

# Output:
┌────────────────────────────────────────────────────────────┐
│ Workflow: wf_abc123                                         │
├────────────────────────────────────────────────────────────┤
│ Status:     running                                         │
│ Adapter:    llamaindex                                      │
│ Created:    2026-02-06 10:30:00 UTC                        │
│ Progress:   75%                                             │
│ Duration:   00:05:23                                        │
├────────────────────────────────────────────────────────────┤
│ Task:       ai-sweep                                        │
│ Repositories:                                               │
│   - mahavishnu (complete)                                   │
│   - session-buddy (running)                                 │
│   - akosha (pending)                                        │
├────────────────────────────────────────────────────────────┤
│ Errors:                                                     │
│   None                                                      │
└────────────────────────────────────────────────────────────┘
```

### Available CLI Commands

Mahavishnu exposes all CLI commands in the shell:

```bash
# Repository commands
list-repos [--tag TAG] [--role ROLE]
list-roles
show-role ROLE_NAME
list-nicknames

# Workflow commands
sweep --tag TAG [--adapter ADAPTER]

# Pool commands
pool {spawn|list|execute|route|scale|close|close-all|health}

# Worker commands
workers {spawn|execute}

# Production validation
validate-production [--check CHECK] [--json] [--save]

# MCP server
mcp {start|stop|restart|status|health}

# Terminal management
terminal {launch|list|send|capture|close}

# Backup/restore
backup {create|restore|list|delete}

# WASM Booster
booster {format|lint|rename|stats|benchmark}

# Ecosystem
ecosystem {configure|validate}

# Monitoring
monitoring {metrics|alerts|dashboards}

# And more...
```

### Rich Formatters

Mahavishnu uses Rich for beautiful output:

```python
# Use Rich Console directly
from rich import print
from rich.table import Table
from rich.panel import Panel

print("[bold green]Success![/bold green]")

table = Table(title="Repositories")
table.add_column("Name", style="cyan")
table.add_column("Role", style="magenta")
table.add_row("mahavishnu", "orchestrator")
print(table)

panel = Panel("Hello", title="Message")
print(panel)
```

---

## Troubleshooting

### Commands Not Discovered

**Problem**: CLI commands not recognized in shell.

**Symptoms**:
```python
Mahavishnu> list-repos
Unknown command: list-repos
Available commands: []
```

**Diagnosis**:
```python
# Check if component name is correct
Mahavishnu> import mahavishnu.cli as cli
Mahavishnu> print(hasattr(cli, 'app'))  # Should be True

# Check registered commands
Mahavishnu> print(cli.app.registered_commands)  # Should show CommandInfo objects
Mahavishnu> print(cli.app.registered_groups)  # Should show TyperInfo objects
```

**Solutions**:

1. **Check `_get_component_name()` override**:
   ```python
   # In mahavishnu/shell/adapter.py
   def _get_component_name(self) -> str | None:
       return "mahavishnu"  # Must match Python module name
   ```

2. **Verify CLI app structure**:
   ```python
   # CLI module must have 'app' attribute
   # In mahavishnu/cli.py
   app = typer.Typer()  # Must be named 'app'
   ```

3. **Check import path**:
   ```python
   # Component must be importable
   python -c "import mahavishnu.cli; print(mahavishnu.cli.app)"
   ```

4. **Enable CLI preprocessing**:
   ```python
   config = ShellConfig(cli_preprocessing_enabled=True)
   shell = MahavishnuShell(app, config)
   ```

### Import Errors

**Problem**: Shell fails to start with import errors.

**Symptoms**:
```python
ModuleNotFoundError: No module named 'mahavishnu.cli'
ImportError: cannot import name 'app' from 'mahavishnu.cli'
```

**Solutions**:

1. **Install component in development mode**:
   ```bash
   pip install -e /path/to/mahavishnu
   ```

2. **Check CLI module exists**:
   ```bash
   ls -la mahavishnu/cli.py
   # or
   ls -la mahavishnu/cli/__init__.py
   ```

3. **Verify exports**:
   ```python
   # In mahavishnu/cli.py
   app = typer.Typer()  # Must be exported
   ```

4. **Check Python path**:
   ```python
   import sys
   print(sys.path)  # Should include your component path
   ```

### Tab Completion Not Working

**Problem**: Tab completion doesn't show available commands.

**Symptoms**:
```python
Mahavishnu> list-<TAB>
# No completion shown
```

**Solutions**:

1. **Ensure IPython is properly initialized**:
   ```python
   # Check if shell is IPython
   Mahavishnu> print(type(__builtins__))
   ```

2. **Check command registry**:
   ```python
   # Commands must be in registry
   Mahavishnu> print(shell.input_preprocessor.command_registry.keys())
   ```

3. **Use IPython's tab completion**:
   ```python
   # Python completion still works
   Mahavishnu> imp<TAB>  # Completes to import
   ```

### Python vs CLI Command Conflicts

**Problem**: Command name conflicts between Python and CLI.

**Symptoms**:
```python
# 'help' is both Python builtin and potential CLI command
Mahavishnu> help
# Which one executes?
```

**Resolution Order**:
1. CLI commands are checked first (if in registry)
2. Python code executes if CLI command not found
3. Use explicit Python when needed:
   ```python
   Mahavishnu> help()  # Python builtin (function call)
   Mahavishnu> import help; help  # Python module
   ```

**Best Practices**:
- Avoid naming CLI commands after Python builtins
- Use verbose CLI command names: `list-repos` instead of `list`
- Use magic commands for meta-operations: `%help_shell`

### Shell Exits Immediately

**Problem**: Shell starts but exits immediately.

**Symptoms**:
```bash
$ python -m mahavishnu shell
Mahavishnu Admin Shell
...
# Shell exits immediately
```

**Solutions**:

1. **Check for exceptions in startup**:
   ```python
   # Look for errors in banner
   # Check logs for traceback
   ```

2. **Verify IPython is installed**:
   ```bash
   pip install ipython
   ```

3. **Check if shell is disabled in config**:
   ```yaml
   # settings/mahavishnu.yaml
   shell_enabled: true  # Must be true
   ```

4. **Test shell creation**:
   ```python
   from mahavishnu.shell import MahavishnuShell
   from mahavishnu.core.app import MahavishnuApp

   app = MahavishnuApp()
   shell = MahavishnuShell(app)
   shell.start()  # Should enter interactive mode
   ```

### Subprocess Invocation Fails

**Problem**: CLI commands fail to execute via subprocess.

**Symptoms**:
```python
Mahavishnu> list-repos
Failed to invoke command: [Errno 2] No such file or directory
```

**Solutions**:

1. **Check Python executable**:
   ```python
   import sys
   print(sys.executable)  # Should be valid Python path
   ```

2. **Verify CLI module is executable**:
   ```bash
   python -m mahavishnu list-repos  # Should work
   ```

3. **Check PATH**:
   ```bash
   which python  # Should return valid path
   echo $PATH  # Should include Python path
   ```

4. **Use absolute Python path**:
   ```python
   # In CLIInvoker.invoke()
   cmd = ["/usr/bin/python3", "-m", self.component_name] + parts
   ```

### Async Helper Functions Fail

**Problem**: Convenience helpers like `ps()` fail with async errors.

**Symptoms**:
```python
Mahavishnu> ps()
RuntimeError: This event loop is already running
```

**Solutions**:

1. **Ensure async functions are wrapped**:
   ```python
   # Correct - wraps async in sync
   "ps": lambda: asyncio.run(ps(self.app))

   # Incorrect - raw async function
   "ps": ps(self.app)  # Will fail!
   ```

2. **Use proper async context**:
   ```python
   # Shell provides asyncio in namespace
   Mahavishnu> asyncio.run(ps())
   ```

3. **Check if app is running async event loop**:
   ```python
   # Some apps may have their own event loop
   # Consult your component's async documentation
   ```

### Getting Help

If you encounter issues not covered here:

1. **Check logs**:
   ```python
   import logging
   logging.basicConfig(level=logging.DEBUG)
   ```

2. **Report issues**:
   - Check GitHub Issues for similar problems
   - Include full traceback and shell configuration
   - Specify component name and version

3. **Debug mode**:
   ```python
   # Enable verbose logging
   import logging
   logger = logging.getLogger("oneiric.shell")
   logger.setLevel(logging.DEBUG)
   ```

---

## Advanced Usage

### Custom Command Routing

Override input preprocessing for custom routing logic:

```python
class CustomShell(AdminShell):
    def _register_cli_preprocessor(self):
        """Register custom preprocessor."""
        # Add custom routing logic
        preprocessor = create_cli_preprocessor("mycomponent")

        # Wrap with custom logic
        def custom_preprocess(line):
            # Check for custom patterns
            if line.startswith("@"):
                # Handle special commands
                return self._handle_special_command(line)

            # Use default preprocessing
            return preprocessor.preprocess(line)

        self.shell.input_transformer_manager.register_transformer(
            custom_preprocess
        )
```

### Shell Hooks

Execute code at shell startup/shutdown:

```python
class HookedShell(AdminShell):
    def start(self):
        """Start shell with hooks."""
        # Pre-start hook
        self._on_shell_start()

        # Start shell
        super().start()

        # Post-start hook (runs after shell exits)
        self._on_shell_exit()

    def _on_shell_start(self):
        """Run startup tasks."""
        print("Initializing shell...")
        # Load history, connect to services, etc.

    def _on_shell_exit(self):
        """Run cleanup tasks."""
        print("Cleaning up...")
        # Save history, disconnect, etc.
```

### Multi-Component Shells

Create a shell that works with multiple components:

```python
class MultiComponentShell(AdminShell):
    """Shell supporting multiple component CLIs."""

    def __init__(self, apps: dict[str, Any]):
        """Initialize with multiple apps."""
        # Use first app as primary
        primary_app = list(apps.values())[0]
        super().__init__(primary_app)

        # Store all apps
        self.apps = apps
        self.component_names = list(apps.keys())

    def _get_component_name(self) -> str | None:
        """Return first component name."""
        return self.component_names[0]

    def _build_namespace(self):
        """Add all apps to namespace."""
        super()._build_namespace()
        for name, app in self.apps.items():
            self.namespace[name] = app
```

### Interactive Sessions

Use shell for interactive debugging and monitoring:

```python
# Start shell programmatically
from mahavishnu.core.app import MahavishnuApp
from mahavishnu.shell import MahavishnuShell

app = MahavishnuApp()
shell = MahavishnuShell(app)

# For automated testing
from io import StringIO
import sys

# Capture output
old_stdout = sys.stdout
sys.stdout = StringIO()

# Execute command
is_cli, processed = shell.input_preprocessor.preprocess("list-repos")

# Restore stdout
output = sys.stdout.getvalue()
sys.stdout = old_stdout

print(f"Output: {output}")
```

---

## Reference

### AdminShell Base Class

Located in `oneiric/shell/core.py`.

**Methods**:
- `start()` - Start interactive shell
- `add_helper(name, func)` - Add helper function
- `add_object(name, obj)` - Add object to namespace

**Overridable Methods**:
- `_get_banner()` - Custom banner
- `_get_component_name()` - Component name for CLI discovery
- `_register_magics()` - Register magic commands
- `_build_namespace()` - Build shell namespace

### MahavishnuShell

Located in `mahavishnu/shell/adapter.py`.

**Helpers**:
- `ps()` - Show all workflows
- `top()` - Show active workflows
- `errors(n=10)` - Show recent errors
- `sync()` - Sync from OpenSearch

**Magics**:
- `%repos [tag]` - List repositories
- `%workflow <id>` - Show workflow details

### CLI Parser Components

Located in `oneiric/shell/cli_parser_v2.py`.

**Classes**:
- `CommandTreeBuilder` - Builds command tree from Typer app
- `CLIInvoker` - Invokes CLI commands via subprocess
- `InputPreprocessor` - Routes CLI vs Python input

**Functions**:
- `create_cli_preprocessor(component_name)` - Create preprocessor

### Shell Configuration

Located in `oneiric/shell/config.py`.

**ShellConfig**:
- `banner: str` - Shell banner text
- `cli_preprocessing_enabled: bool` - Enable CLI commands

---

## Best Practices

### Command Naming

- Use kebab-case for CLI commands: `list-repos`, `show-role`
- Use descriptive names: `validate-production` not `check`
- Avoid Python builtins: don't use `list`, `help`, `eval` as command names
- Use verbs for actions: `sweep`, `spawn`, `scale`, `validate`

### Helper Design

- Keep helpers simple and focused
- Use lambda wrappers for async: `lambda: asyncio.run(async_func())`
- Provide sensible defaults: `errors(limit=10)`
- Return None for display helpers; return values for computation

### Namespace Organization

- Group related objects: `WorkflowStatus`, `MahavishnuApp`
- Use clear names: `app` not `maha_app_instance`
- Avoid conflicts with Python builtins
- Document complex objects with docstrings

### Error Handling

- Catch and display errors gracefully
- Provide helpful error messages
- Log errors for debugging
- Don't let errors crash the shell

### Performance

- Lazy-load heavy modules
- Cache expensive operations
- Use asyncio for I/O-bound operations
- Limit output size: `ps()` limits to 100 workflows

---

## Future Enhancements

Planned improvements to the CLI shell system:

- [x] Automatic session tracking with Session-Buddy
- [ ] Tab completion for CLI commands
- [ ] Argument completion (e.g., `--tag` values)
- [ ] Recursive subcommand discovery
- [ ] Command-specific help integration
- [ ] Shell command history
- [ ] Multi-command execution (`list-repos; validate-production`)
- [ ] Output capture and processing
- [ ] Shell scripting support

---

## Summary

The CLI shell system provides a powerful, universal admin interface for Python components with Typer CLIs. Key takeaways:

**For Users**:
- Start shell with `python -m <component> shell`
- Use CLI commands without prefixes
- Mix CLI commands, Python code, and magic commands
- Leverage convenience helpers for common tasks
- Session tracking is automatic and transparent

**For Developers**:
- Extend `AdminShell` for your component
- Override `_get_component_name()` to enable CLI discovery
- Add custom helpers, magics, and formatters
- Keep commands simple and focused
- Session tracking works automatically

**Architecture**:
- Oneiric provides universal base class
- Components extend for specific functionality
- Dynamic command discovery from Typer apps
- Input preprocessing routes CLI vs Python
- Session tracking via MCP events to Session-Buddy

The system is production-ready and used by Mahavishnu for workflow orchestration, pool management, and production validation.
