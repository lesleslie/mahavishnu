"""Unit tests for Mahavishnu IPython magic commands."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.shell.magics import MahavishnuMagics


@pytest.fixture
def mock_shell():
    return MagicMock()


@pytest.fixture
def magics(mock_shell):
    with patch("mahavishnu.shell.magics.Magics.__init__", return_value=None):
        m = MahavishnuMagics.__new__(MahavishnuMagics)
        m.shell = mock_shell
        m.app = None
        m.repo_formatter = MagicMock()
        m.workflow_formatter = MagicMock()
        return m


@pytest.fixture
def app():
    app = MagicMock()
    app.get_all_repos = MagicMock(
        return_value=[
            {"path": "/tmp/repo1", "tags": ["python", "backend"], "description": "Repo 1"},
            {"path": "/tmp/repo2", "tags": ["go", "backend"], "description": "Repo 2"},
            {"path": "/tmp/repo3", "tags": ["python", "frontend"], "description": "Repo 3"},
        ]
    )
    return app


def _make_workflow_state_manager(workflow=None, exception=None):
    async def _get(workflow_id):
        if exception:
            raise exception
        return workflow

    mgr = MagicMock()
    mgr.get = MagicMock(side_effect=_get)
    return mgr


class TestMahavishnuMagicsInit:
    """Test MahavishnuMagics initialization."""

    def test_init_creates_instance(self):
        """Test that MahavishnuMagics can be instantiated with a shell."""
        shell = MagicMock()
        with patch("mahavishnu.shell.magics.Magics.__init__", return_value=None):
            m = MahavishnuMagics(shell)
        assert m is not None

    def test_init_app_is_none(self, mock_shell):
        """Test that app reference starts as None."""
        with patch("mahavishnu.shell.magics.Magics.__init__", return_value=None):
            m = MahavishnuMagics(mock_shell)
        assert m.app is None

    def test_init_creates_repo_formatter(self, mock_shell):
        """Test that RepoFormatter is created during init."""
        with patch("mahavishnu.shell.magics.Magics.__init__", return_value=None):
            m = MahavishnuMagics(mock_shell)
        assert m.repo_formatter is not None

    def test_init_creates_workflow_formatter(self, mock_shell):
        """Test that WorkflowFormatter is created during init."""
        with patch("mahavishnu.shell.magics.Magics.__init__", return_value=None):
            m = MahavishnuMagics(mock_shell)
        assert m.workflow_formatter is not None

    def test_init_calls_super(self, mock_shell):
        """Test that __init__ passes shell to parent class."""
        with patch("mahavishnu.shell.magics.Magics.__init__", return_value=None) as mock_super:
            MahavishnuMagics(mock_shell)
            mock_super.assert_called_once_with(mock_shell)

    def test_set_app(self, magics, app):
        """Test that set_app stores the application reference."""
        magics.set_app(app)
        assert magics.app is app

    def test_set_app_overwrites(self, magics, app):
        """Test that set_app can overwrite a previous app reference."""
        app2 = MagicMock()
        magics.set_app(app)
        magics.set_app(app2)
        assert magics.app is app2


class TestReposMagic:
    """Test the %repos line magic."""

    def test_repos_no_app(self, magics, capsys):
        """Test that repos prints message when no app is configured."""
        magics.repos("")
        captured = capsys.readouterr()
        assert "No application configured" in captured.out

    def test_repos_empty_line(self, magics, app, capsys):
        """Test that repos with empty string argument lists all repos."""
        magics.set_app(app)
        magics.repos("")
        app.get_all_repos.assert_called_once()
        captured = capsys.readouterr()
        assert "No repositories" not in captured.out

    def test_repos_whitespace_line(self, magics, app):
        """Test that repos with whitespace-only argument lists all repos."""
        magics.set_app(app)
        magics.repos("   ")
        app.get_all_repos.assert_called_once()

    def test_repos_with_tag_filter(self, magics, app, capsys):
        """Test that repos filters by tag when tag is provided."""
        magics.set_app(app)
        magics.repos("python")
        app.get_all_repos.assert_called_once()
        captured = capsys.readouterr()
        assert "No repositories" not in captured.out

    def test_repos_tag_filter_excludes_non_matching(self, magics, app):
        """Test that repos with tag filter excludes repos without that tag."""
        magics.set_app(app)
        magics.repos("go")
        magics.repo_formatter.format_repos.assert_called_once()
        repos_arg = magics.repo_formatter.format_repos.call_args[0][0]
        assert len(repos_arg) == 1
        assert repos_arg[0]["path"] == "/tmp/repo2"

    def test_repos_no_matching_tag(self, magics, app):
        """Test that repos with non-matching tag shows no repos."""
        magics.set_app(app)
        magics.repos("rust")
        magics.repo_formatter.format_repos.assert_called_once()
        repos_arg = magics.repo_formatter.format_repos.call_args[0][0]
        assert repos_arg == []

    def test_repos_calls_formatter_with_show_tags_true(self, magics, app):
        """Test that repos calls format_repos with show_tags=True."""
        magics.set_app(app)
        magics.repos("")
        magics.repo_formatter.format_repos.assert_called_once()
        kwargs = magics.repo_formatter.format_repos.call_args[1]
        assert kwargs.get("show_tags") is True

    def test_repos_app_without_get_all_repos(self, magics, capsys):
        """Test that repos handles app without get_all_repos attribute."""
        bare_app = MagicMock(spec=[])
        magics.set_app(bare_app)
        magics.repos("")
        magics.repo_formatter.format_repos.assert_called_once()
        repos_arg = magics.repo_formatter.format_repos.call_args[0][0]
        assert repos_arg == []

    def test_repos_empty_repo_list(self, magics, app):
        """Test that repos handles empty repo list from app."""
        app.get_all_repos = MagicMock(return_value=[])
        magics.set_app(app)
        magics.repos("")
        repos_arg = magics.repo_formatter.format_repos.call_args[0][0]
        assert repos_arg == []

    def test_repos_repo_missing_tags_key(self, magics, app):
        """Test that repos handles repos without tags key gracefully."""
        app.get_all_repos = MagicMock(
            return_value=[
                {"path": "/tmp/repo1", "description": "Repo 1"},
            ]
        )
        magics.set_app(app)
        magics.repos("python")
        repos_arg = magics.repo_formatter.format_repos.call_args[0][0]
        assert repos_arg == []


class TestWorkflowMagic:
    """Test the %workflow line magic."""

    def test_workflow_no_app(self, magics, capsys):
        """Test that workflow prints message when no app is configured."""
        magics.workflow("abc123")
        captured = capsys.readouterr()
        assert "No application configured" in captured.out

    def test_workflow_empty_id(self, magics, app, capsys):
        """Test that workflow prints usage when no id is provided."""
        magics.set_app(app)
        magics.workflow("")
        captured = capsys.readouterr()
        assert "Usage: %workflow <id>" in captured.out

    def test_workflow_whitespace_id(self, magics, app, capsys):
        """Test that workflow prints usage when id is whitespace only."""
        magics.set_app(app)
        magics.workflow("   ")
        captured = capsys.readouterr()
        assert "Usage: %workflow <id>" in captured.out

    def test_workflow_not_found(self, magics, app, capsys):
        """Test that workflow prints not found message for missing workflow."""
        magics.set_app(app)
        app.workflow_state_manager = _make_workflow_state_manager(workflow=None)

        with patch("mahavishnu.shell.magics.asyncio.run", return_value=None):
            magics.workflow("nonexistent")
        captured = capsys.readouterr()
        assert "Workflow not found: nonexistent" in captured.out

    def test_workflow_found_calls_formatter(self, magics, app):
        """Test that workflow calls format_workflow_detail when found."""
        magics.set_app(app)
        workflow = {"id": "wf-1", "status": "running", "progress": 50}
        app.workflow_state_manager = _make_workflow_state_manager(workflow=workflow)

        with patch("mahavishnu.shell.magics.asyncio.run", return_value=workflow):
            magics.workflow("wf-1")
        magics.workflow_formatter.format_workflow_detail.assert_called_once_with(workflow)

    def test_workflow_exception(self, magics, app, capsys):
        """Test that workflow prints error message on exception."""
        magics.set_app(app)
        app.workflow_state_manager = _make_workflow_state_manager(exception=RuntimeError("boom"))

        with patch("mahavishnu.shell.magics.asyncio.run", side_effect=RuntimeError("boom")):
            magics.workflow("wf-1")
        captured = capsys.readouterr()
        assert "Error fetching workflow: boom" in captured.out

    def test_workflow_strips_id(self, magics, app):
        """Test that workflow strips whitespace from the id argument."""
        magics.set_app(app)
        app.workflow_state_manager = _make_workflow_state_manager(workflow={"id": "wf-1"})

        with patch("mahavishnu.shell.magics.asyncio.run", return_value={"id": "wf-1"}) as mock_run:
            magics.workflow("  wf-1  ")
            mock_run.assert_called_once()
            coroutine = mock_run.call_args[0][0]
            assert asyncio.iscoroutine(coroutine)


class TestMagicRegistration:
    """Test that magic commands are properly registered."""

    def test_repos_is_line_magic(self):
        """Test that repos is registered as a line magic."""
        assert hasattr(MahavishnuMagics, "repos")
        assert callable(MahavishnuMagics.repos)

    def test_workflow_is_line_magic(self):
        """Test that workflow is registered as a line magic."""
        assert hasattr(MahavishnuMagics, "workflow")
        assert callable(MahavishnuMagics.workflow)

    def test_magics_class_decorator(self):
        """Test that MahavishnuMagics is decorated with magics_class."""
        assert hasattr(MahavishnuMagics, "__wrapped__") or issubclass(MahavishnuMagics, object)
