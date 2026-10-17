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

    failures = _check_workflow_pool_worker_terminal_preconditions(
        adapter="mock",
        exists=lambda _: True,  # bypass Shepherd workspace probe
    )
    assert failures == []


def test_workflow_pool_worker_terminal_preconditions_pass_with_tmux_when_present() -> None:
    from mahavishnu.cli.demo_cli import _check_workflow_pool_worker_terminal_preconditions

    failures = _check_workflow_pool_worker_terminal_preconditions(
        adapter="tmux",
        tmux_which=lambda _: "/usr/bin/tmux",
        exists=lambda _: True,
    )
    assert failures == []


def test_workflow_pool_worker_terminal_preconditions_fail_when_tmux_missing() -> None:
    from mahavishnu.cli.demo_cli import _check_workflow_pool_worker_terminal_preconditions

    failures = _check_workflow_pool_worker_terminal_preconditions(
        adapter="tmux",
        tmux_which=lambda _: None,
        exists=lambda _: True,
    )
    assert any("tmux" in f for f in failures)


def test_workflow_pool_worker_terminal_preconditions_fail_when_adapter_unsupported() -> None:
    from mahavishnu.cli.demo_cli import _check_workflow_pool_worker_terminal_preconditions

    failures = _check_workflow_pool_worker_terminal_preconditions(
        adapter="crow",
        exists=lambda _: True,
    )
    assert any("unsupported" in f for f in failures)


def test_workflow_pool_worker_terminal_preconditions_fail_when_shepherd_workspace_uninitialized() -> None:
    """Shepherd precondition fires when the workspace marker ``.vcscore`` is missing.

    The triple-composition demo uses ``MahavishnuPool`` (the only pool
    that wires a ``terminal_manager`` directly), so it inherits the
    Shepherd-workspace requirement — surfaced here so the operator
    sees a clear "run sp init first" message instead of an MHV-312
    stack trace at runtime.
    """
    from pathlib import Path

    from mahavishnu.cli.demo_cli import _check_workflow_pool_worker_terminal_preconditions

    failures = _check_workflow_pool_worker_terminal_preconditions(
        adapter="mock",
        exists=lambda _: False,
        home=Path("/tmp/fake-home-for-shepherd-test"),
    )
    assert any("Shepherd workspace" in f and "sp init" in f for f in failures), (
        f"expected a Shepherd-init remediation message, got: {failures}"
    )


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
        exists=lambda _: True,  # bypass both Shepherd workspace probes
    )
    assert failures == []


def test_workflow_adapter_swap_preconditions_pass_with_mock_mock_and_explicit_check() -> None:
    """Same-name adapters are rejected — exercise the rejection path explicitly."""
    from mahavishnu.cli.demo_cli import _check_workflow_adapter_swap_preconditions

    # mock vs mock is rejected (swap is meaningless). The same-name
    # failure surfaces BEFORE the Shepherd check (it comes earlier in
    # the precondition function), so this test passes regardless of
    # the workspace state.
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
        exists=lambda _: True,
    )
    assert any("not supported" in f for f in failures)


def test_workflow_adapter_swap_preconditions_fail_when_tmux_missing() -> None:
    from mahavishnu.cli.demo_cli import _check_workflow_adapter_swap_preconditions

    failures = _check_workflow_adapter_swap_preconditions(
        adapter_a="mock",
        adapter_b="tmux",
        tmux_which=lambda _: None,
        exists=lambda _: True,
    )
    assert any("tmux" in f for f in failures)


def test_workflow_adapter_swap_preconditions_fail_when_shepherd_workspace_uninitialized() -> None:
    """Both Shepherd workspace probes fire when the marker is missing.

    The swap demo runs the same task through two pools back-to-back
    (one per adapter). Each pool needs its own Shepherd workspace, so
    BOTH ``demo-aswap-adapter_a/workspace`` and
    ``demo-aswap-adapter_b/workspace`` are checked. When the
    ``.vcscore`` marker is reported missing, the precondition surfaces
    two remediation lines so the operator can ``sp init`` each.
    """
    from pathlib import Path

    from mahavishnu.cli.demo_cli import _check_workflow_adapter_swap_preconditions

    failures = _check_workflow_adapter_swap_preconditions(
        adapter_a="mock",
        adapter_b="mock",  # use mock/mock so the same-name check is the
        #                          first failure; this test focuses on
        #                          whether the Shepherd probes fire after
        #                          it. Note: with mock/mock the swap
        #                          rejection surfaces first, so we test
        #                          the distinct-adapter case below for
        #                          both Shepherd probes.
        exists=lambda _: False,
    )
    # With mock/mock, the same-name failure is the only thing in the
    # list (Shepherd checks come after the same-name check in the
    # function but still run, so we expect BOTH failures).
    assert any("two different" in f for f in failures)
    assert any("Shepherd workspace" in f for f in failures), (
        f"expected at least one Shepherd-init remediation, got: {failures}"
    )


def test_workflow_adapter_swap_preconditions_surfaces_both_shepherd_failures() -> None:
    """With distinct adapters, the precondition surfaces BOTH Shepherd failures."""
    from pathlib import Path

    from mahavishnu.cli.demo_cli import _check_workflow_adapter_swap_preconditions

    failures = _check_workflow_adapter_swap_preconditions(
        adapter_a="mock",
        adapter_b="tmux",
        tmux_which=lambda _: "/usr/bin/tmux",
        exists=lambda _: False,
        home=Path("/tmp/fake-home-for-shepherd-test"),
    )
    shepherd_failures = [f for f in failures if "Shepherd workspace" in f]
    assert len(shepherd_failures) == 2, (
        f"expected 2 Shepherd failures (one per pool), got: {failures}"
    )
    assert any("demo-aswap-adapter_a" in f for f in shepherd_failures)
    assert any("demo-aswap-adapter_b" in f for f in shepherd_failures)
