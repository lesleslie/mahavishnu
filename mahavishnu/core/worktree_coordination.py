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
import os
from pathlib import Path
from typing import Any

from mahavishnu.core.coordination.manager import CoordinationManager
from mahavishnu.core.errors import ConfigurationError
from mahavishnu.core.paths import get_worktree_base_path
from mahavishnu.core.repo_manager import RepositoryManager

from .worktree_audit import WorktreeAuditLogger
from .worktree_backup import WorktreeBackupManager
from .worktree_providers.base import WorktreeProvider
from .worktree_providers.local import DirectGitWorktreeProvider, LocalWorktreeProvider
from .worktree_providers.registry import WorktreeProviderRegistry
from .worktree_providers.session_buddy import SessionBuddyWorktreeProvider
from .worktree_validation import WorktreePathValidator

logger = logging.getLogger(__name__)

# Workaround for missing `list_worktrees` / `create_worktree` /
# `remove_worktree` tools on the Session-Buddy MCP server. The provider's
# health_check() only verifies TCP reachability, so a healthy MCP server
# still fails the actual worktree tool calls. Set the env var to "true"
# (or set `worktree_providers.session_buddy_enabled: true` in
# settings/mahavishnu.yaml) once session-buddy exposes those tools.
# Tracking: docs/superpowers/plans/2026-07-26-session-buddy-worktree-tools.md
_SESSION_BUDDY_ENABLED = os.environ.get(
    "MAHAVISHNU_WORKTREE_SESSION_BUDDY_ENABLED", "true"
).lower() in ("1", "true", "yes", "on")


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
            # ADR 015 v4 §1: LocalWorktreeProvider is the v4-era primary
            # local backend (preserves .git/objects/ sharing with the
            # source repo, returns WorktreeHandle). DirectGitWorktreeProvider
            # is the 1-release deprecated alias (Phase 0.5).
            providers = [
                LocalWorktreeProvider(),  # v4 primary (local)
                DirectGitWorktreeProvider(),  # 1-release alias
            ]
            # Re-enable SessionBuddyWorktreeProvider when its MCP server
            # exposes the worktree tools (worktree-list / worktree-add /
            # worktree-remove). Until then, the provider's health_check()
            # only verifies TCP reachability and the actual tool calls
            # fail with "Unknown tool". See
            # docs/superpowers/plans/2026-07-26-session-buddy-worktree-tools.md.
            if _SESSION_BUDDY_ENABLED:
                providers.insert(0, SessionBuddyWorktreeProvider())  # Primary

        self.provider_registry = WorktreeProviderRegistry(providers)

        # Path validator (security - defense in depth)
        if allowed_worktree_roots is None:
            # Default allow-list covers:
            #  - <get_worktree_base_path()> : the canonical convention
            #    (resolved from MAHAVISHNU_WORKTREE_BASE_PATH or
            #    MAHAVISHNU_AUTO_WORKTREE_ROOT or Path.home()/"worktrees")
            #  - <cwd>        : the current working directory
            #  - <repo>/.worktrees
            #  - <repo>/.claude/worktrees
            #    For every repo registered with the repo_manager. This
            #    replaces the previous broad `~/Projects` entry, which
            #    under a str.startswith check let `~/Projects-evil/...`
            #    match the `~/Projects` prefix (sibling-confusion). The
            #    per-repo subdirs are enumerated at init time so the
            #    validator's is_relative_to check can match them
            #    component-wise without glob support.
            #
            # Defense-in-depth (CWE-22/114/170) is preserved: the
            # validator still rejects null bytes, traversal, and shell
            # metacharacters on top of this allow-list.
            allowed_worktree_roots = [
                get_worktree_base_path(),
                Path.cwd(),
            ]
            try:
                for repo in self.repo_manager.filter():
                    repo_path = Path(repo.path).resolve()
                    allowed_worktree_roots.append(repo_path / ".worktrees")
                    allowed_worktree_roots.append(repo_path / ".claude" / "worktrees")
            except Exception as e:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
                # If the repo catalog is briefly unavailable, fall back
                # to the base allow-list rather than failing to construct
                # the coordinator. Per-repo subdirs are added on the next
                # coordinator construction.
                logger.warning(
                    "Failed to enumerate repo subdirs for worktree allow-list: %s",
                    e,
                )

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
        blocking_deps = self.coordination_manager._get_blocking_dependencies(repo_nickname)
        if blocking_deps:
            logger.warning(
                "Repo %s has %d blocking dependencies: %s",
                repo_nickname,
                len(blocking_deps),
                blocking_deps,
            )

        # Generate safe worktree path
        if worktree_name:
            # Use custom worktree name
            worktree_path = self.path_validator.get_safe_worktree_path(repo_nickname, worktree_name)
        else:
            # Generate from branch name
            worktree_path = self.path_validator.get_safe_worktree_path(repo_nickname, branch)

        # Validate worktree path (SECURITY-002: defense in depth)
        is_valid, error = self.path_validator.validate_worktree_path(str(worktree_path), user_id)
        if not is_valid:
            self.audit_logger.log_security_rejection(
                user_id=user_id,
                operation="create_worktree",
                rejection_reason=error or "Path validation failed",
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
            logger.exception("Failed to create worktree")
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
        is_valid, error = self.path_validator.validate_worktree_path(worktree_path, user_id)
        if not is_valid:
            self.audit_logger.log_security_rejection(
                user_id=user_id,
                operation="remove_worktree",
                rejection_reason=error or "Path validation failed",
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

        # Run preflight safety checks (uncommitted, dependents, verify).
        # Returns (error_dict_or_None, has_uncommitted, backup_path_or_None).
        safety_error, has_uncommitted, backup_path = await self._evaluate_removal_safety(
            repo_nickname=repo_nickname,
            worktree_path=worktree_path,
            force=force,
            force_reason=force_reason,
            user_id=user_id,
        )
        if safety_error is not None:
            return safety_error

        try:
            # Get provider and delegate
            provider = await self.provider_registry.get_available_provider()
            result = await provider.remove_worktree(
                repository_path=Path(repo.path),
                worktree_path=Path(worktree_path),
                force=force,
            )

            # Bug session-buddy-mcp-remove-worktree-bugs.md: do not log
            # ``removal_success`` when the provider reports failure. The
            # provider's return value is the only source of truth — an
            # exception path below handles programming errors, but a
            # well-formed ``{"success": False, ...}`` dict was previously
            # logged as success, hiding real failures behind a green audit
            # line.
            self._log_removal_outcome(
                result=result,
                repo_nickname=repo_nickname,
                worktree_path=worktree_path,
                force=force,
                force_reason=force_reason,
                user_id=user_id,
                has_uncommitted=has_uncommitted,
                backup_path=backup_path,
            )

            if not result.get("success"):
                return result

            logger.info(f"Worktree removed successfully: {worktree_path}")
            return result

        except Exception as e:
            self.audit_logger.log_removal_failure(
                user_id=user_id,
                repo_nickname=repo_nickname,
                worktree_path=worktree_path,
                error=str(e),
            )
            logger.exception("Failed to remove worktree")
            raise

    async def _evaluate_removal_safety(
        self,
        repo_nickname: str,
        worktree_path: str,
        force: bool,
        force_reason: str | None,
        user_id: str | None,
    ) -> tuple[dict[str, Any] | None, bool, Path | None]:
        """Run preflight safety checks for worktree removal.

        Returns:
            (error_dict_or_None, has_uncommitted, backup_path_or_None).

            If the first element is not None, the caller should return it
            as the operation result. The boolean + Path are returned for
            the caller's audit log regardless.
        """
        # SAFETY CHECK 1: Check for uncommitted changes
        has_uncommitted = await self._check_uncommitted_changes(worktree_path)

        if has_uncommitted and not force:
            return (
                {
                    "success": False,
                    "error": "Worktree has uncommitted changes. Use --force with --force-reason to override.",
                    "safety_check": "uncommitted_changes",
                },
                has_uncommitted,
                None,
            )

        # SECURITY-001: Require reason when bypassing uncommitted changes
        if has_uncommitted and force and not force_reason:
            return (
                {
                    "success": False,
                    "error": "Worktree has uncommitted changes. --force requires --force-reason.",
                    "safety_check": "force_reason_required",
                },
                has_uncommitted,
                None,
            )

        # SECURITY-001: Create backup before force removal
        backup_path: Path | None = None
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
                logger.exception("Failed to create backup")
                return (
                    {
                        "success": False,
                        "error": f"Failed to create backup before force removal: {e}",
                        "safety_check": "backup_failed",
                    },
                    has_uncommitted,
                    None,
                )

        # SAFETY CHECK 2: Check if worktree is depended on by other repos
        dependents = self._get_worktree_dependents(repo_nickname, worktree_path)
        if dependents and not force:
            return (
                {
                    "success": False,
                    "error": f"Worktree is depended on by {len(dependents)} other repositories",
                    "safety_check": "dependency_block",
                    "dependents": dependents,
                },
                has_uncommitted,
                backup_path,
            )

        # SAFETY CHECK 3: Verify path is actually a worktree
        if not await self._verify_is_worktree(worktree_path):
            return (
                {
                    "success": False,
                    "error": "Path is not a valid worktree",
                    "safety_check": "path_validation",
                },
                has_uncommitted,
                backup_path,
            )

        return None, has_uncommitted, backup_path

    def _log_removal_outcome(
        self,
        result: dict[str, Any],
        repo_nickname: str,
        worktree_path: str,
        force: bool,
        force_reason: str | None,
        user_id: str | None,
        has_uncommitted: bool,
        backup_path: Path | None,
    ) -> None:
        """Emit the audit log entry for a removal attempt's outcome.

        Extracted from ``remove_worktree`` to keep the public method's
        branch count below the project's complexity limit (C901).
        """
        succeeded = bool(result.get("success"))

        if succeeded and force and has_uncommitted:
            self.audit_logger.log_forced_removal(
                user_id=user_id,
                repo_nickname=repo_nickname,
                worktree_path=worktree_path,
                force_reason=force_reason or "not provided",
                has_uncommitted=has_uncommitted,
                backup_path=str(backup_path) if backup_path else None,
            )
        elif succeeded:
            self.audit_logger.log_removal_success(
                user_id=user_id,
                repo_nickname=repo_nickname,
                worktree_path=worktree_path,
                force=force,
            )
        else:
            self.audit_logger.log_removal_failure(
                user_id=user_id,
                repo_nickname=repo_nickname,
                worktree_path=worktree_path,
                error=str(result.get("error", "provider reported failure")),
            )
            logger.warning(
                "Worktree removal failed: path=%s, error=%s",
                worktree_path,
                result.get("error"),
            )

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
                        result = await provider.list_worktrees(repository_path=Path(repo.path))
                        all_worktrees.extend(result.get("worktrees", []))
                    except Exception as e:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
                        logger.warning(f"Failed to list worktrees for {repo.nickname}: {e}")
                        continue

                return {
                    "success": True,
                    "worktrees": all_worktrees,
                    "total_count": len(all_worktrees),
                }

        except Exception:
            logger.exception("Failed to list worktrees")
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

        except Exception:
            logger.exception("Failed to prune worktrees")
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
        health = self.provider_registry.get_provider_health()
        return {name: {"healthy": status} for name, status in health.items()}

    async def start_health_check_loop(self, interval: float = 60.0) -> None:
        """
        Start background health checking loop.

        Args:
            interval: Check interval in seconds
        """
        await self.provider_registry.health_check_loop(interval_seconds=interval)

    # ========================================================================
    # Safety check methods
    # ========================================================================

    async def _check_uncommitted_changes(self, worktree_path: str) -> bool:
        """Check if worktree has uncommitted changes."""
        try:
            result = await self._execute_git_command(worktree_path, ["status", "--porcelain"])
            return bool(result.strip())
        except Exception as e:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            logger.warning(f"Failed to check uncommitted changes: {e}")
            return False

    def _get_worktree_dependents(self, repo_nickname: str, worktree_path: str) -> list[str]:
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

        except Exception as e:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            logger.warning(f"Failed to verify worktree: {e}")
            return False

    async def _branch_exists(self, repo_path: str, branch: str) -> bool:
        """Check if branch exists in repository."""
        try:
            result = await self._execute_git_command(repo_path, ["branch", "--list", branch])
            return bool(result.strip())
        except Exception as e:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            logger.warning(f"Failed to check branch existence: {e}")
            return False

    async def _get_worktree_branch(self, worktree_path: str) -> str:
        """Get current branch for worktree."""
        try:
            result = await self._execute_git_command(worktree_path, ["branch", "--show-current"])
            return result.strip()
        except Exception as e:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            logger.warning(f"Failed to get worktree branch: {e}")
            return "unknown"

    async def _execute_git_command(self, cwd: str, args: list[str]) -> str:
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

    # ------------------------------------------------------------------
    # v4 WorktreeHandle-based dispatch (ADR 015 v4 §13, §18 Phase 2)
    # ------------------------------------------------------------------
    #
    # The legacy ``create_worktree`` / ``remove_worktree`` / ``list_worktrees``
    # methods above return ``dict[str, Any]`` and remain in place for the
    # Phase 5 deprecation window. The new v4 methods below return
    # ``WorktreeHandle`` / ``WorktreeRef`` directly. Legacy call sites
    # continue to use the dict API; new code should use these.

    async def create_worktree_handle(
        self,
        repo_nickname: str,
        branch: str,
        base_ref: str,
        principal: Any,
    ) -> Any:
        """v4 dispatch: resolve a v4 provider via the registry, then call
        ``create_worktree_handle`` on it.

        Falls back to a structured error if the resolved provider
        doesn't expose the v4 method (e.g. legacy providers that only
        support ``create_worktree``).
        """
        from mahavishnu.core.errors import WorktreeError

        provider = await self.provider_registry.get_available_provider()
        if not hasattr(provider, "create_worktree_handle"):
            raise WorktreeError(
                f"Provider {provider.provider_name()} does not support the v4 "
                f"create_worktree_handle API; use the legacy create_worktree path"
            )
        return await provider.create_worktree_handle(
            repo=repo_nickname,
            branch=branch,
            base_ref=base_ref,
            principal=principal,
        )

    async def fetch_worktree_handle(self, handle: Any) -> Any:
        """v4 dispatch: resolve provider + call ``fetch(handle)``."""
        from mahavishnu.core.errors import WorktreeError

        provider = await self.provider_registry.get_available_provider()
        if not hasattr(provider, "fetch"):
            raise WorktreeError(
                f"Provider {provider.provider_name()} does not support v4 fetch"
            )
        return await provider.fetch(handle)

    async def remove_worktree_handle(self, handle: Any) -> bool:
        """v4 dispatch: resolve provider + call ``remove_handle(handle)``."""
        from mahavishnu.core.errors import WorktreeError

        provider = await self.provider_registry.get_available_provider()
        if not hasattr(provider, "remove_handle"):
            raise WorktreeError(
                f"Provider {provider.provider_name()} does not support v4 remove_handle"
            )
        return await provider.remove_handle(handle)

    async def list_worktree_handles(
        self,
        principal: Any | None = None,
        repo: str | None = None,
        caller: Any | None = None,
    ) -> list:
        """v4 dispatch: resolve provider + call ``list_handles(...)``."""
        from mahavishnu.core.errors import WorktreeError

        provider = await self.provider_registry.get_available_provider()
        if not hasattr(provider, "list_handles"):
            raise WorktreeError(
                f"Provider {provider.provider_name()} does not support v4 list_handles"
            )
        return await provider.list_handles(
            principal=principal, repo=repo, caller=caller
        )

    def _legacy_create_worktree_response(self, handle: Any) -> dict[str, Any]:
        """Adapter: convert a v4 ``WorktreeHandle`` to the legacy
        ``dict[str, Any]`` response shape consumed by v1 callers.

        Preserves backward compatibility for legacy call sites that
        still expect the dict shape during the Phase 5 deprecation
        window. New code should consume ``WorktreeHandle`` directly.
        """
        from .worktree_providers.types import (
            LocalWorktreeRef,
            RemoteWorktreeRef,
        )

        worktree_path: str = ""
        if isinstance(handle.storage_ref, LocalWorktreeRef):
            worktree_path = str(handle.storage_ref.path)
        elif isinstance(handle.storage_ref, RemoteWorktreeRef):
            worktree_path = f"s3://{handle.storage_ref.bucket}/{handle.storage_ref.key}"

        return {
            "success": True,
            "worktree_path": worktree_path,
            "branch": handle.branch,
            "handle_id": handle.handle_id,
            "provider": "v4-handle-based",
            "provenance": handle.provenance,
        }
