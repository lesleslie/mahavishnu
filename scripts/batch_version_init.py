#!/usr/bin/env python3
"""
Batch Agent Version Initialization

Initialize versioning for all agents with appropriate versions
based on their maturity and lifecycle status.

Usage:
    uv run batch_version_init.py --dry-run  # Preview changes
    uv run batch_version_init.py            # Execute initialization
"""

from pathlib import Path
import click
import sys

# Add agent_versioning to path
sys.path.insert(0, str(Path(__file__).parent))
from agent_versioning import AgentVersionManager


# Agent categorization for versioning
AGENT_VERSIONS = {
    # Mature, production-ready specialists (1.0.0)
    "1.0.0": [
        # Languages (already have 1.1.0: c-pro, cpp-pro)
        "python-pro",
        "typescript-pro",
        "javascript-pro",
        "rust-pro",
        "golang-pro",
        "java-pro",
        "flutter-expert",

        # Databases
        "postgresql-specialist",
        "mysql-specialist",
        "sqlite-specialist",
        "redis-specialist",
        "database-operations-specialist",

        # Protocols
        "websocket-specialist",
        "grpc-specialist",
        "graphql-architect",
        "htmx-specialist",

        # Data platforms (data-engineer already has 1.1.0)
        "data-pipeline-engineer",
        "data-scientist",

        # Frontend
        "frontend-developer",
        "css-architect",
        "responsive-design-specialist",
        "accessibility-specialist",

        # Backend & Infrastructure
        "backend-architect",
        "docker-specialist",
        "terraform-specialist",
        "deployment-engineer",
        "devops-troubleshooter",
        "cloud-architect",
        "cloud-native-architect",

        # Testing
        "comprehensive-test-specialist",
        "pytest-hypothesis-specialist",
        "qa-strategist",

        # Security
        "security-auditor",
        "api-security-specialist",
        "authentication-specialist",

        # AI/ML
        "ai-engineer",
        "ml-engineer",
        "mlops-engineer",

        # Meta
        "code-reviewer",
        "refactoring-specialist",
        "documentation-specialist",
    ],

    # Established specialists (0.9.0)
    "0.9.0": [
        # Specialized frameworks
        "starlette-specialist",
        "fastblocks-specialist",
        "web-components-specialist",
        "pwa-specialist",
        "htmy-specialist",

        # Specialized storage
        "vector-database-specialist",

        # Specialized AI
        "gemini-consultant",
        "liquid-ai-specialist",

        # Leadership
        "product-manager",
        "architecture-council",
        "delivery-lead",
        "release-manager",
        "observability-incident-lead",
        "incident-responder",

        # Monitoring
        "monitoring-specialist",
        "sentry-logfire-specialist",
        "log-analyzer",

        # Meta
        "agent-creation-specialist",
        "critical-audit-specialist",
        "context-manager",
        "search-specialist",
        "mcp-integration-expert",
    ],

    # Newer or niche specialists (0.5.0)
    "0.5.0": [
        # Mobile & Embedded
        "mobile-developer",
        "embedded-systems-engineer",
        "electrical-engineer",

        # Specialized templates
        "jinja2-template-designer",
        "tui-designer",
        "mermaid-expert",

        # Specialized development
        "payment-integration",
        "pyo3-specialist",
        "pycharm-plugin-creator",

        # Performance
        "performance-engineer",
        "finops-specialist",

        # Process & Compliance
        "privacy-officer",
        "legal-advisor",
        "accessibility-auditor",
        "data-retention-specialist",
        "customer-success-lead",
        "support-analytics-specialist",
        "ux-researcher",
        "content-designer",
        "developer-enablement-lead",

        # Testing
        "dev-testing-assistant",
        "crackerjack-test-specialist",

        # Specialized
        "acb-specialist",
        "sql-pro",
        "prompt-engineer",
        "reference-builder",
        "tutorial-engineer",
    ],
}


def get_initial_changelog(version: str, agent_name: str) -> list[str]:
    """Generate appropriate initial changelog"""

    if version == "1.0.0":
        return [
            "Production-ready agent with comprehensive capabilities",
            "Mature instruction set and examples",
            "Proven patterns and best practices",
            "Established integration points"
        ]
    elif version == "0.9.0":
        return [
            "Well-established specialist with proven capabilities",
            "Comprehensive instruction set",
            "Active integration patterns",
            "Approaching production maturity"
        ]
    else:  # 0.5.0
        return [
            "Specialized agent with focused capabilities",
            "Initial instruction set and patterns",
            "Domain-specific expertise",
            "Foundational capabilities established"
        ]


@click.command()
@click.option("--dry-run", is_flag=True, help="Preview changes without modifying files")
@click.option("--agents-dir", type=click.Path(path_type=Path),
              default=Path.home() / ".claude" / "agents",
              help="Path to agents directory")
def main(dry_run: bool, agents_dir: Path):
    """Initialize versioning for all agents"""

    manager = AgentVersionManager(agents_dir)

    # Build version mapping
    version_map = {}
    for version, agents in AGENT_VERSIONS.items():
        for agent in agents:
            version_map[agent] = version

    # Track results
    results = {
        "initialized": [],
        "already_versioned": [],
        "not_found": [],
        "errors": []
    }

    click.echo("\n=== Agent Versioning Initialization ===\n")

    if dry_run:
        click.echo("DRY RUN MODE - No files will be modified\n")

    # Process each agent
    total_agents = sum(len(agents) for agents in AGENT_VERSIONS.values())
    current = 0

    for version, agent_names in AGENT_VERSIONS.items():
        for agent_name in agent_names:
            current += 1
            agent_file = agents_dir / f"{agent_name}.md"

            progress = f"[{current}/{total_agents}]"

            if not agent_file.exists():
                click.echo(f"{progress} ⚠️  {agent_name}: File not found", err=True)
                results["not_found"].append(agent_name)
                continue

            # Check if already versioned
            try:
                version_info = manager.get_version_info(agent_file)

                if version_info and version_info.current_version != "0.0.0":
                    click.echo(f"{progress} ℹ️  {agent_name}: Already versioned ({version_info.current_version})")
                    results["already_versioned"].append({
                        "name": agent_name,
                        "version": version_info.current_version
                    })
                    continue

                # Initialize version
                if not dry_run:
                    changelog = get_initial_changelog(version, agent_name)
                    manager.add_version(agent_file, version, changelog)

                click.echo(f"{progress} ✓ {agent_name}: Initialized at {version}")
                results["initialized"].append({
                    "name": agent_name,
                    "version": version
                })

            except Exception as e:
                click.echo(f"{progress} ❌ {agent_name}: Error - {e}", err=True)
                results["errors"].append({
                    "name": agent_name,
                    "error": str(e)
                })

    # Summary
    click.echo("\n=== Summary ===\n")
    click.echo(f"Initialized: {len(results['initialized'])}")
    click.echo(f"Already Versioned: {len(results['already_versioned'])}")
    click.echo(f"Not Found: {len(results['not_found'])}")
    click.echo(f"Errors: {len(results['errors'])}")

    if results["initialized"]:
        click.echo("\n=== Version Distribution ===")
        version_counts = {}
        for item in results["initialized"]:
            v = item["version"]
            version_counts[v] = version_counts.get(v, 0) + 1

        for version in sorted(version_counts.keys(), reverse=True):
            click.echo(f"  {version}: {version_counts[version]} agents")

    if results["not_found"]:
        click.echo("\n⚠️  Missing Agents:")
        for name in results["not_found"]:
            click.echo(f"  - {name}")

    if results["errors"]:
        click.echo("\n❌ Errors:")
        for item in results["errors"]:
            click.echo(f"  - {item['name']}: {item['error']}")

    if dry_run:
        click.echo("\n✓ Dry run complete - run without --dry-run to apply changes")
    else:
        click.echo("\n✓ Version initialization complete")


if __name__ == "__main__":
    main()
