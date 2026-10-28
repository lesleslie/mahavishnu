"""Guard: the published Bodai registry must never leak a machine's paths.

``BODAI_REPO_REGISTRY.md`` is tracked in a *public* repository, so an
absolute path in it discloses the operator's account name and local
directory layout to anyone who clones the repo. The registry therefore
publishes paths relative to a "projects root" and declares how a consumer
resolves that root back to a directory.

These tests cover the generator's root inference and relative rendering,
plus the guarantee that the committed artifact contains no absolute path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "BODAI_REPO_REGISTRY.md"
GENERATOR_PATH = REPO_ROOT / "scripts" / "regen_bodai_registry.py"


def _load_generator() -> ModuleType:
    """Import the generator script by path.

    It lives in ``scripts/`` rather than the package, so it is not
    importable as a module -- but it is deliberately dependency-light
    (stdlib plus PyYAML) so it stays runnable standalone.
    """
    spec = importlib.util.spec_from_file_location("regen_bodai_registry", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def generator() -> ModuleType:
    return _load_generator()


class TestProjectsRootInference:
    """The root comes from the catalog's geometry, not from configuration."""

    def test_infers_the_shared_parent(self, generator: ModuleType) -> None:
        paths = [
            "/Users/someone/Projects/oneiric",
            "/Users/someone/Projects/akosha",
            "/Users/someone/Projects/crackerjack",
        ]

        root = generator.infer_projects_root(paths)

        assert root == Path("/Users/someone/Projects")

    def test_a_stray_repo_does_not_drag_the_root_upwards(self, generator: ModuleType) -> None:
        """The *mode* of the parents wins, not the common ancestor.

        One repo kept elsewhere must not pull the root up to the home
        directory -- the rendered relative paths would then re-disclose
        the account name.
        """
        paths = [
            "/Users/someone/Projects/oneiric",
            "/Users/someone/Projects/akosha",
            "/Users/someone/Projects/crackerjack",
            "/Users/someone/elsewhere/stray",
        ]

        root = generator.infer_projects_root(paths)

        assert root == Path("/Users/someone/Projects")

    def test_empty_input_has_no_root(self, generator: ModuleType) -> None:
        assert generator.infer_projects_root([]) is None


class TestRelativeRendering:
    """Rows render relative to the root; anything else leaks nothing."""

    def test_renders_relative_to_the_root(self, generator: ModuleType) -> None:
        root = Path("/Users/someone/Projects")

        rendered = generator.render_repo_path("/Users/someone/Projects/oneiric", root)

        assert rendered == "oneiric/"

    def test_renders_nested_paths(self, generator: ModuleType) -> None:
        root = Path("/Users/someone/Projects")

        rendered = generator.render_repo_path("/Users/someone/Projects/ARCHIVED/old-repo", root)

        assert rendered == "ARCHIVED/old-repo/"

    def test_out_of_root_repo_falls_back_to_its_name(self, generator: ModuleType) -> None:
        """A repo outside the root must not drag the layout in with it."""
        root = Path("/Users/someone/Projects")

        rendered = generator.render_repo_path("/elsewhere/stray", root)

        assert rendered == "stray/"
        assert "/Users" not in rendered


class TestPublishedArtifact:
    """The committed registry is the thing that actually gets published."""

    def test_registry_contains_no_absolute_path(self) -> None:
        text = REGISTRY_PATH.read_text(encoding="utf-8")

        assert "/Users/" not in text, (
            "BODAI_REPO_REGISTRY.md is published in a public repository; an "
            "absolute path discloses the operator's account name."
        )

    def test_registry_declares_the_resolution_rule(self) -> None:
        """A consumer must be able to resolve a row without guessing."""
        text = REGISTRY_PATH.read_text(encoding="utf-8")

        assert "## Path resolution" in text
        assert "BODAI_PROJECTS_ROOT" in text

    def test_registry_path_cells_are_relative(self) -> None:
        """Every Path cell in the catalog tables is root-relative."""
        text = REGISTRY_PATH.read_text(encoding="utf-8")
        section = ""
        for line in text.splitlines():
            if line.startswith("#"):
                section = line.strip("# ").lower()
                continue
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.split("|")]
            if len(cells) < 3 or cells[1].lower() == "repo":
                continue
            path_cell = cells[2].strip("`")
            if not path_cell or path_cell == "n/a":
                continue
            if "archived" in section:
                continue
            assert not path_cell.startswith("/"), (
                f"absolute path in the registry catalog: {path_cell!r}"
            )
