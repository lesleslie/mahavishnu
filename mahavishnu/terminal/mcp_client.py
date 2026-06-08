"""MCP client for communicating with external MCP servers."""

import asyncio
import json
from logging import getLogger
from typing import Any

logger = getLogger(__name__)


class StdioMCPClient:
    """MCP client that communicates with stdio-based MCP servers.

    This client can communicate with MCP servers that use stdio transport,
    such as mcpretentious when configured to run via uvx.

    Example:
        >>> client = StdioMCPClient("uvx", ["--from", "mcpretentious", "mcpretentious"])
        >>> await client.start()
        >>> result = await client.call_tool("mcpretentious-open", {"columns": 80, "rows": 24})
        >>> await client.stop()
    """

    def __init__(self, command: str, args: list[str]):
        """Initialize stdio MCP client.

        Args:
            command: Command to run (e.g., "uvx")
            args: Arguments for the command
        """
        self.command = command
        self.args = args
        self.process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._pending_requests: dict[int, asyncio.Future] = {}
        # Responses that arrived before their request was registered. We
        # buffer them so the next ``call_tool`` with the matching id can
        # pick them up instead of waiting for a response that already came
        # and went.
        self._response_buffer: dict[int, dict[str, Any]] = {}

    async def start(self) -> None:
        """Start the MCP server process.

        Raises:
            RuntimeError: If process fails to start
        """
        try:
            self.process = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            logger.info(f"Started MCP server process: {self.command} {' '.join(self.args)}")

            # Start reader task
            asyncio.create_task(self._read_stdout())

        except Exception as e:
            raise RuntimeError(f"Failed to start MCP server: {e}") from e

    async def stop(self) -> None:
        """Stop the MCP server process."""
        if self.process:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except TimeoutError:
                self.process.kill()
                try:
                    await self.process.wait()
                except TimeoutError:
                    # ``kill`` did not unblock the process; surface but do
                    # not raise — the caller is already on the shutdown path.
                    logger.warning("Process did not exit after kill()")
            logger.info("Stopped MCP server process")

    async def _read_stdout(self) -> None:
        """Read stdout from MCP server process."""
        if not self.process:
            return

        try:
            while True:
                line = await self.process.stdout.readline()  # type: ignore[union-attr]
                if not line:
                    break

                try:
                    response = json.loads(line.decode().strip())

                    # Handle responses to pending requests
                    if "id" in response:
                        req_id = response["id"]
                        if req_id in self._pending_requests:
                            future = self._pending_requests.pop(req_id)
                            future.set_result(response)
                        else:
                            # No pending future for this id yet — the
                            # response arrived before the matching
                            # ``call_tool`` registered. Buffer it so the
                            # request can pick it up on its next yield.
                            self._response_buffer[req_id] = response

                except json.JSONDecodeError:
                    logger.debug(f"Non-JSON output: {line.decode().strip()}")

        except Exception as e:
            logger.error(f"Error reading stdout: {e}")

    def _build_request(
        self, tool_name: str, params: dict[str, Any], request_id: int
    ) -> dict[str, Any]:
        """Build the JSON-RPC request payload for a tool call."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": params},
        }

    def _handle_buffered_response(self, request_id: int, future: asyncio.Future) -> None:
        """Pre-fill ``future`` from the response buffer if one is queued.

        The reader may have raced ahead of the request registration and
        already received a response for this id into ``_response_buffer``.
        In that case we want the subsequent ``wait_for`` to resolve
        immediately rather than waiting for a second response that will
        never come.

        Mirrors the original behaviour: the request is still built and
        sent afterwards, so the server-side state stays consistent with
        the caller's view even though no fresh response is expected.
        """
        if request_id not in self._response_buffer:
            return
        buffered = self._response_buffer.pop(request_id)
        self._pending_requests.pop(request_id, None)
        future.set_result(buffered)

    async def _send_and_await(
        self, tool_name: str, future: asyncio.Future, request: dict[str, Any]
    ) -> Any:
        """Send ``request`` to the server and await ``future`` for the reply.

        Args:
            tool_name: Tool name (used only for error messages).
            future: Pre-registered future that the reader will resolve.
            request: JSON-RPC payload to serialise and write to stdin.

        Returns:
            The ``result`` field of the resolved response.

        Raises:
            RuntimeError: On transport, timeout, or protocol-level failures.
        """
        try:
            message = json.dumps(request) + "\n"
            self.process.stdin.write(message.encode())  # type: ignore[union-attr]
            await self.process.stdin.drain()  # type: ignore[union-attr]

            response = await asyncio.wait_for(future, timeout=30.0)
            return self._extract_result(response)

        except TimeoutError:
            self._pending_requests.pop(request["id"], None)
            raise RuntimeError(f"Timeout calling MCP tool {tool_name}") from None
        except Exception as e:
            self._pending_requests.pop(request["id"], None)
            raise RuntimeError(f"Failed to call MCP tool {tool_name}: {e}") from e

    @staticmethod
    def _extract_result(response: dict[str, Any]) -> Any:
        """Validate a JSON-RPC response and return its ``result`` field.

        Raises:
            RuntimeError: If the response carries an error or is missing
                the expected ``result`` field.
        """
        if "error" in response:
            raise RuntimeError(f"MCP tool error: {response['error']}")
        if "result" not in response:
            raise RuntimeError(f"Invalid MCP response: {response}")
        return response["result"]

    async def call_tool(self, tool_name: str, params: dict[str, Any]) -> Any:
        """Call an MCP tool on the server.

        Args:
            tool_name: Name of the tool to call
            params: Parameters for the tool

        Returns:
            Tool execution result

        Raises:
            RuntimeError: If MCP server is not running or call fails
        """
        if not self.process or self.process.returncode is not None:
            raise RuntimeError("MCP server process is not running")

        # Allocate a fresh id and register the future BEFORE the reader
        # can deliver a response for it. This is the only spot where
        # ``_pending_requests`` is mutated for an outgoing call.
        self._request_id += 1
        request_id = self._request_id
        future: asyncio.Future = asyncio.Future()
        self._pending_requests[request_id] = future

        # Reader-ahead-of-registration race: the response may already be
        # sitting in ``_response_buffer`` if the reader ran ahead of the
        # registration above. Pre-fill the future so ``wait_for`` returns
        # immediately, then continue and send the request so the server
        # stays in sync with the caller's view.
        self._handle_buffered_response(request_id, future)

        request = self._build_request(tool_name, params, request_id)
        return await self._send_and_await(tool_name, future, request)


class McpretentiousClient:
    """High-level client for mcpretentious MCP server.

    Provides a simplified interface for mcpretentious operations.

    Example:
        >>> client = McpretentiousClient()
        >>> await client.start()
        >>> term_id = await client.open_terminal(80, 24)
        >>> await client.type_text(term_id, "qwen", "enter")
        >>> output = await client.read_text(term_id, lines=100)
        >>> await client.close()
    """

    def __init__(self):
        """Initialize mcpretentious client."""
        self._client = StdioMCPClient("uvx", ["--from", "mcpretentious", "mcpretentious"])

    async def start(self) -> None:
        """Start the mcpretentious server."""
        await self._client.start()

    async def stop(self) -> None:
        """Stop the mcpretentious server."""
        await self._client.stop()

    async def open_terminal(self, columns: int = 80, rows: int = 24) -> str:
        """Open a new terminal.

        Args:
            columns: Terminal width
            rows: Terminal height

        Returns:
            Terminal ID
        """
        result = await self._client.call_tool(
            "mcpretentious-open", {"columns": columns, "rows": rows}
        )
        return result["terminal_id"]  # type: ignore[no-any-return]

    async def type_text(self, terminal_id: str, *input_parts: str) -> None:
        """Type text into a terminal.

        Args:
            terminal_id: Terminal session ID
            *input_parts: Text parts to type (can include special keys like "enter")
        """
        await self._client.call_tool(
            "mcpretentious-type", {"terminal_id": terminal_id, "input": list(input_parts)}
        )

    async def read_text(self, terminal_id: str, lines: int | None = None) -> str:
        """Read text from a terminal.

        Args:
            terminal_id: Terminal session ID
            lines: Number of lines to read

        Returns:
            Terminal output as string
        """
        params: dict[str, Any] = {"terminal_id": terminal_id}
        if lines is not None:
            params["limit_lines"] = lines

        result = await self._client.call_tool("mcpretentious-read", params)
        return result["output"]  # type: ignore[no-any-return]

    async def close_terminal(self, terminal_id: str) -> None:
        """Close a terminal.

        Args:
            terminal_id: Terminal session ID to close
        """
        await self._client.call_tool("mcpretentious-close", {"terminal_id": terminal_id})

    async def list_terminals(self) -> list[dict[str, Any]]:
        """List all active terminals.

        Returns:
            List of terminal information
        """
        result = await self._client.call_tool("mcpretentious-list", {})
        return result.get("terminals", [])  # type: ignore[no-any-return]
