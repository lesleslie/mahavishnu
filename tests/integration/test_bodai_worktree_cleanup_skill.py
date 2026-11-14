"""Skill trigger phrases + wrapper script smoke for bodai-worktree-cleanup.

F-QA-15 (reinterpreted): Claude Code auto-discovers skills via the SKILL.md
frontmatter `description:` field. The trigger phrases are the comma-separated
phrases inside that description. If they vanish (or the description is
missing), the skill will not fire — this test pins both:

- the SKILL.md frontmatter exists
- the description field contains every phrase operators rely on

Also asserts the wrapper script exists and invokes the right module path
so the skill can actually run via `python .claude/skills/.../cli_scan.py`.
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "bodai-worktree-cleanup"
SKILL_MD = SKILL_DIR / "SKILL.md"
WRAPPER = SKILL_DIR / "scripts" / "cli_scan.py"

EXPECTED_TRIGGERS = (
    "scan worktrees",
    "find stale worktrees",
    "audit bodai worktrees",
    "list orphaned worktrees",
)


def _frontmatter_description(skill_md: Path) -> str:
    """Extract the `description:` value from a SKILL.md header.

    bodai-worktree-cleanup declares its description as a YAML *folded
    block scalar*::

        description: >-
          "Scan Bodai repos ... Triggers on
          'scan worktrees', 'find stale worktrees', ..."

    A line-oriented reader cannot read that. Scanning for the
    ``description:`` line stops at the ``>-`` marker and yields the
    literal string ``">-"``, so every trigger phrase looks absent.
    The frontmatter is therefore parsed as YAML, which folds the
    block into one string.

    Some bodai skills use an H2 header instead of YAML fences:
        ## name: <id> description: "<text>"

    The regex fallback still handles that form.
    """
    text = skill_md.read_text()
    # Try YAML frontmatter fences first.
    yaml_match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if yaml_match:
        front = yaml.safe_load(yaml_match.group(1))
        if isinstance(front, dict):
            value = front.get("description")
            if isinstance(value, str):
                return value
    # Fall back to the H2 form used by bodai skills.
    h2_match = re.search(r"^## .*?description:\s*(.+)$", text, re.MULTILINE)
    assert h2_match, f"SKILL.md has no description header: {skill_md}"
    value = h2_match.group(1).strip()
    if value.startswith(("'", '"')) and value.endswith(value[0]):
        value = value[1:-1]
    return value


def test_skill_md_exists_with_trigger_phrases() -> None:
    desc = _frontmatter_description(SKILL_MD)
    missing = [t for t in EXPECTED_TRIGGERS if t not in desc]
    assert not missing, (
        f"SKILL.md frontmatter description is missing trigger phrases: {missing}. "
        f"Found description: {desc!r}. Claude Code needs these in `description:` "
        f"to consider firing the skill on user input."
    )


def test_wrapper_script_invokes_scan_module() -> None:
    """The wrapper at .claude/skills/.../cli_scan.py must call the scan
    subcommand via python -m (not via the legacy `worktree_cli worktree scan`)."""
    if not WRAPPER.exists():
        pytest.skip(f"wrapper missing: {WRAPPER}")
    body = WRAPPER.read_text()
    assert "mahavishnu.worktree_cli" in body, (
        "Wrapper does not invoke mahavishnu.worktree_cli; skill is broken."
    )
    assert "scan" in body, "Wrapper does not call scan; skill is broken."


def test_wrapper_runs_end_to_end(tmp_path: Path) -> None:
    """Smoke-run the wrapper against a tmp repo; non-zero exit is acceptable
    but stderr should not contain an unhandled exception traceback."""
    if not WRAPPER.exists():
        pytest.skip(f"wrapper missing: {WRAPPER}")
    repo = tmp_path / "repo1"
    repo.mkdir()
    (repo / ".git").mkdir()
    result = subprocess.run(
        [sys.executable, str(WRAPPER), "--repo", str(repo), "--format", "text"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "Traceback" not in result.stderr, (
        f"wrapper raised an unhandled exception; stderr: {result.stderr!r}"
    )
