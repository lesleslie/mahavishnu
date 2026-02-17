#!/usr/bin/env python3
"""
Agent Discovery Tool - Find the right agent for your task.

Usage:
    python3 discover_agent.py "task description"
    python3 discover_agent.py --tag python
    python3 discover_agent.py --list-tags
"""

import glob
import re
import sys
from collections import defaultdict
from typing import List, Dict, Tuple

def parse_agent_file(file_path: str) -> Dict:
    """Parse agent metadata from markdown file."""
    with open(file_path, 'r') as f:
        content = f.read()

    # Extract frontmatter
    name = re.search(r'^name:\s*(.+)$', content, re.MULTILINE)
    desc = re.search(r'^description:\s*(.+?)(?=\nmodel:)', content, re.DOTALL | re.MULTILINE)
    model = re.search(r'^model:\s*(.+)$', content, re.MULTILINE)
    color = re.search(r'^color:\s*(.+)$', content, re.MULTILINE)
    tags = re.search(r'^tags:\s*\n((?:^-\s*.+$\n?)+)', content, re.MULTILINE)

    # Parse tags
    tag_list = []
    if tags:
        tag_lines = tags.group(1).strip().split('\n')
        tag_list = [line.strip('- ').strip() for line in tag_lines]

    return {
        'name': name.group(1) if name else 'Unknown',
        'description': desc.group(1).strip() if desc else '',
        'model': model.group(1) if model else 'unknown',
        'color': color.group(1) if color else None,
        'tags': tag_list,
        'file': file_path.split('/')[-1],
        'has_proactive': 'PROACTIVELY' in content or 'IMMEDIATELY' in content
    }

def load_all_agents() -> List[Dict]:
    """Load all agent metadata."""
    agents = []
    for file_path in glob.glob('/Users/les/.claude/agents/*.md'):
        try:
            agent = parse_agent_file(file_path)
            agents.append(agent)
        except Exception as e:
            print(f"Error parsing {file_path}: {e}", file=sys.stderr)
    return agents

def search_agents(query: str, agents: List[Dict]) -> List[Tuple[Dict, float]]:
    """Search agents by query with relevance scoring."""
    results = []
    query_lower = query.lower()
    query_words = set(query_lower.split())

    for agent in agents:
        score = 0.0

        # Name match (highest weight)
        if query_lower in agent['name'].lower():
            score += 10.0

        # Description match
        desc_lower = agent['description'].lower()
        if query_lower in desc_lower:
            score += 5.0

        # Word matches in description
        desc_words = set(desc_lower.split())
        word_matches = len(query_words & desc_words)
        score += word_matches * 2.0

        # Tag matches
        for tag in agent['tags']:
            if query_lower in tag.lower():
                score += 3.0

        if score > 0:
            results.append((agent, score))

    return sorted(results, key=lambda x: x[1], reverse=True)

def filter_by_tag(tag: str, agents: List[Dict]) -> List[Dict]:
    """Filter agents by tag."""
    return [a for a in agents if tag.lower() in [t.lower() for t in a['tags']]]

def get_all_tags(agents: List[Dict]) -> Dict[str, int]:
    """Get all unique tags with counts."""
    tag_counts = defaultdict(int)
    for agent in agents:
        for tag in agent['tags']:
            tag_counts[tag] += 1
    return dict(sorted(tag_counts.items()))

def print_agent(agent: Dict, score: float = None):
    """Print agent information."""
    color_emoji = {
        'red': '🔴', 'orange': '🟠', 'amber': '🟡', 'green': '🟢',
        'blue': '🔵', 'purple': '🟣', 'cyan': '🩵', 'emerald': '💚',
        'pink': '🩷', 'teal': '🔷', 'indigo': '🟦', 'violet': '🟪'
    }

    emoji = color_emoji.get(agent['color'], '⚪')
    model_emoji = {'opus': '💎', 'sonnet': '🎵', 'haiku-4.5': '⚡'}.get(agent['model'], '🤖')

    print(f"\n{emoji} {agent['name']}")
    if score:
        print(f"   Relevance: {score:.1f}/10")
    print(f"   Model: {model_emoji} {agent['model']}")
    print(f"   Tags: {', '.join(agent['tags'][:5])}")
    desc_short = agent['description'][:150] + '...' if len(agent['description']) > 150 else agent['description']
    print(f"   {desc_short}")

def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  discover_agent.py 'task description'")
        print("  discover_agent.py --tag python")
        print("  discover_agent.py --list-tags")
        sys.exit(1)

    agents = load_all_agents()
    print(f"Loaded {len(agents)} agents\n")

    if sys.argv[1] == '--list-tags':
        tags = get_all_tags(agents)
        print("Available tags:")
        for tag, count in tags.items():
            print(f"  {tag}: {count} agents")
        return

    if sys.argv[1] == '--tag':
        if len(sys.argv) < 3:
            print("Error: --tag requires a tag name")
            sys.exit(1)
        tag = sys.argv[2]
        filtered = filter_by_tag(tag, agents)
        print(f"Found {len(filtered)} agents with tag '{tag}':")
        for agent in filtered[:10]:
            print_agent(agent)
        return

    # Search query
    query = ' '.join(sys.argv[1:])
    results = search_agents(query, agents)

    if not results:
        print(f"No agents found for: {query}")
        print("\nTry:")
        print("  - Using different keywords")
        print("  - Listing all tags with: --list-tags")
        print("  - Filtering by tag with: --tag <tagname>")
        return

    print(f"Found {len(results)} agents for: '{query}'\n")
    print("=" * 60)

    # Show top 5 results
    for agent, score in results[:5]:
        print_agent(agent, score)

    if len(results) > 5:
        print(f"\n... and {len(results) - 5} more results")
        print("Refine your search for more specific results")

if __name__ == '__main__':
    main()
