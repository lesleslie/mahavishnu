"""CLI commands for worktree management."""

import asyncio
from datetime import datetime, timedelta, timezone
import json

import typer

from .core.app import MahavishnuApp
from .core.worktree_session_registry import SessionWorktreeRegistry

worktree_app = typer.Typer(help="Manage git worktrees across the ecosystem")


def _run_async(coro):
    """Run async coroutine.

    Args:
        coro: Async coroutine to execute

    Returns:
        Result of the coroutine execution
    """
    return asyncio.run(coro)


@worktree_app.command("create")
def create_worktree(
    repo_nickname: str = typer.Argument(..., help="Repository nickname"),
    branch: str = typer.Argument(..., help="Branch name"),
    name: str = typer.Option(None, "--name", "-n", help="Custom worktree name"),
    create_branch: bool = typer.Option(
        False, "--create-branch", "-b", help="Create branch if doesn't exist"
    ),
):
    """Create a new worktree with safety checks."""

    async def _create():
        app = MahavishnuApp.load()

        # Initialize worktree coordinator
        await app.initialize_worktree_coordinator()

        if not app.worktree_coordinator:
            typer.echo("❌ WorktreeCoordinator not available")
            raise typer.Exit(code=1)

        result = await app.worktree_coordinator.create_worktree(
            repo_nickname=repo_nickname,
            branch=branch,
            worktree_name=name,
            create_branch=create_branch,
            user_id=None,  # CLI user
        )

        if result.get("success"):
            typer.echo(f"✅ Created worktree: {result.get('worktree_path', 'N/A')}")
        else:
            typer.echo(f"❌ Failed: {result.get('error', 'Unknown error')}", err=True)
            raise typer.Exit(code=1)

    _run_async(_create())


@worktree_app.command("remove")
def remove_worktree(
    repo_nickname: str = typer.Argument(..., help="Repository nickname"),
    worktree_path: str = typer.Argument(..., help="Path to worktree"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip safety checks"),
    force_reason: str = typer.Option(
        None,
        "--force-reason",
        "-r",
        help="Required reason when using --force with uncommitted changes",
    ),
):
    """Remove a worktree with safety validation."""

    async def _remove():
        app = MahavishnuApp.load()

        # Initialize worktree coordinator
        await app.initialize_worktree_coordinator()

        if not app.worktree_coordinator:
            typer.echo("❌ WorktreeCoordinator not available")
            raise typer.Exit(code=1)

        # Show safety status first
        status = await app.worktree_coordinator.get_worktree_safety_status(
            repo_nickname=repo_nickname,
            worktree_path=worktree_path,
        )

        if not force:
            if status.get("uncommitted_changes"):
                typer.echo("⚠️  Worktree has uncommitted changes!")
                if not typer.confirm("Continue anyway?"):
                    typer.echo("Removal cancelled")
                    raise typer.Exit()

            if status.get("dependencies"):
                dependents = status["dependencies"]
                typer.echo(f"⚠️  {len(dependents)} repos depend on this worktree:")
                for dep in dependents:
                    typer.echo(f"  - {dep}")
                if not typer.confirm("Remove anyway?"):
                    typer.echo("Removal cancelled")
                    raise typer.Exit()

        result = await app.worktree_coordinator.remove_worktree(
            repo_nickname=repo_nickname,
            worktree_path=worktree_path,
            force=force,
            force_reason=force_reason,
            user_id=None,  # CLI user
        )

        if result.get("success"):
            typer.echo(f"✅ Removed worktree: {worktree_path}")
            if result.get("backup_path"):
                typer.echo(f"💾 Backup created: {result['backup_path']}")
        else:
            error = result.get("error", "Unknown error")
            typer.echo(f"❌ Failed: {error}", err=True)
            raise typer.Exit(code=1)

    _run_async(_remove())


@worktree_app.command("list")
def list_worktrees(
    repo: str = typer.Option(None, "--repo", "-r", help="Filter by repository"),
):
    """List worktrees across ecosystem."""

    async def _list():
        app = MahavishnuApp.load()

        # Initialize worktree coordinator
        await app.initialize_worktree_coordinator()

        if not app.worktree_coordinator:
            typer.echo("❌ WorktreeCoordinator not available")
            raise typer.Exit(code=1)

        result = await app.worktree_coordinator.list_worktrees(repo_nickname=repo)

        if result.get("success"):
            worktrees = result.get("worktrees", [])
            total = result.get("total_count", len(worktrees))
            typer.echo(f"📋 Worktrees ({total} total):")
            for wt in worktrees:
                status_icon = "✅" if wt.get("exists") else "❌"
                typer.echo(f"  {status_icon} {wt['path']} ({wt['branch']})")
        else:
            typer.echo(f"❌ Failed: {result.get('error', 'Unknown error')}", err=True)
            raise typer.Exit(code=1)

    _run_async(_list())


@worktree_app.command("prune")
def prune_worktrees(
    repo_nickname: str = typer.Argument(..., help="Repository nickname"),
):
    """Prune stale worktree references."""

    async def _prune():
        app = MahavishnuApp.load()

        # Initialize worktree coordinator
        await app.initialize_worktree_coordinator()

        if not app.worktree_coordinator:
            typer.echo("❌ WorktreeCoordinator not available")
            raise typer.Exit(code=1)

        result = await app.worktree_coordinator.prune_worktrees(repo_nickname)

        if result.get("success"):
            count = result.get("pruned_count", 0)
            typer.echo(f"✅ Pruned {count} stale worktrees")
        else:
            typer.echo(f"❌ Failed: {result.get('error', 'Unknown error')}", err=True)
            raise typer.Exit(code=1)

    _run_async(_prune())


@worktree_app.command("safety-status")
def safety_status(
    repo_nickname: str = typer.Argument(..., help="Repository nickname"),
    worktree_path: str = typer.Argument(..., help="Path to worktree"),
):
    """Get safety status for a worktree before removal."""

    async def _status():
        app = MahavishnuApp.load()

        # Initialize worktree coordinator
        await app.initialize_worktree_coordinator()

        if not app.worktree_coordinator:
            typer.echo("❌ WorktreeCoordinator not available")
            raise typer.Exit(code=1)

        status = await app.worktree_coordinator.get_worktree_safety_status(
            repo_nickname=repo_nickname,
            worktree_path=worktree_path,
        )

        typer.echo(f"🔍 Safety Status for {worktree_path}:")
        typer.echo(
            f"   Uncommitted changes: {'⚠️ Yes' if status.get('uncommitted_changes') else '✅ No'}"
        )
        typer.echo(
            f"   Is valid worktree: {'✅ Yes' if status.get('is_valid_worktree') else '❌ No'}"
        )
        typer.echo(f"   Path is safe: {'✅ Yes' if status.get('path_safe') else '❌ No'}")

        dependencies = status.get("dependencies", [])
        if dependencies:
            typer.echo(f"   Dependencies found: {len(dependencies)}")
            for dep in dependencies:
                typer.echo(f"     - {dep}")
        else:
            typer.echo("   ✅ No blocking dependencies")

    _run_async(_status())


@worktree_app.command("provider-health")
def provider_health():
    """Check health of all worktree providers."""

    async def _health():
        app = MahavishnuApp.load()

        # Initialize worktree coordinator
        await app.initialize_worktree_coordinator()

        if not app.worktree_coordinator:
            typer.echo("❌ WorktreeCoordinator not available")
            raise typer.Exit(code=1)

        health_status = await app.worktree_coordinator.get_provider_health()

        typer.echo("🏥 Worktree Provider Health:")
        for provider_name, status in health_status.items():
            if status.get("healthy"):
                typer.echo(f"  ✅ {provider_name}: Healthy")
            else:
                typer.echo(f"  ❌ {provider_name}: Unhealthy")
                if status.get("error"):
                    typer.echo(f"     Error: {status['error']}")

    _run_async(_health())


# ── Session worktree registry subcommands ────────────────────────


@worktree_app.command("list-sessions")
def list_sessions(
    state: str = typer.Option(
        "active",
        "--state",
        help="Filter by state: active|abandoned (or 'all' for no filter)",
    ),
    older_than_days: int = typer.Option(
        None,
        "--older-than-days",
        help="Only show entries older than N days (by last_seen_at or abandoned_at)",
    ),
    registry_path: str = typer.Option(
        None,
        "--registry-path",
        help="Override the registry file location (default: XDG state path)",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON instead of the human-readable table",
    ),
):
    """List Claude sessions with their associated worktrees.

    Reads the SessionWorktreeRegistry (the ``session_id → worktree_path``
    map populated by ``.claude/hooks/worktree-session-isolation.py``).

    Useful for cleaning up orphaned worktrees after long sessions
    accumulate; pair with ``worktree prune-abandoned`` to actually
    remove the on-disk worktrees (always explicit, never automatic).
    """
    from pathlib import Path

    path = Path(registry_path) if registry_path else None
    registry = SessionWorktreeRegistry(path=path)

    state_filter: str | None = None if state == "all" else state
    entries = registry.list_active(
        state=state_filter,
        older_than_days=older_than_days,
    )

    if json_output:
        typer.echo(json.dumps({
            "filter": {"state": state, "older_than_days": older_than_days},
            "count": len(entries),
            "entries": entries,
        }, indent=2, sort_keys=True, default=str))
        return

    if not entries:
        typer.echo(f"No sessions found (state={state}, older_than_days={older_than_days})")
        return

    typer.echo(f"📋 Sessions ({len(entries)}):")
    for entry in entries:
        sid = entry["session_id_short"]
        wt = entry["worktree_path"]
        branch = entry["branch"]
        st = entry["state"]
        last_seen = entry.get("last_seen_at", "?")
        abandoned_at = entry.get("abandoned_at") or "—"
        icon = "✅" if st == "active" else "💤"
        typer.echo(f"  {icon} {sid}  {wt}  branch={branch}  state={st}")
        typer.echo(f"      last_seen={last_seen}  abandoned_at={abandoned_at}")


@worktree_app.command("prune-abandoned")
def prune_abandoned(
    older_than_days: int = typer.Option(
        7,
        "--older-than-days",
        help="Only prune entries abandoned at least N days ago",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be pruned without removing anything",
    ),
    registry_path: str = typer.Option(
        None,
        "--registry-path",
        help="Override the registry file location",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON instead of the human-readable summary",
    ),
):
    """Remove abandoned worktree entries from the registry.

    SAFETY: This command NEVER removes the actual git worktree on disk.
    It only removes the registry entry that tracks the worktree. To
    delete the worktree itself, run::

        mahavishnu worktree remove <repo_nickname> <worktree_path>

    Use ``--dry-run`` to preview.

    Required by the never-auto-remove safety policy (4-lens plan,
    2026-07-16) — abandoned worktrees must be explicitly cleaned up.
    """
    from pathlib import Path

    path = Path(registry_path) if registry_path else None
    registry = SessionWorktreeRegistry(path=path)

    abandoned = registry.list_active(state="abandoned", older_than_days=older_than_days)

    if json_output:
        # For --json, always do the actual remove (no --dry-run semantics
        # in machine-readable mode; the caller is responsible for dry-run
        # semantics by passing --older-than-days=large-enough).
        removed: list[str] = []
        if not dry_run:
            for entry in abandoned:
                registry.remove(entry["session_id_short"])
                removed.append(entry["session_id_short"])
        typer.echo(json.dumps({
            "filter": {"older_than_days": older_than_days, "dry_run": dry_run},
            "would_remove_count": len(abandoned),
            "removed_count": len(removed) if not dry_run else 0,
            "removed_sessions": removed,
        }, indent=2, sort_keys=True))
        return

    if not abandoned:
        typer.echo(f"No abandoned sessions older than {older_than_days} days")
        return

    typer.echo(f"🧹 Found {len(abandoned)} abandoned session(s):")
    for entry in abandoned:
        sid = entry["session_id_short"]
        wt = entry["worktree_path"]
        abandoned_at = entry.get("abandoned_at", "?")
        typer.echo(f"  - {sid}  {wt}  abandoned_at={abandoned_at}")

    if dry_run:
        typer.echo("🔍 Dry run: no changes made. Re-run without --dry-run to apply.")
        return

    for entry in abandoned:
        registry.remove(entry["session_id_short"])
    typer.echo(f"✅ Removed {len(abandoned)} abandoned session(s) from the registry.")
    typer.echo(
        "⚠️  The git worktrees themselves are still on disk. To remove them, run:\n"
        "    mahavishnu worktree remove <repo_nickname> <worktree_path>"
    )
