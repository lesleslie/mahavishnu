"""Peer-affinity pool resolution.

Phase 1.5 Item 2: surfaces a recommended pool_id for a
``(peer_id, project_id)`` pair by reading the Session-Buddy
``user_models`` table via the ``peer_context`` MCP tool contract.

Per the plan's A3 architecture decision, **ACL is authoritative**:
a missing ``peer_models:read`` grant short-circuits to ``None`` so
the caller falls back to ``LEAST_LOADED``. The peer model is only
a hint, never an override of the access policy.

The ``representation_text`` is parsed with a simple regex for
``pool: <pool_id>`` per Q1 option (a) — no LLM call. We can move to
a structured column once the LLM-derived hints are accurate enough
to justify the migration cost.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


# ``pool: <pool_id>`` — lowercase prefix, ASCII pool id (letters,
# digits, underscore, dash). Whitespace around the id is trimmed.
# The pattern is intentionally case-sensitive (lowercase only) to
# avoid false positives on sentences like "the pool: ...is cold".
POOL_HINT_PATTERN = re.compile(r"\bpool:\s*([A-Za-z0-9_\-]+)\s*")

# ACL scope required to read peer models. Cross-component consumers
# (Mahavishnu routing, Akosha analytics) must hold this grant.
PEER_MODELS_READ_SCOPE = "peer_models:read"


def has_pool_acl_grant(acl: dict[str, Any] | None) -> bool:
    """Return True if the caller holds the ``peer_models:read`` grant.

    A3 (peer model is a hint, ACL is authoritative): this is the
    structural gate checked BEFORE the peer context lookup.

    Args:
        acl: Mapping of scope -> truthy grant. None/empty/None-valued
            maps all deny access.

    Returns:
        True if a ``peer_models:read`` grant is present and truthy.
    """
    if not acl:
        return False
    return bool(acl.get(PEER_MODELS_READ_SCOPE))


def parse_pool_hint(representation_text: str | None) -> str | None:
    """Extract the first ``pool: <id>`` hint from a representation text.

    Per Q1 option (a): free-form ``pool: <pool_id>`` is the hint
    format. The pattern is intentionally narrow — the heuristic
    must be predictable for callers that seed the representation
    text and predictable for tests that assert on it.

    Args:
        representation_text: Free-form peer model summary from
            Session-Buddy's ``user_models`` table. May be None or
            empty (no row exists).

    Returns:
        The first matching pool_id, or None if no hint is found.
    """
    if not representation_text:
        return None
    match = POOL_HINT_PATTERN.search(representation_text)
    if match is None:
        return None
    return match.group(1)


class PeerRouteResolver:
    """Resolve a pool_id for a (peer_id, project_id) pair from Session-Buddy.

    The resolver is a thin async wrapper around a duck-typed
    ``session_buddy_client`` — any object with an
    ``async def peer_context(peer_id, project_id)`` method works.
    This keeps the unit tests free of any Session-Buddy import.

    The resolver is intentionally LLM-free: it parses the peer
    model's ``representation_text`` with a regex. If the future
    moves to a structured column (``user_models.recommended_pool_id``),
    only ``_fetch_pool_hint`` needs to change.

    Args:
        session_buddy_client: Duck-typed client with
            ``async peer_context(peer_id, project_id) -> dict``.
            The returned dict must include a ``representation_text``
            key (may be None when no peer model row exists).
        acl_provider: Callable returning the per-peer ACL map, or
            None when the caller is not granted. Defaults to a
            permissive grant (caller already gated the user).
    """

    def __init__(
        self,
        session_buddy_client: Any,
        acl_provider: Callable[[str], dict[str, Any] | None] | None = None,
    ) -> None:
        self._client = session_buddy_client
        # Default ACL provider grants access — useful when the
        # caller (PoolManager) has already done an upstream ACL
        # check and only wants the peer model lookup.
        self._acl_provider: Callable[[str], dict[str, Any] | None] = (
            acl_provider if acl_provider is not None else lambda _peer_id: {PEER_MODELS_READ_SCOPE: True}
        )

    async def resolve_pool(
        self,
        peer_id: str,
        project_id: str,
    ) -> str | None:
        """Return the pool_id the peer model recommends, or None.

        A3: if the caller has no ``peer_models:read`` grant for
        ``peer_id``, this returns None WITHOUT consulting
        Session-Buddy. The caller (PoolManager) is expected to
        fall back to ``LEAST_LOADED`` in that case.

        Args:
            peer_id: Stable peer identifier (Honcho convention).
            project_id: Project scope for the peer model.

        Returns:
            The recommended pool_id, or None when:
              - the peer has no ACL grant (A3)
              - no peer model row exists for (peer_id, project_id)
              - the representation_text has no ``pool: <id>`` hint
              - Session-Buddy raises (graceful degradation)
        """
        if not has_pool_acl_grant(self._acl_provider(peer_id)):
            logger.debug(
                "peer_route_acl_denied: peer_id=%r project_id=%r",
                peer_id,
                project_id,
            )
            return None

        try:
            context = await self._client.peer_context(
                peer_id=peer_id,
                project_id=project_id,
            )
        except Exception as exc:
            logger.warning(
                "peer_route_session_buddy_failure: peer_id=%r project_id=%r err=%s",
                peer_id,
                project_id,
                exc,
            )
            return None

        if not isinstance(context, dict):
            logger.debug(
                "peer_route_unexpected_context_type: peer_id=%r type=%s",
                peer_id,
                type(context).__name__,
            )
            return None

        return parse_pool_hint(context.get("representation_text"))


__all__ = [
    "PEER_MODELS_READ_SCOPE",
    "POOL_HINT_PATTERN",
    "PeerRouteResolver",
    "has_pool_acl_grant",
    "parse_pool_hint",
]


# Type-only re-export to keep the import surface tight. The Awaitable
# import is here for callers that want to type-annotate the resolver's
# return value as an awaitable (e.g. ``Awaitable[str | None]``).
_ = Awaitable
