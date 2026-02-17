# MCP Server Architecture Diagrams

**Last Updated:** 2026-02-17

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Mahavishnu Ecosystem                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ Mahavishnu   │  │Session-Buddy │  │ Crackerjack  │          │
│  │ MCP Server   │  │  MCP Server  │  │  MCP Server  │          │
│  │   Port 8680  │  │  Port 8678   │  │  Port 8676   │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                 │                 │                   │
│         └─────────────────┴─────────────────┘                   │
│                           │                                     │
│                    ┌──────▼──────┐                               │
│                    │ FastMCP 3.0 │                               │
│                    │   Framework  │                               │
│                    └─────────────┘                               │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Single MCP Server Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     MCP Server (e.g., mahavishnu)             │
│                         Version: 0.2.0                        │
├──────────────────────────────────────────────────────────────┤
│                                                                │
│  ┌─────────────────────────────────────────────────────┐     │
│  │           FastMCPServer Class                        │     │
│  │  ┌─────────────────────────────────────────────┐    │     │
│  │  │  FastMCP Instance                             │    │     │
│  │  │  - name: "Mahavishnu Orchestrator"           │    │     │
│  │  │  - version: __version__ (dynamic)            │    │     │
│  │  │  - transport: HTTP (port 8680)               │    │     │
│  │  └─────────────────────────────────────────────┘    │     │
│  │                                                      │     │
│  │  ┌─────────────────────────────────────────────┐    │     │
│  │  │  Tool Registration                            │    │     │
│  │  │  ┌──────────────┐  ┌──────────────┐         │    │     │
│  │  │  │ Session Buddy│  │ Git Analytics│         │    │     │
│  │  │  │    Tools     │  │    Tools     │         │    │     │
│  │  │  └──────────────┘  └──────────────┘         │    │     │
│  │  │  ┌──────────────┐  ┌──────────────┐         │    │     │
│  │  │  │  Terminal    │  │    Worker    │         │    │     │
│  │  │  │    Tools     │  │    Tools     │         │    │     │
│  │  │  └──────────────┘  └──────────────┘         │    │     │
│  │  └─────────────────────────────────────────────┘    │     │
│  │                                                      │     │
│  │  ┌─────────────────────────────────────────────┐    │     │
│  │  │  Authorization Layer                          │    │     │
│  │  │  - RBACManager                                │    │     │
│  │  │  - @require_mcp_auth decorator                │    │     │
│  │  │  - AuditLogger (data/audit.log)               │    │     │
│  │  └─────────────────────────────────────────────┘    │     │
│  └─────────────────────────────────────────────────────┘     │
│                                                                │
│  ┌─────────────────────────────────────────────────────┐     │
│  │           MahavishnuApp Instance                     │     │
│  │  - Configuration (settings/mahavishnu.yaml)          │     │
│  │  - Adapters (agno, worker, prefect)                │     │
│  │  - Storage (dhruva, oneiric, akosha)               │     │
│  └─────────────────────────────────────────────────────┘     │
│                                                                │
└──────────────────────────────────────────────────────────────┘
```

## Tool Authorization Flow

```
┌──────────────┐
│ MCP Client   │
│  Request     │
└──────┬───────┘
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│  @require_mcp_auth Decorator                              │
│  ┌─────────────────────────────────────────────────┐     │
│  │ 1. Check Authentication                           │     │
│  │    - user_id parameter exists?                   │     │
│  │    - No → Return AUTH_REQUIRED error             │     │
│  └─────────────────────────────────────────────────┘     │
│                          │                                │
│                          ▼                                │
│  ┌─────────────────────────────────────────────────┐     │
│  │ 2. Check Authorization                            │     │
│  │    - Extract repo_path from params                │     │
│  │    - Call rbac_manager.check_permission()         │     │
│  │    - No permission → Return AUTH_DENIED error     │     │
│  └─────────────────────────────────────────────────┘     │
│                          │                                │
│                          ▼                                │
│  ┌─────────────────────────────────────────────────┐     │
│  │ 3. Log to Audit Logger                            │     │
│  │    - event_type: "tool_access"                    │     │
│  │    - user_id, tool_name, params                   │     │
│  │    - result: "success" / "denied"                 │     │
│  │    - Write to data/audit.log                      │     │
│  └─────────────────────────────────────────────────┘     │
│                          │                                │
│                          ▼                                │
│  ┌─────────────────────────────────────────────────┐     │
│  │ 4. Execute Tool Function                         │     │
│  │    - Call original function                      │     │
│  │    - Return result to client                      │     │
│  └─────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────┘
```

## Import Path Dependencies

```
package/
│
├── core/
│   ├── auth.py                          ← MultiAuthHandler, AuthenticationError
│   ├── permissions.py                   ← Permission, RBACManager
│   └── app.py                           ← MahavishnuApp
│
├── mcp/
│   ├── auth.py                          ← require_mcp_auth, AuditLogger
│   ├── server_core.py                   ← FastMCPServer class
│   └── tools/
│       └── my_tool.py
│           │
│           └── Importing from core/:
│               from ...core.permissions import Permission
│               from ...core.auth import AuthenticationError
│
│           └── Importing from mcp/:
│               from ...mcp.auth import require_mcp_auth
│
│           └── Importing from root:
│               from ...messaging import MessagePriority
│
└── messaging.py                         ← MessagePriority
```

**Relative Import Math:**

```
Current Location: package/mcp/tools/my_tool.py
Target Location: package/core/permissions.py

Path Analysis:
  my_tool.py  →  tools/     (1 up)
  tools/      →  mcp/       (1 up)
  mcp/        →  package/   (1 up)

Total: 3 levels up = ...
Then: 1 level down to core/ = core
Then: 1 level down to permissions.py = permissions

Result: from ...core.permissions import Permission
```

## Version Management Flow

```
┌─────────────────┐
│ pyproject.toml  │
│ version = 0.2.0 │
└────────┬────────┘
         │
         │ Build & Install
         ▼
┌─────────────────┐
│ Python Package  │
│ Metadata stored │
└────────┬────────┘
         │
         │ importlib.metadata.version()
         ▼
┌─────────────────────────────────────┐
│  MCP Server Initialization          │
│  ┌─────────────────────────────┐    │
│  │ __version__ = pkg_version(  │    │
│  │   "mahavishnu"              │    │
│  │ )                           │    │
│  │ # Returns: "0.2.0"          │    │
│  └─────────────────────────────┘    │
│           │                           │
│           ▼                           │
│  ┌─────────────────────────────┐    │
│  │ FastMCP(                    │    │
│  │   name="Mahavishnu...",     │    │
│  │   version=__version__       │    │
│  │ )                           │    │
│  └─────────────────────────────┘    │
└─────────────────────────────────────┘
         │
         │ Server Startup
         ▼
┌─────────────────────────────────────┐
│  Server Banner Displayed             │
│  Mahavishnu Orchestrator, 0.2.0     │
└─────────────────────────────────────┘
```

## Testing Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Test Suite                          │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  Unit Tests (pytest)                                     │
│  ┌───────────────────────────────────────────────┐       │
│  │  MockFastMCP                                  │       │
│  │  ┌─────────────────────────────────────────┐  │       │
│  │  │ - Mock tool decorator                   │  │       │
│  │  │ - Track registered tools                 │  │       │
│  │  │ - Simulate auth decorator               │  │       │
│  │  └─────────────────────────────────────────┘  │       │
│  └───────────────────────────────────────────────┘       │
│                           │                               │
│                           ▼                               │
│  ┌───────────────────────────────────────────────┐       │
│  │  Test Categories                              │       │
│  │  - Tool registration tests                   │       │
│  │  - Authorization tests                       │       │
│  │  - Import path tests                         │       │
│  │  - Error handling tests                      │       │
│  └───────────────────────────────────────────────┘       │
│                                                           │
│  Integration Tests                                      │
│  ┌───────────────────────────────────────────────┐       │
│  │  Test Server Lifecycle                        │       │
│  │  - Start server on test port                  │       │
│  │  - Register real tools                        │       │
│  │  - Make HTTP requests to endpoints            │       │
│  │  - Verify responses                           │       │
│  │  - Stop server                                │       │
│  └───────────────────────────────────────────────┘       │
│                                                           │
└─────────────────────────────────────────────────────────┘
```

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Production Environment                │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Docker Container / Systemd Service             │    │
│  │  ┌─────────────────────────────────────────┐     │    │
│  │  │  Python 3.13 Runtime                     │     │    │
│  │  │  ┌───────────────────────────────────┐   │     │    │
│  │  │  │  MCP Server Process               │   │     │    │
│  │  │  │  - uvicorn worker (×4)            │   │     │    │
│  │  │  │  - FastMCP HTTP server            │   │     │    │
│  │  │  │  - Port 8680                       │   │     │    │
│  │  │  └───────────────────────────────────┘   │     │    │
│  │  │                                          │     │    │
│  │  │  ┌───────────────────────────────────┐   │     │    │
│  │  │  │  Health Check Endpoint            │   │     │    │
│  │  │  │  GET /health → {"status": "ok"}   │   │     │    │
│  │  │  └───────────────────────────────────┘   │     │    │
│  │  └─────────────────────────────────────────┘     │    │
│  │                                                  │    │
│  │  ┌─────────────────────────────────────────┐     │    │
│  │  │  Logging                                 │     │    │
│  │  │  - stdout → journald (systemd)           │     │    │
│  │  │  - audit.log → persistent storage        │     │    │
│  │  │  - metrics → Prometheus                 │     │    │
│  │  └─────────────────────────────────────────┘     │    │
│  └─────────────────────────────────────────────────┘    │
│                                                           │
│  Monitoring & Observability                              │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Grafana Dashboard                              │    │
│  │  - Server health status                        │    │
│  │  - Request rate / latency                      │    │
│  │  - Error rates                                 │    │
│  │  - Authorization audit log                     │    │
│  └─────────────────────────────────────────────────┘    │
│                                                           │
└─────────────────────────────────────────────────────────┘
```

## Error Handling Flow

```
┌──────────────┐
│ Client Request│
└──────┬───────┘
       │
       ▼
┌──────────────────┐     ┌──────────────┐
│ Validation Check │────▶│ Invalid?     │
│ - Required params│     │ Return Error │
│ - Auth tokens    │     └──────────────┘
└──────┬───────────┘
       │ Valid
       ▼
┌──────────────────┐     ┌──────────────┐
│ Auth Check       │────▶│ Denied?      │
│ - user_id exists │     │ Return 403   │
│ - Has permission │     └──────────────┘
└──────┬───────────┘
       │ Authorized
       ▼
┌──────────────────┐
│ Tool Execution   │
│ - Try block      │
│ - Business logic │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐     ┌──────────────┐
│ Success?         │────▶│ Exception?   │
│ Return result    │     │ Log & Return │
└──────────────────┘     │ Error        │
                         └──────────────┘
```

## File System Layout

```
/opt/mahavishnu/
│
├── .venv/                    # Virtual environment
│   └── lib/python3.13/site-packages/
│       ├── mahavishnu/       # Package installed
│       │   ├── mcp/
│       │   │   ├── server_core.py
│       │   │   ├── auth.py
│       │   │   └── tools/
│       │   │       ├── session_buddy_tools.py
│       │   │       ├── git_analytics.py
│       │   │       └── terminal_tools.py
│       │   ├── core/
│       │   │   ├── auth.py
│       │   │   ├── permissions.py
│       │   │   └── app.py
│       │   └── ...
│       └── fastmcp/
│
├── data/
│   ├── audit.log             # Security audit trail
│   └── (other runtime data)
│
├── logs/
│   ├── mcp-server.log        # Server logs
│   └── error.log             # Error logs
│
├── settings/
│   └── mahavishnu.yaml       # Configuration
│
├── pyproject.toml            # Package metadata (version source)
└── uv.lock                   # Dependency lock file
```

---

**Document Version:** 1.0.0
**Companion Documents:**
- [MCP_SERVER_ARCHITECTURE.md](./MCP_SERVER_ARCHITECTURE.md) - Full documentation
- [MCP_QUICKREF.md](./MCP_QUICKREF.md) - Quick reference card
