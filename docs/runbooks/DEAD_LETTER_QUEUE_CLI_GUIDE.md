# Dead Letter Queue CLI Integration Guide

## Overview

This guide shows how to integrate Dead Letter Queue CLI commands into the Mahavishnu CLI for operational management of failed workflows.

## CLI Commands to Add

Add these commands to `mahavishnu/cli.py`:

### 1. DLQ Status Command

```python
@app.command()
def dlq_status(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Show Dead Letter Queue status and statistics.

    Example:
        mahavishnu dlq status
        mahavishnu dlq status --json
    """
    import asyncio
    from rich.console import Console
    from rich.table import Table

    app = ctx.ensure_object(dict)["app"]

    async def show_status():
        if not app.dlq:
            console.print("[yellow]DLQ is not enabled[/yellow]")
            return

        stats = asyncio.run(app.dlq.get_statistics())

        if json_output:
            import json
            console.print(json.dumps(stats, indent=2))
            return

        # Rich table output
        console = Console()
        console.print("\n[bold cyan]Dead Letter Queue Status[/bold cyan]\n")

        # Overall stats
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Queue Size", f"{stats['queue_size']:,} / {stats['max_size']:,}")
        table.add_row("Utilization", f"{stats['utilization_percent']:.2f}%")
        table.add_row("Processor Running", "✓" if stats['is_processor_running'] else "✗")

        if stats['is_processor_running']:
            table.add_row("Retry Interval", f"{stats['retry_interval_seconds']}s")

        console.print(table)

        # Status breakdown
        console.print("\n[bold]Status Breakdown[/bold]")
        status_table = Table(show_header=True)
        status_table.add_column("Status")
        status_table.add_column("Count")

        for status, count in stats['status_breakdown'].items():
            status_table.add_row(status.capitalize(), str(count))

        console.print(status_table)

        # Error categories
        if stats['error_categories']:
            console.print("\n[bold]Error Categories[/bold]")
            cat_table = Table(show_header=True)
            cat_table.add_column("Category")
            cat_table.add_column("Count")

            for category, count in sorted(stats['error_categories'].items(), key=lambda x: x[1], reverse=True):
                cat_table.add_row(category.capitalize(), str(count))

            console.print(cat_table)

        # Lifetime stats
        console.print("\n[bold]Lifetime Statistics[/bold]")
        lifetime_table = Table(show_header=True)
        lifetime_table.add_column("Metric")
        lifetime_table.add_column("Count")

        for metric, count in stats['lifetime_stats'].items():
            lifetime_table.add_row(metric.replace("_", " ").title(), str(count))

        console.print(lifetime_table)

    asyncio.run(show_status())
```

### 2. List DLQ Tasks Command

```python
@app.command()
def dlq_list(
    ctx: typer.Context,
    status: str = typer.Option(None, "--status", "-s", help="Filter by status (pending, retrying, exhausted, completed, archived)"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of tasks to show"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List tasks in the Dead Letter Queue.

    Example:
        mahavishnu dlq list
        mahavishnu dlq list --status exhausted --limit 20
        mahavishnu dlq list --json
    """
    import asyncio
    from rich.console import Console
    from rich.table import Table
    from datetime import datetime

    app = ctx.ensure_object(dict)["app"]

    async def list_tasks():
        if not app.dlq:
            console.print("[yellow]DLQ is not enabled[/yellow]")
            return

        # Convert status string to enum
        from mahavishnu.core.dead_letter_queue import DeadLetterStatus
        status_filter = DeadLetterStatus(status) if status else None

        tasks = await app.dlq.list_tasks(status=status_filter, limit=limit)

        if json_output:
            import json
            task_dicts = [task.to_dict() for task in tasks]
            console.print(json.dumps(task_dicts, indent=2))
            return

        console = Console()

        if not tasks:
            console.print("[yellow]No tasks found in DLQ[/yellow]")
            return

        console.print(f"\n[bold cyan]DLQ Tasks[/bold cyan] ({len(tasks)} shown)\n")

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Task ID", style="cyan")
        table.add_column("Status", style="yellow")
        table.add_column("Error Category", style="blue")
        table.add_column("Retries", style="green")
        table.add_column("Failed At", style="dim")
        table.add_column("Error", style="red")

        for task in tasks:
            # Format timestamp
            failed_at = task.failed_at.strftime("%Y-%m-%d %H:%M:%S") if task.failed_at else "N/A"

            # Format retries
            retry_str = f"{task.retry_count}/{task.max_retries}"

            # Truncate error
            error = task.error[:50] + "..." if len(task.error) > 50 else task.error

            table.add_row(
                task.task_id,
                task.status.value,
                task.error_category or "N/A",
                retry_str,
                failed_at,
                error,
            )

        console.print(table)

        if len(tasks) == limit:
            console.print(f"\n[dim]Showing {limit} tasks (use --limit to show more)[/dim]")

    asyncio.run(list_tasks())
```

### 3. Show DLQ Task Details

```python
@app.command()
def dlq_show(
    ctx: typer.Context,
    task_id: str = typer.Argument(..., help="Task ID to inspect"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Show detailed information about a specific DLQ task.

    Example:
        mahavishnu dlq show wf_abc123
        mahavishnu dlq show wf_abc123 --json
    """
    import asyncio
    import json
    from rich.console import Console
    from rich.panel import Panel
    from rich.syntax import Syntax

    app = ctx.ensure_object(dict)["app"]

    async def show_task():
        if not app.dlq:
            console.print("[yellow]DLQ is not enabled[/yellow]")
            return

        task = await app.dlq.get_task(task_id)

        if not task:
            console.print(f"[red]Task {task_id} not found in DLQ[/red]")
            raise typer.Exit(1)

        console = Console()

        if json_output:
            console.print(json.dumps(task.to_dict(), indent=2))
            return

        # Rich panel output
        console.print(f"\n[bold cyan]DLQ Task: {task_id}[/bold cyan]\n")

        # Basic info
        info_table = Table(show_header=False, box=None)
        info_table.add_column("Field", style="cyan")
        info_table.add_column("Value", style="green")

        info_table.add_row("Task ID", task.task_id)
        info_table.add_row("Status", f"[{task.status_color}]{task.status.value}[/{task.status_color}]")
        info_table.add_row("Error Category", task.error_category or "N/A")
        info_table.add_row("Retries", f"{task.retry_count}/{task.max_retries}")
        info_table.add_row("Total Attempts", str(task.total_attempts))
        info_table.add_row("Retry Policy", task.retry_policy.value)

        if task.next_retry_at:
            retry_in = task.next_retry_at - datetime.now(task.next_retry_at.tzinfo)
            info_table.add_row("Next Retry At", task.next_retry_at.strftime("%Y-%m-%d %H:%M:%S UTC"))
            info_table.add_row("Retry In", f"{retry_in}")

        info_table.add_row("Failed At", task.failed_at.strftime("%Y-%m-%d %H:%M:%S UTC"))

        console.print(Panel(info_table, title="[bold]Basic Information[/bold]"))

        # Error
        console.print("\n[bold]Error:[/bold]")
        console.print(f"[red]{task.error}[/red]")

        if task.last_error and task.last_error != task.error:
            console.print(f"\n[bold]Last Error:[/bold]")
            console.print(f"[red]{task.last_error}[/red]")

        # Repositories
        console.print(f"\n[bold]Repositories ({len(task.repos)}):[/bold]")
        for repo in task.repos:
            console.print(f"  • {repo}")

        # Task specification
        console.print(f"\n[bold]Task Specification:[/bold]")
        task_json = json.dumps(task.task, indent=2)
        syntax = Syntax(task_json, "json", theme="monokai", line_numbers=True)
        console.print(Panel(syntax, title="Task"))

        # Metadata
        if task.metadata:
            console.print(f"\n[bold]Metadata:[/bold]")
            metadata_json = json.dumps(task.metadata, indent=2)
            syntax = Syntax(metadata_json, "json", theme="monokai", line_numbers=False)
            console.print(Panel(syntax, title="Metadata"))

    asyncio.run(show_task())
```

### 4. Retry DLQ Task

```python
@app.command()
def dlq_retry(
    ctx: typer.Context,
    task_id: str = typer.Argument(..., help="Task ID to retry"),
):
    """Manually retry a specific DLQ task.

    Example:
        mahavishnu dlq retry wf_abc123
    """
    import asyncio
    from rich.console import Console

    app = ctx.ensure_object(dict)["app"]

    async def retry_task():
        if not app.dlq:
            console.print("[yellow]DLQ is not enabled[/yellow]")
            raise typer.Exit(1)

        console = Console()
        console.print(f"[cyan]Retrying task {task_id}...[/cyan]")

        result = await app.dlq.retry_task(task_id)

        if result["success"]:
            console.print(f"[green]✓ Task {task_id} retried successfully[/green]")
            console.print(f"  Result: {result.get('result', 'N/A')}")
        else:
            console.print(f"[red]✗ Task {task_id} retry failed[/red]")
            console.print(f"  Error: {result.get('error', 'Unknown error')}")
            raise typer.Exit(1)

    asyncio.run(retry_task())
```

### 5. Archive DLQ Task

```python
@app.command()
def dlq_archive(
    ctx: typer.Context,
    task_id: str = typer.Argument(..., help="Task ID to archive"),
):
    """Archive a DLQ task (remove from active queue).

    Example:
        mahavishnu dlq archive wf_abc123
    """
    import asyncio
    from rich.console import Console

    app = ctx.ensure_object(dict)["app"]

    async def archive_task():
        if not app.dlq:
            console.print("[yellow]DLQ is not enabled[/yellow]")
            raise typer.Exit(1)

        console = Console()

        result = await app.dlq.archive_task(task_id)

        if result:
            console.print(f"[green]✓ Task {task_id} archived[/green]")
        else:
            console.print(f"[red]✗ Task {task_id} not found[/red]")
            raise typer.Exit(1)

    asyncio.run(archive_task())
```

### 6. Clear DLQ

```python
@app.command()
def dlq_clear(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
    status: str = typer.Option(None, "--status", "-s", help="Only clear tasks with specific status"),
):
    """Clear all tasks from the Dead Letter Queue.

    WARNING: This is a destructive operation!

    Example:
        mahavishnu dlq clear --force
        mahavishnu dlq clear --status exhausted
    """
    import asyncio
    from rich.console import Console
    from rich.prompt import Confirm

    app = ctx.ensure_object(dict)["app"]

    async def clear_queue():
        if not app.dlq:
            console.print("[yellow]DLQ is not enabled[/yellow]")
            raise typer.Exit(1)

        console = Console()

        # Get current stats
        stats = await app.dlq.get_statistics()
        queue_size = stats["queue_size"]

        if queue_size == 0:
            console.print("[yellow]DLQ is already empty[/yellow]")
            return

        # Confirm
        if not force:
            console.print(f"[red]WARNING: This will remove {queue_size} tasks from the DLQ![/red]")
            if not Confirm.ask("Are you sure you want to continue?"):
                console.print("Aborted")
                raise typer.Exit()

        # Clear
        count = await app.dlq.clear_all()
        console.print(f"[green]✓ Cleared {count} tasks from DLQ[/green]")

    asyncio.run(clear_queue())
```

### 7. Start DLQ Processor

```python
@app.command()
def dlq_start_processor(
    ctx: typer.Context,
    interval: int = typer.Option(60, "--interval", "-i", help="Check interval in seconds"),
):
    """Start the DLQ retry processor.

    Example:
        mahavishnu dlq start-processor
        mahavishnu dlq start-processor --interval 30
    """
    import asyncio
    from rich.console import Console

    app = ctx.ensure_object(dict)["app"]

    async def start_processor():
        if not app.dlq:
            console.print("[yellow]DLQ is not enabled[/yellow]")
            raise typer.Exit(1)

        console = Console()

        # Define retry callback
        async def dlq_retry_callback(task, repos):
            adapter_name = task.get("adapter", "llamaindex")
            return await app.execute_workflow_parallel(
                task=task,
                adapter_name=adapter_name,
                repos=repos,
            )

        console.print(f"[cyan]Starting DLQ retry processor (interval={interval}s)...[/cyan]")

        try:
            await app.dlq.start_retry_processor(
                callback=dlq_retry_callback,
                check_interval_seconds=interval,
            )
            console.print("[green]✓ DLQ retry processor started[/green]")
            console.print("\n[dim]Processor is running in the background.[/dim]")
            console.print("[dim]Press Ctrl+C to stop.[/dim]")

            # Keep running until interrupted
            try:
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                console.print("\n[yellow]Stopping DLQ retry processor...[/yellow]")
                await app.dlq.stop_retry_processor()
                console.print("[green]✓ DLQ retry processor stopped[/green]")

        except Exception as e:
            console.print(f"[red]✗ Failed to start DLQ retry processor: {e}[/red]")
            raise typer.Exit(1)

    asyncio.run(start_processor())
```

### 8. Stop DLQ Processor

```python
@app.command()
def dlq_stop_processor(
    ctx: typer.Context,
):
    """Stop the DLQ retry processor.

    Example:
        mahavishnu dlq stop-processor
    """
    import asyncio
    from rich.console import Console

    app = ctx.ensure_object(dict)["app"]

    async def stop_processor():
        if not app.dlq:
            console.print("[yellow]DLQ is not enabled[/yellow]")
            raise typer.Exit(1)

        console = Console()
        console.print("[cyan]Stopping DLQ retry processor...[/cyan]")

        await app.dlq.stop_retry_processor()

        console.print("[green]✓ DLQ retry processor stopped[/green]")

    asyncio.run(stop_processor())
```

## CLI Group Structure

Organize the commands under a `dlq` group:

```python
# Create DLQ command group
@app.group()
def dlq():
    """Dead Letter Queue management commands."""
    pass

# Add commands to the group
@dlq.command()
def status(...):
    """Show DLQ status and statistics."""
    pass

@dlq.command()
def list(...):
    """List tasks in the DLQ."""
    pass

@dlq.command()
def show(...):
    """Show detailed task information."""
    pass

@dlq.command()
def retry(...):
    """Manually retry a task."""
    pass

@dlq.command()
def archive(...):
    """Archive a task."""
    pass

@dlq.command()
def clear(...):
    """Clear all tasks from DLQ."""
    pass

@dlq.command()
def start_processor(...):
    """Start the DLQ retry processor."""
    pass

@dlq.command()
def stop_processor(...):
    """Stop the DLQ retry processor."""
    pass
```

## Usage Examples

### Check DLQ Status

```bash
# Show status with rich formatting
mahavishnu dlq status

# Show status as JSON
mahavishnu dlq status --json
```

### List DLQ Tasks

```bash
# List all pending tasks
mahavishnu dlq list

# List exhausted tasks
mahavishnu dlq list --status exhausted

# List more tasks
mahavishnu dlq list --limit 100

# Output as JSON
mahavishnu dlq list --json
```

### Inspect Task Details

```bash
# Show task details
mahavishnu dlq show wf_abc123

# Show as JSON
mahavishnu dlq show wf_abc123 --json
```

### Manual Operations

```bash
# Manually retry a task
mahavishnu dlq retry wf_abc123

# Archive a task
mahavishnu dlq archive wf_abc123

# Clear all tasks (with confirmation)
mahavishnu dlq clear

# Clear without confirmation
mahavishnu dlq clear --force

# Clear only exhausted tasks
mahavishnu dlq clear --status exhausted
```

### Processor Management

```bash
# Start processor with default interval (60s)
mahavishnu dlq start-processor

# Start processor with 30s interval
mahavishnu dlq start-processor --interval 30

# Stop processor
mahavishnu dlq stop-processor
```

## Integration Testing

Test the CLI integration:

```bash
# Enable DLQ and start processor
mahavishnu dlq start-processor &

# Trigger a failed workflow
mahavishnu execute code-sweep --adapter llamaindex --repo /invalid/path

# Check DLQ status
mahavishnu dlq status

# List failed tasks
mahavishnu dlq list

# Show task details
mahavishnu dlq show wf_abc123

# Manually retry
mahavishnu dlq retry wf_abc123

# Stop processor
mahavishnu dlq stop-processor
```

## Error Handling

```python
# Handle DLQ not enabled
if not app.dlq:
    console.print("[yellow]DLQ is not enabled in configuration[/yellow]")
    console.print("Enable with: dlq_enabled: true in settings/mahavishnu.yaml")
    raise typer.Exit(1)

# Handle task not found
task = await app.dlq.get_task(task_id)
if not task:
    console.print(f"[red]Task {task_id} not found[/red]")
    raise typer.Exit(1)

# Handle processor already running
if dlq._is_running:
    console.print("[yellow]Processor is already running[/yellow]")
    console.print("Stop it first with: mahavishnu dlq stop-processor")
    raise typer.Exit(1)
```

## Tab Completion

Add shell completion for task IDs and status values:

```python
def complete_task_ids(incomplete: str) -> List[str]:
    """Complete DLQ task IDs."""
    import asyncio
    app = get_app()
    if not app.dlq:
        return []

    async def get_ids():
        tasks = await app.dlq.list_tasks(limit=100)
        return [t.task_id for t in tasks if t.task_id.startswith(incomplete)]

    return asyncio.run(get_ids())

@app.command()
def dlq_show(
    task_id: str = typer.Argument(
        ...,
        autocompletion=complete_task_ids,
        help="Task ID to inspect"
    ),
):
    """Show detailed task information."""
    pass
```

This provides comprehensive CLI management of the Dead Letter Queue with rich formatting, JSON output options, and full operational control.
