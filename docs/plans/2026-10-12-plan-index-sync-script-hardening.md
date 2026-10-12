---
status: draft
role: implementation
kind: plan
date: 2026-10-12
last_reviewed: 2026-10-12
superseded_by: null
blocks_on: []
topic: lifecycle
title: "Plan Index Sync Script Hardening — Draft Repairs + Regex + Read-Full-File"
---

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:test-driven-development` — each Phase writes a failing test first. The 3 phases are independent; can be merged in any order, but commit separately per Phase to keep the diff readable.

# Plan Index Sync Script Hardening — Draft Repairs + Regex + Read-Full-File

**Goal:** make `python scripts/regenerate_plan_index.py` succeed end-to-end on the current `main` working tree, and harden the script so the same class of failure (multiline YAML values with unquoted colons inside frontmatter-bearing `.md` files) cannot recur. The 3 phases are independent and each ships in its own commit.

**Background:** the script's frontmatter discovery has two latent bugs that interact with 3 pre-existing draft plans in `docs/plans/drafts/` whose frontmatter contains unquoted multiline values with embedded `:` characters. Discovered during the 2026-10-12 plan audit (commit `982380e7`): the 3 broken drafts cause `regenerate_plan_index.py` to fail with `yaml.scanner.ScannerError: mapping values are not allowed here` at line 14, column 149. The script bug surfaces the latent data bug; fixing only one side is not durable.

**Architecture:** three independent fixes — (1) quote the offending values in the 3 draft files, (2) replace the non-greedy regex with a line-anchored parser that matches the FIRST `---` line not followed by additional content, (3) read the full file (not just 4096 bytes) during discovery so the regex sees the real closing fence.

**Tech Stack:** Python 3.14, PyYAML, pytest. No new dependencies.

**Parent context:** bug surfaced 2026-10-12 during the plan audit that produced commit `982380e7` ("chore(docs): refresh 3 active plans + add Phase 1b test backfill"). That commit's body notes the script failure is pre-existing and not caused by the commit; this plan closes the loop.

## 1. Outcome

`python scripts/regenerate_plan_index.py` exits 0 against the current `main` working tree. `docs/plans/PLAN_INDEX.md` is regenerated cleanly and includes all valid plans and all 3 draft plans (now repaired). Subsequent commits that touch any `docs/plans/**/*.md` file will not break the script, even if the body content contains `---` markers or colon-containing multiline values.

**Concrete success signals:**
1. `python scripts/regenerate_plan_index.py` exits 0 (currently fails).
2. `grep -L '^---$' docs/plans/drafts/*.md | wc -l` returns 0 (all 3 drafts have a closing `---` fence on its own line).
3. `pytest tests/unit/scripts_tests/test_audit_plan_index.py tests/integration/regenerate_plan_index/ -v` exits 0 with at least 4 new tests (1 per Phase plus 1 integration).
4. The 3 drafts' frontmatter values are semantically equivalent to the original (round-trip parse produces equal dicts modulo whitespace).

## 2. Goals

1. **Repair the 3 broken drafts** in `docs/plans/drafts/` so their frontmatter parses as valid YAML. Use quoted scalars (`>`, `|`, or `"..."`) where multiline values contain `:` or other YAML-significant characters. Do not change the semantic content.
2. **Replace the non-greedy regex** in `scripts/regenerate_plan_index.py:_FRONTMATTER_RE` with a line-anchored parser that finds the FIRST line that is exactly `---` (or `---` with trailing whitespace) after the opening fence. The new parser is robust to `---` markers in the body.
3. **Read the full file** in `_has_frontmatter` instead of truncating to 4096 bytes. The 4096 limit was a cheap pre-filter; it introduces the same body-`---` collision class for any plan with a long frontmatter (> 4 KiB) — currently none exist, but a future plan could.
4. **Add regression tests** for each Phase so the bug class cannot recur silently.

## 3. Non-Goals

1. **Re-running the script and committing the regenerated `PLAN_INDEX.md`** is the natural follow-up but **not** part of this plan. The script's commit-time integration is a separate concern (per `mcp-backend-wiring-discipline.md` for tooling; this plan is about correctness, not automation).
2. **Repairing the 3 broken drafts' semantic content** (e.g., rewriting the `delivered:` / `activation_signal:` / `unblocks:` prose to be cleaner) — out of scope. We quote the existing values; we don't rewrite them.
3. **Touching `scripts/regenerate_plan_index.py`'s other code paths** (e.g., `discover_stores`, `_coerce_date`, the YAML-emit pass). Scope is the frontmatter-extraction function and its callers.
4. **Adding a frontmatter validation pre-commit hook** — that's a separate plan-level concern (per the existing `2026-07-16-frontmatter-validator-wiring-plan.md`).
5. **Migrating drafts out of `docs/plans/drafts/`** — drafts subdirectory is recognized by the script (`DRAFTS_PREFIX = "docs/plans/drafts/"` at line 141; routed to a different code path at line 234). Moving them would be a separate concern.

## 4. Current Findings

### 4.1 The 3 broken drafts (Phase 1 data fix)

`docs/plans/drafts/2026-09-27-akosha-eval-metric-sink.md` — the first 4096 bytes of this file include frontmatter with multiline unquoted values:

```yaml
delivered:
  - phase_1: commit f09035f (akosha local main, 2026-09-29) — REQ-MS-001 + REQ-MS-003 + REQ-MS-006. MCP write-side tool `akosha_add_eval_metric`, suffixed metric_name guard `is_eval_metric_name(name)`, `AddEvalMetricRequest` Pydantic schema. In-memory cache only; persistence is Phase 2.
  - phase_2: commit d07c473 (akosha local main, 2026-09-29) — REQ-MS-002 + REQ-MS-004 + REQ-MS-005. TimeSeriesAnalytics SQLite write-through backing: `metric_points` table indexed by `metric_name`, PK `(metric_name, timestamp, system_id)`, ...
```

The `metric_points` value is followed by content with a `: ` (colon-space) pattern that the YAML parser interprets as a key-value boundary. The `delivered:` block becomes malformed at that point.

Same pattern affects:
- `docs/plans/drafts/2026-09-27-akosha-tool-call-feed-lifecycle.md` — error at line 17, column 209, mentioning `OtelTraceIngester`.
- `docs/plans/drafts/2026-09-26-eval-methodology.md` — error at line 17, column 442, mentioning a calendar reference.

All 3 share the same root cause: multiline unquoted YAML scalar values that contain `:` characters.

### 4.2 The regex bug (Phase 2 script fix)

`scripts/regenerate_plan_index.py:148`:

```python
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)
```

The non-greedy `(.*?)` matches up to the FIRST `\n---` after the opener. For files where the body has `---` markers within 4096 bytes of the file start, the regex incorrectly matches body content as the closer. The 3 broken drafts happen to be long enough that their body's first `---` line falls within 4096 bytes, but the failure mode would occur for ANY draft with body `---` content regardless of length, because the lazy quantifier always picks the first closer.

The current regex is also a pre-existing footgun: a future plan that opens with a long frontmatter (> 4 KiB) and a short body with `---` would fail. Both bugs must be fixed independently.

### 4.3 The 4096-byte truncation (Phase 3 script fix)

`scripts/regenerate_plan_index.py:284`:

```python
with path.open("rb") as fh:
    head = fh.read(4096)
```

The 4096-byte truncation is a cheap pre-filter. For a corpus of ~200 plan files averaging 5 KB each, reading the full file adds ~1 MB of I/O per `discover_stores` run — negligible. The downside of truncating is that ANY logic that depends on full content (Phase 2's regex, future plan-body parsing) silently misbehaves for files > 4 KiB. The 3 broken drafts are 5-9 KB each.

### 4.4 Existing test coverage

- `tests/unit/scripts_tests/test_audit_plan_index.py` — covers the *audit* script, not the *regenerate* script.
- `tests/integration/regenerate_plan_index/` — exists per `ls`. Inspect on Phase 1 start; this plan adds tests, doesn't replace the directory.

No existing test covers the frontmatter-extraction edge cases (multiline values, body `---` markers, > 4 KiB frontmatter).

### 4.5 Interaction between phases

The 3 phases are independent. Phase 1 alone (data fix) unblocks the script today. Phases 2 and 3 are forward-compatible hardening. All 3 should land in `main` because the bugs compound: Phase 1 alone would mask a recurrence of Phase 2's bug class in a future plan, and Phase 2 alone would still break on the existing drafts. Doing all 3 is the only durable fix.

## 5. Requirements

```yaml
requirements:
  - id: REQ-IDX-001
    title: "All 3 broken drafts have YAML-valid frontmatter; semantic content preserved"
  - id: REQ-IDX-002
    title: "extract_frontmatter uses line-anchored parser; body `---` markers do not match"
  - id: REQ-IDX-003
    title: "_has_frontmatter reads the full file (not just 4096 bytes)"
  - id: REQ-IDX-004
    title: "Regression test: frontmatter with multiline unquoted `:`-containing value parses"
  - id: REQ-IDX-005
    title: "Regression test: frontmatter with body `---` markers does not mis-extract"
  - id: REQ-IDX-006
    title: "Regression test: frontmatter > 4 KiB parses correctly"
  - id: REQ-IDX-007
    title: "`python scripts/regenerate_plan_index.py` exits 0 against current main working tree"
```

Every Phase's Integration Contract below links back to the REQ IDs it fulfils.

## 6. Implementation Phases

### Phase 1: Repair the 3 broken drafts (data fix)

**Goal:** quote the offending values in `docs/plans/drafts/*.md` so the frontmatter parses as valid YAML. Single Phase; one commit per file (3 commits total) to keep the diff readable.

#### Integration Contract ← Phase 1
- **Triggered from**: `python -c "import yaml, re; [yaml.safe_load(re.match(r'\A---\s*\n(.*?)\n---\s*(?:\n|$)', open(p).read(), re.DOTALL).group(1)) for p in ['docs/plans/drafts/2026-09-27-akosha-eval-metric-sink.md', 'docs/plans/drafts/2026-09-26-eval-methodology.md', 'docs/plans/drafts/2026-09-27-akosha-tool-call-feed-lifecycle.md']]"` exits 0 (currently raises `ScannerError`).
- **Returns to / updates**: 3 `.md` files in `docs/plans/drafts/`. No source-file changes.
- **Demonstrable by**: the snippet above exits 0 after the commit. `python scripts/regenerate_plan_index.py` advances past these 3 files (it may still fail on other files — that's the script bug, not this Phase's concern; Phase 2 closes that).
- **Rollback signal**: N/A (data-only fix; `git revert`).
- **Observability added**: each of the 3 commits has a "Frontmatter repair" message noting which YAML field was quoted.

(Implements REQ-IDX-001, REQ-IDX-004.)

**Tasks (TDD-light, one step per file — 5-10 minutes each):**

- [ ] **Task 1.1: Add the regression test for multiline unquoted values**
  - Create `tests/unit/scripts_tests/test_regenerate_plan_index_frontmatter.py` with a test that loads each of the 3 drafts and asserts the frontmatter parses as a dict.
  - The test currently FAILS with `yaml.scanner.ScannerError`; after Phase 1 commits it passes.
  - The test uses `extract_frontmatter` (or a re-implementation) so it exercises the same parsing path the script uses.
  - Mark with `@pytest.mark.req(["REQ-IDX-001", "REQ-IDX-004"])`.

- [ ] **Task 1.2: Repair `docs/plans/drafts/2026-09-27-akosha-eval-metric-sink.md`**
  - The 3 offending fields are: `delivered:`, `activation_signal:`, and any other multiline value with a `:`. Read the file first, identify each.
  - Convert to YAML block scalar (`>` for folded or `|` for literal) OR quoted scalar (`"..."` with `\n` for newlines). Prefer `>` for prose where newlines should become spaces; prefer `|` for prose where newlines must be preserved.
  - Do NOT change the prose content. The fix is purely syntactic.
  - Re-run the test from Task 1.1; assert it passes for this file alone.

- [ ] **Task 1.3: Repair `docs/plans/drafts/2026-09-27-akosha-tool-call-feed-lifecycle.md`**
  - Same pattern. Identify the offending field (line 17, column 209 — the `OtelTraceIngester` block per the script error).
  - Apply the same quoting fix.
  - Re-run the test; assert it passes.

- [ ] **Task 1.4: Repair `docs/plans/drafts/2026-09-26-eval-methodology.md`**
  - Same pattern. Identify the offending field (line 17, column 442 — calendar reference per the script error).
  - Apply the same quoting fix.
  - Re-run the test; assert it passes.

- [ ] **Task 1.5: Three separate commits (one per file)**
  ```bash
  cd /Users/les/Projects/mahavishnu

  git add docs/plans/drafts/2026-09-27-akosha-eval-metric-sink.md tests/unit/scripts_tests/test_regenerate_plan_index_frontmatter.py
  git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m \
      "fix(docs/drafts): quote multiline unquoted values in akosha-eval-metric-sink frontmatter (REQ-IDX-001)"

  git add docs/plans/drafts/2026-09-27-akosha-tool-call-feed-lifecycle.md
  git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m \
      "fix(docs/drafts): quote multiline unquoted values in akosha-tool-call-feed-lifecycle frontmatter (REQ-IDX-001)"

  git add docs/plans/drafts/2026-09-26-eval-methodology.md
  git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m \
      "fix(docs/drafts): quote multiline unquoted values in eval-methodology frontmatter (REQ-IDX-001)"
  ```

  Note: the test file goes in with the FIRST commit; the remaining 2 commits only touch the data fix, which keeps the test as the "always-passing" canary.

### Phase 2: Line-anchored frontmatter parser (script fix)

**Goal:** replace the non-greedy regex in `_FRONTMATTER_RE` (and the function that uses it, `extract_frontmatter`) with a line-anchored parser. The new parser finds the FIRST line that is exactly `---` (modulo trailing whitespace) after the opening fence, and does not match body `---` content.

#### Integration Contract ← Phase 2
- **Triggered from**: `python scripts/regenerate_plan_index.py` after the commit lands.
- **Returns to / updates**: `scripts/regenerate_plan_index.py:148` (`_FRONTMATTER_RE`) and `scripts/regenerate_plan_index.py:190-203` (`extract_frontmatter`). Backward compatible — the function's signature and return type are unchanged.
- **Demonstrable by**: a new test (`test_extract_frontmatter_with_body_horizontal_rule_does_not_mis_extract`) that constructs a synthetic `.md` file with body `---` markers and asserts only the real frontmatter is returned. Plus the existing pre-Phase-1 broken drafts (now repaired by Phase 1) continue to parse via the new parser.
- **Rollback signal**: any of the new regression tests fails; `regenerate_plan_index.py` exits non-zero on `main`.
- **Observability added**: the new parser is slightly slower (O(n) over lines, not O(n) over the regex backtracking); not user-visible.

(Implements REQ-IDX-002, REQ-IDX-005.)

**Tasks (TDD, one step per action — 5-10 minutes each):**

- [ ] **Task 2.1: Add the failing test for body `---` markers**
  - In `tests/unit/scripts_tests/test_regenerate_plan_index_frontmatter.py` (created in Phase 1), add a test that passes a string with:
    ```
    ---
    status: active
    ---
    # Title

    Some body with a `---` in the middle.

    ---

    More body.
    ```
    and asserts the parser returns only the frontmatter (`{"status": "active"}`), not the body content.
  - Test currently FAILS (regex matches the body's first `---`).
  - Mark with `@pytest.mark.req(["REQ-IDX-002", "REQ-IDX-005"])`.

- [ ] **Task 2.2: Replace the regex with a line-anchored parser**
  - In `scripts/regenerate_plan_index.py`, replace the `_FRONTMATTER_RE` constant and the `extract_frontmatter` function body with a line-anchored implementation. Suggested shape:
    ```python
    def extract_frontmatter(text: str, yaml_module: Any) -> dict[str, Any] | None:
        """Return the parsed YAML mapping from `text`, or None when no
        frontmatter block is present. Returns {} for an empty `---` block.

        The parser is line-anchored: it splits the text on newlines and
        looks for the FIRST line equal to `---` (modulo trailing
        whitespace) after the opening fence. Body content that happens
        to contain `---` lines is NOT mistaken for the closer.
        """
        if not text:
            return None
        lines = text.splitlines()
        if not lines or lines[0].rstrip() != "---":
            return None
        # Find the next line that is exactly `---` (closing fence).
        for i in range(1, len(lines)):
            if lines[i].rstrip() == "---":
                frontmatter_text = "\n".join(lines[1:i])
                try:
                    parsed = yaml_module.safe_load(frontmatter_text)
                except yaml_module.YAMLError:
                    return None
                if parsed is None:
                    return {}
                return parsed if isinstance(parsed, dict) else None
        return None  # No closing fence found.
    ```
  - This change obsoletes the `_FRONTMATTER_RE` constant. Remove it (or mark it deprecated with a comment). Do NOT remove the constant name from any import or test reference without first grepping for usages.
  - Note: the parser now consumes ALL lines until the closing fence, including blank lines. The current regex uses `(?:\n|$)` which is more permissive about the final newline. Verify against a fixture with `---` at EOF (no trailing newline) — the line-split approach handles that.
  - Re-run Task 2.1's test; assert it passes.
  - Re-run Task 1.1's test (multiline unquoted values); assert it still passes.

- [ ] **Task 2.3: Commit**
  ```bash
  cd /Users/les/Projects/mahavishnu

  git add scripts/regenerate_plan_index.py tests/unit/scripts_tests/test_regenerate_plan_index_frontmatter.py
  git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m \
      "fix(scripts/regenerate_plan_index): replace non-greedy regex with line-anchored parser (REQ-IDX-002)

      The previous regex matched the first '---' line in the truncated 4096-byte
      head, which incorrectly matched body '---' markers as the frontmatter
      closer. The new parser splits the text on newlines and finds the FIRST
      line equal to '---' (modulo trailing whitespace) after the opening
      fence, so body content with '---' is never mistaken for the closer."
  ```

### Phase 3: Read full file in `_has_frontmatter` (script fix)

**Goal:** change `_has_frontmatter` to read the full file instead of truncating to 4096 bytes. The 4096 truncation was a cheap pre-filter that introduced a latent bug for any plan with a long frontmatter (> 4 KiB).

#### Integration Contract ← Phase 3
- **Triggered from**: `python scripts/regenerate_plan_index.py` after the commit lands.
- **Returns to / updates**: `scripts/regenerate_plan_index.py:282-302` (`_has_frontmatter`). Reads the full file; I/O cost is ~1 MB per script run, negligible.
- **Demonstrable by**: a new test that constructs a synthetic `.md` file with a 6-KiB frontmatter (no body `---` markers) and asserts `_has_frontmatter` returns True. With the 4096 truncation, this test FAILS today.
- **Rollback signal**: I/O regression (script becomes noticeably slow) — measured via a single `time python scripts/regenerate_plan_index.py` before/after.
- **Observability added**: none (read amount is an internal concern).

(Implements REQ-IDX-003, REQ-IDX-006.)

**Tasks (TDD, one step per action — 5 minutes each):**

- [ ] **Task 3.1: Add the failing test for > 4 KiB frontmatter**
  - In `tests/unit/scripts_tests/test_regenerate_plan_index_frontmatter.py`, add a test that creates a 6-KiB frontmatter (a long description field, no `---` in the body) and asserts the frontmatter parses correctly.
  - Test currently FAILS (truncated regex sees only the first 4096 bytes, which may not include the closing `---`).
  - Mark with `@pytest.mark.req(["REQ-IDX-003", "REQ-IDX-006"])`.

- [ ] **Task 3.2: Remove the 4096 truncation**
  - In `scripts/regenerate_plan_index.py:282-302`, change `_has_frontmatter` to read the full file:
    ```python
    def _has_frontmatter(path: Path, yaml_module: Any) -> bool:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        if not text.startswith("---"):
            return False
        return extract_frontmatter(text, yaml_module) is not None
    ```
  - Note: this requires importing `Path` (already imported) and removes the cheap pre-filter. The script walks ~200 files; reading each fully is ~1 MB total. Verified during planning — not a regression.
  - Re-run Task 3.1's test; assert it passes.
  - Re-run Tasks 1.1, 2.1's tests; assert they still pass.

- [ ] **Task 3.3: Commit**
  ```bash
  cd /Users/les/Projects/mahavishnu

  git add scripts/regenerate_plan_index.py tests/unit/scripts_tests/test_regenerate_plan_index_frontmatter.py
  git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m \
      "fix(scripts/regenerate_plan_index): read full file in _has_frontmatter (REQ-IDX-003)

      The previous implementation read only the first 4096 bytes, which
      mis-extracted frontmatter for any plan with a > 4 KiB frontmatter
      block. Read the full file instead; the I/O cost is negligible
      (corpus ~200 files, ~1 MB total)."
  ```

## 7. Required Code Changes

```yaml
mahavishnu:
  - path: docs/plans/drafts/2026-09-27-akosha-eval-metric-sink.md
    change: EDIT — quote the multiline unquoted values in `delivered:`, `activation_signal:`, and any other `:`-containing field
  - path: docs/plans/drafts/2026-09-27-akosha-tool-call-feed-lifecycle.md
    change: EDIT — same quoting fix
  - path: docs/plans/drafts/2026-09-26-eval-methodology.md
    change: EDIT — same quoting fix
  - path: scripts/regenerate_plan_index.py
    change: REPLACE `_FRONTMATTER_RE` regex and `extract_frontmatter` body with a line-anchored parser (Phase 2); change `_has_frontmatter` to read the full file (Phase 3)
  - path: tests/unit/scripts_tests/test_regenerate_plan_index_frontmatter.py
    change: NEW — 4 regression tests (1 per Phase 1 file + body `---` + > 4 KiB frontmatter)
```

## 8. Validation Matrix

| Tool / Command | Expected outcome | Evidence |
|---|---|---|
| `python scripts/regenerate_plan_index.py` | Exit 0 (after all 3 Phases) | shell exit 0; `docs/plans/PLAN_INDEX.md` regenerated |
| `python -c "import yaml, re; yaml.safe_load(re.match(r'\A---\s*\n(.*?)\n---\s*(?:\n\|\$)', open('docs/plans/drafts/2026-09-27-akosha-eval-metric-sink.md').read(), re.DOTALL).group(1))"` | Exit 0 after Phase 1 | shell exit 0 |
| `pytest tests/unit/scripts_tests/test_regenerate_plan_index_frontmatter.py -v` | All 4+ tests pass | pytest stdout |
| `pytest tests/integration/regenerate_plan_index/ -v` | Existing tests still pass | pytest stdout |
| `time python scripts/regenerate_plan_index.py` before vs. after Phase 3 | < 1.5x slowdown | shell `time` output |
| `git grep _FRONTMATTER_RE scripts/` | 0 hits after Phase 2 (constant removed) | shell exit 1 |
| `python -c "from scripts.regenerate_plan_index import extract_frontmatter, _has_frontmatter; print('ok')"` | Exit 0 (no import breakage) | shell exit 0 |

## 9. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Quoting a value changes its semantic content (e.g., `>` folds newlines into spaces) | medium | Phase 1 Task 1.2-1.4 each verify the parsed dict equals the original modulo whitespace. If a value's whitespace semantics matter, use `|` (literal block scalar) instead of `>` (folded). |
| A new test fixture (the 6-KiB frontmatter) makes `_has_frontmatter` slow on CI | low | The fixture is in a unit test, not a loop; the I/O cost is bounded. If it shows up as flaky, mark the test `@pytest.mark.timeout(5)`. |
| The 3 drafts' authors object to the syntactic change | low | The change is documented in the commit message and the 3 files' frontmatter is now self-documenting (the YAML keys are explicit). No semantic change. |
| Phase 2's line-anchored parser breaks for some legitimate frontmatter with `---` mid-value | low | The parser only matches lines that are EXACTLY `---` (modulo trailing whitespace). A legitimate value that contains `---` on its own line would be unusual but possible; verify against the existing 200+ plans that nothing breaks. |
| The 4096-byte pre-filter was load-bearing for a performance reason I haven't identified | very low | The corpus is ~200 files averaging 5 KB; 1 MB total is well within typical git-hook budgets. Re-time in Phase 3 Task 3.3. |
| The 3 drafts are not actually draft (they may be "active" plans) and the quoting change is a behavior change | low | The drafts subdirectory is routed to a different code path (line 234). If they were active, they would live in `docs/plans/`. The quoting is purely syntactic. |

## 10. Decision Rule

Plan is **done enough** when:
1. All 3 Phases merged to `main` on this repo in 5 commits (1 data + 1 data + 1 data + 1 script + 1 script).
2. `python scripts/regenerate_plan_index.py` exits 0 against `main` (currently fails).
3. `pytest tests/unit/scripts_tests/test_regenerate_plan_index_frontmatter.py -v` passes with ≥ 4 tests.
4. The 3 drafts' frontmatter is semantically equivalent to the pre-Phase-1 state (round-trip parse produces equal dicts modulo whitespace).
5. `git grep _FRONTMATTER_RE scripts/` returns 0 hits (constant removed after Phase 2).

Plan is **not done** when:
- The script still fails on the 3 drafts after Phase 1 commits (means the quoting fix was incomplete).
- The script still fails on synthetic body `---` content after Phase 2 commits.
- The script still fails on > 4 KiB frontmatter after Phase 3 commits.
- Any of the 5 commits touches a file outside the `## 7. Required Code Changes` list (keep the diff narrow).

## 11. References

- `docs/plans/2026-10-12-mcp-common-test-backfill.md` — sibling plan created in the same session; uses the same `last_reviewed: 2026-10-12` cycle.
- `docs/plans/2026-07-16-frontmatter-validator-wiring-plan.md` — related (frontmatter validation as a CI gate); this plan does not duplicate that scope.
- `docs/plans/2026-07-26-shared-frontmatter-validator.md` — related (validator implementation); this plan does not modify the validator.
- `scripts/regenerate_plan_index.py:148` (`_FRONTMATTER_RE`) and `:282-302` (`_has_frontmatter`) — the two functions this plan modifies.
- `scripts/regenerate_plan_index.py:1312` — the line number of the script's `main()` entry point (where the traceback ends today).
- `tests/integration/regenerate_plan_index/` — existing integration test directory; Phase 2 and 3 should not break anything there.
- `mcp-backend-wiring-discipline.md` — Bodai-wide rule that integration tests are required; this plan adds unit tests for the frontmatter extraction path. Integration coverage already exists.
- `feedback-keep-plan-files-tracked.md` — `git add docs/plans/*.md` first; Phase 1's commits follow this pattern.
- `feedback-no-backwards-compat-pre-1.0.md` — no deprecation windows; the `_FRONTMATTER_RE` constant is removed cleanly in Phase 2, not kept as a shim.
- `bodai-pre-1.0-merge-policy.md` — direct-to-main merge rule; all 5 commits in this plan go directly to `main`.
- `crackerjack.tools.plan_index_sync` (referenced in `docs/plans/PLAN_INDEX.md` header) — the fast-hook that calls this script on every commit. The hook will pick up the script fix on the next run after Phase 2 + 3 land.
