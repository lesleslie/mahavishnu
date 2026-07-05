"""Tests for indexer module."""

from __future__ import annotations

from datetime import UTC
import os
import time
from typing import TYPE_CHECKING

from mahavishnu.core.code_index.indexer import (
    QUEUE_DIR,
    get_last_indexed_commit,
    index_repo,
    set_last_indexed_commit,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_set_and_get_last_indexed_commit(tmp_path: Path) -> None:
    set_last_indexed_commit(str(tmp_path), "abc123")
    assert get_last_indexed_commit(str(tmp_path)) == "abc123"


def test_get_last_indexed_commit_none(tmp_path: Path) -> None:
    assert get_last_indexed_commit(str(tmp_path)) is None


def test_index_repo_no_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Indexing with no changes returns complete with no files."""
    monkeypatch.setattr(
        "mahavishnu.core.code_index.indexer.get_current_commit",
        lambda _r: "def456",
    )
    set_last_indexed_commit(str(tmp_path), "def456")
    result = index_repo(str(tmp_path), trigger="manual")
    assert result.status == "complete"
    assert result.files_changed == []


def test_index_repo_already_locked(tmp_path: Path) -> None:
    """Indexing a locked repo returns failed."""
    # Create a lock file owned by the current process so acquire() sees it as held.
    lock_file = tmp_path / ".git" / "mahavishnu-index.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()
    lock_file.write_text(f"{pid}\n{time.time()}\n{tmp_path}\n")

    result = index_repo(str(tmp_path), trigger="manual")
    assert result.status == "failed"


def test_queue_dir_path() -> None:
    assert QUEUE_DIR.name == "mahavishnu-index-queue"
    assert QUEUE_DIR.parent.name == "data"


def test_index_repo_full_with_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full index with mock parse_file returns parsed nodes."""
    monkeypatch.setattr(
        "mahavishnu.core.code_index.indexer.get_current_commit",
        lambda _r: "sha1full",
    )
    monkeypatch.setattr(
        "mahavishnu.core.code_index.indexer.filter_changed_files",
        lambda _repo, _commit: ["foo.py"],
    )

    from datetime import datetime

    from mahavishnu.core.code_index.models import CodeGraphNode

    mock_node = CodeGraphNode(
        symbol_id="test|||foo.py|||function|||bar",
        symbol_name="bar",
        symbol_type="function",
        file_path="foo.py",
        repo_path=str(tmp_path),
        last_indexed_at=datetime.now(UTC),
        commit_hash="sha1full",
    )
    monkeypatch.setattr(
        "mahavishnu.core.code_index.indexer.parse_file",
        lambda _fp, _repo, _commit: ([mock_node], []),
    )
    monkeypatch.setattr(
        "mahavishnu.core.code_index.indexer._upsert_to_session_buddy",
        lambda _repo, _nodes, _edges: False,
    )
    monkeypatch.setattr(
        "mahavishnu.core.code_index.indexer._queue_locally",
        lambda _repo, _commit, _nodes, _edges: None,
    )

    result = index_repo(str(tmp_path), trigger="manual", full=True)
    assert result.status == "complete"
    assert result.files_changed == ["foo.py"]
    assert result.parse_failures == 0


def test_index_repo_parse_failure_tolerance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parse failures below threshold still complete successfully."""
    monkeypatch.setattr(
        "mahavishnu.core.code_index.indexer.get_current_commit",
        lambda _r: "sha2partial",
    )
    monkeypatch.setattr(
        "mahavishnu.core.code_index.indexer.filter_changed_files",
        lambda _repo, _commit: ["good.py", "bad.py", "ok.py", "fine.py"],
    )

    call_count = 0

    def mock_parse(_fp, _repo, _commit):
        nonlocal call_count
        call_count += 1
        if _fp == "bad.py":
            raise RuntimeError("parse error")
        from datetime import datetime

        from mahavishnu.core.code_index.models import CodeGraphNode

        return (
            [
                CodeGraphNode(
                    symbol_id=f"test|||{_fp}|||function|||fn",
                    symbol_name="fn",
                    symbol_type="function",
                    file_path=_fp,
                    repo_path=str(tmp_path),
                    last_indexed_at=datetime.now(UTC),
                    commit_hash="sha2partial",
                )
            ],
            [],
        )

    monkeypatch.setattr(
        "mahavishnu.core.code_index.indexer.parse_file",
        mock_parse,
    )
    monkeypatch.setattr(
        "mahavishnu.core.code_index.indexer._upsert_to_session_buddy",
        lambda _repo, _nodes, _edges: True,
    )

    result = index_repo(str(tmp_path), trigger="manual", full=True)
    assert result.status == "complete"
    assert result.parse_failures == 1
