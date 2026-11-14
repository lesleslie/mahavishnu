"""The requirements audit must SEE the markers this branch lands.

A requirement marker the audit's own regex does not match is worse than
no marker at all: the requirement reads as delivered, the audit stays
quiet, and the traceability is fictional. ``#: req: REQ-X`` looks like
a marker and is not one — the audit's pattern is ``#\\s*req:`` and the
``:`` breaks it.

These tests pin the marker syntax and the frontmatter declaration
together, because either one alone is not enough:

- a marker the audit cannot see makes the requirement a *phantom*
  (referenced in prose, invisible to the scanner);
- a declaration with no visible marker makes it an *orphan* (declared,
  never referenced) and takes the audit's exit code to 1.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = REPO_ROOT / "docs/plans/2026-11-01-control-plane-consolidation.md"
OPENHANDS_PATH = REPO_ROOT / "mahavishnu/workers/openhands.py"


@pytest.fixture(scope="module")
def audit() -> ModuleType:
    """The audit script, loaded from the repo root."""
    spec = importlib.util.spec_from_file_location(
        "audit_requirements", REPO_ROOT / "scripts/audit_requirements.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # ``dataclass`` resolves the defining module through ``sys.modules``,
    # so the module has to be registered before it is executed.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestTheMarkersAreVisible:
    def test_the_openhands_marker_is_detected_by_the_audit(self, audit: ModuleType):
        """REQ-C14's marker must be one the audit's scanner recognises."""
        refs = audit.extract_references([OPENHANDS_PATH])
        assert "REQ-C14" in {ref.requirement_id for ref in refs}

    def test_the_marker_is_a_plain_comment_not_a_sphinx_field(self):
        """The audit's pattern is ``#\\s*req:`` — a ``:`` after the ``#``
        breaks the match, so the marker is written plainly."""
        source = OPENHANDS_PATH.read_text(encoding="utf-8")
        marker_lines = [line for line in source.splitlines() if "req:" in line.lower()]
        assert marker_lines, "the openhands worker must carry a requirement marker"
        for line in marker_lines:
            assert "#:" not in line, (
                f"'#: req:' is not the audit's marker syntax: {line!r}"
            )


class TestTheDeclarationsAreVisible:
    def test_req_c14_is_declared_in_the_plan_frontmatter(self, audit: ModuleType):
        """A declared requirement with no visible marker is an orphan, and
        the audit's exit code goes to 1 with it."""
        decls = audit.extract_declarations([PLAN_PATH])
        declared = {decl.requirement_id for decl in decls}
        assert "REQ-C14" in declared

    def test_req_c02_is_still_declared(self, audit: ModuleType):
        """The narrowing rule is one requirement per phase, not one
        requirement per plan — the phase that landed REQ-C02's marker
        keeps it declared."""
        decls = audit.extract_declarations([PLAN_PATH])
        declared = {decl.requirement_id for decl in decls}
        assert "REQ-C02" in declared
