"""Verify producer (receiver) and consumer (replay) round-trip a WebhookIngress.

End-to-end contract test for M-WEBHOOK-DURABLE Task 3. The producer-side
TestClient posts a valid payload; a capture mock stores the persisted
``WebhookIngress``; a second capture mock returns the same record from
``dhara.get`` so the consumer reads it back via ``webhook_replay``.
Struct equality holds across ``msgspec.Struct``'s duck-typed field access.

Mirrors ``tests/integration/approval/test_round_trip.py`` and
``tests/integration/workflow/test_outcome_round_trip.py`` — the canonical
producer/consumer durability pattern across the portfolio.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import dhara
from dhara.schema import WebhookIngress
from fastapi.testclient import TestClient
import pytest

from mahavishnu.webhooks import replay as replay_module
from mahavishnu.webhooks.receiver import app


@pytest.fixture
def client_and_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, MagicMock, MagicMock]:
    """Return ``(TestClient, captured_dhara_put_mock, captured_dhara_get_mock)``.

    The producer-side mock records every ``dhara.put(key, value)`` call;
    the consumer-side mock is wired so that ``dhara.get(key)`` returns the
    value the producer just wrote. This stands in for a real substrate
    while still letting the test exercise both modules' validation paths.

    Both modules resolve their substrate bindings at call time via
    ``getattr(dhara, "put"/"get", None)``, so we patch the live ``dhara``
    module (not the receiver module — the receiver no longer imports
    ``dhara`` as a name).
    """
    storage: dict[str, object] = {}
    mock_put = MagicMock(side_effect=lambda key, value: storage.__setitem__(key, value))
    mock_get = MagicMock(side_effect=lambda key: storage.get(key))
    monkeypatch.setattr(dhara, "put", mock_put, raising=False)
    monkeypatch.setattr(dhara, "get", mock_get, raising=False)
    return TestClient(app), mock_put, mock_get


def _valid_payload(webhook_id: str = "evt-roundtrip") -> dict[str, object]:
    return {
        "webhook_id": webhook_id,
        "source": "github",
        "received_at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC).isoformat(),
        "payload_hash": "sha256:roundtrip",
        "metadata": {"action": "roundtrip"},
    }


def test_webhook_round_trip_struct_equality(
    client_and_storage: tuple[TestClient, MagicMock, MagicMock],
) -> None:
    """Producer writes a validated WebhookIngress; consumer reads it back.

    asserts:
        - ``response.status_code == 202``
        - ``mock_put`` called once with the validated struct under
          ``f"webhook-ingress/{webhook_id}/"``
        - ``webhook_replay(webhook_id)`` returns a ``WebhookIngress``
          with field-by-field equality against the producer-side struct.
    """
    client, mock_put, mock_get = client_and_storage
    payload = _valid_payload("evt-roundtrip")

    response = client.post("/webhook", json=payload)
    assert response.status_code == 202, response.text
    assert mock_put.call_count == 1

    # Producer side: persisted value is the validated struct.
    put_args = mock_put.call_args
    key, written = put_args.args
    assert key == "webhook-ingress/evt-roundtrip/"
    assert isinstance(written, WebhookIngress)
    assert written.webhook_id == "evt-roundtrip"
    assert written.source == "github"
    assert written.payload_hash == "sha256:roundtrip"

    # Consumer side: read it back via the persistence key. Pass a
    # JWT-shaped token so the leaf's RBAC gate (rejects missing/non-JWT
    # tokens) falls through.
    result = replay_module.webhook_replay("evt-roundtrip", token="header.payload.signature")
    assert result is not None
    mock_get.assert_called_with("webhook-ingress/evt-roundtrip/")

    # Struct equality — duck-typed msgspec.Struct field access.
    read = result
    assert isinstance(read, WebhookIngress)
    assert read.webhook_id == written.webhook_id
    assert read.source == written.source
    assert read.received_at == written.received_at
    assert read.payload_hash == written.payload_hash
    assert read.metadata == written.metadata


def test_webhook_round_trip_uses_matching_persistence_keys(
    client_and_storage: tuple[TestClient, MagicMock, MagicMock],
) -> None:
    """Producer write key and consumer read key MUST match (contract).

    Locks the producer/consumer contract: any drift between the two
    sides surfaces here as a captured-put-vs-read-get key mismatch.
    """
    client, mock_put, mock_get = client_and_storage
    payload = _valid_payload("evt-keycheck")

    response = client.post("/webhook", json=payload)
    assert response.status_code == 202, response.text
    producer_key = mock_put.call_args.args[0]

    replay_module.webhook_replay("evt-keycheck", token="header.payload.signature")
    consumer_key = mock_get.call_args.args[0]

    assert producer_key == consumer_key == "webhook-ingress/evt-keycheck/"


def test_webhook_round_trip_with_distinct_ids_isolates_records(
    client_and_storage: tuple[TestClient, MagicMock, MagicMock],
) -> None:
    """Two distinct webhook IDs produce two distinct substrate keys.

    Mirrors the approval-log round-trip's
    ``test_approval_log_round_trip_isolates_per_approval_id`` test.
    """
    client, mock_put, mock_get = client_and_storage

    client.post("/webhook", json=_valid_payload("evt-a"))
    client.post("/webhook", json=_valid_payload("evt-b"))

    assert mock_put.call_count == 2
    keys = {call.args[0] for call in mock_put.call_args_list}
    assert keys == {"webhook-ingress/evt-a/", "webhook-ingress/evt-b/"}

    # Read-back scoping: webhook_replay("evt-a") must read the "evt-a"
    # key, not the "evt-b" key — the consumer's key format enforces
    # per-id isolation.
    replay_module.webhook_replay("evt-a", token="header.payload.signature")
    replay_module.webhook_replay("evt-b", token="header.payload.signature")
    assert mock_get.call_args_list[0].args[0] == "webhook-ingress/evt-a/"
    assert mock_get.call_args_list[1].args[0] == "webhook-ingress/evt-b/"
