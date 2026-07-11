"""Single source of truth for opensearchpy availability.

Do not re-probe in calling modules — see followup
2026-06-29-opensearch-diverged-flags.md.
"""

from __future__ import annotations

try:
    from opensearchpy import AsyncOpenSearch as _AsyncOpenSearch
except ImportError:
    _AsyncOpenSearch = None  # ty: ignore[invalid-assignment] # type: ignore[misc]

OPENSEARCH_AVAILABLE: bool = _AsyncOpenSearch is not None
