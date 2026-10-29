"""Tests for ``scripts.bodai_paths``.

mahavishnu is a public repository, so no tracked file may carry an absolute
path: an absolute path discloses the operator's account name and local
directory layout to anyone who clones the repo. The Bodai registry publishes
root-relative paths and declares the rule for resolving that root back to a
directory.

This module is the single implementation of that rule, so every consumer
resolves the root the same way. The tests pin the chain, the rendering, and
the agreement between this renderer and the generator's own copy.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from scripts.bodai_paths import (
    DEFAULT_PROJECTS_DIRNAME,
    PROJECTS_ROOT_ENV_VAR,
    REPO_DIRNAME,
    render_repo_path,
    resolve_projects_root,
)

if TYPE_CHECKING:
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR_PATH = REPO_ROOT / "scripts" / "regen_bodai_registry.py"


@pytest.fixture(autouse=True)
def _clear_projects_root_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may inherit a projects-root override from the environment."""
    monkeypatch.delenv(PROJECTS_ROOT_ENV_VAR, raising=False)


class TestResolveProjectsRoot:
    """The chain: env var, then the repo's own location, then ~/Projects."""

    def test_env_var_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """``$BODAI_PROJECTS_ROOT`` beats every other candidate."""
        monkeypatch.setenv(PROJECTS_ROOT_ENV_VAR, str(tmp_path))

        root = resolve_projects_root(tmp_path / REPO_DIRNAME)

        assert root == tmp_path

    def test_env_var_is_expanded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A ``~``-prefixed override resolves against the home directory."""
        monkeypatch.setenv(PROJECTS_ROOT_ENV_VAR, "~/somewhere")

        assert resolve_projects_root() == Path.home() / "somewhere"

    def test_derived_from_the_repo_location(self, tmp_path: Path) -> None:
        """This repo sits at ``<projects root>/mahavishnu/``."""
        repo_root = tmp_path / REPO_DIRNAME
        (repo_root / ".git").mkdir(parents=True)

        assert resolve_projects_root(repo_root) == tmp_path

    def test_a_worktree_is_not_a_projects_root(self, tmp_path: Path) -> None:
        """The fleet's worktree bucket must not be mistaken for a projects root.

        The bucket holds directories named after fleet repos, so the name
        alone cannot tell it apart from a projects root -- but a git
        worktree's ``.git`` is a *file* pointing at the real repository,
        while a primary checkout's is a *directory*. Without that check the
        root resolves to the bucket, and every repo then resolves to a
        worktree instead of the primary checkout.
        """
        repo_root = tmp_path / REPO_DIRNAME
        repo_root.mkdir()
        (repo_root / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n")

        assert resolve_projects_root(repo_root) == Path.home() / DEFAULT_PROJECTS_DIRNAME

    def test_a_directory_that_is_not_a_checkout_is_not_a_projects_root(
        self, tmp_path: Path
    ) -> None:
        """A directory with no ``.git`` is not a checkout, so it locates nothing."""
        repo_root = tmp_path / REPO_DIRNAME
        repo_root.mkdir()

        assert resolve_projects_root(repo_root) == Path.home() / DEFAULT_PROJECTS_DIRNAME

    def test_falls_back_to_the_home_layout(self, tmp_path: Path) -> None:
        """A checkout that is not named ``mahavishnu`` has no known root."""
        repo_root = tmp_path / "some-other-checkout"

        assert resolve_projects_root(repo_root) == Path.home() / DEFAULT_PROJECTS_DIRNAME

    def test_falls_back_to_the_cwd_without_a_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no home directory the working directory is the last resort."""
        monkeypatch.setenv("HOME", "")
        monkeypatch.setattr(Path, "home", _raise_runtime_error)

        root = resolve_projects_root(tmp_path / "not-mahavishnu")

        assert root == Path.cwd()


class TestRenderRepoPath:
    """Paths render relative to the root; anything else renders as a name."""

    def test_renders_a_path_under_the_root(self, tmp_path: Path) -> None:
        """A repo under the root becomes its root-relative path."""
        assert render_repo_path(str(tmp_path / "oneiric"), tmp_path) == "oneiric/"

    def test_renders_a_nested_path(self, tmp_path: Path) -> None:
        """A repo in a subdirectory keeps that subdirectory."""
        assert render_repo_path(str(tmp_path / "group" / "oneiric"), tmp_path) == ("group/oneiric/")

    def test_falls_back_to_the_directory_name(self, tmp_path: Path) -> None:
        """A repo outside the root leaks nothing but its name."""
        assert render_repo_path("/elsewhere/oneiric", tmp_path) == "oneiric/"

    def test_without_a_root_only_the_name_is_rendered(self) -> None:
        """With no root at all, only the directory name survives."""
        assert render_repo_path("/Users/someone/Projects/oneiric", None) == "oneiric/"

    def test_never_renders_an_absolute_path(self, tmp_path: Path) -> None:
        """The rendering is safe to publish: it never starts with a slash."""
        rendered = render_repo_path(str(tmp_path / "oneiric"), tmp_path)

        assert not rendered.startswith("/")


def _raise_runtime_error() -> Path:
    """Stand-in for ``Path.home()`` when no home directory exists."""
    msg = "could not determine home directory"
    raise RuntimeError(msg)


def _load_generator() -> ModuleType:
    """Import the registry generator by path."""
    spec = importlib.util.spec_from_file_location("regen_bodai_registry", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_generator_agrees_with_the_shared_renderer() -> None:
    """The generator keeps its own copy; the two must not drift.

    The generator is deliberately standalone-runnable (stdlib plus PyYAML),
    so it cannot import this module. That makes the duplication a drift
    risk, so the agreement is pinned here instead.
    """
    generator = _load_generator()

    cases = [
        ("/root/oneiric", Path("/root"), "oneiric/"),
        ("/root/group/oneiric", Path("/root"), "group/oneiric/"),
        ("/elsewhere/oneiric", Path("/root"), "oneiric/"),
        ("/root/oneiric", None, "oneiric/"),
    ]
    for raw, root, expected in cases:
        assert generator.render_repo_path(raw, root) == expected
        assert render_repo_path(raw, root) == expected
