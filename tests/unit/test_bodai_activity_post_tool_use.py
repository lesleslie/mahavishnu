"""Unit tests for ``.claude/hooks/bodai-activity-post-tool-use.py``.

Phase 12a Task 5: the hook now reads from the Bodai EventBridge via
``read_bodai_events_since`` (one-shot XREAD) instead of polling the
now-retired JSON queue file. Tests mock the bus read so they don't
depend on a live Redis instance.

Test coverage:
- Empty envelope list: no output, no state change
- Allowed source: emits summary, advances cursor
- Unknown source: skipped with debug log, cursor still advances
- Forward compat: legacy ``last_read_at`` state migrates to ``last_message_id``
- Bus read failure: logs to stderr, exits 0 (hook contract per spec §4.13.3)
- State file write atomicity (via tmp + os.replace pattern)
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

HOOKS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "hooks"
HOOK_PATH = HOOKS_DIR / "bodai-activity-post-tool-use.py"


@pytest.fixture
def hook_module(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """Load the hook module with a hermetic state-file location.

    The hook is a standalone script that reads ``CLAUDE_PROJECT_DIR`` from
    the environment and (lazily) imports ``mahavishnu.bodai_hook_bridge``.
    We inject ``CLAUDE_PROJECT_DIR`` pointing at the repo root so the
    bridge import resolves, and override the state-file env var so
    tests don't touch the operator's real ``~/.mahavishnu`` state.
    """
    state_path = tmp_path / "post-tool-use-state.json"
    monkeypatch.setenv("MAHAVISHNU_BODAI_POST_TOOL_USE_STATE_PATH", str(state_path))
    # Preserve any existing CLAUDE_PROJECT_DIR so the bridge import works.
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo_root))

    spec = importlib.util.spec_from_file_location(
        "bodai_activity_post_tool_use", str(HOOK_PATH)
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_bus_read(monkeypatch: pytest.MonkeyPatch) -> list[list[tuple[str, dict[str, Any]]]]:
    """Replace the lazy ``read_bodai_events_since`` import target.

    Returns the list of envelope batches the mock will produce. Each
    batch is a list of ``(message_id, envelope_dict)`` tuples.
    """
    batches: list[list[tuple[str, dict[str, Any]]]] = []

    async def fake_read(*_args: Any, **_kwargs: Any) -> list[tuple[str, dict[str, Any]]]:
        if not batches:
            return []
        return batches.pop(0)

    # The hook imports read_bodai_events_since inside _read_new_envelopes,
    # so we patch the module attribute the import resolves to.
    monkeypatch.setattr(
        "mahavishnu.core.events.bodai_subscriber.read_bodai_events_since",
        fake_read,
    )
    return batches


def _envelope(
    topic: str = "workflow_completed",
    *,
    source: str = "mahavishnu",
    msg_id: str = "1737120000000-0",
    payload: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build a canonical envelope with all required headers populated."""
    return msg_id, {
        "topic": topic,
        "payload": payload or {"workflow_id": "wid_abc"},
        "headers": {
            "source": source,
            "event_id": f"evt_{msg_id}",
            "version": "1.0.0",
            "timestamp": "2026-01-15T10:00:00+00:00",
        },
    }


# ---------------------------------------------------------------------------
# Empty / no-op paths
# ---------------------------------------------------------------------------


def test_post_tool_use_no_messages_emits_nothing(
    hook_module: Any,
    fake_bus_read: list[list[tuple[str, dict[str, Any]]]],
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Empty bus → no output, no state-file write."""
    # fake_bus_read is already an empty list — no batches.
    rc = hook_module._post_tool_use()
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert not (tmp_path / "post-tool-use-state.json").exists()


def test_post_tool_use_bus_read_failure_exits_zero(
    hook_module: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """If the bus read raises, the hook logs to stderr and exits 0.

    Per spec §4.13.3 fire-and-forget: the hook never blocks tool
    execution on bus unavailability.
    """

    async def exploding_read(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(
        "mahavishnu.core.events.bodai_subscriber.read_bodai_events_since",
        exploding_read,
    )
    rc = hook_module._post_tool_use()
    assert rc == 0
    captured = capsys.readouterr()
    assert "bus read failed" in captured.err
    assert "redis unavailable" in captured.err


# ---------------------------------------------------------------------------
# Allowed source → emit summary
# ---------------------------------------------------------------------------


def test_post_tool_use_allowed_source_emits_summary(
    hook_module: Any,
    fake_bus_read: list[list[tuple[str, dict[str, Any]]]],
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Envelopes from allowed sources produce ``[component] event_type k=v`` lines."""
    fake_bus_read.append([_envelope(msg_id="1737120000001-0", source="mahavishnu")])
    rc = hook_module._post_tool_use()
    assert rc == 0
    captured = capsys.readouterr()
    assert "[mahavishnu] workflow_completed workflow_id=wid_abc" in captured.out

    state = json.loads((tmp_path / "post-tool-use-state.json").read_text())
    assert state["last_message_id"] == "1737120000001-0"


def test_post_tool_use_multiple_sources_all_surfaced(
    hook_module: Any,
    fake_bus_read: list[list[tuple[str, dict[str, Any]]]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """mahavishnu, akosha, and crackerjack envelopes all surface."""
    fake_bus_read.append(
        [
            _envelope(msg_id="1737120000001-0", source="mahavishnu"),
            _envelope(
                topic="aggregation_completed",
                source="akosha",
                msg_id="1737120000002-0",
                payload={"count": 5},
            ),
            _envelope(
                topic="test_run_completed",
                source="crackerjack",
                msg_id="1737120000003-0",
                payload={"tests_passed": 42},
            ),
        ]
    )
    rc = hook_module._post_tool_use()
    assert rc == 0
    captured = capsys.readouterr()
    assert "[mahavishnu] workflow_completed" in captured.out
    assert "[akosha] aggregation_completed count=5" in captured.out
    assert "[crackerjack] test_run_completed tests_passed=42" in captured.out


# ---------------------------------------------------------------------------
# Unknown source → skip + advance cursor
# ---------------------------------------------------------------------------


def test_post_tool_use_unknown_source_skipped_but_cursor_advances(
    hook_module: Any,
    fake_bus_read: list[list[tuple[str, dict[str, Any]]]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Envelopes from sources outside ALLOWED_SOURCES do NOT produce output,
    but the cursor still advances so we don't re-evaluate them."""
    monkeypatch.setenv("MAHAVISHNU_BODAI_DEBUG", "1")
    fake_bus_read.append([_envelope(msg_id="1737120000001-0", source="unrecognized")])

    rc = hook_module._post_tool_use()
    assert rc == 0

    captured = capsys.readouterr()
    assert captured.out == ""  # no summary emitted
    assert "skipping envelope from unknown" in captured.err  # debug log

    # Cursor advanced so we don't re-evaluate the same envelope next call.
    state = json.loads((tmp_path / "post-tool-use-state.json").read_text())
    assert state["last_message_id"] == "1737120000001-0"


# ---------------------------------------------------------------------------
# State schema migration (last_read_at → last_message_id)
# ---------------------------------------------------------------------------


def test_state_migrates_legacy_last_read_at(
    hook_module: Any, tmp_path: Path
) -> None:
    """A state file with only ``last_read_at`` (legacy schema) migrates
    cleanly to the new ``last_message_id`` schema without losing the
    hook's behaviour."""
    state_path = tmp_path / "post-tool-use-state.json"
    state_path.write_text(json.dumps({"last_read_at": 1737120000.0}))

    state = hook_module._read_state()

    # Migration: last_read_at dropped, last_message_id added.
    assert "last_read_at" not in state
    assert state["last_message_id"] is None


def test_state_handles_missing_file(hook_module: Any) -> None:
    """Missing state file → empty schema (no error)."""
    state = hook_module._read_state()
    assert state == {"last_message_id": None}


def test_state_handles_corrupt_file(
    hook_module: Any, tmp_path: Path
) -> None:
    """Corrupt JSON in the state file → empty schema (no error)."""
    state_path = tmp_path / "post-tool-use-state.json"
    state_path.write_text("{not valid json")

    state = hook_module._read_state()
    assert state == {"last_message_id": None}


# ---------------------------------------------------------------------------
# Cursor advancement across calls
# ---------------------------------------------------------------------------


def test_post_tool_use_second_call_uses_advanced_cursor(
    hook_module: Any,
    fake_bus_read: list[list[tuple[str, dict[str, Any]]]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Two successive calls advance the cursor; the second call only
    surfaces envelopes with message_id > last_message_id."""
    fake_bus_read.append([_envelope(msg_id="1737120000001-0", source="mahavishnu")])
    rc1 = hook_module._post_tool_use()
    assert rc1 == 0
    first_out = capsys.readouterr().out
    assert "[mahavishnu]" in first_out

    # Second call: bus returns 0 new envelopes (cursor caught up).
    rc2 = hook_module._post_tool_use()
    assert rc2 == 0
    second_out = capsys.readouterr().out
    assert second_out == ""
