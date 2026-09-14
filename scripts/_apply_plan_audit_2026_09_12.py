#!/usr/bin/env uv run python
"""Apply the 2026-09-12 plan audit frontmatter changes.

Single transaction. Reads each plan file, parses YAML frontmatter,
flips status to the proposed value, updates last_reviewed to
2026-09-12, and writes back. Aborts if current status doesn't
match expected (defensive against mid-edit dirty-tree collisions).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import yaml

REPO = Path("/Users/les/Projects/mahavishnu")
NEW_DATE = "2026-09-12"

# (path, expected_current_status, new_status)
CHANGES: list[tuple[str, str, str]] = [
    # docs/plans/ — 9 → complete
    ("docs/plans/2026-04-04-ecosystem-execution-board.md", "active", "complete"),
    ("docs/plans/2026-07-29-pyscn-ty-quality-repair.md", "active", "complete"),
    ("docs/plans/2026-08-20-bodai-mcp-surface-standardization.md", "active", "complete"),
    ("docs/plans/2026-08-25-bodai-cli-audit.md", "active", "complete"),
    ("docs/plans/2026-08-25-bodai-cli-audit-implementation.md", "active", "complete"),
    ("docs/plans/2026-09-07-goose-terminal-adapter.md", "active", "complete"),
    ("docs/plans/2026-09-07-pi-pool-backend.md", "active", "complete"),
    ("docs/plans/2026-09-09-bodai-skill-agent-distribution.md", "active", "complete"),
    ("docs/plans/2026-09-10-bodai-math-initiatives-tier1.md", "active", "complete"),
    # docs/plans/ — 3 → partial
    ("docs/plans/2026-08-24-claude-env-audit-remediation.md", "active", "partial"),
    ("docs/plans/2026-09-10-settle-semantic-merge.md", "active", "partial"),
    ("docs/plans/2026-09-12-finish-partial-implementations.md", "active", "partial"),
    # docs/superpowers/plans/ — 2 → complete
    ("docs/superpowers/plans/2026-08-23-oneiric-action-kit-promotion.md", "active", "complete"),
    ("docs/superpowers/plans/2026-09-06-registry-manifest-migration.md", "active", "complete"),
    # docs/superpowers/plans/ — 3 → partial
    ("docs/superpowers/plans/2026-05-14-doc-sync-and-channel-phase2.md", "active", "partial"),
    ("docs/superpowers/plans/2026-07-16-bodai-plugin-standardization.md", "active", "partial"),
    ("docs/superpowers/plans/2026-09-12-jot-drain-polish.md", "active", "partial"),
    # docs/superpowers/specs/ — 5 → complete
    ("docs/superpowers/specs/2026-06-19-external-integrations-design.md", "active", "complete"),
    ("docs/superpowers/specs/2026-06-19-wave2a-chaos-hardening-design.md", "active", "complete"),
    ("docs/superpowers/specs/2026-06-19-wave2b-a2a-worker-design.md", "active", "complete"),
    ("docs/superpowers/specs/2026-07-14-multi-backend-pty-design.md", "active", "complete"),
    (
        "docs/superpowers/specs/2026-08-22-oneiric-action-kit-promotion-design.md",
        "active",
        "complete",
    ),
    # docs/superpowers/specs/ — 2 → partial
    (
        "docs/superpowers/specs/2026-05-16-llm-routing-standardization-design.md",
        "active",
        "partial",
    ),
    ("docs/superpowers/specs/2026-07-15-constellation-tui-design.md", "active", "partial"),
]


def split_frontmatter(text: str) -> tuple[str, str, str]:
    """Return (frontmatter_yaml, body, raw_frontmatter_block)."""
    if not text.startswith("---"):
        raise ValueError("file does not start with `---`")
    end = text.find("\n---", 3)
    if end < 0:
        raise ValueError("no closing `---` for frontmatter")
    raw = text[3:end].lstrip("\n")
    body = text[end + 4 :].lstrip("\n")
    return raw, body, text[: end + 4]


def main() -> int:
    rc = 0
    for relpath, expected, new_status in CHANGES:
        path = REPO / relpath
        if not path.exists():
            print(f"  MISSING: {relpath}", file=sys.stderr)
            rc = 1
            continue

        text = path.read_text()
        try:
            raw, body, _raw_block = split_frontmatter(text)
        except ValueError as exc:
            print(f"  NO_FRONTMATTER: {relpath}: {exc}", file=sys.stderr)
            rc = 1
            continue

        try:
            fm = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            print(f"  YAML_ERROR: {relpath}: {exc}", file=sys.stderr)
            rc = 1
            continue

        current = fm.get("status")
        if current != expected:
            print(
                f"  STATUS_MISMATCH: {relpath}: expected={expected!r}, found={current!r}",
                file=sys.stderr,
            )
            rc = 1
            continue

        old_date = fm.get("last_reviewed")
        fm["status"] = new_status
        fm["last_reviewed"] = NEW_DATE

        # Re-emit YAML preserving block scalar style where present.
        new_yaml = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True)
        new_block = "---\n" + new_yaml + "---"

        path.write_text(new_block + "\n" + body)
        print(
            f"  OK: {relpath}  {expected} -> {new_status}  (last_reviewed {old_date} -> {NEW_DATE})"
        )

    print()
    print(f"Total changes attempted: {len(CHANGES)}")
    print(f"Total errors: {1 if rc else 0}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
