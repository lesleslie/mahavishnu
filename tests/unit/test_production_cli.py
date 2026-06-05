"""Unit tests for the Mahavishnu production CLI module.

Covers:
    - add_production_commands() registration of the 'production' sub-typer
    - Discovery of the four subcommands (check, test, benchmark, suite)
    - Presence of the --detailed/-d flag on every subcommand
    - --help output for the parent group and each subcommand
    - End-to-end invocation with mocked production_readiness classes
      (avoiding instantiation of a real MahavishnuApp)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from mahavishnu.production_cli import add_production_commands

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_readiness_components() -> dict[str, MagicMock]:
    """Build a set of mocks for the production_readiness classes.

    All async methods return JSON-serialisable dictionaries so the
    --detailed branch can be exercised safely.
    """
    checker = MagicMock()
    checker.run_all_checks = AsyncMock(return_value={"status": "ok", "checks": []})

    tests = MagicMock()
    tests.run_all_tests = AsyncMock(return_value={"status": "ok", "tests": []})

    benchmarks = MagicMock()
    benchmarks.run_benchmarks = AsyncMock(return_value={"status": "ok", "latency_ms": 1.0})

    suite = AsyncMock(return_value={"status": "ok", "summary": "all green"})

    return {
        "ProductionReadinessChecker": checker,
        "IntegrationTestSuite": tests,
        "PerformanceBenchmark": benchmarks,
        "run_production_readiness_suite": suite,
    }


def _build_app_with_mocks() -> typer.Typer:
    """Construct a fresh parent Typer app and patch heavy dependencies.

    Returns the app ready to be invoked. The patches are in effect for
    the duration of the calling test because ``patch`` is used as a
    context manager inside the helper.
    """
    app = typer.Typer()
    mocks = _make_mock_readiness_components()

    patcher_checker = patch(
        "mahavishnu.core.production_readiness.ProductionReadinessChecker",
        return_value=mocks["ProductionReadinessChecker"],
    )
    patcher_tests = patch(
        "mahavishnu.core.production_readiness.IntegrationTestSuite",
        return_value=mocks["IntegrationTestSuite"],
    )
    patcher_bench = patch(
        "mahavishnu.core.production_readiness.PerformanceBenchmark",
        return_value=mocks["PerformanceBenchmark"],
    )
    patcher_suite = patch(
        "mahavishnu.core.production_readiness.run_production_readiness_suite",
        mocks["run_production_readiness_suite"],
    )
    patcher_app = patch("mahavishnu.core.app.MahavishnuApp")

    # Activate all patches and store them on the app so tests can stop them
    # via app._active_patches.
    active = [
        patcher_checker.__enter__(),
        patcher_tests.__enter__(),
        patcher_bench.__enter__(),
        patcher_suite.__enter__(),
        patcher_app.__enter__(),
    ]
    app._active_patches = active  # type: ignore[attr-defined]

    add_production_commands(app)
    return app


def _release_app(app: typer.Typer) -> None:
    """Release any active patchers attached to the app."""
    for p in getattr(app, "_active_patches", []):
        p.__exit__(None, None, None)


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestAddProductionCommands:
    """Tests for the add_production_commands registration helper."""

    def test_add_production_commands_registers_group(self) -> None:
        """The 'production' group is added to the parent app."""
        app = typer.Typer()
        try:
            add_production_commands(app)
            group_names = [g.name for g in app.registered_groups]
            assert "production" in group_names
        finally:
            _release_app(app)

    def test_add_production_commands_attaches_typer_instance(self) -> None:
        """The registered group carries a Typer sub-application."""
        app = typer.Typer()
        try:
            add_production_commands(app)
            production_groups = [g for g in app.registered_groups if g.name == "production"]
            assert len(production_groups) == 1
            assert isinstance(production_groups[0].typer_instance, typer.Typer)
        finally:
            _release_app(app)

    def test_add_production_commands_idempotent_on_fresh_apps(self) -> None:
        """Calling add_production_commands on two fresh parents works independently."""
        app_a = typer.Typer()
        app_b = typer.Typer()
        try:
            add_production_commands(app_a)
            add_production_commands(app_b)
            assert "production" in [g.name for g in app_a.registered_groups]
            assert "production" in [g.name for g in app_b.registered_groups]
        finally:
            _release_app(app_a)
            _release_app(app_b)

    def test_parent_help_lists_production(self) -> None:
        """The parent Typer app's --help mentions the production group."""
        app = typer.Typer()
        try:
            add_production_commands(app)
            result = runner.invoke(app, ["--help"])
            assert result.exit_code == 0
            assert "production" in result.stdout
        finally:
            _release_app(app)


# ---------------------------------------------------------------------------
# Subcommand registration tests
# ---------------------------------------------------------------------------


class TestSubcommandRegistration:
    """Tests verifying each expected subcommand is registered."""

    @staticmethod
    def _production_typer(app: typer.Typer) -> typer.Typer:
        groups = [g for g in app.registered_groups if g.name == "production"]
        assert groups, "production group not registered"
        return groups[0].typer_instance

    def test_all_four_subcommands_registered(self) -> None:
        """All four subcommands (check, test, benchmark, suite) are registered."""
        app = typer.Typer()
        try:
            add_production_commands(app)
            sub = self._production_typer(app)
            names = {cmd.name for cmd in sub.registered_commands}
            assert {"check", "test", "benchmark", "suite"} <= names
        finally:
            _release_app(app)

    @pytest.mark.parametrize("sub_name", ["check", "test", "benchmark", "suite"])
    def test_each_subcommand_is_discoverable(self, sub_name: str) -> None:
        """Each subcommand is callable via the production group."""
        app = typer.Typer()
        try:
            add_production_commands(app)
            sub = self._production_typer(app)
            names = {cmd.name for cmd in sub.registered_commands}
            assert sub_name in names
        finally:
            _release_app(app)


# ---------------------------------------------------------------------------
# --detailed flag tests
# ---------------------------------------------------------------------------


class TestDetailedFlag:
    """Tests for the --detailed / -d flag on every subcommand."""

    @pytest.mark.parametrize("sub_name", ["check", "test", "benchmark", "suite"])
    def test_subcommand_help_documents_detailed_flag(self, sub_name: str) -> None:
        """Each subcommand's --help lists the --detailed / -d flag."""
        app = typer.Typer()
        try:
            add_production_commands(app)
            result = runner.invoke(app, ["production", sub_name, "--help"])
            assert result.exit_code == 0
            assert "--detailed" in result.stdout
            assert "-d" in result.stdout
        finally:
            _release_app(app)

    @pytest.mark.parametrize("sub_name", ["check", "test", "benchmark", "suite"])
    def test_subcommand_runs_with_detailed_flag(self, sub_name: str) -> None:
        """Each subcommand runs successfully with --detailed (mocked I/O)."""
        app = _build_app_with_mocks()
        try:
            result = runner.invoke(app, ["production", sub_name, "--detailed"])
            assert result.exit_code == 0, result.stdout
        finally:
            _release_app(app)

    @pytest.mark.parametrize("sub_name", ["check", "test", "benchmark", "suite"])
    def test_subcommand_runs_with_short_detailed_flag(self, sub_name: str) -> None:
        """Each subcommand accepts the short -d flag."""
        app = _build_app_with_mocks()
        try:
            result = runner.invoke(app, ["production", sub_name, "-d"])
            assert result.exit_code == 0, result.stdout
        finally:
            _release_app(app)


# ---------------------------------------------------------------------------
# Help output tests
# ---------------------------------------------------------------------------


class TestHelpOutput:
    """Tests for --help text content."""

    def test_production_group_help_text(self) -> None:
        """The production group's help text is 'Production readiness checks and benchmarks'."""
        app = typer.Typer()
        try:
            add_production_commands(app)
            result = runner.invoke(app, ["production", "--help"])
            assert result.exit_code == 0
            assert "Production readiness checks and benchmarks" in result.stdout
        finally:
            _release_app(app)

    def test_production_group_help_lists_all_subcommands(self) -> None:
        """The production group's --help lists check, test, benchmark, suite."""
        app = typer.Typer()
        try:
            add_production_commands(app)
            result = runner.invoke(app, ["production", "--help"])
            assert result.exit_code == 0
            for sub_name in ("check", "test", "benchmark", "suite"):
                assert sub_name in result.stdout
        finally:
            _release_app(app)

    def test_check_help_describes_command(self) -> None:
        """The 'check' subcommand --help describes its purpose."""
        app = typer.Typer()
        try:
            add_production_commands(app)
            result = runner.invoke(app, ["production", "check", "--help"])
            assert result.exit_code == 0
            assert "production readiness checks" in result.stdout.lower()
        finally:
            _release_app(app)

    def test_test_help_describes_command(self) -> None:
        """The 'test' subcommand --help describes its purpose."""
        app = typer.Typer()
        try:
            add_production_commands(app)
            result = runner.invoke(app, ["production", "test", "--help"])
            assert result.exit_code == 0
            assert "integration tests" in result.stdout.lower()
        finally:
            _release_app(app)

    def test_benchmark_help_describes_command(self) -> None:
        """The 'benchmark' subcommand --help describes its purpose."""
        app = typer.Typer()
        try:
            add_production_commands(app)
            result = runner.invoke(app, ["production", "benchmark", "--help"])
            assert result.exit_code == 0
            assert "performance benchmarks" in result.stdout.lower()
        finally:
            _release_app(app)

    def test_suite_help_describes_command(self) -> None:
        """The 'suite' subcommand --help describes its purpose."""
        app = typer.Typer()
        try:
            add_production_commands(app)
            result = runner.invoke(app, ["production", "suite", "--help"])
            assert result.exit_code == 0
            assert "production readiness suite" in result.stdout.lower()
        finally:
            _release_app(app)


# ---------------------------------------------------------------------------
# Invocation tests (with mocked heavy dependencies)
# ---------------------------------------------------------------------------


class TestSubcommandInvocation:
    """End-to-end tests invoking each subcommand with patched I/O."""

    def test_check_invocation_without_detailed(self) -> None:
        """The 'check' subcommand runs without --detailed and exits 0."""
        app = _build_app_with_mocks()
        try:
            result = runner.invoke(app, ["production", "check"])
            assert result.exit_code == 0, result.stdout
        finally:
            _release_app(app)

    def test_check_with_detailed_emits_json(self) -> None:
        """The 'check' subcommand with --detailed prints JSON to stdout."""
        app = _build_app_with_mocks()
        try:
            result = runner.invoke(app, ["production", "check", "--detailed"])
            assert result.exit_code == 0, result.stdout
            assert '"status"' in result.stdout
            assert '"ok"' in result.stdout
        finally:
            _release_app(app)

    def test_test_invocation_without_detailed(self) -> None:
        """The 'test' subcommand runs without --detailed and exits 0."""
        app = _build_app_with_mocks()
        try:
            result = runner.invoke(app, ["production", "test"])
            assert result.exit_code == 0, result.stdout
        finally:
            _release_app(app)

    def test_test_with_detailed_emits_json(self) -> None:
        """The 'test' subcommand with --detailed prints JSON to stdout."""
        app = _build_app_with_mocks()
        try:
            result = runner.invoke(app, ["production", "test", "--detailed"])
            assert result.exit_code == 0, result.stdout
            assert '"status"' in result.stdout
        finally:
            _release_app(app)

    def test_benchmark_invocation_without_detailed(self) -> None:
        """The 'benchmark' subcommand runs without --detailed and exits 0."""
        app = _build_app_with_mocks()
        try:
            result = runner.invoke(app, ["production", "benchmark"])
            assert result.exit_code == 0, result.stdout
        finally:
            _release_app(app)

    def test_benchmark_with_detailed_emits_json(self) -> None:
        """The 'benchmark' subcommand with --detailed prints JSON to stdout."""
        app = _build_app_with_mocks()
        try:
            result = runner.invoke(app, ["production", "benchmark", "--detailed"])
            assert result.exit_code == 0, result.stdout
            assert '"status"' in result.stdout
        finally:
            _release_app(app)

    def test_suite_invocation_without_detailed(self) -> None:
        """The 'suite' subcommand runs without --detailed and exits 0."""
        app = _build_app_with_mocks()
        try:
            result = runner.invoke(app, ["production", "suite"])
            assert result.exit_code == 0, result.stdout
        finally:
            _release_app(app)

    def test_suite_with_detailed_emits_json(self) -> None:
        """The 'suite' subcommand with --detailed prints JSON to stdout."""
        app = _build_app_with_mocks()
        try:
            result = runner.invoke(app, ["production", "suite", "--detailed"])
            assert result.exit_code == 0, result.stdout
            assert '"status"' in result.stdout
        finally:
            _release_app(app)

    def test_mahavishnu_app_not_instantiated_when_help_only(self) -> None:
        """--help invocations must not construct a real MahavishnuApp."""
        with patch("mahavishnu.core.app.MahavishnuApp") as mock_app_cls:
            app = typer.Typer()
            try:
                add_production_commands(app)
                # Reading --help on the group should not instantiate the app
                runner.invoke(app, ["production", "--help"])
                # The MahavishnuApp class may be referenced at import time, but
                # --help alone should not call the constructor
                assert mock_app_cls.call_count == 0
            finally:
                _release_app(app)
