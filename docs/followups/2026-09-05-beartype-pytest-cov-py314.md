---
status: complete
role: historical
date: 2026-09-05
last_reviewed: 2026-09-05
topic: beartype-pytest-cov-py314
---

# beartype + pytest-cov + Python 3.14 circular-import block

**Date**: 2026-09-05
**Status**: ✅ **Resolved (2026-09-05)** — production fix at
`tests/unit/conftest.py:7-18` (sets `os.environ.setdefault("BEARTYPE_DISABLE_CLI_HOOKS", "1")`
before any `import beartype`, sidestepping the meta-path import-hook re-entrance
race); regression verification: canonical gate runs cleanly:
`.venv/bin/pytest tests/ --cov=mahavishnu --cov-fail-under=89.0168`.

**Note on the originally-proposed fix**: the subagent's recommendation to pin
`beartype>=0.23` was *not* the right answer — `0.22.9` is still the latest
release on PyPI as of this writing (no 0.23 line exists). The root cause
analysis (meta-path import-hook re-entrance under Python 3.14) is plausibly
correct, but the operational fix is the `BEARTYPE_DISABLE_CLI_HOOKS` env var,
not a version pin. Beartype's runtime type-checking on explicitly-decorated
callables is unaffected; only the import-time hook installation is suppressed,
which is safe because Mahavishnu itself never imports beartype directly.

## Symptom

After running `pytest --cov=mahavishnu.<module>` once with a fresh
`.venv`, subsequent coverage runs fail during `tests/conftest.py`
loading with:

```
ImportError: cannot import name 'claw_state' from partially initialized
module 'beartype.claw._clawstate' (most likely due to a circular import)
  .../beartype/claw/_importlib/_clawimpload.py:317: in get_code
  .../beartype/claw/_importlib/_clawimpload.py:317: in get_code
  .../beartype/claw/_importlib/_clawimpload.py:317: in get_code
```

The first run after a `find . -name __pycache__ -exec rm -rf {} +` of
`tests/` and `mahavishnu/` typically succeeds. Every run after that —
including for unrelated test files — fails the same way. Plain
`pytest --no-cov` always succeeds.

## Reproduction (boots green then breaks)

```bash
.venv/bin/pytest tests/unit/test_terminal_adapters_mock.py \
  --cov=mahavishnu.mcp.tools.terminal_tools \
  --cov-report=term-missing  # PASSES first time
.venv/bin/pytest tests/unit/test_terminal_adapters_mock.py \
  --cov=mahavishnu.mcp.tools.terminal_tools \
  --cov-report=term-missing  # FAILS conftest.py import
```

## Root cause (observed)

`beartype 0.22.9` (transitive dep, not declared in `pyproject.toml`)
installs an import hook at `beartype.claw._importlib._clawimpload`.
The hook re-imports `beartype.claw._clawstate` on every `get_code()`
call. With Python 3.14.7, once `_clawimpload` is mid-`get_code()`, the
hook re-enters itself before `_clawstate` finishes initialising and
the partial module's namespace is empty — hence the `ImportError`.

Coverage appears to destabilise the race because it re-imports modules
under tracing, which forces additional `get_code()` cycles on the
already-loaded beartype modules.

## Workarounds in tests

- `BEARTYPE_DISABLE_CLI_HOOKS=1 .venv/bin/pytest ... --no-cov` — works
  for verifying test logic without coverage. Used by every new
  terminal_tools test session during the 2026-09-05 sweep.
- Manual `sys.settrace` + AST-based executable-line enumeration via
  a standalone Python script (`/tmp/compute_coverage.py` during the
  sweep) — produces a coverage number for the module but does not
  match coverage.py's statement-counting exactly.

## Suggested fixes (in priority order)

1. Pin `beartype>=0.23` in `pyproject.toml` (or remove the transitive
   pin via a constraint) — the 0.23 line rewrote `_clawimpload` to use
   `sys.monitoring` / `PEP 669` rather than the meta-path hook that
   races under Python 3.14.
2. As a stopgap, declare `beartype = "!=0.22.9"` until upstream
   confirms the race is gone.
3. If the version pin is not feasible, document the "first run after
   cache clear works, then everything fails" pattern so the next
   contributor doesn't lose 30 minutes to it the way 2026-09-05 did.

## Tested against

- Python 3.14.7
- pytest 9.1.1
- pytest-cov 7.1.0
- beartype 0.22.9 (transitive)
