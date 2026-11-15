"""Tests for the merge pipeline's stash handling.

The stash stack is shared by every worktree and every session in the
repo, so the entry the pipeline creates has to be restored by identity.
These tests use real git repositories because the behaviour under test
is git's own: which entry a positional ``stash@{n}`` addresses, and
which entry ``git stash pop`` actually pops.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from mahavishnu.core.merge_to_main import (
    _find_stash_entry,
    _pop_stash_safely,
    run_squash_merge,
)

if TYPE_CHECKING:
    from pathlib import Path

OURS = "merge-to-main auto-stash: feat/x -> main (2026-11-15T00:00:00+00:00)"
THEIRS = "some-other-session: work in progress"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with one commit, so it has a stash-able baseline."""
    _git(tmp_path, "init", "-q", ".")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "tracked.txt").write_text("base\n")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def _stash(repo: Path, message: str, content: str) -> None:
    (repo / "tracked.txt").write_text(content)
    _git(repo, "stash", "push", "-m", message)


class TestFindStashEntry:
    def test_finds_the_entry_carrying_its_message(self, repo: Path) -> None:
        _stash(repo, OURS, "ours\n")
        _stash(repo, THEIRS, "theirs\n")

        entry = _find_stash_entry(repo, OURS)

        assert entry is not None
        sha, ref = entry
        assert len(sha) == 40
        assert ref.startswith("stash@{")

    def test_returns_none_when_no_entry_matches(self, repo: Path) -> None:
        _stash(repo, THEIRS, "theirs\n")

        assert _find_stash_entry(repo, OURS) is None

    def test_returns_none_in_a_repo_with_no_stashes(self, repo: Path) -> None:
        assert _find_stash_entry(repo, OURS) is None


class TestPopStashSafely:
    def test_restores_its_own_entry_not_the_top_of_the_stack(self, repo: Path) -> None:
        """The regression: ours is buried, another session's is on top.

        A bare ``git stash pop`` pops the top entry — which is the other
        session's — landing their work in the main checkout and leaving
        ours buried. The pipeline's entry has to be restored by
        identity.
        """
        _stash(repo, OURS, "ours\n")
        _stash(repo, THEIRS, "theirs\n")

        _pop_stash_safely(repo, OURS)

        # Our content came back ...
        assert (repo / "tracked.txt").read_text() == "ours\n"
        # ... and the other session's entry is still theirs, untouched.
        remaining = _git(repo, "stash", "list", "--format=%gs")
        assert THEIRS in remaining
        assert OURS not in remaining

    def test_leaves_the_stack_alone_when_no_entry_matches(self, repo: Path) -> None:
        _stash(repo, THEIRS, "theirs\n")

        _pop_stash_safely(repo, OURS)

        remaining = _git(repo, "stash", "list", "--format=%gs")
        assert THEIRS in remaining
        # Nothing was applied either: the working tree is clean.
        assert _git(repo, "status", "--porcelain").strip() == ""

    def test_keeps_the_entry_when_the_apply_conflicts(self, repo: Path) -> None:
        """A conflicting apply leaves the entry in the stack.

        Losing the entry would lose the user's pre-merge work, which is
        exactly what the stash exists to preserve.
        """
        _stash(repo, OURS, "ours\n")
        # Change the file on disk so the apply conflicts.
        (repo / "tracked.txt").write_text("conflicting\n")
        _git(repo, "add", "tracked.txt")
        _git(repo, "commit", "-qm", "conflicting")

        _pop_stash_safely(repo, OURS)

        remaining = _git(repo, "stash", "list", "--format=%gs")
        assert OURS in remaining

    def test_restores_the_entry_when_it_is_the_only_one(self, repo: Path) -> None:
        _stash(repo, OURS, "ours\n")

        _pop_stash_safely(repo, OURS)

        assert (repo / "tracked.txt").read_text() == "ours\n"
        assert _git(repo, "stash", "list", "--format=%gs").strip() == ""


@pytest.fixture
def repo_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """A main checkout plus a second worktree on a feature branch.

    The squash-merge lands on ``main`` in the *main* checkout, and it
    finds that checkout through ``git worktree list`` — so the test
    needs the same shape the pipeline sees in production: two
    worktrees of one repository, one of them on ``main``.
    """
    main_repo = tmp_path / "main"
    main_repo.mkdir()
    _git(main_repo, "init", "-q", "-b", "main", ".")
    _git(main_repo, "config", "user.email", "test@example.com")
    _git(main_repo, "config", "user.name", "Test")
    (main_repo / "tracked.txt").write_text("base\n")
    _git(main_repo, "add", "tracked.txt")
    _git(main_repo, "commit", "-qm", "base")

    worktree = tmp_path / "feature"
    _git(main_repo, "worktree", "add", "-b", "feat/x", str(worktree), "main")
    (worktree / "tracked.txt").write_text("feature\n")
    _git(worktree, "commit", "-aqm", "feature change")
    return main_repo, worktree


class TestTheStashIsOnlyRecordedWhenOneWasCreated:
    """A dirty tree can go clean before the stash runs.

    ``git stash push`` exits 0 when it had nothing to save -- it
    prints "No local changes to save" and creates no entry. The exit
    code alone does not say an entry exists, and a dirty tree can be
    unstaged away by another session between the status check and the
    push. Recording a stash that was never created is what made the
    restore step pop whatever happened to be on top of the shared
    stack -- another session's work.
    """

    def test_a_stash_that_was_never_created_leaves_the_stack_alone(
        self,
        repo_with_worktree: tuple[Path, Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        main_repo, worktree = repo_with_worktree

        # Another session's entry is on the shared stack. The
        # pipeline's restore step must not touch it.
        (main_repo / "tracked.txt").write_text("theirs\n")
        _git(main_repo, "stash", "push", "-m", THEIRS)

        # The pipeline's own dirty state: an untracked file that goes
        # away before the stash runs.
        scratch = main_repo / "scratch.txt"
        scratch.write_text("wip\n")

        # A git wrapper that removes the file when the stash runs, so
        # the stash has nothing to save. The status check that
        # precedes it still sees the file.
        real_git = shutil.which("git")
        assert real_git is not None
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        wrapper = bin_dir / "git"
        wrapper.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "stash" ] && [ "$2" = "push" ]; then\n'
            f'  rm -f "{scratch}"\n'
            "fi\n"
            f'exec "{real_git}" "$@"\n'
        )
        wrapper.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

        rc, stderr = run_squash_merge(worktree, "main", "feat/x")

        assert rc == 0, stderr

        # The stack is untouched: the other session's entry is still
        # there, and the pipeline did not claim to have captured one.
        remaining = _git(main_repo, "stash", "list", "--format=%gs")
        assert THEIRS in remaining
        assert len(remaining.splitlines()) == 1

        # The pipeline says nothing was captured. Without the check on
        # git's own "No local changes to save" output, the pipeline
        # records a stash entry that does not exist and goes looking
        # for it on the shared stack.
        reported = capsys.readouterr().err
        assert "nothing captured" in reported
        assert "captured main_checkout dirty tree" not in reported
