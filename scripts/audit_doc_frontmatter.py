#!/usr/bin/env python3
"""Audit YAML frontmatter conformance across the schema-governed doc stores.

`docs/schemas/document-frontmatter-v1.md` defines the frontmatter contract
for the documentation stores. `scripts/regenerate_plan_index.py` consumes
that frontmatter to render `docs/plans/PLAN_INDEX.md`, and it *silently
skips* any file whose frontmatter is absent or unparsable.

That silence is the hazard this audit exists to close. A file whose
frontmatter fails to parse looks identical to a file that has none: both
simply vanish from the index. A 2026-11-05 audit found a live decision
(`docs/decisions/2026-10-17-runpod-status-truth.md`) whose `description:`
value began with a backtick. YAML cannot start a plain scalar with a
backtick, so `yaml.safe_load` raised `ScannerError`, and the decision was
absent from the index with no error anywhere.

The stores governed by the schema are listed in ``SCHEMA_STORES``. Stores
with their own vocabularies — `docs/feature-tracking/` uses
``built | wired | adopted``, and `docs/audits/` predates the schema — are
deliberately excluded; see ``EXCLUDED_STORES`` for the reasoning.

Usage:
    python scripts/audit_doc_frontmatter.py [--repo-root PATH]

Exits 0 when every governed document conforms; 1 otherwise.
"""

from __future__ import annotations

import argparse
import datetime
from dataclasses import dataclass
from pathlib import Path
import re
import sys
from typing import TYPE_CHECKING

import yaml

from scripts.regenerate_plan_index import (
    KIND_VALUES,
    LIFECYCLE_VALUES,
    ROLE_VALUES,
    _is_excluded,
    extract_frontmatter,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

#: Stores the frontmatter schema governs. Each is a "Lite" or "Full"
#: schema store per docs/schemas/document-frontmatter-v1.md.
SCHEMA_STORES: tuple[str, ...] = (
    "docs/adr/",
    "docs/plans/",
    "docs/specs/",
    "docs/decisions/",
    "docs/followups/",
    "docs/initiatives/",
)

#: Stores that look like doc stores but are governed by another vocabulary.
#: `docs/feature-tracking/` tracks {built, wired, adopted} feature states
#: (see docs/feature-tracking/TEMPLATE.md); `docs/audits/` predates the
#: schema and has never been migrated. Validating them against the doc
#: schema would report failures that are not failures.
EXCLUDED_STORES: tuple[str, ...] = (
    "docs/feature-tracking/",
    "docs/audits/",
)

#: Keys every governed document must carry. `superseded_by` is conditional
#: on `role: superseded` and `blocks_on` is optional.
REQUIRED_KEYS: tuple[str, ...] = (
    "status",
    "role",
    "date",
    "last_reviewed",
    "topic",
)

#: Topic slugs are kebab-case, 3-40 characters, starting with a letter.
TOPIC_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{2,40}$")


@dataclass(frozen=True)
class Problem:
    """One frontmatter violation in one file."""

    path: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.code} — {self.message}"


def _is_iso_date(value: object) -> bool:
    """Return True when *value* is an ISO ``YYYY-MM-DD`` date."""
    if isinstance(value, datetime.datetime):
        return False
    if isinstance(value, datetime.date):
        return True
    return isinstance(value, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))


def _has_value(value: object) -> bool:
    """Return True when *value* is a meaningful, non-null value."""
    return value is not None and value != ""


def check_frontmatter(path: Path, rel: str) -> list[Problem]:
    """Return every frontmatter problem in one file.

    Distinguishes the two failure modes the indexer conflates: a file with
    no frontmatter block at all, and a file whose block is not parseable
    YAML. The latter is the dangerous one — it is invisible to every
    consumer that silently skips unparsable frontmatter.
    """
    problems: list[Problem] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [Problem(rel, "unreadable", str(exc))]

    lines = text.splitlines()
    has_block = bool(lines) and lines[0].rstrip() == "---"
    front = extract_frontmatter(text, yaml) if has_block else None

    if not has_block:
        return [
            Problem(rel, "frontmatter_missing", "file has no YAML frontmatter block")
        ]

    if front is None:
        return [
            Problem(
                rel,
                "frontmatter_malformed",
                "frontmatter block is not parseable YAML (the indexer skips it silently)",
            )
        ]

    for key in REQUIRED_KEYS:
        if key not in front:
            problems.append(
                Problem(rel, "key_missing", f"required key '{key}' is absent")
            )

    status = front.get("status")
    if "status" in front and status not in LIFECYCLE_VALUES:
        problems.append(
            Problem(
                rel,
                "status_invalid",
                f"status {status!r} is not one of {list(LIFECYCLE_VALUES)}",
            )
        )

    role = front.get("role")
    if "role" in front and role not in ROLE_VALUES:
        problems.append(
            Problem(
                rel, "role_invalid", f"role {role!r} is not one of {list(ROLE_VALUES)}"
            )
        )

    kind = front.get("kind")
    if kind is not None and kind not in KIND_VALUES:
        problems.append(
            Problem(
                rel, "kind_invalid", f"kind {kind!r} is not one of {list(KIND_VALUES)}"
            )
        )

    topic = front.get("topic")
    if "topic" in front and (
        not isinstance(topic, str) or not TOPIC_SLUG_RE.match(topic)
    ):
        problems.append(
            Problem(rel, "topic_invalid", f"topic {topic!r} is not a kebab-case slug")
        )

    for key in ("date", "last_reviewed"):
        if key in front and not _is_iso_date(front.get(key)):
            problems.append(
                Problem(
                    rel,
                    f"{key}_invalid",
                    f"{key} {front.get(key)!r} is not an ISO date",
                )
            )

    # A document is superseded if and only if it says so. `role: superseded`
    # without a successor is a broken chain; a successor without the role
    # is a document that reads as current while pointing at its replacement.
    superseded_by = front.get("superseded_by")
    if role == "superseded" and not _has_value(superseded_by):
        problems.append(
            Problem(
                rel,
                "superseded_mismatch",
                "role is 'superseded' but 'superseded_by' is empty",
            )
        )
    if role != "superseded" and _has_value(superseded_by):
        problems.append(
            Problem(
                rel,
                "superseded_mismatch",
                f"'superseded_by' is set but role is {role!r}, not 'superseded'",
            )
        )

    return problems


def audit_store(repo_root: Path, store: str) -> list[Problem]:
    """Return every frontmatter problem in one store."""
    root = repo_root / store.rstrip("/")
    if not root.is_dir():
        return []
    problems: list[Problem] = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(repo_root).as_posix()
        if _is_excluded(rel):
            continue
        problems.extend(check_frontmatter(path, rel))
    return problems


def audit_frontmatter(repo_root: Path) -> list[Problem]:
    """Return every frontmatter problem across the schema-governed stores."""
    problems: list[Problem] = []
    for store in SCHEMA_STORES:
        problems.extend(audit_store(repo_root, store))
    return problems


def format_problems(problems: list[Problem]) -> list[str]:
    """Render the problems as human-readable report lines."""
    if not problems:
        return ["OK: every schema-governed document has conformant frontmatter"]
    lines = [f"FAIL: {len(problems)} frontmatter problem(s) found"]
    lines.extend(f"  {problem}" for problem in problems)
    return lines


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Repository root (default: the repo containing this script)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root: Path = args.repo_root.resolve()

    problems = audit_frontmatter(repo_root)
    for line in format_problems(problems):
        print(line)
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
