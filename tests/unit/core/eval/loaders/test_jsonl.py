"""Contract tests for the JSONL dataset loader (REQ-EVAL-002).

Validates:

- a three-case file loads into three fully-populated ``DatasetCase``
  objects, with a content hash and a name derived from the path;
- malformed JSON and invalid cases raise ``EvalDatasetLoadError`` naming
  the offending line — never a bare ``json.JSONDecodeError`` or
  ``pydantic.ValidationError``;
- an empty file and a missing file both raise ``EvalDatasetLoadError``;
- the loader is discoverable through the registry.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from mahavishnu.core.errors import EvalDatasetLoadError
from mahavishnu.core.eval._registry import discover_dataset_loaders
from mahavishnu.core.eval.loaders.jsonl import JsonlDatasetLoader

if TYPE_CHECKING:
    from pathlib import Path

_CASES: list[dict[str, Any]] = [
    {
        "id": "route-1",
        "input": "which selector?",
        "expected": "least_loaded",
        "metadata": {"added_by": "core-eng", "failure_mode": "wrong selector"},
    },
    {
        "id": "route-2",
        "input": "which adapter?",
        "expected": "prefect",
        "metadata": {"added_by": "core-eng"},
    },
    {
        "id": "route-3",
        "input": "health?",
        "expected": "degraded",
        "metadata": {},
    },
]


@pytest.fixture
def dataset_file(tmp_path: Path) -> Path:
    """Write a three-case JSONL dataset and return its path."""
    path = tmp_path / "golden.jsonl"
    body = "\n".join(json.dumps(case) for case in _CASES)
    path.write_text(f"{body}\n")
    return path


@pytest.mark.req(["REQ-EVAL-002"])
async def test_load_reads_every_case(dataset_file: Path) -> None:
    """A three-case file loads into three fully-populated cases."""
    dataset = await JsonlDatasetLoader().load(dataset_file)

    assert len(dataset.cases) == 3
    assert [case.id for case in dataset.cases] == ["route-1", "route-2", "route-3"]

    first = dataset.cases[0]
    assert first.input == "which selector?"
    assert first.expected == "least_loaded"
    assert first.metadata["added_by"] == "core-eng"
    assert first.metadata["failure_mode"] == "wrong selector"

    assert dataset.name == "golden"
    assert dataset.version == "v0"
    assert len(dataset.content_hash) == 64


@pytest.mark.req(["REQ-EVAL-002"])
async def test_content_hash_is_stable_across_loads(dataset_file: Path) -> None:
    """Loading the same bytes twice yields the same content hash."""
    loader = JsonlDatasetLoader()
    first = await loader.load(dataset_file)
    second = await loader.load(dataset_file)
    assert first.content_hash == second.content_hash


@pytest.mark.req(["REQ-EVAL-002"])
async def test_load_rejects_malformed_json(tmp_path: Path) -> None:
    """Malformed JSON raises EvalDatasetLoadError naming the line."""
    path = tmp_path / "broken.jsonl"
    path.write_text(
        '{"id": "ok", "input": "a", "expected": "a", "metadata": {}}\n{"id": "bad"\n'
    )

    with pytest.raises(EvalDatasetLoadError) as excinfo:
        await JsonlDatasetLoader().load(path)
    assert "line 2" in str(excinfo.value)


@pytest.mark.req(["REQ-EVAL-002"])
async def test_load_rejects_an_invalid_case(tmp_path: Path) -> None:
    """A case missing a required field raises EvalDatasetLoadError."""
    path = tmp_path / "invalid.jsonl"
    path.write_text('{"id": "x", "input": "a"}\n')

    with pytest.raises(EvalDatasetLoadError) as excinfo:
        await JsonlDatasetLoader().load(path)
    assert "line 1" in str(excinfo.value)


@pytest.mark.req(["REQ-EVAL-002"])
async def test_load_rejects_an_empty_dataset(tmp_path: Path) -> None:
    """A file with no cases raises EvalDatasetLoadError."""
    path = tmp_path / "empty.jsonl"
    path.write_text("")

    with pytest.raises(EvalDatasetLoadError) as excinfo:
        await JsonlDatasetLoader().load(path)
    assert "no cases" in str(excinfo.value)


@pytest.mark.req(["REQ-EVAL-002"])
async def test_missing_file_raises_eval_dataset_load_error(tmp_path: Path) -> None:
    """A missing file raises EvalDatasetLoadError, not a bare OSError."""
    with pytest.raises(EvalDatasetLoadError):
        await JsonlDatasetLoader().load(tmp_path / "absent.jsonl")


@pytest.mark.req(["REQ-EVAL-002"])
def test_loader_is_discoverable() -> None:
    """The JSONL loader is discoverable through the registry."""
    loaders = discover_dataset_loaders()
    assert loaders["mahavishnu.jsonl"] is JsonlDatasetLoader
