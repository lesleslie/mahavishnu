"""Verify list_approval_history reads MCP payloads and returns typed ApprovalLog structs.

The reader is the one substrate call site that runs **outside** the
server process, so it reads through the server's public KV surface over
HTTP rather than the in-process facade (which would answer from the
CLI's own, empty, store). The tests stub the MCP client the CLI builds.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any

import pytest
from structlog.testing import capture_logs

from mahavishnu.cli.approval_cli import list_approval_history
from mahavishnu.core.models.persistence import ApprovalLog

TOKEN = "header.payload.signature"


class _FakeMCPClient:
    """Stand-in for ``mahavishnu.core.mcp_adapter.MCPClient``.

    The CLI imports the client lazily inside the function, so patching
    the attribute on the source module reaches it.
    """

    def __init__(
        self, base_url: str, timeout: float = 30.0, token: str | None = None, internal: bool = False
    ) -> None:
        self.base_url = base_url
        self.internal = internal
        self.kv_list_prefixes: list[str] = []
        self.closed = False
        self.items: list[tuple[str, str]] = []
        self.raise_on_list: Exception | None = None

    async def kv_list(self, prefix: str) -> list[tuple[str, str]]:
        self.kv_list_prefixes.append(prefix)
        if self.raise_on_list is not None:
            raise self.raise_on_list
        return list(self.items)

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> _FakeMCPClient:
    """Patch the MCP client the CLI builds; return the instance it will use.

    The client is constructed lazily *inside* ``list_approval_history``,
    so the fixture pre-creates the instance and hands the factory a
    closure that returns it. Tests can then seed ``.items`` before the
    call.
    """
    instance = _FakeMCPClient(base_url="http://localhost:8680/mcp")

    def factory(
        base_url: str, timeout: float = 30.0, token: str | None = None, internal: bool = False
    ) -> _FakeMCPClient:
        instance.base_url = base_url
        instance.internal = internal
        return instance

    monkeypatch.setattr("mahavishnu.core.mcp_adapter.MCPClient", factory)
    return instance


def _payload(
    approval_id: str,
    *,
    action: str = "approved",
    actor: str = "alice",
    metadata: dict[str, Any] | None = None,
    at: datetime | None = None,
) -> dict[str, Any]:
    """Build the JSON payload the KV store holds for an approval record."""
    return {
        "approval_id": approval_id,
        "action": action,
        "actor": actor,
        "at": (at or datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC)).isoformat(),
        "metadata": metadata or {"rationale": f"reason for {approval_id}"},
    }


def _store(pairs: list[tuple[str, dict[str, Any]]]) -> list[tuple[str, str]]:
    return [(key, json.dumps(value)) for key, value in pairs]


@pytest.mark.asyncio
async def test_list_approval_history_returns_validated_structs(
    fake_client: _FakeMCPClient,
) -> None:
    fake_client.items = _store(
        [
            (
                "approval-history/apr-001/20260810T120000000000Z-aaaa1111",
                _payload("apr-001", action="approved", actor="alice"),
            ),
            (
                "approval-history/apr-002/20260811T120000000000Z-bbbb2222",
                _payload("apr-002", action="denied", actor="bob"),
            ),
        ]
    )

    results = await list_approval_history(
        approval_id="apr-stream",
        since=None,
        status=None,
        token=TOKEN,
    )

    assert isinstance(results, list)
    assert len(results) == 2
    for record in results:
        assert isinstance(record, ApprovalLog)
    assert [r.approval_id for r in results] == ["apr-001", "apr-002"]
    assert results[0].action == "approved"
    assert results[0].actor == "alice"
    assert results[1].action == "denied"
    assert results[1].actor == "bob"

    assert fake_client.kv_list_prefixes == ["approval-history/apr-stream/"]
    assert fake_client.closed


@pytest.mark.asyncio
async def test_list_approval_history_filters_by_since_and_status(
    fake_client: _FakeMCPClient,
) -> None:
    """The live KV surface lists by prefix only, so the filters are local."""
    fake_client.items = _store(
        [
            (
                "approval-history/apr-old/20260701T000000000000Z-cccc3333",
                _payload("apr-old", action="approved", at=datetime(2026, 7, 1, tzinfo=UTC)),
            ),
            (
                "approval-history/apr-new/20260901T000000000000Z-dddd4444",
                _payload("apr-new", action="approved", at=datetime(2026, 9, 1, tzinfo=UTC)),
            ),
            (
                "approval-history/apr-denied/20260901T000000000000Z-eeee5555",
                _payload("apr-denied", action="denied", at=datetime(2026, 9, 1, tzinfo=UTC)),
            ),
        ]
    )

    results = await list_approval_history(
        approval_id="apr-stream",
        since="2026-08-01",
        status="approved",
        token=TOKEN,
    )

    assert [r.approval_id for r in results] == ["apr-new"]


@pytest.mark.asyncio
async def test_list_approval_history_returns_empty_when_substrate_unreachable(
    fake_client: _FakeMCPClient,
) -> None:
    """A substrate that cannot be reached returns [] and warns."""
    fake_client.raise_on_list = RuntimeError("connection refused")

    with capture_logs() as logs:
        results = await list_approval_history(
            approval_id="apr-stream",
            since=None,
            status=None,
            token=TOKEN,
        )

    assert results == []
    skipped = [entry for entry in logs if entry["event"] == "approval_list_skipped"]
    assert len(skipped) == 1, logs
    assert skipped[0]["extra"]["approval_id"] == "apr-stream"
    # The WARNING must not carry exception text.
    assert "Traceback" not in json.dumps(skipped[0]["extra"])


@pytest.mark.asyncio
async def test_list_approval_history_skips_invalid_payloads(
    fake_client: _FakeMCPClient,
) -> None:
    """One valid + one invalid payload -> returns only the valid struct."""
    fake_client.items = _store(
        [
            (
                "approval-history/apr-good/20260810T120000000000Z-ffff6666",
                _payload("apr-good", action="approved", actor="alice"),
            ),
            (
                "approval-history/apr-bad/20260810T120000000000Z-9999aaaa",
                {
                    "approval_id": "apr-bad",
                    "action": "not_a_real_action",  # fails Literal validation
                    "actor": "carol",
                    "at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC).isoformat(),
                    "metadata": {},
                },
            ),
        ]
    )

    results = await list_approval_history(
        approval_id="apr-stream",
        since=None,
        status=None,
        token=TOKEN,
    )

    assert len(results) == 1
    assert isinstance(results[0], ApprovalLog)
    assert results[0].approval_id == "apr-good"


@pytest.mark.asyncio
async def test_list_entry_skipped_log_carries_bound_exception_type(
    fake_client: _FakeMCPClient,
) -> None:
    """`approval_list_entry_skipped` log carries the bound exc type, not a constant string.

    Regression guard for the constant-string bug:
    `type(msgspec.ValidationError).__name__` evaluates to the literal
    string "ValidationError" because the surrounding `except` already
    narrowed the type. The fix binds the exception as ``exc`` and logs
    ``type(exc).__name__``.
    """
    fake_client.items = _store(
        [
            (
                "approval-history/apr-bad/20260810T120000000000Z-9999aaaa",
                {
                    "approval_id": "apr-bad",
                    "action": "not_a_real_action",  # fails Literal validation
                    "actor": "carol",
                    "at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC).isoformat(),
                    "metadata": {},
                },
            ),
        ]
    )

    with capture_logs() as logs:
        results = await list_approval_history(
            approval_id="apr-stream",
            since=None,
            status=None,
            token=TOKEN,
        )

    # Partial-failure resilience still holds.
    assert results == []

    skipped = [entry for entry in logs if entry["event"] == "approval_list_entry_skipped"]
    assert len(skipped) == 1, logs
    assert skipped[0]["extra"]["reason"] == "ValidationError"
    assert "Traceback" not in json.dumps(skipped[0]["extra"])


@pytest.mark.asyncio
async def test_list_approval_history_rejects_missing_token(
    fake_client: _FakeMCPClient,
) -> None:
    """RBAC gate: missing token returns [] before any MCP call.

    Multi-agent review flagged HIGH-severity missing auth on this read
    path. The gate must short-circuit before the substrate is queried.
    """
    with capture_logs() as logs:
        result = await list_approval_history(
            approval_id="apr-1",
            since=None,
            status=None,
            token=None,
        )

    assert result == []
    assert not fake_client.kv_list_prefixes
    skipped = [entry for entry in logs if entry["event"] == "approval_list_skipped"]
    assert skipped, logs
    assert skipped[-1]["extra"]["reason"] == "rbac_denied"


@pytest.mark.asyncio
async def test_list_approval_history_rejects_non_jwt_token(
    fake_client: _FakeMCPClient,
) -> None:
    """RBAC gate: a non-JWT-shaped token is rejected as malformed.

    The check is JWT-shape presence (three dot-separated segments). A
    single-segment string looks like a token but is not a JWT — must be
    rejected.
    """
    result = await list_approval_history(
        approval_id="apr-2",
        since=None,
        status=None,
        token="not-a-jwt",
    )

    assert result == []
    assert not fake_client.kv_list_prefixes


@pytest.mark.asyncio
async def test_list_approval_history_passes_with_jwt_shaped_token(
    fake_client: _FakeMCPClient,
) -> None:
    """With a JWT-shaped token the RBAC gate passes and the substrate is queried."""
    fake_client.items = _store(
        [
            (
                "approval-history/apr-3/20260810T120000000000Z-bbbb7777",
                _payload("apr-3", action="approved", actor="reviewer-1"),
            )
        ]
    )

    result = await list_approval_history(
        approval_id="apr-3",
        since=None,
        status=None,
        token=TOKEN,
    )

    assert fake_client.kv_list_prefixes == ["approval-history/apr-3/"]
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], ApprovalLog)
    assert result[0].approval_id == "apr-3"
