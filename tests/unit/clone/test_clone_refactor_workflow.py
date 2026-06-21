"""Unit tests for mahavishnu.workflows.clone_refactor_workflow — Task 13 Phase B."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.workflows.clone_refactor_workflow import (
    CloneRefactorResult,
    ConsumingPR,
    ExtractionPR,
    create_consuming_pr,
    create_extraction_pr,
    run_clone_refactor_dag,
    wait_for_merge,
)

pytestmark = pytest.mark.unit

CLUSTER_ID = "abc1234567890def"
TARGET_REPO = "oneiric"
CONSUMER_REPOS = ["crackerjack", "dhara"]
SYMBOL = "parse_clone_groups"
DIFF = "--- a/old.py\n+++ b/new.py\n@@ -1 +1 @@\n-dup\n+extracted"


# ---------------------------------------------------------------------------
# create_extraction_pr
# ---------------------------------------------------------------------------


class TestCreateExtractionPr:
    async def test_stub_mode_returns_open_pr(self):
        pr = await create_extraction_pr(
            cluster_id=CLUSTER_ID,
            target_repo=TARGET_REPO,
            extracted_symbol=SYMBOL,
            diff=DIFF,
            gh_client=None,
        )
        assert isinstance(pr, ExtractionPR)
        assert pr.status == "open"
        assert TARGET_REPO in pr.repo

    async def test_real_client_calls_create_pr(self):
        gh = AsyncMock()
        gh.create_pr = AsyncMock(
            return_value={"html_url": "https://github.com/oneiric/pulls/1"}
        )
        pr = await create_extraction_pr(
            cluster_id=CLUSTER_ID,
            target_repo=TARGET_REPO,
            extracted_symbol=SYMBOL,
            diff=DIFF,
            gh_client=gh,
        )
        assert pr.pr_url == "https://github.com/oneiric/pulls/1"
        gh.create_pr.assert_called_once()

    async def test_client_failure_raises_runtime_error(self):
        gh = AsyncMock()
        gh.create_pr = AsyncMock(side_effect=RuntimeError("API error"))
        with pytest.raises(RuntimeError, match="Failed to create extraction PR"):
            await create_extraction_pr(
                cluster_id=CLUSTER_ID,
                target_repo=TARGET_REPO,
                extracted_symbol=SYMBOL,
                diff=DIFF,
                gh_client=gh,
            )


# ---------------------------------------------------------------------------
# wait_for_merge
# ---------------------------------------------------------------------------


class TestWaitForMerge:
    async def test_stub_mode_returns_merged_immediately(self):
        pr = ExtractionPR(
            pr_url="https://github.com/oneiric/pulls/1", repo="oneiric", status="open"
        )
        result = await wait_for_merge(pr, gh_client=None)
        assert result.status == "merged"

    async def test_polls_until_merged(self):
        gh = AsyncMock()
        gh.get_pr_status = AsyncMock(side_effect=["open", "open", "merged"])
        pr = ExtractionPR(pr_url="https://github.com/oneiric/pulls/2", repo="oneiric")

        result = await wait_for_merge(pr, gh_client=gh, poll_interval=0, timeout=10)
        assert result.status == "merged"
        assert gh.get_pr_status.call_count == 3

    async def test_returns_closed_when_pr_closed(self):
        gh = AsyncMock()
        gh.get_pr_status = AsyncMock(return_value="closed")
        pr = ExtractionPR(pr_url="https://github.com/oneiric/pulls/3", repo="oneiric")

        result = await wait_for_merge(pr, gh_client=gh, poll_interval=0, timeout=10)
        assert result.status == "closed"

    async def test_raises_on_timeout(self):
        gh = AsyncMock()
        gh.get_pr_status = AsyncMock(return_value="open")
        pr = ExtractionPR(pr_url="https://github.com/oneiric/pulls/4", repo="oneiric")

        with pytest.raises(RuntimeError, match="timed out"):
            await wait_for_merge(pr, gh_client=gh, poll_interval=0, timeout=0)


# ---------------------------------------------------------------------------
# create_consuming_pr
# ---------------------------------------------------------------------------


class TestCreateConsumingPr:
    async def test_stub_mode_returns_open_pr(self):
        pr = await create_consuming_pr(
            cluster_id=CLUSTER_ID,
            consumer_repo="crackerjack",
            extracted_symbol=SYMBOL,
            extraction_target_repo=TARGET_REPO,
            diff=DIFF,
            gh_client=None,
        )
        assert isinstance(pr, ConsumingPR)
        assert pr.status == "open"
        assert pr.repo == "crackerjack"

    async def test_real_client_calls_create_pr(self):
        gh = AsyncMock()
        gh.create_pr = AsyncMock(
            return_value={"html_url": "https://github.com/crackerjack/pulls/5"}
        )
        pr = await create_consuming_pr(
            cluster_id=CLUSTER_ID,
            consumer_repo="crackerjack",
            extracted_symbol=SYMBOL,
            extraction_target_repo=TARGET_REPO,
            diff=DIFF,
            gh_client=gh,
        )
        assert pr.pr_url == "https://github.com/crackerjack/pulls/5"


# ---------------------------------------------------------------------------
# run_clone_refactor_dag — full DAG integration tests
# ---------------------------------------------------------------------------


class TestRunCloneRefactorDag:
    async def test_stub_mode_full_dag(self):
        """Stub mode completes all three steps with no external I/O."""
        result = await run_clone_refactor_dag(
            cluster_id=CLUSTER_ID,
            target_repo=TARGET_REPO,
            consumer_repos=CONSUMER_REPOS,
            extracted_symbol=SYMBOL,
            extraction_diff=DIFF,
            gh_client=None,
        )
        assert isinstance(result, CloneRefactorResult)
        assert result.extraction_pr is not None
        assert result.extraction_pr.status == "merged"
        assert len(result.consuming_prs) == len(CONSUMER_REPOS)
        assert not result.cancelled
        assert result.error is None

    async def test_dag_cancels_consuming_prs_when_extraction_pr_closed(self):
        """If the extraction PR is closed, consuming PRs must NOT be opened (M-NEW-7)."""
        gh = AsyncMock()
        gh.create_pr = AsyncMock(
            return_value={"html_url": "https://github.com/oneiric/pulls/1"}
        )
        gh.get_pr_status = AsyncMock(return_value="closed")

        result = await run_clone_refactor_dag(
            cluster_id=CLUSTER_ID,
            target_repo=TARGET_REPO,
            consumer_repos=CONSUMER_REPOS,
            extracted_symbol=SYMBOL,
            extraction_diff=DIFF,
            gh_client=gh,
        )
        assert result.cancelled is True
        assert result.consuming_prs == []

    async def test_dag_creates_consuming_prs_in_parallel(self):
        """All consuming PRs are created concurrently after extraction PR merges."""
        call_order: list[str] = []

        async def fake_create_pr(repo, title, body, diff):
            call_order.append(repo)
            return {"html_url": f"https://github.com/{repo}/pulls/99"}

        gh = AsyncMock()
        gh.create_pr = AsyncMock(side_effect=fake_create_pr)
        gh.get_pr_status = AsyncMock(return_value="merged")

        result = await run_clone_refactor_dag(
            cluster_id=CLUSTER_ID,
            target_repo=TARGET_REPO,
            consumer_repos=CONSUMER_REPOS,
            extracted_symbol=SYMBOL,
            extraction_diff=DIFF,
            gh_client=gh,
        )
        assert len(result.consuming_prs) == len(CONSUMER_REPOS)
        for pr in result.consuming_prs:
            assert pr.status == "open"

    async def test_dag_handles_partial_consuming_pr_failure(self):
        """Failed consuming PRs are logged but do not abort the whole DAG."""
        gh = AsyncMock()
        call_count = 0

        async def selective_fail(repo, title, body, diff):
            nonlocal call_count
            call_count += 1
            if repo == TARGET_REPO:
                return {"html_url": f"https://github.com/{repo}/pulls/1"}
            if call_count == 3:
                raise RuntimeError("PR creation failed")
            return {"html_url": f"https://github.com/{repo}/pulls/{call_count}"}

        gh.create_pr = AsyncMock(side_effect=selective_fail)
        gh.get_pr_status = AsyncMock(return_value="merged")

        result = await run_clone_refactor_dag(
            cluster_id=CLUSTER_ID,
            target_repo=TARGET_REPO,
            consumer_repos=["crackerjack", "dhara", "akosha"],
            extracted_symbol=SYMBOL,
            extraction_diff=DIFF,
            gh_client=gh,
        )
        assert result.error is None
        assert not result.cancelled
        assert len(result.consuming_prs) < 3

    async def test_dag_extraction_pr_failure_short_circuits(self):
        """If create_extraction_pr raises, the DAG aborts before Steps 2 and 3."""
        gh = AsyncMock()
        gh.create_pr = AsyncMock(side_effect=RuntimeError("network error"))

        result = await run_clone_refactor_dag(
            cluster_id=CLUSTER_ID,
            target_repo=TARGET_REPO,
            consumer_repos=CONSUMER_REPOS,
            extracted_symbol=SYMBOL,
            extraction_diff=DIFF,
            gh_client=gh,
        )
        assert result.error is not None
        assert "create_extraction_pr failed" in result.error
        assert result.consuming_prs == []
