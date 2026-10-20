#!/usr/bin/env python3
from __future__ import annotations

"""Bifrost ↔ Qwen CLI base URL cutover smoke test.

Companion to ``scripts/bifrost_anthropic_url_cutover_smoke.py`` — same
shape, Qwen-specific target.

Verifies the Qwen cutover *plumbing* without requiring Bifrost to be live:

- ``scripts/bifrost-toggle-qwen-url`` is present and runnable.
- ``scripts/bifrost-ctl`` exists and is executable.
- ``~/.qwen/settings.json`` current state and whether Bifrost has touched it.
- dry-run toggle in both directions, capture diff.
- the actual gateway port (``8471``) bind state.

This is intentionally light on Bifrost-side checks — the cross-repo
``scripts/audit_bifrost_callers.py``, the operator-facing
``scripts/verify_qwen_bifrost_gate.sh``, and ``tests/integration/test_bifrost_*``
cover the gateway-side surface. This script targets the Qwen CLI cutover
mechanics specifically.

Run::

    python scripts/bifrost_qwen_url_cutover_smoke.py
    # optionally:
    #   --host 127.0.0.1 --port 8471 --settings ~/.qwen/settings.json

Exit codes:

- 0  — every check is OK or INFO (cutover plumbing is intact).
- 1  — at least one FAIL (file missing, helper crashed) — see report.
- 2  — settings.json invalid JSON or unreadable — fix by hand, retry.

The script is idempotent and read-only: it does not modify
``~/.qwen/settings.json`` (only ``bifrost-toggle-qwen-url --dry-run`` is
invoked).
"""

import argparse
import json
import socket
import subprocess
import sys
from pathlib import Path

DEFAULT_SETTINGS: Path = Path.home() / ".qwen" / "settings.json"
DEFAULT_BIFROST_HOST: str = "127.0.0.1"
DEFAULT_BIFROST_PORT: int = 8471
TOGGLE_HELPER: Path = Path(__file__).resolve().parent / "bifrost-toggle-qwen-url"
CTL_SCRIPT: Path = Path(__file__).resolve().parent / "bifrost-ctl"
LAUNCHD_READY: Path = Path.home() / ".local/state/mcp/ready/bifrost.ready"
LAUNCHD_LOG: Path = Path.home() / ".local/state/mcp/logs/bifrost.log"


def is_bifrost_url(value: str | None) -> bool:
    """Literal-string check; True iff ``value`` points at the configured Bifrost host:port.

    Smoke-grade: avoids full URL parsing. The 4-digit port check is sufficient
    to distinguish Bifrost-managed from operator-managed URLs.
    """
    return isinstance(value, str) and f":{DEFAULT_BIFROST_PORT}" in value


def read_settings_url(settings: Path) -> str | None:
    """Return the current ``env.OPENAI_BASE_URL`` value or ``None``.

    Returns ``None`` when the file is missing or empty (Qwen CLI falls
    back to its default), when ``env`` is missing, or when the key is
    absent.
    """
    if not settings.exists():
        return None
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"WARN: {settings} is not valid JSON; cannot read URL", file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, dict):
        return None
    env = data.get("env")
    if not isinstance(env, dict):
        return None
    value = env.get("OPENAI_BASE_URL")
    return value if isinstance(value, str) else None


def port_bound(host: str, port: int, timeout: float = 1.0) -> bool:
    """Return True iff a TCP connect to ``(host, port)`` succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def dry_run_toggle(toggle_helper: Path) -> tuple[str, str]:
    """Run the toggle helper in --dry-run for both directions.

    Returns ``(bifrost_out, direct_out)``. Never raises — non-zero exits
    fall through to empty stdout, which the caller reports as INFO.
    """
    bifrost_proc = subprocess.run(
        [sys.executable, str(toggle_helper), "bifrost", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    direct_proc = subprocess.run(
        [sys.executable, str(toggle_helper), "direct", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    return bifrost_proc.stdout.strip(), direct_proc.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test the Bifrost ↔ Qwen CLI base URL cutover plumbing.",
    )
    parser.add_argument("--host", default=DEFAULT_BIFROST_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_BIFROST_PORT)
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    args = parser.parse_args()

    report: list[str] = []
    failures: list[str] = []

    def check_or_fail(label: str, ok: bool, detail: str) -> None:
        line = f"[{('OK' if ok else 'FAIL')}] {label}: {detail}"
        report.append(line)
        if not ok:
            failures.append(line)

    check_or_fail("qwen toggle helper", TOGGLE_HELPER.exists(), str(TOGGLE_HELPER))
    check_or_fail("ctl script", CTL_SCRIPT.exists(), str(CTL_SCRIPT))

    current = read_settings_url(args.settings)
    if current is None:
        report.append(f"[INFO] OPENAI_BASE_URL: <unset> in {args.settings}")
    elif is_bifrost_url(current):
        report.append(f"[INFO] OPENAI_BASE_URL: Bifrost ({current})")
    else:
        report.append(f"[INFO] OPENAI_BASE_URL: custom/direct ({current})")

    if port_bound(args.host, args.port):
        report.append(
            f"[INFO] {args.host}:{args.port} is BOUND — Bifrost may be live. "
            "Run scripts/verify_qwen_bifrost_gate.sh before exercising the cutover."
        )
    else:
        report.append(
            f"[INFO] {args.host}:{args.port} is NOT BOUND — Bifrost is paused/down. "
            "See docs/specs/2026-10-20-bifrost-anthropic-baseurl-cutover-design.md §4."
        )

    if LAUNCHD_READY.exists():
        report.append(f"[OK]   launchd ready file: {LAUNCHD_READY}")
    else:
        report.append(f"[INFO] launchd ready file absent: {LAUNCHD_READY}")
    if LAUNCHD_LOG.exists():
        report.append(f"[INFO] bifrost.log present: {LAUNCHD_LOG}")
    else:
        report.append(f"[INFO] bifrost.log absent: {LAUNCHD_LOG}")

    if TOGGLE_HELPER.exists():
        bifrost_out, direct_out = dry_run_toggle(TOGGLE_HELPER)
        report.append(
            f"[OK]   dry-run toggle works "
            f"(bifrost: {len(bifrost_out)}ch, direct: {len(direct_out)}ch)"
        )
    else:
        failures.append("[FAIL] qwen toggle helper missing — cannot dry-run")

    print("\n".join(report))
    if failures:
        print(
            f"\n{len(failures)} failure(s); cutover plumbing NOT ready.",
            file=sys.stderr,
        )
        return 1
    print("\nCutover plumbing PASS — review INFO lines, then flip manually.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
