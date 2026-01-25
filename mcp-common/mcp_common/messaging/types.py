"""Shared messaging types for Session Buddy and Mahavishnu"""
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel


class Priority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class MessageType(str, Enum):
    REPOSITORY = "repository"
    PROJECT = "project"
    WORKFLOW = "workflow"
    ALERT = "alert"


class MessageStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class MessageContent(BaseModel):
    type: MessageType
    title: str
    content: str
    metadata: Optional[Dict[str, Any]] = None


class ForwardedFrom(BaseModel):
    project: str
    timestamp: float
    original_id: str


class RepositoryMessage(BaseModel):
    repo_id: str
    message: MessageContent
    priority: Priority = Priority.NORMAL
    forwarded_from: Optional[ForwardedFrom] = None


class ProjectMessage(BaseModel):
    project_id: str
    message: MessageContent
    priority: Priority = Priority.NORMAL
    forwarded_from: Optional[ForwardedFrom] = None