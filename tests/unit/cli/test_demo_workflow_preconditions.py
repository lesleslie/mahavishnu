"""Precondition checks for the 3 workflow demos (PR #3).

The demos' preconditions functions are the CLI-friendly surface for
"is this composition even runnable from my shell?" — empty list = pass,
non-empty list = human-readable failures. Each function accepts
injectable probes (env getters, HTTP probes, ``shutil.which``
substitutes) so the tests can drive every branch without touching the
real substrate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# workflow-pool-worker-terminal
# ---------------------------------------------------------------------------


def test_workflow_pool_worker_terminal_preconditions_pass_with_mock() -> None:
    from mahavishnu.cli.demo_cli import _check_workflow_pool_worker_terminal_preconditions

    failures = _check_workflow_pool_worker_terminal_preconditions(adapter="mock")
    assert failures == []


def test_workflow_pool_worker_terminal_preconditions_pass_with_tmux_when_present() -> None:
    from mahavishnu.cli.demo_cli import _check_workflow_pool_worker_terminal_preconditions

    failures = _check_workflow_pool_worker_terminal_preconditions(
        adapter="tmux",
        tmux_which=lambda _: "/usr/bin/tmux",
    )
    assert failures == []


def test_workflow_pool_worker_terminal_preconditions_fail_when_tmux_missing() -> None:
    from mahavishnu.cli.demo_cli import _check_workflow_pool_worker_terminal_preconditions

    failures = _check_workflow_pool_worker_terminal_preconditions(
        adapter="tmux",
        tmux_which=lambda _: None,
    )
    assert any("tmux" in f for f in failures)


def test_workflow_pool_worker_terminal_preconditions_fail_when_adapter_unsupported() -> None:
    from mahavishnu.cli.demo_cli import _check_workflow_pool_worker_terminal_preconditions

    failures = _check_workflow_pool_worker_terminal_preconditions(adapter="crow")
    assert any("unsupported" in f for f in failures)


# ---------------------------------------------------------------------------
# workflow-multi-pool-handoff
# ---------------------------------------------------------------------------


def test_workflow_multi_pool_handoff_preconditions_pass_with_pi_pi() -> None:
    from mahavishnu.cli.demo_cli import _check_workflow_multi_pool_handoff_preconditions

    # pi requires npx; use injectable which + skip session-buddy probe
    failures = _check_workflow_multi_pool_handoff_preconditions(
        source_pool="pi",
        target_pool="pi",
        tmux_which=lambda _: None,
    )
    # No tmux check fires for source/target=pi; HTTP probe only fires
    # for source/target=session-buddy (default source is sb but we
    # overrode to pi above).
    assert failures == []


def test_workflow_multi_pool_handoff_preconditions_fail_when_source_pool_unsupported() -> None:
    from mahavishnu.cli.demo_cli import _check_workflow_multi_pool_handoff_preconditions

    failures = _check_workflow_multi_pool_handoff_preconditions(
        source_pool="runpod",
        target_pool="mahavishnu",
        tmux_which=lambda _: "/usr/bin/tmux",
    )
    assert any("not supported" in f for f in failures)


def test_workflow_multi_pool_handoff_preconditions_fail_when_target_pool_unsupported() -> None:
    from mahavishnu.cli.demo_cli import _check_workflow_multi_pool_handoff_preconditions

    failures = _check_workflow_multi_pool_handoff_preconditions(
        source_pool="mahavishnu",
        target_pool="runpod",
        tmux_which=lambda _: "/usr/bin/tmux",
    )
    assert any("not supported" in f for f in failures)


def test_workflow_multi_pool_handoff_preconditions_fail_when_mahavishnu_target_lacks_tmux() -> None:
    from mahavishnu.cli.demo_cli import _check_workflow_multi_pool_handoff_preconditions

    failures = _check_workflow_multi_pool_handoff_preconditions(
        source_pool="pi",
        target_pool="mahavishnu",
        tmux_which=lambda _: None,
    )
    assert any("tmux" in f for f in failures)


# ---------------------------------------------------------------------------
# workflow-adapter-swap
# ---------------------------------------------------------------------------


def test_workflow_adapter_swap_preconditions_pass_with_distinct_adapters() -> None:
    from mahavishnu.cli.demo_cli import _check_workflow_adapter_swap_preconditions

    failures = _check_workflow_adapter_swap_preconditions(
        adapter_a="mock",
        adapter_b="tmux",
        tmux_which=lambda _: "/usr/bin/tmux",
    )
    assert failures == []


def test_workflow_adapter_swap_preconditions_pass_with_mock_mock_and_explicit_check() -> None:
    """Same-name adapters are rejected — exercise the rejection path explicitly."""
    from mahavishnu.cli.demo_cli import _check_workflow_adapter_swap_preconditions

    # mock vs mock is rejected (swap is meaningless)
    failures = _check_workflow_adapter_swap_preconditions(
        adapter_a="mock",
        adapter_b="mock",
    )
    assert any("two different" in f for f in failures)


def test_workflow_adapter_swap_preconditions_fail_when_unsupported_adapter() -> None:
    from mahavishnu.cli.demo_cli import _check_workflow_adapter_swap_preconditions

    failures = _check_workflow_adapter_swap_preconditions(
        adapter_a="crow",
        adapter_b="mock",
    )
    assert any("not supported" in f for f in failures)


def test_workflow_adapter_swap_preconditions_fail_when_tmux_missing() -> None:
    from mahavishnu.cli.demo_cli import _check_workflow_adapter_swap_preconditions

    failures = _check_workflow_adapter_swap_preconditions(
        adapter_a="mock",
        adapter_b="tmux",
        tmux_which=lambda _: None,
    )
    assert any("tmux" in f for f in failures)
