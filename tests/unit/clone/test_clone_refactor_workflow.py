"""Integration tests for run_clone_refactor_dag.

Implements: REQ-CLONE-010, REQ-CLONE-011, REQ-CLONE-012, REQ-CLONE-013
"""

from __future__ import annotations

import asyncio
import subprocess
import warnings
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from mahavishnu.workflows.clone_refactor_workflow import (
    DAGResult,
    RepoCommit,
    run_clone_refactor_dag,
)

pytestmark = [pytest.mark.unit, pytest.mark.req(["REQ-CLONE-010", "REQ-CLONE-011", "REQ-CLONE-012", "REQ-CLONE-013"])]


# ---- Valid unified diff fixtures -----------------------------------------
# Brief defect (TD-m9): brief's diffs were malformed — `@@ -1 +1 @@` header
# with 2-line body rejected by git apply with "corrupt patch at line 8".
# Fixed below with proper hunk headers matching line counts.

EXTRACTION_DIFF = (
    "--- a/foo.py\n+++ b/foo.py\n@@ -1,2 +1,2 @@\n"
    " class Foo:\n-    pass\n+    '''Extracted'''\n"
)

EXTRACTION_DIFF_SIMPLE = (
    "--- a/foo.py\n+++ b/foo.py\n@@ -1,2 +1,2 @@\n"
    " class Foo:\n-    pass\n+    pass  # modified\n"
)

CONSUMING_DIFF_FROM_FOO = (
    "--- a/consumer.py\n+++ b/consumer.py\n@@ -1 +1 @@\n"
    "-from foo import Foo\n+from foo import Foo  # updated\n"
)

CONSUMING_DIFF_OLD_NEW = (
    "--- a/c.py\n+++ b/c.py\n@@ -1 +1 @@\n-old\n+new\n"
)

CONSUMING_DIFF_INIT_NEW = (
    "--- a/c.py\n+++ b/c.py\n@@ -1 +1 @@\n-init\n+new\n"
)

# Bad: targets existing c.py with non-matching context — git apply rejects
# Brief defect: original `--- a/nonexistent.py\n+++ b/nonexistent.py\n@@ -0,0 +1 @@\n+x\n`
# succeeds by CREATING the nonexistent file, which doesn't fail the consumer.
CONSUMING_DIFF_BAD = (
    "--- a/c.py\n+++ b/c.py\n@@ -1 +1 @@\n-different_content\n+new\n"
)


@pytest.fixture
def target_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "target"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"], check=True, capture_output=True
    )
    (repo / "foo.py").write_text("class Foo:\n    pass\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True)
    return repo


@pytest.fixture
def consumer_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "consumer"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"], check=True, capture_output=True
    )
    (repo / "consumer.py").write_text("from foo import Foo\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True)
    return repo


@pytest.fixture
def mock_backend() -> AsyncMock:
    backend = AsyncMock()
    backend.dag_key = lambda x: f"workflow/v1/{x}"
    backend.cluster_key = lambda x: f"cluster/v1/{x}"
    backend.in_flight_key = lambda x: f"cluster/v1/{x}/in_flight"
    backend.try_put_with_log_context = AsyncMock(return_value=True)
    backend.put = AsyncMock()
    backend.delete = AsyncMock()
    backend.get = AsyncMock(return_value=None)
    return backend


@pytest.fixture(autouse=True)
def _suppress_prefect_asyncmock_runtime_warnings() -> None:
    """Suppress RuntimeWarnings from Prefect serializing AsyncMock parameters.

    Prefect's `Flow.serialize_parameters` calls `fastapi.encoders.jsonable_encoder`
    on each parameter. AsyncMock attributes return coroutines that are never
    awaited, producing ~780 RuntimeWarnings per test invocation of the @flow.
    Per-test scope; no global side effects. Production code path is unchanged.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        yield


class TestRunCloneRefactorDAG:
    async def test_happy_path_propose_consume_persist(
        self, target_repo: Path, consumer_repo: Path, mock_backend: AsyncMock
    ) -> None:
        # Setup: detect_cluster_members mocked to return [target_repo]
        with patch(
            "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
            new=AsyncMock(return_value=[{"repo": str(target_repo), "match_score": 1.0}]),
        ):
            result = await run_clone_refactor_dag(
                refactor_job_id="job-001",
                cluster_id="cluster-1",
                mcp_backend=mock_backend,
                target_repo=str(target_repo),
                consumer_repos=[str(consumer_repo)],
                extracted_symbol="Foo",
                extraction_diff=EXTRACTION_DIFF,
                consuming_diffs={str(consumer_repo): CONSUMING_DIFF_FROM_FOO},
            )
        assert isinstance(result, DAGResult)
        assert result.status == "completed"
        assert len(result.consumer_commits) == 1
        assert result.consumer_commits[0].status == "completed"
        assert result.consumer_commits[0].repo == str(consumer_repo)

    async def test_target_write_fails_no_consumer_writes(
        self, target_repo: Path, consumer_repo: Path, mock_backend: AsyncMock
    ) -> None:
        # CA-M3 fix: mock `write_canonical_symbol` to raise instead of chmod
        # (chmod 0o000 is no-op for uid 0 and bypassed by git ops anyway).
        # The failure must happen INSIDE write_canonical_symbol — after
        # detect_cluster_members returns but before any consumer work.
        with patch(
            "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
            new=AsyncMock(return_value=[{"repo": str(target_repo), "match_score": 1.0}]),
        ):
            with patch(
                "mahavishnu.workflows.clone_refactor_workflow.write_canonical_symbol",
                new=AsyncMock(side_effect=RuntimeError("write_canonical_symbol failed")),
            ):
                with pytest.raises(RuntimeError, match="write_canonical_symbol failed"):
                    await run_clone_refactor_dag(
                        refactor_job_id="job-002",
                        cluster_id="cluster-1",
                        mcp_backend=mock_backend,
                        target_repo=str(target_repo),
                        consumer_repos=[str(consumer_repo)],
                        extracted_symbol="x",
                        extraction_diff=EXTRACTION_DIFF_SIMPLE,
                    )
        # REQ-CLONE-010: terminal "failed" was written
        failed_calls = [
            c for c in mock_backend.try_put_with_log_context.call_args_list
            if c.kwargs.get("log_context", {}).get("step_name") == "failed"
        ]
        assert len(failed_calls) == 1
        # REQ-CLONE-009: claim released in finally
        mock_backend.delete.assert_called_with("cluster/v1/cluster-1/in_flight")

    async def test_one_consumer_fails_others_succeed(
        self, target_repo: Path, tmp_path: Path, mock_backend: AsyncMock
    ) -> None:
        good1 = tmp_path / "good1"
        good2 = tmp_path / "good2"
        bad = tmp_path / "bad"
        for r in (good1, good2, bad):
            r.mkdir()
            subprocess.run(["git", "init", str(r)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(r), "config", "user.email", "x@x"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(r), "config", "user.name", "X"], check=True, capture_output=True)
            (r / "c.py").write_text("old\n")
            subprocess.run(["git", "-C", str(r), "add", "."], check=True)
            subprocess.run(["git", "-C", str(r), "commit", "-m", "init"], check=True)

        with patch(
            "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
            new=AsyncMock(return_value=[{"repo": str(target_repo)}]),
        ):
            result = await run_clone_refactor_dag(
                refactor_job_id="job-003",
                cluster_id="cluster-1",
                mcp_backend=mock_backend,
                target_repo=str(target_repo),
                consumer_repos=[str(good1), str(bad), str(good2)],
                extracted_symbol="Foo",
                extraction_diff=EXTRACTION_DIFF_SIMPLE,
                consuming_diffs={
                    str(good1): CONSUMING_DIFF_OLD_NEW,
                    str(bad): CONSUMING_DIFF_BAD,
                    str(good2): CONSUMING_DIFF_OLD_NEW,
                },
            )
        assert result.status == "failed"
        assert any(c.status == "failed" for c in result.consumer_commits)
        assert any(c.status == "completed" for c in result.consumer_commits)

    async def test_no_auto_revert_on_failure(
        self, target_repo: Path, tmp_path: Path, mock_backend: AsyncMock
    ) -> None:
        good = tmp_path / "good"
        bad = tmp_path / "bad"
        for r in (good, bad):
            r.mkdir()
            subprocess.run(["git", "init", str(r)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(r), "config", "user.email", "x@x"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(r), "config", "user.name", "X"], check=True, capture_output=True)
            (r / "c.py").write_text("old\n")
            subprocess.run(["git", "-C", str(r), "add", "."], check=True)
            subprocess.run(["git", "-C", str(r), "commit", "-m", "init"], check=True)

        with patch(
            "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
            new=AsyncMock(return_value=[{"repo": str(target_repo)}]),
        ):
            await run_clone_refactor_dag(
                refactor_job_id="job-004",
                cluster_id="cluster-1",
                mcp_backend=mock_backend,
                target_repo=str(target_repo),
                consumer_repos=[str(good), str(bad)],
                extracted_symbol="Foo",
                extraction_diff=EXTRACTION_DIFF_SIMPLE,
                consuming_diffs={
                    str(good): CONSUMING_DIFF_OLD_NEW,
                    str(bad): CONSUMING_DIFF_BAD,
                },
            )

        # REQ-CLONE-005: good repo's commit remains on local main
        # Brief defect: original assertion was `"new" in log.stdout` but
        # `git log --oneline` shows commit messages (refactor-job: ...),
        # NOT file contents. Correct assertion: more than one commit
        # (init + the new refactor-job commit).
        log = subprocess.run(
            ["git", "-C", str(good), "log", "--oneline"], capture_output=True, text=True
        )
        commit_lines = [ln for ln in log.stdout.splitlines() if ln.strip()]
        assert len(commit_lines) >= 2, f"expected 2+ commits, got: {commit_lines!r}"
        assert any("refactor-job" in ln for ln in commit_lines)

    async def test_dag_unhandled_exception_marks_failed(
        self, target_repo: Path, consumer_repo: Path, mock_backend: AsyncMock
    ) -> None:
        # Inject failure in detect_cluster_members
        with patch(
            "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
            new=AsyncMock(side_effect=RuntimeError("detect boom")),
        ):
            with pytest.raises(RuntimeError, match="detect boom"):
                await run_clone_refactor_dag(
                    refactor_job_id="job-005",
                    cluster_id="cluster-1",
                    mcp_backend=mock_backend,
                    target_repo=str(target_repo),
                    consumer_repos=[str(consumer_repo)],
                    extracted_symbol="Foo",
                    extraction_diff=EXTRACTION_DIFF,
                )
        # REQ-CLONE-010: terminal "failed" was written
        # Find the call to try_put_with_log_context with step_name="failed"
        failed_calls = [
            c for c in mock_backend.try_put_with_log_context.call_args_list
            if c.kwargs.get("log_context", {}).get("step_name") == "failed"
        ]
        assert len(failed_calls) == 1
        # REQ-CLONE-009: claim released in finally
        mock_backend.delete.assert_called_with("cluster/v1/cluster-1/in_flight")

    async def test_dag_commit_message_includes_refactor_job_id(
        self, target_repo: Path, consumer_repo: Path, mock_backend: AsyncMock
    ) -> None:
        # REQ-CLONE-012
        with patch(
            "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
            new=AsyncMock(return_value=[{"repo": str(target_repo)}]),
        ):
            await run_clone_refactor_dag(
                refactor_job_id="0193f5e2-7c8d-7abc-9def-1234567890ab",
                cluster_id="cluster-1",
                mcp_backend=mock_backend,
                target_repo=str(target_repo),
                consumer_repos=[str(consumer_repo)],
                extracted_symbol="Foo",
                extraction_diff=EXTRACTION_DIFF_SIMPLE,
                consuming_diffs={
                    str(consumer_repo): CONSUMING_DIFF_FROM_FOO,
                },
            )
        log = subprocess.run(
            ["git", "-C", str(consumer_repo), "log", "-1", "--format=%B"], capture_output=True, text=True
        )
        assert "refactor-job: 0193f5e2-7c8d-7abc-9def-1234567890ab" in log.stdout

    async def test_dag_git_commit_permanent_no_retry(
        self, target_repo: Path, consumer_repo: Path, mock_backend: AsyncMock
    ) -> None:
        # REQ-CLONE-013: GitCommitPermanent must NOT trigger Prefect retry.
        # We verify by counting git_commit invocations — only 1 expected.
        from mahavishnu.workflows import _git_ops
        original_commit = _git_ops.git_commit
        call_count = 0

        async def counting_commit(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise _git_ops.GitCommitPermanent(reason="test", stderr="x", exit_code=1)

        _git_ops.git_commit = counting_commit
        try:
            with patch(
                "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
                new=AsyncMock(return_value=[{"repo": str(target_repo)}]),
            ):
                with pytest.raises(_git_ops.GitCommitPermanent):
                    await run_clone_refactor_dag(
                        refactor_job_id="job-007",
                        cluster_id="cluster-1",
                        mcp_backend=mock_backend,
                        target_repo=str(target_repo),
                        consumer_repos=[str(consumer_repo)],
                        extracted_symbol="Foo",
                        extraction_diff=EXTRACTION_DIFF_SIMPLE,
                    )
            assert call_count == 1  # NO retry
        finally:
            _git_ops.git_commit = original_commit

    async def test_dag_state_writes_are_best_effort(
        self, target_repo: Path, consumer_repo: Path
    ) -> None:
        # REQ-CLONE-014: substrate failure is logged but DAG still runs
        backend = AsyncMock()
        backend.dag_key = lambda x: f"workflow/v1/{x}"
        backend.cluster_key = lambda x: f"cluster/v1/{x}"
        backend.in_flight_key = lambda x: f"cluster/v1/{x}/in_flight"
        backend.try_put_with_log_context = AsyncMock(return_value=False)  # substrate always fails
        backend.put = AsyncMock()
        backend.delete = AsyncMock()
        backend.get = AsyncMock(return_value=None)

        with patch(
            "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
            new=AsyncMock(return_value=[{"repo": str(target_repo)}]),
        ):
            result = await run_clone_refactor_dag(
                refactor_job_id="job-008",
                cluster_id="cluster-1",
                mcp_backend=backend,
                target_repo=str(target_repo),
                consumer_repos=[str(consumer_repo)],
                extracted_symbol="Foo",
                extraction_diff=EXTRACTION_DIFF_SIMPLE,
                consuming_diffs={
                    str(consumer_repo): CONSUMING_DIFF_FROM_FOO,
                },
            )
        # DAG still completes despite substrate failures
        assert result.status == "completed"

    async def test_dag_git_commit_failure_leaves_no_dirty_tree(
        self, target_repo: Path, tmp_path: Path, mock_backend: AsyncMock
    ) -> None:
        # REQ-CLONE-011: stash pop in finally → working tree clean post-failure
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        subprocess.run(["git", "init", str(consumer)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(consumer), "config", "user.email", "x@x"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(consumer), "config", "user.name", "X"], check=True, capture_output=True)
        (consumer / "c.py").write_text("init\n")
        subprocess.run(["git", "-C", str(consumer), "add", "."], check=True)
        subprocess.run(["git", "-C", str(consumer), "commit", "-m", "init"], check=True)

        from mahavishnu.workflows import _git_ops
        original_commit = _git_ops.git_commit

        async def failing_commit(*args, **kwargs):
            raise _git_ops.GitCommitPermanent(reason="test", stderr="x", exit_code=1)

        _git_ops.git_commit = failing_commit
        try:
            with patch(
                "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
                new=AsyncMock(return_value=[{"repo": str(target_repo)}]),
            ):
                with pytest.raises(_git_ops.GitCommitPermanent):
                    await run_clone_refactor_dag(
                        refactor_job_id="job-009",
                        cluster_id="cluster-1",
                        mcp_backend=mock_backend,
                        target_repo=str(target_repo),
                        consumer_repos=[str(consumer)],
                        extracted_symbol="Foo",
                        extraction_diff=EXTRACTION_DIFF_SIMPLE,
                        consuming_diffs={
                            str(consumer): CONSUMING_DIFF_INIT_NEW,
                        },
                    )
        finally:
            _git_ops.git_commit = original_commit

        # Verify working tree is clean
        status = subprocess.run(
            ["git", "-C", str(consumer), "status", "--porcelain"], capture_output=True, text=True
        )
        assert status.stdout == ""

    @pytest.mark.req(["REQ-CLONE-016"])
    async def test_dag_cancellation_persists_terminal_state(
        self, target_repo: Path, consumer_repo: Path, mock_backend: AsyncMock
    ) -> None:
        # REQ-CLONE-016: cancellation must persist terminal "cancelled" state
        # before re-raising CancelledError. Wrap run_clone_refactor_dag with
        # asyncio.wait_for(timeout=0.5) to trigger CancelledError mid-flow;
        # the @flow's `except asyncio.CancelledError` arm must call
        # _write_terminal_cancelled before propagating.

        async def slow_detect(*_args, **_kwargs):
            # Sleep long enough that asyncio.wait_for's timeout fires first.
            await asyncio.sleep(5)
            return [{"repo": str(target_repo), "match_score": 1.0}]

        with patch(
            "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
            new=AsyncMock(side_effect=slow_detect),
        ):
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(
                    run_clone_refactor_dag(
                        refactor_job_id="job-010",
                        cluster_id="cluster-1",
                        mcp_backend=mock_backend,
                        target_repo=str(target_repo),
                        consumer_repos=[str(consumer_repo)],
                        extracted_symbol="Foo",
                        extraction_diff=EXTRACTION_DIFF_SIMPLE,
                    ),
                    timeout=0.5,
                )

        # REQ-CLONE-016: terminal "cancelled" was written before the
        # CancelledError was re-raised (and converted by wait_for to TimeoutError).
        cancelled_calls = [
            c
            for c in mock_backend.try_put_with_log_context.call_args_list
            if c.kwargs.get("log_context", {}).get("step_name") == "cancelled"
        ]
        assert len(cancelled_calls) == 1
        # The cancelled outcome payload includes a timestamp.
        payload = cancelled_calls[0].args[1]
        assert "cancelled_at" in payload