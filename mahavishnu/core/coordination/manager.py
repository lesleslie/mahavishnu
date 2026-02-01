"""
Coordination manager for cross-repository operations.

This module provides the CoordinationManager class that loads, queries,
and updates coordination data from ecosystem.yaml.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import ValidationError

from mahavishnu.core.coordination.models import (
    CrossRepoIssue,
    CrossRepoPlan,
    CrossRepoTodo,
    Dependency,
    IssueStatus,
    TodoStatus,
)
from mahavishnu.core.errors import ConfigurationError


class CoordinationManager:
    """
    Manage cross-repository coordination data.

    The CoordinationManager loads coordination data from ecosystem.yaml
    and provides query methods for issues, plans, todos, and dependencies.
    """

    def __init__(self, ecosystem_path: str = "settings/ecosystem.yaml") -> None:
        """
        Initialize the coordination manager.

        Args:
            ecosystem_path: Path to the ecosystem.yaml file

        Raises:
            ConfigurationError: If ecosystem.yaml cannot be loaded or parsed
        """
        self.ecosystem_path = Path(ecosystem_path)
        self._ecosystem: Dict[str, Any] = {}
        self._coordination: Dict[str, Any] = {}

        self._load_ecosystem()

    def _load_ecosystem(self) -> None:
        """
        Load ecosystem.yaml from disk.

        Raises:
            ConfigurationError: If the file cannot be loaded or parsed
        """
        if not self.ecosystem_path.exists():
            raise ConfigurationError(
                f"ecosystem.yaml not found at {self.ecosystem_path}",
                details={"path": str(self.ecosystem_path)},
            )

        try:
            with open(self.ecosystem_path) as f:
                self._ecosystem = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ConfigurationError(
                f"Failed to parse ecosystem.yaml: {e}",
                details={"path": str(self.ecosystem_path), "error": str(e)},
            ) from e

        self._coordination = self._ecosystem.get("coordination", {})

    def reload(self) -> None:
        """Reload coordination data from ecosystem.yaml."""
        self._load_ecosystem()

    def save(self) -> None:
        """
        Save coordination data back to ecosystem.yaml.

        Raises:
            ConfigurationError: If the file cannot be written
        """
        try:
            # Update the coordination section
            self._ecosystem["coordination"] = self._coordination

            with open(self.ecosystem_path, "w") as f:
                yaml.dump(self._ecosystem, f, default_flow_style=False, sort_keys=False)
        except IOError as e:
            raise ConfigurationError(
                f"Failed to write ecosystem.yaml: {e}",
                details={"path": str(self.ecosystem_path), "error": str(e)},
            ) from e

    # Issue Management

    def list_issues(
        self,
        status: Optional[IssueStatus] = None,
        priority: Optional[str] = None,
        repo: Optional[str] = None,
        assignee: Optional[str] = None,
    ) -> List[CrossRepoIssue]:
        """
        List cross-repository issues with optional filtering.

        Args:
            status: Filter by issue status
            priority: Filter by priority level
            repo: Filter by repository nickname
            assignee: Filter by assignee

        Returns:
            List of issues matching the filters
        """
        issues_data = self._coordination.get("issues", [])

        try:
            issues = [CrossRepoIssue(**issue) for issue in issues_data]
        except ValidationError as e:
            raise ConfigurationError(
                f"Invalid issue data in ecosystem.yaml: {e}",
                details={"error": str(e)},
            ) from e

        # Apply filters
        if status:
            issues = [i for i in issues if i.status == status]
        if priority:
            issues = [i for i in issues if i.priority.value == priority]
        if repo:
            issues = [i for i in issues if repo in i.repos]
        if assignee:
            issues = [i for i in issues if i.assignee == assignee]

        return issues

    def get_issue(self, issue_id: str) -> Optional[CrossRepoIssue]:
        """
        Get a specific issue by ID.

        Args:
            issue_id: Issue identifier (e.g., ISSUE-001)

        Returns:
            The issue if found, None otherwise
        """
        issues = self.list_issues()
        for issue in issues:
            if issue.id == issue_id:
                return issue
        return None

    def create_issue(self, issue: CrossRepoIssue) -> None:
        """
        Create a new cross-repository issue.

        Args:
            issue: The issue to create

        Raises:
            ConfigurationError: If an issue with the same ID already exists
        """
        issues = self._coordination.get("issues", [])

        # Check for duplicate ID
        if any(i.get("id") == issue.id for i in issues):
            raise ConfigurationError(
                f"Issue with ID {issue.id} already exists",
                details={"issue_id": issue.id},
            )

        # Add the new issue
        issues.append(issue.model_dump(mode="json"))
        self._coordination["issues"] = issues

    def update_issue(self, issue_id: str, updates: Dict[str, Any]) -> None:
        """
        Update an existing issue.

        Args:
            issue_id: Issue identifier
            updates: Dictionary of fields to update

        Raises:
            ConfigurationError: If the issue is not found
        """
        issues = self._coordination.get("issues", [])

        for i, issue in enumerate(issues):
            if issue.get("id") == issue_id:
                issues[i].update(updates)
                self._coordination["issues"] = issues
                return

        raise ConfigurationError(
            f"Issue {issue_id} not found",
            details={"issue_id": issue_id},
        )

    def delete_issue(self, issue_id: str) -> None:
        """
        Delete an issue.

        Args:
            issue_id: Issue identifier

        Raises:
            ConfigurationError: If the issue is not found
        """
        issues = self._coordination.get("issues", [])

        original_count = len(issues)
        issues = [i for i in issues if i.get("id") != issue_id]

        if len(issues) == original_count:
            raise ConfigurationError(
                f"Issue {issue_id} not found",
                details={"issue_id": issue_id},
            )

        self._coordination["issues"] = issues

    # Plan Management

    def list_plans(
        self,
        status: Optional[str] = None,
        repo: Optional[str] = None,
    ) -> List[CrossRepoPlan]:
        """
        List cross-repository plans with optional filtering.

        Args:
            status: Filter by plan status
            repo: Filter by repository nickname

        Returns:
            List of plans matching the filters
        """
        plans_data = self._coordination.get("plans", [])

        try:
            plans = [CrossRepoPlan(**plan) for plan in plans_data]
        except ValidationError as e:
            raise ConfigurationError(
                f"Invalid plan data in ecosystem.yaml: {e}",
                details={"error": str(e)},
            ) from e

        # Apply filters
        if status:
            plans = [p for p in plans if p.status.value == status]
        if repo:
            plans = [p for p in plans if repo in p.repos]

        return plans

    def get_plan(self, plan_id: str) -> Optional[CrossRepoPlan]:
        """
        Get a specific plan by ID.

        Args:
            plan_id: Plan identifier (e.g., PLAN-001)

        Returns:
            The plan if found, None otherwise
        """
        plans = self.list_plans()
        for plan in plans:
            if plan.id == plan_id:
                return plan
        return None

    # Todo Management

    def list_todos(
        self,
        status: Optional[TodoStatus] = None,
        repo: Optional[str] = None,
        assignee: Optional[str] = None,
    ) -> List[CrossRepoTodo]:
        """
        List todo items with optional filtering.

        Args:
            status: Filter by todo status
            repo: Filter by repository nickname
            assignee: Filter by assignee

        Returns:
            List of todos matching the filters
        """
        todos_data = self._coordination.get("todos", [])

        try:
            todos = [CrossRepoTodo(**todo) for todo in todos_data]
        except ValidationError as e:
            raise ConfigurationError(
                f"Invalid todo data in ecosystem.yaml: {e}",
                details={"error": str(e)},
            ) from e

        # Apply filters
        if status:
            todos = [t for t in todos if t.status == status]
        if repo:
            todos = [t for t in todos if t.repo == repo]
        if assignee:
            todos = [t for t in todos if t.assignee == assignee]

        return todos

    def get_todo(self, todo_id: str) -> Optional[CrossRepoTodo]:
        """
        Get a specific todo by ID.

        Args:
            todo_id: Todo identifier (e.g., TODO-001)

        Returns:
            The todo if found, None otherwise
        """
        todos = self.list_todos()
        for todo in todos:
            if todo.id == todo_id:
                return todo
        return None

    # Dependency Management

    def list_dependencies(
        self,
        consumer: Optional[str] = None,
        provider: Optional[str] = None,
        dependency_type: Optional[str] = None,
    ) -> List[Dependency]:
        """
        List dependencies with optional filtering.

        Args:
            consumer: Filter by consumer repository
            provider: Filter by provider repository
            dependency_type: Filter by dependency type

        Returns:
            List of dependencies matching the filters
        """
        deps_data = self._coordination.get("dependencies", [])

        try:
            deps = [Dependency(**dep) for dep in deps_data]
        except ValidationError as e:
            raise ConfigurationError(
                f"Invalid dependency data in ecosystem.yaml: {e}",
                details={"error": str(e)},
            ) from e

        # Apply filters
        if consumer:
            deps = [d for d in deps if d.consumer == consumer]
        if provider:
            deps = [d for d in deps if d.provider == provider]
        if dependency_type:
            deps = [d for d in deps if d.type.value == dependency_type]

        return deps

    def check_dependencies(self, consumer: Optional[str] = None) -> Dict[str, Any]:
        """
        Validate inter-repository dependencies.

        Args:
            consumer: Optional consumer repository to filter by

        Returns:
            Dictionary with validation results including:
            - total: Total number of dependencies checked
            - satisfied: Number of satisfied dependencies
            - unsatisfied: Number of unsatisfied dependencies
            - unknown: Number of dependencies with unknown status
            - dependencies: List of dependency details
        """
        deps = self.list_dependencies(consumer=consumer)

        results = {
            "total": len(deps),
            "satisfied": 0,
            "unsatisfied": 0,
            "unknown": 0,
            "deprecated": 0,
            "dependencies": [],
        }

        for dep in deps:
            dep_info = {
                "id": dep.id,
                "consumer": dep.consumer,
                "provider": dep.provider,
                "type": dep.type.value,
                "version_constraint": dep.version_constraint,
                "status": dep.status.value,
                "validation": None,
            }

            # Attempt validation if validation method is specified
            if dep.validation:
                dep_info["validation"] = self._validate_dependency(dep)

            # Count by status
            if dep.status.value == "satisfied":
                results["satisfied"] += 1
            elif dep.status.value == "unsatisfied":
                results["unsatisfied"] += 1
            elif dep.status.value == "unknown":
                results["unknown"] += 1
            elif dep.status.value == "deprecated":
                results["deprecated"] += 1

            results["dependencies"].append(dep_info)

        return results

    def _validate_dependency(self, dep: Dependency) -> Dict[str, Any]:
        """
        Validate a dependency using its validation method.

        Args:
            dep: The dependency to validate

        Returns:
            Dictionary with validation results
        """
        import subprocess

        result = {"method": None, "passed": False, "details": None}

        if dep.validation and dep.validation.command:
            result["method"] = "command"
            try:
                output = subprocess.check_output(
                    dep.validation.command,
                    shell=True,
                    text=True,
                    stderr=subprocess.STDOUT,
                )
                if dep.validation.expected_pattern:
                    pattern = re.compile(dep.validation.expected_pattern)
                    result["passed"] = bool(pattern.search(output))
                    result["details"] = output.strip()
                else:
                    result["passed"] = True
                    result["details"] = output.strip()
            except subprocess.CalledProcessError as e:
                result["passed"] = False
                result["details"] = e.output
            except Exception as e:
                result["passed"] = False
                result["details"] = str(e)

        return result

    # Status and Reporting

    def get_blocking_issues(self, repo: str) -> List[CrossRepoIssue]:
        """
        Get all issues blocking a specific repository.

        Args:
            repo: Repository nickname

        Returns:
            List of issues that affect the repository and are not resolved
        """
        issues = self.list_issues(repo=repo)
        return [i for i in issues if i.status not in [IssueStatus.RESOLVED, IssueStatus.CLOSED]]

    def get_repo_status(self, repo: str) -> Dict[str, Any]:
        """
        Get comprehensive coordination status for a repository.

        Args:
            repo: Repository nickname

        Returns:
            Dictionary with:
            - issues: List of issues affecting this repo
            - todos: List of todos for this repo
            - dependencies_outgoing: Dependencies this repo has on others
            - dependencies_incoming: Dependencies other repos have on this one
            - blocking: What this repo is blocking
            - blocked_by: What is blocking this repo
        """
        return {
            "issues": self.get_blocking_issues(repo),
            "todos": self.list_todos(repo=repo),
            "dependencies_outgoing": self.list_dependencies(consumer=repo),
            "dependencies_incoming": self.list_dependencies(provider=repo),
            "blocking": self._get_blocking_todos(repo),
            "blocked_by": self._get_blocking_dependencies(repo),
        }

    def _get_blocking_todos(self, repo: str) -> List[CrossRepoTodo]:
        """
        Get todos in this repository that are blocking other repos.

        Args:
            repo: Repository nickname

        Returns:
            List of todos that have blocking items
        """
        todos = self.list_todos(repo=repo)
        return [t for t in todos if t.blocking and t.status != TodoStatus.COMPLETED]

    def _get_blocking_dependencies(self, repo: str) -> List[Dependency]:
        """
        Get dependencies that are blocking this repository.

        Args:
            repo: Repository nickname

        Returns:
            List of unsatisfied dependencies
        """
        deps = self.list_dependencies(consumer=repo)
        return [d for d in deps if d.status.value != "satisfied"]
