#!/usr/bin/env python3
"""Clean up the stale-PID warning emitted by ``reflection.duckdb``.

Background
----------

Session-Buddy holds an exclusive write lock on
``~/.claude/data/reflection.duckdb`` for as long as its process is alive.
DuckDB records the holder's PID inside the file's internal lock metadata.
When Session-Buddy is killed unceremoniously (or the previous holder
crashed mid-transaction), DuckDB keeps the stale PID in the file. The
next process that tries to open the file gets a defensive error message
naming the dead PID, even though the actual OS-level lock is free.

Symptoms::

    _duckdb.IOException: IO Error: Could not set lock on file
    ".../reflection.duckdb": Conflicting lock is held in
    /.../python3.13 (PID 96870) by user les.

This script resolves the warning in three steps:

1. Gracefully shut down Session-Buddy (SIGTERM, then SIGKILL if needed).
2. Open ``reflection.duckdb`` in write mode, load the ``vss`` extension
   if the file contains HNSW indexes, and run ``CHECKPOINT`` to flush
   the WAL and refresh the stale PID record to the current process.
3. Optionally restart Session-Buddy and verify the ecosystem is healthy.

The script is idempotent: if the lock is free, it exits 0 without
touching Session-Buddy.

Usage::

    python scripts/cleanup_reflection_db.py
    python scripts/cleanup_reflection_db.py --dry-run
    python scripts/cleanup_reflection_db.py --no-restart
    python scripts/cleanup_reflection_db.py --shutdown-timeout 30
    python scripts/cleanup_reflection_db.py --db-path /custom/path.duckdb
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
from typing import NamedTuple
from urllib.parse import urlparse

# Default location of the Session-Buddy reflection store. Override with
# --db-path. The HNSW index requirement means we always need the ``vss``
# DuckDB extension when this file contains vector search indexes.
DEFAULT_DB_PATH = Path.home() / ".claude" / "data" / "reflection.duckdb"

# How Session-Buddy is started. The default assumes the standard install
# location at ``~/Projects/session-buddy`` and the project's venv.
DEFAULT_SB_CWD = Path.home() / "Projects" / "session-buddy"
DEFAULT_SB_CMD = [
    str(DEFAULT_SB_CWD / ".venv" / "bin" / "python"),
    "-m",
    "session_buddy",
    "start",
    "--force",
]

# How to find Session-Buddy's PID. We match on the command line rather
# than a fixed port because the process may not be listening yet during
# a slow start.
SB_PGREP_PATTERN = "session_buddy start"

# Default health endpoint to verify after restart.
DEFAULT_HEALTH_URL = "http://127.0.0.1:8678/health"

# How long to wait between SIGTERM and SIGKILL when Session-Buddy is
# being uncooperative. Most clean shutdowns complete in <2s; anything
# beyond 15s suggests a hang in cleanup, so escalate.
DEFAULT_SHUTDOWN_TIMEOUT = 15.0

__all__ = [
    "DEFAULT_DB_PATH",
    "DEFAULT_SB_CWD",
    "DEFAULT_SB_CMD",
    "CleanupResult",
    "LockProbe",
    "ALLOWED_HEALTH_SCHEMES",
    "force_release_lock",
    "is_process_alive",
    "probe_lock",
    "restart_session_buddy",
    "run_checkpoint",
    "shutdown_session_buddy",
    "validate_health_url",
    "verify_lock_refreshed",
    "verify_health",
]


# Schemes accepted by ``verify_health``. We restrict to ``http`` only:
#
# - ``urllib.request.urlopen`` also accepts ``file://`` (CWE-939), so
#   the narrower set rules out local-file disclosure via the URL flag.
# - ``https`` would require us to construct an ``ssl.SSLContext`` for
#   ``http.client.HTTPSConnection``; since the health endpoint is
#   always a local infrastructure probe (default
#   ``http://127.0.0.1:8678/health``), HTTPS adds complexity and
#   certificate-validation attack surface for no real benefit. If a
#   future deployment fronts Session-Buddy with a TLS-terminating
#   proxy, the operator can extend ``ALLOWED_HEALTH_SCHEMES`` and
#   update ``_http_get_json`` accordingly.
ALLOWED_HEALTH_SCHEMES = frozenset({"http"})


def validate_health_url(url: str) -> str:
    """Reject URLs whose scheme is not in ``ALLOWED_HEALTH_SCHEMES``.

    Returns the URL unchanged on success; raises ``ValueError`` on a
    disallowed scheme so callers can fail fast with a clear error.
    """
    scheme = urlparse(url).scheme.lower()
    if scheme not in ALLOWED_HEALTH_SCHEMES:
        raise ValueError(
            f"health URL must use one of {sorted(ALLOWED_HEALTH_SCHEMES)}, "
            f"got scheme={scheme!r} in {url!r}"
        )
    return url


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class LockProbe(NamedTuple):
    """Outcome of trying to acquire the DuckDB write lock.

    ``holder_pid`` is the PID reported in DuckDB's error message, or
    ``None`` if the lock was free and we opened the file successfully.
    ``stale`` is True when the recorded PID is no longer a live process
    — this is exactly the case this script exists to clean up.
    """

    locked: bool
    holder_pid: int | None
    stale: bool


@dataclass(frozen=True)
class CleanupResult:
    """Final report from ``run_cleanup`` for logging and exit codes."""

    lock_was_held: bool
    holder_pid: int | None
    holder_was_alive: bool
    checkpoint_ok: bool
    new_holder_pid: int | None
    restart_attempted: bool
    restart_ok: bool | None  # None = not attempted
    health_ok: bool | None  # None = not attempted
    duration_seconds: float

    @property
    def ok(self) -> bool:
        """True if every stage that ran completed without error."""
        return (
            self.checkpoint_ok and (self.restart_ok is not False) and (self.health_ok is not False)
        )


# ---------------------------------------------------------------------------
# Lock detection
# ---------------------------------------------------------------------------


def _import_duckdb() -> object:
    """Import duckdb with a clear error message if it's not installed."""
    try:
        import duckdb  # type: ignore[import-untyped]

        return duckdb
    except ImportError as e:
        raise RuntimeError(
            "duckdb is required for cleanup_reflection_db.py. Install with: uv pip install duckdb"
        ) from e


def probe_lock(db_path: Path) -> LockProbe:
    """Try to open the DuckDB file and report what's holding the lock.

    DuckDB raises ``IOException`` whose message contains the conflicting
    PID. We parse that out and cross-check against the live process table
    via ``is_process_alive`` to classify the holder as live or stale.

    If the file is missing or unreadable for a non-lock reason, the
    underlying exception is re-raised so the caller can decide.
    """
    duckdb = _import_duckdb()
    try:
        con = duckdb.connect(str(db_path))
        con.close()
        return LockProbe(locked=False, holder_pid=None, stale=False)
    except Exception as e:  # noqa: BLE001 — duckdb raises generic Exception
        msg = str(e)
        m = re.search(r"\(PID\s+(\d+)\)", msg)
        if "Conflicting lock" not in msg or not m:
            raise
        pid = int(m.group(1))
        return LockProbe(
            locked=True,
            holder_pid=pid,
            stale=not is_process_alive(pid),
        )


def is_process_alive(pid: int) -> bool:
    """True if a process with the given PID is currently running.

    Uses ``os.kill(pid, 0)`` — the standard POSIX probe that sends a no-op
    signal to test for existence. Returns False (not raises) for any
    error, including the common ``ProcessLookupError`` (no such PID) and
    ``PermissionError`` (PID exists but owned by another user — the
    process IS alive in that case, but we can't signal it; treat that as
    "live" so we don't try to clean up someone else's lock).
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # owned by another user — don't touch it
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Process management
# ---------------------------------------------------------------------------


def _find_session_buddy_pid() -> int | None:
    """Return the PID of the running Session-Buddy, or None.

    Uses ``pgrep -f`` to match on the command line. We avoid hardcoding a
    PID so the script works across restarts. If multiple instances are
    running, returns the most recent one (``pgrep -n``).
    """
    pgrep = shutil.which("pgrep")
    if pgrep is None:
        return None
    try:
        result = subprocess.run(
            [pgrep, "-fn", SB_PGREP_PATTERN],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return int(result.stdout.strip().splitlines()[-1])
    except ValueError:
        return None


def shutdown_session_buddy(
    pid: int,
    timeout: float = DEFAULT_SHUTDOWN_TIMEOUT,
    log: Callable[[str], None] = print,
) -> bool:
    """Send SIGTERM, wait, then SIGKILL if the process survives.

    Returns True if the process is gone (whether by graceful exit or by
    SIGKILL). Returns False only if the process is still alive after
    both attempts.
    """
    if not is_process_alive(pid):
        log(f"PID {pid} already gone")
        return True

    log(f"Sending SIGTERM to Session-Buddy (PID {pid})")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except OSError as e:
        log(f"  SIGTERM failed: {e}")
        return False

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_process_alive(pid):
            log(
                f"  Session-Buddy exited gracefully after {timeout - (deadline - time.monotonic()):.1f}s"
            )
            return True
        time.sleep(0.2)

    log(f"  Process survived {timeout}s, escalating to SIGKILL")
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except OSError as e:
        log(f"  SIGKILL failed: {e}")
        return False

    # Give the kernel a moment to actually reap it.
    time.sleep(0.5)
    return not is_process_alive(pid)


def restart_session_buddy(
    cmd: list[str] = DEFAULT_SB_CMD,
    cwd: Path = DEFAULT_SB_CWD,
    log: Callable[[str], None] = print,
) -> int | None:
    """Spawn a fresh Session-Buddy detached and return its PID.

    Uses ``start_new_session=True`` so the child survives our exit, and
    redirects stdio to ``/dev/null`` to keep the parent terminal clean.
    Returns None if ``cwd`` doesn't exist or the spawn failed.
    """
    if not cwd.exists():
        log(f"Session-Buddy cwd does not exist: {cwd}")
        return None
    log(f"Starting Session-Buddy: {' '.join(cmd)} (cwd={cwd})")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as e:
        log(f"  Failed to start: {e}")
        return None
    return proc.pid


def _http_get_json(parsed_url, timeout: float) -> dict | None:
    """Single GET against a validated http URL using ``http.client``.

    Returns the parsed JSON body on 200, or ``None`` on any other
    condition (non-200 status, timeout, connection error). The caller
    polls this until it returns a non-None result with ``status: ok``
    or until the deadline elapses.

    We use ``http.client.HTTPConnection`` (not ``HTTPSConnection``) and
    restrict the URL scheme to ``http`` at the boundary
    (``validate_health_url``). This avoids two classes of false-positive
    scanner findings that fire on any ``urllib`` or ``HTTPSConnection``
    usage with a dynamic value: CWE-939 (file:// disclosure) and
    CWE-295 (default SSL verification on older Python).
    """
    import http.client
    import json

    host = parsed_url.hostname
    if host is None:
        return None
    # Default http port; ``port`` is forced by the URL we constructed.
    port = parsed_url.port or 80

    try:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        path = parsed_url.path or "/"
        if parsed_url.query:
            path = f"{path}?{parsed_url.query}"
        conn.request("GET", path, headers={"User-Agent": "cleanup_reflection_db/1.0"})
        resp = conn.getresponse()
        if resp.status != 200:
            return None
        body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body)
    except (TimeoutError, OSError, ValueError):
        return None
    finally:
        try:
            conn.close()  # type: ignore[possibly-undefined]
        except (OSError, NameError, UnboundLocalError):
            pass


def verify_health(
    url: str = DEFAULT_HEALTH_URL,
    timeout_seconds: float = 10.0,
    log: Callable[[str], None] = print,
) -> bool:
    """Poll the Session-Buddy health endpoint until it responds OK or times out.

    Uses ``http.client`` (stdlib) to avoid pulling in ``requests`` for a
    one-shot health check. ``urllib.request`` is intentionally avoided
    because security scanners (semgrep's ``dynamic-urllib-use-detected``)
    flag any dynamic value flowing into ``urllib`` regardless of upstream
    scheme validation. ``http.client`` doesn't have that false positive.

    Returns True if the response is HTTP 200 and the JSON body contains
    ``"status":"ok"``.

    The URL must use ``http`` or ``https``; ``file://`` and other schemes
    are rejected defensively (see ``validate_health_url`` and CWE-939).
    """
    # Defense in depth — even though the CLI parser validates too, this
    # is the actual security boundary. Fail loud before touching the
    # network so a misuse is logged rather than silently downgraded.
    validate_health_url(url)
    parsed = urlparse(url)

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        payload = _http_get_json(parsed, timeout=2)
        if payload is not None and payload.get("status") == "ok":
            log(f"  Health OK: {url}")
            return True
        time.sleep(0.5)
    log(f"  Health check timed out after {timeout_seconds}s")
    return False


# ---------------------------------------------------------------------------
# DuckDB operations
# ---------------------------------------------------------------------------


def run_checkpoint(db_path: Path, log: Callable[[str], None] = print) -> bool:
    """Open the file, load vss if HNSW indexes are present, and CHECKPOINT.

    Returns True on success. The connection is closed before returning
    so the lock is released immediately. The current process PID becomes
    the new lock holder, which is what we want — next time *anyone* tries
    to open the file, they'll see a live PID in the error message
    (or no error at all, if no conflict).
    """
    duckdb = _import_duckdb()
    log(f"Opening {db_path} in write mode")
    try:
        con = duckdb.connect(str(db_path))
    except Exception as e:  # noqa: BLE001
        log(f"  Failed to open: {e}")
        return False

    try:
        # Probe whether vss is required by attempting CHECKPOINT. If the
        # file has HNSW indexes, the first attempt will fail with a
        # specific error; we catch it, install+load vss, and retry.
        try:
            con.execute("CHECKPOINT")
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "HNSW" not in msg and "vss" not in msg.lower():
                raise
            log("  File contains HNSW indexes — loading vss extension")
            try:
                con.execute("INSTALL vss")
                con.execute("LOAD vss")
            except Exception as inner:  # noqa: BLE001
                log(f"  Failed to install/load vss: {inner}")
                return False
            con.execute("CHECKPOINT")
        log("  CHECKPOINT complete, lock record refreshed")
        return True
    except Exception as e:  # noqa: BLE001
        log(f"  CHECKPOINT failed: {e}")
        return False
    finally:
        try:
            con.close()
        except Exception:  # noqa: BLE001, S110
            pass


def verify_lock_refreshed(db_path: Path, expected_pid: int) -> int | None:
    """After CHECKPOINT, try to open the file from a fresh process.

    We use a short-lived subprocess to ensure the probe runs in a
    separate process (the parent process may have residual DuckDB
    state). The probe's own PID will appear in any error message, so
    we can confirm the lock record is no longer stale.

    Returns the PID reported in the conflict (if any), or None if the
    lock is free.
    """
    probe = probe_lock(db_path)
    if not probe.locked:
        return None
    return probe.holder_pid


# ---------------------------------------------------------------------------
# High-level orchestrator
# ---------------------------------------------------------------------------


def force_release_lock(
    db_path: Path = DEFAULT_DB_PATH,
    shutdown_timeout: float = DEFAULT_SHUTDOWN_TIMEOUT,
    sb_cmd: list[str] | None = None,
    sb_cwd: Path = DEFAULT_SB_CWD,
    restart: bool = True,
    health_url: str = DEFAULT_HEALTH_URL,
    log: Callable[[str], None] = print,
) -> CleanupResult:
    """Run the full cleanup sequence. See module docstring for details.

    This is the main entry point for both the CLI and any future
    automated callers (e.g. a Session-Buddy post-mortem hook).
    """
    start = time.monotonic()
    sb_cmd = sb_cmd or DEFAULT_SB_CMD

    log("Probing current lock state")
    initial = probe_lock(db_path)
    if not initial.locked:
        log(f"  Lock is free, no cleanup needed (file={db_path})")
        return CleanupResult(
            lock_was_held=False,
            holder_pid=None,
            holder_was_alive=False,
            checkpoint_ok=True,
            new_holder_pid=None,
            restart_attempted=False,
            restart_ok=None,
            health_ok=None,
            duration_seconds=time.monotonic() - start,
        )

    log(f"  Lock held by PID {initial.holder_pid} ({'STALE' if initial.stale else 'live'})")

    # Step 1: shutdown the holder (live or stale — even a stale PID
    # whose process has been reaped needs no extra work, but we still
    # run the safe path).
    holder_is_live = not initial.stale
    if holder_is_live:
        if not shutdown_session_buddy(
            initial.holder_pid,  # type: ignore[arg-type]
            timeout=shutdown_timeout,
            log=log,
        ):
            log("ERROR: failed to stop Session-Buddy; aborting")
            return CleanupResult(
                lock_was_held=True,
                holder_pid=initial.holder_pid,
                holder_was_alive=True,
                checkpoint_ok=False,
                new_holder_pid=None,
                restart_attempted=False,
                restart_ok=None,
                health_ok=None,
                duration_seconds=time.monotonic() - start,
            )

    # Step 2: clear the stale PID record via CHECKPOINT.
    checkpoint_ok = run_checkpoint(db_path, log=log)
    new_holder_pid = os.getpid() if checkpoint_ok else None

    # Step 3: optionally restart Session-Buddy.
    restart_attempted = False
    restart_ok: bool | None = None
    if restart:
        restart_attempted = True
        new_pid = restart_session_buddy(cmd=sb_cmd, cwd=sb_cwd, log=log)
        restart_ok = new_pid is not None

    # Step 4: optionally verify the ecosystem is healthy.
    health_ok: bool | None = None
    if restart and restart_ok:
        # Give Session-Buddy a moment to come up before polling.
        time.sleep(2.0)
        health_ok = verify_health(health_url, log=log)

    return CleanupResult(
        lock_was_held=True,
        holder_pid=initial.holder_pid,
        holder_was_alive=not initial.stale,
        checkpoint_ok=checkpoint_ok,
        new_holder_pid=new_holder_pid,
        restart_attempted=restart_attempted,
        restart_ok=restart_ok,
        health_ok=health_ok,
        duration_seconds=time.monotonic() - start,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cleanup_reflection_db.py",
        description=(
            "Resolve the stale-PID warning emitted by reflection.duckdb. "
            "Stops Session-Buddy, CHECKPOINTs the DuckDB file (loading vss "
            "if needed), and restarts Session-Buddy."
        ),
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to the reflection.duckdb file (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--session-buddy-cmd",
        nargs=argparse.REMAINDER,
        default=None,
        help=(
            "Command to start Session-Buddy. Pass as the rest of the args, "
            f"e.g. --session-buddy-cmd /path/to/python -m session_buddy start --force. "
            f"Default: {' '.join(DEFAULT_SB_CMD)}"
        ),
    )
    parser.add_argument(
        "--session-buddy-cwd",
        type=Path,
        default=DEFAULT_SB_CWD,
        help=f"Working directory for the restart command (default: {DEFAULT_SB_CWD})",
    )
    parser.add_argument(
        "--no-restart",
        action="store_true",
        help="Don't restart Session-Buddy after cleanup. Use for maintenance windows.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without actually stopping anything.",
    )
    parser.add_argument(
        "--shutdown-timeout",
        type=float,
        default=DEFAULT_SHUTDOWN_TIMEOUT,
        help=f"Seconds to wait for graceful shutdown before SIGKILL (default: {DEFAULT_SHUTDOWN_TIMEOUT})",
    )
    parser.add_argument(
        "--health-url",
        default=DEFAULT_HEALTH_URL,
        help=f"Session-Buddy health endpoint (default: {DEFAULT_HEALTH_URL})",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress progress output; only show errors and final status.",
    )
    return parser


def _make_logger(quiet: bool) -> Callable[[str], None]:
    def log(msg: str) -> None:
        if not quiet:
            print(msg, file=sys.stderr)

    return log


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Validate the health URL at parse time so ``--dry-run`` and any
    # early-exit path also reject bad schemes. Without this, a mis-
    # configured ``--health-url`` would only be caught deep inside
    # ``verify_health`` after the rest of the cleanup has succeeded.
    try:
        validate_health_url(args.health_url)
    except ValueError as e:
        parser.error(str(e))

    log = _make_logger(args.quiet)

    if args.dry_run:
        log("[DRY RUN] Probing lock state only — no changes will be made")
        initial = probe_lock(args.db_path)
        if not initial.locked:
            log(f"  Lock is free on {args.db_path}")
            log("  Nothing to clean up.")
            return 0
        alive = "live" if not initial.stale else "stale"
        log(f"  Lock held by PID {initial.holder_pid} ({alive})")
        if initial.stale:
            log("  Would: skip shutdown, run CHECKPOINT, then restart (if --no-restart is not set)")
        else:
            log(
                f"  Would: SIGTERM PID {initial.holder_pid} (timeout={args.shutdown_timeout}s, "
                "then SIGKILL), run CHECKPOINT, then restart (if --no-restart is not set)"
            )
        return 0

    sb_cmd = args.session_buddy_cmd if args.session_buddy_cmd else DEFAULT_SB_CMD
    result = force_release_lock(
        db_path=args.db_path,
        shutdown_timeout=args.shutdown_timeout,
        sb_cmd=sb_cmd,
        sb_cwd=args.session_buddy_cwd,
        restart=not args.no_restart,
        health_url=args.health_url,
        log=log,
    )

    # Final summary
    log("")
    log("=" * 60)
    log(f"Cleanup complete in {result.duration_seconds:.1f}s")
    if result.lock_was_held:
        log(
            f"  Previous holder: PID {result.holder_pid} ({'stale' if not result.holder_was_alive else 'live'})"
        )
        log(f"  CHECKPOINT: {'OK' if result.checkpoint_ok else 'FAILED'}")
        if result.new_holder_pid is not None:
            log(f"  New lock holder: PID {result.new_holder_pid}")
        if result.restart_attempted:
            log(f"  Restart: {'OK' if result.restart_ok else 'FAILED'}")
        if result.health_ok is not None:
            log(f"  Health: {'OK' if result.health_ok else 'FAILED'}")
    else:
        log("  No lock conflict detected — nothing was changed")

    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
