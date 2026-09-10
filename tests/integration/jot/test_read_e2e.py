"""End-to-end read pipeline integration tests.

Exercises the full read pipeline via subprocess CLI calls + event round-trips.
The subprocess tests invoke the Typer app via `python -m mahavishnu` with
HOME pointed at tmp_path so the jot log resolves under an isolated
directory (the existing `python -m mahavishnu.cli` form does not work
because `mahavishnu.cli` is a package, not a module — and the jot
subcommands do not expose `--log-path`).

The subprocess env is a strict whitelist (HOME + PATH + PYTHONPATH) so
host-set vars like MAHAVISHNU_LOG_PATH / XDG_CONFIG_HOME cannot mask the
HOME redirect.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from mahavishnu.jot.events import HLC, JotEvent, serialize

# Repo root derived from this file: tests/integration/jot/ -> tests/integration/
# -> tests/ -> <repo_root>. Avoids hardcoding `/Users/les/Projects/mahavishnu`
# so the suite is portable to CI, worktrees, and other developers.
REPO_ROOT = Path(__file__).resolve().parents[3]


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


def _subprocess_env(home: Path) -> dict[str, str]:
    """Whitelist the env so host vars cannot mask the HOME redirect."""
    return {
        "HOME": str(home),
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(REPO_ROOT),
    }


def _run_jot_cli(args: list[str], home: Path) -> subprocess.CompletedProcess:
    """Invoke `python -m mahavishnu jot <args>` with HOME pointed at `home`."""
    return subprocess.run(
        [sys.executable, "-m", "mahavishnu", "jot", *args],
        check=False, capture_output=True, text=True,
        cwd=str(REPO_ROOT),
        env=_subprocess_env(home),
        timeout=30,
    )


def _assert_resolved_log(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sanity check: confirm `paths.log_path()` actually resolves under HOME.

    Pins the convention so future refactors of `paths.log_path()` that drift
    away from `~/.mahavishnu/jot/log.jsonl` fail loudly instead of silently
    masking the HOME redirect.
    """
    expected_log = home / ".mahavishnu" / "jot" / "log.jsonl"
    from mahavishnu.jot import paths as paths_module

    paths_module._jot_dir_cache = None
    monkeypatch.setattr(Path, "home", lambda: home)
    resolved = paths_module.log_path()
    assert resolved == expected_log, f"log_path drifted: {resolved} != {expected_log}"


def test_capture_then_cli_list_round_trip(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pipeline: capture -> fold -> CLI list."""
    _assert_resolved_log(isolated_home, monkeypatch)
    log = isolated_home / ".mahavishnu" / "jot" / "log.jsonl"
    _seed(log, [_capture("a" * 32, "refactor", wall_ms=1)])
    result = _run_jot_cli(["list"], isolated_home)
    assert result.returncode == 0, result.stderr
    assert "refactor" in result.stdout


def test_cli_vitals_returns_counts(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vitals surfaces total/open/done counts from the fold."""
    _assert_resolved_log(isolated_home, monkeypatch)
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
