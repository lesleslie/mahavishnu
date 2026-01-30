"""Ecosystem management commands for Mahavishnu CLI."""

from pathlib import Path

import typer

from mahavishnu.core.ecosystem import get_ecosystem_loader
from mahavishnu.core.errors import ConfigurationError


def add_ecosystem_commands(app: typer.Typer) -> None:
    """Add ecosystem management commands to a Typer app.

    Args:
        app: The Typer app to add commands to
    """

    @app.command("validate")
    def validate_all() -> None:
        """Validate all MCP server configurations."""
        try:
            loader = get_ecosystem_loader()
            result = loader.validate_mcp_servers()

            if result["errors"]:
                typer.echo("❌ Validation Errors:", err=True)
                for error in result["errors"]:
                    typer.echo(f"  - {error}", err=True)

            if result["warnings"]:
                typer.echo("\n⚠️  Warnings:", err=True)
                for warning in result["warnings"]:
                    typer.echo(f"  - {warning}", err=True)

            if not result["errors"]:
                typer.echo("✅ All MCP server configurations are valid!")
            else:
                raise typer.Exit(code=1)

        except ConfigurationError as e:
            typer.echo(f"❌ Configuration Error: {e.message}", err=True)
            raise typer.Exit(code=1) from None

    @app.command("list")
    def list_servers(
        category: str = typer.Option(None, "--category", "-c", help="Filter by category"),
        status: str = typer.Option(
            None, "--status", "-s", help="Filter by status (enabled/disabled)"
        ),
    ) -> None:
        """List all MCP servers."""
        try:
            loader = get_ecosystem_loader()

            servers = loader.config.mcp_servers

            # Apply filters
            if category:
                servers = [s for s in servers if s.category == category]
            if status:
                servers = [s for s in servers if s.status == status]

            # Group by category
            by_category: dict = {}
            for server in servers:
                if server.category not in by_category:
                    by_category[server.category] = []
                by_category[server.category].append(server)

            # Display
            for cat, cat_servers in sorted(by_category.items()):
                typer.echo(f"\n{cat.upper()} ({len(cat_servers)} servers)")
                typer.echo("─" * 60)
                for server in sorted(cat_servers, key=lambda s: s.name):
                    status_icon = "✅" if server.status == "enabled" else "❌"
                    port_info = f":{server.port}" if server.port else "stdio"
                    typer.echo(
                        f"  {status_icon} {server.name:20} {port_info:10} - {server.function}"
                    )

        except ConfigurationError as e:
            typer.echo(f"❌ Configuration Error: {e.message}", err=True)
            raise typer.Exit(code=1) from None

    @app.command("generate-claude-config")
    def generate_claude_config(
        output: Path | None = typer.Option(  # noqa: B008
            None, "--output", "-o", help="Output path for generated config"
        ),
        dry_run: bool = typer.Option(False, "--dry-run", help="Print config without writing"),
    ) -> None:
        """Generate ~/.claude.json MCP server configuration from ecosystem.yaml."""
        import json

        # Set default output path if not provided
        if output is None:
            output = Path.home() / ".claude.json"

        try:
            loader = get_ecosystem_loader()
            mcp_config = loader.generate_claude_mcp_config()

            if dry_run:
                typer.echo("Generated MCP configuration (dry run):")
                typer.echo(json.dumps(mcp_config, indent=2))
            else:
                # Read existing config
                try:
                    with open(output) as f:
                        claude_config = json.load(f)
                except FileNotFoundError:
                    typer.echo(f"⚠️  Creating new config file: {output}")
                    claude_config = {}

                # Update mcpServers section
                claude_config["mcpServers"] = mcp_config

                # Write back
                with open(output, "w") as f:
                    json.dump(claude_config, f, indent=2)

                typer.echo(f"✅ Generated MCP configuration for {len(mcp_config)} servers")
                typer.echo(f"   Written to: {output}")

        except ConfigurationError as e:
            typer.echo(f"❌ Configuration Error: {e.message}", err=True)
            raise typer.Exit(code=1) from None

    @app.command("audit")
    def audit_info(
        server_name: str = typer.Argument(None, help="Server name (omit for all servers)"),
    ) -> None:
        """Show audit information for MCP servers."""
        try:
            loader = get_ecosystem_loader()

            if server_name:
                # Show audit info for specific server
                servers = [s for s in loader.config.mcp_servers if s.name == server_name]
                if not servers:
                    typer.echo(f"❌ Server not found: {server_name}", err=True)
                    raise typer.Exit(code=1)
            else:
                # Show audit info for all servers
                servers = loader.config.mcp_servers

            for server in servers:
                typer.echo(f"\n📋 {server.name}")
                typer.echo("─" * 60)
                typer.echo(f"Category:      {server.category}")
                typer.echo(f"Type:          {server.type}")
                if server.port:
                    typer.echo(f"Port:          {server.port}")
                typer.echo(f"Status:        {server.status}")
                typer.echo(f"Maintainer:    {server.maintainer}")
                typer.echo(f"Command:       {server.command}")

                if server.audit:
                    typer.echo("\nAudit History:")
                    for key, value in server.audit.items():
                        typer.echo(f"  {key}: {value}")

        except ConfigurationError as e:
            typer.echo(f"❌ Configuration Error: {e.message}", err=True)
            raise typer.Exit(code=1) from None

    @app.command("update-audit")
    def update_audit(
        server_name: str = typer.Argument(..., help="Server name"),
        field: str = typer.Argument(
            ..., help="Audit field to update (e.g., last_validated, last_tested)"
        ),
        value: str = typer.Argument(..., help="Timestamp value"),
        notes: str = typer.Option(None, "--notes", "-n", help="Optional notes"),
    ) -> None:
        """Update audit timestamp for an MCP server."""
        try:
            loader = get_ecosystem_loader()
            loader.update_audit_timestamp(server_name, field, value, notes)
            loader.save()

            typer.echo(f"✅ Updated audit info for {server_name}:")
            typer.echo(f"   {field}: {value}")
            if notes:
                typer.echo(f"   notes: {notes}")

        except ConfigurationError as e:
            typer.echo(f"❌ Error: {e.message}", err=True)
            raise typer.Exit(code=1) from None

    @app.command("urls")
    def show_server_urls(
        server_name: str = typer.Argument(..., help="MCP server name"),
    ) -> None:
        """Show all URLs for an MCP server."""
        try:
            loader = get_ecosystem_loader()
            servers = [s for s in loader.config.mcp_servers if s.name == server_name]
            if not servers:
                typer.echo(f"❌ Server not found: {server_name}", err=True)
                raise typer.Exit(code=1)

            server = servers[0]
            typer.echo(f"\n🔗 URLs for {server.name}")
            typer.echo("─" * 60)

            if server.repo_url:
                typer.echo(f"📦 Repository:  {server.repo_url}")
            if server.homepage_url:
                typer.echo(f"🏠 Homepage:     {server.homepage_url}")
            if server.docs_url:
                typer.echo(f"📚 Documentation: {server.docs_url}")

            if server.urls:
                typer.echo("\n📎 Additional URLs:")
                for key, url in sorted(server.urls.items()):
                    typer.echo(f"   {key}: {url}")

            if not any([server.repo_url, server.homepage_url, server.docs_url, server.urls]):
                typer.echo("No URLs configured for this server")

        except ConfigurationError as e:
            typer.echo(f"❌ Configuration Error: {e.message}", err=True)
            raise typer.Exit(code=1) from None

    @app.command("repo-urls")
    def show_repo_urls(
        repo_name: str = typer.Argument(..., help="Repository name"),
    ) -> None:
        """Show all URLs for a repository."""
        try:
            loader = get_ecosystem_loader()
            repos = [r for r in loader.config.repos if r.name == repo_name]
            if not repos:
                typer.echo(f"❌ Repository not found: {repo_name}", err=True)
                raise typer.Exit(code=1)

            repo = repos[0]
            typer.echo(f"\n🔗 URLs for {repo.name}")
            typer.echo("─" * 60)

            if repo.repo_url:
                typer.echo(f"📦 Repository:  {repo.repo_url}")
            if repo.homepage_url:
                typer.echo(f"🏠 Homepage:     {repo.homepage_url}")
            if repo.docs_url:
                typer.echo(f"📚 Documentation: {repo.docs_url}")

            if repo.urls:
                typer.echo("\n📎 Additional URLs:")
                for key, url in sorted(repo.urls.items()):
                    typer.echo(f"   {key}: {url}")

            if not any([repo.repo_url, repo.homepage_url, repo.docs_url, repo.urls]):
                typer.echo("No URLs configured for this repository")

        except ConfigurationError as e:
            typer.echo(f"❌ Configuration Error: {e.message}", err=True)
            raise typer.Exit(code=1) from None

    @app.command("list-lsp")
    def list_lsp_servers(
        language: str = typer.Option(None, "--language", "-l", help="Filter by language"),
        enabled: str = typer.Option(
            None, "--enabled", "-e", help="Filter by enabled status (true/false)"
        ),
    ) -> None:
        """List all LSP servers."""
        try:
            loader = get_ecosystem_loader()
            servers = loader.config.lsp_servers

            # Apply filters
            if language:
                servers = [s for s in servers if s.get("language") == language]
            if enabled:
                enabled_bool = enabled.lower() == "true"
                servers = [s for s in servers if s.get("enabled") == enabled_bool]

            # Group by language
            by_language: dict = {}
            for server in servers:
                lang = server.get("language", "unknown")
                if lang not in by_language:
                    by_language[lang] = []
                by_language[lang].append(server)

            # Display
            for lang, lang_servers in sorted(by_language.items()):
                typer.echo(f"\n{lang.upper()} ({len(lang_servers)} servers)")
                typer.echo("─" * 60)
                for server in sorted(lang_servers, key=lambda s: s.get("name", "")):
                    status_icon = "✅" if server.get("enabled") else "❌"
                    lsp_type = server.get("type", "unknown")
                    typer.echo(
                        f"  {status_icon} {server.get('name'):20} {lsp_type:8} - {server.get('description', 'No description')[:40]}"
                    )

        except ConfigurationError as e:
            typer.echo(f"❌ Configuration Error: {e.message}", err=True)
            raise typer.Exit(code=1) from None

    @app.command("lsp-info")
    def lsp_info(
        server_name: str = typer.Argument(None, help="LSP server name (omit for all servers)"),
    ) -> None:
        """Show detailed information about LSP servers."""
        try:
            loader = get_ecosystem_loader()

            if server_name:
                servers = [s for s in loader.config.lsp_servers if s.get("name") == server_name]
                if not servers:
                    typer.echo(f"❌ LSP server not found: {server_name}", err=True)
                    raise typer.Exit(code=1)
            else:
                servers = loader.config.lsp_servers

            for server in servers:
                typer.echo(f"\n🔧 {server.get('name')}")
                typer.echo("─" * 60)
                typer.echo(f"Language:      {server.get('language')}")
                typer.echo(f"Type:          {server.get('type')}")
                typer.echo(f"Status:        {'enabled' if server.get('enabled') else 'disabled'}")
                typer.echo(
                    f"Command:       {server.get('command')} {' '.join(server.get('args', []))}"
                )
                typer.echo(f"Config File:   {server.get('config_file') or 'N/A'}")
                typer.echo(f"Config Section: {server.get('config_section') or 'N/A'}")

                if server.get("repo_url"):
                    typer.echo(f"\n📦 Repository:  {server.get('repo_url')}")
                if server.get("docs_url"):
                    typer.echo(f"📚 Documentation: {server.get('docs_url')}")
                if server.get("urls"):
                    typer.echo("\n📎 Additional URLs:")
                    for key, url in sorted(server.get("urls", {}).items()):
                        typer.echo(f"   {key}: {url}")

                if server.get("audit"):
                    typer.echo("\nAudit History:")
                    for key, value in server.get("audit", {}).items():
                        typer.echo(f"  {key}: {value}")

        except ConfigurationError as e:
            typer.echo(f"❌ Configuration Error: {e.message}", err=True)
            raise typer.Exit(code=1) from None

    @app.command("ports")
    def list_ports(
        type_filter: str = typer.Option(
            None, "--type", "-t", help="Filter by type (MCP, LSP, WebSocket)"
        ),
        status: str = typer.Option(
            None, "--status", "-s", help="Filter by status (enabled/disabled)"
        ),
    ) -> None:
        """Show all ports used across the ecosystem in numeric order."""
        try:
            loader = get_ecosystem_loader()
            portmap = loader.config.portmap

            # Apply filters
            if type_filter:
                portmap = [p for p in portmap if p.get("type", "").upper() == type_filter.upper()]
            if status:
                portmap = [p for p in portmap if p.get("status", "").lower() == status.lower()]

            if not portmap:
                typer.echo("No port mappings found")
                return

            # Display header
            typer.echo("\n" + "=" * 80)
            typer.echo("ECOSYSTEM PORT MAP")
            typer.echo("=" * 80)

            # Group by port range
            infrastructure = [p for p in portmap if 8000 <= p.get("port", 0) <= 9999]
            tools = [p for p in portmap if 3000 <= p.get("port", 0) <= 3999]

            # Display Infrastructure (8000-9999)
            if infrastructure:
                typer.echo("\n🏗️  INFRASTRUCTURE (8000-9999)")
                typer.echo("─" * 80)
                for entry in sorted(infrastructure, key=lambda x: x.get("port", 0)):
                    port = entry.get("port")
                    service = entry.get("service", "unknown")
                    svc_type = entry.get("type", "?")
                    category = entry.get("category", "")
                    protocol = entry.get("protocol", "")
                    status_icon = "✅" if entry.get("status") == "enabled" else "❌"
                    description = entry.get("description", "")[:50]

                    typer.echo(
                        f"  {status_icon} {port:5} | {service:25} {svc_type:4} | {category:15} | {protocol:20}"
                    )
                    if description:
                        typer.echo(f"       {description}")

            # Display Tools & Integrations (3000-3999)
            if tools:
                typer.echo("\n🔧 TOOLS & INTEGRATIONS (3000-3999)")
                typer.echo("─" * 80)
                for entry in sorted(tools, key=lambda x: x.get("port", 0)):
                    port = entry.get("port")
                    service = entry.get("service", "unknown")
                    svc_type = entry.get("type", "?")
                    category = entry.get("category", "")
                    protocol = entry.get("protocol", "")
                    status_icon = "✅" if entry.get("status") == "enabled" else "❌"
                    description = entry.get("description", "")[:50]

                    typer.echo(
                        f"  {status_icon} {port:5} | {service:25} {svc_type:4} | {category:15} | {protocol:20}"
                    )
                    if description:
                        typer.echo(f"       {description}")

            # Summary
            total = len(portmap)
            enabled = sum(1 for p in portmap if p.get("status") == "enabled")
            typer.echo("\n" + "─" * 80)
            typer.echo(f"Total: {total} ports | Enabled: {enabled} | Disabled: {total - enabled}")
            typer.echo("=" * 80 + "\n")

        except ConfigurationError as e:
            typer.echo(f"❌ Configuration Error: {e.message}", err=True)
            raise typer.Exit(code=1) from None
