# Apple Container Worker (microVM per task)

## State

| State | Status | Date | Notes |
|-------|--------|------|-------|
| built | ✅ | 2026-07-26 | Authored on Intel hardware; mock-only tests pass (25 tests) |
| wired | ✅ | 2026-07-27 | Tier fallback live: `WorkerManager._create_isolated_worker` routes CONTAINER category → Apple tier → E2B tier; Docker/OrbStack `ContainerWorker` removed |
| adopted | ❌ | — | Blocked on Apple silicon hardware for verification |

## What it is

`mahavishnu/workers/apple_container.py` — `AppleContainerWorker`, a
`BaseWorker` that executes tasks in per-task microVMs via Apple's
open-source `container` CLI (Apple silicon + macOS 26 only). Replaces the
Docker/OrbStack shared-kernel path as the local isolation tier.

Supporting pieces:

- `mahavishnu/workers/_exec_guard.py` — command allowlist/deny-pattern
  validation shared by isolation runtimes (extracted from `ContainerWorker`
  so adapters need not import the Docker-era worker).
- `AppleContainerUnsupported` in `mahavishnu/core/errors.py` — typed
  "wrong hardware" signal. **Semantics: skip to the next isolation tier**
  (cloud sandbox pool), unlike `ContainerDaemonUnavailable` which means
  "right hardware, runtime broken — fail loud."
- Registry: `RuntimeKind.APPLE_CONTAINER` + `"apple-container"` worker
  config; manager creates `AppleContainerWorker` for that worker type.

## Integration Contract

- **Triggered from:** `WorkerManager._create_worker(worker_type="apple-container")`.
- **Returns to / updates:** `WorkerResult` to callers; results stored in
  Session-Buddy via `store_memory` when a client is configured.
- **Demonstrable by:** `pytest tests/unit/workers/test_apple_container.py`
  (mock-only); on Apple silicon: spawn `apple-container` worker and run
  `{"command": "echo hello"}`.
- **Rollback signal:** `AppleContainerUnsupported` on unsupported hosts →
  caller routes to next tier; construction failure leaves no state behind.
- **Observability added:** structured log lines on start/stop/exec failure
  (`apple-container` runtime tag in `WorkerResult.metadata`).

## Open wiring work

1. ~~Tier-fallback consumption~~ ✅ 2026-07-27: `_create_isolated_worker`
   in `workers/manager.py` catches `AppleContainerUnsupported` and falls
   through to `E2BSandboxWorker` (see
   `docs/feature-tracking/e2b-sandbox-worker.md`).
1. **Hardware verification** (authored on Intel; cannot run here) — verify
   on an Apple silicon Mac with macOS 26+ and `container` 1.0+:
   - [ ] `container system status` is the right liveness probe (and its
     exit code semantics); adjust `_probe_runtime` if the subcommand
     differs. May need `container system start` first.
   - [ ] `container run --detach --rm [--cpus N] [--memory X] IMAGE sleep infinity` — flag spellings and that stdout is the container ID.
   - [ ] `container exec ID sh -c ...` works against a `--detach` VM and
     the image auto-pulls on first `run`.
   - [ ] `container inspect ID` JSON schema — `_inspect_reports_running`
     tolerates list/object forms and `status`/`state` keys; pin the real
     schema once observed and tighten the parser.
   - [ ] `container stop` on a `--rm` container fully removes the VM.
1. **Docker-path deprecation**: once verified, decide the removal schedule
   for `ContainerWorker` (Docker/Podman/OrbStack) per the
   containers-to-microVMs plan discussion (2026-07-26 session).

## References

- Apple container: <https://github.com/apple/container> (1.0.0, 2026-06-09)
- Research session: microVM isolation tiers (Apple container local /
  E2B cloud sandbox / Cloud Run services), 2026-07-26.
