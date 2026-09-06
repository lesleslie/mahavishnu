# Crackerjack: scripts/ and examples/ Coverage in Fast Hooks

**Date:** 2026-09-05
**Status:** Approved for implementation
**Path:** Architectural change to Crackerjack's fast-hook coverage

---

## 1. Context

Crackerjack's fast hooks currently target only `./crackerjack` (the package directory). The `scripts/` and `examples/` directories in every Bodai-maintained repo are explicitly skipped — by tool-command hardcoding, pytest test path, and coverage source scope. The user wants these directories brought into fast-hook coverage "at the very least," with compatibility across all Bodai repos that run Crackerjack.

An audit of 14 Bodai repos revealed:

- **333 ruff violations** in `scripts/` and `examples/` across the ecosystem
- **5 repos already clean** (akosha, excalidraw-mcp, fastblocks-ui, opera-cloud-mcp, raindropio-mcp)
- **Heavy offenders**: mahavishnu (134), session-buddy (117), oneiric (30)
- **7 universal rules** account for **63.7%** of all violations
- **`audit_type_checking_runtime_refs.py`** itself ships in 7 repos with the same 10-12 violations per copy — a recurring source of 84 violations

---

## 2. Goals

1. **Add `scripts/` and `examples/` to Crackerjack's fast-hook coverage** for at least ruff-check, ruff-format, codespell, and tc-refs.
2. **Universal compatibility**: a single Crackerjack change works across all 14 Bodai repos without per-repo `pyproject.toml` edits.
3. **Silence ecosystem-wide noise** via a CLI-injected per-file-ignores starter pack.
4. **Make the audit tool itself ruff-clean** so it stops generating 84 violations across 7 consumer repos.
5. **Preserve the audit tool's detection behavior** through regression tests.

## 3. Non-Goals

1. Modifying any per-repo `pyproject.toml` files.
2. Changing pytest `testpaths` (stays `["tests"]`).
3. Changing coverage `source` scope (stays `["crackerjack"]`).
4. Fixing the `tc-refs` deal-breaker (crackerjack missing from oneiric/mdinject venvs) — separate issue.
5. Fixing crackerjack native tools' silent failure in non-crackerjack CWDs — separate bug.
6. Cleaning up stale `.bak2`/`.bak3` files in `crackerjack/scripts/` — separate PR.
7. Refactoring mahavishnu's production-imported scripts (`collect_metrics`, etc.) out of `scripts/` — separate refactor.
8. Per-repo cleanup of single-repo rules (DTZ005, UP034, RUF012, etc.) — follow-up issues.

---

## 4. Design

### 4.1 Architecture & change surface

**Files changed (crackerjack-only):**

| File | Change |
|---|---|
| `crackerjack/config/per_file_ignores.py` | **NEW** module containing the universal starter pack + file-creation helper |
| `crackerjack/config/tool_commands.py` | Add `./scripts ./examples` to ruff-check, ruff-format, codespell, tc-refs; inject `--per-file-ignores` to ruff-check |
| `crackerjack/config/hooks.py` | No structural change (FAST_HOOKS composition unchanged) |
| `crackerjack/audit_type_checking_runtime_refs.py` | Rewrite to silence 12 violations; `chmod +x` for EXE001 |
| `tests/config/test_tool_commands.py` | Update `test_target_directories_specified`; add tests for codespell + tc-refs paths |
| `tests/unit/config/test_per_file_ignores.py` | **NEW** — 11 tests covering starter pack contents, file lifecycle, ruff acceptance |
| `tests/unit/test_audit_type_checking_runtime_refs.py` | **NEW** — regression tests for behavior preservation |

**Files NOT changed:**

- Per-repo `pyproject.toml` files (the CLI-injected per-file-ignore travels with Crackerjack)
- Pytest config (`testpaths = ["tests"]` stays)
- Coverage config (`source = ["crackerjack"]` stays)
- `crackerjack/services/file_filter.py` SmartFileFilter (the `--incremental` mode behavior becomes consistent with default mode automatically)
- Deal-breaker tools (separate issues)

### 4.2 Universal starter pack (9 + 3 examples-specific rules)

```toml
"scripts/**/*.py" = [
    "EXE001",   # shebang-not-executable (78 fires, 6 repos)
    "BLE001",   # blind-except (56 fires, 7 repos)
    "F541",     # f-string-missing-placeholders (32 fires, 6 repos)
    "C901",     # complex-structure (12 fires, 6 repos)
    "SIM102",   # collapsible-if (11 fires, 6 repos)
    "SIM103",   # needless-bool (7 fires, 6 repos)
    "SIM114",   # if-with-same-arms (8 fires, 7 repos)
    "S110",     # try-except-pass (10 fires, 2 repos)
    "PLW1510",  # subprocess-run-without-check (9 fires, 3 repos)
]
"examples/**/*.py" = [
    # Same as scripts/** + 3 examples-specific additions:
    "EXE001", "BLE001", "F541", "C901", "SIM102", "SIM103", "SIM114",
    "S110", "PLW1510",
    # Examples-only additions:
    "N999",     # invalid-module-name (underscored demo filenames)
    "RUF100",   # unused-noqa in example files
    "FURB162",  # fromisoformat-replace-z
]
"scripts/_*.py" = ["N999"]
"**/*.bak[0-9]" = ["ALL"]
```

**Rationale:** The 7 universal rules (`EXE001`, `BLE001`, `F541`, `C901`, `SIM102`, `SIM103`, `SIM114`) account for 212 of 333 violations (63.7%) across 6-7 repos each. They reflect legitimate patterns in admin/demo code: shebang-without-chmod, broad exception handlers, complex procedural flows. The 3 examples-specific additions handle common demo-code conventions. The `scripts/_*.py` glob handles underscore-prefixed one-shot scripts. The `**/*.bak[0-9]` pattern silences stale backup files.

**`TC003` is explicitly NOT in the starter pack.** It catches real runtime bugs (TYPE_CHECKING-only imports used at runtime) that `tc-refs` also catches. Silencing it would mask bugs in production-imported admin code (e.g., mahavishnu's `collect_metrics.py`).

**Single-repo rules** (UP034, DTZ005, RUF012, PLR1722, FURB162, etc.) are NOT in the starter pack. They represent repo-specific patterns that should be fixed per-repo, not silenced ecosystem-wide.

### 4.3 Per-file-ignores injection mechanism

A new module `crackerjack/config/per_file_ignores.py` provides:

```python
UNIVERSAL_PER_FILE_IGNORES: dict[str, list[str]] = { ... }  # The 4 patterns above

def build_inline_per_file_ignores() -> str:
    """Build the inline TOML string for use with `ruff --config='<value>'`.

    The returned string is a single TOML key=value pair:
        lint.extend-per-file-ignores = {"scripts/**/*.py" = [...], ...}

    Consumer auto-discovery is preserved because the value is injected as
    a single config override (--config='KEY = VALUE' preserves auto-discovery
    of pyproject.toml, ruff.toml, etc.; --config=<file.toml> REPLACES).
    """
```

**Critical ruff invocation detail** (verified empirically 2026-09-05):
- Ruff's `--per-file-ignores` CLI flag accepts only inline `<FilePattern>:<RuleCode>` mappings (one rule per arg), and is **replacing**, not additive.
- Ruff's `--config=<file.toml>` flag accepts a TOML config file BUT REPLACES auto-discovery entirely. Consumer's `pyproject.toml` is ignored when `--config=<file>` is passed. **DO NOT use this form.**
- Ruff's `--config='<KEY> = <VALUE>'` (inline TOML key-value) PRESERVES auto-discovery. This is the correct invocation pattern.
- The `<KEY>` is `lint.extend-per-file-ignores` (with the `extend-` prefix for additive behavior).
- The `<VALUE>` is an inline-table TOML expression: `{"pat1" = ["rule1", ...], "pat2" = [...], ...}`

The tool invocation uses:
```python
"--config", f"lint.extend-per-file-ignores = {inline_table}",
```

This is what makes the change universally compatible: consumer repos with their own per-file-ignores (e.g., mahavishnu's `scripts/**/*.py = [B007, B008, ...]`) retain those rules; the crackerjack starter pack adds on top via `extend-per-file-ignores`.

**Optional debug artifact**: The helper may also write the same inline TOML to `.crackerjack_cache/scripts_examples_per_file_ignores.toml` for users to inspect. The file is not used by the ruff invocation — only the inline string is.

### 4.4 `tool_commands.py` changes

**ruff-check:** New command shape:
```python
"ruff-check": _python_module_command(
    "ruff", "check", "--output-format", "json", "--fix",
    "--config", f"lint.extend-per-file-ignores = {build_inline_per_file_ignores()}",
    f"./{package_name}", "./scripts", "./examples",
),
```

Note: uses `--config='<inline TOML>'`, NOT `--config=<file>` or `--per-file-ignores=<file>`. The inline form preserves consumer auto-discovery (verified empirically 2026-09-05).

**ruff-format:** Add targets only (no `--per-file-ignores` for format):
```python
"ruff-format": _python_module_command(
    "ruff", "format",
    f"./{package_name}", "./scripts", "./examples",
),
```

**codespell + tc-refs:** Add `./scripts ./examples` to target list (same pattern).

**Refactor:** Extract a `_build_targets(package_name)` helper that returns the canonical target list, used by every tool. Centralizes the change and makes future additions one-line edits.

The `_get_per_file_ignores_path()` helper is **stateless and recomputed on every call**. The implementation:

```python
def _get_per_file_ignores_path() -> Path:
    """Compute path on every call. The file write is idempotent (only writes
    if not present), so re-computing is cheap (single stat + maybe-write).
    No module-level cache needed — keeps behavior simple across repo switches.
    """
    return ensure_per_file_ignores_file(Path.cwd())
```

This avoids the "stale singleton across repo switches" gotcha that a module-level cache would introduce when crackerjack is invoked from different repos in sequence.

### 4.5 Audit tool rewrite strategy

**Strategy:** Minimal patch (rule-by-rule surgical fixes), not full refactor. Detection semantics preserved through regression tests.

**The 12 violations per copy:**

| Rule | Fix |
|---|---|
| `EXE001` | `chmod +x crackerjack/audit_type_checking_runtime_refs.py` |
| `F541` (2-3) | Replace `f"literal"` with `"literal"` |
| `C901` | Extract helper function (e.g., `_check_block`) to reduce cyclomatic complexity |
| `SIM103` | Replace `return True/return False` with direct return |
| `SIM114` | Combine if-branches with same bodies |
| `SIM102` | Inline nested ifs |
| `BLE001` | Narrow `except Exception:` to `(OSError, UnicodeDecodeError)` |
| `D301` | Use raw string `r"..."` for backslash-containing strings |
| `PIE810` | Fix `*args, **kwargs` unpacking pattern |
| `TRY004` | Replace `raise Exception(...)` with `raise TypeError(...)` |

**Public API preserved verbatim:** `audit_file(path) -> list[Violation]`, `find_type_checking_runtime_usage(tree) -> list[Violation]`.

**Propagation:** Each of the 7 consumer repos syncs `scripts/audit_type_checking_runtime_refs.py` from crackerjack's canonical source. This is a follow-up task per consumer; this change does NOT gate on consumer-side syncing. Document-only propagation.

### 4.6 Test updates

**Existing test updates** (`tests/config/test_tool_commands.py::test_target_directories_specified`):
- Assert `ruff-check` and `ruff-format` commands include `crackerjack`, `scripts`, `examples`
- Assert `ruff-check` includes `--per-file-ignores` flag pointing to existing file
- Assert `ruff-format` does NOT include `--per-file-ignores` (only lint needs it)
- New tests: `test_codespell_targets_include_scripts_and_examples`, `test_tc_refs_targets_include_scripts_and_examples`

**New tests** (`tests/unit/config/test_per_file_ignores.py`):
- 5 tests for `UNIVERSAL_PER_FILE_IGNORES` contents (correct rules, no TC003, examples extends scripts, etc.)
- 5 tests for `ensure_per_file_ignores_file()` (creates file, creates cache dir, idempotent, valid TOML, ruff-compatible format)
- 1 integration test verifying ruff accepts the generated file

**New regression tests** (`tests/unit/test_audit_type_checking_runtime_refs.py`):
- 3 tests for detection semantics preservation (runtime use detected, legitimate typing not flagged, multiline blocks)
- 1 test verifying the rewritten file passes ruff (with starter pack applied)

---

## 5. Verification & Rollout

### 5.1 Pre-commit gates (per commit)

- `ruff check crackerjack/` — 0 violations
- `ruff format --check crackerjack/` — no diff
- `mypy crackerjack/` — 0 errors
- `pytest tests/unit/ tests/config/ -x` — all pass
- `pytest tests/unit/test_audit_type_checking_runtime_refs.py -v` — all pass
- `pytest tests/unit/config/test_per_file_ignores.py -v` — all pass
- `crackerjack run --select ruff-check,ruff-format` — passes on crackerjack itself

### 5.2 Post-deploy verification

After commits land, run on each heavy-offender repo:

```bash
for repo in mahavishnu session-buddy oneiric crackerjack fastblocks mcp-common; do
    cd /Users/les/Projects/$repo
    echo "=== $repo ==="
    uv run ruff check scripts/ examples/ 2>&1 | tail -5
done
```

**Expected reduction:**

| Repo | Pre-change | Expected post-change | Reduction |
|---|---|---|---|
| mahavishnu | 134 | ~40-50 | ~60% |
| session-buddy | 117 | ~50-60 | ~50% |
| oneiric | 30 | ~10 | ~66% |
| crackerjack | 4 | 0 | 100% |
| fastblocks | 14 | ~5 | ~64% |
| mcp-common | 14 | ~5 | ~64% |

Remaining violations are per-repo rules (intentionally not silenced).

### 5.3 Audit tool spot-check

```bash
cd /Users/les/Projects/mahavishnu
python3 -m crackerjack.tools.audit_type_checking_runtime_refs scripts/ > /tmp/post.txt
# Compare with pre-rewrite output — should be semantically equivalent
diff /tmp/pre.txt /tmp/post.txt
# Expected: empty diff
```

### 5.4 Rollout sequence

5 commits to local main (no PR per Bodai pre-1.0 policy):

1. **Commit 1:** Add `crackerjack/config/per_file_ignores.py` + tests
2. **Commit 2:** Update `tool_commands.py` — add `./scripts ./examples` to ruff-check + ruff-format; update tests
3. **Commit 3:** Extend codespell + tc-refs to `./scripts ./examples`
4. **Commit 4:** Audit tool rewrite (`chmod +x` + 9 surgical fixes)
5. **Commit 5:** Verification report (post-deploy results from 5.2)

### 5.5 Success criteria

- [ ] All 5 commits landed on local main
- [ ] Pre-commit gates pass for each commit
- [ ] `crackerjack run` passes on crackerjack itself
- [ ] mahavishnu reports ≤50 ruff violations (down from 134)
- [ ] session-buddy reports ≤60 ruff violations (down from 117)
- [ ] Audit tool rewrite passes regression tests
- [ ] Audit tool spot-check shows empty diff
- [ ] No new deal-breakers introduced
- [ ] No per-repo `pyproject.toml` files edited

### 5.6 Rollback

Each commit is independently revertable via `git revert <sha>`. The only persistent state change is `.crackerjack_cache/scripts_examples_per_file_ignores.toml` in each consumer repo — deleting it disables the new behavior.

---

## 6. Out-of-band Follow-ups

These surfaced during the audit but are NOT part of this change:

1. **`tc-refs` missing in oneiric/mdinject** — Add crackerjack as dev-dep. Separate issue.
2. **Crackerjack native tools' silent failure** in non-crackerjack CWDs (`check_ast`, `check_yaml`, `trailing_whitespace`). Bug in those tools.
3. **`.bak2`/`.bak3` files** in `crackerjack/scripts/`. Cleanup PR.
4. **Mahavishnu production-imported scripts** (`metrics_cli.py` imports `scripts.collect_metrics` etc.). Refactor to move out of `scripts/`.
5. **Per-repo single-rule violations**: DTZ005 in session-buddy, UP034/RUF012 in mahavishnu, etc. Follow-up issues.

---

## 7. References

- Audit data: Bodai ecosystem `scripts/` and `examples/` landscape survey (2026-09-05)
- Audit data: Fast-hook tool violations across 14 repos (2026-09-05)
- Crackerjack config: `/Users/les/Projects/crackerjack/crackerjack/config/tool_commands.py`
- Crackerjack hooks: `/Users/les/Projects/crackerjack/crackerjack/config/hooks.py`
- Universal conventions: `/Users/les/Projects/mahavishnu/CLAUDE.md` (Bodai pre-1.0 merge policy)