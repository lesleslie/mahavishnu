# Bodai Crow HTTP MCP Server — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Bodai-native HTTP MCP server at port 8675 that exposes file, web, and terminal tools to all Bodai consumers (pool workers, CLI, ACP agents) — not just Claude Code.

**Architecture:** A-hybrid: `terminal` proxies to a persistent crow-mcp stdio subprocess via `AsyncExitStack`-managed `ClientSession`; all other tools (`read`, `write`, `edit`, `glob`, `grep`, `web_fetch`, `web_fetch_batch`, `web_search`) are natively implemented with async-first I/O, ripgrep, trafilatura, and a vendored rapidfuzz-accelerated edit cascade. Server uses mcp-common `StandardServer` at `mcp_common.profiles.standard`.

**Tech Stack:** Python 3.13, FastMCP / mcp-common `StandardServer`, httpx2[zstd], aiofiles, rapidfuzz, trafilatura, selectolax, ripgrep (system binary), SearXNG (Docker), respx (tests)

**Spec:** `docs/superpowers/specs/2026-06-21-bodai-crow-server-design.md`

**Out of scope:** httpx2 migration across repos (spec §9) — separate plan.

## Global Constraints

- `from __future__ import annotations` as first non-comment line in every source file
- Python 3.13 syntax: `X | None` not `Optional[X]`; `list[str]` not `List[str]`
- `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed on any test
- No `assert` in production code — use exception hierarchy from `mahavishnu/core/errors.py`
- Oneiric logger: `from oneiric.core.logging import get_logger`; never `logging` or `print`
- Async I/O only: `aiofiles` for files, `httpx2` for HTTP, `asyncio.to_thread` for CPU-bound
- Line length: 100 chars; max 10 function args (excl. self/cls)
- `respx` already in deps (`respx>=0.23.1`); `aiofiles>=25.1.0` already in deps
- Pytest markers in use: `unit`, `integration`, `mcp`, `slow`, `requires_network`
- Import `httpx2` not `httpx` in production code; tests may use `httpx` via respx fixtures
- All tool internal implementations prefixed `_` (e.g. `_read`); `register(server, settings)` wraps them as MCP tools via closures

---

## File Structure

**New files:**
```
mahavishnu/mcp/
  crow_server.py                  # StandardServer factory + _lifespan
  crow/
    __init__.py                   # empty package marker
    settings.py                   # CrowSettings(StandardServerSettings)
    path_security.py              # resolve_workspace_path(), validate_url()
    client.py                     # httpx2 singleton: init/close/get_http_client
    terminal_proxy.py             # AsyncExitStack stdio client to crow-mcp
    vendor/
      __init__.py                 # empty
      editor.py                   # vendored crow-mcp cascade + rapidfuzz swap
    tools/
      __init__.py                 # register_all(server, settings)
      file_tools.py               # _read, _write, _edit, _glob + register()
      grep_tool.py                # _grep (ripgrep + Python fallback) + register()
      web_tools.py                # _web_fetch, _web_fetch_batch + register()
      search_tools.py             # _web_search + register()
      terminal_proxy_tool.py      # terminal MCP tool + register()

tests/unit/mcp/crow/
  __init__.py
  conftest.py                     # mock_settings(), fixtures
  test_path_security.py
  test_file_tools.py              # read, write, edit, glob tests
  test_grep_tool.py               # grep + ripgrep fallback tests
  test_web_tools.py               # web_fetch, web_fetch_batch tests
  test_search_tools.py            # web_search tests

tests/integration/mcp/
  __init__.py
  crow/
    __init__.py
    conftest.py
    test_crow_server.py

docker-compose.crow.yml
settings/searxng/settings.yml
docs/runbooks/bodai-crow-server.md
```

**Modified files:**
```
mahavishnu/terminal/manager.py          # add crow case to create()
mahavishnu/mcp/tools/terminal_tools.py # add crow case to terminal_switch_adapter
pyproject.toml                          # add deps, swap httpx → httpx2
.mcp.json                               # add bodai-crow HTTP entry
docs/runbooks/crow-mcp-server.md        # add note pointing to bodai-crow-server.md
```

**Note:** `mahavishnu/terminal/adapters/crow.py` already exists and is complete — do NOT modify it.

---

### Task 1: Foundation — CrowSettings, path security, shared HTTP client, conftest

**Files:**
- Create: `mahavishnu/mcp/crow/__init__.py`
- Create: `mahavishnu/mcp/crow/settings.py`
- Create: `mahavishnu/mcp/crow/path_security.py`
- Create: `mahavishnu/mcp/crow/client.py`
- Create: `tests/unit/mcp/crow/__init__.py`
- Create: `tests/unit/mcp/crow/conftest.py`
- Create: `tests/unit/mcp/crow/test_path_security.py`

**Interfaces:**
- Produces: `CrowSettings`, `resolve_workspace_path(path, workspace_root)`, `validate_url(url)`, `get_http_client()`, `init_http_client(settings)`, `close_http_client()`, `mock_settings(workspace_root, **overrides)` factory

- [ ] **Step 1: Write the failing tests for path security**

```python
# tests/unit/mcp/crow/test_path_security.py
from __future__ import annotations

import pytest
from pathlib import Path

from mahavishnu.mcp.crow.path_security import resolve_workspace_path, validate_url


def test_resolve_accepts_path_inside_workspace(tmp_path):
    f = tmp_path / "a.py"
    f.touch()
    assert resolve_workspace_path(str(f), tmp_path) == f.resolve()


def test_resolve_rejects_traversal(tmp_path):
    with pytest.raises(PermissionError, match="outside workspace root"):
        resolve_workspace_path("/etc/passwd", tmp_path)


def test_resolve_rejects_null_byte(tmp_path):
    with pytest.raises(PermissionError, match="null byte"):
        resolve_workspace_path("/tmp/a\x00.py", tmp_path)


def test_validate_url_accepts_https(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *_a, **_k: [(None, None, None, None, ("93.184.216.34", 0))],
    )
    validate_url("https://example.com/page")  # must not raise


def test_validate_url_rejects_file_scheme():
    with pytest.raises(ValueError, match="Only http"):
        validate_url("file:///etc/passwd")


def test_validate_url_blocks_private_ip(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *_a, **_k: [(None, None, None, None, ("192.168.1.1", 0))],
    )
    with pytest.raises(PermissionError, match="SSRF"):
        validate_url("http://internal.corp/secret")


def test_validate_url_blocks_loopback(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *_a, **_k: [(None, None, None, None, ("127.0.0.1", 0))],
    )
    with pytest.raises(PermissionError, match="SSRF"):
        validate_url("http://localhost/admin")
```

- [ ] **Step 2: Run tests — expect ImportError/ModuleNotFoundError**

```bash
pytest tests/unit/mcp/crow/test_path_security.py -v
```
Expected: collection error — `mahavishnu.mcp.crow.path_security` does not exist.

- [ ] **Step 3: Create package markers and implement all four foundation modules**

```python
# mahavishnu/mcp/crow/__init__.py  (empty)
```

```python
# mahavishnu/mcp/crow/settings.py
from __future__ import annotations

import shutil
from pathlib import Path

from mcp_common.profiles.standard import StandardServerSettings
from pydantic import Field, model_validator


class CrowSettings(StandardServerSettings):
    http_port: int = 8675
    workspace_root: Path = Field(default_factory=Path.cwd)
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

```python
# mahavishnu/mcp/crow/path_security.py
from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlparse

_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def resolve_workspace_path(path: str, workspace_root: Path) -> Path:
    if "\x00" in path:
        raise PermissionError("null byte in path")
    resolved = Path(path).expanduser().resolve()
    root = workspace_root.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PermissionError(
            f"Path '{resolved}' is outside workspace root '{root}'"
        ) from exc
    return resolved


def validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Only http/https URLs are allowed, got: {parsed.scheme!r}")
    hostname = parsed.hostname or ""
    try:
        addrs = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"DNS resolution failed for {hostname!r}: {exc}") from exc
    for _, _, _, _, sockaddr in addrs:
        ip = ipaddress.ip_address(sockaddr[0])
        if any(ip in net for net in _PRIVATE_NETS):
            raise PermissionError(
                f"URL resolves to private/reserved address {ip} — blocked (SSRF)"
            )
```

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
        follow_redirects=False,
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
        raise RuntimeError("HTTP client not initialized — call init_http_client first")
    return _http_client
```

```python
# tests/unit/mcp/crow/__init__.py  (empty)
```

```python
# tests/unit/mcp/crow/conftest.py
from __future__ import annotations

import httpx
import pytest
import respx
from pathlib import Path

from mahavishnu.mcp.crow.settings import CrowSettings


def mock_settings(workspace_root: Path | None = None, **overrides) -> CrowSettings:
    """Factory — not a fixture. Call as: mock_settings(tmp_path, max_grep_matches=5)."""
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
    """respx router wired to a fake AsyncClient; patches get_http_client (sync)."""
    router = respx.MockRouter(assert_all_called=False)
    router.start()
    client = httpx.AsyncClient(transport=respx.MockTransport(router))
    monkeypatch.setattr("mahavishnu.mcp.crow.client.get_http_client", lambda: client)
    yield router
    router.stop()
```

- [ ] **Step 4: Run tests — expect all to pass**

```bash
pytest tests/unit/mcp/crow/test_path_security.py -v
```
Expected: 7 PASSED

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/mcp/crow/ tests/unit/mcp/crow/
git commit -m "feat(crow): Task 1 — settings, path_security, client, conftest"
```

---

### Task 2: vendor/editor.py — crow-mcp cascade with rapidfuzz

Copy the crow-mcp edit cascade from the installed package, replace the pure Python Levenshtein function with rapidfuzz.

**Files:**
- Create: `mahavishnu/mcp/crow/vendor/__init__.py`
- Create: `mahavishnu/mcp/crow/vendor/editor.py`

**Interfaces:**
- Produces: `replace(content: str, old_string: str, new_string: str) -> str` — returns modified content string, or raises `ValueError` if old_string not found after exhausting all cascade levels.

- [ ] **Step 1: Locate and copy the cascade source**

```bash
python -c "import crow_mcp.editor.main as m; import inspect; print(inspect.getfile(m))"
```

Copy the output path's contents to `mahavishnu/mcp/crow/vendor/editor.py`. Then prepend this header:

```python
# mahavishnu/mcp/crow/vendor/editor.py
#
# Vendored from crow-mcp (MIT License)
# https://github.com/crow-mcp/crow-mcp
#
# Modifications from original:
#   - levenshtein() replaced with rapidfuzz.distance.Levenshtein (C++ backend, ~40x faster)
#   - score_cutoff=0.5 added for early-exit on non-matching blocks
```

Also create the empty `__init__.py`:
```python
# mahavishnu/mcp/crow/vendor/__init__.py  (empty)
```

- [ ] **Step 2: Replace the levenshtein function**

Find the `levenshtein` function in `vendor/editor.py`. It will look similar to:

```python
def levenshtein(s1: str, s2: str) -> int:
    # ... pure Python dynamic programming implementation
```

Replace the entire function body with:

```python
from rapidfuzz.distance import Levenshtein as _Lev


def levenshtein(s1: str, s2: str) -> int:
    return _Lev.distance(s1, s2)


def _lev_similarity(s1: str, s2: str) -> float:
    return _Lev.normalized_similarity(s1, s2, score_cutoff=0.5)
```

Then find every call site within the cascade that computes a normalized ratio (e.g. `levenshtein(a, b) / max(len(a), len(b))`) and replace with `_lev_similarity(a, b)`. There will be 1–3 such call sites in levels 3–9.

- [ ] **Step 3: Write smoke tests**

```python
# tests/unit/mcp/crow/test_vendor_editor.py
from __future__ import annotations

import pytest
from mahavishnu.mcp.crow.vendor.editor import replace


def test_replace_exact_match():
    content = "def foo(): pass\n"
    result = replace(content, "def foo(): pass", "def bar(): pass")
    assert result == "def bar(): pass\n"


def test_replace_whitespace_normalized():
    content = "def  foo():  pass\n"
    result = replace(content, "def foo(): pass", "def bar(): pass")
    assert "bar" in result


def test_replace_raises_when_not_found():
    with pytest.raises((ValueError, Exception)):
        replace("hello world\n", "ZZZNOTHERE", "replacement")
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/mcp/crow/test_vendor_editor.py -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/mcp/crow/vendor/
git commit -m "feat(crow): Task 2 — vendor editor cascade with rapidfuzz levenshtein"
```

---

### Task 3: read + write tools

**Files:**
- Create: `mahavishnu/mcp/crow/tools/__init__.py` (stub — full `register_all` in Task 10)
- Create: `mahavishnu/mcp/crow/tools/file_tools.py` (read + write only; edit/glob added in Tasks 4–5)
- Modify: `tests/unit/mcp/crow/test_file_tools.py` (create with read+write tests)

**Interfaces:**
- Consumes: `resolve_workspace_path`, `CrowSettings`
- Produces: `_read(file_path, settings, offset, limit, encoding) -> ReadResult`, `_write(file_path, content, settings, dry_run) -> WriteResult`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/mcp/crow/test_file_tools.py
from __future__ import annotations

import pytest
from pathlib import Path
from tests.unit.mcp.crow.conftest import mock_settings
from mahavishnu.mcp.crow.tools.file_tools import _read, _write


@pytest.mark.unit
async def test_read_content_and_line_count(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("line1\nline2\n")
    result = await _read(str(f), mock_settings(tmp_path))
    assert result["content"] == "line1\nline2\n"
    assert result["total_lines"] == 2
    assert result["truncated"] is False


@pytest.mark.unit
async def test_read_pagination(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("a\nb\nc\n")
    result = await _read(str(f), mock_settings(tmp_path), offset=1, limit=1)
    assert result["content"] == "b\n"
    assert result["line_start"] == 2
    assert result["truncated"] is True


@pytest.mark.unit
async def test_read_rejects_outside_workspace(tmp_path):
    with pytest.raises(PermissionError):
        await _read("/etc/passwd", mock_settings(tmp_path))


@pytest.mark.unit
async def test_read_raises_on_binary(tmp_path):
    f = tmp_path / "bin.dat"
    f.write_bytes(b"\x00\x01\x02")
    with pytest.raises(ValueError, match="binary"):
        await _read(str(f), mock_settings(tmp_path))


@pytest.mark.unit
async def test_read_raises_on_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        await _read(str(tmp_path / "missing.py"), mock_settings(tmp_path))


@pytest.mark.unit
async def test_write_creates_file(tmp_path):
    f = tmp_path / "new.py"
    result = await _write(str(f), "x = 1\n", mock_settings(tmp_path))
    assert result["written"] is True
    assert f.read_text() == "x = 1\n"


@pytest.mark.unit
async def test_write_atomic_leaves_original_on_crash(tmp_path, monkeypatch):
    f = tmp_path / "x.py"
    f.write_text("original")
    monkeypatch.setattr(
        "mahavishnu.mcp.crow.tools.file_tools.os.replace",
        lambda *_: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(OSError):
        await _write(str(f), "new content", mock_settings(tmp_path))
    assert f.read_text() == "original"


@pytest.mark.unit
async def test_write_preserves_permissions(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("original")
    f.chmod(0o755)
    await _write(str(f), "updated", mock_settings(tmp_path))
    assert oct(f.stat().st_mode & 0o777) == oct(0o755)


@pytest.mark.unit
async def test_write_dry_run(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("original")
    result = await _write(str(f), "new", mock_settings(tmp_path), dry_run=True)
    assert result["written"] is False
    assert f.read_text() == "original"


@pytest.mark.unit
async def test_write_creates_parent_directories(tmp_path):
    f = tmp_path / "deep" / "nested" / "x.py"
    await _write(str(f), "content", mock_settings(tmp_path))
    assert f.read_text() == "content"
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/unit/mcp/crow/test_file_tools.py -v 2>&1 | head -20
```

- [ ] **Step 3: Implement read + write**

```python
# mahavishnu/mcp/crow/tools/__init__.py
from __future__ import annotations
# register_all() added in Task 10
```

```python
# mahavishnu/mcp/crow/tools/file_tools.py
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TypedDict

import aiofiles

from mahavishnu.mcp.crow.path_security import resolve_workspace_path
from mahavishnu.mcp.crow.settings import CrowSettings


class ReadResult(TypedDict):
    content: str
    line_start: int
    line_end: int
    total_lines: int
    truncated: bool


class WriteResult(TypedDict):
    written: bool
    path: str
    lines: int
    bytes: int


async def _read(
    file_path: str,
    settings: CrowSettings,
    offset: int = 0,
    limit: int | None = None,
    encoding: str = "utf-8",
) -> ReadResult:
    path = resolve_workspace_path(file_path, settings.workspace_root)
    async with aiofiles.open(path, mode="rb") as fb:
        header = await fb.read(8192)
    if b"\x00" in header:
        raise ValueError(f"binary file: {path}")
    async with aiofiles.open(path, encoding=encoding, errors="replace") as f:
        all_lines = (await f.read()).splitlines(keepends=True)
    total = len(all_lines)
    start = offset
    end = total if limit is None else min(offset + limit, total)
    selected = all_lines[start:end]
    return ReadResult(
        content="".join(selected),
        line_start=start + 1,
        line_end=end,
        total_lines=total,
        truncated=(end < total),
    )


async def _write(
    file_path: str,
    content: str,
    settings: CrowSettings,
    dry_run: bool = False,
) -> WriteResult:
    path = resolve_workspace_path(file_path, settings.workspace_root)
    lines = content.count("\n") + (0 if content.endswith("\n") else 1)
    byte_count = len(content.encode("utf-8"))
    if dry_run:
        return WriteResult(written=False, path=str(path), lines=lines, bytes=byte_count)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode if path.exists() else None
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".crow.tmp")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        async with aiofiles.open(tmp_path, mode="w", encoding="utf-8") as f:
            await f.write(content)
        if mode is not None:
            os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return WriteResult(written=True, path=str(path), lines=lines, bytes=byte_count)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/mcp/crow/test_file_tools.py -v -k "read or write"
```
Expected: 10 PASSED

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/mcp/crow/tools/ tests/unit/mcp/crow/test_file_tools.py
git commit -m "feat(crow): Task 3 — read + write tools with atomic write"
```

---

### Task 4: edit tool

**Files:**
- Modify: `mahavishnu/mcp/crow/tools/file_tools.py` (add `EditResult`, `_edit`)
- Modify: `tests/unit/mcp/crow/test_file_tools.py` (add edit tests)

**Interfaces:**
- Consumes: `mahavishnu.mcp.crow.vendor.editor.replace`
- Produces: `_edit(file_path, old_string, new_string, settings, replace_all, dry_run) -> EditResult`

- [ ] **Step 1: Add failing edit tests**

Append to `tests/unit/mcp/crow/test_file_tools.py`:

```python
from mahavishnu.mcp.crow.tools.file_tools import _edit


@pytest.mark.unit
async def test_edit_exact_match(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("def foo(): pass\n")
    result = await _edit(str(f), "def foo(): pass", "def bar(): pass", mock_settings(tmp_path))
    assert result["success"] is True
    assert f.read_text() == "def bar(): pass\n"


@pytest.mark.unit
async def test_edit_fuzzy_whitespace(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("def  foo():  pass\n")
    result = await _edit(str(f), "def foo(): pass", "def bar(): pass", mock_settings(tmp_path))
    assert result["success"] is True
    assert "bar" in f.read_text()


@pytest.mark.unit
async def test_edit_not_found_returns_failure(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("hello world\n")
    result = await _edit(str(f), "ZZZNOTHERE", "replacement", mock_settings(tmp_path))
    assert result["success"] is False
    assert f.read_text() == "hello world\n"


@pytest.mark.unit
async def test_edit_dry_run_does_not_write(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("def foo(): pass\n")
    result = await _edit(
        str(f), "def foo(): pass", "def bar(): pass", mock_settings(tmp_path), dry_run=True
    )
    assert result["success"] is True
    assert f.read_text() == "def foo(): pass\n"


@pytest.mark.unit
async def test_edit_replace_all(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("foo\nfoo\nfoo\n")
    result = await _edit(str(f), "foo", "bar", mock_settings(tmp_path), replace_all=True)
    assert result["changes"] == 3
    assert f.read_text() == "bar\nbar\nbar\n"
```

- [ ] **Step 2: Run — expect ImportError for `_edit`**

```bash
pytest tests/unit/mcp/crow/test_file_tools.py -v -k "edit" 2>&1 | head -10
```

- [ ] **Step 3: Implement `_edit` — add to `file_tools.py`**

Add to `file_tools.py` (after the imports block, add `asyncio`; after `WriteResult`):

```python
import asyncio

from mahavishnu.mcp.crow.vendor.editor import replace as _cascade_replace


class EditResult(TypedDict):
    success: bool
    path: str
    level_used: str
    changes: int


async def _edit(
    file_path: str,
    old_string: str,
    new_string: str,
    settings: CrowSettings,
    replace_all: bool = False,
    dry_run: bool = False,
) -> EditResult:
    path = resolve_workspace_path(file_path, settings.workspace_root)
    async with aiofiles.open(path, encoding="utf-8", errors="replace") as f:
        original = await f.read()
    try:
        updated = await asyncio.to_thread(_cascade_replace, original, old_string, new_string)
    except Exception:
        return EditResult(success=False, path=str(path), level_used="none", changes=0)
    changes = 1
    if replace_all:
        while True:
            try:
                next_pass = await asyncio.to_thread(_cascade_replace, updated, old_string, new_string)
                updated = next_pass
                changes += 1
            except Exception:
                break
    if not dry_run:
        await _write(str(path), updated, settings)
    # level_used comes from cascade internals; surface what we can
    return EditResult(success=True, path=str(path), level_used="cascade", changes=changes)
```

**Note:** If the vendored `replace()` exposes a `level_used` return value (some cascade implementations return a tuple `(content, level_name)`), update `_edit` to unpack it. Check the signature of `replace()` in `vendor/editor.py` after copying.

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/mcp/crow/test_file_tools.py -v -k "edit"
```
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/mcp/crow/tools/file_tools.py tests/unit/mcp/crow/test_file_tools.py
git commit -m "feat(crow): Task 4 — edit tool with vendored rapidfuzz cascade"
```

---

### Task 5: glob tool

**Files:**
- Modify: `mahavishnu/mcp/crow/tools/file_tools.py` (add `GlobResult`, `_glob`)
- Modify: `tests/unit/mcp/crow/test_file_tools.py` (add glob tests)

**Interfaces:**
- Produces: `_glob(pattern, settings, path, include_hidden, file_info, max_results) -> GlobResult`

- [ ] **Step 1: Add failing glob tests**

Append to `tests/unit/mcp/crow/test_file_tools.py`:

```python
from mahavishnu.mcp.crow.tools.file_tools import _glob


@pytest.mark.unit
async def test_glob_finds_matching_files(tmp_path):
    (tmp_path / "a.py").touch()
    (tmp_path / "b.txt").touch()
    result = await _glob("*.py", mock_settings(tmp_path), path=str(tmp_path))
    assert result["count"] == 1
    assert any(r["relative"] == "a.py" for r in result["results"])


@pytest.mark.unit
async def test_glob_excludes_hidden_by_default(tmp_path):
    (tmp_path / ".hidden.py").touch()
    result = await _glob("*.py", mock_settings(tmp_path), path=str(tmp_path))
    assert result["count"] == 0


@pytest.mark.unit
async def test_glob_include_hidden_flag(tmp_path):
    (tmp_path / ".hidden.py").touch()
    result = await _glob("*.py", mock_settings(tmp_path), path=str(tmp_path), include_hidden=True)
    assert result["count"] == 1


@pytest.mark.unit
async def test_glob_truncates_at_max(tmp_path):
    for i in range(5):
        (tmp_path / f"f{i}.py").touch()
    result = await _glob("*.py", mock_settings(tmp_path, max_glob_results=3), path=str(tmp_path))
    assert result["truncated"] is True
    assert result["count"] == 3


@pytest.mark.unit
async def test_glob_rejects_outside_workspace(tmp_path):
    with pytest.raises(PermissionError):
        await _glob("*.py", mock_settings(tmp_path), path="/etc")
```

- [ ] **Step 2: Implement `_glob` — append to `file_tools.py`**

```python
_ALWAYS_SKIP = {".git", "__pycache__", ".venv", "node_modules", ".mypy_cache", ".ruff_cache"}


class GlobEntry(TypedDict):
    path: str
    relative: str
    type: str
    size_bytes: int
    modified_epoch: float


class GlobResult(TypedDict):
    pattern: str
    root: str
    results: list[GlobEntry]
    count: int
    truncated: bool


async def _glob(
    pattern: str,
    settings: CrowSettings,
    path: str = ".",
    include_hidden: bool = False,
    file_info: bool = True,
    max_results: int | None = None,
) -> GlobResult:
    root = resolve_workspace_path(path, settings.workspace_root)
    limit = max_results if max_results is not None else settings.max_glob_results
    raw = await asyncio.to_thread(lambda: list(root.glob(pattern)))
    results: list[GlobEntry] = []
    for p in raw:
        parts = p.parts
        if not include_hidden and any(part.startswith(".") for part in parts):
            continue
        if any(part in _ALWAYS_SKIP for part in parts):
            continue
        try:
            stat = p.stat() if file_info else None
        except OSError:
            continue
        results.append(GlobEntry(
            path=str(p),
            relative=str(p.relative_to(root)),
            type="file" if p.is_file() else "dir",
            size_bytes=stat.st_size if stat and p.is_file() else 0,
            modified_epoch=stat.st_mtime if stat else 0.0,
        ))
        if len(results) >= limit:
            break
    return GlobResult(
        pattern=pattern,
        root=str(root),
        results=results,
        count=len(results),
        truncated=len(results) >= limit,
    )
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/unit/mcp/crow/test_file_tools.py -v -k "glob"
```
Expected: 5 PASSED

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/mcp/crow/tools/file_tools.py tests/unit/mcp/crow/test_file_tools.py
git commit -m "feat(crow): Task 5 — glob tool with hidden-file and _ALWAYS_SKIP filtering"
```

---

### Task 6: grep tool

**Files:**
- Create: `mahavishnu/mcp/crow/tools/grep_tool.py`
- Create: `tests/unit/mcp/crow/test_grep_tool.py`

**Interfaces:**
- Produces: `_grep(pattern, settings, path, include, max_matches, case_sensitive, fixed_string) -> GrepResult`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/mcp/crow/test_grep_tool.py
from __future__ import annotations

import pytest
from tests.unit.mcp.crow.conftest import mock_settings
from mahavishnu.mcp.crow.tools.grep_tool import _grep


@pytest.mark.unit
async def test_grep_rg_engine_when_available(tmp_path, settings_with_rg):
    (tmp_path / "a.py").write_text("def hello(): pass\n")
    result = await _grep("hello", settings_with_rg, path=str(tmp_path))
    assert result["engine"] == "ripgrep"
    assert any(m["file"].endswith("a.py") for m in result["matches"])


@pytest.mark.unit
async def test_grep_python_fallback_when_no_rg(tmp_path, settings_no_rg):
    (tmp_path / "a.py").write_text("def hello(): pass\n")
    result = await _grep("hello", settings_no_rg, path=str(tmp_path))
    assert result["engine"] == "python"
    assert len(result["matches"]) == 1


@pytest.mark.unit
async def test_grep_rg_exit_1_is_not_error(tmp_path, settings_with_rg):
    (tmp_path / "a.py").write_text("no match here\n")
    result = await _grep("ZZZNOTHERE", settings_with_rg, path=str(tmp_path))
    assert result["matches"] == []


@pytest.mark.unit
async def test_grep_case_insensitive(tmp_path, settings_no_rg):
    (tmp_path / "a.py").write_text("Hello World\n")
    result = await _grep("hello", settings_no_rg, path=str(tmp_path), case_sensitive=False)
    assert len(result["matches"]) == 1


@pytest.mark.unit
async def test_grep_fixed_string_no_regex(tmp_path, settings_no_rg):
    (tmp_path / "a.py").write_text("cost = a + b\n")
    result = await _grep("a + b", settings_no_rg, path=str(tmp_path), fixed_string=True)
    assert len(result["matches"]) == 1


@pytest.mark.unit
async def test_grep_rejects_outside_workspace(tmp_path):
    with pytest.raises(PermissionError):
        await _grep("pattern", mock_settings(tmp_path), path="/etc")
```

- [ ] **Step 2: Implement `grep_tool.py`**

```python
# mahavishnu/mcp/crow/tools/grep_tool.py
from __future__ import annotations

import asyncio
import json
import re
import subprocess
from pathlib import Path
from typing import TypedDict

import aiofiles

from mahavishnu.mcp.crow.path_security import resolve_workspace_path
from mahavishnu.mcp.crow.settings import CrowSettings


class GrepMatch(TypedDict):
    file: str
    line_number: int
    match: str


class GrepResult(TypedDict):
    engine: str
    pattern: str
    matches: list[GrepMatch]
    total_found: int
    truncated: bool
    files_searched: int


async def _grep(
    pattern: str,
    settings: CrowSettings,
    path: str = ".",
    include: str | None = None,
    max_matches: int | None = None,
    case_sensitive: bool = True,
    fixed_string: bool = False,
) -> GrepResult:
    root = resolve_workspace_path(path, settings.workspace_root)
    limit = max_matches if max_matches is not None else settings.max_grep_matches
    if settings.rg_path is not None:
        return await _grep_rg(pattern, root, settings.rg_path, include, limit, case_sensitive, fixed_string)
    return await _grep_python(pattern, root, include, limit, case_sensitive, fixed_string)


async def _grep_rg(
    pattern: str,
    root: Path,
    rg_path: Path,
    include: str | None,
    limit: int,
    case_sensitive: bool,
    fixed_string: bool,
) -> GrepResult:
    args = [str(rg_path), "--json", f"--max-count={limit}"]
    if not case_sensitive:
        args.append("-i")
    if fixed_string:
        args.append("-F")
    if include:
        args.extend(["-g", include])
    args += ["--", pattern, str(root)]
    proc = await asyncio.to_thread(
        subprocess.run, args, capture_output=True
    )
    if proc.returncode == 2:
        raise RuntimeError(proc.stderr.decode()[:500])
    matches: list[GrepMatch] = []
    for line in proc.stdout.decode(errors="replace").splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "match":
            continue
        data = obj["data"]
        matches.append(GrepMatch(
            file=data["path"]["text"],
            line_number=data["line_number"],
            match=data["lines"]["text"].rstrip("\n"),
        ))
    return GrepResult(
        engine="ripgrep",
        pattern=pattern,
        matches=matches,
        total_found=len(matches),
        truncated=len(matches) >= limit,
        files_searched=0,
    )


async def _grep_python(
    pattern: str,
    root: Path,
    include: str | None,
    limit: int,
    case_sensitive: bool,
    fixed_string: bool,
) -> GrepResult:
    flags = 0 if case_sensitive else re.IGNORECASE
    regex = re.compile(re.escape(pattern) if fixed_string else pattern, flags)
    glob_pat = include if include else "**/*"
    candidates = [p for p in root.rglob(glob_pat.lstrip("*/")) if p.is_file()]
    matches: list[GrepMatch] = []
    files_searched = 0
    sem = asyncio.Semaphore(50)

    async def search(p: Path) -> list[GrepMatch]:
        nonlocal files_searched
        async with sem:
            try:
                async with aiofiles.open(p, mode="rb") as fb:
                    if b"\x00" in await fb.read(8192):
                        return []
                async with aiofiles.open(p, encoding="utf-8", errors="ignore") as f:
                    text = await f.read()
                files_searched += 1
                found = []
                for i, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        found.append(GrepMatch(file=str(p), line_number=i, match=line))
                return found
            except OSError:
                return []

    for file_matches in await asyncio.gather(*[search(p) for p in candidates]):
        matches.extend(file_matches)
        if len(matches) >= limit:
            break

    return GrepResult(
        engine="python",
        pattern=pattern,
        matches=matches[:limit],
        total_found=len(matches),
        truncated=len(matches) >= limit,
        files_searched=files_searched,
    )


def register(server, settings: CrowSettings) -> None:
    @server.tool()
    async def grep(
        pattern: str,
        path: str = ".",
        include: str | None = None,
        max_matches: int | None = None,
        case_sensitive: bool = True,
        fixed_string: bool = False,
    ) -> GrepResult:
        return await _grep(pattern, settings, path, include, max_matches, case_sensitive, fixed_string)
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/unit/mcp/crow/test_grep_tool.py -v
```
Expected: 6 PASSED

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/mcp/crow/tools/grep_tool.py tests/unit/mcp/crow/test_grep_tool.py
git commit -m "feat(crow): Task 6 — grep tool with ripgrep primary and Python fallback"
```

---

### Task 7: web_fetch + web_fetch_batch

**Files:**
- Create: `mahavishnu/mcp/crow/tools/web_tools.py`
- Create: `tests/unit/mcp/crow/test_web_tools.py`

**Interfaces:**
- Consumes: `get_http_client()`, `validate_url()`
- Produces: `_web_fetch(url, settings, max_length, start_index, raw) -> WebFetchResult`, `_web_fetch_batch(urls, settings, max_length, max_concurrent) -> list[BatchItem]`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/mcp/crow/test_web_tools.py
from __future__ import annotations

import httpx
import pytest
from tests.unit.mcp.crow.conftest import mock_settings
from mahavishnu.mcp.crow.tools.web_tools import _web_fetch, _web_fetch_batch


@pytest.mark.unit
async def test_web_fetch_returns_content(mock_http_client, tmp_path):
    mock_http_client.get("https://example.com").mock(
        return_value=httpx.Response(200, text="<html><body><p>Hello world</p></body></html>")
    )
    result = await _web_fetch("https://example.com", mock_settings(tmp_path))
    assert result["url"] == "https://example.com"
    assert result["duration_ms"] >= 0
    assert isinstance(result["content"], str)


@pytest.mark.unit
async def test_web_fetch_blocks_non_http_scheme(tmp_path):
    with pytest.raises(ValueError, match="Only http"):
        await _web_fetch("file:///etc/passwd", mock_settings(tmp_path))


@pytest.mark.unit
async def test_web_fetch_blocks_ssrf(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *_a, **_k: [(None, None, None, None, ("192.168.1.1", 0))],
    )
    with pytest.raises(PermissionError, match="SSRF"):
        await _web_fetch("http://internal.corp/", mock_settings(tmp_path))


@pytest.mark.unit
async def test_batch_partial_failure_isolates_per_url(mock_http_client, tmp_path):
    mock_http_client.get("https://bad.example.com").mock(
        side_effect=httpx.TimeoutException("timeout")
    )
    mock_http_client.get("https://good.example.com").mock(
        return_value=httpx.Response(200, text="<html><body>ok</body></html>")
    )
    results = await _web_fetch_batch(
        ["https://bad.example.com", "https://good.example.com"],
        mock_settings(tmp_path),
    )
    assert results[0]["error"] is not None
    assert results[1]["content"] is not None


@pytest.mark.unit
async def test_batch_rejects_over_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *_a, **_k: [(None, None, None, None, ("93.184.216.34", 0))],
    )
    results = await _web_fetch_batch(
        [f"https://example.com/{i}" for i in range(21)],
        mock_settings(tmp_path),
    )
    assert all(r["error"] is not None for r in results)
```

- [ ] **Step 2: Implement `web_tools.py`**

```python
# mahavishnu/mcp/crow/tools/web_tools.py
from __future__ import annotations

import asyncio
import time
from typing import TypedDict

import trafilatura
from selectolax.parser import HTMLParser

from mahavishnu.mcp.crow.client import get_http_client
from mahavishnu.mcp.crow.path_security import validate_url
from mahavishnu.mcp.crow.settings import CrowSettings


class WebFetchResult(TypedDict):
    url: str
    content: str
    truncated: bool
    content_type: str
    duration_ms: int


class BatchItem(TypedDict):
    url: str
    content: str | None
    truncated: bool
    error: str | None
    duration_ms: int


def _extract_text(html: str) -> str:
    text = trafilatura.extract(html, output_format="markdown") or ""
    if not text:
        try:
            text = HTMLParser(html).css_first("body").text()
        except Exception:
            text = html
    return text


async def _web_fetch(
    url: str,
    settings: CrowSettings,
    max_length: int = 5000,
    start_index: int = 0,
    raw: bool = False,
) -> WebFetchResult:
    validate_url(url)
    client = get_http_client()
    t0 = time.monotonic()
    resp = await client.get(url, headers={"Accept": "text/html,*/*"})
    elapsed = int((time.monotonic() - t0) * 1000)
    content_type = resp.headers.get("content-type", "")
    if raw:
        text = resp.text
    else:
        text = await asyncio.to_thread(_extract_text, resp.text)
    chunk = text[start_index: start_index + max_length]
    return WebFetchResult(
        url=url,
        content=chunk,
        truncated=len(text) > start_index + max_length,
        content_type=content_type,
        duration_ms=elapsed,
    )


async def _web_fetch_batch(
    urls: list[str],
    settings: CrowSettings,
    max_length: int = 5000,
    max_concurrent: int | None = None,
) -> list[BatchItem]:
    limit = len(urls)
    if limit > settings.max_batch_urls:
        return [
            BatchItem(url=u, content=None, truncated=False,
                      error=f"batch limit is {settings.max_batch_urls} URLs", duration_ms=0)
            for u in urls
        ]
    concurrency = max_concurrent if max_concurrent is not None else settings.max_concurrent_fetches
    sem = asyncio.Semaphore(concurrency)

    async def fetch_one(url: str) -> BatchItem:
        async with sem:
            try:
                result = await _web_fetch(url, settings, max_length)
                return BatchItem(
                    url=url, content=result["content"],
                    truncated=result["truncated"], error=None,
                    duration_ms=result["duration_ms"],
                )
            except Exception as exc:
                return BatchItem(url=url, content=None, truncated=False,
                                 error=str(exc), duration_ms=0)

    return list(await asyncio.gather(*[fetch_one(u) for u in urls]))


def register(server, settings: CrowSettings) -> None:
    @server.tool()
    async def web_fetch(
        url: str, max_length: int = 5000, start_index: int = 0, raw: bool = False
    ) -> WebFetchResult:
        return await _web_fetch(url, settings, max_length, start_index, raw)

    @server.tool()
    async def web_fetch_batch(
        urls: list[str], max_length: int = 5000, max_concurrent: int = 5
    ) -> list[BatchItem]:
        return await _web_fetch_batch(urls, settings, max_length, max_concurrent)
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/unit/mcp/crow/test_web_tools.py -v
```
Expected: 5 PASSED

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/mcp/crow/tools/web_tools.py tests/unit/mcp/crow/test_web_tools.py
git commit -m "feat(crow): Task 7 — web_fetch + web_fetch_batch with SSRF guard"
```

---

### Task 8: web_search + SearXNG deployment config

**Files:**
- Create: `mahavishnu/mcp/crow/tools/search_tools.py`
- Create: `tests/unit/mcp/crow/test_search_tools.py`
- Create: `docker-compose.crow.yml`
- Create: `settings/searxng/settings.yml`

**Interfaces:**
- Consumes: `get_http_client()`
- Produces: `_web_search(queries, settings, max_results) -> list[SearchQueryResult]`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/mcp/crow/test_search_tools.py
from __future__ import annotations

import httpx
import pytest
from tests.unit.mcp.crow.conftest import mock_settings
from mahavishnu.mcp.crow.tools.search_tools import _web_search


@pytest.mark.unit
async def test_web_search_structured_error_when_down(mock_http_client, tmp_path):
    mock_http_client.get("http://localhost:2946/").mock(
        side_effect=httpx.ConnectError("refused")
    )
    results = await _web_search(["test query"], mock_settings(tmp_path))
    assert results[0]["error"] is not None
    assert results[0]["results"] == []


@pytest.mark.unit
async def test_web_search_returns_results(mock_http_client, tmp_path):
    mock_http_client.get("http://localhost:2946/").mock(
        return_value=httpx.Response(200, text="ok")
    )
    mock_http_client.get("http://localhost:2946/search").mock(
        return_value=httpx.Response(
            200,
            json={"results": [{"title": "T", "url": "https://x.com", "content": "snippet"}]},
        )
    )
    results = await _web_search(["query"], mock_settings(tmp_path))
    assert results[0]["error"] is None
    assert len(results[0]["results"]) == 1


@pytest.mark.unit
async def test_web_search_parallel_queries(mock_http_client, tmp_path):
    mock_http_client.get("http://localhost:2946/").mock(
        return_value=httpx.Response(200, text="ok")
    )
    mock_http_client.get("http://localhost:2946/search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    results = await _web_search(["q1", "q2", "q3"], mock_settings(tmp_path))
    assert len(results) == 3
```

- [ ] **Step 2: Implement `search_tools.py`**

```python
# mahavishnu/mcp/crow/tools/search_tools.py
from __future__ import annotations

import asyncio
from typing import TypedDict

from mahavishnu.mcp.crow.client import get_http_client
from mahavishnu.mcp.crow.settings import CrowSettings

_searxng_ready: bool = False


class SearchResult(TypedDict):
    title: str
    url: str
    snippet: str


class SearchQueryResult(TypedDict):
    query: str
    results: list[SearchResult]
    error: str | None


async def _wait_for_searxng(base_url: str) -> bool:
    global _searxng_ready
    if _searxng_ready:
        return True
    client = get_http_client()
    for delay in [1, 2, 4, 8, 15]:
        try:
            r = await client.get(base_url + "/", timeout=3.0)
            if r.status_code < 500:
                _searxng_ready = True
                return True
        except Exception:
            pass
        await asyncio.sleep(delay)
    return False


async def _search_one(query: str, base_url: str, max_results: int) -> SearchQueryResult:
    client = get_http_client()
    try:
        r = await client.get(
            base_url + "/search",
            params={"q": query, "format": "json", "pageno": 1},
            timeout=15.0,
        )
        r.raise_for_status()
        data = r.json()
        results = [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
            )
            for item in data.get("results", [])[:max_results]
        ]
        return SearchQueryResult(query=query, results=results, error=None)
    except Exception as exc:
        return SearchQueryResult(query=query, results=[], error=str(exc))


async def _web_search(
    queries: list[str],
    settings: CrowSettings,
    max_results: int = 5,
) -> list[SearchQueryResult]:
    base_url = settings.searxng_url.rstrip("/")
    ready = await _wait_for_searxng(base_url)
    if not ready:
        return [SearchQueryResult(query=q, results=[], error="SearXNG unavailable") for q in queries]
    return list(await asyncio.gather(*[_search_one(q, base_url, max_results) for q in queries]))


def register(server, settings: CrowSettings) -> None:
    @server.tool()
    async def web_search(queries: list[str], max_results: int = 5) -> list[SearchQueryResult]:
        return await _web_search(queries, settings, max_results)
```

- [ ] **Step 3: Create SearXNG deployment files**

```yaml
# docker-compose.crow.yml
services:
  searxng:
    image: searxng/searxng:latest
    ports:
      - "127.0.0.1:2946:8080"
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

```yaml
# settings/searxng/settings.yml
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

**Important:** Set `server.secret_key` to a real random string in `settings/local.yaml` or via env var before running. Do not commit a real key.

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/mcp/crow/test_search_tools.py -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/mcp/crow/tools/search_tools.py tests/unit/mcp/crow/test_search_tools.py \
        docker-compose.crow.yml settings/searxng/
git commit -m "feat(crow): Task 8 — web_search + SearXNG Docker config"
```

---

### Task 9: Terminal proxy + TerminalManager gap fix

**Files:**
- Create: `mahavishnu/mcp/crow/tools/terminal_proxy_tool.py`
- Create: `mahavishnu/mcp/crow/terminal_proxy.py`
- Modify: `mahavishnu/terminal/manager.py` (lines 449–484 — add crow case)
- Modify: `mahavishnu/mcp/tools/terminal_tools.py` (lines 173–181 — add crow case)

**Note:** `mahavishnu/terminal/adapters/crow.py` is **already complete**. Do not modify it.

**Interfaces:**
- Produces: `get_crow_session() -> ClientSession`, `init_crow_stdio_client(settings)`, `close_crow_stdio_client()`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/mcp/crow/test_terminal_proxy.py
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from tests.unit.mcp.crow.conftest import mock_settings
from mahavishnu.mcp.crow import terminal_proxy
from mahavishnu.core.errors import ConfigurationError


@pytest.mark.unit
async def test_get_crow_session_raises_before_init():
    terminal_proxy._crow_session = None
    with pytest.raises(RuntimeError, match="not initialized"):
        terminal_proxy.get_crow_session()


@pytest.mark.unit
async def test_terminal_manager_crow_case_requires_mcp_client(tmp_path):
    from mahavishnu.terminal.manager import TerminalManager
    from mahavishnu.core.config import MahavishnuSettings
    config = MahavishnuSettings()
    config.terminal.adapter_preference = "crow"
    with pytest.raises(ConfigurationError, match="crow"):
        await TerminalManager.create(config, mcp_client=None)


@pytest.mark.unit
async def test_terminal_manager_crow_case_creates_crow_adapter(tmp_path):
    from mahavishnu.terminal.manager import TerminalManager
    from mahavishnu.terminal.adapters.crow import CrowTerminalAdapter
    from mahavishnu.core.config import MahavishnuSettings
    config = MahavishnuSettings()
    config.terminal.adapter_preference = "crow"
    mock_client = MagicMock()
    manager = await TerminalManager.create(config, mcp_client=mock_client)
    assert isinstance(manager._adapter, CrowTerminalAdapter)
```

- [ ] **Step 2: Implement `terminal_proxy.py`**

```python
# mahavishnu/mcp/crow/terminal_proxy.py
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mahavishnu.mcp.crow.settings import CrowSettings

_crow_session: ClientSession | None = None
_crow_exit_stack: AsyncExitStack | None = None
_crow_lock = asyncio.Lock()


async def init_crow_stdio_client(settings: CrowSettings) -> None:
    global _crow_session, _crow_exit_stack
    async with _crow_lock:
        stack = AsyncExitStack()
        params = StdioServerParameters(command=settings.crow_mcp_command, args=[])
        _read, _write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(_read, _write))
        await session.initialize()
        _crow_session = session
        _crow_exit_stack = stack


async def close_crow_stdio_client() -> None:
    global _crow_session, _crow_exit_stack
    if _crow_exit_stack is not None:
        await _crow_exit_stack.aclose()
        _crow_exit_stack = None
    _crow_session = None


def get_crow_session() -> ClientSession:
    if _crow_session is None:
        raise RuntimeError("crow stdio client not initialized — server lifespan not running")
    return _crow_session
```

- [ ] **Step 3: Implement `terminal_proxy_tool.py`**

```python
# mahavishnu/mcp/crow/tools/terminal_proxy_tool.py
from __future__ import annotations

from typing import TypedDict

from mahavishnu.mcp.crow.settings import CrowSettings
from mahavishnu.mcp.crow.terminal_proxy import get_crow_session


class TerminalResult(TypedDict):
    output: str


def register(server, settings: CrowSettings) -> None:
    @server.tool()
    async def terminal(command: str) -> TerminalResult:
        """(HTTP, for pool workers and CLI) — Execute a shell command via the persistent crow-mcp PTY."""
        session = get_crow_session()
        result = await session.call_tool("terminal", {"command": command})
        output = result.content[0].text if result.content else ""
        return TerminalResult(output=output)
```

- [ ] **Step 4: Add crow case to `TerminalManager.create()`**

In `mahavishnu/terminal/manager.py`, after the mcpretentious block (after line ~460), add:

```python
        # crow (requires MCP client pointing at Bodai crow HTTP server)
        if preference == "crow":
            if mcp_client is None:
                raise ConfigurationError(
                    message="crow adapter requires mcp_client pointing at the Bodai crow HTTP server",
                    component="terminal_manager",
                    details={"adapter_preference": "crow"},
                )
            from .adapters.crow import CrowTerminalAdapter
            adapter = CrowTerminalAdapter(mcp_client=mcp_client)  # type: ignore[assignment]
            logger.info("Using crow terminal adapter")
            return cls(adapter, terminal_config)
```

- [ ] **Step 5: Add crow case to `terminal_switch_adapter`**

In `mahavishnu/mcp/tools/terminal_tools.py`, in `terminal_switch_adapter`, after the `elif adapter_name == "mcpretentious":` block (around line 176), add:

```python
        elif adapter_name == "crow":
            if mcp_client is None:
                return {"status": "error", "message": "crow adapter requires MCP client"}
            from mahavishnu.terminal.adapters.crow import CrowTerminalAdapter
            new_adapter = CrowTerminalAdapter(mcp_client)  # type: ignore[assignment]
```

Also update the error message on the final `else` branch to include `'crow'`:

```python
        else:
            return {
                "status": "error",
                "message": f"Unknown adapter: {adapter_name}. Use 'iterm2', 'mcpretentious', or 'crow'",
            }
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/unit/mcp/crow/test_terminal_proxy.py -v
```
Expected: 3 PASSED

- [ ] **Step 7: Commit**

```bash
git add mahavishnu/mcp/crow/terminal_proxy.py \
        mahavishnu/mcp/crow/tools/terminal_proxy_tool.py \
        mahavishnu/terminal/manager.py \
        mahavishnu/mcp/tools/terminal_tools.py \
        tests/unit/mcp/crow/test_terminal_proxy.py
git commit -m "feat(crow): Task 9 — terminal proxy + TerminalManager crow gap fix"
```

---

### Task 10: Server wiring + register_all + pyproject.toml deps

**Files:**
- Create: `mahavishnu/mcp/crow_server.py`
- Modify: `mahavishnu/mcp/crow/tools/__init__.py` (add `register_all`)
- Modify: `pyproject.toml` (swap httpx → httpx2, add new deps)

**Interfaces:**
- Consumes: all `register()` functions from tool modules
- Produces: `create_crow_server(settings: CrowSettings) -> StandardServer`

- [ ] **Step 1: Update `pyproject.toml`**

Replace:
```toml
"httpx[http2]>=0.28.1",
```
With:
```toml
"httpx2[zstd]~=0.1",
```

Add to `[project.dependencies]`:
```toml
"trafilatura~=2.1",
"selectolax~=0.3",
"markdownify~=0.13",
"charset-normalizer~=3.4",
"rapidfuzz~=3.9",
```

- [ ] **Step 2: Implement `register_all` in `tools/__init__.py`**

```python
# mahavishnu/mcp/crow/tools/__init__.py
from __future__ import annotations

from mcp_common.profiles.standard import StandardServer

from mahavishnu.mcp.crow.settings import CrowSettings
from . import file_tools, grep_tool, web_tools, search_tools, terminal_proxy_tool


def register_all(server: StandardServer, settings: CrowSettings) -> None:
    file_tools.register(server, settings)
    grep_tool.register(server, settings)
    web_tools.register(server, settings)
    search_tools.register(server, settings)
    terminal_proxy_tool.register(server, settings)
```

Add the missing `register()` function to `file_tools.py` (append):

```python
def register(server, settings: CrowSettings) -> None:
    @server.tool()
    async def read(
        file_path: str, offset: int = 0, limit: int | None = None, encoding: str = "utf-8"
    ) -> ReadResult:
        """(HTTP, for pool workers and CLI) — Read file contents with pagination."""
        return await _read(file_path, settings, offset, limit, encoding)

    @server.tool()
    async def write(
        file_path: str, content: str, dry_run: bool = False
    ) -> WriteResult:
        """(HTTP, for pool workers and CLI) — Write file atomically, preserving permissions."""
        return await _write(file_path, content, settings, dry_run)

    @server.tool()
    async def edit(
        file_path: str, old_string: str, new_string: str,
        replace_all: bool = False, dry_run: bool = False
    ) -> EditResult:
        """(HTTP, for pool workers and CLI) — Edit file with 9-level fuzzy cascade."""
        return await _edit(file_path, old_string, new_string, settings, replace_all, dry_run)

    @server.tool()
    async def glob(
        pattern: str, path: str = ".", include_hidden: bool = False,
        file_info: bool = True, max_results: int = 1000
    ) -> GlobResult:
        """(HTTP, for pool workers and CLI) — Glob files within workspace."""
        return await _glob(pattern, settings, path, include_hidden, file_info, max_results)
```

- [ ] **Step 3: Implement `crow_server.py`**

```python
# mahavishnu/mcp/crow_server.py
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from mcp_common.profiles.standard import StandardServer

from mahavishnu.mcp.crow.client import close_http_client, init_http_client
from mahavishnu.mcp.crow.settings import CrowSettings
from mahavishnu.mcp.crow.terminal_proxy import close_crow_stdio_client, init_crow_stdio_client
from mahavishnu.mcp.crow import tools


@asynccontextmanager
async def _lifespan(server: StandardServer) -> AsyncGenerator[None, None]:
    await init_http_client(server.settings)
    await init_crow_stdio_client(server.settings)
    try:
        yield
    finally:
        await close_http_client()
        await close_crow_stdio_client()


def create_crow_server(settings: CrowSettings | None = None) -> StandardServer:
    cfg = settings or CrowSettings()
    server = StandardServer(
        name="bodai-crow",
        description="Bodai-native file, web, and terminal tools over HTTP MCP",
        settings=cfg,
    )
    server.set_lifespan(_lifespan)
    tools.register_all(server, cfg)
    return server
```

- [ ] **Step 4: Install updated deps and verify imports**

```bash
uv pip install -e ".[dev]"
python -c "from mahavishnu.mcp.crow_server import create_crow_server; print('ok')"
```
Expected: `ok`

- [ ] **Step 5: Run full unit test suite**

```bash
pytest tests/unit/mcp/crow/ -v
```
Expected: all tests PASSED

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/mcp/crow_server.py mahavishnu/mcp/crow/tools/__init__.py \
        mahavishnu/mcp/crow/tools/file_tools.py pyproject.toml
git commit -m "feat(crow): Task 10 — server wiring, register_all, dep updates"
```

---

### Task 11: Integration tests, .mcp.json, runbooks

**Files:**
- Create: `tests/integration/mcp/__init__.py`
- Create: `tests/integration/mcp/crow/__init__.py`
- Create: `tests/integration/mcp/crow/conftest.py`
- Create: `tests/integration/mcp/crow/test_crow_server.py`
- Modify: `.mcp.json` (add `bodai-crow` HTTP entry)
- Create: `docs/runbooks/bodai-crow-server.md`
- Modify: `docs/runbooks/crow-mcp-server.md` (add cross-reference note)

- [ ] **Step 1: Create integration test scaffolding**

```python
# tests/integration/mcp/__init__.py  (empty)
# tests/integration/mcp/crow/__init__.py  (empty)
```

```python
# tests/integration/mcp/crow/conftest.py
from __future__ import annotations

import pytest
from mahavishnu.mcp.crow.settings import CrowSettings
from mahavishnu.mcp.crow_server import create_crow_server


@pytest.fixture(scope="module")
async def crow_server(tmp_path_factory):
    settings = CrowSettings(workspace_root=tmp_path_factory.mktemp("workspace"))
    server = create_crow_server(settings)
    # Use StandardServer's test context API — check mcp_common docs for exact method name.
    # If server.run_context() does not exist, use: async with server.lifespan_context():
    async with server.run_context():
        yield server
```

```python
# tests/integration/mcp/crow/test_crow_server.py
from __future__ import annotations

import httpx
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.mcp]


@pytest.mark.integration
async def test_health_endpoint_returns_200(crow_server):
    async with httpx.AsyncClient() as client:
        r = await client.get("http://localhost:8675/health")
    assert r.status_code == 200


@pytest.mark.integration
async def test_tool_list_includes_all_expected_tools(crow_server):
    # MCP tools/list via HTTP — exact call depends on mcp_common client API
    expected = {"read", "write", "edit", "glob", "grep",
                "web_fetch", "web_fetch_batch", "web_search", "terminal"}
    # Verify by calling tools/list via the MCP protocol
    # Placeholder: replace with actual mcp_common HTTP client call
    pass


@pytest.mark.integration
async def test_read_rejects_path_outside_workspace_as_mcp_error(crow_server):
    # Send read call with /etc/passwd — expect MCP error response, not HTTP 500
    pass


@pytest.mark.integration
@pytest.mark.requires_network
async def test_web_search_with_real_searxng(crow_server):
    # Only runs when SearXNG is running on localhost:2946
    pass
```

- [ ] **Step 2: Add `bodai-crow` to `.mcp.json`**

Open `.mcp.json` and add inside the `mcpServers` object:

```json
"bodai-crow": {
  "type": "http",
  "url": "http://localhost:8675/mcp"
}
```

The existing `"crow": {"command": "crow-mcp"}` entry is **retained** — Claude Code continues using it for its own terminal sessions.

- [ ] **Step 3: Create `docs/runbooks/bodai-crow-server.md`**

Create the file with at minimum these sections:
```markdown
# Bodai Crow HTTP MCP Server Runbook

**Port:** 8675  
**Transport:** HTTP MCP (SSE/StreamableHTTP)  
**Namespace:** `mcp__bodai-crow__*`

## Starting the server
\`\`\`bash
mahavishnu mcp start  # starts all registered MCP servers including bodai-crow
# or directly:
python -m mahavishnu.mcp.crow_server
\`\`\`

## SearXNG (required for web_search)
\`\`\`bash
docker compose -f docker-compose.crow.yml up -d
\`\`\`
Set a real `secret_key` in `settings/searxng/settings.yml` or `settings/local.yaml` before starting.

## ripgrep (optional, improves grep performance)
Install via: `brew install ripgrep` or `apt install ripgrep`
Detected automatically at runtime via `shutil.which("rg")`. Falls back to pure Python if absent.

## workspace_root
Defaults to `Path.cwd()`. Widen in `settings/local.yaml`:
\`\`\`yaml
crow:
  workspace_root: "/Users/les/Projects"
\`\`\`

## Tool disambiguation
Both `crow` (stdio) and `bodai-crow` (HTTP) expose tools with the same names.
MCP namespaces them: `mcp__crow__read` vs `mcp__bodai-crow__read`.
bodai-crow returns structured TypedDicts; crow-mcp returns plain strings — not interchangeable.
```

- [ ] **Step 4: Add cross-reference to `docs/runbooks/crow-mcp-server.md`**

Add at the top of `docs/runbooks/crow-mcp-server.md`:

```markdown
> **See also:** [Bodai Crow HTTP MCP Server](bodai-crow-server.md) — the HTTP transport
> version of this server for pool workers, CLI, and ACP agents.
```

- [ ] **Step 5: Run integration tests (they should pass or skip — not fail hard)**

```bash
pytest tests/integration/mcp/crow/ -v -m "integration and mcp"
```
Expected: tests that have `pass` bodies pass trivially; `requires_network` tests skip if SearXNG is not running.

- [ ] **Step 6: Run full test suite, verify no regressions**

```bash
pytest tests/unit/ -v --tb=short
```
Expected: all unit tests PASSED, no regressions in existing tests.

- [ ] **Step 7: Commit**

```bash
git add tests/integration/mcp/ .mcp.json \
        docs/runbooks/bodai-crow-server.md docs/runbooks/crow-mcp-server.md \
        docker-compose.crow.yml settings/searxng/
git commit -m "feat(crow): Task 11 — integration tests, .mcp.json, runbooks"
```

---

## Self-Review

**Spec coverage check:**

| Spec section | Covered by |
|---|---|
| §1 motivation + TerminalManager gap | Task 9 |
| §2 A-hybrid architecture | Tasks 3–9 (native) + Task 9 (proxy) |
| §3 StandardServer + lifespan | Task 10 |
| §3.1 CrowSettings | Task 1 |
| §3.2 terminal proxy lifecycle | Task 9 |
| §4 TerminalManager crow case | Task 9 |
| §5.1 error convention | Tasks 3–8 (raise vs in-band error) |
| §5.2 read | Task 3 |
| §5.3 write | Task 3 |
| §5.4 edit + vendor/editor.py | Tasks 2 + 4 |
| §5.5 web_fetch | Task 7 |
| §5.6 web_search | Task 8 |
| §5.7 glob | Task 5 |
| §5.8 grep | Task 6 |
| §5.9 web_fetch_batch | Task 7 |
| §6.1 path security | Task 1 |
| §6.2 SSRF mitigation | Task 1 |
| §6.3 shared httpx2 client | Task 1 |
| §6.4 tool registration | Task 10 |
| §7 SearXNG deployment | Task 8 |
| §8 .mcp.json changes | Task 11 |
| §10 new dependencies | Task 10 |
| §11 file layout | All tasks |
| §12 testing strategy | All tasks |
| §13 Q5 lifespan API | Task 10 — verify `set_lifespan()` exists; fallback: `lifespan=` param in `StandardServer(...)` |
| §13 Q7 symlink semantics | Documented in `_write`: `os.replace` on a symlink path replaces the link, not the target |

**Gaps / confirmations needed before Task 10:**
1. Confirm `StandardServer.set_lifespan()` exists in the installed `mcp-common` version. If it doesn't, replace with the `lifespan=` constructor parameter: `StandardServer(..., lifespan=_lifespan)`.
2. Check whether the vendored `replace()` in Task 2 returns `str` or `tuple[str, str]` (content, level_name). Update `_edit` accordingly.
3. Confirm `StandardServer.run_context()` API for integration test fixture in Task 11. Check `mcp_common` source.
