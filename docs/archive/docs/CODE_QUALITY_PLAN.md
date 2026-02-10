# Code Quality Improvement Plan

## Phase 5: Code Quality Improvements

### Summary
Remove type: ignore comments, add comprehensive docstrings, replace print statements with logger.

## Files to Modify

### 1. Type: Ignore Removal (6 occurrences)

| File | Line | Issue | Fix |
|------|------|-------|-----|
| `mahavishnu/ingesters/otel_ingester.py` | 22 | `SentenceTransformer = None  # type: ignore` | Change to `SentenceTransformer: type[Any] \| None = None` |
| `mahavishnu/core/coordination/memory.py` | 286 | `class CoordinationManagerWithMemory:  # type: ignore` | Remove comment, fix type stub imports |
| `mahavishnu/core/app.py` | 608, 616 | `.get("repos", [])  # type: ignore` | Fix return type annotation |
| `mahavishnu/session_buddy/auth.py` | 132, 134 | `# type: ignore` on auth methods | Fix type stub issues |

### 2. Print → Logger Replacement (51 occurrences)

#### mahavishnu/core/production_readiness.py (39 prints)
- Replace all `print()` with `logger` at appropriate levels
- Add `import logging` and `logger = logging.getLogger(__name__)`

#### mahavishnu/pools/memory_aggregator.py (3 prints)
- Replace print statements with `logger.info()`

#### mahavishnu/pools/manager.py (3 prints)
- Replace print statements with `logger.info()`

#### mahavishnu/core/app.py (3 prints)
- Replace print statements with `logger.warning()`

#### mahavishnu/core/coordination/memory.py (3 prints)
- Replace print statements with `logger.error()`

#### mahavishnu/pools/kubernetes_pool.py (1 print)
- This is in a command string, keep as-is (generated code)

### 3. Docstring Additions

Need to review and add docstrings to:
- All public classes missing `__doc__`
- All public functions/methods without docstrings
- Complex private methods (> 10 lines)

## Expected Outcomes

- **Type ignores removed**: 6
- **Print statements replaced**: 50
- **Docstrings added**: ~20 (estimated)
- **Files modified**: 8
- **Test coverage**: No change (maintain 90%+)

## Implementation Order

1. Fix type: ignore comments (easiest, highest impact)
2. Replace print with logger (mechanical, medium impact)
3. Add docstrings (requires thinking, lower impact)

## Testing

After changes:
- Run `pytest` to ensure no regressions
- Run `mypy` to verify type correctness
- Run `ruff check` for linting
