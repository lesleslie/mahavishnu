"""
Comprehensive unit tests for the worktree CLI module.

Tests cover all CLI commands registered on the worktree_app sub-app,
mocking MahavishnuApp and WorktreeCoordinator to avoid filesystem
and git operations.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from mahavishnu.worktree_cli import worktree_app

runner = CliRunner()


def _make_coordinator():
    coord = MagicMock()
    coord.create_worktree = AsyncMock(return_value={"success": True, "worktree_path": "/tmp/test-wt"})
    coord.remove_worktree = AsyncMock(return_value={"success": True})
    coord.list_worktrees = AsyncMock(
        return_value={
            "success": True,
            "worktrees": [
                {"path": "/tmp/wt1", "branch": "feature-x", "exists": True},
            ],
            "total_count": 1,
        }
    )
    coord.prune_worktrees = AsyncMock(return_value={"success": True, "pruned_count": 2})
    coord.get_worktree_safety_status = AsyncMock(
        return_value={
            "uncommitted_changes": False,
            "is_valid_worktree": True,
            "path_safe": True,
            "dependencies": [],
        }
    )
    coord.get_provider_health = AsyncMock(
        return_value={
            "local": {"healthy": True},
            "remote": {"healthy": False, "error": "Connection refused"},
        }
    )
    return coord


def _make_app(coordinator=None):
    app = MagicMock()
    app.initialize_worktree_coordinator = AsyncMock()
    app.worktree_coordinator = coordinator or _make_coordinator()
    return app


@pytest.fixture
def mock_app():
    with patch("mahavishnu.worktree_cli.MahavishnuApp") as MockApp:
        MockApp.load.return_value = _make_app()
        yield MockApp


class TestCreateWorktree:
    """Tests for the 'create' command."""

    def test_create_success(self, mock_app):
        result = runner.invoke(worktree_app, ["create", "myrepo", "feature-branch"])
        assert result.exit_code == 0
        assert "Created worktree" in result.output

    def test_create_with_custom_name(self, mock_app):
        result = runner.invoke(worktree_app, ["create", "myrepo", "feature-branch", "--name", "custom-wt"])
        assert result.exit_code == 0
        coord = mock_app.load.return_value.worktree_coordinator
        coord.create_worktree.assert_called_once_with(
            repo_nickname="myrepo",
            branch="feature-branch",
            worktree_name="custom-wt",
            create_branch=False,
            user_id=None,
        )

    def test_create_with_create_branch_flag(self, mock_app):
        result = runner.invoke(worktree_app, ["create", "myrepo", "new-branch", "-b"])
        assert result.exit_code == 0
        coord = mock_app.load.return_value.worktree_coordinator
        coord.create_worktree.assert_called_once_with(
            repo_nickname="myrepo",
            branch="new-branch",
            worktree_name=None,
            create_branch=True,
            user_id=None,
        )

    def test_create_failure(self, mock_app):
        coord = mock_app.load.return_value.worktree_coordinator
        coord.create_worktree.return_value = {"success": False, "error": "Branch not found"}
        result = runner.invoke(worktree_app, ["create", "myrepo", "bad-branch"])
        assert result.exit_code == 1
        assert "Failed" in result.output
        assert "Branch not found" in result.output

    def test_create_unknown_error(self, mock_app):
        coord = mock_app.load.return_value.worktree_coordinator
        coord.create_worktree.return_value = {"success": False}
        result = runner.invoke(worktree_app, ["create", "myrepo", "branch"])
        assert result.exit_code == 1
        assert "Unknown error" in result.output

    def test_create_coordinator_unavailable(self, mock_app):
        mock_app.load.return_value.worktree_coordinator = None
        result = runner.invoke(worktree_app, ["create", "myrepo", "branch"])
        assert result.exit_code == 1
        assert "not available" in result.output

    def test_create_missing_repo_arg(self):
        result = runner.invoke(worktree_app, ["create", "myrepo"])
        assert result.exit_code != 0

    def test_create_short_name_flag(self, mock_app):
        result = runner.invoke(worktree_app, ["create", "myrepo", "branch", "-n", "wt-name"])
        assert result.exit_code == 0
        coord = mock_app.load.return_value.worktree_coordinator
        coord.create_worktree.assert_called_once()
        assert coord.create_worktree.call_args.kwargs["worktree_name"] == "wt-name"


class TestRemoveWorktree:
    """Tests for the 'remove' command."""

    def test_remove_success(self, mock_app):
        result = runner.invoke(worktree_app, ["remove", "myrepo", "/tmp/wt1"])
        assert result.exit_code == 0
        assert "Removed worktree" in result.output

    def test_remove_with_force(self, mock_app):
        result = runner.invoke(worktree_app, ["remove", "myrepo", "/tmp/wt1", "--force"])
        assert result.exit_code == 0
        coord = mock_app.load.return_value.worktree_coordinator
        coord.remove_worktree.assert_called_once_with(
            repo_nickname="myrepo",
            worktree_path="/tmp/wt1",
            force=True,
            force_reason=None,
            user_id=None,
        )

    def test_remove_with_force_and_reason(self, mock_app):
        result = runner.invoke(
            worktree_app, ["remove", "myrepo", "/tmp/wt1", "-f", "-r", "cleanup needed"]
        )
        assert result.exit_code == 0
        coord = mock_app.load.return_value.worktree_coordinator
        coord.remove_worktree.assert_called_once()
        assert coord.remove_worktree.call_args.kwargs["force_reason"] == "cleanup needed"

    def test_remove_with_backup(self, mock_app):
        coord = mock_app.load.return_value.worktree_coordinator
        coord.remove_worktree.return_value = {
            "success": True,
            "backup_path": "/tmp/backups/wt1.tar.gz",
        }
        result = runner.invoke(worktree_app, ["remove", "myrepo", "/tmp/wt1"])
        assert result.exit_code == 0
        assert "Backup created" in result.output
        assert "/tmp/backups/wt1.tar.gz" in result.output

    def test_remove_failure(self, mock_app):
        coord = mock_app.load.return_value.worktree_coordinator
        coord.remove_worktree.return_value = {"success": False, "error": "Worktree not found"}
        result = runner.invoke(worktree_app, ["remove", "myrepo", "/tmp/wt1"])
        assert result.exit_code == 1
        assert "Failed" in result.output

    def test_remove_coordinator_unavailable(self, mock_app):
        mock_app.load.return_value.worktree_coordinator = None
        result = runner.invoke(worktree_app, ["remove", "myrepo", "/tmp/wt1"])
        assert result.exit_code == 1
        assert "not available" in result.output

    def test_remove_uncommitted_changes_user_cancels(self, mock_app):
        coord = mock_app.load.return_value.worktree_coordinator
        coord.get_worktree_safety_status.return_value = {
            "uncommitted_changes": True,
            "is_valid_worktree": True,
            "path_safe": True,
            "dependencies": [],
        }
        result = runner.invoke(worktree_app, ["remove", "myrepo", "/tmp/wt1"], input="n")
        assert result.exit_code == 0
        assert "cancelled" in result.output.lower()

    def test_remove_uncommitted_changes_user_continues(self, mock_app):
        coord = mock_app.load.return_value.worktree_coordinator
        coord.get_worktree_safety_status.return_value = {
            "uncommitted_changes": True,
            "is_valid_worktree": True,
            "path_safe": True,
            "dependencies": [],
        }
        result = runner.invoke(worktree_app, ["remove", "myrepo", "/tmp/wt1"], input="y")
        assert result.exit_code == 0
        assert "Removed worktree" in result.output

    def test_remove_with_dependencies_user_cancels(self, mock_app):
        coord = mock_app.load.return_value.worktree_coordinator
        coord.get_worktree_safety_status.return_value = {
            "uncommitted_changes": False,
            "is_valid_worktree": True,
            "path_safe": True,
            "dependencies": ["repo-b", "repo-c"],
        }
        result = runner.invoke(worktree_app, ["remove", "myrepo", "/tmp/wt1"], input="n")
        assert result.exit_code == 0
        assert "cancelled" in result.output.lower()

    def test_remove_with_dependencies_user_continues(self, mock_app):
        coord = mock_app.load.return_value.worktree_coordinator
        coord.get_worktree_safety_status.return_value = {
            "uncommitted_changes": False,
            "is_valid_worktree": True,
            "path_safe": True,
            "dependencies": ["repo-b"],
        }
        result = runner.invoke(worktree_app, ["remove", "myrepo", "/tmp/wt1"], input="y")
        assert result.exit_code == 0
        assert "Removed worktree" in result.output

    def test_remove_force_skips_safety_checks(self, mock_app):
        coord = mock_app.load.return_value.worktree_coordinator
        coord.get_worktree_safety_status.return_value = {
            "uncommitted_changes": True,
            "dependencies": ["repo-b"],
        }
        result = runner.invoke(worktree_app, ["remove", "myrepo", "/tmp/wt1", "--force"])
        assert result.exit_code == 0
        coord.remove_worktree.assert_called_once()

    def test_remove_missing_path_arg(self):
        result = runner.invoke(worktree_app, ["remove", "myrepo"])
        assert result.exit_code != 0

    def test_remove_short_force_flag(self, mock_app):
        result = runner.invoke(worktree_app, ["remove", "myrepo", "/tmp/wt1", "-f"])
        assert result.exit_code == 0
        coord = mock_app.load.return_value.worktree_coordinator
        assert coord.remove_worktree.call_args.kwargs["force"] is True


class TestListWorktrees:
    """Tests for the 'list' command."""

    def test_list_success(self, mock_app):
        result = runner.invoke(worktree_app, ["list"])
        assert result.exit_code == 0
        assert "Worktrees" in result.output
        assert "1 total" in result.output
        assert "/tmp/wt1" in result.output
        assert "feature-x" in result.output

    def test_list_with_repo_filter(self, mock_app):
        result = runner.invoke(worktree_app, ["list", "--repo", "myrepo"])
        assert result.exit_code == 0
        coord = mock_app.load.return_value.worktree_coordinator
        coord.list_worktrees.assert_called_once_with(repo_nickname="myrepo")

    def test_list_empty(self, mock_app):
        coord = mock_app.load.return_value.worktree_coordinator
        coord.list_worktrees.return_value = {"success": True, "worktrees": [], "total_count": 0}
        result = runner.invoke(worktree_app, ["list"])
        assert result.exit_code == 0
        assert "0 total" in result.output

    def test_list_nonexistent_worktree(self, mock_app):
        coord = mock_app.load.return_value.worktree_coordinator
        coord.list_worktrees.return_value = {
            "success": True,
            "worktrees": [{"path": "/tmp/missing", "branch": "dead", "exists": False}],
            "total_count": 1,
        }
        result = runner.invoke(worktree_app, ["list"])
        assert result.exit_code == 0
        assert "/tmp/missing" in result.output

    def test_list_failure(self, mock_app):
        coord = mock_app.load.return_value.worktree_coordinator
        coord.list_worktrees.return_value = {"success": False, "error": "Repo not found"}
        result = runner.invoke(worktree_app, ["list"])
        assert result.exit_code == 1
        assert "Failed" in result.output

    def test_list_coordinator_unavailable(self, mock_app):
        mock_app.load.return_value.worktree_coordinator = None
        result = runner.invoke(worktree_app, ["list"])
        assert result.exit_code == 1
        assert "not available" in result.output

    def test_list_short_repo_flag(self, mock_app):
        result = runner.invoke(worktree_app, ["list", "-r", "myrepo"])
        assert result.exit_code == 0
        coord = mock_app.load.return_value.worktree_coordinator
        coord.list_worktrees.assert_called_once_with(repo_nickname="myrepo")


class TestPruneWorktrees:
    """Tests for the 'prune' command."""

    def test_prune_success(self, mock_app):
        result = runner.invoke(worktree_app, ["prune", "myrepo"])
        assert result.exit_code == 0
        assert "Pruned 2" in result.output

    def test_prune_zero(self, mock_app):
        coord = mock_app.load.return_value.worktree_coordinator
        coord.prune_worktrees.return_value = {"success": True, "pruned_count": 0}
        result = runner.invoke(worktree_app, ["prune", "myrepo"])
        assert result.exit_code == 0
        assert "Pruned 0" in result.output

    def test_prune_failure(self, mock_app):
        coord = mock_app.load.return_value.worktree_coordinator
        coord.prune_worktrees.return_value = {"success": False, "error": "Not a git repo"}
        result = runner.invoke(worktree_app, ["prune", "myrepo"])
        assert result.exit_code == 1
        assert "Failed" in result.output

    def test_prune_coordinator_unavailable(self, mock_app):
        mock_app.load.return_value.worktree_coordinator = None
        result = runner.invoke(worktree_app, ["prune", "myrepo"])
        assert result.exit_code == 1
        assert "not available" in result.output

    def test_prune_missing_repo_arg(self):
        result = runner.invoke(worktree_app, ["prune"])
        assert result.exit_code != 0


class TestSafetyStatus:
    """Tests for the 'safety-status' command."""

    def test_safety_status_clean(self, mock_app):
        result = runner.invoke(worktree_app, ["safety-status", "myrepo", "/tmp/wt1"])
        assert result.exit_code == 0
        assert "Safety Status" in result.output
        assert "No" in result.output
        assert "No blocking dependencies" in result.output

    def test_safety_status_uncommitted_changes(self, mock_app):
        coord = mock_app.load.return_value.worktree_coordinator
        coord.get_worktree_safety_status.return_value = {
            "uncommitted_changes": True,
            "is_valid_worktree": True,
            "path_safe": True,
            "dependencies": [],
        }
        result = runner.invoke(worktree_app, ["safety-status", "myrepo", "/tmp/wt1"])
        assert result.exit_code == 0
        assert "Yes" in result.output

    def test_safety_status_invalid_worktree(self, mock_app):
        coord = mock_app.load.return_value.worktree_coordinator
        coord.get_worktree_safety_status.return_value = {
            "uncommitted_changes": False,
            "is_valid_worktree": False,
            "path_safe": False,
            "dependencies": [],
        }
        result = runner.invoke(worktree_app, ["safety-status", "myrepo", "/tmp/wt1"])
        assert result.exit_code == 0
        assert "No" in result.output

    def test_safety_status_with_dependencies(self, mock_app):
        coord = mock_app.load.return_value.worktree_coordinator
        coord.get_worktree_safety_status.return_value = {
            "uncommitted_changes": False,
            "is_valid_worktree": True,
            "path_safe": True,
            "dependencies": ["repo-b", "repo-c"],
        }
        result = runner.invoke(worktree_app, ["safety-status", "myrepo", "/tmp/wt1"])
        assert result.exit_code == 0
        assert "2" in result.output
        assert "repo-b" in result.output
        assert "repo-c" in result.output

    def test_safety_status_coordinator_unavailable(self, mock_app):
        mock_app.load.return_value.worktree_coordinator = None
        result = runner.invoke(worktree_app, ["safety-status", "myrepo", "/tmp/wt1"])
        assert result.exit_code == 1
        assert "not available" in result.output

    def test_safety_status_missing_args(self):
        result = runner.invoke(worktree_app, ["safety-status", "myrepo"])
        assert result.exit_code != 0

    def test_safety_status_missing_all_args(self):
        result = runner.invoke(worktree_app, ["safety-status"])
        assert result.exit_code != 0


class TestProviderHealth:
    """Tests for the 'provider-health' command."""

    def test_provider_health_mixed(self, mock_app):
        result = runner.invoke(worktree_app, ["provider-health"])
        assert result.exit_code == 0
        assert "Provider Health" in result.output
        assert "local" in result.output
        assert "Healthy" in result.output
        assert "Unhealthy" in result.output
        assert "Connection refused" in result.output

    def test_provider_health_all_healthy(self, mock_app):
        coord = mock_app.load.return_value.worktree_coordinator
        coord.get_provider_health.return_value = {
            "local": {"healthy": True},
            "remote": {"healthy": True},
        }
        result = runner.invoke(worktree_app, ["provider-health"])
        assert result.exit_code == 0
        assert "Unhealthy" not in result.output

    def test_provider_health_all_unhealthy(self, mock_app):
        coord = mock_app.load.return_value.worktree_coordinator
        coord.get_provider_health.return_value = {
            "local": {"healthy": False, "error": "git not found"},
            "remote": {"healthy": False, "error": "timeout"},
        }
        result = runner.invoke(worktree_app, ["provider-health"])
        assert result.exit_code == 0
        assert "git not found" in result.output
        assert "timeout" in result.output

    def test_provider_health_empty(self, mock_app):
        coord = mock_app.load.return_value.worktree_coordinator
        coord.get_provider_health.return_value = {}
        result = runner.invoke(worktree_app, ["provider-health"])
        assert result.exit_code == 0
        assert "Provider Health" in result.output

    def test_provider_health_unhealthy_no_error(self, mock_app):
        coord = mock_app.load.return_value.worktree_coordinator
        coord.get_provider_health.return_value = {
            "local": {"healthy": False},
        }
        result = runner.invoke(worktree_app, ["provider-health"])
        assert result.exit_code == 0
        assert "Unhealthy" in result.output
        assert "Error:" not in result.output

    def test_provider_health_coordinator_unavailable(self, mock_app):
        mock_app.load.return_value.worktree_coordinator = None
        result = runner.invoke(worktree_app, ["provider-health"])
        assert result.exit_code == 1
        assert "not available" in result.output


class TestAppLoadException:
    """Tests for exception handling when MahavishnuApp.load fails."""

    def test_create_app_load_raises(self):
        with patch("mahavishnu.worktree_cli.MahavishnuApp") as MockApp:
            MockApp.load.side_effect = RuntimeError("config missing")
            result = runner.invoke(worktree_app, ["create", "repo", "branch"])
            assert result.exit_code != 0

    def test_remove_app_load_raises(self):
        with patch("mahavishnu.worktree_cli.MahavishnuApp") as MockApp:
            MockApp.load.side_effect = RuntimeError("config missing")
            result = runner.invoke(worktree_app, ["remove", "repo", "/tmp/wt"])
            assert result.exit_code != 0

    def test_list_app_load_raises(self):
        with patch("mahavishnu.worktree_cli.MahavishnuApp") as MockApp:
            MockApp.load.side_effect = RuntimeError("config missing")
            result = runner.invoke(worktree_app, ["list"])
            assert result.exit_code != 0

    def test_prune_app_load_raises(self):
        with patch("mahavishnu.worktree_cli.MahavishnuApp") as MockApp:
            MockApp.load.side_effect = RuntimeError("config missing")
            result = runner.invoke(worktree_app, ["prune", "repo"])
            assert result.exit_code != 0

    def test_safety_status_app_load_raises(self):
        with patch("mahavishnu.worktree_cli.MahavishnuApp") as MockApp:
            MockApp.load.side_effect = RuntimeError("config missing")
            result = runner.invoke(worktree_app, ["safety-status", "repo", "/tmp/wt"])
            assert result.exit_code != 0

    def test_provider_health_app_load_raises(self):
        with patch("mahavishnu.worktree_cli.MahavishnuApp") as MockApp:
            MockApp.load.side_effect = RuntimeError("config missing")
            result = runner.invoke(worktree_app, ["provider-health"])
            assert result.exit_code != 0


class TestInitializeCoordinatorRaises:
    """Tests for exception handling when initialize_worktree_coordinator fails."""

    def test_create_init_raises(self):
        with patch("mahavishnu.worktree_cli.MahavishnuApp") as MockApp:
            app = MockApp.load.return_value
            app.initialize_worktree_coordinator = AsyncMock(
                side_effect=RuntimeError("init failed")
            )
            result = runner.invoke(worktree_app, ["create", "repo", "branch"])
            assert result.exit_code != 0

    def test_list_init_raises(self):
        with patch("mahavishnu.worktree_cli.MahavishnuApp") as MockApp:
            app = MockApp.load.return_value
            app.initialize_worktree_coordinator = AsyncMock(
                side_effect=RuntimeError("init failed")
            )
            result = runner.invoke(worktree_app, ["list"])
            assert result.exit_code != 0
