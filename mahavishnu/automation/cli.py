"""CLI commands for desktop automation.

Provides command-line interface for automation operations.

Usage:
    mahavishnu automation launch-app com.apple.finder
    mahavishnu automation list-apps
    mahavishnu automation list-windows com.apple.finder
    mahavishnu automation type "Hello World"
    mahavishnu automation screenshot --output screenshot.png
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from typing import Annotated, Any

from rich.console import Console
from rich.table import Table
import typer

from mahavishnu.automation import AutomationManager
from mahavishnu.automation.errors import AutomationError
from mahavishnu.automation.models import AutomationConfig

app = typer.Typer(
    name="automation",
    help="Desktop automation commands",
    no_args_is_help=True,
)

console = Console()


def get_manager(dry_run: bool = False) -> AutomationManager:
    """Get or create automation manager."""
    config = AutomationConfig(dry_run_default=dry_run)
    return AutomationManager(config=config)


def format_result(result: Any, output_format: str = "text") -> None:
    """Format and print result."""
    if output_format == "json":
        if hasattr(result, "to_dict"):
            console.print_json(data=result.to_dict())
        elif isinstance(result, dict):
            console.print_json(data=result)
        else:
            console.print_json(data={"result": str(result)})
    else:
        if hasattr(result, "to_dict"):
            console.print(result.to_dict())
        elif isinstance(result, dict):
            console.print(result)
        else:
            console.print(str(result))


async def run_async(coro: Any) -> Any:
    """Run async coroutine."""
    return await coro


# =============================================================================
# Application Commands
# =============================================================================


@app.command("launch-app")
def launch_app(
    bundle_id: Annotated[str, typer.Argument(help="Application bundle identifier")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Simulate without executing")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Launch an application by bundle identifier.

    Example:
        mahavishnu automation launch-app com.apple.finder
    """
    manager = get_manager(dry_run=dry_run)

    async def _run():
        async with manager:
            result = await manager.launch_application(bundle_id)
            return result

    try:
        result = asyncio.run(_run())
        if result.status == "success":
            if not json_output:
                data = result.data or {}
                console.print(f"[green]✓[/green] Launched: {data.get('name', bundle_id)}")
            else:
                format_result(result, "json")
        else:
            console.print(f"[red]✗[/red] {result.error}")
            raise typer.Exit(1)
    except AutomationError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command("list-apps")
def list_apps(
    include_windows: Annotated[
        bool, typer.Option("--windows", help="Include window information")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """List all running applications.

    Example:
        mahavishnu automation list-apps
        mahavishnu automation list-apps --windows
    """
    manager = get_manager()

    async def _run():
        async with manager:
            return await manager.list_applications()

    try:
        result = asyncio.run(_run())

        if result.status != "success":
            console.print(f"[red]Error:[/red] {result.error}")
            raise typer.Exit(1)

        apps = result.data.get("result", result.data) if result.data else []

        if json_output:
            format_result({"apps": apps}, "json")
            return

        table = Table(title="Running Applications")
        table.add_column("Bundle ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("PID", justify="right")
        table.add_column("Active", justify="center")

        for app in apps:
            if isinstance(app, dict):
                table.add_row(
                    app.get("bundle_id", ""),
                    app.get("name", ""),
                    str(app.get("pid", "")),
                    "✓" if app.get("frontmost") else "",
                )

        console.print(table)
    except AutomationError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command("quit-app")
def quit_app(
    bundle_id: Annotated[str, typer.Argument(help="Application bundle identifier")],
    force: Annotated[bool, typer.Option("--force", help="Force quit")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Simulate")] = False,
) -> None:
    """Quit an application.

    Example:
        mahavishnu automation quit-app com.apple.finder
        mahavishnu automation quit-app com.apple.finder --force
    """
    manager = get_manager(dry_run=dry_run)

    async def _run():
        async with manager:
            return await manager.quit_application(bundle_id, force=force)

    try:
        result = asyncio.run(_run())
        if result.status == "success":
            console.print(f"[green]✓[/green] Quit: {bundle_id}")
        else:
            console.print(f"[red]✗[/red] {result.error}")
            raise typer.Exit(1)
    except AutomationError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command("activate-app")
def activate_app(
    bundle_id: Annotated[str, typer.Argument(help="Application bundle identifier")],
) -> None:
    """Activate (bring to front) an application.

    Example:
        mahavishnu automation activate-app com.apple.finder
    """
    manager = get_manager()

    async def _run():
        async with manager:
            return await manager.activate_application(bundle_id)

    try:
        result = asyncio.run(_run())
        if result.status == "success":
            console.print(f"[green]✓[/green] Activated: {bundle_id}")
        else:
            console.print(f"[red]✗[/red] {result.error}")
            raise typer.Exit(1)
    except AutomationError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


# =============================================================================
# Window Commands
# =============================================================================


@app.command("list-windows")
def list_windows(
    bundle_id: Annotated[str, typer.Argument(help="Application bundle identifier")],
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """List windows for an application.

    Example:
        mahavishnu automation list-windows com.apple.finder
    """
    manager = get_manager()

    async def _run():
        async with manager:
            return await manager.get_windows(bundle_id)

    try:
        result = asyncio.run(_run())

        if result.status != "success":
            console.print(f"[red]Error:[/red] {result.error}")
            raise typer.Exit(1)

        windows = result.data.get("result", result.data) if result.data else []

        if json_output:
            format_result({"windows": windows}, "json")
            return

        table = Table(title=f"Windows: {bundle_id}")
        table.add_column("ID", style="dim")
        table.add_column("Title", style="cyan")
        table.add_column("Position", justify="right")
        table.add_column("Size", justify="right")
        table.add_column("Focused", justify="center")

        for win in windows:
            if isinstance(win, dict):
                pos = win.get("position", (0, 0))
                size = win.get("size", (0, 0))
                table.add_row(
                    str(win.get("id", ""))[:8],
                    win.get("title", "")[:40],
                    f"{pos[0]}, {pos[1]}" if pos else "",
                    f"{size[0]}x{size[1]}" if size else "",
                    "✓" if win.get("focused") else "",
                )

        console.print(table)
    except AutomationError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


# =============================================================================
# Input Commands
# =============================================================================


@app.command("type")
def type_text(
    text: Annotated[str, typer.Argument(help="Text to type")],
    interval: Annotated[
        float, typer.Option("--interval", "-i", help="Delay between keystrokes")
    ] = 0.05,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Simulate")] = False,
) -> None:
    """Type text at current cursor position.

    Example:
        mahavishnu automation type "Hello World"
        mahavishnu automation type "Hello" --interval 0.1
    """
    manager = get_manager(dry_run=dry_run)

    async def _run():
        async with manager:
            return await manager.type_text(text, interval=interval)

    try:
        result = asyncio.run(_run())
        if result.status == "success":
            console.print(f"[green]✓[/green] Typed: {text[:50]}{'...' if len(text) > 50 else ''}")
        else:
            console.print(f"[red]✗[/red] {result.error}")
            raise typer.Exit(1)
    except AutomationError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command("press-key")
def press_key(
    key: Annotated[str, typer.Argument(help="Key to press")],
    modifiers: Annotated[
        str | None, typer.Option("--modifiers", "-m", help="Modifiers (comma-separated)")
    ] = None,
) -> None:
    """Press a key with optional modifiers.

    Example:
        mahavishnu automation press-key return
        mahavishnu automation press-key s --modifiers cmd
        mahavishnu automation press-key c --modifiers cmd,shift
    """
    manager = get_manager()

    mod_list = None
    if modifiers:
        mod_list = [m.strip() for m in modifiers.split(",")]

    async def _run():
        async with manager:
            return await manager.press_key(key, modifiers=mod_list)

    try:
        result = asyncio.run(_run())
        if result.status == "success":
            mod_str = f" with {', '.join(mod_list)}" if mod_list else ""
            console.print(f"[green]✓[/green] Pressed: {key}{mod_str}")
        else:
            console.print(f"[red]✗[/red] {result.error}")
            raise typer.Exit(1)
    except AutomationError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command("click")
def click(
    x: Annotated[int, typer.Argument(help="X coordinate")],
    y: Annotated[int, typer.Argument(help="Y coordinate")],
    button: Annotated[
        str, typer.Option("--button", "-b", help="Mouse button (left/right/middle)")
    ] = "left",
    clicks: Annotated[int, typer.Option("--clicks", "-c", help="Number of clicks")] = 1,
) -> None:
    """Click at coordinates.

    Example:
        mahavishnu automation click 100 200
        mahavishnu automation click 100 200 --button right
        mahavishnu automation click 100 200 --clicks 2  # Double click
    """
    manager = get_manager()

    async def _run():
        async with manager:
            return await manager.click(x, y, button=button, clicks=clicks)

    try:
        result = asyncio.run(_run())
        if result.status == "success":
            click_type = "Double-click" if clicks == 2 else "Click"
            console.print(f"[green]✓[/green] {click_type} at ({x}, {y})")
        else:
            console.print(f"[red]✗[/red] {result.error}")
            raise typer.Exit(1)
    except AutomationError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


# =============================================================================
# Menu Commands
# =============================================================================


@app.command("click-menu")
def click_menu(
    bundle_id: Annotated[str, typer.Argument(help="Application bundle identifier")],
    menu_path: Annotated[str, typer.Argument(help="Menu path (comma-separated, e.g., File,Save)")],
) -> None:
    """Click a menu item.

    Example:
        mahavishnu automation click-menu com.apple.finder "File,New Finder Window"
    """
    manager = get_manager()

    path = [p.strip() for p in menu_path.split(",")]

    async def _run():
        async with manager:
            return await manager.click_menu_item(bundle_id, path)

    try:
        result = asyncio.run(_run())
        if result.status == "success":
            console.print(f"[green]✓[/green] Clicked: {' > '.join(path)}")
        else:
            console.print(f"[red]✗[/red] {result.error}")
            raise typer.Exit(1)
    except AutomationError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


# =============================================================================
# Screenshot Commands
# =============================================================================


@app.command("screenshot")
def screenshot(
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output file path")] = None,
    region: Annotated[
        str | None, typer.Option("--region", "-r", help="Region (x,y,width,height)")
    ] = None,
) -> None:
    """Capture a screenshot.

    Example:
        mahavishnu automation screenshot
        mahavishnu automation screenshot -o screenshot.png
        mahavishnu automation screenshot -r 0,0,800,600 -o region.png
    """
    manager = get_manager()

    region_tuple = None
    if region:
        parts = [int(p.strip()) for p in region.split(",")]
        if len(parts) != 4:
            console.print("[red]Error:[/red] Region must be x,y,width,height")
            raise typer.Exit(1)
        region_tuple = tuple(parts)

    async def _run():
        async with manager:
            return await manager.screenshot(region=region_tuple)

    try:
        result = asyncio.run(_run())
        if result.status == "success":
            image_data = result.data

            # Handle different data formats
            if isinstance(image_data, dict):
                if "image_base64" in image_data:
                    import base64

                    image_bytes = base64.b64decode(image_data["image_base64"])
                elif "result" in image_data:
                    image_bytes = image_data["result"]
                else:
                    image_bytes = image_data
            else:
                image_bytes = image_data

            if output:
                output.write_bytes(image_bytes)
                console.print(f"[green]✓[/green] Saved: {output}")
            else:
                # Output to stdout as binary
                sys.stdout.buffer.write(image_bytes)
        else:
            console.print(f"[red]✗[/red] {result.error}")
            raise typer.Exit(1)
    except AutomationError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


# =============================================================================
# Utility Commands
# =============================================================================


@app.command("check-permissions")
def check_permissions(
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Check automation permissions.

    Example:
        mahavishnu automation check-permissions
    """
    manager = get_manager()

    async def _run():
        async with manager:
            return await manager.check_permissions()

    try:
        result = asyncio.run(_run())

        if result.status != "success":
            console.print(f"[red]Error:[/red] {result.error}")
            raise typer.Exit(1)

        data = result.data or {}

        if json_output:
            format_result(data, "json")
            return

        table = Table(title="Automation Permissions")
        table.add_column("Permission", style="cyan")
        table.add_column("Status", justify="center")
        table.add_column("Required", justify="center")

        for perm in data.get("permissions", []):
            status = perm.get("status", "unknown")
            status_str = "[green]✓[/green]" if status == "granted" else "[red]✗[/red]"
            required_str = "Yes" if perm.get("required") else "No"
            table.add_row(perm.get("name", ""), status_str, required_str)

        console.print(table)

        if not data.get("all_granted"):
            console.print(
                "\n[yellow]Warning:[/yellow] Some permissions are not granted. "
                "Automation may not work correctly."
            )
    except AutomationError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command("status")
def status(
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Show automation manager status.

    Example:
        mahavishnu automation status
    """
    manager = get_manager()

    async def _run():
        async with manager:
            await manager.initialize()
            return {
                "backend": manager.get_backend_name(),
                "stats": manager.get_stats(),
                "capabilities": [str(c) for c in manager.get_capabilities()],
            }

    try:
        result = asyncio.run(_run())

        if json_output:
            format_result(result, "json")
            return

        console.print(f"[cyan]Backend:[/cyan] {result.get('backend', 'none')}")
        console.print(
            f"[cyan]Operations:[/cyan] {result.get('stats', {}).get('operations_total', 0)}"
        )
        console.print(f"[cyan]Capabilities:[/cyan] {len(result.get('capabilities', []))}")
    except AutomationError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command("list-screens")
def list_screens(
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """List connected displays.

    Example:
        mahavishnu automation list-screens
    """
    manager = get_manager()

    async def _run():
        async with manager:
            return await manager.list_screens()

    try:
        result = asyncio.run(_run())

        if result.status != "success":
            console.print(f"[red]Error:[/red] {result.error}")
            raise typer.Exit(1)

        screens = result.data.get("result", result.data) if result.data else []

        if json_output:
            format_result({"screens": screens}, "json")
            return

        table = Table(title="Connected Displays")
        table.add_column("ID", justify="right")
        table.add_column("Name", style="cyan")
        table.add_column("Resolution", justify="right")
        table.add_column("Position", justify="right")
        table.add_column("Scale", justify="right")
        table.add_column("Primary", justify="center")

        for screen in screens:
            if isinstance(screen, dict):
                size = screen.get("size", (0, 0))
                pos = screen.get("position", (0, 0))
                table.add_row(
                    str(screen.get("id", "")),
                    screen.get("name", ""),
                    f"{size[0]}x{size[1]}" if size else "",
                    f"{pos[0]}, {pos[1]}" if pos else "",
                    f"{screen.get('scale', 1.0)}x",
                    "✓" if screen.get("primary") else "",
                )

        console.print(table)
    except AutomationError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
