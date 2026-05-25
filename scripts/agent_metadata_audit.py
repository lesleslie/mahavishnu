#!/usr/bin/env python3
"""
Comprehensive Agent Metadata Audit Script
"""

from collections import Counter
from pathlib import Path
import re


def extract_frontmatter(content):
    """Extract YAML frontmatter from markdown content."""
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", content, re.DOTALL)
    if match:
        yaml_str, body = match.groups()
        metadata = {}
        for line in yaml_str.split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip()
        return metadata, body
    return {}, content


def load_agents(agents_dir):
    """Load all agent files from the agents directory."""
    agents = []
    for agent_file in sorted(Path(agents_dir).glob("*.md")):
        with open(agent_file) as f:
            content = f.read()
        metadata, body = extract_frontmatter(content)
        agents.append(
            {
                "file": agent_file.name,
                "path": str(agent_file),
                "metadata": metadata,
                "body": body,
                "content": content,
            }
        )
    return agents


def compute_statistics(agents):
    """Compute summary statistics for agents."""
    lifecycles = Counter(a["metadata"].get("lifecycle", "unknown") for a in agents)
    models = Counter(a["metadata"].get("model", "missing") for a in agents)
    return lifecycles, models


def print_summary(total, lifecycles, models):
    """Print summary statistics."""
    print("=== AGENT METADATA AUDIT SUMMARY ===\n")
    print(f"Total agents found: {total}\n")
    print("Lifecycle distribution:")
    for lifecycle, count in lifecycles.most_common():
        print(f"  {lifecycle}: {count}")

    print("\nModel distribution:")
    for model, count in models.most_common():
        print(f"  {model}: {count}")


def check_metadata_issues(agents):
    """Check for missing metadata fields."""
    print("\n=== METADATA ISSUES ===")
    issues = []
    for agent in agents:
        file = agent["file"]
        meta = agent["metadata"]

        if not meta.get("name"):
            issues.append(f"{file}: Missing 'name' field")
        if not meta.get("description"):
            issues.append(f"{file}: Missing 'description' field")
        if not meta.get("model"):
            issues.append(f"{file}: Missing 'model' field")

    if issues:
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("  No critical metadata issues found")


def check_duplicates(agents):
    """Check for duplicate agent names."""
    print("\n=== POTENTIAL OVERLAPS ===")
    names = [a["metadata"].get("name", "") for a in agents]
    name_counts = Counter(names)
    duplicates = [(name, count) for name, count in name_counts.items() if count > 1 and name]

    if duplicates:
        for name, count in duplicates:
            print(f"  - '{name}' appears {count} times")
            matching_files = [a["file"] for a in agents if a["metadata"].get("name") == name]
            for f in matching_files:
                print(f"    - {f}")
    else:
        print("  No duplicate names found")


def check_naming_inconsistencies(agents):
    """Check for naming inconsistencies."""
    print("\n=== NAMING INCONSISTENCIES ===")
    similar_names = [
        ("devex-optimizer", "dx-optimizer"),
        ("monitoring-specialist", "observability-specialist"),
        ("backend-architect", "cloud-architect", "crackerjack-architect"),
    ]

    for name_group in similar_names:
        found = []
        for name in name_group:
            matching = [a for a in agents if a["metadata"].get("name") == name]
            if matching:
                agent = matching[0]
                found.append(f"{name} [{agent['metadata'].get('lifecycle', 'unknown')}]")
        if len(found) > 1:
            print(f"  - Similar agents: {', '.join(found)}")


def check_instruction_quality(agents):
    """Check instruction quality issues."""
    print("\n=== INSTRUCTION QUALITY CHECKS ===")
    quality_issues = []
    for agent in agents:
        meta = agent["metadata"]
        if meta.get("lifecycle") in ["deprecated", "archived"]:
            continue

        body = agent["body"]
        file = agent["file"]

        if len(body.strip()) < 200:
            quality_issues.append(f"{file}: Very short content ({len(body.strip())} chars)")

        if "```" not in body and len(body.strip()) > 500:
            quality_issues.append(f"{file}: No code examples despite length")

    if quality_issues:
        for issue in quality_issues[:10]:  # Show first 10
            print(f"  - {issue}")
    else:
        print("  No significant quality issues detected")


def main():
    """Main entry point for the audit script."""
    agents_dir = "/Users/les/.claude/agents"
    agents = load_agents(agents_dir)

    total = len(agents)
    lifecycles, models = compute_statistics(agents)

    print_summary(total, lifecycles, models)
    check_metadata_issues(agents)
    check_duplicates(agents)
    check_naming_inconsistencies(agents)
    check_instruction_quality(agents)

    print("\n=== END OF AUDIT ===")


if __name__ == "__main__":
    main()
