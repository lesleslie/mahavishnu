"""Guard against drift between the Mahavishnu registry files.

settings/ecosystem.yaml is canonical (read by load_repos() at
mahavishnu/core/bootstrap.py:187). settings/repos.yaml is legacy but still
consumed by mahavishnu/repo_cli.py. These assertions exist because the two
files diverged silently for four months: canonical held 8 repos while the
legacy file held 32, so 24 repositories were invisible to list_repos,
role-based routing, and tag sweeps while both files looked authoritative.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_DIR = REPO_ROOT / "settings"
ECOSYSTEM_PATH = SETTINGS_DIR / "ecosystem.yaml"
LEGACY_PATH = SETTINGS_DIR / "repos.yaml"

NEW_SERVERS = ("archive-org-mcp", "medium-mcp", "scapy-mcp")


def _load(path: Path) -> dict[str, Any]:
    with path.open() as handle:
        return yaml.safe_load(handle)


def _repos(path: Path) -> list[dict[str, Any]]:
    return _load(path)["repos"]


def _names(path: Path) -> set[str]:
    return {repo["name"] for repo in _repos(path)}


def _role_names(path: Path) -> set[str]:
    return {role["name"] for role in _load(path).get("roles", [])}


@pytest.mark.unit
class TestNewServerRegistration:
    """The three new MCP servers must be registered in the canonical manifest."""

    @pytest.mark.parametrize("server_name", NEW_SERVERS)
    def test_new_server_is_registered(self, server_name: str) -> None:
        assert server_name in _names(ECOSYSTEM_PATH)

    @pytest.mark.parametrize("server_name", NEW_SERVERS)
    def test_new_server_not_added_to_legacy(self, server_name: str) -> None:
        """repos.yaml is being deprecated; new entries must not be written there."""
        assert server_name not in _names(LEGACY_PATH)


@pytest.mark.unit
class TestRegistryIntegrity:
    """Structural invariants over the canonical manifest."""

    def test_every_path_exists(self) -> None:
        """A registered repo whose path is gone will fail routing at runtime."""
        missing = [
            (repo["name"], repo["path"])
            for repo in _repos(ECOSYSTEM_PATH)
            if not Path(repo["path"]).expanduser().is_dir()
        ]
        assert missing == [], f"registered paths do not exist: {missing}"

    def test_every_role_is_in_taxonomy(self) -> None:
        """A repo with an unknown role matches no routing filter and is silently
        unreachable — it neither errors nor appears in role-scoped sweeps."""
        taxonomy = _role_names(ECOSYSTEM_PATH)
        offenders = {
            repo["name"]: repo["role"]
            for repo in _repos(ECOSYSTEM_PATH)
            if repo.get("role") not in taxonomy
        }
        assert offenders == {}, f"roles absent from taxonomy: {offenders}"

    def test_legacy_roles_are_migratable(self) -> None:
        """Every role used in the legacy file must exist in the canonical
        taxonomy, or Task 5's migration will introduce unroutable entries."""
        taxonomy = _role_names(ECOSYSTEM_PATH)
        legacy_roles = {repo.get("role") for repo in _repos(LEGACY_PATH)}
        assert legacy_roles <= taxonomy, (
            f"legacy roles missing from taxonomy: {sorted(legacy_roles - taxonomy)}"
        )

    def test_canonical_is_superset_of_legacy(self) -> None:
        """Anything in the legacy file must also be in canonical, or it is
        invisible to the runtime — which read canonical only."""
        stranded = _names(LEGACY_PATH) - _names(ECOSYSTEM_PATH)
        assert stranded == set(), (
            f"{len(stranded)} repos are in repos.yaml but not ecosystem.yaml, so "
            f"the runtime cannot see them: {sorted(stranded)}"
        )
