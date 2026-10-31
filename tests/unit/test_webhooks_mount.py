"""Verify the durable webhook receiver is mounted under /durable-webhooks.

Mirrors the existing ``tests/unit/test_webhooks_receiver.py`` pattern:
POST through the parent app's TestClient and assert the receiver's
``receive_webhook`` handler fires (status 202, ``webhook_id`` echoed
back) and the record reaches the substrate store.
"""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from mahavishnu.core.kv_store import kv_store
from mahavishnu.webhooks import mount_durable_webhooks

pytestmark = pytest.mark.unit


@pytest.fixture
def parent_app_with_mount() -> FastAPI:
    """Build a parent FastAPI app with the durable webhook receiver mounted."""
    app = FastAPI()
    mount_durable_webhooks(app)
    return app


def test_mount_durable_webhooks_reaches_receiver(
    parent_app_with_mount: FastAPI,
) -> None:
    """POST /durable-webhooks/webhook reaches the receiver's handler."""
    client = TestClient(parent_app_with_mount)

    # Valid WebhookIngress payload per the receiver's contract.
    payload = {
        "webhook_id": "wh-123",
        "source": "openclaw",
        "received_at": "2026-08-10T12:00:00Z",
        "payload_hash": "sha256:deadbeef",
        "metadata": {"hello": "world"},
    }

    response = client.post("/durable-webhooks/webhook", json=payload)

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "accepted"
    assert body["webhook_id"] == "wh-123"

    assert [k for k, _ in kv_store.list_prefix("")] == ["webhook-ingress/wh-123/"]
    stored = json.loads(kv_store.get("webhook-ingress/wh-123/") or "")
    assert stored["webhook_id"] == "wh-123"


def test_mount_durable_webhooks_invalid_payload_returns_422(
    parent_app_with_mount: FastAPI,
) -> None:
    """POST /durable-webhooks/webhook with an invalid payload returns 422."""
    client = TestClient(parent_app_with_mount)

    # Missing required field (``webhook_id``); the schema validator
    # refuses and the receiver returns 422.
    response = client.post(
        "/durable-webhooks/webhook",
        json={"source": "openclaw", "received_at": "2026-08-10T12:00:00Z"},
    )

    assert response.status_code == 422


def test_mount_durable_webhooks_does_not_shadow_root(
    parent_app_with_mount: FastAPI,
) -> None:
    """A catch-all GET on the parent app must not be routed to the receiver.

    Sanity-checks the Starlette mount-order contract: the
    ``/durable-webhooks`` sub-app MUST only own requests under its
    own prefix. A 404 from the parent (not the receiver) proves the
    sub-app did not swallow the catch-all path.
    """
    client = TestClient(parent_app_with_mount)

    response = client.get("/")
    assert response.status_code == 404
