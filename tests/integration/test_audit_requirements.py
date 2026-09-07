"""Integration test for the audit_requirements.py script (D2 traceable specs).

Runs ``scripts/audit_requirements.py`` against the real tree and asserts:
- The script exits with code 0 (no orphans or phantoms).
- The JSON output is valid and contains expected top-level keys.

This test is gated by ``@pytest.mark.integration`` and runs in the weekly
advisory cron (``.github/workflows/audit-requirements-weekly.yml``). It is
NOT a PR-blocking gate for the first 30 days (per the D2 promotion criteria).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_audit_requirements_reports_clean_state() -> None:
    """The script must exit cleanly (no orphans or phantoms) against the
    current tree. If this fails, declare the new requirement IDs in
    ``docs/plans/`` and reference them from code, or fix the convention.
    """
    result = subprocess.run(
        [sys.executable, "scripts/audit_requirements.py", "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"audit_requirements.py exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )

    payload = json.loads(result.stdout)
    assert "summary" in payload
    summary = payload["summary"]
    assert summary["orphan_count"] == 0, f"orphan requirements found: {payload['orphans']}"
    assert summary["phantom_count"] == 0, f"phantom requirements found: {payload['phantoms']}"


@pytest.mark.integration
def test_audit_requirements_emits_expected_keys() -> None:
    """The JSON output must include declared / referenced / orphans / phantoms /
    summary keys for downstream tooling (Session-Buddy, dashboards) to consume.
    """
    result = subprocess.run(
        [sys.executable, "scripts/audit_requirements.py", "--json", "--dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # --dry-run exits 0 even with orphans/phantoms, so just check the shape.
    assert result.returncode in (0, 1)
    payload = json.loads(result.stdout)
    for key in ("declared", "referenced", "orphans", "phantoms", "summary"):
        assert key in payload, f"missing key {key!r} in audit JSON output"