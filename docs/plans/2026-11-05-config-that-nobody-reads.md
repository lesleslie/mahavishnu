---
status: draft
role: implementation
kind: plan
date: 2026-11-05
last_reviewed: 2026-11-05
superseded_by: null
topic: config-that-nobody-reads
title: "Config that nobody reads — a settings/ sweep for the dead-knob pattern"
requirements:
  - id: REQ-DEAD-001
    title: "No documented config knob is inert"
  - id: REQ-DEAD-002
    title: "A YAML key and the code that implements it cannot disagree"
  - id: REQ-DEAD-003
    title: "A config file that no code loads is removed or wired"
---

# Config that nobody reads — a `settings/` sweep for the dead-knob pattern

> **Why this plan exists.** The jot recorded 2026-11-02 (`4abc180f…`) said:
> *"Both baselines independently wrote YAML-parsing machinery against
> `settings/models.yaml`, a file no production code loads. Whatever the
> ladder's final numbers, that duplication is real and recurring."*
>
> The `models.yaml` half was fixed on 2026-11-05
> (`docs/plans/2026-11-05-yaml-backed-model-routing.md`): the file is now the
> authoritative routing, loaded by `core/model_routing.py`.
>
> This document records the sweep that was never run: **does the same pattern
> recur elsewhere in `settings/`?** It does — in two whole files and nineteen
> top-level keys of a third. The audit result is §4; the proposed remediation
> is §5. **Nothing in §5 is implemented yet**; this plan is a proposal.

## 1. Outcome

No key in `settings/` describes a knob the code does not have, and no
document tells an operator that a key is live when it is not.

Success signal: a sweep of `settings/` reports zero INERT keys, and
`docs/CONFIGURATION.md` describes only keys that a reader can find a consumer
for.

## 2. Goals

1. Every key in `settings/` is READ, or is documented as inert (REQ-DEAD-001).
2. A YAML key and the code that implements it cannot disagree (REQ-DEAD-002).
3. A config file that no code loads is removed or wired (REQ-DEAD-003).

## 3. Non-Goals

1. **Not** changing any runtime behaviour in this plan. The findings below
   need per-key decisions (wire it, delete it, or document it as inert);
   those decisions are §5, and each is a separate piece of work.
2. **Not** auditing `config/` (Bifrost, Prometheus), `.mcp.json`, or the
   sibling repos' settings.
3. **Not** re-auditing `settings/models.yaml` — that file was fixed on
   2026-11-05 and is now live.

## 4. Current Findings

Audited 2026-11-05. Method: enumerate every key programmatically
(`yaml.safe_load` + `model_fields` introspection against
`mahavishnu/core/config.py`), then grep `mahavishnu/`, `scripts/`, `tests/`,
`docs/` and `config/` for the key name and for the section accessor.

**How `mahavishnu.yaml` and `local.yaml` bind** — the mechanism that makes
the dead knobs *silent*:

- `mahavishnu/core/config.py:3545-3548` merges oneiric's extras into
  `MahavishnuSettings` **only if the key is a declared field**. A top-level
  YAML key that is not a declared field is dropped before it reaches the
  settings object at all.
- `config.py:3560-3563` → `_filter_subconfig_keys()` drops unknown
  *sub*-keys of declared sections, failing soft.
- `config.py:2946-2950` — `MahavishnuSettings.model_config` is
  `extra="allow"`, so anything that does reach the constructor is accepted
  without error.

So a wrong key name produces no warning, no log line, and no test failure.
That is the whole mechanism of this failure mode.

### 4.1 Verdicts per file

| File | Git | READ | READ (test-only) | VALIDATED ONLY | INERT |
|---|---|---|---|---|---|
| `settings/embeddings.yaml` | tracked | 0 | 0 | 16 | 0 (functionally all 16 dead) |
| `settings/agno_teams/code_review.yaml` | tracked | 0 | 0 | 0 | 10 (whole file) |
| `settings/agno_teams/research.yaml` | tracked | 0 | 0 | 0 | 11 (whole file) |
| `settings/mahavishnu.yaml` | tracked | 24 (+5 partial) | 0 | 0 | 19 top-level (+7 sub-keys) |
| `settings/local.yaml` | untracked | 6 | 0 | 0 | 1 (`server_name`) |
| `settings/ecosystem.yaml` | untracked | 5 + 10/repo + 4/role | 0 | 1 | 2 + 1/repo |
| `settings/repos.yaml` | untracked | 6 (fallback only) | 0 | 2 | 1 |
| `settings/registry_metadata.yaml` | tracked | 9 (tooling) | 0 | 0 | 6 |
| `settings/registry_metadata.local.yaml` | untracked | 7 (tooling) | 0 | 0 | 5 |
| `settings/crackerjack.yaml` | tracked | 1 (cross-repo) | 0 | 0 | 0 |

The four untracked files are gitignored operator-local state. They are
audited because they are live on disk, but a finding against them is a
finding against a local copy — `settings/*.example` is the tracked stand-in.

### 4.2 Top findings, most severe first

1. **`settings/agno_teams/*.yaml` are never loaded by any production path.**
   The knob that should point at them, `agno.teams_config_path`
   (`config.py:460`, default `settings/agno_teams`), has **zero production
   readers** — only two test assertions. The loader
   `create_team_from_yaml` (`mahavishnu/engines/agno_teams/manager.py:204`)
   requires an explicit path and is exposed neither as an MCP tool nor
   through `mahavishnu team create` (`mahavishnu/cli/team_cli.py:217-290`
   has no YAML option). Production teams are built in code at
   `mahavishnu/engines/goal_team_factory.py:393`.
   `docs/CONFIGURATION.md:398` advertises the knob as "team configuration
   directory".

2. **`settings/embeddings.yaml` is never opened by any code.** The only
   reference is `mahavishnu/core/unified_config.py:24` with an **empty**
   required-key list — the file is syntax-checked and nothing more.
   `CLAUDE.md:321` and `docs/CONFIGURATION.md:109` both present it as the
   live "Embedding model configuration for content ingestion". Compounding
   it: the live `EmbeddingConfig` loader
   (`mahavishnu/core/embeddings_oneiric.py:96-99`) parses the YAML **top
   level**, so the file's nested `embeddings:` block — and the `embeddings:`
   block in `mahavishnu.yaml` — are both unreachable. Verified at runtime:
   the loader returns hardcoded defaults.

3. **`bifrost.route_qwen_code: true` does nothing.**
   `BifrostConfig` was deleted from `mahavishnu/core/config.py`
   (see `mahavishnu/core/health.py:1319`), so the `bifrost:` key is no
   longer a declared field and is dropped at `config.py:3547`. The YAML's own
   comment at `settings/mahavishnu.yaml:94-101` still tells operators to
   flip it, and `docs/specs/2026-10-15-bifrost-gateway-wiring-design.md:40`
   still documents it as a live opt-in. The repo's own
   `docs/plans/2026-10-17-bifrost-oneiric-gateway-adapter.md:36,99` already
   names this as the "dead flag" anti-pattern.

4. **`caller_quota` is inert, and the YAML disagrees with the code by 60×.**
   `settings/mahavishnu.yaml:470-473` says `default: 100,
   window_seconds: 3600`; the enforcing code hardcodes
   `window_size_seconds = 60, max_per_window = 60`
   (`mahavishnu/pools/manager.py:107-111`).
   `docs/CONFIGURATION.md:466-468` documents the YAML numbers as live.

5. **`docs/CONFIGURATION.md` documents ten blocks that nothing reads** —
   `verification.*` (:462-465), `caller_quota.*` (:466-468),
   `feature_flags.use_*` (:469-471), `persistence.*` (:458-461),
   `worker_contract.*` (:328-336), `worktree_providers.*` (:340-342),
   `adapter_registry.*` (:415-421), `otel_storage.*` (:204-215),
   `embeddings.*` (:473-486), `runpod_pool.*` (:488-494). Only
   `persistence.postgres_url` has a reader
   (`mahavishnu/metrics_cli.py:53-64`, a direct `yaml.safe_load` of
   `settings/mahavishnu.yaml` that bypasses the settings model entirely).
   The doc hedges at `:456` ("compatibility blocks … permits extra YAML
   keys") but still describes each as a functioning knob with a behavioural
   description.

6. **`task_orphan_sweeper:` is a shadow copy of code defaults.** All five
   values (`enabled`, `stream`, `consumer_group`, `block_ms`, `count`) are
   duplicated verbatim as constructor defaults at
   `mahavishnu/mcp/sweepers/task_orphan_sweeper.py:94-113`, and the
   production wiring (`mahavishnu/mcp/lifecycle.py:129-131`) passes **none**
   of them. The worst kind of knob: it looks live and the values happen to
   agree.

7. **`worker_contract:` is test-only.** The single reader is
   `tests/unit/config/test_worker_contract_settings.py:9-16`, which parses
   the raw YAML. `docs/CONFIGURATION.md:328-336` claims it "enables the
   worker contract runtime". `docs/CONFIGURATION.md:344-350` similarly
   documents `worktree_storage.backend_preference` / `.local.base_path` /
   `.s3.*` / `.gcs.*` — **fields that do not exist** on the current
   `WorktreeStorageSettings` — as does `idempotency.default_ttl_seconds` /
   `.pending_timeout_seconds` (:587-599) and `pi_pool.default_model` (:203,
   explicitly deleted).

8. **`settings/embeddings.yaml` is a stale, renamed mirror of live
   sections.** Its `pools_enabled` / `default_pool_type` /
   `pool_routing_strategy` / `memory_aggregation_enabled` /
   `memory_sync_interval` / `session_buddy_pool_url` / `akosha_url` are the
   *old names* of `pools.*` (`config.py:591-651`), and its
   `adapters: {prefect, llamaindex, agno}` are the old names of
   `AdapterConfig.prefect_enabled` / `llamaindex_enabled` / `agno_enabled`.

### 4.3 Drift risks — declared in YAML *and* hardcoded in Python

| Key | YAML site | Python site | Consequence |
|---|---|---|---|
| `caller_quota.default` / `.window_seconds` | `mahavishnu.yaml:472-473` (`100`/`3600`) | `pools/manager.py:107-111` (`60`/`60`) | 60× disagreement; YAML ignored |
| `task_orphan_sweeper.*` (5 keys) | `mahavishnu.yaml:704-708` | `mcp/sweepers/task_orphan_sweeper.py:97-103` | exact duplicates; YAML ignored |
| `pools.default_writable_root` | `mahavishnu.yaml:162` | `pools/mahavishnu_pool.py:150-185` | the YAML name is not the field the code reads (`writable_root`), and `PoolConfig` forbids extra |
| `agno_teams` team definitions | `settings/agno_teams/*.yaml` (model `MiniMax-M3`) | `engines/agno_teams/config.py:287-373` (model `claude-sonnet-4-6`) | two divergent copies of the same teams; neither is used in production |
| `embeddings.{provider,model,batch_size,enable_cache}` | `settings/embeddings.yaml:35,45,52,53` | `core/embeddings_oneiric.py:48-80` | two copies; the YAML one is unreachable |
| `runpod_pool.{default_gpu,default_workers,default_endpoint_name,default_dependencies}` | `mahavishnu.yaml:167-173` | — | the values exist nowhere in Python |

### 4.4 The generalizable lesson

`settings/models.yaml` was not special. It failed the same way these keys
fail: **a key whose name looks plausible, bound by a config loader that
fails soft, consumed by nothing.** The fix that worked there was to make
the file *live* (load it for real) rather than to document it as inert.

For keys with no intended consumer, the equivalent fix is to **delete them**,
not to annotate them — an annotated dead knob is still a trap for the next
reader.

## 5. Implementation Phases

Each phase below is a separate decision. §5.1 is proposed first because it
is the cheapest and because it fixes the recurrence, not just the instance.

### Phase 1: Make the loader loud about unknown keys (REQ-DEAD-001)

**Goal:** a key that binds to nothing produces a warning, so the next dead
knob is visible at startup instead of at audit time.

**Tasks:** in `mahavishnu/core/config.py`, log a WARNING for each top-level
YAML key dropped at `config.py:3547` and each sub-key dropped at
`config.py:3560`, naming the key and the section. Add a test asserting the
warning fires for an unknown key and does not fire for a known one.

#### Integration Contract
- **Triggered from:** `get_settings()` (`mahavishnu/core/config.py:3455`).
- **Returns to / updates:** the logger; no settings state.
- **Demonstrable by:** `pytest tests/unit/test_config.py -k unknown_key -v`
  and a startup log line naming the dropped key.
- **Rollback signal:** the warning volume — a config with many stale keys
  would emit a warning storm; suppress per-section after the first.
- **Observability added:** one WARNING per dropped key, naming key + section.

### Phase 2: Delete or wire the two unread files (REQ-DEAD-003)

**Goal:** `settings/embeddings.yaml` and `settings/agno_teams/*.yaml` are
either loaded or gone.

**Tasks:** decide per file — delete the file and its `CLAUDE.md` /
`docs/CONFIGURATION.md` mentions, or wire the loader. For `agno_teams`,
wiring means making `agno.teams_config_path` reachable from
`mahavishnu team create`; for `embeddings.yaml`, wiring means fixing the
top-level-vs-nested shape mismatch in `embeddings_oneiric.py:96-99` (which
also affects the `embeddings:` block in `mahavishnu.yaml`).

#### Integration Contract
- **Triggered from:** `mahavishnu team create` / the embeddings loader.
- **Returns to / updates:** `settings/`, `docs/CONFIGURATION.md`,
  `CLAUDE.md`, `settings/README.md`.
- **Demonstrable by:** `pytest tests/unit/engines/test_agno_teams.py -v`;
  `mahavishnu team create --config settings/agno_teams/research.yaml` prints
  the team's members.
- **Rollback signal:** `audit_orphans.py` flags a newly-orphaned loader.
- **Observability added:** the loader's existing log line names the file it
  loaded.

### Phase 3: Reconcile the inert `mahavishnu.yaml` keys (REQ-DEAD-001)

**Goal:** the nineteen inert top-level keys are removed or given a consumer.

**Tasks:** per key, decide. The ones with an obvious intended consumer are
`caller_quota` (values disagree with the code by 60× — decide which is
right, then make the other one read it), `task_orphan_sweeper` (pass the
five values through `mcp/lifecycle.py:129`), `bifrost.route_qwen_code`
(either revive `BifrostConfig` or drop the key), and `worker_contract`
(its only reader is a test). The remainder —
`server_name`, `cache_root`, `health_ttl_seconds`, `otel_storage`,
`runpod_pool`, `pi_pool`, `embeddings`, `adapter_registry`, `verification`,
`caller_quota`, `feature_flags`, `worktree_providers`, `worktree_storage`,
`idempotency`, `jot`, `goal_teams.goal_parsing`, `goal_teams.limits`,
`hatchet.max_runs`, `workers.default_type`, `workers.timeout_seconds`,
`workers.session_buddy_integration`, `workers.container.runtime`,
`persistence.read_source`, `persistence.task_store_write`,
`persistence.search_write`, `persistence.event_write`,
`pools.default_writable_root`, `health.feed_halflife_seconds` — are
candidates for deletion, subject to a check that no *other* repo or a
deployment script reads them.

#### Integration Contract
- **Triggered from:** `get_settings()`; `docs/CONFIGURATION.md` readers.
- **Returns to / updates:** `settings/mahavishnu.yaml`,
  `docs/CONFIGURATION.md`, `mahavishnu/core/config.py` (delete the now-unused
  fields), `settings/mahavishnu.yaml.example`.
- **Demonstrable by:** the Phase 1 warning stream is empty for the shipped
  config; `pytest tests/unit/test_config.py -q`.
- **Rollback signal:** `audit_orphans.py` flags a settings field that lost
  its last reader.
- **Observability added:** Phase 1's warnings, which become the regression
  detector for this phase.

### Phase 4: Correct `docs/CONFIGURATION.md` (REQ-DEAD-001)

**Goal:** the doc describes only knobs a reader can find a consumer for.

**Tasks:** after Phases 1-3 settle which keys survive, delete the sections
for the deleted keys and mark any deliberately-inert key as inert with the
reason. Fix the fields documented but non-existent —
`worktree_storage.backend_preference` / `.local.base_path` / `.s3.*` /
`.gcs.*`, `idempotency.default_ttl_seconds` / `.pending_timeout_seconds`,
`pi_pool.default_model`.

#### Integration Contract
- **Triggered from:** a reader following the configuration doc.
- **Returns to / updates:** `docs/CONFIGURATION.md` only.
- **Demonstrable by:** every key named in the doc has a consumer greppable
  in `mahavishnu/`.
- **Rollback signal:** n/a — documentation-only phase.
- **Observability added:** none.

### Phase 5: Sweep the sibling repos

**Goal:** the pattern is not unique to this repo.

**Tasks:** run the same audit against `oneiric`, `akosha`, `session-buddy`,
`crackerjack`, and `mcp-common` `settings/` directories.

#### Integration Contract
- **Triggered from:** this plan's audit method.
- **Returns to / updates:** sibling repos — cross-repo, separate PRs.
- **Demonstrable by:** a per-repo verdict table like §4.1.
- **Rollback signal:** n/a.
- **Observability added:** none.

## 6. Required Code Changes

- [ ] `mahavishnu/core/config.py` — warn on dropped top-level and sub-keys
- [ ] `mahavishnu/core/config.py` — remove fields whose keys are deleted
- [ ] `mahavishnu/mcp/lifecycle.py` — pass the `task_orphan_sweeper` values
- [ ] `mahavishnu/core/embeddings_oneiric.py` — fix the top-level parse, or
      leave the file deleted
- [ ] `mahavishnu/cli/team_cli.py` — accept a YAML team config, or leave the
      files deleted
- [ ] `settings/mahavishnu.yaml`, `settings/embeddings.yaml`,
      `settings/agno_teams/*.yaml` — delete or complete
- [ ] `settings/mahavishnu.yaml.example` — track the same removals
- [ ] `docs/CONFIGURATION.md`, `CLAUDE.md`, `settings/README.md` — correct

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence |
|---|---|---|
| `pytest tests/unit/test_config.py -q` | pass | pytest output |
| `pytest tests/unit/engines/test_agno_teams.py -q` | pass | pytest output |
| `python scripts/audit_orphans.py` | no newly-orphaned settings field | script output |
| `python scripts/audit_requirements.py` | exit 0 | script output |
| startup log scan for dropped-key warnings | empty for the shipped config | log output |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| A deleted key was read by a deployment script outside this repo | Medium | Grep the fleet and the sibling repos before deleting; Phase 5 surfaces it |
| Warning noise from a config with many stale keys | High | Collapse to one warning per section |
| A key is deleted while a plan intends to revive it | Medium | Check `docs/plans/` for the key before deleting; record the decision in §5 |
| The doc is corrected but the key stays dead | Medium | Phase 1's warnings are the regression detector; doc edits alone are not the fix |

## 9. Decision Rule

This plan is done when: no key in `settings/` is INERT; every key the
`docs/CONFIGURATION.md` names has a greppable consumer; the two unread files
are loaded or gone; and Phase 1's warnings are empty for the shipped config.
If Phase 1 proves too noisy to ship, cut to Phases 2-4 — deleting the dead
keys is worth doing even without the warning stream.

## 10. Known limitations of this audit

- The sub-key diff inside `settings/mahavishnu.yaml` was exhaustive
  (programmatic `model_fields` comparison, which found exactly two
  non-field sub-keys), and every leaf name was grepped across `mahavishnu/`
  and `scripts/`. A leaf with a hit was assumed READ; a coincidental hit (the
  same identifier used for an unrelated concept) could hide an INERT key.
  The INERT list in §4.2 was hand-verified.
- `settings/repos.yaml` is dead at runtime *on this machine* only because
  `settings/ecosystem.yaml` exists. It is a live fallback elsewhere.
- `repos[].mcp` and `repos[].status` are read only by `scripts/` doc
  generators, not by a runtime service. Classified READ (tooling).
- `settings/crackerjack.yaml` is read by the sibling crackerjack repo, and
  only when crackerjack runs with a mahavishnu checkout as its project root
  (`mahavishnu/core/merge_to_main.py:221-244`). If that path is out of band,
  this file is INERT too.
