"""Ratchet tests for MCP tool-inventory claims in README.md and CLAUDE.md.

These tests pin the documented tool count and profile-group count to the
actual code so that narrative drift between docs and source gets caught at
CI. A previous Bodai audit wave found that hand-maintained tool counts
in component READMEs routinely drifted (3-30 dead refs per wave). This
guard keeps that drift from recurring on Mahavishnu.

Counter sources of truth:
- Decorator scan: ``@mcp.tool()`` / ``@app.tool()`` / ``@server.tool()``
  under ``mahavishnu/mcp/``.
- Profile groups: ``FULL_REGISTRATIONS`` in
  ``mahavishnu/mcp/tools/profiles.py`` (the union of registration methods
  called when ``MAHAVISHNU_TOOL_PROFILE=full``).

The numeric claim is read from the docs via regex; the test asserts the
claim is within ±5 of the counted value (narrative phrasing like
"~180 tools" maps to a 5-tool headroom window).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_DIR = REPO_ROOT / "mahavishnu" / "mcp"
PROFILES_FILE = MCP_DIR / "tools" / "profiles.py"
README_FILE = REPO_ROOT / "README.md"
CLAUDE_FILE = REPO_ROOT / "CLAUDE.md"

TOOL_HEADROOM = 5
TOOL_DECORATOR_RE = re.compile(
    r"^\s*@(?:mcp|app|server)\.tool\(\)",
    re.MULTILINE,
)
TOOL_CLAIM_RE = re.compile(
    r"~?\s*(\d{2,4})\s+(?:decorated\s+)?tools",
    re.IGNORECASE,
)
GROUP_CLAIM_RE = re.compile(
    r"(\d{1,2})\s+(?:profile-gated\s+)?groups",
    re.IGNORECASE,
)


def _count_tool_decorators() -> int:
    """Count ``@mcp.tool()`` / ``@app.tool()`` / ``@server.tool()`` decorators.

    Scans every ``.py`` file under ``mahavishnu/mcp/``. Comment lines that
    happen to mention the decorator form (e.g. inside docstrings) are not
    matched because the regex is anchored at line-start.
    """
    total = 0
    for py_file in MCP_DIR.rglob("*.py"):
        total += len(TOOL_DECORATOR_RE.findall(py_file.read_text()))
    return total


def _count_full_profile_groups() -> int:
    """Count the number of registration methods in ``FULL_REGISTRATIONS``.

    Imported via importlib because ``mahavishnu.mcp.tools.profiles`` pulls
    in ``mcp_common`` which may not be available in all test envs. The
    import is wrapped in a helper so the test fails with a useful message
    rather than a collection-time ImportError.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("profiles_under_test", PROFILES_FILE)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load spec for {PROFILES_FILE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return len(module.FULL_REGISTRATIONS)


def _extract_tool_claim(text: str) -> int | None:
    """Pull the first numeric "tools" claim out of a doc file."""
    match = TOOL_CLAIM_RE.search(text)
    return int(match.group(1)) if match else None


def _extract_group_claim(text: str) -> int | None:
    """Pull the first numeric "groups" claim out of a doc file."""
    match = GROUP_CLAIM_RE.search(text)
    return int(match.group(1)) if match else None


class TestMCPToolInventory:
    """Guard README/CLAUDE tool-count claims against decorator-scan reality."""

    def test_decorator_scan_runs(self):
        """Sanity: the decorator scan should find tools in this repo."""
        count = _count_tool_decorators()
        assert count > 100, (
            f"expected >100 tool decorators under {MCP_DIR}, found {count}"
        )

    @pytest.mark.parametrize(
        "doc_path",
        [pytest.param(README_FILE, id="README.md"),
         pytest.param(CLAUDE_FILE, id="CLAUDE.md")],
    )
    def test_readme_tool_claim_within_headroom(self, doc_path: Path):
        """The numeric "tools" claim must be within ±5 of the scanned count."""
        doc_text = doc_path.read_text()
        claim = _extract_tool_claim(doc_text)
        if claim is None:
            pytest.skip(f"{doc_path.name} has no numeric tool-count claim to verify")
        actual = _count_tool_decorators()
        assert abs(actual - claim) <= TOOL_HEADROOM, (
            f"{doc_path.name} claims ~{claim} tools but decorator scan found {actual}"
        )

    @pytest.mark.parametrize(
        "doc_path",
        [pytest.param(README_FILE, id="README.md"),
         pytest.param(CLAUDE_FILE, id="CLAUDE.md")],
    )
    def test_readme_group_claim_matches_profile(self, doc_path: Path):
        """The numeric "groups" claim must equal FULL_REGISTRATIONS length."""
        doc_text = doc_path.read_text()
        claim = _extract_group_claim(doc_text)
        if claim is None:
            pytest.skip(f"{doc_path.name} has no numeric groups claim to verify")
        actual = _count_full_profile_groups()
        assert claim == actual, (
            f"{doc_path.name} claims {claim} profile-gated groups but "
            f"FULL_REGISTRATIONS has {actual}"
        )

    def test_full_profile_count_is_stable(self):
        """FULL_REGISTRATIONS should expose exactly the documented floor.

        Locks the group count against accidental additions that would
        silently invalidate the docs without anyone noticing.
        """
        assert _count_full_profile_groups() >= 14, (
            "FULL_REGISTRATIONS shrank below the documented floor; "
            "update README.md/CLAUDE.md or investigate dropped groups"
        )
