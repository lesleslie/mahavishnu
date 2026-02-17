#!/usr/bin/env python3
"""
Add PROACTIVELY or IMMEDIATELY triggers to agent descriptions where missing.
"""

import re
import glob

# Define agents and their appropriate triggers
TRIGGERS = {
    'code-reviewer.md': ('PROACTIVELY', 'code reviews, pull requests, or quality checks'),
    'incident-responder.md': ('IMMEDIATELY', 'production incidents or outages'),
    'architecture-council.md': ('PROACTIVELY', 'architectural decisions or design reviews'),
    'qa-strategist.md': ('PROACTIVELY', 'test strategy, quality planning, or risk assessment'),
    'product-manager.md': ('PROACTIVELY', 'product planning, prioritization, or roadmap decisions'),
    'finops-specialist.md': ('PROACTIVELY', 'cloud cost optimization or spend analysis'),
    'observability-incident-lead.md': ('PROACTIVELY', 'monitoring setup, incident response, or observability'),
    'context-manager.md': ('PROACTIVELY', 'multi-agent coordination or complex workflows'),
    'release-manager.md': ('PROACTIVELY', 'release planning, governance, or deployment coordination'),
    'customer-success-lead.md': ('PROACTIVELY', 'customer onboarding, adoption, or value realization'),
    'data-retention-specialist.md': ('PROACTIVELY', 'data lifecycle, retention policies, or compliance'),
    'ux-researcher.md': ('PROACTIVELY', 'user research, usability testing, or product insights'),
    'privacy-officer.md': ('PROACTIVELY', 'privacy impact, data governance, or regulatory compliance'),
    'data-scientist.md': ('PROACTIVELY', 'data analysis, SQL queries, or BigQuery operations'),
    'claude-environment-auditor.md': ('PROACTIVELY', 'Claude configuration issues or environment optimization'),
    'content-designer.md': ('PROACTIVELY', 'UX copy, product content, or knowledge assets'),
    'accessibility-auditor.md': ('PROACTIVELY', 'accessibility compliance, WCAG audits, or inclusive design'),
    'prompt-engineer.md': ('PROACTIVELY', 'prompt optimization, LLM tuning, or system prompt design'),
    'support-analytics-specialist.md': ('PROACTIVELY', 'support data analysis or customer insights'),
    'general-assistant.md': ('PROACTIVELY', 'general tasks, coordination, or basic assistance'),
    'developer-enablement-lead.md': ('PROACTIVELY', 'developer experience, tooling, or modernization'),
    'delivery-lead.md': ('PROACTIVELY', 'delivery planning, execution, or risk management'),
}

def add_trigger_to_description(file_path, trigger_word, use_case):
    """Add proactive trigger to agent description."""
    with open(file_path, 'r') as f:
        content = f.read()

    # Check if trigger already exists
    if trigger_word in content:
        print(f"✓ {file_path.split('/')[-1]}: Already has {trigger_word}")
        return False

    # Find the description field
    desc_pattern = r'(description:.*?)(\nmodel:)'
    match = re.search(desc_pattern, content, re.DOTALL)

    if not match:
        print(f"✗ {file_path.split('/')[-1]}: Could not find description")
        return False

    old_desc = match.group(1)

    # Add trigger at the end of description
    new_desc = old_desc.rstrip()
    if not new_desc.endswith('.'):
        new_desc += '.'

    new_desc += f' Use {trigger_word} for {use_case}.'

    # Replace in content
    new_content = content.replace(old_desc, new_desc)

    with open(file_path, 'w') as f:
        f.write(new_content)

    print(f"✓ {file_path.split('/')[-1]}: Added {trigger_word}")
    return True

def main():
    """Process all agents needing triggers."""
    updated = 0
    skipped = 0

    for filename, (trigger, use_case) in TRIGGERS.items():
        file_path = f"/Users/les/.claude/agents/{filename}"
        try:
            if add_trigger_to_description(file_path, trigger, use_case):
                updated += 1
            else:
                skipped += 1
        except FileNotFoundError:
            print(f"✗ {filename}: File not found")
        except Exception as e:
            print(f"✗ {filename}: Error - {e}")

    print(f"\n=== Summary ===")
    print(f"Updated: {updated}")
    print(f"Skipped: {skipped}")
    print(f"Total: {updated + skipped}")

if __name__ == '__main__':
    main()
