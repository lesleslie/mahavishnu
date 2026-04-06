"""Tests for repository validation models.

Tests cover:
- RepositoryMetadata defaults and field validation
- Repository creation, path validation, tag validation, name validation
- MCP consistency validator (auto-tag, conflict detection)
- Nickname normalization integration
- RepositoryManifest uniqueness constraints
"""

import pytest
from pathlib import Path

from mahavishnu.core.repo_models import (
    Repository,
    RepositoryManifest,
    RepositoryMetadata,
)


# ============================================================================
# RepositoryMetadata Tests
# ============================================================================


class TestRepositoryMetadataDefaults:
    def test_defaults(self):
        meta = RepositoryMetadata()
        assert meta.version == "0.0.0"
        assert meta.language == "python"
        assert meta.min_python is None
        assert meta.dependencies == 0
        assert meta.last_validated is not None

    def test_custom_values(self):
        meta = RepositoryMetadata(
            version="1.2.3",
            language="go",
            min_python="3.11",
            dependencies=15,
        )
        assert meta.version == "1.2.3"
        assert meta.language == "go"
        assert meta.min_python == "3.11"
        assert meta.dependencies == 15

    def test_dependencies_must_be_non_negative(self):
        with pytest.raises(Exception):
            RepositoryMetadata(dependencies=-1)


# ============================================================================
# Repository Tests
# ============================================================================


class TestRepositoryCreation:
    def test_minimal_valid(self):
        repo = Repository(
            name="my-repo",
            package="my_repo",
            path=Path("/tmp/my-repo"),
            tags=["python"],
            description="A test repo",
        )
        assert repo.name == "my-repo"
        assert repo.package == "my_repo"
        assert repo.tags == ["python"]
        assert repo.nickname is None
        assert repo.nicknames == []
        assert repo.mcp is None
        assert repo.metadata is None

    def test_full_creation(self):
        repo = Repository(
            name="mahavishnu",
            package="mahavishnu",
            path=Path("/Users/les/Projects/mahavishnu"),
            nickname="vishnu",
            nicknames=["mv", "orchestrator"],
            role="orchestrator",
            tags=["python", "mcp"],
            description="Orchestration platform",
            mcp="native",
        )
        assert repo.role == "orchestrator"
        assert repo.mcp == "native"


class TestRepositoryPathValidation:
    def test_absolute_path_accepted(self):
        repo = Repository(
            name="test",
            package="test",
            path=Path("/tmp/test"),
            tags=["python"],
            description="test",
        )
        assert repo.path.is_absolute()

    def test_relative_path_rejected(self):
        with pytest.raises(Exception, match="absolute"):
            Repository(
                name="test",
                package="test",
                path=Path("relative/path"),
                tags=["python"],
                description="test",
            )


class TestRepositoryNameValidation:
    def test_valid_names(self):
        valid_names = [
            "my-repo",
            "repo123",
            "a",
            "my-cool-repo",
            "test2",
        ]
        for name in valid_names:
            repo = Repository(
                name=name,
                package="test",
                path=Path("/tmp/test"),
                tags=["python"],
                description="test",
            )
            assert repo.name == name

    def test_rejects_empty_name(self):
        with pytest.raises(Exception):
            Repository(
                name="",
                package="test",
                path=Path("/tmp/test"),
                tags=["python"],
                description="test",
            )

    def test_rejects_spaces(self):
        with pytest.raises(Exception):
            Repository(
                name="my repo",
                package="test",
                path=Path("/tmp/test"),
                tags=["python"],
                description="test",
            )

    def test_rejects_uppercase(self):
        with pytest.raises(Exception):
            Repository(
                name="MyRepo",
                package="test",
                path=Path("/tmp/test"),
                tags=["python"],
                description="test",
            )

    def test_rejects_too_long(self):
        with pytest.raises(Exception):
            Repository(
                name="x" * 101,
                package="test",
                path=Path("/tmp/test"),
                tags=["python"],
                description="test",
            )


class TestRepositoryTagValidation:
    def test_valid_tags(self):
        repo = Repository(
            name="test",
            package="test",
            path=Path("/tmp/test"),
            tags=["python", "mcp", "backend-ai"],
            description="test",
        )
        assert len(repo.tags) == 3

    def test_rejects_empty_tags_list(self):
        with pytest.raises(Exception):
            Repository(
                name="test",
                package="test",
                path=Path("/tmp/test"),
                tags=[],
                description="test",
            )

    def test_rejects_invalid_tag_format(self):
        with pytest.raises(Exception, match="Invalid tag"):
            Repository(
                name="test",
                package="test",
                path=Path("/tmp/test"),
                tags=["UPPERCASE"],
                description="test",
            )

    def test_rejects_tag_with_spaces(self):
        with pytest.raises(Exception, match="Invalid tag"):
            Repository(
                name="test",
                package="test",
                path=Path("/tmp/test"),
                tags=["has space"],
                description="test",
            )

    def test_max_10_tags(self):
        with pytest.raises(Exception):
            Repository(
                name="test",
                package="test",
                path=Path("/tmp/test"),
                tags=[f"tag{i}" for i in range(11)],
                description="test",
            )


class TestRepositoryMcpConsistency:
    def test_native_mcp_auto_adds_tag(self):
        repo = Repository(
            name="test",
            package="test",
            path=Path("/tmp/test"),
            tags=["python"],
            description="test",
            mcp="native",
        )
        assert "mcp" in repo.tags

    def test_third_party_mcp_auto_adds_tag(self):
        repo = Repository(
            name="test",
            package="test",
            path=Path("/tmp/test"),
            tags=["python"],
            description="test",
            mcp="3rd-party",
        )
        assert "mcp" in repo.tags

    def test_native_rejects_3rd_party_tag(self):
        with pytest.raises(Exception, match="cannot have '3rd-party' tag"):
            Repository(
                name="test",
                package="test",
                path=Path("/tmp/test"),
                tags=["python", "3rd-party"],
                description="test",
                mcp="native",
            )

    def test_third_party_rejects_native_tag(self):
        with pytest.raises(Exception, match="cannot have 'native' tag"):
            Repository(
                name="test",
                package="test",
                path=Path("/tmp/test"),
                tags=["python", "native"],
                description="test",
                mcp="3rd-party",
            )


class TestRepositoryNicknameIntegration:
    def test_nicknames_deduplicated(self):
        repo = Repository(
            name="test",
            package="test",
            path=Path("/tmp/test"),
            nickname="primary",
            nicknames=["primary", "alt"],
            tags=["python"],
            description="test",
        )
        # Deduplicated via normalize_nicknames
        assert repo.nicknames == ["primary", "alt"]

    def test_nickname_set_from_first_nicknames(self):
        repo = Repository(
            name="test",
            package="test",
            path=Path("/tmp/test"),
            nicknames=["alpha", "beta"],
            tags=["python"],
            description="test",
        )
        assert repo.nickname == "alpha"


# ============================================================================
# RepositoryManifest Tests
# ============================================================================


def _make_repo(name: str, package: str | None = None, path: str | None = None) -> Repository:
    """Helper to create a minimal Repository."""
    return Repository(
        name=name,
        package=package or name.replace("-", "_"),
        path=Path(path or f"/tmp/{name}"),
        tags=["python"],
        description=f"Test repo {name}",
    )


class TestRepositoryManifest:
    def test_valid_manifest(self):
        manifest = RepositoryManifest(repos=[
            _make_repo("repo-a"),
            _make_repo("repo-b"),
        ])
        assert len(manifest.repos) == 2
        assert manifest.version == "1.0"

    def test_rejects_empty_repos(self):
        with pytest.raises(Exception):
            RepositoryManifest(repos=[])

    def test_rejects_duplicate_paths(self):
        with pytest.raises(Exception, match="Duplicate repository path"):
            RepositoryManifest(repos=[
                _make_repo("repo-a", path="/tmp/same"),
                _make_repo("repo-b", path="/tmp/same"),
            ])

    def test_rejects_duplicate_names(self):
        with pytest.raises(Exception, match="Duplicate repository name"):
            RepositoryManifest(repos=[
                _make_repo("same-name", package="pkg_a", path="/tmp/a"),
                _make_repo("same-name", package="pkg_b", path="/tmp/b"),
            ])

    def test_rejects_duplicate_packages(self):
        with pytest.raises(Exception, match="Duplicate package name"):
            RepositoryManifest(repos=[
                _make_repo("repo-a", package="same_pkg", path="/tmp/a"),
                _make_repo("repo-b", package="same_pkg", path="/tmp/b"),
            ])
