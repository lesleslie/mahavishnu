---
status: active
role: implementation
date: 2026-09-10
last_reviewed: 2026-09-10
superseded_by: null
topic: settle-semantic-merge
requirements:
  - id: REQ-SM-001
    title: "Pluggable MergeStrategy enum on MahavishnuSettle.apply path"
  - id: REQ-SM-002
    title: "Mergiraf shell-out driver with lazy first-call PATH probe"
  - id: REQ-SM-003
    title: "Loud-failure MergeDriverUnavailableError when mergiraf missing under SEMANTIC"
  - id: REQ-SM-004
    title: "Per-binding merge_strategy field in SettleRunRecord (Dhara-persisted)"
  - id: REQ-SM-005
    title: "MahavishnuSettings.merge_driver_required startup guard (MahavishnuApp._init_observability)"
  - id: REQ-SM-006
    title: "git-merge-tree --name-only diagnostic subprocess for SEMANTIC strategy (deferred)"
  - id: REQ-SM-007
    title: "MergeStrategy serialization round-trip (to_dict → from_dict → equal)"
  - id: REQ-SM-008
    title: "scripts/check_merge_driver.py probes binary + tree-sitter grammars + git version"
  - id: REQ-SM-009
    title: "/health merge_driver.{available, binary, version, grammars, degraded_since}"
---

# Settle Semantic Merge — mergiraf opt-in + git-merge-tree diagnostics

**Date:** 2026-09-10
**Status:** `active`, `implementation`
**Owner:** Core Eng
**Scope:** `mahavishnu/settle/` and the single MCP call site that consumes it.
**Purpose:** Replace line-level `git merge-file` with entity-aware `mergiraf merge` as the default 3-way merger for `MahavishnuSettle.apply`, opt-out via per-binding strategy, and add a `git-merge-tree --name-only` diagnostic channel for audit.

## 1. Outcome

When a Mahavishnu worker applies a settle run, its candidate edits will merge with the user's main branch at the **entity level** (functions, classes, methods) rather than the line level, so non-overlapping edits inside the same file no longer produce spurious `<<<<<<<` conflict markers.

Concrete artifacts that prove success:

1. `mahavishnu/settle/merge.py::merge_three_way` accepts a `strategy` parameter; default resolution is `SEMANTIC` when `mergiraf` is on `$PATH`, else `LINE` with a `MergeDriverUnavailableError`.
2. Existing `MergeConflictError.merged` payload is preserved byte-shape; smoke test in `tests/integration/test_settle_merge_semantic_e2e.py` proves a 3-way merge that line-merging would fail on resolves cleanly under `SEMANTIC`.
3. A `git-merge-tree --name-only` diagnostic subprocess runs alongside the SEMANTIC merge and populates `MergeDiagnostics.conflicted_paths` so audit consumers can find every conflicted file in one query.
4. Operational hardening lands: `MAHAVISHNU_REQUIRE_MERGE_DRIVER=1` hard-errors at startup if mergiraf is missing; `scripts/check_merge_driver.py` exposes version + availability on `/health`.

## 2. Goals

1. Pluggable merge strategy without breaking the existing `MergeResult | MergeConflictError | MergeFailureError` contract.
2. Module-import PATH probe of `mergiraf` — cached on first call.
3. Per-binding strategy override threaded through `SettleRunRecord` and persisted to Dhara.
4. Loud-failure semantics (no silent fallback) when mergiraf is configured as default and the binary is missing.
5. Diagnostic channel via `git-merge-tree --name-only` for structured conflict-path reporting.

## 3. Non-Goals

1. Not replacing `git merge-file` outright — it stays as the `LINE` strategy for fallback and for environments that explicitly opt out.
2. Not changing the MCP tool surface (`worker_settle` action=`apply` keeps its existing JSON schema).
3. Not adding new public settings keys beyond `merge_driver_default: str = "mergiraf"` and the `MAHAVISHNU_REQUIRE_MERGE_DRIVER` env var.
4. Not migrating the merge engine to `git merge-tree --write-tree` (kept as a Phase 6 candidate per the plan's Decision Rule).
5. Not adding per-file `.gitattributes merge=mergiraf` wiring — the settle path shells out directly without going through git's merge plumbing.

## 4. Current Findings

- `mahavishnu/settle/merge.py` is the **only** merger; module docstring explicitly states "We deliberately do NOT implement our own merge algorithm." (Lines 1-13.)
- The **sole current consumer** is `mahavishnu/mcp/tools/worker_contract_tools.py:663`, which calls `await merge_three_way(base=..., ours=..., theirs=...)` inside the `APPLY` action handler. The `try/except` at lines 669-680 only catches `MergeConflictError` and `MergeFailureError` — a new `MergeDriverUnavailableError` (Phase 2) will need an additional arm.
- **Mergiraf exit-code semantics are NOT git's** (R4 reviewer-blind-spot finding, 2026-09-10). Real behavior verified against `mergiraf 0.19.1` at `/usr/local/bin/mergiraf` with positional invocation `mergiraf merge <BASE> <LEFT> <RIGHT> -p <PATH> --allow-parse-errors`:
  - Exit **0** = subprocess succeeded; stdout **may or may not** contain `<<<<<<<` conflict markers. Real semantic conflicts exit 0.
  - Exit **1** = input file unreadable (`could not read input`).
  - Exit **2** = internal parse error (tree-sitter grammar failure).
  Therefore conflict detection must scan stdout for `<<<<<<<` markers, **not** map exit codes. The legacy `git merge-file` mapping (`0 → clean`, `1 → conflict`) does **not** apply.
- `git merge-tree --name-only` available in git 2.55.0; structured output documented at `GIT-MERGE-TREE(1)`. `git merge-tree --write-tree` (Phase 6 candidate) requires git ≥ 2.38.
- Settle state machine at `mahavishnu/settle/state_machine.py` is a pure-function transition table; adding a `default_merge_strategy` field to `SettleRunRecord` is forward-compatible because `from_dict` already tolerates missing optional fields at lines 148 (state default), 152 (transitions default), 216 (binding `base` default), 293 (timestamps default).
- No prior evaluation of `weave` (Homebrew package, ataraxy-labs) exists in the Bodai session corpus — see Session-Buddy reflection stored 2026-09-10 tagged `merge-driver` for the decision rationale (`mergiraf` chosen over `weave` for broader grammar coverage and maturity).
- Tree-sitter grammars (Python, Rust, Go, etc.) are **not packaged with the mergiraf binary** — Homebrew bundles several, but `cargo binstall mergiraf` and most CI container images ship only the binary. Without a probe, every Python file settles fine locally and explodes in e2b sandboxes.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-SM-001
    title: "Pluggable MergeStrategy enum on MahavishnuSettle.apply path"
  - id: REQ-SM-002
    title: "Mergiraf shell-out driver with lazy first-call PATH probe"
  - id: REQ-SM-003
    title: "Loud-failure MergeDriverUnavailableError when mergiraf missing under SEMANTIC"
  - id: REQ-SM-004
    title: "Per-binding merge_strategy field in SettleRunRecord (Dhara-persisted)"
  - id: REQ-SM-005
    title: "MahavishnuSettings.merge_driver_required startup guard (MahavishnuApp._init_observability)"
  - id: REQ-SM-006
    title: "git-merge-tree --name-only diagnostic subprocess for SEMANTIC strategy (deferred)"
  - id: REQ-SM-007
    title: "MergeStrategy serialization round-trip (to_dict → from_dict → equal)"
  - id: REQ-SM-008
    title: "scripts/check_merge_driver.py probes binary + tree-sitter grammars + git version"
  - id: REQ-SM-009
    title: "/health merge_driver.{available, binary, version, grammars, degraded_since}"
```

## 5. Implementation Phases

### Phase 1: MergeStrategy protocol abstraction

**Goal:** Introduce a strategy enum and parameter to `merge_three_way` without flipping any defaults.
**Tasks:**
- Add `MergeStrategy(str, Enum)` to `mahavishnu/settle/merge.py` with `LINE` and `SEMANTIC` values. **Pin serialization**: `to_dict` writes `str(strategy.value)` (or `None`); `from_dict` accepts `MergeStrategy(raw)` after None-check. Add regression test `test_strategy_roundtrip` covering both `LINE` and `SEMANTIC` round-trips through a Dhara-shaped dict (REQ-SM-007).
- Add `strategy: MergeStrategy | None = None` parameter to `merge_three_way`; when `None` and `mergiraf` is on PATH, resolve to `SEMANTIC`; otherwise `LINE`.
- **Lazy PATH probe** (`_MERGIRAF_BIN: str | None` populated on first `merge_three_way` invocation, not at module import). Eager probe would block module load when `$PATH` is slow or `shutil.which` is expensive — lazy keeps import deterministic.
- Refactor body: branch on `effective == MergeStrategy.SEMANTIC`, delegate to a new private `_merge_via_mergiraf` async function; the existing `git merge-file` block stays in-place and unchanged.
- **Deprecate `merge_three_way_sync`** (the docstring already calls it "orphaned"). Rename to `_merge_three_way_sync_internal` and emit `DeprecationWarning` on call. Threading `strategy` into a sync path adds dead code; Phase 1 keeps only the async surface public.
**Exit criteria:** Existing `tests/unit/settle/test_merge_three_way.py` (if present) still passes; new property test asserts `strategy=LINE` returns byte-identical output to pre-refactor `git merge-file` invocation (lines 93-108 unchanged); `merge_three_way_sync` no longer in `__all__` and emits `DeprecationWarning` if called; `test_strategy_roundtrip` proves Dhara payload round-trip.
**Documents:** Implements REQ-SM-001, REQ-SM-002, REQ-SM-007.

#### Integration Contract — Phase 1

- **Triggered from:** `worker_settle(action="apply")` → `mahavishnu/mcp/tools/worker_contract_tools.py:663` → `merge.merge_three_way(base, ours, theirs, label)`. New signature is backward-compatible: omitting `strategy` triggers default resolution.
- **Returns to / updates:** Same `MergeResult | MergeConflictError | MergeFailureError` return types from same module; no Dhara write; no OTel emission added in this phase. `merge_three_way_sync` is no longer importable from the module public surface.
- **Demonstrable by:** `pytest tests/unit/settle/test_merge_three_way.py::test_line_strategy_byte_equivalence tests/unit/settle/test_merge_strategy.py::test_strategy_roundtrip -v` passes.
- **Rollback signal:** Test fails or `pytest --cov=mahavishnu --cov-fail-under` dips below the 89% configured threshold in `pyproject.toml [tool.pytest] addopts`.
- **Observability added:** None in this phase — observability lands with the subprocess in Phase 2.

### Phase 2: Mergiraf shell-out driver

**Goal:** Implement `_merge_via_mergiraf` to invoke `mergiraf merge` with the same `(base, ours, theirs)` shape. **Correctly classify conflicts vs. fatals** (mergiraf exit semantics differ from `git merge-file`).
**Tasks:**
- Add `async def _merge_via_mergiraf(*, base, ours, theirs, label, binary)` to `mahavishnu/settle/merge.py`. Internal `tempfile.TemporaryDirectory(prefix="settle-mergiraf-")` writes three text files.
- **Validation gate (raised BEFORE subprocess spawn)**: if `binary is None`, raise `MergeDriverUnavailableError("mergiraf binary not on $PATH; install mergiraf or set merge_driver_default: 'line'")`. Never silently fall back.
- `asyncio.create_subprocess_exec(binary, "merge", base_path, ours_path, theirs_path, "-p", label, "--allow-parse-errors", ...)` with `stdout=PIPE`, `stderr=PIPE`. Capture **stderr unconditionally** (truncate to 4KB) and store on result payloads as `driver_warnings`.
- **Exit-code + content mapping** (mergiraf semantics differ from `git merge-file`):
  - Exit 0 + `<<<<<<<` markers in stdout → `MergeConflictError(merged=stdout_text, driver_warnings=stderr[:4096])`
  - Exit 0 + no conflict markers → `MergeResult(merged=stdout_text, conflict_count=0, driver_warnings=stderr[:4096])`
  - Exit 1 (input unreadable) OR Exit 2 (tree-sitter parse error) → `MergeFailureError(stderr_text)`
  - Conflict markers counted by counting `<<<<<<<` lines; reported as `conflict_count` on both `MergeResult` and `MergeConflictError`.
- Add `driver_warnings: str | None` field to `MergeResult` and `MergeConflictError`.
- OTel span `merge.semantic.invocations` with attributes `merge.driver`, `merge.exit_code`, `merge.conflict_count`, `merge.duration_ms`, `merge.has_driver_warnings`.
- OTel counter `merge.fallback_total` increments when default-resolution falls back from `SEMANTIC` to `LINE` (Phase 4 wiring).
- New `MergeDriverUnavailableError(Exception)` raised at the validation gate above.
- **Consumer catch-chain**: extend `mahavishnu/mcp/tools/worker_contract_tools.py:669-680` `try/except` to add `except MergeDriverUnavailableError` arm that surfaces an explicit error to the MCP caller (HTTP 500 with `ErrorCode.MERGE_DRIVER_UNAVAILABLE`). Without this arm the exception escapes as an uncaught error.
**Exit criteria:** `tests/integration/test_settle_merge_semantic_e2e.py` proves a real repo with non-overlapping function edits merges cleanly AND a real semantic conflict raises `MergeConflictError` (with markers in `merged` payload).
**Documents:** Implements REQ-SM-002, REQ-SM-003.

#### Integration Contract — Phase 2

- **Triggered from:** `merge_three_way(strategy=MergeStrategy.SEMANTIC)` or implicit default-resolution to `SEMANTIC`; consumer `worker_contract_tools.py:663` `try/except` re-raises as MCP error.
- **Returns to / updates:** OTel span recorded to the active tracer (currently the OTel exporter pipeline in `mahavishnu/observability/`); Dhara NOT touched in this phase. Consumer `try/except` at `worker_contract_tools.py:669-680` now has `MergeDriverUnavailableError` arm.
- **Demonstrable by:** `pytest tests/integration/test_settle_merge_semantic_e2e.py::test_non_overlapping_function_edits_merge_cleanly tests/integration/test_settle_merge_semantic_e2e.py::test_semantic_conflict_exits_zero_with_markers -v` pass — non-overlapping merges cleanly with `MergeResult(conflict_count=0)`; semantic conflict exits 0 but stdout contains `<<<<<<<` markers and produces `MergeConflictError`.
- **Rollback signal:** OTel export shows `merge.exit_code >= 1` rate > 5% across 1-hour window, OR `tests/integration/test_settle_merge_semantic_e2e.py` regresses, OR `driver_warnings` is non-empty for > 10% of invocations (indicates binary/grammar drift).
- **Observability added:** `mahavishnu.workflow.merge.semantic.duration_ms` and `mahavishnu.workflow.merge.semantic.exit_code` histogram + counter (under existing OTel schema `mahavishnu.workflow.*`); `merge.fallback_total` counter; `merge.has_driver_warnings` boolean attribute.

### Phase 3: Per-binding strategy + Dhara audit trail

**Goal:** Thread `merge_strategy: str | None` through `Binding` → `SettleRunRecord` → Dhara payload.
**Tasks:**
- Update `mahavishnu/settle/state_machine.py` `Binding` dataclass: add `merge_strategy: str | None = None` field.
- **Both edit sites required** (R1 finding): write side at `state_machine.py:122` (`SettleRunRecord.to_dict` emits `{"path", "base", "merge_strategy": str(strategy.value) if strategy else None}` per binding); read side at `state_machine.py:215-227` (`_parse_bindings` accepts the new field, coerces `MergeStrategy(raw)` when non-None, leaves `None` when absent — does NOT trip `_require_str_field` which is strict and would reject missing fields).
- Update `mahavishnu/settle/persistence.py::SettleRunRecord.to_dict()` to emit `merge_strategy` under each binding entry (forwarded from state_machine).
- Update `mahavishnu/mcp/tools/worker_contract_tools.py:663` to read per-binding strategy and forward to `merge.merge_three_way`.
- Add regression test `test_binding_strategy_roundtrip_pydantic_v2_compat` confirming `Binding(merge_strategy=MergeStrategy.SEMANTIC).to_dict() → from_dict() → Binding(merge_strategy=MergeStrategy.SEMANTIC)` (REQ-SM-007 + REQ-SM-004).
**Exit criteria:** New unit test asserts a mixed-strategy run (binding A `LINE`, binding B `SEMANTIC`) routes each binding to the right strategy.
**Documents:** Implements REQ-SM-004, REQ-SM-007.

#### Integration Contract — Phase 3

- **Triggered from:** `worker_settle(action="apply")` for any binding whose run record has a non-null `merge_strategy`.
- **Returns to / updates:** Dhara record at `settle/v1/{run_ref}` (managed by `mahavishnu/settle/persistence.py::persist_transition`); bindings array gains `merge_strategy` key.
- **Demonstrable by:** `pytest tests/unit/settle/test_state_machine.py::test_binding_strategy_roundtrip tests/unit/settle/test_state_machine.py::test_binding_strategy_roundtrip_pydantic_v2_compat tests/integration/settle/test_mixed_strategy_apply.py -v` passes; legacy records (no `merge_strategy` field) deserialize cleanly via `_parse_bindings`; Akosha search on the new field returns the persisted record (when `WebSocketInvocationsSubscriber` is operational — out of scope for this plan, see Known Limitation §10).
- **Rollback signal:** Test fails or `SettleRunRecord.from_dict` raises `ValidationError` on legacy records — must NOT happen because `from_dict` already tolerates missing optional fields (lines 148, 152, 216, 293).
- **Observability added:** OTel span `merge.binding_strategy` attribute on every `merge_three_way` invocation; structured log line `merge.applied` with `binding_count`, `strategy_count_by_value` aggregates.

### Phase 4: Opt-in default + loud-failure semantics + operator escape hatch (NO default-flip)

**Goal:** Add mergiraf as an opt-in strategy with hard-fail at startup when required, and runtime fallback to `LINE` when optional. **The global default stays `"line"`** — flipping to `"mergiraf"` is deferred to a follow-up plan after one release cycle of opt-in telemetry (mirrors `minimax27` plan's M1 deprecation cycle where `zai` was kept as non-default for one release). This avoids the operator-trust erosion of flipping defaults without a deprecation window.
**Tasks:**
- Add `merge_driver_default: str = "line"` (NOT "mergiraf" — see Decision Rule §9 #6) to `MahavishnuSettings` in `mahavishnu/core/config.py`.
- Add `merge_driver_required: bool = False` to `MahavishnuSettings` (replaces the deprecated `MAHAVISHNU_REQUIRE_MERGE_DRIVER` env var — Oneiric layered config is the canonical surface; the env var remains as a transient override for `merge_driver_required` for one release then removed).
- **Startup guard in `MahavishnuApp._init_observability`** (NOT inside `merge_three_way` — R3 #2 critical finding: deferred-to-first-use means app boots green and crashes on first apply). When `merge_driver_required == True` and `_MERGIRAF_BIN is None`, raise `MergeDriverUnavailableError` during app init. Operator sees the failure at process start, not at first worker run.
- **Runtime guard** in `merge.merge_three_way` default-resolution: if `merge_driver_default == "mergiraf"` and binary missing:
  - Log `WARNING merge.semantic.unavailable` and increment OTel counter `merge.fallback_total`.
  - Fall through to `LINE` strategy; surface `MergeResult(strategy_used=MergeStrategy.LINE, driver_warning="mergiraf missing")`.
- New `scripts/check_merge_driver.py` — operator-facing pre-flight. Asserts (REQ-SM-008):
  - `which mergiraf` exits 0.
  - `mergiraf --version` parses (semver-like string).
  - **`tree-sitter-python` grammar loadable** — probed via `mergiraf list-languages | grep -q Python` (R4 #C: tree-sitter grammars not packaged with the binary). If absent, exit 1 with remediation hint: `brew install mergiraf  # Homebrew bundles grammars; for cargo binstall, run: mergiraf install-grammar python`.
  - **`git --version` reports ≥ 2.38** (R4 unstated dependency — `git merge-tree --write-tree` is a Phase 6 candidate but the version is cheap to verify now).
- Add the script to `mahavishnu health` output. Wire into `/health` aggregate per wire-up contract (REQ-SM-009):
  - `merge_driver.available` (bool)
  - `merge_driver.binary` (path or null)
  - `merge_driver.version` (string or null)
  - `merge_driver.grammars` (list of available grammars)
  - **`merge_driver.degraded_since`** (ISO timestamp or null — set when `merge.fallback_total` > 0 since last healthy; cleared on next healthy probe — R3 #3: without this, fallback fires silently)
- **Tmux worker panes** (R4 #D): survive MCP process restarts and only re-probe on the next worker launch. Document in Phase 4 Observability notes; tmux-pane lifecycle is out of scope for the startup guard.
**Exit criteria:** Operator can confirm mergiraf is wired by running `mahavishnu health --section merge_driver` (output shows available/binary/version/grammars/degraded_since); `merge_driver_required: True` with missing binary raises at startup, not first-apply; `merge.fallback_total` increments on every runtime fallback; existing settle runs continue to work even when mergiraf disappears mid-process.
**Documents:** Implements REQ-SM-003, REQ-SM-005, REQ-SM-008, REQ-SM-009.

#### Integration Contract — Phase 4

- **Triggered from:** (a) `MahavishnuApp._init_observability` startup with `merge_driver_required == True` and binary missing; (b) any `merge_three_way` invocation under default settings with mergiraf missing from `$PATH`.
- **Returns to / updates:** `MahavishnuSettings.merge_driver_default` and `merge_driver_required` persisted via Oneiric layered config (defaults → `settings/mahavishnu.yaml` → `settings/local.yaml` → env `MAHAVISHNU_MERGE_DRIVER_DEFAULT` / `MAHAVISHNU_MERGE_DRIVER_REQUIRED`); `/health` aggregates per-section detail under `merge_driver.{available, binary, version, grammars, degraded_since}`; `merge.fallback_total` OTel counter.
- **Demonstrable by:** `mahavishnu health` includes `merge_driver: {available: true, binary: "/usr/local/bin/mergiraf", version: "0.19.1", grammars: ["Python", "Rust", "Go"], degraded_since: null}` in JSON output when healthy; `merge_driver: {available: false, ..., degraded_since: "2026-09-10T..."}` after a runtime fallback.
- **Rollback signal:** `merge_driver_default: "line"` override in `settings/local.yaml` is the default-state; `merge_driver_required: False` disables the hard error; `MAHAVISHNU_MERGE_DRIVER_REQUIRED=0` env override for transient disablement.
- **Observability added:** `mahavishnu.health.merge_driver.available` boolean probe on `/health`; OTel span `merge.driver.probe` on first call (lazy probe per Phase 1); OTel counter `merge.fallback_total`; `/health` `merge_driver.degraded_since` timestamp.

### Phase 5: git-merge-tree --name-only diagnostic channel (DEFERRED — see Decision Rule §9 #2)

**Goal:** Add structured conflict-path reporting alongside the SEMANTIC merge without changing the merge content engine.
**Status:** **Deferred** — Phase 5 only ships after Phase 4 has 30 days of `merge.fallback_total` and `merge.semantic.duration_ms` telemetry confirming p99 < 50ms. Until then, REQ-SM-006 stays in `draft`; the scratch-repo perf risk (R-B: 500ms-1s in practice, not the 200ms claimed in earlier drafts) is too high to ship blind. The Phase 6 candidate to swap to `git merge-tree --write-tree` (over file contents, no scratch repo) is the likely unblocker once we have telemetry.
**Tasks (when unblocked):**
- Add `MergeDiagnostics` dataclass: `conflicted_paths: list[str]`, `diagnostics_source: Literal["git-merge-tree-name-only"] = "git-merge-tree-name-only"`, `duration_ms: float`, `error: str | None = None`.
- In `_merge_via_mergiraf`, after the mergiraf subprocess completes (success OR conflict), run `git merge-tree --name-only` against the same three committed files in a scratch git repo created in the tempdir. This requires `git init -q` plus three `git write-tree` / `git mktree`-equivalent calls or simpler: commit three blobs to a scratch repo and `git merge-tree --name-only <commit-1> <commit-2>`.
- **Diagnostics failure semantics** (R3 #5): if `git-merge-tree --name-only` subprocess fails (non-zero exit, timeout, `git` missing), the merge result is **still returned successfully**; `MergeDiagnostics.error: str | None` is populated; no error propagates to the caller. Diagnostics is observability, not a merge-engine dependency.
- Extend `MergeResult` and `MergeConflictError` payloads with `diagnostics: MergeDiagnostics | None` — benign payload add (existing consumers ignore fields they don't read).
**Exit criteria:** Audit test asserts `diagnostics.conflicted_paths == ["src/foo.py"]` for a single-file semantic conflict; diagnostic-failure test asserts `diagnostics.error` populated but merge returns success.
**Documents:** Implements REQ-SM-006.

#### Integration Contract — Phase 5

- **Triggered from:** `_merge_via_mergiraf` after the mergiraf subprocess completes (success or conflict path) AND `MAHAVISHNU_DIAGNOSTICS_ENABLED != "0"` (operator kill-switch).
- **Returns to / updates:** `MergeResult.diagnostics` (success path) or `MergeConflictError.diagnostics` (conflict path) — both nullable. No Dhara write; audit trail surfaces in the OTel span `merge.diagnostics.conflicted_paths` as a string list attribute.
- **Demonstrable by:** `pytest tests/unit/settle/test_merge_diagnostics.py tests/unit/settle/test_merge_diagnostics.py::test_diagnostics_subprocess_failure_still_returns_success -v` passes.
- **Rollback signal:** (a) `MAHAVISHNU_DIAGNOSTICS_ENABLED=0` env var disables diagnostic subprocess entirely (operator kill-switch — R2 finding: tuning observation isn't operator-actionable); (b) Phase 6 candidate is `git merge-tree --write-tree` over file contents directly without the scratch repo if perf budget is exceeded.
- **Observability added:** `mahavishnu.workflow.merge.diagnostics.duration_ms` histogram; per-result counter `merge.diagnostics.conflict_count`.

## 6. Required Code Changes

- [ ] `mahavishnu/settle/merge.py` — add `MergeStrategy`, `MergeDriverUnavailableError`, `MergeDiagnostics`, `_merge_via_mergiraf`, OTel span; thread `strategy` parameter through `merge_three_way`; **lazy** first-call `_MERGIRAF_BIN` probe (Phase 1+2).
- [ ] `mahavishnu/settle/merge.py` — deprecate `merge_three_way_sync` → `_merge_three_way_sync_internal` with `DeprecationWarning` (Phase 1, R1 #1).
- [ ] `mahavishnu/settle/merge.py` — `MergeResult` and `MergeConflictError` gain `driver_warnings: str | None`; stderr captured unconditionally and truncated to 4KB (Phase 2, R3 #4).
- [ ] `mahavishnu/settle/state_machine.py` — add `merge_strategy: str | None = None` to `Binding`; round-trip in `to_dict`/`from_dict`; **both edit sites required** (write side line 122, read side `_parse_bindings` lines 215-227) (Phase 3, R1 #2).
- [ ] `mahavishnu/settle/persistence.py` — extend Dhara payload schema to round-trip `merge_strategy` (Phase 3).
- [ ] `mahavishnu/mcp/tools/worker_contract_tools.py` — read per-binding strategy at line 663, forward to `merge_three_way` (Phase 3).
- [ ] `mahavishnu/mcp/tools/worker_contract_tools.py` — extend `try/except` at lines 669-680 with `except MergeDriverUnavailableError` arm returning HTTP 500 + `ErrorCode.MERGE_DRIVER_UNAVAILABLE` (Phase 2, R3 #1).
- [ ] `mahavishnu/core/config.py` — add `merge_driver_default: str = "line"` (NOT "mergiraf" — see Decision Rule §9 #6) and `merge_driver_required: bool = False` to `MahavishnuSettings`; Oneiric config-load path picks up `MAHAVISHNU_MERGE_DRIVER_DEFAULT` and `MAHAVISHNU_MERGE_DRIVER_REQUIRED` env vars (Phase 4).
- [ ] `mahavishnu/app.py` — `MahavishnuApp._init_observability` invokes startup guard: when `merge_driver_required == True` and `_MERGIRAF_BIN is None`, raise `MergeDriverUnavailableError` at startup (NOT deferred to first apply) (Phase 4, R3 #2 Critical).
- [ ] `scripts/check_merge_driver.py` — new operator-facing pre-flight. Asserts binary on PATH, version parses, **`tree-sitter-python` grammar loadable**, **`git --version` ≥ 2.38** (Phase 4, REQ-SM-008, R4 #C + R4 unstated dependency).
- [ ] `mahavishnu/health/` — extend `/health` per-section aggregate to include `merge_driver.{available, binary, version, grammars, degraded_since}` (Phase 4, REQ-SM-009, R3 #3).
- [ ] `mahavishnu/observability/` — add OTel counter `merge.fallback_total` (Phase 2+4, R3 #3).
- [ ] `mahavishnu/settle/merge.py` — `MergeDiagnostics` adds `error: str | None`; diagnostic subprocess failure → merge still succeeds with `diagnostics.error` populated (Phase 5, R3 #5) — DEFERRED per §9 Decision Rule #2.
- [ ] `mahavishnu/settle/merge.py` — `MAHAVISHNU_DIAGNOSTICS_ENABLED=0` env var disables diagnostic subprocess entirely (Phase 5, R2 Rollback operator knob).
- [ ] `tests/unit/settle/test_merge_strategy.py` — new unit tests covering: LINE byte-equivalence, SEMANTIC roundtrip, default-resolution matrix, mergiraf-not-found loud-failure, exit-code matrix (0+markers / 0+clean / 1 / 2), `driver_warnings` capture, serialization round-trip (Phase 1-2).
- [ ] `tests/integration/test_settle_merge_semantic_e2e.py` — new integration test, scratch git repo, non-overlapping function merge AND semantic-conflict-marker detection (Phase 2, R4 blind-spot).
- [ ] `tests/integration/settle/test_mixed_strategy_apply.py` — mixed-strategy per-binding apply (Phase 3).
- [ ] `tests/unit/settle/test_state_machine.py::test_binding_strategy_roundtrip_pydantic_v2_compat` — Dhara payload round-trip regression (Phase 3, REQ-SM-007).
- [ ] `docs/plans/PLAN_INDEX.md` — register plan via `scripts/regenerate_plan_index.py` after promotion.
- [ ] `docs/plans/2026-09-10-settle-semantic-merge-default-flip.md` — **follow-up plan stub** (created after Phase 4 ships + 30 days telemetry) to flip `merge_driver_default` from `"line"` to `"mergiraf"` with operator comms.

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `pytest tests/unit/settle/ tests/integration/settle/ -v` | All settle tests pass | CI artifact |
| `pytest --cov=mahavishnu --cov-fail-under=89` | Coverage at/above threshold | CI artifact |
| `crackerjack run` | Ruff + mypy + ty + bandit clean | CI artifact |
| `python -c "from mahavishnu.settle.merge import merge_three_way; import inspect; print(inspect.signature(merge_three_way))"` | Signature shows `strategy: MergeStrategy | None = None` added | Operator shell |
| `pytest tests/unit/settle/test_merge_strategy.py::test_strategy_roundtrip -v` | Dhara payload round-trip proves `Binding(merge_strategy=MergeStrategy.SEMANTIC) → to_dict → from_dict → equal` (REQ-SM-007) | CI artifact |
| `pytest tests/integration/test_settle_merge_semantic_e2e.py::test_exit_code_matrix -v` | Asserts the mergiraf exit-code matrix: (a) non-overlapping edit → exit 0, no markers → `MergeResult(conflict_count=0)`; (b) semantic conflict → exit 0, `<<<<<<<` in stdout → `MergeConflictError`; (c) input unreadable → exit 1 → `MergeFailureError`; (d) tree-sitter parse error → exit 2 → `MergeFailureError` (R4 blind-spot) | CI artifact |
| `pytest tests/unit/settle/test_merge_strategy.py::test_missing_binary_with_required_flag_raises_at_startup -v` | `MahavishnuApp._init_observability` raises `MergeDriverUnavailableError` when `merge_driver_required=True` and binary missing — NOT deferred to first apply (R3 #2 Critical) | CI artifact |
| `pytest tests/unit/settle/test_merge_strategy.py::test_runtime_fallback_increments_counter_and_sets_degraded_since -v` | When `merge_driver_default="mergiraf"` (non-required) and binary missing, runtime falls back to LINE, OTel `merge.fallback_total` increments, `/health` `merge_driver.degraded_since` set (R3 #3) | CI artifact |
| `pytest tests/unit/settle/test_state_machine.py::test_binding_strategy_roundtrip_pydantic_v2_compat -v` | `Binding(merge_strategy="semantic") → Dhara → from_dict → Binding(merge_strategy=MergeStrategy.SEMANTIC)` (REQ-SM-004 + REQ-SM-007) | CI artifact |
| `python scripts/check_merge_driver.py` | Exits 0 with `tree-sitter-python` present; exits 1 with remediation hint when grammar absent (R4 #C) | Operator shell |
| `python scripts/check_merge_driver.py --require git>=2.38` | Exits 0 on supported git; exits 1 with hint on older versions (R4 unstated dependency) | Operator shell |
| `mahavishnu health` | JSON includes `merge_driver: {available, binary, version, grammars, degraded_since}` | CLI output |
| `pytest tests/integration/test_settle_merge_semantic_e2e.py::test_non_overlapping_function_edits_merge_cleanly -v` | Test passes; merged output has 0 `<<<<<<<` markers | CI artifact |

## 8. Risks

| ID | Risk | Likelihood | Mitigation |
|---|---|---|---|
| R-A | Mergiraf CLI surface changes (added/removed flags) break `_merge_via_mergiraf` | Low (clap-anchored CLI, semver-stable) | Pin CLI invocation in a single helper; add property test asserting byte-equivalence against `mergiraf --version` lock at test time |
| R-B | Scratch-repo setup for `git-merge-tree --name-only` (Phase 5) costs 500ms-1s in practice, not the 200ms originally claimed (R4 reviewer observation against typical container IO) | Medium-High | Phase 5 DEFERRED per §9 Decision Rule #2; Phase 6 candidate is `git merge-tree --write-tree` (no scratch repo, no per-invocation `git init` cost). Telemetry gate: only unblock after 30 days of `merge.semantic.duration_ms` p99 < 50ms confirms the budget |
| R-C | Mergiraf binary without `tree-sitter-python` (or other language) grammar fatal-errors every file of that language (R4 #C: Homebrew bundles grammars; `cargo binstall mergiraf` and most CI images ship only the binary) | High for container/CI deployments | `scripts/check_merge_driver.py` probes grammar availability (REQ-SM-008); `/health` surfaces `merge_driver.grammars`; `merge_driver_required=True` raises at startup if required grammars absent; doc-block in `settings/CONFIGURATION.md` recommends Homebrew install path for container deployments |
| R-D | Tmux worker panes survive MCP process restarts; the startup guard runs once per process, so a long-lived tmux pane in a stale `merge_driver_required=True` env keeps using the old probe until relaunch (R4 #D) | Medium for tmux-heavy deployments | Document in Phase 4 Observability: tmux panes must relaunch to pick up new `merge_driver_required` setting. Mitigation scope: out of plan; tracked for follow-up if operator reports it. Alternative: re-probe per worker launch instead of per process — considered but rejected as cost > value for v1 |
| R-E | Operator override `merge_driver_default: "line"` causes silent behavior change | Low (it's the default) | Loud `WARNING` on default override; `/health` shows actual strategy used by last run |
| R-F | Dhara payload schema migration breaks legacy records (Phase 3) | Low | `from_dict` tolerates missing fields already at lines 148, 152, 216, 293 of `state_machine.py` |
| R-G | `MAHAVISHNU_MERGE_DRIVER_DEFAULT` env var name collides with future env conventions | Low | Reserved prefix per `.claude/decisions/`; documented in `docs/CONFIGURATION.md` |
| R-H | Runtime fallback to `LINE` fires silently if `/health` aggregate doesn't surface it (R3 #3) | High without `degraded_since`; Low with mitigation | `merge_driver.degraded_since` ISO timestamp set on `/health` whenever `merge.fallback_total` > 0 since last healthy; OTel counter `merge.fallback_total` exposed for alerting |
| R-I | `merge_three_way_sync` left as dead code if not deprecated (R1 #1) | Medium without deprecation; Low with mitigation | Phase 1 renames to `_merge_three_way_sync_internal` + `DeprecationWarning`; removed from `__all__` |
| R-J | Consumer `try/except` in `worker_contract_tools.py` doesn't catch `MergeDriverUnavailableError`, exception escapes as uncaught error (R3 #1) | High without extension; Low with mitigation | Phase 2 explicitly extends catch chain at lines 669-680 with `except MergeDriverUnavailableError → HTTP 500 + ErrorCode.MERGE_DRIVER_UNAVAILABLE` |
| R-K | Default-flip premature erodes operator trust (R4 contrarian) — flipping `merge_driver_default` to `"mergiraf"` in same delivery as the opt-in means operators can't roll back without code change | Medium | Phase 4 ships opt-in only; default stays `"line"`; follow-up plan `2026-09-10-settle-semantic-merge-default-flip.md` flips after 30-day telemetry cycle (mirrors `minimax27` plan's M1 → M2 deprecation cycle) |
| R-L | Mergiraf exit-code semantics differ from `git merge-file` (R4 reviewer blind spot): real semantic conflicts exit 0, NOT exit 1; mis-classification routes conflicts into `MergeFailureError` (fatal) and bypasses `MergeConflictError` (recoverable). Operator pager fires on real conflicts | High without mitigation; Low with mitigation | Phase 2 conflict detection scans stdout for `<<<<<<<` markers regardless of exit code; exit code determines fatal-vs-recoverable (1, 2 = fatal; 0 = recovered output). Validation Matrix asserts all four cases (0+markers, 0+clean, 1, 2) |
| R-M | `git` dependency unstated — mergiraf and `git merge-tree` both require git on `$PATH`; minimal containers may lack git ≥ 2.38 (R4 unstated dependency) | Medium | `scripts/check_merge_driver.py` asserts `git --version` ≥ 2.38 (REQ-SM-008); `/health` surfaces git version alongside `merge_driver.version` |

## 9. Decision Rule

This plan is "done enough" when:

1. Phase 1-4 are landed and the integration tests in the Validation Matrix pass.
2. Phase 5 lands behind `MAHAVISHNU_DIAGNOSTICS_ENABLED=0` operator kill-switch (default-enabled but off in CI) and stays off by default until 30 days of observability confirms the diagnostic channel is <50ms p99 AND `git merge-tree --write-tree` swap (Phase 6 candidate) is implemented OR ruled out.
3. `python scripts/audit_orphans.py` reports no newly-added symbols with zero callers (every merge_strategy-handling symbol has at least one caller).
4. `python scripts/audit_requirements.py --json` exits 0 — every REQ-SM-001..REQ-SM-009 has either an inline marker, docstring marker, or test marker.
5. `mahavishnu health` JSON output includes the `merge_driver.{available, binary, version, grammars, degraded_since}` section.
6. **Before the follow-up default-flip plan (`2026-09-10-settle-semantic-merge-default-flip.md`) ships**: both mergiraf binary AND required tree-sitter grammars (at least Python; repo language detection determines others) are available in every target deployment container, confirmed by `scripts/check_merge_driver.py` running in CI against the production image. This is the operator-trust precondition for the deprecation cycle (mirrors `minimax27` plan's M1 → M2 transition gate).

If any of (1)-(3) is unmet at scope pressure, the plan is `partial` and the unmet items move to a follow-up plan under the same topic.

## 10. Known Limitation

The Akosha search fallback ("No websocket invocations indexed yet") observed during this plan's authoring means cross-session observability tests in Phase 5's Demonstrable-by field are gated on the `WebSocketInvocationsSubscriber` fix in `akosha/main.py:243-249` — out of scope for this plan but worth flagging.

## 13. Relationship to Other Plans

| Plan | Relationship |
|---|---|
| `docs/plans/2026-05-10-minimax27-provider-migration.md` | **Precedent for deprecation cycle.** MiniMax plan kept `zai` as a non-default fallback for one release cycle before flipping to `MiniMax-M3` as default. Phase 4 follows the same pattern: mergiraf ships as opt-in (default stays `"line"`) for one release, then follow-up plan `2026-09-10-settle-semantic-merge-default-flip.md` flips default after telemetry gate |
| `.claude/decisions/wire-up-contract.md` | **Template policy.** Every phase's Integration Contract follows the Triggered-from / Returns-to / Demonstrable-by / Rollback-signal / Observability-added structure mandated by this decision |
| `docs/plans/2026-08-31-bodai-mcp-plist-stale-cli-subcommand.md` | **Cross-ecosystem precedent for operator-trust erosion.** launchd plist refactor broke CLI subcommand — silent 30s timeout. Reinforces R-K's argument that flipping defaults without operator comms erodes trust. Cited as the cautionary tale for the deprecation cycle in §9 Decision Rule #6 |
| `docs/plans/mahavishnu-phase3-plan-defect-phase2-foundation.md` | **Precedent for orphan-detection gate.** Phase 3 streaming-tar assumed `storage_io.py`/`cache.py` existed; none did. Reinforces §9 Decision Rule #3: `audit_orphans.py` must run before declaring features complete |
| Follow-up: `docs/plans/2026-09-10-settle-semantic-merge-default-flip.md` | **Created after Phase 4 ships + 30 days telemetry.** Flips `merge_driver_default` to `"mergiraf"` with operator comms and explicit rollback via `merge_driver_default: "line"` override |
| Follow-up: Phase 6 (`git merge-tree --write-tree`) | **Diagnostic-channel unblocker.** Replaces scratch-repo setup with `git merge-tree --write-tree` over file contents directly. Tracked under Phase 6 candidate in Non-Goals §3 |

## 14. Review Log

This plan was reviewed by a 4-person reviewer posse (2026-09-10, parallel dispatch with non-overlapping lenses per `multi-agent-review-catches-blind-spots` pattern). Total: **1 Critical + 13 Major + 4 Minor = 18 findings** consolidated into the edit set applied 2026-09-10.

| Reviewer | Lens | Findings |
|---|---|---|
| **R1** | Architecture protocol | 5 findings: sync/async asymmetry (Major), Binding round-trip two-edit site requirement (Major), line-142 cite wrong (Minor), "single consumer" wording (Minor), eager vs lazy probe (Minor) |
| **R2** | Wire-up contract compliance | 4 Compliant + 1 gap: Phase 5 Rollback signal was tuning observation not operator-actionable → fixed via `MAHAVISHNU_DIAGNOSTICS_ENABLED=0` env var |
| **R3** | Silent-failure detection | 1 Critical (startup-guard timing deferred-to-first-use) + 4 Major (raise ordering + consumer catch, fallback not on /health, stderr discarded on exit-0, diagnostics failure mode unspecified) + 1 cross-cutting consumer-catch-chain flag |
| **R4** | Risk / contrarian | 1 reviewer-blind-spot (Critical-ish: mergiraf exit codes differ from git's, conflict detection must scan stdout for `<<<<<<<` markers) + 6 Major (enum serialization drift, Phase 5 perf, tree-sitter grammar missing, git dependency unstated, premature default-flip, plus tmux panes Minor) + 3 template-drift (Missing §13/§14/§15) |

The most consequential finding was **R4's reviewer blind-spot on mergiraf exit semantics**: real semantic conflicts exit 0 (not 1). The Phase 2 conflict-detection logic was rewritten to scan stdout for `<<<<<<<` markers regardless of exit code. This finding + R3's "stderr discarded on exit-0" both attacked the same false premise (exit-0 = clean merge) and were fixed by a single change.

## 15. Progress Log

Implementation progress against the plan's REQ-SM-001..REQ-SM-009 and phase deliverables. Updated as each phase lands.

| Phase | REQ IDs | Status | Date | Evidence |
|---|---|---|---|---|
| Phase 1 | REQ-SM-001, REQ-SM-002, REQ-SM-007 | Done | 2026-09-10 | `merge.py` (+162 lines): `MergeStrategy(StrEnum)`, lazy `_MERGIRAF_BIN` probe, `_resolve_default_strategy`, `_merge_via_mergiraf` Phase 2 stub, `merge_three_way(strategy=...)` parameter; `_merge_three_way_sync_internal` rename + `merge_three_way_sync` deprecation shim; `__all__` excludes deprecated sync surface. `tests/unit/settle/test_settle_merge.py`: 6 async test calls updated to pass `strategy=MergeStrategy.LINE` explicitly (preserves Phase 0 test intent now that default resolution picks SEMANTIC when mergiraf on $PATH). `tests/unit/settle/test_merge_strategy.py` (new, 132 lines): 6 regression tests covering REQ-SM-007 round-trip, `__str__` returns value not repr, JSON round-trip, `merge_three_way_sync` emits `DeprecationWarning`, `merge_three_way_sync` absent from `__all__`. Verification: 27 tests pass (21 legacy + 6 new); 8 expected `DeprecationWarning`s from legacy sync tests; ruff check clean; ruff format clean on Phase 1 changes (one pre-existing format drift on `merged_with_markers` literal in `test_settle_merge.py:84` not introduced by Phase 1); mypy clean on `merge.py`. |
| Phase 2 | REQ-SM-002, REQ-SM-003 | Done | 2026-09-10 | `merge.py`: `MergeDriverUnavailableError(Exception)` added; `MergeResult` and `MergeConflictError` gain `driver_warnings: str | None` field; `_merge_via_mergiraf` implements the mergiraf subprocess with tempfile scratch dir, OTel span emission via `trace.get_tracer(__name__)`, stderr truncated to 4KB, conflict marker counting, and exit-code + content classification. **R4 marker-first fix**: branch order is "markers in stdout → `MergeConflictError`; markers absent + exit 0 → `MergeResult`; markers absent + non-zero exit → `MergeFailureError`". Empirically `mergiraf 0.19.1` exits 1 with markers (the plan claimed exit 0) — the marker-first branch handles both shapes; documented in module + helper docstrings. `merge_three_way` strategy branch now raises `MergeDriverUnavailableError` (not `NotImplementedError`) at the validation gate before subprocess spawn. `worker_contract_tools.py:669-696`: `try/except` chain extended with `except MergeDriverUnavailableError` arm surfacing `error_code: "MHV-313"`. `errors.py`: `MERGE_DRIVER_UNAVAILABLE = "MHV-313"` added to `ErrorCode` (external-integration range). `tests/unit/settle/test_merge_strategy.py` (+12 tests): `test_mergiraf_markers_in_stdout_raises_conflict_error`, `test_mergiraf_exit_zero_clean_returns_result`, `test_mergiraf_fatal_exit_raises_failure` (parametrized 1/2/127), `test_mergiraf_captures_driver_warnings_on_success`, `test_mergiraf_captures_driver_warnings_on_conflict`, `test_mergiraf_truncates_driver_warnings_at_4kb`, `test_merge_three_way_semantic_raises_driver_unavailable_when_binary_missing`, `test_merge_three_way_line_strategy_does_not_resolve_mergiraf`, `test_merge_result_default_driver_warnings_is_none`, `test_merge_conflict_error_default_driver_warnings_is_none`, `test_merge_driver_unavailable_error_is_exception`, plus the existing `__all__` test updated to assert `MergeDriverUnavailableError` is exposed. `tests/integration/test_settle_merge_semantic_e2e.py` (new, ~180 lines, gated on `mergiraf` on `$PATH`): `test_non_overlapping_function_edits_merge_cleanly` (inserts at distinct anchors: `baz` between `foo`/`bar`, `qux` after `bar` — line-merge would conflict; mergiraf resolves cleanly with exit 0), `test_semantic_conflict_exits_with_markers` (same function edited differently — markers in stdout regardless of exit code), `test_semantic_clean_merge_preserves_ours_in_tempfile` (validates tempfile cleanup). Verification: 43 tests pass (40 unit + 3 integration); ruff check + format clean on all 5 Phase 2 files; mypy clean on `merge.py` (pre-existing mypy error on `worker_contract_tools.py:234` is unrelated to Phase 2 — confirmed by `git stash` round-trip). |
| Phase 3 | REQ-SM-004, REQ-SM-007 | Done | 2026-09-10 | `state_machine.py`: `Binding` dataclass gains `merge_strategy: str | None = None` field (REQ-SM-004). Both edit sites wired (R1 finding): `to_dict` at the bindings list-comprehension emits `merge_strategy: b.merge_strategy if isinstance(b.merge_strategy, str) else None` (write side); `_parse_bindings` at the binding validation block accepts the new field, calls `MergeStrategy(raw)` to validate it's a known enum value (raises `ValidationError` on unknown strings), leaves `None` when absent — does NOT use `_require_str_field` so legacy records (no `merge_strategy` key) deserialize cleanly via `None` default. `worker_contract_tools.py:664-681`: per-binding strategy now read from `binding.merge_strategy` (str | None), coerced via `MergeStrategy(binding.merge_strategy)` to a `MergeStrategy | None` enum (or `None` for default resolution), forwarded as `strategy=` to `merge_three_way`. Phase 2 `MergeDriverUnavailableError` catch arm covers per-binding SEMANTIC failures. `tests/unit/mcp/test_settle_state_machine.py` (+7 tests): `test_binding_merge_strategy_defaults_to_none`, `test_binding_accepts_merge_strategy_enum` (verifies StrEnum values are stored as strings), `test_binding_strategy_roundtrip` (REQ-SM-007 pin: `Binding(merge_strategy=MergeStrategy.SEMANTIC).to_dict()` writes `"semantic"`, NOT `"MergeStrategy.SEMANTIC"`), `test_binding_strategy_roundtrip_pydantic_v2_compat` (REQ-SM-007 + REQ-SM-004 mixed-strategy record round-trip), `test_binding_legacy_record_without_merge_strategy` (forward-compat: pre-Phase-3 records deserialize), `test_binding_invalid_merge_strategy_raises` (typo'd value `"Semantic"` rejected), `test_binding_non_string_merge_strategy_raises` (integer / bool / dict rejected). `tests/unit/settle/test_settle_merge.py` (+3 tests): `test_mixed_strategy_apply_routes_per_binding` (binding A `LINE` + binding B `SEMANTIC` both merge cleanly via patched `merge_three_way`), `test_mixed_strategy_apply_forwards_per_binding_strategy_arg` (the **Phase 3 exit criterion**: inspects `merge_three_way.call_args` to assert binding A gets `strategy=MergeStrategy.LINE` and binding B gets `strategy=MergeStrategy.SEMANTIC`), `test_mixed_strategy_apply_default_resolution_when_binding_omits` (binding with `merge_strategy=None` forwards `strategy=None` to trigger Phase 1 default resolution). Verification: 82 tests pass (was 43 pre-Phase-3 — 39 new tests); 8 expected `DeprecationWarning`s from legacy sync tests; ruff check + format clean on all 4 Phase 3 files (one pre-existing format drift on `merged_with_markers` literal in `test_settle_merge.py:91` not introduced by Phase 3); mypy error on `state_machine.py:167` is pre-existing (confirmed via `git stash` round-trip — error was at line 149 in the original, the line shifted due to Phase 3 additions). |
| Phase 4 | REQ-SM-003, REQ-SM-005, REQ-SM-008, REQ-SM-009 | Done | 2026-09-10 | `config.py`: `merge_driver_default: str = "line"` (NOT "mergiraf" — Decision Rule §9 #6) and `merge_driver_required: bool = False` added to `MahavishnuSettings`; env vars `MAHAVISHNU_MERGE_DRIVER_DEFAULT` / `MAHAVISHNU_MERGE_DRIVER_REQUIRED` bind via `model_config = SettingsConfigDict(env_prefix="MAHAVISHNU_", env_nested_delimiter="__")`. `merge.py`: `set_merge_driver_runtime_config(*, default, required)` callable for the bootstrap to install; `_MERGE_DRIVER_RUNTIME_CONFIG` module-level state; `_resolve_default_strategy` reads the config — when `default == "mergiraf"` and binary missing, log `WARNING merge.semantic.unavailable`, increment `merge.fallback_total` OTel counter (new `Counter` on per-module meter), lazily stamp `mark_merge_driver_fallback()` on `core.health`. `MergeResult` and `MergeConflictError` gain `strategy_used: MergeStrategy | None = None` (Phase 4 surface contract — actual strategy that ran) and `driver_warning: str | None = None` (Phase 4 fallback indicator, distinct from Phase 2's stderr `driver_warnings`). `bootstrap.py`: new `_install_merge_driver_runtime_config(app)` helper called at the top of `init_observability`; when `merge_driver_required == True` AND `merge_driver_default == "mergiraf"` AND `_MERGIRAF_BIN is None`, raises `MergeDriverUnavailableError` AT PROCESS START (R3 #2 Critical — operator sees the failure in the boot log, NOT deferred to first apply). `core/health.py`: new `merge_driver_health()` function returning `{available, binary, version, grammars, degraded_since}` per REQ-SM-009; `mark_merge_driver_fallback()` mutates module-level `_DEGRADED_SINCE` timestamp; `_probe_mergiraf_version` and `_probe_mergiraf_grammars` subprocess wrappers with timeout/error guards. The `readiness()` aggregate now includes `merge_driver` in its payload. `scripts/check_merge_driver.py` (new, executable, 250 lines): operator-facing pre-flight script implementing REQ-SM-008. Checks `which mergiraf` → `mergiraf --version` → tree-sitter-python grammar via `mergiraf languages | grep -q Python` (R4 #C) → `git --version >= 2.38` (R4 unstated dependency for Phase 6 `git merge-tree --write-tree`). Hard failures (binary missing, version unparseable, git too old) exit 1 with remediation hint; tree-sitter grammar absent is a soft warning unless `--strict`. `--json` emits machine-readable JSON. `tests/unit/settle/test_merge_strategy.py` (+9 tests): `test_missing_binary_with_required_flag_raises_at_startup` (R3 #2 Critical), `test_startup_guard_does_not_fire_when_binary_present`, `test_startup_guard_skipped_when_required_false`, `test_runtime_fallback_increments_counter_and_sets_degraded_since` (R3 #3), `test_runtime_fallback_sets_driver_warning_field`, `test_runtime_fallback_does_not_set_driver_warning_for_explicit_strategy`, `test_merge_result_strategy_used_set_for_semantic`, `test_merge_conflict_error_strategy_used_set_for_semantic`, plus 3 supporting tests. `tests/unit/test_check_merge_driver.py` (new, 14 tests): all four checks at ok / missing / warning / error states, `--strict` flag, `--json` output, hard-failure exit code. Verification: 105 tests pass (was 82 pre-Phase-4 — 23 new tests including 14 from `test_check_merge_driver.py` + 9 from `test_merge_strategy.py`); ruff check + format clean on all 8 Phase 4 files; mypy errors on `engines/agno_adapter_impl.py:169` (pre-existing in unrelated file) and `core/health.py:809` were resolved during Phase 4 work. Real mergiraf run: `python scripts/check_merge_driver.py` → `checks_passed=4/4`. |
| Phase 5 (DEFERRED) | REQ-SM-006 | Pending (gated on §9 #2 telemetry) | — | — |
| Follow-up: default-flip | — | Not yet drafted (gated on §9 #6 operator-trust precondition) | — | — |

## References

- `mahavishnu/settle/merge.py` — current 3-way merger (200 lines).
- `mahavishnu/settle/state_machine.py` — pure-function transition table.
- `mahavishnu/settle/persistence.py` — Dhara persistence layer.
- `mahavishnu/mcp/tools/worker_contract_tools.py:663` — sole consumer.
- `.claude/decisions/wire-up-contract.md` — policy this plan fulfills.
- `docs/plans/TEMPLATE.md` — plan template.
- Session-Buddy reflection stored 2026-09-10, tags `merge-driver`, `mergiraf`, `decision` — recovery anchor for "have we ever decided to use mergiraf?" archaeology queries.
