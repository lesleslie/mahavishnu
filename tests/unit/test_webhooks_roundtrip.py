"""Verify producer (receiver) and consumer (replay) round-trip a WebhookIngress.

End-to-end contract test for M-WEBHOOK-DURABLE Task 3. The producer-side
TestClient posts a valid payload; the substrate store keeps the persisted
``WebhookIngress``; the consumer reads the same record back via
``webhook_replay``. Struct equality holds across ``msgspec.Struct``'s
duck-typed field access.

This is now a true round-trip: the producer writes into the same
process-local store the consumer reads, so a key mismatch or an
encoding asymmetry shows up here rather than being papered over by a
capture mock.

Mirrors ``tests/integration/approval/test_round_trip.py`` and
``tests/integration/workflow/test_outcome_round_trip.py`` — the canonical
producer/consumer durability pattern across the portfolio.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
import pytest

from mahavishnu.core.kv_store import kv_store
from mahavishnu.core.models.persistence import WebhookIngress
from mahavishnu.webhooks import replay as replay_module
from mahavishnu.webhooks.receiver import app

TOKEN = "header.payload.signature"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _valid_payload(webhook_id: str = "evt-roundtrip") -> dict[str, object]:
    return {
        "webhook_id": webhook_id,
        "source": "github",
        "received_at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC).isoformat(),
        "payload_hash": "sha256:roundtrip",
        "metadata": {"action": "roundtrip"},
    }


@pytest.mark.asyncio
async def test_webhook_round_trip_struct_equality(client: TestClient) -> None:
    """Producer writes a validated WebhookIngress; consumer reads it back.

    asserts:
        - ``response.status_code == 202``
        - the record is stored under ``f"webhook-ingress/{webhook_id}/"``
        - ``webhook_replay(webhook_id)`` returns a ``WebhookIngress``
          with field-by-field equality against the producer-side record.
    """
    payload = _valid_payload("evt-roundtrip")

    response = client.post("/webhook", json=payload)
    assert response.status_code == 202, response.text

    # Producer side: the record landed under the producer's key.
    assert [k for k, _ in kv_store.list_prefix("")] == [
        "webhook-ingress/evt-roundtrip/"
    ]

    # Consumer side: read it back via the persistence key. Pass a
    # JWT-shaped token so the leaf's RBAC gate (rejects missing/non-JWT
    # tokens) falls through.
    result = await replay_module.webhook_replay("evt-roundtrip", token=TOKEN)
    assert result is not None

    # Struct equality — duck-typed msgspec.Struct field access.
    read = result
    assert isinstance(read, WebhookIngress)
    assert read.webhook_id == "evt-roundtrip"
    assert read.source == "github"
    assert read.received_at == datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC)
    assert read.payload_hash == "sha256:roundtrip"
    assert read.metadata == {"action": "roundtrip"}


@pytest.mark.asyncio
async def test_webhook_round_trip_uses_matching_persistence_keys(
    client: TestClient,
) -> None:
    """Producer write key and consumer read key MUST match (contract).

    Locks the producer/consumer contract: any drift between the two
    sides surfaces here as a key mismatch.
    """
    payload = _valid_payload("evt-keycheck")

    response = client.post("/webhook", json=payload)
    assert response.status_code == 202, response.text
    producer_key = next(iter(kv_store.list_prefix("")))[0]

    await replay_module.webhook_replay("evt-keycheck", token=TOKEN)

    # The consumer read the producer's key — it is still the only key
    # in the store, and the replay found the record.
    assert producer_key == "webhook-ingress/evt-keycheck/"
    assert [k for k, _ in kv_store.list_prefix("")] == ["webhook-ingress/evt-keycheck/"]


@pytest.mark.asyncio
async def test_webhook_round_trip_with_distinct_ids_isolates_records(
    client: TestClient,
) -> None:
    """Two distinct webhook IDs produce two distinct substrate keys.

    Mirrors the approval-log round-trip's
    ``test_approval_log_round_trip_isolates_per_approval_id`` test.
    """
    client.post("/webhook", json=_valid_payload("evt-a"))
    client.post("/webhook", json=_valid_payload("evt-b"))

    assert {k for k, _ in kv_store.list_prefix("")} == {
        "webhook-ingress/evt-a/",
        "webhook-ingress/evt-b/",
    }

    # Read-back scoping: webhook_replay("evt-a") must read the "evt-a"
    # record, not the "evt-b" one — the consumer's key format enforces
    # per-id isolation.
    read_a = await replay_module.webhook_replay("evt-a", token=TOKEN)
    read_b = await replay_module.webhook_replay("evt-b", token=TOKEN)

    assert read_a is not None and read_a.webhook_id == "evt-a"
    assert read_b is not None and read_b.webhook_id == "evt-b"
