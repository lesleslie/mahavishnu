"""XDG Base Directory compliant path management.

This module provides XDG-compliant paths for data, configuration, cache,
and state directories using the platformdirs library.

References:
- XDG Base Directory Specification: https://specifications.freedesktop.org/basedir-spec/basedir-spec-latest.html
- platformdirs: https://github.com/platformdirs/platformdirs
- ADR 015: Worktree and Cache Storage Architecture (docs/adr/015-*)
"""

import os
from pathlib import Path
from typing import Final

from platformdirs import PlatformDirs

# XDG-compliant directory paths
_dirs: Final[PlatformDirs] = PlatformDirs(
    appname="mahavishnu",
    version="0.3.0",
    ensure_exists=True,
)

# Public path constants
DATA_DIR: Final[Path] = Path(_dirs.user_data_dir)
CONFIG_DIR: Final[Path] = Path(_dirs.user_config_dir)
CACHE_DIR: Final[Path] = Path(_dirs.user_cache_dir)
STATE_DIR: Final[Path] = Path(_dirs.user_state_dir)
RUNTIME_DIR: Final[Path] = Path(_dirs.user_runtime_dir)

LOG_DIR: Final[Path] = STATE_DIR / "logs"
AUDIT_DIR: Final[Path] = STATE_DIR / "audit"


def ensure_directories() -> None:
    """Ensure all XDG directories exist.

    Creates the following directories if they don't exist:
    - DATA_DIR
    - CONFIG_DIR
    - CACHE_DIR
    - STATE_DIR
    - LOG_DIR
    - AUDIT_DIR
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def get_data_path(*path_parts: str) -> Path:
    """Get XDG-compliant data directory path.

    Args:
        *path_parts: Path components to join with DATA_DIR

    Returns:
        Path to data file/directory

    Examples:
        >>> get_data_path("events.db")
        Path('~/.local/share/mahavishnu/events.db')
        >>> get_data_path("metrics", "daily.json")
        Path('~/.local/share/mahavishnu/metrics/daily.json')
    """
    return DATA_DIR.joinpath(*path_parts)


def get_config_path(*path_parts: str) -> Path:
    """Get XDG-compliant config directory path.

    Args:
        *path_parts: Path components to join with CONFIG_DIR

    Returns:
        Path to config file/directory

    Examples:
        >>> get_config_path("mahavishnu.yaml")
        Path('~/.config/mahavishnu/mahavishnu.yaml')
    """
    return CONFIG_DIR.joinpath(*path_parts)


def get_cache_path(*path_parts: str) -> Path:
    """Get XDG-compliant cache directory path.

    Args:
        *path_parts: Path components to join with CACHE_DIR

    Returns:
        Path to cache file/directory

    Examples:
        >>> get_cache_path("embeddings", "model.onnx")
        Path('~/.cache/mahavishnu/embeddings/model.onnx')
    """
    return CACHE_DIR.joinpath(*path_parts)


def get_state_path(*path_parts: str) -> Path:
    """Get XDG-compliant state directory path.

    Args:
        *path_parts: Path components to join with STATE_DIR

    Returns:
        Path to state file/directory

    Examples:
        >>> get_state_path("learning.db")
        Path('~/.local/state/mahavishnu/learning.db')
    """
    return STATE_DIR.joinpath(*path_parts)


def get_log_path(*path_parts: str) -> Path:
    """Get XDG-compliant log directory path.

    Args:
        *path_parts: Path components to join with LOG_DIR

    Returns:
        Path to log file

    Examples:
        >>> get_log_path("app.log")
        Path('~/.local/state/mahavishnu/logs/app.log')
    """
    return LOG_DIR.joinpath(*path_parts)


def get_audit_path(*path_parts: str) -> Path:
    """Get XDG-compliant audit log directory path.

    Args:
        *path_parts: Path components to join with AUDIT_DIR

    Returns:
        Path to audit log file

    Examples:
        >>> get_audit_path("audit.log")
        Path('~/.local/state/mahavishnu/audit/audit.log')
    """
    return AUDIT_DIR.joinpath(*path_parts)


def get_worktree_base_path() -> Path:
    """Return the canonical worktree base path.

    ALL worktree creation, lookup, and validation paths in mahavishnu
    must resolve through this helper. Do not read MAHAVISHNU_AUTO_WORKTREE_ROOT
    directly from any other location.

    Resolution order (ADR 015 v4 §1, §9):
      1. ``MAHAVISHNU_WORKTREE_BASE_PATH`` (canonical, v4+)
      2. ``MAHAVISHNU_AUTO_WORKTREE_ROOT`` (legacy, 1-release alias)
      3. Default: ``Path.home() / "worktrees"`` (preserves current behavior)

    The default is intentionally NOT XDG-correct yet; future work (Phase
    2/3) may migrate to ``DATA_DIR / "worktrees"`` once the per-MCP venv
    registry lands and the workspace convention stabilizes.

    Returns:
        Resolved, absolute Path to the worktree base directory.

    Examples:
        >>> get_worktree_base_path()
        PosixPath('/Users/les/worktrees')
    """
    explicit = os.environ.get("MAHAVISHNU_WORKTREE_BASE_PATH")
    if explicit:
        return Path(explicit).expanduser().resolve()
    legacy = os.environ.get("MAHAVISHNU_AUTO_WORKTREE_ROOT")
    if legacy:
        return Path(legacy).expanduser().resolve()
    return (Path.home() / "worktrees").resolve()


def get_worktree_path(*path_parts: str) -> Path:
    """Get a path under the worktree base.

    Equivalent to ``get_worktree_base_path() / *path_parts`` but resolves
    once and follows the same resolution order as
    ``get_worktree_base_path``.

    Args:
        *path_parts: Path components to join with the worktree base.

    Returns:
        Resolved, absolute Path to the per-worktree subdirectory.

    Examples:
        >>> get_worktree_path("mahavishnu", "feature-auth")
        PosixPath('/Users/les/worktrees/mahavishnu/feature-auth')
    """
    return get_worktree_base_path().joinpath(*path_parts)


# Legacy path migration utilities
def migrate_legacy_data(legacy_path: str | Path, new_path: str | Path) -> bool:
    """Migrate data from legacy path to XDG-compliant path.

    Args:
        legacy_path: Old (non-XDG) path
        new_path: New XDG-compliant path

    Returns:
        True if migration occurred, False otherwise

    Examples:
        >>> migrate_legacy_data("data/events.db", get_data_path("events.db"))
        True
    """
    legacy = Path(legacy_path)
    new = Path(new_path)

    if not legacy.exists():
        return False

    if new.exists():
        # Don't overwrite existing data
        return False

    # Ensure parent directory exists
    new.parent.mkdir(parents=True, exist_ok=True)

    # Copy data to new location
    if legacy.is_file():
        import shutil

        shutil.copy2(legacy, new)
    else:
        import shutil

        shutil.copytree(legacy, new, dirs_exist_ok=True)

    return True
