"""Diff current CLI inventories against PHASE_0_BASELINE.json.

Catches regressions (command count shrank unexpectedly) and stale
findings (commands marked stale remain stale).

Run: `python3 scripts/diff_inventories.py`
Exit 0 = all Core 7 repos within tolerance; non-zero = regression or
unremediated staleness.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = REPO_ROOT / "docs" / "audit-inventory" / "PHASE_0_BASELINE.json"
INVENTORY_DIR = REPO_ROOT / "docs" / "audit-inventory"
TOLERANCE = 2


def main() -> int:
    baseline = json.loads(BASELINE_PATH.read_text())
    failures: list[str] = []
    for repo, baseline_data in baseline["repos"].items():
        inv_path = INVENTORY_DIR / f"{repo}-cli-inventory.json"
        if not inv_path.exists():
            failures.append(f"{repo}: inventory missing at {inv_path}")
            continue
        current = json.loads(inv_path.read_text())
        diff = current["command_count"] - baseline_data["command_count"]
        if abs(diff) > TOLERANCE:
            failures.append(f"{repo}: command count changed by {diff} (baseline={baseline_data['command_count']}, current={current['command_count']})")
        baseline_stale = sum(1 for c in baseline_data["commands"] if c["staleness_verdict"] in {"stale", "deprecated"})
        current_stale = sum(1 for c in current["commands"] if c["staleness_verdict"] in {"stale", "deprecated"})
        if current_stale > baseline_stale:
            failures.append(f"{repo}: stale count increased (baseline={baseline_stale}, current={current_stale})")
    if failures:
        print("FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"OK: all {len(baseline['repos'])} repos within tolerance")
    return 0


if __name__ == "__main__":
    sys.exit(main())