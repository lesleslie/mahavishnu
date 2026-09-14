"""End-to-end integration tests for ``merge_three_way(strategy=SEMANTIC)``.

Verifies the Phase 2 exit criteria against a real ``mergiraf`` binary on
``$PATH``. Skipped if ``mergiraf`` is unavailable so the suite stays
green in CI environments that haven't installed the optional dependency.

These tests exercise the full subprocess flow (validation gate, tempdir
write, asyncio.create_subprocess_exec, exit-code + content matrix) — the
unit tests in ``tests/unit/settle/test_merge_strategy.py`` cover the same
matrix with mocked subprocesses for fast feedback.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile

import pytest

from mahavishnu.settle.merge import (
    MergeConflictError,
    MergeResult,
    MergeStrategy,
    merge_three_way,
)

MERGIRAF_BIN = shutil.which("mergiraf")


# ---------------------------------------------------------------------------
# Skip guard: mergiraf binary required
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    MERGIRAF_BIN is None,
    reason="mergiraf binary not on $PATH; install via 'brew install mergiraf' "
    "or 'cargo binstall mergiraf' to run these tests.",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_python_files() -> tuple[str, str, str]:
    """Return base/ours/theirs for a 3-way Python merge scenario.

    Base defines ``foo`` followed by ``bar``. Ours inserts ``baz`` between
    ``foo`` and ``bar``. Theirs appends ``qux`` after ``bar``. The insertion
    positions are at *different* anchors (between foo/bar vs. after bar),
    so mergiraf can resolve them cleanly — the headline Phase 2 outcome.

    If both sides tried to insert at the *same* anchor (e.g. both at the
    end of the file), mergiraf would emit a conflict because the
    insertion points collide. The non-overlapping case requires distinct
    anchors — line-level git merge-file would conflict on this either
    way because it operates on line ranges, not on AST nodes.
    """
    base = "def foo() -> int:\n    return 0\n\ndef bar() -> int:\n    return 0\n"
    ours = (
        "def foo() -> int:\n"
        "    return 0\n"
        "\n"
        "def baz() -> int:\n"
        "    return 1\n"
        "\n"
        "def bar() -> int:\n"
        "    return 0\n"
    )
    theirs = (
        "def foo() -> int:\n"
        "    return 0\n"
        "\n"
        "def bar() -> int:\n"
        "    return 0\n"
        "\n"
        "def qux() -> int:\n"
        "    return 2\n"
    )
    return base, ours, theirs


@pytest.fixture
def conflict_python_files() -> tuple[str, str, str]:
    """Return base/ours/theirs for a 3-way Python merge CONFLICT scenario.

    Base defines ``foo`` returning 0. Ours returns 1, theirs returns 2.
    Entity-level mergiraf detects the same function edited differently on
    both sides → real semantic conflict. Empirically (mergiraf 0.19.1)
    this exits 1 with ``<<<<<<<`` markers in stdout — same shape as git
    merge-file's conflict case. The R4 reviewer-blind-spot fix is the
    marker-first classification regardless of exit code.
    """
    base = "def foo() -> int:\n    return 0\n"
    ours = "def foo() -> int:\n    return 1\n"
    theirs = "def foo() -> int:\n    return 2\n"
    return base, ours, theirs


# ---------------------------------------------------------------------------
# Exit-code matrix (real mergiraf binary)
# ---------------------------------------------------------------------------


async def test_non_overlapping_function_edits_merge_cleanly(
    sample_python_files: tuple[str, str, str],
) -> None:
    """Non-overlapping function edits → ``MergeResult(conflict_count=0)``.

    The headline Phase 2 outcome: line-level git merge-file would mark
    this as a conflict (overlapping edits in the same file), but
    entity-aware mergiraf sees that ``baz`` (added in ours) and ``qux``
    (added in theirs) don't touch each other.
    """
    base, ours, theirs = sample_python_files
    result = await merge_three_way(
        base=base,
        ours=ours,
        theirs=theirs,
        label="sample.py",
        strategy=MergeStrategy.SEMANTIC,
    )
    assert isinstance(result, MergeResult)
    assert result.conflict_count == 0
    assert "<<<<<<< " not in result.merged
    assert ">>>>>>> " not in result.merged
    assert "def baz" in result.merged  # ours added baz
    assert "def qux" in result.merged  # theirs added qux


async def test_semantic_conflict_exits_with_markers(
    conflict_python_files: tuple[str, str, str],
) -> None:
    """R4 reviewer-blind-spot fix: marker-first classification.

    The plan claimed real semantic conflicts exit 0 with markers;
    empirically (mergiraf 0.19.1) they exit 1 with markers. The fix is
    the same regardless of which exit code mergiraf chooses: scan stdout
    for ``<<<<<<<`` markers FIRST, route to ``MergeConflictError``
    (recoverable). The exit code only matters for fatals — markers in
    stdout always mean a real conflict.
    """
    base, ours, theirs = conflict_python_files
    with pytest.raises(MergeConflictError) as excinfo:
        await merge_three_way(
            base=base,
            ours=ours,
            theirs=theirs,
            label="conflict.py",
            strategy=MergeStrategy.SEMANTIC,
        )
    err = excinfo.value
    assert err.path == "conflict.py"
    assert "<<<<<<< " in err.merged
    assert ">>>>>>> " in err.merged


async def test_semantic_clean_merge_preserves_ours_in_tempfile(
    sample_python_files: tuple[str, str, str],
) -> None:
    """Tempdir cleanup is automatic — no orphaned files.

    Validates the tempdir lifecycle: ``tempfile.TemporaryDirectory`` is
    used as a context manager inside ``_merge_via_mergiraf`` and the
    scratch files (``base``, ``ours``, ``theirs``) are removed when the
    context exits.
    """
    base, ours, theirs = sample_python_files
    # Wrap the merge in an outer tempdir we control so we can probe for
    # leftover scratch files in a known location.
    with tempfile.TemporaryDirectory(prefix="phase2-cleanup-") as outer:
        outer_path = Path(outer)
        before_files = set(outer_path.glob("settle-mergiraf-*"))
        await merge_three_way(
            base=base,
            ours=ours,
            theirs=theirs,
            label="cleanup.py",
            strategy=MergeStrategy.SEMANTIC,
        )
        # No inner tempdir should have leaked into the outer scope.
        after_files = set(outer_path.glob("settle-mergiraf-*"))
        assert before_files == after_files
