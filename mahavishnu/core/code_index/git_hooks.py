"""Install/uninstall git hooks for automatic code graph indexing."""

from __future__ import annotations

from pathlib import Path
import stat

# Post-event hooks run the code-graph indexer.
# Skip worktrees: the worktree path isn't registered in ecosystem.yaml
# (which only lists canonical repo roots), and the index should reflect
# canonical main-branch state, not transient feature-branch work.
# Detection: a linked worktree's --git-dir differs from the main
# checkout's --git-common-dir; the main checkout sees them equal.
HOOK_CONTENT = """#!/bin/sh
# Managed by mahavishnu index install-hooks
# Remove with: mahavishnu index uninstall-hooks <path>
GIT_DIR=$(git rev-parse --git-dir 2>/dev/null)
GIT_COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null)
if [ -n "$GIT_DIR" ] && [ -n "$GIT_COMMON_DIR" ] && [ "$GIT_DIR" != "$GIT_COMMON_DIR" ]; then
    exit 0
fi
mahavishnu index repo --trigger git-event "$(pwd)" &
"""

# Pre-commit hook guards against hardcoded *_KEY / *_TOKEN / *_SECRET literals
# landing in any .mcp.json. No-op when the audit script is absent (so other
# repos without scripts/audit_no_secrets_in_mcp.py can still install hooks).
# `|| exit 1` propagates the audit's exit code so a violation blocks the commit.
# Phase 2 gate (Plan Task 2.2): findings.md ≤ 250 lines + validate_findings.py
# integrity check. Both gates are skipped when their inputs don't exist yet
# (early repo state) so other repos without the audit can still install.
PRE_COMMIT_CONTENT = """#!/bin/sh
# Managed by mahavishnu index install-hooks
# Remove with: mahavishnu index uninstall-hooks <path>
# Enforces .claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md §1.
if [ -f "scripts/audit_no_secrets_in_mcp.py" ]; then
    python3 scripts/audit_no_secrets_in_mcp.py || exit 1
fi
# Phase 2 gate: findings.md ≤ 250 lines + validate_findings.py
if [ -f "docs/audit-inventory/findings.md" ] && [ -f "scripts/validate_findings.py" ]; then
    test "$(wc -l < docs/audit-inventory/findings.md)" -le 250 || { echo "findings.md exceeds 250-line budget"; exit 1; }
    python3 scripts/validate_findings.py docs/audit-inventory/findings.md || exit 1
fi
"""

MAHAVISHNU_HEADER = "# Managed by mahavishnu index install-hooks"

_HOOK_NAMES = ("post-commit", "post-merge", "post-rewrite", "pre-commit")

# Map each hook to its template content.
_HOOK_TEMPLATES: dict[str, str] = {
    "post-commit": HOOK_CONTENT,
    "post-merge": HOOK_CONTENT,
    "post-rewrite": HOOK_CONTENT,
    "pre-commit": PRE_COMMIT_CONTENT,
}


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

        hook_file.write_text(_HOOK_TEMPLATES[hook_name])
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
