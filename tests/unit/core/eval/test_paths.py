"""Path-confinement tests for evaluation datasets (REQ-EVAL-002).

The eval MCP tools are server-reachable: a client names a dataset path
and the server reads it. These tests pin the confinement that keeps a
client from naming any file on disk.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mahavishnu.core.errors import EvalDatasetLoadError
from mahavishnu.core.eval.paths import resolve_dataset_path

if TYPE_CHECKING:
    from pathlib import Path

# req: REQ-EVAL-002


@pytest.mark.req(["REQ-EVAL-002"])
def test_a_path_inside_the_root_resolves(tmp_path: Path) -> None:
    """A dataset inside the root resolves to its absolute path."""
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text("{}\n", encoding="utf-8")

    resolved = resolve_dataset_path(dataset, tmp_path)
    assert resolved == dataset.resolve()


@pytest.mark.req(["REQ-EVAL-002"])
def test_a_path_outside_the_root_is_refused(tmp_path: Path) -> None:
    """A dataset outside the root is refused."""
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "elsewhere.jsonl"
    outside.write_text("{}\n", encoding="utf-8")

    with pytest.raises(EvalDatasetLoadError, match="outside the eval dataset root"):
        resolve_dataset_path(outside, root)


@pytest.mark.req(["REQ-EVAL-002"])
def test_a_traversal_path_is_refused(tmp_path: Path) -> None:
    """A ``..`` traversal out of the root is refused."""
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(EvalDatasetLoadError, match="outside the eval dataset root"):
        resolve_dataset_path(root / ".." / "secret.jsonl", root)


@pytest.mark.req(["REQ-EVAL-002"])
def test_a_symlink_out_of_the_root_is_refused(tmp_path: Path) -> None:
    """A symlink inside the root that points out of it is refused.

    The resolution is symlink-aware, so the link's *target* is what gets
    checked against the root.
    """
    root = tmp_path / "root"
    root.mkdir()
    target = tmp_path / "secret.jsonl"
    target.write_text("{}\n", encoding="utf-8")
    link = root / "link.jsonl"
    link.symlink_to(target)

    with pytest.raises(EvalDatasetLoadError, match="outside the eval dataset root"):
        resolve_dataset_path(link, root)


@pytest.mark.req(["REQ-EVAL-002"])
def test_an_empty_path_is_refused(tmp_path: Path) -> None:
    """An empty path is refused rather than resolving to the cwd."""
    with pytest.raises(EvalDatasetLoadError, match="empty"):
        resolve_dataset_path("   ", tmp_path)


@pytest.mark.req(["REQ-EVAL-002"])
def test_a_null_byte_in_the_path_is_refused(tmp_path: Path) -> None:
    """A null byte in the path is refused."""
    with pytest.raises(EvalDatasetLoadError, match="null byte"):
        resolve_dataset_path("cases.jsonl\x00.txt", tmp_path)
