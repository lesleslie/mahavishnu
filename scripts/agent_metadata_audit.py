#!/usr/bin/env python3
"""
Comprehensive Agent Metadata Audit Script
"""

import os
import re
import glob
from pathlib import Path
from collections import defaultdict, Counter
import json

def extract_frontmatter(content):
    """Extract YAML frontmatter from markdown content."""
    match = re.match(r'^---\n(.*?)\n---\n(.*)$', content, re.DOTALL)
    if match:
        yaml_str, body = match.groups()
        metadata = {}
        for line in yaml_str.split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                metadata[key.strip()] = value.strip()
        return metadata, body
    return {}, content

agents_dir = Path("/Users/les/.claude/agents")
agents = []

# Load all agent files
for agent_file in sorted(agents_dir.glob("*.md")):
    with open(agent_file, 'r') as f:
        content = f.read()
    metadata, body = extract_frontmatter(content)
    agents.append({
        'file': agent_file.name,
        'path': str(agent_file),
        'metadata': metadata,
        'body': body,
        'content': content
    })

# Summary statistics
total = len(agents)
lifecycles = Counter(a['metadata'].get('lifecycle', 'unknown') for a in agents)
models = Counter(a['metadata'].get('model', 'missing') for a in agents)

print(f"=== AGENT METADATA AUDIT SUMMARY ===\n")
print(f"Total agents found: {total}\n")
print(f"Lifecycle distribution:")
for lifecycle, count in lifecycles.most_common():
    print(f"  {lifecycle}: {count}")

print(f"\nModel distribution:")
for model, count in models.most_common():
    print(f"  {model}: {count}")

# Check for metadata issues
print(f"\n=== METADATA ISSUES ===")
issues = []
for agent in agents:
    file = agent['file']
    meta = agent['metadata']
    
    if not meta.get('name'):
        issues.append(f"{file}: Missing 'name' field")
    if not meta.get('description'):
        issues.append(f"{file}: Missing 'description' field")
    if not meta.get('model'):
        issues.append(f"{file}: Missing 'model' field")
        
if issues:
    for issue in issues:
        print(f"  - {issue}")
else:
    print("  No critical metadata issues found")

# Check for duplicates and overlaps
print(f"\n=== POTENTIAL OVERLAPS ===")
names = [a['metadata'].get('name', '') for a in agents]
name_counts = Counter(names)
duplicates = [(name, count) for name, count in name_counts.items() if count > 1 and name]

if duplicates:
    for name, count in duplicates:
        print(f"  - '{name}' appears {count} times")
        matching_files = [a['file'] for a in agents if a['metadata'].get('name') == name]
        for f in matching_files:
            print(f"    - {f}")
else:
    print("  No duplicate names found")

# Check for naming inconsistencies
print(f"\n=== NAMING INCONSISTENCIES ===")
similar_names = [
    ('devex-optimizer', 'dx-optimizer'),
    ('monitoring-specialist', 'observability-specialist'),
    ('backend-architect', 'cloud-architect', 'crackerjack-architect')
]

for name_group in similar_names:
    found = []
    for name in name_group:
        matching = [a for a in agents if a['metadata'].get('name') == name]
        if matching:
            agent = matching[0]
            found.append(f"{name} [{agent['metadata'].get('lifecycle', 'unknown')}]")
    if len(found) > 1:
        print(f"  - Similar agents: {', '.join(found)}")

print(f"\n=== INSTRUCTION QUALITY CHECKS ===")
quality_issues = []
for agent in agents:
    meta = agent['metadata']
    if meta.get('lifecycle') in ['deprecated', 'archived']:
        continue
        
    body = agent['body']
    file = agent['file']
    
    if len(body.strip()) < 200:
        quality_issues.append(f"{file}: Very short content ({len(body.strip())} chars)")
    
    if '```' not in body and len(body.strip()) > 500:
        quality_issues.append(f"{file}: No code examples despite length")

if quality_issues:
    for issue in quality_issues[:10]:  # Show first 10
        print(f"  - {issue}")
else:
    print("  No significant quality issues detected")

print(f"\n=== END OF AUDIT ===")
