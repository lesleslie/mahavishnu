"""Tests for the Bifrost launchd lifecycle port.

req: REQ-BIFROST-033

These exercise the sequencing invariants that matter, not launchctl itself:
readiness gating on the harness rewrite, the ``stop`` ordering, and the fact
that every harness rewrite routes through ``toggles.apply`` so the operator
gate is honoured.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mahavishnu.bifrost import gateway, lifecycle

if TYPE_CHECKING:
    from pathlib import Path


_RECORDED: list[str] = []


@pytest.fixture(autouse=True)
def _no_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise the operator gate and record harness rewrites."""
    from mahavishnu.bifrost import toggles

    monkeypatch.delenv(toggles.GATE_ENV, raising=False)
    _RECORDED.clear()
    monkeypatch.setattr(lifecycle, "apply", lambda _harness, action: _RECORDED.append(action))


@pytest.fixture(autouse=True)
def _no_launchd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Never touch the real launchd domain, plist, port, or ready file."""
    monkeypatch.setattr(lifecycle, "GUI_DOMAIN", f"gui/test-{tmp_path.name}")
    monkeypatch.setattr(lifecycle, "TARGET_PLIST", tmp_path / "ai.bifrost.gateway.plist")
    monkeypatch.setattr(lifecycle, "SOURCE_PLIST", tmp_path / "source.plist")
    monkeypatch.setattr(lifecycle, "READY_FILE", tmp_path / "bifrost.ready")
    monkeypatch.setattr(lifecycle, "PORT", 18471)
    monkeypatch.setattr(lifecycle, "kill_listener", lambda: None)
    monkeypatch.setattr(lifecycle, "install_plist", lambda: None)
    monkeypatch.setattr(lifecycle, "bootstrap", lambda: None)
    monkeypatch.setattr(lifecycle, "bootout", lambda: None)
    monkeypatch.setattr(lifecycle.time, "sleep", lambda _s: None)
    monkeypatch.setattr(lifecycle, "wait_for_ready_file", lambda *_a, **_k: True)


def _calls() -> list[str]:
    return list(_RECORDED)


def test_start_repoints_harnesses_once_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """req: REQ-BIFROST-033 -- routing flips only after the gateway is ready."""
    lifecycle.start()
    assert _calls() == ["bifrost", "bifrost"]


def test_start_leaves_harness_untouched_when_never_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed boot must not leave a client aimed at a dead gateway."""
    monkeypatch.setattr(lifecycle, "wait_for_ready_file", lambda *_a, **_k: False)

    lifecycle.start()

    assert _calls() == []


def test_stop_restores_before_teardown(monkeypatch: pytest.MonkeyPatch) -> None:
    """req: REQ-BIFROST-033 -- clients are restored before the gateway dies."""
    order: list[str] = []

    monkeypatch.setattr(lifecycle, "repoint_harnesses", lambda a: order.append(f"harness:{a}"))
    monkeypatch.setattr(lifecycle, "bootout", lambda: order.append("bootout"))

    lifecycle.stop()

    assert order == ["harness:direct", "bootout"]


def test_stop_clears_ready_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The ready file is the readiness contract; stop must retract it."""
    ready = tmp_path / "bifrost.ready"
    ready.touch()

    monkeypatch.setattr(lifecycle, "READY_FILE", ready)
    lifecycle.stop()

    assert not ready.exists()


def test_restart_and_rebootstrap_repoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both keep clients on Bifrost when the gateway comes back up."""
    lifecycle.restart()
    assert _calls() == ["bifrost", "bifrost"]

    _RECORDED.clear()
    lifecycle.rebootstrap()
    assert _calls() == ["bifrost", "bifrost"]


def test_status_reports_not_loaded(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """A missing service is reported, not raised."""
    monkeypatch.setattr(
        lifecycle,
        "_run",
        lambda _cmd: lifecycle.subprocess.CompletedProcess([], 1, "", "no such service"),
    )
    lifecycle.status()
    assert "service not loaded" in capsys.readouterr().out


def test_gateway_wrap_adds_stdbuf_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Node block-buffering delays log emission; stdbuf prevents it."""
    monkeypatch.setattr(gateway.shutil, "which", lambda _n: "/usr/bin/stdbuf")
    assert gateway.wrap_with_line_buffering(["node", "b.js"])[:3] == [
        "stdbuf",
        "-oL",
        "-eL",
    ]


def test_gateway_wrap_degrades_without_stdbuf(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing coreutils warns but still returns a runnable command."""
    monkeypatch.setattr(gateway.shutil, "which", lambda _n: None)
    assert gateway.wrap_with_line_buffering(["node", "b.js"]) == ["node", "b.js"]


def test_gateway_readiness_returns_false_when_child_exits() -> None:
    """A child that dies before binding fails fast instead of timing out."""
    exited = gateway.subprocess.CompletedProcess([], 1, "", "")
    exited.poll = lambda: 1  # type: ignore[method-assign]
    exited.returncode = 1
    assert gateway.wait_for_ready(exited, timeout=5) is False


def test_gateway_templates_resolve_under_repo() -> None:
    """REPO_ROOT moved with the module; the config template must still resolve."""
    assert gateway.TEMPLATE_CONFIG.name == "config.template.json"
    assert gateway.TEMPLATE_CONFIG.parent.name == "bifrost"
