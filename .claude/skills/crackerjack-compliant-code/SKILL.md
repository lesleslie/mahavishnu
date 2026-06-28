______________________________________________________________________

## name: crackerjack-compliant-code description: Use when writing Python code that should pass quality gates on the first run.

# Crackerjack-Compliant Code

## Overview

Use these rules before writing or modifying Python code so it passes the main quality gates without a fix loop.

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
