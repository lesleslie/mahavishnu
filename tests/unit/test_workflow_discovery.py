"""Regression tests for workflow discovery quarantine invariant.

Phase A.0 of Plan 5 (Distilled Workflows). The quarantine invariant is
the load-bearing security claim: files under ``mahavishnu/workflows/distilled/``
MUST NOT be discoverable by ``iter_workflow_modules`` or
``discover_workflows``. The CI guard (scripts/ci/check_workflow_quarantine.py)
enforces this for new files at commit time; these tests pin the runtime
behavior so a future refactor cannot silently break it.

If a change to discovery glob would let a quarantined file slip through,
these tests MUST fail loudly.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def fake_repo_root(tmp_path: Path) -> Path:
    """Create a minimal repo layout with workflows/ + workflows/distilled/."""
    workflows_dir = tmp_path / "mahavishnu" / "workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "__init__.py").write_text("")
    return tmp_path


def _make_module(path: Path, body: str) -> None:
    """Write a workflow module file with the given body."""
    path.write_text(textwrap.dedent(body))


# ---------------------------------------------------------------------------
# iter_workflow_modules: quarantine invariant
# ---------------------------------------------------------------------------


class TestIterWorkflowModulesQuarantine:
    """The quarantine invariant: distilled/*.py is NEVER yielded."""

    def test_does_not_yield_files_under_distilled_subdir(
        self, fake_repo_root: Path
    ) -> None:
        """Files under workflows/distilled/ MUST NOT be yielded even if pattern drifts."""
        from mahavishnu.distill.discovery import iter_workflow_modules

        distilled_dir = fake_repo_root / "mahavishnu" / "workflows" / "distilled"
        distilled_dir.mkdir()
        _make_module(
            distilled_dir / "_quarantined.py",
            "def quarantined_workflow():\n    return 'should not be discovered'\n",
        )

        yielded = list(iter_workflow_modules(fake_repo_root))
        assert yielded == [], (
            f"Quarantined file leaked into discovery: "
            f"{[p.name for p in yielded]}"
        )

    def test_yields_files_at_workflows_root(self, fake_repo_root: Path) -> None:
        """Top-level workflows/*.py files MUST be yielded."""
        from mahavishnu.distill.discovery import iter_workflow_modules

        _make_module(
            fake_repo_root / "mahavishnu" / "workflows" / "my_workflow.py",
            "def my_workflow():\n    return 'ok'\n",
        )

        yielded = list(iter_workflow_modules(fake_repo_root))
        names = {p.name for p in yielded}
        assert "my_workflow.py" in names
        assert "__init__.py" not in names

    def test_excludes_init_py(self, fake_repo_root: Path) -> None:
        """__init__.py at workflows/ root MUST NOT be yielded."""
        from mahavishnu.distill.discovery import iter_workflow_modules

        # The fixture already creates __init__.py; ensure it isn't yielded.
        yielded = list(iter_workflow_modules(fake_repo_root))
        assert all(p.stem != "__init__" for p in yielded), (
            f"__init__.py leaked: {[p.name for p in yielded]}"
        )

    def test_excludes_pycache(self, fake_repo_root: Path) -> None:
        """Python bytecode cache files MUST NOT be yielded."""
        from mahavishnu.distill.discovery import iter_workflow_modules

        pycache = fake_repo_root / "mahavishnu" / "workflows" / "__pycache__"
        pycache.mkdir()
        _make_module(pycache / "cached.pyc", "fake bytecode")

        yielded = list(iter_workflow_modules(fake_repo_root))
        assert all("__pycache__" not in p.parts for p in yielded)

    def test_missing_workflows_dir_is_empty(self, tmp_path: Path) -> None:
        """If workflows/ doesn't exist, return empty iterator (no crash)."""
        from mahavishnu.distill.discovery import iter_workflow_modules

        yielded = list(iter_workflow_modules(tmp_path))
        assert yielded == []


# ---------------------------------------------------------------------------
# discover_workflows: decorator attachment + quarantine integration
# ---------------------------------------------------------------------------


class TestDiscoverWorkflowsDecorator:
    """discover_workflows() finds @mahavishnu_workflow-decorated functions."""

    def test_finds_decorated_function(
        self, fake_repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A module with a decorated function yields one workflow entry."""
        from mahavishnu.distill.decorator import mahavishnu_workflow
        from mahavishnu.distill.discovery import discover_workflows

        _make_module(
            fake_repo_root / "mahavishnu" / "workflows" / "wf_a.py",
            textwrap.dedent(
                """\
                from mahavishnu.distill.decorator import mahavishnu_workflow

                @mahavishnu_workflow(intent="run a")
                async def wf_a() -> str:
                    return "a"
                """
            ),
        )

        # Ensure the decorator module is importable in the subprocess-imported
        # module. (We import by file path, not by package, so it inherits the
        # current sys.path — which pytest already has.)
        results = discover_workflows(fake_repo_root)
        assert len(results) == 1
        entry = results[0]
        assert entry["workflow_id"] == "wf_a"
        assert entry["intent"] == "run a"

    def test_quarantined_decorated_function_not_discovered(
        self, fake_repo_root: Path
    ) -> None:
        """A decorated function under distilled/ MUST NOT appear in results."""
        from mahavishnu.distill.discovery import discover_workflows

        distilled_dir = fake_repo_root / "mahavishnu" / "workflows" / "distilled"
        distilled_dir.mkdir()
        _make_module(
            distilled_dir / "secret_wf.py",
            textwrap.dedent(
                """\
                from mahavishnu.distill.decorator import mahavishnu_workflow

                @mahavishnu_workflow(intent="should not appear")
                async def secret_wf() -> str:
                    return "secret"
                """
            ),
        )

        results = discover_workflows(fake_repo_root)
        assert results == [], (
            f"Quarantined workflow leaked into discovery results: "
            f"{[r['workflow_id'] for r in results]}"
        )

    def test_module_with_syntax_error_is_skipped(self, fake_repo_root: Path) -> None:
        """A module that fails to import MUST be skipped, not raise."""
        from mahavishnu.distill.discovery import discover_workflows

        _make_module(
            fake_repo_root / "mahavishnu" / "workflows" / "broken.py",
            "def broken(:\n    pass\n",  # syntax error
        )

        # Should not raise
        results = discover_workflows(fake_repo_root)
        assert all(r["workflow_id"] != "broken" for r in results)


# ---------------------------------------------------------------------------
# WorkflowSpec + decorator unit tests
# ---------------------------------------------------------------------------


class TestWorkflowSpec:
    """WorkflowSpec is a frozen dataclass holding deployment metadata."""

    def test_spec_is_frozen(self) -> None:
        """WorkflowSpec instances MUST be immutable after construction."""
        from mahavishnu.distill.decorator import WorkflowSpec

        spec = WorkflowSpec(intent="x")
        with pytest.raises((AttributeError, Exception)) as exc_info:
            spec.intent = "y"  # type: ignore[misc]
        # Frozen dataclasses raise FrozenInstanceError (a subclass of AttributeError).
        assert "frozen" in str(exc_info.value).lower() or isinstance(
            exc_info.value, AttributeError
        )

    def test_spec_default_values(self) -> None:
        """Defaults: work_pool='default', tags=(), schedule=None, etc."""
        from mahavishnu.distill.decorator import WorkflowSpec

        spec = WorkflowSpec(intent="only")
        assert spec.intent == "only"
        assert spec.work_pool == "default"
        assert spec.tags == ()
        assert spec.schedule is None
        assert spec.repo_filter == "*"
        assert spec.description == ""


class TestMahavishnuWorkflowDecorator:
    """The @mahavishnu_workflow(...) decorator attaches a WorkflowSpec."""

    def test_decorator_attaches_spec_to_function(self) -> None:
        """After decoration, fn.__mahavishnu_workflow_spec__ is a WorkflowSpec."""
        from mahavishnu.distill.decorator import (
            WorkflowSpec,
            mahavishnu_workflow,
        )

        @mahavishnu_workflow(
            intent="test-intent",
            tags=("a", "b"),
            work_pool="alt",
            description="desc",
        )
        async def my_fn() -> str:
            return "ok"

        spec = getattr(my_fn, "__mahavishnu_workflow_spec__", None)
        assert isinstance(spec, WorkflowSpec)
        assert spec.intent == "test-intent"
        assert spec.tags == ("a", "b")
        assert spec.work_pool == "alt"
        assert spec.description == "desc"

    def test_decorator_preserves_function_behavior(self) -> None:
        """Decorated function MUST still be callable with original behavior."""
        from mahavishnu.distill.decorator import mahavishnu_workflow

        @mahavishnu_workflow(intent="passthrough")
        def add(a: int, b: int) -> int:
            return a + b

        assert add(2, 3) == 5
        assert getattr(add, "__mahavishnu_workflow_spec__", None) is not None

    def test_multiple_decorated_functions_in_one_module(
        self, fake_repo_root: Path
    ) -> None:
        """Two decorated functions in the same module: both discovered."""
        from mahavishnu.distill.discovery import discover_workflows

        _make_module(
            fake_repo_root / "mahavishnu" / "workflows" / "multi.py",
            textwrap.dedent(
                """\
                from mahavishnu.distill.decorator import mahavishnu_workflow

                @mahavishnu_workflow(intent="first")
                async def wf_one() -> str:
                    return "1"

                @mahavishnu_workflow(intent="second")
                async def wf_two() -> str:
                    return "2"

                async def helper() -> str:  # NOT decorated — must not appear
                    return "helper"
                """
            ),
        )

        results = discover_workflows(fake_repo_root)
        intents = {r["intent"] for r in results}
        assert intents == {"first", "second"}