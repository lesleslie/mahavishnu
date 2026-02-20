"""MCP tools for self-improvement workflow."""

from __future__ import annotations

from enum import StrEnum
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mahavishnu.core.app import MahavishnuApp

logger = logging.getLogger(__name__)


class ReviewScope(StrEnum):
    """Scope for review operations."""

    CRITICAL = "critical"
    SECURITY = "security"
    PERFORMANCE = "performance"
    QUALITY = "quality"
    ALL = "all"


class SelfImprovementTools:
    """MCP tools for self-improvement workflow.

    Provides tools for running review agents, managing approvals,
    and coordinating self-improvement workflows across the ecosystem.
    """

    def __init__(self, app: MahavishnuApp) -> None:
        """Initialize self-improvement tools.

        Args:
            app: MahavishnuApp instance with coordination and approval managers.
        """
        self.app = app

    async def review_and_fix(
        self,
        scope: ReviewScope = ReviewScope.CRITICAL,
        auto_fix: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Run comprehensive review and optionally fix issues.

        Runs review agents based on scope, creates issues for findings,
        and optionally auto-fixes critical issues.

        Args:
            scope: Scope of review (critical, security, performance, quality, all).
            auto_fix: Whether to auto-fix critical findings.
            dry_run: If True, don't create issues or apply fixes.

        Returns:
            Dictionary with review results including:
            - dry_run: Whether this was a dry run
            - findings_count: Total number of findings
            - issues_created: Number of issues created
            - auto_fixed: Number of auto-fixes applied
            - findings: List of all findings

        Example:
            ```python
            result = await tools.review_and_fix(
                scope=ReviewScope.SECURITY,
                auto_fix=True,
                dry_run=False,
            )
            print(f"Found {result['findings_count']} issues")
            print(f"Created {result['issues_created']} issues")
            print(f"Auto-fixed {result['auto_fixed']} issues")
            ```
        """
        logger.info(f"Running review with scope={scope}, auto_fix={auto_fix}, dry_run={dry_run}")

        # Run review agents based on scope
        findings = await self._run_review(scope)

        result: dict[str, Any] = {
            "dry_run": dry_run,
            "scope": scope.value,
            "findings_count": len(findings),
            "issues_created": 0,
            "auto_fixed": 0,
            "findings": findings,
        }

        if dry_run:
            logger.info(f"Dry run complete: found {len(findings)} issues")
            return result

        # Create issues for findings
        issues_created = 0
        for finding in findings:
            try:
                if self.app.coordination_manager is not None:
                    await self.app.coordination_manager.create_issue(
                        title=finding.get("title", "Review finding"),
                        description=finding.get("description", str(finding)),
                        pool=finding.get("pool", "python"),
                        affected_files=finding.get("affected_files", []),
                        metadata={
                            "finding_id": finding.get("id"),
                            "severity": finding.get("severity"),
                            "scope": scope.value,
                        },
                    )
                    issues_created += 1
            except Exception as e:
                logger.warning(f"Failed to create issue for finding {finding.get('id')}: {e}")

        result["issues_created"] = issues_created

        # Auto-fix if requested
        if auto_fix and findings:
            auto_fix_results = await self._auto_fix(findings)
            result["auto_fixed"] = len(auto_fix_results)
            result["auto_fix_results"] = auto_fix_results

        logger.info(
            f"Review complete: {issues_created} issues created, {result['auto_fixed']} auto-fixed"
        )
        return result

    async def request_approval(
        self,
        approval_type: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Request manual approval for version bump or publish.

        Creates an approval request that requires human response before
        proceeding with sensitive operations.

        Args:
            approval_type: Type of approval ("version_bump" or "publish").
            context: Context data for the approval decision.

        Returns:
            Dictionary with approval request details:
            - approval_id: Unique ID for this request
            - status: Current status (always "pending")
            - approval_type: Type of approval requested
            - expires_at: When this request expires

        Example:
            ```python
            result = await tools.request_approval(
                approval_type="version_bump",
                context={
                    "current_version": "0.24.2",
                    "suggested_version": "0.24.3",
                    "reason": "Bug fix release",
                },
            )
            print(f"Approval ID: {result['approval_id']}")
            ```
        """
        logger.info(f"Requesting approval for {approval_type}")

        if self.app.approval_manager is None:
            return {
                "error": "Approval manager not available",
                "approval_type": approval_type,
                "status": "failed",
            }

        try:
            request = self.app.approval_manager.create_request(
                approval_type=approval_type,  # type: ignore[arg-type]
                context=context,
            )

            request_dict = request.to_dict()
            logger.info(f"Created approval request: {request.id}")

            return {
                "approval_id": request.id,
                "status": "pending",
                "approval_type": request.approval_type,
                "expires_at": request_dict.get("expires_at"),
                "options": request_dict.get("options", []),
            }
        except Exception as e:
            logger.error(f"Failed to create approval request: {e}")
            return {
                "error": str(e),
                "approval_type": approval_type,
                "status": "failed",
            }

    async def respond_to_approval(
        self,
        approval_id: str,
        approved: bool,
        selected_option: int | None = None,
        rejection_reason: str | None = None,
    ) -> dict[str, Any]:
        """Respond to a pending approval request.

        Provides a response to an approval request, either approving or
        rejecting it with optional details.

        Args:
            approval_id: ID of the approval request to respond to.
            approved: Whether to approve the request.
            selected_option: Index of selected option if approved.
            rejection_reason: Reason for rejection if not approved.

        Returns:
            Dictionary with response result:
            - approved: Whether the request was approved
            - selected_option: The selected option index (if approved)
            - rejection_reason: The rejection reason (if rejected)
            - error: Error message if request not found

        Example:
            ```python
            # Approve with first option
            result = await tools.respond_to_approval(
                approval_id="approval-abc123",
                approved=True,
                selected_option=0,
            )

            # Reject with reason
            result = await tools.respond_to_approval(
                approval_id="approval-abc123",
                approved=False,
                rejection_reason="Need more testing",
            )
            ```
        """
        logger.info(f"Responding to approval {approval_id}: approved={approved}")

        if self.app.approval_manager is None:
            return {
                "error": "Approval manager not available",
                "approved": False,
            }

        try:
            result = self.app.approval_manager.respond(
                request_id=approval_id,
                approved=approved,
                selected_option=selected_option,
                rejection_reason=rejection_reason,
            )

            response: dict[str, Any] = {
                "approved": result.approved,
                "selected_option": result.selected_option,
            }

            if not approved and rejection_reason:
                response["rejection_reason"] = rejection_reason

            logger.info(f"Approval {approval_id} response: approved={result.approved}")
            return response

        except ValueError as e:
            error_msg = str(e)
            logger.warning(f"Approval response failed: {error_msg}")
            return {
                "error": error_msg,
                "approved": False,
            }
        except Exception as e:
            logger.error(f"Unexpected error responding to approval: {e}")
            return {
                "error": f"Request {approval_id} not found or expired",
                "approved": False,
            }

    async def get_pending_approvals(self) -> dict[str, Any]:
        """Get all pending approval requests.

        Returns a list of all approval requests awaiting response.

        Returns:
            Dictionary with pending approvals:
            - count: Number of pending approvals
            - approvals: List of approval request dictionaries

        Example:
            ```python
            result = await tools.get_pending_approvals()
            for approval in result["approvals"]:
                print(f"{approval['id']}: {approval['approval_type']}")
            ```
        """
        logger.debug("Getting pending approvals")

        if self.app.approval_manager is None:
            return {
                "count": 0,
                "approvals": [],
                "error": "Approval manager not available",
            }

        pending = self.app.approval_manager.pending_requests

        approvals = [req.to_dict() for req in pending]

        logger.debug(f"Found {len(approvals)} pending approvals")
        return {
            "count": len(approvals),
            "approvals": approvals,
        }

    async def _run_review(self, scope: ReviewScope) -> list[dict[str, Any]]:
        """Run review agents based on scope.

        Internal method that spawns appropriate review agents based on
        the requested scope and collects findings.

        Args:
            scope: Scope of review to run.

        Returns:
            List of finding dictionaries with:
            - id: Unique finding identifier
            - title: Finding title
            - severity: Severity level (critical, high, medium, low)
            - pool: Target pool for the finding
            - affected_files: List of affected files
            - description: Detailed description

        Note:
            This is a placeholder implementation. In production, this would
            spawn actual review agents via the pool manager and collect
            their findings.
        """
        logger.debug(f"Running review with scope: {scope.value}")

        # Placeholder implementation
        # In production, this would:
        # 1. Determine which review agents to run based on scope
        # 2. Spawn agents via pool_manager
        # 3. Collect and aggregate findings
        # 4. Return structured results

        # Map scope to review types
        scope_to_review_types: dict[ReviewScope, list[str]] = {
            ReviewScope.CRITICAL: ["security-critical", "error-handling"],
            ReviewScope.SECURITY: ["security-audit", "dependency-scan", "secrets-check"],
            ReviewScope.PERFORMANCE: ["performance-profile", "memory-analysis"],
            ReviewScope.QUALITY: ["code-quality", "test-coverage", "documentation"],
            ReviewScope.ALL: [
                "security-audit",
                "dependency-scan",
                "performance-profile",
                "code-quality",
                "test-coverage",
            ],
        }

        review_types = scope_to_review_types.get(scope, [])
        logger.debug(f"Would run review types: {review_types}")

        # Return empty list for now - actual implementation would
        # spawn agents and collect real findings
        return []

    async def _auto_fix(self, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Auto-fix critical findings.

        Internal method that attempts to automatically fix critical
        findings without human intervention.

        Args:
            findings: List of findings to potentially fix.

        Returns:
            List of fix results with:
            - issue_id: ID of the finding that was fixed
            - status: Fix status (fixed, failed, skipped)
            - details: Additional details about the fix

        Note:
            This is a placeholder implementation. In production, this would
            integrate with the FixOrchestrator to apply actual fixes.
        """
        logger.debug(f"Auto-fix requested for {len(findings)} findings")

        # Placeholder implementation
        # In production, this would:
        # 1. Filter findings to those that are auto-fixable
        # 2. Use FixOrchestrator to apply fixes
        # 3. Return results of fix attempts

        # Return empty list for now - actual implementation would
        # use fix_orchestrator to apply real fixes
        return []


def register_self_improvement_tools(
    mcp: Any,
    app: MahavishnuApp,
) -> None:
    """Register self-improvement MCP tools.

    Args:
        mcp: FastMCP instance to register tools with.
        app: MahavishnuApp instance.

    This registers the following tools:
    - review_and_fix: Run review agents and optionally fix issues
    - request_approval: Request manual approval
    - respond_to_approval: Respond to pending approval
    - get_pending_approvals: List all pending approvals
    """
    tools = SelfImprovementTools(app)

    @mcp.tool()
    async def review_and_fix(
        scope: str = "critical",
        auto_fix: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Run comprehensive review and optionally fix issues.

        Args:
            scope: Scope of review (critical, security, performance, quality, all).
            auto_fix: Whether to auto-fix critical findings.
            dry_run: If True, don't create issues or apply fixes.

        Returns:
            Dictionary with review results.
        """
        review_scope = ReviewScope(scope)
        return await tools.review_and_fix(
            scope=review_scope,
            auto_fix=auto_fix,
            dry_run=dry_run,
        )

    @mcp.tool()
    async def request_approval(
        approval_type: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Request manual approval for version bump or publish.

        Args:
            approval_type: Type of approval ("version_bump" or "publish").
            context: Context data for the approval decision.

        Returns:
            Dictionary with approval request details.
        """
        return await tools.request_approval(
            approval_type=approval_type,
            context=context,
        )

    @mcp.tool()
    async def respond_to_approval(
        approval_id: str,
        approved: bool,
        selected_option: int | None = None,
        rejection_reason: str | None = None,
    ) -> dict[str, Any]:
        """Respond to a pending approval request.

        Args:
            approval_id: ID of the approval request.
            approved: Whether to approve the request.
            selected_option: Index of selected option if approved.
            rejection_reason: Reason for rejection if not approved.

        Returns:
            Dictionary with response result.
        """
        return await tools.respond_to_approval(
            approval_id=approval_id,
            approved=approved,
            selected_option=selected_option,
            rejection_reason=rejection_reason,
        )

    @mcp.tool()
    async def get_pending_approvals() -> dict[str, Any]:
        """Get all pending approval requests.

        Returns:
            Dictionary with count and list of pending approvals.
        """
        return await tools.get_pending_approvals()

    logger.info("Registered 4 self-improvement MCP tools")
