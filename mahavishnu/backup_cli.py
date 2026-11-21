"""Backup and recovery CLI commands."""

from __future__ import annotations

import json

import typer

from mahavishnu.core.async_patterns import run_sync


def _do_backup_create(backup_type: str) -> None:
    """Create a new backup."""
    from .core.app import MahavishnuApp
    from .core.backup_recovery import BackupManager

    async def _create() -> None:
        maha_app = MahavishnuApp()
        backup_manager = BackupManager(maha_app)

        try:
            backup_info = await backup_manager.create_backup(backup_type)
        except (  # CLI entry point — broad catch is the documented contract
            Exception  # noqa: BLE001, RUF100
        ) as e:
            typer.echo(f"✗ Backup failed: {e}", err=True)
            raise typer.Exit(code=1) from None

        typer.echo(f"✓ Backup created: {backup_info.backup_id}")
        typer.echo(f"  Location: {backup_info.location}")
        typer.echo(f"  Size: {backup_info.size_bytes / (1024 * 1024):.2f} MB")
        typer.echo(f"  Time: {backup_info.timestamp.isoformat()}")

    run_sync(_create())


def _do_backup_list() -> None:
    """List all available backups."""
    from .core.app import MahavishnuApp
    from .core.backup_recovery import BackupManager

    async def _list() -> None:
        maha_app = MahavishnuApp()
        backup_manager = BackupManager(maha_app)

        backups = await backup_manager.list_backups()

        if not backups:
            typer.echo("No backups found")
            return

        typer.echo(f"Found {len(backups)} backup(s):")
        for backup in backups:
            typer.echo(f"  - {backup.backup_id}")
            typer.echo(f"    Time: {backup.timestamp.isoformat()}")
            typer.echo(f"    Size: {backup.size_bytes / (1024 * 1024):.2f} MB")
            typer.echo(f"    Status: {backup.status}")

    run_sync(_list())


def _do_backup_restore(backup_id: str) -> None:
    """Restore from a backup."""
    from .core.app import MahavishnuApp
    from .core.backup_recovery import BackupManager

    async def _restore() -> None:
        maha_app = MahavishnuApp()
        backup_manager = BackupManager(maha_app)

        try:
            success = await backup_manager.restore_backup(backup_id)
        except (  # CLI entry point — broad catch is the documented contract
            Exception  # noqa: BLE001, RUF100
        ) as e:
            typer.echo(f"✗ Restore error: {e}", err=True)
            raise typer.Exit(code=1) from None

        if success:
            typer.echo(f"✓ Restored backup: {backup_id}")
            return

        typer.echo(f"✗ Restore failed: {backup_id}", err=True)
        raise typer.Exit(code=1)

    run_sync(_restore())


def _do_backup_info(backup_id: str) -> None:
    """Show information about a specific backup."""
    from .core.app import MahavishnuApp
    from .core.backup_recovery import BackupManager

    async def _info() -> None:
        maha_app = MahavishnuApp()
        backup_manager = BackupManager(maha_app)

        try:
            info = await backup_manager.get_backup_info(backup_id)
        except ValueError as e:
            # An id that is not a backup id is the operator's mistake,
            # not a backend failure, and it deserves a sentence rather
            # than a traceback. A backend error is a different thing
            # and it propagates -- the backup commands' convention,
            # which the CLI test suite pins for list, info, check and
            # procedures alike.
            typer.echo(f"✗ Backup info error: {e}", err=True)
            raise typer.Exit(code=1) from None

        if not info:
            typer.echo(f"Backup not found: {backup_id}", err=True)
            raise typer.Exit(code=1)

        typer.echo(f"Backup ID: {info.backup_id}")
        typer.echo(f"Time: {info.timestamp.isoformat()}")
        typer.echo(f"Size: {info.size_bytes / (1024 * 1024):.2f} MB")
        typer.echo(f"Location: {info.location}")
        typer.echo(f"Status: {info.status}")
        typer.echo(f"Files: {info.files_backed_up}")
        if info.checksum:
            typer.echo(f"Checksum: {info.checksum}")

    run_sync(_info())


def _do_backup_check() -> None:
    """Run disaster recovery check."""
    from .core.app import MahavishnuApp
    from .core.backup_recovery import DisasterRecoveryManager

    async def _check() -> None:
        maha_app = MahavishnuApp()
        recovery_manager = DisasterRecoveryManager(maha_app)

        results = await recovery_manager.run_disaster_recovery_check()

        typer.echo(f"Status: {results['status']}")
        typer.echo("\nChecks:")
        for check_name, check_result in results["checks"].items():
            status_symbol = "✓" if check_result.get("status") == "pass" else "✗"
            typer.echo(f"  {status_symbol} {check_name}: {check_result.get('status')}")

    run_sync(_check())


def _do_backup_procedures() -> None:
    """Show disaster recovery procedures."""
    from .core.app import MahavishnuApp
    from .core.backup_recovery import DisasterRecoveryManager

    async def _procedures() -> None:
        maha_app = MahavishnuApp()
        recovery_manager = DisasterRecoveryManager(maha_app)

        procedures = await recovery_manager.get_recovery_procedures()

        typer.echo(json.dumps(procedures, indent=2))

    run_sync(_procedures())


def add_backup_commands(app: typer.Typer) -> None:
    """Add backup and recovery commands to the main CLI app.

    Each command is a thin wrapper that delegates to a module-level
    ``_do_*`` helper. The wrappers exist so Typer can introspect the
    function signature for option/argument parsing; the real logic
    lives in the helpers (so cyclomatic complexity stays bounded per
    function).
    """
    backup_app = typer.Typer(help="Backup and disaster recovery operations")
    app.add_typer(backup_app, name="backup")

    @backup_app.command("create")
    def backup_create(
        backup_type: str = typer.Option(
            "full", "--type", "-t", help="Backup type (full, incremental)"
        ),
    ) -> None:
        """Create a new backup."""
        _do_backup_create(backup_type)

    @backup_app.command("list")
    def backup_list() -> None:
        """List all available backups."""
        _do_backup_list()

    @backup_app.command("restore")
    def backup_restore(
        backup_id: str = typer.Argument(..., help="Backup ID to restore"),
    ) -> None:
        """Restore from a backup."""
        _do_backup_restore(backup_id)

    @backup_app.command("info")
    def backup_info(
        backup_id: str = typer.Argument(..., help="Backup ID to inspect"),
    ) -> None:
        """Show information about a specific backup."""
        _do_backup_info(backup_id)

    @backup_app.command("check")
    def backup_check() -> None:
        """Run disaster recovery check."""
        _do_backup_check()

    @backup_app.command("procedures")
    def backup_procedures() -> None:
        """Show disaster recovery procedures."""
        _do_backup_procedures()


__all__ = ["add_backup_commands"]
