# Wave 2b: A2A Worker & Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Google A2A protocol support — an outbound `A2AWorker` that routes tasks to external agents by name, and inbound Starlette routes that accept A2A tasks from external callers.

**Architecture:** `mahavishnu/a2a/card.py` holds the shared `AgentCard` Pydantic model. `mahavishnu/workers/a2a.py` contains `A2AClient` (httpx + SSE) and `A2AWorker(BaseWorker)`. `mahavishnu/a2a/server.py` builds a Starlette sub-app with three routes (`/.well-known/agent.json`, `/tasks/send`, `/tasks/sendSubscribe`) mounted on FastMCP's `http_app`. Agent URLs come exclusively from `settings/mahavishnu.yaml` — never from task input (SSRF prevention).

**Tech Stack:** Python 3.13, httpx (already a dep), Starlette (already a dep), respx (test dep), Pydantic v2, FastMCP, `asyncio.Queue` + `StreamingResponse` for SSE.

## Global Constraints

- `from __future__ import annotations` as the first non-comment line of every new file
- `@pytest.mark.unit` on every test function — no `@pytest.mark.asyncio` (asyncio_mode = "auto")
- `oneiric.core.logging.get_logger` — no stdlib `logging`, no `print()`
- `X | None` not `Optional[X]`; `list[str]` not `List[str]`
- No `assert` in production code; use `mahavishnu/core/errors.py` hierarchy
- Line length ≤ 100 chars; max 10 function args; max 15 branches; max 6 returns
- `from typing import Any` only under `TYPE_CHECKING` guard (pure annotations with `__future__`)
- All async I/O uses `httpx` — no `requests`, no `aiohttp`
- `enabled: false` default in YAML — A2A routes are not mounted unless explicitly set to `true`
- SSRF guarantee: agent URLs only from `settings/mahavishnu.yaml`, never from task input

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `mahavishnu/a2a/__init__.py` | Package init + `A2AError` exception |
| Create | `mahavishnu/a2a/card.py` | `AgentCard`, `A2ACapabilities`, `A2ASkill` Pydantic models |
| Create | `mahavishnu/a2a/server.py` | `build_a2a_router()` + three inbound route handlers |
| Create | `mahavishnu/workers/a2a.py` | `A2AAgentConfig`, `A2AClient`, `A2AWorker` |
| Create | `tests/unit/a2a/__init__.py` | Empty package marker |
| Create | `tests/unit/workers/test_a2a_worker.py` | 5 unit tests for A2AWorker |
| Create | `tests/unit/a2a/test_a2a_server.py` | 4 unit tests for A2A server routes |
| Modify | `mahavishnu/core/errors.py` | Add `A2A_AGENT_NOT_FOUND = "MHV-310"`, `A2A_AGENT_ERROR = "MHV-311"` |
| Modify | `mahavishnu/core/config.py` | Add `A2ACapabilitiesSettings`, `A2ACardSettings`, `A2AAgentEntry`, `A2ASettings`; add `a2a` field to `MahavishnuSettings` |
| Modify | `mahavishnu/workers/registry.py` | Add A2A `WorkerConfig` entry |
| Modify | `mahavishnu/mcp/bootstrap.py` | Conditional A2A mount in `_register_optional_tools` |
| Modify | `settings/mahavishnu.yaml` | Add `a2a:` config block |

---

## Task 1: Error Codes + `mahavishnu/a2a/` Package + AgentCard

**Files:**
- Modify: `mahavishnu/core/errors.py` (find the end of the `# External integration errors` block, currently ends at `OPENHANDS_TASK_FAILED = "MHV-309"`)
- Create: `mahavishnu/a2a/__init__.py`
- Create: `mahavishnu/a2a/card.py`

**Interfaces:**
- Produces: `ErrorCode.A2A_AGENT_NOT_FOUND` (`"MHV-310"`), `ErrorCode.A2A_AGENT_ERROR` (`"MHV-311"`)
- Produces: `A2AError(Exception)` from `mahavishnu.a2a`
- Produces: `AgentCard`, `A2ACapabilities`, `A2ASkill` from `mahavishnu.a2a.card`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_a2a_foundation.py  (temporary test file, deleted after Task 1)
from __future__ import annotations

import pytest

from mahavishnu.core.errors import ErrorCode


@pytest.mark.unit
def test_a2a_error_codes_exist() -> None:
    assert ErrorCode.A2A_AGENT_NOT_FOUND == "MHV-310"
    assert ErrorCode.A2A_AGENT_ERROR == "MHV-311"


@pytest.mark.unit
def test_agent_card_imports() -> None:
    from mahavishnu.a2a import A2AError
    from mahavishnu.a2a.card import AgentCard, A2ACapabilities, A2ASkill

    card = AgentCard(
        name="Test",
        description="Test agent",
        url="http://localhost",
        version="1.0.0",
    )
    assert card.capabilities.streaming is False
    assert isinstance(A2AError("test"), Exception)
    _ = A2ASkill(id="s1", name="Search", description="Searches things")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_a2a_foundation.py -v
```

Expected: `FAILED — ImportError: cannot import name 'A2A_AGENT_NOT_FOUND' from 'mahavishnu.core.errors'`

- [ ] **Step 3: Add error codes to `mahavishnu/core/errors.py`**

Find the line `OPENHANDS_TASK_FAILED = "MHV-309"` and add immediately after:

```python
    A2A_AGENT_NOT_FOUND = "MHV-310"   # agent name not in registry
    A2A_AGENT_ERROR = "MHV-311"        # remote agent returned error or stream failed
```

- [ ] **Step 4: Create `mahavishnu/a2a/__init__.py`**

```python
from __future__ import annotations


class A2AError(Exception):
    """Raised when an A2A protocol interaction fails unrecoverably."""
```

- [ ] **Step 5: Create `mahavishnu/a2a/card.py`**

```python
from __future__ import annotations

from pydantic import BaseModel


class A2ACapabilities(BaseModel):
    streaming: bool = False
    pushNotifications: bool = False  # noqa: N815 — A2A protocol field name


class A2ASkill(BaseModel):
    id: str
    name: str
    description: str


class AgentCard(BaseModel):
    name: str
    description: str
    url: str
    version: str
    capabilities: A2ACapabilities = A2ACapabilities()
    skills: list[A2ASkill] = []
```

- [ ] **Step 6: Run test to verify it passes**

```bash
pytest tests/unit/test_a2a_foundation.py -v
```

Expected: `2 passed`

- [ ] **Step 7: Delete the temporary test file**

```bash
rm tests/unit/test_a2a_foundation.py
```

- [ ] **Step 8: Commit**

```bash
git add mahavishnu/core/errors.py mahavishnu/a2a/__init__.py mahavishnu/a2a/card.py
git commit -m "feat(a2a): add MHV-310/311 error codes and AgentCard model"
```

---

## Task 2: Settings Models + YAML

**Files:**
- Modify: `mahavishnu/core/config.py` — add 4 Pydantic models and `a2a` field to `MahavishnuSettings`
- Modify: `settings/mahavishnu.yaml` — add `a2a:` block

**Interfaces:**
- Consumes: `A2ACapabilitiesSettings`, `A2ACardSettings`, `A2AAgentEntry`, `A2ASettings` are new — no prior tasks define them
- Produces: `MahavishnuSettings.a2a: A2ASettings | None` — consumed by Task 3 (worker construction) and Task 4 (server mount)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_a2a_config.py`:

```python
from __future__ import annotations

import pytest

from mahavishnu.core.config import A2ASettings, A2AAgentEntry, MahavishnuSettings


@pytest.mark.unit
def test_a2a_settings_default_disabled() -> None:
    settings = A2ASettings()
    assert settings.enabled is False
    assert settings.agents == []


@pytest.mark.unit
def test_a2a_agent_entry_api_key_optional() -> None:
    entry = A2AAgentEntry(name="coder", url="http://coder.example.com")
    assert entry.api_key_env is None


@pytest.mark.unit
def test_mahavishnu_settings_has_a2a_field() -> None:
    # MahavishnuSettings must accept a2a=None without error
    s = MahavishnuSettings(a2a=None)
    assert s.a2a is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_a2a_config.py -v
```

Expected: `FAILED — ImportError: cannot import name 'A2ASettings' from 'mahavishnu.core.config'`

- [ ] **Step 3: Add Pydantic models to `mahavishnu/core/config.py`**

Find the `OpenHandsSettings` class (around line 945) and add the four new models **before** it:

```python
class A2ACapabilitiesSettings(BaseModel):
    """Capabilities advertised in our outbound A2A agent card."""

    streaming: bool = True
    pushNotifications: bool = False  # noqa: N815


class A2ACardSettings(BaseModel):
    """Fields used to build the /.well-known/agent.json response."""

    name: str = "Mahavishnu"
    description: str = "Bodai ecosystem orchestrator"
    version: str = "0.7.x"
    capabilities: A2ACapabilitiesSettings = A2ACapabilitiesSettings()
    skills: list[dict[str, str]] = []


class A2AAgentEntry(BaseModel):
    """One entry in the outbound agent registry (from settings/mahavishnu.yaml)."""

    name: str
    url: str
    description: str = ""
    api_key_env: str | None = None  # env var name; resolved to actual value at runtime
```

```python
class A2ASettings(BaseModel):
    """Top-level A2A configuration block."""

    enabled: bool = False
    card: A2ACardSettings = A2ACardSettings()
    agents: list[A2AAgentEntry] = []
```

- [ ] **Step 4: Add `a2a` field to `MahavishnuSettings`**

Find `MahavishnuSettings` class (around line 1666) and find the `openhands: OpenHandsSettings | None = None` field. Add immediately after it:

```python
    a2a: A2ASettings | None = None
```

- [ ] **Step 5: Update `settings/mahavishnu.yaml`**

Find the end of the YAML file and add the following block (keep `enabled: false`):

```yaml
# A2A (Agent-to-Agent) protocol — Google A2A spec
# Set enabled: true and add agent entries to activate
a2a:
  enabled: false
  card:
    name: "Mahavishnu"
    description: "Bodai ecosystem orchestrator"
    version: "0.7.x"
    capabilities:
      streaming: true
      pushNotifications: false
    skills: []
  agents: []
  # Example agent entry:
  # agents:
  #   - name: "codegen-agent"
  #     url: "http://agent.example.com"
  #     description: "External code generation agent"
  #     api_key_env: "CODEGEN_API_KEY"
```

- [ ] **Step 6: Run test to verify it passes**

```bash
pytest tests/unit/test_a2a_config.py -v
```

Expected: `3 passed`

- [ ] **Step 7: Delete temporary test file**

```bash
rm tests/unit/test_a2a_config.py
```

- [ ] **Step 8: Commit**

```bash
git add mahavishnu/core/config.py settings/mahavishnu.yaml
git commit -m "feat(a2a): add A2ASettings config models and YAML block"
```

---

## Task 3: A2AWorker + A2AClient + Tests + Registry

**Files:**
- Create: `mahavishnu/workers/a2a.py`
- Create: `tests/unit/workers/test_a2a_worker.py`
- Modify: `mahavishnu/workers/registry.py` — add A2A `WorkerConfig` entry

**Interfaces:**
- Consumes: `ErrorCode.A2A_AGENT_NOT_FOUND` / `A2A_AGENT_ERROR` (Task 1), `AgentCard`, `A2ACapabilities` (Task 1), `A2ASettings`, `A2AAgentEntry` (Task 2), `BaseWorker`, `WorkerResult` (from `mahavishnu.workers.base`), `WorkerStatus` (from `mahavishnu.core.status`)
- Produces: `A2AAgentConfig` dataclass, `A2AClient` class, `A2AWorker(BaseWorker)` from `mahavishnu.workers.a2a`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/workers/test_a2a_worker.py`:

```python
from __future__ import annotations

import pytest
import httpx
import respx

from mahavishnu.core.status import WorkerStatus
from mahavishnu.workers.a2a import A2AAgentConfig, A2AWorker


def _make_worker(*names_urls: tuple[str, str]) -> A2AWorker:
    registry = {
        name: A2AAgentConfig(name=name, url=url)
        for name, url in names_urls
    }
    return A2AWorker(agent_configs=registry)


# ── Scenario 1: Happy path SSE ───────────────────────────────────────────────

@pytest.mark.unit
async def test_happy_path_sse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Agent supports streaming; sendSubscribe returns working→completed."""
    card_json = {
        "name": "coder",
        "description": "codes things",
        "url": "http://coder.example.com",
        "version": "1.0.0",
        "capabilities": {"streaming": True, "pushNotifications": False},
    }
    sse_body = (
        'data: {"id": "t1", "status": {"state": "working"}, "final": false}\n\n'
        'data: {"id": "t1", "status": {"state": "completed"}, '
        '"artifacts": [{"parts": [{"type": "text", "text": "hello world"}]}], '
        '"final": true}\n\n'
    )

    with respx.mock:
        respx.get("http://coder.example.com/.well-known/agent.json").mock(
            return_value=httpx.Response(200, json=card_json)
        )
        respx.post("http://coder.example.com/tasks/sendSubscribe").mock(
            return_value=httpx.Response(
                200, text=sse_body, headers={"content-type": "text/event-stream"}
            )
        )
        worker = _make_worker(("coder", "http://coder.example.com"))
        result = await worker.execute({"agent": "coder", "prompt": "say hello"})

    assert result.status == WorkerStatus.COMPLETED
    assert result.output == "hello world"


# ── Scenario 2: Non-streaming fallback ───────────────────────────────────────

@pytest.mark.unit
async def test_non_streaming_fallback() -> None:
    """Agent does NOT support streaming; falls back to /tasks/send."""
    card_json = {
        "name": "simple",
        "description": "simple agent",
        "url": "http://simple.example.com",
        "version": "1.0.0",
        "capabilities": {"streaming": False, "pushNotifications": False},
    }
    task_response = {
        "id": "t2",
        "status": {"state": "completed"},
        "artifacts": [{"parts": [{"type": "text", "text": "result text"}]}],
        "final": True,
    }

    with respx.mock:
        respx.get("http://simple.example.com/.well-known/agent.json").mock(
            return_value=httpx.Response(200, json=card_json)
        )
        respx.post("http://simple.example.com/tasks/send").mock(
            return_value=httpx.Response(200, json=task_response)
        )
        worker = _make_worker(("simple", "http://simple.example.com"))
        result = await worker.execute({"agent": "simple", "prompt": "run task"})

    assert result.status == WorkerStatus.COMPLETED


# ── Scenario 3: Unknown agent name ───────────────────────────────────────────

@pytest.mark.unit
async def test_unknown_agent_name() -> None:
    """Agent name not in registry returns FAILED with MHV-310."""
    worker = _make_worker(("known-agent", "http://known.example.com"))
    result = await worker.execute({"agent": "ghost-agent", "prompt": "do something"})

    assert result.status == WorkerStatus.FAILED
    assert result.error_code == "MHV-310"


# ── Scenario 4: Remote agent SSE error event ─────────────────────────────────

@pytest.mark.unit
async def test_remote_agent_sse_error_event() -> None:
    """Remote agent emits failed final event; worker returns FAILED with MHV-311."""
    card_json = {
        "name": "erring",
        "description": "always fails",
        "url": "http://erring.example.com",
        "version": "1.0.0",
        "capabilities": {"streaming": True, "pushNotifications": False},
    }
    sse_body = (
        'data: {"id": "t3", "status": {"state": "failed", "message": '
        '"quota exceeded"}, "final": true}\n\n'
    )

    with respx.mock:
        respx.get("http://erring.example.com/.well-known/agent.json").mock(
            return_value=httpx.Response(200, json=card_json)
        )
        respx.post("http://erring.example.com/tasks/sendSubscribe").mock(
            return_value=httpx.Response(
                200, text=sse_body, headers={"content-type": "text/event-stream"}
            )
        )
        worker = _make_worker(("erring", "http://erring.example.com"))
        result = await worker.execute({"agent": "erring", "prompt": "run task"})

    assert result.status == WorkerStatus.FAILED
    assert result.error_code == "MHV-311"


# ── Scenario 5: Card fetch 503 ────────────────────────────────────────────────

@pytest.mark.unit
async def test_card_fetch_503() -> None:
    """Agent card endpoint returns 503; worker returns FAILED."""
    with respx.mock:
        respx.get("http://down.example.com/.well-known/agent.json").mock(
            return_value=httpx.Response(503, text="service unavailable")
        )
        worker = _make_worker(("down", "http://down.example.com"))
        result = await worker.execute({"agent": "down", "prompt": "ping"})

    assert result.status == WorkerStatus.FAILED
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/workers/test_a2a_worker.py -v
```

Expected: `FAILED — ImportError: cannot import name 'A2AAgentConfig' from 'mahavishnu.workers.a2a'`

- [ ] **Step 3: Create `mahavishnu/workers/a2a.py`**

```python
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
from oneiric.core.logging import get_logger

from mahavishnu.a2a import A2AError
from mahavishnu.a2a.card import AgentCard, A2ACapabilities, A2ASkill  # noqa: F401
from mahavishnu.core.errors import ErrorCode
from mahavishnu.core.status import WorkerStatus

from .base import BaseWorker, WorkerResult

if TYPE_CHECKING:
    from typing import Any

logger = get_logger(__name__)


@dataclass
class A2AAgentConfig:
    """Resolved agent entry — URL is always from settings, never from task input."""

    name: str
    url: str
    description: str = ""
    api_key: str | None = None  # already resolved from api_key_env at construction


# ─── helpers ──────────────────────────────────────────────────────────────────


def _build_task_payload(task_id: str, prompt: str) -> dict[str, Any]:
    return {
        "id": task_id,
        "message": {"role": "user", "parts": [{"type": "text", "text": prompt}]},
    }


def _event_to_result(task_id: str, event: dict[str, Any]) -> WorkerResult:
    state = event.get("status", {}).get("state", "failed")
    if state == "completed":
        artifacts = event.get("artifacts", [])
        output = artifacts[0].get("parts", [{}])[0].get("text", "") if artifacts else ""
        return WorkerResult(
            worker_id=task_id,
            status=WorkerStatus.COMPLETED,
            output=output,
            metadata={"worker_type": "a2a"},
        )
    return WorkerResult(
        worker_id=task_id,
        status=WorkerStatus.FAILED,
        error=event.get("status", {}).get("message", "A2A task failed"),
        error_code=ErrorCode.A2A_AGENT_ERROR,
        metadata={"worker_type": "a2a"},
    )


# ─── A2AClient ────────────────────────────────────────────────────────────────


class A2AClient:
    """Thin httpx wrapper for the Google A2A protocol."""

    _CARD_TIMEOUT: float = 10.0
    _TASK_TIMEOUT: float = 600.0

    def __init__(self, config: A2AAgentConfig) -> None:
        self._config = config
        headers: dict[str, str] = {}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        self._http = httpx.AsyncClient(
            base_url=config.url,
            headers=headers,
            timeout=httpx.Timeout(self._TASK_TIMEOUT),
        )

    async def fetch_card(self) -> AgentCard:
        """GET /.well-known/agent.json — raises httpx.HTTPStatusError on non-2xx."""
        resp = await self._http.get(
            "/.well-known/agent.json",
            timeout=self._CARD_TIMEOUT,
        )
        resp.raise_for_status()
        return AgentCard.model_validate(resp.json())

    async def send_task(self, task_id: str, prompt: str) -> dict[str, Any]:
        """POST /tasks/send — synchronous, returns the final task object."""
        resp = await self._http.post(
            "/tasks/send",
            json=_build_task_payload(task_id, prompt),
        )
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    async def send_task_subscribe(self, task_id: str, prompt: str) -> WorkerResult:
        """POST /tasks/sendSubscribe — SSE stream; returns WorkerResult on final event."""
        async with self._http.stream(
            "POST",
            "/tasks/sendSubscribe",
            json=_build_task_payload(task_id, prompt),
            headers={"Accept": "text/event-stream"},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[5:].strip())
                if event.get("final"):
                    return _event_to_result(task_id, event)
        raise A2AError("SSE stream closed without a final event")

    async def close(self) -> None:
        await self._http.aclose()


# ─── A2AWorker ────────────────────────────────────────────────────────────────


class A2AWorker(BaseWorker):
    """Routes tasks to external A2A-compliant agents by name.

    Agent name → URL resolution is from the configured registry only.
    URLs never come from task input (SSRF prevention).
    """

    def __init__(self, agent_configs: dict[str, A2AAgentConfig]) -> None:
        super().__init__(worker_type="a2a")
        self._registry = agent_configs  # name → A2AAgentConfig

    async def start(self) -> str:
        self._status = WorkerStatus.RUNNING
        return "a2a"

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        agent_name: str = task.get("agent", "")
        prompt: str = task.get("prompt", "")

        if agent_name not in self._registry:
            return WorkerResult(
                worker_id="a2a",
                status=WorkerStatus.FAILED,
                error=f"Unknown A2A agent: {agent_name!r}",
                error_code=ErrorCode.A2A_AGENT_NOT_FOUND,
                metadata={"worker_type": "a2a"},
            )

        config = self._registry[agent_name]
        client = A2AClient(config)
        task_id = str(uuid.uuid4())

        try:
            card = await client.fetch_card()
            if card.capabilities.streaming:
                return await client.send_task_subscribe(task_id, prompt)
            data = await client.send_task(task_id, prompt)
            return _event_to_result(task_id, data)
        except Exception as e:
            logger.exception("A2A task failed for agent %r", agent_name)
            return WorkerResult(
                worker_id=task_id,
                status=WorkerStatus.FAILED,
                error=str(e),
                error_code=ErrorCode.A2A_AGENT_ERROR,
                metadata={"worker_type": "a2a", "agent": agent_name},
            )
        finally:
            await client.close()

    async def stop(self) -> None:
        self._status = WorkerStatus.COMPLETED

    async def status(self) -> WorkerStatus:
        return self._status

    async def get_progress(self) -> dict[str, Any]:
        return {"status": self._status.value, "worker_type": self.worker_type}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/workers/test_a2a_worker.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Add registry entry to `mahavishnu/workers/registry.py`**

Find the GATEWAY entries (currently `openhands` is the last one, ending around line 525 in the file). Add immediately after the `openhands` entry:

```python
    "a2a": WorkerConfig(
        name="A2A Gateway",
        worker_type="a2a",
        command="",  # GATEWAY worker — HTTP/SSE API, no shell command
        category=WorkerCategory.GATEWAY,
        description=(
            "Google A2A protocol — routes tasks to external agents by name. "
            "Agent URLs resolved from settings only (SSRF-safe)."
        ),
        requires_tool=None,
    ),
```

- [ ] **Step 6: Run the registry guard test to confirm no duplicate codes**

```bash
pytest tests/unit/test_error_codes.py tests/unit/test_worker_registry.py -v
```

Expected: all passing (the guard tests should still pass with the new entry)

- [ ] **Step 7: Commit**

```bash
git add mahavishnu/workers/a2a.py mahavishnu/workers/registry.py \
        tests/unit/workers/test_a2a_worker.py
git commit -m "feat(a2a): add A2AClient, A2AWorker, and registry entry"
```

---

## Task 4: A2A Server + Tests + Bootstrap Mount

**Files:**
- Create: `tests/unit/a2a/__init__.py`
- Create: `mahavishnu/a2a/server.py`
- Create: `tests/unit/a2a/test_a2a_server.py`
- Modify: `mahavishnu/mcp/bootstrap.py` — add A2A conditional mount in `_register_optional_tools`

**Interfaces:**
- Consumes: `AgentCard`, `A2ACapabilities`, `A2ASkill` from `mahavishnu.a2a.card` (Task 1), `A2ASettings` from `mahavishnu.core.config` (Task 2)
- Produces: `build_a2a_router(settings, worker_manager) -> Starlette` from `mahavishnu.a2a.server`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/a2a/__init__.py` (empty):

```python
```

Create `tests/unit/a2a/test_a2a_server.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from mahavishnu.a2a.server import build_a2a_router
from mahavishnu.core.config import A2ASettings
from mahavishnu.core.status import WorkerStatus
from mahavishnu.workers.base import WorkerResult

if TYPE_CHECKING:
    pass


def _make_app(worker_result: WorkerResult) -> TestClient:
    """Build a TestClient with a mock worker_manager."""
    settings = A2ASettings()
    settings.card.capabilities.streaming = True

    worker_manager = MagicMock()
    worker_manager.execute_task = AsyncMock(return_value=worker_result)

    app = build_a2a_router(settings, worker_manager)
    return TestClient(app, raise_server_exceptions=True)


# ── Scenario 1: GET /.well-known/agent.json ───────────────────────────────────

@pytest.mark.unit
def test_agent_card_returns_valid_json() -> None:
    client = _make_app(
        WorkerResult(worker_id="x", status=WorkerStatus.COMPLETED, output="")
    )
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Mahavishnu"
    assert data["capabilities"]["streaming"] is True


# ── Scenario 2: POST /tasks/send success ──────────────────────────────────────

@pytest.mark.unit
def test_tasks_send_success() -> None:
    result = WorkerResult(
        worker_id="t1",
        status=WorkerStatus.COMPLETED,
        output="task done",
    )
    client = _make_app(result)

    resp = client.post(
        "/tasks/send",
        json={
            "id": "t1",
            "message": {"role": "user", "parts": [{"type": "text", "text": "do work"}]},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"]["state"] == "completed"
    assert data["id"] == "t1"


# ── Scenario 3: POST /tasks/sendSubscribe returns SSE ────────────────────────

@pytest.mark.unit
def test_tasks_send_subscribe_streams_sse() -> None:
    result = WorkerResult(
        worker_id="t2",
        status=WorkerStatus.COMPLETED,
        output="streamed result",
    )
    client = _make_app(result)

    with client.stream(
        "POST",
        "/tasks/sendSubscribe",
        json={
            "id": "t2",
            "message": {"role": "user", "parts": [{"type": "text", "text": "stream me"}]},
        },
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        body = resp.text
    # Must contain at least one SSE data line
    assert "data:" in body
    # Must contain the final completed event
    assert '"completed"' in body


# ── Scenario 4: POST /tasks/send — worker failure ────────────────────────────

@pytest.mark.unit
def test_tasks_send_worker_failure() -> None:
    result = WorkerResult(
        worker_id="t3",
        status=WorkerStatus.FAILED,
        error="ran out of memory",
    )
    client = _make_app(result)

    resp = client.post(
        "/tasks/send",
        json={
            "id": "t3",
            "message": {"role": "user", "parts": [{"type": "text", "text": "risky task"}]},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"]["state"] == "failed"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/a2a/test_a2a_server.py -v
```

Expected: `FAILED — ImportError: cannot import name 'build_a2a_router' from 'mahavishnu.a2a.server'`

- [ ] **Step 3: Create `mahavishnu/a2a/server.py`**

```python
from __future__ import annotations

import asyncio
import json
import uuid
from typing import TYPE_CHECKING

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from mahavishnu.a2a.card import A2ACapabilities, A2ASkill, AgentCard
from mahavishnu.core.status import WorkerStatus

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from typing import Any

    from mahavishnu.core.config import A2ASettings
    from mahavishnu.workers.base import WorkerResult


# ─── private helpers ──────────────────────────────────────────────────────────


def _get_version() -> str:
    try:
        from importlib.metadata import version

        return version("mahavishnu")
    except Exception:  # noqa: BLE001
        return "0.0.0"


def _extract_prompt(task_data: dict[str, Any]) -> str:
    """Extract the first text part from a Google A2A task message."""
    parts = task_data.get("message", {}).get("parts", [])
    return next((p.get("text", "") for p in parts if p.get("type") == "text"), "")


def _result_to_a2a(task_id: str, result: WorkerResult) -> dict[str, Any]:
    if result.status == WorkerStatus.COMPLETED:
        return {
            "id": task_id,
            "status": {"state": "completed"},
            "artifacts": [{"parts": [{"type": "text", "text": result.output or ""}]}],
            "final": True,
        }
    return {
        "id": task_id,
        "status": {"state": "failed", "message": result.error or "Worker failed"},
        "final": True,
    }


def _error_to_a2a(task_id: str, error: str) -> dict[str, Any]:
    return {
        "id": task_id,
        "status": {"state": "failed", "message": error},
        "final": True,
    }


def _sse_event(
    task_id: str,
    state: str,
    *,
    final: bool,
    result: WorkerResult | None = None,
    error: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "id": task_id,
        "status": {"state": state},
        "final": final,
    }
    if result is not None:
        payload["artifacts"] = [
            {"parts": [{"type": "text", "text": result.output or ""}]}
        ]
    if error:
        payload["status"]["message"] = error
    return f"data: {json.dumps(payload)}\n\n"


# ─── route factories ──────────────────────────────────────────────────────────


def _agent_card_handler(settings: A2ASettings):  # type: ignore[no-untyped-def]
    async def handler(request: Request) -> JSONResponse:
        card = AgentCard(
            name=settings.card.name,
            description=settings.card.description,
            url=str(request.base_url).rstrip("/"),
            version=_get_version(),
            capabilities=A2ACapabilities(
                streaming=settings.card.capabilities.streaming,
                pushNotifications=settings.card.capabilities.pushNotifications,
            ),
            skills=[A2ASkill(**s) for s in settings.card.skills],
        )
        return JSONResponse(card.model_dump())

    return handler


def _tasks_send_handler(worker_manager: Any):  # type: ignore[no-untyped-def]
    async def handler(request: Request) -> JSONResponse:
        task_data = await request.json()
        task_id: str = task_data.get("id", str(uuid.uuid4()))
        prompt = _extract_prompt(task_data)
        try:
            result = await worker_manager.execute_task({"prompt": prompt})
            return JSONResponse(_result_to_a2a(task_id, result))
        except Exception as e:  # noqa: BLE001
            return JSONResponse(_error_to_a2a(task_id, str(e)))

    return handler


def _tasks_send_subscribe_handler(worker_manager: Any):  # type: ignore[no-untyped-def]
    async def handler(request: Request) -> StreamingResponse:
        task_data = await request.json()
        task_id: str = task_data.get("id", str(uuid.uuid4()))
        prompt = _extract_prompt(task_data)
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def run_and_emit() -> None:
            await queue.put(_sse_event(task_id, "working", final=False))
            try:
                result = await worker_manager.execute_task({"prompt": prompt})
                await queue.put(
                    _sse_event(task_id, "completed", final=True, result=result)
                )
            except Exception as e:  # noqa: BLE001
                await queue.put(_sse_event(task_id, "failed", final=True, error=str(e)))
            finally:
                await queue.put(None)

        asyncio.create_task(run_and_emit())

        async def event_generator() -> AsyncGenerator[str, None]:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    return handler


# ─── public factory ───────────────────────────────────────────────────────────


def build_a2a_router(settings: A2ASettings, worker_manager: Any) -> Starlette:
    """Build a Starlette sub-application exposing Google A2A routes."""
    return Starlette(
        routes=[
            Route(
                "/.well-known/agent.json",
                endpoint=_agent_card_handler(settings),
                methods=["GET"],
            ),
            Route(
                "/tasks/send",
                endpoint=_tasks_send_handler(worker_manager),
                methods=["POST"],
            ),
            Route(
                "/tasks/sendSubscribe",
                endpoint=_tasks_send_subscribe_handler(worker_manager),
                methods=["POST"],
            ),
        ]
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/a2a/test_a2a_server.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Add the A2A mount to `mahavishnu/mcp/bootstrap.py`**

In `_register_optional_tools`, find the end of the `if "_register_openhands_tools" in methods_set:` block (around line 218) and add immediately after it:

```python
    a2a_config = getattr(server.app.config, "a2a", None)
    if a2a_config and a2a_config.enabled:
        try:
            from ..a2a.server import build_a2a_router

            worker_manager = getattr(server.app, "_worker_manager", None)
            a2a_app = build_a2a_router(a2a_config, worker_manager)
            server.server.http_app.mount("/", a2a_app)
            logger.info("Mounted A2A server routes (/.well-known/agent.json, /tasks/send, /tasks/sendSubscribe)")
        except Exception as exc:  # noqa: BLE001 - defensive: A2A may be unavailable
            logger.warning("A2A server routes not mounted: %s", exc)
```

- [ ] **Step 6: Run the full A2A test suite**

```bash
pytest tests/unit/workers/test_a2a_worker.py tests/unit/a2a/test_a2a_server.py -v
```

Expected: `9 passed` (5 worker + 4 server)

- [ ] **Step 7: Run the broader unit suite to check for regressions**

```bash
pytest tests/unit/ -m unit -x -q --timeout=60
```

Expected: all passing (no regressions)

- [ ] **Step 8: Commit**

```bash
git add mahavishnu/a2a/server.py tests/unit/a2a/__init__.py \
        tests/unit/a2a/test_a2a_server.py mahavishnu/mcp/bootstrap.py
git commit -m "feat(a2a): add inbound A2A server routes and bootstrap mount"
```

---

## Final Verification

After all 4 tasks are complete, run:

```bash
pytest tests/unit/workers/test_a2a_worker.py tests/unit/a2a/test_a2a_server.py -v
```

Expected: `9 passed`

```bash
pytest tests/unit/ -m unit -q --timeout=60 --ignore=tests/unit/test_a2a_foundation.py
```

Expected: no regressions from pre-Wave-2b baseline.

```bash
python -c "
from mahavishnu.a2a.card import AgentCard
from mahavishnu.a2a.server import build_a2a_router
from mahavishnu.workers.a2a import A2AWorker, A2AAgentConfig
from mahavishnu.core.errors import ErrorCode
print('MHV-310:', ErrorCode.A2A_AGENT_NOT_FOUND)
print('MHV-311:', ErrorCode.A2A_AGENT_ERROR)
print('All imports OK')
"
```

Expected: prints `All imports OK` without errors.
