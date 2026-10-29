"""Tests for scripts/audit_cli_inventory.py.

Per Bodai CLI Audit Phase 0 Task 0.1 — verify that inventory_one_repo
returns the per-command schema required by the Phase 1 inventory
subagents and the Phase 7 quarterly staleness cadence.

The script also has to stay publishable: mahavishnu is a public repository,
so the script must not hardcode one machine's directory layout.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.audit_cli_inventory import (
    CORE_REPOS,
    ENTRY_POINTS,
    inventory_one_repo,
    resolve_repo_path,
)
from scripts.bodai_paths import PROJECTS_ROOT_ENV_VAR

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "audit_cli_inventory.py"


@pytest.fixture(autouse=True)
def _clear_projects_root_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may inherit a projects-root override from the environment."""
    monkeypatch.delenv(PROJECTS_ROOT_ENV_VAR, raising=False)


def test_inventory_mahavishnu_returns_per_command_fields(tmp_path):
    out = tmp_path / "mahavishnu-cli-inventory.json"
    # Use this repo's own checkout (works inside the worktree where the
    # inventory script lives); the production CLI resolves the canonical
    # <projects root>/mahavishnu path itself.
    repo_path = str(Path(__file__).resolve().parents[2])
    data = inventory_one_repo("mahavishnu", repo_path, out)
    assert data["repo"] == "mahavishnu"
    assert "commands" in data
    assert isinstance(data["commands"], list)
    # Per-command schema (every command must have these keys)
    for cmd in data["commands"]:
        assert set(cmd.keys()) >= {
            "command_path",
            "module",
            "function",
            "short_help",
            "tests_present",
            "staleness_verdict",
        }


class TestCoreRepos:
    """The inventory covers the Bodai core set — six repos, never seven."""

    def test_is_exactly_the_six_core_repositories(self) -> None:
        assert set(CORE_REPOS) == {
            "mahavishnu",
            "akosha",
            "session-buddy",
            "crackerjack",
            "oneiric",
            "mcp-common",
        }

    def test_does_not_inventory_a_phantom_repo(self) -> None:
        """A stale repo name silently inventories the wrong package.

        ``~/Projects/mcp`` does not exist, so the import fell through to the
        installed FastMCP SDK and the script recorded *its* CLI as a fleet
        repo's surface. The repo list must not name a repo that is not
        there.
        """
        assert "mcp" not in CORE_REPOS

    def test_every_core_repo_has_an_entry_point(self) -> None:
        """Every inventoried repo must have a known Typer entry point.

        ``mcp-common`` is library-only and short-circuits, so it is the one
        repo without an entry point.
        """
        assert set(ENTRY_POINTS) | {"mcp-common"} == set(CORE_REPOS)

    def test_every_entry_point_names_a_known_repo(self) -> None:
        """The entry-point map must not carry a repo the list dropped."""
        assert set(ENTRY_POINTS) <= set(CORE_REPOS)


class TestResolveRepoPath:
    """A repo's checkout is resolved against the projects root."""

    def test_defaults_to_the_projects_root(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv(PROJECTS_ROOT_ENV_VAR, str(tmp_path))

        assert resolve_repo_path("oneiric", None) == tmp_path / "oneiric"

    def test_an_explicit_path_wins(self, tmp_path: Path, monkeypatch) -> None:
        """``--repo-path`` overrides the derived location."""
        monkeypatch.setenv(PROJECTS_ROOT_ENV_VAR, str(tmp_path))
        override = tmp_path / "somewhere-else"

        assert resolve_repo_path("oneiric", str(override)) == override

    def test_the_env_var_reaches_the_resolution(self, tmp_path: Path, monkeypatch) -> None:
        """``$BODAI_PROJECTS_ROOT`` steers the default location."""
        monkeypatch.setenv(PROJECTS_ROOT_ENV_VAR, str(tmp_path))

        assert resolve_repo_path("oneiric", None) == tmp_path / "oneiric"


def test_the_script_hardcodes_no_home_path() -> None:
    """The script may not bake one machine's layout into its source."""
    source = SCRIPT_PATH.read_text()

    assert "/Users/" not in source
