"""short_id derivation (UD5).

UD5: 6-hex short_id is the LAST 6 chars of the UUID v4 ID. The last 6 chars
encode the random node field — stable across rapid same-millisecond captures
(low collision probability). The first 6 chars encode the timestamp + version
portion of UUID v4, which is predictable and can collide.
"""
from __future__ import annotations


def short_id(event_id: str) -> str:
    """Return the last 6 hex chars of the UUID v4 event ID.

    UD5 spec invariant: result is always exactly 6 chars from event_id[-6:].
    """
    return event_id[-6:]
