"""Wire-up invariants for first-class CLI sub-apps.

A test that fails if a refactor silently removes the demo or launchd
wire-up from ``mahavishnu/_main_cli.py``. Pairs with the comment markers
(``=== DEMO SUB-COMMANDS ===``, ``=== LAUNCHD SUB-COMMANDS ===``) in
``_main_cli.py`` — if any of the three markers disappears (CLI module
import, ``_main_cli.py`` comment block, this test), the wire-up is
silently lost and the demo or launchd command is unreachable from the
operator shell.

Plan: ``/Users/les/.claude/plans/dazzling-waddling-ullman.md``
"""

from __future__ import annotations


def test_demo_subcommands_wired_in_main_cli() -> None:
    """``mahavishnu demo <engine|adapter>`` must register on the root CLI.

    Fails loudly if a refactor deletes the ``from .cli.demo_cli import
    demo_app; app.add_typer(demo_app, name=\"demo\")`` wire-up — exactly the
    silent-revert pattern that nuked the original ``demo`` group at commit
    ``98237009``. Without this test, the breakage is invisible to CI.
    """
    from mahavishnu._main_cli import app

    registered = {grp.name for grp in app.registered_groups if grp.name}
    assert "demo" in registered, (
        "demo sub-app silently missing from _main_cli.app.registered_groups. "
        "Re-add `from .cli.demo_cli import demo_app; app.add_typer(demo_app, name=\"demo\")` "
        "in the `=== DEMO SUB-COMMANDS ===` block."
    )


def test_launchd_subcommands_wired_in_main_cli() -> None:
    """``mahavishnu launchd prefect`` must register on the root CLI.

    Was marked ``xfail`` until Phase C (``mahavishnu/cli/launchd_cli.py``)
    shipped — now passes naturally. Sibling to
    ``test_demo_subcommands_wired_in_main_cli`` — same anti-revert
    pattern, three markers.
    """
    from mahavishnu._main_cli import app

    registered = {grp.name for grp in app.registered_groups if grp.name}
    assert "launchd" in registered, (
        "launchd sub-app silently missing from _main_cli.app.registered_groups. "
        "Re-add `from .cli.launchd_cli import launchd_app; app.add_typer(launchd_app, name=\"launchd\")` "
        "in the `=== LAUNCHD SUB-COMMANDS ===` block."
    )
