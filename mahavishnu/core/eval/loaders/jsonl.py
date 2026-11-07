"""JSONL dataset loader (REQ-EVAL-002).

One JSON object per line, four keys per case:

.. code-block:: json

    {"id": "route-1", "input": "which selector?", "expected": "least_loaded", "metadata": {}}
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from mahavishnu.core.errors import EvalDatasetLoadError
from mahavishnu.core.eval._compat import hash_content
from mahavishnu.core.eval.dataset import Dataset, DatasetCase, DatasetLoader

if TYPE_CHECKING:
    from pathlib import Path


class JsonlDatasetLoader(DatasetLoader):
    """Loads a dataset from a JSONL file — one JSON object per line."""

    async def load(self, path: Path) -> Dataset:
        """Load the JSONL dataset at ``path``.

        Args:
            path: Path to the JSONL file.

        Returns:
            The loaded dataset.

        Raises:
            EvalDatasetLoadError: If the file is missing, a line is not
                valid JSON, a line does not validate as a case, or the
                file contains no cases.
        """
        # A read does not create directories. The earlier
        # ``path.parent.mkdir(parents=True, exist_ok=True)`` made the
        # loader a writer: naming a dataset that did not exist created
        # the directory tree leading to it. On a server-reachable path
        # that is an arbitrary-directory-creation primitive.
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise EvalDatasetLoadError(
                f"{path}: cannot read dataset ({exc})",
                details={"path": str(path)},
            ) from exc

        cases = self._parse_cases(path, raw)
        if not cases:
            raise EvalDatasetLoadError(
                f"{path}: contains no cases",
                details={"path": str(path)},
            )

        return Dataset(
            name=path.stem,
            cases=cases,
            content_hash=await hash_content(raw),
            version="v0",
        )

    def _parse_cases(self, path: Path, raw: str) -> list[DatasetCase]:
        """Parse the JSONL body into cases, naming the offending line."""
        cases: list[DatasetCase] = []
        for lineno, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvalDatasetLoadError(
                    f"{path}: line {lineno}: invalid JSON ({exc.msg})",
                    details={"path": str(path), "line": lineno},
                ) from exc
            cases.append(self._build_case(path, lineno, payload))
        return cases

    def _build_case(self, path: Path, lineno: int, payload: Any) -> DatasetCase:
        """Build one case, naming the offending line on a validation failure."""
        try:
            return DatasetCase.model_validate(payload)
        except ValidationError as exc:
            raise EvalDatasetLoadError(
                f"{path}: line {lineno}: invalid case "
                f"({exc.error_count()} validation error(s))",
                details={"path": str(path), "line": lineno},
            ) from exc
