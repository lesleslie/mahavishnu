# crow-mcp HTTP Server Runbook

crow-mcp provides PTY terminal execution for Mahavishnu via MCP on port **8675**.

## Prerequisites

- crow-cli installed: `uv tool install crow-cli` (or per project install)
- Verify: `crow-mcp --help`

## Start

```bash
cd /path/to/crow-cli
uv run python -m crow_mcp --transport http --host 127.0.0.1 --port 8675
```

Or via uvicorn if crow-mcp exposes an ASGI app:

```bash
uv run uvicorn crow_mcp:app --host 127.0.0.1 --port 8675
```

**Important:** Always bind to `127.0.0.1`, never `0.0.0.0`.

## Verify

```bash
curl http://127.0.0.1:8675/health
# Or via MCP health check:
mahavishnu health check
```

## Health Check

Mahavishnu probes crow-mcp on startup when `adapter_preference: "crow"`.
With `fallback_on_probe_failure: false` (default), startup fails if crow-mcp is down.

For development without crow-mcp, override via env var:

```bash
export MAHAVISHNU_TERMINAL__ADAPTER_PREFERENCE=mock
```

## Supervision (Optional)

Create a launchd plist at `~/Library/LaunchAgents/ai.crow.mcp.plist` following
the pattern in `config/launchd/` for Bifrost. Key: `ProgramArguments` should
include the uv/python invocation above with `127.0.0.1:8675`.

## Security Hardening (Wave 2)

- Add JWT auth header matching Mahavishnu's auth pattern
- TLS via reverse proxy (nginx/caddy) for multi-user hosts
