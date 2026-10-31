"""Verify approval_log round-trips: write then read returns equal struct.

End-to-end check of the validate-on-write + validate-on-read contract between
``mahavishnu.core.approval.decision_writer.record_approval_decision`` (Task 1
producer) and ``mahavishnu.cli.approval_cli.list_approval_history`` (Task 2
consumer).

The producer writes through the in-process substrate facade
(:mod:`mahavishnu.core.substrate`) into the server's own process-local KV
store (:mod:`mahavishnu.core.kv_store`). The consumer is the one reader that
lives *outside* the server process, so it reaches the records through the
server's public KV surface over HTTP. The test runs both halves in one
process and stubs only that network hop — the KV read is answered from the
same store the producer wrote to, so the data path stays real end to end.
The store is cleared around every test by the autouse
``_clean_substrate_store`` fixture in ``tests/conftest.py``.

The store holds **one value per key**, so each decision is written under
its own key inside the ``approval-history/{approval_id}/`` namespace. The
consumer lists that namespace by prefix, so the history is append-only:
a second decision for the same ``approval_id`` joins the first rather than
replacing it.
"""

from __future__ import annotations

import secrets
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from mahavishnu.cli.approval_cli import list_approval_history
from mahavishnu.core.approval.decision_writer import record_approval_decision
from mahavishnu.core.kv_store import kv_store
from mahavishnu.core.models.persistence import ApprovalLog
from mahavishnu.core.permissions import JWTManager

if TYPE_CHECKING:
    from mahavishnu.core.config import MahavishnuSettings

#: A per-session JWT secret for the tests. Generated rather than
#: hard-coded so no secret-shaped literal is committed to the repository.
TEST_SECRET = secrets.token_urlsafe(32)


def _settings() -> SimpleNamespace:
    """Return the settings shape the CLI reads (auth + health + tools)."""
    return SimpleNamespace(
        auth=SimpleNamespace(
            secret=TEST_SECRET,
            algorithm="HS256",
            expire_minutes=60,
        ),
        health=SimpleNamespace(dependencies={}),
        tools=SimpleNamespace(mcp_server_url=None),
    )


def _token(user_id: str = "reviewer-1") -> str:
    """Mint a real, signed access token for ``user_id``.

    The consumer verifies the caller's token before it reads, so the
    test must present a credential this server signed — a JWT-shaped
    string is not one.
    """
    return JWTManager(cast("MahavishnuSettings", _settings())).create_token(user_id)


_TOKEN = _token()


@pytest.fixture(autouse=True)
def _server_kv_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answer the consumer's KV read from the server's own store.

    The consumer reaches the records through the server's public KV surface
    over HTTP. The test stubs that hop at the client boundary and answers
    from the process-local store the producer wrote to — the transport is
    faked, the data path is not.
    """
    from mahavishnu.core import bootstrap, mcp_adapter

    class _StubMCPClient:
        """Stand-in for the HTTP client the consumer uses to reach the server."""

        def __init__(self, base_url: str = "", **kwargs: Any) -> None:
            self.base_url = base_url

        async def kv_list(
            self,
            prefix: str,
            user_id: str | None = None,
        ) -> list[tuple[str, str]]:
            # The server would apply the namespace's permission to
            # ``user_id``; the stub answers the read the caller was
            # authorized to make.
            return kv_store.list_prefix(prefix)

        async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
            if name == "mahavishnu_kv_list":
                items = [
                    {"key": key, "value": value}
                    for key, value in kv_store.list_prefix(str(arguments.get("prefix", "")))
                ]
                return {"ok": True, "items": items, "count": len(items)}
            if name == "mahavishnu_kv_get":
                return {"ok": True, "value": kv_store.get(str(arguments.get("key", "")))}
            raise AssertionError(f"unexpected tool call in the approval round trip: {name}")

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(mcp_adapter, "MCPClient", _StubMCPClient)
    monkeypatch.setattr(
        bootstrap,
        "resolve_mcp_url",
        lambda _settings: "http://127.0.0.1:8680/mcp",
    )
    monkeypatch.setattr("mahavishnu.core.config.get_settings", _settings)


async def test_approval_log_round_trips_with_struct_equality() -> None:
    """Producer writes; consumer reads; struct equality holds end-to-end."""
    written = record_approval_decision(
        approval_id="apr-roundtrip",
        decision="approved",
        rationale="All checks pass — round-trip integration test",
        decided_by="alice",
        metadata={"selected_option": 1, "ticket": "OPS-99"},
    )

    assert isinstance(written, ApprovalLog)
    # Producer persisted the record under the documented path prefix.
    assert kv_store.list_prefix("approval-history/apr-roundtrip/") != []

    results = await list_approval_history(
        approval_id="apr-roundtrip",
        since=None,
        status=None,
        token=_TOKEN,
    )

    assert len(results) == 1
    assert isinstance(results[0], ApprovalLog)
    # msgspec.Struct equality is structural: every field matches.
    assert results[0] == written
    # ...and the documented substrate fields round-trip verbatim.
    assert results[0].approval_id == "apr-roundtrip"
    assert results[0].action == "approved"
    assert results[0].actor == "alice"
    assert results[0].metadata["selected_option"] == 1
    assert results[0].metadata["ticket"] == "OPS-99"
    assert results[0].metadata["rationale"] == ("All checks pass — round-trip integration test")


async def test_approval_log_round_trip_with_status_filter() -> None:
    """``status`` filter narrows the read-back to matching action values."""
    record_approval_decision(
        approval_id="apr-filter",
        decision="approved",
        rationale="Approved decision",
        decided_by="alice",
    )

    approved = await list_approval_history(
        approval_id="apr-filter",
        since=None,
        status="approved",
        token=_TOKEN,
    )
    denied = await list_approval_history(
        approval_id="apr-filter",
        since=None,
        status="denied",
        token=_TOKEN,
    )
    all_records = await list_approval_history(
        approval_id="apr-filter",
        since=None,
        status=None,
        token=_TOKEN,
    )

    assert len(approved) == 1
    assert approved[0].action == "approved"
    assert approved[0].actor == "alice"
    # A non-matching action filters the record out.
    assert denied == []
    # status=None returns every record under the prefix.
    assert len(all_records) == 1
    assert all_records[0].action == "approved"


async def test_approval_log_round_trip_appends_rather_than_replacing() -> None:
    """The approval history is append-only: a second decision joins the first.

    The store holds one value per key, so each decision is written under
    its own key inside the ``approval-history/{approval_id}/`` namespace.
    The consumer lists the namespace by prefix, so both decisions survive
    — and they come back in chronological order.
    """
    record_approval_decision(
        approval_id="apr-rewrite",
        decision="approved",
        rationale="First decision",
        decided_by="alice",
    )
    record_approval_decision(
        approval_id="apr-rewrite",
        decision="denied",
        rationale="Second decision",
        decided_by="bob",
    )

    results = await list_approval_history(
        approval_id="apr-rewrite",
        since=None,
        status=None,
        token=_TOKEN,
    )

    assert len(results) == 2
    assert [record.action for record in results] == ["approved", "denied"]
    assert [record.actor for record in results] == ["alice", "bob"]
    assert results[1].metadata["rationale"] == "Second decision"
    # Two distinct keys inside the one namespace.
    assert len(kv_store.list_prefix("approval-history/apr-rewrite/")) == 2


async def test_approval_log_round_trip_isolates_per_approval_id() -> None:
    """Each ``approval_id`` has its own substrate prefix — read-back is scoped to the requested ID."""
    record_approval_decision(
        approval_id="apr-100",
        decision="approved",
        rationale="One",
        decided_by="alice",
    )
    record_approval_decision(
        approval_id="apr-200",
        decision="approved",
        rationale="Two",
        decided_by="alice",
    )

    first = await list_approval_history(
        approval_id="apr-100", since=None, status=None, token=_TOKEN
    )
    second = await list_approval_history(
        approval_id="apr-200", since=None, status=None, token=_TOKEN
    )

    assert len(first) == 1
    assert first[0].approval_id == "apr-100"
    assert first[0].metadata["rationale"] == "One"
    assert len(second) == 1
    assert second[0].approval_id == "apr-200"
    assert second[0].metadata["rationale"] == "Two"
    # Cross-check the substrate-level invariant: each approval has its own
    # namespace, and neither leaks into the other.
    assert {key for key, _ in kv_store.list_prefix("approval-history/")} != set()
    assert {key for key, _ in kv_store.list_prefix("approval-history/apr-100/")} != set()
    assert {key for key, _ in kv_store.list_prefix("approval-history/apr-200/")} != set()
    assert not kv_store.list_prefix("approval-history/apr-300/")


async def test_approval_log_round_trip_default_metadata_round_trips() -> None:
    """When the caller omits ``metadata``, the producer defaults to an empty dict and the round-trip preserves it."""
    written = record_approval_decision(
        approval_id="apr-default-meta",
        decision="requested",
        rationale="Needs operator review",
        decided_by="system",
    )

    assert written.metadata == {"rationale": "Needs operator review"}

    results = await list_approval_history(
        approval_id="apr-default-meta",
        since=None,
        status=None,
        token=_TOKEN,
    )

    assert len(results) == 1
    assert results[0] == written
    assert results[0].metadata == {"rationale": "Needs operator review"}
