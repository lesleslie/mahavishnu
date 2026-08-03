"""End-to-end: pool memory survives a Session-Buddy outage.

NOTE: This test requires a running Session-Buddy MCP server. Marked
`requires_network` so it skips in fast feedback mode.

To run manually:
    uv run pytest tests/e2e/mahavishnu_session_buddy/test_pool_memory_outage.py -v

The test exercises the writer path (outbox enabled, drain optional) to
prove rows accumulate while Session-Buddy is down. A separate manual run
with `MAHAVISHNU_OUTBOX_DRAIN=true` and a live Session-Buddy verifies
the recovery path; see the plan task 12 integration contract.

The DB lives in a tmp dir so the test does not accumulate state across
runs (the real WAL lives at ~/.mahavishnu/outbox.duckdb in production).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from mahavishnu.pools.outbox.writer import MemoryOutboxWriter

if TYPE_CHECKING:
    import pathlib

pytestmark = [pytest.mark.e2e, pytest.mark.requires_network]


async def test_pool_memory_survives_session_buddy_outage(tmp_path: pathlib.Path) -> None:
    os.environ["MAHAVISHNU_OUTBOX_ENABLED"] = "true"
    os.environ["MAHAVISHNU_OUTBOX_DRAIN"] = "true"

    writer = MemoryOutboxWriter(tmp_path / "outbox.duckdb")
    try:
        # Pre-condition: writer works.
        for i in range(10):
            await writer.enqueue(f"reflection:e2e-{i}", {"text": f"hello {i}"})
        assert await writer.pending_count() == 10
    finally:
        writer.close()