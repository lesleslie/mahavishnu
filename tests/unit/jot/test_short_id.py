from __future__ import annotations

import re

from hypothesis import given
from hypothesis import strategies as st

from mahavishnu.jot.short_id import short_id


def test_short_id_returns_first_6_chars() -> None:
    """short_id returns exactly the first 6 hex chars of the event ID."""
    full_id = "abcdef0123456789" * 2  # 32 chars
    assert len(full_id) == 32
    assert short_id(full_id) == "abcdef"


def test_short_id_deterministic() -> None:
    """Same input must always produce the same output."""
    full_id = "0123456789abcdef" * 2
    assert short_id(full_id) == short_id(full_id)


def test_short_id_for_typical_uuid_v4() -> None:
    """Real UUID v4 IDs produce valid 6-char output."""
    uuid_v4 = "a3f9c2b1e8d74f6a9c1b2e3f4a5b6c7d"
    assert short_id(uuid_v4) == "a3f9c2"
    assert re.match(r"^[0-9a-f]{6}$", short_id(uuid_v4))


def test_short_id_does_not_validate_input() -> None:
    """short_id does not validate input — it just slices. Garbage in, garbage out."""
    assert short_id("xyz") == "xyz"
    assert short_id("") == ""


@given(st.lists(st.uuids(), min_size=1000, max_size=1000))
def test_short_id_collision_rate_under_threshold(uuids: list) -> None:
    """For 1000 random UUIDs, 6-char short_id collisions must be < 5%."""
    short_ids = [short_id(str(u).replace("-", "")) for u in uuids]
    unique = len(set(short_ids))
    assert unique >= 950, f"Only {unique} unique short_ids out of 1000"
