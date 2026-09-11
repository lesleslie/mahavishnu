"""Integration tests for the 6 Typer-registered drain subcommands (Task 13).

Each new subcommand on ``mahavishnu.cli.jot_cli.app`` must:
  - Be discoverable via ``--help``.
  - Render its own ``--help`` with exit_code 0.
  - Forward the flags declared in the Task 13 brief.

These tests use Typer's ``CliRunner`` so they do NOT require touching
``~/.mahavishnu/jot/`` or any workflow runtime — the surface check is
pure Typer-registration.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from mahavishnu.cli.jot_cli import app as jot_app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# Top-level help must mention every new drain subcommand.
# ---------------------------------------------------------------------------


def test_top_level_help_mentions_all_drain_subcommands(runner: CliRunner) -> None:
    result = runner.invoke(jot_app, ["--help"])
    assert result.exit_code == 0
    out = result.output
    for name in ("drain", "dispatch", "defer", "delete", "retry", "resurface"):
        assert name in out, f"subcommand {name!r} missing from `jot --help`"


# ---------------------------------------------------------------------------
# One parameterized test per subcommand — every command must support --help.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ["drain", "--help"],
        ["dispatch", "--help"],
        ["defer", "--help"],
        ["delete", "--help"],
        ["retry", "--help"],
        ["resurface", "--help"],
    ],
)
def test_subcommand_help_exits_zero(runner: CliRunner, args: list[str]) -> None:
    result = runner.invoke(jot_app, args)
    assert result.exit_code == 0, (
        f"`mahavishnu jot {' '.join(args)}` failed: {result.output}"
    )


# ---------------------------------------------------------------------------
# Flag-forwarding spot-checks — at minimum the flags declared in the Task 13
# brief must appear in each subcommand's --help text so users can discover
# them. We don't exercise runtime behaviour here (that lives in
# tests/unit/jot/test_drain_cli.py).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "expected_flag"),
    [
        (["drain", "--help"], "--query"),
        (["drain", "--help"], "--limit"),
        (["drain", "--help"], "--include-in-flight"),
        (["defer", "--help"], "--until-ms"),
        (["defer", "--help"], "--reason"),
        (["delete", "--help"], "--reason"),
        (["resurface", "--help"], "--trigger"),
        (["resurface", "--help"], "--context-text"),
    ],
)
def test_subcommand_help_advertises_flag(
    runner: CliRunner, args: list[str], expected_flag: str,
) -> None:
    result = runner.invoke(jot_app, args)
    assert result.exit_code == 0
    assert expected_flag in result.output, (
        f"`{' '.join(args)}` should advertise {expected_flag!r} flag"
    )
