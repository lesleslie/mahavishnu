"""Validate findings.md row links against the per-repo inventory JSONs.

Per Plan Task 2.1 / 2.2 CI gate:
  - findings.md ≤ 250 lines (separate budget check; see pre-commit hook)
  - Each row's `(<repo>-cli-inventory.json#L<line>)` link must resolve:
    - file exists at the resolved path
    - target line is in range
    - the line at target line contains a `"command_path"` JSON key
      (so the link actually points to a command, not noise)

Exit codes:
  0  all links valid
  1  one or more links broken (printed to stderr with the offending row)

Usage:
  python3 scripts/validate_findings.py docs/audit-inventory/findings.md
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

LINK_PATTERN = re.compile(r"\((?:\.\./)?audit-inventory/([\w-]+-cli-inventory\.json)#L(\d+)\)")
LINE_BUDGET = 250


def _line_content_has_command(raw_lines: list[str], target_line: int, repo: str) -> bool:
    """The cited line must contain a JSON command_path key (start of a command object)."""
    if target_line < 1 or target_line > len(raw_lines):
        return False
    line = raw_lines[target_line - 1]
    return '"command_path":' in line


def _resolve(findings_path: Path, repo_file: str) -> Path:
    """Resolve a sibling inventory file in the same directory as findings.md.

    findings.md lives at docs/audit-inventory/findings.md; the cited
    JSONs live alongside it at docs/audit-inventory/<repo>-cli-inventory.json.
    The markdown links use `../audit-inventory/<file>` (one level up
    then back in), which is correct relative addressing from
    `docs/audit-inventory/findings.md`. We resolve by treating the
    JSON as a sibling of findings.md.
    """
    return (findings_path.parent / repo_file).resolve()


def validate(findings_path: Path) -> int:
    findings_text = findings_path.read_text()
    line_count = len(findings_text.splitlines())
    if line_count > LINE_BUDGET:
        print(
            f"findings.md exceeds {LINE_BUDGET}-line budget ({line_count} lines)",
            file=sys.stderr,
        )
        return 1

    # Cache raw lines per referenced JSON file
    raw_cache: dict[Path, list[str]] = {}

    broken: list[str] = []
    for line_num, line in enumerate(findings_text.splitlines(), start=1):
        for match in LINK_PATTERN.finditer(line):
            repo_file = match.group(1)
            target_line = int(match.group(2))
            target = _resolve(findings_path, repo_file)
            if target not in raw_cache:
                if not target.exists():
                    broken.append(
                        f"L{line_num}: file not found: {target} (cited in row: {line.strip()[:80]})"
                    )
                    continue
                raw_cache[target] = target.read_text().splitlines(keepends=False)
            if not _line_content_has_command(raw_cache[target], target_line, repo_file):
                broken.append(
                    f"L{line_num}: link {repo_file}#{target_line} not a command row (row: {line.strip()[:80]})"
                )

    if broken:
        print(f"findings.md has {len(broken)} broken link(s):", file=sys.stderr)
        for entry in broken:
            print(f"  {entry}", file=sys.stderr)
        return 1

    print(
        f"OK: findings.md ({line_count} lines, ≤ {LINE_BUDGET}); all links resolve to commands"
    )
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"Usage: {argv[0]} <findings.md>", file=sys.stderr)
        return 2
    return validate(Path(argv[1]))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))