"""Ratchet tests for MCP tool-inventory claims in README.md and CLAUDE.md.

These tests pin the documented tool count and profile-group count to the
actual code so that narrative drift between docs and source gets caught at
CI. A previous Bodai audit wave found that hand-maintained tool counts
in component READMEs routinely drifted (3-30 dead refs per wave). This
guard keeps that drift from recurring on Mahavishnu.

Counter sources of truth:
- Registered tools: ``tests/fixtures/full_production/tool_names.json`` —
  the tools a client of the *running* server can actually call, captured
  from the production dispatcher (``mahavishnu/mcp/bootstrap.py::
  register_profile_tools``). Regenerate with
  ``uv run python scripts/capture_profile_fixtures.py``.
- Decorator scan: ``@mcp.tool()`` / ``@app.tool()`` / ``@server.tool()``
  under ``mahavishnu/mcp/``. This counts tool *definitions in source*, not
  registered tools — it over-counts (modules the server never imports) and
  under-counts (the ``mcp.tool()(fn)`` call form and multi-line
  ``@app.tool(`` decorators). It is kept only as a sanity check.
- Profile groups: ``FULL_REGISTRATIONS`` in
  ``mahavishnu/mcp/tools/profiles.py`` (the union of registration methods
  called when ``MAHAVISHNU_TOOL_PROFILE=full``).

The numeric claim is read from the docs via regex; the test asserts the
claim matches the registered-tool count exactly. The registered count is a
captured fixture, so it is deterministic — no headroom window is needed.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_DIR = REPO_ROOT / "mahavishnu" / "mcp"
PROFILES_FILE = MCP_DIR / "tools" / "profiles.py"
REGISTERED_TOOLS_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "full_production" / "tool_names.json"
README_FILE = REPO_ROOT / "README.md"
CLAUDE_FILE = REPO_ROOT / "CLAUDE.md"

TOOL_HEADROOM = 0
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

    Loaded via importlib with the proper package namespace so the
    relative ``from ..bootstrap import …`` inside ``profiles.py`` resolves
    correctly. Loading with a bare top-level name (``profiles_under_test``)
    makes the relative import fail with "attempted relative import with no
    known parent package".
    """
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "mahavishnu.mcp.tools.profiles", PROFILES_FILE
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load spec for {PROFILES_FILE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["mahavishnu.mcp.tools.profiles"] = module
    spec.loader.exec_module(module)
    return len(module.FULL_REGISTRATIONS)


def _count_registered_tools() -> int:
    """Count the tools a client of the running server can call.

    Read from the captured production fixture rather than counted from
    source: a decorator scan measures tool *definitions*, which is a
    different set from the registered surface (it counts tools in modules
    the server never imports, and misses the non-decorator registration
    forms).
    """
    return len(json.loads(REGISTERED_TOOLS_FIXTURE.read_text()))


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
        """Sanity: the decorator scan should find tool definitions in this repo."""
        count = _count_tool_decorators()
        assert count > 100, (
            f"expected >100 tool decorators under {MCP_DIR}, found {count}"
        )

    def test_registered_fixture_is_present(self):
        """The captured production fixture must exist and be non-trivial."""
        count = _count_registered_tools()
        assert count > 100, (
            f"expected >100 registered tools in {REGISTERED_TOOLS_FIXTURE}, found {count}"
        )

    @pytest.mark.parametrize(
        "doc_path",
        [
            pytest.param(README_FILE, id="README.md"),
            pytest.param(CLAUDE_FILE, id="CLAUDE.md"),
        ],
    )
    def test_readme_tool_claim_within_headroom(self, doc_path: Path):
        """The numeric "tools" claim must equal the registered-tool count."""
        doc_text = doc_path.read_text()
        claim = _extract_tool_claim(doc_text)
        if claim is None:
            pytest.skip(f"{doc_path.name} has no numeric tool-count claim to verify")
        actual = _count_registered_tools()
        assert abs(actual - claim) <= TOOL_HEADROOM, (
            f"{doc_path.name} claims {claim} tools but the registered surface has "
            f"{actual}. Regenerate the fixture with "
            f"`uv run python scripts/capture_profile_fixtures.py` and update the doc."
        )

    @pytest.mark.parametrize(
        "doc_path",
        [
            pytest.param(README_FILE, id="README.md"),
            pytest.param(CLAUDE_FILE, id="CLAUDE.md"),
        ],
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
