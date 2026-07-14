# Task 4 Report: Gated integration smoke test

**Status:** DONE_WITH_CONCERNS
**Branch HEAD at start:** `928d680`
**Test summary:** 1/1 SKIPPED (default gate; expected first-run outcome), output pristine

## What I implemented

Created `tests/integration/terminal/test_mcpretentious_smoke.py` exactly per
the brief: a real-subprocess MCPretentious smoke test gated by
`MCPRETENTIOUS_INTEGRATION=1` AND `node` AND `npm` on PATH. The module is
silently skipped when any precondition is missing, with two distinct skip
reasons so operators can see which gate tripped:

1. `Set MCPRETENTIOUS_INTEGRATION=1 with node and npm on PATH to run.`
   — the env var is unset (or node/npm missing).
2. `mcpretentious not installed globally; run: npm install -g mcpretentious`
   — the gate is open but the global package is not present.

The test body uses the brief's `unittest.IsolatedAsyncioTestCase` pattern,
preflight-checks the global package, spawns the real subprocess via
`McpretentiousClient(backend_name="mcpretentious")`, exercises the
`open → type → read → close` flow, and wraps the calls in nested
`try/finally` so the client always stops and the terminal always closes,
even on failure.

Style was brought to project compliance: the file uses
`from __future__ import annotations`, has full type annotations, sorted
imports, and passes `ruff check` + `ruff format --check` cleanly.

## TDD evidence

The brief did not require a strict RED-then-GREEN flow (Task 4 is a
"create-the-gated-file" task with skip-by-default as the desired first
run), so TDD was not applicable. I instead followed the brief's
verification steps literally.

### Step 2 — default run (gate closed) — expected SKIPPED, not failure

Command:

```bash
.venv/bin/python -m pytest tests/integration/terminal/test_mcpretentious_smoke.py -v
```

Initial output included the brief-suggested reason text
(`Set MCPRETENTIOUS_INTEGRATION=1 with node and npm on PATH to run.`) but
exited 1 because `pyproject.toml`'s `addopts` injects
`--cov=mahavishnu --cov-fail-under=80` into every invocation, and a
single skipped test obviously cannot meet the 80% threshold. Prior SDD
task reports (Task 1, 2, 3, 3-gap-fix) use `--no-cov` for focused
runs. After adopting that standard override, the result is the expected
skip:

```
tests/integration/terminal/test_mcpretentious_smoke.py::TestMcpretentiousSmoke::test_session_open_type_read_close SKIPPED [100%]
SKIPPED [1] tests/integration/terminal/test_mcpretentious_smoke.py:27: Set MCPRETENTIOUS_INTEGRATION=1 with node and npm on PATH to run.
1 skipped in 1.12s
```

`ruff check` and `ruff format --check` both pass on the file.

### Step 3 — gate-open run

With `MCPRETENTIOUS_INTEGRATION=1` only (no global package yet), the
test reaches the inner preflight and skips with the package-missing
reason:

```
SKIPPED [1] tests/integration/terminal/test_mcpretentious_smoke.py:27: mcpretentious not installed globally; run: npm install -g mcpretentious
```

I then installed the global package (`npm install -g mcpretentious`,
445 packages) to exercise the live tool surface end-to-end. The test
did execute the open/type/read/close sequence against the real
subprocess, but the server rejected the brief's snake_case parameter
names — see "Concerns" below.

## Files changed

- **Created** `tests/integration/terminal/test_mcpretentious_smoke.py`
  (62 lines, lint/format clean)

## Self-review findings

- One-line refactor would have moved the `subprocess` import inside the
  test method to mirror the lazy `mahavishnu.terminal.mcp_client` import.
  Kept it top-of-file because the brief's snippet does so and I did not
  want to deviate from the supplied shape without a green light.
- The brief's test sleeps implicitly between `type` and `read` only via
  the subprocess round-trip. If the real path were observed to flake on
  CI, an explicit short `asyncio.sleep` before `read` would be the first
  lever. Did not add it; the default-first-run expectation is SKIPPED
  here, and I did not run the live path past one full attempt.

## Concerns

1. **Brief vs. live-server schema divergence (DONE_WITH_CONCERNS trigger).**
   The installed `mcpretentious` server (verified against
   `/usr/local/lib/node_modules/mcpretentious/mcpretentious.js`) expects
   camelCase parameter names: `terminalId` and `lines` for the read tool,
   `terminalId` and `input` for the type tool, `terminalId` for the
   close tool, and `columns`/`rows` for the open tool. The brief's
   snippet uses snake_case (`terminal_id`, `limit_lines`) and
   `assertIsNotNone(session_id)`. The live server returns
   `{"content": [{"type": "text", "text": "<message>"}]}` rather than
   `{"terminal_id": "..."}`, so `assertIsNotNone` would see a dict, not
   an ID, and even a passing `type` would be followed by a `read` that
   the server rejects with:
   `MCP error -32602: ... "path": ["terminalId"] ... "Required"`.

   I did NOT modify the test to fix the names: the brief is explicit
   and the instruction was to add the file verbatim. Options for the
   controller: (a) accept the divergence and keep the file as the brief
   dictates (current state — default-gate SKIP behavior is the
   expected first run); (b) align the parameters and result extraction
   with the live server so the gate-open path also passes; (c) flag
   this as a separate upstream fix in the connected chain
   (`McpretentiousClient` itself uses the same snake_case names — see
   `mahavishnu/terminal/mcp_client.py:319, 331, 346, 357` and
   `mahavishnu/terminal/adapters/mcpretentious.py:90-95, 140-146,
   178-182, 201-206`, so the divergence is project-wide, not just in
   the test).

2. **Full-suite pre-existing failures are NOT introduced by this task.**
   I ran the full suite once as the brief requested. The cached
   `lastfailed` shows 562 failing nodes (see
   `.pytest_cache/v/cache/lastfailed`) — all in pre-existing files such
   as `tests/unit/test_debug_monitor.py`,
   `tests/unit/engines/test_prefect_adapter.py`,
   `tests/unit/test_adapters/test_agno_adapter.py`,
   `tests/unit/test_routing_cli_smoke.py`, etc. The new file is not
   among them, and I did not touch any of the failing code. The user
   should treat those as separate work; addressing them is out of scope
   for Task 4.

## Notes on system prerequisites

- `node` and `npm` were already on `PATH` (`/usr/local/bin/node`,
  `/usr/local/bin/npm`).
- To exercise the live path I installed `mcpretentious` globally
  (`npm install -g mcpretentious`); the brief lists this as the
  install-on-failure step.
