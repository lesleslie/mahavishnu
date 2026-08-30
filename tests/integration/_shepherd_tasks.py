"""Module-level task bodies for the Shepherd integration tests.

Shepherd's confined execution model imports the module that declares a
task callable, so the test functions must live in a regular
importable module — not inside a ``test_*.py`` file (pytest refuses
to import test modules as siblings).

Each task declares a ``_repo: GitRepo = None`` parameter so the
substrate's signature schema recognises the workspace handle grant;
without it ``workspace.run`` aborts with ``RunStartError`` (the
substrate refuses tasks that don't declare any handle).
"""

from __future__ import annotations

from pathlib import Path

from shepherd import GitRepo as _GitRepo


def write_inside_grant(target: Path, _repo: _GitRepo) -> Path:
    """Write a file inside the granted root; the substrate's Seatbelt /
    Landlock ruleset must allow the syscall."""
    target.write_text("inside-grant")
    return target


def write_outside_grant(target: Path, _repo: _GitRepo) -> Path:
    """Write a file outside the granted root; the substrate's jail must
    refuse the syscall."""
    target.write_text("outside-grant")
    return target
