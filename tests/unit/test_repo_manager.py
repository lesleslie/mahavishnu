"""Tests for RepositoryManager."""

from pathlib import Path

import pytest
import yaml

from mahavishnu.core.repo_manager import RepositoryManager
from mahavishnu.core.repo_models import (
    Repository,
    RepositoryManifest,
    RepositoryMetadata,
)


@pytest.fixture
def sample_repos_path(tmp_path: Path) -> Path:
    """Create a sample ecosystem.yaml file."""
    repos_data = {
        "repos": [
            {
                "name": "test-repo-1",
                "package": "test_repo_1",
                "path": "/tmp/test1",
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
                "path": "/tmp/test2",
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
    assert len(testing_repos) == 1
    assert "test_repo_1" in testing_repos


@pytest.mark.asyncio
async def test_get_by_mcp_type(sample_repos_path: Path) -> None:
    """Test getting repositories by MCP type."""
    manager = RepositoryManager(sample_repos_path)
    await manager.load()

    native_repos = manager.get_by_mcp_type("native")
    assert len(native_repos) == 1
    assert "test_repo_1" in native_repos

    integration_repos = manager.get_by_mcp_type("integration")
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

    # Native MCP with integration tag
    with pytest.raises(ValueError):
        Repository(
            name="test-repo",
            package="test_repo",
            path="/tmp/test",
            tags=["python-mcp", "integration"],
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
