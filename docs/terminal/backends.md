# Terminal Adapters

> **Historical context**: This document previously described a single
> `mcpretentious` PTY backend (`npx mcpretentious`) that was removed in
> commit `34f61672` (2026-08-10 wave). That backend is no longer
> available and the references to `mcpretentious-open` / `-type` /
> `-read` / `-close` / `-list` in this file are intentionally retained
> as historical record only.
>
> The live adapter architecture is documented below.

Mahavishnu's terminal management is now pluggable via the adapter
system in `mahavishnu/terminal/adapters/`. There are four built-in
adapters; you pick one by name via `terminal.adapter_preference` in
your settings.

## Available adapters

| Name | Module | Prerequisites | Notes |
|------|--------|---------------|-------|
| `tmux` | `mahavishnu/terminal/adapters/tmux.py` | `tmux` on `PATH` | Persistent, multiplexed terminal sessions. Cross-platform (macOS, Linux). |
| `mock` | `mahavishnu/terminal/adapters/mock.py` | None | In-memory adapter for tests and CI environments. |
| `crow` | `mahavishnu/terminal/adapters/crow.py` | crow MCP server | Bridges to the crow MCP server for browser-based terminal control. |
| `base` | `mahavishnu/terminal/adapters/base.py` | None | Abstract base class for new adapters. |

## Choosing an adapter

```yaml
# settings/mahavishnu.yaml (or settings/local.yaml)
terminal:
  adapter_preference: "tmux"   # or "mock", "crow"
```

When `adapter_preference` is `auto`, the manager picks the first
healthy adapter in `tmux`, `crow`, `mock` order. If the requested
adapter's prerequisites are missing, Mahavishnu fails at startup
with a clear error.

## Adding a new adapter

Built-in adapters live in `mahavishnu/terminal/adapters/`. To add
another, subclass `TerminalAdapter` (defined in
`mahavishnu/terminal/adapters/base.py`) and register the module in
`mahavishnu/terminal/adapters/__init__.py`.

This is a code change (one new module), not a config change.

## See also

- `docs/TERMINAL_MANAGEMENT.md` — end-to-end terminal management guide.
- `docs/POOL_REFERENCE.md` — multi-pool orchestration, including the
  cross-server pool layer that lives alongside the local terminal
  adapter layer.
