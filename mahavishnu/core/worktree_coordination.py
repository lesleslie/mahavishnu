"""
Worktree coordination module for Mahavishnu.

Delegates to WorktreeProvider instances for actual worktree operations
while adding Mahavishnu-specific safety checks, dependency validation, and
cross-repository coordination.

Architecture (Phase 0 enhancements):
- Provider registry with automatic fallback (SessionBuddy → DirectGit)
- Path validation layer (defense in depth)
- Enhanced force flag safeguards (--force-reason required)
- Comprehensive audit logging (all operations)
"""

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mahavishnu.core.repo_manager import RepositoryManager
from mahavishnu.core.coordination.manager import CoordinationManager
from mahavishnu.core.errors import ConfigurationError

from .worktree_providers.base import WorktreeProvider
from .worktree_providers.registry import WorktreeProviderRegistry
from .worktree_providers.session_buddy import SessionBuddyWorktreeProvider
from .worktree_providers.direct_git import DirectGitWorktreeProvider
from .worktree_validation import WorktreePathValidator
from .worktree_audit import WorktreeAuditLogger
from .worktree_backup import WorktreeBackupManager

logger = logging.getLogger(__name__)


class WorktreeCoordinator:
    """
    Coordinate worktrees across multiple repositories with safety mechanisms.

    This class uses WorktreeProvider instances and adds:
    - Pre-deletion validation (dependency checks, repo validation)
    - Cross-repository worktree tracking
    - Integration with CoordinationManager for issue tracking
    - Comprehensive audit logging for all operations
    - Provider abstraction with automatic fallback

    Architecture (post-Phase 0):
    ┌─────────────────────────────────────────────────────┐
    │  WorktreeCoordinator                                 │
    │  - Mahavishnu-level safety checks                    │
    │  - Path validation (WorktreePathValidator)           │
    │  - Audit logging (WorktreeAuditLogger)               │
    │  - Dependency checking                               │
    └─────────────────────────────────────────────────────┘
                          │
                          ▼
    ┌─────────────────────────────────────────────────────┐
    │  WorktreeProviderRegistry                          │
    │  - Primary: SessionBuddyWorktreeProvider            │
    │  - Fallback: DirectGitWorktreeProvider              │
    │  - Automatic health checking                         │
    └─────────────────────────────────────────────────────┘
    """

    def __init__(
        self,
        repo_manager: RepositoryManager,
        coordination_manager: CoordinationManager,
        providers: list[WorktreeProvider] | None = None,
        backup_dir: Path | None = None,
        allowed_worktree_roots: list[Path] | None = None,
    ) -> None:
        """
        Initialize worktree coordinator.

        Args:
            repo_manager: Repository metadata manager
            coordination_manager: Cross-repo dependency tracker
            providers: Ordered list of providers (primary first)
            backup_dir: Directory for worktree backups (XDG-compliant)
            allowed_worktree_roots: Allowed root directories for worktrees
        """
        self.repo_manager = repo_manager
        self.coordination_manager = coordination_manager

        # Initialize provider registry with fallback chain
        if providers is None:
            providers = [
                SessionBuddyWorktreeProvider(),  # Primary
                DirectGitWorktreeProvider(),      # Fallback
            ]

        self.provider_registry = WorktreeProviderRegistry(providers)

        # Path validator (security - defense in depth)
        if allowed_worktree_roots is None:
            allowed_worktree_roots = [
                Path.home() / "worktrees",
                Path.cwd(),
            ]

        self.path_validator = WorktreePathValidator(
            allowed_roots=allowed_worktree_roots,
            strict_mode=True,
        )

        # Backup manager (for force removal safety)
        self.backup_manager = WorktreeBackupManager(backup_dir=backup_dir)

        # Audit logger
        self.audit_logger = WorktreeAuditLogger()

        logger.info(
            f"WorktreeCoordinator initialized with {len(providers)} providers "
            f"(primary: {providers[0].__class__.__name__})"
        )

    async def create_worktree(
        self,
        repo_nickname: str,
        branch: str,
        worktree_name: str | None = None,
        create_branch: bool = False,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a worktree with safety checks.

        Args:
            repo_nickname: Repository nickname
            branch: Branch name
            worktree_name: Optional custom worktree name
            create_branch: Whether to create new branch
            user_id: User ID for audit logging

        Returns:
            Creation result with worktree info
        """
        # Validate repository exists
        repo = self.repo_manager.get_by_name(repo_nickname)
        if not repo:
            # Try by package name as fallback
            repo = self.repo_manager.get_by_package(repo_nickname)
        if not repo:
            raise ConfigurationError(f"Repository not found: {repo_nickname}")

        # Check dependencies
        blocking_deps = self.coordination_manager.get_blocking_dependencies(
            repo_nickname
        )
        if blocking_deps:
            logger.warning(
                f"Repo {repo_nickname} has {len(blocking_deps)} blocking dependencies",
                dependencies=blocking_deps,
            )

        # Generate safe worktree path
        if worktree_name:
            # Use custom worktree name
            worktree_path = self.path_validator.get_safe_worktree_path(
                repo_nickname, worktree_name
            )
        else:
            # Generate from branch name
            worktree_path = self.path_validator.get_safe_worktree_path(
                repo_nickname, branch
            )

        # Validate worktree path (SECURITY-002: defense in depth)
        is_valid, error = self.path_validator.validate_worktree_path(
            str(worktree_path), user_id
        )
        if not is_valid:
            self.audit_logger.log_security_rejection(
                user_id=user_id,
                operation="create_worktree",
                rejection_reason=error,
                params={
                    "repo_nickname": repo_nickname,
                    "branch": branch,
                    "worktree_path": str(worktree_path),
                },
            )
            raise ValueError(f"Invalid worktree path: {error}")

        # Log creation attempt (SECURITY-003: audit logging)
        self.audit_logger.log_creation_attempt(
            user_id=user_id,
            repo_nickname=repo_nickname,
            branch=branch,
            worktree_path=str(worktree_path),
            create_branch=create_branch,
        )

        try:
            # Get available provider (with automatic fallback)
            provider = await self.provider_registry.get_available_provider()

            # Delegate to provider
            result = await provider.create_worktree(
                repository_path=Path(repo.path),
                branch=branch,
                worktree_path=worktree_path,
                create_branch=create_branch,
            )

            # Log success
            self.audit_logger.log_creation_success(
                user_id=user_id,
                repo_nickname=repo_nickname,
                branch=branch,
                worktree_path=str(worktree_path),
            )

            logger.info(f"Worktree created successfully: {worktree_path}")
            return result

        except Exception as e:
            # Log failure
            self.audit_logger.log_creation_failure(
                user_id=user_id,
                repo_nickname=repo_nickname,
                branch=branch,
                worktree_path=str(worktree_path),
                error=str(e),
            )
            logger.error(f"Failed to create worktree: {e}", exc_info=True)
            raise

    async def remove_worktree(
        self,
        repo_nickname: str,
        worktree_path: str,
        force: bool = False,
        force_reason: str | None = None,  # SECURITY-001: required for force
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Remove a worktree with comprehensive safety checks.

        Args:
            repo_nickname: Repository nickname
            worktree_path: Path to worktree
            force: Force removal (skip safety checks)
            force_reason: REQUIRED when force=True with uncommitted changes
            user_id: User ID for authorization

        Returns:
            Removal result
        """
        # Validate repository exists
        repo = self.repo_manager.get_by_name(repo_nickname)
        if not repo:
            # Try by package name as fallback
            repo = self.repo_manager.get_by_package(repo_nickname)
        if not repo:
            raise ConfigurationError(f"Repository not found: {repo_nickname}")

        # Validate worktree path BEFORE any operations (SECURITY-002)
        is_valid, error = self.path_validator.validate_worktree_path(
            worktree_path, user_id
        )
        if not is_valid:
            self.audit_logger.log_security_rejection(
                user_id=user_id,
                operation="remove_worktree",
                rejection_reason=error,
                params={
                    "repo_nickname": repo_nickname,
                    "worktree_path": worktree_path,
                },
            )
            raise ValueError(f"Invalid worktree path: {error}")

        # Log removal attempt
        self.audit_logger.log_removal_attempt(
            user_id=user_id,
            repo_nickname=repo_nickname,
            worktree_path=worktree_path,
            force=force,
        )

        # SAFETY CHECK 1: Check for uncommitted changes
        has_uncommitted = await self._check_uncommitted_changes(worktree_path)

        if has_uncommitted and not force:
            return {
                "success": False,
                "error": "Worktree has uncommitted changes. Use --force with --force-reason to override.",
                "safety_check": "uncommitted_changes",
            }

        # SECURITY-001: Require reason when bypassing uncommitted changes
        if has_uncommitted and force and not force_reason:
            return {
                "success": False,
                "error": "Worktree has uncommitted changes. --force requires --force-reason.",
                "safety_check": "force_reason_required",
            }

        # SECURITY-001: Create backup before force removal
        backup_path = None
        if has_uncommitted and force:
            try:
                # Get branch name for backup naming
                branch = await self._get_worktree_branch(worktree_path)
                backup_path = await self.backup_manager.create_backup_before_removal(
                    worktree_path=Path(worktree_path),
                    repo_nickname=repo_nickname,
                    branch=branch,
                    user_id=user_id,
                )
                logger.info(f"Backup created before force removal: {backup_path}")
            except Exception as e:
                logger.error(f"Failed to create backup: {e}", exc_info=True)
                return {
                    "success": False,
                    "error": f"Failed to create backup before force removal: {e}",
                    "safety_check": "backup_failed",
                }

        # SAFETY CHECK 2: Check if worktree is depended on by other repos
        dependents = self._get_worktree_dependents(repo_nickname, worktree_path)
        if dependents and not force:
            return {
                "success": False,
                "error": f"Worktree is depended on by {len(dependents)} other repositories",
                "safety_check": "dependency_block",
                "dependents": dependents,
            }

        # SAFETY CHECK 3: Verify path is actually a worktree
        if not await self._verify_is_worktree(worktree_path):
            return {
                "success": False,
                "error": "Path is not a valid worktree",
                "safety_check": "path_validation",
            }

        try:
            # Get provider and delegate
            provider = await self.provider_registry.get_available_provider()
            result = await provider.remove_worktree(
                repository_path=Path(repo.path),
                worktree_path=Path(worktree_path),
                force=force,
            )

            # Enhanced audit logging for force operations
            if force and has_uncommitted:
                self.audit_logger.log_forced_removal(
                    user_id=user_id,
                    repo_nickname=repo_nickname,
                    worktree_path=worktree_path,
                    force_reason=force_reason or "not provided",
                    has_uncommitted=has_uncommitted,
                    backup_path=str(backup_path) if backup_path else None,
                )
            else:
                self.audit_logger.log_removal_success(
                    user_id=user_id,
                    repo_nickname=repo_nickname,
                    worktree_path=worktree_path,
                    force=force,
                )

            logger.info(f"Worktree removed successfully: {worktree_path}")
            return result

        except Exception as e:
            self.audit_logger.log_removal_failure(
                user_id=user_id,
                repo_nickname=repo_nickname,
                worktree_path=worktree_path,
                error=str(e),
            )
            logger.error(f"Failed to remove worktree: {e}", exc_info=True)
            raise

    async def list_worktrees(
        self, repo_nickname: str | None = None, user_id: str | None = None
    ) -> dict[str, Any]:
        """
        List worktrees across all repositories or specific repository.

        Args:
            repo_nickname: Optional repo filter
            user_id: User ID for audit logging

        Returns:
            List of worktrees with metadata
        """
        # Log list operation (SECURITY-003)
        if repo_nickname:
            self.audit_logger.log_list_operation(user_id, repo_nickname)
        else:
            self.audit_logger.log_list_operation(user_id, None)

        try:
            if repo_nickname:
                # List worktrees for specific repo
                repo = self.repo_manager.get_repo(repo_nickname)
                if not repo:
                    raise ConfigurationError(f"Repository not found: {repo_nickname}")

                provider = await self.provider_registry.get_available_provider()
                result = await provider.list_worktrees(repository_path=Path(repo.path))

                return {
                    "success": True,
                    "repo_nickname": repo_nickname,
                    **result,
                }
            else:
                # Aggregate across all repos
                all_worktrees = []
                repos = self.repo_manager.list_repos()

                for repo in repos:
                    try:
                        provider = await self.provider_registry.get_available_provider()
                        result = await provider.list_worktrees(
                            repository_path=Path(repo.path)
                        )
                        all_worktrees.extend(result.get("worktrees", []))
                    except Exception as e:
                        logger.warning(
                            f"Failed to list worktrees for {repo.nickname}: {e}"
                        )
                        continue

                return {
                    "success": True,
                    "worktrees": all_worktrees,
                    "total_count": len(all_worktrees),
                }

        except Exception as e:
            logger.error(f"Failed to list worktrees: {e}", exc_info=True)
            raise

    async def prune_worktrees(
        self, repo_nickname: str, user_id: str | None = None
    ) -> dict[str, Any]:
        """
        Prune stale worktree references with safety validation.

        Args:
            repo_nickname: Repository nickname
            user_id: User ID for audit logging

        Returns:
            Prune results
        """
        # Validate repository exists
        repo = self.repo_manager.get_by_name(repo_nickname)
        if not repo:
            # Try by package name as fallback
            repo = self.repo_manager.get_by_package(repo_nickname)
        if not repo:
            raise ConfigurationError(f"Repository not found: {repo_nickname}")

        # Log prune operation (SECURITY-003)
        # (We'll log after we know the count)

        try:
            # Get list of worktrees
            provider = await self.provider_registry.get_available_provider()
            list_result = await provider.list_worktrees(repository_path=Path(repo.path))
            worktrees = list_result.get("worktrees", [])

            pruned_count = 0
            for wt in worktrees:
                wt_path = wt.get("path")
                branch = wt.get("branch")

                # Check if branch still exists
                if not await self._branch_exists(str(repo.path), branch):
                    # Branch deleted, safe to prune
                    logger.info(f"Pruning stale worktree: {wt_path} (branch: {branch})")
                    await provider.remove_worktree(
                        repository_path=Path(repo.path),
                        worktree_path=Path(wt_path),
                        force=True,
                    )
                    pruned_count += 1

            # Log prune operation with count
            self.audit_logger.log_prune_operation(
                user_id=user_id, repo_nickname=repo_nickname, pruned_count=pruned_count
            )

            return {
                "success": True,
                "repo_nickname": repo_nickname,
                "pruned_count": pruned_count,
            }

        except Exception as e:
            logger.error(f"Failed to prune worktrees: {e}", exc_info=True)
            raise

    async def get_worktree_safety_status(
        self, repo_nickname: str, worktree_path: str
    ) -> dict[str, Any]:
        """
        Get safety status for a worktree before removal.

        Reports on:
        - Uncommitted changes
        - Active dependencies from other repos
        - Branch status (merged, deleted, etc.)
        - Worktree validity

        Args:
            repo_nickname: Repository nickname
            worktree_path: Path to worktree

        Returns:
            Safety status with recommendations
        """
        return {
            "uncommitted_changes": await self._check_uncommitted_changes(worktree_path),
            "dependencies": self._get_worktree_dependents(repo_nickname, worktree_path),
            "is_valid_worktree": await self._verify_is_worktree(worktree_path),
            "path_safe": self.path_validator.validate_worktree_path(worktree_path)[0],
        }

    async def get_provider_health(self) -> dict[str, dict[str, Any]]:
        """
        Get health status of all providers.

        Returns:
            Dictionary mapping provider names to health status
        """
        return await self.provider_registry.get_all_provider_health()

    async def start_health_check_loop(self, interval: float = 60.0) -> None:
        """
        Start background health checking loop.

        Args:
            interval: Check interval in seconds
        """
        await self.provider_registry.start_health_check_loop(interval=interval)

    # ========================================================================
    # Safety check methods
    # ========================================================================

    async def _check_uncommitted_changes(self, worktree_path: str) -> bool:
        """Check if worktree has uncommitted changes."""
        try:
            result = await self._execute_git_command(
                worktree_path, ["status", "--porcelain"]
            )
            return bool(result.strip())
        except Exception as e:
            logger.warning(f"Failed to check uncommitted changes: {e}")
            return False

    def _get_worktree_dependents(
        self, repo_nickname: str, worktree_path: str
    ) -> list[str]:
        """
        Get repositories that depend on this worktree (ARCH-002 fix).

        Returns list of consumer repositories that would be affected.
        """
        deps = self.coordination_manager.list_dependencies(provider=repo_nickname)
        dependents = []

        for dep in deps:
            # Check if dependency is worktree-specific
            if hasattr(dep, "worktree_path") and dep.worktree_path == worktree_path:
                if dep.status.value != "satisfied":
                    dependents.append(dep.consumer)

        return dependents

    async def _verify_is_worktree(self, worktree_path: str) -> bool:
        """Verify path is actually a git worktree."""
        try:
            path = Path(worktree_path)
            git_file = path / ".git"

            if not git_file.exists():
                return False

            # Check for gitdir: marker (indicates worktree)
            content = git_file.read_text().strip()
            return content.startswith("gitdir:")

        except Exception as e:
            logger.warning(f"Failed to verify worktree: {e}")
            return False

    async def _branch_exists(self, repo_path: str, branch: str) -> bool:
        """Check if branch exists in repository."""
        try:
            result = await self._execute_git_command(
                repo_path, ["branch", "--list", branch]
            )
            return bool(result.strip())
        except Exception as e:
            logger.warning(f"Failed to check branch existence: {e}")
            return False

    async def _get_worktree_branch(self, worktree_path: str) -> str:
        """Get current branch for worktree."""
        try:
            result = await self._execute_git_command(
                worktree_path, ["branch", "--show-current"]
            )
            return result.strip()
        except Exception as e:
            logger.warning(f"Failed to get worktree branch: {e}")
            return "unknown"

    async def _execute_git_command(
        self, cwd: str, args: list[str]
    ) -> str:
        """
        Execute git command and return output.

        Args:
            cwd: Working directory
            args: Git command arguments (without 'git')

        Returns:
            Command output as string
        """
        cmd = ["git"] + args

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(f"Git command failed: {stderr.decode()}")

        return stdout.decode()
