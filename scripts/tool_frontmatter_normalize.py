#!/usr/bin/env python3
"""Normalize .claude/commands/tools/**/*.md frontmatter.

49 files in .claude/commands/tools/ currently have invalid YAML: top-level
keys (risk, status, id, category, required_scripts) are indented at column 2
under what should be list items, breaking PyYAML with
"mapping values are not allowed here".

This script:
- dedents orphaned scalar keys to column 0
- re-indents orphan `- item` list rows to column 2 under their parent key
- leaves indented list items (`  - value`) and the 70-underscore separator alone

Default mode is DRY-RUN. Pass --apply to write.
Idempotent: files already parseable as YAML are reported unchanged.

See .claude/decisions/ (to be added) for rationale and history.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

HOUSE_SEPARATOR = re.compile(r"^_{70,}\s*$", re.MULTILINE)
# Match a `key:` (with or without trailing whitespace/inline value).
# Trailing whitespace is optional because top-level keys like ``agents:``
# or ``tags:`` carry their values on the lines below, not inline.
SCALAR_KEY = re.compile(r"^[A-Za-z_]\w*:")


def normalize_yaml(yaml_text: str) -> str:
    """Rewrite a YAML block to fix column-0/-2 indentation."""
    lines = yaml_text.split("\n")
    out: list[str] = []
    last_top_key: str | None = None

    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if not stripped:
            out.append(line)
            continue

        # Top-level scalar key at column 0: `key: value`
        if indent == 0 and SCALAR_KEY.match(stripped):
            last_top_key = stripped.split(":", 1)[0]
            out.append(line)
            continue

        # Orphan list item at column 0: re-indent under last_top_key.
        if indent == 0 and stripped.startswith("- "):
            if last_top_key is not None:
                out.append("  " + stripped)
                continue
            out.append(line)
            continue

        # Orphaned scalar at column 2: dedent and remember it as the new top key.
        if indent == 2 and SCALAR_KEY.match(stripped):
            out.append(stripped)
            last_top_key = stripped.split(":", 1)[0]
            continue

        # Already-indented list item or other content: keep as-is.
        out.append(line)

    return "\n".join(out)


def normalize_file(path: Path) -> tuple[str, str]:
    """Return (original_text, proposed_text) for a house-style markdown file."""
    original = path.read_text()
    sep_match = HOUSE_SEPARATOR.search(original)
    if not sep_match:
        return original, original

    yaml_block = original[: sep_match.start()]
    sep_line = original[sep_match.start() : sep_match.end()]
    body = original[sep_match.end() :]

    new_yaml = normalize_yaml(yaml_block)
    proposed = new_yaml + sep_line + body
    return original, proposed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply", action="store_true", help="Write changes (default: dry-run, prints diff)"
    )
    parser.add_argument("files", nargs="+", help="Files to process")
    args = parser.parse_args()

    unchanged = changed = errors = 0
    for f in args.files:
        path = Path(f)
        try:
            original, proposed = normalize_file(path)
        except Exception as exc:
            print(f"ERROR  {path}: {exc}")
            errors += 1
            continue

        if original == proposed:
            print(f"OK     {path} (already normalized)")
            unchanged += 1
            continue

        if args.apply:
            path.write_text(proposed)
            print(f"WROTE  {path}")
        else:
            print(f"DIFF   {path}")
            for line in difflib.unified_diff(
                original.splitlines(keepends=True),
                proposed.splitlines(keepends=True),
                fromfile=f"{path} (before)",
                tofile=f"{path} (after)",
                n=2,
            ):
                sys.stdout.write(line)
        changed += 1

    mode = "APPLIED" if args.apply else "dry-run"
    print(f"\n[{mode}] unchanged={unchanged} changed={changed} errors={errors}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
