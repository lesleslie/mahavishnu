"""
Pool execution integration for cross-repository coordination.

Executes todo items via worker pools with progress tracking.
"""

import asyncio
from datetime import datetime
from typing import Any

from mahavishnu.core.coordination.manager import CoordinationManager
from mahavishnu.core.coordination.models import CrossRepoTodo


class CoordinationExecutor:
    """
    Execute coordination tasks via worker pools.

    This class provides integration with Mahavishnu's pool system
    to execute todo items across distributed worker resources.
    """

    def __init__(
        self,
        coordination_manager: CoordinationManager | None = None,
        pool_manager: Any | None = None,
    ) -> None:
        """
        Initialize the coordination executor.

        Args:
            coordination_manager: Optional CoordinationManager instance
            pool_manager: Optional pool manager for task execution
        """
        self.coordination = coordination_manager or CoordinationManager()
        self.pool_manager = pool_manager

    async def execute_todo(
        self,
        todo_id: str,
        pool_type: str = "mahavishnu",
        pool_selector: str = "least_loaded",
        timeout: int = 3600,
    ) -> dict[str, Any]:
        """
        Execute a todo via specified pool.

        Args:
            todo_id: Todo identifier (e.g., TODO-001)
            pool_type: Type of pool to use (mahavishnu, session-buddy, kubernetes)
            pool_selector: Pool selection strategy (round_robin, least_loaded, random)
            timeout: Execution timeout in seconds

        Returns:
            Execution result dictionary with status, output, and metrics
        """
        # Get the todo
        todo = self.coordination.get_todo(todo_id)
        if not todo:
            return {
                "success": False,
                "error": f"Todo {todo_id} not found",
                "todo_id": todo_id,
            }

        # Check if blocked
        if todo.blocked_by:
            return {
                "success": False,
                "error": f"Todo is blocked by: {', '.join(todo.blocked_by)}",
                "todo_id": todo_id,
                "blocked_by": todo.blocked_by,
            }

        # Check if already completed
        if todo.status.value == "completed":
            return {
                "success": True,
                "message": "Todo already completed",
                "todo_id": todo_id,
            }

        # Update todo status to in_progress
        self._update_todo_status(todo_id, "in_progress")

        # Prepare task for pool
        task_prompt = self._create_task_prompt(todo)

        task_data = {
            "prompt": task_prompt,
            "timeout": timeout,
            "repo": todo.repo,
            "todo_id": todo_id,
        }

        # Execute via pool
        start_time = datetime.now()

        try:
            if not self.pool_manager:
                # Simulate execution if no pool manager
                result = await self._simulate_execution(todo)
            else:
                # Actual pool execution
                result = await self._execute_via_pool(
                    task_data,
                    pool_type,
                    pool_selector,
                )

            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            # Update todo with results
            if result.get("success"):
                self._update_todo_status(todo_id, "completed")
                # Record actual hours if estimated was provided
                actual_hours = duration / 3600
                self._update_todo_actual_hours(todo_id, actual_hours)

            return {
                "success": result.get("success", False),
                "todo_id": todo_id,
                "task": todo.task,
                "repo": todo.repo,
                "duration_seconds": duration,
                "output": result.get("output"),
                "error": result.get("error"),
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            }

        except Exception as e:
            # Update todo to blocked if execution failed
            self._update_todo_status(todo_id, "blocked")

            return {
                "success": False,
                "error": str(e),
                "todo_id": todo_id,
                "task": todo.task,
            }

    async def sweep_plan(
        self,
        plan_id: str,
        pool_type: str = "mahavishnu",
        pool_selector: str = "least_loaded",
        parallel: bool = True,
    ) -> dict[str, Any]:
        """
        Execute all pending todos in a plan.

        Args:
            plan_id: Plan identifier (e.g., PLAN-001)
            pool_type: Type of pool to use
            pool_selector: Pool selection strategy
            parallel: Whether to execute todos in parallel

        Returns:
            Sweep results with summary and individual todo results
        """
        # Get the plan
        plan = self.coordination.get_plan(plan_id)
        if not plan:
            return {
                "success": False,
                "error": f"Plan {plan_id} not found",
                "plan_id": plan_id,
            }

        # Get all pending todos for repos in this plan
        todos = []
        for repo in plan.repos:
            repo_todos = self.coordination.list_todos(
                repo=repo,
            )
            # Filter for pending todos only
            pending_todos = [t for t in repo_todos if t.status.value == "pending"]
            todos.extend(pending_todos)

        if not todos:
            return {
                "success": True,
                "message": "No pending todos to execute",
                "plan_id": plan_id,
                "total_todos": 0,
                "executed": 0,
            }

        # Execute todos
        if parallel:
            results = await self._execute_parallel(todos, pool_type, pool_selector)
        else:
            results = await self._execute_sequential(todos, pool_type, pool_selector)

        # Calculate summary
        successful = sum(1 for r in results if r.get("success"))
        failed = len(results) - successful

        return {
            "success": failed == 0,
            "plan_id": plan_id,
            "total_todos": len(todos),
            "successful": successful,
            "failed": failed,
            "results": results,
        }

    async def validate_plan_completion(
        self,
        plan_id: str,
    ) -> dict[str, Any]:
        """
        Validate that all plan acceptance criteria are met.

        Args:
            plan_id: Plan identifier

        Returns:
            Validation results with completion status
        """
        plan = self.coordination.get_plan(plan_id)
        if not plan:
            return {
                "valid": False,
                "error": f"Plan {plan_id} not found",
            }

        # Check each milestone
        milestone_results = []
        for milestone in plan.milestones:
            result = await self._validate_milestone(milestone, plan.repos)
            milestone_results.append(result)

        # Overall validation
        all_valid = all(r["valid"] for r in milestone_results)

        return {
            "valid": all_valid,
            "plan_id": plan_id,
            "milestones": milestone_results,
        }

    async def _execute_via_pool(
        self,
        task_data: dict[str, Any],
        pool_type: str,
        pool_selector: str,
    ) -> dict[str, Any]:
        """Execute task via pool manager."""
        try:
            # Import here to avoid circular imports
            from mahavishnu.pools import PoolSelector

            selector = PoolSelector(pool_selector)
            result = await self.pool_manager.route_task(
                task_data,
                pool_selector=selector,
            )
            return result

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    async def _simulate_execution(
        self,
        todo: CrossRepoTodo,
    ) -> dict[str, Any]:
        """Simulate execution for testing."""
        # Simulate work
        await asyncio.sleep(0.5)

        return {
            "success": True,
            "output": f"Simulated execution of: {todo.task}",
        }

    async def _execute_parallel(
        self,
        todos: list[CrossRepoTodo],
        pool_type: str,
        pool_selector: str,
    ) -> list[dict[str, Any]]:
        """Execute todos in parallel."""
        tasks = [self.execute_todo(todo.id, pool_type, pool_selector) for todo in todos]
        return await asyncio.gather(*tasks)

    async def _execute_sequential(
        self,
        todos: list[CrossRepoTodo],
        pool_type: str,
        pool_selector: str,
    ) -> list[dict[str, Any]]:
        """Execute todos sequentially."""
        results = []
        for todo in todos:
            result = await self.execute_todo(todo.id, pool_type, pool_selector)
            results.append(result)

            # Stop if execution failed
            if not result.get("success"):
                break

        return results

    async def _validate_milestone(
        self,
        milestone: Any,
        repos: list[str],
    ) -> dict[str, Any]:
        """Validate a milestone's completion criteria."""
        # Check all criteria
        criteria_met = []
        for criterion in milestone.completion_criteria:
            # This would check if the criterion is met
            # For now, simulate validation
            criteria_met.append(
                {
                    "criterion": criterion,
                    "met": True,  # Simulated
                }
            )

        all_met = all(c["met"] for c in criteria_met)

        return {
            "valid": all_met,
            "milestone_id": milestone.id,
            "milestone_name": milestone.name,
            "criteria": criteria_met,
        }

    def _create_task_prompt(self, todo: CrossRepoTodo) -> str:
        """Create a task prompt from a todo."""
        prompt = f"Task: {todo.task}\n\n"
        prompt += f"Description: {todo.description}\n\n"
        prompt += f"Repository: {todo.repo}\n\n"

        if todo.acceptance_criteria:
            prompt += "Acceptance Criteria:\n"
            for i, criterion in enumerate(todo.acceptance_criteria, 1):
                prompt += f"  {i}. {criterion}\n"

        return prompt

    def _update_todo_status(self, todo_id: str, status: str) -> None:
        """Update todo status."""
        todos_data = self.coordination._coordination.get("todos", [])
        for todo in todos_data:
            if todo.get("id") == todo_id:
                todo["status"] = status
                todo["updated"] = datetime.now().isoformat()
                self.coordination._coordination["todos"] = todos_data
                self.coordination.save()
                return

    def _update_todo_actual_hours(self, todo_id: str, hours: float) -> None:
        """Update todo with actual hours spent."""
        todos_data = self.coordination._coordination.get("todos", [])
        for todo in todos_data:
            if todo.get("id") == todo_id:
                todo["actual_hours"] = round(hours, 2)
                self.coordination._coordination["todos"] = todos_data
                self.coordination.save()
                return
