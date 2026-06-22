# Bodai Crow MCP Server — Design Spec

**Date:** 2026-06-21
**Status:** Draft — pending user review (v3: rapidfuzz + oneiric httpx2 scope added)
**Port:** 8675 *(add to CLAUDE.md port table)*
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

The server uses mcp-common `StandardServer` — the established Bodai MCP server profile. The real
import path is `mcp_common.profiles.standard`, not `mcp_common.server`.

```python
# mahavishnu/mcp/crow_server.py
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from mcp_common.profiles.standard import StandardServer
from mahavishnu.mcp.crow.settings import CrowSettings
from mahavishnu.mcp.crow.client import init_http_client, close_http_client
from mahavishnu.mcp.crow.terminal_proxy import init_crow_stdio_client, close_crow_stdio_client
from mahavishnu.mcp.crow import tools


@asynccontextmanager
async def _lifespan(server: StandardServer) -> AsyncGenerator[None, None]:
    """Manage shared resources for the lifetime of the server."""
    await init_http_client(server.settings)
    await init_crow_stdio_client(server.settings)
    try:
        yield
    finally:
        await close_http_client()
        await close_crow_stdio_client()


def create_crow_server(settings: CrowSettings) -> StandardServer:
    server = StandardServer(
        name="bodai-crow",
        description="Bodai-native file, web, and terminal tools over HTTP MCP",
        settings=settings,
    )
    server.set_lifespan(_lifespan)
    tools.register_all(server, settings)
    return server
```

Tools register via `@server.tool()` decorators (not `server.mcp` — that attribute does not exist
on `StandardServer`). The server runs at `settings.http_port` via `server.run()`.

### 3.1 CrowSettings

```python
# mahavishnu/mcp/crow/settings.py
from __future__ import annotations

import shutil
from pathlib import Path

from mcp_common.profiles.standard import StandardServerSettings
from pydantic import model_validator


class CrowSettings(StandardServerSettings):
    http_port: int = 8675          # uses StandardServerSettings.http_port
    workspace_root: Path = Path.cwd()   # narrow default; override in local.yaml
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

`workspace_root` defaults to `Path.cwd()` (project working directory), not `Path.home()`.
The home directory default is deliberately avoided — it would expose `.ssh`, `.aws`, browser
cookies, and every other repo. Operators widen it explicitly in `settings/local.yaml`:

```yaml
crow:
  workspace_root: "/Users/les/Projects"
```

Oneiric loads from `settings/mahavishnu.yaml` under `crow:`, then `settings/local.yaml`
overrides, then `MAHAVISHNU_CROW_*` env vars.

### 3.2 Terminal Proxy Lifecycle

The `terminal` tool proxies to a **persistent** crow-mcp stdio subprocess. The subprocess is
created once at server startup and lives for the server's lifetime — NOT one process per call.
Spawning per-call would lose PTY session state (working directory, shell history, background jobs).

```python
# mahavishnu/mcp/crow/terminal_proxy.py
from __future__ import annotations

import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_crow_session: ClientSession | None = None
_crow_lock = asyncio.Lock()


async def init_crow_stdio_client(settings: CrowSettings) -> None:
    global _crow_session
    async with _crow_lock:
        params = StdioServerParameters(command=settings.crow_mcp_command, args=[])
        _read, _write = await stdio_client(params).__aenter__()
        _crow_session = await ClientSession(_read, _write).__aenter__()
        await _crow_session.initialize()


async def close_crow_stdio_client() -> None:
    global _crow_session
    if _crow_session is not None:
        await _crow_session.__aexit__(None, None, None)
        _crow_session = None


def get_crow_session() -> ClientSession:
    if _crow_session is None:
        raise RuntimeError("crow stdio client not initialized")
    return _crow_session
```

**Session isolation:** Claude Code's own `crow` stdio entry and the Bodai crow server's child
`crow-mcp` subprocess are separate processes with separate PTYs. They do not share terminal
state.

**Wire contract:** `CrowTerminalAdapter` (in `terminal/adapters/crow.py`) calls the MCP tool
named `terminal` with a single `command` parameter and reads `result.content[0].text`. The proxy
tool must preserve this exact contract.

---

## 4. TerminalManager Gap Fix

`mahavishnu/terminal/manager.py:441–485` — `TerminalManager.create()` — must gain a `crow` case.
This is a pre-existing bug, not new functionality.

```python
# Add after the "mcpretentious" branch:
if preference == "crow":
    from mahavishnu.terminal.adapters.crow import CrowTerminalAdapter
    if mcp_client is None:
        raise ConfigurationError(
            message="crow adapter requires mcp_client pointing at the Bodai crow HTTP server",
            component="terminal_manager",
        )
    adapter = CrowTerminalAdapter(mcp_client=mcp_client)
    return cls(adapter, terminal_config)
```

The `mcp_client` passed here is an HTTP MCP client pointed at `http://localhost:8675/mcp` — it
calls the bodai-crow server's `terminal` tool, which in turn calls the persistent crow-mcp
subprocess. The caller (application startup) is responsible for creating and injecting this
client.

`terminal_switch_adapter` in `mahavishnu/mcp/tools/terminal_tools.py:148–193` needs the same
`"crow"` case added.

---

## 5. Native Tool Implementations

### 5.1 Error Convention

Tools use a consistent error strategy:

- **Tool-level failures** (path outside workspace, invalid pattern, server down): `raise` — FastMCP
  serializes exceptions as MCP error responses. Callers get a structured MCP error, not a 200 with
  `{error: ...}`.
- **Per-item partial failure** in batch tools only (`web_fetch_batch`): return `{error: str}` in
  the item result — this allows partial success across a batch.
- **Binary file detection** in `read`: raise `ValueError("binary file")` — tool-level failure,
  not an in-band field.

### 5.2 `read`

**crow-mcp behavior:** sync `Path.read_text()`, line numbers via `enumerate()`.

**Bodai behavior:** async with `aiofiles`, binary detection via null-byte scan, optional
`offset`/`limit` for pagination, `encoding` parameter with `charset-normalizer` fallback.

```
Inputs:  file_path: str, offset: int = 0, limit: int | None = None, encoding: str = "utf-8"
Returns: {content: str, line_start: int, line_end: int, total_lines: int, truncated: bool}
Raises:  PermissionError (path outside workspace), ValueError (binary file),
         FileNotFoundError (missing file)
```

### 5.3 `write`

**crow-mcp behavior:** sync `Path.write_text()` with `mkdir -p`.

**Bodai behavior:** async with `aiofiles`, atomic write via temp file + `os.replace()` (prevents
partial writes on crash), `dry_run: bool` parameter, `shutil.copystat()` to preserve original
file permissions.

```
Inputs:  file_path: str, content: str, dry_run: bool = False
Returns: {written: bool, path: str, lines: int, bytes: int}
```

**Atomic write pattern:**
```python
import shutil, tempfile, os

if path.exists():
    mode = path.stat().st_mode      # capture before writing
else:
    mode = None

with tempfile.NamedTemporaryFile(
    mode="w", dir=path.parent, delete=False, suffix=".tmp", encoding="utf-8"
) as tmp:
    await asyncio.to_thread(tmp.write, content)
    tmp_path = Path(tmp.name)

if mode is not None:
    os.chmod(tmp_path, mode)        # restore permissions before replace
os.replace(tmp_path, path)          # atomic on POSIX; replaces the path, not a symlink target
```

### 5.4 `edit`

**crow-mcp behavior:** calls `crow_mcp.editor.main.replace()` — a 466-line, 9-level fuzzy
cascade (exact → line-trimmed → block-anchor → whitespace-normalized → indentation-flexible →
escape-normalized → trimmed-boundary → context-aware → multi-occurrence). Pure Python, MIT
licensed.

**Bodai behavior:** vendor the 466-line cascade into `mahavishnu/mcp/crow/vendor/editor.py`
(MIT license header + provenance comment preserved). The pure Python `levenshtein()` function used
in cascade levels 3–9 is replaced with `rapidfuzz.distance.Levenshtein.distance()` and
`normalized_similarity(score_cutoff=0.5)` — C++-backed, ~40× faster, with `score_cutoff` enabling
early exit on clearly non-matching blocks.

Call the vendored `replace(content, old_string, new_string)` via `asyncio.to_thread()` (the
distance computations are CPU-bound). `replace()` takes file content as a string, not a file path
— crow-mcp's internal path whitelist is never invoked. Path security is enforced independently at
the tool boundary via `_resolve_workspace_path()` before reading the file.

Vendoring eliminates the crow-mcp import dependency and removes the SHA-pinning fragility noted in
Open Q2 (which is now resolved).

```
Inputs:  file_path: str, old_string: str, new_string: str, replace_all: bool = False,
         dry_run: bool = False
Returns: {success: bool, path: str, level_used: str, changes: int}
```

### 5.5 `web_fetch`

**crow-mcp behavior:** creates a new `httpx.AsyncClient` per call; uses `readabilipy` (wraps
Mozilla Readability.js via Node.js subprocess) for HTML extraction; `markdownify` for HTML→MD.

**Bodai behavior:**
- Shared `httpx2.AsyncClient` singleton with `http2=True` and zstd support
- `trafilatura.extract()` via `asyncio.to_thread()` (pure Python, F1=0.937, no Node.js)
- `selectolax` CSS selector fallback when trafilatura fails (30× faster than bs4)
- Pagination via `start_index`/`max_length` preserved for compatibility
- **SSRF mitigation**: `_validate_url()` enforces `https?://` scheme only and blocks private/
  loopback/link-local CIDR ranges after DNS resolution (see §6.4)

```
Inputs:  url: str, max_length: int = 5000, start_index: int = 0, raw: bool = False
Returns: {url: str, content: str, truncated: bool, content_type: str, duration_ms: int}
Raises:  PermissionError (SSRF-blocked URL), ValueError (non-http scheme)
```

### 5.6 `web_search`

**crow-mcp behavior:** creates a new `AsyncClient` per call; queries SearXNG at
`os.getenv("SEARXNG_URL", "http://localhost:2946")`; runs multiple queries sequentially.

**Bodai behavior:**
- Shared `httpx2.AsyncClient` singleton
- `asyncio.gather()` for parallel multi-query search
- SearXNG URL from `CrowSettings.searxng_url` (Oneiric config, not env var)
- Health-check SearXNG on first call via `GET /` (not `/healthz` — that endpoint does not exist
  in the `searxng/searxng` image); exponential backoff retry (see §7)
- SearXNG result URLs are **not** auto-fetched; callers must explicitly call `web_fetch`

```
Inputs:  queries: list[str], max_results: int = 5
Returns: list[{query: str, results: list[{title, url, snippet}], error: str | None}]
```

### 5.7 `glob`

**crow-mcp:** does not exist.

**Bodai behavior:** `asyncio.to_thread(root.glob, pattern)` with workspace_root enforcement,
hidden-file filtering, `_ALWAYS_SKIP` exclusion, structured file metadata.

```
Inputs:  pattern: str, path: str = ".", include_hidden: bool = False,
         file_info: bool = True, max_results: int = 1000
Returns: {pattern: str, root: str, results: list[{path, relative, type, size_bytes?,
          modified_epoch?}], count: int, truncated: bool}
```

### 5.8 `grep`

**crow-mcp:** does not exist.

**Bodai behavior:** ripgrep primary, pure Python fallback.

#### ripgrep path

```python
args = ["rg", "--json", f"--max-count={max_matches}"]
if not case_sensitive: args.append("-i")
if fixed_string:       args.append("-F")
args += ["--", pattern, str(root)]   # "--" separates flags from operands
                                      # prevents leading-dash patterns from
                                      # being interpreted as rg flags

result = await asyncio.to_thread(subprocess.run, args, capture_output=True)
if result.returncode == 2:
    raise RuntimeError(result.stderr.decode()[:500])
# exit 0 = matches found, exit 1 = no matches (NOT an error)
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

### 5.9 `web_fetch_batch`

**crow-mcp:** does not exist.

**Bodai behavior:** `asyncio.Semaphore(max_concurrent)` + `asyncio.gather(*tasks,
return_exceptions=True)`. Each URL validated by `_validate_url()` (SSRF filter) before fetch;
trafilatura extraction in `asyncio.to_thread()`; selectolax fallback; partial failure isolated
per URL.

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
    # Reject null bytes before any Path construction
    if "\x00" in path:
        raise PermissionError("null byte in path")

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

`resolve()` follows symlinks before the containment check, so a symlink pointing outside
workspace is correctly rejected. The null-byte check prevents `Path("/etc/passwd\x00.txt")`-style
bypass attempts on older runtimes.

### 6.2 SSRF Mitigation

All web tools validate URLs before fetching:

```python
import ipaddress, socket
from urllib.parse import urlparse

_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / cloud metadata
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Only http/https URLs are allowed, got: {parsed.scheme!r}")
    hostname = parsed.hostname or ""
    try:
        addrs = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise ValueError(f"DNS resolution failed for {hostname!r}: {e}")
    for _, _, _, _, sockaddr in addrs:
        ip = ipaddress.ip_address(sockaddr[0])
        if any(ip in net for net in _PRIVATE_NETS):
            raise PermissionError(
                f"URL resolves to private/reserved address {ip} — blocked (SSRF)"
            )
```

The shared `httpx2.AsyncClient` uses `follow_redirects=False`. Redirect handling is done
manually so each redirect target is re-validated through `_validate_url()` before following.

### 6.3 Shared httpx2 Client

One `httpx2.AsyncClient` is created at server startup (via `_lifespan` in §3) and closed on
shutdown. The server binds to `127.0.0.1` only (configured in `StandardServerSettings.http_host`
or passed to `server.run(host="127.0.0.1", ...)`).

```python
# mahavishnu/mcp/crow/client.py
from __future__ import annotations
import httpx2
from mahavishnu.mcp.crow.settings import CrowSettings

_http_client: httpx2.AsyncClient | None = None


async def init_http_client(settings: CrowSettings) -> None:
    global _http_client
    _http_client = httpx2.AsyncClient(
        http2=True,
        follow_redirects=False,          # manual redirect validation (SSRF)
        timeout=httpx2.Timeout(30.0, connect=10.0),
        headers={"User-Agent": settings.user_agent},
    )


async def close_http_client() -> None:
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


def get_http_client() -> httpx2.AsyncClient:
    if _http_client is None:
        raise RuntimeError("HTTP client not initialized")
    return _http_client
```

zstd decompression is enabled via the `httpx2[zstd]` extra (auto-negotiated; no code change).

### 6.4 Tool Registration

```python
# mahavishnu/mcp/crow/tools/__init__.py
from __future__ import annotations

from mcp_common.profiles.standard import StandardServer
from mahavishnu.mcp.crow.settings import CrowSettings
from . import file_tools, web_tools, search_tools, terminal_proxy_tool


def register_all(server: StandardServer, settings: CrowSettings) -> None:
    file_tools.register(server, settings)
    web_tools.register(server, settings)
    search_tools.register(server, settings)
    terminal_proxy_tool.register(server, settings)
```

Return types should use `TypedDict` subclasses (not bare `dict`) so FastMCP generates a
structured JSON schema for each tool. This lets MCP clients discover the response shape.

---

## 7. SearXNG Deployment

`web_search` depends on a running SearXNG instance.

**Docker Compose** (`docker-compose.crow.yml`):
```yaml
services:
  searxng:
    image: searxng/searxng:latest   # pin tag after first working setup
    ports:
      - "127.0.0.1:2946:8080"       # bind localhost only, not 0.0.0.0
    volumes:
      - ./settings/searxng:/etc/searxng
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost:8080/"]
      interval: 10s
      timeout: 5s
      retries: 6
      start_period: 10s
```

**Minimum `settings/searxng/settings.yml`** (required — SearXNG will not start without it):
```yaml
use_default_settings: true

server:
  secret_key: "change-me-to-a-random-32-plus-char-string"
  limiter: false
  image_proxy: false

search:
  safe_search: 0
  default_lang: "en"

outgoing:
  request_timeout: 10.0

ui:
  default_theme: simple
```

`secret_key` is mandatory. `use_default_settings: true` inherits the default engine list;
`format=json` is enabled by default and requires no extra config. Set
`server.secret_key` to a real random string (not the placeholder above) in `settings/local.yaml`
or via env var — do not commit a real key.

**launchd plist** (`~/Library/LaunchAgents/com.bodai.searxng.plist`):
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.bodai.searxng</string>

  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/docker</string>
    <string>compose</string>
    <string>-f</string>
    <string>/Users/les/Projects/mahavishnu/docker-compose.crow.yml</string>
    <string>up</string>
    <string>--remove-orphans</string>
  </array>

  <key>WorkingDirectory</key>
  <string>/Users/les/Projects/mahavishnu</string>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <false/>

  <key>StandardOutPath</key>
  <string>/tmp/com.bodai.searxng.stdout.log</string>

  <key>StandardErrorPath</key>
  <string>/tmp/com.bodai.searxng.stderr.log</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin</string>
  </dict>
</dict>
</plist>
```

`KeepAlive false` — Docker Compose with `restart: unless-stopped` manages container restarts;
the plist only needs to run `docker compose up` once at login.

**SearXNG health-check with retry** (in `search_tools.py`):
```python
_searxng_ready: bool = False

async def _wait_for_searxng(client: httpx2.AsyncClient, url: str) -> bool:
    global _searxng_ready
    if _searxng_ready:
        return True
    delays = [1, 2, 4, 8, 15]      # ~30s total ceiling
    for delay in delays:
        try:
            r = await client.get(url + "/", timeout=3.0)
            if r.status_code < 500:
                _searxng_ready = True
                return True
        except Exception:
            pass
        await asyncio.sleep(delay)
    return False
```

The correct SearXNG health endpoint is `GET /` — not `/healthz` (that endpoint does not exist
in the `searxng/searxng` image).

---

## 8. .mcp.json Changes

Add the Bodai crow HTTP server alongside the existing stdio entry:

```json
"bodai-crow": {
  "type": "http",
  "url": "http://localhost:8675/mcp"
}
```

The existing `"crow": {"command": "crow-mcp"}` entry is **retained** — Claude Code's own session
continues using the upstream stdio server for its own terminal sessions. The Bodai crow HTTP
server is for pool workers, CLI, and external MCP clients.

**Tool name disambiguation:** Both servers expose tools named `terminal`, `read`, `web_fetch`,
etc. MCP namespaces them as `mcp__crow__terminal` vs `mcp__bodai-crow__terminal` — no hard
collision. However, tool descriptions should make the distinction explicit:

- bodai-crow tools: *"(HTTP, for pool workers and CLI) — ..."*
- The two servers are **not drop-in interchangeable** for non-terminal tools: bodai-crow returns
  structured dicts; crow-mcp returns plain strings.

Consider gating `bodai-crow` behind a tool profile (see §3 of CLAUDE.md tool profiles) so it
doesn't appear in Claude Code's own session alongside `crow`.

---

## 9. httpx2 Migration Plan

Migrate all **seven** Bodai repos from `httpx[http2]` to `httpx2[zstd]`. Oneiric is Phase 0
because all other repos inherit its `HTTPXClientMixin` and `HTTPClientAdapter` — migrating the
foundation first means downstream repos pick up the change on their next Oneiric version bump.

| Phase | Repo(s) | Action |
|-------|---------|--------|
| 0 | **oneiric** | Dep swap + delete `_AsyncClientShim` (replace with `httpx2.AsyncClient`); update `HTTPXClientMixin` type annotations; audit `dhara_pusher.py` sync client |
| 1 | All 7 | Inventory: `grep -r "import httpx\|from httpx" <repo>` |
| 2 | All 7 | Swap dep: `httpx[http2]>=0.27–0.28` → `httpx2[zstd]~=0.1` in each `pyproject.toml` |
| 3 | All 7 | Add `http2=True` to all long-lived `AsyncClient` instantiations |
| 4 | All 7 | Audit sync `httpx.Client` in async contexts — replace with async or `asyncio.to_thread` |
| 5 | All 7 | Enable zstd: `httpx2[zstd]` extra confirmed; httpx2 auto-negotiates, no code change |

**Repos in scope:** oneiric (Phase 0), mahavishnu, mcp-common, session-buddy, akosha, dhara,
crackerjack.

**Oneiric-specific changes:**
- `oneiric/adapters/http/httpx.py`: delete `_AsyncClientShim` (was wrapping sync `httpx.Client`
  in `asyncio.to_thread`); `HTTPClientAdapter.init()` creates `httpx2.AsyncClient` directly with
  `http2=True`
- `oneiric/adapters/httpx_base.py`: update `HTTPXClientMixin` type annotation from
  `httpx.AsyncClient` to `httpx2.AsyncClient`
- `oneiric/adapters/dhara_pusher.py`: sync `httpx.Client` used directly — Phase 4 audit target;
  replace with `httpx2.AsyncClient` (Dhara pusher is called from async contexts)

**API compatibility:** httpx2 is API-compatible with httpx 0.28. Import paths, method signatures,
and exception types are unchanged. Migration is a dep-swap + `http2=True` audit.

### 9.1 Client Usage Tiers

Not all direct `httpx` imports warrant the same treatment. Classify each usage site before
migrating:

**Tier 1 — Long-lived service clients** *(migrate to `HTTPXClientMixin` or `HTTPClientAdapter`)*

Classes that own a persistent `httpx.AsyncClient` across many requests. These should use:
- `HTTPXClientMixin` for lifecycle management (`_init_client`, `_cleanup_client`) when OTel
  tracing is not needed
- `HTTPClientAdapter` when the client makes Bodai-internal service calls (Akosha, Dhara,
  Session-Buddy) — gains `inject_trace_context(headers)` and `observed_http_request()` wrapping,
  which propagates distributed trace context into Grafana spans

| File | Current pattern | Target |
|------|----------------|--------|
| `mahavishnu/ingesters/content_ingester.py` | 4 separate raw `AsyncClient()` instances | `HTTPClientAdapter` × 4 (Bodai-internal calls) |
| `mahavishnu/pools/session_buddy_pool.py` | `httpx.AsyncClient(timeout=300.0)` | `HTTPXClientMixin` |
| `mahavishnu/pools/memory_aggregator.py` | `httpx.AsyncClient(timeout=300.0)` | `HTTPXClientMixin` |
| `mahavishnu/core/resilient_embeddings.py` | Lazy-init `AsyncClient` | `HTTPXClientMixin` |
| `mahavishnu/core/dhara_adapter.py` | `httpx.AsyncClient(timeout, headers)` | `HTTPClientAdapter` |
| `mahavishnu/core/coordination/memory.py` | Two inline `AsyncClient()` instances | `HTTPXClientMixin` |
| `session_buddy/sync.py` | Multiple raw instances | `HTTPXClientMixin` |
| `session_buddy/storage/akosha_sync.py` | Client passed as parameter | `HTTPClientAdapter` |

**Tier 2 — Short-lived per-request clients** *(dep-swap only, leave as context managers)*

`async with httpx.AsyncClient() as client:` for a single call. Converting to a full adapter adds
lifecycle overhead for no benefit — the context manager is the correct pattern here.

```python
# Keep as-is (just swap httpx → httpx2 in the import):
async with httpx.AsyncClient(timeout=timeout_s) as client:   # ecosystem_status.py
    r = await client.get(url)

async with httpx.AsyncClient(timeout=3.0) as client:         # tui/app.py
    r = await client.get(...)
```

**Tier 3 — Type annotations only** *(dep-swap only)*

`httpx.AsyncClient | None` used as a parameter or attribute type. Change `import httpx` to
`import httpx2 as httpx` (or update the annotation directly). No behavioral change.

**Exception — crow server outbound client:**

The crow server's singleton `httpx2.AsyncClient` in `client.py` intentionally does NOT use
`HTTPClientAdapter`, even though it is a Tier 1 long-lived client. The crow server fetches
arbitrary public URLs — injecting Bodai trace headers into requests to external sites is
incorrect. Raw `httpx2.AsyncClient` is right here.

### 9.2 Refactor Sequencing

The OTel adapter migration (§9.1 Tier 1) is a **separate refactor** from the dep swap. Run them
independently:

1. **Dep swap first** (Phase 0–5 above): mechanical, low-risk, no behavior change
2. **OTel adapter migration second**: per-class refactor, adds tracing — higher cognitive load,
   done after dep swap is stable across all repos

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
"rapidfuzz~=3.9"     # C++ Levenshtein for vendored edit cascade (replaces pure-Python levenshtein())
```

Add to dev/test dependencies:
```toml
"respx~=0.21"       # httpx/httpx2 mock transport for tests
```

`aiofiles>=25.1.0` is already declared. `ripgrep` is a system binary, not a Python dep — document
in runbook and Dockerfile; detect via `shutil.which("rg")` at runtime.

---

## 11. File Layout

```
mahavishnu/
  mcp/
    crow_server.py              # StandardServer factory + lifespan
    crow/
      __init__.py
      settings.py               # CrowSettings (StandardServerSettings-based)
      client.py                 # shared httpx2 client + init/close
      path_security.py          # _resolve_workspace_path(), _validate_url()
      terminal_proxy.py         # crow-mcp stdio client + get_crow_session()
      tools/
        __init__.py             # register_all(server, settings)
        file_tools.py           # read, write, edit, glob, grep
        web_tools.py            # web_fetch, web_fetch_batch
        search_tools.py         # web_search
        terminal_proxy_tool.py  # terminal MCP tool (calls get_crow_session())
      vendor/
        editor.py               # optional: vendored crow-mcp replace() + MIT header

tests/
  unit/
    mcp/
      crow/
        conftest.py             # mock_settings(), mock_http_client (respx)
        test_file_tools.py
        test_web_tools.py
        test_search_tools.py
        test_path_security.py
        test_grep_rg_fallback.py
  integration/
    mcp/
      crow/
        conftest.py             # server startup fixture
        test_crow_server.py     # health endpoint, tool list, workspace enforcement

docs/
  runbooks/
    bodai-crow-server.md        # new runbook for HTTP server
    crow-mcp-server.md          # retained for Claude Code stdio usage
  docker-compose.crow.yml
  settings/searxng/settings.yml
```

---

## 12. Testing Strategy (TDD)

All tools follow Red → Verify Red → Green → Verify Green → Refactor.
Pytest markers used: `unit`, `integration`, `mcp`, `slow`, `requires_network`. No new markers.

### 12.0 Conftest fixtures

```python
# tests/unit/mcp/crow/conftest.py
from __future__ import annotations

import pytest
import respx
import httpx
from pathlib import Path
from mahavishnu.mcp.crow.settings import CrowSettings


def mock_settings(workspace_root: Path | None = None, **overrides) -> CrowSettings:
    """Plain factory — call with tmp_path: mock_settings(tmp_path)."""
    root = workspace_root or Path("/tmp/crow-test-workspace")
    root.mkdir(parents=True, exist_ok=True)
    return CrowSettings(workspace_root=root, **overrides)


@pytest.fixture
def settings_with_rg(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/rg" if name == "rg" else None)
    return CrowSettings(workspace_root=tmp_path)


@pytest.fixture
def settings_no_rg(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    return CrowSettings(workspace_root=tmp_path)


@pytest.fixture
def mock_http_client(monkeypatch):
    """respx router patched onto the shared client getter."""
    router = respx.MockRouter(assert_all_called=False)
    router.start()

    async def _fake_client(settings):
        return httpx.AsyncClient(transport=respx.MockTransport(router))

    monkeypatch.setattr("mahavishnu.mcp.crow.client.get_http_client", _fake_client)
    yield router
    router.stop()
```

`mock_settings` is a factory function (not a fixture) so tests can pass `tmp_path` directly.
`respx` is the correct mock library for httpx/httpx2 — it hooks the transport layer and is
library-agnostic. Do not use `pytest-httpx` (patches module-level, incompatible with httpx2).

### 12.1 `read`

```python
async def test_read_returns_content_and_line_count(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("line1\nline2\n")
    result = await read(str(f), settings=mock_settings(tmp_path))
    assert result["content"] == "line1\nline2\n"
    assert result["total_lines"] == 2

async def test_read_pagination_offset_limit(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("a\nb\nc\n")
    result = await read(str(f), offset=1, limit=1, settings=mock_settings(tmp_path))
    assert result["content"] == "b\n"
    assert result["line_start"] == 2
    assert result["truncated"] is True

async def test_read_rejects_path_outside_workspace(tmp_path):
    with pytest.raises(PermissionError):
        await read("/etc/passwd", settings=mock_settings(tmp_path))

async def test_read_raises_for_binary_file(tmp_path):
    f = tmp_path / "bin.dat"
    f.write_bytes(b"\x00\x01\x02")
    with pytest.raises(ValueError, match="binary"):
        await read(str(f), settings=mock_settings(tmp_path))

async def test_read_raises_for_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        await read(str(tmp_path / "missing.py"), settings=mock_settings(tmp_path))
```

### 12.2 `write`

```python
async def test_write_atomic_on_crash_leaves_original(tmp_path, monkeypatch):
    f = tmp_path / "x.py"
    f.write_text("original")
    # patch in the module-under-test's namespace, not stdlib
    monkeypatch.setattr(
        "mahavishnu.mcp.crow.tools.file_tools.os.replace",
        lambda *_: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(OSError):
        await write(str(f), "new content", settings=mock_settings(tmp_path))
    assert f.read_text() == "original"

async def test_write_preserves_file_permissions(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("original")
    f.chmod(0o755)
    await write(str(f), "updated", settings=mock_settings(tmp_path))
    assert oct(f.stat().st_mode & 0o777) == oct(0o755)

async def test_write_dry_run_does_not_modify_file(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("original")
    result = await write(str(f), "new", dry_run=True, settings=mock_settings(tmp_path))
    assert result["written"] is False
    assert f.read_text() == "original"

async def test_write_creates_parent_directories(tmp_path):
    f = tmp_path / "deep" / "nested" / "x.py"
    await write(str(f), "content", settings=mock_settings(tmp_path))
    assert f.read_text() == "content"
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
    f.write_text("def  foo():  pass\n")
    result = await edit(str(f), "def foo(): pass", "def bar(): pass", settings=mock_settings(tmp_path))
    assert result["success"] is True
    assert "whitespace" in result["level_used"]
```

### 12.4 `glob`

```python
async def test_glob_finds_matching_files(tmp_path):
    (tmp_path / "a.py").touch()
    (tmp_path / "b.txt").touch()
    result = await glob("*.py", path=str(tmp_path), settings=mock_settings(tmp_path))
    assert result["count"] == 1
    assert result["results"][0]["relative"] == "a.py"

async def test_glob_hidden_files_excluded_by_default(tmp_path):
    (tmp_path / ".hidden.py").touch()
    result = await glob("*.py", path=str(tmp_path), settings=mock_settings(tmp_path))
    assert not any(".hidden" in r["path"] for r in result["results"])

async def test_glob_truncates_at_max_results(tmp_path):
    for i in range(5):
        (tmp_path / f"f{i}.py").touch()
    result = await glob("*.py", path=str(tmp_path), settings=mock_settings(tmp_path, max_glob_results=3))
    assert result["truncated"] is True
    assert result["count"] == 3

async def test_glob_rejects_path_outside_workspace(tmp_path):
    with pytest.raises(PermissionError):
        await glob("*.py", path="/etc", settings=mock_settings(tmp_path))
```

### 12.5 `grep`

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
    assert result["matches"] == []   # exit 1 = no matches, not an exception

async def test_grep_rejects_path_outside_workspace(tmp_path):
    with pytest.raises(PermissionError):
        await grep("pattern", "/etc", settings=mock_settings(tmp_path))
```

### 12.6 `web_fetch`

```python
async def test_web_fetch_returns_content_and_duration(mock_http_client, tmp_path):
    mock_http_client.get("https://example.com").mock(
        return_value=httpx.Response(200, text="<html><body><p>Hello</p></body></html>")
    )
    result = await web_fetch("https://example.com", settings=mock_settings(tmp_path))
    assert result["url"] == "https://example.com"
    assert result["duration_ms"] >= 0
    assert isinstance(result["content"], str)

async def test_web_fetch_blocks_private_ip(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda host, *_: [(None, None, None, None, ("192.168.1.1", 0))]
    )
    with pytest.raises(PermissionError, match="SSRF"):
        await web_fetch("http://internal.corp/secret", settings=mock_settings(tmp_path))

async def test_web_fetch_blocks_non_http_scheme(tmp_path):
    with pytest.raises(ValueError, match="Only http"):
        await web_fetch("file:///etc/passwd", settings=mock_settings(tmp_path))
```

### 12.7 `web_search`

```python
async def test_web_search_returns_structured_error_when_searxng_down(tmp_path, mock_http_client):
    mock_http_client.get("http://localhost:2946/").mock(
        side_effect=httpx.ConnectError("refused")
    )
    results = await web_search(["test query"], settings=mock_settings(tmp_path))
    assert results[0]["error"] is not None
    assert results[0]["results"] == []

async def test_web_search_parallel_queries(mock_http_client, tmp_path):
    # Both queries should resolve, not run sequentially
    import time
    mock_http_client.get("http://localhost:2946/").mock(
        return_value=httpx.Response(200, text="ok")
    )
    # ... (verifies gather is used, not sequential loop)
```

### 12.8 `web_fetch_batch`

```python
async def test_batch_partial_failure_does_not_cancel_others(mock_http_client, tmp_path):
    mock_http_client.get("https://bad.example.com").mock(
        side_effect=httpx.TimeoutException("timeout")
    )
    mock_http_client.get("https://good.example.com").mock(
        return_value=httpx.Response(200, text="<html><body>ok</body></html>")
    )
    results = await web_fetch_batch(
        ["https://bad.example.com", "https://good.example.com"],
        settings=mock_settings(tmp_path),
    )
    assert results[0]["error"] is not None
    assert results[1]["content"] is not None

async def test_batch_rejects_over_20_urls(tmp_path):
    results = await web_fetch_batch(["https://x.com"] * 21, settings=mock_settings(tmp_path))
    assert all(r["error"] == "batch limit is 20 URLs" for r in results)
```

### 12.9 TerminalManager crow case

```python
async def test_terminal_manager_creates_crow_adapter(mock_crow_mcp_client, crow_config):
    manager = await TerminalManager.create(crow_config, mcp_client=mock_crow_mcp_client)
    assert isinstance(manager._adapter, CrowTerminalAdapter)

async def test_terminal_manager_crow_requires_mcp_client(crow_config):
    with pytest.raises(ConfigurationError, match="crow adapter requires mcp_client"):
        await TerminalManager.create(crow_config, mcp_client=None)
```

### 12.10 Integration test skeleton

```python
# tests/integration/mcp/crow/test_crow_server.py
import pytest
import httpx

pytestmark = [pytest.mark.integration, pytest.mark.mcp]


@pytest.fixture(scope="module")
async def crow_server(tmp_path_factory):
    """Start the Bodai crow server for integration tests."""
    from mahavishnu.mcp.crow.settings import CrowSettings
    from mahavishnu.mcp.crow_server import create_crow_server
    settings = CrowSettings(workspace_root=tmp_path_factory.mktemp("workspace"))
    server = create_crow_server(settings)
    async with server.run_context():   # or equivalent StandardServer test API
        yield server


async def test_health_endpoint_returns_200(crow_server):
    async with httpx.AsyncClient() as client:
        r = await client.get("http://localhost:8675/health")
    assert r.status_code == 200


async def test_tool_list_includes_expected_tools(crow_server):
    # Use MCP client to call tools/list
    expected = {"read", "write", "edit", "glob", "grep",
                "web_fetch", "web_fetch_batch", "web_search", "terminal"}
    # ... assert expected.issubset(tool_names)


async def test_workspace_enforcement_returns_mcp_error(crow_server):
    # Send read call with path outside workspace via HTTP MCP
    # Assert MCP error response (not 500)
    ...


@pytest.mark.requires_network
async def test_web_search_with_real_searxng(crow_server):
    # Skipped if SearXNG is not reachable
    ...
```

---

## 13. Open Questions

1. **Runbook split** *(resolved)*: Keep `crow-mcp-server.md` for Claude Code stdio usage. Add
   `bodai-crow-server.md` for the HTTP server. Both are needed.

2. **crow-mcp `edit` import stability** *(resolved)*: Vendor the 466-line cascade into
   `vendor/editor.py` (see §5.4). rapidfuzz replaces the pure Python `levenshtein()` in levels
   3–9. crow-mcp is no longer imported at runtime — no SHA pinning required.

3. **SearXNG as hard dependency** *(resolved)*: Return structured error when SearXNG is down.
   See §7 retry policy.

4. **httpx2 stability** *(watch)*: If httpx2 proves unstable before 1.0, fall back to
   `httpx[http2]` with the same singleton pattern. No code change needed beyond the import.

5. **Lifespan API**: Confirm `StandardServer.set_lifespan()` (or equivalent) exists in
   mcp-common. If not, lifespan can be implemented via FastMCP's `lifespan=` parameter passed
   during server construction.

6. **Tool profile gating**: Decide whether `bodai-crow` appears in Claude Code's own session
   (where `crow` already provides the same tools). Recommendation: add `bodai-crow` to the
   `standard` profile only, not `full`/`minimal`, so it loads for pool workers but not the
   Claude Code developer session.

7. **`write` symlink semantics**: `os.replace` on a symlink path replaces the link itself, not
   the target. Decide intended behavior: follow the symlink (open target directly) or replace
   the link (current behavior). Document the decision in code.

8. **niquests** *(deferred)*: Evaluated but not adopted. niquests offers HTTP/3 (QUIC) but
   requires a full API rewrite across all 6 repos (requests-style, not httpx-style). httpx2
   covers HTTP/2 + zstd, which is the gap. Revisit niquests when HTTP/3 becomes relevant for
   Bodai network paths (internal traffic today; latency advantage is marginal).
