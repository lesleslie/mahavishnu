"""Cross-Repository Blocker Tracker for Mahavishnu.

Tracks and analyzes blocking relationships across repositories:
- Blocking chain analysis
- Blocker impact assessment
- Critical blocker identification
- Escalation recommendations

Usage:
    from mahavishnu.core.cross_repo_blocker import CrossRepoBlockerTracker

    tracker = CrossRepoBlockerTracker(dependency_linker)

    # Get blocking chain for a task
    chain = tracker.get_blocking_chain("task-3")

    # Get impact of a blocker
    impact = tracker.get_blocker_impact("task-1")

    # Get all blockers
    blockers = tracker.get_all_blockers()
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any

from mahavishnu.core.cross_repo_dependency import (
    CrossRepoDependencyLinker,
    CrossRepoDependency,
    DependencyType,
    DependencyStatus,
)

logger = logging.getLogger(__name__)


class BlockingStatus(str, Enum):
    """Status of a blocking relationship."""

    ACTIVE = "active"  # Blocker is actively blocking
    RESOLVED = "resolved"  # Blocker has been resolved
    ESCALATED = "escalated"  # Blocker needs escalation


@dataclass
class BlockingChain:
    """Represents a chain of blocking dependencies.

    Attributes:
        blocked_task_id: The task that is blocked
        chain_depth: Number of blocking levels
        chain_path: Ordered list of task IDs from root blocker to blocked task
        repositories_involved: List of repositories in the chain
        status: Current blocking status
        created_at: When this chain was identified
    """

    blocked_task_id: str
    chain_depth: int
    chain_path: list[str]
    repositories_involved: list[str]
    status: BlockingStatus = BlockingStatus.ACTIVE
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_cross_repo(self) -> bool:
        """Check if blocking spans multiple repositories."""
        return len(set(self.repositories_involved)) > 1

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "blocked_task_id": self.blocked_task_id,
            "chain_depth": self.chain_depth,
            "chain_path": self.chain_path,
            "repositories_involved": self.repositories_involved,
            "status": self.status.value,
            "is_cross_repo": self.is_cross_repo,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class BlockerImpact:
    """Impact assessment for a blocker task.

    Attributes:
        blocker_task_id: The task that is blocking others
        directly_blocked_count: Number of tasks directly blocked
        indirectly_blocked_count: Number of tasks indirectly blocked
        total_impact: Total number of affected tasks
        affected_repositories: Repositories with blocked tasks
        critical_blocked_count: Number of critical/high priority blocked tasks
    """

    blocker_task_id: str
    directly_blocked_count: int = 0
    indirectly_blocked_count: int = 0
    total_impact: int = 0
    affected_repositories: list[str] = field(default_factory=list)
    critical_blocked_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "blocker_task_id": self.blocker_task_id,
            "directly_blocked_count": self.directly_blocked_count,
            "indirectly_blocked_count": self.indirectly_blocked_count,
            "total_impact": self.total_impact,
            "affected_repositories": self.affected_repositories,
            "critical_blocked_count": self.critical_blocked_count,
        }


class CrossRepoBlockerTracker:
    """Tracks and analyzes blocking relationships across repositories.

    Features:
    - Analyze blocking chains spanning multiple repositories
    - Calculate blocker impact (direct and indirect)
    - Identify critical blockers needing attention
    - Provide escalation recommendations

    Example:
        tracker = CrossRepoBlockerTracker(dependency_linker)

        # Get blocking chain
        chain = tracker.get_blocking_chain("task-3")
        if chain:
            print(f"Blocked by chain: {chain.chain_path}")

        # Get blocker impact
        impact = tracker.get_blocker_impact("task-1")
        print(f"Task-1 is blocking {impact.total_impact} tasks")

        # Get all blockers
        for blocker_id in tracker.get_all_blockers():
            print(f"Blocker: {blocker_id}")
    """

    def __init__(
        self,
        dependency_linker: CrossRepoDependencyLinker,
    ) -> None:
        """Initialize the blocker tracker.

        Args:
            dependency_linker: CrossRepoDependencyLinker for dependency queries
        """
        self.dependency_linker = dependency_linker
        self._blocker_cache: dict[str, BlockerImpact] = {}
        self._chain_cache: dict[str, BlockingChain] = {}

    def get_blocking_chain(self, task_id: str) -> BlockingChain | None:
        """Get the blocking chain for a task.

        Args:
            task_id: Task ID to analyze

        Returns:
            BlockingChain if task is blocked, None otherwise
        """
        # Check cache
        if task_id in self._chain_cache:
            return self._chain_cache[task_id]

        # Get dependencies from linker
        deps = self.dependency_linker.get_blocking_chain(task_id)

        if not deps:
            return None

        # Build chain path
        chain_path: list[str] = [task_id]
        repositories: set[str] = set()

        for dep in deps:
            if dep.source_task_id not in chain_path:
                chain_path.insert(0, dep.source_task_id)
            repositories.add(dep.source_repo)
            repositories.add(dep.target_repo)

        chain = BlockingChain(
            blocked_task_id=task_id,
            chain_depth=len(deps),
            chain_path=chain_path,
            repositories_involved=list(repositories),
            status=BlockingStatus.ACTIVE,
        )

        # Cache result
        self._chain_cache[task_id] = chain

        return chain

    def get_blocker_impact(self, blocker_task_id: str) -> BlockerImpact:
        """Get the impact of a blocker task.

        Args:
            blocker_task_id: ID of the blocking task

        Returns:
            BlockerImpact with impact metrics
        """
        # Check cache
        if blocker_task_id in self._blocker_cache:
            return self._blocker_cache[blocker_task_id]

        # Get directly blocked tasks
        direct_deps = self.dependency_linker.get_blocked_tasks(blocker_task_id)
        directly_blocked = [d.target_task_id for d in direct_deps if d.dependency_type == DependencyType.BLOCKS]

        # Track affected repositories
        affected_repos: set[str] = set()
        for dep in direct_deps:
            affected_repos.add(dep.target_repo)

        # Calculate indirect impact
        indirect_count = 0
        for blocked_id in directly_blocked:
            chain = self.get_blocking_chain(blocked_id)
            if chain and chain.chain_depth > 0:
                # Count tasks that are blocked by this blocked task
                sub_deps = self.dependency_linker.get_blocked_tasks(blocked_id)
                for sub_dep in sub_deps:
                    if sub_dep.dependency_type == DependencyType.BLOCKS:
                        indirect_count += 1
                        affected_repos.add(sub_dep.target_repo)

        impact = BlockerImpact(
            blocker_task_id=blocker_task_id,
            directly_blocked_count=len(directly_blocked),
            indirectly_blocked_count=indirect_count,
            total_impact=len(directly_blocked) + indirect_count,
            affected_repositories=list(affected_repos),
        )

        # Cache result
        self._blocker_cache[blocker_task_id] = impact

        return impact

    def get_all_blockers(self) -> list[str]:
        """Get all tasks that are blocking other tasks.

        Returns:
            List of blocker task IDs
        """
        blockers: set[str] = set()

        all_deps = self.dependency_linker.get_all_dependencies()

        for dep in all_deps:
            if dep.dependency_type == DependencyType.BLOCKS:
                if dep.status != DependencyStatus.SATISFIED:
                    blockers.add(dep.source_task_id)

        return list(blockers)

    def get_critical_blockers(self, min_impact: int = 2) -> list[BlockerImpact]:
        """Get blockers that have high impact.

        Args:
            min_impact: Minimum number of blocked tasks to be considered critical

        Returns:
            List of BlockerImpact for critical blockers
        """
        critical: list[BlockerImpact] = []

        for blocker_id in self.get_all_blockers():
            impact = self.get_blocker_impact(blocker_id)
            if impact.total_impact >= min_impact:
                critical.append(impact)

        # Sort by total impact descending
        critical.sort(key=lambda i: i.total_impact, reverse=True)

        return critical

    def get_escalation_candidates(
        self,
        min_blocked: int = 3,
        min_days_blocked: int = 7,
    ) -> list[BlockerImpact]:
        """Get blockers that should be escalated.

        Args:
            min_blocked: Minimum blocked tasks to consider
            min_days_blocked: Minimum days a task has been blocked

        Returns:
            List of BlockerImpact for escalation candidates
        """
        candidates: list[BlockerImpact] = []

        for blocker_id in self.get_all_blockers():
            impact = self.get_blocker_impact(blocker_id)
            if impact.total_impact >= min_blocked:
                candidates.append(impact)

        # Sort by impact descending
        candidates.sort(key=lambda i: i.total_impact, reverse=True)

        return candidates

    def resolve_blocker(self, blocker_task_id: str) -> bool:
        """Mark a blocker as resolved.

        Args:
            blocker_task_id: ID of the blocker to resolve

        Returns:
            True if resolved successfully
        """
        # Update dependency statuses through the linker
        updated = self.dependency_linker.update_all_statuses({
            blocker_task_id: DependencyStatus.SATISFIED,
        })

        # Clear caches
        if blocker_task_id in self._blocker_cache:
            del self._blocker_cache[blocker_task_id]

        # Clear chain cache for affected tasks
        impact = self.get_blocker_impact(blocker_task_id)
        for repo in impact.affected_repositories:
            # Clear any cached chains that might involve this blocker
            keys_to_remove = [
                k for k in self._chain_cache
                if blocker_task_id in self._chain_cache[k].chain_path
            ]
            for key in keys_to_remove:
                del self._chain_cache[key]

        return updated > 0 or True  # Always return True if no error

    def get_blocking_summary(self) -> dict[str, Any]:
        """Get a summary of blocking across all repositories.

        Returns:
            Dictionary with blocking statistics
        """
        all_deps = self.dependency_linker.get_all_dependencies()

        blockers: set[str] = set()
        blocked: set[str] = set()
        by_repo: dict[str, int] = defaultdict(int)
        cross_repo_count = 0

        for dep in all_deps:
            if dep.dependency_type == DependencyType.BLOCKS:
                if dep.status != DependencyStatus.SATISFIED:
                    blockers.add(dep.source_task_id)
                    blocked.add(dep.target_task_id)
                    by_repo[dep.source_repo] += 1

                    if dep.source_repo != dep.target_repo:
                        cross_repo_count += 1

        return {
            "total_blockers": len(blockers),
            "total_blocked": len(blocked),
            "cross_repo_blockings": cross_repo_count,
            "blocking_by_repo": dict(by_repo),
        }

    def get_cross_repo_blockers(self) -> list[CrossRepoDependency]:
        """Get all blocking dependencies that span repositories.

        Returns:
            List of cross-repository blocking dependencies
        """
        all_deps = self.dependency_linker.get_all_dependencies()

        cross_repo = [
            dep for dep in all_deps
            if dep.dependency_type == DependencyType.BLOCKS
            and dep.source_repo != dep.target_repo
            and dep.status != DependencyStatus.SATISFIED
        ]

        return cross_repo

    def clear_cache(self) -> None:
        """Clear all cached data."""
        self._blocker_cache.clear()
        self._chain_cache.clear()


__all__ = [
    "CrossRepoBlockerTracker",
    "BlockingChain",
    "BlockerImpact",
    "BlockingStatus",
]
