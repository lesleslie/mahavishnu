"""Verify the durable webhook receiver is mounted under /durable-webhooks.

Mirrors the existing ``tests/unit/test_webhooks_receiver.py`` pattern:
monkeypatch ``dhara.put`` on the receiver module, then POST through
the parent app's TestClient and assert the receiver's
``receive_webhook`` handler fires (status 202, ``webhook_id`` echoed
back).
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

# Pre-warm a minimal ``dhara.schema`` stub so ``mahavishnu.webhooks.receiver``
# can import in environments where the upstream ``dhara`` package is missing
# the ``schema`` submodule (the substrate-compat pattern that Dhara
# installs at runtime). The receiver only needs ``SchemaValidationError``
# and ``validate`` at module load. The stub mirrors the real registry
# API: ``validate(name, payload)`` returns a struct-like ``SimpleNamespace``
# so the receiver can do ``validated.webhook_id`` / ``validated.source``
# attribute access, and rejects payloads missing ``webhook_id`` by raising
# ``SchemaValidationError`` (the receiver's 422 path).
_DHARA_SCHEMA_STUB: ModuleType = ModuleType("dhara.schema")


class _StubSchemaValidationError(Exception):
    """Stand-in for ``dhara.schema.SchemaValidationError``."""


def _stub_validate(name: str, payload: object) -> object:
    """Stand-in for ``dhara.schema.validate``.

    Mirrors the registry call shape ``validate(name, payload)`` used at
    ``mahavishnu/webhooks/receiver.py:87``. Returns ``SimpleNamespace``
    for valid payloads so the receiver's ``validated.webhook_id``
    attribute access works. Rejects payloads missing ``webhook_id`` by
    raising ``SchemaValidationError`` (the receiver's 422 path).
    """
    if not isinstance(payload, dict):
        raise _StubSchemaValidationError("payload must be a dict")
    if not payload.get("webhook_id"):
        raise _StubSchemaValidationError("webhook_id is required")
    return SimpleNamespace(**payload)


_DHARA_SCHEMA_STUB.SchemaValidationError = _StubSchemaValidationError
_DHARA_SCHEMA_STUB.validate = _stub_validate
# Force-assign (not setdefault): sibling tests in the same xdist worker may
# have already populated ``dhara.schema`` in sys.modules with a different
# stub. We need the webhook-shaped stub installed unconditionally so the
# ``mahavishnu.webhooks.receiver`` import chain resolves.
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
    # The receiver imports dhara at module load; the substrate-compat
    # gate sets ``dhara.put = None`` when no binding exists. Monkeypatch
    # the receiver's own reference so the gate sees a bound callable.
    monkeypatch.setattr("mahavishnu.webhooks.receiver.dhara.put", mock_put)

    # Patch the receiver's module-level ``validate`` and
    # ``SchemaValidationError`` directly. Even with
    # ``sys.modules["dhara.schema"]`` force-set, the receiver's globals
    # are frozen at module-import time, so a stub from a sibling test
    # may already have locked in a dict-returning ``validate`` binding.
    # Direct patches on the receiver's namespace override that.
    monkeypatch.setattr(
        "mahavishnu.webhooks.receiver.validate", _stub_validate
    )
    monkeypatch.setattr(
        "mahavishnu.webhooks.receiver.SchemaValidationError",
        _StubSchemaValidationError,
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
        "payload": {"hello": "world"},
        "metadata": {},
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
