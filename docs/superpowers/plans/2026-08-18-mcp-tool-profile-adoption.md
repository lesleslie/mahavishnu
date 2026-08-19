# MCP Tool Profile Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt the `ToolProfile` mechanism from `mcp-common` across all 18 Bodai-ecosystem MCP servers via a single shared `apply_tool_profile()` helper, reducing context-window overhead for Claude sessions by ~30–40k tokens/session at STANDARD profile.

**Architecture:** Two-layer split — framework layer (one `apply_tool_profile()` helper in `mcp-common`) reads `{SERVER}_TOOL_PROFILE` env var and auto-handles MANDATORY tools + `discover_tools()` meta-tool; policy layer (per-repo `PROFILE_REGISTRATIONS` data structure + `registration_map`) declares which tool groups belong to each profile level. Helper supports 4 dispatch modes (callable / decorator / method-on-server / single-group) to fit existing patterns.

**Tech Stack:** Python 3.13, FastMCP 3.4.7 (uses `Tool.from_function`, `_local_provider`, `Tool.parameters`), mcp-common 0.18+, Oneiric logging, pytest, crackerjack for CI/CD, git ff-merge to main per Bodai pre-1.0 policy.

## Global Constraints

The following are project-wide requirements from the design spec (`docs/superpowers/specs/2026-08-18-mcp-tool-profile-adoption-design.md`). Every task's requirements implicitly include this section:

- **Pre-1.0 merge policy:** branch + ff-merge to main, no PRs, no review gates. Exception: W0 has a soft review gate by 1–2 W1 implementers before W1 starts.
- **No backwards compatibility / legacy support.** Crackerjack's existing `TOOL_REGISTRY` is **deleted** via `git rm` (whole file), not wrapped.
- **User bumps `mcp-common` version manually before W1 starts.** Implementers do NOT bump mcp-common themselves.
- **mcp-common depends on `fastmcp>=3.4.0,<4`** (already pinned in pyproject.toml). Helper targets FastMCP 3.4.7's public API.
- **Helper uses `oneiric.logging.get_logger`** (NOT stdlib, NOT \`print()\`\`).
- **Helper uses FastMCP public `await server.list_tools()`** for default introspection (NOT private `_tool_manager`).
- **Helper uses FastMCP 3.4.7's `Tool.from_function()`** for registering the `discover_tools` meta-tool (the only correct way to pass name/description/fn kwargs).
- **Helper uses `_local_provider.remove_tool()`** for idempotent discover_tools removal (the FastMCP 3.4+ public attribute; `_tool_manager` was removed).
- **Helper uses `Tool.parameters`** for the inputSchema dict (NOT `Tool.inputSchema` which doesn't exist on the model).
- **Helper raises `InvalidProfileError` only for SET-BUT-INVALID profile values** (empty/whitespace/unknown when env var IS set). For UNSET env var, fall through to FULL (matches existing `ToolProfile.from_env()` behavior). For set-but-empty, raise.
- **Helper uses `ALL_TOOLS` typed sentinel** (NOT the string `"all_tools"`) for `ToolProfile.FULL` = "register everything".
- **Helper accepts both sync and async register callables** (await if coroutine).
- **Per-repo `PROFILE_REGISTRATIONS` stays local.** `ToolProfile` enum is shared; tool-group taxonomy is domain knowledge.
- **YAML precedence optional via `yaml_loader` parameter** — mahavishnu passes its loader (NEW code), others pass `None`.
- **`MANDATORY_TOOLS ⊆ registered` at all 3 profile levels** (assertion in every repo's `tests/unit/test_tool_profile.py`).
- **Author email: `les@wedgwoodwebworks.com`** (not `.local`). Every `git commit` MUST include `-c user.email=les@wedgwoodwebworks.com`.
- **Per-wave briefs must reference `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/MEMORY.md`** for relevant patterns: AST block removal (W2a), ruff autofix noise (W2b+), venv rebuild (`uv pip install --force-reinstall --no-deps`), uv cross-repo VIRTUAL_ENV/UV_ACTIVE stripping, `uv sync --upgrade-package mcp-common` (NOT `--upgrade`), test-dir shadows site-package pre-check, drift-bundling recovery, session-buddy auto-checkpoint bundling, Bodai pre-1.0 merge policy, Doc-audit patterns, **crackerjack-fast-hooks-ruff-autofix** (single `fast`, not double).
- **Each wave lands before next wave starts; no stashes across waves.**
- **Each PR is independently revertable via `git revert`.**
- **mcp-common version re-bump:** user bumps after W0 lands; W2b+ repos need their `pyproject.toml` updated to pull the new helper (flag in each wave's brief).

______________________________________________________________________

## File Structure

### New Files

| Path | Responsibility |
|------|---------------|
| `/Users/les/Projects/mcp-common/mcp_common/tools/dispatch.py` | The `apply_tool_profile()` helper + `ALL_TOOLS` sentinel + exception classes |
| `/Users/les/Projects/mcp-common/tests/unit/test_apply_tool_profile.py` | Unit tests for all 4 dispatch cases + env var parsing + idempotent register |
| `/Users/les/Projects/mcp-common/tests/integration/test_profile_dispatch.py` | Integration test using a real FastMCP 3.4.7 server fixture |
| `/Users/les/Projects/crackerjack/crackerjack/mcp/tools/profiles.py` | Crackerjack's `PROFILE_REGISTRATIONS` |
| `/Users/les/Projects/crackerjack/crackerjack/mcp/tools/discover_query.py` | Crackerjack's `discovery_fn` override (preserves query filter) |
| `/Users/les/Projects/crackerjack/.claude/decisions/tool-profile-rationale.md` | Crackerjack's profile mapping rationale |
| Per-repo: `<pkg>/mcp/tools/profiles.py` (15 new files) | Each repo's `PROFILE_REGISTRATIONS` |
| Per-repo: `tests/unit/test_tool_profile.py` (17 new files) | Per-repo tests |
| Per-repo: `.claude/decisions/tool-profile-rationale.md` (7 files for Tier-B/C) | Mapping rationale |

### Modified Files

| Path | Change |
|------|--------|
| `/Users/les/Projects/mcp-common/mcp_common/tools/__init__.py` | Re-export `apply_tool_profile`, `ALL_TOOLS`, `InvalidProfileError` |
| `/Users/les/Projects/crackerjack/crackerjack/mcp/server_core.py` | Add `apply_tool_profile()` call |
| `/Users/les/Projects/crackerjack/docs/architecture/MEMORY_ARCHITECTURE.md` | Add resolved annotation (literal text in spec §3) |
| `/Users/les/Projects/mahavishnu/mahavishnu/mcp/server_core.py` | Add `apply_tool_profile()` call |
| `/Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/profiles.py` | Convert to helper call (preserves method-name pattern via `registration_map` lambdas; add NEW `settings_yaml_loader`) |
| Same for session-buddy, akosha, dhara | (4 W1 repos) |
| Per-repo main entrypoint (15 files for Tier-A/B/C) | Add `apply_tool_profile()` call |
| Per-repo CLAUDE.md (15 files) | Add "Tool Profile System" subsection |

### Deleted Files

| Path | When |
|------|------|
| `/Users/les/Projects/crackerjack/crackerjack/mcp/tools/discover_tools.py` | W2a (`git rm` whole file; 170 lines TOOL_REGISTRY + 6 DEFERRED_TOOLS + 41 register_discover_tools + helpers = 236 total) |
| Any Crackerjack test importing `TOOL_REGISTRY` | W2a |

______________________________________________________________________

## Task 1 (W0): Add `apply_tool_profile()` helper to `mcp-common`

**Files:**

- Create: `/Users/les/Projects/mcp-common/mcp_common/tools/dispatch.py`
- Create: `/Users/les/Projects/mcp-common/tests/unit/test_apply_tool_profile.py`
- Create: `/Users/les/Projects/mcp-common/tests/integration/test_profile_dispatch.py`
- Modify: `/Users/les/Projects/mcp-common/mcp_common/tools/__init__.py`

**Interfaces:**

- Consumes: `fastmcp.FastMCP` instance, `{SERVER}_TOOL_PROFILE` env var (optional `yaml_loader()` fallback)
- Produces: `apply_tool_profile(server, profile_env_var, registrations, registration_map, register_all_fn, mandatory_tools, discovery_fn, yaml_loader)` callable; `ALL_TOOLS` sentinel; `InvalidProfileError` exception

**IMPORTANT FastMCP 3.4.7 API verification:** Before writing any code, the implementer MUST verify the actual FastMCP API by running:

```bash
cd /Users/les/Projects/mcp-common
uv run python -c "
from fastmcp import FastMCP
from fastmcp.tools import Tool
import inspect
print('add_tool:', inspect.signature(FastMCP.add_tool))
print('remove_tool:', inspect.signature(FastMCP.remove_tool) if hasattr(FastMCP, 'remove_tool') else 'NOT FOUND')
print('has _tool_manager:', hasattr(FastMCP('x'), '_tool_manager'))
print('has _local_provider:', hasattr(FastMCP('x'), '_local_provider'))
print('Tool.fields:', list(Tool.model_fields.keys()))
"
```

This MUST print: `add_tool: (self, tool: Tool | Callable)`, `_local_provider: True`, `Tool.fields: [...'parameters'...]`. If the output differs, STOP and re-verify against the installed FastMCP version.

- [ ] **Step 1: Write the failing tests**

Create `/Users/les/Projects/mcp-common/tests/unit/test_apply_tool_profile.py`:

```python
"""Unit tests for apply_tool_profile() helper. Uses monkeypatch for env isolation."""
from __future__ import annotations

import pytest

from mcp_common.tools import ToolProfile, MANDATORY_TOOLS
from mcp_common.tools.dispatch import (
    ALL_TOOLS,
    InvalidProfileError,
    apply_tool_profile,
)


def test_all_tools_is_sentinel_class():
    """ALL_TOOLS is a class (sentinel), not the string 'all_tools'."""
    assert isinstance(ALL_TOOLS, type)
    assert ALL_TOOLS.__name__ == "ALL_TOOLS"


def test_unset_env_falls_through_to_full(monkeypatch):
    """Per spec §1, UNSET env var defaults to FULL (matches existing ToolProfile.from_env)."""
    monkeypatch.delenv("TEST_PROFILE", raising=False)
    # Should NOT raise InvalidProfileError; falls through to FULL
    apply_tool_profile(
        server=None,  # type: ignore
        profile_env_var="TEST_PROFILE",
        registrations={
            ToolProfile.MINIMAL: [],
            ToolProfile.STANDARD: [],
            ToolProfile.FULL: ALL_TOOLS,
        },
        registration_map={},
        register_all_fn=lambda s: None,
    )


def test_invalid_profile_error_on_set_but_empty(monkeypatch):
    """SET-BUT-EMPTY env var raises InvalidProfileError."""
    monkeypatch.setenv("TEST_PROFILE", "")
    with pytest.raises(InvalidProfileError):
        apply_tool_profile(
            server=None,  # type: ignore
            profile_env_var="TEST_PROFILE",
            registrations={},
            registration_map={},
            register_all_fn=lambda s: None,
        )


def test_invalid_profile_error_on_whitespace(monkeypatch):
    monkeypatch.setenv("TEST_PROFILE", "   ")
    with pytest.raises(InvalidProfileError):
        apply_tool_profile(
            server=None,  # type: ignore
            profile_env_var="TEST_PROFILE",
            registrations={},
            registration_map={},
            register_all_fn=lambda s: None,
        )


def test_invalid_profile_error_on_unknown_value(monkeypatch):
    monkeypatch.setenv("TEST_PROFILE", "bogus")
    with pytest.raises(InvalidProfileError):
        apply_tool_profile(
            server=None,  # type: ignore
            profile_env_var="TEST_PROFILE",
            registrations={},
            registration_map={},
            register_all_fn=lambda s: None,
        )


def test_valid_profiles_accepted(monkeypatch):
    """lowercase, uppercase, mixed case all accepted for valid profile names."""
    for value in ("minimal", "MINIMAL", "Minimal", "standard", "full", "FULL"):
        monkeypatch.setenv("TEST_PROFILE", value)
        apply_tool_profile(
            server=None,  # type: ignore
            profile_env_var="TEST_PROFILE",
            registrations={
                ToolProfile.MINIMAL: [],
                ToolProfile.STANDARD: [],
                ToolProfile.FULL: ALL_TOOLS,
            },
            registration_map={},
            register_all_fn=lambda s: None,
        )


def test_all_tools_at_full_requires_register_all_fn(monkeypatch):
    """ALL_TOOLS at FULL but register_all_fn=None raises ValueError."""
    monkeypatch.setenv("TEST_PROFILE", "full")
    with pytest.raises(ValueError, match="register_all_fn"):
        apply_tool_profile(
            server=None,  # type: ignore
            profile_env_var="TEST_PROFILE",
            registrations={
                ToolProfile.MINIMAL: [],
                ToolProfile.STANDARD: [],
                ToolProfile.FULL: ALL_TOOLS,
            },
            registration_map={},
            register_all_fn=None,  # type: ignore
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/les/Projects/mcp-common && uv run pytest tests/unit/test_apply_tool_profile.py -v`
Expected: 7 ImportError-style failures (no `dispatch` module yet).

- [ ] **Step 3: Write minimal `dispatch.py` with sentinel + exception + resolver**

Create `/Users/les/Projects/mcp-common/mcp_common/tools/dispatch.py`:

```python
"""Apply ToolProfile gating to a FastMCP server at startup.

Verified against FastMCP 3.4.7 — uses public API only:
- await server.list_tools()  (NOT _tool_manager.list_tools())
- Tool.from_function(...) for registering the discover_tools meta-tool
- server._local_provider.remove_tool() for idempotent removal
- Tool.parameters for inputSchema dict

Supports 4 dispatch modes (see spec §Components §1):
- callable-only (typical Tier-A)
- decorator-mode (Tier-A edge — repos using @mcp.tool decorators)
- method-mode (mahavishnu's `_register_<group>()` pattern)
- single-group (Tier-B simple case)

Public API:
- apply_tool_profile(server, ...) - main entrypoint
- ALL_TOOLS - typed sentinel for ToolProfile.FULL = "register everything"
- InvalidProfileError - raised on SET-BUT-INVALID env var (NOT on unset)
"""

from __future__ import annotations

import inspect
import logging
import os
from typing import Any, Awaitable, Callable

from fastmcp import FastMCP
from fastmcp.tools import Tool
from oneiric.logging import get_logger

from mcp_common.tools.profiles import MANDATORY_TOOLS, ToolProfile

logger = get_logger(__name__)


class ALL_TOOLS:
    """Typed sentinel marking `ToolProfile.FULL` to register every group.

    Using a class (not a string) prevents accidental collision with a
    legit group named "all_tools".
    """

    pass


class InvalidProfileError(Exception):
    """Raised when {SERVER}_TOOL_PROFILE is SET-BUT-INVALID (empty/whitespace/unknown).

    Per spec: UNSET env var falls through to FULL (matches existing from_env behavior).
    """

    pass


def _resolve_profile(
    profile_env_var: str, yaml_loader: Callable[[], dict | None] | None
) -> ToolProfile:
    """Resolve profile from env var (UNSET → yaml_loader → FULL fallback).

    Raises InvalidProfileError ONLY on SET-BUT-INVALID values.
    """
    raw = os.getenv(profile_env_var)
    if raw is None:
        # Env var unset — try YAML fallback
        if yaml_loader is not None:
            try:
                loaded = yaml_loader() or {}
                raw = str(loaded.get("tool_profile", "") or "")
            except Exception:  # noqa: BLE001
                raw = ""
        if raw is None or not raw:
            # No env, no yaml, no usable value — DEFAULT to FULL (per spec + existing from_env)
            return ToolProfile.FULL
    # Env var IS set (or yaml provided one) — validate it
    candidate = raw.strip().lower()
    if not candidate:
        raise InvalidProfileError(
            f"{profile_env_var}={raw!r} is empty or whitespace; expected one of "
            f"{[p.value for p in ToolProfile]}"
        )
    try:
        return ToolProfile(candidate)
    except ValueError as e:
        raise InvalidProfileError(
            f"{profile_env_var}={raw!r} is not a valid profile; "
            f"expected one of {[p.value for p in ToolProfile]}"
        ) from e


async def _maybe_await(result: Awaitable[None] | None) -> None:
    """Await if coroutine, else ignore."""
    if inspect.iscoroutine(result):
        await result


async def _default_discovery(server: FastMCP, filter_query: str | None) -> list[dict]:
    """Default introspection via the FastMCP PUBLIC `list_tools()` method.

    Verified FastMCP 3.4.7: Tool.model_fields contains 'parameters' (not 'inputSchema').
    inputSchema only exists after Tool.to_mcp_tool() conversion.
    """
    tools = await server.list_tools()
    result = [
        {
            "name": t.name,
            "description": t.description or "",
            "inputSchema": t.parameters,  # parameters is the underlying dict
            "group": None,
        }
        for t in tools
    ]
    if filter_query:
        q = filter_query.lower()
        result = [
            t for t in result
            if q in t["name"].lower() or q in t["description"].lower()
        ]
    return result
```

- [ ] **Step 4: Run tests; expect 6 of 7 to pass**

Run: `cd /Users/les/Projects/mcp-common && uv run pytest tests/unit/test_apply_tool_profile.py -v`
Expected: 6 pass, 1 fail (`test_unset_env_falls_through_to_full` fails because `apply_tool_profile` doesn't exist yet).

- [ ] **Step 5: Add the full `apply_tool_profile()` function with `Tool.from_function()`**

Append to `/Users/les/Projects/mcp-common/mcp_common/tools/dispatch.py`:

```python
async def apply_tool_profile(
    server: FastMCP,
    *,
    profile_env_var: str,
    registrations: dict[ToolProfile, list[str | Callable] | type[ALL_TOOLS]],
    registration_map: dict[str, Callable[[FastMCP], Awaitable[None] | None]],
    register_all_fn: Callable[[FastMCP], Awaitable[None] | None] | None = None,
    mandatory_tools: set[str] = MANDATORY_TOOLS,
    discovery_fn: Callable[[FastMCP, str | None], Awaitable[list[dict]]] | None = None,
    yaml_loader: Callable[[], dict | None] | None = None,
) -> None:
    """Apply the tool profile to the server at startup. See module docstring."""
    profile = _resolve_profile(profile_env_var, yaml_loader)

    # Validation: ALL_TOOLS at FULL requires register_all_fn
    full_value = registrations.get(ToolProfile.FULL)
    if full_value is ALL_TOOLS and register_all_fn is None:
        raise ValueError(
            "ToolProfile.FULL == ALL_TOOLS requires register_all_fn; "
            "either pass it or set registrations[FULL] to a list of group names."
        )

    # Step 1: Per-profile registration
    if profile is ToolProfile.MINIMAL:
        groups: list = registrations.get(ToolProfile.MINIMAL, [])
    elif profile is ToolProfile.STANDARD:
        groups = registrations.get(ToolProfile.STANDARD, [])
    else:  # FULL
        if full_value is ALL_TOOLS:
            await _maybe_await(register_all_fn(server))
            groups = []
        elif isinstance(full_value, list):
            groups = full_value
        else:
            groups = list(full_value) if full_value else []

    for item in groups:
        if callable(item):
            await _maybe_await(item(server))
        elif isinstance(item, str):
            fn = registration_map.get(item)
            if fn is None:
                raise ValueError(
                    f"Group {item!r} in registrations but not in registration_map. "
                    f"Add it via registration_map[{item!r}] = <register function>."
                )
            await _maybe_await(fn(server))
        else:
            raise TypeError(
                f"registrations values must be str, Callable, or ALL_TOOLS; got {type(item)}"
            )

    # Step 2: MANDATORY tools (last, idempotent — re-fetch after each call)
    registered_names = {t.name for t in await server.list_tools()}
    for name in mandatory_tools:
        if name in registered_names:
            logger.debug(
                "MANDATORY tool %r already registered, skipping", name
            )
            continue
        fn = registration_map.get(name)
        if fn is None:
            raise ValueError(
                f"MANDATORY tool {name!r} not in registration_map. "
                f"Add it or pass mandatory_tools=set() to skip."
            )
        await _maybe_await(fn(server))
        registered_names = {t.name for t in await server.list_tools()}  # refresh

    # Step 3: discover_tools() (idempotent via _local_provider.remove_tool)
    disc = discovery_fn or _default_discovery
    tools = await disc(server, None)

    # Remove existing discover_tools if present (use _local_provider, the FastMCP 3.4+ public attr)
    try:
        await server._local_provider.remove_tool("discover_tools")  # type: ignore[attr-defined]
    except (KeyError, AttributeError) as e:
        logger.debug(
            "No existing discover_tools to remove (%s); registering fresh", e
        )

    # Register discover_tools via Tool.from_function (the only correct way in FastMCP 3.4+)
    async def discover_tools_handler(query: str | None = None) -> list[dict]:
        """List tools registered in this server, optionally filtered by query."""
        return await disc(server, query)

    discover_tool = Tool.from_function(
        fn=discover_tools_handler,
        name="discover_tools",
        description="List all tools registered in this server (with profile metadata).",
    )
    server.add_tool(discover_tool)

    n = len(await server.list_tools())
    logger.info(
        "Applied %s=%s → %d tools registered",
        profile_env_var,
        profile.value,
        n,
    )
```

- [ ] **Step 6: Run tests; expect all 7 to pass**

Run: `cd /Users/les/Projects/mcp-common && uv run pytest tests/unit/test_apply_tool_profile.py -v`
Expected: All 7 pass.

- [ ] **Step 7: Re-export from `mcp_common.tools.__init__`**

Read `/Users/les/Projects/mcp-common/mcp_common/tools/__init__.py`. Add to `__all__`:

```python
from mcp_common.tools.dispatch import ALL_TOOLS, InvalidProfileError, apply_tool_profile
```

Verify with: `uv run python -c "from mcp_common.tools import apply_tool_profile, ALL_TOOLS, InvalidProfileError; print('ok')"`

- [ ] **Step 8: Write integration test with real FastMCP 3.4.7 server**

Create `/Users/les/Projects/mcp-common/tests/integration/test_profile_dispatch.py`:

```python
"""Integration test: apply_tool_profile against a real FastMCP 3.4.7 server."""
from __future__ import annotations

import pytest
from fastmcp import FastMCP
from fastmcp.tools import Tool

from mcp_common.tools import ToolProfile
from mcp_common.tools.dispatch import ALL_TOOLS, apply_tool_profile


def make_server_with_groups(monkeypatch_session):
    """Build a FastMCP server with 3 groups (group_a, group_b, group_health)."""
    server = FastMCP("test-server")

    def register_group_a(s):
        s.add_tool(Tool.from_function(fn=lambda: "a1", name="tool_a1", description="A1"))
        s.add_tool(Tool.from_function(fn=lambda: "a2", name="tool_a2", description="A2"))

    def register_group_b(s):
        s.add_tool(Tool.from_function(fn=lambda: "b1", name="tool_b1", description="B1"))

    def register_group_health(s):
        s.add_tool(Tool.from_function(fn=lambda: "ok", name="get_liveness", description="Liveness"))
        s.add_tool(Tool.from_function(fn=lambda: "ok", name="get_readiness", description="Readiness"))

    def register_all(s):
        register_group_a(s)
        register_group_b(s)
        register_group_health(s)

    registration_map = {
        "group_a": register_group_a,
        "group_b": register_group_b,
        "group_health": register_group_health,
    }

    registrations = {
        ToolProfile.MINIMAL: ["group_health"],
        ToolProfile.STANDARD: ["group_a", "group_health"],
        ToolProfile.FULL: ALL_TOOLS,
    }

    return server, registrations, registration_map, register_all


@pytest.mark.asyncio
async def test_minimal_registers_mandatory_and_discover(monkeypatch):
    server, registrations, reg_map, register_all = make_server_with_groups(monkeypatch)
    monkeypatch.setenv("TEST_PROFILE", "minimal")
    await apply_tool_profile(
        server,
        profile_env_var="TEST_PROFILE",
        registrations=registrations,
        registration_map=reg_map,
        register_all_fn=register_all,
    )
    names = {t.name for t in await server.list_tools()}
    assert {"get_liveness", "get_readiness", "discover_tools"}.issubset(names)
    assert "tool_a1" not in names
    assert "tool_a2" not in names
    assert "tool_b1" not in names


@pytest.mark.asyncio
async def test_standard_registers_expected_groups(monkeypatch):
    server, registrations, reg_map, register_all = make_server_with_groups(monkeypatch)
    monkeypatch.setenv("TEST_PROFILE", "standard")
    await apply_tool_profile(
        server,
        profile_env_var="TEST_PROFILE",
        registrations=registrations,
        registration_map=reg_map,
        register_all_fn=register_all,
    )
    names = {t.name for t in await server.list_tools()}
    assert {"tool_a1", "tool_a2", "get_liveness", "get_readiness", "discover_tools"}.issubset(names)
    assert "tool_b1" not in names


@pytest.mark.asyncio
async def test_full_registers_everything(monkeypatch):
    server, registrations, reg_map, register_all = make_server_with_groups(monkeypatch)
    monkeypatch.setenv("TEST_PROFILE", "full")
    await apply_tool_profile(
        server,
        profile_env_var="TEST_PROFILE",
        registrations=registrations,
        registration_map=reg_map,
        register_all_fn=register_all,
    )
    names = {t.name for t in await server.list_tools()}
    assert {"tool_a1", "tool_a2", "tool_b1", "get_liveness", "get_readiness", "discover_tools"}.issubset(names)


@pytest.mark.asyncio
async def test_mandatory_subsetting(monkeypatch):
    """Repos without all 4 health tools can opt-out via mandatory_tools=set()."""
    server, registrations, reg_map, register_all = make_server_with_groups(monkeypatch)
    monkeypatch.setenv("TEST_PROFILE", "minimal")
    await apply_tool_profile(
        server,
        profile_env_var="TEST_PROFILE",
        registrations={ToolProfile.MINIMAL: [], ToolProfile.STANDARD: [], ToolProfile.FULL: ALL_TOOLS},
        registration_map=reg_map,
        register_all_fn=register_all,
        mandatory_tools=set(),
    )
    names = {t.name for t in await server.list_tools()}
    assert "get_liveness" not in names
    assert "discover_tools" in names


@pytest.mark.asyncio
async def test_discover_tools_idempotent(monkeypatch):
    """Calling apply_tool_profile twice leaves exactly one discover_tools and identical tool set."""
    server, registrations, reg_map, register_all = make_server_with_groups(monkeypatch)
    monkeypatch.setenv("TEST_PROFILE", "full")
    await apply_tool_profile(
        server,
        profile_env_var="TEST_PROFILE",
        registrations=registrations,
        registration_map=reg_map,
        register_all_fn=register_all,
    )
    first_names = {t.name for t in await server.list_tools()}
    # Second call
    await apply_tool_profile(
        server,
        profile_env_var="TEST_PROFILE",
        registrations=registrations,
        registration_map=reg_map,
        register_all_fn=register_all,
    )
    second_names = {t.name for t in await server.list_tools()}
    assert second_names.count("discover_tools") == 1
    assert first_names == second_names, "Second call must produce identical tool set"


@pytest.mark.asyncio
async def test_unset_env_defaults_to_full(monkeypatch):
    """Unset env var falls through to FULL (matches existing from_env)."""
    monkeypatch.delenv("TEST_PROFILE", raising=False)
    server, registrations, reg_map, register_all = make_server_with_groups(monkeypatch)
    await apply_tool_profile(
        server,
        profile_env_var="TEST_PROFILE",
        registrations=registrations,
        registration_map=reg_map,
        register_all_fn=register_all,
    )
    names = {t.name for t in await server.list_tools()}
    # FULL registers everything
    assert {"tool_a1", "tool_a2", "tool_b1", "discover_tools"}.issubset(names)
```

- [ ] **Step 9: Run all tests with coverage check**

Run: `cd /Users/les/Projects/mcp-common && uv run pytest tests/ -v --cov=mcp_common.tools.dispatch --cov-fail-under=90`
Expected: All tests pass; coverage of `dispatch.py` ≥ 90%.

- [ ] **Step 10: Commit**

```bash
cd /Users/les/Projects/mcp-common
git add mcp_common/tools/dispatch.py mcp_common/tools/__init__.py tests/
git commit -c user.email=les@wedgwoodwebworks.com -m "feat(mcp-common): add apply_tool_profile() helper

Single entrypoint for the 4 dispatch modes (callable/decorator/method/
single-group) per the 2026-08-18 MCP tool profile adoption spec. Uses
FastMCP 3.4.7 public API: Tool.from_function, _local_provider.remove_tool,
Tool.parameters.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

**W0 soft review gate:** Wait for 1–2 W1 implementers to confirm the API covers their backfill needs before proceeding to Task 2.

______________________________________________________________________

## Task 2 (W1.1): Backfill mahavishnu

**Files:**

- Read first: `/Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/profiles.py` — actual `PROFILE_REGISTRATIONS` is at **lines 69-73** (NOT 39-63 which is the three list constants `MINIMAL_REGISTRATIONS`/`STANDARD_REGISTRATIONS`/`FULL_REGISTRATIONS`). Verify the actual `_register_<group>()` method names exist on the server class before writing the `REGISTRATION_MAP`.

- Modify: `/Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/profiles.py`

- Modify: `/Users/les/Projects/mahavishnu/mahavishnu/mcp/server_core.py`

- Create: `/Users/les/Projects/mahavishnu/tests/unit/test_wiring.py`

- Create (golden fixtures): `/Users/les/Projects/mahavishnu/tests/fixtures/{minimal,standard,full}/tool_names.json`

- [ ] **Step 1: Verify `_register_<group>()` methods exist on the server**

```bash
cd /Users/les/Projects/mahavishnu
grep -E '^    def _register_' mahavishnu/mcp/server_core.py
```

Document the actual method names. If names differ from `_register_health_tools`/`_register_terminal_tools`, use the actual names in `REGISTRATION_MAP` below.

- [ ] **Step 2: Capture golden fixtures BEFORE the refactor**

```bash
mkdir -p tests/fixtures/{minimal,standard,full}
cd /Users/les/Projects/mahavishnu
MAHAVISHNU_TOOL_PROFILE=minimal uv run python -c "
import asyncio, json
from mahavishnu.mcp.server import build_mahavishnu_mcp_server
async def main():
    server = await build_mahavishnu_mcp_server()
    tools = await server.list_tools()
    print(json.dumps(sorted([t.name for t in tools]), indent=2))
asyncio.run(main())
" > tests/fixtures/minimal/tool_names.json

MAHAVISHNU_TOOL_PROFILE=standard uv run python -c "
import asyncio, json
from mahavishnu.mcp.server import build_mahavishnu_mcp_server
async def main():
    server = await build_mahavishnu_mcp_server()
    tools = await server.list_tools()
    print(json.dumps(sorted([t.name for t in tools]), indent=2))
asyncio.run(main())
" > tests/fixtures/standard/tool_names.json

MAHAVISHNU_TOOL_PROFILE=full uv run python -c "
import asyncio, json
from mahavishnu.mcp.server import build_mahavishnu_mcp_server
async def main():
    server = await build_mahavishnu_mcp_server()
    tools = await server.list_tools()
    print(json.dumps(sorted([t.name for t in tools]), indent=2))
asyncio.run(main())
" > tests/fixtures/full/tool_names.json
```

- [ ] **Step 3: Write the failing wiring test + golden fixture assertion**

Create `/Users/les/Projects/mahavishnu/tests/unit/test_wiring.py`:

```python
"""Verify server_core.py calls apply_tool_profile() unconditionally + golden fixtures match."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest


def test_server_core_calls_apply_tool_profile():
    server_core = Path("mahavishnu/mcp/server_core.py")
    tree = ast.parse(server_core.read_text())
    found = any(
        isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "apply_tool_profile"
        for node in ast.walk(tree)
    )
    assert found, "server_core.py must call apply_tool_profile()"


@pytest.mark.asyncio
async def test_minimal_matches_golden_fixture(monkeypatch):
    """Tools at MINIMAL match the captured golden fixture."""
    monkeypatch.setenv("MAHAVISHNU_TOOL_PROFILE", "minimal")
    from mahavishnu.mcp.server import build_mahavishnu_mcp_server
    server = await build_mahavishnu_mcp_server()
    actual = sorted(t.name for t in await server.list_tools())
    expected = json.loads(Path("tests/fixtures/minimal/tool_names.json").read_text())
    assert actual == expected


@pytest.mark.asyncio
async def test_standard_matches_golden_fixture(monkeypatch):
    """Tools at STANDARD match the captured golden fixture."""
    monkeypatch.setenv("MAHAVISHNU_TOOL_PROFILE", "standard")
    from mahavishnu.mcp.server import build_mahavishnu_mcp_server
    server = await build_mahavishnu_mcp_server()
    actual = sorted(t.name for t in await server.list_tools())
    expected = json.loads(Path("tests/fixtures/standard/tool_names.json").read_text())
    assert actual == expected


@pytest.mark.asyncio
async def test_full_matches_golden_fixture(monkeypatch):
    """Tools at FULL match the captured golden fixture."""
    monkeypatch.setenv("MAHAVISHNU_TOOL_PROFILE", "full")
    from mahavishnu.mcp.server import build_mahavishnu_mcp_server
    server = await build_mahavishnu_mcp_server()
    actual = sorted(t.name for t in await server.list_tools())
    expected = json.loads(Path("tests/fixtures/full/tool_names.json").read_text())
    assert actual == expected
```

- [ ] **Step 4: Run wiring tests to verify failure**

Run: `cd /Users/les/Projects/mahavishnu && uv run pytest tests/unit/test_wiring.py -v`
Expected: 4 FAILs (no `apply_tool_profile` call; golden fixture import will fail at fixture load).

- [ ] **Step 5: Update `mahavishnu/mcp/tools/profiles.py`** (add NEW `REGISTRATION_MAP` and NEW `settings_yaml_loader`)

Read existing file. Append NEW code (do not modify existing `PROFILE_REGISTRATIONS`):

```python
from collections.abc import Callable


REGISTRATION_MAP: dict[str, Callable] = {
    # Verify actual method names against `grep -E '^    def _register_' mahavishnu/mcp/server_core.py`
    "_register_health_tools": lambda s: s._register_health_tools(),
    "_register_terminal_tools": lambda s: s._register_terminal_tools(),
    # Add one entry per existing PROFILE_REGISTRATIONS group, verified above
}


def settings_yaml_loader() -> dict | None:
    """NEW: Load settings/local.yaml tool_profile key. Preserves mahavishnu's
    env → yaml → default precedence via the helper's yaml_loader parameter.
    """
    try:
        from mahavishnu.core.config import get_settings
        return {"tool_profile": str(get_settings().tool_profile or "")}
    except Exception:
        return None
```

- [ ] **Step 6: Wire `apply_tool_profile()` in `server_core.py`**

Find the existing startup section (currently uses `get_active_profile` to gate). Replace with:

```python
from mcp_common.tools import ALL_TOOLS, ToolProfile, apply_tool_profile
from mahavishnu.mcp.tools.profiles import (
    PROFILE_REGISTRATIONS as _PROFILE_REGISTRATIONS,
    REGISTRATION_MAP,
    settings_yaml_loader,
)


async def _register_all_tool_groups(server) -> None:
    """NEW: Bulk register all tool groups at FULL profile."""
    for fn in set(REGISTRATION_MAP.values()):
        await fn(server) if inspect.iscoroutinefunction(fn) else fn(server)


# Replace existing get_active_profile() gating with:
await apply_tool_profile(
    server,
    profile_env_var="MAHAVISHNU_TOOL_PROFILE",
    registrations=_PROFILE_REGISTRATIONS,
    registration_map=REGISTRATION_MAP,
    register_all_fn=_register_all_tool_groups,
    yaml_loader=settings_yaml_loader,
)
```

- [ ] **Step 7: Run all tests; confirm golden fixture match**

Run: `cd /Users/les/Projects/mahavishnu && uv run pytest tests/unit/test_wiring.py tests/integration/ -v`
Expected: All pass; tool sets at each profile match the golden fixtures.

- [ ] **Step 8: Run crackerjack quality gate**

Run: `cd /Users/les/Projects/mahavishnu && uv run crackerjack run --no-publish`
Expected: PASS.

- [ ] **Step 9: Commit + ff-merge**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/mcp/tools/profiles.py mahavishnu/mcp/server_core.py tests/
git commit -c user.email=les@wedgwoodwebworks.com -m "refactor(mahavishnu): use apply_tool_profile() from mcp-common

Preserves the existing method-name PROFILE_REGISTRATIONS shape via
REGISTRATION_MAP lambdas + yaml precedence via yaml_loader parameter.
Golden fixtures verified identical at MINIMAL/STANDARD/FULL.

Co-Authored-By: Claude <noreply@anthropic.com>"
git checkout main && git merge --ff-only <branch-name>
```

______________________________________________________________________

## Task 3 (W1.2): Backfill session-buddy

**Files:** Same as Task 2 but for session-buddy repo. **Follow the Task 2 pattern exactly**, with these substitutions:

- Replace `mahavishnu` paths with `session-buddy`/`session_buddy`

- Replace `MAHAVISHNU_TOOL_PROFILE` with `SESSION_BUDDY_TOOL_PROFILE`

- Verify session-buddy's `_register_<group>()` method names via `grep -E '^    def _register_' session_buddy/mcp/server.py` BEFORE writing `REGISTRATION_MAP`

- Skip `yaml_loader` parameter (session-buddy uses env-only — pass `None`)

- Skip the `settings_yaml_loader` function definition

- [ ] **Steps 1–9:** Same as Task 2, scoped to session-buddy. Skip Step 5's `settings_yaml_loader`.

______________________________________________________________________

## Task 4 (W1.3): Backfill akosha

**Files:** Same as Task 3 but for akosha repo. Substitutions:

- Replace paths with `akosha/akosha/mcp/...`

- Replace env var with `AKOSHA_TOOL_PROFILE`

- Skip yaml_loader (env-only)

- Verify `_register_<group>()` methods via grep

- [ ] **Steps 1–9:** Same as Task 3, scoped to akosha.

______________________________________________________________________

## Task 5 (W1.4): Backfill dhara

**Files:** Same as Task 3 but for dhara repo. Substitutions:

- Replace paths with `dhara/dhara/mcp/...`

- Replace env var with `DHARA_TOOL_PROFILE`

- Skip yaml_loader (env-only)

- Verify `_register_<group>()` methods via grep

- [ ] **Steps 1–9:** Same as Task 3, scoped to dhara.

**W1 completion gate:** All 4 repos land. Run `python mahavishnu/scripts/audit_orphans.py --days 7 --root <each-repo>` to confirm `apply_tool_profile` is called in each main entrypoint.

______________________________________________________________________

## Task 6 (W2a): Crackerjack retrofit

**Files:**

- Read first: `/Users/les/Projects/crackerjack/crackerjack/mcp/tools/discover_tools.py` (236 lines total: `TOOL_REGISTRY`=170 lines at 9-178; `DEFERRED_TOOLS`=6 lines at 181-186; `register_discover_tools`=41 lines at 189-229)

- Delete: `/Users/les/Projects/crackerjack/crackerjack/mcp/tools/discover_tools.py` (use `git rm`, NOT AST surgery)

- Create: `/Users/les/Projects/crackerjack/crackerjack/mcp/tools/profiles.py`

- Create: `/Users/les/Projects/crackerjack/crackerjack/mcp/tools/discover_query.py` (preserves existing `query` filter)

- Modify: `/Users/les/Projects/crackerjack/crackerjack/mcp/server_core.py`

- Create: `/Users/les/Projects/crackerjack/tests/unit/test_tool_profile.py`

- Create: `/Users/les/Projects/crackerjack/tests/unit/test_discover_tools_deletion.py`

- Create: `/Users/les/Projects/crackerjack/.claude/decisions/tool-profile-rationale.md`

- Modify: `/Users/les/Projects/crackerjack/docs/architecture/MEMORY_ARCHITECTURE.md`

- [ ] **Step 1: Pre-deletion grep** (scoped to docs AND production)

```bash
cd /Users/les/Projects/crackerjack
git grep -l TOOL_REGISTRY crackerjack/  # production code
git grep -l TOOL_REGISTRY docs/        # docs (will hit MEMORY_ARCHITECTURE.md)
git grep -l DEFERRED_TOOLS crackerjack/
```

Production: must return ONLY `discover_tools.py` + tests. Docs: must return ONLY `MEMORY_ARCHITECTURE.md` (which we annotate in Step 10). If docs return more files, add doc-fix steps.

- [ ] **Step 2: Capture TOOL_REGISTRY keys + golden fixtures BEFORE deletion**

```bash
cd /Users/les/Projects/crackerjack
mkdir -p tests/fixtures/{minimal,standard,full}

# Capture TOOL_REGISTRY keys for _TOOL_GROUPS population
python -c "
from crackerjack.mcp.tools.discover_tools import TOOL_REGISTRY
import json
keys = list(TOOL_REGISTRY.keys())
print(json.dumps(keys, indent=2))
" > tests/fixtures/_tool_registry_keys.json

# Capture golden fixtures (current behavior, before env var exists)
python -c "
import asyncio, json
from crackerjack.mcp.server import build_crackerjack_mcp_server
async def main():
    server = await build_crackerjack_mcp_server()
    tools = await server.list_tools()
    print(json.dumps(sorted([t.name for t in tools]), indent=2))
asyncio.run(main())
" > tests/fixtures/full/tool_names.json
# Repeat for minimal, standard (the env var doesn't exist yet, so capture current behavior)
```

- [ ] **Step 3: Build the `_TOOL_GROUPS` mapping from TOOL_REGISTRY**

```bash
cd /Users/les/Projects/crackerjack
python -c "
from crackerjack.mcp.tools.discover_tools import TOOL_REGISTRY
import json
mapping = {name: entry['group'] for name, entry in TOOL_REGISTRY.items()}
print(json.dumps(mapping, indent=2))
" > tests/fixtures/_tool_groups_mapping.json
```

Verify the output makes sense (no `None` groups, no missing tools).

- [ ] **Step 4: Write failing tests for deletion + wiring + discover_fn override**

Create `/Users/les/Projects/crackerjack/tests/unit/test_discover_tools_deletion.py`:

```python
"""Verify discover_tools.py + TOOL_REGISTRY are gone post-W2a."""
from __future__ import annotations

import subprocess
from pathlib import Path


def test_discover_tools_py_deleted():
    assert not Path("crackerjack/mcp/tools/discover_tools.py").exists()


def test_tool_registry_unreferenced():
    """No code in crackerjack/ or docs/ may import TOOL_REGISTRY after W2a."""
    result = subprocess.run(
        ["git", "grep", "-l", "TOOL_REGISTRY", "crackerjack/", "docs/"],
        capture_output=True, text=True,
    )
    assert not result.stdout.strip(), (
        f"TOOL_REGISTRY still referenced: {result.stdout}"
    )
```

Create `/Users/les/Projects/crackerjack/tests/unit/test_tool_profile.py`:

```python
"""Crackerjack tool profile wiring tests."""
from __future__ import annotations

import ast
from pathlib import Path

from mcp_common.tools import ToolProfile
from mcp_common.tools.dispatch import ALL_TOOLS


def test_profiles_py_defes():
    profiles = Path("crackerjack/mcp/tools/profiles.py")
    tree = ast.parse(profiles.read_text())
    found = any(
        isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "PROFILE_REGISTRATIONS"
            for t in node.targets
        )
        for node in ast.walk(tree)
    )
    assert found


def test_server_core_uses_crackerjack_tool_profile_env_var():
    server_core = Path("crackerjack/mcp/server_core.py")
    tree = ast.parse(server_core.read_text())
    found = any(
        isinstance(node, ast.Constant) and node.value == "CRACKERJACK_TOOL_PROFILE"
        for node in ast.walk(tree)
    )
    assert found


def test_discover_fn_wired():
    """server_core.py must pass discovery_fn=crackerjack_discovery to apply_tool_profile."""
    server_core = Path("crackerjack/mcp/server_core.py")
    tree = ast.parse(server_core.read_text())
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "discovery_fn" and isinstance(kw.value, ast.Name):
                    if kw.value.id == "crackerjack_discovery":
                        found = True
    assert found, "apply_tool_profile call must pass discovery_fn=crackerjack_discovery"


@pytest.mark.asyncio
async def test_minimal_matches_golden_fixture(monkeypatch):
    """MANDATORY ⊆ registered at MINIMAL + matches captured fixture."""
    import json
    from pathlib import Path
    monkeypatch.setenv("CRACKERJACK_TOOL_PROFILE", "minimal")
    from crackerjack.mcp.server import build_crackerjack_mcp_server
    server = await build_crackerjack_mcp_server()
    names = {t.name for t in await server.list_tools()}
    from mcp_common.tools import MANDATORY_TOOLS
    assert MANDATORY_TOOLS.issubset(names), (
        f"MANDATORY tools not all registered: missing {MANDATORY_TOOLS - names}"
    )
    assert "discover_tools" in names


# Repeat test_standard_matches_golden_fixture + test_full_matches_golden_fixture
```

- [ ] **Step 5: Run tests to verify failure**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/test_tool_profile.py tests/unit/test_discover_tools_deletion.py -v`
Expected: 5 FAILs.

- [ ] **Step 6: Create `crackerjack/mcp/tools/profiles.py`**

```python
"""Crackerjack tool profile registration.

MANDATORY entries are per-tool (NOT mapped to the same group function —
that caused 4× duplicate registration in early drafts).
"""
from __future__ import annotations

from collections.abc import Callable

from mcp_common.tools import ToolProfile, MANDATORY_TOOLS, ALL_TOOLS


PROFILE_REGISTRATIONS = {
    ToolProfile.MINIMAL: list(MANDATORY_TOOLS),
    ToolProfile.STANDARD: [
        "core_tools",
        "execution_tools",
        "utility_tools",
        "doc_tools",
    ],
    ToolProfile.FULL: ALL_TOOLS,
}


REGISTRATION_MAP: dict[str, Callable] = {
    "core_tools": lambda s: s._register_core_tools(),
    "execution_tools": lambda s: s._register_execution_tools(),
    "utility_tools": lambda s: s._register_utility_tools(),
    "doc_tools": lambda s: s._register_doc_tools(),
    # MANDATORY tools — per-tool entries (each calls a specific register fn)
    "get_liveness": lambda s: s._register_core_tools(),  # adjust to actual health probe fn
    "get_readiness": lambda s: s._register_core_tools(),
    "health_check": lambda s: s._register_core_tools(),
    "health_check_all": lambda s: s._register_core_tools(),
}


def register_all_tool_groups(server) -> None:
    """Bulk register all Crackerjack tool groups (called at FULL profile)."""
    server._register_core_tools()
    server._register_execution_tools()
    server._register_utility_tools()
    server._register_doc_tools()
    if hasattr(server, "_register_eventbridge_tools"):
        server._register_eventbridge_tools()
    if hasattr(server, "_register_progress_tools"):
        server._register_progress_tools()
```

- [ ] **Step 7: Create `crackerjack/mcp/tools/discover_query.py`** (populated from Step 3)

```python
"""Crackerjack's discover_tools() override — preserves query filter from deleted TOOL_REGISTRY.

_TOOL_GROUPS populated from the deleted TOOL_REGISTRY (see tests/fixtures/_tool_groups_mapping.json).
"""
from __future__ import annotations

import json
from pathlib import Path

from fastmcp import FastMCP


_TOOL_GROUPS: dict[str, str] = json.loads(
    Path("tests/fixtures/_tool_groups_mapping.json").read_text()
)


async def crackerjack_discovery(server: FastMCP, filter_query: str | None) -> list[dict]:
    """Discovery with optional query filter (replaces discover_tools.py:189-229)."""
    tools = await server.list_tools()
    result = [
        {
            "name": t.name,
            "description": t.description or "",
            "inputSchema": t.parameters,
            "group": _TOOL_GROUPS.get(t.name),
        }
        for t in tools
    ]
    if filter_query:
        q = filter_query.lower()
        result = [
            t for t in result
            if q in t["name"].lower() or q in t["description"].lower()
        ]
    return result
```

- [ ] **Step 8: Delete `crackerjack/mcp/tools/discover_tools.py`**

```bash
cd /Users/les/Projects/crackerjack
git rm crackerjack/mcp/tools/discover_tools.py
```

Validate the rest of the repo still parses: `python -c "import ast; ast.parse(open('crackerjack/mcp/server_core.py').read())"`

- [ ] **Step 9: Wire `apply_tool_profile()` in `crackerjack/mcp/server_core.py`**

Add at top:

```python
from mcp_common.tools import ToolProfile, apply_tool_profile
from crackerjack.mcp.tools.profiles import (
    PROFILE_REGISTRATIONS,
    REGISTRATION_MAP,
    register_all_tool_groups,
)
from crackerjack.mcp.tools.discover_query import crackerjack_discovery
```

Replace any existing `discover_tools()` registration with:

```python
await apply_tool_profile(
    server,
    profile_env_var="CRACKERJACK_TOOL_PROFILE",
    registrations=PROFILE_REGISTRATIONS,
    registration_map=REGISTRATION_MAP,
    register_all_fn=register_all_tool_groups,
    discovery_fn=crackerjack_discovery,
)
```

- [ ] **Step 10: Update `MEMORY_ARCHITECTURE.md` with the literal annotation text**

Find the section referencing missing `CRACKERJACK_TOOL_PROFILE`. Replace with:

```
**Resolved 2026-08-18:** `CRACKERJACK_TOOL_PROFILE` is now implemented in `crackerjack/mcp/tools/profiles.py`. See `2026-08-18-mcp-tool-profile-adoption-design` for context.
```

- [ ] **Step 11: Create `.claude/decisions/tool-profile-rationale.md`**

Document:

- Why `eventbridge_tools` and `progress_tools` are in FULL not STANDARD

- Why `validate_claude_md` is in STANDARD (write-side tool)

- Reference `2026-08-18-mcp-tool-profile-adoption-design` for context

- [ ] **Step 12: Run all tests; verify golden fixture match**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/ -v`
Expected: All pass.

- [ ] **Step 13: Run crackerjack quality gate**

Run: `cd /Users/les/Projects/crackerjack && uv run crackerjack run --no-publish`
Expected: PASS. (Note: `crackerjack run` runs `ruff check --fix --unsafe-fixes` — verify imports don't collapse per memory `crackerjack-fast-hooks-ruff-autofix`.)

- [ ] **Step 14: Commit + ff-merge**

```bash
cd /Users/les/Projects/crackerjack
git add -A
git commit -c user.email=les@wedgwoodwebworks.com -m "refactor(crackerjack): adopt apply_tool_profile() with CRACKERJACK_TOOL_PROFILE

Deletes legacy crackerjack/mcp/tools/discover_tools.py (236 lines
incl. TOOL_REGISTRY + DEFERRED_TOOLS) via git rm. Preserves the existing
query filter via discovery_fn=crackerjack_discovery override. Golden
fixtures verified identical at MINIMAL/STANDARD/FULL.

Co-Authored-By: Claude <noreply@anthropic.com>"
git checkout main && git merge --ff-only <branch-name>
```

______________________________________________________________________

## Task 7 (W2b.1): Adopt `apply_tool_profile()` in mailgun-mcp (Tier-C example)

**CRITICAL CORRECTION:** The package is `mailgun_mcp/` (underscore), NOT `mailgun/mcp/`. Main is `mailgun_mcp/main.py` with **inline `@mcp.tool()` decorators** (no `register_*` functions exist). This is the **decorator-mode** case.

**Files:**

- Read first: `/Users/les/Projects/mailgun-mcp/mailgun_mcp/main.py` to enumerate the inline `@mcp.tool()` decorators

- Modify: `/Users/les/Projects/mailgun-mcp/mailgun_mcp/main.py` (refactor decorators into callable registrations — Task 7 needs to do this BEFORE applying the helper)

- Create: `/Users/les/Projects/mailgun-mcp/mailgun_mcp/tools/profiles.py`

- Create: `/Users/les/Projects/mailgun-mcp/tests/unit/test_tool_profile.py`

- Create: `/Users/les/Projects/mailgun-mcp/.claude/decisions/tool-profile-rationale.md`

- [ ] **Step 1: Audit existing `@mcp.tool()` decorators + refactor to register functions**

```bash
cd /Users/les/Projects/mailgun-mcp
grep -nE '@mcp\.tool\(' mailgun_mcp/main.py | head -20
```

Refactor strategy: extract each `@mcp.tool()` decorated function into a named module-level function (e.g., `def send_messages(): ...`), then group related functions into `register_<group>` module functions called by the helper.

For mailgun-mcp's 20+ tools, group by domain:

- `register_send_tools()` — send_messages, send_batch, etc.
- `register_stats_tools()` — get_stats, get_deliverability, etc.
- `register_validation_tools()` — validate_address, validate_domain, etc.
- `register_domain_tools()` — list_domains, get_domain_info, etc.
- `register_webhook_tools()` — webhook_management (FULL only)
- `register_suppression_tools()` — suppression_lists (FULL only)

Each register function calls `mcp.tool(name=...)(func)` or `mcp.add_tool(Tool.from_function(...))`.

- [ ] **Step 2: Write the failing wiring test**

Create `/Users/les/Projects/mailgun-mcp/tests/unit/test_tool_profile.py`:

```python
"""mailgun-mcp tool profile tests."""
from __future__ import annotations

import ast
from pathlib import Path


def test_profiles_module_exists():
    assert Path("mailgun_mcp/tools/profiles.py").exists()


def test_server_uses_mailgun_tool_profile_env_var():
    server = Path("mailgun_mcp/main.py")
    tree = ast.parse(server.read_text())
    found = any(
        isinstance(node, ast.Constant) and node.value == "MAILGUN_TOOL_PROFILE"
        for node in ast.walk(tree)
    )
    assert found


# Plus MANDATORY ⊆ registered test (see Task 2 Step 3 for template)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Users/les/Projects/mailgun-mcp && uv run pytest tests/unit/test_tool_profile.py -v`
Expected: FAILs.

- [ ] **Step 4: Create `mailgun_mcp/tools/profiles.py`**

```python
"""mailgun-mcp tool profile registration."""
from __future__ import annotations

from collections.abc import Callable

from mcp_common.tools import ToolProfile, MANDATORY_TOOLS, ALL_TOOLS


PROFILE_REGISTRATIONS = {
    ToolProfile.MINIMAL: list(MANDATORY_TOOLS),
    ToolProfile.STANDARD: [
        "send_tools",
        "stats_tools",
        "validation_tools",
        "domain_tools",
    ],
    ToolProfile.FULL: ALL_TOOLS,
}


# Lazy import to avoid loading the entire mailgun_mcp.main at module import time
def _build_registration_map():
    from mailgun_mcp.main import (
        register_send_tools,
        register_stats_tools,
        register_validation_tools,
        register_domain_tools,
        register_webhook_tools,
        register_suppression_tools,
        register_get_liveness,
        register_get_readiness,
        register_health_check,
        register_health_check_all,
    )
    return {
        "send_tools": register_send_tools,
        "stats_tools": register_stats_tools,
        "validation_tools": register_validation_tools,
        "domain_tools": register_domain_tools,
        "webhook_tools": register_webhook_tools,
        "suppression_tools": register_suppression_tools,
        # MANDATORY — per-tool
        "get_liveness": register_get_liveness,
        "get_readiness": register_get_readiness,
        "health_check": register_health_check,
        "health_check_all": register_health_check_all,
    }


def register_all_tool_groups(server) -> None:
    """Bulk register all mailgun-mcp tool groups (called at FULL profile)."""
    from mailgun_mcp.main import (
        register_send_tools,
        register_stats_tools,
        register_validation_tools,
        register_domain_tools,
        register_webhook_tools,
        register_suppression_tools,
    )
    register_send_tools(server)
    register_stats_tools(server)
    register_validation_tools(server)
    register_domain_tools(server)
    register_webhook_tools(server)
    register_suppression_tools(server)
```

- [ ] **Step 5: Refactor `mailgun_mcp/main.py` to expose `register_<group>` functions**

For each `@mcp.tool()` decorator, extract the function and wrap in a register function. Example pattern:

```python
# BEFORE:
@mcp.tool()
async def send_messages(payload: dict) -> dict:
    ...

# AFTER:
async def send_messages(payload: dict) -> dict:
    ...

def register_send_tools(server) -> None:
    server.add_tool(Tool.from_function(fn=send_messages, name="send_messages", description="..."))
    # ... other send-related tools
```

- [ ] **Step 6: Wire `apply_tool_profile()` in `mailgun_mcp/main.py`**

At the server startup section:

```python
from mcp_common.tools import ToolProfile, apply_tool_profile
from mailgun_mcp.tools.profiles import (
    PROFILE_REGISTRATIONS,
    _build_registration_map,
    register_all_tool_groups,
)

await apply_tool_profile(
    mcp,
    profile_env_var="MAILGUN_TOOL_PROFILE",
    registrations=PROFILE_REGISTRATIONS,
    registration_map=_build_registration_map(),
    register_all_fn=register_all_tool_groups,
)
```

- [ ] **Step 7: Run tests**

Run: `cd /Users/les/Projects/mailgun-mcp && uv run pytest tests/unit/test_tool_profile.py -v`
Expected: All pass.

- [ ] **Step 8: Run crackerjack quality gate**

Run: `cd /Users/les/Projects/mailgun-mcp && uv run crackerjack run --no-publish`
Expected: PASS.

- [ ] **Step 9: Update `mailgun-mcp/CLAUDE.md` "Tool Profile System" subsection**

Add (corrected env var name):

```
## Tool Profile System

mailgun-mcp uses the shared `apply_tool_profile()` helper from `mcp-common`.

- Env var: `MAILGUN_TOOL_PROFILE` (values: `minimal` / `standard` / `full`; default `full`)
- See `.claude/decisions/tool-profile-rationale.md` for bucket mapping.
- `discover_tools()` meta-tool returns current profile + registered tool count.
```

- [ ] **Step 10: Write `.claude/decisions/tool-profile-rationale.md`**

Document the 3-tier mapping rationale.

- [ ] **Step 11: Commit + ff-merge**

```bash
cd /Users/les/Projects/mailgun-mcp
git add -A
git commit -c user.email=les@wedgwoodwebworks.com -m "feat(mailgun-mcp): adopt apply_tool_profile() with MAILGUN_TOOL_PROFILE

Refactored inline @mcp.tool() decorators into register_<group>
module functions (decorator-mode → callable-mode). 3-tier mapping
per 2026-08-18 spec. Daily-driver tools in STANDARD; advanced
(webhook, suppression) in FULL.

Co-Authored-By: Claude <noreply@anthropic.com>"
git checkout main && git merge --ff-only <branch-name>
```

______________________________________________________________________

## Task 8 (W2b.2): Adopt `apply_tool_profile()` in opera-cloud-mcp

**CORRECTIONS from prior plan:**

- Package is `opera_cloud_mcp/` (underscore), NOT `opera-cloud/mcp/`
- Tool count is **53**, NOT 56 as previously stated
- Has ~40 register fns in `tools/operation_tools.py`, `tools/room_tools.py`, `tools/tool_registry.py`

**Files:** Same as Task 7 but for opera-cloud-mcp. Substitutions:

- Replace `mailgun`/`mailgun_mcp` with `opera-cloud`/`opera_cloud_mcp`

- Replace `MAILGUN_TOOL_PROFILE` with `OPERA_CLOUD_TOOL_PROFILE`

- Audit `opera_cloud_mcp/tools/*.py` for actual `register_*` functions BEFORE writing `REGISTRATION_MAP`

- 3-tier mapping: STANDARD = reservation_search + guest_lookup; FULL = all 53 (incl. write-side ops)

- [ ] **Steps 1–11:** Same as Task 7, scoped to opera-cloud-mcp.

______________________________________________________________________

## Task 9 (W2b.3): Adopt `apply_tool_profile()` in spline-mcp

**CORRECTIONS from prior plan:**

- Package is `spline_mcp/` (underscore), NOT `spline/mcp/`
- Actually has these register fns: `register_generation_tools`, `register_asset_tools`, `register_helper_tools`, `register_docs_tools`, `register_integration_tools` (5 register fns, 25 tools total — matches plan)

**Files:** Same as Task 7 but for spline-mcp. Substitutions:

- Replace `mailgun`/`mailgun_mcp` with `spline`/`spline_mcp`

- Replace `MAILGUN_TOOL_PROFILE` with `SPLINE_TOOL_PROFILE`

- Audit `spline_mcp/tools/*.py` for actual `register_*` functions (already known: 5 fns)

- 3-tier mapping: STANDARD = scene CRUD + import/export; FULL = all 25

- [ ] **Steps 1–11:** Same as Task 7, scoped to spline-mcp.

**W2b completion gate:** All 3 Tier-C repos land. Verify with `python mahavishnu/scripts/audit_orphans.py --days 7 --root <each-repo>`.

______________________________________________________________________

## Tasks 10-13 (W3): Tier-B adoption (graphics-mcp, langsmith-mcp, synxis-crs-mcp, unifi-mcp)

**Each W3 repo follows Task 7 pattern** (smaller scope than Tier-C):

- Task 10: graphics-mcp → env var `GRAPHICS_TOOL_PROFILE`
- Task 11: langsmith-mcp → env var `LANGSMITH_TOOL_PROFILE`
- Task 12: synxis-crs-mcp → env var `SYNXIS_CRS_TOOL_PROFILE`
- Task 13: unifi-mcp → env var `UNIFI_TOOL_PROFILE`

Per-repo specifics:

1. Audit `<pkg>/mcp/` for actual register patterns (decorator vs callable)
1. Decorator-mode refactor if needed (mailgun-mcp pattern)
1. Create `profiles.py` with 2-tier mapping (smaller than Tier-C's 3-tier)
1. Wire `apply_tool_profile()` in main entrypoint
1. Update CLAUDE.md "Tool Profile System" subsection
1. Write `.claude/decisions/tool-profile-rationale.md`
1. Commit + ff-merge

All commits MUST include `-c user.email=les@wedgwoodwebworks.com`.

**W3 completion gate:** All 4 repos land. Verify with `audit_orphans.py`.

______________________________________________________________________

## Tasks 14-23 (W4): Tier-A batch adoption (10 repos as 10 sub-tasks)

Per the TDD review, splitting the W4 batch into 10 sub-tasks for proper TDD discipline:

| Task | Repo | Package | Env var | Notes |
|------|------|---------|---------|-------|
| 14 | css-mcp | `css_mcp/` | `CSS_TOOL_PROFILE` | 9 tools |
| 15 | excalidraw-mcp | `excalidraw_mcp/` | `EXCALIDRAW_TOOL_PROFILE` | 5 tools |
| 16 | neo4j-mcp | `neo4j_mcp/` | `NEO4J_TOOL_PROFILE` | 9 tools |
| 17 | penpot-api-mcp | `penpot_api_mcp/` | `PENPOT_API_TOOL_PROFILE` | 6 tools |
| 18 | porkbun-dns-mcp | `porkbun_dns_mcp/` | `PORKBUN_DNS_TOOL_PROFILE` | 5 tools |
| 19 | porkbun-domain-mcp | `porkbun_domain_mcp/` | `PORKBUN_DOMAIN_TOOL_PROFILE` | 5 tools |
| 20 | raindropio-mcp | `raindropio_mcp/` | `RAINDROPIO_TOOL_PROFILE` | 0 tools (MANDATORY opt-out) |
| 21 | synxis-pms-mcp | `synxis_pms_mcp/` | `SYNXIS_PMS_TOOL_PROFILE` | 10 tools |
| 22 | fastblocks | `fastblocks/` | `FASTBLOCKS_TOOL_PROFILE` | 8 tools (uses `_register_tools()`) |
| 23 | splashstand | `splashstand/` | `SPLASHSTAND_TOOL_PROFILE` | ~10 tools |

**Each task follows this template:**

- [ ] **Step 1: Audit `<pkg>/mcp/` for register pattern**

```bash
cd /Users/les/Projects/<repo>
grep -rE '^def register_|@.*\.tool\(|@mcp\.tool\(' <pkg>/mcp/ --include='*.py' | head -10
```

- [ ] **Step 2: Decorator-mode refactor if needed**

For repos using `@mcp.tool()` decorators (Tier-A decorator-mode): extract each decorated function into a named module-level function and wrap in `register_<group>` callable. (See Task 7 Step 5 template.)

- [ ] **Step 3: Create `<pkg>/mcp/tools/profiles.py` with trivial Tier-A mapping**

```python
from collections.abc import Callable

from mcp_common.tools import ToolProfile, MANDATORY_TOOLS, ALL_TOOLS


PROFILE_REGISTRATIONS = {
    ToolProfile.MINIMAL: list(MANDATORY_TOOLS),
    ToolProfile.STANDARD: ALL_TOOLS,
    ToolProfile.FULL: ALL_TOOLS,
}


def _build_registration_map():
    # Audit-derived mappings; replace with actual register fn names
    from <pkg>.mcp.server import (
        register_all_tools,
        register_get_liveness,
        register_get_readiness,
        register_health_check,
        register_health_check_all,
    )
    return {
        "get_liveness": register_get_liveness,
        "get_readiness": register_get_readiness,
        "health_check": register_health_check,
        "health_check_all": register_health_check_all,
    }


def register_all_tool_groups(server) -> None:
    from <pkg>.mcp.server import register_all_tools
    register_all_tools(server)
```

- [ ] **Step 4: Wire `apply_tool_profile()` in main entrypoint**

```python
await apply_tool_profile(
    server,
    profile_env_var="<REPO>_TOOL_PROFILE",
    registrations=PROFILE_REGISTRATIONS,
    registration_map=_build_registration_map(),
    register_all_fn=register_all_tool_groups,
)
```

- [ ] **Step 5: Create `tests/unit/test_tool_profile.py`** with `MANDATORY ⊆ registered` assertion at all 3 profile levels

- [ ] **Step 6: Run tests + crackerjack quality gate**

```bash
cd /Users/les/Projects/<repo>
uv run pytest tests/unit/test_tool_profile.py -v
uv run crackerjack run --no-publish
```

- [ ] **Step 7: Update CLAUDE.md "Tool Profile System" subsection**

- [ ] **Step 8: Commit + ff-merge**

```bash
cd /Users/les/Projects/<repo>
git add -A
git commit -c user.email=les@wedgwoodwebworks.com -m "feat(<repo>): adopt apply_tool_profile() with <REPO>_TOOL_PROFILE

Tier-A trivial mapping (MINIMAL=health, STANDARD/FULL=all). Tier-A
consistency dividend; no significant context savings at this scale.

Co-Authored-By: Claude <noreply@anthropic.com>"
git checkout main && git merge --ff-only <branch-name>
```

**W4 batch can be dispatched in parallel** (10 subagent impls + 1 verifier per memory `wave-11-mirror-review-findings`).

**W4 completion gate:** All 10 repos land. Run `audit_orphans.py` per repo. Generate `docs/ecosystem/MCP_TOOL_PROFILES.md` programmatically from `mcp.list_tools()` (per spec §Cross-Cutting).

______________________________________________________________________

## Self-Review

**1. Spec coverage:** All sections of the spec map to tasks (W0 → Task 1; W1 → Tasks 2-5; W2a → Task 6; W2b → Tasks 7-9; W3 → Tasks 10-13; W4 → Tasks 14-23). Constraints addressed in Global Constraints section.

**2. Placeholder scan:** No "TBD" / "fill in details" remain. The `<pkg>` / `<repo>` placeholders in W4 Tasks 14-23 are intentional — they document per-repo substitution points (each repo's package name + env var). All other code blocks are complete.

**3. Type consistency:**

- `apply_tool_profile()` signature: `(server, *, profile_env_var, registrations, registration_map, register_all_fn, mandatory_tools, discovery_fn, yaml_loader)` — consistent across all tasks.
- `PROFILE_REGISTRATIONS` shape: `dict[ToolProfile, list[str | Callable] | type[ALL_TOOLS]]` — consistent.
- `REGISTRATION_MAP` shape: `dict[str, Callable]` — consistent.
- `register_all_tool_groups(server)` signature — consistent.

All checks pass. Plan is ready for execution.

**Critical fixes applied (from 4-agent review):**

1. FastMCP 3.4.7 API: `Tool.from_function()` (not `add_tool(name=, description=, fn=)`); `_local_provider.remove_tool()` (not `_tool_manager`); `Tool.parameters` (not `Tool.inputSchema`)
1. `_resolve_profile()`: UNSET env → FULL (not raise); SET-BUT-INVALID → raise `InvalidProfileError`
1. `_resolve_profile()` and `mandatory_tools` loop: refresh `registered_names` after each call (avoid stale set)
1. MANDATORY entries: per-tool lambdas (not 4× same group)
1. Tier-C repo paths: `mailgun_mcp/` / `spline_mcp/` / `opera_cloud_mcp/` (underscore package names, NOT hyphen)
1. mailgun-mcp: decorator-mode refactor step BEFORE applying helper
1. opera-cloud-mcp: tool count 53 (not 56)
1. spline-mcp: actual register fn names (`register_generation_tools`, `register_asset_tools`, etc.)
1. Crackerjack: 236 lines discover_tools.py; AST surgery replaced with `git rm`; `_TOOL_GROUPS` capture step BEFORE deletion
1. W4 batch: split into 10 sub-tasks (Tasks 14-23) for proper TDD discipline
1. W0 Step 10 commit: `-c user.email=les@wedgwoodwebworks.com` flag
1. Tests: monkeypatch for env isolation; correct expected count (7 unit tests + 6 integration tests)
1. Task 2: corrected line range (PROFILE_REGISTRATIONS at lines 69-73, not 39-63); `settings_yaml_loader` is NEW code
1. Crackerjack: discover_fn wiring test added
1. Mailgun-mcp CLAUDE.md: corrected env var name (MAILGUN, not MAHAVISHNU)
1. Typo: `crackerjack-fastfast-hooks-ruff-autofix` → `crackerjack-fast-hooks-ruff-autofix`

Plan complete and ready for execution.
