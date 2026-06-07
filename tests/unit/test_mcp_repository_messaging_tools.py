"""Unit tests for mahavishnu.mcp.tools.repository_messaging_tools.

The module exposes ``register_repository_messaging_tools(server, app,
mcp_client)`` which decorates 7 FastMCP tools. All tools delegate to
``RepositoryMessengerManager`` — tests mock that manager.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.mcp.tools import repository_messaging_tools as rmt
from mahavishnu.messaging.repository_messenger import (
    MessagePriority,
    MessageType,
    RepositoryMessage,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


class _StubMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


@pytest.fixture
def fake_messenger():
    """MagicMock for the inner messenger object."""
    m = MagicMock()
    m.send_message = AsyncMock()
    m.broadcast_message = AsyncMock()
    m.get_messages_for_repo = AsyncMock(return_value=[])
    m.acknowledge_message = AsyncMock(return_value=True)
    return m


@pytest.fixture
def fake_manager(fake_messenger):
    """MagicMock for the manager with a .messenger attribute."""
    mgr = MagicMock()
    mgr.messenger = fake_messenger
    mgr.process_repository_changes = AsyncMock(
        return_value={"status": "success", "messages_sent": 2, "changes_notified": 3}
    )
    mgr.notify_workflow_status = AsyncMock(return_value={"status": "success", "messages_sent": 1})
    mgr.send_quality_alert = AsyncMock(return_value={"status": "success", "messages_sent": 1})
    return mgr


@pytest.fixture
def fake_app(fake_manager):
    """A stub app with a get_repos() method."""
    app = MagicMock()
    app.get_repos = MagicMock(return_value=["repo-a", "repo-b"])
    return app


@pytest.fixture
def registered(fake_app, fake_manager, monkeypatch):
    """Register tools against a stub MCP and patch the manager constructor."""
    server = _StubMCP()
    mcp_client = MagicMock()
    monkeypatch.setattr(
        "mahavishnu.mcp.tools.repository_messaging_tools.RepositoryMessengerManager",
        lambda app: fake_manager,
    )
    rmt.register_repository_messaging_tools(server, fake_app, mcp_client)
    return server


def _make_message(
    msg_id: str = "msg-1",
    sender: str = "repo-a",
    receiver: str = "repo-b",
    msg_type: MessageType = MessageType.WORKFLOW_STATUS_UPDATE,
    priority: MessagePriority = MessagePriority.NORMAL,
):
    return RepositoryMessage(
        id=msg_id,
        sender_repo=sender,
        receiver_repo=receiver,
        message_type=msg_type,
        content={"k": "v"},
        priority=priority,
        timestamp=datetime.now(UTC),
        correlation_id=None,
    )


# =============================================================================
# send_repository_message
# =============================================================================


class TestSendMessage:
    """send_repository_message forwards to messenger.send_message."""

    @pytest.mark.asyncio
    async def test_success(self, registered, fake_messenger):
        """A valid send should call send_message and return success dict."""
        msg = _make_message()
        fake_messenger.send_message.return_value = msg

        tool = registered.tools["send_repository_message"]
        result = await tool(
            sender_repo="repo-a",
            receiver_repo="repo-b",
            message_type="workflow_status_update",
            content={"k": "v"},
        )

        assert result["status"] == "success"
        assert result["message_id"] == "msg-1"
        assert result["priority"] == "normal"
        fake_messenger.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalid_message_type(self, registered):
        """An unknown message type returns an error dict, not raise."""
        tool = registered.tools["send_repository_message"]
        result = await tool(
            sender_repo="a",
            receiver_repo="b",
            message_type="totally_made_up",
            content={},
        )
        assert result["status"] == "error"
        assert "Invalid message type" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_priority(self, registered):
        """An unknown priority returns an error dict, not raise."""
        tool = registered.tools["send_repository_message"]
        result = await tool(
            sender_repo="a",
            receiver_repo="b",
            message_type="workflow_status_update",
            content={},
            priority="bogus",
        )
        assert result["status"] == "error"
        assert "Invalid priority" in result["error"]

    @pytest.mark.asyncio
    async def test_exception_caught(self, registered, fake_messenger):
        """An exception inside send_message should be reported as error."""
        fake_messenger.send_message.side_effect = RuntimeError("kaboom")
        tool = registered.tools["send_repository_message"]
        result = await tool(
            sender_repo="a",
            receiver_repo="b",
            message_type="workflow_status_update",
            content={},
        )
        assert result["status"] == "error"
        assert "kaboom" in result["error"]


# =============================================================================
# broadcast_repository_message
# =============================================================================


class TestBroadcastMessage:
    """broadcast_repository_message forwards to messenger.broadcast_message."""

    @pytest.mark.asyncio
    async def test_success(self, registered, fake_messenger, fake_app):
        """Broadcast should call broadcast_message and return message ids."""
        msgs = [_make_message(msg_id="m1"), _make_message(msg_id="m2")]
        fake_messenger.broadcast_message.return_value = msgs

        tool = registered.tools["broadcast_repository_message"]
        result = await tool(
            sender_repo="a",
            message_type="workflow_status_update",
            content={"k": "v"},
            target_repos=["repo-a", "repo-b"],
        )
        assert result["status"] == "success"
        assert result["messages_sent"] == 2
        assert result["message_ids"] == ["m1", "m2"]
        assert result["target_repos"] == ["repo-a", "repo-b"]

    @pytest.mark.asyncio
    async def test_broadcast_invalid_type(self, registered):
        """Invalid type returns error dict."""
        tool = registered.tools["broadcast_repository_message"]
        result = await tool(
            sender_repo="a",
            message_type="bogus_type",
            content={},
        )
        assert result["status"] == "error"
        assert "Invalid message type" in result["error"]

    @pytest.mark.asyncio
    async def test_broadcast_invalid_priority(self, registered):
        """Invalid priority returns error dict."""
        tool = registered.tools["broadcast_repository_message"]
        result = await tool(
            sender_repo="a",
            message_type="workflow_status_update",
            content={},
            priority="nope",
        )
        assert result["status"] == "error"


# =============================================================================
# get_repository_messages
# =============================================================================


class TestGetMessages:
    """get_repository_messages fetches via messenger.get_messages_for_repo."""

    @pytest.mark.asyncio
    async def test_success(self, registered, fake_messenger):
        """Get messages should serialize each RepositoryMessage."""
        msg = _make_message()
        fake_messenger.get_messages_for_repo.return_value = [msg]

        tool = registered.tools["get_repository_messages"]
        result = await tool(receiver_repo="repo-b")

        assert result["status"] == "success"
        assert result["count"] == 1
        assert result["messages"][0]["id"] == "msg-1"
        assert result["messages"][0]["sender_repo"] == "repo-a"

    @pytest.mark.asyncio
    async def test_invalid_message_type(self, registered):
        """Invalid message_type returns error dict."""
        tool = registered.tools["get_repository_messages"]
        result = await tool(receiver_repo="repo-b", message_type="bogus")
        assert result["status"] == "error"
        assert "Invalid message type" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_since(self, registered):
        """Invalid 'since' timestamp returns error dict."""
        tool = registered.tools["get_repository_messages"]
        result = await tool(receiver_repo="repo-b", since="not-a-date")
        assert result["status"] == "error"
        assert "Invalid datetime" in result["error"]

    @pytest.mark.asyncio
    async def test_since_accepts_iso_with_z(self, registered, fake_messenger):
        """'since' should accept an ISO string with 'Z' suffix."""
        fake_messenger.get_messages_for_repo.return_value = []
        tool = registered.tools["get_repository_messages"]
        result = await tool(receiver_repo="repo-b", since="2024-01-01T00:00:00Z")
        assert result["status"] == "success"
        # The parsed datetime should have been passed (source uses kwarg name `since`)
        call_kwargs = fake_messenger.get_messages_for_repo.await_args.kwargs
        assert call_kwargs.get("since") is not None
        assert isinstance(call_kwargs["since"], datetime)

    @pytest.mark.asyncio
    async def test_exception_caught(self, registered, fake_messenger):
        """An exception should be caught and returned as error."""
        fake_messenger.get_messages_for_repo.side_effect = RuntimeError("db down")
        tool = registered.tools["get_repository_messages"]
        result = await tool(receiver_repo="repo-b")
        assert result["status"] == "error"


# =============================================================================
# acknowledge_repository_message
# =============================================================================


class TestAcknowledgeMessage:
    """acknowledge_repository_message calls messenger.acknowledge_message."""

    @pytest.mark.asyncio
    async def test_success(self, registered, fake_messenger):
        """Acknowledge should report success when underlying returns True."""
        fake_messenger.acknowledge_message.return_value = True
        tool = registered.tools["acknowledge_repository_message"]
        result = await tool(message_id="m1", receiver_repo="repo-b")
        assert result["status"] == "success"
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_returns_error_when_unack(self, registered, fake_messenger):
        """When acknowledge returns False, status should be 'error'."""
        fake_messenger.acknowledge_message.return_value = False
        tool = registered.tools["acknowledge_repository_message"]
        result = await tool(message_id="m1", receiver_repo="repo-b")
        assert result["status"] == "error"
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_exception_caught(self, registered, fake_messenger):
        """An exception should be reported as error."""
        fake_messenger.acknowledge_message.side_effect = RuntimeError("boom")
        tool = registered.tools["acknowledge_repository_message"]
        result = await tool(message_id="m1", receiver_repo="repo-b")
        assert result["status"] == "error"


# =============================================================================
# notify_repository_changes / notify_workflow_status / send_quality_alert
# =============================================================================


class TestNotifyAndAlert:
    """notify_repository_changes, notify_workflow_status, send_quality_alert."""

    @pytest.mark.asyncio
    async def test_notify_repository_changes(self, registered, fake_manager):
        """notify_repository_changes should call the manager and forward results."""
        tool = registered.tools["notify_repository_changes"]
        result = await tool(repo_path="/x", changes=[{"type": "modified"}])
        assert result["status"] == "success"
        assert result["messages_sent"] == 2
        assert result["changes_notified"] == 3
        fake_manager.process_repository_changes.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_notify_repository_changes_error(self, registered, fake_manager):
        """An exception should be reported as error."""
        fake_manager.process_repository_changes.side_effect = RuntimeError("nope")
        tool = registered.tools["notify_repository_changes"]
        result = await tool(repo_path="/x", changes=[])
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_notify_workflow_status(self, registered, fake_manager):
        """notify_workflow_status should pass through to manager."""
        tool = registered.tools["notify_workflow_status"]
        result = await tool(
            workflow_id="w1",
            status="running",
            repo_path="/x",
            target_repos=["repo-a"],
        )
        assert result["status"] == "success"
        assert result["messages_sent"] == 1
        assert result["workflow_id"] == "w1"

    @pytest.mark.asyncio
    async def test_notify_workflow_status_error(self, registered, fake_manager):
        """An exception should be reported as error."""
        fake_manager.notify_workflow_status.side_effect = RuntimeError("nope")
        tool = registered.tools["notify_workflow_status"]
        result = await tool(workflow_id="w1", status="running", repo_path="/x")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_send_quality_alert(self, registered, fake_manager):
        """send_quality_alert should pass through to manager."""
        tool = registered.tools["send_quality_alert"]
        result = await tool(
            repo_path="/x",
            alert_type="coverage_drop",
            description="coverage dropped",
            severity="high",
        )
        assert result["status"] == "success"
        assert result["alert_type"] == "coverage_drop"
        assert result["severity"] == "high"

    @pytest.mark.asyncio
    async def test_send_quality_alert_error(self, registered, fake_manager):
        """An exception should be reported as error."""
        fake_manager.send_quality_alert.side_effect = RuntimeError("nope")
        tool = registered.tools["send_quality_alert"]
        result = await tool(repo_path="/x", alert_type="x", description="y")
        assert result["status"] == "error"


# =============================================================================
# Coercion helpers
# =============================================================================


class TestCoercionHelpers:
    """The _coerce_message_type / _coerce_priority helpers."""

    def test_coerce_message_type(self):
        """_coerce_message_type should lowercase and convert."""
        assert (
            rmt._coerce_message_type("WORKFLOW_STATUS_UPDATE") == MessageType.WORKFLOW_STATUS_UPDATE
        )
        assert rmt._coerce_message_type("custom") == MessageType.CUSTOM

    def test_coerce_priority(self):
        """_coerce_priority should lowercase and convert."""
        assert rmt._coerce_priority("NORMAL") == MessagePriority.NORMAL
        assert rmt._coerce_priority("high") == MessagePriority.HIGH
