# E2B Sandbox Worker (tier-2 cloud microVM isolation)

## State

| State | Status | Date | Notes |
|-------|--------|------|-------|
| built | ✅ | 2026-07-27 | Mock-only tests (12); SDK lazy-imported, no network in suite |
| wired | ✅ | 2026-07-27 | Fallback tier in `WorkerManager._create_isolated_worker`; registry type `e2b-sandbox` |
| adopted | ⚠️ partial | 2026-07-27 | SDK installed and API shape verified against `e2b`; live sandbox run still blocked on `E2B_API_KEY` |

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

## SDK verification (2026-07-27, `uv sync --group sandbox`)

Both assumptions that were coded defensively are now **confirmed against
the installed `e2b` package** — no code changes were needed:

| Assumption | Actual SDK | Verdict |
|---|---|---|
| `AsyncSandbox.create(template=, timeout=)` | `create(template: str \| None = None, timeout: int \| None = None, ...)` | ✅ exact |
| `commands.run()` result has `exit_code` / `stdout` / `stderr` | `CommandResult(stderr, stdout, exit_code, error)` | ✅ exact |
| `CommandExitException` carries exit_code/stdout/stderr | `@dataclass class CommandExitException(SandboxException, CommandResult)` | ✅ inherits all three |
| `sandbox.kill()` | present, plus `set_timeout`, `sandbox_id` | ✅ |

Call-path proof without a key: invoking `start()` reaches the real
`AsyncSandbox.create(**create_kwargs)` and fails only at
`AuthenticationException` ("API key is required"), which the worker wraps
as `RuntimeError: E2B sandbox failed to start: ...`. A wrong kwarg shape
would have raised `TypeError` before that point.

## Open work before "adopted"

- [ ] **Live smoke test** — the one step still outstanding. Requires
  `E2B_API_KEY` in the shell (not set in the authoring environment):
  export it, then spawn an `e2b-sandbox` worker and execute
  `{"command": "echo hello"}` to confirm end-to-end sandbox creation,
  exec, and teardown against real infrastructure.
- [ ] Degraded-mode surfacing: decide operator-facing signal when the E2B
  tier is unreachable from a host that also lacks the Apple tier
  (currently a raised RuntimeError with install/start context).
- [ ] Custom template: a `mahavishnu-base` E2B template with python/git
  preinstalled to cut per-task setup.

## References

- E2B docs: <https://e2b.dev/docs> (SDK: `e2b`, env `E2B_API_KEY`)
- Companion: `docs/feature-tracking/apple-container-worker.md` (tier 1)
- Research session 2026-07-26: microVM isolation tiers.
