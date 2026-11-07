"""Scorer contract for the eval framework (REQ-EVAL-002).

A scorer turns one case's actual output and its expected output into a
single number in ``[0, 1]``. Scoring is **synchronous** — comparing two
strings is CPU-bound and there is nothing to await. Scorers that need a
model call (LLM-as-judge) land in Phase 2 as ``async def score`` with an
``asyncio.to_thread`` dispatch.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from mahavishnu.core.errors import EvalScoringError

if TYPE_CHECKING:
    from collections.abc import Mapping

# req: REQ-EVAL-002


class Score(BaseModel):
    """One scorer's verdict on one case."""

    model_config = ConfigDict(extra="forbid")

    value: float = Field(ge=0.0, le=1.0, description="Score in the unit interval")
    kind: str = Field(description="Scorer family, e.g. 'exact_match'")
    reasoning: str | None = Field(
        default=None, description="Why the scorer reached this value"
    )


class Scorer(ABC):
    """Scores one case's actual output against its expected output.

    Implementations are registered under the ``mahavishnu.eval.scorers``
    entry-point group; see ``mahavishnu/core/eval/_registry.py``.
    """

    #: The extension-point name this scorer is registered under.
    name: str = "scorer"
    #: The scorer family, recorded on every :class:`Score` it produces.
    kind: str = "exact"

    @abstractmethod
    def score(
        self,
        actual: str,
        expected: str,
        case_meta: Mapping[str, Any],
    ) -> Score:
        """Score one case.

        Args:
            actual: The model's output for the case.
            expected: The expected output for the case.
            case_meta: The case's metadata, for scorers that are
                case-sensitive (a per-case threshold, say).

        Returns:
            The score, with a value in ``[0, 1]``.

        Raises:
            EvalScoringError: If the scorer cannot reach a verdict.
        """
        raise NotImplementedError


__all__ = [
    "EvalScoringError",
    "Score",
    "Scorer",
]
