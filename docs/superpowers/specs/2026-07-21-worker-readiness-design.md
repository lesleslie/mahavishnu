# Worker Readiness Repair — Design

**Date:** 2026-07-21
**Owner:** Mahavishnu control plane
**Status:** Approved for implementation planning

## Context

The `mahavishnu workers` surface is the CLI entry point for spawning, listing, and
executing against the worker catalog. A 12-session demo and a read-only root-cause
investigation across the registry, lifecycle, security, tests, and operations layers
surfaced structural defects that make workers unreliable in any environment without
real credentials, services, or a non-mock terminal adapter.

Confirmed in-code defects:

- `WORKER_REGISTRY` is a static literal with no per-environment gating; `validate_worker_dependencies()`
  is binary on `shutil.which(requires_tool)` and reports `True` for every MCP/Container/Gateway
  worker regardless of configuration. (`mahavishnu/workers/registry.py:62, 641-655`)
- The CLI global worker gate is mis-wired: it reads nonexistent `config.workers_enabled`
  instead of the nested `config.workers.enabled`. (`mahavishnu/_main_cli.py:1316, 1399`)
- `spawn_workers()` calls `worker.start()` without forwarding `task_spec`, so any worker
  whose registry command contains `{prompt}` (`terminal-codex`, `terminal-openclaw`,
  `terminal-deepagents`, `terminal-clai`) raises `ValueError` at startup.
  (`mahavishnu/workers/manager.py:79-112`, `mahavishnu/workers/generic_shell.py:102-117`)
- The factory only matches the hard-coded name `gateway-openclaw`; other GATEWAY workers
  (`openhands`, `a2a`) and `terminal-crow` (AI_ASSISTANT with `command=""`) raise at
  construction. (`mahavishnu/workers/manager.py:179-217`,
  `mahavishnu/workers/generic_shell.py:86-96`)
- `OpenClawGatewayWorker.execute()` auto-restarts on any non-`RUNNING` status; a permanent
  gateway outage risks an infinite restart loop. (`mahavishnu/workers/openclaw_gateway.py:153-154`)
- `ContainerWorker.start()` flips to `RUNNING` after a 1-second sleep, not a real readiness
  probe. (`mahavishnu/workers/container.py:194-204`)
- `CloudWorker.start()` becomes `RUNNING` even when the only auth-required provider is dropped
  because the credential is missing. (`mahavishnu/workers/cloud_worker.py:76-155`)
- Readiness endpoints never inspect credentials or external service availability.
  (`mahavishnu/core/health.py:592-659`, `mahavishnu/health.py:152-169`)

Confirmed environmental blockers (not code defects):

- OrbStack socket is not auto-discovered; `DOCKER_HOST` is ignored. (`mahavishnu/workers/container.py:35-105`)
- `OPENCLAW_GATEWAY_URL` is presence-checked only; an unreachable URL is only discovered at
  worker start. (`mahavishnu/workers/registry.py:554-612`)
- 13 declared `mcp_server` values in the registry do not resolve to configured MCP servers
  in `.mcp.json`.

## Goals

- Show workers only when they can actually run; never route a job into a known-broken
  backend.
- Distinguish "registered" from "configured" from "ready" from "available" in CLI, pool
  routing, MCP tools, and health.
- Make credential validation provider-aware, with safe diagnostics (requirement names
  only, never secret values).
- Repair the worker lifecycle so that one-shot and interactive workers both have a
  first-class execution path.
- Maintain compatibility: keep `validate_worker_dependencies()` working; keep existing
  worker type names; keep the global `workers.enabled` switch.

## Non-goals

- Migrating `WORKER_REGISTRY` to YAML/JSON.
- Splitting one-shot workers into new type names (`terminal-codex-shot`, etc.).
- Centralizing every subsystem cache/TTL.
- Replacing the existing pool, health, or WebSocket contracts.

## Architecture

A focused capability layer wraps the existing typed registry and the existing
`WorkerManager`; the contracts of pool, health, and WebSocket stay unchanged and consume
the new reports.

### New module: `mahavishnu/workers/capabilities.py`

Owns the state machine, probes, and reporting. Public surface:

- `WorkerCapabilityState` enum: `REGISTERED`, `CONFIGURED`, `READY`, `AVAILABLE`.
- `WorkerCheck` dataclass: `kind`, `status`, `safe_reason`, `duration_ms`, `cached`,
  `checked_at`.
- `WorkerCapabilityReport` dataclass: `worker_type`, `state`, `checks: list[WorkerCheck]`,
  `missing_requirements: list[str]`, `probe_at`, `cache_ttl_s`.
- `evaluate_worker_capabilities(worker_type, *, settings, force_live=False) -> WorkerCapabilityReport`.
- `evaluate_all_capabilities(*, settings, force_live=False) -> dict[str, WorkerCapabilityReport]`.
- `select_routable_workers(candidates=None, *, settings, require_available=False) -> list[str]`.

Static checks are pure functions; live checks live in `_probes/` as `async def` and
return a tri-state result. Probe results are cached for a short TTL (default 30s) and
invalidated on failed startup or successful credential refresh.

### Registry metadata additions

`WorkerConfig` gains typed requirement fields. None of these store credential values;
they store names and kinds only.

- `required_env: list[str]` — required environment variable names.
- `required_settings: list[str]` — dotted settings paths that must be truthy.
- `auth_kind: AuthKind` — `NONE | API_KEY | CLI_SUBSCRIPTION | MCP_CREDENTIAL | BEARER_TOKEN | OAUTH`; the value drives which probe is run.
- `runtime_kind: RuntimeKind` — `NONE | SHELL | DOCKER | PODMAN | ORBSTACK`; for container
  workers, drives runtime discovery.
- `mcp_server: str | None` (already present) is now validated against
  `MahavishnuSettings.mcp_servers` at evaluation time.
- `endpoint: EndpointRef | None` — `URL` or `socket_path` for gateway/runtime workers.
- `one_shot: bool` — defaults to `False`; sets the lifecycle contract (see below).

### Lifecycle separation

`WorkerManager` exposes two paths instead of conflating them:

- `spawn_workers(worker_type, count, *, runtime_kwargs=...)` — interactive workers.
  Validates capability first; refuses with a typed `WorkerUnavailableError` when not
  `READY`. Per-worker `start()` continues to use a session-keep-alive command template
  (no prompt).
- `submit_workers(worker_type, prompts: list[str], *, runtime_kwargs=...)` — one-shot
  workers. For each prompt, formats the command template, validates capability, and
  starts the worker with the formatted command, then waits for completion. Spawn failures
  roll back so no workers are left in `STARTING`.

A unified `execute(worker_id, task)` continues to work for callers that already have a
worker id; lifecycle contracts do not change for runtime code that does not import the
new APIs.

### Factory dispatch

`_create_worker` switches on `WorkerCategory` first, then on `worker_type` for
category-internal specialization. This removes the dead `ValueError("Unknown gateway worker type")` branch and wires the missing dedicated classes for `openhands`, `a2a`,
and `terminal-crow`.

### Capability integration points

- `WorkerManager._create_worker` and `WorkerManager.spawn_workers` consult
  `evaluate_worker_capabilities` and short-circuit before `worker.start()`.
- `resolve_worker_type` becomes a pure intent-routing helper. It no longer infers
  gateway availability from environment-variable presence.
- `mahavishnu workers list-types` adds `--ready` and `--explain` flags.
- `/ready`, `mahavishnu health --ready`, and the MCP `get_readiness` tool consume
  `evaluate_all_capabilities()` to compose the worker-component status.
- Pool routing and `WorkerOrchestratorAdapter.execute` use
  `select_routable_workers()` instead of consulting the registry directly.
- Capability state changes broadcast on the existing `adapter.health_changed` channel
  and emit a new `worker.availability_changed` event that includes the safe reason.

### Health semantics

- Optional workers (not the default) failing the capability check make the worker
  catalog `degraded`. They never make overall Mahavishnu readiness `unhealthy`.
- The default worker class failing the capability check makes overall Mahavishnu
  readiness `degraded` rather than `unhealthy`; readiness only goes `unhealthy` when
  no worker is routable for the default type.
- Health aggregation precedence stays UNHEALTHY > DEGRADED > OK.

### Secret hygiene

- Capability reports carry only requirement names and short reason codes.
- Exception detail payloads and `WorkerResult.error` strings are filtered through a
  `safe_error_for_user()` helper that strips key values, tokens, and `Authorization`
  headers before returning or logging.
- `caplog` regression tests assert that no log record contains a literal key value for
  any auth-skip path.

## Capability states

| State | Definition | Gate | Probe |
|---|---|---|---|
| REGISTERED | Declared in `WORKER_REGISTRY` | Literal lookup | None |
| CONFIGURED | Settings permit the type; required env names listed | Settings load | None |
| READY | Static prerequisites satisfied (binary, env presence, settings values, MCP registration, runtime/socket present) | `evaluate_worker_capabilities` (static phase) | `shutil.which`, env presence, settings, MCP catalog |
| AVAILABLE | Live provider/runtime probe succeeded | `evaluate_worker_capabilities` (live phase) | Provider auth, OpenClaw `/health`, Docker/OrbStack daemon ping, MCP endpoint reachability |

A worker can be CONFIGURED but not READY because a binary is missing. A worker can be
READY but not AVAILABLE because the provider rejects credentials or the daemon is
unreachable. Routing uses only READY (lazy) or AVAILABLE (immediate) workers.

## Data flow

1. CLI / pool / MCP / health calls the capability layer.
1. Capability layer runs static checks (fast) and, if requested, live probes (async,
   cached).
1. Result is a `WorkerCapabilityReport` per worker.
1. Consumer chooses:
   - Routing: `select_routable_workers(require_available=True/False)`.
   - CLI: render table/list with `--explain` detail.
   - Health: aggregate component status using existing precedence.
   - Metrics: increment capability counters; emit reason-code labels.
1. `WorkerManager.spawn_workers` / `submit_workers` consult the report; they never
   bypass it.
1. Lifecycle events fan out via the existing WebSocket and metrics surfaces.

## Provider authentication

- `API_KEY`: probe reads the env name, validates non-empty, and (for the live probe)
  performs a provider-specific lightweight request. Examples: `claude`, `qwen`,
  `minimax`, `openai`, `anthropic`.
- `CLI_SUBSCRIPTION`: probe checks executable and (where supported) runs a
  `--version`-style non-interactive command; never invokes a real task.
- `MCP_CREDENTIAL`: probe validates against the MCP server's `auth_methods` config.
- `BEARER_TOKEN` / `OAUTH`: probe sends a `/health`-style request with the token
  injected; never logs the value.
- `NONE`: static checks only; live probe is skipped.

The provider probe functions live in `mahavishnu/workers/capabilities/_probes/`. New
providers are added by registering a probe function; the registry wires the function
based on `auth_kind`.

## Container runtime detection

Order of precedence for `RuntimeKind.DOCKER | PODMAN | ORBSTACK`:

1. Explicit override from `settings.mahavishnu.yaml:workers.container.runtime` and
   `socket_path` (e.g., `unix:///Users/les/.orbstack/docker/docker.sock`).
1. OrbStack socket presence at the documented path (only on darwin).
1. `DOCKER_HOST` environment variable.
1. `docker` / `podman` on `PATH`; first match wins.
1. Daemon ping (`docker info` or equivalent) before promoting to READY.

The probe result is cached briefly; failures fall through to the next candidate.

## OpenClaw dual-mode gating

- `terminal-openclaw` is gated by the local `openclaw` executable and a non-interactive
  auth/version probe. It does not require `OPENCLAW_GATEWAY_URL`.
- `gateway-openclaw` is gated by a configured `OPENCLAW_GATEWAY_URL` (or
  `MAHAVISHNU_OPENCLAW_GATEWAY_URL`), optional token policy, and a successful
  `/health` request. A malformed or missing `healthy` field in the response is
  treated as failure.
- The two types are routed independently. There is no automatic swap; the caller
  chooses.
- `resolve_worker_type()` no longer uses environment-variable presence to infer
  gateway availability. It only chooses between user-explicit intent options.

## CLI changes

- `mahavishnu workers list-types` gains:
  - `--ready`: only routable types.
  - `--all`: all registered types.
  - `--explain`: show requirement names and short reason codes.
  - `--probe`: force a live probe (still cached).
- `mahavishnu workers submit --type <one-shot-type> --prompt <text>` is added; it
  invokes `submit_workers` directly.
- `mahavishnu workers execute` continues to work for callers that already pass a
  prompt via `--prompt`. It now distinguishes the one-shot path internally.
- `mahavishnu workers spawn` continues to be interactive; its capability gate runs
  before launching each session.

## MCP / pool / health changes

- `mcp__mahavishnu__discover_tools` adds a `capability` filter so callers can list
  only the tools backed by routable workers.
- `mcp__mahavishnu__pool_route_execute` and `dispatch_to_pool` consume
  `select_routable_workers` and fall back with a structured `fallback_used` reason.
- `mcp__mahavishnu__get_health` and `/ready` aggregate the worker-component status.
- WebSocket events on `worker.availability_changed` carry `worker_type`, `state`,
  and `safe_reason`.

## Error handling

- `WorkerUnavailableError` is a new exception in `mahavishnu/core/errors.py` with
  `details` carrying `worker_type`, `state`, and `missing_requirements` (names only).
- All capability-check failures surface this error, not a generic `ValueError`.
- `WorkerResult.error` and stdout for failed spawns are sanitized via
  `safe_error_for_user()`.

## Observability

New metrics (extend existing surface, do not add a new registry):

- `mahavishnu_worker_capability_transitions_total{worker_type,from_state,to_state}`
- `mahavishnu_worker_capability_probe_duration_seconds{worker_type,check_kind,result}`
- `mahavishnu_worker_capability_cache_total{worker_type,result}` (hit/miss)

New structured log markers:

- `worker_capability_transition` with safe fields only.
- `worker_capability_probe_failed` with `check_kind` and `safe_reason`.
- Existing `circuit_breaker_*` markers continue to work.

New WebSocket event:

- `worker.availability_changed`: `{worker_type, state, safe_reason, probe_at}` on the
  existing `adapters` room.

## Testing

### Unit

- Registry metadata and state transitions.
- Required environment / settings checks.
- Provider-specific credential validation with fake probes.
- Secret redaction in reports, exceptions, logs, metrics.
- OpenClaw gateway success, refusal, malformed health, token propagation.
- Docker/OrbStack runtime discovery and daemon ping.
- MCP server registration and reachability.
- CLI/subscription auth probe behavior.
- One-shot prompt construction and interactive session startup.
- Category-based factory dispatch for gateway/application/container workers.
- Partial spawn rollback and guaranteed cleanup.
- Failure durations and terminal worker states (no zero-duration histogram noise).
- Global `workers.enabled` setting actually disables the CLI commands.
- `validate_worker_dependencies` compatibility wrapper still returns flat bool dict.

### Integration

- A fake OpenClaw HTTP server returns healthy/unhealthy responses.
- A fake Docker-compatible runtime validates daemon detection and container readiness.
- A fake terminal adapter executes two concurrent sessions and returns `PONG`.
- A fake MCP client validates application worker routing.
- Pool routing skips blocked workers and reports fallback decisions.

Network- and runtime-dependent tests use existing `requires_network`, `requires_auth`,
and `slow` markers; the default unit suite remains deterministic.

### Quality gates

- All new tests run under the standard pytest invocation.
- `python scripts/audit_orphans.py` reports no new symbols with zero callers.
- `crackerjack run` continues to pass.
- Coverage floor (80%) is preserved.

## Rollout order

1. Fix global `workers.enabled` wiring and add the regression test.
1. Split interactive spawn and one-shot submit paths; add the regression test.
1. Switch factory dispatch to `WorkerCategory`; add dedicated classes for the missing
   gateway/application workers.
1. Add registry capability metadata and `evaluate_worker_capabilities` (static phase).
1. Add live probes (auth, gateway, MCP, Docker/OrbStack).
1. Wire routing, CLI diagnostics, and health/readiness.
1. Run the worker matrix demo in an environment with valid credentials and services.
1. Run `scripts/audit_orphans.py` and the project quality gates.

## Integration contract

- **Triggered from:** CLI worker commands, pool routing, MCP worker tools, and
  readiness checks.
- **Returns to / updates:** worker candidate selection, structured failure results,
  health status, metrics, and WebSocket events.
- **Demonstrable by:** two concurrent `PONG` sessions for each routable worker class,
  plus diagnostic output for blocked classes.
- **Rollback signal:** any worker is routed while `READY=False`, a secret appears in
  output, or a failed probe leaves a worker registered as `RUNNING`.
- **Observability added:** capability state, probe reason, duration, cache status,
  routing fallback.

## Open questions

1. Should the public API expose a third symbol such as
   `list_routable_workers_with_reasons()` for UIs that need richer output than
   `select_routable_workers`?
1. Should the capability layer cache the `READY` state in the registry process even
   after a `start()` failure, or invalidate immediately? Default is immediate
   invalidation; we can revisit if probe storms appear.
1. Should `terminal-ssh` count as a "remote" worker in capability gating the same way
   OpenClaw does, or as a remote worker with a separate "ssh" probe? Default is
   separate remote probe; revisited if the SSH probe proves too expensive.
