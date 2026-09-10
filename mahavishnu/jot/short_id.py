"""Short identifier for human-facing display of jot events.

The short_id is the first 6 hex chars of the 32-char UUID v4 event ID.
It's used only for capture echoes — the log stores the full ID.
"""
from __future__ import annotations


def short_id(event_id: str) -> str:
    """Return the first 6 characters of the event ID.

    No validation: garbage in, garbage out. Designed for human display only;
    real event resolution always uses the full 32-char ID stored in the log.

    See spec §"Short ID (echo only)".
    """
    return event_id[:6]
