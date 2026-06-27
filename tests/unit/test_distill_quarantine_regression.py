"""Quarantine invariant regression test for distilled workflow emission.

Plan 5 Phase A.1 Task 5 — every emitted workflow module MUST land in
``mahavishnu/workflows/distilled/``. The CI guard
(``scripts/ci/check_workflow_quarantine.py``) accepts only:

- Files under ``mahavishnu/workflows/distilled/*.py`` (unconditional).
- Files under ``mahavishnu/workflows/*.py`` that carry the required
  ``# Approved by: ...`` + ``# Workflow-ID: ...`` headers.

This test pins both sides of the invariant:

1. **Runtime side**: a synthesized distilled module lands in
   ``distilled/`` and is NOT discoverable by ``discover_workflows``.
2. **CI guard side**: the ``scripts/ci/check_workflow_quarantine.py``
   check accepts a quarantined file and rejects a top-level file
   that lacks the headers.

The runtime invariant is already covered by
``tests/unit/test_workflow_discovery.py``; this test adds a
distill-emit-specific assertion on top.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


@pytest.fixture
def fake_repo_with_distilled(tmp_path: Path) -> Path:
    """Build a repo layout with the workflow discovery root + a
    quarantined module + the CI guard script."""
    workflows_dir = tmp_path / "mahavishnu" / "workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "__init__.py").write_text("")

    # Quarantined module (NOT discoverable).
    distilled_dir = workflows_dir / "distilled"
    distilled_dir.mkdir()
    (distilled_dir / "__init__.py").write_text("")
    (distilled_dir / "01JABC_test.py").write_text(
        textwrap.dedent(
            """\
            # Approved by: reviewer@example.com
            # Workflow-ID: 01JABC_TEST123

            from mahavishnu.distill.decorator import mahavishnu_workflow


            @mahavishnu_workflow(intent="synthetic test")
            async def test_workflow():
                return None
            """
        )
    )

    # A top-level workflow with the headers (publish-time path).
    (workflows_dir / "published_workflow.py").write_text(
        textwrap.dedent(
            """\
            # Approved by: reviewer@example.com
            # Workflow-ID: 01JDEF_PUB1234

            from mahavishnu.distill.decorator import mahavishnu_workflow


            @mahavishnu_workflow(intent="published test")
            async def published_workflow():
                return None
            """
        )
    )

    return tmp_path


class TestRuntimeQuarantineInvariant:
    """The discovery glob MUST NOT yield quarantined modules."""

    def test_quarantined_module_not_discoverable(
        self, fake_repo_with_distilled: Path
    ) -> None:
        from mahavishnu.distill.discovery import (
            discover_workflows,
            iter_workflow_modules,
        )

        paths = iter_workflow_modules(fake_repo_with_distilled)
        # Only the published (top-level) module is yielded. The
        # quarantined one is invisible.
        stems = sorted(p.stem for p in paths)
        assert "published_workflow" in stems
        assert "01JABC_test" not in stems

        # discover_workflows only returns the published one too.
        results = discover_workflows(fake_repo_with_distilled)
        workflow_ids = {r["workflow_id"] for r in results}
        assert "published_workflow" in workflow_ids
        assert "01JABC_test" not in workflow_ids


class TestEmittedModulePathFormat:
    """The distiller's ``python_module_path`` MUST point at the
    quarantined subdir. The format is fixed:

        ``mahavishnu/workflows/distilled/{ulid}.py``
    """

    def test_distiller_emits_under_quarantine(self, tmp_path: Path) -> None:
        """Feed a minimal in-memory setup through the distiller and
        assert the produced path follows the quarantine convention.
        """
        import duckdb

        from mahavishnu.distill.distiller import distill_workflows
        from mahavishnu.distill.schema import apply_distill_schema

        c = duckdb.connect(":memory:")
        apply_distill_schema(c)
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations_v2 (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                project TEXT,
                category TEXT,
                timestamp TIMESTAMP NOT NULL DEFAULT now(),
                memory_tier TEXT NOT NULL DEFAULT 'long_term',
                embedding FLOAT[384],
                searchable_content TEXT NOT NULL DEFAULT '',
                namespace TEXT NOT NULL DEFAULT 'default'
            )
            """
        )
        for i in range(5):
            c.execute(
                """
                INSERT INTO conversations_v2
                    (id, session_id, source_type, content, project,
                     category, timestamp, embedding, searchable_content)
                VALUES (?, ?, ?, ?, ?, ?, now(), NULL, '')
                """,
                [f"s1-{i}", "s1", "mahavishnu_workflow", "tool call", "p", "c"],
            )

        ids = distill_workflows(c, evidence_threshold=3)
        assert ids
        # All emitted paths are under the quarantine dir.
        rows = c.execute(
            "SELECT id, python_module_path FROM distilled_workflows WHERE id = ANY(?)",
            [ids],
        ).fetchall()
        for rid, mod_path in rows:
            assert mod_path.startswith(
                "mahavishnu/workflows/distilled/"
            ), f"{rid} module path {mod_path!r} is NOT in the quarantine dir"
            assert mod_path.endswith(".py")


class TestCIGuardAcceptsQuarantinedFile:
    """The CI check script must accept the quarantined module
    without complaint.
    """

    def test_guard_accepts_quarantined_file(
        self, fake_repo_with_distilled: Path
    ) -> None:
        guard = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "check_workflow_quarantine.py"
        assert guard.exists(), f"CI guard not found: {guard}"
        # Run the guard against the fake repo by chdir-ing.
        result = subprocess.run(
            [sys.executable, str(guard)],
            cwd=fake_repo_with_distilled,
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Quarantined + correctly-headed top-level → guard passes (exit 0).
        # If it fails, surface stderr for debugging.
        if result.returncode != 0:
            pytest.fail(
                f"CI guard rejected quarantined/headed files:\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )


class TestCIGuardRejectsBadTopLevelFile:
    """A file under ``workflows/`` (NOT in distilled/) WITHOUT the
    required headers MUST be rejected.
    """

    def test_guard_rejects_unheaded_top_level(self, tmp_path: Path) -> None:
        workflows_dir = tmp_path / "mahavishnu" / "workflows"
        workflows_dir.mkdir(parents=True)
        (workflows_dir / "__init__.py").write_text("")
        # Top-level file with NO headers → must be rejected.
        (workflows_dir / "rogue_workflow.py").write_text(
            textwrap.dedent(
                """\
                from mahavishnu.distill.decorator import mahavishnu_workflow


                @mahavishnu_workflow(intent="rogue")
                async def rogue_workflow():
                    return None
                """
            )
        )

        guard = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "check_workflow_quarantine.py"
        result = subprocess.run(
            [sys.executable, str(guard)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode != 0, (
            "CI guard accepted a top-level workflow file without headers — "
            "the quarantine bypass is broken.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    def test_guard_rejects_distilled_named_top_level(self, tmp_path: Path) -> None:
        """A file named ``distilled_*.py`` directly under
        ``workflows/`` MUST be rejected — that's the bypass pattern.
        """
        workflows_dir = tmp_path / "mahavishnu" / "workflows"
        workflows_dir.mkdir(parents=True)
        (workflows_dir / "__init__.py").write_text("")
        # Bypass attempt: file named like a distilled one but at top level.
        (workflows_dir / "distilled_bypass.py").write_text(
            textwrap.dedent(
                """\
                # Approved by: reviewer@example.com
                # Workflow-ID: 01JBYPASS


                async def f():
                    return None
                """
            )
        )

        guard = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "check_workflow_quarantine.py"
        result = subprocess.run(
            [sys.executable, str(guard)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode != 0, (
            "CI guard accepted a top-level file named 'distilled_*.py' — "
            "the bypass-detection is broken.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
