"""Tests for Goose session ID uniqueness.

The Mock adapter uses 8-char prefixes; per the security review (D3 BLOCKER
#10), 8-char prefixes collide after ~10K concurrent sessions. Goose defaults
to full UUID4 (36 chars) to avoid that. These tests assert:

- 10K consecutive ``launch_session`` calls produce no duplicate IDs.
- Each session ID is a UUID4 string of length 36 (with hyphens).
- The ``short`` format is still selectable for parity with Mock.

Req: REQ-GOO-005.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import httpx2 as httpx
import pytest
from pydantic import SecretStr

from mahavishnu.terminal.adapters.goose import GooseTerminalAdapter
from mahavishnu.terminal.goose_client import GooseHTTPClient

UUID4_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _build_client() -> GooseHTTPClient:
    """Build a client whose transport never sees a request."""

    def handler(request: httpx.Request) -> httpx.Response:
        # Should never fire — we only test ID generation, not the wire.
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return GooseHTTPClient(
        base_url="http://127.0.0.1:8694",
        secret_key=SecretStr("test-token"),
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.unit
def test_session_id_format_is_uuid4_by_default() -> None:
    """Each generated session ID is a 36-char UUID4 with hyphens.

    We use ``launch_session`` to drive the adapter — but mock the http
    transport so the test only measures ID generation, not network.
    """

    class _SessionCounter:
        def __init__(self) -> None:
            self.n = 0

        def __call__(self, request: httpx.Request) -> httpx.Response:
            self.n += 1
            return httpx.Response(201, json={"session_id": f"srv-{self.n}"})

    counter = _SessionCounter()
    transport = httpx.MockTransport(counter)
    client = GooseHTTPClient(
        base_url="http://127.0.0.1:8694",
        secret_key=SecretStr("test-token"),
        transport=transport,
    )
    adapter = GooseTerminalAdapter(client)

    # Generate 100 IDs locally (no network — _new_session_id is sync).
    ids = [adapter._new_session_id() for _ in range(100)]
    assert all(len(sid) == 36 for sid in ids), (
        f"expected UUID4 36-char strings, got samples: {ids[:3]}"
    )
    assert all(UUID4_PATTERN.match(sid) for sid in ids), (
        f"expected UUID4 pattern, got samples: {ids[:3]}"
    )


@pytest.mark.unit
async def test_10k_launch_session_produces_no_collisions() -> None:
    """Loop 10K launches; assert the returned IDs are unique.

    The 10K threshold mirrors the security review's collision-tolerance
    boundary for 8-char prefixes (D3 BLOCKER #10).
    """

    counter = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        return httpx.Response(201, json={"session_id": f"srv-{counter['n']}"})

    transport = httpx.MockTransport(handler)
    client = GooseHTTPClient(
        base_url="http://127.0.0.1:8694",
        secret_key=SecretStr("test-token"),
        transport=transport,
    )
    adapter = GooseTerminalAdapter(client)

    n = 10_000
    ids: set[str] = set()
    for _ in range(n):
        sid = await adapter.launch_session("bash")
        ids.add(sid)

    assert len(ids) == n, (
        f"expected {n} unique IDs, got {len(ids)} (collisions detected)"
    )
    assert all(len(sid) == 36 for sid in ids)


@pytest.mark.unit
def test_short_format_uses_8_char_prefix() -> None:
    """``session_id_format='short'`` produces 8-char prefixes (Mock parity)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"session_id": "srv"})

    client = GooseHTTPClient(
        base_url="http://127.0.0.1:8694",
        secret_key=SecretStr("test-token"),
        transport=httpx.MockTransport(handler),
    )
    adapter = GooseTerminalAdapter(client, session_id_format="short")
    # Generate many and assert all are 8 chars and unique within a small sample.
    ids = {adapter._new_session_id() for _ in range(50)}
    assert all(len(sid) == 8 for sid in ids)
    assert len(ids) == 50


@pytest.mark.unit
def test_invalid_session_id_format_rejected_at_init() -> None:
    client = _build_client()
    with pytest.raises(ValueError, match="session_id_format"):
        GooseTerminalAdapter(client, session_id_format="abcdefgh")  # type: ignore[arg-type]


@pytest.mark.unit
def test_default_format_unchanged_for_backcompat() -> None:
    """The adapter's default session_id_format is 'uuid' — locking that down."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"session_id": "srv"})

    client = GooseHTTPClient(
        base_url="http://127.0.0.1:8694",
        secret_key=SecretStr("test-token"),
        transport=httpx.MockTransport(handler),
    )
    adapter = GooseTerminalAdapter(client)
    assert adapter._session_id_format == "uuid"
