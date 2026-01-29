"""Backup and recovery CLI commands."""

import asyncio

import typer


def add_backup_commands(app: typer.Typer) -> None:
    """Add backup and recovery commands to the main CLI app."""
    from .core.backup_recovery import BackupManager, DisasterRecoveryManager

    backup_app = typer.Typer(help="Backup and disaster recovery operations")
    app.add_typer(backup_app, name="backup")

    @backup_app.command("create")
    def backup_create(
        backup_type: str = typer.Option(
            "full", "--type", "-t", help="Backup type (full, incremental)"
        ),
    ) -> None:
        """Create a new backup."""

        async def _create():
            from .core.app import MahavishnuApp

            maha_app = MahavishnuApp()
            backup_manager = BackupManager(maha_app)

            try:
                backup_info = await backup_manager.create_backup(backup_type)
                typer.echo(f"✓ Backup created: {backup_info.backup_id}")
                typer.echo(f"  Location: {backup_info.location}")
                typer.echo(f"  Size: {backup_info.size_bytes / (1024 * 1024):.2f} MB")
                typer.echo(f"  Time: {backup_info.timestamp.isoformat()}")
            except Exception as e:
                typer.echo(f"✗ Backup failed: {e}", err=True)
                raise typer.Exit(code=1) from None

        asyncio.run(_create())

    @backup_app.command("list")
    def backup_list() -> None:
        """List all available backups."""

        async def _list():
            from .core.app import MahavishnuApp

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

        asyncio.run(_list())

    @backup_app.command("restore")
    def backup_restore(backup_id: str = typer.Argument(..., help="Backup ID to restore")) -> None:
        """Restore from a backup."""

        async def _restore():
            from .core.app import MahavishnuApp

            maha_app = MahavishnuApp()
            backup_manager = BackupManager(maha_app)

            try:
                success = await backup_manager.restore_backup(backup_id)
                if success:
                    typer.echo(f"✓ Restored backup: {backup_id}")
                else:
                    typer.echo(f"✗ Restore failed: {backup_id}", err=True)
                    raise typer.Exit(code=1)
            except Exception as e:
                typer.echo(f"✗ Restore error: {e}", err=True)
                raise typer.Exit(code=1) from None

        asyncio.run(_restore())

    @backup_app.command("info")
    def backup_info(backup_id: str = typer.Argument(..., help="Backup ID to inspect")) -> None:
        """Show information about a specific backup."""

        async def _info():
            from .core.app import MahavishnuApp

            maha_app = MahavishnuApp()
            backup_manager = BackupManager(maha_app)

            info = await backup_manager.get_backup_info(backup_id)

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

        asyncio.run(_info())

    @backup_app.command("check")
    def backup_check() -> None:
        """Run disaster recovery check."""

        async def _check():
            from .core.app import MahavishnuApp

            maha_app = MahavishnuApp()
            recovery_manager = DisasterRecoveryManager(maha_app)

            results = await recovery_manager.run_disaster_recovery_check()

            typer.echo(f"Status: {results['status']}")
            typer.echo("\nChecks:")
            for check_name, check_result in results["checks"].items():
                status_symbol = "✓" if check_result.get("status") == "pass" else "✗"
                typer.echo(f"  {status_symbol} {check_name}: {check_result.get('status')}")

        asyncio.run(_check())

    @backup_app.command("procedures")
    def backup_procedures() -> None:
        """Show disaster recovery procedures."""

        async def _procedures():
            from .core.app import MahavishnuApp

            maha_app = MahavishnuApp()
            recovery_manager = DisasterRecoveryManager(maha_app)

            procedures = await recovery_manager.get_recovery_procedures()

            import json

            typer.echo(json.dumps(procedures, indent=2))

        asyncio.run(_procedures())
