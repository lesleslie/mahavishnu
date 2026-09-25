"""Integration tests for run_clone_refactor_dag.

Implements: REQ-CLONE-010, REQ-CLONE-011, REQ-CLONE-012, REQ-CLONE-013
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess
from unittest.mock import AsyncMock, patch
import warnings

import pytest

from mahavishnu.workflows.clone_refactor_workflow import (
    DAGResult,
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
        # REQ-CLONE-013: GitCommitPermanentError must NOT trigger Prefect retry.
        # We verify by counting git_commit invocations — only 1 expected.
        from mahavishnu.workflows import _git_ops
        original_commit = _git_ops.git_commit
        call_count = 0

        async def counting_commit(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise _git_ops.GitCommitPermanentError(reason="test", stderr="x", exit_code=1)

        _git_ops.git_commit = counting_commit
        try:
            with patch(
                "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
                new=AsyncMock(return_value=[{"repo": str(target_repo)}]),
            ):
                with pytest.raises(_git_ops.GitCommitPermanentError):
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
            raise _git_ops.GitCommitPermanentError(reason="test", stderr="x", exit_code=1)

        _git_ops.git_commit = failing_commit
        try:
            with patch(
                "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
                new=AsyncMock(return_value=[{"repo": str(target_repo)}]),
            ):
                with pytest.raises(_git_ops.GitCommitPermanentError):
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
        # before re-raising CancelledError.
        #
        # This test was previously implemented with asyncio.wait_for(timeout=0.5),
        # which was fragile: Prefect's @flow has setup overhead (transient server
        # bootstrap, flow-run registration) that can exceed 0.5s in some environments,
        # causing wait_for to cancel BEFORE the body ever reaches the awaited
        # `detect_cluster_members(...)` call. The `except asyncio.CancelledError`
        # arm in the flow body never ran, so the cancelled-state write never fired
        # and the test failed (no "cancelled" step in try_put_with_log_context calls).
        #
        # The deterministic pattern below uses asyncio.create_task +
        # task.cancel(): the test signals when the body has reached the awaited
        # call (via an asyncio.Event inside the slow mock), then explicitly
        # cancels. This is independent of Prefect's setup time.

        detect_started = asyncio.Event()

        async def slow_detect(*_args, **_kwargs):
            # Signal that the body has reached the awaited call, then sleep
            # long enough that we can reliably issue task.cancel() before this
            # coroutine returns. The flow's `except asyncio.CancelledError` arm
            # catches the cancellation that task.cancel() delivers here.
            detect_started.set()
            await asyncio.sleep(5)
            return [{"repo": str(target_repo), "match_score": 1.0}]

        with patch(
            "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
            new=AsyncMock(side_effect=slow_detect),
        ):
            task = asyncio.create_task(
                run_clone_refactor_dag(
                    refactor_job_id="job-010",
                    cluster_id="cluster-1",
                    mcp_backend=mock_backend,
                    target_repo=str(target_repo),
                    consumer_repos=[str(consumer_repo)],
                    extracted_symbol="Foo",
                    extraction_diff=EXTRACTION_DIFF_SIMPLE,
                ),
                name="test-cancel-dag",
            )

            # Wait for the body to reach the awaited detect call.
            # Bound this by something larger than worst-case Prefect setup time.
            await asyncio.wait_for(detect_started.wait(), timeout=10.0)

            # Cancel the in-flight flow. Cancellation propagates to
            # slow_detect's `await asyncio.sleep(5)` → raises CancelledError
            # into the flow body → body's `except asyncio.CancelledError`
            # arm runs `_write_terminal_cancelled` then re-raises.
            task.cancel()

            with pytest.raises(asyncio.CancelledError):
                await task

        # REQ-CLONE-016: terminal "cancelled" was written before re-raising.
        cancelled_calls = [
            c
            for c in mock_backend.try_put_with_log_context.call_args_list
            if c.kwargs.get("log_context", {}).get("step_name") == "cancelled"
        ]
        assert len(cancelled_calls) == 1
        # The cancelled outcome payload includes a timestamp.
        payload = cancelled_calls[0].args[1]
        assert "cancelled_at" in payload

    @pytest.mark.req(["REQ-CLONE-013"])
    async def test_dag_git_commit_transient_does_retry(
        self, target_repo: Path, consumer_repo: Path, mock_backend: AsyncMock
    ) -> None:
        """C1 fix: GitCommitTransientError must trigger Prefect retry.

        Pre-fix, retry_condition_fn used tenacity.retry_if_exception_type which
        has a 1-arg __call__(retry_state); Prefect invokes it with 3 args
        (task, run, state). Prefect's `except Exception: return False` swallow
        made call_count == 1 for ALL exception types — including transient ones
        that should retry. After the fix, the 3-arg predicate returns True for
        GitCommitTransientError so Prefect retries up to retries=2.
        """
        from mahavishnu.workflows import _git_ops
        original_commit = _git_ops.git_commit
        call_count = 0

        async def transient_twice(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise _git_ops.GitCommitTransientError(
                    reason="index_lock",
                    stderr="Unable to create .git/index.lock",
                )
            return await original_commit(*args, **kwargs)

        _git_ops.git_commit = transient_twice
        try:
            with patch(
                "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
                new=AsyncMock(return_value=[{"repo": str(target_repo)}]),
            ):
                result = await run_clone_refactor_dag(
                    refactor_job_id="job-011",
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
            # REQ-CLONE-013: target's write_canonical_symbol hit transient
            # twice and succeeded on 3rd attempt (call_count == 3 there); the
            # consumer's write_replacement_diff runs once after (call_count == 4
            # total). Pre-fix this would have been call_count == 1 with the
            # DAG propagating GitCommitTransientError out of the flow.
            assert call_count >= 3, (
                f"expected at least 3 calls (1 initial + 2 retries), got {call_count}"
            )
            assert result.status == "completed"
            assert result.consumer_commits[0].status == "completed"
        finally:
            _git_ops.git_commit = original_commit

    async def test_dag_stash_pop_failure_preserves_captured_sha(
        self, target_repo: Path, consumer_repo: Path, mock_backend: AsyncMock
    ) -> None:
        """C3 fix: stash_pop failure after a successful commit must propagate
        as a typed RepoCommit with the captured SHA — not be silently swallowed
        in a finally block returning status='completed' with a dirty tree.

        Pre-fix, the `finally: try stash_pop ... except StashPopFailedError: pass`
        pattern discarded the captured SHA (sha=None) and returned RepoCommit(
        status='completed') while the worktree was dirty. After the fix,
        stash_pop runs inside the main try; StashPopFailedError is caught with
        sha preserved; finally only runs cleanup if commit failed.

        Note: we mock BOTH stash_push (return a non-None ref so the workflow
        takes the `if stash_ref is not None: stash_pop(...)` branch) and
        stash_pop (raise StashPopFailedError). The test fixtures start with a
        clean working tree, so the unmodified stash_push would return
        None and skip stash_pop entirely.
        """
        from mahavishnu.workflows import _git_ops
        original_stash_push = _git_ops.stash_push
        original_stash_pop = _git_ops.stash_pop

        async def fake_stash_push(repo_path):
            # Don't actually create a stash entry; just return a ref so the
            # workflow's `if stash_ref is not None` branch executes.
            return "stash@{0}"

        async def always_failing_stash_pop(repo_path, stash_ref="stash@{0}"):
            raise _git_ops.StashPopFailedError(
                stderr="conflict marker present", exit_code=1
            )

        _git_ops.stash_push = fake_stash_push
        _git_ops.stash_pop = always_failing_stash_pop
        try:
            with patch(
                "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
                new=AsyncMock(return_value=[{"repo": str(target_repo)}]),
            ):
                result = await run_clone_refactor_dag(
                    refactor_job_id="job-012",
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
            # C3 fix: at least one StashPopFailedError RepoCommit with captured SHA.
            stash_failures: list[tuple[str, object]] = []
            if result.target_commit and result.target_commit.error_type == "StashPopFailedError":
                stash_failures.append(("target", result.target_commit))
            for c in result.consumer_commits:
                if c.error_type == "StashPopFailedError":
                    stash_failures.append((c.repo, c))
            assert stash_failures, (
                "expected at least one StashPopFailedError RepoCommit; "
                f"target={result.target_commit} "
                f"consumers={result.consumer_commits}"
            )
            for repo, rc in stash_failures:
                # C3 fix: captured SHA is preserved (was None pre-fix)
                assert rc.sha is not None, (
                    f"{repo}: stash_pop failed after commit; "
                    f"captured SHA must be preserved (got None)"
                )
                assert rc.status == "failed"
                assert rc.error_stderr is not None
                assert "conflict marker" in rc.error_stderr
            assert result.status == "failed"
        finally:
            _git_ops.stash_push = original_stash_push
            _git_ops.stash_pop = original_stash_pop