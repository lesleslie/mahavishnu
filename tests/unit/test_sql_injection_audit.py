"""Periodic audit: any `cursor.execute(f"...")` in production code must be
explicitly justified with a `# nosemgrep` directive.

This guard prevents a regression where a new f-string in a
`cursor.execute()` call reintroduces a SQL injection vector. SQLite
identifiers (table names, schema names, `VACUUM INTO` filenames) can't
be bound as parameters, so legitimate use of f-string interpolation
must be paired with identifier validation AND a nosemgrep directive
that names the disabled rule.

Mark this test with the `audit` marker so it can be run on demand:
    pytest -m audit
    # or with a fast marker exclusion:
    pytest -m "not audit"
"""

from __future__ import annotations

from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROD_DIR = PROJECT_ROOT / "mahavishnu"
EXCLUDE_DIRS = {"tests", "test_*.py", ".venv", "__pycache__", ".git"}

# These rule IDs are the ones semgrep fires for unparameterized SQL
# with f-strings. The directive on a legitimate call site must name
# at least one of them.
SUPPRESSED_RULE_IDS = {
    "python.lang.security.audit.formatted-sql-query",
    "python.lang.security.audit.sql-string-concatenation",
    "python.sqlalchemy.security.sql-injection-raw-sql",
}

# Regex to find `cursor.execute(...)` calls (or `.executemany`, etc.).
EXECUTE_CALL_RE = re.compile(r"\.execute(?:many)?\s*\(")
# Regex to find a f-string expression (heuristic: f"..." or f'...') used
# in the same call.
F_STRING_RE = re.compile(r"""(?<!r)(?<!\\)\bf['"]""")
# Regex to extract a `# nosemgrep:` directive from a single line.
NOSEMGREP_RE = re.compile(
    r"#\s*nosemgrep(?::\s*(?P<rules>[A-Za-z0-9_.,\-\s]+))?",
)


def _iter_python_files() -> list[Path]:
    return [p for p in PROD_DIR.rglob("*.py") if not any(part in EXCLUDE_DIRS for part in p.parts)]


def _find_fstring_executes(path: Path) -> list[tuple[int, str]]:
    """Return (line_no, line_text) for each `.execute(...)` call whose
    f-string argument is not suppressed by an inline `# nosemgrep`
    naming one of the SQL-injection rules.

    The suppression check covers the entire multi-line statement — the
    `# nosemgrep` may appear on the line that starts the f-string, on
    the line that ends it, or anywhere in between.
    """
    findings: list[tuple[int, str]] = []
    lines = path.read_text(errors="replace").splitlines()
    in_docstring = False
    quote_char: str | None = None

    def _line_has_suppression(s: str) -> bool:
        m = NOSEMGREP_RE.search(s)
        if not m or not m.group("rules"):
            return False
        rules = {r.strip() for r in m.group("rules").split(",")}
        return bool(rules & SUPPRESSED_RULE_IDS)

    for n, line in enumerate(lines, start=1):
        # Track triple-quote state to skip lines inside docstrings.
        if not in_docstring:
            for q in ('"""', "'''"):
                count = line.count(q)
                if count % 2 == 1:
                    in_docstring = True
                    quote_char = q
                    break
            if in_docstring and quote_char and line.count(quote_char) > 1:
                in_docstring = False
                quote_char = None
        else:
            if quote_char and quote_char in line:
                in_docstring = False
                quote_char = None
            continue

        if not EXECUTE_CALL_RE.search(line):
            continue
        if not F_STRING_RE.search(line):
            continue

        # Walk forward through the multi-line f-string (if any) and
        # check every line in the statement for a valid suppression.
        end = n
        if 'f"""' in line or "f'''" in line:
            q = '"""' if 'f"""' in line else "'''"
            for j in range(n, len(lines)):
                end = j + 1
                if lines[j].count(q) >= 1 and j + 1 != n:
                    # Found the closing triple quote; stop after this line.
                    # We allow the same line to open+close (e.g. `f"""x"""`).
                    break
        elif '"""' in line or "'''" in line:
            # Single-line triple-quoted f-string ends on the same line.
            end = n

        if any(_line_has_suppression(s) for s in lines[n - 1 : end]):
            continue

        findings.append((n, line.strip()))

    return findings


class TestSQLInjectionAudit:
    """Periodic guard: no production `cursor.execute(f"...")` without
    a matching `# nosemgrep` directive naming one of the SQL-injection
    rules. New calls must be paired with identifier validation (see
    `migrator._validate_sqlite_identifier` and the validation block
    in `encrypted_sqlite.backup`) and a justification comment.
    """

    def test_no_unjustified_fstring_executes(self):
        offenders: list[str] = []
        for path in _iter_python_files():
            for line_no, line_text in _find_fstring_executes(path):
                rel = path.relative_to(PROJECT_ROOT)
                offenders.append(f"{rel}:{line_no}: {line_text}")

        assert not offenders, (
            'Found `cursor.execute(f"...")` calls without a matching '
            "`# nosemgrep: <rule-id>` directive. SQLite identifiers can't "
            "be parameterized, so each such call needs:\n"
            "  1. Explicit validation of the interpolated identifier\n"
            "  2. A nosemgrep comment naming at least one of:\n"
            f"     {sorted(SUPPRESSED_RULE_IDS)}\n"
            "Offending lines:\n  " + "\n  ".join(offenders)
        )
