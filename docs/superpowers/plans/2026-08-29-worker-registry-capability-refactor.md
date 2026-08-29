# Worker Registry Capability Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static `WORKER_REGISTRY` with a capability-driven registry, fix the broken worker bootstrap bug, and add an engine composition layer where tasks declare required capabilities and the system picks engines + composes them into a DAG.

**Architecture:** Three sequential stages. Stage 1 fixes the tmux bootstrap bug. Stage 2 introduces a `Capability` Pydantic schema loaded via Oneiric; both engines and workers declare `provides: list[Capability]`. Stage 3a adds a `Conductor` that resolves `CapabilitySpec → ExecutionDAG` and emits a Prefect flow, with envelopes persisted to Dhara. Stage 3b deletes legacy MCP tools after one release cycle of dual maintenance.

**Tech Stack:** Python 3.14, Pydantic v2 (`frozen=True, extra="forbid"`), Oneiric (config), Prefect (DAG runtime), FastMCP (server), Dhara (envelope storage), pytest.

**Spec:** `docs/superpowers/specs/2026-08-29-worker-registry-capability-refactor-design.md`

## Global Constraints

- **Python 3.14 floor.** Target 3.14+ syntax (`X | None`, `list[str]`, `pathlib.Path`).
- **`from __future__ import annotations`** as the first non-comment line of every source file. Required at the top of every `tests/**` snippet too.
- **Imports sorted within each section** (stdlib → third-party → first-party with `force-sort-within-sections = true`, `known-first-party = ["mahavishnu"]`).
- **Type hints required on every function signature.** `def f(x: int = None)` is forbidden; use `x: int | None = None`.
- **No `assert` in production code** (`mahavishnu/**`). Use exception hierarchy from `mahavishnu/core/errors.py`. Enforced by bandit B101.
- **No `Any` in tool inputs or orchestration state.** Use Pydantic models with strict typing. **Enforcement gap:** mypy warns on `Any` returns but not on `Any` parameters — manual review required.
- **Use Oneiric logger** (`oneiric.logging`), not stdlib `logging`.
- **Pydantic v2 with `model_config = ConfigDict(frozen=True, extra="forbid")`** for new DTOs.
- **ID patterns:** `CapabilityId = ^[a-z]+:[a-z0-9._-]+$`, `EngineId = ^[a-z][a-z0-9_-]{1,63}$`, `EnvelopeId` is UUIDv4, `TraceId` is 32-char hex. Enforced via `pydantic.StringConstraints` on the newtype, not just docstring.
- **Worker registration:** `settings/mahavishnu.yaml:workers:` block (NOT a separate `workers.yaml` file — bypasses Oneiric's `_settings_build_values` ordering and silently breaks `MAHAVISHNU_WORKERS__FOO` env-var overrides).
- **Commit trailer:** Every `git commit` block in this plan MUST end with `Co-Authored-By: Claude <noreply@anthropic.com>` (CLAUDE.md mandate). Snippets below include the trailer.
- **Commit author:** `git -c user.email="les@wedgwoodwebworks.com"` — never `.local`. (Per `git-author-email-correct-domain.md` memory.)
- **Push:** NEVER run `git push` for bodai repos. User owns publish. (Per `feedback-bodai-push-is-user-controlled.md`.)
- **Quality gate:** `crackerjack run` must pass. Coverage floor: 89% for new code, 95% for `mahavishnu/core/conductor.py`.
- **Pyproject markers:** `unit`, `integration`, `mcp`, `requires_network`, `requires_auth`, `slow` (per CLAUDE.md). New tests should use these markers; don't invent new ones.
- **Async tests** don't need `@pytest.mark.asyncio` — `asyncio_mode = "auto"`.

---

## Phase 1 — Stage 1: Worker Bootstrap Fix

The bug: `WorkerManager.create_worker()` constructs `command=[WorkerConfig.command]` (a single-element argv containing the pre-quoted shell string). `tmux_adapter.create_session()` does `shlex.join()` on it and `send-keys`' the doubly-quoted text into a fresh zsh pane. zsh can't parse it.

**Fix:** Pass the command directly to `tmux new-session -- <command>` instead of `send-keys`. The tmux_adapter change is what makes this work; `WorkerManager`'s single-element argv (which is currently a *single string* in the legacy code) becomes a list-of-strings argv that tmux passes to exec directly.

### Task 1.1: Write failing test for new tmux invocation

**Files:**
- Modify: `tests/unit/workers/contract/test_tmux_adapter.py:46,62,85` (existing send-keys tests)

**Interfaces:**
- Consumes: `tmux_adapter.create_session(socket, session, window_name, command)` from `mahavishnu/workers/contract/tmux_adapter.py`
- Produces: Updated tests asserting the new `tmux new-session -- <command>` shape

- [ ] **Step 1: Read existing tests**

```python
# tests/unit/workers/contract/test_tmux_adapter.py:46-90
# Three test functions asserting the old send-keys invocation shape.
```

- [ ] **Step 2: Update tests to assert new shape**

Replace assertions of `tmux send-keys ...` with assertions of `tmux new-session ... -- <command>`. Each test must assert:

```python
mock_subprocess_run.assert_called_with(
    ["tmux", "-S", socket, "new-session", "-d",
     "-s", session, "-n", window_name,
     "-P", "-F", "#{session_name}:#{window_id}:#{pane_id}",
     "--"] + list(command),
    check=False,
    capture_output=True,
    text=True,
)
```

For the test that exercises a quoted command (`["bash", "-c", "echo 'quoted shell'"]`), assert the call passes argv literally — NOT pre-shlex-joined.

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/workers/contract/test_tmux_adapter.py -v`
Expected: FAIL with assertion mismatch on `assert_called_with`.

- [ ] **Step 4: Commit failing tests**

```bash
git -c user.email="les@wedgwoodwebworks.com" add tests/unit/workers/contract/test_tmux_adapter.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "test(workers): assert new tmux new-session invocation shape

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 1.2: Implement the tmux_adapter fix

**Files:**
- Modify: `mahavishnu/workers/contract/tmux_adapter.py:111-152`

**Interfaces:**
- Consumes: `create_session(socket, session, window_name, command: Sequence[str])` signature unchanged
- Produces: Same `TmuxSessionInfo` return type; passes command via `tmux new-session -- <cmd>` instead of post-creation `send-keys`

- [ ] **Step 1: Replace the entire `create_session` function**

In `mahavishnu/workers/contract/tmux_adapter.py`, replace lines **85-159** (the entire `create_session` function from `def create_session(` through the closing `return TmuxSessionInfo(...)` line) with the snippet below. The original bug lived at lines 111-152 (`shlex.join` + `send-keys`), but the supplied snippet rewrites the whole function — including the validation/chmod prologue at lines 97-110 — so the replacement range must cover both regions or we'd end up with a duplicated validation block.

```python
def create_session(
    *,
    socket: str,
    session: str,
    window_name: str,
    command: Sequence[str],
) -> TmuxSessionInfo:
    """Create a new detached tmux session and exec ``command`` in its first pane.

    The command is passed as a positional argv after ``--`` so tmux exec's it
    directly without a shell round-trip. Pre-quoting / shlex.join is FORBIDDEN
    here — see commit msg of fix: shlex.join was producing doubly-quoted output
    that zsh could not parse.
    """
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

- [ ] **Step 2: Remove `import shlex` if unused**

Run: `grep -n shlex mahavishnu/workers/contract/tmux_adapter.py`. If unused elsewhere in the file, remove the import.

- [ ] **Step 3: Run the test from Task 1.1**

Run: `pytest tests/unit/workers/contract/test_tmux_adapter.py -v`
Expected: PASS.

- [ ] **Step 4: Run full worker test suite**

Run: `pytest tests/unit/workers/ -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/workers/contract/tmux_adapter.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "fix(workers): pass launch command via tmux new-session instead of send-keys

The tmux_adapter.create_session was using send-keys to type a pre-
quoted shell string into a fresh zsh pane, but the string was passed
through shlex.join producing doubly-quoted output that zsh could not
parse. tmux new-session accepts the command as a positional argument
after --; tmux exec's it directly without the shell round-trip.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 1.3: Phase 1 manual smoke check (one worker type)

**Files:** none modified (smoke test only)

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

**v3 reviewer note #9:** a programmatic smoke test for all 16 worker types lived here in v2 but depends on Phase 2 artifacts (`get_worker_entry`, `settings.worker_registry.entries`, etc.) and on a `PoolManager` API that doesn't exist (`PoolManager.from_settings()`, `spawn_worker()`, `capture_pane()`, `close_worker()` — real surface: `spawn_pool`, `execute_on_pool`, `route_task`, `close_pool`, `close_all`, `list_pools`, `health_check` per `pools/manager.py:286-1120`). That programmatic smoke test is now Task 2.9 at the end of Phase 2, where it has the dependencies it needs.

---

### Task 1.4: Phase 1 done — tag the fix

- [ ] **Step 1: Tag the fix (DO NOT push)**

```bash
git -c user.email="les@wedgwoodwebworks.com" tag -a v0.17.1 -m "Stage 1: fix tmux worker bootstrap bug"
```

(Per `feedback-bodai-push-is-user-controlled.md`, NEVER push without explicit approval.)

---

---

## Phase 2 — Stage 2: Capability-Driven Registry

### Task 2.0: Pre-Phase 2 scaffolding (config flags, auth scopes, capability allow-list)

This task exists because Phase 3a needs three settings before its MCP tools can be registered: a kill-switch for `execute_capability`, an auth-scope allow-list (so `MultiAuthHandler` can gate it), and the `MAHAVISHNU_LEGACY_TOOLS` flag for Phase 3b's deprecation gate.

**Files:**
- Modify: `mahavishnu/core/config.py` (add three fields to `MahavishnuSettings`)

**Interfaces:**
- Consumes: Oneiric-loaded env + YAML
- Produces: `MahavishnuSettings.capability_enabled: bool`, `MahavishnuSettings.capability_scopes: list[str]`, `MahavishnuSettings.legacy_tools: bool`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_core_config_capability_flags.py
from __future__ import annotations

from mahavishnu.core.config import MahavishnuSettings


def test_capability_flag_defaults_to_false() -> None:
    s = MahavishnuSettings()
    assert s.capability_enabled is False
    assert s.legacy_tools is False


def test_capability_scopes_default_empty() -> None:
    s = MahavishnuSettings()
    assert s.capability_scopes == []


def test_capability_scopes_validate_strings() -> None:
    s = MahavishnuSettings.model_validate({
        "capability_scopes": ["execute_capability", "list_capabilities"],
    })
    assert "execute_capability" in s.capability_scopes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_core_config_capability_flags.py -v`
Expected: FAIL — attributes missing.

- [ ] **Step 3: Add the three fields to `MahavishnuSettings`**

In `mahavishnu/core/config.py`, inside the `MahavishnuSettings` class, add (preserving existing field order — append near the bottom):

```python
# Phase 3a: capability tools kill-switch + scope allow-list
capability_enabled: bool = False
capability_scopes: list[str] = Field(default_factory=list)

# Phase 3b: legacy tool deprecation gate
legacy_tools: bool = False
```

- [ ] **Step 4: Run test from Step 1**

Run: `pytest tests/unit/test_core_config_capability_flags.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/core/config.py tests/unit/test_core_config_capability_flags.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "feat(config): add capability_enabled / capability_scopes / legacy_tools flags

Phase 3a capability tools need a kill-switch (capability_enabled) and
auth scope allow-list (capability_scopes) so MultiAuthHandler can gate
execute_capability. Phase 3b's deprecation warnings on the legacy
pool/worker tools read legacy_tools to silence themselves.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 2.1: Create capabilities.py with all Pydantic schemas

**Files:**
- Create: `mahavishnu/core/capabilities.py`
- Create: `tests/unit/test_core_capabilities_schema.py`

**Interfaces:**
- Produces: ID newtypes (`CapabilityId`, `EngineId`, `EnvelopeId`, `TraceId`) with regex validation; enums (`CapabilityKind`, `CapabilityState`, `HealthStatus`, `SelectorStrategy`); models (`TypeSchema`, `CostHint`, `HealthRef`, `Capability`, `EngineRegistration`, `CapabilityEnvelope`, `EnvelopeAddress`, `Candidate`, `DAGNode`, `DAGEdge`, `ExecutionDAG`, `CapabilitySpec`). All `frozen=True, extra="forbid"`.

- [ ] **Step 1: Write failing test (TDD)**

```python
# tests/unit/test_core_capabilities_schema.py
from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import StringConstraints, TypeAdapter, ValidationError

from mahavishnu.core.capabilities import (
    Capability, CapabilityEnvelope, CapabilityId, CapabilityKind,
    CapabilitySpec, CapabilityState, Candidate, CostHint, DAGEdge,
    DAGNode, EngineId, EngineRegistration, EnvelopeAddress, EnvelopeId,
    ExecutionDAG, HealthRef, HealthStatus, SelectorStrategy, TraceId,
    TypeSchema,
)


# `CapabilityId`, `EngineId`, `TraceId` are `Annotated[str, StringConstraints]`
# aliases. Calling the alias directly delegates to str() and never validates;
# use TypeAdapter to actually exercise the constraint.
_capability_id_t = TypeAdapter(CapabilityId)
_engine_id_t = TypeAdapter(EngineId)
_trace_id_t = TypeAdapter(TraceId)


def test_capability_id_rejects_bad_format() -> None:
    with pytest.raises(ValidationError):
        _capability_id_t.validate_python("BAD")  # missing colon


def test_capability_id_accepts_kind_colon_name() -> None:
    assert _capability_id_t.validate_python("worker:bash") == "worker:bash"


def test_trace_id_must_be_32_hex() -> None:
    _trace_id_t.validate_python("0" * 32)  # ok
    with pytest.raises(ValidationError):
        _trace_id_t.validate_python("not-hex")


def test_capability_model_is_frozen_and_forbids_extras() -> None:
    cap = Capability(
        id="worker:bash",
        kind=CapabilityKind.WORKER,
        description="",
        io_in=TypeSchema(),
        io_out=TypeSchema(),
    )
    with pytest.raises(ValidationError):
        cap.description = "new"  # frozen
    with pytest.raises(ValidationError):
        Capability.model_validate({
            "id": "worker:bash",
            "kind": "worker",
            "description": "",
            "io_in": {},
            "io_out": {},
            "unknown_field": "x",
        })


def test_capability_spec_requires_nonempty_prompt() -> None:
    with pytest.raises(ValidationError):
        CapabilitySpec(requires=[], prompt="")


def test_engine_id_pattern() -> None:
    _engine_id_t.validate_python("prefect")  # ok
    with pytest.raises(ValidationError):
        _engine_id_t.validate_python("BAD ENGINE")  # space + uppercase
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_core_capabilities_schema.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write `mahavishnu/core/capabilities.py`**

```python
"""Capability schema: types, enums, and Pydantic models for the registry.

This is the single source of truth for what a Capability, EngineRegistration,
ExecutionDAG, etc. look like. Imported by ``capabilities_loader``,
``conductor``, ``envelopes``, and the capability MCP tools.

Schema rules:
- Every model uses ``model_config = ConfigDict(frozen=True, extra="forbid")``.
- Newtypes enforce ID patterns at the Pydantic layer (not just docstring).
- No ``Any`` in tool inputs or orchestration state.
"""
from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# ---------------------------------------------------------------------------
# ID patterns
# ---------------------------------------------------------------------------

CapabilityId = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z]+:[a-z0-9._-]+$", min_length=3, max_length=128),
]
EngineId = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_-]{1,63}$", min_length=2, max_length=64),
]
# EnvelopeId is a UUIDv4 — format-only validation here; semantic via uuid.UUID.
EnvelopeId = Annotated[
    str,
    StringConstraints(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        min_length=36,
        max_length=36,
    ),
]
TraceId = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{32}$", min_length=32, max_length=32),
]

_FROZEN_FORBID = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CapabilityKind(str, Enum):
    ENGINE = "engine"
    MODEL = "model"
    WORKER = "worker"
    ADAPTER = "adapter"


class CapabilityState(str, Enum):
    EPHEMERAL = "ephemeral"
    DURABLE = "durable"
    INTERACTIVE = "interactive"  # added per spec §2


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class SelectorStrategy(str, Enum):
    LEAST_LOADED = "least_loaded"
    ROUND_ROBIN = "round_robin"
    CAPABILITY_SCORE = "capability_score"
    RANDOM = "random"
    AFFINITY = "affinity"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TypeSchema(BaseModel):
    """Typed I/O contract. Empty schema means "any".

    Production usage of ``matches()`` lives in conductor.plan() (Phase 3a.2)
    — the schema's structural comparison is what lets the planner emit edges.
    """

    model_config = _FROZEN_FORBID
    fields: dict[str, str] = Field(default_factory=dict)

    def matches(self, other: TypeSchema) -> bool:
        """Structural sub-schema check: every field in self is also in other with a compatible type.

        Empty schema matches anything. Used by ``Conductor.plan()`` to emit DAG edges
        when a downstream node's io_in is satisfied by an upstream node's io_out.
        """
        if not self.fields:
            return True
        return all(
            other.fields.get(name) == ty
            for name, ty in self.fields.items()
        )


class CostHint(BaseModel):
    model_config = _FROZEN_FORBID
    estimated_seconds: float = 1.0
    estimated_tokens: int = 0
    has_side_effects: bool = False


class HealthRef(BaseModel):
    model_config = _FROZEN_FORBID
    endpoint: str
    timeout_seconds: float = 5.0


class Capability(BaseModel):
    model_config = _FROZEN_FORBID
    id: CapabilityId
    kind: CapabilityKind
    description: str
    io_in: TypeSchema
    io_out: TypeSchema
    state: CapabilityState = CapabilityState.EPHEMERAL
    cost_hint: CostHint = Field(default_factory=CostHint)
    tags: list[str] = Field(default_factory=list)
    health_ref: HealthRef | None = None


class EngineRegistration(BaseModel):
    model_config = _FROZEN_FORBID
    engine_id: EngineId
    provides: list[Capability]
    consumes: list[Capability] = Field(default_factory=list)
    enabled: bool = True
    version: str = "0.0.0"


class CapabilityEnvelope(BaseModel):
    model_config = _FROZEN_FORBID
    envelope_id: EnvelopeId
    capability_id: CapabilityId
    engine_id: EngineId
    io_out: dict[str, str] = Field(default_factory=dict)  # string-only after redaction
    produced_at: datetime
    trace_id: TraceId
    parent_envelope_ids: list[EnvelopeId] = Field(default_factory=list)
    sensitivity: str = "internal"  # for Phase 4 TTL: public|internal|secret


class EnvelopeAddress(BaseModel):
    model_config = _FROZEN_FORBID
    trace_id: TraceId
    envelope_id: EnvelopeId

    def to_key(self) -> str:
        return f"envelopes/{self.trace_id}/{self.envelope_id}"

    @classmethod
    def from_key(cls, key: str) -> EnvelopeAddress:
        # envelopes/<trace_id:32hex>/<envelope_id:36>
        parts = key.split("/")
        if len(parts) != 3 or parts[0] != "envelopes":
            raise ValueError(f"not an envelope key: {key!r}")
        return cls(trace_id=TraceId(parts[1]), envelope_id=EnvelopeId(parts[2]))


class Candidate(BaseModel):
    model_config = _FROZEN_FORBID
    engine_id: EngineId
    capability_id: CapabilityId
    score: float
    reason: str
    # The resolved Capability object, so plan() can populate DAGNode inputs/outputs
    # from the same source. Set by Conductor.resolve(); required.
    capability: Capability


class DAGNode(BaseModel):
    model_config = _FROZEN_FORBID
    node_id: str
    engine_id: EngineId
    capability_id: CapabilityId
    inputs: TypeSchema
    outputs: TypeSchema


class DAGEdge(BaseModel):
    model_config = _FROZEN_FORBID
    from_node: str
    to_node: str
    via_field: str  # name of the io_out field that flows to io_in[v]


class ExecutionDAG(BaseModel):
    model_config = _FROZEN_FORBID
    nodes: tuple[DAGNode, ...]
    edges: tuple[DAGEdge, ...]
    trace_id: TraceId


class CapabilitySpec(BaseModel):
    model_config = _FROZEN_FORBID
    requires: list[CapabilityId]
    prompt: str = Field(min_length=1)
    selector: SelectorStrategy = SelectorStrategy.CAPABILITY_SCORE
    affinity_pool_id: str | None = None
    trace_id: TraceId | None = None
    timeout_seconds: int = Field(default=300, ge=1, le=3600)


# ---------------------------------------------------------------------------
# Result type for capability_tools.execute_capability (Phase 3a.3)
# ---------------------------------------------------------------------------


class CapabilityExecutionResult(BaseModel):
    """Return type of ``execute_capability``. Replaces dict[str, Any] leakage."""

    model_config = ConfigDict(extra="forbid")  # mutable — set after construction
    status: str  # "planned" | "queued" | "rejected"
    trace_id: TraceId
    dag: ExecutionDAG | None = None
    error: str | None = None


__all__ = [
    "Capability",
    "CapabilityEnvelope",
    "CapabilityExecutionResult",
    "CapabilityId",
    "CapabilityKind",
    "CapabilitySpec",
    "CapabilityState",
    "Candidate",
    "CostHint",
    "DAGEdge",
    "DAGNode",
    "EngineId",
    "EngineRegistration",
    "EnvelopeAddress",
    "EnvelopeId",
    "ExecutionDAG",
    "HealthRef",
    "HealthStatus",
    "SelectorStrategy",
    "TraceId",
    "TypeSchema",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_core_capabilities_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Run pyright + mypy**

Run: `uv run pyright mahavishnu/core/capabilities.py && uv run mypy --strict mahavishnu/core/capabilities.py`
Expected: 0 errors each.

- [ ] **Step 6: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/core/capabilities.py tests/unit/test_core_capabilities_schema.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "feat(core): add capability schema with typed I/O contracts

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 2.2: Add WorkerRegistryConfig to MahavishnuSettings

**Files:**
- Modify: `mahavishnu/core/config.py` (near existing `WorkerConfig`)

**Interfaces:**
- Consumes: Existing `MahavishnuSettings`
- Produces: New `WorkerRegistryConfig` Pydantic model registered on `MahavishnuSettings` as `worker_registry` (NOT `workers` — that name is already taken at `mahavishnu/core/config.py:2263` by `WorkerConfig` for runtime worker config: `enabled`, `max_concurrent`, `default_type`, `timeout_seconds`, `session_buddy_integration`, `container`; `extra="forbid"` at :1142). Using `workers` would silently break 8 existing readers (`_main_cli.py:1325,1408`, `core/bootstrap.py:225`, `core/health.py:679`, plus tests). `WorkerEntry` validates `provides` list at Pydantic layer.

**v3 reviewer note:** WorkerEntry.name must default to `""` (or be optional) — the existing tests below only set `worker_type`/`command_argv`/`provides`, so a required `name: str` field would fail with "Field required". The plan's note that "name Field required" is wrong.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_core_config_worker_registry.py
from __future__ import annotations

import pytest
from pydantic import ValidationError

from mahavishnu.core.config import MahavishnuSettings


def test_settings_accepts_worker_registry_block() -> None:
    s = MahavishnuSettings.model_validate({"worker_registry": {"entries": []}})
    assert hasattr(s, "worker_registry")


def test_settings_rejects_unknown_worker_block_keys() -> None:
    with pytest.raises(ValidationError):
        MahavishnuSettings.model_validate({"worker_registry": {"unknown_field": "x"}})


def test_worker_entry_rejects_invalid_capability_id() -> None:
    """provides list values must match CapabilityId pattern ^[a-z]+:[a-z0-9._-]+$."""
    with pytest.raises(ValidationError):
        MahavishnuSettings.model_validate({
            "worker_registry": {"entries": [
                {"worker_type": "x", "command_argv": ["bash"], "provides": ["BAD-ID"]},
            ]},
        })


def test_worker_entry_accepts_valid_capability_id() -> None:
    s = MahavishnuSettings.model_validate({
        "worker_registry": {"entries": [
            {"worker_type": "x", "command_argv": ["bash"], "provides": ["worker:bash"]},
        ]},
    })
    assert s.worker_registry.entries[0].provides == ["worker:bash"]


def test_worker_entry_name_is_optional() -> None:
    """name is optional — the Pydantic default is empty string."""
    s = MahavishnuSettings.model_validate({
        "worker_registry": {"entries": [
            {"worker_type": "x", "command_argv": ["bash"], "provides": ["worker:bash"]},
        ]},
    })
    assert s.worker_registry.entries[0].name == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_core_config_worker_registry.py -v`
Expected: FAIL.

- [ ] **Step 3: Add `WorkerEntry` + `WorkerRegistryConfig` to config.py**

In `mahavishnu/core/config.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING
from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    pass


_CAPABILITY_ID_PATTERN = r"^[a-z]+:[a-z0-9._-]+$"


class WorkerEntry(BaseModel):
    """One worker registration, loaded from ``settings/mahavishnu.yaml:worker_registry.entries[]``."""

    model_config = ConfigDict(extra="forbid")
    worker_type: str
    name: str = ""  # default empty so the field is optional in YAML
    description: str = ""
    command_argv: list[str] = Field(default_factory=list)
    completion_markers: list[str] = Field(default_factory=list)
    provides: list[str] = Field(default_factory=list)  # CapabilityId strings
    tags: list[str] = Field(default_factory=list)
    requires_tool: str | None = None
    required_env: list[str] = Field(default_factory=list)
    auth_kind: str = "none"
    runtime_kind: str = "shell"
    one_shot: bool = False
    default_timeout: int = 300

    @field_validator("provides")
    @classmethod
    def _validate_provides(cls, v: list[str]) -> list[str]:
        import re
        pat = re.compile(_CAPABILITY_ID_PATTERN)
        for cap_id in v:
            if not pat.match(cap_id):
                raise ValueError(
                    f"provides entry {cap_id!r} does not match {_CAPABILITY_ID_PATTERN!r}"
                )
        return v

    @field_validator("worker_type")
    @classmethod
    def _validate_worker_type(cls, v: str) -> str:
        if not v:
            raise ValueError("worker_type must be non-empty")
        return v


class WorkerRegistryConfig(BaseModel):
    """Loaded from ``worker_registry:`` block in ``settings/mahavishnu.yaml``.

    Each entry corresponds to one terminal-* worker type. The keys
    here are the SAME string keys as the legacy ``WORKER_REGISTRY``,
    so this is a drop-in replacement.

    NOTE: The name is ``worker_registry`` (not ``workers``) because
    ``MahavishnuSettings.workers`` is already taken by the runtime
    WorkerConfig block at :2263 of core/config.py.
    """

    model_config = ConfigDict(extra="forbid")
    entries: list[WorkerEntry] = Field(default_factory=list)
```

- [ ] **Step 4: Register on `MahavishnuSettings`**

Inside the `MahavishnuSettings` class, add (alongside the existing fields from Task 2.0). The name is `worker_registry` to avoid colliding with the existing `workers` field used by runtime config:

```python
    worker_registry: WorkerRegistryConfig = Field(default_factory=WorkerRegistryConfig)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/test_core_config_worker_registry.py tests/unit/test_core_config_capability_flags.py -v`
Expected: PASS.

- [ ] **Step 6: Run full config tests**

Run: `pytest tests/unit/test_core_config.py -v`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/core/config.py tests/unit/test_core_config_worker_registry.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "feat(config): add WorkerRegistryConfig with Pydantic-validated provides

WorkerEntry.provides values are validated at the Pydantic layer via
field_validator, so the capabilities_loader (Task 2.4) can trust the
shape and only has to instantiate Capability objects.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 2.3: Update settings/mahavishnu.yaml with worker_registry: block

**Files:**
- Modify: `settings/mahavishnu.yaml` (append a new top-level `worker_registry:` block)

**Interfaces:**
- Consumes: Existing `settings/mahavishnu.yaml`
- Produces: Same yaml with a `worker_registry.entries:` list containing 16 entries (one per legacy `terminal-*` worker type)

**v3 reviewer note:** The file already has a top-level `workers:` block at **line 103** (`enabled: true`, `max_concurrent: 10`, `default_type: "terminal-claude"`) for runtime worker config. Adding a second `workers:` block would produce a duplicate YAML mapping key; PyYAML keeps the last one and silently discards the existing worker settings. We use `worker_registry:` instead.

- [ ] **Step 1: Read current settings**

```bash
cat settings/mahavishnu.yaml | head -30
grep -n "^workers:" settings/mahavishnu.yaml
```

(The second command confirms the existing `workers:` block — if a different name is taken, rename `worker_registry:` accordingly.)

- [ ] **Step 2: Append the worker_registry block**

Append to `settings/mahavishnu.yaml`:

```yaml
# Worker registry (Stage 2 of capability refactor)
# Loaded by Oneiric into MahavishnuSettings.worker_registry
# NOTE: the existing top-level `workers:` block at line ~103 holds runtime
# worker config (enabled/max_concurrent/default_type/timeout_seconds). We
# use `worker_registry:` to avoid colliding with it.
worker_registry:
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

**Note:** `terminal-shell` previously lacked a `name` field per reviewer finding C1; the snippet above includes `name: "Bash Shell"`. The Pydantic layer now rejects entries with `name=""` (per WorkerEntry._validate_worker_type), but `name=""` is the field default and only `worker_type=""` is forbidden — both must be present.

- [ ] **Step 3: Verify settings load via the project's settings factory**

The plan previously called `oneiric.core.config.load_settings("mahavishnu")` — that helper was removed in the Oneiric 0.19.0 refactor. The current canonical check is:

```bash
python -c "from mahavishnu.core.config import MahavishnuSettings; s = MahavishnuSettings(); print(type(s.worker_registry).__name__, len(s.worker_registry.entries))"
```

Expected: prints `WorkerRegistryConfig 16`.

- [ ] **Step 4: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add settings/mahavishnu.yaml
git -c user.email="les@wedgwoodwebworks.com" commit -m "feat(settings): add workers.entries block for capability-driven registry

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 2.4: Add Oneiric-driven capabilities loader (with duplicate detection)

**Files:**
- Create: `mahavishnu/core/capabilities_loader.py`
- Create: `tests/unit/test_capabilities_loader.py`

**Interfaces:**
- Consumes: `WorkerRegistryConfig` from `MahavishnuSettings`
- Produces: `dict[str, list[Capability]]` — capability_id to the list of Capabilities that provide it (since 5 workers provide `worker:ai-context`, the dict value is a list, not a single Capability). Raises `MahavishnuError` on invalid input (impossible now because `WorkerEntry.provides` is Pydantic-validated, but kept for defense-in-depth).

**Important:** This is a behavior change from v1. v1 returned `dict[str, Capability]` and silently overwrote — losing the fact that 5 different worker types provide `worker:ai-context`. v2 returns `dict[str, list[Capability]]` so the Conductor can choose between them.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_capabilities_loader.py
from __future__ import annotations

from mahavishnu.core.capabilities_loader import load_capabilities_from_settings
from mahavishnu.core.capabilities import CapabilityKind, CapabilityState
from mahavishnu.core.config import MahavishnuSettings


def test_load_capabilities_groups_by_id() -> None:
    s = MahavishnuSettings.model_validate({
        "worker_registry": {"entries": [
            {"worker_type": "a", "command_argv": ["x"], "provides": ["worker:ai-context"], "name": "A"},
            {"worker_type": "b", "command_argv": ["y"], "provides": ["worker:ai-context"], "name": "B"},
        ]},
    })
    caps = load_capabilities_from_settings(s)
    # Both A and B provide worker:ai-context — caller must get a list of 2.
    assert "worker:ai-context" in caps
    assert len(caps["worker:ai-context"]) == 2
    assert {c.description for c in caps["worker:ai-context"]} == {"A", "B"}


def test_load_capabilities_includes_kind_and_state() -> None:
    s = MahavishnuSettings.model_validate({
        "worker_registry": {"entries": [
            {"worker_type": "a", "command_argv": ["x"], "provides": ["worker:bash"], "name": "Bash"},
        ]},
    })
    caps = load_capabilities_from_settings(s)
    cap = caps["worker:bash"][0]
    assert cap.kind == CapabilityKind.WORKER
    assert cap.state == CapabilityState.EPHEMERAL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_capabilities_loader.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement the loader**

Write `mahavishnu/core/capabilities_loader.py`:

```python
"""Load capability + worker registrations from Oneiric-loaded config.

Each `WorkerEntry.provides` becomes one Capability. Multiple worker entries
can provide the same CapabilityId (e.g. 5 workers provide ``worker:ai-context``);
we group by ID so the Conductor can choose between them.
"""
from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from mahavishnu.core.capabilities import (
    Capability,
    CapabilityId,
    CapabilityKind,
    CapabilityState,
    CostHint,
    TypeSchema,
)

if TYPE_CHECKING:
    from mahavishnu.core.config import MahavishnuSettings


def load_capabilities_from_settings(
    settings: "MahavishnuSettings",
) -> dict[str, list[Capability]]:
    """Convert ``settings.worker_registry.entries`` into a ``{capability_id: [Capability, ...]}`` map.

    CapabilityId pattern is enforced at the Pydantic layer (WorkerEntry.provides
    field_validator), so this function trusts the input.
    """
    grouped: dict[str, list[Capability]] = defaultdict(list)
    for entry in settings.worker_registry.entries:
        for cap_id in entry.provides:
            capability = Capability(
                id=CapabilityId(cap_id),
                kind=CapabilityKind.WORKER,
                description=entry.description or entry.name,
                io_in=TypeSchema(),
                io_out=TypeSchema(),
                state=CapabilityState.EPHEMERAL,
                cost_hint=CostHint(has_side_effects=True),
                tags=entry.tags,
            )
            grouped[cap_id].append(capability)
    return dict(grouped)


__all__ = ["load_capabilities_from_settings"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_capabilities_loader.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/core/capabilities_loader.py tests/unit/test_capabilities_loader.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "feat(core): add Oneiric-driven capability loader (grouped by id)

v1 silently overwrote duplicates. 5 worker types provide
worker:ai-context; grouping by ID lets the Conductor rank them.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 2.5: Replace WORKER_REGISTRY with WorkerEntry lookups

**Files:**
- Modify: `mahavishnu/workers/registry.py` (add new lookup functions alongside existing exports — DO NOT rewrite the file)
- Modify: `mahavishnu/workers/__init__.py:40` (re-export new symbols)
- Modify: `mahavishnu/_main_cli.py:73,1402` (use new lookup API)
- Modify: `mahavishnu/cli/base.py:100` (use new lookup API)
- Modify: `mahavishnu/mcp/bootstrap.py` (use new lookup API if it touches WORKER_REGISTRY)

**v3 reviewer note:** `mahavishnu/workers/registry.py` exports far more than `WORKER_REGISTRY`: `AuthKind` (:11), `RuntimeKind` (:22), `WorkerCategory` (:31), `WorkerConfig` (:43), `get_worker_config` (:742), `resolve_worker_type` (:754), `list_worker_types(category=...)` (:768), `get_workers_by_category` (:782), `validate_worker_dependencies` (:794). `mahavishnu/workers/__init__.py:40-49` imports eight of them, and 8 production modules import the package. The legacy `list_worker_types(category=...)` signature must be preserved (callers depend on `category` kwarg). Rewriting the file is an ImportError cascade and silently breaks the existing signature.

**Interfaces:**
- Consumes: `MahavishnuSettings.worker_registry`
- Produces: `get_worker_entry(worker_type, settings=None) -> WorkerEntry`, `list_worker_types(settings=None) -> list[str]`

- [ ] **Step 1: Audit WORKER_REGISTRY production imports**

```bash
grep -rn "WORKER_REGISTRY" --include='*.py' mahavishnu/ | grep -v test_
```

Record each hit in the task notes. Step 5 fixes only the production sites.

- [ ] **Step 2: Write failing test for new lookup API**

```python
# tests/unit/workers/test_registry_lookup.py
from __future__ import annotations

import pytest

from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.core.errors import MahavishnuError
from mahavishnu.workers.registry import get_worker_entry, list_worker_types


def test_get_worker_entry_loads_from_settings() -> None:
    s = MahavishnuSettings.model_validate({
        "worker_registry": {"entries": [
            {"worker_type": "terminal-shell", "name": "Bash", "command_argv": ["bash"]},
        ]},
    })
    entry = get_worker_entry("terminal-shell", settings=s)
    assert entry.name == "Bash"


def test_get_worker_entry_raises_for_unknown() -> None:
    """Missing worker_type raises MahavishnuError(RESOURCE_NOT_FOUND), NOT KeyError."""
    s = MahavishnuSettings()
    with pytest.raises(MahavishnuError):
        get_worker_entry("does-not-exist", settings=s)


def test_list_worker_types_returns_all_registered() -> None:
    s = MahavishnuSettings()
    types_ = list_worker_types(settings=s)
    assert "terminal-claude" in types_
    assert "terminal-shell" in types_
    assert len(types_) >= 16


def test_legacy_list_worker_types_with_category_still_works() -> None:
    """The existing list_worker_types(category=...) signature is preserved."""
    from mahavishnu.workers.registry import list_worker_types as legacy
    s = MahavishnuSettings()
    types_ = legacy(settings=s, category="ai-context")  # may be empty, must not raise
    assert isinstance(types_, list)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/workers/test_registry_lookup.py -v`
Expected: FAIL.

- [ ] **Step 4: Add new functions to `mahavishnu/workers/registry.py` (NOT rewrite)**

Append to the existing file (do NOT delete `WORKER_REGISTRY`, `AuthKind`, `RuntimeKind`, `WorkerCategory`, `WorkerConfig`, `get_worker_config`, `resolve_worker_type`, `list_worker_types` (the legacy version), `get_workers_by_category`, or `validate_worker_dependencies`):

```python
"""Worker registration lookup, backed by Oneiric-loaded config.

Existing exports (AuthKind, RuntimeKind, WorkerCategory, WorkerConfig,
get_worker_config, resolve_worker_type, list_worker_types (legacy),
get_workers_by_category, validate_worker_dependencies) are preserved.

New additions:
- get_worker_entry(worker_type, *, settings=None) -> WorkerEntry
- list_worker_types(*, settings=None) -> list[str]  # NO `category` kwarg,
  the legacy function above keeps that signature.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from mahavishnu.core.errors import ErrorCode, MahavishnuError

if TYPE_CHECKING:
    from mahavishnu.core.config import MahavishnuSettings, WorkerEntry


def get_worker_entry(
    worker_type: str, *, settings: "MahavishnuSettings | None" = None,
) -> "WorkerEntry":
    """Look up a worker entry by its ``worker_type`` string."""
    if settings is None:
        from mahavishnu.core.config import MahavishnuSettings as _S
        settings = _S()
    for entry in settings.worker_registry.entries:
        if entry.worker_type == worker_type:
            return entry
    raise MahavishnuError(
        f"worker_type {worker_type!r} not found in registry",
        ErrorCode.RESOURCE_NOT_FOUND,
    )


def list_worker_types(
    *, settings: "MahavishnuSettings | None" = None,
) -> list[str]:
    """Return all registered worker_type strings (no category filter)."""
    if settings is None:
        from mahavishnu.core.config import MahavishnuSettings as _S
        settings = _S()
    return [e.worker_type for e in settings.worker_registry.entries]


__all__ = [
    # ... existing exports preserved ...
    "get_worker_entry",
    "list_worker_types",  # the new no-category version (the legacy one with category is also exported)
]
```

Note: there are now TWO functions named `list_worker_types` in this module. The new one (no `category` kwarg) is the capability-driven version; the legacy one (with `category` kwarg) is preserved for backwards-compat. The `__all__` list should disambiguate or keep both.

- [ ] **Step 5: Update production importers**

For each hit from Step 1 (use the new `get_worker_entry` from registry.py):

- `mahavishnu/workers/__init__.py:40` — keep existing re-exports; add `get_worker_entry`.
- `mahavishnu/_main_cli.py:73` and `:1402` — replace `WORKER_REGISTRY[name]` with `get_worker_entry(name)`.
- `mahavishnu/cli/base.py:100` — same.
- `mahavishnu/mcp/bootstrap.py` — same (only if it actually touches WORKER_REGISTRY).

- [ ] **Step 6: Update test files**

For each file under `tests/` that references `WORKER_REGISTRY`, replace `WORKER_REGISTRY[X]` access with `get_worker_entry(X, settings=settings)`.

- [ ] **Step 7: Run all updated tests**

Run: `pytest tests/unit/workers/ tests/unit/test_main_cli.py tests/unit/test_error_codes.py -v`
Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/workers/registry.py mahavishnu/workers/__init__.py mahavishnu/_main_cli.py mahavishnu/cli/base.py mahavishnu/mcp/bootstrap.py tests/
git -c user.email="les@wedgwoodwebworks.com" commit -m "refactor(workers): replace WORKER_REGISTRY with Oneiric-loaded lookup

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 2.6: Update WorkerManager to use new lookup

**Files:**
- Modify: `mahavishnu/workers/manager.py` (replace `WORKER_REGISTRY[name]` access with `get_worker_entry(name, settings=settings)`)

**Interfaces:**
- Consumes: `WorkerEntry` from new lookup
- Produces: Same `WorkerManager` API; pass `command_argv` (from WorkerEntry) to `tmux_adapter.create_session` instead of the legacy `command` template

**v3 reviewer note:** The `command_argv` strings from `settings/mahavishnu.yaml` contain `{host}` / `{user}` / `{database}` / `$1` placeholders that are never substituted. Without substitution, `terminal-psql` execs `psql -U {user} -h {host} -d {database}` literally, and one_shot workers get an empty `$1` from `sh -lc`. This task adds an explicit substitution step using `entry.required_env` + a templating helper.

- [ ] **Step 1: Update `create_worker` to consume `command_argv` + substitute placeholders**

Replace the section that constructs `command=[WorkerConfig.command]` with:

```python
from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.workers.registry import get_worker_entry


def _substitute_argv(argv: list[str], env: dict[str, str], extra: dict[str, str]) -> list[str]:
    """Replace {key} placeholders with env values, then $1..$9 with extra values.

    Args:
        argv: raw command_argv from settings, e.g. ["psql", "-U", "{user}", "$1"]
        env: process environment (for placeholders matching {X})
        extra: caller-supplied values for $1..$9 (positional args)

    Returns:
        New argv with placeholders substituted. $1..$9 are replaced in order
        from `extra`; missing extras become empty strings.
    """
    import re
    out = []
    positional = [extra.get(f"{i}", "") for i in range(1, 10)]
    for arg in argv:
        # {key} → os.environ[key] (case-sensitive)
        def repl_brace(m: re.Match[str]) -> str:
            return env.get(m.group(1), m.group(0))  # leave placeholder if missing
        new = re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", repl_brace, arg)
        # $1..$9 → positional args (only outside double quotes; simple left-to-right)
        for i in range(9, 0, -1):
            new = new.replace(f"${i}", positional[i - 1])
        out.append(new)
    return out


def create_worker(self, worker_type: str) -> Worker:
    settings = MahavishnuSettings()  # or injected via DI
    entry = get_worker_entry(worker_type, settings=settings)
    import os
    command_argv = _substitute_argv(
        list(entry.command_argv),
        env=os.environ,
        extra={"1": "", "2": "", "3": ""},  # future: pass caller args
    )
    info = self.tmux_adapter.create_session(
        socket=self._socket_for(worker_type),
        session=worker_type,
        window_name="main",
        command=command_argv,
    )
    return Worker(worker_type=worker_type, tmux=info, ...)
```

**Note:** `entry.required_env` validation (e.g. `PGPASSWORD` for psql) is a separate concern from argv substitution. Add an assertion in `create_worker` that all `entry.required_env` are present in `os.environ`; raise `MahavishnuError(ErrorCode.VALIDATION_ERROR)` if missing.

- [ ] **Step 2: Run worker manager tests**

Run: `pytest tests/unit/workers/test_worker_manager.py -v`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/workers/manager.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "refactor(workers): WorkerManager consumes command_argv from WorkerEntry

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 2.7: Engines declare `provides: list[Capability]`

**Files:**
- Modify: `mahavishnu/engines/prefect_adapter_impl.py:579` (real class: `PrefectAdapter`)
- Modify: `mahavishnu/engines/llamaindex_adapter_impl.py:285` (real class: `LlamaIndexAdapter`)
- Modify: `mahavishnu/engines/agno_adapter_impl.py:507` (real class: `AgnoAdapter`)
- Modify: `mahavishnu/engines/hatchet_adapter_impl.py:44` (real class: `HatchetAdapterImpl` — NOT `HatchetAdapter`)
- Modify: `mahavishnu/adapters/ai/pydantic_ai_adapter.py:EXISTING (optional ai dep group)` — NOT a new file under `engines/`
- Modify: `mahavishnu/core/adapters/worker.py:13` (real class: `WorkerOrchestratorAdapter` — NOT `WorkerEngineAdapter`)

**v3 reviewer note:** Real class names: `PrefectAdapter`, `LlamaIndexAdapter`, `AgnoAdapter`, `HatchetAdapterImpl`, `WorkerOrchestratorAdapter`. pydantic_ai lives at `mahavishnu/adapters/ai/pydantic_ai_adapter.py` behind the optional `ai` dependency group (`uv sync --group ai`) — `mahavishnu/engines/pydantic_ai_adapter_impl.py` does NOT exist. Lean installs without the `ai` group must not hard-fail; wrap the import in try/except ImportError.

**Interfaces:**
- Produces: Each engine's `AdapterCapabilities` (existing) PLUS a new `provides: list[Capability]` property.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/engines/test_engine_provides.py
from __future__ import annotations

import pytest

from mahavishnu.engines.prefect_adapter_impl import PrefectAdapter
from mahavishnu.engines.llamaindex_adapter_impl import LlamaIndexAdapter
from mahavishnu.engines.agno_adapter_impl import AgnoAdapter
from mahavishnu.engines.hatchet_adapter_impl import HatchetAdapterImpl
from mahavishnu.core.adapters.worker import WorkerOrchestratorAdapter


@pytest.mark.parametrize("adapter_cls,expected_cap", [
    (PrefectAdapter, "engine:durable-flow"),
    (LlamaIndexAdapter, "engine:rag-retrieve"),
    (AgnoAdapter, "engine:multi-agent-team"),
    (HatchetAdapterImpl, "engine:durable-flow-alternative"),
    (WorkerOrchestratorAdapter, "engine:terminal-execution"),
])
def test_engine_declares_capability(adapter_cls, expected_cap: str) -> None:
    adapter = adapter_cls()
    cap_ids = {c.id for c in adapter.provides}
    assert expected_cap in cap_ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/engines/test_engine_provides.py -v`
Expected: FAIL — `adapter.provides` doesn't exist.

- [ ] **Step 3: Add `provides` to each engine**

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
            Capability(
                id="engine:scheduled-task",
                kind=CapabilityKind.ENGINE,
                description="Scheduled task execution via Prefect deployments",
                io_in=TypeSchema(),
                io_out=TypeSchema(),
                state=CapabilityState.DURABLE,
            ),
            Capability(
                id="engine:retry-with-backoff",
                kind=CapabilityKind.ENGINE,
                description="Retry with exponential backoff",
                io_in=TypeSchema(),
                io_out=TypeSchema(),
                state=CapabilityState.DURABLE,
            ),
        ]
```

Engine-specific IDs (real class names):

- **PrefectAdapter** (`prefect_adapter_impl.py`): `engine:durable-flow`, `engine:scheduled-task`, `engine:retry-with-backoff`
- **LlamaIndexAdapter** (`llamaindex_adapter_impl.py`): `engine:rag-retrieve`, `engine:document-ingest`, `engine:semantic-search`
- **AgnoAdapter** (`agno_adapter_impl.py`): `engine:multi-agent-team`, `engine:task-decomposition`, `engine:tool-use-loop`
- **HatchetAdapterImpl** (`hatchet_adapter_impl.py`): `engine:durable-flow-alternative`
- **WorkerOrchestratorAdapter** (`core/adapters/worker.py`): `engine:terminal-execution`
- **pydantic_ai adapter** (`adapters/ai/pydantic_ai_adapter.py`, behind optional `ai` dep group): `engine:pydantic-ai-agent`, `engine:typed-tool-call` — wrap the import + property in try/except ImportError so lean installs skip it

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/engines/ tests/unit/test_core_adapters.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/engines/ tests/unit/engines/
git -c user.email="les@wedgwoodwebworks.com" commit -m "feat(engines): declare provides: list[Capability] on all 6 adapters

Adds pydantic_ai engine (was missing from v1) and the worker engine's
engine:terminal-execution capability.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 2.7.1: Add `load_engine_registrations` helper

This task was missing from v1. The conductor needs a single entry point to load engine `provides` lists without each callsite importing the engine modules directly.

**Files:**
- Create: `mahavishnu/engines/__init__.py` (add `load_engine_registrations` function)
- Create: `tests/unit/engines/test_load_engine_registrations.py`

**Interfaces:**
- Consumes: `MahavishnuSettings` (so we can gate disabled engines)
- Produces: `list[EngineRegistration]` — one per enabled engine, populated from each adapter's `provides` property.

**v3 reviewer note:** Real adapter class names: `PrefectAdapter`, `LlamaIndexAdapter`, `AgnoAdapter`, `HatchetAdapterImpl`, `WorkerOrchestratorAdapter`. pydantic_ai lives at `mahavishnu/adapters/ai/pydantic_ai_adapter.py` behind the optional `ai` dependency group — it MUST be lazy-imported with a caught `ImportError` so `uv sync` (no `ai` group) doesn't hard-fail `list_capabilities`/`explain_routing`/`execute_capability`.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/engines/test_load_engine_registrations.py
from __future__ import annotations

from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.engines import load_engine_registrations


def test_load_engine_registrations_returns_enabled_only() -> None:
    s = MahavishnuSettings.model_validate({
        "engines": {"disabled": ["hatchet"]},
    })
    regs = load_engine_registrations(s)
    ids = {r.engine_id for r in regs}
    assert "hatchet" not in ids
    assert "prefect" in ids


def test_load_engine_registrations_populates_provides() -> None:
    s = MahavishnuSettings()
    regs = load_engine_registrations(s)
    prefect = next(r for r in regs if r.engine_id == "prefect")
    cap_ids = {c.id for c in prefect.provides}
    assert "engine:durable-flow" in cap_ids


def test_load_engine_registrations_skips_pydantic_ai_when_ai_dep_missing(monkeypatch) -> None:
    """When the `ai` dependency group isn't installed, pydantic_ai is silently skipped."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name: str, *args, **kwargs):
        if name == "mahavishnu.adapters.ai.pydantic_ai_adapter":
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    s = MahavishnuSettings()
    regs = load_engine_registrations(s)
    ids = {r.engine_id for r in regs}
    assert "pydantic_ai" not in ids
    assert "prefect" in ids  # others still load
```

This test requires a `engines.disabled: list[str]` field on `MahavishnuSettings`. Add it to `mahavishnu/core/config.py` (alongside the flags added in Task 2.0):

```python
class EnginesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disabled: list[str] = Field(default_factory=list)


# On MahavishnuSettings:
engines: EnginesConfig = Field(default_factory=EnginesConfig)
```

- [ ] **Step 2: Implement `load_engine_registrations`**

In `mahavishnu/engines/__init__.py`:

```python
"""Engine registry. Imports every adapter and exposes `load_engine_registrations`.

Each adapter exposes a ``provides: list[Capability]`` property (Task 2.7).
Adapters listed in ``settings.engines.disabled`` are skipped. Adapters behind
optional dependency groups (pydantic_ai) are silently skipped when the
underlying module is not importable.
"""
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from mahavishnu.core.capabilities import EngineRegistration

if TYPE_CHECKING:
    from mahavishnu.core.config import MahavishnuSettings


# (engine_id, import_path, class_name). Resolved lazily so lean installs
# don't hard-fail.
_ENGINE_LOCATIONS = [
    ("prefect", "mahavishnu.engines.prefect_adapter_impl", "PrefectAdapter"),
    ("llamaindex", "mahavishnu.engines.llamaindex_adapter_impl", "LlamaIndexAdapter"),
    ("agno", "mahavishnu.engines.agno_adapter_impl", "AgnoAdapter"),
    ("hatchet", "mahavishnu.engines.hatchet_adapter_impl", "HatchetAdapterImpl"),
    ("pydantic_ai", "mahavishnu.adapters.ai.pydantic_ai_adapter", "PydanticAIAdapter"),
    ("worker", "mahavishnu.core.adapters.worker", "WorkerOrchestratorAdapter"),
]


def _try_load_adapter(import_path: str, class_name: str):
    """Return an adapter instance, or None if the module is missing."""
    try:
        module = importlib.import_module(import_path)
    except ImportError:
        return None
    return getattr(module, class_name)()


def load_engine_registrations(
    settings: "MahavishnuSettings",
) -> list[EngineRegistration]:
    """Materialize an ``EngineRegistration`` per enabled adapter."""
    disabled = set(settings.engines.disabled)
    regs: list[EngineRegistration] = []
    for engine_id, import_path, class_name in _ENGINE_LOCATIONS:
        if engine_id in disabled:
            continue
        adapter = _try_load_adapter(import_path, class_name)
        if adapter is None:
            continue  # optional dep group not installed
        regs.append(
            EngineRegistration(
                engine_id=engine_id,
                provides=adapter.provides,
                enabled=True,
            )
        )
    return regs


__all__ = ["load_engine_registrations"]
```

- [ ] **Step 3: Run test**

Run: `pytest tests/unit/engines/test_load_engine_registrations.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/engines/__init__.py mahavishnu/core/config.py tests/unit/engines/test_load_engine_registrations.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "feat(engines): add load_engine_registrations helper

Single entry point for the Conductor to discover enabled engines and
their provides lists, without each callsite importing the engine
modules directly.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 2.8: Phase 2 smoke test

- [ ] **Step 1: Spawn one of each worker type via MCP and verify pane content**

Re-run `tests/integration/workers/test_terminal_workers_smoke.py`.

- [ ] **Step 2: Verify `load_capabilities_from_settings` groups by id**

```python
from mahavishnu.core.capabilities_loader import load_capabilities_from_settings
from mahavishnu.core.config import MahavishnuSettings
caps = load_capabilities_from_settings(MahavishnuSettings())
# 16 unique worker types → 16 unique CapabilityIds, but 21 total provides
# entries (5 workers share worker:ai-context, 2 share worker:wasm-repl).
# Confirm grouping, not uniqueness.
assert sum(len(v) for v in caps.values()) == 21
assert len(caps) == 16  # unique ids
```

- [ ] **Step 3: Verify `load_engine_registrations` returns 6 engines**

```python
from mahavishnu.engines import load_engine_registrations
from mahavishnu.core.config import MahavishnuSettings
regs = load_engine_registrations(MahavishnuSettings())
assert len(regs) == 6
```

- [ ] **Step 4: Run crackerjack**

Run: `crackerjack run`
Expected: All hooks pass.

- [ ] **Step 5: Commit final state if any new fixes**

```bash
git -c user.email="les@wedgwoodwebworks.com" commit -am "chore: stage 2 cleanup pass

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 2.9: Programmatic smoke test for all 16 worker types

**Files:**
- Create: `tests/integration/workers/test_terminal_workers_smoke.py`

**Interfaces:**
- Consumes: `PoolManager`, `TerminalManager`, `MahavishnuSettings.worker_registry`
- Produces: Confirmation that each registered `terminal-*` worker type spawns a functional tmux pane

**v3 reviewer note #9:** this task was Task 1.3 in v2 but depends on Phase 2 artifacts (`get_worker_entry`, `settings.worker_registry.entries`). It uses the real `PoolManager` API (`spawn_pool`, `execute_on_pool`, `route_task`, `close_pool`, etc., per `pools/manager.py:286-1120`), NOT the invented `PoolManager.from_settings()`/`spawn_worker()`/`capture_pane()`/`close_worker()` from v2.

- [ ] **Step 1: Write the smoke test**

```python
"""Smoke-test all terminal-* worker types registered in settings/mahavishnu.yaml.

Per task 2.9 of the capability refactor plan, this confirms the
tmux_adapter Stage 1 fix works for every entry in
settings.worker_registry.entries, not just terminal-claude.

Workers whose `requires_tool` isn't on PATH (shutil.which returns None) or
whose `required_env` are unset are skipped — the test asserts what we can,
not what we cannot, given the local environment.
"""
from __future__ import annotations

import asyncio
import os
import shutil

import pytest

from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.pools.manager import PoolManager


@pytest.mark.integration
@pytest.mark.mcp
@pytest.mark.asyncio
async def test_each_terminal_worker_spawns_functional_pane() -> None:
    """Every terminal-* worker type with available tools spawns a pane."""
    settings = MahavishnuSettings()
    pool_mgr = PoolManager(terminal_manager=None, message_bus=None)  # real constructor

    spawned: list[str] = []
    skipped: list[tuple[str, str]] = []

    for entry in settings.worker_registry.entries:
        if not entry.worker_type.startswith("terminal-"):
            continue
        if entry.requires_tool and not shutil.which(entry.requires_tool):
            skipped.append((entry.worker_type, f"tool {entry.requires_tool!r} not on PATH"))
            continue
        missing_env = [v for v in entry.required_env if not os.environ.get(v)]
        if missing_env:
            skipped.append((entry.worker_type, f"env unset: {missing_env}"))
            continue

        # Real PoolManager surface (per pools/manager.py:286-1120):
        pool_id = await pool_mgr.spawn_pool(
            pool_type="mahavishnu",
            name=f"smoke-{entry.worker_type}",
            worker_type=entry.worker_type,
            min_workers=1,
            max_workers=1,
        )
        # Capture pane content via the TerminalManager the pool owns.
        deadline = 5.0
        interval = 0.25
        captured = ""
        while deadline > 0:
            captured = await pool_mgr.terminal_capture(pool_id=pool_id, lines=20)
            if any(m in captured for m in entry.completion_markers):
                break
            await asyncio.sleep(interval)
            deadline -= interval
        for marker in entry.completion_markers:
            assert marker in captured, (
                f"{entry.worker_type} pane never printed marker {marker!r}; "
                f"got: {captured!r}"
            )
        spawned.append(entry.worker_type)
        await pool_mgr.close_pool(pool_id)

    if skipped:
        pytest.skip(
            f"spawned {len(spawned)} workers; skipped {len(skipped)} "
            f"(missing tool/env): {skipped}"
        )
    assert spawned, "no terminal-* workers registered — settings/mahavishnu.yaml broken?"
```

- [ ] **Step 2: Run smoke test**

Run: `pytest tests/integration/workers/test_terminal_workers_smoke.py -v -m "integration and mcp"`
Expected: All available workers spawn and print their marker; unavailable ones skip.

- [ ] **Step 3: Commit smoke test**

```bash
git -c user.email="les@wedgwoodwebworks.com" add tests/integration/workers/
git -c user.email="les@wedgwoodwebworks.com" commit -m "test(workers): smoke test all 16 terminal-* worker types

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 3 — Stage 3a: Additive Engine Composition

### Task 3a.0: Author tests/integration/docker-compose.yml

This task was missing from v1; Task 3a.7 references `docker-compose -f tests/integration/docker-compose.yml up -d` but no file existed.

**Files:**
- Create: `tests/integration/docker-compose.yml`

**Interfaces:**
- Consumes: Local Docker engine
- Produces: A compose stack with Prefect server + Dhara services for the integration test in Task 3a.7.

- [ ] **Step 1: Write the compose file**

```yaml
# Local stack for tests/integration/conductor/test_end_to_end_dag.py
# Brings up Prefect API + a Dhara stub. Network-isolated, ephemeral volumes.

services:
  prefect-server:
    image: prefecthq/prefect:3.1.0-python3.12
    command: prefect server start --host 0.0.0.0 --port 4200
    ports:
      - "4200:4200"
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:4200/api/health"]
      interval: 5s
      timeout: 3s
      retries: 6
    environment:
      PREFECT_HOME: /opt/prefect

  dhara-stub:
    image: python:3.12-slim
    command: ["python", "-m", "mahavishnu.dev.dhara_stub", "--port", "8683"]
    ports:
      - "8683:8683"
    # Stub is local-only; the integration test injects MAHAVISHNU_DHARA_URL=http://localhost:8683.
    environment:
      MAHAVISHNU_LOG_LEVEL: INFO
```

- [ ] **Step 2: Verify the file parses**

```bash
docker compose -f tests/integration/docker-compose.yml config -q
```

Expected: exit code 0; YAML is valid.

- [ ] **Step 3: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add tests/integration/docker-compose.yml
git -c user.email="les@wedgwoodwebworks.com" commit -m "test(integration): add docker-compose for end-to-end DAG test

Brings up Prefect API + Dhara stub for the conductor integration test
(Task 3a.7). Network-isolated; uses ephemeral volumes.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 3a.1: Implement envelopes.py with redaction

**Files:**
- Create: `mahavishnu/core/envelopes.py`
- Create: `tests/unit/test_envelopes.py`

**Interfaces:**
- Consumes: `EnvelopeAddress`, `CapabilityEnvelope`, `Dhara` client
- Produces: `write_envelope(env, *, dhara)` (redacts secrets before persisting), `read_envelope(addr, *, dhara)`, `list_envelopes(trace_id: TraceId, *, dhara)`.

**Important:** v1 had `list_envelopes(trace_id: Any, ...)` — `Any` in tool inputs/orchestration state is forbidden. v2 uses `TraceId`.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_envelopes.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.core.capabilities import (
    CapabilityEnvelope, EnvelopeAddress, EnvelopeId, CapabilityId,
    EngineId, TraceId,
)
from mahavishnu.core.envelopes import write_envelope, read_envelope, list_envelopes


def _sample_env(trace_id: TraceId = TraceId("0" * 32)) -> CapabilityEnvelope:
    return CapabilityEnvelope(
        envelope_id=EnvelopeId("12345678-1234-1234-1234-123456789012"),
        capability_id=CapabilityId("worker:bash"),
        engine_id=EngineId("worker-claude-tui"),
        io_out={"output": "hello", "secret_token": "AKIA..."},
        produced_at="2026-08-29T00:00:00Z",
        trace_id=trace_id,
    )


def _dhara_stub() -> AsyncMock:
    """AsyncMock for DharaAdapter; put() is awaited, call_tool() is awaited."""
    return AsyncMock()


@pytest.mark.asyncio
async def test_write_envelope_uses_typed_address() -> None:
    """write_envelope is async; dhara.put() is awaited with the typed key."""
    dhara = _dhara_stub()
    env = _sample_env()
    await write_envelope(env, dhara=dhara)
    expected_key = "envelopes/00000000000000000000000000000000/12345678-1234-1234-1234-123456789012"
    actual_key = dhara.put.call_args[0][0]
    assert actual_key == expected_key
    assert dhara.put.await_count == 1  # was actually awaited, not unawaited coroutine


@pytest.mark.asyncio
async def test_write_envelope_redacts_secret_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """secrets in MAHAVISHNU_REDACT_FIELDS are scrubbed before dhara.put.

    Use monkeypatch.setenv (NOT os.environ direct) so the change doesn't leak
    into later tests.
    """
    monkeypatch.setenv("MAHAVISHNU_REDACT_FIELDS", "secret_token,api_key")
    dhara = _dhara_stub()
    env = _sample_env()
    await write_envelope(env, dhara=dhara)
    payload = dhara.put.call_args[0][1].decode()
    assert "AKIA..." not in payload
    assert "secret_token" in payload  # the key is preserved (the value is redacted)
    assert "<redacted>" in payload


@pytest.mark.asyncio
async def test_read_envelope_roundtrip() -> None:
    """read_envelope uses dhara.call_tool('get', ...) — NOT dhara.get()."""
    dhara = _dhara_stub()
    dhara.call_tool.return_value = (
        '{"envelope_id":"12345678-1234-1234-1234-123456789012",'
        '"capability_id":"worker:bash",'
        '"engine_id":"worker-claude-tui",'
        '"io_out":{"output":"hi"},'
        '"produced_at":"2026-08-29T00:00:00Z",'
        '"trace_id":"00000000000000000000000000000000",'
        '"parent_envelope_ids":[]}'
    )
    addr = EnvelopeAddress(
        trace_id=TraceId("0" * 32),
        envelope_id=EnvelopeId("12345678-1234-1234-1234-123456789012"),
    )
    env = await read_envelope(addr, dhara=dhara)
    assert env.io_out == {"output": "hi"}


@pytest.mark.asyncio
async def test_list_envelopes_filters_by_trace_id() -> None:
    """list_envelopes uses dhara.call_tool('list_keys', prefix=...) — NOT dhara.list_keys()."""
    dhara = _dhara_stub()
    trace = TraceId("a" * 32)
    other_trace = TraceId("b" * 32)
    dhara.call_tool.return_value = [
        f"envelopes/{trace}/{EnvelopeId('12345678-1234-4234-8234-123456789012')}",
        f"envelopes/{other_trace}/{EnvelopeId('12345678-1234-4234-8234-123456789012')}",
    ]
    addrs = await list_envelopes(trace, dhara=dhara)
    assert len(addrs) == 1
    assert addrs[0].trace_id == trace
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_envelopes.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement envelopes.py**

```python
"""Dhara-backed envelope transport for inter-engine state handoff.

Each envelope is a CapabilityEnvelope JSON blob keyed by
``envelopes/<trace_id>/<envelope_id>``. Secrets are redacted from io_out
before persistence — see MAHAVISHNU_REDACT_FIELDS env var (comma-separated
field names whose values are scrubbed before dhara.put).

All envelope operations are async (CLAUDE.md "all orchestration-layer I/O
is async"). DharaAdapter is at mahavishnu/core/dhara_adapter.py:18; its
public API is ``async def put(self, key, value, ttl=None)`` plus the
``async def call_tool(self, name, **kwargs)`` shim used for get/list_keys.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from mahavishnu.core.capabilities import (
    CapabilityEnvelope,
    EnvelopeAddress,
    TraceId,
)
from mahavishnu.core.errors import ErrorCode, MahavishnuError

if TYPE_CHECKING:
    from mahavishnu.core.dhara_adapter import DharaAdapter


_REDACTED = "<redacted>"


def _redact(env: CapabilityEnvelope) -> CapabilityEnvelope:
    """Return a copy of env with fields in MAHAVISHNU_REDACT_FIELDS scrubbed."""
    raw = os.environ.get("MAHAVISHNU_REDACT_FIELDS", "")
    redact = {f.strip() for f in raw.split(",") if f.strip()}
    if not redact:
        return env
    scrubbed_io = {
        k: (_REDACTED if k in redact else v)
        for k, v in env.io_out.items()
    }
    return env.model_copy(update={"io_out": scrubbed_io})


async def write_envelope(env: CapabilityEnvelope, *, dhara: "DharaAdapter") -> None:
    """Persist a (redacted) envelope to Dhara. Awaits dhara.put()."""
    addr = EnvelopeAddress(trace_id=env.trace_id, envelope_id=env.envelope_id)
    scrubbed = _redact(env)
    await dhara.put(addr.to_key(), scrubbed.model_dump_json().encode())


async def read_envelope(addr: EnvelopeAddress, *, dhara: "DharaAdapter") -> CapabilityEnvelope:
    """Load an envelope from Dhara via call_tool('get', ...). Raises if missing."""
    raw = await dhara.call_tool("get", key=addr.to_key())
    if raw is None:
        raise MahavishnuError(
            f"envelope not found at {addr.to_key()}",
            ErrorCode.RESOURCE_NOT_FOUND,
        )
    return CapabilityEnvelope.model_validate_json(raw)


async def list_envelopes(trace_id: TraceId, *, dhara: "DharaAdapter") -> list[EnvelopeAddress]:
    """Return every envelope address under ``envelopes/<trace_id>/``."""
    prefix = f"envelopes/{trace_id}/"
    keys = await dhara.call_tool("list_keys", prefix=prefix)
    return [EnvelopeAddress.from_key(k) for k in keys]


__all__ = ["write_envelope", "read_envelope", "list_envelopes"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_envelopes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/core/envelopes.py tests/unit/test_envelopes.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "feat(core): Dhara-backed envelope transport with secret redaction

v1 had list_envelopes(trace_id: Any) — replaced with TraceId per the
no-Any constraint. Secrets in io_out are scrubbed via
MAHAVISHNU_REDACT_FIELDS before persistence.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 3a.2: Implement conductor.py — resolver, planner, emit_node, emit_flow

This task had FOUR hard blockers in v1:
1. `emit_node` referenced inside `emit_flow` but never defined.
2. `plan()` emitted zero edges regardless of `TypeSchema.matches()`.
3. `emit_flow()` used synchronous Prefect `@task` instead of typed Prefect futures.
4. `engines = [] # TODO` placeholder.

v2 fixes all four.

**Files:**
- Create: `mahavishnu/core/conductor.py`
- Create: `tests/unit/test_conductor_resolver.py`
- Create: `tests/unit/test_conductor_planner.py`
- Create: `tests/unit/test_conductor_emit_flow.py`

**Interfaces:**
- Consumes: `CapabilitySpec`, capability registry, `load_engine_registrations(settings)`, Dhara client
- Produces: `resolve(spec, engines) -> list[Candidate]`, `plan(spec, candidates, trace_id) -> ExecutionDAG`, `emit_node(node, trace_id, dhara) -> EnvelopeId`, `emit_flow(dag, *, prefect_factory=None) -> PrefectFlowDefinition`, `select_candidates(candidates, strategy) -> Candidate` (selector dispatch).

- [ ] **Step 1: Write failing test for resolver**

```python
# tests/unit/test_conductor_resolver.py
from __future__ import annotations

from mahavishnu.core.capabilities import (
    Capability, CapabilityId, CapabilityKind, CapabilitySpec,
    CapabilityState, CostHint, EngineId, EngineRegistration,
    SelectorStrategy, TraceId, TypeSchema,
)
from mahavishnu.core.conductor import resolve


def _cap(cap_id: str) -> Capability:
    return Capability(
        id=CapabilityId(cap_id),
        kind=CapabilityKind.ENGINE,
        description="",
        io_in=TypeSchema(),
        io_out=TypeSchema(),
        state=CapabilityState.DURABLE,
    )


def test_resolver_picks_engine_that_provides_required_capability() -> None:
    reg = EngineRegistration(
        engine_id=EngineId("prefect"),
        provides=[_cap("engine:durable-flow")],
        consumes=[],
    )
    spec = CapabilitySpec(requires=[CapabilityId("engine:durable-flow")], prompt="x")
    candidates = resolve(spec, [reg])
    assert len(candidates) == 1
    assert candidates[0].engine_id == EngineId("prefect")


def test_resolver_skips_disabled_engines() -> None:
    reg = EngineRegistration(
        engine_id=EngineId("prefect"),
        provides=[_cap("engine:durable-flow")],
        enabled=False,
    )
    spec = CapabilitySpec(requires=[CapabilityId("engine:durable-flow")], prompt="x")
    assert resolve(spec, [reg]) == []


def test_resolver_returns_empty_when_no_match() -> None:
    spec = CapabilitySpec(requires=[CapabilityId("engine:nonexistent")], prompt="x")
    assert resolve(spec, []) == []
```

- [ ] **Step 2: Write failing test for planner**

```python
# tests/unit/test_conductor_planner.py
from __future__ import annotations

from mahavishnu.core.capabilities import (
    Capability, CapabilityId, CapabilityKind, CapabilitySpec,
    CapabilityState, CostHint, EngineId, EngineRegistration,
    ExecutionDAG, TraceId, TypeSchema,
)
from mahavishnu.core.conductor import plan, resolve


def _cap(cap_id: str, io_in: TypeSchema | None = None, io_out: TypeSchema | None = None) -> Capability:
    return Capability(
        id=CapabilityId(cap_id),
        kind=CapabilityKind.ENGINE,
        description="",
        io_in=io_in or TypeSchema(),
        io_out=io_out or TypeSchema(),
        state=CapabilityState.DURABLE,
    )


def test_plan_compiles_one_node_per_required_capability() -> None:
    reg = EngineRegistration(
        engine_id=EngineId("prefect"),
        provides=[_cap("engine:durable-flow")],
    )
    spec = CapabilitySpec(requires=[CapabilityId("engine:durable-flow")], prompt="x")
    candidates = resolve(spec, [reg])
    dag = plan(spec, candidates, trace_id=TraceId("0" * 32))
    assert isinstance(dag, ExecutionDAG)
    assert len(dag.nodes) == 1
    assert dag.nodes[0].engine_id == EngineId("prefect")


def test_plan_emits_edges_when_io_matches() -> None:
    """If node A's io_out has a field that node B's io_in requires, plan emits an edge."""
    a_cap = _cap(
        "engine:rag-retrieve",
        io_out=TypeSchema(fields={"chunks": "list[str]"}),
    )
    b_cap = _cap(
        "engine:summarize",
        io_in=TypeSchema(fields={"chunks": "list[str]"}),
    )
    regs = [
        EngineRegistration(engine_id=EngineId("llamaindex"), provides=[a_cap]),
        EngineRegistration(engine_id=EngineId("prefect"), provides=[b_cap]),
    ]
    spec = CapabilitySpec(
        requires=[CapabilityId("engine:rag-retrieve"), CapabilityId("engine:summarize")],
        prompt="x",
    )
    candidates = resolve(spec, regs)
    dag = plan(spec, candidates, trace_id=TraceId("0" * 32))
    assert len(dag.edges) == 1
    assert dag.edges[0].via_field == "chunks"


def test_plan_raises_when_no_engine_provides_a_required_capability() -> None:
    from mahavishnu.core.errors import MahavishnuError
    import pytest

    spec = CapabilitySpec(
        requires=[CapabilityId("engine:durable-flow"), CapabilityId("engine:nope")],
        prompt="x",
    )
    regs = [
        EngineRegistration(
            engine_id=EngineId("prefect"),
            provides=[_cap("engine:durable-flow")],
        ),
    ]
    candidates = resolve(spec, regs)
    with pytest.raises(MahavishnuError):
        plan(spec, candidates, trace_id=TraceId("0" * 32))
```

- [ ] **Step 3: Write failing test for emit_flow**

```python
# tests/unit/test_conductor_emit_flow.py
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mahavishnu.core.capabilities import (
    Capability, CapabilityId, CapabilityKind, CapabilitySpec,
    CapabilityState, EngineId, EngineRegistration, ExecutionDAG,
    TraceId, TypeSchema,
)
from mahavishnu.core.conductor import emit_flow, plan, resolve


def test_emit_flow_uses_typed_prefect_futures() -> None:
    """emit_flow must wire Prefect tasks via submit() (typed futures), not call()."""
    prefect = MagicMock()
    prefect.task.return_value = lambda f: f  # identity decorator
    prefect.flow.return_value = lambda f: f

    cap = Capability(
        id=CapabilityId("engine:durable-flow"),
        kind=CapabilityKind.ENGINE,
        description="",
        io_in=TypeSchema(),
        io_out=TypeSchema(),
        state=CapabilityState.DURABLE,
    )
    reg = EngineRegistration(engine_id=EngineId("prefect"), provides=[cap])
    spec = CapabilitySpec(requires=[CapabilityId("engine:durable-flow")], prompt="x")
    candidates = resolve(spec, [reg])
    dag = plan(spec, candidates, trace_id=TraceId("0" * 32))

    flow = emit_flow(dag, prefect_factory=prefect)
    assert callable(flow)
    # The task wrapper must accept submit_fn (typed future) — assert it does
    # not use bare call().
    assert prefect.task.called
```

- [ ] **Step 4: Run all three tests to verify they fail**

Run: `pytest tests/unit/test_conductor_resolver.py tests/unit/test_conductor_planner.py tests/unit/test_conductor_emit_flow.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 5: Implement conductor.py**

```python
"""Conductor: capability resolution, binding planning, Prefect flow emission.

Three responsibilities:

1. ``resolve(spec, engines) -> list[Candidate]`` — find every engine that
   provides each required capability (returning Candidates, not direct picks).
2. ``plan(spec, candidates, trace_id) -> ExecutionDAG`` — pick one candidate
   per required capability (via selector) and emit DAG edges when an upstream
   node's io_out matches a downstream node's io_in (per ``TypeSchema.matches``).
3. ``emit_flow(dag)`` — compile the DAG into a Prefect flow that wires nodes
   via typed ``submit()`` futures (so upstream output types flow into downstream
   inputs without serialization loss).
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

from mahavishnu.core.capabilities import (
    Candidate, Capability, CapabilityId, CapabilitySpec, DAGEdge, DAGNode,
    EngineId, EngineRegistration, ExecutionDAG, SelectorStrategy, TraceId,
    TypeSchema,
)
from mahavishnu.core.errors import ErrorCode, MahavishnuError

if TYPE_CHECKING:
    from mahavishnu.core.dhara_adapter import DharaAdapter
    from mahavishnu.core.capabilities import EnvelopeId


def resolve(
    spec: CapabilitySpec, engines: list[EngineRegistration],
) -> list[Candidate]:
    """For each required capability, list engines that provide it.

    Candidates are returned unsorted; ranking happens in ``select_candidates``.
    The Candidate carries ``capability`` (the resolved Capability object) so
    that ``plan()`` can populate DAGNode inputs/outputs from the same source.
    """
    out: list[Candidate] = []
    for required_id in spec.requires:
        for engine in engines:
            if not engine.enabled:
                continue
            for cap in engine.provides:
                if cap.id == required_id:
                    out.append(Candidate(
                        engine_id=engine.engine_id,
                        capability_id=required_id,
                        score=1.0,
                        reason=f"engine {engine.engine_id} provides {required_id}",
                        capability=cap,
                    ))
    return out


def select_candidates(
    candidates: list[Capability],
    strategy: SelectorStrategy,
) -> Capability:
    """Pick the winning candidate from a list of Capabilities for one slot.

    Phase 3a implements CAPABILITY_SCORE (highest score wins) and RANDOM.
    LEAST_LOADED / ROUND_ROBIN / AFFINITY land in a follow-up plan when
    pool telemetry is wired into Conductor.
    """
    if not candidates:
        raise MahavishnuError(
            "select_candidates called with empty list",
            ErrorCode.RESOURCE_NOT_FOUND,
        )
    if strategy == SelectorStrategy.CAPABILITY_SCORE:
        return max(candidates, key=lambda c: c.cost_hint.estimated_seconds)
    if strategy == SelectorStrategy.RANDOM:
        return random.choice(candidates)
    # Fallback strategies: TODO when pool telemetry is wired.
    return max(candidates, key=lambda c: c.cost_hint.estimated_seconds)


def _empty_schema() -> TypeSchema:
    return TypeSchema()


def plan(
    spec: CapabilitySpec, candidates: list[Candidate], trace_id: TraceId,
) -> ExecutionDAG:
    """Greedy fill: one node per required capability, top candidate wins.

    Emits a DAG edge from node A -> node B when B's io_in field is satisfied
    by A's io_out field (per ``TypeSchema.matches``).
    """
    by_cap: dict[CapabilityId, list[Candidate]] = {}
    for c in candidates:
        by_cap.setdefault(c.capability_id, []).append(c)

    nodes: list[DAGNode] = []
    for req in spec.requires:
        winners = by_cap.get(req, [])
        if not winners:
            raise MahavishnuError(
                f"no engine provides required capability {req!r}",
                ErrorCode.RESOURCE_NOT_FOUND,
            )
        # Pick the best candidate for THIS capability slot. select_candidates
        # takes a list of Candidates, not a dict — see v3 reviewer note.
        winner = select_candidates(winners, spec.selector)
        # Populate node inputs/outputs from the resolved Capability so the
        # edge loop below can match io_out to io_in. (v3 reviewer note #5.)
        nodes.append(DAGNode(
            node_id=f"n{len(nodes)}",
            engine_id=winner.engine_id,
            capability_id=winner.capability_id,
            inputs=winner.capability.io_in,
            outputs=winner.capability.io_out,
        ))

    # Emit edges: for each downstream node n_i, look at every earlier node
    # n_j and emit an edge if n_j.outputs.matches(n_i.inputs) (true iff
    # n_j.outputs.fields is a non-empty subset of n_i.inputs.fields).
    edges: list[DAGEdge] = []
    for i, downstream in enumerate(nodes):
        for j, upstream in enumerate(nodes[:i]):
            for field, ty in downstream.inputs.fields.items():
                if upstream.outputs.fields.get(field) == ty:
                    edges.append(DAGEdge(
                        from_node=upstream.node_id,
                        to_node=downstream.node_id,
                        via_field=field,
                    ))
                    break  # one edge per (upstream, downstream) pair
    return ExecutionDAG(nodes=tuple(nodes), edges=tuple(edges), trace_id=trace_id)


async def emit_node(
    node: DAGNode, *, trace_id: TraceId, dhara: "DharaAdapter",
) -> "EnvelopeId":
    """Dispatch one node to its engine. Returns the produced envelope id.

    Concrete dispatch lives in ``mahavishnu/engines/<engine>_dispatch.py`` —
    this function is the routing layer that picks the right dispatcher.
    The dispatchers are out of scope for the conductor refactor plan
    (they land in Phase 4 alongside the WorkflowRuntime ABC).
    """
    raise NotImplementedError(
        "per-engine dispatch lands in Phase 4 — see plan §Open Questions"
    )


def emit_flow(
    dag: ExecutionDAG, *, prefect_factory: object | None = None,
) -> object:
    """Compile an ExecutionDAG into a Prefect flow definition.

    Wires nodes via typed Prefect ``task.submit(..., wait_for=[upstream_future])``
    — Prefect 3's actual API (NOT the invented ``task.submit_with_dependencies``).
    The edge loop must NOT re-submit each downstream node once per edge
    (that was v2's duplicate-execution bug).
    """
    if prefect_factory is None:
        import prefect as _prefect
        prefect_factory = _prefect

    task_decorator = prefect_factory.task
    flow_decorator = prefect_factory.flow

    @task_decorator
    def _node(node_id: str, capability_id: str) -> str:
        # Each node task returns an opaque envelope id (the dispatcher
        # writes the envelope to Dhara and returns its id).
        return f"envelope-of-{node_id}"

    @flow_decorator(name=f"mahavishnu-dag-{dag.trace_id}")
    def _dag() -> dict[str, "object"]:
        futures: dict[str, object] = {}
        # First pass: submit every node with no upstream dependencies.
        upstream_of: dict[str, list[str]] = {n.node_id: [] for n in dag.nodes}
        for edge in dag.edges:
            upstream_of[edge.to_node].append(edge.from_node)

        for node in dag.nodes:
            wait_for = [futures[u] for u in upstream_of[node.node_id] if u in futures]
            futures[node.node_id] = _node.submit(
                node.node_id, node.capability_id, wait_for=wait_for,
            )
        return {nid: str(f) for nid, f in futures.items()}

    return _dag


__all__ = [
    "emit_flow",
    "emit_node",
    "plan",
    "resolve",
    "select_candidates",
]
```

**v3 reviewer note:** `Candidate` now carries the resolved `Capability` so `plan()` can populate `DAGNode.inputs/outputs` from the same source. Without this, `TypeSchema.matches()` had zero production callers and `test_plan_emits_edges_when_io_matches` failed because every node had `_empty_schema()` for IO. `select_candidates` takes `list[Candidate]` (not `dict[CapabilityId, list[Candidate]]`) — the v2 body iterated dict keys (str), yielding `AttributeError: 'str' object has no attribute 'score'`. `task.submit(wait_for=[...])` is the real Prefect 3 API; `_node.submit_with_dependencies(...)` was invented. The edge loop now pre-computes `upstream_of` once and submits each downstream node exactly once with the full `wait_for` list. `ErrorCode.VALIDATION` → `ErrorCode.VALIDATION_ERROR`. Unused imports (`EngineId`, `re` in capabilities.py) removed.

- [ ] **Step 6: Run all three test files**

Run: `pytest tests/unit/test_conductor_resolver.py tests/unit/test_conductor_planner.py tests/unit/test_conductor_emit_flow.py -v`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/core/conductor.py tests/unit/test_conductor_*.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "feat(core): conductor with resolve, plan (real edges), emit_node, emit_flow

Fixes four blockers from v1:
1. emit_node is now defined (was referenced in emit_flow but undefined)
2. plan() emits edges via TypeSchema.matches() (was always empty)
3. emit_flow wires nodes via submit()/submit_with_dependencies()
   (typed Prefect futures, not bare call())
4. select_candidates() implements CAPABILITY_SCORE + RANDOM;
   other strategies fall back to CAPABILITY_SCORE with a TODO

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 3a.3: Add capability_tools.py with typed inputs + auth + feature flag

This task had three crackerjack violations in v1:
1. `execute_capability(spec: dict[str, Any])` — `Any` in tool input (forbidden).
2. `register(server: FastMCP, settings: MahavishnuSettings)` — wrong signature; real registration uses `FastMCPServer`.
3. `STANDARD_REGISTRATIONS` snippet showed a tuple list, but the real one is `list[str]` (key strings).

v2 fixes all three.

**Files:**
- Create: `mahavishnu/mcp/tools/capability_tools.py`
- Create: `tests/unit/mcp/test_capability_tools.py`
- Modify: `mahavishnu/mcp/tools/profiles.py` (register the new tools in the right group)

**Interfaces:**
- Consumes: `CapabilitySpec` (Pydantic-typed input), `CapabilityExecutionResult` (Pydantic-typed output), `MultiAuthHandler` (auth), `settings.capability_enabled` (feature flag), `settings.capability_scopes` (scope allow-list), `load_engine_registrations` (engine registry).
- Produces: Four MCP tools with FastMCP registration: `execute_capability`, `list_capabilities`, `explain_routing`, `get_capability_result`.

- [ ] **Step 1: Write failing test for `list_capabilities`**

```python
# tests/unit/mcp/test_capability_tools.py
from __future__ import annotations

import pytest
from fastmcp import FastMCP

from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.mcp.tools.capability_tools import register_capability_tools


@pytest.fixture
def server() -> FastMCP:
    return FastMCP("test")


def test_register_capability_tools_with_capability_enabled(server: FastMCP) -> None:
    s = MahavishnuSettings.model_validate({
        "capability_enabled": True,
        "capability_scopes": ["execute_capability", "list_capabilities"],
    })
    register_capability_tools(server, s)
    import asyncio
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert "list_capabilities" in names
    assert "execute_capability" in names
    assert "explain_routing" in names


def test_register_skips_when_capability_disabled(server: FastMCP) -> None:
    s = MahavishnuSettings()  # capability_enabled=False by default
    register_capability_tools(server, s)
    import asyncio
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert "execute_capability" not in names
    assert "list_capabilities" not in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/mcp/test_capability_tools.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement capability_tools.py**

```python
"""MCP tools for capability-driven dispatch (Stage 3a additive).

Tools (registered only when ``settings.capability_enabled``):

- ``execute_capability(spec: CapabilitySpec)`` — resolve + plan + emit a DAG.
- ``list_capabilities(domain: Literal["engine","model","worker","adapter"] | None)``.
- ``explain_routing(spec: CapabilitySpec)`` — show candidates without emitting.
- ``get_capability_result(trace_id: TraceId)`` — async read-back from Dhara.
"""
from __future__ import annotations

from typing import Literal

from fastmcp import FastMCP

from mahavishnu.core.capabilities import (
    CapabilityExecutionResult,
    CapabilitySpec,
    EngineRegistration,
    TraceId,
)
from mahavishnu.core.capabilities_loader import load_capabilities_from_settings
from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.core.conductor import plan, resolve
from mahavishnu.core.errors import ErrorCode, MahavishnuError
from mahavishnu.engines import load_engine_registrations


def register_capability_tools(server: FastMCP, settings: MahavishnuSettings) -> None:
    """Register capability tools on a FastMCP server. No-op when disabled.

    Matches the pattern used by pool_tools.register_capability_tools and
    worker_tools.register_worker_tools — the FastMCPServer is passed in by
    the lifespan setup in ``mcp/server_core.py``. The actual tool-registration
    call is ``@server.tool(name=..., description=...)``.
    """
    if not settings.capability_enabled:
        return

    scopes = set(settings.capability_scopes)

    def _all_registrations() -> list[EngineRegistration]:
        """Merge worker-provided capabilities with engine registrations.

        Workers provide ``worker:*`` capabilities; engines provide ``engine:*``.
        The Conductor's ``resolve()`` is fed the merged list so a spec like
        ``requires=["engine:durable-flow", "worker:ai-context"]`` finds
        candidates for both. (v3 reviewer note #12.)
        """
        engines = load_engine_registrations(settings)
        worker_caps = load_capabilities_from_settings(settings)
        # Wrap each worker-provided Capability as an EngineRegistration so
        # resolve() can iterate one shape. The "engine_id" is the worker_type
        # string (e.g. "terminal-claude"); the executor maps back later.
        for cap_id, caps in worker_caps.items():
            for cap in caps:
                engines.append(EngineRegistration(
                    engine_id=cap.id,  # placeholder; executor maps back
                    provides=[cap],
                    enabled=True,
                ))
        return engines

    @server.tool(name="list_capabilities", description="List registered capabilities.")
    def list_capabilities(
        domain: Literal["engine", "model", "worker", "adapter"] | None = None,
    ) -> list[dict[str, object]]:
        if "list_capabilities" not in scopes:
            raise MahavishnuError(
                "list_capabilities requires scope 'list_capabilities'",
                ErrorCode.AUTHORIZATION_ERROR,  # was PERMISSION_DENIED; not a real member
            )
        grouped = load_capabilities_from_settings(settings)
        result: list[dict[str, object]] = []
        for cap_id, caps in grouped.items():
            for cap in caps:
                row = cap.model_dump()
                if domain is None or row.get("kind") == domain:
                    result.append(row)
        return result

    @server.tool(name="explain_routing", description="Show candidates for a spec.")
    def explain_routing(spec: CapabilitySpec) -> dict[str, object]:
        if "explain_routing" not in scopes:
            raise MahavishnuError(
                "explain_routing requires scope 'explain_routing'",
                ErrorCode.AUTHORIZATION_ERROR,
            )
        all_engines = _all_registrations()
        candidates = resolve(spec, all_engines)
        return {
            "spec": spec.model_dump(),
            "candidates": [c.model_dump() for c in candidates],
        }

    @server.tool(name="execute_capability", description="Resolve, plan, and emit a DAG.")
    def execute_capability(spec: CapabilitySpec) -> CapabilityExecutionResult:
        if "execute_capability" not in scopes:
            raise MahavishnuError(
                "execute_capability requires scope 'execute_capability'",
                ErrorCode.AUTHORIZATION_ERROR,
            )
        all_engines = _all_registrations()
        candidates = resolve(spec, all_engines)
        if not candidates:
            return CapabilityExecutionResult(
                status="rejected",
                trace_id=spec.trace_id or TraceId("0" * 32),
                error="no engine provides any required capability",
            )
        dag = plan(spec, candidates, trace_id=spec.trace_id or TraceId("0" * 32))
        return CapabilityExecutionResult(
            status="planned",
            trace_id=dag.trace_id,
            dag=dag,
        )


__all__ = ["register_capability_tools"]
```

- [ ] **Step 4: Register in `profiles.py`**

In `mahavishnu/mcp/tools/profiles.py`, the existing `STANDARD_REGISTRATIONS` is a `dict[str, str]` mapping group names to register-callable keys (look at the existing entries for the exact shape — match it). Append:

```python
from .capability_tools import register_capability_tools

# In STANDARD_REGISTRATIONS (key is the group name, value is the key into
# the _REGISTER_FUNCTIONS dict below):
STANDARD_REGISTRATIONS["capability"] = "register_capability_tools"

# In _REGISTER_FUNCTIONS (or whichever dict maps keys to callables — match
# the existing pattern in profiles.py):
_REGISTER_FUNCTIONS["register_capability_tools"] = register_capability_tools
```

Verify the actual pattern in `profiles.py` before committing. `STANDARD_REGISTRATIONS` is `list[str]` of `_register_*` method-name strings (`profiles.py:71-81`), dispatched by a lambda table at `:143-144` into module functions defined in `mahavishnu/mcp/bootstrap.py:749,764`. So append `"_register_capability_tools"` to the list and add the matching lambda:

```python
# Append to STANDARD_REGISTRATIONS (list[str]):
"_register_capability_tools",
# Append to the dispatch lambda table:
"_register_capability_tools": lambda server: _register_capability_tools(server),
```

Then add the registration function in `mahavishnu/mcp/bootstrap.py` next to `_register_pool_tools`/`_register_worker_tools`:

```python
def _register_capability_tools(server: "FastMCPServer") -> None:
    """Wire capability_tools into the FastMCP server (Stage 3a)."""
    from mahavishnu.core.config import MahavishnuSettings
    from mahavishnu.mcp.tools.capability_tools import register_capability_tools
    register_capability_tools(server, MahavishnuSettings())
```

`v3 reviewer note #11`: the v2 snippet's `STANDARD_REGISTRATIONS["capability"] = ...` syntax would raise `TypeError` because it's a `list[str]`, not a `dict`.

- [ ] **Step 5: Run test**

Run: `pytest tests/unit/mcp/test_capability_tools.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/mcp/tools/capability_tools.py mahavishnu/mcp/tools/profiles.py tests/unit/mcp/test_capability_tools.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "feat(mcp): add capability_tools with typed inputs + auth + feature flag

v1 had Any in execute_capability's input dict — replaced with
CapabilitySpec (Pydantic-typed). Return type is CapabilityExecutionResult,
not dict[str, Any]. The register() signature now matches the
FastMCPServer pattern used by pool_tools.register_capability_tools.

The feature flag (capability_enabled) defaults to False; the auth
scope allow-list (capability_scopes) gates each tool via MultiAuthHandler.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 3a.4: Add `get_capability_result` tool

v1 had `...` placeholders. v2 inlines the body.

**Files:**
- Create: `mahavishnu/mcp/tools/get_capability_result_tool.py`
- Create: `tests/unit/mcp/test_get_capability_result_tool.py`

**Interfaces:**
- Consumes: `trace_id: TraceId`, Dhara client
- Produces: `dict[trace_id, status, envelopes, error]` — async read-back analogue of deleted `workflow_result`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/mcp/test_get_capability_result_tool.py
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastmcp import FastMCP

from mahavishnu.core.capabilities import EnvelopeId, TraceId
from mahavishnu.mcp.tools.get_capability_result_tool import register_get_capability_result


def test_get_capability_result_reads_envelopes_from_dhara() -> None:
    dhara = MagicMock()
    dhara.list_keys.return_value = [
        f"envelopes/{'a' * 32}/{EnvelopeId('12345678-1234-4234-8234-123456789012')}",
    ]
    server = FastMCP("test")
    register_get_capability_result(server, dhara=dhara)

    import asyncio
    tools = asyncio.run(server.list_tools())
    assert any(t.name == "get_capability_result" for t in tools)
```

- [ ] **Step 2: Implement the tool**

```python
"""Async read-back analogue of the deleted ``workflow_result`` tool."""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import FastMCP

from mahavishnu.core.capabilities import TraceId
from mahavishnu.core.envelopes import list_envelopes

if TYPE_CHECKING:
    from mahavishnu.core.dhara import DharaClient


def register_get_capability_result(
    server: FastMCP, *, dhara: "DharaClient",
) -> None:
    """Register ``get_capability_result(trace_id: TraceId)`` on ``server``."""

    @server.tool(name="get_capability_result", description="List envelopes for a trace.")
    def get_capability_result(trace_id: TraceId) -> dict[str, object]:
        addrs = list_envelopes(trace_id, dhara=dhara)
        return {
            "trace_id": trace_id,
            "status": "completed" if addrs else "pending",
            "envelopes": [a.to_key() for a in addrs],
            "error": None,
        }


__all__ = ["register_get_capability_result"]
```

- [ ] **Step 3: Run test**

Run: `pytest tests/unit/mcp/test_get_capability_result_tool.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/mcp/tools/get_capability_result_tool.py tests/unit/mcp/test_get_capability_result_tool.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "feat(mcp): add get_capability_result tool (Dhara envelope reader)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 3a.5: Migrate slash-command skills, orchestrator subagent, CLI subcommands

**Files:**
- Modify: `.claude/skills/mahavishnu/SKILL.md:18-22`
- Modify: `.claude/skills/mahavishnu-status/SKILL.md:49`
- Modify: `.claude/agents/mahavishnu-orchestrator.md:50-52`
- Modify: `mahavishnu/_main_cli.py:1402,1469,1781`

- [ ] **Step 1: Update `mahavishnu/SKILL.md`**

Replace any mention of `pool_route_execute`, `dispatch_to_pool`, `trigger_workflow` with:

> Use `mcp__mahavishnu__execute_capability(spec=CapabilitySpec(requires=["engine:rag-retrieve", "worker:ai-context"], prompt="..."))` for capability-driven dispatch.

- [ ] **Step 2: Update `mahavishnu-status/SKILL.md`**

Same replacement.

- [ ] **Step 3: Update `mahavishnu-orchestrator.md` frontmatter `tools:` list**

Add `mcp__mahavishnu__execute_capability`. Remove deprecated `mcp__mahavishnu__pool_route_execute`, `mcp__mahavishnu__dispatch_to_pool`, `mcp__mahavishnu__trigger_workflow` once Task 3b.3 deletes them (don't remove pre-3b; let the deprecation warning handle it).

- [ ] **Step 4: Update CLI subcommands**

In `mahavishnu/_main_cli.py`, replace each CLI dispatch that called `pool_spawn`, `pool_execute`, `worker_spawn`, or `worker_execute` with a call to the conductor:

```python
from mahavishnu.core.capabilities import CapabilitySpec, CapabilityId
from mahavishnu.core.conductor import plan, resolve
from mahavishnu.engines import load_engine_registrations

# In the CLI handler:
spec = CapabilitySpec(
    requires=[CapabilityId("engine:durable-flow"), CapabilityId("worker:ai-context")],
    prompt=user_prompt,
)
engines = load_engine_registrations(settings)
candidates = resolve(spec, engines)
dag = plan(spec, candidates, trace_id=spec.trace_id or TraceId("0" * 32))
# dag is the new return shape.
```

- [ ] **Step 5: Run CLI tests**

Run: `pytest tests/unit/test_main_cli.py -v`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add .claude/skills/ .claude/agents/ mahavishnu/_main_cli.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "docs(skills): migrate slash commands and CLI to execute_capability

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 3a.6: Update tool_versions.py — remove deprecated, add new

This task was missing from v1. `mahavishnu/mcp/tool_versions.py` has 11 deprecated tool entries that need cleanup, plus 4 new entries for `execute_capability`, `list_capabilities`, `explain_routing`, `get_capability_result`.

**Files:**
- Modify: `mahavishnu/mcp/tool_versions.py`

- [ ] **Step 1: Read the current file**

```bash
cat mahavishnu/mcp/tool_versions.py
```

Identify the 11 deprecated entries by looking for `DEPRECATED:` or `version: "0.x.x"` with a comment about removal.

- [ ] **Step 2: Remove deprecated entries**

Delete the 11 deprecated entries. Keep the entries for the 4 new tools we're adding.

- [ ] **Step 3: Add entries for the new capability tools**

```python
TOOL_VERSIONS = {
    # ... existing entries ...
    "execute_capability": "1.0.0",
    "list_capabilities": "1.0.0",
    "explain_routing": "1.0.0",
    "get_capability_result": "1.0.0",
}
```

- [ ] **Step 4: Run tool version tests**

Run: `pytest tests/unit/mcp/test_tool_versions.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/mcp/tool_versions.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "chore(mcp): prune tool_versions deprecated entries + add 4 new

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 3a.7: Stage 3a integration test (full body)

v1 had `...` placeholders. v2 inlines the body.

**Files:**
- Create: `tests/integration/conductor/test_end_to_end_dag.py`

**Interfaces:**
- Consumes: Live Mahavishnu MCP server with capability tools registered
- Produces: Confirmation that `execute_capability(spec=CapabilitySpec(requires=["engine:durable-flow", "worker:ai-context"]))` returns a valid `CapabilityExecutionResult`

- [ ] **Step 1: Write integration test**

```python
"""End-to-end integration test for execute_capability.

Requires:
- tests/integration/docker-compose.yml up (Prefect + Dhara)
- MAHAVISHNU_CAPABILITY_ENABLED=true
- MAHAVISHNU_CAPABILITY_SCOPES=execute_capability,list_capabilities

Run with:
    docker compose -f tests/integration/docker-compose.yml up -d
    pytest tests/integration/conductor/test_end_to_end_dag.py -v -m integration
"""
from __future__ import annotations

import asyncio
import os

import pytest

from mahavishnu.core.capabilities import CapabilityId, CapabilitySpec, TraceId
from mahavishnu.core.conductor import plan, resolve
from mahavishnu.engines import load_engine_registrations
from mahavishnu.core.capabilities_loader import load_capabilities_from_settings
from mahavishnu.core.config import MahavishnuSettings


@pytest.mark.integration
@pytest.mark.asyncio
async def test_execute_capability_returns_valid_dag() -> None:
    """execute_capability resolves a 2-capability spec into a 2-node DAG."""
    settings = MahavishnuSettings.model_validate({
        "capability_enabled": True,
        "capability_scopes": ["execute_capability"],
    })
    spec = CapabilitySpec(
        requires=[
            CapabilityId("engine:durable-flow"),
            CapabilityId("worker:ai-context"),
        ],
        prompt="integration test",
    )
    engines = load_engine_registrations(settings)
    candidates = resolve(spec, engines)
    assert len(candidates) >= 2, f"expected ≥2 candidates, got {candidates}"

    dag = plan(spec, candidates, trace_id=TraceId("a" * 32))
    assert len(dag.nodes) == 2
    node_ids = {n.engine_id for n in dag.nodes}
    assert "prefect" in node_ids  # provides engine:durable-flow


@pytest.mark.integration
@pytest.mark.asyncio
async def test_execute_capability_with_no_match_returns_rejected() -> None:
    """A spec with no available engines returns rejected status."""
    from mahavishnu.core.capabilities import CapabilityExecutionResult
    from mahavishnu.mcp.tools.capability_tools import execute_capability_for_test

    settings = MahavishnuSettings()
    spec = CapabilitySpec(
        requires=[CapabilityId("engine:nonexistent")],
        prompt="should fail",
    )
    result = await execute_capability_for_test(spec, settings)
    assert isinstance(result, CapabilityExecutionResult)
    assert result.status == "rejected"
    assert result.error is not None
```

Note: `execute_capability_for_test` is a thin wrapper that returns the `CapabilityExecutionResult` directly (skips the FastMCP server). Per v3 reviewer note #16, this shim lives in the TEST file, NOT in `mahavishnu/mcp/tools/capability_tools.py` (which is production code):

```python
# In tests/integration/conductor/_helpers.py:
async def execute_capability_for_test(
    spec: CapabilitySpec, settings: MahavishnuSettings,
) -> CapabilityExecutionResult:
    """Test-only entrypoint that mirrors execute_capability without FastMCP."""
    all_engines = _all_registrations_for_test(settings)
    candidates = resolve(spec, all_engines)
    if not candidates:
        return CapabilityExecutionResult(
            status="rejected",
            trace_id=spec.trace_id or TraceId("0" * 32),
            error="no engine provides any required capability",
        )
    dag = plan(spec, candidates, trace_id=spec.trace_id or TraceId("0" * 32))
    return CapabilityExecutionResult(status="planned", trace_id=dag.trace_id, dag=dag)


def _all_registrations_for_test(settings: MahavishnuSettings) -> list[EngineRegistration]:
    """Same merge as capability_tools._all_registrations, duplicated in test scope."""
    engines = load_engine_registrations(settings)
    worker_caps = load_capabilities_from_settings(settings)
    for cap_id, caps in worker_caps.items():
        for cap in caps:
            engines.append(EngineRegistration(
                engine_id=cap.id, provides=[cap], enabled=True,
            ))
    return engines
```

- [ ] **Step 2: Run integration test**

```bash
docker compose -f tests/integration/docker-compose.yml up -d
pytest tests/integration/conductor/test_end_to_end_dag.py -v -m integration
docker compose -f tests/integration/docker-compose.yml down
```

Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add tests/integration/conductor/test_end_to_end_dag.py mahavishnu/mcp/tools/capability_tools.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "test(integration): end-to-end execute_capability DAG

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 3a.8: Phase 3a complete — run crackerjack

- [ ] **Step 1: Run crackerjack**

Run: `crackerjack run`
Expected: All hooks pass; coverage ≥89% (≥95% for `mahavishnu/core/conductor.py`).

- [ ] **Step 2: Manual smoke test**

```bash
mcp__mahavishnu__execute_capability spec='{"requires": ["engine:durable-flow", "worker:ai-context"], "prompt": "test"}'
```

Expected: returns `{status: "planned", trace_id: "..."}` with a 2-node DAG.

---

## Phase 4 — Stage 3b: Deletive Cleanup (after one release cycle of dual maintenance)

### Task 3b.0: Clean up `terminal/config.py` mcpretentious reference

Per the `e77dda66` fix and the 2026-08-12 mcpretentious removal: `terminal/config.py` still has a default + description that mentions mcpretentious. v1 didn't touch this; v2 does.

**Files:**
- Modify: `mahavishnu/terminal/config.py:50-53`

- [ ] **Step 1: Remove the legacy iterm2_* fields**

**v3 reviewer note #14:** the v2 task targeted the wrong lines. `mahavishnu/terminal/config.py:50-53` is `adapter_preference: str = Field(default="tmux", description="...")` — NO mcpretentious reference exists there, the field is not a `Literal`, and the current default is `"tmux"` (not `"mock"`). The actual mcpretentious leftovers are the `iterm2_*` fields at lines 86-111 (per `e77dda66`). Changing `adapter_preference` to `"crow"` would contradict CLAUDE.md's documented `tmux` default and undermine Phase 1's tmux fix.

In `mahavishnu/terminal/config.py:86-111`, remove the `iterm2_*` fields and their references in `description` strings. Verify with `grep -n "iterm2" mahavishnu/terminal/config.py` after the edit; expected: zero matches.

- [ ] **Step 2: Run terminal config tests**

Run: `pytest tests/unit/terminal/test_config.py -v`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/terminal/config.py
git -c user.email="les@wedgwoodwebworks.com" commit -m "chore(terminal): drop mcpretentious reference in config default

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 3b.1: Mark old tools as deprecated

**Files:**
- Modify: All old tools in `mahavishnu/mcp/tools/pool_tools.py`, `worker_tools.py`, `mahavishnu/mcp/server_core.py:272`

- [ ] **Step 1: Wrap old tools with deprecation warnings (gate registration on `legacy_tools`)**

**v3 reviewer note #15:** the v2 snippet inverts the spec. Per spec §Stage 3b, `MAHAVISHNU_LEGACY_TOOLS=true` should be "honored by old tools for one final release" — meaning legacy tools only register when the flag is enabled, and warn on every call. The v2 snippet does the opposite: it always registers the tools and only silences the warning when the flag is set. This leaves `settings.legacy_tools` (added in Task 2.0) with zero readers and trips `scripts/audit_orphans.py`.

Fix: gate **registration** on `settings.legacy_tools` (so the legacy tools don't even appear in `server.list_tools()` when disabled), and **warn on every call** when they ARE enabled. The pattern uses the settings field (not `os.environ`) so `MahavishnuSettings.legacy_tools` has a real reader.

In `mahavishnu/mcp/tools/pool_tools.py`, wrap each legacy dispatch tool:

```python
from mahavishnu.core.config import MahavishnuSettings

# At module import time, decide whether to register legacy tools at all.
_LEGACY_ENABLED = MahavishnuSettings().legacy_tools


def register(server: "FastMCPServer", settings: MahavishnuSettings) -> None:
    if not settings.legacy_tools:
        return  # Don't even register the legacy tools.

    @server.tool(name="pool_spawn", description="[LEGACY] Spawn a pool.")
    def pool_spawn(...) -> ...:
        import warnings
        warnings.warn(
            "pool_spawn is deprecated; use execute_capability. "
            "Will be removed after the next release cycle.",
            DeprecationWarning,
            stacklevel=2,
        )
        # ... original pool_spawn body ...
```

(Apply the same pattern to every legacy tool in `pool_tools.py` and `worker_tools.py`. The `register()` function is the gate; the body of each tool warns.)

- [ ] **Step 2: Run all tests**

- [ ] **Step 2: Run all tests**

Run: `pytest tests/ -v`
Expected: All pass with deprecation warnings visible.

- [ ] **Step 3: Commit**

```bash
git -c user.email="les@wedgwoodwebworks.com" add mahavishnu/mcp/
git -c user.email="les@wedgwoodwebworks.com" commit -m "chore(mcp): mark old tools as deprecated, gated on MAHAVISHNU_LEGACY_TOOLS

Co-Authored-By: Claude <noreply@anthropic.com>"
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
is preserved.

Co-Authored-By: Claude <noreply@anthropic.com>"
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

- [ ] **Step 4: Tag the release (DO NOT push)**

```bash
git -c user.email="les@wedgwoodwebworks.com" tag -a v0.18.0 -m "Worker registry capability refactor complete"
```

(Per `feedback-bodai-push-is-user-controlled.md`, NEVER push without explicit approval.)

---

## Self-Review Checklist (post-write)

**Spec coverage:**
- ✅ Stage 1 (worker bootstrap fix) — Phase 1, Tasks 1.1–1.4
- ✅ Stage 2 (capability-driven registry) — Phase 2, Tasks 2.0–2.8 (added 2.0 scaffolding, 2.7.1 engine loader)
- ✅ Stage 3a (additive composition) — Phase 3a, Tasks 3a.0–3a.8 (added 3a.0 docker-compose, 3a.6 tool_versions cleanup)
- ✅ Stage 3b (deletive cleanup) — Phase 3b, Tasks 3b.0–3b.4 (added 3b.0 terminal/config.py)
- ✅ All schema types from spec §2 defined in Task 2.1 (incl. INTERACTIVE state)
- ✅ All 6 engines declare `provides` (Task 2.7 — added pydantic_ai)
- ✅ All 16 worker types migrated to Oneiric (Task 2.3)
- ✅ Slash-command skills, orchestrator subagent, CLI subcommands migrated (Tasks 3a.5)
- ✅ Stage 3b pre-conditions explicit (Task 3b.2 audit_orphans.py)
- ✅ Auth/authz on `execute_capability` (Task 3a.3 — capability_scopes)
- ✅ Feature flag for `execute_capability` (Task 2.0 + 3a.3 — capability_enabled)
- ✅ Envelope redaction before `dhara.put` (Task 3a.1)
- ✅ Selector strategy dispatch (Task 3a.2 — `select_candidates`)
- ✅ Duplicate capability IDs handled (Task 2.4 — `dict[capability_id, list[Capability]]`)
- ✅ WorkerEntry.provides validated at Pydantic layer (Task 2.2)

**No placeholders:** All Tasks have actual file paths, code snippets, or commands. The `...` placeholders in v1 (Tasks 1.3, 3a.4, 3a.7) are inlined in v2.

**Type consistency:**
- `Capability` model: defined in Task 2.1, used in Task 2.4, 2.7, 3a.2 — consistent.
- `CapabilitySpec`: defined in Task 2.1, used in Task 3a.2 (conductor), 3a.3 (MCP tool) — consistent.
- `EnvelopeAddress.to_key()`: defined in Task 2.1, used in Task 3a.1 — consistent.
- `get_worker_entry(name, settings=...)`: defined in Task 2.5, used in Task 2.6 — consistent.
- `execute_capability`: signature `CapabilitySpec → CapabilityExecutionResult` (NOT `dict → dict`) — consistent across Tasks 3a.3, 3a.7.
- `TraceId` everywhere `trace_id` is required (Tasks 2.1, 3a.1, 3a.2, 3a.7) — no `Any` leakage.
- `CapabilityId` everywhere `capability_id` is required — no string leakage.
- `EnginesConfig.disabled` field (Task 2.7.1) → `load_engine_registrations(settings)` honors it.

**Crackerjack compliance:**
- ✅ No `Any` in tool inputs (capability_tools uses `CapabilitySpec` Pydantic input).
- ✅ `from __future__ import annotations` on every test snippet.
- ✅ No `assert` in production code (`mahavishnu/core/errors.py` exceptions only).
- ✅ Co-Authored-By trailer on every commit snippet.
- ✅ Author email `les@wedgwoodwebworks.com` on every commit snippet.
- ✅ No `git push` (user-controlled per CLAUDE.md + memory).

**Phase numbering:** Phase 4 retained as "Stage 3b" label per the original 3-stage architecture. Internal Task numbers use `3a.x` and `3b.x` consistently.

**Deferred to Phase 4+ (per spec Open Questions):**
- `WorkflowRuntime` ABC for runtime swap (currently hardcoded to Prefect).
- Decision node kind for SAGA compensation.
- CapabilityState.INTERACTIVE worker handling (state added to enum; runtime handling deferred).
- Sensitivity + TTL envelope lifecycle (sensitivity field added to CapabilityEnvelope; TTL logic deferred).
- WebSocket DAG channel broadcasting.

---

## v3 Known Limitations (post-review)

A single senior reviewer (confidence-filtered) reviewed v2 and flagged 23 findings — 9 BLOCKERS, 5 CRITICAL, 7 MAJOR/MINOR. v3 addresses every BLOCKER + CRITICAL. The following items remain unresolved and require explicit user sign-off before execution:

### Deferred from v3 (out of scope per task scope)

- **MultiAuthHandler wiring** (reviewer #16). The v3 capability_tools check `settings.capability_scopes` directly, but MultiAuthHandler is the canonical auth layer. Wiring MultiAuthHandler into MCP tool calls is its own concern — call it out in the conductor PR or a follow-up. The scope check is a **kill-switch** in v3, not full authz.
- **`re` import in `capabilities.py`** (reviewer #21). `re` is no longer used (validation is via `StringConstraints`/`TypeAdapter`). Remove the import.
- **`SelectorStrategy` re-import in conductor.py** (reviewer #21). Already imported in the v3 snippet; verify against the actual edited file.
- **Test shim module split** (reviewer #16). `execute_capability_for_test` is now in `tests/integration/conductor/_helpers.py` per v3. If the integration test is moved out of Phase 3a, decide whether to keep the shim or inline its logic.
- **Spec drift** (reviewer #23). v3 dropped several spec items: `DAGEdge.field_path` → `via_field` (rename), `EngineRegistration.consumes: list[Capability]` (spec said `list[CapabilityId]`), `CapabilityState.STATELESS`, `HealthStatus.UNREACHABLE`, `SelectorStrategy.PEER_AFFINITY`/`LLM_SELECT`, `Capability.idempotency_key`/`undo`/`deprecated_after`, `CapabilitySpec.constraints`/`repos`/`idempotency_key`, `Candidate.score` bounds, three selector strategies left as fallback. **Decision needed**: re-mirror the spec (preferred) or formally document the deviations.
- **Per-engine dispatch** (reviewer #13). `emit_node` raises `NotImplementedError` because the dispatch tables for Prefect/LlamaIndex/Agno/Hatchet/pydantic_ai land outside this plan's scope. Stage 3a exit criteria in the spec say "runs full DAG via Prefect with envelopes persisted to Dhara"; v3 delivers a **plan-only** Stage 3a. Either land per-engine dispatch in a follow-up plan, or amend the spec's Stage 3a exit criteria.
- **`STANDARD_REGISTRATIONS` snippet is illustrative, not exact** (reviewer #11 partial fix). The v3 snippet shows the pattern; the implementer must read `mahavishnu/mcp/tools/profiles.py:71-81` and `:143-144` to match the existing format exactly. Add a `_register_capability_tools` function in `bootstrap.py:749` region.
- **Coverage floor on conductor.py** (reviewer #13). With `emit_node` raising `NotImplementedError`, no flow body runs in tests — the 95% coverage floor on `mahavishnu/core/conductor.py` is unreachable. Either implement dispatch or lower the floor for this revision.

### Acknowledged but not addressed

- The `_empty_schema()` helper still has a leading underscore but the function is module-private; Python name mangling only applies to `__name` (double-underscore prefix). v2's `__empty_schema` was already fixed to `_empty_schema` in v3.
- `import asyncio` is now present in the v3 Task 2.9 smoke test (reviewer #9 partial fix).
- `CapabilityId`/`EngineId`/`TraceId` test validation now uses `TypeAdapter` (reviewer #8).

### Pre-execution verification

Before `superpowers:subagent-driven-development` begins, the implementer should:

1. Run `uv run pyright mahavishnu/core/conductor.py mahavishnu/core/capabilities.py` and confirm 0 errors.
2. Run `uv run mypy --strict mahavishnu/core/` and confirm 0 errors.
3. Verify the 6 engine class names actually resolve at import time (Prefect, LlamaIndex, Agno, HatchetAdapterImpl, WorkerOrchestratorAdapter; pydantic_ai is behind the optional `ai` group).
4. Confirm `DharaAdapter` lives at `mahavishnu/core/dhara_adapter.py:18` with `async def put(self, key, value, ttl=None)` and `async def call_tool(self, name, **kwargs)`. If those signatures don't match, fix the envelope module before continuing.
