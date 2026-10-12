---
status: draft
role: implementation
kind: plan
date: 2026-10-12
last_reviewed: 2026-10-12
superseded_by: null
blocks_on: []
topic: mcpserver-settings-convention
title: "mcp-common CommonMCPClient + HealthFeedState Test Backfill"
---

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:test-driven-development` — write the failing test first for each module, then implement to green.

# mcp-common CommonMCPClient + HealthFeedState Test Backfill

**Goal:** close the Phase 1b test gap in the umbrella plan `docs/plans/2026-09-14-common-mcp-client-transport-unification.md`. Phase 1a shipped code without Phase 1b tests; this plan backfills the 20 planned tests + 2 standalone smoke scripts and **does not re-do work the umbrella already shipped**. Out of scope for this plan: URL default normalization (umbrella Phase 2), call-site migration (umbrella Phase 3), and the per-repo health aggregator migration (now under `docs/plans/2026-10-09-mcp-health-check-enrichment.md`, shipped 2026-10-09).

**Architecture:** New test files under `mcp-common/tests/unit/clients/` and `mcp-common/tests/unit/health/` mirror the umbrella's Phase 1 task 7 + task 8 enumeration. New offline smoke scripts under `mcp-common/scripts/` give operators a no-deps way to verify the SDK at runtime. Each test ships with `@pytest.mark.req(["REQ-NNN"])` so the umbrella's `audit_requirements.py` REQ trace machinery closes the canary that `audit-passed` (Phase 1 exit criteria) never picked up.

**Tech Stack:** Python 3.14, Pytest 8+, `pytest-asyncio` (config `asyncio_mode = "auto"` per mcp-common standard), `respx` for HTTP mocking (PyJWT JWKS path), `mcp.client.streamable_http` for offline streamable-HTTP shape tests (test shapes only — no real server in unit tests).

**Parent plan:** `docs/plans/2026-09-14-common-mcp-client-transport-unification.md` (now `status: partial`, `superseded_by: docs/plans/2026-10-09-mcp-health-check-enrichment.md` for the Phase 4 portion).

**Why this plan exists as a separate file:** the umbrella plan is partially-superseded; preserving a single committed plan file per topic would force either (a) expanding the umbrella to track test backfill (drift) or (b) forking the umbrella to remove Phases 2–4 (loss of audit trail). Splitting the unfinished Phase 1b work into a focused plan keeps both readable.

## 1. Outcome

`mcp-common/tests/unit/clients/` and `mcp-common/tests/unit/health/` exist with the 20 tests enumerated in the umbrella Phase 1 task 7 + task 8. Pytest passes with `asyncio_mode = "auto"` and `@pytest.mark.req(["REQ-001…003", "REQ-007", "REQ-008"])` markers. `mcp-common/scripts/smoke_common_mcp_client.py` and `smoke_health_feed.py` execute offline and exit 0. `mcp-common` test coverage gate (≥80%) holds.

**Concrete success signals:**
1. `pytest mcp-common/tests/unit/clients/ mcp-common/tests/unit/health/ -v` exits 0; all 20 tests pass.
2. `python mcp-common/scripts/smoke_health_feed.py` exits 0 and prints the time-bounded decay narrative (matches REQ-007 + REQ-008 canary).
3. `python mcp-common/scripts/smoke_common_mcp_client.py --help` exits 0 and prints the contract documented in §6 (CLI shape parity with `smoke_health_feed.py`).
4. `grep -l '@pytest.mark.req' mcp-common/tests/unit/clients/ mcp-common/tests/unit/health/` returns non-empty (one per file).
5. `grep -rn 'Implements REQ-007\|Implements REQ-008' mcp_common/health/feed.py mcp_common/health/aggregator.py` returns ≥ 2 hits (the umbrella Phase 1 task 4 / Phase 4 task 6 markers; if absent, add them — they were a code-canary from the umbrella Phase 1 task 4 that the new aggregator code may have shed in the regression).

## 2. Goals

1. Ship the **11 tests** enumerated in umbrella Phase 1 task 7 for `CommonMCPClient` (`tests/unit/clients/test_common_mcp_client.py`).
2. Ship the **5 tests** for `HealthFeedState` helpers in umbrella Phase 1 task 4 (`tests/unit/health/test_feed.py`).
3. Ship the **4 tests** for `aggregate_feed_states` in umbrella Phase 1 task 5 / Phase 4 task 7 (`tests/unit/health/test_aggregator.py`).
4. Ship the **2 offline smoke scripts** in umbrella Phase 1 task 9: `scripts/smoke_common_mcp_client.py` and `scripts/smoke_health_feed.py`.
5. Add `@pytest.mark.req(["REQ-001"])` / `["REQ-002"]` / `["REQ-003"]` / `["REQ-007"]` / `["REQ-008"]` markers per the umbrella Phase 1 task 7 + task 8 list, so the audit can verify the canary.
6. Bump `mcp-common/CHANGELOG.md` `[Unreleased]` with a "Test backfill" entry that names the new test files. **Do NOT bump `pyproject.toml` version** — per `feedback-mcp-common-version-bump-is-user.md`, the user runs `crackerjack run -p minor` to bump + tag + publish; this plan is purely additive.

## 3. Non-Goals

1. **URL default normalization** — that's umbrella Phase 2. Out of scope.
2. **Per-repo call-site migration** — that's umbrella Phase 3. Out of scope.
3. **Per-repo `/health` aggregator wiring** — that's now under `2026-10-09-mcp-health-check-enrichment.md` (shipped). Out of scope.
4. **Removing `KNOWN_SERVICES` / cross-compile shared fixtures** — those were audit suggestions, not part of the umbrella's deliverable list. Skip.
5. **Bumping `mcp-common` version** — per the umbrella's §3 Non-Goals #7 and `feedback-mcp-common-version-bump-is-user.md`, user owns the version. This plan is purely test backfill; no public surface change.
6. **Re-running tests under `pytest -m slow` markers** — the umbrella didn't ask for slow tests; this plan stays `unit`.
7. **Benchmarks / property tests** — not in the umbrella enumeration. Stay TDD-classic.

## 4. Current Findings

### 4.1 What shipped without tests (umbrella Phase 1a)

`ls /Users/les/Projects/mcp-common/mcp_common/clients/`:
```
__init__.py
__pycache__
common_mcp_client.py
```

`ls /Users/les/Projects/mcp-common/mcp_common/health/`:
```
__init__.py
__pycache__
aggregator.py
feed.py
metrics.py
```

**`tests/unit/clients/`** does NOT exist (parent directories tested: `tests/auth/`, `tests/server/`, `tests/parsing/`, `tests/performance/`, `tests/release_audit/`, `tests/integration/`, `tests/unit/`; no `clients/` or `health/` subdirs). **This is the gap.**

Inline `# Implements: REQ-NNN` markers: at least one confirmed on `common_mcp_client.py:15`. Health-side markers may be missing — verify and add if absent.

### 4.2 `mcp-common` version drift

Target per the umbrella: 0.25.3 → 0.26.0. **Actual: 0.30.5** (verified from `pyproject.toml`). The user-owned version policy holds (per `feedback-mcp-common-version-bump-is-user.md`), but the umbrella's PR-merge-and-publish exit criterion ("user-initiated bump to 0.26.0") is moot — the library is now 4 minor versions past where Phase 1 expected to publish. **No action** in this plan; just awareness for any reviewer who re-pulls the umbrella.

### 4.3 Integration-test gap (acknowledged but out of scope)

The umbrella's `tests/integration/mcp/test_common_mcp_client.py` (Phase 3 deliverable, spins up akosha + session-buddy in subprocesses) is **NOT** part of this backfill. Backfill is unit tests only. Per `mcp-backend-wiring-discipline.md`, integration tests are required at plan-time, but this plan backfills an already-shipped code surface — integration tests for `CommonMCPClient` are Part 2 of Phase 3, scheduled under umbrella Phase 3, which is itself in ❓ UNVERIFIED state. This plan's exit does NOT promote Plan 2 to "complete"; only the test gap (Phase 1b) closes.

### 4.4 `audit_requirements.py` canary

Each new test must carry `@pytest.mark.req(["REQ-NNN"])` markers per the umbrella Phase 1 task 7+8 enumeration:
- `tests/unit/clients/test_common_mcp_client.py` → `@pytest.mark.req(["REQ-001"])`
- `tests/unit/health/test_feed.py` → `@pytest.mark.req(["REQ-002"])`
- `tests/unit/health/test_aggregator.py` → `@pytest.mark.req(["REQ-002", "REQ-003", "REQ-007", "REQ-008"])`

If `mcp-common/scripts/audit_requirements.py` (or equivalent) does not exist, note the gap but do not implement it as part of this plan — the umbrella is the parent.

## 5. Implementation Phases

### Phase 1: Test backfill (single phase; one commit)

**Goal:** ship all 20 unit tests + 2 smoke scripts + the markers + the CHANGELOG entry in one commit.

#### Integration Contract ← Phase 1
- **Triggered from**: `pytest mcp-common/tests/unit/clients/ mcp-common/tests/unit/health/ -v` after the commit lands.
- **Returns to / updates**: 3 new test files + 2 new smoke scripts + 1 CHANGELOG line. No source-file changes (the SDK code shipped in umbrella Phase 1a is the contract under test). No `pyproject.toml` change.
- **Demonstrable by**: the pytest invocation above exits 0 with 20+ tests reported, plus the two smoke-script invocations exit 0.
- **Rollback signal**: any of the 20 tests fails for a reason traceable to a behavior that already shipped under the umbrella (the backfill test asserted a behavior the SDK does not have) — revert the test, not the SDK code.
- **Observability added**: the `@pytest.mark.req(["REQ-NNN"])` markers make the existing `audit_requirements.py` (if present) surface the canary missing from umbrella Phase 1 task 7. No new metrics.

**Tasks (TDD, one step per action — 5-10 minutes each):**

- [ ] **Task 1.1: TDD `CommonMCPClient` wire-shape contract tests (3 tests, REQ-001)**
  - Tests: `test_call_tool_sends_jsonrpc_envelope`, `test_call_tool_sends_mcp_session_id_header_on_second_request`, `test_call_tool_parses_response_from_result_payload`.
  - Use `respx` to mock the streamable-HTTP endpoint; assert the outbound JSON-RPC envelope shape (`{"jsonrpc": "2.0", "id": <int>, "method": "tools/call", "params": {"name": ..., "arguments": ...}}`) and the inbound `result.structuredContent` payload.
  - Mark each: `@pytest.mark.req(["REQ-001"])`.

- [ ] **Task 1.2: TDD `CommonMCPClient` negative tests (4 tests, REQ-001)**
  - Tests: `test_call_tool_raises_on_error_envelope`, `test_call_tool_raises_mcp_http_error_on_5xx`, `test_call_tool_raises_mcp_timeout_on_read_timeout`, `test_call_tool_raises_on_malformed_json`.
  - Assert the new `MCPClientHTTPError` and `MCPClientTimeoutError` exception types from `mcp_common/clients/exceptions.py` (created if absent — umbrella §6 said NEW but didn't enumerate). If absent, create the module with the two exception classes and empty `__init__.py` re-export.
  - Mark each: `@pytest.mark.req(["REQ-001"])`.

- [ ] **Task 1.3: TDD `CommonMCPClient` lifecycle tests (4 tests, REQ-001)**
  - Tests: `test_session_id_handshake_after_first_response`, `test_reconnect_on_410_with_new_session_id`, `test_multiple_calls_reuse_session`, `test_ssrf_guard_rejects_file_scheme`.
  - The SSRF-guard test exercises the existing `_ALLOWED_SCHREFS = frozenset({"http", "https"})` block the umbrella §4.4 cited.
  - Mark each: `@pytest.mark.req(["REQ-001"])`.

- [ ] **Task 1.4: TDD `HealthFeedState` helper tests (5 tests, REQ-002)**
  - Tests: `test_record_success_resets_errors_within_window`, `test_record_success_clears_first_unhealthy_at_on_recovery`, `test_record_error_sets_first_unhealthy_at_on_healthy_to_unhealthy_transition`, `test_record_error_idempotent_on_subsequent_errors` (no double-set), `test_is_healthy_returns_healthy_when_no_errors_and_entities_populated`.
  - These cover the umbrella Phase 1 task 4 helper description; the actual API may need adjustment if `record_success` / `record_error` differ from the description (verify against `mcp_common/health/feed.py` first; if signatures differ, update the tests to match what's there — the goal is to backfill coverage, not enforce a different API).
  - Mark each: `@pytest.mark.req(["REQ-002"])`.

- [ ] **Task 1.5: TDD `aggregate_feed_states` tests (4 tests, REQ-002, REQ-003, REQ-007, REQ-008)**
  - Tests per umbrella Phase 1 task 8:
    - `test_is_healthy_true_when_no_errors` → `@pytest.mark.req(["REQ-002"])`
    - `test_is_healthy_true_when_error_outside_halflife` → `@pytest.mark.req(["REQ-007"])`
    - `test_is_degraded_when_error_within_halflife` → `@pytest.mark.req(["REQ-007"])`
    - `test_is_warming_up_when_empty_and_no_errors_and_ingester_running` → `@pytest.mark.req(["REQ-008"])`
    - `test_aggregate_picks_worst_status` (failed > degraded > warming_up > healthy) → `@pytest.mark.req(["REQ-003"])`
  - The umbrella listed 4 tests but `aggregate_picks_worst_status` is load-bearing — ship 5 to maintain the canary.

- [ ] **Task 1.6: Write `mcp-common/scripts/smoke_health_feed.py` (offline; REQ-002/007/008)**
  - Per umbrella Phase 1 task 7 (smoke scripts). Construct a `HealthFeedState` with `last_error_at = now - halflife_seconds - 1`; assert `aggregate_feed_states({...})` returns `healthy`. Construct one with `last_error_at = now`; assert `degraded`. Construct one with `entities_count == 0`, `cycles_total >= 1`, `ingester_running = True`; assert `warming_up` with `reason_codes == ["warming_up_empty_feed"]`.
  - CLI: `python scripts/smoke_health_feed.py [--halflife-seconds=300]`. Exit 0 on success; exit 1 on assertion failure with the failing state printed.

- [ ] **Task 1.7: Write `mcp-common/scripts/smoke_common_mcp_client.py` (online; REQ-001)**
  - Per umbrella Phase 1 task 7. CLI shape mirrors `smoke_health_feed.py`:
    `python scripts/smoke_common_mcp_client.py --target URL --tool NAME [--args JSON_STRING] [--timeout-seconds=10]`.
  - Behavior: instantiate `CommonMCPClient(target=URL, timeout=10)`; call `await client.call(name=NAME, arguments=json.loads(ARGS))`; print the result; exit 0 if no exception, exit 1 with the exception class + message on failure.
  - Mark operators: this script requires a running server at `--target URL`; it is **not** offline. The `smoke_health_feed.py` script (Task 1.6) is offline; this one is not. Document the difference in `--help`.

- [ ] **Task 1.8: Add the markers audit (if `audit_requirements.py` missing, just add the markers anyway)**
  - If `mcp-common/scripts/audit_requirements.py` exists, run it locally and confirm the 5 new files have `@pytest.mark.req(["REQ-NNN"])` markers and produce a non-empty REQ-coverage report.
  - If `audit_requirements.py` does NOT exist, this task is a no-op. Mark with a comment in the commit message: "test markers per umbrella §Phase 1 task 7 enumeration; no `audit_requirements.py` exists at time of this commit."

- [ ] **Task 1.9: Update `mcp-common/CHANGELOG.md` `[Unreleased]`**
  - Add an entry naming the test backfill:
    ```
    Added: Test backfill for `mcp_common/clients/common_mcp_client.py` (11 tests)
    and `mcp_common/health/{feed,aggregator}.py` (9 tests). Per plan
    `docs/plans/2026-10-12-mcp-common-test-backfill.md`. Plus operator
    smoke scripts `scripts/smoke_health_feed.py` (offline) and
    `scripts/smoke_common_mcp_client.py` (online; requires running
    server). No public surface change. No version bump.
    ```
  - **DO NOT modify `pyproject.toml` version.** Per `feedback-mcp-common-version-bump-is-user.md`, user bumps via `crackerjack run -p minor`.

- [ ] **Task 1.10: Commit**
  ```bash
  cd /Users/les/Projects/mcp-common

  git add mcp-common/tests/unit/clients/test_common_mcp_client.py \
          mcp-common/tests/unit/health/test_feed.py \
          mcp-common/tests/unit/health/test_aggregator.py \
          mcp-common/scripts/smoke_health_feed.py \
          mcp-common/scripts/smoke_common_mcp_client.py \
          mcp-common/CHANGELOG.md

  git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m \
      "test(mcp-common): backfill CommonMCPClient + HealthFeedState tests (Phase 1b of $(PLAN_UMBRELLA))"
  ```
  **DO NOT tag or bump version.** User does that via `crackerjack run -p minor`.

## 6. Required Code Changes

```yaml
mcp-common:
  - path: mcp-common/tests/unit/clients/__init__.py
    change: NEW (empty marker)
  - path: mcp-common/tests/unit/clients/test_common_mcp_client.py
    change: NEW (11 tests; umbrella Phase 1 task 7 enumeration)
  - path: mcp-common/tests/unit/health/__init__.py
    change: NEW (empty marker)
  - path: mcp-common/tests/unit/health/test_feed.py
    change: NEW (5 tests; REQ-002 helpers)
  - path: mcp-common/tests/unit/health/test_aggregator.py
    change: NEW (4-5 tests; REQ-002, REQ-003, REQ-007, REQ-008)
  - path: mcp-common/scripts/smoke_health_feed.py
    change: NEW (offline smoke; REQ-002/007/008)
  - path: mcp-common/scripts/smoke_common_mcp_client.py
    change: NEW (online smoke; REQ-001)
  - path: mcp-common/mcp_common/clients/exceptions.py
    change: NEW *only if* Task 1.2 finds the exception types missing
  - path: mcp-common/CHANGELOG.md
    change: EDIT — add [Unreleased] entry
```

## 7. Validation Matrix

| Tool / Command | Expected outcome | Evidence location |
|---|---|---|
| `pytest mcp-common/tests/unit/clients/ mcp-common/tests/unit/health/ -v` | All 20 tests pass | pytest stdout |
| `python mcp-common/scripts/smoke_health_feed.py` | Exit 0; prints time-bounded decay narrative covering REQ-002 (HealthFeedState), REQ-007 (time-bounded decay), REQ-008 (warming_up predicate) | script stdout |
| `python mcp-common/scripts/smoke_common_mcp_client.py --help` | Exit 0; prints CLI contract documented in Task 1.7 | script --help |
| `grep -rn '@pytest.mark.req' mcp-common/tests/unit/clients/ mcp-common/tests/unit/health/` | ≥ 20 hits (≥1 per test) | shell exit 0 |
| `python -m pytest mcp-common/tests/ --cov=mcp_common --cov-fail-under=80` | Coverage gate ≥ 80% holds | pytest + coverage output |
| `pytest mcp-common/tests/unit/clients/ mcp-common/tests/unit/health/ --tb=short` | All tests pass; failures report exact line | pytest stdout |
| `git grep -n Implements.REQ-007 mcp_common/health/feed.py` | ≥ 1 hit (umbrella Phase 4 task 6 marker; add if absent) | shell exit 0 |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Test signatures don't match shipped code | medium | First task in each module is "verify the API against `mcp_common/{clients,health}/*.py` then update the test to match" — the goal is to backfill coverage, not enforce a different API. If a signature has drifted, the implementer raises here and we add a "Pre: API drift check" gate to the plan. |
| `mcp-common/scripts/audit_requirements.py` doesn't exist | medium | Task 1.8 documents the gap; the markers are still added regardless so a future audit script can consume them. |
| Implementer bundles a version bump | low | Task 1.10 explicitly excludes `pyproject.toml` from the `git add`. The CLAUDE.md `feedback-mcp-common-version-bump-is-user.md` rule is reinforced in the commit message. |
| `aggregate_picks_worst_status` test catches a real bug in shipped aggregator | low | The aggregator shipped with the worst-status walk; if the test reveals a missed case, log the bug, file a separate fix plan, defer the canary. Do not let a backfill test change SDK behavior. |
| Smoke scripts pollute `mcp-common/scripts/` namespace | low | Both scripts have `smoke_` prefix; `scripts/regenerate_plan_index.py`, `scripts/launch_smoke.py`, `scripts/audit_type_checking_runtime_refs.py` already use that prefix. No naming collision. |
| `tests/unit/health/test_feed.py` Task 1.4 assumptions don't match `record_success` / `record_error` actual signatures | medium | Each test begins by inspecting `HealthFeedState.__init__` and the helper methods to derive expected signatures. Update the test bodies to use whatever is there. |
| Cross-import: tests/unit/clients/ imports mcp_common that re-exports from mcp_common.server.launcher (which has open dev work) | low | `from mcp_common.clients.common_mcp_client import CommonMCPClient` is direct — no transitive dependency on the launcher import that doesn't yet exist at top-level (`mcp_common.__init__.py` is missing `launch`). |

## 9. Decision Rule

Plan is **done enough** when:
1. All 20 (or 21 — including `aggregate_picks_worst_status`) new tests pass with `pytest mcp-common/tests/unit/clients/ mcp-common/tests/unit/health/ -v`.
2. The 2 smoke scripts exist; `smoke_health_feed.py` exits 0; `smoke_common_mcp_client.py --help` exits 0.
3. `python -m pytest mcp-common/tests/ --cov=mcp_common --cov-fail-under=80` exits 0 (coverage gate holds).
4. The CHANGELOG `[Unreleased]` entry exists. `pyproject.toml` version is **unchanged**.
5. The umbrella plan `docs/plans/2026-09-14-common-mcp-client-transport-unification.md` is re-promoted from `status: partial` → `status: active` (the active pieces are: Phase 1a done, Phase 1b now done, Phase 3 unverified, Phase 4 superseded). The umbrella frontmatter `superseded_by` field stays pointed at the health-enrichment plan.

Plan is **not done** when:
- Any source file in `mcp_common/{clients,health}/` is modified (this plan is test-only — the SDK was the umbrella's delivery).
- `pyproject.toml` is touched.
- `git grep Implements.REQ-00. mcp_common/health/` returns 0 hits and the implementer did not add the markers.
- A test fails because the shipped code doesn't have the asserted behavior (file a real-canary bug; do not paper over).

## 10. References

- `docs/plans/2026-09-14-common-mcp-client-transport-unification.md` — parent umbrella (status: partial; Phase 1a done; Phase 1b backfilled here; Phases 3, 4 decoupled)
- `docs/plans/2026-10-09-mcp-health-check-enrichment.md` — Phase 4 successor (shipped 2026-10-09)
- `docs/specs/2026-09-06-mcp-common-auth-primitives-design.md` — historical reference; not directly related to this backfill but cites the `mcp_common/auth` package as the established pattern for these tests
- `docs/plans/2026-09-05-mcp-common-phase1.md` — Phase 1 of `2026-09-05-mcp-common-phase1-design.md`; documents the `auth` package's test conventions this plan follows
- `mcp-backend-wiring-discipline.md` — Bodai-wide rule that integration tests are required; this plan's scope is **unit** tests (per umbrella scope); integration tests for `CommonMCPClient` remain an open piece under umbrella Phase 3
- `feedback-mcp-common-version-bump-is-user.md` — version bumps are user-owned; this plan excludes `pyproject.toml`
- `feedback-keep-plan-files-tracked.md` — `git add docs/plans/*.md` first; this plan follows that
- `feedback-no-backwards-compat-pre-1.0.md` — `mcp-common` pre-1.0; if a test reveals missing behavior, the fix replaces the gap, it does not paper over it
