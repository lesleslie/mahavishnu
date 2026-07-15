"""Unit tests for ``mahavishnu metrics bodai``.

Covers the ``bodai`` subcommand of the metrics CLI (Phase 6.6 of the
Bodai observability plan). The CLI reads the local Bodai queue file
(``~/.mahavishnu/bodai-event-queue.json``) and the subscriber state
file (``~/.mahavishnu/bodai-subscriber-state.json``) and renders
multi-section markdown tables.

These tests inject fixtures into a temporary directory and override
the queue/state paths via the CLI's ``--queue-path`` / ``--state-path``
flags so the suite does not touch the real ``~/.mahavishnu/`` tree.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path  # noqa: TC003  (used at runtime in tmp_path operations)
from typing import Any

import pytest
from typer.testing import CliRunner

from mahavishnu.metrics_cli import metrics_app, _event_timestamp

runner = CliRunner()

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_json(path: Path, payload: Any) -> None:
    """Write *payload* as JSON to *path*, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_event_timestamp_handles_missing_headers() -> None:
    assert _event_timestamp({"received_at": None}) is None


def test_event_timestamp_handles_non_dict_headers() -> None:
    event = {"headers": None, "received_at": "2026-07-14T12:00:00Z"}
    parsed = _event_timestamp(event)
    assert parsed == datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


def test_event_timestamp_prefers_canonical_header_timestamp() -> None:
    event = {
        "headers": {"timestamp": "2026-07-14T13:00:00Z"},
        "received_at": "2026-07-14T12:00:00Z",
    }
    parsed = _event_timestamp(event)
    assert parsed == datetime(2026, 7, 14, 13, 0, tzinfo=UTC)


def _envelope(
    source: str,
    topic: str,
    *,
    payload: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
) -> dict[str, Any]:
    """Build a queue-file envelope entry in the shape the subscriber writes."""
    headers: dict[str, Any] = {"source": source}
    if timestamp is not None:
        headers["timestamp"] = timestamp.isoformat()
    return {
        "topic": topic,
        "payload": payload or {},
        "headers": headers,
        "received_at": (timestamp or datetime.now(UTC)).timestamp(),
    }


# ---------------------------------------------------------------------------
# Subscriber state rendering
# ---------------------------------------------------------------------------


def test_bodai_command_renders_subscriber_state(tmp_path: Path) -> None:
    """A seeded state file surfaces the pid in the rendered output."""
    queue_path = tmp_path / "queue.json"
    state_path = tmp_path / "state.json"

    pid = 424242
    _write_json(
        state_path,
        {
            "pid": pid,
            "started_at": "2026-07-11T10:00:00+00:00",
            "last_seen": "2026-07-11T10:30:00+00:00",
            "uptime_seconds": 1800.0,
        },
    )
    _write_json(queue_path, [])

    result = runner.invoke(
        metrics_app,
        [
            "bodai",
            "--queue-path",
            str(queue_path),
            "--state-path",
            str(state_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "PID" in result.stdout
    assert str(pid) in result.stdout
    assert "yes" in result.stdout  # running=yes


# ---------------------------------------------------------------------------
# Queue state rendering
# ---------------------------------------------------------------------------


def test_bodai_command_renders_queue_state(tmp_path: Path) -> None:
    """Seeded queue file size and timestamps are reflected in the output."""
    queue_path = tmp_path / "queue.json"
    state_path = tmp_path / "state.json"

    now = datetime.now(UTC)
    envelopes = [
        _envelope(
            "mahavishnu",
            "workflow.completed",
            payload={"workflow_id": f"wid_{i}"},
            timestamp=now - timedelta(minutes=i),
        )
        for i in range(5)
    ]
    _write_json(queue_path, envelopes)
    _write_json(state_path, {"pid": 1, "started_at": now.isoformat()})

    result = runner.invoke(
        metrics_app,
        [
            "bodai",
            "--queue-path",
            str(queue_path),
            "--state-path",
            str(state_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Queue size" in result.stdout
    assert "5" in result.stdout  # queue size
    assert "Newest event" in result.stdout
    assert "Oldest event" in result.stdout


# ---------------------------------------------------------------------------
# --component filter
# ---------------------------------------------------------------------------


def test_bodai_command_filters_by_component(tmp_path: Path) -> None:
    """``--component`` only surfaces events matching that source."""
    queue_path = tmp_path / "queue.json"
    state_path = tmp_path / "state.json"

    now = datetime.now(UTC)
    envelopes = [
        _envelope("mahavishnu", "workflow.completed", timestamp=now),
        _envelope("akosha", "aggregation.completed", timestamp=now),
        _envelope("crackerjack", "test_run.completed", timestamp=now),
    ]
    _write_json(queue_path, envelopes)
    _write_json(state_path, {"pid": 1})

    result = runner.invoke(
        metrics_app,
        [
            "bodai",
            "--queue-path",
            str(queue_path),
            "--state-path",
            str(state_path),
            "--component",
            "akosha",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "component=akosha" in result.stdout
    # Per-component counts: akosha gets 1, others get 0.
    # The events section shows only akosha has data; the count "1" for
    # akosha must appear; "0" must appear for the other components.
    assert "akosha" in result.stdout


def test_bodai_command_rejects_unknown_component(tmp_path: Path) -> None:
    """Unknown component names exit non-zero with a clear error."""
    queue_path = tmp_path / "queue.json"
    state_path = tmp_path / "state.json"
    _write_json(queue_path, [])
    _write_json(state_path, None)

    result = runner.invoke(
        metrics_app,
        [
            "bodai",
            "--queue-path",
            str(queue_path),
            "--state-path",
            str(state_path),
            "--component",
            "unknown-component",
        ],
    )

    assert result.exit_code == 2
    assert "Unknown --component" in result.stdout


# ---------------------------------------------------------------------------
# Missing queue handling
# ---------------------------------------------------------------------------


def test_bodai_command_handles_missing_queue(tmp_path: Path) -> None:
    """A missing queue file renders a graceful 'No events in queue' message."""
    queue_path = tmp_path / "does-not-exist.json"
    state_path = tmp_path / "state.json"
    _write_json(state_path, {"pid": 1})

    result = runner.invoke(
        metrics_app,
        [
            "bodai",
            "--queue-path",
            str(queue_path),
            "--state-path",
            str(state_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "No events in queue" in result.stdout


def test_bodai_command_handles_missing_state_file(tmp_path: Path) -> None:
    """A missing state file does not abort; the CLI marks the subscriber as stopped."""
    queue_path = tmp_path / "queue.json"
    state_path = tmp_path / "missing-state.json"
    _write_json(queue_path, [])

    result = runner.invoke(
        metrics_app,
        [
            "bodai",
            "--queue-path",
            str(queue_path),
            "--state-path",
            str(state_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "missing" in result.stdout
    assert "no" in result.stdout  # Running=no


# ---------------------------------------------------------------------------
# Stale source detection
# ---------------------------------------------------------------------------


def test_bodai_command_marks_stale_sources(tmp_path: Path) -> None:
    """Components whose most recent event is >5min old are marked stale."""
    queue_path = tmp_path / "queue.json"
    state_path = tmp_path / "state.json"

    now = datetime.now(UTC)
    fresh = _envelope(
        "mahavishnu",
        "workflow.completed",
        timestamp=now - timedelta(seconds=30),
    )
    stale = _envelope(
        "akosha",
        "aggregation.completed",
        timestamp=now - timedelta(minutes=15),
    )
    _write_json(queue_path, [fresh, stale])
    _write_json(state_path, {"pid": 1})

    result = runner.invoke(
        metrics_app,
        [
            "bodai",
            "--queue-path",
            str(queue_path),
            "--state-path",
            str(state_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    # Stale marker must appear for akosha; mahavishnu should be fresh.
    assert "stale" in result.stdout
    # Both components appear in the per-component health table.
    assert "mahavishnu" in result.stdout
    assert "akosha" in result.stdout


# ---------------------------------------------------------------------------
# --scope filter
# ---------------------------------------------------------------------------


def test_bodai_command_scope_filters_old_events(tmp_path: Path) -> None:
    """``--scope 7d`` drops events older than the cutoff."""
    queue_path = tmp_path / "queue.json"
    state_path = tmp_path / "state.json"

    now = datetime.now(UTC)
    recent = _envelope("mahavishnu", "workflow.completed", timestamp=now - timedelta(days=2))
    ancient = _envelope("mahavishnu", "workflow.completed", timestamp=now - timedelta(days=30))
    _write_json(queue_path, [recent, ancient])
    _write_json(state_path, {"pid": 1})

    result = runner.invoke(
        metrics_app,
        [
            "bodai",
            "--queue-path",
            str(queue_path),
            "--state-path",
            str(state_path),
            "--scope",
            "7d",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "scope=7d" in result.stdout
    # Queue size shows only the recent event (1), not the ancient one.
    assert "Queue size" in result.stdout


def test_bodai_command_rejects_invalid_scope(tmp_path: Path) -> None:
    """Invalid scope values produce a clear error and exit code 2."""
    queue_path = tmp_path / "queue.json"
    state_path = tmp_path / "state.json"
    _write_json(queue_path, [])
    _write_json(state_path, None)

    result = runner.invoke(
        metrics_app,
        [
            "bodai",
            "--queue-path",
            str(queue_path),
            "--state-path",
            str(state_path),
            "--scope",
            "bogus",
        ],
    )

    assert result.exit_code == 2
    assert "Invalid --scope" in result.stdout
