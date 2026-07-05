"""Regression tests for messaging compatibility and enum normalization."""

from __future__ import annotations

from messaging.types import MessageStatus, MessageType, Priority, ProjectMessage

from mahavishnu.mcp.tools.repository_messaging_tools import (
    _coerce_message_type as coerce_repository_message_type,
)
from mahavishnu.mcp.tools.repository_messaging_tools import (
    _coerce_priority as coerce_repository_priority,
)
from mahavishnu.mcp.tools.session_buddy_tools import _coerce_priority as coerce_session_priority
from mahavishnu.messaging.repository_messenger import (
    MessagePriority as RepositoryMessagePriority,
)
from mahavishnu.messaging.repository_messenger import (
    MessageType as RepositoryMessageType,
)


def test_messaging_types_module_exports_shared_enums() -> None:
    """The shared messaging.types module should expose Priority and MessageType."""
    assert Priority.NORMAL.value == "normal"
    # Cross-module value consistency: the local repository MessagePriority and
    # the shared messaging.types.Priority must agree on value strings.
    assert RepositoryMessagePriority.NORMAL.value == Priority.NORMAL.value
    assert MessageType.REQUEST.value == "request"


def test_project_message_constructible() -> None:
    """ProjectMessage should be constructible with the fields the integration uses."""
    message = ProjectMessage(
        id="msg-1",
        from_project="session_buddy",
        to_project="crackerjack",
        timestamp="2025-01-24T10:30:00Z",
        subject="test",
        priority=Priority.NORMAL,
        status=MessageStatus.UNREAD,
        content_type=MessageType.NOTIFICATION,
        content_message="test content",
    )

    assert message.from_project == "session_buddy"
    assert message.content_message == "test content"
    assert message.priority == Priority.NORMAL


def test_repository_messaging_helpers_accept_case_insensitive_values() -> None:
    """Repository messaging tool helpers should normalize enum values defensively."""
    assert (
        coerce_repository_message_type("WORKFLOW_STATUS_UPDATE")
        == RepositoryMessageType.WORKFLOW_STATUS_UPDATE
    )
    assert coerce_repository_priority("NORMAL") == RepositoryMessagePriority.NORMAL


def test_session_buddy_helpers_accept_case_insensitive_values() -> None:
    """Session-Buddy messaging helpers should normalize enum values defensively.

    The session-buddy helper returns mahavishnu.messaging.MessagePriority
    (re-exported from repository_messenger), not messaging.types.Priority --
    so we assert against the local type.
    """
    assert coerce_session_priority("NORMAL") == RepositoryMessagePriority.NORMAL
