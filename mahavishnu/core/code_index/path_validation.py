"""Validate repo paths against the registered repository catalog."""

from __future__ import annotations

from pathlib import Path

from mahavishnu.core.config import MahavishnuSettings


def get_registered_repos() -> set[str]:
    """Load registered repo paths from settings/ecosystem.yaml.

    Returns absolute paths as strings.
    """
    from mahavishnu.core.config import MahavishnuSettings

    settings = MahavishnuSettings()
    # Resolve relative to project directory, not cwd
    settings_dir = Path(__file__).parent.parent.parent.parent / "settings"
    ecosystem_path = settings_dir / "ecosystem.yaml"
    repos_path = settings_dir / "repos.yaml"

    repos_path = settings_dir / "repos.yaml"
    ecosystem_path = settings_dir / "ecosystem.yaml"

    # repos.yaml is the full catalog; ecosystem.yaml is core-only
    if repos_path.exists():
        manifest_path = repos_path
    elif ecosystem_path.exists():
        manifest_path = ecosystem_path
    else:
        return set()
    import yaml

    data = yaml.safe_load(manifest_path.read_text())
    if not data or "repos" not in data:
        return set()
    return {str(Path(r["path"]).resolve()) for r in data["repos"] if "path" in r}


def validate_repo_path(repo_path: str) -> str:
    """Validate that a repo path is registered.

    Returns the resolved absolute path.

    Raises:
        ValueError: If the path is not registered in ecosystem.yaml.
    """
    resolved = str(Path(repo_path).resolve())
    registered = get_registered_repos()
    if resolved not in registered:
        raise ValueError(
            f"Repo path '{repo_path}' is not registered in ecosystem.yaml. "
            f"Registered paths: {sorted(registered)}"
        )
    return resolved
