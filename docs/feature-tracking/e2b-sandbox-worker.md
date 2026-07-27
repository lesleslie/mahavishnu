# E2B Sandbox Worker (tier-2 cloud microVM isolation)

## State

| State | Status | Date | Notes |
|-------|--------|------|-------|
| built | ✅ | 2026-07-27 | Mock-only tests (12); SDK lazy-imported, no network in suite |
| wired | ✅ | 2026-07-27 | Fallback tier in `WorkerManager._create_isolated_worker`; registry type `e2b-sandbox` |
| adopted | ❌ | — | Needs `E2B_API_KEY` + `uv sync --group sandbox` + live smoke test |

## What it is

`mahavishnu/workers/e2b_sandbox.py` — `E2BSandboxWorker`, a `BaseWorker`
executing tasks in hosted E2B Firecracker sandboxes (~150ms create,
~$0.05/vCPU-hr). Serves two roles:

1. **Fallback tier** when the local Apple `container` runtime is
   unsupported (Intel Macs, Linux hosts) — reached automatically via
   `AppleContainerUnsupported` in `_create_isolated_worker`.
1. **Explicit tier** via worker type `e2b-sandbox` (skips the Apple tier).

Shares `workers/_exec_guard.py` command validation with
`AppleContainerWorker`. The Docker/OrbStack `ContainerWorker` was removed
in the same change (2026-07-27); `container` / `container-executor`
worker types remain as auto-tier aliases.

## Integration Contract

- **Triggered from:** `WorkerManager._create_isolated_worker` (CONTAINER
  category) — auto-tier fallback or explicit `e2b-sandbox` type.
- **Returns to / updates:** `WorkerResult` to callers; Session-Buddy
  `store_memory` when a client is configured.
- **Demonstrable by:** `pytest tests/unit/workers/test_e2b_sandbox.py`;
  live: export `E2B_API_KEY`, `uv sync --group sandbox`, spawn an
  `e2b-sandbox` worker and execute `{"command": "echo hello"}`.
- **Rollback signal:** `RuntimeError` at `start()` when the SDK is
  missing or sandbox creation fails (fail-loud; no silent local fallback,
  per degraded-mode policy).
- **Observability added:** structured logs on start/stop/exec transport
  errors; `runtime: "e2b"` tag in `WorkerResult.metadata`.

## Open work before "adopted"

- [ ] `uv sync --group sandbox` in dev environments (group added to
  `pyproject.toml` dev includes) and `E2B_API_KEY` provisioning.
- [ ] Live smoke test: verify `AsyncSandbox.create(template=, timeout=)`
  kwargs and `CommandExitException` attribute names against the installed
  SDK version (worker parses them defensively via getattr).
- [ ] Degraded-mode surfacing: decide operator-facing signal when the E2B
  tier is unreachable from a host that also lacks the Apple tier
  (currently a raised RuntimeError with install/start context).
- [ ] Custom template: a `mahavishnu-base` E2B template with python/git
  preinstalled to cut per-task setup.

## References

- E2B docs: <https://e2b.dev/docs> (SDK: `e2b`, env `E2B_API_KEY`)
- Companion: `docs/feature-tracking/apple-container-worker.md` (tier 1)
- Research session 2026-07-26: microVM isolation tiers.
