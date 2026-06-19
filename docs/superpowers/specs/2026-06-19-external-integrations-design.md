# External Integrations Design: crow-cli, OpenHands, Toad TUI

**Date:** 2026-06-19
**Status:** Approved — ready for implementation planning (rev 3: +TurboVec Track 4)
**Tracks:** 3 parallel, independent

---

## Revision Log

- **rev 1** (2026-06-19): Initial spec
- **rev 3** (2026-06-19): Added Track 4 — TurboVec explicit in-memory fallback for
  LlamaIndex adapter; new `[vector]` dep group in pyproject.toml
- **rev 2** (2026-06-19): Post-subagent review — deferred A2AWorker to Wave 2; moved
  quality loop from worker to MCP tool layer; made MHV-307 fallback config-driven;
  added Security section; added WebSocket/session-lifecycle/quality-loop/TUI test gaps;
  corrected `profiles.py` omission from file manifest; added crow-mcp runbook to new files;
  clarified `conv_id` pass-through; strengthened `workspace_dir` requirements.

---

## Context

Mahavishnu's terminal worker stack (`GenericShellWorker`) is fully implemented but produces
fake output because `MockTerminalAdapter` is the default. OpenHands provides autonomous
coding capability Mahavishnu cannot replicate internally. Toad's Textual/Rich packages
improve CLI readability in monitoring and quality workflows. This spec covers all three.

---

## 1. Overall Architecture

Three independent parallel tracks. No shared *logic*; Tracks 1 and 2 each make additive
edits to `mahavishnu/core/errors.py` and `settings/mahavishnu.yaml` (trivially mergeable).

```
Track 1 — Terminal Gap     Track 2 — OpenHands          Track 3 — Toad TUI
──────────────────────     ────────────────────          ───────────────────
CrowTerminalAdapter        OpenHandsWorker               mahavishnu/tui/
CrowWorker (ACP)           OpenHandsClient (httpx)       monitor watch (Textual)
.mcp.json: crow-mcp        openhands_tools.py (MCP)      quality check (Rich)
adapter_preference: crow   quality loop in openhands_run TUI_AVAILABLE fallback
MHV-307 error              MHV-308, MHV-309 errors       (always degrades cleanly)
```

**Track 4 — TurboVec (LlamaIndex fallback):** small, independent of Tracks 1-3.
`llamaindex_adapter_impl.py` except block + `[vector]` dep group.

**Deferred (not in this spec):** Toad ACP agent (Python 3.14+), BrowserWorker,
A2AWorker (Wave 2 — underspecified + SSRF risk), full A2A discovery mesh.

---

## 2. Track 1 — Terminal Gap (crow-cli)

### 2.1 Problem

`GenericShellWorker` is complete. `TerminalManager` selects adapters at startup via
`adapter_preference`. The default is `"mock"` (`mahavishnu/terminal/config.py:49`,
mirrored in `settings/mahavishnu.yaml`). All terminal workers produce fake output.

### 2.2 CrowTerminalAdapter

**File:** `mahavishnu/terminal/adapters/crow.py`

Implements the full `TerminalAdapter` protocol from `mahavishnu/terminal/adapters/base.py`
— five abstract methods plus the `adapter_name` property:

```python
async def launch_session(self, command: str, columns: int, rows: int, **kwargs) -> str
async def send_command(self, session_id: str, command: str) -> None
async def capture_output(self, session_id: str, lines: int | None) -> str
async def close_session(self, session_id: str) -> None
async def list_sessions(self) -> list[dict[str, Any]]

@property
def adapter_name(self) -> str  # returns "crow"
```

Calls crow-mcp's `terminal` tool via MCP client (`mcp.call_tool("terminal", {...})`),
following the exact pattern of `mahavishnu/terminal/adapters/mcpretentious.py`. Session
state (PTY persistence) is managed server-side by crow-mcp. The `session_id` returned by
`launch_session` is a crow-mcp PTY handle, stored nowhere in Mahavishnu itself.

### 2.3 crow-mcp as HTTP MCP Server

crow-mcp is FastMCP-based. Rather than its default stdio transport it runs as an HTTP
server on port **8675**, binding to `127.0.0.1` only (never `0.0.0.0`).

**Launch:** crow-mcp is a separate project. Mahavishnu *consumes* it; it does not manage
its lifecycle. Operators start it via:
```bash
cd /path/to/crow && uv run python -m crow_mcp --transport http --host 127.0.0.1 --port 8675
```
A runbook lives at `docs/runbooks/crow-mcp-server.md` (see §8 new files). Consider
adding a launchd plist alongside the existing Bifrost plist pattern.

**`.mcp.json` entry:**
```json
"crow-mcp": {
  "type": "http",
  "url": "http://127.0.0.1:8675/mcp"
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

**Fail-fast startup probe:** When `adapter_preference == "crow"`, `TerminalManager`
probes crow-mcp before accepting tasks. Probe failure behaviour is controlled by:

```yaml
terminal:
  adapter_preference: "crow"
  fallback_on_probe_failure: false   # production default — fail hard
```

When `fallback_on_probe_failure: false` (default): probe failure raises `MHV-307` and
blocks startup. When `true` (dev/CI only): falls back to `MockTerminalAdapter` with a
WARNING log that includes the string `[MOCK FALLBACK ACTIVE — NOT FOR PRODUCTION]`.

**CI override:** `MAHAVISHNU_TERMINAL__ADAPTER_PREFERENCE=mock` (Oneiric env-var layering)
bypasses the probe entirely. CI never needs `fallback_on_probe_failure`.

**Session TTL / reaping:** crow-mcp PTY sessions are server-side state. Orphaned sessions
survive crow-mcp restarts only if crow-mcp itself persists them (it currently does not).
Mahavishnu must call `close_session()` in all `stop()` / error paths. A future TTL
mechanism on crow-mcp's side is out of scope for this wave.

### 2.4 Config Flip

`settings/mahavishnu.yaml`, under `terminal:`:
```yaml
terminal:
  adapter_preference: "crow"         # was "auto"
  fallback_on_probe_failure: false   # new key
```

### 2.5 CrowWorker

**File:** `mahavishnu/workers/crow.py`

`CrowWorker(BaseWorker)` for tasks that target crow-cli's ACP reasoning layer directly.
Communicates via ACP session lifecycle: `initialize → new_session → prompt → (poll) →
result`.

**Decision rule (document in registry description):**
- PTY execution (shell, REPL, AI assistant launched in terminal) → `GenericShellWorker`
  with `CrowTerminalAdapter`
- Multi-step autonomous reasoning where crow-cli drives the loop → `CrowWorker`

`CrowWorker` is a sibling of `GenericShellWorker`, not a replacement. Registry entry:
`terminal-crow` / `AI_ASSISTANT` / description: "crow-cli ACP agent — autonomous
multi-step reasoning (not PTY pass-through; use GenericShellWorker for PTY)".

### 2.6 Worker Registry Additions

New entries in `mahavishnu/workers/registry.py`:

| `worker_type` | Category | Description |
|---------------|----------|-------------|
| `terminal-crow` | `AI_ASSISTANT` | crow-cli ACP agent (autonomous reasoning, not PTY) |
| `terminal-aider` | `AI_ASSISTANT` | Aider pair-programming assistant |
| `terminal-goose` | `AI_ASSISTANT` | Block Goose autonomous agent |
| `terminal-gemini` | `AI_ASSISTANT` | Gemini CLI assistant |
| `terminal-amp` | `AI_ASSISTANT` | Amp coding assistant |

### 2.7 Guard Tests

Two guard tests must be confirmed or implemented:

1. `GenericShellWorker` must raise `ValueError` when instantiated with a
   `WorkerCategory.GATEWAY` config. Add `test_generic_shell_rejects_gateway` to the
   relevant unit test file.
2. `TerminalManager` with `adapter_preference="crow"` and `fallback_on_probe_failure=False`
   must raise `MHV-307` (not fall back silently) when the probe fails.

### 2.8 Deletions

- **`mahavishnu/workers/terminal.py`** (`TerminalAIWorker`): delete. Referenced only in
  `workers/__init__.py` lines 48, 62. Superseded by `GenericShellWorker`.
- **`mahavishnu/workers/debug_monitor.py`** (`DebugMonitorWorker`): deprecate-in-place.
  Replace `logger.warning("not yet implemented")` with `raise NotImplementedError(...)`.
  Full removal deferred to Wave 2.

---

## 3. Track 2 — OpenHands Worker

### 3.1 New File: `mahavishnu/workers/openhands.py`

Three components, following `openclaw_gateway.py` structure:

**`OpenHandsConfig`** (dataclass):
```python
base_url: str = "http://localhost:3000"
api_key: str | None = None       # from OPENHANDS_API_KEY env var only
default_timeout: int = 600
runtime: str = "local"
workspace_dir: Path | None = None   # validated Path, not raw str (see §7.2)
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
Falls back to REST polling automatically if WebSocket raises on connect. Both paths
must be unit-tested (see §6.2).

**`OpenHandsWorker(BaseWorker)`**:
- `execute(task)` → create conversation → subscribe to events → return `WorkerResult`
- `stop()` → DELETE conversation
- `status()` → GET conversation mapped to `WorkerStatus`

Worker uses `WorkerCategory.GATEWAY`. Returns a clean `WorkerResult` — no quality check
inside `execute()`. Quality logic lives in the `openhands_run` MCP tool (see §3.4).

### 3.2 Worker Registry Entry

```python
"openhands": WorkerConfig(
    name="OpenHands",
    worker_type="openhands",
    command="",
    category=WorkerCategory.GATEWAY,
    description="Autonomous software dev agent via REST API",
    default_timeout=600,
)
```

### 3.3 `conv_id` Lifecycle

`conv_id` is owned by the OpenHands server. Mahavishnu does not persist it.
`openhands_start` returns it to the MCP caller, who is responsible for passing it to
`openhands_status` and `openhands_cancel`. These tools are stateless pass-throughs to the
OpenHands REST API — no Mahavishnu-side state is required between calls.

### 3.4 MCP Tools: `mahavishnu/mcp/tools/openhands_tools.py`

**Input model (required — do not omit):**
```python
class OpenHandsRunInput(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=10_000)
    timeout: int = Field(600, ge=30, le=3600)
    run_quality_check: bool = True
```

| Tool | Behaviour |
|------|-----------|
| `openhands_run` | Create conversation, wait for completion, **optionally run quality loop**, return result |
| `openhands_start` | Create conversation, return `conv_id` immediately (non-blocking) |
| `openhands_status` | Poll conversation by `conv_id` (stateless pass-through) |
| `openhands_cancel` | Cancel running conversation (stateless pass-through) |

**Quality loop (in `openhands_run` only):**
```
task_complete event received → WorkerResult returned by worker
  → if input.run_quality_check and settings.openhands.run_quality_check:
       try: qc = await _call_crackerjack_mcp()
       except: qc = await _subprocess_crackerjack_fallback(validated_workspace_dir)
       result.metadata["quality_score"] = qc.score if qc else None
       result.metadata["quality_passed"] = (
           qc.score >= settings.openhands.min_quality_score if qc else None
       )
  → return MCP tool response including quality metadata
```

Quality failure never blocks task return. `quality_score = None` when Crackerjack
unavailable; callers surface or ignore as appropriate.

**Registration:** `register_openhands_tools(mcp, settings)` added to
`FULL_REGISTRATIONS` in `profiles.py` (Wave 2 may promote to `STANDARD_REGISTRATIONS`).
Bootstrap checks: `"_register_openhands_tools" in methods_set AND settings.openhands.enabled`.

**Gating:** tools are silently absent when `settings.openhands.enabled: false`.

### 3.5 Settings Block

```yaml
openhands:
  enabled: false
  base_url: "http://localhost:3000"
  default_timeout: 600
  run_quality_check: true
  min_quality_score: 80
  workspace_dir: null     # validated absolute path; config-only, no per-task override
```

OpenHands does **not** go in `.mcp.json` — it exposes REST/WebSocket, not MCP.

---

## 4. Track 3 — Toad TUI Packages

### 4.1 Scope

Toad the ACP agent is deferred (Python 3.14+). This track applies Textual + Rich to two
existing CLI surfaces:

- **`mahavishnu monitor watch`** — live dashboard (new command, Textual)
- **`mahavishnu quality check`** — real implementation with Rich progress (replaces stub)

### 4.2 New Module: `mahavishnu/tui/`

```
mahavishnu/tui/
    __init__.py       # exports TUI_AVAILABLE: bool (module-level constant)
    fallback.py       # plain-text render_*(data) functions
    widgets.py        # reusable Textual widgets
    monitor_app.py    # MonitorApp(App) — live dashboard
```

`TUI_AVAILABLE: bool = importlib.util.find_spec("textual") is not None`

This constant is evaluated once at module import. CLI commands import and use
`TUI_AVAILABLE` directly — they do **not** call `find_spec` themselves. Tests that need
to exercise the `False` path must patch `mahavishnu.tui.TUI_AVAILABLE` (the boolean
attribute), not `importlib.util.find_spec`.

All CLI commands call `render_*(data)` functions that dispatch on `TUI_AVAILABLE`
internally. No conditional branching in command bodies.

### 4.3 `mahavishnu monitor watch`

New command in `mahavishnu/cli/monitoring_cli.py`. 2-second refresh timer.

**TUI mode** (Textual installed):
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
with install hint: `uv sync --group tui`.

**Runtime failure:** `MonitorApp` construction/run failure (e.g. no TTY) must be caught
with `try/except Exception`, log the error, and fall back to plain-text mode.

### 4.4 `mahavishnu quality check` (replace stub)

Uses `rich.progress.Progress` with `SpinnerColumn`. No fallback guard — Rich is always
present via Typer.

```
 Running quality checks...
 ✓ ruff (lint)         0.8s   0 issues
 ✓ ruff (format)       0.4s   clean
 ✓ mypy                3.2s   0 errors
 ✓ bandit              1.1s   0 vulnerabilities
 ✓ crackerjack         8.4s   score: 87/100

 Quality gate: PASSED  (87/100 ≥ 80)
```

### 4.5 Dependencies

`textual>=8.2.7` already in `[tui]` dep group. Rich already a transitive dep. No
`pyproject.toml` changes required.

---

## 5. Error Handling

### 5.1 New Error Codes

Added to `mahavishnu/core/errors.py` (continuing from MHV-306):

| Code | Name | Trigger |
|------|------|---------|
| `MHV-307` | `CROW_MCP_UNAVAILABLE` | crow-mcp probe failure or tool-call error |
| `MHV-308` | `OPENHANDS_SERVICE_ERROR` | OpenHands REST API non-2xx or connection refused |
| `MHV-309` | `OPENHANDS_TASK_FAILED` | Conversation completed in error state |

No new exception classes. `MHV-307` propagates as `TerminalError`; confirm that
`TerminalError` threads the error code through rather than hardcoding `INTERNAL_ERROR`
(check `mcpretentious.py` and fix if needed).

### 5.2 Error Behaviour Per Component

**CrowTerminalAdapter:**
- Probe failure + `fallback_on_probe_failure: false` → raise `MHV-307`, block startup
- Probe failure + `fallback_on_probe_failure: true` → WARNING (with `[MOCK FALLBACK ACTIVE]`),
  switch to `MockTerminalAdapter`
- `call_tool()` error (unknown session_id, PTY crash) → `MHV-307` in context, propagates
  as `TerminalError`
- No retry — retrying blind creates zombie PTY sessions

**OpenHandsWorker:**
- `httpx.ConnectError` → `MHV-308`, fast-fail, no retry
- `httpx.TimeoutException` → exponential backoff via `tenacity`, max 3 retries, then
  `WorkerResult(status=TIMEOUT)`
- WebSocket disconnect → fall back to REST polling automatically
- Conversation state `"error"` → `MHV-309`, error text in `WorkerResult.error`

**`openhands_run` quality loop:**
- Crackerjack MCP unavailable → try subprocess fallback
- Both unavailable → WARNING, `quality_score=None`, task result unaffected
- `WorkerResult.status` remains `COMPLETED` regardless of quality check outcome

---

## 6. Security

### 6.1 `workspace_dir` Path Traversal

`workspace_dir` is a `pathlib.Path` in config, validated at settings load time by a
Pydantic validator that:
- Resolves to absolute realpath (`Path.resolve()`)
- Asserts containment under a configured allowed root (e.g. project directory)
- Rejects symlinks outside the root
- **No per-task override permitted** — `openhands_run` input model has no `workspace_dir`
  field; the config value is used exclusively

### 6.2 `api_key` Leak Prevention

`OpenHandsConfig` must:
- Mask `api_key` in `__repr__` and `__str__` (`"***"`)
- Never place `api_key` in `WorkerResult.metadata`, error context, or MCP tool responses
- Redact the raw httpx response before placing any part of it in metadata (no
  `response.json()` dumps into `WorkerResult.metadata`)

### 6.3 crow-mcp Binding

crow-mcp must bind to `127.0.0.1` (not `0.0.0.0`). The health-check config and `.mcp.json`
URL already use `127.0.0.1`. Auth header matching Mahavishnu's JWT pattern is deferred
to Wave 2 but should be noted in the runbook as a hardening step.

### 6.4 `openhands_run` Input Validation

The Pydantic input model (`OpenHandsRunInput`, §3.4) is mandatory. The prompt field is
data — it must never be interpolated into a shell command that Mahavishnu itself runs.

### 6.5 Quality Loop Subprocess Safety

When falling back to `subprocess crackerjack run`:
- Invoke as argument list (`["crackerjack", "run"]`), `shell=False`
- `cwd` = the validated `workspace_dir` from §6.1
- Resolve absolute path to `crackerjack` executable before invocation
- Apply a timeout matching `settings.openhands.default_timeout`

---

## 7. Testing Strategy

### 7.1 New Test Files

```
tests/unit/workers/
    test_openhands_worker.py       # @pytest.mark.unit
    test_crow_worker.py            # @pytest.mark.unit

tests/unit/terminal/
    test_crow_adapter.py           # @pytest.mark.unit

tests/unit/tui/
    test_tui_fallback.py           # @pytest.mark.unit

tests/integration/
    test_openhands_smoke.py        # @pytest.mark.integration @pytest.mark.requires_network @pytest.mark.slow
    test_crow_mcp_smoke.py         # @pytest.mark.integration @pytest.mark.mcp @pytest.mark.slow
```

### 7.2 Unit Test Coverage Requirements

**`test_openhands_worker.py`** — four scenarios (all via `respx`):
1. Happy path: `POST /conversations` → WS `task_complete` → `WorkerResult(COMPLETED)`
2. WS unavailable: WS connect raises → falls back to REST polling → `WorkerResult(COMPLETED)`
3. `MHV-308`: `httpx.ConnectError` on `POST /conversations` → `WorkerResult` or raised error
4. `MHV-309`: conversation state `"error"` → `WorkerResult(FAILED)` with error text

**`test_crow_adapter.py`** — four scenarios (all via mock MCP client):
1. Protocol conformance: all 5 methods + `adapter_name` property return correct types
2. `send_command` with unknown `session_id` → raises `TerminalError` with MHV-307
3. PTY crash: `call_tool` returns error response → `capture_output` raises `TerminalError`
4. `list_sessions` returns empty list when no sessions exist

**`test_tui_fallback.py`**:
- Patch `mahavishnu.tui.TUI_AVAILABLE = False` (the boolean, not `find_spec`)
- Assert `render_monitor_dashboard(data)` produces plain-text output
- Separate test: `MonitorApp` construction raises → CLI catches and falls back gracefully

**Quality loop test** (add to `test_openhands_worker.py` or a dedicated file):
- Mock both Crackerjack MCP and subprocess to fail
- Assert `result.metadata["quality_score"] is None`
- Assert `result.status == WorkerStatus.COMPLETED`

### 7.3 Guard Tests (CI-safe, always run)

**Error code guard:**
```python
def test_new_integration_error_codes_registered():
    # Use member identity to catch both renames and value changes
    assert ErrorCode("MHV-307") is ErrorCode.CROW_MCP_UNAVAILABLE
    assert ErrorCode("MHV-308") is ErrorCode.OPENHANDS_SERVICE_ERROR
    assert ErrorCode("MHV-309") is ErrorCode.OPENHANDS_TASK_FAILED
    # Guard against duplicate values
    values = [e.value for e in ErrorCode]
    assert len(values) == len(set(values))
```

**GenericShellWorker GATEWAY rejection guard:**
```python
def test_generic_shell_worker_rejects_gateway_category():
    config = WorkerConfig(name="test", worker_type="test",
                          command="", category=WorkerCategory.GATEWAY)
    with pytest.raises(ValueError):
        GenericShellWorker(terminal_manager=mock_tm, worker_type="test", config=config)
```

### 7.4 Smoke Test Assertion

`test_crow_mcp_smoke.py` must assert adapter selection in addition to echo:
```python
assert terminal_manager.active_adapter.__class__.__name__ == "CrowTerminalAdapter"
```
A passing echo with a Mock fallback must not make this test green.

### 7.5 Coverage Target

All new `workers/` and `terminal/adapters/` code must reach the 80% gate. `respx` mock
fixtures and the existing `adapter_mocks.py` pattern make this achievable without live
servers.

### 7.6 Deferred to Wave 2

- Chaos test: OpenHands mid-task crash (connection dropped after `create_conversation`)
- Chaos test: crow-mcp restart with active PTY sessions (orphaned session handling)

---

## 8. Track 4 — TurboVec Explicit In-Memory Fallback (LlamaIndex Adapter)

### 8.1 Problem

`mahavishnu/engines/llamaindex_adapter_impl.py` has a two-path vector store setup in
`__init__` (lines 350–376):

1. **Primary:** `OpensearchVectorStore` — used when OpenSearch is reachable
2. **Fallback (line 375):** `self.vector_store = None` — when OpenSearch fails, index
   creation at line 682 falls back to `VectorStoreIndex(nodes)` with LlamaIndex's
   *implicit* `SimpleVectorStore`

The silent `None` fallback makes the in-memory path unnamed, opaque, and untestable.
The goal: replace `self.vector_store = None` with an explicit `TurboVec` instance.

### 8.2 What TurboVec Is

`turbovec[llama-index]` is a drop-in replacement for
`llama_index.core.vector_stores.SimpleVectorStore` with the same public surface, same
persistence semantics, same retriever and pipeline wiring. Source:
https://github.com/RyanCodrai/turbovec

### 8.3 File Changes

**`mahavishnu/engines/llamaindex_adapter_impl.py`** — one targeted change in the
OpenSearch `except` block (lines 368–376). Replace:

```python
        except Exception as e:
            logger = __import__("logging").getLogger(__name__)
            logger.debug(f"OpenSearch vector store unavailable: {e}")
            logger.info(
                "Using in-memory vector store (install opensearch-knn plugin for persistence)"
            )
            self.vector_store = None  # type: ignore[assignment]
            self._vector_backend = "memory"
```

With:

```python
        except Exception as e:
            logger = __import__("logging").getLogger(__name__)
            logger.debug(f"OpenSearch vector store unavailable: {e}")
            try:
                from turbovec.integrations.llamaindex import TurboVec  # noqa: PLC0415

                self.vector_store = TurboVec()
                self._vector_backend = "turbovec"
                logger.info("Using TurboVec in-memory vector store (install turbovec[llama-index])")
            except ImportError:
                self.vector_store = None  # type: ignore[assignment]
                self._vector_backend = "memory-implicit"
                logger.info(
                    "Using LlamaIndex implicit SimpleVectorStore "
                    "(install turbovec[llama-index] for explicit in-memory store)"
                )
```

**Import path note:** Verify the exact `turbovec` import against the installed package.
The pattern `from turbovec.integrations.llamaindex import TurboVec` is the expected form
for the `[llama-index]` extra; confirm before implementing.

**`_vector_backend` values after this change:**

| Scenario | `_vector_backend` |
|----------|-------------------|
| OpenSearch reachable | `"opensearch"` |
| OpenSearch down, TurboVec installed | `"turbovec"` |
| OpenSearch down, TurboVec not installed | `"memory-implicit"` |

**No changes to lines 674–682.** The `if self.vector_store:` / `else` branch remains.
When `_vector_backend == "turbovec"`, `self.vector_store` is a `TurboVec` instance, so
the `if` branch fires and `VectorStoreIndex` receives a `storage_context` with TurboVec.
The `else` branch now represents "neither OpenSearch nor TurboVec available."

**Conventions:**
- The guarded import (`try/except ImportError`) matches the existing pattern for
  `OpensearchVectorStore` and `LLAMAINDEX_AVAILABLE` in this file
- `from __future__ import annotations` is missing from this file — out of scope for this
  change but noted as tech debt
- The `__import__("logging")` logger in the except block also violates the Oneiric logger
  convention — out of scope, do not touch

### 8.4 Dependency

LlamaIndex is in core `[project.dependencies]` (no separate optional group).
`turbovec[llama-index]` is an optional enhancement — add a new dep group:

```toml
[dependency-groups]
vector = [
    "turbovec[llama-index]~=0.1",
]
```

Add `turbovec` to `[tool.creosote] exclude_deps` alongside `turboquant-pro`.

### 8.5 Scope Boundary

**Only touch:**
- `mahavishnu/engines/llamaindex_adapter_impl.py` (the except block, lines 368–376)
- `pyproject.toml` (new `[vector]` dep group + creosote exclusion)

**Do not touch:** OTel ingester, Agno adapter, any other file.

### 8.6 Test

Add one unit test to `tests/unit/engines/test_llamaindex_adapter.py` (or
`tests/unit/test_adapters/test_llamaindex_adapter.py` — whichever exists):

```python
@pytest.mark.unit
def test_vector_store_fallback_uses_turbovec_when_available(monkeypatch):
    """TurboVec is used as in-memory fallback when OpenSearch is unavailable."""
    # mock OpenSearch import to fail, TurboVec to succeed
    ...
    assert adapter._vector_backend == "turbovec"
    assert adapter.vector_store is not None

@pytest.mark.unit
def test_vector_store_fallback_uses_implicit_when_turbovec_unavailable(monkeypatch):
    """Implicit SimpleVectorStore used when both OpenSearch and TurboVec unavailable."""
    # mock both to fail
    ...
    assert adapter._vector_backend == "memory-implicit"
    assert adapter.vector_store is None
```

---

## 9. Port and Transport Summary

| Server | Port | Bind | Transport | Entry |
|--------|------|------|-----------|-------|
| crow-mcp | 8675 | 127.0.0.1 | HTTP (FastMCP) | `.mcp.json` |
| OpenHands | 3000 | operator-managed | REST + WebSocket | httpx only |
| Toad | N/A | N/A | TUI / in-process | N/A |

Existing Bodai ports: 8676 (Crackerjack), 8678 (Session-Buddy), 8680 (Mahavishnu),
8682 (Akosha), 8683 (Dhara). Port 8675 is the only clean gap below 8676.

---

## 9. File Manifest

### New Files
- `mahavishnu/terminal/adapters/crow.py` — CrowTerminalAdapter
- `mahavishnu/workers/crow.py` — CrowWorker (ACP)
- `mahavishnu/workers/openhands.py` — OpenHandsWorker + OpenHandsClient + OpenHandsConfig
- `mahavishnu/mcp/tools/openhands_tools.py` — 4 MCP tools + OpenHandsRunInput model
- `mahavishnu/tui/__init__.py` — TUI_AVAILABLE flag
- `mahavishnu/tui/fallback.py` — plain-text render functions
- `mahavishnu/tui/widgets.py` — reusable Textual widgets
- `mahavishnu/tui/monitor_app.py` — MonitorApp Textual application
- `docs/runbooks/crow-mcp-server.md` — operator runbook for crow-mcp HTTP server
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
- `mahavishnu/workers/debug_monitor.py` — deprecate-in-place (`raise NotImplementedError`)
- `mahavishnu/mcp/tools/__init__.py` — register `openhands_tools`
- `mahavishnu/mcp/tools/profiles.py` — add `_register_openhands_tools` to `FULL_REGISTRATIONS`
- `mahavishnu/core/errors.py` — add MHV-307, MHV-308, MHV-309; fix `TerminalError` code
- `settings/mahavishnu.yaml` — `adapter_preference: crow`, `fallback_on_probe_failure: false`,
  `openhands:` block, `crow_mcp` health check entry
- `.mcp.json` — add `crow-mcp` HTTP entry (127.0.0.1)
- `pyproject.toml` — add `[a2a]` note deferred; no change needed this wave

### Track 4 — Modified Files
- `mahavishnu/engines/llamaindex_adapter_impl.py` — TurboVec fallback in except block
- `pyproject.toml` — new `[vector]` dep group; creosote exclusion for `turbovec`
- `tests/unit/engines/test_llamaindex_adapter.py` — 2 new unit tests for fallback paths

### Deleted Files
- `mahavishnu/workers/terminal.py` — `TerminalAIWorker` removed

### Wave 2 (not in this spec)
- `mahavishnu/workers/a2a.py` — A2AWorker (deferred: SSRF risk, underspecified)
- `tests/unit/workers/test_a2a_worker.py`
- `tests/chaos/test_openhands_chaos.py`
- `tests/chaos/test_crow_mcp_chaos.py`
