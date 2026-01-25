"""Backup and recovery CLI commands for Mahavishnu."""
import asyncio
import typer
from typing import Optional
import json
from pathlib import Path

from .core.app import MahavishnuApp
from .core.backup_recovery import BackupAndRecoveryCLI

app = typer.Typer(help="Backup and disaster recovery commands for Mahavishnu")


@app.command("create-backup")
def create_backup(
    backup_type: str = typer.Option("full", "--type", "-t", help="Type of backup (full, incremental, config)"),
    config_path: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to configuration file")
):
    """
    Create a backup of the Mahavishnu system.
    
    Creates a backup of configuration, workflow states, and other important data.
    """
    typer.echo("💾 Creating backup...")
    
    # Initialize app with config if provided
    maha_app = MahavishnuApp()
    
    # Initialize backup CLI
    backup_cli = BackupAndRecoveryCLI(maha_app)
    
    # Create backup
    async def _create():
        return await backup_cli.create_backup(backup_type)
    
    result = asyncio.run(_create())
    
    if result["status"] == "success":
        typer.echo(f"✅ Backup created successfully!")
        typer.echo(f"   Backup ID: {result['backup_id']}")
        typer.echo(f"   Size: {result['size_mb']} MB")
        typer.echo(f"   Location: {result['location']}")
        typer.echo(f"   Timestamp: {result['timestamp']}")
        raise typer.Exit(code=0)
    else:
        typer.echo(f"❌ Backup failed: {result['error']}")
        raise typer.Exit(code=1)


@app.command("list-backups")
def list_backups(
    config_path: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to configuration file")
):
    """
    List all available backups.
    """
    typer.echo("📚 Listing backups...")
    
    # Initialize app with config if provided
    maha_app = MahavishnuApp()
    
    # Initialize backup CLI
    backup_cli = BackupAndRecoveryCLI(maha_app)
    
    # List backups
    async def _list():
        return await backup_cli.list_backups()
    
    result = asyncio.run(_list())
    
    if result["status"] == "success":
        typer.echo(f"📁 Found {result['total_count']} backup(s):")
        for backup in result["backups"]:
            typer.echo(f"   • {backup['backup_id']} - {backup['size_mb']} MB - {backup['timestamp']}")
        raise typer.Exit(code=0)
    else:
        typer.echo(f"❌ Failed to list backups: {result['error']}")
        raise typer.Exit(code=1)


@app.command("restore")
def restore(
    backup_id: str = typer.Argument(..., help="ID of the backup to restore"),
    config_path: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to configuration file")
):
    """
    Restore from a backup.
    """
    typer.echo(f"🔄 Restoring from backup: {backup_id}")
    
    # Initialize app with config if provided
    maha_app = MahavishnuApp()
    
    # Initialize backup CLI
    backup_cli = BackupAndRecoveryCLI(maha_app)
    
    # Restore backup
    async def _restore():
        return await backup_cli.restore_backup(backup_id)
    
    result = asyncio.run(_restore())
    
    if result["status"] == "success":
        typer.echo(f"✅ Restore completed successfully!")
        typer.echo(f"   {result['message']}")
        raise typer.Exit(code=0)
    else:
        typer.echo(f"❌ Restore failed: {result['error']}")
        raise typer.Exit(code=1)


@app.command("run-dr-check")
def run_dr_check(
    config_path: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to configuration file")
):
    """
    Run a disaster recovery check.
    
    Verifies backup availability, integrity, and recovery procedures.
    """
    typer.echo("🔍 Running disaster recovery check...")
    
    # Initialize app with config if provided
    maha_app = MahavishnuApp()
    
    # Initialize backup CLI
    backup_cli = BackupAndRecoveryCLI(maha_app)
    
    # Run DR check
    async def _dr_check():
        return await backup_cli.run_disaster_recovery_check()
    
    result = asyncio.run(_dr_check())
    
    if result["status"] == "success":
        typer.echo("✅ Disaster recovery check passed!")
        
        checks = result["results"]["checks"]
        for check_name, check_result in checks.items():
            status = check_result.get("status", "unknown")
            if status == "pass":
                typer.echo(f"   ✅ {check_name}: OK")
            else:
                typer.echo(f"   ❌ {check_name}: ISSUE - {check_result}")
        
        raise typer.Exit(code=0)
    else:
        typer.echo(f"❌ Disaster recovery check failed: {result['error']}")
        raise typer.Exit(code=1)


@app.command("get-procedures")
def get_procedures(
    config_path: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to configuration file"),
    output_file: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file for procedures (JSON)")
):
    """
    Get disaster recovery procedures and documentation.
    """
    typer.echo("📋 Getting disaster recovery procedures...")
    
    # Initialize app with config if provided
    maha_app = MahavishnuApp()
    
    # Initialize backup CLI
    backup_cli = BackupAndRecoveryCLI(maha_app)
    
    # Get procedures
    async def _get_procedures():
        return await backup_cli.get_recovery_procedures()
    
    result = asyncio.run(_get_procedures())
    
    if result["status"] == "success":
        procedures = result["procedures"]
        
        if output_file:
            with open(output_file, 'w') as f:
                json.dump(procedures, f, indent=2)
            typer.echo(f"✅ Procedures saved to: {output_file}")
        else:
            typer.echo("\nEmergency Contact: " + procedures["procedures"]["emergency_contact"])
            typer.echo("Recovery Time Objective: " + procedures["procedures"]["recovery_time_objective"])
            typer.echo("Recovery Point Objective: " + procedures["procedures"]["recovery_point_objective"])
            typer.echo("\nRecovery Steps:")
            for i, step in enumerate(procedures["procedures"]["recovery_steps"], 1):
                typer.echo(f"  {i}. {step}")
        
        raise typer.Exit(code=0)
    else:
        typer.echo(f"❌ Failed to get procedures: {result['error']}")
        raise typer.Exit(code=1)


# Add this command group to the main CLI
def add_backup_commands(main_app):
    """Add backup and recovery commands to the main CLI app."""
    main_app.add_typer(app, name="backup", help="Backup and disaster recovery commands")