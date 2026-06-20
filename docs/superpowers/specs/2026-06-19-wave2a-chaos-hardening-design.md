# Wave 2a: Chaos Hardening Design

**Date:** 2026-06-19
**Status:** Approved
**Scope:** Unit-level chaos tests for OpenHandsWorker and CrowTerminalAdapter

---

## Context

Wave 1 shipped `OpenHandsWorker` and `CrowTerminalAdapter` with `try/finally` httpx
lifecycle management and MHV-307/308/309 error codes. The Wave 1 spec deferred two
chaos scenarios:

- OpenHands mid-task connection drop (after `create_conversation` succeeds)
- crow-mcp server restart with active PTY sessions (orphaned session handling)

This patch validates that the existing Wave 1 production code handles these failure
modes correctly, using `respx` transport mocking so no live services are required.

---

## Global Constraints

- Python 3.13, `from __future__ import annotations` first line in every file
- `@pytest.mark.unit` on every test class and function
- `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` decorator
- Use `respx` for httpx transport mocking (already in dev dependencies)
- Use `oneiric.core.logging.get_logger` — no stdlib `logging`
- Line length ≤ 100 chars
- No `assert` in production code; `assert` is idiomatic in tests
- No new production code unless a test reveals a real gap

---

## Architecture

Two new test files. No new production files. No changes to existing production code
unless a test fails and exposes a real defect in Wave 1's error-handling paths.

```
tests/unit/
  workers/
    test_openhands_chaos.py   ← 3 scenarios for OpenHandsWorker
  terminal/
    test_crow_chaos.py        ← 2 scenarios for CrowTerminalAdapter
```

---

## 1. `tests/unit/workers/test_openhands_chaos.py`

### Scenarios

| # | Name | Injection | Expected |
|---|------|-----------|----------|
| 1 | Mid-task network drop | `create_conversation` succeeds; `poll_conversation` raises `httpx.NetworkError` | `WorkerResult.status == WorkerStatus.FAILED`; httpx client closed |
| 2 | Server 500 during polling | `poll_conversation` returns HTTP 500 | `WorkerResult.status == WorkerStatus.FAILED`; error text in `result.error` |
| 3 | Task timeout | polling loop never returns `completed` within `timeout` | `WorkerResult.status == WorkerStatus.TIMEOUT` |

### Fixture pattern

```python
from __future__ import annotations

import httpx
import pytest
import respx

from mahavishnu.workers.openhands import OpenHandsConfig, OpenHandsWorker
from mahavishnu.core.status import WorkerStatus
from pathlib import Path


@pytest.fixture()
def oh_config() -> OpenHandsConfig:
    return OpenHandsConfig(
        base_url="http://localhost:3000",
        workspace_dir=Path("/tmp/openhands-workspace"),
    )
```

### Scenario 1 — network drop after create

```python
@pytest.mark.unit
async def test_network_drop_after_create(oh_config: OpenHandsConfig) -> None:
    with respx.mock:
        respx.post("http://localhost:3000/api/conversations").mock(
            return_value=httpx.Response(200, json={"conversation_id": "conv-1"})
        )
        respx.get(respx.pattern.M(url__regex=r".*/conversations/conv-1.*")).mock(
            side_effect=httpx.NetworkError("connection reset")
        )
        worker = OpenHandsWorker(config=oh_config)
        result = await worker.execute({"prompt": "write tests", "timeout": 10})
        await worker.stop()

    assert result.status == WorkerStatus.FAILED
    assert result.error is not None
```

### Scenario 2 — 500 during polling

```python
@pytest.mark.unit
async def test_server_500_during_polling(oh_config: OpenHandsConfig) -> None:
    with respx.mock:
        respx.post("http://localhost:3000/api/conversations").mock(
            return_value=httpx.Response(200, json={"conversation_id": "conv-2"})
        )
        respx.get(respx.pattern.M(url__regex=r".*/conversations/conv-2.*")).mock(
            return_value=httpx.Response(500, text="internal server error")
        )
        worker = OpenHandsWorker(config=oh_config)
        result = await worker.execute({"prompt": "write tests", "timeout": 10})
        await worker.stop()

    assert result.status == WorkerStatus.FAILED
    assert result.error is not None
```

### Scenario 3 — timeout

```python
@pytest.mark.unit
async def test_task_timeout(oh_config: OpenHandsConfig) -> None:
    with respx.mock:
        respx.post("http://localhost:3000/api/conversations").mock(
            return_value=httpx.Response(200, json={"conversation_id": "conv-3"})
        )
        respx.get(respx.pattern.M(url__regex=r".*/conversations/conv-3.*")).mock(
            return_value=httpx.Response(200, json={"status": "running"})
        )
        worker = OpenHandsWorker(config=oh_config)
        # timeout=1 ensures the poll loop exits immediately
        result = await worker.execute({"prompt": "write tests", "timeout": 1})
        await worker.stop()

    assert result.status == WorkerStatus.TIMEOUT
```

---

## 2. `tests/unit/terminal/test_crow_chaos.py`

### Scenarios

| # | Name | Injection | Expected |
|---|------|-----------|----------|
| 1 | PTY session orphan (server restart) | `capture_output` returns HTTP 404 | `TerminalError` raised; error carries MHV-307 code |
| 2 | `close_session` network failure | `close_session` raises `httpx.NetworkError` | No exception propagates; adapter logs and continues |

### Scenario 1 — 404 on capture (orphaned PTY)

```python
from __future__ import annotations

import httpx
import pytest
import respx

from mahavishnu.terminal.adapters.crow import CrowTerminalAdapter
from mahavishnu.core.errors import TerminalError


@pytest.mark.unit
async def test_capture_output_404_raises_terminal_error() -> None:
    adapter = CrowTerminalAdapter(base_url="http://localhost:8765")
    with respx.mock:
        respx.post("http://localhost:8765/terminal/launch").mock(
            return_value=httpx.Response(200, json={"session_id": "sess-1"})
        )
        respx.get("http://localhost:8765/terminal/output/sess-1").mock(
            return_value=httpx.Response(404, json={"error": "session not found"})
        )
        session_id = await adapter.launch_session("bash", columns=80, rows=24)
        with pytest.raises(TerminalError) as exc_info:
            await adapter.capture_output(session_id)

    assert "MHV-307" in str(exc_info.value) or exc_info.value.error_code == "MHV-307"
```

### Scenario 2 — network error on close (no leak)

```python
@pytest.mark.unit
async def test_close_session_network_error_does_not_propagate() -> None:
    adapter = CrowTerminalAdapter(base_url="http://localhost:8765")
    with respx.mock:
        respx.post("http://localhost:8765/terminal/launch").mock(
            return_value=httpx.Response(200, json={"session_id": "sess-2"})
        )
        respx.delete("http://localhost:8765/terminal/sessions/sess-2").mock(
            side_effect=httpx.NetworkError("connection refused")
        )
        session_id = await adapter.launch_session("bash", columns=80, rows=24)
        # Must not raise — close_session should log and swallow network errors
        await adapter.close_session(session_id)
```

---

## Verification

After both files are written:

```bash
pytest tests/unit/workers/test_openhands_chaos.py tests/unit/terminal/test_crow_chaos.py -v
```

Expected: all 5 tests pass. If any fail, the failure identifies a real gap in Wave 1's
error-handling paths — fix the production code, then re-run.

---

## Out of Scope

- JWT auth hardening (stays in runbook)
- `tests/chaos/` directory (no separate chaos suite)
- A2AWorker (Wave 2b, separate brainstorm)
- Live-server integration tests
