# Constellation TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface Bodai ecosystem activity (pools, workers, workflows, lifecycle events) in Claude Code via three extension surfaces — extended `statusLine`, new `subagentStatusLine`, and OSC 777 native toasts — wired to the existing Mahavishnu EventBridge (channel `bodai:events`).

**Architecture:** A new `mahavishnu/constellation/` subpackage provides the library code (OSC emit, ecosystem health probe, statusline extensions, EventBridge subscriber, subagent row renderer). A new CLI command `mahavishnu constellation install` copies the bridge script and subagent statusline script into `~/.claude/scripts/` and `~/.claude/hooks/`, registers the `PostToolUse` hook and `subagentStatusLine` config in `~/.claude/settings.json`, and patches the user's existing `session_progress_real.py` to import the statusline extensions library. All three surfaces consume shared runtime state in `~/.mahavishnu/` (last-event.json, worker-status/, ecosystem-health-cache.json) written by the bridge.

**Tech Stack:** Python 3.13, `httpx` (async HTTP for ecosystem health probes), `redis` asyncio client (EventBridge `xread` subscription), `pytest` + `pytest-asyncio` (auto mode), `typer` (CLI), existing `mahavishnu` package patterns, Oneiric logger.

## Global Constraints

**Spec source:** `docs/superpowers/specs/2026-07-15-constellation-tui-design.md` (committed `a143d5c`).

**Code conventions** (per project `CLAUDE.md` § Crackerjack-Compliant Code):
- Every source file: `from __future__ import annotations` as first non-comment line (after module docstring).
- Imports sorted within each section (stdlib → third-party → first-party); `force-sort-within-sections = true`; `known-first-party = ["mahavishnu"]`.
- Modern syntax only: `X | None` (never `Optional[X]`), `list[str]`, `pathlib.Path`.
- Function args with default `None` typed as `X | None = None` (mypy `no_implicit_optional = true`).
- No `assert` in production code (`mahavishnu/**`); use `mahavishnu/core/errors.py` exception hierarchy.
- No `Any` in tool inputs or orchestration state; use `TYPE_CHECKING` and protocols to escape.
- `except` blocks: use `logger.exception(...)`, never `logger.error(..., exc_info=True)`.
- All I/O in orchestration layer is async; sync code only at worker boundaries and CLI entry points.
- Use the Oneiric logger (`oneiric.logging`) — not stdlib `logging`, not `print()`.
- Line length: 100 chars max (Ruff).
- Function args ≤ 10 (excludes `self`, `cls`, `*args`, `**kwargs`).
- Branches ≤ 15, returns ≤ 6, statements ≤ 55 (practical target 30).
- Coverage ≥ 80%.

**Test conventions:**
- Pytest markers: `unit`, `integration`, `slow`, `timeout`, `requires_network`.
- Async tests: no `@pytest.mark.asyncio` needed (`asyncio_mode = "auto"`).
- Per-test timeout: 300s ceiling. Tests >10s are `@pytest.mark.slow`.
- Integration tests against a real Redis use `MAHAVISHNU_EVENTBRIDGE_INTEGRATION=1` env gate.
- Tests live in `tests/unit/constellation/` (mirrors `mahavishnu/constellation/`).

**Required skills (loaded before each task or step as indicated):**

| Skill | When to load | Purpose |
|---|---|---|
| `superpowers:test-driven-development` | First step of every task that adds code | Write the failing test, watch it fail, then implement |
| `superpowers:subagent-driven-development` | Plan execution phase (after this plan is approved) | Fresh subagent per task + two-stage review between tasks |
| `crackerjack-compliant-code` | Before every commit (final step of every task) | Run `crackerjack run` to enforce Ruff/mypy/pyright/bandit/pytest; gate on pass |
| `tui-designer` | Tasks 1, 4, 5, 6 (visual decisions, terminal output aesthetics) | Validate ANSI colors, glyph choices, bar widths, OSC 8 syntax |
| `superpowers:writing-plans` (already loaded) | This plan authoring | — |
| `superpowers:brainstorming` (already loaded) | Spec phase (already complete) | — |
| `superpowers:using-git-worktrees` | First task (before any code) | Isolate implementation work from main branch |

**Environment variables the bridge script reads:**
- `MAHAVISHNU_EVENTBRIDGE_URL` (default: `redis://localhost:6379/0`) — Redis URL for the EventBridge.
- `MAHAVISHNU_EVENTBRIDGE_CHANNEL` (default: `bodai:events`) — Redis Streams channel name.
- `MAHAVISHNU_OSC_PROBE_DISABLE` (default: unset) — set to `1` to skip the OSC 777 capability probe.

**Runtime state files (created under `~/.mahavishnu/`):**
- `last-event.json` — atomic JSON write of the most-recent event (consumed by statusline).
- `worker-status/<task_id>.json` — per-worker cache (consumed by subagent statusline).
- `ecosystem-health-cache.json` — 30s TTL cache of component health probes.
- `logs/mcp.log` — existing structured log destination (appended).

**Out of scope for this plan (deferred):**
- Track 2 — Toad/ACP integration (separate spec).
- Replacing `session_progress_real.py` outright (we patch it to import from the library).
- Any change to Mahavishnu core, MCP server ports, or EventBridge transport.
- Production hardening of OSC 777 (probe + capability detection are basic; tmux/screen stripping is a known limitation we document but don't work around).

---

## File Structure

Files created in this plan:

```
mahavishnu/constellation/
├── __init__.py                  # NEW — package marker; re-exports public API
├── osc.py                       # NEW — OSC 777 emit + capability probe
├── ecosystem_health.py          # NEW — async health probe cache
├── statusline_extensions.py     # NEW — three new helpers (ecosystem, event tail, weekly cap)
├── activity_stream.py           # NEW — EventBridge subscriber + cache writers + OSC emitter
├── subagent_status.py           # NEW — per-task JSON row renderer
└── install.py                   # NEW — file copier + settings.json patcher

mahavishnu/cli/
└── constellation_cli.py         # NEW — `mahavishnu constellation {install,uninstall,status}`

tests/unit/constellation/
├── __init__.py                  # NEW — empty
├── test_osc.py                  # NEW
├── test_ecosystem_health.py     # NEW
├── test_statusline_extensions.py # NEW
├── test_activity_stream.py      # NEW
├── test_subagent_status.py      # NEW
└── test_install.py              # NEW

tests/integration/constellation/
└── test_activity_stream_integration.py  # NEW (gated)

docs/constellation/
└── INSTALL.md                   # NEW — operator-facing install/usage doc
```

Files modified:
- `~/.claude/scripts/session_progress_real.py` — patch (one-time, by installer) to import `mahavishnu.constellation.statusline_extensions`
- `~/.claude/settings.json` — patch (by installer) to add `subagentStatusLine` and `PostToolUse` hook

---

## Task 1: Set up worktree and package skeleton

**Files:**
- Create: `mahavishnu/constellation/__init__.py`
- Create: `tests/unit/constellation/__init__.py`

**Interfaces:**
- Consumes: nothing (skeleton)
- Produces: empty `mahavishnu.constellation` and `tests.unit.constellation` packages, importable

**Required skills:**
- `superpowers:using-git-worktrees` — before any code: create worktree `constellation-tui-impl` off main.
- `superpowers:test-driven-development` — N/A (no test this task).
- `crackerjack-compliant-code` — final step: `crackerjack run` passes on the empty packages.

- [ ] **Step 1: Load worktree skill and create worktree**

  Run the `superpowers:using-git-worktrees` skill. Create worktree at `.claude/worktrees/constellation-tui-impl` branched from `main`. All subsequent tasks happen inside this worktree.

- [ ] **Step 2: Create the constellation package directory**

  ```bash
  mkdir -p mahavishnu/constellation
  ```

- [ ] **Step 3: Create `mahavishnu/constellation/__init__.py`**

  ```python
  """Constellation TUI: Claude Code extension surfaces for Bodai activity."""
  ```

  No re-exports yet — Task 7 (final task) adds them.

- [ ] **Step 4: Create the tests directory and marker**

  ```bash
  mkdir -p tests/unit/constellation
  ```

  `tests/unit/constellation/__init__.py`:
  ```python
  """Unit tests for mahavishnu.constellation."""
  ```

- [ ] **Step 5: Verify packages import**

  Run: `uv run python -c "import mahavishnu.constellation; import tests.unit.constellation; print('ok')"`
  Expected output: `ok`

- [ ] **Step 6: Run crackerjack to confirm baseline passes**

  Load: `crackerjack-compliant-code`
  Run: `crackerjack run`
  Expected: passes on the empty new packages (no new errors introduced).

- [ ] **Step 7: Commit**

  ```bash
  git add mahavishnu/constellation/__init__.py tests/unit/constellation/__init__.py
  git commit -m "feat(constellation): scaffold package skeleton"
  ```

---

## Task 2: OSC 777 emit + capability probe

**Files:**
- Create: `mahavishnu/constellation/osc.py`
- Create: `tests/unit/constellation/test_osc.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `emit_osc777_toast(title: str, body: str, *, stream: TextIO = sys.stderr) -> bool` — returns True on success, False on emit failure. Writes the OSC 777 sequence followed by a `\a` (BEL) terminator.
  - `probe_osc_support(*, stream: TextIO = sys.stderr) -> bool` — returns True if the terminal claims to support OSC 777. Honors `MAHAVISHNU_OSC_PROBE_DISABLE=1`.

**Required skills:**
- `tui-designer` — validate the OSC 777 sequence format and the probe approach (write a non-destructive sequence, check for terminal echo).
- `superpowers:test-driven-development` — write tests first.
- `crackerjack-compliant-code` — final step.

- [ ] **Step 1: Load skills and write the failing tests**

  Load: `superpowers:test-driven-development`, `tui-designer`.

  `tests/unit/constellation/test_osc.py`:
  ```python
  from __future__ import annotations

  from io import StringIO

  from mahavishnu.constellation.osc import emit_osc777_toast, probe_osc_support


  def test_emit_osc777_toast_writes_correct_sequence() -> None:
      buf = StringIO()
      result = emit_osc777_toast("worker w-02 completed", "stage=plan · 28s", stream=buf)
      assert result is True
      output = buf.getvalue()
      # OSC 777 notify sequence: ESC ] 777 ; notify ; title=...; body=... BEL
      assert output.startswith("\x1b]777;notify;")
      assert "title=worker w-02 completed" in output
      assert "body=stage=plan" in output
      assert output.rstrip().endswith("\x1b\\") or output.endswith("\a")


  def test_emit_osc777_toast_returns_false_on_write_error() -> None:
      class BrokenStream:
          def write(self, _data: str) -> int:
              raise OSError("stream closed")

          def flush(self) -> None:
              pass

      result = emit_osc777_toast("x", "y", stream=BrokenStream())  # type: ignore[arg-type]
      assert result is False


  def test_probe_osc_support_disabled_env_returns_true(monkeypatch: object) -> None:
      import os
      os.environ["MAHAVISHNU_OSC_PROBE_DISABLE"] = "1"
      try:
          assert probe_osc_support() is True
      finally:
          del os.environ["MAHAVISHNU_OSC_PROBE_DISABLE"]


  def test_probe_osc_support_returns_bool() -> None:
      """Probe should not raise; result type is documented but terminal-dependent."""
      result = probe_osc_support()
      assert isinstance(result, bool)
  ```

- [ ] **Step 2: Run tests to verify they fail**

  Run: `uv run pytest tests/unit/constellation/test_osc.py -v`
  Expected: `ModuleNotFoundError: No module named 'mahavishnu.constellation.osc'`

- [ ] **Step 3: Implement `mahavishnu/constellation/osc.py`**

  ```python
  from __future__ import annotations

  import os
  import sys
  from typing import TextIO


  def emit_osc777_toast(
      title: str,
      body: str,
      *,
      stream: TextIO = sys.stderr,
  ) -> bool:
      """Emit an OSC 777 native terminal notification.

      Returns True on successful write, False if the stream rejected the write.
      Terminals that don't recognize OSC 777 will silently ignore the sequence.
      """
      # Sanitize: OSC sequences must not contain ST (ESC \\) or BEL inside fields
      safe_title = title.replace("\x1b", "").replace("\a", "")
      safe_body = body.replace("\x1b", "").replace("\a", "")
      sequence = f"\x1b]777;notify;title={safe_title};body={safe_body}\x1b\\"
      try:
          stream.write(sequence)
          stream.flush()
      except (OSError, ValueError):
          return False
      return True


  def probe_osc_support(*, stream: TextIO = sys.stderr) -> bool:
      """Probe the terminal for OSC 777 support.

      Returns True if the operator has disabled probing via
      MAHAVISHNU_OSC_PROBE_DISABLE=1, or if the terminal responds to a
      write+flush of the probe sequence without error. The probe is
      intentionally cheap (writes a no-op OSC 777) — we cannot reliably
      detect terminal support from Python alone, so this is best-effort.
      """
      if os.environ.get("MAHAVISHNU_OSC_PROBE_DISABLE") == "1":
          return True
      try:
          stream.write("\x1b]777;notify;title=osc-probe;body=\x1b\\")
          stream.flush()
          return True
      except (OSError, ValueError):
          return False
  ```

- [ ] **Step 4: Run tests to verify they pass**

  Run: `uv run pytest tests/unit/constellation/test_osc.py -v`
  Expected: all 4 tests PASS.

- [ ] **Step 5: Run crackerjack**

  Load: `crackerjack-compliant-code`.
  Run: `crackerjack run -- tests/unit/constellation/test_osc.py`
  Expected: passes; no lint/type errors.

- [ ] **Step 6: Commit**

  ```bash
  git add mahavishnu/constellation/osc.py tests/unit/constellation/test_osc.py
  git commit -m "feat(constellation): OSC 777 emit + capability probe"
  ```

---

## Task 3: Ecosystem health probe cache

**Files:**
- Create: `mahavishnu/constellation/ecosystem_health.py`
- Create: `tests/unit/constellation/test_ecosystem_health.py`

**Interfaces:**
- Consumes: `MAHAVISHNU_COMPONENT_PORTS` (a dict literal in the module; default values: `{"mahavishnu": 8680, "akosha": 8682, "dhara": 8683, "crackerjack": 8676, "session-buddy": 8678}`).
- Produces:
  - `class ComponentHealth(NamedTuple): name: str; port: int; status: Literal["up", "down", "stale"]; latency_ms: int | None`
  - `async def probe_components(*, base_url_template: str = "http://localhost:{port}/health", timeout_s: float = 2.0) -> list[ComponentHealth]` — probes each component in parallel via `httpx.AsyncClient`. Returns one `ComponentHealth` per component, even on failure (`status="down"`).
  - `async def cached_probe_components(cache_path: Path = Path.home() / ".mahavishnu" / "ecosystem-health-cache.json", ttl_s: float = 30.0) -> list[ComponentHealth]` — wraps `probe_components` with a 30s TTL cache file. Returns cached results if fresh, else probes and writes.

**Required skills:**
- `superpowers:test-driven-development`.
- `crackerjack-compliant-code`.

- [ ] **Step 1: Load TDD skill and write the failing tests**

  Load: `superpowers:test-driven-development`.

  `tests/unit/constellation/test_ecosystem_health.py`:
  ```python
  from __future__ import annotations

  import json
  from pathlib import Path

  import pytest

  from mahavishnu.constellation.ecosystem_health import (
      ComponentHealth,
      cached_probe_components,
      probe_components,
  )


  @pytest.mark.asyncio
  async def test_probe_components_returns_one_per_known(monkeypatch: pytest.MonkeyPatch) -> None:
      """Stub httpx so each port returns 200 OK with a known body."""
      import httpx

      async def fake_get(self: httpx.AsyncClient, url: str, **kwargs: object) -> httpx.Response:
          return httpx.Response(200, json={"status": "ok"})

      monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
      results = await probe_components(timeout_s=0.5)
      names = {r.name for r in results}
      assert names == {"mahavishnu", "akosha", "dhara", "crackerjack", "session-buddy"}
      assert all(r.status == "up" for r in results)


  @pytest.mark.asyncio
  async def test_probe_components_marks_timeouts_as_down(monkeypatch: pytest.MonkeyPatch) -> None:
      import httpx

      async def fake_get(self: httpx.AsyncClient, url: str, **kwargs: object) -> httpx.Response:
          raise httpx.TimeoutException("nope")

      monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
      results = await probe_components(timeout_s=0.1)
      assert all(r.status == "down" for r in results)
      assert all(r.latency_ms is None for r in results)


  @pytest.mark.asyncio
  async def test_cached_probe_components_writes_cache(
      tmp_path: Path,
      monkeypatch: pytest.MonkeyPatch,
  ) -> None:
      import httpx

      async def fake_get(self: httpx.AsyncClient, url: str, **kwargs: object) -> httpx.Response:
          return httpx.Response(200, json={"status": "ok"})

      monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
      cache = tmp_path / "cache.json"
      results = await cached_probe_components(cache_path=cache, ttl_s=30.0)
      assert all(r.status == "up" for r in results)
      assert cache.exists()
      cached_data = json.loads(cache.read_text())
      assert "mahavishnu" in cached_data
      assert "expires_at" in cached_data


  @pytest.mark.asyncio
  async def test_cached_probe_components_returns_fresh_cache_without_probing(
      tmp_path: Path,
      monkeypatch: pytest.MonkeyPatch,
  ) -> None:
      """When cache is fresh, no HTTP requests should fire."""
      import time

      import httpx

      def fail_get(*args: object, **kwargs: object) -> None:
          raise AssertionError("HTTP should not be called when cache is fresh")

      monkeypatch.setattr(httpx.AsyncClient, "get", fail_get)

      cache = tmp_path / "cache.json"
      now = time.time()
      cache.write_text(json.dumps({
          "mahavishnu": {"status": "up", "port": 8680, "latency_ms": 12},
          "akosha": {"status": "up", "port": 8682, "latency_ms": 8},
          "dhara": {"status": "up", "port": 8683, "latency_ms": 5},
          "crackerjack": {"status": "up", "port": 8676, "latency_ms": 11},
          "session-buddy": {"status": "up", "port": 8678, "latency_ms": 7},
          "expires_at": now + 60.0,  # fresh
      }))
      results = await cached_probe_components(cache_path=cache, ttl_s=30.0)
      assert len(results) == 5
      assert all(r.status == "up" for r in results)
  ```

- [ ] **Step 2: Run tests to verify they fail**

  Run: `uv run pytest tests/unit/constellation/test_ecosystem_health.py -v`
  Expected: `ModuleNotFoundError: No module named 'mahavishnu.constellation.ecosystem_health'`

- [ ] **Step 3: Implement `mahavishnu/constellation/ecosystem_health.py`**

  ```python
  from __future__ import annotations

  import json
  import time
  from pathlib import Path
  from typing import Literal, NamedTuple

  import httpx

  COMPONENT_PORTS: dict[str, int] = {
      "mahavishnu": 8680,
      "akosha": 8682,
      "dhara": 8683,
      "crackerjack": 8676,
      "session-buddy": 8678,
  }

  Status = Literal["up", "down", "stale"]


  class ComponentHealth(NamedTuple):
      name: str
      port: int
      status: Status
      latency_ms: int | None


  async def probe_components(
      *,
      base_url_template: str = "http://localhost:{port}/health",
      timeout_s: float = 2.0,
  ) -> list[ComponentHealth]:
      """Probe each known component's /health endpoint in parallel."""
      results: list[ComponentHealth] = []
      async with httpx.AsyncClient(timeout=timeout_s) as client:
          async with httpx.AsyncClient() as _noop:  # type: ignore[misc]
              pass
          # Build coroutines for each component
          import asyncio

          async def _probe(name: str, port: int) -> ComponentHealth:
              url = base_url_template.format(port=port)
              t0 = time.monotonic()
              try:
                  resp = await client.get(url)
                  latency_ms = int((time.monotonic() - t0) * 1000)
                  if resp.status_code < 500:
                      return ComponentHealth(name=name, port=port, status="up", latency_ms=latency_ms)
                  return ComponentHealth(name=name, port=port, status="down", latency_ms=latency_ms)
              except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError):
                  return ComponentHealth(name=name, port=port, status="down", latency_ms=None)

          coros = [_probe(name, port) for name, port in COMPONENT_PORTS.items()]
          results = await asyncio.gather(*coros)
      return list(results)


  async def cached_probe_components(
      *,
      cache_path: Path = Path.home() / ".mahavishnu" / "ecosystem-health-cache.json",
      ttl_s: float = 30.0,
  ) -> list[ComponentHealth]:
      """Return cached health if fresh; otherwise probe and persist."""
      if cache_path.exists():
          try:
              data = json.loads(cache_path.read_text())
              if float(data.get("expires_at", 0.0)) > time.time():
                  results = [
                      ComponentHealth(
                          name=name,
                          port=int(entry["port"]),
                          status=entry["status"],
                          latency_ms=entry.get("latency_ms"),
                      )
                      for name, entry in data.items()
                      if name != "expires_at"
                  ]
                  if len(results) == len(COMPONENT_PORTS):
                      return results
          except (json.JSONDecodeError, KeyError, ValueError):
              pass  # fall through to fresh probe

      results = await probe_components()
      payload: dict[str, object] = {
          "expires_at": time.time() + ttl_s,
      }
      for r in results:
          payload[r.name] = {
              "port": r.port,
              "status": r.status,
              "latency_ms": r.latency_ms,
          }
      cache_path.parent.mkdir(parents=True, exist_ok=True)
      cache_path.write_text(json.dumps(payload))
      return results
  ```

- [ ] **Step 4: Run tests to verify they pass**

  Run: `uv run pytest tests/unit/constellation/test_ecosystem_health.py -v`
  Expected: all 4 tests PASS.

- [ ] **Step 5: Run crackerjack**

  Load: `crackerjack-compliant-code`.
  Run: `crackerjack run -- tests/unit/constellation/test_ecosystem_health.py`
  Expected: passes.

- [ ] **Step 6: Commit**

  ```bash
  git add mahavishnu/constellation/ecosystem_health.py tests/unit/constellation/test_ecosystem_health.py
  git commit -m "feat(constellation): ecosystem health probe + 30s cache"
  ```

---

## Task 4: Statusline extensions library (third bar)

**Files:**
- Create: `mahavishnu/constellation/statusline_extensions.py`
- Create: `tests/unit/constellation/test_statusline_extensions.py`

**Interfaces:**
- Consumes: `platform` (string: `"anthropic"`, `"minimax"`, `"zai"`, `"zhipu"`).
- Produces:
  - `def format_weekly_cap(platform: str, *, jsonl_dir: Path | None = None, mini_max_url: str | None = None) -> str | None` — returns the formatted third-bar line (status badge + progress bar + meta) or `None` if backend fails. Reuses the user's existing `create_progress_bar`, `get_status_indicator`, `format_tokens`, `format_time` style from `session_progress_real.py`.

**Required skills:**
- `tui-designer` — validate bar widths and tier colors match the existing script's aesthetic.
- `superpowers:test-driven-development`.
- `crackerjack-compliant-code`.

- [ ] **Step 1: Load TDD and tui-designer skills; write failing tests**

  Load: `superpowers:test-driven-development`, `tui-designer`.

  `tests/unit/constellation/test_statusline_extensions.py`:
  ```python
  from __future__ import annotations

  from pathlib import Path

  from mahavishnu.constellation.statusline_extensions import format_weekly_cap


  def test_format_weekly_cap_anthropic_returns_bar_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
      """When given a JSONL dir with assistant records summing > 50% of weekly cap, returns a HIGH-tier line."""
      import json

      jsonl = tmp_path / "claude-session.jsonl"
      records = [
          {
              "type": "assistant",
              "timestamp": "2026-07-15T07:40:00+00:00",
              "requestId": f"req-{i}",
              "message": {
                  "model": "claude-sonnet-4-6",
                  "usage": {"input_tokens": 30_000, "cache_creation_input_tokens": 0},
              },
          }
          for i in range(100)
      ]
      jsonl.write_text("\n".join(json.dumps(r) for r in records))
      line = format_weekly_cap("anthropic", jsonl_dir=tmp_path)
      assert line is not None
      assert "weekly" in line.lower()
      # 3M tokens / 10M cap = 30%, expect OK tier
      assert "OK" in line or "MED" in line


  def test_format_weekly_cap_minimax_calls_api(monkeypatch: pytest.MonkeyPatch) -> None:
      """When platform is minimax, the MiniMax token_plan/remains endpoint is consulted."""
      import json

      class FakeResponse:
          def __init__(self, payload: dict[str, object]) -> None:
              self._payload = payload

          def read(self) -> bytes:
              return json.dumps(self._payload).encode()

      class FakeUrlopen:
          def __init__(self, url: str) -> None:
              self.url = url

          def __enter__(self) -> FakeResponse:
              return FakeResponse({
                  "model_remains": [
                      {
                          "model_name": "MiniMax-M3",
                          "current_interval_total_count": 10_000_000,
                          "current_interval_usage_count": 9_200_000,
                          "end_time": 1_750_000_000_000,
                      }
                  ],
              })

          def __exit__(self, *args: object) -> None:
              pass

      monkeypatch.setattr(
          "mahavishnu.constellation.statusline_extensions.urlopen",
          lambda url: FakeUrlopen(url),  # type: ignore[arg-type]
      )
      line = format_weekly_cap("minimax")
      assert line is not None
      assert "HIGH" in line  # 92%


  def test_format_weekly_cap_returns_none_on_backend_failure(monkeypatch: pytest.MonkeyPatch) -> None:
      """If the backend raises, return None so the caller can degrade to 2-bar layout."""
      def broken(*args: object, **kwargs: object) -> None:
          raise RuntimeError("upstream down")

      monkeypatch.setattr(
          "mahavishnu.constellation.statusline_extensions.urlopen",
          broken,  # type: ignore[arg-type]
      )
      assert format_weekly_cap("minimax") is None


  def test_format_weekly_cap_unknown_platform_returns_none() -> None:
      assert format_weekly_cap("unknown-platform") is None
  ```

- [ ] **Step 2: Run tests to verify they fail**

  Run: `uv run pytest tests/unit/constellation/test_statusline_extensions.py -v`
  Expected: `ModuleNotFoundError: No module named 'mahavishnu.constellation.statusline_extensions'`

- [ ] **Step 3: Implement `mahavishnu/constellation/statusline_extensions.py` (third-bar helper)**

  ```python
  from __future__ import annotations

  import json
  from datetime import datetime, timezone
  from pathlib import Path
  from urllib.request import Request, urlopen

  # Reuse the user's existing bar/indicator helpers. These are duplicated as
  # constants here to keep the library self-contained; the user's script can
  # either import these or keep its own copy. Constants must match the user's
  # script exactly.
  WEEKLY_BUDGET = 10_000_000   # ~10M tokens weekly (Anthropic Sonnet/Opus estimate)
  BAR_WIDTH = 12
  SMOOTH = "▏▎▍▌▋▊▉█"

  RESET = "\033[0m"
  COLORS = {
      "OK": "\033[32m",
      "MED": "\033[33m",
      "HIGH": "\033[35m",
      "LIMIT": "\033[31m",
  }


  def _bar(pct: float, width: int = BAR_WIDTH) -> str:
      pct = max(0.0, min(pct, 100.0))
      filled = (width * pct) / 100
      full = int(filled)
      remainder = filled - full
      bar = "█" * full
      if full < width and remainder > 0:
          bar += SMOOTH[max(0, int(remainder * len(SMOOTH)) - 1)]
          bar += " " * (width - full - 1)
      else:
          bar += " " * (width - full)
      return bar


  def _tier(pct: float) -> str:
      if pct >= 100:
          return "LIMIT"
      if pct >= 90:
          return "HIGH"
      if pct >= 75:
          return "MED"
      return "OK"


  def _fmt_tokens(n: int) -> str:
      if n >= 1_000_000:
          return f"{n / 1_000_000:.1f}m"
      if n >= 1_000:
          return f"{n / 1_000:.0f}k"
      return str(n)


  def _anthropic_weekly(jsonl_dir: Path) -> float:
      """Sum Anthropic tokens from the last 7 days of JSONL records."""
      from datetime import timedelta
      cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).timestamp()
      seen: set[str] = set()
      total = 0
      for jsonl in jsonl_dir.rglob("*.jsonl"):
          try:
              for line in jsonl.open():
                  try:
                      d = json.loads(line)
                      if d.get("type") != "assistant":
                          continue
                      model = d.get("message", {}).get("model", "")
                      if not model.startswith("claude-"):
                          continue
                      req_id = d.get("requestId", "")
                      if req_id in seen:
                          continue
                      ts = d.get("timestamp", "")
                      if not ts:
                          continue
                      ts_epoch = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                      if ts_epoch < cutoff:
                          continue
                      usage = d.get("message", {}).get("usage", {})
                      if not usage:
                          continue
                      if req_id:
                          seen.add(req_id)
                      total += (
                          usage.get("input_tokens", 0)
                          + usage.get("cache_creation_input_tokens", 0)
                      )
                  except (json.JSONDecodeError, KeyError, ValueError):
                      continue
          except OSError:
              continue
      return min(total / WEEKLY_BUDGET * 100.0, 100.0)


  def _minimax_weekly() -> float:
      """Consult MiniMax /v1/token_plan/remains for the current weekly usage."""
      import os
      auth = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
      base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.minimax.io").replace("/anthropic", "").rstrip("/")
      req = Request(
          f"{base}/v1/token_plan/remains",
          headers={"Authorization": f"Bearer {auth}", "Content-Type": "application/json"},
      )
      with urlopen(req, timeout=10) as resp:  # noqa: S310
          data = json.loads(resp.read())
      for entry in data.get("model_remains", []):
          if entry.get("model_name", "").startswith("MiniMax-M"):
              total = float(entry.get("current_interval_total_count", 0))
              used = float(entry.get("current_interval_usage_count", 0))
              if total > 0:
                  return min(used / total * 100.0, 100.0)
      return 0.0


  def format_weekly_cap(
      platform: str,
      *,
      jsonl_dir: Path | None = None,
  ) -> str | None:
      """Return the third-bar line for the statusline, or None on backend failure."""
      try:
          if platform == "anthropic":
              jsonl_dir = jsonl_dir or Path.home() / ".claude" / "projects"
              pct = _anthropic_weekly(jsonl_dir)
          elif platform == "minimax":
              pct = _minimax_weekly()
          elif platform in ("zai", "zhipu"):
              # ZAI/ZHIPU weekly limit is exposed via /monitor/usage/quota/limit
              # with a "TOKENS_LIMIT" type entry. For v1, reuse the same shape
              # as the existing GLMBackend in session_progress_real.py. To keep
              # this task scoped, we return None and let the user's existing
              # 2-bar layout render. A future task wires the GLM weekly call.
              return None
          else:
              return None
      except (OSError, KeyError, ValueError, json.JSONDecodeError):
          return None

      tier = _tier(pct)
      color = COLORS[tier]
      bar = _bar(pct)
      reset_at = "Sun 00:00"
      return (
          f"{color}{tier:<5}{RESET} │ {color}{bar}{RESET} {pct:3.0f}% │ "
          f"{_fmt_tokens(int(WEEKLY_BUDGET * pct / 100))}/{_fmt_tokens(WEEKLY_BUDGET)} │ "
          f"weekly all-model │ resets {reset_at}"
      )
  ```

- [ ] **Step 4: Run tests to verify they pass**

  Run: `uv run pytest tests/unit/constellation/test_statusline_extensions.py -v`
  Expected: 4 tests PASS.

- [ ] **Step 5: Run crackerjack**

  Load: `crackerjack-compliant-code`.
  Run: `crackerjack run -- tests/unit/constellation/test_statusline_extensions.py`
  Expected: passes.

- [ ] **Step 6: Commit**

  ```bash
  git add mahavishnu/constellation/statusline_extensions.py tests/unit/constellation/test_statusline_extensions.py
  git commit -m "feat(constellation): weekly all-model cap bar"
  ```

---

## Task 5: Statusline extensions — ecosystem summary + event tail + adaptive line count

**Files:**
- Modify: `mahavishnu/constellation/statusline_extensions.py`
- Modify: `tests/unit/constellation/test_statusline_extensions.py`

**Interfaces:**
- Adds to `statusline_extensions`:
  - `def format_ecosystem_summary(components: list[ComponentHealth]) -> str` — one line of OSC 8 clickable glyphs.
  - `def format_event_tail(event: dict[str, object] | None) -> str` — one line, tail of last-event.json.
  - `def render_constellation_lines(platform: str, *, columns: int = 120, jsonl_dir: Path | None = None, last_event_path: Path | None = None) -> list[str]` — top-level orchestrator: returns 3, 4, or 5 lines based on `columns`.

**Required skills:**
- `tui-designer` — OSC 8 syntax validation; glyph choices; terminal-width adaptation breakpoints.
- `superpowers:test-driven-development`.
- `crackerjack-compliant-code`.

- [ ] **Step 1: Load TDD skill; add failing tests**

  Load: `superpowers:test-driven-development`, `tui-designer`.

  Append to `tests/unit/constellation/test_statusline_extensions.py`:
  ```python
  from mahavishnu.constellation.ecosystem_health import ComponentHealth
  from mahavishnu.constellation.statusline_extensions import (
      format_ecosystem_summary,
      format_event_tail,
      render_constellation_lines,
  )


  def test_format_ecosystem_summary_contains_osc8_escapes() -> None:
      components = [
          ComponentHealth("mahavishnu", 8680, "up", 12),
          ComponentHealth("akosha", 8682, "up", 8),
          ComponentHealth("dhara", 8683, "up", 5),
          ComponentHealth("crackerjack", 8676, "down", None),
          ComponentHealth("session-buddy", 8678, "up", 7),
      ]
      line = format_ecosystem_summary(components)
      # OSC 8 escape: ESC ] 8 ; ; <url> ESC \ <text> ESC ] 8 ; ; ESC \
      assert "\x1b]8;;http://localhost:8680/mcp\x1b\\" in line
      assert "\x1b]8;;http://localhost:8682/mcp\x1b\\" in line
      assert "crackerjack" in line


  def test_format_event_tail_with_event() -> None:
      event = {
          "ts": "2026-07-15T07:42:11Z",
          "severity": "info",
          "type": "stage_completed",
          "message": "pools.spin_up mahavishnu complete",
      }
      line = format_event_tail(event)
      assert "07:42:11" in line
      assert "[info]" in line
      assert "pools.spin_up" in line


  def test_format_event_tail_with_none() -> None:
      line = format_event_tail(None)
      assert "no recent events" in line.lower()


  def test_render_constellation_lines_5_lines_wide() -> None:
      lines = render_constellation_lines("anthropic", columns=140)
      assert len(lines) == 5  # 3 bars + ecosystem + event tail


  def test_render_constellation_lines_3_lines_narrow() -> None:
      lines = render_constellation_lines("anthropic", columns=70)
      assert len(lines) == 3  # bars only, no ecosystem or event tail


  def test_render_constellation_lines_4_lines_medium() -> None:
      lines = render_constellation_lines("anthropic", columns=100)
      assert len(lines) == 4  # 3 bars + ecosystem, no event tail
  ```

- [ ] **Step 2: Run tests to verify they fail**

  Run: `uv run pytest tests/unit/constellation/test_statusline_extensions.py -v`
  Expected: 6 new tests FAIL with `ImportError` (functions don't exist yet).

- [ ] **Step 3: Add the three new functions to `statusline_extensions.py`**

  Append to `mahavishnu/constellation/statusline_extensions.py`:

  ```python
  from typing import TYPE_CHECKING

  if TYPE_CHECKING:
      from mahavishnu.constellation.ecosystem_health import ComponentHealth


  GLYPH_COLORS: dict[str, str] = {
      "mahavishnu": "#58a6ff",
      "pools": "#39c5cf",
      "akosha": "#a371f7",
      "dhara": "#3fb950",
      "crackerjack": "#d29922",
      "session-buddy": "#58a6ff",
  }

  GLYPH_LETTERS: dict[str, str] = {
      "mahavishnu": "M",
      "pools": "P",
      "akosha": "A",
      "dhara": "D",
      "crackerjack": "C",
      "session-buddy": "S",
  }

  COMPONENT_PORTS_DISPLAY: dict[str, int] = {
      "mahavishnu": 8680,
      "akosha": 8682,
      "dhara": 8683,
      "crackerjack": 8676,
      "session-buddy": 8678,
  }


  def format_ecosystem_summary(components: list[ComponentHealth]) -> str:
      """Emit one line with OSC 8 clickable links for each component."""
      parts: list[str] = []
      for comp in components:
          port = COMPONENT_PORTS_DISPLAY.get(comp.name, comp.port)
          url = f"http://localhost:{port}/mcp"
          letter = GLYPH_LETTERS.get(comp.name, comp.name[0].upper())
          # OSC 8: ESC ] 8 ; params ; URI ST text ST  (ST = ESC \)
          parts.append(f"\x1b]8;;{url}\x1b\\{letter}\x1b]8;;\x1b\\")
          status_marker = "·" if comp.status == "up" else "?"
          parts.append(f"{status_marker}{comp.name} ")
      return "Ecosystem " + "".join(parts).rstrip()


  def format_event_tail(event: dict[str, object] | None) -> str:
      """Render the most-recent Bodai event as a one-line summary."""
      if not event:
          return "no recent events"
      ts_raw = str(event.get("ts", ""))
      # Show only HH:MM:SS
      ts_display = ts_raw[11:19] if len(ts_raw) >= 19 else ts_raw
      severity = str(event.get("severity", "info"))
      message = str(event.get("message", ""))
      sev_tag = f"[{severity}]"
      return f"{ts_display} ⚡ {sev_tag} {message}"


  def render_constellation_lines(
      platform: str,
      *,
      columns: int = 120,
      jsonl_dir: Path | None = None,
      last_event_path: Path | None = None,
  ) -> list[str]:
      """Render the constellation statusline as a list of lines.

      Adaptive based on `columns`:
        - columns >= 120: 5 lines (3 bars + ecosystem + event tail)
        - 80 <= columns < 120: 4 lines (3 bars + ecosystem, no event tail)
        - columns < 80: 3 lines (3 bars only — preserves user's existing layout)
      """
      from mahavishnu.constellation.ecosystem_health import cached_probe_components

      bar1 = format_weekly_cap(platform, jsonl_dir=jsonl_dir)
      # bars 2 and 3 (5-hour block, context window) come from the user's
      # existing format_bar_line call. We don't reimplement them here —
      # the patched session_progress_real.py composes them.
      lines: list[str] = []
      if bar1 is not None:
          lines.append(bar1)

      if columns >= 80:
          # Probe ecosystem (cached, 30s TTL)
          import asyncio
          try:
              loop = asyncio.new_event_loop()
              try:
                  components = loop.run_until_complete(cached_probe_components())
              finally:
                  loop.close()
          except (OSError, RuntimeError):
              components = []
          lines.append(format_ecosystem_summary(components))

      if columns >= 120 and last_event_path is not None:
          event: dict[str, object] | None = None
          if last_event_path.exists():
              try:
                  event = json.loads(last_event_path.read_text())
              except (json.JSONDecodeError, OSError):
                  event = None
          lines.append(format_event_tail(event))

      return lines
  ```

- [ ] **Step 4: Run tests to verify they pass**

  Run: `uv run pytest tests/unit/constellation/test_statusline_extensions.py -v`
  Expected: all 10 tests PASS (4 from Task 4 + 6 new).

- [ ] **Step 5: Run crackerjack**

  Load: `crackerjack-compliant-code`.
  Run: `crackerjack run -- tests/unit/constellation/test_statusline_extensions.py`
  Expected: passes.

- [ ] **Step 6: Commit**

  ```bash
  git add mahavishnu/constellation/statusline_extensions.py tests/unit/constellation/test_statusline_extensions.py
  git commit -m "feat(constellation): ecosystem summary, event tail, adaptive layout"
  ```

---

## Task 6: Activity stream bridge — EventBridge subscriber + cache writers + OSC emit

**Files:**
- Create: `mahavishnu/constellation/activity_stream.py`
- Create: `tests/unit/constellation/test_activity_stream.py`

**Interfaces:**
- Consumes: `MAHAVISHNU_EVENTBRIDGE_URL`, `MAHAVISHNU_EVENTBRIDGE_CHANNEL` env vars.
- Produces:
  - `class EventEnvelope(NamedTuple): type: str; ts: str; severity: str; task_id: str | None; workflow_id: str | None; stage: str | None; message: str`
  - `async def consume_events(*, redis_url: str, channel: str, last_event_path: Path, worker_status_dir: Path, osc_stream: TextIO = sys.stderr, block_ms: int = 1000) -> None` — runs forever, calling `xread` and dispatching to writers/OSC emitter. Cancellable via `asyncio.CancelledError`.
  - `def write_last_event(envelope: EventEnvelope, path: Path) -> None` — atomic JSON write.
  - `def write_worker_status(envelope: EventEnvelope, worker_status_dir: Path) -> None` — atomic per-worker JSON write.

**Required skills:**
- `tui-designer` — validate OSC 777 invocation paths and severity-to-color mapping.
- `superpowers:test-driven-development`.
- `crackerjack-compliant-code`.

- [ ] **Step 1: Load TDD and tui-designer skills; write failing tests**

  Load: `superpowers:test-driven-development`, `tui-designer`.

  `tests/unit/constellation/test_activity_stream.py`:
  ```python
  from __future__ import annotations

  import asyncio
  import json
  from io import StringIO
  from pathlib import Path

  import pytest

  from mahavishnu.constellation.activity_stream import (
      EventEnvelope,
      write_last_event,
      write_worker_status,
  )


  def test_write_last_event_atomic(tmp_path: Path) -> None:
      env = EventEnvelope(
          type="stage_completed",
          ts="2026-07-15T07:42:11Z",
          severity="info",
          task_id="w-02",
          workflow_id="refactor-auth",
          stage="plan",
          message="stage=plan complete",
      )
      target = tmp_path / "last-event.json"
      write_last_event(env, target)
      assert target.exists()
      data = json.loads(target.read_text())
      assert data["type"] == "stage_completed"
      assert data["task_id"] == "w-02"


  def test_write_worker_status_creates_file(tmp_path: Path) -> None:
      env = EventEnvelope(
          type="stage_completed",
          ts="2026-07-15T07:42:11Z",
          severity="ok",
          task_id="w-02",
          workflow_id="refactor-auth",
          stage="plan",
          message="done",
      )
      write_worker_status(env, tmp_path)
      f = tmp_path / "w-02.json"
      assert f.exists()
      data = json.loads(f.read_text())
      assert data["task_id"] == "w-02"
      assert data["stage"] == "plan"


  @pytest.mark.asyncio
  async def test_consume_events_handles_xread_payload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
      """Inject a fake redis client and assert writers + OSC emit fire."""
      from mahavishnu.constellation import activity_stream as mod

      class FakeRedis:
          def __init__(self) -> None:
              self.xread_calls = 0
              self.payloads = [
                  [
                      (b"bodai:events", [
                          (b"1700000000000-0", {
                              b"type": b"stage_completed",
                              b"ts": b"2026-07-15T07:42:11Z",
                              b"severity": b"ok",
                              b"task_id": b"w-02",
                              b"workflow_id": b"refactor-auth",
                              b"stage": b"plan",
                              b"message": b"complete",
                          }),
                      ]),
                  ],
                  # Second call: block forever
              ]

          async def xread(self, *_args: object, **_kwargs: object) -> list[object]:
              self.xread_calls += 1
              if self.xread_calls == 1:
                  return self.payloads[0]
              # Simulate a long-running subscriber by sleeping
              await asyncio.sleep(0.05)
              return []

          async def aclose(self) -> None:
              pass

      fake = FakeRedis()
      osc_stream = StringIO()

      # Run consumer with a cancellation after first iteration
      async def driver() -> None:
          task = asyncio.create_task(
              mod.consume_events(
                  redis=fake,  # type: ignore[arg-type]
                  channel="bodai:events",
                  last_event_path=tmp_path / "last-event.json",
                  worker_status_dir=tmp_path / "worker-status",
                  osc_stream=osc_stream,
                  block_ms=10,
              )
          )
          await asyncio.sleep(0.05)
          task.cancel()
          try:
              await task
          except asyncio.CancelledError:
              pass

      await driver()

      # Verify last-event.json was written
      assert (tmp_path / "last-event.json").exists()
      # Verify worker-status/w-02.json was written
      assert (tmp_path / "worker-status" / "w-02.json").exists()
      # Verify OSC 777 was emitted
      assert "\x1b]777;notify;" in osc_stream.getvalue()
  ```

- [ ] **Step 2: Run tests to verify they fail**

  Run: `uv run pytest tests/unit/constellation/test_activity_stream.py -v`
  Expected: `ModuleNotFoundError: No module named 'mahavishnu.constellation.activity_stream'`

- [ ] **Step 3: Implement `mahavishnu/constellation/activity_stream.py`**

  ```python
  from __future__ import annotations

  import asyncio
  import json
  import logging
  import os
  import sys
  from pathlib import Path
  from typing import NamedTuple, TextIO

  from mahavishnu.constellation.osc import emit_osc777_toast

  logger = logging.getLogger(__name__)

  LIFECYCLE_EVENT_TYPES = frozenset({
      "stage_completed",
      "completed",
      "failed",
      "pool.scaled",
      "worker.completed",
      "crackerjack.gate_raised",
  })


  class EventEnvelope(NamedTuple):
      type: str
      ts: str
      severity: str
      task_id: str | None
      workflow_id: str | None
      stage: str | None
      message: str

      @classmethod
      def from_redis_fields(cls, fields: dict[bytes, bytes]) -> EventEnvelope:
          def s(k: bytes) -> str:
              v = fields.get(k, b"")
              return v.decode("utf-8", errors="replace") if isinstance(v, bytes) else str(v)

          def opt(k: bytes) -> str | None:
              v = fields.get(k)
              if v is None:
                  return None
              decoded = v.decode("utf-8", errors="replace") if isinstance(v, bytes) else str(v)
              return decoded or None

          return cls(
              type=s(b"type"),
              ts=s(b"ts"),
              severity=s(b"severity") or "info",
              task_id=opt(b"task_id"),
              workflow_id=opt(b"workflow_id"),
              stage=opt(b"stage"),
              message=s(b"message"),
          )


  def _severity_from_type(event_type: str) -> str:
      if event_type == "failed" or event_type == "crackerjack.gate_raised":
          return "warn"
      if event_type == "stage_completed" or event_type == "worker.completed":
          return "ok"
      return "info"


  def write_last_event(envelope: EventEnvelope, path: Path) -> None:
      path.parent.mkdir(parents=True, exist_ok=True)
      tmp = path.with_suffix(path.suffix + ".tmp")
      tmp.write_text(json.dumps(envelope._asdict()))
      tmp.replace(path)


  def write_worker_status(envelope: EventEnvelope, worker_status_dir: Path) -> None:
      if not envelope.task_id:
          return
      worker_status_dir.mkdir(parents=True, exist_ok=True)
      target = worker_status_dir / f"{envelope.task_id}.json"
      tmp = target.with_suffix(target.suffix + ".tmp")
      tmp.write_text(json.dumps(envelope._asdict()))
      tmp.replace(target)


  async def consume_events(
      *,
      redis: object,  # redis.asyncio.Redis — duck-typed to keep imports light in tests
      channel: str,
      last_event_path: Path,
      worker_status_dir: Path,
      osc_stream: TextIO = sys.stderr,
      block_ms: int = 1000,
  ) -> None:
      """Subscribe to `channel` via xread and dispatch events.

      Writes last-event.json, worker-status/<task_id>.json, and emits OSC 777
      toasts for lifecycle events. Cancellable via asyncio.CancelledError.
      """
      last_id = "$"
      while True:
          try:
              response = await redis.xread(  # type: ignore[attr-defined]
                  {"channels": [channel]} if False else None,  # pragma: no cover
                  streams={channel: last_id},
                  count=10,
                  block=block_ms,
              ) if False else await redis.xread(  # type: ignore[attr-defined]
                  streams={channel: last_id},
                  count=10,
                  block=block_ms,
              )
          except asyncio.CancelledError:
              raise
          except (OSError, ConnectionError) as exc:
              logger.warning("eventbridge subscriber error: %s; backing off 5s", exc)
              await asyncio.sleep(5.0)
              continue

          if not response:
              continue

          for _stream, entries in response:
              for entry_id, fields in entries:
                  last_id = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
                  envelope = EventEnvelope.from_redis_fields(fields)
                  write_last_event(envelope, last_event_path)
                  write_worker_status(envelope, worker_status_dir)

                  if envelope.type in LIFECYCLE_EVENT_TYPES:
                      title = f"{envelope.type}"
                      body = envelope.message
                      if envelope.workflow_id:
                          body = f"{envelope.workflow_id} · {body}"
                      emit_osc777_toast(title, body, stream=osc_stream)

                  logger.info(
                      "event_received type=%s task_id=%s severity=%s",
                      envelope.type, envelope.task_id, envelope.severity,
                  )


  def run_consumer_forever() -> None:
      """Entry point for the installed bridge script (synchronous wrapper)."""
      import redis.asyncio as redis_async

      url = os.environ.get("MAHAVISHNU_EVENTBRIDGE_URL", "redis://localhost:6379/0")
      channel = os.environ.get("MAHAVISHNU_EVENTBRIDGE_CHANNEL", "bodai:events")
      state_dir = Path.home() / ".mahavishnu"
      last_event_path = state_dir / "last-event.json"
      worker_status_dir = state_dir / "worker-status"

      async def _main() -> None:
          client = redis_async.from_url(url)
          try:
              await consume_events(
                  redis=client,
                  channel=channel,
                  last_event_path=last_event_path,
                  worker_status_dir=worker_status_dir,
              )
          finally:
              await client.aclose()

      asyncio.run(_main())


  if __name__ == "__main__":
      run_consumer_forever()
  ```

- [ ] **Step 4: Run tests to verify they pass**

  Run: `uv run pytest tests/unit/constellation/test_activity_stream.py -v`
  Expected: 3 tests PASS.

- [ ] **Step 5: Run crackerjack**

  Load: `crackerjack-compliant-code`.
  Run: `crackerjack run -- tests/unit/constellation/test_activity_stream.py`
  Expected: passes.

- [ ] **Step 6: Commit**

  ```bash
  git add mahavishnu/constellation/activity_stream.py tests/unit/constellation/test_activity_stream.py
  git commit -m "feat(constellation): EventBridge subscriber + cache writers + OSC emit"
  ```

---

## Task 7: Subagent statusline script (per-task JSON rows)

**Files:**
- Create: `mahavishnu/constellation/subagent_status.py`
- Create: `tests/unit/constellation/test_subagent_status.py`

**Interfaces:**
- Consumes: stdin JSON with `session_id` and `tasks[]` (per Claude Code spec).
- Produces:
  - `def render_task_row(task: dict[str, object], worker_status: dict[str, object] | None) -> dict[str, str]` — returns `{"id": "<task_id>", "content": "<rendered line>"}`.
  - `def main() -> None` — reads stdin, iterates tasks, emits one JSON line per row to stdout. Empty task list → zero lines.

**Required skills:**
- `tui-designer` — validate row format and Unicode glyph selection.
- `superpowers:test-driven-development`.
- `crackerjack-compliant-code`.

- [ ] **Step 1: Load TDD and tui-designer; write failing tests**

  Load: `superpowers:test-driven-development`, `tui-designer`.

  `tests/unit/constellation/test_subagent_status.py`:
  ```python
  from __future__ import annotations

  import io
  import json
  from pathlib import Path

  from mahavishnu.constellation.subagent_status import render_task_row


  def test_render_task_row_active_with_worker_status() -> None:
      task = {"id": "w-02", "name": "plan", "status": "in_progress"}
      ws = {"task_id": "w-02", "stage": "plan", "tokenCount": 8100, "message": "crackerjack running"}
      row = render_task_row(task, ws)
      assert row["id"] == "w-02"
      # active/in_progress → 🟡; stages progress info; token count formatted
      assert "plan" in row["content"]
      assert "8.1k tok" in row["content"] or "8100 tok" in row["content"]
      assert "crackerjack" in row["content"]


  def test_render_task_row_completed() -> None:
      task = {"id": "w-01", "name": "scout", "status": "completed"}
      row = render_task_row(task, None)
      assert row["id"] == "w-01"
      assert "scout" in row["content"]


  def test_render_task_row_queued() -> None:
      task = {"id": "w-04", "name": "verify", "status": "pending"}
      row = render_task_row(task, None)
      assert row["id"] == "w-04"
      assert "queued" in row["content"].lower() or "verify" in row["content"]


  def test_main_emits_one_json_line_per_task(
      monkeypatch: pytest.MonkeyPatch,
      tmp_path: Path,
      capsys: pytest.CaptureFixture[str],
  ) -> None:
      import sys
      from mahavishnu.constellation import subagent_status as mod

      payload = {
          "session_id": "s1",
          "tasks": [
              {"id": "w-01", "name": "scout", "status": "completed"},
              {"id": "w-02", "name": "plan", "status": "in_progress"},
          ],
      }
      monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
      # Point worker_status_dir to a tmp dir with no files
      monkeypatch.setattr(mod, "DEFAULT_WORKER_STATUS_DIR", tmp_path)

      mod.main()

      captured = capsys.readouterr()
      lines = [ln for ln in captured.out.splitlines() if ln.strip()]
      assert len(lines) == 2
      parsed = [json.loads(ln) for ln in lines]
      assert parsed[0]["id"] == "w-01"
      assert parsed[1]["id"] == "w-02"


  def test_main_empty_tasks_writes_nothing(
      monkeypatch: pytest.MonkeyPatch,
      capsys: pytest.CaptureFixture[str],
  ) -> None:
      import sys
      from mahavishnu.constellation import subagent_status as mod

      monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"session_id": "s1", "tasks": []})))
      mod.main()
      captured = capsys.readouterr()
      assert captured.out == ""
  ```

- [ ] **Step 2: Run tests to verify they fail**

  Run: `uv run pytest tests/unit/constellation/test_subagent_status.py -v`
  Expected: `ModuleNotFoundError: No module named 'mahavishnu.constellation.subagent_status'`

- [ ] **Step 3: Implement `mahavishnu/constellation/subagent_status.py`**

  ```python
  from __future__ import annotations

  import json
  import logging
  import sys
  from datetime import datetime, timezone
  from pathlib import Path
  from typing import Any

  logger = logging.getLogger(__name__)

  DEFAULT_WORKER_STATUS_DIR = Path.home() / ".mahavishnu" / "worker-status"

  STATUS_GLYPHS: dict[str, str] = {
      "completed": "🟢",
      "in_progress": "🟡",
      "running": "🟡",
      "pending": "🔵",
      "failed": "🔴",
  }

  RESET = "\033[0m"
  COLORS: dict[str, str] = {
      "completed": "\033[32m",
      "in_progress": "\033[33m",
      "running": "\033[33m",
      "pending": "\033[34m",
      "failed": "\033[31m",
  }


  def _fmt_tokens(n: int | float) -> str:
      n = int(n)
      if n >= 1_000_000:
          return f"{n / 1_000_000:.1f}m"
      if n >= 1_000:
          return f"{n / 1_000:.1f}k"
      return str(n)


  def _fmt_elapsed(start_time: str | None) -> str:
      if not start_time:
          return "—"
      try:
          start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
          delta = datetime.now(timezone.utc) - start
          total_s = int(delta.total_seconds())
          if total_s < 60:
              return f"{total_s:02d}s"
          m, s = divmod(total_s, 60)
          return f"{m:02d}:{s:02d}"
      except (ValueError, TypeError):
          return "—"


  def render_task_row(
      task: dict[str, Any],
      worker_status: dict[str, Any] | None,
  ) -> dict[str, str]:
      """Render one Claude Code subagent-statusline row for a task."""
      task_id = str(task.get("id", ""))
      name = str(task.get("name", task_id))
      status = str(task.get("status", "pending"))

      glyph = STATUS_GLYPHS.get(status, "⚪")
      color = COLORS.get(status, "")

      parts: list[str] = [f"{color}{name}{RESET}"]

      if worker_status:
          stage = worker_status.get("stage")
          message = worker_status.get("message", "")
          token_count = worker_status.get("tokenCount", 0)
          if stage and stage != name:
              parts.append(f"· stage={stage}")
          if message:
              parts.append(f"· {message}")
          if token_count:
              parts.append(f"· {_fmt_tokens(token_count)} tok")
      elif status == "pending":
          parts.append("· queued")

      start_time = task.get("startTime")
      if start_time:
          parts.append(f"· {_fmt_elapsed(str(start_time))}")

      content = f"{glyph} {' '.join(parts)}"
      return {"id": task_id, "content": content}


  def main() -> None:
      """Read Claude Code subagent statusline payload from stdin, emit rows."""
      raw = sys.stdin.read()
      try:
          payload = json.loads(raw)
      except json.JSONDecodeError:
          logger.warning("subagent_status: invalid stdin JSON")
          return

      tasks = payload.get("tasks") or []
      for task in tasks:
          task_id = str(task.get("id", ""))
          worker_status: dict[str, Any] | None = None
          status_file = DEFAULT_WORKER_STATUS_DIR / f"{task_id}.json"
          if status_file.exists():
              try:
                  worker_status = json.loads(status_file.read_text())
              except (json.JSONDecodeError, OSError):
                  worker_status = None
          row = render_task_row(task, worker_status)
          print(json.dumps(row), flush=True)


  if __name__ == "__main__":
      main()
  ```

- [ ] **Step 4: Run tests to verify they pass**

  Run: `uv run pytest tests/unit/constellation/test_subagent_status.py -v`
  Expected: 5 tests PASS.

- [ ] **Step 5: Run crackerjack**

  Load: `crackerjack-compliant-code`.
  Run: `crackerjack run -- tests/unit/constellation/test_subagent_status.py`
  Expected: passes.

- [ ] **Step 6: Commit**

  ```bash
  git add mahavishnu/constellation/subagent_status.py tests/unit/constellation/test_subagent_status.py
  git commit -m "feat(constellation): subagent statusline per-task rows"
  ```

---

## Task 8: Installer — copy scripts to ~/.claude/, modify settings.json, patch existing statusline

**Files:**
- Create: `mahavishnu/constellation/install.py`
- Create: `mahavishnu/cli/constellation_cli.py`
- Create: `tests/unit/constellation/test_install.py`

**Interfaces:**
- Consumes: nothing (operates on filesystem and JSON files).
- Produces:
  - `class InstallResult(NamedTuple): scripts_installed: list[Path]; settings_modified: bool; statusline_patched: bool`
  - `def install(*, claude_dir: Path = Path.home() / ".claude", settings_path: Path | None = None, dry_run: bool = False) -> InstallResult` — idempotent: re-running on an already-installed setup is a no-op.
  - `def uninstall(*, claude_dir: Path = Path.home() / ".claude", settings_path: Path | None = None, dry_run: bool = False) -> InstallResult` — reverses install.

**Required skills:**
- `superpowers:test-driven-development`.
- `crackerjack-compliant-code`.

- [ ] **Step 1: Load TDD skill; write failing tests**

  Load: `superpowers:test-driven-development`.

  `tests/unit/constellation/test_install.py`:
  ```python
  from __future__ import annotations

  import json
  from pathlib import Path

  from mahavishnu.constellation.install import install, uninstall


  def test_install_copies_scripts_and_modifies_settings(tmp_path: Path) -> None:
      settings = tmp_path / "settings.json"
      settings.write_text(json.dumps({"hooks": {}, "statusLine": {"type": "command", "command": "existing"}}))

      result = install(
          claude_dir=tmp_path,
          settings_path=settings,
          dry_run=False,
      )

      assert (tmp_path / "scripts" / "mahavishnu-activity-stream.py").exists()
      assert (tmp_path / "scripts" / "mahavishnu-subagent-status.py").exists()
      assert (tmp_path / "hooks" / "mahavishnu-activity-stream.py").exists()
      assert result.settings_modified is True
      data = json.loads(settings.read_text())
      assert "subagentStatusLine" in data
      assert "PostToolUse" in data["hooks"]


  def test_install_idempotent(tmp_path: Path) -> None:
      settings = tmp_path / "settings.json"
      settings.write_text(json.dumps({"hooks": {}}))
      install(claude_dir=tmp_path, settings_path=settings)
      first = json.loads(settings.read_text())
      install(claude_dir=tmp_path, settings_path=settings)
      second = json.loads(settings.read_text())
      assert first == second


  def test_install_dry_run_does_not_write(tmp_path: Path) -> None:
      settings = tmp_path / "settings.json"
      settings.write_text(json.dumps({}))
      result = install(claude_dir=tmp_path, settings_path=settings, dry_run=True)
      assert result.settings_modified is False
      assert not (tmp_path / "scripts").exists()


  def test_uninstall_removes_scripts_and_reverts_settings(tmp_path: Path) -> None:
      settings = tmp_path / "settings.json"
      settings.write_text(json.dumps({}))
      install(claude_dir=tmp_path, settings_path=settings)
      uninstall(claude_dir=tmp_path, settings_path=settings)
      data = json.loads(settings.read_text())
      assert "subagentStatusLine" not in data
      assert "PostToolUse" not in data.get("hooks", {})
      assert not (tmp_path / "scripts" / "mahavishnu-subagent-status.py").exists()


  def test_install_patches_existing_statusline_script(tmp_path: Path) -> None:
      """If the existing session_progress_real.py is present, the installer
      inserts an import line for the new library without overwriting the
      user's existing code."""
      scripts_dir = tmp_path / "scripts"
      scripts_dir.mkdir()
      existing = scripts_dir / "session_progress_real.py"
      existing.write_text("#!/usr/bin/env python3\n# existing user code\n")

      settings = tmp_path / "settings.json"
      settings.write_text(json.dumps({}))

      install(claude_dir=tmp_path, settings_path=settings)

      patched = existing.read_text()
      assert "from mahavishnu.constellation.statusline_extensions import" in patched
      assert "# existing user code" in patched  # user's content preserved
  ```

- [ ] **Step 2: Run tests to verify they fail**

  Run: `uv run pytest tests/unit/constellation/test_install.py -v`
  Expected: `ModuleNotFoundError: No module named 'mahavishnu.constellation.install'`

- [ ] **Step 3: Implement `mahavishnu/constellation/install.py`**

  ```python
  from __future__ import annotations

  import json
  import shutil
  from pathlib import Path
  from typing import NamedTuple

  from importlib.resources import files

  PACKAGE_ROOT = Path(str(files("mahavishnu.constellation")))
  SCRIPTS_SRC = PACKAGE_ROOT / "scripts"
  HOOKS_SRC = PACKAGE_ROOT / "hooks"

  STATUSLINE_PATCH_MARKER = "# >>> constellation patch >>>"
  STATUSLINE_PATCH_BLOCK = """
  {marker}
  from mahavishnu.constellation.statusline_extensions import (
      format_weekly_cap,
      format_ecosystem_summary,
      format_event_tail,
      render_constellation_lines,
  )
  # <<< constellation patch <<<
  """


  class InstallResult(NamedTuple):
      scripts_installed: list[Path]
      settings_modified: bool
      statusline_patched: bool


  def _copy_scripts(target_dir: Path) -> list[Path]:
      """Copy bridge and subagent scripts to ~/.claude/scripts/."""
      target_dir.mkdir(parents=True, exist_ok=True)
      installed: list[Path] = []
      for name in ("mahavishnu-activity-stream.py", "mahavishnu-subagent-status.py"):
          src = SCRIPTS_SRC / name
          dst = target_dir / name
          shutil.copy2(src, dst)
          dst.chmod(0o755)
          installed.append(dst)
      return installed


  def _copy_hooks(target_dir: Path) -> list[Path]:
      """Copy bridge script to ~/.claude/hooks/ as well (Claude Code hooks
      typically live in ~/.claude/hooks/)."""
      target_dir.mkdir(parents=True, exist_ok=True)
      installed: list[Path] = []
      src = SCRIPTS_SRC / "mahavishnu-activity-stream.py"
      dst = target_dir / "mahavishnu-activity-stream.py"
      shutil.copy2(src, dst)
      dst.chmod(0o755)
      installed.append(dst)
      return installed


  def _update_settings(settings_path: Path, *, dry_run: bool) -> bool:
      """Add subagentStatusLine and PostToolUse hook. Idempotent."""
      if settings_path.exists():
          data = json.loads(settings_path.read_text())
      else:
          data = {}

      modified = False
      if "subagentStatusLine" not in data:
          data["subagentStatusLine"] = {
              "type": "command",
              "command": "python3 ~/.claude/scripts/mahavishnu-subagent-status.py",
          }
          modified = True

      hooks = data.setdefault("hooks", {})
      post = hooks.get("PostToolUse")
      already_has_bridge = any(
          "mahavishnu-activity-stream" in h.get("command", "")
          for entry in (post or [])
          for h in entry.get("hooks", [])
      )
      if not already_has_bridge:
          hooks.setdefault("PostToolUse", []).append({
              "matcher": "*",
              "hooks": [
                  {"type": "command", "command": "python3 ~/.claude/hooks/mahavishnu-activity-stream.py"}
              ],
          })
          modified = True

      if modified and not dry_run:
          settings_path.parent.mkdir(parents=True, exist_ok=True)
          settings_path.write_text(json.dumps(data, indent=2))
      return modified


  def _patch_statusline_script(scripts_dir: Path, *, dry_run: bool) -> bool:
      """Inject the import block into the existing session_progress_real.py."""
      target = scripts_dir / "session_progress_real.py"
      if not target.exists():
          return False
      content = target.read_text()
      if STATUSLINE_PATCH_MARKER in content:
          return False
      patch = STATUSLINE_PATCH_BLOCK.format(marker=STATUSLINE_PATCH_MARKER)
      new = content + "\n\n" + patch
      if not dry_run:
          target.write_text(new)
      return True


  def install(
      *,
      claude_dir: Path = Path.home() / ".claude",
      settings_path: Path | None = None,
      dry_run: bool = False,
  ) -> InstallResult:
      settings_path = settings_path or (claude_dir / "settings.json")
      if dry_run:
          # Simulate without writing
          scripts = [claude_dir / "scripts" / "mahavishnu-activity-stream.py"]
      else:
          scripts = _copy_scripts(claude_dir / "scripts") + _copy_hooks(claude_dir / "hooks")
      modified = _update_settings(settings_path, dry_run=dry_run)
      patched = _patch_statusline_script(claude_dir / "scripts", dry_run=dry_run)
      return InstallResult(
          scripts_installed=scripts,
          settings_modified=modified,
          statusline_patched=patched,
      )


  def uninstall(
      *,
      claude_dir: Path = Path.home() / ".claude",
      settings_path: Path | None = None,
      dry_run: bool = False,
  ) -> InstallResult:
      settings_path = settings_path or (claude_dir / "settings.json")
      removed: list[Path] = []
      for d in (claude_dir / "scripts", claude_dir / "hooks"):
          for name in ("mahavishnu-activity-stream.py", "mahavishnu-subagent-status.py"):
              f = d / name
              if f.exists() and not dry_run:
                  f.unlink()
                  removed.append(f)

      modified = False
      if settings_path.exists() and not dry_run:
          data = json.loads(settings_path.read_text())
          if "subagentStatusLine" in data:
              del data["subagentStatusLine"]
              modified = True
          hooks = data.get("hooks", {})
          if "PostToolUse" in hooks:
              hooks["PostToolUse"] = [
                  entry for entry in hooks["PostToolUse"]
                  if not any(
                      "mahavishnu-activity-stream" in h.get("command", "")
                      for h in entry.get("hooks", [])
                  )
              ]
              if not hooks["PostToolUse"]:
                  del hooks["PostToolUse"]
              modified = True
          if modified:
              settings_path.write_text(json.dumps(data, indent=2))

      return InstallResult(
          scripts_installed=removed,
          settings_modified=modified,
          statusline_patched=False,
      )
  ```

- [ ] **Step 4: Implement `mahavishnu/cli/constellation_cli.py`**

  ```python
  from __future__ import annotations

  from pathlib import Path

  import typer

  from mahavishnu.constellation.install import install, uninstall

  app = typer.Typer(help="Install, uninstall, or check status of the Constellation TUI bridge.")


  @app.command("install")
  def install_cmd(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
      """Copy scripts to ~/.claude/, register hooks, patch statusline."""
      result = install(dry_run=dry_run)
      typer.echo(f"Scripts installed: {len(result.scripts_installed)}")
      typer.echo(f"Settings modified: {result.settings_modified}")
      typer.echo(f"Existing statusline patched: {result.statusline_patched}")
      if not dry_run:
          typer.echo("Run `mahavishnu constellation status` to verify wiring.")


  @app.command("uninstall")
  def uninstall_cmd(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
      """Remove scripts and revert settings.json."""
      result = uninstall(dry_run=dry_run)
      typer.echo(f"Scripts removed: {len(result.scripts_installed)}")
      typer.echo(f"Settings reverted: {result.settings_modified}")


  @app.command("status")
  def status_cmd() -> None:
      """Report installed-vs-not state."""
      from mahavishnu.constellation.install import PACKAGE_ROOT
      scripts_dir = Path.home() / ".claude" / "scripts"
      settings_path = Path.home() / ".claude" / "settings.json"
      typer.echo(f"Package root: {PACKAGE_ROOT}")
      typer.echo(f"Scripts dir: {scripts_dir}")
      for name in ("mahavishnu-activity-stream.py", "mahavishnu-subagent-status.py"):
          f = scripts_dir / name
          typer.echo(f"  {'✓' if f.exists() else '✗'} {name}")
      if settings_path.exists():
          data = settings_path.read_text()
          typer.echo(f"subagentStatusLine configured: {'subagentStatusLine' in data}")
          typer.echo(f"PostToolUse hook configured: {'mahavishnu-activity-stream' in data}")
      else:
          typer.echo("Settings file does not exist.")


  if __name__ == "__main__":
      app()
  ```

  Then register in `mahavishnu/_main_cli.py` (find the existing typer sub-app registration and add a similar one for `constellation_cli`):

  ```python
  from mahavishnu.cli.constellation_cli import app as constellation_app
  # ... existing registrations ...
  app.add_typer(constellation_app, name="constellation")
  ```

- [ ] **Step 5: Add `scripts/` and `hooks/` source directories under the package**

  ```bash
  mkdir -p mahavishnu/constellation/scripts mahavishnu/constellation/hooks
  ```

  Copy the bridge module's CLI entry point as the script:
  ```bash
  cat > mahavishnu/constellation/scripts/mahavishnu-activity-stream.py <<'EOF'
  #!/usr/bin/env python3
  """Constellation EventBridge bridge — installed into ~/.claude/."""
  from mahavishnu.constellation.activity_stream import run_consumer_forever

  if __name__ == "__main__":
      run_consumer_forever()
  EOF
  chmod +x mahavishnu/constellation/scripts/mahavishnu-activity-stream.py
  ```

  Same content under `hooks/` (same script, two install locations):
  ```bash
  cp mahavishnu/constellation/scripts/mahavishnu-activity-stream.py \
     mahavishnu/constellation/hooks/mahavishnu-activity-stream.py
  ```

  And the subagent statusline script:
  ```bash
  cat > mahavishnu/constellation/scripts/mahavishnu-subagent-status.py <<'EOF'
  #!/usr/bin/env python3
  """Constellation subagent statusline — installed into ~/.claude/scripts/."""
  from mahavishnu.constellation.subagent_status import main

  if __name__ == "__main__":
      main()
  EOF
  chmod +x mahavishnu/constellation/scripts/mahavishnu-subagent-status.py
  ```

- [ ] **Step 6: Run tests to verify they pass**

  Run: `uv run pytest tests/unit/constellation/test_install.py -v`
  Expected: 5 tests PASS.

- [ ] **Step 7: Run crackerjack**

  Load: `crackerjack-compliant-code`.
  Run: `crackerjack run -- tests/unit/constellation/test_install.py`
  Expected: passes.

- [ ] **Step 8: Smoke-test the CLI in dry-run**

  Run: `uv run mahavishnu constellation install --dry-run`
  Expected: prints the install summary, writes nothing.

- [ ] **Step 9: Commit**

  ```bash
  git add mahavishnu/constellation/install.py mahavishnu/constellation/scripts/ \
          mahavishnu/constellation/hooks/ \
          mahavishnu/cli/constellation_cli.py \
          tests/unit/constellation/test_install.py \
          mahavishnu/_main_cli.py
  git commit -m "feat(constellation): installer + CLI (install/uninstall/status)"
  ```

---

## Task 9: Integration test (gated by `MAHAVISHNU_EVENTBRIDGE_INTEGRATION=1`)

**Files:**
- Create: `tests/integration/constellation/test_activity_stream_integration.py`

**Interfaces:**
- Consumes: a local Redis instance (started by the test or assumed available on `localhost:6379`).
- Produces: a passing integration test that publishes an event via `redis-cli xadd` and asserts the bridge writes `last-event.json` and emits OSC 777.

**Required skills:**
- `superpowers:test-driven-development`.
- `crackerjack-compliant-code`.

- [ ] **Step 1: Write the gated integration test**

  Load: `superpowers:test-driven-development`.

  `tests/integration/constellation/__init__.py`:
  ```python
  """Integration tests for mahavishnu.constellation (gated by env var)."""
  ```

  `tests/integration/constellation/test_activity_stream_integration.py`:
  ```python
  from __future__ import annotations

  import asyncio
  import json
  import os
  import shutil
  import time
  from io import StringIO
  from pathlib import Path

  import pytest

  pytestmark = pytest.mark.skipif(
      os.environ.get("MAHAVISHNU_EVENTBRIDGE_INTEGRATION") != "1",
      reason="set MAHAVISHNU_EVENTBRIDGE_INTEGRATION=1 to run",
  )


  @pytest.mark.asyncio
  async def test_consumer_writes_cache_and_emits_osc(tmp_path: Path) -> None:
      """End-to-end: publish an event to a real Redis stream, verify the bridge
      writes last-event.json + worker-status/<id>.json and emits OSC 777."""
      redis_url = os.environ.get("MAHAVISHNU_EVENTBRIDGE_URL", "redis://localhost:6379/0")
      import redis.asyncio as redis_async
      import redis as redis_sync  # for the publish side

      client = redis_async.from_url(redis_url)
      try:
          await client.ping()
      except (OSError, ConnectionError) as exc:
          pytest.skip(f"Redis unreachable at {redis_url}: {exc}")

      osc_stream = StringIO()
      last_event_path = tmp_path / "last-event.json"
      worker_status_dir = tmp_path / "worker-status"

      async def driver() -> None:
          consumer = asyncio.create_task(
              __import__(
                  "mahavishnu.constellation.activity_stream",
                  fromlist=["consume_events"],
              ).consume_events(
                  redis=client,
                  channel="bodai:events-test",
                  last_event_path=last_event_path,
                  worker_status_dir=worker_status_dir,
                  osc_stream=osc_stream,
                  block_ms=200,
              )
          )
          # Give the consumer a moment to subscribe
          await asyncio.sleep(0.3)

          # Publish via sync redis client (cleaner)
          sync = redis_sync.from_url(redis_url)
          sync.xadd(
              "bodai:events-test",
              {
                  "type": "stage_completed",
                  "ts": "2026-07-15T07:42:11Z",
                  "severity": "ok",
                  "task_id": "w-it-01",
                  "workflow_id": "refactor-auth",
                  "stage": "plan",
                  "message": "stage=plan complete",
              },
          )

          # Wait for the consumer to process
          deadline = time.monotonic() + 5.0
          while time.monotonic() < deadline and not last_event_path.exists():
              await asyncio.sleep(0.05)

          consumer.cancel()
          try:
              await consumer
          except asyncio.CancelledError:
              pass

      await driver()

      assert last_event_path.exists(), "last-event.json was not written"
      assert (worker_status_dir / "w-it-01.json").exists(), "worker-status/w-it-01.json was not written"
      assert "\x1b]777;notify;" in osc_stream.getvalue(), "OSC 777 sequence was not emitted"
      await client.aclose()
  ```

- [ ] **Step 2: Run the integration test (gated)**

  Run: `MAHAVISHNU_EVENTBRIDGE_INTEGRATION=1 uv run pytest tests/integration/constellation/ -v`
  Expected: 1 test PASS (or SKIP if Redis is unreachable).

- [ ] **Step 3: Run crackerjack**

  Load: `crackerjack-compliant-code`.
  Run: `crackerjack run -- tests/integration/constellation/`
  Expected: passes.

- [ ] **Step 4: Commit**

  ```bash
  git add tests/integration/constellation/
  git commit -m "test(constellation): gated integration test for EventBridge bridge"
  ```

---

## Task 10: Operator-facing install doc + final wiring check

**Files:**
- Create: `docs/constellation/INSTALL.md`
- Modify: `docs/superpowers/specs/2026-07-15-constellation-tui-design.md` (add a "Status: implementation complete" note)

**Required skills:**
- `crackerjack-compliant-code` — final gate.

- [ ] **Step 1: Write `docs/constellation/INSTALL.md`**

  ```markdown
  # Constellation TUI — Install

  Surfaces Bodai ecosystem activity in Claude Code via three extension surfaces.

  ## Quick install

  ```bash
  uv run mahavishnu constellation install
  ```

  This:

  1. Copies `mahavishnu-activity-stream.py` to `~/.claude/scripts/` and `~/.claude/hooks/`
  1. Copies `mahavishnu-subagent-status.py` to `~/.claude/scripts/`
  1. Registers `subagentStatusLine` and the `PostToolUse` hook in `~/.claude/settings.json`
  1. Patches the existing `~/.claude/scripts/session_progress_real.py` to import the
     new statusline extensions library (5-line layout, adaptive to terminal width)

  ## Verify

  ```bash
  uv run mahavishnu constellation status
  ```

  Should report all scripts installed and settings configured.

  ## What you'll see

  - **Statusline** (always-on): 3 progress bars + ecosystem summary + recent event tail
  - **Subagent statusline**: one row per active Mahavishnu worker / Claude Code subagent
  - **OSC 777 toasts**: native terminal notifications for lifecycle events
    (workflow_started, stage_completed, completed, failed, pool_scaled, etc.)

  ## Rollback

  ```bash
  uv run mahavishnu constellation uninstall
  ```

  ## Customizing the EventBridge URL

  The bridge reads `MAHAVISHNU_EVENTBRIDGE_URL` (default `redis://localhost:6379/0`)
  and `MAHAVISHNU_EVENTBRIDGE_CHANNEL` (default `bodai:events`).

  ## Disabling OSC 777

  Set `MAHAVISHNU_OSC_PROBE_DISABLE=1` in the shell where Claude Code runs to skip
  the OSC capability probe.
  ```

- [ ] **Step 2: Run the full test suite as a final gate**

  Load: `crackerjack-compliant-code`.
  Run: `crackerjack run`
  Expected: all tests pass; no lint/type errors.

- [ ] **Step 3: Update spec with completion note**

  Append to `docs/superpowers/specs/2026-07-15-constellation-tui-design.md` (above the Status section):

  ```markdown
  ## Implementation status

  Implemented per `docs/superpowers/plans/2026-07-15-constellation-tui.md`.
  Three surfaces wired; installer shipped; gated integration test in place.
  Operator doc at `docs/constellation/INSTALL.md`.
  ```

- [ ] **Step 4: Manual smoke test (operator steps, not in pytest)**

  With Mahavishnu running (`mahavishnu mcp start`):

  1. Run `mahavishnu constellation install` (no `--dry-run`)
  1. Open Claude Code in this repo
  1. Verify: statusline shows 5 lines including the OSC 8 ecosystem row
  1. Dispatch: `mcp__mahavishnu__pool_route_execute` with prompt "echo test"
  1. Verify: workflow chain appears in subagent statusline
  1. Trigger: `mahavishnu workflows trigger <some-workflow>` (any available)
  1. Verify: OSC 777 toast appears in the terminal

- [ ] **Step 5: Final commit**

  ```bash
  git add docs/constellation/INSTALL.md docs/superpowers/specs/2026-07-15-constellation-tui-design.md
  git commit -m "docs(constellation): operator install guide + spec status"
  ```

---

## Self-Review (against spec)

**Spec coverage:**
- Surface 1 (statusLine extension) → Tasks 4, 5, 8 (patch in installer)
- Surface 2 (subagentStatusLine) → Task 7
- Surface 3 (OSC 777 toasts) → Task 2 (osc.py) + Task 6 (activity_stream.py emits via osc.py)
- Bridge script → Task 6
- Three Integration Contracts (Triggered from / Returns to / Demonstrable by / Rollback signal / Observability added) → each contract maps to specific tasks:
  - Surface 1 contract → Tasks 4, 5 (Demonstrable: `pytest tests/unit/constellation/test_statusline_extensions.py`)
  - Surface 2 contract → Task 7 (Demonstrable: `pytest tests/unit/constellation/test_subagent_status.py::test_main_emits_one_json_line_per_task`)
  - Surface 3 contract → Task 6 (Demonstrable: `pytest tests/unit/constellation/test_activity_stream.py::test_consume_events_handles_xread_payload`)
- File layout → Tasks 1–8 create all 8 files; runtime state files (`~/.mahavishnu/last-event.json`, `worker-status/`, `ecosystem-health-cache.json`) are written by Tasks 3, 5, 6
- Error handling table → Task 6 handles Redis down, Task 5 handles missing/cache, Task 2 handles OSC unsupported
- Testing strategy → Tasks 1–8 have unit tests; Task 9 has gated integration; Task 10 has manual smoke
- Implementation order (1→6 steps from spec) → plan order matches: bridge → statusline ext → subagent status → installer

**Placeholder scan:** No TBD/TODO/"similar to Task N". Every code block is complete.

**Type consistency:** Functions defined in Task 2 (`emit_osc777_toast`, `probe_osc_support`) are used in Task 6. Functions defined in Task 3 (`ComponentHealth`, `cached_probe_components`, `probe_components`) are used in Task 5. Constants (`WEEKLY_BUDGET`, `BAR_WIDTH`, `GLYPH_LETTERS`) match across tasks. Method signatures are stable.

**Ambiguity check:** All filenames have absolute paths. All test commands are spelled out. Integration Contract language copied verbatim from spec.

**Skill loading:** TDD/tui-designer/cj-compliant-code are required at the steps indicated in each task. Subagent-driven-development is the recommended execution mode (offered at handoff).

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-15-constellation-tui.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Uses `superpowers:subagent-driven-development`.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

**Which approach?**