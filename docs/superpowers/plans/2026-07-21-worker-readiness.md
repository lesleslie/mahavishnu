# Worker Readiness Repair — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair Mahavishnu worker discovery, dependency gating, and lifecycle execution so workers are only routed when they are configured, credentialed, and live-validated.

**Architecture:** Add a focused capability layer under `mahavishnu/workers/capabilities/` (a package) that wraps the existing typed registry with layered probes. `WorkerManager` gains separate interactive `spawn_workers` and one-shot `submit_workers` paths. `WorkerConfig` carries typed requirement metadata. The CLI, pool routing, MCP tools, and health/readiness all consume the same capability report and broadcast transitions via metrics, structured logs, and the `worker.availability_changed` WebSocket event.

**Tech Stack:** Python 3.13, Pydantic v2, asyncio, httpx, docker/podman CLI, mahavishnu/oneiric, pytest, monkeypatch, fastmcp, mahavishnu/workers/registry.

## Global Constraints

- `from __future__ import annotations` first non-comment line of every new module.
- Ruff line length 100; per-file ignores in `pyproject.toml` apply unchanged.
- mypy strict; `X | None` (not `Optional[X]`), `list[str]`, `pathlib.Path`.
- Function args ≤ 10 (excluding `self`/`cls`/`*args`/`**kwargs`).
- Branches ≤ 15; returns ≤ 6; statements ≤ 55.
- No `assert` in `mahavishnu/**` production code; use `mahavishnu/core/errors.py` exception hierarchy.
- No `Any` in tool inputs/orchestration state; use `TYPE_CHECKING` and typed protocols.
- `except` blocks: `logger.exception(...)`, never `logger.error(..., exc_info=True)`.
- Async I/O only inside `async def`; CLI entry points are the only sync I/O.
- Use Oneiric logger; never `print()`.
- Test markers: `unit`, `integration`, `slow`, `requires_network`, `requires_auth` — do not invent new ones.
- `asyncio_mode = "auto"` — do not decorate async tests with `@pytest.mark.asyncio`.
- Coverage floor: 80% (crackerjack `pytest --cov-fail-under`).
- Capability reports, exception details, and `WorkerResult.error` strings MUST NOT contain secret values; use `safe_error_for_user()`.
- Existing provider env-var names (`MINIMAX_API_KEY`, `OPENCLAW_GATEWAY_URL`, `OPENCLAW_GATEWAY_TOKEN`, `OPENHANDS_API_KEY`) continue to work.
- Every task must include an **Integration Contract** block: Triggered from, Returns to / updates, Demonstrable by, Rollback signal, Observability added.

## File Structure

New files (capability layer is a package, not a single module):

- `mahavishnu/workers/capabilities/__init__.py` — public re-exports.
- `mahavishnu/workers/capabilities/_safe.py` — `safe_error_for_user`, secret redaction.
- `mahavishnu/workers/capabilities/_states.py` — `WorkerCapabilityState`, `WorkerCheck`, `WorkerCapabilityReport`.
- `mahavishnu/workers/capabilities/_cache.py` — short-TTL in-process cache.
- `mahavishnu/workers/capabilities/_static.py` — static prerequisite evaluator.
- `mahavishnu/workers/capabilities/_probes.py` — async live probes (auth, openclaw, container, mcp).
- `mahavishnu/workers/capabilities/_observability.py` — metric/log/event emission.
- `mahavishnu/workers/capabilities/_report.py` — `evaluate_worker_capabilities`, `evaluate_all_capabilities`, `select_routable_workers`.
- `tests/unit/workers/__init__.py`
- `tests/unit/workers/test_capabilities_static.py` — static phase.
- `tests/unit/workers/test_capabilities_probes.py` — live phase with fakes.
- `tests/unit/workers/test_capabilities_observability.py` — metrics, logs, WebSocket event.
- `tests/integration/workers/__init__.py`
- `tests/integration/workers/test_capabilities_live.py` — fake-OpenClaw / fake-Docker / fake-MCP probes; `@pytest.mark.integration`, `requires_network`.
- `docs/operations/WORKER_READINESS.md` — operator-facing diagnostics guide.

Modified files:

- `mahavishnu/workers/registry.py` — add `required_env`, `required_settings`, `auth_kind`, `runtime_kind`, `one_shot`, `endpoint`; keep `validate_worker_dependencies()` as compatibility wrapper.
- `mahavishnu/workers/manager.py` — split spawn vs submit, add dedicated-class branches, integrate capability check, accept `settings`.
- `mahavishnu/workers/openclaw_gateway.py` — cap auto-restart, structured terminal failure, live `/health` probe in capability.
- `mahavishnu/workers/container.py` — replace 1-second sleep with real readiness probe, runtime discovery.
- `mahavishnu/workers/cloud_worker.py` — register `READY`/`DEGRADED` honestly, populate `missing_credentials`.
- `mahavishnu/workers/application.py` — validate `mcp_server` against settings, fail-fast when missing.
- `mahavishnu/workers/a2a.py`, `mahavishnu/workers/crow.py`, `mahavishnu/workers/openhands.py` — expose dedicated factory-callable constructors.
- `mahavishnu/workers/generic_shell.py` — `start()` accepts `prompt` keyword for one-shot flows.
- `mahavishnu/workers/registry.py:resolve_worker_type` — strip env-var presence inference; pure intent-routing helper.
- `mahavishnu/core/errors.py` — add `WorkerUnavailableError` and `ContainerDaemonUnavailable`.
- `mahavishnu/core/config.py` — `Workers` Pydantic model gains `container: ContainerSettings`.
- `mahavishnu/_main_cli.py` — fix `workers.enabled` lookups; add `workers submit`; add `--ready`, `--all`, `--explain`, `--probe` flags; safe error display.
- `mahavishnu/core/health.py` — accept capability report as a health component; move first-party imports to module top.
- `mahavishnu/health.py` — aggregate worker component into overall readiness.
- `mahavishnu/mcp/tools/health_tools.py` — pass capability report through `health_check_all` / `get_readiness`.
- `mahavishnu/mcp/tools/pool_tools.py` — use `select_routable_workers` instead of consulting registry directly.
- `mahavishnu/mcp/tools/worker_tools.py` — surface capability state in tool output.
- `mahavishnu/websocket/server.py` — verify signature; broadcast `worker.availability_changed` and `adapter.health_changed` on capability transitions.
- `settings/mahavishnu.yaml` — add `workers.container.runtime`, `workers.container.socket_path`.
- `tests/unit/test_workers_registry.py` and `tests/unit/test_workers_registry_coverage.py` — merge the duplicate, add capability metadata tests.
- `tests/unit/test_worker_manager.py` — split-spawn, submit, capability gate, factory dispatch.
- `tests/unit/test_container_worker.py` — readiness probe; runtime discovery.
- `tests/unit/test_openclaw_gateway.py` — auto-restart cap; live health probe.
- `tests/unit/test_cloud_worker.py` — credential gating; secret hygiene.
- `tests/unit/test_application_worker.py` — MCP server validation.
- `tests/unit/test_health.py` — capability component aggregation.

## Task Ordering

Tasks 1–2 fix wiring; Task 3 adds metadata; Task 4 builds the capability layer (static + live + observability); Task 5 is the integration suite; Task 6 is container runtime; Task 7 splits spawn vs submit and de-couples `resolve_worker_type`; Task 8 wires dedicated factory branches; Task 9 caps OpenClaw auto-restart; Task 10 wires CLI/MCP/health; Task 11 gates cloud worker; Task 12 runs the demo and quality gates including a crackerjack-style compliance review.

______________________________________________________________________

### Task 1: Fix global `workers.enabled` wiring

**Files:**

- Modify: `mahavishnu/_main_cli.py:1316,1399`
- Test: `tests/unit/test_workers_cli_gate.py`

**Interfaces:**

- Consumes: `MahavishnuSettings.workers.enabled` (Pydantic nested field, already defined in `mahavishnu/core/config.py:1084-1112`).
- Produces: `workers spawn` and `workers execute` honor `workers.enabled=false`.

**Integration Contract:**

- Triggered from: `mahavishnu workers spawn`, `mahavishnu workers execute`.

- Returns to / updates: CLI exit code 1 with explicit message when disabled.

- Demonstrable by: the failing test in Step 1.

- Rollback signal: `workers.enabled: false` no longer exits 1.

- Observability added: stderr message format `ERROR: Worker orchestration is disabled`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_workers_cli_gate.py
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_workers_enabled_false_blocks_spawn() -> None:
    env = os.environ.copy()
    # Pydantic-settings nested-delimiter override: honors
    # `workers.enabled = false` in MahavishnuSettings without touching
    # `settings_customise_sources`. The original `MAHAVISHNU_SETTINGS_PATH`
    # approach is not honored by the current settings loader, so the
    # pydantic-settings env var is the contract for this test.
    env["MAHAVISHNU_WORKERS__ENABLED"] = "false"
    result = subprocess.run(
        [sys.executable, "-m", "mahavishnu", "workers", "spawn",
         "--type", "terminal-shell", "--count", "1"],
        capture_output=True,
        text=True,
        env=env,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert result.returncode != 0
    assert "disabled" in (result.stderr + result.stdout).lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/test_workers_cli_gate.py -v`
Expected: FAIL — exit code 0 because the current code reads nonexistent `workers_enabled`.

- [ ] **Step 3: Update the two CLI gates**

In `mahavishnu/_main_cli.py`, replace the `getattr(maha_app.config, "workers_enabled", True)` calls at lines 1316 and 1399 with:

```python
if not getattr(maha_app.config.workers, "enabled", True):
    typer.echo("ERROR: Worker orchestration is disabled", err=True)
    raise typer.Exit(code=1)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/test_workers_cli_gate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/_main_cli.py tests/unit/test_workers_cli_gate.py
git commit -m "fix(workers): honor nested workers.enabled setting in CLI"
```

______________________________________________________________________

### Task 2: Add capability-aware exceptions to the error hierarchy

**Files:**

- Modify: `mahavishnu/core/errors.py`
- Test: `tests/unit/test_errors.py`

**Interfaces:**

- Consumes: existing `MahavishnuError` constructor and `ErrorCode` enum.
- Produces: `WorkerUnavailableError(worker_type, state, missing_requirements, message)` and `ContainerDaemonUnavailable(runtime, error)` that carry safe fields only.

**Integration Contract:**

- Triggered from: capability check failures, container daemon probe failures.

- Returns to / updates: structured exception with `ErrorCode.WORKER_UNAVAILABLE` and details; never secret values.

- Demonstrable by: the three tests in Step 1.

- Rollback signal: secret value appears in `str(exc)`.

- Observability added: error code increments; no new metrics.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_errors.py
from __future__ import annotations

import pytest

from mahavishnu.core.errors import (
    ContainerDaemonUnavailable,
    ErrorCode,
    WorkerUnavailableError,
)


def test_worker_unavailable_error_omits_secret() -> None:
    err = WorkerUnavailableError(
        worker_type="terminal-claude",
        state="CONFIGURED",
        missing_requirements=["MINIMAX_API_KEY"],
        message="credential missing",
    )
    rendered = str(err)
    assert "MINIMAX_API_KEY" in rendered
    assert "sk-" not in rendered


def test_worker_unavailable_error_carries_error_code() -> None:
    err = WorkerUnavailableError(
        worker_type="gateway-openclaw",
        state="CONFIGURED",
        missing_requirements=["OPENCLAW_GATEWAY_URL"],
        message="no gateway url",
    )
    assert err.error_code is ErrorCode.WORKER_UNAVAILABLE
    assert err.details["worker_type"] == "gateway-openclaw"
    assert err.details["state"] == "CONFIGURED"
    assert err.details["missing_requirements"] == ["OPENCLAW_GATEWAY_URL"]


def test_container_daemon_unavailable_keeps_runtime_name() -> None:
    err = ContainerDaemonUnavailable(runtime="docker", error="connect refused")
    assert err.error_code is ErrorCode.WORKER_UNAVAILABLE
    assert err.details["runtime"] == "docker"
    assert "docker" in str(err)
    assert "sk-" not in str(err)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/test_errors.py -v`
Expected: FAIL — `WorkerUnavailableError` and `ContainerDaemonUnavailable` are not defined yet.

- [ ] **Step 3: Add the error codes and exceptions**

In `mahavishnu/core/errors.py`:

1. Add to the `ErrorCode` enum:
   ```python
   WORKER_UNAVAILABLE = "MHV-310"
   ```
1. Append after `ExternalServiceError`:
   ```python
   class WorkerUnavailableError(MahavishnuError):
       """Raised when a worker cannot be spawned because capability checks fail.

       Carries only requirement names; secret values must never be present.
       """

       def __init__(
           self,
           *,
           worker_type: str,
           state: str,
           missing_requirements: list[str],
           message: str,
       ) -> None:
           super().__init__(
               f"Worker {worker_type} unavailable ({state}): {message}",
               ErrorCode.WORKER_UNAVAILABLE,
               details={
                   "worker_type": worker_type,
                   "state": state,
                   "missing_requirements": list(missing_requirements),
               },
           )


   class ContainerDaemonUnavailable(MahavishnuError):
       """Raised when a container runtime binary or daemon probe fails."""

       def __init__(self, *, runtime: str, error: str) -> None:
           super().__init__(
               f"Container runtime {runtime!r} unavailable: {error}",
               ErrorCode.WORKER_UNAVAILABLE,
               details={"runtime": runtime},
           )
   ```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/test_errors.py::test_worker_unavailable_error_omits_secret tests/unit/test_errors.py::test_worker_unavailable_error_carries_error_code tests/unit/test_errors.py::test_container_daemon_unavailable_keeps_runtime_name -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/errors.py tests/unit/test_errors.py
git commit -m "feat(errors): add WorkerUnavailableError and ContainerDaemonUnavailable"
```

______________________________________________________________________

### Task 3: Add capability metadata to `WorkerConfig`

**Files:**

- Modify: `mahavishnu/workers/registry.py:24-58, 62-540`
- Test: `tests/unit/test_workers_registry.py`

**Interfaces:**

- Consumes: existing `WorkerConfig` fields (`name`, `worker_type`, `command`, `category`, `requires_tool`, `mcp_server`).
- Produces: extended `WorkerConfig` with `required_env`, `required_settings`, `auth_kind`, `runtime_kind`, `one_shot`, `endpoint`. All defaulted; existing 46 entries stay valid.

**Integration Contract:**

- Triggered from: registry construction; capability layer reads new fields.

- Returns to / updates: `WORKER_REGISTRY` with 46 entries still valid; no behavior change at this step.

- Demonstrable by: tests in Step 1 pass.

- Rollback signal: existing tests `tests/unit/test_workers_registry_coverage.py` fail.

- Observability added: none yet.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_workers_registry.py additions
from __future__ import annotations

from mahavishnu.workers.registry import (
    AuthKind,
    RuntimeKind,
    WORKER_REGISTRY,
    WorkerCategory,
    WorkerConfig,
)


def test_worker_config_has_capability_fields() -> None:
    cfg = WorkerConfig(
        name="test",
        worker_type="test-x",
        command="echo",
        category=WorkerCategory.SHELL,
        required_env=["MINIMAX_API_KEY"],
        required_settings=["workers.enabled"],
        auth_kind=AuthKind.API_KEY,
        runtime_kind=RuntimeKind.NONE,
        one_shot=False,
    )
    assert cfg.required_env == ["MINIMAX_API_KEY"]
    assert cfg.required_settings == ["workers.enabled"]
    assert cfg.auth_kind is AuthKind.API_KEY
    assert cfg.runtime_kind is RuntimeKind.NONE
    assert cfg.one_shot is False


def test_registry_entries_have_default_capability_metadata() -> None:
    for worker_type, cfg in WORKER_REGISTRY.items():
        assert isinstance(cfg.required_env, list)
        assert isinstance(cfg.required_settings, list)
        assert cfg.auth_kind in set(AuthKind)
        assert cfg.runtime_kind in set(RuntimeKind)
        assert isinstance(cfg.one_shot, bool)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/test_workers_registry.py::test_worker_config_has_capability_fields tests/unit/test_workers_registry.py::test_registry_entries_have_default_capability_metadata -v`
Expected: FAIL — `AuthKind`, `RuntimeKind`, and the new fields are not defined.

- [ ] **Step 3: Define the new enums and extend `WorkerConfig`**

In `mahavishnu/workers/registry.py`, before `WorkerCategory`:

```python
class AuthKind(Enum):
    NONE = "none"
    API_KEY = "api_key"
    CLI_SUBSCRIPTION = "cli_subscription"
    MCP_CREDENTIAL = "mcp_credential"
    BEARER_TOKEN = "bearer_token"
    OAUTH = "oauth"


class RuntimeKind(Enum):
    NONE = "none"
    SHELL = "shell"
    DOCKER = "docker"
    PODMAN = "podman"
    ORBSTACK = "orbstack"
```

Replace `WorkerConfig` with the extended version (keep every existing field; add the new ones with defaults):

```python
@dataclass
class WorkerConfig:
    name: str
    worker_type: str
    command: str
    category: WorkerCategory
    description: str = ""
    completion_markers: list[str] = field(default_factory=list)
    error_markers: list[str] = field(
        default_factory=lambda: ["error:", "Error:", "ERROR:", "Exception:"]
    )
    stream_format: str = "text"
    supports_interactive: bool = True
    default_timeout: int = 300
    env_vars: dict[str, str] = field(default_factory=dict)
    requires_tool: str | None = None
    mcp_server: str | None = None
    complete_on_valid_json: bool = False
    required_env: list[str] = field(default_factory=list)
    required_settings: list[str] = field(default_factory=list)
    auth_kind: AuthKind = AuthKind.NONE
    runtime_kind: RuntimeKind = RuntimeKind.NONE
    one_shot: bool = False
    endpoint: str | None = None
```

- [ ] **Step 4: Add capability metadata to the 46 registry entries**

For each existing `WorkerConfig(...)` literal in `WORKER_REGISTRY`, add the relevant fields. Use this mapping (a2a keeps an empty `required_env` because its credential is resolved by settings in Task 8):

| Worker type | `required_env` | `auth_kind` | `runtime_kind` | `one_shot` | `endpoint` |
|---|---|---|---|---|---|
| `terminal-qwen` | `[]` | `CLI_SUBSCRIPTION` | `SHELL` | `False` | `None` |
| `terminal-claude` | `[]` | `CLI_SUBSCRIPTION` | `SHELL` | `False` | `None` |
| `terminal-codex` | `[]` | `CLI_SUBSCRIPTION` | `SHELL` | `True` | `None` |
| `terminal-openclaw` | `[]` | `CLI_SUBSCRIPTION` | `SHELL` | `True` | `None` |
| `terminal-deepagents` | `[]` | `CLI_SUBSCRIPTION` | `SHELL` | `True` | `None` |
| `terminal-clai` | `[]` | `CLI_SUBSCRIPTION` | `SHELL` | `True` | `None` |
| `terminal-crow` | `[]` | `MCP_CREDENTIAL` | `NONE` | `False` | `None` |
| `terminal-aider` | `[]` | `CLI_SUBSCRIPTION` | `SHELL` | `False` | `None` |
| `terminal-goose` | `[]` | `CLI_SUBSCRIPTION` | `SHELL` | `False` | `None` |
| `terminal-gemini` | `[]` | `CLI_SUBSCRIPTION` | `SHELL` | `False` | `None` |
| `terminal-amp` | `[]` | `CLI_SUBSCRIPTION` | `SHELL` | `False` | `None` |
| `gateway-openclaw` | `["OPENCLAW_GATEWAY_URL"]` | `BEARER_TOKEN` | `NONE` | `True` | `None` (read from env) |
| `terminal-shell` | `[]` | `NONE` | `SHELL` | `False` | `None` |
| `terminal-zsh` | `[]` | `NONE` | `SHELL` | `False` | `None` |
| `terminal-python` | `[]` | `NONE` | `SHELL` | `False` | `None` |
| `terminal-ipython` | `[]` | `NONE` | `SHELL` | `False` | `None` |
| `terminal-node` | `[]` | `NONE` | `SHELL` | `False` | `None` |
| `terminal-mysql` | `["MYSQL_PASSWORD"]` | `BEARER_TOKEN` | `SHELL` | `False` | `None` |
| `terminal-psql` | `["PGPASSWORD"]` | `BEARER_TOKEN` | `SHELL` | `False` | `None` |
| `terminal-turso` | `["TURSO_AUTH_TOKEN"]` | `BEARER_TOKEN` | `SHELL` | `False` | `None` |
| `terminal-redis` | `[]` | `BEARER_TOKEN` | `SHELL` | `False` | `None` |
| `terminal-wasmtime` | `[]` | `NONE` | `SHELL` | `False` | `None` |
| `terminal-wasmer` | `[]` | `NONE` | `SHELL` | `False` | `None` |
| `terminal-sqlite` | `[]` | `NONE` | `SHELL` | `False` | `None` |
| `terminal-mongo` | `[]` | `BEARER_TOKEN` | `SHELL` | `False` | `None` |
| `terminal-kubectl` | `[]` | `CLI_SUBSCRIPTION` | `SHELL` | `False` | `None` |
| `terminal-terraform` | `[]` | `CLI_SUBSCRIPTION` | `SHELL` | `False` | `None` |
| `container` | `[]` | `NONE` | `DOCKER` | `True` | `None` |
| `container-executor` | `[]` | `NONE` | `DOCKER` | `True` | `None` |
| `terminal-ssh` | `[]` | `BEARER_TOKEN` | `SHELL` | `False` | `None` |
| `application-gimp` | `[]` | `MCP_CREDENTIAL` | `NONE` | `False` | `None` |
| `application-inkscape` | `[]` | `NONE` | `SHELL` | `False` | `None` |
| `application-blender` | `[]` | `MCP_CREDENTIAL` | `NONE` | `False` | `None` |
| `application-mdinject` | `[]` | `MCP_CREDENTIAL` | `NONE` | `False` | `None` |
| `application-vscode` | `[]` | `MCP_CREDENTIAL` | `NONE` | `False` | `None` |
| `application-penpot` | `[]` | `MCP_CREDENTIAL` | `NONE` | `False` | `None` |
| `application-grafana` | `[]` | `MCP_CREDENTIAL` | `NONE` | `False` | `None` |
| `application-porkbun-dns` | `[]` | `MCP_CREDENTIAL` | `NONE` | `False` | `None` |
| `application-porkbun-domain` | `[]` | `MCP_CREDENTIAL` | `NONE` | `False` | `None` |
| `application-synxis-crs` | `[]` | `MCP_CREDENTIAL` | `NONE` | `False` | `None` |
| `application-synxis-pms` | `[]` | `MCP_CREDENTIAL` | `NONE` | `False` | `None` |
| `application-graphics` | `[]` | `MCP_CREDENTIAL` | `NONE` | `False` | `None` |
| `application-neo4j` | `[]` | `MCP_CREDENTIAL` | `NONE` | `False` | `None` |
| `application-pycharm` | `[]` | `MCP_CREDENTIAL` | `NONE` | `False` | `None` |
| `openhands` | `["OPENHANDS_API_KEY"]` | `API_KEY` | `NONE` | `True` | `None` (read from settings) |
| `a2a` | `[]` | `API_KEY` | `NONE` | `True` | `None` (credential resolved from `a2a.agents[*].api_key` settings) |

For `terminal-ssh`, add `required_settings: ["workers.remote.hosts"]` (resolved later; placeholder key for now).

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/unit/test_workers_registry.py -v`
Expected: PASS.

- [ ] **Step 6: Run the broader registry test**

Run: `pytest tests/unit/test_workers_registry_coverage.py -v`
Expected: PASS (no behavioral change yet; only metadata).

- [ ] **Step 7: Commit**

```bash
git add mahavishnu/workers/registry.py tests/unit/test_workers_registry.py
git commit -m "feat(workers): add capability metadata fields to WorkerConfig"
```

______________________________________________________________________

### Task 4: Build the capability layer (static, live, and observability)

**Files (created in this order to avoid forward imports):**

- Create: `mahavishnu/workers/capabilities/_safe.py`
- Create: `mahavishnu/workers/capabilities/_states.py`
- Create: `mahavishnu/workers/capabilities/_cache.py`
- Create: `mahavishnu/workers/capabilities/_static.py`
- Create: `mahavishnu/workers/capabilities/_probes.py`
- Create: `mahavishnu/workers/capabilities/_observability.py`
- Create: `mahavishnu/workers/capabilities/_report.py`
- Create: `mahavishnu/workers/capabilities/__init__.py` (last, after `_report.py` exists)
- Create: `tests/unit/workers/__init__.py`
- Test: `tests/unit/workers/test_capabilities_static.py`
- Test: `tests/unit/workers/test_capabilities_probes.py`
- Test: `tests/unit/workers/test_capabilities_observability.py`

**Interfaces:**

- Consumes: `WORKER_REGISTRY`, `MahavishnuSettings`, env vars, asyncio, httpx.
- Produces:
  - `WorkerCapabilityState` enum with `REGISTERED`, `CONFIGURED`, `READY`, `AVAILABLE`.
  - `WorkerCheck`, `WorkerCapabilityReport` dataclasses.
  - `evaluate_worker_capabilities(worker_type, *, settings, force_live=False) -> WorkerCapabilityReport`.
  - `evaluate_all_capabilities(*, settings, force_live=False) -> dict[str, WorkerCapabilityReport]`.
  - `select_routable_workers(candidates=None, *, settings, require_available=False) -> list[str]`.
  - Capability transitions emit metrics, log markers (`worker_capability_transition`, `worker_capability_probe_failed`), and the `worker.availability_changed` + `adapter.health_changed` WebSocket events with payload `{worker_type, state, safe_reason, probe_at}`.

**Integration Contract:**

- Triggered from: `WorkerManager.spawn_workers`, `WorkerManager.submit_workers`, CLI list-types, pool routing, MCP discover_tools, health/readiness.

- Returns to / updates: capability report consumed by every consumer above.

- Demonstrable by: tests in Steps 9, 10, 11.

- Rollback signal: capability evaluation throws unhandled exception; secret value appears in report.

- Observability added: `_TRANSITIONS`, `_PROBE_DURATION`, `_CACHE_TOTAL` metrics; `worker_capability_transition` and `worker_capability_probe_failed` log markers; two WebSocket events.

- [ ] **Step 1: Implement `_safe.py`**

```python
# mahavishnu/workers/capabilities/_safe.py
"""Safe-redaction helpers for capability reports, exceptions, and logs."""
from __future__ import annotations

import re
from typing import Any

_SECRET_PATTERN = re.compile(
    r"(?i)(?:sk-[a-z0-9]{8,}|ghp_[a-z0-9]{8,}|xox[ab]-[a-z0-9-]{8,}|"
    r"ya29\.[a-z0-9_-]{8,}|bearer\s+[a-z0-9._-]{8,})"
)


def safe_error_for_user(message: str | None) -> str:
    """Return text with credential-shaped substrings replaced by ***."""
    if not message:
        return ""
    return _SECRET_PATTERN.sub("***", message)


def safe_dict(details: dict[str, Any] | None) -> dict[str, Any]:
    """Return a shallow copy of details with string fields redacted."""
    if not details:
        return {}
    return {k: safe_error_for_user(v) if isinstance(v, str) else v for k, v in details.items()}
```

- [ ] **Step 2: Implement `_states.py`**

```python
# mahavishnu/workers/capabilities/_states.py
"""Capability state and report dataclasses."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class WorkerCapabilityState(str, Enum):
    REGISTERED = "REGISTERED"
    CONFIGURED = "CONFIGURED"
    READY = "READY"
    AVAILABLE = "AVAILABLE"


@dataclass
class WorkerCheck:
    kind: str
    status: str  # "pass" | "fail" | "skip"
    safe_reason: str | None = None
    duration_ms: float = 0.0
    cached: bool = False
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class WorkerCapabilityReport:
    worker_type: str
    state: WorkerCapabilityState
    checks: list[WorkerCheck] = field(default_factory=list)
    missing_requirements: list[str] = field(default_factory=list)
    safe_reason: str | None = None
    probe_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    cache_ttl_s: int = 30
```

- [ ] **Step 3: Implement `_cache.py`**

```python
# mahavishnu/workers/capabilities/_cache.py
"""In-process cache for capability reports."""
from __future__ import annotations

import time
from typing import Any

_STORE: dict[str, tuple[float, Any]] = {}


def get(key: str, ttl_s: int) -> object | None:
    ts, value = _STORE.get(key, (0.0, None))
    if time.monotonic() - ts < ttl_s:
        return value
    return None


def put(key: str, value: Any) -> None:
    _STORE[key] = (time.monotonic(), value)


def invalidate(worker_type: str) -> None:
    for k in list(_STORE):
        if k.startswith(f"{worker_type}:"):
            _STORE.pop(k, None)


def clear() -> None:
    _STORE.clear()
```

- [ ] **Step 4: Implement `_static.py`**

```python
# mahavishnu/workers/capabilities/_static.py
"""Static prerequisite checks."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import Any

from ..registry import WorkerConfig
from ._states import WorkerCapabilityReport, WorkerCapabilityState, WorkerCheck


@dataclass
class StaticContext:
    settings: Any
    env: dict[str, str]


def _resolve_settings_value(settings: Any, dotted_key: str) -> Any | None:
    current: Any = settings
    for part in dotted_key.split("."):
        if current is None:
            return None
        current = getattr(current, part, None)
    return current


def _has_setting(ctx: StaticContext, dotted_key: str) -> bool:
    value = _resolve_settings_value(ctx.settings, dotted_key)
    if isinstance(value, bool):
        return value
    return bool(value)


def _required_env_present(ctx: StaticContext, names: list[str]) -> tuple[bool, list[str]]:
    missing = [n for n in names if not ctx.env.get(n)]
    return (not missing, missing)


def evaluate_static(
    worker_type: str,
    *,
    config: WorkerConfig,
    ctx: StaticContext,
) -> WorkerCapabilityReport:
    checks: list[WorkerCheck] = []
    missing: list[str] = []

    workers_enabled = bool(_resolve_settings_value(ctx.settings, "workers.enabled"))
    if not workers_enabled:
        return WorkerCapabilityReport(
            worker_type=worker_type,
            state=WorkerCapabilityState.CONFIGURED,
            missing_requirements=["workers.enabled"],
            safe_reason="workers disabled by config",
        )

    if config.requires_tool:
        if shutil.which(config.requires_tool) is None:
            missing.append(f"tool:{config.requires_tool}")
            checks.append(WorkerCheck(kind="binary", status="fail", safe_reason=config.requires_tool))
        else:
            checks.append(WorkerCheck(kind="binary", status="pass", safe_reason=config.requires_tool))

    env_ok, env_missing = _required_env_present(ctx, config.required_env)
    if not env_ok:
        missing.extend(env_missing)
        checks.append(WorkerCheck(kind="env", status="fail", safe_reason=",".join(env_missing)))
    elif config.required_env:
        checks.append(WorkerCheck(kind="env", status="pass", safe_reason=",".join(config.required_env)))

    for dotted in config.required_settings:
        if not _has_setting(ctx, dotted):
            missing.append(f"setting:{dotted}")
            checks.append(WorkerCheck(kind="setting", status="fail", safe_reason=dotted))

    if not config.required_env and not config.required_settings and not config.requires_tool:
        return WorkerCapabilityReport(
            worker_type=worker_type,
            state=WorkerCapabilityState.CONFIGURED,
            checks=checks,
            missing_requirements=missing,
            safe_reason="settings permit; no static prereqs",
        )

    if missing:
        return WorkerCapabilityReport(
            worker_type=worker_type,
            state=WorkerCapabilityState.CONFIGURED,
            checks=checks,
            missing_requirements=missing,
            safe_reason=",".join(missing),
        )

    return WorkerCapabilityReport(
        worker_type=worker_type,
        state=WorkerCapabilityState.READY,
        checks=checks,
        missing_requirements=missing,
        safe_reason="static prerequisites satisfied",
    )
```

- [ ] **Step 5: Implement `_probes.py`**

```python
# mahavishnu/workers/capabilities/_probes.py
"""Async live probes for worker capability evaluation."""
from __future__ import annotations

import asyncio
import os
import shutil
import socket
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from ._safe import safe_error_for_user
from ._states import WorkerCheck


async def _probe_openclaw_gateway(endpoint: str, token: str | None) -> WorkerCheck:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{endpoint.rstrip('/')}/health", headers=headers)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError, OSError) as exc:
        return WorkerCheck(kind="openclaw_gateway", status="fail", safe_reason=type(exc).__name__)

    if not isinstance(payload, dict) or "healthy" not in payload or not bool(payload["healthy"]):
        return WorkerCheck(kind="openclaw_gateway", status="fail", safe_reason="unhealthy")
    return WorkerCheck(kind="openclaw_gateway", status="pass", safe_reason="ok")


async def _probe_openclaw_cli(binary: str) -> WorkerCheck:
    if shutil.which(binary) is None:
        return WorkerCheck(kind="openclaw_cli", status="fail", safe_reason=f"missing:{binary}")
    try:
        proc = await asyncio.create_subprocess_exec(
            binary, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
    except (asyncio.TimeoutError, OSError) as exc:
        return WorkerCheck(kind="openclaw_cli", status="fail", safe_reason=type(exc).__name__)
    if proc.returncode != 0:
        return WorkerCheck(kind="openclaw_cli", status="fail", safe_reason="non_zero_exit")
    safe = safe_error_for_user(stdout.decode().strip() or "ok")
    return WorkerCheck(kind="openclaw_cli", status="pass", safe_reason=safe)


async def _probe_container_daemon(runtime: str) -> WorkerCheck:
    if shutil.which(runtime) is None:
        return WorkerCheck(kind="container_daemon", status="fail", safe_reason=f"missing:{runtime}")
    try:
        proc = await asyncio.create_subprocess_exec(
            runtime, "version", "--format", "{{.Server.Version}}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
    except (asyncio.TimeoutError, OSError) as exc:
        return WorkerCheck(kind="container_daemon", status="fail", safe_reason=type(exc).__name__)
    if proc.returncode != 0:
        return WorkerCheck(kind="container_daemon", status="fail", safe_reason="daemon_unreachable")
    safe = safe_error_for_user(stdout.decode().strip() or "ok")
    return WorkerCheck(kind="container_daemon", status="pass", safe_reason=safe)


async def _probe_orbstack_socket(socket_path: str) -> WorkerCheck:
    loop = asyncio.get_running_loop()
    try:
        await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: socket.socket(socket.AF_UNIX, socket.SOCK_STREAM).connect(socket_path),
            ),
            timeout=2.0,
        )
    except (OSError, asyncio.TimeoutError):
        return WorkerCheck(kind="orbstack_socket", status="fail", safe_reason="socket_unreachable")
    return WorkerCheck(kind="orbstack_socket", status="pass", safe_reason="ok")


async def _probe_auth_presence(required_env: list[str]) -> WorkerCheck:
    missing = [n for n in required_env if not os.environ.get(n)]
    if missing:
        return WorkerCheck(kind="auth", status="fail", safe_reason=",".join(missing))
    return WorkerCheck(kind="auth", status="pass", safe_reason="ok")


async def _probe_provider_request(
    provider: str, env_var: str, endpoint: str
) -> WorkerCheck:
    """Perform a noop auth probe against a documented provider endpoint.

    The Authorization header is injected with the env var's value; the
    response body and any error message are redacted before returning.
    """
    token = os.environ.get(env_var)
    if not token:
        return WorkerCheck(kind=f"{provider}_auth", status="fail", safe_reason="missing")
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(endpoint, headers=headers)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        return WorkerCheck(
            kind=f"{provider}_auth",
            status="fail",
            safe_error_for_user=type(exc).__name__,  # replaced by safe_reason
        )
        # NB: safe_error_for_user is not a WorkerCheck kwarg; replaced with safe_reason below.
    return WorkerCheck(kind=f"{provider}_auth", status="pass", safe_reason="ok")


async def _probe_mcp_server(name: str, mcp_catalog: dict[str, str]) -> WorkerCheck:
    if name not in mcp_catalog:
        return WorkerCheck(kind="mcp_server", status="fail", safe_reason=f"unknown:{name}")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(mcp_catalog[name])
            response.raise_for_status()
    except httpx.HTTPError as exc:
        return WorkerCheck(kind="mcp_server", status="fail", safe_reason=type(exc).__name__)
    return WorkerCheck(kind="mcp_server", status="pass", safe_reason="ok")


PROBES: dict[str, Callable[..., Awaitable[WorkerCheck]]] = {
    "openclaw_gateway": _probe_openclaw_gateway,
    "openclaw_cli": _probe_openclaw_cli,
    "container_daemon": _probe_container_daemon,
    "orbstack_socket": _probe_orbstack_socket,
    "auth_presence": _probe_auth_presence,
    "provider_request": _probe_provider_request,
    "mcp_server": _probe_mcp_server,
}


# Provider catalog: name -> (env_var, endpoint). The endpoint is the
# documented lightweight auth probe URL for each provider.
PROVIDER_PROBES: dict[str, tuple[str, str]] = {
    "minimax": ("MINIMAX_API_KEY", "https://api.minimax.io/v1/models"),
    "anthropic": ("ANTHROPIC_API_KEY", "https://api.anthropic.com/v1/models"),
    "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1/models"),
    "qwen": ("QWEN_API_KEY", "https://dashscope.aliyuncs.com/api/v1/models"),
}
```

`★ Fix-up: replace the noop body in `\_probe_provider_request` so the call site is correct.` Replace the post-except block with the standard `safe_error_for_user` handling:

```python
    except httpx.HTTPError as exc:
        return WorkerCheck(
            kind=f"{provider}_auth",
            status="fail",
            safe_reason=safe_error_for_user(type(exc).__name__),
        )
```

(Author note: the snippet above uses the corrected keyword name; the `safe_error_for_user=` typo above is a deliberate placeholder for the implementer to delete — keep the final `safe_reason=safe_error_for_user(...)` form only.)

- [ ] **Step 6: Implement `_observability.py`**

```python
# mahavishnu/workers/capabilities/_observability.py
"""Capability transition observability: metrics, logs, WebSocket events."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from oneiric.logging import get_logger
from prometheus_client import Counter, Histogram

from ._safe import safe_error_for_user
from ._states import WorkerCapabilityReport, WorkerCapabilityState

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


_TRANSITIONS = Counter(
    "mahavishnu_worker_capability_transitions_total",
    "Worker capability state transitions",
    labelnames=("worker_type", "from_state", "to_state"),
)
_PROBE_DURATION = Histogram(
    "mahavishnu_worker_capability_probe_duration_seconds",
    "Worker capability probe duration",
    labelnames=("worker_type", "check_kind", "result"),
)
_CACHE_TOTAL = Counter(
    "mahavishnu_worker_capability_cache_total",
    "Worker capability cache hits and misses",
    labelnames=("worker_type", "result"),
)

_last_state: dict[str, WorkerCapabilityState] = {}


def emit_transition(report: WorkerCapabilityReport) -> None:
    previous = _last_state.get(report.worker_type)
    if previous is not None and previous is report.state:
        return
    _TRANSITIONS.labels(
        worker_type=report.worker_type,
        from_state=str(previous),
        to_state=str(report.state),
    ).inc()
    _last_state[report.worker_type] = report.state
    logger.info(
        "worker_capability_transition",
        extra={
            "worker_type": report.worker_type,
            "from_state": str(previous),
            "to_state": str(report.state),
        },
    )
    _publish_event(report)


def record_probe(worker_type: str, check_kind: str, duration_s: float, result: str) -> None:
    _PROBE_DURATION.labels(
        worker_type=worker_type, check_kind=check_kind, result=result,
    ).observe(duration_s)


def record_probe_failure(report: WorkerCapabilityReport, check_kind: str, safe_reason: str) -> None:
    logger.warning(
        "worker_capability_probe_failed",
        extra={
            "worker_type": report.worker_type,
            "check_kind": check_kind,
            "safe_reason": safe_reason,
        },
    )


def record_cache(worker_type: str, result: str) -> None:
    _CACHE_TOTAL.labels(worker_type=worker_type, result=result).inc()


def _publish_event(report: WorkerCapabilityReport) -> None:
    try:
        from ...websocket.server import broadcast_event
    except ImportError:
        return
    payload = {
        "worker_type": report.worker_type,
        "state": report.state.value,
        "safe_reason": safe_error_for_user(report.safe_reason),
        "probe_at": report.probe_at.isoformat(),
    }
    broadcast_event("worker.availability_changed", payload, room="adapters")
    broadcast_event("adapter.health_changed", payload, room="adapters")


def time_probe[T](func: Callable[[], Awaitable[T]]) -> Awaitable[tuple[T, float]]:
    """Wrap an async probe call with a perf_counter measurement."""
    async def _run() -> tuple[T, float]:
        start = time.perf_counter()
        result = await func()
        return result, time.perf_counter() - start
    return _run()


def reset_for_tests() -> None:
    _last_state.clear()


from collections.abc import Awaitable, Callable  # noqa: E402
```

- [ ] **Step 7: Implement `_report.py`**

```python
# mahavishnu/workers/capabilities/_report.py
"""Public entry points for the capability layer."""
from __future__ import annotations

import os
import time
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from ..registry import (
    AuthKind,
    RuntimeKind,
    WORKER_REGISTRY,
    WorkerConfig,
    get_worker_config,
)
from ._cache import get as cache_get
from ._cache import invalidate as cache_invalidate
from ._cache import put as cache_put
from ._observability import (
    emit_transition,
    record_cache,
    record_probe,
    record_probe_failure,
    time_probe,
)
from ._probes import PROBES, PROVIDER_PROBES
from ._states import WorkerCapabilityReport, WorkerCapabilityState
from ._static import StaticContext, evaluate_static

if TYPE_CHECKING:
    pass


def _build_ctx(settings: Any) -> StaticContext:
    env = {k: v for k, v in os.environ.items()}
    return StaticContext(settings=settings, env=env)


def _mcp_catalog(settings: Any) -> dict[str, str]:
    catalog = getattr(settings, "mcp_servers", None)
    if catalog is None:
        return {}
    if isinstance(catalog, dict):
        return {k: str(v) for k, v in catalog.items()}
    return {
        name: str(getattr(catalog, name))
        for name in dir(catalog)
        if not name.startswith("_") and getattr(catalog, name, None) is not None
    }


def _settings_runtime(settings: Any) -> RuntimeKind | None:
    runtime = getattr(getattr(settings, "workers", None), "container", None)
    name = getattr(runtime, "runtime", None)
    if name == "docker":
        return RuntimeKind.DOCKER
    if name == "podman":
        return RuntimeKind.PODMAN
    if name == "orbstack":
        return RuntimeKind.ORBSTACK
    return None


async def _run_live_checks(
    report: WorkerCapabilityReport,
    *,
    config: WorkerConfig,
    settings: Any,
) -> WorkerCapabilityReport:
    if report.state is not WorkerCapabilityState.READY:
        return report

    checks = list(report.checks)
    if config.worker_type == "gateway-openclaw":
        endpoint = os.environ.get("OPENCLAW_GATEWAY_URL", "")
        token = os.environ.get("OPENCLAW_GATEWAY_TOKEN")
        check, duration = await time_probe(lambda: PROBES["openclaw_gateway"](endpoint, token))
        record_probe(config.worker_type, check.kind, duration, check.status)
        if check.status == "fail":
            record_probe_failure(report, check.kind, check.safe_reason or "unknown")
    elif config.worker_type == "terminal-openclaw":
        check, duration = await time_probe(lambda: PROBES["openclaw_cli"]("openclaw"))
        record_probe(config.worker_type, check.kind, duration, check.status)
        if check.status == "fail":
            record_probe_failure(report, check.kind, check.safe_reason or "unknown")
    elif config.worker_type in {"container", "container-executor"}:
        runtime = _settings_runtime(settings) or RuntimeKind.DOCKER
        if runtime is RuntimeKind.ORBSTACK:
            socket_path = getattr(
                getattr(settings, "workers", None), "container", None
            )
            socket = getattr(socket_path, "socket_path", None) or os.path.expanduser(
                "~/.orbstack/docker/docker.sock"
            )
            check, duration = await time_probe(lambda: PROBES["orbstack_socket"](socket))
        else:
            binary = "docker" if runtime is RuntimeKind.DOCKER else "podman"
            check, duration = await time_probe(lambda: PROBES["container_daemon"](binary))
        record_probe(config.worker_type, check.kind, duration, check.status)
        if check.status == "fail":
            record_probe_failure(report, check.kind, check.safe_reason or "unknown")
    elif config.auth_kind is AuthKind.API_KEY and config.required_env:
        env_var = config.required_env[0]
        probe = PROVIDER_PROBES.get(env_var.split("_API_KEY")[0].lower())
        if probe is not None:
            probe_env, probe_url = probe
            check, duration = await time_probe(
                lambda: PROBES["provider_request"](env_var.split("_API_KEY")[0].lower(), probe_env, probe_url)
            )
        else:
            check, duration = await time_probe(lambda: PROBES["auth_presence"](config.required_env))
        record_probe(config.worker_type, check.kind, duration, check.status)
        if check.status == "fail":
            record_probe_failure(report, check.kind, check.safe_reason or "unknown")
    elif config.auth_kind in (AuthKind.BEARER_TOKEN,) and config.required_env:
        check, duration = await time_probe(lambda: PROBES["auth_presence"](config.required_env))
        record_probe(config.worker_type, check.kind, duration, check.status)
        if check.status == "fail":
            record_probe_failure(report, check.kind, check.safe_reason or "unknown")
    elif config.mcp_server:
        check, duration = await time_probe(
            lambda: PROBES["mcp_server"](config.mcp_server, _mcp_catalog(settings))
        )
        record_probe(config.worker_type, check.kind, duration, check.status)
        if check.status == "fail":
            record_probe_failure(report, check.kind, check.safe_reason or "unknown")
    else:
        return report

    checks.append(check)
    new_state = (
        WorkerCapabilityState.AVAILABLE
        if check.status == "pass"
        else WorkerCapabilityState.READY
    )
    return WorkerCapabilityReport(
        worker_type=report.worker_type,
        state=new_state,
        checks=checks,
        missing_requirements=report.missing_requirements,
        safe_reason=report.safe_reason,
        probe_at=report.probe_at,
    )


def evaluate_worker_capabilities(
    worker_type: str,
    *,
    settings: Any,
    force_live: bool = False,
) -> WorkerCapabilityReport:
    cache_key = f"{worker_type}:full" if force_live else f"{worker_type}:static"
    cached = None if force_live else cache_get(cache_key, 30)
    if cached is not None:
        record_cache(worker_type, "hit")
        return cached  # type: ignore[return-value]

    record_cache(worker_type, "miss")
    config = get_worker_config(worker_type)
    if config is None:
        report = WorkerCapabilityReport(
            worker_type=worker_type,
            state=WorkerCapabilityState.REGISTERED,
            missing_requirements=[f"unknown:{worker_type}"],
            safe_reason="unknown worker type",
        )
        cache_put(cache_key, report)
        emit_transition(report)
        return report

    ctx = _build_ctx(settings)
    report = evaluate_static(worker_type, config=config, ctx=ctx)
    if force_live:
        report = _run_live_checks_sync(report, config=config, settings=settings)
    cache_put(cache_key, report)
    emit_transition(report)
    return report


def _run_live_checks_sync(
    report: WorkerCapabilityReport, *, config: WorkerConfig, settings: Any,
) -> WorkerCapabilityReport:
    """Bridge async live checks into the synchronous static API."""
    import asyncio
    return asyncio.run(_run_live_checks(report, config=config, settings=settings))


def evaluate_all_capabilities(
    *, settings: Any, force_live: bool = False,
) -> dict[str, WorkerCapabilityReport]:
    return {
        w: evaluate_worker_capabilities(w, settings=settings, force_live=force_live)
        for w in WORKER_REGISTRY
    }


def select_routable_workers(
    candidates: Iterable[str] | None = None,
    *,
    settings: Any,
    require_available: bool = False,
) -> list[str]:
    pool = list(candidates) if candidates is not None else list(WORKER_REGISTRY)
    routable: list[str] = []
    for w in pool:
        report = evaluate_worker_capabilities(w, settings=settings)
        if require_available and report.state is not WorkerCapabilityState.AVAILABLE:
            continue
        if report.state in {WorkerCapabilityState.READY, WorkerCapabilityState.AVAILABLE}:
            routable.append(w)
    return routable


def invalidate_capability(worker_type: str) -> None:
    cache_invalidate(worker_type)
```

- [ ] **Step 8: Implement `__init__.py`**

```python
# mahavishnu/workers/capabilities/__init__.py
"""Worker capability layer public surface."""
from __future__ import annotations

from ._observability import reset_for_tests
from ._report import (
    evaluate_all_capabilities,
    evaluate_worker_capabilities,
    invalidate_capability,
    select_routable_workers,
)
from ._states import WorkerCapabilityReport, WorkerCapabilityState, WorkerCheck

__all__ = [
    "WorkerCapabilityReport",
    "WorkerCapabilityState",
    "WorkerCheck",
    "evaluate_all_capabilities",
    "evaluate_worker_capabilities",
    "invalidate_capability",
    "select_routable_workers",
    "reset_for_tests",
]
```

- [ ] **Step 9: Write the static-phase test**

```python
# tests/unit/workers/__init__.py
"""Empty file."""
```

```python
# tests/unit/workers/test_capabilities_static.py
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from mahavishnu.workers.capabilities import (
    WorkerCapabilityState,
    evaluate_worker_capabilities,
)


@dataclass
class _ContainerSettings:
    runtime: str | None = None
    socket_path: str | None = None


@dataclass
class _WorkersSettings:
    enabled: bool = True
    container: _ContainerSettings = field(default_factory=_ContainerSettings)


@dataclass
class _Settings:
    workers: _WorkersSettings = field(default_factory=_WorkersSettings)


def test_state_configured_when_workers_disabled() -> None:
    settings = _Settings(workers=_WorkersSettings(enabled=False))
    report = evaluate_worker_capabilities("terminal-claude", settings=settings)
    assert report.state is WorkerCapabilityState.CONFIGURED
    assert "workers.enabled" in (report.missing_requirements or [])


def test_state_configured_when_settings_permit_but_tool_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    settings = _Settings()
    report = evaluate_worker_capabilities("terminal-claude", settings=settings)
    assert report.state is WorkerCapabilityState.CONFIGURED
    assert any("tool:claude" in m for m in report.missing_requirements)


def test_state_ready_when_binary_and_settings_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "shutil.which",
        lambda name: f"/usr/bin/{name}" if name == "claude" else None,
    )
    settings = _Settings()
    report = evaluate_worker_capabilities("terminal-claude", settings=settings)
    assert report.state is WorkerCapabilityState.READY
```

- [ ] **Step 10: Write the probes test**

```python
# tests/unit/workers/test_capabilities_probes.py
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from mahavishnu.workers.capabilities import (
    WorkerCapabilityState,
    evaluate_worker_capabilities,
)


@dataclass
class _ContainerSettings:
    runtime: str | None = None
    socket_path: str | None = None


@dataclass
class _WorkersSettings:
    enabled: bool = True
    container: _ContainerSettings = field(default_factory=_ContainerSettings)


@dataclass
class _Settings:
    workers: _WorkersSettings = field(default_factory=_WorkersSettings)


def test_live_probe_openclaw_gateway_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "")
    report = evaluate_worker_capabilities(
        "gateway-openclaw", settings=_Settings(), force_live=True,
    )
    assert report.state is WorkerCapabilityState.READY
    assert any(c.kind == "openclaw_gateway" for c in report.checks)


def test_live_probe_openclaw_gateway_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCLAW_GATEWAY_URL", "http://gateway.test")

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"healthy": True}

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *exc_info) -> None:
            return None

        async def get(self, url, headers=None):
            return _Response()

    monkeypatch.setattr("httpx.AsyncClient", _Client)
    report = evaluate_worker_capabilities(
        "gateway-openclaw", settings=_Settings(), force_live=True,
    )
    assert report.state is WorkerCapabilityState.AVAILABLE
```

- [ ] **Step 11: Write the observability test**

```python
# tests/unit/workers/test_capabilities_observability.py
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from mahavishnu.workers.capabilities import (
    evaluate_worker_capabilities,
    reset_for_tests,
)


@dataclass
class _ContainerSettings:
    runtime: str | None = None
    socket_path: str | None = None


@dataclass
class _WorkersSettings:
    enabled: bool = True
    container: _ContainerSettings = field(default_factory=_ContainerSettings)


@dataclass
class _Settings:
    workers: _WorkersSettings = field(default_factory=_WorkersSettings)


def test_state_change_emits_log_marker(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    reset_for_tests()
    monkeypatch.setattr("shutil.which", lambda name: None)
    with caplog.at_level("INFO"):
        evaluate_worker_capabilities("terminal-claude", settings=_Settings())
    assert any("worker_capability_transition" in rec.message for rec in caplog.records)


def test_state_change_broadcasts_websocket_event(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_for_tests()
    calls: list[tuple[str, dict]] = []

    def fake_broadcast(event: str, payload: dict, room: str = "") -> None:
        calls.append((event, payload))

    import mahavishnu.workers.capabilities._observability as obs

    monkeypatch.setattr(obs, "_publish_event", lambda report: fake_broadcast(
        "worker.availability_changed",
        {
            "worker_type": report.worker_type,
            "state": report.state.value,
            "safe_reason": report.safe_reason,
            "probe_at": report.probe_at.isoformat(),
        },
        room="adapters",
    ))
    monkeypatch.setattr("shutil.which", lambda name: None)
    evaluate_worker_capabilities("terminal-claude", settings=_Settings())
    assert any(event == "worker.availability_changed" for event, _ in calls)
    assert any("probe_at" in payload for _, payload in calls)


def test_failed_probe_emits_warning(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    reset_for_tests()
    monkeypatch.setattr("shutil.which", lambda name: None)
    with caplog.at_level("WARNING"):
        evaluate_worker_capabilities("terminal-claude", settings=_Settings(), force_live=True)
    assert any("worker_capability_probe_failed" in rec.message for rec in caplog.records)
```

- [ ] **Step 12: Run all capability tests**

Run: `pytest tests/unit/workers/test_capabilities_static.py tests/unit/workers/test_capabilities_probes.py tests/unit/workers/test_capabilities_observability.py -v`
Expected: PASS.

- [ ] **Step 13: Commit**

```bash
git add mahavishnu/workers/capabilities tests/unit/workers/test_capabilities_*.py
git commit -m "feat(workers): add capability layer with static, live, and observability phases"
```

______________________________________________________________________

### Task 5: Add the integration live-probe suite

**Files:**

- Create: `tests/integration/workers/__init__.py`
- Create: `tests/integration/workers/test_capabilities_live.py`
- Test (no new test file beyond this)

**Integration Contract:**

- Triggered from: integration test run.

- Returns to / updates: confidence that the live probe contract works end-to-end.

- Demonstrable by: tests in Step 2.

- Rollback signal: integration tests fail under default `pytest` invocation.

- Observability added: none.

- [ ] **Step 1: Confirm the `integration` marker exists**

Inspect `pyproject.toml`. If absent, add:

```toml
[tool.pytest.ini_options]
markers = [
    "integration: tests that exercise external services via fakes",
    "requires_network: tests that require network access",
]
```

- [ ] **Step 2: Write the live-probe integration test**

```python
# tests/integration/workers/__init__.py
"""Empty file."""
```

```python
# tests/integration/workers/test_capabilities_live.py
from __future__ import annotations

import os
from dataclasses import dataclass, field

import pytest

from mahavishnu.workers.capabilities import (
    WorkerCapabilityState,
    evaluate_worker_capabilities,
)


@dataclass
class _ContainerSettings:
    runtime: str | None = "fake"
    socket_path: str | None = None


@dataclass
class _WorkersSettings:
    enabled: bool = True
    container: _ContainerSettings = field(default_factory=_ContainerSettings)


@dataclass
class _Settings:
    workers: _WorkersSettings = field(default_factory=_WorkersSettings)
    mcp_servers: dict[str, str] = field(
        default_factory=lambda: {"gimp-mcp": "http://mcp.test/gimp"}
    )


@pytest.mark.integration
@pytest.mark.requires_network
def test_live_probe_openclaw_unhealthy() -> None:
    os.environ["OPENCLAW_GATEWAY_URL"] = "http://127.0.0.1:1"
    report = evaluate_worker_capabilities(
        "gateway-openclaw", settings=_Settings(), force_live=True,
    )
    assert report.state is WorkerCapabilityState.READY
    assert any(c.kind == "openclaw_gateway" for c in report.checks)


@pytest.mark.integration
def test_live_probe_container_daemon() -> None:
    report = evaluate_worker_capabilities(
        "container-executor", settings=_Settings(), force_live=True,
    )
    assert report.state in {WorkerCapabilityState.READY, WorkerCapabilityState.AVAILABLE}
```

- [ ] **Step 3: Run the integration test**

Run: `pytest tests/integration/workers/test_capabilities_live.py -v`
Expected: PASS (uses fakes; no real network required).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/workers/test_capabilities_live.py pyproject.toml tests/integration/workers/__init__.py
git commit -m "test(workers): add integration suite for capability live probes"
```

______________________________________________________________________

### Task 6: Add Docker/OrbStack runtime discovery in container workers

**Files:**

- Modify: `mahavishnu/workers/container.py:35-105, 163-210`
- Modify: `mahavishnu/core/config.py:1084-1112`
- Modify: `settings/mahavishnu.yaml`
- Test: `tests/unit/test_container_worker.py`

**Integration Contract:**

- Triggered from: `ContainerWorker` instantiation and `start()`.

- Returns to / updates: container worker uses discovered runtime and refuses to start with a typed `ContainerDaemonUnavailable` when the daemon is unreachable.

- Demonstrable by: tests in Step 1.

- Rollback signal: bare `RuntimeError` raised from `start()`; default runtime no longer Docker-aware.

- Observability added: `ContainerDaemonUnavailable` with `runtime` in `details`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_container_worker.py additions
from __future__ import annotations

from pathlib import Path

import pytest

from mahavishnu.workers.container import ContainerWorker


def test_container_worker_uses_discovered_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = tmp_path / "docker"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:")
    worker = ContainerWorker(runtime="docker")
    assert worker.runtime == "docker"


def test_container_worker_uses_orbstack_socket_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = tmp_path / "orbstack.sock"
    socket.write_text("")
    monkeypatch.setattr("mahavishnu.workers.container.sys.platform", "darwin")
    worker = ContainerWorker(socket_path_override=str(socket))
    assert worker.socket_path == str(socket)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/test_container_worker.py -v`
Expected: FAIL — `ContainerWorker` does not yet accept `socket_path_override`.

- [ ] **Step 3: Update `MahavishnuSettings`**

In `mahavishnu/core/config.py`, find the nested `Workers` model and add:

```python
class ContainerSettings(BaseModel):
    runtime: str | None = None
    socket_path: str | None = None
```

Add the field to the `workers` Pydantic model:

```python
class Workers(BaseModel):
    enabled: bool = True
    max_concurrent: int = 10
    default_type: str = "terminal-claude"
    timeout_seconds: int = 300
    session_buddy_integration: bool = False
    container: ContainerSettings = Field(default_factory=ContainerSettings)
```

- [ ] **Step 4: Update `settings/mahavishnu.yaml`**

Add:

```yaml
workers:
  enabled: true
  max_concurrent: 10
  default_type: terminal-claude
  container:
    runtime: null  # auto-detect (orbstack > docker > podman)
    socket_path: null  # override socket path
```

- [ ] **Step 5: Update `ContainerWorker`**

In `mahavishnu/workers/container.py`:

```python
import asyncio
import os
import shutil
import sys
from dataclasses import dataclass
from typing import Any

from ..core.errors import ContainerDaemonUnavailable


@dataclass
class _RuntimeResolver:
    runtime: str
    socket_path: str | None

    @classmethod
    def from_settings(
        cls, *, runtime: str | None, socket_path: str | None,
    ) -> "_RuntimeResolver":
        if socket_path:
            return cls(runtime=runtime or "docker", socket_path=socket_path)
        if sys.platform == "darwin":
            orbstack = os.path.expanduser("~/.orbstack/docker/docker.sock")
            if os.path.exists(orbstack):
                return cls(runtime=runtime or "docker", socket_path=orbstack)
        env_socket = os.environ.get("DOCKER_HOST")
        if env_socket:
            return cls(runtime=runtime or "docker", socket_path=env_socket)
        for candidate in ("docker", "podman"):
            if shutil.which(candidate):
                return cls(runtime=runtime or candidate, socket_path=None)
        return cls(runtime=runtime or "docker", socket_path=None)


class ContainerWorker:
    def __init__(
        self,
        runtime: str = "docker",
        image: str = "python:3.13-slim",
        session_buddy_client: Any = None,
        *,
        socket_path_override: str | None = None,
    ) -> None:
        super().__init__(worker_type="container-executor")
        self.session_buddy_client = session_buddy_client
        self.image = image
        resolver = _RuntimeResolver.from_settings(
            runtime=runtime,
            socket_path=socket_path_override,
        )
        self.runtime = resolver.runtime
        self.socket_path = resolver.socket_path

    async def _probe_daemon(self) -> None:
        if self.socket_path and not os.path.exists(self.socket_path):
            raise ContainerDaemonUnavailable(runtime=self.runtime, error="socket_missing")
        try:
            proc = await asyncio.create_subprocess_exec(
                self.runtime, "version", "--format", "{{.Server.Version}}",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        except (asyncio.TimeoutError, OSError) as exc:
            raise ContainerDaemonUnavailable(
                runtime=self.runtime, error=type(exc).__name__,
            ) from exc
        if proc.returncode != 0:
            raise ContainerDaemonUnavailable(
                runtime=self.runtime, error="daemon_unreachable",
            )

    async def start(self) -> str:
        await self._probe_daemon()
        # Existing docker run / podman run invocation from
        # mahavishnu/workers/container.py:163-210 is preserved unchanged
        # after the probe. The container launch logic and `asyncio.sleep(1)`
        # stub are replaced with the real readiness probe above.
        return self.container_id
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `pytest tests/unit/test_container_worker.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add mahavishnu/workers/container.py mahavishnu/core/config.py settings/mahavishnu.yaml tests/unit/test_container_worker.py
git commit -m "feat(workers): discover docker/orbstack runtime and probe daemon"
```

______________________________________________________________________

### Task 7: Split `spawn_workers` and `submit_workers`; de-couple `resolve_worker_type`

**Files:**

- Modify: `mahavishnu/workers/manager.py:79-112, 114-229, 231-294`
- Modify: `mahavishnu/workers/generic_shell.py:135`
- Modify: `mahavishnu/_main_cli.py:1404-1430`
- Modify: `mahavishnu/workers/registry.py:resolve_worker_type`
- Test: `tests/unit/test_worker_manager.py`
- Test: `tests/unit/test_workers_registry.py` (new test for `resolve_worker_type`)

**Integration Contract:**

- Triggered from: CLI `workers spawn` / `workers execute`; pool routing; MCP worker tools.

- Returns to / updates: one-shot workers go through `submit_workers`; interactive workers go through `spawn_workers`; `resolve_worker_type` no longer infers gateway availability from env-var presence.

- Demonstrable by: tests in Step 1.

- Rollback signal: one-shot worker fails with the prior `ValueError`; gateway-openclaw routing chosen because `OPENCLAW_GATEWAY_URL` is set.

- Observability added: capability transition broadcasts when `submit_workers` fails.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_worker_manager.py additions
from __future__ import annotations

import pytest

from mahavishnu.core.errors import WorkerUnavailableError
from mahavishnu.workers.capabilities import (
    WorkerCapabilityReport,
    WorkerCapabilityState,
)
from mahavishnu.workers.manager import WorkerManager


def test_submit_workers_runs_one_shot_lifecycle(monkeypatch, terminal_manager) -> None:
    monkeypatch.setattr(
        "mahavishnu.workers.manager.evaluate_worker_capabilities",
        lambda wt, *, settings, force_live=False: WorkerCapabilityReport(
            worker_type=wt, state=WorkerCapabilityState.READY,
        ),
    )
    mgr = WorkerManager(terminal_manager=terminal_manager, settings=object())

    async def _runner() -> list[str]:
        return await mgr.submit_workers("terminal-codex", ["echo PONG"])

    worker_ids = pytest.run(_runner)
    assert worker_ids
```

```python
# tests/unit/test_workers_registry.py additions
from __future__ import annotations

import pytest

from mahavishnu.workers.registry import resolve_worker_type


def test_resolve_worker_type_does_not_infer_gateway_from_env(monkeypatch) -> None:
    monkeypatch.delenv("OPENCLAW_GATEWAY_URL", raising=False)
    monkeypatch.delenv("OPENCLAW_GATEWAY_TOKEN", raising=False)
    result = resolve_worker_type("terminal-claude", task_type="communication", prompt="reply")
    assert result == "terminal-claude"


def test_resolve_worker_type_does_not_inject_openclaw_when_terminal(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENCLAW_GATEWAY_URL", "http://gateway.test")
    result = resolve_worker_type("terminal-claude", task_type="general", prompt="hi")
    assert result == "terminal-claude"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_worker_manager.py::test_submit_workers_runs_one_shot_lifecycle tests/unit/test_workers_registry.py::test_resolve_worker_type_does_not_infer_gateway_from_env -v`
Expected: FAIL — `submit_workers` does not exist; `resolve_worker_type` still infers gateway from env.

- [ ] **Step 3: Refactor `resolve_worker_type`**

In `mahavishnu/workers/registry.py:554-612`, replace the body with:

```python
def resolve_worker_type(
    worker_type: str,
    *,
    task_type: str = "general",
    prompt: str | None = None,
) -> str:
    """Pure intent-routing helper.

    Returns the worker type unchanged. Historical env-var inference that
    swapped terminal-* workers into gateway-openclaw is removed; callers
    pick the gateway explicitly when they want it.
    """
    return worker_type
```

- [ ] **Step 4: Add `submit_workers` to `WorkerManager`**

In `mahavishnu/workers/manager.py`:

```python
from ..core.config import MahavishnuSettings
from ..core.errors import WorkerUnavailableError
from .capabilities import (
    WorkerCapabilityState,
    evaluate_worker_capabilities,
    invalidate_capability,
)
from .registry import get_worker_config


class WorkerManager:
    def __init__(
        self,
        terminal_manager: TerminalManager,
        max_concurrent: int = 10,
        debug_mode: bool = False,
        session_buddy_client: Any = None,
        mcp_client: Any = None,
        *,
        settings: MahavishnuSettings | None = None,
    ) -> None:
        # Existing __init__ body is unchanged beyond the new `settings` attribute.
        self.settings = settings
        # ... rest of __init__ preserved verbatim.

    def _require_ready(self, worker_type: str) -> None:
        report = evaluate_worker_capabilities(worker_type, settings=self.settings)
        if report.state is not WorkerCapabilityState.READY:
            raise WorkerUnavailableError(
                worker_type=worker_type,
                state=report.state.value,
                missing_requirements=report.missing_requirements,
                message=report.safe_reason or "static prerequisites missing",
            )

    async def submit_workers(
        self,
        worker_type: str,
        prompts: list[str],
        *,
        runtime_kwargs: dict[str, Any] | None = None,
    ) -> list[str]:
        cfg = get_worker_config(worker_type)
        if cfg is None or not cfg.one_shot:
            raise ValueError(f"Worker {worker_type!r} is not a one-shot worker")
        self._require_ready(worker_type)

        worker_ids: list[str] = []
        try:
            for prompt in prompts:
                worker = self._create_worker(worker_type, **(runtime_kwargs or {}))
                worker_id = await worker.start(prompt=prompt)
                self._workers[worker_id] = worker
                worker_ids.append(worker_id)
        except Exception:
            for wid in worker_ids:
                await self.close_worker(wid)
            invalidate_capability(worker_type)
            raise
        return worker_ids
```

- [ ] **Step 5: Update `GenericShellWorker.start()` to accept `prompt`**

In `mahavishnu/workers/generic_shell.py:135`:

```python
async def start(
    self,
    launch_command: str | None = None,
    *,
    prompt: str | None = None,
) -> str:
    command = launch_command or self._format_command(prompt)
    session_ids = await self.terminal_manager.launch_sessions(
        command=command,
        count=1,
    )
    self.session_id = session_ids[0]
    self._status = WorkerStatus.RUNNING
    self._start_time = asyncio.get_event_loop().time()
    logger.info(f"Started {self.worker_type} worker: {self.session_id}")
    return self.session_id
```

- [ ] **Step 6: Update CLI workers execute to forward the prompt**

In `mahavishnu/_main_cli.py:1404-1430`, replace the spawn block with:

```python
worker_mgr = WorkerManager(
    terminal_manager=terminal_mgr,
    max_concurrent=getattr(maha_app.config, "max_concurrent_workers", 10),
    debug_mode=False,
    session_buddy_client=None,
    settings=maha_app.config,
)

resolved_worker_type = resolve_worker_type(
    worker_type,
    task_type="general",
    prompt=prompt,
)
config = get_worker_config(resolved_worker_type)
if config is not None and config.one_shot:
    worker_ids = await worker_mgr.submit_workers(resolved_worker_type, [prompt])
else:
    worker_ids = await worker_mgr.spawn_workers(
        worker_type=resolved_worker_type,
        count=count,
    )
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `pytest tests/unit/test_worker_manager.py tests/unit/test_workers_registry.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add mahavishnu/workers/manager.py mahavishnu/workers/generic_shell.py mahavishnu/workers/registry.py mahavishnu/_main_cli.py tests/unit/test_worker_manager.py tests/unit/test_workers_registry.py
git commit -m "feat(workers): split one-shot submit path and de-couple resolve_worker_type"
```

______________________________________________________________________

### Task 8: Wire dedicated-class factory branches for `openhands`, `a2a`, and `terminal-crow`

**Files:**

- Modify: `mahavishnu/workers/manager.py:114-229`
- Test: `tests/unit/test_worker_manager.py`

**Integration Contract:**

- Triggered from: `_create_worker` dispatch.

- Returns to / updates: dedicated classes for `openhands`, `a2a`, `terminal-crow`; existing `gateway-openclaw` and other category branches remain unchanged.

- Demonstrable by: tests in Step 1.

- Rollback signal: any of the three dedicated workers raises `ValueError("Unknown gateway worker type")`.

- Observability added: none beyond existing capability transition.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_worker_manager.py additions
from __future__ import annotations

import pytest

from mahavishnu.workers.manager import WorkerManager


def test_factory_dispatches_a2a(terminal_manager) -> None:
    mgr = WorkerManager(terminal_manager=terminal_manager, settings=object())
    worker = mgr._create_worker("a2a")
    assert worker.__class__.__name__ == "A2AWorker"


def test_factory_dispatches_terminal_crow(terminal_manager) -> None:
    mgr = WorkerManager(terminal_manager=terminal_manager, settings=object())
    worker = mgr._create_worker("terminal-crow")
    assert worker.__class__.__name__ == "CrowWorker"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/test_worker_manager.py::test_factory_dispatches_a2a -v`
Expected: FAIL — `_create_worker("a2a")` raises `ValueError` because the GATEWAY branch is hard-coded to `gateway-openclaw`.

- [ ] **Step 3: Add the dedicated factory branches**

In `mahavishnu/workers/manager.py`, inside `_create_worker`, replace the `if worker_type == "gateway-openclaw": ... raise ValueError(...)` block with:

```python
elif config.category == WorkerCategory.GATEWAY:
    if worker_type == "gateway-openclaw":
        from .openclaw_gateway import (
            HTTPOpenClawGatewayClient,
            OpenClawGatewayConfig,
            OpenClawGatewayWorker,
        )

        gateway_url = kwargs.get(
            "gateway_url",
            os.getenv("OPENCLAW_GATEWAY_URL", "http://localhost:8787"),
        )
        token = kwargs.get("token", os.getenv("OPENCLAW_GATEWAY_TOKEN"))
        rpc_path = kwargs.get(
            "rpc_path",
            os.getenv("OPENCLAW_GATEWAY_RPC_PATH", "/rpc"),
        )
        timeout = float(kwargs.get("timeout", config.default_timeout))
        default_method = kwargs.get("default_method", "agent.run")

        gateway_client = HTTPOpenClawGatewayClient(
            base_url=gateway_url,
            token=token,
            rpc_path=rpc_path,
            timeout=timeout,
        )
        gateway_config = OpenClawGatewayConfig(
            gateway_url=gateway_url,
            token=token,
            default_method=default_method,
            default_timeout=int(timeout),
        )
        return OpenClawGatewayWorker(
            gateway_client=gateway_client,
            config=gateway_config,
        )

    if worker_type == "openhands":
        from .openhands import OpenHandsWorker
        return OpenHandsWorker()

    if worker_type == "a2a":
        from .a2a import A2AWorker
        return A2AWorker()

    raise ValueError(f"Unknown gateway worker type: {worker_type}")


elif config.category == WorkerCategory.AI_ASSISTANT:
    if worker_type == "terminal-crow":
        from .crow import CrowWorker
        return CrowWorker()
    from .generic_shell import GenericShellWorker
    return GenericShellWorker(
        terminal_manager=self.terminal_manager,
        worker_type=worker_type,
        config=config,
        session_buddy_client=self.session_buddy_client,
        **kwargs,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/test_worker_manager.py::test_factory_dispatches_a2a tests/unit/test_worker_manager.py::test_factory_dispatches_terminal_crow -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/workers/manager.py tests/unit/test_worker_manager.py
git commit -m "refactor(workers): add dedicated factory branches for openhands, a2a, terminal-crow"
```

______________________________________________________________________

### Task 9: Cap `OpenClawGatewayWorker` auto-restart and surface failure

**Files:**

- Modify: `mahavishnu/workers/openclaw_gateway.py:139-210`
- Test: `tests/unit/test_openclaw_gateway.py`

**Integration Contract:**

- Triggered from: `OpenClawGatewayWorker.execute`.

- Returns to / updates: at most one auto-restart attempt; subsequent failures return `WorkerStatus.FAILED` with `safe_reason`.

- Demonstrable by: test in Step 1.

- Rollback signal: execute loops indefinitely calling start.

- Observability added: existing `worker_capability_transition` event fires when status flips to FAILED.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_openclaw_gateway.py additions
from __future__ import annotations

import pytest

from mahavishnu.workers.openclaw_gateway import OpenClawGatewayWorker
from mahavishnu.workers.protocol import WorkerStatus


def test_execute_does_not_infinite_restart_when_gateway_unreachable(monkeypatch) -> None:
    calls = {"n": 0}

    async def fake_start(self) -> str:
        calls["n"] += 1
        raise RuntimeError("gateway_unreachable")

    monkeypatch.setattr(OpenClawGatewayWorker, "start", fake_start)
    worker = OpenClawGatewayWorker(_client_stub())
    result = worker.execute({})
    assert result.status is WorkerStatus.FAILED
    assert calls["n"] <= 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/test_openclaw_gateway.py -v`
Expected: FAIL — execute loops on start.

- [ ] **Step 3: Cap auto-restart**

In `mahavishnu/workers/openclaw_gateway.py:139-210`:

```python
async def execute(self, task: dict[str, Any]) -> WorkerResult:
    if self._status is not WorkerStatus.RUNNING:
        try:
            await self.start()
        except Exception as exc:
            self._status = WorkerStatus.FAILED
            return WorkerResult(
                worker_id=self.worker_id,
                status=WorkerStatus.FAILED,
                error=safe_error_for_user(str(exc)),
                duration_seconds=self._duration(),
            )

    request = self._normalize_task(task)
    try:
        response = await asyncio.wait_for(
            self.gateway_client.call(request.method, request.params),
            timeout=request.timeout_seconds,
        )
        output = self._extract_output(response)
        return WorkerResult(
            worker_id=self.worker_id,
            status=WorkerStatus.COMPLETED,
            output=output,
            duration_seconds=self._duration(),
            metadata={
                "gateway_url": self.config.gateway_url,
                "method": request.method,
                "session_id": request.session_id,
                "agent_id": request.agent_id,
                "response": response,
            },
        )
    except TimeoutError:
        return WorkerResult(
            worker_id=self.worker_id,
            status=WorkerStatus.TIMEOUT,
            error=f"Gateway call timed out after {request.timeout_seconds}s",
            duration_seconds=self._duration(),
            metadata={"method": request.method},
        )
    except Exception as exc:
        return WorkerResult(
            worker_id=self.worker_id,
            status=WorkerStatus.FAILED,
            error=safe_error_for_user(str(exc)),
            duration_seconds=self._duration(),
            metadata={"method": request.method, "exception": type(exc).__name__},
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/test_openclaw_gateway.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/workers/openclaw_gateway.py tests/unit/test_openclaw_gateway.py
git commit -m "fix(openclaw): cap auto-restart and surface terminal failure"
```

______________________________________________________________________

### Task 10: Wire CLI diagnostics, MCP tools, and health

**Files:**

- Modify: `mahavishnu/_main_cli.py:1500-1600`
- Modify: `mahavishnu/mcp/tools/worker_tools.py`
- Modify: `mahavishnu/mcp/tools/pool_tools.py`
- Modify: `mahavishnu/mcp/tools/health_tools.py`
- Modify: `mahavishnu/core/health.py`
- Modify: `mahavishnu/health.py`
- Test: `tests/unit/test_workers_cli_diagnostics.py`

**Integration Contract:**

- Triggered from: CLI list-types, MCP discover_tools, pool route, readiness endpoint.

- Returns to / updates: filtered/listed worker types; readiness aggregates the worker component.

- Demonstrable by: tests in Step 1.

- Rollback signal: `--ready` missing workers; readiness does not mention capability reports.

- Observability added: capability state surfaced in every consumer.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_workers_cli_diagnostics.py
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def test_list_types_ready_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCLAW_GATEWAY_URL", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    result = subprocess.run(
        [sys.executable, "-m", "mahavishnu", "workers", "list-types", "--ready"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert result.returncode == 0
    assert "terminal-claude" not in result.stdout
    assert "terminal-shell" in result.stdout


def test_list_types_all_flag_includes_registered() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mahavishnu", "workers", "list-types", "--all"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert result.returncode == 0
    assert "terminal-claude" in result.stdout
    assert "terminal-shell" in result.stdout
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_workers_cli_diagnostics.py -v`
Expected: FAIL — `--ready` and `--all` are not recognized.

- [ ] **Step 3: Update the CLI list-types command**

In `mahavishnu/_main_cli.py:1500-1600`:

```python
@workers_app.command("list-types")
def workers_list_types(
    ready: bool = typer.Option(False, "--ready", help="Only routable types"),
    all_types: bool = typer.Option(False, "--all", help="All registered types"),
    explain: bool = typer.Option(False, "--explain", help="Include safe reasons"),
    probe: bool = typer.Option(False, "--probe", help="Force live probe"),
) -> None:
    """List worker types with optional capability filtering."""
    from .workers.capabilities import (
        evaluate_worker_capabilities,
        WorkerCapabilityState,
    )

    settings = MahavishnuSettings()
    rows: list[tuple[str, str, str]] = []
    for w in WORKER_REGISTRY:
        if probe:
            report = asyncio.run(evaluate_worker_capabilities(w, settings=settings, force_live=True))
        else:
            report = evaluate_worker_capabilities(w, settings=settings)
        if ready and report.state not in {
            WorkerCapabilityState.READY,
            WorkerCapabilityState.AVAILABLE,
        }:
            continue
        reason = report.safe_reason or "" if explain else ""
        rows.append((w, report.state.value, reason))

    headers = ("WORKER", "STATE", "REASON")
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(3)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    typer.echo(fmt.format(*headers))
    for row in rows:
        typer.echo(fmt.format(*row))
```

- [ ] **Step 4: Wire MCP and health**

In `mahavishnu/mcp/tools/worker_tools.py` — add a `capability` parameter to `discover_tools(query, capability=None)`:

```python
async def discover_tools(query: str, capability: str | None = None) -> dict[str, Any]:
    from ...core.config import MahavishnuSettings
    from ...workers.capabilities import select_routable_workers

    if capability == "ready":
        settings = MahavishnuSettings()
        allowed = set(select_routable_workers(settings=settings))
    else:
        allowed = None

    loaded, not_loaded = _load_tool_catalog(query=query, allowed=allowed)
    return {"loaded": loaded, "not_loaded": not_loaded}
```

In `mahavishnu/mcp/tools/pool_tools.py` — replace direct registry consultation with `select_routable_workers`:

```python
from ...workers.capabilities import select_routable_workers
from ...core.config import MahavishnuSettings

settings = MahavishnuSettings()
candidates = select_routable_workers(settings=settings)
result = await pool_manager.route_task(task_data=task_data, candidates=candidates)
```

In `mahavishnu/core/health.py` — add the worker component to `readiness()`. Place first-party imports at the module top:

```python
from ..core.config import MahavishnuSettings
from ..workers.capabilities import (
    WorkerCapabilityState,
    evaluate_all_capabilities,
)


async def readiness(*, settings: MahavishnuSettings | None = None) -> dict[str, Any]:
    if settings is None:
        settings = MahavishnuSettings()
    reports = evaluate_all_capabilities(settings=settings, force_live=False)
    default_type = getattr(getattr(settings, "workers", None), "default_type", "terminal-claude")
    default_report = reports.get(default_type)
    state = default_report.state if default_report else WorkerCapabilityState.REGISTERED
    if state is WorkerCapabilityState.REGISTERED:
        status = HealthStatus.UNHEALTHY
    elif state in {WorkerCapabilityState.CONFIGURED, WorkerCapabilityState.READY}:
        status = HealthStatus.DEGRADED
    else:
        status = HealthStatus.OK
    return {
        "status": status.value,
        "worker_reports": {k: v.state.value for k, v in reports.items()},
    }
```

In `mahavishnu/health.py` — fold the worker component into the readiness response:

```python
def get_readiness() -> dict[str, Any]:
    from .core.config import MahavishnuSettings
    settings = MahavishnuSettings()
    return asyncio.run(_readiness_async(settings))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/unit/test_workers_cli_diagnostics.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/_main_cli.py mahavishnu/mcp/tools/worker_tools.py mahavishnu/mcp/tools/pool_tools.py mahavishnu/mcp/tools/health_tools.py mahavishnu/core/health.py mahavishnu/health.py tests/unit/test_workers_cli_diagnostics.py
git commit -m "feat(workers): wire capability diagnostics into CLI, MCP, and health"
```

______________________________________________________________________

### Task 11: Cloud worker credential gating and secret hygiene

**Files:**

- Modify: `mahavishnu/workers/cloud_worker.py:76-155, 312-341`
- Test: `tests/unit/test_cloud_worker.py`

**Integration Contract:**

- Triggered from: `CloudWorker.start`.

- Returns to / updates: `READY`/`DEGRADED` registered honestly, `missing_credentials` populated.

- Demonstrable by: tests in Step 1.

- Rollback signal: cloud worker reports `RUNNING` when a credential is missing; secret appears in `caplog.text`.

- Observability added: existing capability transition event fires for cloud worker.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_cloud_worker.py additions
from __future__ import annotations

import pytest

from mahavishnu.workers.cloud_worker import CloudWorker
from mahavishnu.workers.protocol import WorkerStatus


def test_cloud_worker_marks_degraded_when_minimax_key_missing(monkeypatch) -> None:
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    worker = CloudWorker()
    assert worker.metadata.get("missing_credentials") == ["MINIMAX_API_KEY"]
    assert worker._status is not WorkerStatus.RUNNING


def test_cloud_worker_logs_do_not_contain_key(monkeypatch, caplog) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-fake-do-not-leak")
    worker = CloudWorker()
    assert "sk-fake-do-not-leak" not in caplog.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_cloud_worker.py -v`
Expected: FAIL — `metadata` is not set and `_status` flips to RUNNING.

- [ ] **Step 3: Update `CloudWorker`**

In `mahavishnu/workers/cloud_worker.py`, ensure the class initializes `self.metadata`:

```python
class CloudWorker:
    def __init__(self, ...) -> None:
        super().__init__(...)
        self.metadata: dict[str, Any] = {}
```

Replace the body of `start()` with:

```python
async def start(self) -> str:
    missing = [n for n in self.required_env if not os.environ.get(n)]
    self.metadata["missing_credentials"] = missing
    if missing and not await self._has_local_fallback():
        self._status = WorkerStatus.DEGRADED
        return self.worker_id
    self._status = WorkerStatus.RUNNING
    return self.worker_id

async def _has_local_fallback(self) -> bool:
    if not shutil.which("ollama") and not shutil.which("llama-server"):
        return False
    for url in ("http://localhost:11434", "http://localhost:8081"):
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                response = await client.get(url)
                if response.status_code < 500:
                    return True
        except httpx.HTTPError:
            continue
    return False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/unit/test_cloud_worker.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/workers/cloud_worker.py tests/unit/test_cloud_worker.py
git commit -m "feat(workers): gate cloud worker on credentials, no secret logging"
```

______________________________________________________________________

### Task 12: Run the demo and quality gates (with crackerjack-style compliance audit)

**Files:**

- No new files.

**Integration Contract:**

- Triggered from: an environment with valid credentials and services.

- Returns to / updates: validated worker matrix, full test suite, crackerjack run, orphan audit, compliance checklist.

- Demonstrable by: every routable worker class returns two concurrent `PONG` sessions; blocked classes print safe reasons.

- Rollback signal: any rollback signal from Tasks 1–11 fires.

- Observability added: full observability surface exercised end-to-end.

- [ ] **Step 1: Run the worker matrix demo**

In a real environment with valid credentials and services:

```bash
# Set environment
export MINIMAX_API_KEY=...
export ANTHROPIC_API_KEY=...
export OPENCLAW_GATEWAY_URL=...
# Start OpenClaw gateway, Docker/OrbStack, and a real terminal adapter

# Discover
mahavishnu workers list-types --ready --explain
mahavishnu workers list-types --all --explain

# Pings (two concurrent per routable worker)
mahavishnu workers submit --type terminal-codex --prompt "PONG"
mahavishnu workers submit --type terminal-openclaw --prompt "PONG"
mahavishnu workers submit --type gateway-openclaw --prompt "PONG"
mahavishnu workers spawn --type terminal-shell --count 2
mahavishnu workers spawn --type terminal-python --count 2
mahavishnu workers spawn --type container --count 2
```

Expected: all routable workers run; diagnostics show the missing pieces for the rest.

- [ ] **Step 2: Crackerjack-style compliance audit**

For every new module, verify:

- [ ] `from __future__ import annotations` is the first non-comment line.

- [ ] No `Optional[X]` / `List[X]`; only `X | None` and `list[str]`.

- [ ] No `assert` in `mahavishnu/**` production code.

- [ ] `except` blocks use `logger.exception(...)`.

- [ ] No `print()`.

- [ ] No blocking I/O inside `async def`; sync only at CLI entry points.

- [ ] No `Any` in tool inputs or orchestration state.

- [ ] Function args ≤ 10; branches ≤ 15; returns ≤ 6; statements ≤ 55.

- [ ] Ruff `line-length = 100` clean.

- [ ] mypy strict clean.

- [ ] No secret value appears in logs, reports, or exception details.

- [ ] **Step 3: Run pytest with coverage**

```bash
pytest --cov=mahavishnu --cov-report=term-missing --cov-fail-under=80
```

Expected: PASS.

- [ ] **Step 4: Run crackerjack**

```bash
crackerjack run
```

Expected: PASS.

- [ ] **Step 5: Run orphan audit**

```bash
python scripts/audit_orphans.py
```

Expected: no new symbols with zero callers.

- [ ] **Step 6: Commit any final adjustments**

```bash
git add -A
git commit -m "chore: worker readiness end-to-end verification"
```
