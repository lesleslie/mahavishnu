"""Focused tests for repository nickname alias handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from mahavishnu.core.repo_manager import RepositoryManager
from mahavishnu.core.repo_nicknames import get_repo_nicknames, normalize_nicknames


def test_normalize_nicknames_merges_legacy_and_aliases() -> None:
    """Legacy nickname and multi-alias nicknames should be merged and deduped."""
    assert normalize_nicknames("vishnu", ["vishnu", "vish"]) == ["vishnu", "vish"]


def test_get_repo_nicknames_supports_both_config_shapes() -> None:
    """Repository dicts should expose all aliases consistently."""
    repo = {
        "name": "mahavishnu",
        "nickname": "vishnu",
        "nicknames": ["vishnu", "vish"],
    }

    assert get_repo_nicknames(repo) == ["vishnu", "vish"]


@pytest.mark.asyncio
async def test_repository_manager_resolves_nickname_alias(tmp_path: Path) -> None:
    """Repository manager lookups should accept configured nickname aliases."""
    repo_path = tmp_path / "mahavishnu"
    repo_path.mkdir()

    manifest_path = tmp_path / "repos.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "repos:",
                "  - name: mahavishnu",
                "    package: mahavishnu",
                f"    path: {repo_path}",
                "    nickname: vishnu",
                "    nicknames: [vishnu, vish]",
                "    role: orchestrator",
                "    tags: [orchestrator, python]",
                "    description: Multi-engine workflow orchestration",
            ]
        )
    )

    manager = RepositoryManager(manifest_path)
    await manager.load()

    assert manager.get_by_nickname("vish") is not None
    assert manager.get_repo("vish").name == "mahavishnu"
    assert manager.get_by_name("vishnu").name == "mahavishnu"
