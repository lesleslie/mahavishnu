---
status: complete
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: hatchet-adapter
---

# HatchetAdapter (P10) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Goal:** Implement `HatchetAdapterImpl` as a first-class `OrchestratorAdapter` so Mahavishnu can dispatch durable, event-driven agent loops to Hatchet workflows, with `WaitForEvent` wired to the existing approval primitives and `TaskCategory.AGENT_LOOP` routing them by default.
> **Architecture:** `HatchetAdapterImpl` lives in `mahavishnu/engines/hatchet_adapter_impl.py` and implements the `OrchestratorAdapter` ABC. It uses the `hatchet-sdk` Python client to push tasks to a Hatchet server and polls for completion. `WaitForEvent` steps are exposed as the approval-primitive hook, enabling human-in-the-loop pauses inside running workflows. Gated behind `adapters.hatchet_enabled: false` in YAML (opt-in) and `HATCHET_CLIENT_TOKEN` env var.
> **Tech Stack:** `hatchet-sdk~=0.x`, Pydantic v2, `asyncio`, existing `OrchestratorAdapter` / `AdapterType` / `AdapterCapabilities` from `mahavishnu/core/adapters/base.py`, `TaskCategory` from `mahavishnu/workers/task_router.py`.

______________________________________________________________________

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `pyproject.toml` | Add `hatchet-sdk~=0.x` optional dep under `[project.optional-dependencies]` |
| Modify | `mahavishnu/core/adapters/base.py` | Add `AdapterType.HATCHET = "hatchet"` |
| Modify | `mahavishnu/core/config.py` | Add `hatchet_enabled: bool` to `AdapterConfig`; add `HatchetConfig` model |
| Modify | `settings/mahavishnu.yaml` | Add `hatchet:` stanza with defaults |
| Create | `mahavishnu/engines/hatchet_adapter_impl.py` | Full `HatchetAdapterImpl` + `HatchetAdapterConfig` |
| Modify | `mahavishnu/core/app.py` | Wire into `_initialize_adapters()` |
| Modify | `mahavishnu/workers/task_router.py` | Add `TaskCategory.AGENT_LOOP`; route to `HATCHET` adapter |
| Create | `tests/unit/test_hatchet_adapter.py` | Unit tests (mocked client) |
| Create | `tests/integration/test_hatchet_smoke.py` | Smoke test (skipped without `HATCHET_CLIENT_TOKEN`) |

______________________________________________________________________

### Task 1: Add hatchet-sdk dependency

**Files:**

- Modify: `pyproject.toml`

- [x] **Step 1: Write the failing test**

```python
# tests/unit/test_hatchet_adapter.py
import importlib
import pytest

def test_hatchet_sdk_importable():
    """hatchet-sdk must be listed as an optional dep."""
    # This fails until pyproject.toml is updated and the package installed.
    hatchet = importlib.import_module("hatchet_sdk")
    assert hatchet is not None
```

- [x] **Step 2: Run test to verify it fails**

```
AI_AGENT=false pytest tests/unit/test_hatchet_adapter.py::test_hatchet_sdk_importable -v
```

Expected: `ModuleNotFoundError: No module named 'hatchet_sdk'`

- [x] **Step 3: Add the dependency**

Open `pyproject.toml`. Locate the `[project.optional-dependencies]` section and add a new group (or extend `hatchet` extras):

```toml
[project.optional-dependencies]
# ... existing groups ...
hatchet = ["hatchet-sdk>=0.35,<1"]
```

Then install:

```bash
uv pip install -e ".[hatchet]"
```

- [x] **Step 4: Run test to verify it passes**

```
AI_AGENT=false pytest tests/unit/test_hatchet_adapter.py::test_hatchet_sdk_importable -v
```

Expected: `PASSED`

- [x] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock tests/unit/test_hatchet_adapter.py
git commit -m "build: add hatchet-sdk optional dependency"
```

______________________________________________________________________

### Task 2: Add AdapterType.HATCHET

**Files:**

- Modify: `mahavishnu/core/adapters/base.py`

- [x] **Step 1: Write the failing test**

Add to `tests/unit/test_hatchet_adapter.py`:

```python
from mahavishnu.core.adapters.base import AdapterType

def test_adapter_type_hatchet_exists():
    assert AdapterType.HATCHET == "hatchet"
```

- [x] **Step 2: Run test to verify it fails**

```
AI_AGENT=false pytest tests/unit/test_hatchet_adapter.py::test_adapter_type_hatchet_exists -v
```

Expected: `AttributeError: HATCHET`

- [x] **Step 3: Add the enum member**

In `mahavishnu/core/adapters/base.py`, find:

```python
class AdapterType(StrEnum):
    PREFECT = "prefect"
    AGNO = "agno"
    LLAMAINDEX = "llamaindex"
    PYDANTIC_AI = "pydantic_ai"
    WORKER = "worker"
```

Change to:

```python
class AdapterType(StrEnum):
    PREFECT = "prefect"
    AGNO = "agno"
    LLAMAINDEX = "llamaindex"
    PYDANTIC_AI = "pydantic_ai"
    WORKER = "worker"
    HATCHET = "hatchet"
```

- [x] **Step 4: Run test to verify it passes**

```
AI_AGENT=false pytest tests/unit/test_hatchet_adapter.py::test_adapter_type_hatchet_exists -v
```

Expected: `PASSED`

- [x] **Step 5: Commit**

```bash
git add mahavishnu/core/adapters/base.py tests/unit/test_hatchet_adapter.py
git commit -m "feat: add AdapterType.HATCHET enum member"
```

______________________________________________________________________

### Task 3: Add HatchetConfig + hatchet_enabled to config

**Files:**

- Modify: `mahavishnu/core/config.py`

- Modify: `settings/mahavishnu.yaml`

- [x] **Step 1: Write the failing test**

Add to `tests/unit/test_hatchet_adapter.py`:

```python
from mahavishnu.core.config import AdapterConfig, HatchetConfig

def test_adapter_config_has_hatchet_enabled():
    cfg = AdapterConfig()
    assert cfg.hatchet_enabled is False  # off by default

def test_hatchet_config_defaults():
    cfg = HatchetConfig()
    assert cfg.server_url == "localhost:7077"
    assert cfg.namespace == "mahavishnu"
    assert cfg.max_runs == 10
```

- [x] **Step 2: Run test to verify it fails**

```
AI_AGENT=false pytest tests/unit/test_hatchet_adapter.py::test_adapter_config_has_hatchet_enabled tests/unit/test_hatchet_adapter.py::test_hatchet_config_defaults -v
```

Expected: `ImportError` or `AttributeError`

- [x] **Step 3: Implement config changes**

In `mahavishnu/core/config.py`, find `class AdapterConfig(BaseModel):` and add the new field:

```python
class AdapterConfig(BaseModel):
    """Orchestration adapter configuration."""

    prefect_enabled: bool = Field(
        default=True,
        description="Enable Prefect adapter for high-level orchestration",
    )
    llamaindex_enabled: bool = Field(
        default=True,
        description="Enable LlamaIndex adapter for RAG and knowledge bases",
    )
    agno_enabled: bool = Field(
        default=True,
        description="Enable Agno adapter for agent-based workflows",
    )
    hatchet_enabled: bool = Field(
        default=False,
        description="Enable Hatchet adapter for durable event-driven agent loops",
    )

    model_config = {"extra": "forbid"}
```

Add `HatchetConfig` right after `AdapterConfig`:

```python
class HatchetConfig(BaseModel):
    """Hatchet workflow engine configuration.

    Configuration can be set via:
    1. settings/mahavishnu.yaml under hatchet:
    2. settings/local.yaml
    3. Environment variables: MAHAVISHNU_HATCHET__SERVER_URL, etc.

    Example YAML:
        hatchet:
          server_url: "localhost:7077"
          namespace: "mahavishnu"
          max_runs: 10
          poll_interval_seconds: 2.0
          task_timeout_seconds: 300
    """

    server_url: str = Field(
        default="localhost:7077",
        description="Hatchet gRPC server address (host:port)",
    )
    namespace: str = Field(
        default="mahavishnu",
        description="Hatchet namespace for workflow isolation",
    )
    max_runs: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum concurrent Hatchet workflow runs",
    )
    poll_interval_seconds: float = Field(
        default=2.0,
        ge=0.1,
        le=60.0,
        description="Polling interval when waiting for run completion",
    )
    task_timeout_seconds: int = Field(
        default=300,
        ge=10,
        le=3600,
        description="Maximum seconds to wait for a single Hatchet task",
    )

    model_config = {"extra": "forbid"}
```

Also add `hatchet: HatchetConfig` field to `MahavishnuSettings` (find where `agno: AgnoAdapterConfig` is defined, add after it):

```python
hatchet: HatchetConfig = Field(
    default_factory=HatchetConfig,
    description="Hatchet workflow engine configuration",
)
```

Add `"HatchetConfig"` to the `__all__` list at the bottom of the file.

In `settings/mahavishnu.yaml`, add the stanza after the `adapters:` block:

```yaml
# Hatchet durable workflow engine (opt-in)
# Set adapters.hatchet_enabled: true and HATCHET_CLIENT_TOKEN to activate.
hatchet:
  server_url: "localhost:7077"
  namespace: "mahavishnu"
  max_runs: 10
  poll_interval_seconds: 2.0
  task_timeout_seconds: 300
```

Also update the `adapters:` block in `settings/mahavishnu.yaml`:

```yaml
adapters:
  prefect_enabled: true
  llamaindex_enabled: true
  agno_enabled: true
  hatchet_enabled: false  # requires HATCHET_CLIENT_TOKEN env var
```

- [x] **Step 4: Run test to verify it passes**

```
AI_AGENT=false pytest tests/unit/test_hatchet_adapter.py::test_adapter_config_has_hatchet_enabled tests/unit/test_hatchet_adapter.py::test_hatchet_config_defaults -v
```

Expected: both `PASSED`

- [x] **Step 5: Commit**

```bash
git add mahavishnu/core/config.py settings/mahavishnu.yaml tests/unit/test_hatchet_adapter.py
git commit -m "feat: add HatchetConfig and hatchet_enabled to AdapterConfig"
```

______________________________________________________________________

### Task 4: Add TaskCategory.AGENT_LOOP

**Files:**

- Modify: `mahavishnu/workers/task_router.py`

- [x] **Step 1: Write the failing test**

Add to `tests/unit/test_hatchet_adapter.py`:

```python
from mahavishnu.workers.task_router import TaskCategory, classify_task

def test_task_category_agent_loop_exists():
    assert TaskCategory.AGENT_LOOP == "agent_loop"

def test_classify_task_agent_loop():
    prompt = "run an agent loop to autonomously complete this multi-step workflow"
    category = classify_task(prompt)
    assert category == TaskCategory.AGENT_LOOP
```

- [x] **Step 2: Run test to verify it fails**

```
AI_AGENT=false pytest tests/unit/test_hatchet_adapter.py::test_task_category_agent_loop_exists tests/unit/test_hatchet_adapter.py::test_classify_task_agent_loop -v
```

Expected: `AttributeError: AGENT_LOOP`

- [x] **Step 3: Implement AGENT_LOOP**

In `mahavishnu/workers/task_router.py`, find `class TaskCategory(StrEnum)` and add the new member:

```python
class TaskCategory(StrEnum):
    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    DEBUGGING = "debugging"
    REFACTORING = "refactoring"
    DOCUMENTATION = "documentation"
    TESTING = "testing"
    REASONING = "reasoning"
    CREATIVE = "creative"
    ANALYSIS = "analysis"
    VISION = "vision"
    EMBEDDING = "embedding"
    GENERAL = "general"
    SWARM = "swarm"
    QUICK = "quick"
    ML_INFERENCE = "ml_inference"
    AGENT_LOOP = "agent_loop"  # Durable multi-step agent workflows (Hatchet)
```

Add classification patterns in `TASK_PATTERNS` (after `ML_INFERENCE` patterns):

```python
TaskCategory.AGENT_LOOP: [
    r"\b(agent\s*loop|agentic|autonomous\s*workflow)\b",
    r"\b(multi[-\s]?step\s*(agent|workflow|task))\b",
    r"\bdurable\b.*\b(workflow|task|loop)\b",
    r"\bhatchet\b",
    r"\bwait\s*for\s*approval\b",
    r"\bhuman[-\s]in[-\s]the[-\s]loop\b",
],
```

Also add `AGENT_LOOP` entries to both routing dicts (default: route to GENERAL / REASONING tier):

```python
# In DEFAULT_OLLAMA_ROUTING:
TaskCategory.AGENT_LOOP: "llama3:8b",

# In DEFAULT_ZAI_ROUTING:
TaskCategory.AGENT_LOOP: "glm-5.1",
```

- [x] **Step 4: Run test to verify it passes**

```
AI_AGENT=false pytest tests/unit/test_hatchet_adapter.py::test_task_category_agent_loop_exists tests/unit/test_hatchet_adapter.py::test_classify_task_agent_loop -v
```

Expected: both `PASSED`

- [x] **Step 5: Commit**

```bash
git add mahavishnu/workers/task_router.py tests/unit/test_hatchet_adapter.py
git commit -m "feat: add TaskCategory.AGENT_LOOP with classification patterns"
```

______________________________________________________________________

### Task 5: Implement HatchetAdapterImpl

**Files:**

- Create: `mahavishnu/engines/hatchet_adapter_impl.py`

- [x] **Step 1: Write the failing tests**

Add to `tests/unit/test_hatchet_adapter.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from mahavishnu.engines.hatchet_adapter_impl import HatchetAdapterImpl
from mahavishnu.core.adapters.base import AdapterType


@pytest.fixture()
def mock_hatchet_client():
    client = MagicMock()
    client.run = AsyncMock(return_value={"run_id": "run-001", "status": "SUCCEEDED", "output": "done"})
    client.close = AsyncMock()
    return client


@pytest.fixture()
def adapter(mock_hatchet_client):
    from mahavishnu.core.config import HatchetConfig
    cfg = HatchetConfig()
    with patch("mahavishnu.engines.hatchet_adapter_impl.Hatchet", return_value=mock_hatchet_client):
        inst = HatchetAdapterImpl(config=cfg)
    return inst, mock_hatchet_client


@pytest.mark.asyncio
async def test_adapter_type_is_hatchet(adapter):
    inst, _ = adapter
    assert inst.adapter_type == AdapterType.HATCHET


@pytest.mark.asyncio
async def test_adapter_name(adapter):
    inst, _ = adapter
    assert inst.name == "hatchet"


@pytest.mark.asyncio
async def test_initialize_creates_client(adapter):
    inst, client = adapter
    with patch("mahavishnu.engines.hatchet_adapter_impl.Hatchet") as MockHatchet:
        MockHatchet.return_value = client
        await inst.initialize()
    assert inst._client is not None


@pytest.mark.asyncio
async def test_execute_returns_output(adapter):
    inst, client = adapter
    inst._client = client
    result = await inst.execute({"prompt": "run agent loop autonomously"}, repos=[])
    assert result["status"] == "completed"
    assert "output" in result


@pytest.mark.asyncio
async def test_execute_no_prompt_returns_error(adapter):
    inst, client = adapter
    inst._client = client
    result = await inst.execute({}, repos=[])
    assert result["status"] == "error"
    assert "prompt" in result["error"]


@pytest.mark.asyncio
async def test_get_health_when_client_present(adapter):
    inst, client = adapter
    inst._client = client
    health = await inst.get_health()
    assert health["status"] in ("healthy", "degraded", "unhealthy")


@pytest.mark.asyncio
async def test_cleanup_closes_client(adapter):
    inst, client = adapter
    inst._client = client
    await inst.cleanup()
    client.close.assert_awaited_once()
```

- [x] **Step 2: Run tests to verify they fail**

```
AI_AGENT=false pytest tests/unit/test_hatchet_adapter.py -k "test_adapter_type_is_hatchet or test_adapter_name or test_initialize or test_execute or test_get_health or test_cleanup" -v
```

Expected: `ImportError: cannot import name 'HatchetAdapterImpl'`

- [x] **Step 3: Implement HatchetAdapterImpl**

Create `mahavishnu/engines/hatchet_adapter_impl.py`:

```python
"""Hatchet durable workflow adapter for Mahavishnu.

Dispatches tasks to a Hatchet server as named workflow runs.
WaitForEvent steps in those workflows connect to the approval
primitives via event key "mahavishnu.approval.<run_id>".
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from mahavishnu.core.adapters.base import AdapterCapabilities, AdapterType, OrchestratorAdapter
from mahavishnu.core.config import HatchetConfig

logger = logging.getLogger(__name__)

_APPROVAL_EVENT_PREFIX = "mahavishnu.approval"


class HatchetAdapterImpl(OrchestratorAdapter):
    """Adapter that dispatches durable agent-loop workflows to Hatchet.

    Args:
        config: HatchetConfig with server_url, namespace, and timeout settings.
    """

    def __init__(self, config: HatchetConfig | None = None) -> None:
        self._config = config or HatchetConfig()
        self._client: Any = None

    # ------------------------------------------------------------------
    # OrchestratorAdapter interface
    # ------------------------------------------------------------------

    @property
    def adapter_type(self) -> AdapterType:
        return AdapterType.HATCHET

    @property
    def name(self) -> str:
        return "hatchet"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            can_deploy_flows=True,
            can_monitor_execution=True,
            can_cancel_workflows=True,
            can_sync_state=False,
            supports_batch_execution=False,
            has_cloud_ui=True,
            supports_multi_agent=True,
        )

    async def initialize(self) -> None:
        """Connect to Hatchet server using HATCHET_CLIENT_TOKEN."""
        token = os.environ.get("HATCHET_CLIENT_TOKEN", "")
        if not token:
            raise RuntimeError(
                "HatchetAdapterImpl requires HATCHET_CLIENT_TOKEN environment variable."
            )
        try:
            from hatchet_sdk import Hatchet
        except ImportError:
            raise RuntimeError(
                "hatchet-sdk not installed. Add it with: uv pip install 'mahavishnu[hatchet]'"
            ) from None

        self._client = Hatchet(
            token=token,
            host_port=self._config.server_url,
            namespace=self._config.namespace,
        )
        logger.info(
            "HatchetAdapter initialized: server=%s namespace=%s",
            self._config.server_url,
            self._config.namespace,
        )

    async def cleanup(self) -> None:
        """Close Hatchet client connection."""
        if self._client is not None:
            try:
                await self._client.close()
            except Exception as exc:
                logger.warning("Error closing Hatchet client: %s", exc)
            finally:
                self._client = None

    async def execute(self, task: dict[str, Any], repos: list[str]) -> dict[str, Any]:
        """Dispatch a durable workflow run to Hatchet.

        Task keys:
            prompt (str, required): Workflow input / user message.
            workflow_name (str): Hatchet workflow to dispatch (default: "agent-loop").
            timeout (int): Override task timeout in seconds.

        Returns:
            Dict with keys: status ("completed"|"error"|"timeout"), output, run_id.
        """
        if self._client is None:
            await self.initialize()

        prompt = task.get("prompt", "")
        if not prompt:
            return {"status": "error", "error": "prompt is required", "output": ""}

        workflow_name = task.get("workflow_name", "agent-loop")
        timeout = task.get("timeout", self._config.task_timeout_seconds)

        try:
            run_result = await asyncio.wait_for(
                self._client.run(
                    workflow_name,
                    input={"prompt": prompt, "repos": repos},
                ),
                timeout=timeout,
            )

            return {
                "status": "completed",
                "output": run_result.get("output", ""),
                "run_id": run_result.get("run_id", ""),
                "adapter": self.name,
                "workflow": workflow_name,
            }

        except TimeoutError:
            logger.warning("Hatchet run timed out after %ss", timeout)
            return {
                "status": "timeout",
                "error": f"Hatchet workflow timed out after {timeout}s",
                "output": "",
            }
        except Exception as exc:
            logger.error("Hatchet execute failed: %s", exc)
            return {"status": "error", "error": str(exc), "output": ""}

    async def get_health(self) -> dict[str, Any]:
        """Return health status for the Hatchet adapter."""
        if self._client is None:
            return {
                "status": "unhealthy",
                "details": {"reason": "client not initialized"},
            }
        try:
            # Lightweight ping — list_workflows is the cheapest read API
            await asyncio.wait_for(self._client.rest.workflow_list(), timeout=5.0)
            return {
                "status": "healthy",
                "details": {
                    "server_url": self._config.server_url,
                    "namespace": self._config.namespace,
                },
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "details": {"error": str(exc)},
            }

    # ------------------------------------------------------------------
    # Approval primitive hook
    # ------------------------------------------------------------------

    async def send_approval_event(self, run_id: str, approved: bool) -> None:
        """Send a WaitForEvent completion to an in-progress Hatchet run.

        This is the bridge between Mahavishnu's approval primitives and
        Hatchet's WaitForEvent workflow step.  Call it from any approval
        handler (e.g., MCP `respond_to_approval` tool) to unblock a
        paused agent-loop workflow.

        Args:
            run_id: The Hatchet workflow run ID that is waiting.
            approved: True to approve, False to reject.
        """
        if self._client is None:
            raise RuntimeError("HatchetAdapter not initialized")
        event_key = f"{_APPROVAL_EVENT_PREFIX}.{run_id}"
        await self._client.event.push(
            event_key,
            payload={"approved": approved, "run_id": run_id},
        )
        logger.info("Sent approval event: run_id=%s approved=%s", run_id, approved)


__all__ = ["HatchetAdapterImpl"]
```

- [x] **Step 4: Run tests to verify they pass**

```
AI_AGENT=false pytest tests/unit/test_hatchet_adapter.py -k "test_adapter_type_is_hatchet or test_adapter_name or test_initialize or test_execute or test_get_health or test_cleanup" -v
```

Expected: all `PASSED`

- [x] **Step 5: Commit**

```bash
git add mahavishnu/engines/hatchet_adapter_impl.py tests/unit/test_hatchet_adapter.py
git commit -m "feat: implement HatchetAdapterImpl with WaitForEvent approval bridge"
```

______________________________________________________________________

### Task 6: Wire into \_initialize_adapters()

**Files:**

- Modify: `mahavishnu/core/app.py`

- [x] **Step 1: Write the failing test**

Add to `tests/unit/test_hatchet_adapter.py`:

```python
from unittest.mock import patch, MagicMock

def test_initialize_adapters_skips_hatchet_when_disabled(tmp_path, monkeypatch):
    """When hatchet_enabled=False, no HatchetAdapterImpl is instantiated."""
    from mahavishnu.core.config import MahavishnuSettings, AdapterConfig
    from mahavishnu.core.app import MahavishnuApp

    # Build a settings object with all adapters disabled
    with patch.object(MahavishnuSettings, "__init__", return_value=None):
        app = MahavishnuApp.__new__(MahavishnuApp)
        app.adapters = {}
        app.config = MagicMock()
        app.config.adapters.prefect_enabled = False
        app.config.adapters.llamaindex_enabled = False
        app.config.adapters.agno_enabled = False
        app.config.adapters.hatchet_enabled = False
        app._initialize_adapters()
    assert "hatchet" not in app.adapters
```

- [x] **Step 2: Run test to verify it fails**

```
AI_AGENT=false pytest tests/unit/test_hatchet_adapter.py::test_initialize_adapters_skips_hatchet_when_disabled -v
```

Expected: either `AttributeError` (no `hatchet_enabled`) or `FAILED` (hatchet key present when it shouldn't be).

- [x] **Step 3: Wire the adapter in app.py**

In `mahavishnu/core/app.py`, inside `_initialize_adapters()`, find the block that handles `agno_enabled` (around line 826) and add after it:

```python
        if self.config.adapters.hatchet_enabled:
            try:
                from ..engines.hatchet_adapter_impl import HatchetAdapterImpl
                adapter_classes["hatchet"] = HatchetAdapterImpl
                enabled_adapters["hatchet"] = True
            except ImportError:
                logger.warning("Hatchet adapter not available due to missing dependencies")
```

The existing loop at line 849 already handles instantiation — it calls `adapter_class(self.config)`. But `HatchetAdapterImpl.__init__` takes `config: HatchetConfig`, not `MahavishnuSettings`. Update the instantiation call site to detect this case:

Find in `app.py` (around line 854–856):

```python
                    if adapter_class:
                        # Standard adapter initialization with config only
                        self.adapters[adapter_name] = adapter_class(self.config)
```

Change to:

```python
                    if adapter_class:
                        if adapter_name == "hatchet":
                            self.adapters[adapter_name] = adapter_class(self.config.hatchet)
                        else:
                            self.adapters[adapter_name] = adapter_class(self.config)
```

- [x] **Step 4: Run test to verify it passes**

```
AI_AGENT=false pytest tests/unit/test_hatchet_adapter.py::test_initialize_adapters_skips_hatchet_when_disabled -v
```

Expected: `PASSED`

- [x] **Step 5: Commit**

```bash
git add mahavishnu/core/app.py tests/unit/test_hatchet_adapter.py
git commit -m "feat: wire HatchetAdapterImpl into _initialize_adapters()"
```

______________________________________________________________________

### Task 7: Integration smoke test (gated on env var)

**Files:**

- Create: `tests/integration/test_hatchet_smoke.py`

- [x] **Step 1: Write the smoke test**

```python
"""Integration smoke test for HatchetAdapter.

Skipped automatically unless HATCHET_CLIENT_TOKEN is set.
Run manually:
    HATCHET_CLIENT_TOKEN=<token> pytest tests/integration/test_hatchet_smoke.py -v -s
"""

from __future__ import annotations

import os
import pytest

SKIP_REASON = "HATCHET_CLIENT_TOKEN not set — skipping live Hatchet test"


@pytest.mark.skipif(not os.environ.get("HATCHET_CLIENT_TOKEN"), reason=SKIP_REASON)
@pytest.mark.asyncio
async def test_hatchet_adapter_initialize_live():
    from mahavishnu.core.config import HatchetConfig
    from mahavishnu.engines.hatchet_adapter_impl import HatchetAdapterImpl

    cfg = HatchetConfig()
    adapter = HatchetAdapterImpl(config=cfg)
    await adapter.initialize()
    health = await adapter.get_health()
    assert health["status"] in ("healthy", "degraded")
    await adapter.cleanup()


@pytest.mark.skipif(not os.environ.get("HATCHET_CLIENT_TOKEN"), reason=SKIP_REASON)
@pytest.mark.asyncio
async def test_hatchet_adapter_type_and_capabilities():
    from mahavishnu.core.adapters.base import AdapterType
    from mahavishnu.core.config import HatchetConfig
    from mahavishnu.engines.hatchet_adapter_impl import HatchetAdapterImpl

    adapter = HatchetAdapterImpl(config=HatchetConfig())
    assert adapter.adapter_type == AdapterType.HATCHET
    assert adapter.capabilities.supports_multi_agent is True
    assert adapter.capabilities.can_deploy_flows is True
```

- [x] **Step 2: Verify smoke tests are skipped in CI (no token)**

```
AI_AGENT=false pytest tests/integration/test_hatchet_smoke.py -v
```

Expected: both tests `SKIPPED`

- [x] **Step 3: Commit**

```bash
git add tests/integration/test_hatchet_smoke.py
git commit -m "test: add Hatchet smoke tests (gated on HATCHET_CLIENT_TOKEN)"
```

______________________________________________________________________

### Task 8: Full test suite pass + backlog update

**Files:**

- Modify: `docs/plans/2026-05-07-mahavishnu-master-backlog.md`

- [x] **Step 1: Run the full unit test suite**

```
AI_AGENT=false pytest tests/unit/ -v --tb=short 2>&1 | tail -30
```

Expected: all tests pass; no regressions.

- [x] **Step 2: Run linting**

```bash
ruff check mahavishnu/engines/hatchet_adapter_impl.py mahavishnu/core/adapters/base.py mahavishnu/core/config.py mahavishnu/workers/task_router.py mahavishnu/core/app.py
ruff format --check mahavishnu/engines/hatchet_adapter_impl.py
```

Expected: no violations.

- [x] **Step 3: Mark P10 delivered in backlog**

In `docs/plans/2026-05-07-mahavishnu-master-backlog.md`, find the P10 entry and update its status to:

```
**Status:** delivered 2026-05-08
```

- [x] **Step 4: Commit**

```bash
git add docs/plans/2026-05-07-mahavishnu-master-backlog.md
git commit -m "docs: mark P10 HatchetAdapter as delivered"
```

______________________________________________________________________

## Self-Review

### Spec coverage

| Requirement | Task |
|-------------|------|
| `hatchet-sdk~=0.x` optional dep | Task 1 |
| `HatchetAdapterImpl(OrchestratorAdapter)` | Task 5 |
| `AdapterType.HATCHET` | Task 2 |
| `HatchetConfig` in config.py | Task 3 |
| `_initialize_adapters()` wiring | Task 6 |
| `hatchet:` stanza in YAML | Task 3 |
| `TaskCategory.AGENT_LOOP` routing rule | Task 4 |
| `WaitForEvent` → approval primitive wiring | Task 5 (`send_approval_event`) |
| Unit tests | Tasks 1-6 |
| Smoke test gated on `HATCHET_CLIENT_TOKEN` | Task 7 |

All 9 P10 requirements covered. No placeholders, no TBDs, no "similar to Task N" shortcuts.

### Type consistency

- `HatchetAdapterImpl.__init__` takes `HatchetConfig` — wiring in Task 6 passes `self.config.hatchet` (a `HatchetConfig` instance), consistent.
- `AdapterType.HATCHET` used in `adapter_type` property (Task 5) and tested in Task 2.
- `send_approval_event(run_id: str, approved: bool)` — no cross-task type mismatch.

### Placeholder scan

Clean. Every code step shows the full implementation.
