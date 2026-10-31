"""Verify webhook_replay reads WebhookIngress through the substrate facade.

The consumer used to resolve ``mcp.get`` through a dynamic module lookup
that always returned ``None`` — the name ``mcp`` now resolves to the MCP
Python SDK, which has no ``get``. Every read therefore reported "no
record" and the durable webhook log was never populated.

These tests use the REAL facade: the store is process-local and
``tests/conftest.py`` clears it around every test, so a write here is
what the consumer reads back.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from structlog.testing import capture_logs

from mahavishnu.core import substrate
from mahavishnu.core.kv_store import kv_store
from mahavishnu.core.models.persistence import WebhookIngress
from mahavishnu.webhooks.replay import webhook_replay

TOKEN = "header.payload.signature"


def _payload(webhook_id: str = "evt-789") -> dict[str, object]:
    return {
        "webhook_id": webhook_id,
        "source": "github",
        "received_at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC).isoformat(),
        "payload_hash": "sha256:deadbeef",
        "metadata": {"action": "closed"},
    }


@pytest.mark.asyncio
async def test_webhook_replay_returns_validated_struct() -> None:
    """Happy path: a stored payload comes back as a WebhookIngress."""
    substrate.put("webhook-ingress/evt-789/", _payload("evt-789"))

    result = await webhook_replay("evt-789", token=TOKEN)

    assert isinstance(result, WebhookIngress)
    assert result.webhook_id == "evt-789"
    assert result.source == "github"
    assert result.payload_hash == "sha256:deadbeef"


@pytest.mark.asyncio
async def test_webhook_replay_uses_persistence_key_format() -> None:
    """Read key must match the producer's write key (producer/consumer contract)."""
    substrate.put("webhook-ingress/evt-789/", _payload("evt-789"))

    await webhook_replay("evt-789", token=TOKEN)

    assert [k for k, _ in kv_store.list_prefix("")] == ["webhook-ingress/evt-789/"]


@pytest.mark.asyncio
async def test_webhook_replay_returns_none_when_record_missing() -> None:
    """No record -> None (no spurious struct)."""
    result = await webhook_replay("evt-missing", token=TOKEN)

    assert result is None


@pytest.mark.asyncio
async def test_webhook_replay_rejects_missing_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RBAC gate: missing token returns None before any substrate read.

    Multi-agent review flagged HIGH-severity missing auth on this read
    path. Mirrors the same shape as the approval-cli gate.
    """
    mock_get = AsyncMock()
    monkeypatch.setattr(substrate, "get", mock_get)

    with capture_logs() as logs:
        result = await webhook_replay(webhook_id="evt-1", token=None)

    assert result is None
    mock_get.assert_not_called()
    skipped = [entry for entry in logs if entry["event"] == "webhook_replay_skipped"]
    assert skipped, logs
    assert skipped[-1]["extra"]["reason"] == "rbac_denied"
    assert skipped[-1]["extra"]["webhook_id"] == "evt-1"


@pytest.mark.asyncio
async def test_webhook_replay_rejects_non_jwt_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RBAC gate: a non-JWT-shaped token is rejected as malformed."""
    mock_get = AsyncMock()
    monkeypatch.setattr(substrate, "get", mock_get)

    result = await webhook_replay(webhook_id="evt-2", token="opaque")

    assert result is None
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_replay_passes_with_jwt_shaped_token() -> None:
    """With a JWT-shaped token the RBAC gate passes and the substrate is read."""
    substrate.put("webhook-ingress/evt-3/", _payload("evt-3"))

    result = await webhook_replay(webhook_id="evt-3", token=TOKEN)

    assert isinstance(result, WebhookIngress)
    assert result.webhook_id == "evt-3"
