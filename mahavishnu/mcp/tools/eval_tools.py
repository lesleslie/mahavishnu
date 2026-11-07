"""MCP tools for the model-evaluation subsystem (REQ-EVAL-005).

Three tools, registered as a profile-gated group:

- ``eval_register_dataset`` — load a JSONL dataset and describe it.
- ``eval_run_suite`` — run a dataset against a model backend and score it.
- ``eval_get_run`` — fetch a persisted run's record, cases, and scores.

**The tools bypass ``EvalPool`` in Phase 1.** They call
:class:`~mahavishnu.core.eval.engine.EvalEngine` directly. The eval pool
is registered so eval is discoverable through the pool machinery and so
Phase 2 can route eval work across pools; routing a Phase 1 run through
it would add a pool round-trip without adding a capability.

There are two ``enabled`` checks, and they do different jobs:

1. **At registration** — when evaluation is off the group is not
   registered at all, so the tools are absent from ``tools/list``.
2. **In each body** — a server that started with evaluation on and had
   it turned off mid-flight returns ``{"status": "error", "error":
   "evaluation disabled"}`` rather than running an unbudgeted suite.

Every tool body delegates to a module-level ``_do_*`` helper so the
complexity budget is spread across three small bodies and three small
helpers rather than concentrated in one long function.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any

from ...core.errors import (
    EvalDatasetLoadError,
    EvalEngineError,
    EvalScoringError,
    EvalStorageError,
)
from ...core.eval._registry import (
    discover_dataset_loaders,
    discover_model_backends,
    discover_scorers,
    discover_storage,
)
from ...core.eval.engine import (
    DEFAULT_MAX_CONCURRENCY,
    CostBudget,
    EvalEngine,
    EvalSuite,
    ModelConfig,
)
from ...core.eval.paths import resolve_dataset_path
from ..eval_feed import record_eval_cycle, record_eval_error

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastmcp import FastMCP

    from ...core.eval.scorer import Scorer

logger = logging.getLogger(__name__)

# req: REQ-EVAL-005

#: The eval errors a tool body reports by name rather than as an
#: opaque "internal error".
_EVAL_ERRORS = (
    EvalDatasetLoadError,
    EvalScoringError,
    EvalStorageError,
    EvalEngineError,
)

#: The payload a tool returns when evaluation is turned off.
_DISABLED = {"status": "error", "error": "evaluation disabled"}


def _lookup(
    registry: dict[str, Callable[..., Any]],
    name: str,
    kind: str,
) -> Callable[..., Any]:
    """Look an extension point up in its registry.

    A bare ``registry[name]`` raises ``KeyError``, which the tool's
    guard flattens to ``{"error": "internal error"}`` -- a server
    fault, reported for what is almost always a client mistake. The
    likeliest mistake is naming a *model* (``MiniMax-M3``) where a
    *backend* (``mahavishnu.mock``) is wanted, so the message says
    what was wanted and lists what exists.

    Args:
        registry: The registry to look in.
        name: The name to look for.
        kind: What the name names ("model backend", "dataset loader",
            ...), used in the error message.

    Returns:
        The registered callable.

    Raises:
        EvalEngineError: If the name is not registered.
    """
    if name not in registry:
        available = ", ".join(sorted(registry)) or "(none registered)"
        raise EvalEngineError(
            f"unknown {kind} {name!r}; available: {available}",
            details={"kind": kind, "name": name, "available": sorted(registry)},
        )
    return registry[name]


def register_eval_tools(server: FastMCP) -> None:
    """Register the eval tool group.

    Args:
        server: The FastMCP server to register on.
    """
    from ...core.eval.settings import get_eval_settings

    if not get_eval_settings().enabled:
        logger.info("Eval tools not registered: evaluation is disabled")
        return

    @server.tool(
        name="eval_register_dataset",
        description=(
            "Load an evaluation dataset (JSONL) and describe it: name, "
            "version, case count, and content hash. Use it to check a "
            "dataset before spending budget on it."
        ),
    )
    async def eval_register_dataset(path: str) -> dict[str, Any]:
        """Load a dataset and return its metadata.

        Args:
            path: Path to the JSONL dataset.

        Returns:
            The dataset's metadata, or an error dict.
        """
        from ...core.eval.settings import get_eval_settings

        if not get_eval_settings().enabled:
            return dict(_DISABLED)
        return await _guarded(
            lambda: _do_register_dataset(path),
            action_name="register_dataset",
        )

    @server.tool(
        name="eval_run_suite",
        description=(
            "Run an evaluation suite: load a JSONL dataset, call a model "
            "backend for every case, score the outputs, and persist the "
            "run. Returns the run id, status, and summary."
        ),
    )
    async def eval_run_suite(
        suite: str,
        model: str = "",
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a suite against a model backend.

        Args:
            suite: Path to the JSONL dataset to run.
            model: The model backend name (for example
                ``mahavishnu.mock``). Empty means the configured default.
            params: Optional overrides — ``budget_usd``, ``scorers``
                (a list of scorer names), and ``max_tokens``. The
                budget and the token ceiling are clamped down to the
                operator's settings. There is no concurrency override:
                Phase 1 runs the cases of a suite one at a time.

        Returns:
            The run's status, id, and summary, or an error dict.
        """
        from ...core.eval.settings import get_eval_settings

        if not get_eval_settings().enabled:
            return dict(_DISABLED)
        return await _guarded(
            lambda: _do_run_suite(suite, model, params),
            action_name="run_suite",
        )

    @server.tool(
        name="eval_get_run",
        description=(
            "Fetch a persisted evaluation run: its record, every case "
            "result, and every score."
        ),
    )
    async def eval_get_run(run_id: str) -> dict[str, Any]:
        """Fetch a run's details.

        Args:
            run_id: The run id returned by ``eval_run_suite``.

        Returns:
            The run's details, or an error dict.
        """
        from ...core.eval.settings import get_eval_settings

        if not get_eval_settings().enabled:
            return dict(_DISABLED)
        return await _guarded(
            lambda: _do_get_run(run_id),
            action_name="get_run",
        )

    logger.info("Registered 3 eval tools with MCP server")


async def _guarded(
    action: Callable[[], Awaitable[dict[str, Any]]],
    *,
    action_name: str,
) -> dict[str, Any]:
    """Run an action and convert any failure into an error dict.

    The health feed's error counter is bumped on every failure so an
    operator watching ``/health`` sees the eval subsystem degrade rather
    than silently stop working.

    Args:
        action: A zero-argument callable returning the result dict.
        action_name: The action's name, used in the log line.

    Returns:
        The action's result, or an error dict.
    """
    try:
        return await action()
    except _EVAL_ERRORS as exc:
        record_eval_error()
        logger.exception("eval.%s.failed", action_name)
        return {
            "status": "error",
            "error": str(exc),
            "error_type": type(exc).__name__,
            # The structured context -- a run id, the case counts, the
            # available extension points -- is what tells a client
            # which knob to turn. The details carry structure only;
            # the failing layer's own text is logged, not returned.
            "details": exc.details,
        }
    except Exception as exc:  # final fallback — the tool must not raise
        record_eval_error()
        logger.exception("eval.%s.unexpected_error", action_name)
        return {
            "status": "error",
            "error": "internal error",
            "error_type": type(exc).__name__,
        }


async def _do_register_dataset(path: str) -> dict[str, Any]:
    """Load a dataset and describe it.

    Args:
        path: Path to the JSONL dataset.

    Returns:
        The dataset's metadata.
    """
    from ...core.eval.settings import get_eval_settings

    settings = get_eval_settings()
    loader_cls = _lookup(
        discover_dataset_loaders(),
        settings.default_dataset_loader,
        "dataset loader",
    )
    dataset = await loader_cls().load(resolve_dataset_path(path, settings.dataset_root))
    return {
        "status": "ok",
        "name": dataset.name,
        "version": dataset.version,
        "cases": len(dataset.cases),
        "content_hash": dataset.content_hash,
    }


async def _do_run_suite(
    suite: str,
    model: str,
    params: dict[str, Any] | None,
) -> dict[str, Any]:
    """Run a suite and persist the run.

    Args:
        suite: Path to the JSONL dataset to run.
        model: The model backend name. Empty means the default.
        params: Optional overrides.

    Returns:
        The run's status, id, summary, and the path of the Markdown
        report the run wrote.
    """
    from ...core.eval.settings import get_eval_settings

    settings = get_eval_settings()
    overrides = params or {}
    backend_name = model or settings.default_model_backend

    loader_cls = _lookup(
        discover_dataset_loaders(),
        settings.default_dataset_loader,
        "dataset loader",
    )
    backend_cls = _lookup(
        discover_model_backends(),
        backend_name,
        "model backend",
    )
    storage_cls = _lookup(
        discover_storage(),
        settings.default_storage,
        "storage backend",
    )

    dataset = await loader_cls().load(
        resolve_dataset_path(suite, settings.dataset_root)
    )
    scorers = _build_scorers(
        [str(name) for name in overrides.get("scorers", settings.default_scorers)]
    )
    eval_suite = EvalSuite(
        name=dataset.name,
        version=dataset.version,
        dataset=dataset,
        scorers=scorers,
        model=ModelConfig(
            name=backend_name,
            max_tokens=int(
                _clamped(
                    overrides.get("max_tokens", 1024),
                    settings.max_tokens_per_call,
                )
            ),
        ),
        cost_budget=CostBudget(
            max_usd=_clamped(
                overrides.get("budget_usd", settings.cost_budget_per_run),
                settings.cost_budget_per_run,
            ),
            max_concurrency=DEFAULT_MAX_CONCURRENCY,
        ),
    )

    storage = storage_cls(db_path=settings.db_path)
    engine = EvalEngine(
        storage=storage,
        model_backend=backend_cls(),
        settings=settings,
    )
    result = await engine.run_suite(eval_suite)
    record_eval_cycle(case_count=result.summary["total_cases"])

    details = await storage.get_run(result.run_id)
    report_path = None
    if details is not None:
        from ...core.eval.report import default_report_path, write_run_markdown

        report_path = default_report_path(settings.db_path, result.run_id)
        write_run_markdown(
            details.run,
            details.case_results,
            details.scores,
            report_path,
        )

    return {
        "status": result.status,
        "run_id": result.run_id,
        "summary": dict(result.summary),
        "report_path": str(report_path) if report_path is not None else None,
    }


async def _do_get_run(run_id: str) -> dict[str, Any]:
    """Fetch a persisted run's details.

    Args:
        run_id: The run id.

    Returns:
        The run's record, case results, and scores.

    Raises:
        EvalStorageError: If no such run exists.
    """
    from ...core.eval.settings import get_eval_settings

    settings = get_eval_settings()
    storage_cls = _lookup(
        discover_storage(),
        settings.default_storage,
        "storage backend",
    )
    storage = storage_cls(db_path=settings.db_path)
    details = await storage.get_run(run_id)
    if details is None:
        raise EvalStorageError(
            f"no evaluation run with id {run_id!r}",
            details={"run_id": run_id},
        )
    return {
        "status": details.run.status,
        "run_id": details.run.id,
        "summary": dict(details.run.summary),
        "case_results": [case.model_dump(mode="json") for case in details.case_results],
        "scores": [score.model_dump(mode="json") for score in details.scores],
    }


def _clamped(value: Any, ceiling: float) -> float:
    """Clamp a caller-supplied limit to the operator's ceiling.

    A caller may *lower* a limit -- a smaller budget is safer, a smaller
    token ceiling is cheaper -- but never raise one. Without the clamp
    the operator's budget is a suggestion any client can overrule.

    A value that is not a finite number is rejected outright rather
    than clamped: ``nan`` would defeat every comparison it takes part
    in, and ``inf`` is a way of asking for no limit at all.

    Args:
        value: The caller-supplied value.
        ceiling: The operator's ceiling.

    Returns:
        The value the run is held to.
    """
    try:
        requested = float(value)
    except TypeError, ValueError:
        return ceiling
    if not math.isfinite(requested):
        return ceiling
    return max(0.0, min(requested, ceiling))


def _build_scorers(names: list[str]) -> list[Scorer]:
    """Instantiate the named scorers.

    Args:
        names: The scorer names to instantiate.

    Returns:
        The instantiated scorers.

    Raises:
        EvalScoringError: If a name is not registered.
    """
    registry = discover_scorers()
    scorers: list[Scorer] = []
    for name in names:
        scorer_cls = registry.get(name)
        if scorer_cls is None:
            raise EvalScoringError(
                f"unknown scorer {name!r}",
                details={"name": name, "available": sorted(registry)},
            )
        scorers.append(scorer_cls())
    return scorers


__all__ = ["register_eval_tools"]
