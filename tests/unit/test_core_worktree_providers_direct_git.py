"""Unit tests for mahavishnu/core/worktree_providers/direct_git.py.

Mocks asyncio.create_subprocess_exec so no real git commands are run.

NOTE: There are existing complementary tests in tests/unit/test_worktree_providers.py
that cover the happy paths. These tests focus on additional behavior such as
provider identity, health checks, and edge cases in the porcelain parser.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from mahavishnu.core.worktree_providers.base import WorktreeProvider
from mahavishnu.core.worktree_providers.direct_git import DirectGitWorktreeProvider
from mahavishnu.core.worktree_providers.errors import (
    WorktreeCreationError,
    WorktreeOperationError,
)

pytestmark = pytest.mark.unit


# ============================== Helpers ==============================


def _fake_process(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""):
    """Build a fake subprocess return value."""
    p = AsyncMock()
    p.communicate = AsyncMock(return_value=(stdout, stderr))
    p.returncode = returncode
    return p


# ============================== Init / identity ==============================


class TestInitAndIdentity:
    """Sanity checks on construction and identity."""

    def test_construction_sets_git_executable(self):
        p = DirectGitWorktreeProvider()
        assert p._git_executable == "git"

    def test_provider_name(self):
        # Static method
        assert DirectGitWorktreeProvider.provider_name() == "DirectGitWorktreeProvider"
        # Also accessible from instance
        assert DirectGitWorktreeProvider().provider_name() == "DirectGitWorktreeProvider"

    def test_inherits_from_base(self):
        assert isinstance(DirectGitWorktreeProvider(), WorktreeProvider)


# ============================== health_check ==============================


class TestHealthCheck:
    """Tests for synchronous health_check."""

    def test_health_check_true_when_git_present(self):
        p = DirectGitWorktreeProvider()
        with patch("shutil.which", return_value="/usr/bin/git"):
            assert p.health_check() is True

    def test_health_check_false_when_git_missing(self):
        p = DirectGitWorktreeProvider()
        with patch("shutil.which", return_value=None):
            assert p.health_check() is False

    def test_health_check_swallows_exceptions(self):
        p = DirectGitWorktreeProvider()
        with patch("shutil.which", side_effect=RuntimeError("nope")):
            assert p.health_check() is False


# ============================== create_worktree ==============================


class TestCreateWorktree:
    """Tests for create_worktree."""

    async def test_command_includes_repository_path(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process()
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ) as mock_exec:
            await p.create_worktree(Path("/myrepo"), "feat", Path("/wt/feat"), True)

        cmd = mock_exec.call_args[0]
        assert "git" in cmd
        assert "-C" in cmd
        assert "/myrepo" in cmd
        assert "feat" in cmd

    async def test_create_branch_flag_b(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process()
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ) as mock_exec:
            await p.create_worktree(Path("/r"), "newbranch", Path("/wt"), create_branch=True)

        cmd = mock_exec.call_args[0]
        # -b should be present but -B (uppercase) should NOT be present
        assert "-b" in cmd
        assert "-B" not in cmd

    async def test_existing_branch_uses_capital_B(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process()
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ) as mock_exec:
            await p.create_worktree(Path("/r"), "main", Path("/wt"), create_branch=False)

        cmd = mock_exec.call_args[0]
        assert "-B" in cmd

    async def test_success_returns_metadata(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process()
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            result = await p.create_worktree(Path("/r"), "br", Path("/wt"), create_branch=True)

        assert result["success"] is True
        assert result["branch"] == "br"
        assert result["worktree_path"] == "/wt"
        assert result["provider"] == "DirectGitWorktreeProvider"

    async def test_failure_raises_creation_error(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process(returncode=1, stderr=b"already exists")
        with (
            patch(
                "asyncio.create_subprocess_exec",
                AsyncMock(return_value=process),
            ),
            pytest.raises(WorktreeCreationError, match="Failed to create worktree"),
        ):
            await p.create_worktree(Path("/r"), "b", Path("/wt"), True)

    async def test_failure_with_empty_stderr(self):
        """Empty stderr should still raise with a generic message."""
        p = DirectGitWorktreeProvider()
        process = _fake_process(returncode=1, stderr=b"")
        with (
            patch(
                "asyncio.create_subprocess_exec",
                AsyncMock(return_value=process),
            ),
            pytest.raises(WorktreeCreationError),
        ):
            await p.create_worktree(Path("/r"), "b", Path("/wt"), True)


# ============================== remove_worktree ==============================


class TestRemoveWorktree:
    """Tests for remove_worktree."""

    async def test_success_returns_metadata(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process()
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            result = await p.remove_worktree(Path("/r"), Path("/wt"))

        assert result["success"] is True
        assert result["removed_path"] == "/wt"
        assert result["provider"] == "DirectGitWorktreeProvider"

    async def test_force_flag_added(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process()
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ) as mock_exec:
            await p.remove_worktree(Path("/r"), Path("/wt"), force=True)

        cmd = mock_exec.call_args[0]
        assert "--force" in cmd

    async def test_without_force_no_flag(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process()
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ) as mock_exec:
            await p.remove_worktree(Path("/r"), Path("/wt"), force=False)

        cmd = mock_exec.call_args[0]
        assert "--force" not in cmd

    async def test_failure_raises_operation_error(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process(returncode=1, stderr=b"locked")
        with (
            patch(
                "asyncio.create_subprocess_exec",
                AsyncMock(return_value=process),
            ),
            pytest.raises(WorktreeOperationError, match="Failed to remove worktree"),
        ):
            await p.remove_worktree(Path("/r"), Path("/wt"))


# ============================== list_worktrees ==============================


class TestListWorktrees:
    """Tests for list_worktrees and porcelain parsing."""

    async def test_empty_output_returns_empty_list(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process(stdout=b"")
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            result = await p.list_worktrees(Path("/r"))

        assert result["success"] is True
        assert result["worktrees"] == []

    async def test_parses_valid_porcelain_output(self):
        p = DirectGitWorktreeProvider()
        output = b"/repo/main main abc123 ok\n/repo/feat feature def456 dirty\n"
        process = _fake_process(stdout=output)
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            result = await p.list_worktrees(Path("/repo"))

        assert len(result["worktrees"]) == 2
        first = result["worktrees"][0]
        assert first["path"] == "/repo/main"
        assert first["branch"] == "main"
        assert first["commit"] == "abc123"
        assert first["status"] == "ok"

    async def test_skips_blank_lines(self):
        p = DirectGitWorktreeProvider()
        # blank line should be skipped
        output = b"/r/a branch1 commit1 ok\n\n/r/b branch2 commit2 ok\n"
        process = _fake_process(stdout=output)
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            result = await p.list_worktrees(Path("/r"))
        assert len(result["worktrees"]) == 2

    async def test_skips_lines_with_too_few_parts(self):
        p = DirectGitWorktreeProvider()
        # Lines with < 4 parts are silently ignored
        output = b"only_one\ntwo parts\nthree parts here\n/r/full path branch commit ok\n"
        process = _fake_process(stdout=output)
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            result = await p.list_worktrees(Path("/r"))
        # Only 1 valid worktree line (4 parts present)
        assert len(result["worktrees"]) == 1

    async def test_provider_name_in_result(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process(stdout=b"")
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            result = await p.list_worktrees(Path("/r"))
        assert result["provider"] == "DirectGitWorktreeProvider"

    async def test_failure_raises_operation_error(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process(returncode=1, stderr=b"not a git repo")
        with (
            patch(
                "asyncio.create_subprocess_exec",
                AsyncMock(return_value=process),
            ),
            pytest.raises(WorktreeOperationError, match="Failed to list worktrees"),
        ):
            await p.list_worktrees(Path("/r"))

    async def test_command_uses_porcelain_flag(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process(stdout=b"")
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ) as mock_exec:
            await p.list_worktrees(Path("/r"))

        cmd = mock_exec.call_args[0]
        assert "--porcelain" in cmd
        assert "worktree" in cmd
        assert "list" in cmd
