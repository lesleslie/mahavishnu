"""
Integration tests for coordination system phases 4-6.

Tests MCP tools, memory integration, and pool execution.
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from mahavishnu.core.coordination.manager import CoordinationManager
from mahavishnu.core.coordination.memory import CoordinationMemory, CoordinationManagerWithMemory
from mahavishnu.core.coordination.executor import CoordinationExecutor
from mahavishnu.core.coordination.models import (
    CrossRepoIssue,
    CrossRepoTodo,
    CrossRepoPlan,
    Milestone,
    IssueStatus,
    Priority,
    TodoStatus,
    PlanStatus,
)


@pytest.fixture
def temp_ecosystem_file():
    """Create a temporary ecosystem.yaml with coordination data."""
    ecosystem_data = {
        "version": "1.0",
        "coordination": {
            "issues": [],
            "plans": [],
            "todos": [],
            "dependencies": [],
        },
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(ecosystem_data, f)
        temp_path = f.name

    yield temp_path

    Path(temp_path).unlink()


@pytest.fixture
def mock_session_buddy():
    """Create a mock Session-Buddy client."""
    client = AsyncMock()
    client.store_memory = AsyncMock()
    client.search = AsyncMock(return_value=[])
    return client


class TestPhase4_MCPTools:
    """Test suite for MCP tools (Phase 4)."""

    @pytest.mark.asyncio
    async def test_coord_list_issues_tool(self, temp_ecosystem_file):
        """Test coord_list_issues MCP tool."""
        # Import here to avoid import issues
        from mahavishnu.mcp.tools.coordination_tools import coord_list_issues

        # Create test data
        mgr = CoordinationManager(temp_ecosystem_file)
        issue = CrossRepoIssue(
            id="ISSUE-001",
            title="Test Issue",
            description="Test",
            status=IssueStatus.PENDING,
            priority=Priority.HIGH,
            severity="bug",
            repos=["mahavishnu"],
            created="2026-02-01T00:00:00",
            updated="2026-02-01T00:00:00",
            dependencies=[],
            blocking=[],
            labels=[],
            metadata={},
        )
        mgr.create_issue(issue)
        mgr.save()

        # Test the tool
        results = await coord_list_issues()
        assert len(results) == 1
        assert results[0]["id"] == "ISSUE-001"

    @pytest.mark.asyncio
    async def test_coord_create_issue_tool(self, temp_ecosystem_file):
        """Test coord_create_issue MCP tool."""
        from mahavishnu.mcp.tools.coordination_tools import coord_create_issue

        result = await coord_create_issue(
            title="MCP Test Issue",
            description="Created via MCP",
            repos=["mahavishnu"],
            priority="high",
        )

        assert result["id"] == "ISSUE-001"
        assert result["title"] == "MCP Test Issue"
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_coord_create_todo_tool(self, temp_ecosystem_file):
        """Test coord_create_todo MCP tool."""
        from mahavishnu.mcp.tools.coordination_tools import coord_create_todo

        # Create todo with unique repo to avoid ID conflicts
        result = await coord_create_todo(
            task="MCP Test Task",
            description="Created via MCP",
            repo="crackerjack",  # Different repo
            estimate_hours=4.0,
        )

        assert result["id"]  # Just verify ID exists
        assert result["task"] == "MCP Test Task"
        assert result["estimated_hours"] == 4.0


class TestPhase5_MemoryIntegration:
    """Test suite for memory integration (Phase 5)."""

    @pytest.mark.asyncio
    async def test_store_issue_event(self, mock_session_buddy):
        """Test storing issue events in memory."""
        memory = CoordinationMemory(mock_session_buddy)

        issue = CrossRepoIssue(
            id="ISSUE-001",
            title="Test Issue",
            description="Test",
            status=IssueStatus.PENDING,
            priority=Priority.HIGH,
            severity="bug",
            repos=["mahavishnu"],
            created="2026-02-01T00:00:00",
            updated="2026-02-01T00:00:00",
            dependencies=[],
            blocking=[],
            labels=[],
            metadata={},
        )

        await memory.store_issue_event("created", issue)

        # Verify memory was stored
        mock_session_buddy.store_memory.assert_called_once()
        call_args = mock_session_buddy.store_memory.call_args

        assert call_args[1]["content"] == "Created issue ISSUE-001: Test Issue"
        assert call_args[1]["metadata"]["entity_id"] == "ISSUE-001"
        assert call_args[1]["metadata"]["entity_type"] == "issue"

    @pytest.mark.asyncio
    async def test_store_todo_event(self, mock_session_buddy):
        """Test storing todo events in memory."""
        memory = CoordinationMemory(mock_session_buddy)

        todo = CrossRepoTodo(
            id="TODO-001",
            task="Test Task",
            description="Test",
            repo="mahavishnu",
            status=TodoStatus.PENDING,
            priority=Priority.MEDIUM,
            created="2026-02-01T00:00:00",
            updated="2026-02-01T00:00:00",
            estimated_hours=8.0,
            blocked_by=[],
            blocking=[],
            labels=[],
            acceptance_criteria=[],
        )

        await memory.store_todo_event("completed", todo)

        # Verify memory was stored
        mock_session_buddy.store_memory.assert_called_once()
        call_args = mock_session_buddy.store_memory.call_args

        assert "Completed todo TODO-001" in call_args[1]["content"]
        assert call_args[1]["metadata"]["entity_id"] == "TODO-001"
        assert call_args[1]["metadata"]["entity_type"] == "todo"

    @pytest.mark.asyncio
    async def test_create_issue_with_memory(self, temp_ecosystem_file, mock_session_buddy):
        """Test CoordinationManagerWithMemory."""
        mgr = CoordinationManagerWithMemory(temp_ecosystem_file, mock_session_buddy)

        issue = CrossRepoIssue(
            id="ISSUE-001",
            title="Memory Test Issue",
            description="Test",
            status=IssueStatus.PENDING,
            priority=Priority.HIGH,
            severity="feature",
            repos=["mahavishnu"],
            created="2026-02-01T00:00:00",
            updated="2026-02-01T00:00:00",
            dependencies=[],
            blocking=[],
            labels=[],
            metadata={},
        )

        await mgr.create_issue_with_memory(issue)

        # Verify issue was created
        retrieved = mgr.get_issue("ISSUE-001")
        assert retrieved is not None
        assert retrieved.title == "Memory Test Issue"

        # Verify memory was stored
        mock_session_buddy.store_memory.assert_called_once()


class TestPhase6_PoolExecution:
    """Test suite for pool execution (Phase 6)."""

    @pytest.mark.asyncio
    async def test_execute_todo_simulated(self, temp_ecosystem_file):
        """Test executing a todo (simulated)."""
        # Create test todo
        mgr = CoordinationManager(temp_ecosystem_file)
        todo = CrossRepoTodo(
            id="TODO-001",
            task="Test execution task",
            description="Test pool execution",
            repo="mahavishnu",
            status=TodoStatus.PENDING,
            priority=Priority.HIGH,
            created="2026-02-01T00:00:00",
            updated="2026-02-01T00:00:00",
            estimated_hours=2.0,
            blocked_by=[],
            blocking=[],
            labels=[],
            acceptance_criteria=[],
        )

        todos_data = mgr._coordination.get("todos", [])
        todos_data.append(todo.model_dump(mode="json"))
        mgr._coordination["todos"] = todos_data
        mgr.save()

        # Create executor (no pool manager = simulated)
        executor = CoordinationExecutor(mgr, pool_manager=None)

        # Execute todo
        result = await executor.execute_todo("TODO-001")

        assert result["success"] is True
        assert result["todo_id"] == "TODO-001"
        assert "duration_seconds" in result

        # Verify todo was marked completed
        mgr.reload()
        completed_todo = mgr.get_todo("TODO-001")
        assert completed_todo.status == TodoStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_execute_blocked_todo(self, temp_ecosystem_file):
        """Test that blocked todos cannot execute."""
        mgr = CoordinationManager(temp_ecosystem_file)
        todo = CrossRepoTodo(
            id="TODO-001",
            task="Blocked task",
            description="This should not execute",
            repo="mahavishnu",
            status=TodoStatus.BLOCKED,
            priority=Priority.HIGH,
            created="2026-02-01T00:00:00",
            updated="2026-02-01T00:00:00",
            estimated_hours=2.0,
            blocked_by=["ISSUE-001"],  # Blocked by an issue
            blocking=[],
            labels=[],
            acceptance_criteria=[],
        )

        todos_data = mgr._coordination.get("todos", [])
        todos_data.append(todo.model_dump(mode="json"))
        mgr._coordination["todos"] = todos_data
        mgr.save()

        executor = CoordinationExecutor(mgr, pool_manager=None)
        result = await executor.execute_todo("TODO-001")

        assert result["success"] is False
        assert "blocked" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_sweep_plan(self, temp_ecosystem_file):
        """Test sweeping a plan (executing all todos)."""
        # Create a plan with todos
        mgr = CoordinationManager(temp_ecosystem_file)

        # Create multiple todos
        for i in range(3):
            todo = CrossRepoTodo(
                id=f"TODO-{i+1:03d}",
                task=f"Task {i+1}",
                description=f"Test task {i+1}",
                repo="mahavishnu",
                status=TodoStatus.PENDING,
                priority=Priority.MEDIUM,
                created="2026-02-01T00:00:00",
                updated="2026-02-01T00:00:00",
                estimated_hours=1.0,
                blocked_by=[],
                blocking=[],
                labels=[],
                acceptance_criteria=[],
            )

            todos_data = mgr._coordination.get("todos", [])
            todos_data.append(todo.model_dump(mode="json"))
            mgr._coordination["todos"] = todos_data
            mgr.save()

        # Create plan
        plan = CrossRepoPlan(
            id="PLAN-001",
            title="Test Plan",
            description="Test sweep",
            status=PlanStatus.ACTIVE,
            repos=["mahavishnu"],
            created="2026-02-01T00:00:00",
            updated="2026-02-01T00:00:00",
            target="2026-02-15T00:00:00",
            milestones=[],
        )

        plans_data = mgr._coordination.get("plans", [])
        plans_data.append(plan.model_dump(mode="json"))
        mgr._coordination["plans"] = plans_data
        mgr.save()

        # Execute sweep
        executor = CoordinationExecutor(mgr, pool_manager=None)
        result = await executor.sweep_plan("PLAN-001", parallel=True)

        assert result["success"] is True
        assert result["total_todos"] == 3
        assert result["successful"] == 3
        assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_validate_plan_completion(self, temp_ecosystem_file):
        """Test validating plan completion."""
        mgr = CoordinationManager(temp_ecosystem_file)

        # Create plan with milestones
        plan = CrossRepoPlan(
            id="PLAN-001",
            title="Test Plan",
            description="Test validation",
            status=PlanStatus.ACTIVE,
            repos=["mahavishnu"],
            created="2026-02-01T00:00:00",
            updated="2026-02-01T00:00:00",
            target="2026-02-15T00:00:00",
            milestones=[
                Milestone(
                    id="MILESTONE-001",
                    name="Test Milestone",
                    description="Test milestone validation",
                    due="2026-02-15T00:00:00",
                    status=TodoStatus.PENDING,
                    dependencies=[],
                    completion_criteria=[
                        "Criterion 1",
                        "Criterion 2",
                    ],
                    deliverables=[],
                )
            ],
        )

        plans_data = mgr._coordination.get("plans", [])
        plans_data.append(plan.model_dump(mode="json"))
        mgr._coordination["plans"] = plans_data
        mgr.save()

        # Validate plan
        executor = CoordinationExecutor(mgr)
        result = await executor.validate_plan_completion("PLAN-001")

        assert result["valid"] is True  # Simulated validation
        assert len(result["milestones"]) == 1


class TestEndToEnd:
    """End-to-end tests for the complete coordination system."""

    @pytest.mark.asyncio
    async def test_full_workflow(self, temp_ecosystem_file, mock_session_buddy):
        """Test complete workflow: create -> execute -> track."""
        # Setup
        mgr = CoordinationManagerWithMemory(temp_ecosystem_file, mock_session_buddy)
        executor = CoordinationExecutor(mgr)

        # 1. Create an issue
        issue = CrossRepoIssue(
            id="ISSUE-001",
            title="Implement feature X",
            description="Full workflow test",
            status=IssueStatus.PENDING,
            priority=Priority.HIGH,
            severity="feature",
            repos=["mahavishnu"],
            created="2026-02-01T00:00:00",
            updated="2026-02-01T00:00:00",
            dependencies=[],
            blocking=[],
            labels=["feature"],
            metadata={},
        )

        await mgr.create_issue_with_memory(issue)

        # 2. Create a todo for the issue
        todo = CrossRepoTodo(
            id="TODO-001",
            task="Implement feature X core logic",
            description="Implement the core functionality",
            repo="mahavishnu",
            status=TodoStatus.PENDING,
            priority=Priority.HIGH,
            created="2026-02-01T00:00:00",
            updated="2026-02-01T00:00:00",
            estimated_hours=4.0,
            blocked_by=[],
            blocking=[],
            labels=["feature"],
            acceptance_criteria=[
                "Passes all tests",
                "Documented",
            ],
        )

        await mgr.create_todo_with_memory(todo)

        # 3. Execute the todo
        result = await executor.execute_todo("TODO-001")

        assert result["success"] is True

        # 4. Verify status
        final_todo = mgr.get_todo("TODO-001")
        assert final_todo.status == TodoStatus.COMPLETED
        assert final_todo.actual_hours is not None

        # 5. Close the issue
        await mgr.close_issue_with_memory("ISSUE-001")

        final_issue = mgr.get_issue("ISSUE-001")
        assert final_issue.status == IssueStatus.CLOSED

        # Verify all memory operations
        assert mock_session_buddy.store_memory.call_count == 4  # create_issue, create_todo, execute, close
