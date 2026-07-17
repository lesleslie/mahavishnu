"""Audit `.claude/workflows/` for missing or mismatched decision files."""

from __future__ import annotations

import re
from pathlib import Path

DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-([a-z0-9-]+)\.md$")


def audit_workflows(repo_root: Path) -> list[str]:
    """Return a list of human-readable issues; empty list means clean."""
    issues: list[str] = []
    wf_dir = repo_root / ".claude" / "workflows"
    dec_dir = repo_root / ".claude" / "decisions" / "workflows"

    if not wf_dir.is_dir():
        return issues

    active = sorted(p for p in wf_dir.glob("*.js") if p.is_file())
    decisions = {p.stem for p in dec_dir.glob("*.md")} if dec_dir.is_dir() else set()

    for wf in active:
        stem = wf.stem  # e.g. "crackerjack-coverage-fanout-wave4"
        # Look for any decision file whose date-name-slug matches the workflow slug.
        # Convention: decision file ends with "-<workflow-stem>.md"
        match = next((d for d in decisions if d.endswith(f"-{stem}")), None)
        if match is None:
            issues.append(f"{wf.name}: no paired decision file in {dec_dir}")

    return issues


if __name__ == "__main__":
    import sys

    repo = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    issues = audit_workflows(repo)
    if issues:
        for line in issues:
            print(f"FAIL: {line}")
        sys.exit(1)
    print("OK")
