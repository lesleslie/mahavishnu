#!/usr/bin/env python3
"""
Validate plugin manifests against Claude Code schema requirements.
"""

from __future__ import annotations

import json
from pathlib import Path

REQUIRED_FIELDS = ["name", "version", "description", "author", "license", "agents"]
REQUIRED_AUTHOR_FIELDS = ["name", "email"]


def _load_manifest(plugin_dir: Path) -> tuple[dict | None, str | None]:
    """Load and parse plugin manifest JSON. Returns (manifest, error_msg)."""
    manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
    try:
        with open(manifest_path) as f:
            return json.load(f), None
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON - {e}"


def _validate_author(author: dict, errors: list[str]) -> None:
    """Validate author object and append errors to list."""
    if not isinstance(author, dict):
        errors.append("'author' must be an object")
        return
    for field in REQUIRED_AUTHOR_FIELDS:
        if field not in author:
            errors.append(f"Missing author.{field}")


def _validate_agents(agents, errors: list[str]) -> None:
    """Validate agents array and append errors to list."""
    if not isinstance(agents, list):
        errors.append("'agents' must be an array")
        return
    for i, agent in enumerate(agents):
        if not isinstance(agent, str):
            errors.append(f"agents[{i}] must be a string")
        elif not agent.endswith(".md"):
            errors.append(f"agents[{i}] must end with '.md': {agent}")


def _check_required_fields(manifest: dict, errors: list[str]) -> None:
    """Check that all required top-level fields are present."""
    for field in REQUIRED_FIELDS:
        if field not in manifest:
            errors.append(f"Missing required field: {field}")


def validate_plugin(plugin_dir: Path) -> bool:
    """Validate a single plugin manifest."""
    manifest, error = _load_manifest(plugin_dir)
    if error:
        print(f"❌ {plugin_dir.name}: {error}")
        return False

    plugin_name = manifest.get("name", plugin_dir.name)
    errors: list[str] = []

    _check_required_fields(manifest, errors)
    if "author" in manifest:
        _validate_author(manifest["author"], errors)
    if "agents" in manifest:
        _validate_agents(manifest["agents"], errors)

    if errors:
        print(f"❌ {plugin_name}: {len(errors)} validation error(s)")
        for error in errors:
            print(f"   - {error}")
        return False

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
