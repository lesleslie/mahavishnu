"""Shared timezone-aware datetime helpers.

Python 3.14 deprecates :func:`datetime.datetime.utcnow` and emits a
``DeprecationWarning`` at import / call time. The deprecated helper also
returns a *naive* ``datetime`` object — comparing one against a tz-aware
field such as ``RepositoryMetadata.last_validated`` raises
``TypeError: can't compare offset-naive and offset-aware datetimes``.

The canonical replacement is :func:`datetime.datetime.now` with an
explicit ``tzinfo=UTC`` (or :class:`datetime.UTC`). This module exposes
that pattern as :func:`now_utc` so call sites stay consistent and so
the rationale lives in one place rather than scattered across every
file that needs a UTC timestamp.
"""

from __future__ import annotations

from datetime import UTC, datetime


def now_utc() -> datetime:
    """Return current UTC time as timezone-aware datetime.

    Use this instead of ``datetime.utcnow()`` — the latter is deprecated
    in Python 3.14 and returns a naive datetime that raises TypeError
    when compared with tz-aware fields.
    """
    return datetime.now(UTC)
