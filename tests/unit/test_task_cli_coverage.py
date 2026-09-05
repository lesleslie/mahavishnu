"""Coverage-push tests for the 5 missed lines in mahavishnu/task_cli.py.

The shorthand callbacks ``tc``/``tl``/``tu``/``td``/``ts`` (defined inside
``register_shorthands``) were previously registered but never invoked by any
test, leaving their single ``console.print(...)`` body lines uncovered. These
tests register a real ``click.Group`` and invoke each callback through
``CliRunner`` to drive the print statements and lift coverage to 100%.
"""

from __future__ import annotations

import click
from click.testing import CliRunner

from mahavishnu.task_cli import register_shorthands


def _build_group_with_shorthands() -> click.Group:
    """Build a fresh click.Group with the shorthand commands registered."""
    group = click.Group(name="mahavishnu")
    register_shorthands(group)
    return group


class TestShorthandCallbacks:
    """Cover the bodies of the five shorthand callbacks."""

    def test_tc_invokes_print(self) -> None:
        runner = CliRunner()
        result = runner.invoke(_build_group_with_shorthands(), ["tc"])
        assert result.exit_code == 0
        assert "task create" in result.output

    def test_tl_invokes_print(self) -> None:
        runner = CliRunner()
        result = runner.invoke(_build_group_with_shorthands(), ["tl"])
        assert result.exit_code == 0
        assert "task list" in result.output

    def test_tu_invokes_print(self) -> None:
        runner = CliRunner()
        result = runner.invoke(_build_group_with_shorthands(), ["tu"])
        assert result.exit_code == 0
        assert "task update" in result.output

    def test_td_invokes_print(self) -> None:
        runner = CliRunner()
        result = runner.invoke(_build_group_with_shorthands(), ["td"])
        assert result.exit_code == 0
        assert "task delete" in result.output

    def test_ts_invokes_print(self) -> None:
        runner = CliRunner()
        result = runner.invoke(_build_group_with_shorthands(), ["ts"])
        assert result.exit_code == 0
        assert "task status" in result.output
