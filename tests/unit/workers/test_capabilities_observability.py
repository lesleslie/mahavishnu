"""Tests for the capability-layer observability recorders.

Matches the project's established pattern (see tests/unit/test_event_wire_observability.py):
monkeypatch the module-level Oneiric logger with a MagicMock and assert on the
call arguments, rather than relying on pytest's ``caplog`` fixture (which only
captures stdlib ``logging`` records by default and is unreliable for the
structlog-backed Oneiric logger).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from mahavishnu.workers.capabilities import _observability as observability
from mahavishnu.workers.capabilities import (
    evaluate_worker_capabilities,
    reset_for_tests,
)
from mahavishnu.workers.capabilities._safe import safe_error_for_user
from mahavishnu.workers.capabilities._states import (
    WorkerCapabilityReport,
    WorkerCapabilityState,
    WorkerCheck,
)


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


# ---------------------------------------------------------------------------
# Security: broadcast payload must not leak env-var names or missing requirements
# (finding #1 — information disclosure via WebSocket).
# ---------------------------------------------------------------------------


def test_publish_event_payload_does_not_leak_env_var_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The coarsened broadcast payload must never expose env-var names from missing_requirements."""
    reset_for_tests()
    calls: list[tuple[str, dict[str, str], str]] = []
    monkeypatch.setattr(
        observability,
        "_broadcast_event",
        lambda event_name, payload, room: calls.append((event_name, payload, room)),
    )

    report = WorkerCapabilityReport(
        worker_type="terminal-claude",
        state=WorkerCapabilityState.CONFIGURED,
        missing_requirements=["MINIMAX_API_KEY", "OPENAI_API_KEY", "tool:claude"],
        safe_reason="missing: MINIMAX_API_KEY,OPENAI_API_KEY,tool:claude",
    )
    observability._publish_event(report)

    assert calls, "_broadcast_event must be called for capability transitions"
    event_name, payload, room = calls[0]

    # Only the new worker.availability_changed event is emitted (the duplicate
    # adapter.health_changed call was removed).
    assert event_name == "worker.availability_changed"
    assert room == "adapters"

    # The payload must not include the literal env-var names or tool identifier.
    payload_repr = repr(payload)
    assert "MINIMAX_API_KEY" not in payload_repr
    assert "OPENAI_API_KEY" not in payload_repr
    assert "missing_requirements" not in payload
    assert "safe_reason" not in payload

    # The coarsened bucket is "missing_tool" because tool:claude is in missing.
    assert payload["reason_bucket"] == "missing_tool"
    assert payload["worker_type"] == "terminal-claude"
    assert payload["state"] == "CONFIGURED"
    assert "probe_at" in payload


def test_publish_event_payload_does_not_leak_tool_or_setting_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CONFIGURED states with tool:/setting: entries bucket into missing_tool / missing_settings."""
    reset_for_tests()
    monkeypatch.setattr(observability, "_broadcast_event", lambda *a, **k: None)

    tool_report = WorkerCapabilityReport(
        worker_type="adapter-ollama",
        state=WorkerCapabilityState.CONFIGURED,
        missing_requirements=["tool:ollama"],
        safe_reason="tool:ollama",
    )
    observability._publish_event(tool_report)

    setting_report = WorkerCapabilityReport(
        worker_type="adapter-llamaindex",
        state=WorkerCapabilityState.CONFIGURED,
        missing_requirements=["setting:llamaindex.api_key"],
        safe_reason="setting:llamaindex.api_key",
    )
    observability._publish_event(setting_report)

    # Verify the bucket helper directly — the broadcast above ran with a mock.
    assert observability._bucket(tool_report) == "missing_tool"
    assert observability._bucket(setting_report) == "missing_settings"


@pytest.mark.parametrize(
    "state,missing_requirements,checks,expected_bucket",
    [
        # READY → ready
        (WorkerCapabilityState.READY, [], [], "ready"),
        # CONFIGURED with tool: → missing_tool
        (WorkerCapabilityState.CONFIGURED, ["tool:claude"], [], "missing_tool"),
        # CONFIGURED with setting: → missing_settings
        (
            WorkerCapabilityState.CONFIGURED,
            ["setting:workers.enabled"],
            [],
            "missing_settings",
        ),
        # CONFIGURED with env-var → missing_credentials
        (
            WorkerCapabilityState.CONFIGURED,
            ["MINIMAX_API_KEY", "OPENAI_API_KEY"],
            [],
            "missing_credentials",
        ),
        # CONFIGURED with mixed (tool wins because it is checked first) → missing_tool
        (
            WorkerCapabilityState.CONFIGURED,
            ["setting:foo", "tool:bar"],
            [],
            "missing_tool",
        ),
        # AVAILABLE with failed check → service_unreachable
        (
            WorkerCapabilityState.AVAILABLE,
            [],
            [WorkerCheck("openclaw_gateway", "fail", "unhealthy")],
            "service_unreachable",
        ),
        # AVAILABLE with all-pass checks → ready
        (
            WorkerCapabilityState.AVAILABLE,
            [],
            [WorkerCheck("openclaw_gateway", "pass", "ok")],
            "ready",
        ),
        # REGISTERED → unknown
        (WorkerCapabilityState.REGISTERED, ["unknown:foo"], [], "unknown"),
    ],
)
def test_bucket_mapping(
    state: WorkerCapabilityState,
    missing_requirements: list[str],
    checks: list[WorkerCheck],
    expected_bucket: str,
) -> None:
    """The _bucket helper covers every documented mapping path."""
    report = WorkerCapabilityReport(
        worker_type="w",
        state=state,
        checks=checks,
        missing_requirements=missing_requirements,
    )
    assert observability._bucket(report) == expected_bucket


def test_publish_event_wraps_strings_through_safe_error_for_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every string field in the broadcast payload is passed through safe_error_for_user."""
    reset_for_tests()
    calls: list[dict[str, str]] = []
    monkeypatch.setattr(
        observability,
        "_broadcast_event",
        lambda event_name, payload, room: calls.append(payload),
    )

    # Worker type deliberately shaped like an OpenAI key to verify defense-in-depth.
    report = WorkerCapabilityReport(
        worker_type="sk-12345678abcdefgh",
        state=WorkerCapabilityState.READY,
        missing_requirements=[],
        safe_reason="static prerequisites satisfied",
    )
    observability._publish_event(report)

    assert calls
    payload = calls[0]
    # Defense-in-depth: any secret-shaped substring in worker_type is redacted.
    assert payload["worker_type"] == "***"


# ---------------------------------------------------------------------------
# Security: redaction regex must catch every known provider key shape
# (finding #2 — under-validated redaction regex).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "secret,label",
    [
        ("sk-abcdefghijklmnop", "openai-without-hyphens"),
        ("sk-abcdefgh-ijkl-mnop", "openai-with-hyphens"),
        ("ghp_abcdefghijklmnop", "github-pat"),
        ("xoxa-abcdefghijklmn", "slack-app-token"),
        ("xoxb-abcdefghijklmn", "slack-bot-token"),
        ("ya29.abcdefghijklmnop", "google-oauth-refresh-token"),
        ("eyJabcdefghijklmnopqrstuvwxyz", "jwt-base64url-header"),
        ("AKIAABCDEFGHIJKLMNOP", "aws-access-key-id"),
        ("glpat-abcdefghijklmnop", "gitlab-personal-access-token"),
        ("Bearer abcdefghijklmnop", "bearer-prefixed-token"),
    ],
)
def test_safe_error_for_user_redacts_known_provider_keys(secret: str, label: str) -> None:
    """Property-style: every known provider key shape is fully redacted."""
    redacted = safe_error_for_user(secret)
    assert redacted == "***", f"{label}: expected '***', got {redacted!r}"


def test_safe_error_for_user_preserves_non_secret_text() -> None:
    """Non-secret text passes through unchanged."""
    msg = "static prerequisites satisfied"
    assert safe_error_for_user(msg) == msg


def test_safe_error_for_user_redacts_secrets_mixed_with_text() -> None:
    """Secrets are redacted even when embedded in surrounding text."""
    msg = "auth failed for token sk-abcdefghijklmnop during connect"
    assert safe_error_for_user(msg) == "auth failed for token *** during connect"


def test_safe_error_for_user_handles_none_and_empty() -> None:
    """None and empty input return the documented sentinel (empty string)."""
    assert safe_error_for_user(None) == ""
    assert safe_error_for_user("") == ""