"""``mahavishnu launchd <service>`` — opt-in launchd management for substrate servers.

Adds Prefect (and other substrate servers, per-substrate PRs) to the
user-level launchd (``~/Library/LaunchAgents/``) so they're always-on
when the operator wants. **Opt-in only** — never installed by default;
the memory note ``feedback-macos-reboot-launchd-keepalive-cascade.md``
documents why (cascading restart storms when boot dependencies are
unmet).

**Wire-up contract (anti-revert)** — three markers all must move together:

1. This docstring references ``mahavishnu/_main_cli.py`` ``=== LAUNCHD
   SUB-COMMANDS ===`` block.
2. ``mahavishnu/_main_cli.py`` carries the matching ``=== LAUNCHD
   SUB-COMMANDS ===`` comment + ``from .cli.launchd_cli import
   launchd_app; app.add_typer(launchd_app, name="launchd")`` wiring.
3. ``tests/unit/cli/test_cli_wireup_invariants.py::test_launchd_subcommands_wired_in_main_cli``
   asserts the ``launchd`` Typer group is registered in
   ``mahavishnu._main_cli.app.registered_groups``.

**Pattern A convention** (matches executions / jot / board / acp /
demo): module-level Typer ``launchd_app``, nested sub-app per service,
wired in ``_main_cli.py`` via ``app.add_typer(launchd_app, name=\"launchd\")``.

**Why the plist template is NOT embedded as a string constant** — to
avoid drift, the plist lives at
``config/launchd/com.mcp.mahavishnu.prefect.plist`` and the install
command interpolates the user's home directory before writing to
``~/Library/LaunchAgents/com.mcp.mahavishnu.prefect.plist``. Round-trips
through ``diff`` show what changed.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import httpx2 as httpx
import typer

# Module-level Typer apps. ``_main_cli.py`` registers the outer one as
# ``mahavishnu launchd <sub>``; the inner ``launchd_prefect_app`` is added
# under ``mahavishnu launchd prefect``.
launchd_app = typer.Typer(
    name="launchd",
    help=(
        "Opt-in launchd management for substrate servers (Prefect, etc.). "
        "Subcommands install/uninstall/status the per-service plist in "
        "~/Library/LaunchAgents/. Never installed by default — see "
        "feedback-macos-reboot-launchd-keepalive-cascade.md."
    ),
)
launchd_prefect_app = typer.Typer(
    name="prefect",
    help="Prefect server under launchd (com.mcp.mahavishnu.prefect).",
)
launchd_app.add_typer(launchd_prefect_app)


# ============================================================================
# Constants — paths and shell argv
# ============================================================================


# In-repo plist template. Interpolated with the user's $HOME at install time.
PLIST_TEMPLATE_PATH = Path(
    "/Users/les/Projects/mahavishnu/config/launchd/com.mcp.mahavishnu.prefect.plist"
)
# Where the live plist lands.
LIVE_PLIST_DEST = Path("~/Library/LaunchAgents/com.mcp.mahavishnu.prefect.plist").expanduser()
# Path of the wrapper script that the plist invokes.
WRAPPER_PATH = Path("/Users/les/.local/state/mcp/scripts/launch_with_healthcheck.sh")
# Health URL for the wrapper to poll. Hit after ``prefect server start``.
PREFECT_HEALTH_URL = "http://127.0.0.1:4200/api/health"
# Plist label — matches the ``com.mcp.*`` convention (per
# architecture review; sibling to com.mcp.mahavishnu, com.mcp.crackerjack, etc.).
PLIST_LABEL = "com.mcp.mahavishnu.prefect"
# Where the spec'd ``MAHAVISHNU_AUTOSTART_PREFECT`` lives (kill switch).
SECRETS_ENV_FILE = Path("~/.config/secrets.env").expanduser()


def _plist_template_text() -> str:
    """Read the in-repo plist template verbatim — keeps the on-disk XML
    the single source of truth so updates don't drift."""
    return PLIST_TEMPLATE_PATH.read_text(encoding="utf-8")


def _interpolate_user_paths(text: str) -> str:
    """Replace any ``%USER_HOME%`` tokens (and a couple bare ``~`` paths)
    with the actual user home. The plist template uses an explicit
    token to keep literal ``~`` out of the on-disk XML (which launchd
    parses strictly)."""
    home = str(Path.home())
    return text.replace("%USER_HOME%", home)


def _launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    """Run ``launchctl <args>`` with capture. Stdout/stderr returned for
    the caller to print; check ``.returncode`` for success."""
    return subprocess.run(
        ["launchctl", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _check_wrapper_exists() -> list[str]:
    """Return failures list (empty = pass)."""
    failures: list[str] = []
    if not WRAPPER_PATH.exists():
        failures.append(
            f"missing wrapper script: {WRAPPER_PATH} "
            "(install via `mahavishnu mcp install --healthcheck` or "
            "bootstrap manually from this repo)"
        )
    return failures


def _check_settings_uuid(uid_str: str) -> int | None:
    """Parse ``id -u``-style uid, or None on error."""
    try:
        return int(uid_str)
    except (TypeError, ValueError):
        return None


# ============================================================================
# install
# ============================================================================


@launchd_prefect_app.command("install")
def install_prefect() -> None:
    """Write the Prefect plist to ~/Library/LaunchAgents and load it.

    Idempotent: re-running updates the plist in place (boots a fresh
    Prefect). Loads via ``launchctl load -w`` so the plist survives
    session logout — operationally the trade-off the memory-note
    cascade-risk warns against. Preflight: confirm wrapper script
    exists.
    """
    failures = _check_wrapper_exists()
    if failures:
        for failure in failures:
            typer.echo(f"  - {failure}", err=True)
        raise typer.Exit(code=1)
    if not PLIST_TEMPLATE_PATH.exists():
        typer.echo(f"plist template missing: {PLIST_TEMPLATE_PATH}", err=True)
        raise typer.Exit(code=2)

    plist_text = _interpolate_user_paths(_plist_template_text())
    LIVE_PLIST_DEST.parent.mkdir(parents=True, exist_ok=True)
    LIVE_PLIST_DEST.write_text(plist_text, encoding="utf-8")

    # bootout any prior load (idempotent — ignore non-zero rc).
    _launchctl("bootout", f"gui/{os.getuid()}/{PLIST_LABEL}")
    load = _launchctl("load", "-w", str(LIVE_PLIST_DEST))
    if load.returncode != 0:
        typer.echo(f"launchctl load failed: {load.stderr.strip() or load.stdout.strip()}", err=True)
        raise typer.Exit(code=load.returncode or 1)

    typer.echo(f"Wrote: {LIVE_PLIST_DEST}")
    typer.echo(f"Loaded: {PLIST_LABEL}")
    typer.echo("View live status: mahavishnu launchd prefect status")
    typer.echo(f"Health URL poll: {PREFECT_HEALTH_URL}")


# ============================================================================
# uninstall
# ============================================================================


@launchd_prefect_app.command("uninstall")
def uninstall_prefect() -> None:
    """Unload the Prefect plist and remove the file."""
    uid = _check_settings_uuid(str(os.getuid()))
    if uid is None:
        typer.echo("could not determine UID; aborting", err=True)
        raise typer.Exit(code=2)
    bootout = _launchctl("bootout", f"gui/{uid}/{PLIST_LABEL}")
    if LIVE_PLIST_DEST.exists():
        LIVE_PLIST_DEST.unlink()
    typer.echo(f"Unloaded: {PLIST_LABEL} (rc={bootout.returncode})")
    typer.echo(f"Removed: {LIVE_PLIST_DEST}")


# ============================================================================
# status
# ============================================================================


@launchd_prefect_app.command("status")
def status_prefect() -> None:
    """Report launchd load state + Prefect health."""
    listing = _launchctl("list", PLIST_LABEL)
    plist_exists = LIVE_PLIST_DEST.exists()

    typer.echo(f"Label         : {PLIST_LABEL}")
    typer.echo(f"Plist present : {plist_exists} ({LIVE_PLIST_DEST})")
    typer.echo(f"launchctl list: exit={listing.returncode}")
    if listing.stdout.strip():
        typer.echo(f"  stdout: {listing.stdout.strip()}")
    if listing.stderr.strip():
        typer.echo(f"  stderr: {listing.stderr.strip()}")

    try:
        resp = httpx.get(PREFECT_HEALTH_URL, timeout=5.0)
        typer.echo(f"Health probe  : HTTP {resp.status_code} — body={resp.text.strip()!r}")
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"Health probe  : failed — {exc}", err=True)


__all__ = ["launchd_app", "launchd_prefect_app"]
