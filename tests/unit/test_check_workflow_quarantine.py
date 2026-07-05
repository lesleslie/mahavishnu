"""Tests for scripts/ci/check_workflow_quarantine.py.

Plan 5 Phase A.0.4 — CI guard that enforces:

1. Files directly under ``mahavishnu/workflows/`` (NOT under
   ``distilled/``) MUST NOT be named ``distilled_*.py``.
2. Files directly under ``mahavishnu/workflows/`` MUST contain BOTH
   header lines within their first 50 lines:
   - ``# Approved by: <reviewer-id>``
   - ``# Workflow-ID: <ulid>``

The guard is defense-in-depth — the runtime quarantine invariant
(mahavishnu/distill/discovery.py) is the primary gate; this CI check
catches the ``cp`` bypass before merge.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD_PATH = REPO_ROOT / "scripts" / "ci" / "check_workflow_quarantine.py"


def _load_guard():
    """Load the CI guard module from scripts/ci/ without a package."""
    import sys as _sys

    spec = importlib.util.spec_from_file_location("check_workflow_quarantine", GUARD_PATH)
    assert spec is not None and spec.loader is not None, f"Cannot load {GUARD_PATH}"
    module = importlib.util.module_from_spec(spec)
    # The dataclass machinery in the loaded module needs to find the module
    # in sys.modules by __name__; otherwise `@dataclass` raises an obscure
    # "'NoneType' object has no attribute '__dict__'" error.
    _sys.modules["check_workflow_quarantine"] = module
    spec.loader.exec_module(module)
    return module


# Module-level singleton — load once. Tests reference this directly so they
# don't need the ``guard`` fixture.
_GUARD = _load_guard()


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """Create a fresh repo with mahavishnu/workflows/ + workflows/distilled/."""
    workflows = tmp_path / "mahavishnu" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "__init__.py").write_text("")
    return tmp_path


def _write_with_headers(path: Path, body: str, *, approved: bool = True, wid: bool = True) -> None:
    """Write a file with the required header comments prepended."""
    headers: list[str] = []
    if approved:
        headers.append("# Approved by: les")
    if wid:
        headers.append("# Workflow-ID: 01J0000000000000000000000X")
    header_block = "\n".join(headers) + "\n"
    path.write_text(header_block + textwrap.dedent(body))


# ---------------------------------------------------------------------------
# Pure-Python unit tests for check_repo()
# ---------------------------------------------------------------------------


class TestCheckRepo:
    """The pure-python check function (no subprocess)."""

    def test_clean_repo_passes(self, fake_repo: Path) -> None:
        """A repo with one well-formed workflow file passes."""
        check_repo = _GUARD.check_repo

        _write_with_headers(
            fake_repo / "mahavishnu" / "workflows" / "good_wf.py",
            "async def good_wf():\n    return 'ok'\n",
        )
        result = check_repo(fake_repo)
        assert result.passed, result.violations

    def test_quarantined_file_does_not_need_headers(self, fake_repo: Path) -> None:
        """A file under workflows/distilled/ is allowed without headers."""
        check_repo = _GUARD.check_repo

        distilled = fake_repo / "mahavishnu" / "workflows" / "distilled"
        distilled.mkdir()
        (distilled / "needs_review.py").write_text(
            "# No headers needed in quarantine\n"
            "async def needs_review():\n    return 'quarantined'\n"
        )
        result = check_repo(fake_repo)
        assert result.passed, (
            f"Quarantined file should NOT trigger header violations: "
            f"{result.violations}"
        )

    def test_missing_workflows_dir_passes(self, tmp_path: Path) -> None:
        """No workflows/ dir = no checks = pass."""
        check_repo = _GUARD.check_repo

        result = check_repo(tmp_path)
        assert result.passed

    def test_filename_distilled_underscore_is_violation(self, fake_repo: Path) -> None:
        """distilled_*.py directly under workflows/ is a bypass attempt."""
        check_repo = _GUARD.check_repo

        # File with valid headers BUT bad name — must still fail on filename.
        _write_with_headers(
            fake_repo / "mahavishnu" / "workflows" / "distilled_evil.py",
            "async def evil():\n    return 'bypass'\n",
        )
        result = check_repo(fake_repo)
        assert not result.passed
        codes = {v.code for v in result.violations}
        assert "distilled_filename_bypass" in codes

    def test_missing_approved_by_header_is_violation(self, fake_repo: Path) -> None:
        """File with only Workflow-ID header → fail."""
        check_repo = _GUARD.check_repo

        path = fake_repo / "mahavishnu" / "workflows" / "no_approver.py"
        # approved=False, wid=True
        _write_with_headers(path, "async def no_approver():\n    return 'x'\n", approved=False)
        result = check_repo(fake_repo)
        assert not result.passed
        codes = {v.code for v in result.violations}
        assert "missing_required_header:approved_by" in codes

    def test_missing_workflow_id_header_is_violation(self, fake_repo: Path) -> None:
        """File with only Approved-by header → fail."""
        check_repo = _GUARD.check_repo

        path = fake_repo / "mahavishnu" / "workflows" / "no_wid.py"
        _write_with_headers(path, "async def no_wid():\n    return 'x'\n", wid=False)
        result = check_repo(fake_repo)
        assert not result.passed
        codes = {v.code for v in result.violations}
        assert "missing_required_header:workflow-id" in codes

    def test_both_headers_missing_emits_two_violations(self, fake_repo: Path) -> None:
        """File with neither header → fail with both violations."""
        check_repo = _GUARD.check_repo

        (fake_repo / "mahavishnu" / "workflows" / "raw.py").write_text(
            "async def raw():\n    return 'x'\n"
        )
        result = check_repo(fake_repo)
        assert not result.passed
        codes = {v.code for v in result.violations}
        assert "missing_required_header:approved_by" in codes
        assert "missing_required_header:workflow-id" in codes

    def test_init_py_ignored(self, fake_repo: Path) -> None:
        """__init__.py is not a workflow and must not be checked."""
        check_repo = _GUARD.check_repo

        (fake_repo / "mahavishnu" / "workflows" / "__init__.py").write_text("# nothing here\n")
        result = check_repo(fake_repo)
        assert result.passed

    def test_header_after_50_lines_does_not_count(self, fake_repo: Path) -> None:
        """Headers beyond line 50 are NOT seen — guard fails fast on early line."""
        check_repo = _GUARD.check_repo

        body_lines = ["async def buried():\n"] + ["    # filler\n"] * 49 + [
            "# Approved by: les\n",
            "# Workflow-ID: 01J0000000000000000000000X\n",
        ]
        path = fake_repo / "mahavishnu" / "workflows" / "buried.py"
        path.write_text("".join(body_lines))
        result = check_repo(fake_repo)
        assert not result.passed


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


class TestCheckRepoCLI:
    """The script as invoked from the command line (subprocess)."""

    def test_cli_pass_exits_zero(self, fake_repo: Path) -> None:
        """Clean repo: exit code 0."""
        _write_with_headers(
            fake_repo / "mahavishnu" / "workflows" / "wf.py",
            "async def wf():\n    return 'ok'\n",
        )
        result = subprocess.run(
            [sys.executable, "scripts/ci/check_workflow_quarantine.py", str(fake_repo)],
            capture_output=True,
            text=True,
            check=False,
            cwd=Path("/Users/les/Projects/mahavishnu"),
        )
        assert result.returncode == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    def test_cli_fail_exits_nonzero(self, fake_repo: Path) -> None:
        """Repo with bad file: exit code 1."""
        (fake_repo / "mahavishnu" / "workflows" / "bad.py").write_text(
            "async def bad():\n    return 'no headers'\n"
        )
        result = subprocess.run(
            [sys.executable, "scripts/ci/check_workflow_quarantine.py", str(fake_repo)],
            capture_output=True,
            text=True,
            check=False,
            cwd=Path("/Users/les/Projects/mahavishnu"),
        )
        assert result.returncode == 1

    def test_cli_json_output(self, fake_repo: Path) -> None:
        """--json emits valid JSON describing violations."""
        import json as jsonlib

        (fake_repo / "mahavishnu" / "workflows" / "bad.py").write_text(
            "async def bad():\n    return 'no headers'\n"
        )
        result = subprocess.run(
            [
                sys.executable,
                "scripts/ci/check_workflow_quarantine.py",
                str(fake_repo),
                "--json",
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=Path("/Users/les/Projects/mahavishnu"),
        )
        # JSON goes to stdout regardless of pass/fail.
        data = jsonlib.loads(result.stdout)
        assert data["passed"] is False
        assert len(data["violations"]) >= 1
        assert "code" in data["violations"][0]
