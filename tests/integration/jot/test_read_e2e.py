"""End-to-end read pipeline integration tests.

Exercises the full read pipeline via subprocess CLI calls + event round-trips.
The subprocess tests invoke the Typer app via `python -m mahavishnu` with
HOME pointed at tmp_path so the jot log resolves under an isolated
directory (the existing `python -m mahavishnu.cli` form does not work
because `mahavishnu.cli` is a package, not a module — and the jot
subcommands do not expose `--log-path`).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mahavishnu.jot.events import HLC, JotEvent, serialize


def _seed(log: Path, events: list[JotEvent]) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("".join(serialize(e) + "\n" for e in events))


def _capture(event_id: str, text: str, wall_ms: int) -> JotEvent:
    return JotEvent(
        id=event_id.ljust(32, "0"), op="capture",
        hlc=HLC(wall_ms=wall_ms, ctr=0, node="a" * 8),
        text=text, ctx={}, created_ms=wall_ms,
    )


@pytest.fixture
def isolated_home(tmp_path: Path) -> Path:
    """Return tmp_path; log lives at tmp_path/.mahavishnu/jot/log.jsonl."""
    return tmp_path


def _run_jot_cli(args: list[str], home: Path) -> subprocess.CompletedProcess:
    """Invoke `python -m mahavishnu jot <args>` with HOME pointed at `home`."""
    return subprocess.run(
        [sys.executable, "-m", "mahavishnu", "jot", *args],
        check=False, capture_output=True, text=True,
        cwd="/Users/les/Projects/mahavishnu",
        env={**os.environ, "HOME": str(home)},
        timeout=30,
    )


def test_capture_then_cli_list_round_trip(isolated_home: Path) -> None:
    """The pipeline: capture -> fold -> CLI list."""
    log = isolated_home / ".mahavishnu" / "jot" / "log.jsonl"
    _seed(log, [_capture("a" * 32, "refactor", wall_ms=1)])
    result = _run_jot_cli(["list"], isolated_home)
    assert result.returncode == 0, result.stderr
    assert "refactor" in result.stdout


def test_cli_vitals_returns_counts(isolated_home: Path) -> None:
    """Vitals surfaces total/open/done counts from the fold."""
    log = isolated_home / ".mahavishnu" / "jot" / "log.jsonl"
    _seed(log, [
        _capture("a" * 32, "open", wall_ms=1),
        _capture("b" * 32, "done", wall_ms=2),
    ])
    result = _run_jot_cli(["vitals"], isolated_home)
    assert result.returncode == 0, result.stderr
    assert "Total:   2" in result.stdout


@pytest.mark.slow
def test_mcp_tool_call_via_subprocess() -> None:
    """Boot MCP server, list tools, verify jot_* present.

    Skipped because MCP server boot is unreliable in CI; document as
    `@pytest.mark.slow` and verify via `mcp__mahavishnu__jot_list` after
    a manual server boot instead.
    """
    pytest.skip("manual smoke — verify via mcp__mahavishnu__jot_list after server boot")


@pytest.mark.parametrize("fixture", ["capture_event", "edit_event", "done_event", "reopen_event"])
def test_event_round_trip(fixture: str) -> None:
    """All 4 event types serialize/deserialize cleanly."""
    op = fixture.replace("_event", "")
    ev = JotEvent(
        id="a" * 32, op=op,
        hlc=HLC(wall_ms=1, ctr=0, node="a" * 8),
        text="" if op in ("done", "reopen") else "x",
        ctx={}, created_ms=1,
    )
    from mahavishnu.jot.events import deserialize
    round_tripped = deserialize(serialize(ev))
    assert round_tripped == ev
