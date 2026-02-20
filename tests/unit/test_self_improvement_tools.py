"""Tests for self-improvement MCP tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.mcp.tools.self_improvement_tools import (
    ReviewScope,
    SelfImprovementTools,
)


class TestReviewScope:
    """Test ReviewScope enum."""

    def test_scope_values(self) -> None:
        """Test scope enum values."""
        assert ReviewScope.CRITICAL.value == "critical"
        assert ReviewScope.SECURITY.value == "security"
        assert ReviewScope.PERFORMANCE.value == "performance"
        assert ReviewScope.QUALITY.value == "quality"
        assert ReviewScope.ALL.value == "all"

    def test_scope_string_representation(self) -> None:
        """Test scope enum string representation."""
        # When inheriting from str, the value is used for string conversion
        assert ReviewScope.CRITICAL.value == "critical"
        assert ReviewScope.SECURITY.value == "security"
        # Can also use in f-strings via .value
        assert f"{ReviewScope.CRITICAL.value}" == "critical"

    def test_scope_from_string(self) -> None:
        """Test creating scope from string."""
        assert ReviewScope("critical") == ReviewScope.CRITICAL
        assert ReviewScope("security") == ReviewScope.SECURITY
        assert ReviewScope("all") == ReviewScope.ALL


class TestSelfImprovementTools:
    """Test SelfImprovementTools class."""

    @pytest.fixture
    def mock_app(self) -> MagicMock:
        """Create mock MahavishnuApp."""
        app = MagicMock()
        app.pool_manager = MagicMock()
        app.coordination_manager = MagicMock()
        app.approval_manager = MagicMock()
        return app

    @pytest.fixture
    def tools(self, mock_app: MagicMock) -> SelfImprovementTools:
        """Create self-improvement tools instance."""
        return SelfImprovementTools(mock_app)

    @pytest.mark.asyncio
    async def test_review_and_fix_dry_run(
        self,
        tools: SelfImprovementTools,
    ) -> None:
        """Test review and fix in dry-run mode."""
        with patch.object(tools, "_run_review") as mock_review:
            mock_review.return_value = [
                {"id": "MHV-001", "title": "Test issue", "severity": "critical"},
            ]

            result = await tools.review_and_fix(
                scope=ReviewScope.CRITICAL,
                auto_fix=False,
                dry_run=True,
            )

        assert result["dry_run"] is True
        assert result["findings_count"] == 1
        assert result["issues_created"] == 0

    @pytest.mark.asyncio
    async def test_review_and_fix_creates_issues(
        self,
        tools: SelfImprovementTools,
        mock_app: MagicMock,
    ) -> None:
        """Test review and fix creates issues."""
        mock_app.coordination_manager.create_issue = AsyncMock(return_value=None)

        with patch.object(tools, "_run_review") as mock_review:
            mock_review.return_value = [
                {
                    "id": "MHV-001",
                    "title": "Test issue",
                    "severity": "critical",
                    "pool": "python",
                    "affected_files": ["app.py"],
                },
            ]

            result = await tools.review_and_fix(
                scope=ReviewScope.CRITICAL,
                auto_fix=False,
                dry_run=False,
            )

        assert result["findings_count"] == 1
        assert result["issues_created"] == 1
        mock_app.coordination_manager.create_issue.assert_called_once()

    @pytest.mark.asyncio
    async def test_review_and_fix_with_auto_fix(
        self,
        tools: SelfImprovementTools,
        mock_app: MagicMock,
    ) -> None:
        """Test review and fix with auto-fix enabled."""
        mock_app.coordination_manager.create_issue = AsyncMock(return_value=None)

        with patch.object(tools, "_run_review") as mock_review:
            mock_review.return_value = [
                {
                    "id": "MHV-001",
                    "title": "Test issue",
                    "severity": "critical",
                    "pool": "python",
                    "affected_files": ["app.py"],
                },
            ]

            with patch.object(tools, "_auto_fix") as mock_auto_fix:
                mock_auto_fix.return_value = [
                    {"issue_id": "MHV-001", "status": "fixed"},
                ]

                result = await tools.review_and_fix(
                    scope=ReviewScope.CRITICAL,
                    auto_fix=True,
                    dry_run=False,
                )

        assert result["findings_count"] == 1
        assert result["issues_created"] == 1
        assert result["auto_fixed"] == 1
        mock_auto_fix.assert_called_once()

    @pytest.mark.asyncio
    async def test_review_and_fix_no_findings(
        self,
        tools: SelfImprovementTools,
    ) -> None:
        """Test review and fix with no findings."""
        with patch.object(tools, "_run_review") as mock_review:
            mock_review.return_value = []

            result = await tools.review_and_fix(
                scope=ReviewScope.ALL,
                auto_fix=False,
                dry_run=False,
            )

        assert result["findings_count"] == 0
        assert result["issues_created"] == 0
        assert result["auto_fixed"] == 0

    @pytest.mark.asyncio
    async def test_request_approval(
        self,
        tools: SelfImprovementTools,
        mock_app: MagicMock,
    ) -> None:
        """Test requesting manual approval."""
        mock_request = MagicMock()
        mock_request.id = "approval-001"
        mock_request.approval_type = "version_bump"
        mock_request.to_dict.return_value = {
            "id": "approval-001",
            "approval_type": "version_bump",
            "status": "pending",
        }
        mock_app.approval_manager.create_request = MagicMock(return_value=mock_request)

        result = await tools.request_approval(
            approval_type="version_bump",
            context={"version": "0.24.3"},
        )

        assert result["approval_id"] == "approval-001"
        assert result["status"] == "pending"
        mock_app.approval_manager.create_request.assert_called_once_with(
            approval_type="version_bump",
            context={"version": "0.24.3"},
        )

    @pytest.mark.asyncio
    async def test_request_approval_publish(
        self,
        tools: SelfImprovementTools,
        mock_app: MagicMock,
    ) -> None:
        """Test requesting approval for publish."""
        mock_request = MagicMock()
        mock_request.id = "approval-002"
        mock_request.approval_type = "publish"
        mock_request.to_dict.return_value = {
            "id": "approval-002",
            "approval_type": "publish",
            "status": "pending",
        }
        mock_app.approval_manager.create_request = MagicMock(return_value=mock_request)

        result = await tools.request_approval(
            approval_type="publish",
            context={"target": "pypi"},
        )

        assert result["approval_id"] == "approval-002"
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_respond_to_approval_approve(
        self,
        tools: SelfImprovementTools,
        mock_app: MagicMock,
    ) -> None:
        """Test responding to an approval request with approval."""
        mock_response = MagicMock()
        mock_response.approved = True
        mock_response.selected_option = 0
        mock_app.approval_manager.respond = MagicMock(return_value=mock_response)

        result = await tools.respond_to_approval(
            approval_id="approval-001",
            approved=True,
            selected_option=0,
        )

        assert result["approved"] is True
        assert result["selected_option"] == 0
        mock_app.approval_manager.respond.assert_called_once_with(
            request_id="approval-001",
            approved=True,
            selected_option=0,
            rejection_reason=None,
        )

    @pytest.mark.asyncio
    async def test_respond_to_approval_reject(
        self,
        tools: SelfImprovementTools,
        mock_app: MagicMock,
    ) -> None:
        """Test responding to an approval request with rejection."""
        mock_response = MagicMock()
        mock_response.approved = False
        mock_response.selected_option = None
        mock_app.approval_manager.respond = MagicMock(return_value=mock_response)

        result = await tools.respond_to_approval(
            approval_id="approval-001",
            approved=False,
            rejection_reason="Need more testing",
        )

        assert result["approved"] is False
        assert result["rejection_reason"] == "Need more testing"

    @pytest.mark.asyncio
    async def test_respond_to_approval_not_found(
        self,
        tools: SelfImprovementTools,
        mock_app: MagicMock,
    ) -> None:
        """Test responding to non-existent approval request."""
        mock_app.approval_manager.respond = MagicMock(return_value=None)

        result = await tools.respond_to_approval(
            approval_id="nonexistent",
            approved=True,
        )

        assert result["error"] is not None
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_get_pending_approvals(
        self,
        tools: SelfImprovementTools,
        mock_app: MagicMock,
    ) -> None:
        """Test getting pending approvals."""
        mock_request1 = MagicMock()
        mock_request1.id = "approval-001"
        mock_request1.approval_type = "version_bump"
        mock_request1.to_dict.return_value = {
            "id": "approval-001",
            "approval_type": "version_bump",
        }

        mock_request2 = MagicMock()
        mock_request2.id = "approval-002"
        mock_request2.approval_type = "publish"
        mock_request2.to_dict.return_value = {
            "id": "approval-002",
            "approval_type": "publish",
        }

        mock_app.approval_manager.pending_requests = [mock_request1, mock_request2]

        result = await tools.get_pending_approvals()

        assert result["count"] == 2
        assert len(result["approvals"]) == 2

    @pytest.mark.asyncio
    async def test_get_pending_approvals_empty(
        self,
        tools: SelfImprovementTools,
        mock_app: MagicMock,
    ) -> None:
        """Test getting pending approvals when none exist."""
        mock_app.approval_manager.pending_requests = []

        result = await tools.get_pending_approvals()

        assert result["count"] == 0
        assert result["approvals"] == []

    @pytest.mark.asyncio
    async def test_run_review_critical(
        self,
        tools: SelfImprovementTools,
    ) -> None:
        """Test _run_review with critical scope."""
        findings = await tools._run_review(ReviewScope.CRITICAL)

        assert isinstance(findings, list)

    @pytest.mark.asyncio
    async def test_run_review_security(
        self,
        tools: SelfImprovementTools,
    ) -> None:
        """Test _run_review with security scope."""
        findings = await tools._run_review(ReviewScope.SECURITY)

        assert isinstance(findings, list)

    @pytest.mark.asyncio
    async def test_run_review_all(
        self,
        tools: SelfImprovementTools,
    ) -> None:
        """Test _run_review with all scope."""
        findings = await tools._run_review(ReviewScope.ALL)

        assert isinstance(findings, list)

    @pytest.mark.asyncio
    async def test_auto_fix_empty(
        self,
        tools: SelfImprovementTools,
    ) -> None:
        """Test _auto_fix with empty findings."""
        result = await tools._auto_fix([])

        assert result == []

    @pytest.mark.asyncio
    async def test_auto_fix_with_findings(
        self,
        tools: SelfImprovementTools,
    ) -> None:
        """Test _auto_fix with findings (placeholder implementation)."""
        findings = [
            {"id": "MHV-001", "severity": "critical"},
        ]

        result = await tools._auto_fix(findings)

        # Placeholder implementation returns empty list
        assert isinstance(result, list)


class TestSelfImprovementToolsIntegration:
    """Integration tests for SelfImprovementTools."""

    @pytest.fixture
    def mock_app_full(self) -> MagicMock:
        """Create fully mocked MahavishnuApp."""
        app = MagicMock()
        app.pool_manager = MagicMock()
        app.coordination_manager = MagicMock()
        app.coordination_manager.create_issue = AsyncMock(return_value=None)
        app.approval_manager = MagicMock()
        return app

    @pytest.mark.asyncio
    async def test_full_workflow_review_to_approval(
        self,
        mock_app_full: MagicMock,
    ) -> None:
        """Test full workflow from review to approval."""
        tools = SelfImprovementTools(mock_app_full)

        # Mock the review to return findings
        with patch.object(tools, "_run_review") as mock_review:
            mock_review.return_value = [
                {
                    "id": "MHV-001",
                    "title": "Critical security issue",
                    "severity": "critical",
                    "pool": "python",
                    "affected_files": ["auth.py"],
                },
            ]

            # Run review and fix
            review_result = await tools.review_and_fix(
                scope=ReviewScope.SECURITY,
                auto_fix=False,
                dry_run=False,
            )

            assert review_result["issues_created"] == 1

        # Request approval for version bump
        mock_request = MagicMock()
        mock_request.id = "approval-001"
        mock_request.to_dict.return_value = {"id": "approval-001"}
        mock_app_full.approval_manager.create_request = MagicMock(return_value=mock_request)

        approval_result = await tools.request_approval(
            approval_type="version_bump",
            context={"version": "0.24.4", "reason": "Security fix"},
        )

        assert approval_result["approval_id"] == "approval-001"

        # Respond to approval
        mock_response = MagicMock()
        mock_response.approved = True
        mock_response.selected_option = 0
        mock_app_full.approval_manager.respond = MagicMock(return_value=mock_response)

        response_result = await tools.respond_to_approval(
            approval_id="approval-001",
            approved=True,
            selected_option=0,
        )

        assert response_result["approved"] is True
