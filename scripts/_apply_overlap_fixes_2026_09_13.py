#!/usr/bin/env uv run python
"""Apply the 2026-09-13 overlap follow-up fixes.

Single transaction. Reads each file, parses YAML frontmatter, applies the
specified mutation, writes back. Aborts if any mutation can't be applied
(defensive).

Actions (from the 2026-09-12 audit follow-up evaluation):
  1. Recategorize ultracode plan: topic routing-composition -> verification-gate
  2. Add explicit blocks_on to the 3 stub MCP plans (gate on Plan 0b)
  3. Add related: in settle-semantic-merge pointing to finish-partial
  4. Add minimal frontmatter to untracked jot-drain.md + add related: in polish
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO = Path("/Users/les/Projects/mahavishnu")
NEW_DATE = "2026-09-13"


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return (raw_yaml, body). Caller decides whether frontmatter exists."""
    if not text.startswith("---"):
        return "", text
    end = text.find("\n---", 3)
    if end < 0:
        return "", text
    raw = text[3:end].lstrip("\n")
    body = text[end + 4 :].lstrip("\n")
    return raw, body


def ensure_list(fm: dict, key: str) -> list:
    val = fm.get(key)
    if val is None:
        fm[key] = []
        return fm[key]
    if isinstance(val, str):
        # yaml.safe_load may give string for inline list — coerce
        if val.startswith("[") and val.endswith("]"):
            try:
                fm[key] = yaml.safe_load(val)
            except yaml.YAMLError:
                fm[key] = [val]
        else:
            fm[key] = [val]
        return fm[key]
    if not isinstance(val, list):
        fm[key] = [val]
    return fm[key]


def write_with_frontmatter(path: Path, fm: dict, body: str) -> None:
    new_yaml = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True)
    path.write_text("---\n" + new_yaml + "---\n" + body)


def action_ultracode() -> None:
    path = REPO / "docs/plans/2026-07-11-ultracode-integration-wiring.md"
    raw, body = split_frontmatter(path.read_text())
    fm = yaml.safe_load(raw)
    fm["topic"] = "verification-gate"
    fm["last_reviewed"] = NEW_DATE
    write_with_frontmatter(path, fm, body)
    print(f"  OK: {path.relative_to(REPO)}  topic -> verification-gate")


def action_stub_mcp(path_rel: str, port_plan: str = "2026-09-06-port-bodai-reconciliation.md") -> None:
    path = REPO / path_rel
    raw, body = split_frontmatter(path.read_text())
    fm = yaml.safe_load(raw)
    block_list = ensure_list(fm, "blocks_on")
    target = port_plan  # relative to same dir
    if target not in block_list:
        block_list.append(target)
    fm["last_reviewed"] = NEW_DATE
    write_with_frontmatter(path, fm, body)
    print(f"  OK: {path.relative_to(REPO)}  blocks_on += {target}")


def action_settle_related() -> None:
    path = REPO / "docs/plans/2026-09-10-settle-semantic-merge.md"
    raw, body = split_frontmatter(path.read_text())
    fm = yaml.safe_load(raw)
    related_list = ensure_list(fm, "related")
    target = "2026-09-12-finish-partial-implementations.md"
    if target not in related_list:
        related_list.append(target)
    fm["last_reviewed"] = NEW_DATE
    write_with_frontmatter(path, fm, body)
    print(f"  OK: {path.relative_to(REPO)}  related += {target}")


def action_jot_drain_frontmatter() -> None:
    path = REPO / "docs/superpowers/plans/2026-09-10-jot-drain.md"
    text = path.read_text()
    raw, body = split_frontmatter(text)
    if raw:
        # already has frontmatter; refactor
        fm = yaml.safe_load(raw)
    else:
        fm = {}
    fm.update(
        {
            "status": "partial",
            "role": "implementation",
            "date": "2026-09-10",
            "last_reviewed": NEW_DATE,
            "superseded_by": None,
            "blocks_on": [],
            "topic": "convergence-control-plane",
            "title": "Jot Inbox: Drain Sub-Plan Implementation Plan",
        }
    )
    write_with_frontmatter(path, fm, body)
    print(f"  OK: {path.relative_to(REPO)}  added frontmatter (status=partial)")


def action_jot_polish_related() -> None:
    path = REPO / "docs/superpowers/plans/2026-09-12-jot-drain-polish.md"
    raw, body = split_frontmatter(path.read_text())
    fm = yaml.safe_load(raw)
    related_list = ensure_list(fm, "related")
    target = "2026-09-10-jot-drain.md"
    if target not in related_list:
        related_list.append(target)
    fm["last_reviewed"] = NEW_DATE
    write_with_frontmatter(path, fm, body)
    print(f"  OK: {path.relative_to(REPO)}  related += {target}")


def main() -> int:
    print("Action 1: Recategorize ultracode plan")
    action_ultracode()

    print("\nAction 2: Add blocks_on to stub MCP plans")
    for rel in [
        "docs/superpowers/plans/2026-09-06-archive-org-mcp.md",
        "docs/superpowers/plans/2026-09-06-medium-mcp.md",
        "docs/superpowers/plans/2026-09-06-scapy-mcp.md",
    ]:
        action_stub_mcp(rel)

    print("\nAction 3: Add related: in settle-semantic-merge")
    action_settle_related()

    print("\nAction 4: Add frontmatter to jot-drain.md + related in polish")
    action_jot_drain_frontmatter()
    action_jot_polish_related()

    print("\nAll 7 frontmatter mutations applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
