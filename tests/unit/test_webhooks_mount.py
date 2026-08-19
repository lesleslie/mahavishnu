"""Verify the durable webhook receiver is mounted under /durable-webhooks.

Mirrors the existing ``tests/unit/test_webhooks_receiver.py`` pattern:
monkeypatch ``dhara.put`` on the live ``dhara`` module, then POST through
the parent app's TestClient and assert the receiver's
``receive_webhook`` handler fires (status 202, ``webhook_id`` echoed
back).
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import dhara
from dhara.schema import SchemaValidationError as _RealSchemaValidationError
from dhara.schema import validate as _real_validate
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

# Pre-warm a minimal ``dhara.schema`` stub so ``mahavishnu.webhooks.receiver``
# can import in environments where the upstream ``dhara`` package is missing
# the ``schema`` submodule. Only installed when the real package is
# unavailable (substrate-compat guard); the pinned ``dhara`` package ships
# a real ``dhara.schema`` module so the real WebhookIngress/validate
# surface is preferred and the mount test exercises the real contract.
_DHARA_SCHEMA_STUB: ModuleType = ModuleType("dhara.schema")

if "dhara.schema" not in sys.modules:
    try:
        import dhara.schema  # noqa: F401
    except ImportError:
        sys.modules["dhara.schema"] = _DHARA_SCHEMA_STUB


from mahavishnu.webhooks import mount_durable_webhooks  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture
def parent_app_with_mount(monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, MagicMock]:
    """Build a parent FastAPI app with the durable webhook receiver mounted.

    Returns:
        (parent_app, captured_put) — the test client is created against
        ``parent_app`` and ``captured_put`` records every
        ``dhara.put(key, value)`` invocation.
    """
    captured: list[tuple[str, object]] = []
    mock_put = MagicMock(side_effect=lambda key, value: captured.append((key, value)))
    # The receiver resolves ``dhara.put`` at request time via
    # ``dhara_calltime("put")`` which reads ``getattr(dhara, "put", None)``,
    # so the substrate-compat gate sees whatever attribute is bound on the
    # live ``dhara`` module.
    monkeypatch.setattr(dhara, "put", mock_put, raising=False)

    app = FastAPI()
    mount_durable_webhooks(app)
    return app, mock_put


# Re-export real schema symbols so test bodies can reference them by name
# without rebinding in every test function.
SchemaValidationError = _RealSchemaValidationError
validate = _real_validate


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
