"""CI gate that every merge commit on `main` has a corresponding dev-log entry.

Per spec REQ-011: "every merge commit on `main` has a corresponding audit
log entry." Failure exits non-zero.

Implements: REQ-011
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path


def main() -> int:
    """Run the audit gate. Returns 0 on pass, non-zero on fail."""
    lookback_days = int(os.environ.get("AUDIT_DEVLOG_LOOKBACK_DAYS", "90"))
    cutoff = datetime.now(tz=UTC) - timedelta(days=lookback_days)

    # 1. Get merge commits on main within lookback.
    log_cmd = [
        "git",
        "log",
        f"--since={cutoff.isoformat()}",
        "--merges",
        "--first-parent",
        "--pretty=format:%H|%ai|%s",
        "main",
    ]
    log_result = subprocess.run(log_cmd, capture_output=True, text=True, check=False)
    if log_result.returncode != 0:
        print(f"ERROR: git log failed: {log_result.stderr}", file=sys.stderr)
        return 2

    merge_commits = []
    for line in log_result.stdout.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            sha, date, subject = parts
            merge_commits.append((sha, date, subject))

    # Short-circuit: no merges to audit → success, regardless of dev-log
    # dir state. Per spec REQ-011 the gate is "every merge commit has a
    # corresponding dev-log entry"; with zero commits there is nothing
    # to check, and a missing dev-log dir is not a failure (it is only
    # relevant when there is at least one merge to look up).
    if not merge_commits:
        print(f"OK: no merge commits on main in last {lookback_days} days.")
        return 0

    # 2. List dev-log entries.
    dev_log_dir = Path(
        os.environ.get("MAHAVISHNU_DEV_LOG_DIR", "~/.local/state/mahavishnu/dev-log")
    ).expanduser()
    if not dev_log_dir.exists():
        print(f"ERROR: dev-log dir missing: {dev_log_dir}", file=sys.stderr)
        return 2
    entry_dates = {f.stem for f in dev_log_dir.glob("*.md")}

    # 3. Check each merge commit has a corresponding entry.
    missing = []
    for sha, date, subject in merge_commits:
        merge_date = date[:10]  # YYYY-MM-DD
        # entry_date stems are <YYYY-MM-DD>-<branch>; substring match suffices.
        if not any(merge_date == stem[: len(merge_date)] for stem in entry_dates):
            missing.append((sha, merge_date, subject))

    if missing:
        print(f"FAIL: {len(missing)} merge commit(s) without audit-log entry:")
        for sha, date, subject in missing:
            print(f"  {sha[:12]} {date} {subject[:57] + '...'}")
        return 1

    print(f"OK: all {len(merge_commits)} merge commits on main have audit entries.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
