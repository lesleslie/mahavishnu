"""Shared messaging types used by Session-Buddy and Mahavishnu.

This module provides a compatibility layer for code that expects the
historical ``messaging.types`` import path from the shared ``mcp-common``
package.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class Priority(str, Enum):
    """Message priority levels."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class MessageType(str, Enum):
    """Message types used for inter-project communication."""

    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"
    UPDATE = "update"


class MessageStatus(str, Enum):
    """Message lifecycle states."""

    UNREAD = "unread"
    READ = "read"
    ARCHIVED = "archived"


class MessageContent(BaseModel):
    """Generic message content wrapper."""

    title: str | None = None
    body: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectMessage(BaseModel):
    """Compatibility model for project-to-project messages."""

    id: str = Field(default_factory=lambda: f"msg_{uuid4().hex}")
    project_id: str
    message: dict[str, Any]
    priority: Priority = Priority.NORMAL
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class RepositoryMessage(BaseModel):
    """Compatibility model for repository-to-repository messages."""

    id: str = Field(default_factory=lambda: f"msg_{uuid4().hex}")
    sender_repo: str
    receiver_repo: str
    message_type: MessageType = MessageType.NOTIFICATION
    content: dict[str, Any]
    priority: Priority = Priority.NORMAL
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


MessagePriority = Priority
