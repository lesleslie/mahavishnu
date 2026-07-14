# PTY Toolserver Backends

Mahavishnu's pool workers run user commands in a PTY session managed by
an external MCP toolserver. The terminal adapter system supports multiple
backends; you pick one by name via `terminal.adapter_preference` in your
settings.

## Available backends

| Name | Command | Prerequisites | Notes |
|------|---------|---------------|-------|
| `mcpretentious` | `npx mcpretentious` | `node` (>=18) | Full-featured. iTerm2 backend (macOS, needs iTerm2 Python API enabled) or tmux backend (cross-platform). |
| `pty_mcp_python` | `uvx --from luqm4nx-pty-mcp-server-python pty-mcp-server-python` | `uvx` | Pure-Python alternative. Same tool shape. |

## Choosing a backend

```yaml
# settings/mahavishnu.yaml (or settings/local.yaml)
terminal:
  adapter_preference: "mcpretentious"   # or "pty_mcp_python" or "iterm2" or "crow" or "mock"
```

If the requested backend's prerequisites are missing, Mahavishnu fails
at startup with a clear `ConfigurationError` like:

```
PTY backend 'mcpretentious' requires 'node' on PATH but it was not found.
Install: brew install node  (or visit https://nodejs.org)
```

This is intentional — silent fallback to `mock` would hide the
misconfiguration.

## Adding a new backend

Built-in backends live in `mahavishnu/terminal/backends.py`. To add
another, append a `PtyBackend` entry to `BUILTIN_BACKENDS`:

```python
"my_backend": PtyBackend(
    name="my_backend",
    command="my-launcher",
    args=("arg1", "arg2"),
    tool_map={},            # if tool names match, leave empty; otherwise alias them
    requires=("dep1",),     # binaries that must be on PATH
)
```

If your backend's MCP tools don't match `mcpretentious-open` / `-type` /
`-read` / `-close` / `-list` (the names `McpretentiousAdapter` calls),
either write a thin adapter shim, or populate `tool_map` with
`{"mcpretentious_open": "your_open_tool_name", ...}`.

This is a code change (one entry in a dict) — not a config change.
We don't expose per-backend config in settings to keep the test
matrix small and the failure modes clear.

## Verifying your backend is reachable

After setting `terminal.adapter_preference`, run:

```bash
mahavishnu mcp start --verbose 2>&1 | head -50
```

Look for one of:

- `Using mcpretentious adapter` — backend spawned successfully
- `ConfigurationError: PTY backend 'mcpretentious' requires 'node'...` — install the prerequisite
- `ConfigurationError: Unknown PTY backend 'foo'...` — check spelling in settings