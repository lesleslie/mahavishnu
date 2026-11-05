---
name: yaml-backed-model-routing
status: wired
date: 2026-11-05
last_reviewed: 2026-11-05
owner: mahavishnu core
role: canonical
---

# Feature: yaml-backed-model-routing

**Owner:** mahavishnu core
**Created:** 2026-11-05
**Last updated:** 2026-11-05
**Repo(s):** /Users/les/Projects/mahavishnu

## Decision

- **2026-11-05:** option (a) of the three-way decision recorded in jot
  `4abc180f…` — the operator config becomes the source of truth for
  task-to-model routing, the in-code tables become the built-in fallback,
  and the drift-equality guard is replaced by a coverage guard. Shipped in
  `9c2f11b1`; plan `docs/plans/2026-11-05-yaml-backed-model-routing.md`.

## State — pick one

- [ ] **built** (code merged, no callers wired)
- [x] **wired** (entry-point exists; integration contract executed end-to-end)
- [ ] **adopted** (in active use by ≥1 user/workflow/agent)

Adoption is not yet claimed: the config was inert until this change, so no
operator has edited it yet. The state moves to `adopted` when an operator
changes a `task_routing` entry in a deployment and the change is observed
in production routing.

## Wiring checklist

- [x] Entry point registered (CLI command / MCP tool / FastAPI route / handler)
- [x] Trigger path identified (who calls this, and from where)
- [x] Returns / state updates land in expected destination
- [x] End-to-end smoke check documented (one command that proves it works)
- [x] Observability hook in place (log/metric/trace)
- [x] Rollback signal defined

## Built (yes/no)

yes — `9c2f11b1`.

## Wired (yes/no)

yes.

- **Entry points**: `mahavishnu/workers/cloud_worker.py` —
  `CloudWorkerConfig.get_model_for_category` and
  `_build_fallback_chain`, reached by the `mahavishnu pool route` CLI and
  the `pool_route_execute` MCP tool.
- **Trigger path**: every LLM dispatch resolves its category-to-model map
  through `resolve_minimax_routing()` / `resolve_llama_server_routing()` /
  `resolve_runpod_public_routing()` in
  `mahavishnu/core/model_routing.py`.
- **State destination**: the `task_routing` map handed to
  `mcp_common.llm.FallbackChain` — the chain that dispatches every LLM
  call.
- **End-to-end check**: edit `settings/models.yaml`
  (`minimax.task_routing.CODE_GENERATION`), then
  `mahavishnu pool route -p "write a function"` — the reported model id
  changes with no restart and no redeploy. Executed 2026-11-05: the
  resolved model moved to the edited id and back when the file was
  restored. **Caveat, found 2026-11-05 after the fact**: the *loader*
  re-parses the file on change, so every live read sees the edit — but a
  cloud worker snapshots the routing into its provider chain when it
  starts (`cloud_worker.py:161`), and `mcp_common/llm/provider.py:75`
  reads that snapshot, never the file. A worker that is already running
  therefore keeps the pre-edit routing until it restarts. The check above
  exercises the resolver, not a running worker's chain.
- **Observability**: `Model routing: loaded N provider table(s) from <path>`
  at INFO on load; `Could not read model routing config <path>: <reason>`
  at WARNING on a broken config;
  `<ENV>=<path> does not name a readable file; using built-in model routing`
  at WARNING on a bad override.
- **Rollback signal**: a `TestRoutingCoverage` failure naming the uncovered
  `TaskCategory`, or the WARNING log lines above — both mean the operator
  config is not describing the system.

## Notes

- The operator config was **inert** before this change: nothing in the
  fleet parsed it. Its only live consumer was the CI guard that asserted
  it agreed with the in-code tables.
- That guard only checked the YAML-to-code direction, so it never noticed
  the YAML was missing `EMBEDDING` (minimax) and `CREATIVE`, `EMBEDDING`,
  `VISION` (llama_server). Four categories would have lost their route the
  moment the file became authoritative. They are added, and the new guard
  requires the config to name every category.
- `MAHAVISHNU_MODELS_PATH` points the loader at a non-default file. The
  file is deliberately **not** shipped in the wheel — a packaged copy would
  be a second file free to drift from the repo one.
