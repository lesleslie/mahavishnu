"""Regression tests for messaging compatibility and enum normalization."""

from __future__ import annotations

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
from messaging.types import MessagePriority, MessageType, Priority, ProjectMessage


def test_messaging_types_module_exports_shared_enums() -> None:
    """The compatibility package should expose the expected shared enums."""
    assert Priority.NORMAL.value == "normal"
    assert MessagePriority.NORMAL.value == "normal"
    assert MessageType.REQUEST.value == "request"


def test_project_message_defaults_are_usable() -> None:
    """ProjectMessage should be constructible with the fields the integration uses."""
    message = ProjectMessage(project_id="session_buddy", message={"type": "code_context"})

    assert message.project_id == "session_buddy"
    assert message.message == {"type": "code_context"}
    assert message.priority == Priority.NORMAL


def test_repository_messaging_helpers_accept_case_insensitive_values() -> None:
    """Repository messaging tool helpers should normalize enum values defensively."""
    assert (
        coerce_repository_message_type("WORKFLOW_STATUS_UPDATE")
        == RepositoryMessageType.WORKFLOW_STATUS_UPDATE
    )
    assert coerce_repository_priority("NORMAL") == RepositoryMessagePriority.NORMAL


def test_session_buddy_helpers_accept_case_insensitive_values() -> None:
    """Session-Buddy messaging helpers should normalize enum values defensively."""
    assert coerce_session_priority("NORMAL").value == MessagePriority.NORMAL.value
