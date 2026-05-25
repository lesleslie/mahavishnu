import asyncio
from mahavishnu.mcp.bodai_component_client import BodaiComponentMCPClient

async def test():
    c = BodaiComponentMCPClient("http://localhost:8682/mcp")
    await c.call_tool("query_local_traces", {"system_id": "mahavishnu", "limit": 1})
    session_id = c.session_id
    print(f"session_id={session_id}")
    await c.aclose()
    print("done")

asyncio.run(test())