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
**Last updated:** 2026-09-07
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
- [x] Observability hook in place — structured logs (`pool.pi.spawned`, `pool.pi.subprocess_died`, `pool.pi.task.failed`) **and** OTel counters `mahavishnu.pi.tasks.executed{status}`, `mahavishnu.pi.task.duration`, `mahavishnu.pi.heartbeat.missed_total` (emitted via `mahavishnu.pools.pi_observability`; lazy `@cache`-d instruments so the test fixture can swap MeterProviders). C1 follow-up closed 2026-09-08.
- [x] Rollback signal defined

## Built (yes/no)

\<yes — `mahavishnu/pools/pi_pool.py`, `mahavishnu/core/json_rpc_stdio.py`, and the new `PiPoolSettings` are merged on the main branch.>

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
real `npx @earendil-works/pi-coding-agent --rpc` task to complete
end-to-end against the actual subprocess. That smoke lives outside the
unit-test harness (requires `npx` and Node.js on the operator host) and
is captured in the plan's Phase 5 integration test as opt-in.

## Next action

- Run the manual smoke (above) on a host with `npx` available; confirm
  `mahavishnu.pi.tasks.executed{status="completed"}` counter increments.
- Promote to `adopted` once one real task completes end-to-end and at
  least one production user/workflow/agent has dispatched through it.

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
