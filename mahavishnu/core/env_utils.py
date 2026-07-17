"""Environment variable utilities shared across the mahavishnu codebase.

Single source of truth for parsing env-var values that have a boolean
intent (e.g. opt-in feature flags). Extracted from the inline patterns in
``mahavishnu.core.events.bodai_subscriber._accept_legacy_wire`` and
``.claude.hooks.bodai-activity-post-tool-use._debug_enabled``.
"""
from __future__ import annotations

import os

_TRUTHY_STRINGS: frozenset[str] = frozenset({"1", "true", "yes", "on"})


def is_truthy_env(name: str, *, default: bool = False) -> bool:
    """Return True when the env var ``name`` is set to a truthy value.

    Treats the case-insensitive strings ``"1"``, ``"true"``, ``"yes"``,
    ``"on"`` as True. Any other value (including unset) returns
    ``default``.

    Examples:
        >>> import os
        >>> os.environ.pop("MAHAVISHNU_FAKE", None) and None
        >>> is_truthy_env("MAHAVISHNU_FAKE")  # default False
        False
        >>> os.environ["MAHAVISHNU_FAKE"] = "yes"
        >>> is_truthy_env("MAHAVISHNU_FAKE")
        True
        >>> os.environ["MAHAVISHNU_FAKE"] = "0"
        >>> is_truthy_env("MAHAVISHNU_FAKE")
        False
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUTHY_STRINGS


__all__ = ["is_truthy_env"]
