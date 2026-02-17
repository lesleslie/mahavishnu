#!/usr/bin/env python3
"""Create plugin directory structure and move agents into plugins."""

import json
import shutil
from pathlib import Path


def create_plugin_structure(base_dir: Path, categorization_file: Path):
    """Create plugin directories and copy agents into them."""

    # Load categorization
    with open(categorization_file) as f:
        categories = json.load(f)

    # Create plugins directory
    plugins_dir = base_dir / 'plugins'
    plugins_dir.mkdir(exist_ok=True)

    print("📁 Creating plugin directory structure...\n")

    for plugin_id, data in categories.items():
        plugin_dir = plugins_dir / plugin_id
        plugin_dir.mkdir(exist_ok=True)

        # Create .claude-plugin directory
        plugin_config_dir = plugin_dir / '.claude-plugin'
        plugin_config_dir.mkdir(exist_ok=True)

        # Create agents directory
        agents_dir = plugin_dir / 'agents'
        agents_dir.mkdir(exist_ok=True)

        print(f"  ✓ {plugin_id}")
        print(f"    - Agents: {len(data['agents'])}")

        # Copy agent files
        source_agents_dir = base_dir / 'agents'
        for agent_name in data['agents']:
            agent_file = f"{agent_name}.md"
            source = source_agents_dir / agent_file
            dest = agents_dir / agent_file

            if source.exists():
                shutil.copy2(source, dest)
            else:
                print(f"    ⚠️  Warning: {agent_file} not found")

    print(f"\n✅ Plugin structure created in: {plugins_dir}")


def main():
    """Main entry point."""
    base_dir = Path('/Users/les/.claude')
    categorization_file = base_dir / 'scripts/marketplace/agent-categorization.json'

    if not categorization_file.exists():
        print(f"❌ Categorization file not found: {categorization_file}")
        print("   Run categorize-agents.py first!")
        return

    create_plugin_structure(base_dir, categorization_file)


if __name__ == '__main__':
    main()
