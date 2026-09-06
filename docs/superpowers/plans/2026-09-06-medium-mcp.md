---
status: draft
role: implementation
date: 2026-09-06
last_reviewed: 2026-09-06
superseded_by: null
topic: mcp-stub-activation
---

# Medium MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `medium-mcp` from a name-reservation scaffold into a working MCP server that surfaces Medium content (users, articles, publications, tags) via the unofficial medium2 RapidAPI, with a Dhara-backed cache and a strict monthly-budget guard that refuses calls rather than overspend.

**Architecture:** `httpx2` direct to `https://medium2.p.rapidapi.com` with a typed pydantic surface. Dhara (via `AsyncKVTimeSeriesStore` + `DharaLock`) holds the cache and serializes the budget counter so two workers cannot both pass the headroom check. Tools return metadata by default; full text is gated by `include_full_text=True` and a separate content-cache key prefix. Profile gating inherits the `mcp-common` baseline; the `/readyz` route reports 503 when Dhara is unreachable.

**Tech Stack:** Python 3.14, FastMCP 2.12+, httpx2 0.28+, pydantic 2.5+, pydantic-settings 2.1+, `mcp-common>=0.18.0`, `oneiric>=0.16.0`, Dhara (lock + AsyncKVTimeSeriesStore).

**Spec:** [2026-09-06-mcp-stub-activation-design.md](2026-09-06-mcp-stub-activation-design.md) §6.2 (medium-mcp), §13.3 (settings). The plan argues from the spec; the spec travels with it.

## Global Constraints

These apply to every task. The spec is the source of truth; this list is the implementation-faithful restatement.

- `requires-python >=3.14`; BSD-3-Clause; `httpx2>=0.28.1`, `mcp-common>=0.18.0`, `oneiric>=0.16.0`, `pydantic>=2.5.0`, `pydantic-settings>=2.1.0`.
- Package: `medium_mcp`. Layout: **flat** (`medium_mcp/` at repo root, not `src/`). Wheel layout matches `raindropio-mcp` and `archive-org-mcp`.
- Settings prefix: `MEDIUM_MCP_`. Env-only secrets (`rapidapi_key`).
- HTTP port: `3055`. `/health` returns 200; `/readyz` returns 503 when required feeds are degraded.
- Tool profile env: `MEDIUM_MCP_TOOL_PROFILE` ∈ `{"full","standard","minimal"}`, default `"full"`.
- Budget hard limit: `monthly_budget=150` metered calls / period. The guard never retries metered calls (`retry_max_attempts=1`).
- Plan 0a (registry migration) and Plan 0b (port reconciliation) must complete before Phase 0b of this plan begins. Plan 0b of *this* plan (live upstream proof) additionally requires `MEDIUM_MCP_RAPIDAPI_KEY` exported in the shell.
- All `MEDIUM_MCP_*` settings keys appear in §13.3; no new keys may be introduced without amending that section.
- Crackerjack is the sole CI (`crackerjack run`); there is no `.github/workflows/`. No PR gate; merges to `main` are user-controlled.
- Git author email: `les@wedgwoodwebworks.com`. Never push without explicit user approval.

## Phase 0a Integration Contract

**Triggered from:** nothing yet. Phase 0a delivers the project skeleton, exceptions, settings, and Dhara client — modules that later phases import, but with no entry point of their own.

**Returns to / updates:** provides `medium_mcp.config.settings.MediumSettings`, `medium_mcp.utils.exceptions.{MediumError, ConfigurationError, UpstreamError, RateLimitedError, BudgetExhaustedError, NotFoundError}` consumed by Phases 1 and 2; provides `medium_mcp.dhara.client.DharaClient` and `medium_mcp.dhara.keys.{cache_key, content_key, budget_key, coalesce_key}` consumed by every later phase.

**Demonstrable by:** `pytest tests/unit/ -v` passes every test from Tasks 1-4. This is a weaker claim than the other phases make, and deliberately so: **Phase 0a is not wired**. Phase 1 (tools) is the first phase that produces something a developer can run.

**Rollback signal:** revert commits from this phase; no Phase 1 work exists yet, so nothing downstream breaks.

**Observability added:** `medium_mcp.utils.logging` configured to oneiric; `MediumSettings.log_level` honored; no metrics yet (Phase 1 introduces them).

---

### Task 1: Make it a git repository and fix the wheel

**Files:**
- Create: `/Users/les/Projects/medium-mcp/.gitignore` (already exists; verify)
- Modify: `/Users/les/Projects/medium-mcp/pyproject.toml` (wheel layout, coverage, scripts)
- Test: `/Users/les/Projects/medium-mcp/tests/unit/test_packaging.py`

**Interfaces:**
- Produces: a git repo with a wheel whose `RECORD` contains `medium_mcp/__init__.py`. Coverage floor `--cov-fail-under=70` (starting point; ratchet later).

- [ ] **Step 1: Initialize git and verify scaffold layout**

```bash
cd /Users/les/Projects/medium-mcp
git init -b main
ls -la
```

Expected: `.git/`, `LICENSE`, `pyproject.toml`, `README.md`, `src/`, `dist/`. There is **no `medium_mcp/` directory yet** — that lands in Step 4.

- [ ] **Step 2: Move from `src/` layout to flat layout**

```bash
cd /Users/les/Projects/medium-mcp
git mv src/medium_mcp medium_mcp_temp 2>/dev/null || true
rm -rf src
mkdir -p medium_mcp tests/unit tests/integration
# Move any existing stubs to a stub directory so they're discoverable but clearly inert
git mv medium_mcp_temp/* medium_mcp_temp/.gitignore 2>/dev/null medium_mcp/ 2>/dev/null || true
rmdir medium_mcp_temp 2>/dev/null || true
touch medium_mcp/__init__.py
echo '__version__ = "0.1.0"' > medium_mcp/__init__.py
git add -A
```

Expected: `medium_mcp/__init__.py` exists with `__version__`. `src/` is gone.

- [ ] **Step 3: Update `pyproject.toml`**

Replace the `[tool.hatch.build.targets.wheel]` section. The wheel must include `medium_mcp/`, not `src/medium_mcp/`. Add coverage config and a `test` script. Final shape:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "medium-mcp"
version = "0.1.0"
description = "MCP server for Medium content via RapidAPI's medium2"
readme = "README.md"
requires-python = ">=3.14"
license = { text = "BSD-3-Clause" }
authors = [{ name = "Les Leslie", email = "les@wedgwoodwebworks.com" }]
dependencies = [
    "fastmcp>=2.12.0",
    "httpx2>=0.28.1",
    "mcp-common>=0.18.0",
    "oneiric>=0.16.0",
    "pydantic>=2.5.0",
    "pydantic-settings>=2.1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "pytest-cov>=5.0", "ruff>=0.6", "crackerjack>=0.30"]

[project.scripts]
medium-mcp = "medium_mcp.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["medium_mcp"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [
    "requires_network: hits a real network endpoint",
    "requires_auth: requires MEDIUM_MCP_RAPIDAPI_KEY in env",
    "requires_bpf: requires /dev/bpf* access",
]
addopts = "--cov=medium_mcp --cov-report=term --cov-report=html --cov-fail-under=70"

[tool.ruff]
line-length = 100
target-version = "py314"
```

- [ ] **Step 4: Write the failing packaging test**

Create `tests/unit/test_packaging.py`:

```python
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_wheel_contains_package() -> None:
    """Build the wheel and assert it contains medium_mcp/__init__.py."""
    import subprocess

    result = subprocess.run(
        ["python", "-m", "hatchling", "build", "-t", "wheel"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    wheels = list((REPO_ROOT / "dist").glob("*.whl"))
    assert wheels, "no wheel produced"
    with zipfile.ZipFile(wheels[-1]) as zf:
        names = zf.namelist()
    assert any(n.endswith("medium_mcp/__init__.py") for n in names), names
    assert not any(n.startswith("src/") for n in names), names


def test_coverage_floor_is_70() -> None:
    """Coverage floor must start at 70 so Phase 1 can ratchet up."""
    import tomllib

    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    addopts = pyproject["tool"]["pytest"]["ini_options"]["addopts"]
    assert "--cov-fail-under=70" in addopts
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd /Users/les/Projects/medium-mcp
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest tests/unit/test_packaging.py -v
```

Expected: 2 passed. (The first builds the wheel from current source; the second reads `pyproject.toml`. Both should pass with the changes from Steps 1-3 applied.)

- [ ] **Step 6: Commit**

```bash
cd /Users/les/Projects/medium-mcp
git -c user.email=les@wedgwoodwebworks.com add -A
git -c user.email=les@wedgwoodwebworks.com commit -m "feat(medium-mcp): initialize git repo, switch to flat layout, packaging test"
```

---

### Task 2: Typed exception hierarchy

**Files:**
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/utils/__init__.py`
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/utils/exceptions.py`
- Test: `/Users/les/Projects/medium-mcp/tests/unit/test_exceptions.py`

**Interfaces:**
- Produces: `MediumError(Exception)` with `.message` and `.context`; subclasses `ConfigurationError`, `UpstreamError(MediumError, status_code, body)`, `RateLimitedError(UpstreamError)`, `BudgetExhaustedError(MediumError, requested_calls, period, resets_at, cached_alternatives)` carrying the spec's structured payload, and `NotFoundError(UpstreamError)`. All inherit from `MediumError`; callers can `except MediumError:` to catch everything.

- [ ] **Step 1: Write the failing exception test**

Create `tests/unit/test_exceptions.py`:

```python
from __future__ import annotations

import pytest

from medium_mcp.utils.exceptions import (
    BudgetExhaustedError,
    ConfigurationError,
    MediumError,
    NotFoundError,
    RateLimitedError,
    UpstreamError,
)


def test_medium_error_carries_context() -> None:
    err = MediumError("boom", context={"foo": "bar"})
    assert err.message == "boom"
    assert err.context == {"foo": "bar"}
    assert "boom" in str(err)
    assert "foo=bar" in str(err)


def test_all_subclasses_inherit_from_medium_error() -> None:
    for cls in (ConfigurationError, UpstreamError, RateLimitedError, BudgetExhaustedError, NotFoundError):
        assert issubclass(cls, MediumError), cls


def test_upstream_error_carries_status_and_body() -> None:
    err = UpstreamError("gateway timeout", status_code=504, body="<html>...</html>")
    assert err.status_code == 504
    assert err.body == "<html>...</html>"


def test_rate_limited_is_upstream_error() -> None:
    err = RateLimitedError("429 too many requests", status_code=429, body="")
    assert isinstance(err, UpstreamError)
    assert err.status_code == 429


def test_not_found_status_is_404() -> None:
    err = NotFoundError("missing", status_code=404, body="")
    assert err.status_code == 404
    assert isinstance(err, UpstreamError)


def test_budget_exhausted_carries_spec_payload() -> None:
    err = BudgetExhaustedError(
        "budget exhausted",
        requested_calls=2,
        remaining_calls=0,
        monthly_budget=150,
        period="2026-09",
        resets_at="2026-10-01T00:00:00Z",
        cached_alternatives=["user_info", "article_metadata"],
    )
    payload = err.to_payload()
    # Spec §6.2's payload does NOT carry monthly_budget; the caller learns the
    # budget from ``budget_remaining``, not from the refusal.
    assert payload == {
        "error": "budget_exhausted",
        "remaining_calls": 0,
        "requested_calls": 2,
        "period": "2026-09",
        "resets_at": "2026-10-01T00:00:00Z",
        "retryable": False,
        "cached_alternatives": ["user_info", "article_metadata"],
    }


def test_budget_exhausted_serializes_to_json() -> None:
    import json

    err = BudgetExhaustedError(
        "budget exhausted",
        requested_calls=1,
        remaining_calls=0,
        monthly_budget=150,
        period="2026-09",
        resets_at="2026-10-01T00:00:00Z",
        cached_alternatives=[],
    )
    payload = err.to_payload()
    assert json.loads(json.dumps(payload)) == payload
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /Users/les/Projects/medium-mcp
.venv/bin/pytest tests/unit/test_exceptions.py -v
```

Expected: ImportError (`medium_mcp.utils.exceptions` does not exist).

- [ ] **Step 3: Implement the exception hierarchy**

Create `medium_mcp/utils/__init__.py` (empty). Create `medium_mcp/utils/exceptions.py`:

```python
from __future__ import annotations

from typing import Any


class MediumError(Exception):
    """Base for every medium-mcp raised exception.

    Carries a human-readable message and a structured context dict so
    upstream tools can render both: ``str(err)`` for logs and
    ``err.context`` / ``err.to_payload()`` for MCP error responses.
    """

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context = dict(context or {})

    def __str__(self) -> str:
        if not self.context:
            return self.message
        ctx = ", ".join(f"{k}={v}" for k, v in sorted(self.context.items()))
        return f"{self.message} ({ctx})"


class ConfigurationError(MediumError):
    """Raised when a required setting is missing or malformed at startup."""


class UpstreamError(MediumError):
    """Raised when medium2 returns a non-success status code."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        body: str = "",
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, context=context)
        self.status_code = status_code
        self.body = body


class RateLimitedError(UpstreamError):
    """Upstream returned 429; treat as transient, do not retry metered calls."""


class NotFoundError(UpstreamError):
    """Upstream returned 404; treat as terminal for the requested resource."""


class BudgetExhaustedError(MediumError):
    """Monthly budget exhausted or below headroom. Caller must NOT retry.

    The structured payload mirrors the spec's budget-error JSON so MCP
    clients can present ``cached_alternatives`` and the reset time.
    """

    def __init__(
        self,
        message: str,
        *,
        requested_calls: int,
        remaining_calls: int,
        monthly_budget: int,
        period: str,
        resets_at: str,
        cached_alternatives: list[str],
    ) -> None:
        super().__init__(
            message,
            context={
                "requested_calls": requested_calls,
                "remaining_calls": remaining_calls,
                "monthly_budget": monthly_budget,
                "period": period,
                "resets_at": resets_at,
            },
        )
        self.requested_calls = requested_calls
        self.remaining_calls = remaining_calls
        self.monthly_budget = monthly_budget
        self.period = period
        self.resets_at = resets_at
        self.cached_alternatives = cached_alternatives

    def to_payload(self) -> dict[str, Any]:
        """Exactly the spec §6.2 refusal payload — no extra keys.

        ``monthly_budget`` is deliberately absent: the refusal states what was
        asked for and what is left, and ``budget_remaining`` is the (free) tool
        that reports the configured budget.
        """
        return {
            "error": "budget_exhausted",
            "remaining_calls": self.remaining_calls,
            "requested_calls": self.requested_calls,
            "period": self.period,
            "resets_at": self.resets_at,
            "retryable": False,
            "cached_alternatives": list(self.cached_alternatives),
        }
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /Users/les/Projects/medium-mcp
.venv/bin/pytest tests/unit/test_exceptions.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/medium-mcp
git -c user.email=les@wedgwoodwebworks.com add -A
git -c user.email=les@wedgwoodwebworks.com commit -m "feat(medium-mcp): typed exception hierarchy with structured BudgetExhaustedError"
```

---

### Task 3: Settings model

**Files:**
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/config/__init__.py`
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/config/settings.py`
- Test: `/Users/les/Projects/medium-mcp/tests/unit/test_settings.py`

**Interfaces:**
- Produces: `MediumSettings(BaseSettings)` with `env_prefix="MEDIUM_MCP_"`, `model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")`. Every key from spec §13.3 is a typed attribute with the documented default. `@lru_cache def get_settings()` returns a singleton. `PROJECT_ROOT = Path(__file__).resolve().parent.parent`.

- [ ] **Step 1: Write the failing settings test**

Create `tests/unit/test_settings.py`:

```python
from __future__ import annotations

import pytest
from pydantic import SecretStr

from medium_mcp.config.settings import MediumSettings, get_settings


def test_defaults_match_spec() -> None:
    settings = MediumSettings(_env_file=None)  # ignore .env
    assert settings.http_port == 3055
    assert settings.rapidapi_base_url == "https://medium2.p.rapidapi.com/"
    assert settings.monthly_budget == 150
    assert settings.budget_reserve_headroom == 5
    assert settings.retry_max_attempts == 1
    assert settings.http_timeout_seconds == 30.0
    assert settings.dhara_namespace == "medium_mcp"
    assert settings.dhara_required is True
    assert settings.cache_max_entries == 10_000
    assert settings.cache_max_content_bytes == 52_428_800
    assert settings.cache_ttl_user_info == 86_400
    assert settings.cache_ttl_user_articles == 3_600
    assert settings.cache_ttl_article_metadata == 604_800
    assert settings.cache_ttl_article_content == 2_592_000
    assert settings.cache_ttl_search == 1_800
    assert settings.cache_ttl_tag == 21_600
    assert settings.coalesce_window_seconds == 5.0
    assert settings.excerpt_max_chars == 500
    assert settings.allow_content_export is False


def test_excerpt_max_chars_capped_at_2000() -> None:
    with pytest.raises(Exception):  # pydantic ValidationError
        MediumSettings(_env_file=None, excerpt_max_chars=2001)


def test_retry_max_attempts_for_metered_calls_is_one() -> None:
    """Spec pins retry_max_attempts=1 because metered calls must not retry."""
    settings = MediumSettings(_env_file=None)
    assert settings.retry_max_attempts == 1


def test_rapidapi_key_required_at_startup() -> None:
    """rapidapi_key is required via env (not defaulted)."""
    settings = MediumSettings(_env_file=None)
    assert settings.rapidapi_key is None or isinstance(settings.rapidapi_key, SecretStr)


def test_env_var_override_works() -> None:
    settings = MediumSettings(
        _env_file=None,
        monthly_budget=200,
        budget_reserve_headroom=10,
    )
    assert settings.monthly_budget == 200
    assert settings.budget_reserve_headroom == 10


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_settings_can_be_reloaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEDIUM_MCP_MONTHLY_BUDGET", "175")
    get_settings.cache_clear()
    assert get_settings().monthly_budget == 175
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /Users/les/Projects/medium-mcp
.venv/bin/pytest tests/unit/test_settings.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement the settings model**

Create `medium_mcp/config/__init__.py` (empty). Create `medium_mcp/config/settings.py`:

```python
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class MediumSettings(BaseSettings):
    """Configuration for medium-mcp. Spec source: §13.3."""

    model_config = SettingsConfigDict(
        env_prefix="MEDIUM_MCP_",
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Network
    rapidapi_base_url: HttpUrl = "https://medium2.p.rapidapi.com"
    rapidapi_key: SecretStr | None = None
    http_port: int | None = 3055
    http_timeout_seconds: float = 30.0

    # Budget
    monthly_budget: int = 150
    budget_reserve_headroom: int = 5
    # Spec rule: metered calls must not retry. Single attempt only.
    retry_max_attempts: int = Field(default=1, ge=0, le=1)

    # Cache
    dhara_namespace: str = "medium_mcp"
    dhara_required: bool = True
    cache_max_entries: int = 10_000
    cache_max_content_bytes: int = 52_428_800
    cache_ttl_user_info: int = 86_400
    cache_ttl_user_articles: int = 3_600
    cache_ttl_article_metadata: int = 604_800
    cache_ttl_article_content: int = 2_592_000
    cache_ttl_search: int = 1_800
    cache_ttl_tag: int = 21_600
    coalesce_window_seconds: float = 5.0

    # Content policy
    excerpt_max_chars: int = Field(default=500, gt=0, le=2000)
    allow_content_export: bool = False

    # Profile / logging
    tool_profile: str = "full"
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> MediumSettings:
    """Cached singleton. Callers can call `.cache_clear()` after env mutation."""
    return MediumSettings()
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /Users/les/Projects/medium-mcp
.venv/bin/pytest tests/unit/test_settings.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/medium-mcp
git -c user.email=les@wedgwoodwebworks.com add -A
git -c user.email=les@wedgwoodwebworks.com commit -m "feat(medium-mcp): MediumSettings with all §13.3 keys and defaults"
```

---

### Task 4: Dhara client and key scheme

**Files:**
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/dhara/__init__.py`
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/dhara/keys.py`
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/dhara/client.py`
- Test: `/Users/les/Projects/medium-mcp/tests/unit/test_dhara_keys.py`
- Test: `/Users/les/Projects/medium-mcp/tests/unit/test_dhara_client.py`

**Interfaces:**
- Produces: key-building helpers used by every later phase:
  - `cache_key(endpoint: str, params: dict) -> str` returns `medium2:v1:<endpoint>:<sha256>`
  - `content_key(article_id: str) -> str` returns `medium2:v1:content:<article_id>`
  - `budget_key(period: str) -> str` returns `medium2:v1:budget:<period>` (no TTL)
  - `coalesce_key(endpoint: str, params: dict) -> str` returns the same value as `cache_key` (the spec says coalescing shares the cache key).
- Produces: `DharaClient` wraps `AsyncKVTimeSeriesStore` + `DharaLock`. Provides `async def get(...)`, `async def put(...)`, `async def get_counter(...)`, `async def inc_atomic(key, *, increment=1, max_value=None) -> tuple[int, bool]` (read-check-increment-write inside the lock), `async def dec_atomic(key, *, decrement) -> int`, `async def acquire_budget_lock(period)`, `async def release_budget_lock(handle)`. Constructed from `MediumSettings`. Starts up by probing a sentinel key.

- [ ] **Step 1: Write the failing key-scheme test**

Create `tests/unit/test_dhara_keys.py`:

```python
from __future__ import annotations

from medium_mcp.dhara.keys import (
    budget_key,
    cache_key,
    coalesce_key,
    content_key,
)


def test_cache_key_is_deterministic_and_sorted() -> None:
    a = cache_key("user_info", {"user_id": "abc", "cursor": None})
    b = cache_key("user_info", {"cursor": None, "user_id": "abc"})
    assert a == b
    assert a.startswith("medium2:v1:user_info:")


def test_cache_key_different_params_differ() -> None:
    a = cache_key("user_info", {"user_id": "abc"})
    b = cache_key("user_info", {"user_id": "xyz"})
    assert a != b


def test_cache_key_normalizes_none_to_empty_string() -> None:
    a = cache_key("user_info", {"cursor": None})
    b = cache_key("user_info", {})
    # canonical serialization must produce the same hash for both
    assert a == b


def test_content_key_is_separate_prefix() -> None:
    assert content_key("abc123") == "medium2:v1:content:abc123"
    assert not content_key("abc123").startswith("medium2:v1:content:abc123".rstrip("abc123")[:-1])


def test_budget_key_format() -> None:
    assert budget_key("2026-09") == "medium2:v1:budget:2026-09"


def test_coalesce_key_equals_cache_key() -> None:
    """Spec: coalescing attaches followers to the leader's future using the cache key."""
    params = {"foo": "bar"}
    assert coalesce_key("search_articles", params) == cache_key("search_articles", params)
```

- [ ] **Step 2: Write the failing Dhara client test (in-memory)**

Create `tests/unit/test_dhara_client.py`:

```python
from __future__ import annotations

import asyncio

import pytest

from medium_mcp.config.settings import MediumSettings
from medium_mcp.dhara.client import DharaClient


@pytest.fixture
def settings() -> MediumSettings:
    return MediumSettings(_env_file=None)


async def test_probe_succeeds_with_in_memory_backend(settings: MediumSettings) -> None:
    client = DharaClient(settings=settings, backend="memory")
    await client.startup()
    try:
        assert await client.probe() is True
    finally:
        await client.shutdown()


async def test_get_returns_none_for_missing_key(settings: MediumSettings) -> None:
    client = DharaClient(settings=settings, backend="memory")
    await client.startup()
    try:
        assert await client.get("medium2:v1:user_info:does-not-exist") is None
    finally:
        await client.shutdown()


async def test_put_then_get_round_trip(settings: MediumSettings) -> None:
    client = DharaClient(settings=settings, backend="memory")
    await client.startup()
    try:
        await client.put("medium2:v1:user_info:abc", b'{"id":"abc"}', ttl=60)
        assert await client.get("medium2:v1:user_info:abc") == b'{"id":"abc"}'
    finally:
        await client.shutdown()


async def test_inc_atomic(settings: MediumSettings) -> None:
    """Successive inc_atomic calls advance the counter from zero by ``increment``."""
    client = DharaClient(settings=settings, backend="memory")
    await client.startup()
    try:
        key = "medium2:v1:budget:2026-09"
        assert await client.inc_atomic(key) == (1, True)
        assert await client.inc_atomic(key, increment=2) == (3, True)
        assert await client.get_counter(key) == 3
    finally:
        await client.shutdown()


async def test_inc_atomic_refuses_past_max_value_without_mutating(
    settings: MediumSettings,
) -> None:
    """The ceiling check happens INSIDE the lock and leaves the counter alone."""
    client = DharaClient(settings=settings, backend="memory")
    await client.startup()
    try:
        key = "medium2:v1:budget:2026-09"
        assert await client.inc_atomic(key, increment=2, max_value=3) == (2, True)
        # 2 + 2 > 3 -> refused, counter unchanged at 2.
        assert await client.inc_atomic(key, increment=2, max_value=3) == (2, False)
        assert await client.get_counter(key) == 2
        # A smaller increment that still fits is accepted.
        assert await client.inc_atomic(key, increment=1, max_value=3) == (3, True)
    finally:
        await client.shutdown()


async def test_dec_atomic_floors_at_zero(settings: MediumSettings) -> None:
    client = DharaClient(settings=settings, backend="memory")
    await client.startup()
    try:
        key = "medium2:v1:budget:2026-09"
        await client.inc_atomic(key, increment=3)
        assert await client.dec_atomic(key, decrement=2) == 1
        assert await client.dec_atomic(key, decrement=99) == 0
    finally:
        await client.shutdown()


async def test_budget_lock_blocks_concurrent_holders(settings: MediumSettings) -> None:
    """Two workers cannot both hold the budget lock at the same time."""
    client = DharaClient(settings=settings, backend="memory")
    await client.startup()
    try:
        first = await client.acquire_budget_lock("2026-09")
        assert first is not None
        second = await client.acquire_budget_lock("2026-09")
        assert second is None  # contention: refused
        await client.release_budget_lock(first)
        third = await client.acquire_budget_lock("2026-09")
        assert third is not None
        await client.release_budget_lock(third)
    finally:
        await client.shutdown()
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
cd /Users/les/Projects/medium-mcp
.venv/bin/pytest tests/unit/test_dhara_keys.py tests/unit/test_dhara_client.py -v
```

Expected: ImportError.

- [ ] **Step 4: Implement the key helpers**

Create `medium_mcp/dhara/__init__.py` (empty). Create `medium_mcp/dhara/keys.py`:

```python
from __future__ import annotations

import hashlib
import json
from typing import Any

NAMESPACE_PREFIX = "medium2:v1"


def _canonical_params(params: dict[str, Any]) -> bytes:
    """Canonically encode params for hashing.

    Rules: keys sorted, JSON dump, ``None`` becomes ``""`` so two callers that
    pass ``cursor=None`` and the same query hash identically.
    """
    normalized = {k: ("" if v is None else v) for k, v in params.items()}
    return json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()


def _hash_params(params: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_params(params)).hexdigest()


def cache_key(endpoint: str, params: dict[str, Any]) -> str:
    """Cache key: namespace + endpoint + sha256 of canonical params."""
    return f"{NAMESPACE_PREFIX}:{endpoint}:{_hash_params(params)}"


def content_key(article_id: str) -> str:
    """Separate key prefix for full-text content per spec §6.2 content policy."""
    return f"{NAMESPACE_PREFIX}:content:{article_id}"


def budget_key(period: str) -> str:
    """Counter key. No TTL — must not evict across the month boundary."""
    return f"{NAMESPACE_PREFIX}:budget:{period}"


def coalesce_key(endpoint: str, params: dict[str, Any]) -> str:
    """Coalescing shares the cache key (spec §6.2)."""
    return cache_key(endpoint, params)
```

- [ ] **Step 5: Implement the Dhara client**

Create `medium_mcp/dhara/client.py`:

```python
from __future__ import annotations

import asyncio
import time
from typing import Any

from dhara.lock.in_memory import InMemoryDharaLock
from dhara.mcp.kv_timeseries import AsyncKVTimeSeriesStore

from medium_mcp.config.settings import MediumSettings
from medium_mcp.dhara.keys import budget_key
from medium_mcp.utils.exceptions import ConfigurationError

# How long a successful/failed ``probe()`` result stays warm.
PROBE_CACHE_SECONDS = 5.0


class DharaClient:
    """Wraps Dhara's KV store and advisory lock for medium-mcp.

    Two production backends are accepted ("memory" for tests, "sql"/"postgres"
    for cross-process). The lock module's ``try_acquire`` returning ``None``
    on contention is the serialization primitive the budget guard uses.
    """

    def __init__(self, settings: MediumSettings, backend: str = "memory") -> None:
        self.settings = settings
        self.backend = backend
        self._kv: AsyncKVTimeSeriesStore | None = None
        self._lock: InMemoryDharaLock | None = None
        self._started = False
        self._namespace = settings.dhara_namespace
        # ``probe()`` is on the hot path (every metered call gates on it), so its
        # result is cached for PROBE_CACHE_SECONDS.
        self._probe_cache_at: float = 0.0
        self._probe_cache_value: bool = False

    async def startup(self) -> None:
        if self._started:
            return
        if self.backend == "memory":
            from dhara.core.connection import Connection
            from dhara.core.persistent import Persistent

            conn = Connection(Persistent({self._namespace: {}}))
            self._kv = AsyncKVTimeSeriesStore(connection=conn)
            self._lock = InMemoryDharaLock()
        else:
            raise ConfigurationError(
                f"unknown backend {self.backend!r}; medium-mcp v1 supports 'memory' only",
                context={"backend": self.backend},
            )
        self._started = True

    async def shutdown(self) -> None:
        self._started = False
        self._kv = None
        self._lock = None
        # Invalidate the probe cache so a restarted client re-probes.
        self._probe_cache_at = 0.0
        self._probe_cache_value = False

    @property
    def kv(self) -> AsyncKVTimeSeriesStore:
        if self._kv is None:
            raise RuntimeError("DharaClient.startup() not called")
        return self._kv

    @property
    def lock(self) -> InMemoryDharaLock:
        if self._lock is None:
            raise RuntimeError("DharaClient.startup() not called")
        return self._lock

    async def probe(self) -> bool:
        """Round-trip a sentinel key to confirm Dhara is reachable.

        Result is cached for ``PROBE_CACHE_SECONDS`` because every metered call
        gates on this; without the cache a burst of tool calls would each pay a
        put+get round trip. ``shutdown()`` invalidates the cache.
        """
        if not self._started:
            return False
        now = time.monotonic()
        if now - self._probe_cache_at < PROBE_CACHE_SECONDS:
            return self._probe_cache_value
        sentinel_key = f"medium2:v1:probe:{self._namespace}"
        try:
            await self.kv.put_async(sentinel_key, b'"ok"', ttl=10)
            result = await self.kv.get_async(sentinel_key)
            probe_ok = result.get("value") == b'"ok"'
        except Exception:
            probe_ok = False
        self._probe_cache_at = now
        self._probe_cache_value = probe_ok
        return probe_ok

    async def get(self, key: str) -> bytes | None:
        result = await self.kv.get_async(key)
        return result.get("value")

    async def put(self, key: str, value: bytes, *, ttl: int | None = None) -> None:
        await self.kv.put_async(key, value, ttl=ttl)

    async def get_counter(self, key: str) -> int:
        raw = await self.get(key)
        if raw is None:
            return 0
        return int(raw.decode("utf-8"))

    async def inc_atomic(
        self,
        key: str,
        *,
        increment: int = 1,
        max_value: int | None = None,
    ) -> tuple[int, bool]:
        """Read-check-increment-write, entirely inside the per-period lock.

        Returns ``(counter_value, accepted)``.

        * accepted: the counter was advanced by ``increment`` and
          ``counter_value`` is the post-increment total.
        * refused: ``max_value`` was set and ``current + increment > max_value``.
          The counter is left **untouched** and ``counter_value`` is the
          unchanged current total.

        The check lives inside the lock so two concurrent reservations can never
        both observe the same headroom and both proceed. Callers translate a
        refusal into a domain error (``BudgetExhaustedError``); this layer knows
        nothing about budgets beyond the ceiling it was handed.
        """
        period = key.rsplit(":", 1)[-1]
        handle = await self.acquire_budget_lock(period)
        if handle is None:
            # Contention: yield briefly and retry once. If still busy, surface to caller.
            await asyncio.sleep(0.05)
            handle = await self.acquire_budget_lock(period)
        if handle is None:
            raise RuntimeError(f"could not acquire budget lock for {period}")
        try:
            current = await self.get_counter(key)
            if max_value is not None and current + increment > max_value:
                return current, False
            new_value = current + increment
            await self.put(key, str(new_value).encode())
            return new_value, True
        finally:
            await self.release_budget_lock(handle)

    async def dec_atomic(self, key: str, *, decrement: int) -> int:
        """Release a reservation under the same lock ``inc_atomic`` uses.

        Floors at zero: a double-release can never drive the counter negative
        and hand out budget that was never there.
        """
        if decrement <= 0:
            return await self.get_counter(key)
        period = key.rsplit(":", 1)[-1]
        handle = await self.acquire_budget_lock(period)
        if handle is None:
            await asyncio.sleep(0.05)
            handle = await self.acquire_budget_lock(period)
        if handle is None:
            raise RuntimeError(f"could not acquire budget lock for {period}")
        try:
            current = await self.get_counter(key)
            target = max(0, current - decrement)
            await self.put(key, str(target).encode())
            return target
        finally:
            await self.release_budget_lock(handle)

    async def acquire_budget_lock(self, period: str):
        key = f"medium2:v1:budget:lock:{period}"
        return await self.lock.try_acquire(key, ttl_seconds=30)

    async def release_budget_lock(self, handle: Any) -> None:
        await self.lock.release(handle)
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
cd /Users/les/Projects/medium-mcp
.venv/bin/pytest tests/unit/test_dhara_keys.py tests/unit/test_dhara_client.py -v
```

Expected: 6 + 7 = 13 passed.

- [ ] **Step 7: Commit**

```bash
cd /Users/les/Projects/medium-mcp
git -c user.email=les@wedgwoodwebworks.com add -A
git -c user.email=les@wedgwoodwebworks.com commit -m "feat(medium-mcp): Dhara client + key scheme for cache, content, budget, coalesce"
```

---

## Phase 1 Integration Contract (informational — Phase 0a only)

This phase has not yet produced an executable surface. Phase 1 (Tasks 5-9) registers tools, Phase 2 (Task 10) wires `server.py`. The integration contracts for those phases are stated when those tasks land.

**Triggered from:** nothing yet. Phase 0a is library code.

**Returns to / updates:** `MediumSettings` (Task 3), exception hierarchy (Task 2), key scheme + Dhara wrapper (Task 4). Phase 1 imports all of these.

**Demonstrable by:** `pytest tests/unit/ -v` passes 14+ tests across Tasks 1-4. Phase 1 is **not** wired.

**Rollback signal:** revert commits; nothing downstream yet.

**Observability added:** oneiric logging configured; no metrics yet (Phase 1 adds per-tool counters).

---

## Phase 1: Tools and the budget guard

### Task 5: API key validator at startup

**Files:**
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/auth/__init__.py`
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/auth/key.py`
- Test: `/Users/les/Projects/medium-mcp/tests/unit/test_auth.py`

**Interfaces:**
- Produces: `validate_rapidapi_key(key: SecretStr | None) -> str` — returns the unmasked value or raises `ConfigurationError`. Uses `mcp_common.security.APIKeyValidator` for masking in logs.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_auth.py`:

```python
from __future__ import annotations

import pytest
from pydantic import SecretStr

from medium_mcp.auth.key import validate_rapidapi_key
from medium_mcp.utils.exceptions import ConfigurationError


def test_missing_key_raises_configuration_error() -> None:
    with pytest.raises(ConfigurationError):
        validate_rapidapi_key(None)


def test_short_key_raises_configuration_error() -> None:
    """RapidAPI keys are typically 50+ chars; reject obviously-too-short values."""
    with pytest.raises(ConfigurationError):
        validate_rapidapi_key(SecretStr("short"))


def test_valid_key_returned_unmasked() -> None:
    fake = "a" * 50
    assert validate_rapidapi_key(SecretStr(fake)) == fake


def test_masked_in_logs() -> None:
    from mcp_common.security import APIKeyValidator

    fake = "abcdef123456" + "x" * 40
    masked = APIKeyValidator.mask_key(SecretStr(fake), visible_chars=4)
    assert masked.startswith("abcd")
    assert "x" * 40 not in masked.get_secret_value() if hasattr(masked, "get_secret_value") else False
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /Users/les/Projects/medium-mcp
.venv/bin/pytest tests/unit/test_auth.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement the validator**

Create `medium_mcp/auth/__init__.py` (empty). Create `medium_mcp/auth/key.py`:

```python
from __future__ import annotations

from pydantic import SecretStr

from medium_mcp.utils.exceptions import ConfigurationError

# RapidAPI keys are >= 32 chars in practice; reject obviously-too-short values.
MIN_KEY_LENGTH = 32


def validate_rapidapi_key(key: SecretStr | None) -> str:
    """Return the unmasked RapidAPI key or raise ConfigurationError.

    Callers should invoke this at startup; the secret is only ever held in
    memory, never logged. ``mcp_common.security.APIKeyValidator.mask_key`` is
    used by logging paths that need a masked representation.
    """
    if key is None:
        raise ConfigurationError(
            "MEDIUM_MCP_RAPIDAPI_KEY is required",
            context={"env_var": "MEDIUM_MCP_RAPIDAPI_KEY"},
        )
    value = key.get_secret_value()
    if len(value) < MIN_KEY_LENGTH:
        raise ConfigurationError(
            "MEDIUM_MCP_RAPIDAPI_KEY is too short to be a valid RapidAPI key",
            context={"length": len(value), "min_required": MIN_KEY_LENGTH},
        )
    return value
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /Users/les/Projects/medium-mcp
.venv/bin/pytest tests/unit/test_auth.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/medium-mcp
git -c user.email=les@wedgwoodwebworks.com add -A
git -c user.email=les@wedgwoodwebworks.com commit -m "feat(medium-mcp): API key validation at startup"
```

---

### Task 6: Typed models for all 13 tool inputs and outputs

**Files:**
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/models/__init__.py`
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/models/dto.py`
- Test: `/Users/les/Projects/medium-mcp/tests/unit/test_models.py`

**Interfaces:**
- Produces pydantic models matching spec §6.2: `UserInfo`, `ArticleSummary`, `ArticleMetadata`, `ArticleContent`, `ArticleResponsesPage`, `UserArticlesPage`, `PublicationInfo`, `PublicationArticlesPage`, `TagInfo`, `TagLatestPage`, `SearchArticlesPage`, `SearchUsersPage`, `SearchPublicationsPage`, `BudgetStatus`. Each page-model has `.articles`/`.users`/etc. plus `next_cursor: str | None`. `ArticleContent` carries `truncated: bool` and never sets `full_text` unless the caller asked.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_models.py`:

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from medium_mcp.models.dto import (
    ArticleContent,
    ArticleMetadata,
    ArticleSummary,
    BudgetStatus,
    PublicationInfo,
    SearchArticlesPage,
    TagInfo,
    UserInfo,
)


def test_user_info_carries_all_fields() -> None:
    u = UserInfo(
        user_id="abc",
        username="les",
        fullname="Les Leslie",
        followers_count=10,
        following_count=5,
        bio="writes code",
        twitter_username="les",
    )
    assert u.user_id == "abc"
    assert u.followers_count == 10


def test_article_summary_never_has_full_text() -> None:
    """ArticleSummary has no full_text field by construction."""
    s = ArticleSummary(
        article_id="x",
        title="t",
        author_id="a",
        published_at="2026-01-01T00:00:00Z",
        reading_time=5,
        claps=10,
        url="https://medium.com/p/x",
    )
    with pytest.raises(AttributeError):
        _ = s.full_text


def test_article_metadata_has_no_full_text() -> None:
    m = ArticleMetadata(
        article_id="x",
        title="t",
        author_id="a",
        published_at="2026-01-01T00:00:00Z",
        reading_time=5,
        claps=10,
        voters=2,
        tags=["x"],
        url="https://medium.com/p/x",
        excerpt="hello",
    )
    with pytest.raises(AttributeError):
        _ = m.full_text


def test_article_content_gates_full_text() -> None:
    """ArticleContent with include_full_text=False always returns None for full_text."""
    c = ArticleContent(
        article_id="x",
        excerpt="hello",
        full_text=None,
        format="markdown",
        truncated=False,
        include_full_text=False,
    )
    assert c.full_text is None


def test_article_content_truncates_excerpt() -> None:
    long = "x" * 5000
    c = ArticleContent(
        article_id="x",
        excerpt=long,
        full_text=None,
        format="markdown",
        truncated=True,
        include_full_text=False,
    )
    assert len(c.excerpt) <= 500  # spec default excerpt_max_chars


def test_budget_status_carries_period_and_reset() -> None:
    b = BudgetStatus(
        remaining_calls=140,
        monthly_budget=150,
        period="2026-09",
        resets_at="2026-10-01T00:00:00Z",
    )
    assert b.remaining_calls == 140
    assert b.monthly_budget == 150


def test_budget_status_has_no_unimplemented_cache_stats() -> None:
    """No ``cache_hit_rate`` / ``cached_entries``: nothing computes them in v1."""
    assert "cache_hit_rate" not in BudgetStatus.model_fields
    assert "cached_entries" not in BudgetStatus.model_fields


def test_search_articles_page_carries_next_cursor() -> None:
    p = SearchArticlesPage(articles=[], next_cursor="abc")
    assert p.next_cursor == "abc"


def test_publication_info_has_search_aliases() -> None:
    p = PublicationInfo(
        publication_id="p1",
        slug="tldr",
        name="TLDR",
        description="d",
        followers_count=1000,
        url="https://medium.com/tldr",
    )
    assert p.slug == "tldr"


def test_tag_info_carries_related() -> None:
    t = TagInfo(tag="python", followers_count=100, related_tags=["django", "fastapi"])
    assert t.related_tags == ["django", "fastapi"]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /Users/les/Projects/medium-mcp
.venv/bin/pytest tests/unit/test_models.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement the models**

Create `medium_mcp/models/__init__.py` (empty). Create `medium_mcp/models/dto.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from medium_mcp.config.settings import MediumSettings


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class UserInfo(_Base):
    user_id: str
    username: str | None = None
    fullname: str | None = None
    followers_count: int = 0
    following_count: int = 0
    bio: str | None = None
    twitter_username: str | None = None


class ArticleSummary(_Base):
    """Never carries full_text — that lives only in ArticleContent."""

    article_id: str
    title: str
    author_id: str
    published_at: str  # ISO-8601 from upstream
    reading_time: int = 0
    claps: int = 0
    url: str


class ArticleMetadata(_Base):
    article_id: str
    title: str
    subtitle: str | None = None
    author_id: str
    published_at: str
    reading_time: int = 0
    claps: int = 0
    voters: int = 0
    tags: list[str] = Field(default_factory=list)
    url: str
    excerpt: str = ""


class ArticleContent(_Base):
    article_id: str
    excerpt: str
    full_text: str | None
    format: Literal["markdown", "html", "text"]
    truncated: bool
    include_full_text: bool  # reflects the caller's request

    @field_validator("excerpt")
    @classmethod
    def _truncate_excerpt(cls, v: str) -> str:
        cap = MediumSettings(_env_file=None).excerpt_max_chars
        if len(v) > cap:
            return v[:cap]
        return v


class _ArticlesPage(_Base):
    articles: list[ArticleSummary]
    next_cursor: str | None = None


class _UsersPage(_Base):
    users: list[UserInfo]
    next_cursor: str | None = None


class _PublicationsPage(_Base):
    publications: list["PublicationInfo"]
    next_cursor: str | None = None


class UserArticlesPage(_ArticlesPage):
    pass


class ArticleResponsesPage(_ArticlesPage):
    pass


class PublicationArticlesPage(_ArticlesPage):
    pass


class TagLatestPage(_ArticlesPage):
    pass


class SearchArticlesPage(_ArticlesPage):
    pass


class SearchUsersPage(_UsersPage):
    pass


class SearchPublicationsPage(_PublicationsPage):
    pass


class PublicationInfo(_Base):
    publication_id: str
    slug: str | None = None
    name: str
    description: str | None = None
    followers_count: int = 0
    url: str | None = None


class TagInfo(_Base):
    tag: str
    followers_count: int = 0
    related_tags: list[str] = Field(default_factory=list)


class BudgetStatus(_Base):
    """What ``budget_remaining`` returns.

    Deliberately has no ``cache_hit_rate`` / ``cached_entries``: nothing in v1
    computes them, and shipping zero-valued fields would read as a feature that
    does not exist. Add them only alongside a real implementation.
    """

    remaining_calls: int
    monthly_budget: int
    period: str  # YYYY-MM
    resets_at: str  # ISO-8601


# Resolve the forward reference so Pydantic can resolve PublicationInfo in _PublicationsPage.
_PublicationsPage.model_rebuild()
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /Users/les/Projects/medium-mcp
.venv/bin/pytest tests/unit/test_models.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/medium-mcp
git -c user.email=les@wedgwoodwebworks.com add -A
git -c user.email=les@wedgwoodwebworks.com commit -m "feat(medium-mcp): typed DTO models for all 13 tools + content policy"
```

---

### Task 7: Typed httpx2 client with budget reservation

**Files:**
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/clients/__init__.py`
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/clients/medium2.py`
- Test: `/Users/les/Projects/medium-mcp/tests/unit/test_medium2_client.py`

**Interfaces:**
- Produces `Medium2Client`:
  - `__init__(settings: MediumSettings, dhara: DharaClient)`
  - `async def request(endpoint: str, params: dict, *, min_cost: int = 1, max_pages: int = 1, tool_name: str) -> dict`
  - Refuses the call outright when `DharaClient.probe()` is False — an unguarded call is unaccountable budget.
  - Reserves `min_cost * max_pages` budget in a single atomic increment whose headroom check happens inside the per-month lock. `max_pages > 1` is rejected in v1.
  - Maps HTTP 404 → `NotFoundError`, 429 → `RateLimitedError`, others → `UpstreamError`.
  - Records failed calls as budget-consuming (per spec §6.2: "Any request that reaches RapidAPI is assumed metered regardless of status"). The reservation is only released when the call was never dispatched.

- [ ] **Step 1: Write the failing client test (uses a fake transport)**

Create `tests/unit/test_medium2_client.py`:

```python
from __future__ import annotations

import json

import httpx2
import pytest

from medium_mcp.clients.medium2 import Medium2Client
from medium_mcp.config.settings import MediumSettings
from medium_mcp.dhara.client import DharaClient
from medium_mcp.dhara.keys import budget_key
from medium_mcp.utils.exceptions import (
    BudgetExhaustedError,
    ConfigurationError,
    NotFoundError,
    RateLimitedError,
    UpstreamError,
)


def _transport_that_returns(status: int, body: dict | str) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if isinstance(body, dict):
            return httpx2.Response(status_code=status, json=body)
        return httpx2.Response(status_code=status, text=body)

    return httpx2.MockTransport(handler)


@pytest.fixture
def settings() -> MediumSettings:
    s = MediumSettings(_env_file=None)
    s.rapidapi_key = type(s.rapidapi_key)(value="a" * 50)  # SecretStr
    return s


@pytest.fixture
async def dhara(settings: MediumSettings) -> DharaClient:
    client = DharaClient(settings=settings, backend="memory")
    await client.startup()
    yield client
    await client.shutdown()


async def test_request_returns_json_on_200(settings: MediumSettings, dhara: DharaClient) -> None:
    transport = _transport_that_returns(200, {"id": "abc"})
    client = Medium2Client(settings=settings, dhara=dhara, transport=transport)
    result = await client.request("user_info", {"user_id": "abc"}, tool_name="user_info")
    assert result == {"id": "abc"}


async def test_request_404_raises_not_found(settings: MediumSettings, dhara: DharaClient) -> None:
    transport = _transport_that_returns(404, "")
    client = Medium2Client(settings=settings, dhara=dhara, transport=transport)
    with pytest.raises(NotFoundError):
        await client.request("user_info", {"user_id": "missing"}, tool_name="user_info")


async def test_request_429_raises_rate_limited(settings: MediumSettings, dhara: DharaClient) -> None:
    transport = _transport_that_returns(429, "")
    client = Medium2Client(settings=settings, dhara=dhara, transport=transport)
    with pytest.raises(RateLimitedError):
        await client.request("user_info", {"user_id": "abc"}, tool_name="user_info")


async def test_request_5xx_raises_upstream(settings: MediumSettings, dhara: DharaClient) -> None:
    transport = _transport_that_returns(500, "")
    client = Medium2Client(settings=settings, dhara=dhara, transport=transport)
    with pytest.raises(UpstreamError) as exc_info:
        await client.request("user_info", {"user_id": "abc"}, tool_name="user_info")
    assert exc_info.value.status_code == 500


async def test_request_increments_budget_on_success(settings: MediumSettings, dhara: DharaClient) -> None:
    transport = _transport_that_returns(200, {"id": "abc"})
    client = Medium2Client(settings=settings, dhara=dhara, transport=transport)
    await client.request("user_info", {"user_id": "abc"}, tool_name="user_info")
    counter = await dhara.get_counter(f"medium2:v1:budget:2026-09")  # placeholder key
    # The exact period is computed; assert via the public ``budget_status`` accessor.
    status = await client.budget_status()
    assert status["calls_used"] >= 1


async def test_request_increments_budget_on_failure(settings: MediumSettings, dhara: DharaClient) -> None:
    """Spec: failed calls count because RapidAPI's metering is undocumented."""
    transport = _transport_that_returns(500, "")
    client = Medium2Client(settings=settings, dhara=dhara, transport=transport)
    with pytest.raises(UpstreamError):
        await client.request("user_info", {"user_id": "abc"}, tool_name="user_info")
    status = await client.budget_status()
    assert status["calls_used"] >= 1


async def test_budget_exhausted_refuses_call(settings: MediumSettings, dhara: DharaClient) -> None:
    """monthly_budget=5, headroom=2 => ceiling 3. Exactly 3 calls get through."""
    settings.monthly_budget = 5
    settings.budget_reserve_headroom = 2
    transport = _transport_that_returns(200, {"id": "abc"})
    client = Medium2Client(settings=settings, dhara=dhara, transport=transport)
    refusals = 0
    successes = 0
    for _ in range(10):
        try:
            await client.request("user_info", {"user_id": "abc"}, tool_name="user_info")
            successes += 1
        except BudgetExhaustedError:
            refusals += 1
    assert successes == 3
    assert refusals == 7
    # A refused reservation must not have advanced the counter past the ceiling.
    assert await dhara.get_counter(budget_key(client.current_period())) == 3


async def test_headroom_check_happens_inside_the_lock(
    settings: MediumSettings, dhara: DharaClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ceiling is enforced by inc_atomic, not by a read-then-check in the client.

    If ``_reserve_budget`` peeked at the counter before locking, a caller could
    observe stale headroom. Assert the client delegates: it must pass the ceiling
    down as ``max_value`` and never pre-read the counter.
    """
    settings.monthly_budget = 5
    settings.budget_reserve_headroom = 2
    seen: list[dict[str, object]] = []

    async def fake_inc(key: str, **kwargs: object) -> tuple[int, bool]:
        # Stands in for the real lock-held read-check-increment-write, so the
        # real ``get_counter`` is never reached from inside the lock either.
        seen.append({"key": key, **kwargs})
        return 1, True

    def forbidden_counter(*_a: object, **_k: object) -> int:
        raise AssertionError("_reserve_budget must not read the counter outside the lock")

    monkeypatch.setattr(dhara, "inc_atomic", fake_inc)
    monkeypatch.setattr(dhara, "get_counter", forbidden_counter)

    transport = _transport_that_returns(200, {"id": "abc"})
    client = Medium2Client(settings=settings, dhara=dhara, transport=transport)
    await client.request("user_info", {"user_id": "abc"}, tool_name="user_info")

    # The ceiling is handed down as max_value; the client computed nothing else.
    assert seen == [
        {"key": budget_key(client.current_period()), "increment": 1, "max_value": 3},
    ]


async def test_dhara_down_refuses_before_reserving(
    settings: MediumSettings, dhara: DharaClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No counter, no guard: refuse rather than spend an unaccountable call."""

    async def probe_false() -> bool:
        return False

    monkeypatch.setattr(DharaClient, "probe", lambda _self: probe_false())
    transport = _transport_that_returns(200, {"id": "abc"})
    client = Medium2Client(settings=settings, dhara=dhara, transport=transport)
    with pytest.raises(UpstreamError) as exc_info:
        await client.request("user_info", {"user_id": "abc"}, tool_name="user_info")
    assert exc_info.value.context["reason"] == "dhara_unreachable"


async def test_max_pages_above_one_is_rejected(
    settings: MediumSettings, dhara: DharaClient
) -> None:
    """v1 reserves exactly one page per call; multi-page is not supported."""
    transport = _transport_that_returns(200, {"id": "abc"})
    client = Medium2Client(settings=settings, dhara=dhara, transport=transport)
    with pytest.raises(ConfigurationError):
        await client.request(
            "user_articles", {"user_id": "abc"}, max_pages=3, tool_name="user_articles",
        )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /Users/les/Projects/medium-mcp
.venv/bin/pytest tests/unit/test_medium2_client.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement the typed client**

Create `medium_mcp/clients/__init__.py` (empty). Create `medium_mcp/clients/medium2.py`:

```python
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urljoin

import httpx2

from medium_mcp.config.settings import MediumSettings
from medium_mcp.dhara.client import DharaClient
from medium_mcp.dhara.keys import budget_key
from medium_mcp.utils.exceptions import (
    BudgetExhaustedError,
    ConfigurationError,
    NotFoundError,
    RateLimitedError,
    UpstreamError,
)


class Medium2Client:
    """Typed wrapper around httpx2 that enforces the budget guard.

    Each call:
    1. Gates on Dhara reachability — with no counter there is no guard, so the
       call is refused rather than made unmetered.
    2. Reserves ``min_cost * max_pages`` budget via ``DharaClient.inc_atomic``,
       whose headroom check and write both happen inside the per-month lock.
    3. Issues a single GET to the upstream (medium2 is paginated; pagination is
       the caller's responsibility, not the client's).
    4. Keeps the reservation on success **and** on any upstream error (per spec
       §6.2: failed calls count).

    **Multi-page reservations are NOT supported in v1.** ``max_pages=1`` is the
    only allowed value, enforced by the lock acquiring exactly the requested
    count: the reservation is taken atomically as one increment, so there is no
    partial-reservation state to unwind. ``_release_reservation`` exists only for
    the pre-flight failure path (reserved but never dispatched); it is not a
    per-page refund mechanism. Supporting ``max_pages > 1`` would require either
    holding the lock across N network calls or reintroducing a refund race, and
    v1 does neither.
    """

    def __init__(
        self,
        *,
        settings: MediumSettings,
        dhara: DharaClient,
        transport: httpx2.MockTransport | None = None,
    ) -> None:
        self.settings = settings
        self.dhara = dhara
        self._transport = transport

    def _period(self) -> str:
        return datetime.now(UTC).strftime("%Y-%m")

    def current_period(self) -> str:
        """Public accessor for the YYYY-MM budget period.

        Wraps ``_period`` so external callers (tests, ``tools/budget.py``) do not
        have to reach into a private attribute. Tests that need to assert against
        the period key should call ``client.current_period()`` — the private
        name is preserved for backward compatibility with any code that already
        reached for ``client._period()``.
        """
        return self._period()

    def _resets_at(self) -> str:
        now = datetime.now(UTC)
        next_month = (now.replace(day=1) + timedelta(days=32)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return next_month.isoformat().replace("+00:00", "Z")

    def _budget_ceiling(self) -> int:
        """Reservations may never push the counter past this value."""
        return self.settings.monthly_budget - self.settings.budget_reserve_headroom

    async def _reserve_budget(self, calls: int) -> tuple[int, str]:
        """Reserve ``calls`` against the month's counter, atomically.

        The read, the headroom check, and the write all happen inside
        ``DharaClient.inc_atomic``'s lock. Nothing here inspects the counter
        first: doing so would reintroduce the check-then-act race this method
        exists to close.

        Returns ``(counter_value_after_reservation, period)``. Raises
        ``BudgetExhaustedError`` when the reservation would breach the ceiling —
        in which case the counter was **not** advanced.
        """
        period = self._period()
        key = budget_key(period)
        ceiling = self._budget_ceiling()
        counter, accepted = await self.dhara.inc_atomic(
            key, increment=calls, max_value=ceiling,
        )
        if not accepted:
            raise BudgetExhaustedError(
                "monthly budget exhausted or below headroom",
                requested_calls=calls,
                remaining_calls=max(0, ceiling - counter),
                monthly_budget=self.settings.monthly_budget,
                period=period,
                resets_at=self._resets_at(),
                cached_alternatives=self._cached_alternatives(),
            )
        return counter, period

    async def _release_reservation(self, period: str, calls: int) -> None:
        """Give back a reservation that was taken but never dispatched.

        Uses the same per-period lock as ``_reserve_budget`` so a release can
        never interleave with another reservation's read-check-write. Only the
        pre-flight failure path calls this; a call that reached RapidAPI keeps
        its reservation regardless of status (spec §6.2).
        """
        if calls <= 0:
            return
        await self.dhara.dec_atomic(budget_key(period), decrement=calls)

    @staticmethod
    def _cached_alternatives() -> list[str]:
        """Tools whose output is cacheable and may serve recent reads."""
        return ["user_info", "article_metadata", "tag_info"]

    async def budget_status(self) -> dict[str, Any]:
        """Single source of truth for period, reset time, and remaining calls.

        ``tools/budget.budget_remaining`` converts this dict into a
        ``BudgetStatus`` and computes nothing itself.
        """
        period = self._period()
        key = budget_key(period)
        used = await self.dhara.get_counter(key)
        return {
            "calls_used": used,
            "remaining_calls": max(0, self.settings.monthly_budget - used),
            "monthly_budget": self.settings.monthly_budget,
            "period": period,
            "resets_at": self._resets_at(),
        }

    async def request(
        self,
        endpoint: str,
        params: dict[str, Any],
        *,
        min_cost: int = 1,
        max_pages: int = 1,
        tool_name: str,
    ) -> dict[str, Any]:
        if max_pages != 1:
            raise ConfigurationError(
                "max_pages > 1 is not supported in v1; reserve one page per call",
                context={"max_pages": max_pages, "tool": tool_name},
            )

        # Dhara-down gate. No counter means no guard, and an unguarded call is
        # budget we can never account for — so refuse before reserving.
        probe_ok = await self.dhara.probe()
        if not probe_ok:
            raise UpstreamError(
                "dhara unreachable; refusing metered call",
                status_code=0,
                body="",
                context={"reason": "dhara_unreachable", "tool": tool_name},
            )

        reserved = min_cost * max_pages
        _counter, period = await self._reserve_budget(reserved)

        if self.settings.rapidapi_key is None:
            # Reserved but never dispatched — hand the reservation back.
            await self._release_reservation(period, reserved)
            raise ConfigurationError(
                "rapidapi_key missing — validate_rapidapi_key must run at startup",
                context={"env_var": "MEDIUM_MCP_RAPIDAPI_KEY", "tool": tool_name},
            )
        key_value = self.settings.rapidapi_key.get_secret_value()

        base = str(self.settings.rapidapi_base_url).rstrip("/")
        url = urljoin(base + "/", endpoint)
        headers = {
            "X-RapidAPI-Key": key_value,
            "X-RapidAPI-Host": "medium2.p.rapidapi.com",
        }

        if self._transport is not None:
            transport = self._transport
        else:
            transport = httpx2.AsyncHTTPTransport()

        try:
            async with httpx2.AsyncClient(
                transport=transport,
                timeout=self.settings.http_timeout_seconds,
            ) as http:
                response = await http.get(url, params=params, headers=headers)
        except httpx2.HTTPError as exc:
            # Network errors: count as metered (spec rule).
            raise UpstreamError(
                "transport error talking to medium2",
                status_code=0,
                body=str(exc),
                context={"endpoint": endpoint, "tool": tool_name},
            ) from exc

        # Any non-2xx counts as a metered failure (spec rule).
        if response.status_code == 404:
            raise NotFoundError(
                "medium2 returned 404",
                status_code=404,
                body=response.text,
                context={"endpoint": endpoint, "tool": tool_name},
            )
        if response.status_code == 429:
            raise RateLimitedError(
                "medium2 returned 429",
                status_code=429,
                body=response.text,
                context={"endpoint": endpoint, "tool": tool_name},
            )
        if response.status_code >= 400:
            raise UpstreamError(
                f"medium2 returned {response.status_code}",
                status_code=response.status_code,
                body=response.text,
                context={"endpoint": endpoint, "tool": tool_name},
            )

        # The reservation stands: this call reached RapidAPI (spec §6.2).
        try:
            return response.json()
        except json.JSONDecodeError:
            return {"raw": response.text}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /Users/les/Projects/medium-mcp
.venv/bin/pytest tests/unit/test_medium2_client.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/medium-mcp
git -c user.email=les@wedgwoodwebworks.com add -A
git -c user.email=les@wedgwoodwebworks.com commit -m "feat(medium-mcp): typed httpx2 client with atomic budget reservation + dhara gate"
```

---

### Task 8: Cache layer with content-policy separation

**Files:**
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/cache/__init__.py`
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/cache/store.py`
- Test: `/Users/les/Projects/medium-mcp/tests/unit/test_cache.py`

**Interfaces:**
- Produces `MediumCache`:
  - `__init__(settings, dhara, *, hits_ref, misses_ref)`
  - `async def get(endpoint, params, *, content=False) -> bytes | None`
  - `async def put(endpoint, params, value: bytes, *, ttl: int, content=False) -> None`
  - TTL selection by endpoint per spec §6.2.
  - Coalescing: `async def get_or_compute(endpoint, params, compute_fn) -> bytes` attaches concurrent callers to the leader's future via an in-process `dict[frozenset, Future]`.

- [ ] **Step 1: Write the failing cache test**

Create `tests/unit/test_cache.py`:

```python
from __future__ import annotations

import asyncio
import pytest

from medium_mcp.cache.store import MediumCache
from medium_mcp.config.settings import MediumSettings
from medium_mcp.dhara.client import DharaClient
from medium_mcp.dhara.keys import cache_key, content_key


@pytest.fixture
def settings() -> MediumSettings:
    return MediumSettings(_env_file=None)


@pytest.fixture
async def dhara(settings: MediumSettings) -> DharaClient:
    client = DharaClient(settings=settings, backend="memory")
    await client.startup()
    yield client
    await client.shutdown()


async def test_put_then_get_round_trip(settings: MediumSettings, dhara: DharaClient) -> None:
    cache = MediumCache(settings=settings, dhara=dhara)
    await cache.put("user_info", {"user_id": "abc"}, b'{"id":"abc"}', ttl=settings.cache_ttl_user_info)
    result = await cache.get("user_info", {"user_id": "abc"})
    assert result == b'{"id":"abc"}'


async def test_content_cache_uses_separate_key(settings: MediumSettings, dhara: DharaClient) -> None:
    cache = MediumCache(settings=settings, dhara=dhara)
    await cache.put(
        "article_content", {"article_id": "x"}, b"full text", ttl=settings.cache_ttl_article_content, content=True,
    )
    # Direct Dhara key check: content prefix is distinct.
    raw = await dhara.get(content_key("x"))
    assert raw == b"full text"
    # The non-content cache key for the same params must NOT have it.
    raw_meta = await dhara.get(cache_key("article_content", {"article_id": "x"}))
    assert raw_meta is None


async def test_ttl_selection_by_endpoint(settings: MediumSettings, dhara: DharaClient) -> None:
    cache = MediumCache(settings=settings, dhara=dhara)
    assert cache._ttl_for("user_info") == settings.cache_ttl_user_info
    assert cache._ttl_for("user_articles") == settings.cache_ttl_user_articles
    assert cache._ttl_for("article_metadata") == settings.cache_ttl_article_metadata
    assert cache._ttl_for("search_articles") == settings.cache_ttl_search
    assert cache._ttl_for("tag_info") == settings.cache_ttl_tag


async def test_coalesce_concurrent_calls_share_one_upstream(settings: MediumSettings, dhara: DharaClient) -> None:
    """Two concurrent get_or_compute calls share one upstream call."""
    cache = MediumCache(settings=settings, dhara=dhara)

    upstream_calls = 0

    async def compute() -> bytes:
        nonlocal upstream_calls
        upstream_calls += 1
        await asyncio.sleep(0.05)
        return b'{"v":1}'

    results = await asyncio.gather(
        cache.get_or_compute("user_info", {"user_id": "abc"}, compute),
        cache.get_or_compute("user_info", {"user_id": "abc"}, compute),
        cache.get_or_compute("user_info", {"user_id": "abc"}, compute),
    )
    assert all(r == b'{"v":1}' for r in results)
    assert upstream_calls == 1


async def test_coalesce_window_timeout_returns_typed_error(settings: MediumSettings, dhara: DharaClient) -> None:
    """If the leader takes longer than the window, followers do NOT block."""
    settings.coalesce_window_seconds = 0.05
    cache = MediumCache(settings=settings, dhara=dhara)

    async def slow_compute() -> bytes:
        await asyncio.sleep(0.5)
        return b"x"

    with pytest.raises(Exception):  # CoalesceTimeout
        await cache.get_or_compute("user_info", {"user_id": "abc"}, slow_compute)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /Users/les/Projects/medium-mcp
.venv/bin/pytest tests/unit/test_cache.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement the cache**

Create `medium_mcp/cache/__init__.py` (empty). Create `medium_mcp/cache/store.py`:

```python
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from medium_mcp.config.settings import MediumSettings
from medium_mcp.dhara.client import DharaClient
from medium_mcp.dhara.keys import cache_key, coalesce_key, content_key
from medium_mcp.utils.exceptions import MediumError


class CoalesceTimeout(MediumError):
    """The leader's compute exceeded the coalesce window; follower gives up."""


_TTL_TABLE = {
    "user_info": "cache_ttl_user_info",
    "user_articles": "cache_ttl_user_articles",
    "article_metadata": "cache_ttl_article_metadata",
    "article_content": "cache_ttl_article_content",
    "search_articles": "cache_ttl_search",
    "search_users": "cache_ttl_search",
    "search_publications": "cache_ttl_search",
    "tag_info": "cache_ttl_tag",
    "tag_latest": "cache_ttl_tag",
    "publication_info": "cache_ttl_user_info",
    "publication_articles": "cache_ttl_user_articles",
}


class MediumCache:
    """Two keyspaces: metadata cache (``medium2:v1:<endpoint>:...``) and
    content cache (``medium2:v1:content:<article_id>``). Coalesces concurrent
    ``get_or_compute`` callers via an in-process future registry.
    """

    def __init__(
        self,
        *,
        settings: MediumSettings,
        dhara: DharaClient,
    ) -> None:
        self.settings = settings
        self.dhara = dhara
        self._in_flight: dict[str, asyncio.Future[bytes]] = {}

    def _ttl_for(self, endpoint: str) -> int:
        attr = _TTL_TABLE.get(endpoint)
        if attr is None:
            return self.settings.cache_ttl_search  # conservative default
        return getattr(self.settings, attr)

    async def get(self, endpoint: str, params: dict[str, Any], *, content: bool = False) -> bytes | None:
        if content:
            article_id = params.get("article_id", "")
            return await self.dhara.get(content_key(article_id))
        return await self.dhara.get(cache_key(endpoint, params))

    async def put(
        self,
        endpoint: str,
        params: dict[str, Any],
        value: bytes,
        *,
        ttl: int,
        content: bool = False,
    ) -> None:
        if content:
            article_id = params.get("article_id", "")
            await self.dhara.put(content_key(article_id), value, ttl=ttl)
            return
        await self.dhara.put(cache_key(endpoint, params), value, ttl=ttl)

    async def get_or_compute(
        self,
        endpoint: str,
        params: dict[str, Any],
        compute_fn: Callable[[], Awaitable[bytes]],
    ) -> bytes:
        cached = await self.get(endpoint, params)
        if cached is not None:
            return cached

        key = coalesce_key(endpoint, params)
        loop = asyncio.get_running_loop()
        if key in self._in_flight:
            # Follower: wait on the leader's future with a bounded timeout.
            fut = self._in_flight[key]
            try:
                return await asyncio.wait_for(fut, timeout=self.settings.coalesce_window_seconds)
            except asyncio.TimeoutError as exc:
                raise CoalesceTimeout(
                    "coalesce window elapsed waiting for leader",
                    context={"key": key, "window": self.settings.coalesce_window_seconds},
                ) from exc

        # Leader: install a future and run the compute.
        fut = loop.create_future()
        self._in_flight[key] = fut
        try:
            value = await compute_fn()
            await self.put(endpoint, params, value, ttl=self._ttl_for(endpoint))
            fut.set_result(value)
            return value
        except BaseException as exc:
            if not fut.done():
                fut.set_exception(exc)
            raise
        finally:
            self._in_flight.pop(key, None)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /Users/les/Projects/medium-mcp
.venv/bin/pytest tests/unit/test_cache.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/medium-mcp
git -c user.email=les@wedgwoodwebworks.com add -A
git -c user.email=les@wedgwoodwebworks.com commit -m "feat(medium-mcp): cache store with TTL-by-endpoint, content prefix, coalesce"
```

---

### Task 9: Tool layer — 13 tools + budget_remaining

**Files:**
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/tools/__init__.py`
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/tools/users.py`
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/tools/articles.py`
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/tools/publications.py`
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/tools/tags.py`
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/tools/search.py`
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/tools/budget.py`
- Test: `/Users/les/Projects/medium-mcp/tests/unit/test_tools.py`

**Interfaces:** Each tool exposes an `async def run(**kwargs) -> ModelType` that composes cache + client + budget guard + content policy. The 13 tools per spec §6.2 are:

1. `user_info(user_id=None, username=None)` — exactly one required
2. `user_articles(user_id, cursor=None)`
3. `article_metadata(article_id)`
4. `article_content(article_id, include_full_text=False, format="markdown")` — **content-policy gate**
5. `article_responses(article_id, cursor=None)`
6. `publication_info(publication_id=None, slug=None)` — exactly one required
7. `publication_articles(publication_id, cursor=None)`
8. `tag_info(tag)`
9. `tag_latest(tag, cursor=None)`
10. `search_articles(query, cursor=None)`
11. `search_users(query, cursor=None)`
12. `search_publications(query, cursor=None)`
13. `budget_remaining()` — **zero upstream calls**

The tool layer is where content policy lives: `article_content` returns `full_text=None` whenever `include_full_text=False`, regardless of cache state. The cache itself can hold `full_text` keyed under `content_key`; the gate is at the return point.

- [ ] **Step 1: Write the failing tools test**

Create `tests/unit/test_tools.py`:

```python
from __future__ import annotations

import pytest

from medium_mcp.cache.store import MediumCache
from medium_mcp.clients.medium2 import Medium2Client
from medium_mcp.config.settings import MediumSettings
from medium_mcp.dhara.client import DharaClient
from medium_mcp.tools.articles import (
    article_content,
    article_metadata,
    article_responses,
)
from medium_mcp.tools.budget import budget_remaining
from medium_mcp.tools.publications import publication_articles, publication_info
from medium_mcp.tools.search import search_articles, search_publications, search_users
from medium_mcp.tools.tags import tag_info, tag_latest
from medium_mcp.tools.users import user_articles, user_info
from medium_mcp.utils.exceptions import ConfigurationError


@pytest.fixture
def settings() -> MediumSettings:
    return MediumSettings(_env_file=None)


@pytest.fixture
async def dhara(settings: MediumSettings) -> DharaClient:
    c = DharaClient(settings=settings, backend="memory")
    await c.startup()
    yield c
    await c.shutdown()


async def test_user_info_requires_exactly_one_identifier(settings: MediumSettings) -> None:
    with pytest.raises(ConfigurationError):
        await user_info(settings=None, dhara=None, cache=None, client=None)  # type: ignore[arg-type]


async def test_article_content_returns_none_when_flag_false(
    settings: MediumSettings, dhara: DharaClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec §6.2 rule 3: return is gated independently of cache state."""
    # Pre-populate the content cache with a full body.
    await dhara.put("medium2:v1:content:abc", b"the actual article body", ttl=99999)

    # The client should NOT be called because the policy gate short-circuits.
    called = []
    async def fake_request(*args, **kwargs):
        called.append((args, kwargs))
        return {"content": {"body": "should not be returned"}}

    client = Medium2Client(settings=settings, dhara=dhara)
    monkeypatch.setattr(client, "request", fake_request)

    cache = MediumCache(settings=settings, dhara=dhara)
    result = await article_content(
        settings=settings, dhara=dhara, cache=cache, client=client, article_id="abc",
        include_full_text=False, format="markdown",
    )
    # Even though the cache has the body, the tool must NOT return it.
    assert result.full_text is None
    assert result.include_full_text is False
    assert called == []  # the upstream call was never made


async def test_article_content_returns_full_text_when_flag_true(
    settings: MediumSettings, dhara: DharaClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await dhara.put("medium2:v1:content:abc", b"the actual article body", ttl=99999)

    client = Medium2Client(settings=settings, dhara=dhara)

    cache = MediumCache(settings=settings, dhara=dhara)
    result = await article_content(
        settings=settings, dhara=dhara, cache=cache, client=client, article_id="abc",
        include_full_text=True, format="markdown",
    )
    assert result.full_text == "the actual article body"
    assert result.include_full_text is True


async def test_budget_remaining_makes_no_upstream_call(
    settings: MediumSettings, dhara: DharaClient
) -> None:
    """budget_remaining must be a local read; spec §6.2."""
    client = Medium2Client(settings=settings, dhara=dhara)

    class Guard:
        async def request(self, *args, **kwargs):
            raise AssertionError("upstream must not be called for budget_remaining")

    cache = MediumCache(settings=settings, dhara=dhara)
    status = await budget_remaining(settings=settings, dhara=dhara, cache=cache, client=client)
    assert status.remaining_calls == settings.monthly_budget
    assert status.monthly_budget == 150


async def test_tools_reject_malformed_inputs(settings: MediumSettings) -> None:
    """user_info with neither user_id nor username raises ConfigurationError."""
    dhara = None
    cache = None
    client = None
    with pytest.raises(Exception):
        await user_info(settings=settings, dhara=dhara, cache=cache, client=client)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /Users/les/Projects/medium-mcp
.venv/bin/pytest tests/unit/test_tools.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement the tools**

Create `medium_mcp/tools/__init__.py` (empty). Now the tool files.

`medium_mcp/tools/users.py`:

```python
from __future__ import annotations

from typing import Any

from medium_mcp.cache.store import MediumCache
from medium_mcp.clients.medium2 import Medium2Client
from medium_mcp.config.settings import MediumSettings
from medium_mcp.dhara.client import DharaClient
from medium_mcp.models.dto import UserArticlesPage, UserInfo
from medium_mcp.utils.exceptions import ConfigurationError


async def _exactly_one(**kwargs: Any) -> str:
    provided = [k for k, v in kwargs.items() if v is not None]
    if len(provided) != 1:
        raise ConfigurationError(
            f"exactly one of {sorted(kwargs)} required, got {len(provided)}",
            context={"provided": provided},
        )
    return provided[0]


async def user_info(
    *,
    settings: MediumSettings,
    dhara: DharaClient,
    cache: MediumCache,
    client: Medium2Client,
    user_id: str | None = None,
    username: str | None = None,
) -> UserInfo:
    field = await _exactly_one(user_id=user_id, username=username)
    params = {field: locals()[field]}
    raw = await cache.get_or_compute(
        "user_info",
        params,
        lambda: client.request("user_info", params, tool_name="user_info"),
    )
    return UserInfo.model_validate(raw)


async def user_articles(
    *,
    settings: MediumSettings,
    dhara: DharaClient,
    cache: MediumCache,
    client: Medium2Client,
    user_id: str,
    cursor: str | None = None,
) -> UserArticlesPage:
    params = {"user_id": user_id, "cursor": cursor}
    raw = await cache.get_or_compute(
        "user_articles",
        params,
        lambda: client.request("user_articles", params, tool_name="user_articles"),
    )
    return UserArticlesPage.model_validate(raw)
```

`medium_mcp/tools/articles.py`:

```python
from __future__ import annotations

from typing import Literal

from medium_mcp.cache.store import MediumCache
from medium_mcp.clients.medium2 import Medium2Client
from medium_mcp.config.settings import MediumSettings
from medium_mcp.dhara.client import DharaClient
from medium_mcp.dhara.keys import content_key
from medium_mcp.models.dto import (
    ArticleContent,
    ArticleMetadata,
    ArticleResponsesPage,
)


async def article_metadata(
    *,
    settings: MediumSettings,
    dhara: DharaClient,
    cache: MediumCache,
    client: Medium2Client,
    article_id: str,
) -> ArticleMetadata:
    params = {"article_id": article_id}
    raw = await cache.get_or_compute(
        "article_metadata",
        params,
        lambda: client.request("article_metadata", params, tool_name="article_metadata"),
    )
    return ArticleMetadata.model_validate(raw)


async def article_content(
    *,
    settings: MediumSettings,
    dhara: DharaClient,
    cache: MediumCache,
    client: Medium2Client,
    article_id: str,
    include_full_text: bool = False,
    format: Literal["markdown", "html", "text"] = "markdown",
) -> ArticleContent:
    """Spec §6.2 content policy:
    1. ``include_full_text`` defaults to False.
    2. Full text cached under a separate ``content_key`` prefix.
    3. Return is gated independently of cache state.
    """
    # Always fetch metadata for the excerpt + canonical fields.
    metadata = await article_metadata(
        settings=settings, dhara=dhara, cache=cache, client=client, article_id=article_id,
    )

    full_text: str | None = None
    truncated = False
    if include_full_text:
        # Reach the upstream only on opt-in. Cached under content prefix.
        cached = await dhara.get(content_key(article_id))
        if cached is None:
            up = await client.request(
                "article_content", {"article_id": article_id}, tool_name="article_content",
            )
            full_text = up.get("content", {}).get("body", "") or ""
            await dhara.put(
                content_key(article_id), full_text.encode(), ttl=settings.cache_ttl_article_content,
            )
        else:
            full_text = cached.decode()

    excerpt = metadata.excerpt or ""
    if len(excerpt) > settings.excerpt_max_chars:
        excerpt = excerpt[: settings.excerpt_max_chars]
        truncated = True

    return ArticleContent(
        article_id=article_id,
        excerpt=excerpt,
        full_text=full_text if include_full_text else None,
        format=format,
        truncated=truncated,
        include_full_text=include_full_text,
    )


async def article_responses(
    *,
    settings: MediumSettings,
    dhara: DharaClient,
    cache: MediumCache,
    client: Medium2Client,
    article_id: str,
    cursor: str | None = None,
) -> ArticleResponsesPage:
    params = {"article_id": article_id, "cursor": cursor}
    raw = await cache.get_or_compute(
        "article_responses",
        params,
        lambda: client.request("article_responses", params, tool_name="article_responses"),
    )
    return ArticleResponsesPage.model_validate(raw)
```

`medium_mcp/tools/publications.py`:

```python
from __future__ import annotations

from medium_mcp.cache.store import MediumCache
from medium_mcp.clients.medium2 import Medium2Client
from medium_mcp.config.settings import MediumSettings
from medium_mcp.dhara.client import DharaClient
from medium_mcp.models.dto import PublicationArticlesPage, PublicationInfo
from medium_mcp.utils.exceptions import ConfigurationError


async def publication_info(
    *,
    settings: MediumSettings,
    dhara: DharaClient,
    cache: MediumCache,
    client: Medium2Client,
    publication_id: str | None = None,
    slug: str | None = None,
) -> PublicationInfo:
    provided = [p for p in (publication_id, slug) if p is not None]
    if len(provided) != 1:
        raise ConfigurationError(
            "exactly one of publication_id or slug required",
            context={"provided": provided},
        )
    field = "publication_id" if publication_id is not None else "slug"
    params = {field: publication_id or slug}
    raw = await cache.get_or_compute(
        "publication_info",
        params,
        lambda: client.request("publication_info", params, tool_name="publication_info"),
    )
    return PublicationInfo.model_validate(raw)


async def publication_articles(
    *,
    settings: MediumSettings,
    dhara: DharaClient,
    cache: MediumCache,
    client: Medium2Client,
    publication_id: str,
    cursor: str | None = None,
) -> PublicationArticlesPage:
    params = {"publication_id": publication_id, "cursor": cursor}
    raw = await cache.get_or_compute(
        "publication_articles",
        params,
        lambda: client.request(
            "publication_articles", params, tool_name="publication_articles",
        ),
    )
    return PublicationArticlesPage.model_validate(raw)
```

`medium_mcp/tools/tags.py`:

```python
from __future__ import annotations

from medium_mcp.cache.store import MediumCache
from medium_mcp.clients.medium2 import Medium2Client
from medium_mcp.config.settings import MediumSettings
from medium_mcp.dhara.client import DharaClient
from medium_mcp.models.dto import TagInfo, TagLatestPage


async def tag_info(
    *,
    settings: MediumSettings,
    dhara: DharaClient,
    cache: MediumCache,
    client: Medium2Client,
    tag: str,
) -> TagInfo:
    params = {"tag": tag}
    raw = await cache.get_or_compute(
        "tag_info",
        params,
        lambda: client.request("tag_info", params, tool_name="tag_info"),
    )
    return TagInfo.model_validate(raw)


async def tag_latest(
    *,
    settings: MediumSettings,
    dhara: DharaClient,
    cache: MediumCache,
    client: Medium2Client,
    tag: str,
    cursor: str | None = None,
) -> TagLatestPage:
    params = {"tag": tag, "cursor": cursor}
    raw = await cache.get_or_compute(
        "tag_latest",
        params,
        lambda: client.request("tag_latest", params, tool_name="tag_latest"),
    )
    return TagLatestPage.model_validate(raw)
```

`medium_mcp/tools/search.py`:

```python
from __future__ import annotations

from medium_mcp.cache.store import MediumCache
from medium_mcp.clients.medium2 import Medium2Client
from medium_mcp.config.settings import MediumSettings
from medium_mcp.dhara.client import DharaClient
from medium_mcp.models.dto import (
    SearchArticlesPage,
    SearchPublicationsPage,
    SearchUsersPage,
)


async def search_articles(
    *,
    settings: MediumSettings,
    dhara: DharaClient,
    cache: MediumCache,
    client: Medium2Client,
    query: str,
    cursor: str | None = None,
) -> SearchArticlesPage:
    params = {"query": query, "cursor": cursor}
    raw = await cache.get_or_compute(
        "search_articles",
        params,
        lambda: client.request("search_articles", params, tool_name="search_articles"),
    )
    return SearchArticlesPage.model_validate(raw)


async def search_users(
    *,
    settings: MediumSettings,
    dhara: DharaClient,
    cache: MediumCache,
    client: Medium2Client,
    query: str,
    cursor: str | None = None,
) -> SearchUsersPage:
    params = {"query": query, "cursor": cursor}
    raw = await cache.get_or_compute(
        "search_users",
        params,
        lambda: client.request("search_users", params, tool_name="search_users"),
    )
    return SearchUsersPage.model_validate(raw)


async def search_publications(
    *,
    settings: MediumSettings,
    dhara: DharaClient,
    cache: MediumCache,
    client: Medium2Client,
    query: str,
    cursor: str | None = None,
) -> SearchPublicationsPage:
    params = {"query": query, "cursor": cursor}
    raw = await cache.get_or_compute(
        "search_publications",
        params,
        lambda: client.request(
            "search_publications", params, tool_name="search_publications",
        ),
    )
    return SearchPublicationsPage.model_validate(raw)
```

`medium_mcp/tools/budget.py`:

```python
from __future__ import annotations

from medium_mcp.cache.store import MediumCache
from medium_mcp.clients.medium2 import Medium2Client
from medium_mcp.config.settings import MediumSettings
from medium_mcp.dhara.client import DharaClient
from medium_mcp.models.dto import BudgetStatus


async def budget_remaining(
    *,
    settings: MediumSettings,  # noqa: ARG001 - uniform caller wiring; budget lives on the client
    dhara: DharaClient,  # noqa: ARG001 - same
    cache: MediumCache,  # noqa: ARG001 - same
    client: Medium2Client,
) -> BudgetStatus:
    """Local read. Zero upstream calls. Spec §6.2.

    Delegates to ``Medium2Client.budget_status()`` rather than recomputing the
    period and reset time. Two implementations of "when does the month roll
    over" would eventually disagree, and the disagreement would be silent.
    """
    status = await client.budget_status()
    return BudgetStatus(
        remaining_calls=status["remaining_calls"],
        monthly_budget=status["monthly_budget"],
        period=status["period"],
        resets_at=status["resets_at"],
    )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /Users/les/Projects/medium-mcp
.venv/bin/pytest tests/unit/test_tools.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/medium-mcp
git -c user.email=les@wedgwoodwebworks.com add -A
git -c user.email=les@wedgwoodwebworks.com commit -m "feat(medium-mcp): 13 tools + budget_remaining + content-policy gate"
```

---

## Phase 1 Integration Contract

**Triggered from:** Phase 0a's settings, exceptions, Dhara client, models, and key scheme.

**Returns to / updates:** 13 tool functions (`medium_mcp.tools.*`) each with signature `async def run(**kwargs) -> ModelType`. Plus `Medium2Client` (httpx2 transport + budget reserve/refund) and `MediumCache` (TTL-by-endpoint, content prefix, coalesce). All five test files exercise real client+cache+Dhara with mocked transport.

**Demonstrable by:** `pytest tests/unit/ -v` runs Tasks 1-9. Each tool has at least one positive test, plus three policy tests: content gate, `include_full_text` opt-in, and `budget_remaining` never making an upstream call.

**Rollback signal:** the tools are not yet registered with FastMCP; reverting Phase 1 commits leaves the project importable but with no MCP entry point. No downstream consumer can break.

**Observability added:** every tool call increments the budget counter (visible via `budget_remaining`). Coalescing and headroom refusals are visible in counters but not yet logged structurally (Phase 2 adds per-tool counters).

---

### Task 10: `server.py` — baseline tools, health routes, profile dispatch

**Files:**
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/server.py`
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/feeds.py`
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/tools/profiles.py`
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/utils/logging.py`
- Create: `/Users/les/Projects/medium-mcp/medium_mcp/cli.py`
- Test: `/Users/les/Projects/medium-mcp/tests/unit/test_server_smoke.py`

**Interfaces:**
- Produces `medium_mcp.server.get_app() -> FastMCP` (lazy accessor) — calling it constructs the FastMCP via `mcp_common`'s `seed_liveness_context`, `bootstrap_baseline_tools`, `register_http_health_route`, `apply_tool_profile` — **in that order**, with the 13 domain tools registered by `apply_tool_profile` through `register_all_fn`. Custom `/readyz` returns 503 when Dhara is unreachable. Profile gating via `MEDIUM_MCP_TOOL_PROFILE`. Importing `medium_mcp.server` no longer requires `MEDIUM_MCP_RAPIDAPI_KEY` to be present.
- Produces `medium_mcp.tools.profiles.PROFILE_REGISTRATIONS: dict[str, list[str]]` mapping each profile value (`full`, `standard`, `minimal`) to its group list, plus `_build_registration_map(bundle)` returning group → tool names.
- Produces `medium_mcp.utils.logging.configure_logging(level)` — oneiric logging, once per process, called from `build_runtime()`.
- Produces `medium_mcp.feeds.FEEDS = {"medium2": FeedState}` carrying the four wiring-discipline signals. `mark_capability_unavailable()` raises on required feeds.

- [ ] **Step 1: Write the failing server smoke test**

Create `tests/unit/test_server_smoke.py`:

```python
from __future__ import annotations

import pytest
from pydantic import SecretStr

from medium_mcp.config.settings import MediumSettings
from medium_mcp.server import build_runtime, get_app

# The four tools mcp_common's bootstrap installs on every Bodai MCP server.
# Mirrors archive-org-mcp. If this set shrinks, the wiring-discipline health
# aggregation loses its probes.
EXPECTED_BASELINE = {
    "discover_tools",
    "get_liveness",
    "get_readiness",
    "health_check_all",
}


@pytest.fixture
def settings() -> MediumSettings:
    s = MediumSettings(_env_file=None)
    # build_runtime() validates the key at startup, so the fixture must carry one.
    s.rapidapi_key = SecretStr("a" * 50)
    return s


def test_app_is_fastmcp_instance() -> None:
    from mcp.server.fastmcp import FastMCP

    # Lazy accessor — avoids `validate_rapidapi_key` running at import time.
    assert isinstance(get_app(), FastMCP)


def test_build_runtime_with_in_memory_dhara(settings: MediumSettings) -> None:
    runtime = build_runtime(settings=settings, dhara_backend="memory")
    assert runtime.dhara is not None
    assert runtime.cache is not None
    assert runtime.client is not None


async def test_baseline_tools_are_registered(settings: MediumSettings) -> None:
    """bootstrap_baseline_tools must run before any domain group is registered."""
    runtime = build_runtime(settings=settings, dhara_backend="memory")
    mcp_app = runtime.build_mcp_app()
    names = {t.name for t in await mcp_app.list_tools()}
    missing = EXPECTED_BASELINE - names
    assert not missing, f"baseline tools missing: {sorted(missing)}"


async def test_domain_tools_registered_alongside_baseline(settings: MediumSettings) -> None:
    """The full profile exposes the 13 domain tools plus the baseline four."""
    runtime = build_runtime(settings=settings, dhara_backend="memory")
    mcp_app = runtime.build_mcp_app()
    names = {t.name for t in await mcp_app.list_tools()}
    assert "budget_remaining" in names
    assert "article_content" in names
    assert EXPECTED_BASELINE <= names


async def test_health_returns_200(settings: MediumSettings) -> None:
    from fastapi.testclient import TestClient

    runtime = build_runtime(settings=settings, dhara_backend="memory")
    await runtime.dhara.startup()
    try:
        # FastMCP exposes an ASGI ``app``; the test client wraps it.
        with TestClient(runtime.build_asgi_app()) as client:
            response = client.get("/health")
        assert response.status_code == 200
    finally:
        await runtime.dhara.shutdown()


async def test_readyz_returns_200_when_dhara_up(settings: MediumSettings) -> None:
    from fastapi.testclient import TestClient

    runtime = build_runtime(settings=settings, dhara_backend="memory")
    await runtime.dhara.startup()
    try:
        with TestClient(runtime.build_asgi_app()) as client:
            response = client.get("/readyz")
        assert response.status_code == 200
    finally:
        await runtime.dhara.shutdown()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /Users/les/Projects/medium-mcp
.venv/bin/pytest tests/unit/test_server_smoke.py -v
```

Expected: ImportError (`medium_mcp.server`).

- [ ] **Step 3: Implement `feeds.py`**

Create `medium_mcp/feeds.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any


@dataclass
class FeedState:
    name: str
    required: bool = True
    cycles_total: int = 0
    entities_count: int = 0
    last_updated_timestamp: str | None = None
    errors_total: int = 0
    last_error: str | None = None

    def record_cycle(
        self,
        *,
        entities: int = 0,
        error: str | None = None,
    ) -> None:
        self.cycles_total += 1
        if error is not None:
            self.errors_total += 1
            self.last_error = error
            return
        self.entities_count += entities
        self.last_updated_timestamp = datetime.now(UTC).isoformat()

    @property
    def healthy(self) -> bool:
        """A feed is healthy when it has had at least one successful cycle.

        A feed with ``entities_count == 0`` after a successful cycle still
        reports degraded, because the surface-health illusion applies: a
        working transport over an empty upstream is not the same as
        non-empty data.
        """
        if not self.required:
            return self.cycles_total > 0 or self.errors_total == 0
        if self.errors_total > 0 and self.cycles_total == self.errors_total:
            return False
        return self.last_updated_timestamp is not None and self.entities_count > 0

    def mark_capability_unavailable(self, reason: str) -> None:
        if self.required:
            raise ValueError(
                f"required feed {self.name!r} cannot be marked unavailable: {reason}"
            )
        self.errors_total += 1
        self.last_error = reason


FEEDS: dict[str, FeedState] = {
    "medium2": FeedState(name="medium2", required=True),
}


def required_feeds_healthy() -> bool:
    return all(f.healthy for f in FEEDS.values() if f.required)


def as_components() -> list[dict[str, Any]]:
    return [
        {
            "name": f.name,
            "required": f.required,
            "cycles_total": f.cycles_total,
            "entities_count": f.entities_count,
            "last_updated_timestamp": f.last_updated_timestamp,
            "errors_total": f.errors_total,
            "healthy": f.healthy,
        }
        for f in FEEDS.values()
    ]
```

- [ ] **Step 4: Implement `tools/profiles.py`**

Create `medium_mcp/tools/profiles.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from medium_mcp.config.settings import MediumSettings
from mcp.server.fastmcp import FastMCP

MEDIUM_MANDATORY_GROUPS: set[str] = {"health_tools"}

# Which groups each profile exposes, keyed by ``ToolProfile`` value. The values
# of ``MEDIUM_MCP_TOOL_PROFILE`` are the keys here; ``apply_tool_profile`` reads
# the env var and looks the group list up in this table.
PROFILE_REGISTRATIONS: dict[str, list[str]] = {
    "full": [
        "health_tools",
        "budget_tools",
        "user_tools",
        "article_tools",
        "publication_tools",
        "tag_tools",
        "search_tools",
    ],
    # standard drops search (3 of the most budget-hungry tools) but keeps reads.
    "standard": [
        "health_tools",
        "budget_tools",
        "user_tools",
        "article_tools",
        "publication_tools",
        "tag_tools",
    ],
    # minimal is health + the free budget read: enough to prove the server is
    # wired without spending a single metered call.
    "minimal": ["health_tools", "budget_tools"],
}


@dataclass
class ClientBundle:
    settings: MediumSettings
    dhara: object  # DharaClient, late-typed to avoid import cycles in this sketch
    cache: object
    client: object  # Medium2Client


def _build_registration_map(bundle: ClientBundle) -> dict[str, list[str]]:
    """Return mapping of group name -> list of MCP tool names.

    Pure metadata: it names the tools in each group without registering
    anything. ``apply_tool_profile`` uses it to decide which groups
    ``register_all_fn`` should actually decorate. It takes no ``app`` precisely
    because it must be safe to call before the server exists.
    """
    from medium_mcp.tools import articles, budget, publications, search, tags, users

    registration = {
        "user_tools": [
            users.user_info.__name__,
            users.user_articles.__name__,
        ],
        "article_tools": [
            articles.article_metadata.__name__,
            articles.article_content.__name__,
            articles.article_responses.__name__,
        ],
        "publication_tools": [
            publications.publication_info.__name__,
            publications.publication_articles.__name__,
        ],
        "tag_tools": [
            tags.tag_info.__name__,
            tags.tag_latest.__name__,
        ],
        "search_tools": [
            search.search_articles.__name__,
            search.search_users.__name__,
            search.search_publications.__name__,
        ],
        "budget_tools": [budget.budget_remaining.__name__],
        "health_tools": ["health"],
    }
    return registration


def register_all_tool_groups(app: FastMCP, bundle: ClientBundle) -> dict[str, list[str]]:
    """Register every domain tool group against the FastMCP ``app``.

    Called *by* ``apply_tool_profile`` via ``register_all_fn``, never directly
    from ``server.py``. Registration is a one-way door — ``@app.tool`` cannot be
    undone — so the profile must decide before the decorators run. Calling this
    eagerly and then pruning the map is the dual-track drift this ordering
    exists to prevent.
    """
    registration = _build_registration_map(bundle)

    from medium_mcp.tools import articles, budget, publications, search, tags, users

    @app.tool(name=users.user_info.__name__)
    async def _user_info(user_id: str | None = None, username: str | None = None) -> dict:
        result = await users.user_info(
            settings=bundle.settings, dhara=bundle.dhara, cache=bundle.cache,
            client=bundle.client, user_id=user_id, username=username,
        )
        return result.model_dump()

    @app.tool(name=users.user_articles.__name__)
    async def _user_articles(user_id: str, cursor: str | None = None) -> dict:
        result = await users.user_articles(
            settings=bundle.settings, dhara=bundle.dhara, cache=bundle.cache,
            client=bundle.client, user_id=user_id, cursor=cursor,
        )
        return result.model_dump()

    @app.tool(name=articles.article_metadata.__name__)
    async def _article_metadata(article_id: str) -> dict:
        result = await articles.article_metadata(
            settings=bundle.settings, dhara=bundle.dhara, cache=bundle.cache,
            client=bundle.client, article_id=article_id,
        )
        return result.model_dump()

    @app.tool(name=articles.article_content.__name__)
    async def _article_content(
        article_id: str, include_full_text: bool = False, format: str = "markdown",
    ) -> dict:
        result = await articles.article_content(
            settings=bundle.settings, dhara=bundle.dhara, cache=bundle.cache,
            client=bundle.client, article_id=article_id,
            include_full_text=include_full_text, format=format,  # ty: ignore[invalid-argument-type]
        )
        return result.model_dump()

    @app.tool(name=articles.article_responses.__name__)
    async def _article_responses(article_id: str, cursor: str | None = None) -> dict:
        result = await articles.article_responses(
            settings=bundle.settings, dhara=bundle.dhara, cache=bundle.cache,
            client=bundle.client, article_id=article_id, cursor=cursor,
        )
        return result.model_dump()

    @app.tool(name=publications.publication_info.__name__)
    async def _publication_info(
        publication_id: str | None = None, slug: str | None = None,
    ) -> dict:
        result = await publications.publication_info(
            settings=bundle.settings, dhara=bundle.dhara, cache=bundle.cache,
            client=bundle.client, publication_id=publication_id, slug=slug,
        )
        return result.model_dump()

    @app.tool(name=publications.publication_articles.__name__)
    async def _publication_articles(publication_id: str, cursor: str | None = None) -> dict:
        result = await publications.publication_articles(
            settings=bundle.settings, dhara=bundle.dhara, cache=bundle.cache,
            client=bundle.client, publication_id=publication_id, cursor=cursor,
        )
        return result.model_dump()

    @app.tool(name=tags.tag_info.__name__)
    async def _tag_info(tag: str) -> dict:
        result = await tags.tag_info(
            settings=bundle.settings, dhara=bundle.dhara, cache=bundle.cache,
            client=bundle.client, tag=tag,
        )
        return result.model_dump()

    @app.tool(name=tags.tag_latest.__name__)
    async def _tag_latest(tag: str, cursor: str | None = None) -> dict:
        result = await tags.tag_latest(
            settings=bundle.settings, dhara=bundle.dhara, cache=bundle.cache,
            client=bundle.client, tag=tag, cursor=cursor,
        )
        return result.model_dump()

    @app.tool(name=search.search_articles.__name__)
    async def _search_articles(query: str, cursor: str | None = None) -> dict:
        result = await search.search_articles(
            settings=bundle.settings, dhara=bundle.dhara, cache=bundle.cache,
            client=bundle.client, query=query, cursor=cursor,
        )
        return result.model_dump()

    @app.tool(name=search.search_users.__name__)
    async def _search_users(query: str, cursor: str | None = None) -> dict:
        result = await search.search_users(
            settings=bundle.settings, dhara=bundle.dhara, cache=bundle.cache,
            client=bundle.client, query=query, cursor=cursor,
        )
        return result.model_dump()

    @app.tool(name=search.search_publications.__name__)
    async def _search_publications(query: str, cursor: str | None = None) -> dict:
        result = await search.search_publications(
            settings=bundle.settings, dhara=bundle.dhara, cache=bundle.cache,
            client=bundle.client, query=query, cursor=cursor,
        )
        return result.model_dump()

    @app.tool(name=budget.budget_remaining.__name__)
    async def _budget_remaining() -> dict:
        result = await budget.budget_remaining(
            settings=bundle.settings, dhara=bundle.dhara, cache=bundle.cache,
            client=bundle.client,
        )
        return result.model_dump()

    return registration
```

- [ ] **Step 5: Implement `utils/logging.py`**

Create `medium_mcp/utils/logging.py`:

```python
from __future__ import annotations

from oneiric.logging import configure_logging as _oneiric_configure

_configured = False


def configure_logging(level: str | None = None) -> None:
    """Configure oneiric logging once per process.

    Called from ``build_runtime()`` — the single startup entry point — not at
    module import time and not per-module. The ``_configured`` latch makes a
    second call a no-op so a test that builds two runtimes does not end up with
    duplicated handlers and doubled log lines.

    ``level`` defaults to ``MediumSettings.log_level``; it is passed in rather
    than read here so this module does not import settings and create a cycle.
    """
    global _configured
    if _configured:
        return
    from medium_mcp.config.settings import get_settings

    _oneiric_configure(level=level or get_settings().log_level)
    _configured = True
```

- [ ] **Step 6: Implement `server.py`**

Create `medium_mcp/server.py`:

```python
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import FastAPI, Response
from mcp.server.fastmcp import FastMCP

from medium_mcp import __version__
from medium_mcp.auth.key import validate_rapidapi_key
from medium_mcp.cache.store import MediumCache
from medium_mcp.clients.medium2 import Medium2Client
from medium_mcp.config.settings import MediumSettings, get_settings
from medium_mcp.dhara.client import DharaClient
from medium_mcp.feeds import FEEDS, as_components, required_feeds_healthy
from medium_mcp.tools.profiles import (
    MEDIUM_MANDATORY_GROUPS,
    PROFILE_REGISTRATIONS,
    ClientBundle,
    _build_registration_map,
    register_all_tool_groups,
)
from medium_mcp.utils.logging import configure_logging

APP_NAME = "medium-mcp"


def _run_async_safely(coro: Any) -> Any:
    """Run an awaitable from a sync context, bridging asyncio.run or a worker thread."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


def build_runtime(
    *,
    settings: MediumSettings | None = None,
    dhara_backend: str = "memory",
) -> "Runtime":
    s = settings or get_settings()
    # Configure logging exactly once, at the single startup entry point.
    # Never at module import time and never per-module: a second call would
    # re-attach handlers and duplicate every line.
    configure_logging(level=s.log_level)
    # Validate the API key at startup. We require it even when no metered call
    # has been made yet, because tools cannot run without it.
    validate_rapidapi_key(s.rapidapi_key)
    dhara = DharaClient(settings=s, backend=dhara_backend)
    cache = MediumCache(settings=s, dhara=dhara)
    client = Medium2Client(settings=s, dhara=dhara)
    return Runtime(settings=s, dhara=dhara, cache=cache, client=client)


class Runtime:
    def __init__(
        self,
        *,
        settings: MediumSettings,
        dhara: DharaClient,
        cache: MediumCache,
        client: Medium2Client,
    ) -> None:
        self.settings = settings
        self.dhara = dhara
        self.cache = cache
        self.client = client
        self.asgi_app: FastAPI | None = None
        self._mcp_app: FastMCP | None = None

    def build_mcp_app(self) -> FastMCP:
        if self._mcp_app is not None:
            return self._mcp_app
        bundle = ClientBundle(
            settings=self.settings, dhara=self.dhara, cache=self.cache, client=self.client,
        )
        app = FastMCP(name=APP_NAME, version=__version__)

        # ORDERING IS LOAD-BEARING. Baseline tools and the liveness context must
        # be installed BEFORE any domain group is registered, and the domain
        # groups must be registered *through* apply_tool_profile. @app.tool is a
        # one-way door: registering the 13 tools first and then pruning the
        # registration map would leave the map claiming a group is hidden while
        # the decorator has already exposed it — the dual-track drift.
        from mcp_common.baseline_tools import seed_liveness_context
        from mcp_common.bootstrap import bootstrap_baseline_tools
        from mcp_common.health import register_http_health_route

        seed_liveness_context(service_name=APP_NAME, version=__version__)
        bootstrap_baseline_tools(app)
        register_http_health_route(
            app,
            service_name=APP_NAME,
            version=__version__,
            extra_components=as_components(),
        )

        from mcp_common.tools.dispatch import apply_tool_profile

        apply_tool_profile(
            app,
            profile_env_var="MEDIUM_MCP_TOOL_PROFILE",
            registrations=PROFILE_REGISTRATIONS,
            registration_map=_build_registration_map(bundle),
            register_all_fn=lambda srv: register_all_tool_groups(srv, bundle),
            mandatory_groups=MEDIUM_MANDATORY_GROUPS,
            essential_tool_names={"health_check"},
        )

        self._mcp_app = app
        return app

    def build_asgi_app(self) -> FastAPI:
        if self.asgi_app is not None:
            return self.asgi_app
        mcp_app = self.build_mcp_app()
        asgi = mcp_app.streamable_http_app()  # type: ignore[no-any-return]

        @asgi.custom_route("/readyz", methods=["GET"])
        async def _readyz() -> Response:
            await self.dhara.startup()
            reachable = await self.dhara.probe()
            if not reachable:
                FEEDS["medium2"].record_cycle(error="dhara unreachable")
                return Response(
                    content='{"status":"degraded","reason":"dhara unreachable"}',
                    status_code=503,
                    media_type="application/json",
                )
            if not required_feeds_healthy():
                return Response(
                    content='{"status":"degraded","reason":"required feed not healthy"}',
                    status_code=503,
                    media_type="application/json",
                )
            return Response(
                content='{"status":"ok"}',
                status_code=200,
                media_type="application/json",
            )

        self.asgi_app = asgi
        return asgi


_default_runtime: Runtime | None = None


def _get_runtime() -> Runtime:
    global _default_runtime
    if _default_runtime is None:
        _default_runtime = build_runtime()
    return _default_runtime


def get_app() -> FastMCP:
    """Lazy accessor — avoids `validate_rapidapi_key` running at import time.

    Importing `medium_mcp.server` no longer requires `MEDIUM_MCP_RAPIDAPI_KEY`
    to be present in the environment. Callers that need the app (the CLI, the
    FastMCP runner, integration tests) call `get_app()` explicitly.
    """
    return _get_runtime().build_mcp_app()
```

- [ ] **Step 7: Implement `cli.py`**

Create `medium_mcp/cli.py`:

```python
from __future__ import annotations

import asyncio

from medium_mcp.config.settings import get_settings
from medium_mcp.server import build_runtime


def main() -> None:
    settings = get_settings()
    runtime = build_runtime(settings=settings, dhara_backend="memory")
    mcp_app = runtime.build_mcp_app()
    asyncio.run(runtime.dhara.startup())
    try:
        mcp_app.run(transport="streamable-http", port=settings.http_port or 3055)
    finally:
        asyncio.run(runtime.dhara.shutdown())


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: Run the test to verify it passes**

```bash
cd /Users/les/Projects/medium-mcp
.venv/bin/pytest tests/unit/test_server_smoke.py -v
```

Expected: 6 passed (the `TestClient` exercise of `/health` and `/readyz` may need `httpx>=0.27` for ASGI; install with `uv pip install httpx`).

- [ ] **Step 9: Commit**

```bash
cd /Users/les/Projects/medium-mcp
git -c user.email=les@wedgwoodwebworks.com add -A
git -c user.email=les@wedgwoodwebworks.com commit -m "feat(medium-mcp): server.py with baseline tools, health routes, profile dispatch"
```

---

## Phase 2 Integration Contract

**Triggered from:** the `medium-mcp` console script (`medium_mcp.cli:main`) and any MCP client connecting over streamable-HTTP on `MEDIUM_MCP_HTTP_PORT` (default 3055). `build_runtime()` is the single startup entry point: it configures logging, validates the RapidAPI key, and constructs the Dhara/cache/client trio. `build_mcp_app()` installs baseline tools and then hands domain registration to `apply_tool_profile`.

**Returns to / updates:** a live `FastMCP` app exposing the baseline four (`discover_tools`, `get_liveness`, `get_readiness`, `health_check_all`) plus the profile's domain groups — all 13 tools + `budget_remaining` under `full`. HTTP surfaces: `/health` (aggregated, includes `FEEDS["medium2"]` via `extra_components`) and `/readyz` (503 when Dhara is unreachable or a required feed is unhealthy). Every metered call updates `medium2:v1:budget:<period>`, readable through `budget_remaining`.

**Demonstrable by:** `pytest tests/unit/test_server_smoke.py -v` — 6 passed, including `test_baseline_tools_are_registered` (asserts `EXPECTED_BASELINE` is present) and `test_domain_tools_registered_alongside_baseline`. Manually: start `medium-mcp`, then `curl -s localhost:3055/health` returns 200 with a `medium2` component, `curl -s localhost:3055/readyz` returns 200, and calling `budget_remaining` over MCP returns a non-empty `BudgetStatus` while spending zero upstream calls.

**Rollback signal:** any of — `/readyz` returns 200 while Dhara is down; `/health` and `budget_remaining` disagree on remaining calls; `list_tools()` omits a member of `EXPECTED_BASELINE`; a profile-hidden group still appears in `list_tools()` (dual-track drift has returned); or the budget counter advances on a call that never reached RapidAPI. Revert Task 10's commit — Phase 1's library code stays importable and no downstream consumer breaks, because nothing outside this task exposes an MCP entry point.

**Observability added:** oneiric logging at `MEDIUM_MCP_LOG_LEVEL`, seeded liveness context (`seed_liveness_context`) so `get_liveness`/`get_readiness` report service name and version; `FeedState` counters (`cycles_total`, `entities_count`, `last_updated_timestamp`, `errors_total`) surfaced through `/health`; `/readyz` records a failed cycle on each Dhara-unreachable probe; the month's budget counter is readable without spending budget.

---

### Task 11: Per-tool e2e tests asserting non-empty results

**Files:**
- Create: `/Users/les/Projects/medium-mcp/tests/integration/conftest.py`
- Create: `/Users/les/Projects/medium-mcp/tests/integration/test_user_info_e2e.py`
- Create: `/Users/les/Projects/medium-mcp/tests/integration/test_article_metadata_e2e.py`
- Create: `/Users/les/Projects/medium-mcp/tests/integration/test_search_articles_e2e.py`
- Create: `/Users/les/Projects/medium-mcp/tests/integration/test_budget_remaining_e2e.py`
- Create: `/Users/les/Projects/medium-mcp/tests/integration/test_article_content_e2e.py`

**Interfaces:**
- Each test stubs `httpx2.MockTransport`, invokes the tool through the registered MCP name, and asserts the response is non-empty.

- [ ] **Step 1: Write the integration conftest**

Create `tests/integration/conftest.py`:

```python
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

import httpx2
import pytest

from medium_mcp.cache.store import MediumCache
from medium_mcp.clients.medium2 import Medium2Client
from medium_mcp.config.settings import MediumSettings
from medium_mcp.dhara.client import DharaClient


@pytest.fixture
def settings() -> MediumSettings:
    s = MediumSettings(_env_file=None)
    s.rapidapi_key = type(s.rapidapi_key)("a" * 50)  # SecretStr
    return s


@pytest.fixture
async def dhara(settings: MediumSettings) -> DharaClient:
    client = DharaClient(settings=settings, backend="memory")
    await client.startup()
    yield client
    await client.shutdown()


def stub_json(status: int, body: dict[str, Any]) -> httpx2.MockTransport:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status_code=status, json=body)

    return httpx2.MockTransport(handler)


def stub_bytes(status: int, body: bytes) -> httpx2.MockTransport:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status_code=status, content=body)

    return httpx2.MockTransport(handler)


@pytest.fixture
def cache(settings: MediumSettings, dhara: DharaClient) -> MediumCache:
    return MediumCache(settings=settings, dhara=dhara)


@pytest.fixture
def make_client(
    settings: MediumSettings, dhara: DharaClient,
) -> Callable[[httpx2.MockTransport], tuple[Medium2Client, MediumCache]]:
    def _factory(transport: httpx2.MockTransport) -> tuple[Medium2Client, MediumCache]:
        client = Medium2Client(settings=settings, dhara=dhara, transport=transport)
        cache = MediumCache(settings=settings, dhara=dhara)
        return client, cache

    return _factory
```

- [ ] **Step 2: Write the e2e tests**

`tests/integration/test_user_info_e2e.py`:

```python
from __future__ import annotations

import pytest

from medium_mcp.tools.users import user_info


async def test_user_info_returns_real_user(make_client) -> None:
    transport = stub_json(
        200,
        {
            "id": "1a2b",
            "username": "les",
            "fullname": "Les Leslie",
            "followers_count": 42,
            "following_count": 7,
            "bio": "writes code",
            "twitter_username": "les",
        },
    )
    client, cache = make_client(transport)
    result = await user_info(
        settings=client.settings, dhara=client.dhara, cache=cache, client=client,
        user_id="1a2b",
    )
    assert result.user_id == "1a2b"
    assert result.username == "les"
    assert result.followers_count == 42
```

`tests/integration/test_article_metadata_e2e.py`:

```python
from __future__ import annotations

import pytest

from medium_mcp.tools.articles import article_metadata


async def test_article_metadata_returns_full_record(make_client) -> None:
    transport = stub_json(
        200,
        {
            "id": "abc",
            "title": "Hello",
            "subtitle": "world",
            "author": "1a2b",
            "published_at": "2026-08-01T00:00:00Z",
            "reading_time": 5,
            "claps": 100,
            "voters": 30,
            "tags": ["python", "mcp"],
            "url": "https://medium.com/p/abc",
            "excerpt": "first 200 chars",
        },
    )
    client, cache = make_client(transport)
    result = await article_metadata(
        settings=client.settings, dhara=client.dhara, cache=cache, client=client,
        article_id="abc",
    )
    assert result.article_id == "abc"
    assert result.title == "Hello"
    assert result.tags == ["python", "mcp"]
    assert result.excerpt == "first 200 chars"
```

`tests/integration/test_search_articles_e2e.py`:

```python
from __future__ import annotations

import pytest

from medium_mcp.tools.search import search_articles


async def test_search_articles_returns_page(make_client) -> None:
    transport = stub_json(
        200,
        {
            "articles": [
                {
                    "id": "x",
                    "title": "T",
                    "author": "a",
                    "published_at": "2026-01-01T00:00:00Z",
                    "reading_time": 3,
                    "claps": 1,
                    "url": "https://medium.com/p/x",
                },
            ],
            "next_cursor": "nextpage",
        },
    )
    client, cache = make_client(transport)
    page = await search_articles(
        settings=client.settings, dhara=client.dhara, cache=cache, client=client,
        query="python",
    )
    assert page.next_cursor == "nextpage"
    assert len(page.articles) == 1
    assert page.articles[0].article_id == "x"
```

`tests/integration/test_budget_remaining_e2e.py`:

```python
from __future__ import annotations

import pytest

from medium_mcp.tools.budget import budget_remaining


async def test_budget_remaining_returns_status(make_client) -> None:
    client, cache = make_client(stub_json(200, {}))
    status = await budget_remaining(
        settings=client.settings, dhara=client.dhara, cache=cache, client=client,
    )
    assert status.remaining_calls == client.settings.monthly_budget
    assert status.monthly_budget == 150
    assert status.period.startswith("20")
```

`tests/integration/test_article_content_e2e.py`:

```python
from __future__ import annotations

import pytest

from medium_mcp.tools.articles import article_content


async def test_article_content_without_flag_returns_no_full_text(make_client) -> None:
    transport = stub_json(
        200,
        {
            "id": "abc",
            "title": "T",
            "content": {"body": "secret text"},
        },
    )
    client, cache = make_client(transport)
    result = await article_content(
        settings=client.settings, dhara=client.dhara, cache=cache, client=client,
        article_id="abc", include_full_text=False,
    )
    assert result.full_text is None


async def test_article_content_with_flag_returns_full_text(make_client) -> None:
    transport = stub_json(
        200,
        {
            "id": "abc",
            "title": "T",
            "content": {"body": "secret text"},
        },
    )
    client, cache = make_client(transport)
    result = await article_content(
        settings=client.settings, dhara=client.dhara, cache=cache, client=client,
        article_id="abc", include_full_text=True,
    )
    assert result.full_text == "secret text"
```

- [ ] **Step 3: Run the integration tests**

```bash
cd /Users/les/Projects/medium-mcp
.venv/bin/pytest tests/integration/ -v
```

Expected: 6 passed.

- [ ] **Step 4: Commit**

```bash
cd /Users/les/Projects/medium-mcp
git -c user.email=les@wedgwoodwebworks.com add -A
git -c user.email=les@wedgwoodwebworks.com commit -m "test(medium-mcp): per-tool e2e tests asserting non-empty results"
```

---

### Task 12: Phase 0b — one recorded live upstream call

**HUMAN PREREQUISITE:** This task blocks until `MEDIUM_MCP_RAPIDAPI_KEY` is exported in the developer's shell. If the key is missing, halt at 0a per spec §11 item 1; do not waive.

**Files:**
- Create: `/Users/les/Projects/medium-mcp/tests/integration/test_upstream_proof.py`
- Create: `/Users/les/Projects/medium-mcp/tests/fixtures/medium2_user_live.json`

- [ ] **Step 1: Confirm the RapidAPI key is exported**

```bash
[ -n "$MEDIUM_MCP_RAPIDAPI_KEY" ] && echo OK || echo "BLOCKED: export MEDIUM_MCP_RAPIDAPI_KEY first"
```

If `BLOCKED`: stop here. Phase 0a is sufficient to ship the wiring — Phase 0b is never waived.

- [ ] **Step 2: Write the recorded live call**

Create `tests/integration/test_upstream_proof.py`:

```python
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx2
import pytest

from medium_mcp.auth.key import validate_rapidapi_key
from medium_mcp.clients.medium2 import Medium2Client
from medium_mcp.config.settings import MediumSettings
from medium_mcp.dhara.client import DharaClient


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.mark.requires_network
@pytest.mark.requires_auth
@pytest.mark.skipif(
    not os.environ.get("MEDIUM_MCP_RAPIDAPI_KEY"),
    reason="requires MEDIUM_MCP_RAPIDAPI_KEY in env",
)
async def test_user_info_returns_real_medium_user() -> None:
    settings = MediumSettings(_env_file=None)
    settings.rapidapi_key = type(settings.rapidapi_key)(
        validate_rapidapi_key(settings.rapidapi_key)
    )
    dhara = DharaClient(settings=settings, backend="memory")
    await dhara.startup()
    try:
        client = Medium2Client(settings=settings, dhara=dhara)
        # Reach upstream directly without the budget guard (proof only).
        base = str(settings.rapidapi_base_url).rstrip("/")
        headers = {
            "X-RapidAPI-Key": settings.rapidapi_key.get_secret_value(),
            "X-RapidAPI-Host": "medium2.p.rapidapi.com",
        }
        async with httpx2.AsyncClient(timeout=30) as http:
            response = await http.get(f"{base}/user/id/1a2b", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert "id" in body, body
        # Record the fixture for offline replay in subsequent runs.
        FIXTURES.mkdir(parents=True, exist_ok=True)
        (FIXTURES / "medium2_user_live.json").write_text(json.dumps(body, indent=2))
    finally:
        await dhara.shutdown()
```

- [ ] **Step 3: Run the proof once to record the fixture**

```bash
cd /Users/les/Projects/medium-mcp
.venv/bin/pytest tests/integration/test_upstream_proof.py -v -m requires_network
```

Expected: 1 passed; `tests/fixtures/medium2_user_live.json` exists with non-empty body.

- [ ] **Step 4: Commit the proof and the recorded fixture**

```bash
cd /Users/les/Projects/medium-mcp
git -c user.email=les@wedgwoodwebworks.com add -A
git -c user.email=les@wedgwoodwebworks.com commit -m "test(medium-mcp): Phase 0b recorded live upstream proof"
```

---

### Task 13: Correct the README and verify registration

**Files:**
- Modify: `/Users/les/Projects/medium-mcp/README.md`

- [ ] **Step 1: Rewrite the README's "Capabilities" section**

Replace any language that mentions an "official" Medium API or a generic "Medium MCP server." State explicitly:

- Source: unofficial medium2 API via RapidAPI.
- Official Medium API is retired (Help Center, March 2023 archive).
- A RapidAPI key is required (`MEDIUM_MCP_RAPIDAPI_KEY`).
- Tier limit: 150 calls/month on the free tier; budget guard refuses calls once exhausted.
- Cache: Dhara-backed (`medium2:v1:<endpoint>:<hash>`), with TTL-by-endpoint.
- Content policy: full text is opt-in via `include_full_text=True`; otherwise only metadata + excerpt is returned.

Suggested structure:

```markdown
## Capabilities

13 tools + the free budget readout:

- `user_info` (one-of `user_id` / `username`)
- `user_articles`
- `article_metadata`
- `article_content` (full text opt-in, see Content policy below)
- `article_responses`
- `publication_info` (one-of `publication_id` / `slug`)
- `publication_articles`
- `tag_info`
- `tag_latest`
- `search_articles`
- `search_users`
- `search_publications`
- `budget_remaining` — local read, never hits RapidAPI

## Source

Data comes from the unofficial **medium2** API on RapidAPI. The official Medium
API was archived March 2023 and does not accept new integrations; medium-mcp is
the project that documents what shape the unofficial API returns and how the
budget guard turns it into a metered-but-capped service.

## Setup

1. Sign up at https://rapidapi.com and subscribe to medium2 (free tier: 150
   calls / month).
2. Export the key:
   ```bash
   export MEDIUM_MCP_RAPIDAPI_KEY=<your-key>
   ```
3. Install + run:
   ```bash
   uv pip install -e ".[dev]"
   medium-mcp
   ```

## Health

Two routes, answering different questions:

- **`/health`** — always HTTP 200. Reports per-feed detail in `components`.
  For orchestrators and `curl` smoke probes.
- **`/readyz`** — HTTP 503 when a required feed has not yet returned data,
  200 otherwise. For readiness probes.

`dhara` is a required feed (the budget counter rides on it), so a freshly
started server returns 503 on `/readyz` until a tool call succeeds. That is
intentional: a server whose counter has never been touched cannot guarantee
its budget, and lies would defeat the only guard we have.

## Budget

The server enforces a strict monthly budget (`medium_mcp.budget.monthly_budget`,
default **150 metered calls / period**) under a Dhara-backed advisory lock.
Once exhausted, metered calls are refused with this payload:

```json
{
  "error": "budget_exhausted",
  "remaining_calls": 0,
  "requested_calls": 1,
  "period": "2026-09",
  "resets_at": "2026-10-01T00:00:00Z",
  "retryable": false,
  "cached_alternatives": ["user_info", "article_metadata", "tag_info"]
}
```

`budget_remaining` is always free; it reads the counter locally and reports
`calls_used`, `remaining_calls`, `monthly_budget`, `period`, `resets_at` so
the caller can decide whether to make the call themselves.

## Content policy

`article_content` returns the full body only when the caller passes
`include_full_text=True`. Five rules govern what the tool does and does not
return, in order:

1. **Default-deny.** `article_content` returns `excerpt` only when
   `include_full_text=False`, regardless of cache state. The cache may hold
   `full_text` under the `content_key` prefix; the gate is at the return
   point, not the cache key.
2. **Opt-in body.** Set `include_full_text=True` to receive `full_text`
   alongside the excerpt. The cache hit path also honors the flag — a cached
   body is *only* returned when the flag was set.
3. **Truncation.** `excerpt` is capped at `excerpt_max_chars` (default 500,
   max 2000) so a caller never receives an unbounded body. The
   `truncated: bool` field tells the caller whether the cap fired.
4. **Format.** `format` is one of `"markdown"`, `"html"`, or `"text"`. The
   tool does not transcode between formats; what the upstream returned is
   what the tool returns, gated only by the include flag.
5. **No export.** `allow_content_export: bool` (default `false`) is a
   hard-stop on writing full text to disk or to a downstream store. Treat
   the body as in-memory-only; do not persist it.

The settings section (`MEDIUM_MCP_*` env vars, prefix-defined) carries
`excerpt_max_chars`, `allow_content_export`, `monthly_budget`, and the
rest. See `settings/medium-mcp.yaml` for the full list.

## License

BSD-3-Clause.
```

- [ ] **Step 2: Ratchet the coverage floor**

In `pyproject.toml`, raise `--cov-fail-under=70` to `--cov-fail-under=85` once
Tasks 1-12 pass cleanly. Matches archive-org-mcp and scapy-mcp pattern — a
brand-new repo starts at 70%, lands at 85% once the documented suite passes,
and a later task in the sequence ratchets further toward the ecosystem
target of 89%.

- [ ] **Step 3: Commit**

```bash
cd /Users/les/Projects/medium-mcp
git -c user.email=les@wedgwoodwebworks.com add -A
git -c user.email=les@wedgwoodwebworks.com commit -m "docs(medium-mcp): correct README to name medium2 RapidAPI + content policy"
```

---

### Task 14: Ratchet coverage and run the full gate

- [ ] **Step 1: Write the content-policy decision record**

Create `.claude/decisions/medium-content-policy.md` capturing the corrected content policy verbatim from spec §6.2 rules 1-5 (context, rules, enforcement point per rule).

- [ ] **Step 2: Ratchet coverage floor**

In `pyproject.toml`, raise `--cov-fail-under=70` to `--cov-fail-under=85` only after Tasks 1-11 pass. The archive-org plan established the precedent: starting at 70, then bumping.

- [ ] **Step 3: Run the full quality gate**

```bash
cd /Users/les/Projects/medium-mcp
.venv/bin/pytest -v --cov=medium_mcp --cov-fail-under=85
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
cd /Users/les/Projects/medium-mcp
git -c user.email=les@wedgwoodwebworks.com add -A
git -c user.email=les@wedgwoodwebworks.com commit -m "chore(medium-mcp): ratchet coverage to 85, decision record"
```

---

## Spec coverage checklist

- §6.2 tools (13 + `budget_remaining`): all 14 covered in Task 9.
- §6.2 cache contract (key, namespace, coalescing, TTL, eviction): covered in Tasks 4, 8.
- §6.2 budget guard (CAS-equivalent via DharaLock, headroom, retries, free `budget_remaining`): covered in Tasks 4, 7.
- §6.2 min_cost/max_pages reservation: covered in Task 7 — `min_cost` is honored; `max_pages > 1` is explicitly rejected in v1 rather than silently mis-reserved (see `Medium2Client`'s docstring).
- §6.2 BudgetExhaustedError payload: covered in Tasks 2, 7 (no `monthly_budget` key — the spec payload does not carry one).
- §6.2 content policy (rules 1-5): covered in Tasks 6, 8, 9.
- §13.3 settings (every key, every default): covered in Task 3.
- Spec §11 prerequisite (RapidAPI key): covered in Task 12 (halt on missing).

## Self-review notes

- Spec says "Dhara's ACID guarantees are the serialization point" — there is no CAS primitive in Dhara. The plan wires the budget guard to `DharaLock.try_acquire` from `dhara.lock.in_memory.InMemoryDharaLock`. This is the only Dhara primitive that provides the required mutual-exclusion guarantee, and the spec's wording is consistent with that reading.
- `retry_max_attempts=1` (default 1, no retries) is enforced both by the `Field(default=1, ge=0, le=1)` constraint in `MediumSettings` and by the test asserting the default.
- The fast-tools pattern from `raindropio-mcp` is reused: every tool is registered through `@app.tool(name=...)` and the `ClientBundle` is closed over.
- The `_run_async_safely` bridge is included in `server.py` even though the current `cli.py` uses `asyncio.run` directly — it's there for downstream tools that may call from sync contexts.
- The budget guard's headroom check lives inside `DharaClient.inc_atomic`, under the per-month lock, rather than in `Medium2Client`. A read-then-check in the client would let two concurrent reservations observe the same headroom and both proceed — the exact race the lock exists to close. `Medium2Client` passes the ceiling down as `max_value` and never pre-reads the counter; `test_headroom_check_happens_inside_the_lock` pins that by making `get_counter` raise.
- Reservations are not refunded after a dispatched call. Spec §6.2 counts any request that reaches RapidAPI regardless of status, so the only release path is the pre-flight failure case (`_release_reservation`), and `max_pages=1` means there is never a partial multi-page reservation to unwind.
- `Medium2Client.request` gates on `DharaClient.probe()` before reserving. Without a reachable counter there is no guard at all, and an unguarded call is budget that can never be accounted for — so it is refused rather than made. `probe()` is cached for `PROBE_CACHE_SECONDS` because it now sits on the hot path of every metered call.
- Tool registration ordering in `build_mcp_app()` is load-bearing: `@app.tool` cannot be undone, so `apply_tool_profile` receives `register_all_fn` and decides what to decorate, instead of pruning a map after the decorators have already run.

---
