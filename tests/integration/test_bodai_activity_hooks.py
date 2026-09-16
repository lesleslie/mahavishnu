"""Integration tests for the PostToolUse hook (Phase 12a Task 5 path).

The pre-Task-5 pipeline (SessionStart spawns a daemon that subscribes
to the bus and writes to a JSON queue; PostToolUse drains the queue)
is retired. The current contract is:

  bridge producers → Oneiric bus (Redis Streams)
                       ↓
  PostToolUse hook (one-shot XREAD via ``read_bodai_events_since``)

These tests exercise the hook end-to-end against the actual script
(with env-var overrides so filesystem isolation is preserved
per-test) and mock the bus read so no live Redis instance is needed.

Marker: ``integration`` per ``CLAUDE.md`` Test conventions.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
import uuid

import pytest

HOOKS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "hooks"
POST_TOOL_USE_HOOK = HOOKS_DIR / "bodai-activity-post-tool-use.py"


def _load_module(path: Path) -> Any:
    """Import a hook script via importlib under a uniquely-named module."""
    unique = f"bodai_hook_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(unique, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load hook spec from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ptu_state_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Wire MAHAVISHNU_BODAI_POST_TOOL_USE_STATE_PATH to a fresh tmp file."""
    monkeypatch.delenv("MAHAVISHNU_HOME", raising=False)
    monkeypatch.delenv("MAHAVISHNU_BODAI_QUEUE_PATH", raising=False)
    state = tmp_path / "bodai-post-tool-use-state.json"
    monkeypatch.setenv(
        "MAHAVISHNU_BODAI_POST_TOOL_USE_STATE_PATH", str(state)
    )
    return state


@pytest.fixture
def post_tool_use_module(
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """Load bodai-activity-post-tool-use.py with a clean MAHAVISHNU_BODAI_* env."""
    for key in (
        "MAHAVISHNU_HOME",
        "MAHAVISHNU_BODAI_POST_TOOL_USE_STATE_PATH",
        "MAHAVISHNU_BODAI_DEBUG",
        "MAHAVISHNU_BODAI_REDIS_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    return _load_module(POST_TOOL_USE_HOOK)


@pytest.fixture
def bus_mock(monkeypatch: pytest.MonkeyPatch) -> list[list[tuple[str, dict[str, Any]]]]:
    """Replace the lazy ``read_bodai_events_since`` import target.

    Returns a list of pre-seeded envelope batches. Each batch is a
    list of ``(message_id, envelope_dict)`` tuples. The mock pops one
    batch per call. Empty list = "no envelopes available" (default).
    """
    batches: list[list[tuple[str, dict[str, Any]]]] = []

    async def fake_read(*_args: Any, **_kwargs: Any) -> list[tuple[str, dict[str, Any]]]:
        if not batches:
            return []
        return batches.pop(0)

    monkeypatch.setattr(
        "mahavishnu.core.events.bodai_subscriber.read_bodai_events_since",
        fake_read,
    )
    return batches


def _envelope(
    *,
    topic: str,
    source: str,
    msg_id: str,
    payload: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build a canonical envelope with required headers populated."""
    return msg_id, {
        "topic": topic,
        "payload": payload or {},
        "headers": {
            "source": source,
            "event_id": f"evt_{msg_id}",
            "version": "1.0.0",
            "timestamp": "2026-01-15T10:00:00+00:00",
        },
    }


# ---------------------------------------------------------------------------
# Test: PostToolUse surfaces one-line summaries from each allowed source
# ---------------------------------------------------------------------------


def test_post_tool_use_emits_recent_events(
    post_tool_use_module: Any,
    ptu_state_path: Path,
    bus_mock: list[list[tuple[str, dict[str, Any]]]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """3 envelopes (one per Bodai component) plus 1 unknown-source envelope
    → emit 3 lines, skip the unknown (forward-compatibility)."""
    bus_mock.append(
        [
            _envelope(
                topic="workflow.completed",
                source="mahavishnu",
                msg_id="1737120000001-0",
                payload={"workflow_id": "wid_abc", "status": "success"},
            ),
            _envelope(
                topic="aggregation_completed",
                source="akosha",
                msg_id="1737120000002-0",
                payload={"suite": "quality"},
            ),
            _envelope(
                topic="test_run_completed",
                source="crackerjack",
                msg_id="1737120000003-0",
                payload={"passed": 42, "failed": 0},
            ),
            _envelope(
                topic="unknown_event",
                source="future-component",
                msg_id="1737120000004-0",
                payload={"foo": "bar"},
            ),
        ]
    )

    rc = post_tool_use_module._post_tool_use()
    assert rc == 0

    captured = capsys.readouterr().out
    # Payload keys are alphabetically sorted in the summary format.
    assert "[mahavishnu] workflow.completed status=success workflow_id=wid_abc" in captured
    assert "[akosha] aggregation_completed suite=quality" in captured
    assert "[crackerjack] test_run_completed failed=0 passed=42" in captured
    assert "[future-component]" not in captured

    # Cursor advances to the max message_id seen (including skipped).
    assert ptu_state_path.exists()
    state = json.loads(ptu_state_path.read_text())
    assert state["last_message_id"] == "1737120000004-0"


# ---------------------------------------------------------------------------
# Test: PostToolUse only emits events newer than the cursor (across calls)
# ---------------------------------------------------------------------------


def test_post_tool_use_only_emits_new_events(
    post_tool_use_module: Any,
    ptu_state_path: Path,
    bus_mock: list[list[tuple[str, dict[str, Any]]]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Two successive calls: first emits everything, second emits nothing."""
    bus_mock.append(
        [
            _envelope(
                topic="workflow.completed",
                source="mahavishnu",
                msg_id="1737120000010-0",
                payload={"workflow_id": "wid_xyz"},
            ),
            _envelope(
                topic="test_run_completed",
                source="crackerjack",
                msg_id="1737120000011-0",
                payload={"passed": 10, "failed": 0},
            ),
        ]
    )

    rc1 = post_tool_use_module._post_tool_use()
    assert rc1 == 0
    first_out = capsys.readouterr().out
    assert "[mahavishnu] workflow.completed workflow_id=wid_xyz" in first_out
    assert "[crackerjack] test_run_completed failed=0 passed=10" in first_out

    # Second call: bus returns nothing new (cursor caught up).
    rc2 = post_tool_use_module._post_tool_use()
    assert rc2 == 0
    second_out = capsys.readouterr().out
    assert second_out == ""


# ---------------------------------------------------------------------------
# Test: Bus read failure does NOT block tool execution (hook contract)
# ---------------------------------------------------------------------------


def test_post_tool_use_bus_read_failure_exits_zero(
    post_tool_use_module: Any,
    ptu_state_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Redis unreachable → log to stderr + exit 0 (spec §4.13.3 fire-and-forget)."""

    async def exploding(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(
        "mahavishnu.core.events.bodai_subscriber.read_bodai_events_since",
        exploding,
    )
    rc = post_tool_use_module._post_tool_use()
    assert rc == 0
    captured = capsys.readouterr()
    assert "bus read failed" in captured.err
    assert "redis unavailable" in captured.err


# ---------------------------------------------------------------------------
# Test: CLI entry point smoke test — hook is executable and exits 0
# ---------------------------------------------------------------------------


def test_post_tool_use_hook_cli_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Smoke-test the post-tool-use hook with a fresh empty environment.

    The bus read will fail (no Redis, no coredis client_factory),
    but the hook contract is fire-and-forget — exit 0 with stderr log.
    """
    ptu_state = tmp_path / "bodai-post-tool-use-state.json"
    monkeypatch.setenv(
        "MAHAVISHNU_BODAI_POST_TOOL_USE_STATE_PATH", str(ptu_state)
    )
    result = subprocess.run(
        [sys.executable, str(POST_TOOL_USE_HOOK)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"hook should exit 0; got {result.returncode}\n"
        f"stderr={result.stderr}"
    )
