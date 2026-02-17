#!/usr/bin/env python3
"""
Project Migration Script - Phase 4

Migrates projects from copied agents to plugin-based architecture.
For each project:
1. Detects which agents are in .claude/agents/
2. Maps agents to plugin IDs using agent-categorization.json
3. Generates .claude/plugins.json
4. Optionally removes duplicate agent files
5. Provides migration report
"""

import json
import shutil
from pathlib import Path
from collections import defaultdict


def load_agent_categorization(claude_home: Path) -> dict:
    """Load agent-to-plugin mapping from categorization JSON."""
    categorization_path = claude_home / "scripts/marketplace/agent-categorization.json"
    with open(categorization_path) as f:
        return json.load(f)


def get_project_agents(project_path: Path) -> list[str]:
    """Get list of agent files in project's .claude/agents/ directory."""
    agents_dir = project_path / ".claude/agents"
    if not agents_dir.exists():
        return []

    agent_files = list(agents_dir.glob("*.md"))
    # Extract agent names (filenames without .md extension)
    return [f.stem for f in agent_files]


def map_agents_to_plugins(agent_names: list[str], categorization: dict) -> dict[str, list[str]]:
    """Map agent names to their plugin IDs."""
    plugin_agents = defaultdict(list)

    for plugin_id, plugin_data in categorization.items():
        plugin_agent_names = plugin_data.get("agents", [])
        for agent in agent_names:
            if agent in plugin_agent_names:
                plugin_agents[plugin_id].append(agent)

    return dict(plugin_agents)


def generate_plugins_json(plugins: list[str]) -> dict:
    """Generate .claude/plugins.json content."""
    return {
        "version": "1.0.0",
        "plugins": [
            {
                "marketplace": "dot-claude",
                "id": plugin_id,
                "enabled": True
            }
            for plugin_id in plugins
        ]
    }


def migrate_project(
    project_path: Path,
    categorization: dict,
    dry_run: bool = False,
    remove_agents: bool = False
) -> dict:
    """
    Migrate a single project to plugin-based architecture.

    Args:
        project_path: Path to the project directory
        categorization: Agent-to-plugin mapping
        dry_run: If True, don't write files or remove agents
        remove_agents: If True, remove duplicate agent files after migration

    Returns:
        Migration report dictionary
    """
    project_name = project_path.name
    report = {
        "project": project_name,
        "path": str(project_path),
        "success": False,
        "agents_found": [],
        "plugins_required": [],
        "actions_taken": []
    }

    # Get agents in project
    agent_names = get_project_agents(project_path)
    report["agents_found"] = agent_names

    if not agent_names:
        report["success"] = True
        report["actions_taken"].append("No agents found - project already clean or has no .claude/agents/")
        return report

    # Map agents to plugins
    plugin_mapping = map_agents_to_plugins(agent_names, categorization)
    plugin_ids = sorted(plugin_mapping.keys())
    report["plugins_required"] = plugin_ids

    # Generate plugins.json
    plugins_json = generate_plugins_json(plugin_ids)
    plugins_json_path = project_path / ".claude/plugins.json"

    if not dry_run:
        # Write plugins.json
        with open(plugins_json_path, "w") as f:
            json.dump(plugins_json, f, indent=2)
        report["actions_taken"].append(f"Created .claude/plugins.json with {len(plugin_ids)} plugins")

        # Optionally remove agent files
        if remove_agents:
            agents_dir = project_path / ".claude/agents"
            for agent_file in agents_dir.glob("*.md"):
                agent_file.unlink()
            report["actions_taken"].append(f"Removed {len(agent_names)} duplicate agent files")

            # Remove agents directory if empty
            if not any(agents_dir.iterdir()):
                agents_dir.rmdir()
                report["actions_taken"].append("Removed empty .claude/agents/ directory")
    else:
        report["actions_taken"].append(f"[DRY RUN] Would create .claude/plugins.json with {len(plugin_ids)} plugins")
        if remove_agents:
            report["actions_taken"].append(f"[DRY RUN] Would remove {len(agent_names)} agent files")

    report["success"] = True
    return report


def migrate_all_projects(
    projects_file: Path,
    claude_home: Path,
    dry_run: bool = False,
    remove_agents: bool = False
) -> list[dict]:
    """
    Migrate all projects listed in active_projects.txt.

    Args:
        projects_file: Path to active_projects.txt
        claude_home: Path to ~/.claude directory
        dry_run: If True, don't write files or remove agents
        remove_agents: If True, remove duplicate agent files after migration

    Returns:
        List of migration reports
    """
    # Load categorization
    categorization = load_agent_categorization(claude_home)

    # Load project list
    with open(projects_file) as f:
        project_names = [line.strip() for line in f if line.strip()]

    # Get projects base directory
    projects_base = claude_home.parent / "Projects"

    # Migrate each project
    reports = []
    for project_name in project_names:
        project_path = projects_base / project_name
        if not project_path.exists():
            reports.append({
                "project": project_name,
                "path": str(project_path),
                "success": False,
                "error": "Project directory not found"
            })
            continue

        report = migrate_project(project_path, categorization, dry_run, remove_agents)
        reports.append(report)

    return reports


def print_report(reports: list[dict], dry_run: bool = False):
    """Print migration report to console."""
    print("\n" + "=" * 80)
    print("PROJECT MIGRATION REPORT")
    if dry_run:
        print("(DRY RUN MODE - No changes made)")
    print("=" * 80 + "\n")

    successful = [r for r in reports if r.get("success")]
    failed = [r for r in reports if not r.get("success")]

    print(f"Total Projects: {len(reports)}")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(failed)}")
    print()

    for report in reports:
        print(f"Project: {report['project']}")
        print(f"Path: {report['path']}")
        print(f"Status: {'✅ Success' if report.get('success') else '❌ Failed'}")

        if report.get("error"):
            print(f"Error: {report['error']}")
        else:
            agents = report.get("agents_found", [])
            plugins = report.get("plugins_required", [])
            print(f"Agents Found: {len(agents)}")
            print(f"Plugins Required: {len(plugins)}")
            if plugins:
                print(f"  - {', '.join(plugins)}")

            actions = report.get("actions_taken", [])
            if actions:
                print("Actions:")
                for action in actions:
                    print(f"  - {action}")

        print("-" * 80)

    print()


def save_report(reports: list[dict], output_path: Path):
    """Save migration report to JSON file."""
    with open(output_path, "w") as f:
        json.dump(reports, f, indent=2)
    print(f"Full report saved to: {output_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migrate projects to plugin-based architecture")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying files"
    )
    parser.add_argument(
        "--remove-agents",
        action="store_true",
        help="Remove duplicate agent files after migration"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.home() / ".claude/scripts/marketplace/migration-report.json",
        help="Path to save migration report JSON"
    )

    args = parser.parse_args()

    # Paths
    claude_home = Path.home() / ".claude"
    projects_file = claude_home.parent / "Projects/active_projects.txt"

    # Run migration
    reports = migrate_all_projects(
        projects_file,
        claude_home,
        dry_run=args.dry_run,
        remove_agents=args.remove_agents
    )

    # Print and save report
    print_report(reports, dry_run=args.dry_run)
    save_report(reports, args.output)

    # Summary
    successful = sum(1 for r in reports if r.get("success"))
    total = len(reports)

    if args.dry_run:
        print("\n🔍 Dry run complete. Use --remove-agents to migrate and clean up agent files.")
    elif successful == total:
        print("\n✅ All projects migrated successfully!")
    else:
        print(f"\n⚠️  {total - successful} project(s) had issues. Check the report above.")
