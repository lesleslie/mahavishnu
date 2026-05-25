# Debug Session: Mahavishnu BodaiComponentMCPClient → Akosha MCP Connection

## Issue Summary

**Problem**: `BodaiComponentMCPClient` in Mahavishnu hangs when calling `session.initialize()` when connecting to Akosha's MCP server at `http://localhost:8682/mcp`.

**Root Cause (IN PROGRESS)**: Session ID extraction issue - the MCP client's `streamable_http_client()` is receiving `session_id: None` despite the server returning a valid `mcp-session-id` header.

## What Works

1. **Direct httpx calls work perfectly** - Sending initialize POST, extracting session ID from response header, then calling tools with that session ID works fine:

```bash
# This works - direct httpx with manual session management
curl -X POST http://localhost:8682/mcp \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"initialize",...}' \
  -i  # Returns mcp-session-id header
# Then with session ID header:
curl -X POST http://localhost:8682/mcp \
  -H "mcp-session-id: <session_id>" \
  -d '{"jsonrpc":"2.0","method":"tools/call",...}'
```

2. **Server returns correct session ID** - The Akosha MCP server at port 8682 does return `mcp-session-id` header on initialize, and subsequent requests with that session ID work.

## What Doesn't Work

The official MCP Python client's `streamable_http_client()` and `ClientSession`:
- `session.initialize()` hangs (timeout after 5-10 seconds)
- Session ID shows as `None` even though server returns it in headers

## Key Files

### Mahavishnu Client
- `/Users/les/Projects/mahavishnu/mahavishnu/mcp/bodai_component_client.py` - The client being debugged

### Akosha Server
- `/Users/les/Projects/akosha/akosha/mcp/server.py` - FastMCP server (uses StreamableHTTPSessionManager)
- `/Users/les/Projects/akosha/akosha/mcp/tools/__init__.py` - Tool registration
- `/Users/les/Projects/akosha/akosha/mcp/tools/otel_tools.py` - OTel query tools (had a bug, fixed)

### MCP Library (venv)
- `/Users/les/Projects/akosha/.venv/lib/python3.13/site-packages/mcp/client/streamable_http.py` - Client transport
- `/Users/les/Projects/akosha/.venv/lib/python3.13/site-packages/mcp/server/streamable_http_manager.py` - Server session manager

## Debugging Log (Key Observations)

1. The server responds with `content-type: text/event-stream` and `mcp-session-id` header on initialize
2. Client's `_maybe_extract_session_id_from_response()` is called (logged "Received session ID: <id>")
3. But session still shows `SID=None` after `__aenter__()` returns
4. The post_writer task sends the initialized notification, then subsequent call_tool hangs

## Minimal Test Script

```python
import asyncio
from mcp.client.streamable_http import streamable_http_client
from mcp.client.session import ClientSession

async def test():
    ctx = streamable_http_client('http://localhost:8682/mcp', terminate_on_close=True)
    rs, ws, get_session_id = await ctx.__aenter__()
    print(f'Session ID: {get_session_id()}')  # Shows None!
    session = ClientSession(rs, ws)
    await session.initialize()  # Hangs here
    result = await session.call_tool('query_local_traces', {'system_id': 'mahavishnu', 'limit': 5})
    await ctx.__aexit__(None, None, None)

asyncio.run(test())
```

## Recent Fixes Applied

1. **Akosha otel_tools.py** - Changed function signature from `register_otel_query_tools(registry: Any, hot_store: Any)` to `register_otel_query_tools(app: Any, hot_store: Any)` because it was receiving a FastMCPToolRegistry instead of the app directly.

2. **Akosha __init__.py** - Updated call site to pass `app` instead of `registry`.

## Questions to Investigate

1. Why does `get_session_id()` return None even though `_maybe_extract_session_id_from_response()` is called and logs the session ID?
2. Is there a timing issue where the session ID is extracted but then lost before `get_session_id()` is called?
3. Is the initialized notification being sent correctly, and is the GET SSE stream being opened?

## Environment

- Mahavishnu venv: `/Users/les/Projects/mahavishnu/.venv`
- Akosha venv: `/Users/les/Projects/akosha/.venv`
- Akosha MCP running on port 8682 (two processes: PIDs 33399 and 22501)
- mcpt 1.27.1 in both venvs
- fastmcp 3.3.1 in Akosha venv

## Session Commands

```bash
# Check Akosha is running
ps aux | grep akosha | grep -v grep

# Health check
curl http://localhost:8682/health

# Direct MCP test with session
curl -X POST http://localhost:8682/mcp \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}' \
  -i
```