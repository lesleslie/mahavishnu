"""Verify list_approval_history reads MCP payloads and returns typed ApprovalLog structs.

The reader is the one substrate call site that runs **outside** the
server process, so it reads through the server's public KV surface over
HTTP rather than the in-process facade (which would answer from the
CLI's own, empty, store). The tests stub the MCP client the CLI builds.

Authorization: the CLI **verifies** the caller's bearer token against the
configured JWT secret and reads as the principal that token names — it
never reads as the internal self-call principal. A JWT-shaped string is
not a credential, so the tests mint real tokens.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest
from structlog.testing import capture_logs

from mahavishnu.cli.approval_cli import list_approval_history
from mahavishnu.core.models.persistence import ApprovalLog
from mahavishnu.core.permissions import JWTManager

if TYPE_CHECKING:
    from mahavishnu.core.config import MahavishnuSettings

#: A 40-character secret — JWTManager requires at least 32.
TEST_SECRET = "test-secret-for-approval-cli-unit-tests-0123456789"


def _settings() -> SimpleNamespace:
    """Return the settings shape the CLI reads.

    The CLI imports ``get_settings`` lazily inside the function, so
    patching ``mahavishnu.core.config.get_settings`` reaches it. The
    stub carries both the auth config ``JWTManager`` reads and the
    health/tools config ``resolve_mcp_url`` reads.
    """
    return SimpleNamespace(
        auth=SimpleNamespace(
            secret=TEST_SECRET,
            algorithm="HS256",
            expire_minutes=60,
        ),
        health=SimpleNamespace(dependencies={}),
        tools=SimpleNamespace(mcp_server_url=None),
    )


@pytest.fixture(autouse=True)
def _auth_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give the CLI a configured JWT secret."""
    monkeypatch.setattr("mahavishnu.core.config.get_settings", _settings)


def _token(user_id: str = "alice") -> str:
    """Mint a real, signed access token for ``user_id``."""
    return JWTManager(cast("MahavishnuSettings", _settings())).create_token(user_id)


class _FakeMCPClient:
    """Stand-in for ``mahavishnu.core.mcp_adapter.MCPClient``.

    The CLI imports the client lazily inside the function, so patching
    the attribute on the source module reaches it.
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        token: str | None = None,
        internal: bool = False,
    ) -> None:
        self.base_url = base_url
        self.token = token
        self.internal = internal
        self.kv_list_prefixes: list[str] = []
        self.kv_list_users: list[str | None] = []
        self.closed = False
        self.items: list[tuple[str, str]] = []
        self.raise_on_list: Exception | None = None

    async def kv_list(
        self,
        prefix: str,
        user_id: str | None = None,
    ) -> list[tuple[str, str]]:
        self.kv_list_prefixes.append(prefix)
        self.kv_list_users.append(user_id)
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
        base_url: str,
        timeout: float = 30.0,
        token: str | None = None,
        internal: bool = False,
    ) -> _FakeMCPClient:
        instance.base_url = base_url
        instance.token = token
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
                "approval-history/apr-stream/20260810T120000000000Z-aaaa1111",
                _payload("apr-stream", action="approved", actor="alice"),
            ),
            (
                "approval-history/apr-stream/20260811T120000000000Z-bbbb2222",
                _payload("apr-stream", action="denied", actor="bob"),
            ),
        ]
    )

    results = await list_approval_history(
        approval_id="apr-stream",
        since=None,
        status=None,
        token=_token(),
    )

    assert isinstance(results, list)
    assert len(results) == 2
    for record in results:
        assert isinstance(record, ApprovalLog)
    assert [r.approval_id for r in results] == ["apr-stream", "apr-stream"]
    assert results[0].action == "approved"
    assert results[0].actor == "alice"
    assert results[1].action == "denied"
    assert results[1].actor == "bob"

    assert fake_client.kv_list_prefixes == ["approval-history/apr-stream/"]
    assert fake_client.closed


@pytest.mark.asyncio
async def test_read_is_performed_as_the_verified_caller(
    fake_client: _FakeMCPClient,
) -> None:
    """The read runs as the principal the token names — not the internal one."""
    fake_client.items = _store([("approval-history/apr-1/x", _payload("apr-1", action="approved"))])

    await list_approval_history(
        approval_id="apr-1",
        since=None,
        status=None,
        token=_token("reviewer-7"),
    )

    assert fake_client.kv_list_users == ["reviewer-7"]
    # The internal self-call principal is NOT used for a user-facing read.
    assert fake_client.internal is False


@pytest.mark.asyncio
async def test_list_approval_history_filters_by_since_and_status(
    fake_client: _FakeMCPClient,
) -> None:
    """The live KV surface lists by prefix only, so the filters are local."""
    fake_client.items = _store(
        [
            (
                "approval-history/apr-stream/20260701T000000000000Z-cccc3333",
                _payload(
                    "apr-stream",
                    action="approved",
                    at=datetime(2026, 7, 1, tzinfo=UTC),
                ),
            ),
            (
                "approval-history/apr-stream/20260901T000000000000Z-dddd4444",
                _payload(
                    "apr-stream",
                    action="approved",
                    at=datetime(2026, 9, 1, tzinfo=UTC),
                ),
            ),
            (
                "approval-history/apr-stream/20260901T000000000000Z-eeee5555",
                _payload(
                    "apr-stream",
                    action="denied",
                    at=datetime(2026, 9, 1, tzinfo=UTC),
                ),
            ),
        ]
    )

    results = await list_approval_history(
        approval_id="apr-stream",
        since="2026-08-01",
        status="approved",
        token=_token(),
    )

    assert len(results) == 1
    assert results[0].action == "approved"
    assert results[0].at == datetime(2026, 9, 1, tzinfo=UTC)


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
            token=_token(),
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
                "approval-history/apr-stream/20260810T120000000000Z-ffff6666",
                _payload("apr-stream", action="approved", actor="alice"),
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
        token=_token(),
    )

    assert len(results) == 1
    assert isinstance(results[0], ApprovalLog)
    assert results[0].approval_id == "apr-stream"


@pytest.mark.asyncio
async def test_list_approval_history_skips_a_record_for_another_approval(
    fake_client: _FakeMCPClient,
) -> None:
    """A record whose ``approval_id`` does not match the request is skipped.

    Defence in depth: the key namespace scopes the read, but the record
    inside must still belong to the approval the caller asked about.
    """
    fake_client.items = _store([("approval-history/apr-stream/x", _payload("some-other-approval"))])

    with capture_logs() as logs:
        results = await list_approval_history(
            approval_id="apr-stream",
            since=None,
            status=None,
            token=_token(),
        )

    assert results == []
    skipped = [entry for entry in logs if entry["event"] == "approval_list_entry_skipped"]
    assert len(skipped) == 1, logs
    assert skipped[0]["extra"]["reason"] == "approval_id_mismatch"


@pytest.mark.asyncio
async def test_list_entry_skipped_log_carries_bound_exception_type(
    fake_client: _FakeMCPClient,
) -> None:
    """`approval_list_entry_skipped` log carries the bound exc type.

    Regression guard for the constant-string bug:
    `type(msgspec.ValidationError).__name__` evaluates to the literal
    string "ValidationError" because the surrounding `except` already
    narrowed the type. The fix binds the exception as ``exc`` and logs
    ``type(exc).__name__``.
    """
    fake_client.items = _store(
        [
            (
                "approval-history/apr-bad/x",
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
            token=_token(),
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
    """A missing token is refused before any substrate call.

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
    assert skipped[-1]["extra"]["reason"] == "missing_token"


@pytest.mark.asyncio
async def test_list_approval_history_rejects_an_unsigned_token(
    fake_client: _FakeMCPClient,
) -> None:
    """A JWT-shaped string this server did not sign is not a credential.

    The retired substrate accepted any three-segment string. A token
    signed with a *different* secret must be refused.
    """
    import jwt as pyjwt

    forged = pyjwt.encode(
        {"user_id": "attacker", "exp": 9999999999},
        "a-different-secret-that-is-long-enough-0123456789",
        algorithm="HS256",
    )

    result = await list_approval_history(
        approval_id="apr-2",
        since=None,
        status=None,
        token=forged,
    )

    assert result == []
    assert not fake_client.kv_list_prefixes


@pytest.mark.asyncio
async def test_list_approval_history_rejects_a_non_jwt_token(
    fake_client: _FakeMCPClient,
) -> None:
    """A non-JWT-shaped token is rejected as malformed."""
    result = await list_approval_history(
        approval_id="apr-2",
        since=None,
        status=None,
        token="not-a-jwt",
    )

    assert result == []
    assert not fake_client.kv_list_prefixes


@pytest.mark.asyncio
async def test_list_approval_history_passes_with_a_valid_token(
    fake_client: _FakeMCPClient,
) -> None:
    """With a valid token the read proceeds against the substrate."""
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
        token=_token("reviewer-1"),
    )

    assert fake_client.kv_list_prefixes == ["approval-history/apr-3/"]
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], ApprovalLog)
    assert result[0].approval_id == "apr-3"
