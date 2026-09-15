# Dhara MCP Decomposition — Final Multi-Agent Review

**Date:** 2026-09-15
**Spec:** `docs/superpowers/specs/2026-09-14-dhara-mcp-decomposition-design.md` (head commit `8badf605`)
**Plan:** `docs/superpowers/plans/2026-09-14-dhara-mcp-decomposition-implementation.md` (head commit `8badf605`)
**Reviewers:** 5 agents across non-overlapping lenses (per `multi-agent-review-catches-blind-spots.md`)
**Outcome:** PATH A applied — 8 high-convergence fixes committed; ~70 findings logged for follow-up.

______________________________________________________________________

## 1. Multi-Agent Review Summary

### Lens × Severity Tally

| Lens | HIGH | MEDIUM | LOW | Total |
|---|---|---|---|---|
| Critical-audit | 6 | 7 | 5 | 18 |
| Observability | 4 | 7 | 4 | 15 |
| Data-retention | 5 | 7 | 4 | 16 |
| Performance | 3 | 7 | 5 | 15 |
| MCP-integration | 4 | 7 | 5 | 16 |
| **Total** | **22** | **35** | **23** | **80** |

### Hot-Spot Convergence (≥2 lenses flag the same concern)

1. **Plan source-map Phases 1-11 TDD gap** — Critical-audit H1 + MCP-integration H2 + Data-retention M6 = **3 lenses**; committed risk for execution.
1. **Enumeration discipline (Phase 1 caller grep + Phase 12 hook grep, too-narrow scope)** — Data-retention H3+H4 + Performance L5 + Critical-audit = **3 lenses**.
1. **Bus + audit observability for hooks** — Observability H1+H3 + Performance M3+M4 + MCP-integration M1 = **3 lenses**.
1. **`mcp_common` cross-repo coordination** — MCP-integration H3 + Observability H4 + Critical-audit via §4.3 = **3 lenses**.
1. **Plan ⇔ spec divergences** — Critical-audit H2-H6 + MCP-integration H5 + Data-retention H5 = **4 lenses**.
1. **`oneiric.adapters.bootstrap.queued_publisher()` factory existence** — MCP-integration M1 + Performance M2+H1 + Observability H1 = **3 lenses**.
1. **HealthMonitor primitives + `observed_tool_span` decorator lack TDD** — MCP-integration M2 + Critical-audit (via spec §4.8) + Observability M2 = **3 lenses**.

### PATH A — Applied in commit `8badf605`

8 of the highest-convergence findings committed (spec + plan, +86/-26 lines):

| Spec section | Fix applied |
|---|---|
| §4.9 | MIGRATION.md ownership assigned to Phase 8 task 20 (resolves §4.9 vs Phase 8 contradiction) |
| §4.8 | Audit event shape extended with `outcome`, `caller_session_id`, `error_class`; audit cross-correlation contract added |
| §4.8 | Bus publish error tracking: `hook_bridge_feed.errors_total` + `publish_failures_total` increment on failure (forbids silent no-op) |
| §4.8 | Bus subscriber per-feed signals: subscribers own their own `ComponentHealth` feed |
| §4.8 | Canonical `polling_interval = 60s` defined |
| §4.10.1 | NEW: migration observability (OTel span `bodai.migration.<substrate>` + audit event + `migration_completed_at` feed field) |
| Phase 11 | `mcp_common.dispatch.mount(server=...)` renamed to `mcp_common.tools.dispatch.register_remote_tools(server, namespace, tools)` for Phase 1.5 naming consistency |

| Plan section | Fix applied |
|---|---|
| Phase 12a task 1 | `_publish()` increments `hook_bridge_feed.errors_total` + `publish_failures_total` on failure |
| Phase 12a task 1 | Path consistency: `bodai_hook_bridge.py` lives at `mahavishnu/mahavishnu/bodai_hook_bridge.py`; `sys.path.insert` arithmetic corrected (`parent.parent` not `parent.parent.parent`) |
| Phase 12a task 5 | Dropped `bus_subscribers/jot_drainer.py` separate package; adopts spec's `oneiric.adapters.queue.redis_streams` directly |
| Phase 12a task 5 | Dropped `MAHAVISHNU_BODAI_QUEUE_PATH` env var fallback (hard cutover per R12) |
| Phase 12a task 0 step 1 | Grep scope extended to `**/*.{py,sh,md,json,yaml,yml,toml}` + `~/.mahavishnu/` + `~/.qwen/hooks/` |
| Phase 12a task 5 step 3 | Subscriber pattern registers `jot_drainer_feed` with own `ComponentHealth` |

### Deferred to follow-up (PATH A explicit exclusion)

Recorded in commit message; reproduced here as a working backlog:

**TDD regeneration (most material deferred item):**

- Phases 1-11 pytest-first scaffold expansion (currently only Phase 12 has full TDD; Phases 1-11 are spec-only)
- Regenerate before Phase 1 execution begins; gating by writing-plans skill template

**Cross-repo coordination:**

- Phase 1 commits to mcp-common modifications (`AuditLogger.tool_invocation`, auth middleware OTel propagation, `observed_tool_span` decorator) that the plan doesn't sequence — pre-Phase-1 must cut mcp-common dev tag, publish, then Phase 1 picks up the tag
- Mahavishnu's `bump_version` (per `feedback-mcp-common-version-bump-is-user`) is user-controlled; explicit gates needed

**Operability gaps from observability lens:**

- Alertmanager rules + `bodai-mcp-incident.md` runbook + `mahavishnu mcp ecosystem health` aggregator currently Phase 8; H2/M7 argue for Phase 1 delivery
- `polling_interval` per-component overrides should be spec-documented

**Adapter / API verification:**

- `oneiric.adapters.bootstrap.queued_publisher()` factory existence (MCP-integration M1) — see §2 below
- Phase 5/Phase 10/Phase 6 cross-coupling explicit double-direction (data-retention M4)

**Performance / quality:**

- Performance budget quantification (H2/H3 perf: cross-MCP call latency, Oneiric 54-adapter lazy-load contract)
- Gateway pattern ADR-018 recommendation (Phase 11)
- `mahavishnu git-hook install` sub-command for per-clone hook installation (data-retention L2)
- Phase 8 'Tests to update' duplicate block removal (critical-audit H2)
- ADR-013 reversal single-owner decision (critical-audit H6)
- Spec §4.3 wording tighten re Dhara exclusion (critical-audit L2)
- `oneiric.adapters.bootstrap.queued_publisher()` factory existence (MCP-integration M1)

**AkoSHA HotStore dedup refactor (post-Phase 5, pre-Phase 10):**

- `akosha/storage/hot_store.py` (~700 LOC) duplicates Oneiric's `DuckdbHotStore` conversations-table surface: `__init__`, `initialize`, `insert`, `search_similar`, `close`, `_compute_content_hash` static method, `conn` attribute, and the conversations-table CREATE TABLE DDL.
- Refactor: `class HotStore(DuckdbHotStore):` — subclass inheriting the conversations-table surface; keeps only the four code-graph methods (`initialize_code_graphs_table`, `store_code_graph`, `get_code_graph`, `list_code_graphs`) as the AkoSHA-only extension.
- Net result: ~700 LOC → ~200 LOC; conversations-table DDL exists only in `oneiric/adapters/vector/duckdb_hot_store.py:143-156`; no caller-side import changes.
- Why deferred (3 reasons): (1) cross-component vs. intra-component split — Phase 5 task 8 fixed cross-component; this is AkoSHA-internal simplification. (2) Depends on Phase 10 pgvector fate — `PgvectorHotStore` (241 LOC, currently unreachable per R10) is unresolved until Phase 10 picks Option A or B; subclass scope depends on that decision. (3) Substrate had to land first — Protocol + concrete shipped in oneiric commits `93f60cd` + `198564e`.
- Where documented: spec §Phase 5 follow-up (new sub-section added 2026-09-15); plan "Phase 5 Follow-up: AkoSHA HotStore → DuckdbHotStore subclass" section (new, with TDD tasks F1-F2); substrate-side note `oneiric/adapters/vector/duckdb_hot_store.py:16-20`.

______________________________________________________________________

## 2. Wiring Verification (NEW — added 2026-09-15 after PATH A)

Conducted following PATH A to verify the spec's assumptions about existing infrastructure before Phase 1 begins. **12 findings — 5 are HIGH (will block Phase 1 execution), 4 are MEDIUM, 3 are LOW.**

### 2.1 Verified inconsistencies between spec/plan and current code state

**W1 [HIGH] — `oneiric.adapters.bootstrap.queued_publisher()` factory does NOT exist.**

- Spec §4.13.4 references `oneiric.adapters.queue.redis_streams`; the Phase 12 plan introduced `queued_publisher()` as the canonical entry point (plan Phase 12a task 0 step 4, task 1 step 3, task 5 step 3).
- Verified: `from oneiric.adapters import bootstrap; dir(bootstrap)` exports adapters (`AdapterMetadata`, `register_builtin_adapters`, `Resolver`, `RedisStreamsQueueAdapter`, ...), but **no `queued_publisher()` function exists**. The package exposes `RedisStreamsQueueAdapter` for direct use.
- **Impact:** Phase 12a task 0 step 4 will FAIL the pre-flight gate (expecting "a function reference or a stub"). Phase 12a task 1 step 3's `from oneiric.adapters.bootstrap import queued_publisher` will raise `ImportError`.
- **Fix path:** Either (a) add `queued_publisher()` factory to `oneiric/adapters/bootstrap.py` (preferred — extends the public API cleanly), OR (b) refactor the plan to use `from oneiric.adapters import bootstrap; bootstrap.RedisStreamsQueueAdapter()` directly without the factory facade.
- **Owner:** Phase 12 pre-flight + Phase 12a task 1.

**W2 [HIGH] — Oneiric OTel default URL has spaces around the colon (real bug).**

- Spec R10 line 369 references `mahavishnu/settings/mahavishnu.yaml:144` with `persistence.postgres_url=""`, but the actual bug is in Oneiric at `/Users/les/Projects/oneiric/oneiric/adapters/observability/settings.py` line 9: `default="postgresql://postgres: postgres@localhost: 5432/otel"`.
- Verified: literal spaces around `:`, between `postgres` and `@`, and between `localhost` and `:`. Validators at line 50-51 only check `startswith("postgresql://")` — they don't strip whitespace, so the spaces would NOT be rejected by either Oneiric OR Mahavishnu's stricter validator (claim needs verification; see W3).
- **Impact:** Operators who rely on the default `OTelStorageSettings()` get a Postgres URL with literal spaces, which Postgres then rejects. Confirm before Phase 5 task 8.
- **Fix path:** Phase 10 task 3 Option A (fix the default literal) is the surgical fix; bundle into Phase 10 task 3 whichever default is locked in (B also keeps the default literal, so fix the default in either case).
- **Owner:** Phase 10.

**W3 [HIGH] — Mahavishnu's "stricter validator" claim against the Oneiric OTel URL is unverified.**

- Spec R10 line 369 says `mahavishnu/core/config.py:880-916` is Mahavishnu's stricter OTel URL validator that would reject the spaces-around-colon default. This file path may or may not exist; the validator may or may not exist in those line numbers; even if it exists, the spaces-around-colon validation behavior must be verified.
- **Impact:** If the validator doesn't actually catch the spaces, the spec's claim is wrong and the bug surfaces at runtime when an operator uses the Oneiric default.
- **Fix path:** In Phase 10 task 3 step 1 (pre-flight), grep `mahavishnu/core/config.py` around 880-916 to verify the validator's existence and behavior. If absent, fix the Oneiric default literal directly (W2 fix) and document the discarded validation claim.
- **Owner:** Phase 10.

**W4 [HIGH] — `mcp_common.canonical_schemas`, `mcp_common.signing`, `mcp_common.traces` modules do NOT exist.**

- Spec §4.11 + Phase 1.5 task 3 + Phase 4 task 2/4 reference `mcp_common.canonical_schemas.agent/skill` and `mcp_common.signing.skills_signer`. Plan Phase 12 refactors `mahavishnu/bodai_hook_bridge.py` to use `mcp_common.traces.endpoint_resolver`.
- Verified `ls /Users/les/Projects/mcp-common/mcp_common/`: directories present include `apple_script, auth, backends, cli, clients, code_graph, config, fastmcp, health, interfaces, llm, parsing, profiles, prompting, schemas, security, server, testing, tools, ui, validation, websocket`. **No `canonical_schemas/`, no `signing/`, no `traces/`, no `discovery.py`, no `catalog.py`, no `health_tools.py` as separate from `health/`**.
- **Impact:** Plan creates new packages that have no PR sequence. These are net-new modules that must be added to a `mcp-common` release before Phase 4 can ship.
- **Fix path:** Update the Phase 1.5 / Phase 4 / Phase 12 plans to ADD a sub-task: "Cut `mcp-common` PR first (canonical_schemas, signing, traces, discovery, catalog, health_tools); publish dev tag; then Phase 1.5/4/12 picks up the tag."
- **Owner:** Phase 1.5 + Phase 4 + Phase 12 (cross-cutting).

**W5 [HIGH] — `mcp_common.tools.observed_tool_span` decorator module-path inconsistency.**

- Phase 1 task 7 (spec line 514, plan Phase 1 task 7) says to implement `mcp_common.tools.observed_tool_span` decorator.
- Verified `ls /Users/les/Projects/mcp-common/mcp_common/tools/`: directories/files include `__init__.py, descriptions.py, dispatch.py, mermaid_validator, profiles.py`. **`observed_tool_span.py` does not exist**; the decorator must be net-new.
- Also: `dispatch.py` exists, but the canonical function the spec names (`apply_tool_profile`) is referenced in `profiles.py` line 103 / 110, not `dispatch.py`. Path inconsistency between spec/plan.
- **Impact:** Phase 1 task 7 is net-new code in `mcp-common`; plan should clarify whether it's in `dispatch.py` (existing module) or `observed_tool_span.py` (new module). Pick one.
- **Fix path:** Phase 1 plan's pre-flight should add "verify `mcp-common` release plan covers this." Plan can decide module path; either works if the function signature is consistent.
- **Owner:** Phase 1.

**W6 [MEDIUM] — `HealthMonitor.record_invocation / set_entities_count / get_feed` primitives do NOT exist.**

- Spec §4.8 / R9 line 1056 says these primitives must be added; Phase 1 task 1 step 1 (Spec creation) and task 6 (Extension) depend on them.
- Verified `grep -rn "def record_invocation" /Users/les/Projects/oneiric/oneiric/runtime/`: 0 matches.
- **Impact:** Phase 1 task 6 is a true precondition; without it, Phase 1 task 8's e2e test ("/health returns 200 with 7 healthy feeds on warm startup") cannot construct feeds with non-zero `cycles_total` and read per-feed signals. This was a known R9 in the spec; the wiring verification confirms it's real.
- **Fix path:** Phase 1 task 1 step 1 (the early task that adds the primitives) is real work; the plan + spec are accurate. Execution risk is bounded to the Phase 1 task 1 commit landing before task 6/8.
- **Owner:** Phase 1 task 1.

**W7 [MEDIUM] — `mahavishnu/settings/mahavishnu.yaml` reference path is correct (verified).**

- Verified path is `/Users/les/Projects/mahavishnu/settings/mahavishnu.yaml` (one level up from `mahavishnu/`); spec's references (lines 140, 144, 304-307, 365-370) assume the right path. Plan Phase 1 task 10 + Phase 5 task 8 should grep here, not in `mahavishnu/settings/` (which does not exist).
- **Impact:** Documentation fix only; path was already correct in spec but Bash checks against `mahavishnu/mahavishnu/settings/` would fail.
- **Owner:** Bash checks only — no spec/plan change needed.

**W8 [MEDIUM] — `akosha/settings/akosha.yaml` reference path is correct (verified).**

- Same as W7 — `akosha/settings/akosha.yaml` exists; spec's references (lines 95-99, 84-89) are correct.
- **Impact:** Same; path is right, Bash checks against `akosha/akosha/settings/` would fail.
- **Owner:** Bash checks only.

**W9 [LOW] — `mcp_common.tools.profiles` vs `dispatch` path inconsistency in spec.**

- Phase 1 task 5 (spec line 489) says: *"Wire tool profile gating via `mcp_common.tools.dispatch.apply_tool_profile`"*.
- Verified: `apply_tool_profile_async` is implemented in `mcp-common/mcp_common/tools/profiles.py:103, 110`, NOT `dispatch.py`. The plan should reference `mcp_common.tools.profiles.apply_tool_profile`, not `dispatch`.
- **Impact:** Plan references the wrong module; small confusion. Either update the spec/plan to point to `profiles.py`, OR add a thin `apply_tool_profile` re-export to `dispatch.py` for spec-fidelity.
- **Fix path:** Phase 1 plan update; low-risk edit.
- **Owner:** Phase 1.

**W10 [LOW] — `mcp_common.health` is a package, `health_tools` is a sibling concept (verified).**

- Phase 1.5 task 4 (spec line 560, plan Phase 1.5 Task 4) creates `mcp_common.health_tools.mount(server)`.
- Verified `mcp_common/health/`: directories include `__init__.py, aggregator.py, feed.py`. So `mcp_common.health` IS a package (with `aggregator.py` + `feed.py`) — it's the canonical home for health primitives. The spec creates a parallel `mcp_common.health_tools` module naming, which is technically distinct but conceptually adjacent.
- **Impact:** Plan creates a sibling module. Either consolidate (`mcp_common.health.tools.mount` inside the package), or distinguish clearly. Doesn't block; just adds a parallel concept.
- **Fix path:** Phase 1.5 plan update — either commit to `mcp_common/health/__init__.py` + a new `mcp_common/health/tools.py` (stays inside package), OR clarify why the separate `mcp_common.health_tools` module exists.
- **Owner:** Phase 1.5.

**W11 [LOW] — `mcp-backend-wiring-discipline.md` is at `mahavishnu/.claude/decisions/` not `~/.claude/decisions/`.**

- Spec §4.8 (paraphrased) and observability review report referenced `~/.claude/decisions/mcp-backend-wiring-discipline.md`. Verified: file exists at `/Users/les/Projects/mahavishnu/.claude/decisions/mcp-backend-wiring-discipline.md` (10,248 bytes; Sep 13). Doesn't exist at `~/.claude/decisions/mcp-backend-wiring-discipline.md`.
- **Impact:** Doc-string references in spec/plan to the wiring-discipline file as the canonical contract for /health 503, per-feed signals, etc., point at the wrong path. The contract is the same; the path is just wrong.
- **Fix path:** Update spec/plan to reference the correct path. Or (better) copy the file to `~/.claude/decisions/` since the spec cites it as a project-spanning rule, not mahavishnu-specific.
- **Owner:** Small text fixes in spec/plan.

**W12 [LOW] — `oneiric/adapters/cache/persistent_kv.py` does NOT exist (Phase 6 net-new).**

- Spec §5 Phase 6 task 1 + plan Phase 6 task 1 creates `oneiric/oneiric/adapters/cache/persistent_kv.py` (~443 LOC ported from `dhara/mcp/kv_timeseries.py`).
- Verified `ls /Users/les/Projects/oneiric/oneiric/adapters/cache/`: `__init__.py, __pycache__, memory.py, multitier.py, redis.py`. **`persistent_kv.py` does NOT exist.**
- **Impact:** Phase 6 task 1 creates net-new adapter; same planning as W5. Plan/cross-repo coordination: cut Oneiric PR for the adapter, publish dev tag, then Phase 6 picks it up.
- **Fix path:** Update Phase 6 plan to make the Oneiric PR cross-cutting coordination explicit.
- **Owner:** Phase 6.

### 2.2 Verified consistency between spec/plan and current code state

- `mahavishnu/ingesters/otel_ingester.py:38-44`: `from akosha.storage import HotStore` IS PRESENT (line 38, in the `if TYPE_CHECKING:` block) — confirms W-dependency claim from spec Phase 5 task 8.
- `oneiric/adapters/observability/settings.py:9`: spaces-around-colon is the literal default — W2 confirmed.
- `oneiric/adapters/bootstrap.py`: exposes `RedisStreamsQueueAdapter`, `Resolver`, `register_builtin_adapters` — public API for Phase 5/6 use exists; Phase 12's `queued_publisher()` factory does NOT.

______________________________________________________________________

## 3. Working Backlog (Phase Sequencing Recommendation)

When Phase 1 execution starts (after PATH A's commit `8badf605`):

**Pre-Phase-1 (must happen first):**

1. **Cut `mcp-common` PR** adding: `canonical_schemas.{agent,skill}.py` (Phase 4 prerequisites), `signing/skills_signer.py` (Phase 4), `signing/dhara_skills_signer/` (Phase 4); `traces/{endpoint_resolver,__init__}.py` (Phase 12); `discovery.py` + `catalog.py` + `ide/__init__.py` + `ide/pycharm_tools.py` + `health_tools.py` (Phase 1.5); `tools/observed_tool_span.py` (Phase 1).
1. **Cut Oneiric PR** adding: `mcp/server_core.py` (Phase 1), `mcp/tools/adapter_registry.py` (Phase 1), `mcp/settings/oneiric.yaml` (Phase 1); `adapters/cache/persistent_kv.py` (Phase 6); `http/routes/substrate.py` (Phase 7); fix `adapters/observability/settings.py:9` literal (Phase 10).
1. **Cut Akosha PR** adding: `mcp/tools/query_local_traces_fitness.py` (Phase 5); decide pgvector fate (Phase 10).
1. **Cut Mahavishnu PR** adding: `mcp/tools/ecosystem_state.py` (Phase 3); `core/ecosystem_state_store.py` (Phase 3); flip ingesters/otel_ingester.py:38 (Phase 5); commit/decide `adapters/pgvector_adapter.py` (Phase 10); `mahavishnu/bodai_hook_bridge.py` (Phase 12).
1. **Cut Crackerjack PR** adding: `mcp/tools/agent_registry.py` + `mcp/tools/skill_registry.py` (Phase 4); `mcp/profiles.py` mandatory_groups update (Phase 4).
1. **Cut Dhara deletions** (Phase 8): `dhara/mcp/`, `dhara/skills_signer/`, slim `pyproject.toml`, CHANGELOG/CLAUDE.md cleanup, MIGRATION.md.

**Phase 1 execution prerequisites:**

- Phase 1 task 6 `HealthMonitor` primitives landed (W6).
- `mcp-common` PR (above) landed + dev tag published.
- Oneiric PR (above) landed + dev tag published.

**Risk register additions (beyond spec §6):**

- R13 (new): mcp-common cross-repo coordination drift — Phase 1's mcp-common dependencies (audit shape, OTel middleware, observed_tool_span) must land BEFORE Phase 1 execution; otherwise commits don't compile
- R14 (new): `oneiric.adapters.bootstrap.queued_publisher()` factory availability — Phase 12a pre-flight gate must verify or implement
- R15 (new): Oneiric OTel default URL spaces-around-colon — Phase 10 must fix (option A or option B); both options must remove the spaces literal
- R16 (new): Phase 1-11 TDD scaffold gap — operationally significant; operator discipline matters more than spec/plan coverage. Recommend explicit TDD regen session before Phase 1 starts

______________________________________________________________________

## 4. Verdict

**Spec is structurally sound.** The decomposition reads correctly top-to-bottom; tool routing per §4.2 is internally consistent; risks are catalogued well; ADR cross-references align.

**Plan has PATH-A-resolvable gaps** — 12 wiring-verification findings expose that much of the spec's expected infrastructure (the mcp-common modules, Oneiric's MCP server + cache adapter, the bus factory) is **net-new** rather than existing. The plan did not sequence these as upstream cross-repo PRs. **This is the single largest pre-execution risk.**

**Multi-agent review caught what spec-internal review didn't.** The decomposition spec and plan were coherent in isolation; the 5-lens review found cross-cutting concerns (audit cross-correlation, bus subscriber-side observability, plan↔spec path inconsistencies, deferred cross-repo coordination) that internal-only review would miss.

**Recommended next session work (in order):**

1. Cut the cross-repo PRs (mcp-common, Oneiric, Akosha, Mahavishnu, Crackerjack, Dhara) — 1-2 sessions
1. Regenerate Phases 1-11 TDD scaffold from this spec — 1 session
1. Begin Phase 1 execution — dependent on (1) and (2)

**No spec rewrite needed.** Apply the PATH A commit `8badf605`; defer the rest via the working backlog above.
