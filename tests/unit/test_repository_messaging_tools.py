"""Unit tests for mahavishnu.mcp.tools.repository_messaging_tools.

Exercises the 7 MCP tools registered by `register_repository_messaging_tools`
plus the internal `_coerce_message_type` / `_coerce_priority` helpers.

Note: `register_repository_messaging_tools` instantiates the
`RepositoryMessengerManager` once at registration time and captures it
in a closure. Each test therefore has to (re)register the tools with a
freshly-mocked manager — the manager cannot be patched after the fact.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.mcp.tools import repository_messaging_tools as rmt
from mahavishnu.messaging.repository_messenger import (
    MessagePriority,
    MessageType,
    RepositoryMessage,
)

# =============================================================================
# Fixtures and helpers
# =============================================================================


def _make_message(
    message_id: str = "msg_abc",
    sender: str = "repo_a",
    receiver: str = "repo_b",
    message_type: MessageType = MessageType.CODE_CHANGE_NOTIFICATION,
    content: dict[str, Any] | None = None,
    priority: MessagePriority = MessagePriority.NORMAL,
    correlation_id: str = "corr_xyz",
) -> RepositoryMessage:
    """Build a RepositoryMessage with deterministic fields."""
    return RepositoryMessage(
        id=message_id,
        sender_repo=sender,
        receiver_repo=receiver,
        message_type=message_type,
        content=content or {"k": "v"},
        priority=priority,
        timestamp=datetime(2026, 6, 1, 12, 0, 0),
        correlation_id=correlation_id,
    )


def _build_manager(
    messenger: MagicMock | None = None,
    *,
    process_changes_return: dict[str, Any] | None = None,
    process_changes_side_effect: BaseException | None = None,
    notify_status_return: dict[str, Any] | None = None,
    notify_status_side_effect: BaseException | None = None,
    quality_alert_return: dict[str, Any] | None = None,
    quality_alert_side_effect: BaseException | None = None,
) -> MagicMock:
    """Build a mock `RepositoryMessengerManager` with given overrides."""
    manager = MagicMock()
    manager.messenger = messenger or MagicMock()

    if process_changes_side_effect is not None:
        manager.process_repository_changes = AsyncMock(side_effect=process_changes_side_effect)
    else:
        manager.process_repository_changes = AsyncMock(
            return_value=process_changes_return
            or {"status": "success", "messages_sent": 3, "changes_notified": 3}
        )

    if notify_status_side_effect is not None:
        manager.notify_workflow_status = AsyncMock(side_effect=notify_status_side_effect)
    else:
        manager.notify_workflow_status = AsyncMock(
            return_value=notify_status_return
            or {"status": "success", "messages_sent": 2, "workflow_id": "wf_1"}
        )

    if quality_alert_side_effect is not None:
        manager.send_quality_alert = AsyncMock(side_effect=quality_alert_side_effect)
    else:
        manager.send_quality_alert = AsyncMock(
            return_value=quality_alert_return
            or {
                "status": "success",
                "messages_sent": 1,
                "alert_type": "lint",
                "severity": "high",
            }
        )
    return manager


@contextmanager
def _registered_tools(manager: MagicMock | None = None):
    """Yield a dict of registered tools built around the given manager.

    Patches `RepositoryMessengerManager` so the closure inside
    `register_repository_messaging_tools` picks up our mock.
    """
    captured: dict[str, Any] = {}
    server = MagicMock()

    def _decorator_factory():
        def _decorator(fn):
            captured[fn.__name__] = fn
            return fn

        return _decorator

    server.tool = MagicMock(side_effect=_decorator_factory)

    app = MagicMock()
    app.get_repos = MagicMock(return_value=["repo_x", "repo_y"])
    mcp_client = MagicMock()

    patch_target = "mahavishnu.mcp.tools.repository_messaging_tools.RepositoryMessengerManager"
    with patch(patch_target, return_value=manager or _build_manager()):
        rmt.register_repository_messaging_tools(server, app, mcp_client)

    yield captured


# =============================================================================
# Helpers: _coerce_message_type / _coerce_priority
# =============================================================================


@pytest.mark.unit
class TestCoercionHelpers:
    """Direct unit tests for the small enum-normalisation helpers."""

    def test_coerce_message_type_lowercases(self) -> None:
        """`_coerce_message_type` should accept uppercase input."""
        assert (
            rmt._coerce_message_type("CODE_CHANGE_NOTIFICATION")
            == MessageType.CODE_CHANGE_NOTIFICATION
        )

    def test_coerce_message_type_mixed_case(self) -> None:
        """`_coerce_message_type` should accept mixed case input."""
        assert (
            rmt._coerce_message_type("Code_Change_Notification")
            == MessageType.CODE_CHANGE_NOTIFICATION
        )

    def test_coerce_message_type_invalid_raises(self) -> None:
        """`_coerce_message_type` should raise ValueError on unknown values."""
        with pytest.raises(ValueError):
            rmt._coerce_message_type("nope")

    def test_coerce_priority_lowercases(self) -> None:
        """`_coerce_priority` should accept uppercase input."""
        assert rmt._coerce_priority("HIGH") == MessagePriority.HIGH

    def test_coerce_priority_invalid_raises(self) -> None:
        """`_coerce_priority` should raise ValueError on unknown values."""
        with pytest.raises(ValueError):
            rmt._coerce_priority("urgent")


# =============================================================================
# send_repository_message
# =============================================================================


@pytest.mark.unit
class TestSendRepositoryMessage:
    """Tests for the `send_repository_message` MCP tool."""

    async def test_send_success(self) -> None:
        """A well-formed call returns success with message id and timestamp."""
        messenger = MagicMock()
        messenger.send_message = AsyncMock(return_value=_make_message())
        manager = _build_manager(messenger)

        with _registered_tools(manager) as tools:
            result = await tools["send_repository_message"](
                sender_repo="repo_a",
                receiver_repo="repo_b",
                message_type="code_change_notification",
                content={"k": "v"},
                priority="normal",
            )

        assert result["status"] == "success"
        assert result["message_id"] == "msg_abc"
        assert result["sent_at"] == "2026-06-01T12:00:00"
        assert result["priority"] == "normal"
        messenger.send_message.assert_awaited_once()

    async def test_send_invalid_message_type(self) -> None:
        """An unknown message_type returns an error dict, not a raise."""
        with _registered_tools() as tools:
            result = await tools["send_repository_message"](
                sender_repo="repo_a",
                receiver_repo="repo_b",
                message_type="not_a_real_type",
                content={},
            )
        assert result["status"] == "error"
        assert "Invalid message type" in result["error"]

    async def test_send_invalid_priority(self) -> None:
        """An unknown priority returns an error dict, not a raise."""
        with _registered_tools() as tools:
            result = await tools["send_repository_message"](
                sender_repo="repo_a",
                receiver_repo="repo_b",
                message_type="code_change_notification",
                content={},
                priority="urgent",
            )
        assert result["status"] == "error"
        assert "Invalid priority" in result["error"]

    async def test_send_messenger_failure(self) -> None:
        """If the messenger raises, the tool returns a caught error dict."""
        messenger = MagicMock()
        messenger.send_message = AsyncMock(side_effect=RuntimeError("boom"))
        manager = _build_manager(messenger)

        with _registered_tools(manager) as tools:
            result = await tools["send_repository_message"](
                sender_repo="repo_a",
                receiver_repo="repo_b",
                message_type="code_change_notification",
                content={},
            )
        assert result["status"] == "error"
        assert "Failed to send" in result["error"]


# =============================================================================
# broadcast_repository_message
# =============================================================================


@pytest.mark.unit
class TestBroadcastRepositoryMessage:
    """Tests for the `broadcast_repository_message` MCP tool."""

    async def test_broadcast_with_explicit_targets(self) -> None:
        """With explicit target_repos, should call messenger.broadcast_message."""
        messenger = MagicMock()
        messenger.broadcast_message = AsyncMock(
            return_value=[
                _make_message(receiver="repo_x"),
                _make_message(receiver="repo_y"),
            ]
        )
        manager = _build_manager(messenger)

        with _registered_tools(manager) as tools:
            result = await tools["broadcast_repository_message"](
                sender_repo="repo_a",
                message_type="quality_alert",
                content={"k": "v"},
                target_repos=["repo_x", "repo_y"],
                priority="high",
            )

        assert result["status"] == "success"
        assert result["messages_sent"] == 2
        assert result["target_repos"] == ["repo_x", "repo_y"]

    async def test_broadcast_without_targets_uses_app_repos(self) -> None:
        """Without target_repos, broadcast should fall back to app.get_repos()."""
        messenger = MagicMock()
        messenger.broadcast_message = AsyncMock(return_value=[_make_message()])
        manager = _build_manager(messenger)

        with _registered_tools(manager) as tools:
            result = await tools["broadcast_repository_message"](
                sender_repo="repo_a",
                message_type="quality_alert",
                content={},
            )

        assert result["status"] == "success"
        # target_repos should default to whatever app.get_repos() returned at registration
        assert result["target_repos"] == ["repo_x", "repo_y"]

    async def test_broadcast_invalid_message_type(self) -> None:
        """Invalid message_type returns an error dict."""
        with _registered_tools() as tools:
            result = await tools["broadcast_repository_message"](
                sender_repo="repo_a",
                message_type="nope",
                content={},
            )
        assert result["status"] == "error"
        assert "Invalid message type" in result["error"]

    async def test_broadcast_invalid_priority(self) -> None:
        """Invalid priority returns an error dict."""
        with _registered_tools() as tools:
            result = await tools["broadcast_repository_message"](
                sender_repo="repo_a",
                message_type="quality_alert",
                content={},
                priority="urgent",
            )
        assert result["status"] == "error"
        assert "Invalid priority" in result["error"]

    async def test_broadcast_messenger_failure(self) -> None:
        """Messenger failure should be caught and reported."""
        messenger = MagicMock()
        messenger.broadcast_message = AsyncMock(side_effect=RuntimeError("net down"))
        manager = _build_manager(messenger)

        with _registered_tools(manager) as tools:
            result = await tools["broadcast_repository_message"](
                sender_repo="repo_a",
                message_type="quality_alert",
                content={},
            )
        assert result["status"] == "error"
        assert "Failed to broadcast" in result["error"]


# =============================================================================
# get_repository_messages
# =============================================================================


@pytest.mark.unit
class TestGetRepositoryMessages:
    """Tests for the `get_repository_messages` MCP tool."""

    async def test_get_messages_default(self) -> None:
        """Default call should return messages and count."""
        messenger = MagicMock()
        messenger.get_messages_for_repo = AsyncMock(
            return_value=[
                _make_message(receiver="repo_b"),
                _make_message(receiver="repo_b", message_id="msg_2"),
            ]
        )
        manager = _build_manager(messenger)

        with _registered_tools(manager) as tools:
            result = await tools["get_repository_messages"](receiver_repo="repo_b")

        assert result["status"] == "success"
        assert result["count"] == 2
        assert len(result["messages"]) == 2
        assert result["messages"][0]["id"] == "msg_abc"
        assert result["messages"][0]["priority"] == "normal"
        assert result["messages"][0]["timestamp"] == "2026-06-01T12:00:00"
        assert result["messages"][0]["correlation_id"] == "corr_xyz"

    async def test_get_messages_with_filters(self) -> None:
        """Passing message_type and since should forward them to messenger."""
        messenger = MagicMock()
        messenger.get_messages_for_repo = AsyncMock(return_value=[])
        manager = _build_manager(messenger)

        with _registered_tools(manager) as tools:
            result = await tools["get_repository_messages"](
                receiver_repo="repo_b",
                message_type="workflow_status_update",
                limit=10,
                since="2026-01-01T00:00:00Z",
            )
        assert result["status"] == "success"
        assert result["count"] == 0

        # Verify the since_dt was parsed and forwarded
        call = messenger.get_messages_for_repo.await_args
        assert call is not None
        assert call.kwargs["repo_name"] == "repo_b"
        assert call.kwargs["message_type"] == MessageType.WORKFLOW_STATUS_UPDATE
        assert call.kwargs["limit"] == 10

        assert call.kwargs["since"] == datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

    async def test_get_messages_invalid_message_type(self) -> None:
        """Invalid message_type returns an error dict."""
        with _registered_tools() as tools:
            result = await tools["get_repository_messages"](
                receiver_repo="repo_b", message_type="not_real"
            )
        assert result["status"] == "error"
        assert "Invalid message type" in result["error"]

    async def test_get_messages_invalid_since(self) -> None:
        """Invalid `since` datetime returns an error dict."""
        with _registered_tools() as tools:
            result = await tools["get_repository_messages"](
                receiver_repo="repo_b", since="not-a-date"
            )
        assert result["status"] == "error"
        assert "Invalid datetime" in result["error"]

    async def test_get_messages_messenger_failure(self) -> None:
        """Messenger failure should be caught and reported."""
        messenger = MagicMock()
        messenger.get_messages_for_repo = AsyncMock(side_effect=RuntimeError("db down"))
        manager = _build_manager(messenger)

        with _registered_tools(manager) as tools:
            result = await tools["get_repository_messages"](receiver_repo="repo_b")
        assert result["status"] == "error"
        assert "Failed to get" in result["error"]


# =============================================================================
# acknowledge_repository_message
# =============================================================================


@pytest.mark.unit
class TestAcknowledgeRepositoryMessage:
    """Tests for the `acknowledge_repository_message` MCP tool."""

    async def test_acknowledge_success(self) -> None:
        """Successful acknowledge returns success with the message id."""
        messenger = MagicMock()
        messenger.acknowledge_message = AsyncMock(return_value=True)
        manager = _build_manager(messenger)

        with _registered_tools(manager) as tools:
            result = await tools["acknowledge_repository_message"](
                message_id="msg_abc", receiver_repo="repo_b"
            )
        assert result["status"] == "success"
        assert result["success"] is True
        assert result["message_id"] == "msg_abc"
        assert result["acknowledged_by"] == "repo_b"

    async def test_acknowledge_returns_false(self) -> None:
        """When the messenger returns False, status should reflect error."""
        messenger = MagicMock()
        messenger.acknowledge_message = AsyncMock(return_value=False)
        manager = _build_manager(messenger)

        with _registered_tools(manager) as tools:
            result = await tools["acknowledge_repository_message"](
                message_id="msg_abc", receiver_repo="repo_b"
            )
        assert result["status"] == "error"
        assert result["success"] is False

    async def test_acknowledge_messenger_failure(self) -> None:
        """Messenger failure should be caught and reported."""
        messenger = MagicMock()
        messenger.acknowledge_message = AsyncMock(side_effect=RuntimeError("net err"))
        manager = _build_manager(messenger)

        with _registered_tools(manager) as tools:
            result = await tools["acknowledge_repository_message"](
                message_id="msg_abc", receiver_repo="repo_b"
            )
        assert result["status"] == "error"
        assert "Failed to acknowledge" in result["error"]


# =============================================================================
# notify_repository_changes
# =============================================================================


@pytest.mark.unit
class TestNotifyRepositoryChanges:
    """Tests for the `notify_repository_changes` MCP tool."""

    async def test_notify_changes_success(self) -> None:
        """Successful call forwards to manager.process_repository_changes."""
        manager = _build_manager(
            process_changes_return={
                "status": "success",
                "messages_sent": 5,
                "changes_notified": 5,
            }
        )

        with _registered_tools(manager) as tools:
            result = await tools["notify_repository_changes"](
                repo_path="/path/to/repo",
                changes=[{"type": "added"}, {"type": "modified"}],
            )
        assert result["status"] == "success"
        assert result["messages_sent"] == 5
        assert result["changes_notified"] == 5

    async def test_notify_changes_manager_error_status(self) -> None:
        """When the manager returns an error status, it should be propagated."""
        manager = _build_manager(process_changes_return={"status": "error", "error": "no repos"})

        with _registered_tools(manager) as tools:
            result = await tools["notify_repository_changes"](repo_path="/path/to/repo", changes=[])
        assert result["status"] == "error"

    async def test_notify_changes_manager_raises(self) -> None:
        """If the manager raises, the tool should return an error dict."""
        manager = _build_manager(process_changes_side_effect=RuntimeError("oops"))

        with _registered_tools(manager) as tools:
            result = await tools["notify_repository_changes"](repo_path="/path/to/repo", changes=[])
        assert result["status"] == "error"
        assert "Failed to notify" in result["error"]


# =============================================================================
# notify_workflow_status
# =============================================================================


@pytest.mark.unit
class TestNotifyWorkflowStatus:
    """Tests for the `notify_workflow_status` MCP tool."""

    async def test_notify_status_success(self) -> None:
        """Successful call returns the status from the manager."""
        manager = _build_manager(
            notify_status_return={
                "status": "success",
                "messages_sent": 4,
                "workflow_id": "wf_1",
            }
        )

        with _registered_tools(manager) as tools:
            result = await tools["notify_workflow_status"](
                workflow_id="wf_1",
                status="completed",
                repo_path="/path/to/repo",
                target_repos=["repo_x", "repo_y"],
            )
        assert result["status"] == "success"
        assert result["messages_sent"] == 4
        assert result["workflow_id"] == "wf_1"

    async def test_notify_status_manager_raises(self) -> None:
        """Manager failure should be caught and reported."""
        manager = _build_manager(notify_status_side_effect=RuntimeError("err"))

        with _registered_tools(manager) as tools:
            result = await tools["notify_workflow_status"](
                workflow_id="wf_1",
                status="failed",
                repo_path="/path/to/repo",
            )
        assert result["status"] == "error"
        assert "Failed to notify" in result["error"]


# =============================================================================
# send_quality_alert
# =============================================================================


@pytest.mark.unit
class TestSendQualityAlert:
    """Tests for the `send_quality_alert` MCP tool."""

    async def test_send_alert_success(self) -> None:
        """Successful call returns the manager's status dict."""
        manager = _build_manager(
            quality_alert_return={
                "status": "success",
                "messages_sent": 3,
                "alert_type": "lint",
                "severity": "high",
            }
        )

        with _registered_tools(manager) as tools:
            result = await tools["send_quality_alert"](
                repo_path="/path/to/repo",
                alert_type="lint",
                description="100 lint errors",
                severity="high",
            )
        assert result["status"] == "success"
        assert result["alert_type"] == "lint"
        assert result["severity"] == "high"

    async def test_send_alert_default_severity(self) -> None:
        """Severity should default to 'medium' when not provided."""
        manager = _build_manager(
            quality_alert_return={
                "status": "success",
                "messages_sent": 1,
                "alert_type": "lint",
                "severity": "medium",
            }
        )

        with _registered_tools(manager) as tools:
            result = await tools["send_quality_alert"](
                repo_path="/path/to/repo",
                alert_type="lint",
                description="issue",
            )
        assert result["status"] == "success"
        assert result["severity"] == "medium"

    async def test_send_alert_manager_raises(self) -> None:
        """Manager failure should be caught and reported."""
        manager = _build_manager(quality_alert_side_effect=RuntimeError("err"))

        with _registered_tools(manager) as tools:
            result = await tools["send_quality_alert"](
                repo_path="/path/to/repo",
                alert_type="lint",
                description="x",
            )
        assert result["status"] == "error"
        assert "Failed to send" in result["error"]


# =============================================================================
# Registration smoke test
# =============================================================================


@pytest.mark.unit
class TestRegistration:
    """Smoke tests for the registration entry-point."""

    def test_registration_attaches_seven_tools(self) -> None:
        """`register_repository_messaging_tools` should register 7 tools."""
        with _registered_tools() as tools:
            assert len(tools) == 7
            assert set(tools.keys()) == {
                "send_repository_message",
                "broadcast_repository_message",
                "get_repository_messages",
                "acknowledge_repository_message",
                "notify_repository_changes",
                "notify_workflow_status",
                "send_quality_alert",
            }

    def test_registration_uses_provided_app(self) -> None:
        """The registered messenger manager should be built with the given app."""
        server = MagicMock()
        app = MagicMock()
        app.get_repos = MagicMock(return_value=["r"])
        mcp_client = MagicMock()
        manager_cls_calls: list[Any] = []
        fake_manager = _build_manager()

        server.tool = MagicMock(side_effect=lambda: lambda fn: fn)

        def _capture_manager(*args, **kwargs):
            manager_cls_calls.append((args, kwargs))
            return fake_manager

        with patch(
            "mahavishnu.mcp.tools.repository_messaging_tools.RepositoryMessengerManager",
            side_effect=_capture_manager,
        ):
            rmt.register_repository_messaging_tools(server, app, mcp_client)

        assert manager_cls_calls, "RepositoryMessengerManager was not instantiated"
        assert manager_cls_calls[0][0] == (app,)
