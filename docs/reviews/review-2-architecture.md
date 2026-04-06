# Review 2 — Architecture & Design

**Date**: 2026-04-05
**Reviewer**: Senior Architect (agent)
**Files**:
- `scripts/rank-tools.py` (130 lines)
- `scripts/eval-content-quality.py` (544 lines)
- `docs/policies/cache-policy.md` (160 lines)
- `docs/reports/tool-ranking-report.md` (82 lines)

**Scope**: Scoring formulas & weight choices, heuristic validity, cache tier model & TTL recommendations, data-conclusion alignment, project-pattern fit, design smells.

---

## Per-Deliverable Ratings

### 1. `scripts/rank-tools.py` — ★★★☆☆ (3/5)

**Formula Assessment**

The scoring formula is:

```
quality = tool_score × 0.4 + doc_ratio × 0.2 + err_ratio × 0.2 + type_ratio × 0.2
```

Where `tool_score = log₂(tools+1) / log₂(25)` and ratios are `count / max(tools, 1)`.

| Aspect | Verdict |
|--------|---------|
| Weight distribution | **Marginal.** 40% on raw tool count dominates. `desktop_automation_tools.py` (23 tools, 0 error handling) outscores `worktree_tools.py` (6 tools, 0 error handling) 0.673 → 0.642 — a module that is objectively less safe wins because it's bigger. Tool count measures *surface area*, not *quality*. |
| Log normalization | **Reasonable.** `log₂(tools+1)/log₂(25)` caps at 25 tools. Prevents huge modules from running away, but the floor is still 0 for single-tool modules. |
| Weight sum | **Correct.** 0.4 + 0.2×3 = 1.0. |

**Heuristic Validity**

| Heuristic | Claim | Reality | Gap |
|-----------|-------|---------|-----|
| `text.count('"""') // 2` | Docstring coverage per tool | Counts *all* triple-quoted strings — class docstrings, module docstrings, multiline constants, f-string fragments. Overcounts significantly. | **High** — inflates doc_ratio |
| `len(re.findall(r"async def \w+\(", text))` | Programmatic tool count | Counts *all* async functions, not just registered tools. Internal helpers, callbacks, private methods all inflate the count. | **High** — inflates tool count and dilutes all ratios |
| `len(re.findall(r"def\s+\w+\s*\([^)]*\)\s*->", text))` | Type-safe function ratio | Counts *all* functions with return type hints — helpers, private methods, test fixtures in tool files. | **Medium** — inflates type_ratio |
| `len(re.findall(r"^\s*try:", text, re.MULTILINE))` | Error handling per tool | Mostly correct but counts `try/except` in helpers and class methods, not just tool functions. | **Low** — acceptable approximation |

**Design Smells**

- **Gaming potential**: A module could inflate its score by adding trivially-typed helper functions with docstrings and try blocks, none of which improve actual tool quality.
- **Floor score quirk**: A module with 0 tools but 1 docstring, 1 try block, and 1 typed function scores 0.600 — the deprecation threshold. This is accidental, not intentional.
- **No AST parsing**: All heuristics are regex-based. A lightweight `ast` walk would give accurate tool/docstring/error counts with minimal complexity cost.

**Recommendations**

1. Use `ast.parse()` instead of regex — eliminates all four heuristic gaps above.
2. Reduce tool-count weight to 0.25, redistribute to error_handling (0.25) and add a *test_coverage* signal (0.10).
3. Count only top-level async defs decorated with `@server.tool()` or `@mcp.tool()` as tools.

---

### 2. `scripts/eval-content-quality.py` — ★★★☆☆ (3/5)

**Structure & Architecture**

The script has a clean three-phase pipeline: load → validate → analyze/report. The `--validate-only` and `--no-auto` flags are good CLI design. Schema validation with label/score consistency checking is a valuable data-quality guard.

**Scoring Functions — All Stubs**

All five scoring functions (`score_readability`, `score_depth`, `score_completeness`, `score_accuracy`, `score_relevance`) are stubs returning `3`. The module is 544 lines, but ~100 of those are TODO comments and docstrings for functions that do nothing.

| Concern | Impact |
|---------|--------|
| The automated scoring section (`run_automated_scoring`) prints a comparison table where every row predicts "acceptable" | Misleading output — implies the framework works when it doesn't |
| `LABEL_THRESHOLDS` dict (line 41) is defined but never referenced | Dead code |
| No test coverage for the stubs | If real implementations are added later, there's no regression safety net |

**Positive Aspects**

- `validate_sample()` is well-implemented: checks required fields, label validity, score range, and cross-field consistency (label vs. mean score).
- `compute_statistics()` produces useful aggregate views (per-label dimension means, source type distribution).
- The per-sample detail table with truncated IDs is a good reporting format.

**Recommendations**

1. Remove the automated scoring section entirely until real scorers exist, or gate it behind a `--dry-run` flag with a loud warning.
2. Implement at least `score_readability` using Flesch-Kincaid (via `textstat` or a simple syllable counter) — it's the easiest dimension to automate and the most immediately useful.
3. Delete `LABEL_THRESHOLDS` or use it in the label/score consistency check.
4. Add unit tests for `validate_sample()` — the consistency checks are the most valuable logic in the file.

---

### 3. `docs/policies/cache-policy.md` — ★★★★☆ (4/5)

**Tier Model**

The L1 (memory) / L2 (SQLite) / L3 (Redis) model is standard, sensible, and matches the actual codebase architecture. The `EmbeddingCache` genuinely implements this two-tier pattern with circuit breaker and singleflight — the policy accurately describes it.

**TTL Recommendations**

| Recommendation | Code Reality | Assessment |
|---------------|-------------|------------|
| Adapter resolution: 300s | `ResolutionCache(ttl_seconds=300)` ✅ | Correct |
| Adapter discovery: 300s | `_cache_ttl_seconds = 300` ✅ | Correct |
| Embedding L2 (Redis): 86,400s ± 20% jitter | Configurable, default matches ✅ | Correct |
| Embedding L1: None (bounded by LRU) | `LRUCache(max_size=50000)` ✅ | Correct |
| Content ingester: Process lifetime | `@lru_cache` (no maxsize) ✅ | Correct |
| Tree-sitter: None (content-hash) | Content-hash key ✅ | Correct |
| **Pool search: None (manual)** | **`CACHE_TTL = timedelta(minutes=5)`** | **❌ Factual error** |
| CrossRepoBlocker: None | Plain dict, no TTL ✅ | Correct |

**Factual Error — Pool Search Cache TTL**

The policy states pool search cache has "None (manual)" TTL and recommends adding a 5-minute TTL in I11-2. The actual code at `memory_aggregator.py:145` already implements `self.CACHE_TTL = timedelta(minutes=5)` with age-based expiry at line 522. The cache has both TTL expiry *and* manual clear. This recommendation is redundant and the TTL table entry is wrong.

**Known Gaps Section — Honest and Valuable**

The four identified gaps (CrossRepoBlocker unbounded, OTel no TTL, content ingester unbounded, pool search "no TTL") are real risks. Three of four are correct; the pool search entry is wrong as noted above.

**Observability Gap Analysis — Good**

The hit/miss tracking matrix (CacheManager ✅, EmbeddingCache ✅, Tree-sitter ✅, AdapterResolution ⚠️, CrossRepoBlocker ❌, OTel ❌, Content ingester ❌) accurately reflects the codebase. The recommendation to unify stats reporting is sound.

**Recommendations**

1. Fix pool search cache entry: TTL is `300s (5 min)`, not "None (manual)". Remove from "Known Gaps" and from I11-2 recommendation #3.
2. Add a "Last verified" date column to the L1/L2/L3 tables — caches drift faster than documentation.
3. Consider adding cache key collision examples for the "Medium" risk entry (pool search `query:limit`).

---

### 4. `docs/reports/tool-ranking-report.md` — ★★☆☆☆ (2/5)

**Data-Conclusion Alignment — Stale Report**

Running `scripts/rank-tools.py` on the current codebase produces significantly different results from the report:

| Module | Report Score | Current Score | Delta |
|--------|:-----------:|:-------------:|:-----:|
| `repository_messaging_tools.py` | 0.600 | 0.858 | +0.258 |
| `session_buddy_tools.py` | 0.600 | 0.858 | +0.258 |
| `git_analytics.py` | 0.600 | 0.842 | +0.242 |
| `otel_tools.py` | 0.600 | 0.800 | +0.200 |

The report's core thesis — "5 modules are stuck at the floor score of 0.600 due to programmatic registration" — is **no longer true**. The script now detects tools in these modules (either the script was updated, or the modules were refactored). Four of the five "floor" modules now rank in the top half.

**Consequences**

- The "Bottom 10-20% — Deprecation Candidates (I10-3)" section lists 7 modules, but 4 of them no longer belong there.
- Recommendation #3 ("Consolidate registration patterns — migrate programmatic registrations to `@mcp.tool()` decorators") is based on a scoring artifact that has been resolved.
- The summary statistics ("125 via `@mcp.tool()` + ~22 via programmatic") are stale.
- The average and median scores are wrong.

**What's Good**

- Methodology description is clear and the signal/weight table is well-formatted.
- The recommendation to add error handling to `worktree_tools.py` and `content_ingestion_tools.py` remains valid (both still have 0 try blocks).
- The overlap analysis between `repository_messaging_tools.py` and `coordination_tools.py` is a useful architectural observation regardless of scores.

**Recommendations**

1. **Regenerate the report immediately** — `uv run python scripts/rank-tools.py > docs/reports/tool-ranking-report.md` (or pipe through the script and update the markdown).
2. Add a `--markdown` flag to `rank-tools.py` that outputs the full report with methodology and summary stats, not just the table — so the report can be regenerated automatically.
3. Pin the report to a specific git commit hash for reproducibility.

---

## Cross-Cutting Observations

### Pattern Fit

| Pattern | Consistent? | Notes |
|---------|:-----------:|-------|
| Script invocation (`uv run python scripts/...`) | ✅ | Matches existing scripts |
| Review format (docs/reviews/review-N-*.md) | ✅ | Follows established convention |
| Markdown tables for structured data | ✅ | Consistent with project docs |
| Exit code discipline | ⚠️ | `rank-tools.py` returns `int` correctly; `eval-content-quality.py` returns `None` (see review-5 H-1) |

### Design Smells Summary

| # | Smell | Severity | Location |
|---|-------|----------|----------|
| D-1 | Stale report with wrong conclusions driving potentially harmful architectural decisions | **High** | `tool-ranking-report.md` |
| D-2 | Factual error in cache policy (pool search TTL) leading to redundant recommendation | **Medium** | `cache-policy.md` |
| D-3 | Regex-based heuristics instead of AST for code analysis — overcounts across the board | **Medium** | `rank-tools.py` |
| D-4 | 544-line file where the core logic (scoring) is entirely stubs | **Medium** | `eval-content-quality.py` |
| D-5 | No automated pipeline to keep report in sync with script output | **Low** | Tool ranking workflow |

---

## Overall Verdict

| Deliverable | Rating | Summary |
|-------------|:------:|---------|
| `scripts/rank-tools.py` | ★★★☆☆ | Reasonable approach, heuristics need AST migration, weights overweight raw tool count |
| `scripts/eval-content-quality.py` | ★★★☆☆ | Well-structured scaffold with strong validation; scoring is all stubs, automated comparison is misleading |
| `docs/policies/cache-policy.md` | ★★★★☆ | Accurate tier model, good gap analysis, one factual error on pool search TTL |
| `docs/reports/tool-ranking-report.md` | ★★☆☆☆ | **Stale data invalidates core conclusions. Must be regenerated.** |

**Overall: ★★★☆☆ (3/5) — Acceptable foundation, needs targeted fixes before driving decisions.**

The cache policy is the strongest deliverable and ready to use after fixing the pool search TTL entry. The ranking script is a useful governance tool but needs AST-based heuristics. The evaluation script is a prototype that should ship only after at least one real scorer is implemented. The ranking report is actively misleading in its current form and should be regenerated before any I10 deprecation decisions are made.
