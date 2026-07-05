"""Unit tests for mahavishnu.mcp.tools.clone_tools — Task 13 Phase B."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_app():
    app = MagicMock()
    app.settings = MagicMock()
    app.settings.crackerjack_url = "http://localhost:8676"
    app.settings.dhara_url = "http://localhost:8683"
    return app


@pytest.fixture
def mock_mcp():
    mcp = MagicMock()
    mcp.tool = MagicMock(return_value=lambda fn: fn)
    return mcp


# ---------------------------------------------------------------------------
# CloneTools class tests
# ---------------------------------------------------------------------------


class TestCloneToolsInit:
    def test_clone_tools_accepts_app(self, mock_app):
        from mahavishnu.mcp.tools.clone_tools import CloneTools

        tools = CloneTools(mock_app)
        assert tools.app is mock_app


class TestCloneDetectEcosystem:
    async def test_returns_job_id_immediately(self, mock_app):
        """clone_detect_ecosystem must return a job_id, not block on scan."""
        from mahavishnu.mcp.tools.clone_tools import CloneTools

        tools = CloneTools(mock_app)
        result = await tools.clone_detect_ecosystem(repos=None, min_similarity=0.9)

        assert "detect_job_id" in result
        assert result["status"] == "queued"

    async def test_accepts_repo_list(self, mock_app):
        from mahavishnu.mcp.tools.clone_tools import CloneTools

        tools = CloneTools(mock_app)
        result = await tools.clone_detect_ecosystem(repos=["repo_a", "repo_b"])
        assert "detect_job_id" in result

    async def test_accepts_none_repos_default(self, mock_app):
        from mahavishnu.mcp.tools.clone_tools import CloneTools

        tools = CloneTools(mock_app)
        result = await tools.clone_detect_ecosystem()
        assert result["status"] == "queued"


class TestCloneRefactorGroup:
    async def test_returns_refactor_job_id_immediately(self, mock_app):
        """clone_refactor_group must return immediately with a job_id (C-NEW-5)."""
        from mahavishnu.mcp.tools.clone_tools import CloneTools

        tools = CloneTools(mock_app)
        result = await tools.clone_refactor_group(
            cluster_id="abc123",
            extraction_target=None,
        )
        assert "refactor_job_id" in result
        assert result["status"] == "queued"
        assert result["cluster_id"] == "abc123"

    async def test_cross_repo_always_propose_approve(self, mock_app):
        """Cross-repo refactors must flag as PROPOSE_APPROVE (M-NEW-5)."""
        from mahavishnu.mcp.tools.clone_tools import CloneTools

        tools = CloneTools(mock_app)
        result = await tools.clone_refactor_group(
            cluster_id="cross-repo-cluster",
            extraction_target="oneiric",
        )
        assert result.get("decision") == "propose_approve"

    async def test_accepts_extraction_target(self, mock_app):
        from mahavishnu.mcp.tools.clone_tools import CloneTools

        tools = CloneTools(mock_app)
        result = await tools.clone_refactor_group(
            cluster_id="x1",
            extraction_target="new_package",
        )
        assert "refactor_job_id" in result


class TestCloneRefactorStatus:
    async def test_returns_open_clusters_list(self, mock_app):
        from mahavishnu.mcp.tools.clone_tools import CloneTools

        tools = CloneTools(mock_app)
        result = await tools.clone_refactor_status()

        assert "clusters" in result
        assert isinstance(result["clusters"], list)

    async def test_returns_summary_counts(self, mock_app):
        from mahavishnu.mcp.tools.clone_tools import CloneTools

        tools = CloneTools(mock_app)
        result = await tools.clone_refactor_status()
        assert "total" in result


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestRegisterCloneTools:
    def test_register_function_exists(self):
        from mahavishnu.mcp.tools.clone_tools import register_clone_tools

        assert callable(register_clone_tools)

    def test_registers_three_tools(self, mock_mcp, mock_app):
        from mahavishnu.mcp.tools.clone_tools import register_clone_tools

        register_clone_tools(mock_mcp, mock_app)
        assert mock_mcp.tool.call_count == 3

    def test_full_registrations_includes_clone_tools(self):
        from mahavishnu.mcp.tools.profiles import FULL_REGISTRATIONS

        assert "_register_clone_tools" in FULL_REGISTRATIONS

    def test_standard_registrations_excludes_clone_tools(self):
        from mahavishnu.mcp.tools.profiles import STANDARD_REGISTRATIONS

        assert "_register_clone_tools" not in STANDARD_REGISTRATIONS

    def test_minimal_registrations_excludes_clone_tools(self):
        from mahavishnu.mcp.tools.profiles import MINIMAL_REGISTRATIONS

        assert "_register_clone_tools" not in MINIMAL_REGISTRATIONS
