"""Unit tests for PeerRouteResolver.

The resolver consults Session-Buddy's ``user_models`` table (or the
``peer_context`` MCP tool) to surface a recommended pool_id for a
(peer_id, project_id) pair. Per A3 (peer model is a hint, ACL is
authoritative): ACL is checked FIRST; a missing ACL grant short-
circuits to None so the caller can fall back to LEAST_LOADED.

The ``representation_text`` is parsed with a simple regex for
``pool: <pool_id>`` (Q1 option (a) — no LLM call).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.pools.peer_routing import (
    DEFAULT_ACL_PROVIDER,
    POOL_HINT_PATTERN,
    PeerRouteResolver,
    has_pool_acl_grant,
)


class TestPoolHintRegex:
    """Q1 option (a) — the representation_text hint format."""

    def test_pool_hint_matches_simple_form(self) -> None:
        text = "Alice prefers Python and FastAPI. pool: pool_abc"
        match = POOL_HINT_PATTERN.search(text)
        assert match is not None
        assert match.group(1) == "pool_abc"

    def test_pool_hint_matches_standalone(self) -> None:
        text = "pool: pool_xyz123"
        match = POOL_HINT_PATTERN.search(text)
        assert match is not None
        assert match.group(1) == "pool_xyz123"

    def test_pool_hint_missing_returns_none(self) -> None:
        text = "Alice prefers Python. No pool hint here."
        match = POOL_HINT_PATTERN.search(text)
        assert match is None

    def test_pool_hint_is_case_sensitive_lowercase(self) -> None:
        # The hint format is `pool:` lowercase — Q1's spec uses lowercase.
        text = "Pool: pool_abc"
        match = POOL_HINT_PATTERN.search(text)
        # Uppercase 'Pool:' is NOT a hint (avoids false positives on
        # sentences like "the pool: ...is too cold").
        assert match is None


class TestHasPoolAclGrant:
    """A3 — ACL is the structural gate. Must be checked BEFORE the hint."""

    def test_no_acl_returns_false(self) -> None:
        assert has_pool_acl_grant(acl=None) is False
        assert has_pool_acl_grant(acl={}) is False
        assert has_pool_acl_grant(acl={"some_other_scope": "read"}) is False

    def test_acl_with_peer_models_read_returns_true(self) -> None:
        acl = {"peer_models:read": True}
        assert has_pool_acl_grant(acl=acl) is True

    def test_acl_with_string_grant_returns_true(self) -> None:
        acl = {"peer_models:read": "granted"}
        assert has_pool_acl_grant(acl=acl) is True

    def test_acl_with_explicit_false_returns_false(self) -> None:
        acl = {"peer_models:read": False}
        assert has_pool_acl_grant(acl=acl) is False


class TestPeerRouteResolver:
    """PeerRouteResolver delegates to a Session-Buddy peer_context call.

    The Session-Buddy client is duck-typed: any object with an
    async ``peer_context(peer_id, project_id)`` method works. The
    unit tests use AsyncMock.
    """

    @pytest.mark.asyncio
    async def test_no_acl_returns_none(self) -> None:
        """A3: no ACL grant → resolver returns None (caller falls back to LEAST_LOADED)."""
        client = MagicMock()
        resolver = PeerRouteResolver(
            session_buddy_client=client,
            acl_provider=lambda _peer_id: None,  # no grant
        )
        result = await resolver.resolve_pool(
            peer_id="alice",
            project_id="proj-x",
        )
        assert result is None
        # The peer_context client should NOT be called when ACL is missing.
        client.peer_context.assert_not_called()

    @pytest.mark.asyncio
    async def test_acl_grant_with_pool_hint_returns_pool_id(self) -> None:
        client = MagicMock()
        client.peer_context = AsyncMock(
            return_value={
                "peer_id": "alice",
                "project_id": "proj-x",
                "representation_text": "Alice is a Python developer. pool: pool_abc",
                "last_updated": "2026-06-01T00:00:00Z",
                "evidence_count": 5,
                "model": "heuristic",
            }
        )
        resolver = PeerRouteResolver(
            session_buddy_client=client,
            acl_provider=lambda _peer_id: {"peer_models:read": True},
        )
        result = await resolver.resolve_pool(peer_id="alice", project_id="proj-x")
        assert result == "pool_abc"
        client.peer_context.assert_awaited_once_with(peer_id="alice", project_id="proj-x")

    @pytest.mark.asyncio
    async def test_acl_grant_without_pool_hint_returns_none(self) -> None:
        """If representation_text has no pool hint, return None (caller falls back)."""
        client = MagicMock()
        client.peer_context = AsyncMock(
            return_value={
                "peer_id": "alice",
                "project_id": "proj-x",
                "representation_text": "Alice is a Python developer.",
                "last_updated": "2026-06-01T00:00:00Z",
                "evidence_count": 5,
                "model": "heuristic",
            }
        )
        resolver = PeerRouteResolver(
            session_buddy_client=client,
            acl_provider=lambda _peer_id: {"peer_models:read": True},
        )
        result = await resolver.resolve_pool(peer_id="alice", project_id="proj-x")
        assert result is None

    @pytest.mark.asyncio
    async def test_acl_grant_with_no_peer_model_row_returns_none(self) -> None:
        """If Session-Buddy returns an empty/None representation_text, no hint exists."""
        client = MagicMock()
        client.peer_context = AsyncMock(
            return_value={
                "peer_id": "alice",
                "project_id": "proj-x",
                "representation_text": None,
                "last_updated": None,
                "evidence_count": 0,
                "model": "heuristic",
            }
        )
        resolver = PeerRouteResolver(
            session_buddy_client=client,
            acl_provider=lambda _peer_id: {"peer_models:read": True},
        )
        result = await resolver.resolve_pool(peer_id="alice", project_id="proj-x")
        assert result is None

    @pytest.mark.asyncio
    async def test_session_buddy_failure_returns_none(self) -> None:
        """Session-Buddy outage must not crash the router — return None to fall back."""
        client = MagicMock()
        client.peer_context = AsyncMock(side_effect=RuntimeError("Session-Buddy down"))
        resolver = PeerRouteResolver(
            session_buddy_client=client,
            acl_provider=lambda _peer_id: {"peer_models:read": True},
        )
        result = await resolver.resolve_pool(peer_id="alice", project_id="proj-x")
        assert result is None

    @pytest.mark.asyncio
    async def test_pool_id_is_trimmed(self) -> None:
        """`pool:   pool_abc ` (with extra whitespace) should still resolve cleanly."""
        client = MagicMock()
        client.peer_context = AsyncMock(
            return_value={
                "representation_text": "Alice likes FastAPI.  pool:   pool_xyz   ",
            }
        )
        resolver = PeerRouteResolver(
            session_buddy_client=client,
            acl_provider=lambda _peer_id: {"peer_models:read": True},
        )
        result = await resolver.resolve_pool(peer_id="alice", project_id="proj-x")
        assert result == "pool_xyz"


class TestPeerRouteResolverDefaultAclProvider:
    """Secure-by-default: when ``acl_provider`` is omitted, the resolver
    uses the deny-everyone default. Per the security review on
    Item 2's commit, the previous permissive default (granting
    ``peer_models:read`` to every peer) was a HIGH-severity finding.
    This test pins the new behavior.
    """

    @pytest.mark.asyncio
    async def test_default_acl_provider_denies(self) -> None:
        client = MagicMock()
        client.peer_context = AsyncMock(return_value={"representation_text": "pool: pool_default"})
        resolver = PeerRouteResolver(session_buddy_client=client)
        result = await resolver.resolve_pool(peer_id="alice", project_id="proj-x")
        assert result is None, "Default ACL must deny; the peer hint must NOT be returned"
        # And the Session-Buddy client must NOT have been consulted
        # (the ACL gate short-circuits BEFORE the peer_context call).
        client.peer_context.assert_not_called()

    def test_default_acl_provider_identity_is_default(self) -> None:
        """The default ACL provider is the named sentinel so
        ``PoolManager.__init__`` can detect it by identity."""
        client = MagicMock()
        resolver = PeerRouteResolver(session_buddy_client=client)
        assert resolver._acl_provider is DEFAULT_ACL_PROVIDER

    def test_explicit_acl_provider_is_preserved(self) -> None:
        """Passing an explicit acl_provider overrides the default."""
        client = MagicMock()
        explicit = lambda _peer_id: {"peer_models:read": True}  # noqa: E731
        resolver = PeerRouteResolver(
            session_buddy_client=client,
            acl_provider=explicit,
        )
        assert resolver._acl_provider is explicit
        assert resolver._acl_provider is not DEFAULT_ACL_PROVIDER
