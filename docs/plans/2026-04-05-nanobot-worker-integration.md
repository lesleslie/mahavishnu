# Plan: NanobotWorker In-Process Integration (Phase B only)

> **Phase A (claude mcp serve autostart via Supergateway) removed 2026-05-01.**
> Rationale: nanobot has its own tool set; the autostart infrastructure never existed;
> Supergateway adds Node.js dependency to a Python ecosystem; loop risk requires
> permanent operational vigilance. Revisit only if a concrete workflow emerges that
> requires nanobot agents to call Claude Code's file tools specifically.

## Context

Mahavishnu's ecosystem includes nanobot, an AI agent with its own `AgentRunner`/`AgentLoop`
Python API, session management, memory, and MCP tool integration. This plan wires nanobot
as an **in-process Mahavishnu worker** — no terminal, no subprocess, direct Python API call.

`NanobotWorker` is unique among Mahavishnu workers because `AgentLoop` mode provides
persistent sessions + memory + MCP tools in a single stateful worker — not just stateless
LLM calls like `CloudWorker`.

**What is already complete (Phase B1–B6):**

- `IN_PROCESS` worker category in `mahavishnu/workers/registry.py`
- `in-process-nanobot` and `in-process-nanobot-loop` registered in `WORKER_REGISTRY`
- `mahavishnu/workers/nanobot_worker.py` — full `NanobotWorker` class
- `WorkerManager` wiring (`IN_PROCESS` branch in `_create_worker()`)
- `_init_nanobot_provider()` exists in `mahavishnu/core/app.py`
- `NanobotWorker` exported from `mahavishnu/workers/__init__.py`

**What remains (Phase B completion):**

______________________________________________________________________

## Task 1: Add `nanobot` dependency

**File:** `pyproject.toml`

The comment at line 102 exists but no actual dep line. Add:

```toml
"nanobot>=0.1.4",
```

under the in-process workers comment. Then install into the main venv.

**Verify:**

```bash
python -c "import nanobot; print(nanobot.__version__)"
```

______________________________________________________________________

## Task 2: Fix provider init to use ZAI (not ANTHROPIC_AUTH_TOKEN)

**File:** `mahavishnu/core/app.py`, method `_init_nanobot_provider()` (~line 519)

The current implementation reads `ANTHROPIC_AUTH_TOKEN` but nanobot in this ecosystem
uses the ZAI GLM API (`ZAI_API_KEY`, `https://api.z.ai/api/coding/paas/v4`).

Replace the env var logic:

```python
auth_token = os.environ.get("ZAI_API_KEY")
base_url = os.environ.get(
    "ZAI_BASE_URL", "https://api.z.ai/api/coding/paas/v4"
)

if not auth_token:
    logger.debug("ZAI_API_KEY not set; nanobot provider not configured")
    return None

from nanobot.providers import OpenAICompatProvider

provider = OpenAICompatProvider(api_key=auth_token, base_url=base_url)
logger.info("Nanobot provider initialized via ZAI (base_url=%s)", base_url)
return provider
```

Remove the gateway_api_base / BIFROST_BASE_URL / ANTHROPIC_BASE_URL logic — that was
the wrong provider family.

______________________________________________________________________

## Task 3: Write unit tests

**New file:** `tests/unit/workers/test_nanobot_worker.py`

Tests to cover:

- `NanobotWorker` constructs without error (provider=None)
- `initialize()` raises `RuntimeError` when provider is None
- `execute()` calls provider and returns result (provider mocked)
- `worker_id` is set and starts with `"nanobot_"`
- Loop mode (`in-process-nanobot-loop`) constructs correctly
- `_init_nanobot_provider()` returns None when `ZAI_API_KEY` not set

______________________________________________________________________

## Verification

```bash
# 1. Import check
python -c "from mahavishnu.workers import NanobotWorker; print('ok')"

# 2. Worker registry check
python -c "
from mahavishnu.workers.registry import get_worker_config
c = get_worker_config('in-process-nanobot')
print(c.name, c.category)
"

# 3. Provider init check (ZAI_API_KEY must be set)
python -c "
import asyncio
from mahavishnu.core.app import MahavishnuApp
app = MahavishnuApp.__new__(MahavishnuApp)
p = app._init_nanobot_provider()
print('provider:', p)
"

# 4. Run tests
pytest tests/unit/workers/test_nanobot_worker.py -v --no-cov
```
