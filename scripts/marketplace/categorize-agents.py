#!/usr/bin/env python3
"""Categorize agents into plugin groups based on their tags and descriptions."""

import json
import re
from pathlib import Path
from typing import Dict, List, Set

import yaml


def parse_agent_metadata(agent_path: Path) -> Dict:
    """Extract frontmatter metadata from agent file."""
    with open(agent_path) as f:
        content = f.read()

    # Extract YAML frontmatter
    match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return {}

    metadata = yaml.safe_load(match.group(1))
    metadata['filename'] = agent_path.name
    return metadata


def categorize_agents(agents_dir: Path) -> Dict[str, List[str]]:
    """Categorize all agents into plugin groups."""

    # Define plugin categories
    categories = {
        'essentials': {
            'description': 'Essential agents for all Claude Code projects',
            'agents': []
        },
        'programming-languages-advanced': {
            'description': 'Advanced programming language specialists',
            'agents': []
        },
        'database-specialists': {
            'description': 'Database and storage specialists',
            'agents': []
        },
        'frontend-specialists': {
            'description': 'Frontend development and design specialists',
            'agents': []
        },
        'backend-specialists': {
            'description': 'Backend architecture and API specialists',
            'agents': []
        },
        'devops-infrastructure': {
            'description': 'DevOps, deployment, and infrastructure specialists',
            'agents': []
        },
        'ai-ml-specialists': {
            'description': 'AI, ML, and data science specialists',
            'agents': []
        },
        'security-testing': {
            'description': 'Security, testing, and quality assurance specialists',
            'agents': []
        },
        'project-frameworks': {
            'description': 'Project-specific framework specialists',
            'agents': []
        },
        'leadership-management': {
            'description': 'Leadership, product, and organizational specialists',
            'agents': []
        }
    }

    # Essential agents (most commonly used - keep this small!)
    essentials_names = {
        'code-reviewer', 'refactoring-specialist',
        'python-pro', 'javascript-pro', 'typescript-pro',
        'general-assistant', 'context-manager',
        'documentation-specialist', 'tutorial-engineer',
        'agent-creation-specialist', 'search-specialist',
        'prompt-engineer', 'mermaid-expert'
    }

    # Leadership & management specialists
    leadership_names = {
        'architecture-council', 'product-manager', 'delivery-lead',
        'customer-success-lead', 'release-manager', 'developer-enablement-lead',
        'qa-strategist', 'ux-researcher'
    }

    # Parse all agents
    agent_metadata = {}
    for agent_file in sorted(agents_dir.glob('*.md')):
        metadata = parse_agent_metadata(agent_file)
        if metadata:
            agent_metadata[metadata['name']] = metadata

    # Categorize agents
    for name, meta in agent_metadata.items():
        tags = set(meta.get('tags', []))

        # Check essentials first (explicitly listed)
        if name in essentials_names:
            categories['essentials']['agents'].append(name)
        # Leadership & management
        elif name in leadership_names:
            categories['leadership-management']['agents'].append(name)
        # Project-specific frameworks
        elif any(proj in name for proj in ['acb', 'fastblocks', 'starlette', 'htmy']):
            categories['project-frameworks']['agents'].append(name)
        # Programming languages (advanced)
        elif any(lang in tags for lang in ['go', 'rust', 'java', 'cpp', 'c', 'c++', 'flutter', 'systems']):
            categories['programming-languages-advanced']['agents'].append(name)
        # Databases
        elif any(db in tags for db in ['database', 'sql', 'nosql', 'redis', 'postgresql', 'mysql', 'sqlite']):
            categories['database-specialists']['agents'].append(name)
        # Data engineering (separate from general databases)
        elif any(data in tags for data in ['data-science', 'data-pipelines', 'etl', 'analytics', 'experimentation']):
            categories['ai-ml-specialists']['agents'].append(name)
        # Frontend
        elif any(fe in tags for fe in ['frontend', 'css', 'html', 'ui', 'ux', 'accessibility', 'responsive']):
            categories['frontend-specialists']['agents'].append(name)
        # Backend
        elif any(be in tags for be in ['backend', 'api', 'graphql', 'grpc', 'websocket', 'authentication']):
            categories['backend-specialists']['agents'].append(name)
        # DevOps
        elif any(ops in tags for ops in ['devops', 'docker', 'kubernetes', 'terraform', 'deployment', 'cloud']):
            categories['devops-infrastructure']['agents'].append(name)
        # Operations/Incidents
        elif any(inc in tags for inc in ['incidents', 'oncall', 'operations', 'observability', 'incident-response']):
            categories['devops-infrastructure']['agents'].append(name)
        # AI/ML
        elif any(ai in tags for ai in ['ai', 'ml', 'machine-learning', 'mlops', 'gemini', 'vector']):
            categories['ai-ml-specialists']['agents'].append(name)
        # Security/Testing/Compliance
        elif any(sec in tags for sec in ['security', 'testing', 'qa', 'audit', 'compliance', 'privacy']):
            categories['security-testing']['agents'].append(name)
        # Mobile
        elif 'mobile' in tags or 'android' in tags or 'ios' in tags:
            categories['frontend-specialists']['agents'].append(name)
        # Templates/Tooling specialists
        elif any(tool in tags for tool in ['jinja2', 'templates', 'pycharm', 'plugins', 'tooling']):
            categories['devops-infrastructure']['agents'].append(name)
        # Documentation/Reference
        elif 'reference' in tags or 'documentation' in tags:
            categories['essentials']['agents'].append(name)
        # Integration specialists
        elif 'mcp' in tags or 'integration' in tags:
            categories['project-frameworks']['agents'].append(name)
        # Customer/Support specialists
        elif any(cs in tags for cs in ['customer-success', 'support', 'customer-experience']):
            categories['leadership-management']['agents'].append(name)
        else:
            # Truly uncategorized
            print(f"⚠️  Uncategorized: {name} (tags: {tags})")
            categories['essentials']['agents'].append(name)

    return categories


def main():
    """Main entry point."""
    agents_dir = Path('/Users/les/.claude/agents')

    print("🔍 Analyzing 83 agents...")
    categories = categorize_agents(agents_dir)

    print("\n📊 Plugin Categories:\n")
    total = 0
    for plugin_id, data in categories.items():
        count = len(data['agents'])
        total += count
        print(f"  {plugin_id}: {count} agents")

    print(f"\n  Total: {total} agents\n")

    # Write categorization to file
    output_file = Path('/Users/les/.claude/scripts/marketplace/agent-categorization.json')
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w') as f:
        json.dump(categories, f, indent=2)

    print(f"✅ Categorization saved to: {output_file}")

    # Print detailed breakdown
    print("\n📝 Detailed Breakdown:\n")
    for plugin_id, data in categories.items():
        print(f"\n{plugin_id} ({len(data['agents'])} agents):")
        print(f"  {data['description']}")
        for agent in sorted(data['agents']):
            print(f"    - {agent}")


if __name__ == '__main__':
    main()
