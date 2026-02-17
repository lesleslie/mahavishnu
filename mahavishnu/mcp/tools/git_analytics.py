"""MCP tools for Git analytics and cross-project aggregation.

This module provides tools for symbiotic ecosystem integration, aggregating
data from Crackerjack (git metrics), Session-Buddy (workflow performance),
and providing cross-project intelligence.
"""

from typing import Any, Dict, List
from datetime import datetime, timedelta

from ...core.permissions import Permission, RBACManager
from ...mcp.auth import require_mcp_auth


def register_git_analytics_tools(
    server, mcp_client, rbac_manager: RBACManager | None = None
):
    """Register Git analytics tools with MCP server.

    Args:
        server: FastMCP server instance
        mcp_client: MCP client for cross-service communication
        rbac_manager: Optional RBAC manager for authorization
    """

    @server.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager,
        required_permission=Permission.READ_REPO,
        require_repo_param="repo_path",
    )
    async def get_git_velocity_dashboard(
        repo_paths: List[str],
        days_back: int = 30,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Get git velocity dashboard across multiple repositories.

        Aggregates commit velocity, branch switch frequency, and merge
        conflict rates from Dhruva time-series storage where Crackerjack
        stores git metrics.

        Args:
            repo_paths: List of repository paths to analyze
            days_back: Number of days to look back for metrics (default: 30)
            user_id: Authenticated user ID (injected by @require_mcp_auth)

        Returns:
            Dictionary with per-project and aggregated velocity metrics
        """
        try:
            # Query Dhruva for git metrics (time-series data)
            from ...core.dhruva_adapter import DhruvaAdapter

            app = getattr(server, "app", None)
            if not app:
                return {"status": "error", "error": "App instance not available in server context"}

            dhruva = DhruvaAdapter(app.dhruva_url)

            # Calculate date threshold
            threshold_date = datetime.now() - timedelta(days=days_back)

            results = {}
            total_commits = 0
            total_branch_switches = 0
            total_merge_conflicts = 0

            for repo_path in repo_paths:
                # Query time-series metrics for this repository
                metrics = await dhruva.query_time_series(
                    metric_type="git_velocity",
                    entity_id=repo_path,
                    start_date=threshold_date.isoformat(),
                )

                repo_name = repo_path.split("/")[-1]

                # Aggregate metrics for this repo
                repo_commits = sum(m.get("commits", 0) for m in metrics)
                repo_branches = sum(m.get("branch_switches", 0) for m in metrics)
                repo_conflicts = sum(m.get("merge_conflicts", 0) for m in metrics)

                results[repo_name] = {
                    "commits_per_day": repo_commits / max(days_back, 1),
                    "branch_switches_per_day": repo_branches / max(days_back, 1),
                    "merge_conflicts_per_day": repo_conflicts / max(days_back, 1),
                    "trend": "increasing" if repo_commits > 0 else "stable",
                }

                total_commits += repo_commits
                total_branch_switches += repo_branches
                total_merge_conflicts += repo_conflicts

            # Calculate aggregated metrics
            avg_velocity = total_commits / max(len(repo_paths) * days_back, 1)
            active_projects = len([r for r in results.values() if r["trend"] == "increasing"])

            return {
                "status": "success",
                "result": {
                    "repositories": results,
                    "aggregated": {
                        "average_velocity": round(avg_velocity, 2),
                        "active_projects": active_projects,
                        "total_projects": len(repo_paths),
                        "analysis_period_days": days_back,
                    },
                    "generated_at": datetime.now().isoformat(),
                },
            }

        except Exception as e:
            return {
                "status": "error",
                "error": f"Failed to get git velocity dashboard: {str(e)}"
            }

    @server.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager,
        required_permission=Permission.READ_REPO,
        require_repo_param="repo_path",
    )
    async def get_repository_health(
        repo_path: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Get repository health metrics including PRs and branches.

        Queries git metrics and combines with workflow performance data from
        Session-Buddy to provide comprehensive repository health assessment.

        Args:
            repo_path: Path to repository to analyze
            user_id: Authenticated user ID (injected by @require_mcp_auth)

        Returns:
            Repository health metrics including stale PRs, branches, and quality scores
        """
        try:
            from ...core.dhruva_adapter import DhruvaAdapter

            app = getattr(server, "app", None)
            if not app:
                return {"status": "error", "error": "App instance not available in server context"}

            dhruva = DhruvaAdapter(app.dhruva_url)
            repo_name = repo_path.split("/")[-1]

            # Query git metrics from Dhruva
            git_metrics = await dhruva.query_time_series(
                metric_type="repository_health",
                entity_id=repo_path,
                limit=100,
            )

            # Extract health indicators
            stale_prs = sum(m.get("stale_prs", 0) for m in git_metrics)
            stale_branches = sum(m.get("stale_branches", 0) for m in git_metrics)
            open_prs = sum(m.get("open_prs", 0) for m in git_metrics)

            # Query Session-Buddy for workflow performance
            workflow_health = await _query_session_buddy_metrics(app, repo_path)

            # Calculate overall health score (0-100)
            health_score = _calculate_health_score(
                stale_prs, stale_branches, workflow_health
            )

            return {
                "status": "success",
                "result": {
                    "repository": repo_name,
                    "path": repo_path,
                    "pull_requests": {
                        "open": open_prs,
                        "stale": stale_prs,
                        "stale_threshold_days": 7,
                    },
                    "branches": {
                        "stale": stale_branches,
                        "stale_threshold_days": 30,
                    },
                    "workflow_performance": workflow_health,
                    "health_score": health_score,
                    "health_status": _get_health_status(health_score),
                    "assessed_at": datetime.now().isoformat(),
                },
            }

        except Exception as e:
            return {
                "status": "error",
                "error": f"Failed to get repository health: {str(e)}"
            }

    @server.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager,
        required_permission=Permission.READ_REPO,
    )
    async def get_cross_project_patterns(
        days_back: int = 90,
        min_occurrences: int = 3,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Detect patterns across all repositories in the ecosystem.

        Analyzes git metrics, workflow performance, and quality scores to
        identify cross-project patterns such as:
        - Most common issue types
        - Repositories with high velocity
        - Recurring quality issues
        - Correlation between velocity and quality

        Args:
            days_back: Number of days to analyze for patterns (default: 90)
            min_occurrences: Minimum pattern occurrences to report (default: 3)
            user_id: Authenticated user ID (injected by @require_mcp_auth)

        Returns:
            Cross-project patterns with insights and correlations
        """
        try:
            from ...core.dhruva_adapter import DhruvaAdapter

            app = getattr(server, "app", None)
            if not app:
                return {"status": "error", "error": "App instance not available in server context"}

            dhruva = DhruvaAdapter(app.dhruva_url)

            # Query all metrics for the analysis period
            threshold_date = (datetime.now() - timedelta(days=days_back)).isoformat()

            # Get git metrics patterns
            git_patterns = await dhruva.aggregate_patterns(
                start_date=threshold_date,
                min_occurrences=min_occurrences,
            )

            # Get workflow patterns from Session-Buddy
            workflow_patterns = await _query_session_buddy_patterns(app, days_back)

            # Get quality patterns from Session-Buddy
            quality_patterns = await _query_quality_patterns(app, days_back)

            # Analyze correlations
            correlations = _analyze_correlations(
                git_patterns, workflow_patterns, quality_patterns
            )

            return {
                "status": "success",
                "result": {
                    "analysis_period": f"P{days_back} days",
                    "git_patterns": git_patterns,
                    "workflow_patterns": workflow_patterns,
                    "quality_patterns": quality_patterns,
                    "correlations": correlations,
                    "insights": _generate_insights(
                        git_patterns, workflow_patterns, correlations
                    ),
                    "generated_at": datetime.now().isoformat(),
                },
            }

        except Exception as e:
            return {
                "status": "error",
                "error": f"Failed to get cross-project patterns: {str(e)}"
            }

    async def _query_session_buddy_metrics(app, repo_path: str) -> Dict[str, Any]:
        """Query Session-Buddy for workflow performance metrics.

        Args:
            app: Mahavishnu app instance
            repo_path: Repository path

        Returns:
            Workflow performance metrics
        """
        try:
            from ...session_buddy.integration import SessionBuddyIntegration

            integration = SessionBuddyIntegration(app)
            return await integration.get_workflow_metrics(repo_path)
        except Exception:
            # Session-Buddy might not be available or configured
            return {"status": "unavailable", "metrics": {}}

    async def _query_session_buddy_patterns(app, days_back: int) -> List[Dict]:
        """Query Session-Buddy for workflow patterns.

        Args:
            app: Mahavishnu app instance
            days_back: Days to analyze

        Returns:
            List of workflow patterns
        """
        try:
            from ...session_buddy.integration import SessionBuddyIntegration

            integration = SessionBuddyIntegration(app)
            return await integration.detect_patterns(days_back)
        except Exception:
            return []

    async def _query_quality_patterns(app, days_back: int) -> List[Dict]:
        """Query Session-Buddy for quality patterns.

        Args:
            app: Mahavishnu app instance
            days_back: Days to analyze

        Returns:
            List of quality patterns
        """
        try:
            from ...session_buddy.integration import SessionBuddyIntegration

            integration = SessionBuddyIntegration(app)
            return await integration.get_quality_patterns(days_back)
        except Exception:
            return []

    def _calculate_health_score(
        stale_prs: int, stale_branches: int, workflow_health: Dict
    ) -> int:
        """Calculate overall repository health score.

        Score components:
        - Stale PRs (weight: 30%)
        - Stale branches (weight: 20%)
        - Workflow success rate (weight: 50%)

        Args:
            stale_prs: Number of stale pull requests
            stale_branches: Number of stale branches
            workflow_health: Workflow performance metrics

        Returns:
            Health score from 0-100
        """
        # Base score starts at 100
        score = 100

        # Penalize for stale PRs (5 points each)
        score -= min(stale_prs * 5, 30)

        # Penalize for stale branches (3 points each)
        score -= min(stale_branches * 3, 20)

        # Factor in workflow success rate (50% weight)
        workflow_score = workflow_health.get("success_rate", 100)
        score -= (100 - workflow_score) * 0.5

        return max(0, min(100, int(score)))

    def _get_health_status(score: int) -> str:
        """Convert health score to status category.

        Args:
            score: Health score (0-100)

        Returns:
            Status category
        """
        if score >= 90:
            return "excellent"
        elif score >= 75:
            return "good"
        elif score >= 60:
            return "fair"
        elif score >= 40:
            return "poor"
        else:
            return "critical"

    def _analyze_correlations(
        git_patterns: List[Dict],
        workflow_patterns: List[Dict],
        quality_patterns: List[Dict],
    ) -> Dict[str, Any]:
        """Analyze correlations between different pattern types.

        Args:
            git_patterns: Git activity patterns
            workflow_patterns: Workflow execution patterns
            quality_patterns: Code quality patterns

        Returns:
            Correlation analysis results
        """
        correlations = []

        # Analyze velocity vs quality
        high_velocity_repos = {
            p.get("repository", "") for p in git_patterns
            if p.get("type") == "high_velocity"
        }

        quality_issues = [
            q for q in quality_patterns
            if q.get("severity") == "high" and q.get("repository") in high_velocity_repos
        ]

        if quality_issues:
            correlations.append({
                "type": "velocity_quality_correlation",
                "description": "High velocity correlates with quality issues",
                "severity": "warning" if len(quality_issues) < 5 else "high",
                "affected_repositories": list(high_velocity_repos),
            })

        # Analyze workflow failures
        failing_workflows = [
            w for w in workflow_patterns
            if w.get("success_rate", 100) < 80
        ]

        if failing_workflows:
            correlations.append({
                "type": "workflow_failure_pattern",
                "description": "Recurring workflow failures detected",
                "severity": "high" if len(failing_workflows) > 5 else "warning",
                "workflows": [w.get("name") for w in failing_workflows],
            })

        return correlations

    def _generate_insights(
        git_patterns: List[Dict],
        workflow_patterns: List[Dict],
        correlations: List[Dict],
    ) -> List[str]:
        """Generate actionable insights from pattern analysis.

        Args:
            git_patterns: Git activity patterns
            workflow_patterns: Workflow execution patterns
            correlations: Correlation analysis results

        Returns:
            List of actionable insights
        """
        insights = []

        # Identify high-velocity projects
        high_velocity = [p for p in git_patterns if p.get("type") == "high_velocity"]
        if high_velocity:
            insights.append(
                f"🚀 {len(high_velocity)} projects showing high commit velocity - "
                f"consider code review practices to maintain quality"
            )

        # Identify quality concerns
        high_correlations = [c for c in correlations if c.get("severity") == "high"]
        if high_correlations:
            insights.append(
                f"⚠️  {len(high_correlations)} high-severity correlations detected - "
                f"investigate process and tooling issues"
            )

        # Identify workflow improvements
        failed_workflows = [w for w in workflow_patterns if w.get("success_rate", 100) < 80]
        if failed_workflows:
            insights.append(
                f"🔄 {len(failed_workflows)} workflows with low success rate - "
                f"consider workflow redesign or resource allocation"
            )

        if not insights:
            insights.append("✅ No significant issues detected - ecosystem is healthy")

        return insights

    print("✅ Registered 3 Git analytics tools with MCP server (with authorization)")
