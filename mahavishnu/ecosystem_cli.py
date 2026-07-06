"""Ecosystem management commands for Mahavishnu CLI."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from mahavishnu.core.ecosystem import get_ecosystem_loader
from mahavishnu.core.errors import ConfigurationError


def _print_config_error(error: ConfigurationError) -> None:
    """Print a ConfigurationError to stderr and exit with code 1.

    Centralises the repeated pattern at the end of each command body so
    the inner command wrappers stay short (and below the complexity
    limit).
    """
    typer.echo(f"❌ Configuration Error: {error.message}", err=True)
    raise typer.Exit(code=1) from None


def _do_validate() -> None:
    """Validate all MCP server configurations."""
    try:
        loader = get_ecosystem_loader()
        result = loader.validate_mcp_servers()
        catalog_result = loader.validate_catalog_references()
        metadata_result = loader.validate_catalog_metadata()

        result["errors"].extend(catalog_result["errors"])
        result["errors"].extend(metadata_result["errors"])
        result["warnings"].extend(catalog_result["warnings"])
        result["warnings"].extend(metadata_result["warnings"])

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
        _print_config_error(e)


def _do_list(category: str | None, status: str | None) -> None:
    """List all MCP servers, optionally filtered by category/status."""
    try:
        loader = get_ecosystem_loader()
        servers = loader.config.mcp_servers

        if category:
            servers = [s for s in servers if s.category == category]
        if status:
            servers = [s for s in servers if s.status == status]

        by_category: dict[str, list] = {}
        for server in servers:
            by_category.setdefault(server.category, []).append(server)

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
        _print_config_error(e)


def _do_generate_claude_config(output: Path | None, dry_run: bool) -> None:
    """Generate ~/.claude.json MCP server configuration from ecosystem.yaml."""
    if output is None:
        output = Path.home() / ".claude.json"

    try:
        loader = get_ecosystem_loader()
        mcp_config = loader.generate_claude_mcp_config()

        if dry_run:
            typer.echo("Generated MCP configuration (dry run):")
            typer.echo(json.dumps(mcp_config, indent=2))
            return

        try:
            with open(output) as f:
                claude_config = json.load(f)
        except FileNotFoundError:
            typer.echo(f"⚠️  Creating new config file: {output}")
            claude_config = {}

        claude_config["mcpServers"] = mcp_config

        with open(output, "w") as f:
            json.dump(claude_config, f, indent=2)

        typer.echo(f"✅ Generated MCP configuration for {len(mcp_config)} servers")
        typer.echo(f"   Written to: {output}")
    except ConfigurationError as e:
        _print_config_error(e)


def _do_audit(server_name: str | None) -> None:
    """Show audit information for MCP servers (one or all)."""
    try:
        loader = get_ecosystem_loader()

        if server_name:
            servers = [s for s in loader.config.mcp_servers if s.name == server_name]
            if not servers:
                typer.echo(f"❌ Server not found: {server_name}", err=True)
                raise typer.Exit(code=1)
        else:
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
        _print_config_error(e)


def _do_update_audit(server_name: str, field: str, value: str, notes: str | None) -> None:
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


def _do_show_server_urls(server_name: str) -> None:
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
        _print_config_error(e)


def _do_show_repo_urls(repo_name: str) -> None:
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
        _print_config_error(e)


def _do_list_lsp_servers(language: str | None, enabled: str | None) -> None:
    """List all LSP servers, optionally filtered."""
    try:
        loader = get_ecosystem_loader()
        servers = loader.config.lsp_servers

        if language:
            servers = [s for s in servers if s.get("language") == language]
        if enabled:
            enabled_bool = enabled.lower() == "true"
            servers = [s for s in servers if s.get("enabled") == enabled_bool]

        by_language: dict[str, list] = {}
        for server in servers:
            lang = server.get("language", "unknown")
            by_language.setdefault(lang, []).append(server)

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
        _print_config_error(e)


def _print_lsp_server_details(server: dict) -> None:
    """Print one LSP server's details (header + optional sections)."""
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


def _do_lsp_info(server_name: str | None) -> None:
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
            _print_lsp_server_details(server)
    except ConfigurationError as e:
        _print_config_error(e)


def _print_port_section(entries: list[dict], label: str) -> None:
    """Print one port-range section of the ecosystem port map."""
    if not entries:
        return
    typer.echo(f"\n{label}")
    typer.echo("─" * 80)
    for entry in sorted(entries, key=lambda x: x.get("port", 0)):
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


def _do_list_ports(type_filter: str | None, status: str | None) -> None:
    """Show all ports used across the ecosystem in numeric order."""
    try:
        loader = get_ecosystem_loader()
        portmap = loader.config.portmap

        if type_filter:
            portmap = [p for p in portmap if p.get("type", "").upper() == type_filter.upper()]
        if status:
            portmap = [p for p in portmap if p.get("status", "").lower() == status.lower()]

        if not portmap:
            typer.echo("No port mappings found")
            return

        typer.echo("\n" + "=" * 80)
        typer.echo("ECOSYSTEM PORT MAP")
        typer.echo("=" * 80)

        infrastructure = [p for p in portmap if 8000 <= p.get("port", 0) <= 9999]
        tools = [p for p in portmap if 3000 <= p.get("port", 0) <= 3999]

        _print_port_section(infrastructure, "🏗️  INFRASTRUCTURE (8000-9999)")
        _print_port_section(tools, "🔧 TOOLS & INTEGRATIONS (3000-3999)")

        total = len(portmap)
        enabled = sum(1 for p in portmap if p.get("status") == "enabled")
        typer.echo("\n" + "─" * 80)
        typer.echo(f"Total: {total} ports | Enabled: {enabled} | Disabled: {total - enabled}")
        typer.echo("=" * 80 + "\n")
    except ConfigurationError as e:
        _print_config_error(e)


async def _generate_status_report() -> object:
    """Async helper: generate the ecosystem status report."""
    from mahavishnu.core.ecosystem_status import EcosystemStatusService

    service = EcosystemStatusService()
    return await service.generate_report()


def _print_status_table(report: object) -> None:
    """Render the ecosystem status report as a human-readable table."""
    typer.echo(f"Ecosystem Status: {report.status.value}")
    typer.echo(f"Generated at: {report.generated_at}")
    typer.echo(f"Duration: {report.duration_ms:.0f}ms")
    if report.errors:
        typer.echo(f"Section errors: {len(report.errors)}")
    if report.services:
        typer.echo(f"\nServices ({len(report.services)}):")
        for name, svc in report.services.items():
            req = " [required]" if svc.required else ""
            typer.echo(f"  {name}: {svc.status.value}{req}")
    if report.adapters:
        typer.echo(f"\nAdapters ({len(report.adapters)}):")
        for name, adp in report.adapters.items():
            typer.echo(f"  {name}: {adp.status.value}")
    if report.workflows:
        w = report.workflows
        typer.echo(
            f"\nWorkflows: active={w.active_count} failed={w.failed_count} recent={w.recent_count}"
        )
    if report.alerts:
        a = report.alerts
        typer.echo(
            f"\nAlerts: total={a.total_active} critical={a.by_severity.get('critical', 0)}"
        )
    if report.recommendations:
        typer.echo(f"\nRecommendations ({len(report.recommendations)}):")
        for rec in report.recommendations:
            cmd = f" -> {rec.suggested_command}" if rec.suggested_command else ""
            typer.echo(f"  [{rec.severity.value}] {rec.message}{cmd}")


def _do_ecosystem_status(json_output: bool) -> None:
    """Show canonical ecosystem health status."""
    loop = asyncio.new_event_loop()
    try:
        report = loop.run_until_complete(_generate_status_report())
    finally:
        loop.close()

    if json_output:
        typer.echo(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return

    _print_status_table(report)


def _print_capabilities_table(caps: dict, capability_filter: str | None) -> None:
    """Render the capabilities report as a table (or the empty-state message)."""
    if not caps:
        suffix = f' matching "{capability_filter}"' if capability_filter else ""
        typer.echo(f"No capabilities found{suffix}.")
        return

    typer.echo(f"Capabilities ({len(caps)}):")
    for name, cap in caps.items():
        typer.echo(f"  {name}: {cap.status.value}")


def _do_ecosystem_capabilities(json_output: bool, capability: str | None) -> None:
    """Show ecosystem capabilities and adapter capabilities."""
    loop = asyncio.new_event_loop()
    try:
        report = loop.run_until_complete(_generate_status_report())
    finally:
        loop.close()

    caps = report.capabilities
    if capability:
        caps = {k: v for k, v in caps.items() if capability.lower() in k.lower()}

    if json_output:
        typer.echo(
            json.dumps(
                {k: v.model_dump(mode="json") for k, v in caps.items()}, indent=2, default=str
            )
        )
        return

    _print_capabilities_table(caps, capability)


def add_ecosystem_commands(app: typer.Typer) -> None:
    """Add ecosystem management commands to a Typer app.

    Each command is a thin wrapper that delegates to a module-level
    ``_do_*`` helper. The wrappers exist so Typer can introspect the
    function signature for option/argument parsing; the real logic
    lives in the helpers (so cyclomatic complexity stays bounded per
    function).
    """

    @app.command("validate")
    def validate_all() -> None:
        """Validate all MCP server configurations."""
        _do_validate()

    @app.command("list")
    def list_servers(
        category: str = typer.Option(None, "--category", "-c", help="Filter by category"),
        status: str = typer.Option(
            None, "--status", "-s", help="Filter by status (enabled/disabled)"
        ),
    ) -> None:
        """List all MCP servers."""
        _do_list(category, status)

    @app.command("generate-claude-config")
    def generate_claude_config(
        output: Path | None = typer.Option(  # noqa: B008
            None, "--output", "-o", help="Output path for generated config"
        ),
        dry_run: bool = typer.Option(False, "--dry-run", help="Print config without writing"),
    ) -> None:
        """Generate ~/.claude.json MCP server configuration from ecosystem.yaml."""
        _do_generate_claude_config(output, dry_run)

    @app.command("audit")
    def audit_info(
        server_name: str = typer.Argument(None, help="Server name (omit for all servers)"),
    ) -> None:
        """Show audit information for MCP servers."""
        _do_audit(server_name)

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
        _do_update_audit(server_name, field, value, notes)

    @app.command("urls")
    def show_server_urls(
        server_name: str = typer.Argument(..., help="MCP server name"),
    ) -> None:
        """Show all URLs for an MCP server."""
        _do_show_server_urls(server_name)

    @app.command("repo-urls")
    def show_repo_urls(
        repo_name: str = typer.Argument(..., help="Repository name"),
    ) -> None:
        """Show all URLs for a repository."""
        _do_show_repo_urls(repo_name)

    @app.command("list-lsp")
    def list_lsp_servers(
        language: str = typer.Option(None, "--language", "-l", help="Filter by language"),
        enabled: str = typer.Option(
            None, "--enabled", "-e", help="Filter by enabled status (true/false)"
        ),
    ) -> None:
        """List all LSP servers."""
        _do_list_lsp_servers(language, enabled)

    @app.command("lsp-info")
    def lsp_info(
        server_name: str = typer.Argument(None, help="LSP server name (omit for all servers)"),
    ) -> None:
        """Show detailed information about LSP servers."""
        _do_lsp_info(server_name)

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
        _do_list_ports(type_filter, status)

    @app.command("status")
    def ecosystem_status(
        json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    ) -> None:
        """Show canonical ecosystem health status."""
        _do_ecosystem_status(json_output)

    @app.command("capabilities")
    def ecosystem_capabilities(
        json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
        capability: str = typer.Option(None, "--capability", help="Filter by capability name"),
    ) -> None:
        """Show ecosystem capabilities and adapter capabilities."""
        _do_ecosystem_capabilities(json_output, capability)


__all__ = ["add_ecosystem_commands"]