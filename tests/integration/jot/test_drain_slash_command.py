"""Tests that the /jot drain slash command is registered in commands/jot.md.

These tests are static-content checks against the markdown frontmatter,
not behavioral tests against the slash-command runner. The runner
surface for both /jot vitals and /jot drain is the file's automatic
`Run` block, which is shared with the existing /jot vitals command.
"""
from __future__ import annotations

from pathlib import Path

COMMANDS_FILE = Path(__file__).resolve().parents[3] / "mahavishnu" / "commands" / "jot.md"


def test_jot_md_exists() -> None:
    assert COMMANDS_FILE.is_file(), f"missing: {COMMANDS_FILE}"


def test_jot_drain_block_present() -> None:
    content = COMMANDS_FILE.read_text(encoding="utf-8")
    assert "/jot drain" in content, "missing /jot drain block in jot.md"
    # The vitals block must still be present (don't accidentally overwrite it).
    # Note: the file content references the CLI command `mahavishnu jot vitals`,
    # not the slash command `/jot vitals`. The slash-command name is implied
    # by the file path (commands/jot.md → /jot <command>).
    assert "mahavishnu jot vitals" in content, "/jot vitals block was overwritten"


def test_jot_drain_frontmatter_shape() -> None:
    content = COMMANDS_FILE.read_text(encoding="utf-8")
    # Find the /jot drain block's frontmatter via the literal `/jot drain`
    # token (added to the description for self-documentation).
    start = content.find("/jot drain")
    assert start != -1
    block_start = content.rfind("---", 0, start)
    block_end = content.find("---", block_start + 3)
    assert block_start != -1 and block_end != -1
    frontmatter = content[block_start:block_end + 3]
    assert "description:" in frontmatter
    assert "allowed-tools:" in frontmatter
    # Must reference the drain flags the parent spec mandates.
    assert "--query" in content
    assert "--limit" in content
    assert "--include-in-flight" in content
