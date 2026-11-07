"""CLI for the model-evaluation subsystem (REQ-EVAL-010).

The MCP tool group (:func:`mahavishnu.mcp.tools.eval_tools.register_eval_tools`)
is the surface an agent uses. This module is the surface an *operator*
uses: a scriptable command line that runs a dataset, persists the run,
and writes the Markdown report.

Commands:
    mahavishnu eval run-suite --suite docs/eval/dogfood-v0.jsonl
    mahavishnu eval list-runs --limit 10
    mahavishnu eval show-run <run-id>

**``--model`` names a backend, not a model.** The registry publishes
backend names (``mahavishnu.mock``, and whatever a distribution
registers under ``mahavishnu.eval.model_backends``). ``MiniMax-M3`` is
a model *name*; it is what a backend is asked to call, not a backend.
The default is ``mahavishnu.mock``, which needs no credential and
echoes the prompt back -- useful for checking that a dataset loads and
runs, useless for judging a model.

**``EvalSettings.enabled`` does not gate this CLI.** That flag exists
to decide whether the MCP tools are *registered*; an operator who
types the command has already decided.
"""

from __future__ import annotations

import asyncio

# typer resolves the command's annotations at runtime
# (annotationlib.get_annotations), so a TYPE_CHECKING-only ``Path``
# raises NameError when the command is registered. Verified 2026-11-06
# with typer 0.27.3.
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING

import typer

from mahavishnu.core.errors import EvalStorageError

if TYPE_CHECKING:
    from mahavishnu.core.eval.engine import EvalRunResult, ModelBackend
    from mahavishnu.core.eval.scorer import Scorer
    from mahavishnu.core.eval.settings import EvalSettings
    from mahavishnu.core.eval.storage import (
        EvalStorage,
        RunDetails,
        RunRecord,
    )

eval_app = typer.Typer(
    name="eval",
    help="Model evaluation commands (mirrors the eval_* MCP tools).",
)


def _settings() -> EvalSettings:
    """Return the eval settings.

    The import is deferred so the module imports cleanly before the
    eval package is loaded.
    """
    from mahavishnu.core.eval.settings import get_eval_settings

    return get_eval_settings()


def _scorer_names(requested: str) -> list[str]:
    """Parse the ``--scorers`` option.

    Args:
        requested: A comma-separated list of scorer names. Empty means
            the configured defaults.

    Returns:
        The scorer names to use.
    """
    if not requested.strip():
        return list(_settings().default_scorers)
    return [name.strip() for name in requested.split(",") if name.strip()]


def _build_scorers(names: list[str]) -> list[Scorer]:
    """Instantiate the named scorers.

    Args:
        names: The scorer names.

    Returns:
        The scorer instances.

    Raises:
        typer.BadParameter: If a name is not registered.
    """
    from mahavishnu.core.eval._registry import discover_scorers

    registry = discover_scorers()
    scorers: list[Scorer] = []
    for name in names:
        scorer_cls = registry.get(name)
        if scorer_cls is None:
            raise typer.BadParameter(
                f"unknown scorer {name!r}; available: {', '.join(sorted(registry))}"
            )
        scorers.append(scorer_cls())
    return scorers


def _build_storage() -> EvalStorage:
    """Build the configured run store.

    Returns:
        The storage instance.

    Raises:
        typer.BadParameter: If the configured storage is not registered.
    """
    from mahavishnu.core.eval._registry import discover_storage

    settings = _settings()
    storage_cls = discover_storage().get(settings.default_storage)
    if storage_cls is None:
        raise typer.BadParameter(
            f"unknown storage {settings.default_storage!r}; available: "
            f"{', '.join(sorted(discover_storage()))}"
        )
    return storage_cls(db_path=settings.db_path)


def _build_backend(name: str) -> ModelBackend:
    """Build the named model backend.

    Args:
        name: The backend name.

    Returns:
        The backend instance.

    Raises:
        typer.BadParameter: If the name is not registered.
    """
    from mahavishnu.core.eval._registry import discover_model_backends

    registry = discover_model_backends()
    backend_cls = registry.get(name)
    if backend_cls is None:
        raise typer.BadParameter(
            f"unknown model backend {name!r}; available: {', '.join(sorted(registry))}"
        )
    return backend_cls()


async def _run_suite_async(
    suite_path: Path,
    backend_name: str,
    budget: float | None,
    scorer_names: list[str],
) -> tuple[EvalRunResult, RunDetails]:
    """Run a suite and persist it.

    Args:
        suite_path: The JSONL dataset to run.
        backend_name: The model backend to run it against.
        budget: The per-run cost cap, or ``None`` for the configured one.
        scorer_names: The scorers to apply.

    Returns:
        The run's result and its persisted details. Both come from one
        event loop and one storage instance: the store keeps a live
        SQLite connection, and opening a second one in a second loop
        to re-read the run the first one just wrote would be two
        connections to the same file for no reason.
    """
    from mahavishnu.core.eval._registry import discover_dataset_loaders
    from mahavishnu.core.eval.engine import (
        DEFAULT_MAX_CONCURRENCY,
        CostBudget,
        EvalEngine,
        EvalSuite,
        ModelConfig,
    )

    settings = _settings()
    loaders = discover_dataset_loaders()
    loader_cls = loaders.get(settings.default_dataset_loader)
    if loader_cls is None:
        raise typer.BadParameter(
            f"unknown dataset loader {settings.default_dataset_loader!r}; "
            f"available: {', '.join(sorted(loaders)) or '(none registered)'}"
        )
    dataset = await loader_cls().load(suite_path)

    eval_suite = EvalSuite(
        name=dataset.name,
        version=dataset.version,
        dataset=dataset,
        scorers=_build_scorers(scorer_names),
        model=ModelConfig(name=backend_name),
        cost_budget=CostBudget(
            max_usd=settings.cost_budget_per_run if budget is None else budget,
            max_concurrency=DEFAULT_MAX_CONCURRENCY,
        ),
    )
    storage = _build_storage()
    engine = EvalEngine(
        storage=storage,
        model_backend=_build_backend(backend_name),
        settings=settings,
    )
    result = await engine.run_suite(eval_suite)
    details = await storage.get_run(result.run_id)
    if details is None:
        raise EvalStorageError(
            f"the run {result.run_id!r} vanished from the run store",
            details={"run_id": result.run_id},
        )
    return result, details


@eval_app.command("run-suite")
def run_suite(
    suite: Path = typer.Option(
        ...,
        "--suite",
        exists=True,
        dir_okay=False,
        help="Path to the JSONL dataset to run.",
    ),
    model: str = typer.Option(
        "mahavishnu.mock",
        "--model",
        help=(
            "Model *backend* name from the eval registry "
            "(mahavishnu.mock, ...). Not a model name."
        ),
    ),
    budget: float | None = typer.Option(
        None,
        "--budget",
        help="Per-run cost cap in USD. Defaults to the configured budget.",
    ),
    scorers: str = typer.Option(
        "",
        "--scorers",
        help=(
            "Comma-separated scorer names. Defaults to the configured "
            "scorers (mahavishnu.contains)."
        ),
    ),
    report_dir: Path | None = typer.Option(
        None,
        "--report-dir",
        help="Where to write the Markdown report. Defaults to <run store>/reports.",
    ),
) -> None:
    """Run a dataset against a model backend and write the report."""
    from mahavishnu.core.eval.report import default_report_path, write_run_markdown

    scorer_names = _scorer_names(scorers)
    result, details = asyncio.run(_run_suite_async(suite, model, budget, scorer_names))
    summary = result.summary

    if report_dir is not None:
        report_path = report_dir / f"{result.run_id}.md"
    else:
        report_path = default_report_path(_settings().db_path, result.run_id)
    write_run_markdown(
        details.run,
        details.case_results,
        details.scores,
        report_path,
    )

    typer.echo(f"run_id:   {result.run_id}")
    typer.echo(f"status:   {result.status}")
    typer.echo(f"cases:    {summary['total_cases']}")
    typer.echo(f"scored:   {summary['scored_cases']}")
    typer.echo(f"errors:   {summary['errors']}")
    typer.echo(f"mean:     {summary['mean_score']:.3f}")
    typer.echo(f"cost_usd: {summary['cost_usd']:.4f}")
    typer.echo(f"report:   {report_path}")


async def _fetch_details(run_id: str) -> RunDetails | None:
    """Fetch a run with its cases and scores.

    Args:
        run_id: The run id.

    Returns:
        The run details, or ``None`` if the run cannot be read.
    """
    storage = _build_storage()
    return await storage.get_run(run_id)


@eval_app.command("list-runs")
def list_runs(
    limit: int = typer.Option(10, "--limit", min=1, help="How many runs to list."),
) -> None:
    """List the most recent evaluation runs."""
    runs = asyncio.run(_list_runs_async(limit))
    if not runs:
        typer.echo("no evaluation runs recorded")
        return
    for run in runs:
        typer.echo(
            f"{run.id}  {run.status:<16} {run.suite_name:<24} "
            f"{run.started_at.isoformat()}"
        )


async def _list_runs_async(limit: int) -> list[RunRecord]:
    """Fetch the most recent runs.

    Args:
        limit: How many runs to fetch.

    Returns:
        The runs, newest first.
    """
    storage = _build_storage()
    return await storage.list_runs(limit=limit)


@eval_app.command("show-run")
def show_run(
    run_id: str = typer.Argument(..., help="The run id to show."),
) -> None:
    """Show one evaluation run's details."""
    details = asyncio.run(_fetch_details(run_id))
    if details is None:
        typer.echo(f"no evaluation run with id {run_id!r}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"run_id:   {details.run.id}")
    typer.echo(f"suite:    {details.run.suite_name} ({details.run.suite_version})")
    typer.echo(f"status:   {details.run.status}")
    typer.echo(f"cases:    {len(details.case_results)}")
    typer.echo(f"scores:   {len(details.scores)}")


def add_eval_commands(app: typer.Typer) -> None:
    """Register the eval sub-app on the main CLI app.

    Args:
        app: The main Typer app to attach to.
    """
    app.add_typer(eval_app, name="eval")


__all__ = ["add_eval_commands", "eval_app"]
