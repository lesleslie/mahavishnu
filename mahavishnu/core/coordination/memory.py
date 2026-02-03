"""Memory integration for cross-repository coordination.

Stores coordination events in Session-Buddy for semantic search and analytics.
"""

from datetime import datetime
import logging
from typing import Any

from mahavishnu.core.coordination.models import (
    CrossRepoIssue,
    CrossRepoPlan,
    CrossRepoTodo,
    Dependency,
)

# Type hints for circular imports

logger = logging.getLogger(__name__)


class CoordinationMemory:
    """Store coordination events in memory systems.

    This class provides integration with Session-Buddy to store
    coordination events for semantic search and trend analysis.

    Attributes:
        session_buddy: Optional Session-Buddy MCP client
        collection: Collection name for storing coordination events
    """

    def __init__(self, session_buddy_client: Any | None = None) -> None:
        """Initialize coordination memory integration.

        Args:
            session_buddy_client: Optional Session-Buddy MCP client
        """
        self.session_buddy = session_buddy_client
        self.collection = "mahavishnu_coordination"

    async def store_issue_event(
        self,
        event_type: str,
        issue: CrossRepoIssue,
        changes: dict[str, Any] | None = None,
    ) -> None:
        """Store an issue-related event in memory.

        Args:
            event_type: Type of event (created, updated, closed, etc.)
            issue: The issue object
            changes: Optional dictionary of changed fields
        """
        if not self.session_buddy:
            return

        content = f"{event_type.capitalize()} issue {issue.id}: {issue.title}"

        metadata = {
            "event_type": event_type,
            "entity_id": issue.id,
            "entity_type": "issue",
            "title": issue.title,
            "status": issue.status.value,
            "priority": issue.priority.value,
            "repos": issue.repos,
            "assignee": issue.assignee,
            "timestamp": datetime.now().isoformat(),
        }

        if changes:
            metadata["changes"] = changes

        await self._store_memory(content, metadata)

    async def store_todo_event(
        self,
        event_type: str,
        todo: CrossRepoTodo,
        changes: dict[str, Any] | None = None,
    ) -> None:
        """Store a todo-related event in memory.

        Args:
            event_type: Type of event (created, updated, completed, etc.)
            todo: The todo object
            changes: Optional dictionary of changed fields
        """
        if not self.session_buddy:
            return

        content = f"{event_type.capitalize()} todo {todo.id}: {todo.task} in {todo.repo}"

        metadata = {
            "event_type": event_type,
            "entity_id": todo.id,
            "entity_type": "todo",
            "task": todo.task,
            "repo": todo.repo,
            "status": todo.status.value,
            "priority": todo.priority.value,
            "assignee": todo.assignee,
            "estimated_hours": todo.estimated_hours,
            "timestamp": datetime.now().isoformat(),
        }

        if changes:
            metadata["changes"] = changes

        await self._store_memory(content, metadata)

    async def store_dependency_event(
        self,
        event_type: str,
        dependency: Dependency,
        validation_result: dict[str, Any] | None = None,
    ) -> None:
        """Store a dependency-related event in memory.

        Args:
            event_type: Type of event (validated, status_changed, etc.)
            dependency: The dependency object
            validation_result: Optional validation result details
        """
        if not self.session_buddy:
            return

        content = (
            f"{event_type.capitalize()} dependency {dependency.id}: "
            f"{dependency.consumer} requires {dependency.provider} {dependency.version_constraint}"
        )

        metadata = {
            "event_type": event_type,
            "entity_id": dependency.id,
            "entity_type": "dependency",
            "consumer": dependency.consumer,
            "provider": dependency.provider,
            "type": dependency.type.value,
            "version_constraint": dependency.version_constraint,
            "status": dependency.status.value,
            "timestamp": datetime.now().isoformat(),
        }

        if validation_result:
            metadata["validation"] = validation_result

        await self._store_memory(content, metadata)

    async def store_plan_event(
        self,
        event_type: str,
        plan: CrossRepoPlan,
        milestone: str | None = None,
    ) -> None:
        """Store a plan-related event in memory.

        Args:
            event_type: Type of event (created, updated, milestone_completed, etc.)
            plan: The plan object
            milestone: Optional milestone ID related to the event
        """
        if not self.session_buddy:
            return

        content = f"{event_type.capitalize()} plan {plan.id}: {plan.title}"

        metadata = {
            "event_type": event_type,
            "entity_id": plan.id,
            "entity_type": "plan",
            "title": plan.title,
            "status": plan.status.value,
            "repos": plan.repos,
            "target": plan.target,
            "milestone_count": len(plan.milestones),
            "timestamp": datetime.now().isoformat(),
        }

        if milestone:
            metadata["milestone"] = milestone

        await self._store_memory(content, metadata)

    async def search_coordination_history(
        self,
        query: str,
        entity_type: str | None = None,
        repo: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search coordination history.

        Args:
            query: Search query string
            entity_type: Filter by entity type (issue, todo, plan, dependency)
            repo: Filter by repository
            limit: Maximum number of results

        Returns:
            List of matching coordination events
        """
        if not self.session_buddy:
            return []

        # Build search filters
        filters: dict[str, Any] = {"collection": self.collection}

        if entity_type:
            filters["entity_type"] = entity_type

        if repo:
            # Search in repos field (for issues/plans) or repo field (for todos)
            filters["$or"] = [{"repos": repo}, {"repo": repo}]

        # Search via Session-Buddy
        try:
            results = await self.session_buddy.search(
                query=query,
                filters=filters,
                limit=limit,
            )
            return results
        except Exception as e:
            # If search fails, log error and return empty results
            logger.error(f"Coordination memory search failed: {e}")
            return []

    async def get_coordination_trends(
        self,
        repo: str | None = None,
        days: int = 30,
    ) -> dict[str, Any]:
        """Get coordination trends and analytics.

        Args:
            repo: Optional repository to filter by
            days: Number of days to analyze

        Returns:
            Dictionary with trend statistics
        """
        if not self.session_buddy:
            return {"error": "Session-Buddy not available"}

        # This would typically use Session-Buddy's analytics features
        # For now, return a placeholder
        return {
            "message": "Trend analysis not yet implemented",
            "repo": repo,
            "days": days,
        }

    async def _store_memory(self, content: str, metadata: dict[str, Any]) -> None:
        """Store a memory in Session-Buddy.

        Args:
            content: Content string for search
            metadata: Metadata dictionary
        """
        try:
            await self.session_buddy.store_memory(
                collection=self.collection,
                content=content,
                metadata=metadata,
            )
        except Exception as e:
            # Log but don't fail - coordination is more important than memory
            logger.error(f"Failed to store coordination memory: {e}")

    async def close(self) -> None:
        """Close the memory integration and cleanup resources."""
        # Cleanup if needed
        pass


# Extended manager with memory integration


class CoordinationManagerWithMemory:
    """Coordination manager with automatic memory integration.

    Extends CoordinationManager to automatically store events
    in Session-Buddy for search and analytics.

    This class uses composition rather than inheritance to avoid
    MRO (Method Resolution Order) issues with type checking.

    Attributes:
        _coordination_mgr: Wrapped CoordinationManager instance
        _coordination_path: Path to ecosystem.yaml file
        memory: CoordinationMemory instance for storing events
    """

    def __init__(
        self,
        ecosystem_path: str = "settings/ecosystem.yaml",
        session_buddy_client: Any | None = None,
    ) -> None:
        """Initialize the coordination manager with memory.

        Args:
            ecosystem_path: Path to ecosystem.yaml
            session_buddy_client: Optional Session-Buddy client
        """
        # Import here to avoid circular dependency
        from mahavishnu.core.coordination.manager import CoordinationManager

        # Don't use super() to avoid MRO issues with type checking
        self._coordination_mgr = CoordinationManager(ecosystem_path)
        self._coordination_path = ecosystem_path
        self.memory = CoordinationMemory(session_buddy_client)

    # Delegate all CoordinationManager methods

    def reload(self) -> None:
        """Reload coordination data from ecosystem.yaml."""
        self._coordination_mgr.reload()

    def save(self) -> None:
        """Save coordination data back to ecosystem.yaml."""
        self._coordination_mgr.save()

    def list_issues(self, *args, **kwargs):
        """Delegate to wrapped manager.

        Args:
            *args: Positional arguments to pass to wrapped manager
            **kwargs: Keyword arguments to pass to wrapped manager

        Returns:
            Result from wrapped manager's list_issues method
        """
        return self._coordination_mgr.list_issues(*args, **kwargs)

    def get_issue(self, *args, **kwargs):
        """Delegate to wrapped manager.

        Args:
            *args: Positional arguments to pass to wrapped manager
            **kwargs: Keyword arguments to pass to wrapped manager

        Returns:
            Result from wrapped manager's get_issue method
        """
        return self._coordination_mgr.get_issue(*args, **kwargs)

    def create_issue(self, *args, **kwargs):
        """Delegate to wrapped manager.

        Args:
            *args: Positional arguments to pass to wrapped manager
            **kwargs: Keyword arguments to pass to wrapped manager

        Returns:
            Result from wrapped manager's create_issue method
        """
        return self._coordination_mgr.create_issue(*args, **kwargs)

    def update_issue(self, *args, **kwargs):
        """Delegate to wrapped manager.

        Args:
            *args: Positional arguments to pass to wrapped manager
            **kwargs: Keyword arguments to pass to wrapped manager

        Returns:
            Result from wrapped manager's update_issue method
        """
        return self._coordination_mgr.update_issue(*args, **kwargs)

    def delete_issue(self, *args, **kwargs):
        """Delegate to wrapped manager.

        Args:
            *args: Positional arguments to pass to wrapped manager
            **kwargs: Keyword arguments to pass to wrapped manager

        Returns:
            Result from wrapped manager's delete_issue method
        """
        return self._coordination_mgr.delete_issue(*args, **kwargs)

    def list_plans(self, *args, **kwargs):
        """Delegate to wrapped manager.

        Args:
            *args: Positional arguments to pass to wrapped manager
            **kwargs: Keyword arguments to pass to wrapped manager

        Returns:
            Result from wrapped manager's list_plans method
        """
        return self._coordination_mgr.list_plans(*args, **kwargs)

    def get_plan(self, *args, **kwargs):
        """Delegate to wrapped manager.

        Args:
            *args: Positional arguments to pass to wrapped manager
            **kwargs: Keyword arguments to pass to wrapped manager

        Returns:
            Result from wrapped manager's get_plan method
        """
        return self._coordination_mgr.get_plan(*args, **kwargs)

    def list_todos(self, *args, **kwargs):
        """Delegate to wrapped manager.

        Args:
            *args: Positional arguments to pass to wrapped manager
            **kwargs: Keyword arguments to pass to wrapped manager

        Returns:
            Result from wrapped manager's list_todos method
        """
        return self._coordination_mgr.list_todos(*args, **kwargs)

    def get_todo(self, *args, **kwargs):
        """Delegate to wrapped manager.

        Args:
            *args: Positional arguments to pass to wrapped manager
            **kwargs: Keyword arguments to pass to wrapped manager

        Returns:
            Result from wrapped manager's get_todo method
        """
        return self._coordination_mgr.get_todo(*args, **kwargs)

    def list_dependencies(self, *args, **kwargs):
        """Delegate to wrapped manager.

        Args:
            *args: Positional arguments to pass to wrapped manager
            **kwargs: Keyword arguments to pass to wrapped manager

        Returns:
            Result from wrapped manager's list_dependencies method
        """
        return self._coordination_mgr.list_dependencies(*args, **kwargs)

    def check_dependencies(self, *args, **kwargs):
        """Delegate to wrapped manager.

        Args:
            *args: Positional arguments to pass to wrapped manager
            **kwargs: Keyword arguments to pass to wrapped manager

        Returns:
            Result from wrapped manager's check_dependencies method
        """
        return self._coordination_mgr.check_dependencies(*args, **kwargs)

    def get_blocking_issues(self, *args, **kwargs):
        """Delegate to wrapped manager.

        Args:
            *args: Positional arguments to pass to wrapped manager
            **kwargs: Keyword arguments to pass to wrapped manager

        Returns:
            Result from wrapped manager's get_blocking_issues method
        """
        return self._coordination_mgr.get_blocking_issues(*args, **kwargs)

    def get_repo_status(self, *args, **kwargs):
        """Delegate to wrapped manager.

        Args:
            *args: Positional arguments to pass to wrapped manager
            **kwargs: Keyword arguments to pass to wrapped manager

        Returns:
            Result from wrapped manager's get_repo_status method
        """
        return self._coordination_mgr.get_repo_status(*args, **kwargs)

    # Memory-integrated methods

    async def create_issue_with_memory(self, issue: CrossRepoIssue) -> None:
        """Create an issue and store the event in memory.

        Args:
            issue: The issue to create
        """
        self.create_issue(issue)
        await self.memory.store_issue_event("created", issue)

    async def update_issue_with_memory(
        self,
        issue_id: str,
        updates: dict[str, Any],
    ) -> None:
        """Update an issue and store the event in memory.

        Args:
            issue_id: Issue identifier
            updates: Dictionary of fields to update
        """
        # Get old issue for comparison
        old_issue = self.get_issue(issue_id)

        self.update_issue(issue_id, updates)

        # Get updated issue
        new_issue = self.get_issue(issue_id)

        # Store event
        await self.memory.store_issue_event(
            "updated",
            new_issue,
            changes=updates,
        )

    async def close_issue_with_memory(self, issue_id: str) -> None:
        """Close an issue and store the event in memory.

        Args:
            issue_id: Issue identifier
        """
        self.update_issue(issue_id, {"status": "closed"})

        issue = self.get_issue(issue_id)
        await self.memory.store_issue_event("closed", issue)

    async def create_todo_with_memory(self, todo: CrossRepoTodo) -> None:
        """Create a todo and store the event in memory.

        Args:
            todo: The todo to create
        """
        todos_data = self._coordination_mgr._coordination.get("todos", [])
        todos_data.append(todo.model_dump(mode="json"))
        self._coordination["todos"] = todos_data
        self.save()

        await self.memory.store_todo_event("created", todo)

    async def complete_todo_with_memory(self, todo_id: str) -> None:
        """Complete a todo and store the event in memory.

        Args:
            todo_id: Todo identifier

        Raises:
            ValueError: If todo_id is not found
        """
        todos_data = self._coordination_mgr._coordination.get("todos", [])
        for todo in todos_data:
            if todo.get("id") == todo_id:
                todo["status"] = "completed"
                todo["updated"] = datetime.now().isoformat()
                self._coordination["todos"] = todos_data
                self.save()

                # Store event
                from mahavishnu.core.coordination.models import CrossRepoTodo

                completed_todo = CrossRepoTodo(**todo)
                await self.memory.store_todo_event("completed", completed_todo)
                return

        raise ValueError(f"Todo {todo_id} not found")

    async def check_dependencies_with_memory(
        self,
        consumer: str | None = None,
    ) -> dict[str, Any]:
        """Check dependencies and store validation events in memory.

        Args:
            consumer: Optional consumer repository to filter by

        Returns:
            Validation results dictionary
        """
        results = self._coordination_mgr.check_dependencies(consumer=consumer)

        # Store validation events for each dependency
        for dep_info in results["dependencies"]:
            from mahavishnu.core.coordination.models import (
                Dependency,
                DependencyStatus,
                DependencyType,
            )

            # Create a minimal Dependency object for memory
            dep = Dependency(
                id=dep_info["id"],
                consumer=dep_info["consumer"],
                provider=dep_info["provider"],
                type=DependencyType(dep_info["type"]),
                version_constraint=dep_info["version_constraint"],
                status=DependencyStatus(dep_info["status"]),
                created="",
                updated="",
                notes="",
            )

            await self.memory.store_dependency_event(
                "validated",
                dep,
                validation_result=dep_info.get("validation"),
            )

        return results
