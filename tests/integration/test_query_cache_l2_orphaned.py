#!/usr/bin/env python3
"""Cross-component orphan test for Phase A cache consolidation.

Per spec §6.1 "Demonstrable by" gate: greps ``query_cache_l2`` across
session-buddy and akosha trees. Tasks 1, 2, 3 have removed the L2
DuckDB infrastructure:

- Task 1 (session-buddy ``23f7837b`` + ``ab798400``) rewrote
  QueryCacheManager to delegate to MemoryCacheAdapter and deleted the
  L2 DuckDB plumbing.
- Task 2 (session-buddy ``a1b30b1d``) deleted the duplicate
  CREATE TABLE block in ``reflection_adapter_oneiric.py`` and the
  ``"query_cache_l2"`` string in its reset_database() list.
- Task 3 (akosha ``c772de1`` + ``f1b1050``) introduced CacheManager
  over MemoryCacheAdapter without creating any ``query_cache_l2``
  references.

This CI gate catches any regression of those deletions.

REQ traceability: REQ-OSUB-A-001 (substitution), REQ-OSUB-A-002 (L2 removal).
"""

from __future__ import annotations

import subprocess

import pytest


@pytest.mark.req(["REQ-OSUB-A-001", "REQ-OSUB-A-002"])
def test_no_path_reads_or_writes_query_cache_l2() -> None:
    """Per spec §6.1 — no production path references query_cache_l2 after Phase A.

    Scoped to package source roots (session_buddy/session_buddy/ +
    akosha/akosha/). Tests, archived docs, and stale worktrees
    intentionally out of scope — those paths assert absence or
    document history, not the production state.
    """
    result = subprocess.run(
        ["grep", "-rn", "query_cache_l2",
         "/Users/les/Projects/session-buddy/session_buddy",
         "/Users/les/Projects/akosha/akosha"],
        capture_output=True, text=True,
    )
    assert result.stdout == "", f"query_cache_l2 still referenced:\n{result.stdout}"