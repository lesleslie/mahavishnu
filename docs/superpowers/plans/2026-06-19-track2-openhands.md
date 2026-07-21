---
status: draft
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: track2-openhands
---

# Track 2 — OpenHands Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Goal:** Integrate OpenHands autonomous dev agent (v1.7.0) into Mahavishnu via a thin HTTP+WebSocket client, producing an `openhands_run` MCP tool with an integrated Crackerjack quality gate.
> **Architecture:** `OpenHandsClient` (httpx + websockets) wraps the OpenHands REST API. `OpenHandsWorker` extends `BaseWorker` and is registered under `WorkerCategory.GATEWAY` — it routes through HTTP, not PTY. The `openhands_run` MCP tool (registered in `openhands_tools.py`) owns the Crackerjack quality loop: this keeps workers decoupled from quality tools. `workspace_dir` is config-only, path-validated at startup.
> **Tech Stack:** httpx[http2], websockets, FastMCP, Pydantic v2, oneiric logger, Python 3.13, OpenHands REST API (port 3000).

## Global Constraints

- `from __future__ import annotations` as first non-comment line of every new file
- `X | None` not `Optional[X]`; `list[str]` not `List[str]`
- Oneiric logger (`from oneiric.logging import get_logger`) not stdlib logging or print
- No `assert` in production code — use exception hierarchy from `mahavishnu/core/errors.py`
- No per-task `workspace_dir` override — config-only, validated Path with realpath containment
- `conv_id` is stateless: never persist it; owned by the OpenHands server
- Quality loop belongs in `openhands_run` MCP tool, NOT inside `OpenHandsWorker.execute()`
- All I/O async — no blocking calls inside async functions
- Line length 100 chars max

______________________________________________________________________

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `mahavishnu/core/errors.py` | Modify | Add `MHV-308 OPENHANDS_SERVICE_ERROR`, `MHV-309 OPENHANDS_TASK_FAILED` |
| `mahavishnu/workers/openhands.py` | Create | `OpenHandsConfig`, `OpenHandsClient`, `OpenHandsWorker` |
| `mahavishnu/workers/registry.py` | Modify | Add `openhands` `WorkerConfig` |
| `mahavishnu/workers/__init__.py` | Modify | Export `OpenHandsWorker` |
| `mahavishnu/mcp/tools/openhands_tools.py` | Create | `openhands_run`, `openhands_status`, `openhands_cancel`, `openhands_health` tools |
| `mahavishnu/mcp/tools/profiles.py` | Modify | Register `openhands_tools` in `FULL_REGISTRATIONS` |
| `settings/mahavishnu.yaml` | Modify | Add `openhands:` block |
| `tests/unit/workers/test_openhands_worker.py` | Create | 5 worker unit test scenarios |
| `tests/unit/mcp/test_openhands_tools.py` | Create | 4 tool unit test scenarios |

______________________________________________________________________

## Task 1: Error Codes

**Files:**

- Modify: `mahavishnu/core/errors.py`

**Interfaces:**

- Consumes: existing `ErrorCode` enum

- Produces: `ErrorCode.OPENHANDS_SERVICE_ERROR = "MHV-308"`, `ErrorCode.OPENHANDS_TASK_FAILED = "MHV-309"` (used by Tasks 2–3)

- [ ] **Step 1: Add MHV-308 and MHV-309**

In `mahavishnu/core/errors.py`, in the External Integration errors block, add after `MHV-307`:

```python
    OPENHANDS_SERVICE_ERROR = "MHV-308"
    OPENHANDS_TASK_FAILED = "MHV-309"
```

- [ ] **Step 2: Verify**

```bash
cd /Users/les/Projects/mahavishnu && python -c "
from mahavishnu.core.errors import ErrorCode
print(ErrorCode.OPENHANDS_SERVICE_ERROR.value)
print(ErrorCode.OPENHANDS_TASK_FAILED.value)
"
```

Expected: `MHV-308`, `MHV-309`

- [ ] **Step 3: Commit**

```bash
git add mahavishnu/core/errors.py
git commit -m "feat(errors): add MHV-308 OPENHANDS_SERVICE_ERROR, MHV-309 OPENHANDS_TASK_FAILED"
```

______________________________________________________________________

## Task 2: OpenHandsClient + OpenHandsWorker

**Files:**

- Create: `mahavishnu/workers/openhands.py`
- Modify: `mahavishnu/workers/registry.py`
- Modify: `mahavishnu/workers/__init__.py`
- Create: `tests/unit/workers/test_openhands_worker.py`

**Interfaces:**

- Consumes: `ErrorCode.OPENHANDS_SERVICE_ERROR`, `ErrorCode.OPENHANDS_TASK_FAILED` from Task 1

- Consumes: `BaseWorker`, `WorkerResult`, `WorkerStatus` from `mahavishnu/workers/base.py`

- Produces: `OpenHandsConfig(base_url, workspace_dir, timeout_seconds, poll_interval_seconds)`

- Produces: `OpenHandsClient(config)` with `create_conversation(task)`, `get_status(conv_id)`, `cancel_conversation(conv_id)`, `health_check()`

- Produces: `OpenHandsWorker(config, crackerjack_client=None)` with `.execute(task)`, `.stop()`, `.status()`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/workers/test_openhands_worker.py`:

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.errors import ErrorCode
from mahavishnu.core.status import WorkerStatus


def make_config(tmp_path: Path) -> "OpenHandsConfig":  # noqa: UP037
    from mahavishnu.workers.openhands import OpenHandsConfig

    return OpenHandsConfig(
        base_url="http://localhost:3000",
        workspace_dir=tmp_path,
        timeout_seconds=60,
        poll_interval_seconds=0.1,
    )


@pytest.mark.unit
async def test_worker_execute_returns_completed_on_success(tmp_path: Path) -> None:
    from mahavishnu.workers.openhands import OpenHandsWorker

    config = make_config(tmp_path)
    worker = OpenHandsWorker(config=config)

    with patch(
        "mahavishnu.workers.openhands.OpenHandsClient.create_conversation",
        new_callable=AsyncMock,
        return_value="conv-123",
    ), patch(
        "mahavishnu.workers.openhands.OpenHandsClient.get_status",
        new_callable=AsyncMock,
        return_value={"status": "completed", "result": "done"},
    ):
        result = await worker.execute({"prompt": "Write a test", "timeout": 60})

    assert result.status == WorkerStatus.COMPLETED
    assert result.output is not None


@pytest.mark.unit
async def test_worker_execute_returns_failed_on_task_error(tmp_path: Path) -> None:
    from mahavishnu.workers.openhands import OpenHandsWorker

    config = make_config(tmp_path)
    worker = OpenHandsWorker(config=config)

    with patch(
        "mahavishnu.workers.openhands.OpenHandsClient.create_conversation",
        new_callable=AsyncMock,
        return_value="conv-456",
    ), patch(
        "mahavishnu.workers.openhands.OpenHandsClient.get_status",
        new_callable=AsyncMock,
        return_value={"status": "error", "error": "task failed"},
    ):
        result = await worker.execute({"prompt": "Bad task", "timeout": 60})

    assert result.status == WorkerStatus.FAILED
    assert result.error_code == ErrorCode.OPENHANDS_TASK_FAILED


@pytest.mark.unit
async def test_worker_execute_returns_timeout_when_poll_expires(tmp_path: Path) -> None:
    from mahavishnu.workers.openhands import OpenHandsWorker

    config = make_config(tmp_path)
    config.timeout_seconds = 0.1  # force immediate timeout
    worker = OpenHandsWorker(config=config)

    with patch(
        "mahavishnu.workers.openhands.OpenHandsClient.create_conversation",
        new_callable=AsyncMock,
        return_value="conv-789",
    ), patch(
        "mahavishnu.workers.openhands.OpenHandsClient.get_status",
        new_callable=AsyncMock,
        return_value={"status": "running"},
    ):
        result = await worker.execute({"prompt": "Slow task", "timeout": 0})

    assert result.status == WorkerStatus.TIMEOUT


@pytest.mark.unit
async def test_worker_execute_raises_on_service_unavailable(tmp_path: Path) -> None:
    from mahavishnu.workers.openhands import OpenHandsWorker

    config = make_config(tmp_path)
    worker = OpenHandsWorker(config=config)

    with patch(
        "mahavishnu.workers.openhands.OpenHandsClient.create_conversation",
        new_callable=AsyncMock,
        side_effect=ConnectionError("OpenHands unreachable"),
    ):
        result = await worker.execute({"prompt": "Any task", "timeout": 10})

    assert result.status == WorkerStatus.FAILED
    assert result.error_code == ErrorCode.OPENHANDS_SERVICE_ERROR


@pytest.mark.unit
async def test_worker_execute_websocket_fallback_to_polling(tmp_path: Path) -> None:
    """WebSocket status stream failing must fall back to REST polling."""
    from mahavishnu.workers.openhands import OpenHandsWorker

    config = make_config(tmp_path)
    worker = OpenHandsWorker(config=config)

    with patch(
        "mahavishnu.workers.openhands.OpenHandsClient.create_conversation",
        new_callable=AsyncMock,
        return_value="conv-ws-fail",
    ), patch(
        "mahavishnu.workers.openhands.OpenHandsClient.stream_events",
        new_callable=AsyncMock,
        side_effect=ConnectionError("WS refused"),
    ), patch(
        "mahavishnu.workers.openhands.OpenHandsClient.get_status",
        new_callable=AsyncMock,
        return_value={"status": "completed", "result": "done via polling"},
    ):
        result = await worker.execute({"prompt": "WS fallback task", "timeout": 60})

    assert result.status == WorkerStatus.COMPLETED
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu && python -m pytest tests/unit/workers/test_openhands_worker.py -v 2>&1 | head -25
```

Expected: `ImportError: cannot import name 'OpenHandsWorker'`

- [ ] **Step 3: Create `mahavishnu/workers/openhands.py`**

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from oneiric.logging import get_logger

from mahavishnu.core.errors import ErrorCode
from mahavishnu.core.status import WorkerStatus

from .base import BaseWorker, WorkerResult

logger = get_logger(__name__)


@dataclass
class OpenHandsConfig:
    base_url: str = "http://localhost:3000"
    workspace_dir: Path = Path("/tmp/openhands-workspace")
    timeout_seconds: int = 600
    poll_interval_seconds: float = 3.0
    max_output_chars: int = 50_000


class OpenHandsClient:
    """Thin async client for the OpenHands REST API."""

    def __init__(self, config: OpenHandsConfig) -> None:
        self._config = config
        self._http = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=httpx.Timeout(30.0),
        )

    async def create_conversation(self, task: str) -> str:
        """Start an OpenHands conversation and return its conv_id."""
        resp = await self._http.post(
            "/api/conversations",
            json={"task": task},
        )
        resp.raise_for_status()
        return resp.json()["conversation_id"]

    async def get_status(self, conv_id: str) -> dict[str, Any]:
        """Poll REST endpoint for conversation status."""
        resp = await self._http.get(f"/api/conversations/{conv_id}")
        resp.raise_for_status()
        return resp.json()

    async def stream_events(self, conv_id: str) -> list[dict[str, Any]]:
        """Attempt to consume WebSocket events (best-effort, may raise)."""
        import websockets  # noqa: PLC0415

        url = self._config.base_url.replace("http://", "ws://").replace(
            "https://", "wss://"
        ) + f"/ws?conversation_id={conv_id}"
        events: list[dict[str, Any]] = []
        import json  # noqa: PLC0415

        async with websockets.connect(url) as ws:
            async for raw in ws:
                event = json.loads(raw)
                events.append(event)
                if event.get("type") in ("FINISHED", "ERROR"):
                    break
        return events

    async def cancel_conversation(self, conv_id: str) -> None:
        await self._http.delete(f"/api/conversations/{conv_id}")

    async def health_check(self) -> bool:
        try:
            resp = await self._http.get("/health", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        await self._http.aclose()


class OpenHandsWorker(BaseWorker):
    """Gateway worker delegating autonomous dev tasks to an OpenHands server.

    Does NOT embed a quality loop — quality checks belong in the MCP tool layer
    (openhands_tools.openhands_run).
    """

    def __init__(
        self,
        config: OpenHandsConfig | None = None,
        crackerjack_client: Any | None = None,
    ) -> None:
        super().__init__(worker_type="openhands")
        self._config = config or OpenHandsConfig()
        self._crackerjack_client = crackerjack_client
        self._client = OpenHandsClient(self._config)

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        """Submit a task to OpenHands and poll/stream until completion."""
        prompt = task.get("prompt", "")
        timeout = task.get("timeout", self._config.timeout_seconds)

        try:
            conv_id = await self._client.create_conversation(prompt)
        except Exception as e:
            return WorkerResult(
                worker_id="openhands",
                status=WorkerStatus.FAILED,
                error=str(e),
                error_code=ErrorCode.OPENHANDS_SERVICE_ERROR,
                metadata={"worker_type": self.worker_type},
            )

        # Prefer WebSocket stream; fall back to REST polling on connection failure.
        try:
            events = await self._client.stream_events(conv_id)
            finished = next(
                (e for e in events if e.get("type") in ("FINISHED", "ERROR")), None
            )
            if finished:
                if finished.get("type") == "ERROR":
                    return WorkerResult(
                        worker_id=conv_id,
                        status=WorkerStatus.FAILED,
                        error=finished.get("message", "OpenHands task failed"),
                        error_code=ErrorCode.OPENHANDS_TASK_FAILED,
                        metadata={"worker_type": self.worker_type, "conv_id": conv_id},
                    )
                output = finished.get("result") or finished.get("message", "")
                return WorkerResult(
                    worker_id=conv_id,
                    status=WorkerStatus.COMPLETED,
                    output=output[: self._config.max_output_chars],
                    metadata={"worker_type": self.worker_type, "conv_id": conv_id},
                )
        except Exception as ws_err:
            logger.warning(f"OpenHands WS stream failed, falling back to polling: {ws_err}")

        # REST polling fallback
        elapsed = 0.0
        while elapsed < timeout:
            try:
                data = await self._client.get_status(conv_id)
            except Exception as e:
                return WorkerResult(
                    worker_id=conv_id,
                    status=WorkerStatus.FAILED,
                    error=str(e),
                    error_code=ErrorCode.OPENHANDS_SERVICE_ERROR,
                    metadata={"worker_type": self.worker_type, "conv_id": conv_id},
                )

            status = data.get("status")
            if status == "completed":
                output = data.get("result", "")
                return WorkerResult(
                    worker_id=conv_id,
                    status=WorkerStatus.COMPLETED,
                    output=str(output)[: self._config.max_output_chars],
                    duration_seconds=elapsed,
                    metadata={"worker_type": self.worker_type, "conv_id": conv_id},
                )
            if status == "error":
                return WorkerResult(
                    worker_id=conv_id,
                    status=WorkerStatus.FAILED,
                    error=data.get("error", "OpenHands task failed"),
                    error_code=ErrorCode.OPENHANDS_TASK_FAILED,
                    duration_seconds=elapsed,
                    metadata={"worker_type": self.worker_type, "conv_id": conv_id},
                )

            await asyncio.sleep(self._config.poll_interval_seconds)
            elapsed += self._config.poll_interval_seconds

        return WorkerResult(
            worker_id=conv_id,
            status=WorkerStatus.TIMEOUT,
            error="OpenHands task timed out",
            duration_seconds=elapsed,
            metadata={"worker_type": self.worker_type, "conv_id": conv_id},
        )

    async def stop(self) -> None:
        self._status = WorkerStatus.COMPLETED
        await self._client.close()

    async def status(self) -> WorkerStatus:
        return self._status

    async def get_progress(self) -> dict[str, Any]:
        return {"status": self._status.value, "worker_type": self.worker_type}
```

- [ ] **Step 4: Add registry entry**

In `mahavishnu/workers/registry.py`, add after the last existing AI_ASSISTANT entry:

```python
    "openhands": WorkerConfig(
        name="OpenHands",
        worker_type="openhands",
        command="",  # GATEWAY worker — HTTP API, no shell command
        category=WorkerCategory.GATEWAY,
        description="OpenHands autonomous dev agent v1.7.0 — REST+WebSocket API",
        completion_markers=[],
        default_timeout=600,
        requires_tool="openhands",
    ),
```

- [ ] **Step 5: Export from `workers/__init__.py`**

Add:

```python
from .openhands import OpenHandsWorker
```

- [ ] **Step 6: Run tests**

```bash
cd /Users/les/Projects/mahavishnu && python -m pytest tests/unit/workers/test_openhands_worker.py -v
```

Expected: 5 tests PASS

- [ ] **Step 7: Commit**

```bash
git add mahavishnu/workers/openhands.py mahavishnu/workers/registry.py \
        mahavishnu/workers/__init__.py \
        tests/unit/workers/test_openhands_worker.py
git commit -m "feat(workers): add OpenHandsWorker + GATEWAY registry entry"
```

______________________________________________________________________

## Task 3: MCP Tools + Profiles

**Files:**

- Create: `mahavishnu/mcp/tools/openhands_tools.py`
- Modify: `mahavishnu/mcp/tools/profiles.py`
- Create: `tests/unit/mcp/test_openhands_tools.py`

**Interfaces:**

- Consumes: `OpenHandsWorker`, `OpenHandsConfig`, `OpenHandsClient` from Task 2

- Consumes: FastMCP `@mcp.tool()` decorator pattern from existing tool files

- Produces: 4 registered MCP tools — `openhands_run`, `openhands_status`, `openhands_cancel`, `openhands_health`

- Produces: `OpenHandsRunInput(prompt, timeout, run_quality_check)` Pydantic model

- [ ] **Step 1: Write failing tool tests**

Create `tests/unit/mcp/test_openhands_tools.py`:

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from pydantic import ValidationError


@pytest.mark.unit
def test_openhands_run_input_rejects_empty_prompt() -> None:
    from mahavishnu.mcp.tools.openhands_tools import OpenHandsRunInput

    with pytest.raises(ValidationError):
        OpenHandsRunInput(prompt="", timeout=60, run_quality_check=False)


@pytest.mark.unit
def test_openhands_run_input_rejects_oversized_prompt() -> None:
    from mahavishnu.mcp.tools.openhands_tools import OpenHandsRunInput

    with pytest.raises(ValidationError):
        OpenHandsRunInput(
            prompt="x" * 10_001,
            timeout=60,
            run_quality_check=False,
        )


@pytest.mark.unit
def test_openhands_run_input_rejects_timeout_out_of_range() -> None:
    from mahavishnu.mcp.tools.openhands_tools import OpenHandsRunInput

    with pytest.raises(ValidationError):
        OpenHandsRunInput(prompt="valid", timeout=10, run_quality_check=False)


@pytest.mark.unit
async def test_openhands_run_returns_quality_score_none_path(tmp_path: Path) -> None:
    """When Crackerjack returns quality_score=None, result must still succeed."""
    from mahavishnu.mcp.tools.openhands_tools import OpenHandsRunInput, run_openhands_task

    inp = OpenHandsRunInput(prompt="Write tests", timeout=60, run_quality_check=True)
    mock_worker_result = MagicMock()
    mock_worker_result.status.value = "completed"
    mock_worker_result.output = "all tests pass"

    with patch(
        "mahavishnu.mcp.tools.openhands_tools.OpenHandsWorker.execute",
        new_callable=AsyncMock,
        return_value=mock_worker_result,
    ), patch(
        "mahavishnu.mcp.tools.openhands_tools._run_quality_check",
        new_callable=AsyncMock,
        return_value=None,  # quality_score=None
    ):
        result = await run_openhands_task(inp)

    assert result["status"] == "completed"
    assert result.get("quality_score") is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu && python -m pytest tests/unit/mcp/test_openhands_tools.py -v 2>&1 | head -25
```

Expected: `ImportError: cannot import name 'OpenHandsRunInput'`

- [ ] **Step 3: Create `mahavishnu/mcp/tools/openhands_tools.py`**

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from oneiric.logging import get_logger
from pydantic import BaseModel, Field

from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.workers.openhands import OpenHandsClient, OpenHandsConfig, OpenHandsWorker

logger = get_logger(__name__)
mcp = FastMCP("openhands")

_settings = MahavishnuSettings()


class OpenHandsRunInput(BaseModel):
    """Validated input for the openhands_run MCP tool."""

    prompt: str = Field(..., min_length=1, max_length=10_000)
    timeout: int = Field(600, ge=30, le=3600)
    run_quality_check: bool = True


def _make_config() -> OpenHandsConfig:
    """Build OpenHandsConfig from MahavishnuSettings."""
    oh_settings = getattr(_settings, "openhands", None)
    base_url = getattr(oh_settings, "base_url", "http://localhost:3000") if oh_settings else "http://localhost:3000"
    workspace_dir = getattr(oh_settings, "workspace_dir", Path("/tmp/openhands-workspace")) if oh_settings else Path("/tmp/openhands-workspace")

    # Validate workspace_dir containment (MUST be under a configured root)
    workspace_dir = Path(workspace_dir).resolve()
    allowed_root = Path("/tmp").resolve()  # override via settings in production
    if oh_settings and hasattr(oh_settings, "workspace_root"):
        allowed_root = Path(oh_settings.workspace_root).resolve()
    if not str(workspace_dir).startswith(str(allowed_root)):
        raise ValueError(
            f"workspace_dir {workspace_dir} is outside allowed root {allowed_root}"
        )

    return OpenHandsConfig(base_url=base_url, workspace_dir=workspace_dir)


async def _run_quality_check(output: str) -> int | None:
    """Run Crackerjack quality check on output. Returns score or None."""
    try:
        from mahavishnu.quality_cli import run_quality_check as crackerjack_check  # noqa: PLC0415

        score = await crackerjack_check(output)
        return score
    except Exception as e:
        logger.warning(f"Quality check failed (non-fatal): {e}")
        return None


async def run_openhands_task(inp: OpenHandsRunInput) -> dict[str, Any]:
    """Core implementation — called by both the MCP tool and tests."""
    config = _make_config()
    worker = OpenHandsWorker(config=config)

    result = await worker.execute({"prompt": inp.prompt, "timeout": inp.timeout})

    quality_score: int | None = None
    if inp.run_quality_check and result.output:
        quality_score = await _run_quality_check(result.output)

    return {
        "status": result.status.value,
        "output": result.output,
        "error": result.error if result.status.value != "completed" else None,
        "quality_score": quality_score,
        "worker_type": "openhands",
    }


@mcp.tool()
async def openhands_run(
    prompt: str,
    timeout: int = 600,
    run_quality_check: bool = True,
) -> dict[str, Any]:
    """Submit an autonomous development task to OpenHands.

    Args:
        prompt: Task description (1–10,000 chars).
        timeout: Max seconds to wait (30–3600). Default 600.
        run_quality_check: Run Crackerjack quality check on output. Default True.
    """
    inp = OpenHandsRunInput(prompt=prompt, timeout=timeout, run_quality_check=run_quality_check)
    return await run_openhands_task(inp)


@mcp.tool()
async def openhands_status(conv_id: str) -> dict[str, Any]:
    """Get the status of a running OpenHands conversation."""
    config = _make_config()
    client = OpenHandsClient(config)
    try:
        data = await client.get_status(conv_id)
        return {"conv_id": conv_id, "data": data}
    finally:
        await client.close()


@mcp.tool()
async def openhands_cancel(conv_id: str) -> dict[str, Any]:
    """Cancel a running OpenHands conversation."""
    config = _make_config()
    client = OpenHandsClient(config)
    try:
        await client.cancel_conversation(conv_id)
        return {"conv_id": conv_id, "cancelled": True}
    finally:
        await client.close()


@mcp.tool()
async def openhands_health() -> dict[str, Any]:
    """Check whether the OpenHands service is reachable."""
    config = _make_config()
    client = OpenHandsClient(config)
    try:
        healthy = await client.health_check()
        return {"healthy": healthy, "base_url": config.base_url}
    finally:
        await client.close()
```

- [ ] **Step 4: Register in `profiles.py`**

In `mahavishnu/mcp/tools/profiles.py`, find the `FULL_REGISTRATIONS` list and add `"openhands_tools"`:

```python
FULL_REGISTRATIONS = [
    # ... existing entries ...
    "openhands_tools",
]
```

Then in the tool-loading section (where other tool modules are imported), add:

```python
from mahavishnu.mcp.tools.openhands_tools import mcp as openhands_mcp
```

Follow the existing pattern for how other tool `mcp` objects are mounted.

- [ ] **Step 5: Run tool tests**

```bash
cd /Users/les/Projects/mahavishnu && python -m pytest tests/unit/mcp/test_openhands_tools.py -v
```

Expected: 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/mcp/tools/openhands_tools.py mahavishnu/mcp/tools/profiles.py \
        tests/unit/mcp/test_openhands_tools.py
git commit -m "feat(mcp): add openhands_run, openhands_status, openhands_cancel, openhands_health tools"
```

______________________________________________________________________

## Task 4: Settings + Security Validators

**Files:**

- Modify: `settings/mahavishnu.yaml`
- Modify: `mahavishnu/core/config.py` (add `OpenHandsSettings` Pydantic model)

**Interfaces:**

- Consumes: `MahavishnuSettings` from `mahavishnu/core/config.py`

- Produces: `MahavishnuSettings.openhands: OpenHandsSettings | None`

- [ ] **Step 1: Add `OpenHandsSettings` model to `config.py`**

In `mahavishnu/core/config.py`, add after the existing settings models:

```python
class OpenHandsSettings(BaseModel):
    """Configuration for the OpenHands autonomous agent integration."""

    base_url: str = "http://localhost:3000"
    workspace_dir: Path = Path("/tmp/openhands-workspace")
    workspace_root: Path = Path("/tmp")
    timeout_seconds: int = Field(600, ge=30, le=3600)
    poll_interval_seconds: float = Field(3.0, ge=0.5, le=30.0)
    enabled: bool = True

    @field_validator("workspace_dir", "workspace_root")
    @classmethod
    def _validate_path_is_absolute(cls, v: Path) -> Path:
        resolved = Path(v).resolve()
        return resolved

    @model_validator(mode="after")
    def _workspace_dir_inside_root(self) -> "OpenHandsSettings":
        if not str(self.workspace_dir).startswith(str(self.workspace_root)):
            raise ValueError(
                f"workspace_dir ({self.workspace_dir}) must be "
                f"inside workspace_root ({self.workspace_root})"
            )
        return self
```

Then add to `MahavishnuSettings`:

```python
openhands: OpenHandsSettings | None = None
```

- [ ] **Step 2: Add `openhands:` block to `settings/mahavishnu.yaml`**

```yaml
openhands:
  enabled: true
  base_url: "http://localhost:3000"
  workspace_root: "/tmp"
  workspace_dir: "/tmp/openhands-workspace"
  timeout_seconds: 600
  poll_interval_seconds: 3.0
```

- [ ] **Step 3: Verify settings parse correctly**

```bash
cd /Users/les/Projects/mahavishnu && python -c "
from mahavishnu.core.config import MahavishnuSettings
s = MahavishnuSettings()
print('openhands base_url:', s.openhands.base_url if s.openhands else 'None')
print('workspace_dir:', s.openhands.workspace_dir if s.openhands else 'None')
"
```

Expected: prints the configured values

- [ ] **Step 4: Add workspace_dir path containment guard test**

Append to `tests/unit/mcp/test_openhands_tools.py`:

```python
@pytest.mark.unit
def test_openhands_settings_rejects_workspace_dir_outside_root() -> None:
    from mahavishnu.core.config import OpenHandsSettings
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OpenHandsSettings(
            workspace_root="/tmp/safe",
            workspace_dir="/etc/passwd",  # outside root
        )
```

- [ ] **Step 5: Run full test suite for this track**

```bash
cd /Users/les/Projects/mahavishnu && python -m pytest tests/unit/workers/test_openhands_worker.py tests/unit/mcp/test_openhands_tools.py -v
```

Expected: all 9 tests PASS

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/core/config.py settings/mahavishnu.yaml \
        tests/unit/mcp/test_openhands_tools.py
git commit -m "feat(config): add OpenHandsSettings with path containment validator"
```
