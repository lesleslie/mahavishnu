#!/usr/bin/env python3
"""
Comprehensive Agent Metadata Audit Script
"""

from collections import Counter
from pathlib import Path
import re


def extract_frontmatter(content):
    """Extract frontmatter (YAML or collapsed ``## name: ...``) from markdown content.

    Returns ``(metadata, body)`` where ``metadata`` is a dict. Prefers YAML
    frontmatter (``---`` delimited) and falls back to the collapsed
    single-line format used by this repo's agent files:

        ## name: <slug> description: >- <free text> model: <model>

    where the body is everything after the frontmatter line.
    """
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", content, re.DOTALL)
    if match:
        yaml_str, body = match.groups()
        metadata = {}
        for line in yaml_str.split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip()
        return metadata, body
    # Fallback: collapsed `## name: ... description: >- ... model: ...` format.
    meta = _extract_collapsed_frontmatter(content)
    if meta:
        # Body is everything after the matched frontmatter line. The line
        # may be followed by a blank line OR directly by body text — do
        # not assume a ``\n\n`` separator (the previous implementation
        # silently dropped the entire body when the blank line was missing).
        body = _body_after_collapsed_line(content)
        return meta, body
    return {}, content


def _extract_collapsed_frontmatter(content):
    """Parse the collapsed ``## name: ... description: ... model: ...`` format.

    Returns an empty dict if no collapsed frontmatter line is present.
    The ``description:`` value may be either a plain string
    (``description: <text>``) or a YAML folded-block indicator
    (``description: >- <text>``); both forms are handled.

    The search is restricted to the first 5 non-blank lines of the
    content so a body heading like ``## name: old-name`` deep in the
    body cannot be mis-attribute the frontmatter name.
    """
    # Frontmatter lives on the first non-blank line of an agent file;
    # look at most 5 lines deep so a stray body heading that happens to
    # start with ``## name:`` can never be mistaken for the frontmatter.
    _FRONTMATTER_SCAN_WINDOW = 5
    lines = content.split("\n")
    for line in lines[:_FRONTMATTER_SCAN_WINDOW]:
        stripped = line.strip()
        if not stripped.startswith("## name:"):
            continue
        # Strip the `## name:` prefix.
        rest = stripped[len("## name:") :].strip()
        # Model is the rightmost ` model: <slug>` field, anchored at end-of-line.
        m = re.search(r"\s+model:\s*(\S+)\s*$", rest)
        if not m:
            return {}
        model = m.group(1)
        rest = rest[: m.start()].rstrip()
        # Description: rightmost ` description:` field (use the last occurrence
        # so description text containing the word "description:" is preserved).
        desc_matches = list(re.finditer(r"\s+description:\s*", rest))
        if not desc_matches:
            return {}
        m_desc = desc_matches[-1]
        name = rest[: m_desc.start()].strip()
        after = rest[m_desc.end() :].strip()
        # Optional YAML folded-block indicator: `>- ` or `>-`.
        if after.startswith(">- "):
            after = after[3:]
        elif after.startswith(">-"):
            after = after[2:]
        description = after.strip()
        return {"name": name, "description": description, "model": model}
    return {}


def _body_after_collapsed_line(content):
    """Return everything after the collapsed frontmatter line.

    The frontmatter line may be followed by:
      * a blank line, then body text (typical);
      * body text directly on the next line (no separator).

    The previous implementation used ``content.split("\\n\\n", 1)`` which
    silently dropped the entire body when the blank line was missing —
    for example a one-line collapsed frontmatter followed immediately by
    the body produced an empty body. This helper slices the original
    content from after the matched frontmatter line so both layouts
    produce the same correct result.
    """
    lines = content.split("\n")
    for idx, line in enumerate(lines[:5]):
        stripped = line.strip()
        if not stripped.startswith("## name:"):
            continue
        # Found the frontmatter line. Body is everything after it,
        # including the trailing newline (caller can .strip() if needed).
        return "\n".join(lines[idx + 1 :])
    # No frontmatter line matched — fall back to the original behaviour
    # (return the full content) so callers don't get surprising blanks.
    return content


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
    # Derive the project agents directory from this script's location so
    # the audit runs against the repo's own agents (not the user's global
    # agents dir). Works from any clone of the project without config.
    agents_dir = str(Path(__file__).resolve().parent.parent / ".claude" / "agents")
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
