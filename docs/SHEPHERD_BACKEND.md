# Shepherd worker backend

> Phase 4 of the [v2 plan](plans/2026-08-29-orchestrator-research-synthesis.md)
> (lines 231–255). Adds an OS-level syscall-jail worker backend
> alongside the Apple-container and E2B tiers.

`worker_type="shepherd"` routes to
[`ShepherdBackendWorker`](../mahavishnu/workers/shepherd_backend.py),
which delegates task execution to
[Shepherd](https://github.com/shepherd-agents/shepherd) (MIT, arXiv
2605.10913). Shepherd compiles bodyless task signatures
(`May[GitRepo, ...]`) into a real kernel jail:

- **macOS Seatbelt** — `sandbox-exec` profile compiled from the task's
  grant.
- **Linux Landlock** — kernel-side filesystem deny ruleset
  (privileged container only).
- **copy / FUSE** — portable carrier used when the native jail is
  unavailable (auto-tier falls through to advisory).

The wrapper conforms to
[`BaseWorker`](../mahavishnu/workers/base.py) so existing pool
routing, `WorkerManager.execute_task`, and the WebSocket event
surface are agnostic to which isolation tier served the task.

## Quick start

```python
from mahavishnu.workers.shepherd_backend import ShepherdBackendWorker

worker = ShepherdBackendWorker(
    writable_root="/srv/jobs/run-42",
    placement="jail",
)
await worker.start()
result = await worker.execute({"task_ref": my_shepherd_task, ...})
await worker.stop()
```

Or via the manager / pool:

```python
worker_id = manager.spawn_worker(
    worker_type="shepherd",
    task_spec={
        "writable_root": "/srv/jobs/run-42",
        "placement": "jail",
    },
)[0]
```

`pool_route_execute(worker_type="shepherd", ...)` is supported once
the worker is registered in
[`WORKER_REGISTRY`](../mahavishnu/workers/registry.py) (it is — see
[Registry wiring](#registry-wiring)).

## Installation

Shepherd is an **optional** dependency — a lean `uv sync` install does
not pull pygit2 / click / tomli-w / pydantic only to skip them at
runtime. Install the worker with:

```bash
uv sync --group shepherd
```

The wrapper imports the SDK lazily; absence surfaces as
[`RuntimeError("ShepherdBackendWorker requires 'shepherd-ai'. ..." )`](../mahavishnu/workers/shepherd_backend.py) on construction so
pool routing never silently downgrades.

## Capability model

Shepherd tasks are **bodyless**: a task declares what it *would*
read/write via `May[GitRepo, ...]` parameters and Shepherd compiles
that declaration into a real jail. The wrapper maps Mahavishnu task
inputs onto Shepherd's authorization language:

| Mahavishnu field | Shepherd surface | Notes |
|---|---|---|
| `writable_root: str` | workspace root | Required; refusal to start without it is the audit trail. The wrapper creates it if missing. |
| `workspace_cwd: str` (optional) | `ShepherdWorkspace.discover` target | Defaults to `writable_root`. |
| `placement: "auto" \| "advisory" \| "jail"` | `workspace.run(..., placement=...)` | `"jail"` is fail-closed (raises `ShepherdJailUnavailableError` when the host cannot enforce it). |
| `task_ref: callable` | bodyless task body | Substrate derives task identity from `__module__` / `__qualname__`. Inner / local callables are refused. |
| `command: str` (optional) | synthesized `May[GitRepo, ...]` task | Convenience path for parity with `AppleContainerWorker` / `E2BSandboxWorker`; the command must be on the `_exec_guard` allowlist. |
| \*\*kwargs (`target=...`, `input=...`) | task keyword arguments | Forwarded to the task body via `workspace.run(task_ref, **kwargs)`. |

The wrapper's [`execute`](../mahavishnu/workers/shepherd_backend.py)
method surfaces a [`WorkerResult`](../mahavishnu/workers/base.py) with
metadata:

- `runtime`: `"shepherd"`
- `placement`: the resolved carrier (`"seatbelt"` /
  `"landlock"` / `"clonefile"` / `"fuse-overlay"`).
- `settle_ref`: the substrate's `RunRef` (consumed by v2 Phase 2's
  `worker_settle` MCP tool).
- `changeset`: `ChangesetStat`-derived dict with `state`,
  `changed_path_count`, etc. — the diff view substrate consumers use
  for settle reporting.
- `task_ref`: the recorded task identifier.

## Settle operations

Settle integration is **delegated to the substrate** rather than
re-implemented:

- [`WorkspaceRun.changeset()`](https://github.com/shepherd-agents/shepherd)
  returns the read-only diff view. The wrapper maps it onto
  `WorkerResult.metadata["changeset"]`.
- `ChangesetStat` (a small read-only summary) is the substrate's
  settled view; v2 Phase 2's `worker_settle` MCP tool consumes it
  from `mahavishnu://workers/{worker_id}.json`.

This is a deliberate decision — Dhara mirrors the substrate's
durable record rather than storing a parallel settlement stream.
See
[`docs/WEBSOCKET_CONSUMER_GUIDE.md`](WEBSOCKET_CONSUMER_GUIDE.md) for
the canonical settle contract.

## Failure modes

| Failure | Where it surfaces | Notes |
|---|---|---|
| `shepherd-ai` SDK not installed | `RuntimeError` on construction | Wrapper checks `ShepherdWorkspace is None` at `__init__`. Never falls through to Apple / E2B. |
| Host cannot enforce `placement="jail"` | [`ShepherdJailUnavailableError`](../mahavishnu/workers/shepherd_backend.py) raised at construction | `probe_host_capability(placement="auto"|"jail")` is the contract. `placement="auto"` may return `available=False` on platforms without a Shepherd jail carrier (the wrapper refuses to start in that case too). |
| Substrate fails to open the workspace | `ShepherdJailUnavailableError` re-raised from `start()` | Wraps the substrate exception; never fabricates success. |
| Task body raises `EffectNotPermitted` | `WorkerResult(status=FAILED, error=..., metadata["exception"]="EffectNotPermitted")` | Wrapper maps the substrate refusal onto a failed result; the audit trail preserves the exception class name. |
| Task body raises `AmbientWorldAccessRefused` | `WorkerResult(status=FAILED, error=..., metadata["exception"]="AmbientWorldAccessRefused")` | Substrate-side check that the body has the requested handle grant. |
| `command` is not on the allowlist | `ValueError` from `_exec_guard.validate_command` | Standard Mahavishnu exec guard; never bypasses. |
| `writable_root` is `None` | `TypeError` from `Path.resolve()` | Construction refuses to start without an explicit write grant. |

### Fail-closed contract

The wrapper MUST NOT silently fall back to a less-secure backend
(`AppleContainerWorker`, `E2BSandboxWorker`, no-op pass-through).
`WorkerManager._create_isolated_worker` adds the shepherd branch
**before** the apple / e2b branches so the dispatch cannot reach a
fallback tier without a Python edit. `tests/unit/workers/test_shepherd_backend.py::TestManagerDispatch::test_create_isolated_worker_shepherd_does_not_fall_through`
pins this assertion.

## Registry wiring

`ShepherdBackendWorker` is registered as
`worker_type="shepherd"` in
[`WORKER_REGISTRY`](../mahavishnu/workers/registry.py) with
`category=WorkerCategory.CONTAINER`. `pool_route_execute` and the
generic shell fallback both discover it via
`get_worker_config("shepherd")`. The lazy-import table in
[`mahavishnu/workers/__init__.py`](../mahavishnu/workers/__init__.py)
re-exports `ShepherdBackendWorker`, `ShepherdBackendError`,
`ShepherdJailUnavailableError`, and `probe_host_capability` so
upstream code can `from mahavishnu.workers import ShepherdBackendWorker`
without depending on the optional SDK.

The capability-driven registry in
[`mahavishnu/core/config.py`](../mahavishnu/core/config.py) (`WorkerEntry`)
can also declare `worker_type: "shepherd"` in
`settings/mahavishnu.yaml:worker_registry.entries[]` for users who
prefer the new registry.

## Testing

The wrapper ships with two test suites:

- `tests/unit/workers/test_shepherd_backend.py` — host probe,
  fail-closed startup, execute contract, registry wiring, manager
  dispatch. 23 tests, all stubbed at the substrate boundary.
- `tests/integration/test_shepherd_backend.py` — capability probe
  against the real SDK plus substrate round-trip smoke. The smoke
  tests skip on hosts where Shepherd's confined execution refuses to
  import the test-task module (a known limitation of testing
  confinement from a pytest context).

Run the suites:

```bash
pytest tests/unit/workers/test_shepherd_backend.py -v
pytest tests/integration/test_shepherd_backend.py -v
```

### Verifying Seatbelt / Landlock enforcement on real hardware

The capability probe tests verify the wrapper's host-detection
contract; real syscall enforcement requires a host Shepherd
recognizes as jail-capable. On macOS:

```bash
sp init /tmp/shepherd-demo
cd /tmp/shepherd-demo
python -c "
import asyncio
from mahavishnu.workers.shepherd_backend import ShepherdBackendWorker

async def main() -> None:
    w = ShepherdBackendWorker(writable_root='/tmp/shepherd-demo', placement='jail')
    await w.start()
    # Write inside the workspace root — allowed.
    inside = '/tmp/shepherd-demo/inside.txt'
    # Write outside the workspace root — refused at the Seatbelt boundary.
    outside = '/tmp/outside.txt'

    # Bodyless task that writes via stdlib ``open``:
    def _write(target: str, _repo):
        open(target, 'w').write('x')
        return target

    print(await w.execute({'task_ref': _write, 'target': inside}))
    print(await w.execute({'task_ref': _write, 'target': outside}))  # fails
    await w.stop()

asyncio.run(main())
"
```

The wrapper's `placement="jail"` is honoured — Seatbelt profile
compiled from `ShepherdWorkspace.git_repo()` will refuse the second
write at the syscall boundary. The wrapper records the refusal as
`WorkerResult(status=FAILED, exception="EffectNotPermitted", ...)`.

On Linux, the same script requires a privileged container
(`CAP_SYS_ADMIN`) so Landlock can install the ruleset; without it,
Shepherd degrades to the FUSE carrier (advisory only) and the
wrapper's `probe_host_capability("landlock")` returns the carrier
name `landlock` but the substrate itself will surface a
configuration error when the carrier fails to install the
kernel-side ruleset.

## Cross-references

- v2 plan §Phase 4 — `docs/plans/2026-08-29-orchestrator-research-synthesis.md`,
  lines 231–255.
- Integration contract — `docs/plans/2026-08-29-orchestrator-research-synthesis.md`,
  lines 249–255.
- Worker base class — `mahavishnu/workers/base.py`.
- Apple container / E2B siblings — `mahavishnu/workers/apple_container.py`,
  `mahavishnu/workers/e2b_sandbox.py`.
- Capability-driven registry — `mahavishnu/core/config.py`,
  `mahavishnu/workers/capabilities/`.
- Phase 2 settle MCP tools — `docs/WEBSOCKET_CONSUMER_GUIDE.md`.
