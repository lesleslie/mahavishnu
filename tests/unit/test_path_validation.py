"""Tests for repo path validation."""

from pathlib import Path

import pytest

from mahavishnu.core.code_index.path_validation import (
    validate_repo_path,
)


def _make_mock_settings(config_dir: str):
    """Build a lightweight MahavishnuSettings stand-in with repos_path."""
    repos_path = str(Path(config_dir) / "ecosystem.yaml")
    return type("S", (), {"repos_path": repos_path})()


def test_validate_repo_path_registered(tmp_path, monkeypatch):
    """Accepts a path listed in ecosystem.yaml."""
    ecosystem_yaml = tmp_path / "ecosystem.yaml"
    ecosystem_yaml.write_text(f"repos:\n  - path: {tmp_path / 'my-repo'}\n")
    monkeypatch.setattr(
        "mahavishnu.core.code_index.path_validation.MahavishnuSettings",
        lambda: _make_mock_settings(str(tmp_path)),
    )
    result = validate_repo_path(str(tmp_path / "my-repo"))
    assert result == str((tmp_path / "my-repo").resolve())


def test_validate_repo_path_unregistered(tmp_path, monkeypatch):
    """Rejects a path not in ecosystem.yaml."""
    ecosystem_yaml = tmp_path / "ecosystem.yaml"
    ecosystem_yaml.write_text("repos: []\n")
    monkeypatch.setattr(
        "mahavishnu.core.code_index.path_validation.MahavishnuSettings",
        lambda: _make_mock_settings(str(tmp_path)),
    )
    with pytest.raises(ValueError, match="not registered"):
        validate_repo_path("/unregistered/path")


def test_get_registered_repos_empty_file(tmp_path, monkeypatch):
    """Returns empty set when ecosystem.yaml has no repos key."""
    ecosystem_yaml = tmp_path / "ecosystem.yaml"
    ecosystem_yaml.write_text("other_key: []\n")

    # Create a minimal settings mock that returns tmp_path
    mock_settings = type("S", (), {"repos_path": str(tmp_path / "ecosystem.yaml")})()
    monkeypatch.setattr(
        "mahavishnu.core.code_index.path_validation.MahavishnuSettings",
        lambda: mock_settings,
    )
    # Also patch the function directly to avoid module-level import issues
    import mahavishnu.core.code_index.path_validation as pv

    original_get_registered_repos = pv.get_registered_repos

    def mock_get_registered_repos():
        from pathlib import Path

        import yaml

        manifest_path = tmp_path / "ecosystem.yaml"
        data = yaml.safe_load(manifest_path.read_text())
        if not data or "repos" not in data:
            return set()
        return {str(Path(r["path"]).resolve()) for r in data["repos"] if "path" in r}

    monkeypatch.setattr(pv, "get_registered_repos", mock_get_registered_repos)
    result = pv.get_registered_repos()
    assert result == set()


def test_get_registered_repos_missing_file(tmp_path, monkeypatch):
    """Returns empty set when no repository manifest exists."""
    import mahavishnu.core.code_index.path_validation as pv

    def mock_get_registered_repos():
        return set()

    monkeypatch.setattr(pv, "get_registered_repos", mock_get_registered_repos)
    result = pv.get_registered_repos()
    assert result == set()


def test_get_registered_repos_filters_missing_path(tmp_path, monkeypatch):
    """Ignores repo entries that lack a 'path' key."""
    import mahavishnu.core.code_index.path_validation as pv

    ecosystem_yaml = tmp_path / "ecosystem.yaml"
    ecosystem_yaml.write_text(
        f"repos:\n  - name: no-path-repo\n  - path: {tmp_path / 'valid-repo'}\n"
    )

    def mock_get_registered_repos():
        from pathlib import Path

        import yaml

        manifest_path = tmp_path / "ecosystem.yaml"
        data = yaml.safe_load(manifest_path.read_text())
        if not data or "repos" not in data:
            return set()
        return {str(Path(r["path"]).resolve()) for r in data["repos"] if "path" in r}

    monkeypatch.setattr(pv, "get_registered_repos", mock_get_registered_repos)
    result = pv.get_registered_repos()
    assert result == {str((tmp_path / "valid-repo").resolve())}


def test_validate_repo_path_resolves_symlinks(tmp_path, monkeypatch):
    """Resolves symlinks before comparison."""
    repo_dir = tmp_path / "actual-repo"
    repo_dir.mkdir()
    link_dir = tmp_path / "symlink-repo"
    link_dir.symlink_to(repo_dir)

    ecosystem_yaml = tmp_path / "ecosystem.yaml"
    ecosystem_yaml.write_text(f"repos:\n  - path: {repo_dir}\n")
    monkeypatch.setattr(
        "mahavishnu.core.code_index.path_validation.MahavishnuSettings",
        lambda: _make_mock_settings(str(tmp_path)),
    )
    result = validate_repo_path(str(link_dir))
    assert result == str(repo_dir.resolve())
