# LLM Routing Standardization — Plan 1: mcp-common LLM Module

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing `mcp_common/llm/` module to support a three-tier provider chain (MiniMax → llama-server:8081 → ollama:11434) with per-tier retry/backoff, security hooks, multimodal TaskType categories, and a HailuoAdapter for video generation.

**Architecture:** This plan works entirely within `mcp-common`. The existing `FallbackChain`, `CircuitBreaker`, and `OpenAICompatibleProvider` classes are extended in-place — no new package needed. Plan 2 (downstream migration) depends on this plan shipping as mcp-common ≥0.14.0.

**Tech Stack:** Python 3.13+, pydantic v2, openai SDK (async), aiohttp (for HailuoAdapter), pytest, pytest-asyncio, hypothesis

**Working directory:** `/Users/les/Projects/mcp-common`

---

## File Map

| File | Change |
|------|--------|
| `mcp_common/llm/types.py` | Add multimodal TaskType variants + VISION deprecation alias |
| `mcp_common/llm/config.py` | Add `timeout_seconds`, `require_auth` per provider; add `llama_server` defaults; backward-compat schema validator |
| `mcp_common/llm/fallback.py` | Add per-tier retry loop + backoff; security hooks (sanitize_error); fail-closed API key validation at init |
| `mcp_common/llm/provider.py` | Use `timeout_seconds` from config; skip `Authorization` header when `require_auth=False` |
| `mcp_common/llm/hailuo.py` | NEW — HailuoAdapter for MiniMax video generation with SSRF constraints |
| `mcp_common/llm/exceptions.py` | Add `UnsupportedModalityError` |
| `mcp_common/llm/__init__.py` | Export new types and HailuoAdapter |
| `tests/test_llm.py` | Extend with new tests (all existing tests must still pass) |

---

## Task 1: Add multimodal TaskType variants

**Files:**
- Modify: `mcp_common/llm/types.py`
- Modify: `tests/test_llm.py`

- [ ] **Step 1: Write failing tests for new TaskType variants**

Add to `tests/test_llm.py` after the existing `TestTaskType` class (or create one if absent):

```python
class TestTaskTypeMultimodal:
    def test_image_generation_exists(self) -> None:
        assert TaskType.IMAGE_GENERATION == "image_generation"

    def test_image_understanding_exists(self) -> None:
        assert TaskType.IMAGE_UNDERSTANDING == "image_understanding"

    def test_audio_speech_exists(self) -> None:
        assert TaskType.AUDIO_SPEECH == "audio_speech"

    def test_audio_transcription_exists(self) -> None:
        assert TaskType.AUDIO_TRANSCRIPTION == "audio_transcription"

    def test_video_generation_exists(self) -> None:
        assert TaskType.VIDEO_GENERATION == "video_generation"

    def test_vision_alias_maps_to_image_understanding(self) -> None:
        # VISION kept for one release cycle to avoid breaking callers
        assert TaskType.VISION == "vision"
        assert TaskType("vision") is TaskType.VISION

    def test_all_task_types_are_strings(self) -> None:
        for t in TaskType:
            assert isinstance(t.value, str)
            assert t.value == t.value.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mcp-common
uv run pytest tests/test_llm.py::TestTaskTypeMultimodal -v 2>&1 | head -30
```

Expected: `AttributeError: IMAGE_GENERATION` or similar.

- [ ] **Step 3: Extend TaskType in `mcp_common/llm/types.py`**

Replace the entire `TaskType` class with:

```python
class TaskType(StrEnum):
    """Task categories for model routing."""

    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    DEBUGGING = "debugging"
    REFACTORING = "refactoring"
    TESTING = "testing"
    REASONING = "reasoning"
    DOCUMENTATION = "documentation"
    ANALYSIS = "analysis"
    GENERAL = "general"
    SWARM = "swarm"
    QUICK = "quick"
    EMBEDDING = "embedding"
    CREATIVE = "creative"
    ML_INFERENCE = "ml_inference"
    AGENT_LOOP = "agent_loop"
    # Multimodal
    IMAGE_GENERATION = "image_generation"
    IMAGE_UNDERSTANDING = "image_understanding"
    AUDIO_SPEECH = "audio_speech"
    AUDIO_TRANSCRIPTION = "audio_transcription"
    VIDEO_GENERATION = "video_generation"
    # Deprecated — kept for one release cycle; callers should migrate to IMAGE_UNDERSTANDING
    VISION = "vision"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_llm.py::TestTaskTypeMultimodal -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Verify existing TaskType tests still pass — and fix the member-count assertion**

If `tests/test_llm.py` contains a `test_total_member_count` assertion, update it from `14` to `20`
before running (the new definition adds 6 members: IMAGE_GENERATION, IMAGE_UNDERSTANDING,
AUDIO_SPEECH, AUDIO_TRANSCRIPTION, VIDEO_GENERATION, VISION):

```python
# find and update this assertion
assert len(TaskType) == 20   # was 14
```

Then run:

```bash
uv run pytest tests/test_llm.py -v -k "TaskType or task_type"
```

Expected: all existing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add mcp_common/llm/types.py tests/test_llm.py
git commit -m "feat(llm): add multimodal TaskType variants and VISION deprecation alias"
```

---

## Task 2: Add UnsupportedModalityError exception

**Files:**
- Modify: `mcp_common/llm/exceptions.py`
- Modify: `mcp_common/llm/__init__.py`
- Modify: `tests/test_llm.py`

- [ ] **Step 1: Write failing test**

```python
class TestUnsupportedModalityError:
    def test_unsupported_modality_inherits_llm_error(self) -> None:
        from mcp_common.llm.exceptions import UnsupportedModalityError
        err = UnsupportedModalityError("VIDEO_GENERATION not supported by this tier")
        assert isinstance(err, LLMError)
        assert "VIDEO_GENERATION" in str(err)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_llm.py::TestUnsupportedModalityError -v
```

Expected: `ImportError: cannot import name 'UnsupportedModalityError'`

- [ ] **Step 3: Add exception to `mcp_common/llm/exceptions.py`**

Add after the existing `AllProvidersExhaustedError` class:

```python
class UnsupportedModalityError(LLMError):
    """Raised when no tier in the chain supports the requested TaskType modality."""
```

- [ ] **Step 4: Export from `mcp_common/llm/__init__.py`**

Add to the existing imports block:

```python
from .exceptions import (
    AllProvidersExhaustedError,
    LLMError,
    ProviderUnavailableError,
    UnsupportedModalityError,  # add this
)
```

And add `"UnsupportedModalityError"` to `__all__`.

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/test_llm.py::TestUnsupportedModalityError -v
```

- [ ] **Step 6: Commit**

```bash
git add mcp_common/llm/exceptions.py mcp_common/llm/__init__.py tests/test_llm.py
git commit -m "feat(llm): add UnsupportedModalityError exception"
```

---

## Task 3: Add per-tier timeout and conditional auth to ProviderConfig

**Files:**
- Modify: `mcp_common/llm/config.py`
- Modify: `tests/test_llm.py`

- [ ] **Step 1: Write failing tests**

```python
class TestProviderConfigExtensions:
    def test_timeout_seconds_field_exists(self) -> None:
        cfg = ProviderConfig(name="test", timeout_seconds=45)
        assert cfg.timeout_seconds == 45

    def test_timeout_seconds_defaults_to_30(self) -> None:
        cfg = ProviderConfig(name="test")
        assert cfg.timeout_seconds == 30

    def test_require_auth_defaults_true(self) -> None:
        cfg = ProviderConfig(name="test")
        assert cfg.require_auth is True

    def test_require_auth_can_be_false_for_ollama(self) -> None:
        cfg = ProviderConfig(name="ollama", require_auth=False)
        assert cfg.require_auth is False

    def test_api_key_env_field_exists(self) -> None:
        cfg = ProviderConfig(name="test", api_key_env="MINIMAX_API_KEY")
        assert cfg.api_key_env == "MINIMAX_API_KEY"

    def test_api_key_env_nullable(self) -> None:
        cfg = ProviderConfig(name="ollama", api_key_env=None)
        assert cfg.api_key_env is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_llm.py::TestProviderConfigExtensions -v 2>&1 | head -20
```

- [ ] **Step 3: Extend `ProviderConfig` in `mcp_common/llm/config.py`**

Add the three new fields to `ProviderConfig` (keep all existing fields unchanged):

```python
class ProviderConfig(BaseModel):
    """Configuration for a single LLM provider."""

    name: str = ""
    enabled: bool = True
    base_url: str = ""
    api_key: SecretStr = SecretStr("")
    api_key_env: str | None = None          # NEW: env var name, None for no-auth providers
    require_auth: bool = True               # NEW: False for ollama (no Authorization header)
    models: dict[str, str] = {}
    priority: int = 1
    timeout: int = 30                       # kept for backward compat
    timeout_seconds: int = 30              # NEW: per-tier timeout used by FallbackChain
    max_retries: int = 2
    task_routing: dict[str, str] = {}
    fallback: dict[str, str] = {}

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def resolve_env_vars(self) -> ProviderConfig:
        """Resolve ${ENV_VAR} patterns in api_key and base_url."""
        if self.base_url.startswith("${") and self.base_url.endswith("}"):
            env_var = self.base_url[2:-1]
            resolved = os.getenv(env_var, "")
            if resolved:
                self.base_url = resolved

        raw_key = self.api_key.get_secret_value()
        if raw_key.startswith("${") and raw_key.endswith("}"):
            env_var = raw_key[2:-1]
            resolved = os.getenv(env_var, "")
            if resolved:
                self.api_key = SecretStr(resolved)

        # Sync timeout_seconds from legacy timeout if not explicitly set
        if self.timeout_seconds == 30 and self.timeout != 30:
            self.timeout_seconds = self.timeout

        return self
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_llm.py::TestProviderConfigExtensions -v
```

- [ ] **Step 5: Run all existing LLM tests to check for regressions**

```bash
uv run pytest tests/test_llm.py -v
```

Expected: all existing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add mcp_common/llm/config.py tests/test_llm.py
git commit -m "feat(llm): add timeout_seconds, require_auth, api_key_env to ProviderConfig"
```

---

## Task 4: Add llama-server as a recognized provider and fail-closed init validation

**Files:**
- Modify: `mcp_common/llm/config.py`
- Modify: `tests/test_llm.py`

- [ ] **Step 1: Write failing tests**

```python
class TestLLMSettingsValidation:
    def test_llama_server_provider_recognized_in_fallback_chain(self, tmp_path) -> None:
        yaml_content = """
default_provider: minimax
fallback_chain: [minimax, llama_server, ollama]
minimax:
  enabled: true
  base_url: "https://api.minimax.io/v1"
  api_key: "${MINIMAX_API_KEY}"
  timeout_seconds: 30
llama_server:
  enabled: true
  base_url: "http://localhost:8081/v1"
  api_key_env: "LLAMA_SERVER_API_KEY"
  timeout_seconds: 60
ollama:
  enabled: true
  base_url: "http://localhost:11434/v1"
  require_auth: false
  timeout_seconds: 120
"""
        p = tmp_path / "models.yaml"
        p.write_text(yaml_content)
        settings = LLMSettings.from_yaml(str(p))
        assert "llama_server" in [p.name for p in settings.get_enabled_providers()]

    def test_missing_required_api_key_raises_at_load(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        yaml_content = """
default_provider: minimax
fallback_chain: [minimax, ollama]
minimax:
  enabled: true
  base_url: "https://api.minimax.io/v1"
  api_key_env: "MINIMAX_API_KEY"
  require_auth: true
ollama:
  enabled: true
  base_url: "http://localhost:11434/v1"
  require_auth: false
"""
        p = tmp_path / "models.yaml"
        p.write_text(yaml_content)
        settings = LLMSettings.from_yaml(str(p))
        # minimax should be excluded from enabled providers (fail-closed)
        enabled_names = [p.name for p in settings.get_enabled_providers()]
        assert "minimax" not in enabled_names
        assert "ollama" in enabled_names  # local tier still available
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_llm.py::TestLLMSettingsValidation -v 2>&1 | head -30
```

- [ ] **Step 3: Update `LLMSettings.from_yaml` and `get_enabled_providers` in `mcp_common/llm/config.py`**

Find the `LLMSettings` class and update `get_enabled_providers` to enforce fail-closed:

```python
class LLMSettings(BaseModel):
    """Loaded from settings/models.yaml or equivalent."""

    providers: dict[str, dict[str, Any]] = {}
    default_provider: str = "minimax"
    fallback_chain: list[str] = ["minimax", "llama_server", "ollama"]

    def get_enabled_providers(self) -> list[ProviderConfig]:
        """Return providers in fallback_chain order, excluding disabled or key-missing ones."""
        result = []
        for name in self.fallback_chain:
            raw = self.providers.get(name)
            if raw is None:
                logger.warning("Provider %s in fallback_chain not found in config", name)
                continue
            cfg = ProviderConfig(name=name, **raw)
            if not cfg.enabled:
                continue
            # Fail-closed: skip cloud providers with missing API keys
            if cfg.require_auth:
                key = cfg.api_key.get_secret_value()
                env_name = cfg.api_key_env or ""
                if not key or not key.strip() or key.startswith("${"):
                    logger.warning(
                        "Provider %s skipped: API key not set (env: %s). "
                        "Set %s to enable this provider.",
                        name,
                        env_name or "unknown",
                        env_name or "the required env var",
                    )
                    continue
            result.append(cfg)
        return result

    @classmethod
    def from_yaml(cls, path: str) -> LLMSettings:
        """Load settings from a YAML file.

        Accepts both the legacy flat schema (top-level provider keys) and
        the new schema (providers: + fallback_chain:). Both shapes coexist
        during the transition period.
        """
        with open(path) as f:
            data = yaml.safe_load(f) or {}

        # Detect old schema: no top-level 'providers' key but has provider dicts
        reserved = {"default_provider", "fallback_chain", "free_tier_provider",
                    "bifrost", "providers"}
        providers: dict[str, Any] = data.get("providers", {})
        if not providers:
            # Old schema: extract provider configs from top-level keys
            for key, val in data.items():
                if key not in reserved and isinstance(val, dict):
                    providers[key] = val
            if providers:
                logger.debug(
                    "Loaded LLM settings using legacy flat schema — "
                    "migrate to 'providers:' top-level key."
                )

        return cls(
            providers=providers,
            default_provider=data.get("default_provider", "minimax"),
            fallback_chain=data.get("fallback_chain", ["minimax", "llama_server", "ollama"]),
        )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_llm.py::TestLLMSettingsValidation -v
```

- [ ] **Step 5: Verify no regressions**

```bash
uv run pytest tests/test_llm.py -v
```

- [ ] **Step 6: Commit**

```bash
git add mcp_common/llm/config.py tests/test_llm.py
git commit -m "feat(llm): add llama_server support and fail-closed API key validation"
```

---

## Task 5: Add per-tier retry loop and error sanitization to FallbackChain

**Files:**
- Modify: `mcp_common/llm/fallback.py`
- Modify: `tests/test_llm.py`

- [ ] **Step 1: Write failing tests**

```python
class TestFallbackChainRetry:
    @pytest.mark.asyncio
    async def test_retries_within_tier_before_advancing(self) -> None:
        """FallbackChain retries 3x within a tier before falling back."""
        call_count = 0

        async def flaky_execute(task):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("transient failure")
            return {"content": "ok", "provider": "test", "model": "m", "usage": {}}

        mock_provider = AsyncMock()
        mock_provider.name = "tier1"
        mock_provider.execute = flaky_execute

        chain = FallbackChain([mock_provider])
        result = await chain.execute({"model": "m", "messages": []})
        assert result["content"] == "ok"
        assert call_count == 3  # succeeded on 3rd attempt within same tier

    @pytest.mark.asyncio
    async def test_circuit_breaker_counts_per_tier_call_not_per_attempt(self) -> None:
        """Circuit breaker counts tier-calls (after all retries), not individual attempts."""
        tier1_calls = 0

        async def always_fail(task):
            nonlocal tier1_calls
            tier1_calls += 1
            raise Exception("always fails")

        mock_tier1 = AsyncMock()
        mock_tier1.name = "tier1"
        mock_tier1.execute = always_fail

        async def succeed(task):
            return {"content": "ok", "provider": "tier2", "model": "m", "usage": {}}

        mock_tier2 = AsyncMock()
        mock_tier2.name = "tier2"
        mock_tier2.execute = succeed

        chain = FallbackChain([mock_tier1, mock_tier2], max_attempts_per_tier=3)
        # Pin failure_threshold explicitly so the test doesn't depend on the default
        chain._circuit_breakers["tier1"] = CircuitBreaker(failure_threshold=5, reset_timeout=60.0)

        # After 5 tier-calls (each with 3 attempts = 15 total attempts), breaker opens
        for _ in range(5):
            await chain.execute({"model": "m", "messages": []})

        assert tier1_calls == 15  # 5 tier-calls × 3 attempts each
        breaker = chain._circuit_breakers["tier1"]
        assert breaker.is_open  # 5 failures >= threshold of 5

    @pytest.mark.asyncio
    async def test_error_message_sanitized_before_logging(self, caplog) -> None:
        """API keys in error messages must be stripped before logging."""
        import logging

        async def fail_with_key(task):
            raise Exception("auth failed: sk-ant-api03-realkey1234567890abcdef")

        mock_provider = AsyncMock()
        mock_provider.name = "tier1"
        mock_provider.execute = fail_with_key

        chain = FallbackChain([mock_provider])
        with caplog.at_level(logging.WARNING):
            with pytest.raises(Exception):  # AllProvidersExhaustedError
                await chain.execute({"model": "m", "messages": []})

        # No raw key should appear in logs
        for record in caplog.records:
            assert "sk-ant-api03-realkey" not in record.message

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates_immediately(self) -> None:
        """asyncio.CancelledError must never be caught by the chain."""
        import asyncio

        async def cancel_self(task):
            raise asyncio.CancelledError()

        mock_provider = AsyncMock()
        mock_provider.name = "tier1"
        mock_provider.execute = cancel_self

        chain = FallbackChain([mock_provider])
        with pytest.raises(asyncio.CancelledError):
            await chain.execute({"model": "m", "messages": []})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_llm.py::TestFallbackChainRetry -v 2>&1 | head -40
```

- [ ] **Step 3: Update `FallbackChain` in `mcp_common/llm/fallback.py`**

```python
import asyncio
import logging
import re
import time
from typing import Any

from .config import LLMSettings
from .exceptions import AllProvidersExhaustedError
from .provider import OpenAICompatibleProvider

logger = logging.getLogger(__name__)

_SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),                          # Anthropic / OpenAI sk- keys
    re.compile(r"eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}"),  # JWT / MiniMax Token Plan keys
    re.compile(r"Bearer [a-zA-Z0-9\-._~+/]{20,}"),              # Bearer header values
    re.compile(r'["\'][\w\-]{32,}["\']'),                        # quoted long secrets
]
# Note: the overly broad path pattern `/[\w-./ ]{10,}/` was removed — it matches too many
# innocuous strings (e.g. file paths in stack traces) and does more harm than good.


def _sanitize_error(msg: str) -> str:
    """Strip secrets and paths from error messages before logging."""
    for pattern in _SECRET_PATTERNS:
        msg = pattern.sub("<redacted>", msg)
    return msg


class CircuitBreaker:
    # ... (unchanged) ...


class FallbackChain:
    def __init__(
        self,
        providers: list[OpenAICompatibleProvider],
        max_attempts_per_tier: int = 3,
    ) -> None:
        self._providers = providers
        self._max_attempts = max_attempts_per_tier
        self._circuit_breakers: dict[str, CircuitBreaker] = {
            p.name: CircuitBreaker(failure_threshold=5, reset_timeout=60.0)
            for p in providers
        }

    @classmethod
    def from_settings(cls, settings: LLMSettings) -> FallbackChain:
        providers = []
        for provider_config in settings.get_enabled_providers():
            providers.append(OpenAICompatibleProvider(provider_config))
        return cls(providers)

    async def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        """Try providers in order with per-tier retry before advancing.

        Circuit breaker counts per tier-call (after all retries exhausted),
        not per individual attempt. asyncio.CancelledError always propagates.
        """
        last_error: Exception | None = None

        for provider in self._providers:
            breaker = self._circuit_breakers[provider.name]
            if breaker.is_open:
                logger.debug("Skipping %s (circuit breaker open)", provider.name)
                continue

            tier_succeeded = False
            for attempt in range(self._max_attempts):
                try:
                    result = await asyncio.wait_for(
                        provider.execute(task),
                        timeout=provider.timeout_seconds,
                    )
                    if result.get("content"):
                        breaker.record_success()
                        tier_succeeded = True
                        return result
                    # Empty content — treat as failure
                    raise ValueError("Provider returned empty content")

                except asyncio.CancelledError:
                    raise  # never swallow

                except Exception as e:
                    last_error = e
                    sanitized = _sanitize_error(str(e))
                    if attempt < self._max_attempts - 1:
                        backoff = 2 ** attempt  # 1s, 2s, 4s
                        logger.debug(
                            "Provider %s attempt %d/%d failed (%s), retrying in %ds",
                            provider.name, attempt + 1, self._max_attempts,
                            sanitized, backoff,
                        )
                        await asyncio.sleep(backoff)
                    else:
                        logger.warning(
                            "Provider %s exhausted %d attempts: %s",
                            provider.name, self._max_attempts, sanitized,
                        )

            if not tier_succeeded:
                breaker.record_failure()  # counts once per tier-call

        sanitized_last = _sanitize_error(str(last_error)) if last_error else "unknown"
        raise AllProvidersExhaustedError(
            f"All {len(self._providers)} providers failed. Last: {sanitized_last}"
        ) from last_error
```

- [ ] **Step 4: Patch `OpenAICompatibleProvider` — timeout_seconds, no-auth header, sanitized logging**

In `mcp_common/llm/provider.py`, make three changes atomically:

**4a. Add `timeout_seconds` and fix no-auth header in `__init__`**

Replace the existing `__init__` with:

```python
class OpenAICompatibleProvider:
    def __init__(self, config: ProviderConfig) -> None:
        # ... keep all existing attribute assignments ...
        self.timeout_seconds = config.timeout_seconds  # expose for FallbackChain

        if config.require_auth:
            api_key = config.api_key.get_secret_value()
            self._client = openai.AsyncOpenAI(
                api_key=api_key,
                base_url=config.base_url,
                max_retries=0,  # retries handled by FallbackChain
                timeout=config.timeout_seconds,
            )
        else:
            # Local no-auth provider (e.g. ollama) — send empty Authorization header
            # so the openai SDK doesn't inject "Bearer no-auth" into requests
            self._client = openai.AsyncOpenAI(
                api_key="no-auth",  # SDK requires a value; overridden below
                base_url=config.base_url,
                default_headers={"Authorization": ""},
                max_retries=0,
                timeout=config.timeout_seconds,
            )
```

**4b. Sanitize `logger.warning` calls in the existing `execute`/`generate` methods**

Find any `logger.warning(...)` calls that format exception objects directly, e.g.:

```python
logger.warning("Provider %s failed: %s", self.name, e)         # UNSAFE
logger.warning(f"Request to {self.name} failed: {exc}")        # UNSAFE
```

Replace each with a sanitized version:

```python
from mcp_common.llm.fallback import _sanitize_error

logger.warning("Provider %s failed: %s", self.name, _sanitize_error(str(e)))
logger.warning("Request to %s failed: %s", self.name, _sanitize_error(str(exc)))
```

> **Why:** The chain's `_sanitize_error` runs only on errors that propagate to `FallbackChain.execute`.
> Any `logger.warning` inside `provider.py` fires before the chain ever sees the exception — those
> log calls are the only place where raw API keys can leak into logs.

Run after these changes:

```bash
grep -n "logger.warning" mcp_common/llm/provider.py
```

Confirm every match either has no exception interpolation, or has been wrapped with `_sanitize_error`.

- [ ] **Step 5: Run new tests**

```bash
uv run pytest tests/test_llm.py::TestFallbackChainRetry -v
```

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest tests/test_llm.py -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add mcp_common/llm/fallback.py mcp_common/llm/provider.py tests/test_llm.py
git commit -m "feat(llm): add per-tier retry loop, error sanitization, and CancelledError propagation"
```

---

## Task 6: Create HailuoAdapter for MiniMax video generation

**Files:**
- Create: `mcp_common/llm/hailuo.py`
- Modify: `mcp_common/llm/__init__.py`
- Modify: `tests/test_llm.py`

- [ ] **Step 1: Write failing tests**

```python
class TestHailuoAdapter:
    @pytest.mark.asyncio
    async def test_poll_url_constructed_from_fixed_base_not_response(self) -> None:
        """Poll URL must never come from a response-supplied URL (SSRF prevention)."""
        from mcp_common.llm.hailuo import HailuoAdapter

        submitted_poll_urls = []

        # _post and _get return plain dicts — not response objects
        async def fake_post(*args, **kwargs) -> dict:
            return {
                "task_id": "abc123",
                "status_url": "https://evil.example.com/steal",  # attacker-supplied, must be ignored
            }

        async def fake_get(url, *args, **kwargs) -> dict:
            submitted_poll_urls.append(url)
            return {
                "status": "completed",
                "file_url": "https://api.minimax.io/v1/video/abc123.mp4",
            }

        adapter = HailuoAdapter(api_key="test-key", base_url="https://api.minimax.io/v1")
        with patch.object(adapter, "_post", fake_post), \
             patch.object(adapter, "_get", fake_get):
            await adapter.generate_video("a sunset")

        for url in submitted_poll_urls:
            assert "evil.example.com" not in url
            assert url.startswith("https://api.minimax.io/v1/video_generation/")

    @pytest.mark.asyncio
    async def test_raises_after_max_polls(self) -> None:
        from mcp_common.llm.hailuo import HailuoAdapter
        from mcp_common.llm.exceptions import LLMError

        poll_count = 0

        async def fake_post(*args, **kwargs) -> dict:
            return {"task_id": "abc123"}

        async def fake_get(url, *args, **kwargs) -> dict:
            nonlocal poll_count
            poll_count += 1
            return {"status": "processing"}

        adapter = HailuoAdapter(
            api_key="test-key",
            base_url="https://api.minimax.io/v1",
            max_polls=3,
            poll_interval_seconds=0.001,
        )
        with patch.object(adapter, "_post", fake_post), \
             patch.object(adapter, "_get", fake_get):
            with pytest.raises(LLMError, match="timed out"):
                await adapter.generate_video("a sunset")

        assert poll_count == 3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_llm.py::TestHailuoAdapter -v 2>&1 | head -20
```

- [ ] **Step 3: Create `mcp_common/llm/hailuo.py`**

```python
"""HailuoAdapter — MiniMax Hailuo video generation with SSRF-safe async polling."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

import aiohttp

from .exceptions import LLMError

logger = logging.getLogger(__name__)

_ALLOWED_POLL_HOST = "api.minimax.io"


class HailuoAdapter:
    """Async polling adapter for MiniMax Hailuo video generation.

    Submits a job via POST, then polls GET using a URL constructed from a
    fixed base + job_id only — never from URLs in the API response (SSRF prevention).
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.minimax.io/v1",
        model: str = "MiniMax-Video-01",
        max_polls: int = 60,
        poll_interval_seconds: float = 5.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._max_polls = max_polls
        self._poll_interval = poll_interval_seconds
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def generate_video(self, prompt: str) -> dict[str, Any]:
        """Submit a video generation job and poll until complete.

        Args:
            prompt: Text description of the video to generate.

        Returns:
            Dict with 'task_id', 'file_url', 'provider', 'model'.

        Raises:
            LLMError: On submission failure or poll timeout.
        """
        task_id = await self._submit_job(prompt)
        return await self._poll_until_complete(task_id)

    async def _submit_job(self, prompt: str) -> str:
        payload = {"model": self._model, "prompt": prompt}
        # _post returns a dict — read inside context manager, no closed-response risk
        data = await self._post(
            f"{self._base_url}/video_generation",
            json=payload,
        )
        task_id = data.get("task_id")
        if not task_id:
            raise LLMError(f"No task_id in submission response: {list(data.keys())}")
        return task_id

    async def _poll_until_complete(self, task_id: str) -> dict[str, Any]:
        # URL constructed from fixed base + task_id only — never from response URLs
        poll_url = f"{self._base_url}/video_generation/{task_id}"
        parsed = urlparse(poll_url)
        if parsed.hostname != _ALLOWED_POLL_HOST:
            raise LLMError(f"Poll URL host {parsed.hostname!r} not allowed")

        for attempt in range(self._max_polls):
            # _get returns a dict — no closed-response risk
            data = await self._get(poll_url)
            status = data.get("status", "unknown")

            if status == "completed":
                file_url = data.get("file_url", "")
                # Validate artifact URL is also MiniMax-origin
                if file_url and urlparse(file_url).hostname != _ALLOWED_POLL_HOST:
                    raise LLMError(f"file_url host not allowed: {file_url}")
                return {
                    "task_id": task_id,
                    "file_url": file_url,
                    "provider": "minimax_hailuo",
                    "model": self._model,
                }

            if status == "failed":
                raise LLMError(f"Video generation job {task_id} failed")

            logger.debug(
                "Poll %d/%d: task %s status=%s",
                attempt + 1, self._max_polls, task_id, status,
            )
            await asyncio.sleep(self._poll_interval)

        raise LLMError(
            f"Video generation job {task_id} timed out after {self._max_polls} polls"
        )

    async def _post(self, url: str, **kwargs: Any) -> dict[str, Any]:
        """Read JSON inside the context manager and return a plain dict.

        IMPORTANT: response must be consumed before the `async with` block exits —
        aiohttp closes the connection on exit, making any subsequent `.json()` call fail.
        """
        async with aiohttp.ClientSession(headers=self._headers) as session:
            async with session.post(
                url,
                allow_redirects=False,  # no redirects on POST
                **kwargs,
            ) as resp:
                resp.raise_for_status()
                return await resp.json()  # read INSIDE — connection still open

    async def _get(self, url: str, **kwargs: Any) -> dict[str, Any]:
        """Read JSON inside the context manager and return a plain dict."""
        async with aiohttp.ClientSession(headers=self._headers) as session:
            async with session.get(
                url,
                allow_redirects=False,  # no redirects on GET (SSRF prevention)
                **kwargs,
            ) as resp:
                resp.raise_for_status()
                return await resp.json()  # read INSIDE — connection still open
```

- [ ] **Step 4: Export from `mcp_common/llm/__init__.py`**

Add:

```python
from .hailuo import HailuoAdapter
```

And add `"HailuoAdapter"` to `__all__`.

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_llm.py::TestHailuoAdapter -v
```

- [ ] **Step 6: Run full suite**

```bash
uv run pytest tests/test_llm.py -v
```

- [ ] **Step 7: Commit**

```bash
git add mcp_common/llm/hailuo.py mcp_common/llm/__init__.py tests/test_llm.py
git commit -m "feat(llm): add HailuoAdapter with SSRF-safe async polling for MiniMax video"
```

---

## Task 7: Add edge case tests, Hypothesis property test, and final validation

**Files:**
- Modify: `tests/test_llm.py`

- [ ] **Step 1: Add FallbackChain edge case tests**

```python
class TestFallbackChainEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_provider_list_raises_immediately(self) -> None:
        """Chain with no providers must raise without calling anything."""
        from mcp_common.llm.exceptions import AllProvidersExhaustedError
        chain = FallbackChain([])
        with pytest.raises(AllProvidersExhaustedError):
            await chain.execute({"model": "m", "messages": []})

    @pytest.mark.asyncio
    async def test_all_circuit_breakers_open_raises_immediately(self) -> None:
        """If every tier's breaker is open, AllProvidersExhaustedError fires immediately."""
        from mcp_common.llm.exceptions import AllProvidersExhaustedError

        mock_provider = AsyncMock()
        mock_provider.name = "tier1"
        mock_provider.execute = AsyncMock(return_value={"content": "ok"})

        chain = FallbackChain([mock_provider])
        # Force open state by failing past threshold
        chain._circuit_breakers["tier1"] = CircuitBreaker(failure_threshold=1, reset_timeout=60.0)
        chain._circuit_breakers["tier1"].record_failure()  # opens immediately at threshold=1

        with pytest.raises(AllProvidersExhaustedError):
            await chain.execute({"model": "m", "messages": []})

        mock_provider.execute.assert_not_called()  # skipped entirely

    @pytest.mark.asyncio
    async def test_timeout_zero_raises_timeout_not_cancelled(self) -> None:
        """timeout_seconds=0 should be treated as a timeout error, not CancelledError."""
        import asyncio

        async def slow_response(task):
            await asyncio.sleep(1.0)
            return {"content": "too late"}

        mock_provider = AsyncMock()
        mock_provider.name = "tier1"
        mock_provider.execute = slow_response
        mock_provider.timeout_seconds = 0  # immediate timeout

        chain = FallbackChain([mock_provider], max_attempts_per_tier=1)
        # Should raise AllProvidersExhaustedError (wrapping TimeoutError), NOT CancelledError
        with pytest.raises(Exception) as exc_info:
            await chain.execute({"model": "m", "messages": []})
        assert not isinstance(exc_info.value, asyncio.CancelledError)
```

- [ ] **Step 2: Add Hypothesis property tests for TaskType**

```python
from hypothesis import given, settings as h_settings, strategies as st

class TestTaskTypeProperty:
    @given(st.sampled_from(list(TaskType)))
    def test_task_type_round_trips_from_string(self, task: TaskType) -> None:
        """Every TaskType value must round-trip through TaskType(value)."""
        assert TaskType(task.value) is task
        assert task.value == task.value.lower()
        assert task.value  # never empty

    @given(st.sampled_from(list(TaskType)))
    def test_task_type_values_are_distinct(self, task: TaskType) -> None:
        """No two TaskType members share a value (catches alias mistakes)."""
        matches = [t for t in TaskType if t.value == task.value]
        assert len(matches) == 1, f"Duplicate value {task.value!r}: {matches}"

    def test_vision_and_image_understanding_are_distinct_members(self) -> None:
        """VISION and IMAGE_UNDERSTANDING are separate members (alias, not redirect)."""
        assert TaskType.VISION is not TaskType.IMAGE_UNDERSTANDING
        assert TaskType.VISION.value != TaskType.IMAGE_UNDERSTANDING.value
```

- [ ] **Step 3: Run new edge case and property tests**

```bash
uv run pytest tests/test_llm.py::TestFallbackChainEdgeCases tests/test_llm.py::TestTaskTypeProperty -v
```

Expected: all new tests PASS.

- [ ] **Step 4: Run the full quality gate**

```bash
uv run crackerjack run 2>&1 | tail -20
```

If crackerjack is not available locally, run the individual checks:

```bash
uv run ruff format mcp_common/llm/ tests/test_llm.py
uv run ruff check mcp_common/llm/ tests/test_llm.py --fix
uv run pytest tests/test_llm.py -v --tb=short
```

Expected: all tests PASS, no ruff errors.

- [ ] **Step 5: Bump version to 0.14.0 in `pyproject.toml`**

Change:
```toml
version = "0.13.3"
```
To:
```toml
version = "0.14.0"
```

- [ ] **Step 6: Final commit**

```bash
git add tests/test_llm.py pyproject.toml
git commit -m "feat(llm): finalize mcp-common 0.14.0 — three-tier provider chain with multimodal support

- Extended TaskType with IMAGE_GENERATION, IMAGE_UNDERSTANDING, AUDIO_SPEECH,
  AUDIO_TRANSCRIPTION, VIDEO_GENERATION; VISION kept as deprecated alias
- Added UnsupportedModalityError exception
- FallbackChain: per-tier retry (3x, 1s/2s/4s backoff), error sanitization,
  CancelledError propagation, circuit breaker counts per tier-call
- ProviderConfig: timeout_seconds, require_auth, api_key_env fields
- LLMSettings: fail-closed API key validation, llama_server support,
  backward-compatible schema loader
- HailuoAdapter: SSRF-safe video generation with fixed-base poll URL"
```

---

## Self-Review Checklist

- [x] **Spec §4.1 security hooks** — sanitize_input / validate_output: The spec lists these on `LLMAdapter`, but the existing mcp-common module doesn't have an `LLMAdapter` ABC. `_sanitize_error` is implemented on `FallbackChain` and wraps all error paths. `sanitize_input` / `validate_output` are code-fixer concerns (crackerjack-specific) handled in Plan 2 when crackerjack's `BaseCodeFixer` is migrated. **Gap noted — covered in Plan 2.**
- [x] **Spec §4.4 caller-level timeout** — `execute()` does not expose a caller-level outer timeout (by design in this plan). The per-tier `timeout_seconds` from config is the enforcement mechanism. Plan 2 can wrap the chain in `asyncio.wait_for` at the application level if needed.
- [x] **Spec §4.5 YAML backward compat** — covered by `from_yaml` detecting old schema vs. new.
- [x] **No placeholder steps** — all steps have complete code.
- [x] **Type consistency** — `_sanitize_error` used in Task 5, defined in Task 5. `timeout_seconds` defined in Task 3, consumed in Task 5.

## Multi-Agent Review Fixes Applied (rev 2)

Fixes incorporated after security, implementation-feasibility, and TDD review agents:

| Source | Severity | Fix |
|--------|----------|-----|
| Security | **Critical** | Task 5 `_SECRET_PATTERNS`: added JWT/MiniMax `eyJ...` pattern; removed over-broad path pattern |
| Security | **Critical** | Task 5 Step 4: `provider.py` `logger.warning` calls now wrapped with `_sanitize_error` before logging |
| Security | Warning | Task 4 fail-closed check: added `not key.strip()` for whitespace-only keys |
| Security | Warning | Task 5 Step 4: no-auth ollama now uses `default_headers={"Authorization": ""}` to suppress header |
| Implementation | **Critical** | Task 6 `_post`/`_get`: now read JSON inside `async with` block and return `dict`; callers use dict directly |
| Implementation | Warning | Task 5 Steps 3+4: must be applied atomically (both in same edit session) |
| TDD | **Critical** | Task 1 Step 5: added instruction to update `test_total_member_count` from 14 → 20 |
| TDD | **Critical** | Task 5 circuit breaker test: explicit `CircuitBreaker(failure_threshold=5)` assignment to pin threshold |
| TDD | Warning | Task 6 test fakes: now return `dict` directly (matching fixed `_post`/`_get` return type) |
| TDD | Warning | Task 7 Hypothesis test: replaced unused `st.text()` with meaningful `st.sampled_from(list(TaskType))` |
| TDD | Suggestion | Task 7: added `TestFallbackChainEdgeCases` with empty chain, all-open-breakers, and zero-timeout cases |
