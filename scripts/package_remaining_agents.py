#!/usr/bin/env python3
"""
Package the 12 remaining agents into appropriate plugins.
"""

from pathlib import Path
import shutil

# Plugin assignment map
assignments = {
    "ai-ml-specialists": [
        "anthropic-claude-specialist",
        "langchain-specialist",
        "openai-specialist",
    ],
    "backend-specialists": ["rabbitmq-specialist"],
    "database-specialists": ["elasticsearch-specialist"],
    "devops-infrastructure": ["helm-specialist", "kubernetes-specialist"],
    "programming-languages-advanced": ["kotlin-specialist", "swift-specialist"],
    "security-testing": ["playwright-specialist", "vitest-specialist"],
    "essentials": ["MCP_ECOSYSTEM_CRITICAL_AUDIT"],
}


def copy_agents_to_plugins():
    """Copy agent files to appropriate plugin directories."""
    main_agents_dir = Path("/Users/les/.claude/agents")
    plugins_base = Path("/Users/les/.claude/plugins/marketplaces/dot-claude/plugins")

    print("📦 Copying agents to plugins...\n")

    total_copied = 0

    for plugin_name, agents in sorted(assignments.items()):
        plugin_agents_dir = plugins_base / plugin_name / "agents"

        if not plugin_agents_dir.exists():
            print(f"⚠️  Plugin directory not found: {plugin_agents_dir}")
            continue

        print(f"📂 {plugin_name}")

        for agent in agents:
            source = main_agents_dir / f"{agent}.md"
            dest = plugin_agents_dir / f"{agent}.md"

            if not source.exists():
                print(f"   ⚠️  Source not found: {agent}.md")
                continue

            if dest.exists():
                print(f"   ⏭️  Already exists: {agent}.md")
                continue

            shutil.copy2(source, dest)
            print(f"   ✅ Copied: {agent}.md")
            total_copied += 1

        print()

    print(f"📊 Summary: {total_copied} agents copied")
    return total_copied


if __name__ == "__main__":
    copied = copy_agents_to_plugins()
    exit(0 if copied > 0 else 1)
