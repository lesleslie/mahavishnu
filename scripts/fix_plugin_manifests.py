#!/usr/bin/env python3
"""
Fix plugin manifest files to use array of agent file paths instead of directory path.
"""

import json
from pathlib import Path

def fix_plugin_manifest(plugin_dir: Path):
    """Fix a single plugin manifest."""
    manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
    agents_dir = plugin_dir / "agents"

    if not manifest_path.exists():
        print(f"⚠️  Manifest not found: {manifest_path}")
        return False

    if not agents_dir.exists():
        print(f"⚠️  Agents directory not found: {agents_dir}")
        return False

    # Load existing manifest
    with open(manifest_path, 'r') as f:
        manifest = json.load(f)

    # Get all .md files in agents directory
    agent_files = sorted([f"./agents/{f.name}" for f in agents_dir.glob("*.md")])

    if not agent_files:
        print(f"⚠️  No agent files found in: {agents_dir}")
        return False

    # Update agents field
    manifest["agents"] = agent_files

    # Write updated manifest
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)

    plugin_name = manifest.get("name", "unknown")
    print(f"✅ Fixed {plugin_name}: {len(agent_files)} agents")
    return True

def main():
    """Fix all plugin manifests in dot-claude marketplace."""
    marketplace_dir = Path("/Users/les/.claude/plugins/marketplaces/dot-claude/plugins")

    if not marketplace_dir.exists():
        print(f"❌ Marketplace directory not found: {marketplace_dir}")
        return

    print("🔧 Fixing plugin manifests...\n")

    fixed = 0
    failed = 0

    for plugin_dir in sorted(marketplace_dir.iterdir()):
        if plugin_dir.is_dir():
            if fix_plugin_manifest(plugin_dir):
                fixed += 1
            else:
                failed += 1

    print(f"\n📊 Summary: {fixed} fixed, {failed} failed")

if __name__ == "__main__":
    main()
