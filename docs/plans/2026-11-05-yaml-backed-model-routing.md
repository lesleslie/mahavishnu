---
status: shipped
role: implementation
kind: plan
date: 2026-11-05
last_reviewed: 2026-11-05
superseded_by: null
topic: yaml-backed-model-routing
title: "Make settings/models.yaml the live source of task-to-model routing"
requirements:
- id: REQ-YAML-001
  title: Operator config is authoritative for task routing when present
- id: REQ-YAML-002
  title: No TaskCategory loses its route when the operator config omits it
- id: REQ-YAML-003
  title: Absent, unreadable, or malformed operator config degrades to the built-in table and says so
- id: REQ-YAML-004
  title: The operator can point the loader at a non-default file
- id: REQ-YAML-005
  title: A CI guard requires the operator config to cover every TaskCategory
- id: REQ-YAML-006
  title: The built-in table is the only fallback and no second copy of the config ships
- id: REQ-YAML-007
  title: No unread config key implies a live knob
- id: REQ-YAML-008
  title: Documentation states which source is authoritative
---

# Make `settings/models.yaml` the live source of task-to-model routing

> **Status: draft.** Option (a) of the three-way decision recorded in jot
> `4abc180f…` (2026-11-02): the operator config becomes the source of truth
> for routing, the in-code tables become the fallback, and the drift-equality
> guard is replaced by a coverage guard.

## 1. Outcome

An operator edits `settings/models.yaml`, and the next dispatch routes to the
model they named — with no code change, no redeploy, and no silent fallback
to a different model.

Success signal: change `minimax.task_routing.CODE_GENERATION` to a different
model id, run `mahavishnu pool route -p "write a function"`, and observe
that model id in the resolved routing.

## 2. Goals

1. `settings/models.yaml` drives routing when present (REQ-YAML-001).
2. A category the operator omits keeps its built-in route (REQ-YAML-002).
3. A missing/broken config degrades to the built-in table, loudly
   (REQ-YAML-003).
4. The config path is overridable (REQ-YAML-004).
5. CI prevents the operator config from silently dropping a category
   (REQ-YAML-005).
6. Exactly one copy of the operator config exists (REQ-YAML-006).
7. No dead config key implies a live knob (REQ-YAML-007).
8. Every doc that describes routing says which source wins (REQ-YAML-008).

## 3. Non-Goals

1. **Not** making `settings/models.yaml` cover the whole provider registry
   (base_url, api_key, timeout). Only `task_routing` becomes live.
2. **Not** shipping `settings/` in the wheel. A packaged copy would be a
   second file that can drift from the repo one — the exact failure this
   plan removes. Installed deployments use the built-in table or point
   `MAHAVISHNU_MODELS_PATH` at their own file.
3. **Not** rewiring `default_provider`, `base_url`, or the Agno provider
   chain. Those stay on the `MahavishnuSettings` path.
4. **Not** changing `get_model_for_task` or `classify_task` semantics.
5. **Not** resolving the `settings/models.yaml` `bifrost:` block question —
   that block was already deleted by the Bifrost plan.

## 4. Current Findings

**The operator config is inert.** Audited 2026-11-02 (jot `4abc180f…`):

- No production code parses `settings/models.yaml`. Every `mahavishnu/`
  reference is a comment, a docstring, or the drift-check constant added in
  `354eef91`. The only functional touch is `core/unified_config.py:23`,
  which lists it in `_YAML_KEY_CHECKS` — a validator that checks it parses,
  skipped when the file is absent.
- `oneiric` has zero hits for `models_path` / `models.yaml`; the layered
  config loader never opens it.
- `settings/mahavishnu.yaml:21` declares `models_path: settings/models.yaml`
  and no Python reads it. `MahavishnuSettings` is `extra="allow"`, so the
  key is silently accepted and silently ignored.
- `docs/specs/2026-10-15-bifrost-gateway-wiring-design.md:41` claims the
  file is "loaded via `FallbackChain`/`model_routing`". `class FallbackChain`
  no longer exists in `mahavishnu/`; the chain moved to `mcp_common.llm` and
  is fed the in-code tables. That spec line is stale.
- `CLAUDE.md:378` tells operators that a MiniMax outage is recovered by
  setting `default_provider` back to `zai` in this file. Nothing reads that
  key, and `zai` is not in the file at all.

**The operator config is also incomplete.** Measured against the in-code
tables, 2026-11-05:

| Provider | YAML category entries | Missing from YAML | Value mismatches |
|---|---|---|---|
| `minimax` | 15/16 | `EMBEDDING` | none |
| `llama_server` | 13/16 | `CREATIVE`, `EMBEDDING`, `VISION` | none |
| `runpod_public` | 16/16 | none | none |

**The existing guard has a blind spot.** `TestYAMLRoutingSync`
(`tests/unit/test_task_router.py:282`) asserts every category *in the YAML*
matches the in-code table. It never asserts the reverse, so the four
missing entries above pass today. Making the YAML authoritative without
fixing this would silently drop routing for four categories.

**The current routing consumers** are four call sites in
`mahavishnu/workers/cloud_worker.py` (lines 83, 118, 168, 187), all of which
import the in-code tables directly.

## 4.5 Requirements

```yaml
requirements:
- id: REQ-YAML-001
  title: Operator config is authoritative for task routing when present
- id: REQ-YAML-002
  title: No TaskCategory loses its route when the operator config omits it
- id: REQ-YAML-003
  title: Absent, unreadable, or malformed operator config degrades to the built-in table and says so
- id: REQ-YAML-004
  title: The operator can point the loader at a non-default file
- id: REQ-YAML-005
  title: A CI guard requires the operator config to cover every TaskCategory
- id: REQ-YAML-006
  title: The built-in table is the only fallback and no second copy of the config ships
- id: REQ-YAML-007
  title: No unread config key implies a live knob
- id: REQ-YAML-008
  title: Documentation states which source is authoritative
```

## 5. Implementation Phases

### Phase 1: Loader and effective routing tables

**Goal:** `core/model_routing.py` gains cached resolvers that return the
effective routing table for each provider — operator config where present,
built-in table as the per-category fallback.

**Tasks:**
- Add `_models_config_path()` — `MAHAVISHNU_MODELS_PATH` override, then
  repo-root-relative `settings/models.yaml`; `None` when neither resolves.
- Add `_load_task_routing(provider)` — read one provider's `task_routing`,
  map YAML keys (`CODE_GENERATION`) onto `TaskCategory` members, skip the
  `FALLBACK` / `FALLBACK_HIGHSPEED` operator meta-keys.
- Add `resolve_minimax_routing()`,
  `resolve_llama_server_routing()`,
  `resolve_runpod_public_routing()` — `lru_cache`d, returning
  `{**built_in, **operator_config}`.
- Keep `DEFAULT_MINIMAX_ROUTING` and siblings unchanged as the built-in
  fallback.

**Exit criteria:** resolvers return a table covering every `TaskCategory`;
operator values win; missing operator values keep the built-in route.

#### Integration Contract
- **Triggered from**: `mahavishnu.workers.cloud_worker._build_fallback_chain`
  (`mahavishnu/workers/cloud_worker.py:118`) and
  `CloudWorkerConfig.get_model_for_category` (`:83`), via the llama-server
  and runpod_public chain entries (`:168`, `:187`).
- **Returns to / updates**: the `task_routing` map handed to
  `mcp_common.llm.FallbackChain` — the chain that dispatches every LLM
  call. Updates `mahavishnu/core/model_routing.py` in-process state only.
- **Demonstrable by**: `pytest tests/unit/test_model_routing_config.py -k
  operator_config_wins` plus a manual edit of
  `settings/models.yaml:CODE_GENERATION` observed in
  `mahavishnu pool route` output.
- **Rollback signal**: the log line
  `model routing: operator config unreadable, using built-in table`
  (`mahavishnu/core/model_routing.py`) at WARNING, or a
  `TestRoutingCoverage` failure naming the missing category.
- **Observability added**: one WARNING log line per load failure, naming
  the provider and the reason, from the `mahavishnu.core.model_routing`
  logger.

### Phase 2: Close the coverage gap and replace the drift guard

**Goal:** the operator config covers every category, and CI enforces it.

**Tasks:**
- Add the four missing entries to `settings/models.yaml` (`EMBEDDING` for
  `minimax`; `CREATIVE`, `EMBEDDING`, `VISION` for `llama_server`).
- Replace the drift-equality assertions in
  `tests/unit/test_task_router.py::TestYAMLRoutingSync` with a coverage
  guard: the operator config, the built-in tables, and the effective
  tables must each cover every `TaskCategory` for every provider.
- Add `tests/unit/test_model_routing_config.py` covering: operator value
  wins; omitted category keeps the built-in route; missing file → built-in;
  malformed file → built-in + warning; `MAHAVISHNU_MODELS_PATH` override;
  `FALLBACK` meta-keys ignored.

**Exit criteria:** `pytest tests/unit/test_task_router.py
tests/unit/test_model_routing_config.py` green; the coverage guard fails
when a category is removed from the operator config.

#### Integration Contract
- **Triggered from**: `pytest` — the Crackerjack gate runs the suite, which
  includes `tests/unit/test_task_router.py::TestRoutingCoverage`.
- **Returns to / updates**: `settings/models.yaml` (the four added
  entries) and the test suite's assertions.
- **Demonstrable by**: `pytest tests/unit/test_task_router.py -k
  TestRoutingCoverage -v` — passes; then delete one YAML entry and confirm
  the test fails naming that category.
- **Rollback signal**: a `TestRoutingCoverage` failure naming an uncovered
  `TaskCategory`.
- **Observability added**: the guard's failure message names the provider,
  the missing category, and the file to fix.

### Phase 3: Wire the worker and remove the dead key

**Goal:** the cloud worker resolves through the effective tables, and no
unread config key implies a live knob.

**Tasks:**
- Point the four `cloud_worker.py` call sites at the resolvers.
- Remove `models_path: settings/models.yaml` from
  `settings/mahavishnu.yaml` (REQ-YAML-007), or wire it — removal wins
  because `MAHAVISHNU_MODELS_PATH` already provides the override and the
  default path needs no configuration.
- Update `resolve_model_id` (`mahavishnu/core/model_routing.py`) to compare
  against the effective table.

**Exit criteria:** `pytest tests/unit/test_task_router.py
tests/unit/test_model_resolution.py tests/unit/workers/ -q` green; a
one-line edit to `settings/models.yaml` changes the resolved model.

#### Integration Contract
- **Triggered from**: `mahavishnu pool route` and the `pool_route_execute`
  MCP tool, both of which build a worker config and dispatch.
- **Returns to / updates**: the resolved model id in
  `mahavishnu pool route` stdout and in the `pool_route_execute` log line.
- **Demonstrable by**:
  `mahavishnu pool route -p "write a function"` prints
  `model=<id>` matching the edited `settings/models.yaml`.
- **Rollback signal**: a routing mismatch between the CLI-reported model
  and the dispatched model.
- **Observability added**: the `resolve_model_id` warning when a resolved
  id is absent from the configured routing.

### Phase 4: Documentation

**Goal:** no doc describes the operator config as inert, or claims the two
sources are "pinned in sync".

**Tasks:**
- `CLAUDE.md` — the LLM Provider Configuration section: replace "the
  in-code `DEFAULT_MINIMAX_ROUTING` and the YAML in `settings/models.yaml`
  are pinned in sync by a CI guard test" with "the YAML is authoritative
  when present; the in-code tables are the fallback".
- `docs/CONFIGURATION.md`, `docs/FILE_REFERENCE.md`, `settings/README.md`,
  `docs/architecture/MEMORY_ARCHITECTURE.md` — same correction.
- Note (do not rewrite) the stale claim in
  `docs/specs/2026-10-15-bifrost-gateway-wiring-design.md:41`; it is a
  historical spec.

**Exit criteria:** `rg "pinned in sync|sync guard" docs/ CLAUDE.md` returns
no live claim about the removed guard.

#### Integration Contract
- **Triggered from**: a reader following any routing doc.
- **Returns to / updates**: the five documentation files above.
- **Demonstrable by**: `rg -n "models.yaml" CLAUDE.md docs/CONFIGURATION.md`
  showing "authoritative when present" wording.
- **Rollback signal**: n/a — documentation-only phase.
- **Observability added**: none (documentation-only phase).

## 6. Required Code Changes

- [ ] `mahavishnu/core/model_routing.py` — loader + three resolvers
- [ ] `mahavishnu/workers/cloud_worker.py` — four call sites
- [ ] `settings/models.yaml` — four missing entries
- [ ] `settings/mahavishnu.yaml` — drop the dead `models_path` key
- [ ] `tests/unit/test_task_router.py` — replace the drift guard
- [ ] `tests/unit/test_model_routing_config.py` — new coverage
- [ ] `CLAUDE.md`, `docs/CONFIGURATION.md`, `docs/FILE_REFERENCE.md`,
      `settings/README.md`, `docs/architecture/MEMORY_ARCHITECTURE.md`

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence |
|---|---|---|
| `pytest tests/unit/test_task_router.py tests/unit/test_model_routing_config.py` | pass | pytest output |
| `pytest tests/unit/test_model_resolution.py tests/unit/workers/ -q` | pass | pytest output |
| `ruff check` + `ruff format --check` on changed files | clean | ruff output |
| `ty check` on changed files | clean | ty output |
| `python scripts/audit_requirements.py` | exit 0 | script output |
| `python scripts/audit_orphans.py` | no new orphans | script output |
| manual: edit `settings/models.yaml`, run `mahavishnu pool route -p "..."` | new model id reported | CLI output |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| An operator edits the config and one deployment (no file) keeps the old model | Medium | Document the fallback explicitly; `MAHAVISHNU_MODELS_PATH` for installed deployments |
| A malformed config breaks dispatch at runtime | Low | Loader catches parse errors, logs a WARNING, falls back to the built-in table |
| Import-time cost of reading the config | Low | Resolvers are `lru_cache`d and called lazily, not at import |
| A category is dropped because the config omits it | Medium | Per-category fallback (REQ-YAML-002) plus the coverage guard (REQ-YAML-005) |
| The YAML keys use enum names while `TaskCategory.value` is lowercase | High | Loader accepts both name and value forms |
| A peer session edits the same files concurrently | Medium | Commit with `--only`; stage the CLAUDE.md hunk via `git apply --cached` |

## 9. Decision Rule

This plan is done when: the four `cloud_worker.py` call sites resolve through
the effective tables; the coverage guard passes and demonstrably fails when a
category is removed; the four missing YAML entries are added; the dead
`models_path` key is gone; the six documentation files describe the new
precedence; and `audit_requirements.py` and `audit_orphans.py` are both
clean. If the coverage guard proves impossible to make reliable, cut to
Phase 1 + Phase 4 and ship the loader with the operator config advisory
rather than authoritative.

## 10. Completion — 2026-11-05

Shipped in `9c2f11b1` (`feat(routing): make settings/models.yaml the live
source of task routing`).

| Phase | Outcome |
|---|---|
| 1 — loader and effective tables | `_operator_routing_for` / `_operator_routing` / `resolve_*_routing()` in `core/model_routing.py`. The parse is cached per (path, change-detector), so a live read sees an operator's edit with no restart. |
| 2 — coverage gap and guard | The four missing entries added to `settings/models.yaml` (now 16/16 for every provider). `TestYAMLRoutingSync` replaced by `TestRoutingCoverage`, which requires the operator config to name every `TaskCategory` for every provider. `tests/unit/test_model_routing_config.py` adds 9 precedence and degradation tests. |
| 3 — wiring and the dead key | All four `cloud_worker.py` call sites resolve through the effective tables. `models_path` removed from `settings/mahavishnu.yaml`. |
| 4 — documentation | `CLAUDE.md`, `docs/CONFIGURATION.md`, `docs/FILE_REFERENCE.md`, `settings/README.md`, `docs/architecture/MEMORY_ARCHITECTURE.md`. The stale Bifrost-spec claim about `FallbackChain` loading the YAML is left alone — it is a historical record. |

### Deviations from the plan

1. **The operator config is deliberately not shipped in the wheel.** The plan
   listed packaging as a dependency; implementing it would have created a
   second copy of the file free to drift from the repo one — the exact
   failure this plan removes. Installed deployments use the built-in table
   or point `MAHAVISHNU_MODELS_PATH` at their own file.
2. **`reset_routing_cache()` became private and mtime-driven.** The plan
   assumed a public reset function, but a CLI reload cannot work: the cache
   lives in the *running* process, not in a new one. The loader instead
   re-parses when the file's `(st_mtime_ns, st_size)` moves, which needs no
   command at all and satisfies the plan's "pick the change up without a
   restart" goal directly.
3. **The provider chain was not moved into `models.yaml`.** The plan's
   non-goals left it alone, and the dead `default_provider` key is now
   documented as never having been read.

### Verification

- 943 tests pass across the routing, worker, pool, CLI and MCP-tool suites.
- `ruff check`, `ruff format --check` and `ty check` clean on every changed
  file.
- `audit_requirements.py`: 0 orphans, 0 phantoms. `audit_orphans.py`: none
  of the new symbols flagged.
- End-to-end: editing `settings/models.yaml` changed the resolved model with
  no restart and no cache clear; restoring the file changed it back.

### Known follow-ups

1. `docs/specs/2026-10-15-bifrost-gateway-wiring-design.md:41` still claims
   `models.yaml` is "loaded via `FallbackChain`/`model_routing`".
   `class FallbackChain` no longer exists in `mahavishnu/` — the chain moved
   to `mcp_common.llm`. Left as a historical record; worth a footnote if
   that spec is ever treated as current.
2. `docs/plans/2026-10-29-agno-llm-provider-chain.md` (status: complete)
   names `TestYAMLRoutingSync` in its validation matrix. That class is
   renamed, so the command in that matrix no longer resolves.
3. The wheel does not ship `settings/models.yaml`. A deployment that wants
   an editable registry must supply one and set `MAHAVISHNU_MODELS_PATH`.
4. **A running cloud worker keeps the pre-edit routing until it restarts.**
   Found 2026-11-05, after this plan shipped. The *loader* re-parses the
   file when it changes, so every live read sees the operator's edit — but
   `cloud_worker.py:161` stores `task_routing` as a **dict snapshot** in the
   provider config, and `mcp_common/llm/provider.py:75` reads that stored
   dict, never the file. `_build_fallback_chain` is called once, from
   `CloudWorker.start()`. So "no restart" was true of the resolver and
   false of the dispatch path for a worker that is already running.
   `CLAUDE.md`, `docs/CONFIGURATION.md`, `settings/models.yaml` and the
   `crackerjack-compliant-code` skill were corrected to say so. Making the
   chain re-read the config per call would remove the caveat, at the cost
   of a file read on every LLM call — or the chain could take a callable
   instead of a dict. Neither was done here; both are open.
