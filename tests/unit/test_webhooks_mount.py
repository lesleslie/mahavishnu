"""Verify the durable webhook receiver is mounted under /durable-webhooks.

Mirrors the existing ``tests/unit/test_webhooks_receiver.py`` pattern:
patch ``mahavishnu.webhooks.receiver.mcp_calltime`` to a fake that
returns our mock put, then POST through the parent app's TestClient
and assert the receiver's ``receive_webhook`` handler fires (status
202, ``webhook_id`` echoed back).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from mahavishnu.webhooks import mount_durable_webhooks
from mahavishnu.webhooks import receiver as receiver_module

pytestmark = pytest.mark.unit


@pytest.fixture
def parent_app_with_mount(monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, MagicMock]:
    """Build a parent FastAPI app with the durable webhook receiver mounted.

    Returns:
        (parent_app, captured_put) — the test client is created against
        ``parent_app`` and ``captured_put`` records every
        ``mcp.put(key, value)`` invocation.
    """
    captured: list[tuple[str, object]] = []
    mock_put = MagicMock(side_effect=lambda key, value: captured.append((key, value)))
    # Patch the receiver's local ``mcp_calltime`` binding — the receiver
    # calls ``put = mcp_calltime("put")`` at request time, so replacing
    # the binding on the receiver module makes the leaf see the fake.
    monkeypatch.setattr(
        receiver_module,
        "mcp_calltime",
        lambda name: mock_put if name == "put" else None,
    )

    app = FastAPI()
    mount_durable_webhooks(app)
    return app, mock_put


def test_mount_durable_webhooks_reaches_receiver(
    parent_app_with_mount: tuple[FastAPI, MagicMock],
) -> None:
    """POST /durable-webhooks/webhook reaches the receiver's handler."""
    app, mock_put = parent_app_with_mount
    client = TestClient(app)

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
    mock_put.assert_called_once()
    key, value = mock_put.call_args[0]
    assert key == "webhook-ingress/wh-123/"
    # The persisted record is the validated msgspec Struct.
    assert getattr(value, "webhook_id", None) == "wh-123"


def test_mount_durable_webhooks_invalid_payload_returns_422(
    parent_app_with_mount: tuple[FastAPI, MagicMock],
) -> None:
    """POST /durable-webhooks/webhook with an invalid payload returns 422."""
    app, _ = parent_app_with_mount
    client = TestClient(app)

    # Missing required field (``webhook_id``); the schema validator
    # refuses and the receiver returns 422.
    response = client.post(
        "/durable-webhooks/webhook",
        json={"source": "openclaw", "received_at": "2026-08-10T12:00:00Z"},
    )

    assert response.status_code == 422


def test_mount_durable_webhooks_does_not_shadow_root(
    parent_app_with_mount: tuple[FastAPI, MagicMock],
) -> None:
    """A catch-all GET on the parent app must not be routed to the receiver.

    Sanity-checks the Starlette mount-order contract: the
    ``/durable-webhooks`` sub-app MUST only own requests under its
    own prefix. A 404 from the parent (not the receiver) proves the
    sub-app did not swallow the catch-all path.
    """
    app, _ = parent_app_with_mount
    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 404
