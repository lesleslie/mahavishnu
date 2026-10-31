"""Verify the webhook receiver persists validated WebhookIngress records.

The receiver used to resolve ``mcp.put`` through a dynamic module lookup
that always returned ``None`` — the name ``mcp`` now resolves to the MCP
Python SDK, which has no ``put``. Every accepted webhook was therefore
discarded and the durable ingress log stayed empty.

These tests use the REAL substrate facade: the store is process-local and
``tests/conftest.py`` clears it around every test, so a write here is
what a replay would read back.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json

from fastapi.testclient import TestClient
import pytest
from structlog.testing import capture_logs

from mahavishnu.core.kv_store import kv_store
from mahavishnu.webhooks.receiver import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _valid_payload(webhook_id: str = "evt-123") -> dict[str, object]:
    return {
        "webhook_id": webhook_id,
        "source": "github",
        "received_at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC).isoformat(),
        "payload_hash": "sha256:deadbeef",
        "metadata": {"action": "opened"},
    }


def test_post_webhook_persists_the_record(client: TestClient) -> None:
    """Valid payload → 202 + one stored record under the producer's key."""
    response = client.post("/webhook", json=_valid_payload("evt-123"))
    assert response.status_code == 202, response.text

    assert [k for k, _ in kv_store.list_prefix("")] == ["webhook-ingress/evt-123/"]
    stored = json.loads(kv_store.get("webhook-ingress/evt-123/") or "")
    assert stored["webhook_id"] == "evt-123"
    assert stored["source"] == "github"
    assert stored["payload_hash"] == "sha256:deadbeef"


def test_post_webhook_rejects_invalid_payload(client: TestClient) -> None:
    """Missing required ``webhook_id`` → 422 + nothing stored."""
    # `source` is present (so the JSON parses) but `webhook_id` is missing,
    # which the substrate treats as a required-field violation.
    response = client.post("/webhook", json={"source": "github"})
    assert response.status_code == 422, response.text
    assert not kv_store.list_prefix("")


def test_post_webhook_falls_back_to_in_memory_when_v1_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WEBHOOK_DURABLE_V1_ENABLED=false → 202 + warning with reason='v1_disabled'.

    Ensures the rollback lever named in the plan's rollback-signal matrix
    short-circuits persistence before the substrate write.
    """
    monkeypatch.setenv("WEBHOOK_DURABLE_V1_ENABLED", "false")
    client = TestClient(app)

    with capture_logs() as logs:
        response = client.post("/webhook", json=_valid_payload("evt-disabled"))

    assert response.status_code == 202, response.text
    assert response.json() == {"status": "accepted_in_memory_only"}
    assert not kv_store.list_prefix("")

    skipped = [entry for entry in logs if entry["event"] == "webhook_persistence_skipped"]
    assert skipped, logs
    assert skipped[-1]["extra"]["reason"] == "v1_disabled"
    assert skipped[-1]["extra"]["webhook_id"] == "evt-disabled"
