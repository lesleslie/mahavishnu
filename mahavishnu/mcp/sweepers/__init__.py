"""Background sweeper tasks that run alongside the MCP server.

Sweepers are long-lived asyncio loops that maintain ecosystem state by
consuming Redis Streams (or other transports) and reconciling the
results with session-buddy / akosha / crackerjack. They are started
and stopped by the MCP server's lifespan hooks (T10) and report their
own health via :meth:`health` so the master ``/health`` aggregate can
surface degraded state.
"""
