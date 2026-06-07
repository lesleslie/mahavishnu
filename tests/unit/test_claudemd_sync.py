"""CI guards against drift between CLAUDE.md and pyproject.toml.

If the 'Hard limits' table in `CLAUDE.md` and the live config in
`pyproject.toml` disagree, contributors reading CLAUDE.md get a wrong
picture of what the gate enforces. The rules also tell the gate to
fail on these limits, so a stale doc means a surprise on the next PR.

The pattern mirrors `tests/unit/test_task_router.py::TestYAMLRoutingSync`,
which guards the YAML ↔ in-code MiniMax routing.
"""

from __future__ import annotations

from pathlib import Path
import re
import tomllib

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
CLAUDE_MD_PATH = PROJECT_ROOT / "CLAUDE.md"

# Label in the CLAUDE.md "Hard limits" table → pyproject.toml dotted key.
EXPECTED_LIMITS: dict[str, tuple[str, ...]] = {
    "Line length": ("tool", "ruff", "line-length"),
    "Function args": ("tool", "ruff", "lint", "pylint", "max-args"),
    "Branches": ("tool", "ruff", "lint", "pylint", "max-branches"),
    "Returns": ("tool", "ruff", "lint", "pylint", "max-returns"),
    "Statements": ("tool", "ruff", "lint", "pylint", "max-statements"),
}


def _load_pyproject() -> dict:
    with PYPROJECT_PATH.open("rb") as f:
        return tomllib.load(f)


def _load_coverage_floor() -> int:
    """Coverage floor lives in `[tool.pytest] addopts` as --cov-fail-under=N.

    Parsed rather than read as a key because it's an argument inside a
    list of pytest options, not its own config key.
    """
    addopts = _load_pyproject()["tool"]["pytest"]["addopts"]
    joined = " ".join(addopts) if isinstance(addopts, list) else addopts
    match = re.search(r"--cov-fail-under=(\d+)", joined)
    if not match:
        raise AssertionError("pyproject.toml [tool.pytest].addopts must include --cov-fail-under=N")
    return int(match.group(1))


def _parse_hard_limits_table() -> dict[str, int]:
    """Extract {label: integer_value} from the 'Hard limits' table in CLAUDE.md.

    Robust to the value cell containing prose ("55 ceiling — practical
    target 30") by taking the first integer. Robust to column reorder by
    matching on the first column's label.

    Raises AssertionError if the section or its header row can't be found.
    """
    text = CLAUDE_MD_PATH.read_text()

    section_match = re.search(
        r"^### Hard limits[^\n]*\n(.*?)(?=^### |\Z)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    if not section_match:
        raise AssertionError(
            "Could not find '### Hard limits' section in CLAUDE.md. "
            "If you renamed the section, update tests/unit/test_claudemd_sync.py."
        )

    body = section_match.group(1)
    limits: dict[str, int] = {}

    for raw_row in body.splitlines():
        row = raw_row.strip()
        if not row.startswith("|") or "---" in row:
            continue
        cells = [c.strip() for c in row.strip("|").split("|")]
        if len(cells) < 2 or cells[0] == "Limit":
            continue

        label = cells[0]
        value_cell = cells[1]
        int_match = re.search(r"\d+", value_cell)
        if int_match:
            limits[label] = int(int_match.group())

    return limits


def _lookup(config: dict, dotted_key: tuple[str, ...]) -> int:
    """Walk a dotted path like ('tool', 'ruff', 'line-length') through nested dicts."""
    cursor = config
    for part in dotted_key:
        if not isinstance(cursor, dict) or part not in cursor:
            raise AssertionError(
                f"pyproject.toml is missing key path '{'.'.join(dotted_key)}'. "
                f"Either the key moved or CLAUDE.md references a stale location."
            )
        cursor = cursor[part]
    if not isinstance(cursor, int):
        raise AssertionError(
            f"pyproject.toml '{'.'.join(dotted_key)}' = {cursor!r} is not an integer"
        )
    return cursor


class TestHardLimitsSync:
    """The 'Hard limits' table in CLAUDE.md must match pyproject.toml exactly.

    If you change a limit in pyproject.toml, update the doc in the same
    commit. If you change the doc, change the config in the same commit.
    Otherwise this test fails and the doc lies to the next reader.
    """

    def test_table_is_parseable(self):
        """Smoke test: the 'Hard limits' table exists and has the expected rows."""
        limits = _parse_hard_limits_table()
        for label in EXPECTED_LIMITS:
            assert label in limits, (
                f"CLAUDE.md 'Hard limits' table is missing row '{label}'. "
                f"Found rows: {sorted(limits)}"
            )

    @pytest.mark.parametrize(
        "label,dotted_key",
        list(EXPECTED_LIMITS.items()),
        ids=list(EXPECTED_LIMITS),
    )
    def test_limit_matches_pyproject(self, label: str, dotted_key: tuple[str, ...]):
        config = _load_pyproject()
        doc_value = _parse_hard_limits_table().get(label)
        config_value = _lookup(config, dotted_key)

        assert doc_value == config_value, (
            f"Drift on '{label}': CLAUDE.md says {doc_value!r}, "
            f"pyproject.toml [{']['.join(dotted_key)}] says {config_value!r}. "
            f"Update the doc and the config together, or this guard fails."
        )

    def test_coverage_floor_matches_pyproject(self):
        doc_value = _parse_hard_limits_table().get("Coverage")
        config_value = _load_coverage_floor()

        assert doc_value == config_value, (
            f"Drift on 'Coverage': CLAUDE.md says {doc_value!r}, "
            f"pyproject.toml --cov-fail-under says {config_value!r}. "
            f"Update the doc and the config together."
        )


class TestCLAUDMDSectionPresent:
    """Sanity checks on the Crackerjack-Compliant Code section structure.

    These guard against silent renames that would break the parse in
    `_parse_hard_limits_table` and against the section disappearing
    entirely.
    """

    def test_section_header_present(self):
        text = CLAUDE_MD_PATH.read_text()
        assert "## Crackerjack-Compliant Code" in text, (
            "Expected `## Crackerjack-Compliant Code` header in CLAUDE.md"
        )

    def test_conventions_block_present(self):
        text = CLAUDE_MD_PATH.read_text()
        assert "### Conventions" in text, (
            "Expected `### Conventions` subsection under Crackerjack-Compliant Code"
        )

    def test_enforcement_gaps_block_present(self):
        text = CLAUDE_MD_PATH.read_text()
        assert "### Known enforcement gaps" in text, (
            "Expected `### Known enforcement gaps` subsection to stay in CLAUDE.md. "
            "If a previously-aspirational rule became enforced, drop its line "
            "from this block rather than removing the block."
        )
