---
status: complete
role: implementation
kind: plan
date: 2026-11-06
last_reviewed: 2026-11-06
superseded_by: null
topic: bifrost-readiness-budget
title: "Make the Bifrost readiness budget clear the observed cold start"
---

# Make the Bifrost readiness budget clear the observed cold start

## 1. Outcome

A `mahavishnu bifrost start` issued during a cold host — the case where the
gateway is launched alongside the rest of the MCP fleet — reports the gateway
as ready and repoints the harnesses, instead of timing out on a gateway that
is about to come up.

**Success signal:** `bifrost start` returns without the
`not seen within ...s; leaving client URL(s) untouched` warning, and the
ready file plus a bound port 8471 are both observed within the budget.

## 2. Goals

1. The supervisor's bind budget must clear the **worst observed cold start**,
   not merely exceed the CLI's own wait.
2. The budget must cover the whole window the supervisor is responsible for,
   including the spawn itself.
3. A long wait must report progress, so it does not read as a hang.
4. The invariant must be pinned by a test that fails when the budget drops
   below the measured cold start.

## 3. Non-Goals

1. Making the gateway boot *faster* — the 5m29s is the transport's own
   catalog sync, not this repo's code.
2. Changing the transport version pin (`BIFROST_TRANSPORT_VERSION`).
3. Repairing the unrelated pre-existing test failures in
   `test_phase_f_migration.py` and `test_cloud_worker.py` (see §8).

## 4. Current Findings

The gateway was unreachable after the 2026-11-06 reboot. The launchd job
itself was healthy — `ai.bifrost.gateway` loaded at 07:21:07 and spawned at
07:25:23 — but the instance wrote **zero bytes** to stdout and stderr across
its whole 13.9-minute life and never bound port 8471.

Measured cold start on that host, from launchd spawn to the UI accepting
connections: **5m29s (329s)**. A warm boot is ~26s. The gap is the Go
transport's own boot sequence (config store → log store → vectorstore →
model catalog → MCP catalog), and it is widest exactly when the whole MCP
fleet is starting — which is when the gateway is launched.

Against that, the two budgets were:

| Knob | Value | Site |
|---|---|---|
| `gateway.READY_TIMEOUT_SECONDS` | 180s | `mahavishnu/bifrost/gateway.py` |
| `lifecycle.READY_BUDGET_SECONDS` | 210s | `mahavishnu/bifrost/lifecycle.py` |

`gateway.READY_TIMEOUT_SECONDS` is the one that bites: `serve()` kills the
child when it expires, so a healthy-but-slow gateway is killed mid-boot
before the CLI's longer wait ever gets a chance to observe it.

**This is a recurrence.** The 2026-10-29 plan
(`2026-10-29-bifrost-minimax-anthropic-route.md` §7) fixed the budget being
*below* the bind timeout — 60s → 210s. That fix was real but incomplete:
both numbers were still below the 329s this host needs. The test added then
asserted only the **relative** relationship
(`lifecycle.READY_BUDGET_SECONDS > gateway.READY_TIMEOUT_SECONDS`), so both
could be tuned downward together and the assertion would still hold. That is
why the regression was invisible to CI.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-BIFROST-045
    title: "Readiness budget clears the worst observed cold start"
```

## 5. Implementation Phases

### Phase 1: Raise and re-anchor the readiness budget

**Goal:** the supervisor waits long enough for a healthy gateway, and the
wait covers the spawn.

**Tasks:**
1. Raise `gateway.READY_TIMEOUT_SECONDS` from 180s to 600s.
2. Anchor the deadline *before* `launch_bifrost()` so the fork/exec stall
   is charged against the budget instead of extending it.
3. Raise `lifecycle.READY_BUDGET_SECONDS` to `READY_TIMEOUT_SECONDS + 60`.
4. Emit a progress line every 30s from `wait_for_ready_file`.

**Exit criteria:** the new tests pass, and the pre-fix values fail them.

#### Integration Contract

- **Triggered from**: `mahavishnu bifrost start` →
  `mahavishnu/bifrost/lifecycle.py::start()` → `bootstrap()` +
  `launchctl kickstart -k`, which execs `mahavishnu bifrost foreground` →
  `mahavishnu/bifrost/gateway.py::serve()`.
- **Returns to / updates**: `mahavishnu/bifrost/paths.py::READY_FILE`
  (`~/.local/state/mcp/ready/bifrost.ready`) is touched on bind; the harness
  endpoint in `~/.claude/settings.json` and `~/.qwen/settings.json` is
  rewritten only after both the ready file and a bound port 8471 agree.
- **Demonstrable by**: `mahavishnu bifrost status` reports
  `state = running` with a listener on 8471 and the ready file present;
  `pytest tests/unit/test_bifrost_gateway_readiness.py` passes.
- **Rollback signal**: the supervisor's own stderr line
  `bifrost did not bind port 8471 within 600s` in
  `~/.local/state/mcp/logs/bifrost.err`, which means the transport is
  genuinely failing rather than merely slow.
- **Observability added**: the progress line
  `waiting for bifrost.ready (Ns of budget left)` on stdout during
  `bifrost start`, so a multi-minute wait is legible to the operator.

### Phase 2: Pin the invariant

**Goal:** a future edit that shrinks the budget below the measured cold
start fails CI.

**Tasks:** add `tests/unit/test_bifrost_gateway_readiness.py` asserting the
budget clears `OBSERVED_COLD_START_SECONDS` (329s) — an **absolute** floor,
not just the relative relationship — plus coverage for the re-anchored
deadline and the progress line.

**Exit criteria:** with the pre-fix values restored, the new test fails.

#### Integration Contract

- **Triggered from**: `pytest tests/unit/test_bifrost_gateway_readiness.py`
  in CI.
- **Returns to / updates**: nothing at runtime — the test is the guard.
- **Demonstrable by**: the test fails against `READY_TIMEOUT_SECONDS = 180`
  and passes against `600`.
- **Rollback signal**: n/a — a failing test *is* the signal.
- **Observability added**: the failure message names the observed cold start
  so the next reader knows the floor is measured, not arbitrary.

## 6. Required Code Changes

- [x] `mahavishnu/bifrost/gateway.py` — `READY_TIMEOUT_SECONDS` 180 → 600;
      deadline anchored before `launch_bifrost()`.
- [x] `mahavishnu/bifrost/lifecycle.py` — `READY_BUDGET_SECONDS` = timeout
      + 60; `REPORT_INTERVAL_SECONDS`; progress line in
      `wait_for_ready_file`.
- [x] `tests/unit/test_bifrost_gateway_readiness.py` — new.

## 7. Validation Matrix

| tool/command | expected outcome | evidence location |
|---|---|---|
| `pytest tests/unit/test_bifrost_gateway_readiness.py` | 5 passed | test output |
| `pytest tests/unit -k bifrost` | 261 passed, 2 pre-existing failures | see §8 |
| `mahavishnu bifrost status` | `state = running`, listener on 8471, ready file present | CLI output |
| `curl http://127.0.0.1:8471/health` | `{"status":"ok"}` | HTTP response |

## 8. Risks

| risk | likelihood | mitigation |
|---|---|---|
| A genuinely broken gateway now takes 600s to be declared failed | medium | The launchd job is `KeepAlive`; the supervisor still kills the child and launchd respawns after `ThrottleInterval`. The 600s budget is the *upper* bound, not the expected case. |
| The transport's cold start grows further | low | The budget has ~270s of headroom over the measured 329s, and the new test fails loudly if the floor is breached. |
| Pre-existing test failures block the merge gate | certain | `test_phase_f_migration.py::test_no_bifrost_base_url_references` (`mahavishnu/terminal/manager.py` still reads `BIFROST_BASE_URL`) and `test_cloud_worker.py::test_chain_uses_router_when_enabled` (`runpod_public` is now in the fallback chain) both fail identically on unmodified `main`. Out of scope here; they need their own change. |

## 9. Decision Rule

This plan is done when the gateway survives a launch on a loaded host: the
supervisor's budget clears the measured cold start, the harness repoint
happens on a live gateway rather than a stale ready file, and CI fails if the
budget is ever tuned back below the measured floor.
