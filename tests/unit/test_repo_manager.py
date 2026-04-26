"""Tests for RepositoryManager."""

from pathlib import Path

import pytest
import yaml

import mahavishnu.core.repo_manager as repo_manager
from mahavishnu.core.repo_manager import RepositoryManager
from mahavishnu.core.repo_models import (
    Repository,
    RepositoryManifest,
    RepositoryMetadata,
)


@pytest.fixture
def sample_repos_path(tmp_path: Path) -> Path:
    """Create a sample ecosystem.yaml file."""
    repo1_path = tmp_path / "repo1"
    repo2_path = tmp_path / "repo2"
    repos_data = {
        "repos": [
            {
                "name": "test-repo-1",
                "package": "test_repo_1",
                "path": str(repo1_path),
                "nickname": "repo1",
                "nicknames": ["r1"],
                "tags": ["python-testing", "unit-test"],
                "description": "Test repository 1",
                "mcp": "native",
                "metadata": {
                    "version": "1.0.0",
                    "language": "python",
                    "dependencies": 5,
                },
            },
            {
                "name": "test-repo-2",
                "package": "test_repo_2",
                "path": str(repo2_path),
                "tags": ["python-testing", "integration"],  # Both repos share python-testing
                "description": "Test repository 2",
                "mcp": "3rd-party",
            },
        ],
    }

    repos_file = tmp_path / "ecosystem.yaml"
    with repos_file.open("w") as f:
        yaml.dump(repos_data, f)

    return repos_file


@pytest.mark.asyncio
async def test_load_repos(sample_repos_path: Path) -> None:
    """Test loading repository manifest."""
    manager = RepositoryManager(sample_repos_path)
    await manager.load()

    manifest = manager.get_manifest()
    assert isinstance(manifest, RepositoryManifest)
    assert len(manifest.repos) == 2
    assert manifest.version == "1.0"


@pytest.mark.asyncio
async def test_get_by_tag(sample_repos_path: Path) -> None:
    """Test getting repositories by tag."""
    manager = RepositoryManager(sample_repos_path)
    await manager.load()

    python_repos = manager.get_by_tag("python-testing")
    assert len(python_repos) == 2
    assert "test_repo_1" in python_repos
    assert "test_repo_2" in python_repos

    testing_repos = manager.get_by_tag("testing")
    assert len(testing_repos) == 0


@pytest.mark.asyncio
async def test_get_by_mcp_type(sample_repos_path: Path) -> None:
    """Test getting repositories by MCP type."""
    manager = RepositoryManager(sample_repos_path)
    await manager.load()

    native_repos = manager.get_by_mcp_type("native")
    assert len(native_repos) == 1
    assert "test_repo_1" in native_repos

    integration_repos = manager.get_by_mcp_type("3rd-party")
    assert len(integration_repos) == 1
    assert "test_repo_2" in integration_repos


@pytest.mark.asyncio
async def test_get_by_package(sample_repos_path: Path) -> None:
    """Test getting repository by package name."""
    manager = RepositoryManager(sample_repos_path)
    await manager.load()

    repo = manager.get_by_package("test_repo_1")
    assert repo is not None
    assert repo.name == "test-repo-1"
    assert repo.package == "test_repo_1"


@pytest.mark.asyncio
async def test_get_by_name(sample_repos_path: Path) -> None:
    """Test getting repository by name."""
    manager = RepositoryManager(sample_repos_path)
    await manager.load()

    repo = manager.get_by_name("test-repo-2")
    assert repo is not None
    assert repo.name == "test-repo-2"
    assert repo.package == "test_repo_2"


@pytest.mark.asyncio
async def test_filter_repos(sample_repos_path: Path) -> None:
    """Test filtering repositories by multiple criteria."""
    manager = RepositoryManager(sample_repos_path)
    await manager.load()

    # Filter by single tag
    results = manager.filter(tags=["python-testing"])
    assert len(results) == 2

    # Filter by multiple tags (AND)
    results = manager.filter(tags=["python-testing", "unit-test"])
    assert len(results) == 1
    assert results[0].package == "test_repo_1"

    # Filter by tag and MCP type
    results = manager.filter(tags=["python-testing"], mcp_type="native")
    assert len(results) == 1
    assert results[0].package == "test_repo_1"


@pytest.mark.asyncio
async def test_search_repos(sample_repos_path: Path) -> None:
    """Test searching repositories."""
    manager = RepositoryManager(sample_repos_path)
    await manager.load()

    # Search by name
    results = manager.search("test-repo-1")
    assert len(results) == 1
    assert results[0].package == "test_repo_1"

    # Search by package
    results = manager.search("test_repo_2")
    assert len(results) == 1
    assert results[0].name == "test-repo-2"

    # Search by description
    results = manager.search("Test repository")
    assert len(results) == 2

    # Search limit branch
    results = manager.search("Test repository", limit=1)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_cache_invalidation(sample_repos_path: Path) -> None:
    """Test cache invalidation."""
    manager = RepositoryManager(sample_repos_path)
    await manager.load()

    # First call - cache miss
    result1 = manager.get_by_tag("python-testing")
    assert len(result1) == 2

    # Second call - cache hit
    result2 = manager.get_by_tag("python-testing")
    assert len(result2) == 2

    # Invalidate cache
    manager.invalidate_cache()

    # Third call - cache miss again
    result3 = manager.get_by_tag("python-testing")
    assert len(result3) == 2


@pytest.mark.asyncio
async def test_get_by_nickname_and_repo_and_paths_and_language_filter(sample_repos_path: Path) -> None:
    manager = RepositoryManager(sample_repos_path)
    await manager.load()

    by_nickname = manager.get_by_nickname("r1")
    assert by_nickname is not None
    assert by_nickname.package == "test_repo_1"

    by_repo = manager.get_repo("repo1")
    assert by_repo is not None
    assert by_repo.package == "test_repo_1"

    all_paths = manager.get_all_paths()
    assert any(path.endswith("repo1") for path in all_paths)
    assert any(path.endswith("repo2") for path in all_paths)

    language_filtered = manager.filter(language="python")
    assert len(language_filtered) == 1
    assert language_filtered[0].package == "test_repo_1"

    no_match = manager.filter(tags=["python-testing", "missing-tag"])
    assert no_match == []


@pytest.mark.asyncio
async def test_validate_repos_exist_and_empty_helpers(sample_repos_path: Path) -> None:
    manager = RepositoryManager(sample_repos_path)
    await manager.load()

    missing = manager.validate_repos_exist()
    assert len(missing) == 2

    empty_manager = RepositoryManager(sample_repos_path)
    assert empty_manager.search("anything") == []
    assert empty_manager.validate_repos_exist() == []
    assert empty_manager.get_all_paths() == []
    empty_manager._build_indexes()
    with pytest.raises(RuntimeError, match="Manifest not loaded"):
        empty_manager.get_manifest()


@pytest.mark.asyncio
async def test_load_validation_and_parse_errors(tmp_path: Path) -> None:
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(":[", encoding="utf-8")
    manager = RepositoryManager(bad_yaml)
    with pytest.raises(ValueError, match="Invalid repository manifest"):
        await manager.load()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        repo_manager.yaml,
        "safe_load",
        lambda _content: (_ for _ in ()).throw(yaml.YAMLError("boom")),
    )
    try:
        manager2 = RepositoryManager(bad_yaml)
        with pytest.raises(ValueError, match="Failed to parse repository manifest"):
            await manager2.load()
    finally:
        monkeypatch.undo()

    invalid_manifest = tmp_path / "invalid.yaml"
    invalid_manifest.write_text(
        """
repos:
  - name: bad-repo
    package: bad_repo
    path: relative/path
    tags: ["python-testing"]
    description: Test repository
""",
        encoding="utf-8",
    )
    manager2 = RepositoryManager(invalid_manifest)
    with pytest.raises(ValueError, match="Invalid repository manifest"):
        await manager2.load()


def test_repository_validation() -> None:
    """Test Repository model validation."""
    # Valid repository
    repo = Repository(
        name="test-repo",
        package="test_repo",
        path="/tmp/test",
        tags=["python-testing", "unit-test"],
        description="Test repository",
        mcp="native",
    )
    assert repo.name == "test-repo"
    assert repo.mcp == "native"
    assert "mcp" in repo.tags  # Auto-added


def test_repository_validation_errors() -> None:
    """Test Repository model validation errors."""
    # Invalid name (has space)
    with pytest.raises(ValueError):
        Repository(
            name="test repo",
            package="test_repo",
            path="/tmp/test",
            tags=["python-testing"],
            description="Test",
        )

    # Invalid tag (uppercase)
    with pytest.raises(ValueError):
        Repository(
            name="test-repo",
            package="test_repo",
            path="/tmp/test",
            tags=["Python"],
            description="Test",
        )

    # Relative path
    with pytest.raises(ValueError):
        Repository(
            name="test-repo",
            package="test_repo",
            path="relative/path",
            tags=["python-testing"],
            description="Test",
        )

    # Native MCP with third-party tag
    with pytest.raises(ValueError):
        Repository(
            name="test-repo",
            package="test_repo",
            path="/tmp/test",
            tags=["python-mcp", "3rd-party"],
            description="Test",
            mcp="native",
        )


def test_repository_metadata() -> None:
    """Test RepositoryMetadata model."""
    metadata = RepositoryMetadata(
        version="1.0.0",
        language="python",
        min_python="3.11",
        dependencies=10,
    )
    assert metadata.version == "1.0.0"
    assert metadata.language == "python"
    assert metadata.min_python == "3.11"
    assert metadata.dependencies == 10
