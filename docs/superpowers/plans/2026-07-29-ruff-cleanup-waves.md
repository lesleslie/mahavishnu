# Ruff Cleanup Wave-Plan (2026-07-29)

> **For agentic workers:** This is a triage + strategy document, not a
> task-by-task TDD plan. Each wave below has a dedicated sub-plan generated
> when the user approves execution. Steps use checkbox (`- [ ]`) syntax
> only inside sub-plans. **No edits in this repo until at least Wave 1 is
> approved.**

**Goal:** Bring the `mahavishnu/` production code under ruff clean
status (scope = 25 rules listed below) without changing observable
runtime behavior, in five risk-ordered waves that each end in a
testable, committable state.

**Architecture:** Mechanical fixes (autofix where possible) → logging
hygiene → BLE001 (narrowed exception classes + project error
hierarchy) → ASYNC rules (wrap blocking calls in `asyncio.to_thread`)
→ cleanup-orphan check. One wave per PR so a reviewer can focus.

**Tech Stack:** `ruff >= 0.15.16`, `pytest` (existing),
`crackerjack` (gate), `oneiric.logging` (logger convention),
`mahavishnu/core/errors.py` (project error hierarchy, MHV-001..499).

## Scope

- **Total ruff errors (whole repo):** 1854
- **In our 25-rule scope:** 1351
- **Out of scope (other rules in the report):** 503
  (`RUF100` 239 unused-noqa, `EXE001` 44, `RUF059` 43, `I001` 16,
  `PIE790` 12, `PLR0402` 12, `PERF102` 20, `FURB162` 11, `DTZ003` 10,
  `F401` 10, `PIE807` 10, `RUF013` 8, `RUF015` 7, `PLR1722` 6,
  `RUF022` 6, `UP017` 6, `W605` 6, `N999` 5, `TC003` 5, `PIE810` 4)
  — to be addressed in a separate follow-up plan if desired.

## Per-Rule Counts (scope)

| Rule | Count | Severity | Category |
|------|------:|----------|----------|
| BLE001 | 785 | high | blind-except — narrows to specific exceptions |
| DTZ005 | 189 | low | `datetime.now()` → `datetime.now(UTC)` |
| RUF012 | 79 | med | mutable class default → `ClassVar` / `field(default_factory=…)` |
| DTZ001 | 46 | low | `datetime(...)` → `datetime(..., tzinfo=UTC)` |
| S110 | 39 | low | `try-except-pass` → add `logger.debug(…)` |
| G201 | 32 | low | `logger.error(…, exc_info=True)` → `logger.exception(…)` |
| PLW1510| 32 | low | `subprocess.run` add explicit `check=…` |
| ASYNC221| 23 | high | run subprocess in async → wrap in `asyncio.to_thread` |
| TRY002 | 22 | high | `raise Exception(…)` → use `mahavishnu.core.errors.MahavishnuError` (or domain subclass) |
| PLW0602| 14 | low | `global _x` with no assignment in body → delete the line |
| ASYNC230| 13 | high | `open()` in async → `aiofiles.open()` / `asyncio.to_thread` |
| LOG015 | 12 | low | root logger call → use module logger |
| TRY004 | 11 | med | `raise ValueError` for type check → `raise TypeError` |
| TRY401 | 10 | low | `logger.exception(f"…{e}")` → `logger.exception("…%s", e)` |
| PYI036 | 9 | low | `__aexit__/__exit__` arg annotation → `object|None`, `BaseException|None`, `TracebackType|None` |
| DTZ011 | 6 | low | `date.today()` → `datetime.now(UTC).date()` |
| DTZ007 | 5 | low | `strptime(…)` no `%z` → pass `tzinfo=UTC` after parse |
| S112 | 5 | low | `try-except-continue` → add `logger.debug(…)` |
| DTZ006 | 4 | low | `fromtimestamp()` → `fromtimestamp(…, tz=UTC)` |
| PLC0206| 4 | low | `for k in d: use(d[k])` → `for k, v in d.items(): use(v)` |
| PLW0127| 4 | low | `UTC = UTC` self-assign → delete the line |
| ASYNC210| 2 | high | `requests` in async → `httpx.AsyncClient` / `to_thread` |
| RUF034 | 2 | low | useless if-else → direct expression |
| G101 | 1 | low | `extra={"module": …}` clashes with `LogRecord.module` → rename key |
| PERF402| 1 | low | `my_list[:]` copy → `list(my_list)` |
| DTZ901 | 1 | low | `datetime.min` no tz → `datetime.min.replace(tzinfo=UTC)` |

**Sum:** 1351. **Mechanical (autofix candidate):** ≈ 600. **Judgment:
≈ 750** (BLE001 785, RUF012 79, ASYNC 38, TRY002/004 33).

## Per-Rule Filing Decisions

For each rule, the canonical fix is documented here so the implementer
of any wave knows the exact transformation. All fixes are
backward-compatible (no public API changes).

### BLE001 — blind `except Exception`

- **Project policy:** CLAUDE.md says *"No `assert` in production code;
  use the `mahavishnu/core/errors.py` exception hierarchy."* The
  existing `core/errors.py` defines `MHV-001..499` codes plus a
  `MahavishnuError` base (verify by reading `core/errors.py:100+` —
  the sub-plan must confirm the base class name).
- **Standard transform:**
  - **Boundary catch (MCP tool, CLI command, worker dispatch):**
    Replace
    ```python
    except Exception as e:
        logger.error("X failed: %s", e)
        return {"status": "failed", "error": str(e)}
    ```
    with
    ```python
    except MahavishnuError:
        raise  # already structured; let it propagate
    except Exception as e:
        logger.exception("X failed")
        raise MahavishnuError(
            ErrorCode.INTERNAL_ERROR,
            "X failed",
        ) from e
    ```
  - **Recoverable catch (loop over a list, log + continue):** Narrow
    to the specific exception the operation can raise
    (`httpx.RequestError`, `KeyError`, `ValueError`, `OSError`,
    `subprocess.CalledProcessError`, etc.). If a literal `Exception`
    is needed (e.g. plugin loader, optional dep probe), add
    `# noqa: BLE001` with a one-line justification comment.
  - **Last-resort top-level handler** (e.g. `mcp/server_core.py` loop
    over tool invocations): keep `except Exception` but add
    `logger.exception(...)` and re-raise or return a structured
    failure. Do NOT narrow, because the tool may raise any subclass
    and the boundary must catch all of them.

### DTZ005 / DTZ001 / DTZ006 / DTZ007 / DTZ011 / DTZ901

- Standard: `datetime.now()` → `datetime.now(UTC)`,
  `datetime(2024, 1, 1)` → `datetime(2024, 1, 1, tzinfo=UTC)`,
  `fromtimestamp(t)` → `fromtimestamp(t, tz=UTC)`,
  `date.today()` → `datetime.now(UTC).date()`,
  `strptime(s, fmt)` → `datetime.strptime(s, fmt).replace(tzinfo=UTC)`
  (only when the format has no `%z`),
  `datetime.min` → `datetime.min.replace(tzinfo=UTC)`.
- The repo already imports `from datetime import UTC, datetime` (see
  `core/observability.py:4`). Self-assignment `UTC = UTC`
  (PLW0127) is harmless but should be deleted.
- **For Prefect adapter `_flow_run_to_response` patterns like
  `getattr(deployment, "created", datetime.now()) or datetime.now()`**:
  the `or datetime.now()` is already there as a fallback for `None`,
  so the `datetime.now()` calls just need `.replace(tzinfo=UTC)`.

### RUF012 — mutable class default

- **Dataclass:** `field(default_factory=list)` or `field(default_factory=dict)`.
- **Non-dataclass with `__init__`:** add an instance attribute in
  `__init__`: `self.x = x or []`.
- **Class-level constant intended to be shared:** annotate as
  `ClassVar[list[...]] = [...]`.
- **Default sentinel:** keep mutable, mark with `# noqa: RUF012` only
  if the team has reviewed and accepted the mutability risk.

### S110 / S112 — silent `except: pass` / `except: continue`

- Replace `pass`/`continue` with `logger.debug("skipped: %s", e)` (or
  `logger.exception` if the failure is unexpected).
- A `try-except-pass` is allowed only when annotated
  `# noqa: S110` with justification.

### G201 — `logger.error(..., exc_info=True)` → `logger.exception(...)`

- Mechanical rename; preserves stack-trace logging behavior.
- The first arg format may also need converting (G201 fires alongside
  TRY401 in some cases).

### PLW1510 — `subprocess.run` without `check=`

- Add `check=False` (default behaviour preserved) when the caller
  checks `returncode` manually. Add `check=True` when the caller
  wants `CalledProcessError`. Verify the surrounding code's
  `returncode` handling before choosing.

### ASYNC210 / ASYNC221 / ASYNC230

- **ASYNC221 (subprocess.run in async):** wrap in
  `await asyncio.to_thread(subprocess.run, ...)`. Keep
  `capture_output`, `text`, `timeout`, and `check` arguments
  identical.
- **ASYNC230 (open in async):** use `aiofiles.open()` for read paths
  or `await asyncio.to_thread(path.read_text)` for one-shot reads.
  For `tempfile.NamedTemporaryFile` + `open` combos (see
  `automation/backends/native_macos.py:565-580`), wrap the whole
  block in `to_thread` since `tempfile` is sync.
- **ASYNC210 (httpx/requests in async):** replace `requests` with
  `httpx.AsyncClient`; the existing code already uses `httpx` in
  some places — verify per call site.
- **Backwards compat:** these are observability-and-correctness
  improvements, not behavior changes. Existing tests that mock
  `subprocess.run` may need to mock `asyncio.to_thread` instead —
  the sub-plan will re-run `tests/` after the wave and surface any
  breakage.

### TRY002 — `raise Exception(...)`

- Replace `raise Exception(msg)` with
  `raise MahavishnuError(ErrorCode.INTERNAL_ERROR, msg)`. For domain
  errors, find the existing subclass (e.g. `NoBackendAvailableError`
  in `automation/manager.py:232`, or define one in the relevant
  module if the existing exception is too broad).

### TRY004 — `raise ValueError` for type check

- Replace `if not isinstance(x, T): raise ValueError("expected T")`
  with `if not isinstance(x, T): raise TypeError("expected T")`.
- **Caveat:** if the public function's documented contract says it
  raises `ValueError`, prefer `# noqa: TRY004` over a behavioural
  change that could break callers. The sub-plan will list the call
  sites to verify.

### PLW0602 — `global` with no assignment

- Delete the bare `global _x` lines (`factories.py:71,118,223,264,288`).
  These are leftovers from a refactor; the variables are now set
  unconditionally without needing the `global` declaration.

### PLW0127 — self-assigning `UTC = UTC`

- Delete the line (`core/observability.py:6`,
  `core/opensearch_integration.py:5`, `core/permissions.py:5`,
  `core/subscription_auth.py:10`). The module already imports
  `UTC` correctly from `datetime`.

### LOG015 — root logger call

- Replace module-level `import logging; logging.warning(...)` with
  `from oneiric.core.logging import get_logger; logger = get_logger(__name__)`
  and `logger.warning(...)`. Some sites use `import logging` and
  `logger = logging.getLogger(__name__)` which is fine; the issue
  is when the bare `logging.warning(...)` (no `getLogger`) is called.

### TRY401 — `logger.exception(f"...{e}")`

- Replace with `logger.exception("...%s", e)`. Removes the
  `LogRecord` carrying the exception twice (once as the implicit
  `exc_info`, once as the formatted message).

### PYI036 — `__aexit__` / `__exit__` arg annotations

- Change
  ```python
  def __aexit__(self, exc_type, exc_val, exc_tb): ...
  ```
  to
  ```python
  def __aexit__(
      self,
      exc_type: type[BaseException] | None,
      exc_val: BaseException | None,
      exc_tb: types.TracebackType | None,
  ) -> ...: ...
  ```
  Add `import types` if not already imported.

### PLC0206 — `for k in d: use(d[k])`

- Mechanical: `for k, v in d.items(): use(v)`.

### RUF034 — useless if-else

- Collapse `if cond: x = a; else: x = b` to `x = a if cond else b`.

### G101 — `extra={"module": ...}`

- Rename the key: `extra={"module": ...}` → `extra={"component": ...}`.
  (See `workers/capabilities/_observability.py:22`.)

### PERF402 — `my_list[:]`

- Replace `my_list[:]` with `list(my_list)`.

## Wave Plan

Waves are ordered by risk. **Each wave ends with `uv run pytest` and
`uv run ruff check .` clean for the rules it touches.** Each wave is
one PR.

### Wave 0 — Sanity (no edits)

- [ ] Run `uv run ruff check . --statistics` and confirm counts match
  this document.
- [ ] Run `uv run pytest -x -q --no-header` to record baseline.
- [ ] Run `uv run crackerjack run` to record baseline gate output.
- **Output:** baseline numbers in PR description. *No source changes.*

### Wave 1 — Trivial mechanical (~470 findings)

- **Rules:** PLW1510 (32), PLW0602 (14), PLW0127 (4), LOG015 (12),
  TRY401 (10), PYI036 (9), S110 (39), S112 (5), G201 (32),
  DTZ011 (6), DTZ006 (4), DTZ007 (5), DTZ901 (1), DTZ001 (46),
  DTZ005 (189), RUF012 (79), RUF034 (2), PLC0206 (4), PERF402 (1),
  G101 (1).
- **Why first:** zero or near-zero semantic risk; mostly autofix
  candidates or one-line edits. Gives us a 470-finding diff that's
  easy to review.
- **Approach:** one PR with up to 5 commits grouped by rule family
  (subprocess, datetime, logging, mutable-defaults, structure). For
  RUF012, the implementer must inspect each site to choose between
  `field(default_factory=…)`, instance init, or `ClassVar`.
- **Test:** rerun ruff on the rules in this wave → 0 findings.
  Rerun pytest → green.
- **Risk:** RUF012 in non-trivial classes. Implementer must read
  each class to determine the right transform.

### Wave 2 — Exception hierarchy adoption (~22 findings)

- **Rules:** TRY002 (22), TRY004 (11).
- **Why second:** uses the project error hierarchy from
  `core/errors.py`; small but behaviour-affecting (callers may rely
  on the literal `Exception` type being raised). The sub-plan must
  audit call sites first.
- **Approach:** for each `raise Exception(...)`, decide between
  `MahavishnuError(ErrorCode.INTERNAL_ERROR, ...)` and an existing
  domain subclass. For each `raise ValueError("… type …")` doing a
  type check, change to `raise TypeError(...)` **after** grepping
  for callers that catch `ValueError` specifically.
- **Test:** existing tests should pass; add one parametrized test
  per file where the change is non-trivial.
- **Risk:** external callers that catch `Exception` broadly will
  see no change; internal callers that catch `ValueError` from a
  type-check will need to switch to `TypeError`. Sub-plan includes
  a call-site audit script.

### Wave 3 — BLE001 (~785 findings)

- **Rules:** BLE001 (785).
- **Why third:** highest count, judgment-heavy. After Waves 1+2
  reduce noise, the implementer can focus purely on
  "what's the right exception class for this site".
- **Approach:** in sub-waves of ~100 sites each, sorted by
  directory. For each site: read the surrounding function, decide
  between (a) narrow to specific exception, (b) re-raise as
  `MahavishnuError`, (c) keep broad with `logger.exception` and
  `# noqa: BLE001` + justification. A per-directory review
  checklist helps maintain consistency.
- **Test:** ruff on BLE001 → 0; pytest → green; `crackerjack run`
  → green.
- **Risk:** over-narrowing (missing a real exception class) is the
  main concern. Sub-plan mandates that the implementer run the
  full test suite after each sub-wave, not just BLE001-related
  tests. If a tool is misclassified (e.g. swallows a
  `PermissionError` it should propagate), the suite will catch it.

### Wave 4 — Async correctness (~38 findings)

- **Rules:** ASYNC210 (2), ASYNC221 (23), ASYNC230 (13).
- **Why last:** largest behavior change. `subprocess.run` and `open`
  in async functions block the event loop today. The fix improves
  throughput but changes error propagation paths slightly
  (`CalledProcessError` and `FileNotFoundError` may now surface in
  a different task).
- **Approach:** for each site, wrap in `await asyncio.to_thread(...)`
  preserving all kwargs. For `open()` paths, use `aiofiles.open`
  where the file is read in a loop or large chunks; use
  `to_thread(path.read_bytes)` for one-shot reads. The
  `automation/backends/native_macos.py:565-585` site (sync
  `tempfile` + `subprocess` + `open` combo) is a single
  `to_thread` wrapper around the whole block.
- **Test:** existing async tests should pass. Add a tiny
  timing/concurrency test for one or two of the highest-traffic
  paths (e.g. `mcp/server_core.py` tool dispatch loop) to confirm
  the event loop is no longer blocked.
- **Risk:** the `subprocess.run` mock in tests needs to be replaced
  with `asyncio.to_thread` mock in some cases. The sub-plan must
  identify and update these mocks.

### Wave 5 — Final cleanup verification

- [ ] `uv run ruff check .` → 0 in scope (1351 → 0).
- [ ] `uv run ruff check .` overall count drops by 1351 (target
  reduction from 1854 to 503).
- [ ] `uv run pytest` → green.
- [ ] `uv run crackerjack run` → green.
- [ ] `python scripts/audit_orphans.py` → no new orphans.

## Decisions and Approvals Needed

- [ ] **Approve scope** (25 rules, 1351 findings) or trim to a
  subset.
- [ ] **Approve per-rule transforms** above. Any rule where the
  project prefers a different fix (e.g. keep `Exception` for
  plugin loaders) should be flagged here.
- [ ] **Approve Wave 3's judgment approach** (sub-waves of ~100 with
  per-directory review checklist) vs. a single mega-PR.
- [ ] **Wave 4 mock-impact analysis:** confirm we accept touching
  test mocks for the async wrap.
- [ ] **Naming question for G101:** rename `extra={"module": ...}`
  to `extra={"component": ...}` or another key? Affects
  downstream log-parsing queries (Grafana, Akosha).

## Out-of-Scope Follow-Ups (separate plans)

- **189 `RUF100` (unused-noqa):** the current noqas are stale. The
  refactor will obsolete many of them; clean up after Wave 3.
- **`EXE001` 44 shebang-not-executable:** the migrated scripts lost
  their executable bit during a past `git mv`. Single `chmod +x`
  pass.
- **`I001` 16, `F401` 10, `RUF059` 43, `RUF013` 8, `RUF015` 7,
  `RUF022` 6, `TC003` 5, `FURB162` 11, `PERF102` 20:** general
  cleanup, low risk, can ride with Wave 1.
- **`UP017` 6:** `datetime.timezone.utc` → `datetime.UTC`. Mostly
  already done; leftover in a few files.
- **`DTZ003` 10:** `datetime.utcnow()` → `datetime.now(UTC)`. Same
  family as DTZ005.

## Test Strategy

- **Per-wave:** `uv run pytest -q` and
  `uv run ruff check . --select <wave-rules>`.
- **Pre-commit:** `uv run crackerjack run` (the project's canonical
  gate).
- **Per-Wave-3 sub-wave:** `uv run pytest` (full suite, not subset)
  to catch over-narrowed exception classes.
- **Wave 4:** one new test asserting event-loop responsiveness for
  the MCP server tool-dispatch path.
- **Final:** `uv run crackerjack run` must pass; ruff must report
  `Found 0 errors` for the 25 rules in scope.

## Rollback Strategy

- Each wave is a single PR. If a wave fails CI, revert the PR;
  subsequent waves are independent.
- Wave 3 sub-waves should be individual commits within a single PR
  so they can be reverted in chunks if a particular sub-wave
  introduces a regression.
