"""Unit tests for ``mahavishnu.cli.settle_cli``.

Wires the three orphan sync wrappers from
``mahavishnu/settle/{merge,persistence}.py`` into a Typer sub-app so they
become reachable from the ``mahavishnu`` CLI.

These tests are written before the implementation per TDD discipline.
The test file expects:

  - ``add_settle_commands(app: typer.Typer) -> None``
  - Registers a ``settle`` sub-typer on ``app`` with three commands:
    ``status <run_ref>``, ``start <run_ref>``, and ``merge <run_ref>``.

The heavy machinery (Dhara substrate, settle record parsing) is mocked so
the tests stay fast and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any
from unittest.mock import patch

import pytest
import typer
from typer.testing import CliRunner

from mahavishnu.cli.settle_cli import add_settle_commands


@dataclass(frozen=True)
class _FakeSettleRunRecord:
    """Stand-in for ``mahavishnu.settle.state_machine.SettleRunRecord``.

    Only the fields the CLI prints matter for these tests. The real record
    has a ``transitions`` tuple, ``bindings`` tuple, etc. — we keep this
    minimal so the test surfaces exactly what the CLI is expected to show.
    """

    run_ref: str = "abc123"
    worker_id: str = "worker-1"
    task_signature: str = "fix-import-order"
    state: str = "PROPOSED"
    created_at: datetime = field(default_factory=lambda: datetime(2026, 9, 6, tzinfo=UTC))
    updated_at: datetime = field(default_factory=lambda: datetime(2026, 9, 6, tzinfo=UTC))
    bindings: tuple[Any, ...] = ()


@pytest.fixture
def app() -> typer.Typer:
    """A bare Typer app with the settle subcommands registered."""
    root = typer.Typer()
    add_settle_commands(root)
    return root


@pytest.fixture
def runner() -> CliRunner:
    """CliRunner — invoke() takes the app as its first positional arg."""
    return CliRunner()


# ---------------------------------------------------------------------------
# settle status
# ---------------------------------------------------------------------------


def test_settle_status_with_known_run_ref_prints_record_fields(app: typer.Typer, runner: CliRunner) -> None:
    """``settle status <run_ref>`` shows run_ref, state, worker_id, signature."""
    fake_record = _FakeSettleRunRecord(
        run_ref="abc123",
        worker_id="worker-7",
        task_signature="refactor-auth-flow",
        state="APPLIED",
    )
    with patch(
        "mahavishnu.cli.settle_cli.load_record_sync",
        return_value=fake_record,
    ) as mock_load:
        result = runner.invoke(app, ["settle", "status", "abc123"])

    assert result.exit_code == 0, result.stdout
    mock_load.assert_called_once_with("abc123")
    assert "abc123" in result.stdout
    assert "APPLIED" in result.stdout
    assert "worker-7" in result.stdout
    assert "refactor-auth-flow" in result.stdout


def test_settle_status_with_unknown_run_ref_exits_nonzero(app: typer.Typer, runner: CliRunner) -> None:
    """``settle status <run_ref>`` exits non-zero and prints an error when the record is missing."""
    with patch(
        "mahavishnu.cli.settle_cli.load_record_sync",
        return_value=None,
    ):
        result = runner.invoke(app, ["settle", "status", "missing-run"])

    assert result.exit_code != 0
    assert "missing-run" in result.stderr or "not found" in result.stderr.lower()


# ---------------------------------------------------------------------------
# settle start
# ---------------------------------------------------------------------------


def test_settle_start_invokes_persist_initial_with_record(app: typer.Typer, runner: CliRunner) -> None:
    """``settle start <run_ref> --worker <id> --task <sig>`` builds a SettleRunRecord and persists it."""
    from mahavishnu.settle.state_machine import SettleRunRecord, SettleState

    captured: dict[str, SettleRunRecord] = {}

    def _capture_persist(record: SettleRunRecord) -> SettleRunRecord:
        captured["record"] = record
        return record

    with patch(
        "mahavishnu.cli.settle_cli.persist_initial",
        side_effect=_capture_persist,
    ):
        result = runner.invoke(
            app,
            [
                "settle",
                "start",
                "run-1",
                "--worker",
                "worker-9",
                "--task",
                "add-coverage",
            ],
        )

    assert result.exit_code == 0, result.stdout
    record = captured["record"]
    assert record.run_ref == "run-1"
    assert record.worker_id == "worker-9"
    assert record.task_signature == "add-coverage"
    assert record.state == SettleState.PROPOSED
    assert record.bindings == ()
    assert "run-1" in result.stdout
    assert "proposed" in result.stdout.lower()
