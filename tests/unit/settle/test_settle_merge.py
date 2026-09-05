"""Tests for ``mahavishnu.settle.merge`` — the 3-way merge shim around ``git merge-file``.

Covers the async ``merge_three_way`` and the sync ``merge_three_way_sync``
helpers plus the structured error classes they raise.  ``git merge-file`` is
mocked at the ``create_subprocess_exec`` / ``subprocess.run`` boundary so the
suite never needs a real ``git`` binary.
"""

from __future__ import annotations

import asyncio
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.settle.merge import (
    MergeConflictError,
    MergeFailureError,
    MergeResult,
    merge_three_way,
    merge_three_way_sync,
)


def _make_process_mock(returncode: int, stdout: str, stderr: str = "") -> AsyncMock:
    """Build an ``AsyncMock`` that quacks like ``asyncio.subprocess.Process``.

    The async ``merge_three_way`` helper awaits ``proc.communicate()`` and
    then reads ``proc.returncode``; we wire both to fixed values so the
    function under test can branch deterministically on the exit code.
    """
    proc = AsyncMock(spec=asyncio.subprocess.Process)
    proc.communicate = AsyncMock(return_value=(stdout.encode("utf-8"), stderr.encode("utf-8")))
    proc.returncode = returncode
    return proc


def _make_completed_proc(returncode: int, stdout: str, stderr: str = "") -> MagicMock:
    """Build a ``MagicMock`` that quacks like ``subprocess.CompletedProcess``."""
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = returncode
    completed.stdout = stdout
    completed.stderr = stderr
    return completed


# ---------------------------------------------------------------------------
# Async merge_three_way
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "base,ours,theirs,merged_text",
    [
        ("one\n", "one\n", "one\n", "one\n"),
        ("", "", "", ""),
        ("a\nb\nc\n", "a\nb\nc\n", "a\nb\nc\n", "a\nb\nc\n"),
    ],
)
async def test_merge_three_way_clean_merge_returns_result(
    base: str,
    ours: str,
    theirs: str,
    merged_text: str,
) -> None:
    proc = _make_process_mock(returncode=0, stdout=merged_text)
    with patch(
        "asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ):
        result = await merge_three_way(base=base, ours=ours, theirs=theirs)
    assert isinstance(result, MergeResult)
    assert result.merged == merged_text
    assert result.conflict_count == 0


async def test_merge_three_way_conflict_raises_with_markers() -> None:
    merged_with_markers = (
        "<<<<<<< ours\n"
        "ours-line\n"
        "=======\n"
        "theirs-line\n"
        ">>>>>>> theirs\n"
    )
    proc = _make_process_mock(returncode=1, stdout=merged_with_markers)
    with patch(
        "asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ):
        with pytest.raises(MergeConflictError) as excinfo:
            await merge_three_way(
                base="common\n",
                ours="ours-line\n",
                theirs="theirs-line\n",
                label="binding-A.py",
            )
    err = excinfo.value
    assert err.path == "binding-A.py"
    assert err.merged == merged_with_markers
    assert err.base == "common\n"
    assert err.ours == "ours-line\n"
    assert err.theirs == "theirs-line\n"
    assert "<<<<<<< " in err.merged
    assert str(err) == "3-way merge conflict for 'binding-A.py'"


async def test_merge_three_way_conflict_counts_multiple_hunks() -> None:
    # Two distinct conflict regions: two leading conflict markers.
    merged_with_markers = (
        "<<<<<<< ours\nA\n=======\nA'\n>>>>>>> theirs\n"
        "shared\n"
        "<<<<<<< ours\nB\n=======\nB'\n>>>>>>> theirs\n"
    )
    proc = _make_process_mock(returncode=1, stdout=merged_with_markers)
    with patch(
        "asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ):
        with pytest.raises(MergeConflictError) as excinfo:
            await merge_three_way(base="A\nB\n", ours="A\nB\n", theirs="A\nB\n")
    assert "<<<<<<< " in excinfo.value.merged


@pytest.mark.parametrize("returncode", [2, 3, 127])
async def test_merge_three_way_fatal_exit_raises_failure(returncode: int) -> None:
    proc = _make_process_mock(
        returncode=returncode,
        stdout="",
        stderr="fatal: bad invocation\n",
    )
    with patch(
        "asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ):
        with pytest.raises(MergeFailureError) as excinfo:
            await merge_three_way(
                base="x",
                ours="y",
                theirs="z",
                label="binding-X",
            )
    assert f"exit={returncode}" in str(excinfo.value)
    assert "binding-X" in str(excinfo.value)


async def test_merge_three_way_passes_label_and_git_binary() -> None:
    proc = _make_process_mock(returncode=0, stdout="ok\n")
    create_mock = AsyncMock(return_value=proc)
    with patch("asyncio.create_subprocess_exec", create_mock):
        await merge_three_way(
            base="x",
            ours="y",
            theirs="z",
            label="custom-label",
            git_merge_file="/opt/custom/git",
        )
    # First positional arg should be the overridden git binary.
    args, kwargs = create_mock.call_args
    assert args[0] == "/opt/custom/git"
    assert args[1] == "merge-file"
    assert kwargs.get("stdout") is asyncio.subprocess.PIPE


async def test_merge_three_way_empty_inputs_clean() -> None:
    proc = _make_process_mock(returncode=0, stdout="")
    with patch(
        "asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ):
        result = await merge_three_way(base="", ours="", theirs="")
    assert result.merged == ""
    assert result.conflict_count == 0


# ---------------------------------------------------------------------------
# Sync merge_three_way_sync
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "merged_text",
    [
        "one\ntwo\n",
        "",
        "alpha\nbeta\ngamma\n",
    ],
)
def test_merge_three_way_sync_clean_merge(merged_text: str) -> None:
    completed = _make_completed_proc(returncode=0, stdout=merged_text)
    with patch("subprocess.run", return_value=completed):
        result = merge_three_way_sync(base="b", ours="o", theirs="t")
    assert isinstance(result, MergeResult)
    assert result.merged == merged_text
    assert result.conflict_count == 0


def test_merge_three_way_sync_conflict_raises() -> None:
    merged_with_markers = "<<<<<<< ours\nA\n=======\nB\n>>>>>>> theirs\n"
    completed = _make_completed_proc(returncode=1, stdout=merged_with_markers)
    with patch("subprocess.run", return_value=completed):
        with pytest.raises(MergeConflictError) as excinfo:
            merge_three_way_sync(
                base="orig\n",
                ours="A\n",
                theirs="B\n",
                label="sync-binding",
            )
    err = excinfo.value
    assert err.path == "sync-binding"
    assert err.merged == merged_with_markers
    assert "<<<<<<< " in err.merged


@pytest.mark.parametrize("returncode", [2, 5, 42])
def test_merge_three_way_sync_fatal_exit(returncode: int) -> None:
    completed = _make_completed_proc(
        returncode=returncode,
        stdout="",
        stderr="boom\n",
    )
    with patch("subprocess.run", return_value=completed):
        with pytest.raises(MergeFailureError) as excinfo:
            merge_three_way_sync(
                base="x",
                ours="y",
                theirs="z",
                label="sync-fatal",
            )
    assert f"exit={returncode}" in str(excinfo.value)
    assert "sync-fatal" in str(excinfo.value)


def test_merge_three_way_sync_uses_overridden_git_binary() -> None:
    completed = _make_completed_proc(returncode=0, stdout="ok\n")
    run_mock = MagicMock(return_value=completed)
    with patch("subprocess.run", run_mock):
        merge_three_way_sync(
            base="x",
            ours="y",
            theirs="z",
            git_merge_file="/usr/local/bin/git-merge-tool",
        )
    cmd = run_mock.call_args.args[0]
    assert cmd[0] == "/usr/local/bin/git-merge-tool"
    assert "merge-file" in cmd
    assert run_mock.call_args.kwargs.get("check") is False


# ---------------------------------------------------------------------------
# Dataclass / exception class shape
# ---------------------------------------------------------------------------


def test_merge_result_is_frozen() -> None:
    result = MergeResult(merged="x", conflict_count=0)
    with pytest.raises((AttributeError, TypeError)):
        result.merged = "y"  # type: ignore[misc]


def test_merge_conflict_error_carries_all_payload() -> None:
    err = MergeConflictError(
        path="p",
        merged="m",
        base="b",
        ours="o",
        theirs="t",
    )
    assert err.path == "p"
    assert err.merged == "m"
    assert err.base == "b"
    assert err.ours == "o"
    assert err.theirs == "t"
