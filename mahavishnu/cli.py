"""CLI module for Mahavishnu orchestrator."""

import asyncio
from typing import NoReturn

import typer

# Import backup and recovery CLI
from .backup_cli import add_backup_commands
from .core.app import MahavishnuApp
from .core.subscription_auth import MultiAuthHandler

# Import ecosystem management CLI
from .ecosystem_cli import add_ecosystem_commands

# Import monitoring CLI
from .monitoring_cli import add_monitoring_commands

# Import production readiness CLI
from .production_cli import add_production_commands

# Import sync CLI
from .sync_cli import add_sync_commands

app = typer.Typer()


@app.command()
def sweep(
    tag: str = typer.Option(..., "--tag", "-t", help="Tag to filter repositories"),
    adapter: str = typer.Option("langgraph", "--adapter", "-a", help="Orchestrator adapter to use"),
):
    """
    Perform an AI sweep across repositories with a specific tag.
    """
    # Run the async function synchronously
    result = asyncio.run(_async_sweep(tag, adapter))
    typer.echo(f"Sweep completed with result: {result}")


def progress_callback(completed: int, total: int, repo: str) -> None:
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
        task, adapter, repos, progress_callback=progress_callback
    )

    return result


# MCP server management
mcp_app = typer.Typer(help="MCP server lifecycle management")
app.add_typer(mcp_app, name="mcp")


# Ecosystem management
ecosystem_app = typer.Typer(help="Ecosystem configuration and management")
app.add_typer(ecosystem_app, name="ecosystem")


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
            typer.echo(
                f"  - Max concurrent sessions: {maha_app.config.terminal.max_concurrent_sessions}"
            )
            typer.echo(f"  - Adapter: {maha_app.config.terminal.adapter_preference}")
        else:
            typer.echo("MCP Server: Terminal management disabled")

        server = FastMCPServer(maha_app)

        try:
            await server.start(host=host, port=port)
        except KeyboardInterrupt:
            typer.echo("\nShutting down MCP server...")
        finally:
            await server.stop()

    asyncio.run(_start())


@mcp_app.command("stop")
def mcp_stop() -> NoReturn:
    """Stop the MCP server."""
    typer.echo("ERROR: MCP server stop not yet implemented")
    typer.echo("The MCP server runs in the foreground. Use Ctrl+C to stop it.")
    raise typer.Exit(code=1)


@mcp_app.command("restart")
def mcp_restart(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host address to bind to"),
    port: int = typer.Option(3000, "--port", "-p", help="Port to listen on"),
) -> NoReturn:
    """Restart the MCP server."""
    typer.echo("ERROR: MCP server restart not yet implemented")
    typer.echo("Use Ctrl+C to stop the server, then run 'mahavishnu mcp start' to restart.")
    raise typer.Exit(code=1)


@mcp_app.command("status")
def mcp_status() -> None:
    """Check MCP server status."""

    async def _status():
        from .mcp.server_core import FastMCPServer

        maha_app = MahavishnuApp()
        # FastMCPServer instantiation for side effects (initialization)
        _ = FastMCPServer(maha_app.config)

        # Check if terminal management is enabled
        terminal_status = "enabled" if maha_app.config.terminal.enabled else "disabled"
        typer.echo(f"Terminal Management: {terminal_status}")

        if maha_app.config.terminal.enabled:
            typer.echo(
                f"  Max concurrent sessions: {maha_app.config.terminal.max_concurrent_sessions}"
            )
            typer.echo(
                f"  Default dimensions: {maha_app.config.terminal.default_columns}x{maha_app.config.terminal.default_rows}"
            )
            typer.echo(f"  Adapter preference: {maha_app.config.terminal.adapter_preference}")

        # Note: We can't check if the server is actually running without
        # connecting to it, but we can show the configuration status
        typer.echo("Server will bind to: 127.0.0.1:3000 (configurable)")
        typer.echo("\nTo start the server, run: mahavishnu mcp start")

    asyncio.run(_status())


@mcp_app.command("health")
def mcp_health() -> None:
    """Check MCP server health."""

    async def _health():
        host = "127.0.0.1"
        port = 3000

        try:
            # Try to connect to the MCP server
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=2.0
            )
            writer.close()
            reader.close()
            typer.echo("MCP Server: ✓ Running")
            typer.echo(f"Connected to {host}:{port}")
        except (TimeoutError, ConnectionRefusedError, OSError):
            typer.echo("MCP Server: ✗ Not running")
            typer.echo(f"Could not connect to {host}:{port}")
        except Exception as e:
            typer.echo(f"MCP Server: ? Unknown status: {e}")

    asyncio.run(_health())


@app.command()
def list_repos(
    tag: str | None = typer.Option(None, "--tag", "-t", help="Filter repositories by tag"),
    role: str | None = typer.Option(None, "--role", "-r", help="Filter repositories by role"),
) -> None:
    """
    List repositories in repos.yaml.

    Can filter by tag or role (but not both).
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

    # Validate that only one filter is provided
    if tag and role:
        typer.echo("Error: Cannot specify both --tag and --role filters")
        raise typer.Exit(code=1)

    try:
        repos = maha_app.get_repos(tag=tag, role=role)

        if tag:
            typer.echo(f"Repositories with tag '{tag}':")
        elif role:
            typer.echo(f"Repositories with role '{role}':")
        else:
            typer.echo("All repositories:")

        for repo in repos:
            typer.echo(f"  - {repo}")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None


@app.command()
def list_roles() -> None:
    """
    List all available roles with their descriptions.
    """
    maha_app = MahavishnuApp()

    roles = maha_app.get_roles()

    typer.echo(f"Available roles ({len(roles)}):")
    for role in roles:
        typer.echo(f"\n  {role.get('name').upper()}")
        typer.echo(f"  Description: {role.get('description')}")
        if tags := role.get("tags"):
            typer.echo(f"  Tags: {', '.join(tags)}")
        if capabilities := role.get("capabilities"):
            typer.echo(f"  Capabilities: {', '.join(capabilities)}")


@app.command()
def show_role(role_name: str = typer.Argument(..., help="Name of the role to display")) -> None:
    """
    Show detailed information about a specific role.

    Includes description, duties, capabilities, and repositories with that role.
    """
    maha_app = MahavishnuApp()

    role = maha_app.get_role_by_name(role_name)

    if not role:
        typer.echo(f"Error: Role '{role_name}' not found")
        typer.echo("Use 'mahavishnu list-roles' to see available roles")
        raise typer.Exit(code=1)

    # Display role details
    typer.echo(f"\n{role.get('name').upper()}")
    typer.echo("=" * len(role.get("name")))
    typer.echo(f"\nDescription: {role.get('description')}")

    if tags := role.get("tags"):
        typer.echo("\nTags:")
        for tag in tags:
            typer.echo(f"  - {tag}")

    if duties := role.get("duties"):
        typer.echo("\nDuties:")
        for duty in duties:
            typer.echo(f"  - {duty}")

    if capabilities := role.get("capabilities"):
        typer.echo("\nCapabilities:")
        for capability in capabilities:
            typer.echo(f"  - {capability}")

    # Get repos with this role
    repos = maha_app.get_repos_by_role(role_name)

    typer.echo(f"\nRepositories with this role ({len(repos)}):")
    for repo in repos:
        name = repo.get("name", repo.get("path"))
        nickname = repo.get("nickname", "")
        path = repo.get("path")
        typer.echo(f"  - {name}", nl=False)
        if nickname:
            typer.echo(f" (nickname: {nickname})", nl=False)
        typer.echo(f"\n    Path: {path}")


@app.command()
def list_nicknames() -> None:
    """
    List all repository nicknames.
    """
    maha_app = MahavishnuApp()

    nicknames = maha_app.get_all_nicknames()

    if not nicknames:
        typer.echo("No nicknames configured")
        return

    typer.echo(f"Repository nicknames ({len(nicknames)}):")
    for nickname, full_name in sorted(nicknames.items()):
        typer.echo(f"  {nickname}: {full_name}")


@app.command()
def generate_claude_token(user_id: str = typer.Argument(..., help="User ID for the token")) -> None:
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
        user_id=user_id, scopes=["read", "execute", "workflow_manage"]
    )

    typer.echo(f"Claude Code subscription token generated for user '{user_id}':")
    typer.echo(f"Token: {token}")


@app.command()
def generate_codex_token(user_id: str = typer.Argument(..., help="User ID for the token")) -> None:
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
        user_id=user_id, scopes=["read", "execute", "workflow_manage"]
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
) -> None:
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
            raise typer.Exit(code=1) from None

    asyncio.run(_launch())


@terminal_app.command("list")
def terminal_list() -> None:
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
            raise typer.Exit(code=1) from None

    asyncio.run(_list())


@terminal_app.command("send")
def terminal_send(
    session_id: str = typer.Argument(..., help="Terminal session ID"),
    command: str = typer.Argument(..., help="Command to send"),
) -> None:
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
            raise typer.Exit(code=1) from None

    asyncio.run(_send())


@terminal_app.command("capture")
def terminal_capture(
    session_id: str = typer.Argument(..., help="Terminal session ID"),
    lines: int = typer.Option(100, "--lines", "-l", help="Number of lines to capture"),
) -> None:
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
            raise typer.Exit(code=1) from None

    asyncio.run(_capture())


@terminal_app.command("close")
def terminal_close(
    session_id: str = typer.Argument(..., help="Session ID (or 'all' to close all)"),
) -> None:
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
            raise typer.Exit(code=1) from None

    asyncio.run(_close())


# Add production readiness commands
add_production_commands(app)

# Add backup and recovery commands
add_backup_commands(app)

# Add ecosystem management commands
add_ecosystem_commands(ecosystem_app)

# Add monitoring commands
add_monitoring_commands(app)

# Add Claude-Qwen sync commands
add_sync_commands(app)


@app.command("shell")
def shell_cmd() -> None:
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
