"""Tests for SessionBuddyWorktreeProvider and DirectGitWorktreeProvider."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import mahavishnu.core.worktree_providers as worktree_providers_pkg
from mahavishnu.core.worktree_providers.direct_git import DirectGitWorktreeProvider
from mahavishnu.core.worktree_providers.errors import (
    ProviderUnavailableError,
    WorktreeCreationError,
    WorktreeOperationError,
    WorktreeRemovalError,
    WorktreeValidationError,
)
from mahavishnu.core.worktree_providers.mock import MockWorktreeProvider
from mahavishnu.core.worktree_providers.registry import WorktreeProviderRegistry
from mahavishnu.core.worktree_providers.session_buddy import (
    SessionBuddyWorktreeProvider,
)

# ---------------------------------------------------------------------------
# SessionBuddyWorktreeProvider
# ---------------------------------------------------------------------------


class TestSessionBuddyProviderInit:
    def test_default_url(self):
        p = SessionBuddyWorktreeProvider()
        assert p.session_buddy_url == "http://localhost:8678/mcp"
        assert p._mcp_client is None
        assert p._is_healthy is True

    def test_custom_url(self):
        p = SessionBuddyWorktreeProvider(session_buddy_url="http://custom:9000/mcp")
        assert p.session_buddy_url == "http://custom:9000/mcp"

    def test_provider_name(self):
        assert SessionBuddyWorktreeProvider().provider_name() == "session-buddy"


class TestSessionBuddyGetMcpClient:
    async def test_creates_client_on_first_call(self):
        provider = SessionBuddyWorktreeProvider()
        mock_instance = AsyncMock()
        mock_cls = MagicMock(return_value=mock_instance)
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=None)

        mock_module = ModuleType("mcp_client")
        mock_module.MCPClient = mock_cls
        with patch.dict("sys.modules", {"mcp_client": mock_module}):
            client = await provider._get_mcp_client()

        assert client is mock_instance
        mock_cls.assert_called_once_with("http://localhost:8678/mcp")
        assert provider._mcp_client is mock_instance

    async def test_returns_cached_client(self):
        provider = SessionBuddyWorktreeProvider()
        mock_client = AsyncMock()
        provider._mcp_client = mock_client

        client = await provider._get_mcp_client()
        assert client is mock_client

    async def test_import_error_raises_creation_error(self):
        provider = SessionBuddyWorktreeProvider()

        with (
            patch.dict("sys.modules", {"mcp_client": None}),
            pytest.raises(
                WorktreeCreationError,
                match="MCP client not installed",
            ),
        ):
            await provider._get_mcp_client()

    async def test_connection_error_raises_creation_error(self):
        provider = SessionBuddyWorktreeProvider()

        mock_cls = MagicMock(side_effect=Exception("connection refused"))

        mock_module = ModuleType("mcp_client")
        mock_module.MCPClient = mock_cls
        with (
            patch.dict("sys.modules", {"mcp_client": mock_module}),
            pytest.raises(
                WorktreeCreationError,
                match="Failed to connect",
            ),
        ):
            await provider._get_mcp_client()


class TestSessionBuddyCreateWorktree:
    async def test_success(self):
        provider = SessionBuddyWorktreeProvider()
        mock_client = AsyncMock()
        provider._mcp_client = mock_client
        mock_client.call_tool = AsyncMock(return_value={"status": "ok"})

        repo = Path("/repo")
        result = await provider.create_worktree(repo, "main", Path("/wt/main"), create_branch=True)

        assert result["success"] is True
        assert result["worktree_path"] == "/wt/main"
        assert result["branch"] == "main"
        assert result["provider"] == "session-buddy"
        mock_client.call_tool.assert_called_once_with(
            "create_worktree",
            arguments={
                "repository_path": "/repo",
                "branch": "main",
                "new_path": "/wt/main",
                "create_branch": True,
            },
        )

    async def test_creation_error_propagated(self):
        provider = SessionBuddyWorktreeProvider()
        mock_client = AsyncMock()
        provider._mcp_client = mock_client
        mock_client.call_tool = AsyncMock(side_effect=Exception("fail"))

        with pytest.raises(WorktreeCreationError, match="worktree creation failed"):
            await provider.create_worktree(Path("/repo"), "main", Path("/wt"))

    async def test_creation_error_reraised(self):
        provider = SessionBuddyWorktreeProvider()
        mock_client = AsyncMock()
        provider._mcp_client = mock_client
        mock_client.call_tool = AsyncMock(side_effect=WorktreeCreationError("already exists"))

        with pytest.raises(WorktreeCreationError):
            await provider.create_worktree(Path("/repo"), "main", Path("/wt"))


class TestSessionBuddyRemoveWorktree:
    async def test_success(self):
        provider = SessionBuddyWorktreeProvider()
        mock_client = AsyncMock()
        provider._mcp_client = mock_client
        mock_client.call_tool = AsyncMock(return_value={"status": "ok"})

        result = await provider.remove_worktree(Path("/repo"), Path("/wt/main"), force=True)

        assert result["success"] is True
        assert result["removed_path"] == "/wt/main"
        assert result["provider"] == "session-buddy"
        mock_client.call_tool.assert_called_once_with(
            "remove_worktree",
            arguments={
                "repository_path": "/repo",
                "worktree_path": "/wt/main",
                "force": True,
            },
        )

    async def test_removal_error(self):
        provider = SessionBuddyWorktreeProvider()
        mock_client = AsyncMock()
        provider._mcp_client = mock_client
        mock_client.call_tool = AsyncMock(side_effect=Exception("fail"))

        with pytest.raises(WorktreeRemovalError):
            await provider.remove_worktree(Path("/repo"), Path("/wt"))

    async def test_removal_error_reraised(self):
        provider = SessionBuddyWorktreeProvider()
        mock_client = AsyncMock()
        provider._mcp_client = mock_client
        mock_client.call_tool = AsyncMock(side_effect=WorktreeRemovalError("locked"))

        with pytest.raises(WorktreeRemovalError):
            await provider.remove_worktree(Path("/repo"), Path("/wt"))


class TestSessionBuddyListWorktrees:
    async def test_success(self):
        provider = SessionBuddyWorktreeProvider()
        mock_client = AsyncMock()
        provider._mcp_client = mock_client
        mock_client.call_tool = AsyncMock(
            return_value={"worktrees": [{"path": "/wt/1"}, {"path": "/wt/2"}]}
        )

        result = await provider.list_worktrees(Path("/repo"))

        assert result["success"] is True
        assert result["worktrees"] == [{"path": "/wt/1"}, {"path": "/wt/2"}]
        assert result["provider"] == "session-buddy"
        mock_client.call_tool.assert_called_once_with(
            "list_worktrees",
            arguments={"repository_path": "/repo"},
        )

    async def test_list_error(self):
        provider = SessionBuddyWorktreeProvider()
        mock_client = AsyncMock()
        provider._mcp_client = mock_client
        mock_client.call_tool = AsyncMock(side_effect=Exception("fail"))

        with pytest.raises(WorktreeValidationError):
            await provider.list_worktrees(Path("/repo"))

    async def test_list_error_reraised(self):
        provider = SessionBuddyWorktreeProvider()
        mock_client = AsyncMock()
        provider._mcp_client = mock_client
        mock_client.call_tool = AsyncMock(side_effect=WorktreeValidationError("invalid"))

        with pytest.raises(WorktreeValidationError):
            await provider.list_worktrees(Path("/repo"))

    async def test_empty_worktrees(self):
        provider = SessionBuddyWorktreeProvider()
        mock_client = AsyncMock()
        provider._mcp_client = mock_client
        mock_client.call_tool = AsyncMock(return_value={"worktrees": []})

        result = await provider.list_worktrees(Path("/repo"))
        assert result["worktrees"] == []


class TestSessionBuddyHealthCheck:
    def test_healthy(self):
        provider = SessionBuddyWorktreeProvider()
        mock_socket = MagicMock()
        mock_socket.connect_ex.return_value = 0

        with patch("socket.socket", return_value=mock_socket):
            assert provider.health_check() is True

    def test_unreachable(self):
        provider = SessionBuddyWorktreeProvider()
        mock_socket = MagicMock()
        mock_socket.connect_ex.return_value = 1

        with patch("socket.socket", return_value=mock_socket):
            assert provider.health_check() is False

    def test_exception(self):
        provider = SessionBuddyWorktreeProvider()

        with patch("socket.socket", side_effect=OSError("network")):
            assert provider.health_check() is False

    def test_custom_port(self):
        provider = SessionBuddyWorktreeProvider(session_buddy_url="http://example.com:9999/mcp")
        mock_socket = MagicMock()
        mock_socket.connect_ex.return_value = 0

        with patch("socket.socket", return_value=mock_socket):
            assert provider.health_check() is True
            mock_socket.connect_ex.assert_called_once_with(("example.com", 9999))


class TestSessionBuddyClose:
    async def test_close_with_client(self):
        provider = SessionBuddyWorktreeProvider()
        mock_client = AsyncMock()
        provider._mcp_client = mock_client

        await provider.close()

        mock_client.__aexit__.assert_called_once_with(None, None, None)
        assert provider._mcp_client is None

    async def test_close_without_client(self):
        provider = SessionBuddyWorktreeProvider()
        provider._mcp_client = None

        await provider.close()  # Should not raise


# ---------------------------------------------------------------------------
# DirectGitWorktreeProvider
# ---------------------------------------------------------------------------


class TestDirectGitProviderInit:
    def test_default_git_executable(self):
        p = DirectGitWorktreeProvider()
        assert p._git_executable == "git"

    def test_provider_name(self):
        assert DirectGitWorktreeProvider.provider_name() == "DirectGitWorktreeProvider"


class TestDirectGitHealthCheck:
    def test_git_available(self):
        with patch("shutil.which", return_value="/usr/bin/git"):
            assert DirectGitWorktreeProvider().health_check() is True

    def test_git_not_available(self):
        with patch("shutil.which", return_value=None):
            assert DirectGitWorktreeProvider().health_check() is False

    def test_exception(self):
        with patch("shutil.which", side_effect=OSError("error")):
            assert DirectGitWorktreeProvider().health_check() is False


def _make_process(returncode=0, stdout=b"", stderr=b""):
    p = AsyncMock()
    p.communicate = AsyncMock(return_value=(stdout, stderr))
    p.returncode = returncode
    return p


class TestDirectGitCreateWorktree:
    async def test_create_branch(self):
        provider = DirectGitWorktreeProvider()
        repo = Path("/repo")
        wt = Path("/wt/branch")
        process = _make_process()

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            result = await provider.create_worktree(repo, "feature", wt, create_branch=True)

        assert result["success"] is True
        assert result["branch"] == "feature"
        assert result["worktree_path"] == "/wt/branch"
        assert result["provider"] == "DirectGitWorktreeProvider"

    async def test_existing_branch(self):
        provider = DirectGitWorktreeProvider()
        repo = Path("/repo")
        wt = Path("/wt/main")
        process = _make_process()

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)) as mock_exec:
            result = await provider.create_worktree(repo, "main", wt, create_branch=False)

        assert result["success"] is True
        cmd = mock_exec.call_args[0]
        assert "-B" in cmd

    async def test_failure_raises(self):
        provider = DirectGitWorktreeProvider()
        process = _make_process(returncode=128, stderr=b"fatal: not a git repo\n")
        process.communicate = AsyncMock(return_value=(b"", b"fatal: not a git repo\n"))

        with (
            patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)),
            pytest.raises(
                WorktreeCreationError,
                match="Failed to create worktree",
            ),
        ):
            await provider.create_worktree(Path("/bad"), "f", Path("/wt"))


class TestDirectGitRemoveWorktree:
    async def test_success(self):
        provider = DirectGitWorktreeProvider()
        process = _make_process()

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            result = await provider.remove_worktree(Path("/repo"), Path("/wt"))

        assert result["success"] is True
        assert result["removed_path"] == "/wt"

    async def test_force_removal(self):
        provider = DirectGitWorktreeProvider()
        process = _make_process()

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)) as mock_exec:
            await provider.remove_worktree(Path("/repo"), Path("/wt"), force=True)

        cmd = mock_exec.call_args[0]
        assert "--force" in cmd

    async def test_failure_raises(self):
        provider = DirectGitWorktreeProvider()
        process = _make_process(returncode=1, stderr=b"error\n")

        with (
            patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)),
            pytest.raises(
                WorktreeOperationError,
                match="Failed to remove worktree",
            ),
        ):
            await provider.remove_worktree(Path("/repo"), Path("/wt"))


class TestDirectGitListWorktrees:
    async def test_success(self):
        provider = DirectGitWorktreeProvider()
        output = b"/repo/main main abc123 ok\n/repo/feature feature def456 ok\n"
        process = _make_process(stdout=output)

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            result = await provider.list_worktrees(Path("/repo"))

        assert result["success"] is True
        assert len(result["worktrees"]) == 2
        assert result["worktrees"][0]["path"] == "/repo/main"
        assert result["worktrees"][0]["branch"] == "main"

    async def test_empty_output(self):
        provider = DirectGitWorktreeProvider()
        process = _make_process(stdout=b"")

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            result = await provider.list_worktrees(Path("/repo"))

        assert result["success"] is True
        assert result["worktrees"] == []

    async def test_skips_empty_lines(self):
        provider = DirectGitWorktreeProvider()
        output = b"/repo/main main abc123 ok\n\n\n/repo/feat feat def456 ok\n"
        process = _make_process(stdout=output)

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            result = await provider.list_worktrees(Path("/repo"))

        assert len(result["worktrees"]) == 2

    async def test_skips_short_lines(self):
        provider = DirectGitWorktreeProvider()
        output = b"short\n"
        process = _make_process(stdout=output)

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            result = await provider.list_worktrees(Path("/repo"))

        assert result["worktrees"] == []

    async def test_failure_raises(self):
        provider = DirectGitWorktreeProvider()
        process = _make_process(returncode=1, stderr=b"error\n")

        with (
            patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)),
            pytest.raises(
                WorktreeOperationError,
                match="Failed to list worktrees",
            ),
        ):
            await provider.list_worktrees(Path("/repo"))

    async def test_handles_three_column_porcelain(self):
        provider = DirectGitWorktreeProvider()
        output = b"/repo/main main abc123\n"
        process = _make_process(stdout=output)

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            result = await provider.list_worktrees(Path("/repo"))

        assert len(result["worktrees"]) == 0


class TestMockWorktreeProvider:
    def test_init_and_identity(self) -> None:
        provider = MockWorktreeProvider()

        assert provider.provider_name() == "mock"
        assert provider.health_check() is True
        assert provider.created_worktrees == []
        assert provider.removed_worktrees == []
        assert provider.should_fail is False

    async def test_create_remove_list_and_reset(self) -> None:
        provider = MockWorktreeProvider()

        created = await provider.create_worktree(
            Path("/repo"),
            "feature",
            Path("/wt/feature"),
            create_branch=True,
        )
        removed = await provider.remove_worktree(Path("/repo"), Path("/wt/feature"), force=True)
        listed = await provider.list_worktrees(Path("/repo"))

        assert created == {
            "success": True,
            "worktree_path": "/wt/feature",
            "branch": "feature",
            "repository_path": "/repo",
        }
        assert removed == {
            "success": True,
            "removed_path": "/wt/feature",
            "repository_path": "/repo",
        }
        assert listed == {
            "success": True,
            "worktrees": [{"path": "/wt/feature", "branch": "feature"}],
            "repository_path": "/repo",
        }
        assert provider.created_worktrees == [
            {
                "repository_path": "/repo",
                "branch": "feature",
                "worktree_path": "/wt/feature",
                "create_branch": True,
            }
        ]
        assert provider.removed_worktrees == ["/wt/feature"]

        provider.set_healthy(False)
        assert provider.health_check() is False

        provider.reset()
        assert provider.created_worktrees == []
        assert provider.removed_worktrees == []
        assert provider.should_fail is False
        assert provider.health_check() is True

    async def test_failures_raise_expected_errors(self) -> None:
        provider = MockWorktreeProvider()
        provider.should_fail = True

        with pytest.raises(WorktreeCreationError, match="Mock provider failure"):
            await provider.create_worktree(Path("/repo"), "feature", Path("/wt/feature"))

        with pytest.raises(WorktreeRemovalError, match="Mock provider failure"):
            await provider.remove_worktree(Path("/repo"), Path("/wt/feature"))

    async def test_list_worktrees_filters_by_repository(self) -> None:
        provider = MockWorktreeProvider()
        await provider.create_worktree(Path("/repo-a"), "a", Path("/wt/a"))
        await provider.create_worktree(Path("/repo-b"), "b", Path("/wt/b"))

        result = await provider.list_worktrees(Path("/repo-a"))

        assert result["worktrees"] == [{"path": "/wt/a", "branch": "a"}]


class _FakeProvider:
    def __init__(self, name: str, healthy: bool) -> None:
        self._name = name
        self._healthy = healthy

    def provider_name(self) -> str:
        return self._name

    def health_check(self) -> bool:
        return self._healthy


class _ExplodingProvider(_FakeProvider):
    def health_check(self) -> bool:
        raise RuntimeError("boom")


class TestWorktreeProviderRegistry:
    async def test_get_available_provider_returns_first_healthy(self):
        first = _FakeProvider("first", True)
        second = _FakeProvider("second", True)
        registry = WorktreeProviderRegistry([first, second])

        provider = await registry.get_available_provider()

        assert provider is first
        assert registry.get_provider_health() == {"first": True}

    async def test_get_available_provider_skips_unhealthy_and_falls_back(self):
        first = _FakeProvider("first", False)
        second = _FakeProvider("second", True)
        registry = WorktreeProviderRegistry([first, second])

        provider = await registry.get_available_provider()

        assert provider is second
        assert registry.get_provider_health() == {"first": False, "second": True}

    async def test_get_available_provider_raises_when_all_unavailable(self):
        first = _FakeProvider("first", False)
        second = _FakeProvider("second", False)
        registry = WorktreeProviderRegistry([first, second])

        with pytest.raises(ProviderUnavailableError) as exc_info:
            await registry.get_available_provider()

        assert "No worktree providers available" in str(exc_info.value)
        assert exc_info.value.providers == ["first", "second"]

    async def test_get_available_provider_skips_exploding_provider(self):
        first = _ExplodingProvider("first", True)
        second = _FakeProvider("second", True)
        registry = WorktreeProviderRegistry([first, second])

        provider = await registry.get_available_provider()

        assert provider is second
        assert registry.get_provider_health() == {"first": False, "second": True}

    def test_get_primary_provider(self):
        provider = _FakeProvider("first", True)
        registry = WorktreeProviderRegistry([provider])

        assert registry.get_primary_provider() is provider

    def test_get_primary_provider_empty_registry(self):
        registry = WorktreeProviderRegistry([])

        with pytest.raises(IndexError, match="No providers configured"):
            registry.get_primary_provider()

    def test_get_provider_health_returns_copy(self):
        provider = _FakeProvider("first", True)
        registry = WorktreeProviderRegistry([provider])
        registry._provider_health["first"] = True

        health = registry.get_provider_health()
        health["first"] = False

        assert registry.get_provider_health()["first"] is True

    async def test_health_check_loop_runs_and_handles_cancellation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = _FakeProvider("first", True)
        registry = WorktreeProviderRegistry([provider])

        calls = {"count": 0}

        async def fake_sleep(_: float) -> None:
            calls["count"] += 1
            if calls["count"] > 1:
                raise asyncio.CancelledError()

        monkeypatch.setattr("asyncio.sleep", fake_sleep)

        await registry.health_check_loop(interval_seconds=0.0)

        assert registry.get_provider_health() == {"first": True}

    async def test_health_check_loop_handles_provider_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = _ExplodingProvider("first", True)
        registry = WorktreeProviderRegistry([provider])

        calls = {"count": 0}

        async def fake_sleep(_: float) -> None:
            calls["count"] += 1
            if calls["count"] > 1:
                raise asyncio.CancelledError()

        monkeypatch.setattr("asyncio.sleep", fake_sleep)

        await registry.health_check_loop(interval_seconds=0.0)

        assert registry.get_provider_health() == {"first": False}

    async def test_health_check_loop_handles_unhealthy_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = _FakeProvider("first", False)
        registry = WorktreeProviderRegistry([provider])

        calls = {"count": 0}

        async def fake_sleep(_: float) -> None:
            calls["count"] += 1
            if calls["count"] > 1:
                raise asyncio.CancelledError()

        monkeypatch.setattr("asyncio.sleep", fake_sleep)

        await registry.health_check_loop(interval_seconds=0.0)

        assert registry.get_provider_health() == {"first": False}

    async def test_health_check_loop_handles_sleep_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = _FakeProvider("first", True)
        registry = WorktreeProviderRegistry([provider])

        calls = {"count": 0}

        async def fake_sleep(_: float) -> None:
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("sleep failed")
            raise asyncio.CancelledError()

        monkeypatch.setattr("asyncio.sleep", fake_sleep)

        await registry.health_check_loop(interval_seconds=0.0)

        assert registry.get_provider_health() == {}


def test_lazy_imports_and_attribute_errors() -> None:
    assert worktree_providers_pkg.WorktreeProviderRegistry is WorktreeProviderRegistry
    assert worktree_providers_pkg.ProviderUnavailableError is ProviderUnavailableError

    with pytest.raises(AttributeError):
        worktree_providers_pkg.__getattr__("does_not_exist")


# ---------------------------------------------------------------------------
# WorktreeProviderError.to_dict
# ---------------------------------------------------------------------------


def test_worktree_provider_error_to_dict():
    """WorktreeOperationError.to_dict returns expected keys (line 39 in errors.py)."""
    err = WorktreeOperationError(
        message="something failed",
        details={"op": "create"},
        providers=["direct_git", "session_buddy"],
    )
    d = err.to_dict()
    assert d["error"] == "something failed"
    assert d["error_type"] == "WorktreeOperationError"
    assert d["details"] == {"op": "create"}
    assert d["providers"] == ["direct_git", "session_buddy"]
