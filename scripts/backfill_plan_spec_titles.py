#!/usr/bin/env python3
"""
Backfill `title:` frontmatter for plans and specs at docs/plans/ and docs/specs/.

The plan-index cron rebuild (`mahavishnu/plan_index/cron_core.py`) requires both
`status` AND `title` in the frontmatter of each plan/spec to index it. After
the 2026-10-03 path migration (8207138a → 71014fca → 2ce3d897), 252 plans
and 67 specs at the new canonical paths lacked `title:` — pre-existing gap
exposed when the cron rebuild tried to ingest the newly-merged files.

This script:
  1. Walks docs/plans/ and docs/specs/ (recursive into .archive/)
  2. For each .md file without a `title:` line in its frontmatter,
     derive the title from the first H1 (`# ...`) or the first non-empty
     non-frontmatter line if no H1 exists
  3. Insert `title: <derived>` between the closing `---` and the body content
  4. SKIP files that already have `title:` (idempotent)
  5. Print a summary: count of files modified, sample titles

Run: `python scripts/backfill_plan_spec_titles.py [--dry-run]`
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (ROOT / "docs" / "plans", ROOT / "docs" / "specs")

# Frontmatter boundary: `---` on its own line, opening AND closing.
_FRONTMATTER_RE = re.compile(
    r"\A(?P<open>---\s*\n)(?P<fm>.*?)(?P<sep>\n---\s*\n)(?P<body>.*)",
    re.DOTALL,
)
_TITLE_RE = re.compile(r"^title\s*:\s*", re.MULTILINE)
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def _derive_title(body: str) -> str | None:
    """First H1 in body, stripped. Returns None if no H1 found."""
    m = _H1_RE.search(body)
    if m:
        return m.group(1).strip()
    # Fallback: first non-empty line that doesn't start with `#`, `>`, `-`, or `|`
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", ">", "-", "|", "```")):
            continue
        # Truncate at common Markdown inline chars (preserve readability)
        return re.split(r"[\[\(]", stripped, maxsplit=1)[0].strip()[:120]
    return None


def _process(path: Path, dry_run: bool) -> str | None:
    """Returns the derived title if the file was modified, else None."""
    text = path.read_text(encoding="utf-8")
    if _TITLE_RE.search(text):
        return None  # already has title — skip
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None  # no frontmatter — let cron rebuild skip silently
    fm = m.group("fm")
    sep = m.group("sep")
    body = m.group("body")
    title = _derive_title(body)
    if not title:
        return None
    # Quote title if it contains characters that confuse `_coerce_str` (colon,
    # hash, leading quote, etc.) — safe default: always quote with double-quotes
    safe = title.replace("\\", "\\\\").replace('"', '\\"')
    new_fm = fm.rstrip("\n") + f'\ntitle: "{safe}"\n'
    new_text = f"{m.group('open')}{new_fm}{sep}{body}"
    if dry_run:
        return title
    path.write_text(new_text, encoding="utf-8")
    return title


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without writing files",
    )
    args = p.parse_args()

    total = 0
    samples: list[tuple[Path, str]] = []
    for target in TARGETS:
        if not target.is_dir():
            continue
        for md in sorted(target.rglob("*.md")):
            title = _process(md, dry_run=args.dry_run)
            if title:
                total += 1
                if len(samples) < 5:
                    samples.append((md.relative_to(ROOT), title))
    mode = "would backfill" if args.dry_run else "backfilled"
    print(f"{mode} {total} files")
    for path, title in samples:
        print(f"  {path}: {title!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())