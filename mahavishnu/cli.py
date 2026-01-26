"""CLI module for Mahavishnu orchestrator."""
import typer
from typing import Optional
import asyncio
from .core.app import MahavishnuApp
from .core.subscription_auth import MultiAuthHandler

# Import production readiness CLI
from .production_cli import add_production_commands

# Import backup and recovery CLI
from .backup_cli import add_backup_commands

# Import monitoring CLI
from .monitoring_cli import add_monitoring_commands

app = typer.Typer()

@app.command()
def sweep(
    tag: str = typer.Option(..., "--tag", "-t", help="Tag to filter repositories"),
    adapter: str = typer.Option("langgraph", "--adapter", "-a", help="Orchestrator adapter to use")
):
    """
    Perform an AI sweep across repositories with a specific tag.
    """
    # Run the async function synchronously
    result = asyncio.run(_async_sweep(tag, adapter))
    typer.echo(f"Sweep completed with result: {result}")


def progress_callback(completed: int, total: int, repo: str):
    """Callback function to report progress during parallel execution."""
    typer.echo(f"Processed {completed}/{total} repos: {repo}", err=True)


async def _async_sweep(tag: str, adapter: str):
    """Internal async function for sweep command."""
    maha_app = MahavishnuApp()

    # Authenticate if enabled
    auth_handler = MultiAuthHandler(maha_app.config)

    # Check if Claude Code subscription is available
    if auth_handler.is_claude_subscribed():
        typer.echo("Using Claude Code subscription authentication")
    elif maha_app.config.auth_enabled and maha_app.config.auth_secret:
        typer.echo("Using JWT authentication")
    elif auth_handler.is_qwen_free():
        typer.echo("Using Qwen (free service)")
    else:
        typer.echo("Authentication not configured, proceeding without auth")

    repos = maha_app.get_repos(tag=tag)

    # Get the appropriate adapter from the app
    if adapter not in maha_app.adapters:
        typer.echo(f"Adapter '{adapter}' not found. Available: {list(maha_app.adapters.keys())}")
        raise typer.Exit(code=1)

    task = {"task": "ai-sweep", "id": f"sweep-{tag}"}
    result = await maha_app.execute_workflow_parallel(
        task,
        adapter,
        repos,
        progress_callback=progress_callback
    )

    return result


# MCP server management
mcp_app = typer.Typer(help="MCP server lifecycle management")
app.add_typer(mcp_app, name="mcp")


@mcp_app.command("start")
def mcp_start(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host address to bind to"),
    port: int = typer.Option(3000, "--port", "-p", help="Port to listen on"),
):
    """Start the MCP server to expose tools via mcp-common."""
    async def _start():
        from .mcp.server_core import FastMCPServer

        maha_app = MahavishnuApp()

        # Initialize auth handler
        auth_handler = MultiAuthHandler(maha_app.config)

        # Check if Claude Code subscription is available
        if auth_handler.is_claude_subscribed():
            typer.echo("MCP Server: Claude Code subscription authentication enabled")
        elif maha_app.config.auth_enabled and maha_app.config.auth_secret:
            typer.echo("MCP Server: JWT authentication enabled")
        elif auth_handler.is_qwen_free():
            typer.echo("MCP Server: Qwen (free service) authentication")
        else:
            typer.echo("MCP Server: Authentication not configured")

        # Check if terminal management is enabled
        if maha_app.config.terminal.enabled:
            typer.echo("MCP Server: Terminal management enabled")
            typer.echo(f"  - Max concurrent sessions: {maha_app.config.terminal.max_concurrent_sessions}")
            typer.echo(f"  - Adapter: {maha_app.config.terminal.adapter_preference}")
        else:
            typer.echo("MCP Server: Terminal management disabled")

        server = FastMCPServer(maha_app.config)

        try:
            await server.start(host=host, port=port)
        except KeyboardInterrupt:
            typer.echo("\nShutting down MCP server...")
        finally:
            await server.stop()

    asyncio.run(_start())


@mcp_app.command("stop")
def mcp_stop():
    """Stop the MCP server."""
    typer.echo("ERROR: MCP server stop not yet implemented")
    typer.echo("The MCP server runs in the foreground. Use Ctrl+C to stop it.")
    raise typer.Exit(code=1)


@mcp_app.command("restart")
def mcp_restart(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host address to bind to"),
    port: int = typer.Option(3000, "--port", "-p", help="Port to listen on"),
):
    """Restart the MCP server."""
    typer.echo("ERROR: MCP server restart not yet implemented")
    typer.echo("Use Ctrl+C to stop the server, then run 'mahavishnu mcp start' to restart.")
    raise typer.Exit(code=1)


@mcp_app.command("status")
def mcp_status():
    """Check MCP server status."""
    async def _status():
        from .mcp.server_core import FastMCPServer

        maha_app = MahavishnuApp()
        server = FastMCPServer(maha_app.config)

        # Check if terminal management is enabled
        terminal_status = "enabled" if maha_app.config.terminal.enabled else "disabled"
        typer.echo(f"Terminal Management: {terminal_status}")

        if maha_app.config.terminal.enabled:
            typer.echo(f"  Max concurrent sessions: {maha_app.config.terminal.max_concurrent_sessions}")
            typer.echo(f"  Default dimensions: {maha_app.config.terminal.default_columns}x{maha_app.config.terminal.default_rows}")
            typer.echo(f"  Adapter preference: {maha_app.config.terminal.adapter_preference}")

        # Note: We can't check if the server is actually running without
        # connecting to it, but we can show the configuration status
        typer.echo(f"Server will bind to: 127.0.0.1:3000 (configurable)")
        typer.echo("\nTo start the server, run: mahavishnu mcp start")

    asyncio.run(_status())


@mcp_app.command("health")
def mcp_health():
    """Check MCP server health."""
    async def _health():
        import socket

        host = "127.0.0.1"
        port = 3000

        try:
            # Try to connect to the MCP server
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=2.0
            )
            writer.close()
            reader.close()
            typer.echo("MCP Server: ✓ Running")
            typer.echo(f"Connected to {host}:{port}")
        except (ConnectionRefusedError, OSError, asyncio.TimeoutError):
            typer.echo("MCP Server: ✗ Not running")
            typer.echo(f"Could not connect to {host}:{port}")
        except Exception as e:
            typer.echo(f"MCP Server: ? Unknown status: {e}")

    asyncio.run(_health())


@app.command()
def list_repos(
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Filter repositories by tag")
):
    """
    List repositories in repos.yaml.
    """
    maha_app = MahavishnuApp()

    # Initialize auth handler
    auth_handler = MultiAuthHandler(maha_app.config)

    # Check if Claude Code subscription is available
    if auth_handler.is_claude_subscribed():
        typer.echo("Using Claude Code subscription authentication")
    elif maha_app.config.auth_enabled and maha_app.config.auth_secret:
        typer.echo("Using JWT authentication")
    elif auth_handler.is_qwen_free():
        typer.echo("Using Qwen (free service)")
    else:
        typer.echo("Authentication not configured, proceeding without auth")

    repos = maha_app.get_repos(tag=tag)

    if tag:
        typer.echo(f"Repositories with tag '{tag}':")
    else:
        typer.echo("All repositories:")

    for repo in repos:
        typer.echo(f"  - {repo}")


@app.command()
def generate_claude_token(user_id: str = typer.Argument(..., help="User ID for the token")):
    """
    Generate a Claude Code subscription token.
    """
    maha_app = MahavishnuApp()

    # Initialize auth handler
    auth_handler = MultiAuthHandler(maha_app.config)

    if not auth_handler.is_claude_subscribed():
        typer.echo("ERROR: Claude Code subscription authentication is not configured")
        typer.echo("Please set subscription_auth_enabled and subscription_auth_secret in config")
        raise typer.Exit(code=1)

    # Generate Claude Code subscription token
    token = auth_handler.create_claude_subscription_token(
        user_id=user_id,
        scopes=["read", "execute", "workflow_manage"]
    )

    typer.echo(f"Claude Code subscription token generated for user '{user_id}':")
    typer.echo(f"Token: {token}")


@app.command()
def generate_codex_token(user_id: str = typer.Argument(..., help="User ID for the token")):
    """
    Generate a Codex subscription token.
    """
    maha_app = MahavishnuApp()

    # Initialize auth handler
    auth_handler = MultiAuthHandler(maha_app.config)

    if not auth_handler.is_codex_subscribed():  # Using same underlying mechanism
        typer.echo("ERROR: Codex subscription authentication is not configured")
        typer.echo("Please set subscription_auth_enabled and subscription_auth_secret in config")
        raise typer.Exit(code=1)

    # Generate Codex subscription token (using same mechanism as Claude but different type)
    token = auth_handler.create_codex_subscription_token(
        user_id=user_id,
        scopes=["read", "execute", "workflow_manage"]
    )

    typer.echo(f"Codex subscription token generated for user '{user_id}':")
    typer.echo(f"Token: {token}")


# Terminal management commands
terminal_app = typer.Typer(help="Terminal session management commands")
app.add_typer(terminal_app, name="terminal")


@terminal_app.command("launch")
def terminal_launch(
    command: str = typer.Argument(..., help="Command to run in each terminal"),
    count: int = typer.Option(1, "--count", "-c", help="Number of sessions to launch"),
    columns: int = typer.Option(120, "--columns", help="Terminal width"),
    rows: int = typer.Option(40, "--rows", help="Terminal height"),
):
    """Launch terminal sessions running a command."""
    async def _launch():
        maha_app = MahavishnuApp()

        if not maha_app.config.terminal.enabled:
            typer.echo("ERROR: Terminal management is not enabled")
            typer.echo("Set 'terminal.enabled: true' in settings/mahavishnu.yaml")
            raise typer.Exit(code=1)

        if maha_app.terminal_manager is None:
            typer.echo("ERROR: Terminal manager not initialized")
            typer.echo("Terminal management requires MCP server context")
            typer.echo("Use MCP tools instead: mahavishnu mcp-serve")
            raise typer.Exit(code=1)

        try:
            session_ids = await maha_app.terminal_manager.launch_sessions(
                command,
                count,
                columns,
                rows,
            )
            typer.echo(f"✓ Launched {len(session_ids)} session(s)")
            for sid in session_ids:
                typer.echo(f"  - {sid}")
        except Exception as e:
            typer.echo(f"ERROR: Failed to launch sessions: {e}")
            raise typer.Exit(code=1)

    asyncio.run(_launch())


@terminal_app.command("list")
def terminal_list():
    """List active terminal sessions."""
    async def _list():
        maha_app = MahavishnuApp()

        if not maha_app.config.terminal.enabled:
            typer.echo("ERROR: Terminal management is not enabled")
            raise typer.Exit(code=1)

        if maha_app.terminal_manager is None:
            typer.echo("ERROR: Terminal manager not initialized")
            raise typer.Exit(code=1)

        try:
            sessions = await maha_app.terminal_manager.list_sessions()
            typer.echo(f"Active sessions: {len(sessions)}")
            for session in sessions:
                typer.echo(f"  - {session}")
        except Exception as e:
            typer.echo(f"ERROR: Failed to list sessions: {e}")
            raise typer.Exit(code=1)

    asyncio.run(_list())


@terminal_app.command("send")
def terminal_send(
    session_id: str = typer.Argument(..., help="Terminal session ID"),
    command: str = typer.Argument(..., help="Command to send"),
):
    """Send command to a terminal session."""
    async def _send():
        maha_app = MahavishnuApp()

        if not maha_app.config.terminal.enabled:
            typer.echo("ERROR: Terminal management is not enabled")
            raise typer.Exit(code=1)

        if maha_app.terminal_manager is None:
            typer.echo("ERROR: Terminal manager not initialized")
            raise typer.Exit(code=1)

        try:
            await maha_app.terminal_manager.send_command(session_id, command)
            typer.echo(f"✓ Sent command to {session_id}")
        except Exception as e:
            typer.echo(f"ERROR: Failed to send command: {e}")
            raise typer.Exit(code=1)

    asyncio.run(_send())


@terminal_app.command("capture")
def terminal_capture(
    session_id: str = typer.Argument(..., help="Terminal session ID"),
    lines: int = typer.Option(100, "--lines", "-l", help="Number of lines to capture"),
):
    """Capture output from a terminal session."""
    async def _capture():
        maha_app = MahavishnuApp()

        if not maha_app.config.terminal.enabled:
            typer.echo("ERROR: Terminal management is not enabled")
            raise typer.Exit(code=1)

        if maha_app.terminal_manager is None:
            typer.echo("ERROR: Terminal manager not initialized")
            raise typer.Exit(code=1)

        try:
            output = await maha_app.terminal_manager.capture_output(
                session_id,
                lines,
            )
            typer.echo(output)
        except Exception as e:
            typer.echo(f"ERROR: Failed to capture output: {e}")
            raise typer.Exit(code=1)

    asyncio.run(_capture())


@terminal_app.command("close")
def terminal_close(
    session_id: str = typer.Argument(..., help="Session ID (or 'all' to close all)"),
):
    """Close terminal session(s)."""
    async def _close():
        maha_app = MahavishnuApp()

        if not maha_app.config.terminal.enabled:
            typer.echo("ERROR: Terminal management is not enabled")
            raise typer.Exit(code=1)

        if maha_app.terminal_manager is None:
            typer.echo("ERROR: Terminal manager not initialized")
            raise typer.Exit(code=1)

        try:
            if session_id.lower() == "all":
                sessions = await maha_app.terminal_manager.list_sessions()
                session_ids = [s.get("id", s.get("terminal_id", "")) for s in sessions]
                if session_ids:
                    await maha_app.terminal_manager.close_all(session_ids)
                    typer.echo(f"✓ Closed {len(session_ids)} session(s)")
                else:
                    typer.echo("No active sessions to close")
            else:
                await maha_app.terminal_manager.close_session(session_id)
                typer.echo(f"✓ Closed session {session_id}")
        except Exception as e:
            typer.echo(f"ERROR: Failed to close session(s): {e}")
            raise typer.Exit(code=1)

    asyncio.run(_close())


# Add production readiness commands
add_production_commands(app)

# Add backup and recovery commands
add_backup_commands(app)

# Add monitoring commands
add_monitoring_commands(app)


@app.command("shell")
def shell_cmd():
    """Start the interactive admin shell for debugging and monitoring.

    Provides an IPython environment pre-configured with:
    - Workflow status display (ps, top, errors)
    - Log viewing and filtering
    - Repository inspection
    - Magic commands (%repos, %workflow)

    Example:
        $ mahavishnu shell
        Mahavishnu> ps()              # Show all workflows
        Mahavishnu> top()             # Show active workflows
        Mahavishnu> errors(5)         # Show recent errors
        Mahavishnu> %repos            # List repositories
    """
    async def _shell():
        from .shell import MahavishnuShell

        maha_app = MahavishnuApp()

        # Check if shell is enabled
        if not getattr(maha_app.config, "shell_enabled", True):
            typer.echo("ERROR: Admin shell is disabled")
            raise typer.Exit(code=1)

        # Create and start shell
        shell = MahavishnuShell(maha_app)
        shell.start()

    asyncio.run(_shell())


if __name__ == "__main__":
    app()