# Bodai Crow MCP Server — Design Spec

**Date:** 2026-06-21
**Status:** Draft — pending user review
**Port:** 8675
**Transport:** HTTP (SSE/StreamableHTTP via mcp-common `StandardServer`)

---

## 1. Context and Motivation

crow-mcp is crow-cli's stdio MCP toolserver providing PTY terminal, file read/write/edit, web
fetch, and web search. It is currently wired into Mahavishnu as a stdio process spawned by Claude
Code:

```json
"crow": { "command": "crow-mcp" }
```

This works for Claude Code's own session but fails every other Bodai consumer:

| Caller | Problem with stdio crow-mcp |
|--------|------------------------------|
| Pool workers (GenericShellWorker) | No MCP client for stdio; no HTTP endpoint |
| CLI / TUI | No subprocess management in CLI context |
| ACP agents over HTTP | Need HTTP MCP, not local subprocess |
| Other Bodai components | Can't connect to a per-session stdio process |

A Bodai-native HTTP MCP server at `http://localhost:8675/mcp` fixes this for all callers
simultaneously while also improving on crow-mcp's implementations (async-first, httpx2, ripgrep,
trafilatura).

There is also a **critical gap** in `TerminalManager.create()` (lines 441–485): the factory
handles `mock`, `auto`, `mcpretentious`, and `iterm2` but has no `crow` case, causing a
`ConfigurationError` even though `settings/mahavishnu.yaml` specifies
`adapter_preference: "crow"`. This design fixes that gap as part of server wiring.

---

## 2. Architecture: A-Hybrid

```
┌──────────────────────────────────────────────────────┐
│  Bodai Crow MCP Server  (HTTP :8675)                 │
│                                                      │
│  PROXIED                    NATIVE                   │
│  ─────────                  ──────                   │
│  terminal ──► crow-mcp      read      (aiofiles)     │
│               (stdio)       write     (aiofiles)     │
│                             edit      (crow cascade) │
│                             web_fetch (trafilatura)  │
│                             web_search(SearXNG)      │
│                             glob      (pathlib)      │
│                             grep      (ripgrep)      │
│                             web_fetch_batch          │
└──────────────────────────────────────────────────────┘
```

**Why proxy `terminal` instead of reimplementing:**
crow-mcp's PTY implementation (`terminal/backend.py` + `terminal/session.py`) is 511 lines of
threading code: `pty.openpty()`, a background reader thread, `fcntl` non-blocking I/O,
`select.select()`, a PS1-marker completion-detection protocol, soft/hard timeouts, and
`signal.SIGINT` dispatch. It is proven and stateful. Reimplementing it in async Python would
require `asyncio`-compatible PTY management — a significant and risky effort for no benefit.

**Why native for everything else:**
All file and web tools have concrete improvements over crow-mcp's implementations (see §5).
The `glob`, `grep`, and `web_fetch_batch` tools don't exist in crow-mcp at all.

---

## 3. Server Foundation

The server uses mcp-common `StandardServer` — the established Bodai MCP server profile.

```python
# mahavishnu/mcp/crow_server.py
from __future__ import annotations

from mcp_common.server import StandardServer
from mahavishnu.mcp.crow.settings import CrowSettings
from mahavishnu.mcp.crow import tools

def create_crow_server(settings: CrowSettings) -> StandardServer:
    server = StandardServer(
        name="bodai-crow",
        version="0.1.0",
        settings=settings,
        port=settings.port,
    )
    tools.register_all(server.mcp, settings)
    return server
```

`StandardServer` provides: HTTP transport (SSE + StreamableHTTP), `/health` endpoint, Oneiric
config loading, and optional JWT auth. No custom server scaffolding is needed.

### 3.1 CrowSettings

```python
# mahavishnu/mcp/crow/settings.py
from __future__ import annotations

import shutil
from pathlib import Path

from mcp_common.settings import MCPServerSettings
from pydantic import model_validator


class CrowSettings(MCPServerSettings):
    port: int = 8675
    workspace_root: Path = Path.home()
    searxng_url: str = "http://localhost:2946"
    user_agent: str = "BodaiCrow/0.1"
    max_grep_matches: int = 100
    max_glob_results: int = 1000
    max_batch_urls: int = 20
    max_concurrent_fetches: int = 5
    rg_path: Path | None = None
    crow_mcp_command: str = "crow-mcp"

    @model_validator(mode="after")
    def _resolve_rg(self) -> "CrowSettings":
        if self.rg_path is None:
            found = shutil.which("rg")
            object.__setattr__(self, "rg_path", Path(found) if found else None)
        return self
```

Oneiric loads this from `settings/mahavishnu.yaml` under the `crow:` key, then
`settings/local.yaml` overrides, then `MAHAVISHNU_CROW_*` env vars.

---

## 4. TerminalManager Gap Fix

`mahavishnu/terminal/manager.py:441–485` — `TerminalManager.create()` — must gain a `crow` case.
This is a pre-existing bug, not new functionality.

```python
# Add after the "mcpretentious" branch:
if preference == "crow":
    from mahavishnu.terminal.adapters.crow import CrowTerminalAdapter
    import httpx
    # Create a FastMCP HTTP client pointing at the Bodai crow server
    crow_client = _build_crow_mcp_client(terminal_config)
    adapter = CrowTerminalAdapter(mcp_client=crow_client)
    return cls(adapter, terminal_config)
```

`terminal_switch_adapter` in `mahavishnu/mcp/tools/terminal_tools.py:148–193` needs the same
`"crow"` case added.

---

## 5. Native Tool Implementations

### 5.1 `read`

**crow-mcp behavior:** sync `Path.read_text()`, line numbers via `enumerate()`.

**Bodai behavior:** async with `aiofiles`, binary detection, optional `offset`/`limit` for
pagination, `encoding` parameter with `charset-normalizer` fallback.

```
Inputs:  file_path: str, offset: int = 0, limit: int | None = None, encoding: str = "utf-8"
Returns: {content: str, line_start: int, line_end: int, total_lines: int, truncated: bool}
```

### 5.2 `write`

**crow-mcp behavior:** sync `Path.write_text()` with `mkdir -p`.

**Bodai behavior:** async with `aiofiles`, atomic write via temp file + `os.replace()` (prevents
partial writes on crash), `dry_run: bool` parameter.

```
Inputs:  file_path: str, content: str, dry_run: bool = False
Returns: {written: bool, path: str, lines: int, bytes: int}
```

**Atomic write pattern:**
```python
import tempfile, os
with tempfile.NamedTemporaryFile(
    mode="w", dir=path.parent, delete=False, suffix=".tmp"
) as tmp:
    await asyncio.to_thread(tmp.write, content)
    tmp_path = tmp.name
os.replace(tmp_path, path)   # atomic on POSIX
```

### 5.3 `edit`

**crow-mcp behavior:** calls `crow_mcp.editor.main.replace()` — a 466-line, 9-level fuzzy
cascade (exact → line-trimmed → block-anchor → whitespace-normalized → indentation-flexible →
escape-normalized → trimmed-boundary → context-aware → multi-occurrence). Pure Python, MIT
licensed.

**Bodai behavior:** import and call `replace()` from crow-mcp directly (no reimplementation),
wrap in `asyncio.to_thread()` because the Levenshtein distance computations in levels 3–9 are
CPU-bound. `replace(content, old_string, new_string)` takes file content as a string, not a
file path — crow-mcp's internal path whitelist is never invoked. The Bodai edit tool applies
`_resolve_workspace_path()` before reading the file, so path security is enforced at the tool
boundary independently of crow-mcp internals.

```
Inputs:  file_path: str, old_string: str, new_string: str, replace_all: bool = False,
         dry_run: bool = False
Returns: {success: bool, path: str, level_used: str, changes: int}
```

`★ Design note:` importing directly from crow-mcp avoids duplicating 466 lines of battle-tested
fuzzy logic. If crow-mcp's edit API changes, the Bodai server will surface the break at import
time — a clean dependency boundary.

### 5.4 `web_fetch`

**crow-mcp behavior:** creates a new `httpx.AsyncClient` per call; uses `readabilipy` (wraps
Mozilla Readability.js via Node.js subprocess) for HTML extraction; `markdownify` for HTML→MD.

**Bodai behavior:**
- Shared `httpx2.AsyncClient` singleton with `http2=True` and zstd support
- `trafilatura.extract()` via `asyncio.to_thread()` (pure Python, F1=0.937, no Node.js)
- `selectolax` CSS selector fallback when trafilatura fails (30× faster than bs4)
- Pagination via `start_index`/`max_length` preserved for compatibility

```
Inputs:  url: str, max_length: int = 5000, start_index: int = 0, raw: bool = False
Returns: {url: str, content: str, truncated: bool, content_type: str, duration_ms: int}
```

### 5.5 `web_search`

**crow-mcp behavior:** creates a new `AsyncClient` per call; queries SearXNG at
`os.getenv("SEARXNG_URL", "http://localhost:2946")`; runs multiple queries sequentially.

**Bodai behavior:**
- Shared `httpx2.AsyncClient` singleton
- `asyncio.gather()` for parallel multi-query search
- SearXNG URL from `CrowSettings.searxng_url` (Oneiric config, not env var)
- Health-check SearXNG before first use; return structured error if unavailable

```
Inputs:  queries: list[str], max_results: int = 5
Returns: list[{query: str, results: list[{title, url, snippet}], error: str | None}]
```

### 5.6 `glob`

**crow-mcp:** does not exist.

**Bodai behavior:** `asyncio.to_thread(root.glob, pattern)` with workspace_root enforcement,
hidden-file filtering, `_ALWAYS_SKIP` exclusion, structured file metadata.

```
Inputs:  pattern: str, path: str = ".", include_hidden: bool = False,
         file_info: bool = True, max_results: int = 1000
Returns: {pattern: str, root: str, results: list[{path, relative, type, size_bytes?,
          modified_epoch?}], count: int, truncated: bool}
```

### 5.7 `grep`

**crow-mcp:** does not exist.

**Bodai behavior:** ripgrep primary, pure Python fallback.

#### ripgrep path

```python
args = ["rg", "--json", f"--max-count={max_matches}"]
if not case_sensitive: args.append("-i")
if fixed_string:       args.append("-F")
args += [pattern, str(root)]   # root is pre-validated Path; no shell=True

result = await asyncio.to_thread(subprocess.run, args, capture_output=True)
if result.returncode == 2:
    raise RuntimeError(result.stderr.decode()[:500])
```

rg exits 0 (matches), 1 (no matches — not an error), 2 (error). Parse NDJSON with
`json.loads()` per line, extract `type == "match"` records.

#### Python fallback

`asyncio.Semaphore(50)` + `aiofiles.open()` per file, null-byte binary detection in first 8KB,
`re.compile()` + `splitlines()` per file, `asyncio.gather()` across all candidates.

```
Inputs:  pattern: str, path: str = ".", include: str | None = None,
         max_matches: int = 100, case_sensitive: bool = True, fixed_string: bool = False
Returns: {engine: "ripgrep"|"python", pattern: str, matches: list[{file, line_number,
          match, submatches?}], total_found: int, truncated: bool, files_searched: int}
```

### 5.8 `web_fetch_batch`

**crow-mcp:** does not exist.

**Bodai behavior:** `asyncio.Semaphore(max_concurrent)` + `asyncio.gather(*tasks,
return_exceptions=True)`. Each URL fetched with the shared httpx2 client; trafilatura extraction
in `asyncio.to_thread()`; selectolax fallback; partial failure isolated per URL.

```
Inputs:  urls: list[str] (max 20), max_length: int = 5000, max_concurrent: int = 5
Returns: list[{url: str, content: str | None, truncated: bool, error: str | None,
               duration_ms: int}]
```

---

## 6. Shared Infrastructure

### 6.1 Path Security

All file tools enforce `workspace_root` via a single helper:

```python
def _resolve_workspace_path(path: str, settings: CrowSettings) -> Path:
    resolved = Path(path).expanduser().resolve()
    root = settings.workspace_root.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise PermissionError(
            f"Path '{resolved}' is outside workspace root '{root}'"
        )
    return resolved
```

This is the same pattern as `MahavishnuSettings.workspace_root` with
`_workspace_dir_inside_root` validator (`core/config.py:1031–1047`).

### 6.2 Shared httpx2 Client

One `httpx2.AsyncClient` is created at server startup and closed on shutdown:

```python
_http_client: httpx2.AsyncClient | None = None

async def get_http_client(settings: CrowSettings) -> httpx2.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx2.AsyncClient(
            http2=True,
            follow_redirects=True,
            timeout=httpx2.Timeout(30.0, connect=10.0),
            headers={"User-Agent": settings.user_agent},
        )
    return _http_client
```

zstd decompression is enabled via the `httpx2[zstd]` extra.

### 6.3 Tool Registration

```python
# mahavishnu/mcp/crow/tools/__init__.py
from __future__ import annotations

from fastmcp import FastMCP
from mahavishnu.mcp.crow.settings import CrowSettings
from . import file_tools, web_tools, search_tools

def register_all(mcp: FastMCP, settings: CrowSettings) -> None:
    file_tools.register(mcp, settings)
    web_tools.register(mcp, settings)
    search_tools.register(mcp, settings)
```

---

## 7. SearXNG Deployment

`web_search` and the Bodai crow server depend on a running SearXNG instance.

**Docker Compose** (`docker-compose.crow.yml`):
```yaml
services:
  searxng:
    image: searxng/searxng:latest
    ports: ["2946:8080"]
    volumes: ["./settings/searxng:/etc/searxng"]
    restart: unless-stopped
```

**launchd plist** (`com.bodai.searxng.plist`) for macOS background service:
```xml
<key>ProgramArguments</key>
<array>
  <string>/usr/local/bin/docker</string>
  <string>compose</string>
  <string>-f</string>
  <string>/Users/les/Projects/mahavishnu/docker-compose.crow.yml</string>
  <string>up</string>
</array>
```

**Health check** in `web_search` tool: `GET /healthz` on `searxng_url` with a 3s timeout before
accepting queries. Returns structured error if SearXNG is down rather than hanging.

---

## 8. .mcp.json Changes

Add the Bodai crow HTTP server alongside the existing stdio entry:

```json
"bodai-crow": {
  "type": "http",
  "url": "http://localhost:8675/mcp"
}
```

The existing `"crow": {"command": "crow-mcp"}` entry is **retained** — Claude Code's built-in
session continues using the upstream stdio server for its own terminal sessions. The Bodai crow
HTTP server is for pool workers, CLI, and external MCP clients.

---

## 9. httpx2 Migration Plan

Migrate all six Bodai repos from `httpx[http2]` to `httpx2[zstd]`.

| Phase | Action |
|-------|--------|
| 1 | Inventory: `grep -r "import httpx\|from httpx" <repo>` in all 6 repos |
| 2 | Swap dep: `httpx[http2]>=0.28.1` → `httpx2[zstd]~=0.1` in each `pyproject.toml` |
| 3 | Add `http2=True` to all long-lived `AsyncClient` instantiations |
| 4 | Audit sync `httpx.Client` usage in async contexts — replace with async or `to_thread` |
| 5 | Enable zstd: `httpx2[zstd]` extra confirmed; no code change needed — httpx2 auto-negotiates |

**Repos in scope:** mahavishnu, mcp-common, session-buddy, akosha, dhara, crackerjack.

**API compatibility:** httpx2 is API-compatible with httpx 0.28. Import paths, method signatures,
and exception types are unchanged. Migration is a dep-swap + `http2=True` audit.

---

## 10. New Dependencies

Add to `mahavishnu/pyproject.toml`:

```toml
[project.dependencies]
# Replace:
# "httpx[http2]>=0.28.1"
# With:
"httpx2[zstd]~=0.1"

# Add:
"trafilatura~=2.1"
"selectolax~=0.3"
"markdownify~=0.13"
"charset-normalizer~=3.4"
```

`aiofiles>=25.1.0` is already declared. `ripgrep` is a system binary, not a Python dep — document
in runbook and Dockerfile; detect via `shutil.which("rg")` at runtime.

---

## 11. File Layout

```
mahavishnu/
  mcp/
    crow_server.py              # StandardServer factory
    crow/
      __init__.py
      settings.py               # CrowSettings (Oneiric-based)
      client.py                 # shared httpx2 client + lifecycle
      path_security.py          # _resolve_workspace_path()
      tools/
        __init__.py             # register_all()
        file_tools.py           # read, write, edit, glob, grep
        web_tools.py            # web_fetch, web_fetch_batch
        search_tools.py         # web_search
        terminal_proxy.py       # terminal (proxy to crow-mcp stdio)

tests/
  unit/
    mcp/
      crow/
        test_file_tools.py
        test_web_tools.py
        test_search_tools.py
        test_path_security.py
        test_grep_rg_fallback.py
  integration/
    mcp/
      crow/
        test_crow_server.py     # full server smoke tests

docs/
  runbooks/
    bodai-crow-server.md        # replaces/supplements crow-mcp-server.md
```

---

## 12. Testing Strategy (TDD)

All tools follow Red → Verify Red → Green → Verify Green → Refactor.

### 12.1 `read`

```python
# RED
async def test_read_returns_lines_with_numbers(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("line1\nline2\n")
    result = await read(str(f), settings=mock_settings(tmp_path))
    assert result["content"] == "line1\nline2\n"
    assert result["total_lines"] == 2

async def test_read_rejects_path_outside_workspace(tmp_path):
    with pytest.raises(PermissionError):
        await read("/etc/passwd", settings=mock_settings(tmp_path))

async def test_read_detects_binary_file(tmp_path):
    f = tmp_path / "bin.dat"
    f.write_bytes(b"\x00\x01\x02")
    result = await read(str(f), settings=mock_settings(tmp_path))
    assert "binary" in result.get("error", "").lower()
```

### 12.2 `write`

```python
async def test_write_atomic_on_crash_leaves_original(tmp_path, monkeypatch):
    f = tmp_path / "x.py"
    f.write_text("original")
    monkeypatch.setattr("os.replace", lambda *_: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        await write(str(f), "new content", settings=mock_settings(tmp_path))
    assert f.read_text() == "original"   # original preserved

async def test_write_dry_run_does_not_modify_file(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("original")
    result = await write(str(f), "new", dry_run=True, settings=mock_settings(tmp_path))
    assert result["written"] is False
    assert f.read_text() == "original"
```

### 12.3 `edit`

```python
async def test_edit_exact_match(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("def foo(): pass\n")
    await edit(str(f), "def foo(): pass", "def bar(): pass", settings=mock_settings(tmp_path))
    assert f.read_text() == "def bar(): pass\n"

async def test_edit_fuzzy_whitespace_normalized(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("def  foo():  pass\n")   # double spaces
    result = await edit(str(f), "def foo(): pass", "def bar(): pass", settings=mock_settings(tmp_path))
    assert result["success"] is True
    assert "whitespace" in result["level_used"]
```

### 12.4 `grep`

```python
async def test_grep_rg_used_when_available(tmp_path, settings_with_rg):
    (tmp_path / "a.py").write_text("def hello(): pass\n")
    result = await grep("hello", str(tmp_path), settings=settings_with_rg)
    assert result["engine"] == "ripgrep"
    assert any(m["file"].endswith("a.py") for m in result["matches"])

async def test_grep_falls_back_to_python_when_rg_missing(tmp_path, settings_no_rg):
    (tmp_path / "a.py").write_text("def hello(): pass\n")
    result = await grep("hello", str(tmp_path), settings=settings_no_rg)
    assert result["engine"] == "python"

async def test_grep_rg_exit_1_not_error(tmp_path, settings_with_rg):
    (tmp_path / "a.py").write_text("no match here\n")
    result = await grep("ZZZNOTHERE", str(tmp_path), settings=settings_with_rg)
    assert result["matches"] == []   # not an exception

async def test_grep_rejects_path_outside_workspace(tmp_path):
    with pytest.raises(PermissionError):
        await grep("pattern", "/etc", settings=mock_settings(tmp_path))
```

### 12.5 `web_fetch_batch`

```python
async def test_batch_partial_failure_does_not_cancel_others(mock_http_client):
    mock_http_client.register_error("http://bad.example.com", httpx2.TimeoutException)
    mock_http_client.register_response("http://good.example.com", "<html><body>ok</body></html>")
    results = await web_fetch_batch(
        ["http://bad.example.com", "http://good.example.com"],
        settings=mock_settings()
    )
    assert results[0]["error"] is not None
    assert results[1]["content"] is not None

async def test_batch_rejects_over_20_urls():
    results = await web_fetch_batch(["http://x.com"] * 21, settings=mock_settings())
    assert all(r["error"] == "batch limit is 20 URLs" for r in results)
```

### 12.6 TerminalManager crow case

```python
async def test_terminal_manager_creates_crow_adapter(mock_crow_mcp_client, crow_config):
    manager = await TerminalManager.create(crow_config, mcp_client=mock_crow_mcp_client)
    assert isinstance(manager._adapter, CrowTerminalAdapter)

async def test_terminal_manager_crow_requires_mcp_client(crow_config):
    with pytest.raises(ConfigurationError, match="crow adapter requires mcp_client"):
        await TerminalManager.create(crow_config, mcp_client=None)
```

---

## 13. Open Questions

1. **Runbook split**: Should `docs/runbooks/bodai-crow-server.md` replace or supplement
   `crow-mcp-server.md`? Recommendation: supplement — keep the upstream stdio runbook for
   Claude Code's own terminal session; add a new Bodai server runbook for the HTTP server.

2. **crow-mcp `edit` import path stability**: The `replace()` function is imported from
   `crow_mcp.editor.main`. This is an internal module, not a public API. If crow-mcp restructures
   internals, the import breaks. Mitigation: pin `crow-mcp` to a specific git SHA in
   `pyproject.toml`, or vendor the 466-line file into `mahavishnu/mcp/crow/vendor/`.

3. **SearXNG as hard dependency vs. optional**: Should `web_search` return a clear error when
   SearXNG is down, or should the tool be omitted from the server's tool list entirely when
   SearXNG is unavailable? Recommendation: return a structured error — operators get clearer
   feedback than a missing tool.

4. **httpx2 stability**: httpx2 is early-stage (`github.com/pydantic/httpx2`). If it proves
   unstable before reaching 1.0, the fallback is remaining on `httpx[http2]` with the same
   AsyncClient singleton pattern.
