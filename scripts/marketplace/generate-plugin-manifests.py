#!/usr/bin/env python3
"""Generate plugin.json manifests for all plugins."""

import json
from pathlib import Path


def generate_plugin_manifest(plugin_id: str, data: dict, plugins_dir: Path):
    """Generate plugin.json manifest for a plugin."""

    # Plugin metadata
    manifest = {
        "id": plugin_id,
        "name": plugin_id.replace('-', ' ').title(),
        "version": "1.0.0",
        "description": data['description'],
        "author": "lesleslie",
        "homepage": "https://lesleslie.gitlab.io/dot-claude",
        "repository": "https://gitlab.com/lesleslie/dot-claude",
        "license": "MIT",
        "agents": sorted(data['agents']),
        "tags": determine_tags(plugin_id),
        "channels": ["stable"],
        "statistics": {
            "downloads": 0,
            "installations": 0
        },
        "created_at": "2025-10-26T00:00:00Z",
        "updated_at": "2025-10-26T00:00:00Z"
    }

    # Write plugin.json
    plugin_dir = plugins_dir / plugin_id / '.claude-plugin'
    plugin_dir.mkdir(parents=True, exist_ok=True)

    manifest_file = plugin_dir / 'plugin.json'
    with open(manifest_file, 'w') as f:
        json.dump(manifest, f, indent=2)

    return manifest_file


def determine_tags(plugin_id: str) -> list[str]:
    """Determine appropriate tags for a plugin."""

    tag_mapping = {
        'essentials': ['core', 'popular', 'recommended'],
        'programming-languages-advanced': ['languages', 'programming', 'advanced'],
        'database-specialists': ['database', 'storage', 'data'],
        'frontend-specialists': ['frontend', 'ui', 'design'],
        'backend-specialists': ['backend', 'api', 'server'],
        'devops-infrastructure': ['devops', 'deployment', 'infrastructure'],
        'ai-ml-specialists': ['ai', 'ml', 'data-science'],
        'security-testing': ['security', 'testing', 'qa', 'compliance'],
        'project-frameworks': ['frameworks', 'project-specific'],
        'leadership-management': ['leadership', 'management', 'product']
    }

    return tag_mapping.get(plugin_id, ['misc'])


def generate_readme(plugin_id: str, data: dict, plugins_dir: Path):
    """Generate README.md for a plugin."""

    readme_content = f"""# {plugin_id.replace('-', ' ').title()}

{data['description']}

## Included Agents ({len(data['agents'])})

"""

    for agent in sorted(data['agents']):
        readme_content += f"- **{agent}**\n"

    readme_content += f"""

## Installation

### Via Claude Code
```bash
/plugin install {plugin_id}
```

### Via GitLab Marketplace
Add to your project's `.claude/plugins.json`:
```json
{{
  "installed": [
    "{plugin_id}"
  ]
}}
```

## Repository

https://gitlab.com/lesleslie/dot-claude

## License

MIT
"""

    readme_file = plugins_dir / plugin_id / 'README.md'
    with open(readme_file, 'w') as f:
        f.write(readme_content)

    return readme_file


def main():
    """Main entry point."""
    base_dir = Path('/Users/les/.claude')
    categorization_file = base_dir / 'scripts/marketplace/agent-categorization.json'
    plugins_dir = base_dir / 'plugins'

    if not categorization_file.exists():
        print(f"❌ Categorization file not found: {categorization_file}")
        return

    # Load categorization
    with open(categorization_file) as f:
        categories = json.load(f)

    print("📝 Generating plugin manifests...\n")

    for plugin_id, data in categories.items():
        # Generate manifest
        manifest_file = generate_plugin_manifest(plugin_id, data, plugins_dir)
        print(f"  ✓ {plugin_id}")
        print(f"    - Manifest: {manifest_file}")

        # Generate README
        readme_file = generate_readme(plugin_id, data, plugins_dir)
        print(f"    - README: {readme_file}")

    print(f"\n✅ All plugin manifests generated!")


if __name__ == '__main__':
    main()
