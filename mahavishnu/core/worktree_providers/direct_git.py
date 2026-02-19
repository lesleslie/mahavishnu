"""Direct Git worktree provider (fallback).

Uses subprocess git commands as a fallback when Session-Buddy is unavailable.
Always available (no external dependencies).
"""

import asyncio
import logging
from pathlib import Path
from typing import Any

from .base import WorktreeProvider
from .errors import WorktreeCreationError, WorktreeOperationError

logger = logging.getLogger(__name__)


class DirectGitWorktreeProvider(WorktreeProvider):
    """
    Worktree provider using subprocess git commands.

    Serves as a fallback provider when Session-Buddy is unavailable.
    Always available as long as git is installed.
    """

    def __init__(self) -> None:
        """Initialize DirectGit provider."""
        self._git_executable = "git"

    @staticmethod
    def provider_name() -> str:
        """Get provider name."""
        return "DirectGitWorktreeProvider"

    def health_check(self) -> bool:
        """Check if git is available."""
        try:
            process = asyncio.create_subprocess_exec(
                self._git_executable,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            # We can't use asyncio in health_check, so we'll just check if git exists
            import shutil

            return shutil.which(self._git_executable) is not None
        except Exception:
            return False

    async def create_worktree(
        self,
        repository_path: Path,
        branch: str,
        worktree_path: Path,
        create_branch: bool = False,
    ) -> dict[str, Any]:
        """
        Create a worktree using git worktree add command.

        Args:
            repository_path: Path to git repository
            branch: Branch name
            worktree_path: Path for new worktree
            create_branch: Whether to create new branch

        Returns:
            Creation result
        """
        cmd = [
            self._git_executable,
            "-C",
            str(repository_path),
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree_path),
        ]

        if not create_branch:
            # Use -B flag to not create new branch
            cmd[-2:-2] = ["-B"]

        logger.debug(f"Creating worktree: {' '.join(cmd)}")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise WorktreeCreationError(f"Failed to create worktree: {error_msg}")

            logger.info(f"Worktree created successfully: {worktree_path}")

            return {
                "success": True,
                "worktree_path": str(worktree_path),
                "branch": branch,
                "provider": self.provider_name(),
            }

        except Exception as e:
            logger.error(f"DirectGit create failed: {e}")
            raise

    async def remove_worktree(
        self,
        repository_path: Path,
        worktree_path: Path,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Remove a worktree using git worktree remove command.

        Args:
            repository_path: Path to git repository
            worktree_path: Path to worktree directory
            force: Force removal (use --force flag)

        Returns:
            Removal result
        """
        cmd = [
            self._git_executable,
            "-C",
            str(repository_path),
            "worktree",
            "remove",
        ]

        if force:
            cmd.append("--force")

        cmd.append(str(worktree_path))

        logger.debug(f"Removing worktree: {' '.join(cmd)}")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise WorktreeOperationError(f"Failed to remove worktree: {error_msg}")

            logger.info(f"Worktree removed successfully: {worktree_path}")

            return {
                "success": True,
                "removed_path": str(worktree_path),
                "provider": self.provider_name(),
            }

        except Exception as e:
            logger.error(f"DirectGit remove failed: {e}")
            raise

    async def list_worktrees(
        self,
        repository_path: Path,
    ) -> dict[str, Any]:
        """
        List worktrees using git worktree list command.

        Args:
            repository_path: Path to git repository

        Returns:
            List of worktrees with metadata
        """
        cmd = [
            self._git_executable,
            "-C",
            str(repository_path),
            "worktree",
            "list",
            "--porcelain",
        ]

        logger.debug(f"Listing worktrees: {' '.join(cmd)}")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise WorktreeOperationError(f"Failed to list worktrees: {error_msg}")

            # Parse porcelain output
            worktrees = []
            for line in stdout.decode().splitlines():
                if not line.strip():
                    continue

                parts = line.split()
                if len(parts) >= 4:
                    worktrees.append(
                        {
                            "path": parts[0],
                            "branch": parts[1],
                            "commit": parts[2],
                            "status": parts[3] if len(parts) > 3 else "ok",
                        }
                    )

            logger.info(f"Listed {len(worktrees)} worktrees")

            return {
                "success": True,
                "worktrees": worktrees,
                "provider": self.provider_name(),
            }

        except Exception as e:
            logger.error(f"DirectGit list failed: {e}")
            raise
