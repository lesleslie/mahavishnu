"""Tests for :class:`mahavishnu.cli.base.MahavishnuCLI` OneiricCLIBase subclass.

Phase 3 Task 4.6 — OneiricCLIBase adoption for mahavishnu. These tests guard
that the subclass wires up version/doctor/health correctly and that the
override hooks return real data (not ``{}`` or ``UNAVAILABLE`` stubs).
"""
from __future__ import annotations

import json

import typer
from typer.testing import CliRunner

from mahavishnu.cli.base import MahavishnuCLI

runner = CliRunner()


def test_mahavishnucli_component_name() -> None:
    """The subclass must declare component_name='mahavishnu'."""
    cli = MahavishnuCLI()
    assert cli.component_name == "mahavishnu"


def test_mahavishnucli_inherits_typer() -> None:
    """OneiricCLIBase inherits typer.Typer, so MahavishnuCLI must too."""
    assert issubclass(MahavishnuCLI, typer.Typer)


def test_doctor_checks_returns_real_entries() -> None:
    """_doctor_checks() must return a non-empty dict with real check entries.

    Not a stub that returns {}. Per OneiricCLIBase contract, doctor must call
    into the repo's existing health surface.
    """
    cli = MahavishnuCLI()
    checks = cli._doctor_checks()
    assert isinstance(checks, dict)
    assert len(checks) > 0
    for info in checks.values():
        assert isinstance(info, dict)
        assert "status" in info
        assert "detail" in info


def test_doctor_checks_contains_expected_categories() -> None:
    """_doctor_checks() must include workers/registry/config categories."""
    cli = MahavishnuCLI()
    checks = cli._doctor_checks()
    assert "workers" in checks
    assert "registry" in checks
    assert "config" in checks


def test_health_probe_returns_real_snapshot() -> None:
    """_health_probe() must return a non-empty dict with status/component.

    Not a stub that raises NotImplementedError (-> UNAVAILABLE).
    """
    cli = MahavishnuCLI()
    snapshot = cli._health_probe()
    assert isinstance(snapshot, dict)
    assert snapshot.get("component") == "mahavishnu"
    assert "status" in snapshot
    assert snapshot["status"] in {"healthy", "degraded", "unhealthy"}


def test_version_command_runs() -> None:
    """`mahavishnu version` should print the component version."""
    cli = MahavishnuCLI()
    result = runner.invoke(cli, ["version"])
    assert result.exit_code == 0
    assert "mahavishnu" in result.stdout


def test_doctor_command_runs_and_outputs_checks() -> None:
    """`mahavishnu doctor` must run via OneiricCLIBase and emit check info."""
    cli = MahavishnuCLI()
    result = runner.invoke(cli, ["doctor"])
    # exit_code 0 (all healthy) or 1 (some unhealthy) both acceptable; the
    # critical assertion is that doctor did NOT raise UNAVAILABLE (exit 3).
    assert result.exit_code in {0, 1}
    assert "workers" in result.stdout or "registry" in result.stdout


def test_doctor_command_json_output() -> None:
    """`mahavishnu --json doctor` must emit a JSON payload.

    OneiricCLIBase wires `--json` as a global option on the root callback;
    typer requires the global option to come BEFORE the subcommand.
    """
    cli = MahavishnuCLI()
    result = runner.invoke(cli, ["--json", "doctor"])
    assert result.exit_code in {0, 1}
    # Output is a JSON object containing a "checks" key.
    payload = json.loads(result.stdout)
    assert "checks" in payload
    assert isinstance(payload["checks"], dict)


def test_health_command_runs() -> None:
    """`mahavishnu health` must run via OneiricCLIBase and emit a snapshot."""
    cli = MahavishnuCLI()
    result = runner.invoke(cli, ["health"])
    # Should NOT be UNAVAILABLE (3) — _health_probe is real.
    assert result.exit_code != 3
    assert "mahavishnu" in result.stdout


def test_health_command_json_output() -> None:
    """`mahavishnu --json health` must emit a JSON payload.

    OneiricCLIBase wires `--json` as a global option; it must precede the
    subcommand for typer to dispatch correctly.
    """
    cli = MahavishnuCLI()
    result = runner.invoke(cli, ["--json", "health"])
    assert result.exit_code != 3
    payload = json.loads(result.stdout)
    assert payload.get("component") == "mahavishnu"


def test_oneiric_cli_base_run_wires_typer() -> None:
    """OneiricCLIBase.run() wires up typer correctly.

    The base typer.Typer is callable. MahavishnuCLI inherits this
    behaviour, so invoking the cli with no args should NOT raise a
    Typer-specific error (it may print help and exit 0).
    """
    cli = MahavishnuCLI()
    # Calling the typer with no command should show help (exit 0 or 2).
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code in {0, 2}
    assert "mahavishnu" in result.stdout.lower() or "Mahavishnu" in result.stdout


def test_mahavishnucli_detects_version() -> None:
    """OneiricCLIBase._detect_version should resolve mahavishnu's metadata."""
    cli = MahavishnuCLI()
    # Either a real version or the "(not installed)" sentinel.
    assert isinstance(cli.component_version, str)
    assert cli.component_version != ""
