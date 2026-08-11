"""Verify webhook_replay reads WebhookIngress via dhara.get and validates via from_dict.

Mirrors the canonical substrate-compat test pattern used by
``tests/unit/test_webhooks_receiver.py`` and ``tests/unit/approval/test_list_history.py``
- a single fixture substitutes ``dhara.get`` with a capture mock so the
consumer's happy/unbound/missing-key paths can be exercised without a
real substrate.
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from unittest.mock import MagicMock

from dhara.schema import WebhookIngress
import pytest

from mahavishnu.webhooks import replay as replay_module
from mahavishnu.webhooks.replay import webhook_replay


@pytest.fixture
def substrate_get(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub dhara.get after module import so the substrate-compat guard sees it.

    ``raising=False`` lets the monkeypatch land even when the host dhara
    package has not injected a ``dhara.get`` binding (mirrors the
    receiver's substrate-compat fixture pattern).
    """
    mock_get = MagicMock(return_value=None)
    monkeypatch.setattr(replay_module.dhara, "get", mock_get, raising=False)
    return mock_get


def _payload(webhook_id: str = "evt-789") -> dict[str, object]:
    return {
        "webhook_id": webhook_id,
        "source": "github",
        "received_at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC).isoformat(),
        "payload_hash": "sha256:deadbeef",
        "metadata": {"action": "closed"},
    }


def test_webhook_replay_returns_validated_struct(
    substrate_get: MagicMock,
) -> None:
    """Happy path: payload returned by dhara.get -> WebhookIngress instance."""
    substrate_get.return_value = _payload("evt-789")

    result = webhook_replay("evt-789", token="header.payload.signature")

    assert isinstance(result, WebhookIngress)
    assert result.webhook_id == "evt-789"
    assert result.source == "github"
    assert result.payload_hash == "sha256:deadbeef"


def test_webhook_replay_uses_persistence_key_format(
    substrate_get: MagicMock,
) -> None:
    """Read key must match the producer's write key (producer/consumer contract)."""
    substrate_get.return_value = _payload("evt-789")

    webhook_replay("evt-789", token="header.payload.signature")

    substrate_get.assert_called_once_with("webhook-ingress/evt-789/")


def test_webhook_replay_returns_none_when_record_missing(
    substrate_get: MagicMock,
) -> None:
    """dhara.get returns None -> webhook_replay returns None (no spurious struct)."""
    substrate_get.return_value = None

    result = webhook_replay("evt-missing", token="header.payload.signature")

    assert result is None


def test_webhook_replay_returns_none_when_dhara_unbound(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """dhara.get unbound -> None + structured warning (mirrors receiver's skipped path).

    Mirrors the approval_list_skipped pattern from
    ``tests/unit/approval/test_list_history.py``: when the substrate
    attribute is missing the consumer must skip gracefully instead of
    raising AttributeError.
    """
    monkeypatch.setattr(replay_module.dhara, "get", None, raising=False)

    with caplog.at_level(logging.WARNING, logger="mahavishnu.webhooks.replay"):
        result = webhook_replay("evt-unbound", token="header.payload.signature")

    assert result is None

    skip_records = [rec for rec in caplog.records if "webhook_replay_skipped" in rec.message]
    assert skip_records, [rec.message for rec in caplog.records]
    record = skip_records[-1]
    # Oneiric's formatter bundles extras into the formatted message string
    # rather than assigning them as LogRecord attributes, so the structured
    # fields are asserted by substring presence in the message body.
    assert "'reason': 'dhara.get_unbound'" in record.message
    assert "'webhook_id': 'evt-unbound'" in record.message
    # Observability rule: warning log must not carry str(exception).
    assert not hasattr(record, "exc_info") or record.exc_info is None


def test_webhook_replay_rejects_missing_token(monkeypatch, caplog):
    """RBAC gate: missing token returns None before any Dhara call.

    Multi-agent review flagged HIGH-severity missing auth on this read
    path. Mirrors the same shape as the approval-cli gate.
    """
    from mahavishnu.webhooks import replay

    dhara_get = MagicMock(return_value={"webhook_id": "evt-1"})
    monkeypatch.setattr(replay.dhara, "get", dhara_get, raising=False)

    with caplog.at_level("WARNING", logger="mahavishnu.webhooks.replay"):
        result = replay.webhook_replay(webhook_id="evt-1", token=None)

    assert result is None
    dhara_get.assert_not_called()
    skip_records = [r for r in caplog.records if "webhook_replay_skipped" in r.message]
    assert skip_records, [r.message for r in caplog.records]
    assert "'reason': 'rbac_denied'" in skip_records[-1].message
    assert "'webhook_id': 'evt-1'" in skip_records[-1].message


def test_webhook_replay_rejects_non_jwt_token(monkeypatch, caplog):
    """RBAC gate: a non-JWT-shaped token is rejected as malformed."""
    from mahavishnu.webhooks import replay

    dhara_get = MagicMock(return_value={"webhook_id": "evt-2"})
    monkeypatch.setattr(replay.dhara, "get", dhara_get, raising=False)

    with caplog.at_level("WARNING", logger="mahavishnu.webhooks.replay"):
        result = replay.webhook_replay(webhook_id="evt-2", token="opaque")

    assert result is None
    dhara_get.assert_not_called()


def test_webhook_replay_passes_with_jwt_shaped_token(monkeypatch):
    """With a JWT-shaped token the RBAC gate passes and the substrate is queried."""
    from mahavishnu.webhooks import replay

    payload = _payload("evt-3")
    dhara_get = MagicMock(return_value=payload)
    monkeypatch.setattr(replay.dhara, "get", dhara_get, raising=False)

    token = "header.payload.signature"
    result = replay.webhook_replay(webhook_id="evt-3", token=token)

    dhara_get.assert_called_once_with("webhook-ingress/evt-3/")
    assert isinstance(result, WebhookIngress)
    assert result.webhook_id == "evt-3"
