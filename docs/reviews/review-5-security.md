# Review 5 — Security & Best Practices

**Date**: 2026-04-05
**Reviewer**: agent
**Files**:
- `scripts/rank-tools.py` (130 lines)
- `scripts/eval-content-quality.py` (544 lines)
**Scope**: Input validation, safe file handling, dangerous constructs, error handling, entry-point hygiene, mutable defaults.

---

## Findings

### CRITICAL — none

No critical security issues found. Neither script contains hardcoded secrets, `eval()`/`exec()`, `subprocess`, or any mechanism for remote code execution.

---

### HIGH

| # | File | Line(s) | Issue |
|---|------|---------|-------|
| H-1 | `eval-content-quality.py` | 510 | **`main()` returns `None` — no exit code.** The function signature is `def main() -> None` and the `__main__` block calls `main()` without `sys.exit()`. Validation warnings (schema issues) and all other outcomes exit with code 0, making the script unsuitable for CI pipelines or shell `&&` chaining. |

**Recommendation for H-1**: Change `main()` to return `int` (0 on success, 1 on validation errors) and use `sys.exit(main())` in the guard.

---

### MEDIUM

| # | File | Line(s) | Issue |
|---|------|---------|-------|
| M-1 | `rank-tools.py` | 35 | **Missing `encoding="utf-8"`** on `open(path)`. Defaults to locale encoding, which can raise `UnicodeDecodeError` on non-ASCII tool files (e.g., UTF-8 docstrings on a `C`-locale system). |
| M-2 | `rank-tools.py` | 91–96 | **No try/except around per-file reads.** A single unreadable `.py` file in `TOOL_DIR` (permissions error, symlink to deleted file) crashes the entire script with an unhandled `OSError`. |
| M-3 | `eval-content-quality.py` | 176–177, 196–197 | **`load_samples()` calls `sys.exit(1)` directly** instead of raising an exception or returning an error sentinel. This makes the function untestable in isolation and prevents callers from handling the error programmatically. |
| M-4 | `eval-content-quality.py` | 179 | **`PermissionError` not caught.** `path.exists()` passes but `open(path)` can still fail with `PermissionError`. The `open()` call is not wrapped in try/except, producing an unhandled traceback. |

---

### LOW

| # | File | Line(s) | Issue |
|---|------|---------|-------|
| L-1 | both | — | **No path traversal validation.** Both scripts accept file paths that can point anywhere on the filesystem. Acceptable for a developer CLI tool, but worth noting if these ever run in a shared/automated context. |
| L-2 | `eval-content-quality.py` | 41 | **Dead code.** `LABEL_THRESHOLDS` dict is defined but never referenced anywhere in the module. |
| L-3 | `eval-content-quality.py` | 543 | **`__main__` guard does not propagate exit code.** `main()` is called bare; if H-1 is fixed, the guard must also change to `sys.exit(main())`. |

---

### NONE (Positive Findings)

| Check | Status |
|-------|--------|
| Hardcoded secrets | ✅ None found |
| `eval()` / `exec()` | ✅ Absent |
| `subprocess` with `shell=True` | ✅ No subprocess usage at all |
| Mutable default arguments | ✅ None |
| `if __name__ == "__main__"` guard | ✅ Present in both files |
| `argparse` for CLI input | ✅ Both files use it correctly |
| Type hints | ✅ Comprehensive on all public functions |
| Context managers for file I/O | ✅ All `open()` calls use `with` |
| Explicit `encoding="utf-8"` | ⚠️ Present in `eval-content-quality.py`; missing in `rank-tools.py` (see M-1) |
| Return type on `main()` | ✅ `rank-tools.py` returns `int`; ⚠️ `eval-content-quality.py` returns `None` (see H-1) |

---

## Overall Verdict

**PASS with minor fixes required.**

Both scripts are clean, well-structured, and free of dangerous constructs. The HIGH finding (missing exit codes in `eval-content-quality.py`) and the MEDIUM findings (encoding, error handling) are straightforward to fix. No security vulnerabilities are present.

### Recommended priority

1. **H-1 + L-3** — Make `eval-content-quality.py` return a meaningful exit code (~5 min fix).
2. **M-1** — Add `encoding="utf-8"` to `rank-tools.py` line 35.
3. **M-2** — Wrap per-file analysis in try/except with a warning to stderr.
4. **M-3 + M-4** — Refactor `load_samples()` to raise exceptions instead of calling `sys.exit()`, and catch `PermissionError`.
5. **L-2** — Remove or document `LABEL_THRESHOLDS`.
