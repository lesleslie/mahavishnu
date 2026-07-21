---
status: active
role: implementation
topic: routing-composition
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
---

# Wave 2b: A2A Worker & Server Design

## **Date:** 2026-06-19 **Status:** Approved <!-- legacy status: Approved — see YAML frontmatter --> **Scope:** Google A2A protocol — outbound A2AWorker (SSE client) + inbound A2A server routes

## Context

Mahavishnu needs to participate in the emerging Google A2A (Agent-to-Agent) ecosystem as
a full peer: routing tasks outward to external A2A-compliant agents, and accepting tasks
inbound from other agents. Wave 2a proved the chaos-hardening of Wave 1's workers; Wave 2b
adds the protocol layer that connects Mahavishnu to the broader agent ecosystem.

**Deferred from Wave 1**: A2AWorker was flagged as "underspecified + SSRF risk." Wave 2b
resolves both: the SSRF risk is eliminated by name→URL resolution from settings (URLs
never come from task input), and the spec now fully defines the protocol flow.

______________________________________________________________________

## Global Constraints

- Python 3.13, `from __future__ import annotations` first line in every file
- `@pytest.mark.unit` on every test class and function
- `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` decorator
- `oneiric.core.logging.get_logger` — no stdlib `logging`, no `print()`
- Line length ≤ 100 chars; max 10 function args; max 15 branches; max 6 returns
- No `assert` in production code — use the error hierarchy in `mahavishnu/core/errors.py`
- `X | None` not `Optional[X]`; `list[str]` not `List[str]`; `pathlib.Path` for paths
- All new async I/O uses `httpx` (already a dependency) — no `requests`, no `aiohttp`
- `enabled: false` default — A2A routes are not mounted unless explicitly opted in
- SSRF guarantee: agent URLs come only from `settings/mahavishnu.yaml`, never from task input

______________________________________________________________________

## Architecture

Three new units with clear ownership:

```
mahavishnu/a2a/card.py        — AgentCard Pydantic model (shared by client + server)
mahavishnu/a2a/server.py      — Inbound A2A routes (agent card + tasks/send + tasks/sendSubscribe)
mahavishnu/workers/a2a.py     — A2AClient + A2AWorker (outbound)
```

**Outbound flow:**

```
task dict {"agent": "codegen-agent", "prompt": "..."}
→ name lookup in A2ARegistry (from settings) → A2AAgentConfig with base URL
→ GET {url}/.well-known/agent.json → AgentCard (capability check)
→ if streaming: POST {url}/tasks/sendSubscribe → SSE event stream → WorkerResult
→ if not streaming: POST {url}/tasks/send → JSON response → WorkerResult
```

**Inbound flow:**

```
POST /tasks/sendSubscribe (from external agent)
→ asyncio.Queue[str | None] per task
→ asyncio.create_task(run_and_emit(queue, worker_manager, task_data))
→ StreamingResponse(event_generator(queue), media_type="text/event-stream")
→ SSE events: working → completed/failed
```

______________________________________________________________________

## 1. Settings & Configuration

### 1.1 `settings/mahavishnu.yaml` — new `a2a:` block

```yaml
a2a:
  enabled: false                       # opt-in; routes not mounted when false
  card:
    name: "Mahavishnu"
    description: "Bodai ecosystem orchestrator"
    version: "0.7.x"                   # populated from importlib.metadata at runtime
    capabilities:
      streaming: true
      pushNotifications: false
    skills: []
  agents: []
  # Operator adds entries:
  # agents:
  #   - name: "codegen-agent"
  #     url: "http://agent.example.com"
  #     description: "External code generation agent"
  #     api_key_env: "CODEGEN_API_KEY"   # env var name, not value
```

### 1.2 `mahavishnu/core/config.py` — new Pydantic models

```python
class A2ACapabilitiesSettings(BaseModel):
    streaming: bool = True
    pushNotifications: bool = False

class A2ACardSettings(BaseModel):
    name: str = "Mahavishnu"
    description: str = "Bodai ecosystem orchestrator"
    version: str = "0.7.x"
    capabilities: A2ACapabilitiesSettings = A2ACapabilitiesSettings()
    skills: list[dict[str, str]] = []

class A2AAgentEntry(BaseModel):
    name: str
    url: str
    description: str = ""
    api_key_env: str | None = None  # env var name; resolved to value at runtime

class A2ASettings(BaseModel):
    enabled: bool = False
    card: A2ACardSettings = A2ACardSettings()
    agents: list[A2AAgentEntry] = []

# On MahavishnuSettings:
a2a: A2ASettings | None = None
```

______________________________________________________________________

## 2. Shared Model — `mahavishnu/a2a/card.py`

```python
from __future__ import annotations
from pydantic import BaseModel

class A2ACapabilities(BaseModel):
    streaming: bool = False
    pushNotifications: bool = False

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

______________________________________________________________________

## 3. A2AWorker — `mahavishnu/workers/a2a.py`

### 3.1 Config dataclass

```python
@dataclass
class A2AAgentConfig:
    name: str
    url: str              # base URL, from settings — never from task input
    description: str = ""
    api_key: str | None = None   # resolved from api_key_env at construction
```

### 3.2 A2AClient

Thin httpx wrapper. One instance per agent interaction.

```python
class A2AClient:
    _CARD_TIMEOUT = 10.0
    _TASK_TIMEOUT = 600.0

    def __init__(self, config: A2AAgentConfig) -> None:
        self._config = config
        headers = {}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        self._http = httpx.AsyncClient(
            base_url=config.url,
            headers=headers,
            timeout=httpx.Timeout(self._TASK_TIMEOUT),
        )

    async def fetch_card(self) -> AgentCard:
        """GET /.well-known/agent.json — raises httpx.HTTPError on failure."""
        resp = await self._http.get(
            "/.well-known/agent.json",
            timeout=self._CARD_TIMEOUT,
        )
        resp.raise_for_status()
        return AgentCard.model_validate(resp.json())

    async def send_task(self, task_id: str, prompt: str) -> dict[str, Any]:
        """POST /tasks/send — synchronous, returns final task object."""
        resp = await self._http.post(
            "/tasks/send",
            json=_build_task_payload(task_id, prompt),
        )
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    async def send_task_subscribe(self, task_id: str, prompt: str) -> WorkerResult:
        """POST /tasks/sendSubscribe — SSE stream, returns WorkerResult on final event."""
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
        raise A2AError("SSE stream closed without final event")

    async def close(self) -> None:
        await self._http.aclose()
```

Helper functions (module-level, not methods):

```python
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
```

### 3.3 A2AWorker

```python
class A2AWorker(BaseWorker):
    """Routes tasks to external A2A-compliant agents by name.

    Agent name is resolved to a URL via the configured registry —
    URLs never come from task input (SSRF prevention).
    """

    def __init__(self, agent_configs: dict[str, A2AAgentConfig]) -> None:
        super().__init__(worker_type="a2a")
        self._registry = agent_configs  # name → config

    async def start(self) -> str:
        self._status = WorkerStatus.RUNNING
        return "a2a"

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        agent_name = task.get("agent", "")
        prompt = task.get("prompt", "")

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
            else:
                data = await client.send_task(task_id, prompt)
                return _event_to_result(task_id, data)
        except Exception as e:
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

### 3.4 Error codes — `mahavishnu/core/errors.py`

```python
A2A_AGENT_NOT_FOUND = "MHV-310"   # agent name not in registry
A2A_AGENT_ERROR = "MHV-311"        # remote agent returned error or stream failed
```

### 3.5 Registry entry — `mahavishnu/workers/registry.py`

```python
WorkerRegistryEntry(
    name="a2a",
    worker_class="A2AWorker",
    category=WorkerCategory.GATEWAY,
    description="Google A2A protocol — routes tasks to external agents by name",
    module="mahavishnu.workers.a2a",
)
```

______________________________________________________________________

## 4. A2A Server — `mahavishnu/a2a/server.py`

### 4.1 Router factory

```python
def build_a2a_router(settings: A2ASettings, worker_manager: Any) -> Starlette:
    """Build a Starlette sub-application with A2A routes."""
    from starlette.applications import Starlette
    from starlette.routing import Route

    return Starlette(routes=[
        Route("/.well-known/agent.json", endpoint=agent_card(settings), methods=["GET"]),
        Route("/tasks/send", endpoint=tasks_send(worker_manager), methods=["POST"]),
        Route("/tasks/sendSubscribe", endpoint=tasks_send_subscribe(worker_manager), methods=["POST"]),
    ])
```

### 4.2 Agent card route

```python
def agent_card(settings: A2ASettings):
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
```

`_get_version()` uses `importlib.metadata.version("mahavishnu")`, falling back to `"0.0.0"`.

### 4.3 Synchronous task route

```python
def tasks_send(worker_manager: Any):
    async def handler(request: Request) -> JSONResponse:
        task_data = await request.json()
        task_id = task_data.get("id", str(uuid.uuid4()))
        prompt = _extract_prompt(task_data)
        try:
            result = await worker_manager.execute_task({"prompt": prompt})
            return JSONResponse(_result_to_a2a(task_id, result))
        except Exception as e:
            return JSONResponse(_error_to_a2a(task_id, str(e)))
    return handler
```

### 4.4 SSE streaming route

```python
def tasks_send_subscribe(worker_manager: Any):
    async def handler(request: Request) -> StreamingResponse:
        task_data = await request.json()
        task_id = task_data.get("id", str(uuid.uuid4()))
        prompt = _extract_prompt(task_data)
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def run_and_emit() -> None:
            await queue.put(_sse_event(task_id, "working", final=False))
            try:
                result = await worker_manager.execute_task({"prompt": prompt})
                await queue.put(_sse_event(task_id, "completed", result=result, final=True))
            except Exception as e:
                await queue.put(_sse_event(task_id, "failed", error=str(e), final=True))
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
```

Helper:

```python
def _sse_event(task_id: str, state: str, *, final: bool,
               result: Any = None, error: str | None = None) -> str:
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
```

### 4.5 `_extract_prompt` helper (module-level in `server.py`)

```python
def _extract_prompt(task_data: dict[str, Any]) -> str:
    """Extract text from A2A task message parts."""
    parts = task_data.get("message", {}).get("parts", [])
    return next((p.get("text", "") for p in parts if p.get("type") == "text"), "")
```

### 4.6 Mount point — `mahavishnu/mcp/server.py`

```python
# After FastMCP server is constructed:
if settings.a2a and settings.a2a.enabled:
    from mahavishnu.a2a.server import build_a2a_router  # noqa: PLC0415
    mcp.app.mount("/", build_a2a_router(settings.a2a, worker_manager))
```

______________________________________________________________________

## 5. Testing

### 5.1 `tests/unit/workers/test_a2a_worker.py` — 5 scenarios

All use `respx` for httpx mocking and `@pytest.mark.unit`.

| # | Scenario | Mock | Assert |
|---|----------|------|--------|
| 1 | Happy path SSE | card: `streaming: true`; `sendSubscribe` emits working→completed with artifact | `status == COMPLETED`, `output` non-empty |
| 2 | Non-streaming fallback | card: `streaming: false`; `send` returns completed task | `status == COMPLETED` |
| 3 | Unknown agent name | name absent from registry | `status == FAILED`, `error_code == "MHV-310"` |
| 4 | Remote agent SSE error event | `sendSubscribe` emits `"failed"` final event | `status == FAILED`, `error_code == "MHV-311"` |
| 5 | Card fetch 503 | `GET /.well-known/agent.json` → 503 | `status == FAILED` |

SSE mock pattern for `respx` (streaming):

```python
sse_body = (
    'data: {"id": "t1", "status": {"state": "working"}, "final": false}\n\n'
    'data: {"id": "t1", "status": {"state": "completed"}, '
    '"artifacts": [{"parts": [{"type": "text", "text": "done"}]}], "final": true}\n\n'
)
respx.post("http://agent.example.com/tasks/sendSubscribe").mock(
    return_value=httpx.Response(200, text=sse_body,
                                headers={"content-type": "text/event-stream"})
)
```

### 5.2 `tests/unit/a2a/test_a2a_server.py` — 4 scenarios

Use Starlette `TestClient` (sync) and `httpx.AsyncClient` for async SSE.

| # | Scenario | Assert |
|---|----------|--------|
| 1 | `GET /.well-known/agent.json` | 200, `AgentCard` validates, `capabilities.streaming == true` |
| 2 | `POST /tasks/send` success | 200, `status.state == "completed"` |
| 3 | `POST /tasks/sendSubscribe` | 200, `content-type: text/event-stream`, final event present |
| 4 | `POST /tasks/send` worker failure | 200, `status.state == "failed"` |

______________________________________________________________________

## 6. File Manifest

| Action | Path |
|--------|------|
| Create | `mahavishnu/a2a/__init__.py` |
| Create | `mahavishnu/a2a/card.py` |
| Create | `mahavishnu/a2a/server.py` |
| Create | `mahavishnu/workers/a2a.py` |
| Create | `tests/unit/a2a/__init__.py` |
| Create | `tests/unit/workers/test_a2a_worker.py` |
| Create | `tests/unit/a2a/test_a2a_server.py` |
| Modify | `mahavishnu/core/errors.py` — add `A2A_AGENT_NOT_FOUND`, `A2A_AGENT_ERROR` |
| Modify | `mahavishnu/core/config.py` — add `A2ASettings`, `A2AAgentEntry`, `A2ACapabilitiesSettings`, `A2ACardSettings` |
| Modify | `mahavishnu/workers/registry.py` — A2A registry entry |
| Modify | `mahavishnu/mcp/server.py` — conditional mount |
| Modify | `settings/mahavishnu.yaml` — `a2a:` block |

______________________________________________________________________

## 7. Out of Scope

- Mahavishnu as A2A server exposing its own workers as skills to other agents (planned Wave 3)
- SSE reconnection / `Last-Event-ID` resumption
- Push notifications (`pushNotifications: false` in card)
- Bodai-internal peer routing (Akosha, Dhara, Crackerjack as A2A targets)
- A2A authentication (JWT token validation on inbound `/tasks/send`)
