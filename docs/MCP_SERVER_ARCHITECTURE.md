# MCP Server Architecture Patterns

**Last Updated:** 2026-02-17
**Author:** Claude Sonnet 4.5 + lesleslie
**Status:** Production Ready
**Applies To:** mahavishnu, session-buddy, crackerjack

---

## Table of Contents

1. [Overview](#overview)
2. [Core Architecture Patterns](#core-architecture-patterns)
3. [Version Management](#version-management)
4. [Import Path Discipline](#import-path-discipline)
5. [Tool Registration Patterns](#tool-registration-patterns)
6. [Authorization & Security](#authorization--security)
7. [Testing Strategies](#testing-strategies)
8. [Deployment Patterns](#deployment-patterns)
9. [Troubleshooting Guide](#troubleshooting-guide)
10. [Best Practices Checklist](#best-practices-checklist)

---

## Overview

This document captures the architectural patterns and best practices for Model Context Protocol (MCP) servers across the mahavishnu ecosystem. These patterns have been validated across three production MCP servers:

- **Mahavishnu Orchestrator** (v0.2.0) - Multi-agent coordination
- **Session-Buddy** (v0.14.1) - Session management & memory
- **Crackerjack** (v0.53.3) - Quality assurance & testing

### Philosophy

1. **Single Source of Truth** - Version numbers come from `pyproject.toml`
2. **Import Discipline** - Relative imports follow strict conventions
3. **Security First** - All tools require authentication and authorization
4. **Testability** - Mock FastMCP for unit testing
5. **Observability** - Comprehensive logging and error tracking

---

## Core Architecture Patterns

### Pattern 1: Dynamic Version Loading

**Problem:** Hardcoded version strings become stale and diverge from package metadata.

**Solution:** Use `importlib.metadata` to load version dynamically.

```python
"""MCP Server Core Infrastructure."""

from importlib.metadata import version as pkg_version

# Get version from package metadata
try:
    __version__ = pkg_version("package-name")
except Exception:
    __version__ = "0.0.0-unknown"

# Use version when creating FastMCP server
from fastmcp import FastMCP

mcp_server = FastMCP(
    name="My Server",
    version=__version__,  # ✅ Dynamic, never stale
    lifespan=lifecycle_manager
)
```

**Benefits:**
- ✅ Version always matches `pyproject.toml`
- ✅ No manual updates needed when releasing
- ✅ Consistent across all MCP servers in ecosystem
- ✅ Fallback for development environments

**Implementation Locations:**
- `mahavishnu/mcp/server_core.py:112`
- `session-buddy/server_optimized.py:132`
- `crackerjack/mcp/server_core.py:139`

---

### Pattern 2: Server Core Class Pattern

**Problem:** Complex initialization logic scattered across multiple functions.

**Solution:** Encapsulate server lifecycle in a dedicated class.

```python
class FastMCPServer:
    """FastMCP server lifecycle management.

    Handles:
    - Server initialization
    - Tool registration
    - Lifecycle management
    - Health monitoring
    """

    def __init__(self, app=None, config=None):
        """Initialize the FastMCP server.

        Args:
            app: Optional MahavishnuApp instance (creates new one if None)
            config: Optional configuration object (used if app is None)
        """
        if app is None:
            self.app = MahavishnuApp(config)
        else:
            self.app = app

        # Initialize FastMCP with dynamic version
        self.server = FastMCP(
            name="Mahavishnu Orchestrator",
            version=__version__
        )

        # Register all tools
        self._register_tools()

    def _register_tools(self) -> None:
        """Register all tool modules with MCP server."""
        self._register_terminal_tools()
        self._register_session_buddy_tools()
        self._register_git_analytics_tools()
        # ... more tool registrations

    async def start(self, host: str = "127.0.0.1", port: int = 3000):
        """Start the MCP server."""
        await self.server.start(host=host, port=port)

    async def stop(self):
        """Stop the MCP server."""
        await self.server.stop()
```

**Benefits:**
- ✅ Clear separation of concerns
- ✅ Easy to test (mock app, config)
- ✅ Lifecycle management centralized
- ✅ Tool registration organized

---

### Pattern 3: Tool Module Registration Pattern

**Problem:** Tool registration becomes unwieldy as tools grow.

**Solution:** Separate tool modules with registration functions.

```python
# File: mahavishnu/mcp/tools/session_buddy_tools.py

from typing import Any
from ...mcp.auth import require_mcp_auth
from ...core.permissions import Permission, RBACManager

def register_session_buddy_tools(
    server,
    mcp_client,
    rbac_manager: RBACManager | None = None
):
    """Register Session Buddy integration tools with MCP server."""

    @server.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager,
        required_permission=Permission.READ_REPO,
        require_repo_param="project_path",
    )
    async def index_code_graph(
        project_path: str,
        include_docs: bool = True,
        user_id: str | None = None
    ) -> dict[str, Any]:
        """Index codebase structure for better context.

        Args:
            project_path: Path to the project to analyze
            include_docs: Whether to include documentation indexing
            user_id: Authenticated user ID (injected by @require_mcp_auth)

        Returns:
            Analysis results with indexed elements
        """
        # Tool implementation
        return {"status": "success", "result": {...}}

    # More tools...

    print("✅ Registered 7 Session Buddy integration tools")
```

**Usage in Server Core:**

```python
def _register_session_buddy_tools(self):
    """Register Session Buddy integration tools."""
    from ..mcp.tools.session_buddy_tools import register_session_buddy_tools

    register_session_buddy_tools(
        self.server,
        self.mcp_client,
        self.rbac_manager
    )
    logger.info("Registered Session Buddy integration tools")
```

**Benefits:**
- ✅ Tools organized by domain
- ✅ Clear dependency injection
- ✅ Easy to add/remove tool sets
- ✅ Authorization centralized per module

---

## Version Management

### Version Synchronization Across Ecosystem

All MCP servers MUST use dynamic version loading:

```python
# ✅ CORRECT - Dynamic version
from importlib.metadata import version as pkg_version

try:
    __version__ = pkg_version("package-name")
except Exception:
    __version__ = "0.0.0-unknown"

server = FastMCP("name", version=__version__)
```

```python
# ❌ WRONG - Hardcoded version
server = FastMCP("name", version="1.0.0")  # Becomes stale!
```

### Release Process

When releasing a new version:

1. **Update `pyproject.toml`:**
   ```toml
   [project]
   name = "mahavishnu"
   version = "0.3.0"  # Bump version
   ```

2. **Commit and tag:**
   ```bash
   git add pyproject.toml
   git commit -m "bump: v0.3.0"
   git tag v0.3.0
   ```

3. **Build and publish:**
   ```bash
   uv build
   uv publish
   ```

4. **Verify MCP server reports correct version:**
   ```bash
   python -m mahavishnu mcp start
   # Should show: Mahavishnu Orchestrator, 0.3.0
   ```

---

## Import Path Discipline

### The "Dot Count" Rule

When importing from within `package/mcp/tools/`:

```python
# Directory structure:
# package/
# ├── core/
# │   ├── auth.py
# │   └── permissions.py
# ├── mcp/
# │   ├── auth.py
# │   └── tools/
# │       └── my_tool.py  ← We are here
# └── messaging.py

# ✅ CORRECT - Count the directories
from ...core.permissions import Permission      # Up 3 levels to package/, then core/permissions
from ...messaging import MessagePriority        # Up 3 levels to package/, then messaging
from ...mcp.auth import require_mcp_auth        # Up 3 levels to package/, then mcp/auth

# ❌ WRONG - Too few dots
from ..core.permissions import Permission       # Resolves to package.mcp.core (doesn't exist)
```

**Visual Guide:**

```
package/ (level 0 - package root)
├── core/ (level 1)
│   └── auth.py
├── mcp/ (level 1)
│   ├── auth.py
│   └── tools/ (level 2)
│       └── my_tool.py (level 3) ← Current file
└── messaging.py (level 1)

To reach level 0: ... (3 dots up from level 3)
Then descend: ...core.auth (down to core, then auth)
```

### Import Style Guidelines

1. **Standard Library First:**
   ```python
   import asyncio
   from pathlib import Path
   from typing import Any
   ```

2. **Third-Party Packages:**
   ```python
   from fastmcp import FastMCP
   from pydantic import BaseModel
   ```

3. **Local Imports (sorted by depth):**
   ```python
   # Deep imports first (more dots)
   from ...core.permissions import Permission
   from ...messaging import MessagePriority
   from ...mcp.auth import require_mcp_auth

   # Then shallower imports
   from ..adapters import AdapterFactory
   from ..utils import helper_function
   ```

### Testing Import Paths

Add import path validation to CI:

```python
# tests/test_import_paths.py

import sys
from pathlib import Path

def test_import_paths():
    """Verify all modules can be imported."""
    project_root = Path(__file__).parent.parent

    # Add project to path
    sys.path.insert(0, str(project_root))

    # Try importing critical modules
    from mahavishnu.mcp.server_core import FastMCPServer
    from mahavishnu.mcp.tools.session_buddy_tools import register_session_buddy_tools
    from mahavishnu.mcp.tools.git_analytics import register_git_analytics_tools

    # If we get here, all imports succeeded
    assert True
```

---

## Tool Registration Patterns

### Pattern 1: Authorization Decorator

All tools MUST use `@require_mcp_auth` decorator:

```python
from ...mcp.auth import require_mcp_auth
from ...core.permissions import Permission, RBACManager

@server.tool()
@require_mcp_auth(
    rbac_manager=rbac_manager,
    required_permission=Permission.READ_REPO,
    require_repo_param="project_path",
)
async def sensitive_operation(
    project_path: str,
    user_id: str | None = None
) -> dict[str, Any]:
    """Perform operation requiring authorization."""
    # user_id is injected by decorator if authentication succeeds
    return {"status": "success"}
```

**Authorization Flow:**

1. **Authentication Check:**
   - Decorator verifies `user_id` parameter exists
   - Returns error if missing: `"Authentication required"`

2. **Authorization Check:**
   - Extracts repo path from `require_repo_param`
   - Calls `rbac_manager.check_permission()`
   - Returns error if denied: `"Authorization denied"`

3. **Audit Logging:**
   - All access attempts logged to `data/audit.log`
   - Sensitive parameters redacted automatically

### Pattern 2: Error Handling

All tools should return structured error responses:

```python
@server.tool()
@require_mcp_auth(rbac_manager=rbac_manager)
async def my_tool(param: str, user_id: str | None = None) -> dict[str, Any]:
    """Tool with proper error handling."""
    try:
        # Attempt operation
        result = await do_something(param)

        return {
            "status": "success",
            "result": result
        }
    except ValueError as e:
        return {
            "status": "error",
            "error": f"Invalid parameter: {e}",
            "error_code": "INVALID_PARAM"
        }
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return {
            "status": "error",
            "error": "Operation failed",
            "error_code": "INTERNAL_ERROR"
        }
```

**Error Response Schema:**

```python
{
    "status": "error" | "success",
    "error": str | None,           # Human-readable message
    "error_code": str | None,      # Machine-readable code
    "result": Any | None           # Success result
}
```

### Pattern 3: Resource Management

Tools that access files/resources should use context managers:

```python
@server.tool()
@require_mcp_auth(
    rbac_manager=rbac_manager,
    required_permission=Permission.READ_REPO,
    require_repo_param="repo_path",
)
async def analyze_repository(
    repo_path: str,
    user_id: str | None = None
) -> dict[str, Any]:
    """Analyze repository with proper resource management."""
    try:
        from pathlib import Path

        repo = Path(repo_path)

        # Validate path exists
        if not repo.exists():
            return {
                "status": "error",
                "error": f"Path does not exist: {repo_path}",
                "error_code": "NOT_FOUND"
            }

        # Use context manager for file operations
        with open(repo / "README.md") as f:
            readme_content = f.read()

        # Process and return
        return {
            "status": "success",
            "result": {"readme": readme_content[:500]}
        }

    except OSError as e:
        return {
            "status": "error",
            "error": f"File system error: {e}",
            "error_code": "IO_ERROR"
        }
```

---

## Authorization & Security

### RBAC Integration Pattern

All MCP servers MUST integrate with RBAC system:

```python
# mahavishnu/core/permissions.py

class Permission(str, Enum):
    """Permission types for repository access control."""
    READ_REPO = "read_repo"       # Read repository contents
    WRITE_REPO = "write_repo"     # Modify repository
    ADMIN_REPO = "admin_repo"     # Administrative operations

class RBACManager:
    """Role-Based Access Control manager."""

    async def check_permission(
        self,
        user_id: str,
        repo: str,
        permission: Permission
    ) -> bool:
        """Check if user has permission for repo.

        Args:
            user_id: User identifier
            repo: Repository path
            permission: Required permission

        Returns:
            True if user has permission, False otherwise
        """
        # Implementation checks:
        # 1. User role assignments
        # 2. Repository ownership
        # 3. Team membership
        # 4. Explicit grants/revocations
        ...
```

### Audit Logging Pattern

All security events MUST be logged:

```python
# mahavishnu/mcp/auth.py

class AuditLogger:
    """Audit logger for security events."""

    def log(
        self,
        event_type: str,
        user_id: str | None,
        tool_name: str,
        params: dict[str, Any],
        result: str = "success",
        error: str | None = None,
    ) -> None:
        """Log security event.

        Args:
            event_type: Type of event ("tool_access", "auth_failure", "auth_denied")
            user_id: User identifier (None if unauthenticated)
            tool_name: Name of the tool being accessed
            params: Tool parameters (sensitive values will be redacted)
            result: Result of the operation ("success", "failure", "denied")
            error: Error message if operation failed
        """
        # Redact sensitive parameters
        safe_params = self._redact_secrets(params)

        # Write to audit log
        log_entry = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "event_type": event_type,
            "user_id": user_id,
            "tool_name": tool_name,
            "params": safe_params,
            "result": result,
            "error": error,
        }

        # Write to audit log file
        with open(self.log_path, "a") as f:
            f.write(json.dumps(log_entry) + "\n")

        # Also log to standard logger
        logger.info(
            f"[{event_type}] user={user_id}, tool={tool_name}, result={result}"
        )
```

**Audit Log Format:**

```json
{
  "timestamp": "2026-02-17T10:15:00.000Z",
  "event_type": "tool_access",
  "user_id": "user@example.com",
  "tool_name": "index_code_graph",
  "params": {
    "project_path": "/path/to/repo",
    "include_docs": true
  },
  "result": "success",
  "error": null
}
```

**Redacted Sensitive Parameters:**

```python
SENSITIVE_KEYS = {
    "password", "token", "key", "secret", "credential",
    "api_key", "auth_token", "access_token", "ssh_key"
}

# Before redaction:
{"password": "my_secret_password"}

# After redaction:
{"password": "***REDACTED***"}
```

---

## Testing Strategies

### Pattern 1: Mock FastMCP for Testing

```python
# tests/conftest.py

import pytest
from unittest.mock import Mock

class MockFastMCP:
    """Mock FastMCP server for testing."""

    def __init__(self, name: str, version: str = "0.0.0-test", **kwargs):
        self.name = name
        self.version = version
        self.tools_registered = []

    def tool(self):
        """Decorator for registering tools."""
        def decorator(func):
            self.tools_registered.append(func.__name__)
            return func
        return decorator

@pytest.fixture
def mock_mcp_server():
    """Mock FastMCP server for testing."""
    return MockFastMCP("test-server", version="1.0.0-test")

@pytest.fixture
def mock_rbac_manager():
    """Mock RBAC manager."""
    manager = Mock()
    manager.check_permission = AsyncMock(return_value=True)
    return manager
```

### Pattern 2: Tool Registration Tests

```python
# tests/test_tool_registration.py

import pytest
from mahavishnu.mcp.tools.session_buddy_tools import register_session_buddy_tools

@pytest.mark.asyncio
async def test_session_buddy_tools_registration(mock_mcp_server, mock_rbac_manager):
    """Test Session Buddy tools register correctly."""
    # Register tools
    register_session_buddy_tools(
        mock_mcp_server,
        mcp_client=None,
        rbac_manager=mock_rbac_manager
    )

    # Verify tools were registered
    assert "index_code_graph" in mock_mcp_server.tools_registered
    assert "get_function_context" in mock_mcp_server.tools_registered
    assert "find_related_code" in mock_mcp_server.tools_registered

    # Should have 7 tools total
    assert len(mock_mcp_server.tools_registered) == 7
```

### Pattern 3: Authorization Tests

```python
# tests/test_authorization.py

import pytest
from mahavishnu.mcp.auth import require_mcp_auth
from mahavishnu.core.permissions import Permission

@pytest.mark.asyncio
async def test_require_auth_with_no_user_id():
    """Test that tool rejects requests without user_id."""
    @require_mcp_auth(rbac_manager=None)
    async def test_tool(user_id: str | None = None):
        return {"status": "success"}

    # Call without user_id
    result = await test_tool()

    # Should return error
    assert result["status"] == "error"
    assert result["error_code"] == "AUTH_REQUIRED"

@pytest.mark.asyncio
async def test_require_auth_with_valid_user(mock_rbac_manager):
    """Test that tool accepts requests with valid user_id."""
    mock_rbac_manager.check_permission = AsyncMock(return_value=True)

    @require_mcp_auth(
        rbac_manager=mock_rbac_manager,
        required_permission=Permission.READ_REPO,
        require_repo_param="repo_path"
    )
    async def test_tool(repo_path: str, user_id: str | None = None):
        return {"status": "success"}

    # Call with valid parameters
    result = await test_tool(
        repo_path="/path/to/repo",
        user_id="user@example.com"
    )

    # Should succeed
    assert result["status"] == "success"
```

### Pattern 4: Import Path Tests

```python
# tests/test_import_paths.py

def test_mcp_tool_imports():
    """Test all MCP tool modules can be imported."""
    # These should not raise ImportError
    from mahavishnu.mcp.tools.session_buddy_tools import register_session_buddy_tools
    from mahavishnu.mcp.tools.git_analytics import register_git_analytics_tools
    from mahavishnu.mcp.tools.terminal_tools import register_terminal_tools

def test_relative_import_depth():
    """Test that relative imports have correct depth."""
    import mahavishnu.mcp.tools.session_buddy_tools as sbt

    # Check that the module can import from core (3 dots up)
    from mahavishnu.core.permissions import Permission

    # If we got here, imports work correctly
    assert Permission.READ_REPO is not None
```

---

## Deployment Patterns

### Development Mode

```bash
# Start with auto-reload on file changes
uv run --extra dev-tool python -m mahavishnu mcp start \
    --host 127.0.0.1 \
    --port 8680
```

### Production Mode

```bash
# Use uvicorn for production
uvicorn mahavishnu.mcp.server_core:app \
    --host 0.0.0.0 \
    --port 8680 \
    --workers 4 \
    --log-level info
```

### Docker Deployment

```dockerfile
# Dockerfile
FROM python:3.13-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy application
COPY . .

# Expose MCP port
EXPOSE 8680

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8680/health || exit 1

# Run server
CMD ["uv", "run", "python", "-m", "mahavishnu", "mcp", "start", "--port", "8680"]
```

### Service Configuration

```ini
# /etc/systemd/system/mahavishnu-mcp.service
[Unit]
Description=Mahavishnu MCP Server
After=network.target

[Service]
Type=simple
User=mahavishnu
WorkingDirectory=/opt/mahavishnu
Environment="PATH=/opt/mahavishnu/.venv/bin"
ExecStart=/opt/mahavishnu/.venv/bin/python -m mahavishnu mcp start --port 8680
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

---

## Troubleshooting Guide

### Issue 1: "ModuleNotFoundError: No module named 'package.mcp.core'"

**Symptom:**
```
ModuleNotFoundError: No module named 'mahavishnu.mcp.core'
```

**Cause:** Incorrect number of dots in relative import.

**Solution:**
```python
# ❌ WRONG (2 dots from package/mcp/tools/)
from ..core.permissions import Permission

# ✅ CORRECT (3 dots from package/mcp/tools/)
from ...core.permissions import Permission
```

**Verification:**
```bash
# Check current directory
pwd
# Should show: .../package/mcp/tools/

# Count levels to package root
# tools/ = level 1
# mcp/ = level 2
# package/ = level 3 ← Need to go up 3 levels
```

---

### Issue 2: Version mismatch between server and pyproject.toml

**Symptom:**
```
MCP Server: Mahavishnu Orchestrator, 1.0.0  # But pyproject.toml says 0.2.0
```

**Cause:** Hardcoded version in FastMCP initialization.

**Solution:**
```python
# ❌ WRONG
server = FastMCP("name", version="1.0.0")

# ✅ CORRECT
from importlib.metadata import version as pkg_version
try:
    __version__ = pkg_version("package-name")
except Exception:
    __version__ = "0.0.0-unknown"

server = FastMCP("name", version=__version__)
```

---

### Issue 3: "ImportError: cannot import name 'require_mcp_auth'"

**Symptom:**
```
ImportError: cannot import name 'require_mcp_auth' from 'mahavishnu.core.auth'
```

**Cause:** Importing from wrong module - `require_mcp_auth` is in `mcp/auth.py`, not `core/auth.py`.

**Solution:**
```python
# ❌ WRONG
from ...core.auth import require_mcp_auth

# ✅ CORRECT
from ...mcp.auth import require_mcp_auth
```

**Module Locations:**
- `core/auth.py` - Application authentication (MultiAuthHandler, AuthenticationError)
- `mcp/auth.py` - MCP tool authorization (require_mcp_auth decorator, AuditLogger)

---

### Issue 4: Tools not accessible after server start

**Symptom:** Server starts but tools don't appear in tool list.

**Cause:** Tool registration not called or failed silently.

**Solution:**
```python
# Add debug logging to tool registration
def _register_tools(self):
    """Register all tool modules."""
    logger.info("Registering tools...")

    self._register_terminal_tools()
    logger.info("✅ Terminal tools registered")

    self._register_session_buddy_tools()
    logger.info("✅ Session Buddy tools registered")

    # ... more registrations

    logger.info(f"Total tools registered: {len(self.server.tools)}")
```

**Verification:**
```bash
# Start server with verbose logging
RUST_LOG=debug python -m mahavishnu mcp start

# Check tool registration in logs
grep "tools registered" /tmp/mcp-mahavishnu.log
```

---

### Issue 5: Port already in use

**Symptom:**
```
OSError: [Errno 48] Address already in use
```

**Cause:** Another process using the port.

**Solution:**
```bash
# Find process using port 8680
lsof -i :8680

# Kill the process
kill <PID>

# Or use a different port
python -m mahavishnu mcp start --port 8681
```

---

## Best Practices Checklist

### Development Phase

- [ ] **Dynamic Version Loading** - Use `importlib.metadata.version()`
- [ ] **Import Path Discipline** - Count dots correctly for relative imports
- [ ] **Authorization Decorator** - All tools use `@require_mcp_auth`
- [ ] **Error Handling** - Structured error responses with status codes
- [ ] **Type Hints** - Full type annotations on tool functions
- [ ] **Docstrings** - Comprehensive docstrings for all tools
- [ ] **Logging** - Appropriate logging levels (info, warning, error)

### Testing Phase

- [ ] **Mock FastMCP** - Use mock server for unit tests
- [ ] **Tool Registration Tests** - Verify tools register correctly
- [ ] **Authorization Tests** - Test auth decorator behavior
- [ ] **Import Path Tests** - Verify all imports work
- [ ] **Integration Tests** - Test server start/stop lifecycle
- [ ] **Error Case Tests** - Test error handling paths

### Deployment Phase

- [ ] **Version Check** - Confirm server reports correct version
- [ ] **Port Configuration** - Document default port (8680 for mahavishnu)
- [ ] **Health Checks** - Implement `/health` endpoint
- [ ] **Audit Logging** - Verify audit logs are written
- [ ] **Graceful Shutdown** - Handle SIGTERM/SIGINT correctly
- [ ] **Monitoring** - Export metrics for observability

### Documentation Phase

- [ ] **README** - Quick start guide
- [ ] **API Docs** - Tool reference documentation
- [ ] **Architecture** - System design documentation
- [ ] **Changelog** - Version history and changes
- [ ] **Contributing** - Development workflow guide

---

## Quick Reference

### Common Import Patterns

```python
# From package/mcp/tools/ directory:

# Import from core/
from ...core.permissions import Permission, RBACManager
from ...core.auth import AuthenticationError
from ...core.app import MahavishnuApp

# Import from mcp/
from ...mcp.auth import require_mcp_auth, AuditLogger
from ...mcp.server_core import FastMCPServer

# Import from package root
from ...messaging import MessagePriority
from ...terminal.manager import TerminalManager
```

### Server Initialization Template

```python
"""MCP Server template with best practices."""

from importlib.metadata import version as pkg_version
from fastmcp import FastMCP
from typing import Any

# Get version dynamically
try:
    __version__ = pkg_version("your-package")
except Exception:
    __version__ = "0.0.0-unknown"

# Create server with lifecycle
mcp = FastMCP(
    name="Your Server",
    version=__version__,
    lifespan=lifespan_manager
)

# Register tools with authorization
@mcp.tool()
@require_mcp_auth(
    rbac_manager=rbac_manager,
    required_permission=Permission.READ_REPO,
    require_repo_param="repo_path"
)
async def your_tool(
    repo_path: str,
    user_id: str | None = None
) -> dict[str, Any]:
    """Tool description."""
    try:
        # Implementation
        return {"status": "success", "result": {...}}
    except Exception as e:
        return {"status": "error", "error": str(e)}
```

---

**Document Version:** 1.0.0
**Last Reviewed:** 2026-02-17
**Next Review:** 2026-03-17
**Maintainer:** lesleslie
