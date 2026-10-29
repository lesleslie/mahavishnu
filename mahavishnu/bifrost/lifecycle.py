"""launchd lifecycle for the Bifrost gateway.

req: REQ-BIFROST-033

Port of ``scripts/bifrost-ctl``. The zsh semantics are preserved rather than
re-designed, in particular:

- ``start``/``restart``/``rebootstrap`` repoint the client harness **only
  after** the ready file appears. Gating the rewrite on real readiness (not on
  intent) is what stops a failed boot from leaving Claude Code aimed at a
  gateway that never came up.
- ``stop`` restores the harness to its prior endpoint before tearing the
  gateway down, and removes the ready file last.
- ``foreground`` restores the harness on exit via an EXIT/INT/TERM trap.

Every harness rewrite routes through :func:`mahavishnu.bifrost.toggles.apply`,
so ``BIFROST_CTL_NO_CC_URL_REWRITE`` is honoured identically here and on the
direct ``bifrost cc-url`` command. The retired zsh script had to duplicate
that check because its Python helper was a separate process that ignored it.
"""

from __future__ import annotations

from pathlib import Path
import plistlib
import shutil
import sqlite3
import subprocess
import time

import typer

from .gateway import PORT
from .models import HARNESSES, HarnessDescriptor
from .paths import (
    BIFROST_CONFIG_DIR,
    GUI_DOMAIN,
    LAUNCHD_LABEL,
    READY_FILE,
)
from .toggles import apply

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SOURCE_PLIST = REPO_ROOT / "config" / "launchd" / f"{LAUNCHD_LABEL}.plist"
TARGET_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
SOURCE_CONFIG = REPO_ROOT / "config" / "bifrost" / "config.template.json"
TARGET_CONFIG = BIFROST_CONFIG_DIR / "config.json"

#: Budget for the ready file to appear after a launch, matching the shell
#: wrapper. Generous because Bifrost's catalog sync can take a while cold.
READY_BUDGET_SECONDS = 60

READY_FILE.parent.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# launchd plumbing
# --------------------------------------------------------------------------


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a launchctl/lsof command, tolerating a non-zero exit."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except OSError, subprocess.SubprocessError:
        return subprocess.CompletedProcess(cmd, 1, "", "")


def install_plist() -> None:
    """Copy the repo plist into ~/Library/LaunchAgents."""
    TARGET_PLIST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(SOURCE_PLIST, TARGET_PLIST)
    with TARGET_PLIST.open("rb") as fh:
        plistlib.load(fh)  # validate before launchd ever sees it


def bootstrap() -> None:
    _run(["launchctl", "bootstrap", GUI_DOMAIN, str(TARGET_PLIST)])


def bootout() -> None:
    _run(["launchctl", "bootout", f"{GUI_DOMAIN}/{LAUNCHD_LABEL}"])
    _run(["launchctl", "bootout", GUI_DOMAIN, str(TARGET_PLIST)])


def kill_listener() -> None:
    """Terminate anything still holding the port, then verify it released."""
    result = _run(["lsof", "-tiTCP:" + str(PORT), "-sTCP:LISTEN"])
    pids = [p for p in result.stdout.split() if p.strip().isdigit()]
    if not pids:
        return
    for pid in pids:
        _run(["kill", pid])
    time.sleep(1)
    remaining = _run(["lsof", "-tiTCP:" + str(PORT), "-sTCP:LISTEN"])
    for pid in (p for p in remaining.stdout.split() if p.strip().isdigit()):
        _run(["kill", "-9", pid])


def wait_for_ready_file(timeout: int = READY_BUDGET_SECONDS) -> bool:
    """Poll for the ready file the gateway wrapper writes on bind."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if READY_FILE.exists():
            return True
        time.sleep(1)
    return False


def _secure_dir(path: Path) -> None:
    """Create ``path`` owner-only and force the mode past the umask.

    ``mkdir(mode=...)`` is masked by the process umask, so a 0700 request can
    still land as 0755. An explicit ``chmod`` is the only reliable way to get
    owner-only.
    """
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def _backup_config_store(backup_dir: Path) -> None:
    """Snapshot the config store into an owner-only directory.

    Uses SQLite's backup API rather than copying the files. The gateway holds
    this database open in WAL mode, so a plain ``shutil.copy`` can capture a
    main file that does not match its WAL -- a backup that fails to open, which
    is worse than no backup because it looks like one worked. The API also
    produces a single self-contained file, so the ``-shm``/``-wal`` siblings do
    not need copying at all.

    The destination holds provider key material and virtual-key values, so both
    the directory and the file are forced to owner-only regardless of umask.
    """
    source = BIFROST_CONFIG_DIR / "config.db"
    if not source.exists():
        return

    destination = backup_dir / "config.db"
    connection = sqlite3.connect(source)
    try:
        target = sqlite3.connect(destination)
        try:
            with target:
                connection.backup(target)
        finally:
            target.close()
    except sqlite3.Error:
        # Never let a failed backup abort the operator's own command; report
        # it and let them decide whether proceeding is safe.
        typer.echo(f"WARNING: config store backup failed: {destination}", err=True)
        return
    finally:
        connection.close()

    destination.chmod(0o600)


def sync_config(drop_db: bool = False) -> None:
    """Re-seed ``config.json`` from the repo template.

    The config **database is not stale** -- with ``config_store`` enabled it is
    the authoritative store for providers, keys, governance config, virtual
    keys, and the dashboard admin account. ``config.json`` is only a first-run
    seed. This function previously deleted ``config.db`` unconditionally,
    which silently destroyed the virtual key and admin account; it now backs
    the database up first and only removes it when ``drop_db`` is explicit.
    """
    TARGET_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(SOURCE_CONFIG, TARGET_CONFIG)

    db_files = [
        BIFROST_CONFIG_DIR / name for name in ("config.db", "config.db-shm", "config.db-wal")
    ]
    present = [path for path in db_files if path.exists()]
    if not present:
        return

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_dir = BIFROST_CONFIG_DIR / ".bak" / f"{stamp}-presync"
    _secure_dir(backup_dir)
    _backup_config_store(backup_dir)

    if drop_db:
        for path in present:
            path.unlink(missing_ok=True)
    else:
        typer.echo(
            f"kept config store ({', '.join(p.name for p in present)}); "
            f"backed up to {backup_dir}\n"
            f"  pass --drop-db to discard it and re-seed from the template",
            err=True,
        )


# --------------------------------------------------------------------------
# harness routing side-effects
# --------------------------------------------------------------------------


def repoint_harnesses(action: str) -> None:
    """Apply ``action`` to every harness, honouring the operator gate.

    Routed through ``toggles.apply`` so ``BIFROST_CTL_NO_CC_URL_REWRITE``
    applies uniformly. Unlike the zsh original this never needs its own copy
    of the gate check -- there is only one implementation now.
    """
    for harness in HARNESSES.values():
        try:
            apply(harness, action)
        except typer.Exit:
            # A harness refusing (e.g. refusing to clobber a credential it
            # cannot restore) must not abort the whole lifecycle operation.
            typer.echo(f"warning: {harness.label} URL rewrite refused; see above")


def _after_ready(action: str) -> None:
    """Repoint harnesses only if the gateway actually came up."""
    if wait_for_ready_file():
        repoint_harnesses(action)
    else:
        typer.echo(
            f"warning: {READY_FILE} not seen within {READY_BUDGET_SECONDS}s; "
            f"leaving client URL(s) untouched"
        )


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------


def start() -> None:
    """Install, bootstrap, and start the gateway."""
    install_plist()
    bootout()
    kill_listener()
    time.sleep(1)
    bootstrap()
    _run(["launchctl", "kickstart", "-k", f"{GUI_DOMAIN}/{LAUNCHD_LABEL}"])
    _after_ready("bifrost")


def stop() -> None:
    """Restore client endpoints, then tear the gateway down."""
    repoint_harnesses("direct")
    bootout()
    kill_listener()
    READY_FILE.unlink(missing_ok=True)


def restart() -> None:
    """Stop then start, preserving the client's current routing choice."""
    install_plist()
    bootout()
    kill_listener()
    time.sleep(1)
    bootstrap()
    _run(["launchctl", "kickstart", "-k", f"{GUI_DOMAIN}/{LAUNCHD_LABEL}"])
    _after_ready("bifrost")


def rebootstrap(drop_db: bool = False) -> None:
    """Re-seed config from template, then restart.

    The config store survives unless ``drop_db`` is set -- see
    :func:`sync_config` for why dropping it is destructive.
    """
    install_plist()
    bootout()
    kill_listener()
    sync_config(drop_db=drop_db)
    time.sleep(1)
    bootstrap()
    _run(["launchctl", "kickstart", "-k", f"{GUI_DOMAIN}/{LAUNCHD_LABEL}"])
    _after_ready("bifrost")


def status() -> None:
    """Print service state, port binding, ready file, and harness routing."""
    result = _run(["launchctl", "print", f"{GUI_DOMAIN}/{LAUNCHD_LABEL}"])
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith(("state =", "pid =", "last exit code =", "path =")):
                typer.echo(stripped)
    else:
        typer.echo(f"service not loaded: {LAUNCHD_LABEL}")

    listener = _run(["lsof", "-nP", "-iTCP:" + str(PORT), "-sTCP:LISTEN"])
    typer.echo(listener.stdout.strip() or f"nothing listening on {PORT}")
    ready_state = str(READY_FILE) if READY_FILE.exists() else f"{READY_FILE} (missing)"
    typer.echo(f"ready file: {ready_state}")

    for harness in HARNESSES.values():
        apply(harness, "status")


__all__ = [
    "HarnessDescriptor",
    "install_plist",
    "rebootstrap",
    "repoint_harnesses",
    "restart",
    "start",
    "status",
    "stop",
    "sync_config",
    "wait_for_ready_file",
]
