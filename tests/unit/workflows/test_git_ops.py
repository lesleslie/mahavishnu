"""Unit tests for _git_ops.py — git subprocess wrapper.

Implements: REQ-CLONE-011, REQ-CLONE-013
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mahavishnu.workflows._git_ops import (
    GitApplyConflict,
    GitCommandTimeout,
    GitCommitFailed,
    GitCommitPermanent,
    GitCommitTransient,
    StashPopFailed,
    current_head_sha,
    diff_files,
    git_apply,
    git_commit,
    is_working_tree_clean,
    stash_pop,
    stash_push,
)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Initialize a git repo at tmp_path with user.email/name configured."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test"],
        check=True, capture_output=True,
    )
    return tmp_path


class TestGitApply:
    async def test_git_apply_clean(self, git_repo: Path) -> None:
        # Setup: create initial file, commit
        (git_repo / "foo.py").write_text("x = 1\n")
        subprocess.run(["git", "-C", str(git_repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(git_repo), "commit", "-m", "init"], check=True)

        diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
        await git_apply(git_repo, diff)
        assert (git_repo / "foo.py").read_text() == "x = 2\n"

    async def test_git_apply_conflict_raises_structured(self, git_repo: Path) -> None:
        # Initial commit has DIFFERENT content from what the diff expects,
        # so the hunk actually conflicts.
        (git_repo / "foo.py").write_text("y = 99\n")
        subprocess.run(["git", "-C", str(git_repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(git_repo), "commit", "-m", "init"], check=True)

        # Diff that conflicts with the existing file (-x = 1 doesn't match y = 99)
        bad_diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x = 1\n+x = 999\n"
        with pytest.raises(GitApplyConflict) as exc_info:
            await git_apply(git_repo, bad_diff)
        assert isinstance(exc_info.value.diff_offset, int)
        assert exc_info.value.conflict_marker  # non-empty

    async def test_git_apply_via_stdin_not_argv(self, git_repo: Path, monkeypatch) -> None:
        # Verify diff is passed via stdin, not argv (REQ security note in spec §6.2)
        import asyncio

        (git_repo / "foo.py").write_text("x = 1\n")
        subprocess.run(["git", "-C", str(git_repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(git_repo), "commit", "-m", "init"], check=True)

        diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
        # If diff was in argv, a malicious diff containing "rm -rf /" would be
        # passed as a literal arg. We verify by checking the subprocess was
        # called with the diff via stdin (mock subprocess).
        captured_stdin: list[str] = []
        captured_args: list[tuple] = []

        async def fake_subprocess_exec(*args, stdin=None, **kwargs):
            captured_args.append(args)

            class FakeProc:
                returncode = 0

                async def communicate(self, input=None):
                    # Capture stdin data passed via input= kwarg
                    if input is not None:
                        captured_stdin.append(
                            input.decode() if isinstance(input, bytes) else input
                        )
                    return b"", b""

                async def wait(self):
                    return 0

            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess_exec)
        await git_apply(git_repo, diff)
        assert captured_stdin, "git_apply must call proc.communicate(input=...)"
        assert diff in captured_stdin[0], (
            f"diff must be passed via stdin; got: {captured_stdin[0][:80]!r}"
        )
        # Critical: diff must NOT appear in argv
        for arg_tuple in captured_args:
            assert diff not in str(arg_tuple), (
                f"diff must not appear in argv; got: {arg_tuple!r}"
            )


class TestGitCommit:
    async def test_git_commit_returns_sha(self, git_repo: Path) -> None:
        (git_repo / "foo.py").write_text("x = 1\n")
        subprocess.run(["git", "-C", str(git_repo), "add", "."], check=True)
        sha = await git_commit(git_repo, "test commit")
        assert len(sha) == 40
        assert all(c in "0123456789abcdef" for c in sha)

    async def test_git_commit_transient_index_lock(self, git_repo: Path, monkeypatch) -> None:
        # Simulate the exact stderr pattern that triggers Transient
        from unittest.mock import AsyncMock
        import asyncio

        async def fake_subprocess_exec(*args, stdin=None, **kwargs):
            class FakeProc:
                returncode = 1

                async def communicate(self, input=None):
                    return b"", b"fatal: Unable to create .git/index.lock: File exists.\n"

                async def wait(self):
                    return 1

            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess_exec)
        with pytest.raises(GitCommitTransient) as exc_info:
            await git_commit(git_repo, "x")
        assert "index.lock" in exc_info.value.reason

    async def test_git_commit_permanent_default(self, git_repo: Path, monkeypatch) -> None:
        import asyncio

        async def fake_subprocess_exec(*args, stdin=None, **kwargs):
            class FakeProc:
                returncode = 128

                async def communicate(self, input=None):
                    return b"", b"fatal: cannot commit without user.email\n"

                async def wait(self):
                    return 128

            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess_exec)
        with pytest.raises(GitCommitPermanent) as exc_info:
            await git_commit(git_repo, "x")
        assert exc_info.value.exit_code == 128

    async def test_git_commit_with_precommit_fail_is_permanent(
        self, git_repo: Path, monkeypatch
    ) -> None:
        # Pre-commit hook failure must NOT retry (REQ-CLONE-013)
        import asyncio

        async def fake_subprocess_exec(*args, stdin=None, **kwargs):
            class FakeProc:
                returncode = 1

                async def communicate(self, input=None):
                    return (
                        b"",
                        b"husky > pre-commit hook failed (add --no-verify to bypass)\n",
                    )

                async def wait(self):
                    return 1

            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess_exec)
        with pytest.raises(GitCommitPermanent):
            await git_commit(git_repo, "x")


class TestCurrentHeadSha:
    async def test_returns_latest_sha(self, git_repo: Path) -> None:
        (git_repo / "a").write_text("1")
        subprocess.run(["git", "-C", str(git_repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(git_repo), "commit", "-m", "first"], check=True)
        first_sha = await current_head_sha(git_repo)

        (git_repo / "b").write_text("2")
        subprocess.run(["git", "-C", str(git_repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(git_repo), "commit", "-m", "second"], check=True)
        second_sha = await current_head_sha(git_repo)

        assert first_sha != second_sha
        assert len(second_sha) == 40


class TestStashWrap:
    async def test_stash_push_pop_roundtrip(self, git_repo: Path) -> None:
        (git_repo / "foo.py").write_text("original\n")
        subprocess.run(["git", "-C", str(git_repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(git_repo), "commit", "-m", "init"], check=True)

        # Make dirty changes
        (git_repo / "foo.py").write_text("dirty WIP\n")
        assert not await is_working_tree_clean(git_repo)

        # Stash + pop restores
        stash_ref = await stash_push(git_repo)
        assert await is_working_tree_clean(git_repo)
        await stash_pop(git_repo, stash_ref)
        assert (git_repo / "foo.py").read_text() == "dirty WIP\n"

    async def test_stash_push_uses_plain_stash_not_keep_index(
        self, git_repo: Path, monkeypatch
    ) -> None:
        # REQ-CLONE-011: plain `git stash`, NOT `git stash --keep-index`.
        # Verify by inspecting the args passed to subprocess.
        import asyncio

        captured_args: list[tuple] = []

        async def fake_subprocess_exec(*args, **kwargs):
            captured_args.append(args)

            class FakeProc:
                returncode = 0

                async def communicate(self, input=None):
                    return b"Saved working directory and index state WIP on main: abc\n", b""

                async def wait(self):
                    return 0

            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess_exec)
        await stash_push(git_repo)
        # Find the stash call
        stash_calls = [a for a in captured_args if "stash" in a and isinstance(a, tuple)]
        assert any("--keep-index" not in a for a in stash_calls), (
            f"stash_push must NOT use --keep-index; got args: {captured_args}"
        )


class TestErrorPaths:
    """Critical exception paths that Task 5 (DAG rewrite) relies on.

    These tests cover the three Important test-coverage gaps flagged by the
    Task 4 reviewer:
    - SF-B5: timeout classification (GitCommandTimeout → Transient)
    - SF-B4: stash pop failure must raise (was previously swallowed)
    - SF-m5: negative exit code = signal-killed → Permanent with signal_N reason
    """

    async def test_timeout_raises_git_command_timeout(
        self, git_repo: Path, monkeypatch
    ) -> None:
        """SF-B5: subprocess timeout raises GitCommandTimeout (Transient subclass).

        Verifies (1) GitCommandTimeout is raised, (2) it is a GitCommitTransient
        so Prefect retries, (3) the timed-out subprocess was killed (proc.kill()
        was called) so we don't leak half-completed git processes.
        """
        import asyncio

        proc_killed = False

        async def fake_subprocess_exec(*args, stdin=None, **kwargs):
            nonlocal proc_killed

            class FakeProc:
                returncode = -1

                async def communicate(self, input=None):
                    # asyncio.wait_for raises TimeoutError when the inner
                    # coroutine raises it OR when the deadline expires;
                    # both paths land in the same `except` branch. In
                    # Python 3.11+ asyncio.TimeoutError is an alias for
                    # the builtin TimeoutError; use the builtin directly.
                    raise TimeoutError()

                async def wait(self):
                    return -9

                def kill(self):
                    nonlocal proc_killed
                    proc_killed = True

            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess_exec)
        diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
        with pytest.raises(GitCommandTimeout) as exc_info:
            await git_apply(git_repo, diff)
        # SF-B5: GitCommandTimeout is a Transient subclass so Prefect retries.
        assert isinstance(exc_info.value, GitCommitTransient)
        assert exc_info.value.reason == "timeout"
        # SF-B5: proc.kill() must terminate the timed-out subprocess.
        assert proc_killed, "proc.kill() must be called on timeout (SF-B5)"

    async def test_stash_pop_failure_raises_stash_pop_failed(
        self, git_repo: Path, monkeypatch
    ) -> None:
        """SF-B4: stash pop failure must raise StashPopFailed (not silently swallow).

        The previous implementation used check=False and swallowed non-zero
        exits, leaving the working tree dirty. This regression test pins the
        raise behavior so Task 5's DAG can record typed errors on the
        RepoCommit.
        """
        import asyncio

        async def fake_subprocess_exec(*args, stdin=None, **kwargs):
            # First 3 args are always ("git", "-C", str(repo_path)); args[3:]
            # is the actual git subcommand. We succeed for everything except
            # `stash pop`, which we make fail with a realistic untracked-file
            # conflict.
            extra = args[3:] if len(args) > 3 else ()
            is_stash_pop = "stash" in extra and "pop" in extra

            class FakeProc:
                returncode = 1 if is_stash_pop else 0
                _stderr = (
                    b"error: could not restore untracked files from stash\n"
                    if is_stash_pop
                    else b""
                )

                async def communicate(self, input=None):
                    return b"", self._stderr

                async def wait(self):
                    return self.returncode

            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess_exec)
        # stash_push is fully mocked to succeed (returncode=0, check=True).
        await stash_push(git_repo)
        with pytest.raises(StashPopFailed) as exc_info:
            await stash_pop(git_repo)
        assert exc_info.value.exit_code == 1
        assert "untracked" in exc_info.value.stderr

    async def test_negative_exit_code_raises_git_commit_permanent(
        self, git_repo: Path, monkeypatch
    ) -> None:
        """SF-m5: negative exit code (signal-killed) → GitCommitPermanent signal_N.

        Operators need to distinguish a process that died from SIGKILL/SIGTERM
        (signal_-9 / signal_-15, transient resource pressure) from a process
        that exited with a git-level error (config, hook, etc.). The
        `reason=f"signal_{-exit_code}"` encoding lets the DAG surface this.
        """
        import asyncio

        async def fake_subprocess_exec(*args, stdin=None, **kwargs):
            class FakeProc:
                returncode = -9  # SIGKILL

                async def communicate(self, input=None):
                    return b"", b"Killed: 9\n"

                async def wait(self):
                    return -9

            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess_exec)
        with pytest.raises(GitCommitPermanent) as exc_info:
            await git_commit(git_repo, "x")
        assert exc_info.value.exit_code == -9
        assert exc_info.value.reason == "signal_9"
        # signal-killed commits should NOT be classified as Transient
        assert not isinstance(exc_info.value, GitCommitTransient)
