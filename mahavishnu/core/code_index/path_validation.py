"""Validate repo paths against the registered repository catalog."""

from __future__ import annotations

from pathlib import Path

from mahavishnu.core.config import MahavishnuSettings


def get_registered_repos() -> set[str]:
    """Load registered repo paths from settings/repos.yaml.

    Returns absolute paths as strings.
    """
    settings = MahavishnuSettings()
    settings_dir = Path(settings.repos_path).parent
    repos_path = settings_dir / "repos.yaml"
    if not repos_path.exists():
        return set()
    import yaml

    data = yaml.safe_load(repos_path.read_text())
    if not data or "repos" not in data:
        return set()
    return {str(Path(r["path"]).resolve()) for r in data["repos"] if "path" in r}


def validate_repo_path(repo_path: str) -> str:
    """Validate that a repo path is registered.

    Returns the resolved absolute path.

    Raises:
        ValueError: If the path is not registered in repos.yaml.
    """
    resolved = str(Path(repo_path).resolve())
    registered = get_registered_repos()
    if resolved not in registered:
        raise ValueError(
            f"Repo path '{repo_path}' is not registered in repos.yaml. "
            f"Registered paths: {sorted(registered)}"
        )
    return resolved
