"""Resolve the directory that holds the Bodai fleet checkouts.

mahavishnu is a **public** repository, so no tracked file may carry an
absolute path: an absolute path discloses the operator's account name and
local directory layout to anyone who clones the repo. The Bodai registry
therefore publishes paths relative to a "projects root" and declares the
rule for resolving that root back to a directory.

This module is the single implementation of that rule, so every consumer
resolves the root the same way. The registry's generator keeps its own
copy of the renderer so it stays standalone-runnable (stdlib plus PyYAML);
``tests/unit/test_bodai_paths.py`` pins the two to agree.

Resolution order (first hit wins):

  1. ``$BODAI_PROJECTS_ROOT`` — explicit operator override.
  2. The repository's own location — this repo sits at
     ``<projects root>/mahavishnu/``. A git *worktree* does not define the
     root: the fleet's worktree bucket holds directories named after fleet
     repos, and a root resolved to the bucket would send every lookup to a
     worktree instead of the primary checkout.
  3. ``~/Projects`` — the standard developer layout.
"""

from __future__ import annotations

import os
from pathlib import Path

# Consumer-side override for the projects root. The registry's Path column
# is relative to it; see ``resolve_projects_root``.
PROJECTS_ROOT_ENV_VAR = "BODAI_PROJECTS_ROOT"
DEFAULT_PROJECTS_DIRNAME = "Projects"

# This repo's own directory name. Its parent is the projects root.
REPO_DIRNAME = "mahavishnu"

__all__ = [
    "DEFAULT_PROJECTS_DIRNAME",
    "PROJECTS_ROOT_ENV_VAR",
    "REPO_DIRNAME",
    "render_repo_path",
    "resolve_projects_root",
]


def _is_primary_checkout(repo_root: Path) -> bool:
    """Whether `repo_root` is a primary git checkout rather than a worktree.

    A git worktree's ``.git`` is a *file* that points at the real
    repository; a primary checkout's is a *directory*. The fleet's
    worktree bucket (``~/.local/state/mahavishnu/worktrees/``) holds
    directories named after fleet repos, so the name alone cannot tell a
    projects root from the bucket -- but the ``.git`` entry can.
    """
    return (repo_root / ".git").is_dir()


def resolve_projects_root(repo_root: Path | None = None) -> Path:
    """Resolve the projects root the registry's Path column is relative to.

    Args:
        repo_root: The repository checkout to derive the root from. Defaults
            to this repository's own location. A worktree does not define a
            root; see the module docstring.

    Returns:
        The projects root. Never raises: when nothing can be resolved the
        current working directory is returned, and every repo path derived
        from it simply will not exist.
    """
    override = os.environ.get(PROJECTS_ROOT_ENV_VAR)
    if override:
        return Path(override).expanduser()

    base = repo_root if repo_root is not None else Path(__file__).resolve().parent.parent
    if base.name == REPO_DIRNAME and _is_primary_checkout(base):
        return base.parent

    try:
        home = Path.home()
    except RuntimeError:
        return Path.cwd()
    return home / DEFAULT_PROJECTS_DIRNAME


def render_repo_path(repo_path: str, root: Path | None) -> str:
    """Render a repo path for publication.

    Root-relative when the repo lives under `root`; otherwise the directory
    name alone, so a repo kept outside the root can never leak the layout
    that holds it.

    Args:
        repo_path: The repo's path, absolute or relative.
        root: The projects root to render against. ``None`` renders only the
            directory name.

    Returns:
        A publishable path, always ending in a slash.
    """
    candidate = Path(repo_path)
    if root is not None:
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            pass
        else:
            return f"{relative.as_posix()}/"
    return f"{candidate.name}/"
