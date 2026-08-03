"""
Cross-repository coordination and tracking system.

This module provides data models and management for coordinating work across
multiple repositories in the Mahavishnu ecosystem.
"""

from mahavishnu.core.coordination.executor import CoordinationExecutor
from mahavishnu.core.coordination.manager import CoordinationManager
from mahavishnu.core.coordination.memory import (
    CoordinationManagerWithMemory,
    CoordinationMemory,
)
from mahavishnu.core.coordination.models import (
    CrossRepoIssue,
    CrossRepoPlan,
    CrossRepoTodo,
    Dependency,
    DependencyStatus,
    DependencyType,
    IssueStatus,
    Milestone,
    PlanStatus,
    Priority,
    TodoStatus,
)

__all__ = [
    # Executor
    "CoordinationExecutor",
    # Manager
    "CoordinationManager",
    "CoordinationManagerWithMemory",
    # Memory
    "CoordinationMemory",
    # Models
    "CrossRepoIssue",
    "CrossRepoPlan",
    "CrossRepoTodo",
    "Dependency",
    "DependencyStatus",
    "DependencyType",
    "IssueStatus",
    "Milestone",
    "PlanStatus",
    "Priority",
    "TodoStatus",
]
