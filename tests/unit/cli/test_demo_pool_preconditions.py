"""Precondition checks for the 4 pool demos (PR #2).

The demos' preconditions functions are the CLI-friendly surface for
"is this substrate even reachable from my shell?" — empty list = pass,
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
# pool-mahavishnu
# ---------------------------------------------------------------------------


def test_pool_mahavishnu_preconditions_pass_when_tmux_and_claude_present() -> None:
    from mahavishnu.cli.demo_cli import _check_pool_mahavishnu_preconditions

    failures = _check_pool_mahavishnu_preconditions(
        tmux_which=lambda _: "/usr/bin/tmux",
        # Bypass the Shepherd workspace probe so this test focuses on
        # the tmux + claude branch. Shepherd is tested separately below.
        exists=lambda _: True,
    )
    assert failures == []


def test_pool_mahavishnu_preconditions_fail_when_tmux_missing() -> None:
    from mahavishnu.cli.demo_cli import _check_pool_mahavishnu_preconditions

    failures = _check_pool_mahavishnu_preconditions(
        tmux_which=lambda _: None,
        exists=lambda _: True,
    )
    assert any("tmux" in f for f in failures)


def test_pool_mahavishnu_preconditions_fail_when_claude_missing() -> None:
    from mahavishnu.cli.demo_cli import _check_pool_mahavishnu_preconditions

    failures = _check_pool_mahavishnu_preconditions(
        tmux_which=lambda _: "/usr/bin/tmux",
        claude_which=lambda _: None,
        exists=lambda _: True,
    )
    # Default require_claude=True; if claude is absent, expect a claude failure.
    assert any("claude" in f for f in failures)


def test_pool_mahavishnu_preconditions_skip_claude_when_require_claude_false() -> None:
    from mahavishnu.cli.demo_cli import _check_pool_mahavishnu_preconditions

    failures = _check_pool_mahavishnu_preconditions(
        tmux_which=lambda _: "/usr/bin/tmux",
        claude_which=lambda _: None,
        require_claude=False,
        exists=lambda _: True,
    )
    assert failures == []


def test_pool_mahavishnu_preconditions_fail_when_shepherd_workspace_uninitialized() -> None:
    """Shepherd precondition fires when the workspace marker ``.vcscore`` is missing.

    Without the marker, ``MahavishnuPool.start()`` fails fail-closed with
    ``MHV-312`` ("not a Shepherd workspace. Run `sp init` first.") — the
    precondition surfaces that here so the operator gets a clear
    remediation instead of a stack trace at runtime.
    """
    from pathlib import Path

    from mahavishnu.cli.demo_cli import _check_pool_mahavishnu_preconditions

    failures = _check_pool_mahavishnu_preconditions(
        tmux_which=lambda _: "/usr/bin/tmux",
        # exists=lambda _: False → the .vcscore marker is reported as
        # absent, regardless of what's on disk.
        exists=lambda _: False,
        home=Path("/tmp/fake-home-for-shepherd-test"),
    )
    assert any("Shepherd workspace" in f and "sp init" in f for f in failures), (
        f"expected a Shepherd-init remediation message, got: {failures}"
    )


def test_pool_mahavishnu_preconditions_pass_when_shepherd_workspace_initialized() -> None:
    """Shepherd precondition passes when ``.vcscore`` is reported present."""
    from mahavishnu.cli.demo_cli import _check_pool_mahavishnu_preconditions

    failures = _check_pool_mahavishnu_preconditions(
        tmux_which=lambda _: "/usr/bin/tmux",
        exists=lambda _: True,
    )
    # No Shepherd failure; the only remaining precondition is tmux+claude
    # which are satisfied.
    assert not any("Shepherd" in f for f in failures)


# ---------------------------------------------------------------------------
# _expected_shepherd_workspace_path — path-traversal rejection
# (sibling-path-gate-parity hardening: keep the precondition's path
#  equal to what the pool will resolve at runtime; reject names that
#  would resolve to a different location).
# ---------------------------------------------------------------------------


def test_expected_shepherd_workspace_path_rejects_parent_traversal() -> None:
    """``..`` in the pool name would let the gate disagree with the pool's ``Path.resolve()``."""
    import pytest

    from mahavishnu.cli.demo_cli import _expected_shepherd_workspace_path

    with pytest.raises(ValueError, match="must not contain '..' or be absolute"):
        _expected_shepherd_workspace_path("../../tmp/evil")


def test_expected_shepherd_workspace_path_rejects_absolute_path() -> None:
    """Absolute paths in the pool name would bypass the worktrees root entirely."""
    import pytest

    from mahavishnu.cli.demo_cli import _expected_shepherd_workspace_path

    with pytest.raises(ValueError, match="must not contain '..' or be absolute"):
        _expected_shepherd_workspace_path("/tmp/evil")


def test_expected_shepherd_workspace_path_rejects_path_separators() -> None:
    """``/`` or ``\\`` in the pool name would let the path escape the worktrees root."""
    import pytest

    from mahavishnu.cli.demo_cli import _expected_shepherd_workspace_path

    with pytest.raises(ValueError, match="must not contain path separators"):
        _expected_shepherd_workspace_path("subdir/evil")


def test_expected_shepherd_workspace_path_accepts_clean_name() -> None:
    """Clean names (kebab/underscore/alnum) are accepted and resolve under the worktrees root."""
    from pathlib import Path

    from mahavishnu.cli.demo_cli import _expected_shepherd_workspace_path

    result = _expected_shepherd_workspace_path("demo-mahavishnu", home=Path("/tmp/fake-home"))
    assert result == Path("/tmp/fake-home/.local/state/mahavishnu/worktrees/demo-mahavishnu/workspace")


def test_check_shepherd_workspace_resolves_symlinks_for_gate_parity() -> None:
    """``Path.resolve()`` is used inside the gate so a symlinked workspace is checked at its target.

    Without resolution, the gate checks the literal symlink path while
    the pool resolves the symlink and checks the target — gate and
    runtime disagree. The ``exists`` probe is invoked with the
    *resolved* path so the parity holds.
    """
    from pathlib import Path

    from mahavishnu.cli.demo_cli import _check_shepherd_workspace

    captured_paths: list[Path] = []

    def capturing_exists(p: Path) -> bool:
        captured_paths.append(p)
        return False

    # /tmp is a symlink to /private/tmp on macOS. Passing a workspace
    # under /tmp should make the gate resolve to /private/tmp/... .
    workspace = Path("/tmp/some-link-target/my-workspace")
    failures = _check_shepherd_workspace(workspace, exists=capturing_exists)
    assert failures, "expected a precondition failure when the marker is missing"
    # The captured path is the resolved one, not the literal symlink path.
    assert not str(captured_paths[0]).startswith("/tmp/some-link-target")
    # The failure message also references the resolved path.
    assert "/tmp/some-link-target" not in failures[0] or "/private" in failures[0]


# ---------------------------------------------------------------------------
# pool-session-buddy
# ---------------------------------------------------------------------------


def test_pool_session_buddy_preconditions_pass_when_probe_succeeds() -> None:
    from mahavishnu.cli.demo_cli import _check_pool_session_buddy_preconditions

    failures = _check_pool_session_buddy_preconditions(
        url="http://localhost:8678/mcp",
        http_probe=lambda _url, _timeout: True,
    )
    assert failures == []


def test_pool_session_buddy_preconditions_fail_when_probe_fails() -> None:
    from mahavishnu.cli.demo_cli import _check_pool_session_buddy_preconditions

    failures = _check_pool_session_buddy_preconditions(
        url="http://localhost:8678/mcp",
        http_probe=lambda _url, _timeout: False,
    )
    assert any("not reachable" in f for f in failures)


def test_pool_session_buddy_preconditions_reject_non_http_url() -> None:
    from mahavishnu.cli.demo_cli import _check_pool_session_buddy_preconditions

    failures = _check_pool_session_buddy_preconditions(
        url="ftp://localhost:8678/mcp",
        http_probe=lambda _url, _timeout: True,
    )
    assert any("http" in f for f in failures)


def test_pool_session_buddy_preconditions_reject_empty_url() -> None:
    from mahavishnu.cli.demo_cli import _check_pool_session_buddy_preconditions

    failures = _check_pool_session_buddy_preconditions(
        url="",
        http_probe=lambda _url, _timeout: True,
    )
    assert any("empty" in f for f in failures)


# ---------------------------------------------------------------------------
# pool-runpod
# ---------------------------------------------------------------------------


def test_pool_runpod_preconditions_pass_when_key_and_endpoint_present() -> None:
    from mahavishnu.cli.demo_cli import _check_pool_runpod_preconditions

    failures = _check_pool_runpod_preconditions(
        endpoint_id="ep-test-1234",
        env_getter=lambda name: "rp-secret" if name == "RUNPOD_API_KEY" else None,
    )
    assert failures == []


def test_pool_runpod_preconditions_fail_when_api_key_missing() -> None:
    from mahavishnu.cli.demo_cli import _check_pool_runpod_preconditions

    failures = _check_pool_runpod_preconditions(
        endpoint_id="ep-test-1234",
        env_getter=lambda _name: None,
    )
    assert any("RUNPOD_API_KEY" in f for f in failures)


def test_pool_runpod_preconditions_fail_when_endpoint_id_missing() -> None:
    from mahavishnu.cli.demo_cli import _check_pool_runpod_preconditions

    failures = _check_pool_runpod_preconditions(
        endpoint_id="",
        env_getter=lambda name: "rp-secret" if name == "RUNPOD_API_KEY" else None,
    )
    assert any("endpoint_id" in f for f in failures)


# ---------------------------------------------------------------------------
# pool-pi
# ---------------------------------------------------------------------------


def test_pool_pi_preconditions_pass_when_npx_present() -> None:
    from mahavishnu.cli.demo_cli import _check_pool_pi_preconditions

    failures = _check_pool_pi_preconditions(npx_which=lambda _: "/usr/bin/npx")
    assert failures == []


def test_pool_pi_preconditions_fail_when_npx_missing() -> None:
    from mahavishnu.cli.demo_cli import _check_pool_pi_preconditions

    failures = _check_pool_pi_preconditions(npx_which=lambda _: None)
    assert any("npx" in f for f in failures)
