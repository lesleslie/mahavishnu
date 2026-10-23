"""``mahavishnu bifrost ...`` — Bifrost LLM gateway control surface.

req: REQ-BIFROST-024

One wired CLI replacing the seven standalone ``scripts/bifrost*`` tools.
Logic lives in :mod:`mahavishnu.bifrost`; this module is the Typer shell,
matching the ``mahavishnu/cli/*_cli.py`` convention.

**Wire-up contract (anti-revert)** — three markers all must move together:

1. This docstring references ``mahavishnu/_main_cli.py``
   ``=== BIFROST SUB-COMMANDS ===`` block.
2. ``mahavishnu/_main_cli.py`` carries the matching
   ``=== BIFROST SUB-COMMANDS ===`` block.
3. ``tests/unit/cli/test_cli_wireup_invariants.py`` asserts the registration.

Phase 1 covers the harness URL toggles and the bind/credential report.
Lifecycle, smoke, and verify commands land in later phases of
``docs/plans/2026-10-21-bifrost-cli-consolidation.md``.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path  # noqa: TC003 -- Typer resolves annotations at runtime

import typer

from ..bifrost import gateway, lifecycle, verify
from ..bifrost.lifecycle import TARGET_PLIST
from ..bifrost.models import VIRTUAL_KEY_ENV, resolve_harness
from ..bifrost.paths import DEFAULT_BIFROST_HOST, DEFAULT_BIFROST_PORT
from ..bifrost.policy import build_report
from ..bifrost.toggles import apply, credential_configured

bifrost_app = typer.Typer(
    help="Bifrost LLM gateway: client routing, credentials, and bind posture.",
    no_args_is_help=True,
)


class UrlAction(StrEnum):
    """Actions available on a harness URL toggle."""

    bifrost = "bifrost"
    direct = "direct"
    status = "status"


def _run_toggle(
    harness_key: str,
    action: UrlAction,
    host: str,
    port: int,
    key_file: Path | None,
    dry_run: bool,
    force: bool,
) -> None:
    harness = resolve_harness(harness_key)
    code = apply(
        harness,
        action.value,
        host=host,
        port=port,
        key_file=key_file,
        dry_run=dry_run,
        force=force,
    )
    if code:
        raise typer.Exit(code)


@bifrost_app.command("cc-url")
def cc_url(
    action: UrlAction = typer.Argument(UrlAction.status, help="What to do."),
    host: str = typer.Option(DEFAULT_BIFROST_HOST, "--host", help="Bifrost host."),
    port: int = typer.Option(DEFAULT_BIFROST_PORT, "--port", help="Bifrost port."),
    key_file: Path | None = typer.Option(
        None, "--virtual-key-file", help=f"File holding the key. Or set ${VIRTUAL_KEY_ENV}."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report without writing."),
    force: bool = typer.Option(
        False, "--force", help="Overwrite a pre-existing virtual key (it will not be restored)."
    ),
) -> None:
    """Point Claude Code at Bifrost, or restore its prior endpoint."""
    _run_toggle("cc", action, host, port, key_file, dry_run, force)


@bifrost_app.command("qwen-url")
def qwen_url(
    action: UrlAction = typer.Argument(UrlAction.status, help="What to do."),
    host: str = typer.Option(DEFAULT_BIFROST_HOST, "--host", help="Bifrost host."),
    port: int = typer.Option(DEFAULT_BIFROST_PORT, "--port", help="Bifrost port."),
    key_file: Path | None = typer.Option(
        None, "--virtual-key-file", help=f"File holding the key. Or set ${VIRTUAL_KEY_ENV}."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report without writing."),
    force: bool = typer.Option(
        False, "--force", help="Overwrite a pre-existing virtual key (it will not be restored)."
    ),
) -> None:
    """Point Qwen Code at Bifrost, or restore its prior endpoint."""
    _run_toggle("qwen", action, host, port, key_file, dry_run, force)


@bifrost_app.command("policy")
def policy(
    port: int = typer.Option(DEFAULT_BIFROST_PORT, "--port", help="Bifrost port."),
) -> None:
    """Report bind addresses and per-harness credential state."""
    configured = [k for k in ("cc", "qwen") if credential_configured(resolve_harness(k))]
    report = build_report(port=port, credential_configured=bool(configured))
    typer.echo(f"binds: {', '.join(report.binds) or '<none>'}")
    typer.echo(f"reachable off-host: {'yes' if report.reachable_off_host else 'no'}")
    typer.echo(f"virtual key configured for: {', '.join(configured) or '<none>'}")
    typer.echo(f"risk: {report.risk}")


@bifrost_app.command("credential-source")
def credential_source() -> None:
    """Print where the virtual key is read from. Never prints the key itself."""
    typer.echo(f"virtual key is read from ${VIRTUAL_KEY_ENV}, or --virtual-key-file")


# --- lifecycle (req: REQ-BIFROST-033) ---


@bifrost_app.command("start")
def bifrost_start() -> None:
    """Start the gateway via launchd; repoint harnesses once it is ready."""
    lifecycle.start()


@bifrost_app.command("stop")
def bifrost_stop() -> None:
    """Restore harness endpoints to their prior value, then stop the gateway."""
    lifecycle.stop()


@bifrost_app.command("restart")
def bifrost_restart() -> None:
    """Restart the gateway, keeping client routing intact."""
    lifecycle.restart()


@bifrost_app.command("rebootstrap")
def bifrost_rebootstrap(
    drop_db: bool = typer.Option(
        False,
        "--drop-db",
        help=(
            "Also delete config.db. That destroys virtual keys, the dashboard "
            "admin account, and all governance config; it is backed up first."
        ),
    ),
) -> None:
    """Re-seed the gateway config from the repo template, then restart.

    The config *store* is preserved unless ``--drop-db`` is passed.
    """
    lifecycle.rebootstrap(drop_db=drop_db)


@bifrost_app.command("install")
def bifrost_install() -> None:
    """Install the launchd plist into ~/Library/LaunchAgents."""
    lifecycle.install_plist()
    typer.echo(f"installed {TARGET_PLIST}")


@bifrost_app.command("status")
def bifrost_status() -> None:
    """Report service state, port binding, ready file, and harness routing."""
    lifecycle.status()


@bifrost_app.command("foreground", hidden=True)
def bifrost_foreground() -> None:
    """Run the gateway in this shell (used by the LaunchAgent plist)."""
    gateway.serve()


@bifrost_app.command("verify-gate")
def bifrost_verify_gate(
    timeout: int = typer.Option(
        30,
        "--timeout",
        help="Seconds to wait for a Qwen-route row in the Bifrost log store.",
    ),
) -> None:
    """Operator gate: confirm a Qwen worker actually routes through Bifrost."""
    code = verify.run_gate(timeout)
    if code:
        raise typer.Exit(code)
