# Fresh Session Prompt: Debug BodaiComponentMCPClient Session Hang

Copy and paste this prompt into a new Claude Code session to continue debugging:

______________________________________________________________________

## Context

You've been debugging a connection issue between Mahavishnu's `BodaiComponentMCPClient` and Akosha's MCP server at `http://localhost:8682/mcp`.

The problem: When using the official MCP Python client's `streamable_http_client()` + `ClientSession`, the `session.initialize()` call hangs and `get_session_id()` returns `None`, even though direct httpx calls work perfectly and the server does return a valid `mcp-session-id` header.

## What's Working

Direct httpx calls with manual session ID extraction work fine:

```bash
# Get session ID
curl -X POST http://localhost:8682/mcp \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}' \
  -i

# Use the session ID from mcp-session-id header in subsequent requests
curl -X POST http://localhost:8682/mcp \
  -H "mcp-session-id: <session_id>" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"query_local_traces","arguments":{"system_id":"mahavishnu","limit":5}},"id":2}'
```

## Your Task

Debug why the official MCP client transport doesn't work while direct httpx does.

### Key files to examine

1. **Client transport** (in Mahavishnu's venv):

   ```
   /Users/les/Projects/mahavishnu/.venv/lib/python3.13/site-packages/mcp/client/streamable_http.py
   ```

   Specifically the `_maybe_extract_session_id_from_response()` method at line 173 and how the session_id is propagated.

1. **Server session manager** (in Akosha's venv):

   ```
   /Users/les/Projects/akosha/.venv/lib/python3.13/site-packages/mcp/server/streamable_http_manager.py
   ```

   How it handles the initialize request and returns the session ID header.

1. **Mahavishnu client**:

   ```
   /Users/les/Projects/mahavishnu/mahavishnu/mcp/bodai_component_client.py
   ```

   The client code (this works with direct httpx, so focus on the MCP client library integration).

### Debugging Steps to Try

1. **Add debug logging** to `streamable_http.py` around session ID extraction to trace what's happening

1. **Check the timing** - is the session ID being extracted but then overwritten/lost before `get_session_id()` is called?

1. **Compare the two approaches**:

   - Working: direct httpx POST → extract header → use session ID
   - Not working: streamable_http_client → __aenter__() → get_session_id() returns None

1. **Check for anyio task group issues** - the `post_writer` task runs in a different task than the main code. Could there be a race condition?

1. **Verify the initialized notification** is being sent correctly after initialize()

### Test Script

Run this minimal test and see if you can figure out where the session ID is being lost:

```python
import asyncio
from mcp.client.streamable_http import streamable_http_client, StreamableHTTPTransport
from mcp.client.session import ClientSession

async def test():
    ctx = streamable_http_client('http://localhost:8682/mcp', terminate_on_close=True)
    rs, ws, get_session_id = await ctx.__aenter__()
    transport = ???  # How to access the transport from outside?
    print(f'Session ID: {get_session_id()}')
    session = ClientSession(rs, ws)
    await session.initialize()
    print('Initialized!')
    result = await session.call_tool('query_local_traces', {'system_id': 'mahavishnu', 'limit': 5})
    print(f'Result: {result}')
    await ctx.__aexit__(None, None, None)

asyncio.run(test())
```

### Hypothesis to Investigate

The `streamable_http_client()` yields `(read_stream, write_stream, get_session_id_callback)`. The transport object is internal. Maybe the session ID is extracted during the POST handling but the transport's `session_id` attribute isn't being set correctly, or there's a different transport instance being used.

### Known Fixes Applied Earlier

1. Fixed `register_otel_query_tools` in Akosha to accept `app` instead of `registry`
1. Updated the call site in `__init__.py`

### Environment

- Mahavishnu venv: `/Users/les/Projects/mahavishnu/.venv`
- Akosha MCP server: running on port 8682 (PID 33399 and 22501)
- mcp 1.27.1, fastmcp 3.3.1

### Quick Checks

```bash
# Is Akosha running?
ps aux | grep akosha | grep mcp | grep -v grep

# Health check
curl http://localhost:8682/health

# Direct test (should work)
curl -X POST http://localhost:8682/mcp \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}' \
  -i
```

______________________________________________________________________

## Notes

The detailed debug session is documented at:
`/Users/les/Projects/mahavishnu/docs/debug-sessions/2026-05-25-bodai-component-mcp-debug.md`
