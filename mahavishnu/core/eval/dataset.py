"""Dataset model and loader contract for the eval framework (REQ-EVAL-002).

A dataset is an ordered, content-addressed collection of evaluation cases.
The loader is the pluggable extension point: a dataset can come from
JSONL on disk, from a LangSmith dataset, or from anywhere else, as long
as it resolves to a :class:`Dataset`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mahavishnu.core.errors import EvalDatasetLoadError

if TYPE_CHECKING:
    from pathlib import Path

# req: REQ-EVAL-002


class DatasetCase(BaseModel):
    """One evaluation case: an input, the expected output, and metadata."""

    model_config = ConfigDict(extra="forbid")

    id: str
    input: str
    expected: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Dataset(BaseModel, ABC):
    """An immutable, content-addressed collection of evaluation cases.

    ``content_hash`` is the digest of the source material, so two datasets
    with the same hash are the same dataset regardless of where they were
    loaded from.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    cases: list[DatasetCase]
    content_hash: str
    version: str

    @model_validator(mode="after")
    def _require_at_least_one_case(self) -> Dataset:
        """Reject an empty dataset — a run over zero cases proves nothing."""
        if not self.cases:
            raise ValueError("a dataset must contain at least one case")
        return self


class DatasetLoader(ABC):
    """Loads a :class:`Dataset` from a source.

    Implementations are registered under the
    ``mahavishnu.eval.dataset_loaders`` entry-point group; see
    ``mahavishnu/core/eval/_registry.py``.
    """

    @abstractmethod
    async def load(self, path: Path) -> Dataset:
        """Load the dataset at ``path``.

        Args:
            path: Location of the dataset source.

        Returns:
            The loaded dataset.

        Raises:
            EvalDatasetLoadError: If the source is missing, malformed, or
                yields no cases.
        """
        raise NotImplementedError


__all__ = [
    "Dataset",
    "DatasetCase",
    "DatasetLoader",
    "EvalDatasetLoadError",
]
