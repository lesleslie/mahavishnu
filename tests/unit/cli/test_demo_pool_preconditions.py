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
    )
    assert failures == []


def test_pool_mahavishnu_preconditions_fail_when_tmux_missing() -> None:
    from mahavishnu.cli.demo_cli import _check_pool_mahavishnu_preconditions

    failures = _check_pool_mahavishnu_preconditions(tmux_which=lambda _: None)
    assert any("tmux" in f for f in failures)


def test_pool_mahavishnu_preconditions_fail_when_claude_missing() -> None:
    from mahavishnu.cli.demo_cli import _check_pool_mahavishnu_preconditions

    failures = _check_pool_mahavishnu_preconditions(
        tmux_which=lambda _: "/usr/bin/tmux",
        claude_which=lambda _: None,
    )
    # Default require_claude=True; if claude is absent, expect a claude failure.
    assert any("claude" in f for f in failures)


def test_pool_mahavishnu_preconditions_skip_claude_when_require_claude_false() -> None:
    from mahavishnu.cli.demo_cli import _check_pool_mahavishnu_preconditions

    failures = _check_pool_mahavishnu_preconditions(
        tmux_which=lambda _: "/usr/bin/tmux",
        claude_which=lambda _: None,
        require_claude=False,
    )
    assert failures == []


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
