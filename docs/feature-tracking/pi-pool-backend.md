---
name: pi-pool-backend
status: wired
date: 2026-09-07
last_reviewed: 2026-09-08
owner: Core Eng
role: canonical
---

# Feature: pi-pool-backend

**Owner:** Core Eng
**Created:** 2026-09-07
**Last updated:** 2026-10-19
**Repo(s):** /Users/les/Projects/mahavishnu

## State — pick one

- [ ] **built** (code merged, no callers wired)
- [x] **wired** (entry-point exists; integration contract executed end-to-end)
- [ ] **adopted** (in active use by ≥1 user/workflow/agent)

## Wiring checklist

- [x] Entry point registered (CLI command / MCP tool / FastAPI route / handler)
- [x] Trigger path identified (who calls this, and from where)
- [x] Returns / state updates land in expected destination
- [x] End-to-end smoke check documented (one command that proves it works)
- [x] Observability hook in place — structured logs (`pool.pi.spawned`, `pool.pi.task.failed`, `pool.pi.task_timeout`, `pool.pi.task_unavailable`) **and** OTel counters `mahavishnu.pi.tasks.executed{status}`, `mahavishnu.pi.task.duration`, `mahavishnu.pi.heartbeat.missed_total` (emitted via `mahavishnu.pools.pi_observability`; lazy `@cache`-d instruments so the test fixture can swap MeterProviders).
- [x] Rollback signal defined

## Built (yes/no)

\<yes — `mahavishnu/pools/pi_pool.py` (per-task spawner against
`@earendil-works/pi-coding-agent` v1.3.0+ CLI) and `PiPoolSettings`
are merged on the main branch. The legacy
`mahavishnu/core/json_rpc_stdio.py` and
`mahavishnu/core/json_rpc_ipc.py` modules were removed when the
pool switched from a persistent JSON-RPC subprocess to one-shot
CLI invocations.>

## Wired (yes/no)

\<yes — `register_pool_type("pi", _build_pi_pool)` is called at module
import; `PoolManager.spawn_pool("pi", config)` resolves via the D0 registry;
`list_pool_types()` returns `('mahavishnu', 'pi', 'runpod', 'session-buddy')`.>

## Trigger path

- `mahavishnu.pools._registry.register_pool_type("pi", _build_pi_pool)`
  fires on `import mahavishnu.pools.pi_pool` (also surfaced by
  `mahavishnu.pools._load_all_pool_types()` and
  `mahavishnu.pools._registry._ensure_pool_registry_loaded()`).
- `PoolManager.spawn_pool("pi", config)` (in `mahavishnu/pools/manager.py`)
  looks up the factory via `get_pool_factory("pi")` and calls
  `_build_pi_pool(config=config)` which constructs a `PiPool(config)`.
- Operator CLI: `mahavishnu pool spawn --type pi --name <name>` followed
  by `mahavishnu pool execute <pool_id> --prompt "..."` (existing CLI
  surface; no new CLI subcommands added).

## Integration point

- `mahavishnu.pools._registry._POOL_FACTORIES["pi"]` — registry entry
  consumed by `PoolManager.spawn_pool`.
- `mahavishnu.core.config.MahavishnuSettings.pi_pool` — config singleton
  loaded by Oneiric from `settings/mahavishnu.yaml` and
  `MAHAVISHNU_PI_POOL__*` env vars.
- `mahavishnu.mcp.tools.pool_tools.py` — `pool_list`, `pool_health`,
  `pool_monitor` MCP tools now expose the new pool type via
  `list_pool_types()` (registry-driven; no MCP-tool edit required).

## End-to-end check

```bash
# Unit tests prove the wiring contract:
uv run pytest tests/unit/pools/test_pi_pool.py \
                tests/unit/test_pi_pool_env_stripping.py \
                tests/unit/test_pi_pool_npx_allowlist.py \
                -v --no-cov

# Registry self-registration:
uv run python -c \
  "from mahavishnu.pools._registry import list_pool_types; \
   types = list_pool_types(); \
   assert 'pi' in types, types; \
   print('OK', types)"

# Manual smoke (operator run, not CI):
mahavishnu pool spawn --type pi --name pi-smoke
mahavishnu pool execute pi_<id> --prompt "hello"
mahavishnu pool list | grep pi
mahavishnu pool health pi_<id>
```

If any of the above fails, the wiring does not exist.

## Blocker

None — feature is wired. Promotion to "adopted" requires at least one
real `npx @earendil-works/pi-coding-agent` task to complete
end-to-end against the actual CLI. That smoke lives outside the
unit-test harness (requires `npx` and Node.js on the operator host) and
is captured in the plan's Phase 5 integration test as opt-in.

## Operator setup (2026-10-19 update)

The pool's per-task subprocess inherits the operator's LLM
credentials via the PiPool ``env_allowlist`` (see
`mahavishnu/pools/pi_pool.py`). The default allowlist includes
the four standard LLM credential env vars; the operator opts in
by setting them in their shell. The `mahavishnu demo pool-pi`
precondition check (`_check_pool_pi_preconditions` in
`mahavishnu/cli/demo_cli.py`) fails fast with a clear hint if no
LLM cred is set, so the agent returns the upstream's auth error
inline instead of a silent empty result.

**Minimum (any provider):**

```bash
export OPENAI_API_KEY=...      # any OpenAI-compatible key
# OR
export ANTHROPIC_API_KEY=...   # for Anthropic
```

**To route through the local Bifrost gateway** (the post-Phase-8
canonical upstream — see `docs/llm-routing.md`):

```bash
export ONEIRIC_BIFROST_ENABLED=true
export ONEIRIC_BIFROST_ROUTES=qwen_route   # OPENAI maps to QWEN_ROUTE
export ONEIRIC_BIFROST_BASE_URL=http://127.0.0.1:8471/v1
export OPENAI_API_KEY=...                 # any non-empty key (Bifrost may accept/drop)
export OPENAI_BASE_URL=http://127.0.0.1:8471/v1   # what the pi-coding-agent actually calls
```

The `OPENAI_BASE_URL` and `ONEIRIC_BIFROST_BASE_URL` both point at
the same gateway URL; the first is what the pi-coding-agent reads,
the second is what oneiric's `BifrostLLMRouter` reads. They stay
in sync by convention (the oneiric 0.32.1 default is
`http://127.0.0.1:8471/v1`).

## Agent version (2026-10-19 update)

The pool is pinned to `@earendil-works/pi-coding-agent` v1.3.0+
which removed the legacy `--rpc` flag. The pool is now a per-task
spawner: every `execute_task` runs one `npx ... pi <prompt>`
invocation and reaps. There is no persistent subprocess, no
JSON-RPC transport, and no Content-Length framing.

To pin a specific version, set the env var override:

```bash
export MAHAVISHNU_PI_POOL__NPX_COMMAND=npx,-y,@earendil-works/pi-coding-agent@1.3.0
```

## Next action

- Run the manual smoke (above) on a host with `npx` available **and**
  one of the LLM credential env vars exported; confirm
  `mahavishnu.pi.tasks.executed{status="completed"}` counter increments.
- Promote to `adopted` once one real task completes end-to-end and at
  least one production user/workflow/agent has dispatched through it.

## Per-task spawner design (2026-10-19 update)

The pool is implemented as a per-task spawner against
`@earendil-works/pi-coding-agent@1.3.0`:

- `PiPool.start()` runs a single `npx ... --version` probe to populate
  the health-check `version` field. Failure is best-effort; the pool
  still serves tasks.
- `PiPool.execute_task(task)` builds argv
  `(*npx_command, --provider X?, --model Y?, <prompt>)` and runs one
  `asyncio.create_subprocess_exec` invocation. The default 30s
  per-task timeout fires `asyncio.TimeoutError` → `PiRPCTimeout`
  → counter `mahavishnu.pi.heartbeat.missed_total` (retained under
  the legacy name for dashboard continuity).
- `PiPool.stop()` is a no-op (no subprocess to reap). Out-of-band
  tasks complete independently.
- Test seam: `subprocess_runner: SubprocessRunner | None` — defaults
  to `_default_subprocess_runner` (real `create_subprocess_exec`),
  tests inject an in-memory coroutine that returns a canned
  `(returncode, stdout, stderr)` triple.

Removed as dead code:

- `mahavishnu/core/json_rpc_stdio.py` (the persistent-subprocess
  Content-Length client; ~735 lines)
- `mahavishnu/core/json_rpc_ipc.py` (the Unix-socket JSON-RPC server
  only used by the deleted client; ~480 lines)
- `tests/unit/test_json_rpc_ipc.py` and
  `tests/unit/core/test_json_rpc_stdio.py` (tests for the deleted
  modules; the security-boundary tests moved to
  `tests/unit/test_pi_pool_env_stripping.py` and import
  `_FORBIDDEN_ENV_PREFIXES` from its new home in
  `mahavishnu.pools.pi_pool`).

## Related

- Plan: docs/plans/2026-09-07-pi-pool-backend.md
- Parent plan: /Users/les/.claude/plans/adaptive-hugging-mist.md
- Integration contract: docs/plans/2026-09-07-pi-pool-backend.md §5
  Phases 2-5 (one Integration Contract per phase)
- Audit evidence:
  - `python scripts/audit_requirements.py --json` → 0 orphans, 0 phantoms
  - `python scripts/audit_orphans.py` → unchanged from prior to D1

## How to save to Session-Buddy

After completing this file, persist a one-line summary to Session-Buddy
for cross-session retrieval by calling the Session-Buddy MCP tool
`store_reflection` with the following shape:

```python
mcp__session-buddy__store_reflection(
    content=(
        "Feature pi-pool-backend: state=wired, "
        "built=yes, wired=yes, "
        "blocker=none, "
        "next=manual smoke via `mahavishnu pool spawn --type pi` + "
        "`mahavishnu pool execute <id> --prompt hello`"
    ),
    tags=["feature-tracking", "pi-pool-backend", "wire-up-state"],
)
```

That call returns a reflection ID; paste that ID into the section below
so the long-form record and the searchable reflection stay linked.

## Session-Buddy

- Reflection ID: \<to be filled in after `store_reflection` call>
- Saved at: \<ISO timestamp from the call's response>
