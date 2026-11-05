---
name: crackerjack-compliant-code
description: >-
  Use when writing or modifying Python code, when a change looks
  over-engineered or bloated, or when a quality gate fails on the first run.
---

# Crackerjack-Compliant Code

## Overview

Use these rules before writing or modifying Python code so it passes the main quality gates without a fix loop.

Climb the Solution Ladder first: it finds the smallest change that still
passes every gate below.

## Solution Ladder (smallest change that passes the gates)

Before writing new code, climb and stop at the first rung that holds:

1. **Does this need to exist at all?** If the task did not ask for it, do not
   build it. Extra features are not scope.
2. **Does this repo already have it?** `mahavishnu/core/` holds 169 modules
   and the package holds 618 — the odds a "new helper" duplicates one are
   high. Check before you write:
   - `core/errors.py` — typed exceptions (`ValidationError`,
     `ConfigurationError`, `TaskNotFoundError`, …); use one instead of
     inventing a class or raising bare `Exception`.
   - `core/model_routing.py` — `TaskCategory`, `get_model_for_task`,
     `routing_to_task_map`, the `DEFAULT_*_ROUTING` tables (the built-in
     fallback), and the operator-config loader. `settings/models.yaml` is
     the live source of task routing: its `task_routing` blocks win, an
     edit is picked up with no restart, and
     `tests/unit/test_task_router.py::TestRoutingCoverage` requires the
     config to name every `TaskCategory`.
   - `core/unified_config.py` — cross-file schema validation for all five
     YAML config files. It validates; it does not return parsed config.
   - `core/config.py` — `MahavishnuSettings`.
   - `core/` also has `atomic.py`, `circuit_breaker.py`, `retry_policy.py`,
     `validators.py`, `config_validator.py`, `secure_logging.py`,
     `paths.py`, `rate_limit.py`, `idempotency.py`.
   - `pools/manager.py` — `PoolSelector`, `route_task`, `execute_on_pool`.
   - `oneiric.actions` — `security.SecuritySignatureAction` (HMAC),
     `http.HttpFetchAction`, `data.DataSanitizeAction`,
     `data.DataTransformAction`, plus `compression`, `serialization` and
     `payloads`. See `oneiric/docs/action-kits.md`.
   - `mcp/tools/` — 180 registered tools; check before adding one.
3. **Does the stdlib do it?** `pathlib`, `enum`, `dataclasses`, `itertools`,
   `contextlib`.
4. **Does an already-installed dependency do it?** `pydantic`, `httpx`,
   `structlog`, `pyyaml`. Never add a dependency for a few lines.
5. **Can it be one line a reader gets at a glance?** One line.
6. **Otherwise: the minimum that passes `crackerjack run`.**

The ladder runs **after** you understand the problem, not instead of it. Read
the code the change touches and trace the real flow first. A small diff you
do not understand is not efficiency — it is a bug you have not found yet.

**Never cut** — the floor is not negotiable: input validation at trust
boundaries (Pydantic models, per `CLAUDE.md`); the `core/errors.py` exception
hierarchy; `logger.exception(...)` inside `except` blocks; strict typing
(`ty`, mypy and pyright all clean); the 89% coverage floor — new branches
need tests; anything the user explicitly asked for.

Rung 6 is the floor, not the goal. "Smallest" means *smallest that passes
every gate above*. A one-line change that skips validation, error handling
or a test is a defect, not a shorter solution. Deletion beats addition, but
never delete a gate.

## Core Rules

- Add `from __future__ import annotations` as the first non-comment line.
- Keep imports ordered: stdlib, third-party, first-party.
- Use full type annotations on all functions.
- Prefer modern Python syntax like `X | None`, `list[str]`, and `pathlib.Path`.
- Avoid `assert` in production code.
- Keep functions small and refactor when complexity rises.

## Quality Limits

- Line length: 100 chars
- Function complexity: 15
- Parameters: 10
- Return points: 6
- Statements: 55

## Quick Checks

- Run `crackerjack run`
- Fix lint, type, security, and complexity issues before committing

## Notes

- Prefer explicit errors over assertions.
- Remove unused imports and dead code immediately.

## Traceable Spec IDs (REQ-NNN) — D2 wire-up discipline

Plans declare IDs in `## 4.5 Requirements` (YAML list under `requirements:`).
Code references them via one of:

- **Inline marker** (preferred): `# req: REQ-001` (or comma-separated: `# req: REQ-001, REQ-002`)
- **Docstring marker**: `# Implements: REQ-001` (used for class/function headers)
- **Test marker**: `@pytest.mark.req(["REQ-001"])` — registered in `pyproject.toml [tool.pytest] markers`

Audit: `python scripts/audit_requirements.py [--json]`. Exit codes: 0 clean / 1
orphans or phantoms / 2 missing root / 3 internal error. Enforcement is
Crackerjack-only: `crackerjack run` runs the pytest suite, which includes
`tests/integration/test_audit_requirements.py` asserting a clean exit. This
repo has no provider-specific CI — do not add `.github/workflows/*`.

## Type checker specifics (ty, since Phase I)

Crackerjack uses **ty** as the default type checker (replaces zuban).
Use `# ty: ignore[<code>]` to suppress specific diagnostics. **Never** use
the bare `# type: ignore` — ty silently ignores mypy/ruff syntax.

**Default suppression rules**:

- `# ty: ignore[invalid-argument-type]` for None-to-required-T fixes.
  Prefer `assert x is not None` or `t.cast("T", value)` at structural
  boundaries over blanket suppression.
- `# ty: ignore[unresolved-attribute]` only after verifying the attribute
  *should* exist (often a typo — see Phase I.A: 8 broken-control-flow bugs
  found via mass-suppression audit).
- `# ty: ignore[call-non-callable]` only if the call site cannot be None.
  Otherwise add the None-check.
- `# ty: ignore[unresolved-import]` only for TYPE_CHECKING imports; for
  runtime imports, fix the path.

**Mass suppressions are a smell.** If you find yourself adding more than
5 `# ty: ignore` to a single file, stop and audit: those suppressions
probably hide a real bug that tests have been written to accommodate
(see Phase M.A: 18 silent bug-maskers found via this pattern).

## Ratchet (crackerjack.tools.ty_ratchet)

The crackerjack comprehensive suite runs ty with a diagnostic-count gate
implemented at `crackerjack/tools/ty_ratchet.py`.

- **Phase Q (pending)**: split into `ty_max_errors_prod` and
  `ty_max_errors_test`. Production is tight (default 50); tests are
  tracked but not gate-failing (default 30).
- **Audit cadence**: when test suppressions cross 50, run a suppression
  audit. Mass suppressions in tests are a bug-finding signal, not noise.

## Where the value was (lessons from Phases I–N)

- **70% of latent bugs found** were surfaced because tests had been
  written to accommodate them. Type-check tests AND production; do not
  limit ty to `crackerjack/`.
- **Audit before counting.** Per-suppression classification matters; CI
  counts alone don't. The split ratchet (Phase Q) gives tests room to
  breathe; the audit cadence catches the regressions that the count
  cannot.
- **`Mock(spec=X)` and `SimpleNamespace`** are the highest-frequency
  sources of `invalid-argument-type` in tests. Replace with real
  dataclass instances or `t.cast("X", ...)` at the boundary.

See `docs/plans/2026-06-27-ty-cleanup-and-ai-fix.md` for the full
audit trail.
