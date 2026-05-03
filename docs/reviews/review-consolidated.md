# Consolidated Deliverables Review

**Reviewed**: 2026-04-05 ~10:10
**Reviewer**: nanobot (direct — subagents rate-limited)
**Scope**: I10-1 (tool ranking), I11-1 (cache policy), I15-1 (content quality eval)

______________________________________________________________________

## Review 1: Lint & Type Safety

### `scripts/rank-tools.py` — ✅ PASS

- `ruff check`: All checks passed
- `ruff format --check`: Already formatted
- `--help`: Works correctly
- Type hints: `main() -> int`, `analyze_module() -> dict[str, float | int]`
- `if __name__` guard: ✅ (line 129)
- Exit codes: Proper `sys.exit(main())`

### `scripts/eval-content-quality.py` — ✅ PASS

- `ruff check`: All checks passed
- `ruff format --check`: Already formatted
- `--help`: Works correctly
- Type hints on all public functions
- `if __name__` guard: ✅ (line 543)

### Minor Notes

- `eval-content-quality.py` uses `sys.exit()` inside `load_samples()` (lines 177, 197) instead of raising exceptions — acceptable for a CLI script but not ideal for testability
- No `mypy` check run (would require full project config), but visible type annotations look correct

**Verdict: PASS** — Both scripts are clean.

______________________________________________________________________

## Review 2: Architecture & Design

### `scripts/rank-tools.py` — Rating: 3/5

**Scoring formula**: Weighted sum of tool count (log-normalized), doc ratio, error ratio, type ratio. Reasonable as a quick heuristic but has known weaknesses:

- **Programmatic tool detection** (line 41-44): Counts ALL `async def` functions as potential tools if a `register_*` function exists — this overcounts helper functions in modules like `coordination_tools.py`
- **Magic numbers**: `math.log2(25)` (line 56) — assumes max 25 tools, should be configurable
- **Docstring counting** (line 46): Counts `"""` occurrences / 2 — fragile, could be fooled by strings containing triple quotes

### `scripts/eval-content-quality.py` — Rating: 4/5

**Design is solid**: Clean separation of loading, validation, statistics, and reporting. Well-structured for extension.

- **Stub scoring functions** return constant 3 — expected per I15-2 scope, but the stubs have excellent docstrings with implementation ideas
- **Label/score consistency validation** (lines 245-259) is a nice addition — catches data quality issues
- **Minor issue**: `main()` returns `None` (line 510) instead of `int` — inconsistent with rank-tools.py pattern

### `docs/policies/cache-policy.md` — Rating: 4/5

**Tier model is sensible**: L1 (memory) → L2 (SQLite) → L3 (Redis) is standard and appropriate.

- **TTL recommendations are practical**: 300s for adapter caches, 24h for embeddings
- **Identified gaps are real**: Verified all 4 invalidation gaps against source code (see Review 4)

### `docs/reports/tool-ranking-report.md` — Rating: 4/5

**Conclusions supported by data**: Report accurately reflects script output.

- **Deprecation recommendations are reasonable**: Bottom 3 modules (content_ingestion 0.623, oneiric 0.600, worktree 0.642) have genuine quality issues
- **Methodology is transparent**: Weights and formulas clearly documented

**Verdict: GOOD** — Designs are pragmatic and fit existing project patterns. Scoring heuristics are approximate but adequate for governance purposes.

______________________________________________________________________

## Review 3: Documentation Quality

### `docs/reports/tool-ranking-report.md` — Rating: 4/5

- ✅ Clear methodology section
- ✅ Complete ranked table with all 20 modules
- ✅ Deprecation zone clearly marked
- ✅ Actionable next steps (I10-2, I10-3)
- ⚠️ No date on the generated timestamp (just "2026-04-05", no time)

### `docs/policies/cache-policy.md` — Rating: 4/5

- ✅ Well-structured tier model
- ✅ Tables are properly formatted
- ✅ Known gaps section is honest and specific
- ✅ Recommendations section is actionable
- ⚠️ Line number references not verified (see Review 4)
- ⚠️ "Known gaps" section could benefit from priority/severity ratings

### `docs/ml/content-quality-eval-rubric.md` — Rating: 4/5

- ✅ 5 dimensions well-defined with 1-5 scales
- ✅ Examples for each level
- ✅ Inter-annotator guidance included
- ⚠️ Could benefit from anchor examples (real content scored at each level)

### `docs/ml/content-quality-dataset-spec.md` — Rating: 4/5

- ✅ Schema clearly defined with types
- ✅ Collection strategy documented
- ✅ Versioning policy sensible
- ✅ Cross-references to rubric correct
- ⚠️ Example JSON block at line 81 uses `"label": "good"` — matches spec

### `docs/reports/deprecation-migration.md` — ❌ NOT CREATED

- I10-2 was blocked by rate limits — this deliverable is missing

**Verdict: GOOD** — All created docs are well-written and consistent. One deliverable missing (I10-2).

______________________________________________________________________

## Review 4: Data & Accuracy

### Tool Ranking Report vs Script Output — ✅ PASS

- Script and report both show pool_tools.py at #1 (0.898)
- All 20 modules match between script output and report
- Methodology description matches actual code

### Cache Policy File References — ⚠️ PARTIAL

- ✅ `core/cache_manager.py:160` — LRUCache class exists (confirmed with grep)
- ✅ `core/embedding_cache.py:321` — EmbeddingCache class exists (confirmed)
- ✅ `core/cross_repo_blocker.py:157-158` — `_chain_cache` and `_blocker_cache` confirmed
- ✅ `ingesters/content_ingester.py:917` — `@lru_cache` confirmed
- ⚠️ Exact line numbers may drift as code changes — should note this is a snapshot

### Content Quality JSONL — ⚠️ PARTIAL

- ✅ Schema matches dataset spec (required fields all present)
- ✅ 9 valid samples, all pass schema validation
- ❌ **Line 10 has invalid JSON** — `Invalid \escape: line 1 column 187`. Content contains raw `\x00` bytes and `\\n` escape sequences that aren't valid JSON. This is a "corrupted export" test sample but it breaks JSON parsing.
- ✅ Field name is `label` in spec and data (not `human_label` — my validation script was wrong, not the data)

### Eval Script Output — ✅ PASS

- Scores in 1-5 range
- Dimensions match rubric (readability, depth, completeness, accuracy, relevance)
- Label distribution reasonable: 4 good, 2 acceptable, 3 poor
- Stub scoring correctly returns 3 for all dimensions

**Verdict: PASS WITH NOTES** — One JSONL line is invalid (line 10), but the eval script handles it gracefully (reports parse error, continues with 9 valid samples).

______________________________________________________________________

## Review 5: Security & Best Practices

### Security Findings — NONE (CRITICAL/HIGH)

- ✅ No `eval()`, `exec()`, `subprocess`, `pickle`, `__import__` in either script
- ✅ No hardcoded secrets, tokens, or passwords
- ✅ No shell injection vectors
- ✅ Scripts use only stdlib (argparse, json, math, os, re, sys, pathlib, collections)

### Best Practice Issues — LOW

| Issue | File:Line | Severity | Description |
|-------|-----------|----------|-------------|
| No encoding on file open | `rank-tools.py:35` | LOW | `open(path)` without `encoding="utf-8"` — works on macOS but not portable |
| sys.exit() in library code | `eval-content-quality.py:177,197` | LOW | `load_samples()` calls `sys.exit()` — should raise ValueError for testability |
| main() returns None | `eval-content-quality.py:510` | LOW | Should return `int` exit code for consistency |
| No argparse error handling | Both | INFO | argparse handles invalid args, but no validation of JSONL path existence before argparse runs |

### Other Checks

- ✅ Both scripts have `if __name__ == "__main__"` guards
- ✅ No mutable default arguments
- ✅ Proper docstrings on all public functions
- ✅ Uses `pathlib.Path` in eval script (modern Python practice)

**Verdict: PASS** — No security concerns. Minor best practice issues are low severity.

______________________________________________________________________

## Summary

| Review | Verdict | Key Issues |
|--------|---------|------------|
| 1. Lint & Types | ✅ PASS | Clean |
| 2. Architecture | ✅ GOOD (3.8/5 avg) | Magic numbers, overcounting in programmatic detection |
| 3. Documentation | ✅ GOOD (4/5 avg) | I10-2 migration doc missing, no time on timestamps |
| 4. Data Accuracy | ✅ PASS | JSONL line 10 invalid (handled gracefully), line refs may drift |
| 5. Security | ✅ PASS | No security issues, minor best practice nits |

### Action Items

1. **Fix JSONL line 10** — Either remove the corrupted sample or fix the escape sequences
1. **Add `encoding="utf-8"`** to `rank-tools.py:35` file open
1. **Create deprecation-migration.md** (I10-2) — blocked by rate limits, needs retry
1. **Consider making `main()` return int** in eval-content-quality.py for consistency
1. **Note in cache policy** that line numbers are snapshot-specific and may drift
