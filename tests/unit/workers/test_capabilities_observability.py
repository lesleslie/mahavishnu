"""Tests for the capability-layer observability recorders.

Matches the project's established pattern (see tests/unit/test_event_wire_observability.py):
monkeypatch the module-level Oneiric logger with a MagicMock and assert on the
call arguments, rather than relying on pytest's ``caplog`` fixture (which only
captures stdlib ``logging`` records by default and is unreliable for the
structlog-backed Oneiric logger).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from mahavishnu.workers.capabilities import _observability as observability
from mahavishnu.workers.capabilities import (
    evaluate_worker_capabilities,
    reset_for_tests,
)
from mahavishnu.workers.capabilities._states import (
    WorkerCapabilityReport,
    WorkerCapabilityState,
)

if TYPE_CHECKING:
    import pytest


@dataclass
class C:
    runtime: str | None = None
    socket_path: str | None = None


@dataclass
class W:
    enabled: bool = True
    container: C = field(default_factory=C)


@dataclass
class S:
    workers: W = field(default_factory=W)


def test_state_change_emits_log_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    """First evaluation for a worker emits a worker_capability_transition info log."""
    reset_for_tests()
    monkeypatch.setattr("shutil.which", lambda _: None)
    logger = MagicMock()
    monkeypatch.setattr(observability, "logger", logger)
    # Avoid emitting a real websocket event in unit tests.
    monkeypatch.setattr(observability, "_publish_event", lambda _report: None)

    evaluate_worker_capabilities("terminal-claude", settings=S())

    logger.info.assert_called_once()
    args, _kwargs = logger.info.call_args
    assert "worker_capability_transition" in args[0]


def test_state_change_broadcasts_websocket_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """State change publishes a websocket event via ``_publish_event``."""
    reset_for_tests()
    monkeypatch.setattr("shutil.which", lambda _: None)
    calls = []
    monkeypatch.setattr(observability, "_publish_event", lambda report: calls.append(report))

    evaluate_worker_capabilities("terminal-claude", settings=S())

    assert calls


def test_failed_probe_emits_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """Recording a probe failure emits a worker_capability_probe_failed warning log."""
    reset_for_tests()
    logger = MagicMock()
    monkeypatch.setattr(observability, "logger", logger)

    report = WorkerCapabilityReport(
        worker_type="terminal-claude",
        state=WorkerCapabilityState.READY,
        safe_reason="static prerequisites satisfied",
    )
    observability.record_probe_failure(report, "binary", "claude binary not found")

    logger.warning.assert_called_once()
    args, _kwargs = logger.warning.call_args
    assert "worker_capability_probe_failed" in args[0]
