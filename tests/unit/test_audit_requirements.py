"""Unit tests for the requirement-audit grammar and categories.

The audit distinguishes four things that a plain set difference cannot:

* a **namespaced** ID (``REQ-ORC-001``) names exactly one requirement, so a
  missing reference is a failure;
* a **bare** ID (``REQ-001``) is a repo-wide convention that predates the
  namespaced grammar and collides across unrelated plans, so it is reported
  as a worklist and never fails the audit;
* an **external** requirement declares ``implementation_repo`` and is
  implemented in a sibling repository;
* a requirement in a **closed** plan describes work that is already over, so
  its unimplemented requirements are history rather than drift.

These tests build a synthetic tree rather than reading the real one, so they
pin the behaviour instead of the repository's current state.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "audit_requirements.py"


def _plan(name: str, *, status: str = "active", requirements: str = "") -> str:
    return (
        "---\n"
        f"status: {status}\n"
        "role: implementation\n"
        "kind: plan\n"
        "date: 2026-11-07\n"
        "last_reviewed: 2026-11-07\n"
        "superseded_by: null\n"
        "topic: test\n"
        f'title: "Test plan {name}"\n'
        f"{requirements}"
        "---\n\n"
        f"# Test plan {name}\n"
    )


def _run(root: Path) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(root),
            "--plans",
            str(root / "docs" / "plans"),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode in (0, 1), result.stderr
    return json.loads(result.stdout)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A synthetic repo root. Its siblings live beside it, so the audit's
    ``implementation_repo`` resolution (a sibling of ``--root``) finds them."""
    repo = tmp_path / "repo"
    (repo / "docs" / "plans" / ".archive").mkdir(parents=True)
    (repo / "pkg").mkdir()
    return repo


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.mark.unit
def test_archive_plans_are_not_scanned(tree: Path) -> None:
    """A requirement declared only in ``.archive/`` must not satisfy a
    reference. The archive is git-ignored, so scanning it would make the
    verdict depend on the machine."""
    _write(
        tree / "docs" / "plans" / ".archive" / "old.md",
        _plan(
            "archived",
            status="complete",
            requirements="requirements:\n- id: REQ-ARCHIVED-001\n  title: Old\n",
        ),
    )
    _write(tree / "pkg" / "code.py", "# req: REQ-ARCHIVED-001\n")

    payload = _run(tree)
    assert payload["summary"]["phantom_count"] == 1
    assert payload["phantoms"][0]["requirement_id"] == "REQ-ARCHIVED-001"


@pytest.mark.unit
def test_bare_ids_are_reported_but_never_fail(tree: Path) -> None:
    """A bare ``REQ-001`` is ambiguous across plans, so it is surfaced as a
    worklist and does not fail the audit."""
    _write(
        tree / "docs" / "plans" / "p.md",
        _plan(
            "bare",
            requirements="requirements:\n- id: REQ-001\n  title: Bare one\n",
        ),
    )
    _write(tree / "pkg" / "code.py", "# req: REQ-001\n")

    payload = _run(tree)
    assert payload["summary"]["orphan_count"] == 0
    assert payload["summary"]["phantom_count"] == 0
    assert payload["summary"]["unnamespaced_count"] == 1
    assert payload["unnamespaced"][0]["requirement_id"] == "REQ-001"


@pytest.mark.unit
def test_bare_reference_without_declaration_is_informal(tree: Path) -> None:
    """A bare reference to an ID nothing declares is informal, not a phantom."""
    _write(
        tree / "docs" / "plans" / "p.md",
        _plan("namespaced", requirements="requirements:\n- id: REQ-XYZ-001\n  title: X\n"),
    )
    _write(tree / "pkg" / "code.py", "# req: REQ-777\n")

    payload = _run(tree)
    assert payload["summary"]["phantom_count"] == 0
    assert payload["summary"]["informal_count"] == 1
    assert payload["informal"][0]["requirement_id"] == "REQ-777"


@pytest.mark.unit
def test_namespaced_declaration_without_reference_is_an_orphan(tree: Path) -> None:
    """A namespaced requirement with no implementation is real drift."""
    _write(
        tree / "docs" / "plans" / "p.md",
        _plan(
            "orphan",
            requirements=(
                "requirements:\n"
                "- id: REQ-XYZ-001\n"
                "  title: X\n"
                "- id: REQ-XYZ-002\n"
                "  title: Y\n"
            ),
        ),
    )
    _write(tree / "pkg" / "code.py", "# req: REQ-XYZ-001\n")

    payload = _run(tree)
    assert payload["summary"]["orphan_count"] == 1
    assert payload["orphans"][0]["requirement_id"] == "REQ-XYZ-002"


@pytest.mark.unit
def test_namespaced_reference_without_declaration_is_a_phantom(tree: Path) -> None:
    """A namespaced reference to an ID nothing declares is a failure."""
    _write(
        tree / "docs" / "plans" / "p.md",
        _plan("p", requirements="requirements:\n- id: REQ-XYZ-001\n  title: X\n"),
    )
    _write(tree / "pkg" / "code.py", "# req: REQ-XYZ-999\n")

    payload = _run(tree)
    assert payload["summary"]["phantom_count"] == 1
    assert payload["phantoms"][0]["requirement_id"] == "REQ-XYZ-999"


@pytest.mark.unit
def test_external_requirement_is_not_an_orphan(tree: Path) -> None:
    """``implementation_repo`` says the implementation lives in a sibling
    repo. A missing marker there is a missing marker, not a missing
    implementation."""
    _write(
        tree / "docs" / "plans" / "p.md",
        _plan(
            "external",
            requirements=(
                "requirements:\n"
                "- id: REQ-EXT-001\n"
                "  title: Implemented elsewhere\n"
                "  implementation_repo: sibling\n"
            ),
        ),
    )
    _write(tree / "pkg" / "code.py", "x = 1\n")

    payload = _run(tree)
    assert payload["summary"]["orphan_count"] == 0
    assert payload["summary"]["unverified_count"] == 1
    assert payload["unverified"][0]["implementation_repo"] == "sibling"


@pytest.mark.unit
def test_external_requirement_is_verified_when_the_sibling_has_a_marker(
    tree: Path,
) -> None:
    """When the sibling repo carries a marker, the requirement is reported as
    verified-external rather than unverified."""
    sibling = tree.parent / "sibling"
    _write(sibling / "mod.py", "# req: REQ-EXT-002\n")
    _write(
        tree / "docs" / "plans" / "p.md",
        _plan(
            "external",
            requirements=(
                "requirements:\n"
                "- id: REQ-EXT-002\n"
                "  title: Implemented in the sibling\n"
                "  implementation_repo: sibling\n"
            ),
        ),
    )

    payload = _run(tree)
    assert payload["summary"]["external_count"] == 1
    assert payload["summary"]["unverified_count"] == 0
    assert payload["summary"]["orphan_count"] == 0
    assert payload["external"][0]["requirement_id"] == "REQ-EXT-002"


@pytest.mark.unit
def test_closed_plan_requirements_are_history_not_drift(tree: Path) -> None:
    """A shipped plan's unimplemented requirements are not orphans."""
    _write(
        tree / "docs" / "plans" / "p.md",
        _plan(
            "closed",
            status="complete",
            requirements=(
                "requirements:\n"
                "- id: REQ-DONE-001\n"
                "  title: Done long ago\n"
                "- id: REQ-DONE-002\n"
                "  title: Also done\n"
            ),
        ),
    )
    _write(tree / "pkg" / "code.py", "# req: REQ-DONE-001\n")

    payload = _run(tree)
    assert payload["summary"]["orphan_count"] == 0
    assert payload["summary"]["phantom_count"] == 0


@pytest.mark.unit
def test_partially_implemented_open_plan_reports_its_dead_ids(tree: Path) -> None:
    """An open plan with some implemented requirements still reports the
    unimplemented ones -- that is real drift."""
    _write(
        tree / "docs" / "plans" / "p.md",
        _plan(
            "open",
            requirements=(
                "requirements:\n"
                "- id: REQ-OPEN-001\n"
                "  title: Implemented\n"
                "- id: REQ-OPEN-002\n"
                "  title: Not implemented\n"
            ),
        ),
    )
    _write(tree / "pkg" / "code.py", "# req: REQ-OPEN-001\n")

    payload = _run(tree)
    assert payload["summary"]["orphan_count"] == 1
    assert payload["orphans"][0]["requirement_id"] == "REQ-OPEN-002"


@pytest.mark.unit
def test_plan_with_nothing_implemented_is_not_reported(tree: Path) -> None:
    """A plan whose whole table is unimplemented is bookkeeping noise, not
    drift -- it is the normal state of a plan that has not started."""
    _write(
        tree / "docs" / "plans" / "p.md",
        _plan("fresh", requirements="requirements:\n- id: REQ-NEW-001\n  title: New\n"),
    )
    _write(tree / "pkg" / "code.py", "x = 1\n")

    payload = _run(tree)
    assert payload["summary"]["orphan_count"] == 0
