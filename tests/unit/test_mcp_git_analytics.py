"""Unit tests for mahavishnu.mcp.tools.git_analytics.

The module exposes ``register_git_analytics_tools(server, mcp_client,
rbac_manager)`` which decorates 3 FastMCP tools. All tools delegate to
``DharaAdapter`` and (optionally) ``SessionBuddyIntegration``; we mock
both via ``patch``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.mcp.tools import git_analytics

pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


class _StubMCP:
    """Minimal FastMCP stand-in that captures decorated functions."""

    def __init__(self) -> None:
        self.tools: dict[str, object] = {}
        self.app = MagicMock(dhara_url="http://dhara:8683")

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


@pytest.fixture
def server() -> _StubMCP:
    return _StubMCP()


@pytest.fixture
def registered(server):
    """Register the 3 git analytics tools onto a stub MCP server."""
    mcp_client = MagicMock()
    git_analytics.register_git_analytics_tools(server, mcp_client, rbac_manager=None)
    return server


@pytest.fixture
def fake_dhara():
    """Return a MagicMock for the DharaAdapter constructor."""
    instance = MagicMock()
    instance.query_time_series = AsyncMock(return_value=[])
    instance.aggregate_patterns = AsyncMock(return_value=[])
    return instance


# =============================================================================
# Registration
# =============================================================================


class TestRegistration:
    """All 3 git analytics tools should be registered."""

    def test_registers_three_tools(self, registered):
        """The 3 public tools should be on the stub server after register()."""
        expected = {
            "get_git_velocity_dashboard",
            "get_repository_health",
            "get_cross_project_patterns",
        }
        assert expected.issubset(set(registered.tools.keys()))


# =============================================================================
# get_git_velocity_dashboard
# =============================================================================


class TestGitVelocityDashboard:
    """get_git_velocity_dashboard aggregates commits/branches/conflicts."""

    @pytest.mark.asyncio
    async def test_success_aggregates_per_repo(self, registered, fake_dhara):
        """Each repo should get per-day commits, branches, conflicts."""
        fake_dhara.query_time_series = AsyncMock(
            side_effect=[
                [
                    {"commits": 10, "branch_switches": 2, "merge_conflicts": 1},
                    {"commits": 5, "branch_switches": 1, "merge_conflicts": 0},
                ],
                [{"commits": 7, "branch_switches": 3, "merge_conflicts": 0}],
            ]
        )

        with patch("mahavishnu.core.dhara_adapter.DharaAdapter", return_value=fake_dhara):
            result = await registered.tools["get_git_velocity_dashboard"](
                repo_paths=["/work/repo-a", "/work/repo-b"],
                days_back=10,
                user_id="u1",
            )

        assert result["status"] == "success"
        repos = result["result"]["repositories"]
        assert "repo-a" in repos
        assert "repo-b" in repos
        # 15 commits / 10 days = 1.5
        assert repos["repo-a"]["commits_per_day"] == 1.5
        # total commits 22 over 20 repo-days = 1.1
        assert result["result"]["aggregated"]["average_velocity"] == 1.1
        assert result["result"]["aggregated"]["total_projects"] == 2

    @pytest.mark.asyncio
    async def test_missing_app_returns_error(self, registered, fake_dhara):
        """Without a server.app attribute, return error dict."""
        registered.app = None
        with patch("mahavishnu.core.dhara_adapter.DharaAdapter", return_value=fake_dhara):
            result = await registered.tools["get_git_velocity_dashboard"](
                repo_paths=["/x/repo-a"], user_id="u1"
            )
        assert result["status"] == "error"
        assert "App instance" in result["error"]

    @pytest.mark.asyncio
    async def test_exception_returns_error(self, registered, fake_dhara):
        """An exception in DharaAdapter should be caught and returned as error."""
        with patch(
            "mahavishnu.core.dhara_adapter.DharaAdapter",
            side_effect=RuntimeError("boom"),
        ):
            result = await registered.tools["get_git_velocity_dashboard"](
                repo_paths=["/x/repo-a"], user_id="u1"
            )
        assert result["status"] == "error"
        assert "boom" in result["error"]


# =============================================================================
# get_repository_health
# =============================================================================


class TestRepositoryHealth:
    """get_repository_health returns PR/branch counts and a health score."""

    @pytest.mark.asyncio
    async def test_calculates_health_score(self, registered, fake_dhara):
        """With no stale PRs/branches and full success, score should be 100."""
        fake_dhara.query_time_series = AsyncMock(
            return_value=[
                {"stale_prs": 0, "stale_branches": 0, "open_prs": 3},
            ]
        )

        def _make_sb_integration(metrics=None):
            instance = MagicMock()
            instance.get_workflow_metrics = AsyncMock(return_value=metrics or {"success_rate": 100})
            instance.detect_patterns = AsyncMock(return_value=[])
            instance.get_quality_patterns = AsyncMock(return_value=[])
            return instance

        with (
            patch("mahavishnu.core.dhara_adapter.DharaAdapter", return_value=fake_dhara),
            patch(
                "mahavishnu.session_buddy.integration.SessionBuddyIntegration",
                return_value=_make_sb_integration(),
            ),
        ):
            result = await registered.tools["get_repository_health"](
                repo_path="/work/repo-a", user_id="u1"
            )

        assert result["status"] == "success"
        r = result["result"]
        assert r["repository"] == "repo-a"
        assert r["pull_requests"]["open"] == 3
        assert r["health_score"] == 100
        assert r["health_status"] == "excellent"

    @pytest.mark.asyncio
    async def test_stale_prs_lower_score(self, registered, fake_dhara):
        """Stale PRs should reduce the score (5 points per, capped at 30)."""
        fake_dhara.query_time_series = AsyncMock(
            return_value=[{"stale_prs": 4, "stale_branches": 0, "open_prs": 5}]
        )

        sb = MagicMock()
        sb.get_workflow_metrics = AsyncMock(return_value={"success_rate": 100})

        with (
            patch("mahavishnu.core.dhara_adapter.DharaAdapter", return_value=fake_dhara),
            patch(
                "mahavishnu.session_buddy.integration.SessionBuddyIntegration",
                return_value=sb,
            ),
        ):
            result = await registered.tools["get_repository_health"](
                repo_path="/x/repo-a", user_id="u1"
            )

        # 100 - 20 (4 * 5) = 80
        assert result["result"]["health_score"] == 80
        assert result["result"]["health_status"] == "good"

    @pytest.mark.asyncio
    async def test_session_buddy_unavailable(self, registered, fake_dhara):
        """When session-buddy integration raises, workflow_health should be unavailable."""
        fake_dhara.query_time_series = AsyncMock(
            return_value=[{"stale_prs": 0, "stale_branches": 0, "open_prs": 0}]
        )
        with (
            patch("mahavishnu.core.dhara_adapter.DharaAdapter", return_value=fake_dhara),
            patch(
                "mahavishnu.session_buddy.integration.SessionBuddyIntegration",
                side_effect=RuntimeError("down"),
            ),
        ):
            result = await registered.tools["get_repository_health"](
                repo_path="/x/repo-a", user_id="u1"
            )
        assert result["status"] == "success"
        assert result["result"]["workflow_performance"]["status"] == "unavailable"

    @pytest.mark.asyncio
    async def test_missing_app(self, registered, fake_dhara):
        """Missing server.app should yield error dict."""
        registered.app = None
        with patch("mahavishnu.core.dhara_adapter.DharaAdapter", return_value=fake_dhara):
            result = await registered.tools["get_repository_health"](
                repo_path="/x/repo-a", user_id="u1"
            )
        assert result["status"] == "error"


# =============================================================================
# get_cross_project_patterns
# =============================================================================


class TestCrossProjectPatterns:
    """get_cross_project_patterns aggregates git/workflow/quality patterns."""

    @pytest.mark.asyncio
    async def test_returns_aggregated_payload(self, registered, fake_dhara):
        """Successful run returns analysis_period and pattern sections."""
        fake_dhara.aggregate_patterns = AsyncMock(
            return_value=[
                {"type": "high_velocity", "repository": "repo-a"},
            ]
        )

        sb = MagicMock()
        sb.detect_patterns = AsyncMock(return_value=[])
        sb.get_quality_patterns = AsyncMock(return_value=[])

        with (
            patch("mahavishnu.core.dhara_adapter.DharaAdapter", return_value=fake_dhara),
            patch(
                "mahavishnu.session_buddy.integration.SessionBuddyIntegration",
                return_value=sb,
            ),
        ):
            result = await registered.tools["get_cross_project_patterns"](user_id="u1")

        assert result["status"] == "success"
        r = result["result"]
        assert r["analysis_period"] == "P90 days"
        assert isinstance(r["git_patterns"], list)
        assert isinstance(r["workflow_patterns"], list)
        assert isinstance(r["quality_patterns"], list)
        assert isinstance(r["correlations"], list)
        assert isinstance(r["insights"], list)
        # With only one high-velocity repo and no failures/quality issues,
        # there should be no correlations.
        assert r["correlations"] == []
        # And one of the insights should mention velocity.
        assert any("velocity" in s.lower() for s in r["insights"])

    @pytest.mark.asyncio
    async def test_high_velocity_with_quality_issues(self, registered, fake_dhara):
        """A high-velocity repo with high-severity quality issues should correlate."""
        fake_dhara.aggregate_patterns = AsyncMock(
            return_value=[{"type": "high_velocity", "repository": "repo-a"}]
        )
        sb = MagicMock()
        sb.detect_patterns = AsyncMock(return_value=[])
        sb.get_quality_patterns = AsyncMock(
            return_value=[{"severity": "high", "repository": "repo-a"}]
        )
        with (
            patch("mahavishnu.core.dhara_adapter.DharaAdapter", return_value=fake_dhara),
            patch(
                "mahavishnu.session_buddy.integration.SessionBuddyIntegration",
                return_value=sb,
            ),
        ):
            result = await registered.tools["get_cross_project_patterns"](
                days_back=30, min_occurrences=1, user_id="u1"
            )

        assert result["status"] == "success"
        corr_types = [c["type"] for c in result["result"]["correlations"]]
        assert "velocity_quality_correlation" in corr_types

    @pytest.mark.asyncio
    async def test_failing_workflow_pattern(self, registered, fake_dhara):
        """Failing workflows should be flagged as a correlation."""
        fake_dhara.aggregate_patterns = AsyncMock(return_value=[])
        sb = MagicMock()
        sb.detect_patterns = AsyncMock(return_value=[{"name": "wf1", "success_rate": 50}])
        sb.get_quality_patterns = AsyncMock(return_value=[])
        with (
            patch("mahavishnu.core.dhara_adapter.DharaAdapter", return_value=fake_dhara),
            patch(
                "mahavishnu.session_buddy.integration.SessionBuddyIntegration",
                return_value=sb,
            ),
        ):
            result = await registered.tools["get_cross_project_patterns"](user_id="u1")

        corr_types = [c["type"] for c in result["result"]["correlations"]]
        assert "workflow_failure_pattern" in corr_types

    @pytest.mark.asyncio
    async def test_exception_caught(self, registered, fake_dhara):
        """An exception should be reported as an error result, not raise."""
        with patch(
            "mahavishnu.core.dhara_adapter.DharaAdapter",
            side_effect=RuntimeError("nope"),
        ):
            result = await registered.tools["get_cross_project_patterns"](user_id="u1")
        assert result["status"] == "error"
        assert "nope" in result["error"]


# =============================================================================
# Health score edge cases (via get_repository_health)
# =============================================================================


class TestHealthScoreEdgeCases:
    """Verify the health-score formula via the public tool."""

    @pytest.mark.asyncio
    async def test_health_score_critical(self, registered, fake_dhara):
        """Many stale PRs/branches + low workflow success should yield critical."""
        fake_dhara.query_time_series = AsyncMock(
            return_value=[{"stale_prs": 50, "stale_branches": 50, "open_prs": 100}]
        )
        sb = MagicMock()
        sb.get_workflow_metrics = AsyncMock(return_value={"success_rate": 0})
        with (
            patch("mahavishnu.core.dhara_adapter.DharaAdapter", return_value=fake_dhara),
            patch(
                "mahavishnu.session_buddy.integration.SessionBuddyIntegration",
                return_value=sb,
            ),
        ):
            result = await registered.tools["get_repository_health"](repo_path="/x/r", user_id="u1")
        # Score floors at 0, status='critical'
        assert result["result"]["health_score"] == 0
        assert result["result"]["health_status"] == "critical"

    @pytest.mark.asyncio
    async def test_health_score_fair(self, registered, fake_dhara):
        """Mid-range score should yield 'fair' status."""
        fake_dhara.query_time_series = AsyncMock(
            return_value=[{"stale_prs": 8, "stale_branches": 0, "open_prs": 10}]
        )
        sb = MagicMock()
        sb.get_workflow_metrics = AsyncMock(return_value={"success_rate": 100})
        with (
            patch("mahavishnu.core.dhara_adapter.DharaAdapter", return_value=fake_dhara),
            patch(
                "mahavishnu.session_buddy.integration.SessionBuddyIntegration",
                return_value=sb,
            ),
        ):
            result = await registered.tools["get_repository_health"](repo_path="/x/r", user_id="u1")
        # 100 - min(40, 30) = 70, status='fair'
        assert result["result"]["health_score"] == 70
        assert result["result"]["health_status"] == "fair"
