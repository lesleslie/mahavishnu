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
                await self.process.wait()
            logger.info("Stopped MCP server process")

    async def _read_stdout(self) -> None:
        """Read stdout from MCP server process."""
        if not self.process:
            return

        try:
            while True:
                line = await self.process.stdout.readline()
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

                except json.JSONDecodeError:
                    logger.debug(f"Non-JSON output: {line.decode().strip()}")

        except Exception as e:
            logger.error(f"Error reading stdout: {e}")

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

        # Create request
        self._request_id += 1
        request_id = self._request_id
        future: asyncio.Future = asyncio.Future()

        self._pending_requests[request_id] = future

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": params},
        }

        # Send request
        try:
            message = json.dumps(request) + "\n"
            self.process.stdin.write(message.encode())
            await self.process.stdin.drain()

            # Wait for response (with timeout)
            response = await asyncio.wait_for(future, timeout=30.0)

            # Extract result
            if "error" in response:
                raise RuntimeError(f"MCP tool error: {response['error']}")
            if "result" not in response:
                raise RuntimeError(f"Invalid MCP response: {response}")

            return response["result"]

        except TimeoutError:
            del self._pending_requests[request_id]
            raise RuntimeError(f"Timeout calling MCP tool {tool_name}") from None
        except Exception as e:
            del self._pending_requests[request_id]
            raise RuntimeError(f"Failed to call MCP tool {tool_name}: {e}") from e


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
        return result["terminal_id"]

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
        return result["output"]

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
        return result.get("terminals", [])
