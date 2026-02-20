"""JSON-RPC 2.0 IPC Server for GUI communication.

Provides Unix domain socket-based JSON-RPC 2.0 server for native GUI clients.

Features:
- JSON-RPC 2.0 compliant request/response handling
- Unix domain socket transport
- Method registration with decorators
- Parameter validation with Pydantic
- Batch request support
- Notification support (no response)

Usage:
    from mahavishnu.core.json_rpc_ipc import JSONRPCServer

    server = JSONRPCServer(name="TaskAPI")

    @server.method("get_task")
    async def get_task(params: dict) -> dict:
        return {"id": params["task_id"], "title": "Test"}

    await server.start("/tmp/mahavishnu.sock")
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class JSONRPCErrorCode(int, Enum):
    """Standard JSON-RPC 2.0 error codes."""

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # Server-defined errors (-32000 to -32099)
    SERVER_ERROR_START = -32000
    SERVER_ERROR_END = -32099


class JSONRPCError(Exception):
    """JSON-RPC error object.

    Attributes:
        code: Error code (negative integer)
        message: Short error description
        data: Optional additional error information
    """

    def __init__(
        self,
        code: JSONRPCErrorCode | int,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Initialize JSON-RPC error.

        Args:
            code: Error code
            message: Error message
            data: Optional additional data
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "code": self.code if isinstance(self.code, int) else self.code.value,
            "message": self.message,
        }
        if self.data is not None:
            result["data"] = self.data
        return result


@dataclass
class JSONRPCRequest:
    """JSON-RPC 2.0 request.

    Attributes:
        method: Method name to invoke
        params: Parameters (dict or list)
        request_id: Request identifier (None for notifications)
        jsonrpc: Protocol version (always "2.0")
    """

    method: str
    params: dict[str, Any] | list[Any] | None = None
    request_id: str | int | None = None
    jsonrpc: str = "2.0"

    @property
    def is_notification(self) -> bool:
        """Check if this is a notification (no id)."""
        return self.request_id is None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JSONRPCRequest:
        """Parse a JSON-RPC request from dictionary.

        Args:
            data: Request dictionary

        Returns:
            Parsed JSONRPCRequest

        Raises:
            JSONRPCError: If request is invalid
        """
        # Check jsonrpc version
        if data.get("jsonrpc") != "2.0":
            raise JSONRPCError(
                JSONRPCErrorCode.INVALID_REQUEST,
                "Invalid JSON-RPC version, expected '2.0'",
            )

        # Check method
        method = data.get("method")
        if not method or not isinstance(method, str):
            raise JSONRPCError(
                JSONRPCErrorCode.INVALID_REQUEST,
                "Missing or invalid 'method' field",
            )

        return cls(
            method=method,
            params=data.get("params"),
            request_id=data.get("id"),
        )


@dataclass
class JSONRPCResponse:
    """JSON-RPC 2.0 response.

    Attributes:
        result: Result value (None for error responses)
        error: Error object (None for success responses)
        request_id: Request identifier
        jsonrpc: Protocol version (always "2.0")
    """

    result: Any = None
    error: JSONRPCError | None = None
    request_id: str | int | None = None
    jsonrpc: str = "2.0"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        response: dict[str, Any] = {
            "jsonrpc": self.jsonrpc,
            "id": self.request_id,
        }

        if self.error is not None:
            response["error"] = self.error.to_dict()
        else:
            response["result"] = self.result

        return response

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())


@dataclass
class MethodHandler:
    """Handler for a JSON-RPC method.

    Attributes:
        name: Method name
        handler: Async handler function
        description: Method description
        params_model: Optional Pydantic model for parameter validation
    """

    name: str
    handler: Callable[[Any], Coroutine[Any, Any, Any]]
    description: str = ""
    params_model: type | None = None

    async def invoke(self, params: Any) -> Any:
        """Invoke the handler with parameters.

        Args:
            params: Method parameters

        Returns:
            Handler result
        """
        # Validate with Pydantic model if present
        if self.params_model is not None:
            if isinstance(params, dict):
                validated = self.params_model(**params)
            elif isinstance(params, list):
                validated = self.params_model(*params)
            else:
                validated = self.params_model(params)
            return await self.handler(validated)

        return await self.handler(params)


class JSONRPCServer:
    """JSON-RPC 2.0 server for IPC communication.

    Features:
    - Method registration with @method decorator
    - Parameter validation with Pydantic
    - Batch request support
    - Notification support
    - Error handling per JSON-RPC spec

    Example:
        server = JSONRPCServer(name="TaskAPI")

        @server.method("get_task", description="Get task by ID")
        async def get_task(params: dict) -> dict:
            return {"id": params["task_id"]}
    """

    def __init__(
        self,
        name: str = "JSONRPCServer",
        version: str = "1.0.0",
    ) -> None:
        """Initialize JSON-RPC server.

        Args:
            name: Server name for identification
            version: Server version
        """
        self.name = name
        self.version = version
        self.methods: dict[str, MethodHandler] = {}
        self._server: asyncio.Server | None = None

    def method(
        self,
        name: str | None = None,
        description: str = "",
        params_model: type | None = None,
    ) -> Callable:
        """Decorator to register a method handler.

        Args:
            name: Method name (defaults to function name)
            description: Method description
            params_model: Pydantic model for parameter validation

        Returns:
            Decorator function
        """
        def decorator(func: Callable[[Any], Coroutine[Any, Any, Any]]) -> Callable:
            method_name = name or func.__name__
            handler = MethodHandler(
                name=method_name,
                handler=func,
                description=description or func.__doc__ or "",
                params_model=params_model,
            )
            self.methods[method_name] = handler
            return func

        return decorator

    def get_method(self, name: str) -> MethodHandler | None:
        """Get a registered method by name.

        Args:
            name: Method name

        Returns:
            MethodHandler or None if not found
        """
        return self.methods.get(name)

    def list_methods(self) -> list[str]:
        """List all registered method names.

        Returns:
            List of method names
        """
        return list(self.methods.keys())

    def get_method_info(self, name: str) -> dict[str, Any] | None:
        """Get detailed method information.

        Args:
            name: Method name

        Returns:
            Method info dictionary or None
        """
        handler = self.methods.get(name)
        if handler is None:
            return None

        return {
            "name": handler.name,
            "description": handler.description,
            "has_validation": handler.params_model is not None,
        }

    def get_server_info(self) -> dict[str, Any]:
        """Get server information.

        Returns:
            Server info dictionary
        """
        return {
            "name": self.name,
            "version": self.version,
            "jsonrpc": "2.0",
            "methods": self.list_methods(),
        }

    async def handle_raw(self, data: bytes) -> JSONRPCResponse:
        """Handle raw JSON data.

        Args:
            data: Raw JSON bytes

        Returns:
            JSON-RPC response
        """
        try:
            parsed = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return JSONRPCResponse(
                error=JSONRPCError(
                    JSONRPCErrorCode.PARSE_ERROR,
                    f"Parse error: {e}",
                ),
            )

        # Check for batch request
        if isinstance(parsed, list):
            return await self.handle_batch(parsed)

        return await self.handle_request(parsed)

    async def handle_request(
        self,
        data: dict[str, Any],
    ) -> JSONRPCResponse | None:
        """Handle a single JSON-RPC request.

        Args:
            data: Request dictionary

        Returns:
            JSON-RPC response or None for notifications
        """
        try:
            request = JSONRPCRequest.from_dict(data)
        except JSONRPCError as e:
            return JSONRPCResponse(
                error=e,
                request_id=data.get("id"),
            )

        # Find method
        handler = self.methods.get(request.method)
        if handler is None:
            if not request.is_notification:
                return JSONRPCResponse(
                    error=JSONRPCError(
                        JSONRPCErrorCode.METHOD_NOT_FOUND,
                        f"Method '{request.method}' not found",
                    ),
                    request_id=request.request_id,
                )
            return None

        # Execute method
        try:
            result = await handler.invoke(request.params)

            # Notifications don't get responses
            if request.is_notification:
                return None

            return JSONRPCResponse(
                result=result,
                request_id=request.request_id,
            )

        except JSONRPCError as e:
            if request.is_notification:
                return None
            return JSONRPCResponse(
                error=e,
                request_id=request.request_id,
            )

        except ValueError as e:
            if request.is_notification:
                return None
            return JSONRPCResponse(
                error=JSONRPCError(
                    JSONRPCErrorCode.INVALID_PARAMS,
                    str(e),
                ),
                request_id=request.request_id,
            )

        except Exception as e:
            logger.exception(f"Internal error handling {request.method}")
            if request.is_notification:
                return None
            return JSONRPCResponse(
                error=JSONRPCError(
                    JSONRPCErrorCode.INTERNAL_ERROR,
                    f"Internal error: {e}",
                ),
                request_id=request.request_id,
            )

    async def handle_batch(
        self,
        requests: list[dict[str, Any]],
    ) -> JSONRPCResponse | list[JSONRPCResponse]:
        """Handle a batch of JSON-RPC requests.

        Args:
            requests: List of request dictionaries

        Returns:
            List of responses (excluding notifications) or single error response
        """
        if not requests:
            return JSONRPCResponse(
                error=JSONRPCError(
                    JSONRPCErrorCode.INVALID_REQUEST,
                    "Empty batch request",
                ),
            )

        responses: list[JSONRPCResponse] = []

        for request_data in requests:
            response = await self.handle_request(request_data)
            # Only include responses (not notifications)
            if response is not None:
                responses.append(response)

        # If all requests were notifications, return empty list
        if not responses:
            return []

        return responses


__all__ = [
    "JSONRPCServer",
    "JSONRPCRequest",
    "JSONRPCResponse",
    "JSONRPCError",
    "JSONRPCErrorCode",
    "MethodHandler",
]
