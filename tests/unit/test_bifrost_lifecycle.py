"""Tests for the Bifrost launchd lifecycle port.

req: REQ-BIFROST-033

These exercise the sequencing invariants that matter, not launchctl itself:
readiness gating on the harness rewrite, the ``stop`` ordering, and the fact
that every harness rewrite routes through ``toggles.apply`` so the operator
gate is honoured.
"""

from __future__ import annotations

import json
import os
import sqlite3
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
    """Never touch the real launchd domain, plist, port, or config directory."""
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


@pytest.fixture(autouse=True)
def _no_real_config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Never write to the operator's live ``~/.config/bifrost``.

    Regression for live data loss. ``sync_config`` performs real filesystem
    work, and ``rebootstrap`` calls it. Before these paths were redirected,
    running this module overwrote the live ``config.json`` with the repo
    template and deleted the live ``config.db`` -- which took out the virtual
    key and the dashboard admin account ("no such table:
    governance_config"). Every test in a module that touches the config must
    therefore be confined to a scratch directory.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    template = tmp_path / "template.json"
    template.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(lifecycle, "BIFROST_CONFIG_DIR", config_dir)
    monkeypatch.setattr(lifecycle, "TARGET_CONFIG", config_dir / "config.json")
    monkeypatch.setattr(lifecycle, "SOURCE_CONFIG", template)
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


def test_sync_config_keeps_the_config_store(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """req: REQ-BIFROST-034 -- re-seeding config.json must not drop config.db.

    Regression for live data loss. With ``config_store`` enabled the SQLite DB
    is authoritative: it holds the providers, keys, governance config, virtual
    keys, and the dashboard admin account. ``config.json`` is only a first-run
    seed. ``sync_config`` used to unlink ``config.db`` unconditionally, so
    ``bifrost rebootstrap`` silently destroyed the virtual key and locked the
    operator out of the dashboard with "no such table: governance_config".

    The DB must now survive, with a timestamped backup alongside it.
    """
    config_dir = tmp_path / "bifrost"
    config_dir.mkdir()
    template = tmp_path / "template.json"
    template.write_text('{"seeded": true}', encoding="utf-8")
    target = config_dir / "config.json"
    target.write_text('{"old": true}', encoding="utf-8")
    db = config_dir / "config.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE governance_virtual_keys (name TEXT, value TEXT)")
        con.execute("INSERT INTO governance_virtual_keys VALUES ('k', 'sk-bf-secret')")
        con.commit()

    monkeypatch.setattr(lifecycle, "BIFROST_CONFIG_DIR", config_dir)
    monkeypatch.setattr(lifecycle, "TARGET_CONFIG", target)
    monkeypatch.setattr(lifecycle, "SOURCE_CONFIG", template)

    lifecycle.sync_config()

    assert json.loads(target.read_text(encoding="utf-8")) == {"seeded": True}
    assert db.exists(), "config store must survive a config.json re-seed"
    backups = list((config_dir / ".bak").glob("*-presync/config.db"))
    assert backups, "config store must be backed up before any re-seed"
    with sqlite3.connect(f"file:{backups[0]}?mode=ro", uri=True) as con:
        assert con.execute("SELECT value FROM governance_virtual_keys").fetchone()[0] == (
            "sk-bf-secret"
        ), "the snapshot must carry the store's contents"


def test_sync_config_drops_the_store_only_when_asked(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``drop_db=True`` still discards it -- after backing it up."""
    config_dir = tmp_path / "bifrost"
    config_dir.mkdir()
    template = tmp_path / "template.json"
    template.write_text("{}", encoding="utf-8")
    target = config_dir / "config.json"
    db = config_dir / "config.db"
    db.write_bytes(b"store")

    monkeypatch.setattr(lifecycle, "BIFROST_CONFIG_DIR", config_dir)
    monkeypatch.setattr(lifecycle, "TARGET_CONFIG", target)
    monkeypatch.setattr(lifecycle, "SOURCE_CONFIG", template)

    lifecycle.sync_config(drop_db=True)

    assert not db.exists()
    assert list((config_dir / ".bak").glob("*-presync/config.db"))


def test_backup_is_owner_only_and_consistent(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """req: REQ-BIFROST-034 -- the snapshot is private and actually opens.

    The backup holds provider key material and virtual-key values, so both the
    directory and the file must be owner-only regardless of the process umask.
    It must also be a *usable* database: the gateway runs the store in WAL mode,
    so copying the files by hand can pair a main file with a mismatched WAL and
    yield a snapshot that fails to open -- which reads as a successful backup
    right up until it is needed.
    """
    config_dir = tmp_path / "store"
    config_dir.mkdir()
    template = tmp_path / "template.json"
    template.write_text("{}", encoding="utf-8")
    target = config_dir / "config.json"

    source = config_dir / "config.db"
    with sqlite3.connect(source) as con:
        con.execute("CREATE TABLE governance_virtual_keys (name TEXT, value TEXT)")
        con.execute("INSERT INTO governance_virtual_keys VALUES ('bodai-pi-pool', 'sk-bf-secret')")
        con.commit()
    source.chmod(0o644)

    monkeypatch.setattr(lifecycle, "BIFROST_CONFIG_DIR", config_dir)
    monkeypatch.setattr(lifecycle, "TARGET_CONFIG", target)
    monkeypatch.setattr(lifecycle, "SOURCE_CONFIG", template)

    lifecycle.sync_config()

    backups = list((config_dir / ".bak").glob("*-presync"))
    assert len(backups) == 1
    backup_dir = backups[0]
    assert backup_dir.stat().st_mode & 0o777 == 0o700, "backup dir must be owner-only"

    snapshot = backup_dir / "config.db"
    assert snapshot.stat().st_mode & 0o777 == 0o600, "snapshot must be owner-only"

    # A private backup is useless if it cannot be opened.
    with sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True) as con:
        assert con.execute("SELECT count(*) FROM governance_virtual_keys").fetchone()[0] == 1


def test_backup_survives_a_rough_umask(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A permissive umask must not widen the backup's permissions.

    ``mkdir(mode=0o700)`` is masked by the umask, so the explicit ``chmod``
    is what actually holds the guarantee.
    """
    config_dir = tmp_path / "store"
    config_dir.mkdir()
    template = tmp_path / "template.json"
    template.write_text("{}", encoding="utf-8")
    target = config_dir / "config.json"
    source = config_dir / "config.db"
    with sqlite3.connect(source) as con:
        con.execute("CREATE TABLE t (a TEXT)")
        con.commit()

    monkeypatch.setattr(lifecycle, "BIFROST_CONFIG_DIR", config_dir)
    monkeypatch.setattr(lifecycle, "TARGET_CONFIG", target)
    monkeypatch.setattr(lifecycle, "SOURCE_CONFIG", template)

    original = os.umask(0o000)
    try:
        lifecycle.sync_config()
    finally:
        os.umask(original)

    backup_dir = next((config_dir / ".bak").glob("*-presync"))
    assert backup_dir.stat().st_mode & 0o777 == 0o700
    assert (backup_dir / "config.db").stat().st_mode & 0o777 == 0o600


def test_rebootstrap_does_not_double_delete(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """``rebootstrap`` seeds once, not twice.

    The Typer command used to call ``sync_config()`` and then
    ``rebootstrap()``, which called ``sync_config()`` again -- removing the
    same three files twice and, before the fix, truncating the store twice.
    """
    calls: list[bool] = []
    monkeypatch.setattr(
        lifecycle,
        "sync_config",
        lambda drop_db=False: calls.append(drop_db),
    )
    for name in ("install_plist", "bootout", "kill_listener", "bootstrap"):
        monkeypatch.setattr(lifecycle, name, lambda: None)
    monkeypatch.setattr(lifecycle, "_run", lambda *_a, **_k: None)
    monkeypatch.setattr(lifecycle, "_after_ready", lambda _action: None)
    monkeypatch.setattr(lifecycle.time, "sleep", lambda _s: None)

    lifecycle.rebootstrap()
    assert calls == [False], "rebootstrap must seed exactly once"

    calls.clear()
    lifecycle.rebootstrap(drop_db=True)
    assert calls == [True], "drop_db must be threaded through to sync_config"


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
