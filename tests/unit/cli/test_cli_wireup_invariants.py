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


def test_demo_agno_is_live_implementation() -> None:
    """``mahavishnu demo agno`` must be a live implementation.

    2026-10-15 wire-up fix: the agno demo was promoted from a stub to
    a live implementation (drives ``AgnoAdapter.execute`` end-to-end).
    This invariant catches a silent revert back to the stub.

    The stub registration path emits ``--why-stub`` and exits with
    code 0; the live path exposes ``--repos``, ``--task-type``,
    ``--prompt``, ``--keep``, ``--timeout``. Asserting ``--repos`` is
    present proves the live callback won the Typer registration race.
    """
    from click.testing import CliRunner

    from mahavishnu._main_cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["demo", "agno", "--help"])
    assert result.exit_code == 0, result.output
    assert "--repos" in result.output, (
        "demo agno is showing stub-style --help (missing --repos). "
        "The live @demo_app.command(\"agno\") callback was likely "
        "replaced by the stub registration loop."
    )


def test_demo_stub_loop_no_longer_registers_agno() -> None:
    """The stub registration loop must not include ``agno``.

    The loop in ``cli/demo_cli.py`` iterates over a tuple of stub names;
    ``agno`` was promoted to live in 2026-10-15 and would otherwise
    override the live command with a no-op stub.
    """
    from mahavishnu.cli import demo_cli

    stub_names = set(demo_cli._STUB_COSTS.keys())
    assert "agno" not in stub_names, (
        "agno is in _STUB_COSTS — the stub registration loop will "
        "shadow the live @demo_app.command(\"agno\") callback. "
        "Remove the \"agno\" entry from _STUB_COSTS and from the "
        "registration loop tuple."
    )


def test_demo_llamaindex_is_live_implementation() -> None:
    """``mahavishnu demo llamaindex`` must be a live implementation.

    2026-10-16 wire-up fix: the llamaindex demo was promoted from a
    stub to a live implementation (drives ``LlamaIndexAdapter.execute``
    end-to-end after the ollama drop). The live path exposes
    ``--repos``, ``--task-type``, ``--query``, ``--keep``,
    ``--timeout``; the stub path emits ``--why-stub`` instead.
    Asserting ``--repos`` is present proves the live callback won the
    Typer registration race.
    """
    from click.testing import CliRunner

    from mahavishnu._main_cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["demo", "llamaindex", "--help"])
    assert result.exit_code == 0, result.output
    assert "--repos" in result.output, (
        "demo llamaindex is showing stub-style --help (missing --repos). "
        "The live @demo_app.command(\"llamaindex\") callback was likely "
        "replaced by the stub registration loop."
    )


def test_demo_stub_loop_no_longer_registers_llamaindex() -> None:
    """The stub registration loop must not include ``llamaindex``.

    The loop in ``cli/demo_cli.py`` iterates over a tuple of stub names;
    ``llamaindex`` was promoted to live in 2026-10-16 and would
    otherwise override the live command with a no-op stub.
    """
    from mahavishnu.cli import demo_cli

    stub_names = set(demo_cli._STUB_COSTS.keys())
    assert "llamaindex" not in stub_names, (
        "llamaindex is in _STUB_COSTS — the stub registration loop will "
        "shadow the live @demo_app.command(\"llamaindex\") callback. "
        "Remove the \"llamaindex\" entry from _STUB_COSTS and from the "
        "registration loop tuple."
    )


def test_demo_pydantic_ai_is_live_implementation() -> None:
    """``mahavishnu demo pydantic_ai`` must be a live implementation.

    2026-10-16 wire-up fix: the pydantic_ai demo was promoted from a
    stub to a live implementation (drives ``PydanticAIAdapter.execute``
    end-to-end). The live path exposes ``--repos``, ``--prompt``,
    ``--keep``, ``--timeout``; the stub path emits ``--why-stub``
    instead. Asserting ``--repos`` is present proves the live callback
    won the Typer registration race.
    """
    from click.testing import CliRunner

    from mahavishnu._main_cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["demo", "pydantic_ai", "--help"])
    assert result.exit_code == 0, result.output
    assert "--repos" in result.output, (
        "demo pydantic_ai is showing stub-style --help (missing --repos). "
        "The live @demo_app.command(\"pydantic_ai\") callback was likely "
        "replaced by the stub registration loop."
    )


def test_demo_stub_loop_no_longer_registers_pydantic_ai() -> None:
    """The stub registration loop must not include ``pydantic_ai``.

    The loop in ``cli/demo_cli.py`` iterates over a tuple of stub names;
    ``pydantic_ai`` was promoted to live in 2026-10-16 and would
    otherwise override the live command with a no-op stub.
    """
    from mahavishnu.cli import demo_cli

    stub_names = set(demo_cli._STUB_COSTS.keys())
    assert "pydantic_ai" not in stub_names, (
        "pydantic_ai is in _STUB_COSTS — the stub registration loop will "
        "shadow the live @demo_app.command(\"pydantic_ai\") callback. "
        "Remove the \"pydantic_ai\" entry from _STUB_COSTS and from the "
        "registration loop tuple."
    )


def test_demo_crow_is_live_implementation() -> None:
    """``mahavishnu demo crow`` must be a live implementation.

    2026-10-16 wire-up fix: the crow demo was promoted from a stub
    to a live implementation (drives ``CrowTerminalAdapter`` against
    a live crow-mcp). The live path exposes ``--cmd``, ``--keep``,
    ``--timeout``; the stub path emits ``--why-stub`` instead.
    Asserting ``--cmd`` is present proves the live callback won the
    Typer registration race.
    """
    from click.testing import CliRunner

    from mahavishnu._main_cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["demo", "crow", "--help"])
    assert result.exit_code == 0, result.output
    assert "--cmd" in result.output, (
        "demo crow is showing stub-style --help (missing --cmd). "
        "The live @demo_app.command(\"crow\") callback was likely "
        "replaced by the stub registration loop."
    )


def test_demo_stub_loop_no_longer_registers_crow() -> None:
    """The stub registration loop must not include ``crow``.

    The loop in ``cli/demo_cli.py`` iterates over a tuple of stub names;
    ``crow`` was promoted to live in 2026-10-16 and would otherwise
    override the live command with a no-op stub.
    """
    from mahavishnu.cli import demo_cli

    stub_names = set(demo_cli._STUB_COSTS.keys())
    assert "crow" not in stub_names, (
        "crow is in _STUB_COSTS — the stub registration loop will "
        "shadow the live @demo_app.command(\"crow\") callback. "
        "Remove the \"crow\" entry from _STUB_COSTS and from the "
        "registration loop tuple."
    )


def test_demo_hatchet_is_live_implementation() -> None:
    """``mahavishnu demo hatchet`` must be a live implementation.

    2026-10-17 wire-up fix: the hatchet demo was promoted from a
    stub to a live implementation (drives ``HatchetAdapterImpl.execute``
    end-to-end). The live path exposes ``--repos``, ``--prompt``,
    ``--workflow-name``, ``--keep``, ``--timeout``; the stub path
    emits ``--why-stub`` instead. Asserting ``--repos`` is present
    proves the live callback won the Typer registration race.
    """
    from click.testing import CliRunner

    from mahavishnu._main_cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["demo", "hatchet", "--help"])
    assert result.exit_code == 0, result.output
    assert "--repos" in result.output, (
        "demo hatchet is showing stub-style --help (missing --repos). "
        "The live @demo_app.command(\"hatchet\") callback was likely "
        "replaced by the stub registration loop."
    )


def test_demo_stub_loop_no_longer_registers_hatchet() -> None:
    """The stub registration loop must not include ``hatchet``.

    The loop in ``cli/demo_cli.py`` iterates over a tuple of stub names;
    ``hatchet`` was promoted to live in 2026-10-17 and would otherwise
    override the live command with a no-op stub.
    """
    from mahavishnu.cli import demo_cli

    stub_names = set(demo_cli._STUB_COSTS.keys())
    assert "hatchet" not in stub_names, (
        "hatchet is in _STUB_COSTS — the stub registration loop will "
        "shadow the live @demo_app.command(\"hatchet\") callback. "
        "Remove the \"hatchet\" entry from _STUB_COSTS and from the "
        "registration loop tuple."
    )
