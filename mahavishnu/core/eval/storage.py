"""Run-storage contract for the eval framework (REQ-EVAL-002).

A run store holds three kinds of row: the run itself, one row per case
result, and one row per score. The concrete backend is pluggable — the
Phase 1 backend is SQLite (see
``mahavishnu/core/eval/storage_backends/sqlite.py``).

**ID convention.** Every row id is a UUID7 hex string
(``uuid7().hex``) — the app layer generates it and passes it in. Note the
distinction between ``CaseRecord.id`` (the row's own id) and
``CaseRecord.case_id`` (the id of the case *in the dataset*):
``ScoreRecord.case_id`` references ``CaseRecord.id``, not the dataset
case id.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from mahavishnu.core.errors import EvalStorageError

if TYPE_CHECKING:
    from collections.abc import Sequence

# req: REQ-EVAL-002

#: The states a run can be in.
RunStatus = Literal["running", "completed", "budget_exceeded", "failed"]


class EvalSummary(TypedDict):
    """Aggregate statistics for one eval run."""

    total_cases: int
    scored_cases: int
    errors: int
    duration_seconds: float
    cost_usd: float
    mean_score: float
    min_score: float
    max_score: float


def _zero_summary() -> EvalSummary:
    """The summary of a run that has not produced any results yet."""
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


class RunRecord(BaseModel):
    """One evaluation run."""

    model_config = ConfigDict(extra="forbid")

    id: str
    suite_name: str
    suite_version: str
    suite_hash: str
    model_configs: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime
    finished_at: datetime | None = None
    status: RunStatus = "running"
    summary: EvalSummary = Field(default_factory=_zero_summary)


class CaseRecord(BaseModel):
    """The result of running one dataset case.

    ``id`` is this row's id; ``case_id`` is the id of the case in the
    dataset it came from.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    run_id: str
    case_id: str
    case_index: int
    actual: str
    error: str | None = None
    scored: bool = False


class ScoreRecord(BaseModel):
    """One scorer's verdict on one case result.

    ``case_id`` references :attr:`CaseRecord.id` — the row id — not the
    dataset case id.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    case_id: str
    scorer_name: str
    value: float
    kind: str
    reasoning: str | None = None


class RunDetails(BaseModel):
    """A run together with its case results and their scores."""

    model_config = ConfigDict(extra="forbid")

    run: RunRecord
    case_results: list[CaseRecord] = Field(default_factory=list)
    scores: list[ScoreRecord] = Field(default_factory=list)


class EvalStorage(ABC):
    """Stores evaluation runs, their case results, and their scores.

    Implementations are registered under the ``mahavishnu.eval.storage``
    entry-point group; see ``mahavishnu/core/eval/_registry.py``.
    """

    @abstractmethod
    async def start_run(self, run: RunRecord) -> str:
        """Record the start of a run.

        Args:
            run: The run to record. Its ``id`` is the caller's UUID7 hex.

        Returns:
            The run id.

        Raises:
            EvalStorageError: If the run cannot be written.
        """
        raise NotImplementedError

    @abstractmethod
    async def add_case_result(
        self,
        case: CaseRecord,
        scores: Sequence[ScoreRecord] = (),
    ) -> None:
        """Record one case result and its scores.

        Args:
            case: The case result.
            scores: The scores produced for it. Each score's ``case_id``
                must equal ``case.id``.

        Raises:
            EvalStorageError: If the result cannot be written.
        """
        raise NotImplementedError

    @abstractmethod
    async def finish_run(
        self,
        run_id: str,
        status: RunStatus,
        finished_at: datetime,
        summary: EvalSummary,
    ) -> None:
        """Transition a run out of the ``running`` state.

        Args:
            run_id: The run to finish.
            status: The terminal status.
            finished_at: When the run finished.
            summary: The run's aggregate statistics.

        Raises:
            EvalStorageError: If the run cannot be updated.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_run(self, run_id: str) -> RunDetails | None:
        """Return a run with its case results and scores.

        Args:
            run_id: The run to fetch.

        Returns:
            The run, or ``None`` if no such run exists.
        """
        raise NotImplementedError

    @abstractmethod
    async def list_runs(self, limit: int = 50) -> list[RunRecord]:
        """Return the most recent runs, newest first.

        Args:
            limit: The maximum number of runs to return.

        Returns:
            The runs.
        """
        raise NotImplementedError


__all__ = [
    "CaseRecord",
    "EvalStorage",
    "EvalStorageError",
    "EvalSummary",
    "RunDetails",
    "RunRecord",
    "RunStatus",
    "ScoreRecord",
]
