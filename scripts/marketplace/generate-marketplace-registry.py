#!/usr/bin/env python3
"""Generate marketplace.json registry file."""

import json
from pathlib import Path


def generate_marketplace_registry(base_dir: Path):
    """Generate the marketplace.json registry."""

    plugins_dir = base_dir / 'plugins'

    # Marketplace metadata
    registry = {
        "version": "1.0.0",
        "marketplace": {
            "id": "dot-claude",
            "name": "Dot Claude Marketplace",
            "description": "Official plugin marketplace for Claude Code specialists",
            "url": "https://gitlab.com/lesleslie/dot-claude",
            "homepage": "https://lesleslie.gitlab.io/dot-claude",
            "author": "lesleslie",
            "license": "MIT"
        },
        "plugins": [],
        "categories": {},
        "statistics": {
            "total_plugins": 0,
            "total_agents": 0,
            "total_mcp_servers": 0
        },
        "updated_at": "2025-10-26T00:00:00Z"
    }

    # Scan plugins directory
    if plugins_dir.exists():
        total_agents = 0

        for plugin_dir in sorted(plugins_dir.iterdir()):
            if not plugin_dir.is_dir():
                continue

            # Read plugin.json
            manifest_file = plugin_dir / '.claude-plugin' / 'plugin.json'
            if not manifest_file.exists():
                continue

            with open(manifest_file) as f:
                manifest = json.load(f)

            # Add to registry
            plugin_entry = {
                "id": manifest['id'],
                "name": manifest['name'],
                "description": manifest['description'],
                "version": manifest['version'],
                "path": f"plugins/{plugin_dir.name}",
                "agents_count": len(manifest.get('agents', [])),
                "tags": manifest.get('tags', []),
                "channels": manifest.get('channels', ['stable'])
            }

            registry['plugins'].append(plugin_entry)

            # Update categories
            for tag in manifest.get('tags', []):
                if tag not in registry['categories']:
                    registry['categories'][tag] = []
                registry['categories'][tag].append(manifest['id'])

            total_agents += len(manifest.get('agents', []))

        # Update statistics
        registry['statistics']['total_plugins'] = len(registry['plugins'])
        registry['statistics']['total_agents'] = total_agents

    # Write registry
    registry_file = base_dir / 'marketplace.json'
    with open(registry_file, 'w') as f:
        json.dump(registry, f, indent=2)

    return registry_file, registry


def main():
    """Main entry point."""
    # Use the repository root (2 levels up from this script)
    base_dir = Path(__file__).parent.parent.parent

    print("📋 Generating marketplace registry...\n")

    registry_file, registry = generate_marketplace_registry(base_dir)

    print(f"✅ Registry created: {registry_file}\n")
    print("📊 Statistics:")
    print(f"  - Total plugins: {registry['statistics']['total_plugins']}")
    print(f"  - Total agents: {registry['statistics']['total_agents']}")
    print(f"  - Categories: {len(registry['categories'])}")
    print(f"\n📝 Plugin List:")
    for plugin in registry['plugins']:
        print(f"  - {plugin['id']}: {plugin['agents_count']} agents")


if __name__ == '__main__':
    main()
