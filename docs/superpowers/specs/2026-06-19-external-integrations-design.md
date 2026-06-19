# External Integrations Design: crow-cli, OpenHands, Toad TUI

**Date:** 2026-06-19
**Status:** Approved — ready for implementation planning
**Tracks:** 3 parallel, independent

---

## Context

Mahavishnu's terminal worker stack (`GenericShellWorker`) is fully implemented but produces
fake output because `MockTerminalAdapter` is the default. OpenHands provides autonomous
coding capability Mahavishnu cannot replicate internally. Toad's Textual/Rich packages
improve CLI readability in monitoring and quality workflows. This spec covers all three.

---

## 1. Overall Architecture

Three independent parallel tracks. No shared files, no ordering dependencies between tracks.

```
Track 1 — Terminal Gap     Track 2 — OpenHands          Track 3 — Toad TUI
──────────────────────     ────────────────────          ───────────────────
CrowTerminalAdapter        OpenHandsWorker               mahavishnu/tui/
CrowWorker                 OpenHandsClient (httpx)       monitor watch (Textual)
A2AWorker                  openhands_tools.py (MCP)      quality check (Rich)
.mcp.json: crow-mcp        settings: openhands block     TUI_AVAILABLE fallback
preferred_adapter: crow    MHV-308, MHV-309 errors       (always degrades cleanly)
```

**Deferred (not in this spec):** Toad ACP agent integration (requires Python 3.14+),
BrowserWorker, full A2A discovery mesh.

---

## 2. Track 1 — Terminal Gap (crow-cli / ACP)

### 2.1 Problem

`GenericShellWorker` is complete. `TerminalManager` selects adapters at startup via
`preferred_adapter`. The default is `"mock"` (set in `mahavishnu/terminal/config.py:49`
and mirrored in `settings/mahavishnu.yaml`). All terminal workers produce fake output.

### 2.2 CrowTerminalAdapter

**File:** `mahavishnu/terminal/adapters/crow.py`

Implements all five methods of the `TerminalAdapter` protocol defined in
`mahavishnu/terminal/adapters/base.py`:

```python
async def launch_session(self, command: str, ...) -> str
async def send_command(self, session_id: str, command: str) -> None
async def capture_output(self, session_id: str, lines: int) -> str
async def close_session(self, session_id: str) -> None
async def list_sessions(self) -> list[dict]
```

Calls crow-mcp's `terminal` tool via an MCP client (`mcp.call_tool("terminal", {...})`),
following the exact pattern of `mahavishnu/terminal/adapters/mcpretentious.py`. Session
state (PTY persistence) is managed server-side by crow-mcp.

### 2.3 crow-mcp as HTTP MCP Server

crow-mcp is FastMCP-based. Rather than using its default stdio transport, it runs as an
HTTP MCP server on port **8675** for Bodai ecosystem alignment.

**`.mcp.json` entry:**
```json
"crow-mcp": {
  "type": "http",
  "url": "http://localhost:8675/mcp"
}
```

**Health check entry** in `settings/mahavishnu.yaml`:
```yaml
health:
  dependencies:
    crow_mcp:
      host: "localhost"
      port: 8675
      required: false
      timeout_seconds: 10
      use_tls: false
```

**Fail-fast startup probe:** When `preferred_adapter == "crow"`, `TerminalManager` probes
crow-mcp before accepting tasks. Probe failure raises `MHV-307` and falls back to
`MockTerminalAdapter` with a loud WARNING log — never silently.

**CI override:** `MAHAVISHNU_TERMINAL__ADAPTER_PREFERENCE=mock` (Oneiric env-var layering)
keeps CI green without a live crow-mcp server.

### 2.4 Config Flip

`settings/mahavishnu.yaml`, under `terminal:`:
```yaml
terminal:
  adapter_preference: "crow"   # was "auto"
```

### 2.5 CrowWorker

**File:** `mahavishnu/workers/crow.py`

`CrowWorker(BaseWorker)` for tasks that target crow-cli's ACP agent directly (AI ReAct
reasoning over the terminal, not just PTY execution). Communicates via ACP session
lifecycle: `initialize → new_session → prompt → (poll) → result`.

`CrowWorker` is a sibling of `GenericShellWorker`, not a replacement. `GenericShellWorker`
uses the `CrowTerminalAdapter` for PTY I/O. `CrowWorker` speaks ACP to crow-cli's
reasoning layer for tasks that need autonomous multi-step execution.

### 2.6 A2AWorker

**File:** `mahavishnu/workers/a2a.py`

`A2AWorker(BaseWorker)` for communicating with A2A-capable agents (Agent Card at
`/.well-known/agent-card.json`, v1.0 March 2026, `a2a-sdk>=0.3.25`). Routes tasks to
external agents exposing the A2A protocol. Scoped to a single-hop request/response in
this wave — discovery mesh deferred.

**Optional dep group:**
```toml
[dependency-groups]
a2a = ["a2a-sdk>=0.3.25"]
```

### 2.7 Worker Registry Additions

New entries in `mahavishnu/workers/registry.py`:

| `worker_type` | Category | Description |
|---------------|----------|-------------|
| `terminal-crow` | `AI_ASSISTANT` | crow-cli ACP agent (ReAct, autonomous) |
| `terminal-aider` | `AI_ASSISTANT` | Aider pair-programming assistant |
| `terminal-goose` | `AI_ASSISTANT` | Block Goose autonomous agent |
| `terminal-gemini` | `AI_ASSISTANT` | Gemini CLI assistant |
| `terminal-amp` | `AI_ASSISTANT` | Amp coding assistant |

### 2.8 Deletions

- **`mahavishnu/workers/terminal.py`** (`TerminalAIWorker`): delete. Only referenced in
  `workers/__init__.py` lines 48, 62. Superseded entirely by `GenericShellWorker`.
- **`mahavishnu/workers/debug_monitor.py`** (`DebugMonitorWorker`): deprecate-in-place.
  Replace `logger.warning("not yet implemented")` with `raise NotImplementedError(...)`.
  Full removal deferred to Wave 2 (after CrowTerminalAdapter is validated).

---

## 3. Track 2 — OpenHands Worker

### 3.1 New File: `mahavishnu/workers/openhands.py`

Three components, following `openclaw_gateway.py` structure:

**`OpenHandsConfig`** (dataclass):
```python
base_url: str = "http://localhost:3000"
api_key: str | None = None       # from OPENHANDS_API_KEY env var
default_timeout: int = 600
runtime: str = "local"
workspace_dir: str | None = None
```

**`OpenHandsClient`** (httpx + WebSocket):

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `create_conversation` | `POST /api/conversations` | Start task, returns `conv_id` |
| `get_conversation` | `GET /api/conversations/{id}` | Poll status |
| `send_message` | `POST /api/conversations/{id}/messages` | Follow-up prompts |
| `cancel` | `DELETE /api/conversations/{id}` | Stop task |
| WebSocket | `ws://host/ws?conversation_id={id}` | Real-time event stream |

WebSocket drives completion detection (`"type": "task_complete"` or `"type": "error"`).
Falls back to REST polling automatically if WebSocket is unavailable.

**`OpenHandsWorker(BaseWorker)`**:
- `execute(task)` → create conversation → subscribe to events → optional quality loop
  → store in Session-Buddy → return `WorkerResult`
- `stop()` → DELETE conversation
- `status()` → GET conversation mapped to `WorkerStatus`

Worker uses `WorkerCategory.GATEWAY`. `GenericShellWorker` rejects GATEWAY workers by
design — `OpenHandsWorker` is instantiated directly by the manager.

### 3.2 Quality Loop

After task completion, if `task.get("run_quality_check", True)` and
`settings.openhands.run_quality_check`:

```
task_complete event received
  → call mcp__crackerjack__execute_crackerjack (if MCP available)
    OR subprocess `crackerjack run` (fallback)
  → result.metadata["quality_score"] = score
  → result.metadata["quality_passed"] = score >= settings.openhands.min_quality_score
```

Quality check failure never blocks task completion. `quality_score = None` when
Crackerjack is unavailable; callers decide whether to surface or retry.

### 3.3 Worker Registry Entry

```python
"openhands": WorkerConfig(
    name="OpenHands",
    worker_type="openhands",
    command="",                    # HTTP-API worker
    category=WorkerCategory.GATEWAY,
    description="Autonomous software dev agent via REST API",
    default_timeout=600,
)
```

### 3.4 MCP Tools: `mahavishnu/mcp/tools/openhands_tools.py`

| Tool | Behaviour |
|------|-----------|
| `openhands_run` | Create conversation, wait for completion, return result (blocking) |
| `openhands_start` | Create conversation, return `conv_id` immediately (non-blocking) |
| `openhands_status` | Poll conversation by `conv_id` |
| `openhands_cancel` | Cancel a running conversation |

Registered via `register_openhands_tools(mcp, settings)` in the standard pattern.
Gated by `settings.openhands.enabled` — tools silently absent when disabled.

### 3.5 Settings Block

```yaml
openhands:
  enabled: false
  base_url: "http://localhost:3000"
  default_timeout: 600
  run_quality_check: true
  min_quality_score: 80
  workspace_dir: null
```

OpenHands does **not** go in `.mcp.json` — it exposes REST/WebSocket, not MCP.

---

## 4. Track 3 — Toad TUI Packages

### 4.1 Scope

Toad the ACP agent is deferred (requires Python 3.14+). This track applies the Textual +
Rich packages Toad is built on to two existing CLI surfaces:

- **`mahavishnu monitor watch`** — live-updating dashboard (new command, Textual)
- **`mahavishnu quality check`** — real implementation with Rich progress (replaces stub)

### 4.2 New Module: `mahavishnu/tui/`

```
mahavishnu/tui/
    __init__.py       # exports TUI_AVAILABLE: bool
    fallback.py       # plain-text alternatives matching TUI output shape
    widgets.py        # reusable Textual widgets
    monitor_app.py    # MonitorApp(App) — live dashboard Textual application
```

`TUI_AVAILABLE = importlib.util.find_spec("textual") is not None`

All CLI commands call `render_*(data)` functions that dispatch internally on
`TUI_AVAILABLE`. No conditional branching in command bodies.

### 4.3 `mahavishnu monitor watch`

New command in `mahavishnu/cli/monitoring_cli.py`.

**TUI mode** (Textual installed): `MonitorApp` with three panels, 2-second refresh timer:

```
┌─ System ──────────────┐ ┌─ Workers / Pools ──────────────┐
│ CPU:    23%           │ │ terminal-claude  [RUNNING]  2s │
│ Memory: 4.1 GB free   │ │ openhands        [IDLE]        │
│ Uptime: 4h 12m        │ │ Pool: local (3/5 workers)      │
└───────────────────────┘ └────────────────────────────────┘
┌─ Adapter Health ──────────────────────────────────────────┐
│ ✓ prefect  ✓ agno  ✓ llamaindex  ✗ hatchet (disabled)    │
└───────────────────────────────────────────────────────────┘
┌─ Active Alerts ───────────────────────────────────────────┐
│ [MEDIUM] High memory usage — 87% at 14:23:01              │
└───────────────────────────────────────────────────────────┘
```

Data source: `maha_app.monitoring_service.get_dashboard_data()` — no new data plumbing.

**Fallback mode** (Textual absent): plain-text `get-dashboard` output in a polling loop
with a clear install hint: `uv sync --group tui`.

### 4.4 `mahavishnu quality check` (replace stub)

Runs the full quality stack sequentially, displaying Rich progress:

```
mahavishnu quality check .

 Running quality checks...
 ✓ ruff (lint)         0.8s   0 issues
 ✓ ruff (format)       0.4s   clean
 ✓ mypy                3.2s   0 errors
 ✓ bandit              1.1s   0 vulnerabilities
 ✓ crackerjack         8.4s   score: 87/100

 Quality gate: PASSED  (87/100 ≥ 80)
```

Uses `rich.progress.Progress` with `SpinnerColumn`. Rich is always available (Typer
transitive dep) — no fallback guard needed here.

### 4.5 Dependencies

`textual>=8.2.7` already in `[tui]` dep group. Rich already a transitive dep. No
`pyproject.toml` changes required.

---

## 5. Error Handling

### 5.1 New Error Codes

Added to `mahavishnu/core/errors.py` (MHV-300 range, continuing from MHV-306):

| Code | Name | Trigger |
|------|------|---------|
| `MHV-307` | `CROW_MCP_UNAVAILABLE` | crow-mcp server unreachable at probe or tool call |
| `MHV-308` | `OPENHANDS_SERVICE_ERROR` | OpenHands REST API non-2xx or connection refused |
| `MHV-309` | `OPENHANDS_TASK_FAILED` | OpenHands conversation completed in error state |

No new exception classes. Error codes carry specificity; existing `MahavishnuError`
hierarchy handles propagation.

### 5.2 Error Behaviour Per Component

**CrowTerminalAdapter:**
- Startup probe failure → `MHV-307`, WARNING log, fall back to `MockTerminalAdapter`
- During `call_tool()` → `MHV-307` in `context`, propagates as `TerminalError`
- No retry on PTY errors — retrying blind creates zombie sessions

**OpenHandsWorker:**
- `httpx.ConnectError` → `MHV-308`, fast-fail, no retry (server is down)
- `httpx.TimeoutException` → exponential backoff via `tenacity`, max 3 retries, then
  `WorkerResult(status=TIMEOUT)`
- WebSocket disconnect → fall back to REST polling automatically
- Conversation state `"error"` → `MHV-309`, error text in `WorkerResult.error`
- Quality loop failure → WARNING log, `quality_score=None`, task result unaffected

---

## 6. Testing Strategy

### 6.1 New Test Files

```
tests/unit/workers/
    test_openhands_worker.py       # @pytest.mark.unit
    test_crow_worker.py            # @pytest.mark.unit

tests/unit/terminal/
    test_crow_adapter.py           # @pytest.mark.unit — protocol conformance

tests/unit/tui/
    test_tui_fallback.py           # @pytest.mark.unit — patches find_spec

tests/integration/
    test_openhands_smoke.py        # @pytest.mark.integration @pytest.mark.requires_network @pytest.mark.slow
    test_crow_mcp_smoke.py         # @pytest.mark.integration @pytest.mark.mcp @pytest.mark.slow
```

### 6.2 Unit Test Approach

- **`OpenHandsWorker`**: `respx` (already in dev deps) mocks httpx. Three scenarios:
  success path, `MHV-308` (connect error), `MHV-309` (conversation error state).
- **`CrowTerminalAdapter`**: mock FastMCP client via `adapter_mocks.py` fixture pattern.
  Protocol conformance: all 5 abstract methods return correct types.
- **TUI fallback**: patch `importlib.util.find_spec` to return `None`, assert plain-text
  output is produced by `render_*` functions.

### 6.3 Guard Test (CI-safe, always runs)

Appended to `tests/unit/` error code tests:
```python
def test_new_integration_error_codes_registered():
    assert ErrorCode.CROW_MCP_UNAVAILABLE == "MHV-307"
    assert ErrorCode.OPENHANDS_SERVICE_ERROR == "MHV-308"
    assert ErrorCode.OPENHANDS_TASK_FAILED == "MHV-309"
```

### 6.4 Coverage Target

All new `workers/` and `terminal/adapters/` code must reach the existing 80% gate.
`respx` mock fixtures make this achievable without live servers.

---

## 7. Port and Transport Summary

| Server | Port | Transport | Entry |
|--------|------|-----------|-------|
| crow-mcp | 8675 | HTTP (FastMCP) | `.mcp.json` |
| OpenHands | 3000 | REST + WebSocket | httpx (no `.mcp.json`) |
| Toad | N/A | TUI / in-process | N/A |

Existing Bodai ports: 8676 (Crackerjack), 8678 (Session-Buddy), 8680 (Mahavishnu),
8682 (Akosha), 8683 (Dhara). Port 8675 is the only clean gap below 8676.

---

## 8. File Manifest

### New Files
- `mahavishnu/terminal/adapters/crow.py` — CrowTerminalAdapter
- `mahavishnu/workers/crow.py` — CrowWorker (ACP)
- `mahavishnu/workers/a2a.py` — A2AWorker
- `mahavishnu/workers/openhands.py` — OpenHandsWorker + OpenHandsClient + OpenHandsConfig
- `mahavishnu/mcp/tools/openhands_tools.py` — 4 MCP tools
- `mahavishnu/tui/__init__.py` — TUI_AVAILABLE flag
- `mahavishnu/tui/fallback.py` — plain-text render functions
- `mahavishnu/tui/widgets.py` — reusable Textual widgets
- `mahavishnu/tui/monitor_app.py` — MonitorApp Textual application
- `tests/unit/workers/test_openhands_worker.py`
- `tests/unit/workers/test_crow_worker.py`
- `tests/unit/terminal/test_crow_adapter.py`
- `tests/unit/tui/test_tui_fallback.py`
- `tests/integration/test_openhands_smoke.py`
- `tests/integration/test_crow_mcp_smoke.py`

### Modified Files
- `mahavishnu/terminal/adapters/__init__.py` — export `CrowTerminalAdapter`
- `mahavishnu/workers/__init__.py` — export new workers; remove `TerminalAIWorker`
- `mahavishnu/workers/registry.py` — add 5 new worker entries
- `mahavishnu/workers/debug_monitor.py` — deprecate-in-place
- `mahavishnu/mcp/tools/__init__.py` — register `openhands_tools`
- `mahavishnu/core/errors.py` — add MHV-307, MHV-308, MHV-309
- `settings/mahavishnu.yaml` — `adapter_preference: crow`, `openhands:` block, health check
- `.mcp.json` — add `crow-mcp` HTTP entry
- `pyproject.toml` — add `[a2a]` optional dep group

### Deleted Files
- `mahavishnu/workers/terminal.py` — `TerminalAIWorker` removed
