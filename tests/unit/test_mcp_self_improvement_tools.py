"""Unit tests for mahavishnu.mcp.tools.self_improvement_tools."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.approval_manager import (
    ApprovalManager,
    ApprovalOption,
    ApprovalRequest,
    ApprovalResult,
)
from mahavishnu.mcp.tools.self_improvement_tools import (
    ReviewScope,
    SelfImprovementTools,
    register_self_improvement_tools,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


def _make_approval_request(
    req_id: str = "apr-1",
    approval_type: str = "version_bump",
) -> ApprovalRequest:
    """Create an ApprovalRequest with default fields."""
    now = datetime.now(UTC)
    return ApprovalRequest(
        id=req_id,
        approval_type=approval_type,
        context={"current_version": "0.1.0", "suggested_version": "0.1.1"},
        created_at=now,
        expires_at=now,
        options=[ApprovalOption(label="approve", description="approve")],
    )


@pytest.fixture
def mock_coordination_manager():
    """Build a mock coordination manager."""
    mgr = MagicMock()
    mgr.create_issue = AsyncMock(return_value={"issue_id": "iss-1"})
    return mgr


@pytest.fixture
def mock_approval_manager():
    """Build a mock approval manager."""
    mgr = MagicMock(spec=ApprovalManager)
    mgr.create_request = MagicMock(return_value=_make_approval_request())
    mgr.respond = MagicMock(return_value=ApprovalResult(approved=True, selected_option=0))
    mgr.pending_requests = [_make_approval_request("apr-2")]
    return mgr


@pytest.fixture
def mock_app(mock_coordination_manager, mock_approval_manager):
    """Build a mock MahavishnuApp."""
    app = MagicMock()
    app.coordination_manager = mock_coordination_manager
    app.approval_manager = mock_approval_manager
    return app


@pytest.fixture
def tools(mock_app):
    """Build SelfImprovementTools with the mock app."""
    return SelfImprovementTools(mock_app)


@pytest.fixture
def mock_mcp():
    """Build a mock FastMCP that captures tool functions."""
    mcp = MagicMock()
    mcp._tools = {}

    def tool_decorator():
        def wrapper(fn):
            mcp._tools[fn.__name__] = fn
            return fn

        return wrapper

    mcp.tool = MagicMock(side_effect=lambda: tool_decorator())
    return mcp


@pytest.fixture
def registered_mcp(mock_mcp, mock_app):
    """Register self-improvement tools on the mock MCP."""
    register_self_improvement_tools(mock_mcp, mock_app)
    return mock_mcp


# =============================================================================
# ReviewScope enum
# =============================================================================


class TestReviewScope:
    """Tests for the ReviewScope enum."""

    def test_values(self):
        """All scope values should be present."""
        assert ReviewScope.CRITICAL.value == "critical"
        assert ReviewScope.SECURITY.value == "security"
        assert ReviewScope.PERFORMANCE.value == "performance"
        assert ReviewScope.QUALITY.value == "quality"
        assert ReviewScope.ALL.value == "all"

    def test_str_enum_construction(self):
        """ReviewScope should be constructible from string values."""
        assert ReviewScope("critical") == ReviewScope.CRITICAL
        assert ReviewScope("security") == ReviewScope.SECURITY
        assert ReviewScope("all") == ReviewScope.ALL


# =============================================================================
# _collect_ruff_targets
# =============================================================================


class TestCollectRuffTargets:
    """Tests for the _collect_ruff_targets helper."""

    def test_collects_python_files(self, tools):
        """Should collect .py and .pyi files from findings."""
        findings = [
            {"affected_files": ["src/foo.py", "src/bar.pyi", "README.md"]},
            {"affected_files": ["other.py"]},
        ]
        targets = tools._collect_ruff_targets(findings)
        assert "src/foo.py" in targets
        assert "src/bar.pyi" in targets
        assert "README.md" not in targets
        assert "other.py" in targets

    def test_deduplicates(self, tools):
        """Should not return the same file twice."""
        findings = [
            {"affected_files": ["a.py"]},
            {"affected_files": ["a.py"]},
        ]
        targets = tools._collect_ruff_targets(findings)
        assert targets.count("a.py") == 1

    def test_skips_non_python(self, tools):
        """Should skip files without .py or .pyi extension."""
        findings = [{"affected_files": ["foo.txt", "bar.js", "qux.py"]}]
        targets = tools._collect_ruff_targets(findings)
        assert targets == ["qux.py"]

    def test_empty_findings(self, tools):
        """Empty findings returns empty list."""
        assert tools._collect_ruff_targets([]) == []

    def test_missing_affected_files(self, tools):
        """Finding without 'affected_files' key should be skipped."""
        findings = [{"title": "no files"}]
        assert tools._collect_ruff_targets(findings) == []

    def test_none_affected_files(self, tools):
        """Finding with affected_files=None should be skipped."""
        findings = [{"affected_files": None}]
        assert tools._collect_ruff_targets(findings) == []


# =============================================================================
# _run_ruff_command
# =============================================================================


class TestRunRuffCommand:
    """Tests for the _run_ruff_command helper."""

    def test_run_ruff_command_captures_output(self, tools):
        """Should return a dict with command, returncode, stdout, stderr."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "out"
        mock_result.stderr = "err"
        with patch(
            "mahavishnu.mcp.tools.self_improvement_tools.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            result = tools._run_ruff_command(["check", "foo.py"])
        assert result["command"] == ["ruff", "check", "foo.py"]
        assert result["returncode"] == 0
        assert result["stdout"] == "out"
        assert result["stderr"] == "err"
        # Verify subprocess.run was called with timeout=120
        assert mock_run.call_args.kwargs["timeout"] == 120

    def test_run_ruff_command_with_cwd(self, tools, tmp_path):
        """cwd should be passed through to subprocess."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        with patch(
            "mahavishnu.mcp.tools.self_improvement_tools.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            tools._run_ruff_command(["check"], cwd=tmp_path)
        assert mock_run.call_args.kwargs["cwd"] == str(tmp_path)


# =============================================================================
# review_and_fix
# =============================================================================


class TestReviewAndFix:
    """Tests for the review_and_fix method."""

    async def test_dry_run_no_issues(self, tools):
        """Dry run should not create issues or auto-fix."""
        result = await tools.review_and_fix(scope=ReviewScope.CRITICAL, auto_fix=True, dry_run=True)
        assert result["dry_run"] is True
        assert result["scope"] == "critical"
        assert result["findings_count"] == 0
        assert result["issues_created"] == 0
        assert result["auto_fixed"] == 0

    async def test_review_creates_issues(self, tools, mock_coordination_manager):
        """Findings should become issues when not dry-run."""
        with patch.object(tools, "_run_review") as mock_run:
            mock_run.return_value = [
                {
                    "id": "f-1",
                    "title": "Test finding",
                    "description": "Test desc",
                    "pool": "python",
                    "affected_files": ["foo.py"],
                    "severity": "high",
                }
            ]
            result = await tools.review_and_fix(
                scope=ReviewScope.SECURITY, auto_fix=False, dry_run=False
            )
        assert result["issues_created"] == 1
        mock_coordination_manager.create_issue.assert_awaited_once()
        call_kwargs = mock_coordination_manager.create_issue.await_args.kwargs
        assert call_kwargs["title"] == "Test finding"
        assert call_kwargs["metadata"]["finding_id"] == "f-1"

    async def test_issue_creation_exception_continues(self, tools, mock_coordination_manager):
        """If create_issue raises, the loop should continue."""
        mock_coordination_manager.create_issue.side_effect = RuntimeError("boom")
        with patch.object(tools, "_run_review") as mock_run:
            mock_run.return_value = [
                {"id": "f-1", "title": "a", "description": "a", "affected_files": []},
                {"id": "f-2", "title": "b", "description": "b", "affected_files": []},
            ]
            result = await tools.review_and_fix(
                scope=ReviewScope.ALL, auto_fix=False, dry_run=False
            )
        assert result["issues_created"] == 0

    async def test_auto_fix_called_when_requested(self, tools):
        """With auto_fix=True and findings, _auto_fix should be called."""
        with (
            patch.object(tools, "_run_review") as mock_run,
            patch.object(tools, "_auto_fix") as mock_fix,
        ):
            mock_run.return_value = [{"id": "f-1", "affected_files": ["foo.py"]}]
            mock_fix.return_value = [{"status": "fixed"}, {"status": "skipped"}]
            result = await tools.review_and_fix(
                scope=ReviewScope.QUALITY, auto_fix=True, dry_run=False
            )
        assert result["auto_fixed"] == 1
        assert result["auto_fix_results"] == [{"status": "fixed"}, {"status": "skipped"}]

    async def test_no_coordination_manager(self):
        """When coordination_manager is None, issue creation is skipped silently."""
        app = MagicMock()
        app.coordination_manager = None
        app.approval_manager = MagicMock()
        tools = SelfImprovementTools(app)
        with patch.object(tools, "_run_review") as mock_run:
            mock_run.return_value = [{"id": "f-1", "affected_files": []}]
            result = await tools.review_and_fix(
                scope=ReviewScope.CRITICAL, auto_fix=False, dry_run=False
            )
        assert result["issues_created"] == 0


# =============================================================================
# request_approval
# =============================================================================


class TestRequestApproval:
    """Tests for the request_approval method."""

    async def test_request_approval_success(self, tools, mock_approval_manager):
        """Should return a dict with approval details."""
        result = await tools.request_approval(approval_type="version_bump", context={"v": "1.0"})
        assert result["approval_id"] == "apr-1"
        assert result["status"] == "pending"
        assert result["approval_type"] == "version_bump"
        assert "options" in result
        mock_approval_manager.create_request.assert_called_once()

    async def test_request_approval_no_manager(self):
        """If approval_manager is None, return error payload."""
        app = MagicMock()
        app.approval_manager = None
        tools = SelfImprovementTools(app)
        result = await tools.request_approval(approval_type="version_bump", context={})
        assert result["status"] == "failed"
        assert "Approval manager not available" in result["error"]

    async def test_request_approval_exception(self, tools, mock_approval_manager):
        """If create_request raises, return error payload."""
        mock_approval_manager.create_request.side_effect = RuntimeError("kaboom")
        result = await tools.request_approval(approval_type="publish", context={})
        assert result["status"] == "failed"
        assert "kaboom" in result["error"]


# =============================================================================
# respond_to_approval
# =============================================================================


class TestRespondToApproval:
    """Tests for the respond_to_approval method."""

    async def test_respond_approve(self, tools, mock_approval_manager):
        """Approve with a selected option."""
        result = await tools.respond_to_approval(
            approval_id="apr-1", approved=True, selected_option=0
        )
        assert result["approved"] is True
        assert result["selected_option"] == 0

    async def test_respond_reject(self, tools, mock_approval_manager):
        """Reject with a reason."""
        mock_approval_manager.respond = MagicMock(
            return_value=ApprovalResult(approved=False, rejection_reason="not ready")
        )
        result = await tools.respond_to_approval(
            approval_id="apr-1",
            approved=False,
            rejection_reason="not ready",
        )
        assert result["approved"] is False
        assert result["rejection_reason"] == "not ready"

    async def test_respond_no_manager(self):
        """If approval_manager is None, return error."""
        app = MagicMock()
        app.approval_manager = None
        tools = SelfImprovementTools(app)
        result = await tools.respond_to_approval(approval_id="apr-1", approved=True)
        assert result["approved"] is False
        assert "Approval manager not available" in result["error"]

    async def test_respond_value_error(self, tools, mock_approval_manager):
        """If respond raises ValueError, return error dict."""
        mock_approval_manager.respond.side_effect = ValueError("not found")
        result = await tools.respond_to_approval(approval_id="apr-bad", approved=True)
        assert result["approved"] is False
        assert "not found" in result["error"]

    async def test_respond_generic_exception(self, tools, mock_approval_manager):
        """Other exceptions return a generic error."""
        mock_approval_manager.respond.side_effect = RuntimeError("anything")
        result = await tools.respond_to_approval(approval_id="apr-1", approved=True)
        assert result["approved"] is False
        assert "not found or expired" in result["error"]


# =============================================================================
# get_pending_approvals
# =============================================================================


class TestGetPendingApprovals:
    """Tests for the get_pending_approvals method."""

    async def test_returns_pending_list(self, tools):
        """Should return count and the list of approvals."""
        result = await tools.get_pending_approvals()
        assert result["count"] == 1
        assert len(result["approvals"]) == 1
        assert result["approvals"][0]["id"] == "apr-2"

    async def test_no_manager(self):
        """If approval_manager is None, return empty list with error."""
        app = MagicMock()
        app.approval_manager = None
        tools = SelfImprovementTools(app)
        result = await tools.get_pending_approvals()
        assert result["count"] == 0
        assert result["approvals"] == []
        assert "not available" in result["error"]


# =============================================================================
# _run_review
# =============================================================================


class TestRunReview:
    """Tests for the internal _run_review helper."""

    async def test_run_review_returns_empty_list(self, tools):
        """The placeholder implementation returns an empty list."""
        for scope in ReviewScope:
            result = await tools._run_review(scope)
            assert result == []


# =============================================================================
# _auto_fix
# =============================================================================


class TestAutoFix:
    """Tests for the _auto_fix method."""

    async def test_no_python_targets(self, tools):
        """No Python files in findings should return a single skipped result."""
        result = await tools._auto_fix([{"affected_files": ["README.md", "foo.txt"]}])
        assert len(result) == 1
        assert result[0]["status"] == "skipped"
        assert "no_python_files" in result[0]["reason"]

    async def test_runs_ruff_check_fix_format_validate(self, tools, tmp_path):
        """Should run ruff check --fix, format, then validate."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        with (
            patch.object(
                tools,
                "_run_ruff_command",
                return_value={
                    "command": ["ruff"],
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                },
            ) as mock_ruff,
            patch(
                "mahavishnu.mcp.tools.self_improvement_tools.Path.cwd",
                return_value=tmp_path,
            ),
        ):
            result = await tools._auto_fix([{"affected_files": [str(tmp_path / "foo.py")]}])
        # Should call _run_ruff_command 3 times
        assert mock_ruff.call_count == 3
        # Result should be a single dict
        assert len(result) == 1
        assert result[0]["status"] == "fixed"

    async def test_validate_failure_status_partial(self, tools, tmp_path):
        """If validate still finds issues, status should be 'partial'."""
        call_count = {"n": 0}

        def fake_ruff(args, cwd):
            call_count["n"] += 1
            returncode = (
                1 if "check" in args and "--fix" not in args and "format" not in args else 0
            )
            # For the third call (validate), return non-zero
            if call_count["n"] == 3:
                returncode = 1
            return {
                "command": ["ruff"] + args,
                "returncode": returncode,
                "stdout": "",
                "stderr": "",
            }

        with (
            patch.object(tools, "_run_ruff_command", side_effect=fake_ruff),
            patch(
                "mahavishnu.mcp.tools.self_improvement_tools.Path.cwd",
                return_value=tmp_path,
            ),
        ):
            result = await tools._auto_fix([{"affected_files": [str(tmp_path / "foo.py")]}])
        assert result[0]["status"] == "partial"
        assert "remaining issues" in result[0]["message"]


# =============================================================================
# register_self_improvement_tools
# =============================================================================


class TestRegisterSelfImprovementTools:
    """Tests for the register_self_improvement_tools function."""

    def test_all_tools_registered(self, registered_mcp):
        """All 4 self-improvement tools should be registered."""
        expected = {
            "review_and_fix",
            "request_approval",
            "respond_to_approval",
            "get_pending_approvals",
        }
        assert expected.issubset(set(registered_mcp._tools.keys()))

    async def test_review_and_fix_dispatches(self, registered_mcp, mock_app):
        """The MCP-decorated review_and_fix dispatches to the class method."""
        with patch.object(
            SelfImprovementTools, "review_and_fix", new_callable=AsyncMock
        ) as mock_method:
            mock_method.return_value = {"success": True, "findings_count": 0}
            await registered_mcp._tools["review_and_fix"](
                scope="critical", auto_fix=False, dry_run=True
            )
        mock_method.assert_awaited_once()

    async def test_request_approval_dispatches(self, registered_mcp):
        """The MCP-decorated request_approval dispatches to the class method."""
        with patch.object(
            SelfImprovementTools, "request_approval", new_callable=AsyncMock
        ) as mock_method:
            mock_method.return_value = {"approval_id": "x", "status": "pending"}
            await registered_mcp._tools["request_approval"](
                approval_type="version_bump", context={}
            )
        mock_method.assert_awaited_once()

    async def test_respond_to_approval_dispatches(self, registered_mcp):
        """The MCP-decorated respond_to_approval dispatches."""
        with patch.object(
            SelfImprovementTools, "respond_to_approval", new_callable=AsyncMock
        ) as mock_method:
            mock_method.return_value = {"approved": True}
            await registered_mcp._tools["respond_to_approval"](approval_id="apr-1", approved=True)
        mock_method.assert_awaited_once()

    async def test_get_pending_approvals_dispatches(self, registered_mcp):
        """The MCP-decorated get_pending_approvals dispatches."""
        with patch.object(
            SelfImprovementTools, "get_pending_approvals", new_callable=AsyncMock
        ) as mock_method:
            mock_method.return_value = {"count": 0, "approvals": []}
            await registered_mcp._tools["get_pending_approvals"]()
        mock_method.assert_awaited_once()
