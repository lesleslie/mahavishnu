"""Tests for Command Execution API - RPC method handlers for GUI clients."""

import pytest
from datetime import datetime, UTC
from unittest.mock import MagicMock, AsyncMock
from typing import Any

from mahavishnu.core.command_api import (
    CommandRegistry,
    CommandHandler,
    CommandResult,
    CommandError,
    ErrorCode,
)


@pytest.fixture
def mock_task_store() -> AsyncMock:
    """Create a mock task store."""
    store = AsyncMock()
    store.get.return_value = {
        "id": "task-123",
        "title": "Test Task",
        "status": "pending",
        "priority": "high",
    }
    store.list.return_value = [
        {"id": "task-1", "title": "Task 1", "status": "pending"},
        {"id": "task-2", "title": "Task 2", "status": "in_progress"},
    ]
    store.create.return_value = {"id": "task-new", "title": "New Task"}
    store.update.return_value = {"id": "task-123", "status": "completed"}
    store.delete.return_value = True
    return store


@pytest.fixture
def sample_create_params() -> dict[str, Any]:
    """Create sample parameters for task creation."""
    return {
        "title": "New Task",
        "description": "Task description",
        "priority": "high",
        "repository": "mahavishnu",
    }


class TestErrorCode:
    """Tests for ErrorCode enum."""

    def test_error_codes(self) -> None:
        """Test available error codes."""
        assert ErrorCode.TASK_NOT_FOUND.value == "TASK_NOT_FOUND"
        assert ErrorCode.INVALID_PARAMETER.value == "INVALID_PARAMETER"
        assert ErrorCode.PERMISSION_DENIED.value == "PERMISSION_DENIED"
        assert ErrorCode.OPERATION_FAILED.value == "OPERATION_FAILED"
        assert ErrorCode.VALIDATION_ERROR.value == "VALIDATION_ERROR"


class TestCommandError:
    """Tests for CommandError class."""

    def test_create_error(self) -> None:
        """Create a command error."""
        error = CommandError(
            code=ErrorCode.TASK_NOT_FOUND,
            message="Task not found",
        )

        assert error.code == ErrorCode.TASK_NOT_FOUND
        assert error.message == "Task not found"

    def test_error_with_details(self) -> None:
        """Create error with details."""
        error = CommandError(
            code=ErrorCode.VALIDATION_ERROR,
            message="Validation failed",
            details={"field": "title", "reason": "required"},
        )

        assert error.details["field"] == "title"
        assert error.details["reason"] == "required"

    def test_error_to_dict(self) -> None:
        """Convert error to dictionary."""
        error = CommandError(
            code=ErrorCode.INVALID_PARAMETER,
            message="Invalid parameter",
            details={"param": "task_id"},
        )

        d = error.to_dict()

        assert d["code"] == "INVALID_PARAMETER"
        assert d["message"] == "Invalid parameter"
        assert d["details"]["param"] == "task_id"


class TestCommandResult:
    """Tests for CommandResult class."""

    def test_success_result(self) -> None:
        """Create a success result."""
        result = CommandResult.success(
            data={"id": "task-123"},
            message="Task retrieved",
        )

        assert result.success is True
        assert result.data["id"] == "task-123"
        assert result.message == "Task retrieved"
        assert result.error is None

    def test_error_result(self) -> None:
        """Create an error result."""
        error = CommandError(ErrorCode.TASK_NOT_FOUND, "Task not found")
        result = CommandResult.failure(error)

        assert result.success is False
        assert result.error == error
        assert result.data is None

    def test_result_to_dict(self) -> None:
        """Convert result to dictionary."""
        result = CommandResult.success(
            data={"tasks": []},
            message="Success",
        )

        d = result.to_dict()

        assert d["success"] is True
        assert d["data"] == {"tasks": []}
        assert d["message"] == "Success"

    def test_error_result_to_dict(self) -> None:
        """Convert error result to dictionary."""
        error = CommandError(ErrorCode.PERMISSION_DENIED, "Access denied")
        result = CommandResult.failure(error)

        d = result.to_dict()

        assert d["success"] is False
        assert d["error"]["code"] == "PERMISSION_DENIED"


class TestCommandHandler:
    """Tests for CommandHandler class."""

    def test_create_handler(self) -> None:
        """Create a command handler."""
        async def get_task(params: dict) -> dict:
            return {"id": params["task_id"]}

        handler = CommandHandler(
            name="get_task",
            handler=get_task,
            description="Get a task by ID",
        )

        assert handler.name == "get_task"
        assert handler.description == "Get a task by ID"

    @pytest.mark.asyncio
    async def test_invoke_handler(self) -> None:
        """Invoke a command handler."""
        async def get_task(params: dict) -> dict:
            return {"id": params["task_id"], "title": "Test"}

        handler = CommandHandler(name="get_task", handler=get_task)

        result = await handler.invoke({"task_id": "task-123"})

        assert result.success is True
        assert result.data["id"] == "task-123"

    @pytest.mark.asyncio
    async def test_handler_with_validation(self) -> None:
        """Handler with parameter validation."""
        from pydantic import BaseModel

        class CreateTaskParams(BaseModel):
            title: str
            priority: str = "medium"

        async def create_task(params: CreateTaskParams) -> dict:
            return {"id": "new", "title": params.title}

        handler = CommandHandler(
            name="create_task",
            handler=create_task,
            params_model=CreateTaskParams,
        )

        result = await handler.invoke({"title": "New Task"})

        assert result.success is True
        assert result.data["title"] == "New Task"

    @pytest.mark.asyncio
    async def test_handler_validation_error(self) -> None:
        """Handler with validation error."""
        from pydantic import BaseModel, ValidationError

        class GetTaskParams(BaseModel):
            task_id: str

        async def get_task(params: GetTaskParams) -> dict:
            return {"id": params.task_id}

        handler = CommandHandler(
            name="get_task",
            handler=get_task,
            params_model=GetTaskParams,
        )

        result = await handler.invoke({})  # Missing task_id

        assert result.success is False
        assert result.error is not None
        assert result.error.code == ErrorCode.VALIDATION_ERROR


class TestCommandRegistry:
    """Tests for CommandRegistry class."""

    def test_create_registry(self) -> None:
        """Create a command registry."""
        registry = CommandRegistry()

        assert registry is not None
        assert len(registry.commands) == 0

    def test_register_command(self) -> None:
        """Register a command."""
        registry = CommandRegistry()

        @registry.command("get_task")
        async def get_task(params: dict) -> dict:
            return {}

        assert "get_task" in registry.commands

    def test_register_command_with_description(self) -> None:
        """Register command with description."""
        registry = CommandRegistry()

        @registry.command("list_tasks", description="List all tasks")
        async def list_tasks(params: dict) -> list:
            return []

        handler = registry.get("list_tasks")
        assert handler is not None
        assert handler.description == "List all tasks"

    def test_get_command(self) -> None:
        """Get a registered command."""
        registry = CommandRegistry()

        @registry.command("get_task")
        async def get_task(params: dict) -> dict:
            return {"id": "test"}

        handler = registry.get("get_task")
        assert handler is not None
        assert handler.name == "get_task"

    def test_get_nonexistent_command(self) -> None:
        """Get a command that doesn't exist."""
        registry = CommandRegistry()

        handler = registry.get("unknown")
        assert handler is None

    def test_list_commands(self) -> None:
        """List all registered commands."""
        registry = CommandRegistry()

        @registry.command("get_task")
        async def get_task(params: dict) -> dict:
            return {}

        @registry.command("list_tasks")
        async def list_tasks(params: dict) -> list:
            return []

        commands = registry.list_commands()

        assert "get_task" in commands
        assert "list_tasks" in commands

    @pytest.mark.asyncio
    async def test_execute_command(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Execute a registered command."""
        registry = CommandRegistry()

        @registry.command("get_task")
        async def get_task(params: dict) -> dict:
            task_id = params.get("task_id")
            task = await mock_task_store.get(task_id)
            if not task:
                raise ValueError("Task not found")
            return task

        result = await registry.execute("get_task", {"task_id": "task-123"})

        assert result.success is True
        assert result.data["id"] == "task-123"

    @pytest.mark.asyncio
    async def test_execute_unknown_command(self) -> None:
        """Execute an unknown command."""
        registry = CommandRegistry()

        result = await registry.execute("unknown", {})

        assert result.success is False
        assert result.error is not None
        assert "unknown" in result.error.message.lower()

    @pytest.mark.asyncio
    async def test_execute_with_error(self) -> None:
        """Execute command that raises error."""
        registry = CommandRegistry()

        @registry.command("failing_command")
        async def failing_command(params: dict) -> dict:
            raise RuntimeError("Something went wrong")

        result = await registry.execute("failing_command", {})

        assert result.success is False
        assert result.error is not None
        assert result.error.code == ErrorCode.OPERATION_FAILED

    def test_get_command_info(self) -> None:
        """Get command information."""
        registry = CommandRegistry()

        @registry.command("create_task", description="Create a new task")
        async def create_task(params: dict) -> dict:
            """Create a new task.

            Args:
                title: Task title
                priority: Task priority (optional)
            """
            return {}

        info = registry.get_command_info("create_task")

        assert info is not None
        assert info["name"] == "create_task"
        assert info["description"] == "Create a new task"

    def test_get_registry_info(self) -> None:
        """Get registry information."""
        registry = CommandRegistry(name="TaskAPI", version="1.0.0")

        @registry.command("get_task")
        async def get_task(params: dict) -> dict:
            return {}

        info = registry.get_registry_info()

        assert info["name"] == "TaskAPI"
        assert info["version"] == "1.0.0"
        assert "get_task" in info["commands"]


class TestBuiltinCommands:
    """Tests for built-in commands."""

    @pytest.mark.asyncio
    async def test_ping_command(self) -> None:
        """Test ping command."""
        registry = CommandRegistry()
        registry.register_builtin_commands()

        result = await registry.execute("ping", {})

        assert result.success is True
        assert "pong" in result.data

    @pytest.mark.asyncio
    async def test_help_command(self) -> None:
        """Test help command."""
        registry = CommandRegistry()
        registry.register_builtin_commands()

        @registry.command("get_task", description="Get task")
        async def get_task(params: dict) -> dict:
            return {}

        result = await registry.execute("help", {})

        assert result.success is True
        assert "commands" in result.data

    @pytest.mark.asyncio
    async def test_version_command(self) -> None:
        """Test version command."""
        registry = CommandRegistry(name="TaskAPI", version="1.0.0")
        registry.register_builtin_commands()

        result = await registry.execute("version", {})

        assert result.success is True
        assert result.data["name"] == "TaskAPI"
        assert result.data["version"] == "1.0.0"
