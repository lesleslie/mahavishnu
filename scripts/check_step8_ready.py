#!/usr/bin/env python3
"""Print whether migration step 8 is ready.

Step 8 fires at the later of:
  (a) this spec's cut-over + 14 days
  (b) jot sub-plan 3 ship date + 14 days

Plus: docs/feature-tracking/plan-index-dhara.md must record `adopted`.

Usage:
    python scripts/check_step8_ready.py \\
        [--cutover-date YYYY-MM-DD] [--jot-drain-ship-date YYYY-MM-DD]

Prints "ready: yes" or "ready: no" with the blocking reasons.
"""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
import os
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Any

import yaml  # PyYAML is already a project dep

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

_GRACE_DAYS = 14


def parse_frontmatter(path: Path) -> dict[str, Any] | None:
    """Parse YAML frontmatter from a markdown file, or None when absent."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    try:
        result = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return None
    return result if isinstance(result, dict) else None


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC).date()
    except ValueError:
        return None


def compute_blockers(
    *,
    today: date,
    cutover_date: str | None,
    jot_drain_ship_date: str | None,
    feature_tracking: Path,
) -> list[str]:
    """Return the list of reasons step 8 cannot fire. Empty list == ready."""
    blockers: list[str] = []

    cutover = parse_date(cutover_date)
    if cutover is None:
        blockers.append("cutover date unknown (set --cutover-date or PLAN_INDEX_CUTOVER_DATE)")
    else:
        cond_a = cutover + timedelta(days=_GRACE_DAYS)
        if today < cond_a:
            blockers.append(f"cutover+{_GRACE_DAYS}d ({cond_a}) not reached")

    # Condition (b) is optional: with no jot drain ship date the gate
    # reduces to condition (a) alone (spec D10).
    jot_ship = parse_date(jot_drain_ship_date)
    if jot_ship is not None:
        cond_b = jot_ship + timedelta(days=_GRACE_DAYS)
        if today < cond_b:
            blockers.append(f"jot-drain+{_GRACE_DAYS}d ({cond_b}) not reached")

    front = parse_frontmatter(feature_tracking)
    if not front or front.get("status") != "adopted":
        blockers.append(f"feature-tracking {feature_tracking} status != adopted")

    return blockers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cutover-date", type=str, default=os.environ.get("PLAN_INDEX_CUTOVER_DATE")
    )
    parser.add_argument(
        "--jot-drain-ship-date", type=str, default=os.environ.get("JOT_DRAIN_SHIP_DATE")
    )
    parser.add_argument(
        "--feature-tracking",
        type=Path,
        default=Path("docs/feature-tracking/plan-index-dhara.md"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    blockers = compute_blockers(
        today=datetime.now(tz=UTC).date(),
        cutover_date=args.cutover_date,
        jot_drain_ship_date=args.jot_drain_ship_date,
        feature_tracking=args.feature_tracking,
    )

    if not blockers:
        print("ready: yes")
        return 0

    print("ready: no")
    for blocker in blockers:
        print(f"  - {blocker}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
