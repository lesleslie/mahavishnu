"""Tests for ``mahavishnu status`` — the terminal diagnostic subcommand.

Three required cases pin the diagnostic contract:

1. ``test_reports_yaml_and_effective`` — the rendered table must include
   the YAML-declared adapter_preference AND the resolved effective value.
2. ``test_marks_disagreement`` — when the YAML declares tmux but the
   env-var override forces ``mock``, the effective row is marked
   ``[warn]`` so operators see the discrepancy in one glance.
3. ``test_handles_missing_tmux`` — ``shutil.which("tmux")`` returns ``None``
   on systems without tmux; the CLI must not crash and must mark the
   row ``[missing]``.

All tests pin the ``_collect_diagnostic`` helper so the CliRunner only
exercises the Typer shell, not the YAML parser, settings loader, or
``shutil.which`` calls. Mirror of the ``test_reap_cli`` / ``test_spawn_allowlist``
monkeypatch-first pattern.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from mahavishnu import _main_cli as cli_module
from mahavishnu.cli import status_cli
from mahavishnu.workers.contract.record import DurableWorkerRecord

if TYPE_CHECKING:
    from mahavishnu.workers.contract.state import WorkerLifecycleState
    import pathlib
    import datetime as dt

    import pytest


runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fake_settings(
    *,
    adapter_preference: str,
    socket_dir: pathlib.Path | None = None,
) -> MagicMock:
    """Return a ``MahavishnuSettings``-shaped MagicMock with the chosen adapter.

    The CLI only reads ``settings.terminal.adapter_preference`` and
    ``settings.terminal.socket_dir`` (the latter via ``getattr`` so it
    tolerates missing). A MagicMock covers both without needing the real
    Oneiric loader chain.
    """
    settings = MagicMock()
    settings.terminal.adapter_preference = adapter_preference
    if socket_dir is None:
        # Drop the attribute entirely to exercise the ``getattr`` fallback
        # in ``_resolve_socket_dir``; the CLI must NOT crash when the
        # settings shape does not expose a socket_dir field.
        del settings.terminal.socket_dir
    else:
        settings.terminal.socket_dir = socket_dir
    return settings


def _fake_record(
    worker_id: str,
    state: WorkerLifecycleState,
    *,
    created_at: "dt.datetime | None" = None,
) -> DurableWorkerRecord:
    """Build a ``DurableWorkerRecord`` for store mocking."""
    import datetime as dt

    now = created_at or dt.datetime.now(dt.UTC)
    return DurableWorkerRecord(
        worker_id=worker_id,
        worker_type="terminal-claude",
        backend="claude_tui",
        tmux=None,
        state=state,
        created_at=now,
        last_seen_at=now,
    )


def _fake_store(*records: DurableWorkerRecord) -> MagicMock:
    """Build a ``WorkerRecordStore`` MagicMock whose ``list_all()`` yields records."""
    store = MagicMock()
    store.list_all.return_value = iter(records)
    return store


@pytest.fixture
def _stub_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    """Wire a stub diagnostic for the CLI without touching the filesystem.

    Returns a dict so individual tests can override individual slots
    (e.g. a fresh ``fake_store`` with a different record set).
    """

    state: dict[str, object] = {
        "settings": _fake_settings(adapter_preference="tmux"),
        "yaml_value": "tmux",
        "env_value": None,
        "store": _fake_store(),
        "tmux_path": "/usr/local/bin/tmux",
        "claude_path": "/usr/local/bin/claude",
    }

    monkeypatch.setattr(status_cli, "_load_settings", lambda: state["settings"])
    monkeypatch.setattr(status_cli, "_yaml_adapter_value", lambda path=None: state["yaml_value"])
    monkeypatch.setattr(status_cli, "_env_adapter_value", lambda env_key=None: state["env_value"])
    monkeypatch.setattr(status_cli, "_worker_record_store", lambda: state["store"])

    # Rebuild the rows inside ``_collect_diagnostic`` using the injected
    # ``tmux_which`` / ``claude_which`` callables. The current shape of
    # ``_collect_diagnostic`` reads these from parameters, not globals.
    return state


def _invoke_status() -> object:
    """Invoke the ``mahavishnu status`` Typer command via CliRunner."""
    return runner.invoke(cli_module.app, ["status"])


# ---------------------------------------------------------------------------
# Required tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_reports_yaml_and_effective(
    _stub_diagnostic: dict[str, object],
) -> None:
    """YAML-declared and effective values both appear in the output."""
    state = _stub_diagnostic
    state["yaml_value"] = "tmux"
    state["env_value"] = None
    state["settings"] = _fake_settings(adapter_preference="tmux")  # agrees with YAML

    result = _invoke_status()

    assert result.exit_code == 0, (
        f"expected clean exit, got {result.exit_code}\n"
        f"output={result.output!r}\n"
        f"stderr={getattr(result, 'stderr', '') or ''!r}"
    )
    combined = (result.output or "") + (getattr(result, "stderr", "") or "")

    # The YAML-declared row is present (formatted as repr()).
    assert "'tmux'" in combined, (
        "expected YAML-declared value 'tmux' in status output; "
        f"got: {combined!r}"
    )
    assert "YAML declared adapter_preference" in combined
    # The effective-resolved row is present.
    assert "Effective adapter_preference" in combined
    # All nine rows surface under their canonical labels.
    for label in (
        "Pydantic default adapter_preference",
        "Env override",
        "tmux binary",
        "claude binary (shell PATH)",
        "socket_dir",
        "Live workers (state != reaped)",
        "Reaped workers",
    ):
        assert label in combined, f"missing diagnostic row '{label}': {combined!r}"


@pytest.mark.unit
def test_marks_disagreement(
    _stub_diagnostic: dict[str, object],
) -> None:
    """YAML says tmux, env says mock → effective row marked [warn].

    The Pydantic default + YAML declaration are stable (``mock`` and
    ``tmux`` respectively). The env override forces ``mock``. With no
    other overrides applied, the resolved effective value falls back to
    whatever the settings layer composes — here we explicitly make the
    effective value ``mock`` so the disagreement surfaces as
    ``[warn]`` on the effective row.
    """
    state = _stub_diagnostic
    state["yaml_value"] = "tmux"
    state["env_value"] = "mock"
    state["settings"] = _fake_settings(adapter_preference="mock")  # disagrees with YAML

    result = _invoke_status()

    assert result.exit_code == 0, (
        f"expected clean exit, got {result.exit_code}\n"
        f"output={result.output!r}"
    )
    combined = (result.output or "") + (getattr(result, "stderr", "") or "")

    # The YAML declaration is still printed verbatim.
    assert "YAML declared adapter_preference" in combined
    assert "'tmux'" in combined
    # The env override surfaces too — operators need to see what force-set it.
    assert "Env override" in combined
    assert "'mock'" in combined
    # The effective row carries the [warn] marker when YAML disagrees.
    # Walk the rows so a stray ``[warn]`` on a different row cannot
    # satisfy the assertion by coincidence.
    effective_line = next(
        (line for line in combined.splitlines() if "Effective adapter_preference" in line),
        None,
    )
    assert effective_line is not None, (
        f"could not find effective row in output: {combined!r}"
    )
    assert status_cli.MARK_WARN in effective_line, (
        f"expected [warn] marker on effective row, got: {effective_line!r}"
    )
    assert status_cli.MARK_OK not in effective_line.split("Effective")[0], (
        f"effective row should not also carry [ok]; got: {effective_line!r}"
    )


@pytest.mark.unit
def test_handles_missing_tmux(
    _stub_diagnostic: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``shutil.which('tmux')`` returns ``None`` → tmux row marked [missing], no crash.

    We pass an explicit ``tmux_which`` callable that returns ``None`` so
    the production ``shutil.which`` is never invoked. ``claude_which``
    remains the same to make sure one missing binary does not poison the
    rest of the diagnostic.
    """
    import shutil

    # Bind the real ``shutil.which`` BEFORE the monkeypatch so the
    # fallback branch in our fake does not recurse through the patched
    # module attribute.
    real_which = shutil.which

    def _fake_which(name: str, *args: object, **kwargs: object) -> str | None:
        if name == "tmux":
            return None
        return real_which(name)

    # ``_collect_diagnostic`` reads ``tmux_which`` / ``claude_which`` as
    # function-local names captured at module-import time. Patch the
    # module-level ``shutil`` reference so the ``shutil.which`` lookup
    # inside ``_collect_diagnostic`` returns our fake. ``real_which``
    # above is bound by closure to the pre-patch stdlib function.
    monkeypatch.setattr(status_cli, "shutil", type("S", (), {"which": _fake_which}))

    result = runner.invoke(cli_module.app, ["status"])

    assert result.exit_code == 0, (
        f"expected clean exit even with missing tmux, got {result.exit_code}\n"
        f"output={result.output!r}"
    )
    combined = (result.output or "") + (getattr(result, "stderr", "") or "")

    # The tmux row is present and carries the [missing] marker.
    tmux_line = next(
        (line for line in combined.splitlines() if "tmux binary" in line),
        None,
    )
    assert tmux_line is not None, f"could not find tmux row in output: {combined!r}"
    assert status_cli.MARK_MISSING in tmux_line, (
        f"expected [missing] marker on tmux row, got: {tmux_line!r}"
    )
    # The "not on PATH" placeholder text surfaces so operators know
    # what absence looks like in the table.
    assert "<not on PATH>" in tmux_line, (
        f"expected <not on PATH> placeholder when tmux missing, got: {tmux_line!r}"
    )
    # The claude row still passes — one missing binary must not
    # poison the rest of the diagnostic. The fake delegates non-tmux
    # names to the real ``shutil.which``, so the path here is whatever
    # the test environment has on PATH; we only assert the row is
    # marked ``[ok]`` and contains a non-empty path (i.e. NOT the
    # ``<not on PATH>`` placeholder).
    claude_line = next(
        (line for line in combined.splitlines() if "claude binary" in line),
        None,
    )
    assert claude_line is not None
    assert status_cli.MARK_OK in claude_line
    assert "<not on PATH>" not in claude_line, (
        f"claude row should not be marked missing when only tmux is missing: {claude_line!r}"
    )
    # Path component is non-empty (anything after the label column).
    _, _, after_label = claude_line.partition("claude binary (shell PATH)")
    assert after_label.strip(), (
        f"claude row should carry a resolved path, got empty tail: {claude_line!r}"
    )
