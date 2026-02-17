#!/usr/bin/env python3
"""
Agent Versioning System

Tracks agent evolution, enables rollbacks, and documents breaking changes.

Usage:
    uv run agent_versioning.py add-version <agent_file> <version> <changes>
    uv run agent_versioning.py list-versions <agent_file>
    uv run agent_versioning.py show-changelog <agent_name>
    uv run agent_versioning.py validate-all
"""

import re
import yaml
from pathlib import Path
from typing import Optional
from datetime import datetime
from dataclasses import dataclass, field
import click


@dataclass
class VersionChange:
    """Single version change entry"""
    version: str
    date: str
    changes: list[str]
    breaking: bool = False


@dataclass
class AgentVersion:
    """Agent version metadata"""
    name: str
    current_version: str
    changelog: list[VersionChange] = field(default_factory=list)


class AgentVersionManager:
    """Manage agent versions and changelogs"""

    def __init__(self, agents_dir: Path = Path.home() / ".claude" / "agents"):
        self.agents_dir = agents_dir

    def parse_agent_file(self, agent_file: Path) -> tuple[dict, str]:
        """Parse agent file into frontmatter and content"""
        content = agent_file.read_text()

        # Extract YAML frontmatter
        match = re.match(r'^---\n(.*?)\n---\n(.*)', content, re.DOTALL)
        if not match:
            raise ValueError(f"Invalid agent file format: {agent_file}")

        frontmatter_text, body = match.groups()
        frontmatter = yaml.safe_load(frontmatter_text)

        return frontmatter, body

    def write_agent_file(self, agent_file: Path, frontmatter: dict, body: str) -> None:
        """Write agent file with updated frontmatter"""
        frontmatter_text = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)

        content = f"---\n{frontmatter_text}---\n{body}"
        agent_file.write_text(content)

    def add_version(
        self,
        agent_file: Path,
        version: str,
        changes: list[str],
        breaking: bool = False
    ) -> None:
        """Add a version entry to an agent file"""
        frontmatter, body = self.parse_agent_file(agent_file)

        # Initialize version if not exists
        if "version" not in frontmatter:
            frontmatter["version"] = version

        if "changelog" not in frontmatter:
            frontmatter["changelog"] = []

        # Add new changelog entry
        new_entry = {
            "version": version,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "changes": changes
        }

        if breaking:
            new_entry["breaking"] = True

        # Prepend to changelog (newest first)
        frontmatter["changelog"].insert(0, new_entry)

        # Update current version
        frontmatter["version"] = version

        self.write_agent_file(agent_file, frontmatter, body)

    def get_version_info(self, agent_file: Path) -> Optional[AgentVersion]:
        """Get version information for an agent"""
        try:
            frontmatter, _ = self.parse_agent_file(agent_file)

            if "version" not in frontmatter:
                return None

            changelog = [
                VersionChange(
                    version=entry.get("version", "unknown"),
                    date=entry.get("date", "unknown"),
                    changes=entry.get("changes", []),
                    breaking=entry.get("breaking", False)
                )
                for entry in frontmatter.get("changelog", [])
            ]

            return AgentVersion(
                name=frontmatter.get("name", "unknown"),
                current_version=frontmatter.get("version", "0.0.0"),
                changelog=changelog
            )

        except Exception as e:
            click.echo(f"Error reading {agent_file}: {e}", err=True)
            return None

    def validate_version_format(self, version: str) -> bool:
        """Validate semantic version format (X.Y.Z)"""
        pattern = r'^\d+\.\d+\.\d+$'
        return bool(re.match(pattern, version))

    def validate_all_agents(self) -> dict:
        """Validate all agent files for version consistency"""
        results = {
            "total": 0,
            "versioned": 0,
            "unversioned": 0,
            "invalid_format": [],
            "missing_changelog": []
        }

        for agent_file in self.agents_dir.glob("*.md"):
            results["total"] += 1

            try:
                frontmatter, _ = self.parse_agent_file(agent_file)

                if "version" in frontmatter:
                    results["versioned"] += 1

                    # Validate version format
                    version = frontmatter["version"]
                    if not self.validate_version_format(version):
                        results["invalid_format"].append({
                            "file": agent_file.name,
                            "version": version
                        })

                    # Check for changelog
                    if "changelog" not in frontmatter or not frontmatter["changelog"]:
                        results["missing_changelog"].append(agent_file.name)

                else:
                    results["unversioned"] += 1

            except Exception as e:
                click.echo(f"Error validating {agent_file.name}: {e}", err=True)

        return results

    def suggest_next_version(
        self,
        agent_file: Path,
        change_type: str = "patch"
    ) -> str:
        """Suggest next version based on semantic versioning"""
        version_info = self.get_version_info(agent_file)

        if not version_info or version_info.current_version == "0.0.0":
            return "1.0.0" if change_type == "major" else "0.1.0"

        major, minor, patch = map(int, version_info.current_version.split('.'))

        if change_type == "major":
            return f"{major + 1}.0.0"
        elif change_type == "minor":
            return f"{major}.{minor + 1}.0"
        else:  # patch
            return f"{major}.{minor}.{patch + 1}"


@click.group()
def cli():
    """Agent Versioning System CLI"""
    pass


@cli.command("add-version")
@click.argument("agent_file", type=click.Path(exists=True, path_type=Path))
@click.argument("version")
@click.argument("changes", nargs=-1, required=True)
@click.option("--breaking", is_flag=True, help="Mark as breaking change")
def add_version_cmd(agent_file: Path, version: str, changes: tuple, breaking: bool):
    """Add a version entry to an agent file"""
    manager = AgentVersionManager()

    if not manager.validate_version_format(version):
        click.echo(f"Error: Invalid version format '{version}'. Use X.Y.Z (e.g., 1.2.0)", err=True)
        return

    manager.add_version(agent_file, version, list(changes), breaking)
    click.echo(f"✓ Added version {version} to {agent_file.name}")


@cli.command("list-versions")
@click.argument("agent_file", type=click.Path(exists=True, path_type=Path))
def list_versions_cmd(agent_file: Path):
    """List all versions for an agent"""
    manager = AgentVersionManager()
    version_info = manager.get_version_info(agent_file)

    if not version_info:
        click.echo(f"No version information found for {agent_file.name}")
        return

    click.echo(f"\n{version_info.name} - Current Version: {version_info.current_version}\n")

    for entry in version_info.changelog:
        breaking_marker = " [BREAKING]" if entry.breaking else ""
        click.echo(f"Version {entry.version}{breaking_marker} ({entry.date})")

        for change in entry.changes:
            click.echo(f"  • {change}")

        click.echo()


@cli.command("show-changelog")
@click.argument("agent_name")
def show_changelog_cmd(agent_name: str):
    """Show changelog for a specific agent"""
    manager = AgentVersionManager()
    agent_file = manager.agents_dir / f"{agent_name}.md"

    if not agent_file.exists():
        click.echo(f"Error: Agent '{agent_name}' not found", err=True)
        return

    version_info = manager.get_version_info(agent_file)

    if not version_info or not version_info.changelog:
        click.echo(f"No changelog found for {agent_name}")
        return

    click.echo(f"\n# {version_info.name} Changelog\n")

    for entry in version_info.changelog:
        breaking_marker = " **[BREAKING]**" if entry.breaking else ""
        click.echo(f"## Version {entry.version}{breaking_marker}")
        click.echo(f"*Released: {entry.date}*\n")

        for change in entry.changes:
            click.echo(f"- {change}")

        click.echo()


@cli.command("validate-all")
def validate_all_cmd():
    """Validate all agent files for version consistency"""
    manager = AgentVersionManager()
    results = manager.validate_all_agents()

    click.echo("\n=== Agent Versioning Validation ===\n")
    click.echo(f"Total Agents: {results['total']}")
    click.echo(f"Versioned: {results['versioned']}")
    click.echo(f"Unversioned: {results['unversioned']}")

    if results['invalid_format']:
        click.echo("\n⚠️  Invalid Version Formats:")
        for item in results['invalid_format']:
            click.echo(f"  - {item['file']}: {item['version']}")

    if results['missing_changelog']:
        click.echo("\n⚠️  Missing Changelogs:")
        for file in results['missing_changelog']:
            click.echo(f"  - {file}")

    coverage = (results['versioned'] / results['total'] * 100) if results['total'] > 0 else 0
    click.echo(f"\nVersion Coverage: {coverage:.1f}%")


@cli.command("suggest-version")
@click.argument("agent_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--type",
    "change_type",
    type=click.Choice(["major", "minor", "patch"]),
    default="patch",
    help="Type of version bump"
)
def suggest_version_cmd(agent_file: Path, change_type: str):
    """Suggest next version number"""
    manager = AgentVersionManager()
    next_version = manager.suggest_next_version(agent_file, change_type)

    click.echo(f"Suggested {change_type} version: {next_version}")


@cli.command("init-version")
@click.argument("agent_file", type=click.Path(exists=True, path_type=Path))
@click.option("--version", default="1.0.0", help="Initial version")
def init_version_cmd(agent_file: Path, version: str):
    """Initialize versioning for an agent"""
    manager = AgentVersionManager()

    version_info = manager.get_version_info(agent_file)
    if version_info:
        click.echo(f"Agent already versioned at {version_info.current_version}")
        return

    manager.add_version(
        agent_file,
        version,
        ["Initial version with comprehensive capabilities"]
    )

    click.echo(f"✓ Initialized {agent_file.name} at version {version}")


if __name__ == "__main__":
    cli()
