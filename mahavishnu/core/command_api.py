"""Command Execution API - RPC method handlers for GUI clients.

Provides command registry and handlers for task operations:

- CommandRegistry for registering handlers
- Command types for task CRUD operations
- Parameter validation with Pydantic
- Error handling with error codes

Usage:
    from mahavishnu.core.command_api import CommandRegistry

    registry = CommandRegistry(name="TaskAPI")

    @registry.command("get_task", description="Get task by ID")
    async def get_task(params: dict) -> dict:
        return {"id": params["task_id"], "title": "Test"}

    result = await registry.execute("get_task", {"task_id": "task-123"})
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class ErrorCode(str, Enum):
    """Error codes for command results."""

    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    INVALID_PARAMETER = "INVALID_PARAMETER"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    OPERATION_FAILED = "OPERATION_FAILED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    RATE_LIMITED = "RATE_LIMITED"


@dataclass
class CommandError:
    """Error information for failed commands.

    Attributes:
        code: Error code
        message: Human-readable error message
        details: Optional additional error details
    """

    code: ErrorCode
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result: dict[str, Any] = {
            "code": self.code.value,
            "message": self.message,
        }
        if self.details:
            result["details"] = self.details
        return result


@dataclass
class CommandResult:
    """Result of a command execution.

    Attributes:
        success: Whether command succeeded
        data: Result data (None on failure)
        message: Result message
        error: Error information (None on success)
        timestamp: When result was generated
    """

    success: bool
    data: Any = None
    message: str = ""
    error: CommandError | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def success(
        cls,
        data: Any = None,
        message: str = "Success",
    ) -> CommandResult:
        """Create a success result.

        Args:
            data: Result data
            message: Success message

        Returns:
            Success CommandResult
        """
        return cls(
            success=True,
            data=data,
            message=message,
        )

    @classmethod
    def failure(
        cls,
        error: CommandError,
    ) -> CommandResult:
        """Create a failure result.

        Args:
            error: Error information

        Returns:
            Failure CommandResult
        """
        return cls(
            success=False,
            error=error,
            message=error.message,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result: dict[str, Any] = {
            "success": self.success,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.success:
            result["data"] = self.data
        else:
            result["error"] = self.error.to_dict() if self.error else None
        return result


@dataclass
class CommandHandler:
    """Handler for a command.

    Attributes:
        name: Command name
        handler: Async handler function
        description: Command description
        params_model: Optional Pydantic model for parameter validation
    """

    name: str
    handler: Callable[[Any], Coroutine[Any, Any, Any]]
    description: str = ""
    params_model: type | None = None

    async def invoke(self, params: Any) -> CommandResult:
        """Invoke the command handler.

        Args:
            params: Command parameters

        Returns:
            CommandResult
        """
        try:
            # Validate with Pydantic model if present
            if self.params_model is not None:
                if isinstance(params, dict):
                    validated = self.params_model(**params)
                elif isinstance(params, list):
                    validated = self.params_model(*params)
                else:
                    validated = self.params_model(params)
                result = await self.handler(validated)
            else:
                result = await self.handler(params)

            # Handle different return types
            if isinstance(result, CommandResult):
                return result
            return CommandResult.success(data=result)

        except Exception as e:
            # Handle validation errors
            error_name = type(e).__name__
            if "Validation" in error_name or "ValidationError" in error_name:
                return CommandResult.failure(
                    CommandError(
                        code=ErrorCode.VALIDATION_ERROR,
                        message=str(e),
                        details={"exception_type": error_name},
                    )
                )

            # Handle other errors
            logger.error(f"Command {self.name} failed: {e}")
            return CommandResult.failure(
                CommandError(
                    code=ErrorCode.OPERATION_FAILED,
                    message=str(e),
                    details={"exception_type": error_name},
                )
            )


class CommandRegistry:
    """Registry for command handlers.

    Features:
    - Register commands with decorators
    - Parameter validation with Pydantic
    - Error handling with error codes
    - Built-in commands (ping, help, version)

    Example:
        registry = CommandRegistry(name="TaskAPI")

        @registry.command("get_task", description="Get task by ID")
        async def get_task(params: dict) -> dict:
            return {"id": params["task_id"]}
    """

    def __init__(
        self,
        name: str = "CommandRegistry",
        version: str = "1.0.0",
    ) -> None:
        """Initialize command registry.

        Args:
            name: Registry name
            version: Registry version
        """
        self.name = name
        self.version = version
        self.commands: dict[str, CommandHandler] = {}

    def command(
        self,
        name: str | None = None,
        description: str = "",
        params_model: type | None = None,
    ) -> Callable:
        """Decorator to register a command handler.

        Args:
            name: Command name (defaults to function name)
            description: Command description
            params_model: Pydantic model for parameter validation

        Returns:
            Decorator function
        """
        def decorator(func: Callable[[Any], Coroutine[Any, Any, Any]]) -> Callable:
            command_name = name or func.__name__
            handler = CommandHandler(
                name=command_name,
                handler=func,
                description=description or func.__doc__ or "",
                params_model=params_model,
            )
            self.commands[command_name] = handler
            return func

        return decorator

    def get(self, name: str) -> CommandHandler | None:
        """Get a command handler by name.

        Args:
            name: Command name

        Returns:
            CommandHandler or None if not found
        """
        return self.commands.get(name)

    def list_commands(self) -> list[str]:
        """List all registered commands.

        Returns:
            List of command names
        """
        return list(self.commands.keys())

    def get_command_info(self, name: str) -> dict[str, Any] | None:
        """Get command information.

        Args:
            name: Command name

        Returns:
            Command info dictionary or None
        """
        handler = self.commands.get(name)
        if handler is None:
            return None

        return {
            "name": handler.name,
            "description": handler.description,
            "has_validation": handler.params_model is not None,
        }

    def get_registry_info(self) -> dict[str, Any]:
        """Get registry information.

        Returns:
            Registry info dictionary
        """
        return {
            "name": self.name,
            "version": self.version,
            "commands": self.list_commands(),
            "command_count": len(self.commands),
        }

    async def execute(
        self,
        name: str,
        params: Any,
    ) -> CommandResult:
        """Execute a command.

        Args:
            name: Command name
            params: Command parameters

        Returns:
            CommandResult
        """
        handler = self.commands.get(name)
        if handler is None:
            return CommandResult.failure(
                CommandError(
                    code=ErrorCode.NOT_IMPLEMENTED,
                    message=f"Unknown command: {name}",
                    details={"available_commands": self.list_commands()},
                )
            )

        return await handler.invoke(params)

    def register_builtin_commands(self) -> None:
        """Register built-in commands (ping, help, version)."""

        @self.command("ping", description="Ping the server")
        async def ping(params: dict) -> dict[str, Any]:
            """Ping command - returns pong."""
            return {"pong": True, "timestamp": datetime.now(UTC).isoformat()}

        @self.command("help", description="List available commands")
        async def help(params: dict) -> dict[str, Any]:
            """Help command - lists all commands."""
            commands = []
            for name, handler in self.commands.items():
                commands.append({
                    "name": name,
                    "description": handler.description,
                })
            return {
                "commands": commands,
                "registry": self.get_registry_info(),
            }

        @self.command("version", description="Get server version")
        async def version(params: dict) -> dict[str, Any]:
            """Version command - returns registry info."""
            return self.get_registry_info()


__all__ = [
    "CommandRegistry",
    "CommandHandler",
    "CommandResult",
    "CommandError",
    "ErrorCode",
]
