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


# ============================================================================
# Pool demos (PR #2 — 4 new live implementations)
#
# Each pool demo follows the same anti-revert pattern as the engine
# demos above: (1) a live-implementation test asserting a callback-
# specific flag is present in --help, and (2) a stub-loop exclusion
# test asserting the name is NOT in _STUB_COSTS. The PR #2 migration
# also removed the runpod-flash deprecation warning that the pool-runpod
# demo would otherwise have inherited (the SDK 2.0 substrate is
# deprecation-free; see docs/decisions/2026-10-17-runpod-flash-to-sdk-2.md).
# ============================================================================


def test_demo_pool_mahavishnu_is_live_implementation() -> None:
    """``mahavishnu demo pool-mahavishnu`` must be a live implementation.

    The live path exposes ``--min`` and ``--max`` (MahavishnuPool scales
    between min and max workers); the stub path only exposes
    ``--why-stub``. Asserting ``--max`` proves the live callback won
    the Typer registration race.
    """
    from click.testing import CliRunner

    from mahavishnu._main_cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["demo", "pool-mahavishnu", "--help"])
    assert result.exit_code == 0, result.output
    assert "--max" in result.output, (
        "demo pool-mahavishnu is showing stub-style --help (missing --max). "
        "The live @demo_app.command(\"pool-mahavishnu\") callback was "
        "likely replaced by the stub registration loop."
    )


def test_demo_stub_loop_no_longer_registers_pool_mahavishnu() -> None:
    """The stub registration loop must not include ``pool-mahavishnu``."""
    from mahavishnu.cli import demo_cli

    stub_names = set(demo_cli._STUB_COSTS.keys())
    assert "pool-mahavishnu" not in stub_names, (
        "pool-mahavishnu is in _STUB_COSTS — the stub registration "
        "loop will shadow the live @demo_app.command(\"pool-mahavishnu\") "
        "callback. Remove the entry from _STUB_COSTS and from the "
        "registration loop tuple."
    )


def test_demo_pool_session_buddy_is_live_implementation() -> None:
    """``mahavishnu demo pool-session-buddy`` must be a live implementation.

    The live path exposes ``--url`` (the Session-Buddy MCP server URL);
    the stub path only exposes ``--why-stub``. Asserting ``--url``
    proves the live callback won the Typer registration race.
    """
    from click.testing import CliRunner

    from mahavishnu._main_cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["demo", "pool-session-buddy", "--help"])
    assert result.exit_code == 0, result.output
    assert "--url" in result.output, (
        "demo pool-session-buddy is showing stub-style --help (missing --url). "
        "The live @demo_app.command(\"pool-session-buddy\") callback was "
        "likely replaced by the stub registration loop."
    )


def test_demo_stub_loop_no_longer_registers_pool_session_buddy() -> None:
    """The stub registration loop must not include ``pool-session-buddy``."""
    from mahavishnu.cli import demo_cli

    stub_names = set(demo_cli._STUB_COSTS.keys())
    assert "pool-session-buddy" not in stub_names, (
        "pool-session-buddy is in _STUB_COSTS — the stub registration "
        "loop will shadow the live @demo_app.command(\"pool-session-buddy\") "
        "callback. Remove the entry from _STUB_COSTS and from the "
        "registration loop tuple."
    )


def test_demo_pool_runpod_is_live_implementation() -> None:
    """``mahavishnu demo pool-runpod`` must be a live implementation.

    The live path exposes ``--endpoint-id`` (the RunPod serverless
    endpoint id); the stub path only exposes ``--why-stub``. Asserting
    ``--endpoint-id`` proves the live callback won the Typer registration
    race. This demo also exercises the SDK 2.0 thin client — the
    runpod-flash deprecation warning is gone.
    """
    from click.testing import CliRunner

    from mahavishnu._main_cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["demo", "pool-runpod", "--help"])
    assert result.exit_code == 0, result.output
    assert "--endpoint-id" in result.output, (
        "demo pool-runpod is showing stub-style --help (missing --endpoint-id). "
        "The live @demo_app.command(\"pool-runpod\") callback was likely "
        "replaced by the stub registration loop."
    )


def test_demo_stub_loop_no_longer_registers_pool_runpod() -> None:
    """The stub registration loop must not include ``pool-runpod``."""
    from mahavishnu.cli import demo_cli

    stub_names = set(demo_cli._STUB_COSTS.keys())
    assert "pool-runpod" not in stub_names, (
        "pool-runpod is in _STUB_COSTS — the stub registration loop "
        "will shadow the live @demo_app.command(\"pool-runpod\") callback. "
        "Remove the entry from _STUB_COSTS and from the registration loop tuple."
    )


def test_demo_pool_pi_is_live_implementation() -> None:
    """``mahavishnu demo pool-pi`` must be a live implementation.

    The live path exposes ``--prompt`` (PiPool dispatches a prompt to
    the npx pi-coding-agent subprocess); the stub path only exposes
    ``--why-stub``. Asserting ``--prompt`` proves the live callback won
    the Typer registration race.
    """
    from click.testing import CliRunner

    from mahavishnu._main_cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["demo", "pool-pi", "--help"])
    assert result.exit_code == 0, result.output
    assert "--prompt" in result.output, (
        "demo pool-pi is showing stub-style --help (missing --prompt). "
        "The live @demo_app.command(\"pool-pi\") callback was likely "
        "replaced by the stub registration loop."
    )


def test_demo_stub_loop_no_longer_registers_pool_pi() -> None:
    """The stub registration loop must not include ``pool-pi``."""
    from mahavishnu.cli import demo_cli

    stub_names = set(demo_cli._STUB_COSTS.keys())
    assert "pool-pi" not in stub_names, (
        "pool-pi is in _STUB_COSTS — the stub registration loop will "
        "shadow the live @demo_app.command(\"pool-pi\") callback. "
        "Remove the entry from _STUB_COSTS and from the registration loop tuple."
    )


# ============================================================================
# Workflow demos (PR #3 — 3 new live implementations of cross-substrate
# compositions). Each demo follows the same anti-revert pattern as the
# pool demos above: (1) a live-implementation test asserting a callback-
# specific flag is present in --help, and (2) a stub-loop exclusion test
# asserting the name is NOT in _STUB_COSTS.
# ============================================================================


def test_demo_workflow_pool_worker_terminal_is_live_implementation() -> None:
    """``mahavishnu demo workflow-pool-worker-terminal`` must be a live implementation.

    The live path exposes ``--adapter`` (terminal adapter selection: mock|tmux);
    the stub path only exposes ``--why-stub``. Asserting ``--adapter`` proves
    the live callback won the Typer registration race.
    """
    from click.testing import CliRunner

    from mahavishnu._main_cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["demo", "workflow-pool-worker-terminal", "--help"])
    assert result.exit_code == 0, result.output
    assert "--adapter" in result.output, (
        "demo workflow-pool-worker-terminal is showing stub-style --help "
        "(missing --adapter). The live @demo_app.command(\"workflow-pool-"
        "worker-terminal\") callback was likely replaced by the stub "
        "registration loop."
    )


def test_demo_stub_loop_no_longer_registers_workflow_pool_worker_terminal() -> None:
    """The stub registration loop must not include ``workflow-pool-worker-terminal``."""
    from mahavishnu.cli import demo_cli

    stub_names = set(demo_cli._STUB_COSTS.keys())
    assert "workflow-pool-worker-terminal" not in stub_names, (
        "workflow-pool-worker-terminal is in _STUB_COSTS — the stub "
        "registration loop will shadow the live callback. Remove the "
        "entry from _STUB_COSTS and from the registration loop tuple."
    )


def test_demo_workflow_multi_pool_handoff_is_live_implementation() -> None:
    """``mahavishnu demo workflow-multi-pool-handoff`` must be a live implementation.

    The live path exposes ``--source-pool`` and ``--target-pool`` (the two
    pool substrates that participate in the handoff); the stub path only
    exposes ``--why-stub``. Asserting ``--source-pool`` proves the live
    callback won the Typer registration race.
    """
    from click.testing import CliRunner

    from mahavishnu._main_cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["demo", "workflow-multi-pool-handoff", "--help"])
    assert result.exit_code == 0, result.output
    assert "--source-pool" in result.output, (
        "demo workflow-multi-pool-handoff is showing stub-style --help "
        "(missing --source-pool). The live @demo_app.command(\"workflow-"
        "multi-pool-handoff\") callback was likely replaced by the stub "
        "registration loop."
    )


def test_demo_stub_loop_no_longer_registers_workflow_multi_pool_handoff() -> None:
    """The stub registration loop must not include ``workflow-multi-pool-handoff``."""
    from mahavishnu.cli import demo_cli

    stub_names = set(demo_cli._STUB_COSTS.keys())
    assert "workflow-multi-pool-handoff" not in stub_names, (
        "workflow-multi-pool-handoff is in _STUB_COSTS — the stub "
        "registration loop will shadow the live callback. Remove the "
        "entry from _STUB_COSTS and from the registration loop tuple."
    )


def test_demo_workflow_adapter_swap_is_live_implementation() -> None:
    """``mahavishnu demo workflow-adapter-swap`` must be a live implementation.

    The live path exposes ``--adapter-a`` and ``--adapter-b`` (the two
    terminal adapters compared side-by-side); the stub path only exposes
    ``--why-stub``. Asserting ``--adapter-a`` proves the live callback
    won the Typer registration race.
    """
    from click.testing import CliRunner

    from mahavishnu._main_cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["demo", "workflow-adapter-swap", "--help"])
    assert result.exit_code == 0, result.output
    assert "--adapter-a" in result.output, (
        "demo workflow-adapter-swap is showing stub-style --help "
        "(missing --adapter-a). The live @demo_app.command(\"workflow-"
        "adapter-swap\") callback was likely replaced by the stub "
        "registration loop."
    )


def test_demo_stub_loop_no_longer_registers_workflow_adapter_swap() -> None:
    """The stub registration loop must not include ``workflow-adapter-swap``."""
    from mahavishnu.cli import demo_cli

    stub_names = set(demo_cli._STUB_COSTS.keys())
    assert "workflow-adapter-swap" not in stub_names, (
        "workflow-adapter-swap is in _STUB_COSTS — the stub registration "
        "loop will shadow the live callback. Remove the entry from "
        "_STUB_COSTS and from the registration loop tuple."
    )


# ============================================================================
# Workflow demos (PR #4 — 2 new live implementations: pi-cascade and
# pi-then-local). Each demo follows the same anti-revert pattern as the
# demos above: (1) a live-implementation test asserting a callback-
# specific flag is present in --help, and (2) a stub-loop exclusion test
# asserting the name is NOT in _STUB_COSTS.
# ============================================================================


def test_demo_workflow_pi_cascade_is_live_implementation() -> None:
    """``mahavishnu demo workflow-pi-cascade`` must be a live implementation.

    The live path exposes ``--followup`` (the second-turn prompt for
    PiPool's cascade); the stub path only exposes ``--why-stub``.
    Asserting ``--followup`` proves the live callback won the Typer
    registration race.
    """
    from click.testing import CliRunner

    from mahavishnu._main_cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["demo", "workflow-pi-cascade", "--help"])
    assert result.exit_code == 0, result.output
    assert "--followup" in result.output, (
        "demo workflow-pi-cascade is showing stub-style --help "
        "(missing --followup). The live @demo_app.command(\"workflow-"
        "pi-cascade\") callback was likely replaced by the stub "
        "registration loop."
    )


def test_demo_stub_loop_no_longer_registers_workflow_pi_cascade() -> None:
    """The stub registration loop must not include ``workflow-pi-cascade``."""
    from mahavishnu.cli import demo_cli

    stub_names = set(demo_cli._STUB_COSTS.keys())
    assert "workflow-pi-cascade" not in stub_names, (
        "workflow-pi-cascade is in _STUB_COSTS — the stub registration "
        "loop will shadow the live callback. Remove the entry from "
        "_STUB_COSTS and from the registration loop tuple."
    )


def test_demo_workflow_pi_then_local_is_live_implementation() -> None:
    """``mahavishnu demo workflow-pi-then-local`` must be a live implementation.

    The live path exposes ``--pi-prompt`` and ``--local-prompt`` (the
    two prompts sent to the two pools in sequence); the stub path
    only exposes ``--why-stub``. Asserting ``--pi-prompt`` proves the
    live callback won the Typer registration race.
    """
    from click.testing import CliRunner

    from mahavishnu._main_cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["demo", "workflow-pi-then-local", "--help"])
    assert result.exit_code == 0, result.output
    assert "--pi-prompt" in result.output, (
        "demo workflow-pi-then-local is showing stub-style --help "
        "(missing --pi-prompt). The live @demo_app.command(\"workflow-"
        "pi-then-local\") callback was likely replaced by the stub "
        "registration loop."
    )


def test_demo_stub_loop_no_longer_registers_workflow_pi_then_local() -> None:
    """The stub registration loop must not include ``workflow-pi-then-local``."""
    from mahavishnu.cli import demo_cli

    stub_names = set(demo_cli._STUB_COSTS.keys())
    assert "workflow-pi-then-local" not in stub_names, (
        "workflow-pi-then-local is in _STUB_COSTS — the stub registration "
        "loop will shadow the live callback. Remove the entry from "
        "_STUB_COSTS and from the registration loop tuple."
    )
