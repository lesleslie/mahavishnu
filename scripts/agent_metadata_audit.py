#!/usr/bin/env python3
"""
Comprehensive Agent Metadata Audit Script
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import re
import sys


def extract_frontmatter(content):
    """Extract frontmatter (YAML or collapsed ``## name: ...``) from markdown content.

    Returns ``(metadata, body)`` where ``metadata`` is a dict. Prefers YAML
    frontmatter (``---`` delimited) and falls back to the collapsed
    single-line format used by this repo's agent files:

        ## name: <slug> description: >- <free text> model: <model>

    where the body is everything after the frontmatter line.
    """
    # Frontmatter delimiter: a line of 3+ dashes OR underscores.
    # Matches both standard YAML (``---``) and the 70-underscore house
    # style used by some agent files (e.g. ``.claude/agents/mahavishnu-orchestrator.md``).
    # The backreference ``\1`` ensures the closer matches the opener
    # character — ``---`` cannot be closed by ``___`` or vice versa.
    match = re.match(r"^([-_]{3,})\n(.*?)\n\1\n(.*)$", content, re.DOTALL)
    if match:
        # Three capture groups: delimiter, YAML body, post-frontmatter body.
        # Group 1 (the delimiter) is unused here.
        yaml_str = match.group(2)
        body = match.group(3)
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


def find_dot_prefixed_agent_files(agents_dir):
    """Find agent ``.md`` files that live inside a dot-prefixed subdirectory.

    Claude Code scans agent directories *recursively*, so **every** ``.md`` file
    under an agents directory is loaded as an agent — including files in a
    dot-prefixed subdirectory that looks like an archive. Untracking those
    files in git (or ignoring them) hides them from version control but not
    from the loader.

    This is the exact failure that let 49 retired agents sit in
    ``.claude/agents/.archive/`` for four months while charging ~2.2k tokens
    against every turn. See ``docs/decisions/agent-curation-strategy.md``.

    Returns a list of ``(md_path, dot_directory)`` tuples.
    """
    root = Path(agents_dir)
    if not root.is_dir():
        return []
    findings = []
    for md in sorted(root.rglob("*.md")):
        if not md.is_file():
            continue
        try:
            relative = md.relative_to(root)
        except ValueError:  # pragma: no cover - rglob always yields under root
            continue
        # Only the directory components matter: a dot-prefixed *file* name is
        # a different (and much narrower) concern.
        dot_dirs = [part for part in relative.parts[:-1] if part.startswith(".")]
        if dot_dirs:
            findings.append((md, dot_dirs[0]))
    return findings


def check_dot_prefixed_subdirectories(agents_dir):
    """Check that no agent file is hidden in a dot-prefixed subdirectory.

    Prints the offending files and returns the number of violations found.
    """
    print(f"\n=== DOT-PREFIXED SUBDIRECTORY SCAN ({agents_dir}) ===")
    findings = find_dot_prefixed_agent_files(agents_dir)
    if not findings:
        print("  No agent files hidden in dot-prefixed subdirectories")
        return 0
    for md, dot_dir in findings:
        print(f"  - {md}: inside '{dot_dir}/' — Claude Code still loads it as an agent")
    print(
        f"  {len(findings)} agent file(s) hidden in a dot-prefixed subdirectory.\n"
        "  Move them outside the agents directory "
        "(e.g. ~/.claude/.archive/agents-removed/)\n"
        "  or delete them. Untracking or gitignoring them does NOT hide them from\n"
        "  Claude Code — it scans the filesystem, not git."
    )
    return len(findings)


def main():
    """Main entry point for the audit script."""
    parser = argparse.ArgumentParser(
        description="Audit Claude Code agent metadata and agent-directory layout."
    )
    parser.add_argument(
        "--agents-dir",
        default=None,
        help="Project agents directory to audit (default: the repo's .claude/agents).",
    )
    parser.add_argument(
        "--user-agents-dir",
        default=None,
        help="User-level agents directory to scan (default: ~/.claude/agents).",
    )
    parser.add_argument(
        "--skip-user-agents-dir",
        action="store_true",
        help="Do not scan the user-level agents directory.",
    )
    args = parser.parse_args()

    # Derive the project agents directory from this script's location so
    # the audit runs against the repo's own agents (not the user's global
    # agents dir). Works from any clone of the project without config.
    agents_dir = args.agents_dir or str(
        Path(__file__).resolve().parent.parent / ".claude" / "agents"
    )
    agents = load_agents(agents_dir)

    total = len(agents)
    lifecycles, models = compute_statistics(agents)

    print_summary(total, lifecycles, models)
    check_metadata_issues(agents)
    check_duplicates(agents)
    check_naming_inconsistencies(agents)
    check_instruction_quality(agents)

    # The checks above only see top-level agent files, so a file parked in a
    # dot-prefixed subdirectory is invisible to them. Scan the filesystem
    # recursively so the archive-in-the-scan-path failure cannot come back
    # unnoticed.
    violations = check_dot_prefixed_subdirectories(agents_dir)

    user_agents_dir = args.user_agents_dir or str(Path.home() / ".claude" / "agents")
    if (
        not args.skip_user_agents_dir
        and Path(user_agents_dir).is_dir()
        and Path(user_agents_dir) != Path(agents_dir)
    ):
        violations += check_dot_prefixed_subdirectories(user_agents_dir)

    print("\n=== END OF AUDIT ===")

    if violations:
        print(
            f"FAILED: {violations} agent file(s) hidden in dot-prefixed "
            "subdirectories. Claude Code loads these as agents; move them out "
            "of the agents directory."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
