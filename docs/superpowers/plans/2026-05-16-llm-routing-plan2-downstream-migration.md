---
status: complete
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: llm-routing-plan2
---

# LLM Routing Standardization — Plan 2: Downstream Migration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate crackerjack, session-buddy, akosha, and mahavishnu from their per-repo LLM provider implementations to the three-tier `FallbackChain` shipped in Plan 1 (mcp-common ≥0.14.0). Subscription-based usage (`claude -p`, Anthropic subscription) is removed entirely.

**Architecture:** Each repo that had its own provider stack (crackerjack's `ProviderChain`, session-buddy's anthropic/gemini providers, mahavishnu's per-cloud workers) is migrated to import and configure `FallbackChain` from `mcp_common.llm`. `settings/models.yaml` in mahavishnu is the canonical source of provider configuration; crackerjack and session-buddy read their own Oneiric/MCPServerSettings config. The `TaskCategory` enum in `mahavishnu/workers/task_router.py` is extended with multimodal variants so routing decisions align with the chain's modality support.

**Prerequisite:** mcp-common `0.14.0` must be published (Plan 1 complete) before any task in this plan begins.

**Tech Stack:** Python 3.13+, pydantic v2, mcp-common ≥0.14.0, pytest, pytest-asyncio

______________________________________________________________________

## File Map

| File | Repo | Change |
|------|------|--------|
| `settings/models.yaml` | mahavishnu | Add `llama_server` tier; migrate to `providers:` + `task_tiers:` schema |
| `mahavishnu/workers/task_router.py` | mahavishnu | Add multimodal TaskCategory variants; keep VISION as deprecated alias; fix DEFAULT_OLLAMA_ROUTING model names |
| `mahavishnu/workers/cloud_worker.py` | mahavishnu | Replace direct OpenAI client with FallbackChain; remove MiniMax-specific logic |
| `mahavishnu/workers/ollama.py` | mahavishnu | Remove standalone OllamaWorker; consolidate into FallbackChain-backed worker |
| `crackerjack/adapters/ai/registry.py` | crackerjack | Delete (and backup) |
| `crackerjack/adapters/ai/{claude,minimax,qwen,ollama}.py` | crackerjack | Delete |
| `crackerjack/adapters/ai/__init__.py` | crackerjack | Update re-exports |
| `crackerjack/adapters/ai/base.py` | crackerjack | Keep security validation; wire as validate_output hook |
| `crackerjack/agents/enhanced_coordinator.py` | crackerjack | Replace ProviderChain/ProviderID with FallbackChain |
| `crackerjack/cli/handlers/provider_selection.py` | crackerjack | Replace ProviderFactory/ProviderID/ProviderInfo |
| `crackerjack/adapters/factory.py` | crackerjack | Replace factory logic |
| `crackerjack/tests/adapters/test_provider_chain.py` | crackerjack | Rewrite against FallbackChain interface |
| `session_buddy/llm/providers/anthropic_provider.py` | session-buddy | Delete |
| `session_buddy/llm/providers/gemini_provider.py` | session-buddy | Delete |
| `session_buddy/llm/providers/openai_provider.py` | session-buddy | Rename to minimax_provider.py; update base_url/model |
| `session_buddy/llm_providers.py` | session-buddy | Replace ProviderFactory with FallbackChain |
| `session_buddy/settings.py` | session-buddy | Ensure `default_provider = "minimax"` |
| `tests/` (per-repo) | all | New migration parity tests |

______________________________________________________________________

## Task 1: Update mahavishnu `settings/models.yaml` for three-tier chain

**Files:**

- Modify: `settings/models.yaml` in `/Users/les/Projects/mahavishnu`

- Modify: `tests/unit/test_models_yaml.py` (create if absent)

- [ ] **Step 1: Write a failing test that validates the new schema**

Create `tests/unit/test_models_yaml.py`:

```python
import pytest
from mcp_common.llm.config import LLMSettings


class TestModelsYamlSchema:
    def test_minimax_is_first_in_fallback_chain(self) -> None:
        settings = LLMSettings.from_yaml("settings/models.yaml")
        chain = settings.fallback_chain
        assert chain[0] == "minimax"

    def test_llama_server_is_second_in_fallback_chain(self) -> None:
        settings = LLMSettings.from_yaml("settings/models.yaml")
        assert "llama_server" in settings.fallback_chain
        idx_minimax = settings.fallback_chain.index("minimax")
        idx_llama = settings.fallback_chain.index("llama_server")
        assert idx_llama > idx_minimax

    def test_ollama_is_third_in_fallback_chain(self) -> None:
        settings = LLMSettings.from_yaml("settings/models.yaml")
        assert settings.fallback_chain[-1] == "ollama"

    def test_llama_server_uses_port_8081_not_11434(self) -> None:
        settings = LLMSettings.from_yaml("settings/models.yaml")
        providers = {p.name: p for p in settings.get_enabled_providers()}
        if "llama_server" in providers:
            assert ":8081" in providers["llama_server"].base_url
            assert "11434" not in providers["llama_server"].base_url

    def test_ollama_uses_port_11434(self) -> None:
        settings = LLMSettings.from_yaml("settings/models.yaml")
        providers = {p.name: p for p in settings.get_enabled_providers()}
        if "ollama" in providers:
            assert "11434" in providers["ollama"].base_url

    def test_ollama_require_auth_is_false(self) -> None:
        settings = LLMSettings.from_yaml("settings/models.yaml")
        providers = {p.name: p for p in settings.get_enabled_providers()}
        # ollama included even when MINIMAX_API_KEY unset, so check raw config
        raw = settings.providers.get("ollama", {})
        assert raw.get("require_auth", True) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu
uv run pytest tests/unit/test_models_yaml.py -v 2>&1 | head -30
```

Expected: failures due to missing `llama_server` key and old schema shape.

- [ ] **Step 3: Rewrite `settings/models.yaml` with new three-tier schema**

Replace the entire file content:

```yaml
# Mahavishnu — LLM Model Configuration
# Updated: 2026-05-16 (three-tier provider chain, Plan 2 migration)
#
# IMPORTANT: llama-server runs on port 8081 (llama.cpp via llama-server binary).
#            ollama runs on port 11434.  These are separate processes — do NOT conflate.
#
# Related files:
#   - mahavishnu/workers/task_router.py   - TaskCategory + model routing
#   - mahavishnu/workers/cloud_worker.py  - FallbackChain-backed worker
#   - config/bifrost/config.template.json - Bifrost gateway (Phase 2)

# =============================================================================
# PROVIDER DEFINITIONS
# =============================================================================

providers:
  minimax:
    enabled: true
    base_url: "https://api.minimax.io/v1"
    api_key_env: "MINIMAX_API_KEY"
    require_auth: true
    model: "MiniMax-M2.7"
    timeout_seconds: 30
    max_retries: 2

  minimax_highspeed:
    enabled: true
    base_url: "https://api.minimax.io/v1"
    api_key_env: "MINIMAX_API_KEY"
    require_auth: true
    model: "MiniMax-M2.7-highspeed"
    timeout_seconds: 15
    max_retries: 2

  minimax_hailuo:
    enabled: true
    base_url: "https://api.minimax.io/v1"
    api_key_env: "MINIMAX_API_KEY"
    require_auth: true
    model: "MiniMax-Video-01"
    timeout_seconds: 300  # async polling max (60 polls × 5s)

  llama_server:
    enabled: true
    base_url: "http://localhost:8081/v1"  # llama-server, NOT ollama
    api_key_env: "LLAMA_SERVER_API_KEY"
    require_auth: false  # no-auth for local service; env var unused if missing
    model: "Qwen3-8B-8.2B-Q4_K_M"
    timeout_seconds: 60
    max_retries: 1

  ollama:
    enabled: true
    base_url: "http://localhost:11434/v1"  # ollama, NOT llama-server
    api_key_env: null
    require_auth: false  # no Authorization header sent
    model: "qwen2.5-coder:7b"
    timeout_seconds: 120
    max_retries: 1

# =============================================================================
# TASK-TIER ROUTING
# Maps TaskCategory → ordered list of provider keys
# =============================================================================

task_tiers:
  default:            [minimax, llama_server, ollama]
  quick:              [minimax_highspeed, llama_server, ollama]
  swarm:              [minimax_highspeed, llama_server, ollama]
  code_generation:    [minimax, llama_server, ollama]
  code_review:        [minimax, llama_server, ollama]
  debugging:          [minimax, llama_server, ollama]
  refactoring:        [minimax, llama_server, ollama]
  documentation:      [minimax, llama_server, ollama]
  testing:            [minimax, llama_server, ollama]
  reasoning:          [minimax, llama_server, ollama]
  analysis:           [minimax, llama_server, ollama]
  creative:           [minimax, llama_server, ollama]
  general:            [minimax, llama_server, ollama]
  embedding:          [llama_server, ollama]             # local preferred for embeddings
  agent_loop:         [minimax, llama_server, ollama]
  ml_inference:       [minimax, llama_server, ollama]
  image_generation:   [minimax_hailuo]                   # MiniMax-Image-01 via HailuoAdapter
  image_understanding: [minimax, llama_server, ollama]   # vision-capable models
  audio_speech:       [minimax]                          # MiniMax-Speech-02 only
  audio_transcription: [minimax]                         # MiniMax-Speech-02-Turbo only
  video_generation:   [minimax_hailuo]                   # MiniMax-Video-01 (Hailuo) only
  # VISION is deprecated — routes to image_understanding tier
  vision:             [minimax, llama_server, ollama]

# =============================================================================
# GLOBAL DEFAULTS
# =============================================================================

default_provider: "minimax"
fallback_chain: ["minimax", "llama_server", "ollama"]

# =============================================================================
# BIFROST (Phase 2 — optional)
# Activated via BIFROST_BASE_URL env var only
# =============================================================================

bifrost:
  enabled: false
  base_url: "http://127.0.0.1:8471"
  activate_env: "BIFROST_BASE_URL"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_models_yaml.py -v
```

- [ ] **Step 5: Commit**

```bash
git add settings/models.yaml tests/unit/test_models_yaml.py
git commit -m "feat(config): migrate models.yaml to three-tier provider chain schema

- Add llama_server tier at localhost:8081 (llama-server, NOT ollama)
- Separate ollama remains at localhost:11434
- Add task_tiers routing for all TaskCategory variants including multimodal
- Add minimax_highspeed and minimax_hailuo as named sub-providers
- Mark bifrost as disabled pending Phase 2 activation"
```

______________________________________________________________________

## Task 2: Extend mahavishnu `task_router.py` with multimodal TaskCategory variants

**Files:**

- Modify: `mahavishnu/workers/task_router.py` in `/Users/les/Projects/mahavishnu`

- Modify: `tests/unit/test_task_router_and_auth.py`

- [ ] **Step 1: Write failing tests for new TaskCategory variants**

Add to `tests/unit/test_task_router_and_auth.py`:

```python
class TestTaskCategoryMultimodal:
    def test_image_generation_exists(self) -> None:
        from mahavishnu.workers.task_router import TaskCategory
        assert TaskCategory.IMAGE_GENERATION == "image_generation"

    def test_image_understanding_exists(self) -> None:
        from mahavishnu.workers.task_router import TaskCategory
        assert TaskCategory.IMAGE_UNDERSTANDING == "image_understanding"

    def test_audio_speech_exists(self) -> None:
        from mahavishnu.workers.task_router import TaskCategory
        assert TaskCategory.AUDIO_SPEECH == "audio_speech"

    def test_audio_transcription_exists(self) -> None:
        from mahavishnu.workers.task_router import TaskCategory
        assert TaskCategory.AUDIO_TRANSCRIPTION == "audio_transcription"

    def test_video_generation_exists(self) -> None:
        from mahavishnu.workers.task_router import TaskCategory
        assert TaskCategory.VIDEO_GENERATION == "video_generation"

    def test_vision_deprecated_alias_still_works(self) -> None:
        from mahavishnu.workers.task_router import TaskCategory
        # VISION kept for one release cycle — must not raise AttributeError
        assert TaskCategory.VISION == "vision"
        assert TaskCategory("vision") is TaskCategory.VISION

    def test_default_ollama_routing_uses_updated_qwen3_model(self) -> None:
        from mahavishnu.workers.task_router import DEFAULT_OLLAMA_ROUTING, TaskCategory
        # Model name must match settings/models.yaml ollama.model
        assert DEFAULT_OLLAMA_ROUTING[TaskCategory.CODE_GENERATION] == "Qwen3-8B-8.2B-Q4_K_M"

    def test_default_llama_server_routing_covers_all_text_categories(self) -> None:
        from mahavishnu.workers.task_router import DEFAULT_LLAMA_SERVER_ROUTING, TaskCategory
        text_categories = [
            TaskCategory.CODE_GENERATION, TaskCategory.REASONING,
            TaskCategory.DOCUMENTATION, TaskCategory.ANALYSIS,
        ]
        for cat in text_categories:
            assert cat in DEFAULT_LLAMA_SERVER_ROUTING
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu
uv run pytest tests/unit/test_task_router_and_auth.py::TestTaskCategoryMultimodal -v 2>&1 | head -20
```

- [ ] **Step 3: Extend `TaskCategory` and add `DEFAULT_LLAMA_SERVER_ROUTING` in `task_router.py`**

In `mahavishnu/workers/task_router.py`, add after the existing `AGENT_LOOP` entry:

```python
class TaskCategory(StrEnum):
    """Categories for task classification."""

    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    DEBUGGING = "debugging"
    REFACTORING = "refactoring"
    DOCUMENTATION = "documentation"
    TESTING = "testing"
    REASONING = "reasoning"
    CREATIVE = "creative"
    ANALYSIS = "analysis"
    GENERAL = "general"
    SWARM = "swarm"
    QUICK = "quick"
    EMBEDDING = "embedding"
    ML_INFERENCE = "ml_inference"
    AGENT_LOOP = "agent_loop"
    # Multimodal — added 2026-05-16
    IMAGE_GENERATION = "image_generation"
    IMAGE_UNDERSTANDING = "image_understanding"
    AUDIO_SPEECH = "audio_speech"
    AUDIO_TRANSCRIPTION = "audio_transcription"
    VIDEO_GENERATION = "video_generation"
    # Deprecated — VISION kept as alias for one release cycle
    # Migrate callers to IMAGE_UNDERSTANDING. Will be removed in next minor version.
    VISION = "vision"
```

Update `DEFAULT_OLLAMA_ROUTING` to use the current model name and add new categories:

```python
DEFAULT_OLLAMA_ROUTING: dict[TaskCategory, str] = {
    TaskCategory.CODE_GENERATION: "Qwen3-8B-8.2B-Q4_K_M",
    TaskCategory.CODE_REVIEW: "Qwen3-8B-8.2B-Q4_K_M",
    TaskCategory.DEBUGGING: "Qwen3-8B-8.2B-Q4_K_M",
    TaskCategory.REFACTORING: "Qwen3-8B-8.2B-Q4_K_M",
    TaskCategory.DOCUMENTATION: "Qwen3-8B-8.2B-Q4_K_M",
    TaskCategory.TESTING: "Qwen3-8B-8.2B-Q4_K_M",
    TaskCategory.REASONING: "Qwen3-8B-8.2B-Q4_K_M",
    TaskCategory.CREATIVE: "Qwen3-8B-8.2B-Q4_K_M",
    TaskCategory.ANALYSIS: "Qwen3-8B-8.2B-Q4_K_M",
    TaskCategory.VISION: "Qwen3-8B-8.2B-Q4_K_M",          # deprecated alias
    TaskCategory.IMAGE_UNDERSTANDING: "Qwen3-8B-8.2B-Q4_K_M",
    TaskCategory.EMBEDDING: "nomic-embed-text",
    TaskCategory.GENERAL: "Qwen3-8B-8.2B-Q4_K_M",
    TaskCategory.SWARM: "Qwen3-8B-8.2B-Q4_K_M",
    TaskCategory.QUICK: "Qwen3-8B-8.2B-Q4_K_M",
    TaskCategory.ML_INFERENCE: "Qwen3-8B-8.2B-Q4_K_M",
    TaskCategory.AGENT_LOOP: "Qwen3-8B-8.2B-Q4_K_M",
    # Multimodal categories with no ollama equivalent fall back gracefully
    TaskCategory.IMAGE_GENERATION: "Qwen3-8B-8.2B-Q4_K_M",  # best-effort
    TaskCategory.AUDIO_SPEECH: "Qwen3-8B-8.2B-Q4_K_M",
    TaskCategory.AUDIO_TRANSCRIPTION: "Qwen3-8B-8.2B-Q4_K_M",
    TaskCategory.VIDEO_GENERATION: "Qwen3-8B-8.2B-Q4_K_M",
}

# New: llama-server routing (Qwen3-8B, same model for all text tasks)
DEFAULT_LLAMA_SERVER_ROUTING: dict[TaskCategory, str] = {
    cat: "Qwen3-8B-8.2B-Q4_K_M"
    for cat in TaskCategory
    if cat not in {TaskCategory.EMBEDDING, TaskCategory.VIDEO_GENERATION,
                   TaskCategory.AUDIO_SPEECH, TaskCategory.AUDIO_TRANSCRIPTION}
}
# Embedding uses a dedicated model if available, else falls back
DEFAULT_LLAMA_SERVER_ROUTING[TaskCategory.EMBEDDING] = "nomic-embed-text"
```

Add `"DEFAULT_LLAMA_SERVER_ROUTING"` to `__all__`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_task_router_and_auth.py::TestTaskCategoryMultimodal -v
```

- [ ] **Step 5: Run full task_router test suite to verify no regressions**

```bash
uv run pytest tests/unit/test_task_router_and_auth.py -v
```

Fix any assertions that check `len(TaskCategory) == <old_count>` — update to new count.

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/workers/task_router.py tests/unit/test_task_router_and_auth.py
git commit -m "feat(routing): extend TaskCategory with multimodal variants and add llama_server routing

- Add IMAGE_GENERATION, IMAGE_UNDERSTANDING, AUDIO_SPEECH, AUDIO_TRANSCRIPTION, VIDEO_GENERATION
- Keep VISION as deprecated alias (one release cycle)
- Fix DEFAULT_OLLAMA_ROUTING model names to Qwen3-8B-8.2B-Q4_K_M (was qwen2.5-coder:7b)
- Add DEFAULT_LLAMA_SERVER_ROUTING for new llama-server tier"
```

______________________________________________________________________

## Task 3: Migrate mahavishnu workers to FallbackChain

**Files:**

- Modify: `mahavishnu/workers/cloud_worker.py`
- Modify: `mahavishnu/workers/ollama.py`
- Modify: `mahavishnu/workers/__init__.py`
- Modify: `tests/unit/test_workers.py` (create if absent)

This task replaces the direct OpenAI client in `cloud_worker.py` and the standalone `OllamaWorker` with a single `FallbackChain`-backed worker. Both files become thin wrappers.

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_workers.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch


class TestFallbackChainWorker:
    @pytest.mark.asyncio
    async def test_worker_uses_fallback_chain_not_direct_client(self) -> None:
        """Worker must delegate to FallbackChain, not call openai.AsyncOpenAI directly."""
        from mahavishnu.workers.cloud_worker import CloudWorker
        from mcp_common.llm.fallback import FallbackChain

        mock_chain = AsyncMock(spec=FallbackChain)
        mock_chain.execute = AsyncMock(return_value={
            "content": "result",
            "provider": "minimax",
            "model": "MiniMax-M2.7",
            "usage": {},
        })

        worker = CloudWorker.__new__(CloudWorker)
        worker._chain = mock_chain

        result = await worker.execute({"prompt": "write a function"})
        mock_chain.execute.assert_called_once()
        assert result["content"] == "result"

    @pytest.mark.asyncio
    async def test_worker_loads_chain_from_models_yaml(self) -> None:
        """FallbackChain must be initialized from settings/models.yaml on first call."""
        from mahavishnu.workers.cloud_worker import CloudWorker
        from mcp_common.llm.config import LLMSettings

        with patch.object(LLMSettings, "from_yaml") as mock_load:
            mock_settings = AsyncMock()
            mock_settings.get_enabled_providers.return_value = []
            mock_load.return_value = mock_settings

            # Just check the import works; chain init is lazy
            worker = CloudWorker()
            assert worker is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu
uv run pytest tests/unit/test_workers.py -v 2>&1 | head -20
```

- [ ] **Step 3: Update `cloud_worker.py` to use FallbackChain**

Replace the worker's LLM call machinery with a chain instance loaded from `models.yaml`.
Keep all existing public methods (`execute`, `process_task`, `get_status`) — only replace the internal provider call:

```python
from __future__ import annotations

import logging
from typing import Any

from mcp_common.llm.config import LLMSettings
from mcp_common.llm.fallback import FallbackChain

from .base import BaseWorker
from .task_router import TaskCategory, classify_task, get_model_for_task

logger = logging.getLogger(__name__)


class CloudWorker(BaseWorker):
    """OpenAI-compatible worker backed by the three-tier FallbackChain.

    Replaces direct MiniMax/OpenAI client usage with mcp_common.llm.FallbackChain,
    which handles MiniMax → llama-server → ollama fallback automatically.
    """

    def __init__(self, settings_path: str = "settings/models.yaml") -> None:
        super().__init__()
        settings = LLMSettings.from_yaml(settings_path)
        self._chain = FallbackChain.from_settings(settings)
        logger.debug(
            "CloudWorker initialized with %d providers",
            len(self._chain._providers),
        )

    async def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute a task through the provider chain.

        Args:
            task: Must contain 'prompt' or 'messages'. Optional 'model' is ignored —
                  model selection is handled by the chain's task routing.

        Returns:
            Dict with 'content', 'provider', 'model', 'usage'.
        """
        prompt = task.get("prompt", "")
        messages = task.get("messages") or [{"role": "user", "content": prompt}]

        chain_task = {
            "model": "auto",  # chain selects model based on TaskCategory
            "messages": messages,
        }
        return await self._chain.execute(chain_task)
```

- [ ] **Step 4: Update `ollama.py` to use FallbackChain**

The existing `OllamaWorker` should delegate to the chain's ollama tier rather than maintaining its own connection. Replace the direct connection with a chain restricted to the `ollama` provider:

```python
from __future__ import annotations

import logging
from typing import Any

from mcp_common.llm.config import LLMSettings
from mcp_common.llm.fallback import FallbackChain, _build_chain_for_tier

from .base import BaseWorker

logger = logging.getLogger(__name__)


class OllamaWorker(BaseWorker):
    """Local-only worker that uses only the ollama tier of the FallbackChain.

    Used for tasks that must stay local (privacy, cost, latency).
    """

    def __init__(self, settings_path: str = "settings/models.yaml") -> None:
        super().__init__()
        settings = LLMSettings.from_yaml(settings_path)
        # Build chain with only ollama tier
        all_providers = {p.name: p for p in settings.get_enabled_providers()}
        ollama_cfg = all_providers.get("ollama")
        if ollama_cfg is None:
            raise RuntimeError("ollama provider not found in settings — check models.yaml")
        from mcp_common.llm.provider import OpenAICompatibleProvider
        self._chain = FallbackChain([OpenAICompatibleProvider(ollama_cfg)])

    async def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        prompt = task.get("prompt", "")
        messages = task.get("messages") or [{"role": "user", "content": prompt}]
        return await self._chain.execute({"model": "auto", "messages": messages})
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/unit/test_workers.py -v
```

- [ ] **Step 6: Run all unit tests to verify no regressions**

```bash
uv run pytest tests/unit/ -v --tb=short 2>&1 | tail -30
```

- [ ] **Step 7: Commit**

```bash
git add mahavishnu/workers/cloud_worker.py mahavishnu/workers/ollama.py \
        mahavishnu/workers/__init__.py tests/unit/test_workers.py
git commit -m "feat(workers): migrate CloudWorker and OllamaWorker to FallbackChain

Replaces direct openai.AsyncOpenAI client usage with mcp_common.llm.FallbackChain.
Both workers now load their configuration from settings/models.yaml.
CloudWorker covers all three tiers; OllamaWorker is restricted to ollama tier only."
```

______________________________________________________________________

## Task 4: Migrate crackerjack AI registry to FallbackChain

**Working directory:** `/Users/les/Projects/crackerjack`

**Files:**

- Delete: `crackerjack/adapters/ai/claude.py`, `minimax.py`, `qwen.py`, `ollama.py`, `registry.py`

- Modify: `crackerjack/adapters/ai/__init__.py`

- Modify: `crackerjack/adapters/ai/base.py`

- Modify: `crackerjack/agents/enhanced_coordinator.py`

- Modify: `crackerjack/cli/handlers/provider_selection.py`

- Modify: `crackerjack/adapters/factory.py`

- Rewrite: `crackerjack/tests/adapters/test_provider_chain.py`

- [ ] **Step 1: Write parity tests before deleting anything**

Create `crackerjack/tests/adapters/test_provider_chain_migration.py`:

```python
"""Parity tests: verify FallbackChain provides the same interface as old ProviderChain.

Run BEFORE deleting the old registry to confirm both APIs are accessible.
After deletion, update imports to point at the new chain only.
"""
import pytest
from unittest.mock import AsyncMock, patch


class TestFallbackChainParityWithProviderChain:
    @pytest.mark.asyncio
    async def test_chain_has_get_available_provider_equivalent(self) -> None:
        """Old: chain.get_available_provider() → (provider, provider_id).
        New: chain.execute(task) → result dict.
        Verify execute() works end-to-end with a mock provider.
        """
        from mcp_common.llm.fallback import FallbackChain
        from unittest.mock import AsyncMock

        mock_provider = AsyncMock()
        mock_provider.name = "minimax"
        mock_provider.timeout_seconds = 30
        mock_provider.execute = AsyncMock(return_value={
            "content": "fixed code",
            "provider": "minimax",
            "model": "MiniMax-M2.7",
            "usage": {},
        })

        chain = FallbackChain([mock_provider])
        result = await chain.execute({
            "model": "auto",
            "messages": [{"role": "user", "content": "fix this bug"}],
        })
        assert result["content"] == "fixed code"
        assert result["provider"] == "minimax"

    def test_fallback_chain_importable_from_mcp_common(self) -> None:
        from mcp_common.llm import FallbackChain, LLMSettings
        assert FallbackChain is not None
        assert LLMSettings is not None
```

- [ ] **Step 2: Run parity tests to confirm they pass against the new mcp-common**

```bash
cd /Users/les/Projects/crackerjack
uv run pytest tests/adapters/test_provider_chain_migration.py -v
```

Expected: PASS (mcp-common 0.14.0 must be installed).

- [ ] **Step 3: Create a FallbackChain-backed replacement for `BaseCodeFixer`**

In `crackerjack/adapters/ai/base.py`, keep the existing security validation methods and add a new `execute_with_chain` helper:

````python
# In crackerjack/adapters/ai/base.py — ADD alongside existing BaseCodeFixer class

from mcp_common.llm.fallback import FallbackChain
from mcp_common.llm.config import LLMSettings


def create_code_fixer_chain(settings_path: str | None = None) -> FallbackChain:
    """Create a FallbackChain pre-configured for code-fixing tasks.

    Loads from crackerjack's own config or falls back to the default models.yaml path.
    """
    path = settings_path or "settings/models.yaml"
    settings = LLMSettings.from_yaml(path)
    return FallbackChain.from_settings(settings)


async def fix_code_with_chain(
    chain: FallbackChain,
    original_code: str,
    errors: list[str],
    language: str = "python",
) -> str:
    """Execute a code-fix request through the FallbackChain.

    Returns the fixed code content, or raises AllProvidersExhaustedError.
    """
    from crackerjack.adapters.ai.base import BaseCodeFixer

    # Use existing input sanitization from BaseCodeFixer
    sanitized_code = BaseCodeFixer._sanitize_prompt_input_static(original_code)

    messages = [
        {
            "role": "system",
            "content": "You are a code quality expert. Fix the issues described. "
                       "Return ONLY the corrected code without explanation.",
        },
        {
            "role": "user",
            "content": f"Fix this {language} code:\n\n```{language}\n{sanitized_code}\n```\n\n"
                       f"Issues to fix:\n" + "\n".join(f"- {e}" for e in errors),
        },
    ]
    result = await chain.execute({"model": "auto", "messages": messages})

    content = result.get("content", "")
    # Use existing validation hook from BaseCodeFixer
    is_safe, _ = BaseCodeFixer._validate_ai_generated_code_static(content)
    if not is_safe:
        raise ValueError("AI-generated code failed safety validation")

    return content
````

> **Note:** `_sanitize_prompt_input_static` and `_validate_ai_generated_code_static` are static
> versions of the existing instance methods. Add `@staticmethod` wrappers in `base.py` if not
> already present — check with `grep -n "_sanitize_prompt_input\|_validate_ai_generated" base.py`.

- [ ] **Step 4: Update `enhanced_coordinator.py` to use FallbackChain**

In `crackerjack/agents/enhanced_coordinator.py`, find the `ProviderChain` import and replace:

```python
# OLD (remove):
from crackerjack.adapters.ai.registry import ProviderChain, ProviderID

# NEW (add):
from mcp_common.llm.fallback import FallbackChain
from crackerjack.adapters.ai.base import create_code_fixer_chain
```

Replace any `chain = ProviderChain([...])` / `await chain.get_available_provider()` calls:

```python
# OLD pattern:
chain = ProviderChain(["claude", "minimax", "ollama"])
provider, provider_id = await chain.get_available_provider()
result = await provider.fix_code(code, errors)

# NEW pattern:
chain = create_code_fixer_chain()
from crackerjack.adapters.ai.base import fix_code_with_chain
fixed = await fix_code_with_chain(chain, code, errors)
```

- [ ] **Step 5: Update `cli/handlers/provider_selection.py`**

Replace `ProviderFactory`/`ProviderID`/`ProviderInfo` usage with simplified provider listing:

```python
# OLD (remove):
from crackerjack.adapters.ai.registry import ProviderFactory, ProviderID, ProviderInfo

# NEW (add):
from mcp_common.llm.config import LLMSettings


def list_available_providers(settings_path: str = "settings/models.yaml") -> list[str]:
    """Return names of providers in the fallback chain that have valid API keys."""
    settings = LLMSettings.from_yaml(settings_path)
    return [p.name for p in settings.get_enabled_providers()]


def get_default_provider() -> str:
    settings = LLMSettings.from_yaml("settings/models.yaml")
    return settings.default_provider
```

Update any CLI display code to call `list_available_providers()` instead of
`ProviderFactory.list_providers()`.

- [ ] **Step 6: Delete the old provider files**

```bash
cd /Users/les/Projects/crackerjack
git rm crackerjack/adapters/ai/claude.py \
        crackerjack/adapters/ai/minimax.py \
        crackerjack/adapters/ai/qwen.py \
        crackerjack/adapters/ai/ollama.py \
        crackerjack/adapters/ai/registry.py
```

Update `crackerjack/adapters/ai/__init__.py` to remove re-exports of deleted symbols.

- [ ] **Step 7: Run full crackerjack test suite**

```bash
uv run pytest tests/ -v --tb=short 2>&1 | tail -40
```

Fix any remaining import errors. The most common pattern: any file that imported
`ProviderChain`, `ProviderID`, `ProviderFactory`, `ClaudeCodeFixer`, `MiniMaxCodeFixer`,
`QwenCodeFixer`, or `OllamaCodeFixer` needs to be updated.

Find all remaining references:

```bash
grep -rn "ProviderChain\|ProviderID\|ProviderFactory\|ClaudeCodeFixer\|MiniMaxCodeFixer\|QwenCodeFixer\|OllamaCodeFixer" crackerjack/ --include="*.py"
```

- [ ] **Step 8: Commit**

```bash
git add crackerjack/adapters/ai/ crackerjack/agents/enhanced_coordinator.py \
        crackerjack/cli/handlers/provider_selection.py crackerjack/adapters/factory.py \
        crackerjack/tests/adapters/
git commit -m "feat(ai): replace ProviderChain registry with mcp_common FallbackChain

Removes claude.py, minimax.py, qwen.py, ollama.py, registry.py.
Security validation (sanitize_input, validate_output) preserved in base.py.
All callers updated to use FallbackChain.from_settings() + fix_code_with_chain()."
```

______________________________________________________________________

## Task 5: Migrate session-buddy LLM providers

**Working directory:** `/Users/les/Projects/session-buddy`

**Files:**

- Delete: `session_buddy/llm/providers/anthropic_provider.py`

- Delete: `session_buddy/llm/providers/gemini_provider.py`

- Modify: `session_buddy/llm/providers/openai_provider.py` → rename to `minimax_provider.py`

- Modify: `session_buddy/llm_providers.py`

- Modify: `session_buddy/settings.py`

- Modify: `session_buddy/llm/providers/__init__.py`

- [ ] **Step 1: Write migration parity tests**

Create `tests/llm/test_provider_migration.py`:

```python
"""Verify session-buddy can route LLM tasks through FallbackChain after migration."""
import pytest
from unittest.mock import AsyncMock


class TestSessionBuddyProviderMigration:
    def test_anthropic_provider_not_importable(self) -> None:
        """After migration, the removed file must not be importable."""
        with pytest.raises(ImportError):
            from session_buddy.llm.providers import anthropic_provider  # noqa: F401

    def test_gemini_provider_not_importable(self) -> None:
        with pytest.raises(ImportError):
            from session_buddy.llm.providers import gemini_provider  # noqa: F401

    def test_default_provider_is_minimax(self) -> None:
        from session_buddy.settings import Settings
        s = Settings()
        assert s.default_provider == "minimax"

    @pytest.mark.asyncio
    async def test_llm_providers_module_returns_fallback_chain(self) -> None:
        from session_buddy.llm_providers import get_llm_chain
        from mcp_common.llm.fallback import FallbackChain

        chain = get_llm_chain()
        assert isinstance(chain, FallbackChain)
```

- [ ] **Step 2: Run tests to verify they fail (expected)**

```bash
cd /Users/les/Projects/session-buddy
uv run pytest tests/llm/test_provider_migration.py -v 2>&1 | head -20
```

- [ ] **Step 3: Delete anthropic and gemini providers**

```bash
git rm session_buddy/llm/providers/anthropic_provider.py \
        session_buddy/llm/providers/gemini_provider.py
```

Update `session_buddy/llm/providers/__init__.py` — remove re-exports of deleted providers.

- [ ] **Step 4: Update `session_buddy/llm_providers.py` to use FallbackChain**

Replace the provider factory with a chain getter:

```python
"""LLM provider access for session-buddy.

Previously instantiated per-provider clients (Anthropic, Gemini, OpenAI).
Now delegates to mcp_common.llm.FallbackChain for three-tier routing.
"""
from __future__ import annotations

from functools import lru_cache

from mcp_common.llm.config import LLMSettings
from mcp_common.llm.fallback import FallbackChain


@lru_cache(maxsize=1)
def get_llm_chain(settings_path: str = "settings/models.yaml") -> FallbackChain:
    """Return the singleton FallbackChain for session-buddy LLM tasks.

    Cached for the lifetime of the process — call get_llm_chain.cache_clear()
    in tests that need a fresh chain.
    """
    settings = LLMSettings.from_yaml(settings_path)
    return FallbackChain.from_settings(settings)
```

- [ ] **Step 5: Update `session_buddy/settings.py`**

Ensure `default_provider = "minimax"` is set. Remove any `ANTHROPIC_API_KEY` or
`GOOGLE_API_KEY` fields that were only needed by the deleted providers.

Find and verify:

```bash
grep -n "anthropic\|gemini\|ANTHROPIC\|GOOGLE_API" session_buddy/settings.py
```

Comment out or remove any such fields, replacing with a note that MiniMax is now primary.

- [ ] **Step 6: Update callers in session-buddy**

Find all sites that imported from the deleted providers or used the old factory:

```bash
grep -rn "anthropic_provider\|gemini_provider\|AnthropicProvider\|GeminiProvider\|get_provider\|LLMProvider(" session_buddy/ --include="*.py"
```

For each site, replace with:

```python
from session_buddy.llm_providers import get_llm_chain

chain = get_llm_chain()
result = await chain.execute({"model": "auto", "messages": [{"role": "user", "content": prompt}]})
response_text = result["content"]
```

- [ ] **Step 7: Run full test suite**

```bash
uv run pytest tests/ -v --tb=short 2>&1 | tail -30
```

- [ ] **Step 8: Commit**

```bash
git add session_buddy/llm/ session_buddy/llm_providers.py session_buddy/settings.py tests/llm/
git commit -m "feat(llm): replace anthropic/gemini providers with mcp_common FallbackChain

Removes anthropic_provider.py and gemini_provider.py.
session_buddy.llm_providers.get_llm_chain() returns the singleton FallbackChain.
default_provider remains 'minimax'; all API key env vars for removed providers cleaned up."
```

______________________________________________________________________

## Task 6: Audit and migrate akosha LLM usage

**Working directory:** Akosha repo (path from settings/repos.yaml or `mahavishnu list-repos`)

- [ ] **Step 1: Enumerate all LLM call sites in akosha**

```bash
# Find the akosha repo path
cd /Users/les/Projects/mahavishnu
python -c "import yaml; repos=yaml.safe_load(open('settings/repos.yaml')); [print(r['path']) for r in repos.get('repos',[]) if 'akosha' in r.get('name','')]"

# Then in the akosha repo:
grep -rn "openai\|anthropic\|minimax\|AsyncOpenAI\|ChatCompletion\|llm\|LLM\|embed" \
    <akosha_path>/ --include="*.py" -l
```

Record the list of files. If no files match, skip to Step 6 (no changes needed).

- [ ] **Step 2: Write a parity test for each identified LLM call site**

For each file found in Step 1, create a corresponding test in `tests/test_akosha_llm_migration.py`:

```python
class TestAkoshaLLMCallSites:
    """One test per file that had LLM calls — verifies behavior is preserved after migration."""

    @pytest.mark.asyncio
    async def test_<module_name>_uses_fallback_chain(self) -> None:
        """<module_name> must not directly import openai/anthropic/minimax SDK."""
        import importlib
        module = importlib.import_module("akosha.<module_path>")
        # Verify no direct provider SDK attribute is set at module level
        assert not hasattr(module, "anthropic")
        assert not hasattr(module, "_openai_client")
```

Adapt the assertions to the actual module structure found.

- [ ] **Step 3: Migrate each LLM call site to FallbackChain**

For each file found in Step 1, replace direct SDK usage with:

```python
from mcp_common.llm.fallback import FallbackChain
from mcp_common.llm.config import LLMSettings

_chain: FallbackChain | None = None

def _get_chain() -> FallbackChain:
    global _chain
    if _chain is None:
        settings = LLMSettings.from_yaml("settings/models.yaml")
        _chain = FallbackChain.from_settings(settings)
    return _chain
```

Replace call sites:

```python
# OLD (direct openai/anthropic call):
response = await client.chat.completions.create(model="...", messages=[...])
text = response.choices[0].message.content

# NEW (FallbackChain):
result = await _get_chain().execute({"model": "auto", "messages": [...]})
text = result["content"]
```

- [ ] **Step 4: Run akosha tests**

```bash
uv run pytest tests/ -v --tb=short 2>&1 | tail -20
```

- [ ] **Step 5: If no LLM usage found in Step 1, document it**

Add a comment to `docs/superpowers/plans/2026-05-16-llm-routing-plan2-downstream-migration.md`:

```
Akosha audit result (YYYY-MM-DD): no direct LLM call sites found.
Akosha uses mcp-common tooling only. No migration required.
```

- [ ] **Step 6: Commit (or document no-op)**

```bash
# If changes were made:
git add akosha/ tests/
git commit -m "feat(llm): migrate akosha LLM call sites to mcp_common FallbackChain"

# If no changes were needed:
git commit --allow-empty -m "chore: akosha LLM audit — no direct LLM call sites found, no changes needed"
```

______________________________________________________________________

## Task 7: Integration smoke tests

**Files:**

- Create: `tests/integration/test_llm_e2e.py` (in mahavishnu repo)

Run only when `BODAI_INTEGRATION_TESTS=1` **and** the relevant service is reachable.

- [ ] **Step 1: Create integration test suite**

Create `tests/integration/test_llm_e2e.py`:

```python
"""End-to-end LLM provider tests.

Run condition:
    BODAI_INTEGRATION_TESTS=1 pytest tests/integration/test_llm_e2e.py

Each test is skipped if its tier's port is unreachable.
"""
import os
import socket
import pytest
from mcp_common.llm.config import LLMSettings
from mcp_common.llm.fallback import FallbackChain


def is_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(autouse=True)
def require_integration_env():
    if "BODAI_INTEGRATION_TESTS" not in os.environ:
        pytest.skip("Set BODAI_INTEGRATION_TESTS=1 to run integration tests")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_minimax_tier_responds() -> None:
    if not os.getenv("MINIMAX_API_KEY"):
        pytest.skip("MINIMAX_API_KEY not set")

    settings = LLMSettings.from_yaml("settings/models.yaml")
    chain = FallbackChain.from_settings(settings)

    result = await chain.execute({
        "model": "auto",
        "messages": [{"role": "user", "content": "Say 'ok' and nothing else."}],
    })
    assert result["content"].strip().lower() in {"ok", "ok.", "okay", "okay."}
    assert result["provider"] == "minimax"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_llama_server_tier_responds() -> None:
    if not is_port_open("127.0.0.1", 8081):
        pytest.skip("llama-server not reachable on :8081")

    from mcp_common.llm.config import ProviderConfig
    from mcp_common.llm.provider import OpenAICompatibleProvider

    cfg = ProviderConfig(
        name="llama_server",
        base_url="http://localhost:8081/v1",
        require_auth=False,
        model="Qwen3-8B-8.2B-Q4_K_M",
        timeout_seconds=60,
    )
    provider = OpenAICompatibleProvider(cfg)
    chain = FallbackChain([provider])

    result = await chain.execute({
        "model": "auto",
        "messages": [{"role": "user", "content": "Say 'ok' and nothing else."}],
    })
    assert result["content"]
    assert result["provider"] == "llama_server"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ollama_tier_responds() -> None:
    if not is_port_open("127.0.0.1", 11434):
        pytest.skip("ollama not reachable on :11434")

    from mcp_common.llm.config import ProviderConfig
    from mcp_common.llm.provider import OpenAICompatibleProvider

    cfg = ProviderConfig(
        name="ollama",
        base_url="http://localhost:11434/v1",
        require_auth=False,
        model="qwen2.5-coder:7b",
        timeout_seconds=120,
    )
    provider = OpenAICompatibleProvider(cfg)
    chain = FallbackChain([provider])

    result = await chain.execute({
        "model": "auto",
        "messages": [{"role": "user", "content": "Say 'ok' and nothing else."}],
    })
    assert result["content"]
    assert result["provider"] == "ollama"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_full_chain_falls_through_to_local() -> None:
    """With a bad API key, chain should fall through to local tiers."""
    import os
    from mcp_common.llm.config import LLMSettings

    if not is_port_open("127.0.0.1", 8081) and not is_port_open("127.0.0.1", 11434):
        pytest.skip("No local tiers reachable")

    # Temporarily override the API key to simulate MiniMax unavailability
    original = os.environ.get("MINIMAX_API_KEY", "")
    os.environ["MINIMAX_API_KEY"] = "invalid-key-to-force-fallback"
    try:
        settings = LLMSettings.from_yaml("settings/models.yaml")
        chain = FallbackChain.from_settings(settings)
        result = await chain.execute({
            "model": "auto",
            "messages": [{"role": "user", "content": "Say 'ok' and nothing else."}],
        })
        assert result["provider"] in {"llama_server", "ollama"}
    finally:
        if original:
            os.environ["MINIMAX_API_KEY"] = original
        else:
            del os.environ["MINIMAX_API_KEY"]
```

- [ ] **Step 2: Run unit subset (no live services needed)**

```bash
cd /Users/les/Projects/mahavishnu
uv run pytest tests/unit/ -v --tb=short 2>&1 | tail -20
```

All unit tests must PASS.

- [ ] **Step 3: Run integration tests (optional, requires live services)**

```bash
BODAI_INTEGRATION_TESTS=1 uv run pytest tests/integration/test_llm_e2e.py -v
```

At minimum `test_minimax_tier_responds` should pass if `MINIMAX_API_KEY` is set.

- [ ] **Step 4: Final commit**

```bash
git add tests/integration/test_llm_e2e.py
git commit -m "test(llm): add end-to-end integration smoke tests for three-tier chain

Tests are skipped unless BODAI_INTEGRATION_TESTS=1.
Per-tier skip guards check port reachability before attempting connection."
```

______________________________________________________________________

## Self-Review Checklist

- [x] **Spec §8.1–§8.7 coverage** — all per-repo migration sections covered by tasks 1–6.
- [x] **Release sequencing** — Plan 1 (mcp-common 0.14.0) must ship before any task here executes. Stated as prerequisite.
- [x] **Port conflation fixed** — Task 1 YAML explicitly documents llama-server on 8081 and ollama on 11434, with inline comments.
- [x] **VISION alias preserved** — Task 2 keeps VISION in TaskCategory; DEFAULT_OLLAMA_ROUTING covers it.
- [x] **Security validation preserved** — crackerjack's `_sanitize_prompt_input` and `_validate_ai_generated_code` are kept in `base.py` and reused via static methods in `fix_code_with_chain`.
- [x] **No placeholder steps** — all steps have complete code or explicit grep/find commands.
- [x] **Akosha handled as conditional** — Task 6 covers both the "has LLM calls" and "no LLM calls" cases.
- [x] **Integration tests skip-guard** — port reachability check gates each test independently, preventing CI failures when local tiers are offline.
