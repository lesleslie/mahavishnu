"""Production readiness CLI commands."""
from typing import Optional
import typer
import asyncio


def add_production_commands(app: typer.Typer) -> None:
    """Add production readiness commands to the main CLI app."""
    from .core.production_readiness import ProductionReadinessChecker, IntegrationTestSuite, PerformanceBenchmark, run_production_readiness_suite

    production_app = typer.Typer(help="Production readiness checks and benchmarks")
    app.add_typer(production_app, name="production")

    @production_app.command("check")
    def production_check(
        detailed: bool = typer.Option(False, "--detailed", "-d", help="Show detailed results")
    ) -> None:
        """Run production readiness checks."""
        async def _check() -> None:
            from .core.app import MahavishnuApp
            maha_app = MahavishnuApp()
            checker = ProductionReadinessChecker(maha_app)
            results = await checker.run_all_checks()

            if detailed:
                import json
                typer.echo(json.dumps(results, indent=2))

        asyncio.run(_check())

    @production_app.command("test")
    def production_test(
        detailed: bool = typer.Option(False, "--detailed", "-d", help="Show detailed results")
    ) -> None:
        """Run integration tests."""
        async def _test() -> None:
            from .core.app import MahavishnuApp
            maha_app = MahavishnuApp()
            tests = IntegrationTestSuite(maha_app)
            results = await tests.run_all_tests()

            if detailed:
                import json
                typer.echo(json.dumps(results, indent=2))

        asyncio.run(_test())

    @production_app.command("benchmark")
    def production_benchmark(
        detailed: bool = typer.Option(False, "--detailed", "-d", help="Show detailed results")
    ) -> None:
        """Run performance benchmarks."""
        async def _benchmark() -> None:
            from .core.app import MahavishnuApp
            maha_app = MahavishnuApp()
            benchmarks = PerformanceBenchmark(maha_app)
            results = await benchmarks.run_benchmarks()

            if detailed:
                import json
                typer.echo(json.dumps(results, indent=2))

        asyncio.run(_benchmark())

    @production_app.command("suite")
    def production_suite(
        detailed: bool = typer.Option(False, "--detailed", "-d", help="Show detailed results")
    ) -> None:
        """Run complete production readiness suite."""
        async def _suite() -> None:
            from .core.app import MahavishnuApp
            maha_app = MahavishnuApp()
            results = await run_production_readiness_suite(maha_app)

            if detailed:
                import json
                typer.echo(json.dumps(results, indent=2))

        asyncio.run(_suite())
