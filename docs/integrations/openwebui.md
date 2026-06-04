# OpenWebUI Integration via mcpo

Connect OpenWebUI (locally installed) to Mahavishnu's MCP server using `mcpo` as a bridge — no Docker required.

## Architecture

```
OpenWebUI (Homebrew desktop app)
    ↓  OpenAI tool-calling format
http://127.0.0.1:8001
    ↓  mcpo bridge (uvx, zero-install)
http://localhost:8680/sse          ← local Mahavishnu
  OR
https://mahavishnu.example.com/sse ← remote / serverless deployment
    ↓  MCP JSON-RPC over SSE (FastMCP 3.x)
Mahavishnu MCP server
```

`mcpo` translates between OpenWebUI's OpenAI-compatible tool-calling format and the MCP JSON-RPC protocol that Mahavishnu speaks. Mahavishnu already runs an HTTP/SSE MCP server (FastMCP 3.x) — no code changes are needed.

## Prerequisites

- OpenWebUI installed (Homebrew cask: `brew install --cask open-webui`)
- `uv` installed (`brew install uv` or `curl -Ls https://astral.sh/uv/install.sh | sh`)
- Mahavishnu MCP server running (local or remote)

## Starting the Bridge

Mahavishnu uses FastMCP 3.x with the **Streamable HTTP** transport (not legacy SSE). The MCP endpoint is `/mcp` on port 8680. Use `--type streamable-http` with mcpo.

### Local Mahavishnu

Start Mahavishnu's MCP server first, with a full tool profile:

```bash
MAHAVISHNU_TOOL_PROFILE=standard mahavishnu mcp start
# Listening on http://127.0.0.1:8680
```

Then start the mcpo bridge in a separate terminal:

```bash
uvx mcpo \
  --type streamable-http \
  --host 127.0.0.1 \
  --port 8001 \
  http://127.0.0.1:8680/mcp
```

### Remote / Serverless Mahavishnu

Same command, different URL:

```bash
uvx mcpo \
  --type streamable-http \
  --host 127.0.0.1 \
  --port 8001 \
  https://mahavishnu.your-deployment.example.com/mcp
```

OpenWebUI always connects to `http://127.0.0.1:8001` regardless of where Mahavishnu is deployed.

### With Mahavishnu Auth Enabled

If `MAHAVISHNU_AUTH_SECRET` is set and JWT auth is enabled, pass the token as a header:

```bash
uvx mcpo \
  --type streamable-http \
  --host 127.0.0.1 \
  --port 8001 \
  --header '{"Authorization": "Bearer YOUR_JWT_TOKEN"}' \
  http://127.0.0.1:8680/mcp
```

To generate a token:

```bash
mahavishnu auth token --user admin
```

### mcpo Config File (Recommended for Repeated Use)

Create `~/.config/mcpo/mahavishnu.json`:

```json
{
  "mcpServers": {
    "mahavishnu": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:8680/mcp"
    }
  }
}
```

Then run:

```bash
uvx mcpo --config ~/.config/mcpo/mahavishnu.json --host 127.0.0.1 --port 8001
```

Add to `~/.zshrc` as an alias for convenience:

```bash
alias mahavishnu-bridge='uvx mcpo --config ~/.config/mcpo/mahavishnu.json --host 127.0.0.1 --port 8001'
```

## Registering in OpenWebUI

1. Open OpenWebUI (launch from Applications or `open /Applications/Open\ WebUI.app`)
1. Navigate to **Admin Panel → Settings → Tools**
1. Click **Add Tool Server**
1. Enter URL: `http://127.0.0.1:8001`
1. Click **Save** — OpenWebUI will discover all registered Mahavishnu tools

### Recommended First Tools to Verify

| Tool | What it tests |
|------|---------------|
| `ecosystem_status` | Full ecosystem health check |
| `adapter_health` | Adapter connectivity |
| `pool_route_execute` | End-to-end task routing |
| `get_health` | Simple liveness probe |

In the OpenWebUI chat, enable tools via the paperclip/tools icon, then try:

```
What is the current status of the Mahavishnu ecosystem?
```

A successful response confirms the full round-trip: OpenWebUI → mcpo → Mahavishnu MCP → response.

## Troubleshooting

**`Connection refused` on port 8001**: mcpo is not running. Start it first.

**`Connection refused` on port 8680**: Mahavishnu MCP server is not running. Run `mahavishnu mcp start`.

**`401 Unauthorized`**: JWT auth is enabled. Pass the `Authorization` header to mcpo (see above).

**Tools not appearing in OpenWebUI**: Mahavishnu may be using the `minimal` tool profile (health probes only). Set `MAHAVISHNU_TOOL_PROFILE=standard` or `full` before starting the server.

**Connection drops**: Streamable HTTP is stateless per-request — mcpo reconnects automatically on each tool call. No persistent connection to drop.

## Model Arena: MiniMax vs Ollama Benchmarking

OpenWebUI's Arena mode enables blind ELO comparisons between models. Use this to build data for improving `StatisticalRouter` priors.

### Setup

1. In OpenWebUI **Admin → Settings → Connections**:
   - Add MiniMax endpoint: `https://api.minimax.io/v1` with your `MINIMAX_API_KEY`
   - Add Ollama endpoint: `http://localhost:11434` (or your Ollama host)
1. Enable models: `MiniMax-M3`, `MiniMax-M3-highspeed`, `llama3:8b`, `qwen2.5-coder:7b`

### Benchmark Prompt Set

Run each prompt in Arena mode (blind A/B), record which model wins:

| # | Prompt | Expected winner |
|---|--------|-----------------|
| 1 | "Write a Python async function that retries with exponential backoff" | Code model |
| 2 | "Design the data model for a multi-tenant approval workflow system" | Reasoning model |
| 3 | "What is the status of the Mahavishnu ecosystem?" (with tools enabled) | Either, test tool use |
| 4 | "Refactor this function to use a sliding window: `def rate_check(count, window): ...`" | Code model |
| 5 | "Explain the tradeoffs between SSE and Streamable HTTP for MCP transport" | Reasoning model |
| 6 | "Generate a Prometheus alerting rule for p99 latency > 500ms" | Code model |
| 7 | "Summarize the Dhara integration approach in 3 bullet points" | Fast model |
| 8 | "Route this task to the least-loaded pool and explain the decision" (with tools) | Either, test routing |
| 9 | "Write pytest tests for an approval manager that uses Dhara persistence" | Code model |
| 10 | "What architectural pattern does `DharaStateBackend` implement and why?" | Reasoning model |

After 10 prompts, export the ELO table from **Admin → Evaluations** and update `settings/models.yaml` task-category routing if the data contradicts current defaults.

## Reference

- FastMCP HTTP transport: exposes `/mcp` (Streamable HTTP) on port 8680 — use `--type streamable-http` with mcpo
- mcpo source: https://github.com/open-webui/mcpo
- Tool profile docs: `mahavishnu/mcp/tools/profiles.py`
- MiniMax model configuration: `settings/models.yaml`
