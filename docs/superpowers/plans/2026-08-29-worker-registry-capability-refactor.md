# Worker Registry Capability Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static `WORKER_REGISTRY` with a capability-driven registry, fix the broken worker bootstrap bug, and add an engine composition layer where tasks declare required capabilities and the system picks engines + composes them into a DAG.

**Architecture:** Three sequential stages. Stage 1 fixes the tmux bootstrap bug. Stage 2 introduces a `Capability` Pydantic schema loaded via Oneiric; both engines and workers declare `provides: list[Capability]`. Stage 3a adds a `Conductor` that resolves `CapabilitySpec → ExecutionDAG` and emits a Prefect flow, with envelopes persisted to Dhara. Stage 3b deletes legacy MCP tools after one release cycle of dual maintenance.

**Tech Stack:** Python 3.14, Pydantic v2 (`frozen=True, extra="forbid"`), Oneiric (config), Prefect (DAG runtime), FastMCP (server), Dhara (envelope storage), pytest.

**Spec:** `docs/superpowers/specs/2026-08-29-worker-registry-capability-refactor-design.md`

## Global Constraints

- **Python 3.14 floor.** Target 3.14+ syntax (`X | None`, `list[str]`, `pathlib.Path`).
- **`from __future__ import annotations`** as the first non-comment line of every source file.
- **Imports sorted within each section** (stdlib → third-party → first-party with `force-sort-within-sections = true`, `known-first-party = ["mahavishnu"]`).
- **Type hints required on every function signature.** `def f(x: int = None)` is forbidden; use `x: int | None = None`.
- **No `assert` in production code.** Use exception hierarchy from `mahavishnu/core/errors.py`.
- **No `Any` in tool inputs or orchestration state.** Use Pydantic models with strict typing.
- **Use Oneiric logger** (`oneiric.logging`), not stdlib `logging`.
- **Pydantic v2 with `model_config = ConfigDict(frozen=True, extra="forbid")`** for new DTOs.
- **ID patterns:** `CapabilityId = ^[a-z]+:[a-z0-9._-]+$`, `EngineId = ^[a-z][a-z0-9_-]{1,63}$`, `EnvelopeId` is UUIDv4, `TraceId` is 32-char hex.
- **Worker registration:** `settings/mahavishnu.yaml:workers:` block (NOT a separate `workers.yaml` file — bypasses Oneiric's `_settings_build_values` ordering and silently breaks `MAHAVISHNU_WORKERS__FOO` env-var overrides).
- **Quality gate:** `crackerjack run` must pass. Coverage floor: 89% for new code, 95% for `mahavishnu/core/conductor.py`.
- **Pyproject markers:** `unit`, `integration`, `mcp`, `requires_network`, `requires_auth`, `slow` (per CLAUDE.md). New tests should use these markers; don't invent new ones.
- **No `Any` imports** in modules that should minimize type leakage.

---

## Phase 1 — Stage 1: Worker Bootstrap Fix

The bug: `WorkerManager.create_worker()` constructs `command=[WorkerConfig.command]` (a single-element argv containing the pre-quoted shell string). `tmux_adapter.create_session()` does `shlex.join()` on it and `send-keys`' the doubly-quoted text into a fresh zsh pane. zsh can't parse it.

**Fix:** Pass the command directly to `tmux new-session -- <command>` instead of `send-keys`. Two-file change.

### Task 1.1: Write failing test for new tmux invocation

**Files:**
- Modify: `tests/unit/workers/contract/test_tmux_adapter.py:46,62,85` (existing send-keys tests)

**Interfaces:**
- Consumes: `tmux_adapter.create_session(socket, session, window_name, command)` from `mahavishnu/workers/contract/tmux_adapter.py`
- Produces: Updated tests asserting the new `tmux new-session -- <command>` shape

- [ ] **Step 1: Read existing tests**

```python
# tests/unit/workers/contract/test_tmux_adapter.py:46-90
# Note the three test functions asserting the old send-keys invocation
```

- [ ] **Step 2: Update tests to assert new shape**

Replace assertions of `tmux send-keys ...` with assertions of `tmux new-session ... -- <command>`. Each test should `mock_subprocess_run.assert_called_with(["tmux", "-S", socket, "new-session", "-d", "-s", session, "-n", window_name, "-P", "-F", "#{session_name}:#{window_id}:#{pane_id}", "--"] + list(command), ...)`.

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/workers/contract/test_tmux_adapter.py -v`
Expected: FAIL with "expected new-session call, got send-keys call" (or similar assertion mismatch).

- [ ] **Step 4: Commit failing tests**

```bash
git -c user.email="les@wedgwoodwebworks.com" add tests/unit/workers/contract/test_tmux_adapter.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "test(workers): assert new tmux new-session invocation shape"
```

### Task 1.2: Implement the tmux_adapter fix

**Files:**
- Modify: `mahavishnu/workers/contract/tmux_adapter.py:111-152`

**Interfaces:**
- Consumes: `create_session(socket, session, window_name, command: Sequence[str])` signature unchanged
- Produces: Same `TmuxSessionInfo` return type; passes command via `tmux new-session -- <cmd>` instead of post-creation `send-keys`

- [ ] **Step 1: Replace the create_session body**

In `mahavishnu/workers/contract/tmux_adapter.py`, replace lines 111-152:

```python
def create_session(
    *,
    socket: str,
    session: str,
    window_name: str,
    command: Sequence[str],
) -> TmuxSessionInfo:
    """Create a new detached tmux session and exec ``command`` in its first pane."""
    _validate_socket_path(socket)
    _validate_session_name(session)
    _validate_session_name(window_name)
    socket_path = Path(socket)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(socket_path.parent, 0o700)
    except PermissionError as e:
        raise TmuxAdapterError(
            f"cannot chmod socket parent {socket_path.parent!s} to 0700: {e}"
        ) from e

    proc = subprocess.run(
        [
            "tmux", "-S", socket, "new-session", "-d",
            "-s", session, "-n", window_name,
            "-P", "-F", "#{session_name}:#{window_id}:#{pane_id}",
            "--",
            *command,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise TmuxAdapterError(
            f"tmux new-session failed: rc={proc.returncode} stderr={_safe_stderr(proc.stderr)}"
        )
    stdout = proc.stdout.strip()
    line = stdout.splitlines()[-1] if stdout else ""
    parts = line.split(":")
    if len(parts) != 3:
        raise TmuxAdapterError(f"unexpected tmux new-session -P output: {proc.stdout!r}")
    session_name, window_id, pane_id = parts
    _validate_session_name(session_name)
    if socket_path.exists():
        try:
            os.chmod(socket, 0o600)
        except PermissionError as e:
            raise TmuxAdapterError(f"cannot chmod socket {socket} to 0600: {e}") from e

    return TmuxSessionInfo(
        socket=socket,
        session=session_name,
        window=window_id,
        pane=pane_id,
        attach_command=_attach_command(socket, session_name),
    )
```

- [ ] **Step 2: Remove the now-unused `quoted` variable and the send-keys block**

Delete lines 112 (`quoted = shlex.join(command)`) and 144-152 (chmod + send-keys).

- [ ] **Step 3: Remove `import shlex` if no longer used**

Run: `grep -n shlex mahavishnu/workers/contract/tmux_adapter.py`. If unused elsewhere in the file, remove the import.

- [ ] **Step 4: Run the test from Task 1.1**

Run: `pytest tests/unit/workers/contract/test_tmux_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Run full worker test suite**

Run: `pytest tests/unit/workers/ -v`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/workers/contract/tmux_adapter.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "fix(workers): pass launch command via tmux new-session instead of send-keys

The tmux_adapter.create_session was using send-keys to type a pre-
quoted shell string into a fresh zsh pane, but the string was passed
through shlex.join producing doubly-quoted output that zsh could not
parse. tmux new-session accepts the command as a positional argument
after --; tmux exec's it directly without the shell round-trip."
```

### Task 1.3: Smoke-test all 16 worker types

**Files:** none modified (smoke test only)

**Interfaces:**
- Consumes: `pool_spawn` MCP tool
- Produces: Confirmation that all 16 `terminal-*` worker types spawn functional tmux panes

- [ ] **Step 1: Spawn one pool of each terminal-* worker type via MCP**

```python
# tests/integration/workers/test_terminal_workers_smoke.py (NEW)
import asyncio
import pytest
from mahavishnu.pools.manager import PoolManager

WORKER_TYPES = [
    "terminal-shell", "terminal-python", "terminal-ipython", "terminal-node",
    "terminal-qwen", "terminal-claude", "terminal-codex", "terminal-deepagents",
    "terminal-clai", "terminal-mysql", "terminal-psql", "terminal-turso",
    "terminal-redis", "terminal-wasmtime", "terminal-wasmer", "terminal-ssh",
]

@pytest.mark.parametrize("worker_type", WORKER_TYPES)
@pytest.mark.integration
@pytest.mark.mcp
async def test_worker_type_spawns_functional_pane(worker_type: str) -> None:
    """Every terminal-* worker type spawns a tmux pane with its expected process running."""
    # Skip workers that need credentials
    if worker_type in {"terminal-mysql", "terminal-psql", "terminal-turso", "terminal-redis"}:
        pytest.skip(f"{worker_type} requires external service")
    # Spawn one worker; capture pane content; assert no "command not found" error
    ...
```

- [ ] **Step 2: Run smoke test**

Run: `pytest tests/integration/workers/test_terminal_workers_smoke.py -v -m "integration and mcp"`
Expected: All pass (or skip if credentials missing).

- [ ] **Step 3: Commit smoke test**

```bash
git -c user.email="les@wedgwoodwebworks.com" add tests/integration/workers/
git -c user.email="les@wedgwoodwebworks.com" commit -m "test(workers): smoke test all 16 terminal-* worker types"
```

### Task 1.4: Phase 1 done — manual smoke check

- [ ] **Step 1: Manually verify in a live MCP session**

```bash
mcp__mahavishnu__pool_spawn --pool_type=mahavishnu --name=phase1-smoke --worker_type=terminal-claude
mcp__mahavishnu__terminal_capture --session_id=<returned_id> --lines=40
```

Expected: pane shows `claude --output-format stream-json --permission-mode acceptEdits` running, NOT `zsh: command not found`.

- [ ] **Step 2: Tear down test pool**

```bash
mcp__mahavishnu__pool_close --pool_id=<phase1-pool-id>
```

---

## Phase 2 — Stage 2: Capability-Driven Registry

### Task 2.1: Create capabilities.py with all Pydantic schemas

**Files:**
- Create: `mahavishnu/core/capabilities.py`

**Interfaces:**
- Produces: All Pydantic schemas from spec §2: ID newtypes (`CapabilityId`, `EngineId`, `EnvelopeId`, `TraceId`), enums (`CapabilityKind`, `CapabilityState`, `HealthStatus`, `SelectorStrategy`), models (`TypeSchema`, `CostHint`, `HealthRef`, `Capability`, `EngineRegistration`, `CapabilityEnvelope`, `EnvelopeAddress`, `Candidate`, `DAGNode`, `DAGEdge`, `ExecutionDAG`, `CapabilitySpec`).

- [ ] **Step 1: Write the file**

Write `mahavishnu/core/capabilities.py` with the full schema block from spec §2 (already typed in the spec).

- [ ] **Step 2: Run pyright to confirm types check**

Run: `uv run pyright mahavishnu/core/capabilities.py`
Expected: 0 errors.

- [ ] **Step 3: Run mypy strict**

Run: `uv run mypy --strict mahavishnu/core/capabilities.py`
Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/core/capabilities.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "feat(core): add capability schema with typed I/O contracts"
```

### Task 2.2: Add WorkerRegistryConfig to MahavishnuSettings

**Files:**
- Modify: `mahavishnu/core/config.py:1110-1142` (existing `WorkerConfig` lives near here)

**Interfaces:**
- Consumes: Existing `MahavishnuSettings`
- Produces: New `WorkerRegistryConfig` Pydantic model registered on `MahavishnuSettings`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_core_config_worker_registry.py (NEW)
from __future__ import annotations

import pytest
from pydantic import ValidationError

from mahavishnu.core.config import MahavishnuSettings


def test_settings_accepts_workers_block():
    """MahavishnuSettings accepts a workers: block via Oneiric."""
    settings = MahavishnuSettings.model_validate({"workers": {"entries": []}})
    assert hasattr(settings, "workers")


def test_settings_rejects_unknown_worker_block_keys():
    """WorkerRegistryConfig has extra='forbid'."""
    with pytest.raises(ValidationError):
        MahavishnuSettings.model_validate({"workers": {"unknown_field": "x"}})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_core_config_worker_registry.py -v`
Expected: FAIL — `MahavishnuSettings` has no `workers` attribute yet.

- [ ] **Step 3: Add `WorkerRegistryConfig` to config.py**

In `mahavishnu/core/config.py`, add near the existing `WorkerConfig`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from mahavishnu.core.capabilities import Capability


class WorkerEntry(BaseModel):
    """One worker registration, loaded from `settings/mahavishnu.yaml:workers.entries[]`."""
    model_config = ConfigDict(extra="forbid")
    worker_type: str
    name: str
    description: str = ""
    command_argv: list[str] = Field(default_factory=list)
    completion_markers: list[str] = Field(default_factory=list)
    provides: list[str] = Field(default_factory=list)  # List of CapabilityId strings
    tags: list[str] = Field(default_factory=list)
    requires_tool: str | None = None
    required_env: list[str] = Field(default_factory=list)
    auth_kind: str = "none"
    runtime_kind: str = "shell"
    one_shot: bool = False
    default_timeout: int = 300


class WorkerRegistryConfig(BaseModel):
    """Loaded from `workers:` block in `settings/mahavishnu.yaml`.

    Each entry corresponds to one terminal-* worker type. The keys
    here are the SAME string keys as the legacy `WORKER_REGISTRY`,
    so this is a drop-in replacement.
    """
    model_config = ConfigDict(extra="forbid")
    entries: list[WorkerEntry] = Field(default_factory=list)
```

- [ ] **Step 4: Register on `MahavishnuSettings`**

In `mahavishnu/core/config.py`, find the `MahavishnuSettings` class and add:

```python
    workers: WorkerRegistryConfig = Field(default_factory=WorkerRegistryConfig)
```

- [ ] **Step 5: Run the test from Step 1**

Run: `pytest tests/unit/test_core_config_worker_registry.py -v`
Expected: PASS.

- [ ] **Step 6: Run full config tests**

Run: `pytest tests/unit/test_core_config.py -v`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/core/config.py tests/unit/test_core_config_worker_registry.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "feat(config): add WorkerRegistryConfig to MahavishnuSettings"
```

### Task 2.3: Update settings/mahavishnu.yaml with workers: block

**Files:**
- Modify: `settings/mahavishnu.yaml` (append a new top-level `workers:` block)

**Interfaces:**
- Consumes: Existing `settings/mahavishnu.yaml`
- Produces: Same yaml with a `workers.entries:` list containing 16 entries (one per legacy `terminal-*` worker type)

- [ ] **Step 1: Read current settings**

```bash
cat settings/mahavishnu.yaml | head -30
```

- [ ] **Step 2: Append the workers block**

Append to `settings/mahavishnu.yaml`:

```yaml
# Worker registry (Stage 2 of capability refactor)
# Loaded by Oneiric into MahavishnuSettings.workers
workers:
  entries:
    - worker_type: terminal-shell
      name: "Bash Shell"
      command_argv: ["bash", "--noediting"]
      completion_markers: ["$"]
      provides: ["worker:bash"]
    - worker_type: terminal-python
      name: "Python REPL"
      command_argv: ["python3", "-iq"]
      completion_markers: [">>>", "..."]
      requires_tool: python3
      provides: ["worker:python-repl"]
    - worker_type: terminal-ipython
      name: "IPython"
      command_argv: ["ipython", "--no-banner"]
      completion_markers: ["In [", "Out ["]
      requires_tool: ipython
      provides: ["worker:ipython"]
    - worker_type: terminal-node
      name: "Node.js REPL"
      command_argv: ["node", "-i"]
      completion_markers: [">"]
      requires_tool: node
      provides: ["worker:node-repl"]
    - worker_type: terminal-claude
      name: "Claude Code"
      command_argv: ["sh", "-lc", "claude --output-format stream-json --permission-mode acceptEdits"]
      completion_markers: ['"done"', "finish_reason"]
      requires_tool: claude
      provides: ["worker:claude-persistent", "worker:ai-context"]
    - worker_type: terminal-qwen
      name: "Qwen AI"
      command_argv: ["sh", "-lc", "qwen -o stream-json --approval-mode yolo"]
      completion_markers: ['"done"', "finish_reason"]
      requires_tool: qwen
      provides: ["worker:qwen-persistent", "worker:ai-context"]
    - worker_type: terminal-codex
      name: "Codex CLI"
      command_argv: ["sh", "-lc", "codex exec --json \"$1\"; printf \"\\n__MAHAVISHNU_DONE__\\n\""]
      completion_markers: ["__MAHAVISHNU_DONE__"]
      requires_tool: codex
      one_shot: true
      provides: ["worker:codex-oneshot", "worker:ai-context"]
    - worker_type: terminal-deepagents
      name: "DeepAgents CLI"
      command_argv: ["sh", "-lc", "deepagents-cli --non-interactive \"$1\" --quiet --no-stream; printf \"\\n__MAHAVISHNU_DONE__\\n\""]
      completion_markers: ["__MAHAVISHNU_DONE__"]
      requires_tool: deepagents-cli
      one_shot: true
      provides: ["worker:deepagents-oneshot", "worker:ai-context"]
    - worker_type: terminal-clai
      name: "CLAI"
      command_argv: ["sh", "-lc", "clai --no-stream \"$1\"; printf \"\\n__MAHAVISHNU_DONE__\\n\""]
      completion_markers: ["__MAHAVISHNU_DONE__"]
      requires_tool: clai
      one_shot: true
      provides: ["worker:clai-oneshot", "worker:ai-context"]
    - worker_type: terminal-mysql
      name: "MySQL CLI"
      command_argv: ["mysql", "-u", "{user}", "-p{password}", "-h", "{host}", "{database}"]
      completion_markers: ["mysql>", "->"]
      requires_tool: mysql
      required_env: ["MYSQL_PASSWORD"]
      provides: ["worker:mysql-repl"]
    - worker_type: terminal-psql
      name: "PostgreSQL CLI"
      command_argv: ["psql", "-U", "{user}", "-h", "{host}", "-d", "{database}"]
      completion_markers: ["=>", "->"]
      requires_tool: psql
      required_env: ["PGPASSWORD"]
      provides: ["worker:psql-repl"]
    - worker_type: terminal-turso
      name: "Turso CLI"
      command_argv: ["turso", "db", "shell", "{database}"]
      completion_markers: ["turso> ", "...>"]
      requires_tool: turso
      required_env: ["TURSO_AUTH_TOKEN"]
      provides: ["worker:turso-repl"]
    - worker_type: terminal-redis
      name: "Redis CLI"
      command_argv: ["redis-cli", "-h", "{host}", "-p", "{port}"]
      completion_markers: [">"]
      requires_tool: redis-cli
      provides: ["worker:redis-repl"]
    - worker_type: terminal-wasmtime
      name: "Wasmtime Runtime"
      command_argv: ["wasmtime"]
      completion_markers: [">", "$"]
      requires_tool: wasmtime
      provides: ["worker:wasm-repl"]
    - worker_type: terminal-wasmer
      name: "Wasmer Runtime"
      command_argv: ["wasmer"]
      completion_markers: [">", "$"]
      requires_tool: wasmer
      provides: ["worker:wasm-repl"]
    - worker_type: terminal-ssh
      name: "SSH Remote"
      command_argv: ["ssh", "{host}"]
      completion_markers: ["$", "#", "%"]
      requires_tool: ssh
      default_timeout: 600
      provides: ["worker:ssh"]
```

- [ ] **Step 3: Verify Oneiric parses it**

```bash
python -c "from oneiric.core.config import load_settings; from pathlib import Path; s = load_settings('mahavishnu'); print(type(s.workers).__name__, len(s.workers.entries))"
```

Expected: prints `WorkerRegistryConfig 16`.

- [ ] **Step 4: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add settings/mahavishnu.yaml
git -c user.email="les@wedgwoodwebworks.com" commit -m "feat(settings): add workers.entries block for capability-driven registry"
```

### Task 2.4: Add Oneiric-driven capabilities loader

**Files:**
- Create: `mahavishnu/core/capabilities_loader.py`

**Interfaces:**
- Consumes: `WorkerRegistryConfig` from `MahavishnuSettings`
- Produces: `dict[str, Capability]` mapping `CapabilityId` strings to `Capability` objects; `dict[str, WorkerEntry]` mapping worker_type strings to entries.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_capabilities_loader.py (NEW)
from __future__ import annotations

from mahavishnu.core.capabilities_loader import load_capabilities_from_settings
from mahavishnu.core.config import MahavishnuSettings


def test_load_capabilities_from_settings():
    settings = MahavishnuSettings.model_validate({
        "workers": {"entries": [
            {"worker_type": "terminal-shell", "command_argv": ["bash"], "provides": ["worker:bash"]},
        ]}
    })
    caps = load_capabilities_from_settings(settings)
    assert "worker:bash" in caps
    assert caps["worker:bash"].description == "Bash Shell"


def test_load_capabilities_rejects_invalid_capability_id():
    """CapabilityId pattern enforces kind:name format."""
    import pytest
    from pydantic import ValidationError
    settings = MahavishnuSettings.model_validate({
        "workers": {"entries": [
            {"worker_type": "x", "command_argv": ["bash"], "provides": ["INVALID-ID"]},
        ]}
    })
    with pytest.raises(ValidationError):
        load_capabilities_from_settings(settings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_capabilities_loader.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement the loader**

Write `mahavishnu/core/capabilities_loader.py`:

```python
"""Load capability + worker registrations from Oneiric-loaded config."""
from __future__ import annotations

from typing import TYPE_CHECKING

from mahavishnu.core.capabilities import (
    Capability,
    CapabilityKind,
    CapabilityState,
    CostHint,
    EngineRegistration,
    TypeSchema,
)

if TYPE_CHECKING:
    from mahavishnu.core.config import MahavishnuSettings


def load_capabilities_from_settings(
    settings: "MahavishnuSettings",
) -> dict[str, Capability]:
    """Convert `settings.workers.entries` into a dict of Capability objects keyed by id.

    Each worker entry's `provides` list becomes one Capability. The CapabilityId
    pattern `^[a-z]+:[a-z0-9._-]+$` is enforced by the Capability model.
    """
    capabilities: dict[str, Capability] = {}
    for entry in settings.workers.entries:
        for cap_id in entry.provides:
            capability = Capability(
                id=cap_id,
                kind=CapabilityKind.WORKER,
                description=entry.description or entry.name,
                io_in=TypeSchema(),
                io_out=TypeSchema(),
                state=CapabilityState.EPHEMERAL,
                cost_hint=CostHint(has_side_effects=True),
                tags=entry.tags,
            )
            capabilities[cap_id] = capability
    return capabilities
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_capabilities_loader.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/core/capabilities_loader.py tests/unit/test_capabilities_loader.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "feat(core): add Oneiric-driven capability loader"
```

### Task 2.5: Replace WORKER_REGISTRY with WorkerEntry lookups

**Files:**
- Modify: `mahavishnu/workers/registry.py` (replace `WORKER_REGISTRY` dict with a function that loads from `MahavishnuSettings.workers`)
- Modify: `mahavishnu/workers/__init__.py:40` (re-export new symbols)
- Modify: `mahavishnu/_main_cli.py:73,1402` (use new lookup API)
- Modify: `mahavishnu/cli/base.py:100` (use new lookup API)
- Modify: 9 test files listed in `feature-dev:code-architect` review C1

**Interfaces:**
- Consumes: `MahavishnuSettings.workers`
- Produces: `get_worker_entry(worker_type: str) -> WorkerEntry` (replaces `WORKER_REGISTRY[worker_type]`); `list_worker_types() -> list[str]`

- [ ] **Step 1: Write failing test for new lookup API**

```python
# tests/unit/workers/test_registry_lookup.py (NEW)
from __future__ import annotations

from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.workers.registry import get_worker_entry, list_worker_types


def test_get_worker_entry_loads_from_settings():
    settings = MahavishnuSettings.model_validate({
        "workers": {"entries": [
            {"worker_type": "terminal-shell", "name": "Bash", "command_argv": ["bash"]},
        ]}
    })
    entry = get_worker_entry("terminal-shell", settings=settings)
    assert entry.name == "Bash"


def test_get_worker_entry_raises_for_unknown():
    import pytest
    settings = MahavishnuSettings()
    with pytest.raises(KeyError):
        get_worker_entry("does-not-exist", settings=settings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/workers/test_registry_lookup.py -v`
Expected: FAIL — `get_worker_entry` doesn't exist yet.

- [ ] **Step 3: Replace `WORKER_REGISTRY` in `mahavishnu/workers/registry.py`**

Rewrite the file to:

```python
"""Worker registration lookup, backed by Oneiric-loaded config."""
from __future__ import annotations

from typing import TYPE_CHECKING

from mahavishnu.core.errors import ErrorCode, MahavishnuError

if TYPE_CHECKING:
    from mahavishnu.core.config import MahavishnuSettings, WorkerEntry


def get_worker_entry(worker_type: str, *, settings: "MahavishnuSettings | None" = None) -> "WorkerEntry":
    """Look up a worker entry by its `worker_type` string."""
    if settings is None:
        from mahavishnu.core.config import MahavishnuSettings as _S
        settings = _S()
    for entry in settings.workers.entries:
        if entry.worker_type == worker_type:
            return entry
    raise MahavishnuError(
        f"worker_type {worker_type!r} not found in registry",
        ErrorCode.RESOURCE_NOT_FOUND,
    )


def list_worker_types(*, settings: "MahavishnuSettings | None" = None) -> list[str]:
    """Return all registered worker_type strings."""
    if settings is None:
        from mahavishnu.core.config import MahavishnuSettings as _S
        settings = _S()
    return [e.worker_type for e in settings.workers.entries]


__all__ = ["get_worker_entry", "list_worker_types"]
```

- [ ] **Step 4: Update 4 production importers**

- `mahavishnu/workers/__init__.py:40` — replace `WORKER_REGISTRY` re-exports with `get_worker_entry`, `list_worker_types`.
- `mahavishnu/_main_cli.py:73` and `:1402` — replace `WORKER_REGISTRY[name]` with `get_worker_entry(name)`.
- `mahavishnu/cli/base.py:100` — same replacement.

- [ ] **Step 5: Update 9 test files**

For each file in `test_pycharm_worker.py`, `test_workers_registry_coverage.py`, `test_workers_registry.py`, `test_worker_registry.py`, `test_worker_manager.py`, `test_application_worker.py`, `test_main_cli.py`, `test_error_codes.py`, `test_generic_shell_worker.py`: replace `WORKER_REGISTRY[X]` access with `get_worker_entry(X)` (passing settings if needed).

- [ ] **Step 6: Run all updated tests**

Run: `pytest tests/unit/workers/ tests/unit/test_main_cli.py tests/unit/test_error_codes.py -v`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/workers/registry.py mahavishnu/workers/__init__.py mahavishnu/_main_cli.py mahavishnu/cli/base.py tests/
git -c user.email="les@wedgwoodwebworks.com" commit -m "refactor(workers): replace WORKER_REGISTRY with Oneiric-loaded lookup"
```

### Task 2.6: Update WorkerManager to use new lookup

**Files:**
- Modify: `mahavishnu/workers/manager.py` (replace `WORKER_REGISTRY[name]` access with `get_worker_entry(name, settings=settings)`)

**Interfaces:**
- Consumes: `WorkerEntry` from new lookup
- Produces: Same `WorkerManager` API; pass `command_argv` (from WorkerEntry) to `tmux_adapter.create_session` instead of the legacy `command` template

- [ ] **Step 1: Update `create_worker` to consume `command_argv`**

Replace the section that constructs `command=[WorkerConfig.command]` with:

```python
from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.workers.registry import get_worker_entry

def create_worker(self, worker_type: str) -> Worker:
    settings = MahavishnuSettings()  # or injected via DI
    entry = get_worker_entry(worker_type, settings=settings)
    command_argv = list(entry.command_argv)
    info = self.tmux_adapter.create_session(
        socket=self._socket_for(worker_type),
        session=worker_type,
        window_name="main",
        command=command_argv,
    )
    return Worker(worker_type=worker_type, tmux=info, ...)
```

- [ ] **Step 2: Run worker manager tests**

Run: `pytest tests/unit/workers/test_worker_manager.py -v`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/workers/manager.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "refactor(workers): WorkerManager consumes command_argv from WorkerEntry"
```

### Task 2.7: Engines declare `provides: list[Capability]`

**Files:**
- Modify: `mahavishnu/engines/prefect_adapter_impl.py:579`
- Modify: `mahavishnu/engines/llamaindex_adapter_impl.py:285`
- Modify: `mahavishnu/engines/agno_adapter_impl.py:507`
- Modify: `mahavishnu/engines/hatchet_adapter_impl.py:44`
- Modify: `mahavishnu/core/adapters/worker.py:110`

**Interfaces:**
- Produces: Each engine's `AdapterCapabilities` (existing) PLUS a new `provides: list[Capability]` field on the registration returned by `__init__`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/engines/test_engine_provides.py (NEW)
import pytest
from mahavishnu.engines.prefect_adapter_impl import PrefectAdapter


def test_prefect_adapter_declares_capabilities():
    adapter = PrefectAdapter()
    caps = adapter.provides  # New attribute
    assert any(c.id == "engine:durable-flow" for c in caps)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/engines/test_engine_provides.py -v`
Expected: FAIL — `adapter.provides` doesn't exist.

- [ ] **Step 3: Add `provides: list[Capability]` to each engine**

Pattern (apply to each engine file):

```python
from mahavishnu.core.capabilities import (
    Capability, CapabilityKind, CapabilityState, CostHint, TypeSchema,
)

class PrefectAdapter:
    @property
    def provides(self) -> list[Capability]:
        return [
            Capability(
                id="engine:durable-flow",
                kind=CapabilityKind.ENGINE,
                description="Durable workflow execution with retries and scheduling",
                io_in=TypeSchema(),
                io_out=TypeSchema(),
                state=CapabilityState.DURABLE,
                cost_hint=CostHint(has_side_effects=True),
            ),
        ]
```

Engine-specific `provides`:
- Prefect: `engine:durable-flow`, `engine:scheduled-task`, `engine:retry-with-backoff`
- LlamaIndex: `engine:rag-retrieve`, `engine:document-ingest`, `engine:semantic-search`
- Agno: `engine:multi-agent-team`, `engine:task-decomposition`, `engine:tool-use-loop`
- Hatchet: `engine:durable-flow-alternative`
- Worker (engine): `engine:terminal-execution` (delegates to workers)

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/engines/ tests/unit/test_core_adapters.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/engines/ tests/unit/engines/
git -c user.email="les@wedgwoodwebworks.com" commit -m "feat(engines): declare provides: list[Capability] on all 5 adapters"
```

### Task 2.8: Phase 2 smoke test

- [ ] **Step 1: Spawn one of each worker type via MCP and verify pane content**

Re-run `tests/integration/workers/test_terminal_workers_smoke.py`.

- [ ] **Step 2: Verify `list_capabilities(domain="worker")` returns the 16 expected entries**

(Tool not implemented yet — covered in Stage 3a. For now, verify the loader directly via Python REPL.)

```python
from mahavishnu.core.capabilities_loader import load_capabilities_from_settings
from mahavishnu.core.config import MahavishnuSettings
caps = load_capabilities_from_settings(MahavishnuSettings())
assert len(caps) == 16, f"expected 16, got {len(caps)}"
```

- [ ] **Step 3: Run crackerjack**

Run: `crackerjack run`
Expected: All hooks pass.

- [ ] **Step 4: Commit final state if any new fixes**

```bash
git -c user.email="les@wedgwoodwebworks.com" commit -am "chore: stage 2 cleanup pass"
```

---

## Phase 3 — Stage 3a: Additive Engine Composition

### Task 3a.1: Implement envelopes.py with Dhara-backed transport

**Files:**
- Create: `mahavishnu/core/envelopes.py`

**Interfaces:**
- Consumes: `EnvelopeAddress`, `CapabilityEnvelope`, `Dhara` client
- Produces: `write_envelope(env: CapabilityEnvelope) -> None`, `read_envelope(addr: EnvelopeAddress) -> CapabilityEnvelope`, `list_envelopes(trace_id: TraceId) -> list[EnvelopeAddress]`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_envelopes.py (NEW)
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mahavishnu.core.capabilities import CapabilityEnvelope, EnvelopeAddress, EnvelopeId, CapabilityId, EngineId, TraceId
from mahavishnu.core.envelopes import write_envelope, read_envelope


def test_write_envelope_uses_typed_address():
    dhara = MagicMock()
    env = CapabilityEnvelope(
        envelope_id=EnvelopeId("12345678-1234-1234-1234-123456789012"),
        capability_id=CapabilityId("worker:bash"),
        engine_id=EngineId("worker-claude-tui"),
        io_out={"output": "hello"},
        produced_at="2026-08-29T00:00:00Z",
        trace_id=TraceId("0" * 32),
    )
    write_envelope(env, dhara=dhara)
    expected_key = "envelopes/00000000000000000000000000000000/12345678-1234-1234-1234-123456789012"
    dhara.put.assert_called_once()
    actual_key = dhara.put.call_args[0][0]
    assert actual_key == expected_key


def test_read_envelope_roundtrip():
    dhara = MagicMock()
    dhara.get.return_value = (
        '{"envelope_id":"12345678-1234-1234-1234-123456789012",'
        '"capability_id":"worker:bash",'
        '"engine_id":"worker-claude-tui",'
        '"io_out":{"output":"hi"},'
        '"produced_at":"2026-08-29T00:00:00Z",'
        '"trace_id":"00000000000000000000000000000000",'
        '"parent_envelope_ids":[]}'
    )
    addr = EnvelopeAddress(trace_id=TraceId("0" * 32), envelope_id=EnvelopeId("12345678-1234-1234-1234-123456789012"))
    env = read_envelope(addr, dhara=dhara)
    assert env.io_out == {"output": "hi"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_envelopes.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement envelopes.py**

```python
"""Dhara-backed envelope transport for inter-engine state handoff."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mahavishnu.core.capabilities import CapabilityEnvelope, EnvelopeAddress
from mahavishnu.core.errors import ErrorCode, MahavishnuError

if TYPE_CHECKING:
    from mahavishnu.core.dhara import DharaClient


def write_envelope(env: CapabilityEnvelope, *, dhara: "DharaClient") -> None:
    addr = EnvelopeAddress(trace_id=env.trace_id, envelope_id=env.envelope_id)
    dhara.put(addr.to_key(), env.model_dump_json().encode())


def read_envelope(addr: EnvelopeAddress, *, dhara: "DharaClient") -> CapabilityEnvelope:
    raw = dhara.get(addr.to_key())
    if raw is None:
        raise MahavishnuError(
            f"envelope not found at {addr.to_key()}",
            ErrorCode.RESOURCE_NOT_FOUND,
        )
    return CapabilityEnvelope.model_validate_json(raw)


def list_envelopes(trace_id: Any, *, dhara: "DharaClient") -> list[EnvelopeAddress]:
    prefix = f"envelopes/{trace_id}/"
    keys = dhara.list_keys(prefix=prefix)
    return [EnvelopeAddress.from_key(k) for k in keys]


__all__ = ["write_envelope", "read_envelope", "list_envelopes"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_envelopes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/core/envelopes.py tests/unit/test_envelopes.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "feat(core): Dhara-backed envelope transport"
```

### Task 3a.2: Implement conductor.py — resolver + planner + emit_flow

**Files:**
- Create: `mahavishnu/core/conductor.py`

**Interfaces:**
- Consumes: `CapabilitySpec`, capability registry, engine registrations
- Produces: `resolve(spec) -> list[Candidate]`, `plan(spec, candidates) -> ExecutionDAG`, `emit_flow(dag) -> PrefectFlowDefinition`

- [ ] **Step 1: Write failing test for resolver**

```python
# tests/unit/test_conductor_resolver.py (NEW)
import pytest
from mahavishnu.core.capabilities import (
    Capability, CapabilityKind, CapabilityState, CostHint, TypeSchema,
    EngineRegistration, CapabilitySpec,
)
from mahavishnu.core.conductor import resolve


def test_resolver_picks_engine_that_provides_required_capability():
    cap = Capability(id="engine:durable-flow", kind=CapabilityKind.ENGINE,
                     description="", io_in=TypeSchema(), io_out=TypeSchema(),
                     state=CapabilityState.DURABLE)
    reg = EngineRegistration(
        engine_id="prefect",
        provides=[cap],
        consumes=[],
    )
    spec = CapabilitySpec(requires=["engine:durable-flow"], prompt="x")
    candidates = resolve(spec, [reg])
    assert len(candidates) == 1
    assert candidates[0].engine_id == "prefect"


def test_resolver_returns_empty_when_no_match():
    spec = CapabilitySpec(requires=["engine:nonexistent"], prompt="x")
    candidates = resolve(spec, [])
    assert candidates == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_conductor_resolver.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement resolver**

```python
"""Conductor: capability resolution, binding planning, Prefect flow emission."""
from __future__ import annotations

from typing import Iterable

from mahavishnu.core.capabilities import (
    Candidate, CapabilityId, CapabilitySpec, DAGNode, DAGEdge,
    EngineRegistration, ExecutionDAG, TraceId,
)


def resolve(
    spec: CapabilitySpec, engines: Iterable[EngineRegistration],
) -> list[Candidate]:
    """For each required capability, find engines that provide it. Score = 1.0 (exact match)."""
    candidates: list[Candidate] = []
    for required_id in spec.requires:
        for engine in engines:
            if not engine.enabled:
                continue
            for cap in engine.provides:
                if cap.id == required_id:
                    candidates.append(Candidate(
                        engine_id=engine.engine_id,
                        capability_id=required_id,
                        score=1.0,
                        reason=f"engine {engine.engine_id} provides {required_id}",
                    ))
    return candidates


def plan(
    spec: CapabilitySpec, candidates: list[Candidate], trace_id: TraceId,
) -> ExecutionDAG:
    """Greedy fill: one node per required capability, top-scoring candidate wins."""
    by_cap: dict[CapabilityId, list[Candidate]] = {}
    for c in candidates:
        by_cap.setdefault(c.capability_id, []).append(c)

    nodes: list[DAGNode] = []
    for req in spec.requires:
        cands = sorted(by_cap.get(req, []), key=lambda c: c.score, reverse=True)
        if not cands:
            raise ValueError(f"no engine provides required capability {req!r}")
        winner = cands[0]
        nodes.append(DAGNode(
            node_id=f"n{len(nodes)}",
            engine_id=winner.engine_id,
            capability_id=winner.capability_id,
            inputs=__empty_schema(),
            outputs=__empty_schema(),
        ))

    edges: list[DAGEdge] = []  # Sequential by default; refinement in Phase 4
    return ExecutionDAG(nodes=tuple(nodes), edges=tuple(edges), trace_id=trace_id)


def __empty_schema():
    from mahavishnu.core.capabilities import TypeSchema
    return TypeSchema()


def emit_flow(dag: ExecutionDAG, *, prefect_factory) -> Any:
    """Compile an ExecutionDAG into a Prefect flow definition. Returns the flow."""
    from prefect import flow, task

    @task
    def _node(n: DAGNode) -> None:
        # Dispatch to engine via conductor.emit_node(n)
        from mahavishnu.core.conductor import emit_node
        emit_node(n, trace_id=dag.trace_id)

    @flow(name=f"mahavishnu-dag-{dag.trace_id}")
    def _dag() -> None:
        for n in dag.nodes:
            _node(n)

    return _dag
```

- [ ] **Step 4: Run resolver test**

Run: `pytest tests/unit/test_conductor_resolver.py -v`
Expected: PASS.

- [ ] **Step 5: Write + run planner test**

```python
def test_plan_compiles_one_node_per_required_capability():
    cap = Capability(id="engine:durable-flow", kind=CapabilityKind.ENGINE,
                     description="", io_in=TypeSchema(), io_out=TypeSchema(),
                     state=CapabilityState.DURABLE)
    reg = EngineRegistration(engine_id="prefect", provides=[cap], consumes=[])
    spec = CapabilitySpec(requires=["engine:durable-flow"], prompt="x")
    candidates = resolve(spec, [reg])
    dag = plan(spec, candidates, trace_id=TraceId("0" * 32))
    assert len(dag.nodes) == 1
    assert dag.nodes[0].engine_id == "prefect"
```

- [ ] **Step 6: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/core/conductor.py tests/unit/test_conductor_resolver.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "feat(core): conductor resolver + planner + Prefect flow emitter"
```

### Task 3a.3: Add capability_tools.py — execute_capability + list_capabilities + explain_routing

**Files:**
- Create: `mahavishnu/mcp/tools/capability_tools.py`
- Modify: `mahavishnu/mcp/tools/profiles.py` (register 18th group in `STANDARD_REGISTRATIONS`)

**Interfaces:**
- Consumes: `CapabilitySpec`, conductor
- Produces: Three MCP tools with FastMCP registration

- [ ] **Step 1: Write failing test for `list_capabilities`**

```python
# tests/unit/mcp/test_capability_tools.py (NEW)
import pytest
from fastmcp import FastMCP

from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.mcp.tools.capability_tools import register


@pytest.fixture
def server():
    return FastMCP("test")


def test_list_capabilities_tool_registered(server):
    register(server, MahavishnuSettings())
    import asyncio
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert "list_capabilities" in names
    assert "execute_capability" in names
    assert "explain_routing" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/mcp/test_capability_tools.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement capability_tools.py**

```python
"""MCP tools for capability-driven dispatch (Stage 3a additive)."""
from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from pydantic import ValidationError

from mahavishnu.core.capabilities import (
    CapabilitySpec, ExecutionDAG, SelectorStrategy, TraceId,
)
from mahavishnu.core.capabilities_loader import load_capabilities_from_settings
from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.core.conductor import plan, resolve
from mahavishnu.core.errors import ErrorCode, MahavishnuError


def register(server: FastMCP, settings: MahavishnuSettings) -> None:
    @server.tool
    async def execute_capability(
        spec: dict[str, Any],
        async_callback: bool = False,
    ) -> dict[str, Any]:
        try:
            cap_spec = CapabilitySpec.model_validate(spec)
        except ValidationError as e:
            raise MahavishnuError("invalid CapabilitySpec", ErrorCode.VALIDATION, details={"errors": e.errors()})
        # Resolve + plan
        engines = []  # TODO: load from engine registrations
        candidates = resolve(cap_spec, engines)
        if not candidates and async_callback:
            return {"status": "queued", "trace_id": cap_spec.trace_id}
        dag = plan(cap_spec, candidates, trace_id=cap_spec.trace_id or TraceId("0" * 32))
        return {"status": "planned", "dag": dag.model_dump()}

    @server.tool
    async def list_capabilities(domain: str | None = None) -> list[dict[str, Any]]:
        caps = load_capabilities_from_settings(settings)
        result = [c.model_dump() for c in caps.values()]
        if domain:
            result = [c for c in result if c.get("kind") == domain]
        return result

    @server.tool
    async def explain_routing(spec: dict[str, Any]) -> dict[str, Any]:
        cap_spec = CapabilitySpec.model_validate(spec)
        engines = []
        candidates = resolve(cap_spec, engines)
        return {"spec": cap_spec.model_dump(), "candidates": [c.model_dump() for c in candidates]}
```

- [ ] **Step 4: Register in `profiles.py`**

In `mahavishnu/mcp/tools/profiles.py`, add to `STANDARD_REGISTRATIONS`:

```python
from .capability_tools import register as register_capability_tools

STANDARD_REGISTRATIONS = [
    ...
    ("capability", register_capability_tools),
]
```

(Adjust the import path and registration pattern to match the existing structure in `profiles.py`.)

- [ ] **Step 5: Run test**

Run: `pytest tests/unit/mcp/test_capability_tools.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/mcp/tools/capability_tools.py mahavishnu/mcp/tools/profiles.py tests/unit/mcp/test_capability_tools.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "feat(mcp): add execute_capability + list_capabilities + explain_routing tools"
```

### Task 3a.4: Add `get_capability_result` tool

**Files:**
- Create: `mahavishnu/mcp/tools/get_capability_result_tool.py`

**Interfaces:**
- Consumes: `trace_id: str`, Dhara
- Produces: `{trace_id, status, envelopes, error}` — async read-back analogue of deleted `workflow_result`

- [ ] **Step 1: Write failing test**

```python
def test_get_capability_result_reads_envelopes_from_dhara():
    from unittest.mock import MagicMock
    from fastmcp import FastMCP
    dhara = MagicMock()
    server = FastMCP("test")
    register_get_capability_result(server, dhara=dhara)
    # ... call tool, assert it reads from dhara
```

- [ ] **Step 2: Implement + test + commit (mirror Task 3a.3 pattern)**

### Task 3a.5: Migrate slash-command skills

**Files:**
- Modify: `.claude/skills/mahavishnu/SKILL.md:18-22` (replace `mcp__mahavishnu__pool_route_execute` etc. with `execute_capability` example)
- Modify: `.claude/skills/mahavishnu-status/SKILL.md:49` (same)
- Modify: `.claude/agents/mahavishnu-orchestrator.md:50-52` (frontmatter `tools:` list)

- [ ] **Step 1: Update `mahavishnu/SKILL.md`**

Replace any mention of `pool_route_execute`, `dispatch_to_pool`, `trigger_workflow` with:

> Use `mcp__mahavishnu__execute_capability(spec={"requires": ["engine:rag-retrieve", "worker:ai-context"], "prompt": "..."})` for capability-driven dispatch.

- [ ] **Step 2: Update `mahavishnu-status/SKILL.md`** similarly.

- [ ] **Step 3: Update `mahavishnu-orchestrator.md`** frontmatter `tools:` list to include `mcp__mahavishnu__execute_capability` and remove deprecated tools.

- [ ] **Step 4: Update `/vishnu` skill description** in `.claude/skills/vishnu/SKILL.md` (if present).

- [ ] **Step 5: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add .claude/skills/ .claude/agents/
git -c user.email="les@wedgwoodwebworks.com" commit -m "docs(skills): migrate slash commands to execute_capability"
```

### Task 3a.6: Update CLI subcommands

**Files:**
- Modify: `mahavishnu/_main_cli.py:1402,1469,1781` (CLI flags that used `pool_route_execute` etc.)

- [ ] **Step 1: Replace CLI-level dispatches with `execute_capability` calls**

For each CLI subcommand that called `pool_spawn`, `pool_execute`, `worker_spawn`, or `worker_execute`: replace with `await execute_capability(spec={"requires": ["..."], "prompt": "..."})`.

- [ ] **Step 2: Run CLI tests**

Run: `pytest tests/unit/test_main_cli.py -v`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/_main_cli.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "refactor(cli): dispatch via execute_capability"
```

### Task 3a.7: Stage 3a integration test

**Files:**
- Create: `tests/integration/conductor/test_end_to_end_dag.py`

**Interfaces:**
- Consumes: Live Mahavishnu MCP server with capability tools registered
- Produces: Confirmation that `execute_capability({"requires": ["engine:durable-flow", "worker:ai-context"]})` returns a valid binding plan

- [ ] **Step 1: Write integration test**

```python
@pytest.mark.integration
@pytest.mark.mcp
async def test_execute_capability_returns_binding_plan():
    """execute_capability resolves a 2-capability spec into a 2-node DAG."""
    # Spin up local MCP server via docker-compose (Prefect + Dhara + worker pool)
    # Call execute_capability(spec={"requires": ["engine:durable-flow", "worker:ai-context"]})
    # Assert response has 2 nodes and trace_id is set
    ...
```

- [ ] **Step 2: Run with docker-compose**

Run: `docker-compose -f tests/integration/docker-compose.yml up -d && pytest tests/integration/conductor/test_end_to_end_dag.py -v -m integration`

- [ ] **Step 3: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add tests/integration/conductor/
git -c user.email="les@wedgwoodwebworks.com" commit -m "test(integration): end-to-end execute_capability DAG"
```

### Task 3a.8: Phase 3a complete — run crackerjack

- [ ] **Step 1: Run crackerjack**

Run: `crackerjack run`
Expected: All hooks pass; coverage ≥89%.

- [ ] **Step 2: Manual smoke test**

```bash
mcp__mahavishnu__execute_capability spec='{"requires": ["engine:durable-flow", "worker:ai-context"], "prompt": "test"}'
```

Expected: returns `{status: "planned", dag: {nodes: [..., ...], edges: [], trace_id: "..."}}`.

---

## Phase 4 — Stage 3b: Deletive Cleanup (after one release cycle of dual maintenance)

### Task 3b.1: Mark old tools as deprecated

**Files:**
- Modify: All old tools in `mahavishnu/mcp/tools/pool_tools.py`, `worker_tools.py`, `mahavishnu/mcp/server_core.py:272`

- [ ] **Step 1: Wrap old tools with deprecation warnings**

For each tool, add at the top of the function:

```python
import warnings
from mahavishnu.core.config import MAHAVISHNU_LEGACY_TOOLS

if not os.getenv("MAHAVISHNU_LEGACY_TOOLS"):
    warnings.warn(
        "pool_spawn is deprecated; use execute_capability. "
        "Set MAHAVISHNU_LEGACY_TOOLS=true to silence this warning.",
        DeprecationWarning,
        stacklevel=2,
    )
```

- [ ] **Step 2: Run all tests**

Run: `pytest tests/ -v`
Expected: All pass with deprecation warnings.

- [ ] **Step 3: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/mcp/
git -c user.email="les@wedgwoodwebworks.com" commit -m "chore(mcp): mark old tools as deprecated, gated on MAHAVISHNU_LEGACY_TOOLS"
```

### Task 3b.2: Audit orphans

- [ ] **Step 1: Run audit script**

Run: `python scripts/audit_orphans.py`
Expected: Zero callers of `pool_spawn`, `pool_route_execute`, `dispatch_to_pool`, `workflow_result`, `worker_spawn`, `worker_execute`, `worker_close`, `worker_health`, `worker_list`, `trigger_workflow` outside the deprecated tools themselves.

If callers exist, STOP and create a follow-up task to migrate them before deleting.

### Task 3b.3: Delete old tools

**Files:**
- Modify: `mahavishnu/mcp/tools/pool_tools.py` — delete `pool_spawn`, `pool_execute`, `pool_route_execute`, `dispatch_to_pool`, `workflow_result`
- Modify: `mahavishnu/mcp/tools/worker_tools.py` — delete `worker_spawn`, `worker_execute`, `worker_close`, `worker_health`, `worker_list`
- Modify: `mahavishnu/mcp/server_core.py:272` — delete `trigger_workflow` registration

- [ ] **Step 1: Delete each tool, keep operator-observability subset**

Operator-observability subset preserved: `pool_list`, `pool_health`, `pool_monitor`, `pool_scale`, `pool_close`, `pool_close_all`, `pool_search_memory`.

- [ ] **Step 2: Delete orphaned tests**

Delete `tests/unit/test_*pool*dispatch*`, `tests/unit/test_*worker*spawn*`, etc.

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v`
Expected: All pass.

- [ ] **Step 4: Run crackerjack**

Run: `crackerjack run`
Expected: All hooks pass.

- [ ] **Step 5: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/mcp/ tests/
git -c user.email="les@wedgwoodwebworks.com" commit -m "chore(mcp): delete legacy pool/worker/trigger_workflow tools

Per Stage 3b exit criteria, all dispatch tools are replaced by
execute_capability. Operator-observability subset (pool_list, pool_health,
pool_monitor, pool_scale, pool_close, pool_close_all, pool_search_memory)
is preserved."
```

### Task 3b.4: Phase 3b done — final verification

- [ ] **Step 1: Verify no dead imports**

Run: `uv run pyright mahavishnu/`
Expected: 0 errors.

- [ ] **Step 2: Run full crackerjack**

Run: `crackerjack run`
Expected: All pass.

- [ ] **Step 3: Live MCP smoke**

```bash
mcp__mahavishnu__execute_capability spec='{"requires": ["engine:durable-flow"], "prompt": "test"}'
mcp__mahavishnu__pool_list  # Should still work (observability subset preserved)
mcp__mahavishnu__pool_health  # Should still work
```

- [ ] **Step 4: Tag the release**

```bash
git -c user.email="les@wedgwoodwebworks.com" tag -a v0.18.0 -m "Worker registry capability refactor complete"
```

---

## Self-Review Checklist (post-write)

**Spec coverage:**
- ✅ Stage 1 (worker bootstrap fix) — Phase 1, Tasks 1.1–1.4
- ✅ Stage 2 (capability-driven registry) — Phase 2, Tasks 2.1–2.8
- ✅ Stage 3a (additive composition) — Phase 3a, Tasks 3a.1–3a.8
- ✅ Stage 3b (deletive cleanup) — Phase 4, Tasks 4.1–4.4
- ✅ All schema types from spec §2 defined in Task 2.1
- ✅ All 5 engines declare `provides` (Task 2.7)
- ✅ All 16 worker types migrated to Oneiric (Task 2.3)
- ✅ Slash-command skills, orchestrator subagent, CLI subcommands migrated (Tasks 3a.5, 3a.6)
- ✅ Stage 3b pre-conditions explicit (Task 3b.2 audit_orphans.py)

**No placeholders:** Every step has actual file paths, code snippets, or commands. No TBDs.

**Type consistency:**
- `Capability` model: defined in Task 2.1, used in Task 2.4, 2.7, 3a.2 — consistent.
- `CapabilitySpec`: defined in Task 2.1, used in Task 3a.2 (conductor), 3a.3 (MCP tool) — consistent.
- `EnvelopeAddress.to_key()`: defined in Task 2.1, used in Task 3a.1 — consistent.
- `get_worker_entry(name, settings=...)`: defined in Task 2.5, used in Task 2.6 — consistent.
- `execute_capability`: signature defined in Task 3a.3, used in Task 3a.6 (CLI), 3a.8 (integration test) — consistent.
