"""
Coordination manager for cross-repository operations.

This module provides the CoordinationManager class that loads, queries,
and updates coordination data from ecosystem.yaml.
"""

import os
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any

from pydantic import ValidationError
import yaml

from mahavishnu.core.coordination.models import (
    CrossRepoIssue,
    CrossRepoPlan,
    CrossRepoTodo,
    Dependency,
    IssueStatus,
    TodoStatus,
)
from mahavishnu.core.errors import ConfigurationError


def _run_command_safe(command: str) -> str:
    """Run a validation command without shell=True.

    Handles pipe-separated commands by chaining Popen processes explicitly
    instead of delegating to a shell. Commands come from operator-controlled
    ecosystem.yaml, but we still avoid shell=True to eliminate the injection
    vector entirely.
    """
    stages = [shlex.split(stage.strip()) for stage in command.split("|")]
    if not stages:
        return ""

    procs: list[subprocess.Popen[str]] = []
    for args in stages:
        stdin = procs[-1].stdout if procs else None
        proc = subprocess.Popen(
            args,
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if stdin is not None:
            stdin.close()
        procs.append(proc)

    output, _ = procs[-1].communicate()
    for proc in procs[:-1]:
        proc.wait()

    last_rc = procs[-1].returncode
    if last_rc not in (0, None):
        raise subprocess.CalledProcessError(last_rc, stages[-1], output=output)
    return output


class CoordinationManager:
    """
    Manage cross-repository coordination data.

    The CoordinationManager loads coordination data from ecosystem.yaml
    and provides query methods for issues, plans, todos, and dependencies.
    """

    def __init__(self, ecosystem_path: str | None = None) -> None:
        """
        Initialize the coordination manager.

        Args:
            ecosystem_path: Path to the ecosystem.yaml file

        Raises:
            ConfigurationError: If ecosystem.yaml cannot be loaded or parsed
        """
        if ecosystem_path is None:
            ecosystem_path = os.getenv("MAHAVISHNU_ECOSYSTEM_PATH", "settings/ecosystem.yaml")

        self.ecosystem_path = Path(ecosystem_path)
        self._ecosystem: dict[str, Any] = {}
        self._coordination: dict[str, Any] = {}

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

    def _normalize_issue_record(self, issue: dict[str, Any]) -> dict[str, Any]:
        """Normalize legacy issue records to the current schema."""
        normalized = dict(issue)

        if "repos" not in normalized or not normalized.get("repos"):
            inferred_repos = self._infer_issue_repos(normalized)
            if inferred_repos:
                normalized["repos"] = inferred_repos

        if "created" not in normalized:
            normalized["created"] = normalized.get("created_at") or normalized.get("created") or ""
        if "updated" not in normalized:
            normalized["updated"] = (
                normalized.get("updated_at")
                or normalized.get("fixed_at")
                or normalized.get("updated")
                or normalized.get("created")
            )

        normalized["created"] = self._stringify_datetime(normalized.get("created"))
        normalized["updated"] = self._stringify_datetime(normalized.get("updated"))

        normalized["status"] = self._normalize_issue_status(normalized.get("status"))
        normalized["priority"] = self._normalize_issue_priority(normalized.get("priority"))

        if "labels" not in normalized and "tags" in normalized:
            tags = normalized.get("tags")
            normalized["labels"] = tags if isinstance(tags, list) else []

        return normalized

    def _normalize_todo_record(self, todo: dict[str, Any]) -> dict[str, Any]:
        """Normalize legacy todo records to the current schema."""
        normalized = dict(todo)

        if "task" not in normalized:
            normalized["task"] = (
                normalized.get("title")
                or normalized.get("description")
                or normalized.get("id")
                or "todo"
            )
        if "description" not in normalized:
            normalized["description"] = normalized.get("task") or ""

        if "repo" not in normalized or not normalized.get("repo"):
            normalized["repo"] = self._infer_todo_repo(normalized)

        if "created" not in normalized:
            normalized["created"] = normalized.get("created_at") or normalized.get("created") or ""
        if "updated" not in normalized:
            normalized["updated"] = (
                normalized.get("updated_at")
                or normalized.get("completed_at")
                or normalized.get("updated")
                or normalized.get("created")
            )

        normalized["created"] = self._stringify_datetime(normalized.get("created"))
        normalized["updated"] = self._stringify_datetime(normalized.get("updated"))

        estimated_hours = normalized.get("estimated_hours")
        if estimated_hours is None:
            estimated_hours = normalized.get("estimate_hours")
        if estimated_hours is None:
            estimated_hours = 1.0
        normalized["estimated_hours"] = estimated_hours

        normalized["status"] = self._normalize_todo_status(normalized.get("status"))
        normalized["priority"] = self._normalize_issue_priority(normalized.get("priority"))

        if "labels" not in normalized and "tags" in normalized:
            tags = normalized.get("tags")
            normalized["labels"] = tags if isinstance(tags, list) else []

        return normalized

    def _infer_todo_repo(self, todo: dict[str, Any]) -> str:
        """Infer the repository for a todo from legacy fields."""
        issue_id = todo.get("issue_id")
        if isinstance(issue_id, str) and issue_id.strip():
            issue = self.get_issue(issue_id.strip())
            if issue and issue.repos:
                return issue.repos[0]

        pool = todo.get("pool")
        if isinstance(pool, str) and pool.strip():
            return pool.strip()

        return "mahavishnu"

    def _infer_issue_repos(self, issue: dict[str, Any]) -> list[str]:
        """Infer affected repositories from legacy issue fields."""
        affected_files = issue.get("affected_files")
        if isinstance(affected_files, list):
            repos = sorted(
                {
                    Path(path).parts[0]
                    for path in affected_files
                    if isinstance(path, str) and Path(path).parts
                }
            )
            if repos:
                return repos

        pool = issue.get("pool")
        if isinstance(pool, str) and pool.strip():
            return [pool.strip()]

        return ["mahavishnu"]

    def _normalize_issue_status(self, value: Any) -> IssueStatus:
        """Map legacy status values onto the current issue lifecycle."""
        if isinstance(value, IssueStatus):
            return value

        normalized = str(value).strip().lower() if value is not None else ""
        aliases = {
            "fixed": IssueStatus.RESOLVED,
            "resolved": IssueStatus.RESOLVED,
            "closed": IssueStatus.CLOSED,
            "open": IssueStatus.PENDING,
            "todo": IssueStatus.PENDING,
            "planned": IssueStatus.PENDING,
            "in progress": IssueStatus.IN_PROGRESS,
            "in_progress": IssueStatus.IN_PROGRESS,
            "blocked": IssueStatus.BLOCKED,
        }
        if normalized in aliases:
            return aliases[normalized]

        try:
            return IssueStatus(normalized)
        except Exception:
            return IssueStatus.PENDING

    def _normalize_issue_priority(self, value: Any) -> str:
        """Map legacy priority values onto the current priority enum."""
        normalized = str(value).strip().lower() if value is not None else ""
        aliases = {
            "p0": "critical",
            "p1": "high",
            "p2": "medium",
            "p3": "low",
            "critical": "critical",
            "high": "high",
            "medium": "medium",
            "low": "low",
        }
        return aliases.get(normalized, "medium")

    def _normalize_todo_status(self, value: Any) -> TodoStatus:
        """Map legacy todo status values onto the current todo lifecycle."""
        if isinstance(value, TodoStatus):
            return value

        normalized = str(value).strip().lower() if value is not None else ""
        aliases = {
            "done": TodoStatus.COMPLETED,
            "completed": TodoStatus.COMPLETED,
            "complete": TodoStatus.COMPLETED,
            "blocked": TodoStatus.BLOCKED,
            "in progress": TodoStatus.IN_PROGRESS,
            "in_progress": TodoStatus.IN_PROGRESS,
            "in-progress": TodoStatus.IN_PROGRESS,
            "pending": TodoStatus.PENDING,
            "open": TodoStatus.PENDING,
            "todo": TodoStatus.PENDING,
        }
        if normalized in aliases:
            return aliases[normalized]

        try:
            return TodoStatus(normalized)
        except Exception:
            return TodoStatus.PENDING

    def _stringify_datetime(self, value: Any) -> Any:
        """Convert parsed YAML datetimes back to ISO strings."""
        if hasattr(value, "isoformat") and not isinstance(value, str):
            return value.isoformat()
        return value

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
        except OSError as e:
            raise ConfigurationError(
                f"Failed to write ecosystem.yaml: {e}",
                details={"path": str(self.ecosystem_path), "error": str(e)},
            ) from e

    # Issue Management

    @staticmethod
    def _apply_issue_filters(
        issues: list[CrossRepoIssue],
        status: IssueStatus | None,
        priority: str | None,
        repo: str | None,
        assignee: str | None,
    ) -> list[CrossRepoIssue]:
        if status:
            issues = [i for i in issues if i.status == status]
        if priority:
            issues = [i for i in issues if i.priority.value == priority]
        if repo:
            issues = [i for i in issues if repo in i.repos]
        if assignee:
            issues = [i for i in issues if i.assignee == assignee]
        return issues

    def list_issues(
        self,
        status: IssueStatus | None = None,
        priority: str | None = None,
        repo: str | None = None,
        assignee: str | None = None,
    ) -> list[CrossRepoIssue]:
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
            issues = [
                CrossRepoIssue(**self._normalize_issue_record(issue)) for issue in issues_data
            ]
        except ValidationError as e:
            raise ConfigurationError(
                f"Invalid issue data in ecosystem.yaml: {e}",
                details={"error": str(e)},
            ) from e

        return self._apply_issue_filters(issues, status, priority, repo, assignee)

    def get_issue(self, issue_id: str) -> CrossRepoIssue | None:
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

    def update_issue(self, issue_id: str, updates: dict[str, Any]) -> None:
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
        status: str | None = None,
        repo: str | None = None,
    ) -> list[CrossRepoPlan]:
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

    def get_plan(self, plan_id: str) -> CrossRepoPlan | None:
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
        status: TodoStatus | None = None,
        repo: str | None = None,
        assignee: str | None = None,
    ) -> list[CrossRepoTodo]:
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
            todos = [CrossRepoTodo(**self._normalize_todo_record(todo)) for todo in todos_data]
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

    def get_todo(self, todo_id: str) -> CrossRepoTodo | None:
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
        consumer: str | None = None,
        provider: str | None = None,
        dependency_type: str | None = None,
    ) -> list[Dependency]:
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

    def check_dependencies(self, consumer: str | None = None) -> dict[str, Any]:
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
                dep_info["validation"] = self._validate_dependency(dep)  # type: ignore[assignment]

            # Count by status
            if dep.status.value == "satisfied":
                results["satisfied"] += 1  # type: ignore[operator]
            elif dep.status.value == "unsatisfied":
                results["unsatisfied"] += 1  # type: ignore[operator]
            elif dep.status.value == "unknown":
                results["unknown"] += 1  # type: ignore[operator]
            elif dep.status.value == "deprecated":
                results["deprecated"] += 1  # type: ignore[operator]

            results["dependencies"].append(dep_info)  # type: ignore[attr-defined]

        return results

    def _validate_dependency(self, dep: Dependency) -> dict[str, Any]:
        """
        Validate a dependency using its validation method.

        Args:
            dep: The dependency to validate

        Returns:
            Dictionary with validation results
        """
        result = {"method": None, "passed": False, "details": None}

        if dep.validation and dep.validation.command:
            result["method"] = "command"  # type: ignore[assignment]
            try:
                output = _run_command_safe(dep.validation.command)
                if dep.validation.expected_pattern:
                    pattern = re.compile(dep.validation.expected_pattern)
                    result["passed"] = bool(pattern.search(output))
                    result["details"] = output.strip()  # type: ignore[assignment]
                else:
                    result["passed"] = True
                    result["details"] = output.strip()  # type: ignore[assignment]
            except subprocess.CalledProcessError as e:
                result["passed"] = False
                result["details"] = getattr(e, "output", str(e))  # type: ignore[arg-type]
            except Exception as e:
                result["passed"] = False
                result["details"] = str(e)  # type: ignore[assignment]

        return result

    # Status and Reporting

    def get_blocking_issues(self, repo: str) -> list[CrossRepoIssue]:
        """
        Get all issues blocking a specific repository.

        Args:
            repo: Repository nickname

        Returns:
            List of issues that affect the repository and are not resolved
        """
        issues = self.list_issues(repo=repo)
        return [i for i in issues if i.status not in [IssueStatus.RESOLVED, IssueStatus.CLOSED]]

    def get_repo_status(self, repo: str) -> dict[str, Any]:
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

    def _get_blocking_todos(self, repo: str) -> list[CrossRepoTodo]:
        """
        Get todos in this repository that are blocking other repos.

        Args:
            repo: Repository nickname

        Returns:
            List of todos that have blocking items
        """
        todos = self.list_todos(repo=repo)
        return [t for t in todos if t.blocking and t.status != TodoStatus.COMPLETED]

    def _get_blocking_dependencies(self, repo: str) -> list[Dependency]:
        """
        Get dependencies that are blocking this repository.

        Args:
            repo: Repository nickname

        Returns:
            List of unsatisfied dependencies
        """
        deps = self.list_dependencies(consumer=repo)
        return [d for d in deps if d.status.value != "satisfied"]

    def get_ecosystem_status(self) -> dict[str, Any]:
        """Get unified ecosystem coordination status.

        Returns a single aggregated view suitable for operator dashboards and
        the coord_get_ecosystem_status MCP tool. Answers: "What is blocked,
        failing, and needs action right now?"

        Returns:
            Dictionary with active_plans, critical_blockers, degraded_dependencies,
            pending/in_progress todo counts, and an overall health indicator.
        """
        active_plans = self.list_plans(status="active")

        open_blockers = [
            i
            for i in self.list_issues()
            if i.priority.value in ("critical", "high")
            and i.status.value not in ("resolved", "closed")
        ]

        dep_check = self.check_dependencies()
        unsatisfied = [d for d in dep_check["dependencies"] if d["status"] != "satisfied"]

        pending_todos = self.list_todos(status=TodoStatus.PENDING)
        in_progress_todos = self.list_todos(status=TodoStatus.IN_PROGRESS)

        health = "degraded" if (open_blockers or unsatisfied) else "healthy"

        return {
            "health": health,
            "active_plans": len(active_plans),
            "plans": [
                {
                    "id": p.id,
                    "title": p.title,
                    "target": p.target,
                    "milestones_total": len(p.milestones),
                    "milestones_done": sum(
                        1 for m in p.milestones if m.status.value == "completed"
                    ),
                }
                for p in active_plans
            ],
            "critical_blockers": len(open_blockers),
            "blockers": [
                {"id": i.id, "title": i.title, "priority": i.priority.value, "repos": i.repos}
                for i in open_blockers
            ],
            "degraded_dependencies": len(unsatisfied),
            "dependencies": unsatisfied,
            "pending_todos": len(pending_todos),
            "in_progress_todos": len(in_progress_todos),
        }
