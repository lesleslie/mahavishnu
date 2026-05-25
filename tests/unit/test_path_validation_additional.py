"""Additional tests for repository path validation."""

from __future__ import annotations

from pathlib import Path

import pytest

import mahavishnu.core.code_index.path_validation as path_validation


class _Settings:
    def __init__(self, repos_path: str):
        self.repos_path = repos_path


def _patch_settings(monkeypatch, repos_yaml: Path):
    monkeypatch.setattr(
        path_validation,
        "MahavishnuSettings",
        lambda: _Settings(str(repos_yaml)),
    )


def test_get_registered_repos_missing_manifest(tmp_path, monkeypatch):
    _patch_settings(monkeypatch, tmp_path / "missing.yaml")

    assert path_validation.get_registered_repos() == set()


def test_get_registered_repos_empty_manifest(tmp_path, monkeypatch):
    repos_yaml = tmp_path / "ecosystem.yaml"
    repos_yaml.write_text("other_key: true\n")
    _patch_settings(monkeypatch, repos_yaml)

    assert path_validation.get_registered_repos() == set()


def test_get_registered_repos_filters_missing_path(tmp_path, monkeypatch):
    repos_yaml = tmp_path / "ecosystem.yaml"
    valid_repo = tmp_path / "repo-a"
    repos_yaml.write_text(f"repos:\n  - name: missing-path\n  - path: {valid_repo}\n")
    _patch_settings(monkeypatch, repos_yaml)

    assert path_validation.get_registered_repos() == {str(valid_repo.resolve())}


def test_validate_repo_path_accepts_registered_repo(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo-a"
    repo_dir.mkdir()
    repos_yaml = tmp_path / "ecosystem.yaml"
    repos_yaml.write_text(f"repos:\n  - path: {repo_dir}\n")
    _patch_settings(monkeypatch, repos_yaml)

    assert path_validation.validate_repo_path(str(repo_dir)) == str(repo_dir.resolve())


def test_validate_repo_path_resolves_symlink(tmp_path, monkeypatch):
    repo_dir = tmp_path / "real-repo"
    repo_dir.mkdir()
    link_dir = tmp_path / "link-repo"
    link_dir.symlink_to(repo_dir)

    repos_yaml = tmp_path / "ecosystem.yaml"
    repos_yaml.write_text(f"repos:\n  - path: {repo_dir}\n")
    _patch_settings(monkeypatch, repos_yaml)

    assert path_validation.validate_repo_path(str(link_dir)) == str(repo_dir.resolve())


def test_validate_repo_path_rejects_unregistered(tmp_path, monkeypatch):
    repos_yaml = tmp_path / "ecosystem.yaml"
    repos_yaml.write_text("repos: []\n")
    _patch_settings(monkeypatch, repos_yaml)

    with pytest.raises(ValueError, match="not registered"):
        path_validation.validate_repo_path("/unregistered/path")
