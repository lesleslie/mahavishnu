"""
Path validation for worktree operations (SECURITY-002 fix).

Implements defense-in-depth by validating paths BEFORE MCP calls.

Security Checks:
- Null byte prevention (CWE-170)
- Path traversal prevention (CWE-22)
- Shell metacharacter detection (CWE-114)
- Allowed root verification
- Audit logging for security rejections
"""

import logging
from pathlib import Path
from typing import Any

from ..core.errors import ValidationError

logger = logging.getLogger(__name__)


class WorktreePathValidator:
    """Validate worktree paths with security checks.

    This validator implements defense-in-depth security by validating all paths
    at the Mahavishnu layer BEFORE they reach MCP calls to Session-Buddy or git commands.

    Security Principles:
    1. Never trust user input
    2. Validate before processing
    3. Use allow-listing (allowed roots) rather than deny-listing
    4. Log all security rejections for audit trail

    Example:
        >>> validator = WorktreePathValidator(
        ...     allowed_roots=[Path.home() / "worktrees", Path.cwd()]
        ... )
        >>> is_valid, error = validator.validate_worktree_path(
        ...     "~/worktrees/mahavishnu/feature-auth",
        ...     user_id="user-123"
        ... )
        >>> assert is_valid
    """

    # Dangerous shell metacharacters (CWE-114)
    SHELL_METACHARACTERS = [";", "&", "|", "`", "$", "\n", "\r", "(", ")", "<", ">"]

    # Dangerous path components (CWE-22)
    DANGER_PATH_COMPONENTS = ["..", "~", ".git", ".svn", ".hg"]

    def __init__(
        self,
        allowed_roots: list[Path],
        strict_mode: bool = True,
    ) -> None:
        """Initialize path validator with allowed root directories.

        Args:
            allowed_roots: List of allowed base paths (e.g., ~/worktrees, cwd)
            strict_mode: If True, reject any path outside allowed roots
        """
        # Resolve all allowed roots to absolute paths
        self.allowed_roots = [root.resolve() for root in allowed_roots]
        self.strict_mode = strict_mode

        logger.debug(
            f"WorktreePathValidator initialized with {len(self.allowed_roots)} "
            f"allowed roots: {[str(r) for r in self.allowed_roots]}"
        )

    def validate_worktree_path(
        self,
        worktree_path: str,
        user_id: str | None = None,
    ) -> tuple[bool, str | None]:
        """Validate worktree path with comprehensive security checks.

        Security checks:
        1. Null byte prevention (CWE-170)
        2. Path traversal prevention (CWE-22)
        3. Shell metacharacter detection (CWE-114)
        4. Allowed root verification
        5. Path normalization

        Args:
            worktree_path: Path to validate
            user_id: User ID for audit logging

        Returns:
            (is_valid, error_message) tuple

        Raises:
            ValidationError: If path is malicious (not just invalid)
        """
        try:
            # Check 1: Null byte prevention (CWE-170)
            if "\x00" in worktree_path:
                error = "Path contains null bytes (CWE-170)"
                self._log_security_rejection("null_byte", worktree_path, user_id, error)
                return False, error

            # Check 2: Shell metacharacter detection (CWE-114)
            if self._has_shell_metacharacters(worktree_path):
                error = "Path contains shell metacharacters (CWE-114)"
                self._log_security_rejection(
                    "shell_metachar", worktree_path, user_id, error
                )
                return False, error

            # Check 3: Path traversal prevention (CWE-22)
            path = Path(worktree_path)

            # Check for dangerous components before resolution
            for component in path.parts:
                if component in self.DANGER_PATH_COMPONENTS:
                    error = f"Path contains dangerous component: {component} (CWE-22)"
                    self._log_security_rejection(
                        "path_traversal", worktree_path, user_id, error
                    )
                    return False, error

            # Resolve to absolute path
            try:
                resolved_path = path.resolve()
            except Exception as e:
                error = f"Path resolution failed: {e}"
                logger.warning(f"Invalid path '{worktree_path}': {error}")
                return False, error

            # Check 4: Allowed root verification (defense in depth)
            if self.strict_mode:
                is_allowed = any(
                    str(resolved_path).startswith(str(root)) or resolved_path == root
                    for root in self.allowed_roots
                )

                if not is_allowed:
                    error = (
                        f"Path outside allowed directories: {self.allowed_roots} "
                        f"(CWE-22)"
                    )
                    self._log_security_rejection(
                        "allowed_root", worktree_path, user_id, error
                    )
                    return False, error

            # Check 5: Path normalization (detect escape attempts)
            normalized = str(resolved_path)
            if "../" in normalized or "~/" in normalized:
                error = f"Path contains escape sequences after resolution (CWE-22)"
                self._log_security_rejection(
                    "escape_sequence", worktree_path, user_id, error
                )
                return False, error

            # All checks passed
            logger.debug(f"Path validation passed: {worktree_path}")
            return True, None

        except ValidationError:
            # Re-raise ValidationError (malicious path)
            raise
        except Exception as e:
            # Other exceptions are just invalid paths (not malicious)
            logger.warning(f"Path validation error for '{worktree_path}': {e}")
            return False, str(e)

    def _has_shell_metacharacters(self, path: str) -> bool:
        """Check if path contains shell metacharacters.

        Args:
            path: Path string to check

        Returns:
            True if path contains dangerous shell metacharacters
        """
        return any(char in path for char in self.SHELL_METACHARACTERS)

    def _log_security_rejection(
        self,
        rejection_type: str,
        worktree_path: str,
        user_id: str | None,
        error_message: str,
    ) -> None:
        """Log security rejection to audit trail.

        Args:
            rejection_type: Type of security rejection (null_byte, etc.)
            worktree_path: The rejected path
            user_id: User ID for audit logging
            error_message: Error message
        """
        # Log to application logger
        logger.warning(
            f"SECURITY REJECTION ({rejection_type}): user={user_id}, "
            f"path='{worktree_path}', error='{error_message}'"
        )

        # Log to audit logger (for SOC 2, ISO 27001, PCI DSS compliance)
        try:
            from ..mcp.auth import get_audit_logger

            get_audit_logger().log(
                event_type="security_rejection",
                user_id=user_id,
                tool_name="WorktreePathValidator",
                params={
                    "worktree_path": worktree_path,
                    "rejection_type": rejection_type,
                },
                result="denied",
                error=error_message,
            )
        except Exception as e:
            # Don't fail if audit logging fails
            logger.error(f"Failed to log security rejection to audit trail: {e}")

    def validate_repository_path(
        self,
        repository_path: str,
        user_id: str | None = None,
    ) -> tuple[bool, str | None]:
        """Validate repository path with security checks.

        Similar to validate_worktree_path but specifically for repository paths.
        Repository paths have different validation rules:
        - Must be absolute or resolvable to absolute
        - Must exist and be a valid git repository
        - Can be outside allowed roots (repositories are trusted)

        Args:
            repository_path: Path to validate
            user_id: User ID for audit logging

        Returns:
            (is_valid, error_message) tuple
        """
        try:
            # Check for null bytes
            if "\x00" in repository_path:
                error = "Repository path contains null bytes (CWE-170)"
                self._log_security_rejection(
                    "null_byte", repository_path, user_id, error
                )
                return False, error

            # Check for shell metacharacters
            if self._has_shell_metacharacters(repository_path):
                error = "Repository path contains shell metacharacters (CWE-114)"
                self._log_security_rejection(
                    "shell_metachar", repository_path, user_id, error
                )
                return False, error

            # Resolve to absolute path
            path = Path(repository_path)
            try:
                resolved_path = path.resolve()
            except Exception as e:
                error = f"Repository path resolution failed: {e}"
                logger.warning(f"Invalid repository path '{repository_path}': {error}")
                return False, error

            # Check if it's a valid git repository
            if not self._is_git_repository(resolved_path):
                return False, "Not a valid git repository (missing .git directory)"

            logger.debug(f"Repository path validation passed: {repository_path}")
            return True, None

        except ValidationError:
            raise
        except Exception as e:
            logger.warning(f"Repository path validation error: {e}")
            return False, str(e)

    def _is_git_repository(self, path: Path) -> bool:
        """Check if path is a valid git repository.

        Args:
            path: Path to check

        Returns:
            True if path contains .git directory
        """
        git_dir = path / ".git"
        return git_dir.exists() and git_dir.is_dir()

    def get_safe_worktree_path(
        self,
        repo_nickname: str,
        branch: str,
        base_dir: Path | None = None,
    ) -> Path:
        """Generate a safe worktree path from repository and branch.

        This is a helper method to generate safe, XDG-compliant worktree paths
        without requiring user input. It sanitizes the branch name to prevent
        path traversal attacks.

        Args:
            repo_nickname: Repository nickname (safe, from repos.yaml)
            branch: Branch name (will be sanitized)
            base_dir: Base directory for worktrees (default: ~/worktrees)

        Returns:
            Safe, absolute worktree path
        """
        if base_dir is None:
            base_dir = Path.home() / "worktrees"

        # Sanitize branch name for filesystem
        safe_branch = self._sanitize_branch_name(branch)

        # Generate safe path
        worktree_path = base_dir / repo_nickname / safe_branch

        logger.debug(f"Generated safe worktree path: {worktree_path}")
        return worktree_path

    def _sanitize_branch_name(self, branch: str) -> str:
        """Sanitize branch name for safe filesystem usage.

        Args:
            branch: Branch name to sanitize

        Returns:
            Sanitized branch name safe for filesystem
        """
        # Replace dangerous characters
        dangerous_chars = ["../", "..\\", "~", "\x00"]
        sanitized = branch

        for char in dangerous_chars:
            sanitized = sanitized.replace(char, "_")

        # Replace slashes with dashes (flatten branch hierarchy)
        sanitized = sanitized.replace("/", "-").replace("\\", "-")

        # Remove any remaining non-alphanumeric characters except safe ones
        safe_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
        sanitized = "".join(c if c in safe_chars else "_" for c in sanitized)

        # Ensure not empty
        if not sanitized:
            sanitized = "unnamed"

        return sanitized
