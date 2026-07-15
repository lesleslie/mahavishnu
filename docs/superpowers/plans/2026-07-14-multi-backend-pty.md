# Multi-Backend PTY Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the broken `uvx` launch in `mcp_client.py:248` and make Mahavishnu's PTY toolservers pluggable across multiple backends (MCPretentious on npm, luqm4nx/pty-mcp-server-python on PyPI), via a hardcoded built-in registry.

**Architecture:** A new `mahavishnu/terminal/backends.py` module holds a frozen `PtyBackend` dataclass and a `BUILTIN_BACKENDS` dict. `McpretentiousClient` takes a `backend_name`, resolves it through the registry, and uses the result to spawn the MCP subprocess. A `check_prerequisites()` helper validates that the required executables (`node`, `uvx`, etc.) are on `PATH` before spawn, so failures surface as clear `ConfigurationError`s at construction time instead of generic 30s timeouts at first tool call.

**Tech Stack:** Python 3.13, asyncio, `dataclasses(frozen=True)`, `shutil.which`, `pytest` (asyncio_mode=auto per `pyproject.toml`), npm for MCPretentious at install time, `uvx` for pty-mcp-server-python at install time.

**Spec:** `docs/superpowers/specs/2026-07-14-multi-backend-pty-design.md`

## Global Constraints

- **One `PtyBackend` per built-in.** No config surface for adding new backends. Operators pick by name.
- **Tool map is data-driven** for future-proofing but starts empty for both built-ins (both expose `mcpretentious-*` tool names).
- **No silent fallbacks** in error handling. `ConfigurationError` at construction, `ToolCallError` per call.
- **Gated integration test** — `MCPRETENTIOUS_INTEGRATION=1` env var. Skipped in fast CI.
- **Frequent commits** — every task ends with a commit.
- **Crackerjack code style** per `/Users/les/Projects/mahavishnu/CLAUDE.md`: `from __future__ import annotations` first, `X | None = None` (not `Optional`), no `Any` in tool inputs, `logger.exception(...)` not `logger.error(exc_info=)`, no `assert` in production code.
- **Public API check**: `mahavishnu/terminal/__init__.py` exposes `McpretentiousAdapter`. The new `backends.py` should NOT be in the public init — it's an internal implementation detail of the `mcp_client.py` module.

______________________________________________________________________

## Task 1: Add `backends.py` registry module (TDD)

**Files:**

- Create: `mahavishnu/terminal/backends.py`
- Create: `tests/unit/terminal/test_backends.py`

**Interfaces this task produces:**

- `from mahavishnu.terminal.backends import PtyBackend, BUILTIN_BACKENDS, check_prerequisites`

- `PtyBackend(name: str, command: str, args: tuple[str, ...], tool_map: dict[str, str] = {}, requires: tuple[str, ...] = ())` — frozen dataclass

- `BUILTIN_BACKENDS: dict[str, PtyBackend]` — keyed by name

- `check_prerequisites(backend: PtyBackend) -> list[str]` — returns missing prerequisite names (empty = all present)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/terminal/test_backends.py` with these tests:

```python
"""Unit tests for mahavishnu.terminal.backends."""
from __future__ import annotations

from mahavishnu.terminal.backends import (
    BUILTIN_BACKENDS,
    PtyBackend,
    check_prerequisites,
)


class TestPtyBackend:
    def test_frozen_dataclass(self) -> None:
        # Frozen dataclasses raise FrozenInstanceError on attribute assignment.
        backend = PtyBackend(name="x", command="y", args=("z",))
        import dataclasses

        self.assertTrue(dataclasses.is_dataclass(backend))
        # Verify frozen by attempting mutation.
        with self.assertRaises(Exception):
            backend.name = "mutated"  # type: ignore[misc]

    def test_default_tool_map_is_empty_dict(self) -> None:
        backend = PtyBackend(name="x", command="y", args=("z",))
        self.assertEqual(backend.tool_map, {})

    def test_default_requires_is_empty_tuple(self) -> None:
        backend = PtyBackend(name="x", command="y", args=("z",))
        self.assertEqual(backend.requires, ())

    def test_equality_supports_dict_keys(self) -> None:
        a = PtyBackend(name="x", command="y", args=("z",))
        b = PtyBackend(name="x", command="y", args=("z",))
        # Equal PtyBackends should hash identically (frozen dataclass + eq=True).
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(a, b)


class TestBuiltinBackends:
    def test_has_mcpretentious(self) -> None:
        self.assertIn("mcpretentious", BUILTIN_BACKENDS)

    def test_mcpretentious_uses_npx(self) -> None:
        # Regression: the original bug was using "uvx" for an npm package.
        # The fix is "npx" + the npm package name.
        backend = BUILTIN_BACKENDS["mcpretentious"]
        self.assertEqual(backend.command, "npx")
        self.assertEqual(backend.args, ("mcpretentious",))

    def test_mcpretentious_requires_node(self) -> None:
        # MCPretentious is an npm package, so it needs Node.js on PATH.
        self.assertIn("node", BUILTIN_BACKENDS["mcpretentious"].requires)

    def test_has_pty_mcp_python(self) -> None:
        # The second built-in backend, using uvx.
        self.assertIn("pty_mcp_python", BUILTIN_BACKENDS)

    def test_pty_mcp_python_uses_uvx(self) -> None:
        backend = BUILTIN_BACKENDS["pty_mcp_python"]
        self.assertEqual(backend.command, "uvx")
        # Verify it has the --from flag pointing at the package.
        self.assertIn("--from", backend.args)
        self.assertIn("luqm4nx-pty-mcp-server-python", backend.args)

    def test_all_backends_have_command_args_name(self) -> None:
        # Defensive: every registered backend must be launchable.
        for name, backend in BUILTIN_BACKENDS.items():
            self.assertEqual(backend.name, name)
            self.assertTrue(backend.command, f"backend {name!r} has empty command")
            self.assertTrue(backend.args, f"backend {name!r} has empty args")


class TestCheckPrerequisites:
    def test_empty_requires_returns_empty_list(self) -> None:
        backend = PtyBackend(name="x", command="y", args=("z",))
        self.assertEqual(check_prerequisites(backend), [])

    def test_missing_prereq_is_reported(self) -> None:
        # "definitely-not-a-real-binary-xyz" should never exist on PATH.
        backend = PtyBackend(
            name="x", command="y", args=("z",),
            requires=("definitely-not-a-real-binary-xyz",),
        )
        result = check_prerequisites(backend)
        self.assertEqual(result, ["definitely-not-a-real-binary-xyz"])

    def test_present_prereq_is_not_reported(self) -> None:
        # "sh" is universally available on POSIX. On Windows this test would
        # need adjustment, but the spec is macOS/Linux only.
        backend = PtyBackend(
            name="x", command="y", args=("z",),
            requires=("sh",),
        )
        self.assertEqual(check_prerequisites(backend), [])

    def test_partial_missing_reports_only_missing(self) -> None:
        backend = PtyBackend(
            name="x", command="y", args=("z",),
            requires=("sh", "definitely-not-a-real-binary-xyz"),
        )
        self.assertEqual(check_prerequisites(backend), ["definitely-not-a-real-binary-xyz"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/python -m pytest tests/unit/terminal/test_backends.py -v
```

Expected: import error (`ModuleNotFoundError: No module named 'mahavishnu.terminal.backends'`).

- [ ] **Step 3: Write the minimal implementation**

Create `mahavishnu/terminal/backends.py`:

```python
"""PTY toolserver backend registry.

Built-in backends. Each entry defines:
  - command + args: how to spawn the MCP subprocess
  - tool_map: how Mahavishnu's generic tool names map to backend-specific
                names (empty = adapter uses its own hardcoded names; populated
                when a future adapter wants to share McpretentiousAdapter with
                a backend whose tool names differ — e.g., {"read": "screenshot"})
  - requires: prerequisites that must be on PATH

Adding a new backend = one entry here + (if tool surface differs) a thin
adapter shim. Operators pick by name via terminal.adapter_preference.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PtyBackend:
    """A single built-in PTY toolserver backend."""

    name: str
    command: str
    args: tuple[str, ...]
    tool_map: dict[str, str] = field(default_factory=dict)
    requires: tuple[str, ...] = field(default_factory=tuple)


BUILTIN_BACKENDS: dict[str, PtyBackend] = {
    "mcpretentious": PtyBackend(
        name="mcpretentious",
        command="npx",                              # was: "uvx" — BUG
        args=("mcpretentious",),
        tool_map={},                                # uses default names
        requires=("node",),                         # npm package
    ),
    "pty_mcp_python": PtyBackend(
        name="pty_mcp_python",
        command="uvx",
        args=("--from", "luqm4nx-pty-mcp-server-python", "pty-mcp-server-python"),
        tool_map={},                                # see Tool-name mapping in spec
        requires=("uvx",),
    ),
}


def check_prerequisites(backend: PtyBackend) -> list[str]:
    """Return a list of missing prerequisites (empty = all good).

    Called at McpretentiousClient construction time so failures surface
    with a clear message instead of every subsequent tool call timing out.
    """
    return [req for req in backend.requires if shutil.which(req) is None]
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/python -m pytest tests/unit/terminal/test_backends.py -v
```

Expected: all 13 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/terminal/backends.py tests/unit/terminal/test_backends.py
git commit -m "feat(terminal): add PTY backend registry

PtyBackend dataclass + BUILTIN_BACKENDS dict (mcpretentious via npx,
pty_mcp_server_python via uvx) and check_prerequisites() helper.
Module is internal to mcp_client.py — not re-exported from terminal/__init__.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

______________________________________________________________________

## Task 2: Wire registry into `mcp_client.py` (fix the original bug)

**Files:**

- Modify: `mahavishnu/terminal/mcp_client.py:248` (the hardcoded `StdioMCPClient(...)` call)
- Modify: `tests/unit/terminal/mcp_client.py` (add regression tests)

**Interfaces this task consumes from Task 1:**

- `from mahavishnu.terminal.backends import BUILTIN_BACKENDS, PtyBackend, check_prerequisites`
- `PtyBackend.command: str`, `PtyBackend.args: tuple[str, ...]`, `PtyBackend.requires: tuple[str, ...]`
- `BUILTIN_BACKENDS: dict[str, PtyBackend]`
- `check_prerequisites(backend) -> list[str]`

**New signature this task introduces:**

- `class McpretentiousClient: __init__(self, backend_name: str = "mcpretentious")` — replaces the no-arg constructor

- [ ] **Step 1: Read the current `mcp_client.py:248` to know what you're changing**

Open `/Users/les/Projects/mahavishnu/mahavishnu/terminal/mcp_client.py`. Around line 240-260 you'll find:

```python
class McpretentiousClient:
    def __init__(self, ...) -> None:
        ...
        self._client = StdioMCPClient("uvx", ["--from", "mcpretentious", "mcpretentious"])
        ...
```

The exact lines and surrounding context are confirmed by the spec. **Do not** read the entire file — just the constructor.

- [ ] **Step 2: Write the failing regression test**

Open `tests/unit/terminal/mcp_client.py` (or create it if it doesn't exist). Add a new test class:

```python
"""Unit tests for mahavishnu.terminal.mcp_client."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.terminal.mcp_client import McpretentiousClient


class TestMcpretentiousClientLaunchesViaRegistry:
    """Regression tests: the original bug was using 'uvx' for an npm package.

    These tests pin the launch command so a future regression to 'uvx'
    would be caught immediately.
    """

    def test_default_backend_uses_npx_not_uvx(self) -> None:
        """The default 'mcpretentious' backend must be spawned via npx, not uvx."""
        with patch("mahavishnu.terminal.mcp_client.asyncio.create_subprocess_exec") as mock_exec:
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.stdout = MagicMock()
            mock_process.stderr = MagicMock()
            mock_exec.return_value = AsyncMock(return_value=mock_process)

            with patch(
                "mahavishnu.terminal.mcp_client.StdioMCPClient.start",
                new=AsyncMock(),
            ):
                client = McpretentiousClient()

            # First positional arg of create_subprocess_exec should be "npx", not "uvx".
            call_args = mock_exec.call_args
            self.assertIsNotNone(call_args, "create_subprocess_exec was not called")
            first_arg = call_args.args[0]
            self.assertEqual(
                first_arg, "npx",
                f"Expected npx for npm package, got {first_arg!r}. "
                "This is the original 'uvx on npm' regression.",
            )

    def test_explicit_backend_name_uses_registry(self) -> None:
        """Passing a name resolves through BUILTIN_BACKENDS, not hardcoded."""
        with patch("mahavishnu.terminal.mcp_client.asyncio.create_subprocess_exec") as mock_exec:
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.stdout = MagicMock()
            mock_process.stderr = MagicMock()
            mock_exec.return_value = AsyncMock(return_value=mock_process)

            with patch(
                "mahavishnu.terminal.mcp_client.StdioMCPClient.start",
                new=AsyncMock(),
            ):
                # Construct directly with the name; the resolved args should
                # match the registry entry, not a hardcoded launch.
                client = McpretentiousClient(backend_name="mcpretentious")

            call_args = mock_exec.call_args
            self.assertEqual(call_args.args[0], "npx")
            self.assertEqual(call_args.args[1], "mcpretentious")

    def test_unknown_backend_name_raises_keyerror(self) -> None:
        """Asking for a backend that doesn't exist should fail loud, not silently."""
        with pytest.raises(KeyError) as exc_info:
            McpretentiousClient(backend_name="definitely-not-a-real-backend")
        # KeyError should mention the bad name for debuggability.
        self.assertIn("definitely-not-a-real-backend", str(exc_info.value))
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/python -m pytest tests/unit/terminal/mcp_client.py -v
```

Expected: the three new tests FAIL. The first two will fail because the current code uses `uvx` (you can verify the assertion message names the bad value). The third will fail because the current `__init__` doesn't take a `backend_name` parameter.

- [ ] **Step 4: Modify `mcp_client.py` to use the registry**

In `/Users/les/Projects/mahavishnu/mahavishnu/terminal/mcp_client.py`, near the top of the file, add the import:

```python
from .backends import BUILTIN_BACKENDS, check_prerequisites
```

Then modify the `McpretentiousClient.__init__` method. The exact existing constructor (around line 240-260) should be replaced with:

```python
class McpretentiousClient:
    def __init__(
        self,
        backend_name: str = "mcpretentious",
    ) -> None:
        """Construct a McpretentiousClient.

        Args:
            backend_name: Key into BUILTIN_BACKENDS. Defaults to "mcpretentious".

        Raises:
            KeyError: If backend_name is not in BUILTIN_BACKENDS.
            ConfigurationError: If a required prerequisite is missing.
        """
        from ..core.errors import ConfigurationError

        if backend_name not in BUILTIN_BACKENDS:
            raise KeyError(
                f"Unknown PTY backend {backend_name!r}. "
                f"Available: {sorted(BUILTIN_BACKENDS.keys())}"
            )
        backend = BUILTIN_BACKENDS[backend_name]

        missing = check_prerequisites(backend)
        if missing:
            raise ConfigurationError(
                message=(
                    f"PTY backend {backend_name!r} requires {missing!r} on PATH "
                    f"but {'it was' if len(missing) == 1 else 'they were'} not found. "
                    f"Install: {_install_hint(missing)}"
                ),
                details={"backend": backend_name, "missing": missing},
            )

        self._client = StdioMCPClient(backend.command, list(backend.args))
        # Carry the backend for later reference (e.g., error messages, future tool_map use).
        self._backend = backend
```

And add the small `_install_hint` helper near the top of the file (just below the imports):

```python
def _install_hint(missing: list[str]) -> str:
    """Return a one-line install hint for the given missing prerequisites.

    Best-effort: covers the binaries we currently use. If a new requirement
    is added, fall back to a generic message.
    """
    hints = {
        "node": "brew install node  (or visit https://nodejs.org)",
        "uvx":  "pip install uv  (https://docs.astral.sh/uv/)",
    }
    parts = [hints.get(req, f"install {req}") for req in missing]
    return "; ".join(parts)
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/python -m pytest tests/unit/terminal/mcp_client.py -v
```

Expected: all three regression tests pass. The pre-existing tests in this file (if any) should still pass — the `backend_name` parameter has a default, so callers that don't pass it get the same behavior as before.

- [ ] **Step 6: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/terminal/mcp_client.py tests/unit/terminal/mcp_client.py
git commit -m "fix(terminal): use BUILTIN_BACKENDS for mcpretentious launch

The hardcoded 'uvx --from mcpretentious mcpretentious' is wrong: it is
an npm package, not a PyPI package. Replace with registry lookup that
resolves to 'npx mcpretentious'. Adds check_prerequisites() so a missing
'node' surfaces as ConfigurationError at construction instead of a
30s timeout per tool call.

Regression tests pin the launch command so this can't break silently.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

______________________________________________________________________

## Task 3: Pass `backend_name` from `manager.py` to `McpretentiousClient`

**Files:**

- Modify: `mahavishnu/terminal/manager.py` (the call site that constructs `McpretentiousClient`)

**Background:** In Task 2 we changed `McpretentiousClient.__init__` to take a `backend_name`. The default value `"mcpretentious"` preserves old behavior, but we want the manager to pass the user's `preference` through explicitly so the chain is: `settings.adapter_preference` → `manager` → `client`. This is the wiring task.

- [ ] **Step 1: Find the call site in `manager.py`**

Open `/Users/les/Projects/mahavishnu/mahavishnu/terminal/manager.py` and search for `McpretentiousClient` (case-insensitive). There should be exactly one instantiation site. It currently looks like:

```python
mcp_client = McpretentiousClient()
```

You'll find it inside the branch that handles `adapter_preference == "mcpretentious"`. Confirm this by reading the surrounding 5-10 lines (the variable holding the preference should be visible).

- [ ] **Step 2: Write a failing test for the wiring**

Open `tests/unit/terminal/test_manager.py` (create it if it doesn't exist). Add:

```python
"""Unit tests for mahavishnu.terminal.manager."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from mahavishnu.terminal.manager import TerminalManager


class TestManagerPassesPreferenceToClient:
    """The manager must thread the operator's preference through to the client."""

    def test_mcpretentious_preference_passes_name(self) -> None:
        # Build a minimal config that requests the mcpretentious adapter.
        from mahavishnu.terminal.config import TerminalConfig

        config = MagicMock()
        config.terminal = TerminalConfig(adapter_preference="mcpretentious")

        with patch("mahavishnu.terminal.manager.McpretentiousClient") as mock_client:
            mock_client.return_value = MagicMock()
            TerminalManager.create(config, mcp_client=None)

            # The manager should have constructed McpretentiousClient with
            # backend_name="mcpretentious" (the preference value).
            mock_client.assert_called_once()
            call_kwargs = mock_client.call_args.kwargs
            self.assertEqual(
                call_kwargs.get("backend_name"), "mcpretentious",
                f"Expected backend_name='mcpretentious' in {call_kwargs!r}",
            )
```

- [ ] **Step 3: Run the test to verify it fails**

Run:

```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/python -m pytest tests/unit/terminal/test_manager.py::TestManagerPassesPreferenceToClient -v
```

Expected: FAIL with "Expected backend_name='mcpretentious' in {}" — the current call has no `backend_name` kwarg.

- [ ] **Step 4: Update the call site in `manager.py`**

Change the single line:

```python
# BEFORE:
mcp_client = McpretentiousClient()

# AFTER:
mcp_client = McpretentiousClient(backend_name=preference)
```

`preference` is the local variable in the manager (you saw it in Step 1). Don't hardcode `"mcpretentious"` — pass the preference through so it works for any future backend the operator picks.

- [ ] **Step 5: Run the test to verify it passes**

Run:

```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/python -m pytest tests/unit/terminal/test_manager.py::TestManagerPassesPreferenceToClient -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/terminal/manager.py tests/unit/terminal/test_manager.py
git commit -m "feat(terminal): thread adapter_preference to McpretentiousClient

Manager now passes the operator's selected backend name to the client
constructor, so any registered backend (not just the hardcoded default)
can be selected via terminal.adapter_preference.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

______________________________________________________________________

## Task 4: Add gated integration smoke test

**Files:**

- Create: `tests/integration/terminal/test_mcpretentious_smoke.py`

**Purpose:** Real coverage when `MCPRETENTIOUS_INTEGRATION=1` is set (and npm + iTerm2 are present). Skipped silently otherwise. CI stays fast.

- [ ] **Step 1: Create the gated test file**

Create `tests/integration/terminal/test_mcpretentious_smoke.py`:

```python
"""Integration smoke test for the mcpretentious backend.

Gated by MCPRETENTIOUS_INTEGRATION=1. Skipped otherwise. This is the only
test that actually spawns a real MCPretentious subprocess and exercises
its tool surface; everything else is unit-level with mocks.
"""
from __future__ import annotations

import os
import shutil
import unittest


# Skip the whole module unless both the env var is set AND the prerequisites
# are present on PATH. This makes the test safe to run in any environment.
INTEGRATION_ENABLED = bool(os.environ.get("MCPRETENTIOUS_INTEGRATION"))
NODE_AVAILABLE = shutil.which("node") is not None
NPM_AVAILABLE = shutil.which("npm") is not None
SKIP_REASON = (
    "Set MCPRETENTIOUS_INTEGRATION=1 with node and npm on PATH to run."
)


@unittest.skipUnless(INTEGRATION_ENABLED and NODE_AVAILABLE and NPM_AVAILABLE, SKIP_REASON)
class TestMcpretentiousSmoke(unittest.IsolatedAsyncioTestCase):
    """End-to-end smoke against a real MCPretentious subprocess."""

    async def test_session_open_type_read_close(self) -> None:
        """Open a session, send 'echo hello', read the output, close."""
        from mahavishnu.terminal.mcp_client import McpretentiousClient

        # Pre-flight: confirm npm has mcpretentious installable.
        import subprocess
        result = subprocess.run(
            ["npm", "list", "-g", "mcpretentious"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            self.skipTest("mcpretentious not installed globally; run: npm install -g mcpretentious")

        # Spawn the client.
        client = McpretentiousClient(backend_name="mcpretentious")
        await client._client.start()  # type: ignore[attr-defined]

        try:
            # Open a session.
            session_id = await client._client.call_tool(  # type: ignore[attr-defined]
                "mcpretentious-open", {"columns": 120, "rows": 40},
            )
            self.assertIsNotNone(session_id)

            try:
                # Send a command and read the output.
                await client._client.call_tool(  # type: ignore[attr-defined]
                    "mcpretentious-type",
                    {"terminal_id": session_id, "input": ["echo hello", "enter"]},
                )
                # Read may take a moment; allow some time.
                output = await client._client.call_tool(  # type: ignore[attr-defined]
                    "mcpretentious-read", {"terminal_id": session_id, "limit_lines": 50},
                )
                self.assertIn("hello", str(output))
            finally:
                # Always close, even on failure.
                try:
                    await client._client.call_tool(  # type: ignore[attr-defined]
                        "mcpretentious-close", {"terminal_id": session_id},
                    )
                except Exception:
                    pass
        finally:
            # Stop the client subprocess.
            try:
                await client._client.stop()  # type: ignore[attr-defined]
            except Exception:
                pass
```

- [ ] **Step 2: Run the test to verify it SKIPS (not fails) by default**

Run:

```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/python -m pytest tests/integration/terminal/test_mcpretentious_smoke.py -v
```

Expected: `SKIPPED` (with reason "Set MCPRETENTIOUS_INTEGRATION=1 with node and npm on PATH to run."). Not a failure — the test is correctly gated.

- [ ] **Step 3: Run with the gate open (on a machine with MCPretentious installed)**

Run:

```bash
cd /Users/les/Projects/mahavishnu
MCPRETENTIOUS_INTEGRATION=1 .venv/bin/python -m pytest tests/integration/terminal/test_mcpretentious_smoke.py -v
```

Expected: PASS (1 test). If it fails with a clear error about missing `mcpretentious` package, install it: `npm install -g mcpretentious`, then re-run.

- [ ] **Step 4: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add tests/integration/terminal/test_mcpretentious_smoke.py
git commit -m "test(terminal): gated integration smoke for mcpretentious

Runs only when MCPRETENTIOUS_INTEGRATION=1 AND node AND npm are on PATH.
CI stays fast. Operators who want real coverage can run with the gate open.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

______________________________________________________________________

## Task 5: Operator documentation

**Files:**

- Create: `docs/terminal/backends.md`

**Purpose:** Operators need to know what backends are available, what their prerequisites are, and how to switch. The spec says these belong in `docs/terminal/backends.md`; this task writes that file.

- [ ] **Step 1: Create the doc file**

Create `docs/terminal/backends.md`:

````markdown
# PTY Toolserver Backends

Mahavishnu's pool workers run user commands in a PTY session managed by
an external MCP toolserver. The terminal adapter system supports multiple
backends; you pick one by name via `terminal.adapter_preference` in your
settings.

## Available backends

| Name | Command | Prerequisites | Notes |
|------|---------|---------------|-------|
| `mcpretentious` | `npx mcpretentious` | `node` (>=18) | Full-featured. iTerm2 backend (macOS, needs iTerm2 Python API enabled) or tmux backend (cross-platform). |
| `pty_mcp_python` | `uvx --from luqm4nx-pty-mcp-server-python pty-mcp-server-python` | `uvx` | Pure-Python alternative. Same tool shape. |

## Choosing a backend

```yaml
# settings/mahavishnu.yaml (or settings/local.yaml)
terminal:
  adapter_preference: "mcpretentious"   # or "pty_mcp_python" or "iterm2" or "crow" or "mock"
```

If the requested backend's prerequisites are missing, Mahavishnu fails
at startup with a clear `ConfigurationError` like:

```
PTY backend 'mcpretentious' requires 'node' on PATH but it was not found.
Install: brew install node  (or visit https://nodejs.org)
```

This is intentional — silent fallback to `mock` would hide the
misconfiguration.

## Adding a new backend

Built-in backends live in `mahavishnu/terminal/backends.py`. To add
another, append a `PtyBackend` entry to `BUILTIN_BACKENDS`:

```python
"my_backend": PtyBackend(
    name="my_backend",
    command="my-launcher",
    args=("arg1", "arg2"),
    tool_map={},            # if tool names match, leave empty; otherwise alias them
    requires=("dep1",),     # binaries that must be on PATH
)
```

If your backend's MCP tools don't match `mcpretentious-open` / `-type` /
`-read` / `-close` / `-list` (the names `McpretentiousAdapter` calls),
either write a thin adapter shim, or populate `tool_map` with
`{"mcpretentious_open": "your_open_tool_name", ...}`.

This is a code change (one entry in a dict) — not a config change.
We don't expose per-backend config in settings to keep the test
matrix small and the failure modes clear.

## Verifying your backend is reachable

After setting `terminal.adapter_preference`, run:

```bash
mahavishnu mcp start --verbose 2>&1 | head -50
```

Look for one of:

- `Using mcpretentious adapter` — backend spawned successfully
- `ConfigurationError: PTY backend 'mcpretentious' requires 'node'...` — install the prerequisite
- `ConfigurationError: Unknown PTY backend 'foo'...` — check spelling in settings
````

- [ ] **Step 2: Verify the doc renders cleanly**

Read it back to make sure the table is well-formed and the examples are accurate (you'll be re-reading the registry entry you wrote in Task 1).

- [ ] **Step 3: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add docs/terminal/backends.md
git commit -m "docs(terminal): document built-in PTY backends

Covers the two built-ins (mcpretentious, pty_mcp_python), how to switch
via terminal.adapter_preference, the prerequisite check that fails loud,
and how to add a new backend by editing backends.py.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

______________________________________________________________________

## Task 6: End-to-end manual smoke test (checklist, no code)

**Purpose:** A final cross-check on a real machine. This isn't automated — it's a checklist the operator (or you) runs after Tasks 1-5 are merged. Document the result in a commit message.

- [ ] **Step 1: Run the full test suite to confirm nothing else broke**

```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/python -m pytest tests/unit/terminal/ -v
```

Expected: all unit tests pass, integration test is skipped.

- [ ] **Step 2: Start Mahavishnu with each backend, confirm it boots**

For `mcpretentious`:

```bash
# In a settings/local.yaml or via override:
#   terminal:
#     adapter_preference: "mcpretentious"
mahavishnu mcp start --verbose 2>&1 | head -20
```

Expected: starts, logs include something about mcpretentious, no `ConfigurationError`.

For `pty_mcp_python` (if you have `uvx`):

```bash
# Switch terminal.adapter_preference to "pty_mcp_python", restart
mahavishnu mcp start --verbose 2>&1 | head -20
```

Expected: starts, no `ConfigurationError`.

- [ ] **Step 3: Run a pool task to confirm end-to-end works**

```bash
# In a Mahavishnu-using project:
python -m crackerjack run -v -p patch
```

Expected: completes without "Keyring token format appears invalid" or other auth errors. (The publish itself may succeed or fail based on the actual package state — that's fine. The point is no auth-bootstrap error.)

- [ ] **Step 4: Verify the prerequisite failure path is loud**

```bash
# Temporarily hide 'node' from PATH and try to start with mcpretentious:
PATH=/usr/bin:/bin mahavishnu mcp start --verbose 2>&1 | head -10
```

Expected: `ConfigurationError: PTY backend 'mcpretentious' requires 'node' on PATH but it was not found. Install: brew install node...`

- [ ] **Step 5: Commit a smoke-test summary**

If you ran the manual smoke, commit a record of the result. If you didn't, skip this step.

```bash
cd /Users/les/Projects/mahavishnu
# Replace the message with the actual result.
git commit --allow-empty -m "chore: smoke test multi-backend PTY

Verified by hand on 2026-07-14:
- mcpretentious: boots, no errors
- pty_mcp_python: skipped (uvx not installed on smoke machine)
- crackerjack run -p patch: completes
- prereq failure (PATH=/usr/bin): loud ConfigurationError, as expected

Co-Authored-By: Claude <noreply@anthropic.com>"
```

______________________________________________________________________

## Self-review

- **Spec coverage**: Architecture, components, data flow, error handling, testing, implementation order — all addressed across the 6 tasks.
- **Placeholders**: None. Every step has actual code or actual commands.
- **Type consistency**: `PtyBackend`, `BUILTIN_BACKENDS`, `check_prerequisites()` are defined in Task 1 and used unchanged in Tasks 2 and 3. `McpretentiousClient(backend_name=...)` is the new signature, used in Tasks 2, 3, 4.
- **Frequent commits**: 6 commits total (one per task + the optional smoke record). Each commit has a single coherent purpose.
- **TDD discipline**: Tasks 1, 2, 3 each follow write-fail-fix-pass-commit. Task 4 is a gated scaffold (skipping is the expected first run). Task 5 is documentation.
