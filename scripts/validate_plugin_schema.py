#!/usr/bin/env python3
"""
Validate plugin manifests against Claude Code schema requirements.
"""

import json
from pathlib import Path

REQUIRED_FIELDS = ["name", "version", "description", "author", "license", "agents"]
REQUIRED_AUTHOR_FIELDS = ["name", "email"]

def validate_plugin(plugin_dir: Path):
    """Validate a single plugin manifest."""
    manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
    
    try:
        with open(manifest_path, 'r') as f:
            manifest = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ {plugin_dir.name}: Invalid JSON - {e}")
        return False
    
    plugin_name = manifest.get("name", plugin_dir.name)
    errors = []
    
    # Check required fields
    for field in REQUIRED_FIELDS:
        if field not in manifest:
            errors.append(f"Missing required field: {field}")
    
    # Check author structure
    if "author" in manifest:
        author = manifest["author"]
        if not isinstance(author, dict):
            errors.append("'author' must be an object")
        else:
            for field in REQUIRED_AUTHOR_FIELDS:
                if field not in author:
                    errors.append(f"Missing author.{field}")
    
    # Check agents is array
    if "agents" in manifest:
        agents = manifest["agents"]
        if not isinstance(agents, list):
            errors.append("'agents' must be an array")
        else:
            # Check each agent path ends with .md
            for i, agent in enumerate(agents):
                if not isinstance(agent, str):
                    errors.append(f"agents[{i}] must be a string")
                elif not agent.endswith(".md"):
                    errors.append(f"agents[{i}] must end with '.md': {agent}")
    
    if errors:
        print(f"❌ {plugin_name}: {len(errors)} validation error(s)")
        for error in errors:
            print(f"   - {error}")
        return False
    else:
        agent_count = len(manifest.get("agents", []))
        print(f"✅ {plugin_name}: Valid ({agent_count} agents)")
        return True

def main():
    """Validate all plugins in dot-claude marketplace."""
    marketplace_dir = Path("/Users/les/.claude/plugins/marketplaces/dot-claude/plugins")
    
    print("✓ Validating plugin schemas...\n")
    
    valid = 0
    invalid = 0
    
    for plugin_dir in sorted(marketplace_dir.iterdir()):
        if plugin_dir.is_dir():
            if validate_plugin(plugin_dir):
                valid += 1
            else:
                invalid += 1
    
    print(f"\n📊 Summary: {valid} valid, {invalid} invalid")
    
    if invalid > 0:
        return 1
    return 0

if __name__ == "__main__":
    exit(main())
