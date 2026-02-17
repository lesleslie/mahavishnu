#!/usr/bin/env python3
"""
Verify that all agent files referenced in plugin manifests actually exist.
"""

import json
from pathlib import Path

def verify_plugin(plugin_dir: Path):
    """Verify all agent files exist for a plugin."""
    manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
    
    with open(manifest_path, 'r') as f:
        manifest = json.load(f)
    
    plugin_name = manifest.get("name", "unknown")
    agent_paths = manifest.get("agents", [])
    
    missing = []
    for agent_path in agent_paths:
        # Resolve relative path from plugin directory
        full_path = plugin_dir / agent_path.lstrip("./")
        if not full_path.exists():
            missing.append(agent_path)
    
    if missing:
        print(f"❌ {plugin_name}: {len(missing)} missing files")
        for path in missing:
            print(f"   - {path}")
        return False
    else:
        print(f"✅ {plugin_name}: All {len(agent_paths)} agent files exist")
        return True

def main():
    """Verify all plugins in dot-claude marketplace."""
    marketplace_dir = Path("/Users/les/.claude/plugins/marketplaces/dot-claude/plugins")
    
    print("🔍 Verifying plugin agent files...\n")
    
    verified = 0
    failed = 0
    
    for plugin_dir in sorted(marketplace_dir.iterdir()):
        if plugin_dir.is_dir():
            if verify_plugin(plugin_dir):
                verified += 1
            else:
                failed += 1
    
    print(f"\n📊 Summary: {verified} verified, {failed} failed")
    
    if failed > 0:
        return 1
    return 0

if __name__ == "__main__":
    exit(main())
