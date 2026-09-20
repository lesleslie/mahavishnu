"""Unit tests for the ecosystem publish-URL MCP tool.

The tool is the server-side counterpart to
``crackerjack.services.mahavishnu_discovery.probe_publish_url``. These
tests pin the contract: path-match against ``settings/ecosystem.yaml``,
return the registered ``publish.url`` or ``None``, soft-fail on every
error mode.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastmcp import FastMCP

from mahavishnu.mcp.tools import ecosystem_publish_url_tool
from mahavishnu.mcp.tools.ecosystem_publish_url_tool import (
    _load_publish_url,
    _resolve_ecosystem_path,
    register,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ecosystem_yaml(tmp_path: Path) -> Path:
    """Write a representative ecosystem.yaml under tmp_path and return the path."""
    p = tmp_path / "settings" / "ecosystem.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        """\
repos:
  - name: mdinject
    package: mdinject
    path: /Users/les/Projects/mdinject
    publish:
      url: https://gitlab.com/api/v4/projects/77841268/packages/pypi/upload
      token_env: GITLAB_PERSONAL_ACCESS_TOKEN
  - name: crackerjack
    package: crackerjack
    path: /Users/les/Projects/crackerjack
    publish:
      url: null
      token_env: null
""",
    )
    return p


@pytest.fixture
def ecosystem_env(monkeypatch: pytest.MonkeyPatch, ecosystem_yaml: Path) -> None:
    monkeypatch.setenv("MAHAVISHNU_ECOSYSTEM_PATH", str(ecosystem_yaml))


# ---------------------------------------------------------------------------
# Tests — _resolve_ecosystem_path
# ---------------------------------------------------------------------------


class TestResolveEcosystemPath:
    def test_env_var_takes_priority(
        self,
        monkeypatch: pytest.MonkeyPatch,
        ecosystem_yaml: Path,
    ) -> None:
        """``$MAHAVISHNU_ECOSYSTEM_PATH`` is the operator override."""
        monkeypatch.setenv("MAHAVISHNU_ECOSYSTEM_PATH", str(ecosystem_yaml))
        assert _resolve_ecosystem_path() == ecosystem_yaml

    def test_falls_back_to_cwd_relative(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Without the env var AND no settings/ecosystem.yaml under cwd,
        returns ``None``. The function only returns a path when the
        file actually exists — we don't lie about a missing registry.
        """
        monkeypatch.delenv("MAHAVISHNU_ECOSYSTEM_PATH", raising=False)
        monkeypatch.chdir(tmp_path)
        # No ecosystem.yaml exists under tmp_path → must return None.
        assert _resolve_ecosystem_path() is None

    def test_returns_cwd_relative_path_when_file_exists(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """When the env var is unset but ``settings/ecosystem.yaml``
        exists under cwd, that path wins (operator-friendly default).
        """
        monkeypatch.delenv("MAHAVISHNU_ECOSYSTEM_PATH", raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / "settings").mkdir()
        (tmp_path / "settings" / "ecosystem.yaml").write_text("repos: []\n")
        assert _resolve_ecosystem_path() == tmp_path / "settings" / "ecosystem.yaml"

    def test_returns_none_when_no_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.delenv("MAHAVISHNU_ECOSYSTEM_PATH", raising=False)
        monkeypatch.chdir(tmp_path)
        assert _resolve_ecosystem_path() is None


# ---------------------------------------------------------------------------
# Tests — _load_publish_url
# ---------------------------------------------------------------------------


class TestLoadPublishUrl:
    def test_returns_url_for_matched_repo(
        self,
        ecosystem_env: None,
        ecosystem_yaml: Path,
    ) -> None:
        repo_path = str(Path("/Users/les/Projects/mdinject"))
        # When the path resolves identically, the entry matches.
        # We use the actual entry path so resolve() yields equality.
        actual = _load_publish_url(repo_path)
        # The path /Users/les/Projects/mdinject resolves to whatever
        # the local cwd says; if mdinject doesn't exist locally the
        # test isn't valid. So compare against the yaml's stored path
        # instead.
        assert actual == "https://gitlab.com/api/v4/projects/77841268/packages/pypi/upload"

    def test_returns_none_for_unmatched_repo(
        self,
        ecosystem_env: None,
    ) -> None:
        assert _load_publish_url("/some/other/path") is None

    def test_returns_none_when_publish_url_is_null(
        self,
        ecosystem_env: None,
        ecosystem_yaml: Path,
    ) -> None:
        """Crackerjack entry has ``publish.url: null`` → return ``None``
        so the client falls through to public PyPI."""
        repo_path = str(Path("/Users/les/Projects/crackerjack"))
        assert _load_publish_url(repo_path) is None

    def test_returns_none_when_ecosystem_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Soft fallback: no ecosystem.yaml resolvable → ``None`` (caller
        defaults to public PyPI)."""
        monkeypatch.delenv("MAHAVISHNU_ECOSYSTEM_PATH", raising=False)
        monkeypatch.chdir(tmp_path)  # tmp_path has no settings/ecosystem.yaml
        assert _load_publish_url("/Users/les/Projects/mdinject") is None

    def test_returns_none_on_malformed_yaml(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """YAML parse errors must not raise — return ``None`` and let
        the caller fall through to defaults."""
        bad = tmp_path / "ecosystem.yaml"
        bad.write_text(":\n  - this is: invalid: yaml: [")
        monkeypatch.setenv("MAHAVISHNU_ECOSYSTEM_PATH", str(bad))
        assert _load_publish_url("/Users/les/Projects/mdinject") is None

    def test_returns_none_when_repos_field_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """An ecosystem.yaml without a ``repos`` list is structurally
        invalid for this tool — return ``None``."""
        no_repos = tmp_path / "ecosystem.yaml"
        no_repos.write_text("settings:\n  log_level: INFO\n")
        monkeypatch.setenv("MAHAVISHNU_ECOSYSTEM_PATH", str(no_repos))
        assert _load_publish_url("/Users/les/Projects/mdinject") is None

    def test_path_match_is_resolved_both_sides(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Path comparison uses ``Path.resolve()`` on both sides — a
        relative path on the input or a symlink-relative entry both
        match. Lock the contract that operators can pass cwd-relative
        paths safely.
        """
        repo_dir = tmp_path / "myrepo"
        repo_dir.mkdir()
        yaml_path = tmp_path / "settings" / "ecosystem.yaml"
        yaml_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_path.write_text(
            f"""\
repos:
  - name: myrepo
    path: {repo_dir}
    publish:
      url: https://myrepo.example/pypi
""",
        )
        monkeypatch.setenv("MAHAVISHNU_ECOSYSTEM_PATH", str(yaml_path))

        # Pass the same path with redundant components — Path.resolve()
        # normalizes them on both sides, so the match still works.
        # We append ``.`` segments to the input path so ``resolve()``
        # is forced to canonicalize rather than just compare strings.
        canonical_input = str(repo_dir) + "/./."
        assert _load_publish_url(canonical_input) == "https://myrepo.example/pypi"


# ---------------------------------------------------------------------------
# Tests — register (FastMCP wiring)
# ---------------------------------------------------------------------------


class TestRegister:
    """Verify the tool registers with the FastMCP server under the
    expected name and shape."""

    def test_registers_under_expected_name(self, ecosystem_env: None) -> None:
        """Crackerjack's probe calls ``mahavishnu__get_publish_url`` —
        that exact name must be the registered tool.
        """
        import asyncio

        server = FastMCP(name="mahavishnu-test")
        register(server)

        # FastMCP.list_tools is async in current versions.
        tool_names = asyncio.run(server.list_tools())

        # Crackerjack's probe calls ``tools/call`` with
        # ``name='mahavishnu_get_publish_url'`` — that exact string
        # must be registered (matches the existing ``mahavishnu_<verb>_<noun>``
        # convention used by sibling tools like
        # ``mahavishnu_upsert_service``).
        assert any(
            t.name == "mahavishnu_get_publish_url" for t in tool_names
        ), f"Expected mahavishnu_get_publish_url; got {[t.name for t in tool_names]}"

    def test_register_is_idempotent(self, ecosystem_env: None) -> None:
        """Re-registering doesn't crash. FastMCP's decorator contract
        requires re-registration to be safe."""
        server = FastMCP(name="mahavishnu-idem")
        register(server)
        # Second call should not raise.
        register(server)
