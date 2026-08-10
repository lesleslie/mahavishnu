"""Verify webhook receiver persists validated WebhookIngress via dhara.put.

Mirrors the canonical substrate-compat test pattern used by
``tests/unit/workflow/test_outcome_writer.py`` and
``tests/unit/approval/test_decision_writer.py`` — a single fixture
substitutes ``dhara.put`` with a capture mock so the receiver's
happy/invalid paths can be exercised without a real substrate.
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from unittest.mock import MagicMock

from dhara.schema import WebhookIngress
from fastapi.testclient import TestClient
import pytest

from mahavishnu.webhooks import receiver as receiver_module
from mahavishnu.webhooks.receiver import app


@pytest.fixture
def client_and_storage(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, MagicMock]:
    """Return ``(TestClient, captured_dhara_put_mock)``.

    ``monkeypatch.setattr`` resolves ``"mahavishnu.webhooks.receiver.dhara"``
    against the same module reference that the receiver binds at import time,
    which is required because the receiver installs ``dhara.put = None`` in a
    substrate-compat guard that runs at module load.
    """
    captured: list[tuple[str, object]] = []
    mock_put = MagicMock(side_effect=lambda key, value: captured.append((key, value)))
    monkeypatch.setattr("mahavishnu.webhooks.receiver.dhara.put", mock_put)
    return TestClient(app), mock_put


def _valid_payload(webhook_id: str = "evt-123") -> dict[str, object]:
    return {
        "webhook_id": webhook_id,
        "source": "github",
        "received_at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC).isoformat(),
        "payload_hash": "sha256:deadbeef",
        "metadata": {"action": "opened"},
    }


def test_post_webhook_emits_validated_struct(
    client_and_storage: tuple[TestClient, MagicMock],
) -> None:
    """Valid payload → 202 + single dhara.put carrying a WebhookIngress."""
    client, mock_put = client_and_storage
    payload = {
        "webhook_id": "evt-123",
        "source": "github",
        "received_at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC).isoformat(),
        "payload_hash": "sha256:deadbeef",
        "metadata": {"action": "opened"},
    }
    response = client.post("/webhook", json=payload)
    assert response.status_code == 202, response.text
    assert mock_put.call_count == 1

    # Verify the persisted value is a validated WebhookIngress with the
    # expected fields populated from the request body.
    put_args = mock_put.call_args
    key, value = put_args.args
    assert key == "webhook-ingress/evt-123/"
    assert isinstance(value, WebhookIngress)
    assert value.webhook_id == "evt-123"
    assert value.source == "github"
    assert value.payload_hash == "sha256:deadbeef"


def test_post_webhook_rejects_invalid_payload(
    client_and_storage: tuple[TestClient, MagicMock],
) -> None:
    """Missing required ``webhook_id`` → 422 + zero dhara.put calls."""
    client, mock_put = client_and_storage
    # `source` is present (so the JSON parses) but `webhook_id` is missing,
    # which the substrate treats as a required-field violation.
    response = client.post("/webhook", json={"source": "github"})
    assert response.status_code == 422, response.text
    assert mock_put.call_count == 0


def test_post_webhook_emits_warning_when_dhara_put_unbound(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """dhara.put=None → 202 + structured warning with reason='dhara.put_unbound'.

    Mirrors the approval_log_persistence_skipped pattern from
    ``decision_writer.py``: when the substrate attribute is missing the
    receiver must skip persistence gracefully instead of raising TypeError.
    """
    monkeypatch.setattr(receiver_module.dhara, "put", None, raising=False)
    client = TestClient(app)

    with caplog.at_level(logging.WARNING, logger="mahavishnu.webhooks.receiver"):
        response = client.post("/webhook", json=_valid_payload("evt-unbound"))

    assert response.status_code == 202, response.text
    assert response.json() == {"status": "accepted_in_memory_only"}

    skip_records = [rec for rec in caplog.records if "webhook_persistence_skipped" in rec.message]
    assert skip_records, [rec.message for rec in caplog.records]
    record = skip_records[-1]
    # Oneiric's formatter bundles extras into the formatted message string
    # rather than assigning them as LogRecord attributes, so the structured
    # fields are asserted by substring presence in the message body. This
    # mirrors the approach in tests/unit/approval/test_decision_writer.py.
    assert "'reason': 'dhara.put_unbound'" in record.message
    assert "'webhook_id': 'evt-unbound'" in record.message
    # Observability rule: warning log must not carry str(exception).
    assert not hasattr(record, "exc_info") or record.exc_info is None


def test_post_webhook_falls_back_to_in_memory_when_v1_disabled(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """WEBHOOK_DURABLE_V1_ENABLED=false → 202 + warning with reason='v1_disabled'.

    Ensures the rollback lever named in the plan's rollback-signal matrix
    short-circuits persistence before the substrate-compat gate runs.
    """
    monkeypatch.setattr(receiver_module.dhara, "put", MagicMock(), raising=False)
    monkeypatch.setenv("WEBHOOK_DURABLE_V1_ENABLED", "false")
    client = TestClient(app)

    with caplog.at_level(logging.WARNING, logger="mahavishnu.webhooks.receiver"):
        response = client.post("/webhook", json=_valid_payload("evt-disabled"))

    assert response.status_code == 202, response.text
    assert response.json() == {"status": "accepted_in_memory_only"}

    skip_records = [rec for rec in caplog.records if "webhook_persistence_skipped" in rec.message]
    assert skip_records, [rec.message for rec in caplog.records]
    record = skip_records[-1]
    # Oneiric's formatter bundles extras into the formatted message string
    # rather than assigning them as LogRecord attributes, so the structured
    # fields are asserted by substring presence in the message body. This
    # mirrors the approach in tests/unit/approval/test_decision_writer.py.
    assert "'reason': 'v1_disabled'" in record.message
    assert "'webhook_id': 'evt-disabled'" in record.message
    assert not hasattr(record, "exc_info") or record.exc_info is None
