"""Tests for JSON-RPC IPC Server - Unix socket communication for GUI."""

import pytest
import asyncio
import json
from datetime import datetime, UTC
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Any

from mahavishnu.core.json_rpc_ipc import (
    JSONRPCServer,
    JSONRPCRequest,
    JSONRPCResponse,
    JSONRPCError,
    JSONRPCErrorCode,
    MethodHandler,
)


@pytest.fixture
def sample_request() -> dict[str, Any]:
    """Create a sample JSON-RPC request."""
    return {
        "jsonrpc": "2.0",
        "method": "get_task",
        "params": {"task_id": "task-123"},
        "id": 1,
    }


@pytest.fixture
def sample_notification() -> dict[str, Any]:
    """Create a sample JSON-RPC notification (no id)."""
    return {
        "jsonrpc": "2.0",
        "method": "task_updated",
        "params": {"task_id": "task-123", "status": "completed"},
    }


@pytest.fixture
def sample_batch_request() -> list[dict[str, Any]]:
    """Create a sample batch JSON-RPC request."""
    return [
        {"jsonrpc": "2.0", "method": "get_task", "params": {"task_id": "task-1"}, "id": 1},
        {"jsonrpc": "2.0", "method": "list_tasks", "params": {}, "id": 2},
    ]


class TestJSONRPCErrorCode:
    """Tests for JSONRPCErrorCode enum."""

    def test_error_codes(self) -> None:
        """Test standard JSON-RPC error codes."""
        assert JSONRPCErrorCode.PARSE_ERROR.value == -32700
        assert JSONRPCErrorCode.INVALID_REQUEST.value == -32600
        assert JSONRPCErrorCode.METHOD_NOT_FOUND.value == -32601
        assert JSONRPCErrorCode.INVALID_PARAMS.value == -32602
        assert JSONRPCErrorCode.INTERNAL_ERROR.value == -32603


class TestJSONRPCError:
    """Tests for JSONRPCError class."""

    def test_create_error(self) -> None:
        """Create a JSON-RPC error."""
        error = JSONRPCError(
            code=JSONRPCErrorCode.INVALID_PARAMS,
            message="Invalid parameter",
            data={"field": "task_id"},
        )

        assert error.code == JSONRPCErrorCode.INVALID_PARAMS
        assert error.message == "Invalid parameter"
        assert error.data == {"field": "task_id"}

    def test_error_to_dict(self) -> None:
        """Convert error to dictionary."""
        error = JSONRPCError(
            code=JSONRPCErrorCode.METHOD_NOT_FOUND,
            message="Method not found",
        )

        d = error.to_dict()

        assert d["code"] == -32601
        assert d["message"] == "Method not found"
        assert "data" not in d

    def test_error_to_dict_with_data(self) -> None:
        """Convert error with data to dictionary."""
        error = JSONRPCError(
            code=JSONRPCErrorCode.INTERNAL_ERROR,
            message="Internal error",
            data={"details": "Something went wrong"},
        )

        d = error.to_dict()

        assert "data" in d
        assert d["data"]["details"] == "Something went wrong"


class TestJSONRPCRequest:
    """Tests for JSONRPCRequest class."""

    def test_create_request(self) -> None:
        """Create a JSON-RPC request."""
        request = JSONRPCRequest(
            method="get_task",
            params={"task_id": "task-123"},
            request_id=1,
        )

        assert request.method == "get_task"
        assert request.params == {"task_id": "task-123"}
        assert request.request_id == 1
        assert request.jsonrpc == "2.0"

    def test_create_notification(self) -> None:
        """Create a JSON-RPC notification (no id)."""
        request = JSONRPCRequest(
            method="task_updated",
            params={"task_id": "task-123"},
        )

        assert request.method == "task_updated"
        assert request.request_id is None
        assert request.is_notification is True

    def test_parse_valid_request(
        self,
        sample_request: dict[str, Any],
    ) -> None:
        """Parse a valid JSON-RPC request."""
        request = JSONRPCRequest.from_dict(sample_request)

        assert request is not None
        assert request.method == "get_task"
        assert request.params == {"task_id": "task-123"}
        assert request.request_id == 1

    def test_parse_notification(
        self,
        sample_notification: dict[str, Any],
    ) -> None:
        """Parse a JSON-RPC notification."""
        request = JSONRPCRequest.from_dict(sample_notification)

        assert request is not None
        assert request.method == "task_updated"
        assert request.is_notification is True

    def test_parse_invalid_jsonrpc_version(self) -> None:
        """Parse request with invalid jsonrpc version."""
        invalid = {
            "jsonrpc": "1.0",
            "method": "test",
            "id": 1,
        }

        # from_dict raises JSONRPCError (which is caught by server)
        # For direct parsing, we check the error in response
        server = JSONRPCServer()
        response = asyncio.get_event_loop().run_until_complete(
            server.handle_request(invalid)
        )

        assert response is not None
        assert response.error is not None
        assert response.error.code == JSONRPCErrorCode.INVALID_REQUEST

    def test_parse_missing_method(self) -> None:
        """Parse request with missing method."""
        invalid = {
            "jsonrpc": "2.0",
            "id": 1,
        }

        # from_dict raises JSONRPCError (which is caught by server)
        # For direct parsing, we check the error in response
        server = JSONRPCServer()
        response = asyncio.get_event_loop().run_until_complete(
            server.handle_request(invalid)
        )

        assert response is not None
        assert response.error is not None
        assert response.error.code == JSONRPCErrorCode.INVALID_REQUEST

    def test_parse_by_name_params(self) -> None:
        """Parse request with named parameters."""
        data = {
            "jsonrpc": "2.0",
            "method": "create_task",
            "params": {"title": "Test", "priority": "high"},
            "id": 1,
        }

        request = JSONRPCRequest.from_dict(data)

        assert request.params == {"title": "Test", "priority": "high"}

    def test_parse_positional_params(self) -> None:
        """Parse request with positional parameters."""
        data = {
            "jsonrpc": "2.0",
            "method": "get_task",
            "params": ["task-123"],
            "id": 1,
        }

        request = JSONRPCRequest.from_dict(data)

        assert request.params == ["task-123"]


class TestJSONRPCResponse:
    """Tests for JSONRPCResponse class."""

    def test_create_success_response(self) -> None:
        """Create a success response."""
        response = JSONRPCResponse(
            result={"id": "task-123", "title": "Test"},
            request_id=1,
        )

        assert response.result == {"id": "task-123", "title": "Test"}
        assert response.error is None
        assert response.request_id == 1

    def test_create_error_response(self) -> None:
        """Create an error response."""
        error = JSONRPCError(JSONRPCErrorCode.METHOD_NOT_FOUND, "Unknown method")
        response = JSONRPCResponse(
            error=error,
            request_id=1,
        )

        assert response.result is None
        assert response.error == error
        assert response.request_id == 1

    def test_success_response_to_dict(self) -> None:
        """Convert success response to dictionary."""
        response = JSONRPCResponse(
            result={"status": "ok"},
            request_id=1,
        )

        d = response.to_dict()

        assert d["jsonrpc"] == "2.0"
        assert d["result"] == {"status": "ok"}
        assert d["id"] == 1
        assert "error" not in d

    def test_error_response_to_dict(self) -> None:
        """Convert error response to dictionary."""
        error = JSONRPCError(JSONRPCErrorCode.INTERNAL_ERROR, "Error")
        response = JSONRPCResponse(error=error, request_id=1)

        d = response.to_dict()

        assert d["jsonrpc"] == "2.0"
        assert "result" not in d
        assert d["error"]["code"] == -32603
        assert d["id"] == 1

    def test_response_to_json(self) -> None:
        """Convert response to JSON string."""
        response = JSONRPCResponse(
            result={"task_id": "task-123"},
            request_id=1,
        )

        json_str = response.to_json()

        parsed = json.loads(json_str)
        assert parsed["jsonrpc"] == "2.0"
        assert parsed["result"]["task_id"] == "task-123"


class TestMethodHandler:
    """Tests for MethodHandler class."""

    def test_create_handler(self) -> None:
        """Create a method handler."""
        async def get_task(params: dict[str, Any]) -> dict[str, Any]:
            return {"id": params["task_id"]}

        handler = MethodHandler(
            name="get_task",
            handler=get_task,
            description="Get a task by ID",
        )

        assert handler.name == "get_task"
        assert handler.description == "Get a task by ID"

    @pytest.mark.asyncio
    async def test_invoke_handler(self) -> None:
        """Invoke a method handler."""
        async def get_task(params: dict[str, Any]) -> dict[str, Any]:
            return {"id": params["task_id"], "title": "Test"}

        handler = MethodHandler(name="get_task", handler=get_task)

        result = await handler.invoke({"task_id": "task-123"})

        assert result["id"] == "task-123"
        assert result["title"] == "Test"

    @pytest.mark.asyncio
    async def test_handler_with_validation(self) -> None:
        """Handler with parameter validation."""
        from pydantic import BaseModel

        class GetTaskParams(BaseModel):
            task_id: str

        async def get_task(params: GetTaskParams) -> dict[str, Any]:
            return {"id": params.task_id}

        handler = MethodHandler(
            name="get_task",
            handler=get_task,
            params_model=GetTaskParams,
        )

        result = await handler.invoke({"task_id": "task-123"})

        assert result["id"] == "task-123"


class TestJSONRPCServer:
    """Tests for JSONRPCServer class."""

    def test_create_server(self) -> None:
        """Create a JSON-RPC server."""
        server = JSONRPCServer()

        assert server is not None
        assert len(server.methods) == 0

    def test_register_method(self) -> None:
        """Register a method handler."""
        server = JSONRPCServer()

        @server.method("get_task")
        async def get_task(params: dict[str, Any]) -> dict[str, Any]:
            return {"id": params["task_id"]}

        assert "get_task" in server.methods

    def test_register_method_decorator(self) -> None:
        """Register method using decorator."""
        server = JSONRPCServer()

        @server.method("list_tasks")
        async def list_tasks(params: dict[str, Any]) -> list[dict[str, Any]]:
            return []

        assert "list_tasks" in server.methods

    def test_get_method(self) -> None:
        """Get a registered method."""
        server = JSONRPCServer()

        @server.method("get_task")
        async def get_task(params: dict[str, Any]) -> dict[str, Any]:
            return {}

        handler = server.get_method("get_task")
        assert handler is not None
        assert handler.name == "get_task"

    def test_get_nonexistent_method(self) -> None:
        """Get a method that doesn't exist."""
        server = JSONRPCServer()

        handler = server.get_method("unknown_method")
        assert handler is None

    def test_list_methods(self) -> None:
        """List all registered methods."""
        server = JSONRPCServer()

        @server.method("get_task")
        async def get_task(params: dict[str, Any]) -> dict[str, Any]:
            return {}

        @server.method("list_tasks")
        async def list_tasks(params: dict[str, Any]) -> list[dict[str, Any]]:
            return []

        methods = server.list_methods()

        assert "get_task" in methods
        assert "list_tasks" in methods

    @pytest.mark.asyncio
    async def test_handle_request(
        self,
        sample_request: dict[str, Any],
    ) -> None:
        """Handle a JSON-RPC request."""
        server = JSONRPCServer()

        @server.method("get_task")
        async def get_task(params: dict[str, Any]) -> dict[str, Any]:
            return {"id": params["task_id"], "title": "Test Task"}

        response = await server.handle_request(sample_request)

        assert response is not None
        assert response.result["id"] == "task-123"
        assert response.request_id == 1

    @pytest.mark.asyncio
    async def test_handle_notification(
        self,
        sample_notification: dict[str, Any],
    ) -> None:
        """Handle a JSON-RPC notification (no response)."""
        server = JSONRPCServer()

        received = []

        @server.method("task_updated")
        async def task_updated(params: dict[str, Any]) -> None:
            received.append(params)

        response = await server.handle_request(sample_notification)

        # Notifications don't get responses
        assert response is None
        assert len(received) == 1
        assert received[0]["task_id"] == "task-123"

    @pytest.mark.asyncio
    async def test_handle_unknown_method(
        self,
        sample_request: dict[str, Any],
    ) -> None:
        """Handle request for unknown method."""
        server = JSONRPCServer()

        response = await server.handle_request(sample_request)

        assert response is not None
        assert response.error is not None
        assert response.error.code == JSONRPCErrorCode.METHOD_NOT_FOUND

    @pytest.mark.asyncio
    async def test_handle_invalid_params(self) -> None:
        """Handle request with invalid parameters."""
        server = JSONRPCServer()

        @server.method("get_task")
        async def get_task(params: dict[str, Any]) -> dict[str, Any]:
            if "task_id" not in params:
                raise ValueError("Missing task_id")
            return {"id": params["task_id"]}

        request = {
            "jsonrpc": "2.0",
            "method": "get_task",
            "params": {},  # Missing task_id
            "id": 1,
        }

        response = await server.handle_request(request)

        assert response.error is not None
        assert response.error.code == JSONRPCErrorCode.INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_handle_batch_request(
        self,
        sample_batch_request: list[dict[str, Any]],
    ) -> None:
        """Handle a batch JSON-RPC request."""
        server = JSONRPCServer()

        @server.method("get_task")
        async def get_task(params: dict[str, Any]) -> dict[str, Any]:
            return {"id": params["task_id"]}

        @server.method("list_tasks")
        async def list_tasks(params: dict[str, Any]) -> list[dict[str, Any]]:
            return [{"id": "task-1"}, {"id": "task-2"}]

        responses = await server.handle_batch(sample_batch_request)

        assert len(responses) == 2
        assert responses[0].result["id"] == "task-1"
        assert len(responses[1].result) == 2

    @pytest.mark.asyncio
    async def test_handle_batch_with_notifications(self) -> None:
        """Handle batch with notifications (excluded from response)."""
        server = JSONRPCServer()

        @server.method("get_task")
        async def get_task(params: dict[str, Any]) -> dict[str, Any]:
            return {"id": params.get("task_id", "unknown")}

        @server.method("log_event")
        async def log_event(params: dict[str, Any]) -> None:
            pass

        batch = [
            {"jsonrpc": "2.0", "method": "get_task", "params": {"task_id": "t1"}, "id": 1},
            {"jsonrpc": "2.0", "method": "log_event", "params": {"event": "test"}},  # No id = notification
            {"jsonrpc": "2.0", "method": "get_task", "params": {"task_id": "t2"}, "id": 2},
        ]

        responses = await server.handle_batch(batch)

        # Only 2 responses (notifications excluded)
        assert len(responses) == 2
        assert responses[0].request_id == 1
        assert responses[1].request_id == 2

    @pytest.mark.asyncio
    async def test_handle_empty_batch(self) -> None:
        """Handle empty batch request."""
        server = JSONRPCServer()

        response = await server.handle_batch([])

        assert response is not None
        assert response.error is not None
        assert response.error.code == JSONRPCErrorCode.INVALID_REQUEST

    @pytest.mark.asyncio
    async def test_parse_error(self) -> None:
        """Handle invalid JSON (parse error)."""
        server = JSONRPCServer()

        response = await server.handle_raw(b"invalid json{")

        assert response.error.code == JSONRPCErrorCode.PARSE_ERROR

    @pytest.mark.asyncio
    async def test_internal_error(self) -> None:
        """Handle internal server error."""
        server = JSONRPCServer()

        @server.method("failing_method")
        async def failing_method(params: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("Something went wrong")

        request = {
            "jsonrpc": "2.0",
            "method": "failing_method",
            "params": {},
            "id": 1,
        }

        response = await server.handle_request(request)

        assert response.error is not None
        assert response.error.code == JSONRPCErrorCode.INTERNAL_ERROR

    def test_method_info(self) -> None:
        """Get method information."""
        server = JSONRPCServer()

        @server.method("get_task", description="Get a task by ID")
        async def get_task(params: dict[str, Any]) -> dict[str, Any]:
            """Get a task by ID.

            Args:
                params: Must contain task_id

            Returns:
                Task dictionary
            """
            return {}

        info = server.get_method_info("get_task")

        assert info is not None
        assert info["name"] == "get_task"
        assert info["description"] == "Get a task by ID"

    def test_server_info(self) -> None:
        """Get server information."""
        server = JSONRPCServer(name="TaskAPI", version="1.0.0")

        @server.method("get_task")
        async def get_task(params: dict[str, Any]) -> dict[str, Any]:
            return {}

        info = server.get_server_info()

        assert info["name"] == "TaskAPI"
        assert info["version"] == "1.0.0"
        assert "get_task" in info["methods"]
