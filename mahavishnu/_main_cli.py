"""CLI module for Mahavishnu orchestrator."""

import asyncio
import json
from typing import Any, NoReturn

import typer

# Import backup and recovery CLI
from .backup_cli import add_backup_commands

# Import configuration validation CLI
from .cli.config_validator import add_config_inventory_commands, add_config_validation_commands

# Import docs audit CLI
from .cli.docs_cli import add_docs_commands

# Import events CLI
from .cli.events import add_events_commands

# Import code indexing CLI
from .cli.index_cli import add_index_commands

# Import scaffold CLI
from .cli.scaffold_cli import app as scaffold_app

# Import precommitment CLI (Spec #2)
from .cli.precommit_cli import precommit_app as precommit_app_obj

# Import SOP evolution CLI (Spec #7)
from .cli.sop_cli import add_sop_commands

# Import team CLI
from .cli.team_cli import add_team_commands

# Import coordination CLI
from .coordination_cli import add_coordination_commands
from .core.app import MahavishnuApp
from .core.health import HealthStatus
from .core.subscription_auth import MultiAuthHandler

# Import ecosystem management CLI
from .ecosystem_cli import add_ecosystem_commands

# Import content ingestion CLI
from .ingestion_cli import add_ingestion_commands

# Import metrics CLI
from .metrics_cli import add_metrics_commands

# Import monitoring CLI
from .monitoring_cli import add_monitoring_commands

# Import production readiness CLI
from .production_cli import add_production_commands

# Import quality evaluation CLI
from .quality_cli import add_quality_commands

# Import rollback CLI (audit H8: SLOs/rollback for Plan 1 + Plan 5)
from .cli.rollback_cli import add_rollback_commands

# Import adaptive routing CLI
from .routing_cli import add_routing_commands

# Import worktree management CLI
from .worktree_cli import worktree_app

# Import comprehensive help system
# NOTE: help_cli uses Click which is incompatible with Typer's add_typer()
# from .cli.help_cli import help_group

app = typer.Typer(name="mahavishnu")
DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 8680


def _resolve_crow_mcp_client(config: Any) -> Any:
    """Build a crow MCP client when ``terminal.crow_enabled`` is true.

    Returns ``None`` when crow is disabled so the terminal factory falls
    through to the mock adapter (the documented default behavior). When
    crow is enabled, constructs a client pointing at the bundled
    ``bodai-crow`` HTTP server using ``terminal.crow_http_host`` /
    ``terminal.crow_http_port`` (or the ``MAHAVISHNU_CROW_HTTP_HOST`` /
    ``MAHAVISHNU_CROW_HTTP_PORT`` env overrides).

    Symmetric across all three ``TerminalManager.create(...)`` call sites
    in this module. See ``docs/followups/2026-06-29-crow-mcp-client-wiring.md``.
    """
    terminal_config = getattr(config, "terminal", None)
    if terminal_config is None:
        return None
    if not getattr(terminal_config, "crow_enabled", False):
        return None
    from .mcp.crow_server import create_crow_mcp_client

    return create_crow_mcp_client(
        host=getattr(terminal_config, "crow_http_host", None),
        port=getattr(terminal_config, "crow_http_port", None),
    )


# Add worktree sub-app
app.add_typer(worktree_app, name="worktree")

# Add configuration validation command
add_config_validation_commands(app)

# Add config inventory commands (list-agents, list-skills, list-mcp-servers, sync, rollback)
add_config_inventory_commands(app)

# Add docs audit commands (docs audit)
add_docs_commands(app)

# Add quality evaluation commands (quality check, quality report)
add_quality_commands(app)

# Add comprehensive help system - DISABLED due to Click/Typer incompatibility
# app.add_typer(help_group, name="help")


# ── Workflow sub-app (canonical CLI pathways for top workflows) ──────────

workflows_app = typer.Typer(help="Canonical orchestration workflow commands")
app.add_typer(workflows_app, name="workflow")


@workflows_app.command("sweep")
def workflow_sweep(
    tag: str = typer.Option(..., "--tag", "-t", help="Tag to filter repositories"),
    adapter: str = typer.Option("langgraph", "--adapter", "-a", help="Orchestrator adapter"),
):
    """Run an AI code sweep across repositories matching a tag."""
    result = asyncio.run(_async_sweep(tag, adapter))
    typer.echo(f"Sweep completed with result: {result}")


@workflows_app.command("quality-check")
def workflow_quality_check(
    tag: str = typer.Option(..., "--tag", "-t", help="Tag to filter repositories"),
    adapter: str = typer.Option("langgraph", "--adapter", "-a", help="Orchestrator adapter"),
    repos: list[str] | None = typer.Option(
        None, "--repo", "-r", help="Explicit repo list (overrides tag)"
    ),
):
    """Run quality assurance evaluation across repositories."""
    result = asyncio.run(
        _async_trigger_workflow(
            task_type="quality_check",
            adapter=adapter,
            tag=tag,
            repos=repos,
        )
    )
    typer.echo(f"Quality check completed: {result}")


@workflows_app.command("heal")
def workflow_heal():
    """Auto-recover failed workflows from the dead letter queue."""
    result = asyncio.run(_async_heal_workflows())
    typer.echo(json.dumps(result, indent=2, default=str))


@workflows_app.command("fix")
def workflow_fix(
    pool_id: str = typer.Option(..., "--pool", "-p", help="Worker pool ID to use"),
    issue_id: str = typer.Option(..., "--issue", "-i", help="Coordination issue ID to fix"),
    description: str = typer.Option("", "--desc", "-d", help="Issue description for the AI worker"),
    files: list[str] | None = typer.Option(
        None, "--file", "-f", help="Files to include in context"
    ),
):
    """Execute a fix via worker pool with quality gate validation."""
    result = asyncio.run(
        _async_fix_orchestrate(
            pool_id=pool_id,
            issue_id=issue_id,
            description=description,
            files=files or [],
        )
    )
    typer.echo(json.dumps(result, indent=2, default=str))


@workflows_app.command("review")
def workflow_review(
    scope: str = typer.Option(
        "critical",
        "--scope",
        "-s",
        help="Review scope: critical, security, performance, quality, all",
    ),
    auto_fix: bool = typer.Option(False, "--fix", help="Auto-fix safe, deterministic issues"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview findings without applying fixes"
    ),
):
    """Run automated code review with optional auto-fix."""
    result = asyncio.run(_async_review_and_fix(scope, auto_fix, dry_run))
    typer.echo(json.dumps(result, indent=2, default=str))


# ── Adapter sub-app (canonical adapter routing commands) ─────────────────

adapter_app = typer.Typer(help="Adapter discovery and routing")
app.add_typer(adapter_app, name="adapter")


@adapter_app.command("list")
def adapter_list_cmd(
    domain: str | None = typer.Option(None, "--domain", "-d", help="Filter by domain"),
    healthy_only: bool = typer.Option(False, "--healthy", help="Show only healthy adapters"),
):
    """List registered adapters with optional filtering."""
    result = asyncio.run(_async_adapter_list(domain, healthy_only))
    typer.echo(json.dumps(result, indent=2, default=str))


@adapter_app.command("resolve")
def adapter_resolve_cmd(
    task_type: str = typer.Argument(..., help="Type of task to route"),
    capabilities: list[str] = typer.Option(..., "--cap", "-c", help="Required capabilities"),
    domain: str = typer.Option("orchestration", "--domain", "-d", help="Domain category"),
):
    """Resolve the best adapter for a task by capabilities."""
    result = asyncio.run(_async_adapter_resolve(task_type, capabilities, domain))
    typer.echo(json.dumps(result, indent=2, default=str))


@adapter_app.command("health")
def adapter_health_cmd(
    name: str | None = typer.Argument(None, help="Specific adapter (omit for all)"),
):
    """Check health of one or all adapters."""
    result = asyncio.run(_async_adapter_health(name))
    typer.echo(json.dumps(result, indent=2, default=str))


# ── Internal async helpers for workflow commands ─────────────────────────


async def _async_trigger_workflow(
    task_type: str,
    adapter: str,
    tag: str,
    repos: list[str] | None,
) -> dict:
    """Trigger a workflow via the canonical execution path."""
    maha_app = MahavishnuApp()

    all_repos = repos or maha_app.get_repos(tag=tag)

    if not all_repos:
        typer.echo("No repositories found", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Running {task_type} across {len(all_repos)} repos via {adapter}...")

    task = {"task": task_type, "id": f"{task_type}-{tag}"}
    result = await maha_app.execute_workflow_parallel(task, adapter, all_repos)
    return result


async def _async_heal_workflows() -> dict:
    """Trigger workflow healing from the dead letter queue."""
    from .core.dead_letter_queue import DeadLetterQueue

    dlq = DeadLetterQueue()

    failed_tasks = await dlq.list_tasks(status="pending")  # type: ignore[arg-type]
    if not failed_tasks:
        return {"status": "no_failed_workflows", "message": "DLQ is empty"}

    typer.echo(f"Found {len(failed_tasks)} failed workflows in DLQ")

    healed = 0
    errors = []
    for task in failed_tasks:
        try:
            result = await dlq.retry_task(task.task_id)
            if result.get("status") == "retried":
                healed += 1
        except Exception as e:
            errors.append({"workflow_id": task.task_id, "error": str(e)})

    return {
        "status": "completed",
        "total_failed": len(failed_tasks),
        "healed": healed,
        "errors": errors,
    }


async def _async_fix_orchestrate(
    pool_id: str,
    issue_id: str,
    description: str,
    files: list[str],
) -> dict:
    """Execute a fix via the FixOrchestrator canonical path."""
    from .core.fix_orchestrator import FixOrchestrator, FixTask

    prompt_parts = [f"Fix issue {issue_id}"]
    if description:
        prompt_parts.append(f"Description: {description}")
    if files:
        prompt_parts.append(f"Files: {', '.join(files)}")

    task = FixTask(
        issue_id=issue_id,
        pool_type="mahavishnu",
        prompt="\n".join(prompt_parts),
        affected_files=files,
    )

    orchestrator = FixOrchestrator()
    typer.echo(f"Executing fix for {issue_id} on pool {pool_id}...")
    result = await orchestrator.execute_fix(pool_id=pool_id, task=task)
    return result  # type: ignore[return-value]


async def _async_review_and_fix(scope: str, auto_fix: bool, dry_run: bool) -> dict:
    """Run code review with optional auto-fix via the canonical path."""
    from .mcp.tools.self_improvement_tools import ReviewScope, SelfImprovementTools

    maha_app = MahavishnuApp()
    tools = SelfImprovementTools(maha_app)
    typer.echo(
        f"Running {'dry-run ' if dry_run else ''}review (scope={scope}, auto_fix={auto_fix})..."
    )
    result = await tools.review_and_fix(
        scope=ReviewScope(scope),
        auto_fix=auto_fix,
        dry_run=dry_run,
    )
    return result


async def _async_adapter_list(domain: str | None, healthy_only: bool) -> dict:
    """List adapters via the canonical adapter registry path."""
    from .core.adapter_registry import HybridAdapterRegistry

    registry = HybridAdapterRegistry()  # type: ignore[call-arg]
    adapters = registry.list_adapters(domain=domain, healthy_only=healthy_only)
    return {
        "count": len(adapters),
        "adapters": [
            {
                "name": a.name,  # type: ignore[attr-defined]
                "domain": a.domain,  # type: ignore[attr-defined]
                "status": a.status,  # type: ignore[attr-defined]
                "capabilities": a.capabilities,  # type: ignore[attr-defined]
            }
            for a in adapters
        ],
    }


async def _async_adapter_resolve(task_type: str, capabilities: list[str], domain: str) -> dict:
    """Resolve adapter via the canonical routing path."""
    from .core.task_router import TaskRouter, TaskType

    router = TaskRouter()
    try:
        task = TaskType(task_type)
    except ValueError:
        typer.echo(
            f"Unknown task type: {task_type}. Valid: {', '.join(t.value for t in TaskType)}",
            err=True,
        )
        raise typer.Exit(code=1)

    result = await router.route(task_type=task, additional_capabilities=capabilities, domain=domain)  # type: ignore[call-arg]
    return {
        "task_type": task_type,
        "selected_adapter": result.get("adapter") if isinstance(result, dict) else str(result),
        "confidence": result.get("confidence") if isinstance(result, dict) else None,
    }


async def _async_adapter_health(name: str | None) -> dict:
    """Check adapter health via the canonical path."""
    from .core.adapter_registry import HybridAdapterRegistry

    registry = HybridAdapterRegistry()  # type: ignore[call-arg]
    results = await registry.check_all_health()
    if name:
        if name in results:
            return {"adapter": name, **results[name]}
        return {"adapter": name, "status": "not_found", "error": f"Adapter '{name}' not registered"}
    return {"count": len(results), "adapters": results}


# ── Legacy sweep command (delegates to workflow sweep) ───────────────────


@app.command()
def sweep(
    tag: str = typer.Option(..., "--tag", "-t", help="Tag to filter repositories"),
    adapter: str = typer.Option("langgraph", "--adapter", "-a", help="Orchestrator adapter to use"),
):
    """
    Perform an AI sweep across repositories with a specific tag.

    Prefer: mahavishnu workflow sweep --tag TAG
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
    elif maha_app.config.auth.enabled and maha_app.config.auth.secret:
        typer.echo("Using JWT authentication")
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

# Content ingestion
add_ingestion_commands()


@mcp_app.command("start")
def mcp_start(
    host: str = typer.Option(DEFAULT_MCP_HOST, "--host", "-h", help="Host address to bind to"),
    port: int = typer.Option(DEFAULT_MCP_PORT, "--port", "-p", help="Port to listen on"),
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
        elif maha_app.config.auth.enabled and maha_app.config.auth.secret:
            typer.echo("MCP Server: JWT authentication enabled")
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
    host: str = typer.Option(DEFAULT_MCP_HOST, "--host", "-h", help="Host address to bind to"),
    port: int = typer.Option(DEFAULT_MCP_PORT, "--port", "-p", help="Port to listen on"),
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
        _ = FastMCPServer(app=maha_app)

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
        typer.echo(f"Server will bind to: {DEFAULT_MCP_HOST}:{DEFAULT_MCP_PORT} (configurable)")
        typer.echo("\nTo start the server, run: mahavishnu mcp start")

    asyncio.run(_status())


@mcp_app.command("health")
def mcp_health() -> None:
    """Check MCP server health."""

    async def _health():
        host = DEFAULT_MCP_HOST
        port = DEFAULT_MCP_PORT

        try:
            # Try to connect to the MCP server
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=2.0
            )
            writer.close()
            await writer.wait_closed()
            typer.echo("MCP Server: ✓ Running")
            typer.echo(f"Connected to {host}:{port}")
        except (TimeoutError, ConnectionRefusedError, OSError):
            typer.echo("MCP Server: ✗ Not running")
            typer.echo(f"Could not connect to {host}:{port}")
        except Exception as e:
            typer.echo(f"MCP Server: ? Unknown status: {e}")

    asyncio.run(_health())


@app.command("health")
def health_command(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit structured JSON output instead of human-readable text",
    ),
) -> None:
    """Check the current Mahavishnu service health."""

    async def _health():
        maha_app = MahavishnuApp()
        endpoint = maha_app.health_endpoint

        if endpoint is None:
            payload = {
                "service": "mahavishnu",
                "status": HealthStatus.UNHEALTHY.value,
                "reason": "Health checks are disabled in configuration",
            }
            if json_output:
                typer.echo(json.dumps(payload, indent=2))
            else:
                typer.echo("Service: ✗ unhealthy")
                typer.echo("Reason: Health checks are disabled in configuration")
            return

        liveness = await endpoint.liveness()
        readiness = await endpoint.readiness()

        dependency_details = {
            name: {
                "status": dep.status.value,
                "latency_ms": dep.latency_ms,
                "error": dep.error,
                "last_check": dep.last_check.isoformat() if dep.last_check else None,
            }
            for name, dep in readiness.dependencies.items()
        }

        dependency_statuses = [dep.status for dep in readiness.dependencies.values()]
        if any(status == HealthStatus.UNHEALTHY for status in dependency_statuses):
            overall_status = HealthStatus.UNHEALTHY
        elif any(status == HealthStatus.DEGRADED for status in dependency_statuses):
            overall_status = HealthStatus.DEGRADED
        else:
            overall_status = liveness.status

        payload = {
            "service": readiness.service,
            "version": liveness.version,
            "status": overall_status.value,
            "liveness": liveness.model_dump(),
            "readiness": readiness.model_dump(),
            "dependencies": dependency_details,  # type: ignore[dict-item]
        }

        if json_output:
            typer.echo(json.dumps(payload, indent=2, default=str))
            return

        status_symbol = {"ok": "✓", "degraded": "!", "unhealthy": "✗"}[overall_status.value]
        typer.echo(f"Service: {status_symbol} {payload['status']}")
        typer.echo(f"Name: {payload['service']}")
        typer.echo(f"Version: {payload['version']}")
        typer.echo(f"Uptime: {liveness.uptime_seconds:.1f}s")
        typer.echo(f"Readiness: {'ready' if readiness.ready else 'not ready'}")
        if dependency_details:
            typer.echo("Dependencies:")
            for name, dep in dependency_details.items():
                line = f"  - {name}: {dep['status']}"
                if dep["latency_ms"] is not None:
                    line += f" ({dep['latency_ms']:.1f}ms)"
                if dep["error"]:
                    line += f" - {dep['error']}"
                typer.echo(line)

    asyncio.run(_health())


@app.command()
def list_repos(
    tag: str | None = typer.Option(None, "--tag", "-t", help="Filter repositories by tag"),
    role: str | None = typer.Option(None, "--role", "-r", help="Filter repositories by role"),
) -> None:
    """
    List repositories in ecosystem.yaml.

    Can filter by tag or role (but not both).
    """
    maha_app = MahavishnuApp()

    # Initialize auth handler
    auth_handler = MultiAuthHandler(maha_app.config)

    # Check if Claude Code subscription is available
    if auth_handler.is_claude_subscribed():
        typer.echo("Using Claude Code subscription authentication")
    elif maha_app.config.auth.enabled and maha_app.config.auth.secret:
        typer.echo("Using JWT authentication")
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
        typer.echo(f"\n  {role.get('name').upper()}")  # type: ignore[union-attr]
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
    typer.echo(f"\n{role.get('name').upper()}")  # type: ignore[union-attr]
    typer.echo("=" * len(role.get("name")))  # type: ignore[arg-type]
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
        nicknames = MahavishnuApp.get_repo_nicknames(repo)
        path = repo.get("path")
        typer.echo(f"  - {name}", nl=False)
        if nicknames:
            label = "nickname" if len(nicknames) == 1 else "nicknames"
            typer.echo(f" ({label}: {', '.join(nicknames)})", nl=False)
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


# Add cross-repository coordination commands
add_coordination_commands(app)

# Add metrics commands
add_metrics_commands(app)

# Add routing commands
add_routing_commands(app)

# Add team commands
add_team_commands(app)

# Add events commands
add_events_commands(app)
# Add code indexing commands
add_index_commands(app)

# Add rollback commands (audit H8: bodai-crow + distilled-workflow)
add_rollback_commands(app)

# Add scaffold CLI
app.add_typer(scaffold_app, name="scaffold")

# Repo diff / PR create (Plan 3 Tier 1)
from .repo_cli import repo_app

app.add_typer(repo_app, name="repo")

# Add precommit CLI (Spec #2)
app.add_typer(precommit_app_obj, name="precommit")

# Add SOP evolution CLI (Spec #7)
add_sop_commands(app)

# Worker management
workers_app = typer.Typer(help="Worker orchestration and management")
app.add_typer(workers_app, name="workers")


@workers_app.command("spawn")
def workers_spawn(
    worker_type: str = typer.Option(
        "terminal-claude",
        "--type",
        "-t",
        help=(
            "Type of worker "
            "(terminal-qwen [legacy], terminal-claude, terminal-codex, terminal-openclaw, "
            "gateway-openclaw, container-executor)"
        ),
    ),
    count: int = typer.Option(1, "--count", "-n", min=1, max=50, help="Number of workers to spawn"),
) -> None:
    """Spawn worker instances for task execution.

    Example:
        $ mahavishnu workers spawn --type terminal-claude --count 3
        $ mahavishnu workers spawn -t terminal-claude -n 5
        $ mahavishnu workers spawn -t terminal-codex -n 2
        $ mahavishnu workers spawn -t terminal-openclaw -n 2
    """

    async def _spawn():
        from .terminal.manager import TerminalManager
        from .workers import WorkerManager

        maha_app = MahavishnuApp()

        # Check if workers are enabled
        if not getattr(maha_app.config, "workers_enabled", True):
            typer.echo("ERROR: Worker orchestration is disabled")
            raise typer.Exit(code=1)

        # Create terminal manager (reusing existing infrastructure)
        terminal_mgr = await TerminalManager.create(
            maha_app.config,
            mcp_client=_resolve_crow_mcp_client(maha_app.config),
        )

        # Create worker manager
        worker_mgr = WorkerManager(
            terminal_manager=terminal_mgr,
            max_concurrent=getattr(maha_app.config, "max_concurrent_workers", 10),
            debug_mode=False,  # Use --debug flag for debug mode
            session_buddy_client=None,  # Will integrate in Phase 2.5
        )

        # Spawn workers
        try:
            worker_ids = await worker_mgr.spawn_workers(
                worker_type=worker_type,
                count=count,
            )

            typer.echo(f"✅ Spawned {len(worker_ids)} {worker_type} workers")
            typer.echo(f"Worker IDs: {', '.join(worker_ids)}")

            # List workers
            workers_list = await worker_mgr.list_workers()
            typer.echo(f"\nActive workers: {len(workers_list)}")

        except Exception as e:
            typer.echo(f"❌ Failed to spawn workers: {e}", err=True)
            raise typer.Exit(code=1)

    asyncio.run(_spawn())


@workers_app.command("execute")
def workers_execute(
    prompt: str = typer.Option(..., "--prompt", "-p", help="Task prompt for AI workers"),
    count: int = typer.Option(3, "--count", "-n", min=1, max=20, help="Number of workers to use"),
    worker_type: str = typer.Option(
        "terminal-claude",
        "--type",
        "-t",
        help=(
            "Type of worker "
            "(terminal-qwen [legacy], terminal-claude, terminal-codex, terminal-openclaw, gateway-openclaw)"
        ),
    ),
    timeout: int = typer.Option(
        300,
        "--timeout",
        "-T",
        min=30,
        max=3600,
        help="Task timeout in seconds",
    ),
) -> None:
    """Execute task on multiple workers concurrently.

    Example:
        $ mahavishnu workers execute --prompt "Implement a REST API" --count 3
        $ mahavishnu workers execute -p "Create a Python class" -n 5 -t terminal-claude
        $ mahavishnu workers execute -p "Draft migration steps for this API" -t terminal-codex
        $ mahavishnu workers execute -p "Review this patch for regressions" -t terminal-claude
        $ mahavishnu workers execute -p "Notify Slack with a deployment summary" -t terminal-openclaw

    Notes:
        Communication-style prompts may be rerouted to gateway-openclaw or
        terminal-openclaw when appropriate.
    """

    async def _execute():
        from .terminal.manager import TerminalManager
        from .workers import WorkerManager
        from .workers.registry import resolve_worker_type

        maha_app = MahavishnuApp()

        # Check if workers are enabled
        if not getattr(maha_app.config, "workers_enabled", True):
            typer.echo("ERROR: Worker orchestration is disabled")
            raise typer.Exit(code=1)

        # Create managers
        terminal_mgr = await TerminalManager.create(
            maha_app.config,
            mcp_client=_resolve_crow_mcp_client(maha_app.config),
        )

        worker_mgr = WorkerManager(
            terminal_manager=terminal_mgr,
            max_concurrent=getattr(maha_app.config, "max_concurrent_workers", 10),
            debug_mode=False,
            session_buddy_client=None,
        )

        resolved_worker_type = resolve_worker_type(
            worker_type,
            task_type="general",
            prompt=prompt,
        )

        # Spawn workers
        typer.echo(f"🚀 Spawning {count} {resolved_worker_type} workers...")
        worker_ids = await worker_mgr.spawn_workers(
            worker_type=resolved_worker_type,
            count=count,
        )
        typer.echo(f"✅ Workers spawned: {', '.join(worker_ids)}")
        if resolved_worker_type != worker_type:
            typer.echo(f"   Routed from {worker_type} to {resolved_worker_type}")

        # Prepare tasks
        tasks = [
            {
                "prompt": prompt,
                "timeout": timeout,
            }
            for _ in range(count)
        ]

        # Execute tasks
        typer.echo(f"\n⚙️  Executing tasks across {count} workers...")
        results = await worker_mgr.execute_batch(worker_ids, tasks)

        # Display results
        typer.echo("\n📊 Results:")
        successful = 0
        failed = 0

        for wid, result in results.items():
            status_emoji = "✅" if result.is_success() else "❌"
            typer.echo(f"{status_emoji} Worker {wid}:")
            typer.echo(f"   Status: {result.status.value}")
            typer.echo(f"   Duration: {result.duration_seconds:.2f}s")

            if result.has_output():
                output_preview = (
                    result.output[:150] + "..." if len(result.output) > 150 else result.output  # type: ignore[arg-type, index]
                )
                typer.echo(f"   Output: {output_preview}")

            if result.error:
                typer.echo(f"   Error: {result.error}")

            if result.is_success():
                successful += 1
            else:
                failed += 1

        typer.echo(f"\n📈 Summary: {successful} successful, {failed} failed")

        # Cleanup workers
        typer.echo("\n🧹 Cleaning up workers...")
        for wid in worker_ids:
            await worker_mgr.close_worker(wid)
        typer.echo("✅ All workers closed")

    asyncio.run(_execute())


_WORKER_CATEGORY_ICONS: dict = {}


def _get_worker_category_icons() -> dict:
    from .workers.registry import WorkerCategory

    return {
        WorkerCategory.AI_ASSISTANT: "🤖",
        WorkerCategory.SHELL: "💻",
        WorkerCategory.CONTAINER: "🐳",
        WorkerCategory.REMOTE: "🌐",
        WorkerCategory.APPLICATION: "🖥️",
    }


def _display_worker_category(cat, workers, check_available: bool, availability: dict) -> None:
    icons = _get_worker_category_icons()
    icon = icons.get(cat, "📦")
    typer.echo(f"{icon} {cat.value.upper().replace('_', ' ')}")
    typer.echo("─" * 40)
    for config in workers:
        if check_available:
            is_available = availability.get(config.worker_type, True)
            status = "✅" if is_available else "❌"
        else:
            is_available = True
            status = "○"
        typer.echo(f"  {status} {config.worker_type}")
        typer.echo(f"      {config.name}")
        if config.description:
            typer.echo(f"      {config.description}")
        if config.requires_tool and check_available and not is_available:
            typer.echo(f"      ⚠️  Requires: {config.requires_tool}")
        typer.echo("")


def _display_availability_summary(availability: dict, get_worker_config) -> None:
    available_count = sum(1 for v in availability.values() if v)
    typer.echo(f"📊 {available_count}/{len(availability)} worker types available")
    unavailable = [k for k, v in availability.items() if not v]
    if unavailable:
        typer.echo("\n⚠️  Unavailable workers (missing dependencies):")
        for worker_type in unavailable:
            config = get_worker_config(worker_type)
            if config:
                typer.echo(f"   - {worker_type}: install {config.requires_tool}")


@workers_app.command("list-types")
def workers_list_types(
    category: str | None = typer.Option(
        None,
        "--category",
        "-c",
        help="Filter by category (ai_assistant, shell, remote, container, application)",
    ),
    check_available: bool = typer.Option(
        True,
        "--check/--no-check",
        help="Check if required tools are installed",
    ),
) -> None:
    """List available worker types.

    Shows all worker types organized by category with descriptions
    and availability status.

    Example:
        $ mahavishnu workers list-types
        $ mahavishnu workers list-types --category ai_assistant
        $ mahavishnu workers list-types --no-check
    """
    from .workers.registry import (
        WorkerCategory,
        get_worker_config,
        get_workers_by_category,
        validate_worker_dependencies,
    )

    category_enum = None
    if category:
        try:
            category_enum = WorkerCategory(category.lower())
        except ValueError:
            typer.echo(f"Invalid category: {category}")
            typer.echo(f"Valid categories: {', '.join(c.value for c in WorkerCategory)}")
            raise typer.Exit(code=1)

    workers_by_category = get_workers_by_category()
    availability = validate_worker_dependencies() if check_available else {}

    typer.echo("\n📋 Available Worker Types\n")
    for cat, workers in workers_by_category.items():
        if category_enum and cat != category_enum:
            continue
        _display_worker_category(cat, workers, check_available, availability)

    if check_available:
        _display_availability_summary(availability, get_worker_config)


# Pool management
pool_app = typer.Typer(help="Multi-pool orchestration and management")
app.add_typer(pool_app, name="pool")


@pool_app.command("spawn")
def pool_spawn(
    pool_type: str = typer.Option(
        "mahavishnu",
        "--type",
        "-t",
        help="Type of pool (mahavishnu, session-buddy, runpod)",
    ),
    name: str = typer.Option("default", "--name", "-n", help="Pool name"),
    min_workers: int = typer.Option(1, "--min", "-m", min=1, max=10, help="Minimum workers"),
    max_workers: int = typer.Option(10, "--max", "-M", min=1, max=100, help="Maximum workers"),
    worker_type: str = typer.Option(
        "terminal-claude",
        "--worker-type",
        "-w",
        help=(
            "Worker type "
            "(terminal-qwen [legacy], terminal-claude, terminal-codex, terminal-openclaw, "
            "gateway-openclaw, container-executor)"
        ),
    ),
) -> None:
    """Spawn a new worker pool.

    Example:
        $ mahavishnu pool spawn --type mahavishnu --name local --min 2 --max 5
        $ mahavishnu pool spawn -t session-buddy -n delegated
        $ mahavishnu pool spawn -t mahavishnu -n comms --worker-type gateway-openclaw
    """

    async def _spawn():
        from .pools import PoolConfig, PoolManager
        from .terminal.manager import TerminalManager

        maha_app = MahavishnuApp()

        # Check if pools are enabled
        if not getattr(maha_app.config, "pools_enabled", True):
            typer.echo("ERROR: Pool management is disabled")
            raise typer.Exit(code=1)

        # Create terminal manager
        terminal_mgr = await TerminalManager.create(
            maha_app.config,
            mcp_client=_resolve_crow_mcp_client(maha_app.config),
        )

        # Create pool manager
        from .mcp.protocols.message_bus import MessageBus

        message_bus = MessageBus()
        pool_mgr = PoolManager(
            terminal_manager=terminal_mgr,
            session_buddy_client=maha_app.session_buddy,
            message_bus=message_bus,
        )

        # Create pool config
        config = PoolConfig(
            name=name,
            pool_type=pool_type,
            min_workers=min_workers,
            max_workers=max_workers,
            worker_type=worker_type,
        )

        # Spawn pool
        try:
            pool_id = await pool_mgr.spawn_pool(pool_type, config)
            typer.echo(f"✅ Spawned {pool_type} pool: {pool_id}")
            typer.echo(f"   Name: {name}")
            typer.echo(f"   Workers: {min_workers}-{max_workers}")
            typer.echo(f"   Worker type: {worker_type}")

        except Exception as e:
            typer.echo(f"❌ Failed to spawn pool: {e}", err=True)
            raise typer.Exit(code=1)

    asyncio.run(_spawn())


@pool_app.command("list")
def pool_list() -> None:
    """List all active pools.

    Example:
        $ mahavishnu pool list
    """

    async def _list():
        maha_app = MahavishnuApp()

        if not hasattr(maha_app, "pool_manager") or maha_app.pool_manager is None:
            typer.echo("No pool manager initialized")
            raise typer.Exit(code=1)

        try:
            pools = await maha_app.pool_manager.list_pools()

            if not pools:
                typer.echo("No active pools")
                return

            typer.echo(f"Active pools: {len(pools)}\n")
            for pool in pools:
                typer.echo(f"  📦 {pool['pool_id']}")
                typer.echo(f"     Type: {pool['pool_type']}")
                typer.echo(f"     Name: {pool['name']}")
                typer.echo(f"     Status: {pool['status']}")
                typer.echo(
                    f"     Workers: {pool['workers']} ({pool['min_workers']}-{pool['max_workers']})"
                )
                typer.echo("")

        except Exception as e:
            typer.echo(f"❌ Failed to list pools: {e}", err=True)
            raise typer.Exit(code=1)

    asyncio.run(_list())


@pool_app.command("execute")
def pool_execute(
    pool_id: str = typer.Argument(..., help="Pool ID to execute on"),
    prompt: str = typer.Option(..., "--prompt", "-p", help="Task prompt"),
    timeout: int = typer.Option(
        300, "--timeout", "-T", min=30, max=3600, help="Timeout in seconds"
    ),
) -> None:
    """Execute task on specific pool.

    Example:
        $ mahavishnu pool execute pool_abc --prompt "Write Python code"
    """

    async def _execute():
        maha_app = MahavishnuApp()

        if not hasattr(maha_app, "pool_manager") or maha_app.pool_manager is None:
            typer.echo("No pool manager initialized")
            raise typer.Exit(code=1)

        try:
            result = await maha_app.pool_manager.execute_on_pool(
                pool_id,
                {"prompt": prompt, "timeout": timeout},
            )

            typer.echo(f"✅ Task completed on pool: {pool_id}")
            typer.echo(f"   Status: {result['status']}")
            if result.get("output"):
                typer.echo(f"   Output:\n{result['output']}")
            if result.get("error"):
                typer.echo(f"   Error: {result['error']}")

        except ValueError as e:
            typer.echo(f"❌ {e}", err=True)
            raise typer.Exit(code=1)
        except Exception as e:
            typer.echo(f"❌ Failed to execute task: {e}", err=True)
            raise typer.Exit(code=1)

    asyncio.run(_execute())


@pool_app.command("route")
def pool_route(
    prompt: str = typer.Option(..., "--prompt", "-p", help="Task prompt"),
    selector: str = typer.Option(
        "least_loaded",
        "--selector",
        "-s",
        help="Pool selector (round_robin, least_loaded, random)",
    ),
    timeout: int = typer.Option(
        300, "--timeout", "-T", min=30, max=3600, help="Timeout in seconds"
    ),
) -> None:
    """Execute task with automatic pool routing.

    Example:
        $ mahavishnu pool route --prompt "Write tests" --selector least_loaded
    """

    async def _route():
        from .pools import PoolSelector

        maha_app = MahavishnuApp()

        if not hasattr(maha_app, "pool_manager") or maha_app.pool_manager is None:
            typer.echo("No pool manager initialized")
            raise typer.Exit(code=1)

        try:
            pool_selector = PoolSelector(selector)
            result = await maha_app.pool_manager.route_task(
                {"prompt": prompt, "timeout": timeout},
                pool_selector=pool_selector,
            )

            typer.echo(f"✅ Task routed to pool: {result['pool_id']}")
            typer.echo(f"   Status: {result['status']}")
            if result.get("output"):
                typer.echo(f"   Output:\n{result['output']}")

        except ValueError as e:
            typer.echo(f"❌ {e}", err=True)
            raise typer.Exit(code=1)
        except Exception as e:
            typer.echo(f"❌ Failed to route task: {e}", err=True)
            raise typer.Exit(code=1)

    asyncio.run(_route())


@pool_app.command("scale")
def pool_scale(
    pool_id: str = typer.Argument(..., help="Pool ID to scale"),
    target: int = typer.Option(..., "--target", "-t", min=1, max=100, help="Target worker count"),
) -> None:
    """Scale pool to target worker count.

    Example:
        $ mahavishnu pool scale pool_abc --target 10
    """

    async def _scale():
        maha_app = MahavishnuApp()

        if not hasattr(maha_app, "pool_manager") or maha_app.pool_manager is None:
            typer.echo("No pool manager initialized")
            raise typer.Exit(code=1)

        try:
            pool = maha_app.pool_manager._pools.get(pool_id)
            if not pool:
                typer.echo(f"❌ Pool not found: {pool_id}", err=True)
                raise typer.Exit(code=1)

            await pool.scale(target)
            typer.echo(f"✅ Scaled pool {pool_id} to {target} workers")
            typer.echo(f"   Current workers: {len(pool._workers)}")

        except NotImplementedError as e:
            typer.echo(f"❌ {e}", err=True)
            raise typer.Exit(code=1)
        except Exception as e:
            typer.echo(f"❌ Failed to scale pool: {e}", err=True)
            raise typer.Exit(code=1)

    asyncio.run(_scale())


@pool_app.command("close")
def pool_close(
    pool_id: str = typer.Argument(..., help="Pool ID to close"),
) -> None:
    """Close a specific pool.

    Example:
        $ mahavishnu pool close pool_abc
    """

    async def _close():
        maha_app = MahavishnuApp()

        if not hasattr(maha_app, "pool_manager") or maha_app.pool_manager is None:
            typer.echo("No pool manager initialized")
            raise typer.Exit(code=1)

        try:
            await maha_app.pool_manager.close_pool(pool_id)
            typer.echo(f"✅ Closed pool: {pool_id}")

        except Exception as e:
            typer.echo(f"❌ Failed to close pool: {e}", err=True)
            raise typer.Exit(code=1)

    asyncio.run(_close())


@pool_app.command("close-all")
def pool_close_all() -> None:
    """Close all active pools.

    Example:
        $ mahavishnu pool close-all
    """

    async def _close_all():
        maha_app = MahavishnuApp()

        if not hasattr(maha_app, "pool_manager") or maha_app.pool_manager is None:
            typer.echo("No pool manager initialized")
            raise typer.Exit(code=1)

        try:
            await maha_app.pool_manager.close_all()
            typer.echo("✅ All pools closed")

        except Exception as e:
            typer.echo(f"❌ Failed to close pools: {e}", err=True)
            raise typer.Exit(code=1)

    asyncio.run(_close_all())


@pool_app.command("health")
def pool_health() -> None:
    """Get health status of all pools.

    Example:
        $ mahavishnu pool health
    """

    async def _health():
        maha_app = MahavishnuApp()

        if not hasattr(maha_app, "pool_manager") or maha_app.pool_manager is None:
            typer.echo("No pool manager initialized")
            raise typer.Exit(code=1)

        try:
            health = await maha_app.pool_manager.health_check()

            typer.echo(f"Pool Manager Health: {health['status']}")
            typer.echo(f"Active pools: {health['pools_active']}\n")

            if health.get("pools"):
                for pool in health["pools"]:
                    status_emoji = "✅" if pool["status"] == "running" else "⚠️"
                    typer.echo(f"  {status_emoji} {pool['pool_id']}")
                    typer.echo(f"     Type: {pool['pool_type']}")
                    typer.echo(f"     Workers: {pool['workers']}")
                    typer.echo("")

        except Exception as e:
            typer.echo(f"❌ Failed to get health: {e}", err=True)
            raise typer.Exit(code=1)

    asyncio.run(_health())


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


@app.command("dashboard")
def dashboard_cmd() -> None:
    """Launch the read-only ecosystem dashboard (Textual TUI).

    Provides four screens: Overview, Sweep, Routing, Alerts.

    Example:
        $ mahavishnu dashboard
    """
    try:
        from mahavishnu.tui.app import DashboardApp
    except ImportError:
        typer.echo("ERROR: textual not installed. Install with: pip install mahavishnu[tui]")
        raise typer.Exit(code=1) from None

    app = DashboardApp()
    app.run()


if __name__ == "__main__":
    app()
