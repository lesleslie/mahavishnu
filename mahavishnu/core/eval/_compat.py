"""Compatibility shims for the oneiric action-kit primitives the eval
framework needs.

Phase 1 needs exactly one primitive: content hashing. The oneiric action
``oneiric.actions.compression.HashAction`` covers it, so this module is a
thin wrapper rather than a hand-rolled implementation — there is no
``link_to_issue`` note to carry because nothing is missing.

Keeping the dependency behind one function means a future oneiric change
is a one-file edit here rather than a change at every call site. If the
action is ever removed, replace the body of :func:`hash_content` with a
``hashlib.sha256`` implementation and note the upstream issue in this
docstring.
"""

from __future__ import annotations

from oneiric.actions.compression import HashAction


async def hash_content(content: str) -> str:
    """Return the lowercase hex sha256 digest of ``content``.

    Args:
        content: The text to hash.

    Returns:
        The hex digest produced by ``oneiric.actions.compression.HashAction``.
    """
    result = await HashAction().execute({"algorithm": "sha256", "data": content})
    return str(result["digest"])
