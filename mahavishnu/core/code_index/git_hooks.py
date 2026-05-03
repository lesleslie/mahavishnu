"""Install/uninstall git hooks for automatic code graph indexing."""

from __future__ import annotations

from pathlib import Path
import stat

HOOK_CONTENT = """#!/bin/sh
# Managed by mahavishnu index --install-hooks
# Remove with: mahavishnu index --uninstall-hooks --repo <path>
mahavishnu index --trigger git-event --repo "$(pwd)" &
"""

MAHAVISHNU_HEADER = "# Managed by mahavishnu index --install-hooks"

_HOOK_NAMES = ("post-commit", "post-merge", "post-rewrite")


def install_hooks(repo_path: str, force: bool = False) -> list[str]:
    """Install post-commit, post-merge, and post-rewrite hooks.

    Args:
        repo_path: Absolute path to a git repository.
        force: Overwrite existing hooks that are not managed by mahavishnu.

    Returns:
        List of installed hook names.

    Raises:
        FileExistsError: A hook already exists and is not mahavishnu-managed
            (unless *force* is True).
    """
    hooks_dir = Path(repo_path) / ".git" / "hooks"
    installed: list[str] = []

    for hook_name in _HOOK_NAMES:
        hook_file = hooks_dir / hook_name
        hooks_dir.mkdir(parents=True, exist_ok=True)

        if hook_file.exists() and not force:
            content = hook_file.read_text()
            if MAHAVISHNU_HEADER not in content:
                raise FileExistsError(
                    f"Hook {hook_name} exists but is not managed by mahavishnu. "
                    f"Use --force to overwrite."
                )

        hook_file.write_text(HOOK_CONTENT)
        hook_file.chmod(hook_file.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        installed.append(hook_name)

    return installed


def uninstall_hooks(repo_path: str) -> list[str]:
    """Remove only mahavishnu-managed hooks.

    Args:
        repo_path: Absolute path to a git repository.

    Returns:
        List of removed hook names.  Unmanaged hooks are left untouched.
    """
    hooks_dir = Path(repo_path) / ".git" / "hooks"
    removed: list[str] = []

    for hook_name in _HOOK_NAMES:
        hook_file = hooks_dir / hook_name
        if hook_file.exists():
            content = hook_file.read_text()
            if MAHAVISHNU_HEADER in content:
                hook_file.unlink()
                removed.append(hook_name)

    return removed
