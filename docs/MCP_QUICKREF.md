# MCP Server Quick Reference

**Last Updated:** 2026-02-17

## Import Path Cheat Sheet

```
Location: package/mcp/tools/my_tool.py

┌─────────────────────────────────────────────────┐
│ To import from...    Use this import...         │
├─────────────────────────────────────────────────┤
│ package/core/auth.py   from ...core.auth import │
│ package/core/permissions.py from ...core.permissions import │
│ package/mcp/auth.py     from ...mcp.auth import │
│ package/messaging.py   from ...messaging import │
│ package/terminal/      from ...terminal. import │
└─────────────────────────────────────────────────┘
```

**Rule:** 3 dots (`...`) = up 3 levels from `package/mcp/tools/` to `package/` root

## Version Loading Template

```python
from importlib.metadata import version as pkg_version

try:
    __version__ = pkg_version("package-name")
except Exception:
    __version__ = "0.0.0-unknown"

server = FastMCP("name", version=__version__)
```

## Tool Template

```python
@server.tool()
@require_mcp_auth(
    rbac_manager=rbac_manager,
    required_permission=Permission.READ_REPO,
    require_repo_param="repo_path",
)
async def my_tool(
    repo_path: str,
    user_id: str | None = None
) -> dict[str, Any]:
    """Tool description.

    Args:
        repo_path: Repository path
        user_id: Authenticated user (injected)

    Returns:
        Structured response
    """
    try:
        result = await do_work(repo_path)
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}
```

## Error Response Format

```python
{
    "status": "success" | "error",
    "result": Any,        # On success
    "error": str,         # On error
    "error_code": str     # On error
}
```

## Common Issues & Fixes

| Issue | Cause | Fix |
|-------|-------|-----|
| `ModuleNotFoundError: package.mcp.core` | Wrong dot count | Use `...core` not `..core` |
| `ImportError: require_mcp_auth` | Wrong module | Use `...mcp.auth` not `...core.auth` |
| Version shows `1.0.0` not `0.2.0` | Hardcoded version | Use `importlib.metadata` |
| Port already in use | Process on port | `lsof -i :8680` then `kill <PID>` |

## Server Ports

- **Mahavishnu:** 8680
- **Session-Buddy:** 8678
- **Crackerjack:** 8676

## Testing Commands

```bash
# Start server
python -m mahavishnu mcp start --port 8680

# Test endpoint
curl http://127.0.0.1:8680/health

# Check logs
tail -f /tmp/mcp-mahavishnu.log

# Verify version
curl http://127.0.0.1:8680/mcp
```

## Audit Log Location

```bash
# View audit log
tail -f data/audit.log

# Search for user activity
grep "user@example.com" data/audit.log

# Check denied access
grep "auth_denied" data/audit.log
```

---

**Full Documentation:** See [MCP_SERVER_ARCHITECTURE.md](./MCP_SERVER_ARCHITECTURE.md)
