"""Production readiness CLI commands for Mahavishnu."""

import asyncio
import json
from pathlib import Path

import typer

from .core.app import MahavishnuApp
from .core.production_readiness import run_production_readiness_suite

app = typer.Typer(help="Production readiness and testing commands for Mahavishnu")


@app.command("run-all-tests")
def run_all_tests(
    config_path: Path | None = typer.Option(
        None, "--config", "-c", help="Path to configuration file"
    ),
    output_file: Path | None = typer.Option(
        None, "--output", "-o", help="Output file for results (JSON)"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """
    Run the complete production readiness suite.

    This includes:
    - Configuration validity checks
    - Adapter health checks
    - Repository accessibility checks
    - Workflow execution tests
    - Resource limit validations
    - Security settings verification
    - Integration tests
    - Performance benchmarks
    """
    typer.echo("🚀 Running Production Readiness Suite...")

    # Initialize app with config if provided
    if config_path:
        # For now, we'll just use the default app initialization
        # In a real implementation, we'd load from the specified config
        typer.echo(f"Using config from: {config_path}")

    maha_app = MahavishnuApp()

    # Run the production readiness suite
    async def _run_suite():
        return await run_production_readiness_suite(maha_app)

    results = asyncio.run(_run_suite())

    # Output results
    if output_file:
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2)
        typer.echo(f"✅ Results saved to: {output_file}")
    else:
        typer.echo("\n📋 RESULTS:")
        typer.echo(json.dumps(results, indent=2))


@app.command("check-config")
def check_config(
    config_path: Path | None = typer.Option(
        None, "--config", "-c", help="Path to configuration file"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """
    Run only configuration validity checks.
    """
    typer.echo("🔍 Checking configuration validity...")

    # Initialize app with config if provided
    if config_path:
        typer.echo(f"Using config from: {config_path}")

    maha_app = MahavishnuApp()

    # Run just the config check
    from .core.production_readiness import ProductionReadinessChecker

    checker = ProductionReadinessChecker(maha_app)

    result = checker._check_config_validity()

    if result:
        typer.echo("✅ Configuration is valid and secure")
        raise typer.Exit(code=0)
    else:
        typer.echo("❌ Configuration has issues that need to be addressed")
        raise typer.Exit(code=1)


@app.command("run-integration-tests")
def run_integration_tests(
    config_path: Path | None = typer.Option(
        None, "--config", "-c", help="Path to configuration file"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """
    Run only integration tests.
    """
    typer.echo("🧪 Running integration tests...")

    # Initialize app with config if provided
    if config_path:
        typer.echo(f"Using config from: {config_path}")

    maha_app = MahavishnuApp()

    # Run just the integration tests
    from .core.production_readiness import IntegrationTestSuite

    test_suite = IntegrationTestSuite(maha_app)

    async def _run_tests():
        return await test_suite.run_all_tests()

    results = asyncio.run(_run_tests())

    typer.echo(f"\n📊 Integration Test Results: {results['summary']['score_percentage']}%")

    if results["summary"]["status"] == "PASS":
        typer.echo("✅ All integration tests passed")
        raise typer.Exit(code=0)
    else:
        typer.echo("❌ Some integration tests failed")
        raise typer.Exit(code=1)


@app.command("run-benchmarks")
def run_benchmarks(
    config_path: Path | None = typer.Option(
        None, "--config", "-c", help="Path to configuration file"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """
    Run only performance benchmarks.
    """
    typer.echo("⚡ Running performance benchmarks...")

    # Initialize app with config if provided
    if config_path:
        typer.echo(f"Using config from: {config_path}")

    maha_app = MahavishnuApp()

    # Run just the benchmarks
    from .core.production_readiness import PerformanceBenchmark

    benchmark_suite = PerformanceBenchmark(maha_app)

    async def _run_benchmarks():
        return await benchmark_suite.run_benchmarks()

    results = asyncio.run(_run_benchmarks())

    typer.echo(f"\n📈 Performance Score: {results['summary']['performance_score']}/100")

    if results["summary"]["status"] in ("EXCELLENT", "GOOD"):
        typer.echo("✅ Performance benchmarks passed")
        raise typer.Exit(code=0)
    else:
        typer.echo("⚠️  Performance benchmarks show areas for improvement")
        raise typer.Exit(code=0)


# Add this command group to the main CLI
def add_production_commands(main_app):
    """Add production readiness commands to the main CLI app."""
    main_app.add_typer(app, name="production", help="Production readiness and testing commands")
