"""UD5: short_id is the LAST 6 hex chars of the UUID v4 ID."""
from __future__ import annotations

from mahavishnu.jot.short_id import short_id


def test_short_id_returns_last_six_chars() -> None:
    """UD5 spec — random node field for cross-session stability."""
    # UUID v4 example: first 6 encode timestamp/version, last 6 are random node
    event_id = "f2c8a1b1e8d74f6a9c1b2e3f4a5b6c7d"
    assert short_id(event_id) == "a5b6c7d"[-6:]  # last 6 chars


def test_short_id_is_always_six_chars() -> None:
    """UD5 — invariant regardless of input length."""
    assert len(short_id("abcdef0123456789" * 2)) == 6
    assert len(short_id("abcdef")) == 6


def test_short_id_preserves_last_six_chars_only() -> None:
    """UD5 — change to first 6 chars would break this test."""
    event_id = "0123456789abcdef0123456789abcdef"
    assert short_id(event_id) == "abcdef"
