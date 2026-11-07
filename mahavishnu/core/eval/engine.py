"""The eval engine — the primitive that runs a suite against a model (REQ-EVAL-003).

The engine composes the four extension points (dataset loader, scorer,
storage, model backend) and turns them into a scored, persisted, queryable
run. It is deliberately **not** an ``OrchestratorAdapter`` subclass: the
adapter contract is ``(task, repos) -> dict`` and the eval contract is
``(suite, model_config, budget) -> EvalRunResult``, and forcing eval
through the adapter signature would be dishonest about both.

**Span cardinality (REQ-EVAL-011).** The ``eval.run_suite`` span carries a
closed, fixed set of attribute keys. Per-case data lives in the run store,
not in span attributes — the v7 substrate's cardinality alarm fires on any
key outside :data:`SPAN_ATTRIBUTE_KEYS`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
import time
import traceback
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable
from uuid import uuid7

from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field

from mahavishnu.core.errors import EvalEngineError
from mahavishnu.core.eval.dataset import Dataset, DatasetCase
from mahavishnu.core.eval.scorer import Scorer
from mahavishnu.core.eval.storage import (
    CaseRecord,
    EvalSummary,
    RunRecord,
    ScoreRecord,
)

if TYPE_CHECKING:
    from mahavishnu.core.eval.settings import EvalSettings
    from mahavishnu.core.eval.storage import EvalStorage

logger = logging.getLogger(__name__)

# req: REQ-EVAL-002, REQ-EVAL-003

_tracer = trace.get_tracer(__name__)


def _redacted_traceback(exc: BaseException) -> str:
    """Format an exception's traceback with credentials redacted.

    The traceback is the operator's debugging material, but an
    arbitrary exception's text is untrusted: it is whatever the
    failing layer wrote, and this repo's logging pipeline does not
    redact. So the text goes through the repo's own credential
    redactor (``mahavishnu.core.secure_logging``) before it is
    logged, and it is logged at debug level -- the root logger runs at
    INFO, so the detail is off by default.

    Args:
        exc: The exception to format.

    Returns:
        The formatted traceback, with credentials redacted.
    """
    from mahavishnu.core.secure_logging import CredentialRedactor

    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return CredentialRedactor().redact_string(text)


def _redacted_message(exc: BaseException) -> str:
    """Format an exception's message with credentials redacted.

    Unlike the traceback, the message is *persisted*: it becomes
    ``CaseRecord.error``, which ``add_case_result`` writes to the eval
    store and the run report renders. A backend or scorer that echoes
    its auth header puts a live credential in that text, and this
    repo's logging pipeline does not redact -- so the redaction has to
    happen here, before the text leaves the engine.

    Args:
        exc: The exception whose message to format.

    Returns:
        The exception's message, with credentials redacted.
    """
    from mahavishnu.core.secure_logging import CredentialRedactor

    return CredentialRedactor().redact_string(str(exc))


#: The closed set of attribute keys the ``eval.run_suite`` span may carry.
#: REQ-EVAL-011: this keyspace is fixed and closed. Per-case keys
#: (``eval.case_id``, ``eval.prompt_hash``, ``eval.case.*``) are never
#: emitted — the v7 substrate's cardinality alarm would fire on them.
SPAN_ATTRIBUTE_KEYS = frozenset(
    {
        "eval.suite_name",
        "eval.model",
        "eval.case_count",
        "eval.cost_usd",
        "eval.duration_ms",
        "eval.outcome",
        "eval.total_input_tokens",
        "eval.total_output_tokens",
    }
)


class TokenUsage(BaseModel):
    """Token counts for one model call."""

    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ModelResponse(BaseModel):
    """One model's response to one prompt."""

    model_config = ConfigDict(extra="forbid")

    output: str
    usage: TokenUsage | None = None
    latency_ms: float | None = None


class ModelConfig(BaseModel):
    """Identifies the model a run uses and prices its tokens.

    Pricing is per 1000 tokens. The defaults are zero — the mock backend
    is free — so a run only spends budget when the operator has priced
    the model.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = "mahavishnu.mock"
    max_tokens: int = 1024
    input_cost_per_1k_tokens: float = 0.0
    output_cost_per_1k_tokens: float = 0.0


@runtime_checkable
class ModelBackend(Protocol):
    """Calls a model and returns its response."""

    async def complete(self, prompt: str, model_config: ModelConfig) -> ModelResponse:
        """Call the model.

        Args:
            prompt: The prompt to send.
            model_config: The model to call and how it is priced.

        Returns:
            The model's response.
        """
        ...


#: The suite's concurrency ceiling: the limit on in-flight model calls.
#:
#: Phase 1's engine awaits each case before starting the next, so the
#: ceiling is never contended -- the budget guard is exact because the
#: spend is checked before every case. The limit is still declared,
#: because it is the bound the engine applies when the loop is widened.
#: There is deliberately no operator knob for it: a knob whose only
#: effect is to set a ceiling the engine never reaches is a knob that
#: lies.
DEFAULT_MAX_CONCURRENCY = 20


class CostBudget(BaseModel):
    """The per-run cost cap and the concurrency limit."""

    model_config = ConfigDict(extra="forbid")

    max_usd: float = 5.0
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY


class EvalSuite(BaseModel):
    """A dataset plus the model, scorers, and budget to run it with.

    The model configuration is the field ``model``, not ``model_config``:
    ``model_config`` is Pydantic v2's reserved name for a model's
    configuration and cannot be used as a field name.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    name: str
    version: str = "v0"
    dataset: Dataset
    scorers: list[Scorer] = Field(default_factory=list)
    model: ModelConfig = Field(default_factory=ModelConfig)
    cost_budget: CostBudget = Field(default_factory=CostBudget)


class EvalRunResult(BaseModel):
    """The outcome of one suite run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: Literal["completed", "budget_exceeded", "failed"]
    finished_at: datetime
    summary: EvalSummary


@dataclass
class _RunOutcome:
    """What the engine observed while running a suite's cases."""

    result: EvalRunResult
    input_tokens: int = 0
    output_tokens: int = 0
    spent_usd: float = 0.0
    case_results: list[CaseRecord] = field(default_factory=list)
    scores: list[ScoreRecord] = field(default_factory=list)


class EvalEngine:
    """Runs a suite against a model and records every result.

    Args:
        storage: Where runs, case results, and scores are written.
        model_backend: The model the suite runs against.
        settings: The eval settings. Its ``cost_budget_per_run`` caps
            the suite budget's ``max_usd``.
    """

    def __init__(
        self,
        storage: EvalStorage,
        model_backend: ModelBackend,
        settings: EvalSettings | None = None,
    ) -> None:
        self._storage = storage
        self._model_backend = model_backend
        self._settings = settings

    async def run_suite(self, suite: EvalSuite) -> EvalRunResult:
        """Run a suite end to end and record every result.

        Args:
            suite: The suite to run.

        Returns:
            The run's outcome. The run is persisted before this returns.

        Raises:
            EvalEngineError: If the run cannot be completed.
        """
        started = time.perf_counter()
        with _tracer.start_as_current_span("eval.run_suite") as span:
            outcome = await self._run_suite_inner(suite, started, span)
            self._annotate_span(span, suite, outcome)
            return outcome.result

    async def _run_suite_inner(
        self,
        suite: EvalSuite,
        started: float,
        span: trace.Span,
    ) -> _RunOutcome:
        """Run every case of the suite, then finalize the run."""
        run_id = uuid7().hex
        await self._storage.start_run(self._run_record(run_id, suite))

        outcome = _RunOutcome(
            result=EvalRunResult(
                run_id=run_id,
                status="completed",
                finished_at=datetime.now(UTC),
                summary=self._empty_summary(),
            )
        )
        semaphore = asyncio.Semaphore(self._concurrency(suite))

        budget_cap = self._budget_cap(suite)
        try:
            for index, case in enumerate(suite.dataset.cases):
                if not self._track_budget(outcome.spent_usd, budget_cap):
                    break
                record, scores, cost, tokens_in, tokens_out = await self._run_one_case(
                    suite, case, index, run_id, semaphore
                )
                outcome.case_results.append(record)
                outcome.scores.extend(scores)
                outcome.spent_usd += cost
                outcome.input_tokens += tokens_in
                outcome.output_tokens += tokens_out
        except Exception as exc:
            # The exception's text is untrusted input: it is whatever
            # the failing layer wrote, and this repo's logging pipeline
            # does not redact. So the failure is *classified* rather
            # than attached -- the house rule is `logger.exception`,
            # and it is deliberately not followed here, because
            # `logger.exception` attaches the raw message and the raw
            # traceback to the log record. The operator still gets the
            # detail: the traceback is redacted through the repo's own
            # credential redactor and logged at debug level, which the
            # INFO root leaves off by default.
            logger.error(
                "eval.run.failed run_id=%s cases=%d/%d error_type=%s",
                run_id,
                len(outcome.case_results),
                len(suite.dataset.cases),
                type(exc).__name__,
            )
            logger.debug(
                "eval.run.failed_detail run_id=%s detail=%s",
                run_id,
                _redacted_traceback(exc),
            )
            await self._mark_run_failed(run_id, outcome, started)
            # The span is the run's rollback signal. Without attributes
            # a failed run's span is indistinguishable from a span the
            # process never got to instrument, and the plan's contract
            # says a failed run is visible as ``eval.outcome="failed"``.
            # The attributes stay inside the closed keyspace -- no
            # per-case keys.
            span.set_attribute("eval.outcome", "failed")
            span.set_attribute("eval.case_count", len(outcome.case_results))
            span.set_attribute(
                "eval.duration_ms", (time.perf_counter() - started) * 1000.0
            )
            raise EvalEngineError(
                f"the eval run {run_id!r} failed after "
                f"{len(outcome.case_results)} of "
                f"{len(suite.dataset.cases)} cases",
                # The cause is logged, not returned. `MahavishnuError
                # .to_dict()` serialises `details` into API responses,
                # and an arbitrary exception's text can carry anything
                # the failing layer put in it -- a connection string, a
                # file path, a fragment of a credential. The client
                # gets the run id and the counts, which is what it can
                # act on; the operator gets the traceback in the log.
                details={
                    "run_id": run_id,
                    "cases_completed": len(outcome.case_results),
                    "cases_total": len(suite.dataset.cases),
                    "error_type": type(exc).__name__,
                },
            ) from exc

        outcome.result = await self._summarize_run(suite, run_id, outcome, started)
        return outcome

    async def _run_one_case(
        self,
        suite: EvalSuite,
        case: DatasetCase,
        index: int,
        run_id: str,
        semaphore: asyncio.Semaphore,
    ) -> tuple[CaseRecord, list[ScoreRecord], float, int, int]:
        """Run one case: call the model, score the output, persist both.

        A failing case is recorded with its error and does not stop the
        run.
        """
        record = CaseRecord(
            id=uuid7().hex,
            run_id=run_id,
            case_id=case.id,
            case_index=index,
            actual="",
            scored=False,
        )
        try:
            async with semaphore:
                response = await self._model_backend.complete(case.input, suite.model)
        except Exception as exc:  # noqa: BLE001 - the backend may raise anything
            # Same discipline as the run-failure path: the exception's
            # text is untrusted, so the failure is *classified* rather
            # than attached. `logger.exception` would attach the raw
            # message and the raw traceback to the log record; the
            # operator still gets the detail, redacted, at debug level.
            logger.error(
                "eval.case.failed case_id=%s error_type=%s",
                case.id,
                type(exc).__name__,
            )
            logger.debug(
                "eval.case.failed_detail case_id=%s detail=%s",
                case.id,
                _redacted_traceback(exc),
            )
            record.error = _redacted_message(exc)
            await self._storage.add_case_result(record)
            return record, [], 0.0, 0, 0

        record.actual = response.output
        scores = self._score_case(suite, case, record, response)
        record.scored = bool(scores)
        await self._storage.add_case_result(record, scores)

        tokens_in, tokens_out = self._token_counts(suite.model, response)
        return (
            record,
            scores,
            self._estimate_cost(suite.model, response),
            tokens_in,
            tokens_out,
        )

    def _score_case(
        self,
        suite: EvalSuite,
        case: DatasetCase,
        record: CaseRecord,
        response: ModelResponse,
    ) -> list[ScoreRecord]:
        """Score one case's output with every configured scorer.

        A scorer that raises is logged and skipped; the run continues.
        """
        scores: list[ScoreRecord] = []
        for scorer in suite.scorers:
            try:
                score = scorer.score(response.output, case.expected, case.metadata)
            except Exception as exc:  # noqa: BLE001 - a scorer may raise anything
                # Same discipline as the run-failure path: classify the
                # failure, and redact the message before it is persisted.
                logger.error(
                    "eval.scorer.error scorer=%s case_id=%s error_type=%s",
                    scorer.name,
                    case.id,
                    type(exc).__name__,
                )
                logger.debug(
                    "eval.scorer.error_detail scorer=%s case_id=%s detail=%s",
                    scorer.name,
                    case.id,
                    _redacted_traceback(exc),
                )
                record.error = _redacted_message(exc)
                continue
            scores.append(
                ScoreRecord(
                    id=uuid7().hex,
                    case_id=record.id,
                    scorer_name=scorer.name,
                    value=score.value,
                    kind=score.kind,
                    reasoning=score.reasoning,
                )
            )
        return scores

    async def _summarize_run(
        self,
        suite: EvalSuite,
        run_id: str,
        outcome: _RunOutcome,
        started: float,
    ) -> EvalRunResult:
        """Build the run's summary, persist it, and return the outcome."""
        status = self._run_status(suite, outcome)
        summary = self._build_summary(outcome, started)
        finished_at = datetime.now(UTC)
        await self._storage.finish_run(run_id, status, finished_at, summary)
        return EvalRunResult(
            run_id=run_id,
            status=status,
            finished_at=finished_at,
            summary=summary,
        )

    def _run_status(
        self,
        suite: EvalSuite,
        outcome: _RunOutcome,
    ) -> Literal["completed", "budget_exceeded", "failed"]:
        """Return the terminal status of a run whose loop finished.

        There are two ways to exhaust the operator's budget:

        - the run *spent* past the cap, and
        - the cap was too small for even the first case, so the loop
          broke before any case ran.

        The second case is why the status cannot be derived from the
        spend alone: a zero budget spends nothing, so it is neither
        "strictly past the cap" nor a completed run. Reporting it as
        completed tells a caller the suite ran when not one case did --
        and a caller who asked for a zero budget is exactly the caller
        who must not be told the run succeeded.
        """
        if outcome.spent_usd > self._budget_cap(suite):
            return "budget_exceeded"
        if suite.dataset.cases and not outcome.case_results:
            return "budget_exceeded"
        return "completed"

    def _build_summary(self, outcome: _RunOutcome, started: float) -> EvalSummary:
        """Build the aggregate statistics of a run."""
        values = [score.value for score in outcome.scores]
        return EvalSummary(
            total_cases=len(outcome.case_results),
            scored_cases=sum(1 for record in outcome.case_results if record.scored),
            errors=sum(1 for record in outcome.case_results if record.error),
            duration_seconds=time.perf_counter() - started,
            cost_usd=outcome.spent_usd,
            mean_score=(sum(values) / len(values)) if values else 0.0,
            min_score=min(values) if values else 0.0,
            max_score=max(values) if values else 0.0,
        )

    async def _mark_run_failed(
        self,
        run_id: str,
        outcome: _RunOutcome,
        started: float,
    ) -> None:
        """Mark a run as failed after an unhandled error.

        Without this the run row keeps ``status="running"`` and a NULL
        ``finished_at``, which reads as "still running" forever. The
        storage may be the very thing that failed, so a failure to
        record the failure is logged rather than raised -- the original
        error is the one worth surfacing.
        """
        try:
            await self._storage.finish_run(
                run_id,
                status="failed",
                finished_at=datetime.now(UTC),
                summary=self._build_summary(outcome, started),
            )
        except Exception as exc:  # noqa: BLE001 - the store may raise anything
            logger.error(
                "eval.run.record_failed run_id=%s error_type=%s",
                run_id,
                type(exc).__name__,
            )
            logger.debug(
                "eval.run.record_failed_detail run_id=%s detail=%s",
                run_id,
                _redacted_traceback(exc),
            )

    def _run_record(self, run_id: str, suite: EvalSuite) -> RunRecord:
        """Build the run's record."""
        return RunRecord(
            id=run_id,
            suite_name=suite.name,
            suite_version=suite.version,
            suite_hash=suite.dataset.content_hash,
            model_configs={suite.model.name: suite.model.model_dump()},
            started_at=datetime.now(UTC),
        )

    def _annotate_span(self, span: Any, suite: EvalSuite, outcome: _RunOutcome) -> None:
        """Set the span's attributes — the closed keyspace and nothing else."""
        span.set_attribute("eval.suite_name", suite.name)
        span.set_attribute("eval.model", suite.model.name)
        span.set_attribute("eval.case_count", outcome.result.summary["total_cases"])
        span.set_attribute("eval.cost_usd", outcome.result.summary["cost_usd"])
        span.set_attribute(
            "eval.duration_ms", outcome.result.summary["duration_seconds"] * 1000.0
        )
        span.set_attribute("eval.outcome", outcome.result.status)
        span.set_attribute("eval.total_input_tokens", outcome.input_tokens)
        span.set_attribute("eval.total_output_tokens", outcome.output_tokens)

    def _budget_cap(self, suite: EvalSuite) -> float:
        """Return the effective cost cap for a suite.

        The suite's own cap is a *request*; the operator's setting is a
        *ceiling*. A caller that names a larger cap -- an MCP client
        passing ``params={"budget_usd": 1000}``, say -- is clamped down
        to it. Without the clamp the operator's budget is a suggestion
        any caller can raise.

        Args:
            suite: The suite being run.

        Returns:
            The cap the run is held to.
        """
        cap = suite.cost_budget.max_usd
        if self._settings is not None:
            cap = min(cap, self._settings.cost_budget_per_run)
        return cap

    def _track_budget(self, spent_usd: float, max_usd: float) -> bool:
        """Return True while the run still has budget for another case."""
        return spent_usd < max_usd

    def _concurrency(self, suite: EvalSuite) -> int:
        """Return the suite's concurrency limit.

        The limit is the suite's own ``CostBudget.max_concurrency``. There
        is no operator knob for it: Phase 1's loop awaits each case
        before starting the next, so the limit is the bound the engine
        applies when the loop is widened -- and a knob whose only effect
        is to set a bound the engine never reaches is a knob that lies.
        """
        return max(1, suite.cost_budget.max_concurrency)

    def _token_counts(
        self, model: ModelConfig, response: ModelResponse
    ) -> tuple[int, int]:
        """Return the input and output token counts for one call.

        Falls back to ``max_tokens`` when the backend reports no usage —
        the estimate is then an upper bound, which is the safe direction
        for a budget guard.
        """
        if response.usage is None:
            return model.max_tokens, model.max_tokens
        return response.usage.prompt_tokens, response.usage.completion_tokens

    def _estimate_cost(self, model: ModelConfig, response: ModelResponse) -> float:
        """Estimate the cost of one model call."""
        tokens_in, tokens_out = self._token_counts(model, response)
        return (
            tokens_in / 1000.0 * model.input_cost_per_1k_tokens
            + tokens_out / 1000.0 * model.output_cost_per_1k_tokens
        )

    @staticmethod
    def _empty_summary() -> EvalSummary:
        """The summary of a run that has produced nothing yet."""
        return EvalSummary(
            total_cases=0,
            scored_cases=0,
            errors=0,
            duration_seconds=0.0,
            cost_usd=0.0,
            mean_score=0.0,
            min_score=0.0,
            max_score=0.0,
        )


__all__ = [
    "SPAN_ATTRIBUTE_KEYS",
    "CostBudget",
    "EvalEngine",
    "EvalEngineError",
    "EvalRunResult",
    "EvalSuite",
    "ModelBackend",
    "ModelConfig",
    "ModelResponse",
    "TokenUsage",
]
