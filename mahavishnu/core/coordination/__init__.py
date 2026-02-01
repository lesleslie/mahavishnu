"""
Cross-repository coordination and tracking system.

This module provides data models and management for coordinating work across
multiple repositories in the Mahavishnu ecosystem.
"""

from mahavishnu.core.coordination.models import (
    CrossRepoIssue,
    CrossRepoPlan,
    CrossRepoTodo,
    Dependency,
    Milestone,
    IssueStatus,
    Priority,
    PlanStatus,
    TodoStatus,
    DependencyType,
    DependencyStatus,
)

from mahavishnu.core.coordination.manager import CoordinationManager

from mahavishnu.core.coordination.memory import (
    CoordinationMemory,
    CoordinationManagerWithMemory,
)

from mahavishnu.core.coordination.executor import CoordinationExecutor

__all__ = [
    # Models
    "CrossRepoIssue",
    "CrossRepoPlan",
    "CrossRepoTodo",
    "Dependency",
    "Milestone",
    "IssueStatus",
    "Priority",
    "PlanStatus",
    "TodoStatus",
    "DependencyType",
    "DependencyStatus",
    # Manager
    "CoordinationManager",
    # Memory
    "CoordinationMemory",
    "CoordinationManagerWithMemory",
    # Executor
    "CoordinationExecutor",
]
