"""Contract tests for the eval CLI (REQ-EVAL-010).

The CLI is the operator's surface: a scriptable command that runs a
dataset, persists the run, and writes the report. These tests drive it
through typer's runner against a temporary run store.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mahavishnu.cli.eval_cli import add_eval_commands, eval_app

# req: REQ-EVAL-010


@pytest.fixture
def runner() -> CliRunner:
    """A typer CLI runner."""
    return CliRunner()


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    """A two-case JSONL dataset."""
    path = tmp_path / "cases.jsonl"
    path.write_text(
        '{"id": "c1", "input": "ping", "expected": "ping"}\n'
        '{"id": "c2", "input": "pong", "expected": "pong"}\n',
        encoding="utf-8",
    )
    return path


def _use_temp_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the eval settings at a temporary run store.

    Args:
        monkeypatch: The monkeypatch fixture.
        tmp_path: The temporary directory.

    Returns:
        The run store's path.
    """
    from mahavishnu.core.eval.settings import EvalSettings

    store = tmp_path / "runs.sqlite"
    settings = EvalSettings(
        enabled=True,
        db_path=str(store),
        default_model_backend="mahavishnu.mock",
        default_scorers=["mahavishnu.exact_match"],
    )
    monkeypatch.setattr(
        "mahavishnu.core.eval.settings.get_eval_settings",
        lambda: settings,
    )
    return store


@pytest.mark.req(["REQ-EVAL-010"])
def test_run_suite_reports_the_run_and_writes_the_report(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    dataset: Path,
) -> None:
    """``run-suite`` prints the run's numbers and writes the report."""
    _use_temp_store(monkeypatch, tmp_path)

    result = runner.invoke(
        eval_app,
        [
            "run-suite",
            "--suite",
            str(dataset),
            "--model",
            "mahavishnu.mock",
            "--report-dir",
            str(tmp_path / "reports"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "status:   completed" in result.output
    assert "cases:    2" in result.output
    assert "scored:   2" in result.output

    reports = list((tmp_path / "reports").glob("*.md"))
    assert len(reports) == 1
    document = reports[0].read_text(encoding="utf-8")
    assert "## Summary" in document
    assert "## Cases" in document


@pytest.mark.req(["REQ-EVAL-010"])
def test_run_suite_rejects_an_unknown_backend(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    dataset: Path,
) -> None:
    """An unregistered model backend is a clear error, not a traceback."""
    _use_temp_store(monkeypatch, tmp_path)

    result = runner.invoke(
        eval_app,
        ["run-suite", "--suite", str(dataset), "--model", "nope"],
    )

    assert result.exit_code != 0
    assert "unknown model backend" in result.output


@pytest.mark.req(["REQ-EVAL-010"])
def test_run_suite_rejects_an_unknown_scorer(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    dataset: Path,
) -> None:
    """An unregistered scorer is a clear error, not a traceback."""
    _use_temp_store(monkeypatch, tmp_path)

    result = runner.invoke(
        eval_app,
        ["run-suite", "--suite", str(dataset), "--scorers", "nope"],
    )

    assert result.exit_code != 0
    assert "unknown scorer" in result.output


@pytest.mark.req(["REQ-EVAL-010"])
def test_list_runs_reports_an_empty_store(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An empty run store says so rather than printing nothing."""
    _use_temp_store(monkeypatch, tmp_path)

    result = runner.invoke(eval_app, ["list-runs"])

    assert result.exit_code == 0, result.output
    assert "no evaluation runs recorded" in result.output


@pytest.mark.req(["REQ-EVAL-010"])
def test_show_run_reports_an_unknown_run(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An unknown run id exits non-zero with a clear message."""
    _use_temp_store(monkeypatch, tmp_path)

    result = runner.invoke(eval_app, ["show-run", "does-not-exist"])

    assert result.exit_code == 1
    assert "no evaluation run with id" in result.output


@pytest.mark.req(["REQ-EVAL-010"])
def test_add_eval_commands_registers_the_sub_app() -> None:
    """The sub-app is attached under the name ``eval``."""
    import typer

    app = typer.Typer()
    add_eval_commands(app)

    names = {group.name for group in app.registered_groups}
    assert "eval" in names


@pytest.mark.req(["REQ-EVAL-010"])
def test_the_dogfood_golden_set_is_valid_jsonl() -> None:
    """Every line of the golden set is a JSON object with the four fields."""
    import mahavishnu

    path = (
        Path(mahavishnu.__file__).resolve().parents[1]
        / "docs"
        / "eval"
        / "dogfood-v0.jsonl"
    )
    assert path.exists()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        assert set(case) == {"id", "input", "expected", "metadata"}
