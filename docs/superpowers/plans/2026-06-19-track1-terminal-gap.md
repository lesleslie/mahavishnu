---
status: draft
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: track1-terminal-gap
---

# Track 1 — Terminal Gap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace MockTerminalAdapter as the default with CrowTerminalAdapter backed by crow-mcp, activating GenericShellWorker for real PTY execution across all terminal-based AI workers.

**Architecture:** `CrowTerminalAdapter` implements the 5-method `TerminalAdapter` protocol by calling crow-mcp's PTY tools via MCP client, exactly mirroring `McpretentiousAdapter`. `CrowWorker` is an independent sibling that speaks crow-cli's ACP protocol for autonomous reasoning tasks. The config key `adapter_preference: "crow"` with `fallback_on_probe_failure: false` activates the adapter and fails hard when crow-mcp is unreachable.

**Tech Stack:** FastMCP (MCP client), httpx (probe), Python 3.13, existing `TerminalAdapter` protocol, `MahavishnuError` error hierarchy.

## Global Constraints

- `from __future__ import annotations` as first non-comment line of every new file
- `X | None` not `Optional[X]`; `list[str]` not `List[str]`
- Oneiric logger (`from oneiric.logging import get_logger`) not stdlib logging or print
- No `assert` in production code (`mahavishnu/**`) — use exception hierarchy
- All new deps use `~=` compatible release pins
- Line length 100 chars max
- Async throughout — no blocking calls inside async functions
- Python 3.13 target

______________________________________________________________________

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `mahavishnu/core/errors.py` | Modify | Add `MHV-307 CROW_MCP_UNAVAILABLE` |
| `mahavishnu/terminal/adapters/mcpretentious.py` | Modify | Fix `TerminalError` to accept custom error code |
| `mahavishnu/terminal/adapters/crow.py` | Create | `CrowTerminalAdapter` — 5-method protocol + `adapter_name` |
| `mahavishnu/terminal/adapters/__init__.py` | Modify | Export `CrowTerminalAdapter` |
| `mahavishnu/workers/crow.py` | Create | `CrowWorker` — ACP session lifecycle |
| `mahavishnu/workers/registry.py` | Modify | Add 5 new `WorkerConfig` entries |
| `mahavishnu/workers/__init__.py` | Modify | Export `CrowWorker`; remove `TerminalAIWorker` |
| `mahavishnu/workers/terminal.py` | Delete | `TerminalAIWorker` removed |
| `mahavishnu/workers/debug_monitor.py` | Modify | Deprecate-in-place |
| `settings/mahavishnu.yaml` | Modify | `adapter_preference: crow`, `fallback_on_probe_failure: false`, health check |
| `.mcp.json` | Modify | Add crow-mcp HTTP entry |
| `docs/runbooks/crow-mcp-server.md` | Create | Operator runbook |
| `tests/unit/terminal/test_crow_adapter.py` | Create | 4 unit test scenarios |
| `tests/unit/workers/test_crow_worker.py` | Create | CrowWorker unit tests |

______________________________________________________________________

## Task 1: Error Code + TerminalError Fix

**Files:**

- Modify: `mahavishnu/core/errors.py`
- Modify: `mahavishnu/terminal/adapters/mcpretentious.py`
- Test: (guard test appended to existing error test in Task 5)

**Interfaces:**

- Produces: `ErrorCode.CROW_MCP_UNAVAILABLE = "MHV-307"` (used by Tasks 2–3)

- Produces: `TerminalError(message, error_code=ErrorCode.X, details={})` (backward-compatible)

- [ ] **Step 1: Add MHV-307 to ErrorCode enum**

In `mahavishnu/core/errors.py`, find the External Integration errors block (around line 74). Add after `EXTERNAL_SERVICE_UNAVAILABLE = "MHV-306"`:

```python
    CROW_MCP_UNAVAILABLE = "MHV-307"
```

- [ ] **Step 2: Fix TerminalError to accept a custom error code**

In `mahavishnu/terminal/adapters/mcpretentious.py`, replace the `TerminalError.__init__` method:

```python
class TerminalError(MahavishnuError):
    """Base exception for terminal operations."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, error_code, details=details)
```

- [ ] **Step 3: Verify existing callers still compile**

```bash
cd /Users/les/Projects/mahavishnu && python -c "from mahavishnu.terminal.adapters.mcpretentious import TerminalError, SessionNotFoundError; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/core/errors.py mahavishnu/terminal/adapters/mcpretentious.py
git commit -m "feat(terminal): add MHV-307 error code; fix TerminalError to accept custom code"
```

______________________________________________________________________

## Task 2: CrowTerminalAdapter

**Files:**

- Create: `mahavishnu/terminal/adapters/crow.py`
- Modify: `mahavishnu/terminal/adapters/__init__.py`
- Create: `tests/unit/terminal/test_crow_adapter.py`

**Interfaces:**

- Consumes: `TerminalError`, `SessionNotFoundError`, `ErrorCode.CROW_MCP_UNAVAILABLE` from Task 1
- Consumes: `TerminalAdapter` ABC from `mahavishnu/terminal/adapters/base.py`
- Produces: `CrowTerminalAdapter(mcp_client)` — `adapter_name == "crow"`, all 5 async methods

**NOTE on crow-mcp tool names:** crow-mcp exposes a `terminal` tool that maintains a persistent PTY with directory state. Verify the exact tool name and parameter schema against the installed crow-mcp package before implementing. The tool call pattern is:

```python
result = await mcp_client.call_tool("terminal", {"command": "echo hello"})
# result.content[0].text → output string
```

For multi-session support, crow-mcp may use `session_id` parameters — verify and adjust.

- [ ] **Step 1: Create `tests/unit/terminal/` directory and write the failing tests**

```bash
mkdir -p /Users/les/Projects/mahavishnu/tests/unit/terminal
touch /Users/les/Projects/mahavishnu/tests/unit/terminal/__init__.py
```

Create `tests/unit/terminal/test_crow_adapter.py`:

```python
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.core.errors import ErrorCode
from mahavishnu.terminal.adapters.mcpretentious import SessionNotFoundError, TerminalError


class MockMcpResult:
    def __init__(self, text: str) -> None:
        self.content = [MagicMock(text=text)]


def make_mock_mcp(tool_results: dict[str, Any] | None = None) -> AsyncMock:
    mock = AsyncMock()
    if tool_results:
        mock.call_tool.side_effect = lambda name, params: MockMcpResult(
            tool_results.get(name, "")
        )
    else:
        mock.call_tool.return_value = MockMcpResult("output")
    return mock


@pytest.mark.unit
async def test_adapter_name_is_crow() -> None:
    from mahavishnu.terminal.adapters.crow import CrowTerminalAdapter

    adapter = CrowTerminalAdapter(make_mock_mcp())
    assert adapter.adapter_name == "crow"


@pytest.mark.unit
async def test_launch_session_returns_session_id() -> None:
    from mahavishnu.terminal.adapters.crow import CrowTerminalAdapter

    mcp = make_mock_mcp()
    mcp.call_tool.return_value = MockMcpResult("session-abc123")
    adapter = CrowTerminalAdapter(mcp)

    session_id = await adapter.launch_session("bash")
    assert isinstance(session_id, str)
    assert len(session_id) > 0


@pytest.mark.unit
async def test_send_command_unknown_session_raises_session_not_found() -> None:
    from mahavishnu.terminal.adapters.crow import CrowTerminalAdapter

    adapter = CrowTerminalAdapter(make_mock_mcp())
    with pytest.raises(SessionNotFoundError):
        await adapter.send_command("nonexistent-session", "ls")


@pytest.mark.unit
async def test_capture_output_pty_crash_raises_terminal_error_with_mhv307() -> None:
    from mahavishnu.terminal.adapters.crow import CrowTerminalAdapter

    mcp = make_mock_mcp()
    adapter = CrowTerminalAdapter(mcp)
    # Manually register a session to bypass SessionNotFoundError
    adapter._sessions["session-x"] = {"command": "bash"}
    # Make call_tool raise (simulates PTY crash / crow-mcp error)
    mcp.call_tool.side_effect = RuntimeError("PTY crashed")

    with pytest.raises(TerminalError) as exc_info:
        await adapter.capture_output("session-x")

    assert exc_info.value.error_code == ErrorCode.CROW_MCP_UNAVAILABLE


@pytest.mark.unit
async def test_list_sessions_returns_empty_when_none() -> None:
    from mahavishnu.terminal.adapters.crow import CrowTerminalAdapter

    adapter = CrowTerminalAdapter(make_mock_mcp())
    sessions = await adapter.list_sessions()
    assert sessions == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu && python -m pytest tests/unit/terminal/test_crow_adapter.py -v 2>&1 | head -30
```

Expected: `ImportError: cannot import name 'CrowTerminalAdapter'`

- [ ] **Step 3: Create `mahavishnu/terminal/adapters/crow.py`**

```python
from __future__ import annotations

from typing import Any

from oneiric.logging import get_logger

from mahavishnu.core.errors import ErrorCode

from ..adapters.base import TerminalAdapter
from .mcpretentious import SessionNotFoundError, TerminalError

logger = get_logger(__name__)


class CrowTerminalAdapter(TerminalAdapter):
    """Terminal adapter backed by crow-mcp PTY toolserver.

    Calls crow-mcp's `terminal` tool via MCP client to provide persistent
    PTY sessions. Session state is managed server-side by crow-mcp.

    NOTE: Verify crow-mcp tool names against installed package.
    Expected tool: `terminal` with `{"command": "..."}` parameter.
    """

    def __init__(self, mcp_client: Any) -> None:
        self.mcp = mcp_client
        self._sessions: dict[str, dict[str, Any]] = {}

    @property
    def adapter_name(self) -> str:
        return "crow"

    async def launch_session(
        self,
        command: str,
        columns: int = 80,
        rows: int = 24,
        **kwargs: Any,
    ) -> str:
        """Launch a PTY session via crow-mcp and return a session ID."""
        try:
            result = await self.mcp.call_tool(
                "terminal",
                {"command": command},
            )
            # crow-mcp returns the session output; use a local handle for tracking.
            # If crow-mcp supports explicit session IDs, extract from result here.
            import uuid  # noqa: PLC0415

            session_id = str(uuid.uuid4())
            self._sessions[session_id] = {
                "command": command,
                "columns": columns,
                "rows": rows,
                "initial_output": result.content[0].text if result.content else "",
            }
            logger.debug(f"crow-mcp session launched: {session_id}")
            return session_id
        except Exception as e:
            raise TerminalError(
                message=f"crow-mcp: failed to launch session: {e}",
                error_code=ErrorCode.CROW_MCP_UNAVAILABLE,
                details={"command": command},
            ) from e

    async def send_command(self, session_id: str, command: str) -> None:
        """Send a command to an active crow-mcp PTY session."""
        if session_id not in self._sessions:
            raise SessionNotFoundError(
                message=f"crow-mcp: session {session_id} not found",
                details={"session_id": session_id},
            )
        try:
            await self.mcp.call_tool(
                "terminal",
                {"command": command},
            )
        except Exception as e:
            raise TerminalError(
                message=f"crow-mcp: failed to send command: {e}",
                error_code=ErrorCode.CROW_MCP_UNAVAILABLE,
                details={"session_id": session_id, "command": command},
            ) from e

    async def capture_output(
        self,
        session_id: str,
        lines: int | None = None,
    ) -> str:
        """Capture PTY output from crow-mcp."""
        if session_id not in self._sessions:
            raise SessionNotFoundError(
                message=f"crow-mcp: session {session_id} not found",
                details={"session_id": session_id},
            )
        try:
            result = await self.mcp.call_tool(
                "terminal",
                {"command": ""},  # empty command to flush/read output
            )
            output = result.content[0].text if result.content else ""
            if lines is not None:
                output = "\n".join(output.splitlines()[-lines:])
            return output
        except Exception as e:
            raise TerminalError(
                message=f"crow-mcp: failed to capture output: {e}",
                error_code=ErrorCode.CROW_MCP_UNAVAILABLE,
                details={"session_id": session_id},
            ) from e

    async def close_session(self, session_id: str) -> None:
        """Close a crow-mcp PTY session."""
        if session_id not in self._sessions:
            raise SessionNotFoundError(
                message=f"crow-mcp: session {session_id} not found",
                details={"session_id": session_id},
            )
        try:
            await self.mcp.call_tool("terminal", {"command": "exit"})
            del self._sessions[session_id]
            logger.debug(f"crow-mcp session closed: {session_id}")
        except Exception as e:
            # Best-effort close — remove from local tracking even on error
            self._sessions.pop(session_id, None)
            raise TerminalError(
                message=f"crow-mcp: failed to close session: {e}",
                error_code=ErrorCode.CROW_MCP_UNAVAILABLE,
                details={"session_id": session_id},
            ) from e

    async def list_sessions(self) -> list[dict[str, Any]]:
        """Return all locally tracked crow-mcp sessions."""
        return [
            {"id": sid, **meta}
            for sid, meta in self._sessions.items()
        ]
```

- [ ] **Step 4: Export from `__init__.py`**

In `mahavishnu/terminal/adapters/__init__.py`, add:

```python
from .crow import CrowTerminalAdapter
```

- [ ] **Step 5: Run tests and verify they pass**

```bash
cd /Users/les/Projects/mahavishnu && python -m pytest tests/unit/terminal/test_crow_adapter.py -v
```

Expected: 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/terminal/adapters/crow.py mahavishnu/terminal/adapters/__init__.py \
        tests/unit/terminal/__init__.py tests/unit/terminal/test_crow_adapter.py
git commit -m "feat(terminal): add CrowTerminalAdapter backed by crow-mcp PTY toolserver"
```

______________________________________________________________________

## Task 3: CrowWorker + Registry Additions

**Files:**

- Create: `mahavishnu/workers/crow.py`
- Modify: `mahavishnu/workers/registry.py`
- Modify: `mahavishnu/workers/__init__.py`
- Create: `tests/unit/workers/test_crow_worker.py`

**Interfaces:**

- Consumes: `BaseWorker`, `WorkerResult`, `WorkerStatus` from `mahavishnu/workers/base.py`

- Consumes: `WorkerCategory`, `WorkerConfig` from `mahavishnu/workers/registry.py`

- Produces: `CrowWorker(base_url, session_buddy_client=None)` with `start()`, `execute(task)`, `stop()`, `status()`

- [ ] **Step 1: Create `tests/unit/workers/` directory and write failing tests**

```bash
mkdir -p /Users/les/Projects/mahavishnu/tests/unit/workers
touch /Users/les/Projects/mahavishnu/tests/unit/workers/__init__.py
```

Create `tests/unit/workers/test_crow_worker.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.unit
async def test_crow_worker_execute_returns_completed_result() -> None:
    from mahavishnu.workers.crow import CrowWorker
    from mahavishnu.core.status import WorkerStatus

    worker = CrowWorker(base_url="http://localhost:8765")

    mock_response = {
        "session_id": "sess-abc",
        "status": "completed",
        "result": "Task done.",
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_post.return_value.json.return_value = {"session_id": "sess-abc"}
        mock_post.return_value.raise_for_status = lambda: None
        mock_get.return_value.json.return_value = mock_response
        mock_get.return_value.raise_for_status = lambda: None

        result = await worker.execute({"prompt": "Write a hello world script"})

    assert result.status == WorkerStatus.COMPLETED
    assert result.output is not None


@pytest.mark.unit
async def test_crow_worker_returns_worker_type() -> None:
    from mahavishnu.workers.crow import CrowWorker

    worker = CrowWorker(base_url="http://localhost:8765")
    assert worker.worker_type == "terminal-crow"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu && python -m pytest tests/unit/workers/test_crow_worker.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'CrowWorker'`

- [ ] **Step 3: Create `mahavishnu/workers/crow.py`**

```python
from __future__ import annotations

from typing import Any

import httpx
from oneiric.logging import get_logger

from mahavishnu.core.status import WorkerStatus

from .base import BaseWorker, WorkerResult

logger = get_logger(__name__)

_ACP_TIMEOUT = 30.0


class CrowWorker(BaseWorker):
    """Worker for crow-cli's ACP reasoning layer.

    Use this for multi-step autonomous tasks where crow-cli drives the loop.
    For PTY pass-through (launching a shell/AI assistant in a terminal),
    use GenericShellWorker with CrowTerminalAdapter instead.

    ACP lifecycle: initialize → new_session → prompt → poll → result
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8765",
        session_buddy_client: Any | None = None,
    ) -> None:
        super().__init__(worker_type="terminal-crow")
        self._base_url = base_url.rstrip("/")
        self._session_buddy_client = session_buddy_client
        self._session_id: str | None = None
        self._client = httpx.AsyncClient(timeout=_ACP_TIMEOUT)

    async def start(self) -> str:
        """Initialize ACP connection and create a session."""
        resp = await self._client.post(
            f"{self._base_url}/acp/new_session",
            json={"agent": "crow"},
        )
        resp.raise_for_status()
        self._session_id = resp.json()["session_id"]
        self._status = WorkerStatus.RUNNING
        logger.info(f"CrowWorker ACP session started: {self._session_id}")
        return self._session_id  # type: ignore[return-value]

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        """Send prompt to crow-cli ACP and poll for result."""
        if not self._session_id:
            await self.start()

        prompt = task.get("prompt", "")
        timeout = task.get("timeout", 300)

        resp = await self._client.post(
            f"{self._base_url}/acp/prompt",
            json={"session_id": self._session_id, "prompt": prompt},
        )
        resp.raise_for_status()

        import asyncio  # noqa: PLC0415

        elapsed = 0.0
        poll_interval = 2.0
        while elapsed < timeout:
            poll = await self._client.get(
                f"{self._base_url}/acp/status/{self._session_id}",
            )
            poll.raise_for_status()
            data = poll.json()

            if data.get("status") == "completed":
                return WorkerResult(
                    worker_id=self._session_id or "crow",
                    status=WorkerStatus.COMPLETED,
                    output=data.get("result", ""),
                    duration_seconds=elapsed,
                    metadata={"worker_type": self.worker_type},
                )
            if data.get("status") == "error":
                return WorkerResult(
                    worker_id=self._session_id or "crow",
                    status=WorkerStatus.FAILED,
                    output=None,
                    error=data.get("error", "ACP task failed"),
                    duration_seconds=elapsed,
                    metadata={"worker_type": self.worker_type},
                )

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        return WorkerResult(
            worker_id=self._session_id or "crow",
            status=WorkerStatus.TIMEOUT,
            error="ACP task timed out",
            duration_seconds=elapsed,
            metadata={"worker_type": self.worker_type},
        )

    async def stop(self) -> None:
        """Cancel ACP session."""
        if self._session_id:
            try:
                await self._client.post(
                    f"{self._base_url}/acp/cancel/{self._session_id}",
                )
            except Exception as e:
                logger.warning(f"Failed to cancel CrowWorker ACP session: {e}")
            finally:
                self._status = WorkerStatus.COMPLETED
                await self._client.aclose()

    async def status(self) -> WorkerStatus:
        return self._status

    async def get_progress(self) -> dict[str, Any]:
        return {
            "status": self._status.value,
            "session_id": self._session_id,
            "worker_type": self.worker_type,
        }
```

- [ ] **Step 4: Add registry entries**

In `mahavishnu/workers/registry.py`, after the last existing `AI_ASSISTANT` entry (around `terminal-clai`), add:

```python
    "terminal-crow": WorkerConfig(
        name="crow-cli ACP",
        worker_type="terminal-crow",
        command="",  # HTTP-ACP worker — no shell command
        category=WorkerCategory.AI_ASSISTANT,
        description=(
            "crow-cli ACP agent — autonomous multi-step reasoning. "
            "For PTY pass-through use GenericShellWorker with CrowTerminalAdapter."
        ),
        completion_markers=[],
        default_timeout=300,
        requires_tool="crow",
    ),
    "terminal-aider": WorkerConfig(
        name="Aider",
        worker_type="terminal-aider",
        command="sh -lc 'aider --no-auto-commit'",
        category=WorkerCategory.AI_ASSISTANT,
        description="Aider AI pair-programming assistant",
        completion_markers=[">"],
        default_timeout=300,
        requires_tool="aider",
    ),
    "terminal-goose": WorkerConfig(
        name="Block Goose",
        worker_type="terminal-goose",
        command="sh -lc 'goose'",
        category=WorkerCategory.AI_ASSISTANT,
        description="Block Goose autonomous agent",
        completion_markers=["Goose: "],
        default_timeout=300,
        requires_tool="goose",
    ),
    "terminal-gemini": WorkerConfig(
        name="Gemini CLI",
        worker_type="terminal-gemini",
        command="sh -lc 'gemini'",
        category=WorkerCategory.AI_ASSISTANT,
        description="Gemini CLI AI assistant",
        completion_markers=["> "],
        default_timeout=300,
        requires_tool="gemini",
    ),
    "terminal-amp": WorkerConfig(
        name="Amp",
        worker_type="terminal-amp",
        command="sh -lc 'amp'",
        category=WorkerCategory.AI_ASSISTANT,
        description="Amp AI coding assistant",
        completion_markers=["> "],
        default_timeout=300,
        requires_tool="amp",
    ),
```

- [ ] **Step 5: Update `workers/__init__.py`**

Find the `TerminalAIWorker` import lines (48, 62) and remove them. Add `CrowWorker`:

```python
from .crow import CrowWorker
```

- [ ] **Step 6: Delete `terminal.py`**

```bash
rm /Users/les/Projects/mahavishnu/mahavishnu/workers/terminal.py
```

- [ ] **Step 7: Run tests**

```bash
cd /Users/les/Projects/mahavishnu && python -m pytest tests/unit/workers/test_crow_worker.py -v
```

Expected: 2 tests PASS

- [ ] **Step 8: Verify registry import**

```bash
python -c "from mahavishnu.workers.registry import WORKER_REGISTRY; print(list(WORKER_REGISTRY.keys()))"
```

Expected: `[..., 'terminal-crow', 'terminal-aider', 'terminal-goose', 'terminal-gemini', 'terminal-amp']`

- [ ] **Step 9: Commit**

```bash
git add mahavishnu/workers/crow.py mahavishnu/workers/registry.py mahavishnu/workers/__init__.py \
        tests/unit/workers/__init__.py tests/unit/workers/test_crow_worker.py
git rm mahavishnu/workers/terminal.py
git commit -m "feat(workers): add CrowWorker (ACP), 5 new registry entries; delete TerminalAIWorker"
```

______________________________________________________________________

## Task 4: Config, .mcp.json, Settings, Runbook

**Files:**

- Modify: `settings/mahavishnu.yaml`

- Modify: `.mcp.json`

- Create: `docs/runbooks/crow-mcp-server.md`

- Modify: `mahavishnu/workers/debug_monitor.py`

- [ ] **Step 1: Update `settings/mahavishnu.yaml` terminal block**

Find the `terminal:` section and replace `adapter_preference: "auto"` with:

```yaml
terminal:
  enabled: true
  default_columns: 120
  default_rows: 40
  capture_lines: 100
  poll_interval: 0.5
  max_concurrent_sessions: 20
  adapter_preference: "crow"
  fallback_on_probe_failure: false
```

Then add a `crow_mcp` entry under `health.dependencies`:

```yaml
    crow_mcp:
      host: "localhost"
      port: 8675
      required: false
      timeout_seconds: 10
      use_tls: false
```

- [ ] **Step 2: Add crow-mcp to `.mcp.json`**

Open `.mcp.json` and add a new entry alongside the existing servers:

```json
"crow-mcp": {
  "type": "http",
  "url": "http://127.0.0.1:8675/mcp"
}
```

- [ ] **Step 3: Deprecate DebugMonitorWorker**

In `mahavishnu/workers/debug_monitor.py`, find the `logger.warning("DebugMonitorWorker not yet implemented (Phase 3)")` line and replace with:

```python
raise NotImplementedError(
    "DebugMonitorWorker is deprecated. "
    "Use CrowTerminalAdapter with GenericShellWorker for terminal debugging. "
    "Full removal scheduled for Wave 2."
)
```

- [ ] **Step 4: Create crow-mcp runbook**

```bash
mkdir -p /Users/les/Projects/mahavishnu/docs/runbooks
```

Create `docs/runbooks/crow-mcp-server.md`:

````markdown
# crow-mcp HTTP Server Runbook

crow-mcp provides PTY terminal execution for Mahavishnu via MCP on port **8675**.

## Prerequisites

- crow-cli installed: `uv tool install crow-cli` (or per project install)
- Verify: `crow-mcp --help`

## Start

```bash
cd /path/to/crow-cli
uv run python -m crow_mcp --transport http --host 127.0.0.1 --port 8675
````

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

````

- [ ] **Step 5: Verify settings parse cleanly**

```bash
cd /Users/les/Projects/mahavishnu && python -c "
from mahavishnu.core.config import MahavishnuSettings
s = MahavishnuSettings()
print('adapter_preference:', s.terminal.adapter_preference)
print('fallback_on_probe_failure:', s.terminal.fallback_on_probe_failure)
"
````

Expected: prints `crow` and `False`. If `fallback_on_probe_failure` is not yet a field in `MahavishnuSettings`, add it to the terminal config model with `fallback_on_probe_failure: bool = False`.

- [ ] **Step 6: Commit**

```bash
git add settings/mahavishnu.yaml .mcp.json mahavishnu/workers/debug_monitor.py \
        docs/runbooks/crow-mcp-server.md
git commit -m "feat(config): activate crow adapter; add crow-mcp .mcp.json + runbook; deprecate DebugMonitorWorker"
```

______________________________________________________________________

## Task 5: Guard Tests

**Files:**

- Modify or create: `tests/unit/test_error_codes.py`

- Modify: relevant terminal/worker test file

- [ ] **Step 1: Write guard tests**

Append to `tests/unit/test_error_codes.py` (or create if it doesn't exist):

```python
from __future__ import annotations

import pytest

from mahavishnu.core.errors import ErrorCode
from mahavishnu.workers.base import WorkerResult
from mahavishnu.workers.registry import WorkerCategory, WorkerConfig


@pytest.mark.unit
def test_crow_mcp_unavailable_error_code_registered() -> None:
    assert ErrorCode("MHV-307") is ErrorCode.CROW_MCP_UNAVAILABLE


@pytest.mark.unit
def test_no_duplicate_error_code_values() -> None:
    values = [e.value for e in ErrorCode]
    assert len(values) == len(set(values)), "Duplicate error code values detected"


@pytest.mark.unit
def test_generic_shell_worker_rejects_gateway_category() -> None:
    from mahavishnu.terminal.manager import TerminalManager
    from unittest.mock import MagicMock
    from mahavishnu.workers.generic_shell import GenericShellWorker

    config = WorkerConfig(
        name="test",
        worker_type="test-gateway",
        command="",
        category=WorkerCategory.GATEWAY,
        description="Test gateway worker",
    )

    with pytest.raises(ValueError, match="requires a non-empty command"):
        GenericShellWorker(
            terminal_manager=MagicMock(spec=TerminalManager),
            worker_type="test-gateway",
            config=config,
        )
```

- [ ] **Step 2: Run guard tests**

```bash
cd /Users/les/Projects/mahavishnu && python -m pytest tests/unit/test_error_codes.py -v -k "crow or duplicate or gateway"
```

Expected: 3 tests PASS

- [ ] **Step 3: Final Track 1 regression run**

```bash
cd /Users/les/Projects/mahavishnu && python -m pytest tests/unit/terminal/ tests/unit/workers/ tests/unit/test_error_codes.py -v
```

Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_error_codes.py
git commit -m "test(terminal): add guard tests for MHV-307, no-duplicate codes, GATEWAY rejection"
```
