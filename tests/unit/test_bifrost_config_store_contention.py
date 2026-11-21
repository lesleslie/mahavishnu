"""Tests for the config-store contention counter.

req: REQ-BIFROST-050

Bifrost's background jobs write to the config store with no busy timeout, so
a writer that cannot take the lock fails immediately. The failure is invisible
from the gateway's own surface -- ``/health`` reports ``db_pings: ok``
because a ping tests connectivity and not contention -- so the fleet reads it
from the gateway's stderr, which is the only place it is recorded.

See ``docs/decisions/2026-11-20-bifrost-config-store-lock-contention.md``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from mahavishnu.bifrost import gateway

if TYPE_CHECKING:
    from pathlib import Path


def _line(when: str, message: str) -> str:
    return json.dumps({"level": "error", "time": when, "message": message}) + "\n"


@pytest.fixture
def _log(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the counter at a scratch log."""
    log = tmp_path / "bifrost.err"
    monkeypatch.setattr(gateway, "LOG_ERR", log)
    return log


def test_a_clean_log_reports_no_contention(_log: Path) -> None:
    """The ordinary case reads as zero, not as an error."""
    _log.write_text(
        _line("2026-11-20T10:00:00-08:00", "request completed")
        + _line("2026-11-20T10:00:01-08:00", "tracing: transport never handed off"),
        encoding="utf-8",
    )

    assert gateway.config_store_contention() == (0, None)


def test_a_missing_log_reports_no_contention(_log: Path) -> None:
    """A gateway that has not started yet has no contention to report."""
    assert not _log.exists()

    assert gateway.config_store_contention() == (0, None)


def test_the_failures_are_counted_and_the_latest_is_named(_log: Path) -> None:
    """The count answers "how bad", the timestamp answers "is it still happening"."""
    _log.write_text(
        _line(
            "2026-11-20T10:00:00-08:00",
            "per-user OAuth flow sweep failed: failed to delete expired oauth "
            "flows: database is locked",
        )
        + _line(
            "2026-11-20T11:30:00-08:00",
            "temp-token sweep failed: temptoken: delete expired failed: "
            "database is locked",
        )
        + _line("2026-11-20T11:31:00-08:00", "request completed"),
        encoding="utf-8",
    )

    count, latest = gateway.config_store_contention()

    assert count == 2
    assert latest == "2026-11-20T11:30:00-08:00"


def test_failures_older_than_the_window_are_not_counted(_log: Path) -> None:
    """A month-old failure is history, not a live condition.

    Without the window the count would only ever grow, and a number that only
    grows is a number nobody reads.
    """
    _log.write_text(
        _line(
            "2026-08-29T04:22:11-07:00",
            "per-user OAuth flow sweep failed: database is locked",
        ),
        encoding="utf-8",
    )

    assert gateway.config_store_contention(window_hours=24) == (0, None)


def test_a_malformed_line_does_not_break_the_count(_log: Path) -> None:
    """The log carries plain-text lines as well as JSON.

    The launcher's own failure output is not JSON, and the counter reads the
    tail of the file, where a partial line can start.
    """
    _log.write_text(
        "❌ Failed to start Bifrost. Error: spawnSync ... EACCES\n"
        + _line(
            "2026-11-20T11:30:00-08:00",
            "temp-token sweep failed: database is locked",
        ),
        encoding="utf-8",
    )

    count, _latest = gateway.config_store_contention()

    assert count == 1


def test_the_window_is_honoured(_log: Path) -> None:
    """A wider window counts the older failures too."""
    _log.write_text(
        _line(
            "2026-11-19T04:22:11-08:00",
            "temp-token sweep failed: database is locked",
        ),
        encoding="utf-8",
    )

    assert gateway.config_store_contention(window_hours=24)[0] == 0
    assert gateway.config_store_contention(window_hours=72)[0] == 1


def test_only_the_tail_of_a_large_log_is_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The log grows without bound, so the counter reads from the end.

    The file here is 12.6 MB and the gateway appends to it for the life of
    the deployment. Reading all of it on every status call would make the
    status command slower the longer the gateway had been up.
    """
    log = tmp_path / "bifrost.err"
    monkeypatch.setattr(gateway, "LOG_ERR", log)
    monkeypatch.setattr(gateway, "CONTENTION_TAIL_BYTES", 4096)

    with log.open("w", encoding="utf-8") as handle:
        for index in range(500):
            handle.write(_line("2026-11-20T10:00:00-08:00", f"filler {index}"))
        handle.write(
            _line(
                "2026-11-20T11:30:00-08:00",
                "temp-token sweep failed: database is locked",
            )
        )

    count, latest = gateway.config_store_contention()

    assert count == 1
    assert latest == "2026-11-20T11:30:00-08:00"
